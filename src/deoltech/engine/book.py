"""Order book synthesis.

Finviz publishes a last price. It does not publish a bid, an ask, or a depth
ladder — and neither does any free equity feed. So the engine has to construct
the two-sided market it needs to decide whether a limit order is marketable and
what a market order actually pays.

The honest way to do that is to model the spread explicitly and *label the
result as modelled* (`Quote.is_synthetic_book`), rather than pretending the
last trade is both the bid and the ask. That pretence is the second-biggest
source of fake paper-trading profits after ignoring fees: it hands every market
order a free half-spread, which is precisely the edge most short-term
strategies claim to have.

The spread model widens for the things that really do widen spreads:

* **Session** — a pre-market book is three to five times wider than a 10am one.
* **Volatility** — market makers charge for the risk of holding inventory.
* **Size** — the touch is only good for so many shares; past that you walk the
  book, which `slippage` prices.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..clock import Session, session_for
from ..instruments import Instrument
from ..types import AssetClass, Quote, Side

# Spread multipliers by session. Regular hours are the baseline.
SESSION_SPREAD_MULT = {
    Session.REGULAR: 1.0,
    Session.PREMARKET: 3.5,
    Session.AFTERHOURS: 3.0,
    Session.CLOSED: 6.0,
}

# Fraction of a day's volume displayed at the touch at any one moment. Very
# small, because it is: AAPL trades ~55M shares a day and shows a few hundred
# at the NBBO. Calibrated so the modelled touch sizes land in the observed
# range — hundreds of shares, single-digit BTC, a few million in EUR/USD.
TOUCH_LIQUIDITY_FRACTION = {
    AssetClass.EQUITY: 0.00002,
    AssetClass.CRYPTO: 0.00002,
    AssetClass.FX: 0.00040,
}


@dataclass(frozen=True, slots=True)
class BookState:
    """Top of book, plus the provenance needed to judge how much to trust it."""

    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    mid: float
    synthetic: bool
    session: Session
    spread_bps: float

    def touch(self, side: Side) -> float:
        """The price a marketable order of that side crosses to."""
        return self.ask if side is Side.BUY else self.bid

    def available(self, side: Side) -> float:
        """Displayed size a taker can hit immediately at the touch."""
        return self.ask_size if side is Side.BUY else self.bid_size

    def resting(self, side: Side) -> float:
        """The price a passive (maker) order of that side would join."""
        return self.bid if side is Side.BUY else self.ask

    def is_marketable(self, side: Side, limit_price: float) -> bool:
        return (limit_price >= self.ask - 1e-12 if side is Side.BUY
                else limit_price <= self.bid + 1e-12)


def realized_vol_bps(quote: Quote) -> float:
    """A cheap intraday volatility proxy: today's range as bps of mid.

    Not a substitute for a proper ATR — it is a *widening signal*, and the
    day's range is the one volatility measure available from a single quote.
    """
    if quote.high <= 0 or quote.low <= 0 or quote.mid <= 0:
        return 0.0
    return (quote.high - quote.low) / quote.mid * 10_000.0


def spread_bps_for(inst: Instrument, quote: Quote, session: Session) -> float:
    """Model the spread in basis points."""
    base = max(0.1, inst.typical_spread_bps)
    base *= SESSION_SPREAD_MULT.get(session, 1.0)

    # Volatility widening: a name whose day range is 4x its typical spread is
    # in a state where makers quote wider. Capped so a limit-up day does not
    # produce a nonsensical spread.
    vol = realized_vol_bps(quote)
    if vol > 0:
        base *= min(3.0, max(1.0, math.sqrt(vol / max(base * 8.0, 1.0))))

    # Low-priced instruments are tick-bound: a $2 stock cannot have a 1bp
    # spread, because one cent on $2 is 50bps.
    if quote.mid > 0:
        tick_bps = inst.tick_size / quote.mid * 10_000.0
        base = max(base, tick_bps)
    return base


def build_book(inst: Instrument, quote: Quote, now=None) -> BookState:
    """Return the real book when the feed has one, otherwise a modelled one."""
    session = session_for(inst.asset_class.value, now or quote.ts)

    if quote.bid > 0 and quote.ask > quote.bid:
        mid = (quote.bid + quote.ask) / 2.0
        return BookState(
            symbol=quote.symbol, bid=quote.bid, ask=quote.ask,
            bid_size=quote.bid_size or _touch_size(inst, quote),
            ask_size=quote.ask_size or _touch_size(inst, quote),
            mid=mid, synthetic=False, session=session,
            spread_bps=(quote.ask - quote.bid) / mid * 10_000.0 if mid else 0.0,
        )

    mid = quote.last
    if mid <= 0:
        raise ValueError(f"cannot build a book for {quote.symbol} at price {mid}")
    sbps = spread_bps_for(inst, quote, session)
    half = mid * (sbps / 2.0) / 10_000.0
    # A spread narrower than one tick cannot exist on a real venue.
    half = max(half, inst.tick_size / 2.0)

    bid = inst.round_price(mid - half, Side.BUY)
    ask = inst.round_price(mid + half, Side.SELL)
    if ask - bid < inst.tick_size:                 # rounding collapsed the spread
        ask = inst.round_price(bid + inst.tick_size, Side.SELL)

    size = _touch_size(inst, quote)
    return BookState(
        symbol=quote.symbol, bid=bid, ask=ask, bid_size=size, ask_size=size,
        mid=(bid + ask) / 2.0, synthetic=True, session=session,
        spread_bps=(ask - bid) / mid * 10_000.0,
    )


def _touch_size(inst: Instrument, quote: Quote) -> float:
    """How much is displayed at the touch right now."""
    frac = TOUCH_LIQUIDITY_FRACTION.get(inst.asset_class, 0.0003)
    daily = quote.volume if quote.volume > 0 else inst.adv
    session = session_for(inst.asset_class.value, quote.ts)
    if session is Session.PREMARKET or session is Session.AFTERHOURS:
        frac *= 0.15                # extended hours books are thin
    elif session is Session.CLOSED:
        frac *= 0.05
    size = daily * frac
    if inst.asset_class is AssetClass.EQUITY:
        return max(inst.lot_size, math.floor(size))
    return max(inst.min_qty, round(size, 8))


def depth_ladder(book: BookState, inst: Instrument, levels: int = 5
                 ) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """A synthetic depth ladder for display, and for walking the book.

    Size grows with distance from the touch — the standard shape of a real
    ladder, where the best price is the thinnest.
    """
    bids, asks = [], []
    for i in range(levels):
        step = inst.tick_size * (i + 1) * max(1, round(book.spread_bps / 4) or 1)
        growth = 1.0 + i * 0.85
        bids.append((inst.round_price(book.bid - i * step, Side.BUY),
                     round(book.bid_size * growth, 8)))
        asks.append((inst.round_price(book.ask + i * step, Side.SELL),
                     round(book.ask_size * growth, 8)))
    return bids, asks
