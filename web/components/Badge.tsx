import type { ReactNode } from "react";
import type { BadgeVariant } from "@/lib/presentation";
export function Badge({ children, variant = "neutral", as: Tag = "span" }: { children: ReactNode; variant?: BadgeVariant; as?: "span" | "summary" }) {
  return <Tag className={`badge badge-${variant}`}>{children}</Tag>;
}
