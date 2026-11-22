/**
 * Overview tab — port of dashboard.py `tab_overview(tickers, start, end)`.
 * Pure data → figure JSON; the React layer only renders what this returns.
 *
 * Kept for parity, reported as findings (not "fixed" — no redesign in WEB-01):
 *  P-04  the price subplot is titled "Base=100 at range start" but is indexed to
 *        the first close of the 5-YEAR fetch, not the start of the visible range;
 *  P-06  FIXED in dashboard.py and here (2026-11-09 QA): a NULL perf value used
 *        to crash the whole Overview under pandas 3 (heatmap text) and print
 *        "nan%" (KPI). Now: no KPI delta, "—" heatmap cell.
 */
import { addDays, ymd, type Clock } from "./clock";
import { crawlTimestamp } from "./badges";
import { BG3, CAT_RANK, CHART_COLORS, GREEN, RED, SUBTEXT, TEXT, tickerLabel } from "./config";
import { placeholders, type Db } from "./db";
import { addSeries, baseLayout, emptyFigure, updateAxis, updateLayout, withRangeSelector, type Figure, type Json } from "./plotly/figure";
import { makeSubplotsColumn, subplotRef } from "./plotly/subplots";
import { npRound, pyFixed, pyFloatStr, pyGrouped } from "./pynum";
import { DailyPriceRow, MarketSentimentRow, type MarketSentimentRow as Sent } from "./schemas";

export type Kpi = { label: string; value: string; value_colour: string; delta: string; delta_colour: string };
export type Footer = { source: string; stamp: string; notes: string };
export type OverviewResult =
  | { kind: "empty"; message: string }
  | { kind: "ok"; kpis: Kpi[]; priceFig: Figure; heatmap: Figure | null; heatmapMessage: string | null; footer: Footer };

export function priceData(db: Db, tickers: readonly string[], start: string, end: string) {
  if (tickers.length === 0) return [];
  return db.all(
    `SELECT ticker,date,open,high,low,close,volume FROM daily_prices WHERE ticker IN (${placeholders(tickers.length)}) ` +
    "AND date BETWEEN ? AND ? ORDER BY ticker,date", [...tickers, start, end], DailyPriceRow, "price_data");
}

export function sentimentData(db: Db, tickers: readonly string[]): Sent[] {
  if (tickers.length === 0) return [];
  return db.all(
    `SELECT s.* FROM market_sentiment s INNER JOIN (SELECT ticker, MAX(snapshot_date) AS md FROM market_sentiment
      WHERE ticker IN (${placeholders(tickers.length)}) GROUP BY ticker) latest
      ON s.ticker=latest.ticker AND s.snapshot_date=latest.md ORDER BY s.ticker`,
    [...tickers], MarketSentimentRow, "sentiment_data");
}

const byTicker = <T extends { ticker: string; date: string }>(rows: readonly T[], t: string) =>
  rows.filter((r) => r.ticker === t).sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
const nn = (x: number | null) => (x === null ? NaN : x);

/** perf_1m for one ticker; NULL (pandas NaN) is MISSING → null → no delta. */
function perf1m(sent: Sent[], t: string): number | null {
  return sent.find((r) => r.ticker === t)?.perf_1m ?? null;
}

export function buildOverview(db: Db, clock: Clock, tickers: readonly string[], start: string, end: string): OverviewResult {
  const prices = priceData(db, tickers, start, end);
  const sent = sentimentData(db, tickers);
  if (prices.length === 0) return { kind: "empty", message: "No price data found. Run crawler.py first." };

  // ── KPI cards ────────────────────────────────────────────────────────────
  const kpis: Kpi[] = [];
  for (const t of tickers) {
    const df = byTicker(prices, t);
    if (df.length === 0) continue;
    const latest = nn(df[df.length - 1].close);
    const p1m = perf1m(sent, t);
    const truthy = p1m !== null && p1m !== 0; // NaN is truthy in Python
    const delta = p1m === null ? "" : truthy && p1m >= 0 ? `+${pyFixed(p1m, 1)}%` : `${pyFixed(p1m, 1)}%`;
    const col = truthy && p1m! >= 0 ? GREEN : truthy && p1m! < 0 ? RED : TEXT;
    kpis.push({ label: t, value: `$${pyGrouped(latest, 2)}`, value_colour: col, delta,
                delta_colour: delta.startsWith("+") ? GREEN : delta.startsWith("-") ? RED : SUBTEXT });
  }

  // ── price + volume subplot over 5Y so the 1Y/3Y/5Y buttons have data ────
  const start5y = ymd(addDays(clock.hkt, -365 * 5));
  const p5 = priceData(db, tickers, start5y, end);
  const fig = makeSubplotsColumn({ rowHeights: [0.68, 0.32], verticalSpacing: 0.04,
    titles: ["Price Performance (Base=100 at range start)", "Trading Volume"] });

  tickers.forEach((t, i) => {
    const df = byTicker(p5, t);
    if (df.length < 2) return;
    const base = nn(df[0].close);
    if (base === 0) return;
    addSeries(fig, { provenance: "published", trace: {
      type: "scatter", ...subplotRef(1), x: df.map((r) => r.date), y: df.map((r) => (nn(r.close) / base) * 100),
      name: t, mode: "lines", line: { width: 2, color: CHART_COLORS[i % CHART_COLORS.length] },
      hovertemplate: `<b>${t}</b><br>Date: %{x}<br>Indexed: %{y:.1f}<extra></extra>`,
    } });
  });
  tickers.slice(0, 8).forEach((t, i) => {
    const df = byTicker(p5, t);
    if (df.length === 0) return;
    addSeries(fig, { provenance: "published", trace: {
      type: "bar", ...subplotRef(2), x: df.map((r) => r.date), y: df.map((r) => nn(r.volume)), name: t,
      marker: { color: CHART_COLORS[i % CHART_COLORS.length] }, showlegend: false,
      hovertemplate: `<b>${t}</b><br>%{x}<br>Vol: %{y:,.0f}<extra></extra>`,
    } });
  });

  const oneYAgo = ymd(addDays(clock.hkt, -365));
  baseLayout(fig, { height: 620, hovermode: "x unified", barmode: "overlay", bargap: 0.1 });
  withRangeSelector(fig, { axis: "xaxis", range: [oneYAgo, end], legendBottom: false, extraHeight: 40 });
  updateAxis(fig, "yaxis", { title: { text: "Index (Base=100)" }, gridcolor: "var(--grid)", color: TEXT });
  updateAxis(fig, "yaxis2", { title: { text: "Volume" }, gridcolor: "var(--grid)", color: TEXT });
  for (const a of fig.layout.annotations as Record<string, Json>[]) a.font = { color: TEXT, size: 13 };

  // ── return heatmap ──────────────────────────────────────────────────────
  let heatmap: Figure | null = null;
  let heatmapMessage: string | null = null;
  if (sent.length > 0) {
    const cols = ["perf_5d", "perf_10d", "perf_1m"] as const;
    const rows = [...sent].sort((a, b) => {
      const ra = CAT_RANK.get(a.ticker) ?? [99, 99], rb = CAT_RANK.get(b.ticker) ?? [99, 99];
      return ra[0] - rb[0] || ra[1] - rb[1];
    });
    const z = rows.map((r) => cols.map((c) => nn(r[c])));
    heatmap = emptyFigure();
    addSeries(heatmap, { provenance: "derived", trace: {
      type: "heatmap", z, x: ["5-Day %", "10-Day %", "1-Month %"], y: rows.map((r) => tickerLabel(r.ticker)),
      colorscale: [[0, RED], [0.5, BG3], [1, GREEN]], zmid: 0,
      text: z.map((row) => row.map((v) => (Number.isNaN(v) ? "—" : `${pyFloatStr(npRound(v, 1))}%`))),
      texttemplate: "%{text}", hovertemplate: "<b>%{y}</b><br>%{x}: %{z:.2f}%<extra></extra>",
    } });
    baseLayout(heatmap, {});
    updateLayout(heatmap, { title: { text: "Return Heatmap" }, height: Math.max(280, tickers.length * 30) });
  } else {
    heatmapMessage = "Sentiment data not yet available.";
  }

  return { kind: "ok", kpis, priceFig: fig, heatmap, heatmapMessage, footer: {
    source: "Yahoo Finance / yfinance", stamp: crawlTimestamp(db),
    notes: "OHLCV daily price data and 1-month performance. Prices are as-of market close.",
  } };
}
