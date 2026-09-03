"""The forge web server: JSON API + static app + preview + SSE streams.

Built on http.server (threaded) because this repo is stdlib-only. Two
defenses matter even for a localhost tool:

- Host-header check: requests must address localhost (or the host forge
  was explicitly bound to), which blocks DNS-rebinding tricks.
- Custom-header check: every state-changing /api call must carry an
  ``X-Forge-Client`` header. Browsers won't attach custom headers
  cross-origin without a CORS preflight (which this server never
  grants), so random websites can't POST to your local forge.
"""

from __future__ import annotations

import http.client
import json
import mimetypes
import re
import socket
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ai
from .runner import Runner, RunnerError
from .store import Store, StoreError

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 25 * 1024 * 1024
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
# Not forwarded in either direction by the app proxy.
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length", "accept-encoding",
}

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def _routes() -> list[tuple[str, re.Pattern, str]]:
    pid = r"([a-z0-9][a-z0-9-]{0,63})"
    table = [
        ("GET", r"^/api/health$", "health"),
        ("GET", r"^/api/system$", "system"),
        ("GET", r"^/api/settings$", "settings_get"),
        ("POST", r"^/api/settings$", "settings_post"),
        ("GET", r"^/api/templates$", "templates_get"),
        ("GET", r"^/api/projects$", "projects_list"),
        ("POST", r"^/api/projects$", "projects_create"),
        ("GET", rf"^/api/projects/{pid}$", "project_get"),
        ("PATCH", rf"^/api/projects/{pid}$", "project_patch"),
        ("DELETE", rf"^/api/projects/{pid}$", "project_delete"),
        ("POST", rf"^/api/projects/{pid}/duplicate$", "project_duplicate"),
        ("GET", rf"^/api/projects/{pid}/tree$", "tree_get"),
        ("GET", rf"^/api/projects/{pid}/file$", "file_get"),
        ("PUT", rf"^/api/projects/{pid}/file$", "file_put"),
        ("DELETE", rf"^/api/projects/{pid}/file$", "file_delete"),
        ("POST", rf"^/api/projects/{pid}/files$", "files_batch"),
        ("POST", rf"^/api/projects/{pid}/folder$", "folder_post"),
        ("POST", rf"^/api/projects/{pid}/move$", "move_post"),
        ("GET", rf"^/api/projects/{pid}/search$", "search_get"),
        ("GET", rf"^/api/projects/{pid}/snapshots$", "snaps_list"),
        ("POST", rf"^/api/projects/{pid}/snapshots$", "snaps_create"),
        ("POST", rf"^/api/projects/{pid}/snapshots/([\w-]+)/restore$", "snaps_restore"),
        ("DELETE", rf"^/api/projects/{pid}/snapshots/([\w-]+)$", "snaps_delete"),
        ("GET", rf"^/api/projects/{pid}/export$", "export_get"),
        ("GET", rf"^/api/projects/{pid}/version$", "version_get"),
        ("POST", rf"^/api/projects/{pid}/run$", "run_start"),
        ("GET", rf"^/api/projects/{pid}/run/stream$", "run_stream"),
        ("GET", rf"^/api/projects/{pid}/run/state$", "run_state"),
        ("POST", rf"^/api/projects/{pid}/run/input$", "run_input"),
        ("POST", rf"^/api/projects/{pid}/run/stop$", "run_stop"),
        ("POST", r"^/api/ai/chat$", "ai_chat"),
    ]
    return [(m, re.compile(p), name) for m, p, name in table]


ROUTES = _routes()


class ForgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "forge"

    # ------------------------------------------------------------- plumbing

    def log_message(self, fmt, *args):  # quiet: errors surface as JSON
        pass

    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    @property
    def runner(self) -> Runner:
        return self.server.runner  # type: ignore[attr-defined]

    def _send(self, status: int, ctype: str, body: bytes,
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _json(self, obj, status: int = 200, extra: dict | None = None) -> None:
        body = json.dumps(obj).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body, extra)

    def _error(self, message: str, status: int, code: str | None = None) -> None:
        # An early rejection may leave a request body unread on the socket,
        # which would corrupt keep-alive parsing — so close after errors.
        self.close_connection = True
        payload = {"error": message}
        if code:
            payload["code"] = code
        self._json(payload, status)

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError("request too large", 413)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError("body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("body must be a JSON object")
        return data

    def _host_ok(self) -> bool:
        if getattr(self.server, "allow_any_host", False):
            return True
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):  # [::1]:port
            name = host.split("]")[0] + "]"
        else:
            name = host.rsplit(":", 1)[0] if ":" in host else host
        return name.lower() in LOCAL_HOSTS

    # ------------------------------------------------------------- dispatch

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        try:
            if not self._host_ok():
                return self._error("host not allowed (DNS-rebinding guard)", 403)
            split = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(split.path)
            query = urllib.parse.parse_qs(split.query)

            if path.startswith("/proxy/"):
                return self._proxy(method, path, split.query)

            if path.startswith("/api/"):
                if method != "GET" and self.headers.get("X-Forge-Client") is None:
                    return self._error(
                        "missing X-Forge-Client header (CSRF guard)", 403)
                for m, pattern, name in ROUTES:
                    match = pattern.match(path)
                    if match:
                        if m != method:
                            continue
                        getattr(self, f"h_{name}")(match, query)
                        return
                return self._error("not found", 404)

            if method != "GET":
                return self._error("not found", 404)
            self._static(path)
        except (StoreError, RunnerError, ai.AIError) as e:
            self._error(str(e), e.status)
        except ApiError as e:
            self._error(str(e), e.status, e.code)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:  # last resort: never hang the connection
            traceback.print_exc(file=sys.stderr)
            try:
                self._error(f"internal error: {e}", 500)
            except Exception:
                self.close_connection = True

    # ---------------------------------------------------------------- pages

    def _static(self, path: str) -> None:
        if path.startswith("/p/"):
            return self._preview(path)
        if path == "/__forge/live.js":
            return self._file_from_web("live.js")
        if path.startswith("/assets/"):
            return self._file_from_web(path[len("/assets/"):])
        if path in ("/manifest.webmanifest", "/sw.js", "/icon.svg",
                    "/icon-180.png", "/icon-512.png", "/offline.html"):
            return self._file_from_web(path.lstrip("/"))
        if path in ("/favicon.ico", "/favicon.svg"):
            return self._file_from_web("icon.svg")
        if path == "/apple-touch-icon.png":  # iOS requests this by convention
            return self._file_from_web("icon-180.png")
        # Anything else is an app route: serve the single-page app.
        self._file_from_web("index.html")

    def _file_from_web(self, rel: str) -> None:
        base = WEB_DIR.resolve()
        target = (base / rel).resolve()
        if base != target and base not in target.parents:
            return self._error("not found", 404)
        if not target.is_file():
            return self._error("not found", 404)
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/manifest+json",):
            mime += "; charset=utf-8"
        self._send(200, mime, target.read_bytes())

    def _preview(self, path: str) -> None:
        parts = path[len("/p/"):].split("/", 1)
        pid = parts[0]
        rel = parts[1] if len(parts) > 1 else ""
        try:
            target = self.store.resolve(pid, rel, allow_root=True)
        except StoreError as e:
            if e.status == 404:
                return self._preview_404(pid, rel)
            raise
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self._preview_404(pid, rel)
        data = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime == "text/html":
            tag = b'<script src="/__forge/live.js" defer></script>'
            low = data.lower()
            idx = low.rfind(b"</body>")
            data = data[:idx] + tag + data[idx:] if idx != -1 else data + tag
        if mime.startswith("text/"):
            mime += "; charset=utf-8"
        self._send(200, mime, data)

    def _proxy(self, method: str, path: str, rawquery: str) -> None:
        """Forward a request to the user app listening on the project's port.

        Lets the preview pane show live server apps, not just static files.
        Only ever connects to 127.0.0.1 on the port stored in project
        metadata (validated 1024-65535 by the store).
        """
        parts = path[len("/proxy/"):].split("/", 1)
        pid = parts[0]
        target = "/" + (parts[1] if len(parts) > 1 else "")
        meta = self.store.get_meta(pid)  # 404 for unknown projects
        port = int(meta.get("port") or 0)
        if not port:
            return self._proxy_wait(pid, 0)
        if rawquery:
            target += "?" + rawquery

        if "upgrade" in (self.headers.get("Connection") or "").lower() and \
                (self.headers.get("Upgrade") or "").lower() == "websocket":
            return self._proxy_websocket(method, target, port)

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError("request too large", 413)
        body = self.rfile.read(length) if length else None

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_HEADERS}
        headers["Host"] = f"127.0.0.1:{port}"
        headers["Accept-Encoding"] = "identity"
        if body is not None:
            headers["Content-Length"] = str(len(body))

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request(method, target, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except (ConnectionError, TimeoutError, OSError):
            return self._proxy_wait(pid, port)
        finally:
            conn.close()

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            lk = k.lower()
            if lk in HOP_HEADERS:
                continue
            if lk == "location" and v.startswith("/") and not v.startswith("//"):
                v = f"/proxy/{pid}" + v
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _proxy_websocket(self, method: str, target: str, port: int) -> None:
        """Relay a WebSocket upgrade, then splice bytes in both directions.

        After the 101 handshake a WebSocket is just a byte stream, so no
        frame parsing is needed — two pumps and the browser talks straight
        to the user's app.
        """
        try:
            backend = socket.create_connection(("127.0.0.1", port), timeout=10)
        except OSError:
            return self._proxy_wait("", port)

        lines = [f"{method} {target} HTTP/1.1"]
        for key, value in self.headers.items():
            if key.lower() == "host":
                value = f"127.0.0.1:{port}"
            lines.append(f"{key}: {value}")
        try:
            backend.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))

            head = b""
            while b"\r\n\r\n" not in head and len(head) < 65536:
                chunk = backend.recv(4096)
                if not chunk:
                    break
                head += chunk
            self.close_connection = True
            if b" 101 " not in head.split(b"\r\n", 1)[0] + b" ":
                # The app declined the upgrade — pass its answer through.
                self.wfile.write(head)
                backend.close()
                return
            self.wfile.write(head)  # includes any early frames after \r\n\r\n
            self.wfile.flush()

            backend.settimeout(None)
            self.connection.settimeout(None)

            def pump_client_to_backend():
                try:
                    while True:
                        data = self.rfile.read1(4096)
                        if not data:
                            break
                        backend.sendall(data)
                except OSError:
                    pass
                try:
                    backend.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

            pump = threading.Thread(target=pump_client_to_backend, daemon=True)
            pump.start()
            try:
                while True:
                    data = backend.recv(4096)
                    if not data:
                        break
                    self.wfile.write(data)
                    self.wfile.flush()
            except OSError:
                pass
        finally:
            try:
                backend.close()
            except OSError:
                pass

    def _proxy_wait(self, pid: str, port: int) -> None:
        if port:
            hint = (f"Waiting for your app on port {port}…<br>"
                    "start it with the <b>Run</b> button.")
            retry = "<meta http-equiv='refresh' content='1.5'>"
        else:
            hint = ("This project has no app port set.<br>"
                    "Add one in project settings to preview a server app.")
            retry = ""
        page = (
            f"<!DOCTYPE html><meta charset='utf-8'>{retry}"
            "<body style='background:#0b0e13;color:#9aa7b8;font-family:system-ui;"
            "display:grid;place-items:center;height:100vh;margin:0'>"
            f"<div style='text-align:center;line-height:1.7'>"
            f"<div style='font-size:34px'>⏳</div><p>{hint}</p></div></body>"
        )
        self._send(502, "text/html; charset=utf-8", page.encode("utf-8"))

    def _preview_404(self, pid: str, rel: str) -> None:
        page = (
            "<!DOCTYPE html><meta charset='utf-8'>"
            "<body style='background:#0b0e13;color:#9aa7b8;font-family:system-ui;"
            "display:grid;place-items:center;height:100vh;margin:0'>"
            f"<div style='text-align:center'><div style='font-size:42px'>404</div>"
            f"<p>{'/' + rel if rel else 'index.html'} not found in this project</p>"
            "</div></body>"
        )
        self._send(404, "text/html; charset=utf-8", page.encode("utf-8"))

    # ------------------------------------------------------------------ SSE

    def _sse_begin(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, data: dict, event: str | None = None,
             eid: int | None = None) -> bool:
        try:
            lines = []
            if eid is not None:
                lines.append(f"id: {eid}")
            if event:
                lines.append(f"event: {event}")
            lines.append("data: " + json.dumps(data))
            self.wfile.write(("\n".join(lines) + "\n\n").encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _sse_ping(self) -> bool:
        try:
            self.wfile.write(b": ping\n\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    # ------------------------------------------------------------- handlers

    def h_health(self, match, query):
        self._json({"ok": True})

    def h_system(self, match, query):
        import shutil as _shutil
        from . import __version__
        settings = self.store.get_settings()
        providers = ai.provider_status(settings)
        sel_provider, sel_model = ai.default_selection(settings)
        self._json({
            "version": __version__,
            "python": sys.version.split()[0],
            "node": _shutil.which("node") is not None,
            "models": ai.MODELS,
            "default_model": sel_model,
            "providers": providers,
            "ai": {"provider": sel_provider, "model": sel_model},
            "ai_ready": any(p["ready"] for p in providers.values()),
            "ai_source": providers["anthropic"]["source"],
        })

    def h_settings_get(self, match, query):
        settings = self.store.get_settings()
        providers = ai.provider_status(settings)
        sel_provider, sel_model = ai.default_selection(settings)
        anthropic = providers["anthropic"]
        self._json({
            # Legacy flat fields (anthropic view) plus the provider map.
            "model": ai.default_model_for(settings, "anthropic"),
            "ai_ready": any(p["ready"] for p in providers.values()),
            "ai_source": anthropic["source"],
            "key_masked": anthropic["key_masked"],
            "providers": providers,
            "ai": {"provider": sel_provider, "model": sel_model},
        })

    def h_settings_post(self, match, query):
        body = self._body_json()
        settings = self.store.get_settings()
        patch: dict = {}

        if "anthropic_api_key" in body:  # legacy shape, kept working
            value = body["anthropic_api_key"]
            if value is not None and not isinstance(value, str):
                raise ApiError("anthropic_api_key must be a string")
            patch["anthropic_api_key"] = (value or "").strip()
        if "model" in body:
            value = body["model"]
            if value and value not in [m["id"] for m in ai.MODELS]:
                raise ApiError("unknown model")
            patch["model"] = value

        if "providers" in body:
            incoming = body["providers"]
            if not isinstance(incoming, dict):
                raise ApiError("providers must be an object")
            merged = dict(settings.get("providers") or {})
            for pid, conf in incoming.items():
                if pid not in ai.PROVIDERS:
                    raise ApiError(f"unknown provider: {pid}")
                if not isinstance(conf, dict):
                    raise ApiError("provider settings must be an object")
                current = dict(merged.get(pid) or {})
                for field in ("api_key", "base_url", "model"):
                    if field not in conf:
                        continue
                    value = conf[field]
                    if value is not None and not isinstance(value, str):
                        raise ApiError(f"{pid}.{field} must be a string")
                    value = (value or "").strip()
                    if field == "base_url" and value and \
                            not value.startswith(("http://", "https://")):
                        raise ApiError("base_url must start with http(s)://")
                    if value:
                        current[field] = value
                    else:
                        current.pop(field, None)
                if current:
                    merged[pid] = current
                else:
                    merged.pop(pid, None)
            patch["providers"] = merged or None

        if "ai" in body:
            selection = body["ai"]
            if not isinstance(selection, dict):
                raise ApiError("ai must be an object")
            provider = selection.get("provider") or "anthropic"
            if provider not in ai.PROVIDERS:
                raise ApiError(f"unknown provider: {provider}")
            patch["ai"] = {"provider": provider,
                           "model": str(selection.get("model") or "").strip()}

        self.store.update_settings(patch)
        self.h_settings_get(match, query)

    def h_templates_get(self, match, query):
        from . import templates
        self._json({"templates": templates.public_list()})

    def h_projects_list(self, match, query):
        self._json({"projects": self.store.list_projects()})

    def h_projects_create(self, match, query):
        body = self._body_json()
        meta = self.store.create(body.get("name", ""), body.get("template", "blank"))
        self._json(meta, 201)

    def h_project_get(self, match, query):
        self._json(self.store.get_meta(match.group(1)))

    def h_project_patch(self, match, query):
        self._json(self.store.update_meta(match.group(1), self._body_json()))

    def h_project_delete(self, match, query):
        pid = match.group(1)
        self.runner.stop(pid)
        self.store.delete_project(pid)
        self._json({"ok": True})

    def h_project_duplicate(self, match, query):
        body = self._body_json()
        self._json(self.store.duplicate(match.group(1), body.get("name")), 201)

    def h_tree_get(self, match, query):
        self._json({"tree": self.store.tree(match.group(1))})

    def _qpath(self, query) -> str:
        path = (query.get("path") or [""])[0]
        if not path:
            raise ApiError("path query parameter is required")
        return path

    def h_file_get(self, match, query):
        self._json(self.store.read_file(match.group(1), self._qpath(query)))

    def h_file_put(self, match, query):
        body = self._body_json()
        result = self.store.write_file(
            match.group(1), self._qpath(query),
            body.get("content"), body.get("content_b64"))
        self._json(result)

    def h_file_delete(self, match, query):
        self.store.delete_path(match.group(1), self._qpath(query))
        self._json({"ok": True})

    def h_files_batch(self, match, query):
        body = self._body_json()
        written = self.store.batch_write(match.group(1), body.get("files"))
        self._json({"written": written})

    def h_folder_post(self, match, query):
        body = self._body_json()
        self._json(self.store.mkdir(match.group(1), body.get("path", "")), 201)

    def h_move_post(self, match, query):
        body = self._body_json()
        result = self.store.move(
            match.group(1), body.get("src", ""), body.get("dst", ""))
        self._json(result)

    def h_snaps_list(self, match, query):
        self._json({"snapshots": self.store.list_snapshots(match.group(1))})

    def h_snaps_create(self, match, query):
        body = self._body_json()
        self._json(self.store.snapshot(match.group(1),
                                       body.get("label", "")), 201)

    def h_snaps_restore(self, match, query):
        self._json(self.store.restore_snapshot(match.group(1), match.group(2)))

    def h_snaps_delete(self, match, query):
        self.store.delete_snapshot(match.group(1), match.group(2))
        self._json({"ok": True})

    def h_search_get(self, match, query):
        q = (query.get("q") or [""])[0]
        self._json(self.store.search(match.group(1), q))

    def h_export_get(self, match, query):
        pid = match.group(1)
        data = self.store.export_zip(pid)
        self._send(200, "application/zip", data, {
            "Content-Disposition": f'attachment; filename="{pid}.zip"',
        })

    def h_version_get(self, match, query):
        self._json({"version": self.store.version(match.group(1))})

    # ----------------------------------------------------------------- runs

    def h_run_start(self, match, query):
        pid = match.group(1)
        meta = self.store.get_meta(pid)
        body = self._body_json()
        command = body.get("command") or meta.get("run") or ""
        pdir = self.store.resolve(pid, "", allow_root=True)
        run = self.runner.start(pid, command, str(pdir),
                                timeout=body.get("timeout"))
        self._json({"ok": True, "pid": run.proc.pid, "command": command}, 201)

    def h_run_state(self, match, query):
        run = self.runner.get(match.group(1))
        if run is None:
            self._json({"running": False, "returncode": None, "started": None})
        else:
            self._json(run.state())

    def h_run_input(self, match, query):
        run = self.runner.get(match.group(1))
        if run is None:
            raise ApiError("nothing is running", 409)
        body = self._body_json()
        text = body.get("text", "")
        if body.get("newline", True) and not text.endswith("\n"):
            text += "\n"
        run.write_input(text)
        self._json({"ok": True})

    def h_run_stop(self, match, query):
        stopped = self.runner.stop(match.group(1))
        self._json({"ok": True, "stopped": stopped})

    def h_run_stream(self, match, query):
        self.store.get_meta(match.group(1))  # 404 for unknown projects
        run = self.runner.get(match.group(1))
        self._sse_begin()
        if run is None:
            self._sse({}, event="none")
            return
        try:
            last = int(self.headers.get("Last-Event-ID", "-1"))
        except ValueError:
            last = -1
        while True:
            events, done = run.events_since(last, wait=15.0)
            if not events:
                if done:
                    return
                if not self._sse_ping():
                    return
                continue
            for event in events:
                last = event["seq"]
                if not self._sse(event["data"], event=event["kind"],
                                 eid=event["seq"]):
                    return

    # ------------------------------------------------------------------- AI

    def h_ai_chat(self, match, query):
        body = self._body_json()
        settings = self.store.get_settings()
        provider = body.get("provider") or ai.default_selection(settings)[0]
        if provider not in ai.PROVIDERS:
            raise ApiError(f"unknown provider: {provider}")
        if not ai.provider_ready(settings, provider):
            label = ai.PROVIDERS[provider]["label"]
            what = ("a base URL" if provider == "compat" else "an API key")
            raise ApiError(
                f"No {what} for {label} yet — add one in Settings to use it.",
                400, code="no_key")

        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ApiError("messages must be a non-empty list")
        clean = []
        for m in messages:
            role = m.get("role") if isinstance(m, dict) else None
            content = m.get("content") if isinstance(m, dict) else None
            if role not in ("user", "assistant") or not isinstance(content, str):
                raise ApiError("each message needs role user|assistant and "
                               "string content")
            if content.strip():
                clean.append({"role": role, "content": content})
        if not clean:
            raise ApiError("messages are empty")

        mode = body.get("mode") or "build"
        model = body.get("model") or ai.default_model_for(settings, provider)
        if not model:
            raise ApiError("set a model for this provider in Settings")
        meta = None
        tree_paths: list[str] = []
        files: list[tuple[str, str]] = []
        pid = body.get("project_id")
        if pid:
            meta = self.store.get_meta(pid)
            tree_paths = [e["path"] for e in self.store.tree(pid)
                          if e["type"] == "file"]
            for rel in (body.get("include_paths") or [])[:8]:
                try:
                    f = self.store.read_file(pid, rel)
                except StoreError:
                    continue
                if not f["binary"]:
                    files.append((rel, f["content"]))

        system = ai.build_system(mode, meta, tree_paths, files)
        transport = getattr(self.server, "ai_transport", None)

        self._sse_begin()
        try:
            for event in ai.chat(provider, model, system, clean, settings,
                                 transport, body.get("max_tokens")):
                if not self._sse(event):
                    return
        except ai.AIError as e:
            self._sse({"type": "error", "message": str(e)})


def make_server(host: str, port: int, store: Store, runner: Runner,
                ai_transport=None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), ForgeHandler)
    httpd.daemon_threads = True
    httpd.store = store  # type: ignore[attr-defined]
    httpd.runner = runner  # type: ignore[attr-defined]
    httpd.ai_transport = ai_transport  # type: ignore[attr-defined]
    httpd.allow_any_host = host not in ("127.0.0.1", "localhost", "::1")  # type: ignore[attr-defined]
    return httpd
