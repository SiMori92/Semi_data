"use client";
/**
 * Navbar status cluster. Initial values are server-rendered; afterwards it polls
 * /ui-api/status every 30 s — the Dash `status-interval` — so only the chips
 * refresh, never the charts. "🔄 Reload Charts" re-runs the Server Components.
 * "⚡ Run Crawl" posts to /ui-api/run-crawl (server), which calls Flask's keyed
 * POST /api/run-crawl. Next itself still never writes the DB: the crawl runs in
 * the Python container under the shared run lock (BACKLOG WEB-01c).
 */
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { z } from "zod";
import { StatusChip } from "./StatusChip";
import { StatusChip as ChipSchema } from "@/lib/schemas";

export const StatusPayload = z.object({
  lastCrawl: z.string(),
  freshness: ChipSchema, crawl: ChipSchema, iv: ChipSchema,
});
export type StatusPayload = z.infer<typeof StatusPayload>;

const hktHm = () => {
  const d = new Date(Date.now() + 8 * 3600_000);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};

/** Response of /ui-api/run-crawl — mirrors trigger_crawl()'s toast outputs. */
export const CrawlResult = z.object({
  message: z.string(), icon: z.enum(["primary", "warning", "danger"]), lastCrawl: z.string().optional(),
});
type CrawlResult = z.infer<typeof CrawlResult>;

export function NavStatus({ initial }: { initial: StatusPayload }) {
  const [s, setS] = useState(initial);
  const [toast, setToast] = useState<CrawlResult | null>(null);
  const [crawlBusy, setCrawlBusy] = useState(false);
  const [stamp, setStamp] = useState("");
  const [pending, start] = useTransition();
  const router = useRouter();

  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const r = await fetch("/ui-api/status", { cache: "no-store" });
        const parsed = StatusPayload.safeParse(await r.json());
        if (parsed.success) setS(parsed.data);
        else console.error("[status] schema mismatch", parsed.error.message);
      } catch (e) { console.warn("[status] poll failed", e); }
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="dashboard-navbar-right">
      <div className="dashboard-status">
        <span style={{ color: "#8b949e", fontSize: 12 }}>Last crawl: </span>
        <span id="last-crawl-time" style={{ color: "#58a6ff", fontSize: 12 }}>{s.lastCrawl}</span>
        <span id="reload-stamp" style={{ color: "#3fb950", fontSize: 11, marginLeft: 12, opacity: 0.8 }}>{stamp}</span>
        <StatusChip id="data-freshness-badge" chip={s.freshness} />
        <StatusChip id="crawl-status-badge" chip={s.crawl} />
        <StatusChip id="ibkr-status-badge" chip={s.iv} />
      </div>
      <div className="dashboard-actions">
        <button id="btn-refresh" className="btn btn-primary btn-sm" style={{ marginLeft: 16, fontSize: 12 }}
          title="Re-read data from the database and redraw all charts" disabled={pending}
          onClick={() => start(() => { router.refresh(); setStamp(`✓ Reloaded ${hktHm()} HKT`); })}>
          🔄 Reload Charts
        </button>
        <button id="btn-run-crawl" className="btn btn-warning btn-sm" style={{ marginLeft: 8, fontSize: 12 }}
          title="Fetch fresh market data from Yahoo Finance (takes ~2 min)" disabled={crawlBusy}
          onClick={async () => {
            setCrawlBusy(true);
            try {
              const r = await fetch("/ui-api/run-crawl", { method: "POST" });
              const parsed = CrawlResult.safeParse(await r.json());
              if (!parsed.success) throw new Error(parsed.error.message);
              setToast(parsed.data);
              if (parsed.data.lastCrawl) setS((cur) => ({ ...cur, lastCrawl: parsed.data.lastCrawl! }));
            } catch (e) {
              setToast({ message: `Could not start the crawl: ${(e as Error).message}`, icon: "danger" });
            } finally { setCrawlBusy(false); }
          }}>
          ⚡ Run Crawl
        </button>
        <a href="/api/export-bundle" role="button" id="btn-download-data" className="btn btn-success btn-sm"
          style={{ marginLeft: 8, fontSize: 12 }}
          title="Download the full dataset as a .zip: multi-sheet Excel workbook (for reading) + SQLite .db snapshot (restorable backup)">
          ⬇️ Download Data
        </a>
      </div>
      {toast ? (
        <div id="crawl-toast" role="alert" className="toast show dashboard-toast fade"
          style={{ position: "fixed", top: 66, right: 16, width: 320, zIndex: 9999 }}>
          <div className="toast-header">
            <svg className={`rounded me-2 text-${toast.icon}`} width="20" height="20" focusable="false" role="img"><rect fill="currentColor" width="100%" height="100%" /></svg>
            <strong className="me-auto">Crawl Status</strong>
            <button type="button" className="btn-close" aria-label="Close" onClick={() => setToast(null)} />
          </div>
          <div className="toast-body">{toast.message}</div>
        </div>
      ) : null}
    </div>
  );
}
