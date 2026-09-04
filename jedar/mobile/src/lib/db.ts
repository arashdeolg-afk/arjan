import { openDatabaseAsync, type SQLiteDatabase } from "expo-sqlite";
import { randomUUID } from "expo-crypto";
import { migrate, type Database } from "./schema";
import { JournalRepository } from "./journal";
import { PreferencesStore } from "./preferences";

export const DB_NAME = "jedar.db";

export type Services = { db: Database; journal: JournalRepository; preferences: PreferencesStore };

let cached: Promise<Services> | null = null;

/** Open (once) the private on-device database and build repositories over it. */
export function getServices(): Promise<Services> {
  if (!cached) {
    cached = (async () => {
      const raw: SQLiteDatabase = await openDatabaseAsync(DB_NAME);
      const db: Database = {
        execAsync: (sql) => raw.execAsync(sql),
        runAsync: (sql, params = []) => raw.runAsync(sql, params),
        getAllAsync: (sql, params = []) => raw.getAllAsync(sql, params),
        getFirstAsync: (sql, params = []) => raw.getFirstAsync(sql, params),
      };
      await migrate(db);
      return {
        db,
        journal: new JournalRepository(db, { id: randomUUID }),
        preferences: new PreferencesStore(db, randomUUID),
      };
    })();
    cached.catch(() => {
      cached = null;
    });
  }
  return cached;
}
