/**
 * Memory-price helpers — ports of dashboard.py _MEM_* constants,
 * _mem_normalize_usd_per_gb, _mem_break_gaps, _mem_yoy.
 *
 * Missing values are NaN inside this module, exactly as in the pandas frames
 * (to_numeric(errors="coerce") turns NULL into NaN). Nothing is interpolated,
 * forward-filled or defaulted: a gap stays a gap (a NaN row lifts Plotly's pen),
 * and a YoY with no genuine 12–15-month anchor is null → rendered "—".
 */
import { addMonths } from "./clock";
import type { ScDramSpotRow } from "./schemas";

export const MEM_DIE_GB: Record<string, number> = { DDR4: 1.0, DDR5: 2.0, LPDDR5X: 2.0, HBM3: 1.0, HBM3E: 1.0 };
export const MEM_COLORS: Record<string, string> = {
  DDR4: "#1896FA", DDR5: "#2EA843", HBM3: "#CC5DE8", HBM3E: "#FF5858", LPDDR5X: "#B58D00",
};
export const MEM_UNIT_LABEL: Record<string, string> = {
  DDR4: "$/die", DDR5: "$/die", LPDDR5X: "$/die", HBM3: "$/GB", HBM3E: "$/GB",
};
export const MEM_SPECS: Record<string, { bandwidth_gbs: number; capacity_gb: number; config: string; bw_basis: string; class: "Commodity DRAM" | "HBM" }> = {
  DDR4: { bandwidth_gbs: 25.6, capacity_gb: 1, config: "8Gb 1Gx8 die", bw_basis: "per DDR4-3200 DIMM (64-bit bus)", class: "Commodity DRAM" },
  DDR5: { bandwidth_gbs: 51.2, capacity_gb: 2, config: "16Gb 2Gx8 die", bw_basis: "per DDR5-6400 DIMM (64-bit bus)", class: "Commodity DRAM" },
  HBM3: { bandwidth_gbs: 819.0, capacity_gb: 48, config: "8-Hi stack", bw_basis: "per 8-Hi stack (1024-bit bus)", class: "HBM" },
  HBM3E: { bandwidth_gbs: 1177.0, capacity_gb: 96, config: "12-Hi stack", bw_basis: "per 12-Hi stack (1024-bit bus)", class: "HBM" },
};
export const MEM_ORDER = ["DDR4", "DDR5", "HBM3", "HBM3E", "LPDDR5X"] as const;
export const MEM_GAP_MONTHS = 3;

export type MemRow = Omit<ScDramSpotRow, "price_usd"> & {
  price_usd: number; // NaN when missing
  die_gb: number;
  price_usd_gb: number; // NaN when missing
  period_dt: Date;
};

/** Stable sort (pandas multi-key sort_values is stable; single-key is not
 *  guaranteed — see finding P-09 — but no fixture series has duplicate periods). */
const stableSort = <T>(xs: T[], cmp: (a: T, b: T) => number) =>
  xs.map((x, i) => [x, i] as const).sort((a, b) => cmp(a[0], b[0]) || a[1] - b[1]).map(([x]) => x);
const cmpStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** `_mem_normalize_usd_per_gb(df)` — returns a sorted copy; input untouched. */
export function memNormalize(rows: readonly ScDramSpotRow[]): MemRow[] {
  const out = rows.map((r): MemRow => {
    const price = r.price_usd === null ? NaN : r.price_usd;
    const die = MEM_DIE_GB[r.product_type] ?? 1.0;
    const p7 = String(r.period).slice(0, 7);
    return { ...r, price_usd: price, die_gb: die, price_usd_gb: price / die,
             period_dt: new Date(`${p7}-01T00:00:00Z`) };
  });
  return stableSort(out, (a, b) => cmpStr(a.product_type, b.product_type) || cmpStr(String(a.period), String(b.period)));
}

const monthsBetween = (a: Date, b: Date) =>
  (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + b.getUTCMonth() - a.getUTCMonth();

/** `_mem_break_gaps(grp, gap_months)` — inserts a NaN row where a series skips
 *  more than `gapMonths`. The blank row copies `prev` (incl. its `period`
 *  string, as the Python does) with period_dt = prev + 1 month. */
export function memBreakGaps(grp: readonly MemRow[], gapMonths = MEM_GAP_MONTHS): MemRow[] {
  const sorted = stableSort([...grp], (a, b) => a.period_dt.getTime() - b.period_dt.getTime());
  if (sorted.length < 2) return sorted;
  const out: MemRow[] = [];
  let prev: MemRow | null = null;
  for (const row of sorted) {
    if (prev !== null && monthsBetween(prev.period_dt, row.period_dt) > gapMonths) {
      out.push({ ...prev, period_dt: addMonths(prev.period_dt, 1), price_usd: NaN, price_usd_gb: NaN });
    }
    out.push(row);
    prev = row;
  }
  return out;
}

export type MemYoy = { latest: MemRow | null; price1yAgo: number | null; yoyPct: number | null };

/** `_mem_yoy(grp, price_col)` — anchored on the SERIES' own latest period,
 *  12–15-month lookback; anything else is null ("—"). */
export function memYoy(grp: readonly MemRow[], priceCol: "price_usd_gb" | "price_usd" = "price_usd_gb"): MemYoy {
  const g = stableSort([...grp], (a, b) => a.period_dt.getTime() - b.period_dt.getTime())
    .filter((r) => !Number.isNaN(r[priceCol]));
  if (g.length === 0) return { latest: null, price1yAgo: null, yoyPct: null };
  const latest = g[g.length - 1];
  const target = addMonths(latest.period_dt, -12).getTime();
  const floor = addMonths(latest.period_dt, -15).getTime();
  const prior = g.filter((r) => r.period_dt.getTime() <= target && r.period_dt.getTime() >= floor);
  if (prior.length === 0) return { latest, price1yAgo: null, yoyPct: null };
  const pPrev = prior[prior.length - 1][priceCol];
  if (Number.isNaN(pPrev) || pPrev <= 0 || Number.isNaN(latest[priceCol])) return { latest, price1yAgo: null, yoyPct: null };
  return { latest, price1yAgo: pPrev, yoyPct: (latest[priceCol] / pPrev - 1) * 100 };
}

