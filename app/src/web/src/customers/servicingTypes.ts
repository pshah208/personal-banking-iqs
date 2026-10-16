/** Shapes returned by `/api/mortgage/servicing*` (pb_servicing.py, pb_stream.py). SYNTHETIC data. */
import type { ActionLogEntry, ActionSpec, FeedFile, ProcessorEvent } from "../cards/processorTypes";

export type SvcType = "Support" | "Retain" | "Service";

export interface SvcInsight {
  code: string;
  type: SvcType;
  title: string;
  detail: string;
  evidence: string[];
  value_cad: number;
  policy: string;
  actions: string[];
  done: string[];
  new_signal: boolean;
  live?: boolean;
  customer_id?: string;
  customer_name?: string;
  renewal_id?: string;
  days_to_maturity?: number;
}

export interface ServicingOverview {
  profile: { id: string; name: string; api_base: string; feeds: string; simulated: boolean; disclaimer: string };
  as_of: string;
  feeds: FeedFile[];
  kpis: {
    payout_requests: number; payout_balance: number; unseen_by_book: number; shopping_clients: number; holds_expiring: number;
    offers_unopened: number; missed_payments: number; prepay_surge: number; pad_success_pct: number; inquiries_without_consent: number;
  };
  insight_counts: { code: string; count: number }[];
  insights: SvcInsight[];
  events: ProcessorEvent[];
}

export interface SvcPayment { due_date: string; scheduled_cad: number; status: string; paid_on: string; prepayment_cad: number }
export interface SvcPayout {
  request_id: string; requested_on: string; requested_by: string; purpose: string; payout_amount_cad: number;
  statement_due: string; status: string; prepayment_penalty_cad: number;
}
export interface SvcInquiry { inquiry_id: string; inquiry_date: string; inquirer: string; inquirer_type: string; bureau: string }
export interface SvcOffer {
  offer_ref: string; sent_on: string; channel: string; offered_rate_pct: string | number; opened: "Y" | "N"; opened_on: string;
  rate_hold_expiry: string; status: string; preferred_language: string;
}

export interface ServicingCustomer {
  profile: ServicingOverview["profile"];
  customer_id: string;
  customer_name: string;
  renewal: { renewal_id: string; days_to_maturity: string; mortgage_balance_cad: string; offered_renewal_rate_pct: string; product_type: string };
  risk: { attrition_risk_band: string; rate_shopping_signal: string };
  wellness_band: string;
  insights: SvcInsight[];
  payments: SvcPayment[];
  payouts: SvcPayout[];
  offer: SvcOffer | null;
  deferral: { months: number; status: string; by: string } | null;
  retention_offer: { offerName: string; discountBps: number; toRatePct: number; status: string; requiredApprover: string } | null;
  inquiries: SvcInquiry[];
  inquiries_withheld: number;
  actions: ActionSpec[];
  log: ActionLogEntry[];
}

export interface ServicingLive {
  connected: boolean;
  reason?: string;
  queried_at?: string;
  source: { eventstream: string; eventhouse: string; database: string; table: string; uri: string };
  kpis_24h?: { events?: number; payout_requests?: number; bureau_inquiries?: number; pad_returns?: number; offers_opened?: number; last_event?: string };
  kpis_7d?: { events?: number; payout_requests?: number; bureau_inquiries?: number; pad_returns?: number; payout_balance_cad?: number; customers?: number };
  payouts?: { customer_id: string; renewal_id: string; customer_name: string; payout_amount_cad: number; requested_by: string; purpose: string; last_seen: string }[];
  shopping?: { customer_id: string; renewal_id: string; customer_name: string; inquiries: number; lenders: string[] | string; last_seen: string }[];
  pad_returns?: { customer_id: string; customer_name: string; returns: number; amount_cad: number; last_seen: string }[];
  recent?: { event_ts: string; event_id: string; event_type: string; customer_id: string; customer_name: string; amount_cad: number; counterparty: string; detail: string }[];
}

export const SVC_LABEL: Record<string, string> = {
  PAYOUT_REQUESTED: "Payout requested", SHOPPING: "Shopping", SHOPPING_NO_CONSENT: "Trigger without consent",
  RATE_HOLD_EXPIRING: "Rate hold expiring", OFFER_NOT_OPENED: "Offer not opened", MISSED_PAYMENTS: "Missed payments",
  PREPAYMENT_SURGE: "Prepayment surge",
};
