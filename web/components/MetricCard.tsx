import type { ReactNode } from "react";
export type MetricCardProps = { label: string; value: string; note: ReactNode; colour?: string; noteColour?: string };
export function MetricCard({ label, value, note, colour, noteColour }: MetricCardProps) {
  return <div className="metric-card panel">
    <div className="metric-label">{label}</div>
    <div className="metric-value" style={{ color: colour, fontSize: `clamp(12px, ${160 / Math.max(value.length, 1)}cqw, 32px)` }}>{value}</div>
    <div className="metric-note" style={{ color: noteColour }}>{note}</div>
  </div>;
}
