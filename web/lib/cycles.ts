/**
 * Cycle detection — scipy.signal.argrelextrema(data, np.greater_equal|np.less_equal,
 * order=_CYCLE_WINDOW, mode="clip").
 *
 * scipy's _boolrelextrema compares each point with its neighbours at distances
 * 1..order on both sides, CLIPPING indices at the array ends — so an endpoint is
 * compared with itself and `>=` is true there. That is why plateaus and series
 * ends produce runs of adjacent "peaks"; it is scipy's behaviour, kept exactly.
 * NaN compares false, so a NaN is never an extremum and blocks its neighbours.
 */
export const CYCLE_WINDOW = 15;

type Cmp = (a: number, b: number) => boolean;
export const greaterEqual: Cmp = (a, b) => a >= b;
export const lessEqual: Cmp = (a, b) => a <= b;

export function argrelextrema(data: readonly number[], cmp: Cmp, order = 1): number[] {
  if (!Number.isInteger(order) || order < 1) throw new Error("order must be an int >= 1");
  const n = data.length;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    let ok = true;
    for (let s = 1; s <= order && ok; s++) {
      const plus = data[Math.min(i + s, n - 1)];
      const minus = data[Math.max(i - s, 0)];
      ok = cmp(data[i], plus) && cmp(data[i], minus);
    }
    if (ok) out.push(i);
  }
  return out;
}

export function detectCycles(closes: readonly number[], order = CYCLE_WINDOW) {
  return { peaks: argrelextrema(closes, greaterEqual, order), troughs: argrelextrema(closes, lessEqual, order) };
}
