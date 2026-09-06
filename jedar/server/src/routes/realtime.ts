import { Router, type Request } from "express";
import { z } from "zod";
import { FAITHS, JEDAR_VOICES, MODES } from "../domain.js";
import { ContentRepository, ID_PATTERN } from "../content.js";
import { buildInstructions } from "../instructions.js";
import { toOpenAIVoice } from "../voices.js";
import { OpenAIError, type OpenAIGateway } from "../openai.js";
import { safetyIdentifier } from "../safety.js";
import type { Env } from "../env.js";
import { log } from "../logger.js";

/**
 * Selections travel as headers because the body is the raw SDP offer
 * (Content-Type: application/sdp). Every value is validated; the client can
 * never supply instructions or reflection text, only a reflection ID that is
 * resolved against curated content on the server.
 */
export const realtimeSelectionSchema = z.object({
  faith: z.enum(FAITHS),
  mode: z.enum(MODES),
  voice: z.enum(JEDAR_VOICES),
  reflectionId: z.string().regex(ID_PATTERN).optional(),
});

export function readSelection(req: Request) {
  const header = (name: string) => {
    const v = req.header(name);
    return v === undefined || v === "" ? undefined : v;
  };
  return realtimeSelectionSchema.safeParse({
    faith: header("x-jedar-faith"),
    mode: header("x-jedar-mode"),
    voice: header("x-jedar-voice"),
    reflectionId: header("x-jedar-reflection"),
  });
}

export function isSdpOffer(body: unknown): body is string {
  return typeof body === "string" && body.length > 20 && body.length < 64_000 && /^v=0\r?\n/.test(body) && /m=audio/.test(body);
}

export function realtimeRouter(env: Env, content: ContentRepository, gateway: OpenAIGateway): Router {
  const router = Router();

  router.post("/session", async (req, res) => {
    if (!req.is("application/sdp") || !isSdpOffer(req.body)) {
      res.status(400).json({ error: "Expected an SDP offer with Content-Type: application/sdp" });
      return;
    }
    const selection = readSelection(req);
    if (!selection.success) {
      res.status(400).json({ error: "Invalid faith, mode, voice or reflection" });
      return;
    }
    const { faith, mode, voice, reflectionId } = selection.data;
    const reflection = reflectionId ? content.get(reflectionId) : undefined;
    if (reflectionId && !reflection) {
      res.status(404).json({ error: "Reflection not found" });
      return;
    }
    if (reflection && reflection.faith !== faith) {
      res.status(400).json({ error: "Reflection does not belong to the selected faith" });
      return;
    }

    const instructions = buildInstructions({ faith, mode, reflection, channel: "voice" });
    const safetyId = safetyIdentifier(req.header("x-jedar-install"), env.SAFETY_ID_SALT);

    try {
      const answer = await gateway.createRealtimeCall(
        req.body,
        {
          model: env.OPENAI_REALTIME_MODEL,
          instructions,
          voice: toOpenAIVoice(voice),
          transcriptionModel: env.OPENAI_TRANSCRIPTION_MODEL,
        },
        safetyId,
      );
      res.status(201).type("application/sdp").send(answer);
    } catch (err) {
      const status = err instanceof OpenAIError && err.status === 503 ? 503 : 502;
      log.error("realtime.session.failed", { status, message: err instanceof Error ? err.message : "unknown" });
      res.status(status).json({ error: "Could not start a voice session right now" });
    }
  });

  return router;
}
