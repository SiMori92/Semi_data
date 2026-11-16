/** Cycles tab — port of _build_cycle_chart(), tab_cycles(), update_cycle_price_chart(). */
import { addDays, ymd, type Clock } from "../clock";
import { ACCENT, BG3, CAT_RANK, GREEN, RED, SUBTEXT, TEXT, tickerCat } from "../config";
import { placeholders, type Db } from "../db";
import { crawlTimestamp } from "../badges";
import { argrelextrema, CYCLE_WINDOW, greaterEqual, lessEqual } from "../cycles";
import { card, cols, ODD_ROW, responsiveGraph, sectionTitle, sourceFooter, TBL_CELL, TBL_HEADER } from "../dash/common";
import { DataTable, dbc, dcc, html, type DNode } from "../dash/tree";
import { addAnnotation, addHline, addSeries, addVrect, emptyFigure, pyLayout, withRangeSelector, type Figure } from "../plotly/figure";
import { pyFixed, pySignedFixed } from "../pynum";
import { CycleAnalysisRow, DateCloseRow } from "../schemas";
import { stableSort } from "../pd";

/** `_build_cycle_chart(ticker)` — 5 years of closes, peaks/troughs via
 *  argrelextrema(order=15), green/red shaded segments. "" → empty figure (as the callback). */
export function buildCycleChart(db: Db, clock: Clock, ticker: string): Figure {
  if (!ticker) return emptyFigure();
  const cutoff = ymd(addDays(clock.hkt, -365 * 5));
  const rows = db.all("SELECT date, close FROM daily_prices WHERE ticker=? AND date>=? ORDER BY date", [ticker, cutoff], DateCloseRow, "cycle chart");
  const fig = emptyFigure();
  pyLayout(fig, { title: `${ticker} — Cycle Detection  (window = ${CYCLE_WINDOW} trading days)`, height: 400,
    xaxis_title: "Date", yaxis_title: "Price (USD)", hovermode: "x unified" });
  if (rows.length === 0 || rows.length < CYCLE_WINDOW * 3) {
    addAnnotation(fig, { text: "Not enough price history for cycle detection (need ≥ 2 years).", xref: "paper", yref: "paper",
      x: 0.5, y: 0.5, showarrow: false, font: { color: SUBTEXT, size: 13 } });
    return fig;
  }
  const closes = rows.map((r) => (r.close === null ? NaN : r.close));
  const dates = rows.map((r) => r.date.slice(0, 10));
  const peaks = argrelextrema(closes, greaterEqual, CYCLE_WINDOW);
  const troughs = argrelextrema(closes, lessEqual, CYCLE_WINDOW);
  const events = stableSort([...peaks.map((i) => [i, "peak"] as const), ...troughs.map((i) => [i, "trough"] as const)], (a, b) => a[0] - b[0]);
  for (let k = 0; k < events.length - 1; k++) {
    const [i0, t0] = events[k], [i1, t1] = events[k + 1];
    const pct = (closes[i1] / closes[i0] - 1) * 100;
    let color = SUBTEXT, label = "";
    if (t0 === "trough" && t1 === "peak") { color = GREEN; label = `+${pyFixed(pct, 0)}%`; }
    else if (t0 === "peak" && t1 === "trough") { color = RED; label = `${pyFixed(pct, 0)}%`; }
    addVrect(fig, dates[i0], dates[i1], { fillcolor: color, opacity: 0.1, lineWidth: 0 },
      { text: label, font: { color, size: 9 } });
  }
  addSeries(fig, { provenance: "published", trace: { type: "scatter", x: dates, y: closes, name: ticker,
    line: { color: ACCENT, width: 2 }, hovertemplate: "<b>%{x}</b>  $%{y:,.2f}<extra></extra>" } });
  if (peaks.length) addSeries(fig, { provenance: "derived", trace: { type: "scatter", x: peaks.map((i) => dates[i]), y: peaks.map((i) => closes[i]),
    mode: "markers", name: "Peak", marker: { symbol: "triangle-up", color: GREEN, size: 10, line: { width: 1, color: BG3 } },
    hovertemplate: "<b>Peak</b>  $%{y:,.2f}<extra></extra>" } });
  if (troughs.length) addSeries(fig, { provenance: "derived", trace: { type: "scatter", x: troughs.map((i) => dates[i]), y: troughs.map((i) => closes[i]),
    mode: "markers", name: "Trough", marker: { symbol: "triangle-down", color: RED, size: 10, line: { width: 1, color: BG3 } },
    hovertemplate: "<b>Trough</b>  $%{y:,.2f}<extra></extra>" } });
  withRangeSelector(fig, { range: [ymd(addDays(clock.hkt, -365 * 2)), ymd(clock.hkt)] });
  return fig;
}

const rank = (t: string) => CAT_RANK.get(t) ?? ([99, 99] as const);

/** `tab_cycles(tickers)`; `selected` mirrors the dropdown value after a change (callback). */
export function buildCycles(db: Db, clock: Clock, tickers: readonly string[], selected?: string): DNode {
  let cyc = tickers.length ? db.all(
    `SELECT c.* FROM cycle_analysis c INNER JOIN (SELECT ticker, MAX(snapshot_date) AS md FROM cycle_analysis WHERE ticker IN (${placeholders(tickers.length)}) GROUP BY ticker) latest ON c.ticker=latest.ticker AND c.snapshot_date=latest.md ORDER BY c.ticker`,
    [...tickers], CycleAnalysisRow, "cycle_data") : [];
  if (cyc.length === 0) return card(html.P("No cycle data found. Run crawler.py with ≥2 years of price history.", { style: { color: SUBTEXT } }));
  const stamp = crawlTimestamp(db);
  cyc = cyc.filter((r) => !(r.up_cycle_magnitude === null && r.down_cycle_magnitude === null));
  const sorted = stableSort(cyc, (a, b) => { const x = rank(a.ticker), y = rank(b.ticker); return x[0] - y[0] || x[1] - y[1]; });

  const mag = (x: number | null) => (x === null ? "—" : x >= 0 ? `+${pyFixed(x, 1)}%` : `${pyFixed(x, 1)}%`);
  const dur = (x: number | null) => (x === null ? "—" : `${Math.trunc(x)}d`);
  const data = sorted.map((r) => ({ "Ticker": r.ticker, "Category": tickerCat(r.ticker), "↑ Magnitude": mag(r.up_cycle_magnitude),
    "↑ Duration": dur(r.up_cycle_duration), "↓ Magnitude": mag(r.down_cycle_magnitude), "↓ Duration": dur(r.down_cycle_duration),
    "Vol Δ vs Prior Cycle": r.vol_diff_last_cycle === null ? "—" : `${pySignedFixed(r.vol_diff_last_cycle, 1)}%` }));
  const cond: unknown[] = [ODD_ROW];
  for (const c of ["↑ Magnitude", "Vol Δ vs Prior Cycle"]) cond.push({ if: { filter_query: `{${c}} contains "+"`, column_id: c }, color: GREEN, fontWeight: "600" });
  for (const c of ["↓ Magnitude", "Vol Δ vs Prior Cycle"]) cond.push({ if: { filter_query: `{${c}} contains "-"`, column_id: c }, color: RED, fontWeight: "600" });
  const tbl = DataTable({ data, columns: cols(["Ticker", "Category", "↑ Magnitude", "↑ Duration", "↓ Magnitude", "↓ Duration", "Vol Δ vs Prior Cycle"]),
    sort_action: "native", style_table: { overflowX: "auto" }, style_cell: TBL_CELL(), style_header: TBL_HEADER, style_data_conditional: cond });

  const nan = (v: number | null) => (v === null ? NaN : v);
  const figMag = emptyFigure();
  addSeries(figMag, { provenance: "derived", trace: { type: "bar", name: "Up Cycle (%)", x: sorted.map((r) => r.ticker), y: sorted.map((r) => nan(r.up_cycle_magnitude)),
    marker: { color: GREEN }, hovertemplate: "<b>%{x}</b><br>Up: +%{y:.1f}%<extra></extra>" } });
  addSeries(figMag, { provenance: "derived", trace: { type: "bar", name: "Down Cycle (%)", x: sorted.map((r) => r.ticker), y: sorted.map((r) => nan(r.down_cycle_magnitude)),
    marker: { color: RED }, hovertemplate: "<b>%{x}</b><br>Down: %{y:.1f}%<extra></extra>" } });
  pyLayout(figMag, { title: "Last Cycle Magnitude (Up vs Down)", barmode: "group", height: 350 });

  const figDur = emptyFigure();
  addSeries(figDur, { provenance: "derived", trace: { type: "bar", name: "Up Duration (days)", x: sorted.map((r) => r.ticker), y: sorted.map((r) => nan(r.up_cycle_duration)),
    marker: { color: GREEN }, hovertemplate: "<b>%{x}</b><br>Up: %{y} days<extra></extra>" } });
  addSeries(figDur, { provenance: "derived", trace: { type: "bar", name: "Down Duration (days)", x: sorted.map((r) => r.ticker), y: sorted.map((r) => nan(r.down_cycle_duration)),
    marker: { color: RED }, hovertemplate: "<b>%{x}</b><br>Down: %{y} days<extra></extra>" } });
  pyLayout(figDur, { title: "Last Cycle Duration (trading days)", barmode: "group", height: 300 });

  const vol = sorted.filter((r) => r.vol_diff_last_cycle !== null);
  const figVol = emptyFigure();
  addSeries(figVol, { provenance: "derived", trace: { type: "bar", x: vol.map((r) => r.ticker), y: vol.map((r) => r.vol_diff_last_cycle!),
    marker: { color: vol.map((r) => (r.vol_diff_last_cycle! > 0 ? GREEN : RED)) }, hovertemplate: "<b>%{x}</b><br>Vol Δ vs last cycle: %{y:+.1f}%<extra></extra>" } });
  pyLayout(figVol, { title: "Volume Change vs Previous Cycle (%)", showlegend: false, height: 280 });
  addHline(figVol, 0, { dash: "dash", color: SUBTEXT, width: 1 });

  const def = tickers.length ? tickers[0] : "";
  const value = selected ?? def;
  const defFig = def ? buildCycleChart(db, clock, def) : emptyFigure();
  const shown = selected !== undefined ? buildCycleChart(db, clock, selected) : defFig;
  // Dash fixes the graph's style height at FIRST render (the callback only swaps
  // the figure), so the container height follows the default ticker's figure.
  const graph = responsiveGraph(defFig, { displayModeBar: true }, "cycles-price-chart");
  graph.props.figure = shown;
  const chartSection = card([
    sectionTitle("Cycle Price Chart"),
    html.Div([
      html.Label("Select ticker:", { style: { color: SUBTEXT, fontSize: "12px", marginRight: "8px" } }),
      dcc.Dropdown({ id: "cycles-ticker-select", className: "cycle-ticker-select", options: tickers.map((t) => ({ label: t, value: t })),
        value, clearable: false, style: { width: "200px", display: "inline-block", backgroundColor: BG3, color: TEXT, border: "1px solid #30363d" } }),
    ], { style: { marginBottom: "10px" } }),
    html.Div([
      html.Span("🟢 Green shading = up cycle  ", { style: { color: GREEN, fontSize: "12px" } }),
      html.Span("🔴 Red shading = down cycle  ", { style: { color: RED, fontSize: "12px" } }),
      html.Span("▲ Peak  ▼ Trough — % label shows magnitude of each cycle segment", { style: { color: SUBTEXT, fontSize: "11px" } }),
    ], { style: { marginBottom: "8px" } }),
    graph,
  ]);

  return html.Div([
    card([sectionTitle("Cycle Summary"), tbl]),
    chartSection,
    card(responsiveGraph(figMag, { displayModeBar: true })),
    dbc.Row([dbc.Col(card(responsiveGraph(figDur, { displayModeBar: false })), { width: 7 }),
      dbc.Col(card(responsiveGraph(figVol, { displayModeBar: false })), { width: 5 })]),
    card(sourceFooter(stamp, "Yahoo Finance / yfinance — scipy.signal.argrelextrema",
      `Cycle peaks/troughs detected via rolling local extrema (window=${CYCLE_WINDOW} trading days). Volume Δ = current up-cycle avg volume vs prior up-cycle.`)),
  ]);
}
