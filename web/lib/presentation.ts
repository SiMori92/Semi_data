/** Presentation only: preserve every stored status label and its meaning. */
export type BadgeVariant = "fresh" | "stale" | "empty" | "missing" | "ok" | "no-data" | "error" | "abandoned" | "derived" | "published" | "pending" | "neutral";
export function statusVariant(text: string): BadgeVariant {
  if (text.includes("🔴")) return /EMPTY/.test(text) ? "empty" : /STALE/.test(text) ? "stale" : "error";
  if (text.includes("🟡")) return /NO DATA/.test(text) ? "no-data" : "pending";
  if (text.includes("🟠") || /ABANDONED/.test(text)) return "abandoned";
  if (text.includes("🟢")) return "ok";
  if (text.includes("⚪") && !/MISSING/.test(text)) return "neutral";
  if (/MISSING|NOT RECORDED|NEVER RUN/.test(text)) return "missing";
  if (/NO DATA/.test(text)) return "no-data";
  if (/FAILED|ERROR/.test(text)) return "error";
  if (/RUNNING/.test(text)) return "pending";
  if (/^(IBKR|DVOL)$/.test(text)) return "published";
  if (/^(IV30\*|IV|HV30)$/.test(text)) return "derived";
  return "neutral";
}
