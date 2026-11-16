/**
 * `_IV_SOURCE_META` / `_iv_source_meta` / `_iv_source_summary`.
 * Labels derive from the row's own `source` — never hardcode a producer name in
 * the UI (CLAUDE.md §9 IV-01). Matched by PREFIX so "(proxy:GLD)" resolves;
 * unknown values pass through unrelabelled.
 */
import type { Provenance } from "./schemas";

export type IvMeta = readonly [short: string, description: string, isPublished: boolean];

export const IV_SOURCE_META: ReadonlyArray<readonly [string, IvMeta]> = [
  ["derived-yfinance-atm30", ["IV30*", "Derived — 30d ATM constant-maturity interpolation over Yahoo option chains", false]],
  ["Deribit DVOL", ["DVOL", "Deribit DVOL 30-day implied-volatility index (published)", true]],
  ["IBKR", ["IBKR", "Interactive Brokers real-time IV (relayed from local TWS/Gateway)", true]],
  ["relay", ["IBKR", "Interactive Brokers real-time IV (relayed from local TWS/Gateway)", true]],
];

export function ivSourceMeta(source: unknown): IvMeta {
  if (typeof source !== "string" || source === "") return ["IV", "Unlabelled source", false];
  for (const [prefix, meta] of IV_SOURCE_META) if (source.startsWith(prefix)) return meta;
  return [source.slice(0, 12), source, false];
}

/** Provenance of one IV value, for the chart/table primitives. */
export const ivProvenance = (source: unknown): Provenance => (ivSourceMeta(source)[2] ? "published" : "derived");

/** `_iv_source_summary(df)` → [joined description, all_published]. */
export function ivSourceSummary(sources: ReadonlyArray<string | null> | null): [string, boolean] {
  if (sources === null || sources.length === 0) return ["—", false];
  const uniq = [...new Set(sources.filter((s): s is string => s !== null))].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const metas = uniq.map(ivSourceMeta);
  const desc: string[] = [];
  for (const [, d] of metas) if (!desc.includes(d)) desc.push(d);
  return [desc.join(" · "), metas.length ? metas.every(([, , p]) => p) : false];
}
