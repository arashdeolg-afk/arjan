"""HTTP API tests against a real threaded server on an ephemeral port."""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forge.runner import Runner        # noqa: E402
from forge.server import make_server   # noqa: E402
from forge.store import Store          # noqa: E402


def fake_ai_transport(url, headers, body):
    """Pretend to be the Anthropic API: stream two deltas and stop."""
    events = [
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hello from "}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "fake Claude"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 4}},
        {"type": "message_stop"},
    ]
    lines = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}\n".encode())
        lines.append(b"\n")
    return lines


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The AI endpoints must see a clean environment, not a real key.
        cls._saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(cls.tmp.name)
        cls.runner = Runner()
        cls.httpd = make_server("127.0.0.1", 0, cls.store, cls.runner,
                                ai_transport=fake_ai_transport)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.runner.stop_all()
        cls.tmp.cleanup()
        if cls._saved_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = cls._saved_key

    # ------------------------------------------------------------- helpers

    def request(self, method, path, body=None, headers=None, host=None,
                csrf=True, timeout=10):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            send_headers = dict(headers or {})
            if host:
                send_headers["Host"] = host
            if csrf and method != "GET":
                send_headers.setdefault("X-Forge-Client", "1")
            payload = None
            if body is not None:
                payload = json.dumps(body).encode()
                send_headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=send_headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, dict(resp.getheaders()), raw
        finally:
            conn.close()

    def json_request(self, method, path, body=None, **kw):
        status, headers, raw = self.request(method, path, body, **kw)
        return status, json.loads(raw) if raw else None

    def make_project(self, name="Proj", template="website"):
        status, meta = self.json_request("POST", "/api/projects",
                                         {"name": name, "template": template})
        self.assertEqual(status, 201)
        return meta

    def read_sse(self, path, until_events, deadline=12.0, extra_headers=None):
        """Collect SSE (event, data) pairs until one of ``until_events``."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=deadline)
        collected = []
        try:
            conn.request("GET", path, headers=extra_headers or {})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.getheader("Content-Type", ""))
            event_name, end = None, time.time() + deadline
            while time.time() < end:
                line = resp.readline()
                if not line:
                    break
                line = line.decode().rstrip("\n")
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip() or "{}")
                    collected.append((event_name or "message", data))
                    if (event_name or "message") in until_events:
                        return collected
                    event_name = None
            return collected
        finally:
            conn.close()


class TestSecurity(ServerTest):
    def test_foreign_host_header_is_rejected(self):
        status, body = self.json_request("GET", "/api/health",
                                         host="evil.example.com")
        self.assertEqual(status, 403)
        self.assertIn("host", body["error"])

    def test_mutation_without_csrf_header_is_rejected(self):
        status, body = self.json_request("POST", "/api/projects",
                                         {"name": "x"}, csrf=False)
        self.assertEqual(status, 403)
        self.assertIn("X-Forge-Client", body["error"])

    def test_get_needs_no_csrf_header(self):
        status, _ = self.json_request("GET", "/api/health")
        self.assertEqual(status, 200)

    def test_static_jail(self):
        status, _headers, _raw = self.request("GET", "/assets/../store.py")
        self.assertEqual(status, 404)


class TestProjectApi(ServerTest):
    def test_crud_flow(self):
        meta = self.make_project("Flow Site")
        pid = meta["id"]

        status, listing = self.json_request("GET", "/api/projects")
        self.assertIn(pid, [m["id"] for m in listing["projects"]])

        status, tree = self.json_request("GET", f"/api/projects/{pid}/tree")
        self.assertIn("index.html", [e["path"] for e in tree["tree"]])

        status, _ = self.json_request(
            "PUT", f"/api/projects/{pid}/file?path=notes.txt",
            {"content": "hello"})
        self.assertEqual(status, 200)
        status, f = self.json_request("GET",
                                      f"/api/projects/{pid}/file?path=notes.txt")
        self.assertEqual(f["content"], "hello")

        status, renamed = self.json_request("PATCH", f"/api/projects/{pid}",
                                            {"name": "Renamed"})
        self.assertEqual(renamed["name"], "Renamed")

        status, _ = self.json_request("DELETE", f"/api/projects/{pid}")
        self.assertEqual(status, 200)
        status, _ = self.json_request("GET", f"/api/projects/{pid}")
        self.assertEqual(status, 404)

    def test_error_shapes(self):
        status, body = self.json_request("GET", "/api/projects/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", body)
        status, body = self.json_request("POST", "/api/projects", {"name": ""})
        self.assertEqual(status, 400)
        status, body = self.json_request("GET", "/api/nothing-here")
        self.assertEqual(status, 404)

    def test_traversal_via_api_is_denied(self):
        pid = self.make_project("Jail Site")["id"]
        status, body = self.json_request(
            "GET", f"/api/projects/{pid}/file?path=../../settings.json")
        self.assertEqual(status, 403)

    def test_export_zip(self):
        pid = self.make_project("Zip Site")["id"]
        status, headers, raw = self.request("GET", f"/api/projects/{pid}/export")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "application/zip")
        self.assertTrue(raw.startswith(b"PK"))

    def test_version_endpoint(self):
        pid = self.make_project("Ver Site")["id"]
        _, v1 = self.json_request("GET", f"/api/projects/{pid}/version")
        self.json_request("PUT", f"/api/projects/{pid}/file?path=a.txt",
                          {"content": "x"})
        _, v2 = self.json_request("GET", f"/api/projects/{pid}/version")
        self.assertGreater(v2["version"], v1["version"])


class TestPreviewAndStatic(ServerTest):
    def test_preview_serves_html_with_live_reload(self):
        pid = self.make_project("Preview Site")["id"]
        status, headers, raw = self.request("GET", f"/p/{pid}/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"Aurora", raw)
        self.assertIn(b"/__forge/live.js", raw)

    def test_preview_css_mime_and_no_injection(self):
        pid = self.make_project("Mime Site")["id"]
        status, headers, raw = self.request("GET", f"/p/{pid}/style.css")
        self.assertIn("text/css", headers["Content-Type"])
        self.assertNotIn(b"live.js", raw)

    def test_preview_missing_file_404s(self):
        pid = self.make_project("Missing Site")["id"]
        status, _h, raw = self.request("GET", f"/p/{pid}/nope.html")
        self.assertEqual(status, 404)

    def test_spa_fallback_serves_app(self):
        for path in ("/", "/app/some-project"):
            status, headers, raw = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn("text/html", headers["Content-Type"])
            self.assertIn(b"forge", raw.lower())

    def test_live_js_served(self):
        status, headers, _raw = self.request("GET", "/__forge/live.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])


class TestRunApi(ServerTest):
    def test_run_stream_and_exit(self):
        pid = self.make_project("Runner", template="python")["id"]
        status, _ = self.json_request(
            "POST", f"/api/projects/{pid}/run",
            {"command": 'python3 -c "print(\'streamed!\')"'})
        self.assertEqual(status, 201)
        events = self.read_sse(f"/api/projects/{pid}/run/stream", {"exit"})
        kinds = [k for k, _ in events]
        self.assertIn("start", kinds)
        self.assertIn("exit", kinds)
        out = "".join(d.get("text", "") for k, d in events if k == "out")
        self.assertIn("streamed!", out)

    def test_stdin_roundtrip_over_api(self):
        pid = self.make_project("Stdin", template="python")["id"]
        self.json_request(
            "POST", f"/api/projects/{pid}/run",
            {"command": 'python3 -c "print(\'hi \' + input())"'})
        deadline = time.time() + 5
        while time.time() < deadline:
            _, state = self.json_request("GET", f"/api/projects/{pid}/run/state")
            if state["running"]:
                break
            time.sleep(0.05)
        status, _ = self.json_request("POST", f"/api/projects/{pid}/run/input",
                                      {"text": "there"})
        self.assertEqual(status, 200)
        events = self.read_sse(f"/api/projects/{pid}/run/stream", {"exit"})
        out = "".join(d.get("text", "") for k, d in events if k == "out")
        self.assertIn("hi there", out)

    def test_stop_endpoint(self):
        pid = self.make_project("Stopper", template="python")["id"]
        self.json_request("POST", f"/api/projects/{pid}/run",
                          {"command": 'python3 -c "import time; time.sleep(60)"'})
        status, body = self.json_request("POST", f"/api/projects/{pid}/run/stop")
        self.assertEqual(status, 200)
        events = self.read_sse(f"/api/projects/{pid}/run/stream", {"exit"})
        self.assertIn("exit", [k for k, _ in events])

    def test_stream_with_no_run_says_none(self):
        pid = self.make_project("Idle", template="python")["id"]
        events = self.read_sse(f"/api/projects/{pid}/run/stream", {"none"},
                               deadline=5.0)
        self.assertEqual(events[-1][0], "none")

    def test_run_without_command_is_an_error(self):
        pid = self.make_project("NoCmd", template="website")["id"]
        status, body = self.json_request("POST", f"/api/projects/{pid}/run", {})
        self.assertEqual(status, 400)
        self.assertIn("run command", body["error"])


class TestAiApi(ServerTest):
    def test_chat_requires_a_key(self):
        self.json_request("POST", "/api/settings", {"anthropic_api_key": ""})
        status, body = self.json_request(
            "POST", "/api/ai/chat",
            {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "no_key")

    def test_chat_streams_with_key(self):
        self.json_request("POST", "/api/settings",
                          {"anthropic_api_key": "sk-test-123"})
        try:
            pid = self.make_project("Ai Site")["id"]
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.request(
                    "POST", "/api/ai/chat",
                    body=json.dumps({
                        "messages": [{"role": "user", "content": "build it"}],
                        "project_id": pid,
                        "include_paths": ["index.html"],
                    }),
                    headers={"Content-Type": "application/json",
                             "X-Forge-Client": "1"})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                raw = resp.read().decode()
            finally:
                conn.close()
            payloads = [json.loads(line[5:]) for line in raw.splitlines()
                        if line.startswith("data:")]
            text = "".join(p.get("text", "") for p in payloads
                           if p.get("type") == "text")
            self.assertEqual(text, "Hello from fake Claude")
            self.assertEqual(payloads[-1]["type"], "done")
        finally:
            self.json_request("POST", "/api/settings", {"anthropic_api_key": ""})

    def test_settings_masks_key(self):
        self.json_request("POST", "/api/settings",
                          {"anthropic_api_key": "sk-ant-api03-secretmiddle9999"})
        try:
            _, body = self.json_request("GET", "/api/settings")
            self.assertTrue(body["ai_ready"])
            self.assertNotIn("secretmiddle", body["key_masked"])
        finally:
            self.json_request("POST", "/api/settings", {"anthropic_api_key": ""})


if __name__ == "__main__":
    unittest.main()
