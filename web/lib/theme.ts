/**
 * UI-01 theming (Product/docs/UI_REFRESH_PLAN.md §1.1).
 *
 * TOKENS mirrors app/tokens.css value for value (tests/theme.test.ts enforces it
 * and checks every contrast floor). UI code never uses these hex values directly:
 * it uses `var(--name)` references (lib/config.ts), which the browser resolves
 * for the current theme. Plotly cannot read CSS variables, so PlotlyChart runs
 * every figure through `resolveCssVars()` with the live computed values just
 * before drawing, and redraws when the theme flips.
 *
 * Isomorphic (no DOM, no next/headers) — safe for server and client.
 */
export type Theme = "light" | "dark";
export const THEME_COOKIE = "semi-theme";
export const parseTheme = (v: string | undefined | null): Theme => (v === "dark" ? "dark" : "light");

export const TOKEN_NAMES = [
  "bg", "surface", "surface-2", "text", "muted", "line", "grid", "blue", "blue-dark", "on-blue", "accent-soft",
  "green", "red", "amber", "orange", "green-soft", "red-soft", "amber-soft", "neutral-soft", "focus",
] as const;
export type TokenName = (typeof TOKEN_NAMES)[number];

export const TOKENS: Record<Theme, Record<TokenName, string>> = {
  light: {
    bg: "#f7f5ef", surface: "#fffefa", "surface-2": "#f2f0e9", text: "#263449", muted: "#626e79",
    line: "#dedfd9", grid: "#ecebe5", blue: "#355f87", "blue-dark": "#284a6b", "on-blue": "#ffffff",
    "accent-soft": "#eaf0ef", green: "#226850", red: "#a43939", amber: "#84621e", orange: "#9a4a12",
    "green-soft": "#eaf7f2", "red-soft": "#fff0ee", "amber-soft": "#fbf5e8", "neutral-soft": "#f0f3f7", focus: "#5c7e98",
  },
  dark: {
    bg: "#141a23", surface: "#1b2330", "surface-2": "#222c3b", text: "#e8e6df", muted: "#a3abb5",
    line: "#344052", grid: "#2a3442", blue: "#7fa6cc", "blue-dark": "#9dbbd9", "on-blue": "#10161f",
    "accent-soft": "#263347", green: "#5cbf91", red: "#ec8a8a", amber: "#d9b35c", orange: "#e8955a",
    "green-soft": "#183328", "red-soft": "#3a1f22", "amber-soft": "#352b17", "neutral-soft": "#253040", focus: "#9dbbd9",
  },
};

/** `var(--name)` — the only way UI code should name a theme colour. */
export const cssVar = (name: TokenName) => `var(--${name})`;

const VAR_RE = /var\(--([a-z0-9-]+)\)/g;

/** Deep-copy `x`, replacing every `var(--name)` inside strings via `lookup`.
 *  Unknown names are left as written (Plotly then falls back to its default)
 *  rather than guessed. Pure — unit-tested. */
export function resolveCssVars<T>(x: T, lookup: (name: string) => string | undefined): T {
  if (typeof x === "string") {
    return (x.includes("var(--") ? x.replace(VAR_RE, (m, n: string) => lookup(n)?.trim() || m) : x) as T;
  }
  if (Array.isArray(x)) return x.map((v) => resolveCssVars(v, lookup)) as T;
  if (x && typeof x === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(x as Record<string, unknown>)) out[k] = resolveCssVars(v, lookup);
    return out as T;
  }
  return x;
}

/** Lookup against a fixed theme (server-side tests, exports). */
export const themeLookup = (t: Theme) => (name: string) => (TOKENS[t] as Record<string, string>)[name];

// ── WCAG contrast (used by tests/theme.test.ts) ──────────────────────────────
export function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
