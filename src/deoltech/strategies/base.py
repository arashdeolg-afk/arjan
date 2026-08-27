"""Strategy API.

A strategy sees completed bars and places orders. It never sees the future,
because the backtester only ever hands it bars that have closed, and the orders
it places are matched against the *next* bar. That single constraint is what
separates a backtest from a story.

Strategies do not touch the portfolio or the matcher directly. They go through
`StrategyContext`, which owns sizing, exposes read-only account state, and
stamps every order with the strategy's name so attribution works afterwards.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ..instruments import Instrument, resolve
from ..types import (
    Bar, Fill, Order, OrderType, Position, Quote, Side, TimeInForce,
)


@dataclass
class StrategyContext:
    """What a strategy is allowed to do and see."""

    broker: object                    # PaperBroker (untyped to avoid a cycle)
    symbol: str
    params: dict = field(default_factory=dict)
    bars: list[Bar] = field(default_factory=list)
    strategy_name: str = "strategy"
    _log: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- account

    @property
    def instrument(self) -> Instrument:
        return resolve(self.symbol)

    @property
    def position(self) -> Position:
        return self.broker.portfolio.position(self.symbol)

    @property
    def qty(self) -> float:
        return self.position.qty

    @property
    def is_long(self) -> bool:
        return self.position.is_long

    @property
    def is_short(self) -> bool:
        return self.position.is_short

    @property
    def is_flat(self) -> bool:
        return self.position.is_flat

    @property
    def equity(self) -> float:
        return self.broker.portfolio.equity()

    @property
    def cash(self) -> float:
        return self.broker.portfolio.cash_total()

    @property
    def price(self) -> float:
        return self.bars[-1].close if self.bars else 0.0

    @property
    def closes(self) -> list[float]:
        return [b.close for b in self.bars]

    def log(self, message: str) -> None:
        self._log.append(f"[{self.strategy_name}] {message}")

    # -------------------------------------------------------------- sizing

    def size_by_risk(self, stop_distance: float, risk_pct: float = 1.0) -> float:
        """Quantity that risks `risk_pct` of equity if the stop is hit.

        This is the sizing rule that makes results comparable across
        instruments: the same 1% is at stake whether the stop is 30 cents away
        on a $12 stock or $900 away on Bitcoin.
        """
        if stop_distance <= 0:
            return 0.0
        inst = self.instrument
        risk_amount = self.equity * (risk_pct / 100.0)
        rate = self.broker.portfolio.fx_rate(inst.quote_ccy)
        per_unit = stop_distance * inst.multiplier * rate
        if per_unit <= 0:
            return 0.0
        return max(0.0, inst.round_qty(risk_amount / per_unit))

    def size_by_notional(self, notional: float) -> float:
        px = self.price
        inst = self.instrument
        if px <= 0:
            return 0.0
        rate = self.broker.portfolio.fx_rate(inst.quote_ccy)
        return max(0.0, inst.round_qty(notional / (px * inst.multiplier * rate)))

    def size_by_equity_fraction(self, fraction: float = 0.1) -> float:
        return self.size_by_notional(self.equity * fraction)

    def max_size(self, side: Side = Side.BUY) -> float:
        return self.broker.risk.max_qty(self.symbol, side,
                                        self.broker.portfolio, self.price)

    # -------------------------------------------------------------- orders

    def _submit(self, order: Order) -> Order:
        order.strategy = self.strategy_name
        return self.broker.submit(order)

    def buy(self, qty: float, *, limit: float | None = None,
            stop_loss: float | None = None, take_profit: float | None = None,
            tif: TimeInForce = TimeInForce.DAY, tag: str = "") -> Order | None:
        return self._order(Side.BUY, qty, limit, stop_loss, take_profit, tif, tag)

    def sell(self, qty: float, *, limit: float | None = None,
             stop_loss: float | None = None, take_profit: float | None = None,
             tif: TimeInForce = TimeInForce.DAY, tag: str = "") -> Order | None:
        return self._order(Side.SELL, qty, limit, stop_loss, take_profit, tif, tag)

    def _order(self, side, qty, limit, stop_loss, take_profit, tif, tag):
        qty = self.instrument.round_qty(qty)
        if qty <= 0:
            return None
        return self._submit(Order(
            symbol=self.symbol, side=side, qty=qty,
            order_type=OrderType.LIMIT if limit else OrderType.MARKET,
            limit_price=limit, tif=tif, stop_loss=stop_loss,
            take_profit=take_profit, tag=tag or None,
        ))

    def close(self, qty: float | None = None) -> Order | None:
        return self.broker.close_position(self.symbol, qty)

    def target_position(self, target_qty: float) -> Order | None:
        """Trade the difference to reach `target_qty`. Handles flips."""
        delta = self.instrument.round_qty(abs(target_qty - self.qty))
        if delta <= 0:
            return None
        side = Side.BUY if target_qty > self.qty else Side.SELL
        return self._submit(Order(symbol=self.symbol, side=side, qty=delta,
                                  order_type=OrderType.MARKET))


class Strategy(ABC):
    """Base class. Override the callbacks you need."""

    name: str = "strategy"
    description: str = ""
    # Declared so a UI can render a parameter form without instantiating.
    params_schema: dict[str, dict] = {}

    def __init__(self, **params):
        self.params = {**{k: v.get("default") for k, v in self.params_schema.items()},
                       **params}

    def param(self, key: str, default=None):
        return self.params.get(key, default)

    def on_start(self, ctx: StrategyContext) -> None:
        """Called once before the first bar."""

    @abstractmethod
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        """Called once per COMPLETED bar. Orders fill on the next one."""

    def on_quote(self, ctx: StrategyContext, quote: Quote) -> None:
        """Called on each live tick. Unused by bar-driven strategies."""

    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
        """Called after one of this strategy's orders executes."""

    def on_finish(self, ctx: StrategyContext) -> None:
        """Called after the last bar."""


REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> type[Strategy]:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; available: "
                       f"{', '.join(sorted(REGISTRY))}")
    return REGISTRY[name]


def available() -> list[dict]:
    return [{"name": c.name, "description": c.description,
             "params": c.params_schema}
            for c in sorted(REGISTRY.values(), key=lambda c: c.name)]
