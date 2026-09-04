/**
 * Minimal database contract satisfied by expo-sqlite's SQLiteDatabase (and, in
 * tests, by a thin adapter over node:sqlite). Keeping repositories on this
 * interface means journal logic is unit-testable without a device.
 */
export type SqlParam = string | number | null;

export interface Database {
  execAsync(sql: string): Promise<void>;
  runAsync(sql: string, params?: SqlParam[]): Promise<unknown>;
  getAllAsync<T>(sql: string, params?: SqlParam[]): Promise<T[]>;
  getFirstAsync<T>(sql: string, params?: SqlParam[]): Promise<T | null>;
}

export const SCHEMA_VERSION = 1;

export async function migrate(db: Database): Promise<void> {
  await db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS journal_entries (
      id TEXT PRIMARY KEY NOT NULL,
      type TEXT NOT NULL CHECK (type IN ('reflection','note','conversation')),
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      faith TEXT NOT NULL CHECK (faith IN ('sikh','muslim','christian','hindu','jewish')),
      reflection_id TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_journal_created ON journal_entries (created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_journal_faith_type ON journal_entries (faith, type);
    CREATE TABLE IF NOT EXISTS preferences (
      key TEXT PRIMARY KEY NOT NULL,
      value TEXT NOT NULL
    );
  `);
}
