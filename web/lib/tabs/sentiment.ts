/**
 * Sentiment tab — port of tab_sentiment(), _ibkr_iv_data(), _ibkr_iv_history().
 * IV labels derive from each row's own `source` (§9 IV-01) — EXCEPT the footer,
 * which dashboard.py still hardcodes as "Interactive Brokers TWS …" whenever any
 * options_iv row exists, even though the fixture's IV is derived from Yahoo.
 * Kept for parity; logged as finding P-14 (an IV-01 regression live in prod).
 */
import type { Clock } from "../clock";
import { addDays, ymd } from "../clock";
import { ACCENT, CAT_RANK, CHART_COLORS, GREEN, RED, SUBTEXT, YELLOW, tickerCat } from "../config";
import { placeholders, type Db } from "../db";
import { crawlTimestamp } from "../badges";
import { card, cols, ODD_ROW, responsiveGraph, sectionTitle, sourceFooter, TBL_CELL, TBL_HEADER } from "../dash/common";
import { DataTable, dbc, html, type DNode } from "../dash/tree";
import { computeHv30 } from "../hv30";
import { ivSourceMeta, ivProvenance, ivSourceSummary } from "../iv-source";
import { sentimentData } from "../overview";
import { addHline, addVline, addSeries, emptyFigure, pyLayout, updateAxis, withRangeSelector } from "../plotly/figure";
import { npRound, pyFixed, pyGrouped, pySignedFixed } from "../pynum";
import { OptionsIvHistoryRow, OptionsIvRow } from "../schemas";
import { stableSort } from "../pd";

const r1 = (v: number) => npRound(v, 1);
const rank = (t: string) => CAT_RANK.get(t) ?? ([99, 99] as const);
const byRank = (a: string, b: string) => { const x = rank(a), y = rank(b); return x[0] - y[0] || x[1] - y[1]; };

export function buildSentiment(db: Db, clock: Clock, tickers: readonly string[]): DNode {
  const sent = sentimentData(db, tickers);
  const iv = tickers.length ? db.all(
    `SELECT i.* FROM options_iv i INNER JOIN (SELECT ticker, MAX(snapshot_date) AS md FROM options_iv WHERE ticker IN (${placeholders(tickers.length)}) GROUP BY ticker) latest ON i.ticker=latest.ticker AND i.snapshot_date=latest.md ORDER BY i.ticker`,
    [...tickers], OptionsIvRow, "options_iv latest") : [];
  const hasIv = iv.length > 0;
  if (sent.length === 0 && !hasIv) return card(html.P("No sentiment data found. Run crawler.py first.", { style: { color: SUBTEXT } }));
  const stamp = crawlTimestamp(db);

  const [ivDesc, ivAllPub] = ivSourceSummary(hasIv ? iv.map((r) => r.source) : null);
  const sourceNote = html.Div([
    html.Span("📡 Options IV source: ", { style: { color: SUBTEXT, fontSize: "12px" } }),
    html.Span(hasIv ? ivDesc : "Yahoo Finance snapshot IV (crawler.py) / HV30 fallback",
      { style: { color: ivAllPub ? ACCENT : YELLOW, fontSize: "12px", fontWeight: "600" } }),
    html.Span(hasIv && !ivAllPub ? "  ✳ derived metric — our own constant-maturity construction, not a published index"
      : hasIv ? "" : " — run python3 iv_crawler.py to populate a 30d ATM IV series",
      { style: { color: SUBTEXT, fontSize: "11px" } }),
  ], { style: { marginBottom: "12px" } });

  let ivSection: DNode;
  if (hasIv) {
    // A1 term structure
    const term = emptyFigure();
    const ivCols = ["iv_current", "iv_1m_avg", "iv_1q_avg", "iv_6m_avg", "iv_1y_avg"] as const;
    const ivLabels = ["Current", "1-Month Avg", "1-Quarter Avg", "6-Month Avg", "1-Year Avg"];
    const ivColors = [ACCENT, "#74C0FC", "#51CF66", YELLOW, "#CC5DE8"];
    ivCols.forEach((c, k) => {
      const sub = iv.filter((r) => r[c] !== null);
      if (!sub.length) return;
      const prov = sub.every((r) => ivProvenance(r.source) === "published") ? "published" : "derived";
      addSeries(term, { provenance: prov, trace: { type: "bar", name: ivLabels[k], x: sub.map((r) => r.ticker),
        y: sub.map((r) => r1(r[c] as number)), marker: { color: ivColors[k] },
        hovertemplate: `<b>%{x}</b><br>${ivLabels[k]}: %{y:.1f}%<extra></extra>` } });
    });
    pyLayout(term, { title: "Options IV — Term Structure per Ticker", barmode: "group", height: 380,
      xaxis_title: "Ticker", yaxis_title: "Implied Volatility (%)" });

    // A2 percentile vs 1Y
    const pctRows = iv.filter((r) => r.iv_pct_vs_1y !== null && r.iv_current !== null && r.iv_52w_low !== null && r.iv_52w_high !== null);
    const pct = emptyFigure();
    if (pctRows.length) {
      addSeries(pct, { provenance: "derived", trace: { type: "bar", x: pctRows.map((r) => r.ticker), y: pctRows.map((r) => r.iv_pct_vs_1y!),
        marker: { color: pctRows.map((r) => (r.iv_pct_vs_1y! > 80 ? RED : r.iv_pct_vs_1y! > 50 ? YELLOW : GREEN)) },
        customdata: pctRows.map((r) => [r.iv_current!, r.iv_52w_low!, r.iv_52w_high!]),
        hovertemplate: "<b>%{x}</b><br>IV Percentile (1Y): %{y:.0f}%<br>Current IV: %{customdata[0]:.1f}%<br>52W Low: %{customdata[1]:.1f}%  |  52W High: %{customdata[2]:.1f}%<extra></extra>" } });
    }
    addHline(pct, 80, { dash: "dot", color: RED, width: 1 }, { text: "High fear zone (>80th pct)", font: { color: RED } });
    addHline(pct, 20, { dash: "dot", color: GREEN, width: 1 }, { text: "Low vol zone (<20th pct)", font: { color: GREEN } });
    pyLayout(pct, { title: "IV Percentile vs 1-Year Range — Where is IV sitting today?", height: 300, showlegend: false,
      xaxis_title: "Ticker", yaxis_title: "IV Percentile (%)" });

    // A3 history
    const hist = db.all(`SELECT * FROM options_iv_history WHERE ticker IN (${placeholders(tickers.length)}) ORDER BY ticker, date`,
      [...tickers], OptionsIvHistoryRow, "options_iv_history");
    const ivh = emptyFigure();
    const groups = new Map<string, typeof hist>();
    for (const r of hist) { if (!groups.has(r.ticker)) groups.set(r.ticker, []); groups.get(r.ticker)!.push(r); }
    [...groups.keys()].sort().forEach((t, i) => {
      const g = [...groups.get(t)!].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
      addSeries(ivh, { provenance: g.every((r) => ivProvenance(r.source) === "published") ? "published" : "derived", trace: {
        type: "scatter", x: g.map((r) => r.date), y: g.map((r) => (r.iv_pct === null ? NaN : r.iv_pct)), name: t, mode: "lines",
        line: { width: 2, color: CHART_COLORS[i % CHART_COLORS.length] },
        hovertemplate: `<b>${t}</b><br>Date: %{x}<br>IV: %{y:.1f}%<extra></extra>` } });
    });
    pyLayout(ivh, { title: "Daily Implied Volatility History", height: 340, xaxis_title: "Date", yaxis_title: "IV (%)", hovermode: "x unified" });
    withRangeSelector(ivh, { range: [ymd(addDays(clock.hkt, -365)), ymd(clock.hkt)] });

    // A4 table
    const f1 = (x: number | null) => (x === null ? "—" : `${pyFixed(x, 1)}%`);
    const data = iv.map((r) => ({ "Ticker": r.ticker, "Date": r.snapshot_date, "IV Current": f1(r.iv_current), "1M Avg": f1(r.iv_1m_avg),
      "1Q Avg": f1(r.iv_1q_avg), "6M Avg": f1(r.iv_6m_avg), "1Y Avg": f1(r.iv_1y_avg),
      "1Y Pct": r.iv_pct_vs_1y === null ? "—" : `${pyFixed(r.iv_pct_vs_1y, 0)}th`, "52W Low": f1(r.iv_52w_low), "52W High": f1(r.iv_52w_high) }));
    const ivTable = DataTable({ data, columns: cols(Object.keys(data[0])), sort_action: "native", style_table: { overflowX: "auto" },
      style_cell: TBL_CELL("12px", "5px 10px"), style_header: TBL_HEADER, style_data_conditional: [ODD_ROW] });

    ivSection = html.Div([
      card([sectionTitle("Options IV — Snapshot Table"), ivTable,
        html.Div("Source: " + ivDesc, { style: { color: SUBTEXT, fontSize: "11px", marginTop: "6px" } }),
        html.Div("Blank averages/percentiles accumulate daily — option chains cannot be backfilled.",
          { style: { color: SUBTEXT, fontSize: "11px", fontStyle: "italic" } })]),
      card(responsiveGraph(term, { displayModeBar: true })),
      dbc.Row([dbc.Col(card(responsiveGraph(pct, { displayModeBar: false })), { width: 6 }),
        dbc.Col(card(responsiveGraph(ivh, { displayModeBar: true })), { width: 6 })]),
    ]);
  } else {
    const withIv = sent.filter((r) => r.implied_volatility !== null);
    if (withIv.length) {
      // sort_values(ascending=False) — pandas quicksort; ties keep a stable order here
      const ivDf = stableSort(withIv, (a, b) => b.implied_volatility! - a.implied_volatility!);
      const fig = emptyFigure();
      addSeries(fig, { provenance: "derived", trace: { type: "bar", x: ivDf.map((r) => r.ticker), y: ivDf.map((r) => r1(r.implied_volatility!)),
        marker: { color: ivDf.map((r) => (r.implied_volatility! > 60 ? RED : r.implied_volatility! > 30 ? YELLOW : GREEN)) },
        text: ivDf.map((r) => `${pyFixed(r.implied_volatility!, 1)}%`), textposition: "outside",
        hovertemplate: "<b>%{x}</b><br>IV (ATM): %{y:.1f}%<extra></extra>" } });
      pyLayout(fig, { title: `Implied Volatility — ATM Estimate via yfinance (${ivDf.length} of ${sent.length} tickers have IV data)`,
        height: 320, showlegend: false, xaxis_title: "Ticker", yaxis_title: "Implied Volatility (%)" });
      updateAxis(fig, "yaxis", { rangemode: "tozero" });
      const missing = sent.filter((r) => r.implied_volatility === null).map((r) => r.ticker);
      const missingNote = missing.length ? `IV not available for: ${missing.slice(0, 12).join(", ")}` + (missing.length > 12 ? " …" : "") : "";
      ivSection = card([
        responsiveGraph(fig, { displayModeBar: false }),
        html.Div([
          html.Span("⚠️ Source: yfinance ATM snapshot (annualised) — no historical period averages.  ", { style: { color: YELLOW, fontSize: "12px" } }),
          html.Span("Connect Interactive Brokers for full IV term structure.", { style: { color: SUBTEXT, fontSize: "12px" } }),
        ], { style: { marginTop: "8px" } }),
        missingNote ? html.P(missingNote, { style: { color: SUBTEXT, fontSize: "11px", marginTop: "4px" } }) : html.Span(),
      ]);
    } else {
      ivSection = card([
        sectionTitle("Implied Volatility — ATM Estimate"),
        html.Div([
          html.P("IV data is not yet in the database.", { style: { color: YELLOW, fontWeight: "600", fontSize: "13px", margin: "0 0 6px 0" } }),
          html.P("The crawler now fetches IV automatically on every crawl (including --quick mode). Trigger a fresh crawl with the ⚡ Run Crawl " +
            "button in the navbar and then reload — IV data will appear for US-listed stocks (ETFs, bonds, and crypto may still show N/A).",
            { style: { color: SUBTEXT, fontSize: "12px", margin: "0" } }),
        ], { style: { padding: "20px", textAlign: "center" } }),
      ]);
    }
  }

  if (sent.length === 0) return html.Div([sourceNote, ivSection]);

  // Section B
  const dropDf = stableSort(sent.filter((r) => r.days_since_large_drop !== null), (a, b) => a.days_since_large_drop! - b.days_since_large_drop!);
  const drop = emptyFigure();
  addSeries(drop, { provenance: "derived", trace: { type: "bar", x: dropDf.map((r) => r.ticker), y: dropDf.map((r) => r.days_since_large_drop!),
    marker: { color: dropDf.map((r) => (r.days_since_large_drop! > 90 ? GREEN : r.days_since_large_drop! > 30 ? YELLOW : RED)) },
    hovertemplate: "<b>%{x}</b><br>Days since ≥5% drop: %{y}<extra></extra>" } });
  pyLayout(drop, { title: "Days Since Last Large Single-Day Drop (≥5%)", height: 280, showlegend: false });

  const perf = sent.filter((r) => r.perf_5d !== null && r.perf_1m !== null);
  const scatter = emptyFigure();
  if (perf.length) {
    addSeries(scatter, { provenance: "derived", trace: { type: "scatter", x: perf.map((r) => r.perf_5d!), y: perf.map((r) => r.perf_1m!),
      mode: "markers+text", text: perf.map((r) => r.ticker), textposition: "top center",
      marker: { size: 14, color: perf.map((r) => (r.perf_1m! > 0 ? GREEN : RED)), line: { width: 1, color: "#30363d" } },
      hovertemplate: "<b>%{text}</b><br>5-Day: %{x:.1f}%<br>1-Month: %{y:.1f}%<extra></extra>" } });
    addHline(scatter, 0, { dash: "dash", color: SUBTEXT, width: 1 });
    addVline(scatter, 0, { dash: "dash", color: SUBTEXT, width: 1 });
  }
  pyLayout(scatter, { title: "5-Day vs 1-Month Return (%)", height: 360, xaxis_title: "5-Day Return (%)", yaxis_title: "1-Month Return (%)" });

  // Summary table — category order, IV from options_iv (preferred) or snapshot IV → HV30
  type Row = { ticker: string; close_price: number | null; perf_5d: number | null; perf_10d: number | null; perf_1m: number | null; days: number | null; iv: number | null; src: string };
  let rows: Row[] = stableSort(sent.map((r) => ({ ticker: r.ticker, close_price: r.close_price, perf_5d: r.perf_5d, perf_10d: r.perf_10d,
    perf_1m: r.perf_1m, days: r.days_since_large_drop, iv: null as number | null, src: "N/A" })), (a, b) => byRank(a.ticker, b.ticker));
  if (hasIv) {
    const ivBy = new Map(iv.map((r) => [r.ticker, r]));
    rows = rows.map((r) => { const v = ivBy.get(r.ticker); const val = v?.iv_current ?? null;
      return { ...r, iv: val, src: val !== null ? ivSourceMeta(v!.source)[0] : "N/A" }; });
  } else {
    const snap = new Map(sent.map((r) => [r.ticker, r.implied_volatility]));
    const hv = new Map(computeHv30(db, clock, rows.map((r) => r.ticker)).map((h) => [h.ticker, h.hv30]));
    rows = rows.map((r) => { const s = snap.get(r.ticker) ?? null; if (s !== null) return { ...r, iv: s, src: "IV" };
      const h = hv.get(r.ticker) ?? null; return h !== null ? { ...r, iv: h, src: "HV30" } : { ...r, iv: null, src: "N/A" }; });
  }
  const sp = (x: number | null) => (x === null ? "—" : `${pySignedFixed(x, 1)}%`);
  const data = rows.map((r) => ({ "Ticker": r.ticker, "Category": tickerCat(r.ticker),
    "Close Price": r.close_price === null ? "—" : `$${pyGrouped(r.close_price, 2)}`,
    "Perf 5D": sp(r.perf_5d), "Perf 10D": sp(r.perf_10d), "Perf 1M": sp(r.perf_1m),
    "Days Since Drop": r.days === null ? "—" : String(Math.trunc(r.days)),
    "Vol %": r.iv === null ? "—" : `${pyFixed(r.iv, 1)}%`, "Vol Source": r.src }));
  const cond: unknown[] = [ODD_ROW];
  for (const c of ["Perf 5D", "Perf 10D", "Perf 1M"]) {
    cond.push({ if: { filter_query: `{${c}} contains "+"`, column_id: c }, color: GREEN, fontWeight: "600" },
      { if: { filter_query: `{${c}} contains "-"`, column_id: c }, color: RED, fontWeight: "600" });
  }
  cond.push(
    { if: { filter_query: '{Vol Source} = "IBKR"', column_id: "Vol Source" }, color: GREEN, fontWeight: "600" },
    { if: { filter_query: '{Vol Source} = "DVOL"', column_id: "Vol Source" }, color: GREEN, fontWeight: "600" },
    { if: { filter_query: '{Vol Source} = "IV30*"', column_id: "Vol Source" }, color: ACCENT, fontWeight: "600" },
    { if: { filter_query: '{Vol Source} = "IV"', column_id: "Vol Source" }, color: ACCENT, fontWeight: "600" },
    { if: { filter_query: '{Vol Source} = "HV30"', column_id: "Vol Source" }, color: YELLOW, fontWeight: "600" },
    { if: { filter_query: '{Vol Source} = "N/A"', column_id: "Vol Source" }, color: SUBTEXT });
  const tbl = DataTable({ data, columns: cols(["Ticker", "Category", "Close Price", "Perf 5D", "Perf 10D", "Perf 1M", "Days Since Drop", "Vol %", "Vol Source"]),
    sort_action: "native", style_table: { overflowX: "auto" }, style_cell: TBL_CELL(), style_header: TBL_HEADER, style_data_conditional: cond });

  const ivSource = hasIv ? "Interactive Brokers TWS — real-time options IV term structure"  // P-14: hardcoded producer (parity)
    : "Yahoo Finance / yfinance — delayed ATM IV estimate (no period averages)";
  return html.Div([
    sourceNote,
    card([sectionTitle("Sentiment Snapshot"), tbl]),
    ivSection,
    dbc.Row([dbc.Col(card(responsiveGraph(drop, { displayModeBar: false })), { width: 6 }),
      dbc.Col(card(responsiveGraph(scatter, { displayModeBar: true })), { width: 6 })]),
    card(sourceFooter(stamp, ivSource, "Performance metrics (5d/10d/1m) from Yahoo Finance / yfinance.")),
  ]);
}
