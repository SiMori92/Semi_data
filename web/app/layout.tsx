import type { Metadata } from "next";
import { cookies } from "next/headers";
import "./tokens.css";
import "./globals.css";
import { parseTheme, THEME_COOKIE } from "@/lib/theme";

export const metadata: Metadata = { title: "Semi Industry Tracker" };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // UI-01 D1: theme chosen server-side from the cookie, so the first paint is correct.
  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);
  return (
    <html lang="en" data-theme={theme}>
      <body>{children}</body>
    </html>
  );
}
