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
| **Web server** | Python server + page in one project | Run → the preview connects to your live server through the app proxy |
| **Browser game** | Canvas breakout starter | Runs right in the preview pane |
| **Blank** | Empty project | Bring your own files, or let the AI scaffold them |

Projects are plain directories under `data/forge/projects/<id>/` — open
them in any other editor, or **Export zip** to ship them anywhere.

## Snapshots (time travel)

The clock button freezes the whole project into a snapshot (a zip under
`data/forge/snapshots/`, last 20 kept). One is taken automatically
before every AI apply and before every restore, so **any AI edit — and
any restore — can be undone**. Restoring validates every zip entry
through the path jail first, then replaces the project's files while
leaving its settings untouched. No git required; it works anywhere
Python runs.

## Server apps and the proxy

A project with an **app port** set (project settings; the Web server
template ships with 8000) gets a second preview mode: `App :<port>`.
While the project is running, `/proxy/<id>/…` forwards requests to
`127.0.0.1:<port>` — so the preview pane shows the app your own process
is serving, not static files. Absolute `Location:` redirects are
rewritten to stay inside the proxy; until the server is up, the pane
shows a waiting page that retries by itself. One rule for proxied apps:
use **relative** URLs (`api/hello`, not `/api/hello`) in pages, since
the app is mounted under `/proxy/<id>/`.

## The AI pane (bring your own keys)

The assistant is off until at least one provider has credentials — add
them whenever you're ready, in **Settings → AI models** or via
environment variables. Four providers are wired in:

| Provider | Key | Models |
|---|---|---|
| **Claude (Anthropic)** — default | `ANTHROPIC_API_KEY` or Settings | Curated picker: Opus 5 (default), Sonnet 5, Haiku 4.5 |
| **OpenAI** | `OPENAI_API_KEY` or Settings | Free-text model id (e.g. `gpt-4o`) |
| **Google Gemini** | `GEMINI_API_KEY` or Settings | Free-text model id (e.g. `gemini-2.0-flash`) |
| **OpenAI-compatible** | Base URL (+ optional key) | Ollama, OpenRouter, Groq… free-text model id |

Non-Anthropic model ids are free text on purpose: when a provider ships
a new model, you type its id — no forge release needed. Keys are saved
to `data/forge/settings.json` (gitignored, chmod 600) and leave the
machine only in requests to the provider you selected. Environment
variables always override saved keys.

With **can edit files** on, the model answers in *build mode*: every
file it creates or changes arrives as a complete `file:` block. **Apply**
opens a review dialog first — a per-file line diff (new files shown as
all-additions) — so nothing touches the project until you've seen the
change. The **context** button picks which files the model can read
(up to 8; defaults to the file you're editing). Everything streams
token-by-token, with a stop button mid-generation; on Claude Opus the
server-side refusal-fallback option is enabled so a safety refusal
degrades gracefully instead of returning an empty turn.

All integrations are raw HTTPS via `urllib` (stdlib-only repo — vendor
SDKs would be dependencies).

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
- Proxy: WebSocket passthrough for apps that use them.
- Optional git integration on top of snapshots, for users who want
  real branches and remotes.
