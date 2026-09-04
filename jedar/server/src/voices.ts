import type { JedarVoice } from "./domain.js";

/**
 * Product voices → OpenAI Realtime voices. The right-hand side never reaches the
 * client; the app only ever sees "maya", "noor" and "ayaan".
 */
const VOICE_MAP: Record<JedarVoice, string> = {
  maya: "marin", // Calm female
  noor: "shimmer", // Gentle female
  ayaan: "cedar", // Grounded male
};

export function toOpenAIVoice(voice: JedarVoice): string {
  return VOICE_MAP[voice];
}
