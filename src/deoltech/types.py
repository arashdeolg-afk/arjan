"""Core value objects: the vocabulary every other module speaks.

Feeds produce `Quote` and `Bar`. The engine consumes `Order` and produces
`Fill`. The portfolio holds `Position` and `Lot`. Nothing else crosses a
module boundary, which is what keeps the matching engine testable without a
network, a database, or a clock.

Money is float here, not Decimal. Paper trading does not settle real cash, and
float keeps the hot loop simple — but every value that lands in the cash ledger
is rounded to the currency's minor unit on write (see `portfolio.round_money`),
so balances never accumulate 1e-13 dust across a million fills.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------- enums


class StrEnum(str, Enum):
    """str-valued enum: survives a round trip through SQLite and JSON as-is."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class AssetClass(StrEnum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FX = "fx"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"                 # stop-market
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    MARKET_ON_CLOSE = "moc"


class TimeInForce(StrEnum):
    DAY = "day"       # expires at session close
    GTC = "gtc"       # good till canceled
    GTD = "gtd"       # good till date (expires_at)
    IOC = "ioc"       # fill what you can right now, cancel the rest
    FOK = "fok"       # all of it right now, or nothing


class OrderStatus(StrEnum):
    """FIX-style lifecycle. Terminal states are the ones `is_terminal` names."""

    PENDING_NEW = "pending_new"          # accepted by us, not yet working
    NEW = "new"                          # working at the venue
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    PENDING_CANCEL = "pending_cancel"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in (
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )

    @property
    def is_open(self) -> bool:
        return not self.is_terminal


class Liquidity(StrEnum):
    MAKER = "maker"
    TAKER = "taker"


# ------------------------------------------------------------------ market data


@dataclass(frozen=True, slots=True)
class Quote:
    """Top of book at an instant.

    Feeds that only publish a last price (Finviz is one) leave bid/ask at 0 and
    let `engine.book` synthesize a two-sided market from the asset class's
    spread model. `is_synthetic` records which happened, because a fill against
    a modelled spread is a weaker claim than a fill against a real one.
    """

    symbol: str
    ts: datetime
    last: float
    bid: float = 0.0
    ask: float = 0.0
    bid_size: float = 0.0
    ask_size: float = 0.0
    volume: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = 0.0
    source: str = "unknown"
    is_synthetic_book: bool = False

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid) if self.bid > 0 and self.ask > 0 else 0.0

    @property
    def spread_bps(self) -> float:
        m = self.mid
        return (self.spread / m) * 10_000.0 if m > 0 else 0.0

    @property
    def change_pct(self) -> float:
        if self.prev_close > 0:
            return (self.last - self.prev_close) / self.prev_close * 100.0
        return 0.0

    def age_s(self, now: datetime | None = None) -> float:
        return ((now or utcnow()) - self.ts).total_seconds()

    def with_book(self, bid: float, ask: float, bid_size: float, ask_size: float) -> "Quote":
        return replace(
            self, bid=bid, ask=ask, bid_size=bid_size,
            ask_size=ask_size, is_synthetic_book=True,
        )


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV candle, timestamped at the bar's CLOSE."""

    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    interval: str = "1d"

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_up(self) -> bool:
        return self.close >= self.open


# ----------------------------------------------------------------------- orders


_ORDER_SEQ = {"n": 0}


def next_order_id(prefix: str = "ORD") -> str:
    _ORDER_SEQ["n"] += 1
    return f"{prefix}-{_ORDER_SEQ['n']:08d}"


def reset_order_ids(n: int = 0) -> None:
    """Test hook: make order ids deterministic across runs."""
    _ORDER_SEQ["n"] = n


@dataclass
class Order:
    symbol: str
    side: Side
    qty: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    trail_pct: float | None = None
    trail_amount: float | None = None
    tif: TimeInForce = TimeInForce.DAY
    expires_at: datetime | None = None

    # Execution flags
    post_only: bool = False       # reject rather than cross the spread (maker only)
    reduce_only: bool = False     # may shrink a position, never open or flip one
    display_qty: float | None = None   # iceberg: how much is visible to the tape
    allow_extended: bool = False  # may work outside regular trading hours

    # Bracket linkage: OTO parent -> children, OCO siblings cancel each other.
    parent_id: str | None = None
    oco_group: str | None = None
    take_profit: float | None = None
    stop_loss: float | None = None

    # Provenance
    strategy: str | None = None
    tag: str | None = None
    client_order_id: str = field(default_factory=next_order_id)

    # Mutable state, owned by the engine
    id: str = ""
    status: OrderStatus = OrderStatus.PENDING_NEW
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    fees_paid: float = 0.0
    reject_reason: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    triggered: bool = False       # stop orders: has the trigger fired yet
    peak_price: float | None = None   # trailing stops: best price seen so far
    rested: bool = False          # has sat in the book unfilled for a tick;
                                  # decides maker vs taker on a later crossing

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.client_order_id
        if self.qty <= 0:
            raise ValueError(f"order qty must be positive, got {self.qty}")
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and self.limit_price is None:
            raise ValueError(f"{self.order_type} requires a limit price")
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError(f"{self.order_type} requires a stop price")
        if self.order_type is OrderType.TRAILING_STOP and not (self.trail_pct or self.trail_amount):
            raise ValueError("trailing stop requires trail_pct or trail_amount")
        if self.tif is TimeInForce.GTD and self.expires_at is None:
            raise ValueError("GTD requires expires_at")

    @property
    def remaining(self) -> float:
        return max(0.0, self.qty - self.filled_qty)

    @property
    def is_open(self) -> bool:
        return self.status.is_open

    @property
    def notional_at(self) -> float:
        """Best guess at the order's notional, for pre-trade limit checks."""
        px = self.limit_price or self.stop_price or 0.0
        return self.qty * px

    @property
    def needs_trigger(self) -> bool:
        return self.order_type in (
            OrderType.STOP, OrderType.STOP_LIMIT, OrderType.TRAILING_STOP,
        )

    def touch(self) -> None:
        self.updated_at = utcnow()

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "tif": self.tif.value,
            "status": self.status.value,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "fees_paid": self.fees_paid,
            "reject_reason": self.reject_reason,
            "strategy": self.strategy,
            "tag": self.tag,
            "parent_id": self.parent_id,
            "oco_group": self.oco_group,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }


@dataclass(frozen=True, slots=True)
class Fill:
    """An execution. Immutable — the blotter is append-only by construction."""

    order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    ts: datetime
    fee: float = 0.0
    liquidity: Liquidity = Liquidity.TAKER
    slippage_bps: float = 0.0
    reference_price: float = 0.0   # what the mid was when the order arrived
    venue: str = "paper"

    @property
    def notional(self) -> float:
        return self.qty * self.price

    @property
    def cash_delta(self) -> float:
        """Signed cash effect including fees: buys drain, sells add."""
        return -self.side.sign * self.notional - self.fee


@dataclass
class Lot:
    """One tax lot. FIFO consumption keeps realized P&L auditable."""

    qty: float
    price: float
    ts: datetime
    fee: float = 0.0


@dataclass
class Position:
    symbol: str
    qty: float = 0.0                 # signed: negative is short
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    lots: list[Lot] = field(default_factory=list)
    opened_at: datetime | None = None
    last_price: float = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < 1e-12

    @property
    def is_long(self) -> bool:
        return self.qty > 1e-12

    @property
    def is_short(self) -> bool:
        return self.qty < -1e-12

    @property
    def direction(self) -> int:
        return 0 if self.is_flat else (1 if self.qty > 0 else -1)

    def market_value(self, price: float | None = None) -> float:
        return self.qty * (price if price is not None else self.last_price)

    def unrealized_pnl(self, price: float | None = None) -> float:
        px = price if price is not None else self.last_price
        if self.is_flat or px <= 0:
            return 0.0
        return (px - self.avg_price) * self.qty

    def unrealized_pct(self, price: float | None = None) -> float:
        px = price if price is not None else self.last_price
        if self.is_flat or self.avg_price <= 0 or px <= 0:
            return 0.0
        return (px - self.avg_price) / self.avg_price * 100.0 * self.direction

    @property
    def cost_basis(self) -> float:
        return abs(self.qty) * self.avg_price


# ------------------------------------------------------------------- utilities


def round_to_tick(price: float, tick: float, side: Side | None = None) -> float:
    """Snap a price to the instrument's tick grid.

    With a side, round conservatively — a buy limit rounds DOWN and a sell limit
    rounds UP — so tick rounding can never make an order more aggressive than
    the trader asked for.
    """
    if tick <= 0:
        return price
    n = price / tick
    if side is Side.BUY:
        k = math.floor(n + 1e-9)
    elif side is Side.SELL:
        k = math.ceil(n - 1e-9)
    else:
        k = math.floor(n + 0.5)
    return round(k * tick, 12)


def round_to_lot(qty: float, lot: float) -> float:
    """Snap a quantity DOWN to the lot grid. Never round a size up."""
    if lot <= 0:
        return qty
    return round(math.floor(qty / lot + 1e-9) * lot, 12)
