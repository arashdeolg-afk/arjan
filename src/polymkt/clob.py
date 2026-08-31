"""CLOB — live prices and order books.

Everything here is keyed by *token id* (one per outcome), not by market.
A yes/no market has two token ids and two independent books; their best
bids do not have to sum to 1, and the gap between them is the spread you
would actually cross.

Read-only by design. Placing an order requires an EIP-712 signature over
the order struct, which requires a secp256k1 implementation — a real
dependency, and this repo is stdlib-only. See docs/POLYMKT.md.
"""

from __future__ import annotations

from typing import Any

from .endpoints import END_CURSOR, FIRST_CURSOR, SERVICES
from .http import Client, Transport, urllib_transport
from .models import Book, Market, as_float


class Clob:
    def __init__(self, transport: Transport = urllib_transport,
                 base_url: str | None = None) -> None:
        self.client = Client(base_url or SERVICES["clob"], transport=transport)

    # -------------------------------------------------------------- state

    def ok(self) -> bool:
        try:
            self.client.get("/")
            return True
        except Exception:
            return False

    def market(self, condition_id: str) -> Market:
        return Market.from_clob(self.client.get(f"/markets/{condition_id}"))

    def markets(self, *, next_cursor: str | None = None) -> tuple[list[Market], str | None]:
        """One page of markets plus the cursor for the next one.

        The cursor is always sent, defaulting to FIRST_CURSOR ("MA==",
        base64 "0"). Omitting it is not the same request as starting at
        zero — the official client passes it on every paginated call.

        The end of the sequence is END_CURSOR ("LTE=", base64 "-1"), which
        is translated to None so callers can loop `while cursor:`.
        """
        payload = self.client.get(
            "/markets", next_cursor=next_cursor or FIRST_CURSOR) or {}
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
        if cursor in (END_CURSOR, "", None):
            cursor = None
        return [Market.from_clob(m) for m in rows or []], cursor

    # ------------------------------------------------------------- prices

    def book(self, token_id: str) -> Book:
        return Book.from_clob(self.client.get("/book", token_id=token_id) or {})

    def price(self, token_id: str, side: str = "buy") -> float | None:
        payload = self.client.get("/price", token_id=token_id, side=side) or {}
        return as_float(payload.get("price") if isinstance(payload, dict) else payload)

    def midpoint(self, token_id: str) -> float | None:
        payload = self.client.get("/midpoint", token_id=token_id) or {}
        return as_float(payload.get("mid") if isinstance(payload, dict) else payload)

    def spread(self, token_id: str) -> float | None:
        payload = self.client.get("/spread", token_id=token_id) or {}
        return as_float(payload.get("spread") if isinstance(payload, dict) else payload)

    def quote(self, token_id: str) -> dict[str, Any]:
        """One round trip, everything a snapshot needs.

        Derived from the book rather than the /price and /midpoint
        endpoints: three separate calls can straddle a trade and produce a
        bid above the ask. One book cannot.
        """
        book = self.book(token_id)
        return {
            "token_id": token_id,
            "bid": book.best_bid,
            "ask": book.best_ask,
            "mid": book.midpoint,
            "spread": book.spread,
            "bid_depth": sum(l.price * l.size for l in book.bids),
            "ask_depth": sum(l.price * l.size for l in book.asks),
        }

    def last_trade_price(self, token_id: str) -> float | None:
        """What the book last actually agreed on.

        On a thin market the midpoint can sit far from any real trade;
        this is the last price two people genuinely met at.
        """
        payload = self.client.get("/last-trade-price", token_id=token_id) or {}
        if isinstance(payload, dict):
            return as_float(payload.get("price"))
        return as_float(payload)

    def tick_size(self, token_id: str) -> float | None:
        """Minimum price increment. An off-tick price is rejected outright."""
        payload = self.client.get("/tick-size", token_id=token_id) or {}
        if isinstance(payload, dict):
            return as_float(payload.get("minimum_tick_size") or payload.get("tick_size"))
        return as_float(payload)

    def history(self, token_id: str, *, interval: str = "1d",
                fidelity: int | None = None, start_ts: int | None = None,
                end_ts: int | None = None) -> list[dict]:
        """Price history for one token.

        The query parameter is called `market` but takes a token id — a
        long-standing wart worth naming, because passing a condition id
        here returns an empty series rather than an error.
        """
        payload = self.client.get(
            "/prices-history", market=token_id, interval=interval,
            fidelity=fidelity, startTs=start_ts, endTs=end_ts,
        ) or {}
        rows = payload.get("history", []) if isinstance(payload, dict) else payload
        out = []
        for row in rows or []:
            price = as_float(row.get("p"))
            ts = row.get("t")
            if price is not None and ts is not None:
                out.append({"t": int(ts), "p": price})
        return out
