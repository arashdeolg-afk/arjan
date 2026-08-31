"""The Polymarket API surface, written down as data rather than as code.

Why a catalog instead of just methods: this package was written in an
environment with no network access to Polymarket, so the base URLs come
from the published overview but the individual paths and parameter names
come from prior knowledge and have not been checked against a live server.
Rather than pretend otherwise, every entry carries its provenance, and
`polymkt doctor` probes the whole catalog and reports what actually
answers. Once a run confirms an entry, promote its `confidence` to
"verified" and note the date in docs/POLYMKT.md.

Legend for `confidence`, weakest to strongest:
  recall     — believed correct, never confirmed against anything
  documented — taken from Polymarket's own published API overview
  client     — matches Polymarket's official py-clob-client source, read
               from PyPI 0.34.6 on 2026-08-24. Their spelling, not mine —
               but still their code, not a live response, so a path could
               in principle be deprecated server-side.
  verified   — confirmed by a `doctor` run against the live API
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Base URLs. These are from the published overview, so they are the one
# part of this file that is not guesswork.
SERVICES: dict[str, str] = {
    "gamma": "https://gamma-api.polymarket.com",
    "clob": "https://clob.polymarket.com",
    "data": "https://data-api.polymarket.com",
    "relayer": "https://relayer-v2.polymarket.com",
    "bridge": "https://bridge.polymarket.com",
}

# Realtime streams. Not used by this package yet — the stdlib has no
# WebSocket client, and writing one is a bigger commitment than it looks.
# Pagination sentinels, from the official client's constants. A paginated
# read starts at FIRST_CURSOR — omitting it is not the same request.
FIRST_CURSOR = "MA=="   # base64 "0"
END_CURSOR = "LTE="     # base64 "-1", the server saying "no more pages"

WEBSOCKETS: dict[str, str] = {
    "market": "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    "user": "wss://ws-subscriptions-clob.polymarket.com/ws/user",
}


@dataclass(frozen=True)
class Endpoint:
    name: str
    service: str
    method: str
    path: str
    summary: str
    params: tuple[str, ...] = ()
    confidence: str = "recall"
    # A cheap, side-effect-free call `doctor` can make to see if this is real.
    probe: dict[str, Any] | None = None
    # Set when the path needs a value doctor cannot invent (an address, a
    # token id). Those are probed only when the user supplies one.
    needs: str | None = None
    auth: bool = False

    def url(self, **path_args: Any) -> str:
        base = SERVICES[self.service].rstrip("/")
        return base + self.path.format(**path_args)


def _e(*args: Any, **kw: Any) -> Endpoint:
    return Endpoint(*args, **kw)


CATALOG: tuple[Endpoint, ...] = (
    # ---------------------------------------------------------- gamma
    _e("gamma.events", "gamma", "GET", "/events",
       "Discover events (an event groups related markets).",
       params=("limit", "offset", "order", "ascending", "slug", "id", "tag_id",
               "active", "closed", "archived", "liquidity_min", "volume_min",
               "start_date_min", "end_date_min"),
       probe={"limit": 1, "closed": "false"}),
    _e("gamma.event", "gamma", "GET", "/events/{event_id}",
       "One event by numeric id.", needs="event_id"),
    _e("gamma.event_by_slug", "gamma", "GET", "/events/slug/{slug}",
       "One event by URL slug.", needs="slug"),
    _e("gamma.markets", "gamma", "GET", "/markets",
       "Discover markets. The workhorse for finding tradeable questions.",
       params=("limit", "offset", "order", "ascending", "slug", "id",
               "condition_ids", "clob_token_ids", "active", "closed",
               "archived", "liquidity_num_min", "volume_num_min",
               "start_date_min", "end_date_min", "tag_id"),
       probe={"limit": 1, "closed": "false"}),
    _e("gamma.market", "gamma", "GET", "/markets/{market_id}",
       "One market by numeric id.", needs="market_id"),
    _e("gamma.market_by_slug", "gamma", "GET", "/markets/slug/{slug}",
       "One market by URL slug.", needs="slug"),
    _e("gamma.tags", "gamma", "GET", "/tags",
       "Category tags, for filtering discovery by subject.",
       params=("limit", "offset"), probe={"limit": 1}),
    _e("gamma.search", "gamma", "GET", "/public-search",
       "Free-text search across events and markets.",
       params=("q", "limit_per_type", "events_status"),
       probe={"q": "election", "limit_per_type": 1}),

    # ----------------------------------------------------------- clob
    # Every path below marked "client" was read out of Polymarket's own
    # py-clob-client 0.34.6 source, so the spelling is theirs, not mine.
    _e("clob.ok", "clob", "GET", "/", "Health check.",
       probe={}, confidence="client"),
    _e("clob.time", "clob", "GET", "/time",
       "Server time. The cheapest possible reachability check.",
       probe={}, confidence="client"),
    _e("clob.markets", "clob", "GET", "/markets",
       "Paginated market list, keyed by condition id.",
       params=("next_cursor",), probe={"next_cursor": FIRST_CURSOR},
       confidence="client"),
    _e("clob.market", "clob", "GET", "/markets/{condition_id}",
       "One market's CLOB view, including its outcome token ids.",
       needs="condition_id", confidence="client"),
    _e("clob.simplified_markets", "clob", "GET", "/simplified-markets",
       "Market list trimmed to the fields a trading UI needs.",
       params=("next_cursor",), probe={"next_cursor": FIRST_CURSOR},
       confidence="client"),
    _e("clob.sampling_markets", "clob", "GET", "/sampling-markets",
       "Markets that currently carry liquidity rewards.",
       params=("next_cursor",), probe={"next_cursor": FIRST_CURSOR},
       confidence="client"),
    _e("clob.sampling_simplified_markets", "clob", "GET",
       "/sampling-simplified-markets",
       "Reward-bearing markets, trimmed.",
       params=("next_cursor",), probe={"next_cursor": FIRST_CURSOR},
       confidence="client"),
    _e("clob.book", "clob", "GET", "/book",
       "Full order book for one outcome token.",
       params=("token_id",), needs="token_id", confidence="client"),
    _e("clob.books", "clob", "POST", "/books",
       "Order books for many tokens at once. Body is a list of "
       "{token_id, side}.", needs="token_id", confidence="client"),
    _e("clob.price", "clob", "GET", "/price",
       "Best price on one side of the book.",
       params=("token_id", "side"), needs="token_id", confidence="client"),
    _e("clob.midpoint", "clob", "GET", "/midpoint",
       "Midpoint between best bid and best ask — the usual 'probability'.",
       params=("token_id",), needs="token_id", confidence="client"),
    _e("clob.spread", "clob", "GET", "/spread",
       "Bid/ask spread for one token.",
       params=("token_id",), needs="token_id", confidence="client"),
    _e("clob.last_trade_price", "clob", "GET", "/last-trade-price",
       "Price of the most recent trade — what the book last agreed on.",
       params=("token_id",), needs="token_id", confidence="client"),
    _e("clob.tick_size", "clob", "GET", "/tick-size",
       "Minimum price increment; an off-tick order is rejected.",
       params=("token_id",), needs="token_id", confidence="client"),
    _e("clob.neg_risk", "clob", "GET", "/neg-risk",
       "Whether a market is neg-risk (multi-outcome, mutually exclusive).",
       params=("token_id",), needs="token_id", confidence="client"),
    _e("clob.prices_history", "clob", "GET", "/prices-history",
       "Historical price series. The param is named `market` but takes a "
       "TOKEN id. Absent from the official client, so unlike its neighbours "
       "this one is still pure recall.",
       params=("market", "interval", "startTs", "endTs", "fidelity"),
       needs="token_id"),

    # ----------------------------------------------------------- data
    _e("data.positions", "data", "GET", "/positions",
       "Open positions for one account.",
       params=("user", "market", "sizeThreshold", "limit", "offset",
               "sortBy", "sortDirection"),
       needs="address"),
    _e("data.value", "data", "GET", "/value",
       "Current portfolio value for one account.",
       params=("user", "market"), needs="address"),
    _e("data.activity", "data", "GET", "/activity",
       "Account history: trades, splits, merges, redeems, rewards.",
       params=("user", "limit", "offset", "type", "market"), needs="address"),
    _e("data.trades", "data", "GET", "/trades",
       "Public trade prints, filterable by account or market.",
       params=("user", "market", "limit", "offset", "takerOnly"),
       probe={"limit": 1}),
    _e("data.holders", "data", "GET", "/holders",
       "Largest holders of a market's outcome tokens.",
       params=("market", "limit"), needs="condition_id"),
)

BY_NAME: dict[str, Endpoint] = {e.name: e for e in CATALOG}


def for_service(service: str) -> list[Endpoint]:
    return [e for e in CATALOG if e.service == service]


def probeable() -> list[Endpoint]:
    """Endpoints `doctor` can call with no user-supplied identifiers."""
    return [e for e in CATALOG if e.probe is not None and not e.auth]
