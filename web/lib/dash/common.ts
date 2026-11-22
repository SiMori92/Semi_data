/** Ports of the dashboard.py layout helpers: _card, _section_title, _kpi,
 *  _source_footer, _responsive_graph, _modeled_note and the DataTable style
 *  blocks every tab repeats. Output = DNode trees (lib/dash/tree.ts). */
import { BG2, SUBTEXT, TEXT } from "../config";
import type { Figure, Json } from "../plotly/figure";
import { dcc, html, type Child, type DNode } from "./tree";

export function card(children: Child, style?: Record<string, unknown>): DNode {
  return html.Div(children, { style, className: "dashboard-card panel" });
}

export const sectionTitle = (text: string): DNode =>
  html.Div(text, { className: "section-title" });

/** `_source_footer(source, notes)` — `stamp` is `_crawl_timestamp()`. */
export function sourceFooter(stamp: string, source: string, notes = ""): DNode {
  const parts: DNode[] = [
    html.Span(`[Source: ${source}]`, { style: { marginRight: "12px" } }),
    html.Span(`[Data Last Crawled/Updated: ${stamp}]`, { style: { color: SUBTEXT } }),
  ];
  if (notes) parts.push(html.Span(`  ·  ${notes}`, { style: { color: SUBTEXT } }));
  return html.Div(parts, { className: "source-footer" });
}

/** `_responsive_graph()` incl. the WEB-01a fix: container height = figure height. */
export function responsiveGraph(figure: Figure, config: { [k: string]: Json }, id?: string): DNode {
  const h = figure.layout.height;
  return dcc.Graph({ id, figure, config, responsive: true,
    style: typeof h === "number" && h ? { height: `${Math.trunc(h)}px` } : undefined });
}

export const modeledNote = (what: string): DNode => html.Div(
  `⚠️ ${what} are MODELED estimates, not observations — drawn as open markers on a ` +
  "dotted connector so they cannot be read as measured data. The month-to-month " +
  "shape is an author's assumption (several run at a constant step or constant " +
  "percentage for 10+ months); read the level, not the trend. Solid lines elsewhere " +
  "on this dashboard are observed. See BACKLOG SC-16.",
  { className: "alert warning" });

export const TBL_CELL = (fontSize = "13px", padding = "6px 10px") =>
  ({ color: TEXT, border: "1px solid var(--line)", fontSize, padding });
export const TBL_HEADER = { backgroundColor: BG2, color: SUBTEXT, fontWeight: "600", border: "1px solid var(--line)" };
export const ODD_ROW = { if: { row_index: "odd" }, backgroundColor: "var(--bg)" };
export const cols = (names: string[], labels?: (c: string) => string) =>
  names.map((c) => ({ name: labels ? labels(c) : c, id: c }));
