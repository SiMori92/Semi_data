import type { CSSProperties, ReactNode } from "react";
import { SUBTEXT } from "@/lib/config";

/** `_card()` */
export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="dashboard-card panel" style={style}>
      {children}
    </div>
  );
}

/** `_section_title()` */
export function SectionTitle({ children }: { children: ReactNode }) {
  return <div className="section-title">{children}</div>;
}

/** `_source_footer()` — [Source: …] · [Data Last Crawled/Updated: …] */
export function SourceFooter({ source, stamp, notes }: { source: string; stamp: string; notes?: string }) {
  return (
    <div className="source-footer">
      <span style={{ marginRight: 12 }}>[Source: {source}]</span>
      <span style={{ color: SUBTEXT }}>[Data Last Crawled/Updated: {stamp}]</span>
      {notes ? <span style={{ color: SUBTEXT }}>{`  ·  ${notes}`}</span> : null}
    </div>
  );
}

/** Explicit "data unavailable" state — a Zod parse failure is never coerced or silently dropped. */
export function DataUnavailable({ what, detail }: { what: string; detail?: string }) {
  return (
    <div className="alert error" role="alert">
      <SectionTitle>⚠️ Data unavailable</SectionTitle>
      <p style={{ margin: 0 }}>{what}: the stored rows did not match the expected schema, so nothing is shown rather than a guess.</p>
      {detail ? <pre style={{ color: SUBTEXT, fontSize: 12, whiteSpace: "pre-wrap", marginTop: 8 }}>{detail}</pre> : null}
    </div>
  );
}
