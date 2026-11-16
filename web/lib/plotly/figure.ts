/**
 * Typed Plotly figure helpers. Two production crashes and one rendering bug in
 * dashboard.py came from layout plumbing (CLAUDE.md §7.1, §7.2); this module's
 * API makes each of them impossible to write rather than merely documented:
 *
 *  §7.1  `baseLayout(extra)` — `extra` may NOT contain font / xaxis / yaxis (a
 *        type error). Axis styling goes through `updateAxis()`, which deep-merges
 *        onto the template keys instead of replacing them.
 *  §7.2  The rangeselector button dict is private. The ONLY way to put one on a
 *        figure is `withRangeSelector()`, which also reserves the headroom
 *        (`_apply_rangeselector_layout`) — the two can no longer be separated.
 *
 * Provenance: every trace enters a figure through `series()`, which REQUIRES a
 * provenance. A "modeled" series is forced into the open-marker/dotted style
 * and gets the "(modeled)" legend suffix — it cannot be drawn as observed.
 */
import { ACCENT, BG2, PLOTLY_BASE, TEXT } from "../config";
import type { Provenance } from "../schemas";

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export type Trace = { type: string; [k: string]: Json | undefined };
export type Layout = { [k: string]: Json | undefined };
export type Figure = { data: Trace[]; layout: Layout };

type Forbidden = "font" | "xaxis" | "yaxis";
export type LayoutExtras = { [K in string]: K extends Forbidden ? never : Json | undefined };

const isObj = (v: unknown): v is Record<string, Json> => typeof v === "object" && v !== null && !Array.isArray(v);
function deepMerge(target: Record<string, Json | undefined>, patch: Record<string, Json | undefined>) {
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) continue;
    const cur = target[k];
    if (isObj(cur) && isObj(v)) deepMerge(cur, v);
    else target[k] = structuredClone(v);
  }
  return target;
}

/** update_layout(**PLOTLY_TEMPLATE["layout"], **extra) — merges onto `fig.layout`. */
export function baseLayout<E extends LayoutExtras>(fig: Figure, extra: E & { [K in Forbidden]?: never }): Figure {
  deepMerge(fig.layout, structuredClone(PLOTLY_BASE) as unknown as Layout);
  deepMerge(fig.layout, extra as Layout);
  return fig;
}

/** fig.update_xaxes / update_yaxes(..., row, col) — deep-merge into one axis. */
export function updateAxis(fig: Figure, axis: `xaxis${string}` | `yaxis${string}`, patch: Layout): Figure {
  const cur = (fig.layout[axis] ?? {}) as Record<string, Json>;
  fig.layout[axis] = deepMerge(cur, patch) as Json;
  return fig;
}

/** fig.update_layout(...) for keys that are not template-owned. */
export function updateLayout(fig: Figure, patch: LayoutExtras & { [K in Forbidden]?: never }): Figure {
  deepMerge(fig.layout, patch as Layout);
  return fig;
}

// ── §7.2: rangeselector + its headroom, inseparable ─────────────────────────
const rangeselectorButtons = (): Json => ({
  buttons: [
    { count: 1, label: "1Y", step: "year", stepmode: "backward" },
    { count: 3, label: "3Y", step: "year", stepmode: "backward" },
    { count: 5, label: "5Y", step: "year", stepmode: "backward" },
  ],
  activecolor: ACCENT, bgcolor: BG2, bordercolor: "#30363d", borderwidth: 1,
  font: { color: TEXT, size: 11 },
  x: 0, xanchor: "left", y: 1.03, yanchor: "bottom",
});

export function withRangeSelector(
  fig: Figure,
  opts: { axis?: `xaxis${string}`; range: [string, string]; legendBottom?: boolean; extraHeight?: number; axisExtras?: Layout },
): Figure {
  updateAxis(fig, opts.axis ?? "xaxis", {
    ...(opts.axisExtras ?? {}),
    range: opts.range, rangeselector: rangeselectorButtons(), rangeslider: { visible: false }, type: "date",
  });
  const h = (typeof fig.layout.height === "number" ? fig.layout.height : 0) || 400;
  const upd: Layout = {
    height: h + (opts.extraHeight ?? 70),
    title: { y: 0.975, yanchor: "top", x: 0.01, xanchor: "left" },
  };
  if (opts.legendBottom ?? true) {
    upd.margin = { l: 60, r: 25, t: 95, b: 95 };
    upd.legend = { orientation: "h", yanchor: "top", y: -0.18, xanchor: "left", x: 0,
      font: { color: TEXT, size: 10 }, bgcolor: "rgba(0,0,0,0)", bordercolor: "#30363d" };
  } else {
    upd.margin = { l: 60, r: 25, t: 95, b: 55 };
  }
  deepMerge(fig.layout, upd);
  return fig;
}

// ── provenance-carrying traces ──────────────────────────────────────────────
export const MODELED_SUFFIX = "  (modeled)";

/** `_trace_style(is_modeled, color, width)` */
export function traceStyle(isModeled: boolean, color: string, width = 2.0): Record<string, Json> {
  if (isModeled) {
    return { mode: "lines+markers", line: { color, width: 1, dash: "dot" },
             marker: { color, size: 6, symbol: "circle-open" }, opacity: 0.85 };
  }
  return { mode: "lines+markers", line: { color, width }, marker: { color, size: 4 } };
}

export type Series = { provenance: Provenance; trace: Trace };

/** The only way a trace enters a figure. A modeled series is restyled and
 *  suffixed no matter what the caller asked for. */
/** A modeled trace already drawn in the modeled convention — dotted connector
 *  AND open markers — keeps its own symbol/size (e.g. the CPU chart's per-vendor
 *  shapes). Anything else is forced into traceStyle(true). */
const isModeledStyled = (t: Trace) => {
  const line = t.line as Record<string, Json> | undefined, marker = t.marker as Record<string, Json> | undefined;
  return line?.dash === "dot" && typeof marker?.symbol === "string" && (marker.symbol as string).endsWith("-open");
};

/** `exempt: "single-point"` — a modeled value plotted as ONE marker (no connector,
 *  so there is no line style to carry provenance; e.g. TFLOPS-vs-latest-price).
 *  Asserted, not trusted: a multi-point trace with the exemption throws. */
export function addSeries(fig: Figure, s: Series, exempt?: "single-point"): Figure {
  if (exempt === "single-point") {
    if (!Array.isArray(s.trace.x) || s.trace.x.length !== 1) throw new Error("single-point exemption used on a multi-point trace");
    fig.data.push(s.trace);
    return fig;
  }
  if (s.provenance === "modeled" && isModeledStyled(s.trace)) {
    const name = String(s.trace.name ?? "");
    fig.data.push({ ...s.trace, name: name.endsWith(MODELED_SUFFIX) ? name : name + MODELED_SUFFIX });
    return fig;
  }
  if (s.provenance === "modeled") {
    const color = String((s.trace.line as Record<string, Json> | undefined)?.color ?? (s.trace.marker as Record<string, Json> | undefined)?.color ?? "#888");
    const name = String(s.trace.name ?? "");
    fig.data.push({ ...s.trace, ...traceStyle(true, color),
                    name: name.endsWith(MODELED_SUFFIX) ? name : name + MODELED_SUFFIX });
  } else {
    fig.data.push(s.trace);
  }
  return fig;
}

export const emptyFigure = (): Figure => ({ data: [], layout: {} });

// ── Python-style layout kwargs ──────────────────────────────────────────────
/** `fig.update_layout(**PLOTLY_TEMPLATE["layout"], title="…", xaxis_title="…", …)`.
 *  `title`/`*_title` are the magic-underscore forms; everything else is a plain
 *  layout key. font/xaxis/yaxis remain forbidden (§7.1). */
export function pyLayout(fig: Figure, kw: { title?: string; xaxis_title?: string; yaxis_title?: string } & LayoutExtras & { [K in Forbidden]?: never }): Figure {
  const { title, xaxis_title, yaxis_title, ...rest } = kw as Record<string, Json | undefined>;
  baseLayout(fig, rest as LayoutExtras);
  if (title !== undefined) deepMerge(fig.layout, { title: { text: title } });
  if (xaxis_title !== undefined) updateAxis(fig, "xaxis", { title: { text: xaxis_title } });
  if (yaxis_title !== undefined) updateAxis(fig, "yaxis", { title: { text: yaxis_title } });
  return fig;
}

/** fig.update_yaxes(...) with no row/col — applies to EVERY y axis present. */
export function updateAllAxes(fig: Figure, prefix: "xaxis" | "yaxis", patch: Layout): Figure {
  const keys = Object.keys(fig.layout).filter((k) => new RegExp(`^${prefix}\\d*$`).test(k));
  if (!keys.includes(prefix)) keys.unshift(prefix);
  for (const k of keys) updateAxis(fig, k as `xaxis${string}`, patch);
  return fig;
}

// ── add_hline / add_vline / add_vrect (plotly.py's exact shape+annotation output)
type LineOpts = { dash?: string; color?: string; width?: number };
type AnnOpts = { text?: string; position?: string; font?: Record<string, Json>; extra?: Record<string, Json> };
const lineOf = (o: LineOpts) => {
  const l: Record<string, Json> = {};
  if (o.color !== undefined) l.color = o.color;
  if (o.dash !== undefined) l.dash = o.dash;
  if (o.width !== undefined) l.width = o.width;
  return l;
};
const push = (fig: Figure, key: "shapes" | "annotations", v: Json) => {
  const arr = (fig.layout[key] as Json[] | undefined) ?? [];
  arr.push(v);
  fig.layout[key] = arr;
};
function annotation(fig: Figure, base: Record<string, Json>, a: AnnOpts) {
  if (a.text === undefined) return; // plotly adds one even for annotation_text="" (empty label, kept)
  const ann: Record<string, Json> = { showarrow: false, text: a.text, ...base, ...(a.extra ?? {}) };
  if (a.font && Object.keys(a.font).length) ann.font = a.font;
  push(fig, "annotations", ann);
}

export function addHline(fig: Figure, y: number, line: LineOpts, a: AnnOpts = {}): Figure {
  push(fig, "shapes", { type: "line", x0: 0, x1: 1, xref: "x domain", y0: y, y1: y, yref: "y", line: lineOf(line) });
  const pos = a.position ?? "top right";
  const base: Record<string, Json> = pos === "right"
    ? { x: 1, xanchor: "left", xref: "x domain", y, yanchor: "middle", yref: "y" }
    : { x: 1, xanchor: "right", xref: "x domain", y, yanchor: "bottom", yref: "y" };
  annotation(fig, base, a);
  return fig;
}

export function addVline(fig: Figure, x: string | number, line: LineOpts, a: AnnOpts = {}): Figure {
  push(fig, "shapes", { type: "line", x0: x, x1: x, xref: "x", y0: 0, y1: 1, yref: "y domain", line: lineOf(line) });
  annotation(fig, { x, xanchor: "left", xref: "x", y: 1, yanchor: "top", yref: "y domain" }, a); // "top right"
  return fig;
}

export function addVrect(fig: Figure, x0: string, x1: string, s: { fillcolor: string; lineWidth: number; opacity?: number }, a: AnnOpts = {}): Figure {
  const shape: Record<string, Json> = { type: "rect", x0, x1, xref: "x", y0: 0, y1: 1, yref: "y domain",
    fillcolor: s.fillcolor, line: { width: s.lineWidth } };
  if (s.opacity !== undefined) shape.opacity = s.opacity;
  push(fig, "shapes", shape);
  annotation(fig, { x: x0, xanchor: "left", xref: "x", y: 1, yanchor: "top", yref: "y domain" }, a); // "top left"
  return fig;
}

/** fig.add_shape / fig.add_annotation — raw. */
export const addShape = (fig: Figure, s: Record<string, Json>) => (push(fig, "shapes", s), fig);
export const addAnnotation = (fig: Figure, a: Record<string, Json>) => (push(fig, "annotations", a), fig);
