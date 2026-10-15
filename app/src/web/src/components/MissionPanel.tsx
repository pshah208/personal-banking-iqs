/**
 * Agent mission - the part of a product book that an API cannot do, run through a visible harness.
 *
 * Every book already shows deterministic KPIs, plays and templated drafts. This panel shows the
 * contrast ("an API alone returns" vs "only the agent can") and runs one client case end to end:
 *   1 plan → 2 governed packet (siloed plays) → 3 agent (live tool calls) → 4 guardrails
 *   → 5 Compliance Reviewer → 6 human decision (audit-logged).
 * Everything streams from POST /api/missions/{book}/run.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, streamSSE } from "../api";
import { Markdown } from "./Markdown";
import "./missions.css";

export type MissionBook = "mortgage" | "cards" | "banking" | "borrowing" | "investing" | "newcomers" | "insurance" | "security";
type Layer = "work" | "fabric" | "foundry" | "web";
const LAYER_NAME: Record<Layer, string> = { work: "Work IQ", fabric: "Fabric IQ", foundry: "Foundry IQ", web: "Web IQ" };

interface MissionCase {
  caseId: string; name: string; accountId: string; books: string[]; plays: number; why: string;
  colleagueThread: boolean; conflict: boolean; salesPaused: boolean; openFraudCase: boolean; wellnessBand: string;
}
interface Mission {
  book: MissionBook; bookTitle: string; asOf: string; agentName: string; reviewer: string; title: string; question: string;
  deliverable: string; owner: string; api: string[]; agentCan: string[]; policies: string[]; cases: MissionCase[];
  harness: { step: string; title: string; detail: string }[];
}
interface SiloPlay { book: string; account_id: string; play_type: string; play: string; eligibility: string; rationale: string; policy: string }
interface Check { rule: string; name: string; status: "pass" | "warn" | "block"; detail: string }
interface Step { state: "idle" | "running" | "done" | "skipped" | "failed" | "waiting"; title: string; detail: string; ms: number; data: any }
interface ToolCall { iq: Layer | null; tool: string; detail: string; error: string }
interface Decision { decision: string; by: string; at: string; note: string; runId: string; guardrails: string; review: string }

const STEP_ICON: Record<Step["state"], string> = { idle: "○", running: "◌", done: "✓", skipped: "–", failed: "✕", waiting: "●" };
const isEligible = (e: string) => e.trim().toLowerCase() === "eligible";
const secs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);

function useMission(book: MissionBook, active: boolean) {
  const [m, setM] = useState<Mission | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!active || m) return;
    apiGet<Mission>(`/api/missions/${book}`).then(setM).catch((e) => setErr(String(e)));
  }, [active, book, m]);
  return { m, err };
}

export function MissionPanel({ book, active, bankName }: { book: MissionBook; active: boolean; bankName?: string }) {
  const { m, err } = useMission(book, active);
  const storeKey = `pb.mission.${book}.open`;
  const [open, setOpen] = useState(() => (typeof localStorage === "undefined" ? true : localStorage.getItem(storeKey) !== "0"));
  const [caseId, setCaseId] = useState<string | null>(null);
  const [steps, setSteps] = useState<Record<string, Step>>({});
  const [tools, setTools] = useState<ToolCall[]>([]);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [answer, setAnswer] = useState("");
  const [review, setReview] = useState("");
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [copied, setCopied] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const t0 = useRef(0);
  const [, tick] = useState(0);

  useEffect(() => { try { localStorage.setItem(storeKey, open ? "1" : "0"); } catch { /* private mode */ } }, [open, storeKey]);
  useEffect(() => { if (m && !caseId && m.cases.length) setCaseId(m.cases[0].caseId); }, [m, caseId]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => tick((x) => x + 1), 250);
    return () => window.clearInterval(id);
  }, [running]);

  const mission = m;
  const selected = mission?.cases.find((c) => c.caseId === caseId) ?? null;
  const packet = steps.packet?.data ?? null;
  const plays: SiloPlay[] = packet?.plays ?? [];
  const guard = steps.guardrails?.data ?? null;
  const checks: Check[] = guard?.checks ?? [];
  const clientMsg: { subject: string; body: string } | null = guard?.clientMessage ?? null;
  const reviewVerdict: string = steps.review?.data?.verdict ?? "";
  const started = Object.keys(steps).length > 0;

  const reset = () => {
    setSteps({}); setTools([]); setLayers([]); setAnswer(""); setReview(""); setRunId(""); setError("");
    setDecision(null); setNote(""); setCopied(false);
  };

  const run = async () => {
    if (!selected || running) return;
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    reset();
    setRunning(true);
    t0.current = performance.now();
    await streamSSE(`/api/missions/${book}/run`, { caseId: selected.caseId }, {
      onIQ: (iq, st) => { if (st === "active") setLayers((l) => (l.includes(iq as Layer) ? l : [...l, iq as Layer])); },
      onToken: (t) => setAnswer((a) => a + t),
      onMessage: (t) => setAnswer(t),
      onError: (t, d) => setError(`${t} ${d}`.trim()),
      onDone: (p) => { if (typeof p.runId === "string") setRunId(p.runId); setRunning(false); },
      onEvent: (ev, p) => {
        if (ev === "harness") {
          if (p.runId) setRunId(p.runId);
          setSteps((s) => ({ ...s, [p.step]: { state: p.state, title: p.title, detail: p.detail, ms: p.ms, data: p.data ?? {} } }));
        } else if (ev === "tool_call") {
          setTools((t) => [...t, p as ToolCall]);
        } else if (ev === "review_token") {
          setReview((r) => r + (p.text ?? ""));
        } else if (ev === "review_message") {
          setReview(p.text ?? "");
        } else if (ev === "review_error") {
          setReview(`**${p.text ?? "Reviewer error"}**\n\n${p.detail ?? ""}`);
        }
      },
    }, ctrl.signal).catch((e) => { if (e?.name !== "AbortError") setError(String(e)); });
    setRunning(false);
  };

  const decide = async (d: "approve" | "send_back" | "escalate") => {
    if (!runId || !selected) return;
    setDeciding(true);
    try {
      setDecision(await apiPost<Decision>(`/api/missions/${book}/decision`, { runId, caseId: selected.caseId, decision: d, note }));
    } catch (e) {
      setError(`Could not record the decision: ${String(e)}`);
    } finally { setDeciding(false); }
  };

  const copyMsg = async () => {
    if (!clientMsg) return;
    const text = `${clientMsg.subject}\n\n${clientMsg.body}`.replace(/\bthe Bank\b/g, bankName || "the Bank");
    try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setCopied(false); }
  };

  const stats = useMemo(() => {
    const byLayer: Record<string, number> = {};
    tools.forEach((t) => { const k = t.iq ?? "other"; byLayer[k] = (byLayer[k] ?? 0) + 1; });
    return byLayer;
  }, [tools]);

  const verdict: string = guard?.verdict ?? "";
  const copyBlocked = verdict === "blocked" || reviewVerdict === "BLOCKED";
  const elapsed = running ? performance.now() - t0.current : (steps.human?.ms ?? steps.agent?.ms ?? 0);

  return (
    <section className={`ms-root${open ? "" : " ms-closed"}`} aria-labelledby={`ms-${book}-h`}>
      <header className="ms-head">
        <div className="ms-head-text">
          <div className="ms-eyebrow"><span className="ms-dot" aria-hidden />Agent mission · {mission?.bookTitle ?? "…"} · runs through the harness</div>
          <h2 id={`ms-${book}-h`}>{mission?.title ?? "Loading mission…"}</h2>
          {open && <p>{mission?.question}</p>}
        </div>
        <div className="ms-head-side">
          {mission && open && (
            <dl className="ms-deliv">
              <div><dt>Deliverable</dt><dd>{mission.deliverable}</dd></div>
              <div><dt>Hand-off</dt><dd>{mission.owner}</dd></div>
            </dl>
          )}
          <button type="button" className="ms-btn ms-btn-ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Collapse" : "Open mission"}
          </button>
        </div>
      </header>
      {err && <p className="ms-error" role="alert">Could not load the mission ({err}).</p>}

      {open && mission && (
        <>
          <div className="ms-contrast">
            <div className="ms-col ms-col-api">
              <h3><span className="ms-tag ms-tag-api">API</span> An API alone returns</h3>
              <ul>{mission.api.map((x) => <li key={x}>{x}</li>)}</ul>
              <small>Deterministic: Fabric IQ tables plus rules in code. No agent needed. Already on this page.</small>
            </div>
            <div className="ms-col ms-col-agent">
              <h3><span className="ms-tag ms-tag-agent">Agent</span> Only the agent can</h3>
              <ul>{mission.agentCan.map((x) => <li key={x}>{x}</li>)}</ul>
              <small>pb-mission-agent · Work IQ, Foundry IQ, Web IQ, Fabric IQ · bounded by the harness, a human decides</small>
            </div>
          </div>

          <div className="ms-pick">
            <div className="ms-pick-head">
              <h3>Pick a case</h3>
              <span>Cases where the books disagree, a colleague has written something, or sales are paused</span>
            </div>
            <div className="ms-cases" role="radiogroup" aria-label="Mission cases">
              {mission.cases.map((c) => (
                <button key={c.caseId} type="button" role="radio" aria-checked={caseId === c.caseId} disabled={running}
                        className={`ms-case${caseId === c.caseId ? " ms-on" : ""}`} onClick={() => { setCaseId(c.caseId); if (!running) reset(); }}>
                  <span className="ms-case-top"><b>{c.name}</b><code>{c.accountId}</code></span>
                  <span className="ms-case-why">{c.why}</span>
                  <span className="ms-case-tags">
                    {c.colleagueThread && <i className="ms-chip ms-chip-work">Colleague thread</i>}
                    {c.conflict && <i className="ms-chip ms-chip-conflict">Books disagree</i>}
                    {c.openFraudCase && <i className="ms-chip ms-chip-sec">Open fraud case</i>}
                    {c.salesPaused && !c.openFraudCase && <i className="ms-chip ms-chip-support">Sales paused</i>}
                    <i className="ms-chip">{c.books.length} books · {c.plays} plays</i>
                  </span>
                </button>
              ))}
            </div>
            <div className="ms-run-bar">
              <button type="button" className="ms-btn ms-btn-primary" disabled={!selected || running} onClick={run}>
                {running ? "Mission running…" : started ? "Run again" : "Run mission"}
              </button>
              {running && <button type="button" className="ms-btn ms-btn-ghost" onClick={() => { abort.current?.abort(); setRunning(false); }}>Stop</button>}
              <span className="ms-muted">
                {selected ? <>Case <b>{selected.name}</b> · {mission.agentName} with {mission.reviewer} · as of {mission.asOf}</> : "Choose a case"}
                {started && <> · {secs(Math.round(elapsed))}</>}
              </span>
            </div>
          </div>

          {started && (
            <div className="ms-run">
              <ol className="ms-steps" aria-label="Harness steps">
                {mission.harness.map((h, i) => {
                  const s = steps[h.step];
                  const state = s?.state ?? "idle";
                  return (
                    <li key={h.step} className={`ms-step ms-st-${state}`}>
                      <span className="ms-step-ico" aria-hidden>{STEP_ICON[state]}</span>
                      <div>
                        <b>{i + 1}. {h.title}</b>
                        <span>{s?.title ?? h.detail}</span>
                        {s?.detail && <small>{s.detail}</small>}
                        {h.step === "agent" && (tools.length > 0 || layers.length > 0) && (
                          <span className="ms-layer-row">
                            {(["work", "foundry", "web", "fabric"] as Layer[]).map((l) => (
                              <i key={l} className={`ms-layer ms-l-${l}${layers.includes(l) || stats[l] ? " ms-lit" : ""}`}>
                                {LAYER_NAME[l]}{stats[l] ? ` ×${stats[l]}` : ""}
                              </i>
                            ))}
                          </span>
                        )}
                      </div>
                      {s && state !== "running" && <em>{secs(s.ms)}</em>}
                    </li>
                  );
                })}
              </ol>

              <div className="ms-body">
                {error && <p className="ms-error" role="alert">{error}</p>}

                {plays.length > 0 && (
                  <details className="ms-block" open={!answer}>
                    <summary><b>What the APIs say, book by book</b><span>{plays.length} siloed plays · deterministic · Fabric IQ</span></summary>
                    <div className="ms-table-wrap">
                      <table className="ms-table">
                        <thead><tr><th>Book</th><th>Play</th><th>Eligibility</th><th>Rule's reason</th></tr></thead>
                        <tbody>
                          {plays.map((p, i) => (
                            <tr key={i} className={isEligible(p.eligibility) ? "" : "ms-row-blocked"}>
                              <td>{p.book}<small>{p.account_id}</small></td>
                              <td><span className={`ms-pt ms-pt-${p.play_type.toLowerCase()}`}>{p.play_type}</span> {p.play}</td>
                              <td>{p.eligibility}</td>
                              <td>{p.rationale}{p.policy && <code> {p.policy}</code>}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="ms-muted ms-small">Each book answers alone. None of them knows what the others recommend, what colleagues wrote, or what changed this week.</p>
                  </details>
                )}

                {(tools.length > 0 || steps.agent) && (
                  <details className="ms-block" open={running}>
                    <summary><b>Agent trace</b><span>{tools.length} tool call{tools.length === 1 ? "" : "s"} · every call the agent made, in order</span></summary>
                    <ol className="ms-trace">
                      {tools.map((t, i) => (
                        <li key={i} className={t.error ? "ms-trace-err" : ""}>
                          <i className={`ms-layer ms-lit ms-l-${t.iq ?? "other"}`}>{t.iq ? LAYER_NAME[t.iq] : "Tool"}</i>
                          <code>{t.tool}</code>
                          <span>{t.detail}</span>
                          {t.error && <small>{t.error}</small>}
                        </li>
                      ))}
                      {running && <li className="ms-trace-wait"><span className="ms-skel" /></li>}
                    </ol>
                  </details>
                )}

                {(answer || steps.agent?.state === "running") && (
                  <article className="ms-block ms-answer" aria-live="polite" aria-busy={running && !steps.guardrails}>
                    <div className="ms-answer-head"><b>Agent's decision package</b><span>{mission.agentName} · for {mission.owner}</span></div>
                    {answer ? <Markdown text={answer} /> : <div className="ms-skel-lines"><span className="ms-skel" /><span className="ms-skel short" /></div>}
                  </article>
                )}

                {checks.length > 0 && (
                  <div className="ms-block">
                    <div className="ms-block-head">
                      <b>Guardrails over the agent's output</b>
                      <span className={`ms-verdict ms-v-${verdict}`}>{verdict === "pass" ? "Pass" : verdict === "blocked" ? "Blocked" : "Needs a human"}</span>
                    </div>
                    <ul className="ms-checks">
                      {checks.map((c, i) => (
                        <li key={i} className={`ms-ck ms-ck-${c.status}`}>
                          <span aria-hidden>{c.status === "pass" ? "✓" : c.status === "warn" ? "!" : "✕"}</span>
                          <b>{c.name}</b><code>{c.rule}</code><small>{c.detail}</small>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {(review || steps.review) && (
                  <div className="ms-block">
                    <div className="ms-block-head">
                      <b>Compliance Reviewer</b>
                      <span className={`ms-verdict ms-v-${reviewVerdict === "PASS" ? "pass" : reviewVerdict === "BLOCKED" ? "blocked" : reviewVerdict ? "needs_approval" : "none"}`}>
                        {steps.review?.state === "skipped" ? "Skipped" : reviewVerdict || (steps.review?.state === "running" ? "Reviewing…" : "-")}
                      </span>
                    </div>
                    {steps.review?.state === "skipped" && <p className="ms-muted ms-small">{steps.review.title}: {steps.review.detail}</p>}
                    {review && <div className="ms-review"><Markdown text={review.replace(/^\s*VERDICT:[^\n]*\n?/i, "")} /></div>}
                  </div>
                )}

                {steps.human && (
                  <div className="ms-block ms-human">
                    <div className="ms-block-head"><b>Your decision</b><span>The agent prepared this. You decide. Nothing is sent from here.</span></div>
                    {!decision ? (
                      <>
                        <label className="ms-note"><span>Note for the audit record (optional)</span>
                          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Agreed - booking the verified call-back today" />
                        </label>
                        <div className="ms-human-actions">
                          <button type="button" className="ms-btn ms-btn-primary" disabled={deciding} onClick={() => decide("approve")}>
                            {verdict === "blocked" ? "Approve plan (not the client copy)" : "Approve plan"}
                          </button>
                          <button type="button" className="ms-btn" disabled={deciding} onClick={() => decide("send_back")}>Send back</button>
                          <button type="button" className="ms-btn" disabled={deciding} onClick={() => decide("escalate")}>Escalate to {mission.owner.split("→").pop()?.trim()}</button>
                          {clientMsg && (
                            <button type="button" className="ms-btn ms-btn-ghost" disabled={copyBlocked} onClick={copyMsg}
                                    title={copyBlocked ? "Blocked by the guardrails or the reviewer" : "Copy the client message to paste into your approved channel"}>
                              {copied ? "Copied ✓" : "Copy client message"}
                            </button>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="ms-decided">
                        <b>{decision.decision === "approve" ? "Approved" : decision.decision === "send_back" ? "Sent back" : "Escalated"}</b>
                        {" "}by {decision.by} at {new Date(decision.at).toLocaleString("en-CA")} · run <code>{decision.runId}</code>
                        {" "}· guardrails {decision.guardrails || "-"} · reviewer {decision.review || "-"}{decision.note && <> · "{decision.note}"</>}
                        <small>Written to the audit log. {decision.decision === "send_back" ? "Change the case or run again." : ""}</small>
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
