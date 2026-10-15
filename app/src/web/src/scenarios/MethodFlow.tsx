/**
 * "How it works" - the renewal scenario engine as an animated six-stage pipeline.
 * Each stage shows its rule AND the live numbers for one selected renewal, so the
 * method is read through a real run rather than as prose. CSS-only motion
 * (transform / opacity), staggered, and disabled under prefers-reduced-motion.
 */
import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { Library, RenewalRun, ScenarioRun } from "./types";
import { cad, signed, tdsTone } from "./format";

const ICON: Record<string, ReactNode> = {
  factors: <path d="M3 17l5-6 4 3 6-8M15 6h3v3" />,
  rate: <path d="M5 19L19 5M7.5 8.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM16.5 18.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z" />,
  payment: <path d="M3 7h18v10H3zM3 11h18M7 15h3" />,
  afford: <path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6l8-3zM8.5 12l2.5 2.5 4.5-5" />,
  risk: <path d="M12 4l9 16H3L12 4zM12 10v4M12 17h.01" />,
  value: <path d="M3 12h4l3-7 4 14 3-7h4" />,
};

const FACTOR_SHORT: Record<string, string> = {
  boc_bp: "BoC", goc5_bp: "GoC 5Y", spread_bp: "Spread", competitor_gap_bp: "Undercut",
  unemployment_pp: "Jobless", inflation_pp: "CPI", house_price_pct: "Homes",
};
const unitOf = (k: string) => (k.endsWith("_bp") ? "bp" : k.endsWith("_pp") ? "pp" : "%");

interface Stage { id: string; title: string; rule: string; source: string; live: ReactNode }

function stages(r: RenewalRun, run: ScenarioRun, v: Record<string, number>, good: Record<string, number>): Stage[] {
  const moved = Object.entries(run.factors).filter(([, x]) => x !== 0);
  const variable = /variable/i.test(r.product);
  const dRate = Math.round((r.rate_after - r.rate_before) * 100);
  const gds = v.gds_limit_pct ?? 39;
  const tds = v.tds_limit_pct ?? 44;
  const tone = tdsTone(r.tds_after_pct, gds, tds);
  return [
    {
      id: "factors", title: "Market factors", source: "rate_scenario_presets",
      rule: "Seven governed factors: a committee preset, a Web IQ-scaled household signal, or your own sliders.",
      live: moved.length
        ? <span className="sc-flow-chips">{moved.map(([k, x]) => (
            <em key={k} className={x * (good[k] ?? 1) < 0 ? "bad" : "good"}>
              {FACTOR_SHORT[k] ?? k} {signed(x, unitOf(k) === "bp" || k === "house_price_pct" ? 0 : 2)}{unitOf(k)}
            </em>))}</span>
        : <span>All factors flat · today's book</span>,
    },
    {
      id: "rate", title: "Renewal rate", source: "renewal_scenario_sensitivity",
      rule: "Fixed terms follow the GoC 5-year yield (×0.9 pass-through); variable follows the BoC overnight rate. Plus the mortgage-spread move.",
      live: <><b className={dRate > 0 ? "t-down" : dRate < 0 ? "t-up" : ""}>{r.rate_before.toFixed(2)}% → {r.rate_after.toFixed(2)}%</b>
        <small>{variable ? "Variable · BoC" : "Fixed · GoC 5Y"} · {signed(dRate, 0)}bp</small></>,
    },
    {
      id: "payment", title: "Payment shock", source: "credit_capacity",
      rule: "The renewal payment is re-priced on the remaining amortization (annuity) and compared with today's payment.",
      live: <><b>{cad(r.payment_after)}/mo</b>
        <small>vs {cad(r.payment_now)} today · shock {r.shock_before_pct.toFixed(0)}% → <span className={r.shock_after_pct > r.shock_before_pct ? "t-down" : ""}>{r.shock_after_pct.toFixed(0)}%</span></small></>,
    },
    {
      id: "afford", title: "Affordability", source: "credit_capacity · RP-013",
      rule: `Income falls by unemployment × segment beta; obligations rise with inflation. GDS / TDS re-tested against ${gds}% / ${tds}% (RP-013).`,
      live: <><b>TDS {r.tds_before_pct.toFixed(1)}% → <span className={`sc-pill p-${tone}`}>{r.tds_after_pct.toFixed(1)}%</span></b>
        <small>GDS {r.gds_before_pct.toFixed(1)}% → {r.gds_after_pct.toFixed(1)}% · {r.segment}</small></>,
    },
    {
      id: "risk", title: "Risk", source: "financial_wellness · mortgage_renewals",
      rule: "Delinquency PD = bureau base × TDS multiplier × unemployment uplift. Attrition = model score + competitor undercut + shock.",
      live: <><b className={r.pd_after_pct > r.pd_before_pct ? "t-down" : ""}>PD {r.pd_before_pct.toFixed(2)}% → {r.pd_after_pct.toFixed(2)}%</b>
        <small>attrition {(r.attrition_before * 100).toFixed(0)}% → {(r.attrition_after * 100).toFixed(0)}%</small></>,
    },
    {
      id: "value", title: "Relationship value", source: "customer_360",
      rule: `Retained revenue − expected loss, over ${v.horizon_years ?? 5} years at ${v.discount_pct ?? 6}%. Flips to support-first above ${tds}% TDS (RP-012).`,
      live: <><b className={r.value_change < 0 ? "t-down" : r.value_change > 0 ? "t-up" : ""}>{cad(r.value_before)} → {cad(r.value_after)}</b>
        <small>{r.action_before}{r.action_after !== r.action_before
          ? <> → <span className={`sc-act ${r.action_after === "Support first" ? "a-flip" : "a-other"}`}>{r.action_after}</span></>
          : ""} · {cad(r.value_change, true)}</small></>,
    },
  ];
}

export function MethodFlow({ run, lib, initialId }: { run: ScenarioRun; lib: Library; initialId?: string | null }) {
  const [exId, setExId] = useState<string>(initialId ?? run.renewals[0]?.renewal_id ?? "");
  const [focus, setFocus] = useState<string | null>(null);
  const r = run.renewals.find((x) => x.renewal_id === exId) ?? run.renewals[0];
  if (!r) return null;
  const list = stages(r, run, lib.valuation, lib.good_dir ?? {});

  return (
    <section className="sc-flow" aria-label="How the scenario engine works">
      <div className="sc-flow-head">
        <div>
          <span className="sc-flow-kicker">How it works</span>
          <h2>Six deterministic steps from a market move to relationship value</h2>
          <p>Every number is reproducible from governed Fabric IQ tables and RP-013 limits; the Scenario Analyst only narrates them.</p>
        </div>
        <label className="sc-flow-pick">
          <span>Trace a renewal</span>
          <select value={r.renewal_id} onChange={(e) => setExId(e.target.value)}>
            {run.renewals.map((x) => (
              <option key={x.renewal_id} value={x.renewal_id}>
                {x.renewal_id} · {x.name}{x.flipped ? " · flips" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>

      <ol className={`sc-flow-track${focus ? " has-focus" : ""}`}>
        {list.map((st, i) => (
          <li key={st.id} className={`sc-flow-stage${focus === st.id ? " focus" : ""}`} style={{ "--i": i } as CSSProperties}
              tabIndex={0} onMouseEnter={() => setFocus(st.id)} onMouseLeave={() => setFocus(null)}
              onFocus={() => setFocus(st.id)} onBlur={() => setFocus(null)}>
            {i > 0 && <span className="sc-flow-link" aria-hidden><i /></span>}
            <div className="sc-flow-node">
              <span className="sc-flow-icon" aria-hidden>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{ICON[st.id]}</svg>
              </span>
              <span className="sc-flow-step">{String(i + 1).padStart(2, "0")}</span>
            </div>
            <h3>{st.title}</h3>
            <p className="sc-flow-rule">{st.rule}</p>
            <div className="sc-flow-live" key={`${r.renewal_id}-${run.name}-${JSON.stringify(run.factors)}`}>{st.live}</div>
            <code className="sc-flow-src">{st.source}</code>
          </li>
        ))}
      </ol>

      <div className="sc-flow-foot">
        <div className="sc-flow-tile fabric" style={{ "--i": 6 } as CSSProperties}>
          <small>Fabric IQ · governed data</small>
          <b>rate_scenario_presets · renewal_scenario_sensitivity · credit_capacity</b>
          <span>Preset library, per-renewal pass-through and income betas, and today's GDS/TDS and bureau PD.</span>
        </div>
        <div className="sc-flow-tile foundry" style={{ "--i": 7 } as CSSProperties}>
          <small>Foundry IQ · policy</small>
          <b>RP-013 · RP-012 · RP-014 · RP-015</b>
          <span>Affordability limits, support-first treatment, fair-pricing and decision-support guardrails frame the brief.</span>
        </div>
        <div className="sc-flow-tile agent" style={{ "--i": 8 } as CSSProperties}>
          <small>Foundry agent</small>
          <b>pb-scenario-analyst</b>
          <span>Fabric IQ + Foundry IQ only. It narrates governed numbers, cites RP ids and refers to clients by renewal ID, never by name.</span>
        </div>
      </div>

      <details className="sc-flow-text">
        <summary>Full method (text)</summary>
        <pre>{run.method}</pre>
      </details>
    </section>
  );
}
