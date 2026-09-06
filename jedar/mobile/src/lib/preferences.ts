import { isFaith, isJedarVoice, type Faith, type JedarVoice } from "./domain.js";
import type { Database } from "./schema.js";

export type Preferences = {
  faith: Faith | null;
  voice: JedarVoice;
  onboardingComplete: boolean;
  reminderEnabled: boolean;
  reminderHour: number;
  reminderMinute: number;
  /** Random per-install ID; the server hashes it with a salt before use. */
  installId: string;
};

export const DEFAULT_PREFERENCES: Omit<Preferences, "installId"> = {
  faith: null,
  voice: "maya",
  onboardingComplete: false,
  reminderEnabled: false,
  reminderHour: 8,
  reminderMinute: 0,
};

const KEYS = ["faith", "voice", "onboardingComplete", "reminderEnabled", "reminderHour", "reminderMinute", "installId"] as const;

export class PreferencesStore {
  constructor(
    private readonly db: Database,
    private readonly makeId: () => string,
  ) {}

  async load(): Promise<Preferences> {
    const rows = await this.db.getAllAsync<{ key: string; value: string }>(`SELECT key, value FROM preferences`);
    const raw: Record<string, unknown> = {};
    for (const row of rows) {
      try {
        raw[row.key] = JSON.parse(row.value);
      } catch {
        // ignore corrupt values; defaults apply
      }
    }
    let installId = typeof raw.installId === "string" && raw.installId ? raw.installId : "";
    if (!installId) {
      installId = this.makeId();
      await this.set("installId", installId);
    }
    return {
      faith: isFaith(raw.faith) ? raw.faith : DEFAULT_PREFERENCES.faith,
      voice: isJedarVoice(raw.voice) ? raw.voice : DEFAULT_PREFERENCES.voice,
      onboardingComplete: raw.onboardingComplete === true,
      reminderEnabled: raw.reminderEnabled === true,
      reminderHour: clampInt(raw.reminderHour, 0, 23, DEFAULT_PREFERENCES.reminderHour),
      reminderMinute: clampInt(raw.reminderMinute, 0, 59, DEFAULT_PREFERENCES.reminderMinute),
      installId,
    };
  }

  async save(patch: Partial<Omit<Preferences, "installId">>): Promise<Preferences> {
    for (const key of KEYS) {
      if (key === "installId") continue;
      if (key in patch) await this.set(key, patch[key]);
    }
    return this.load();
  }

  private async set(key: string, value: unknown): Promise<void> {
    await this.db.runAsync(`INSERT INTO preferences (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value`, [
      key,
      JSON.stringify(value ?? null),
    ]);
  }

  /** Forget everything except the anonymous install ID. */
  async reset(): Promise<Preferences> {
    await this.db.runAsync(`DELETE FROM preferences WHERE key != 'installId'`);
    return this.load();
  }
}

function clampInt(value: unknown, min: number, max: number, fallback: number): number {
  if (typeof value !== "number" || !Number.isInteger(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}
