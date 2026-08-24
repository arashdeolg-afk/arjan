"""Normalising the payloads.

Polymarket's JSON has two habits that bite every integration:

1. **Stringified arrays.** Gamma returns `"outcomes": "[\\"Yes\\", \\"No\\"]"`
   — a JSON string *containing* JSON. Same for `outcomePrices` and
   `clobTokenIds`. Read them naively and you get a character-by-character
   iteration instead of two outcomes.
2. **Numbers as strings.** Prices and sizes arrive as `"0.53"`, and the
   same field is sometimes a float and sometimes a string depending on
   which service answered.

Everything below decodes once, at the edge, so the rest of the package
only ever sees real lists and real floats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


def as_float(value: Any, default: float | None = None) -> float | None:
    """Floats, strings, None — one answer, never an exception."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_list(value: Any) -> list[Any]:
    """Decode a field that may be a list, a JSON string holding a list, or junk."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return decoded if isinstance(decoded, list) else [decoded]
    return [value]


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _first(payload: dict, *keys: str, default: Any = None) -> Any:
    """Field names differ between Gamma and CLOB for the same concept."""
    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload[key]
    return default


@dataclass
class Outcome:
    """One side of a market. Its price *is* its implied probability."""

    name: str
    token_id: str | None
    price: float | None

    @property
    def percent(self) -> str:
        return "  ? " if self.price is None else f"{self.price * 100:5.1f}%"


@dataclass
class Market:
    """A single yes/no (or multi-outcome) question."""

    id: str
    question: str
    slug: str
    condition_id: str
    outcomes: list[Outcome] = field(default_factory=list)
    volume: float | None = None
    volume_24h: float | None = None
    liquidity: float | None = None
    end_date: str | None = None
    active: bool = True
    closed: bool = False
    best_bid: float | None = None
    best_ask: float | None = None
    last_trade_price: float | None = None
    neg_risk: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_gamma(cls, payload: dict) -> "Market":
        names = [str(n) for n in as_list(payload.get("outcomes"))]
        prices = [as_float(p) for p in as_list(payload.get("outcomePrices"))]
        tokens = [str(t) for t in as_list(payload.get("clobTokenIds"))]
        outcomes = [
            Outcome(
                name=names[i] if i < len(names) else f"outcome {i + 1}",
                token_id=tokens[i] if i < len(tokens) else None,
                price=prices[i] if i < len(prices) else None,
            )
            for i in range(max(len(names), len(prices), len(tokens)))
        ]
        return cls(
            id=str(_first(payload, "id", default="")),
            question=str(_first(payload, "question", "title", default="(untitled)")),
            slug=str(_first(payload, "slug", default="")),
            condition_id=str(_first(payload, "conditionId", "condition_id", default="")),
            outcomes=outcomes,
            volume=as_float(_first(payload, "volumeNum", "volume")),
            volume_24h=as_float(_first(payload, "volume24hr", "volume24hrClob")),
            liquidity=as_float(_first(payload, "liquidityNum", "liquidity")),
            end_date=_first(payload, "endDate", "end_date_iso"),
            active=as_bool(payload.get("active", True)),
            closed=as_bool(payload.get("closed", False)),
            best_bid=as_float(payload.get("bestBid")),
            best_ask=as_float(payload.get("bestAsk")),
            last_trade_price=as_float(payload.get("lastTradePrice")),
            neg_risk=as_bool(payload.get("negRisk", False)),
            raw=payload,
        )

    @classmethod
    def from_clob(cls, payload: dict) -> "Market":
        """The CLOB's market shape: tokens carry their own outcome + price."""
        outcomes = [
            Outcome(
                name=str(t.get("outcome") or "?"),
                token_id=str(t.get("token_id") or "") or None,
                price=as_float(t.get("price")),
            )
            for t in payload.get("tokens", []) or []
        ]
        return cls(
            id=str(_first(payload, "condition_id", "conditionId", default="")),
            question=str(_first(payload, "question", default="(untitled)")),
            slug=str(_first(payload, "market_slug", "slug", default="")),
            condition_id=str(_first(payload, "condition_id", "conditionId", default="")),
            outcomes=outcomes,
            end_date=_first(payload, "end_date_iso", "endDate"),
            active=as_bool(payload.get("active", True)),
            closed=as_bool(payload.get("closed", False)),
            neg_risk=as_bool(payload.get("neg_risk", False)),
            raw=payload,
        )

    @property
    def token_ids(self) -> list[str]:
        return [o.token_id for o in self.outcomes if o.token_id]

    def outcome(self, name: str) -> Outcome | None:
        target = name.strip().lower()
        for o in self.outcomes:
            if o.name.strip().lower() == target:
                return o
        return None

    def favourite(self) -> Outcome | None:
        """The outcome the market currently thinks is most likely."""
        priced = [o for o in self.outcomes if o.price is not None]
        return max(priced, key=lambda o: o.price or 0.0) if priced else None

    def book_sum(self) -> float | None:
        """Outcome prices should sum to ~1. A drift is a data or arb signal."""
        priced = [o.price for o in self.outcomes if o.price is not None]
        return sum(priced) if priced else None


@dataclass
class Event:
    """A group of related markets, e.g. one election with a market per seat."""

    id: str
    title: str
    slug: str
    markets: list[Market] = field(default_factory=list)
    volume: float | None = None
    liquidity: float | None = None
    end_date: str | None = None
    closed: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_gamma(cls, payload: dict) -> "Event":
        return cls(
            id=str(_first(payload, "id", default="")),
            title=str(_first(payload, "title", "question", default="(untitled)")),
            slug=str(_first(payload, "slug", default="")),
            markets=[Market.from_gamma(m) for m in payload.get("markets", []) or []],
            volume=as_float(_first(payload, "volume", "volumeNum")),
            liquidity=as_float(_first(payload, "liquidity", "liquidityNum")),
            end_date=_first(payload, "endDate"),
            closed=as_bool(payload.get("closed", False)),
            raw=payload,
        )


@dataclass
class Level:
    price: float
    size: float


@dataclass
class Book:
    """One outcome token's order book, with both sides sorted best-first.

    The server's ordering is not relied on: bids descend, asks ascend,
    always, so `best_bid`/`best_ask` cannot silently invert.
    """

    token_id: str
    bids: list[Level] = field(default_factory=list)
    asks: list[Level] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_clob(cls, payload: dict) -> "Book":
        def levels(key: str) -> list[Level]:
            out = []
            for row in payload.get(key, []) or []:
                price = as_float(row.get("price"))
                size = as_float(row.get("size"))
                if price is not None and size:
                    out.append(Level(price, size))
            return out

        return cls(
            token_id=str(_first(payload, "asset_id", "token_id", default="")),
            bids=sorted(levels("bids"), key=lambda l: l.price, reverse=True),
            asks=sorted(levels("asks"), key=lambda l: l.price),
            raw=payload,
        )

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def midpoint(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def sweep(self, usd: float, side: str = "buy") -> tuple[float | None, float]:
        """Average fill price for spending `usd`, and how much of it fills.

        Prediction-market books are thin. The midpoint is what you quote;
        this is what you would actually pay. Returns (avg_price, filled_usd)
        and a partial fill when the book runs out.
        """
        levels = self.asks if side == "buy" else self.bids
        remaining, shares, spent = usd, 0.0, 0.0
        for level in levels:
            capacity = level.price * level.size
            take = min(remaining, capacity)
            if take <= 0:
                break
            shares += take / level.price
            spent += take
            remaining -= take
            if remaining <= 1e-9:
                break
        return (spent / shares if shares else None), spent


@dataclass
class Position:
    """One account's stake in one outcome."""

    title: str
    outcome: str
    size: float
    avg_price: float | None
    current_price: float | None
    value: float | None
    pnl: float | None
    condition_id: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_data(cls, payload: dict) -> "Position":
        return cls(
            title=str(_first(payload, "title", "question", "slug", default="(unknown)")),
            outcome=str(_first(payload, "outcome", default="?")),
            size=as_float(payload.get("size"), 0.0) or 0.0,
            avg_price=as_float(_first(payload, "avgPrice", "avg_price")),
            current_price=as_float(_first(payload, "curPrice", "currentPrice")),
            value=as_float(payload.get("currentValue")),
            pnl=as_float(_first(payload, "cashPnl", "percentPnl")),
            condition_id=str(_first(payload, "conditionId", "condition_id", default="")),
            raw=payload,
        )
