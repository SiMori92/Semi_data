/**
 * Renders a DNode tree (lib/dash/tree.ts — the exact shape Dash ships) as React.
 * Static html/dbc nodes render here (server-safe); interactive ones delegate to
 * small client components. Unknown component types render a visible marker
 * instead of disappearing silently.
 */
import type { CSSProperties, ReactNode } from "react";
import { isNode, type Child, type DNode } from "@/lib/dash/tree";
import type { Figure } from "@/lib/plotly/figure";
import { PlotlyChart } from "./PlotlyChart";
import { DashTable, type TableProps } from "./DashTable";
import { DashTabs } from "./DashTabs";
import { CycleSelect, ComparePicker } from "./DashControls";

const TAGS: Record<string, string> = { Div: "div", Span: "span", P: "p", Label: "label", Hr: "hr", Pre: "pre", Details: "details", Summary: "summary" };

export function DashTree({ node }: { node: Child }): ReactNode {
  if (node === null || node === undefined) return null;
  if (typeof node === "string" || typeof node === "number") return node;
  if (Array.isArray(node)) return node.map((c, i) => <DashTree key={i} node={c} />);
  if (!isNode(node)) return null;
  return <Node n={node} />;
}

function Node({ n }: { n: DNode }): ReactNode {
  const p = n.props as Record<string, unknown>;
  const style = p.style as CSSProperties | undefined;
  const id = p.id as string | undefined;
  const kids = <DashTree node={p.children as Child} />;
  const cls = (p.className as string | undefined) ?? undefined;

  if (n.namespace === "dash_html_components") {
    const Tag = (TAGS[n.type] ?? "div") as "div";
    if (n.type === "Hr") return <hr style={style} className={cls} />;
    return <Tag id={id} style={style} className={cls}>{kids}</Tag>;
  }
  if (n.namespace === "dash_bootstrap_components") {
    switch (n.type) {
      case "Row":
        if (JSON.stringify(p.children).includes('"cmp-period-a"')) return <CompareControls tree={n} />;
        return <div id={id} className={["row", cls].filter(Boolean).join(" ")} style={style}>{kids}</div>;
      case "Col": return <div id={id} className={[p.width ? `col-${p.width}` : "col", cls].filter(Boolean).join(" ")} style={style}>{kids}</div>;
      case "Tabs": return <DashTabs node={n} />;
      case "Button": return <button id={id} className={`btn btn-${p.color ?? "primary"}`} style={style}>{kids}</button>;
      case "Badge": return <span className={`badge bg-${p.color ?? "secondary"}`} style={style}>{kids}</span>;
    }
  }
  if (n.namespace === "dash_core_components") {
    switch (n.type) {
      case "Graph": {
        const cfg = (p.config ?? {}) as { displayModeBar?: boolean };
        return <PlotlyChart id={id} figure={p.figure as Figure} displayModeBar={cfg.displayModeBar !== false} />;
      }
      case "Dropdown":
        if (id === "cycles-ticker-select") return <CycleSelect options={(p.options as { value: string }[]).map((o) => o.value)} value={p.value as string} style={style} />;
        break;
      case "DatePickerRange":
        return null; // rendered as a pair by ComparePicker (see "Store" below)
      case "Store":
        if (id === "cmp-tickers") return null;
        return null;
    }
  }
  if (n.namespace === "dash_table" && n.type === "DataTable") return <DashTable {...(p as unknown as TableProps)} />;
  return <div style={{ color: "#f85149", fontSize: 11 }}>[unrendered component {n.namespace}.{n.type}]</div>;
}

/** Period Compare: Dash's controls card is replaced by an equivalent client form
 *  (two date ranges + "Compare →"), driven by the DatePickerRange props in the tree. */
export function CompareControls({ tree }: { tree: DNode }) {
  const pickers: Record<string, { start_date: string; end_date: string }> = {};
  const walk = (c: Child) => {
    if (Array.isArray(c)) return c.forEach(walk);
    if (!isNode(c)) return;
    if (c.type === "DatePickerRange") pickers[c.props.id as string] = c.props as never;
    walk(c.props.children as Child);
  };
  walk(tree);
  return <ComparePicker a={pickers["cmp-period-a"]} b={pickers["cmp-period-b"]} />;
}
