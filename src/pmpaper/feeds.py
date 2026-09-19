"""Live data recorders for Polymarket and a spot reference.

Network calls and parsing are deliberately separated. `fetch_*` does IO;
`parse_*` is pure. Only the parsers are unit-tested, because a test that
depends on a live exchange isn't a test — it's a weather report.

Public endpoints change without notice. If a parser starts returning None,
check the raw payload with `pmpaper probe` before assuming the harness broke.
"""

from __future__ import annotations

import json
import urllib.request

CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
BINANCE = "https://api.binance.com/api/v3/ticker/bookTicker?symbol=BTCUSDT"
COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"

UA = {"User-Agent": "pmpaper/0.1 (paper trading research)"}


def _get(url: str, timeout: float = 10.0) -> dict | list:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------------ parsers


def parse_book(payload: dict) -> tuple[float, float, float, float] | None:
    """Extract (bid, ask, bid_size, ask_size) from a CLOB book response.

    Polymarket returns bids ascending and asks descending, so the best bid
    is the LAST bid and the best ask is the LAST ask. Taking [0] from each
    is the classic mistake here and silently produces an inverted book.
    """
    if not isinstance(payload, dict):
        return None
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    if not bids or not asks:
        return None

    def best(levels, want_max: bool):
        pts = []
        for lv in levels:
            try:
                pts.append((float(lv["price"]), float(lv.get("size", 0))))
            except (KeyError, TypeError, ValueError):
                continue
        if not pts:
            return None
        return max(pts, key=lambda x: x[0]) if want_max else min(pts, key=lambda x: x[0])

    b, a = best(bids, True), best(asks, False)
    if b is None or a is None or a[0] <= b[0]:
        return None          # crossed or unusable book
    return (b[0], a[0], b[1], a[1])


def parse_spot(payload: dict) -> float | None:
    """Mid price from Binance bookTicker or Coinbase ticker."""
    if not isinstance(payload, dict):
        return None
    if "bidPrice" in payload and "askPrice" in payload:      # Binance
        try:
            return (float(payload["bidPrice"]) + float(payload["askPrice"])) / 2
        except (TypeError, ValueError):
            return None
    if "bid" in payload and "ask" in payload:                # Coinbase
        try:
            return (float(payload["bid"]) + float(payload["ask"])) / 2
        except (TypeError, ValueError):
            return None
    if "price" in payload:
        try:
            return float(payload["price"])
        except (TypeError, ValueError):
            return None
    return None


def parse_markets(payload, contains: str = "bitcoin") -> list[dict]:
    """Pick candidate up/down markets out of a Gamma markets listing."""
    items = payload if isinstance(payload, list) else payload.get("data", [])
    out = []
    needle = contains.lower()
    for m in items:
        if not isinstance(m, dict):
            continue
        text = f"{m.get('question','')} {m.get('slug','')}".lower()
        if needle not in text:
            continue
        raw = m.get("clobTokenIds")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = None
        if not raw:
            continue
        out.append({
            "question": m.get("question"),
            "slug": m.get("slug"),
            "end_date": m.get("endDate"),
            "yes_token": raw[0],
            "no_token": raw[1] if len(raw) > 1 else None,
        })
    return out


# ----------------------------------------------------------------- fetchers


def fetch_spot(source: str = "binance") -> float | None:
    return parse_spot(_get(BINANCE if source == "binance" else COINBASE))


def fetch_book(token_id: str) -> tuple[float, float, float, float] | None:
    return parse_book(_get(f"{CLOB}/book?token_id={token_id}"))


def fetch_markets(contains: str = "bitcoin", limit: int = 100) -> list[dict]:
    return parse_markets(
        _get(f"{GAMMA}/markets?closed=false&limit={limit}"), contains)
