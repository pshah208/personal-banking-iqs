/**
 * Customer workspace - Customer 360, next-best action, outreach and review.
 *
 *   1 Next-best action   Support > Retain > Deepen. Blocked actions stay
 *                        visible with the reason; a vulnerable client gets the
 *                        support-first banner and no offer rail (RP-012).
 *   2 Draft outreach     deterministic draft, editable, with live guardrail
 *                        checks (RP-011 consent, RP-012, RP-013, RP-016).
 *   3 Compliance review  the Compliance Reviewer agent judges tone and
 *                        implied promises; it can block, never approve.
 *   4 Wrap-up            conversation note (.docx) and an Outlook draft with
 *                        no recipient - nothing is ever sent.
 *
 * The AI panel on the right is the live main agent, scoped by the customer's
 * suggested prompts.
 */
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from "react";
import { apiDownload, apiGet, apiPost, streamChat, streamSSE } from "../api";
import { Markdown } from "../components/Markdown";
import { SplitHandle, SplitRail, SplitToggle, type ChatSplit } from "../components/ChatSplit";
import { Lock } from "./CustomersView";
import { HeatStrip, WellnessPill } from "./WellnessView";
import {
  GDS_GUIDE, TDS_GUIDE, cad, isEligible, num, signalsToStrip,
  type Action, type Channel, type Check, type Customer360, type Draft, type Verdict,
} from "./types";
import "./customers.css";

type Step = 1 | 2 | 3 | 4;
const STEPS: { id: Step; label: string }[] = [
  { id: 1, label: "Next-best action" }, { id: 2, label: "Draft outreach" },
  { id: 3, label: "Compliance review" }, { id: 4, label: "Wrap-up" },
];
const TYPE_ORDER: Record<string, number> = { Support: 0, Retain: 1, Deepen: 2 };
const CHANNELS: Channel[] = ["Email", "SMS", "Phone"];
const VERDICT_LABEL: Record<Verdict, string> = { pass: "Ready", needs_approval: "Needs approval", blocked: "Blocked" };

const GROUPS = ["Lending", "Day-to-day", "Investing", "Protection"] as const;
type Group = (typeof GROUPS)[number];
function groupOf(category: string, productId: string): Group {
  if (productId === "PRD-INS" || /insur|protect/i.test(category)) return "Protection";
  if (["PRD-TFSA", "PRD-RSP"].includes(productId) || /invest/i.test(category)) return "Investing";
  if (["PRD-MTG", "PRD-HEL", "PRD-REL"].includes(productId) || /lend/i.test(category)) return "Lending";
  return "Day-to-day";
}

const fmtDate = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return y ? new Date(y, m - 1, d, 12).toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" }) : iso;
};

/* ------------------------------------------------------------------ AI panel */
function AiPanel({ c, id, hidden }: { c: Customer360; id: string; hidden?: boolean }) {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [asked, setAsked] = useState("");
  const [layers, setLayers] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const thread = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const ask = async (question: string, label?: string) => {
    if (!question.trim() || busy) return;
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setAsked(label ?? question); setAnswer(""); setLayers([]); setBusy(true);
    await streamChat(question, thread.current, {
      onStatus: setStatus,
      onIQ: (iq) => setLayers((l) => (l.includes(iq) ? l : [...l, iq])),
      onToken: (t) => setAnswer((a) => a + t),
      onMessage: (t) => setAnswer(t),
      onError: (t, d) => setAnswer(`**${t}**\n\n${d}`),
      onDone: (p) => {
        setBusy(false); setStatus("");
        if (typeof p.threadId === "string") thread.current = p.threadId;
      },
    }, ctrl.signal).catch(() => setBusy(false));
  };

  return (
    <aside className="cu-ai" id={id} hidden={hidden} aria-label={`AI assistant for ${c.name}`}>
      <header>
        <span className="cu-ai-mark" aria-hidden>✦</span>
        <div><b>Advisor AI</b><small>Live agent · {c.name}</small></div>
      </header>
      <div className="cu-ai-prompts">
        {c.prompts.map((p) => (
          <button key={p.label} type="button" disabled={busy} onClick={() => ask(p.prompt, p.label)}>{p.label} <span aria-hidden>↗</span></button>
        ))}
      </div>
      <div className="cu-ai-body" aria-live="polite">
        {!asked && <p className="cu-muted">Pick a prompt or ask anything about {c.name.split(" ")[0]}'s household. Answers are grounded in Fabric IQ and policy, under your identity.</p>}
        {asked && <div className="cu-ai-q">{asked}</div>}
        {layers.length > 0 && <div className="cu-ai-layers">{layers.map((l) => <span key={l} className={`cu-ai-layer l-${l}`}>{l} IQ</span>)}</div>}
        {busy && !answer && <div aria-busy="true"><div className="cu-skel cu-skel-line" /><div className="cu-skel cu-skel-line short" /><small className="cu-muted">{status}</small></div>}
        {answer && <div className="cu-ai-answer"><Markdown text={answer} /></div>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); setQ(""); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${c.name}…`} aria-label="Ask the agent" />
        <button type="submit" className="cu-btn cu-btn-primary" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </aside>
  );
}

/* --------------------------------------------------------------- 360 pieces */
function RelationshipMap({ c }: { c: Customer360 }) {
  const held = new Set(c.products.map((p) => p.product_id));
  const recs = c.actions.filter((a) => !held.has(a.product_id) && a.product_id !== "PRD-REL");
  const byGroup = (g: Group) => ({
    held: c.products.filter((p) => groupOf(p.category, p.product_id) === g),
    rec: recs.filter((a) => groupOf("", a.product_id) === g),
  });
  const hh = c.household;
  return (
    <article className="cu-card cu-map">
      <div className="cu-card-head"><h3>Household relationship</h3><span><i className="cu-key cu-key-held" /> held <i className="cu-key cu-key-rec" /> recommended</span></div>
      <div className="cu-map-grid">
        {GROUPS.map((g, i) => {
          const { held: h, rec } = byGroup(g);
          return (
            <section key={g} className={`cu-map-group cu-map-g${i}`} aria-label={g}>
              <h4>{g}</h4>
              <div className="cu-map-chips">
                {h.map((p) => (
                  <span key={p.account_id} className="cu-prod cu-prod-held" title={`${p.account_id} · opened ${p.opened_year} · ${p.status}`}>
                    {p.product_name}<small>{cad(p.balance_cad)}</small>
                  </span>
                ))}
                {rec.map((a) => {
                  const ok = isEligible(a.eligibility);
                  return (
                    <span key={a.product_id} className={`cu-prod cu-prod-rec${ok ? "" : " cu-prod-blocked"}`} title={ok ? a.rationale : a.eligibility}>
                      {!ok && <Lock />}{a.product_name}<small>{ok ? a.action_type : "blocked"}</small>
                    </span>
                  );
                })}
                {!h.length && !rec.length && <span className="cu-prod cu-prod-none">None</span>}
              </div>
            </section>
          );
        })}
        <div className="cu-map-hub">
          <small>{hh.household_id}</small>
          <b>{hh.household_name}</b>
          <span>{num(hh.members)} member{num(hh.members) === 1 ? "" : "s"} · {num(hh.dependents)} dependent{num(hh.dependents) === 1 ? "" : "s"}</span>
          <span>{hh.life_stage}{hh.co_borrower_flag === "Y" ? " · co-borrower" : ""}</span>
          <span>Household income {cad(hh.gross_household_income_cad)}</span>
        </div>
      </div>
    </article>
  );
}

function RatioBar({ label, now, at, guide }: { label: string; now: number; at: number; guide: number }) {
  const scale = Math.max(70, at + 5, now + 5);
  return (
    <div className="cu-ratio">
      <div className="cu-ratio-top">
        <span>{label}</span>
        <span>{now.toFixed(1)}% → <b className={at > guide ? "cu-over" : ""}>{at.toFixed(1)}%</b> <small>vs {guide}% guideline</small></span>
      </div>
      <div className="cu-ratio-track" aria-hidden>
        <span className="cu-ratio-at" style={{ width: `${(at / scale) * 100}%` }} data-over={at > guide} />
        <span className="cu-ratio-now" style={{ width: `${(now / scale) * 100}%` }} />
        <u style={{ left: `${(guide / scale) * 100}%` }} />
      </div>
    </div>
  );
}

function Affordability({ c }: { c: Customer360 }) {
  const cap = c.capacity;
  const today = num(cap.current_payment_monthly_cad), next = num(cap.renewal_payment_monthly_cad);
  return (
    <article className="cu-card cu-afford">
      <div className="cu-card-head"><h3>Affordability at renewal</h3><span>RP-013 · bureau {cap.bureau_band}</span></div>
      <div className="cu-pay">
        <div><small>Today</small><b>{cad(today)}</b><span>/ month</span></div>
        <span className="cu-pay-arrow" aria-hidden>→</span>
        <div><small>At renewal</small><b>{cad(next)}</b><span>/ month</span></div>
        <div className={`cu-pay-shock${c.payment_shock_pct >= 30 ? " cu-over" : ""}`}>+{c.payment_shock_pct.toFixed(0)}%</div>
      </div>
      <RatioBar label="GDS" now={num(cap.gds_now_pct)} at={num(cap.gds_renewal_pct)} guide={GDS_GUIDE} />
      <RatioBar label="TDS" now={num(cap.tds_now_pct)} at={num(cap.tds_renewal_pct)} guide={TDS_GUIDE} />
      <p className="cu-muted cu-small">
        Income {cad(cap.gross_income_cad)} · other debt {cad(cap.monthly_other_debt_cad)}/mo · tax &amp; heat {cad(cap.monthly_tax_heat_cad)}/mo · 12-month PD {num(cap.base_pd_12m_pct).toFixed(1)}%
      </p>
    </article>
  );
}

function WellnessCard({ c }: { c: Customer360 }) {
  const w = c.wellness;
  return (
    <article className="cu-card cu-well">
      <div className="cu-card-head"><h3>Financial wellness</h3><WellnessPill band={w.wellness_band} score={num(w.wellness_score)} /></div>
      <HeatStrip strip={signalsToStrip(c.signals)} />
      {w.drivers.length > 0 && <ul className="cu-drivers">{w.drivers.map((d) => <li key={d}>{d}</li>)}</ul>}
      {w.support_pathway && <p className="cu-small"><span className="cu-tag cu-tag-path">{w.support_pathway}</span></p>}
    </article>
  );
}

function EventsConsent({ c }: { c: Customer360 }) {
  return (
    <article className="cu-card cu-events">
      <div>
        <div className="cu-card-head"><h3>Life events</h3><span>{c.life_events.length} on file</span></div>
        {c.life_events.length ? (
          <ul className="cu-timeline">
            {c.life_events.map((e, i) => (
              <li key={i}>
                <time dateTime={e.event_date}>{fmtDate(e.event_date)}</time>
                <span><b>{e.event_type}</b><small>{e.source} · {e.confidence} confidence</small></span>
                <span className={`cu-atype cu-atype-${e.implication.toLowerCase()}`}>{e.implication}</span>
              </li>
            ))}
          </ul>
        ) : <p className="cu-muted cu-small">No life events recorded.</p>}
      </div>
      <div>
        <div className="cu-card-head"><h3>Contact consent</h3><span>RP-011</span></div>
        <div className="cu-consent">
          {CHANNELS.map((ch) => {
            const s = c.consent[ch] ?? "Not captured";
            return <span key={ch} className={`cu-consent-chip cu-cs-${s.split(" ")[0].toLowerCase()}`}><b>{ch}</b>{s}</span>;
          })}
        </div>
        <p className="cu-muted cu-small">Marketing needs channel consent (RP-011); service messages do not.</p>
      </div>
    </article>
  );
}

/* ----------------------------------------------------------------- outreach */
const ICON: Record<Check["status"], string> = { pass: "✓", warn: "!", block: "✕" };
function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="cu-checks">
      {checks.map((k, i) => (
        <li key={`${k.rule}-${k.name}-${i}`} className={`cu-check cu-check-${k.status}`}>
          <span className="cu-check-icon" aria-label={k.status}>{ICON[k.status]}</span>
          <div><b>{k.name}</b><small>{k.detail}</small></div>
          <code>{k.rule}</code>
        </li>
      ))}
    </ul>
  );
}

function VerdictBadge({ v }: { v: Verdict }) {
  return <span className={`cu-verdict cu-verdict-${v}`}>{v === "blocked" && <Lock />}{VERDICT_LABEL[v]}</span>;
}

type ReviewVerdict = "PASS" | "NEEDS FIXES" | "BLOCKED";
function parseReview(text: string) {
  const vm = /VERDICT:\s*\**\s*(PASS|NEEDS FIXES|BLOCKED)/i.exec(text);
  const blocks = [...text.matchAll(/```(?:text|txt)?[^\S\n]*\n([\s\S]*?)```/g)];
  const corrected = blocks.length ? blocks[blocks.length - 1][1].trim() : "";
  const shown = vm ? text.slice(0, vm.index) + text.slice(vm.index + vm[0].length) : text;
  return { verdict: (vm?.[1].toUpperCase() as ReviewVerdict | undefined) ?? null, corrected, shown: shown.replace(/^\s+/, "") };
}

/* ---------------------------------------------------------------- workspace */
export function CustomerWorkspace({ cid, preferSupport, onBack, backLabel, split }: {
  cid: string;
  preferSupport?: boolean;
  onBack: () => void;
  backLabel: string;
  split: ChatSplit;
}) {
  const [c, setC] = useState<Customer360 | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>(1);
  const [show360, setShow360] = useState(true);
  const [selIdx, setSelIdx] = useState<number | null>(null);
  const [channel, setChannel] = useState<Channel>("Email");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [checks, setChecks] = useState<Check[]>([]);
  const [verdict, setVerdict] = useState<Verdict>("pass");
  const [checking, setChecking] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [review, setReview] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [reviewedText, setReviewedText] = useState("");
  const [usedCorrection, setUsedCorrection] = useState(false);
  const [approved, setApproved] = useState(false);
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "bad" | "info"; text: string; link?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const shell = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const reviewAbort = useRef<AbortController | null>(null);
  const checkSeq = useRef(0);
  const aiId = `cu-ai-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  useEffect(() => {
    let live = true;
    apiGet<Customer360>(`/api/pb/customer/${cid}`).then((r) => {
      if (!live) return;
      setC(r);
      if (preferSupport) {
        const i = r.actions.findIndex((a) => a.action_type === "Support" && isEligible(a.eligibility));
        if (i >= 0) setSelIdx(i);
      }
    }).catch((e) => live && setError(String(e)));
    return () => { live = false; reviewAbort.current?.abort(); };
  }, [cid, preferSupport]);

  const ordered = useMemo(() => (c?.actions ?? []).map((a, i) => ({ a, i }))
    .sort((x, y) => (TYPE_ORDER[x.a.action_type] ?? 9) - (TYPE_ORDER[y.a.action_type] ?? 9) || x.a.rank - y.a.rank), [c]);
  const vulnerable = c?.wellness.vulnerability_flag === "Y" || c?.wellness_band === "Vulnerable";
  const action: Action | null = draft?.action ?? (selIdx !== null && c ? c.actions[selIdx] : null);
  const payload = () => ({ channel, purpose: draft?.purpose ?? "Service", subject, body, action: draft?.action ?? {}, notes });

  // Live guardrails: re-run the deterministic checks whenever the text or channel changes.
  useEffect(() => {
    if (!draft) return;
    const seq = ++checkSeq.current;
    setChecking(true);
    const t = window.setTimeout(() => {
      apiPost<{ checks: Check[]; verdict: Verdict }>(`/api/pb/customer/${cid}/checks`,
        { channel, purpose: draft.purpose, subject, body, action: draft.action })
        .then((r) => { if (seq === checkSeq.current && r?.checks) { setChecks(r.checks); setVerdict(r.verdict); } })
        .catch(() => undefined)
        .finally(() => { if (seq === checkSeq.current) setChecking(false); });
    }, 350);
    return () => window.clearTimeout(t);
  }, [cid, draft, subject, body, channel]);

  const go = (s: Step) => {
    setStep(s);
    if (s > 1) setShow360(false);
    mainRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const generate = async (idx: number, ch: Channel = channel) => {
    setDrafting(true); setMsg(null);
    try {
      const d = await apiPost<Draft>(`/api/pb/customer/${cid}/draft`, { actionIndex: idx, channel: ch });
      setSelIdx(idx); setDraft(d); setSubject(d.subject); setBody(d.body);
      setChecks(d.checks ?? []); setVerdict(d.verdict ?? "pass");
      setReview(""); setReviewedText(""); setUsedCorrection(false); setApproved(false);
      return true;
    } catch (e) {
      setMsg({ tone: "bad", text: `Could not draft: ${String(e)}` });
      return false;
    } finally { setDrafting(false); }
  };

  const runReview = async () => {
    if (!draft) return;
    reviewAbort.current?.abort();
    const ctrl = new AbortController();
    reviewAbort.current = ctrl;
    setReview(""); setReviewing(true); setUsedCorrection(false);
    setReviewedText(`${subject}\n${body}`);
    await streamSSE(`/api/pb/customer/${cid}/review`, payload(), {
      onToken: (t) => setReview((r) => r + t),
      onMessage: (t) => setReview(t),
      onError: (t, d) => setReview(`**${t}**\n\n${d}`),
      onDone: () => setReviewing(false),
    }, ctrl.signal).catch(() => setReviewing(false));
    setReviewing(false);
  };

  const parsed = parseReview(review);
  const stale = !!review && reviewedText !== `${subject}\n${body}`;

  const useCorrected = () => {
    const block = parsed.corrected;
    if (!block) return;
    const m = /^\s*Subject:\s*(.+?)\s*$/im.exec(block);
    if (m) {
      setSubject(m[1].trim());
      setBody(block.slice(m.index + m[0].length).replace(/^\s*\n/, "").trim());
    } else {
      setBody(block);
    }
    setApproved(false);
    setUsedCorrection(true);
  };

  const canSave = !!draft && channel === "Email" && verdict !== "blocked" && (verdict === "pass" || approved) && !checking;
  const saveOutlook = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await apiPost<{ saved: boolean; webLink: string; note: string }>(`/api/pb/customer/${cid}/outlook-draft`, payload());
      setMsg({ tone: "ok", text: r.note || "Saved to your Outlook Drafts - no recipient set, nothing sent.", link: r.webLink || undefined });
    } catch (e) {
      const s = String(e);
      setMsg({ tone: "bad", text: s.includes("409") ? "Blocked by the compliance checks - fix the draft before saving."
        : s.includes("502") ? "Outlook draft failed - sign out and back in once to grant mailbox draft access." : s });
    } finally { setBusy(false); }
  };
  const downloadNote = async () => {
    setBusy(true);
    try {
      await apiDownload(`/api/pb/customer/${cid}/memo`, payload(), `conversation-note-${cid}.docx`);
      setMsg({ tone: "info", text: "Conversation note downloaded (.docx) - internal record, not for the client." });
    } catch (e) { setMsg({ tone: "bad", text: `Could not build the note: ${String(e)}` }); } finally { setBusy(false); }
  };

  const locked = (s: Step) => (s === 2 && selIdx === null && !draft) || ((s === 3 || s === 4) && !draft);

  const gate = draft && verdict === "needs_approval" && (
    <label className="cu-approve">
      <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
      <span><b>Branch Manager approval obtained</b><small>Required before this message can be saved as a draft (RP-012 support-first client).</small></span>
    </label>
  );

  return (
    <div ref={shell} className={`cu-root cu-ws${split.open ? "" : " cu-ws-collapsed"}`} style={{ "--split-w": `${split.width}%` } as CSSProperties}>
      <div className="cu-ws-main" ref={mainRef}>
        <div className="cu-ws-top">
          <button type="button" className="cu-link" onClick={onBack}>← {backLabel}</button>
          <ol className="cu-steps" aria-label="Outreach workflow">
            {STEPS.map((s) => (
              <li key={s.id} className={s.id === step ? "on" : s.id < step ? "done" : ""}>
                <button type="button" disabled={locked(s.id)} aria-current={s.id === step ? "step" : undefined}
                        title={locked(s.id) ? "Choose an action and draft the outreach first" : ""}
                        onClick={() => go(s.id)}><i>{s.id < step ? "✓" : s.id}</i>{s.label}</button>
              </li>
            ))}
          </ol>
        </div>

        {error && <p className="cu-error" role="alert">Could not load {cid} ({error}).</p>}
        {!c && !error && <div aria-busy="true"><div className="cu-skel cu-skel-title" /><div className="cu-skel" /><div className="cu-skel" /></div>}

        {c && <>
          <header className="cu-ws-head">
            <div>
              <div className="cu-eyebrow">{c.customer_id} · {c.segment} · {c.branch} · advisor {c.advisor}</div>
              <h2>{c.name} <small>{c.household.household_name}</small></h2>
              <p className="cu-muted">
                {c.renewal.product_type} · {cad(c.renewal.mortgage_balance_cad)} · renews {fmtDate(c.renewal.maturity_date)} ({c.days_to_maturity} days)
                · {c.tenure_years} yrs with the Bank · {c.language}
              </p>
              <div className="cu-ws-pills">
                <WellnessPill band={c.wellness_band} score={c.wellness_score} />
                <span className={`cu-risk cu-risk-${c.attrition_band.toLowerCase()}`}>Attrition {c.attrition_band} · {c.attrition_score.toFixed(2)}</span>
                <span className="cu-tag">Likelihood {num(c.renewal.renewal_likelihood_pct).toFixed(0)}%</span>
                {c.flags.map((f) => <span key={f} className={`cu-flag cu-flag-${f.split(" ")[0].toLowerCase()}`}>{f}</span>)}
              </div>
            </div>
            <SplitToggle split={split} controls={aiId} className="cu-btn cu-btn-ghost" />
          </header>

          {vulnerable && (
            <div className="cu-banner" role="note">
              <span className="cu-banner-mark" aria-hidden>◐</span>
              <div><b>Support first · sales suppressed (RP-012)</b>
                <p>{c.wellness.primary_driver}. Lead with a support conversation - {c.wellness.support_pathway || "budgeting help"}. Product offers are switched off and any outreach needs Branch Manager approval.</p>
              </div>
            </div>
          )}

          <section className={`cu-360${show360 ? "" : " cu-360-closed"}`} aria-label="Customer 360">
            <button type="button" className="cu-360-toggle" aria-expanded={show360} onClick={() => setShow360(!show360)}>
              <span>Customer 360</span><small>household · affordability · wellness · life events · consent</small><i aria-hidden>{show360 ? "−" : "+"}</i>
            </button>
            {show360 && (
              <div className="cu-360-grid">
                <RelationshipMap c={c} />
                <Affordability c={c} />
                <WellnessCard c={c} />
                <EventsConsent c={c} />
              </div>
            )}
          </section>

          {step === 1 && (
            <section className="cu-step" aria-labelledby="cu-s1">
              <div className="cu-step-head"><h3 id="cu-s1">Next-best action</h3><span>Support › Retain › Deepen · rules applied before AI</span></div>
              <ol className="cu-actions">
                {ordered.map(({ a, i }) => {
                  const ok = isEligible(a.eligibility);
                  const sel = selIdx === i;
                  return (
                    <li key={i} className={`cu-action${ok ? "" : " cu-action-blocked"}${sel ? " cu-action-sel" : ""}`}>
                      <span className={`cu-atype cu-atype-${a.action_type.toLowerCase()}`}>{a.action_type}</span>
                      <div className="cu-action-body">
                        <b>{a.product_name}</b>
                        <small>{a.rationale}</small>
                        {!ok && <small className="cu-lock"><Lock />{a.eligibility}</small>}
                      </div>
                      <span className="cu-action-score" title="Model score">{a.score.toFixed(0)}</span>
                      <button type="button" className={`cu-btn${sel ? " cu-btn-primary" : ""}`} disabled={!ok || drafting}
                              title={ok ? "" : a.eligibility}
                              onClick={async () => { if (await generate(i)) go(2); }}>
                        {ok ? (sel && preferSupport && !draft ? "Draft support outreach ›" : "Draft outreach ›") : "Blocked"}
                      </button>
                    </li>
                  );
                })}
              </ol>
              {!vulnerable && (
                <div className="cu-rail" aria-label="Offer rail">
                  <article className="cu-card cu-offer">
                    <small>Retention offer</small>
                    <b>{c.renewal.recommended_offer_id || "—"}</b>
                    <span>Competitor gap {num(c.renewal.competitor_rate_gap_bps).toFixed(0)} bps · offered {num(c.renewal.offered_renewal_rate_pct).toFixed(2)}%</span>
                    <span className="cu-muted">Pricing subject to approval (RP-001–RP-003)</span>
                  </article>
                  <article className="cu-card cu-offer">
                    <small>Revenue at stake</small>
                    <b>{cad(c.renewal.annual_revenue_exposure_cad)}</b>
                    <span>per year · 5-yr value {cad(c.lifetime_value)}</span>
                  </article>
                  {c.actions.filter((a) => a.action_type === "Deepen" && isEligible(a.eligibility)).slice(0, 2).map((a) => (
                    <article key={a.product_id} className="cu-card cu-offer cu-offer-deepen">
                      <small>Deepen</small><b>{a.product_name}</b><span>{a.rationale}</span>
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}

          {step === 2 && (
            <section className="cu-step" aria-labelledby="cu-s2">
              <div className="cu-step-head"><h3 id="cu-s2">Draft outreach</h3><span>Deterministic draft · edit freely · checks re-run as you type</span></div>
              <div className="cu-compose-controls">
                <label className="cu-field">
                  <span>Action</span>
                  <select value={selIdx ?? ""} disabled={drafting}
                          onChange={(e) => { const i = Number(e.target.value); if (Number.isFinite(i)) generate(i); }}>
                    {selIdx === null && <option value="">Choose an action…</option>}
                    {ordered.map(({ a, i }) => (
                      <option key={i} value={i}>{a.action_type} · {a.product_name}{isEligible(a.eligibility) ? "" : ` (blocked: ${a.eligibility})`}</option>
                    ))}
                  </select>
                </label>
                <div className="cu-field">
                  <span>Channel</span>
                  <div className="cu-seg" role="radiogroup" aria-label="Channel">
                    {CHANNELS.map((ch) => (
                      <button key={ch} type="button" role="radio" aria-checked={channel === ch} onClick={() => setChannel(ch)}>
                        {ch}<small className={`cu-cs-${(c.consent[ch] ?? "Not captured").split(" ")[0].toLowerCase()}`}>{c.consent[ch] ?? "Not captured"}</small>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {action && !isEligible(action.eligibility) && (
                <p className="cu-inline-warn"><Lock /> This action is not eligible ({action.eligibility}). The draft is shown so you can see why it cannot be saved.</p>
              )}
              {!draft ? <p className="cu-empty">{drafting ? "Drafting…" : "Choose an action to draft the outreach."}</p> : (
                <div className="cu-compose">
                  <div className="cu-editor">
                    <label className="cu-field"><span>Subject</span>
                      <input value={subject} onChange={(e) => { setSubject(e.target.value); setApproved(false); }} />
                    </label>
                    <label className="cu-field"><span>Message · {draft.purpose.toLowerCase()} {channel.toLowerCase()}</span>
                      <textarea className="cu-body" value={body} rows={14} onChange={(e) => { setBody(e.target.value); setApproved(false); }} />
                    </label>
                    <small className="cu-muted">Drafted deterministically from Fabric IQ facts. Edit freely - the checks re-run as you type. AI-assisted text is labelled as a draft (RP-017).</small>
                  </div>
                  <aside className="cu-guard" aria-live="polite">
                    <div className="cu-guard-head"><b>Pre-send checks</b>{checking ? <small className="cu-muted">checking…</small> : <VerdictBadge v={verdict} />}</div>
                    <CheckList checks={checks} />
                  </aside>
                </div>
              )}
              <div className="cu-step-actions">
                <button type="button" className="cu-btn" onClick={() => go(1)}>‹ Actions</button>
                <button type="button" className="cu-btn cu-btn-primary" disabled={!draft} onClick={() => go(3)}>Compliance review ›</button>
              </div>
            </section>
          )}

          {step === 3 && draft && (
            <section className="cu-step" aria-labelledby="cu-s3">
              <div className="cu-step-head"><h3 id="cu-s3">Compliance review</h3><span>Compliance Reviewer agent · can block, never approves</span></div>
              <div className="cu-review-grid">
                <div className="cu-card cu-review">
                  <div className="cu-review-top">
                    <div>
                      <small>Reviewer verdict</small>
                      {parsed.verdict
                        ? <span className={`cu-rv cu-rv-${parsed.verdict.split(" ")[0].toLowerCase()}`}>{parsed.verdict}</span>
                        : <span className="cu-rv cu-rv-none">{reviewing ? "Reviewing…" : "Not reviewed yet"}</span>}
                      {stale && <small className="cu-stale">Reviewed an earlier version</small>}
                    </div>
                    <button type="button" className={`cu-btn${review ? "" : " cu-btn-primary"}`} disabled={reviewing} onClick={runReview}>
                      {review ? "Re-run review" : "Run compliance review"}
                    </button>
                  </div>
                  {reviewing && !review && <div aria-busy="true"><div className="cu-skel cu-skel-line" /><div className="cu-skel cu-skel-line short" /></div>}
                  {review && <div className="cu-review-body"><Markdown text={parsed.shown} /></div>}
                  {parsed.corrected && !reviewing && (
                    <div className="cu-review-fix">
                      <button type="button" className="cu-btn cu-btn-primary" disabled={usedCorrection} onClick={useCorrected}>
                        {usedCorrection ? "Corrected draft applied" : "Use corrected draft"}
                      </button>
                      <small className="cu-muted">Replaces the subject and message, then re-runs the checks.</small>
                    </div>
                  )}
                  {!review && !reviewing && <p className="cu-muted cu-small">The reviewer reads the draft with the deterministic findings as authoritative, then judges tone, implied promises, fairness and privacy.</p>}
                </div>
                <aside className="cu-guard">
                  <div className="cu-guard-head"><b>Deterministic checks</b>{checking ? <small className="cu-muted">checking…</small> : <VerdictBadge v={verdict} />}</div>
                  <CheckList checks={checks} />
                  {usedCorrection && <details className="cu-preview"><summary>Current draft</summary><p><b>{subject}</b></p><pre>{body}</pre></details>}
                  {gate}
                </aside>
              </div>
              <div className="cu-step-actions">
                <button type="button" className="cu-btn" onClick={() => go(2)}>‹ Edit draft</button>
                <button type="button" className="cu-btn cu-btn-primary" onClick={() => go(4)}>Wrap-up ›</button>
              </div>
            </section>
          )}

          {step === 4 && draft && (
            <section className="cu-step" aria-labelledby="cu-s4">
              <div className="cu-step-head"><h3 id="cu-s4">Wrap-up</h3><VerdictBadge v={verdict} /></div>
              <div className="cu-review-grid">
                <div className="cu-card">
                  <label className="cu-field"><span>What the client said (conversation notes)</span>
                    <textarea className="cu-notes" rows={5} value={notes} onChange={(e) => setNotes(e.target.value)}
                              placeholder="Key points, concerns raised, what was agreed…" />
                  </label>
                  <div className="cu-preview-mail">
                    <small>{channel} draft · {action?.action_type} · {action?.product_name}</small>
                    <b>{subject}</b>
                    <pre>{body}</pre>
                  </div>
                </div>
                <aside className="cu-guard">
                  <div className="cu-guard-head"><b>Release gate</b><VerdictBadge v={verdict} /></div>
                  <ul className="cu-gate">
                    <li className={verdict !== "blocked" ? "ok" : "no"}>{verdict !== "blocked" ? "✓" : "✕"} No blocking findings</li>
                    {verdict === "needs_approval" && <li className={approved ? "ok" : "no"}>{approved ? "✓" : "○"} Branch Manager approval</li>}
                    <li className={channel === "Email" ? "ok" : "no"}>{channel === "Email" ? "✓" : "○"} Email channel (Outlook drafts are email)</li>
                  </ul>
                  {gate}
                  <div className="cu-wrap-actions">
                    <button type="button" className="cu-btn" disabled={busy} onClick={downloadNote}>Download note (.docx)</button>
                    <button type="button" className="cu-btn cu-btn-primary" disabled={!canSave || busy} onClick={saveOutlook}
                            title={canSave ? "" : verdict === "blocked" ? "Blocked by the checks" : "Needs approval or an email channel"}>
                      Save to Outlook drafts
                    </button>
                    <small className="cu-muted">No recipient is set and nothing is sent. You review and send from Outlook.</small>
                    {msg && (
                      <p className={`cu-msg cu-msg-${msg.tone}`} role="status">
                        {msg.text}{msg.link && <> <a href={msg.link} target="_blank" rel="noopener noreferrer">Open in Outlook ↗</a></>}
                      </p>
                    )}
                  </div>
                </aside>
              </div>
              <div className="cu-step-actions">
                <button type="button" className="cu-btn" onClick={() => go(3)}>‹ Review</button>
              </div>
            </section>
          )}
          {msg && step !== 4 && (
            <p className={`cu-msg cu-msg-${msg.tone}`} role="status">{msg.text}</p>
          )}
          <p className="cu-foot">Synthetic demo data. Internal signals (wellness, attrition, TDS) are for the advisor and never go in client copy (RP-016).</p>
        </>}
      </div>
      {split.open
        ? <SplitHandle split={split} container={shell} controls={aiId} label="Advisor AI" />
        : <SplitRail split={split} controls={aiId} label="Advisor AI" />}
      {c ? <AiPanel c={c} id={aiId} hidden={!split.open} /> : <aside className="cu-ai" id={aiId} hidden={!split.open} aria-busy="true" />}
    </div>
  );
}
