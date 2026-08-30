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

# The AI pane is multi-provider: Claude is the first-class default, and
# keys for other providers can be added later without code changes —
# their model ids are free text, so new models need no forge release.
PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label": "Claude (Anthropic)",
        "env": "ANTHROPIC_API_KEY",
        "needs_key": True,
        "default_model": DEFAULT_MODEL,
        "model_choice": "list",  # curated dropdown (MODELS)
    },
    "openai": {
        "label": "OpenAI",
        "env": "OPENAI_API_KEY",
        "needs_key": True,
        "default_model": "gpt-4o",
        "model_choice": "free",
    },
    "gemini": {
        "label": "Google Gemini",
        "env": "GEMINI_API_KEY",
        "needs_key": True,
        "default_model": "gemini-2.0-flash",
        "model_choice": "free",
    },
    "compat": {
        "label": "OpenAI-compatible",
        "env": "",
        "needs_key": False,  # a local Ollama needs no key, just a base URL
        "default_model": "",
        "model_choice": "free",
    },
}

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


# ------------------------------------------------------- provider registry


def provider_conf(settings: dict, provider: str) -> dict:
    conf = dict((settings.get("providers") or {}).get(provider) or {})
    if provider == "anthropic" and not conf.get("api_key"):
        legacy = str(settings.get("anthropic_api_key", "")).strip()
        if legacy:
            conf["api_key"] = legacy
    return conf


def resolve_provider_key(settings: dict, provider: str) -> tuple[str | None, str]:
    """(key, source) for one provider — the environment wins over settings."""
    spec = PROVIDERS[provider]
    if spec["env"]:
        env = os.environ.get(spec["env"], "").strip()
        if env:
            return env, "env"
    saved = str(provider_conf(settings, provider).get("api_key", "")).strip()
    if saved:
        return saved, "settings"
    return None, "none"


def default_model_for(settings: dict, provider: str) -> str:
    conf = provider_conf(settings, provider)
    model = str(conf.get("model", "")).strip()
    if model:
        return model
    if provider == "anthropic":
        legacy = str(settings.get("model", "")).strip()
        if legacy:
            return legacy
    return PROVIDERS[provider]["default_model"]


def provider_ready(settings: dict, provider: str) -> bool:
    if provider == "compat":
        return bool(str(provider_conf(settings, "compat").get("base_url", "")).strip())
    key, _source = resolve_provider_key(settings, provider)
    return key is not None


def provider_status(settings: dict) -> dict:
    out = {}
    for pid, spec in PROVIDERS.items():
        key, source = resolve_provider_key(settings, pid)
        entry = {
            "label": spec["label"],
            "ready": provider_ready(settings, pid),
            "source": source,
            "key_masked": mask_key(key) if key else None,
            "default_model": default_model_for(settings, pid),
            "model_choice": spec["model_choice"],
            "needs_key": spec["needs_key"],
        }
        if pid == "anthropic":
            entry["models"] = MODELS
        if pid == "compat":
            entry["base_url"] = str(provider_conf(settings, "compat").get("base_url", ""))
        out[pid] = entry
    return out


def default_selection(settings: dict) -> tuple[str, str]:
    """The (provider, model) the AI pane starts on."""
    ai_conf = settings.get("ai") or {}
    provider = ai_conf.get("provider") or "anthropic"
    if provider not in PROVIDERS:
        provider = "anthropic"
    model = str(ai_conf.get("model", "")).strip() or default_model_for(settings, provider)
    return provider, model


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


def _data_lines(resp):
    """SSE 'data:' payloads from an iterable of raw lines."""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                yield data


def _parse_anthropic(resp):
    stop_reason = None
    usage: dict = {}
    for data in _data_lines(resp):
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
    if stop_reason == "refusal":
        yield {"type": "error",
               "message": "Claude declined this request (safety refusal)."}
        return
    yield {"type": "done", "stop_reason": stop_reason, "usage": usage}


def _parse_openai(resp):
    finish = None
    for data in _data_lines(resp):
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except ValueError:
            continue
        if event.get("error"):
            yield {"type": "error",
                   "message": event["error"].get("message", "stream error")}
            return
        choices = event.get("choices") or []
        if choices:
            text = (choices[0].get("delta") or {}).get("content")
            if text:
                yield {"type": "text", "text": text}
            finish = choices[0].get("finish_reason") or finish
    yield {"type": "done", "stop_reason": finish, "usage": {}}


def _parse_gemini(resp):
    finish = None
    for data in _data_lines(resp):
        try:
            event = json.loads(data)
        except ValueError:
            continue
        if event.get("error"):
            yield {"type": "error",
                   "message": event["error"].get("message", "stream error")}
            return
        for cand in event.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                if part.get("text"):
                    yield {"type": "text", "text": part["text"]}
            finish = cand.get("finishReason") or finish
    yield {"type": "done", "stop_reason": finish, "usage": {}}


_PARSERS = {
    "anthropic": _parse_anthropic,
    "openai": _parse_openai,
    "compat": _parse_openai,
    "gemini": _parse_gemini,
}


def prepare_request(provider: str, model: str, system: str,
                    messages: list[dict], settings: dict,
                    max_tokens: int | None = None) -> tuple[str, dict, dict]:
    """(url, headers, payload) for a streaming chat call on any provider."""
    if provider not in PROVIDERS:
        raise AIError(f"unknown provider: {provider}", 400)
    conf = provider_conf(settings, provider)
    key, _source = resolve_provider_key(settings, provider)

    if provider == "anthropic":
        payload, extra = request_payload(model, system, messages, max_tokens)
        headers = {
            "content-type": "application/json",
            "x-api-key": key or "",
            "anthropic-version": API_VERSION,
            "accept": "text/event-stream",
        }
        headers.update(extra)
        return API_URL, headers, payload

    if provider in ("openai", "compat"):
        default_base = "https://api.openai.com/v1" if provider == "openai" else ""
        base = str(conf.get("base_url", "")).strip() or default_base
        if not base:
            raise AIError("set a base URL for the OpenAI-compatible provider "
                          "in Settings", 400)
        headers = {"content-type": "application/json",
                   "accept": "text/event-stream"}
        if key:
            headers["authorization"] = f"Bearer {key}"
        payload = {
            "model": model,
            "stream": True,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + messages,
        }
        return base.rstrip("/") + "/chat/completions", headers, payload

    # gemini
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:streamGenerateContent?alt=sse")
    headers = {"content-type": "application/json",
               "accept": "text/event-stream",
               "x-goog-api-key": key or ""}
    contents = [{"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"]}]} for m in messages]
    payload: dict = {"contents": contents}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    return url, headers, payload


def chat(provider: str, model: str, system: str, messages: list[dict],
         settings: dict, transport=None, max_tokens: int | None = None):
    """Unified streaming chat: yields {'type': 'text'|'done'|'error', ...}."""
    url, headers, payload = prepare_request(
        provider, model, system, messages, settings, max_tokens)
    transport = transport or _default_transport
    resp = transport(url, headers, json.dumps(payload).encode("utf-8"))
    try:
        yield from _PARSERS[provider](resp)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


def stream_chat(key: str, payload: dict, extra_headers: dict | None = None,
                transport=None):
    """Anthropic-only streaming call (kept for direct use and tests)."""
    headers = {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "accept": "text/event-stream",
    }
    headers.update(extra_headers or {})
    transport = transport or _default_transport
    resp = transport(API_URL, headers, json.dumps(payload).encode("utf-8"))
    try:
        yield from _parse_anthropic(resp)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


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
