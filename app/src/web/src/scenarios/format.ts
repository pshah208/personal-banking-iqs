const MINUS = "−";

/** CAD with thousands separators, no cents; `sign` forces a leading +/−. */
export function cad(v: number, sign = false): string {
  const n = Math.round(v);
  const body = `$${Math.abs(n).toLocaleString("en-CA")}`;
  if (n < 0) return `${MINUS}${body}`;
  return sign ? `${n > 0 ? "+" : "±"}${body}` : body;
}

/** Compact CAD for large balances: $26.4M, $415K. */
export function cadShort(v: number, sign = false): string {
  const a = Math.abs(v);
  const body = a >= 1e6 ? `$${(a / 1e6).toFixed(1)}M` : a >= 1e4 ? `$${Math.round(a / 1e3)}K` : `$${Math.round(a).toLocaleString("en-CA")}`;
  if (v < 0 && Math.round(a) !== 0) return `${MINUS}${body}`;
  return sign ? `${v > 0 ? "+" : "±"}${body}` : body;
}

export function signed(v: number, dp = 1): string {
  return `${v > 0 ? "+" : v < 0 ? MINUS : "±"}${Math.abs(v).toFixed(dp)}`;
}

export const tone = (v: number, eps = 0.0005) => (v > eps ? "up" : v < -eps ? "down" : "flat");

/** TDS pill tone: above the TDS guideline is bad, inside the GDS-TDS corridor is a warning. */
export const tdsTone = (tds: number, gdsLimit = 39, tdsLimit = 44) =>
  tds > tdsLimit ? "bad" : tds >= gdsLimit ? "warn" : "ok";
