"use client";
/** dbc.Tabs with pre-rendered dbc.Tab children (CSS show/hide, no server round trip) —
 *  the pattern CLAUDE.md §6.2 prescribes for the Supply Chain sub-tabs. */
import { useId, useRef, useState, type CSSProperties } from "react";
import type { DNode } from "@/lib/dash/tree";
import { DashTree } from "./DashTree";

export function DashTabs({ node }: { node: DNode }) {
  const groupId = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const tabs = (node.props.children as DNode[]) ?? [];
  const [active, setActive] = useState((node.props.active_tab as string) ?? (tabs[0]?.props.tab_id as string));
  return (
    <div>
      <ul className="nav nav-tabs" role="tablist" aria-label="Supply chain categories" style={node.props.style as CSSProperties}>
        {tabs.map((t, index) => {
          const on = t.props.tab_id === active;
          return (
            <li role="presentation" className="nav-item" key={t.props.tab_id as string}>
              <button type="button" role="tab" id={`${groupId}-tab-${index}`} aria-controls={`${groupId}-panel-${index}`} aria-selected={on} tabIndex={on ? 0 : -1}
                ref={el => { buttons.current[index] = el; }} className={`nav-link${on ? " active" : ""}`}
                style={{ ...(t.props.label_style as CSSProperties), ...(on ? (t.props.active_label_style as CSSProperties) : {}), cursor: "pointer" }}
                onClick={() => setActive(t.props.tab_id as string)}
                onKeyDown={e => {
                  const next = e.key === "ArrowRight" ? (index + 1) % tabs.length : e.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
                  if (next === null) return;
                  e.preventDefault();
                  setActive(tabs[next].props.tab_id as string);
                  buttons.current[next]?.focus();
                }}>{t.props.label as string}</button>
            </li>
          );
        })}
      </ul>
      <div className="tab-content">
        {tabs.map((t, index) => (
          <div key={t.props.tab_id as string} id={`${groupId}-panel-${index}`} role="tabpanel" aria-labelledby={`${groupId}-tab-${index}`} tabIndex={0} className="tab-pane" hidden={t.props.tab_id !== active}>
            <DashTree node={t.props.children as never} />
          </div>
        ))}
      </div>
    </div>
  );
}
