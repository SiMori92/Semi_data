/**
 * The handful of pandas operations the Supply Chain / Financials / Sentiment
 * tabs rely on, ported with pandas' semantics (NaN-skipping, ordering, Kahan
 * sums) rather than "whatever is natural in JS". Each names its pandas source.
 */
import { npSum } from "./pynum";

/** pandas _libs.groupby.group_mean — Kahan-compensated sum / count, NaN skipped. */
export function kahanMean(xs: readonly number[]): number {
  let sum = 0, comp = 0, n = 0;
  for (const v of xs) {
    if (Number.isNaN(v)) continue;
    n++;
    const y = v - comp;
    const t = sum + y;
    comp = t - sum - y;
    if (Number.isNaN(comp)) comp = 0; // inf handling, as pandas
    sum = t;
  }
  return n === 0 ? NaN : sum / n;
}

/** pandas _libs.groupby.group_sum — Kahan-compensated, NaN skipped (0 when empty). */
export function kahanSum(xs: readonly number[]): number {
  let sum = 0, comp = 0;
  for (const v of xs) {
    if (Number.isNaN(v)) continue;
    const y = v - comp;
    const t = sum + y;
    comp = t - sum - y;
    if (Number.isNaN(comp)) comp = 0;
    sum = t;
  }
  return sum;
}

/** groupby(...).last() for one column — last NON-NaN value (pandas group_last). */
export const lastValid = <T>(xs: readonly T[], isNa: (v: T) => boolean): T | undefined => {
  for (let i = xs.length - 1; i >= 0; i--) if (!isNa(xs[i])) return xs[i];
  return undefined;
};

export type MonthSeries = { index: Date[]; values: number[] };
const monthStart = (d: Date) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
const ym = (d: Date) => d.getUTCFullYear() * 12 + d.getUTCMonth();

/** `series.resample("MS").<agg>().dropna()` — every month bin between min and
 *  max is created, empty bins are NaN and then dropped. */
export function resampleMS(dates: readonly Date[], values: readonly number[], agg: "mean" | "last"): MonthSeries {
  if (dates.length === 0) return { index: [], values: [] };
  const bins = new Map<number, number[]>();
  for (let i = 0; i < dates.length; i++) {
    const k = ym(dates[i]);
    if (!bins.has(k)) bins.set(k, []);
    bins.get(k)!.push(values[i]);
  }
  const keys = [...bins.keys()];
  const lo = Math.min(...keys), hi = Math.max(...keys);
  const out: MonthSeries = { index: [], values: [] };
  for (let k = lo; k <= hi; k++) {
    const b = bins.get(k) ?? [];
    const v = agg === "mean" ? kahanMean(b) : (lastValid(b, Number.isNaN) ?? NaN);
    if (Number.isNaN(v)) continue;
    out.index.push(new Date(Date.UTC(Math.floor(k / 12), k % 12, 1)));
    out.values.push(v);
  }
  return out;
}
export { monthStart };

/** pd.concat([a, b], axis=1).dropna() — outer join on the (sorted) index, keep rows present in both. */
export function alignInner(a: MonthSeries, b: MonthSeries): { index: Date[]; x: number[]; y: number[] } {
  const bm = new Map(b.index.map((d, i) => [d.getTime(), b.values[i]]));
  const out = { index: [] as Date[], x: [] as number[], y: [] as number[] };
  const idx = [...new Set([...a.index.map((d) => d.getTime()), ...b.index.map((d) => d.getTime())])].sort((p, q) => p - q);
  const am = new Map(a.index.map((d, i) => [d.getTime(), a.values[i]]));
  for (const t of idx) {
    const x = am.get(t), y = bm.get(t);
    if (x === undefined || y === undefined || Number.isNaN(x) || Number.isNaN(y)) continue;
    out.index.push(new Date(t)); out.x.push(x); out.y.push(y);
  }
  return out;
}

/** Series.corr(other) — pandas 3.x nanops._pearson_corr (centred, scaled, dot). */
export function pearson(a: readonly number[], b: readonly number[]): number {
  if (a.length < 2) return NaN;
  const ma = npSum(a) / a.length, mb = npSum(b) / b.length;
  let x = a.map((v) => v - ma), y = b.map((v) => v - mb);
  const sa = Math.max(...x.map(Math.abs)), sb = Math.max(...y.map(Math.abs));
  if (sa === 0 || sb === 0) return NaN;
  x = x.map((v) => v / sa); y = y.map((v) => v / sb);
  const fact = x.length - 1;
  const dot = (p: number[], q: number[]) => npSum(p.map((v, i) => v * q[i]));
  let div = Math.sqrt(dot(x, x) / fact);
  if (div === 0) return NaN;
  const r = dot(x, y) / fact / div;
  div = Math.sqrt(dot(y, y) / fact);
  if (div === 0) return NaN;
  return Math.min(1, Math.max(-1, r / div));
}

/** x.rolling(window, min_periods).corr(y) on already-aligned, NaN-free series.
 *  Same estimator as pandas' roll_corr: (E[xy]−E[x]E[y])·n/(n−1) / √(var_x·var_y),
 *  ddof=1. pandas computes it with an online add/remove kernel (compiled; source
 *  not shipped), so agreement is to ~1e-12, not bit-for-bit (documented). */
export function rollingCorr(x: readonly number[], y: readonly number[], window: number, minPeriods: number): number[] {
  return x.map((_, i) => {
    const lo = Math.max(0, i - window + 1);
    const xs = x.slice(lo, i + 1), ys = y.slice(lo, i + 1);
    const n = xs.length;
    if (n < minPeriods) return NaN;
    const mx = xs.reduce((s, v) => s + v, 0) / n, my = ys.reduce((s, v) => s + v, 0) / n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let k = 0; k < n; k++) {
      const dx = xs[k] - mx, dy = ys[k] - my;
      sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
    }
    const cov = sxy / (n - 1), vx = sxx / (n - 1), vy = syy / (n - 1);
    const den = Math.sqrt(vx * vy);
    return den === 0 ? NaN : cov / den;
  });
}

/** pandas Timestamp.isoformat() for a midnight date: "2023-01-01T00:00:00". */
export const isoTs = (d: Date) => d.toISOString().slice(0, 19);

/** Stable sort (pandas multi-key sorts are stable; we use stable everywhere). */
export const stableSort = <T>(xs: readonly T[], cmp: (a: T, b: T) => number) =>
  xs.map((x, i) => [x, i] as const).sort((a, b) => cmp(a[0], b[0]) || a[1] - b[1]).map(([x]) => x);
export const cmpStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** Python `str()` of a value as pandas would hand it (ints without ".0"). */
export const isNa = (v: unknown) => v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));
