"""The matching engine.

This is where a paper platform earns or loses its credibility, so the rules it
implements are stated plainly:

**Stops gap through.** A stop-loss at 100 does not fill at 100 when the market
opens at 92. It fills at 92, minus slippage. Systems that fill stops at the stop
price make every risk-managed strategy look bulletproof and are the single
most dangerous simplification in retail backtesting.

**Resting limits need the market to trade through them.** Being *at* the touch
does not mean being filled — there is a queue in front of you. A passive fill
requires the market to trade past the limit price, which is the conservative
assumption and the correct default. Optimism here manufactures an edge that
evaporates the moment real money is involved.

**Fills are bounded by displayed liquidity.** An order for 50,000 shares of a
name showing 400 at the touch does not fill in one print at one price. It walks
the book, paying progressively worse prices, or it partially fills and keeps
working.

**Marketable orders pay the spread; passive orders earn it.** Crossing to the
touch is a real cost, and the maker/taker distinction it creates flows straight
through to fees.

**Nothing fills in a closed market.** Orders queue for the next session.

All of it is deterministic: the same order against the same market state
produces the same fills every time, which is what makes a backtest reproducible
and a regression test meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ..clock import Session, session_for
from ..instruments import Instrument
from ..types import (
    Bar, Fill, Liquidity, Order, OrderStatus, OrderType, Quote, Side,
    TimeInForce,
)
from .book import BookState, build_book
from .slippage import SlippageModel, walk_the_book

# Callback the broker supplies so the matcher stays independent of fee policy.
FeeFn = Callable[[Instrument, Side, float, float, Liquidity], float]


def _zero_fee(inst, side, qty, price, liquidity) -> float:
    return 0.0


@dataclass
class MatchContext:
    """Everything the matcher needs to know about the market right now."""

    inst: Instrument
    quote: Quote
    book: BookState
    ts: datetime
    session: Session

    @classmethod
    def build(cls, inst: Instrument, quote: Quote, ts: datetime | None = None
              ) -> "MatchContext":
        when = ts or quote.ts
        return cls(inst=inst, quote=quote, book=build_book(inst, quote, when),
                   ts=when, session=session_for(inst.asset_class.value, when))


@dataclass
class MatchResult:
    fills: list[Fill] = field(default_factory=list)
    status: OrderStatus | None = None     # set only when the order changes state
    reason: str = ""

    @property
    def filled_qty(self) -> float:
        return sum(f.qty for f in self.fills)

    def __bool__(self) -> bool:
        return bool(self.fills) or self.status is not None


class Matcher:
    """Deterministic fill simulation against a quote or a bar."""

    def __init__(self, slippage: SlippageModel | None = None,
                 fee_fn: FeeFn = _zero_fee, *,
                 require_trade_through: bool = True,
                 max_book_levels: int = 8,
                 allow_closed_session_fills: bool = False):
        self.slippage = slippage or SlippageModel()
        self.fee_fn = fee_fn
        # Conservative maker fills. Turning this off assumes you are always at
        # the front of the queue, which you are not.
        self.require_trade_through = require_trade_through
        self.max_book_levels = max_book_levels
        self.allow_closed_session_fills = allow_closed_session_fills

    # ------------------------------------------------------------- triggering

    def update_trailing(self, order: Order, ctx: MatchContext) -> None:
        """Ratchet a trailing stop toward the market. It never moves backward."""
        if order.order_type is not OrderType.TRAILING_STOP or order.triggered:
            return
        price = ctx.quote.last
        if price <= 0:
            return
        inst = ctx.inst
        if order.peak_price is None:
            order.peak_price = price
        if order.side is Side.SELL:
            # Long protection: track the high, trail below it.
            order.peak_price = max(order.peak_price, price)
            offset = (order.trail_amount if order.trail_amount
                      else order.peak_price * (order.trail_pct or 0) / 100.0)
            new_stop = inst.round_price(order.peak_price - offset, Side.SELL)
            order.stop_price = (new_stop if order.stop_price is None
                                else max(order.stop_price, new_stop))
        else:
            # Short protection: track the low, trail above it.
            order.peak_price = min(order.peak_price, price)
            offset = (order.trail_amount if order.trail_amount
                      else order.peak_price * (order.trail_pct or 0) / 100.0)
            new_stop = inst.round_price(order.peak_price + offset, Side.BUY)
            order.stop_price = (new_stop if order.stop_price is None
                                else min(order.stop_price, new_stop))

    def check_trigger(self, order: Order, ctx: MatchContext) -> bool:
        """Has a stop's trigger price been touched?

        Triggers reference the last trade, which is the convention on every US
        venue: a stop is elected by a print, not by a quote flickering through.
        """
        if not order.needs_trigger or order.triggered or order.stop_price is None:
            return False
        last = ctx.quote.last
        if last <= 0:
            return False
        hit = (last >= order.stop_price - 1e-12 if order.side is Side.BUY
               else last <= order.stop_price + 1e-12)
        if hit:
            order.triggered = True
            order.touch()
        return hit

    # ------------------------------------------------------------- execution

    def _taker_fill(self, order: Order, ctx: MatchContext, want: float,
                    price_cap: float | None) -> tuple[float, float]:
        """Take liquidity. Returns (qty, average price) — (0, 0) if none.

        `price_cap` is a marketable limit's worst acceptable price; a market
        order passes None. Walking the book past the cap stops rather than
        filling through it, which is what a limit order means.
        """
        book, inst = ctx.book, ctx.inst
        available = book.available(order.side)
        if available <= 0:
            return 0.0, 0.0

        if want <= available:
            # Fits at the touch: one price, plus modelled slippage.
            touch = book.touch(order.side)
            slip = self.slippage.apply(inst, order.side, want, touch,
                                       ctx.quote, order.id)
            price = slip.price
        else:
            # Bigger than what is displayed: walk the ladder for a real VWAP.
            vwap, filled = walk_the_book(book, inst, order.side, want,
                                         self.max_book_levels)
            if filled <= 0:
                return 0.0, 0.0
            want = min(want, filled)
            slip = self.slippage.apply(inst, order.side, want, vwap,
                                       ctx.quote, order.id)
            price = slip.price

        if price_cap is not None:
            through = (price > price_cap + 1e-12 if order.side is Side.BUY
                       else price < price_cap - 1e-12)
            if through:
                # Slippage pushed the fill beyond the limit. A limit order does
                # not fill there; cap it and let the rest keep working.
                price = price_cap
        return want, price

    def _make_fill(self, order: Order, ctx: MatchContext, qty: float,
                   price: float, liquidity: Liquidity,
                   reference: float | None = None) -> Fill:
        """Build a Fill and measure its slippage against a DECISION price.

        `reference` is what the order could have expected to pay at the moment
        it was actionable. Live, that is the current mid. On a historical bar it
        is the bar's OPEN, not its close — measuring a fill at the open against
        the close reports the day's entire price move as execution slippage,
        which turns a 1.5bps cost into a nonsensical 250bps.
        """
        inst = ctx.inst
        qty = round(min(qty, order.remaining), 12)
        ref = reference if reference and reference > 0 else ctx.book.mid
        slip_bps = ((price - ref) / ref * 10_000.0 * order.side.sign) if ref > 0 else 0.0
        fee = self.fee_fn(inst, order.side, qty, price, liquidity)
        return Fill(
            order_id=order.id, symbol=order.symbol, side=order.side, qty=qty,
            price=price, ts=ctx.ts, fee=fee, liquidity=liquidity,
            slippage_bps=round(slip_bps, 4), reference_price=ref,
            venue="deoltech-paper",
        )

    # ----------------------------------------------------------------- entry

    def match(self, order: Order, ctx: MatchContext) -> MatchResult:
        """Advance one working order against the current market."""
        if not order.is_open or order.remaining <= 0:
            return MatchResult()

        # 1. Session gate. Nothing trades in a closed market.
        if ctx.session is Session.CLOSED and not self.allow_closed_session_fills:
            if order.tif in (TimeInForce.IOC, TimeInForce.FOK):
                return MatchResult(status=OrderStatus.CANCELED,
                                   reason="market closed")
            return MatchResult()
        if (ctx.session in (Session.PREMARKET, Session.AFTERHOURS)
                and not order.allow_extended
                and order.order_type is not OrderType.MARKET_ON_CLOSE):
            # Extended-hours trading is opt-in per order, as at every broker,
            # because the risk profile is different: thin books, wide spreads.
            return MatchResult()

        # 2. Trailing stops ratchet, then stops elect.
        self.update_trailing(order, ctx)
        if order.needs_trigger and not order.triggered:
            self.check_trigger(order, ctx)
            if not order.triggered:
                return MatchResult()

        book = ctx.book
        want = order.remaining
        if order.display_qty and order.display_qty > 0:
            # Iceberg: only the displayed slice is exposed on any one tick.
            want = min(want, order.display_qty)

        otype = order.order_type

        # 3. Market-like orders: MARKET, elected STOP, and MOC at the close.
        if otype in (OrderType.MARKET, OrderType.STOP, OrderType.TRAILING_STOP) or (
                otype is OrderType.MARKET_ON_CLOSE and self._at_close(ctx)):
            # An elected stop fills at the MARKET, not at the stop price. If
            # the market gapped past the stop overnight, the gap is the fill.
            qty, price = self._taker_fill(order, ctx, want, None)
            if qty <= 0:
                return MatchResult(reason="no liquidity at touch")
            fill = self._make_fill(order, ctx, qty, price, Liquidity.TAKER)
            return MatchResult(fills=[fill])

        if otype is OrderType.MARKET_ON_CLOSE:
            return MatchResult()      # waits for the closing auction

        # 4. Limit-like orders: LIMIT and an elected STOP_LIMIT.
        limit = order.limit_price
        if limit is None:
            return MatchResult(status=OrderStatus.REJECTED,
                               reason="limit order without a limit price")

        if book.is_marketable(order.side, limit):
            if order.rested:
                # It was already sitting in the book and the market has now
                # crossed it. That makes this a PASSIVE fill at the trader's own
                # limit — they were in the queue, and the market came to them.
                # Treating it as a taker would both charge the wrong fee and
                # hand out price improvement the order could not have received:
                # a resting bid at 194.98 is hit at 194.98 as the market falls
                # through it, not at the 194.00 the market reached afterwards.
                qty = min(want, max(book.available(order.side.opposite),
                                    ctx.inst.min_qty))
                return MatchResult(fills=[self._make_fill(
                    order, ctx, qty, limit, Liquidity.MAKER)])
            if order.post_only:
                # Post-only exists to guarantee maker fees. If it would cross,
                # the venue rejects it rather than charging taker fees.
                return MatchResult(status=OrderStatus.REJECTED,
                                   reason="post-only order would cross the spread")
            qty, price = self._taker_fill(order, ctx, want, limit)
            if qty <= 0:
                return MatchResult(reason="no liquidity at touch")
            # Price improvement: a buy limit above the ask fills at the ask.
            price = min(price, limit) if order.side is Side.BUY else max(price, limit)
            fill = self._make_fill(order, ctx, qty, price, Liquidity.TAKER)
            return MatchResult(fills=[fill])

        # 5. Resting passive order. It fills only if the market trades through.
        traded = ctx.quote.last
        order.rested = True          # it is in the queue from here on
        if traded <= 0:
            return MatchResult()
        if self.require_trade_through:
            through = (traded < limit - 1e-12 if order.side is Side.BUY
                       else traded > limit + 1e-12)
        else:
            through = (traded <= limit + 1e-12 if order.side is Side.BUY
                       else traded >= limit - 1e-12)
        if not through:
            return MatchResult()

        # Passive fills are capped by what actually traded through, and a maker
        # never gets a worse price than their limit.
        qty = min(want, max(book.available(order.side.opposite),
                            ctx.inst.min_qty))
        fill = self._make_fill(order, ctx, qty, limit, Liquidity.MAKER)
        return MatchResult(fills=[fill])

    def _at_close(self, ctx: MatchContext) -> bool:
        """Is this the last chance to execute in the regular session?"""
        from ..clock import close_time_for, to_et
        if ctx.inst.asset_class.value != "equity":
            return False
        et = to_et(ctx.ts)
        close = close_time_for(et.date())
        minutes_to_close = (close.hour * 60 + close.minute) - (et.hour * 60 + et.minute)
        return ctx.session is Session.REGULAR and 0 <= minutes_to_close <= 5

    # -------------------------------------------------------- bar-based match

    def match_bar(self, order: Order, inst: Instrument, bar: Bar,
                  prev_close: float = 0.0) -> MatchResult:
        """Match against a completed OHLC bar, for backtesting.

        Assumptions, all deliberately pessimistic:

        * A market order fills at the bar's OPEN. A signal computed from a
          bar's close can only act on the next bar — filling at the close of
          the bar that produced the signal is lookahead, and it is the reason
          most published backtests do not survive contact with a broker.
        * A stop triggers if the bar's range covers it, and fills at the WORSE
          of the stop price and the bar's open. A gap open fills at the gap.
        * A limit fills only if the bar traded strictly through it, at the
          limit price — never at the better extreme of the bar.
        """
        quote = Quote(symbol=bar.symbol, ts=bar.ts, last=bar.close,
                      open=bar.open, high=bar.high, low=bar.low,
                      volume=bar.volume, prev_close=prev_close or bar.open,
                      source="bar")
        ctx = MatchContext.build(inst, quote, bar.ts)
        want = order.remaining
        if want <= 0 or not order.is_open:
            return MatchResult()

        otype = order.order_type

        if otype is OrderType.MARKET:
            price = self._apply_bar_slippage(order, inst, bar.open, quote)
            return MatchResult(fills=[self._make_fill(
                order, ctx, want, price, Liquidity.TAKER, reference=bar.open)])

        if otype is OrderType.MARKET_ON_CLOSE:
            price = self._apply_bar_slippage(order, inst, bar.close, quote)
            return MatchResult(fills=[self._make_fill(
                order, ctx, want, price, Liquidity.TAKER, reference=bar.close)])

        if order.needs_trigger and not order.triggered:
            self._update_trailing_bar(order, inst, bar)
            stop = order.stop_price
            if stop is None:
                return MatchResult()
            hit = (bar.high >= stop - 1e-12 if order.side is Side.BUY
                   else bar.low <= stop + 1e-12)
            if not hit:
                return MatchResult()
            order.triggered = True
            if otype in (OrderType.STOP, OrderType.TRAILING_STOP):
                # THE gap rule: a stop-buy elected by a gap-up fills at the
                # open, not at the stop. Taking the better of the two would
                # hand every stop a fill it could not have received.
                gapped = (max(stop, bar.open) if order.side is Side.BUY
                          else min(stop, bar.open))
                price = self._apply_bar_slippage(order, inst, gapped, quote)
                # Referenced against the STOP: the gap between where the trader
                # asked to exit and where they actually got out is the number
                # that matters, and it is the true cost of the gap.
                return MatchResult(fills=[self._make_fill(
                    order, ctx, want, price, Liquidity.TAKER, reference=stop)])
            # STOP_LIMIT becomes a resting limit within this same bar.

        limit = order.limit_price
        if limit is None:
            return MatchResult()
        through = (bar.low < limit - 1e-12 if order.side is Side.BUY
                   else bar.high > limit + 1e-12)
        if not through:
            return MatchResult()
        # Fill AT the limit. Filling at the bar's low for a buy would assume
        # you caught the exact bottom tick. A limit filled at its own price has
        # no slippage by definition, hence the limit as the reference.
        return MatchResult(fills=[self._make_fill(
            order, ctx, want, limit, Liquidity.MAKER, reference=limit)])

    def _apply_bar_slippage(self, order: Order, inst: Instrument, price: float,
                            quote: Quote) -> float:
        """Cross the modelled spread, then add impact — same model as live."""
        book = build_book(inst, quote, quote.ts)
        half_spread = (book.ask - book.bid) / 2.0
        crossed = price + order.side.sign * half_spread
        return self.slippage.apply(inst, order.side, order.remaining, crossed,
                                   quote, order.id).price

    def _update_trailing_bar(self, order: Order, inst: Instrument, bar: Bar) -> None:
        if order.order_type is not OrderType.TRAILING_STOP:
            return
        # Trail from the bar's favourable extreme — the best price it reached.
        extreme = bar.high if order.side is Side.SELL else bar.low
        if order.peak_price is None:
            order.peak_price = extreme
        if order.side is Side.SELL:
            order.peak_price = max(order.peak_price, extreme)
            offset = (order.trail_amount
                      or order.peak_price * (order.trail_pct or 0) / 100.0)
            new_stop = inst.round_price(order.peak_price - offset, Side.SELL)
            order.stop_price = (new_stop if order.stop_price is None
                                else max(order.stop_price, new_stop))
        else:
            order.peak_price = min(order.peak_price, extreme)
            offset = (order.trail_amount
                      or order.peak_price * (order.trail_pct or 0) / 100.0)
            new_stop = inst.round_price(order.peak_price + offset, Side.BUY)
            order.stop_price = (new_stop if order.stop_price is None
                                else min(order.stop_price, new_stop))
