/**
 * Financials tab — port of tab_financials() + _valuation_snapshot_panel().
 * Valuation figures come ONLY from ticker_valuation_history, stamped "Observed
 * On" (§9 F-02); pe_ratio / market_cap are never read from quarterly_financials.
 *
 * Kept for parity, logged as finding P-13: "Latest Quarter Summary" uses pandas
 * groupby().last(), which takes the last NON-NULL value per COLUMN — so a row can
 * mix quarters (e.g. a newer revenue with an older EPS) under one Period End.
 */
import { addDays, type Clock } from "../clock";
import { CHART_COLORS, SUBTEXT, YELLOW } from "../config";
import { placeholders, type Db } from "../db";
import { crawlTimestamp } from "../badges";
import { card, cols, ODD_ROW, responsiveGraph, sectionTitle, sourceFooter, TBL_CELL, TBL_HEADER } from "../dash/common";
import { DataTable, dbc, html, type DNode } from "../dash/tree";
import { emptyFigure, pyLayout, addSeries } from "../plotly/figure";
import { pyFixed, pyGrouped } from "../pynum";
import { QuarterlyFinancialsRow } from "../schemas";
import { valuationSnapshot } from "../valuation";
import { lastValid } from "../pd";
import type { z } from "zod";

type Fin = z.infer<typeof QuarterlyFinancialsRow>;
const nn = (v: number | null) => (v === null ? NaN : v);

function valuationPanel(db: Db, clock: Clock, tickers: readonly string[], stamp: string): DNode {
  const vdf = valuationSnapshot(db, tickers);
  if (vdf.length === 0) {
    return card([
      sectionTitle("Valuation Snapshot"),
      html.Div(
        "No valuation snapshot recorded yet. This series is observed, not historical — it starts on the first crawl after this panel " +
        "shipped and gains one row per ticker per crawl. It cannot be backfilled: the free feed exposes no historical trailing P/E " +
        "or market cap, and reconstructing one would restate today's multiple as the past (the defect this panel replaced).",
        { style: { color: SUBTEXT, fontSize: "13px", lineHeight: "1.6" } }),
      sourceFooter(stamp, "Yahoo Finance (yfinance .info snapshot)", "Observed values only — no point-in-time history available."),
    ]);
  }
  const asOf = [...new Set(vdf.map((r) => r.snapshot_date))].sort();
  const asOfLabel = asOf.length === 1 ? asOf[asOf.length - 1] : asOf.length ? `${asOf[0]} → ${asOf[asOf.length - 1]}` : "—";
  const fmtCap = (x: number | null) => (x === null ? "—" : `$${pyGrouped(x / 1e9, 1)}B`);
  const fmtNum = (x: number | null) => (x === null ? "—" : pyGrouped(x, 2));
  const data = vdf.map((r) => ({
    ticker: r.ticker, snapshot_date: r.snapshot_date, close_price: fmtNum(r.close_price), market_cap: fmtCap(r.market_cap),
    trailing_pe: fmtNum(r.trailing_pe), forward_pe: fmtNum(r.forward_pe), trailing_eps: fmtNum(r.trailing_eps),
    price_to_book: fmtNum(r.price_to_book),
  }));
  const labels: Record<string, string> = {
    ticker: "Ticker", snapshot_date: "Observed On", close_price: "Price", market_cap: "Market Cap",
    trailing_pe: "P/E (TTM)", forward_pe: "P/E (Fwd, est.)", trailing_eps: "EPS (TTM)", price_to_book: "P/B",
  };
  const newest = new Date(`${asOf[asOf.length - 1]}T00:00:00Z`);
  const ageDays = Math.floor((clock.hkt.getTime() - newest.getTime()) / 86400_000);
  const staleNote = ageDays > 4 ? html.Div(
    `⚠️  Newest snapshot is ${ageDays} days old. These are observed values from ${asOfLabel} — not current quotes. Do not read them as live pricing.`,
    { style: { color: YELLOW, fontSize: "12px", marginBottom: "8px", padding: "8px 10px", border: `1px solid ${YELLOW}`, borderRadius: "4px" } }) : null;

  return card([
    sectionTitle(`Valuation Snapshot  ·  Observed ${asOfLabel}`),
    staleNote ?? html.Div(),
    html.Div(
      "Point-in-time only. Each figure describes the date in the “Observed On” column, not any fiscal quarter above — trailing P/E, " +
      "market cap and TTM EPS have no historical series in this feed. Forward P/E is the vendor's consensus-derived estimate, not a " +
      "reported figure.", { style: { color: SUBTEXT, fontSize: "12px", marginBottom: "10px" } }),
    DataTable({ data, columns: cols(Object.keys(labels), (c) => labels[c]), style_table: { overflowX: "auto" },
      style_cell: TBL_CELL(), style_header: TBL_HEADER, style_data_conditional: [ODD_ROW], page_size: 20 }),
    sourceFooter(stamp, "Yahoo Finance (yfinance .info snapshot)", "Observed, not point-in-time history. Vendor-normalised; not primary filings."),
  ]);
}

const qlabel = (d: string) => `${d.slice(0, 4)}-Q${Math.floor((Number(d.slice(5, 7)) - 1) / 3) + 1}`;

export function buildFinancials(db: Db, clock: Clock, tickers: readonly string[]): DNode {
  const df: Fin[] = tickers.length ? db.all(
    `SELECT * FROM quarterly_financials WHERE ticker IN (${placeholders(tickers.length)}) ORDER BY ticker,period_end`,
    [...tickers], QuarterlyFinancialsRow, "financials_data") : [];
  if (df.length === 0) {
    return card(html.P("No quarterly financial data. Run crawler.py — financials are only available for listed companies.", { style: { color: SUBTEXT } }));
  }
  const stamp = crawlTimestamp(db);
  const cutoff = addDays(clock.hkt, -365 * 5).getTime();
  const view = [...df].sort((a, b) => (a.period_end < b.period_end ? -1 : a.period_end > b.period_end ? 1 : 0))
    .filter((r) => new Date(`${r.period_end.slice(0, 10)}T00:00:00Z`).getTime() >= cutoff);

  const metricChart = (col: keyof Fin, title: string) => {
    const fig = emptyFigure();
    tickers.forEach((t, i) => {
      const sub = view.filter((r) => r.ticker === t && r[col] !== null);
      if (!sub.length) return;
      addSeries(fig, { provenance: "published", trace: {
        type: "bar", x: sub.map((r) => qlabel(r.period_end)), y: sub.map((r) => (r[col] as number) / 1e9), name: t,
        marker: { color: CHART_COLORS[i % CHART_COLORS.length] },
        hovertemplate: `<b>${t}</b><br>%{x}<br>${title}: %{y:,.2f}B<extra></extra>` } });
    });
    pyLayout(fig, { title: `${title} (USD Billions)`, barmode: "group", height: 320, yaxis_title: title });
    return responsiveGraph(fig, { displayModeBar: false });
  };
  const trendChart = (col: keyof Fin, title: string, pct = false) => {
    const fig = emptyFigure();
    tickers.forEach((t, i) => {
      const sub = view.filter((r) => r.ticker === t && r[col] !== null);
      if (!sub.length) return;
      addSeries(fig, { provenance: "published", trace: {
        type: "scatter", x: sub.map((r) => qlabel(r.period_end)), y: sub.map((r) => r[col] as number), name: t, mode: "lines+markers",
        line: { width: 2, color: CHART_COLORS[i % CHART_COLORS.length] },
        hovertemplate: `<b>${t}</b><br>%{x}<br>${title}: %{y:.2f}${pct ? "%" : ""}<extra></extra>` } });
    });
    pyLayout(fig, { title: title + (pct ? " (%)" : ""), height: 280 });
    return responsiveGraph(fig, { displayModeBar: false });
  };

  // groupby("ticker").last() — sorted tickers, last NON-NULL per column (P-13)
  const byT = new Map<string, Fin[]>();
  for (const r of view) { if (!byT.has(r.ticker)) byT.set(r.ticker, []); byT.get(r.ticker)!.push(r); }
  const pick = (rows: Fin[], c: keyof Fin) => lastValid(rows.map((r) => r[c]), (v) => v === null) ?? null;
  const pct = (x: unknown) => (x === null ? "—" : `${pyFixed(x as number, 1)}%`);
  const data = [...byT.keys()].sort().map((t) => {
    const rows = byT.get(t)!;
    const rev = pick(rows, "revenue") as number | null, eps = pick(rows, "eps") as number | null;
    return { ticker: t, period_end: (pick(rows, "period_end") as string).slice(0, 10),
      revenue: rev === null ? "—" : `$${pyGrouped(rev / 1e9, 1)}B`,
      gross_margin: pct(pick(rows, "gross_margin")), op_margin: pct(pick(rows, "op_margin")), net_margin: pct(pick(rows, "net_margin")),
      eps: eps === null ? "—" : pyFixed(eps, 2) };
  });
  const L: Record<string, string> = { ticker: "Ticker", period_end: "Period End", revenue: "Revenue", gross_margin: "Gross Margin",
    op_margin: "Operating Margin", net_margin: "Net Margin", eps: "EPS (Diluted, Quarter)" };
  const tbl = DataTable({ data, columns: cols(Object.keys(L), (c) => L[c]), style_table: { overflowX: "auto" },
    style_cell: TBL_CELL(), style_header: TBL_HEADER, style_data_conditional: [ODD_ROW], page_size: 20 });

  const C = (child: DNode, width: number) => dbc.Col(card(child), { width });
  return html.Div([
    card([sectionTitle("Latest Quarter Summary"), tbl]),
    valuationPanel(db, clock, tickers, stamp),
    dbc.Row([C(metricChart("revenue", "Revenue"), 6), C(metricChart("gross_profit", "Gross Profit"), 6)]),
    dbc.Row([C(metricChart("operating_profit", "Operating Profit"), 6), C(metricChart("rd_expense", "R&D Expense"), 6)]),
    dbc.Row([C(metricChart("net_profit", "Net Profit"), 6), C(trendChart("gross_margin", "Gross Margin", true), 6)]),
    dbc.Row([C(trendChart("op_margin", "Operating Margin", true), 4), C(trendChart("net_margin", "Net Margin", true), 4),
      C(trendChart("rd_to_revenue", "R&D / Revenue", true), 4)]),
    dbc.Row([C(trendChart("ar_turnover", "Accounts Receivable Turnover"), 6), C(trendChart("inventory_turnover", "Inventory Turnover"), 6)]),
    card(sourceFooter(stamp, "Yahoo Finance / yfinance",
      "Quarterly financials sourced from SEC EDGAR filings via yfinance. Showing up to 5 years of quarterly data. " +
      "Revenue, profit, margins, R&D, AR and inventory turnover ratios.")),
  ]);
}
