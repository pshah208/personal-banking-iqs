/** Shapes returned by the BFF `/api/pb/*` customer endpoints (pb_customers.py). */

export type WellnessBand = "Thriving" | "Stable" | "Stretched" | "Vulnerable";
export type ActionType = "Support" | "Retain" | "Deepen";
export type Flag = "Support first" | "Deposit flight" | "Above TDS guideline" | "Life event";
export type ConsentStatus = "Granted" | "Withdrawn" | "Not captured";
export type Channel = "Email" | "SMS" | "Phone";
export type Verdict = "pass" | "needs_approval" | "blocked";
export type CheckStatus = "pass" | "warn" | "block";

export interface Overview {
  as_of: string;
  kpis: {
    customers: number; households: number; balance: number; products_per_customer: number;
    vulnerable: number; stretched: number; deposit_flight: number; above_tds: number;
    email_consent_pct: number; life_events: number;
  };
  wellness_bands: { band: WellnessBand; count: number }[];
  actions: { eligible: Partial<Record<ActionType, number>>; blocked: { consent?: number; vulnerable?: number } };
}

export interface CustomerRow {
  customer_id: string;
  name: string;
  segment: string;
  branch: string;
  branch_id: string;
  advisor: string;
  renewal_id: string;
  days_to_maturity: number;
  balance: number;
  payment_shock_pct: number;
  attrition_band: string;
  attrition_score: number;
  lifetime_value: number;
  wellness_score: number;
  wellness_band: WellnessBand;
  tds_renewal_pct: number;
  products_held: number;
  top_action: { type: ActionType; product: string; eligibility: string };
  flags: Flag[];
  email_consent: ConsentStatus;
}

/** One month of the heat strip, normalised across the wellness and 360 payloads. */
export interface StripMonth {
  month: string;
  overdraft_days: number;
  nsf: number;
  missed: number;
  util: number;
  payroll: number;
  outflow: number;
}

export interface WellnessRow extends CustomerRow {
  drivers: string[];
  support_pathway: string;
  sales_suppressed: boolean;
  strip: StripMonth[];
}

export interface Action {
  rank: number;
  action_type: ActionType;
  product_id: string;
  product_name: string;
  score: number;
  rationale: string;
  /** "Eligible", or the reason it is blocked - displayed as-is. */
  eligibility: string;
}

export interface Product {
  account_id: string;
  product_id: string;
  product_name: string;
  category: string;
  balance_cad: number;
  status: string;
  opened_year: number;
}

export interface Signal {
  month: string;
  overdraft_days: number;
  nsf_count: number;
  missed_payments: number;
  card_utilization_pct: number;
  payroll_inflow_cad: number;
  competitor_outflow_cad: number;
  savings_balance_cad?: number;
}

export interface LifeEvent {
  event_type: string;
  event_date: string;
  source: string;
  confidence: string;
  implication: string;
}

type Num = number | string;

export interface Customer360 extends CustomerRow {
  household: {
    household_id: string; household_name: string; members: Num; dependents: Num;
    co_borrower_flag: string; gross_household_income_cad: Num; life_stage: string;
  };
  province: string;
  tenure_years: number;
  language: string;
  channel: string;
  nps: number;
  renewal: {
    product_type: string; maturity_date: string; mortgage_balance_cad: Num; current_rate_pct: Num;
    offered_renewal_rate_pct: Num; ltv_pct: Num; amortization_remaining_years: Num; attrition_risk_score: Num;
    renewal_likelihood_pct: Num; top_risk_drivers: string; competitor_rate_gap_bps: Num;
    recommended_offer_id: string; annual_revenue_exposure_cad: Num; renewal_stage?: string; payment_frequency?: string;
  };
  capacity: {
    gross_income_cad: Num; monthly_other_debt_cad: Num; monthly_tax_heat_cad: Num;
    current_payment_monthly_cad: Num; renewal_payment_monthly_cad: Num;
    gds_now_pct: Num; tds_now_pct: Num; gds_renewal_pct: Num; tds_renewal_pct: Num;
    bureau_band: string; base_pd_12m_pct: Num;
  };
  wellness: {
    wellness_score: Num; wellness_band: WellnessBand; vulnerability_flag: string; primary_driver: string;
    drivers: string[]; support_pathway: string; sales_suppressed: string; competitor_outflow_share_pct: Num;
  };
  products: Product[];
  signals: Signal[];
  life_events: LifeEvent[];
  consent: Partial<Record<Channel, ConsentStatus>>;
  actions: Action[];
  prompts: { label: string; prompt: string }[];
}

export interface Check {
  rule: string;
  name: string;
  status: CheckStatus;
  detail: string;
}

export interface Draft {
  customer_id: string;
  action: Action;
  channel: Channel;
  purpose: "Service" | "Marketing";
  subject: string;
  body: string;
  checks: Check[];
  verdict: Verdict;
}

export const num = (v: Num | undefined | null): number => {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return Number.isFinite(n) ? n : 0;
};

export const cad = (v: Num, digits = 0): string =>
  num(v).toLocaleString("en-CA", { style: "currency", currency: "CAD", currencyDisplay: "narrowSymbol", maximumFractionDigits: digits, minimumFractionDigits: digits });

export const isEligible = (e: string) => e.trim().toLowerCase() === "eligible";

export function signalsToStrip(s: Signal[]): StripMonth[] {
  return s.map((x) => ({
    month: x.month, overdraft_days: num(x.overdraft_days), nsf: num(x.nsf_count), missed: num(x.missed_payments),
    util: num(x.card_utilization_pct), payroll: num(x.payroll_inflow_cad), outflow: num(x.competitor_outflow_cad),
  }));
}

export const TDS_GUIDE = 44;
export const GDS_GUIDE = 39;
