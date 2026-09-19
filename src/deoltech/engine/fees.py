"""Transaction costs.

The single most common way a paper-trading result lies is by ignoring costs. A
strategy that trades 40 times a day and clears $3 a trade is profitable on
paper and loses money in an account, and the entire difference is here.

Every schedule below is a real-world convention:

* **Equities** — zero commission at the retail brokers, but never actually
  free: the SEC Section 31 fee and the FINRA Trading Activity Fee are charged
  on *sells only*, and both are asymmetric in a way that matters to a strategy
  turning over intraday.
* **Crypto** — maker/taker basis points, tiered by 30-day volume. The
  maker/taker split is why `post_only` exists as an order flag.
* **FX** — commission per standard lot per side, plus the overnight swap that
  is charged (or paid) at the 17:00 ET value-date roll, tripled on Wednesday to
  carry the weekend.

Fees are returned as a `FeeBreakdown` rather than a float so the blotter can
show a trader exactly what they were charged and why.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..instruments import Instrument
from ..types import AssetClass, Liquidity, Side

# --- US regulatory rates (FY2025 schedule) ----------------------------------
# Section 31: charged on the seller, per dollar of principal.
SEC_FEE_RATE = 27.80 / 1_000_000
# FINRA Trading Activity Fee: per share sold, capped per trade.
TAF_PER_SHARE = 0.000166
TAF_MAX = 8.30


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    """Itemized cost of one execution, in the ACCOUNT currency.

    `Instrument.notional()` is quoted in the instrument's quote currency, so
    anything derived from it (crypto exchange fees, FX swap) must be converted
    before it lands here. Commission on FX is the exception: brokers quote it
    per lot in the account currency already.
    """

    commission: float = 0.0
    exchange: float = 0.0        # venue / ECN / maker-taker
    regulatory: float = 0.0      # SEC 31 + FINRA TAF
    clearing: float = 0.0
    swap: float = 0.0            # FX overnight financing
    borrow: float = 0.0          # short borrow accrual

    @property
    def total(self) -> float:
        return round(self.commission + self.exchange + self.regulatory
                     + self.clearing + self.swap + self.borrow, 6)

    def items(self) -> list[tuple[str, float]]:
        return [(k, v) for k, v in (
            ("commission", self.commission), ("exchange", self.exchange),
            ("regulatory", self.regulatory), ("clearing", self.clearing),
            ("swap", self.swap), ("borrow", self.borrow),
        ) if abs(v) > 1e-9]

    def __add__(self, other: "FeeBreakdown") -> "FeeBreakdown":
        return FeeBreakdown(
            self.commission + other.commission, self.exchange + other.exchange,
            self.regulatory + other.regulatory, self.clearing + other.clearing,
            self.swap + other.swap, self.borrow + other.borrow,
        )


@dataclass
class FeeSchedule:
    """One account's cost structure. Editable from the admin console."""

    # Equities
    equity_commission_per_share: float = 0.0
    equity_commission_per_trade: float = 0.0
    equity_min_commission: float = 0.0
    equity_regulatory_fees: bool = True

    # Crypto, in basis points of notional
    crypto_maker_bps: float = 10.0
    crypto_taker_bps: float = 15.0

    # FX, per standard lot (100k) per side
    fx_commission_per_lot: float = 3.50
    fx_min_commission: float = 0.0

    # Annualized short-borrow, applied to equity shorts held overnight
    borrow_enabled: bool = True

    # 30-day volume tiers for crypto: (volume_usd, maker_bps, taker_bps).
    crypto_tiers: list[tuple[float, float, float]] = field(default_factory=lambda: [
        (0.0, 10.0, 15.0),
        (100_000.0, 8.0, 12.0),
        (1_000_000.0, 5.0, 9.0),
        (10_000_000.0, 2.0, 6.0),
    ])

    def crypto_rates(self, volume_30d: float = 0.0) -> tuple[float, float]:
        maker, taker = self.crypto_maker_bps, self.crypto_taker_bps
        for threshold, m, t in sorted(self.crypto_tiers):
            if volume_30d >= threshold:
                maker, taker = m, t
        return maker, taker


DEFAULT_SCHEDULE = FeeSchedule()


def compute_fees(inst: Instrument, side: Side, qty: float, price: float, *,
                 schedule: FeeSchedule | None = None,
                 liquidity: Liquidity = Liquidity.TAKER,
                 volume_30d: float = 0.0,
                 quote_to_account: float = 1.0) -> FeeBreakdown:
    """Cost of one execution, in the account currency.

    `quote_to_account` converts from the instrument's quote currency (1.0 for
    anything quoted in USD on a USD account).
    """
    sch = schedule or DEFAULT_SCHEDULE
    qty = abs(qty)
    notional = inst.notional(qty, price)

    if inst.asset_class is AssetClass.EQUITY:
        commission = max(
            sch.equity_commission_per_share * qty + sch.equity_commission_per_trade,
            sch.equity_min_commission,
        ) if (sch.equity_commission_per_share or sch.equity_commission_per_trade
              or sch.equity_min_commission) else 0.0
        regulatory = 0.0
        if sch.equity_regulatory_fees and side is Side.SELL:
            # Both are sell-side only. A round trip therefore costs less than
            # twice a single leg, which changes break-even on scalps.
            regulatory = (notional * SEC_FEE_RATE
                          + min(TAF_MAX, qty * TAF_PER_SHARE))
        return FeeBreakdown(commission=round(commission, 4),
                            regulatory=round(regulatory, 4))

    if inst.asset_class is AssetClass.CRYPTO:
        maker_bps, taker_bps = sch.crypto_rates(volume_30d)
        bps = maker_bps if liquidity is Liquidity.MAKER else taker_bps
        return FeeBreakdown(
            exchange=round(notional * bps / 10_000.0 * quote_to_account, 6))

    # FX: per-lot commission, both sides.
    lots = qty / 100_000.0
    commission = max(sch.fx_commission_per_lot * lots, sch.fx_min_commission)
    return FeeBreakdown(commission=round(commission, 4))


# ------------------------------------------------------------------ financing

# Annualized swap in basis points of notional: (long, short). Positive means
# the holder pays. Derived from the two legs' policy-rate differential — carry
# is the whole reason a long AUD/JPY position behaves differently from a short.
SWAP_BPS: dict[str, tuple[float, float]] = {
    "EURUSD": (95.0, -55.0), "GBPUSD": (40.0, -10.0), "USDJPY": (-390.0, 430.0),
    "USDCHF": (-330.0, 370.0), "AUDUSD": (85.0, -45.0), "USDCAD": (30.0, 5.0),
    "NZDUSD": (55.0, -20.0), "EURGBP": (55.0, -20.0), "EURJPY": (-300.0, 340.0),
    "GBPJPY": (-350.0, 390.0), "AUDJPY": (-330.0, 370.0), "EURCHF": (40.0, -10.0),
    "USDMXN": (620.0, -580.0), "USDZAR": (450.0, -410.0), "USDTRY": (3800.0, -3600.0),
}
DEFAULT_SWAP_BPS = (120.0, -80.0)   # unknown pair: assume a costly carry both ways


def swap_charge(inst: Instrument, qty: float, price: float,
                multiplier: int = 1, quote_to_account: float = 1.0) -> FeeBreakdown:
    """Overnight FX financing at the 17:00 ET roll.

    `multiplier` is 3 on Wednesday, when the roll carries Saturday and Sunday.
    A positive result is a charge; negative means the position earns carry.

    Interest accrues on the position's **quote-currency** notional, so a long
    100k USD/JPY accrues in yen. `quote_to_account` converts that to the
    account's currency (for USD/JPY, roughly 1/147). Skipping the conversion
    inflates a $10/day carry into a $1,570/day one, which is a real and very
    easy mistake to make — hence the explicit argument rather than a default
    that silently applies to every pair.
    """
    if inst.asset_class is not AssetClass.FX or abs(qty) < 1e-9:
        return FeeBreakdown()
    long_bps, short_bps = SWAP_BPS.get(inst.symbol, DEFAULT_SWAP_BPS)
    bps = long_bps if qty > 0 else short_bps
    notional_quote = inst.notional(qty, price)
    daily_quote = notional_quote * (bps / 10_000.0) / 365.0
    return FeeBreakdown(swap=round(daily_quote * multiplier * quote_to_account, 6))


def borrow_charge(inst: Instrument, qty: float, price: float, days: float = 1.0,
                  schedule: FeeSchedule | None = None) -> FeeBreakdown:
    """Short borrow accrual. Only shorts pay, and hard-to-borrow names pay a lot.

    GME at 1500bps is not a hypothetical — a short held through a squeeze pays
    the borrow every single day, and a backtest that omits it is fiction.
    """
    sch = schedule or DEFAULT_SCHEDULE
    if not sch.borrow_enabled or qty >= 0 or inst.borrow_bps <= 0:
        return FeeBreakdown()
    notional = inst.notional(qty, price)
    return FeeBreakdown(
        borrow=round(notional * (inst.borrow_bps / 10_000.0) / 365.0 * days, 6))


def round_trip_cost_bps(inst: Instrument, notional: float,
                        schedule: FeeSchedule | None = None) -> float:
    """Total cost of a round trip in bps — the hurdle a trade must clear.

    Worth surfacing in the UI: a trader sizing a 0.1% scalp in a name whose
    round trip costs 0.25% is losing money by construction.
    """
    if notional <= 0:
        return 0.0
    price = 100.0
    qty = notional / (price * inst.multiplier)
    buy = compute_fees(inst, Side.BUY, qty, price, schedule=schedule)
    sell = compute_fees(inst, Side.SELL, qty, price, schedule=schedule)
    spread_cost = notional * (inst.typical_spread_bps / 10_000.0)   # cross once
    return (buy.total + sell.total + spread_cost) / notional * 10_000.0
