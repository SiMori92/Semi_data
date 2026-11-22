/**
 * Constants mirrored from config.py and the top of dashboard.py. These are
 * presentation constants, not business data — but they are still mirrored, so
 * tests/parity.config.test.ts checks them against the golden dump where the dump
 * carries them (ticker list, colours used in figures, job labels).
 */
// UI-01: theme colours are CSS-variable REFERENCES, resolved by the browser for
// the current theme (light default / dark option). Values live in app/tokens.css,
// mirrored in lib/theme.ts. Plotly figures may carry these too — PlotlyChart
// resolves them before drawing (lib/theme.ts resolveCssVars).
import { cssVar } from "./theme";

export const BG = cssVar("bg");
export const BG2 = cssVar("surface");
export const BG3 = cssVar("surface-2");
export const ACCENT = cssVar("blue");
export const ACCENT_SOFT = cssVar("accent-soft");
export const GREEN = cssVar("green");
export const RED = cssVar("red");
export const YELLOW = cssVar("amber");
export const ORANGE = cssVar("orange");
export const TEXT = cssVar("text");
export const SUBTEXT = cssVar("muted");
export const LINE = cssVar("line");
export const GRID = cssVar("grid");

/** config.CHART_COLORS — fixed series colours, theme-independent: each is
 *  >= 3:1 on both chart surfaces (tests/theme.test.ts). Must equal config.py. */
export const CHART_COLORS = [
  "#048BA6", "#E9403B", "#249240", "#9E7A04", "#B654D7",
  "#D55905", "#1A80E6", "#E33D82", "#578E19", "#109076",
  "#7276D6", "#A77448", "#D53AC8", "#81842C", "#688396",
] as const;

/** config.SEMI_COMPANIES / SEMI_ETFS and the two hard-coded sidebar groups. */
export const SEMI_COMPANIES = [
  "NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "ARM",
  "LRCX", "AMAT", "MRVL", "TSM", "TXN", "NXPI", "INTC",
] as const;
export const SEMI_ETFS = ["SOXL", "SOXS", "SMH", "SOXX"] as const;
export const MACRO_OTHER = ["TQQQ", "QQQ", "VIX", "USD", "10YTreasury", "Gold", "BTC", "ETH"] as const;
export const TECH_MIXED = ["MSFT", "GOOG", "META", "AAPL", "TSLA", "AMZN", "ORCL", "BRK.A"] as const;

export const TICKER_GROUPS = [
  { name: "Semi Companies", short: "Semi", members: SEMI_COMPANIES,
    defaults: ["NVDA", "AMD", "ASML", "AVGO", "QCOM", "MU", "TSM", "INTC"] },
  { name: "Semi ETFs", short: "ETF", members: SEMI_ETFS, defaults: ["SMH", "SOXX"] },
  { name: "Macro / Other", short: "Macro", members: MACRO_OTHER, defaults: ["VIX", "10YTreasury", "Gold"] },
  { name: "Tech / Mixed", short: "Tech", members: TECH_MIXED, defaults: [] },
] as const;

/**
 * What the Overview actually renders first. The `selected-tickers` Store is
 * initialised with 12 tickers, but sync_tickers (prevent_initial_call=False)
 * fires on load and replaces it with the union of the checklist defaults in
 * group order — 13 tickers, including Gold.
 */
export const INITIAL_SELECTED: readonly string[] = TICKER_GROUPS.flatMap((g) => [...g.defaults]);

/** `_cat_rank`: ticker → [category index, index within category]. */
export const CAT_RANK: ReadonlyMap<string, readonly [number, number]> = new Map(
  TICKER_GROUPS.flatMap((g, ci) => g.members.map((t, ti) => [t, [ci, ti] as const] as const)),
);

/** `_ticker_cat` */
export function tickerCat(t: string): string {
  for (const g of TICKER_GROUPS) if ((g.members as readonly string[]).includes(t)) return g.short;
  return "Other";
}

/** `_ticker_label` → "[Semi] NVDA" */
export function tickerLabel(t: string): string {
  const c = tickerCat(t);
  return c !== "Other" ? `[${c}] ${t}` : t;
}

export const PLOTLY_BASE = {
  paper_bgcolor: BG2,
  plot_bgcolor: BG2,
  font: { color: TEXT, family: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" },
  xaxis: { gridcolor: GRID, linecolor: LINE, zerolinecolor: LINE },
  yaxis: { gridcolor: GRID, linecolor: LINE, zerolinecolor: LINE },
  legend: { bgcolor: BG2, bordercolor: LINE },
  colorway: [...CHART_COLORS],
  margin: { l: 50, r: 20, t: 40, b: 40 },
} as const;
