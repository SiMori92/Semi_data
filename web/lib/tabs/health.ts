/**
 * 🩺 Data Health tab (DH-01, 2026-11-22). Read-only, Next-only — no Dash original,
 * so it is not part of the golden parity suite.
 *
 * Three questions, each answered from ONE existing source of truth:
 *   1. Is each data source producing?   → freshnessReport() (lib/freshness.ts) —
 *      the same helper behind the navbar chip and /api/db-stats, so this tab
 *      cannot disagree with them (CLAUDE.md §6.5).
 *   2. Did the job that feeds it succeed? → crawl_runs heartbeats (job_heartbeat.py).
 *   3. Which charts does it break?        → SOURCE_CATALOG below.
 *
 * Per-source crawl results: crawl_runs is one row per JOB; since DH-01 each
 * supply_chain scraper ALSO writes a crawl_source_runs row (ok / no_data / error,
 * job_heartbeat.run_source). A source's status = its data freshness, downgraded
 * to 🟡 when the scraper (or, with no scraper rows, the job) feeding it failed.
 * market / iv are single-source jobs, so the job row is their source result.
 */
import { addDays, isoSeconds, parseNaive, type Clock } from "../clock";
import { GREEN, RED, SUBTEXT, YELLOW } from "../config";
import type { Db } from "../db";
import { card, cols, ODD_ROW, responsiveGraph, sectionTitle, TBL_CELL, TBL_HEADER } from "../dash/common";
import { dbc, DataTable, html, type DNode } from "../dash/tree";
import { freshnessReport } from "../freshness";
import { JOB_SPECS } from "../jobs";
import { TABS, type TabId } from "../params";
import { addSeries, emptyFigure, pyLayout, updateAxis } from "../plotly/figure";
import { pyRound } from "../pynum";
import type { FreshnessEntry } from "../schemas";
import { z } from "zod";

// ── Catalogue: freshness key → who produces it, which charts read it ─────────
/** Curated reload job (job_heartbeat.JOB_CURATED) — runs every deploy, no network. */
const CURATED = "supply_chain_curated";
type Job = keyof typeof JOB_SPECS | typeof CURATED;
type SourceInfo = { label: string; jobs: Job[]; charts: [TabId, string][] };

const tabLabel = (t: TabId) => TABS.find((x) => x.id === t)?.label ?? t;

const SC_DEMAND_PANEL: [TabId, string][] = [["supplychain", "Macro Demand Indicators"]];
const SC_RAM: [TabId, string][] = [
  ["supplychain", "RAM (Enterprise) › DRAM & HBM Spot / Contract Prices"],
  ["supplychain", "RAM (Enterprise) › Normalized USD/GB · Bandwidth vs Price"],
  ["supplychain", "RAM (Enterprise) › Latest Prices & YoY tables"],
];

const EXACT: Record<string, SourceInfo> = {
  daily_prices: { label: "Daily prices (Yahoo Finance / yfinance)", jobs: ["market"], charts: [
    ["overview", "Price Performance + Trading Volume"], ["cycles", "Cycle Price Chart"],
    ["compare", "Price Return — Period A vs B"], ["sentiment", "HV30 fallback (when no IV)"],
    ["supplychain", "Price Index vs SOXX ETF — Correlation"]] },
  market_sentiment: { label: "Market sentiment snapshot (derived from prices)", jobs: ["market"], charts: [
    ["overview", "KPI cards · Return Heatmap"], ["sentiment", "Days Since Large Drop · 5-Day vs 1-Month Return"],
    ["sentiment", "Sentiment Snapshot table"]] },
  cycle_analysis: { label: "Cycle analysis snapshot (derived from prices)", jobs: ["market"], charts: [
    ["cycles", "Cycle Summary · Magnitude · Duration · Volume Change"]] },
  quarterly_financials: { label: "Quarterly financials (yfinance)", jobs: ["market"], charts: [
    ["financials", "Latest Quarter Summary · Revenue/Profit/R&D/Margin charts"],
    ["compare", "Avg Revenue / Gross Profit / Net Profit"]] },
  ticker_valuation_history: { label: "Valuation snapshot — P/E, market cap (yfinance)", jobs: ["market"], charts: [
    ["financials", "Valuation Snapshot"]] },
  options_iv: { label: "Implied volatility (derived ATM30 + Deribit DVOL)", jobs: ["iv"], charts: [
    ["sentiment", "IV Term Structure · IV Percentile · Daily IV History"],
    ["sentiment", "Options IV Snapshot table"]] },
  sc_market_share: { label: "Steam Hardware Survey — GPU share", jobs: ["supply_chain", CURATED], charts: [
    ["supplychain", "Consumer GPU Market Share — Steam Hardware Survey"]] },
  sc_fab_metrics: { label: "Manufacturer disclosures (TSMC quarterly + curated filings)", jobs: ["supply_chain", CURATED], charts: [
    ["supplychain", "Manufacturer Disclosures · Disclosure Detail"]] },
  "sc_prices[curated]": { label: "Enterprise GPU/CPU contract prices (curated, modeled)", jobs: [CURATED], charts: [
    ["supplychain", "GPU (Enterprise) › Price · TFLOPS vs Price · YoY table"],
    ["supplychain", "CPU (Enterprise) › Price · Cores vs Price · YoY table"],
    ["supplychain", "Enterprise AI Hardware Price Index vs ETF"]] },
  "sc_prices[passmark]": { label: "PassMark consumer GPU/CPU prices", jobs: ["supply_chain"], charts: [] },
  "sc_prices[newegg]": { label: "Newegg consumer retail prices", jobs: ["supply_chain"], charts: [] },
  "sc_dram_spot[ddr4]": { label: "DDR4 spot (TrendForce live + curated)", jobs: ["supply_chain", CURATED], charts: SC_RAM },
  "sc_dram_spot[ddr5]": { label: "DDR5 spot (TrendForce live + curated)", jobs: ["supply_chain", CURATED], charts: SC_RAM },
  "sc_dram_spot[hbm3]": { label: "HBM3 (curated)", jobs: [CURATED], charts: SC_RAM },
  "sc_dram_spot[hbm3e]": { label: "HBM3E (curated)", jobs: [CURATED], charts: SC_RAM },
  "sc_demand[tsmc_revenue]": { label: "TSMC monthly revenue (IR, live)", jobs: ["supply_chain", CURATED], charts: SC_DEMAND_PANEL },
  "sc_demand[umc_revenue]": { label: "UMC monthly revenue (IR, live)", jobs: ["supply_chain", CURATED], charts: SC_DEMAND_PANEL },
  "sc_demand[nanya_revenue]": { label: "Nanya monthly revenue (IR, live)", jobs: ["supply_chain", CURATED], charts: SC_DEMAND_PANEL },
  "sc_demand[korea_chip_exports_20d]": { label: "Korea 20-day chip exports (MOTIE, curated)", jobs: [CURATED], charts: SC_DEMAND_PANEL },
  "sc_demand[wsts_billings]": { label: "WSTS / SIA global billings (curated)", jobs: [CURATED], charts: SC_DEMAND_PANEL },
  "sc_demand[semi_wwsems_billings]": { label: "SEMI WWSEMS equipment billings (curated)", jobs: [CURATED], charts: SC_DEMAND_PANEL },
};

/** Unknown keys are shown as-is, never coerced into a known bucket (the IV-01 lesson). */
export function sourceInfo(key: string): SourceInfo & { mapped: boolean } {
  const hit = EXACT[key];
  if (hit) return { ...hit, mapped: true };
  if (key.startsWith("sc_demand[")) return { label: key, jobs: [CURATED], charts: SC_DEMAND_PANEL, mapped: false };
  if (key.startsWith("sc_dram_spot[")) return { label: key, jobs: [CURATED], charts: SC_RAM, mapped: false };
  return { label: key, jobs: [], charts: [], mapped: false };
}

// ── crawl_runs reads ─────────────────────────────────────────────────────────
const RunRow = z.object({
  id: z.number().int(), job: z.string().nullable(), started_at: z.string(), finished_at: z.string().nullable(),
  status: z.string().nullable(), tickers_attempted: z.number().nullable(), tickers_ok: z.number().nullable(),
  note: z.string().nullable(),
});
type Run = z.infer<typeof RunRow>;

/** A "running" row with no finish this long after start was killed (redeploy / OOM / timeout). */
const ABANDON_HOURS = 2;
const HISTORY_DAYS = 60;

type Outcome = "success" | "failed" | "running" | "abandoned";
function outcome(r: Run, now: Date): Outcome {
  if (r.status === "completed") return "success";
  if (r.status === "running" || r.status === null) {
    const s = parseNaive(r.started_at);
    return s && (now.getTime() - s.getTime()) / 3600_000 > ABANDON_HOURS ? "abandoned" : "running";
  }
  return "failed";
}
const OUTCOME_META: Record<Outcome, { icon: string; text: string; colour: string }> = {
  success: { icon: "🟢", text: "SUCCESS", colour: GREEN },
  failed: { icon: "🔴", text: "FAILED", colour: RED },
  running: { icon: "🟡", text: "RUNNING", colour: YELLOW },
  abandoned: { icon: "🟠", text: "ABANDONED", colour: "var(--orange)" },
};

const jobLabel = (j: string) => (j === CURATED ? "supply_chain_curated (deploy reload)" : j);
const hm = (s: string | null) => (s ? s.replace("T", " ").slice(0, 16) : "—");
const ageText = (h: number | null) => (h === null ? "—" : h < 48 ? `${pyRound(h, 1)} h ago` : `${pyRound(h / 24, 1)} d ago`);
const hoursSince = (s: string | null, now: Date) => {
  const d = s ? parseNaive(s) : null;
  return d ? (now.getTime() - d.getTime()) / 3600_000 : null;
};
function duration(r: Run): string {
  const a = parseNaive(r.started_at), b = r.finished_at ? parseNaive(r.finished_at) : null;
  if (!a || !b) return "—";
  const s = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000));
  return s < 120 ? `${s}s` : `${pyRound(s / 60, 1)} min`;
}

type JobState = { job: string; last: Run | null; lastOk: string | null; ok30: number; fail30: number };
function jobStates(db: Db, now: Date): Map<string, JobState> {
  const since = isoSeconds(addDays(now, -30));
  const out = new Map<string, JobState>();
  for (const job of [...Object.keys(JOB_SPECS), CURATED]) {
    const last = db.all("SELECT * FROM crawl_runs WHERE job = ? ORDER BY id DESC LIMIT 1", [job], RunRow, "health:last_run")[0] ?? null;
    const lastOk = db.all("SELECT MAX(finished_at) AS mx FROM crawl_runs WHERE job = ? AND status = 'completed'",
      [job], z.object({ mx: z.string().nullable() }), "health:last_ok")[0]?.mx ?? null;
    const counts = db.all("SELECT status, COUNT(*) AS n FROM crawl_runs WHERE job = ? AND started_at >= ? GROUP BY status",
      [job, since], z.object({ status: z.string().nullable(), n: z.number().int() }), "health:counts30");
    let ok30 = 0, fail30 = 0;
    for (const c of counts) {
      if (c.status === "completed") ok30 += c.n;
      else if (c.status !== "running" && c.status !== null) fail30 += c.n;
    }
    out.set(job, { job, last, lastOk, ok30, fail30 });
  }
  return out;
}

// ── per-scraper outcomes (crawl_source_runs, written by job_heartbeat.run_source) ──
/** Scraper key (supply_chain_crawler.py `steps`) → the freshness keys it writes. */
export const SCRAPER_SOURCES: Record<string, { label: string; keys: string[] }> = {
  passmark: { label: "PassMark GPU/CPU price tables", keys: ["sc_prices[passmark]"] },
  newegg: { label: "Newegg retail listings", keys: ["sc_prices[newegg]"] },
  steam_survey: { label: "Steam Hardware Survey page", keys: ["sc_market_share"] },
  trendforce_spot: { label: "TrendForce DRAM spot page", keys: ["sc_dram_spot[ddr4]", "sc_dram_spot[ddr5]"] },
  tsmc_revenue: { label: "TSMC IR monthly revenue", keys: ["sc_demand[tsmc_revenue]"] },
  umc_revenue: { label: "UMC IR monthly revenue", keys: ["sc_demand[umc_revenue]"] },
  nanya_revenue: { label: "Nanya IR monthly revenue", keys: ["sc_demand[nanya_revenue]"] },
  tsmc_quarterly: { label: "TSMC quarterly results", keys: ["sc_fab_metrics"] },
};

const SrcRunRow = z.object({
  id: z.number().int(), run_id: z.number().int().nullable(), source: z.string(), started_at: z.string(),
  status: z.string().nullable(), rows_written: z.number().nullable(), error: z.string().nullable(),
});
type SrcRun = z.infer<typeof SrcRunRow>;
type ScraperState = { source: string; last: SrcRun; lastOk: string | null; ok30: number; total30: number };

const SCRAPER_META: Record<string, { icon: string; text: string }> = {
  ok: { icon: "🟢", text: "OK" }, no_data: { icon: "🟡", text: "NO DATA" }, error: { icon: "🔴", text: "ERROR" },
};
const scraperMeta = (st: string | null) => SCRAPER_META[st ?? ""] ?? { icon: "⚪", text: (st ?? "unknown").toUpperCase() };

/** Empty map on a DB that predates the table (it appears with the first crawl after DH-01 ships). */
function scraperStates(db: Db, now: Date): Map<string, ScraperState> {
  const out = new Map<string, ScraperState>();
  const has = db.all("SELECT name FROM sqlite_master WHERE type='table' AND name='crawl_source_runs'",
    [], z.object({ name: z.string() }), "health:has_src_runs").length > 0;
  if (!has) return out;
  const since = isoSeconds(addDays(now, -30));
  const latest = db.all("SELECT r.* FROM crawl_source_runs r JOIN (SELECT source, MAX(id) AS mid FROM crawl_source_runs GROUP BY source) m " +
    "ON r.id = m.mid ORDER BY r.source", [], SrcRunRow, "health:src_latest");
  for (const last of latest) {
    const lastOk = db.all("SELECT MAX(started_at) AS mx FROM crawl_source_runs WHERE source = ? AND status = 'ok'",
      [last.source], z.object({ mx: z.string().nullable() }), "health:src_ok")[0]?.mx ?? null;
    const c = db.all("SELECT SUM(status = 'ok') AS ok, COUNT(*) AS n FROM crawl_source_runs WHERE source = ? AND started_at >= ?",
      [last.source, since], z.object({ ok: z.number().nullable(), n: z.number().int() }), "health:src_30")[0];
    out.set(last.source, { source: last.source, last, lastOk, ok30: c?.ok ?? 0, total30: c?.n ?? 0 });
  }
  return out;
}

// ── source status ────────────────────────────────────────────────────────────
type SrcStatus = { icon: string; text: string };
/** `producerProblem` — why the feeding job / scraper is unhealthy, or null. */
export function sourceStatus(f: FreshnessEntry, producerProblem: string | null): SrcStatus {
  if (f.rows === "table missing") return { icon: "⚪", text: "MISSING — table not created" };
  if (f.rows === 0) return { icon: "⚪", text: "NO DATA" };
  if (f.empty) return { icon: "🔴", text: `EMPTY — ${f.null_price_pct}% rows have no value` };
  if (f.stale) return { icon: "🔴", text: `STALE — ${f.days_stale}d old (SLA ${f.sla_days}d)` };
  if (producerProblem) return { icon: "🟡", text: `OK — but ${producerProblem}` };
  return { icon: "🟢", text: "OK" };
}

// ── builder ──────────────────────────────────────────────────────────────────
export function buildHealth(db: Db, clock: Clock): DNode {
  const now = clock.hkt;
  const fresh = freshnessReport(db, clock);
  const jobs = jobStates(db, now);
  const scrapers = scraperStates(db, now);
  const feeders = (key: string) => Object.entries(SCRAPER_SOURCES).filter(([, v]) => v.keys.includes(key)).map(([k]) => k);
  const lastOutcome = (j: string) => {
    const s = jobs.get(j);
    return s?.last ? outcome(s.last, now) : null;
  };

  // 1 ── Source table
  type Row = Record<string, string | number>;
  const srcRows: (Row & { _rank: number })[] = Object.entries(fresh).map(([key, f]) => {
    const info = sourceInfo(key);
    const failedJobs = info.jobs.filter((j) => lastOutcome(j) === "failed" || lastOutcome(j) === "abandoned");
    const fed = feeders(key).filter((k) => scrapers.has(k));
    const badScrapers = fed.filter((k) => scrapers.get(k)!.last.status !== "ok");
    const problem = badScrapers.length
      ? `${badScrapers.map((k) => `${k} ${scraperMeta(scrapers.get(k)!.last.status).text.toLowerCase()}`).join(", ")} on last crawl`
      : failedJobs.length ? `last ${failedJobs.join(", ")} crawl failed` : null;
    const st = sourceStatus(f, problem);
    const crawlLines = info.jobs.length === 0 ? [] : info.jobs.flatMap((j) => {
      // A supply_chain source with per-scraper results shows the SCRAPER outcome, not the job's.
      if (j === "supply_chain" && fed.length) return fed.map((k) => {
        const r = scrapers.get(k)!.last, m = scraperMeta(r.status);
        return `${k}: ${m.icon} ${m.text.toLowerCase()} ${hm(r.started_at)}`;
      });
      const s = jobs.get(j);
      if (!s?.last) return [`${j}: never run`];
      const o = OUTCOME_META[outcome(s.last, now)];
      return [`${j}: ${o.icon} ${o.text.toLowerCase()} ${hm(s.last.finished_at ?? s.last.started_at)}`];
    });
    const crawl = crawlLines.length ? crawlLines.join("\n") : "—";
    const charts = info.charts.length === 0
      ? "Not charted — stored for export / backup only"
      : info.charts.map(([t, c]) => `${tabLabel(t)} › ${c}`).join("\n");
    const rank = st.icon === "🔴" ? 0 : st.icon === "🟡" ? 1 : st.icon === "⚪" ? 2 : 3;
    return {
      _rank: rank,
      Status: `${st.icon} ${st.text}`,
      Source: info.mapped ? `${info.label}\n${key}` : key,
      "Latest data": f.max_period ?? "—",
      Age: f.days_stale === null ? "—" : `${f.days_stale} d / SLA ${f.sla_days} d`,
      Rows: typeof f.rows === "number" ? f.rows : 0,
      "Last crawl (HKT)": crawl,
      "Affected charts": charts,
    };
  });
  srcRows.sort((a, b) => a._rank - b._rank);
  const nBad = srcRows.filter((r) => r._rank === 0).length;
  const nWarn = srcRows.filter((r) => r._rank === 1 || r._rank === 2).length;
  const nOk = srcRows.filter((r) => r._rank === 3).length;
  const brokenCharts = new Set(srcRows.filter((r) => r._rank === 0).flatMap((r) =>
    String(r["Affected charts"]).split("\n").filter((c) => !c.startsWith("Not charted"))));

  // Wrapping columns get a floor width so a phone scrolls the table sideways inside its panel
  // instead of squeezing each column to a few characters (UI handbook: tables scroll internally).
  const MIN_W: Record<string, string> = { Status: "150px", Source: "220px", Scraper: "180px", "Last crawl (HKT)": "220px",
    "Affected charts": "300px", "Last note": "200px" };
  const multiline = (col: string) => ({ if: { column_id: col }, whiteSpace: "pre-line", textAlign: "left", minWidth: MIN_W[col] ?? "160px" });
  const statusCond = [
    ODD_ROW,
    { if: { column_id: "Status", filter_query: '{Status} contains "🔴"' }, color: RED, fontWeight: "600" },
    { if: { column_id: "Status", filter_query: '{Status} contains "🟡"' }, color: YELLOW, fontWeight: "600" },
    { if: { column_id: "Status", filter_query: '{Status} contains "🟢"' }, color: GREEN },
    { if: { column_id: "Status", filter_query: '{Status} contains "⚪"' }, color: SUBTEXT },
    { if: { column_id: "Affected charts", filter_query: '{Status} contains "🔴"' }, color: RED },
    multiline("Source"), multiline("Last crawl (HKT)"), multiline("Affected charts"), multiline("Status"),
  ];
  const srcCols = ["Status", "Source", "Latest data", "Age", "Rows", "Last crawl (HKT)", "Affected charts"];
  const srcTable = DataTable({
    data: srcRows.map((r) => Object.fromEntries(Object.entries(r).filter(([k]) => k !== "_rank"))), columns: cols(srcCols), sort_action: "native",
    style_table: { overflowX: "auto" }, style_cell: { ...TBL_CELL("12px", "6px 8px"), verticalAlign: "top" },
    style_header: TBL_HEADER, style_data_conditional: statusCond,
  });

  // 1b ── Scraper table (per-source crawl results)
  const scraperRows: Row[] = Object.entries(SCRAPER_SOURCES).map(([k, v]) => {
    const st = scrapers.get(k);
    const charts = [...new Set(v.keys.flatMap((key) => sourceInfo(key).charts.map(([t, c]) => `${tabLabel(t)} › ${c}`)))];
    if (!st) return { Scraper: `${k}\n${v.label}`, "Last result": "⚪ NOT RECORDED YET", "Rows written": "—", "Last run (HKT)": "—",
      "Last OK": "—", "30-day OK": "—", Error: "", "Affected charts": charts.join("\n") || "Not charted — stored for export / backup only" };
    const m = scraperMeta(st.last.status);
    return {
      Scraper: `${k}\n${v.label}`, "Last result": `${m.icon} ${m.text}`, "Rows written": st.last.rows_written ?? 0,
      "Last run (HKT)": hm(st.last.started_at), "Last OK": st.lastOk ? `${hm(st.lastOk)} (${ageText(hoursSince(st.lastOk, now))})` : "never",
      "30-day OK": st.total30 ? `${st.ok30}/${st.total30}` : "—", Error: st.last.error ?? "",
      "Affected charts": charts.join("\n") || "Not charted — stored for export / backup only",
    };
  });
  const scraperTable = DataTable({
    data: scraperRows, columns: cols(["Last result", "Scraper", "Rows written", "Last run (HKT)", "Last OK", "30-day OK", "Error", "Affected charts"]),
    style_table: { overflowX: "auto" }, style_cell: { ...TBL_CELL("12px", "6px 8px"), verticalAlign: "top" }, style_header: TBL_HEADER,
    style_data_conditional: [ODD_ROW,
      { if: { column_id: "Last result", filter_query: '{Last result} contains "ERROR"' }, color: RED, fontWeight: "600" },
      { if: { column_id: "Last result", filter_query: '{Last result} contains "NO DATA"' }, color: YELLOW, fontWeight: "600" },
      { if: { column_id: "Last result", filter_query: '{Last result} contains "OK"' }, color: GREEN },
      { if: { column_id: "Last result", filter_query: '{Last result} contains "NOT RECORDED"' }, color: SUBTEXT },
      { if: { column_id: "Affected charts", filter_query: '{Last result} contains "ERROR"' }, color: RED },
      { if: { column_id: "Error" }, color: RED, whiteSpace: "normal", textAlign: "left", minWidth: "180px" },
      multiline("Scraper"), multiline("Affected charts")],
  });

  // 2 ── Job table
  const jobRows: Row[] = [...jobs.values()].map((s) => {
    const spec = (JOB_SPECS as Record<string, { label: string; interval_hours: number; overdue_hours: number }>)[s.job];
    const o = s.last ? OUTCOME_META[outcome(s.last, now)] : null;
    const okAge = hoursSince(s.lastOk, now);
    const overdue = spec ? okAge === null || okAge >= spec.overdue_hours : false;
    const total = s.ok30 + s.fail30;
    return {
      Job: jobLabel(s.job),
      "What it crawls": spec?.label ?? "Curated seed reload from products_config.py (every deploy, no network)",
      "Last run": o ? `${o.icon} ${o.text}` : "⚪ NEVER RUN",
      "Last run at (HKT)": hm(s.last?.started_at ?? null),
      "Last success": s.lastOk ? `${hm(s.lastOk)} (${ageText(okAge)})` : "—",
      Schedule: spec ? `every ${spec.interval_hours} h${overdue ? " — ⚠️ OVERDUE" : ""}` : "on deploy",
      "30-day success": total ? `${s.ok30}/${total} (${pyRound((s.ok30 / total) * 100, 0)}%)` : "—",
      "Last note": s.last?.note ?? "",
    };
  });
  const jobTable = DataTable({
    data: jobRows, columns: cols(Object.keys(jobRows[0] ?? { Job: "" })),
    style_table: { overflowX: "auto" }, style_cell: TBL_CELL("12px", "6px 8px"), style_header: TBL_HEADER,
    style_data_conditional: [ODD_ROW,
      { if: { column_id: "Last run", filter_query: '{Last run} contains "FAILED"' }, color: RED, fontWeight: "600" },
      { if: { column_id: "Last run", filter_query: '{Last run} contains "ABANDONED"' }, color: "var(--orange)", fontWeight: "600" },
      { if: { column_id: "Last run", filter_query: '{Last run} contains "SUCCESS"' }, color: GREEN },
      { if: { column_id: "Schedule", filter_query: '{Schedule} contains "OVERDUE"' }, color: RED, fontWeight: "600" },
      multiline("Last note")],
  });

  // 3 ── History (timeline + log)
  const since = isoSeconds(addDays(now, -HISTORY_DAYS));
  const runs = db.all("SELECT * FROM crawl_runs WHERE started_at >= ? ORDER BY id DESC", [since], RunRow, "health:history");
  const jobOrder = [...Object.keys(JOB_SPECS), CURATED];
  const fig = emptyFigure();
  for (const o of ["success", "failed", "abandoned", "running"] as Outcome[]) {
    const sub = runs.filter((r) => outcome(r, now) === o);
    if (!sub.length) continue;
    const m = OUTCOME_META[o];
    addSeries(fig, { provenance: "derived", trace: {
      type: "scatter", mode: "markers", name: `${m.text.toLowerCase()} (${sub.length})`,
      x: sub.map((r) => r.started_at.replace("T", " ")), y: sub.map((r) => jobLabel(r.job ?? "market")),
      marker: { color: m.colour, size: o === "success" ? 9 : 13, symbol: o === "success" ? "circle" : "x",
        line: { color: "var(--surface)", width: 1 } },
      customdata: sub.map((r) => [duration(r), r.tickers_ok ?? 0, r.tickers_attempted ?? 0, (r.note ?? "").slice(0, 140)]),
      hovertemplate: "<b>%{y}</b><br>%{x} HKT<br>" + m.text + " · %{customdata[0]}<br>ok %{customdata[1]} / %{customdata[2]}" +
        "<br>%{customdata[3]}<extra></extra>",
    } });
  }
  pyLayout(fig, { title: `Crawl Runs — last ${HISTORY_DAYS} days (one marker per run)`, height: 320, xaxis_title: "Started (HKT)",
    legend: { orientation: "h", yanchor: "bottom", y: 1.02, x: 1, xanchor: "right" } });
  updateAxis(fig, "yaxis", { type: "category", categoryorder: "array", categoryarray: jobOrder.map(jobLabel).reverse(), title: { text: "" } });
  updateAxis(fig, "xaxis", { type: "date" });

  const logRows: Row[] = runs.slice(0, 200).map((r) => {
    const o = OUTCOME_META[outcome(r, now)];
    return {
      "#": r.id, Job: jobLabel(r.job ?? "market"), Result: `${o.icon} ${o.text}`,
      "Started (HKT)": hm(r.started_at), Duration: duration(r),
      "OK / attempted": r.tickers_attempted ? `${r.tickers_ok ?? 0} / ${r.tickers_attempted}` : "—",
      Note: r.note ?? "",
    };
  });
  const logTable = DataTable({
    data: logRows, columns: cols(["#", "Job", "Result", "Started (HKT)", "Duration", "OK / attempted", "Note"]),
    sort_action: "native", page_size: 25, style_table: { overflowX: "auto" }, style_cell: TBL_CELL("12px", "5px 8px"),
    style_header: TBL_HEADER,
    style_data_conditional: [ODD_ROW,
      { if: { column_id: "Result", filter_query: '{Result} contains "FAILED"' }, color: RED, fontWeight: "600" },
      { if: { column_id: "Result", filter_query: '{Result} contains "ABANDONED"' }, color: "var(--orange)", fontWeight: "600" },
      { if: { column_id: "Result", filter_query: '{Result} contains "SUCCESS"' }, color: GREEN },
      { if: { column_id: "Note" }, textAlign: "left", whiteSpace: "normal", minWidth: "240px" }],
  });

  // ── KPI strip
  const kpi = (label: string, value: string, colour: string, sub: string): DNode => ({
    namespace: "semi_ui", type: "MetricCard", props: { label, value, colour, note: sub },
  });
  const failedJobs = [...jobs.values()].filter((s) => s.last && ["failed", "abandoned"].includes(outcome(s.last, now))).length;
  const badScraperCount = [...scrapers.values()].filter((x) => x.last.status === "error").length;
  const overdueJobs = jobRows.filter((r) => String(r.Schedule).includes("OVERDUE")).length;
  const runs30 = [...jobs.values()].reduce((a, s) => a + s.ok30 + s.fail30, 0);
  const ok30 = [...jobs.values()].reduce((a, s) => a + s.ok30, 0);

  const note = (text: string) => html.P(text, { style: { color: SUBTEXT, fontSize: "12px", margin: "0 0 10px 0" } });
  return html.Div([
    html.Div([
      kpi("Sources healthy", `${nOk} / ${srcRows.length}`, nBad ? RED : nWarn ? YELLOW : GREEN, `${nBad} stale/empty · ${nWarn} warning`),
      kpi("Charts affected", String(brokenCharts.size), brokenCharts.size ? RED : GREEN, "by a stale or empty source"),
      kpi("Crawl problems", String(failedJobs + overdueJobs + badScraperCount), failedJobs + overdueJobs + badScraperCount ? RED : GREEN,
        `${failedJobs} job failed · ${overdueJobs} overdue · ${badScraperCount} scraper error`),
      kpi("30-day crawl success", runs30 ? `${pyRound((ok30 / runs30) * 100, 0)}%` : "—", ok30 === runs30 ? GREEN : YELLOW, `${ok30} of ${runs30} runs`),
    ], { className: "metric-grid" }),
    card([
      sectionTitle("Data Sources — status & affected charts"),
      note("One row per tracked source (the same freshness check as the navbar chip and /api/db-stats). Status: 🔴 stale past its SLA or " +
        "≥50% empty rows · 🟡 data still within SLA but the job feeding it failed its last run · ⚪ no rows · 🟢 OK. " +
        "Supply-chain sources also show their own scraper's last result (table below); a 🟡 names the scraper that errored or wrote nothing."),
      srcTable,
    ]),
    card([sectionTitle("Supply-Chain Scrapers — result of each source on its last crawl"),
      note("Recorded per scraper inside every supply_chain run (crawl_source_runs). 🟢 OK wrote rows · 🟡 NO DATA ran but wrote nothing " +
        "(a validation gate rejected the page, or the page had nothing) · 🔴 ERROR the scraper raised — the other scrapers still ran. " +
        (scrapers.size ? "" : "No per-scraper results yet: the table appears with the first supply-chain crawl after this feature ships.")),
      scraperTable]),
    card([sectionTitle("Crawl Jobs"), note("Scheduled by scheduler.py from JOB_SPECS (job_heartbeat.py). Overdue = no success within the job's overdue window."), jobTable]),
    card([sectionTitle("Crawl History"), responsiveGraph(fig, { displayModeBar: false }),
      runs.length ? logTable : html.P("No crawl runs recorded in this window.", { style: { color: SUBTEXT } })]),
    html.Div(`[Source: crawl_runs heartbeat log + freshness report] [Data Last Checked: ${hm(isoSeconds(now))} HKT]`,
      { className: "source-footer" }),
  ]);
}
