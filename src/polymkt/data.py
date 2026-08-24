"""Data API — who holds what, and what happened.

Positions, activity and holders. Public: everything is keyed by an
on-chain address, so no authentication is involved and no key ever has to
be present for any of it.
"""

from __future__ import annotations

from typing import Any

from .endpoints import SERVICES
from .http import Client, Transport, urllib_transport
from .models import Position, as_float


class Data:
    def __init__(self, transport: Transport = urllib_transport,
                 base_url: str | None = None) -> None:
        self.client = Client(base_url or SERVICES["data"], transport=transport)

    def positions(self, address: str, *, limit: int = 50, offset: int = 0,
                  size_threshold: float = 1.0, market: str | None = None,
                  sort_by: str = "CURRENT", **extra: Any) -> list[Position]:
        payload = self.client.get(
            "/positions", user=address, limit=limit, offset=offset,
            sizeThreshold=size_threshold, market=market, sortBy=sort_by, **extra,
        )
        return [Position.from_data(p) for p in _rows(payload)]

    def value(self, address: str, market: str | None = None) -> float | None:
        payload = self.client.get("/value", user=address, market=market)
        rows = _rows(payload)
        if not rows:
            return None
        return as_float(rows[0].get("value"))

    def activity(self, address: str, *, limit: int = 50, offset: int = 0,
                 kind: str | None = None) -> list[dict]:
        return _rows(self.client.get(
            "/activity", user=address, limit=limit, offset=offset, type=kind))

    def trades(self, *, address: str | None = None, market: str | None = None,
               limit: int = 50, offset: int = 0, taker_only: bool | None = None) -> list[dict]:
        return _rows(self.client.get(
            "/trades", user=address, market=market, limit=limit,
            offset=offset, takerOnly=taker_only))

    def holders(self, condition_id: str, *, limit: int = 20) -> list[dict]:
        return _rows(self.client.get("/holders", market=condition_id, limit=limit))


def _rows(payload: Any) -> list[dict]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in ("data", "positions", "activity", "holders", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return [row for row in payload if isinstance(row, dict)]
