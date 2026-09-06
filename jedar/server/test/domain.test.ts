import { test } from "node:test";
import assert from "node:assert/strict";
import { FAITHS, FAITH_LABELS, isFaith, JEDAR_VOICES, MODES } from "../src/domain.js";
import { toOpenAIVoice } from "../src/voices.js";

test("exactly five faiths, in product order, with no generic option", () => {
  assert.deepEqual([...FAITHS], ["sikh", "muslim", "christian", "hindu", "jewish"]);
  assert.equal(FAITHS.length, 5);
  assert.ok(!(FAITHS as readonly string[]).includes("spiritual"));
  for (const f of FAITHS) assert.ok(isFaith(f), `${f} should be a faith`);
  assert.ok(!isFaith("spiritual"));
  assert.ok(!isFaith(""));
  assert.ok(!isFaith(42));
});

test("every faith has a display label", () => {
  for (const f of FAITHS) assert.match(FAITH_LABELS[f], /^[A-Z][a-z]+$/);
});

test("modes and voices are the product set", () => {
  assert.deepEqual([...MODES], ["calm", "prayer", "guidance", "journal", "learn"]);
  assert.deepEqual([...JEDAR_VOICES], ["maya", "noor", "ayaan"]);
});

test("product voices map to distinct OpenAI voices and never leak product names", () => {
  const ids = JEDAR_VOICES.map(toOpenAIVoice);
  assert.equal(new Set(ids).size, 3);
  for (const id of ids) assert.ok(!(JEDAR_VOICES as readonly string[]).includes(id));
});
