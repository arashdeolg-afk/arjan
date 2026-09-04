import { DatabaseSync } from "node:sqlite";
import type { Database, SqlParam } from "../src/lib/schema.js";

/** Adapts Node's built-in sqlite to the expo-sqlite-shaped Database interface used by the app. */
export function memoryDatabase(): Database {
  const db = new DatabaseSync(":memory:");
  return {
    async execAsync(sql: string) {
      db.exec(sql);
    },
    async runAsync(sql: string, params: SqlParam[] = []) {
      return db.prepare(sql).run(...params);
    },
    async getAllAsync<T>(sql: string, params: SqlParam[] = []) {
      return db.prepare(sql).all(...params) as T[];
    },
    async getFirstAsync<T>(sql: string, params: SqlParam[] = []) {
      return (db.prepare(sql).get(...params) as T | undefined) ?? null;
    },
  };
}
