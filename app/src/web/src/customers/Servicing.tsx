/**
 * Mortgage servicing - the simulated system of record under the renewal book.
 *
 *   ServicingPortfolio  servicing feeds, KPIs only the servicing platform can
 *                       compute, insights the attrition model has not seen,
 *                       the live Eventstream panel and the event stream.
 *   ServicingAccount    one client's mortgage at the servicer: offer and rate hold,
 *                       payout requests, bureau triggers (consented only), payment
 *                       history, insights with guarded actions and the audit log.
 *
 * Built on the same framework as the card processor (sor.py / Processor.tsx):
 * preview -> policy guards -> named approval -> vendor-style response -> audit.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api";
import { SorActionPanel, useSorAction } from "../cards/SorAction";
import "../cards/cards.css";
import "../cards/processorView.css";
import { SVC_LABEL, type ServicingCustomer, type ServicingLive, type ServicingOverview, type SvcInsight } from "./servicingTypes";

const cad = (v: number, d = 0) => new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: d, minimumFractionDigits: d }).format(v);
const cadShort = (v: number) => (v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : cad(v));
const when = (ts: string) => ts.replace("T", " ").replace(/:\d\d(\.\d+)?Z?$/, "");
const ago = (iso?: string) => {
  if (!iso) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};

function Tag({ t }: { t: SvcInsight["type"] }) {
  return t === "Service" ? <span className="px-tag px-tag-service">Service</span> : <span className={`cd-ptype cd-ptype-${t.toLowerCase()}`}>{t}</span>;
}

function SimBadge({ name }: { name: string }) {
  return <span className="px-sor" title="Simulated system of record - synthetic data, not connected to any vendor"><i aria-hidden />{name} · simulated</span>;
}

function useLive(active: boolean, customer = "") {
  const [live, setLive] = useState<ServicingLive | null>(null);
  useEffect(() => {
    if (!active) return;
    let stop = false;
    const tick = () => apiGet<ServicingLive>(`/api/mortgage/servicing/live${customer ? `?customer=${encodeURIComponent(customer)}` : ""}`)
      .then((r) => { if (!stop) setLive(r); }).catch(() => undefined);
    tick();
    const h = window.setInterval(tick, 10000);
    return () => { stop = true; window.clearInterval(h); };
  }, [active, customer]);
  return live;
}

function LivePanel({ active, onOpen }: { active: boolean; onOpen: (cid: string) => void }) {
  const live = useLive(active);
  if (!live) return null;
  if (!live.connected) {
    return (
      <div className="px-live px-live-off" role="note">
        <b>Live servicing stream not connected</b>
        <span>Fabric Eventstream <code>{live.source.eventstream}</code> → <code>{live.source.table}</code>. Run <code>data/fabric-iq/deploy_realtime.py</code>.</span>
        {live.reason && <small>{live.reason}</small>}
      </div>
    );
  }
  const k = live.kpis_24h ?? {};
  const w = live.kpis_7d ?? {};
  return (
    <div className="px-live" aria-label="Live servicing stream">
      <div className="px-live-head">
        <span className="px-live-dot" aria-hidden /><b>Live · Fabric Eventstream → Eventhouse</b>
        <code>{live.source.eventstream} → {live.source.database}.{live.source.table}</code>
        <small>last event {ago(k.last_event)} · refreshed {ago(live.queried_at)}</small>
      </div>
      <div className="px-live-kpis">
        <div className={w.payout_requests ? "px-hot" : ""}><b>{w.payout_requests ?? 0}</b><small>payout requests · 7 d</small></div>
        <div><b>{w.payout_balance_cad ? cadShort(w.payout_balance_cad) : "–"}</b><small>balance on payout requests</small></div>
        <div><b>{w.bureau_inquiries ?? 0}</b><small>lender inquiries · 7 d (consented)</small></div>
        <div><b>{w.pad_returns ?? 0}</b><small>returned payments · 7 d</small></div>
        <div><b>{k.offers_opened ?? 0}</b><small>offers opened · 24 h</small></div>
        <div><b>{k.events ?? 0}</b><small>events · 24 h</small></div>
      </div>
      <div className="px-live-grid">
        <div>
          <h4>Payout requests (KQL · PayoutRequestsLive)</h4>
          {!live.payouts?.length && <p className="cd-muted">None in the last 7 days.</p>}
          <ul className="px-live-alerts">
            {live.payouts?.map((p) => (
              <li key={p.customer_id}><button type="button" onClick={() => onOpen(p.customer_id)}>
                <b>{p.customer_name || p.customer_id}</b><span>{cad(p.payout_amount_cad)} · {p.requested_by} · {p.purpose}</span>
                <small>{p.renewal_id} · {ago(p.last_seen)}</small></button></li>
            ))}
          </ul>
          {!!live.shopping?.length && <>
            <h4>Shopping (ShoppingSignalsLive · consented)</h4>
            <ul className="px-live-alerts px-live-support">
              {live.shopping.map((s) => (
                <li key={s.customer_id}><button type="button" onClick={() => onOpen(s.customer_id)}>
                  <b>{s.customer_name || s.customer_id}</b><span>{s.inquiries} inquir{s.inquiries === 1 ? "y" : "ies"} · {Array.isArray(s.lenders) ? s.lenders.join(", ") : s.lenders}</span>
                  <small>{s.renewal_id} · {ago(s.last_seen)}</small></button></li>
              ))}
            </ul>
          </>}
        </div>
        <div>
          <h4>Latest servicing events</h4>
          <ul className="px-live-feed">
            {live.recent?.map((r) => (
              <li key={r.event_id} className={r.event_type === "payout.requested" || r.event_type === "pad.returned" ? "px-live-declined" : ""}>
                <small>{ago(r.event_ts)}</small>
                <span><b>{r.customer_name || r.customer_id}</b> · {r.detail}{r.counterparty ? ` · ${r.counterparty}` : ""}</span>
                <code>{r.event_type}</code>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- portfolio */
export function ServicingPortfolio({ active, onOpen }: { active: boolean; onOpen: (cid: string) => void }) {
  const [data, setData] = useState<ServicingOverview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(true);

  const load = useCallback(() => {
    setBusy(true);
    apiGet<ServicingOverview>("/api/mortgage/servicing").then((d) => { setData(d); setError(""); })
      .catch((e) => setError(String(e))).finally(() => setBusy(false));
  }, []);
  useEffect(() => { if (active && !data) load(); }, [active, data, load]);

  const reset = async () => {
    setBusy(true);
    try { await apiPost("/api/mortgage/servicing/reset", {}); } catch { /* reload shows state */ }
    load();
  };
  const k = data?.kpis;

  return (
    <div className="cd-root px-embed">
      <section className="cd-card px-portfolio" aria-labelledby="sv-h">
        <div className="px-head">
          <div>
            <div className="cd-eyebrow">System of record · mortgage servicing</div>
            <h2 id="sv-h">Who is leaving before the attrition model knows</h2>
            <p className="cd-muted">Payout statement requests, other lenders' credit inquiries (consented only), renewal offer and rate-hold status,
              returned payments and prepayments - from the servicing platform, joined to the renewal book.</p>
          </div>
          <div className="px-head-meta">
            {data && <SimBadge name={data.profile.name} />}
            {data && <code className="px-api">{data.profile.api_base}</code>}
            <span className="px-head-btns">
              <button type="button" className="cd-btn cd-btn-ghost" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Collapse" : "Expand"}</button>
              <button type="button" className="cd-btn cd-btn-ghost" onClick={load} disabled={busy}>Refresh</button>
              <button type="button" className="cd-btn cd-btn-ghost" onClick={reset} disabled={busy} title="Clear simulated actions and events">Reset simulator</button>
            </span>
          </div>
        </div>
        {error && <p className="cd-error" role="alert">Could not load the servicing feed ({error}).</p>}
        {open && data && k && <>
          <ol className="px-pipeline" aria-label="Integration path">
            <li><b>{data.profile.name}</b><small>servicing master · PAD results · payout requests</small></li>
            <li><b>Bureau triggers</b><small>other lenders' hard inquiries · consented clients only</small></li>
            <li><b>Eventstream → Eventhouse</b><small>es_mortgage_servicing → svc_stream · KQL insights</small></li>
            <li><b>Fabric IQ</b><small>svc_* tables + svc_event_stream joined to renewals</small></li>
            <li><b>Renewal book &amp; agents</b><small>insights · human-approved actions · audit</small></li>
          </ol>

          <LivePanel active={active && open} onOpen={onOpen} />

          <div className="px-feeds" aria-label="Files delivered by the servicing systems">
            {data.feeds.map((f) => (
              <div key={f.file_id} className={`px-feed${f.warnings ? " px-warn" : ""}`} title={`${f.description} · ${f.format} → ${f.landing}`}>
                <b>{f.feed}</b><span>{f.records.toLocaleString()} records</span>
                <small>{f.received === "continuous" ? "streaming" : `received ${f.received.slice(11)}`} · {f.status}</small>
              </div>
            ))}
          </div>

          <div className="px-kpis">
            <div className="px-kpi px-kpi-protect"><small>Payout requests</small><b>{k.payout_requests}</b>
              <span>{k.unseen_by_book ? <strong>{k.unseen_by_book} not flagged by the model</strong> : `${cadShort(k.payout_balance)} balance`}</span></div>
            <div className="px-kpi"><small>Balance leaving</small><b>{cadShort(k.payout_balance)}</b><span>named on payout requests</span></div>
            <div className="px-kpi"><small>Shopping</small><b>{k.shopping_clients}</b><span>lender inquiries · consented</span></div>
            <div className="px-kpi"><small>Rate holds expiring</small><b>{k.holds_expiring}</b><span>within 10 days</span></div>
            <div className="px-kpi"><small>Offers not opened</small><b>{k.offers_unopened}</b><span>5+ days after sending</span></div>
            <div className="px-kpi px-kpi-support"><small>Returned payments</small><b>{k.missed_payments}</b><span>clients · support first</span></div>
            <div className="px-kpi"><small>PAD success</small><b>{k.pad_success_pct}%</b><span>last 3 months</span></div>
            <div className="px-kpi"><small>Prepayment surge</small><b>{k.prepay_surge}</b><span>{k.inquiries_without_consent} triggers withheld (no consent)</span></div>
          </div>

          <div className="px-grid">
            <div className="px-col">
              <div className="cd-card-head"><h3>Insights only the servicing platform can give</h3><span>click to open the client</span></div>
              <p className="px-counts">{data.insight_counts.map((c) => <span key={c.code} className="cd-tag">{SVC_LABEL[c.code] ?? c.code} · {c.count}</span>)}</p>
              <ul className="px-insights">
                {data.insights.map((i, n) => (
                  <li key={`${i.customer_id}-${i.code}-${n}`}>
                    <button type="button" className="px-insight" onClick={() => i.customer_id && onOpen(i.customer_id)}>
                      <Tag t={i.type} />
                      <span className="px-insight-main">
                        <b>{i.title}{i.live && <em className="px-new px-live-tag">live</em>}{i.new_signal && <em className="px-new">new to the book</em>}</b>
                        <small>{i.customer_name} · {i.renewal_id} · renews in {i.days_to_maturity} days</small>
                      </span>
                      <span className="px-insight-side">{i.value_cad > 0 && <b>{cadShort(i.value_cad)}</b>}<code>{i.policy}</code></span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="px-col">
              <div className="cd-card-head px-events-head"><h3>Event stream</h3><span>servicing webhooks · newest first</span></div>
              <ul className="px-events">
                {data.events.map((e) => (
                  <li key={e.id} className={e.source === "feed" ? "" : "px-event-live"}>
                    <code>{e.type}</code><span>{e.detail}</span><small>{e.account_id} · {when(e.ts)}</small>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <p className="cd-foot">{data.profile.disclaimer} Data as of {data.as_of}.</p>
        </>}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ client */
export function ServicingAccount({ cid }: { cid: string }) {
  const [d, setD] = useState<ServicingCustomer | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(true);
  const load = useCallback(() => {
    apiGet<ServicingCustomer>(`/api/mortgage/servicing/${cid}`).then((r) => { setD(r); setError(""); }).catch((e) => setError(String(e)));
  }, [cid]);
  useEffect(() => { setD(null); load(); }, [load]);
  const act = useSorAction(`/api/mortgage/servicing/${cid}/action`, load);
  const live = useLive(open, cid);
  const label = (id: string) => d?.actions.find((x) => x.id === id)?.label ?? id;

  return (
    <div className="cd-root px-embed">
      <section className={`cd-360 px-account${open ? "" : " cd-360-closed"}`} aria-label="Mortgage servicing">
        <button type="button" className="cd-360-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span>Mortgage servicing</span><small>payout requests · bureau triggers · offer &amp; rate hold · payments · actions</small>
          {d && <SimBadge name={d.profile.name} />}<i aria-hidden>{open ? "−" : "+"}</i>
        </button>
        {open && <div className="px-acc">
          {error && <p className="cd-error" role="alert">Servicing platform unavailable ({error}).</p>}
          {!d && !error && <div className="cd-skel" aria-busy="true" />}
          {d && <>
            <div className="px-acc-top">
              <div className={`px-cardtile${d.payouts.length ? " px-status-temporarily" : ""}`}>
                <small>{d.renewal.renewal_id} · {d.renewal.product_type}</small>
                <b>{d.payouts.length ? "Payout requested" : d.offer ? d.offer.status : "No offer yet"}</b>
                <span>{cad(Number(d.renewal.mortgage_balance_cad))} · renews in {d.renewal.days_to_maturity} days · offered {d.renewal.offered_renewal_rate_pct}%</span>
                <ul className="px-ctl">
                  {d.offer && <li className="on">rate hold to {d.offer.rate_hold_expiry}</li>}
                  {d.offer && <li className={d.offer.opened === "Y" ? "on" : "off"}>offer {d.offer.opened === "Y" ? "opened" : "not opened"}</li>}
                  <li className="on">model: {d.risk.attrition_risk_band} · shopping {d.risk.rate_shopping_signal}</li>
                  <li className="on">wellness {d.wellness_band}</li>
                  {d.retention_offer && <li className="on">{d.retention_offer.offerName} · {d.retention_offer.status}</li>}
                  {d.deferral && <li className="on">deferral {d.deferral.status}</li>}
                </ul>
              </div>
              <div className="px-acc-sum">
                <div><b>{d.payouts.length}</b><small>payout requests</small></div>
                <div><b>{d.inquiries.length || (d.inquiries_withheld ? "–" : 0)}</b><small>{d.inquiries_withheld ? `${d.inquiries_withheld} withheld · no consent` : "lender inquiries"}</small></div>
                <div><b>{d.payments.filter((p) => p.status.startsWith("Returned")).length}</b><small>returned payments · 12 m</small></div>
                <div><b>{cadShort(d.payments.reduce((a, p) => a + p.prepayment_cad, 0))}</b><small>prepaid · 12 m</small></div>
                <div><b>{d.offer ? d.offer.channel : "–"}</b><small>offer channel</small></div>
              </div>
            </div>

            <div className="px-acc-insights">
              {!d.insights.length && <p className="cd-empty">Nothing unusual at the servicer for this mortgage.</p>}
              {d.insights.map((i) => (
                <article key={`${i.code}-${i.live ? "live" : "feed"}`} className={`px-ins px-ins-${i.type === "Support" ? "support" : i.type === "Retain" ? "protect" : "service"}`}>
                  <header><Tag t={i.type} /><b>{i.title}</b>{i.live && <em className="px-new px-live-tag">live</em>}{i.new_signal && <em className="px-new">new to the book</em>}<code>{i.policy}</code></header>
                  <p>{i.detail}</p>
                  {!!i.done.length && <ul className="px-done">{i.done.map((x) => <li key={x}>✓ {x}</li>)}</ul>}
                  {!!i.actions.length && (
                    <div className="px-ins-actions">
                      {i.actions.map((a) => <button key={a} type="button" className="cd-btn" onClick={() => act.start(a, `${i.title} - ${i.evidence.slice(0, 3).join(", ")}`)}>{label(a)}…</button>)}
                    </div>
                  )}
                </article>
              ))}
            </div>

            <SorActionPanel a={act} system={d.profile.name} policy="RP-037 / RP-002" />

            {live?.connected && !!live.recent?.length && (
              <div className="px-live px-live-acc">
                <div className="px-live-head"><span className="px-live-dot" aria-hidden /><b>Live servicing events for this client</b>
                  <code>{live.source.eventstream} → {live.source.table}</code><small>refreshed {ago(live.queried_at)}</small></div>
                <ul className="px-live-feed">
                  {live.recent.slice(0, 8).map((r) => (
                    <li key={r.event_id} className={r.event_type === "payout.requested" || r.event_type === "pad.returned" ? "px-live-declined" : ""}>
                      <small>{ago(r.event_ts)}</small><span>{r.detail}{r.counterparty ? ` · ${r.counterparty}` : ""}{r.amount_cad ? ` · ${cad(r.amount_cad)}` : ""}</span><code>{r.event_type}</code>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="px-acc-grid">
              <div className="px-auths">
                <div className="cd-card-head"><h3>Payments · 12 months</h3><span>pre-authorised debits</span></div>
                <div className="px-table-wrap">
                  <table className="px-table">
                    <thead><tr><th>Due</th><th className="px-num">Scheduled</th><th>Status</th><th className="px-num">Prepayment</th></tr></thead>
                    <tbody>
                      {d.payments.map((p) => (
                        <tr key={p.due_date} className={p.status.startsWith("Returned") ? "px-declined px-flagged" : ""}>
                          <td>{p.due_date}</td><td className="px-num">{cad(p.scheduled_cad, 2)}</td>
                          <td>{p.status}{p.paid_on && p.paid_on !== p.due_date ? <><br /><small>paid {p.paid_on}</small></> : null}</td>
                          <td className="px-num">{p.prepayment_cad ? cad(p.prepayment_cad) : "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="px-side">
                <div className="cd-card-head"><h3>Payout requests</h3><span>{d.payouts.length || "none"}</span></div>
                <ul className="px-list">
                  {d.payouts.map((p) => (
                    <li key={p.request_id} className="px-stopped"><b>{p.request_id} · {p.status}</b><span>{cad(p.payout_amount_cad)}</span>
                      <small>{p.requested_by} · {p.purpose} · requested {p.requested_on} · statement due {p.statement_due}{p.prepayment_penalty_cad ? ` · penalty ${cad(p.prepayment_penalty_cad)}` : ""}</small></li>
                  ))}
                </ul>
                <div className="cd-card-head"><h3>Lender inquiries</h3><span>bureau triggers</span></div>
                <ul className="px-list">
                  {d.inquiries_withheld > 0 && <li><small>{d.inquiries_withheld} trigger(s) received - withheld, no consent on file (RP-038).</small></li>}
                  {!d.inquiries.length && !d.inquiries_withheld && <li><small className="cd-muted">None.</small></li>}
                  {d.inquiries.map((q) => <li key={q.inquiry_id}><b>{q.inquirer}</b><span>{q.inquiry_date}</span><small>{q.inquirer_type} · {q.bureau}</small></li>)}
                </ul>
                <div className="cd-card-head"><h3>Activity log</h3><span>approved actions</span></div>
                <ul className="px-list">
                  {!d.log.length && <li><small className="cd-muted">No actions yet.</small></li>}
                  {d.log.map((l) => <li key={l.reference}><b>{l.label}</b><span><code>{l.reference}</code></span>
                    <small>{when(l.ts)} · approved by {l.approver}{l.reason ? ` · ${l.reason}` : ""}</small></li>)}
                </ul>
              </div>
            </div>
            <p className="cd-foot">{d.profile.disclaimer}</p>
          </>}
        </div>}
      </section>
    </div>
  );
}
