"""HTML rendering.

Plain functions returning strings. No template engine, because the stdlib-only
constraint rules one out and because the alternative — string building with a
mandatory escape helper — is honest about where the danger is: `esc()` is
applied to every interpolated value, and any place it is missing is visible in
review rather than buried in a template file.

The layout is one shell (sidebar, topbar, content) that every page fills in, so
navigation, the live ticker and the feed-status indicator behave identically
everywhere.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone

BRAND = "Deol Tech"
TAGLINE = "Paper Trading Terminal"


def esc(value) -> str:
    """Escape for HTML text and attribute contexts. Applied to every value."""
    return html.escape("" if value is None else str(value), quote=True)


def attr_json(data) -> str:
    return esc(json.dumps(data, default=str))


def money(value, dp: int = 2) -> str:
    try:
        return f"{float(value):,.{dp}f}"
    except (TypeError, ValueError):
        return "—"


def signed(value, dp: int = 2, suffix: str = "") -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{'+' if v > 0 else ''}{v:,.{dp}f}{suffix}"


def pnl_class(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "dim"
    return "up" if v > 0 else ("down" if v < 0 else "dim")


NAV = [
    ("Trading", [
        ("/", "Dashboard", "view.account"),
        ("/terminal", "Terminal", "view.market"),
        ("/positions", "Positions", "view.account"),
        ("/orders", "Orders", "view.account"),
        ("/blotter", "Blotter", "view.blotter"),
    ]),
    ("Research", [
        ("/analytics", "Performance", "view.analytics"),
        ("/backtest", "Backtest", "run.backtest"),
        ("/markets", "Markets", "view.market"),
    ]),
    ("Administration", [
        ("/admin", "Console", "admin.users"),
        ("/admin/users", "Users", "admin.users"),
        ("/admin/accounts", "Accounts", "admin.accounts"),
        ("/admin/audit", "Audit log", "admin.audit"),
        ("/admin/system", "System", "admin.settings"),
    ]),
    ("Account", [
        ("/profile", "Profile", "view.account"),
    ]),
]


def layout(*, title: str, body: str, user=None, active: str = "/",
           csrf: str = "", ticker_symbols: list[str] | None = None,
           summary: dict | None = None, refresh_ms: int = 6000,
           feed: dict | None = None) -> str:
    """The application shell."""
    nav_html = []
    for group, items in NAV:
        visible = [(href, label) for href, label, perm in items
                   if user is None or user.can(perm)]
        if not visible:
            continue
        nav_html.append(f'<div class="nav-group">{esc(group)}</div>')
        for href, label in visible:
            is_active = (href == active or
                         (href != "/" and active.startswith(href)))
            nav_html.append(
                f'<a href="{esc(href)}" class="{"active" if is_active else ""}">'
                f'{esc(label)}</a>')

    ticker = ",".join(ticker_symbols or [])
    feed = feed or {}
    dot_class = "feed-dot"
    if not feed.get("ok", True):
        dot_class += " down"
    elif feed.get("degraded"):
        dot_class += " degraded"
    feed_label = ("SIMULATED — live feed unreachable" if feed.get("degraded")
                  else (feed.get("source") or feed.get("name") or "feed"))

    summary_html = ""
    if summary:
        summary_html = f"""
        <div class="row gap-lg">
          <div>
            <div class="stat-label">Equity</div>
            <div class="mono topstat"
                 id="stat-equity-top">{money(summary.get('equity'))}</div>
          </div>
          <div>
            <div class="stat-label">Day P&amp;L</div>
            <div class="mono {pnl_class(summary.get('day_pnl'))} topstat">
              {signed(summary.get('day_pnl'))}</div>
          </div>
          <div>
            <div class="stat-label">Buying power</div>
            <div class="mono topstat">
              {money(summary.get('buying_power'))}</div>
          </div>
        </div>"""

    user_html = ""
    if user:
        user_html = f"""
        <div class="row gap-sm">
          <div class="user-block">
            <div class="username">{esc(user.display_name)}</div>
            <div class="faint role-tag">{esc(user.role.value)}</div>
          </div>
          <form method="post" action="/logout" class="m-0">
            <input type="hidden" name="csrf_token" value="{esc(csrf)}">
            <button class="btn btn-sm" type="submit">Sign out</button>
          </form>
        </div>"""

    return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{esc(csrf)}">
<meta name="color-scheme" content="dark light">
<title>{esc(title)} · {esc(BRAND)}</title>
<link rel="stylesheet" href="/static/app.css">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
</head>
<body data-refresh="{refresh_ms}">
<div class="shell">
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">DT</div>
      <div>
        <div class="brand-name">{esc(BRAND)}</div>
        <div class="brand-sub">{esc(TAGLINE)}</div>
      </div>
    </div>
    <nav class="main">{''.join(nav_html)}</nav>
    <div class="sidebar-foot">
      <div class="row gap-xs">
        <span class="{dot_class}" id="feed-dot"></span>
        <span id="feed-label" class="fs-xs">{esc(feed_label)}</span>
      </div>
      <div class="mt-sm">
        <button class="btn btn-sm" id="theme-toggle" type="button">Theme</button>
      </div>
    </div>
  </aside>
  <div class="main-col">
    <header class="topbar">
      <div class="ticker" id="ticker" data-symbols="{esc(ticker)}"></div>
      <div class="spacer"></div>
      {summary_html}
      {user_html}
    </header>
    <main class="content">{body}</main>
  </div>
</div>
<script src="/static/app.js"></script>
</body>
</html>"""


def login_page(*, error: str = "", notice: str = "", username: str = "",
               setup: bool = False) -> str:
    """Sign-in, or first-run administrator setup."""
    alert = ""
    if error:
        alert = f'<div class="alert alert-error">{esc(error)}</div>'
    elif notice:
        alert = f'<div class="alert alert-ok">{esc(notice)}</div>'

    if setup:
        form = f"""
        <p class="dim fs-note">
          No administrator exists yet. Create one to finish installing
          {esc(BRAND)}. This form is only available while the platform has no
          administrator.</p>
        <form method="post" action="/setup">
          <div class="field">
            <label for="username">Administrator username</label>
            <input id="username" name="username" type="text" required
                   autocomplete="username" value="{esc(username or 'admin')}"
                   minlength="3" maxlength="32">
          </div>
          <div class="field">
            <label for="email">Email <span class="faint">(optional)</span></label>
            <input id="email" name="email" type="email" autocomplete="email">
          </div>
          <div class="field">
            <label for="password">Password</label>
            <input id="password" name="password" type="password" required
                   autocomplete="new-password" minlength="12">
            <div class="hint">At least 12 characters, mixing three of:
              lowercase, uppercase, digits, symbols.</div>
          </div>
          <div class="field">
            <label for="confirm">Confirm password</label>
            <input id="confirm" name="confirm" type="password" required
                   autocomplete="new-password">
          </div>
          <button class="btn btn-primary btn-block" type="submit">
            Create administrator</button>
        </form>"""
    else:
        form = f"""
        <form method="post" action="/login">
          <div class="field">
            <label for="username">Username</label>
            <input id="username" name="username" type="text" required autofocus
                   autocomplete="username" value="{esc(username)}">
          </div>
          <div class="field">
            <label for="password">Password</label>
            <input id="password" name="password" type="password" required
                   autocomplete="current-password">
          </div>
          <button class="btn btn-primary btn-block" type="submit">Sign in</button>
        </form>"""

    return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{'Set up' if setup else 'Sign in'} · {esc(BRAND)}</title>
<link rel="stylesheet" href="/static/app.css">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
</head>
<body>
<div class="auth-page">
  <div class="auth-card">
    <div class="auth-brand">
      <div class="brand-mark">DT</div>
      <div>
        <div class="brand-name fs-3xl">{esc(BRAND)}</div>
        <div class="brand-sub">{esc(TAGLINE)}</div>
      </div>
    </div>
    {alert}
    {form}
    <p class="hint center-foot">
      Simulated trading only. No real orders are ever placed and no real funds
      are at risk.</p>
  </div>
</div>
</body>
</html>"""


# --------------------------------------------------------------- components


def stat(label: str, value: str, *, sub: str = "", value_class: str = "",
         value_id: str = "") -> str:
    id_attr = f' id="{esc(value_id)}"' if value_id else ""
    sub_html = f'<div class="stat-sub">{esc(sub)}</div>' if sub else ""
    return f"""<div class="card m-0"><div class="stat">
      <div class="stat-label">{esc(label)}</div>
      <div class="stat-value {esc(value_class)}"{id_attr}>{value}</div>
      {sub_html}</div></div>"""


def card(title: str, body: str, *, actions: str = "", flush: bool = False,
         subtitle: str = "") -> str:
    head = ""
    if title or actions:
        sub = (f'<span class="faint fs-sm">{esc(subtitle)}</span>'
               if subtitle else "")
        head = (f'<div class="card-head"><h2>{esc(title)}</h2>{sub}'
                f'<div class="spacer"></div>{actions}</div>')
    return (f'<div class="card">{head}'
            f'<div class="card-body{" flush" if flush else ""}">{body}</div></div>')


def table(headers: list[str], rows: list[list[str]], *, empty: str = "Nothing here yet.",
          body_id: str = "", numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    head = "".join(
        f'<th class="{"num" if i in numeric else ""}">{esc(h)}</th>'
        for i, h in enumerate(headers))
    if rows:
        body = "".join(
            "<tr>" + "".join(
                f'<td class="{"num" if i in numeric else ""}">{cell}</td>'
                for i, cell in enumerate(row)) + "</tr>"
            for row in rows)
    else:
        body = (f'<tr><td colspan="{len(headers)}" class="empty">'
                f'{esc(empty)}</td></tr>')
    bid = f' id="{esc(body_id)}"' if body_id else ""
    return (f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody{bid}>{body}</tbody></table></div>')


def badge(text: str, kind: str = "neutral") -> str:
    return f'<span class="badge badge-{esc(kind)}">{esc(text)}</span>'


def alert(message: str, kind: str = "info") -> str:
    return f'<div class="alert alert-{esc(kind)}">{esc(message)}</div>'


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="7" fill="#00c2a8"/>
<text x="16" y="22" font-family="ui-monospace,monospace" font-size="15"
 font-weight="700" fill="#04120f" text-anchor="middle">DT</text></svg>"""
