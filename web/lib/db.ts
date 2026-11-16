/**
 * Read-only SQLite access. Next.js is a READER: the Python crawlers own the
 * schema and every write.
 *
 *  - opened `readonly: true, fileMustExist: true` — Node can never create the DB
 *    file (that would reproduce CLAUDE.md §5.1's ephemeral-storage failure);
 *  - prod runs WAL (every crawler sets PRAGMA journal_mode=WAL; VACUUM INTO
 *    backups are DELETE-mode, which once misled us). Readers don't block on
 *    commits, but SQLITE_BUSY is still possible at checkpoints → bounded retry
 *    below. Concurrency is tested in tests/wal.test.ts;
 *  - every row is Zod-parsed before it leaves this module. A SQL error (e.g. a
 *    table that does not exist on an older DB) returns [] — the same contract as
 *    dashboard.py's `query()` — but a SCHEMA mismatch throws DataUnavailableError,
 *    so a renamed column renders "data unavailable" instead of silent blanks.
 */
import Database from "better-sqlite3";
import type { z } from "zod";

if (typeof window !== "undefined") {
  throw new Error("lib/db.ts imported in a client bundle — DB access is server-only");
}

export class DataUnavailableError extends Error {
  constructor(public readonly what: string, public readonly issues: string) {
    super(`data unavailable: ${what} — ${issues}`);
    this.name = "DataUnavailableError";
  }
}

export interface Db {
  /** Rows parsed by `schema`. SQL error → [] (+ logged); schema error → throws. */
  all<S extends z.ZodTypeAny>(sql: string, params: readonly unknown[], schema: S, what?: string): z.infer<S>[];
  close(): void;
}

const BUSY_RETRIES = 4;
const sleepSync = (ms: number) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

function isBusy(e: unknown): boolean {
  const code = (e as { code?: string })?.code ?? "";
  return code === "SQLITE_BUSY" || code === "SQLITE_LOCKED";
}

export function openDb(path: string): Db {
  // timeout = SQLite busy_timeout (ms) per statement; the loop below bounds the total.
  const conn = new Database(path, { readonly: true, fileMustExist: true, timeout: 2000 });
  return {
    all(sql, params, schema, what = sql.slice(0, 60)) {
      let raw: unknown[] = [];
      for (let attempt = 0; ; attempt++) {
        try {
          raw = conn.prepare(sql).all(...(params as unknown[]));
          break;
        } catch (e) {
          if (isBusy(e) && attempt < BUSY_RETRIES) {
            sleepSync(100 * 2 ** attempt);
            continue;
          }
          console.warn(`[db] query failed (${what}): ${(e as Error).message}`);
          return [];
        }
      }
      const out: z.infer<typeof schema>[] = [];
      for (const r of raw) {
        const parsed = schema.safeParse(r);
        if (!parsed.success) {
          console.error(`[db] schema mismatch (${what}):`, parsed.error.message, r);
          throw new DataUnavailableError(what, parsed.error.message);
        }
        out.push(parsed.data);
      }
      return out;
    },
    close() {
      conn.close();
    },
  };
}

/** Comma-joined "?" placeholders, as dashboard.py builds them. */
export const placeholders = (n: number) => Array.from({ length: n }, () => "?").join(",");
