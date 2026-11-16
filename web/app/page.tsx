/**
 * The app shell + tab router (Server Component). All data is queried here, on
 * the server, through Zod-validated helpers; client components receive only
 * serialisable, finished props. No DB access or secrets ever reach the browser.
 */
import Link from "next/link";
import { Card, DataUnavailable } from "@/components/Card";
import { NavStatus } from "@/components/NavStatus";
import { ActiveTabIntoView } from "@/components/ActiveTabIntoView";
import { OverviewTab } from "@/components/OverviewTab";
import { DashTree } from "@/components/DashTree";
import { buildFinancials } from "@/lib/tabs/financials";
import { buildSentiment } from "@/lib/tabs/sentiment";
import { buildCycles } from "@/lib/tabs/cycles";
import { buildCompare, runComparison } from "@/lib/tabs/compare";
import { buildSupplyChain } from "@/lib/tabs/supplychain";
import { Sidebar } from "@/components/Sidebar";
import { systemClock } from "@/lib/clock";
import { BG, BG2, RED, SUBTEXT, TEXT } from "@/lib/config";
import { DataUnavailableError } from "@/lib/db";
import { getEnv, volumeStatus } from "@/lib/env";
import { buildOverview } from "@/lib/overview";
import { parseView, TABS, viewHref, type View } from "@/lib/params";
import { getDb } from "@/lib/server";
import { statusPayload } from "@/lib/status";

export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const env = getEnv();
  const db = getDb();
  const clock = systemClock();
  const view = parseView(await searchParams, clock);
  const vol = volumeStatus(env);

  return (
    <div className="dashboard-app container-fluid" style={{ background: BG, minHeight: "100vh", padding: 0 }}>
      <nav className="navbar navbar-expand-md navbar-dark" style={{ backgroundColor: BG2, borderBottom: "1px solid #30363d", padding: "10px 20px" }}>
        <div className="dashboard-navbar container-fluid">
          <span className="dashboard-brand" style={{ color: TEXT, fontSize: 17, fontWeight: 700, letterSpacing: 0.3 }}>⚡ Semiconductor Industry Tracker</span>
          <NavStatus initial={statusPayload(db, clock, env)} />
        </div>
      </nav>

      {vol.ok ? null : (
        <div style={{ background: RED, color: "#fff", padding: "8px 20px", fontSize: 12.5, letterSpacing: 0.2, borderBottom: "1px solid #7d1d17" }}>
          <span style={{ fontWeight: 700, marginRight: 12 }}>⚠️ EPHEMERAL STORAGE — DATA WILL BE LOST ON REDEPLOY</span>
          <span style={{ opacity: 0.9 }}>{vol.reason}</span>
          <span style={{ opacity: 0.75, marginLeft: 12 }}>  Fix: Railway → service → Settings → Volumes, then point DB_PATH inside the mount.</span>
        </div>
      )}

      <div className="dashboard-shell row" style={{ margin: 0 }}>
        <Sidebar key={`${view.tickers.join(",")}|${view.start}|${view.end}`} view={view} />
        <div className="dashboard-main col-lg-10" style={{ padding: 16, overflowY: "auto", maxHeight: "calc(100vh - 56px)" }}>
          <ul className="dashboard-tabs nav nav-tabs" role="tablist" style={{ marginBottom: 16, ["--bs-nav-tabs-border-color" as string]: "#30363d" }}>
            {TABS.map((t) => (
              <div className="nav-item" key={t.id}>
                <Link role="tab" className={`nav-link${view.tab === t.id ? " active" : ""}`} href={viewHref({ tab: t.id }, view)} scroll={false}>{t.label}</Link>
              </div>
            ))}
          </ul>
          <ActiveTabIntoView tab={view.tab} />
          <TabContent view={view} />
        </div>
      </div>
    </div>
  );

  function TabContent({ view }: { view: View }) {
    if (view.tickers.length === 0) return <Card><p style={{ color: SUBTEXT }}>Select at least one ticker in Filters.</p></Card>;
    try {
      switch (view.tab) {
        case "overview": return <OverviewTab r={buildOverview(db, clock, view.tickers, view.start, view.end)} />;
        case "financials": return <DashTree node={buildFinancials(db, clock, view.tickers)} />;
        case "sentiment": return <DashTree node={buildSentiment(db, clock, view.tickers)} />;
        case "cycles": return <DashTree node={buildCycles(db, clock, view.tickers, view.cyc)} />;
        case "compare": {
          const out = view.cmp ? runComparison(db, view.cmp.a0, view.cmp.a1, view.cmp.b0, view.cmp.b1, view.tickers) : null;
          return <DashTree node={buildCompare(clock, view.tickers, out)} />;
        }
        case "supplychain": return <DashTree node={buildSupplyChain(db, clock)} />;
      }
    } catch (e) {
      if (e instanceof DataUnavailableError) return <DataUnavailable what={e.what} detail={e.issues} />;
      throw e;
    }
  }
}
