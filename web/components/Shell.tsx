/**
 * UI-01 Phase 2 — the app shell (UI Handbook "Layout"): a persistent navigation
 * sidebar (222 px → 206 px at ≤1150 → 60 px icon rail at ≤650), a topbar, and ONE
 * <main id="main"> landmark with a skip link. The page scrolls normally — no
 * fixed-height inner scroll box (the Phase 0 baseline finding).
 * Server Component: the active link comes from the parsed URL view.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { Activity, ChartLine, Cpu, Factory, Gauge, Landmark, Repeat, Scale, type LucideIcon } from "lucide-react";
import { TABS, viewHref, type TabId, type View } from "@/lib/params";

const ICONS: Record<TabId, LucideIcon> = {
  overview: ChartLine, financials: Landmark, sentiment: Gauge, cycles: Repeat,
  compare: Scale, supplychain: Factory, health: Activity,
};

export function Shell({ view, topbar, banner, children }: { view: View; topbar: ReactNode; banner?: ReactNode; children: ReactNode }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className="sidebar">
        <div className="brand">
          <Cpu size={22} aria-hidden="true" className="brand-icon" />
          <span className="brand-text"><strong>Semiconductor</strong><span>Industry Tracker</span></span>
        </div>
        <nav aria-label="Dashboard sections">
          <ul className="side-nav">
            {TABS.map((t) => {
              const Icon = ICONS[t.id];
              const on = view.tab === t.id;
              return (
                <li key={t.id}>
                  <Link href={viewHref({ tab: t.id }, view)} scroll={false} className={`side-link${on ? " active" : ""}`}
                    aria-current={on ? "page" : undefined} aria-label={t.label} title={t.label}>
                    <Icon size={18} aria-hidden="true" />
                    <span className="side-label">{t.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>
      <div className="workspace">
        <header className="topbar">{topbar}</header>
        {banner}
        <main id="main" className="main" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
