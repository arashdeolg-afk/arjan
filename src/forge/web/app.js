/* Forge — the app shell: dashboard + workspace.
 * No framework, no build step; talks to the local forge server's JSON API.
 */
"use strict";

/* ================================================================ utils */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

function el(tag, attrs = {}, html = "") {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  if (html) node.innerHTML = html;
  return node;
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const toastWrap = el("div", { class: "toast-wrap" });
document.body.appendChild(toastWrap);
function toast(msg, kind = "info") {
  const t = el("div", { class: `toast ${kind}` }, esc(msg));
  toastWrap.appendChild(t);
  setTimeout(() => t.classList.add("show"), 10);
  setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 300); }, 3600);
}

/* ================================================================ icons */

const svg = (body, vb = "0 0 24 24") =>
  `<svg viewBox="${vb}" fill="none" stroke="currentColor" stroke-width="2" ` +
  `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

const I = {
  logo: `<svg viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffb054"/><stop offset="1" stop-color="#ff5d73"/></linearGradient></defs><rect width="64" height="64" rx="14" fill="#161b24"/><g fill="none" stroke="url(#lg)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"><polyline points="24 22 14 32 24 42"/><polyline points="40 22 50 32 40 42"/><line x1="35" y1="18" x2="29" y2="46"/></g></svg>`,
  plus: svg('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 9 19.36a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.64 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.03a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z"/>'),
  play: svg('<polygon points="6 3 20 12 6 21 6 3" fill="currentColor" stroke="none"/>'),
  stop: svg('<rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" stroke="none"/>'),
  download: svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'),
  upload: svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'),
  trash: svg('<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'),
  pencil: svg('<path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>'),
  copy: svg('<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
  x: svg('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'),
  chevron: svg('<polyline points="9 18 15 12 9 6"/>'),
  back: svg('<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>'),
  file: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'),
  filePlus: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="12" x2="12" y2="18"/><line x1="9" y1="15" x2="15" y2="15"/>'),
  folder: svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>'),
  folderPlus: svg('<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="10" x2="12" y2="16"/><line x1="9" y1="13" x2="15" y2="13"/>'),
  sparkle: svg('<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" fill="currentColor" stroke="none"/><path d="M19 15l.9 2.4L22 18.3l-2.1.9L19 21.5l-.9-2.3-2.1-.9 2.1-.9z" fill="currentColor" stroke="none"/>'),
  refresh: svg('<polyline points="23 4 23 10 17 10"/><path d="M20.5 15a9 9 0 1 1-2-9.4L23 10"/>'),
  external: svg('<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>'),
  send: svg('<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>'),
  terminal: svg('<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>'),
  eye: svg('<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>'),
  dots: svg('<circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none"/>'),
  clock: svg('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
  check: svg('<polyline points="20 6 9 17 4 12"/>'),
  globe: svg('<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>'),
};

const FILE_ICON_COLOR = {
  html: "#ff8a5c", htm: "#ff8a5c", css: "#58a6ff", js: "#ffd166",
  mjs: "#ffd166", json: "#a5b4fc", md: "#9aa7b8", py: "#3ecf8e",
  png: "#c792ea", jpg: "#c792ea", jpeg: "#c792ea", gif: "#c792ea",
  svg: "#c792ea", ico: "#c792ea",
};
const IMG_EXTS = new Set(["png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp"]);
const extOf = (p) => (p.split(".").pop() || "").toLowerCase();

function fileIcon(path) {
  const color = FILE_ICON_COLOR[extOf(path)] || "#7d8b9f";
  return `<span class="fic" style="color:${color}">${I.file}</span>`;
}

/* ================================================================== api */

async function api(method, path, body) {
  const opts = { method, headers: { "X-Forge-Client": "1" } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  let data = null;
  try { data = await resp.json(); } catch { /* non-JSON */ }
  if (!resp.ok) {
    const err = new Error(data?.error || `${method} ${path} failed (${resp.status})`);
    err.code = data?.code;
    err.status = resp.status;
    throw err;
  }
  return data;
}

/* ============================================================== overlays */

function modal({ title, body, actions = [], wide = false }) {
  const back = el("div", { class: "modal-back" });
  const box = el("div", { class: `modal${wide ? " wide" : ""}` });
  box.appendChild(el("div", { class: "modal-title" },
    `<span>${esc(title)}</span>`));
  const closeBtn = el("button", { class: "btn icon ghost modal-x", title: "Close" }, I.x);
  box.querySelector(".modal-title").appendChild(closeBtn);
  const bodyEl = el("div", { class: "modal-body" });
  box.appendChild(bodyEl);
  const foot = el("div", { class: "modal-foot" });
  box.appendChild(foot);
  back.appendChild(box);
  document.body.appendChild(back);

  const close = () => { document.removeEventListener("keydown", onKey); back.remove(); };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey);
  closeBtn.addEventListener("click", close);
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });

  for (const a of actions) {
    const btn = el("button", { class: `btn ${a.kind || ""}` }, esc(a.label));
    btn.addEventListener("click", () => a.fn(close, box));
    foot.appendChild(btn);
  }
  if (typeof body === "function") body(bodyEl, close);
  else bodyEl.innerHTML = body;
  return { close, box, bodyEl, foot };
}

function promptModal(title, { label = "", value = "", placeholder = "", ok = "Save" } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (val, close) => { if (!done) { done = true; resolve(val); } if (close) close(); };
    modal({
      title,
      body: (bodyEl, close) => {
        if (label) bodyEl.appendChild(el("label", { class: "label" }, esc(label)));
        const input = el("input", { class: "input", value, placeholder, spellcheck: "false" });
        bodyEl.appendChild(input);
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") finish(input.value.trim(), close);
        });
        setTimeout(() => { input.focus(); input.select(); }, 30);
      },
      actions: [
        { label: "Cancel", kind: "ghost", fn: (close) => finish(null, close) },
        {
          label: ok, kind: "primary",
          fn: (close, box) => finish($(".input", box).value.trim(), close),
        },
      ],
    });
  });
}

function confirmModal(title, text, { danger = false, ok = "Confirm" } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (val, close) => { if (!done) { done = true; resolve(val); } if (close) close(); };
    modal({
      title,
      body: `<p class="modal-text">${esc(text)}</p>`,
      actions: [
        { label: "Cancel", kind: "ghost", fn: (close) => finish(false, close) },
        { label: ok, kind: danger ? "danger" : "primary", fn: (close) => finish(true, close) },
      ],
    });
  });
}

function ctxMenu(x, y, items) {
  $$(".ctx").forEach((c) => c.remove());
  const menu = el("div", { class: "ctx" });
  for (const item of items) {
    if (item === "sep") { menu.appendChild(el("div", { class: "ctx-sep" })); continue; }
    const row = el("button", { class: `ctx-item${item.danger ? " danger" : ""}` },
      `${item.icon || ""}<span>${esc(item.label)}</span>`);
    row.addEventListener("click", () => { menu.remove(); item.fn(); });
    menu.appendChild(row);
  }
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, innerWidth - rect.width - 8)}px`;
  menu.style.top = `${Math.min(y, innerHeight - rect.height - 8)}px`;
  const away = (e) => {
    if (!menu.contains(e.target)) { menu.remove(); cleanup(); }
  };
  const onKey = (e) => { if (e.key === "Escape") { menu.remove(); cleanup(); } };
  const cleanup = () => {
    document.removeEventListener("mousedown", away, true);
    document.removeEventListener("keydown", onKey);
  };
  setTimeout(() => {
    document.addEventListener("mousedown", away, true);
    document.addEventListener("keydown", onKey);
  }, 0);
}

/* ============================================================ markdown-ish */

function mdSegments(text) {
  const lines = (text || "").split("\n");
  const segs = [];
  let prose = [], code = null;
  const flushProse = () => {
    if (prose.length && prose.join("").trim()) segs.push({ t: "p", body: prose.join("\n") });
    prose = [];
  };
  for (const line of lines) {
    if (code === null && line.startsWith("```")) {
      flushProse();
      code = { t: "code", info: line.slice(3).trim(), lines: [] };
    } else if (code !== null && line.trim() === "```") {
      segs.push({ t: "code", info: code.info, body: code.lines.join("\n"), closed: true });
      code = null;
    } else if (code !== null) {
      code.lines.push(line);
    } else {
      prose.push(line);
    }
  }
  if (code) segs.push({ t: "code", info: code.info, body: code.lines.join("\n"), closed: false });
  flushProse();
  return segs;
}

function fileBlocks(text) {
  return mdSegments(text)
    .filter((s) => s.t === "code" && s.closed && s.info.startsWith("file:"))
    .map((s) => ({ path: s.info.slice(5).trim().replace(/^\/+/, ""), content: s.body }))
    .filter((f) => f.path);
}

function proseHtml(text) {
  let h = esc(text);
  h = h.replace(/\[([^\]\n]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  h = h.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/^#{1,4} (.*)$/gm, '<span class="md-h">$1</span>');
  h = h.replace(/^[-*] (.*)$/gm, '<span class="md-li">•&nbsp; $1</span>');
  h = h.replace(/^\d+\. (.*)$/gm, '<span class="md-li">$&</span>');
  return h.replace(/\n/g, "<br>");
}

function mdHtml(text) {
  return mdSegments(text).map((seg) => {
    if (seg.t === "p") return `<div class="md-p">${proseHtml(seg.body)}</div>`;
    const isFile = seg.info.startsWith("file:");
    const label = isFile ? seg.info.slice(5).trim() : (seg.info || "code");
    const apply = isFile && seg.closed
      ? `<button class="btn sm apply-btn" data-path="${esc(seg.info.slice(5).trim())}">Apply</button>`
      : "";
    return (
      `<div class="md-code${isFile ? " is-file" : ""}">` +
      `<div class="md-code-head"><span>${esc(label)}</span>${apply}</div>` +
      `<pre>${esc(seg.body)}</pre></div>`
    );
  }).join("");
}

/* ============================================================ line diff */

function diffLines(aText, bText) {
  const a = aText.split("\n"), b = bText.split("\n");
  let pre = 0;
  while (pre < a.length && pre < b.length && a[pre] === b[pre]) pre++;
  let endA = a.length, endB = b.length;
  while (endA > pre && endB > pre && a[endA - 1] === b[endB - 1]) { endA--; endB--; }
  const midA = a.slice(pre, endA), midB = b.slice(pre, endB);
  const n = midA.length, m = midB.length;
  if (n * m > 400000) return null;  // too big for a per-line diff
  const w = m + 1;
  const dp = new Int32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] = midA[i] === midB[j]
        ? dp[(i + 1) * w + j + 1] + 1
        : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
    }
  }
  const out = [];
  for (let k = 0; k < pre; k++) out.push([" ", a[k]]);
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (midA[i] === midB[j]) { out.push([" ", midA[i]]); i++; j++; }
    else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) out.push(["-", midA[i++]]);
    else out.push(["+", midB[j++]]);
  }
  while (i < n) out.push(["-", midA[i++]]);
  while (j < m) out.push(["+", midB[j++]]);
  for (let k = endA; k < a.length; k++) out.push([" ", a[k]]);
  return out;
}

function diffHtml(current, proposed) {
  const row = ([t, s]) =>
    `<div class="dl${t === "+" ? " add" : t === "-" ? " del" : ""}">${esc(s) || "&nbsp;"}</div>`;
  if (current === null) {  // brand-new file: show it all as additions
    const lines = proposed.split("\n").slice(0, 400);
    return `<div class="diff">${lines.map((l) => row(["+", l])).join("")}</div>`;
  }
  const d = diffLines(current, proposed);
  if (!d) return '<p class="hint">Too large to diff — the whole file will be replaced.</p>';
  const rows = [];
  let run = [];
  const flush = () => {
    if (run.length > 8) {
      rows.push(...run.slice(0, 3).map(row),
        `<div class="dl skip">⋯ ${run.length - 6} unchanged lines</div>`,
        ...run.slice(-3).map(row));
    } else rows.push(...run.map(row));
    run = [];
  };
  for (const item of d) {
    if (item[0] === " ") run.push(item);
    else { flush(); rows.push(row(item)); }
  }
  flush();
  return `<div class="diff">${rows.join("")}</div>`;
}

/* ============================================================ app state */

const state = { system: null, ws: null };
const appRoot = $("#app") || document.body.appendChild(el("div", { id: "app" }));

function nav(path) {
  history.pushState({}, "", path);
  route();
}

async function route() {
  if (state.ws) { state.ws.cleanup(); state.ws = null; }
  const path = location.pathname;
  const m = path.match(/^\/app\/([a-z0-9-]+)$/);
  try {
    if (m) await renderWorkspace(m[1]);
    else await renderDashboard();
  } catch (e) {
    if (e.status === 404 && m) { toast("Project not found", "err"); nav("/"); return; }
    appRoot.innerHTML = `<div class="fatal"><h2>Something broke</h2><p>${esc(e.message)}</p></div>`;
  }
}

/* ============================================================= dashboard */

async function renderDashboard() {
  const [sys, projRes, tplRes] = await Promise.all([
    api("GET", "/api/system"), api("GET", "/api/projects"), api("GET", "/api/templates"),
  ]);
  state.system = sys;
  const projects = projRes.projects;
  document.title = "Forge";

  appRoot.innerHTML = `
    <div class="db">
      <header class="db-top">
        <div class="brand">${I.logo}<span>Forge</span></div>
        <div class="db-top-right">
          <button class="pill ${sys.ai_ready ? "pill-ok" : "pill-warn"}" id="ai-pill">
            ${I.sparkle}<span>${sys.ai_ready ? "Claude connected" : "Add Claude key"}</span>
          </button>
          <button class="btn icon ghost" id="settings-btn" title="Settings">${I.gear}</button>
        </div>
      </header>
      <section class="db-hero">
        <h1>Build websites &amp; apps <br>right in your browser.</h1>
        <p class="db-sub">Pick a template, edit with a live preview, run real code,
          download the result. Pair with Claude to build even faster.</p>
        <button class="btn primary big" id="new-btn">${I.plus}<span>New project</span></button>
      </section>
      <h2 class="db-h2">Start from a template</h2>
      <div class="tpl-row" id="tpl-row"></div>
      <h2 class="db-h2">Your projects <span class="count">${projects.length}</span></h2>
      <div class="proj-grid" id="proj-grid"></div>
      <footer class="db-foot">forge ${esc(sys.version)} · local-first — everything stays on this machine</footer>
    </div>`;

  $("#settings-btn").addEventListener("click", () => settingsModal());
  $("#ai-pill").addEventListener("click", () => settingsModal());
  $("#new-btn").addEventListener("click", () => newProjectModal(tplRes.templates));

  const tplRow = $("#tpl-row");
  for (const t of tplRes.templates) {
    const card = el("button", { class: "tpl-card" }, `
      <span class="tpl-kind ${t.kind}">${t.kind === "web" ? I.globe : I.terminal}</span>
      <h4>${esc(t.label)}</h4><p>${esc(t.desc)}</p>`);
    card.addEventListener("click", () => newProjectModal(tplRes.templates, t.id));
    tplRow.appendChild(card);
  }

  const grid = $("#proj-grid");
  if (!projects.length) {
    grid.innerHTML = `
      <div class="empty">
        <div class="empty-art">${I.logo}</div>
        <p>No projects yet. Create one from a template above —<br>
           or run <code>python3 -m forge demo</code> for samples.</p>
      </div>`;
    return;
  }
  for (const p of projects) {
    const card = el("div", { class: "proj-card", tabindex: "0", role: "button" }, `
      <div class="proj-head">
        <span class="proj-kind ${p.kind}">${p.kind === "web" ? I.globe : I.terminal}</span>
        <button class="btn icon ghost proj-menu">${I.dots}</button>
      </div>
      <div class="proj-name">${esc(p.name)}</div>
      <div class="proj-meta">${esc(p.template)} · updated ${timeAgo(p.updated)}</div>`);
    const open = () => nav(`/app/${p.id}`);
    card.addEventListener("click", (e) => {
      if (!e.target.closest(".proj-menu")) open();
    });
    card.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    $(".proj-menu", card).addEventListener("click", (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      ctxMenu(r.left, r.bottom + 4, [
        { label: "Open", icon: I.chevron, fn: open },
        { label: "Rename", icon: I.pencil, fn: async () => {
          const name = await promptModal("Rename project", { value: p.name, ok: "Rename" });
          if (name) { await api("PATCH", `/api/projects/${p.id}`, { name }); route(); }
        } },
        { label: "Duplicate", icon: I.copy, fn: async () => {
          await api("POST", `/api/projects/${p.id}/duplicate`, {});
          toast("Project duplicated", "ok"); route();
        } },
        { label: "Download zip", icon: I.download, fn: () => {
          location.href = `/api/projects/${p.id}/export`;
        } },
        "sep",
        { label: "Delete", icon: I.trash, danger: true, fn: async () => {
          if (await confirmModal("Delete project",
            `"${p.name}" and all of its files will be deleted. This cannot be undone.`,
            { danger: true, ok: "Delete" })) {
            await api("DELETE", `/api/projects/${p.id}`);
            toast("Project deleted", "ok"); route();
          }
        } },
      ]);
    });
    grid.appendChild(card);
  }
}

function newProjectModal(templates, preselect) {
  let selected = preselect || templates[0]?.id;
  modal({
    title: "New project",
    wide: true,
    body: (bodyEl, close) => {
      bodyEl.innerHTML = `
        <label class="label">Name</label>
        <input class="input" id="np-name" placeholder="My cool site" spellcheck="false">
        <label class="label">Template</label>
        <div class="tpl-pick" id="np-tpls"></div>`;
      const pick = $("#np-tpls", bodyEl);
      for (const t of templates) {
        const card = el("button", {
          class: `tpl-card sm${t.id === selected ? " sel" : ""}`, "data-id": t.id,
        }, `<span class="tpl-kind ${t.kind}">${t.kind === "web" ? I.globe : I.terminal}</span>
            <h4>${esc(t.label)}</h4><p>${esc(t.desc)}</p>`);
        card.addEventListener("click", () => {
          selected = t.id;
          $$(".tpl-card", pick).forEach((c) => c.classList.toggle("sel", c.dataset.id === t.id));
        });
        pick.appendChild(card);
      }
      const name = $("#np-name", bodyEl);
      name.addEventListener("keydown", (e) => { if (e.key === "Enter") create(close, bodyEl); });
      setTimeout(() => name.focus(), 30);
    },
    actions: [
      { label: "Cancel", kind: "ghost", fn: (close) => close() },
      { label: "Create project", kind: "primary", fn: (close, box) => create(close, box) },
    ],
  });
  async function create(close, root) {
    const name = $("#np-name", root).value.trim();
    if (!name) { toast("Give it a name", "err"); return; }
    try {
      const meta = await api("POST", "/api/projects", { name, template: selected });
      close();
      nav(`/app/${meta.id}`);
    } catch (e) { toast(e.message, "err"); }
  }
}

async function settingsModal() {
  const sys = await api("GET", "/api/system");
  state.system = sys;
  const P = sys.providers;
  const sel = { ...(sys.ai || { provider: "anthropic", model: sys.default_model }) };

  const provCard = (pid, controls) => {
    const p = P[pid];
    const chip = p.ready
      ? `<span class="prov-chip ok">${p.source === "env" ? "env key" : "ready"}</span>`
      : `<span class="prov-chip">${pid === "compat" ? "no base URL" : "no key"}</span>`;
    return `
      <div class="prov" data-pid="${pid}">
        <div class="prov-head">
          <b>${esc(p.label)}</b>${chip}
          ${p.key_masked ? `<span class="hint-inline">${esc(p.key_masked)}</span>` : ""}
          <span class="spacer"></span>
          ${p.source === "settings" ? '<button class="btn ghost sm prov-rm">remove key</button>' : ""}
        </div>
        ${controls}
      </div>`;
  };

  modal({
    title: "Settings",
    wide: true,
    body: (bodyEl) => {
      bodyEl.innerHTML = `
        <h3 class="modal-h">${I.sparkle} AI models</h3>
        <p class="hint">Bring your own keys — saved only to
          <code>data/forge/settings.json</code> on this machine (never committed).
          Environment variables (<code>ANTHROPIC_API_KEY</code>,
          <code>OPENAI_API_KEY</code>, <code>GEMINI_API_KEY</code>) override saved keys.</p>
        <label class="label">Default chat model</label>
        <div class="row">
          <select class="select" id="set-prov" style="max-width: 46%">
            ${Object.entries(P).map(([pid, p]) =>
              `<option value="${pid}"${pid === sel.provider ? " selected" : ""}>${esc(p.label)}</option>`).join("")}
          </select>
          <span id="set-model-slot" style="flex:1"></span>
        </div>
        ${provCard("anthropic", `
          <input class="input prov-key" type="password" placeholder="sk-ant-…"
                 autocomplete="off" spellcheck="false">`)}
        ${provCard("openai", `
          <div class="row">
            <input class="input prov-key" type="password" placeholder="sk-…"
                   autocomplete="off" spellcheck="false">
            <input class="input mono prov-model" placeholder="model · e.g. gpt-4o"
                   value="${esc(P.openai.default_model)}" spellcheck="false"
                   style="max-width: 44%">
          </div>`)}
        ${provCard("gemini", `
          <div class="row">
            <input class="input prov-key" type="password" placeholder="AIza…"
                   autocomplete="off" spellcheck="false">
            <input class="input mono prov-model" placeholder="model · e.g. gemini-2.0-flash"
                   value="${esc(P.gemini.default_model)}" spellcheck="false"
                   style="max-width: 44%">
          </div>`)}
        ${provCard("compat", `
          <input class="input mono prov-url"
                 placeholder="base URL · e.g. http://127.0.0.1:11434/v1"
                 value="${esc(P.compat.base_url || "")}" spellcheck="false">
          <div class="row" style="margin-top: 8px">
            <input class="input prov-key" type="password"
                   placeholder="API key (optional)" autocomplete="off" spellcheck="false">
            <input class="input mono prov-model" placeholder="model · e.g. llama3"
                   value="${esc(P.compat.default_model)}" spellcheck="false"
                   style="max-width: 44%">
          </div>
          <p class="hint">Ollama, OpenRouter, Groq — anything speaking the OpenAI chat API.</p>`)}`;

      const modelSlot = $("#set-model-slot", bodyEl);
      const renderModelPick = () => {
        const pid = $("#set-prov", bodyEl).value;
        if (pid === "anthropic") {
          const current = sel.provider === "anthropic" ? sel.model : P.anthropic.default_model;
          modelSlot.innerHTML = `<select class="select" id="set-model">
            ${P.anthropic.models.map((m) =>
              `<option value="${esc(m.id)}"${m.id === current ? " selected" : ""}>${esc(m.label)} — ${esc(m.blurb)}</option>`).join("")}
          </select>`;
        } else {
          modelSlot.innerHTML =
            `<span class="hint">uses the model on the ${esc(P[pid].label)} card below</span>`;
        }
      };
      renderModelPick();
      $("#set-prov", bodyEl).addEventListener("change", renderModelPick);
      $$(".prov-rm", bodyEl).forEach((btn) => btn.addEventListener("click", async (e) => {
        const pid = e.target.closest(".prov").dataset.pid;
        await api("POST", "/api/settings", { providers: { [pid]: { api_key: "" } } });
        toast("Key removed", "ok");
        await refreshSystem();
      }));
    },
    actions: [
      { label: "Cancel", kind: "ghost", fn: (close) => close() },
      {
        label: "Save", kind: "primary",
        fn: async (close, box) => {
          const providers = {};
          $$(".prov", box).forEach((card) => {
            const pid = card.dataset.pid;
            const conf = {};
            const key = $(".prov-key", card)?.value.trim();
            if (key) conf.api_key = key;
            const modelInput = $(".prov-model", card);
            if (modelInput) conf.model = modelInput.value.trim();
            const urlInput = $(".prov-url", card);
            if (urlInput) conf.base_url = urlInput.value.trim();
            if (Object.keys(conf).length) providers[pid] = conf;
          });
          const provider = $("#set-prov", box).value;
          const model = provider === "anthropic"
            ? $("#set-model", box).value
            : ($(`.prov[data-pid="${provider}"] .prov-model`, box)?.value.trim() || "");
          try {
            await api("POST", "/api/settings", { providers, ai: { provider, model } });
            toast("Settings saved", "ok");
            close();
            await refreshSystem();
          } catch (e) { toast(e.message, "err"); }
        },
      },
    ],
  });
}

async function refreshSystem() {
  state.system = await api("GET", "/api/system");
  if (!state.ws) route();
  else state.ws.onSystem?.();
}

/* ============================================================= workspace */

async function renderWorkspace(pid) {
  const meta = await api("GET", `/api/projects/${pid}`);
  if (!state.system) state.system = await api("GET", "/api/system");
  document.title = `${meta.name} · Forge`;

  const ws = {
    pid, meta,
    tabs: [], active: null,
    openDirs: new Set(),
    es: null, running: false,
    right: meta.kind === "web" ? "preview" : "ai",
    ai: {
      msgs: [], busy: false, build: true, ctrl: null,
      ctx: new Set(), ctxCustom: false,
      provider: state.system.ai?.provider || "anthropic",
      model: state.system.ai?.model || state.system.default_model,
    },
    cleanups: [],
    cleanup() { this.cleanups.forEach((fn) => { try { fn(); } catch {} }); },
  };
  state.ws = ws;

  appRoot.innerHTML = `
  <div class="ws">
    <header class="ws-top">
      <button class="btn icon ghost" id="w-back" title="All projects">${I.back}</button>
      <div class="brand sm">${I.logo}</div>
      <button class="ws-title" id="w-title" title="Rename">${esc(meta.name)}</button>
      <span class="ws-badge ${meta.kind}">${meta.kind === "web" ? "website" : "program"}</span>
      <div class="spacer"></div>
      <button class="btn primary sm" id="w-run">${I.play}<span>Run</span></button>
      <button class="btn icon ghost" id="w-console" title="Toggle console">${I.terminal}</button>
      <button class="btn icon ghost" id="w-history" title="Snapshots / history">${I.clock}</button>
      <button class="btn icon ghost" id="w-export" title="Download zip">${I.download}</button>
      <button class="btn icon ghost" id="w-settings" title="Project settings">${I.gear}</button>
    </header>
    <div class="ws-body">
      <aside class="side" id="w-side">
        <div class="side-head"><span>Files</span>
          <span class="side-tools">
            <button class="btn icon ghost sm" id="t-newfile" title="New file">${I.filePlus}</button>
            <button class="btn icon ghost sm" id="t-newdir" title="New folder">${I.folderPlus}</button>
            <button class="btn icon ghost sm" id="t-upload" title="Upload files">${I.upload}</button>
          </span>
        </div>
        <div class="side-search">
          <input id="w-search" placeholder="Search project…" spellcheck="false">
        </div>
        <div class="tree" id="w-tree"></div>
        <input type="file" id="w-file-input" multiple hidden>
      </aside>
      <div class="rz rz-v" id="rz-side"></div>
      <main class="ws-main" id="w-main">
        <div class="ed-area">
          <div class="tabs" id="w-tabs"><div class="tabs-status" id="w-status"></div></div>
          <div class="ed-host" id="w-edhost">
            <div class="ed-empty" id="w-edempty">
              <div>${I.logo}</div>
              <p>Open a file from the left — or ask the AI to build something.</p>
              <p class="kbd-row"><span class="kbd">⌘S</span> save
                 <span class="kbd">⌘↵</span> run
                 <span class="kbd">⌘/</span> comment</p>
            </div>
          </div>
        </div>
        <div class="rz rz-h" id="rz-console"></div>
        <section class="console" id="w-consolebox">
          <div class="console-head">
            <span class="console-title">${I.terminal} Console</span>
            <span class="console-status" id="c-status">idle</span>
            <div class="spacer"></div>
            <button class="btn icon ghost sm" id="c-clear" title="Clear">${I.trash}</button>
          </div>
          <div class="console-body" id="c-body"></div>
          <div class="console-in" id="c-inrow" hidden>
            <span class="c-prompt">›</span>
            <input id="c-input" placeholder="send input to the program…" spellcheck="false">
          </div>
        </section>
      </main>
      <div class="rz rz-v" id="rz-right"></div>
      <aside class="right" id="w-right">
        <div class="right-head">
          <div class="seg">
            <button class="seg-btn" data-pane="preview">${I.eye}<span>Preview</span></button>
            <button class="seg-btn" data-pane="ai">${I.sparkle}<span>AI</span></button>
          </div>
          <div class="spacer"></div>
          <span id="right-tools"></span>
        </div>
        <div class="right-body" id="right-body"></div>
      </aside>
    </div>
    <nav class="mnav" id="w-mnav">
      <button data-pane="files">${I.folder}<span>Files</span></button>
      <button data-pane="code" class="active">${I.terminal}<span>Code</span></button>
      <button data-pane="preview">${I.eye}<span>Preview</span></button>
      <button data-pane="ai">${I.sparkle}<span>AI</span></button>
    </nav>
  </div>`;

  /* ---------- workspace helpers bound to `ws` ---------- */

  const treeEl = $("#w-tree"), tabsEl = $("#w-tabs"), hostEl = $("#w-edhost");
  const statusEl = $("#w-status"), cBody = $("#c-body"), cStatus = $("#c-status");

  /* ----- files & tabs ----- */

  async function refreshTree() {
    const res = await api("GET", `/api/projects/${pid}/tree`);
    ws.tree = res.tree;
    if (!ws._dirsInit) {
      ws._dirsInit = true;
      res.tree.filter((e) => e.type === "dir" && !e.path.includes("/"))
        .forEach((e) => ws.openDirs.add(e.path));
    }
    renderTree();
  }

  function renderTree() {
    if (($("#w-search")?.value.trim().length || 0) >= 2) return;
    treeEl.innerHTML = "";
    const visible = ws.tree.filter((entry) => {
      const parts = entry.path.split("/");
      for (let i = 1; i < parts.length; i++) {
        if (!ws.openDirs.has(parts.slice(0, i).join("/"))) return false;
      }
      return true;
    });
    if (!visible.length) {
      treeEl.innerHTML = '<div class="tree-empty">No files yet.<br>Create one with the buttons above.</div>';
    }
    for (const entry of visible) {
      const depth = entry.path.split("/").length - 1;
      const isDir = entry.type === "dir";
      const open = ws.openDirs.has(entry.path);
      const row = el("div", {
        class: `tree-item ${entry.type}${ws.active?.path === entry.path ? " active" : ""}`,
        style: `padding-left:${10 + depth * 14}px`, title: entry.path,
      }, `
        ${isDir ? `<span class="tw${open ? " open" : ""}">${I.chevron}</span>
                   <span class="fic" style="color:#8fa3bd">${I.folder}</span>`
                : fileIcon(entry.path)}
        <span class="tree-name">${esc(entry.path.split("/").pop())}</span>
        <button class="btn icon ghost sm tree-more">${I.dots}</button>`);
      row.addEventListener("click", (e) => {
        if (e.target.closest(".tree-more")) return;
        if (isDir) {
          ws.openDirs.has(entry.path) ? ws.openDirs.delete(entry.path) : ws.openDirs.add(entry.path);
          renderTree();
        } else openFile(entry.path);
      });
      const menu = (x, y) => ctxMenu(x, y, [
        ...(isDir ? [
          { label: "New file here", icon: I.filePlus, fn: () => newFile(entry.path + "/") },
          { label: "New folder here", icon: I.folderPlus, fn: () => newFolder(entry.path + "/") },
          "sep",
        ] : []),
        { label: "Rename / move", icon: I.pencil, fn: async () => {
          const dst = await promptModal("Rename / move", {
            label: "New path", value: entry.path, ok: "Move" });
          if (!dst || dst === entry.path) return;
          try {
            await api("POST", `/api/projects/${pid}/move`, { src: entry.path, dst });
            retargetTabs(entry.path, dst, isDir);
            await refreshTree();
          } catch (e) { toast(e.message, "err"); }
        } },
        { label: "Delete", icon: I.trash, danger: true, fn: async () => {
          if (!await confirmModal("Delete", `Delete ${entry.path}?`, { danger: true, ok: "Delete" }))
            return;
          await api("DELETE", `/api/projects/${pid}/file?path=${encodeURIComponent(entry.path)}`);
          closeTabsUnder(entry.path, isDir);
          await refreshTree();
          reloadPreview();
        } },
      ]);
      row.addEventListener("contextmenu", (e) => { e.preventDefault(); menu(e.clientX, e.clientY); });
      $(".tree-more", row).addEventListener("click", (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        menu(r.left, r.bottom + 4);
      });
      treeEl.appendChild(row);
    }
  }

  function retargetTabs(src, dst, isDir) {
    for (const tab of ws.tabs) {
      if (tab.path === src) tab.path = dst;
      else if (isDir && tab.path.startsWith(src + "/"))
        tab.path = dst + tab.path.slice(src.length);
    }
    renderTabs();
  }

  function closeTabsUnder(path, isDir) {
    ws.tabs.filter((t) => t.path === path || (isDir && t.path.startsWith(path + "/")))
      .forEach((t) => closeTab(t, true));
  }

  async function newFile(prefix = "") {
    const path = await promptModal("New file", {
      label: "Path", value: prefix, placeholder: "index.html", ok: "Create" });
    if (!path) return;
    try {
      await api("PUT", `/api/projects/${pid}/file?path=${encodeURIComponent(path)}`,
        { content: "" });
      await refreshTree();
      openFile(path);
    } catch (e) { toast(e.message, "err"); }
  }

  async function newFolder(prefix = "") {
    const path = await promptModal("New folder", {
      label: "Path", value: prefix, placeholder: "assets", ok: "Create" });
    if (!path) return;
    try {
      await api("POST", `/api/projects/${pid}/folder`, { path });
      ws.openDirs.add(path);
      await refreshTree();
    } catch (e) { toast(e.message, "err"); }
  }

  function b64of(buf) {
    const bytes = new Uint8Array(buf);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000)
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }

  async function uploadFiles(files) {
    for (const f of files) {
      try {
        await api("PUT", `/api/projects/${pid}/file?path=${encodeURIComponent(f.name)}`,
          { content_b64: b64of(await f.arrayBuffer()) });
      } catch (e) { toast(`${f.name}: ${e.message}`, "err"); }
    }
    toast(`Uploaded ${files.length} file${files.length > 1 ? "s" : ""}`, "ok");
    await refreshTree();
    reloadPreview();
  }

  async function openFile(path) {
    let tab = ws.tabs.find((t) => t.path === path);
    if (!tab) {
      let data;
      try { data = await api("GET", `/api/projects/${pid}/file?path=${encodeURIComponent(path)}`); }
      catch (e) { toast(e.message, "err"); return; }
      tab = { path, dirty: false, savedValue: data.content, binary: data.binary, size: data.size };
      tab.wrap = el("div", { class: "ed-wrap" });
      hostEl.appendChild(tab.wrap);
      if (data.binary) {
        const isImg = IMG_EXTS.has(extOf(path));
        tab.wrap.innerHTML = isImg
          ? `<div class="bin-view"><img src="/p/${pid}/${esc(path)}" alt="${esc(path)}">
             <p>${esc(path)} · ${fmtSize(data.size)}</p></div>`
          : `<div class="bin-view"><p>${I.file}</p>
             <p>${esc(path)} — binary file, ${fmtSize(data.size)}</p></div>`;
      } else {
        tab.ed = new ForgeEditor(tab.wrap, {
          value: data.content,
          language: ForgeEditor.langForPath(path),
          onChange: (value) => {
            tab.dirty = value !== tab.savedValue;
            renderTabs();
            autosave(tab);
          },
          onSave: () => saveTab(tab),
          onRun: () => runOrStop(),
          onCursor: (ln, col) => {
            if (ws.active === tab) renderStatus(`Ln ${ln}, Col ${col}`);
          },
        });
      }
      ws.tabs.push(tab);
    }
    ws.active = tab;
    renderTabs();
    renderTree();
    for (const t of ws.tabs) t.wrap.classList.toggle("on", t === tab);
    $("#w-edempty").style.display = "none";
    tab.ed?.focus();
  }

  function closeTab(tab, force = false) {
    const doClose = () => {
      tab.ed?.destroy();
      tab.wrap.remove();
      ws.tabs = ws.tabs.filter((t) => t !== tab);
      if (ws.active === tab) {
        ws.active = ws.tabs[ws.tabs.length - 1] || null;
        if (ws.active) openFile(ws.active.path);
        else { $("#w-edempty").style.display = ""; renderTabs(); renderTree(); renderStatus(""); }
      } else renderTabs();
    };
    if (tab.dirty && !force) {
      confirmModal("Unsaved changes", `Close ${tab.path} without saving?`,
        { danger: true, ok: "Close" }).then((yes) => { if (yes) doClose(); });
    } else doClose();
  }

  function renderTabs() {
    $$(".tab", tabsEl).forEach((t) => t.remove());
    for (const tab of ws.tabs) {
      const t = el("button", { class: `tab${tab === ws.active ? " active" : ""}`, title: tab.path }, `
        ${fileIcon(tab.path)}<span>${esc(tab.path.split("/").pop())}</span>
        <span class="tab-dot${tab.dirty ? " on" : ""}"></span>
        <span class="tab-x">${I.x}</span>`);
      t.addEventListener("click", (e) => {
        if (e.target.closest(".tab-x")) closeTab(tab);
        else openFile(tab.path);
      });
      t.addEventListener("auxclick", (e) => { if (e.button === 1) closeTab(tab); });
      tabsEl.insertBefore(t, statusEl);
    }
  }

  function renderStatus(cursorText) {
    const tab = ws.active;
    const lang = tab && !tab.binary ? ForgeEditor.langForPath(tab.path) : "";
    const save = !tab ? "" : tab.dirty ? "· unsaved" : "· saved";
    statusEl.textContent = tab ? `${cursorText || ""} ${lang} ${save}` : "";
  }

  const autosave = debounce((tab) => { if (tab.dirty) saveTab(tab, true); }, 900);

  async function saveTab(tab, quiet = false) {
    if (!tab || tab.binary || !tab.ed) return;
    const value = tab.ed.getValue();
    if (value === tab.savedValue) return;
    try {
      await api("PUT", `/api/projects/${pid}/file?path=${encodeURIComponent(tab.path)}`,
        { content: value });
      tab.savedValue = value;
      tab.dirty = tab.ed.getValue() !== value;
      renderTabs(); renderStatus("");
      if (!quiet) toast("Saved", "ok");
      reloadPreview();
    } catch (e) { toast(`Save failed: ${e.message}`, "err"); }
  }

  async function saveAll() {
    for (const tab of ws.tabs) if (tab.dirty) await saveTab(tab, true);
  }

  /* ----- console & running ----- */

  let cQueue = [], cFlushScheduled = false, cLast = null;
  function cAppend(kind, text) {
    cQueue.push([kind, text.replace(/\x1b\[[0-9;]*[A-Za-z]/g, "")]);
    if (!cFlushScheduled) {
      cFlushScheduled = true;
      requestAnimationFrame(() => {
        cFlushScheduled = false;
        const nearBottom = cBody.scrollHeight - cBody.scrollTop - cBody.clientHeight < 60;
        for (const [kind2, text2] of cQueue) {
          if (cLast && cLast.dataset.kind === kind2) cLast.textContent += text2;
          else {
            cLast = el("span", { class: `c-${kind2}`, "data-kind": kind2 });
            cLast.textContent = text2;
            cBody.appendChild(cLast);
          }
        }
        cQueue = [];
        while (cBody.children.length > 2000) cBody.firstChild.remove();
        if (nearBottom) cBody.scrollTop = cBody.scrollHeight;
      });
    }
  }
  const cSys = (text) => cAppend("sys", text + "\n");

  function setRunning(running) {
    ws.running = running;
    const btn = $("#w-run");
    btn.innerHTML = running ? `${I.stop}<span>Stop</span>` : `${I.play}<span>Run</span>`;
    btn.classList.toggle("danger", running);
    btn.classList.toggle("primary", !running);
    $("#c-inrow").hidden = !running;
    cStatus.textContent = running ? "running" : "idle";
    cStatus.className = `console-status${running ? " run" : ""}`;
    if (running) $("#c-input").focus();
  }

  function attachStream() {
    ws.es?.close();
    const es = new EventSource(`/api/projects/${pid}/run/stream`);
    ws.es = es;
    es.addEventListener("start", (e) => {
      setRunning(true);
      showConsole(true);
      cSys(`$ ${JSON.parse(e.data).command}`);
    });
    es.addEventListener("out", (e) => cAppend("out", JSON.parse(e.data).text));
    es.addEventListener("err", (e) => cAppend("err", JSON.parse(e.data).text));
    es.addEventListener("exit", (e) => {
      const d = JSON.parse(e.data);
      cSys(`— exited with code ${d.code} · ${d.seconds}s`);
      cStatus.textContent = `exit ${d.code}`;
      cStatus.className = `console-status${d.code === 0 ? " ok" : " err"}`;
      setRunningSoft(d.code);
      es.close();
    });
    es.addEventListener("none", () => { es.close(); });
    es.onerror = () => { /* EventSource retries with Last-Event-ID on its own */ };
  }

  function setRunningSoft(code) {
    ws.running = false;
    const btn = $("#w-run");
    btn.innerHTML = `${I.play}<span>Run</span>`;
    btn.classList.remove("danger"); btn.classList.add("primary");
    $("#c-inrow").hidden = true;
    cStatus.textContent = `exit ${code}`;
  }

  async function runOrStop() {
    if (ws.running) {
      await api("POST", `/api/projects/${pid}/run/stop`, {});
      return;
    }
    await saveAll();
    if (!ws.meta.run) {
      if (ws.meta.kind === "web") {
        setRight("preview");
        toast("Static site — it's already live in the preview", "ok");
        return;
      }
      toast("Set a run command in project settings first", "err");
      projectSettingsModal();
      return;
    }
    cBody.innerHTML = ""; cLast = null;
    try {
      await api("POST", `/api/projects/${pid}/run`, {});
      attachStream();
      if (+ws.meta.port) {
        ws.previewMode = "app";
        setRight("preview");
      }
    } catch (e) { toast(e.message, "err"); }
  }

  function showConsole(show) {
    const box = $("#w-consolebox"), rz = $("#rz-console");
    const on = show ?? box.classList.contains("hide");
    box.classList.toggle("hide", !on);
    rz.classList.toggle("hide", !on);
  }

  /* ----- right pane: preview + AI ----- */

  const rightBody = $("#right-body"), rightTools = $("#right-tools");
  let previewFrame = null;

  function setRight(pane) {
    ws.right = pane;
    $$(".seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.pane === pane));
    if (pane === "preview") renderPreview();
    else renderAi();
  }

  function renderPreview() {
    rightTools.innerHTML = "";
    rightBody.innerHTML = "";
    const port = +ws.meta.port || 0;
    if (!port) ws.previewMode = "files";
    else if (!ws.previewMode) ws.previewMode = "app";
    const url = ws.previewMode === "app" ? `/proxy/${pid}/` : `/p/${pid}/`;
    previewFrame = el("iframe", { class: "preview-frame", src: url, title: "Preview" });
    rightBody.appendChild(previewFrame);
    if (port) {
      const seg = el("div", { class: "seg" }, `
        <button class="seg-btn${ws.previewMode === "files" ? " active" : ""}" data-m="files">Files</button>
        <button class="seg-btn${ws.previewMode === "app" ? " active" : ""}" data-m="app">App :${port}</button>`);
      $$("button", seg).forEach((b) => b.addEventListener("click", () => {
        ws.previewMode = b.dataset.m;
        renderPreview();
      }));
      rightTools.appendChild(seg);
    }
    const refresh = el("button", { class: "btn icon ghost sm", title: "Refresh" }, I.refresh);
    refresh.addEventListener("click", () => reloadPreview(true));
    const ext = el("a", {
      class: "btn icon ghost sm", href: url, target: "_blank",
      rel: "noopener", title: "Open in new tab",
    }, I.external);
    rightTools.append(refresh, ext);
  }

  const reloadPreview = debounce((force) => {
    if (ws.right !== "preview" || !previewFrame) return;
    try { previewFrame.contentWindow.location.reload(); }
    catch { previewFrame.src = previewFrame.src; }
  }, 250);

  function aiOptions() {
    const P = state.system.providers || {};
    const opts = [];
    for (const [pid, p] of Object.entries(P)) {
      if (pid === "anthropic") {
        for (const m of p.models || []) {
          opts.push({ v: `anthropic::${m.id}`, t: m.label, ready: p.ready });
        }
      } else if (p.default_model) {
        const name = p.label.replace(" (Anthropic)", "").replace("Google ", "");
        opts.push({ v: `${pid}::${p.default_model}`,
                    t: `${name} · ${p.default_model}`, ready: p.ready });
      }
    }
    return opts;
  }

  function renderAi() {
    rightTools.innerHTML = "";
    previewFrame = null;
    const opts = aiOptions();
    const current = `${ws.ai.provider}::${ws.ai.model}`;
    const modelSel = el("select", { class: "select sm", title: "Model" },
      opts.map((o) =>
        `<option value="${esc(o.v)}"${o.v === current ? " selected" : ""}` +
        `${o.ready ? "" : " disabled"}>${esc(o.t)}${o.ready ? "" : " — add key"}</option>`
      ).join(""));
    modelSel.addEventListener("change", () => {
      [ws.ai.provider, ws.ai.model] = modelSel.value.split("::");
      updateAiNote();
    });
    rightTools.appendChild(modelSel);

    rightBody.innerHTML = `
      <div class="ai">
        <div class="ai-msgs" id="ai-msgs"></div>
        <div class="ai-note" id="ai-note" hidden></div>
        <div class="ai-comp">
          <div class="ai-opts">
            <label class="chk"><input type="checkbox" id="ai-build" ${ws.ai.build ? "checked" : ""}>
              can edit files</label>
            <button class="btn ghost sm" id="ai-ctx-btn">${I.file}<span id="ai-ctx-label"></span></button>
          </div>
          <div class="ai-inrow">
            <textarea id="ai-input" rows="1"
              placeholder="Describe what to build or change…"></textarea>
            <button class="btn primary icon" id="ai-send" title="Send">${I.send}</button>
          </div>
        </div>
      </div>`;
    $("#ai-build").addEventListener("change", (e) => { ws.ai.build = e.target.checked; });
    $("#ai-ctx-btn").addEventListener("click", (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      ctxFilesPopover(r.left, r.top);
    });
    updateCtxLabel();
    const input = $("#ai-input");
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendAi(); }
    });
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    });
    $("#ai-send").addEventListener("click", () => {
      if (ws.ai.busy) ws.ai.ctrl?.abort();
      else sendAi();
    });
    $("#ai-msgs").addEventListener("click", (e) => {
      const btn = e.target.closest(".apply-btn");
      if (!btn) return;
      const msg = ws.ai.msgs[+btn.closest(".msg").dataset.idx];
      if (btn.dataset.all) confirmApply(fileBlocks(msg.content));
      else {
        const block = fileBlocks(msg.content).find((f) => f.path === btn.dataset.path);
        if (block) confirmApply([block]);
      }
    });
    renderAiMsgs();
    updateAiNote();
  }

  function currentCtxPaths() {
    if (ws.ai.ctxCustom) return [...ws.ai.ctx].slice(0, 8);
    return ws.active && !ws.active.binary ? [ws.active.path] : [];
  }

  function updateCtxLabel() {
    const label = $("#ai-ctx-label");
    if (!label) return;
    if (!ws.ai.ctxCustom) { label.textContent = "context: current file"; return; }
    const n = currentCtxPaths().length;
    label.textContent = `context: ${n} file${n === 1 ? "" : "s"}`;
  }

  function ctxFilesPopover(x, y) {
    $$(".ctx").forEach((c) => c.remove());
    const files = ws.tree.filter((e) => e.type === "file").slice(0, 50);
    const selected = new Set(currentCtxPaths());
    const pop = el("div", { class: "ctx ctx-files" },
      `<div class="ctx-title">Files the AI can read
         <span class="hint-inline">up to 8</span></div>` +
      files.map((f) => `<label class="ctx-check">
        <input type="checkbox" data-path="${esc(f.path)}"${selected.has(f.path) ? " checked" : ""}>
        <span>${esc(f.path)}</span></label>`).join(""));
    document.body.appendChild(pop);
    const rect = pop.getBoundingClientRect();
    pop.style.left = `${Math.min(x, innerWidth - rect.width - 8)}px`;
    pop.style.top = `${Math.max(8, Math.min(y - rect.height - 6, innerHeight - rect.height - 8))}px`;
    pop.addEventListener("change", (e) => {
      const checked = $$("input:checked", pop);
      if (checked.length > 8) {
        e.target.checked = false;
        toast("Up to 8 context files", "err");
        return;
      }
      ws.ai.ctxCustom = true;
      ws.ai.ctx = new Set($$("input:checked", pop).map((i) => i.dataset.path));
      updateCtxLabel();
    });
    const away = (e) => { if (!pop.contains(e.target)) { pop.remove(); cleanup(); } };
    const onKey = (e) => { if (e.key === "Escape") { pop.remove(); cleanup(); } };
    const cleanup = () => {
      document.removeEventListener("mousedown", away, true);
      document.removeEventListener("keydown", onKey);
    };
    setTimeout(() => {
      document.addEventListener("mousedown", away, true);
      document.addEventListener("keydown", onKey);
    }, 0);
  }

  function updateAiNote() {
    const note = $("#ai-note");
    if (!note) return;
    const P = state.system.providers || {};
    const current = P[ws.ai.provider];
    if (current?.ready) { note.hidden = true; return; }
    note.hidden = false;
    const what = ws.ai.provider === "compat" ? "a base URL" : "an API key";
    note.innerHTML = `${I.sparkle}
      <span>Add ${what} for ${esc(current?.label || ws.ai.provider)} —
        Claude, OpenAI, Gemini and local models all work.</span>
      <button class="btn sm primary" id="ai-addkey">Open settings</button>`;
    $("#ai-addkey").addEventListener("click", () => settingsModal());
  }
  ws.onSystem = () => {
    if (ws.right === "ai") renderAi();
    else updateAiNote();
  };

  function renderAiMsgs(streaming = false) {
    const box = $("#ai-msgs");
    if (!box) return;
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    if (!ws.ai.msgs.length) {
      box.innerHTML = `
        <div class="ai-empty">
          <div>${I.sparkle}</div>
          <p>Ask for anything: <em>"make the hero section purple"</em>,
             <em>"add a contact form"</em>, <em>"build a pomodoro timer"</em>.</p>
          <p class="hint">With <b>can edit files</b> on, Claude writes complete files
             you can apply with one click.</p>
        </div>`;
      return;
    }
    box.innerHTML = ws.ai.msgs.map((m, idx) => {
      const files = m.role === "assistant" && !m.streaming ? fileBlocks(m.content) : [];
      const applyAll = files.length > 1
        ? `<div class="ai-bar"><button class="btn sm primary apply-btn" data-all="1">
             Apply all ${files.length} files</button></div>` : "";
      return `<div class="msg ${m.role}" data-idx="${idx}">
        <div class="msg-body">${m.role === "user" ? proseHtml(m.content) : mdHtml(m.content)}
        ${m.streaming ? '<span class="cursor-blink">▌</span>' : ""}</div>${applyAll}</div>`;
    }).join("");
    if (nearBottom || streaming) box.scrollTop = box.scrollHeight;
  }

  async function sendAi() {
    const input = $("#ai-input");
    const text = input.value.trim();
    if (!text || ws.ai.busy) return;
    const P = state.system.providers || {};
    if (!P[ws.ai.provider]?.ready) {
      updateAiNote();
      toast("Add an API key for this model first", "err");
      return;
    }
    input.value = ""; input.style.height = "auto";
    ws.ai.busy = true;
    ws.ai.ctrl = new AbortController();
    const sendBtn = $("#ai-send");
    if (sendBtn) { sendBtn.innerHTML = I.stop; sendBtn.title = "Stop"; }
    ws.ai.msgs.push({ role: "user", content: text });
    const reply = { role: "assistant", content: "", streaming: true };
    ws.ai.msgs.push(reply);
    renderAiMsgs(true);
    await saveAll();

    const history = ws.ai.msgs
      .filter((m) => !m.streaming && m.content.trim())
      .slice(-20)
      .map((m) => ({ role: m.role, content: m.content }));

    let renderQueued = false;
    const queueRender = () => {
      if (renderQueued) return;
      renderQueued = true;
      requestAnimationFrame(() => { renderQueued = false; renderAiMsgs(true); });
    };

    try {
      const resp = await fetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Forge-Client": "1" },
        signal: ws.ai.ctrl.signal,
        body: JSON.stringify({
          messages: history,
          project_id: pid,
          mode: ws.ai.build ? "build" : "chat",
          provider: ws.ai.provider,
          model: ws.ai.model,
          include_paths: currentCtxPaths(),
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw Object.assign(new Error(err.error || `AI request failed (${resp.status})`),
          { code: err.code });
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          let event;
          try { event = JSON.parse(line.slice(5)); } catch { continue; }
          if (event.type === "text") { reply.content += event.text; queueRender(); }
          else if (event.type === "error") {
            reply.content += `\n\n**⚠ ${event.message}**`;
            queueRender();
          }
        }
      }
    } catch (e) {
      if (e.name === "AbortError") reply.content += "\n\n*(stopped)*";
      else reply.content += `\n\n**⚠ ${e.message}**`;
      if (e.code === "no_key") updateAiNote();
    } finally {
      reply.streaming = false;
      ws.ai.busy = false;
      ws.ai.ctrl = null;
      const btn = $("#ai-send");
      if (btn) { btn.innerHTML = I.send; btn.title = "Send"; }
      renderAiMsgs(true);
    }
  }

  async function confirmApply(files) {
    if (!files.length) return;
    const items = [];
    for (const f of files) {
      let current = null, isNew = false;
      const tab = ws.tabs.find((t) => t.path === f.path);
      if (tab?.ed) current = tab.ed.getValue();
      else {
        try {
          const d = await api("GET",
            `/api/projects/${pid}/file?path=${encodeURIComponent(f.path)}`);
          current = d.binary ? null : d.content;
        } catch { isNew = true; }
      }
      items.push({ ...f, current, isNew });
    }
    modal({
      title: items.length > 1 ? `Review ${items.length} files` : `Review ${items[0].path}`,
      wide: true,
      body: (bodyEl) => {
        bodyEl.innerHTML = items.map((it) => {
          const badge = it.isNew
            ? '<span class="prov-chip ok">new file</span>'
            : it.current === it.content
              ? '<span class="prov-chip">unchanged</span>'
              : '<span class="prov-chip warn">modified</span>';
          const body = it.current === it.content
            ? '<p class="hint">Identical to what\'s on disk.</p>'
            : diffHtml(it.isNew ? null : it.current, it.content);
          return `<div class="diff-file">
            <div class="diff-head"><b>${esc(it.path)}</b>${badge}</div>${body}</div>`;
        }).join("");
      },
      actions: [
        { label: "Cancel", kind: "ghost", fn: (close) => close() },
        {
          label: files.length > 1 ? `Apply ${files.length} files` : "Apply",
          kind: "primary",
          fn: async (close) => { close(); await applyFiles(files); },
        },
      ],
    });
  }

  async function applyFiles(files) {
    if (!files.length) return;
    try {
      // Safety net: every AI apply can be undone from Snapshots.
      await api("POST", `/api/projects/${pid}/snapshots`,
        { label: "before AI edit" }).catch(() => {});
      await api("POST", `/api/projects/${pid}/files`, { files });
      toast(`Applied ${files.length} file${files.length > 1 ? "s" : ""}`, "ok");
      for (const f of files) {
        const tab = ws.tabs.find((t) => t.path === f.path);
        if (tab?.ed) {
          tab.ed.setValue(f.content);
          tab.savedValue = f.content;
          tab.dirty = false;
        }
      }
      renderTabs();
      await refreshTree();
      reloadPreview();
    } catch (e) { toast(e.message, "err"); }
  }

  /* ----- snapshots / history ----- */

  async function reloadOpenTabs() {
    for (const tab of [...ws.tabs]) {
      try {
        const d = await api("GET",
          `/api/projects/${pid}/file?path=${encodeURIComponent(tab.path)}`);
        if (tab.ed && !d.binary) {
          tab.ed.setValue(d.content);
          tab.savedValue = d.content;
          tab.dirty = false;
        }
      } catch { closeTab(tab, true); }
    }
    renderTabs();
  }

  async function historyModal() {
    const { snapshots } = await api("GET", `/api/projects/${pid}/snapshots`);
    const m = modal({
      title: "Snapshots",
      body: (bodyEl) => {
        bodyEl.innerHTML = `
          <p class="hint">A snapshot freezes every file in the project.
            One is taken automatically before each AI apply, so anything
            can be undone. The last 20 are kept.</p>
          <div class="row" style="margin-bottom:12px">
            <input class="input" id="snap-label" placeholder="Label (optional)"
                   spellcheck="false">
            <button class="btn primary" id="snap-take">Snapshot now</button>
          </div>
          <div id="snap-list"></div>`;
        const list = $("#snap-list", bodyEl);
        const renderList = (snaps) => {
          list.innerHTML = snaps.length ? "" :
            '<p class="hint">No snapshots yet.</p>';
          for (const s of snaps) {
            const row = el("div", { class: "snap-row" }, `
              <div class="snap-info">
                <b>${esc(s.label || "snapshot")}</b>
                <span class="hint-inline">${timeAgo(s.created)} ·
                  ${s.files} files · ${fmtSize(s.size)}</span>
              </div>
              <button class="btn sm" data-act="restore">Restore</button>
              <button class="btn icon ghost sm" data-act="del" title="Delete">${I.trash}</button>`);
            row.querySelector('[data-act="restore"]').addEventListener("click", async () => {
              if (!await confirmModal("Restore snapshot",
                `Replace all current files with "${s.label || "this snapshot"}" from ${timeAgo(s.created)}? A safety snapshot of the current state is taken first.`,
                { ok: "Restore" })) return;
              try {
                await api("POST", `/api/projects/${pid}/snapshots`,
                  { label: "before restore" });
                await api("POST",
                  `/api/projects/${pid}/snapshots/${s.id}/restore`, {});
                m.close();
                toast("Snapshot restored", "ok");
                await refreshTree();
                await reloadOpenTabs();
                reloadPreview();
              } catch (e) { toast(e.message, "err"); }
            });
            row.querySelector('[data-act="del"]').addEventListener("click", async () => {
              await api("DELETE", `/api/projects/${pid}/snapshots/${s.id}`);
              const fresh = await api("GET", `/api/projects/${pid}/snapshots`);
              renderList(fresh.snapshots);
            });
            list.appendChild(row);
          }
        };
        renderList(snapshots);
        $("#snap-take", bodyEl).addEventListener("click", async () => {
          try {
            await api("POST", `/api/projects/${pid}/snapshots`,
              { label: $("#snap-label", bodyEl).value.trim() });
            $("#snap-label", bodyEl).value = "";
            const fresh = await api("GET", `/api/projects/${pid}/snapshots`);
            renderList(fresh.snapshots);
            toast("Snapshot taken", "ok");
          } catch (e) { toast(e.message, "err"); }
        });
      },
      actions: [{ label: "Close", kind: "ghost", fn: (close) => close() }],
    });
  }

  /* ----- project settings ----- */

  function projectSettingsModal() {
    modal({
      title: "Project settings",
      body: `
        <label class="label">Name</label>
        <input class="input" id="ps-name" value="${esc(ws.meta.name)}" spellcheck="false">
        <label class="label">Run command <span class="hint-inline">what the Run button executes</span></label>
        <input class="input mono" id="ps-run" value="${esc(ws.meta.run || "")}"
               placeholder="python3 -u main.py" spellcheck="false">
        <label class="label">App port <span class="hint-inline">for server apps — the preview connects to it while running</span></label>
        <input class="input mono" id="ps-port" value="${+ws.meta.port || ""}"
               placeholder="8000" spellcheck="false" inputmode="numeric">
        <label class="label">Kind</label>
        <select class="select" id="ps-kind">
          <option value="web"${ws.meta.kind === "web" ? " selected" : ""}>website (leads with preview)</option>
          <option value="console"${ws.meta.kind === "console" ? " selected" : ""}>program (leads with console)</option>
        </select>
        <div class="danger-zone">
          <button class="btn danger ghost" id="ps-delete">${I.trash}<span>Delete project</span></button>
        </div>`,
      actions: [
        { label: "Cancel", kind: "ghost", fn: (close) => close() },
        {
          label: "Save", kind: "primary",
          fn: async (close, box) => {
            try {
              ws.meta = await api("PATCH", `/api/projects/${pid}`, {
                name: $("#ps-name", box).value,
                run: $("#ps-run", box).value,
                kind: $("#ps-kind", box).value,
                port: $("#ps-port", box).value.trim(),
              });
              $("#w-title").textContent = ws.meta.name;
              document.title = `${ws.meta.name} · Forge`;
              if (!+ws.meta.port) ws.previewMode = "files";
              if (ws.right === "preview") renderPreview();
              toast("Saved", "ok");
              close();
            } catch (e) { toast(e.message, "err"); }
          },
        },
      ],
    });
    $("#ps-delete").addEventListener("click", async () => {
      if (await confirmModal("Delete project",
        `"${ws.meta.name}" and all of its files will be deleted. This cannot be undone.`,
        { danger: true, ok: "Delete forever" })) {
        await api("DELETE", `/api/projects/${pid}`);
        nav("/");
      }
    });
  }

  /* ----- resizers ----- */

  function initResize(handle, { key, apply, min, max, from }) {
    const saved = +localStorage.getItem(key);
    if (saved) apply(Math.min(max, Math.max(min, saved)));
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const value = Math.min(max, Math.max(min, from(ev)));
        apply(value);
        localStorage.setItem(key, Math.round(value));
      };
      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
    });
  }

  const body = $(".ws-body"), main = $("#w-main");
  initResize($("#rz-side"), {
    key: "forge.side", min: 160, max: 420,
    from: (e) => e.clientX,
    apply: (v) => body.style.setProperty("--side", `${v}px`),
  });
  initResize($("#rz-right"), {
    key: "forge.right", min: 280, max: innerWidth * 0.65,
    from: (e) => innerWidth - e.clientX,
    apply: (v) => body.style.setProperty("--right", `${v}px`),
  });
  initResize($("#rz-console"), {
    key: "forge.console", min: 80, max: innerHeight * 0.6,
    from: (e) => {
      const rect = main.getBoundingClientRect();
      return rect.bottom - e.clientY;
    },
    apply: (v) => main.style.setProperty("--console", `${v}px`),
  });

  /* ----- top bar wiring ----- */

  $("#w-back").addEventListener("click", () => nav("/"));
  $("#w-title").addEventListener("click", async () => {
    const name = await promptModal("Rename project", { value: ws.meta.name, ok: "Rename" });
    if (!name) return;
    ws.meta = await api("PATCH", `/api/projects/${pid}`, { name });
    $("#w-title").textContent = ws.meta.name;
    document.title = `${ws.meta.name} · Forge`;
  });
  $("#w-run").addEventListener("click", runOrStop);
  $("#w-console").addEventListener("click", () => showConsole());
  $("#w-history").addEventListener("click", historyModal);
  $("#w-export").addEventListener("click", () => {
    location.href = `/api/projects/${pid}/export`;
  });
  $("#w-settings").addEventListener("click", projectSettingsModal);
  $("#t-newfile").addEventListener("click", () => newFile());
  $("#t-newdir").addEventListener("click", () => newFolder());
  $("#t-upload").addEventListener("click", () => $("#w-file-input").click());
  $("#w-file-input").addEventListener("change", (e) => {
    if (e.target.files.length) uploadFiles([...e.target.files]);
    e.target.value = "";
  });
  const searchIn = $("#w-search");
  const runSearch = debounce(async () => {
    const q = searchIn.value.trim();
    if (q.length < 2) { renderTree(); return; }
    let res;
    try {
      res = await api("GET",
        `/api/projects/${pid}/search?q=${encodeURIComponent(q)}`);
    } catch { return; }
    if (searchIn.value.trim() !== q) return;  // stale response
    treeEl.innerHTML = "";
    if (!res.results.length) {
      treeEl.innerHTML = `<div class="tree-empty">No matches for “${esc(q)}”.</div>`;
      return;
    }
    let lastPath = null;
    for (const r of res.results) {
      if (r.path !== lastPath) {
        lastPath = r.path;
        treeEl.appendChild(el("div", { class: "sr-file" },
          `${fileIcon(r.path)}<span>${esc(r.path)}</span>`));
      }
      const row = el("div", { class: "sr-hit", title: `${r.path}:${r.line}` },
        `<span class="sr-ln">${r.line}</span><span class="sr-text">${esc(r.text)}</span>`);
      row.addEventListener("click", async () => {
        await openFile(r.path);
        ws.active?.ed?.revealLine(r.line);
      });
      treeEl.appendChild(row);
    }
    if (res.truncated) {
      treeEl.appendChild(el("div", { class: "tree-empty" }, "…more matches not shown"));
    }
  }, 250);
  searchIn.addEventListener("input", () => {
    if (searchIn.value.trim().length < 2) renderTree();
    else runSearch();
  });
  searchIn.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { searchIn.value = ""; renderTree(); searchIn.blur(); }
  });

  const sideEl = $("#w-side");
  ["dragenter", "dragover"].forEach((type) => sideEl.addEventListener(type, (e) => {
    if ([...(e.dataTransfer?.types || [])].includes("Files")) {
      e.preventDefault();
      sideEl.classList.add("drop");
    }
  }));
  sideEl.addEventListener("dragleave", (e) => {
    if (!sideEl.contains(e.relatedTarget)) sideEl.classList.remove("drop");
  });
  sideEl.addEventListener("drop", (e) => {
    e.preventDefault();
    sideEl.classList.remove("drop");
    const files = [...(e.dataTransfer?.files || [])];
    if (files.length) uploadFiles(files);
  });
  $("#c-clear").addEventListener("click", () => { cBody.innerHTML = ""; cLast = null; });
  $("#c-input").addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const text = e.target.value;
    e.target.value = "";
    cAppend("in", text + "\n");
    try { await api("POST", `/api/projects/${pid}/run/input`, { text }); }
    catch (err) { toast(err.message, "err"); }
  });
  $$(".seg-btn").forEach((b) =>
    b.addEventListener("click", () => setRight(b.dataset.pane)));

  /* mobile pane nav */
  $$("#w-mnav button").forEach((b) => b.addEventListener("click", () => {
    $$("#w-mnav button").forEach((x) => x.classList.toggle("active", x === b));
    const pane = b.dataset.pane;
    $(".ws").dataset.pane = pane;
    if (pane === "preview") setRight("preview");
    if (pane === "ai") setRight("ai");
  }));

  const onKey = (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveTab(ws.active); }
    if (mod && e.key === "Enter") { e.preventDefault(); runOrStop(); }
  };
  document.addEventListener("keydown", onKey);
  const onUnload = (e) => {
    if (ws.tabs.some((t) => t.dirty)) { e.preventDefault(); e.returnValue = ""; }
  };
  addEventListener("beforeunload", onUnload);

  // Console/debug handles (also used by tooling screenshots).
  ws.renderAiMsgs = renderAiMsgs;
  ws.confirmApply = confirmApply;

  ws.cleanups.push(
    () => ws.es?.close(),
    () => ws.tabs.forEach((t) => t.ed?.destroy()),
    () => document.removeEventListener("keydown", onKey),
    () => removeEventListener("beforeunload", onUnload),
  );

  /* ----- go ----- */

  await refreshTree();
  setRight(ws.right);
  attachStream();  // reattach to a run that survived a reload
  const entry = ws.meta.entry && ws.tree.some((e2) => e2.path === ws.meta.entry)
    ? ws.meta.entry
    : ws.tree.find((e2) => e2.type === "file")?.path;
  if (entry) await openFile(entry);
  if (ws.meta.kind === "web") showConsole(false);
}

/* ================================================================= boot */

addEventListener("popstate", route);
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
route();
