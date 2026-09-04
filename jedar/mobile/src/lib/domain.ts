/**
 * Jedar domain values. Mirrors server/src/domain.ts exactly; the server is the
 * authority and rejects anything outside these sets.
 */
export const FAITHS = ["sikh", "muslim", "christian", "hindu", "jewish"] as const;
export type Faith = (typeof FAITHS)[number];

export const MODES = ["calm", "prayer", "guidance", "journal", "learn"] as const;
export type Mode = (typeof MODES)[number];

export const JEDAR_VOICES = ["maya", "noor", "ayaan"] as const;
export type JedarVoice = (typeof JEDAR_VOICES)[number];

export const JOURNAL_TYPES = ["reflection", "note", "conversation"] as const;
export type JournalEntryType = (typeof JOURNAL_TYPES)[number];

export const FAITH_INFO: Record<Faith, { label: string; description: string }> = {
  sikh: { label: "Sikh", description: "Service, equality, remembrance, and rising spirit." },
  muslim: { label: "Muslim", description: "Mercy, patience, prayer, and trust in Allah." },
  christian: { label: "Christian", description: "Love, grace, forgiveness, and hope." },
  hindu: { label: "Hindu", description: "Dharma, devotion, truth, and non-harm." },
  jewish: { label: "Jewish", description: "Compassion, justice, learning, and repair." },
};

export const MODE_INFO: Record<Mode, { label: string; hint: string }> = {
  calm: { label: "Calm", hint: "Settle and breathe." },
  prayer: { label: "Prayer", hint: "Find words together." },
  guidance: { label: "Guidance", hint: "Talk something through." },
  journal: { label: "Journal", hint: "Notice and name what's here." },
  learn: { label: "Learn", hint: "Understand your tradition." },
};

export const VOICE_INFO: Record<JedarVoice, { label: string; description: string }> = {
  maya: { label: "Maya", description: "Calm female" },
  noor: { label: "Noor", description: "Gentle female" },
  ayaan: { label: "Ayaan", description: "Grounded male" },
};

export const JOURNAL_TYPE_INFO: Record<JournalEntryType, { label: string }> = {
  reflection: { label: "Reflection" },
  note: { label: "Note" },
  conversation: { label: "Conversation" },
};

export function isFaith(value: unknown): value is Faith {
  return typeof value === "string" && (FAITHS as readonly string[]).includes(value);
}
export function isMode(value: unknown): value is Mode {
  return typeof value === "string" && (MODES as readonly string[]).includes(value);
}
export function isJedarVoice(value: unknown): value is JedarVoice {
  return typeof value === "string" && (JEDAR_VOICES as readonly string[]).includes(value);
}

/** Shape returned by the server for both reflection endpoints. */
export type PublicReflection = {
  id: string;
  faith: Faith;
  type: "reflection" | "scripture";
  label: "Reflection" | "Scripture";
  title: string;
  body: string;
  approved: boolean;
  sourceName?: string;
  reference?: string;
  reviewedBy?: string;
};
