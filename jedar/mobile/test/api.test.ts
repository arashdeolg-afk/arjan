import { test } from "node:test";
import assert from "node:assert/strict";
import { buildSelectionHeaders, resolveApiUrl } from "../src/lib/api.js";
import { localDateString, formatTimestamp } from "../src/lib/dates.js";
import { FAITHS, FAITH_INFO, JEDAR_VOICES, MODES, isFaith } from "../src/lib/domain.js";

test("api url falls back and strips trailing slashes", () => {
  assert.equal(resolveApiUrl({}), "http://localhost:8787");
  assert.equal(resolveApiUrl({ EXPO_PUBLIC_API_URL: "http://192.168.1.10:8787/" }), "http://192.168.1.10:8787");
});

test("selection headers carry only validated product values", () => {
  const h = buildSelectionHeaders({ faith: "hindu", mode: "learn", voice: "noor" }, "inst-1");
  assert.equal(h["Content-Type"], "application/sdp");
  assert.equal(h["X-Jedar-Faith"], "hindu");
  assert.equal(h["X-Jedar-Mode"], "learn");
  assert.equal(h["X-Jedar-Voice"], "noor");
  assert.equal(h["X-Jedar-Install"], "inst-1");
  assert.ok(!("X-Jedar-Reflection" in h));
  const withRef = buildSelectionHeaders({ faith: "hindu", mode: "learn", voice: "noor", reflectionId: "hindu-002" }, "inst-1");
  assert.equal(withRef["X-Jedar-Reflection"], "hindu-002");
  for (const key of Object.keys(h)) assert.ok(!/instruction|prompt|key/i.test(key));
});

test("mobile domain mirrors the server: five faiths, no generic option", () => {
  assert.deepEqual([...FAITHS], ["sikh", "muslim", "christian", "hindu", "jewish"]);
  assert.ok(!isFaith("spiritual"));
  for (const f of FAITHS) assert.ok(FAITH_INFO[f].label && FAITH_INFO[f].description);
  assert.deepEqual([...MODES], ["calm", "prayer", "guidance", "journal", "learn"]);
  assert.deepEqual([...JEDAR_VOICES], ["maya", "noor", "ayaan"]);
});

test("local date string uses the device timezone, not UTC", () => {
  assert.equal(localDateString(new Date(2026, 0, 5, 0, 30)), "2026-01-05");
  assert.equal(localDateString(new Date(2026, 11, 31, 23, 59)), "2026-12-31");
  assert.match(formatTimestamp(new Date(2026, 8, 4, 9, 5).toISOString(), new Date(2026, 8, 4, 12, 0)), /^Today, /);
  assert.equal(formatTimestamp("not a date"), "");
});
