/**
 * Evergreen dates for the bundled synthetic snapshot.
 *
 * Port of the BFF's app/evergreen.py — keep the two in step. The snapshot is
 * generated once, dated BASE; at load time every date in it is moved forward by
 * the whole number of weeks between BASE and today (UTC), so days-to-maturity,
 * ages and weekdays are unchanged and only the calendar moves. The BFF and the
 * Fabric IQ tables use the same rule, so all three agree on the as-of date.
 */

const BASE_DATE = new Date(Date.UTC(2026, 7, 3));
const BASE = BASE_DATE.getTime();
const BASE_YEAR = BASE_DATE.getUTCFullYear();
const BASE_MONTH = BASE_DATE.getUTCMonth();
const DAY = 86_400_000;

const FULL = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
const ABBR = FULL.map((m) => m.slice(0, 3));
const MON = [...FULL, "Sept", ...ABBR].join("|");
const LONE = FULL.filter((m) => m !== "May").join("|");
const IDX: Record<string, number> = { Sept: 9 };
FULL.forEach((m, i) => { IDX[m] = i + 1; IDX[m.slice(0, 3)] = i + 1; });

const RX = new RegExp(
  String.raw`(?<iso>(?<![\w-])(?<y>(?:19|20)\d\d)-(?<m>0[1-9]|1[0-2])-(?<d>[0-3]\d)(?=T\d|(?![\w-])))`
  + String.raw`|(?<ym>(?<![\w-])(?<ymy>(?:19|20)\d\d)-(?<ymm>0[1-9]|1[0-2])(?![\w-]))`
  + String.raw`|(?<dm>\b(?<dmd>[0-3]?\d)(?<dms>st|nd|rd|th)? (?<dmm>${MON})\b(?<dmy>,? (?:19|20)\d\d\b)?)`
  + String.raw`|(?<md>\b(?<mdm>${MON})(?<mdp>\.?) (?<mdd>[0-3]?\d)(?<mds>st|nd|rd|th)?\b(?<mdy>,? (?:19|20)\d\d\b)?)`
  + String.raw`|(?<my>\b(?<mym>${MON}) (?<myy>(?:19|20)\d\d)\b)`
  + String.raw`|(?<mo>\b(?<mon>${LONE})\b)`,
  "g",
);

export function offsetDays(now: Date = new Date()): number {
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.max(0, Math.floor((today - BASE) / DAY / 7) * 7);
}

const utc = (y: number, m: number, d: number): Date | null => {
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCMonth() === m - 1 && t.getUTCDate() === d ? t : null;
};
const plus = (t: Date, days: number) => new Date(t.getTime() + days * DAY);
const iso = (t: Date) => t.toISOString().slice(0, 10);
const pad = (n: number) => String(n).padStart(2, "0");

function monthsFor(days: number): number {
  const a = plus(BASE_DATE, days);
  return (a.getUTCFullYear() * 12 + a.getUTCMonth()) - (BASE_YEAR * 12 + BASE_MONTH);
}

function addMonths(y: number, m: number, n: number): [number, number] {
  const k = y * 12 + (m - 1) + n;
  return [Math.floor(k / 12), (k % 12) + 1];
}

function nameFor(orig: string, month: number): string {
  if (FULL.includes(orig)) return FULL[month - 1];
  if (orig === "Sept" && month === 9) return "Sept";
  return ABBR[month - 1];
}

function ordinal(n: number): string {
  if (n % 100 >= 10 && n % 100 <= 20) return "th";
  return ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
}

/** The explicit year, or the one that puts a bare "14 August" nearest BASE. */
function yearOf(month: number, day: number, yearText: string | undefined): number | null {
  if (yearText) return Number(yearText.replace(/\D/g, ""));
  let best: [number, number] | null = null;
  for (const y of [BASE_YEAR - 1, BASE_YEAR, BASE_YEAR + 1]) {
    const t = utc(y, month, day);
    if (!t) continue;
    const gap = Math.abs(t.getTime() - BASE);
    if (!best || gap < best[0]) best = [gap, y];
  }
  return best ? best[1] : null;
}

export function shiftText(text: string, days: number = offsetDays()): string {
  if (!days || !text) return text;
  const months = monthsFor(days);
  return text.replace(RX, (whole, ...args) => {
    const g = args[args.length - 1] as Record<string, string | undefined>;
    if (g.iso) {
      const t = utc(+g.y!, +g.m!, +g.d!);
      return t ? iso(plus(t, days)) : whole;
    }
    if (g.ym) {
      const [y, m] = addMonths(+g.ymy!, +g.ymm!, months);
      return `${y}-${pad(m)}`;
    }
    if (g.dm || g.md) {
      const k = g.dm ? "dm" : "md";
      const monTxt = g[`${k}m`]!, dayTxt = g[`${k}d`]!, suf = g[`${k}s`], yr = g[`${k}y`];
      const month = IDX[monTxt];
      const year = yearOf(month, +dayTxt, yr);
      const t = year === null ? null : utc(year, month, +dayTxt);
      if (!t) return whole;
      const s = plus(t, days);
      const d = s.getUTCDate(), name = nameFor(monTxt, s.getUTCMonth() + 1);
      const sfx = suf ? ordinal(d) : "";
      const ytxt = yr ? `${yr.slice(0, -4)}${s.getUTCFullYear()}` : "";
      return k === "dm" ? `${d}${sfx} ${name}${ytxt}` : `${name}${g.mdp ?? ""} ${d}${sfx}${ytxt}`;
    }
    if (g.my) {
      const [y, m] = addMonths(+g.myy!, IDX[g.mym!], months);
      return `${nameFor(g.mym!, m)} ${y}`;
    }
    if (g.mo) {
      const [, m] = addMonths(BASE_YEAR, IDX[g.mon!], months);
      return FULL[m - 1];
    }
    return whole;
  });
}

/** A shifted deep copy of a JSON-like value. */
export function evergreen<T>(value: T, days: number = offsetDays()): T {
  if (!days) return value;
  const walk = (v: unknown): unknown => {
    if (typeof v === "string") return shiftText(v, days);
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === "object") {
      return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)]));
    }
    return v;
  };
  return walk(value) as T;
}
