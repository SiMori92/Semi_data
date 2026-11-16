import type { Metadata } from "next";
import "./theme.css";
import "./responsive.css";
import "./globals.css";

export const metadata: Metadata = { title: "Semi Industry Tracker" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
