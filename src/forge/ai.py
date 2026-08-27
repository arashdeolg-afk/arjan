"""Claude integration: the AI pane's backend.

Talks to the Anthropic Messages API directly over urllib (this repo is
stdlib-only, so the official SDK is not an option). Responses stream as
Server-Sent Events which we parse and relay to the browser.

The key is read from ANTHROPIC_API_KEY or from forge's local settings
(saved via the in-app settings dialog); nothing works — and nothing is
sent anywhere — until one of those exists.

In "build" mode the system prompt asks Claude to emit complete files as
fenced blocks of the form `````file:relative/path`` so the frontend can
offer one-click apply; :func:`parse_file_blocks` is the parser.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

DEFAULT_MODEL = "claude-opus-5"
MODELS = [
    {"id": "claude-opus-5", "label": "Claude Opus 5",
     "blurb": "Best default — top-tier coding", "max_tokens": 64000},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5",
     "blurb": "Fast and capable", "max_tokens": 64000},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5",
     "blurb": "Fastest, cheapest", "max_tokens": 32000},
]
# Models where a safety refusal can be rescued server-side.
_FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5"}

MAX_CONTEXT_FILE = 30_000  # chars of any single file included as context
MAX_TREE_PATHS = 200

CHAT_SYSTEM = (
    "You are the assistant inside Forge, a lightweight browser IDE for "
    "building websites and small apps. Be direct and concise. When you "
    "show code, use fenced code blocks with a language tag. Websites here "
    "are plain HTML/CSS/JS served statically with live reload; programs "
    "run with Python 3 (stdlib only — nothing can be pip-installed)."
)

BUILD_SYSTEM = CHAT_SYSTEM + (
    "\n\nYou can create and modify project files. For every file you add "
    "or change, output ONE fenced block per file in exactly this form:\n"
    "```file:relative/path.ext\n<the complete file contents>\n```\n"
    "Rules: always give the COMPLETE file (it replaces the old one), "
    "never truncate or elide, and don't put ``` fences inside the file "
    "body. Outside the blocks, keep commentary to a sentence or two. "
    "Prefer plain HTML/CSS/JS for web projects and stdlib-only Python "
    "for programs, so everything runs in Forge as-is."
)


class AIError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def resolve_key(settings: dict) -> tuple[str | None, str]:
    """(key, source) — the environment wins over saved settings."""
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env, "env"
    saved = str(settings.get("anthropic_api_key", "")).strip()
    if saved:
        return saved, "settings"
    return None, "none"


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:7]}…{key[-4:]}"


def model_info(model_id: str) -> dict:
    for m in MODELS:
        if m["id"] == model_id:
            return m
    return {"id": model_id, "label": model_id, "max_tokens": 32000}


def build_system(mode: str, meta: dict | None = None,
                 tree_paths: list[str] | None = None,
                 files: list[tuple[str, str]] | None = None) -> str:
    parts = [BUILD_SYSTEM if mode == "build" else CHAT_SYSTEM]
    if meta:
        run = meta.get("run") or "none (static preview)"
        parts.append(
            f"Current project: \"{meta.get('name')}\" "
            f"(kind: {meta.get('kind')}, run command: {run})."
        )
    if tree_paths:
        shown = tree_paths[:MAX_TREE_PATHS]
        listing = "\n".join(shown)
        if len(tree_paths) > len(shown):
            listing += f"\n… and {len(tree_paths) - len(shown)} more"
        parts.append(f"Files in the project:\n{listing}")
    for path, content in files or []:
        body = content[:MAX_CONTEXT_FILE]
        if len(content) > MAX_CONTEXT_FILE:
            body += "\n… (truncated)"
        parts.append(f"Current contents of {path}:\n```\n{body}\n```")
    return "\n\n".join(parts)


def request_payload(model: str, system: str, messages: list[dict],
                    max_tokens: int | None = None) -> tuple[dict, dict]:
    """(payload, extra_headers) for a streaming Messages API call."""
    info = model_info(model)
    payload = {
        "model": model,
        "max_tokens": min(max_tokens or info["max_tokens"], info["max_tokens"]),
        "stream": True,
        "system": system,
        "messages": messages,
    }
    headers: dict[str, str] = {}
    if model in _FALLBACK_MODELS:
        # Rescue safety refusals by re-running on a fallback model
        # server-side instead of returning an empty turn.
        payload["fallbacks"] = "default"
        headers["anthropic-beta"] = FALLBACK_BETA
    return payload, headers


def _default_transport(url: str, headers: dict, body: bytes):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=600)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read().decode("utf-8", "replace"))
            detail = err.get("error", {}).get("message", "")
        except (ValueError, OSError):
            pass
        raise AIError(f"Anthropic API error {e.code}: {detail or e.reason}",
                      e.code if e.code >= 400 else 502)
    except urllib.error.URLError as e:
        raise AIError(f"could not reach the Anthropic API: {e.reason}")


def stream_chat(key: str, payload: dict, extra_headers: dict | None = None,
                transport=None):
    """Yield {'type': 'text'|'done'|'error', ...} dicts from a streaming call."""
    headers = {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "accept": "text/event-stream",
    }
    headers.update(extra_headers or {})
    transport = transport or _default_transport
    body = json.dumps(payload).encode("utf-8")

    resp = transport(API_URL, headers, body)
    stop_reason = None
    usage: dict = {}
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            try:
                event = json.loads(data)
            except ValueError:
                continue
            etype = event.get("type")
            if etype == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield {"type": "text", "text": delta.get("text", "")}
            elif etype == "message_delta":
                stop_reason = event.get("delta", {}).get("stop_reason")
                usage = event.get("usage", {}) or usage
            elif etype == "message_stop":
                break
            elif etype == "error":
                message = event.get("error", {}).get("message", "stream error")
                yield {"type": "error", "message": message}
                return
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()

    if stop_reason == "refusal":
        yield {"type": "error",
               "message": "Claude declined this request (safety refusal)."}
        return
    yield {"type": "done", "stop_reason": stop_reason, "usage": usage}


_FILE_BLOCK = re.compile(
    r"^```file:([^\n`]+?)[ \t]*\n(.*?)\n?^```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


def parse_file_blocks(text: str) -> list[dict]:
    """Extract ``` ```file:path`` fenced blocks -> [{path, content}]."""
    out = []
    for match in _FILE_BLOCK.finditer(text or ""):
        path = match.group(1).strip().strip("/")
        if path:
            out.append({"path": path, "content": match.group(2)})
    return out
