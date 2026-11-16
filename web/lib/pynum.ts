/**
 * Bit-faithful ports of the numpy / pandas / Python-formatting primitives the
 * dashboard's numbers pass through. Parity lives or dies here: a naive
 * `arr.reduce((a, b) => a + b)` differs from numpy's pairwise sum in the last
 * ulp, and `Number.toFixed` breaks exact ties differently from Python's `format`.
 *
 * Every function names the Python expression it reproduces.
 */

/** numpy `np.add.reduce` on a contiguous float64 array (pairwise_sum, PW_BLOCKSIZE=128).
 *  Verified bit-exact against np.sum on 3,000 random arrays (WEB-01 log). */
export function npSum(a: readonly number[], lo = 0, hi = a.length): number {
  const n = hi - lo;
  if (n < 8) {
    let r = 0;
    for (let i = lo; i < hi; i++) r += a[i];
    return r;
  }
  if (n <= 128) {
    const r = [a[lo], a[lo + 1], a[lo + 2], a[lo + 3], a[lo + 4], a[lo + 5], a[lo + 6], a[lo + 7]];
    let i = 8;
    for (; i < n - (n % 8); i += 8) {
      for (let j = 0; j < 8; j++) r[j] += a[lo + i + j];
    }
    let res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
    for (; i < n; i++) res += a[lo + i];
    return res;
  }
  let n2 = Math.floor(n / 2);
  n2 -= n2 % 8;
  return npSum(a, lo, lo + n2) + npSum(a, lo + n2, hi);
}

/** pandas `Series.std()` (nanops.nanvar, skipna, ddof=1, no bottleneck) → sqrt.
 *  Input must already be NaN-free (callers dropna first, as the Python does). */
export function pdStd(values: readonly number[], ddof = 1): number {
  const count = values.length;
  const d = count - ddof;
  if (count === 0 || d <= 0) return NaN;
  const avg = npSum(values) / count;
  const sqr = values.map((v) => (avg - v) ** 2);
  return Math.sqrt(npSum(sqr) / d);
}

/** numpy `rint` — round half to even. */
export function rint(x: number): number {
  if (!Number.isFinite(x)) return x;
  const f = Math.floor(x);
  const diff = x - f;
  if (diff < 0.5) return f === 0 && x < 0 ? -0 : f;
  if (diff > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

/** `np.round(x, decimals)` / `round(np.float64(x), d)` / `DataFrame.round(d)`.
 *  numpy multiplies, rints, divides — NOT Python's correctly-rounded `round(float)`. */
export function npRound(x: number, decimals: number): number {
  if (!Number.isFinite(x)) return x;
  if (decimals === 0) return rint(x);
  const p = 10 ** decimals;
  const y = rint(x * p) / p;
  return y === 0 && (x < 0 || Object.is(x, -0)) ? -0 : y;
}

/** Python `round(float, d)` on a plain Python float: correctly rounded on the
 *  exact binary value, ties to even. */
export function pyRound(x: number, d: number): number {
  return Number(pyFixed(x, d));
}

/** Exact decimal expansion of a double (finite). */
function exactDecimal(x: number): { neg: boolean; int: string; frac: string } {
  const neg = x < 0 || Object.is(x, -0);
  const s = Math.abs(x).toFixed(100).replace(/0+$/, ""); // V8 toFixed(≤100) is exact
  const [int, frac = ""] = s.split(".");
  return { neg, int, frac };
}

/** Python `format(x, f".{d}f")` — rounds the EXACT binary value, ties to even. */
export function pyFixed(x: number, d: number): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  const { neg, int, frac } = exactDecimal(x);
  const digits = (int + frac.padEnd(d + 1, "0")).split("").map(Number);
  const cut = int.length + d; // index of first dropped digit
  const rest = frac.slice(d);
  let roundUp = false;
  if (rest.length > 0) {
    const first = Number(rest[0]);
    const tail = rest.slice(1).replace(/0+$/, "");
    if (first > 5 || (first === 5 && tail.length > 0)) roundUp = true;
    else if (first === 5) roundUp = cut > 0 ? digits[cut - 1] % 2 === 1 : false;
  }
  let kept = digits.slice(0, cut);
  if (roundUp) {
    let i = kept.length - 1;
    while (i >= 0) {
      if (kept[i] === 9) { kept[i] = 0; i--; } else { kept[i]++; break; }
    }
    if (i < 0) kept = [1, ...kept];
  }
  const intLen = kept.length - d;
  const ip = kept.slice(0, intLen).join("").replace(/^0+(?=\d)/, "") || "0";
  const fp = kept.slice(intLen).join("");
  const body = d > 0 ? `${ip}.${fp}` : ip;
  return neg ? `-${body}` : body;
}

/** Python `f"{x:+.{d}f}"`. */
export function pySignedFixed(x: number, d: number): string {
  const s = pyFixed(x, d);
  return s.startsWith("-") || s === "nan" ? s : `+${s}`;
}

/** Python `f"{x:,.{d}f}"` — thousands separators. */
export function pyGrouped(x: number, d: number): string {
  const s = pyFixed(x, d);
  const neg = s.startsWith("-");
  const [ip, fp] = (neg ? s.slice(1) : s).split(".");
  const g = ip.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (neg ? "-" : "") + g + (fp !== undefined ? `.${fp}` : "");
}

/** Python `repr(float)` / `str(float)` — shortest round-trip, Python spelling. */
export function pyFloatStr(x: number): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  if (Object.is(x, -0)) return "-0.0";
  const abs = Math.abs(x);
  if (abs !== 0 && (abs >= 1e16 || abs < 1e-4)) {
    // Python: 1e+16, 1.5e-05
    const [m, e] = x.toExponential().split("e");
    const ei = Number(e);
    return `${m}e${ei < 0 ? "-" : "+"}${String(Math.abs(ei)).padStart(2, "0")}`;
  }
  const s = String(x);
  return s.includes(".") || s.includes("e") ? s : `${s}.0`;
}

/** Python `format(x, "g")` and `"+g"` (6 significant digits, trailing zeros stripped). */
export function pyG(x: number, sign = false): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return (x > 0 ? (sign ? "+" : "") : "-") + "inf";
  const P = 6;
  let out: string;
  if (x === 0) {
    out = Object.is(x, -0) ? "-0" : "0";
  } else {
    // exponent after rounding to P significant digits
    const [m, e] = Number(x).toExponential(P - 1).split("e");
    const exp = Number(e);
    if (exp < -4 || exp >= P) {
      const mm = m.includes(".") ? m.replace(/0+$/, "").replace(/\.$/, "") : m;
      out = `${mm}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
    } else {
      const f = pyFixed(x, Math.max(0, P - 1 - exp));
      out = f.includes(".") ? f.replace(/0+$/, "").replace(/\.$/, "") : f;
    }
  }
  if (sign && !out.startsWith("-")) out = `+${out}`;
  return out;
}

/** Python `f"{x:.0%}"`. */
export function pyPercent0(x: number): string {
  return `${pyFixed(x * 100, 0)}%`;
}

/** Python `int(x)` truncation toward zero. */
export function pyInt(x: number): number {
  return Math.trunc(x);
}
