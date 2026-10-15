/** Shapes returned by the BFF `/api/books/{book}/*` endpoints (pb_books.py). SYNTHETIC demo data. */

export type BookId = "banking" | "borrowing" | "investing" | "newcomers" | "insurance" | "security";
export type PlayType = "Support" | "Protect" | "Retain" | "Grow";
export type Verdict = "pass" | "needs_approval" | "blocked";
export type CheckStatus = "pass" | "warn" | "block";
export type Format = "number" | "cad" | "pct" | "text";
export type Num = number | string;

export interface Kpi { id: string; label: string; value: Num; format: Format; hint: string; source: string }
export interface ChartDatum { label: string; value: number }
export interface Chart { id: string; title: string; kind: "bars" | "hbars" | "stack"; source: string; data: ChartDatum[] }
export interface PlaySummary { play: string; play_type: PlayType; eligible: number; blocked: number; policy: string; explain: string }

export interface BookOverview {
  book: BookId;
  title: string;
  tagline: string;
  as_of: string;
  kpis: Kpi[];
  charts: Chart[];
  plays: PlaySummary[];
  iq: { fabric: string[]; foundry: string[]; work_prompt: string; web_prompt: string };
}

export interface Play {
  rank: number;
  play_type: PlayType;
  play: string;
  recommendation?: string;
  recommended_product?: string;
  rationale: string;
  /** "Eligible", or the reason it is blocked - displayed as-is. */
  eligibility: string;
  value_at_stake_cad: Num;
  policy: string;
  purpose?: string;
}

export interface Column { key: string; label: string; format: Format }

export interface BookRow {
  account_id: string;
  customer_id: string;
  customer_name: string;
  segment: string;
  branch: string;
  product: string;
  wellness_band: string;
  email_consent: string;
  linked_mortgage: "Y" | "N";
  linked_cards: "Y" | "N";
  flags: string[];
  values: Record<string, Num>;
  top_play: Play | null;
  plays: number;
}

export interface Section { title: string; source: string; items: { label: string; value: Num; format: Format }[] }
export interface Series { title: string; source: string; months: string[]; lines: { label: string; values: number[] }[] }

export interface BookAccountDetail extends Omit<BookRow, "plays"> {
  sections: Section[];
  series: Series;
  plays: Play[];
  prompts: { label: string; prompt: string }[];
}

export interface Check { rule: string; name: string; status: CheckStatus; detail: string }

export interface BookDraft {
  account_id: string;
  play: Play;
  channel: string;
  purpose: "Service" | "Marketing";
  subject: string;
  body: string;
  checks: Check[];
  verdict: Verdict;
}

/** Per-book copy that is UI framing only - every number comes from the BFF. */
export const BOOK_META: Record<BookId, { title: string; headline: string; aiName: string; noun: string }> = {
  banking: {
    title: "Everyday banking", aiName: "Banking AI", noun: "everyday banking relationships",
    headline: "Who is moving their money, and who is paying for the wrong package?",
  },
  borrowing: {
    title: "Borrowing", aiName: "Borrowing AI", noun: "credit facilities",
    headline: "Who is paying too much for credit, and who should not get more?",
  },
  investing: {
    title: "Investing", aiName: "Investing AI", noun: "investing clients",
    headline: "Whose money is waiting, and what is suitable?",
  },
  newcomers: {
    title: "Newcomers & transfers", aiName: "Newcomers AI", noun: "newcomer clients",
    headline: "Who is building a life here, and who is paying too much to send money home?",
  },
  insurance: {
    title: "Insurance", aiName: "Insurance AI", noun: "insured clients",
    headline: "Who is under-protected, and who is paying for cover they may not need?",
  },
  security: {
    title: "Security & fraud", aiName: "Security AI", noun: "clients with security signals",
    headline: "Who needs protecting right now - before any other conversation?",
  },
};

export const TYPE_ORDER: Record<string, number> = { Support: 0, Protect: 1, Retain: 2, Grow: 3 };

export const num = (v: Num | undefined | null): number => {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return Number.isFinite(n) ? n : 0;
};

/** CAD with thousands separators; cents only when the value has them and is small (package fees, payments). */
export const cad = (v: Num, digits?: number): string => {
  const n = num(v);
  const d = digits ?? (Math.abs(n) < 1000 && Math.round(n * 100) % 100 !== 0 ? 2 : 0);
  return n.toLocaleString("en-CA", { style: "currency", currency: "CAD", currencyDisplay: "narrowSymbol", maximumFractionDigits: d, minimumFractionDigits: d });
};

/** Compact money for chart labels ($2.18M, $57.7K). */
export const cadShort = (v: Num): string => {
  const n = num(v), a = Math.abs(n);
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `$${(n / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K`;
  return cad(n, 0);
};

export const fmt = (v: Num | null | undefined, f: Format): string => {
  if (v === null || v === undefined || v === "") return "—";
  switch (f) {
    case "cad": return cad(v);
    case "pct": return `${num(v).toLocaleString("en-CA", { maximumFractionDigits: 2 })}%`;
    case "number": return typeof v === "number" || /^-?\d+(\.\d+)?$/.test(String(v)) ? num(v).toLocaleString("en-CA", { maximumFractionDigits: 1 }) : String(v);
    default: return String(v);
  }
};

/** KPI tiles: full CAD below a million, compact above. */
export const fmtKpi = (v: Num, f: Format): string => (f === "cad" && Math.abs(num(v)) >= 1e6 ? cadShort(v) : fmt(v, f));

export const isEligible = (e: string) => e.trim().toLowerCase() === "eligible";

export const playKey = (p: { play: string; play_type: string }) => `${p.play_type}|${p.play}`;

export const monthLabel = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return y ? new Date(y, m - 1, 15).toLocaleDateString("en-CA", { month: "short" }).replace(".", "") : ym;
};

export const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export const supportBand = (band: string) => band === "Vulnerable" || band === "Stretched";

/* ------------------------------------------------------------ IQ layers */
export type IQLayer = "work" | "fabric" | "foundry" | "web";
export const IQ_NAME: Record<IQLayer, string> = { fabric: "Fabric IQ", foundry: "Foundry IQ", web: "Web IQ", work: "Work IQ" };
export const isIQLayer = (v: unknown): v is IQLayer => typeof v === "string" && v in IQ_NAME;
