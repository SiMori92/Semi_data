/** Period Compare tab — port of tab_compare() and the run_comparison() callback. */
import { addDays, ymd, type Clock } from "../clock";
import { ACCENT, SUBTEXT, YELLOW } from "../config";
import { placeholders, type Db } from "../db";
import { card, responsiveGraph, sectionTitle } from "../dash/common";
import { dbc, dcc, html, type DNode } from "../dash/tree";
import { priceData } from "../overview";
import { addHline, addSeries, emptyFigure, pyLayout } from "../plotly/figure";
import { cmpStr } from "../pd";
import { z } from "zod";

export function buildCompare(clock: Clock, tickers: readonly string[], output: DNode | null = null): DNode {
  const d = (n: number) => ymd(addDays(clock.hkt, -n));
  const picker = (id: string, s: string, e: string) => dcc.DatePickerRange({ id, number_of_months_shown: 1, with_portal: true,
    start_date: s, end_date: e, display_format: "DD MMM YYYY" });
  return html.Div([
    card([
      sectionTitle("Select Two Periods to Compare"),
      dbc.Row([
        dbc.Col([html.Label("Period A", { style: { color: SUBTEXT, fontSize: "12px" } }), picker("cmp-period-a", d(180), d(91))], { width: 5 }),
        dbc.Col([html.Label("Period B", { style: { color: SUBTEXT, fontSize: "12px" } }), picker("cmp-period-b", d(90), d(0))], { width: 5 }),
        dbc.Col([html.Div(null, { style: { height: "20px" } }), dbc.Button("Compare →", { id: "btn-compare", color: "primary", style: { marginTop: "4px" } })], { width: 2 }),
      ]),
    ]),
    html.Div(output, { id: "cmp-output" }),
    dcc.Store({ id: "cmp-tickers", data: [...tickers] }),
  ]);
}

const FinAvg = z.object({ ticker: z.string(), rev: z.number().nullable(), gp: z.number().nullable(), np: z.number().nullable() });

/** run_comparison(_, a_start, a_end, b_start, b_end, tickers) */
export function runComparison(db: Db, aStart0: string | null, aEnd0: string | null, bStart0: string | null, bEnd0: string | null, tickers: readonly string[]): DNode {
  if (!tickers.length) return html.P("No tickers selected.", { style: { color: SUBTEXT } });
  const [aStart, aEnd, bStart, bEnd] = [aStart0, aEnd0, bStart0, bEnd0].map((x) => (x ?? "").slice(0, 10));
  const ret = (rows: ReturnType<typeof priceData>) => {
    const out = new Map<string, number>();
    for (const t of tickers) {
      const sub = rows.filter((r) => r.ticker === t).sort((a, b) => cmpStr(a.date, b.date));
      if (sub.length >= 2) out.set(t, ((sub[sub.length - 1].close ?? NaN) / (sub[0].close ?? NaN) - 1) * 100);
    }
    return out;
  };
  const ra = ret(priceData(db, tickers, aStart, aEnd)), rb = ret(priceData(db, tickers, bStart, bEnd));
  const common = tickers.filter((t) => ra.has(t) && rb.has(t));
  const figRet = emptyFigure();
  addSeries(figRet, { provenance: "derived", trace: { type: "bar", name: `Period A (${aStart} → ${aEnd})`, x: common, y: common.map((t) => ra.get(t)!),
    marker: { color: ACCENT }, hovertemplate: "<b>%{x}</b><br>Period A: %{y:+.1f}%<extra></extra>" } });
  addSeries(figRet, { provenance: "derived", trace: { type: "bar", name: `Period B (${bStart} → ${bEnd})`, x: common, y: common.map((t) => rb.get(t)!),
    marker: { color: YELLOW }, hovertemplate: "<b>%{x}</b><br>Period B: %{y:+.1f}%<extra></extra>" } });
  addHline(figRet, 0, { dash: "dash", color: SUBTEXT, width: 1 });
  pyLayout(figRet, { title: "Price Return — Period A vs B", barmode: "group", height: 380 });

  const fin = (s: string, e: string) => db.all(
    `SELECT ticker, AVG(revenue) as rev, AVG(gross_profit) as gp, AVG(net_profit) as np FROM quarterly_financials WHERE ticker IN (${placeholders(tickers.length)}) AND period_end BETWEEN ? AND ? GROUP BY ticker`,
    [...tickers, s, e], FinAvg, "compare fin");
  const fa = fin(aStart, aEnd), fb = fin(bStart, bEnd);
  const charts: DNode[] = [card(responsiveGraph(figRet, { displayModeBar: true }))];
  for (const [m, label] of [["rev", "Avg Revenue"], ["gp", "Avg Gross Profit"], ["np", "Avg Net Profit"]] as const) {
    if (!fa.length && !fb.length) break;
    // pd.merge(how="outer") sorts keys lexicographically; then dropna(subset=["A","B"])
    const A = new Map(fa.map((r) => [r.ticker, r[m]])), B = new Map(fb.map((r) => [r.ticker, r[m]]));
    const keys = [...new Set([...A.keys(), ...B.keys()])].sort(cmpStr)
      .filter((t) => A.get(t) != null && B.get(t) != null);
    if (!keys.length) continue;
    const f = emptyFigure();
    addSeries(f, { provenance: "derived", trace: { type: "bar", name: "Period A", x: keys, y: keys.map((t) => A.get(t)! / 1e9), marker: { color: ACCENT },
      hovertemplate: "<b>%{x}</b><br>A: $%{y:.2f}B<extra></extra>" } });
    addSeries(f, { provenance: "derived", trace: { type: "bar", name: "Period B", x: keys, y: keys.map((t) => B.get(t)! / 1e9), marker: { color: YELLOW },
      hovertemplate: "<b>%{x}</b><br>B: $%{y:.2f}B<extra></extra>" } });
    pyLayout(f, { title: `${label} (USD Bn) — Period A vs B`, barmode: "group", height: 300 });
    charts.push(card(responsiveGraph(f, { displayModeBar: false })));
  }
  return html.Div(charts);
}
