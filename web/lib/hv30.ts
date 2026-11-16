/**
 * `_compute_hv30(tickers)` — 30-day historical volatility, annualised %.
 *
 * Faithful to the Python, including two things worth knowing (findings P-01/P-02):
 *  - the code says "log_ret" but computes SIMPLE returns (`pct_change()`);
 *  - pct_change follows pandas 3 (fill_method=None): a NULL close makes the two
 *    adjacent returns NaN and they are dropped. pandas 2.x padded instead. Prod's
 *    pandas is unpinned (requirements.txt `pandas>=2.0.0`), so the deployed
 *    result for a series with a NULL close depends on the build date.
 * std is pandas' (ddof=1, numpy pairwise sums); rounding is np.round (rint).
 */
import { addDays, ymd, type Clock } from "./clock";
import { placeholders, type Db } from "./db";
import { npRound, pdStd } from "./pynum";
import { TickerDateCloseRow } from "./schemas";

export type Hv30 = { ticker: string; hv30: number | null };

const SQRT_252 = 252 ** 0.5; // Python (252 ** 0.5)

export function computeHv30(db: Db, clock: Clock, tickers: readonly string[]): Hv30[] {
  if (tickers.length === 0) return [];
  const cutoff = ymd(addDays(clock.hkt, -75));
  const rows = db.all(
    `SELECT ticker, date, close FROM daily_prices WHERE ticker IN (${placeholders(tickers.length)}) AND date >= ? ORDER BY ticker, date`,
    [...tickers, cutoff], TickerDateCloseRow, "hv30");
  const groups = new Map<string, number[]>();
  for (const r of rows) {
    if (!groups.has(r.ticker)) groups.set(r.ticker, []);
    groups.get(r.ticker)!.push(r.close === null ? NaN : r.close);
  }
  const out: Hv30[] = [];
  for (const t of [...groups.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))) {
    const closes = groups.get(t)!;
    if (closes.length < 10) { out.push({ ticker: t, hv30: null }); continue; }
    out.push({ ticker: t, hv30: hv30FromCloses(closes) });
  }
  return out;
}

/** The numeric core, exported for edge-case tests. */
export function hv30FromCloses(closes: readonly number[]): number | null {
  const ret: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const r = closes[i] / closes[i - 1] - 1;
    if (!Number.isNaN(r)) ret.push(r);
  }
  const tail = ret.slice(-30);
  const hv = pdStd(tail) * SQRT_252 * 100;
  return Number.isNaN(hv) ? null : npRound(hv, 1);
}
