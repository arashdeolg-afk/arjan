import { test } from "node:test";
import assert from "node:assert/strict";
import { buildInstructions } from "../src/instructions.js";
import { FAITHS, MODES } from "../src/domain.js";
import { ContentRepository } from "../src/content.js";

const repo = ContentRepository.fromFile();

test("authority boundaries are present for every faith and mode", () => {
  for (const faith of FAITHS) {
    for (const mode of MODES) {
      const text = buildInstructions({ faith, mode, channel: "voice" });
      for (const role of ["deity", "prophet", "guru", "priest", "imam", "pastor", "rabbi", "therapist", "doctor", "lawyer", "religious authority"]) {
        assert.ok(text.includes(role), `${faith}/${mode} must disclaim being a ${role}`);
      }
      assert.match(text, /two to five short sentences/);
      assert.match(text, /no more than one question at a time/);
      assert.match(text, /Never fabricate scripture, quotations/);
      assert.match(text, /qualified clergy or scholars/);
      assert.match(text, /emergency services/);
      assert.match(text, /Never shame, pressure, preach/);
      assert.match(text, /agency/);
      assert.match(text, /without assuming every follower believes the same thing/);
    }
  }
});

test("faith-specific guidance is included and only for the selected faith", () => {
  const expectations: Record<string, RegExp[]> = {
    sikh: [/seva/, /chardi kala/, /Gurbani/, /ang numbers/],
    muslim: [/mercy/, /sabr/, /Quran/, /hadith/, /Arabic/],
    christian: [/grace/, /forgiveness/, /Bible verses/, /doctrine/],
    hindu: [/dharma/, /ahimsa/, /Sanskrit/, /diversity/],
    jewish: [/tikkun olam/, /Torah/, /Talmud/, /Hebrew/, /halakhic/],
  };
  for (const faith of FAITHS) {
    const text = buildInstructions({ faith, mode: "guidance", channel: "text" });
    for (const re of expectations[faith]!) assert.match(text, re, `${faith} should mention ${re}`);
    for (const other of FAITHS) {
      if (other === faith) continue;
      assert.ok(!text.includes(`identifies as ${other[0]!.toUpperCase()}${other.slice(1)}`), `${faith} instructions leak ${other}`);
    }
  }
});

test("reflection context is embedded as an opening topic that never masquerades as scripture", () => {
  const reflection = repo.get("christian-001")!;
  const text = buildInstructions({ faith: "christian", mode: "calm", reflection, channel: "voice" });
  assert.ok(text.includes(reflection.title));
  assert.ok(text.includes(reflection.body));
  assert.match(text, /not scripture/);
  assert.match(text, /first let the person speak naturally/);
});

test("channel wording differs between voice and text", () => {
  const voice = buildInstructions({ faith: "hindu", mode: "learn", channel: "voice" });
  const text = buildInstructions({ faith: "hindu", mode: "learn", channel: "text" });
  assert.match(voice, /live voice conversation/);
  assert.match(text, /fallback composer/);
  assert.notEqual(voice, text);
});
