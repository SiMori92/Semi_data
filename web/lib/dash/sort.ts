/**
 * dash_table "native" sort, copied from dash 4.4.1's async-table.js:
 *   R.sortWith(sort_by.map(s => R.comparator(
 *     asc:  (t, r) => !nully(t[c]) && (nully(r[c]) || t[c] < r[c])
 *     desc: (t, r) => !nully(t[c]) && (nully(r[c]) || t[c] > r[c]))), data)
 * i.e. the RAW cell value compared with JS `<`/`>` (strings by code unit, numbers
 * numerically), null/undefined and the column's `sort_as_null` values LAST in
 * both directions, stable. Header clicks cycle asc → desc → none.
 */
export type SortDir = "asc" | "desc";
export type SortBy = { column_id: string; direction: SortDir } | null;

export function nextSort(cur: SortBy, col: string): SortBy {
  if (!cur || cur.column_id !== col) return { column_id: col, direction: "asc" };
  return cur.direction === "asc" ? { column_id: col, direction: "desc" } : null;
}

export function dashSort<T extends Record<string, unknown>>(data: readonly T[], by: SortBy, sortAsNull: readonly unknown[] = []): T[] {
  if (!by) return [...data];
  const c = by.column_id;
  const nully = (v: unknown) => v === null || v === undefined || sortAsNull.includes(v);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const lt = (a: any, b: any) => a < b, gt = (a: any, b: any) => a > b;
  const op = by.direction === "asc" ? lt : gt;
  const pred = (t: T, r: T) => !nully(t[c]) && (nully(r[c]) || op(t[c], r[c]));
  return data.map((row, i) => [row, i] as const)
    .sort(([a, i], [b, j]) => (pred(a, b) ? -1 : pred(b, a) ? 1 : i - j))
    .map(([row]) => row);
}
