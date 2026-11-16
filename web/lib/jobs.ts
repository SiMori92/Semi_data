/**
 * Read-only port of job_heartbeat.job_report / overdue_jobs / scheduler_enabled.
 *
 * JOB_SPECS lives in job_heartbeat.py and is THE schedule. This mirror exists
 * only so the badge can render; tests/parity.test.ts checks every label and
 * interval against the golden dump, so a JOB_SPECS edit that is not mirrored
 * here fails the suite on the next `npm run golden`.
 *
 * Difference by design: the Python calls ensure_schema() (DDL!) on every read.
 * Node is read-only, so a DB missing the `job` column simply reports
 * never-run — the Python crawlers create that column on their next run.
 */
import { isoSeconds, parseNaive, type Clock } from "./clock";
import type { Db } from "./db";
import { pyRound } from "./pynum";
import type { JobReport } from "./schemas";
import { z } from "zod";

export const JOB_SPECS = {
  market: { interval_hours: 24, overdue_hours: 30, label: "Prices + financials + sentiment + cycles" },
  iv: { interval_hours: 24, overdue_hours: 30, label: "Implied volatility (derived ATM30 + Deribit DVOL)" },
  supply_chain: { interval_hours: 24 * 7, overdue_hours: 24 * 9, label: "Supply chain live scrape (PassMark/Steam/TrendForce/IR)" },
} as const;

export function jobReport(db: Db, clock: Clock): JobReport {
  const out: JobReport = {};
  const now = clock.hkt;
  for (const [job, spec] of Object.entries(JOB_SPECS)) {
    const entry = {
      label: spec.label, interval_hours: spec.interval_hours, overdue_hours: spec.overdue_hours,
      last_success: null as string | null, age_hours: null as number | null,
      due: true, overdue: true, never_run: true, last_status: null as string | null,
    };
    try {
      const ts = db.all(
        "SELECT MAX(finished_at) AS mx FROM crawl_runs WHERE job = ? AND status = 'completed' AND finished_at IS NOT NULL",
        [job], z.object({ mx: z.string().nullable() }), "job:last_success")[0]?.mx;
      const last = db.all("SELECT status FROM crawl_runs WHERE job = ? ORDER BY id DESC LIMIT 1",
        [job], z.object({ status: z.string().nullable() }), "job:last_status")[0];
      if (last) entry.last_status = last.status;
      const t = ts ? parseNaive(ts) : null;
      if (t) {
        const age = (now.getTime() - t.getTime()) / 1000 / 3600.0;
        Object.assign(entry, {
          last_success: isoSeconds(t), age_hours: pyRound(age, 1),
          due: age >= spec.interval_hours, overdue: age >= spec.overdue_hours, never_run: false,
        });
      }
    } catch {
      /* never raises — same contract as the Python */
    }
    out[job] = entry;
  }
  return out;
}

/** Overdue jobs, worst first: key (age is not None, age or 0), reverse. */
export function overdueJobs(rep: JobReport): string[] {
  return Object.entries(rep)
    .filter(([, e]) => e.overdue)
    .sort((a, b) => {
      const ka = [a[1].age_hours !== null ? 1 : 0, a[1].age_hours ?? 0];
      const kb = [b[1].age_hours !== null ? 1 : 0, b[1].age_hours ?? 0];
      return kb[0] - ka[0] || kb[1] - ka[1];
    })
    .map(([j]) => j);
}

export const schedulerEnabled = (env: { SEMI_DISABLE_SCHEDULER?: string }) => (env.SEMI_DISABLE_SCHEDULER ?? "0") !== "1";

/** last_crawl_time() / _crawl_timestamp(): newest completed crawl_runs row. */
export function lastCompletedCrawl(db: Db): string | null {
  return db.all("SELECT finished_at FROM crawl_runs WHERE status='completed' ORDER BY id DESC LIMIT 1",
    [], z.object({ finished_at: z.string().nullable() }), "last_crawl")[0]?.finished_at ?? null;
}
