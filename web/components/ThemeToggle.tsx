"use client";
/**
 * UI-01 D1 — light (default) / dark switch. The choice is stored in the
 * `semi-theme` cookie, which app/layout.tsx reads on the server, so the first
 * paint is already in the right theme (no flash). Flipping <html data-theme>
 * re-themes CSS instantly; PlotlyChart observes the attribute and redraws.
 * A toggle button: constant name "Dark theme" + aria-pressed (on = dark), so the
 * accessible name never contradicts the state. Text is visible above 650 px.
 */
import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { THEME_COOKIE, type Theme } from "@/lib/theme";

export function ThemeToggle({ initial }: { initial: Theme }) {
  const [theme, setTheme] = useState<Theme>(initial);
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="btn btn-outline-secondary btn-sm theme-toggle" aria-pressed={theme === "dark"}
      title={`Switch to the ${next} theme`}
      onClick={() => {
        const el = document.documentElement;
        el.dataset.theme = next;
        document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
        setTheme(next);
      }}>
      {theme === "dark" ? <Sun size={15} aria-hidden="true" /> : <Moon size={15} aria-hidden="true" />}
      <span className="btn-text">Dark theme</span>
    </button>
  );
}
