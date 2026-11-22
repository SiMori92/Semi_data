"use client";
/**
 * Client-only Plotly renderer (the `dynamic(..., { ssr: false })` equivalent:
 * plotly.js is imported inside useEffect, so it never runs on the server).
 * Uses plotly.js 4.1.1 — the exact build production Dash serves — and Python
 * plotly's default "plotly" template, so traces/axes/rangeselectors match 1:1.
 * Receives a finished, Zod-validated figure from a Server Component; it never
 * touches data itself.
 *
 * UI-01 theming: figures carry `var(--token)` colour references (lib/config.ts).
 * Plotly cannot read CSS variables, so they are resolved against the live
 * computed style right before drawing, and the chart redraws whenever
 * <html data-theme> changes (ThemeToggle). Server output stays theme-free.
 */
import { useEffect, useRef, useState } from "react";
import template from "@/lib/plotly/template.json";
import type { Figure } from "@/lib/plotly/figure";
import { resolveCssVars } from "@/lib/theme";

/** Current <html data-theme>, updated live. */
function useDocTheme(): string {
  const [t, setT] = useState("light");
  useEffect(() => {
    const el = document.documentElement;
    const read = () => setT(el.dataset.theme ?? "light");
    read();
    const mo = new MutationObserver(read);
    mo.observe(el, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return t;
}

type PlotlyModule = {
  react: (el: HTMLElement, data: unknown[], layout: unknown, config: unknown) => Promise<unknown>;
  purge: (el: HTMLElement) => void;
};

export function PlotlyChart({ figure, displayModeBar, id }: { figure: Figure; displayModeBar: boolean; id?: string }) {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const theme = useDocTheme();
  useEffect(() => {
    let alive = true;
    const el = ref.current;
    setLoading(true);
    setFailed(false);
    (async () => {
      try {
      const mod = (await import("plotly.js-dist-min")) as unknown as { default: PlotlyModule };
      if (!alive || !el) return;
      const css = getComputedStyle(document.documentElement);
      const fig = resolveCssVars(figure, (n) => css.getPropertyValue(`--${n}`));
      await mod.default.react(el, fig.data, { ...fig.layout, template, autosize: true },
        { displayModeBar, responsive: true });
      } catch {
        if (alive) setFailed(true);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
      if (el) import("plotly.js-dist-min").then((m) => (m as unknown as { default: PlotlyModule }).default.purge(el)).catch(() => { /* Failed imports have nothing to purge. */ });
    };
  }, [figure, displayModeBar, theme]);
  const h = typeof figure.layout.height === "number" ? figure.layout.height : 450;
  return <div className="chart-frame" style={{ position: "relative", minHeight: h }}>
    {loading && <div className="chart-loading" role="status">Loading chart…</div>}
    {failed && <div className="chart-error alert error" role="alert">Chart unavailable. Reload the page to try again. <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => window.location.reload()}>Reload page</button></div>}
    <div id={id} className="dash-graph" ref={ref} style={{ width: "100%", minHeight: h }} />
  </div>;
}
