/**
 * One Zod schema per SQLite table (and per derived report). Columns mirror
 * `PRAGMA table_info` on the 2026-11-08 fixture exactly — the Python crawlers
 * own the schema; this file only describes it. If a crawler adds a column, the
 * object schemas below are `.strict()`-free on purpose (extra columns pass),
 * but a renamed or retyped column fails parsing loudly (Hard Rule 2).
 *
 * Types are derived with z.infer — never hand-write a duplicate interface.
 */
import { z } from "zod";

const real = z.number().nullable();
const text = z.string().nullable();
const int = z.number().int().nullable();
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}/, "expected YYYY-MM-DD");

// ── Provenance is a type, not a footnote (prompt constraint 7) ────────────
export const Provenance = z.enum(["published", "derived", "curated", "modeled"]);
export type Provenance = z.infer<typeof Provenance>;

// ── crawler.py tables ─────────────────────────────────────────────────────
export const DailyPriceRow = z.object({
  ticker: z.string(), date: isoDate,
  open: real, high: real, low: real, close: real, volume: real,
});
export const MarketSentimentRow = z.object({
  ticker: z.string(), snapshot_date: isoDate,
  close_price: real, trading_volume: real, implied_volatility: real,
  iv_1m_avg: real, iv_3m_avg: real, iv_6m_avg: real, iv_1y_avg: real,
  days_since_large_drop: int, perf_5d: real, perf_10d: real, perf_1m: real,
});
export const CycleAnalysisRow = z.object({
  ticker: z.string(), snapshot_date: isoDate,
  up_cycle_magnitude: real, up_cycle_duration: int,
  down_cycle_magnitude: real, down_cycle_duration: int, vol_diff_last_cycle: real,
});
export const QuarterlyFinancialsRow = z.object({
  ticker: z.string(), period_end: isoDate,
  revenue: real, gross_profit: real, gross_margin: real, operating_profit: real,
  op_margin: real, rd_expense: real, rd_to_revenue: real, net_profit: real,
  net_margin: real, eps: real,
  /** F-02: retained-but-always-NULL. Never read for display. */
  pe_ratio: real, market_cap: real,
  accounts_receivable: real, ar_turnover: real, inventory: real, inventory_turnover: real,
});
export const TickerValuationRow = z.object({
  ticker: z.string(), snapshot_date: isoDate,
  trailing_pe: real, forward_pe: real, trailing_eps: real, market_cap: real,
  shares_outstanding: real, price_to_book: real, close_price: real, source: text,
});
export const CompanyInfoRow = z.object({
  ticker: z.string(), display_name: text, company_name: text, exchange: text,
  hq_country: text, sector: text, industry: text, currency: text, updated_at: text,
});
export const CrawlRunRow = z.object({
  id: z.number().int(), started_at: z.string(), finished_at: text, status: text,
  tickers_attempted: int, tickers_ok: int, job: text, note: text,
});

// ── IV (two producers, one schema — distinguished only by `source`) ───────
export const OptionsIvRow = z.object({
  ticker: z.string(), snapshot_date: isoDate,
  iv_current: real, iv_1m_avg: real, iv_1q_avg: real, iv_6m_avg: real, iv_1y_avg: real,
  iv_pct_vs_1y: real, iv_52w_high: real, iv_52w_low: real, source: text,
});
export const OptionsIvHistoryRow = z.object({
  ticker: z.string(), date: isoDate, iv_pct: real, source: text,
});

// ── supply_chain_crawler.py tables ────────────────────────────────────────
export const ScProductRow = z.object({
  model_id: z.string(), category: text, name: text, brand: text, process_node: text,
  manufacturer: text, msrp_usd: real, specs_json: text,
});
export const ScPriceRow = z.object({
  model_id: z.string(), date: isoDate, source: z.string(),
  price_usd: real, passmark_score: real, price_perf: real, in_stock: int,
});
export const ScDramSpotRow = z.object({
  product_type: z.string(), spec_label: z.string(),
  period: z.string().regex(/^\d{4}-\d{2}/), price_usd: real, source: text,
});
export const ScMarketShareRow = z.object({
  model_name: z.string(), period: z.string(), share_pct: real, source: text,
});
export const ScFabMetricsRow = z.object({
  company: z.string(), metric_key: z.string(), detail: z.string(), period: z.string(),
  value: real, unit: text, source: text, notes: text,
});
export const ScDemandIndicatorRow = z.object({
  indicator_key: z.string(), metric_label: z.string(), period: z.string(),
  period_type: z.string(), value: real, unit: text, yoy_pct: real, seq_pct: real,
  source: text, notes: text,
});

// ── aggregate query rows used by the derived reports ──────────────────────
export const CountMaxRow = z.object({ n: z.number().int(), mx: z.union([z.string(), z.number()]).nullable() });
export const KeyCountMaxRow = z.object({
  k: z.union([z.string(), z.number()]), n: z.number().int(),
  priced: z.number().int().optional(), mx: z.union([z.string(), z.number()]).nullable(),
});
export const SeriesPointRow = z.object({
  k: z.union([z.string(), z.number()]).nullable(),
  p: z.union([z.string(), z.number()]).nullable(),
  v: z.number(),
  s: z.string().nullable(),
});
export const TickerDateCloseRow = z.object({ ticker: z.string(), date: isoDate, close: real });
export const DateCloseRow = z.object({ date: isoDate, close: real });
export const IvBadgeRow = z.object({ source: text, d: z.string().nullable(), n: z.number().int() });

// ── derived reports (what /api/db-stats and the badges serialise) ─────────
export const FreshnessEntry = z.object({
  rows: z.union([z.number().int(), z.literal("table missing")]),
  max_period: z.string().nullable(),
  days_stale: z.number().int().nullable(),
  sla_days: z.number().int(),
  stale: z.boolean(),
  null_price_pct: z.number().optional(),
  empty: z.boolean().optional(),
  unhealthy: z.boolean().optional(),
});
export const FreshnessReport = z.record(z.string(), FreshnessEntry);

export const ConsistencyFlag = z.object({
  series: z.string(), rule: z.enum(["frozen", "synthetic_glide", "geometric_glide", "divergence"]),
  detail: z.string(), severity: z.enum(["high", "expected"]),
});
export const ConsistencyReport = z.object({
  flags: z.array(ConsistencyFlag), high: z.number().int().optional(),
  expected: z.number().int().optional(), checked: z.number().int(), ok: z.boolean(),
  error: z.string().optional(),
});

export const JobEntry = z.object({
  label: z.string(), interval_hours: z.number(), overdue_hours: z.number(),
  last_success: z.string().nullable(), age_hours: z.number().nullable(),
  due: z.boolean(), overdue: z.boolean(), never_run: z.boolean(), last_status: z.string().nullable(),
});
export const JobReport = z.record(z.string(), JobEntry);

export const StatusChip = z.object({
  icon: z.string(), label: z.string(), colour: z.string(), detail: z.string(),
});

export type DailyPriceRow = z.infer<typeof DailyPriceRow>;
export type MarketSentimentRow = z.infer<typeof MarketSentimentRow>;
export type TickerValuationRow = z.infer<typeof TickerValuationRow>;
export type OptionsIvRow = z.infer<typeof OptionsIvRow>;
export type ScDramSpotRow = z.infer<typeof ScDramSpotRow>;
export type FreshnessEntry = z.infer<typeof FreshnessEntry>;
export type FreshnessReport = z.infer<typeof FreshnessReport>;
export type ConsistencyFlag = z.infer<typeof ConsistencyFlag>;
export type ConsistencyReport = z.infer<typeof ConsistencyReport>;
export type JobEntry = z.infer<typeof JobEntry>;
export type JobReport = z.infer<typeof JobReport>;
export type StatusChip = z.infer<typeof StatusChip>;
