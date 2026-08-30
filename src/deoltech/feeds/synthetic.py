"""Deterministic simulated market data.

This exists for three reasons, in order of importance:

1. **Tests must not touch the network.** A test suite that depends on a vendor
   being up is not a test suite.
2. **The platform must degrade visibly, not silently.** When Finviz is
   unreachable — an outage, a rate limit, an egress policy — the composite feed
   falls through to here and flags `degraded`, rather than serving a stale price
   as if it were live.
3. **Demos and training need a market that behaves like one** without spending
   a vendor's bandwidth.

The prices are a *pure function of (symbol, timestamp)*: no accumulated state,
no RNG object whose sequence depends on call order. Restart the process and
BTCUSD is at the same price it was; two workers serving the same request agree.
That is what makes a simulator usable as a fallback rather than a toy — a
random walk held in memory would teleport on every restart.

The generator is fractional Brownian motion in log-price space: several octaves
of smoothly-interpolated value noise summed with halving amplitude. It is O(1)
at any timestamp, seekable, and produces the trends, reversals and volatility
clustering that make chart-reading practice meaningful. It is *not* a claim
about real market dynamics, and nothing here should be read as a forecast.
"""

from __future__ import annotations

import math
import zlib
from datetime import datetime, timedelta, timezone

from ..clock import Session, session_for
from ..instruments import AssetClass, resolve
from ..types import Bar, Quote, utcnow
from .base import Feed, FeedHealth, SymbolNotFound

# Realistic anchors so the demo does not open with AAPL at $3.71. Anything not
# listed gets a stable price derived from its symbol.
ANCHORS: dict[str, float] = {
    "AAPL": 217.90, "MSFT": 405.10, "NVDA": 118.40, "AMZN": 178.20,
    "GOOGL": 163.80, "META": 512.30, "TSLA": 221.60, "SPY": 552.40,
    "QQQ": 468.90, "IWM": 213.70, "AMD": 148.20, "NFLX": 678.40,
    "JPM": 213.50, "XOM": 114.80, "GME": 22.40,
    "BTCUSD": 64210.00, "ETHUSD": 3410.00, "SOLUSD": 148.20,
    "XRPUSD": 0.5820, "DOGEUSD": 0.10420, "ADAUSD": 0.3810,
    "AVAXUSD": 26.400, "LINKUSD": 11.320,
    "EURUSD": 1.08520, "GBPUSD": 1.27340, "USDJPY": 147.220,
    "USDCHF": 0.88140, "AUDUSD": 0.66820, "USDCAD": 1.36740,
    "NZDUSD": 0.61230, "EURGBP": 0.85210, "EURJPY": 159.740,
    "GBPJPY": 187.480, "AUDJPY": 98.380, "EURCHF": 0.95620,
    "USDMXN": 18.7420, "USDZAR": 18.1240, "USDTRY": 33.4120,
}

# Annualized volatility by asset class — the realistic order of magnitude.
CLASS_VOL = {
    AssetClass.EQUITY: 0.28,
    AssetClass.CRYPTO: 0.65,
    AssetClass.FX: 0.08,
}

_SECONDS_PER_YEAR = 365.25 * 24 * 3600


def _seed(symbol: str) -> int:
    """Stable across processes — Python's str hash is randomized per run."""
    return zlib.crc32(symbol.upper().encode()) & 0xFFFFFFFF


def _hash01(seed: int, n: int) -> float:
    """Integer hash to [0,1). SplitMix64's mixing function, 64-bit masked."""
    x = (seed * 0x9E3779B97F4A7C15 + n * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 30
    x = (x * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 27
    x = (x * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 31
    return x / 0xFFFFFFFFFFFFFFFF


def _value_noise(seed: int, x: float) -> float:
    """Smoothly interpolated noise in [0,1). Smoothstep keeps the path C1."""
    i = math.floor(x)
    f = x - i
    a, b = _hash01(seed, i), _hash01(seed, i + 1)
    u = f * f * (3.0 - 2.0 * f)
    return a + (b - a) * u


def _fbm(seed: int, x: float, octaves: int = 6) -> float:
    """Fractional Brownian motion in [-1, 1]. Low octaves trend, high ones chop."""
    total = 0.0
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for k in range(octaves):
        total += amp * (_value_noise(seed + k * 7919, x * freq) - 0.5) * 2.0
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm if norm else 0.0


def _session_vol_multiplier(asset_class: AssetClass, ts: datetime) -> float:
    """Equities are loudest at the open and the close; crypto/FX are flatter."""
    if asset_class is not AssetClass.EQUITY:
        return 1.0
    sess = session_for("equity", ts)
    if sess is Session.CLOSED:
        return 0.15
    if sess in (Session.PREMARKET, Session.AFTERHOURS):
        return 0.45
    from ..clock import to_et
    minutes = to_et(ts).hour * 60 + to_et(ts).minute - (9 * 60 + 30)
    if minutes < 30:
        return 1.9           # opening auction and the rush after it
    if minutes > 330:
        return 1.6           # closing 30 minutes
    return 1.0


class SyntheticFeed(Feed):
    """A market that always answers, priced as a pure function of time."""

    name = "synthetic"
    supported = (AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FX)

    def __init__(self, *, seed: int = 0, vol_scale: float = 1.0,
                 anchors: dict[str, float] | None = None):
        self.seed = seed
        self.vol_scale = vol_scale
        self.anchors = {**ANCHORS, **(anchors or {})}

    # ------------------------------------------------------------- internals

    def anchor(self, symbol: str) -> float:
        """A stable, plausible starting price for any symbol."""
        s = symbol.upper()
        if s in self.anchors:
            return self.anchors[s]
        inst = resolve(s)
        r = _hash01(_seed(s), 1)
        if inst.asset_class is AssetClass.FX:
            base = 0.6 + r * 1.0 if inst.quote_ccy != "JPY" else 90.0 + r * 80.0
        elif inst.asset_class is AssetClass.CRYPTO:
            base = math.exp(math.log(0.5) + r * (math.log(3000.0) - math.log(0.5)))
        else:
            base = 8.0 + r * 380.0
        return inst.round_price(base)

    def _log_path(self, symbol: str, ts: datetime) -> float:
        """Cumulative log return from the anchor at time `ts`."""
        inst = resolve(symbol)
        sd = (_seed(symbol) + self.seed) & 0xFFFFFFFF
        t = ts.timestamp()

        vol = CLASS_VOL[inst.asset_class] * self.vol_scale
        # Three timescales: a multi-month drift, a multi-day swing, and the
        # intraday chop. Summing them is what produces trends that persist and
        # reversals that do not look periodic.
        slow = _fbm(sd, t / (86400.0 * 45.0), 4) * vol * math.sqrt(0.75)
        mid = _fbm(sd + 101, t / (86400.0 * 3.0), 5) * vol * math.sqrt(0.08)
        fast = _fbm(sd + 977, t / 900.0, 6) * vol * math.sqrt(0.0015)
        fast *= _session_vol_multiplier(inst.asset_class, ts)
        return slow + mid + fast

    def price_at(self, symbol: str, ts: datetime) -> float:
        inst = resolve(symbol)
        px = self.anchor(symbol) * math.exp(self._log_path(symbol, ts))
        return max(inst.tick_size, inst.round_price(px))

    def _volume_at(self, symbol: str, ts: datetime, span_s: float) -> float:
        inst = resolve(symbol)
        daily = inst.adv
        frac = min(1.0, span_s / 86400.0)
        noise = 0.55 + _hash01(_seed(symbol) + 31, int(ts.timestamp() // 3600)) * 0.9
        return round(daily * frac * noise * _session_vol_multiplier(inst.asset_class, ts))

    # ---------------------------------------------------------------- quotes

    def get_quote(self, symbol: str) -> Quote:
        sym = symbol.upper().strip()
        if not sym:
            raise SymbolNotFound("empty symbol")
        inst = resolve(sym)
        now = utcnow()
        last = self.price_at(sym, now)
        prev_close = self.price_at(sym, now - timedelta(days=1))
        day_open = self.price_at(sym, now - timedelta(hours=8))
        # Sample the session for a true high/low rather than guessing a band.
        samples = [self.price_at(sym, now - timedelta(minutes=30 * k)) for k in range(0, 14)]
        return Quote(
            symbol=sym, ts=now, last=last,
            open=day_open, high=max(samples), low=min(samples),
            volume=self._volume_at(sym, now, 8 * 3600),
            prev_close=prev_close, source="synthetic",
        )

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        return {s.upper(): self.get_quote(s) for s in symbols if s.strip()}

    # ------------------------------------------------------------------ bars

    def _make_bar(self, sym: str, inst, open_ts: datetime, close_ts: datetime,
                  interval: str) -> Bar:
        """Sample the price path across one bar to get a real high and low.

        Wicks come from actually looking inside the bar, not from padding the
        body by a percentage — which matters, because stop orders in the
        backtester are triggered by exactly these highs and lows.
        """
        span = (close_ts - open_ts).total_seconds()
        o = self.price_at(sym, open_ts)
        c = self.price_at(sym, close_ts)
        inner = [self.price_at(sym, open_ts + timedelta(seconds=span * f / 8.0))
                 for f in range(1, 8)]
        hi, lo = max([o, c] + inner), min([o, c] + inner)
        return Bar(
            symbol=sym, ts=close_ts,
            open=inst.round_price(o), high=inst.round_price(hi),
            low=inst.round_price(lo), close=inst.round_price(c),
            volume=self._volume_at(sym, close_ts, span), interval=interval,
        )

    def get_bars(self, symbol: str, interval: str = "1d", limit: int = 200) -> list[Bar]:
        sym = symbol.upper().strip()
        inst = resolve(sym)
        now = utcnow()

        # Equity dailies follow the exchange calendar: one bar per business
        # day, stamped at that day's actual close (13:00 ET on a half day).
        # Snapping to a 24h UTC grid instead would silently invent Saturday
        # candles and mis-time every close.
        if inst.asset_class is AssetClass.EQUITY and interval == "1d":
            from ..clock import ET, REGULAR_OPEN, close_time_for, is_business_day, to_et
            day = to_et(now).date()
            days: list = []
            guard = 0
            while len(days) < limit and guard < limit * 3 + 30:
                if is_business_day(day):
                    days.append(day)
                day -= timedelta(days=1)
                guard += 1
            days.reverse()
            out = []
            for d in days:
                open_ts = datetime.combine(d, REGULAR_OPEN, ET).astimezone(timezone.utc)
                close_ts = datetime.combine(d, close_time_for(d), ET).astimezone(timezone.utc)
                if close_ts > now:
                    close_ts = now      # today's bar is still forming
                if close_ts <= open_ts:
                    continue
                out.append(self._make_bar(sym, inst, open_ts, close_ts, interval))
            return out

        step = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
        }.get(interval, 86400)
        # Snap to the bar grid so repeated calls return identical timestamps.
        end = datetime.fromtimestamp(
            math.floor(now.timestamp() / step) * step, timezone.utc)

        bars: list[Bar] = []
        # Over-scan, because closed sessions are dropped rather than emitted.
        scan = limit * 3 if inst.asset_class is AssetClass.EQUITY else limit
        for k in range(scan, 0, -1):
            close_ts = end - timedelta(seconds=step * (k - 1))
            open_ts = close_ts - timedelta(seconds=step)
            if inst.asset_class is AssetClass.EQUITY:
                # Intraday: only bars inside a tradeable session exist.
                if session_for("equity", open_ts) is Session.CLOSED:
                    continue
            bars.append(self._make_bar(sym, inst, open_ts, close_ts, interval))
        return bars[-limit:]

    def health(self) -> FeedHealth:
        return FeedHealth(name=self.name, ok=True, breaker="closed",
                          last_success=utcnow())
