"""Slippage: what an order actually pays versus what the screen showed.

Three distinct costs, modelled separately because they behave differently and a
trader needs to be able to tell them apart:

1. **Spread** — crossing to the touch. Priced by `book`, not here.
2. **Market impact** — the price moves against you as you consume liquidity.
   Modelled with the square-root law, ``Δp/p = η·σ·√(Q/ADV)``, which is the
   most empirically supported functional form there is (Almgren et al.), and
   the reason a strategy that works on 100 shares stops working on 100,000.
3. **Latency** — the market moves between your decision and your fill. Small
   for a retail paper account, not zero, and it is systematically adverse:
   you are more likely to get filled when the price is moving toward you.

The model is **deterministic given the same inputs**. Randomized slippage would
make every backtest irreproducible and every regression test flaky, and it
would let a strategy author re-roll until they liked the answer. Where variation
is genuinely wanted, `noise_bps` derives it from the order id — reproducible per
order, uncorrelated across orders.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

from ..instruments import Instrument
from ..types import AssetClass, Quote, Side
from .book import BookState, realized_vol_bps

# Impact coefficient η in the square-root law, by asset class. Crypto is highest
# because its books are thinner relative to headline volume.
IMPACT_ETA = {
    AssetClass.EQUITY: 0.55,
    AssetClass.CRYPTO: 0.90,
    AssetClass.FX: 0.25,
}

# Default one-way latency by asset class, in milliseconds: a retail order over
# the public internet, not a colocated one.
LATENCY_MS = {
    AssetClass.EQUITY: 250.0,
    AssetClass.CRYPTO: 180.0,
    AssetClass.FX: 120.0,
}


@dataclass(frozen=True, slots=True)
class SlippageResult:
    price: float             # the actual fill price
    impact_bps: float
    latency_bps: float
    noise_bps: float
    total_bps: float         # signed against the trader: positive is worse

    @property
    def cost_vs(self) -> float:
        return self.total_bps


@dataclass
class SlippageModel:
    """Configurable execution-cost model. One per account."""

    enabled: bool = True
    impact_scale: float = 1.0          # 0 disables impact, 2 doubles it
    latency_scale: float = 1.0
    noise_bps: float = 0.0             # deterministic per-order jitter, in bps
    max_slippage_bps: float = 500.0    # sanity cap; a fill 5% through is a bug

    def impact_bps(self, inst: Instrument, qty: float, quote: Quote) -> float:
        """Square-root market impact, in basis points."""
        adv = quote.volume if quote.volume > 0 else inst.adv
        if adv <= 0 or qty <= 0:
            return 0.0
        participation = min(1.0, abs(qty) / adv)
        # Daily volatility as a fraction. The intraday range is roughly 1.5
        # standard deviations for a typical session, so divide it back out.
        sigma = max(0.002, realized_vol_bps(quote) / 10_000.0 / 1.5)
        eta = IMPACT_ETA.get(inst.asset_class, 0.6) * self.impact_scale
        return eta * sigma * math.sqrt(participation) * 10_000.0

    def latency_bps(self, inst: Instrument, quote: Quote) -> float:
        """Adverse drift over the round-trip latency window."""
        ms = LATENCY_MS.get(inst.asset_class, 200.0) * self.latency_scale
        sigma_daily = max(0.002, realized_vol_bps(quote) / 10_000.0 / 1.5)
        seconds = ms / 1000.0
        # Scale daily vol down to the latency window: σ_t = σ_day·√(t/86400).
        sigma_window = sigma_daily * math.sqrt(seconds / 86_400.0)
        # Half of that window's movement is adverse on average — the fill you
        # get is conditioned on the price having come to you.
        return sigma_window * 0.5 * 10_000.0

    def _noise(self, order_id: str) -> float:
        if self.noise_bps <= 0:
            return 0.0
        h = zlib.crc32(order_id.encode()) & 0xFFFFFFFF
        return (h / 0xFFFFFFFF - 0.5) * 2.0 * self.noise_bps

    def apply(self, inst: Instrument, side: Side, qty: float, touch_price: float,
              quote: Quote, order_id: str = "") -> SlippageResult:
        """Move `touch_price` against the trader by the modelled cost."""
        if not self.enabled or touch_price <= 0:
            return SlippageResult(touch_price, 0.0, 0.0, 0.0, 0.0)

        impact = self.impact_bps(inst, qty, quote)
        latency = self.latency_bps(inst, quote)
        noise = self._noise(order_id)
        total = min(self.max_slippage_bps, impact + latency + noise)

        # Always adverse in direction: a buy fills higher, a sell fills lower.
        adjusted = touch_price * (1.0 + side.sign * total / 10_000.0)
        # Round away from the trader, so tick rounding can never hand back the
        # slippage the model just charged.
        price = inst.round_price(adjusted, Side.SELL if side is Side.BUY else Side.BUY)
        price = max(inst.tick_size, price)
        return SlippageResult(price, round(impact, 4), round(latency, 4),
                              round(noise, 4), round(total, 4))


def walk_the_book(book: BookState, inst: Instrument, side: Side, qty: float,
                  levels: int = 8) -> tuple[float, float]:
    """Volume-weighted price for consuming `qty` across the synthetic ladder.

    Returns (vwap, filled_qty). Used for orders larger than the touch, where a
    single-price fill would understate the cost badly.
    """
    from .book import depth_ladder
    bids, asks = depth_ladder(book, inst, levels)
    ladder = asks if side is Side.BUY else bids

    remaining, cost, filled = abs(qty), 0.0, 0.0
    for price, size in ladder:
        if remaining <= 1e-12:
            break
        take = min(remaining, size)
        cost += take * price
        filled += take
        remaining -= take
    if filled <= 0:
        return book.touch(side), 0.0
    return cost / filled, filled
