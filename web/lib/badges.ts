/**
 * The three navbar chips — ports of update_freshness_badge, update_crawl_badge,
 * update_ibkr_badge. Each returns a Zod-typed StatusChip; the component layer
 * only renders it. Strings match the Python byte-for-byte (golden-tested).
 */
import { fmtDMonY, fmtYmdHm, parseNaive, type Clock } from "./clock";
import { consistencyReport } from "./consistency";
import type { Db } from "./db";
import { freshnessReport, staleSources } from "./freshness";
import { ivSourceMeta } from "./iv-source";
import { jobReport, lastCompletedCrawl, overdueJobs, schedulerEnabled } from "./jobs";
import { pyFixed } from "./pynum";
import { GREEN, RED, SUBTEXT, YELLOW } from "./config";
import { IvBadgeRow, type StatusChip } from "./schemas";

const chip = (icon: string, label: string, colour: string, detail: string): StatusChip => ({ icon, label, colour, detail });

export function freshnessBadge(db: Db, clock: Clock): StatusChip {
  let report, stale;
  try {
    report = freshnessReport(db, clock);
    stale = staleSources(report);
  } catch (e) {
    return chip("⚠️", "freshness: error", YELLOW, `Freshness check failed: ${(e as Error).message}`);
  }
  let cons;
  try { cons = consistencyReport(db); } catch { cons = { flags: [], checked: 0 }; }
  const cflags = cons.flags ?? [];
  if (stale.length === 0 && cflags.length === 0) {
    return chip("🟢", "data: fresh", GREEN,
      `Every tracked source is within its freshness SLA, and ${cons.checked ?? 0} series passed the shape checks.`);
  }
  if (stale.length === 0) {
    const detail = cflags.map((f) => `${f.series} [${f.rule}]: ${f.detail}`).join("\n");
    return chip("🟡", `${cflags.length} shape flag${cflags.length > 1 ? "s" : ""}`, YELLOW,
      "Every source is fresh, but these series look implausible — verify against the publisher before trusting them:\n\n" + detail);
  }
  const why = (k: string) => {
    const r = report[k];
    if (r.empty) return `${k}: ${pyNum(r.null_price_pct)}% of rows have no price — scraper writing empty rows`;
    return `${k}: ${r.max_period} — ${r.days_stale}d old (SLA ${r.sla_days}d)`;
  };
  return chip("🔴", `${stale.length} stale/empty source${stale.length > 1 ? "s" : ""}`, RED,
    "Sources past their freshness SLA — see /api/db-stats:\n\n" + stale.map(why).join("\n"));
}

/** str() of the rounded pct Python float (e.g. 100.0, 57.1). */
const pyNum = (x: number | undefined) => (x === undefined ? "None" : Number.isInteger(x) ? `${x}.0` : String(x));

export function crawlBadge(db: Db, clock: Clock, env: { SEMI_DISABLE_SCHEDULER?: string }): StatusChip {
  let rep;
  try { rep = jobReport(db, clock); } catch (e) {
    return chip("⚠️", "crawl: error", YELLOW, `Heartbeat check failed: ${(e as Error).message}`);
  }
  const late = overdueJobs(rep);
  const lines = Object.entries(rep).map(([j, e]) =>
    `${j}: ${e.never_run ? "never" : `${pyFixed(e.age_hours!, 0)}h ago`} (every ${e.interval_hours}h) — ${e.label}`);
  const on = schedulerEnabled(env);
  if (!on) lines.push("Watchdog DISABLED via SEMI_DISABLE_SCHEDULER=1 — crawls must be driven externally.");
  const tip = lines.join("\n");
  if (late.length) {
    return chip("🔴", `crawl: ${late.length} overdue`, RED,
      "These jobs have not succeeded within their window:\n" + late.map((j) => `  · ${j}`).join("\n") + "\n\n" + tip);
  }
  if (!on) return chip("🟡", "crawl: external", YELLOW, tip);
  return chip("🟢", "crawl: on schedule", GREEN, tip);
}

export function ivBadge(db: Db): StatusChip {
  const latest = db.all(
    "SELECT source, MAX(snapshot_date) AS d, COUNT(DISTINCT ticker) AS n FROM options_iv " +
    "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM options_iv) GROUP BY source ORDER BY n DESC",
    [], IvBadgeRow, "iv_badge");
  if (latest.length === 0) {
    return chip("⚫", "IV: none", SUBTEXT, "No rows in options_iv.\nRun: python3 iv_crawler.py (no broker or subscription needed)");
  }
  const [short, , published] = ivSourceMeta(latest[0].source);
  const tickers = latest.reduce((a, r) => a + r.n, 0);
  const detail = latest.map((r) => `${ivSourceMeta(r.source)[1]} — ${r.n} tickers`).join("\n");
  return chip(published ? "🟢" : "🟡", `IV: ${short} (${tickers})`, published ? GREEN : YELLOW,
    `As of ${latest[0].d}\n${detail}\n\n${published ? "Published index." : "✳ Derived metric — our own construction, not a published index."}`);
}

/** Navbar "Last crawl:" text — last_crawl_time(). */
export function lastCrawlTime(db: Db): string {
  const f = lastCompletedCrawl(db);
  if (f === null) return "Never";
  const d = parseNaive(f);
  return d ? fmtDMonY(d) : f;
}

/** Source-footer stamp — _crawl_timestamp(). */
export function crawlTimestamp(db: Db): string {
  const f = lastCompletedCrawl(db);
  if (f === null) return "Data not available in the latest crawl.";
  const d = parseNaive(f);
  return d ? fmtYmdHm(d) : f;
}
