/**
 * Pure state machine for a Jedar voice session. Realtime server events and
 * connection changes are reduced into a status plus a transcript. No WebRTC
 * imports so it can be unit tested.
 */
export type VoiceStatus = "idle" | "connecting" | "listening" | "reflecting" | "speaking" | "paused";

export const STATUS_LABELS: Record<VoiceStatus, string> = {
  idle: "Ready when you are",
  connecting: "Connecting",
  listening: "Listening",
  reflecting: "Reflecting",
  speaking: "Speaking",
  paused: "Connection paused",
};

export type TranscriptEntry = {
  id: string;
  role: "user" | "assistant";
  text: string;
  final: boolean;
  source: "voice" | "text";
};

export type SessionState = {
  status: VoiceStatus;
  transcript: TranscriptEntry[];
  error: string | null;
  connected: boolean;
};

export const INITIAL_STATE: SessionState = { status: "idle", transcript: [], error: null, connected: false };

export type RealtimeEvent = {
  type: string;
  event_id?: string;
  item_id?: string;
  response_id?: string;
  transcript?: string;
  delta?: string;
  error?: { message?: string; code?: string };
  response?: { status?: string };
};

export type SessionAction =
  | { kind: "start" }
  | { kind: "connected" }
  | { kind: "connection", state: "connected" | "disconnected" | "failed" | "closed" | "connecting" | "new" }
  | { kind: "server", event: RealtimeEvent }
  | { kind: "text.user", id: string; text: string }
  | { kind: "text.assistant", id: string; text: string }
  | { kind: "error", message: string }
  | { kind: "end" }
  | { kind: "clear" };

const MAX_TRANSCRIPT = 200;

function upsert(list: TranscriptEntry[], entry: TranscriptEntry, append: boolean): TranscriptEntry[] {
  const idx = list.findIndex((e) => e.id === entry.id);
  if (idx === -1) return [...list, entry].slice(-MAX_TRANSCRIPT);
  const existing = list[idx]!;
  const merged: TranscriptEntry = { ...existing, ...entry, text: append ? existing.text + entry.text : entry.text };
  return [...list.slice(0, idx), merged, ...list.slice(idx + 1)];
}

export function reduceSession(state: SessionState, action: SessionAction): SessionState {
  switch (action.kind) {
    case "start":
      return { ...state, status: "connecting", error: null };
    case "connected":
      return { ...state, status: "listening", connected: true, error: null };
    case "connection":
      if (action.state === "connected") return state.connected ? state : { ...state, status: "listening", connected: true };
      if (action.state === "disconnected" || action.state === "failed") return { ...state, status: "paused", connected: false };
      if (action.state === "closed") return { ...state, status: "idle", connected: false };
      return state;
    case "server":
      return reduceServerEvent(state, action.event);
    case "text.user":
      return { ...state, transcript: upsert(state.transcript, { id: action.id, role: "user", text: action.text, final: true, source: "text" }, false) };
    case "text.assistant":
      return { ...state, transcript: upsert(state.transcript, { id: action.id, role: "assistant", text: action.text, final: true, source: "text" }, false) };
    case "error":
      return { ...state, status: state.connected ? "paused" : "idle", error: action.message };
    case "end":
      return { ...state, status: "idle", connected: false };
    case "clear":
      return { ...INITIAL_STATE };
    default:
      return state;
  }
}

function reduceServerEvent(state: SessionState, event: RealtimeEvent): SessionState {
  switch (event.type) {
    case "session.created":
    case "session.updated":
      return { ...state, status: state.status === "connecting" ? "listening" : state.status, connected: true, error: null };
    case "input_audio_buffer.speech_started":
      return { ...state, status: "listening" };
    case "input_audio_buffer.speech_stopped":
      return { ...state, status: "reflecting" };
    case "conversation.item.input_audio_transcription.completed": {
      const text = (event.transcript ?? "").trim();
      if (!text) return state;
      return { ...state, transcript: upsert(state.transcript, { id: event.item_id ?? `user-${event.event_id}`, role: "user", text, final: true, source: "voice" }, false) };
    }
    case "response.output_audio_transcript.delta":
    case "response.audio_transcript.delta": {
      const id = event.item_id ?? event.response_id ?? "assistant";
      return { ...state, status: "speaking", transcript: upsert(state.transcript, { id, role: "assistant", text: event.delta ?? "", final: false, source: "voice" }, true) };
    }
    case "response.output_audio_transcript.done":
    case "response.audio_transcript.done": {
      const id = event.item_id ?? event.response_id ?? "assistant";
      return { ...state, transcript: upsert(state.transcript, { id, role: "assistant", text: event.transcript ?? "", final: true, source: "voice" }, false) };
    }
    case "response.done":
      return { ...state, status: state.connected ? "listening" : state.status };
    case "error":
      return { ...state, status: state.connected ? "listening" : "paused", error: event.error?.message ?? "Something went wrong" };
    default:
      return state;
  }
}

/** Parse a data-channel message defensively; anything malformed is ignored. */
export function parseServerEvent(raw: unknown): RealtimeEvent | null {
  if (typeof raw !== "string") return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object" && typeof (parsed as { type?: unknown }).type === "string") return parsed as RealtimeEvent;
  } catch {
    // ignore
  }
  return null;
}
