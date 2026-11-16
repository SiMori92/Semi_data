/**
 * Ports of dashboard.py: _FRESHNESS_SPEC, _SC_*_SLA, _period_end_date,
 * _freshness_report, _stale_sources. Same contract: never throws for a missing
 * table (reported as "table missing"), one helper backs every surface.
 */
import type { Clock } from "./clock";
import { ymd } from "./clock";
import type { Db } from "./db";
import { pyFloatStr, pyRound } from "./pynum";
import { CountMaxRow, KeyCountMaxRow, type FreshnessEntry, type FreshnessReport } from "./schemas";

type Kind = "date" | "month" | "quarter";

export const FRESHNESS_SPEC: ReadonlyArray<readonly [string, string, Kind, number]> = [
  ["daily_prices", "date", "date", 4],
  ["market_sentiment", "snapshot_date", "date", 4],
  ["cycle_analysis", "snapshot_date", "date", 4],
  ["quarterly_financials", "period_end", "date", 120],
  ["options_iv", "snapshot_date", "date", 4],
  ["ticker_valuation_history", "snapshot_date", "date", 4],
  ["sc_market_share", "period", "month", 120],
  ["sc_fab_metrics", "period", "quarter", 150],
];
export const SC_PRICE_SLA: Record<string, number> = { newegg: 7, passmark: 7, curated: 45 };
export const SC_DEMAND_SLA: Record<string, number> = {
  tsmc_revenue: 40, umc_revenue: 40, nanya_revenue: 70, korea_chip_exports_20d: 20,
  wsts_billings: 75, semi_wwsems_billings: 160,
};
export const SC_DEMAND_KIND: Record<string, Kind> = { semi_wwsems_billings: "quarter" };
export const SC_DRAM_SLA: Record<string, number> = { DDR4: 45, DDR5: 45, HBM3: 75, HBM3E: 75 };

const lastDayOfMonth = (y: number, m0: number) => new Date(Date.UTC(y, m0 + 1, 0));

/** pd.to_datetime(v[:10]).normalize() for the shapes this DB holds. */
function parseDateish(v: string): Date | null {
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(v);
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.getUTCMonth() === +m[2] - 1 ? d : null;
  }
  m = /^(\d{4})-(\d{1,2})$/.exec(v);
  if (m && +m[2] >= 1 && +m[2] <= 12) return new Date(Date.UTC(+m[1], +m[2] - 1, 1));
  m = /^(\d{4})$/.exec(v);
  if (m) return new Date(Date.UTC(+m[1], 0, 1));
  return null;
}

/** `_period_end_date(value, kind)` → the calendar date a period stops describing. */
export function periodEndDate(value: unknown, kind: Kind): Date | null {
  if (value === null || value === undefined) return null;
  const v = String(value).trim();
  if (kind === "month") {
    // pd.Period(v[:7], freq="M")
    const s = v.slice(0, 7);
    const m = /^(\d{4})-(\d{1,2})$/.exec(s) ?? /^(\d{4})(\d{2})$/.exec(s);
    if (m && +m[2] >= 1 && +m[2] <= 12) return lastDayOfMonth(+m[1], +m[2] - 1);
    const q = /^(\d{4})Q([1-4])$/.exec(s);
    if (q) return lastDayOfMonth(+q[1], +q[2] * 3 - 1); // Period("2025Q3", M) → quarter end month
    return null;
  }
  if (kind === "quarter") {
    // pd.Period(v.replace("-", ""), freq="Q")
    const s = v.replace(/-/g, "");
    const m = /^(\d{4})Q([1-4])$/.exec(s);
    if (m) return lastDayOfMonth(+m[1], +m[2] * 3 - 1);
    return null;
  }
  return parseDateish(v.slice(0, 10));
}

const dayDiff = (a: Date, b: Date) => Math.floor((a.getTime() - b.getTime()) / 86400_000);

function strOrNull(mx: string | number | null): string | null {
  if (mx === null) return null;
  return typeof mx === "number" ? (Number.isInteger(mx) ? String(mx) : pyFloatStr(mx)) : mx;
}

/** `_freshness_report()` — keys in the same insertion order as the Python dict. */
export function freshnessReport(db: Db, clock: Clock): FreshnessReport {
  const today = new Date(`${ymd(clock.serverLocal)}T00:00:00Z`); // pd.Timestamp.today().normalize()
  const report: FreshnessReport = {};

  const entry = (key: string, mx: string | number | null, kind: Kind, sla: number, rows: number,
                 extra?: { null_price_pct: number }) => {
    const end = periodEndDate(mx, kind);
    const days = end !== null ? dayDiff(today, end) : null;
    const rec: FreshnessEntry = {
      rows, max_period: strOrNull(mx), days_stale: days, sla_days: sla,
      stale: days !== null && days > sla,
    };
    if (extra) Object.assign(rec, extra);
    rec.empty = (rec.null_price_pct ?? 0) >= 50;
    rec.unhealthy = rec.stale || rec.empty;
    report[key] = rec;
  };

  for (const [table, col, kind, sla] of FRESHNESS_SPEC) {
    const rows = db.all(`SELECT COUNT(*) AS n, MAX(${col}) AS mx FROM ${table}`, [], CountMaxRow, `freshness:${table}`);
    if (rows.length === 0) {
      report[table] = { rows: "table missing", max_period: null, days_stale: null, sla_days: sla, stale: false };
      continue;
    }
    entry(table, rows[0].mx, kind, sla, rows[0].n);
  }

  for (const r of db.all("SELECT source AS k, COUNT(*) AS n, COUNT(price_usd) AS priced, MAX(date) AS mx " +
                         "FROM sc_prices GROUP BY source", [], KeyCountMaxRow, "freshness:sc_prices")) {
    const src = String(r.k);
    const n = r.n;
    const prc = r.priced ?? 0;
    entry(`sc_prices[${src}]`, r.mx, "date", SC_PRICE_SLA[src] ?? 45, n,
      { null_price_pct: n ? pyRound(((n - prc) / n) * 100, 1) : 0.0 });
  }

  for (const r of db.all("SELECT product_type AS k, COUNT(*) AS n, MAX(period) AS mx " +
                         "FROM sc_dram_spot GROUP BY product_type", [], KeyCountMaxRow, "freshness:sc_dram_spot")) {
    const pt = String(r.k);
    entry(`sc_dram_spot[${pt.toLowerCase()}]`, r.mx, "month", SC_DRAM_SLA[pt] ?? 45, r.n);
  }

  for (const r of db.all("SELECT indicator_key AS k, COUNT(*) AS n, MAX(period) AS mx " +
                         "FROM sc_demand_indicators GROUP BY indicator_key", [], KeyCountMaxRow, "freshness:sc_demand")) {
    const key = String(r.k);
    entry(`sc_demand[${key}]`, r.mx, SC_DEMAND_KIND[key] ?? "month", SC_DEMAND_SLA[key] ?? 45, r.n);
  }
  return report;
}

/** `_stale_sources(rep)` — unhealthy keys, worst (most days stale) first; stable. */
export function staleSources(rep: FreshnessReport): string[] {
  return Object.entries(rep)
    .filter(([, v]) => v.unhealthy)
    .sort((a, b) => (b[1].days_stale ?? 0) - (a[1].days_stale ?? 0))
    .map(([k]) => k);
}
