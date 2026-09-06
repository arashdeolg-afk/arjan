/**
 * Minimal structured logger. Callers must never pass secrets, transcripts,
 * or journal content; the redact() helper strips anything that looks like a key.
 */
const SECRET_PATTERN = /\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]+)/g;

export function redact(value: unknown): unknown {
  if (typeof value === "string") return value.replace(SECRET_PATTERN, "[redacted]");
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (/key|secret|token|authorization|password|salt/i.test(k)) out[k] = "[redacted]";
      else out[k] = redact(v);
    }
    return out;
  }
  return value;
}

type Level = "info" | "warn" | "error";

function write(level: Level, event: string, fields: Record<string, unknown> = {}): void {
  if (process.env.NODE_ENV === "test" && !process.env.JEDAR_TEST_LOGS) return;
  const line = JSON.stringify({ ts: new Date().toISOString(), level, event, ...(redact(fields) as object) });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

export const log = {
  info: (event: string, fields?: Record<string, unknown>) => write("info", event, fields),
  warn: (event: string, fields?: Record<string, unknown>) => write("warn", event, fields),
  error: (event: string, fields?: Record<string, unknown>) => write("error", event, fields),
};
