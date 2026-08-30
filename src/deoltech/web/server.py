"""HTTP framework for Deol Tech, built on the standard library.

`http.server` is not a production web server on its own, and this module is
what makes it safe to put one in front of a reverse proxy: routing, sessions,
CSRF, rate limiting, security headers, and error handling that never leaks a
traceback to a browser.

Security posture, stated so it can be audited:

* **Session cookies are HttpOnly and SameSite=Lax**, and `Secure` whenever TLS
  is in use, so a cookie cannot be read by script or sent cross-site.
* **CSRF uses a signed double-submit token** derived from the session with
  HMAC-SHA256. Every state-changing request must present it, and it is compared
  in constant time. Stateless, so it survives a restart without invalidating
  everyone's forms.
* **A strict Content-Security-Policy** with no `unsafe-inline` and no external
  origins. All CSS and JS is served from this application, which is why the
  assets are files rather than inline `<script>` blocks.
* **Login is rate limited per IP** on top of the per-account lockout, so
  spraying one password across many usernames is throttled too.
* **Errors are logged with detail and returned without it.** A stack trace in a
  browser is a map of the application.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
import traceback
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn
from typing import Callable

log = logging.getLogger("deoltech.web")

SESSION_COOKIE = "deoltech_session"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"
MAX_BODY_BYTES = 2 * 1024 * 1024      # a trading form is never a megabyte


# ------------------------------------------------------------------ request


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    form: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    remote_addr: str = ""
    user: object = None            # auth.User once authenticated
    account_id: int | None = None
    session_token: str = ""
    app: "WebApp | None" = None

    def get(self, key: str, default: str = "") -> str:
        """Form value first, then query string."""
        return self.form.get(key, self.query.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(float(self.get(key, "")))
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        raw = self.get(key, "").replace(",", "").strip()
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str) -> bool:
        return self.get(key, "").lower() in ("1", "true", "on", "yes")

    def json_body(self) -> dict:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    @property
    def is_json(self) -> bool:
        return "application/json" in self.headers.get("content-type", "")

    @property
    def wants_json(self) -> bool:
        return (self.path.startswith("/api/") or self.is_json
                or "application/json" in self.headers.get("accept", ""))

    @property
    def is_secure(self) -> bool:
        return (self.headers.get("x-forwarded-proto", "").lower() == "https"
                or self.headers.get("x-forwarded-ssl", "").lower() == "on")


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[str] = field(default_factory=list)

    @classmethod
    def html(cls, markup: str, status: int = 200) -> "Response":
        return cls(status=status, body=markup.encode("utf-8"))

    @classmethod
    def json(cls, data, status: int = 200) -> "Response":
        return cls(status=status,
                   body=json.dumps(data, default=_json_default).encode("utf-8"),
                   content_type="application/json; charset=utf-8")

    @classmethod
    def text(cls, message: str, status: int = 200) -> "Response":
        return cls(status=status, body=message.encode("utf-8"),
                   content_type="text/plain; charset=utf-8")

    @classmethod
    def redirect(cls, location: str, status: int = 303) -> "Response":
        return cls(status=status, headers={"Location": location})

    def set_cookie(self, name: str, value: str, *, max_age: int | None = None,
                   http_only: bool = True, secure: bool = False,
                   same_site: str = "Lax", path: str = "/") -> "Response":
        name, value = sanitize_header_value(name), sanitize_header_value(value)
        parts = [f"{name}={value}", f"Path={path}", f"SameSite={same_site}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        self.cookies.append("; ".join(parts))
        return self


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):           # enums
        return obj.value
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


# CR and LF terminate a header. `http.server.send_header` does no sanitising
# whatsoever — it formats "%s: %s\r\n" and encodes latin-1 — so anything
# reaching a header value has to be cleaned here or an attacker who controls
# it can inject headers and forge an entire second response.
_HEADER_UNSAFE = re.compile(r"[\r\n\x00]")


def sanitize_header_value(value: object) -> str:
    """Strip characters that would let a value break out of its header."""
    return _HEADER_UNSAFE.sub("", str(value))


def safe_redirect_target(target: str, fallback: str = "/") -> str:
    """Validate a caller-supplied redirect path.

    Only a site-relative path is allowed, and only from a conservative
    character set. A prefix check alone is not enough: `/\evil.com` and
    `/%09/evil.com` both start with a single slash, and browsers normalise
    them to `//evil.com` — an off-site redirect. Percent-decoding also means
    a CRLF can arrive already decoded.
    """
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return fallback
    if not re.fullmatch(r"/[A-Za-z0-9/_.~\-]*(\?[A-Za-z0-9/_.~\-&=%+]*)?", target):
        return fallback
    return target


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ------------------------------------------------------------------- routing


class Route:
    """One path pattern. `<name>` and `<int:name>` capture path segments."""

    _SEGMENT = re.compile(r"<(?:(int|str):)?([a-zA-Z_][a-zA-Z0-9_]*)>")

    def __init__(self, method: str, pattern: str, handler: Callable, **options):
        self.method = method.upper()
        self.pattern = pattern
        self.handler = handler
        self.options = options
        self.regex = re.compile("^" + self._SEGMENT.sub(self._replace,
                                                        re.escape(pattern)
                                                        .replace(r"\<", "<")
                                                        .replace(r"\>", ">")
                                                        .replace(r"\:", ":")) + "$")

    @staticmethod
    def _replace(m: re.Match) -> str:
        kind, name = m.group(1) or "str", m.group(2)
        return (f"(?P<{name}>\\d+)" if kind == "int" else f"(?P<{name}>[^/]+)")

    def match(self, path: str) -> dict | None:
        m = self.regex.match(path)
        return m.groupdict() if m else None


class RateLimiter:
    """Per-key sliding window. Guards login and other expensive endpoints."""

    def __init__(self):
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < window_s]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            # Opportunistic cleanup so a long-running server does not grow a
            # dictionary entry for every IP that ever connected.
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items()
                              if v and now - v[-1] < window_s}
            return True


# ----------------------------------------------------------------------- app


class WebApp:
    """Routing, middleware and configuration."""

    def __init__(self, *, secret: str = "", secure_cookies: bool = False,
                 debug: bool = False):
        self.routes: list[Route] = []
        self.secret = (secret or os.environ.get("DEOLTECH_SECRET")
                       or secrets.token_urlsafe(48))
        self.secure_cookies = secure_cookies
        self.debug = debug
        self.static: dict[str, tuple[bytes, str]] = {}
        self.limiter = RateLimiter()
        # Domain exceptions that are ANSWERS, not failures. A permission
        # refusal is the system working; logging it as an unhandled error with
        # a stack trace buries real faults in noise.
        self.exception_status: dict[type, int] = {}
        self.before_request: list[Callable[[Request], Response | None]] = []
        self.error_handler: Callable[[Request, Exception], Response] | None = None
        self.started_at = datetime.now(timezone.utc)

    # -------------------------------------------------------- registration

    def route(self, pattern: str, methods: tuple[str, ...] = ("GET",), **options):
        def decorator(fn):
            for method in methods:
                self.routes.append(Route(method, pattern, fn, **options))
            return fn
        return decorator

    def get(self, pattern: str, **options):
        return self.route(pattern, ("GET",), **options)

    def post(self, pattern: str, **options):
        return self.route(pattern, ("POST",), **options)

    def add_static(self, path: str, content: str | bytes,
                   content_type: str = "") -> None:
        data = content.encode("utf-8") if isinstance(content, str) else content
        ctype = content_type or (mimetypes.guess_type(path)[0]
                                 or "application/octet-stream")
        if ctype.startswith(("text/", "application/javascript",
                             "application/json")) and "charset" not in ctype:
            ctype += "; charset=utf-8"
        self.static[path] = (data, ctype)

    # ---------------------------------------------------------------- csrf

    def csrf_token(self, session_token: str) -> str:
        """Deterministic per-session token. Stateless, so restarts are painless."""
        return hmac.new(self.secret.encode(),
                        f"csrf:{session_token}".encode(), sha256).hexdigest()[:40]

    def check_csrf(self, request: Request) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        if not request.session_token:
            # No session means nothing to protect: login itself is guarded by
            # rate limiting rather than CSRF, since there is no session yet.
            return True
        expected = self.csrf_token(request.session_token)
        supplied = (request.headers.get(CSRF_HEADER.lower(), "")
                    or request.form.get(CSRF_FIELD, "")
                    or request.json_body().get(CSRF_FIELD, ""))
        return bool(supplied) and hmac.compare_digest(expected, supplied)

    # -------------------------------------------------------------- dispatch

    def handle(self, request: Request) -> Response:
        request.app = self

        static = self.static.get(request.path)
        if static is not None and request.method in ("GET", "HEAD"):
            data, ctype = static
            etag = f'W/"{sha256(data).hexdigest()[:16]}"'
            if request.headers.get("if-none-match") == etag:
                return Response(status=304, headers={"ETag": etag})
            return Response(body=data, content_type=ctype, headers={
                "ETag": etag, "Cache-Control": "public, max-age=300"})

        for hook in self.before_request:
            early = hook(request)
            if early is not None:
                return early

        allowed_methods = set()
        for route in self.routes:
            params = route.match(request.path)
            if params is None:
                continue
            allowed_methods.add(route.method)
            if route.method != request.method:
                continue
            request.params = params
            if not self.check_csrf(request):
                return self._fail(request, 403,
                                  "Your session expired or the form was stale. "
                                  "Reload the page and try again.")
            try:
                return self._finish(request, route.handler(request))
            except HttpError as e:
                return self._fail(request, e.status, e.message)
            except Exception as e:                     # noqa: BLE001
                for cls, status in self.exception_status.items():
                    if isinstance(e, cls):
                        log.info("%s on %s %s: %s", type(e).__name__,
                                 request.method, request.path, e)
                        return self._fail(request, status, str(e))
                log.error("unhandled error on %s %s: %s\n%s", request.method,
                          request.path, e, traceback.format_exc())
                if self.error_handler:
                    return self.error_handler(request, e)
                detail = (f"{type(e).__name__}: {e}" if self.debug
                          else "The server hit an unexpected error. It has been "
                               "logged.")
                return self._fail(request, 500, detail)

        if allowed_methods:
            return self._fail(request, 405,
                              f"{request.method} is not allowed here.")
        return self._fail(request, 404, "That page does not exist.")

    def _finish(self, request: Request, response) -> Response:
        if isinstance(response, Response):
            return response
        if isinstance(response, str):
            return Response.html(response)
        if isinstance(response, (dict, list)):
            return Response.json(response)
        if response is None:
            return Response(status=204)
        return Response.text(str(response))

    def _fail(self, request: Request, status: int, message: str) -> Response:
        if request.wants_json:
            return Response.json({"error": message, "status": status}, status)
        if self.error_handler:
            try:
                return self.error_handler(request, HttpError(status, message))
            except Exception:                          # noqa: BLE001
                pass
        return Response.html(
            f"<!doctype html><meta charset=utf-8><title>{status}</title>"
            f"<body style='font-family:system-ui;padding:3rem;max-width:40rem;"
            f"margin:auto'><h1>{status}</h1><p>{_escape(message)}</p>"
            f"<p><a href='/'>Back to Deol Tech</a></p></body>", status)


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# -------------------------------------------------------------- HTTP handler


class _Handler(BaseHTTPRequestHandler):
    server_version = "DeolTech"
    sys_version = ""            # do not advertise the Python version
    protocol_version = "HTTP/1.1"

    app: WebApp = None            # type: ignore[assignment]
    trust_proxy: bool = False

    def log_message(self, fmt: str, *args) -> None:
        # Log the path but never the query string. Nothing sensitive should be
        # in a URL, and this makes that a property of the server rather than a
        # promise every future handler has to keep.
        line = fmt % args
        if "?" in line:
            head, _, tail = line.partition("?")
            rest = tail.split(" ", 1)
            line = head + ("?<redacted> " + rest[1] if len(rest) > 1 else "?<redacted>")
        log.info("%s %s", self.address_string(), line)

    def _client_ip(self) -> str:
        if self.trust_proxy:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                # Leftmost entry is the original client; the rest are proxies.
                return forwarded.split(",")[0].strip()[:45]
        return self.client_address[0]

    def _build_request(self) -> Request:
        parsed = urllib.parse.urlparse(self.path)
        query = {k: v[-1] for k, v in
                 urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
        headers = {k.lower(): v for k, v in self.headers.items()}

        body = b""
        length = int(headers.get("content-length") or 0)
        if length > MAX_BODY_BYTES:
            raise HttpError(413, "That request was too large.")
        if length:
            body = self.rfile.read(length)

        form: dict[str, str] = {}
        ctype = headers.get("content-type", "")
        if body and "application/x-www-form-urlencoded" in ctype:
            form = {k: v[-1] for k, v in urllib.parse.parse_qs(
                body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        elif body and "application/json" in ctype:
            try:
                data = json.loads(body.decode("utf-8"))
                if isinstance(data, dict):
                    form = {k: (v if isinstance(v, str) else json.dumps(v))
                            for k, v in data.items()}
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        cookies: dict[str, str] = {}
        if raw := headers.get("cookie"):
            jar = SimpleCookie()
            try:
                jar.load(raw)
                cookies = {k: v.value for k, v in jar.items()}
            except Exception:                          # noqa: BLE001
                cookies = {}

        return Request(
            method=self.command, path=urllib.parse.unquote(parsed.path),
            query=query, form=form, headers=headers, cookies=cookies,
            body=body, remote_addr=self._client_ip(),
            session_token=cookies.get(SESSION_COOKIE, ""),
        )

    def _serve(self) -> None:
        try:
            request = self._build_request()
        except HttpError as e:
            self._send(Response.text(e.message, e.status))
            return
        except Exception as e:                         # noqa: BLE001
            log.error("malformed request: %s", e)
            self._send(Response.text("Bad request.", 400))
            return
        self._send(self.app.handle(request), head_only=(self.command == "HEAD"))

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _serve

    def _send(self, response: Response, head_only: bool = False) -> None:
        body = b"" if head_only else response.body
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            # Defence in depth. The CSP is strict on purpose: no inline script,
            # no external origins, nothing framed.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                "object-src 'none'; base-uri 'none'; form-action 'self'; "
                "frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Permissions-Policy",
                             "geolocation=(), microphone=(), camera=()")
            if self.app.secure_cookies:
                self.send_header("Strict-Transport-Security",
                                 "max-age=31536000; includeSubDomains")
            # Last line of defence: every header leaving this server is
            # stripped of CR/LF here, so a handler that forgets cannot split
            # the response.
            for key, value in response.headers.items():
                self.send_header(sanitize_header_value(key),
                                 sanitize_header_value(value))
            for cookie in response.cookies:
                self.send_header("Set-Cookie", sanitize_header_value(cookie))
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass          # the browser navigated away mid-response; not an error


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # Bound so a burst of connections queues rather than exhausting the socket.
    request_queue_size = 64


def serve(app: WebApp, host: str = "127.0.0.1", port: int = 8000, *,
          trust_proxy: bool = False) -> Server:
    handler = type("BoundHandler", (_Handler,),
                   {"app": app, "trust_proxy": trust_proxy})
    return Server((host, port), handler)
