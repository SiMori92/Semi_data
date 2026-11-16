/**
 * `valuation_snapshot_data(tickers)` — newest ticker_valuation_history row per
 * ticker. Valuation figures come ONLY from here, stamped with the date they were
 * OBSERVED — never from quarterly_financials (CLAUDE.md §9 F-02).
 * Returns [] (never throws on SQL) on a DB predating the table.
 */
import { placeholders, type Db } from "./db";
import { TickerValuationRow } from "./schemas";

export function valuationSnapshot(db: Db, tickers: readonly string[]) {
  if (tickers.length === 0) return [];
  return db.all(
    `SELECT v.* FROM ticker_valuation_history v JOIN (
       SELECT ticker, MAX(snapshot_date) AS md FROM ticker_valuation_history
       WHERE ticker IN (${placeholders(tickers.length)}) GROUP BY ticker
     ) latest ON v.ticker = latest.ticker AND v.snapshot_date = latest.md
     ORDER BY v.ticker`,
    [...tickers], TickerValuationRow, "valuation_snapshot");
}
