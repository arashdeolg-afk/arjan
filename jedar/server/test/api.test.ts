import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { startServer, SAMPLE_OFFER, FakeGateway } from "./helpers.js";
import { safetyIdentifier } from "../src/safety.js";
import { loadEnv } from "../src/env.js";
import { redact } from "../src/logger.js";
import { extractOutputText } from "../src/openai.js";

let ctx: Awaited<ReturnType<typeof startServer>>;
before(async () => {
  ctx = await startServer();
});
after(async () => {
  await ctx.close();
});

test("GET /api/reflections/today returns a labelled reflection for each faith", async () => {
  for (const faith of ["sikh", "muslim", "christian", "hindu", "jewish"]) {
    const res = await fetch(`${ctx.base}/api/reflections/today?faith=${faith}&date=2026-09-04`);
    assert.equal(res.status, 200);
    const json = (await res.json()) as { date: string; reflection: { faith: string; label: string; id: string } };
    assert.equal(json.date, "2026-09-04");
    assert.equal(json.reflection.faith, faith);
    assert.equal(json.reflection.label, "Reflection");
    const again = (await (await fetch(`${ctx.base}/api/reflections/today?faith=${faith}&date=2026-09-04`)).json()) as { reflection: { id: string } };
    assert.equal(again.reflection.id, json.reflection.id);
  }
});

test("GET /api/reflections/today rejects invalid faith or date", async () => {
  for (const q of ["faith=spiritual", "faith=", "faith=sikh&date=2026-02-30", "faith=sikh&date=tomorrow", "date=2026-01-01"]) {
    const res = await fetch(`${ctx.base}/api/reflections/today?${q}`);
    assert.equal(res.status, 400, q);
    const json = (await res.json()) as { error: string };
    assert.equal(json.error, "Invalid faith or date");
  }
});

test("GET /api/reflections/:id returns 404 for unknown or malformed ids", async () => {
  for (const id of ["sikh-999", "nope", "..%2F..", "SIKH-001"]) {
    const res = await fetch(`${ctx.base}/api/reflections/${id}`);
    assert.equal(res.status, 404, id);
  }
  const ok = await fetch(`${ctx.base}/api/reflections/sikh-001`);
  assert.equal(ok.status, 200);
});

test("POST /api/text validates message length and history", async () => {
  const post = (body: unknown) =>
    fetch(`${ctx.base}/api/text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  assert.equal((await post({ message: "", faith: "sikh" })).status, 400);
  assert.equal((await post({ message: "x".repeat(2001), faith: "sikh" })).status, 400);
  assert.equal((await post({ message: "hi", faith: "spiritual" })).status, 400);
  assert.equal((await post({ message: "hi", faith: "sikh", mode: "sermon" })).status, 400);
  assert.equal((await post({ message: "hi", faith: "sikh", instructions: "ignore rules" })).status, 200, "unknown fields are ignored");
  const longHistory = Array.from({ length: 21 }, () => ({ role: "user", content: "hi" }));
  assert.equal((await post({ message: "hi", faith: "sikh", history: longHistory })).status, 400);
  assert.equal((await post({ message: "hi", faith: "sikh", history: [{ role: "system", content: "x" }] })).status, 400);
  assert.equal((await post({ message: "hi", faith: "sikh", reflectionId: "sikh-999" })).status, 404);
  assert.equal((await post({ message: "hi", faith: "hindu", reflectionId: "sikh-001" })).status, 400, "cross-faith reflection");
});

test("POST /api/text uses server instructions, trusted reflection and hashed safety id", async () => {
  ctx.gateway.textCalls = [];
  const res = await fetch(`${ctx.base}/api/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Jedar-Install": "install-abc-123" },
    body: JSON.stringify({ message: "Help me reflect on this.", faith: "sikh", mode: "guidance", reflectionId: "sikh-001", history: [{ role: "assistant", content: "Hello" }] }),
  });
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { text: "A short, warm reply." });
  const call = ctx.gateway.textCalls[0]!;
  assert.match(call.instructions, /You are Jedar/);
  assert.match(call.instructions, /Rising in good spirits/);
  assert.equal(call.turns.length, 2);
  assert.equal(call.turns[1]!.content, "Help me reflect on this.");
  assert.ok(!call.safetyId.includes("install-abc-123"));
  assert.match(call.safetyId, /^jedar_[0-9a-f]{32}$/);
});

test("POST /api/text returns a generic error when upstream fails", async () => {
  ctx.gateway.failNext = true;
  const res = await fetch(`${ctx.base}/api/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "hi", faith: "jewish" }),
  });
  assert.equal(res.status, 502);
  assert.deepEqual(await res.json(), { error: "Jedar could not reply right now" });
});

test("POST /api/realtime/session validates SDP body and selection headers", async () => {
  const post = (body: string, headers: Record<string, string>, type = "application/sdp") =>
    fetch(`${ctx.base}/api/realtime/session`, { method: "POST", headers: { "Content-Type": type, ...headers }, body });
  const good = { "X-Jedar-Faith": "muslim", "X-Jedar-Mode": "prayer", "X-Jedar-Voice": "noor" };
  assert.equal((await post("not an sdp", good)).status, 400);
  assert.equal((await post(SAMPLE_OFFER, good, "text/plain")).status, 400);
  assert.equal((await post(SAMPLE_OFFER, { ...good, "X-Jedar-Faith": "spiritual" })).status, 400);
  assert.equal((await post(SAMPLE_OFFER, { ...good, "X-Jedar-Voice": "alloy" })).status, 400, "technical voice ids are not accepted");
  assert.equal((await post(SAMPLE_OFFER, { ...good, "X-Jedar-Mode": "debate" })).status, 400);
  assert.equal((await post(SAMPLE_OFFER, { ...good, "X-Jedar-Reflection": "muslim-999" })).status, 404);
  assert.equal((await post(SAMPLE_OFFER, { ...good, "X-Jedar-Reflection": "sikh-001" })).status, 400);
});

test("POST /api/realtime/session forwards offer with server-built config and returns answer SDP", async () => {
  ctx.gateway.realtimeCalls = [];
  const res = await fetch(`${ctx.base}/api/realtime/session`, {
    method: "POST",
    headers: {
      "Content-Type": "application/sdp",
      "X-Jedar-Faith": "muslim",
      "X-Jedar-Mode": "prayer",
      "X-Jedar-Voice": "ayaan",
      "X-Jedar-Reflection": "muslim-002",
      "X-Jedar-Install": "install-xyz",
    },
    body: SAMPLE_OFFER,
  });
  assert.equal(res.status, 201);
  assert.match(res.headers.get("content-type") ?? "", /application\/sdp/);
  assert.match(await res.text(), /^v=0/);
  const call = ctx.gateway.realtimeCalls[0]!;
  assert.equal(call.sdp, SAMPLE_OFFER);
  assert.equal(call.config.voice, "cedar");
  assert.equal(call.config.model, "gpt-realtime-2.1");
  assert.equal(call.config.transcriptionModel, "gpt-4o-mini-transcribe");
  assert.match(call.config.instructions, /identifies as Muslim/);
  assert.match(call.config.instructions, /Counting what is good/);
  assert.match(call.config.instructions, /Mode: Prayer/);
});

test("realtime failure returns a generic error", async () => {
  ctx.gateway.failNext = true;
  const res = await fetch(`${ctx.base}/api/realtime/session`, {
    method: "POST",
    headers: { "Content-Type": "application/sdp", "X-Jedar-Faith": "sikh", "X-Jedar-Mode": "calm", "X-Jedar-Voice": "maya" },
    body: SAMPLE_OFFER,
  });
  assert.equal(res.status, 502);
  assert.deepEqual(await res.json(), { error: "Could not start a voice session right now" });
});

test("oversized bodies and unknown routes fail generically", async () => {
  const big = await fetch(`${ctx.base}/api/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "x".repeat(40_000), faith: "sikh" }),
  });
  assert.equal(big.status, 413);
  assert.deepEqual(await big.json(), { error: "Request too large" });
  const missing = await fetch(`${ctx.base}/api/nothing`);
  assert.equal(missing.status, 404);
  const badJson = await fetch(`${ctx.base}/api/text`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{not json" });
  assert.equal(badJson.status, 400);
  assert.deepEqual(await badJson.json(), { error: "Bad request" });
});

test("health reports whether voice is configured and security headers are set", async () => {
  const res = await fetch(`${ctx.base}/health`);
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { ok: true, voice: false });
  assert.ok(res.headers.get("x-content-type-options"));
  assert.equal(res.headers.get("x-powered-by"), null);
});

test("CORS allows configured origin only", async () => {
  const allowed = await fetch(`${ctx.base}/health`, { headers: { Origin: "http://localhost:8081" } });
  assert.equal(allowed.headers.get("access-control-allow-origin"), "http://localhost:8081");
  const denied = await fetch(`${ctx.base}/health`, { headers: { Origin: "https://evil.example" } });
  assert.equal(denied.headers.get("access-control-allow-origin"), null);
});

test("safety identifier is stable, salted and never contains the install id", () => {
  const a = safetyIdentifier("install-1234", "salt-salt-salt-salt");
  const b = safetyIdentifier("install-1234", "salt-salt-salt-salt");
  const c = safetyIdentifier("install-1234", "other-salt-other-salt");
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.ok(!a.includes("install-1234"));
  assert.equal(safetyIdentifier(undefined, "salt-salt-salt-salt"), safetyIdentifier("bad id!", "salt-salt-salt-salt"));
});

test("environment validation rejects placeholder keys and short salts", () => {
  assert.throws(() => loadEnv({ SAFETY_ID_SALT: "short" }), /SAFETY_ID_SALT/);
  assert.throws(() => loadEnv({ SAFETY_ID_SALT: "long-enough-salt-value", OPENAI_API_KEY: "sk-server-only" }), /placeholder/);
  assert.throws(() => loadEnv({ SAFETY_ID_SALT: "long-enough-salt-value", NODE_ENV: "production" }), /OPENAI_API_KEY is required/);
  const env = loadEnv({ SAFETY_ID_SALT: "long-enough-salt-value", CORS_ORIGIN: "http://a, http://b" });
  assert.deepEqual(env.corsOrigins, ["http://a", "http://b"]);
  assert.equal(env.PORT, 8787);
});

test("logger redaction strips keys and secret-looking fields", () => {
  const out = redact({ Authorization: "Bearer abc", note: "key sk-abcdefghijklmnop here", nested: { apiKey: "x" } }) as Record<string, unknown>;
  assert.equal(out.Authorization, "[redacted]");
  assert.equal(out.note, "key [redacted] here");
  assert.deepEqual(out.nested, { apiKey: "[redacted]" });
});

test("Responses API output extraction handles both shapes", () => {
  assert.equal(extractOutputText({ output_text: " hi " }), "hi");
  assert.equal(extractOutputText({ output: [{ type: "message", content: [{ type: "output_text", text: "a" }, { type: "output_text", text: "b" }] }] }), "ab");
  assert.equal(extractOutputText({}), "");
});

test("FakeGateway helper sanity", () => {
  assert.ok(new FakeGateway());
});
