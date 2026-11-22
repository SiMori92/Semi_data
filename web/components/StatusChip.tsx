import { Badge } from "./Badge";
import { statusVariant } from "@/lib/presentation";
import type { StatusChip as Chip } from "@/lib/schemas";

/** `_status_chip()` — <details>, so the detail is reachable by touch and keyboard, not only hover. */
export function StatusChip({ chip, id }: { chip: Chip; id: string }) {
  return (
    <span id={id} className="status-chip-wrap">
      <details className="dashboard-status-chip">
        <Badge as="summary" variant={statusVariant(chip.icon + " " + chip.label)}>
          <span style={{ marginRight: 4 }}>{chip.icon}</span>{chip.label}
        </Badge>
        <div className="dashboard-status-detail">{chip.detail}</div>
      </details>
    </span>
  );
}
