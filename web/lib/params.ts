/**
 * URL search params hold every selection so a view is linkable (constraint 10):
 *   ?tab=overview&t=NVDA,AMD&start=2025-11-09&end=2026-11-09
 * Parsed with Zod; anything invalid falls back to the Dash defaults.
 */
import { z } from "zod";
import { addDays, ymd, type Clock } from "./clock";
import { INITIAL_SELECTED } from "./config";

export const TABS = [
  { id: "overview", label: "📊 Overview" },
  { id: "financials", label: "💰 Financials" },
  { id: "sentiment", label: "🌡️ Sentiment" },
  { id: "cycles", label: "🔄 Cycles" },
  { id: "compare", label: "⚖️ Period Compare" },
  { id: "supplychain", label: "🏭 Supply Chain" },
] as const;
export type TabId = (typeof TABS)[number]["id"];

const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const Params = z.object({
  tab: z.enum(TABS.map((t) => t.id) as [TabId, ...TabId[]]).catch("overview"),
  t: z.string().max(600).optional(),
  start: date.optional().catch(undefined),
  end: date.optional().catch(undefined),
  cyc: z.string().regex(/^[A-Za-z0-9.^-]{0,15}$/).optional().catch(undefined),
  a0: date.optional().catch(undefined), a1: date.optional().catch(undefined),
  b0: date.optional().catch(undefined), b1: date.optional().catch(undefined),
});

export type View = { tab: TabId; tickers: string[]; start: string; end: string;
  /** Cycles dropdown value (update_cycle_price_chart) */ cyc?: string;
  /** Period Compare submission (run_comparison) */ cmp?: { a0: string; a1: string; b0: string; b1: string } };

export function parseView(sp: Record<string, string | string[] | undefined>, clock: Clock): View {
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k]![0] : sp[k]) as string | undefined;
  const p = Params.parse({ tab: one("tab"), t: one("t"), start: one("start"), end: one("end"), cyc: one("cyc"),
    a0: one("a0"), a1: one("a1"), b0: one("b0"), b1: one("b1") });
  const tickers = p.t === undefined
    ? [...INITIAL_SELECTED]
    : p.t.split(",").map((s) => s.trim()).filter((s) => /^[A-Za-z0-9.^-]{1,15}$/.test(s)).slice(0, 60);
  // dashboard.py: DatePickerRange defaults (now−365d … now); render_tab falls back to 2023-01-01 / today.
  return {
    tab: p.tab, tickers,
    start: p.start ?? ymd(addDays(clock.hkt, -365)),
    end: p.end ?? ymd(clock.hkt),
    cyc: p.cyc,
    cmp: p.a0 && p.a1 && p.b0 && p.b1 ? { a0: p.a0, a1: p.a1, b0: p.b0, b1: p.b1 } : undefined,
  };
}

export function viewHref(v: Partial<View> & { tab: TabId }, base: View): string {
  const m = { ...base, ...v };  // cyc / cmp are per-tab state: dropped when switching tabs
  const q = new URLSearchParams({ tab: m.tab, t: m.tickers.join(","), start: m.start, end: m.end });
  return `/?${q.toString()}`;
}
