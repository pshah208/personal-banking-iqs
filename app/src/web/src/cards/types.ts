/** Shapes returned by the BFF `/api/cards/*` endpoints (pb_cards.py). SYNTHETIC demo data. */

export type Behaviour = "Transactor" | "Revolver" | "Persistent debt";
export type PlayType = "Support" | "Protect" | "Retain" | "Grow";
export type Verdict = "pass" | "needs_approval" | "blocked";
export type CheckStatus = "pass" | "warn" | "block";
export type Num = number | string;

export interface CardsOverview {
  as_of: string;
  kpis: {
    accounts: number; linked_to_mortgage: number; balances: number; limits: number; utilization_pct: number;
    spend_12m: number; revolving_share_pct: number; persistent_debt: number; past_due_30: number;
    fraud_alerts: number; rewards_liability: number; fee_renewals_60d: number;
  };
  behaviour: { behaviour: Behaviour; accounts: number }[];
  products: { product: string; accounts: number; balance: number; spend: number }[];
  spend_by_month: { month: string; spend: number }[];
  spend_by_category: { category: string; spend: number }[];
  plays: { play: string; eligible: number; blocked: number }[];
}

export interface Play {
  account_id?: string;
  customer_id?: string;
  rank: number;
  play_type: PlayType;
  play: string;
  recommended_product: string;
  rationale: string;
  /** "Eligible", or the reason it is blocked - displayed as-is. */
  eligibility: string;
  value_at_stake_cad: Num;
}

export interface CardRow {
  account_id: string;
  customer_id: string;
  customer_name: string;
  segment: string;
  branch: string;
  product_id: string;
  product_name: string;
  behaviour: Behaviour;
  wellness_band: string;
  email_consent: string;
  linked_mortgage: "Y" | "N";
  top_category: string;
  credit_limit: number;
  balance: number;
  utilization_pct: number;
  monthly_spend_avg: number;
  spend_trend_pct: number;
  annual_fee: number;
  fee_anniversary_days: number;
  days_past_due: number;
  fraud_alerts_90d: number;
  top_play: Play | null;
  plays: number;
  /** Card processor (system of record) signals - see processor.ts. */
  processor_signals?: number;
  processor_top?: string | null;
  processor_new?: boolean;
}

export interface CardProduct {
  product_id: string;
  product_name: string;
  tier: string;
  annual_fee: Num;
  purchase_apr: Num;
  rewards: string;
  fx_fee: string;
  min_income: Num;
  welcome_bonus_points: Num;
}

export interface SpendMonth {
  month: string;
  spend: Num; groceries: Num; dining: Num; travel: Num; gas_transit: Num; bills: Num; online: Num; other: Num;
  foreign_spend: Num; payment: Num; interest_charged: Num; statement_balance: Num;
}

export interface CardAccountDetail extends Omit<CardRow, "plays"> {
  account: Record<string, Num> & {
    as_of_date: string; autopay: string; cli_express_consent: string; rewards_points: Num;
    min_payment_months_12m: Num; foreign_spend_share_pct: Num; income: Num; tds_renewal_pct: Num;
    purchase_apr: Num; opened_year: Num; province: string;
  };
  product: CardProduct;
  spend: SpendMonth[];
  plays: Play[];
  prompts: { label: string; prompt: string }[];
}

export interface Check { rule: string; name: string; status: CheckStatus; detail: string }

export interface CardDraft {
  account_id: string;
  play: Play;
  channel: string;
  purpose: "Service" | "Marketing";
  subject: string;
  body: string;
  checks: Check[];
  verdict: Verdict;
}

export const CATS = ["groceries", "dining", "travel", "gas_transit", "bills", "online", "other"] as const;
export type Cat = (typeof CATS)[number];
export const CAT_LABEL: Record<string, string> = {
  groceries: "Groceries", dining: "Dining", travel: "Travel", gas_transit: "Gas & transit",
  bills: "Bills", online: "Online", other: "Other",
};

export const TYPE_ORDER: Record<string, number> = { Support: 0, Protect: 1, Retain: 2, Grow: 3 };

/** The six plays, in Support → Protect → Retain → Grow order, with the policy each one leans on. */
export const PLAY_META: { play: string; type: PlayType; blurb: string; policy: string }[] = [
  { play: "Persistent-debt support", type: "Support", blurb: "Minimum payments month after month - offer a lower-cost path and budgeting help, never more credit.", policy: "RP-021" },
  { play: "Security check-in", type: "Protect", blurb: "Recent fraud alert - reassure and explain card lock and alerts before any sales conversation.", policy: "RP-022" },
  { play: "Fee renewal at risk", type: "Retain", blurb: "Annual fee due soon on a card that may no longer earn its keep - review value first.", policy: "RP-019" },
  { play: "Spend decline", type: "Retain", blurb: "Spend is trending down - check the card still suits how the client pays.", policy: "RP-019 · RP-011" },
  { play: "Upgrade fit: travel", type: "Grow", blurb: "Travel and foreign spend suggest a premium travel card would return more than it costs.", policy: "RP-019" },
  { play: "Credit limit increase", type: "Grow", blurb: "High utilisation with clean payments - only with express consent and affordability.", policy: "RP-020" },
];

export const num = (v: Num | undefined | null): number => {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return Number.isFinite(n) ? n : 0;
};

export const cad = (v: Num, digits = 0): string =>
  num(v).toLocaleString("en-CA", { style: "currency", currency: "CAD", currencyDisplay: "narrowSymbol", maximumFractionDigits: digits, minimumFractionDigits: digits });

/** Compact money for chart labels ($2.18M, $577K). */
export const cadShort = (v: Num): string => {
  const n = num(v), a = Math.abs(n);
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${(n / 1e3).toFixed(a >= 1e5 ? 0 : 1)}K`;
  return cad(n);
};

export const isEligible = (e: string) => e.trim().toLowerCase() === "eligible";

export const monthLabel = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return y ? new Date(y, m - 1, 15).toLocaleDateString("en-CA", { month: "short" }).replace(".", "") : ym;
};

export const addDays = (iso: string, days: number) => {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y) return "";
  return new Date(y, m - 1, d + days, 12).toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });
};

/** Wellness bands that make a client support-first in the list (carried from the mortgage book when linked). */
export const supportBand = (band: string) => band === "Vulnerable" || band === "Stretched";

/** Mirrors pb_cards.checks: who RP-021 treats as support-first (no upgrades, limit increases or new credit). */
export const supportFirst = (r: { behaviour: string; wellness_band: string; days_past_due: number }) =>
  r.behaviour === "Persistent debt" || r.wellness_band === "Vulnerable" || r.days_past_due > 0;

export const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/* ------------------------------------------------------------ IQ layers */
export type IQLayer = "work" | "fabric" | "foundry" | "web";
export const IQ_NAME: Record<IQLayer, string> = { fabric: "Fabric IQ", foundry: "Foundry IQ", web: "Web IQ", work: "Work IQ" };
export const isIQLayer = (v: unknown): v is IQLayer => typeof v === "string" && v in IQ_NAME;

/* ------------------------------------------- Web IQ market (/api/cards/market) */
export const OFFER_CATEGORIES = ["Premium travel", "Premium rewards", "Cash back", "No annual fee", "Low rate"] as const;

export interface MarketOffer {
  category: string; issuer: string; card: string; welcome_offer: string;
  annual_fee: string; purchase_rate: string; date: string; source: string; url: string;
}
export interface MarketObservation { text: string; source: string; date: string; url: string }
export interface MarketData {
  status: "live" | "baseline";
  stale?: boolean;
  fetchedAt?: string;
  detail?: string;
  offers: MarketOffer[];
  observations: MarketObservation[];
}

const str = (v: unknown) => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");

/** Coerce whatever the BFF returned into a safe MarketData, or null if it is not one. */
export function normaliseMarket(raw: unknown): MarketData | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const offers = (Array.isArray(r.offers) ? r.offers : [])
    .filter((o): o is Record<string, unknown> => !!o && typeof o === "object" && !!str((o as Record<string, unknown>).card))
    .map((o) => ({
      category: str(o.category), issuer: str(o.issuer), card: str(o.card), welcome_offer: str(o.welcome_offer),
      annual_fee: str(o.annual_fee), purchase_rate: str(o.purchase_rate), date: str(o.date), source: str(o.source), url: str(o.url),
    }));
  const observations = (Array.isArray(r.observations) ? r.observations : [])
    .filter((o): o is Record<string, unknown> => !!o && typeof o === "object" && !!str((o as Record<string, unknown>).text))
    .map((o) => ({ text: str(o.text), source: str(o.source), date: str(o.date), url: str(o.url) }));
  return {
    status: r.status === "live" ? "live" : "baseline",
    stale: r.stale === true,
    fetchedAt: str(r.fetchedAt) || undefined,
    detail: str(r.detail) || undefined,
    offers,
    observations,
  };
}

/** True when a public offer is the deployed bank's own, so the panel can show only *other* issuers.
 *  `aliases` comes from the brand pack (brand.json), e.g. ["rbc", "royal bank"]. */
export function isOwnBankOffer(o: Pick<MarketOffer, "issuer" | "card">, aliases: string[]): boolean {
  const names = aliases.map((a) => a.trim().toLowerCase()).filter(Boolean);
  if (!names.length) return false;
  const re = new RegExp(`\\b(?:${names.map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "i");
  return re.test(o.issuer) || re.test(o.card);
}

/** Only http(s) links are rendered as anchors. */
export const safeUrl = (u: string) => (/^https?:\/\//i.test(u) ? u : "");
