"""Synthetic payloads, shaped like the real ones.

Every number in this file is made up. It exists so that `polymkt demo`
runs with no network and no account, and so the tests can exercise the
whole stack — client, normalisation, storage, output — offline.

The *shapes* are the point: stringified JSON arrays in Gamma, string
prices in the CLOB, both sides of a book unsorted. If a real response
ever stops looking like this, `polymkt doctor` is what tells you.
"""

from __future__ import annotations

import json
from typing import Any

from .http import Response

GAMMA_MARKETS: list[dict] = [
    {
        "id": "512001",
        "question": "Will the Fed cut rates at the September meeting?",
        "slug": "fed-cut-september",
        "conditionId": "0xfed09",
        # Note the stringified arrays — this is the real Gamma shape.
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.62", "0.38"]),
        "clobTokenIds": json.dumps(["1001", "1002"]),
        "volumeNum": 4820000.0,
        "volume24hr": 310500.0,
        "liquidityNum": 265000.0,
        "endDate": "2026-09-17T00:00:00Z",
        "active": True,
        "closed": False,
        "bestBid": 0.61,
        "bestAsk": 0.63,
        "lastTradePrice": 0.62,
        "negRisk": False,
    },
    {
        "id": "512002",
        "question": "Will an AI model score above 90% on FrontierMath in 2026?",
        "slug": "frontiermath-90-2026",
        "conditionId": "0xfm90",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.19", "0.81"]),
        "clobTokenIds": json.dumps(["2001", "2002"]),
        "volumeNum": 1140000.0,
        "volume24hr": 88000.0,
        "liquidityNum": 71000.0,
        "endDate": "2026-12-31T00:00:00Z",
        "active": True,
        "closed": False,
        "bestBid": 0.18,
        "bestAsk": 0.21,
        "lastTradePrice": 0.19,
        "negRisk": False,
    },
    {
        "id": "512003",
        "question": "Which studio releases the highest-grossing animated film of 2026?",
        "slug": "top-animated-film-2026",
        "conditionId": "0xanim26",
        "outcomes": json.dumps(["Ghibli", "Pixar", "Sony", "Other"]),
        "outcomePrices": json.dumps(["0.31", "0.28", "0.17", "0.24"]),
        "clobTokenIds": json.dumps(["3001", "3002", "3003", "3004"]),
        "volumeNum": 396000.0,
        "volume24hr": 12400.0,
        "liquidityNum": 45000.0,
        "endDate": "2027-01-15T00:00:00Z",
        "active": True,
        "closed": False,
        "negRisk": True,
    },
]

GAMMA_EVENTS: list[dict] = [
    {
        "id": "9001",
        "title": "Fed decisions 2026",
        "slug": "fed-2026",
        "volume": 12400000.0,
        "liquidity": 890000.0,
        "endDate": "2026-12-31T00:00:00Z",
        "closed": False,
        "markets": [GAMMA_MARKETS[0]],
    },
    {
        "id": "9002",
        "title": "AI benchmarks 2026",
        "slug": "ai-benchmarks-2026",
        "volume": 3100000.0,
        "liquidity": 210000.0,
        "endDate": "2026-12-31T00:00:00Z",
        "closed": False,
        "markets": [GAMMA_MARKETS[1]],
    },
]

# Books are returned deliberately out of order, to prove the normaliser sorts.
CLOB_BOOKS: dict[str, dict] = {
    "1001": {
        "market": "0xfed09",
        "asset_id": "1001",
        "bids": [{"price": "0.58", "size": "4200"}, {"price": "0.61", "size": "900"},
                 {"price": "0.60", "size": "1500"}],
        "asks": [{"price": "0.65", "size": "3300"}, {"price": "0.63", "size": "1100"},
                 {"price": "0.64", "size": "2000"}],
    },
    # The complementary token. Its book is not a mirror of the Yes book:
    # bid_No != 1 - ask_Yes in practice, which is why both are stored.
    "1002": {
        "market": "0xfed09",
        "asset_id": "1002",
        "bids": [{"price": "0.35", "size": "2600"}, {"price": "0.37", "size": "1200"}],
        "asks": [{"price": "0.39", "size": "1400"}, {"price": "0.42", "size": "5000"}],
    },
    "2001": {
        "market": "0xfm90",
        "asset_id": "2001",
        "bids": [{"price": "0.18", "size": "2500"}, {"price": "0.15", "size": "8000"}],
        "asks": [{"price": "0.21", "size": "1800"}, {"price": "0.25", "size": "6000"}],
    },
    "2002": {
        "market": "0xfm90",
        "asset_id": "2002",
        "bids": [{"price": "0.79", "size": "3100"}, {"price": "0.75", "size": "9000"}],
        "asks": [{"price": "0.82", "size": "2200"}, {"price": "0.86", "size": "7400"}],
    },
}

DATA_POSITIONS: list[dict] = [
    {
        "title": "Will the Fed cut rates at the September meeting?",
        "conditionId": "0xfed09",
        "outcome": "Yes",
        "size": 500.0,
        "avgPrice": 0.44,
        "curPrice": 0.62,
        "currentValue": 310.0,
        "cashPnl": 90.0,
    },
]


def fake_transport(method: str, url: str, headers: dict[str, str],
                   body: bytes | None) -> Response:
    """A Transport that answers from the fixtures above. No network.

    Routing is by substring, which is crude but keeps the fixture honest:
    it only answers paths this package actually calls.
    """
    payload: Any
    if "/public-search" in url:
        payload = {"events": GAMMA_EVENTS, "markets": GAMMA_MARKETS[:1]}
    elif "/markets/slug/" in url:
        slug = url.rsplit("/", 1)[-1].split("?")[0]
        payload = [m for m in GAMMA_MARKETS if m["slug"] == slug]
    elif "gamma" in url and "/markets" in url:
        payload = GAMMA_MARKETS
    elif "gamma" in url and "/events" in url:
        payload = GAMMA_EVENTS
    elif "/book" in url:
        token = _param(url, "token_id")
        payload = CLOB_BOOKS.get(token, {"asset_id": token, "bids": [], "asks": []})
    elif "/prices-history" in url:
        payload = {"history": [{"t": 1756000000 + i * 3600, "p": 0.40 + i * 0.02}
                               for i in range(12)]}
    elif "/positions" in url:
        payload = DATA_POSITIONS
    elif "/value" in url:
        payload = [{"user": _param(url, "user"), "value": 310.0}]
    else:
        payload = []
    return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode()


def _param(url: str, key: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return (parse_qs(urlparse(url).query).get(key) or [""])[0]
