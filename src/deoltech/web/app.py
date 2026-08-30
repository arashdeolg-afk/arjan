"""Application assembly: routes, authentication middleware, and startup.

The middleware chain is short and its order matters. Every request resolves an
identity first (session cookie, then bearer token), then the route runs. Public
paths are an explicit allowlist rather than a pattern — a typo in a regex that
accidentally exposes `/admin` is exactly the failure mode worth designing out.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

from ..accounts import (
    AccountError, AccountService, default_account, list_accounts,
)
from ..auth import (
    AuthError, PermissionDenied, Role, admin_count, bootstrap_admin,
    change_own_password, create_api_token, create_user, find_user, login,
    logout, password_problems, revoke_api_token, session_user, token_user,
)
from ..db import audit, connect, get_setting, set_setting
from . import admin as admin_views
from . import flash
from . import api as api_views
from . import views
from .assets import CSS, JS
from .server import (
    SESSION_COOKIE, HttpError, Request, Response, WebApp,
    safe_redirect_target, serve,
)
from .templates import FAVICON, alert, esc, layout, login_page

log = logging.getLogger("deoltech.web")

# Paths reachable without a session. An explicit list, not a prefix rule.
PUBLIC_PATHS = frozenset({
    "/login", "/setup", "/api/health", "/static/app.css", "/static/app.js",
    "/static/favicon.svg", "/favicon.ico",
})


class Platform:
    """Process-wide state: database, service layer, and configuration."""

    def __init__(self, *, db_path: str | None = None, feed_mode: str = "",
                 finviz_token: str = ""):
        if db_path:
            os.environ["DEOLTECH_DB"] = str(db_path)
        self.conn_factory = connect
        conn = self.conn()
        self.feed_mode = (feed_mode or get_setting(conn, "feed_mode")
                          or os.environ.get("DEOLTECH_FEED", "auto"))
        self.finviz_token = (finviz_token or get_setting(conn, "finviz_token")
                             or os.environ.get("FINVIZ_AUTH_TOKEN", ""))
        self.service = AccountService(self.conn_factory,
                                      feed_mode=self.feed_mode,
                                      finviz_token=self.finviz_token)

    def conn(self):
        return self.conn_factory()

    def rebuild_feed(self) -> None:
        """Re-create the feed stack after an admin changes its settings."""
        conn = self.conn()
        self.feed_mode = get_setting(conn, "feed_mode") or "auto"
        self.finviz_token = get_setting(conn, "finviz_token") or ""
        service = AccountService(self.conn_factory, feed_mode=self.feed_mode,
                                 finviz_token=self.finviz_token)
        # Preserve loaded brokers so a settings change does not drop live state.
        service._brokers = self.service._brokers
        service._ledger_marks = self.service._ledger_marks
        for broker in service._brokers.values():
            broker.feed = service.feed
        self.service = service

    def needs_setup(self) -> bool:
        return admin_count(self.conn()) == 0

    def username(self, user_id: int) -> str:
        row = self.conn().execute("SELECT username FROM users WHERE id = ?",
                                  (user_id,)).fetchone()
        return row["username"] if row else f"user:{user_id}"


def build_app(platform: Platform, *, secret: str = "",
              secure_cookies: bool = False, debug: bool = False) -> WebApp:
    app = WebApp(secret=secret, secure_cookies=secure_cookies, debug=debug)
    app.platform = platform
    app.exception_status = {
        PermissionDenied: 403,      # authorization refusal
        AuthError: 400,             # a user-correctable input problem
        AccountError: 400,
    }

    app.add_static("/static/app.css", CSS, "text/css")
    app.add_static("/static/app.js", JS, "application/javascript")
    app.add_static("/static/favicon.svg", FAVICON, "image/svg+xml")
    app.add_static("/favicon.ico", FAVICON, "image/svg+xml")

    # ----------------------------------------------------------- middleware

    def authenticate(request: Request) -> Response | None:
        conn = platform.conn()

        # First run: force the setup flow rather than showing a login form no
        # one can pass. API callers get JSON — an HTML redirect to a browser
        # form is a useless answer to a programmatic request.
        if platform.needs_setup() and request.path not in (
                "/setup", "/static/app.css", "/static/app.js",
                "/static/favicon.svg", "/api/health"):
            if request.wants_json:
                return Response.json(
                    {"error": "This Deol Tech instance has not been set up yet. "
                              "Open /setup in a browser to create the first "
                              "administrator.", "status": 503}, 503)
            return Response.redirect("/setup")

        user = session_user(conn, request.session_token)
        if user is None:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                user = token_user(conn, auth_header[7:].strip())
        request.user = user

        if user is not None:
            request.account_id = default_account(conn, user.id, user.username)
            if request.path in ("/login", "/setup"):
                return Response.redirect("/")
            return None

        if request.path in PUBLIC_PATHS:
            return None
        if request.wants_json:
            return Response.json({"error": "Authentication required."}, 401)
        target = quote(request.path)
        return Response.redirect(f"/login?next={target}")

    app.before_request.append(authenticate)

    def render_error(request: Request, error: Exception) -> Response:
        status = getattr(error, "status", 500)
        message = getattr(error, "message", None) or (
            "The server hit an unexpected error. It has been logged.")
        if isinstance(error, PermissionDenied):
            status, message = 403, str(error)
        if request.wants_json:
            return Response.json({"error": message, "status": status}, status)
        body = (alert(message, "error")
                + '<p><a class="btn" href="/">Back to the dashboard</a></p>')
        try:
            return Response.html(layout(
                title=f"Error {status}", body=f"<h1>{status}</h1>{body}",
                user=request.user, active="",
                csrf=app.csrf_token(request.session_token),
                feed={}), status)
        except Exception:                                  # noqa: BLE001
            return Response.text(message, status)

    app.error_handler = render_error

    # --------------------------------------------------------------- routes

    @app.get("/")
    def _dashboard(request):
        return views.dashboard(request)

    @app.get("/terminal")
    def _terminal(request):
        return views.terminal(request)

    @app.get("/positions")
    def _positions(request):
        return views.positions_page(request)

    @app.get("/orders")
    def _orders(request):
        return views.orders_page(request)

    @app.get("/blotter")
    def _blotter(request):
        return views.blotter_page(request)

    @app.get("/analytics")
    def _analytics(request):
        return views.analytics_page(request)

    @app.route("/backtest", ("GET", "POST"))
    def _backtest(request):
        return views.backtest_page(request)

    @app.get("/markets")
    def _markets(request):
        return views.markets_page(request)

    @app.get("/profile")
    def _profile(request):
        return views.profile_page(request)

    # ------------------------------------------------------------- auth

    @app.get("/login")
    def _login_form(request):
        return Response.html(login_page(
            error=request.query.get("error", "")[:300],
            notice=request.query.get("ok", "")[:300]))

    @app.post("/login")
    def _login(request):
        conn = platform.conn()
        ip = request.remote_addr
        # Per-IP throttle on top of the per-account lockout, so spraying one
        # password across many usernames is limited too.
        if not app.limiter.allow(f"login:{ip}", limit=12, window_s=300):
            return Response.html(login_page(
                error="Too many sign-in attempts from this address. "
                      "Wait a few minutes and try again."), 429)
        username = request.get("username", "").strip()[:64]
        password = request.get("password", "")
        try:
            user, token = login(conn, username, password, ip=ip,
                                user_agent=request.headers.get("user-agent", ""))
        except AuthError as e:
            return Response.html(login_page(error=str(e), username=username), 401)

        # Never redirect off-site from a login, and never let a decoded CRLF
        # reach the Location header.
        target = safe_redirect_target(request.get("next", "/"))
        if user.must_change_password:
            target = "/profile?warn=" + quote(
                "Your password was set by an administrator. Change it now.")
        return Response.redirect(target).set_cookie(
            SESSION_COOKIE, token, max_age=12 * 3600,
            secure=app.secure_cookies or request.is_secure)

    @app.post("/logout")
    def _logout(request):
        if request.session_token:
            logout(platform.conn(), request.session_token, request.user)
        return Response.redirect("/login?ok=" + quote("Signed out.")).set_cookie(
            SESSION_COOKIE, "", max_age=0, secure=app.secure_cookies)

    @app.get("/setup")
    def _setup_form(request):
        if not platform.needs_setup():
            return Response.redirect("/login")
        return Response.html(login_page(setup=True,
                                        error=request.query.get("error", "")[:300]))

    @app.post("/setup")
    def _setup(request):
        if not platform.needs_setup():
            raise HttpError(403, "An administrator already exists.")
        conn = platform.conn()
        username = request.get("username", "admin").strip()
        password = request.get("password", "")
        if password != request.get("confirm", ""):
            return Response.html(login_page(
                setup=True, error="The two passwords do not match.",
                username=username), 400)
        problems = password_problems(password, username)
        if problems:
            return Response.html(login_page(
                setup=True, error="Password " + "; ".join(problems) + ".",
                username=username), 400)
        try:
            user, _ = bootstrap_admin(conn, username, password,
                                      request.get("email", "").strip())
        except AuthError as e:
            return Response.html(login_page(setup=True, error=str(e),
                                            username=username), 400)
        default_account(conn, user.id, user.username)
        _, token = login(conn, username, password, ip=request.remote_addr,
                         user_agent=request.headers.get("user-agent", ""))
        return Response.redirect("/?ok=" + quote(
            f"Welcome to Deol Tech, {user.display_name}. Your paper account is "
            f"ready.")).set_cookie(
            SESSION_COOKIE, token, max_age=12 * 3600,
            secure=app.secure_cookies or request.is_secure)

    # ---------------------------------------------------------- profile ops

    @app.post("/profile/password")
    def _change_password(request):
        try:
            change_own_password(platform.conn(), request.user,
                                request.get("current", ""),
                                request.get("new_password", ""))
        except AuthError as e:
            return Response.redirect("/profile?error=" + quote(str(e)))
        return Response.redirect("/login?ok=" + quote(
            "Password changed. Sign in again.")).set_cookie(
            SESSION_COOKIE, "", max_age=0, secure=app.secure_cookies)

    @app.post("/profile/watchlist")
    def _save_watchlist(request):
        request.user.require("watchlist.edit")
        raw = request.get("symbols", "").replace("\n", ",")
        symbols = [s for s in raw.split(",") if s.strip()]
        platform.service.set_watchlist(request.user.id, symbols)
        return Response.redirect("/profile?ok=" + quote("Watchlist saved."))

    @app.post("/profile/risk")
    def _save_risk(request):
        # Its sibling _save_watchlist checks; this one did not. A viewer could
        # rewrite their own risk limits — harmless today because trade.submit
        # still gates order entry, but the check belongs here.
        request.user.require("account.manage")
        changes = {
            "max_order_notional": request.get_float("max_order_notional", 0) or None,
            "max_position_notional": request.get_float("max_position_notional", 0) or None,
            "daily_loss_limit": request.get_float("daily_loss_limit", 0),
            "fat_finger_pct": request.get_float("fat_finger_pct", 25),
            "allow_shorting": request.get_bool("allow_shorting"),
            "allow_margin": request.get_bool("allow_margin"),
            "enforce_pdt": request.get_bool("enforce_pdt"),
        }
        platform.service.update_risk(
            request.account_id, {k: v for k, v in changes.items() if v is not None},
            request.user.username)
        return Response.redirect("/profile?ok=" + quote("Risk limits updated."))

    @app.post("/profile/tokens")
    def _create_token(request):
        try:
            token = create_api_token(platform.conn(), request.user,
                                     request.get("name", "token"),
                                     request.get("scopes", "read"))
        except (AuthError, PermissionDenied) as e:
            return Response.redirect("/profile?error=" + quote(str(e)))
        # Same reasoning as the password paths: a bearer token in a URL is a
        # bearer token in the access log and the browser's history.
        flash.put(request.session_token,
                  f"Token created: {token} — copy it now, it is never shown "
                  f"again.")
        return Response.redirect("/profile")

    @app.post("/profile/tokens/<int:token_id>/revoke")
    def _revoke_token(request):
        try:
            revoke_api_token(platform.conn(), request.user,
                             int(request.params["token_id"]))
        except (AuthError, PermissionDenied) as e:
            return Response.redirect("/profile?error=" + quote(str(e)))
        return Response.redirect("/profile?ok=" + quote("Token revoked."))

    @app.post("/profile/reset")
    def _reset_own_account(request):
        from ..accounts import reset_account
        request.user.require("account.manage")
        reset_account(platform.conn(), request.account_id, request.user.username)
        platform.service.evict(request.account_id)
        return Response.redirect("/?ok=" + quote(
            "Paper account reset to its opening balance."))

    @app.post("/actions/flatten")
    def _flatten(request):
        request.user.require("trade.submit")
        orders = platform.service.flatten_all(request.account_id)
        return Response.redirect("/?ok=" + quote(
            f"Sent {len(orders)} closing order(s)."))

    # ------------------------------------------------------------- admin

    @app.get("/admin")
    def _admin(request):
        return admin_views.console(request)

    @app.get("/admin/users")
    def _admin_users(request):
        return admin_views.users_page(request)

    @app.post("/admin/users")
    def _admin_create_user(request):
        return admin_views.create_user_action(request)

    @app.post("/admin/users/<int:user_id>/role")
    def _admin_role(request):
        return admin_views.set_role_action(request)

    @app.post("/admin/users/<int:user_id>/status")
    def _admin_status(request):
        return admin_views.set_status_action(request)

    @app.post("/admin/users/<int:user_id>/reset")
    def _admin_reset(request):
        return admin_views.reset_password_action(request)

    @app.post("/admin/users/<int:user_id>/delete")
    def _admin_delete(request):
        return admin_views.delete_user_action(request)

    @app.get("/admin/accounts")
    def _admin_accounts(request):
        return admin_views.accounts_page(request)

    @app.post("/admin/accounts/<int:account_id>/halt")
    def _admin_halt(request):
        return admin_views.halt_account_action(request)

    @app.post("/admin/accounts/<int:account_id>/resume")
    def _admin_resume(request):
        return admin_views.resume_account_action(request)

    @app.post("/admin/accounts/<int:account_id>/reset")
    def _admin_reset_account(request):
        return admin_views.reset_account_action(request)

    @app.get("/admin/audit")
    def _admin_audit(request):
        return admin_views.audit_page(request)

    @app.get("/admin/system")
    def _admin_system(request):
        return admin_views.system_page(request)

    @app.post("/admin/system/feed")
    def _admin_feed(request):
        return admin_views.save_feed_action(request)

    @app.post("/admin/system/purge-sessions")
    def _admin_purge(request):
        return admin_views.purge_sessions_action(request)

    # --------------------------------------------------------------- api

    app.get("/api/health")(api_views.health)
    app.get("/api/quotes")(api_views.quotes)
    app.get("/api/quotes/<symbol>")(api_views.quote_one)
    app.get("/api/bars")(api_views.bars)
    app.get("/api/account")(api_views.account)
    app.get("/api/equity-curve")(api_views.equity_curve)
    app.get("/api/blotter")(api_views.blotter)
    app.get("/api/performance")(api_views.performance)
    app.get("/api/instruments")(api_views.instruments)
    app.get("/api/strategies")(api_views.strategies)
    app.get("/api/max-qty")(api_views.max_qty)
    app.post("/api/orders")(api_views.submit_order)
    app.post("/api/orders/<order_id>/cancel")(api_views.cancel_order)
    app.post("/api/positions/<symbol>/close")(api_views.close_position)
    app.post("/api/preview")(api_views.preview)
    app.route("/api/watchlist", ("GET", "POST"))(api_views.watchlist)

    return app


def run(host: str = "127.0.0.1", port: int = 8000, *, db_path: str | None = None,
        feed_mode: str = "", secret: str = "", secure_cookies: bool = False,
        trust_proxy: bool = False, debug: bool = False):
    """Start the server. Blocks until interrupted."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s")

    platform = Platform(db_path=db_path, feed_mode=feed_mode)
    conn = platform.conn()

    # A stable secret across restarts, so sessions and CSRF tokens survive one.
    secret = secret or os.environ.get("DEOLTECH_SECRET", "")
    if not secret:
        secret = get_setting(conn, "server_secret", "")
        if not secret:
            import secrets as _s
            secret = _s.token_urlsafe(48)
            set_setting(conn, "server_secret", secret)
            log.info("generated a new server secret and stored it in the database")

    app = build_app(platform, secret=secret, secure_cookies=secure_cookies,
                    debug=debug)
    httpd = serve(app, host, port, trust_proxy=trust_proxy)

    log.info("Deol Tech listening on http://%s:%d", host, port)
    log.info("market data: %s", platform.feed_mode)
    if platform.needs_setup():
        log.warning("no administrator yet — open http://%s:%d/setup to create one",
                    host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        httpd.server_close()
    return httpd
