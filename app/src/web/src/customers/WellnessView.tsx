/**
 * Financial wellness - "support before sales".
 *
 * The queue is every Vulnerable or Stretched customer, lowest wellness score
 * first, with the plain-language drivers, the support pathway policy and a
 * compact 12-month heat strip. Opening a support plan goes to the same
 * customer workspace with the Support action preselected. Under RP-012 sales
 * are suppressed for vulnerable customers; nothing here offers a product.
 */
import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api";
import type { Overview, StripMonth, WellnessBand, WellnessRow } from "./types";
import "./customers.css";

const BAND_ORDER: WellnessBand[] = ["Thriving", "Stable", "Stretched", "Vulnerable"];

export function WellnessPill({ band, score }: { band: WellnessBand; score?: number }) {
  return (
    <span className={`cu-pill cu-band-${band.toLowerCase()}`}>
      <i aria-hidden />{band}{score !== undefined && <b>{score}</b>}
    </span>
  );
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const ROWS: { key: keyof Omit<StripMonth, "month">; label: string; unit: (v: number) => string }[] = [
  { key: "overdraft_days", label: "Overdraft days", unit: (v) => `${v} day${v === 1 ? "" : "s"} in overdraft` },
  { key: "nsf", label: "NSF items", unit: (v) => `${v} NSF item${v === 1 ? "" : "s"}` },
  { key: "missed", label: "Missed payments", unit: (v) => `${v} missed payment${v === 1 ? "" : "s"}` },
  { key: "util", label: "Card utilisation", unit: (v) => `${v.toFixed(0)}% card utilisation` },
  { key: "payroll", label: "Payroll drop", unit: (v) => `Payroll ${v.toLocaleString("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 })}` },
  { key: "outflow", label: "Outflow to others", unit: (v) => `${v.toLocaleString("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 })} moved to other institutions` },
];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 12 months x 6 stress signals. Intensity 0..1 per cell; one calm hue, never alarm red. */
export function HeatStrip({ strip, compact = false }: { strip: StripMonth[]; compact?: boolean }) {
  const base = useMemo(() => {
    const first = strip.slice(0, 6).map((s) => s.payroll).filter((v) => v > 0);
    return first.length ? first.reduce((a, b) => a + b, 0) / first.length : 0;
  }, [strip]);
  const intensity = (key: (typeof ROWS)[number]["key"], v: number) => {
    switch (key) {
      case "overdraft_days": return clamp01(v / 12);
      case "nsf": return clamp01(v / 2);
      case "missed": return v > 0 ? 1 : 0;
      case "util": return clamp01((v - 35) / 50);
      case "payroll": return base ? clamp01((base - v) / base / 0.35) : 0;
      case "outflow": return base ? clamp01(v / (base * 0.4)) : 0;
    }
  };
  return (
    <div className={`cu-heat${compact ? " cu-heat-compact" : ""}`} role="table"
         aria-label="Twelve months of financial stress signals; darker cells mean more stress">
      {!compact && (
        <div className="cu-heat-row cu-heat-months" role="row">
          <span role="columnheader" />
          {strip.map((s) => <span role="columnheader" key={s.month}>{MONTHS[Number(s.month.slice(5, 7)) - 1]?.[0] ?? ""}</span>)}
        </div>
      )}
      {ROWS.map((r) => (
        <div className="cu-heat-row" role="row" key={r.key}>
          <span role="rowheader" className="cu-heat-label">{r.label}</span>
          {strip.map((s) => {
            const i = intensity(r.key, s[r.key]);
            return (
              <span role="cell" key={s.month} className="cu-heat-cell" title={`${s.month}: ${r.unit(s[r.key])}`}
                    style={{ background: i > 0.02 ? `rgb(67 56 202 / ${(0.12 + 0.78 * i).toFixed(2)})` : undefined }}>
                <span className="cu-sr">{`${s.month}: ${r.unit(s[r.key])}`}</span>
              </span>
            );
          })}
        </div>
      ))}
      {!compact && strip.length > 0 && (
        <div className="cu-heat-foot">
          <span>{strip[0].month}</span>
          <span className="cu-heat-scale" aria-hidden><i /><i /><i /><i /></span>
          <span>{strip[strip.length - 1].month}</span>
        </div>
      )}
    </div>
  );
}

export function BandBar({ bands }: { bands: { band: WellnessBand; count: number }[] }) {
  const total = bands.reduce((a, b) => a + b.count, 0) || 1;
  const sorted = BAND_ORDER.map((b) => bands.find((x) => x.band === b) ?? { band: b, count: 0 });
  return (
    <div className="cu-bandbar">
      <div className="cu-bandbar-track" role="img"
           aria-label={sorted.map((b) => `${b.band} ${b.count}`).join(", ")}>
        {sorted.map((b) => b.count > 0 && (
          <span key={b.band} className={`cu-band-${b.band.toLowerCase()}`} style={{ flexGrow: b.count }} />
        ))}
      </div>
      <ul className="cu-bandbar-legend">
        {sorted.map((b) => (
          <li key={b.band}><WellnessPill band={b.band} /><b>{b.count}</b><small>{Math.round((100 * b.count) / total)}%</small></li>
        ))}
      </ul>
    </div>
  );
}

export function WellnessView({ active, onOpen }: { active: boolean; onOpen: (cid: string) => void }) {
  const [rows, setRows] = useState<WellnessRow[] | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [policy, setPolicy] = useState("");
  const [error, setError] = useState("");
  const [band, setBand] = useState<"all" | "Vulnerable" | "Stretched">("all");

  useEffect(() => {
    if (!active || rows) return;
    apiGet<{ customers: WellnessRow[]; policy: string }>("/api/pb/wellness")
      .then((r) => { setRows(r.customers ?? []); setPolicy(r.policy ?? ""); })
      .catch((e) => setError(String(e)));
    apiGet<Overview>("/api/pb/overview").then(setOverview).catch(() => undefined);
  }, [active, rows]);

  const shown = (rows ?? []).filter((r) => band === "all" || r.wellness_band === band);
  const count = (b: WellnessBand) => (rows ?? []).filter((r) => r.wellness_band === b).length;

  return (
    <div className="cu-root cu-page" hidden={!active}>
      <header className="cu-hero">
        <div>
          <div className="cu-eyebrow">Financial wellness · RP-012 support-first</div>
          <h2>Support before sales</h2>
          <p>
            Customers whose banking shows strain ahead of renewal. For anyone flagged vulnerable, sales are suppressed
            and the only outreach is a support conversation - amortization relief (RP-006), hardship arrangements (RP-014)
            or budgeting help. Signals are synthetic and shown to the advisor only; they are never repeated to the client.
          </p>
        </div>
        {overview?.wellness_bands?.length ? (
          <div className="cu-card cu-hero-bands">
            <div className="cu-card-head"><h3>Wellness across the book</h3><span>{overview.kpis?.customers ?? ""} customers</span></div>
            <BandBar bands={overview.wellness_bands} />
          </div>
        ) : null}
      </header>

      {error && <p className="cu-error" role="alert">Could not load the wellness queue ({error}).</p>}

      <div className="cu-toolbar">
        <div className="cu-chips" role="group" aria-label="Filter the support queue">
          {(["all", "Vulnerable", "Stretched"] as const).map((b) => (
            <button key={b} type="button" className="cu-chip" aria-pressed={band === b} onClick={() => setBand(b)}>
              {b === "all" ? "All in queue" : b}<b>{b === "all" ? rows?.length ?? 0 : count(b)}</b>
            </button>
          ))}
        </div>
        {policy && <small className="cu-muted">{policy}</small>}
      </div>

      {!rows && !error && <div className="cu-skel-list" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="cu-skel" />)}</div>}
      {rows && !shown.length && <p className="cu-empty">No customers in this part of the queue.</p>}

      <ol className="cu-queue">
        {shown.map((r) => (
          <li key={r.customer_id} className={`cu-card cu-qcard cu-q-${r.wellness_band.toLowerCase()}`}>
            <div className="cu-q-who">
              <div className="cu-q-name">
                <h3>{r.name}</h3>
                <WellnessPill band={r.wellness_band} score={r.wellness_score} />
              </div>
              <small>{r.segment} · {r.branch} · {r.advisor}</small>
              <div className="cu-q-meta">
                <span>Renews in <b>{r.days_to_maturity}</b> days</span>
                <span>Payment +{r.payment_shock_pct.toFixed(0)}% at renewal</span>
                <span>TDS {r.tds_renewal_pct.toFixed(1)}%</span>
              </div>
              <div className="cu-q-tags">
                <span className="cu-tag cu-tag-path">{r.support_pathway}</span>
                {r.sales_suppressed && <span className="cu-tag cu-tag-quiet" title="RP-012: no product offers while the client is flagged vulnerable">Sales suppressed</span>}
              </div>
            </div>
            <div className="cu-q-why">
              <h4>What we are seeing</h4>
              <ul>{r.drivers.slice(0, 4).map((d) => <li key={d}>{d}</li>)}</ul>
              {r.drivers.length > 4 && <small className="cu-muted">+{r.drivers.length - 4} more in the workspace</small>}
            </div>
            <div className="cu-q-strip">
              <h4>Last 12 months</h4>
              <HeatStrip strip={r.strip} compact />
            </div>
            <div className="cu-q-go">
              <button type="button" className="cu-btn cu-btn-primary" onClick={() => onOpen(r.customer_id)}>
                Open support plan ›
              </button>
            </div>
          </li>
        ))}
      </ol>
      <p className="cu-foot">Synthetic demo data. Wellness bands are a conversation aid for the advisor, not a credit decision.</p>
    </div>
  );
}
