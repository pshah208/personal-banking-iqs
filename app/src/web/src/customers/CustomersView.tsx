/**
 * Customers - the triage list behind the renewal book.
 *
 * KPIs, then every customer with the signal that decides the conversation:
 * wellness band, attrition, TDS at renewal, and the top next-best action with
 * its eligibility (a blocked action shows the lock and the reason, verbatim).
 */
import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api";
import { WellnessPill } from "./WellnessView";
import { TDS_GUIDE, cad, isEligible, type CustomerRow, type Flag, type Overview } from "./types";
import "./customers.css";

const FILTERS: ("All" | Flag)[] = ["All", "Support first", "Deposit flight", "Above TDS guideline", "Life event"];
const FILTER_LABEL: Record<string, string> = { "Above TDS guideline": "Above TDS" };

export const Lock = () => (
  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6">
    <rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
  </svg>
);

export function CustomersView({ active, onOpen }: { active: boolean; onOpen: (cid: string) => void }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [rows, setRows] = useState<CustomerRow[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!active || rows) return;
    apiGet<{ customers: CustomerRow[] }>("/api/pb/customers").then((r) => setRows(r.customers ?? [])).catch((e) => setError(String(e)));
    apiGet<Overview>("/api/pb/overview").then(setOverview).catch(() => undefined);
  }, [active, rows]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter((r) =>
      (filter === "All" || r.flags.includes(filter)) &&
      `${r.name} ${r.customer_id} ${r.segment} ${r.branch} ${r.advisor} ${r.renewal_id}`.toLowerCase().includes(needle));
  }, [rows, filter, q]);

  const k = overview?.kpis;
  const eligible = Object.values(overview?.actions?.eligible ?? {}).reduce((a, b) => a + (b ?? 0), 0);
  const blocked = overview?.actions?.blocked ?? {};
  const blockedN = (blocked.consent ?? 0) + (blocked.vulnerable ?? 0);

  return (
    <div className="cu-root cu-page" hidden={!active}>
      <section className="cu-kpis" aria-label="Book summary">
        <div className="cu-kpi"><small>Customers</small><b>{k?.customers ?? "–"}</b><span>{k ? `${k.households} households · ${cad(k.balance)} maturing` : " "}</span></div>
        <div className="cu-kpi"><small>Products per customer</small><b>{k ? k.products_per_customer.toFixed(2) : "–"}</b><span>{k ? `${k.life_events} life events on file` : " "}</span></div>
        <div className="cu-kpi"><small>Deposit flight</small><b>{k?.deposit_flight ?? "–"}</b><span>≥10% of inflow moving out</span></div>
        <div className="cu-kpi"><small>Above TDS guideline</small><b>{k?.above_tds ?? "–"}</b><span>TDS at renewal over {TDS_GUIDE}%</span></div>
        <div className="cu-kpi"><small>Email consent</small><b>{k ? `${k.email_consent_pct}%` : "–"}</b><span>marketing consent granted</span></div>
        <div className="cu-kpi cu-kpi-split">
          <small>Next-best actions</small>
          <b>{overview ? <>{eligible}<em> / </em>{blockedN}</> : "–"}</b>
          <span>{overview ? `eligible / blocked · ${blocked.consent ?? 0} consent · ${blocked.vulnerable ?? 0} RP-012` : " "}</span>
        </div>
      </section>

      <div className="cu-toolbar">
        <div className="cu-chips" role="group" aria-label="Filter customers">
          {FILTERS.map((f) => (
            <button key={f} type="button" className="cu-chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {FILTER_LABEL[f] ?? f}<b>{f === "All" ? rows?.length ?? 0 : (rows ?? []).filter((r) => r.flags.includes(f)).length}</b>
            </button>
          ))}
        </div>
        <label className="cu-search">
          <span className="cu-sr">Search customers</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, branch, advisor…" />
        </label>
      </div>

      {error && <p className="cu-error" role="alert">Could not load customers ({error}).</p>}

      <div className="cu-card cu-list-card">
        <div className="cu-list-head" aria-hidden>
          <span>Customer</span><span>Renews</span><span>Wellness</span><span>Attrition</span><span>TDS at renewal</span><span>Top action</span><span>Signals</span>
        </div>
        {!rows && !error && <div className="cu-skel-list" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="cu-skel" />)}</div>}
        {rows && !shown.length && <p className="cu-empty">No customers match. <button type="button" className="cu-link" onClick={() => { setFilter("All"); setQ(""); }}>Clear filters</button></p>}
        <ul className="cu-list">
          {shown.map((r) => {
            const ok = isEligible(r.top_action.eligibility);
            return (
              <li key={r.customer_id}>
                <button type="button" className="cu-row" onClick={() => onOpen(r.customer_id)}
                        aria-label={`Open ${r.name}, ${r.wellness_band}, renews in ${r.days_to_maturity} days`}>
                  <span className="cu-c-who"><b>{r.name}</b><small>{r.segment} · {r.branch}</small></span>
                  <span className="cu-c-days"><b>{r.days_to_maturity}</b><small>days</small></span>
                  <span><WellnessPill band={r.wellness_band} score={r.wellness_score} /></span>
                  <span><span className={`cu-risk cu-risk-${r.attrition_band.toLowerCase()}`}>{r.attrition_band}</span><small className="cu-num">{r.attrition_score.toFixed(2)}</small></span>
                  <span className="cu-c-tds">
                    <b className={r.tds_renewal_pct > TDS_GUIDE ? "cu-over" : ""}>{r.tds_renewal_pct.toFixed(1)}%</b>
                    <i className="cu-minibar" aria-hidden><i style={{ width: `${Math.min(100, (r.tds_renewal_pct / 70) * 100)}%` }} className={r.tds_renewal_pct > TDS_GUIDE ? "cu-over" : ""} /><u style={{ left: `${(TDS_GUIDE / 70) * 100}%` }} /></i>
                  </span>
                  <span className={`cu-c-action${ok ? "" : " cu-blocked"}`}>
                    <span className={`cu-atype cu-atype-${r.top_action.type.toLowerCase()}`}>{r.top_action.type}</span>
                    <span className="cu-c-prod">{r.top_action.product}</span>
                    {!ok && <small className="cu-lock"><Lock />{r.top_action.eligibility}</small>}
                  </span>
                  <span className="cu-c-flags">
                    {r.flags.length ? r.flags.map((f) => <span key={f} className={`cu-flag cu-flag-${f.split(" ")[0].toLowerCase()}`}>{FILTER_LABEL[f] ?? f}</span>) : <small className="cu-muted">—</small>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      <p className="cu-foot">Synthetic demo data · {rows?.length ?? 0} customers on the 180-day renewal book{overview?.as_of ? ` · Fabric IQ as of ${overview.as_of}` : ""}. Internal signals are for the advisor only.</p>
    </div>
  );
}
