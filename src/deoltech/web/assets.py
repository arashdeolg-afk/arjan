"""Static assets: stylesheet and client script.

Served as real files rather than inlined into the HTML, because the
Content-Security-Policy forbids `unsafe-inline`. That is the point — a strict
CSP is the difference between an XSS bug being a nuisance and being a breach,
and paying for it with two extra requests is a good trade.

The design targets the job: a trading screen is read at a glance under time
pressure, so numbers are tabular-figure monospace and right-aligned (digits
line up, magnitude is legible without reading), direction is carried by both
colour and sign (colour alone fails for the ~8% of men with red-green colour
blindness), and density is high because scrolling to find a position is a
worse failure than a busy screen.
"""

from __future__ import annotations

CSS = """
/* ============================================================ Deol Tech ==
   Colour is defined once as tokens on :root, then re-pointed for dark mode.
   Semantic names (--up, --down, --accent) rather than literal ones, so a
   rebrand touches this block and nothing else.
   ======================================================================== */
:root {
  --bg:          #0b0e14;
  --bg-raised:   #11151f;
  --bg-inset:    #080a10;
  --bg-hover:    #1a2030;
  --border:      #1e2536;
  --border-soft: #171d2b;
  --text:        #e4e8f1;
  --text-dim:    #8b95a9;
  --text-faint:  #5a6478;
  --accent:      #00c2a8;
  --accent-dim:  #00806f;
  --accent-glow: rgba(0,194,168,.14);
  --up:          #26c281;
  --down:        #f0616d;
  --warn:        #f5a623;
  --info:        #4a9eff;
  --radius:      6px;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Inter, Roboto, sans-serif;
  color-scheme: dark;
}
:root[data-theme="light"] {
  --bg: #f6f7fa; --bg-raised: #ffffff; --bg-inset: #eef0f5; --bg-hover: #e8ecf4;
  --border: #d6dbe6; --border-soft: #e4e8f0;
  --text: #10131a; --text-dim: #5c6577; --text-faint: #8d95a6;
  --accent: #00806f; --accent-dim: #00c2a8; --accent-glow: rgba(0,128,111,.10);
  --up: #0f9d58; --down: #d93438;
  color-scheme: light;
}

* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 var(--sans);
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1,h2,h3,h4 { margin: 0 0 .6rem; font-weight: 600; letter-spacing: -.01em; }
h1 { font-size: 1.35rem; } h2 { font-size: 1.1rem; } h3 { font-size: .95rem; }
p { margin: 0 0 .75rem; }
code, .mono, .num { font-family: var(--mono); font-variant-numeric: tabular-nums; }

/* ------------------------------------------------------------- structure */
.shell { display: grid; grid-template-columns: 210px 1fr; min-height: 100vh; }
.sidebar {
  background: var(--bg-raised); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; position: sticky; top: 0;
  height: 100vh; overflow-y: auto;
}
.brand {
  display: flex; align-items: center; gap: .6rem; padding: 1rem 1.1rem;
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.brand-mark {
  width: 30px; height: 30px; border-radius: 7px; flex-shrink: 0;
  background: linear-gradient(135deg, var(--accent), var(--accent-dim));
  display: grid; place-items: center; color: #04120f;
  font: 700 13px/1 var(--mono); letter-spacing: -.5px;
}
.brand-name { font-weight: 650; letter-spacing: -.02em; font-size: .95rem; }
.brand-sub { color: var(--text-faint); font-size: .65rem; letter-spacing: .1em;
  text-transform: uppercase; }
nav.main { padding: .6rem 0; flex: 1; }
nav.main a {
  display: flex; align-items: center; gap: .6rem; padding: .5rem 1.1rem;
  color: var(--text-dim); font-size: .85rem; border-left: 2px solid transparent;
}
nav.main a:hover { background: var(--bg-hover); color: var(--text);
  text-decoration: none; }
nav.main a.active {
  color: var(--accent); border-left-color: var(--accent);
  background: var(--accent-glow); font-weight: 550;
}
nav.main .nav-group {
  padding: .9rem 1.1rem .3rem; font-size: .62rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--text-faint); font-weight: 600;
}
.sidebar-foot { padding: .8rem 1.1rem; border-top: 1px solid var(--border);
  font-size: .75rem; color: var(--text-faint); }

.main-col { display: flex; flex-direction: column; min-width: 0; }
.topbar {
  display: flex; align-items: center; gap: 1.25rem; padding: .6rem 1.25rem;
  background: var(--bg-raised); border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 20; flex-wrap: wrap;
}
.topbar .spacer { flex: 1; }
.content { padding: 1.25rem; max-width: 1600px; width: 100%; }

/* ------------------------------------------------------------ components */
.card {
  background: var(--bg-raised); border: 1px solid var(--border);
  border-radius: var(--radius); margin-bottom: 1rem; overflow: hidden;
}
.card-head {
  display: flex; align-items: center; gap: .75rem; padding: .65rem .9rem;
  border-bottom: 1px solid var(--border-soft); background: var(--bg-inset);
}
.card-head h2, .card-head h3 { margin: 0; font-size: .85rem; letter-spacing: .01em; }
.card-head .spacer { flex: 1; }
.card-body { padding: .9rem; }
.card-body.flush { padding: 0; }
.grid { display: grid; gap: 1rem; }
.grid.cols-2 { grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.grid.cols-3 { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.grid.cols-4 { grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); }
.split { display: grid; grid-template-columns: minmax(0,1fr) 320px; gap: 1rem; }
@media (max-width: 1100px) { .split { grid-template-columns: 1fr; } }

/* --------------------------------------------------------------- metrics */
.stat { padding: .8rem .9rem; }
.stat-label {
  font-size: .65rem; letter-spacing: .09em; text-transform: uppercase;
  color: var(--text-faint); font-weight: 600; margin-bottom: .25rem;
}
.stat-value { font-family: var(--mono); font-variant-numeric: tabular-nums;
  font-size: 1.4rem; font-weight: 600; letter-spacing: -.02em; }
.stat-sub { font-size: .72rem; color: var(--text-dim); margin-top: .15rem;
  font-family: var(--mono); }

.up { color: var(--up); } .down { color: var(--down); }
.dim { color: var(--text-dim); } .faint { color: var(--text-faint); }
.warn { color: var(--warn); } .info { color: var(--info); }
.right { text-align: right; } .center { text-align: center; }
.nowrap { white-space: nowrap; }

/* --------------------------------------------------------------- tables */
table { width: 100%; border-collapse: collapse; font-size: .82rem; }
thead th {
  text-align: left; padding: .5rem .75rem; font-size: .64rem; font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase; color: var(--text-faint);
  border-bottom: 1px solid var(--border); background: var(--bg-inset);
  position: sticky; top: 0; white-space: nowrap;
}
tbody td { padding: .5rem .75rem; border-bottom: 1px solid var(--border-soft);
  vertical-align: middle; }
tbody tr:hover { background: var(--bg-hover); }
tbody tr:last-child td { border-bottom: none; }
td.num, th.num { font-family: var(--mono); font-variant-numeric: tabular-nums;
  text-align: right; white-space: nowrap; }
.table-wrap { overflow-x: auto; max-width: 100%; }
.empty { padding: 2rem 1rem; text-align: center; color: var(--text-faint);
  font-size: .85rem; }

/* --------------------------------------------------------------- badges */
.badge {
  display: inline-block; padding: .12rem .45rem; border-radius: 4px;
  font-size: .66rem; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; border: 1px solid transparent; white-space: nowrap;
}
.badge-up { background: rgba(38,194,129,.13); color: var(--up);
  border-color: rgba(38,194,129,.3); }
.badge-down { background: rgba(240,97,109,.13); color: var(--down);
  border-color: rgba(240,97,109,.3); }
.badge-neutral { background: var(--bg-inset); color: var(--text-dim);
  border-color: var(--border); }
.badge-accent { background: var(--accent-glow); color: var(--accent);
  border-color: var(--accent-dim); }
.badge-warn { background: rgba(245,166,35,.13); color: var(--warn);
  border-color: rgba(245,166,35,.35); }

/* ---------------------------------------------------------------- forms */
label { display: block; font-size: .7rem; font-weight: 600; letter-spacing: .05em;
  text-transform: uppercase; color: var(--text-dim); margin-bottom: .3rem; }
input, select, textarea, button { font: inherit; }
input[type=text], input[type=password], input[type=number], input[type=email],
select, textarea {
  width: 100%; padding: .45rem .6rem; background: var(--bg-inset);
  border: 1px solid var(--border); border-radius: var(--radius);
  color: var(--text); font-family: var(--mono); font-size: .85rem;
}
input:focus, select:focus, textarea:focus {
  outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow);
}
.field { margin-bottom: .7rem; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: .6rem; }
.hint { font-size: .7rem; color: var(--text-faint); margin-top: .25rem;
  text-transform: none; letter-spacing: 0; font-weight: 400; }
.check { display: flex; align-items: center; gap: .45rem; margin-bottom: .5rem; }
.check input { width: auto; }
.check label { margin: 0; text-transform: none; letter-spacing: 0;
  font-size: .8rem; font-weight: 400; color: var(--text); }

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: .4rem;
  padding: .45rem .85rem; border-radius: var(--radius); cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-inset);
  color: var(--text); font-size: .82rem; font-weight: 550;
  transition: background .12s, border-color .12s;
}
.btn:hover { background: var(--bg-hover); border-color: var(--text-faint);
  text-decoration: none; }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn-primary { background: var(--accent); border-color: var(--accent);
  color: #04120f; }
.btn-primary:hover { background: var(--accent-dim); border-color: var(--accent-dim);
  color: #fff; }
.btn-buy { background: var(--up); border-color: var(--up); color: #04120a; }
.btn-buy:hover { filter: brightness(1.1); color: #04120a; }
.btn-sell { background: var(--down); border-color: var(--down); color: #fff; }
.btn-sell:hover { filter: brightness(1.1); color: #fff; }
.btn-danger { color: var(--down); border-color: rgba(240,97,109,.4); }
.btn-danger:hover { background: rgba(240,97,109,.12); }
.btn-sm { padding: .25rem .5rem; font-size: .72rem; }
.btn-block { width: 100%; }
.btn-row { display: flex; gap: .5rem; flex-wrap: wrap; }

.seg { display: flex; border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; }
.seg button {
  flex: 1; padding: .4rem .5rem; background: var(--bg-inset); border: none;
  color: var(--text-dim); cursor: pointer; font-size: .78rem; font-weight: 600;
}
.seg button.active { background: var(--accent); color: #04120f; }
.seg button.active.sell-active { background: var(--down); color: #fff; }
.seg button.active.buy-active { background: var(--up); color: #04120a; }

/* --------------------------------------------------------------- alerts */
.alert { padding: .65rem .85rem; border-radius: var(--radius); margin-bottom: 1rem;
  font-size: .85rem; border: 1px solid; display: flex; gap: .6rem; }
.alert-error { background: rgba(240,97,109,.1); border-color: rgba(240,97,109,.35);
  color: var(--down); }
.alert-ok { background: rgba(38,194,129,.1); border-color: rgba(38,194,129,.35);
  color: var(--up); }
.alert-warn { background: rgba(245,166,35,.1); border-color: rgba(245,166,35,.35);
  color: var(--warn); }
.alert-info { background: rgba(74,158,255,.1); border-color: rgba(74,158,255,.3);
  color: var(--info); }

/* ---------------------------------------------------------------- ticker */
.ticker { display: flex; gap: 1.1rem; overflow-x: auto; font-family: var(--mono);
  font-size: .78rem; scrollbar-width: none; }
.ticker::-webkit-scrollbar { display: none; }
.ticker-item { display: flex; gap: .4rem; white-space: nowrap; cursor: pointer;
  padding: .1rem 0; }
.ticker-item:hover .tsym { color: var(--accent); }
.tsym { font-weight: 650; }

.feed-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block;
  background: var(--up); flex-shrink: 0; }
.feed-dot.degraded { background: var(--warn); }
.feed-dot.down { background: var(--down); }

/* ----------------------------------------------------------- price flash */
@keyframes flash-up { from { background: rgba(38,194,129,.28); } to { background: transparent; } }
@keyframes flash-down { from { background: rgba(240,97,109,.28); } to { background: transparent; } }
.flash-up { animation: flash-up .55s ease-out; }
.flash-down { animation: flash-down .55s ease-out; }
@media (prefers-reduced-motion: reduce) {
  .flash-up, .flash-down { animation: none; }
}

/* ----------------------------------------------------------------- chart */
.chart { width: 100%; display: block; }
.chart-controls { display: flex; gap: .3rem; }
.chart-controls button {
  padding: .2rem .5rem; font-size: .7rem; background: transparent;
  border: 1px solid var(--border); border-radius: 4px; color: var(--text-dim);
  cursor: pointer;
}
.chart-controls button.active { color: var(--accent); border-color: var(--accent); }

/* ----------------------------------------------------------- login page */
.auth-page { display: grid; place-items: center; min-height: 100vh; padding: 1.5rem; }
.auth-card { width: 100%; max-width: 380px; background: var(--bg-raised);
  border: 1px solid var(--border); border-radius: 10px; padding: 1.75rem; }
.auth-brand { display: flex; align-items: center; gap: .7rem; margin-bottom: 1.4rem; }
.auth-brand .brand-mark { width: 38px; height: 38px; font-size: 15px; }

/* ------------------------------------------------------------- utilities */
.row { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.muted-box { background: var(--bg-inset); border: 1px solid var(--border-soft);
  border-radius: var(--radius); padding: .7rem .85rem; font-size: .8rem; }
.kv { display: flex; justify-content: space-between; gap: 1rem; padding: .25rem 0;
  font-size: .8rem; }
.kv .k { color: var(--text-dim); } .kv .v { font-family: var(--mono); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0,0,0,0); white-space: nowrap; }
hr { border: none; border-top: 1px solid var(--border-soft); margin: 1rem 0; }
.scroll-y { max-height: 420px; overflow-y: auto; }

/* ---------------------------------------------------------- utilities --
   These exist because the Content-Security-Policy forbids inline styles.
   `style="..."` attributes are exactly what `style-src` is meant to stop —
   they are an injection vector — so every one of them is a class instead.
   ---------------------------------------------------------------------- */
.m-0        { margin: 0; }
.mb-1       { margin-bottom: 1rem; }
.mb-sm      { margin-bottom: .7rem; }
.mt-sm      { margin-top: .5rem; }
.mt-md      { margin-top: .6rem; }
.mt-lg      { margin-top: .7rem; }
.mt-xl      { margin-top: .8rem; }
.mt-1       { margin-top: 1rem; }
.mt-2       { margin-top: 1.2rem; }
.my-md      { margin: .6rem 0; }
.mt-only-md { margin: .6rem 0 0; }
.mt-only-lg { margin: .8rem 0 0; }
.mb-head    { margin: 0 0 .6rem; }
.mt-note    { margin: .2rem 0 .7rem; }

.fs-xs      { font-size: .7rem; }
.fs-sm      { font-size: .72rem; }
.fs-md      { font-size: .75rem; }
.fs-base    { font-size: .78rem; }
.fs-lg      { font-size: .82rem; }
.fs-note    { font-size: .85rem; }
.fs-xl      { font-size: .95rem; }
.fs-2xl     { font-size: 1rem; }
.fs-3xl     { font-size: 1.05rem; }

.gap-xs     { gap: .4rem; }
.gap-sm     { gap: .6rem; }
.gap-lg     { gap: 1.5rem; }
.baseline   { align-items: baseline; }
.no-wrap    { flex-wrap: nowrap; }
.flex-1     { flex: 1; }

.w-sm       { max-width: 140px; }
.w-md       { max-width: 160px; }
.w-lg       { max-width: 180px; }
.w-xl       { max-width: 220px; }

.h-chart    { height: 340px; }
.h-equity   { height: 260px; }
.h-spark    { height: 220px; }

.topstat    { font-size: 1rem; font-weight: 600; }
.username   { font-size: .82rem; font-weight: 600; }
.user-block { text-align: right; line-height: 1.25; }
.center     { text-align: center; }
.center-note{ text-align: center; margin-top: .5rem; }
.center-foot{ margin-top: 1.2rem; text-align: center; }
.price-hero { font-size: 2rem; font-weight: 600; letter-spacing: -.02em; }
.select-inline { width: auto; padding: .15rem .35rem; font-size: .75rem; }
.log-pre    { font-size: .72rem; margin: 0; white-space: pre-wrap; }
.note-flat  { font-size: .85rem; margin: 0; }
.role-tag   { font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; }
.toast-host { position: fixed; bottom: 1rem; right: 1rem; z-index: 100;
              display: flex; flex-direction: column; gap: .5rem; max-width: 340px; }

@media (max-width: 820px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; flex-direction: row;
    align-items: center; overflow-x: auto; }
  .sidebar .brand { border-bottom: none; border-right: 1px solid var(--border); }
  nav.main { display: flex; padding: 0; }
  nav.main .nav-group, .sidebar-foot { display: none; }
  nav.main a { border-left: none; border-bottom: 2px solid transparent;
    white-space: nowrap; }
  nav.main a.active { border-left: none; border-bottom-color: var(--accent); }
  .content { padding: .85rem; }
}
"""

JS = r"""
/* Deol Tech client. Vanilla, no build step, no external dependencies —
   the Content-Security-Policy forbids external origins, and a trading screen
   that breaks when a CDN is slow is worse than one with fewer features. */
(function () {
  "use strict";

  const $  = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  /* --------------------------------------------------- number formatting */
  function money(v, dp) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    dp = dp === undefined ? 2 : dp;
    return Number(v).toLocaleString("en-US",
      { minimumFractionDigits: dp, maximumFractionDigits: dp });
  }
  function signed(v, dp) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return (v > 0 ? "+" : "") + money(v, dp);
  }
  function cls(v) { return v > 0 ? "up" : (v < 0 ? "down" : "dim"); }

  /* ------------------------------------------------------------- fetch */
  function csrf() {
    const el = $('meta[name="csrf-token"]');
    return el ? el.content : "";
  }
  async function api(path, options) {
    options = options || {};
    const headers = Object.assign(
      { "Accept": "application/json" }, options.headers || {});
    if (options.body && typeof options.body !== "string") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    if ((options.method || "GET") !== "GET") headers["X-CSRF-Token"] = csrf();
    const res = await fetch(path, Object.assign({}, options, { headers }));
    let data = null;
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok) {
      if (res.status === 401) { location.href = "/login"; return null; }
      throw new Error((data && data.error) || ("Request failed: " + res.status));
    }
    return data;
  }
  window.dtApi = api;

  /* ------------------------------------------------------- price flashing */
  const lastValues = new Map();
  function setPrice(el, value, dp) {
    if (!el) return;
    const key = el.dataset.flashKey || el.id || el.dataset.symbol;
    const prev = lastValues.get(key);
    el.textContent = money(value, dp);
    if (prev !== undefined && value !== prev) {
      el.classList.remove("flash-up", "flash-down");
      void el.offsetWidth;                       /* restart the animation */
      el.classList.add(value > prev ? "flash-up" : "flash-down");
    }
    lastValues.set(key, value);
  }

  /* ------------------------------------------------------------ ticker */
  async function refreshTicker() {
    const bar = $("#ticker");
    if (!bar) return;
    const symbols = (bar.dataset.symbols || "").split(",").filter(Boolean);
    if (!symbols.length) return;
    try {
      const data = await api("/api/quotes?symbols=" + encodeURIComponent(symbols.join(",")));
      if (!data) return;
      bar.innerHTML = "";
      symbols.forEach(function (sym) {
        const q = data.quotes[sym];
        if (!q) return;
        const item = document.createElement("a");
        item.className = "ticker-item";
        item.href = "/terminal?symbol=" + encodeURIComponent(sym);
        const chg = q.change_pct;
        item.innerHTML =
          '<span class="tsym">' + sym + '</span>' +
          '<span>' + money(q.last, q.price_precision) + '</span>' +
          '<span class="' + cls(chg) + '">' + signed(chg, 2) + '%</span>';
        bar.appendChild(item);
      });
      updateFeedStatus(data.feed);
    } catch (e) { /* a failed poll must never break the page */ }
  }

  function updateFeedStatus(feed) {
    const dot = $("#feed-dot"), label = $("#feed-label");
    if (!dot || !feed) return;
    dot.className = "feed-dot" + (!feed.ok ? " down" : (feed.degraded ? " degraded" : ""));
    if (label) {
      label.textContent = feed.degraded
        ? "SIMULATED — live feed unreachable"
        : (feed.ok ? (feed.source || feed.name) : "feed down");
      label.title = feed.last_error || "";
    }
  }

  /* --------------------------------------------------------- live panels */
  async function refreshAccount() {
    const host = $("#account-summary");
    if (!host) return;
    try {
      const data = await api("/api/account");
      if (!data) return;
      const s = data.summary;
      setPrice($("#stat-equity"), s.equity);
      const dayEl = $("#stat-day-pnl");
      if (dayEl) {
        dayEl.textContent = signed(s.day_pnl);
        dayEl.className = "stat-value " + cls(s.day_pnl);
      }
      const upl = $("#stat-unrealized");
      if (upl) {
        upl.textContent = signed(s.unrealized_pnl);
        upl.className = "stat-value " + cls(s.unrealized_pnl);
      }
      const bp = $("#stat-bp");
      if (bp) bp.textContent = money(s.buying_power);
      const call = $("#margin-call");
      if (call) call.hidden = !s.margin_call;
      if (data.positions) renderPositions(data.positions);
      if (data.orders) renderOrders(data.orders);
    } catch (e) { /* keep the last good render */ }
  }

  function renderPositions(rows) {
    const body = $("#positions-body");
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="8" class="empty">' +
        'No open positions. Use the order ticket to place your first trade.</td></tr>';
      return;
    }
    body.innerHTML = rows.map(function (p) {
      return '<tr>' +
        '<td><a href="/terminal?symbol=' + p.symbol + '"><strong>' + p.symbol + '</strong></a>' +
        ' <span class="badge badge-' + (p.side === "long" ? "up" : "down") + '">' + p.side + '</span></td>' +
        '<td class="num">' + p.qty_fmt + '</td>' +
        '<td class="num">' + money(p.avg_price, 4) + '</td>' +
        '<td class="num">' + money(p.last, 4) + '</td>' +
        '<td class="num">' + money(p.market_value) + '</td>' +
        '<td class="num ' + cls(p.unrealized_pnl) + '">' + signed(p.unrealized_pnl) + '</td>' +
        '<td class="num ' + cls(p.unrealized_pct) + '">' + signed(p.unrealized_pct, 2) + '%</td>' +
        '<td class="right"><button class="btn btn-sm btn-danger" data-close="' +
        p.symbol + '">Close</button></td>' +
        '</tr>';
    }).join("");
  }

  function renderOrders(rows) {
    const body = $("#orders-body");
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="7" class="empty">No working orders.</td></tr>';
      return;
    }
    body.innerHTML = rows.map(function (o) {
      const price = o.limit_price || o.stop_price;
      return '<tr>' +
        '<td><strong>' + o.symbol + '</strong></td>' +
        '<td><span class="badge badge-' + (o.side === "buy" ? "up" : "down") + '">' +
          o.side + '</span></td>' +
        '<td>' + o.order_type + '</td>' +
        '<td class="num">' + o.qty_fmt + (o.filled_qty > 0 ? ' <span class="faint">(' +
          o.filled_qty + ' done)</span>' : '') + '</td>' +
        '<td class="num">' + (price ? money(price, 4) : "mkt") + '</td>' +
        '<td><span class="badge badge-neutral">' + o.status + '</span></td>' +
        '<td class="right"><button class="btn btn-sm btn-danger" data-cancel="' +
          o.id + '">Cancel</button></td>' +
        '</tr>';
    }).join("");
  }

  /* ------------------------------------------------------- order actions */
  document.addEventListener("click", async function (ev) {
    const closeBtn = ev.target.closest("[data-close]");
    if (closeBtn) {
      const sym = closeBtn.dataset.close;
      if (!confirm("Close the entire " + sym + " position at the market?")) return;
      closeBtn.disabled = true;
      try {
        await api("/api/positions/" + encodeURIComponent(sym) + "/close",
                  { method: "POST", body: {} });
        toast("Closing order sent for " + sym, "ok");
        refreshAccount();
      } catch (e) { toast(e.message, "error"); closeBtn.disabled = false; }
      return;
    }
    const cancelBtn = ev.target.closest("[data-cancel]");
    if (cancelBtn) {
      cancelBtn.disabled = true;
      try {
        await api("/api/orders/" + encodeURIComponent(cancelBtn.dataset.cancel) +
                  "/cancel", { method: "POST", body: {} });
        toast("Order cancelled", "ok");
        refreshAccount();
      } catch (e) { toast(e.message, "error"); cancelBtn.disabled = false; }
      return;
    }
  });

  /* -------------------------------------------------------------- toasts */
  function toast(message, kind) {
    let host = $("#toasts");
    if (!host) {
      host = document.createElement("div");
      host.id = "toasts";
      host.className = "toast-host";
      document.body.appendChild(host);
    }
    const el = document.createElement("div");
    el.className = "alert alert-" + (kind || "info") + " m-0";
    el.textContent = message;
    host.appendChild(el);
    setTimeout(function () { el.remove(); }, 5000);
  }
  window.dtToast = toast;

  /* --------------------------------------------------------- order ticket */
  function initTicket() {
    const form = $("#order-ticket");
    if (!form) return;
    const sideInput = $("#ticket-side", form);

    $$(".seg button", form).forEach(function (btn) {
      btn.addEventListener("click", function () {
        $$(".seg button", form).forEach(function (b) {
          b.classList.remove("active", "buy-active", "sell-active");
        });
        btn.classList.add("active", btn.dataset.side === "buy" ? "buy-active" : "sell-active");
        sideInput.value = btn.dataset.side;
        updateEstimate();
      });
    });

    const typeSelect = $("#ticket-type", form);
    function syncFields() {
      const t = typeSelect.value;
      const limitRow = $("#row-limit", form), stopRow = $("#row-stop", form);
      if (limitRow) limitRow.hidden = !(t === "limit" || t === "stop_limit");
      if (stopRow) stopRow.hidden = !(t === "stop" || t === "stop_limit");
    }
    typeSelect.addEventListener("change", function () { syncFields(); updateEstimate(); });
    syncFields();

    ["ticket-qty", "ticket-limit", "ticket-stop"].forEach(function (id) {
      const el = $("#" + id, form);
      if (el) el.addEventListener("input", updateEstimate);
    });

    async function updateEstimate() {
      const out = $("#ticket-estimate");
      if (!out) return;
      const qty = parseFloat($("#ticket-qty", form).value || "0");
      if (!qty || qty <= 0) { out.innerHTML = ""; return; }
      try {
        const data = await api("/api/preview", { method: "POST", body: {
          symbol: form.dataset.symbol, side: sideInput.value, qty: qty,
          order_type: typeSelect.value,
          limit_price: ($("#ticket-limit", form) || {}).value || "",
          stop_price: ($("#ticket-stop", form) || {}).value || ""
        }});
        if (!data) return;
        out.innerHTML =
          '<div class="kv"><span class="k">Estimated fill</span><span class="v">' +
            money(data.estimated_price, data.price_precision) + '</span></div>' +
          '<div class="kv"><span class="k">Notional</span><span class="v">' +
            money(data.notional) + '</span></div>' +
          '<div class="kv"><span class="k">Est. fees</span><span class="v">' +
            money(data.fees, 2) + '</span></div>' +
          '<div class="kv"><span class="k">Margin required</span><span class="v">' +
            money(data.margin_required) + '</span></div>' +
          '<div class="kv"><span class="k">Buying power after</span><span class="v">' +
            money(data.buying_power_after) + '</span></div>' +
          (data.allowed
            ? '<div class="alert alert-ok mt-only-md">Passes pre-trade risk checks.</div>'
            : '<div class="alert alert-error mt-only-md">' + data.reason + '</div>');
      } catch (e) { out.innerHTML = '<div class="hint">' + e.message + '</div>'; }
    }

    const maxBtn = $("#ticket-max", form);
    if (maxBtn) maxBtn.addEventListener("click", async function () {
      try {
        const data = await api("/api/max-qty?symbol=" +
          encodeURIComponent(form.dataset.symbol) + "&side=" + sideInput.value);
        if (data) { $("#ticket-qty", form).value = data.max_qty; updateEstimate(); }
      } catch (e) { toast(e.message, "error"); }
    });

    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const btn = $("#ticket-submit", form);
      btn.disabled = true;
      const payload = {};
      new FormData(form).forEach(function (v, k) { payload[k] = v; });
      try {
        const data = await api("/api/orders", { method: "POST", body: payload });
        if (data) {
          if (data.status === "rejected") toast("Rejected: " + data.reject_reason, "error");
          else if (data.status === "filled")
            toast("Filled " + data.filled_qty + " " + data.symbol + " at " +
                  money(data.avg_fill_price, 4), "ok");
          else toast("Order " + data.status + " — " + data.id, "ok");
          /* A rejected stop-loss leaves a live position unprotected. Say so
             loudly rather than letting the green "filled" toast imply safety. */
          (data.warnings || []).forEach(function (w) { toast(w, "error"); });
          refreshAccount();
        }
      } catch (e) { toast(e.message, "error"); }
      btn.disabled = false;
    });

    updateEstimate();
  }

  /* --------------------------------------------------------------- chart */
  function drawChart(el, bars) {
    if (!el || !bars || bars.length < 2) return;
    const W = el.clientWidth || 800, H = el.clientHeight || 300;
    const padL = 8, padR = 62, padT = 10, padB = 22;
    const iw = W - padL - padR, ih = H - padT - padB;
    const highs = bars.map(b => b.high), lows = bars.map(b => b.low);
    let hi = Math.max.apply(null, highs), lo = Math.min.apply(null, lows);
    const pad = (hi - lo) * 0.06 || hi * 0.01 || 1;
    hi += pad; lo -= pad;
    const x = i => padL + (i / (bars.length - 1)) * iw;
    const y = v => padT + (1 - (v - lo) / (hi - lo)) * ih;

    const cw = Math.max(1.2, Math.min(9, iw / bars.length * 0.66));
    const up = getComputedStyle(document.documentElement)
      .getPropertyValue("--up").trim() || "#26c281";
    const down = getComputedStyle(document.documentElement)
      .getPropertyValue("--down").trim() || "#f0616d";
    const grid = getComputedStyle(document.documentElement)
      .getPropertyValue("--border").trim() || "#1e2536";
    const dim = getComputedStyle(document.documentElement)
      .getPropertyValue("--text-faint").trim() || "#5a6478";

    let svg = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H +
              '" preserveAspectRatio="none" role="img" aria-label="Price chart">';
    for (let g = 0; g <= 4; g++) {
      const gy = padT + (g / 4) * ih, val = hi - (g / 4) * (hi - lo);
      svg += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) +
             '" y2="' + gy + '" stroke="' + grid + '" stroke-width="1"/>';
      svg += '<text x="' + (W - padR + 6) + '" y="' + (gy + 3.5) + '" fill="' + dim +
             '" font-size="10" font-family="ui-monospace,monospace">' +
             money(val, val > 500 ? 0 : (val > 5 ? 2 : 4)) + '</text>';
    }
    bars.forEach(function (b, i) {
      const colour = b.close >= b.open ? up : down;
      const cx = x(i);
      svg += '<line x1="' + cx + '" y1="' + y(b.high) + '" x2="' + cx + '" y2="' +
             y(b.low) + '" stroke="' + colour + '" stroke-width="1"/>';
      const yo = y(b.open), yc = y(b.close);
      svg += '<rect x="' + (cx - cw / 2) + '" y="' + Math.min(yo, yc) +
             '" width="' + cw + '" height="' + Math.max(1, Math.abs(yc - yo)) +
             '" fill="' + colour + '"/>';
    });
    svg += '</svg>';
    el.innerHTML = svg;
  }

  async function loadChart(symbol, interval, host) {
    host = host || $("#chart-host");
    if (!host) return;
    try {
      const data = await api("/api/bars?symbol=" + encodeURIComponent(symbol) +
                             "&interval=" + interval + "&limit=140");
      if (data && data.bars) drawChart(host, data.bars);
      else host.innerHTML = '<div class="empty">No price history available.</div>';
    } catch (e) {
      host.innerHTML = '<div class="empty">Chart unavailable: ' + e.message + '</div>';
    }
  }

  function initChart() {
    const host = $("#chart-host");
    if (!host) return;
    const symbol = host.dataset.symbol;
    let interval = host.dataset.interval || "1d";
    loadChart(symbol, interval, host);
    $$(".chart-controls button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        $$(".chart-controls button").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        interval = btn.dataset.interval;
        loadChart(symbol, interval, host);
      });
    });
    let t;
    window.addEventListener("resize", function () {
      clearTimeout(t);
      t = setTimeout(function () { loadChart(symbol, interval, host); }, 250);
    });
  }

  /* -------------------------------------------------------- equity curve */
  function drawEquity(el, points) {
    if (!el || !points || points.length < 2) {
      if (el) el.innerHTML = '<div class="empty">Not enough history yet — ' +
        'the curve appears once the account has traded.</div>';
      return;
    }
    const W = el.clientWidth || 800, H = el.clientHeight || 220;
    const padL = 8, padR = 62, padT = 10, padB = 18;
    const iw = W - padL - padR, ih = H - padT - padB;
    const vals = points.map(p => p.equity);
    let hi = Math.max.apply(null, vals), lo = Math.min.apply(null, vals);
    const pad = (hi - lo) * 0.08 || hi * 0.01 || 1;
    hi += pad; lo -= pad;
    const x = i => padL + (i / (points.length - 1)) * iw;
    const y = v => padT + (1 - (v - lo) / (hi - lo)) * ih;
    const gained = vals[vals.length - 1] >= vals[0];
    const root = getComputedStyle(document.documentElement);
    const colour = (gained ? root.getPropertyValue("--up")
                           : root.getPropertyValue("--down")).trim();
    const grid = root.getPropertyValue("--border").trim();
    const dim = root.getPropertyValue("--text-faint").trim();

    let path = "", area = "";
    points.forEach(function (p, i) {
      path += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p.equity).toFixed(1) + " ";
    });
    area = path + "L" + x(points.length - 1).toFixed(1) + " " + (padT + ih) +
           " L" + padL + " " + (padT + ih) + " Z";

    let svg = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H +
              '" preserveAspectRatio="none" role="img" aria-label="Equity curve">';
    svg += '<defs><linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">' +
           '<stop offset="0%" stop-color="' + colour + '" stop-opacity=".28"/>' +
           '<stop offset="100%" stop-color="' + colour + '" stop-opacity="0"/>' +
           '</linearGradient></defs>';
    for (let g = 0; g <= 3; g++) {
      const gy = padT + (g / 3) * ih, val = hi - (g / 3) * (hi - lo);
      svg += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy +
             '" stroke="' + grid + '" stroke-width="1"/>';
      svg += '<text x="' + (W - padR + 6) + '" y="' + (gy + 3.5) + '" fill="' + dim +
             '" font-size="10" font-family="ui-monospace,monospace">' +
             money(val, 0) + '</text>';
    }
    svg += '<path d="' + area + '" fill="url(#eqfill)"/>';
    svg += '<path d="' + path + '" fill="none" stroke="' + colour +
           '" stroke-width="1.8" stroke-linejoin="round"/>';
    svg += '</svg>';
    el.innerHTML = svg;
  }

  function initEquity() {
    const el = $("#equity-host");
    if (!el) return;
    api("/api/equity-curve").then(function (data) {
      if (data) drawEquity(el, data.points);
    }).catch(function () {});
  }

  /* ---------------------------------------------------------------- theme */
  function initTheme() {
    const stored = (function () {
      try { return localStorage.getItem("dt-theme"); } catch (e) { return null; }
    })();
    if (stored) document.documentElement.dataset.theme = stored;
    const btn = $("#theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("dt-theme", next); } catch (e) {}
      const host = $("#chart-host");
      if (host) loadChart(host.dataset.symbol, host.dataset.interval || "1d", host);
      initEquity();
    });
  }

  /* ----------------------------------------------------------------- boot */
  function boot() {
    initTheme();
    initTicket();
    initChart();
    initEquity();
    refreshTicker();
    refreshAccount();
    const every = parseInt(document.body.dataset.refresh || "6000", 10);
    if (every > 0) {
      setInterval(function () {
        if (document.hidden) return;       /* do not poll a background tab */
        refreshTicker();
        refreshAccount();
      }, every);
    }
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
"""
