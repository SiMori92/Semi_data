import type { CSSProperties, ReactNode } from "react";
import { ACCENT, BG2, SUBTEXT } from "@/lib/config";

/** `_card()` */
export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="dashboard-card" style={{ background: BG2, borderRadius: 8, padding: 16, border: "1px solid #30363d", marginBottom: 12, ...style }}>
      {children}
    </div>
  );
}

/** `_section_title()` */
export function SectionTitle({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 13, fontWeight: 600, color: ACCENT, textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>{children}</div>;
}

/** `_source_footer()` — [Source: …] · [Data Last Crawled/Updated: …] */
export function SourceFooter({ source, stamp, notes }: { source: string; stamp: string; notes?: string }) {
  return (
    <div style={{ fontSize: 11, marginTop: 10, paddingTop: 8, borderTop: "1px solid #30363d", fontFamily: "monospace" }}>
      <span style={{ color: ACCENT, fontWeight: 600, marginRight: 12 }}>[Source: {source}]</span>
      <span style={{ color: SUBTEXT }}>[Data Last Crawled/Updated: {stamp}]</span>
      {notes ? <span style={{ color: SUBTEXT }}>{`  ·  ${notes}`}</span> : null}
    </div>
  );
}

/** Explicit "data unavailable" state — a Zod parse failure is never coerced or silently dropped. */
export function DataUnavailable({ what, detail }: { what: string; detail?: string }) {
  return (
    <Card style={{ borderColor: "#d29922" }}>
      <SectionTitle>⚠️ Data unavailable</SectionTitle>
      <p style={{ color: "#d29922", margin: 0 }}>{what}: the stored rows did not match the expected schema, so nothing is shown rather than a guess.</p>
      {detail ? <pre style={{ color: SUBTEXT, fontSize: 11, whiteSpace: "pre-wrap", marginTop: 8 }}>{detail}</pre> : null}
    </Card>
  );
}
