"""Historical simulation.

The backtester runs a strategy over completed bars using **the same matching
engine, the same fee schedule and the same risk checks as live paper trading**.
That is the design's whole point: a result here and a result in the live
terminal differ because the market differed, not because the simulator was
kinder.

The bar loop enforces the ordering that prevents lookahead:

    for each bar:
        1. match orders placed on the PREVIOUS bar against THIS bar
        2. mark the portfolio to this bar's close
        3. record the equity point
        4. show the strategy this completed bar; any orders it places
           will be matched on the NEXT bar

A strategy therefore cannot act on a price it could not have known. Reordering
steps 1 and 4 is the single edit that would make every result in this module
optimistic, which is why the loop is written out rather than hidden behind an
event framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .analytics import Performance, analyze, by_symbol
from .engine.broker import EquityPoint, PaperBroker
from .engine.fees import FeeSchedule
from .engine.matching import Matcher
from .engine.risk import RiskLimits
from .engine.slippage import SlippageModel
from .feeds.base import Feed
from .instruments import resolve
from .portfolio import Portfolio
from .strategies.base import Strategy, StrategyContext
from .types import Bar, Fill, Order, OrderStatus, TimeInForce, utcnow


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    interval: str
    params: dict = field(default_factory=dict)
    bars: int = 0
    start: datetime | None = None
    end: datetime | None = None
    starting_equity: float = 0.0
    ending_equity: float = 0.0
    performance: Performance | None = None
    equity_curve: list[EquityPoint] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    benchmark_return_pct: float | None = None

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return (self.ending_equity / self.starting_equity - 1.0) * 100.0

    @property
    def alpha_pct(self) -> float | None:
        """Excess return over buy-and-hold. Often the only number that matters."""
        if self.benchmark_return_pct is None:
            return None
        return round(self.total_return_pct - self.benchmark_return_pct, 3)

    def summary(self) -> dict:
        perf = self.performance.to_dict() if self.performance else {}
        return {
            "strategy": self.strategy, "symbol": self.symbol,
            "interval": self.interval, "params": self.params,
            "bars": self.bars,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "starting_equity": round(self.starting_equity, 2),
            "ending_equity": round(self.ending_equity, 2),
            "total_return_pct": round(self.total_return_pct, 3),
            "benchmark_return_pct": self.benchmark_return_pct,
            "alpha_pct": self.alpha_pct,
            "orders": len(self.orders), "fills": len(self.fills),
            **{k: v for k, v in perf.items() if k != "caveats"},
            "caveats": perf.get("caveats", []),
        }


class Backtester:
    """Replays bars through the live execution stack."""

    def __init__(self, *, starting_cash: float = 100_000.0,
                 fee_schedule: FeeSchedule | None = None,
                 slippage: SlippageModel | None = None,
                 risk_limits: RiskLimits | None = None):
        self.starting_cash = starting_cash
        self.fee_schedule = fee_schedule or FeeSchedule()
        self.slippage = slippage or SlippageModel()
        # Backtests bypass session gating: historical daily bars are already
        # only the sessions that existed, and re-checking the clock against
        # *today* would reject every one of them.
        self.risk_limits = risk_limits or RiskLimits(
            max_position_pct_equity=1.0, enforce_pdt=False)

    def run(self, strategy: Strategy, bars: list[Bar], *,
            symbol: str | None = None, benchmark: bool = True) -> BacktestResult:
        if len(bars) < 2:
            raise ValueError("a backtest needs at least two bars")
        sym = (symbol or bars[0].symbol).upper()
        inst = resolve(sym)
        bars = sorted(bars, key=lambda b: b.ts)

        portfolio = Portfolio(account_id=f"backtest:{strategy.name}",
                              starting_cash=self.starting_cash)
        broker = PaperBroker(portfolio, feed=None,
                             fee_schedule=self.fee_schedule,
                             risk_limits=self.risk_limits,
                             slippage=self.slippage,
                             auto_liquidate=True)
        matcher = Matcher(self.slippage, fee_fn=broker._fee_fn)

        ctx = StrategyContext(broker=broker, symbol=sym,
                              params=dict(strategy.params),
                              strategy_name=strategy.name)
        strategy.on_start(ctx)

        curve: list[EquityPoint] = []
        prev_close = bars[0].open

        # Point the broker's clock at the bar being processed. Without this a
        # DAY order placed on a historical bar is measured against today's
        # session close and expires before it can ever be matched.
        cursor = {"ts": bars[0].ts}
        broker.clock = lambda: cursor["ts"]

        for i, bar in enumerate(bars):
            cursor["ts"] = bar.ts
            # 1. Match orders that were placed on earlier bars.
            for order in list(broker.working.values()):
                if order.symbol.upper() != sym:
                    continue
                result = matcher.match_bar(order, inst, bar, prev_close)
                if result.status is OrderStatus.REJECTED:
                    broker._reject(order, result.reason)
                    continue
                for fill in result.fills:
                    broker._book(order, fill, inst)
                    strategy.on_fill(ctx, fill)
                # DAY orders do not survive to the next bar.
                if order.is_open and order.tif is TimeInForce.DAY:
                    broker._finish(order, OrderStatus.EXPIRED,
                                   "day order expired at the bar's close")

            # 2. Mark to this bar's close.
            portfolio.mark({sym: bar.close})

            # 3. Record equity, and force a liquidation if margin is breached.
            if portfolio.margin_call():
                self._liquidate_on_bar(broker, matcher, inst, bar, sym)
            curve.append(EquityPoint(bar.ts, portfolio.equity(),
                                     portfolio.cash_total(),
                                     portfolio.unrealized_pnl(),
                                     portfolio.realized_pnl))

            # 4. Only now does the strategy see the completed bar.
            ctx.bars = bars[: i + 1]
            strategy.on_bar(ctx, bar)
            prev_close = bar.close

        strategy.on_finish(ctx)

        # Close anything still open at the final price, so the result reflects
        # realized outcomes rather than a hopeful open position.
        final = bars[-1]
        pos = portfolio.position(sym)
        if not pos.is_flat:
            from .types import Side
            closing = Order(symbol=sym,
                            side=Side.SELL if pos.is_long else Side.BUY,
                            qty=inst.round_qty(abs(pos.qty)),
                            tag="backtest-final-close")
            closing.status = OrderStatus.NEW
            broker.orders[closing.id] = closing
            for fill in matcher.match_bar(closing, inst, final, prev_close).fills:
                broker._book(closing, fill, inst)
            portfolio.mark({sym: final.close})
            curve.append(EquityPoint(final.ts, portfolio.equity(),
                                     portfolio.cash_total(), 0.0,
                                     portfolio.realized_pnl))

        result = BacktestResult(
            strategy=strategy.name, symbol=sym, interval=bars[0].interval,
            params=dict(strategy.params), bars=len(bars),
            start=bars[0].ts, end=bars[-1].ts,
            starting_equity=self.starting_cash,
            ending_equity=portfolio.equity(),
            equity_curve=curve, fills=list(broker.fills),
            orders=list(broker.orders.values()), log=list(ctx._log),
        )
        result.performance = analyze(
            curve, broker.fills, asset_class=inst.asset_class.value,
            strategies={o.id: o.strategy for o in broker.orders.values() if o.strategy})
        if benchmark:
            result.benchmark_return_pct = round(
                (bars[-1].close / bars[0].open - 1.0) * 100.0, 3)
        return result

    def _liquidate_on_bar(self, broker: PaperBroker, matcher: Matcher,
                          inst, bar: Bar, sym: str) -> None:
        from .types import Side
        pos = broker.portfolio.position(sym)
        if pos.is_flat:
            return
        broker._log("margin_call", None,
                    f"equity {broker.portfolio.equity():,.2f} below maintenance")
        order = Order(symbol=sym, side=Side.SELL if pos.is_long else Side.BUY,
                      qty=inst.round_qty(abs(pos.qty)), reduce_only=True,
                      tag="margin-liquidation")
        order.status = OrderStatus.NEW
        broker.orders[order.id] = order
        for fill in matcher.match_bar(order, inst, bar).fills:
            broker._book(order, fill, inst)

    # ------------------------------------------------------------ convenience

    def run_from_feed(self, strategy: Strategy, feed: Feed, symbol: str, *,
                      interval: str = "1d", limit: int = 400) -> BacktestResult:
        return self.run(strategy, feed.get_bars(symbol, interval, limit),
                        symbol=symbol)

    def compare(self, strategies: list[Strategy], bars: list[Bar],
                symbol: str | None = None) -> list[BacktestResult]:
        """Run several strategies over identical data. Ranked by return."""
        results = [self.run(s, bars, symbol=symbol) for s in strategies]
        return sorted(results, key=lambda r: -r.total_return_pct)


def sweep(strategy_cls: type[Strategy], bars: list[Bar], grid: dict[str, list],
          *, symbol: str | None = None, starting_cash: float = 100_000.0
          ) -> list[BacktestResult]:
    """Grid-search parameters over one dataset.

    A caution that belongs next to the function rather than in a footnote: the
    best cell of a large grid is mostly a measurement of how many cells were
    tried. Treat the *distribution* of results as the signal — a parameter that
    only works at one exact setting is fitted to this history, not to the
    market — and confirm anything promising on data the sweep never saw.
    """
    keys = list(grid)
    combos: list[dict] = [{}]
    for k in keys:
        combos = [{**c, k: v} for c in combos for v in grid[k]]

    bt = Backtester(starting_cash=starting_cash)
    out = []
    for combo in combos:
        out.append(bt.run(strategy_cls(**combo), bars, symbol=symbol))
    return sorted(out, key=lambda r: -r.total_return_pct)
