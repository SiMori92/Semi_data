import type { TabId } from "./params";

/** Page identity is independent of filters and data availability. */
export const PAGE_HEADINGS = {
  overview: { eyebrow: "MARKET OVERVIEW", title: "Price performance", description: "Rebased price and volume for the selected tickers over the chosen range" },
  financials: { eyebrow: "COMPANY FUNDAMENTALS", title: "Quarterly financials", description: "Reported revenue, profit and margins, with point-in-time valuation" },
  sentiment: { eyebrow: "OPTIONS & MOMENTUM", title: "Market sentiment", description: "Implied volatility, drawdowns and short-term returns" },
  cycles: { eyebrow: "PRICE CYCLES", title: "Up and down cycles", description: "Magnitude and duration of each ticker’s most recent cycle" },
  compare: { eyebrow: "PERIOD ANALYSIS", title: "Compare two periods", description: "Price return and average fundamentals, period A against period B" },
  supplychain: { eyebrow: "SUPPLY CHAIN", title: "Hardware prices and demand", description: "Enterprise GPU/CPU/memory pricing and published demand indicators" },
  health: { eyebrow: "DATA OPERATIONS", title: "Data health", description: "Status of every source, each crawl, and the charts each source feeds" },
} satisfies Record<TabId, { eyebrow: string; title: string; description: string }>;
