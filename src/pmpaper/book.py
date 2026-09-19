"""Order book snapshots and the fill model.

The fill model is where honest backtests are won or lost. Three costs kill
naive crypto-binary strategies, and all three are modelled here:

  1. SPREAD      — you buy at the ask and sell at the bid, never at mid.
  2. LATENCY     — you decide on the book at time t, but your order arrives
                   at t + latency and fills against the book THEN. If the
                   underlying moved against you in between, you eat it.
  3. FEES        — charged on notional, and they compound with volume.

Omit any one of them and a coin-flip strategy will look profitable.
"""

from __future__ import annotations

from dataclasses import dataclass

# Polymarket binaries are quoted in cents; sub-cent prices aren't tradeable.
TICK = 0.01
MIN_PRICE, MAX_PRICE = 0.01, 0.99


@dataclass(frozen=True)
class Snapshot:
    """One observation of the market and its underlying at a moment in time."""
    ts: float                 # epoch seconds
    window_start: float       # when this binary's window opened
    window_end: float         # when it resolves
    strike: float             # underlying price at window open; up/down measured vs this
    spot: float               # underlying price now
    yes_bid: float
    yes_ask: float
    yes_bid_size: float = 1e9
    yes_ask_size: float = 1e9

    @property
    def mid(self) -> float:
        return (self.yes_bid + self.yes_ask) / 2

    @property
    def spread(self) -> float:
        return self.yes_ask - self.yes_bid

    @property
    def time_to_expiry(self) -> float:
        """Seconds remaining. Clamped at zero; never negative."""
        return max(0.0, self.window_end - self.ts)


@dataclass(frozen=True)
class Fill:
    ts: float
    side: str                 # "buy" (long YES) or "sell" (short YES)
    price: float              # price actually paid/received, after crossing
    size: float               # number of contracts
    fee: float                # dollars
    intended_price: float     # price visible when the decision was made
    slippage: float           # intended -> actual, caused by latency
    window_end: float
    strike: float


class FillModel:
    """Converts an intent into a fill, or into nothing.

    `latency_ms` is the round trip from your decision to the order resting
    on the book. Retail over public internet is realistically 80-250ms;
    a colocated market maker is single digits. That gap is the entire
    reason naive latency arbitrage fails, so it is a first-class parameter.
    """

    def __init__(self, latency_ms: float = 150.0, fee_bps: float = 0.0,
                 max_size: float = 100.0):
        if latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")
        self.latency_ms = latency_ms
        self.fee_bps = fee_bps
        self.max_size = max_size

    def fee_for(self, price: float, size: float) -> float:
        return abs(price * size) * (self.fee_bps / 10_000.0)

    def execute(self, intent_side: str, size: float, seen: Snapshot,
                arrival: Snapshot | None) -> Fill | None:
        """Fill `size` contracts against the book as it is on ARRIVAL.

        `seen` is what the strategy looked at; `arrival` is the book after
        latency. Passing arrival=None means the market ended before the
        order landed — no fill, which is the correct outcome rather than a
        silently optimistic one.
        """
        if arrival is None or size <= 0:
            return None

        size = min(size, self.max_size)
        if intent_side == "buy":
            price, avail, intended = arrival.yes_ask, arrival.yes_ask_size, seen.yes_ask
        elif intent_side == "sell":
            price, avail, intended = arrival.yes_bid, arrival.yes_bid_size, seen.yes_bid
        else:
            raise ValueError(f"side must be 'buy' or 'sell', got {intent_side!r}")

        size = min(size, avail)
        if size <= 0 or not (MIN_PRICE <= price <= MAX_PRICE):
            return None

        # Slippage signed so positive always means "worse than expected".
        slip = (price - intended) if intent_side == "buy" else (intended - price)
        return Fill(
            ts=arrival.ts, side=intent_side, price=price, size=size,
            fee=self.fee_for(price, size), intended_price=intended,
            slippage=slip, window_end=arrival.window_end, strike=arrival.strike,
        )


def settle(fill: Fill, final_spot: float) -> float:
    """Realised PnL for one fill, after fees.

    YES resolves to 1 if the underlying finished strictly above the strike.
    An exact tie resolves DOWN, matching how these markets are written.
    """
    yes = 1.0 if final_spot > fill.strike else 0.0
    gross = (yes - fill.price) if fill.side == "buy" else (fill.price - yes)
    return gross * fill.size - fill.fee
