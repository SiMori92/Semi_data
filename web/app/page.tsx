/**
 * The tab router (Server Component), inside the UI-01 Shell (sidebar nav + topbar). All data is queried here, on
 * the server, through Zod-validated helpers; client components receive only
 * serialisable, finished props. No DB access or secrets ever reach the browser.
 */
import { Card, DataUnavailable } from "@/components/Card";
import { NavStatus } from "@/components/NavStatus";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Shell } from "@/components/Shell";
import { PageHeading } from "@/components/PageHeading";
import { PAGE_HEADINGS } from "@/lib/page-headings";
import { FilterPanel } from "@/components/FilterPanel";
import { cookies } from "next/headers";
import { parseTheme, THEME_COOKIE } from "@/lib/theme";
import { OverviewTab } from "@/components/OverviewTab";
import { DashTree } from "@/components/DashTree";
import { buildFinancials } from "@/lib/tabs/financials";
import { buildSentiment } from "@/lib/tabs/sentiment";
import { buildCycles } from "@/lib/tabs/cycles";
import { buildCompare, runComparison } from "@/lib/tabs/compare";
import { buildSupplyChain } from "@/lib/tabs/supplychain";
import { buildHealth } from "@/lib/tabs/health";
import { systemClock } from "@/lib/clock";
import { SUBTEXT } from "@/lib/config";
import { DataUnavailableError } from "@/lib/db";
import { getEnv, volumeStatus } from "@/lib/env";
import { buildOverview } from "@/lib/overview";
import { parseView, TABS, type View } from "@/lib/params";
import { getDb } from "@/lib/server";
import { statusPayload } from "@/lib/status";

export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const env = getEnv();
  const db = getDb();
  const clock = systemClock();
  const view = parseView(await searchParams, clock);
  const vol = volumeStatus(env);
  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);

  const usesTickers = TABS.find((t) => t.id === view.tab)?.tickers ?? false;

  return (
    <Shell view={view}
      topbar={<NavStatus initial={statusPayload(db, clock, env)} extra={<ThemeToggle initial={theme} />} />}
      banner={vol.ok ? null : (
        <div role="alert" className="volume-banner alert error">
          <strong>⚠️ Ephemeral storage — data will be lost on redeploy.</strong>{" "}
          <span>{vol.reason}</span>{" "}
          <span className="muted">Fix: Railway → service → Settings → Volumes, then point DB_PATH inside the mount.</span>
        </div>
      )}>
      <PageHeading {...PAGE_HEADINGS[view.tab]} visitKey={view.tab} />
      {usesTickers ? <FilterPanel view={view} /> : null}
      <TabContent view={view} />
    </Shell>
  );

  function TabContent({ view }: { view: View }) {
    try {
      // Supply Chain and Data Health don't read tickers (no filter panel there), so they
      // must render even with an empty selection.
      if (view.tab === "health") return <DashTree node={buildHealth(db, clock)} />;
      if (view.tab === "supplychain") return <DashTree node={buildSupplyChain(db, clock)} />;
      if (view.tickers.length === 0) return <Card><p style={{ color: SUBTEXT }}>No tickers selected. Open Filters above and choose at least one.</p></Card>;
      switch (view.tab) {
        case "overview": return <OverviewTab r={buildOverview(db, clock, view.tickers, view.start, view.end)} />;
        case "financials": return <DashTree node={buildFinancials(db, clock, view.tickers)} />;
        case "sentiment": return <DashTree node={buildSentiment(db, clock, view.tickers)} />;
        case "cycles": return <DashTree node={buildCycles(db, clock, view.tickers, view.cyc)} />;
        case "compare": {
          const out = view.cmp ? runComparison(db, view.cmp.a0, view.cmp.a1, view.cmp.b0, view.cmp.b1, view.tickers) : null;
          return <DashTree node={buildCompare(clock, view.tickers, out)} />;
        }
      }
    } catch (e) {
      if (e instanceof DataUnavailableError) return <DataUnavailable what={e.what} detail={e.issues} />;
      throw e;
    }
  }
}
