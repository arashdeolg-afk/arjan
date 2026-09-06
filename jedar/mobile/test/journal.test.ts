import { test } from "node:test";
import assert from "node:assert/strict";
import { memoryDatabase } from "./sqliteAdapter.js";
import { migrate } from "../src/lib/schema.js";
import { JournalRepository, formatConversation } from "../src/lib/journal.js";
import { PreferencesStore } from "../src/lib/preferences.js";

async function setup() {
  const db = memoryDatabase();
  await migrate(db);
  await migrate(db); // idempotent
  let n = 0;
  let clock = 1_000;
  const journal = new JournalRepository(db, { id: () => `id-${++n}`, now: () => new Date(clock++ * 1000).toISOString() });
  return { db, journal };
}

test("create, get, list ordering and timestamps", async () => {
  const { journal } = await setup();
  const a = await journal.create({ type: "note", title: "  First  ", body: "Body one", faith: "sikh" });
  const b = await journal.create({ type: "reflection", title: "Second", body: "Body two", faith: "hindu", reflectionId: "hindu-001" });
  assert.equal(a.title, "First");
  assert.equal(a.createdAt, a.updatedAt);
  assert.equal(b.reflectionId, "hindu-001");
  assert.equal(a.reflectionId, undefined);
  const got = await journal.get(a.id);
  assert.deepEqual(got, a);
  const all = await journal.list();
  assert.deepEqual(all.map((e) => e.id), [b.id, a.id], "newest first");
  assert.equal(await journal.count(), 2);
});

test("filter by faith, type and search", async () => {
  const { journal } = await setup();
  await journal.create({ type: "note", title: "Morning", body: "grateful today", faith: "muslim" });
  await journal.create({ type: "conversation", title: "Talk", body: "You: hi", faith: "muslim" });
  await journal.create({ type: "note", title: "Evening", body: "quiet", faith: "jewish" });
  assert.equal((await journal.list({ faith: "muslim" })).length, 2);
  assert.equal((await journal.list({ faith: "muslim", type: "note" })).length, 1);
  assert.equal((await journal.list({ type: "conversation" })).length, 1);
  assert.equal((await journal.list({ query: "GRATEFUL" })).length, 1);
  assert.equal((await journal.list({ query: "%" })).length, 0, "LIKE wildcards are escaped");
  assert.equal((await journal.list({ query: "_" })).length, 0);
  assert.equal((await journal.list({ faith: "christian" })).length, 0);
});

test("update changes only title/body and bumps updatedAt", async () => {
  const { journal } = await setup();
  const a = await journal.create({ type: "note", title: "T", body: "B", faith: "christian" });
  const updated = await journal.update(a.id, { body: "B2" });
  assert.ok(updated);
  assert.equal(updated.title, "T");
  assert.equal(updated.body, "B2");
  assert.equal(updated.createdAt, a.createdAt);
  assert.notEqual(updated.updatedAt, a.updatedAt);
  assert.equal(await journal.update("missing", { title: "x" }), null);
  await assert.rejects(journal.update(a.id, { title: "   " }), /Title is required/);
});

test("delete one and delete all", async () => {
  const { journal } = await setup();
  const a = await journal.create({ type: "note", title: "T", body: "B", faith: "sikh" });
  await journal.create({ type: "note", title: "T2", body: "B2", faith: "sikh" });
  assert.equal(await journal.remove(a.id), true);
  assert.equal(await journal.remove(a.id), false);
  assert.equal(await journal.get(a.id), null);
  assert.equal(await journal.removeAll(), 1);
  assert.equal(await journal.count(), 0);
});

test("validation rejects empty, oversized, and unknown values", async () => {
  const { journal } = await setup();
  await assert.rejects(journal.create({ type: "note", title: "", body: "B", faith: "sikh" }), /Title/);
  await assert.rejects(journal.create({ type: "note", title: "T", body: " ", faith: "sikh" }), /Body/);
  await assert.rejects(journal.create({ type: "note", title: "x".repeat(121), body: "B", faith: "sikh" }), /120/);
  await assert.rejects(journal.create({ type: "note", title: "T", body: "B", faith: "spiritual" as never }), /faith/);
  await assert.rejects(journal.create({ type: "diary" as never, title: "T", body: "B", faith: "sikh" }), /entry type/);
});

test("findByReflection returns the saved reflection entry", async () => {
  const { journal } = await setup();
  assert.equal(await journal.findByReflection("sikh-001"), null);
  const e = await journal.create({ type: "reflection", title: "T", body: "B", faith: "sikh", reflectionId: "sikh-001" });
  assert.equal((await journal.findByReflection("sikh-001"))?.id, e.id);
});

test("formatConversation labels speakers and drops blanks", () => {
  const text = formatConversation([
    { role: "assistant", text: " Hello " },
    { role: "user", text: "" },
    { role: "user", text: "I feel tired" },
  ]);
  assert.equal(text, "Jedar: Hello\n\nYou: I feel tired");
});

test("preferences persist, validate and generate a stable install id", async () => {
  const { db } = await setup();
  let n = 0;
  const store = new PreferencesStore(db, () => `install-${++n}`);
  const first = await store.load();
  assert.equal(first.faith, null);
  assert.equal(first.voice, "maya");
  assert.equal(first.onboardingComplete, false);
  assert.equal(first.installId, "install-1");
  const saved = await store.save({ faith: "jewish", voice: "ayaan", onboardingComplete: true, reminderEnabled: true, reminderHour: 20, reminderMinute: 15 });
  assert.equal(saved.faith, "jewish");
  assert.equal(saved.reminderHour, 20);
  assert.equal(saved.installId, "install-1", "install id is stable");
  await db.runAsync(`UPDATE preferences SET value = ? WHERE key = 'faith'`, [JSON.stringify("spiritual")]);
  await db.runAsync(`UPDATE preferences SET value = ? WHERE key = 'reminderHour'`, [JSON.stringify(99)]);
  const reloaded = await store.load();
  assert.equal(reloaded.faith, null, "unknown faith falls back");
  assert.equal(reloaded.reminderHour, 23, "hour is clamped");
  const reset = await store.reset();
  assert.equal(reset.faith, null);
  assert.equal(reset.installId, "install-1");
});
