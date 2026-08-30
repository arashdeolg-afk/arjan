"""Administrator console.

Every handler here calls `user.require(...)` before doing anything, and every
action writes an audit entry. Administrative power without a record of its use
is not accountability — so an admin can reset a password or halt an account,
and the trail shows who did it, to whom, and when.

Two things an administrator deliberately *cannot* do: read another user's
password (there is nothing to read — only a hash), and place a trade on someone
else's account. Admins can halt, inspect and reset, which covers the legitimate
operational needs without creating a way to trade as someone else.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..accounts import (
    AccountError, create_account, get_account, list_accounts, reset_account,
)
from ..auth import (
    AuthError, Role, active_sessions, create_user, delete_user, generate_password,
    list_users, purge_expired_sessions, reset_password, set_role, set_status,
)
from ..db import audit, audit_trail, get_setting, set_setting, stats
from ..instruments import catalog
from . import flash
from .server import HttpError, Request, Response
from .templates import (
    alert, badge, card, esc, money, pnl_class, signed, stat, table,
)
from .views import _flash, shell


def _redirect(path: str, ok: str = "", error: str = "") -> Response:
    from urllib.parse import quote
    if ok:
        return Response.redirect(f"{path}?ok={quote(ok)}")
    if error:
        return Response.redirect(f"{path}?error={quote(error)}")
    return Response.redirect(path)


# ------------------------------------------------------------------ console


def console(request: Request) -> Response:
    request.user.require("admin.users")
    platform = request.app.platform
    conn = platform.conn()
    st = stats(conn)
    feed = platform.service.feed_health()

    accounts = list_accounts(conn)
    total_equity = 0.0
    halted = 0
    for a in accounts:
        try:
            total_equity += platform.service.broker(a["id"]).portfolio.equity()
        except Exception:                                  # noqa: BLE001
            pass
        if a["status"] == "halted":
            halted += 1

    top = f"""
    <div class="grid cols-4 mb-1">
      {stat("Users", f"{st['users']:,}",
            sub=f"{st['active_users']} active · {st['admins']} admin")}
      {stat("Accounts", f"{st['accounts']:,}",
            sub=f"{halted} halted" if halted else "all trading")}
      {stat("Platform equity", money(total_equity),
            sub="sum of all paper accounts")}
      {stat("Executions", f"{st['fills']:,}",
            sub=f"{st['orders']:,} orders placed")}
    </div>"""

    feed_kind = "down" if not feed["ok"] else ("warn" if feed["degraded"] else "up")
    feed_card = card("Market data", f"""
      <div class="kv"><span class="k">Mode</span>
        <span class="v">{badge(feed['mode'], 'accent')}</span></div>
      <div class="kv"><span class="k">Active source</span>
        <span class="v">{badge(feed['source'] or '—', feed_kind)}</span></div>
      <div class="kv"><span class="k">Circuit breaker</span>
        <span class="v">{esc(feed['breaker'])}</span></div>
      <div class="kv"><span class="k">Requests</span>
        <span class="v">{feed['requests']:,}</span></div>
      <div class="kv"><span class="k">Errors</span>
        <span class="v {'down' if feed['errors'] else ''}">{feed['errors']:,}
        ({money(feed['error_rate'] * 100, 1)}%)</span></div>
      <div class="kv"><span class="k">Last success</span>
        <span class="v">{esc((feed['last_success'] or '—')[:19].replace('T', ' '))}</span></div>
      {alert("Live feed unreachable — prices are SIMULATED. Nothing on this "
             "platform is real market data right now.", "warn")
       if feed["degraded"] else ""}
      {alert(feed["last_error"][:300], "error") if feed.get("last_error") else ""}
      <div class="btn-row mt-lg">
        <a class="btn btn-sm" href="/admin/system">Feed settings &amp; probe</a>
      </div>""")

    recent = audit_trail(conn, 15)
    audit_card = card("Recent activity", table(
        ["Time", "Severity", "Action", "Actor", "Target"],
        [[esc(e["ts"][:19].replace("T", " ")),
          badge(e["severity"], {"critical": "down", "warning": "warn"}
                .get(e["severity"], "neutral")),
          esc(e["action"]), esc(e["actor_name"] or "—"), esc(e["target"] or "—")]
         for e in recent], empty="Nothing logged yet."),
        actions='<a class="btn btn-sm" href="/admin/audit">Full audit log</a>',
        flush=True)

    body = (_flash(request) + top
            + f'<div class="grid cols-2">{feed_card}'
            + card("Quick actions", """
              <div class="btn-row">
                <a class="btn" href="/admin/users">Manage users</a>
                <a class="btn" href="/admin/accounts">Manage accounts</a>
                <a class="btn" href="/admin/audit">Audit log</a>
                <a class="btn" href="/admin/system">System</a>
              </div>
              <p class="hint mt-xl">Every administrative
              action is recorded in the audit log with your username attached.
              </p>""") + '</div>'
            + audit_card)
    return shell(request, "Admin console", body, "/admin")


# -------------------------------------------------------------------- users


def users_page(request: Request) -> Response:
    request.user.require("admin.users")
    conn = request.app.platform.conn()
    csrf = request.app.csrf_token(request.session_token)
    users = list_users(conn)

    rows = []
    for u in users:
        is_self = u["id"] == request.user.id
        locked = ""
        if u.get("locked_until"):
            try:
                if datetime.fromisoformat(u["locked_until"]) > datetime.now(timezone.utc):
                    locked = badge("locked", "down")
            except ValueError:
                pass
        role_form = f"""
        <form method="post" action="/admin/users/{u['id']}/role" class="m-0">
          <input type="hidden" name="csrf_token" value="{esc(csrf)}">
          <select name="role" data-autosubmit class="select-inline">
            {''.join(f'<option value="{r}" {"selected" if u["role"] == r else ""}>{r}</option>'
                     for r in ("admin", "trader", "viewer"))}
          </select></form>"""
        actions = f"""
        <div class="btn-row no-wrap">
          <form method="post" action="/admin/users/{u['id']}/status" class="m-0">
            <input type="hidden" name="csrf_token" value="{esc(csrf)}">
            <input type="hidden" name="status"
                   value="{'suspended' if u['status'] == 'active' else 'active'}">
            <button class="btn btn-sm {'btn-danger' if u['status'] == 'active' else ''}"
                    {'disabled' if is_self else ''}>
              {'Suspend' if u['status'] == 'active' else 'Reinstate'}</button>
          </form>
          <form method="post" action="/admin/users/{u['id']}/reset" class="m-0"
                data-confirm="Reset this user&#39;s password? They will be signed out everywhere.">
            <input type="hidden" name="csrf_token" value="{esc(csrf)}">
            <button class="btn btn-sm">Reset password</button>
          </form>
          <form method="post" action="/admin/users/{u['id']}/delete" class="m-0"
                data-confirm="Permanently delete this user and every account, order and fill they own?">
            <input type="hidden" name="csrf_token" value="{esc(csrf)}">
            <button class="btn btn-sm btn-danger" {'disabled' if is_self else ''}>
              Delete</button>
          </form>
        </div>"""
        rows.append([
            f'<strong>{esc(u["username"])}</strong>'
            + (' <span class="badge badge-accent">you</span>' if is_self else ""),
            esc(u["display_name"]), esc(u["email"] or "—"), role_form,
            badge(u["status"], "up" if u["status"] == "active" else "down") + " " + locked,
            str(u["accounts"]), str(u["active_sessions"]),
            esc((u["last_login_at"] or "never")[:16].replace("T", " ")),
            actions,
        ])

    create = card("Create a user", f"""
      <form method="post" action="/admin/users">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <div class="field-row">
          <div class="field"><label for="nu">Username</label>
            <input id="nu" name="username" required minlength="3" maxlength="32"></div>
          <div class="field"><label for="nd">Display name</label>
            <input id="nd" name="display_name"></div>
        </div>
        <div class="field-row">
          <div class="field"><label for="ne">Email</label>
            <input id="ne" name="email" type="email"></div>
          <div class="field"><label for="nr">Role</label>
            <select id="nr" name="role">
              <option value="trader">trader — can trade their own accounts</option>
              <option value="viewer">viewer — read only</option>
              <option value="admin">admin — full platform control</option>
            </select></div>
        </div>
        <div class="field-row">
          <div class="field"><label for="np">Password</label>
            <input id="np" name="password" type="text"
                   placeholder="leave blank to generate one">
            <div class="hint">A generated password is shown once, here.</div></div>
          <div class="field"><label for="nc">Starting cash</label>
            <input id="nc" name="starting_cash" value="100000"></div>
        </div>
        <button class="btn btn-primary" type="submit">Create user</button>
      </form>""")

    body = (_flash(request) + card(
        "Users", table(
            ["Username", "Name", "Email", "Role", "Status", "Accts", "Sessions",
             "Last sign-in", ""], rows, empty="No users."),
        subtitle=f"{len(users)} total", flush=True) + create)
    return shell(request, "Users", body, "/admin/users")


def create_user_action(request: Request) -> Response:
    request.user.require("admin.users")
    conn = request.app.platform.conn()
    username = request.get("username", "").strip()
    password = request.get("password", "").strip()
    generated = not password
    if generated:
        password = generate_password()
    try:
        user = create_user(
            conn, username, password, role=request.get("role", "trader"),
            email=request.get("email", "").strip(),
            display_name=request.get("display_name", "").strip(),
            actor=request.user, must_change_password=generated)
        cash = max(1000.0, request.get_float("starting_cash", 100_000.0))
        create_account(conn, user.id, "Main", starting_cash=cash,
                       actor_name=request.user.username)
    except (AuthError, AccountError) as e:
        return _redirect("/admin/users", error=str(e))
    message = f"Created {user.username} ({user.role.value})."
    if generated:
        # Via the one-shot store, never the URL: a password in a query string
        # is a password in the access log.
        flash.put(request.session_token,
                  f"{message} One-time password: {password} — copy it now, it "
                  f"is not stored and cannot be shown again.")
        return Response.redirect("/admin/users")
    return _redirect("/admin/users", ok=message)


def set_role_action(request: Request) -> Response:
    request.user.require("admin.users")
    conn = request.app.platform.conn()
    try:
        user = set_role(conn, request.user, int(request.params["user_id"]),
                        request.get("role", "trader"))
    except (AuthError, ValueError) as e:
        return _redirect("/admin/users", error=str(e))
    return _redirect("/admin/users",
                     ok=f"{user.username} is now a {user.role.value}. "
                        f"Their sessions were signed out.")


def set_status_action(request: Request) -> Response:
    request.user.require("admin.users")
    conn = request.app.platform.conn()
    try:
        user = set_status(conn, request.user, int(request.params["user_id"]),
                          request.get("status", "active"))
    except (AuthError, ValueError) as e:
        return _redirect("/admin/users", error=str(e))
    return _redirect("/admin/users", ok=f"{user.username} is now {user.status}.")


def reset_password_action(request: Request) -> Response:
    request.user.require("admin.users")
    conn = request.app.platform.conn()
    try:
        uid = int(request.params["user_id"])
        password = reset_password(conn, request.user, uid)
        username = request.app.platform.username(uid)
    except (AuthError, ValueError) as e:
        return _redirect("/admin/users", error=str(e))
    flash.put(request.session_token,
              f"New password for {username}: {password} — shown once. "
              f"They must change it at next sign-in.")
    return Response.redirect("/admin/users")


def delete_user_action(request: Request) -> Response:
    request.user.require("admin.users")
    conn = request.app.platform.conn()
    try:
        uid = int(request.params["user_id"])
        username = request.app.platform.username(uid)
        for acct in list_accounts(conn, uid):
            request.app.platform.service.evict(acct["id"])
        delete_user(conn, request.user, uid)
    except (AuthError, ValueError) as e:
        return _redirect("/admin/users", error=str(e))
    return _redirect("/admin/users",
                     ok=f"Deleted {username} and everything they owned.")


# ----------------------------------------------------------------- accounts


def accounts_page(request: Request) -> Response:
    request.user.require("admin.accounts")
    platform = request.app.platform
    conn = platform.conn()
    csrf = request.app.csrf_token(request.session_token)
    accounts = list_accounts(conn)

    rows = []
    for a in accounts:
        try:
            broker = platform.service.broker(a["id"])
            s = broker.summary()
            equity, day, positions = s["equity"], s["day_pnl"], s["open_positions"]
            call = badge("MARGIN CALL", "down") if s["margin_call"] else ""
        except Exception:                                  # noqa: BLE001
            equity = day = positions = 0
            call = badge("unavailable", "warn")
        halted = a["status"] == "halted"
        toggle = f"""
        <form method="post" action="/admin/accounts/{a['id']}/{'resume' if halted else 'halt'}" class="m-0">
          <input type="hidden" name="csrf_token" value="{esc(csrf)}">
          <input type="hidden" name="reason" value="halted by an administrator">
          <button class="btn btn-sm {'' if halted else 'btn-danger'}">
            {'Resume' if halted else 'Halt'}</button></form>"""
        reset = f"""
        <form method="post" action="/admin/accounts/{a['id']}/reset" class="m-0"
              data-confirm="Delete all trading history on this account?">
          <input type="hidden" name="csrf_token" value="{esc(csrf)}">
          <button class="btn btn-sm btn-danger">Reset</button></form>"""
        rows.append([
            f'<span class="mono">#{a["id"]}</span>', esc(a["username"]),
            esc(a["name"]),
            badge(a["status"], "down" if halted else "up") + " " + call,
            money(a["starting_cash"], 0), money(equity),
            f'<span class="{pnl_class(day)}">{signed(day)}</span>',
            str(positions), f'{a["orders"]:,}', f'{a["fills"]:,}',
            f'<div class="btn-row no-wrap">{toggle}{reset}</div>',
        ])

    body = _flash(request) + card(
        "All paper accounts",
        table(["ID", "Owner", "Name", "Status", "Opening", "Equity", "Day P&L",
               "Positions", "Orders", "Fills", ""], rows,
              empty="No accounts.", numeric={4, 5, 6, 7, 8, 9}),
        subtitle=f"{len(accounts)} accounts", flush=True) + card(
        "About halting", """
        <p class="note-flat">Halting cancels every working order
        on the account and rejects new ones. Open positions are left alone —
        force-closing someone's positions is a different and much more
        consequential action, and it is not something an administrator should be
        able to do with one click.</p>""")
    return shell(request, "Accounts", body, "/admin/accounts")


def halt_account_action(request: Request) -> Response:
    request.user.require("admin.halt")
    account_id = int(request.params["account_id"])
    reason = request.get("reason", "halted by an administrator")[:200]
    request.app.platform.service.halt_account(account_id, reason,
                                              request.user.username)
    return _redirect("/admin/accounts", ok=f"Account #{account_id} halted.")


def resume_account_action(request: Request) -> Response:
    request.user.require("admin.halt")
    account_id = int(request.params["account_id"])
    request.app.platform.service.resume_account(account_id, request.user.username)
    return _redirect("/admin/accounts", ok=f"Account #{account_id} resumed.")


def reset_account_action(request: Request) -> Response:
    request.user.require("admin.accounts")
    conn = request.app.platform.conn()
    account_id = int(request.params["account_id"])
    reset_account(conn, account_id, request.user.username)
    request.app.platform.service.evict(account_id)
    return _redirect("/admin/accounts", ok=f"Account #{account_id} reset.")


# ---------------------------------------------------------------- audit log


def audit_page(request: Request) -> Response:
    request.user.require("admin.audit")
    conn = request.app.platform.conn()
    severity = request.query.get("severity") or None
    if severity not in (None, "info", "warning", "critical"):
        severity = None
    entries = audit_trail(conn, 400, severity=severity)

    tabs = "".join(
        f'<a class="btn btn-sm {"btn-primary" if severity == s else ""}" '
        f'href="/admin/audit{"?severity=" + s if s else ""}">{label}</a>'
        for s, label in [(None, "All"), ("info", "Info"),
                         ("warning", "Warning"), ("critical", "Critical")])

    body = _flash(request) + card(
        "Audit log",
        table(["Time", "Severity", "Action", "Actor", "Target", "Detail", "IP"],
              [[esc(e["ts"][:19].replace("T", " ")),
                badge(e["severity"], {"critical": "down", "warning": "warn"}
                      .get(e["severity"], "neutral")),
                f'<span class="mono">{esc(e["action"])}</span>',
                esc(e["actor_name"] or "—"), esc(e["target"] or "—"),
                f'<span class="faint">{esc((e["detail"] or "")[:120])}</span>',
                f'<span class="mono faint">{esc(e["ip"] or "—")}</span>']
               for e in entries], empty="Nothing logged yet."),
        actions=tabs, subtitle="append-only", flush=True)
    return shell(request, "Audit log", body, "/admin/audit")


# ------------------------------------------------------------------- system


def system_page(request: Request) -> Response:
    request.user.require("admin.settings")
    platform = request.app.platform
    conn = platform.conn()
    csrf = request.app.csrf_token(request.session_token)
    st = stats(conn)
    feed = platform.service.feed_health()
    sessions = active_sessions(conn)

    uptime = datetime.now(timezone.utc) - request.app.started_at
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)

    system = card("System", f"""
      <div class="kv"><span class="k">Uptime</span>
        <span class="v">{hours}h {remainder // 60}m</span></div>
      <div class="kv"><span class="k">Database</span>
        <span class="v mono fs-sm">{esc(st['db_path'])}</span></div>
      <div class="kv"><span class="k">Database size</span>
        <span class="v">{money(st['db_size_bytes'] / 1024 / 1024, 2)} MB</span></div>
      <div class="kv"><span class="k">Active sessions</span>
        <span class="v">{st['sessions']}</span></div>
      <div class="kv"><span class="k">Audit entries</span>
        <span class="v">{st['audit_entries']:,}</span></div>
      <div class="kv"><span class="k">Instruments</span>
        <span class="v">{len(catalog()):,}</span></div>
      <form method="post" action="/admin/system/purge-sessions" class="mt-lg">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <button class="btn btn-sm">Purge expired sessions</button>
      </form>""")

    probe_result = ""
    if request.query.get("probe"):
        try:
            probe_result = _render_probe(platform)
        except Exception as e:                             # noqa: BLE001
            probe_result = alert(f"Probe failed: {e}", "error")

    feed_card = card("Market data feed", f"""
      <div class="kv"><span class="k">Mode</span>
        <span class="v">{badge(feed['mode'], 'accent')}</span></div>
      <div class="kv"><span class="k">Serving</span>
        <span class="v">{esc(feed['source'] or '—')}</span></div>
      <div class="kv"><span class="k">Breaker</span>
        <span class="v">{esc(feed['breaker'])}</span></div>
      <div class="kv"><span class="k">Requests / errors</span>
        <span class="v">{feed['requests']:,} / {feed['errors']:,}</span></div>
      {alert("Serving SIMULATED prices — Finviz is unreachable from this host.",
             "warn") if feed["degraded"] else ""}
      <form method="post" action="/admin/system/feed" class="mt-xl">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <div class="field"><label for="fm">Feed mode</label>
          <select id="fm" name="feed_mode">
            <option value="auto" {"selected" if feed['mode'] == 'auto' else ""}>
              auto — Finviz, simulated fallback</option>
            <option value="live" {"selected" if feed['mode'] == 'live' else ""}>
              live — Finviz only, fail loudly</option>
            <option value="synthetic" {"selected" if feed['mode'] == 'synthetic' else ""}>
              synthetic — simulator only</option>
          </select></div>
        <div class="field"><label for="ft">Finviz Elite token</label>
          <input id="ft" name="finviz_token" type="password"
                 placeholder="{'stored' if get_setting(conn, 'finviz_token') else 'optional'}">
          <div class="hint">With an Elite token the adapter uses the supported
            CSV export instead of scraping the screener.</div></div>
        <button class="btn btn-primary" type="submit">Save feed settings</button>
      </form>
      <div class="btn-row mt-lg">
        <a class="btn btn-sm" href="/admin/system?probe=1">Probe Finviz endpoints</a>
      </div>
      {probe_result}""")

    session_card = card("Active sessions", table(
        ["User", "Role", "Signed in", "Last seen", "IP", "Client"],
        [[esc(s["username"]), badge(s["role"], "accent"),
          esc(s["created_at"][:16].replace("T", " ")),
          esc((s["last_seen_at"] or "—")[:16].replace("T", " ")),
          f'<span class="mono">{esc(s["ip"] or "—")}</span>',
          f'<span class="faint fs-xs">{esc((s["user_agent"] or "")[:60])}</span>']
         for s in sessions], empty="No active sessions."), flush=True)

    body = (_flash(request) + f'<div class="grid cols-2">{system}{feed_card}</div>'
            + session_card)
    return shell(request, "System", body, "/admin/system")


def _render_probe(platform) -> str:
    """Check each Finviz endpoint live and report which parsers matched."""
    from ..feeds.finviz import FinvizFeed
    feed = platform.service.feed
    live = None
    for candidate in (getattr(feed, "inner", None), feed):
        if isinstance(candidate, FinvizFeed):
            live = candidate
        for sub in getattr(candidate, "feeds", []) or []:
            if isinstance(sub, FinvizFeed):
                live = sub
    if live is None:
        live = FinvizFeed()
    results = live.probe()
    ok_count = sum(1 for r in results if r["ok"])
    return card(f"Finviz endpoint probe · {ok_count}/{len(results)} reachable",
                table(["Endpoint", "Status", "Records", "Error"],
                      [[f'<span class="mono">{esc(r["endpoint"])}</span>',
                        badge("ok" if r["ok"] else "failed",
                              "up" if r["ok"] else "down"),
                        str(r["records"]),
                        f'<span class="faint fs-sm">'
                        f'{esc((r["error"] or "")[:160])}</span>']
                       for r in results]),
                flush=True)


def save_feed_action(request: Request) -> Response:
    request.user.require("admin.feeds")
    conn = request.app.platform.conn()
    mode = request.get("feed_mode", "auto")
    if mode not in ("auto", "live", "synthetic"):
        return _redirect("/admin/system", error="Unknown feed mode.")
    token = request.get("finviz_token", "").strip()
    set_setting(conn, "feed_mode", mode, request.user.id)
    if token:
        set_setting(conn, "finviz_token", token, request.user.id)
    request.app.platform.rebuild_feed()
    audit(conn, "system.feed", actor_id=request.user.id,
          actor_name=request.user.username, detail=f"mode={mode}",
          severity="warning")
    return _redirect("/admin/system", ok=f"Feed mode set to {mode}.")


def purge_sessions_action(request: Request) -> Response:
    request.user.require("admin.settings")
    conn = request.app.platform.conn()
    n = purge_expired_sessions(conn)
    audit(conn, "system.purge_sessions", actor_id=request.user.id,
          actor_name=request.user.username, detail=f"{n} rows removed")
    return _redirect("/admin/system", ok=f"Removed {n} expired session rows.")
