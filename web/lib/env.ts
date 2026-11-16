/**
 * Environment, parsed with Zod at startup (prompt constraint 6).
 *  DB_PATH                 required. Same variable the Python reads.
 *  PORT                    read by `next start`; never defaulted here (§7 rule 8).
 *  SEMI_VOLUME_OK/_REASON  set by startup.sh's volume guard — surfaced, never re-derived (constraint 5).
 *  SEMI_DISABLE_SCHEDULER  mirrors job_heartbeat.scheduler_enabled().
 *  CLASSIC_ORIGIN          where gunicorn listens during the strangler phase; /health and
 *                          /api/* are proxied there (next.config.ts). Local-dev default only.
 *  RELAY_API_KEY           read ONLY by app/ui-api/run-crawl/route.ts (server) to call Flask's
 *                          keyed POST /api/run-crawl. Never passed to a component, so it never
 *                          reaches a client bundle (checked by the QA leak scan). NB: the ⚡
 *                          button itself is public, exactly like Dash's — the key stops
 *                          scripts hitting Flask directly; the run LOCK is what stops overlap.
 */
import { z } from "zod";

const Env = z.object({
  DB_PATH: z.string().min(1, "DB_PATH is required (path to semiconductor_data.db)"),
  PORT: z.string().regex(/^\d+$/).optional(),
  SEMI_VOLUME_OK: z.string().optional(),
  SEMI_VOLUME_REASON: z.string().optional(),
  SEMI_DISABLE_SCHEDULER: z.string().optional(),
  CLASSIC_ORIGIN: z.string().url().default("http://127.0.0.1:8051"), // = next.config.ts + startup.sh
  RELAY_API_KEY: z.string().optional(),
});
export type Env = z.infer<typeof Env>;

let cached: Env | null = null;
export function getEnv(): Env {
  if (cached) return cached;
  const parsed = Env.safeParse(process.env);
  if (!parsed.success) throw new Error(`Invalid environment: ${parsed.error.message}`);
  cached = parsed.data;
  return cached;
}

/** dashboard.py: VOLUME_OK = os.environ.get("SEMI_VOLUME_OK", "1") != "0" */
export const volumeStatus = (env: Env) => ({
  ok: (env.SEMI_VOLUME_OK ?? "1") !== "0",
  reason: env.SEMI_VOLUME_REASON ?? "ok",
});
