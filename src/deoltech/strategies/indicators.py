"""Technical indicators.

Pure functions over a list of floats, returning a list aligned to the input
with `None` in the warm-up region. That alignment is deliberate: an indicator
that silently returns a shorter list is how off-by-one lookahead bugs get into
a backtest, because index `i` of the signal stops meaning bar `i`.
"""

from __future__ import annotations

import statistics
from ..types import Bar

Series = list[float]
Signal = list[float | None]


def sma(values: Series, period: int) -> Signal:
    out: Signal = [None] * len(values)
    if period <= 0:
        return out
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: Series, period: int) -> Signal:
    out: Signal = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = statistics.fmean(values[:period])
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def stdev(values: Series, period: int) -> Signal:
    out: Signal = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = statistics.pstdev(values[i - period + 1:i + 1])
    return out


def zscore(values: Series, period: int) -> Signal:
    m, s = sma(values, period), stdev(values, period)
    return [None if m[i] is None or not s[i] else (values[i] - m[i]) / s[i]
            for i in range(len(values))]


def rsi(values: Series, period: int = 14) -> Signal:
    """Wilder's RSI. Smoothed, not a simple average of gains and losses."""
    out: Signal = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(0.0, d)
        losses += max(0.0, -d)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(0.0, d)) / period
        avg_loss = (avg_loss * (period - 1) + max(0.0, -d)) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def true_range(bars: list[Bar]) -> Series:
    out = []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(b.high - b.low)
        else:
            pc = bars[i - 1].close
            out.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
    return out


def atr(bars: list[Bar], period: int = 14) -> Signal:
    """Average True Range — the position-sizing input that matters most.

    Sizing by ATR rather than by share count is what makes risk comparable
    across a $5 stock and a $60,000 coin.
    """
    tr = true_range(bars)
    out: Signal = [None] * len(bars)
    if len(tr) < period:
        return out
    prev = statistics.fmean(tr[:period])
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def donchian(bars: list[Bar], period: int = 20
             ) -> tuple[Signal, Signal]:
    """Rolling high/low channel, EXCLUDING the current bar.

    Excluding it is the whole point: comparing today's close to a channel that
    already contains today's high means the breakout can never be detected
    until it has already happened. This is lookahead in its most common form.
    """
    highs: Signal = [None] * len(bars)
    lows: Signal = [None] * len(bars)
    for i in range(period, len(bars)):
        window = bars[i - period:i]
        highs[i] = max(b.high for b in window)
        lows[i] = min(b.low for b in window)
    return highs, lows


def bollinger(values: Series, period: int = 20, mult: float = 2.0
              ) -> tuple[Signal, Signal, Signal]:
    mid = sma(values, period)
    sd = stdev(values, period)
    upper = [None if mid[i] is None or sd[i] is None else mid[i] + mult * sd[i]
             for i in range(len(values))]
    lower = [None if mid[i] is None or sd[i] is None else mid[i] - mult * sd[i]
             for i in range(len(values))]
    return upper, mid, lower


def crossed_above(a: Signal, b: Signal, i: int) -> bool:
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return a[i - 1] <= b[i - 1] and a[i] > b[i]


def crossed_below(a: Signal, b: Signal, i: int) -> bool:
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return a[i - 1] >= b[i - 1] and a[i] < b[i]
