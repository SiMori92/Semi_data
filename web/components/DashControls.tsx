"use client";
/** The two dashboard callbacks, as URL updates (so views stay linkable):
 *   update_cycle_price_chart → ?cyc=TICKER
 *   run_comparison           → ?a0&a1&b0&b1 (Compare button) */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type CSSProperties } from "react";

function useParamPush() {
  const router = useRouter(), path = usePathname(), sp = useSearchParams();
  return (patch: Record<string, string>) => {
    const q = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) q.set(k, v);
    router.replace(`${path}?${q.toString()}`, { scroll: false });
  };
}

export function CycleSelect({ options, value, style }: { options: string[]; value: string; style?: CSSProperties }) {
  const push = useParamPush();
  return (
    <select aria-label="Cycle chart ticker" id="cycles-ticker-select" className="cycle-ticker-select form-select form-select-sm" value={value} style={style}
      onChange={(e) => push({ cyc: e.target.value })}>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

export function ComparePicker({ a, b }: { a: { start_date: string; end_date: string }; b: { start_date: string; end_date: string } }) {
  const sp = useSearchParams();
  const push = useParamPush();
  const [v, setV] = useState({ a0: sp.get("a0") ?? a.start_date, a1: sp.get("a1") ?? a.end_date, b0: sp.get("b0") ?? b.start_date, b1: sp.get("b1") ?? b.end_date });
  const inp = (k: keyof typeof v, label: string) => (
    <input type="date" aria-label={label} value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
  );
  return (
    <div className="row semi-compare">
      <div className="col-5"><label style={{ color: "var(--muted)", fontSize: 12 }}>Period A</label><div className="semi-daterange">{inp("a0", "Period A start")}{inp("a1", "Period A end")}</div></div>
      <div className="col-5"><label style={{ color: "var(--muted)", fontSize: 12 }}>Period B</label><div className="semi-daterange">{inp("b0", "Period B start")}{inp("b1", "Period B end")}</div></div>
      <div className="col-2"><div style={{ height: 20 }} /><button id="btn-compare" className="btn btn-primary" style={{ marginTop: 4 }} onClick={() => push(v)}>Compare →</button></div>
    </div>
  );
}
