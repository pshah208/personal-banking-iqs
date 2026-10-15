export interface Factor { id: string; label: string; unit: string; min: number; max: number; step: number }
export interface Preset {
  id: string; name: string; note: string; factors: Record<string, number>;
  group?: "market" | "world"; channels?: string; web_query?: string;
}

export type Severity = "dormant" | "low" | "elevated" | "high" | "severe";
export interface WorldTheme {
  id: string; name: string; note: string; channels: string;
  status: "active" | "emerging" | "dormant" | "unknown";
  severity: Severity; intensity: number;
  headline: string; date: string; source: string; url: string;
  base_factors: Record<string, number>; factors: Record<string, number>;
  live: boolean;
}
export interface EmergingRisk {
  title: string; severity: Severity; headline: string; why: string;
  date: string; source: string; url: string;
  closest: string | null; closest_name: string | null; proxy_factors: Record<string, number> | null;
}
export interface WorldPulse {
  status: "live" | "baseline"; detail?: string; stale?: boolean; fetchedAt?: string;
  themes: WorldTheme[]; emerging?: EmergingRisk[]; intensity: Record<Severity, number>;
}
export interface Library {
  factors: Factor[];
  presets: Preset[];
  good_dir: Record<string, number>;
  valuation: Record<string, number>;
  as_of: string;
  source: string;
}

export type Action = "Renew" | "Retain" | "Support first";

export interface RenewalRun {
  renewal_id: string; customer_id: string; name: string; segment: string;
  branch_id: string; branch: string; product: string; days_to_maturity: number;
  balance: number; insured: boolean;
  rate_before: number; rate_after: number;
  payment_now: number; payment_before: number; payment_after: number;
  shock_before_pct: number; shock_after_pct: number;
  gds_before_pct: number; gds_after_pct: number;
  tds_before_pct: number; tds_after_pct: number;
  pd_before_pct: number; pd_after_pct: number;
  attrition_before: number; attrition_after: number;
  ltv_before_pct: number; ltv_after_pct: number;
  nii_before: number; nii_after: number;
  el_before: number; el_after: number;
  value_before: number; value_after: number; value_change: number;
  wellness_band: string; vulnerable: boolean;
  action_before: Action; action_after: Action; flipped: boolean;
}

export interface Rollup {
  key: string; count: number; balance: number;
  value_before: number; value_after: number; value_change: number;
  above_tds: number; flipped: number; avg_shock_after_pct: number;
}

export interface Portfolio {
  renewals: number; balance: number;
  avg_shock_before_pct: number; avg_shock_after_pct: number;
  above_tds_before: number; above_tds_after: number;
  expected_delinquencies_before: number; expected_delinquencies_after: number;
  expected_attrition_before: number; expected_attrition_after: number;
  balance_at_risk_after: number;
  nii_before: number; nii_after: number;
  el_before: number; el_after: number;
  value_before: number; value_after: number; value_change: number; value_change_pct: number;
  support_first_before: number; support_first_after: number; flipped: number;
}

export interface ScenarioRun {
  name: string; factors: Record<string, number>; as_of: string;
  portfolio: Portfolio;
  branches: Rollup[];
  segments: Rollup[];
  renewals: RenewalRun[];
  method: string;
}
