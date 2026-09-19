"""Built-in strategies.

These are teaching implementations of well-known approaches, not proprietary
edges, and they are here so a trader can see how the same market behaves under
trend-following versus mean-reversion before writing their own.

`buy-and-hold` is included deliberately. It is the benchmark every other
strategy has to beat, and a system that makes it inconvenient to compare
against is helping its user fool themselves.
"""

from __future__ import annotations

from ..types import Bar, Side
from .base import Strategy, StrategyContext, register
from .indicators import (
    atr, bollinger, crossed_above, crossed_below, donchian, rsi, sma, zscore,
)


@register
class BuyAndHold(Strategy):
    name = "buy-and-hold"
    description = ("Buy once with a fixed fraction of equity and hold. The "
                   "benchmark every active strategy must beat after costs.")
    params_schema = {
        "allocation": {"type": "float", "default": 0.95, "min": 0.01, "max": 1.0,
                       "label": "Fraction of equity to deploy"},
    }

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        if ctx.is_flat and ctx.price > 0:
            qty = ctx.size_by_equity_fraction(self.param("allocation", 0.95))
            if qty > 0:
                ctx.buy(qty, tag="entry")
                ctx.log(f"bought {qty} at {bar.close}")


@register
class SmaCrossover(Strategy):
    name = "sma-crossover"
    description = ("Go long when a fast moving average crosses above a slow "
                   "one, flat (or short) when it crosses back below.")
    params_schema = {
        "fast": {"type": "int", "default": 20, "min": 2, "max": 200},
        "slow": {"type": "int", "default": 50, "min": 3, "max": 400},
        "risk_pct": {"type": "float", "default": 1.0, "min": 0.1, "max": 10.0},
        "allow_short": {"type": "bool", "default": False},
        "stop_atr": {"type": "float", "default": 2.5, "min": 0.0, "max": 10.0,
                     "label": "Stop distance in ATRs (0 = none)"},
    }

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        fast_n, slow_n = int(self.param("fast")), int(self.param("slow"))
        if len(ctx.bars) < slow_n + 2:
            return
        closes = ctx.closes
        f, s = sma(closes, fast_n), sma(closes, slow_n)
        i = len(closes) - 1
        atr_val = (atr(ctx.bars, 14) or [None])[i] or (bar.close * 0.02)
        stop_mult = float(self.param("stop_atr", 2.5))

        if crossed_above(f, s, i):
            if ctx.is_short:
                ctx.close()
            if ctx.is_flat:
                stop = bar.close - stop_mult * atr_val if stop_mult > 0 else None
                qty = (ctx.size_by_risk(stop_mult * atr_val, self.param("risk_pct", 1.0))
                       if stop_mult > 0 else ctx.size_by_equity_fraction(0.5))
                if qty > 0:
                    ctx.buy(qty, stop_loss=stop, tag="golden-cross")
                    ctx.log(f"long {qty} @ {bar.close:.2f} stop {stop}")
        elif crossed_below(f, s, i):
            if ctx.is_long:
                ctx.close()
                ctx.log(f"exit long @ {bar.close:.2f}")
            if self.param("allow_short") and ctx.is_flat:
                stop = bar.close + stop_mult * atr_val if stop_mult > 0 else None
                qty = (ctx.size_by_risk(stop_mult * atr_val, self.param("risk_pct", 1.0))
                       if stop_mult > 0 else ctx.size_by_equity_fraction(0.5))
                if qty > 0:
                    ctx.sell(qty, stop_loss=stop, tag="death-cross")


@register
class DonchianBreakout(Strategy):
    name = "donchian-breakout"
    description = ("Buy a break of the N-day high, exit on a break of the M-day "
                   "low. The classic trend-following system, ATR-sized.")
    params_schema = {
        "entry": {"type": "int", "default": 20, "min": 5, "max": 200},
        "exit": {"type": "int", "default": 10, "min": 3, "max": 100},
        "risk_pct": {"type": "float", "default": 1.0, "min": 0.1, "max": 10.0},
        "atr_stop": {"type": "float", "default": 2.0, "min": 0.5, "max": 10.0},
    }

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        entry_n, exit_n = int(self.param("entry")), int(self.param("exit"))
        if len(ctx.bars) < max(entry_n, exit_n) + 15:
            return
        i = len(ctx.bars) - 1
        entry_hi, _ = donchian(ctx.bars, entry_n)
        _, exit_lo = donchian(ctx.bars, exit_n)
        a = atr(ctx.bars, 14)[i] or bar.close * 0.02

        if ctx.is_flat and entry_hi[i] and bar.close > entry_hi[i]:
            mult = float(self.param("atr_stop", 2.0))
            qty = ctx.size_by_risk(mult * a, self.param("risk_pct", 1.0))
            if qty > 0:
                ctx.buy(qty, stop_loss=bar.close - mult * a, tag="breakout")
                ctx.log(f"breakout long {qty} @ {bar.close:.2f}")
        elif ctx.is_long and exit_lo[i] and bar.close < exit_lo[i]:
            ctx.close()
            ctx.log(f"channel exit @ {bar.close:.2f}")


@register
class MeanReversion(Strategy):
    name = "mean-reversion"
    description = ("Fade extremes: buy when price is far below its mean in "
                   "standard-deviation terms, exit as it reverts.")
    params_schema = {
        "period": {"type": "int", "default": 20, "min": 5, "max": 200},
        "entry_z": {"type": "float", "default": -2.0, "min": -5.0, "max": -0.5},
        "exit_z": {"type": "float", "default": -0.3, "min": -2.0, "max": 2.0},
        "risk_pct": {"type": "float", "default": 1.0, "min": 0.1, "max": 10.0},
        "max_hold_bars": {"type": "int", "default": 15, "min": 1, "max": 200},
    }

    def __init__(self, **params):
        super().__init__(**params)
        self._held = 0

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        period = int(self.param("period"))
        if len(ctx.bars) < period + 5:
            return
        i = len(ctx.bars) - 1
        z = zscore(ctx.closes, period)[i]
        if z is None:
            return
        a = atr(ctx.bars, 14)[i] or bar.close * 0.02

        if ctx.is_flat and z <= float(self.param("entry_z", -2.0)):
            qty = ctx.size_by_risk(2.0 * a, self.param("risk_pct", 1.0))
            if qty > 0:
                ctx.buy(qty, stop_loss=bar.close - 3.0 * a, tag="fade")
                self._held = 0
                ctx.log(f"fade long {qty} @ {bar.close:.2f} (z={z:.2f})")
        elif ctx.is_long:
            self._held += 1
            # A time stop matters here: mean reversion that has not reverted is
            # not a cheap position, it is a wrong one.
            if (z >= float(self.param("exit_z", -0.3))
                    or self._held >= int(self.param("max_hold_bars", 15))):
                ctx.close()
                ctx.log(f"revert exit @ {bar.close:.2f} (z={z:.2f}, {self._held} bars)")
                self._held = 0


@register
class RsiPullback(Strategy):
    name = "rsi-pullback"
    description = ("Buy short-term oversold readings inside a longer uptrend; "
                   "exit when the oscillator recovers.")
    params_schema = {
        "rsi_period": {"type": "int", "default": 2, "min": 2, "max": 30},
        "oversold": {"type": "float", "default": 10.0, "min": 1.0, "max": 40.0},
        "exit_level": {"type": "float", "default": 60.0, "min": 40.0, "max": 95.0},
        "trend_sma": {"type": "int", "default": 200, "min": 20, "max": 400},
        "risk_pct": {"type": "float", "default": 1.0, "min": 0.1, "max": 10.0},
    }

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        trend_n = int(self.param("trend_sma"))
        if len(ctx.bars) < trend_n + 5:
            return
        i = len(ctx.bars) - 1
        closes = ctx.closes
        trend = sma(closes, trend_n)[i]
        r = rsi(closes, int(self.param("rsi_period", 2)))[i]
        if trend is None or r is None:
            return
        a = atr(ctx.bars, 14)[i] or bar.close * 0.02

        if ctx.is_flat and bar.close > trend and r <= float(self.param("oversold", 10)):
            qty = ctx.size_by_risk(2.0 * a, self.param("risk_pct", 1.0))
            if qty > 0:
                ctx.buy(qty, stop_loss=bar.close - 2.5 * a, tag="pullback")
                ctx.log(f"pullback long {qty} @ {bar.close:.2f} (rsi={r:.1f})")
        elif ctx.is_long and r >= float(self.param("exit_level", 60)):
            ctx.close()
            ctx.log(f"rsi exit @ {bar.close:.2f} (rsi={r:.1f})")


@register
class BollingerBreakout(Strategy):
    name = "bollinger-breakout"
    description = ("Trade expansion rather than reversion: buy a close above "
                   "the upper band, exit back through the middle.")
    params_schema = {
        "period": {"type": "int", "default": 20, "min": 5, "max": 100},
        "mult": {"type": "float", "default": 2.0, "min": 0.5, "max": 4.0},
        "risk_pct": {"type": "float", "default": 1.0, "min": 0.1, "max": 10.0},
    }

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        period = int(self.param("period"))
        if len(ctx.bars) < period + 15:
            return
        i = len(ctx.bars) - 1
        upper, mid, _ = bollinger(ctx.closes, period, float(self.param("mult", 2.0)))
        if upper[i] is None:
            return
        a = atr(ctx.bars, 14)[i] or bar.close * 0.02
        if ctx.is_flat and bar.close > upper[i]:
            qty = ctx.size_by_risk(2.0 * a, self.param("risk_pct", 1.0))
            if qty > 0:
                ctx.buy(qty, stop_loss=bar.close - 2.5 * a, tag="band-break")
        elif ctx.is_long and mid[i] and bar.close < mid[i]:
            ctx.close()
