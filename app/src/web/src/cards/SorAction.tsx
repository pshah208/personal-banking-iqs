/**
 * Shared system-of-record action panel: preview the vendor-style request and the
 * policy guards, capture a reason, require an explicit approval tick, then send.
 * Used by the mortgage servicing console; the card processor has its own copy
 * inline (Processor.tsx) with the same behaviour.
 */
import { useState } from "react";
import { apiPost } from "../api";
import type { ActionResult } from "./processorTypes";

export function useSorAction(endpoint: string, onDone: () => void) {
  const [preview, setPreview] = useState<ActionResult | null>(null);
  const [reason, setReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<ActionResult | null>(null);
  const [error, setError] = useState("");

  const start = async (action: string, why: string) => {
    setResult(null); setApproved(false); setReason(why); setError("");
    try { setPreview(await apiPost<ActionResult>(endpoint, { action, execute: false })); }
    catch (e) { setError(String(e)); }
  };
  const send = async () => {
    if (!preview) return;
    setSending(true);
    try {
      const r = await apiPost<ActionResult>(endpoint, { action: preview.action, reason, execute: true, confirm: true });
      setResult(r);
      if (r.executed) { setPreview(null); onDone(); }
    } catch (e) { setError(String(e)); }
    finally { setSending(false); }
  };
  return { preview, setPreview, reason, setReason, approved, setApproved, sending, result, error, start, send };
}

export function SorActionPanel({ a, system, policy }: { a: ReturnType<typeof useSorAction>; system: string; policy: string }) {
  const p = a.preview;
  return <>
    {a.error && <p className="cd-error" role="alert">{a.error}</p>}
    {p && (
      <div className="px-dialog" role="group" aria-label={`Approve: ${p.label}`}>
        <header><b>{p.label}</b><span className={`px-verdict px-verdict-${p.verdict}`}>{p.verdict === "ready" ? "Ready for approval" : "Blocked by policy"}</span></header>
        <p className="cd-muted">{p.effect}</p>
        <ul className="px-guards">
          {p.guards.map((g) => <li key={g.name} className={g.status}><code>{g.rule}</code> {g.name} - {g.detail}</li>)}
        </ul>
        <details open>
          <summary>Request to {system}</summary>
          <pre>{`${p.request.method} ${p.request.url}\n${Object.entries(p.request.headers).map(([h, v]) => `${h}: ${v}`).join("\n")}\n\n${JSON.stringify(p.request.body, null, 2)}`}</pre>
        </details>
        <label className="px-reason">Reason (kept in the audit log)
          <textarea value={a.reason} onChange={(e) => a.setReason(e.target.value)} rows={2} maxLength={300} />
        </label>
        <label className="px-approve">
          <input type="checkbox" checked={a.approved} onChange={(e) => a.setApproved(e.target.checked)} disabled={p.verdict !== "ready"} />
          I approve this change. It is sent under my name ({policy}).
        </label>
        <div className="px-dialog-btns">
          <button type="button" className="cd-btn cd-btn-ghost" onClick={() => a.setPreview(null)}>Cancel</button>
          <button type="button" className="cd-btn cd-btn-primary" disabled={!a.approved || p.verdict !== "ready" || a.sending} onClick={a.send}>
            {a.sending ? "Sending…" : "Approve and send"}
          </button>
        </div>
      </div>
    )}
    {a.result && (
      <div className={`px-result${a.result.executed ? "" : " px-result-bad"}`} role="status">
        {a.result.executed ? <>
          <b>✓ {a.result.label} - {a.result.response?.status} · {String(a.result.response?.body.reference ?? "")}</b>
          <small>{a.result.event?.type} · {a.result.event?.detail}</small>
          <pre>{JSON.stringify(a.result.response?.body, null, 2)}</pre>
        </> : <b>{a.result.error ?? "Not sent."}</b>}
      </div>
    )}
  </>;
}
