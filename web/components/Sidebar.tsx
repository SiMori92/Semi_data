"use client";
/**
 * Filters sidebar — ticker checklists, date range, Select/Clear All. Every change
 * is written to the URL (router.replace), so the view is linkable and the Server
 * Components re-query. Same class names as Dash so responsive.css applies as-is.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ACCENT, BG2, TEXT, TICKER_GROUPS } from "@/lib/config";
import type { View } from "@/lib/params";
import { viewHref } from "@/lib/params";

const groupId = (name: string) => `chk-${name.toLowerCase().replace(/ /g, "-").replace(/\//g, "")}`;

export function Sidebar({ view }: { view: View }) {
  const router = useRouter();
  const [sel, setSel] = useState<string[]>(view.tickers);
  const [start, setStart] = useState(view.start);
  const [end, setEnd] = useState(view.end);

  const push = (tickers: string[], s = start, e = end) => {
    // sync_tickers order: group by group, in each group's checklist order
    const ordered = TICKER_GROUPS.flatMap((g) => (g.members as readonly string[]).filter((t) => tickers.includes(t)));
    const extra = tickers.filter((t) => !ordered.includes(t));
    const next = [...ordered, ...extra];
    setSel(next);
    router.replace(viewHref({ tab: view.tab, tickers: next, start: s, end: e }, view), { scroll: false });
  };

  const n = sel.length;
  return (
    <div className="dashboard-sidebar col-lg-2" style={{ background: BG2, borderRight: "1px solid #30363d", padding: 16, minHeight: "calc(100vh - 56px)", overflowY: "auto" }}>
      <div className="form-check mobile-filter-toggle">
        <input id="mobile-filter-toggle" className="form-check-input" type="checkbox" />
      </div>
      <label className="mobile-filter-label" htmlFor="mobile-filter-toggle">
        <span className="filter-toggle-title">Filters</span>
        <span id="filter-selected-count" className="filter-selected-count">{`${n} ticker${n !== 1 ? "s" : ""} selected`}</span>
        <span className="filter-toggle-chevron" aria-hidden="true">▾</span>
      </label>
      <div className="dashboard-filter-body">
        <Title>Date Range</Title>
        <div className="semi-daterange" style={{ fontSize: 12 }}>
          <input type="date" aria-label="Start Date" value={start} max={end}
            onChange={(e) => { setStart(e.target.value); if (e.target.value) push(sel, e.target.value, end); }} />
          <input type="date" aria-label="End Date" value={end} min={start}
            onChange={(e) => { setEnd(e.target.value); if (e.target.value) push(sel, start, e.target.value); }} />
        </div>
        <hr style={{ borderColor: "#30363d", margin: "12px 0" }} />
        {TICKER_GROUPS.map((g) => (
          <div key={g.name} style={{ marginBottom: 16 }}>
            <Title>{g.name}</Title>
            <div id={groupId(g.name)}>
              {g.members.map((t) => (
                <div className="form-check" key={t} style={{ margin: "2px 0" }}>
                  <input id={`${groupId(g.name)}-${t}`} className="form-check-input" type="checkbox" checked={sel.includes(t)}
                    style={{ marginRight: 6, accentColor: ACCENT }}
                    onChange={(e) => push(e.target.checked ? [...sel, t] : sel.filter((x) => x !== t))} />
                  <label className="form-check-label" htmlFor={`${groupId(g.name)}-${t}`} style={{ fontSize: 13, color: TEXT, cursor: "pointer" }}>{t}</label>
                </div>
              ))}
            </div>
          </div>
        ))}
        <hr style={{ borderColor: "#30363d", margin: "12px 0" }} />
        <button id="btn-select-all" className="btn btn-outline-secondary btn-sm" style={{ width: "100%", marginBottom: 6, fontSize: 12 }}
          onClick={() => push(TICKER_GROUPS.flatMap((g) => [...g.members]))}>Select All</button>
        <button id="btn-clear-all" className="btn btn-outline-secondary btn-sm" style={{ width: "100%", fontSize: 12 }}
          onClick={() => push([])}>Clear All</button>
      </div>
    </div>
  );
}

function Title({ children }: { children: string }) {
  return <div style={{ fontSize: 13, fontWeight: 600, color: ACCENT, textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>{children}</div>;
}
