"""Market data feeds.

`build_feed()` is the one place the platform decides where prices come from.
The default stack is:

    CachingFeed( CompositeFeed( FinvizFeed, SyntheticFeed ) )

Finviz is the live source. The synthetic feed sits behind it so an outage, a
rate limit or a blocked network degrades the platform visibly instead of taking
it down — `CompositeFeed.degraded` goes true, the UI says so, and no stale price
is ever passed off as live.
"""

from __future__ import annotations

from .base import (
    CircuitBreaker, CompositeFeed, Feed, FeedError, FeedHealth, FeedUnavailable,
    HttpClient, ParseError, RateLimited, RateLimiter, SymbolNotFound, is_stale,
    parse_number,
)
from .cache import CachingFeed, QuoteCache
from .finviz import FinvizFeed
from .synthetic import SyntheticFeed

__all__ = [
    "Feed", "FeedError", "FeedHealth", "FeedUnavailable", "ParseError",
    "RateLimited", "SymbolNotFound", "CompositeFeed", "CachingFeed",
    "QuoteCache", "FinvizFeed", "SyntheticFeed", "HttpClient", "RateLimiter",
    "CircuitBreaker", "is_stale", "parse_number", "build_feed",
]


def build_feed(mode: str = "auto", *, finviz_token: str = "",
               cache_ttl_s: float = 5.0, rate_per_s: float = 0.7,
               seed: int = 0) -> Feed:
    """Assemble the feed stack.

    mode="live"      Finviz only. Fails loudly when Finviz is unreachable.
    mode="synthetic" Simulator only. Deterministic; what tests and demos use.
    mode="auto"      Finviz with a simulated fallback. The production default.
    """
    mode = (mode or "auto").lower()
    if mode == "synthetic":
        return CachingFeed(SyntheticFeed(seed=seed), ttl_s=cache_ttl_s)
    live = FinvizFeed(auth_token=finviz_token, rate_per_s=rate_per_s)
    if mode == "live":
        return CachingFeed(live, ttl_s=cache_ttl_s)
    return CachingFeed(
        CompositeFeed(live, SyntheticFeed(seed=seed)), ttl_s=cache_ttl_s)
