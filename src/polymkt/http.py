"""HTTP plumbing. Stdlib urllib only — no requests, no install step.

Two things here are not optional in practice:

1. **Throttling.** Polymarket publishes per-endpoint rate limits. Rather
   than encode numbers that drift, this keeps a conservative floor on the
   gap between requests and backs off hard when the server says 429.
2. **An injectable transport.** Every test in this repo runs offline. The
   client takes a callable, so tests hand it recorded payloads instead of
   reaching the network.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

USER_AGENT = "polymkt/0.1 (+stdlib urllib)"

# Floor on the gap between two requests to the same host, in seconds.
# Deliberately conservative: being slow is cheaper than being blocked.
MIN_INTERVAL = float(os.environ.get("POLYMKT_MIN_INTERVAL", "0.12"))
TIMEOUT = float(os.environ.get("POLYMKT_TIMEOUT", "20"))
RETRIES = int(os.environ.get("POLYMKT_RETRIES", "3"))

# (status, headers, body) — the whole surface a transport must implement.
Response = tuple[int, dict[str, str], bytes]
Transport = Callable[[str, str, dict[str, str], bytes | None], Response]


class PolymarketError(RuntimeError):
    """Base for anything this package raises deliberately."""


class HTTPError(PolymarketError):
    def __init__(self, status: int, url: str, body: str) -> None:
        self.status = status
        self.url = url
        self.body = body[:500]
        super().__init__(f"HTTP {status} for {url}: {self.body}")


class TransportError(PolymarketError):
    """The request never got an HTTP answer — DNS, TLS, proxy, timeout."""


def urllib_transport(method: str, url: str, headers: dict[str, str],
                     body: bytes | None) -> Response:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:            # 4xx/5xx still carry a body
        return exc.code, dict(exc.headers or {}), exc.read()
    except urllib.error.URLError as exc:
        raise TransportError(f"{url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise TransportError(f"{url}: timed out after {TIMEOUT}s") from exc


def _encode(params: dict[str, Any] | None) -> str:
    """Query string, dropping Nones and expanding lists into repeated keys.

    Gamma takes repeated keys for multi-value filters (`?tag_id=1&tag_id=2`),
    so a naive urlencode of a list would silently send `['1', '2']`.
    """
    if not params:
        return ""
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            pairs.extend((key, str(v)) for v in value if v is not None)
        else:
            pairs.append((key, str(value)))
    return urllib.parse.urlencode(pairs)


@dataclass
class Client:
    """A JSON client for one Polymarket service."""

    base_url: str
    transport: Transport = urllib_transport
    min_interval: float = MIN_INTERVAL
    retries: int = RETRIES
    calls: int = field(default=0, init=False)
    _last_call: float = field(default=0.0, init=False)

    def url_for(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        query = _encode(params)
        return f"{url}?{query}" if query else url

    def _wait(self) -> None:
        gap = time.monotonic() - self._last_call
        if self._last_call and gap < self.min_interval:
            time.sleep(self.min_interval - gap)

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                json_body: Any = None) -> Any:
        url = self.url_for(path, params)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait()
            self.calls += 1
            try:
                status, resp_headers, raw = self.transport(method, url, headers, body)
            except TransportError as exc:
                last_error = exc
                if attempt == self.retries:
                    raise
                time.sleep(_backoff(attempt))
                continue
            finally:
                self._last_call = time.monotonic()

            if status == 429 or status >= 500:
                last_error = HTTPError(status, url, _text(raw))
                if attempt == self.retries:
                    raise last_error
                time.sleep(_retry_after(resp_headers) or _backoff(attempt))
                continue
            if status >= 400:
                raise HTTPError(status, url, _text(raw))
            return _parse(raw, url)

        raise last_error or PolymarketError(f"{url}: exhausted retries")

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: Any) -> Any:
        return self.request("POST", path, json_body=json_body)


def _backoff(attempt: int) -> float:
    return min(8.0, 0.5 * (2 ** attempt))


def _retry_after(headers: dict[str, str]) -> float | None:
    raw = {k.lower(): v for k, v in headers.items()}.get("retry-after")
    try:
        return min(30.0, float(raw)) if raw else None
    except ValueError:
        return None


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").strip()


def _parse(raw: bytes, url: str) -> Any:
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolymarketError(f"{url}: response was not JSON ({exc})") from exc
