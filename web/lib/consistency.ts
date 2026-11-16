/**
 * Port of dashboard.py `_consistency_report()` (BACKLOG SC-12). Advisory shape
 * checks — flags, never deletes. Same four rules, same thresholds, same message
 * strings (formatted with the Python-faithful helpers in pynum.ts).
 */
import type { Db } from "./db";
import { pyFloatStr, pyG, pyPercent0, pySignedFixed } from "./pynum";
import { SeriesPointRow, type ConsistencyFlag, type ConsistencyReport } from "./schemas";
import { z } from "zod";

export const CONSISTENCY_SPEC: ReadonlyArray<readonly [string, string, string, string, string, string]> = [
  ["sc_dram_spot", "sc_dram_spot", "product_type", "period", "price_usd", "source"],
  ["sc_market_share", "sc_market_share", "model_name", "period", "share_pct", "source"],
  ["sc_demand", "sc_demand_indicators", "indicator_key", "period", "value", "source"],
  ["sc_fab_metrics", "sc_fab_metrics", "company", "period", "value", "source"],
  ["sc_prices", "sc_prices", "model_id", "date", "price_usd", "source"],
  ["fin_valuation", "quarterly_financials", "ticker", "period_end", "pe_ratio", "'yfinance (vendor feed)'"],
  ["fin_revenue", "quarterly_financials", "ticker", "period_end", "revenue", "'yfinance (vendor feed)'"],
];

const MODELED_MARKERS = ["modeled", "modelled", "estimate", "curated"];
export const shapeSeverity = (source: string | null): "high" | "expected" => {
  const s = (source ?? "").toLowerCase();
  return MODELED_MARKERS.some((m) => s.includes(m)) ? "expected" : "high";
};

const FLAT_MIN_POINTS = 6;
const GLIDE_MIN_STEPS = 5;
const GLIDE_REL_TOL = 0.01;
const DIVERGE_YOY_PCT = 20.0;

/** Python str() of a SQLite cell as pandas would hand it to str(). */
const pyStr = (x: string | number | null) => (x === null ? "None" : typeof x === "number" ? (Number.isInteger(x) ? String(x) : pyFloatStr(x)) : x);

/** Python `<` on str — code-point order (NOT localeCompare). */
const cmpStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/**
 * `max(set(srcs), key=srcs.count)`. With a tie Python's answer depends on set
 * iteration order (string hashing is randomised per process), so the Python
 * itself is non-deterministic there. We return the first-seen of the tied
 * values and surface ties via `onTie` (WEB-01 finding P-07).
 */
function modeSource(srcs: string[], onTie?: (vals: string[]) => void): string {
  const counts = new Map<string, number>();
  for (const s of srcs) counts.set(s, (counts.get(s) ?? 0) + 1);
  let best = "";
  let bestN = -1;
  const tied: string[] = [];
  for (const [s, n] of counts) {
    if (n > bestN) { best = s; bestN = n; tied.length = 0; tied.push(s); }
    else if (n === bestN) tied.push(s);
  }
  if (tied.length > 1 && onTie) onTie(tied);
  return best;
}

export function consistencyReport(db: Db, onTie?: (series: string, vals: string[]) => void): ConsistencyReport {
  const flags: ConsistencyFlag[] = [];
  let checked = 0;
  try {
    let wstsYoy: number | null = null;
    const w = db.all(
      "SELECT value, period FROM sc_demand_indicators WHERE indicator_key='wsts_billings' AND value IS NOT NULL ORDER BY period",
      [], z.object({ value: z.number(), period: z.string() }), "consistency:wsts");
    if (w.length >= 2) {
      const first = w[0].value;
      const last = w[w.length - 1].value;
      if (first > 0) wstsYoy = (last / first - 1) * 100;
    }

    for (const [label, table, keyCol, perCol, valCol, srcCol] of CONSISTENCY_SPEC) {
      const df = db.all(
        `SELECT ${keyCol} AS k, ${perCol} AS p, ${valCol} AS v, ${srcCol} AS s FROM ${table} WHERE ${valCol} IS NOT NULL ORDER BY k, p`,
        [], SeriesPointRow, `consistency:${label}`);
      if (df.length === 0) continue;

      // pandas groupby("k"): sorted keys, NaN keys dropped, row order kept within a group.
      const groups = new Map<string, typeof df>();
      for (const r of df) {
        if (r.k === null) continue;
        const key = pyStr(r.k);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key)!.push(r);
      }
      for (const key of [...groups.keys()].sort(cmpStr)) {
        const grp = groups.get(key)!;
        const vals = grp.map((r) => r.v);
        const pers = grp.map((r) => pyStr(r.p));
        if (vals.length < 3) continue;
        checked += 1;
        const sid = `${label}[${key}]`;
        const srcs = grp.map((r) => r.s).filter((s): s is string => s !== null);
        const sev = shapeSeverity(srcs.length ? modeSource(srcs, (t) => onTie?.(sid, t)) : "");
        const flag = (rule: ConsistencyFlag["rule"], detail: string) =>
          flags.push({ series: sid, rule, detail, severity: sev });

        // RULE 1 — frozen
        const tail = vals.slice(-FLAT_MIN_POINTS);
        if (tail.length >= FLAT_MIN_POINTS && new Set(tail).size === 1) {
          let msg = `${tail.length} consecutive identical values (${pyG(tail[tail.length - 1])}) through ${pers[pers.length - 1]}`;
          if (wstsYoy !== null && Math.abs(wstsYoy) > DIVERGE_YOY_PCT) msg += ` while WSTS billings moved ${pySignedFixed(wstsYoy, 0)}%`;
          flag("frozen", msg);
        }

        // RULE 2 — synthetic glide (constant difference)
        const diffs = vals.slice(1).map((b, i) => b - vals[i]);
        let run = 1, best = 1, bestAt = diffs.length - 1;
        for (let i = 1; i < diffs.length; i++) {
          const prev = diffs[i - 1], cur = diffs[i];
          const same = Math.abs(cur - prev) <= GLIDE_REL_TOL * Math.max(Math.abs(prev), 1e-9);
          run = same ? run + 1 : 1;
          if (run > best) { best = run; bestAt = i; }
        }
        if (best >= GLIDE_MIN_STEPS && Math.abs(diffs[bestAt]) > 0) {
          flag("synthetic_glide",
            `${best} consecutive steps of ~${pyG(diffs[bestAt], true)} (<${pyPercent0(GLIDE_REL_TOL)} variation) ending ${pers[bestAt + 1]}`);
        }

        // RULE 2b — geometric glide (constant ratio). NB: zero bases are dropped
        // BEFORE indexing, so `pers[rat + 1]` can be misaligned after a zero —
        // the Python does exactly this; kept for parity (finding P-08).
        const ratios: number[] = [];
        for (let i = 0; i + 1 < vals.length; i++) if (vals[i] !== 0) ratios.push(vals[i + 1] / vals[i]);
        if (ratios.length >= GLIDE_MIN_STEPS) {
          let rrun = 1, rbest = 1, rat = ratios.length - 1;
          for (let i = 1; i < ratios.length; i++) {
            const same = Math.abs(ratios[i] - ratios[i - 1]) <= GLIDE_REL_TOL * Math.abs(ratios[i - 1]);
            rrun = same ? rrun + 1 : 1;
            if (rrun > rbest) { rbest = rrun; rat = i; }
          }
          if (rbest >= GLIDE_MIN_STEPS && Math.abs(ratios[rat] - 1.0) > 1e-6) {
            flag("geometric_glide",
              `${rbest} consecutive steps of ~${pySignedFixed((ratios[rat] - 1) * 100, 2)}% (<${pyPercent0(GLIDE_REL_TOL)} variation) ending ${pers[rat + 1]}`);
          }
        }

        // RULE 3 — divergence
        if (wstsYoy !== null && wstsYoy > DIVERGE_YOY_PCT && diffs.length >= FLAT_MIN_POINTS &&
            diffs.slice(-FLAT_MIN_POINTS).every((d) => d < 0)) {
          flag("divergence",
            `fell for ${FLAT_MIN_POINTS} consecutive periods to ${pyG(vals[vals.length - 1])} (${pers[pers.length - 1]}) while WSTS billings moved ${pySignedFixed(wstsYoy, 0)}%`);
        }
      }
    }
  } catch (e) {
    return { flags: [], checked: 0, ok: true, error: String((e as Error).message ?? e) };
  }

  flags.sort((a, b) => {
    const ah = a.severity !== "high" ? 1 : 0, bh = b.severity !== "high" ? 1 : 0;
    return ah - bh || cmpStr(a.rule, b.rule) || cmpStr(a.series, b.series);
  });
  const high = flags.filter((f) => f.severity === "high").length;
  return { flags, high, expected: flags.length - high, checked, ok: high === 0 };
}

