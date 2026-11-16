/**
 * ⚡ Run Crawl, server side. Calls Flask's keyed POST /api/run-crawl with
 * RELAY_API_KEY (server-only) and maps the answer to the same toast texts
 * dashboard.py's trigger_crawl() shows. Next never writes the DB: the crawl runs
 * in the Python container, under job_heartbeat's shared run lock (WEB-01c).
 */
import { getEnv } from "@/lib/env";
import { lastCrawlTime } from "@/lib/badges";
import { getDb } from "@/lib/server";

export const dynamic = "force-dynamic";

const STARTED = "Crawl started — prices & supply-chain data refreshing (~2 min). " +
  "Last Crawl timestamp will update when complete.";
const BUSY = "Crawl already in progress — please wait.";

export async function POST() {
  const env = getEnv();
  if (!env.RELAY_API_KEY) {
    return Response.json({ message: "Run Crawl is not configured on this server (RELAY_API_KEY is not set).", icon: "danger" }, { status: 503 });
  }
  let r: Response;
  try {
    r = await fetch(`${env.CLASSIC_ORIGIN}/api/run-crawl`, {
      method: "POST", cache: "no-store",
      headers: { "X-API-Key": env.RELAY_API_KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ jobs: ["market", "supply_chain"] }),
    });
  } catch (e) {
    return Response.json({ message: `Crawl service unreachable: ${(e as Error).message}`, icon: "danger" }, { status: 502 });
  }
  if (r.status === 202) return Response.json({ message: STARTED, icon: "primary", lastCrawl: lastCrawlTime(getDb()) });
  if (r.status === 409) return Response.json({ message: BUSY, icon: "warning" });
  return Response.json({ message: `Crawl request failed (HTTP ${r.status}).`, icon: "danger" }, { status: 502 });
}
