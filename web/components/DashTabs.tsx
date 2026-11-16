"use client";
/** dbc.Tabs with pre-rendered dbc.Tab children (CSS show/hide, no server round trip) —
 *  the pattern CLAUDE.md §6.2 prescribes for the Supply Chain sub-tabs. */
import { useState, type CSSProperties } from "react";
import type { DNode } from "@/lib/dash/tree";
import { DashTree } from "./DashTree";

export function DashTabs({ node }: { node: DNode }) {
  const tabs = (node.props.children as DNode[]) ?? [];
  const [active, setActive] = useState((node.props.active_tab as string) ?? (tabs[0]?.props.tab_id as string));
  return (
    <div>
      <ul className="nav nav-tabs" role="tablist" style={node.props.style as CSSProperties}>
        {tabs.map((t) => {
          const on = t.props.tab_id === active;
          return (
            <li className="nav-item" key={t.props.tab_id as string}>
              <a role="tab" href="#" className={`nav-link${on ? " active" : ""}`}
                style={{ ...(t.props.label_style as CSSProperties), ...(on ? (t.props.active_label_style as CSSProperties) : {}), cursor: "pointer" }}
                onClick={(e) => { e.preventDefault(); setActive(t.props.tab_id as string); }}>{t.props.label as string}</a>
            </li>
          );
        })}
      </ul>
      <div className="tab-content">
        {tabs.map((t) => (
          <div key={t.props.tab_id as string} className="tab-pane" style={{ display: t.props.tab_id === active ? "block" : "none" }}>
            <DashTree node={t.props.children as never} />
          </div>
        ))}
      </div>
    </div>
  );
}
