"use client";
/**
 * Topbar status + actions (UI-01 Phase 2: handbook topbar; ⚡ Run crawl is the one
 * primary action, Reload / Download are secondary).
 * Navbar status cluster. Initial values are server-rendered; afterwards it polls
 * /ui-api/status every 30 s — the Dash `status-interval` — so only the chips
 * refresh, never the charts. "🔄 Reload Charts" re-runs the Server Components.
 * "⚡ Run Crawl" posts to /ui-api/run-crawl (server), which calls Flask's keyed
 * POST /api/run-crawl. Next itself still never writes the DB: the crawl runs in
 * the Python container under the shared run lock (BACKLOG WEB-01c).
 */
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition, type ReactNode } from "react";
import { z } from "zod";
import { Download, RotateCw, X, Zap } from "lucide-react";
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

export function NavStatus({ initial, extra }: { initial: StatusPayload; extra?: ReactNode }) {
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
    <div className="topbar-inner">
      <div className="topbar-status">
        <span className="topbar-crawl">
          <span className="muted">Last crawl </span>
          <span id="last-crawl-time" className="mono">{s.lastCrawl}</span>
          <span id="reload-stamp" className="reload-stamp" aria-live="polite">{stamp}</span>
        </span>
        <StatusChip id="data-freshness-badge" chip={s.freshness} />
        <StatusChip id="crawl-status-badge" chip={s.crawl} />
        <StatusChip id="ibkr-status-badge" chip={s.iv} />
      </div>
      <div className="topbar-actions">
        <button type="button" id="btn-refresh" className="btn btn-outline-secondary btn-sm"
          title="Re-read data from the database and redraw all charts" aria-label="Reload charts" disabled={pending}
          onClick={() => start(() => { router.refresh(); setStamp(`✓ Reloaded ${hktHm()} HKT`); })}>
          <RotateCw size={15} aria-hidden="true" /><span className="btn-text">Reload</span>
        </button>
        <a href="/api/export-bundle" id="btn-download-data" className="btn btn-outline-secondary btn-sm" aria-label="Download data"
          title="Download the full dataset as a .zip: multi-sheet Excel workbook (for reading) + SQLite .db snapshot (restorable backup)">
          <Download size={15} aria-hidden="true" /><span className="btn-text">Download data</span>
        </a>
        <button type="button" id="btn-run-crawl" className="btn btn-primary btn-sm"
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
          <Zap size={15} aria-hidden="true" />{crawlBusy ? "Starting…" : "Run crawl"}
        </button>
        {extra}
      </div>
      {toast ? (
        <div id="crawl-toast" role={toast.icon === "danger" ? "alert" : "status"} className={`toast toast-${toast.icon}`}>
          <div className="toast-head">
            <strong>Crawl status</strong>
            <button type="button" className="icon-button" aria-label="Close" onClick={() => setToast(null)}><X size={16} aria-hidden="true" /></button>
          </div>
          <div className="toast-body">{toast.message}</div>
        </div>
      ) : null}
    </div>
  );
}
