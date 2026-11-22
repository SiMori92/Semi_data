"use client";
/**
 * UI-01 Phase 2 — ticker + date filters as a collapsible panel above the content
 * (replaces the filter sidebar; the sidebar is now navigation). Shown only on tabs
 * that read the selection (TABS[].tickers). Same URL contract as before: every
 * change is written with router.replace (?t=…&start=…&end=…), so views stay
 * linkable and the Server Components re-query.
 *
 * Not keyed on the selection (the old Sidebar was), so the panel stays open while
 * boxes are ticked; local state re-syncs from the URL when it changes.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { TICKER_GROUPS } from "@/lib/config";
import { viewHref, type View } from "@/lib/params";

const groupId = (name: string) => `chk-${name.toLowerCase().replace(/ /g, "-").replace(/\//g, "")}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dmy = (s: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  return m ? `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}` : s;
};

export function FilterPanel({ view }: { view: View }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<string[]>(view.tickers);
  const [start, setStart] = useState(view.start);
  const [end, setEnd] = useState(view.end);
  const urlKey = `${view.tickers.join(",")}|${view.start}|${view.end}`;
  useEffect(() => { setSel(view.tickers); setStart(view.start); setEnd(view.end); }, [urlKey]); // eslint-disable-line react-hooks/exhaustive-deps

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
    <details className="filter-panel" open={open} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <SlidersHorizontal size={16} aria-hidden="true" />
        <span className="filter-title">Filters</span>
        <span id="filter-selected-count" className="filter-summary">
          {`${n} ticker${n !== 1 ? "s" : ""} · ${dmy(start)} – ${dmy(end)}`}
        </span>
        <span className="filter-edit">{open ? "Close" : "Edit"}</span>
        <ChevronDown size={16} aria-hidden="true" className="filter-chevron" />
      </summary>
      <div className="filter-body">
        <fieldset className="filter-dates">
          <legend>Date range</legend>
          <label>Start
            <input type="date" value={start} max={end}
              onChange={(e) => { setStart(e.target.value); if (e.target.value) push(sel, e.target.value, end); }} />
          </label>
          <label>End
            <input type="date" value={end} min={start}
              onChange={(e) => { setEnd(e.target.value); if (e.target.value) push(sel, start, e.target.value); }} />
          </label>
        </fieldset>
        <div className="filter-groups">
          {TICKER_GROUPS.map((g) => (
            <fieldset key={g.name} id={groupId(g.name)}>
              <legend>{g.name}</legend>
              {g.members.map((t) => (
                <label className="form-check" key={t} htmlFor={`${groupId(g.name)}-${t}`}>
                  <input id={`${groupId(g.name)}-${t}`} className="form-check-input" type="checkbox" checked={sel.includes(t)}
                    onChange={(e) => push(e.target.checked ? [...sel, t] : sel.filter((x) => x !== t))} />
                  <span>{t}</span>
                </label>
              ))}
            </fieldset>
          ))}
        </div>
        <div className="filter-actions">
          <button type="button" id="btn-select-all" className="btn btn-outline-secondary btn-sm"
            onClick={() => push(TICKER_GROUPS.flatMap((g) => [...g.members]))}>Select all</button>
          <button type="button" id="btn-clear-all" className="btn btn-outline-secondary btn-sm"
            onClick={() => push([])}>Clear all</button>
        </div>
      </div>
    </details>
  );
}
