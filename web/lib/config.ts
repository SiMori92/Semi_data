/**
 * Constants mirrored from config.py and the top of dashboard.py. These are
 * presentation constants, not business data — but they are still mirrored, so
 * tests/parity.config.test.ts checks them against the golden dump where the dump
 * carries them (ticker list, colours used in figures, job labels).
 */
export const BG = "#0d1117";
export const BG2 = "#161b22";
export const BG3 = "#21262d";
export const ACCENT = "#58a6ff";
export const GREEN = "#3fb950";
export const RED = "#f85149";
export const YELLOW = "#d29922";
export const TEXT = "#e6edf3";
export const SUBTEXT = "#8b949e";

/** config.CHART_COLORS */
export const CHART_COLORS = [
  "#00D4FF", "#FF6B6B", "#51CF66", "#FFD43B", "#CC5DE8",
  "#FF922B", "#74C0FC", "#F06595", "#A9E34B", "#63E6BE",
  "#4DABF7", "#FFA94D", "#DA77F2", "#E599F7", "#96F2D7",
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
  plot_bgcolor: BG3,
  font: { color: TEXT, family: "Inter, Segoe UI, sans-serif" },
  xaxis: { gridcolor: "#30363d", linecolor: "#30363d", zerolinecolor: "#30363d" },
  yaxis: { gridcolor: "#30363d", linecolor: "#30363d", zerolinecolor: "#30363d" },
  legend: { bgcolor: BG2, bordercolor: "#30363d" },
  colorway: [...CHART_COLORS],
  margin: { l: 50, r: 20, t: 40, b: 40 },
} as const;
