import type { AddressInfo } from "node:net";
import { createApp } from "../src/app.js";
import { loadEnv, type Env } from "../src/env.js";
import { ContentRepository } from "../src/content.js";
import type { OpenAIGateway, RealtimeSessionConfig, TextTurn } from "../src/openai.js";

export function testEnv(overrides: Record<string, string> = {}): Env {
  return loadEnv({
    NODE_ENV: "test",
    SAFETY_ID_SALT: "unit-test-salt-that-is-long-enough",
    CORS_ORIGIN: "http://localhost:8081",
    ...overrides,
  });
}

export class FakeGateway implements OpenAIGateway {
  realtimeCalls: Array<{ sdp: string; config: RealtimeSessionConfig; safetyId: string }> = [];
  textCalls: Array<{ instructions: string; turns: TextTurn[]; safetyId: string }> = [];
  failNext = false;

  async createRealtimeCall(sdp: string, config: RealtimeSessionConfig, safetyId: string): Promise<string> {
    if (this.failNext) {
      this.failNext = false;
      throw new Error("upstream down");
    }
    this.realtimeCalls.push({ sdp, config, safetyId });
    return "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n";
  }

  async createTextResponse(instructions: string, turns: TextTurn[], safetyId: string): Promise<string> {
    if (this.failNext) {
      this.failNext = false;
      throw new Error("upstream down");
    }
    this.textCalls.push({ instructions, turns, safetyId });
    return "A short, warm reply.";
  }
}

export async function startServer(gateway = new FakeGateway(), content?: ContentRepository) {
  const env = testEnv();
  const app = createApp({ env, gateway, ...(content ? { content } : {}) });
  const server = await new Promise<import("node:http").Server>((resolve) => {
    const s = app.listen(0, "127.0.0.1", () => resolve(s));
  });
  const { port } = server.address() as AddressInfo;
  const base = `http://127.0.0.1:${port}`;
  return {
    base,
    gateway,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

export const SAMPLE_OFFER = "v=0\r\no=- 46 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n";
