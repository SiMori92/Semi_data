/** Process-wide singletons for server components and route handlers. */
import { openDb, type Db } from "./db";
import { getEnv } from "./env";

const g = globalThis as unknown as { __semiDb?: Db };
export function getDb(): Db {
  if (!g.__semiDb) g.__semiDb = openDb(getEnv().DB_PATH);
  return g.__semiDb;
}
