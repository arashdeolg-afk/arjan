"""Feed contract, HTTP plumbing, and failover.

Every feed answers the same three questions — what is this trading at, what has
it traded at, and are you healthy — so the engine above never learns which
vendor it is talking to. That matters because market data vendors go down, rate
limit you, change their HTML, and serve stale prices, and none of those should
reach the matching engine as a silent bad fill.

The defenses here are the boring, load-bearing ones: a token bucket so we never
hammer a vendor, exponential backoff with jitter on transient failures, a
circuit breaker so a dead vendor fails fast instead of blocking every request
for a timeout's worth of seconds, and a staleness check so a quote frozen at
yesterday's close is reported as stale rather than traded on.
"""

from __future__ import annotations

import gzip
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..types import AssetClass, Bar, Quote, utcnow

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# A quote older than this is not a price, it is a memory.
DEFAULT_STALE_AFTER_S = 900.0


# ------------------------------------------------------------------- errors


class FeedError(Exception):
    """Base for anything that goes wrong fetching market data."""


class SymbolNotFound(FeedError):
    """The vendor has no such instrument. Retrying will not help."""


class RateLimited(FeedError):
    """Vendor asked us to slow down. Retryable, after a wait."""

    def __init__(self, msg: str, retry_after: float = 60.0):
        super().__init__(msg)
        self.retry_after = retry_after


class FeedUnavailable(FeedError):
    """Transport or parse failure. Retryable, and trips the breaker."""


class ParseError(FeedUnavailable):
    """The response arrived but did not look like anything we know how to read.

    Separate from a transport error on purpose: this is the signal that the
    vendor changed their format, which needs a human, not a retry.
    """


# --------------------------------------------------------------- rate limiting


class RateLimiter:
    """Token bucket. Thread-safe, because the web app serves requests in threads."""

    def __init__(self, rate_per_s: float, burst: int = 5):
        self.rate = max(0.01, rate_per_s)
        self.burst = max(1, burst)
        self._tokens = float(self.burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait = (1.0 - self._tokens) / self.rate
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.25))


class CircuitBreaker:
    """Fail fast when a vendor is down; probe occasionally to see if it's back.

    CLOSED -> (failures >= threshold) -> OPEN -> (cooldown elapsed) -> HALF_OPEN
    -> success -> CLOSED, or failure -> OPEN again.
    """

    def __init__(self, threshold: int = 5, cooldown_s: float = 60.0):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._failures < self.threshold:
                return "closed"
            if time.monotonic() - self._opened_at >= self.cooldown_s:
                return "half_open"
            return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold:
                self._opened_at = time.monotonic()

    def reset(self) -> None:
        self.record_success()


# ------------------------------------------------------------------ transport


@dataclass
class HttpResponse:
    url: str
    status: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    from_cache: bool = False


class HttpClient:
    """Small, dependency-free HTTP client with the retry semantics we need.

    Deliberately not a general-purpose client: it does exactly one thing, GET a
    URL and hand back decoded text, with the failure taxonomy the feeds above
    expect. Honors HTTPS_PROXY through urllib's default environment handling.
    """

    def __init__(self, *, rate_per_s: float = 1.0, burst: int = 4,
                 timeout: float = 12.0, max_retries: int = 3,
                 user_agent: str = USER_AGENT, breaker: CircuitBreaker | None = None):
        self.limiter = RateLimiter(rate_per_s, burst)
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.breaker = breaker or CircuitBreaker()
        self.stats = {"requests": 0, "errors": 0, "retries": 0, "bytes": 0}
        self._etags: dict[str, str] = {}

    def _decode(self, raw: bytes, encoding: str, charset: str) -> str:
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw.decode(charset, errors="replace")

    def get(self, url: str, params: dict | None = None,
            headers: dict | None = None) -> HttpResponse:
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
        if not self.breaker.allow():
            raise FeedUnavailable(f"circuit open for {urllib.parse.urlparse(url).netloc}")
        if not self.limiter.acquire():
            raise RateLimited("local rate limiter timed out", retry_after=5.0)

        hdrs = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
            **(headers or {}),
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            try:
                self.stats["requests"] += 1
                req = urllib.request.Request(url, headers=hdrs, method="GET")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    meta = {k.lower(): v for k, v in resp.headers.items()}
                    body = self._decode(
                        raw, meta.get("content-encoding", "").lower(),
                        resp.headers.get_content_charset() or "utf-8")
                self.stats["bytes"] += len(raw)
                self.breaker.record_success()
                return HttpResponse(url, 200, body, meta,
                                    (time.monotonic() - started) * 1000.0)
            except urllib.error.HTTPError as e:
                self.stats["errors"] += 1
                if e.code == 404:
                    self.breaker.record_success()   # a 404 is an answer, not an outage
                    raise SymbolNotFound(f"404 for {url}") from e
                if e.code in (429, 503):
                    retry_after = float(e.headers.get("Retry-After", 0) or 0)
                    last_error = RateLimited(f"HTTP {e.code} from vendor",
                                             retry_after or 30.0)
                elif 400 <= e.code < 500:
                    # 401/403 are policy answers — an egress block or a vendor
                    # ban. Retrying just burns the budget and looks like abuse.
                    self.breaker.record_failure()
                    raise FeedUnavailable(f"HTTP {e.code} for {url}") from e
                else:
                    last_error = FeedUnavailable(f"HTTP {e.code} for {url}")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                self.stats["errors"] += 1
                last_error = FeedUnavailable(f"{type(e).__name__}: {e}")

            if attempt < self.max_retries:
                self.stats["retries"] += 1
                # Exponential backoff with full jitter: without the jitter,
                # every worker that failed together retries together.
                backoff = min(8.0, 0.5 * (2 ** attempt))
                time.sleep(random.uniform(0, backoff))

        self.breaker.record_failure()
        raise last_error or FeedUnavailable(f"failed to fetch {url}")

    def get_json(self, url: str, params: dict | None = None) -> object:
        resp = self.get(url, params, headers={"Accept": "application/json"})
        try:
            return json.loads(resp.body)
        except json.JSONDecodeError as e:
            head = resp.body[:160].replace("\n", " ")
            raise ParseError(f"expected JSON from {url}, got: {head!r}") from e


# ---------------------------------------------------------------- feed contract


@dataclass
class FeedHealth:
    name: str
    ok: bool
    breaker: str = "closed"
    last_success: datetime | None = None
    last_error: str | None = None
    requests: int = 0
    errors: int = 0

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 0.0


class Feed(ABC):
    """What every market data source must provide."""

    name: str = "feed"
    supported: tuple[AssetClass, ...] = (
        AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FX,
    )

    def supports(self, asset_class: AssetClass) -> bool:
        return asset_class in self.supported

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """Latest top-of-book (or last trade) for one symbol."""

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Batch fetch. Override when the vendor has a bulk endpoint — most do,
        and one request for forty symbols beats forty requests every time."""
        out: dict[str, Quote] = {}
        for s in symbols:
            try:
                out[s.upper()] = self.get_quote(s)
            except FeedError:
                continue
        return out

    def get_bars(self, symbol: str, interval: str = "1d", limit: int = 200) -> list[Bar]:
        raise FeedUnavailable(f"{self.name} does not serve historical bars")

    def health(self) -> FeedHealth:
        return FeedHealth(name=self.name, ok=True)

    def close(self) -> None:
        """Release any held resources. Safe to call more than once."""


class CompositeFeed(Feed):
    """Try feeds in order per asset class; fall through on failure.

    The point is not redundancy for its own sake — it is that a live vendor and
    a deterministic simulator can be composed, so the platform still functions
    (visibly degraded, never silently wrong) when the vendor is unreachable.
    """

    name = "composite"

    def __init__(self, *feeds: Feed, mark_degraded: bool = True):
        if not feeds:
            raise ValueError("CompositeFeed needs at least one feed")
        self.feeds = list(feeds)
        self.mark_degraded = mark_degraded
        self.last_used: str = ""
        self.degraded: bool = False
        self.last_error: str | None = None

    def _candidates(self, symbol: str) -> list[Feed]:
        from ..instruments import resolve
        ac = resolve(symbol).asset_class
        return [f for f in self.feeds if f.supports(ac)] or self.feeds

    def get_quote(self, symbol: str) -> Quote:
        errors = []
        for i, feed in enumerate(self._candidates(symbol)):
            try:
                q = feed.get_quote(symbol)
                self.last_used = feed.name
                self.degraded = i > 0
                return q
            except SymbolNotFound:
                raise
            except FeedError as e:
                errors.append(f"{feed.name}: {e}")
        self.last_error = " | ".join(errors)
        raise FeedUnavailable(f"all feeds failed for {symbol} -> {self.last_error}")

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        remaining = [s.upper() for s in symbols]
        for i, feed in enumerate(self.feeds):
            if not remaining:
                break
            batch = [s for s in remaining if feed.supports(_ac(s))]
            if not batch:
                continue
            try:
                got = feed.get_quotes(batch)
            except FeedError as e:
                self.last_error = f"{feed.name}: {e}"
                continue
            if got:
                self.last_used = feed.name
                self.degraded = self.degraded or i > 0
            out.update(got)
            remaining = [s for s in remaining if s not in out]
        return out

    def get_bars(self, symbol: str, interval: str = "1d", limit: int = 200) -> list[Bar]:
        errors = []
        for feed in self._candidates(symbol):
            try:
                bars = feed.get_bars(symbol, interval, limit)
                if bars:
                    return bars
            except FeedError as e:
                errors.append(f"{feed.name}: {e}")
        raise FeedUnavailable(f"no bars for {symbol}: {' | '.join(errors)}")

    def health(self) -> FeedHealth:
        healths = [f.health() for f in self.feeds]
        primary = healths[0]
        return FeedHealth(
            name="composite",
            ok=any(h.ok for h in healths),
            breaker=primary.breaker,
            last_success=primary.last_success,
            last_error=self.last_error or primary.last_error,
            requests=sum(h.requests for h in healths),
            errors=sum(h.errors for h in healths),
        )

    def feed_healths(self) -> list[FeedHealth]:
        return [f.health() for f in self.feeds]

    def close(self) -> None:
        for f in self.feeds:
            f.close()


def _ac(symbol: str) -> AssetClass:
    from ..instruments import resolve
    return resolve(symbol).asset_class


# ------------------------------------------------------------------- helpers


def parse_number(text: object, default: float = 0.0) -> float:
    """Parse the many ways a vendor writes a number.

    Handles '1,234.56', '$1,234.56', '-2.31%', '12.4M', '1.2B', '3.5K', '(4.2)'
    for negatives, and '-' for missing. Returns `default` rather than raising:
    one unparseable cell in a fundamentals table must not kill the whole quote.
    """
    if text is None:
        return default
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if not s or s in {"-", "--", "N/A", "n/a", "NaN", ""}:
        return default
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("$", "").replace("%", "").replace("+", "")
    mult = 1.0
    if s and s[-1] in "KMBT":
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1]]
        s = s[:-1]
    try:
        val = float(s) * mult
    except ValueError:
        return default
    return -val if negative else val


def is_stale(q: Quote, max_age_s: float = DEFAULT_STALE_AFTER_S,
             now: datetime | None = None) -> bool:
    return q.age_s(now) > max_age_s


def bars_to_quote(symbol: str, bars: list[Bar], source: str) -> Quote:
    """Synthesize a quote from the most recent bar, for bar-only vendors."""
    if not bars:
        raise SymbolNotFound(f"no bars for {symbol}")
    last, prev = bars[-1], (bars[-2] if len(bars) > 1 else bars[-1])
    return Quote(
        symbol=symbol.upper(), ts=last.ts, last=last.close, open=last.open,
        high=last.high, low=last.low, volume=last.volume,
        prev_close=prev.close, source=source,
    )
