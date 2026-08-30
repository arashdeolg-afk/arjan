"""Quote caching and last-known-good retention.

Two different jobs, deliberately kept apart:

**Cache** — inside the TTL, serve the stored quote and skip the vendor. A
trading screen refreshing every two seconds must not become two requests per
second per user against Finviz.

**Last known good** — outside the TTL, when the vendor fails, the previous
quote is still the best information available. It is returned *marked stale*,
never silently. Everything downstream can then make its own decision: the UI
greys the price, and the matching engine refuses to fill against it. The one
unacceptable behaviour is passing a stale price off as current, which is how
paper systems produce fills at prices that never existed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

from ..types import Bar, Quote
from .base import Feed, FeedError, FeedHealth, SymbolNotFound


@dataclass
class CacheEntry:
    quote: Quote
    stored_at: float
    hits: int = 0


class QuoteCache:
    """TTL cache with last-known-good retention. Thread-safe."""

    def __init__(self, ttl_s: float = 5.0, max_entries: int = 5000):
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._data: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self.stats = {"hits": 0, "misses": 0, "stale_served": 0, "evictions": 0}

    def get(self, symbol: str) -> Quote | None:
        """Fresh quote, or None. Never returns a stale one — ask `last_good`."""
        with self._lock:
            e = self._data.get(symbol.upper())
            if e and (time.monotonic() - e.stored_at) < self.ttl_s:
                e.hits += 1
                self.stats["hits"] += 1
                return e.quote
            self.stats["misses"] += 1
            return None

    def last_good(self, symbol: str) -> Quote | None:
        """The most recent quote at any age. Caller must treat it as stale."""
        with self._lock:
            e = self._data.get(symbol.upper())
            if e:
                self.stats["stale_served"] += 1
                return e.quote
            return None

    def put(self, quote: Quote) -> None:
        with self._lock:
            if len(self._data) >= self.max_entries and quote.symbol not in self._data:
                # Evict the oldest 10% in one pass; evicting one at a time turns
                # a full cache into a sort on every single write.
                victims = sorted(self._data.items(), key=lambda kv: kv[1].stored_at)
                for sym, _ in victims[: max(1, self.max_entries // 10)]:
                    del self._data[sym]
                    self.stats["evictions"] += 1
            self._data[quote.symbol.upper()] = CacheEntry(quote, time.monotonic())

    def put_all(self, quotes: dict[str, Quote]) -> None:
        for q in quotes.values():
            self.put(q)

    def invalidate(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol:
                self._data.pop(symbol.upper(), None)
            else:
                self._data.clear()

    def symbols(self) -> list[str]:
        with self._lock:
            return sorted(self._data)

    @property
    def hit_rate(self) -> float:
        total = self.stats["hits"] + self.stats["misses"]
        return self.stats["hits"] / total if total else 0.0


class CachingFeed(Feed):
    """Wraps any feed with a TTL cache and last-known-good fallback.

    A quote served from last-known-good comes back with `source` suffixed
    `+stale`, so staleness travels with the data instead of living in a flag
    somewhere the consumer might forget to check.
    """

    def __init__(self, inner: Feed, ttl_s: float = 5.0,
                 serve_stale_on_error: bool = True):
        self.inner = inner
        self.cache = QuoteCache(ttl_s)
        self.serve_stale_on_error = serve_stale_on_error
        self.name = f"{inner.name}+cache"
        self.supported = inner.supported

    def get_quote(self, symbol: str) -> Quote:
        sym = symbol.upper()
        if hit := self.cache.get(sym):
            return hit
        try:
            q = self.inner.get_quote(sym)
            self.cache.put(q)
            return q
        except SymbolNotFound:
            raise
        except FeedError:
            if self.serve_stale_on_error and (old := self.cache.last_good(sym)):
                return replace(old, source=f"{old.source}+stale")
            raise

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        wanted = [s.upper() for s in symbols]
        out: dict[str, Quote] = {}
        missing: list[str] = []
        for s in wanted:
            hit = self.cache.get(s)
            (out.__setitem__(s, hit) if hit else missing.append(s))
        if missing:
            try:
                fresh = self.inner.get_quotes(missing)
                self.cache.put_all(fresh)
                out.update(fresh)
            except FeedError:
                fresh = {}
            if self.serve_stale_on_error:
                for s in missing:
                    if s not in out and (old := self.cache.last_good(s)):
                        out[s] = replace(old, source=f"{old.source}+stale")
        return out

    def get_bars(self, symbol: str, interval: str = "1d", limit: int = 200) -> list[Bar]:
        return self.inner.get_bars(symbol, interval, limit)

    def health(self) -> FeedHealth:
        return self.inner.health()

    def close(self) -> None:
        self.inner.close()
