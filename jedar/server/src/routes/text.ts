import { Router } from "express";
import { z } from "zod";
import { FAITHS, MODES } from "../domain.js";
import { ContentRepository, ID_PATTERN } from "../content.js";
import { buildInstructions } from "../instructions.js";
import { type OpenAIGateway } from "../openai.js";
import { safetyIdentifier } from "../safety.js";
import type { Env } from "../env.js";
import { log } from "../logger.js";

export const MAX_MESSAGE_CHARS = 2000;
export const MAX_HISTORY_TURNS = 20;

export const textRequestSchema = z.object({
  message: z.string().trim().min(1).max(MAX_MESSAGE_CHARS),
  faith: z.enum(FAITHS),
  mode: z.enum(MODES).default("guidance"),
  reflectionId: z.string().regex(ID_PATTERN).optional(),
  history: z
    .array(
      z.object({
        role: z.enum(["user", "assistant"]),
        content: z.string().trim().min(1).max(MAX_MESSAGE_CHARS),
      }),
    )
    .max(MAX_HISTORY_TURNS)
    .default([]),
});

export function textRouter(env: Env, content: ContentRepository, gateway: OpenAIGateway): Router {
  const router = Router();

  router.post("/", async (req, res) => {
    const parsed = textRequestSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: "Invalid request" });
      return;
    }
    const { message, faith, mode, reflectionId, history } = parsed.data;
    const reflection = reflectionId ? content.get(reflectionId) : undefined;
    if (reflectionId && !reflection) {
      res.status(404).json({ error: "Reflection not found" });
      return;
    }
    if (reflection && reflection.faith !== faith) {
      res.status(400).json({ error: "Reflection does not belong to the selected faith" });
      return;
    }
    const instructions = buildInstructions({ faith, mode, reflection, channel: "text" });
    const safetyId = safetyIdentifier(req.header("x-jedar-install"), env.SAFETY_ID_SALT);
    try {
      const text = await gateway.createTextResponse(instructions, [...history, { role: "user", content: message }], safetyId);
      res.json({ text });
    } catch (err) {
      log.error("text.failed", { message: err instanceof Error ? err.message : "unknown" });
      res.status(502).json({ error: "Jedar could not reply right now" });
    }
  });

  return router;
}
