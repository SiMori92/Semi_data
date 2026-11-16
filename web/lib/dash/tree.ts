/**
 * A serialisable component tree in EXACTLY the shape Dash ships to the browser
 * (`Component.to_plotly_json()`): {type, namespace, props}. The tab builders in
 * lib/tabs/ return these; components/DashTree.tsx renders them; the parity suite
 * deep-compares them with the trees golden_dump.py serialises from dashboard.py.
 *
 * Dash rules mirrored here: any component that takes children always carries a
 * `children` prop (null when none); an explicitly passed None prop is kept as null.
 */
import type { Figure, Json } from "../plotly/figure";

export type DNode = { type: string; namespace: string; props: { [k: string]: unknown } };
export type Child = DNode | string | number | null | Child[];
type Props = { [k: string]: unknown };

const NS = {
  html: "dash_html_components", dbc: "dash_bootstrap_components",
  dcc: "dash_core_components", table: "dash_table",
} as const;

const clean = (p: Props) => Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined));
const withChildren = (ns: string, type: string) => (children: Child = null, props: Props = {}): DNode =>
  ({ type, namespace: ns, props: clean({ children, ...props }) });
const noChildren = (ns: string, type: string) => (props: Props = {}): DNode =>
  ({ type, namespace: ns, props: clean(props) });

export const html = {
  Div: withChildren(NS.html, "Div"), Span: withChildren(NS.html, "Span"), P: withChildren(NS.html, "P"),
  Label: withChildren(NS.html, "Label"), Hr: withChildren(NS.html, "Hr"), Pre: withChildren(NS.html, "Pre"),
  Details: withChildren(NS.html, "Details"), Summary: withChildren(NS.html, "Summary"),
};
export const dbc = {
  Row: withChildren(NS.dbc, "Row"), Col: withChildren(NS.dbc, "Col"), Tabs: withChildren(NS.dbc, "Tabs"),
  Tab: withChildren(NS.dbc, "Tab"), Button: withChildren(NS.dbc, "Button"), Badge: withChildren(NS.dbc, "Badge"),
};
export const dcc = {
  Graph: noChildren(NS.dcc, "Graph"), Dropdown: noChildren(NS.dcc, "Dropdown"),
  DatePickerRange: noChildren(NS.dcc, "DatePickerRange"), Store: noChildren(NS.dcc, "Store"),
};
export const DataTable = noChildren(NS.table, "DataTable");

export type GraphProps = { figure: Figure; config: { [k: string]: Json }; responsive: boolean; style?: { height: string }; id?: string };
export const isNode = (x: unknown): x is DNode =>
  typeof x === "object" && x !== null && !Array.isArray(x) && "namespace" in x && "props" in x;
