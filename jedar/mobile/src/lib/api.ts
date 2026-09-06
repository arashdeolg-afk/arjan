import type { Faith, JedarVoice, Mode, PublicReflection } from "./domain.js";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export function resolveApiUrl(env: { EXPO_PUBLIC_API_URL?: string | undefined }): string {
  const raw = (env.EXPO_PUBLIC_API_URL ?? "").trim();
  if (!raw) return "http://localhost:8787";
  return raw.replace(/\/+$/, "");
}

export const API_URL = resolveApiUrl(process.env as { EXPO_PUBLIC_API_URL?: string });

export type VoiceSelection = { faith: Faith; mode: Mode; voice: JedarVoice; reflectionId?: string | undefined };

/** Headers carrying the user's selections next to a raw SDP body. */
export function buildSelectionHeaders(selection: VoiceSelection, installId: string): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/sdp",
    "X-Jedar-Faith": selection.faith,
    "X-Jedar-Mode": selection.mode,
    "X-Jedar-Voice": selection.voice,
    "X-Jedar-Install": installId,
  };
  if (selection.reflectionId) headers["X-Jedar-Reflection"] = selection.reflectionId;
  return headers;
}

async function readError(res: Response): Promise<string> {
  try {
    const json = (await res.json()) as { error?: string };
    return json.error ?? `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

function withTimeout(ms: number): { signal: AbortSignal; clear: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

export async function fetchTodayReflection(faith: Faith, date: string, installId: string): Promise<{ date: string; reflection: PublicReflection }> {
  const t = withTimeout(10_000);
  try {
    const res = await fetch(`${API_URL}/api/reflections/today?faith=${encodeURIComponent(faith)}&date=${encodeURIComponent(date)}`, {
      headers: { "X-Jedar-Install": installId },
      signal: t.signal,
    });
    if (!res.ok) throw new ApiError(await readError(res), res.status);
    return (await res.json()) as { date: string; reflection: PublicReflection };
  } finally {
    t.clear();
  }
}

export async function fetchReflection(id: string, installId: string): Promise<PublicReflection> {
  const t = withTimeout(10_000);
  try {
    const res = await fetch(`${API_URL}/api/reflections/${encodeURIComponent(id)}`, { headers: { "X-Jedar-Install": installId }, signal: t.signal });
    if (!res.ok) throw new ApiError(await readError(res), res.status);
    return ((await res.json()) as { reflection: PublicReflection }).reflection;
  } finally {
    t.clear();
  }
}

export type TextTurn = { role: "user" | "assistant"; content: string };

export async function sendTextMessage(
  input: { message: string; faith: Faith; mode: Mode; reflectionId?: string | undefined; history: TextTurn[] },
  installId: string,
): Promise<string> {
  const t = withTimeout(45_000);
  try {
    const res = await fetch(`${API_URL}/api/text`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jedar-Install": installId },
      body: JSON.stringify({ ...input, history: input.history.slice(-20) }),
      signal: t.signal,
    });
    if (!res.ok) throw new ApiError(await readError(res), res.status);
    return ((await res.json()) as { text: string }).text;
  } finally {
    t.clear();
  }
}

/** Exchange an SDP offer for the answer SDP via the Jedar server (never OpenAI directly). */
export async function createRealtimeSession(offerSdp: string, selection: VoiceSelection, installId: string): Promise<string> {
  const t = withTimeout(20_000);
  try {
    const res = await fetch(`${API_URL}/api/realtime/session`, {
      method: "POST",
      headers: buildSelectionHeaders(selection, installId),
      body: offerSdp,
      signal: t.signal,
    });
    if (!res.ok) throw new ApiError(await readError(res), res.status);
    return await res.text();
  } finally {
    t.clear();
  }
}

export async function checkServer(): Promise<{ ok: boolean; voice: boolean }> {
  const t = withTimeout(5_000);
  try {
    const res = await fetch(`${API_URL}/health`, { signal: t.signal });
    if (!res.ok) return { ok: false, voice: false };
    return (await res.json()) as { ok: boolean; voice: boolean };
  } catch {
    return { ok: false, voice: false };
  } finally {
    t.clear();
  }
}
