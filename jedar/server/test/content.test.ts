import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ContentRepository,
  ContentValidationError,
  displayLabel,
  isEligible,
  isValidLocalDate,
  normalizeItem,
  parseContent,
  toPublic,
  type DailyContent,
} from "../src/content.js";
import { FAITHS } from "../src/domain.js";

const repo = ContentRepository.fromFile();

test("sample content contains original reflections for all five faiths and no scripture", () => {
  for (const faith of FAITHS) {
    const pool = repo.forFaith(faith);
    assert.ok(pool.length >= 2, `${faith} needs at least two reflections`);
    for (const item of pool) {
      assert.equal(item.type, "reflection");
      assert.equal(displayLabel(item), "Reflection");
      assert.equal(item.sourceName, undefined);
      assert.equal(item.reference, undefined);
    }
  }
});

test("daily selection is deterministic for faith + date and varies across days", () => {
  for (const faith of FAITHS) {
    const a = repo.today(faith, "2026-09-04");
    const b = repo.today(faith, "2026-09-04");
    assert.ok(a);
    assert.equal(a.id, b?.id);
    assert.equal(a.faith, faith);
  }
  const seen = new Set<string>();
  for (let d = 1; d <= 28; d++) {
    seen.add(repo.today("sikh", `2026-02-${String(d).padStart(2, "0")}`)!.id);
  }
  assert.ok(seen.size > 1, "a month of dates should cover more than one reflection");
});

test("selection differs between faiths on the same date", () => {
  const ids = FAITHS.map((f) => repo.today(f, "2026-09-04")!.faith);
  assert.deepEqual(ids, [...FAITHS]);
});

test("unapproved scripture is downgraded to a Reflection with no citation", () => {
  const item = normalizeItem({
    id: "sikh-x1",
    faith: "sikh",
    type: "scripture",
    title: "T",
    body: "B",
    approved: false,
    sourceName: "Some source",
    reference: "1:1",
  });
  assert.equal(item.type, "reflection");
  assert.equal(displayLabel(item), "Reflection");
  assert.equal(item.sourceName, undefined);
  assert.equal(item.reference, undefined);
  assert.equal(toPublic(item).label, "Reflection");
  assert.ok(!("sourceName" in toPublic(item)));
});

test("unapproved reflection is always labelled Reflection", () => {
  const item: DailyContent = { id: "hindu-z", faith: "hindu", type: "reflection", title: "T", body: "B", approved: false };
  assert.equal(displayLabel(item), "Reflection");
  assert.equal(toPublic(item).label, "Reflection");
  assert.equal(toPublic(item).type, "reflection");
});

test("approved scripture requires source, reference and reviewer", () => {
  const base = { id: "jewish-s1", faith: "jewish" as const, type: "scripture" as const, title: "T", body: "B", approved: true };
  assert.throws(() => normalizeItem({ ...base }), ContentValidationError);
  assert.throws(() => normalizeItem({ ...base, sourceName: "S", reference: "R" }), ContentValidationError);
  assert.throws(() => normalizeItem({ ...base, sourceName: "S", reviewedBy: "Rabbi X" }), ContentValidationError);
  const ok = normalizeItem({ ...base, sourceName: "S", reference: "R", reviewedBy: "Rabbi X" });
  assert.equal(ok.type, "scripture");
  assert.equal(displayLabel(ok), "Scripture");
  assert.ok(isEligible(ok));
  const pub = toPublic(ok);
  assert.equal(pub.label, "Scripture");
  assert.equal(pub.sourceName, "S");
  assert.equal(pub.reference, "R");
  assert.equal(pub.reviewedBy, "Rabbi X");
});

test("a plain reflection may not carry a citation (would look like scripture)", () => {
  assert.throws(
    () => normalizeItem({ id: "muslim-c1", faith: "muslim", type: "reflection", title: "T", body: "B", approved: true, sourceName: "S" }),
    ContentValidationError,
  );
});

test("parseContent rejects malformed files and duplicate ids", () => {
  assert.throws(() => parseContent({ version: 2, items: [] }), ContentValidationError);
  assert.throws(() => parseContent({ version: 1, items: [] }), ContentValidationError);
  const item = { id: "sikh-d1", faith: "sikh", type: "reflection", title: "T", body: "B", approved: false };
  assert.throws(() => parseContent({ version: 1, items: [item, item] }), /Duplicate/);
  assert.throws(() => parseContent({ version: 1, items: [{ ...item, faith: "spiritual" }] }), ContentValidationError);
});

test("invalid reflection ids are rejected without lookup", () => {
  assert.equal(repo.get("nope"), undefined);
  assert.equal(repo.get("../etc/passwd"), undefined);
  assert.equal(repo.get("sikh-999"), undefined);
  assert.equal(repo.get(""), undefined);
  assert.equal(repo.get("SIKH-001"), undefined);
  assert.ok(repo.get("sikh-001"));
});

test("local date validation", () => {
  assert.ok(isValidLocalDate("2026-02-28"));
  assert.ok(isValidLocalDate("2028-02-29"));
  assert.ok(!isValidLocalDate("2026-02-30"));
  assert.ok(!isValidLocalDate("2026-13-01"));
  assert.ok(!isValidLocalDate("26-1-1"));
  assert.ok(!isValidLocalDate("2026-09-04T00:00"));
});
