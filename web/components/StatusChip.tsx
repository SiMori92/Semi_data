import type { StatusChip as Chip } from "@/lib/schemas";

/** `_status_chip()` — <details>, so the detail is reachable by touch and keyboard, not only hover. */
export function StatusChip({ chip, id }: { chip: Chip; id: string }) {
  return (
    <span id={id} style={{ marginLeft: id === "data-freshness-badge" ? 20 : 10 }}>
      <details className="dashboard-status-chip">
        <summary style={{ color: chip.colour, border: `1px solid ${chip.colour}` }}>
          <span style={{ marginRight: 4 }}>{chip.icon}</span>{chip.label}
        </summary>
        <div className="dashboard-status-detail">{chip.detail}</div>
      </details>
    </span>
  );
}
