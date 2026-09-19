"""One-shot server-side messages.

The obvious way to show "here is your new password" after a redirect is to put
it in the query string. That is also how it ends up in the HTTP access log, in
nginx's log, in the browser's history, and — because `Referrer-Policy` is
`same-origin` — in the Referer of every subsequent request from that page.

So secrets travel here instead: held in memory, keyed to the session that
created them, and readable exactly once. Nothing sensitive touches a URL.

In-memory is the right store for this. The messages are worthless a second
after they are read, the platform is a single process by design, and writing
them to SQLite would put the very credential we are trying to keep out of the
logs into a file on disk.
"""

from __future__ import annotations

import hashlib
import threading
import time

# A message nobody collects (the user closed the tab) is dropped after this.
TTL_SECONDS = 300
MAX_PENDING = 2_000

_messages: dict[str, tuple[float, str, str]] = {}
_lock = threading.Lock()


def _key(session_token: str) -> str:
    """Key on a hash, so the store never holds a live session token."""
    return hashlib.sha256((session_token or "anon").encode()).hexdigest()


def put(session_token: str, message: str, kind: str = "ok") -> None:
    """Stash a message for the next page this session loads."""
    now = time.monotonic()
    with _lock:
        if len(_messages) >= MAX_PENDING:
            for k, (created, _, _) in list(_messages.items()):
                if now - created > TTL_SECONDS:
                    _messages.pop(k, None)
        _messages[_key(session_token)] = (now, kind, message)


def take(session_token: str) -> tuple[str, str] | None:
    """Read and remove this session's pending message, if any."""
    with _lock:
        entry = _messages.pop(_key(session_token), None)
    if entry is None:
        return None
    created, kind, message = entry
    if time.monotonic() - created > TTL_SECONDS:
        return None
    return kind, message


def clear() -> None:
    with _lock:
        _messages.clear()
