import { z } from "zod";

const envSchema = z.object({
  OPENAI_API_KEY: z.string().trim().min(1).optional(),
  PORT: z.coerce.number().int().min(1).max(65535).default(8787),
  OPENAI_REALTIME_MODEL: z.string().trim().min(1).default("gpt-realtime-2.1"),
  OPENAI_TEXT_MODEL: z.string().trim().min(1).default("gpt-5-mini"),
  OPENAI_TRANSCRIPTION_MODEL: z.string().trim().min(1).default("gpt-4o-mini-transcribe"),
  CORS_ORIGIN: z.string().trim().default("http://localhost:8081"),
  SAFETY_ID_SALT: z.string().trim().min(16, "SAFETY_ID_SALT must be at least 16 characters"),
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  OPENAI_BASE_URL: z.string().url().default("https://api.openai.com/v1"),
});

export type Env = z.infer<typeof envSchema> & { corsOrigins: string[] };

/**
 * Validate process.env (or any record) into a typed config. Throws with a readable
 * message listing every problem so misconfiguration fails fast at boot.
 */
export function loadEnv(source: NodeJS.ProcessEnv = process.env): Env {
  const parsed = envSchema.safeParse(source);
  if (!parsed.success) {
    const issues = parsed.error.issues.map((i) => `${i.path.join(".") || "env"}: ${i.message}`);
    throw new Error(`Invalid environment:\n  ${issues.join("\n  ")}`);
  }
  const env = parsed.data;
  if (env.NODE_ENV === "production" && !env.OPENAI_API_KEY) {
    throw new Error("Invalid environment:\n  OPENAI_API_KEY is required in production");
  }
  if (env.OPENAI_API_KEY && /^sk-server-only$/i.test(env.OPENAI_API_KEY)) {
    throw new Error("Invalid environment:\n  OPENAI_API_KEY still has the placeholder value from .env.example");
  }
  if (env.NODE_ENV === "production" && env.SAFETY_ID_SALT === "replace-with-a-long-random-value") {
    throw new Error("Invalid environment:\n  SAFETY_ID_SALT still has the placeholder value from .env.example");
  }
  const corsOrigins = env.CORS_ORIGIN.split(",").map((s) => s.trim()).filter(Boolean);
  return { ...env, corsOrigins };
}

/** Tiny .env loader (stdlib only). Existing process.env values always win. */
export async function loadDotEnv(path = ".env"): Promise<void> {
  const fs = await import("node:fs/promises");
  let text: string;
  try {
    text = await fs.readFile(path, "utf8");
  } catch {
    return;
  }
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}
