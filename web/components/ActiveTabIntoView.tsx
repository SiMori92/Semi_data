"use client";
/** On narrow screens the tab strip scrolls horizontally (responsive.css); keep the
 *  active tab visible, as Dash's tab strip does. */
import { useEffect } from "react";
export function ActiveTabIntoView({ tab }: { tab: string }) {
  useEffect(() => {
    document.querySelector(".dashboard-tabs .nav-link.active")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab]);
  return null;
}
