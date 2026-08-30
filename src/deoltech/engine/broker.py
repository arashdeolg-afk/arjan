"""The paper broker: order lifecycle, execution, and account state.

This is the component a trader actually talks to. It owns the working order
book, runs every order through risk, drives the matcher on each market update,
books fills into the portfolio, and handles the lifecycle machinery that makes
a simulator feel like a broker rather than a spreadsheet:

* **Time in force** — DAY orders expire at the session close, GTD at their
  date, IOC keeps what it can fill and cancels the rest, FOK is all-or-nothing.
* **Brackets** — a filled entry automatically arms its take-profit and
  stop-loss as an OCO pair, and the one that fills cancels the other. This is
  how a real trader defines risk at entry rather than improvising later.
* **Financing** — FX swap at the 17:00 ET roll (tripled on Wednesday) and
  short borrow accrue daily against open positions.
* **Margin calls** — when equity falls below maintenance, positions are
  liquidated largest-requirement-first, exactly as a risk desk would.
* **An append-only event journal** — every state transition is recorded, so any
  balance on the screen can be traced back to the events that produced it.

Everything is deterministic. Given the same market data and the same orders,
this produces the same fills, the same balances, and the same journal.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ..clock import is_rollover_time, session_close, session_for, swap_multiplier, to_et
from ..feeds.base import Feed, FeedError
from ..instruments import Instrument, resolve
from ..portfolio import Portfolio, round_money
from ..types import (
    AssetClass, Fill, Liquidity, Order, OrderStatus, OrderType, Quote, Side,
    TimeInForce, iso, utcnow,
)
from .fees import FeeSchedule, borrow_charge, compute_fees, swap_charge
from .matching import MatchContext, Matcher
from .risk import RiskDecision, RiskEngine, RiskLimits, RiskState
from .slippage import SlippageModel


@dataclass
class BrokerEvent:
    ts: datetime
    kind: str          # submit | accept | reject | fill | partial | cancel | expire | ...
    order_id: str = ""
    symbol: str = ""
    detail: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class EquityPoint:
    ts: datetime
    equity: float
    cash: float
    unrealized: float
    realized: float


class PaperBroker:
    """A deterministic simulated broker for one account."""

    def __init__(self, portfolio: Portfolio | None = None, *,
                 feed: Feed | None = None,
                 fee_schedule: FeeSchedule | None = None,
                 risk_limits: RiskLimits | None = None,
                 slippage: SlippageModel | None = None,
                 auto_liquidate: bool = True,
                 journal_limit: int = 20_000,
                 clock=None):
        # Every time decision goes through `self.clock`, never straight to the
        # wall clock. The backtester points it at the bar being processed, so a
        # DAY order placed on a 2019 bar expires at that bar's session close
        # rather than instantly against today's date.
        self.clock = clock or utcnow
        self.portfolio = portfolio or Portfolio()
        self.feed = feed
        self.fees = fee_schedule or FeeSchedule()
        self.risk = RiskEngine(risk_limits or RiskLimits())
        self.matcher = Matcher(slippage or SlippageModel(), fee_fn=self._fee_fn)
        self.auto_liquidate = auto_liquidate

        self.orders: dict[str, Order] = {}
        self.working: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.events: deque[BrokerEvent] = deque(maxlen=journal_limit)
        self.equity_curve: list[EquityPoint] = []

        self._oco: dict[str, set[str]] = defaultdict(set)
        self._children: dict[str, list[Order]] = defaultdict(list)
        self._lock = threading.RLock()

        self._day_trades: deque[tuple[date, str]] = deque(maxlen=500)
        self._opened_today: dict[str, float] = {}
        self._session_date: date = to_et(self.clock()).date()
        self._start_of_day_equity = self.portfolio.equity()
        self._last_financing: date | None = None
        self.last_error: str = ""

    # ------------------------------------------------------------------ hooks

    def _fee_fn(self, inst: Instrument, side: Side, qty: float, price: float,
                liquidity: Liquidity) -> float:
        rate = self.portfolio.fx_rate(inst.quote_ccy)
        return compute_fees(inst, side, qty, price, schedule=self.fees,
                            liquidity=liquidity,
                            volume_30d=self.portfolio.volume_30d,
                            quote_to_account=rate).total

    def _log(self, kind: str, order: Order | None = None, detail: str = "",
             **data) -> BrokerEvent:
        ev = BrokerEvent(
            ts=self.clock(), kind=kind,
            order_id=order.id if order else "",
            symbol=order.symbol if order else data.pop("symbol", ""),
            detail=detail, data=data)
        self.events.append(ev)
        return ev

    # ---------------------------------------------------------------- pricing

    def _quote(self, symbol: str) -> Quote | None:
        if self.feed is None:
            px = self.portfolio.price_of(symbol)
            if px <= 0:
                return None
            return Quote(symbol=symbol.upper(), ts=self.clock(), last=px,
                         high=px, low=px, prev_close=px, source="portfolio-mark")
        try:
            return self.feed.get_quote(symbol)
        except FeedError as e:
            self.last_error = str(e)
            px = self.portfolio.price_of(symbol)
            return (Quote(symbol=symbol.upper(), ts=self.clock(), last=px, high=px,
                          low=px, prev_close=px, source="last-mark")
                    if px > 0 else None)

    def risk_state(self) -> RiskState:
        return RiskState(
            open_orders=len(self.working),
            day_trades_5d=self.day_trade_count(),
            realized_today=self.portfolio.realized_pnl,
            start_of_day_equity=self._start_of_day_equity,
        )

    # ----------------------------------------------------------------- submit

    def submit(self, order: Order, quote: Quote | None = None) -> Order:
        """Risk-check, accept, and attempt an immediate execution."""
        with self._lock:
            self.orders[order.id] = order
            self._log("submit", order,
                      f"{order.side.value} {order.qty} {order.symbol} "
                      f"{order.order_type.value}")

            inst = resolve(order.symbol)
            q = quote or self._quote(order.symbol)
            last = q.last if q else 0.0

            decision = self.risk.check(order, self.portfolio, self.risk_state(),
                                       last, self.clock())
            if not decision:
                return self._reject(order, decision.reason, decision.code)

            # reduce_only is clamped rather than rejected when it is merely
            # oversized: the intent ("close this") is unambiguous.
            if order.reduce_only:
                pos = self.portfolio.positions.get(order.symbol.upper())
                if pos and abs(pos.qty) < order.qty:
                    order.qty = inst.round_qty(abs(pos.qty))
                    if order.qty <= 0:
                        return self._reject(order, "nothing left to reduce",
                                            "reduce_only_no_position")

            order.status = OrderStatus.NEW
            order.touch()
            if order.tif is TimeInForce.DAY and order.expires_at is None:
                order.expires_at = self._day_expiry(inst.asset_class.value)
            self.working[order.id] = order
            if order.oco_group:
                self._oco[order.oco_group].add(order.id)
            self._log("accept", order, "working")

            if q is not None:
                self._try_match(order, inst, q)
            self._enforce_tif(order, immediate=True)
            return order

    def _day_expiry(self, asset_class: str):
        """When a DAY order placed now should expire.

        If the current session has already ended — an order placed at 9pm, or
        over a weekend — the order belongs to the NEXT session, which is what
        every broker does. Pinning it to a close that is already in the past
        would expire it the instant it was accepted.
        """
        now = self.clock()
        close = session_close(asset_class, now)
        if close is not None and close > now:
            return close
        from ..clock import next_open
        upcoming = next_open(asset_class, now)
        return session_close(asset_class, upcoming) if upcoming else None

    def _reject(self, order: Order, reason: str, code: str = "") -> Order:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.touch()
        self.working.pop(order.id, None)
        self._log("reject", order, reason, code=code)
        self._cancel_children(order, "parent rejected")
        return order

    # ------------------------------------------------------------------ match

    def _try_match(self, order: Order, inst: Instrument, quote: Quote) -> None:
        ctx = MatchContext.build(inst, quote, self.clock())
        result = self.matcher.match(order, ctx)

        if result.status is OrderStatus.REJECTED:
            self._reject(order, result.reason or "rejected by the venue")
            return
        if result.status is OrderStatus.CANCELED:
            self._finish(order, OrderStatus.CANCELED, result.reason)
            return

        if not result.fills:
            return

        # FOK is all-or-nothing: a partial fill is not an acceptable outcome, so
        # discard it entirely rather than booking half a position.
        if order.tif is TimeInForce.FOK and result.filled_qty < order.remaining - 1e-12:
            self._finish(order, OrderStatus.CANCELED,
                         "fill-or-kill: insufficient size at the touch")
            return

        for fill in result.fills:
            self._book(order, fill, inst)

    def _book(self, order: Order, fill: Fill, inst: Instrument) -> None:
        realized = self.portfolio.apply_fill(fill, inst)
        self.fills.append(fill)

        prev_filled = order.filled_qty
        order.filled_qty = round(prev_filled + fill.qty, 12)
        # Round to the instrument's own precision. Without it, a weighted
        # average of exact tick prices comes back as 249.20999999999998 and
        # every screen showing it looks broken.
        order.avg_fill_price = inst.round_price(
            ((prev_filled * order.avg_fill_price + fill.qty * fill.price)
             / order.filled_qty) if order.filled_qty else fill.price)
        order.fees_paid += fill.fee
        order.touch()

        self._track_day_trade(order, fill)

        if order.remaining <= 1e-12:
            order.status = OrderStatus.FILLED
            self.working.pop(order.id, None)
            self._log("fill", order,
                      f"filled {inst.fmt_qty(order.filled_qty)} @ "
                      f"{inst.fmt_price(order.avg_fill_price)}",
                      price=fill.price, qty=fill.qty, fee=fill.fee,
                      liquidity=fill.liquidity.value, realized=realized)
            self._on_filled(order)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
            self._log("partial", order,
                      f"{inst.fmt_qty(order.filled_qty)}/{inst.fmt_qty(order.qty)} @ "
                      f"{inst.fmt_price(fill.price)}",
                      price=fill.price, qty=fill.qty, fee=fill.fee)

    def _on_filled(self, order: Order) -> None:
        """A fill cancels its OCO siblings and arms any bracket children."""
        if order.oco_group:
            for sibling_id in list(self._oco.get(order.oco_group, ())):
                if sibling_id == order.id:
                    continue
                sib = self.working.get(sibling_id)
                if sib:
                    self._finish(sib, OrderStatus.CANCELED,
                                 f"OCO: cancelled by {order.id}")
            self._oco.pop(order.oco_group, None)
        self._arm_bracket(order)

    def _arm_bracket(self, parent: Order) -> None:
        """Turn an entry's take-profit / stop-loss into a live OCO pair."""
        if parent.take_profit is None and parent.stop_loss is None:
            return
        exit_side = parent.side.opposite
        group = f"OCO-{parent.id}"
        children: list[Order] = []
        if parent.take_profit is not None:
            children.append(Order(
                symbol=parent.symbol, side=exit_side, qty=parent.filled_qty,
                order_type=OrderType.LIMIT, limit_price=parent.take_profit,
                tif=TimeInForce.GTC, reduce_only=True, parent_id=parent.id,
                oco_group=group, strategy=parent.strategy,
                tag=f"{parent.tag or ''}:take-profit".strip(":"),
            ))
        if parent.stop_loss is not None:
            children.append(Order(
                symbol=parent.symbol, side=exit_side, qty=parent.filled_qty,
                order_type=OrderType.STOP, stop_price=parent.stop_loss,
                tif=TimeInForce.GTC, reduce_only=True, parent_id=parent.id,
                oco_group=group, strategy=parent.strategy,
                tag=f"{parent.tag or ''}:stop-loss".strip(":"),
            ))
        for child in children:
            self._children[parent.id].append(child)
            self.submit(child)
        if children:
            self._log("bracket", parent,
                      f"armed {len(children)} protective order(s)", group=group)

    def _cancel_children(self, parent: Order, reason: str) -> None:
        for child in self._children.get(parent.id, []):
            if child.is_open:
                self._finish(child, OrderStatus.CANCELED, reason)

    def _finish(self, order: Order, status: OrderStatus, reason: str = "") -> None:
        order.status = status
        order.reject_reason = reason or order.reject_reason
        order.touch()
        self.working.pop(order.id, None)
        if order.oco_group:
            self._oco.get(order.oco_group, set()).discard(order.id)
        self._log(status.value, order, reason)

    # -------------------------------------------------------------------- tif

    def _enforce_tif(self, order: Order, immediate: bool = False) -> None:
        if not order.is_open:
            return
        now = self.clock()
        if order.tif is TimeInForce.IOC and immediate:
            if order.remaining > 1e-12:
                self._finish(
                    order,
                    OrderStatus.CANCELED if order.filled_qty > 0 else OrderStatus.CANCELED,
                    "immediate-or-cancel: remainder cancelled")
            return
        if order.tif is TimeInForce.FOK and immediate and order.filled_qty <= 0:
            self._finish(order, OrderStatus.CANCELED,
                         "fill-or-kill: could not fill in full")
            return
        if order.expires_at and now >= order.expires_at:
            self._finish(order, OrderStatus.EXPIRED,
                         f"{order.tif.value} order expired")

    # ------------------------------------------------------------------- ticks

    def on_market_data(self, quotes: dict[str, Quote]) -> list[Fill]:
        """Advance every working order against fresh prices. The main loop."""
        with self._lock:
            before = len(self.fills)
            self.portfolio.mark({s: q.last for s, q in quotes.items() if q.last > 0})

            self._roll_session_if_needed()

            for order in list(self.working.values()):
                q = quotes.get(order.symbol.upper())
                if q is None:
                    self._enforce_tif(order)
                    continue
                self._try_match(order, resolve(order.symbol), q)
                self._enforce_tif(order)

            self._accrue_financing()
            if self.auto_liquidate and self.portfolio.margin_call():
                self._liquidate()

            self._snapshot_equity()
            return self.fills[before:]

    def refresh(self, symbols: list[str] | None = None) -> list[Fill]:
        """Pull fresh quotes for everything that matters and process them."""
        if self.feed is None:
            return []
        wanted = set(s.upper() for s in (symbols or []))
        wanted |= {o.symbol.upper() for o in self.working.values()}
        wanted |= {p.symbol for p in self.portfolio.open_positions()}
        if not wanted:
            return []
        try:
            quotes = self.feed.get_quotes(sorted(wanted))
        except FeedError as e:
            self.last_error = str(e)
            return []
        return self.on_market_data(quotes)

    # -------------------------------------------------------------- financing

    def _roll_session_if_needed(self) -> None:
        today = to_et(self.clock()).date()
        if today != self._session_date:
            self._session_date = today
            self._start_of_day_equity = self.portfolio.equity()
            self._opened_today.clear()

    def _accrue_financing(self, now: datetime | None = None) -> None:
        """Charge FX swap and short borrow once per day."""
        now = now or self.clock()
        today = to_et(now).date()
        if self._last_financing == today:
            return
        if not (is_rollover_time(now) or self._last_financing is None):
            # Outside the roll window and already initialized: nothing to do.
            if self._last_financing is not None:
                return
        self._last_financing = today

        for pos in self.portfolio.open_positions():
            inst = resolve(pos.symbol)
            px = self.portfolio.price_of(pos.symbol) or pos.avg_price
            if px <= 0:
                continue
            if inst.asset_class is AssetClass.FX:
                rate = self.portfolio.fx_rate(inst.quote_ccy)
                fee = swap_charge(inst, pos.qty, px, swap_multiplier(now), rate)
                if abs(fee.swap) > 1e-9:
                    self.portfolio.accrue(fee.swap, "swap", pos.symbol, now)
                    self._log("swap", None, f"{pos.symbol} swap {fee.swap:+.4f}",
                              symbol=pos.symbol, amount=fee.swap)
            elif pos.is_short:
                fee = borrow_charge(inst, pos.qty, px, 1.0, self.fees)
                if abs(fee.borrow) > 1e-9:
                    self.portfolio.accrue(fee.borrow, "borrow", pos.symbol, now)
                    self._log("borrow", None,
                              f"{pos.symbol} borrow {fee.borrow:+.4f}",
                              symbol=pos.symbol, amount=fee.borrow)

    # ----------------------------------------------------------- margin calls

    def _liquidate(self) -> None:
        """Close positions until the maintenance requirement is met again."""
        self._log("margin_call", None,
                  f"equity {self.portfolio.equity():,.2f} below maintenance "
                  f"{self.portfolio.maintenance_margin():,.2f}")
        for pos in self.portfolio.liquidation_order():
            if not self.portfolio.margin_call():
                break
            inst = resolve(pos.symbol)
            q = self._quote(pos.symbol)
            if q is None:
                continue
            # Cancel resting orders on the name first — liquidating into your
            # own working orders is how a forced close double-fills.
            for o in list(self.working.values()):
                if o.symbol.upper() == pos.symbol:
                    self._finish(o, OrderStatus.CANCELED, "margin liquidation")
            close = Order(
                symbol=pos.symbol,
                side=Side.SELL if pos.is_long else Side.BUY,
                qty=inst.round_qty(abs(pos.qty)),
                order_type=OrderType.MARKET, tif=TimeInForce.IOC,
                reduce_only=True, allow_extended=True,
                tag="margin-liquidation",
            )
            close.status = OrderStatus.NEW
            self.orders[close.id] = close
            self.working[close.id] = close
            self._log("liquidate", close, f"forced close of {pos.symbol}")
            self._try_match(close, inst, q)
            self._enforce_tif(close, immediate=True)

    # ---------------------------------------------------------------- pdt

    def _track_day_trade(self, order: Order, fill: Fill) -> None:
        """A day trade is an open and a close of the same name on the same day."""
        if resolve(order.symbol).asset_class is not AssetClass.EQUITY:
            return
        sym = order.symbol.upper()
        today = to_et(fill.ts).date()
        signed = fill.side.sign * fill.qty
        prior = self._opened_today.get(sym, 0.0)
        if prior != 0.0 and (prior > 0) != (signed > 0):
            self._day_trades.append((today, sym))
            self._opened_today[sym] = prior + signed
        else:
            self._opened_today[sym] = prior + signed

    def day_trade_count(self, now: datetime | None = None) -> int:
        """Day trades in the trailing five business days."""
        cutoff = to_et(now or self.clock()).date() - timedelta(days=7)
        return sum(1 for d, _ in self._day_trades if d >= cutoff)

    # ------------------------------------------------------------------ admin

    def cancel(self, order_id: str, reason: str = "cancelled by user") -> bool:
        with self._lock:
            order = self.working.get(order_id)
            if not order:
                return False
            self._finish(order, OrderStatus.CANCELED, reason)
            self._cancel_children(order, "parent cancelled")
            return True

    def cancel_all(self, symbol: str | None = None,
                   reason: str = "cancel-all") -> int:
        with self._lock:
            targets = [o.id for o in self.working.values()
                       if symbol is None or o.symbol.upper() == symbol.upper()]
            return sum(1 for oid in targets if self.cancel(oid, reason))

    def close_position(self, symbol: str, qty: float | None = None) -> Order | None:
        """Flatten a position at the market."""
        pos = self.portfolio.positions.get(symbol.upper())
        if not pos or pos.is_flat:
            return None
        inst = resolve(symbol)
        amount = inst.round_qty(abs(qty) if qty else abs(pos.qty))
        if amount <= 0:
            return None
        return self.submit(Order(
            symbol=pos.symbol, side=Side.SELL if pos.is_long else Side.BUY,
            qty=amount, order_type=OrderType.MARKET, reduce_only=True,
            tag="close-position",
        ))

    def flatten_all(self) -> list[Order]:
        self.cancel_all(reason="flatten-all")
        out = []
        for pos in list(self.portfolio.open_positions()):
            o = self.close_position(pos.symbol)
            if o:
                out.append(o)
        return out

    def halt(self, reason: str = "halted by administrator") -> None:
        self.risk.limits.trading_halted = True
        self.risk.limits.halt_reason = reason
        self.cancel_all(reason="trading halted")
        self._log("halt", None, reason)

    def resume(self) -> None:
        self.risk.limits.trading_halted = False
        self.risk.limits.halt_reason = ""
        self._log("resume", None, "trading resumed")

    # ---------------------------------------------------------------- reporting

    def _snapshot_equity(self) -> None:
        p = self.portfolio
        point = EquityPoint(self.clock(), p.equity(), p.cash_total(),
                            p.unrealized_pnl(), p.realized_pnl)
        # Collapse consecutive identical marks so a quiet market does not
        # produce a million-point equity curve.
        if self.equity_curve and abs(self.equity_curve[-1].equity - point.equity) < 1e-9:
            self.equity_curve[-1] = point
        else:
            self.equity_curve.append(point)

    def open_orders(self, symbol: str | None = None) -> list[Order]:
        items = [o for o in self.working.values()
                 if symbol is None or o.symbol.upper() == symbol.upper()]
        return sorted(items, key=lambda o: o.created_at)

    def order_history(self, limit: int = 200) -> list[Order]:
        return sorted(self.orders.values(), key=lambda o: o.created_at,
                      reverse=True)[:limit]

    def blotter(self, limit: int = 200) -> list[dict]:
        rows = []
        for f in sorted(self.fills, key=lambda f: f.ts, reverse=True)[:limit]:
            inst = resolve(f.symbol)
            rows.append({
                "ts": iso(f.ts), "order_id": f.order_id, "symbol": f.symbol,
                "side": f.side.value, "qty": f.qty,
                "qty_fmt": inst.fmt_qty(f.qty),
                "price": f.price, "price_fmt": inst.fmt_price(f.price),
                "notional": round_money(inst.notional(f.qty, f.price)),
                "fee": round(f.fee, 4), "liquidity": f.liquidity.value,
                "slippage_bps": f.slippage_bps,
            })
        return rows

    def summary(self) -> dict:
        snap = self.portfolio.snapshot()
        snap.update({
            "working_orders": len(self.working),
            "total_orders": len(self.orders),
            "total_fills": len(self.fills),
            "day_trades_5d": self.day_trade_count(),
            "trading_halted": self.risk.limits.trading_halted,
            "halt_reason": self.risk.limits.halt_reason,
            "start_of_day_equity": round_money(self._start_of_day_equity),
            "day_pnl": round_money(self.portfolio.equity() - self._start_of_day_equity),
            "last_feed_error": self.last_error,
        })
        return snap
