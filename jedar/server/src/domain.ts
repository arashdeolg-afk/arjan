/**
 * Shared Jedar domain values. The mobile app keeps an identical copy in
 * mobile/src/lib/domain.ts so both sides agree on exactly which strings are valid.
 */
export const FAITHS = ["sikh", "muslim", "christian", "hindu", "jewish"] as const;
export type Faith = (typeof FAITHS)[number];

export const MODES = ["calm", "prayer", "guidance", "journal", "learn"] as const;
export type Mode = (typeof MODES)[number];

/** Product voice names shown in the UI. Technical voice IDs never leave the server. */
export const JEDAR_VOICES = ["maya", "noor", "ayaan"] as const;
export type JedarVoice = (typeof JEDAR_VOICES)[number];

export const CONTENT_TYPES = ["reflection", "scripture"] as const;
export type ContentType = (typeof CONTENT_TYPES)[number];

export const FAITH_LABELS: Record<Faith, string> = {
  sikh: "Sikh",
  muslim: "Muslim",
  christian: "Christian",
  hindu: "Hindu",
  jewish: "Jewish",
};

export function isFaith(value: unknown): value is Faith {
  return typeof value === "string" && (FAITHS as readonly string[]).includes(value);
}
