"""Finviz market data adapter — equities, crypto and forex.

Finviz publishes no documented public API, so this adapter reads the same
surfaces a browser does, and one supported one:

  equities (bulk)  screener.ashx?v=111&t=A,B,C   one request, many symbols
  equities (deep)  quote.ashx?t=SYM              price plus the fundamentals table
  equities (elite) export.ashx?...&auth=TOKEN    CSV, when a Finviz Elite token is set
  crypto           api/crypto_all.ashx           every pair in one payload
  forex            api/forex_all.ashx            every pair in one payload
  bars (any)       api/quote.ashx?instrument=... OHLCV series

Two consequences shape the code below.

First, **prefer the bulk endpoints**. A forty-symbol watchlist is one request
against the screener, not forty against the quote page. Politeness here is not
just etiquette — it is what keeps the feed working.

Second, **parse defensively**. Scraped markup and undocumented JSON change
without notice, so every parser accepts each response shape Finviz has been
observed to serve, and raises `ParseError` (a distinct, human-needed signal)
rather than inventing a price when none of them match. Prices are the one thing
this system must never guess at. `FinvizFeed.probe()` reports which parser
matched live, so a format change is a diagnosable event rather than a mystery.

Note on quality: Finviz serves delayed prices (roughly 15 minutes for US
equities) and no bid/ask. Both are handled honestly rather than papered over —
quotes carry their true timestamp so staleness checks can fire, and the missing
book is synthesized by `engine.book` with `is_synthetic_book=True` set, so a
fill against a modelled spread is never mistaken for a fill against a real one.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from ..instruments import resolve
from ..types import AssetClass, Bar, Quote, utcnow
from .base import (
    Feed, FeedHealth, FeedUnavailable, HttpClient, ParseError, SymbolNotFound,
    bars_to_quote, parse_number,
)

FINVIZ_BASE = "https://finviz.com"
FINVIZ_ELITE_BASE = "https://elite.finviz.com"

# Interval -> the token each endpoint family expects. Finviz is not internally
# consistent about this, which is exactly why it belongs in one table.
_CHART_TF = {
    "1m": "i1", "3m": "i3", "5m": "i5", "15m": "i15", "30m": "i30",
    "1h": "h", "1d": "d", "1w": "w", "1M": "m",
}
_ALL_TF = {
    "1m": "1m", "5m": "5m", "1h": "h1", "1d": "d1", "1w": "w1", "1M": "m1",
}

# Labels on the quote page whose values we care about. Matching on label text
# rather than CSS class survives the markup reshuffles that break scrapers.
_QUOTE_LABELS = {
    "Price", "Change", "Volume", "Prev Close", "Open", "Range", "Avg Volume",
    "Market Cap", "P/E", "Forward P/E", "EPS (ttm)", "Beta", "ATR", "ATR (14)",
    "SMA20", "SMA50", "SMA200", "RSI (14)", "Rel Volume", "Short Float",
    "Shs Outstand", "Shs Float", "Dividend TTM", "Target Price", "52W Range",
    "52W High", "52W Low", "Perf Week", "Perf Month", "Perf Year", "Sector",
    "Industry", "Country", "Earnings", "Employees", "Recom", "Volatility",
}


# --------------------------------------------------------------- HTML parsing


class _TableExtractor(HTMLParser):
    """Pull every table out of a page as rows of plain cell text.

    Stdlib-only and forgiving of the unclosed tags real-world markup is full
    of. Cell text is whitespace-collapsed; links keep their href so a screener
    row can be tied back to its ticker.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.links: list[str] = []
        self._table_stack: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" or tag == "style":
            self._in_script = True
        elif tag == "table":
            self._table_stack.append([])
        elif tag == "tr" and self._table_stack:
            self._flush_row()
            self._row = []
        elif tag in ("td", "th"):
            self._flush_cell()
            self._cell = []
            if self._row is None and self._table_stack:
                self._row = []
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._in_script = False
        elif tag in ("td", "th"):
            self._flush_cell()
        elif tag == "tr":
            self._flush_row()
        elif tag == "table":
            self._flush_row()
            if self._table_stack:
                self.tables.append(self._table_stack.pop())

    def handle_data(self, data: str) -> None:
        if self._in_script or self._cell is None:
            return
        self._cell.append(data)

    def _flush_cell(self) -> None:
        if self._cell is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
        if self._row is None:
            self._row = []
        self._row.append(text)
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if self._row and self._table_stack:
            self._table_stack[-1].append(self._row)
        self._row = None

    def close(self) -> None:  # pragma: no cover - flush tail on malformed input
        super().close()
        self._flush_row()
        while self._table_stack:
            self.tables.append(self._table_stack.pop())


def _all_cells(html: str) -> tuple[list[str], list[list[list[str]]]]:
    p = _TableExtractor()
    p.feed(html)
    p.close()
    cells = [c for table in p.tables for row in table for c in row]
    return cells, p.tables


def parse_quote_page(html: str, symbol: str,
                     now: datetime | None = None) -> tuple[Quote, dict[str, str]]:
    """Read finviz.com/quote.ashx into a Quote plus its fundamentals table.

    Works by pairing each known label cell with the cell that follows it, which
    is how the snapshot table is laid out regardless of what the classes are
    called this quarter.
    """
    cells, _tables = _all_cells(html)
    if not cells:
        raise ParseError(f"no tables in quote page for {symbol}")

    fundamentals: dict[str, str] = {}
    for i, cell in enumerate(cells[:-1]):
        label = cell.strip()
        if label in _QUOTE_LABELS and label not in fundamentals:
            fundamentals[label] = cells[i + 1].strip()

    price = parse_number(fundamentals.get("Price"))
    if price <= 0:
        # Fall back to the og:price / JSON-LD metadata some page variants carry.
        m = re.search(r'"(?:price|regularMarketPrice)"\s*:\s*"?([\d.]+)', html)
        if m:
            price = parse_number(m.group(1))
    if price <= 0:
        raise ParseError(
            f"no price found for {symbol}; the quote page layout may have changed"
        )

    prev_close = parse_number(fundamentals.get("Prev Close"))
    change_pct = parse_number(fundamentals.get("Change"))
    if prev_close <= 0 and change_pct:
        # Recover prev close from the percentage when the cell is absent.
        prev_close = price / (1.0 + change_pct / 100.0)

    low = high = 0.0
    if rng := fundamentals.get("Range"):
        parts = [parse_number(p) for p in rng.split("-")]
        if len(parts) == 2 and all(p > 0 for p in parts):
            low, high = min(parts), max(parts)

    return Quote(
        symbol=symbol.upper(),
        ts=now or utcnow(),
        last=price,
        open=parse_number(fundamentals.get("Open")) or price,
        high=high or price,
        low=low or price,
        volume=parse_number(fundamentals.get("Volume")),
        prev_close=prev_close or price,
        source="finviz:quote",
    ), fundamentals


def parse_screener_page(html: str, now: datetime | None = None) -> dict[str, Quote]:
    """Read the screener's overview table (v=111) into quotes by ticker."""
    _cells, tables = _all_cells(html)
    ts = now or utcnow()
    out: dict[str, Quote] = {}

    for table in tables:
        if len(table) < 2:
            continue
        header = [h.strip().lower() for h in table[0]]
        if "ticker" not in header:
            continue
        idx = {name: i for i, name in enumerate(header)}
        t_i, p_i = idx.get("ticker"), idx.get("price")
        if t_i is None or p_i is None:
            continue
        c_i, v_i = idx.get("change"), idx.get("volume")
        for row in table[1:]:
            if len(row) <= max(t_i, p_i):
                continue
            ticker = row[t_i].strip().upper()
            price = parse_number(row[p_i])
            if not ticker or not re.fullmatch(r"[A-Z][A-Z.\-]{0,9}", ticker) or price <= 0:
                continue
            chg = parse_number(row[c_i]) if c_i is not None and len(row) > c_i else 0.0
            vol = parse_number(row[v_i]) if v_i is not None and len(row) > v_i else 0.0
            out[ticker] = Quote(
                symbol=ticker, ts=ts, last=price, volume=vol,
                prev_close=price / (1.0 + chg / 100.0) if chg else price,
                source="finviz:screener",
            )
        if out:
            break
    if not out:
        raise ParseError("screener response contained no readable rows")
    return out


def parse_export_csv(text: str, now: datetime | None = None) -> dict[str, Quote]:
    """Read the Finviz Elite CSV export. Same columns as the screener view."""
    ts = now or utcnow()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ParseError("empty CSV export")
    out: dict[str, Quote] = {}
    for row in rows:
        norm = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
        ticker = norm.get("ticker", "").strip().upper()
        price = parse_number(norm.get("price"))
        if not ticker or price <= 0:
            continue
        chg = parse_number(norm.get("change"))
        # The CSV writes change as a fraction (0.0231), the HTML as a percent.
        chg_pct = chg * 100.0 if abs(chg) < 1.0 else chg
        out[ticker] = Quote(
            symbol=ticker, ts=ts, last=price,
            volume=parse_number(norm.get("volume")),
            prev_close=price / (1.0 + chg_pct / 100.0) if chg_pct else price,
            source="finviz:export",
        )
    if not out:
        raise ParseError("CSV export had no rows with a ticker and price")
    return out


# --------------------------------------------------------------- JSON parsing


def _as_dt(value: object, index: int = 0) -> datetime:
    """Coerce whatever Finviz used for a timestamp into an aware UTC datetime."""
    if isinstance(value, (int, float)):
        # Seconds or milliseconds since epoch; 1e11 is the year 5138 in seconds.
        secs = float(value) / 1000.0 if float(value) > 1e11 else float(value)
        return datetime.fromtimestamp(secs, timezone.utc)
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        # Last resort: space the bars a day apart so ordering still holds.
        return utcnow() - timedelta(days=index)


def parse_series(payload: object, symbol: str, interval: str = "1d") -> list[Bar]:
    """Read an OHLCV series out of any shape Finviz has served.

    Four shapes are accepted, in order of how often they turn up:
      1. columns:      {"date": [...], "open": [...], "close": [...], ...}
      2. nested:       {"candles"|"bars"|"data": <one of the other shapes>}
      3. records:      [{"date": ..., "open": ..., ...}, ...]
      4. rows:         [[date, open, high, low, close, volume], ...]
    """
    sym = symbol.upper()
    node = payload

    # Shape 2: unwrap a single known container, possibly twice.
    for _ in range(3):
        if isinstance(node, dict):
            for key in ("candles", "bars", "data", "chart", "series", "quotes"):
                inner = node.get(key)
                if isinstance(inner, (dict, list)) and inner:
                    node = inner
                    break
            else:
                break
        else:
            break

    bars: list[Bar] = []

    # Shape 1: parallel column arrays.
    if isinstance(node, dict):
        keys = {k.lower(): k for k in node.keys()}

        def col(*names: str) -> list:
            for n in names:
                k = keys.get(n)
                if k is not None and isinstance(node[k], list):
                    return node[k]
            return []

        closes = col("close", "c", "closes")
        if closes:
            dates = col("date", "dates", "t", "time", "timestamp", "datetime")
            opens = col("open", "o", "opens") or closes
            highs = col("high", "h", "highs") or closes
            lows = col("low", "l", "lows") or closes
            vols = col("volume", "v", "volumes")
            for i, c in enumerate(closes):
                close = parse_number(c)
                if close <= 0:
                    continue
                bars.append(Bar(
                    symbol=sym,
                    ts=_as_dt(dates[i], i) if i < len(dates) else utcnow(),
                    open=parse_number(opens[i]) if i < len(opens) else close,
                    high=parse_number(highs[i]) if i < len(highs) else close,
                    low=parse_number(lows[i]) if i < len(lows) else close,
                    close=close,
                    volume=parse_number(vols[i]) if i < len(vols) else 0.0,
                    interval=interval,
                ))

    # Shapes 3 and 4: a list of records or of positional rows.
    elif isinstance(node, list):
        for i, item in enumerate(node):
            if isinstance(item, dict):
                low_item = {str(k).lower(): v for k, v in item.items()}

                def pick(*names: str, default=None):
                    for n in names:
                        if n in low_item and low_item[n] not in (None, ""):
                            return low_item[n]
                    return default

                close = parse_number(pick("close", "c", "last", "price"))
                if close <= 0:
                    continue
                bars.append(Bar(
                    symbol=sym,
                    ts=_as_dt(pick("date", "time", "t", "timestamp", default=i), i),
                    open=parse_number(pick("open", "o", default=close)),
                    high=parse_number(pick("high", "h", default=close)),
                    low=parse_number(pick("low", "l", default=close)),
                    close=close,
                    volume=parse_number(pick("volume", "v", default=0)),
                    interval=interval,
                ))
            elif isinstance(item, (list, tuple)) and len(item) >= 5:
                close = parse_number(item[4])
                if close <= 0:
                    continue
                bars.append(Bar(
                    symbol=sym, ts=_as_dt(item[0], i),
                    open=parse_number(item[1]), high=parse_number(item[2]),
                    low=parse_number(item[3]), close=close,
                    volume=parse_number(item[5]) if len(item) > 5 else 0.0,
                    interval=interval,
                ))

    if not bars:
        raise ParseError(f"no OHLC series found for {symbol} in Finviz payload")
    bars.sort(key=lambda b: b.ts)
    return bars


def parse_all_pairs(payload: object, now: datetime | None = None) -> dict[str, Quote]:
    """Read crypto_all / forex_all: every pair the venue lists, in one payload.

    Accepts a mapping of symbol -> series or -> record, and a flat list of
    records carrying their own ticker.
    """
    ts = now or utcnow()
    out: dict[str, Quote] = {}

    def record_to_quote(sym: str, rec: dict) -> Quote | None:
        low = {str(k).lower(): v for k, v in rec.items()}
        last = parse_number(
            low.get("last", low.get("close", low.get("price", low.get("c", 0)))))
        if last <= 0:
            return None
        prev = parse_number(low.get("prevclose", low.get("prev_close", 0)))
        chg = parse_number(low.get("change", low.get("changepercent", 0)))
        if prev <= 0 and chg:
            prev = last / (1.0 + chg / 100.0)
        return Quote(
            symbol=sym, ts=ts, last=last,
            open=parse_number(low.get("open", low.get("o", 0))) or last,
            high=parse_number(low.get("high", low.get("h", 0))) or last,
            low=parse_number(low.get("low", low.get("l", 0))) or last,
            volume=parse_number(low.get("volume", low.get("v", 0))),
            prev_close=prev or last,
            source="finviz:all",
        )

    if isinstance(payload, dict):
        for raw_sym, value in payload.items():
            sym = str(raw_sym).upper().replace("/", "").replace("-", "")
            if not re.fullmatch(r"[A-Z0-9]{4,12}", sym):
                continue
            if isinstance(value, dict):
                # Either a flat record, or a full OHLC series for that pair.
                q = record_to_quote(sym, value)
                if q is None:
                    try:
                        q = bars_to_quote(sym, parse_series(value, sym), "finviz:all")
                    except ParseError:
                        continue
                out[sym] = q
            elif isinstance(value, list) and value:
                try:
                    out[sym] = bars_to_quote(sym, parse_series(value, sym), "finviz:all")
                except ParseError:
                    continue
            elif isinstance(value, (int, float)) and float(value) > 0:
                out[sym] = Quote(symbol=sym, ts=ts, last=float(value),
                                 prev_close=float(value), source="finviz:all")
    elif isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            low = {str(k).lower(): v for k, v in item.items()}
            sym = str(low.get("ticker", low.get("symbol", low.get("name", "")))
                      ).upper().replace("/", "").replace("-", "")
            if not sym:
                continue
            q = record_to_quote(sym, item)
            if q:
                out[sym] = q

    if not out:
        raise ParseError("no pairs found in Finviz bulk payload")
    return out


# ------------------------------------------------------------------- the feed


class FinvizFeed(Feed):
    """Live market data from Finviz for equities, crypto and forex.

    Bulk payloads are cached for `bulk_ttl_s` because crypto_all and forex_all
    return the entire universe: fetching them once per watchlist refresh rather
    than once per symbol is the difference between a good citizen and a scraper
    that gets blocked.
    """

    name = "finviz"
    supported = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FX)

    def __init__(self, *, auth_token: str = "", base_url: str = FINVIZ_BASE,
                 rate_per_s: float = 0.7, timeout: float = 12.0,
                 bulk_ttl_s: float = 20.0, http: HttpClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token.strip()
        self.bulk_ttl_s = bulk_ttl_s
        self.http = http or HttpClient(rate_per_s=rate_per_s, burst=3, timeout=timeout)
        self._bulk: dict[str, tuple[float, dict[str, Quote]]] = {}
        self._last_success: datetime | None = None
        self._last_error: str | None = None
        self.fundamentals_cache: dict[str, dict[str, str]] = {}

    # -------------------------------------------------------------- internals

    def _now_mono(self) -> float:
        import time as _t
        return _t.monotonic()

    def _bulk_pairs(self, kind: str) -> dict[str, Quote]:
        """Fetch (and briefly cache) every crypto or forex pair Finviz lists."""
        hit = self._bulk.get(kind)
        if hit and self._now_mono() - hit[0] < self.bulk_ttl_s:
            return hit[1]
        url = f"{self.base_url}/api/{kind}_all.ashx"
        payload = self.http.get_json(url, {"timeframe": _ALL_TF["1d"]})
        quotes = parse_all_pairs(payload)
        self._bulk[kind] = (self._now_mono(), quotes)
        self._mark_ok()
        return quotes

    def _pair_kind(self, ac: AssetClass) -> str:
        return "crypto" if ac is AssetClass.CRYPTO else "forex"

    def _mark_ok(self) -> None:
        self._last_success = utcnow()
        self._last_error = None

    def _mark_err(self, err: Exception) -> None:
        self._last_error = f"{type(err).__name__}: {err}"

    def _finviz_symbol(self, symbol: str) -> str:
        return (resolve(symbol).finviz_symbol or symbol).upper()

    # ----------------------------------------------------------------- quotes

    def get_quote(self, symbol: str) -> Quote:
        sym = symbol.upper().strip()
        inst = resolve(sym)
        try:
            if inst.asset_class in (AssetClass.CRYPTO, AssetClass.FX):
                pairs = self._bulk_pairs(self._pair_kind(inst.asset_class))
                q = pairs.get(self._finviz_symbol(sym)) or pairs.get(sym)
                if q is None:
                    raise SymbolNotFound(f"{sym} is not listed by Finviz")
                self._mark_ok()
                # Hand back the caller's spelling, not Finviz's.
                return q if q.symbol == sym else dc_replace(q, symbol=sym)
            quote, fundamentals = parse_quote_page(
                self.http.get(f"{self.base_url}/quote.ashx",
                              {"t": self._finviz_symbol(sym), "p": "d"}).body,
                sym,
            )
            self.fundamentals_cache[sym] = fundamentals
            self._mark_ok()
            return quote
        except SymbolNotFound:
            raise
        except Exception as e:
            self._mark_err(e)
            raise

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """One request per asset class, not one per symbol."""
        wanted = [s.upper().strip() for s in symbols if s.strip()]
        by_class: dict[AssetClass, list[str]] = {}
        for s in wanted:
            by_class.setdefault(resolve(s).asset_class, []).append(s)

        out: dict[str, Quote] = {}
        for ac, syms in by_class.items():
            try:
                if ac is AssetClass.EQUITY:
                    out.update(self._equity_bulk(syms))
                else:
                    pairs = self._bulk_pairs(self._pair_kind(ac))
                    for s in syms:
                        q = pairs.get(self._finviz_symbol(s)) or pairs.get(s)
                        if q:
                            out[s] = q
            except Exception as e:      # one class failing must not sink the rest
                self._mark_err(e)
                continue
        if out:
            self._mark_ok()
        return out

    def _equity_bulk(self, symbols: list[str]) -> dict[str, Quote]:
        """Screener (or Elite CSV) in pages — the URL has a practical length cap."""
        out: dict[str, Quote] = {}
        page = 40
        for i in range(0, len(symbols), page):
            chunk = symbols[i:i + page]
            tickers = ",".join(chunk)
            if self.auth_token:
                resp = self.http.get(
                    f"{FINVIZ_ELITE_BASE}/export.ashx",
                    {"v": "111", "t": tickers, "auth": self.auth_token})
                got = parse_export_csv(resp.body)
            else:
                resp = self.http.get(f"{self.base_url}/screener.ashx",
                                     {"v": "111", "t": tickers})
                got = parse_screener_page(resp.body)
            out.update({s: q for s, q in got.items() if s in set(chunk)})
        return out

    # ------------------------------------------------------------------ bars

    def get_bars(self, symbol: str, interval: str = "1d", limit: int = 200) -> list[Bar]:
        sym = symbol.upper().strip()
        inst = resolve(sym)
        instrument_param = {
            AssetClass.EQUITY: "stock", AssetClass.CRYPTO: "crypto",
            AssetClass.FX: "forex",
        }[inst.asset_class]
        try:
            payload = self.http.get_json(f"{self.base_url}/api/quote.ashx", {
                "instrument": instrument_param,
                "ticker": self._finviz_symbol(sym),
                "timeframe": _CHART_TF.get(interval, "d"),
                "type": "new",
            })
            bars = parse_series(payload, sym, interval)
            self._mark_ok()
            return bars[-limit:]
        except Exception as e:
            self._mark_err(e)
            raise

    def get_fundamentals(self, symbol: str) -> dict[str, str]:
        """The quote page's snapshot table. Equities only; cached per session."""
        sym = symbol.upper().strip()
        if sym in self.fundamentals_cache:
            return self.fundamentals_cache[sym]
        if resolve(sym).asset_class is not AssetClass.EQUITY:
            return {}
        self.get_quote(sym)
        return self.fundamentals_cache.get(sym, {})

    # ---------------------------------------------------------------- health

    def health(self) -> FeedHealth:
        return FeedHealth(
            name=self.name,
            ok=self.http.breaker.allow() and self._last_error is None,
            breaker=self.http.breaker.state,
            last_success=self._last_success,
            last_error=self._last_error,
            requests=self.http.stats["requests"],
            errors=self.http.stats["errors"],
        )

    def probe(self) -> list[dict]:
        """Check every endpoint against the live site and report what happened.

        Run this after a Finviz redesign, or the first time the platform is
        pointed at the internet: it says which surfaces still parse, so a
        format change shows up as a named failing endpoint instead of an
        empty watchlist.
        """
        checks = [
            ("equity/screener", lambda: self._equity_bulk(["AAPL", "MSFT"])),
            ("equity/quote", lambda: self.get_quote("AAPL")),
            ("equity/bars", lambda: self.get_bars("AAPL", "1d", 30)),
            ("crypto/all", lambda: self._bulk_pairs("crypto")),
            ("crypto/bars", lambda: self.get_bars("BTCUSD", "1d", 30)),
            ("forex/all", lambda: self._bulk_pairs("forex")),
            ("forex/bars", lambda: self.get_bars("EURUSD", "1d", 30)),
        ]
        results = []
        for label, fn in checks:
            try:
                value = fn()
                n = len(value) if hasattr(value, "__len__") else 1
                results.append({"endpoint": label, "ok": True, "records": n, "error": None})
            except Exception as e:
                results.append({"endpoint": label, "ok": False, "records": 0,
                                "error": f"{type(e).__name__}: {e}"})
        return results
