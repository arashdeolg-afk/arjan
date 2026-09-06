import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { z } from "zod";
import { CONTENT_TYPES, FAITHS, type Faith } from "./domain.js";

/**
 * Curated daily content. Records are loaded from content/reflections.json and
 * validated with the rules from the product spec:
 *
 *  - Unapproved content is ALWAYS type "reflection" (coerced on load).
 *  - A scripture record must be approved and carry sourceName, reference and
 *    reviewedBy, otherwise loading fails loudly.
 *  - The model never invents daily content; it only receives these records.
 */
export type DailyContent = {
  id: string;
  faith: Faith;
  type: "reflection" | "scripture";
  title: string;
  body: string;
  approved: boolean;
  sourceName?: string;
  reference?: string;
  reviewedBy?: string;
};

export const ID_PATTERN = /^[a-z]+-[a-z0-9-]{1,40}$/;

const rawItemSchema = z.object({
  id: z.string().regex(ID_PATTERN, "id must look like faith-001"),
  faith: z.enum(FAITHS),
  type: z.enum(CONTENT_TYPES),
  title: z.string().trim().min(1).max(120),
  body: z.string().trim().min(1).max(1200),
  approved: z.boolean(),
  sourceName: z.string().trim().min(1).max(120).optional(),
  reference: z.string().trim().min(1).max(120).optional(),
  reviewedBy: z.string().trim().min(1).max(160).optional(),
});

const fileSchema = z.object({
  version: z.literal(1),
  note: z.string().optional(),
  items: z.array(rawItemSchema).min(1),
});

export class ContentValidationError extends Error {}

/** Normalise a raw record according to the integrity rules. Throws on invalid scripture. */
export function normalizeItem(raw: z.infer<typeof rawItemSchema>): DailyContent {
  const item: DailyContent = {
    id: raw.id,
    faith: raw.faith,
    type: raw.type,
    title: raw.title,
    body: raw.body,
    approved: raw.approved,
  };
  if (raw.sourceName) item.sourceName = raw.sourceName;
  if (raw.reference) item.reference = raw.reference;
  if (raw.reviewedBy) item.reviewedBy = raw.reviewedBy;

  if (item.type === "scripture") {
    if (!item.approved) {
      // Unapproved content must always be presented as an ordinary reflection.
      item.type = "reflection";
      delete item.sourceName;
      delete item.reference;
    } else if (!item.sourceName || !item.reference || !item.reviewedBy) {
      throw new ContentValidationError(
        `Scripture record "${item.id}" is approved but is missing sourceName, reference or reviewedBy`,
      );
    }
  } else if (item.sourceName || item.reference) {
    // A reflection must never look like scripture, so citations are not allowed on it.
    throw new ContentValidationError(
      `Reflection record "${item.id}" carries sourceName/reference; only approved scripture may cite a source`,
    );
  }
  return item;
}

export function parseContent(json: unknown): DailyContent[] {
  const parsed = fileSchema.safeParse(json);
  if (!parsed.success) {
    const issues = parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
    throw new ContentValidationError(`reflections.json is invalid: ${issues}`);
  }
  const items = parsed.data.items.map(normalizeItem);
  const ids = new Set<string>();
  for (const item of items) {
    if (ids.has(item.id)) throw new ContentValidationError(`Duplicate content id "${item.id}"`);
    ids.add(item.id);
  }
  return items;
}

export class ContentRepository {
  private readonly byId: Map<string, DailyContent>;
  private readonly byFaith: Map<Faith, DailyContent[]>;

  constructor(items: DailyContent[]) {
    this.byId = new Map(items.map((i) => [i.id, i]));
    this.byFaith = new Map();
    for (const faith of FAITHS) {
      this.byFaith.set(
        faith,
        items.filter((i) => i.faith === faith && isEligible(i)),
      );
    }
  }

  static fromFile(path?: string): ContentRepository {
    const here = dirname(fileURLToPath(import.meta.url));
    const file = path ?? join(here, "..", "content", "reflections.json");
    const json = JSON.parse(readFileSync(file, "utf8")) as unknown;
    return new ContentRepository(parseContent(json));
  }

  all(): DailyContent[] {
    return [...this.byId.values()];
  }

  get(id: string): DailyContent | undefined {
    if (!ID_PATTERN.test(id)) return undefined;
    return this.byId.get(id);
  }

  forFaith(faith: Faith): DailyContent[] {
    return this.byFaith.get(faith) ?? [];
  }

  /**
   * Deterministic pick for (faith, local date). The same inputs always give the same
   * record for the whole day, on every device, without storing anything.
   */
  today(faith: Faith, date: string): DailyContent | undefined {
    const pool = this.forFaith(faith);
    if (pool.length === 0) return undefined;
    const index = fnv1a(`${faith}:${date}`) % pool.length;
    return pool[index];
  }
}

/** Scripture is only eligible when fully approved; reflections are always original text. */
export function isEligible(item: DailyContent): boolean {
  if (item.type === "reflection") return true;
  return item.approved && !!item.sourceName && !!item.reference && !!item.reviewedBy;
}

/** Display label. Only approved scripture may ever be labelled "Scripture". */
export function displayLabel(item: DailyContent): "Reflection" | "Scripture" {
  return item.type === "scripture" && isEligible(item) ? "Scripture" : "Reflection";
}

export const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function isValidLocalDate(date: string): boolean {
  if (!DATE_PATTERN.test(date)) return false;
  const [y, m, d] = date.split("-").map(Number) as [number, number, number];
  if (m < 1 || m > 12 || d < 1) return false;
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return d <= daysInMonth && y >= 2000 && y <= 2200;
}

export function fnv1a(input: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

/** Shape sent to clients. Identical for both reflection endpoints. */
export function toPublic(item: DailyContent) {
  const label = displayLabel(item);
  return {
    id: item.id,
    faith: item.faith,
    type: label === "Scripture" ? "scripture" : "reflection",
    label,
    title: item.title,
    body: item.body,
    approved: item.approved,
    ...(label === "Scripture"
      ? { sourceName: item.sourceName, reference: item.reference, reviewedBy: item.reviewedBy }
      : {}),
  };
}
