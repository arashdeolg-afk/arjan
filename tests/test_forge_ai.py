"""AI module tests — no network: the transport is faked."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forge import ai  # noqa: E402


def sse(*events):
    """Fake Anthropic SSE byte stream from event dicts."""
    lines = []
    for event in events:
        lines.append(f"event: {event['type']}\n".encode())
        lines.append(f"data: {json.dumps(event)}\n".encode())
        lines.append(b"\n")
    return lines


def delta(text):
    return {"type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": text}}


class TestKeyHandling(unittest.TestCase):
    def test_env_wins_over_settings(self):
        import os
        os.environ["ANTHROPIC_API_KEY"] = "sk-env"
        try:
            key, source = ai.resolve_key({"anthropic_api_key": "sk-saved"})
            self.assertEqual((key, source), ("sk-env", "env"))
        finally:
            del os.environ["ANTHROPIC_API_KEY"]
        key, source = ai.resolve_key({"anthropic_api_key": "sk-saved"})
        self.assertEqual((key, source), ("sk-saved", "settings"))
        self.assertEqual(ai.resolve_key({}), (None, "none"))

    def test_mask_key_never_shows_the_middle(self):
        masked = ai.mask_key("sk-ant-api03-abcdefghijklmnop1234")
        self.assertNotIn("abcdefghijklmnop", masked)
        self.assertTrue(masked.endswith("1234"))
        self.assertEqual(ai.mask_key("short"), "*****")


class TestPayload(unittest.TestCase):
    def test_opus_gets_refusal_fallbacks(self):
        payload, headers = ai.request_payload(
            "claude-opus-5", "sys", [{"role": "user", "content": "hi"}])
        self.assertEqual(payload["fallbacks"], "default")
        self.assertEqual(headers["anthropic-beta"], ai.FALLBACK_BETA)
        self.assertTrue(payload["stream"])
        self.assertNotIn("temperature", payload)
        self.assertNotIn("thinking", payload)

    def test_other_models_do_not(self):
        payload, headers = ai.request_payload(
            "claude-haiku-4-5", "sys", [{"role": "user", "content": "hi"}])
        self.assertNotIn("fallbacks", payload)
        self.assertEqual(headers, {})

    def test_max_tokens_capped_per_model(self):
        payload, _ = ai.request_payload(
            "claude-haiku-4-5", "s", [], max_tokens=999_999)
        self.assertEqual(payload["max_tokens"], 32000)

    def test_build_system_includes_context(self):
        system = ai.build_system(
            "build",
            {"name": "Site", "kind": "web", "run": ""},
            ["index.html", "style.css"],
            [("index.html", "<p>hi</p>"), ("big.txt", "x" * 40_000)],
        )
        self.assertIn("```file:", system)          # build-mode contract
        self.assertIn('"Site"', system)
        self.assertIn("index.html", system)
        self.assertIn("<p>hi</p>", system)
        self.assertIn("(truncated)", system)
        chat = ai.build_system("chat", None, [], [])
        self.assertNotIn("```file:", chat)


class TestStream(unittest.TestCase):
    def run_stream(self, lines, capture=None):
        def transport(url, headers, body):
            if capture is not None:
                capture.update(url=url, headers=headers,
                               body=json.loads(body.decode()))
            return lines
        payload, extra = ai.request_payload(
            "claude-opus-5", "sys", [{"role": "user", "content": "hi"}])
        return list(ai.stream_chat("sk-key", payload, extra, transport))

    def test_text_deltas_and_done(self):
        capture = {}
        out = self.run_stream(sse(
            {"type": "message_start", "message": {}},
            delta("Hello "), delta("world"),
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 5}},
            {"type": "message_stop"},
        ), capture)
        texts = [e["text"] for e in out if e["type"] == "text"]
        self.assertEqual("".join(texts), "Hello world")
        self.assertEqual(out[-1]["type"], "done")
        self.assertEqual(out[-1]["stop_reason"], "end_turn")
        self.assertEqual(capture["headers"]["x-api-key"], "sk-key")
        self.assertEqual(capture["headers"]["anthropic-version"], ai.API_VERSION)
        self.assertEqual(capture["body"]["model"], "claude-opus-5")

    def test_pings_and_unknown_events_ignored(self):
        out = self.run_stream(
            [b": keepalive\n", b"\n"] + sse(
                {"type": "ping"}, delta("ok"), {"type": "message_stop"}))
        self.assertEqual([e["text"] for e in out if e["type"] == "text"], ["ok"])

    def test_error_event_surfaces(self):
        out = self.run_stream(sse(
            delta("partial"),
            {"type": "error", "error": {"type": "overloaded_error",
                                        "message": "Overloaded"}},
        ))
        self.assertEqual(out[-1]["type"], "error")
        self.assertIn("Overloaded", out[-1]["message"])

    def test_refusal_stop_reason_becomes_error(self):
        out = self.run_stream(sse(
            {"type": "message_delta", "delta": {"stop_reason": "refusal"},
             "usage": {}},
            {"type": "message_stop"},
        ))
        self.assertEqual(out[-1]["type"], "error")
        self.assertIn("declined", out[-1]["message"])


class TestProviders(unittest.TestCase):
    """The multi-provider layer: keys land later, everything is ready now."""

    def setUp(self):
        import os
        self._saved = {}
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            self._saved[var] = os.environ.pop(var, None)

    def tearDown(self):
        import os
        for var, value in self._saved.items():
            if value is not None:
                os.environ[var] = value

    def test_key_resolution_per_provider(self):
        import os
        settings = {"providers": {"openai": {"api_key": "sk-saved"}}}
        self.assertEqual(ai.resolve_provider_key(settings, "openai"),
                         ("sk-saved", "settings"))
        os.environ["OPENAI_API_KEY"] = "sk-env"
        try:
            self.assertEqual(ai.resolve_provider_key(settings, "openai"),
                             ("sk-env", "env"))
        finally:
            del os.environ["OPENAI_API_KEY"]
        self.assertEqual(ai.resolve_provider_key({}, "gemini"), (None, "none"))

    def test_legacy_anthropic_key_still_counts(self):
        settings = {"anthropic_api_key": "sk-old"}
        self.assertEqual(ai.resolve_provider_key(settings, "anthropic"),
                         ("sk-old", "settings"))
        self.assertTrue(ai.provider_ready(settings, "anthropic"))

    def test_compat_is_ready_with_base_url_and_no_key(self):
        self.assertFalse(ai.provider_ready({}, "compat"))
        settings = {"providers": {"compat":
                    {"base_url": "http://127.0.0.1:11434/v1"}}}
        self.assertTrue(ai.provider_ready(settings, "compat"))

    def test_default_selection_and_models(self):
        self.assertEqual(ai.default_selection({}),
                         ("anthropic", ai.DEFAULT_MODEL))
        settings = {"ai": {"provider": "gemini"},
                    "providers": {"gemini": {"model": "gemini-x"}}}
        self.assertEqual(ai.default_selection(settings), ("gemini", "gemini-x"))
        # Legacy top-level model still steers anthropic.
        self.assertEqual(ai.default_model_for({"model": "claude-sonnet-5"},
                                              "anthropic"), "claude-sonnet-5")

    def test_prepare_openai_request(self):
        settings = {"providers": {"openai": {"api_key": "sk-oa"}}}
        url, headers, payload = ai.prepare_request(
            "openai", "gpt-4o", "sys prompt",
            [{"role": "user", "content": "hi"}], settings)
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(headers["authorization"], "Bearer sk-oa")
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["messages"][0],
                         {"role": "system", "content": "sys prompt"})
        self.assertEqual(payload["messages"][1]["content"], "hi")

    def test_prepare_compat_needs_base_url(self):
        with self.assertRaises(ai.AIError):
            ai.prepare_request("compat", "llama3", "s",
                               [{"role": "user", "content": "hi"}], {})
        settings = {"providers": {"compat":
                    {"base_url": "http://127.0.0.1:11434/v1/"}}}
        url, headers, _payload = ai.prepare_request(
            "compat", "llama3", "s", [{"role": "user", "content": "hi"}],
            settings)
        self.assertEqual(url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertNotIn("authorization", headers)  # keyless local server

    def test_prepare_gemini_request(self):
        settings = {"providers": {"gemini": {"api_key": "g-key"}}}
        url, headers, payload = ai.prepare_request(
            "gemini", "gemini-2.0-flash", "sys",
            [{"role": "user", "content": "q"},
             {"role": "assistant", "content": "a"}], settings)
        self.assertIn("gemini-2.0-flash:streamGenerateContent", url)
        self.assertEqual(headers["x-goog-api-key"], "g-key")
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(payload["contents"][1]["role"], "model")
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "sys")

    def test_chat_streams_openai_shape(self):
        chunks = [
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
            b"data: [DONE]\n",
        ]
        captured = {}

        def transport(url, headers, body):
            captured.update(url=url, body=json.loads(body))
            return chunks

        settings = {"providers": {"openai": {"api_key": "sk"}}}
        out = list(ai.chat("openai", "gpt-4o", "s",
                           [{"role": "user", "content": "hi"}],
                           settings, transport))
        text = "".join(e["text"] for e in out if e["type"] == "text")
        self.assertEqual(text, "Hello")
        self.assertEqual(out[-1], {"type": "done", "stop_reason": "stop",
                                   "usage": {}})
        self.assertEqual(captured["body"]["model"], "gpt-4o")

    def test_chat_streams_gemini_shape(self):
        chunks = [
            b'data: {"candidates":[{"content":{"parts":[{"text":"Hi "}]}}]}\n',
            b'data: {"candidates":[{"content":{"parts":[{"text":"there"}]},'
            b'"finishReason":"STOP"}]}\n',
        ]
        settings = {"providers": {"gemini": {"api_key": "g"}}}
        out = list(ai.chat("gemini", "gemini-2.0-flash", "s",
                           [{"role": "user", "content": "hi"}],
                           settings, lambda *a: chunks))
        text = "".join(e["text"] for e in out if e["type"] == "text")
        self.assertEqual(text, "Hi there")
        self.assertEqual(out[-1]["stop_reason"], "STOP")

    def test_openai_error_object_surfaces(self):
        chunks = [b'data: {"error":{"message":"invalid model"}}\n']
        settings = {"providers": {"openai": {"api_key": "sk"}}}
        out = list(ai.chat("openai", "nope", "s",
                           [{"role": "user", "content": "hi"}],
                           settings, lambda *a: chunks))
        self.assertEqual(out[-1]["type"], "error")
        self.assertIn("invalid model", out[-1]["message"])

    def test_provider_status_masks_keys(self):
        settings = {"providers": {"openai": {"api_key": "sk-oa-secret123456"}}}
        status = ai.provider_status(settings)
        self.assertTrue(status["openai"]["ready"])
        self.assertNotIn("secret1234", status["openai"]["key_masked"])
        self.assertFalse(status["gemini"]["ready"])
        self.assertIn("models", status["anthropic"])


class TestFileBlocks(unittest.TestCase):
    def test_single_block(self):
        text = ("Here you go.\n\n```file:index.html\n<h1>Hi</h1>\n```\n\nDone.")
        blocks = ai.parse_file_blocks(text)
        self.assertEqual(blocks, [{"path": "index.html",
                                   "content": "<h1>Hi</h1>"}])

    def test_multiple_blocks_and_nested_paths(self):
        text = ("```file:src/app.js\nconsole.log(1)\n```\n"
                "middle words\n"
                "```file:/style.css\nbody{}\n```")
        blocks = ai.parse_file_blocks(text)
        self.assertEqual([b["path"] for b in blocks],
                         ["src/app.js", "style.css"])
        self.assertEqual(blocks[1]["content"], "body{}")

    def test_multiline_content_preserved(self):
        body = "line1\n\n  indented\nline3"
        blocks = ai.parse_file_blocks(f"```file:a.py\n{body}\n```")
        self.assertEqual(blocks[0]["content"], body)

    def test_plain_code_fences_are_not_files(self):
        text = "```python\nprint('hi')\n```"
        self.assertEqual(ai.parse_file_blocks(text), [])

    def test_backticks_inside_a_line_do_not_close(self):
        blocks = ai.parse_file_blocks(
            "```file:doc.md\nuse `code` inline\n```")
        self.assertEqual(blocks[0]["content"], "use `code` inline")

    def test_empty_body(self):
        blocks = ai.parse_file_blocks("```file:empty.txt\n\n```")
        self.assertEqual(blocks[0]["content"], "")


if __name__ == "__main__":
    unittest.main()
