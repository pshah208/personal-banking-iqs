/**
 * Card processor - the simulated system of record for the Cards book.
 *
 *   ProcessorPortfolio  the processor's daily files, KPIs only it can compute,
 *                       insights the monthly book cannot see, and the event stream.
 *   ProcessorAccount    one card at the processor: status and controls, insights
 *                       with servicing actions, 30 days of authorisations,
 *                       card-on-file billers, disputes and the audit log.
 *
 * Actions go through a vendor-style API (pb_processor.py): preview the request
 * and the policy guards, then a colleague explicitly approves before it is sent.
 * Nothing leaves the BFF - it is a simulator over synthetic data.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../api";
import { PlayTag } from "./CardAccount";
import {
  ENTRY_LABEL, INSIGHT_LABEL,
  type ActionResult, type Authorization, type LiveStream, type ProcessorAccount as Detail, type ProcessorInsight, type ProcessorOverview,
} from "./processorTypes";
import { cad, cadShort } from "./types";
import "./processorView.css";

const when = (ts: string) => ts.replace("T", " ").replace(/:\d\dZ?$/, "").replace(/Z$/, "");

function SimBadge({ name }: { name: string }) {
  return <span className="px-sor" title="Simulated system of record - synthetic data, not connected to any vendor"><i aria-hidden />{name} · simulated</span>;
}

function InsightTag({ t }: { t: ProcessorInsight["type"] }) {
  return t === "Service" ? <span className="px-tag px-tag-service">Service</span> : <PlayTag t={t} />;
}

/* ------------------------------------------------------------- live stream */
const ago = (iso?: string) => {
  if (!iso) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};

function useLive(active: boolean, account = "") {
  const [live, setLive] = useState<LiveStream | null>(null);
  useEffect(() => {
    if (!active) return;
    let stop = false;
    const tick = () => apiGet<LiveStream>(`/api/cards/processor/live${account ? `?account=${encodeURIComponent(account)}` : ""}`)
      .then((r) => { if (!stop) setLive(r); }).catch(() => undefined);
    tick();
    const h = window.setInterval(tick, 10000);
    return () => { stop = true; window.clearInterval(h); };
  }, [active, account]);
  return live;
}

function LivePanel({ active, onOpen }: { active: boolean; onOpen: (aid: string) => void }) {
  const live = useLive(active);
  if (!live) return null;
  if (!live.connected) {
    return (
      <div className="px-live px-live-off" role="note">
        <b>Live stream not connected</b>
        <span>Fabric Eventstream <code>{live.source.eventstream}</code> → Eventhouse <code>{live.source.eventhouse}</code>.
          Run <code>data/fabric-iq/deploy_realtime.py</code> and set <code>PROCESSOR_KQL_URI</code> / <code>PROCESSOR_KQL_DB</code> on the BFF.</span>
        {live.reason && <small>{live.reason}</small>}
      </div>
    );
  }
  const k = live.kpis_15m ?? {};
  const d = live.kpis_24h ?? {};
  return (
    <div className="px-live" aria-label="Live processor stream">
      <div className="px-live-head">
        <span className="px-live-dot" aria-hidden /><b>Live · Fabric Eventstream → Eventhouse</b>
        <code>{live.source.eventstream} → {live.source.database}.{live.source.table}</code>
        <small>last event {ago(k.last_event || d.last_event)} · refreshed {ago(live.queried_at)}</small>
      </div>
      <div className="px-live-kpis">
        <div><b>{k.events ?? 0}</b><small>authorisations · 15 min</small></div>
        <div><b>{k.events ? `${k.approval_rate}%` : "–"}</b><small>approved · 15 min</small></div>
        <div><b>{k.events ? `${k.cnp_share}%` : "–"}</b><small>card not present</small></div>
        <div className={d.fraud_declines ? "px-hot" : ""}><b>{d.fraud_declines ?? 0}</b><small>fraud declines · 24 h</small></div>
        <div><b>{d.limit_declines ?? 0}</b><small>declined at limit · 24 h</small></div>
        <div><b>{d.events ?? 0}</b><small>events · 24 h · {d.accounts ?? 0} cards</small></div>
      </div>
      <div className="px-live-grid">
        <div>
          <h4>Card testing detected (KQL · CardTestingLive)</h4>
          {!live.card_testing?.length && <p className="cd-muted">No pattern in the last hour.</p>}
          <ul className="px-live-alerts">
            {live.card_testing?.map((t) => (
              <li key={t.account_id}>
                <button type="button" onClick={() => onOpen(t.account_id)}>
                  <b>{t.customer_name || t.account_id}</b>
                  <span>{t.attempts} attempts under $5 · {t.approved} approved · {t.merchants} merchants · {Array.isArray(t.countries) ? t.countries.join(", ") : t.countries}</span>
                  <small>{t.account_id} · last {ago(t.last_seen)} · max risk {t.max_risk}</small>
                </button>
              </li>
            ))}
          </ul>
          {!!live.declines_at_limit?.length && <>
            <h4>Declined at the limit (DeclinesAtLimitLive)</h4>
            <ul className="px-live-alerts px-live-support">
              {live.declines_at_limit.map((x) => (
                <li key={x.account_id}><button type="button" onClick={() => onOpen(x.account_id)}>
                  <b>{x.customer_name || x.account_id}</b><span>{x.declines} declines · {cad(x.amount_cad, 0)} · support, never a limit increase</span>
                  <small>{x.account_id} · last {ago(x.last_seen)}</small></button></li>
              ))}
            </ul>
          </>}
        </div>
        <div>
          <h4>Latest authorisations</h4>
          <ul className="px-live-feed">
            {live.recent?.map((r) => (
              <li key={r.auth_id} className={r.decision === "Declined" ? "px-live-declined" : ""}>
                <small>{ago(r.event_ts)}</small>
                <span><b>{r.customer_name || r.account_id}</b> · {r.merchant_name} ({r.merchant_country}) · {cad(r.amount_cad, 2)}</span>
                <code>{r.response_code} {r.decision}</code>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- portfolio */
export function ProcessorPortfolio({ active, onOpen }: { active: boolean; onOpen: (aid: string) => void }) {
  const [data, setData] = useState<ProcessorOverview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    apiGet<ProcessorOverview>("/api/cards/processor")
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => { if (active && !data) load(); }, [active, data, load]);

  const reset = async () => {
    setBusy(true);
    try { await apiPost("/api/cards/processor/reset", {}); } catch { /* shown on reload */ }
    load();
  };

  const k = data?.kpis;
  const maxDecline = Math.max(1, ...(data?.declines_by_code ?? []).map((d) => d.count));

  return (
    <section className="cd-card px-portfolio" id="cd-sec-processor" aria-labelledby="px-h" tabIndex={-1}>
      <div className="px-head">
        <div>
          <div className="cd-eyebrow">System of record · card processor</div>
          <h2 id="px-h">What the processor sees that the monthly book does not</h2>
          <p className="cd-muted">
            Authorisations, declines, card controls, billers on file and disputes from the issuer processor, landed daily in OneLake
            and joined to the card book. Insights below change who you call first.
          </p>
        </div>
        <div className="px-head-meta">
          {data && <SimBadge name={data.profile.name} />}
          {data && <code className="px-api" title={data.profile.style}>{data.profile.api_base}</code>}
          <span className="px-head-btns">
            <button type="button" className="cd-btn cd-btn-ghost" onClick={load} disabled={busy}>Refresh</button>
            <button type="button" className="cd-btn cd-btn-ghost" onClick={reset} disabled={busy}
                    title="Clear simulated actions, disputes and events">Reset simulator</button>
          </span>
        </div>
      </div>

      {error && <p className="cd-error" role="alert">Could not load the processor feed ({error}).</p>}
      {!data && !error && <div className="cd-skel-row" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="cd-skel cd-skel-chart" />)}</div>}

      {data && k && <>
        <ol className="px-pipeline" aria-label="Integration path">
          <li><b>{data.profile.name}</b><small>{data.profile.auth_format} · {data.profile.events}</small></li>
          <li><b>Azure API Management</b><small>front door for servicing APIs · managed identity</small></li>
          <li><b>OneLake landing zone</b><small>Files/processor/* · daily files + fraud-score stream</small></li>
          <li><b>Fabric IQ</b><small>proc_* tables joined to card_accounts</small></li>
          <li><b>Cards book &amp; agents</b><small>insights · human-approved actions · audit</small></li>
        </ol>

        <LivePanel active={active} onOpen={onOpen} />

        <div className="px-feeds" aria-label="Files delivered by the processor">
          {data.feeds.map((f) => (
            <div key={f.file_id} className={`px-feed${f.warnings ? " px-warn" : ""}`} title={`${f.description} · ${f.format} → ${f.landing}`}>
              <b>{f.feed}</b>
              <span>{f.records.toLocaleString()} records</span>
              <small>{f.received === "continuous" ? "streaming" : `received ${f.received.slice(11)}`} · {f.status}</small>
            </div>
          ))}
        </div>

        <div className="px-kpis">
          <div className="px-kpi"><small>Approval rate</small><b>{k.approval_rate}%</b><span>{k.auths_30d.toLocaleString()} authorisations · 30 d</span></div>
          <div className="px-kpi"><small>Card not present</small><b>{k.cnp_share}%</b><span>{k.cross_border_share}% cross-border · {k.wallet_share}% wallet</span></div>
          <div className="px-kpi px-kpi-protect"><small>Card testing</small><b>{k.card_testing}</b>
            <span>{k.unseen_by_book ? <strong>{k.unseen_by_book} not flagged in the book</strong> : "all flagged in the book"}</span></div>
          <div className="px-kpi px-kpi-support"><small>Declines at limit</small><b>{k.declines_at_limit}</b><span>accounts · support, never a CLI</span></div>
          <div className="px-kpi"><small>Disputes open</small><b>{k.disputes_open}</b><span>{data.disputes_by_stage.map((d) => `${d.count} ${d.stage.toLowerCase()}`).slice(0, 2).join(" · ")}</span></div>
          <div className="px-kpi"><small>Billers stopped</small><b>{k.billers_stopped}</b><span>card-on-file merchants gone quiet</span></div>
          <div className="px-kpi"><small>Cards expiring</small><b>{k.expiring_60d}</b><span>within 60 days</span></div>
          <div className="px-kpi"><small>Alerts off</small><b>{k.alerts_off}</b><span>{cad(k.fx_fees_30d, 0)} FX fees in 30 d</span></div>
        </div>

        <div className="px-grid">
          <div className="px-col">
            <div className="cd-card-head"><h3>Insights only the processor can give</h3><span>click to open the card</span></div>
            <p className="px-counts">
              {data.insight_counts.map((c) => <span key={c.code} className="cd-tag">{INSIGHT_LABEL[c.code] ?? c.code} · {c.count}</span>)}
            </p>
            <ul className="px-insights">
              {data.insights.map((i, n) => (
                <li key={`${i.account_id}-${i.code}-${n}`}>
                  <button type="button" className="px-insight" onClick={() => i.account_id && onOpen(i.account_id)}>
                    <InsightTag t={i.type} />
                    <span className="px-insight-main">
                      <b>{i.title}{i.new_signal && <em className="px-new">new to the book</em>}</b>
                      <small>{i.customer_name} · {i.account_id} · {i.product_name}</small>
                    </span>
                    <span className="px-insight-side">
                      {i.value_cad > 0 && <b>{cadShort(i.value_cad)}</b>}
                      <code>{i.policy}</code>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="px-col">
            <div className="cd-card-head"><h3>Declines by reason</h3><span>response codes · 30 days</span></div>
            <ul className="px-bars">
              {data.declines_by_code.map((d) => (
                <li key={d.code}>
                  <span><code>{d.code}</code> {d.text}</span>
                  <i aria-hidden><i style={{ width: `${(d.count / maxDecline) * 100}%` }} className={d.code === "59" ? "px-bar-fraud" : d.code === "51" ? "px-bar-limit" : ""} /></i>
                  <b>{d.count}</b>
                </li>
              ))}
            </ul>
            <div className="cd-card-head px-events-head"><h3>Event stream</h3><span>processor webhooks · newest first</span></div>
            <ul className="px-events">
              {data.events.map((e) => (
                <li key={e.id} className={e.source === "feed" ? "" : "px-event-live"}>
                  <code>{e.type}</code>
                  <span>{e.detail}</span>
                  <small>{e.account_id} · {when(e.ts)}</small>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <p className="cd-foot">{data.profile.disclaimer} Data as of {data.as_of}.</p>
      </>}
    </section>
  );
}

/* ------------------------------------------------------------------ account */
type AuthFilter = "All" | "Flagged" | "Declined" | "Online" | "Cross-border";
const AUTH_FILTERS: AuthFilter[] = ["All", "Flagged", "Declined", "Online", "Cross-border"];
const keep = (f: AuthFilter, a: Authorization) =>
  f === "All" || (f === "Flagged" && a.flagged) || (f === "Declined" && a.decision === "Declined") ||
  (f === "Online" && a.channel === "CNP") || (f === "Cross-border" && a.merchant_country !== "CA");

export function ProcessorAccount({ aid }: { aid: string }) {
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(true);
  const [filter, setFilter] = useState<AuthFilter>("All");
  const [preview, setPreview] = useState<ActionResult | null>(null);
  const [reason, setReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<ActionResult | null>(null);
  const live = useLive(open, aid);

  const load = useCallback(() => {
    apiGet<Detail>(`/api/cards/account/${aid}/processor`).then((r) => { setD(r); setError(""); }).catch((e) => setError(String(e)));
  }, [aid]);
  useEffect(() => { setD(null); setPreview(null); setResult(null); load(); }, [load]);

  const auths = useMemo(() => (d?.authorizations ?? []).filter((a) => keep(filter, a)), [d, filter]);
  const label = (id: string) => d?.actions.find((x) => x.id === id)?.label ?? id;

  const start = async (action: string, insight: ProcessorInsight) => {
    setResult(null); setApproved(false);
    setReason(`${insight.title} - evidence ${insight.evidence.slice(0, 4).join(", ")}${insight.evidence.length > 4 ? "…" : ""}`);
    try { setPreview(await apiPost<ActionResult>(`/api/cards/account/${aid}/processor/action`, { action, execute: false })); }
    catch (e) { setError(String(e)); }
  };

  const send = async () => {
    if (!preview) return;
    setSending(true);
    try {
      const r = await apiPost<ActionResult>(`/api/cards/account/${aid}/processor/action`,
        { action: preview.action, reason, execute: true, confirm: true });
      setResult(r);
      if (r.executed) { setPreview(null); load(); }
    } catch (e) { setError(String(e)); }
    finally { setSending(false); }
  };

  const c = d?.controls;
  const liveTesting = live?.card_testing?.find((t) => t.account_id === aid);
  return (
    <section className={`cd-360 px-account${open ? "" : " cd-360-closed"}`} aria-label="Card processor">
      <button type="button" className="cd-360-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>Card processor</span><small>authorisations · controls · billers · disputes · servicing actions</small>
        {d && <SimBadge name={d.profile.name} />}<i aria-hidden>{open ? "−" : "+"}</i>
      </button>
      {open && <div className="px-acc">
        {error && <p className="cd-error" role="alert">Processor unavailable ({error}).</p>}
        {!d && !error && <div className="cd-skel" aria-busy="true" />}
        {d && c && <>
          <div className="px-acc-top">
            <div className={`px-cardtile px-status-${c.card_status.split(" ")[0].toLowerCase()}`}>
              <small>{c.network} · {c.masked_pan}</small>
              <b>{c.card_status}</b>
              <span>expires {c.card_expiry}{c.new_masked_pan ? ` · new card ${c.new_masked_pan.slice(-4)} exp ${c.new_card_expiry}` : ""}</span>
              <ul className="px-ctl">
                {([["Online", c.ecommerce_enabled], ["International", c.international_enabled], ["Contactless", c.contactless_enabled],
                   ["Alerts", c.alerts_enrolled], ["Account Updater", c.account_updater_enrolled]] as const).map(([n, v]) => (
                  <li key={n} className={v === "Y" ? "on" : "off"}>{n} {v === "Y" ? "on" : "off"}</li>
                ))}
                <li className="on">{c.wallet_tokens} wallet token{c.wallet_tokens === 1 ? "" : "s"}</li>
              </ul>
            </div>
            <div className="px-acc-sum">
              <div><b>{d.summary.auths}</b><small>authorisations</small></div>
              <div><b>{d.summary.declined}</b><small>declined</small></div>
              <div><b>{d.summary.cnp}</b><small>online / on file</small></div>
              <div><b>{d.summary.cross_border}</b><small>cross-border</small></div>
              <div><b>{cadShort(d.summary.spend_approved)}</b><small>approved · 30 d</small></div>
            </div>
          </div>

          <div className="px-acc-insights">
            {!d.insights.length && <p className="cd-empty">Nothing unusual at the processor for this card.</p>}
            {d.insights.map((i) => (
              <article key={i.code} className={`px-ins px-ins-${i.type.toLowerCase()}`}>
                <header>
                  <InsightTag t={i.type} /><b>{i.title}</b>
                  {i.new_signal && <em className="px-new">new to the book</em>}
                  <code>{i.policy}</code>
                </header>
                <p>{i.detail}</p>
                {i.play && <small className="cd-muted">Links to the <b>{i.play}</b> play.</small>}
                {!!i.done.length && <ul className="px-done">{i.done.map((x) => <li key={x}>✓ {x}</li>)}</ul>}
                {!!i.actions.length && (
                  <div className="px-ins-actions">
                    {i.actions.map((a) => (
                      <button key={a} type="button" className="cd-btn" onClick={() => start(a, i)}>{label(a)}…</button>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>

          {live?.connected && (
            <div className="px-live px-live-acc">
              <div className="px-live-head">
                <span className="px-live-dot" aria-hidden /><b>Live stream for this card</b>
                <code>{live.source.eventstream} → {live.source.table}</code>
                <small>refreshed {ago(live.queried_at)}</small>
              </div>
              {liveTesting && (
                <p className="px-live-alert-inline">
                  <b>Card testing in progress:</b> {liveTesting.attempts} attempts under $5 in the last hour, {liveTesting.approved} approved,
                  max risk {liveTesting.max_risk}. Lock the card now, then reissue (RP-035).
                </p>
              )}
              {!live.recent?.length ? <p className="cd-muted">No live authorisations for this card yet.</p> : (
                <ul className="px-live-feed">
                  {live.recent.slice(0, 8).map((r) => (
                    <li key={r.auth_id} className={r.decision === "Declined" ? "px-live-declined" : ""}>
                      <small>{ago(r.event_ts)}</small>
                      <span>{r.merchant_name} ({r.merchant_country}) · {cad(r.amount_cad, 2)} · {r.channel}</span>
                      <code>{r.response_code} {r.decision} · risk {r.risk_score}</code>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {preview && (
            <div className="px-dialog" role="group" aria-label={`Approve: ${preview.label}`}>
              <header><b>{preview.label}</b><span className={`px-verdict px-verdict-${preview.verdict}`}>{preview.verdict === "ready" ? "Ready for approval" : "Blocked by policy"}</span></header>
              <p className="cd-muted">{preview.effect}</p>
              <ul className="px-guards">
                {preview.guards.map((g) => <li key={g.name} className={g.status}><code>{g.rule}</code> {g.name} - {g.detail}</li>)}
              </ul>
              <details open>
                <summary>Request to {d.profile.name}</summary>
                <pre>{`${preview.request.method} ${preview.request.url}\n${Object.entries(preview.request.headers).map(([h, v]) => `${h}: ${v}`).join("\n")}\n\n${JSON.stringify(preview.request.body, null, 2)}`}</pre>
              </details>
              <label className="px-reason">Reason (kept in the audit log)
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={300} />
              </label>
              <label className="px-approve">
                <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} disabled={preview.verdict !== "ready"} />
                I approve this change. It is sent under my name (RP-035).
              </label>
              <div className="px-dialog-btns">
                <button type="button" className="cd-btn cd-btn-ghost" onClick={() => setPreview(null)}>Cancel</button>
                <button type="button" className="cd-btn cd-btn-primary" disabled={!approved || preview.verdict !== "ready" || sending} onClick={send}>
                  {sending ? "Sending…" : "Approve and send"}
                </button>
              </div>
            </div>
          )}
          {result && (
            <div className={`px-result${result.executed ? "" : " px-result-bad"}`} role="status">
              {result.executed ? <>
                <b>✓ {result.label} - {result.response?.status} · {String(result.response?.body.reference ?? "")}</b>
                <small>{result.event?.type} · {result.event?.detail}</small>
                <pre>{JSON.stringify(result.response?.body, null, 2)}</pre>
              </> : <b>{result.error ?? "Not sent."}</b>}
            </div>
          )}

          <div className="px-acc-grid">
            <div className="px-auths">
              <div className="cd-card-head">
                <h3>Authorisations · 30 days</h3>
                <div className="cd-chips" role="group" aria-label="Filter authorisations">
                  {AUTH_FILTERS.map((f) => (
                    <button key={f} type="button" className="cd-chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                      {f}<b>{(d.authorizations ?? []).filter((a) => keep(f, a)).length}</b>
                    </button>
                  ))}
                </div>
              </div>
              <div className="px-table-wrap">
                <table className="px-table">
                  <thead><tr><th>Time</th><th>Merchant</th><th>Entry</th><th className="px-num">Amount</th><th>Response</th><th className="px-num">Risk</th></tr></thead>
                  <tbody>
                    {auths.map((a) => (
                      <tr key={a.auth_id} className={`${a.flagged ? "px-flagged" : ""}${a.decision === "Declined" ? " px-declined" : ""}`}>
                        <td><small>{when(a.auth_ts)}</small><br /><code>{a.auth_id}</code></td>
                        <td>{a.merchant_name}<br /><small>{a.mcc} {a.mcc_desc} · {a.merchant_country}</small></td>
                        <td>{ENTRY_LABEL[a.pos_entry_mode] ?? a.pos_entry_mode}{a.wallet ? " · wallet" : ""}<br /><small>{a.channel}{a.three_ds === "Y" ? " · 3DS" : ""}</small></td>
                        <td className="px-num">{cad(a.amount_cad, 2)}{a.txn_currency !== "CAD" && <><br /><small>{a.txn_currency}{a.fx_fee_cad ? ` · fee ${cad(a.fx_fee_cad, 2)}` : ""}</small></>}</td>
                        <td><code>{a.response_code}</code> {a.decision}<br /><small>{a.response_text}</small></td>
                        <td className={`px-num${a.risk_score >= 850 ? " px-risk-hi" : a.risk_score >= 600 ? " px-risk-mid" : ""}`}>{a.risk_score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="px-side">
              <div className="cd-card-head"><h3>Billers on file</h3><span>{d.card_on_file.length} recurring</span></div>
              <ul className="px-list">
                {d.card_on_file.map((b) => (
                  <li key={b.merchant_name} className={b.status === "Stopped" ? "px-stopped" : ""}>
                    <b>{b.merchant_name}</b><span>{cad(b.amount_cad, 2)} / mo</span>
                    <small>{b.status === "Stopped" ? `stopped - last billed ${b.last_billed}` : `last billed ${b.last_billed}`} · updater {b.account_updater === "Y" ? "on" : "off"}</small>
                  </li>
                ))}
              </ul>
              <div className="cd-card-head"><h3>Disputes</h3><span>{d.disputes.length || "none"}</span></div>
              <ul className="px-list">
                {d.disputes.map((x) => (
                  <li key={x.dispute_id}>
                    <b>{x.dispute_id} · {x.stage}</b><span>{cad(x.amount_cad, 2)}</span>
                    <small>{x.reason_code} {x.reason} · opened {x.opened}{x.response_due ? ` · due ${x.response_due}` : ""}{x.provisional_credit === "Y" ? " · provisional credit" : ""}</small>
                  </li>
                ))}
              </ul>
              <div className="cd-card-head"><h3>Activity log</h3><span>approved actions</span></div>
              <ul className="px-list">
                {!d.log.length && <li><small className="cd-muted">No actions yet.</small></li>}
                {d.log.map((l) => (
                  <li key={l.reference}><b>{l.label}</b><span><code>{l.reference}</code></span>
                    <small>{when(l.ts)} · approved by {l.approver}{l.reason ? ` · ${l.reason}` : ""}</small></li>
                ))}
              </ul>
            </div>
          </div>
          <p className="cd-foot">{d.profile.disclaimer}</p>
        </>}
      </div>}
    </section>
  );
}
