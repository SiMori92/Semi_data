"use client";
/**
 * dash_table.DataTable equivalent: same props (data, columns, style_cell,
 * style_header, style_data_conditional, sort_action="native", page_size).
 * Conditional styles support the filter_query forms the dashboard uses:
 *   {col} contains "x" · {col} = "x" · {col} eq "x" · {col} != "x" · row_index "odd".
 */
import { useMemo, useState, type CSSProperties } from "react";
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
  const [sort, setSort] = useState<SortBy>(null);
  const [page, setPage] = useState(0);
  const rows = useMemo(() => dashSort(p.data, sort, p.columns.find((c) => c.id === sort?.column_id)?.sort_as_null ?? []),
    [p.data, p.columns, sort]);
  const size = p.page_size ?? 250;
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const shown = rows.slice(page * size, page * size + size);

  // dash_table's own defaults (measured from the running Dash app), under style_cell
  const BASE: CSSProperties = { textAlign: "right", fontFamily: "monospace", whiteSpace: "nowrap" };
  const cellStyle = (row: Record<string, unknown>, rowIndex: number, col: string): CSSProperties => {
    const s: Record<string, unknown> = { ...BASE, ...(p.style_cell ?? {}) };
    for (const c of p.style_data_conditional ?? []) {
      const { if: cond, ...rest } = c;
      if (cond.row_index && (cond.row_index === "odd") !== (rowIndex % 2 === 1)) continue;
      if (cond.column_id && cond.column_id !== col) continue;
      if (cond.filter_query && !matches(cond.filter_query, row)) continue;
      Object.assign(s, rest);
    }
    return s as CSSProperties;
  };

  return (
    <div className="dash-table-container" style={p.style_table}>
      <table className="semi-dt" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {p.columns.map((c) => (
              <th key={c.id} style={{ ...BASE, ...(p.style_cell ?? {}), ...(p.style_header ?? {}), cursor: p.sort_action ? "pointer" : undefined, whiteSpace: "nowrap" }}
                onClick={p.sort_action ? () => setSort((s) => nextSort(s, c.id)) : undefined}>
                {p.sort_action ? <span style={{ opacity: 0.6, marginRight: 4 }}>{sort?.column_id === c.id ? (sort.direction === "asc" ? "▲" : "▼") : "⇅"}</span> : null}
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i}>{p.columns.map((c) => <td key={c.id} style={cellStyle(r, page * size + i, c.id)}>{r[c.id] === null || r[c.id] === undefined ? "" : String(r[c.id])}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {pages > 1 ? (
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center", fontSize: 12, marginTop: 6, color: "#8b949e" }}>
          <button className="btn btn-sm btn-outline-secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>‹</button>
          {page + 1} / {pages}
          <button className="btn btn-sm btn-outline-secondary" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>›</button>
        </div>
      ) : null}
    </div>
  );
}
