import { test } from "node:test";
import assert from "node:assert/strict";
import { INITIAL_STATE, STATUS_LABELS, parseServerEvent, reduceSession, type SessionState } from "../src/lib/realtimeEvents.js";

function run(actions: Parameters<typeof reduceSession>[1][], from: SessionState = INITIAL_STATE): SessionState {
  return actions.reduce(reduceSession, from);
}

test("status labels match the product copy", () => {
  assert.deepEqual(STATUS_LABELS, {
    idle: "Ready when you are",
    connecting: "Connecting",
    listening: "Listening",
    reflecting: "Reflecting",
    speaking: "Speaking",
    paused: "Connection paused",
  });
});

test("a full voice turn moves through connecting, listening, reflecting, speaking and back", () => {
  let s = run([{ kind: "start" }]);
  assert.equal(s.status, "connecting");
  s = run([{ kind: "server", event: { type: "session.created" } }], s);
  assert.equal(s.status, "listening");
  assert.equal(s.connected, true);
  s = run([{ kind: "server", event: { type: "input_audio_buffer.speech_started" } }], s);
  assert.equal(s.status, "listening");
  s = run([{ kind: "server", event: { type: "input_audio_buffer.speech_stopped" } }], s);
  assert.equal(s.status, "reflecting");
  s = run([{ kind: "server", event: { type: "conversation.item.input_audio_transcription.completed", item_id: "u1", transcript: " I feel restless. " } }], s);
  assert.deepEqual(s.transcript, [{ id: "u1", role: "user", text: "I feel restless.", final: true, source: "voice" }]);
  s = run(
    [
      { kind: "server", event: { type: "response.output_audio_transcript.delta", item_id: "a1", delta: "That sounds " } },
      { kind: "server", event: { type: "response.output_audio_transcript.delta", item_id: "a1", delta: "heavy." } },
    ],
    s,
  );
  assert.equal(s.status, "speaking");
  assert.equal(s.transcript[1]?.text, "That sounds heavy.");
  assert.equal(s.transcript[1]?.final, false);
  s = run([{ kind: "server", event: { type: "response.output_audio_transcript.done", item_id: "a1", transcript: "That sounds heavy. Shall we breathe?" } }], s);
  assert.equal(s.transcript[1]?.text, "That sounds heavy. Shall we breathe?");
  assert.equal(s.transcript[1]?.final, true);
  s = run([{ kind: "server", event: { type: "response.done" } }], s);
  assert.equal(s.status, "listening");
  s = run([{ kind: "end" }], s);
  assert.equal(s.status, "idle");
  assert.equal(s.transcript.length, 2, "transcript survives session end until cleared");
  assert.equal(run([{ kind: "clear" }], s).transcript.length, 0);
});

test("disconnection pauses, reconnection resumes, failure surfaces an error", () => {
  let s = run([{ kind: "start" }, { kind: "connected" }]);
  s = run([{ kind: "connection", state: "disconnected" }], s);
  assert.equal(s.status, "paused");
  s = run([{ kind: "connection", state: "connected" }], s);
  assert.equal(s.status, "listening");
  s = run([{ kind: "error", message: "lost" }], s);
  assert.equal(s.status, "paused");
  assert.equal(s.error, "lost");
  s = run([{ kind: "connection", state: "closed" }], s);
  assert.equal(s.status, "idle");
});

test("server error events are recorded without dropping the transcript", () => {
  let s = run([{ kind: "start" }, { kind: "connected" }, { kind: "text.user", id: "t1", text: "hi" }]);
  s = run([{ kind: "server", event: { type: "error", error: { message: "rate limited" } } }], s);
  assert.equal(s.error, "rate limited");
  assert.equal(s.transcript.length, 1);
});

test("text fallback entries are appended in order and empty transcripts are ignored", () => {
  const s = run([
    { kind: "text.user", id: "t1", text: "Hello" },
    { kind: "text.assistant", id: "t1-reply", text: "Hi there" },
    { kind: "server", event: { type: "conversation.item.input_audio_transcription.completed", item_id: "u9", transcript: "   " } },
  ]);
  assert.deepEqual(s.transcript.map((e) => [e.role, e.text, e.source]), [
    ["user", "Hello", "text"],
    ["assistant", "Hi there", "text"],
  ]);
});

test("parseServerEvent ignores malformed messages", () => {
  assert.equal(parseServerEvent(undefined), null);
  assert.equal(parseServerEvent("{"), null);
  assert.equal(parseServerEvent(JSON.stringify({ no: "type" })), null);
  assert.deepEqual(parseServerEvent(JSON.stringify({ type: "response.done" })), { type: "response.done" });
});
