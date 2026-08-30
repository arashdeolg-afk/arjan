"""Performance measurement.

The purpose of this module is to make a trading record hard to lie to yourself
with. Three rules follow from that, and they are enforced in the code rather
than left to the reader:

**Report the median trade, not just the mean.** Trade P&L is fat-tailed. One
outsized winner drags the average above the level of a strategy that loses on
most trades, so mean and median appear side by side, always. Where they diverge
sharply, the median is the honest one.

**Gate on sample size.** A Sharpe ratio computed from eleven trades is noise
with a decimal point. Below `MIN_TRADES`, statistics are still shown — hiding
them would be its own distortion — but flagged `low_confidence`, and the
headline verdict stays silent.

**Annualize honestly.** Scaling a two-week return to a yearly figure produces
numbers like "1,400% CAGR" that mean nothing. Annualized figures are suppressed
below `MIN_DAYS_FOR_ANNUAL` of history.

Everything is computed from the executed record — fills and the equity curve —
never from a strategy's intentions.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .engine.broker import EquityPoint
from .instruments import resolve
from .types import Fill, Side

# Below this many closed trades, per-trade statistics are noise.
MIN_TRADES = 20
# Below this many days of history, annualized figures are meaningless.
MIN_DAYS_FOR_ANNUAL = 30
# Risk-free rate used in Sharpe/Sortino. Zero is a defensible default and is
# stated rather than hidden, because a nonzero one quietly lowers every Sharpe.
RISK_FREE_RATE = 0.0

TRADING_DAYS = {"equity": 252, "fx": 252, "crypto": 365}


@dataclass
class RoundTrip:
    """One completed trade: an entry and the exit that closed it."""

    symbol: str
    side: str                  # long | short
    qty: float
    entry_price: float
    exit_price: float
    entry_ts: datetime
    exit_ts: datetime
    pnl: float = 0.0           # net of fees
    fees: float = 0.0
    strategy: str | None = None

    @property
    def hold_seconds(self) -> float:
        return max(0.0, (self.exit_ts - self.entry_ts).total_seconds())

    @property
    def hold_hours(self) -> float:
        return self.hold_seconds / 3600.0

    @property
    def return_pct(self) -> float:
        basis = abs(self.qty * self.entry_price)
        return (self.pnl / basis * 100.0) if basis > 0 else 0.0

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    @property
    def is_day_trade(self) -> bool:
        return self.entry_ts.date() == self.exit_ts.date()


def reconstruct_trades(fills: list[Fill],
                       strategies: dict[str, str] | None = None) -> list[RoundTrip]:
    """Pair fills FIFO into completed round trips.

    Open inventory is carried per symbol; a fill on the opposite side consumes
    it oldest-first, emitting one RoundTrip per lot consumed. Fills that only
    open exposure produce nothing — an open position is not a result.
    """
    strategies = strategies or {}
    inventory: dict[str, list[dict]] = {}
    trips: list[RoundTrip] = []

    for f in sorted(fills, key=lambda x: (x.ts, x.order_id)):
        sym = f.symbol.upper()
        inst = resolve(sym)
        book = inventory.setdefault(sym, [])
        signed = f.side.sign * f.qty
        remaining = abs(signed)
        # Fees are apportioned across the quantity this fill actually moves.
        fee_per_unit = (f.fee / f.qty) if f.qty else 0.0

        while remaining > 1e-12 and book and (book[0]["qty"] > 0) != (signed > 0):
            lot = book[0]
            take = min(remaining, abs(lot["qty"]))
            direction = 1.0 if lot["qty"] > 0 else -1.0
            gross = (f.price - lot["price"]) * take * direction * inst.multiplier
            fees = take * (lot["fee_per_unit"] + fee_per_unit)
            trips.append(RoundTrip(
                symbol=sym,
                side="long" if direction > 0 else "short",
                qty=take, entry_price=lot["price"], exit_price=f.price,
                entry_ts=lot["ts"], exit_ts=f.ts,
                pnl=gross - fees, fees=fees,
                strategy=strategies.get(lot["order_id"]) or strategies.get(f.order_id),
            ))
            lot["qty"] -= direction * take
            remaining -= take
            if abs(lot["qty"]) <= 1e-12:
                book.pop(0)

        if remaining > 1e-12:
            book.append({
                "qty": math.copysign(remaining, signed), "price": f.price,
                "ts": f.ts, "fee_per_unit": fee_per_unit, "order_id": f.order_id,
            })
    return trips


# ------------------------------------------------------------------- returns


def _returns(curve: list[EquityPoint]) -> list[float]:
    out = []
    for i in range(1, len(curve)):
        prev = curve[i - 1].equity
        if prev > 0:
            out.append(curve[i].equity / prev - 1.0)
    return out


def daily_returns(curve: list[EquityPoint]) -> list[tuple[datetime, float]]:
    """Collapse an irregular equity curve to one return per calendar day.

    Sharpe computed over raw tick-level marks is meaningless — its scale
    depends on how often the price happened to be sampled.
    """
    if len(curve) < 2:
        return []
    by_day: dict[str, EquityPoint] = {}
    for p in sorted(curve, key=lambda x: x.ts):
        by_day[p.ts.date().isoformat()] = p     # last mark of each day
    days = sorted(by_day.items())
    out = []
    for i in range(1, len(days)):
        prev, cur = days[i - 1][1], days[i][1]
        if prev.equity > 0:
            out.append((cur.ts, cur.equity / prev.equity - 1.0))
    return out


def max_drawdown(curve: list[EquityPoint]) -> tuple[float, float, int]:
    """Deepest peak-to-trough decline: (fraction, absolute, days underwater)."""
    if not curve:
        return 0.0, 0.0, 0
    peak = curve[0].equity
    peak_ts = curve[0].ts
    worst_frac = worst_abs = 0.0
    worst_days = 0
    for p in curve:
        if p.equity > peak:
            peak, peak_ts = p.equity, p.ts
        elif peak > 0:
            frac = (peak - p.equity) / peak
            if frac > worst_frac:
                worst_frac = frac
                worst_abs = peak - p.equity
                worst_days = max(0, (p.ts - peak_ts).days)
    return worst_frac, worst_abs, worst_days


def sharpe(returns: list[float], periods_per_year: int = 252,
           risk_free: float = RISK_FREE_RATE) -> float:
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free / periods_per_year for r in returns]
    sd = statistics.pstdev(excess)
    if sd <= 1e-12:
        return 0.0
    return statistics.fmean(excess) / sd * math.sqrt(periods_per_year)


def sortino(returns: list[float], periods_per_year: int = 252,
            risk_free: float = RISK_FREE_RATE) -> float:
    """Like Sharpe, but only downside deviation counts as risk."""
    if len(returns) < 2:
        return 0.0
    target = risk_free / periods_per_year
    excess = [r - target for r in returns]
    downside = [min(0.0, r) for r in excess]
    dd = math.sqrt(statistics.fmean([d * d for d in downside]))
    if dd <= 1e-12:
        # No losing period. Real, but not a Sharpe of infinity — say so.
        return float("inf") if statistics.fmean(excess) > 0 else 0.0
    return statistics.fmean(excess) / dd * math.sqrt(periods_per_year)


def value_at_risk(returns: list[float], confidence: float = 0.95) -> float:
    """Historical VaR: the loss the worst (1-confidence) of days exceed."""
    if len(returns) < 10:
        return 0.0
    ordered = sorted(returns)
    idx = max(0, min(len(ordered) - 1, int((1.0 - confidence) * len(ordered))))
    return abs(min(0.0, ordered[idx]))


def conditional_var(returns: list[float], confidence: float = 0.95) -> float:
    """Expected shortfall: the average loss *given* you are in the tail."""
    if len(returns) < 10:
        return 0.0
    ordered = sorted(returns)
    cut = max(1, int((1.0 - confidence) * len(ordered)))
    tail = ordered[:cut]
    return abs(min(0.0, statistics.fmean(tail))) if tail else 0.0


# -------------------------------------------------------------------- report


@dataclass
class Performance:
    """A full performance record, with its own confidence caveats attached."""

    # Sample
    trades: int = 0
    days: int = 0
    low_confidence: bool = True
    caveats: list[str] = field(default_factory=list)

    # Returns
    starting_equity: float = 0.0
    ending_equity: float = 0.0
    total_return_pct: float = 0.0
    cagr_pct: float | None = None
    volatility_pct: float | None = None

    # Risk
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    drawdown_days: int = 0
    calmar_ratio: float | None = None
    var_95_pct: float = 0.0
    cvar_95_pct: float = 0.0

    # Trades — mean AND median, always together
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    mean_trade_pnl: float = 0.0
    median_trade_pnl: float = 0.0
    mean_win: float = 0.0
    mean_loss: float = 0.0
    median_win: float = 0.0
    median_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    median_hold_hours: float = 0.0
    day_trades: int = 0

    # Costs
    total_fees: float = 0.0
    fees_pct_of_gross: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0

    def verdict(self) -> str:
        """A one-line read, or an honest refusal to give one."""
        if self.trades < MIN_TRADES:
            return (f"Not enough evidence yet — {self.trades} closed "
                    f"trade{'s' if self.trades != 1 else ''} against a "
                    f"{MIN_TRADES}-trade minimum. Any ratio below is noise.")
        if self.net_pnl <= 0:
            return (f"Losing over {self.trades} trades: net "
                    f"{self.net_pnl:,.2f} with a {self.win_rate_pct:.0f}% hit rate.")
        if self.median_trade_pnl <= 0 < self.mean_trade_pnl:
            return ("Profitable in total but the MEDIAN trade loses money — the "
                    "result rests on a few outliers, not a repeatable edge.")
        if self.profit_factor < 1.2:
            return (f"Marginal: profit factor {self.profit_factor:.2f}. Costs of "
                    f"{self.total_fees:,.2f} are "
                    f"{self.fees_pct_of_gross:.0f}% of gross profit.")
        return (f"Profitable across {self.trades} trades: profit factor "
                f"{self.profit_factor:.2f}, median trade "
                f"{self.median_trade_pnl:+,.2f}, max drawdown "
                f"{self.max_drawdown_pct:.1f}%.")

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["verdict"] = self.verdict()
        return d


def analyze(curve: list[EquityPoint], fills: list[Fill], *,
            asset_class: str = "equity",
            strategies: dict[str, str] | None = None) -> Performance:
    """Turn an equity curve and a fill history into a performance record."""
    perf = Performance()
    trips = reconstruct_trades(fills, strategies)
    perf.trades = len(trips)

    # ---- equity-curve statistics
    if len(curve) >= 2:
        ordered = sorted(curve, key=lambda p: p.ts)
        perf.starting_equity = ordered[0].equity
        perf.ending_equity = ordered[-1].equity
        span = ordered[-1].ts - ordered[0].ts
        perf.days = max(0, span.days)

        if perf.starting_equity > 0:
            perf.total_return_pct = (
                perf.ending_equity / perf.starting_equity - 1.0) * 100.0

        dr = [r for _, r in daily_returns(ordered)]
        ppy = TRADING_DAYS.get(asset_class, 252)
        if len(dr) >= 2:
            perf.sharpe_ratio = round(sharpe(dr, ppy), 3)
            s = sortino(dr, ppy)
            perf.sortino_ratio = round(s, 3) if math.isfinite(s) else float("inf")
            perf.volatility_pct = round(statistics.pstdev(dr) * math.sqrt(ppy) * 100, 3)
            perf.var_95_pct = round(value_at_risk(dr) * 100, 3)
            perf.cvar_95_pct = round(conditional_var(dr) * 100, 3)

        frac, absolute, dd_days = max_drawdown(ordered)
        perf.max_drawdown_pct = round(frac * 100, 3)
        perf.max_drawdown_abs = round(absolute, 2)
        perf.drawdown_days = dd_days

        if perf.days >= MIN_DAYS_FOR_ANNUAL and perf.starting_equity > 0:
            years = perf.days / 365.25
            if years > 0 and perf.ending_equity > 0:
                cagr = (perf.ending_equity / perf.starting_equity) ** (1 / years) - 1
                perf.cagr_pct = round(cagr * 100, 3)
                if frac > 1e-9:
                    perf.calmar_ratio = round((cagr * 100) / (frac * 100), 3)
        else:
            perf.caveats.append(
                f"Annualized figures suppressed: {perf.days} days of history, "
                f"{MIN_DAYS_FOR_ANNUAL} required. Scaling a short record to a "
                f"yearly rate invents precision that is not there.")

    # ---- trade statistics
    if trips:
        pnls = [t.pnl for t in trips]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        perf.win_rate_pct = round(len(wins) / len(pnls) * 100, 2)
        perf.mean_trade_pnl = round(statistics.fmean(pnls), 4)
        perf.median_trade_pnl = round(statistics.median(pnls), 4)
        perf.mean_win = round(statistics.fmean(wins), 4) if wins else 0.0
        perf.mean_loss = round(statistics.fmean(losses), 4) if losses else 0.0
        perf.median_win = round(statistics.median(wins), 4) if wins else 0.0
        perf.median_loss = round(statistics.median(losses), 4) if losses else 0.0
        perf.largest_win = round(max(pnls), 4)
        perf.largest_loss = round(min(pnls), 4)
        perf.median_hold_hours = round(
            statistics.median([t.hold_hours for t in trips]), 3)
        perf.day_trades = sum(1 for t in trips if t.is_day_trade)

        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        perf.profit_factor = round(gross_win / gross_loss, 3) if gross_loss > 0 else (
            float("inf") if gross_win > 0 else 0.0)
        perf.expectancy = round(statistics.fmean(pnls), 4)

        perf.total_fees = round(sum(t.fees for t in trips), 4)
        perf.net_pnl = round(sum(pnls), 4)
        perf.gross_pnl = round(perf.net_pnl + perf.total_fees, 4)
        if perf.gross_pnl > 0:
            perf.fees_pct_of_gross = round(perf.total_fees / perf.gross_pnl * 100, 2)

        # The house rule, made explicit rather than left to the reader.
        if perf.mean_trade_pnl > 0 >= perf.median_trade_pnl:
            perf.caveats.append(
                "Mean trade is positive but the median is not: the record "
                "depends on a small number of outliers. Rank on the median.")

    perf.low_confidence = perf.trades < MIN_TRADES
    if perf.low_confidence:
        perf.caveats.insert(0, (
            f"Low confidence: {perf.trades} closed trades, {MIN_TRADES} needed "
            f"before per-trade statistics mean anything."))
    return perf


# ------------------------------------------------------------- attribution


def by_symbol(fills: list[Fill]) -> list[dict]:
    """Per-symbol attribution, ranked on median trade P&L, not total.

    Total P&L ranks a symbol you traded 400 times above one you traded twice as
    well. The median says which was actually the better decision, and the count
    says how much to trust it.
    """
    trips = reconstruct_trades(fills)
    groups: dict[str, list[RoundTrip]] = {}
    for t in trips:
        groups.setdefault(t.symbol, []).append(t)

    rows = []
    for sym, items in groups.items():
        pnls = [t.pnl for t in items]
        wins = [p for p in pnls if p > 0]
        rows.append({
            "symbol": sym,
            "asset_class": resolve(sym).asset_class.value,
            "trades": len(items),
            "net_pnl": round(sum(pnls), 2),
            "median_pnl": round(statistics.median(pnls), 2),
            "mean_pnl": round(statistics.fmean(pnls), 2),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1),
            "fees": round(sum(t.fees for t in items), 2),
            "low_confidence": len(items) < MIN_TRADES,
        })
    return sorted(rows, key=lambda r: (-r["median_pnl"], -r["trades"]))


def by_strategy(fills: list[Fill], strategies: dict[str, str]) -> list[dict]:
    trips = reconstruct_trades(fills, strategies)
    groups: dict[str, list[RoundTrip]] = {}
    for t in trips:
        groups.setdefault(t.strategy or "manual", []).append(t)

    rows = []
    for name, items in groups.items():
        pnls = [t.pnl for t in items]
        wins = [p for p in pnls if p > 0]
        gross_loss = abs(sum(p for p in pnls if p <= 0))
        rows.append({
            "strategy": name,
            "trades": len(items),
            "net_pnl": round(sum(pnls), 2),
            "median_pnl": round(statistics.median(pnls), 2),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 1),
            "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss else None,
            "low_confidence": len(items) < MIN_TRADES,
        })
    return sorted(rows, key=lambda r: -r["net_pnl"])
