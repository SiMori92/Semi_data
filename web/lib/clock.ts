/**
 * The two clocks dashboard.py actually uses — made explicit so every port takes
 * `now` as a parameter and parity tests can freeze it.
 *
 *  - `hkt`  : config.now_hkt() — wall time in UTC+8, tz stripped. Used for range
 *             starts, HV30 cutoff, job ages, cycle windows.
 *  - `serverLocal` : pd.Timestamp.today().normalize() — the CONTAINER-LOCAL date.
 *             Used only by _freshness_report(). Railway containers run UTC, so
 *             this is the UTC date, which lags the HKT date for 8 h every day.
 *             The golden harness freezes it to UTC to model Railway.
 *             (Parity bug kept on purpose; logged as WEB-01 finding P-03.)
 *
 * Dates are carried as naive "wall" values in a UTC-based Date (getUTC* = wall
 * fields), which is how Python's naive datetimes behave.
 */
export type Clock = {
  /** naive HKT wall time, encoded as a UTC Date */
  hkt: Date;
  /** naive server-local wall time (UTC on Railway), encoded as a UTC Date */
  serverLocal: Date;
};

const HKT_OFFSET_MS = 8 * 3600_000;

export function clockFromUtc(utc: Date): Clock {
  return { hkt: new Date(utc.getTime() + HKT_OFFSET_MS), serverLocal: new Date(utc.getTime()) };
}

/** Live clock. `serverLocal` follows THIS process's TZ, exactly as
 *  pd.Timestamp.today() follows the Python process's TZ — on Railway both are
 *  UTC; on a Mac both are local. Same container ⇒ same answer. */
export function systemClock(): Clock {
  const now = new Date();
  return { hkt: new Date(now.getTime() + HKT_OFFSET_MS),
           serverLocal: new Date(now.getTime() - now.getTimezoneOffset() * 60_000) };
}

/** "YYYY-MM-DD" of a naive wall Date. */
export function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** naive datetime.isoformat(timespec="seconds"). */
export function isoSeconds(d: Date): string {
  return d.toISOString().slice(0, 19);
}

export function addDays(d: Date, days: number): Date {
  return new Date(d.getTime() + days * 86400_000);
}

/** Parse a naive ISO string (Python datetime.fromisoformat, 'Z' stripped). */
export function parseNaive(s: string): Date | null {
  const t = s.replace("Z", "").trim();
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?$/.exec(t);
  if (!m) return null;
  const [, y, mo, da, h = "0", mi = "0", se = "0", fr = "0"] = m;
  const ms = Math.floor(Number(fr.padEnd(6, "0")) / 1000);
  const d = new Date(Date.UTC(+y, +mo - 1, +da, +h, +mi, +se, ms));
  return d.getUTCMonth() === +mo - 1 && d.getUTCDate() === +da ? d : null;
}

/** pandas DateOffset(months=n) on a month-start-ish date (clamps day). */
export function addMonths(d: Date, months: number): Date {
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth() + months;
  const target = new Date(Date.UTC(y, m, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  return new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth(), Math.min(d.getUTCDate(), lastDay),
    d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds(), d.getUTCMilliseconds()));
}

/** strftime("%d %b %Y  %H:%M HKT") */
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function fmtDMonY(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCDate())} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}  ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} HKT`;
}
export function fmtYmdHm(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${ymd(d)} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} HKT`;
}
