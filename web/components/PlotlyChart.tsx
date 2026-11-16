"use client";
/**
 * Client-only Plotly renderer (the `dynamic(..., { ssr: false })` equivalent:
 * plotly.js is imported inside useEffect, so it never runs on the server).
 * Uses plotly.js 4.1.1 — the exact build production Dash serves — and Python
 * plotly's default "plotly" template, so traces/axes/rangeselectors match 1:1.
 * Receives a finished, Zod-validated figure from a Server Component; it never
 * touches data itself.
 */
import { useEffect, useRef } from "react";
import template from "@/lib/plotly/template.json";
import type { Figure } from "@/lib/plotly/figure";

type PlotlyModule = {
  react: (el: HTMLElement, data: unknown[], layout: unknown, config: unknown) => Promise<unknown>;
  purge: (el: HTMLElement) => void;
};

export function PlotlyChart({ figure, displayModeBar, id }: { figure: Figure; displayModeBar: boolean; id?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    const el = ref.current;
    (async () => {
      const mod = (await import("plotly.js-dist-min")) as unknown as { default: PlotlyModule };
      if (!alive || !el) return;
      await mod.default.react(el, figure.data, { ...figure.layout, template, autosize: true },
        { displayModeBar, responsive: true });
    })();
    return () => {
      alive = false;
      if (el) import("plotly.js-dist-min").then((m) => (m as unknown as { default: PlotlyModule }).default.purge(el));
    };
  }, [figure, displayModeBar]);
  const h = typeof figure.layout.height === "number" ? figure.layout.height : 450;
  return <div id={id} className="dash-graph" ref={ref} style={{ width: "100%", minHeight: h }} />;
}
