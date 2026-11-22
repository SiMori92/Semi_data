"use client";
/**
 * dash_table.DataTable equivalent: same props (data, columns, style_cell,
 * style_header, style_data_conditional, sort_action="native", page_size).
 * Conditional styles support the filter_query forms the dashboard uses:
 *   {col} contains "x" · {col} = "x" · {col} eq "x" · {col} != "x" · row_index "odd".
 */
import { useId, useMemo, useState, type CSSProperties } from "react";
import { Badge } from "./Badge";
import { statusVariant } from "@/lib/presentation";
import { dashSort, nextSort, type SortBy } from "@/lib/dash/sort";

type Cond = { if: { row_index?: "odd" | "even"; filter_query?: string; column_id?: string } } & Record<string, unknown>;
export type TableProps = {
  data: Record<string, unknown>[]; columns: { name: string; id: string; sort_as_null?: unknown[] }[];
  style_table?: CSSProperties; style_cell?: CSSProperties; style_header?: CSSProperties;
  style_data_conditional?: Cond[]; sort_action?: "native"; page_size?: number;
};

function matches(q: string, row: Record<string, unknown>): boolean {
  const m = /^\{(.+?)\}\s+(contains|=|eq|!=)\s+"(.*)"$/.exec(q.trim());
  if (!m) return false;
  const v = String(row[m[1]] ?? "");
  switch (m[2]) {
    case "contains": return v.includes(m[3]);
    case "=": case "eq": return v === m[3];
    case "!=": return v !== m[3];
  }
  return false;
}

export function DashTable(p: TableProps) {
  const hintId = useId();
  const [sort, setSort] = useState<SortBy>(null);
  const [page, setPage] = useState(0);
  const rows = useMemo(() => dashSort(p.data, sort, p.columns.find((c) => c.id === sort?.column_id)?.sort_as_null ?? []),
    [p.data, p.columns, sort]);
  const size = p.page_size ?? 250;
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const currentPage = Math.min(page, pages - 1);
  const shown = rows.slice(currentPage * size, currentPage * size + size);

  // dash_table's own defaults (measured from the running Dash app), under style_cell
  const BASE: CSSProperties = { textAlign: "right", fontFamily: "inherit", whiteSpace: "nowrap" };
  const cellStyle = (row: Record<string, unknown>, rowIndex: number, col: string): CSSProperties => {
    const s: Record<string, unknown> = { ...BASE, ...(p.style_cell ?? {}) };
    for (const c of p.style_data_conditional ?? []) {
      const { if: cond, ...rest } = c;
      if (cond.row_index && (cond.row_index === "odd") !== (rowIndex % 2 === 1)) continue;
      if (cond.column_id && cond.column_id !== col) continue;
      if (cond.filter_query && !matches(cond.filter_query, row)) continue;
      Object.assign(s, rest);
    }
    if (s.fontSize && parseFloat(String(s.fontSize)) < 12) s.fontSize = "12px";
    return s as CSSProperties;
  };

  return (
    <div className="dash-table-container table-wrap" style={p.style_table} role="region" tabIndex={0}
      aria-label={`Data table: ${p.columns.map(c => c.name).join(", ")}`} aria-describedby={hintId}>
      <table className="semi-dt" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {p.columns.map((c) => (
              <th key={c.id} scope="col"
                aria-sort={p.sort_action ? sort?.column_id === c.id ? sort.direction === "asc" ? "ascending" : "descending" : "none" : undefined}
                style={{ ...BASE, ...(p.style_cell ?? {}), ...(p.style_header ?? {}), color: "var(--muted)", fontSize: 12, whiteSpace: "nowrap" }}>
                {p.sort_action ? <button className="table-sort" type="button" onClick={() => { setSort(s => nextSort(s, c.id)); setPage(0); }}>
                  <span aria-hidden="true">{sort?.column_id === c.id ? (sort.direction === "asc" ? "▲" : "▼") : "⇅"}</span> {c.name}
                </button> : c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i}>{p.columns.map((c) => <td key={c.id} style={cellStyle(r, currentPage * size + i, c.id)}>{r[c.id] === null || r[c.id] === undefined ? "" : ["Status", "Last result", "Last run", "Result", "Vol Source"].includes(c.id)
              ? <Badge variant={statusVariant(String(r[c.id]))}>{String(r[c.id])}</Badge> : String(r[c.id])}</td>)}</tr>
          ))}
        </tbody>
      </table>
      <div id={hintId} className="table-scroll-hint">Scroll horizontally for more columns.</div>
      {pages > 1 ? (
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center", fontSize: 12, marginTop: 6, color: "var(--muted)" }}>
          <button className="btn btn-sm btn-outline-secondary" aria-label="Previous table page" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>‹</button>
          {currentPage + 1} / {pages}
          <button className="btn btn-sm btn-outline-secondary" aria-label="Next table page" disabled={currentPage >= pages - 1} onClick={() => setPage(currentPage + 1)}>›</button>
        </div>
      ) : null}
    </div>
  );
}
