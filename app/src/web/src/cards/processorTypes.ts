/** Shapes returned by the BFF `/api/cards/processor` and `/api/cards/account/{id}/processor`
 *  endpoints (pb_processor.py) - the simulated card processor (system of record). SYNTHETIC data. */

export interface ProcessorProfile {
  id: string;
  name: string;
  style: string;
  api_base: string;
  auth_format: string;
  events: string;
  simulated: boolean;
  disclaimer: string;
}

export interface FeedFile {
  file_id: string;
  feed: string;
  description: string;
  format: string;
  records: number;
  received: string;
  status: string;
  warnings: number;
  landing: string;
}

export type InsightType = "Protect" | "Support" | "Service" | "Retain" | "Grow";

export interface ProcessorInsight {
  code: string;
  type: InsightType;
  title: string;
  detail: string;
  evidence: string[];
  value_cad: number;
  policy: string;
  play: string | null;
  actions: string[];
  done: string[];
  new_signal: boolean;
  account_id?: string;
  customer_name?: string;
  product_name?: string;
}

export interface ProcessorEvent {
  id: string;
  ts: string;
  type: string;
  account_id: string;
  detail: string;
  ref: string;
  source: string;
}

export interface ProcessorOverview {
  profile: ProcessorProfile;
  as_of: string;
  feeds: FeedFile[];
  kpis: {
    auths_30d: number; approval_rate: number; declines: number; cnp_share: number; cross_border_share: number; wallet_share: number;
    disputes_open: number; card_testing: number; unseen_by_book: number; declines_at_limit: number; billers_stopped: number;
    expiring_60d: number; alerts_off: number; fx_fees_30d: number;
  };
  declines_by_code: { code: string; text: string; count: number }[];
  disputes_by_stage: { stage: string; count: number }[];
  insight_counts: { code: string; count: number }[];
  insights: ProcessorInsight[];
  events: ProcessorEvent[];
}

export interface Authorization {
  auth_id: string;
  auth_ts: string;
  amount_cad: number;
  txn_currency: string;
  merchant_name: string;
  mcc: string;
  mcc_desc: string;
  merchant_country: string;
  pos_entry_mode: string;
  channel: "CP" | "CNP";
  wallet: string;
  recurring: "Y" | "N";
  three_ds: string;
  response_code: string;
  response_text: string;
  decision: "Approved" | "Declined";
  risk_score: number;
  fx_fee_cad: number;
  flagged: boolean;
}

export interface CardControls {
  card_token: string;
  masked_pan: string;
  card_status: string;
  ecommerce_enabled: "Y" | "N";
  international_enabled: "Y" | "N";
  contactless_enabled: "Y" | "N";
  alerts_enrolled: "Y" | "N";
  wallet_tokens: number;
  card_expiry: string;
  account_updater_enrolled: "Y" | "N";
  atm_daily_limit: number;
  last_reissue: string;
  network: string;
  new_masked_pan?: string;
  new_card_expiry?: string;
}

export interface CardOnFile {
  merchant_name: string;
  mcc_desc: string;
  amount_cad: number;
  cadence: string;
  first_billed: string;
  last_billed: string;
  status: "Active" | "Stopped";
  account_updater: "Y" | "N";
}

export interface Dispute {
  dispute_id: string;
  auth_ids: string;
  merchant_name: string;
  amount_cad: number;
  reason_code: string;
  reason: string;
  stage: string;
  opened: string;
  response_due: string;
  provisional_credit: "Y" | "N";
  channel: string;
  owner: string;
}

export interface ActionSpec { id: string; label: string; method: string; path: string; policy: string; effect: string }

export interface Guard { rule: string; name: string; status: "pass" | "block"; detail: string }

export interface ApiRequest { method: string; url: string; headers: Record<string, string>; body: unknown }

export interface ActionResult {
  action: string;
  label: string;
  effect: string;
  request: ApiRequest;
  guards: Guard[];
  verdict: "ready" | "blocked";
  executed: boolean;
  error?: string;
  response?: { status: number; body: Record<string, unknown> };
  event?: ProcessorEvent;
}

export interface ActionLogEntry {
  ts: string;
  action: string;
  label: string;
  approver: string;
  reason: string;
  reference: string;
  request: ApiRequest;
  response: { status: number; body: Record<string, unknown> };
  event: ProcessorEvent;
}

export interface ProcessorAccount {
  profile: ProcessorProfile;
  account_id: string;
  customer_name: string;
  support_first: boolean;
  controls: CardControls;
  insights: ProcessorInsight[];
  authorizations: Authorization[];
  summary: { auths: number; declined: number; cnp: number; cross_border: number; spend_approved: number };
  card_on_file: CardOnFile[];
  disputes: Dispute[];
  actions: ActionSpec[];
  log: ActionLogEntry[];
  prompts: { label: string; prompt: string }[];
}

export const ENTRY_LABEL: Record<string, string> = {
  contactless: "Tap", chip: "Chip", ecommerce: "Online", card_on_file: "Card on file",
};

export const INSIGHT_LABEL: Record<string, string> = {
  CARD_TESTING: "Card testing", DECLINES_AT_LIMIT: "Declines at limit", BILLERS_STOPPED: "Billers stopped",
  EXPIRY_BILLERS: "Expiry with billers", FX_FEES: "FX fees", DISPUTE_DUE: "Dispute due", ALERTS_OFF: "Alerts off",
};
