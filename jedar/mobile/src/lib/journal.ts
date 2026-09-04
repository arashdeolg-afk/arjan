import type { Faith, JournalEntryType } from "./domain.js";
import { FAITHS, JOURNAL_TYPES } from "./domain.js";
import type { Database } from "./schema.js";

export type JournalEntry = {
  id: string;
  type: JournalEntryType;
  title: string;
  body: string;
  faith: Faith;
  reflectionId?: string;
  createdAt: string;
  updatedAt: string;
};

export type NewJournalEntry = {
  type: JournalEntryType;
  title: string;
  body: string;
  faith: Faith;
  reflectionId?: string | undefined;
};

export type JournalFilter = {
  faith?: Faith | undefined;
  type?: JournalEntryType | undefined;
  query?: string | undefined;
};

export const TITLE_MAX = 120;
export const BODY_MAX = 20_000;

type Row = {
  id: string;
  type: JournalEntryType;
  title: string;
  body: string;
  faith: Faith;
  reflection_id: string | null;
  created_at: string;
  updated_at: string;
};

function rowToEntry(row: Row): JournalEntry {
  const entry: JournalEntry = {
    id: row.id,
    type: row.type,
    title: row.title,
    body: row.body,
    faith: row.faith,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
  if (row.reflection_id) entry.reflectionId = row.reflection_id;
  return entry;
}

function fallbackId(): string {
  const hex = () => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, "0");
  return `${hex()}-${hex().slice(0, 4)}-4${hex().slice(0, 3)}-${hex().slice(0, 4)}-${hex()}${hex().slice(0, 4)}`;
}

export type JournalOptions = {
  id?: () => string;
  now?: () => string;
};

/**
 * All journal data stays in the on-device database. Nothing here talks to the
 * network; conversations are only saved when the user explicitly asks.
 */
export class JournalRepository {
  private readonly makeId: () => string;
  private readonly now: () => string;

  constructor(
    private readonly db: Database,
    options: JournalOptions = {},
  ) {
    this.makeId = options.id ?? fallbackId;
    this.now = options.now ?? (() => new Date().toISOString());
  }

  private validate(input: { title: string; body: string; faith?: Faith; type?: JournalEntryType }): { title: string; body: string } {
    const title = input.title.trim();
    const body = input.body.trim();
    if (!title) throw new Error("Title is required");
    if (title.length > TITLE_MAX) throw new Error(`Title must be at most ${TITLE_MAX} characters`);
    if (!body) throw new Error("Body is required");
    if (body.length > BODY_MAX) throw new Error(`Body must be at most ${BODY_MAX} characters`);
    if (input.faith !== undefined && !(FAITHS as readonly string[]).includes(input.faith)) throw new Error("Unknown faith");
    if (input.type !== undefined && !(JOURNAL_TYPES as readonly string[]).includes(input.type)) throw new Error("Unknown entry type");
    return { title, body };
  }

  async create(input: NewJournalEntry): Promise<JournalEntry> {
    const { title, body } = this.validate(input);
    const id = this.makeId();
    const ts = this.now();
    await this.db.runAsync(
      `INSERT INTO journal_entries (id, type, title, body, faith, reflection_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [id, input.type, title, body, input.faith, input.reflectionId ?? null, ts, ts],
    );
    return { id, type: input.type, title, body, faith: input.faith, ...(input.reflectionId ? { reflectionId: input.reflectionId } : {}), createdAt: ts, updatedAt: ts };
  }

  async list(filter: JournalFilter = {}): Promise<JournalEntry[]> {
    const where: string[] = [];
    const params: (string | null)[] = [];
    if (filter.faith) {
      where.push("faith = ?");
      params.push(filter.faith);
    }
    if (filter.type) {
      where.push("type = ?");
      params.push(filter.type);
    }
    const q = filter.query?.trim();
    if (q) {
      where.push("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')");
      const like = `%${q.replace(/[\\%_]/g, (c) => `\\${c}`)}%`;
      params.push(like, like);
    }
    const sql = `SELECT * FROM journal_entries${where.length ? ` WHERE ${where.join(" AND ")}` : ""} ORDER BY created_at DESC, id DESC`;
    const rows = await this.db.getAllAsync<Row>(sql, params);
    return rows.map(rowToEntry);
  }

  async get(id: string): Promise<JournalEntry | null> {
    const row = await this.db.getFirstAsync<Row>(`SELECT * FROM journal_entries WHERE id = ?`, [id]);
    return row ? rowToEntry(row) : null;
  }

  async update(id: string, patch: { title?: string; body?: string }): Promise<JournalEntry | null> {
    const existing = await this.get(id);
    if (!existing) return null;
    const { title, body } = this.validate({ title: patch.title ?? existing.title, body: patch.body ?? existing.body });
    const ts = this.now();
    await this.db.runAsync(`UPDATE journal_entries SET title = ?, body = ?, updated_at = ? WHERE id = ?`, [title, body, ts, id]);
    return { ...existing, title, body, updatedAt: ts };
  }

  async remove(id: string): Promise<boolean> {
    const existing = await this.get(id);
    if (!existing) return false;
    await this.db.runAsync(`DELETE FROM journal_entries WHERE id = ?`, [id]);
    return true;
  }

  async removeAll(): Promise<number> {
    const n = await this.count();
    await this.db.runAsync(`DELETE FROM journal_entries`);
    return n;
  }

  async count(): Promise<number> {
    const row = await this.db.getFirstAsync<{ n: number }>(`SELECT COUNT(*) AS n FROM journal_entries`);
    return row?.n ?? 0;
  }

  /** Has this reflection already been saved today? Used to avoid duplicate saves. */
  async findByReflection(reflectionId: string): Promise<JournalEntry | null> {
    const row = await this.db.getFirstAsync<Row>(
      `SELECT * FROM journal_entries WHERE reflection_id = ? AND type = 'reflection' ORDER BY created_at DESC LIMIT 1`,
      [reflectionId],
    );
    return row ? rowToEntry(row) : null;
  }
}

/** Turn a transcript into journal text. Only called after the user confirms. */
export function formatConversation(lines: Array<{ role: "user" | "assistant"; text: string }>): string {
  return lines
    .filter((l) => l.text.trim())
    .map((l) => `${l.role === "user" ? "You" : "Jedar"}: ${l.text.trim()}`)
    .join("\n\n");
}
