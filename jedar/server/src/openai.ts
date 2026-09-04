import type { Env } from "./env.js";
import { log } from "./logger.js";

/**
 * Thin OpenAI client using global fetch. Only the server ever holds the key.
 * Every call logs the x-request-id header (and nothing else sensitive) so
 * problems can be traced with OpenAI support without exposing content.
 */
export class OpenAIError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly requestId: string | null,
  ) {
    super(message);
  }
}

export type RealtimeSessionConfig = {
  model: string;
  instructions: string;
  voice: string;
  transcriptionModel: string;
};

export type TextTurn = { role: "user" | "assistant"; content: string };

export interface OpenAIGateway {
  createRealtimeCall(offerSdp: string, config: RealtimeSessionConfig, safetyIdentifier: string): Promise<string>;
  createTextResponse(
    instructions: string,
    turns: TextTurn[],
    safetyIdentifier: string,
  ): Promise<string>;
}

export class OpenAIClient implements OpenAIGateway {
  constructor(private readonly env: Env) {}

  private headers(): Record<string, string> {
    return { Authorization: `Bearer ${this.env.OPENAI_API_KEY ?? ""}` };
  }

  /**
   * Unified WebRTC flow: POST the SDP offer plus a session config to
   * /v1/realtime/calls and return the SDP answer. See:
   * https://platform.openai.com/docs/guides/realtime-webrtc
   */
  async createRealtimeCall(offerSdp: string, config: RealtimeSessionConfig, safetyIdentifier: string): Promise<string> {
    const session = {
      type: "realtime",
      model: config.model,
      instructions: config.instructions,
      output_modalities: ["audio"],
      audio: {
        input: {
          transcription: { model: config.transcriptionModel },
          turn_detection: { type: "semantic_vad", create_response: true, interrupt_response: true },
        },
        output: { voice: config.voice },
      },
      safety_identifier: safetyIdentifier,
    };
    const form = new FormData();
    form.set("sdp", offerSdp);
    form.set("session", JSON.stringify(session));

    const res = await fetch(`${this.env.OPENAI_BASE_URL}/realtime/calls`, {
      method: "POST",
      headers: this.headers(),
      body: form,
    });
    const requestId = res.headers.get("x-request-id");
    const callId = res.headers.get("location");
    log.info("openai.realtime.call", { status: res.status, requestId, callId, model: config.model });
    const body = await res.text();
    if (!res.ok) {
      log.error("openai.realtime.error", { status: res.status, requestId, body: body.slice(0, 300) });
      throw new OpenAIError("Realtime call failed", res.status, requestId);
    }
    return body;
  }

  /** Responses API text turn used by the fallback composer. */
  async createTextResponse(instructions: string, turns: TextTurn[], safetyIdentifier: string): Promise<string> {
    const res = await fetch(`${this.env.OPENAI_BASE_URL}/responses`, {
      method: "POST",
      headers: { ...this.headers(), "Content-Type": "application/json" },
      body: JSON.stringify({
        model: this.env.OPENAI_TEXT_MODEL,
        instructions,
        input: turns.map((t) => ({ role: t.role, content: t.content })),
        max_output_tokens: 400,
        store: false,
        safety_identifier: safetyIdentifier,
      }),
    });
    const requestId = res.headers.get("x-request-id");
    log.info("openai.responses", { status: res.status, requestId, model: this.env.OPENAI_TEXT_MODEL });
    if (!res.ok) {
      const body = await res.text();
      log.error("openai.responses.error", { status: res.status, requestId, body: body.slice(0, 300) });
      throw new OpenAIError("Text response failed", res.status, requestId);
    }
    const json = (await res.json()) as ResponsesPayload;
    const text = extractOutputText(json);
    if (!text) throw new OpenAIError("Text response was empty", 502, requestId);
    return text;
  }
}

type ResponsesPayload = {
  output_text?: string;
  output?: Array<{ type?: string; content?: Array<{ type?: string; text?: string }> }>;
};

export function extractOutputText(payload: ResponsesPayload): string {
  if (typeof payload.output_text === "string" && payload.output_text.trim()) return payload.output_text.trim();
  const chunks: string[] = [];
  for (const item of payload.output ?? []) {
    if (item.type !== "message") continue;
    for (const part of item.content ?? []) {
      if (part.type === "output_text" && part.text) chunks.push(part.text);
    }
  }
  return chunks.join("").trim();
}

/**
 * Used only when no OPENAI_API_KEY is configured outside production so the app
 * can be exercised end to end (text path) without spending money. It is
 * deliberately generic and never pretends to be scripture.
 */
export class OfflineGateway implements OpenAIGateway {
  async createRealtimeCall(): Promise<string> {
    throw new OpenAIError("Realtime voice needs OPENAI_API_KEY on the server", 503, null);
  }
  async createTextResponse(_instructions: string, turns: TextTurn[]): Promise<string> {
    const last = turns[turns.length - 1]?.content ?? "";
    return `Thank you for sharing that. I'm running without a language model right now, so I can only listen and reflect it back: "${last.slice(0, 120)}". When the server has an API key, I'll be able to respond properly. Is there one small part of this you'd like to sit with for a moment?`;
  }
}
