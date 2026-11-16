/**
 * make_subplots(rows, cols, ...) — the domain arithmetic copied from
 * plotly/_subplots.py so domains match to the last bit (0.34719999999999995,
 * not 0.3472). Top-left start cell (plotly's default), row-major axis numbering.
 */
import type { Figure, Json } from "./figure";

const pySum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

export function makeSubplots(opts: {
  rows: number; cols: number; titles?: string[]; verticalSpacing?: number; horizontalSpacing?: number;
  rowHeights?: number[]; sharedXaxes?: boolean;
}): Figure {
  const { rows, cols } = opts;
  const v = opts.verticalSpacing ?? (opts.titles ? 0.5 / rows : 0.3 / rows);
  const h = opts.horizontalSpacing ?? 0.2 / cols;
  const widths = Array.from({ length: cols }, () => (1.0 - h * (cols - 1)) / cols);
  let heights: number[];
  if (opts.rowHeights) {
    const cum = pySum(opts.rowHeights);
    heights = opts.rowHeights.map((x) => (1.0 - v * (rows - 1)) * (x / cum));
    heights.reverse(); // row_dir < 0
  } else {
    heights = Array.from({ length: rows }, () => (1.0 - v * (rows - 1)) / rows);
  }
  const rowSeq = [...Array(rows).keys()].reverse();
  const gridY = rowSeq.map((r) => pySum(heights.slice(0, r)) + r * v);
  const gridX = [...Array(cols).keys()].map((c) => pySum(widths.slice(0, c)) + c * h);

  const layout: Record<string, Json> = {};
  const titles: Json[] = [];
  let n = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      n++;
      const s = n === 1 ? "" : String(n);
      const xs = gridX[c], xe = gridX[c] + widths[c];
      let ys = gridY[r];
      let ye = gridY[r] + heights[heights.length - 1 - r];
      if (ys < 0 && ys > -0.01) ys = 0.0;
      if (ys > 1 && ys < 1.01) ys = 1.0;
      if (ye > 1 && ye < 1.01) ye = 1.0;
      layout[`xaxis${s}`] = { anchor: `y${s}`, domain: [xs, xe] };
      layout[`yaxis${s}`] = { anchor: `x${s}`, domain: [ys, ye] };
      const t = opts.titles?.[n - 1];
      if (t !== undefined) {
        titles.push({ font: { size: 16 }, showarrow: false, text: t, x: (xs + xe) / 2.0, xanchor: "center",
          xref: "paper", y: ye, yanchor: "bottom", yref: "paper" });
      }
    }
  }
  if (opts.sharedXaxes && cols === 1) {
    const bottom = rows === 1 ? "x" : `x${rows}`;
    for (let r = 0; r < rows - 1; r++) {
      const s = r === 0 ? "" : String(r + 1);
      Object.assign(layout[`xaxis${s}`] as Record<string, Json>, { matches: bottom, showticklabels: false });
    }
  }
  if (opts.titles) layout.annotations = titles;
  return { data: [], layout };
}

/** Back-compat wrapper used by the Overview (shared x, single column). */
export function makeSubplotsColumn(o: { rowHeights: number[]; verticalSpacing: number; titles: string[] }): Figure {
  return makeSubplots({ rows: o.rowHeights.length, cols: 1, titles: o.titles, verticalSpacing: o.verticalSpacing,
    rowHeights: o.rowHeights, sharedXaxes: true });
}

/** Trace axis refs for (row, col) in a rows×cols grid (row-major). */
export const subplotRef = (row: number, col = 1, cols = 1) => {
  const n = (row - 1) * cols + col;
  return n === 1 ? { xaxis: "x", yaxis: "y" } : { xaxis: `x${n}`, yaxis: `y${n}` };
};
