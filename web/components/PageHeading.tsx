import type { ReactNode } from "react";
import { ArtworkHeader } from "./ArtworkHeader";

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
  visitKey,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
  visitKey: string;
}) {
  return (
    <div className="page-heading">
      <div className="page-heading-content">
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
        {action && <div className="page-heading-action">{action}</div>}
      </div>
      <ArtworkHeader visitKey={visitKey} />
    </div>
  );
}
