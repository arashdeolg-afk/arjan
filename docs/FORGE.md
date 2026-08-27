# Forge — build websites & apps in your browser

Forge is this repo's second app: a self-hosted, Replit-style builder.
Open it in a browser and you get a project dashboard, a real code editor
with syntax highlighting, a live-reloading preview for websites, a
streaming console for programs (with stdin), one-click zip export, and
an AI pane that pairs with Claude to write project files for you.

Like everything in this repo it is **pure Python 3.11 stdlib** — no npm,
no pip, no build step — and **local-first**: every project you create
lives in `data/forge/` on your machine, which is gitignored.

```bash
PYTHONPATH=src python3 -m forge demo     # seed three sample projects
PYTHONPATH=src python3 -m forge          # serve on http://127.0.0.1:8484
PYTHONPATH=src python3 -m forge serve --port 9000 --open
```

---

## What you can build with it

| Template | What it is | Workflow |
|---|---|---|
| **Website** | HTML/CSS/JS landing-page starter | Edit → autosave → the preview pane live-reloads |
| **Python app** | Terminal program starter | Run → output streams to the console; the input box feeds `input()` |
| **Browser game** | Canvas breakout starter | Runs right in the preview pane |
| **Blank** | Empty project | Bring your own files, or let the AI scaffold them |

Projects are plain directories under `data/forge/projects/<id>/` — open
them in any other editor, or **Export zip** to ship them anywhere.

## The AI pane (Claude)

The assistant is off until a key exists. Two ways to provide one:

1. `export ANTHROPIC_API_KEY=sk-ant-…` before starting forge, or
2. paste it into **Settings → Claude** in the app; it is saved to
   `data/forge/settings.json` (gitignored, chmod 600) and never leaves
   your machine except in requests to `api.anthropic.com`.

With **can edit files** on, Claude answers in *build mode*: every file it
creates or changes arrives as a complete `file:` block with an **Apply**
button (or **Apply all**), which writes it into the project and refreshes
the preview. Model picker offers Claude Opus 5 (default), Sonnet 5 and
Haiku 4.5. Requests stream token-by-token; on Opus the server-side
refusal-fallback option is enabled so a safety refusal degrades
gracefully instead of returning an empty turn.

The integration is raw HTTPS via `urllib` (stdlib-only repo — the
official SDK would be a dependency).

## How it's put together

```
src/forge/
  server.py     threaded http.server: JSON API, SSE streams, preview, static app
  store.py      projects on disk, path-jailed file ops, zip export, settings
  runner.py     subprocess runner: streamed out/err events, stdin, stop, timeout
  ai.py         Claude Messages API client (streaming) + file-block parser
  templates.py  starter templates + demo seeds
  web/          the frontend: vanilla JS/CSS, no build step
    app.js        dashboard + workspace (tabs, tree, console, AI pane)
    editor.js     ForgeEditor: overlay editor with regex tokenizers
    live.js       injected into previews for live reload
tests/test_forge_*.py
```

Design notes worth keeping in mind when changing it:

- **Every network-supplied path goes through `Store.resolve`**, which
  rejects `..`, absolute escapes, `.forge.json`, and symlink tricks. If
  you add an endpoint that touches files, go through it.
- **Run output is a numbered event log** (`start`/`out`/`err`/`exit`).
  SSE ids are the sequence numbers, so a dropped connection resumes via
  `Last-Event-ID` and a page reload replays the whole run.
- **Two request guards** protect even a localhost tool: the Host header
  must be local (DNS-rebinding), and every mutating `/api` call must
  carry `X-Forge-Client` (a custom header forces a CORS preflight that
  the server never grants, so other websites can't drive your forge).
- The preview server injects `live.js` into HTML it serves; the script
  polls the project's version counter and reloads on change.

## Security honestly stated

Forge runs code you put in it, as you, on your machine — same trust
model as an IDE terminal. It binds `127.0.0.1` by default; `--host
0.0.0.0` exposes it to your network **with no authentication**, so only
do that on networks you trust.

## Roadmap

- **Mobile:** the app is responsive and installable (PWA manifest +
  service worker) today; a dedicated mobile app can reuse the JSON+SSE
  API as-is.
- Webview proxy for projects that run their own server (Flask etc.).
- AI: multi-file context selection, diff view before apply.
