"""Gamma — discovery. Which questions exist, and what are they called?

Gamma is the metadata layer: it knows slugs, titles, tags, end dates and
the CLOB token ids you need before you can ask the CLOB anything. Start
every workflow here.
"""

from __future__ import annotations

from typing import Any

from .endpoints import SERVICES
from .http import Client, Transport, urllib_transport
from .models import Event, Market


class Gamma:
    def __init__(self, transport: Transport = urllib_transport,
                 base_url: str | None = None) -> None:
        self.client = Client(base_url or SERVICES["gamma"], transport=transport)

    # ------------------------------------------------------------ markets

    def markets(self, *, limit: int = 20, offset: int = 0, closed: bool | None = False,
                active: bool | None = True, order: str | None = "volumeNum",
                ascending: bool = False, tag_id: int | None = None,
                volume_min: float | None = None, **extra: Any) -> list[Market]:
        """Markets, busiest first by default.

        `order` is a raw Gamma field name, so it is passed through rather
        than validated — an unknown one is the server's error to report,
        not ours to guess at.
        """
        payload = self.client.get(
            "/markets", limit=limit, offset=offset, closed=closed, active=active,
            order=order, ascending=ascending, tag_id=tag_id,
            volume_num_min=volume_min, **extra,
        )
        return [Market.from_gamma(m) for m in _rows(payload)]

    def market(self, market_id: str | int) -> Market:
        return Market.from_gamma(_one(self.client.get(f"/markets/{market_id}")))

    def market_by_slug(self, slug: str) -> Market:
        return Market.from_gamma(_one(self.client.get(f"/markets/slug/{slug}")))

    # ------------------------------------------------------------- events

    def events(self, *, limit: int = 20, offset: int = 0, closed: bool | None = False,
               order: str | None = "volume", ascending: bool = False,
               tag_id: int | None = None, **extra: Any) -> list[Event]:
        payload = self.client.get(
            "/events", limit=limit, offset=offset, closed=closed, order=order,
            ascending=ascending, tag_id=tag_id, **extra,
        )
        return [Event.from_gamma(e) for e in _rows(payload)]

    def event(self, event_id: str | int) -> Event:
        return Event.from_gamma(_one(self.client.get(f"/events/{event_id}")))

    def event_by_slug(self, slug: str) -> Event:
        return Event.from_gamma(_one(self.client.get(f"/events/slug/{slug}")))

    # ------------------------------------------------------------- search

    def search(self, query: str, *, limit: int = 10) -> dict[str, list]:
        """Free-text search. Returns {'events': [...], 'markets': [...]}.

        The response shape has moved around historically, so both the
        grouped form and a bare list are accepted.
        """
        payload = self.client.get("/public-search", q=query, limit_per_type=limit)
        if isinstance(payload, list):
            return {"events": [Event.from_gamma(e) for e in payload], "markets": []}
        payload = payload or {}
        return {
            "events": [Event.from_gamma(e) for e in payload.get("events", []) or []],
            "markets": [Market.from_gamma(m) for m in payload.get("markets", []) or []],
        }

    def tags(self, *, limit: int = 100) -> list[dict]:
        return _rows(self.client.get("/tags", limit=limit))


def _rows(payload: Any) -> list[dict]:
    """Gamma sometimes wraps a list in {'data': [...]}, sometimes not."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in ("data", "markets", "events", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return [row for row in payload if isinstance(row, dict)]


def _one(payload: Any) -> dict:
    rows = _rows(payload)
    if not rows:
        raise LookupError("no such market/event")
    return rows[0]
