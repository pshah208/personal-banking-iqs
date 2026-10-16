/**
 * Card workspace - one card account, its value, behaviour, fit and plays.
 *
 *   1 Play               Support › Protect › Retain › Grow. Blocked plays stay
 *                        visible with the reason; support-first clients get the
 *                        RP-021 banner and no upgrade or credit offers.
 *   2 Draft              deterministic draft, editable, with live guardrail
 *                        checks (RP-011, RP-016, RP-019, RP-020, RP-021, RP-022).
 *   3 Compliance review  the Compliance Reviewer agent can block, never approve.
 *   4 Done               copy the final text - nothing is ever sent from here.
 *
 * The AI panel on the right is the live main agent, scoped by the account's
 * suggested prompts.
 */
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { apiGet, apiPost, streamChat, streamSSE } from "../api";
import { Markdown } from "../components/Markdown";
import { SplitHandle, SplitRail, SplitToggle, type ChatSplit } from "../components/ChatSplit";
import {
  CATS, CAT_LABEL, IQ_NAME, TYPE_ORDER, addDays, cad, cadShort, isEligible, isIQLayer, monthLabel, num, slug, supportFirst,
  type CardAccountDetail, type CardDraft, type CardProduct, type Check, type IQLayer, type SpendMonth, type Verdict,
} from "./types";
import "./cards.css";
import { ProcessorAccount } from "./Processor";

/* ------------------------------------------------------------ shared atoms */
export const Lock = () => (
  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6">
    <rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
  </svg>
);

export function BehaviourPill({ b }: { b: string }) {
  return <span className={`cd-beh cd-beh-${slug(b)}`}><i aria-hidden />{b}</span>;
}

export function PlayTag({ t }: { t: string }) {
  return <span className={`cd-ptype cd-ptype-${t.toLowerCase()}`}>{t}</span>;
}

/** Which IQ layer powers a section. Children replace the default label (e.g. "Foundry IQ · RP-021"). */
export function IQBadge({ iq, children, title }: { iq: IQLayer; children?: ReactNode; title?: string }) {
  return (
    <span className={`cd-iq cd-iq-${iq}`} title={title ?? `Source: ${IQ_NAME[iq]}`}>
      <i aria-hidden />{children ?? IQ_NAME[iq]}
    </span>
  );
}

function WellnessPill({ band }: { band: string }) {
  return <span className={`cd-pill cd-band-${band.toLowerCase()}`}><i aria-hidden />{band}</span>;
}

type Step = 1 | 2 | 3 | 4;
const STEPS: { id: Step; label: string }[] = [
  { id: 1, label: "Play" }, { id: 2, label: "Draft" }, { id: 3, label: "Compliance review" }, { id: 4, label: "Done" },
];
const VERDICT_LABEL: Record<Verdict, string> = { pass: "Ready", needs_approval: "Needs approval", blocked: "Blocked" };
const CAT_COLOR: Record<string, string> = {
  groceries: "#2f6f62", dining: "#5a9a8b", travel: "#3d5a99", gas_transit: "#8aa1c9",
  bills: "#8a7a5c", online: "#b9a77f", other: "#c9c6c0",
};

/* ------------------------------------------------- illustrative card value */
type Totals = Record<string, number> & { total: number; foreign: number; interest: number };
function totals(spend: SpendMonth[]): Totals {
  const t = { total: 0, foreign: 0, interest: 0 } as Totals;
  CATS.forEach((c) => { t[c] = 0; });
  spend.forEach((m) => {
    CATS.forEach((c) => { t[c] += num(m[c]); });
    t.total += num(m.spend); t.foreign += num(m.foreign_spend); t.interest += num(m.interest_charged);
  });
  return t;
}

/** Simple, labelled-illustrative earn rates; 1 point ≈ $0.01. */
function rewardsFor(pid: string, t: Totals): number {
  const gd = t.groceries + t.dining;
  switch (pid) {
    case "CRD-GOLD": return (5 * gd + (t.total - gd)) * 0.01;
    case "CRD-TRVL": return (3 * gd + 2 * t.gas_transit + (t.total - gd - t.gas_transit)) * 0.01;
    case "CRD-CASH": return 0.04 * (t.groceries + t.bills) + 0.01 * (t.total - t.groceries - t.bills);
    case "CRD-NOFEE": return (2 * gd + (t.total - gd)) * 0.01;
    case "CRD-LOW": return 0;
    default: return t.total * 0.01;
  }
}

interface Fit { p: CardProduct; rewards: number; fx: number; interest: number; fee: number; net: number; lock: string; current: boolean }
function fitTable(c: CardAccountDetail, shelf: CardProduct[], t: Totals): Fit[] {
  const curApr = num(c.account.purchase_apr) || num(c.product.purchase_apr) || 1;
  const income = num(c.account.income);
  const support = supportFirst(c);
  return shelf.map((p) => {
    const rewards = rewardsFor(p.product_id, t);
    const fx = /none/i.test(p.fx_fee) ? t.foreign * 0.025 : 0;
    const interest = t.interest * (num(p.purchase_apr) / curApr);
    const fee = num(p.annual_fee);
    const current = p.product_id === c.product_id;
    let lock = "";
    if (!current && income < num(p.min_income)) lock = `Income below ${cad(p.min_income)} minimum (RP-019)`;
    else if (!current && support && !["CRD-LOW", "CRD-NOFEE"].includes(p.product_id)) lock = "Support-first: lower-cost options only (RP-021)";
    return { p, rewards, fx, interest, fee, net: rewards + fx - fee - interest, lock, current };
  });
}

/* ------------------------------------------------------------------ AI panel */
function AiPanel({ c, id, hidden }: { c: CardAccountDetail; id: string; hidden?: boolean }) {
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
    <aside className="cd-ai" id={id} hidden={hidden} aria-label={`AI assistant for ${c.customer_name}`}>
      <header>
        <span className="cd-ai-mark" aria-hidden>✦</span>
        <div><b>Cards AI</b><small>Live agent · {c.customer_name} · {c.account_id}</small></div>
      </header>
      <div className="cd-ai-prompts">
        {c.prompts.map((p) => (
          <button key={p.label} type="button" disabled={busy} onClick={() => ask(p.prompt, p.label)}>{p.label} <span aria-hidden>↗</span></button>
        ))}
      </div>
      <div className="cd-ai-body" aria-live="polite">
        {!asked && <p className="cd-muted">Pick a prompt or ask anything about this card. Answers are grounded in Fabric IQ and policy, under your identity. "Compare competitor cards" is the only prompt that uses the live web.</p>}
        {asked && <div className="cd-ai-q">{asked}</div>}
        {layers.length > 0 && <div className="cd-ai-layers">{layers.map((l) => <span key={l} className={`cd-ai-layer l-${l}`}>{l} IQ</span>)}</div>}
        {busy && !answer && <div aria-busy="true"><div className="cd-skel cd-skel-line" /><div className="cd-skel cd-skel-line short" /><small className="cd-muted">{status}</small></div>}
        {answer && <div className="cd-ai-answer"><Markdown text={answer} /></div>}
        {answer && !busy && (
          <footer className="cd-sources" aria-label="Sources used">
            <small>Sources used</small>
            {layers.filter(isIQLayer).length
              ? layers.filter(isIQLayer).map((l) => <IQBadge key={l} iq={l} />)
              : <small className="cd-muted">No IQ layer reported for this answer</small>}
          </footer>
        )}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); setQ(""); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${c.customer_name.split(" ")[0]}'s card…`} aria-label="Ask the agent" />
        <button type="submit" className="cd-btn cd-btn-primary" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </aside>
  );
}

/* -------------------------------------------------------------- 360 panels */
function SpendPanel({ spend }: { spend: SpendMonth[] }) {
  const max = Math.max(1, ...spend.map((m) => Math.max(num(m.spend), num(m.payment))));
  const balMax = Math.max(1, ...spend.map((m) => num(m.statement_balance)));
  const pts = (f: (m: SpendMonth) => number, scale: number) =>
    spend.map((m, i) => `${((i + 0.5) / spend.length) * 100},${100 - (f(m) / scale) * 92}`).join(" ");
  const used = CATS.filter((c) => spend.some((m) => num(m[c]) > 0));
  return (
    <article className="cd-card cd-spend">
      <div className="cd-card-head">
        <h3>Spend · last 12 months</h3>
        <span className="cd-legend">
          {used.map((c) => <span key={c}><i style={{ background: CAT_COLOR[c] }} />{CAT_LABEL[c]}</span>)}
          <span><i className="cd-key-pay" />Payment</span>
          <span><i className="cd-key-bal" />Statement balance (right scale)</span>
        </span>
      </div>
      <div className="cd-sp">
        <div className="cd-sp-axis" aria-hidden><span>{cadShort(max)}</span><span>{cadShort(max / 2)}</span><span>$0</span></div>
        <div className="cd-sp-plot" role="img" aria-label="Monthly spend by category with payments and statement balance">
          <div className="cd-sp-bars">
            {spend.map((m, i) => (
              <div key={m.month} className="cd-sp-col" title={`${m.month}: spend ${cad(m.spend)} · paid ${cad(m.payment)} · statement ${cad(m.statement_balance)}`}>
                <div className="cd-sp-stack" style={{ height: `${(num(m.spend) / max) * 92}%`, animationDelay: `${i * 20}ms` }}>
                  {used.map((c) => <span key={c} style={{ flexGrow: num(m[c]), background: CAT_COLOR[c] }} />)}
                </div>
              </div>
            ))}
          </div>
          <svg className="cd-sp-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
            <polyline className="cd-line-bal" points={pts((m) => num(m.statement_balance), balMax)} vectorEffect="non-scaling-stroke" />
            <polyline className="cd-line-pay" points={pts((m) => num(m.payment), max)} vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
        <div className="cd-sp-axis cd-sp-axis-r" aria-hidden><span>{cadShort(balMax)}</span><span>{cadShort(balMax / 2)}</span><span>$0</span></div>
        <div className="cd-sp-months" aria-hidden>{spend.map((m) => <span key={m.month}>{monthLabel(m.month)}</span>)}</div>
      </div>
      <details className="cd-sp-table">
        <summary>Show as table</summary>
        <div className="cd-table-wrap">
          <table>
            <thead><tr><th>Month</th><th>Spend</th>{used.map((c) => <th key={c}>{CAT_LABEL[c]}</th>)}<th>Payment</th><th>Interest</th><th>Statement</th></tr></thead>
            <tbody>
              {spend.map((m) => (
                <tr key={m.month}><td>{m.month}</td><td>{cad(m.spend)}</td>{used.map((c) => <td key={c}>{cad(m[c])}</td>)}<td>{cad(m.payment)}</td><td>{cad(m.interest_charged)}</td><td>{cad(m.statement_balance)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </article>
  );
}

function ValueCard({ c, t, fit }: { c: CardAccountDetail; t: Totals; fit: Fit | undefined }) {
  const pts = num(c.account.rewards_points);
  const fee = num(c.annual_fee);
  const earn = fit?.rewards ?? 0;
  const net = earn + (fit?.fx ?? 0) - fee;
  const scale = Math.max(1, earn + (fit?.fx ?? 0), fee);
  return (
    <article className="cd-card cd-value">
      <div className="cd-card-head"><h3>Rewards &amp; fee value</h3><span>illustrative · 1 pt ≈ $0.01</span></div>
      <div className="cd-stats">
        <div><small>Points balance</small><b>{pts.toLocaleString("en-CA")}</b><span>≈ {cad(pts / 100)}</span></div>
        <div><small>Annual fee</small><b>{fee ? cad(fee) : "None"}</b><span>{fee ? `due ${addDays(c.account.as_of_date, c.fee_anniversary_days)}` : "no-fee card"}</span></div>
        <div><small>Net value / yr</small><b className={net < 0 ? "cd-neg" : ""}>{cad(net)}</b><span>est. rewards − fee</span></div>
      </div>
      <div className="cd-vs" aria-label={`Estimated rewards ${cad(earn)} versus fee ${cad(fee)}`}>
        <div><span>Est. rewards</span><i><i style={{ width: `${((earn + (fit?.fx ?? 0)) / scale) * 100}%` }} className="cd-vs-earn" /></i><b>{cad(earn + (fit?.fx ?? 0))}</b></div>
        <div><span>Annual fee</span><i><i style={{ width: `${(fee / scale) * 100}%` }} className="cd-vs-fee" /></i><b>{cad(fee)}</b></div>
      </div>
      <p className="cd-small cd-muted">From {cad(t.total)} spend over 12 months on the {c.product_name} ({c.product.rewards}).</p>
    </article>
  );
}

function BehaviourCard({ c, t }: { c: CardAccountDetail; t: Totals }) {
  const minM = num(c.account.min_payment_months_12m);
  return (
    <article className="cd-card cd-behcard">
      <div className="cd-card-head"><h3>Payment behaviour</h3><BehaviourPill b={c.behaviour} /></div>
      <div className="cd-minpay">
        <small>Minimum-payment months · last 12</small>
        <div className="cd-dots" role="img" aria-label={`${minM} of 12 months at minimum payment`}>
          {Array.from({ length: 12 }, (_, i) => <i key={i} className={i < minM ? "on" : ""} />)}
          <b>{minM} of 12</b>
        </div>
      </div>
      <div className="cd-stats">
        <div><small>Interest charged</small><b>{cad(t.interest)}</b><span>last 12 months</span></div>
        <div><small>Utilisation</small><b>{c.utilization_pct.toFixed(0)}%</b><span>{cad(c.balance)} of {cad(c.credit_limit)}</span></div>
        <div><small>Autopay</small><b>{c.account.autopay === "Y" ? "On" : "Off"}</b><span>{c.days_past_due ? `${c.days_past_due} days past due` : "up to date"}</span></div>
      </div>
      <p className="cd-small cd-muted">Purchase APR {num(c.account.purchase_apr).toFixed(2)}% · foreign spend {num(c.account.foreign_spend_share_pct).toFixed(0)}% · fraud alerts (90 d) {c.fraud_alerts_90d}</p>
    </article>
  );
}

function FitTable({ rows }: { rows: Fit[] }) {
  const cur = rows.find((r) => r.current);
  const best = rows.filter((r) => !r.lock).reduce<Fit | null>((b, r) => (!b || r.net > b.net ? r : b), null);
  return (
    <article className="cd-card cd-fit">
      <div className="cd-card-head"><h3>Card fit vs the shelf</h3><span>Illustrative · expected annual value = est. rewards + FX saving − fee − est. interest · RP-019</span></div>
      <div className="cd-table-wrap">
        <table className="cd-fit-table">
          <thead>
            <tr><th>Card</th><th>Annual fee</th><th>APR</th><th>Est. rewards</th><th>FX saving</th><th>Est. interest</th><th>Net value / yr</th><th>vs current</th><th>Status</th></tr>
          </thead>
          <tbody>
            {[...rows].sort((a, b) => b.net - a.net).map((r) => {
              const d = cur ? r.net - cur.net : 0;
              return (
                <tr key={r.p.product_id} className={`${r.current ? "cd-fit-cur" : ""}${r.lock ? " cd-fit-locked" : ""}${best?.p.product_id === r.p.product_id && !r.current ? " cd-fit-best" : ""}`}>
                  <th scope="row"><b>{r.p.product_name}</b><small>{r.p.tier} · {r.p.rewards}</small></th>
                  <td>{num(r.p.annual_fee) ? cad(r.p.annual_fee) : "—"}</td>
                  <td>{num(r.p.purchase_apr).toFixed(2)}%</td>
                  <td>{cad(r.rewards)}</td>
                  <td>{r.fx ? cad(r.fx) : "—"}</td>
                  <td>{r.interest ? `−${cad(r.interest)}` : "—"}</td>
                  <td><b className={r.net < 0 ? "cd-neg" : ""}>{cad(r.net)}</b></td>
                  <td className={d > 0 ? "cd-up" : d < 0 ? "cd-down" : ""}>{r.current ? "—" : `${d > 0 ? "+" : d < 0 ? "−" : ""}${cad(Math.abs(d))}`}</td>
                  <td>
                    {r.current ? <span className="cd-tag cd-tag-cur">Current</span>
                      : r.lock ? <small className="cd-lock"><Lock />{r.lock}</small>
                      : best?.p.product_id === r.p.product_id ? <span className="cd-tag cd-tag-best">Best fit</span>
                      : <small className="cd-muted">Eligible</small>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </article>
  );
}

/* ----------------------------------------------------------------- outreach */
const ICON: Record<Check["status"], string> = { pass: "✓", warn: "!", block: "✕" };
function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="cd-checks">
      {checks.map((k, i) => (
        <li key={`${k.rule}-${k.name}-${i}`} className={`cd-check cd-check-${k.status}`}>
          <span className="cd-check-icon" aria-label={k.status}>{ICON[k.status]}</span>
          <div><b>{k.name}</b><small>{k.detail}</small></div>
          <code>{k.rule}</code>
        </li>
      ))}
    </ul>
  );
}

function VerdictBadge({ v }: { v: Verdict }) {
  return <span className={`cd-verdict cd-verdict-${v}`}>{v === "blocked" && <Lock />}{VERDICT_LABEL[v]}</span>;
}

type ReviewVerdict = "PASS" | "NEEDS FIXES" | "BLOCKED";
function parseReview(text: string) {
  const vm = /VERDICT:\s*\**\s*(PASS|NEEDS FIXES|BLOCKED)/i.exec(text);
  const blocks = [...text.matchAll(/```(?:text|txt)?[^\S\n]*\n([\s\S]*?)```/g)];
  const corrected = blocks.length ? blocks[blocks.length - 1][1].trim() : "";
  const shown = vm ? text.slice(0, vm.index) + text.slice(vm.index + vm[0].length) : text;
  return { verdict: (vm?.[1].toUpperCase() as ReviewVerdict | undefined) ?? null, corrected, shown: shown.replace(/^\s+/, "") };
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}

/* ---------------------------------------------------------------- workspace */
export function CardAccount({ aid, shelf, split, onBack }: {
  aid: string;
  shelf: CardProduct[];
  split: ChatSplit;
  onBack: () => void;
}) {
  const [c, setC] = useState<CardAccountDetail | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>(1);
  const [show360, setShow360] = useState(true);
  const [selIdx, setSelIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState<CardDraft | null>(null);
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
  const [msg, setMsg] = useState<{ tone: "ok" | "bad" | "info"; text: string } | null>(null);
  const shell = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const reviewAbort = useRef<AbortController | null>(null);
  const checkSeq = useRef(0);
  const aiId = `cd-ai-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  useEffect(() => {
    let live = true;
    apiGet<CardAccountDetail>(`/api/cards/account/${aid}`).then((r) => { if (live) setC(r); }).catch((e) => live && setError(String(e)));
    return () => { live = false; reviewAbort.current?.abort(); };
  }, [aid]);

  const t = useMemo(() => totals(c?.spend ?? []), [c]);
  const fits = useMemo(() => (c ? fitTable(c, shelf.length ? shelf : [c.product], t) : []), [c, shelf, t]);
  const ordered = useMemo(() => (c?.plays ?? []).map((p, i) => ({ p, i }))
    .sort((x, y) => (TYPE_ORDER[x.p.play_type] ?? 9) - (TYPE_ORDER[y.p.play_type] ?? 9) || x.p.rank - y.p.rank), [c]);
  const support = c ? supportFirst(c) : false;
  const play = draft?.play ?? (selIdx !== null && c ? c.plays[selIdx] : null);
  const payload = () => ({ channel: "Email", purpose: draft?.purpose ?? "Service", subject, body, play: draft?.play ?? {} });

  // Live guardrails: re-run the deterministic checks whenever the text changes.
  useEffect(() => {
    if (!draft) return;
    const seq = ++checkSeq.current;
    setChecking(true);
    const h = window.setTimeout(() => {
      apiPost<{ checks: Check[]; verdict: Verdict }>(`/api/cards/account/${aid}/checks`,
        { channel: "Email", purpose: draft.purpose, subject, body, play: draft.play })
        .then((r) => { if (seq === checkSeq.current && r?.checks) { setChecks(r.checks); setVerdict(r.verdict); } })
        .catch(() => undefined)
        .finally(() => { if (seq === checkSeq.current) setChecking(false); });
    }, 350);
    return () => window.clearTimeout(h);
  }, [aid, draft, subject, body]);

  const go = (s: Step) => {
    setStep(s);
    if (s > 1) setShow360(false);
    mainRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const generate = async (idx: number) => {
    setDrafting(true); setMsg(null);
    try {
      const d = await apiPost<CardDraft>(`/api/cards/account/${aid}/draft`, { playIndex: idx });
      setSelIdx(idx); setDraft(d); setSubject(d.subject); setBody(d.body);
      setChecks(d.checks ?? []); setVerdict(d.verdict ?? "pass");
      setReview(""); setReviewedText(""); setUsedCorrection(false);
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
    await streamSSE(`/api/cards/account/${aid}/review`, payload(), {
      onToken: (x) => setReview((r) => r + x),
      onMessage: (x) => setReview(x),
      onError: (x, d) => setReview(`**${x}**\n\n${d}`),
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
    setUsedCorrection(true);
  };

  const canCopy = !!draft && verdict !== "blocked" && !checking;
  const copyFinal = async () => {
    const ok = await copyText(`Subject: ${subject}\n\n${body}`);
    setMsg(ok ? { tone: "ok", text: "Copied to your clipboard. Nothing has been sent - paste it into your approved channel and send it yourself." }
      : { tone: "bad", text: "Could not reach the clipboard - select the text above and copy it manually." });
  };

  const locked = (s: Step) => (s > 1 && !draft);
  const linked = c?.linked_mortgage === "Y";
  const fee = c ? (c.annual_fee ? `${cad(c.annual_fee)} fee due ${addDays(c.account.as_of_date, c.fee_anniversary_days)} (${c.fee_anniversary_days} days)` : "No annual fee") : "";

  return (
    <div ref={shell} className={`cd-ws${split.open ? "" : " cd-ws-collapsed"}`} style={{ "--split-w": `${split.width}%` } as CSSProperties}>
      <div className="cd-ws-main" ref={mainRef}>
        <div className="cd-ws-top">
          <button type="button" className="cd-link" onClick={onBack}>← Cards</button>
          <ol className="cd-steps" aria-label="Card outreach workflow">
            {STEPS.map((s) => (
              <li key={s.id} className={s.id === step ? "on" : s.id < step ? "done" : ""}>
                <button type="button" disabled={locked(s.id)} aria-current={s.id === step ? "step" : undefined}
                        title={locked(s.id) ? "Choose a play and draft first" : ""}
                        onClick={() => go(s.id)}><i>{s.id < step ? "✓" : s.id}</i>{s.label}</button>
              </li>
            ))}
          </ol>
        </div>

        {error && <p className="cd-error" role="alert">Could not load {aid} ({error}).</p>}
        {!c && !error && <div aria-busy="true"><div className="cd-skel cd-skel-title" /><div className="cd-skel" /><div className="cd-skel" /></div>}

        {c && <>
          <header className="cd-ws-head">
            <div>
              <div className="cd-eyebrow">{c.account_id} · {c.customer_id} · {c.segment} · {c.branch}</div>
              <h2>{c.customer_name} <small>{c.product_name}</small></h2>
              <p className="cd-muted">
                Limit {cad(c.credit_limit)} · balance {cad(c.balance)} ({c.utilization_pct.toFixed(0)}% used) · {fee} · card since {String(c.account.opened_year)}
              </p>
              <div className="cd-ws-pills">
                <BehaviourPill b={c.behaviour} />
                <WellnessPill band={c.wellness_band} />
                {linked && (
                  <span className="cd-carry" title="This client also holds a mortgage - wellness, consent and TDS come from the personal-banking tables">
                    <b>Linked mortgage</b>Wellness band carried from the mortgage book
                  </span>
                )}
                {c.fraud_alerts_90d > 0 && <span className="cd-flag cd-flag-fraud-alert">Fraud alert · {c.fraud_alerts_90d} in 90 d</span>}
                <span className="cd-tag">Email marketing {c.email_consent.toLowerCase()}</span>
              </div>
            </div>
            <SplitToggle split={split} controls={aiId} className="cd-btn cd-btn-ghost" />
          </header>

          {support && (
            <div className="cd-banner" role="note">
              <span className="cd-banner-mark" aria-hidden>◐</span>
              <div><b>Support first · no upgrades, limit increases or new credit (RP-021)</b>
                <p>
                  {num(c.account.min_payment_months_12m)} of the last 12 months at minimum payment, {cad(t.interest)} interest in a year.
                  Lead with a lower-cost path - a lower-rate card or instalment plan - and free budgeting support. Keep the tone helpful, never urgent.
                  {linked ? " The mortgage book has this household as " + c.wellness_band + "." : ""}
                </p>
              </div>
            </div>
          )}
          {!support && c.fraud_alerts_90d > 0 && (
            <div className="cd-banner cd-banner-protect" role="note">
              <span className="cd-banner-mark" aria-hidden>⛨</span>
              <div><b>Security before sales (RP-022)</b>
                <p>An open fraud alert means a security check-in comes before any retain or grow conversation. Never ask for a PIN, passcode or full card number.</p>
              </div>
            </div>
          )}

          <section className={`cd-360${show360 ? "" : " cd-360-closed"}`} aria-label="Card 360">
            <button type="button" className="cd-360-toggle" aria-expanded={show360} onClick={() => setShow360(!show360)}>
              <span>Card 360</span><small>spend · rewards &amp; fee · behaviour · card fit</small><IQBadge iq="fabric" /><i aria-hidden>{show360 ? "−" : "+"}</i>
            </button>
            {show360 && (
              <div className="cd-360-grid">
                <SpendPanel spend={c.spend} />
                <ValueCard c={c} t={t} fit={fits.find((f) => f.current)} />
                <BehaviourCard c={c} t={t} />
                <FitTable rows={fits} />
              </div>
            )}
          </section>

          <ProcessorAccount aid={aid} />

          {step === 1 && (
            <section className="cd-step" aria-labelledby="cd-s1">
              <div className="cd-step-head">
                <h3 id="cd-s1">Plays</h3><span>Support › Protect › Retain › Grow · rules applied before AI</span>
                <span className="cd-iqs"><IQBadge iq="fabric" /><IQBadge iq="foundry">Foundry IQ · RP-019–022</IQBadge></span>
              </div>
              {!ordered.length && <p className="cd-empty cd-card">No play for this card - the client looks well served. Nothing to send.</p>}
              <ol className="cd-actions">
                {ordered.map(({ p, i }) => {
                  const ok = isEligible(p.eligibility);
                  const sel = selIdx === i;
                  return (
                    <li key={i} className={`cd-action${ok ? "" : " cd-action-blocked"}${sel ? " cd-action-sel" : ""}`}>
                      <PlayTag t={p.play_type} />
                      <div className="cd-action-body">
                        <b>{p.play}<span> · {p.recommended_product}</span></b>
                        <small>{p.rationale}</small>
                        {!ok && <small className="cd-lock"><Lock />{p.eligibility}</small>}
                      </div>
                      <span className="cd-action-val" title="Value at stake">{num(p.value_at_stake_cad) ? cad(p.value_at_stake_cad) : ""}</span>
                      <button type="button" className={`cd-btn${ok ? " cd-btn-primary" : ""}`} disabled={drafting}
                              title={ok ? "" : `Blocked: ${p.eligibility}. The draft is shown so you can see why.`}
                              onClick={async () => { if (await generate(i)) go(2); }}>
                        {ok ? "Draft outreach ›" : <><Lock /> See why ›</>}
                      </button>
                    </li>
                  );
                })}
              </ol>
            </section>
          )}

          {step === 2 && (
            <section className="cd-step" aria-labelledby="cd-s2">
              <div className="cd-step-head">
                <h3 id="cd-s2">Draft</h3><span>Deterministic draft · edit freely · checks re-run as you type</span>
                <span className="cd-iqs"><IQBadge iq="fabric" /><IQBadge iq="foundry">Foundry IQ · checks</IQBadge></span>
              </div>
              <div className="cd-compose-controls">
                <label className="cd-field">
                  <span>Play</span>
                  <select value={selIdx ?? ""} disabled={drafting}
                          onChange={(e) => { const i = Number(e.target.value); if (Number.isFinite(i)) generate(i); }}>
                    {selIdx === null && <option value="">Choose a play…</option>}
                    {ordered.map(({ p, i }) => (
                      <option key={i} value={i}>{p.play_type} · {p.play}{isEligible(p.eligibility) ? "" : ` (blocked: ${p.eligibility})`}</option>
                    ))}
                  </select>
                </label>
                <div className="cd-field"><span>Channel · purpose</span><div className="cd-purpose">Email · {draft?.purpose ?? "—"}</div></div>
              </div>
              {play && !isEligible(play.eligibility) && (
                <p className="cd-inline-warn"><Lock /> This play is not eligible ({play.eligibility}). The draft is shown so you can see why it cannot be used.</p>
              )}
              {!draft ? <p className="cd-empty">{drafting ? "Drafting…" : "Choose a play to draft the outreach."}</p> : (
                <div className="cd-compose">
                  <div className="cd-editor">
                    <label className="cd-field"><span>Subject</span>
                      <input value={subject} onChange={(e) => setSubject(e.target.value)} />
                    </label>
                    <label className="cd-field"><span>Message · {draft.purpose.toLowerCase()} email</span>
                      <textarea className="cd-body" value={body} rows={14} onChange={(e) => setBody(e.target.value)} />
                    </label>
                    <small className="cd-muted">Drafted deterministically from Fabric IQ facts. Edit freely - the checks re-run as you type. AI-assisted text is labelled as a draft (RP-017).</small>
                  </div>
                  <aside className="cd-guard" aria-live="polite">
                    <div className="cd-guard-head"><b>Pre-send checks</b>{checking ? <small className="cd-muted">checking…</small> : <VerdictBadge v={verdict} />}</div>
                    <CheckList checks={checks} />
                  </aside>
                </div>
              )}
              <div className="cd-step-actions">
                <button type="button" className="cd-btn" onClick={() => go(1)}>‹ Plays</button>
                <button type="button" className="cd-btn cd-btn-primary" disabled={!draft} onClick={() => go(3)}>Compliance review ›</button>
              </div>
            </section>
          )}

          {step === 3 && draft && (
            <section className="cd-step" aria-labelledby="cd-s3">
              <div className="cd-step-head">
                <h3 id="cd-s3">Compliance review</h3><span>Compliance Reviewer agent · can block, never approves</span>
                <span className="cd-iqs"><IQBadge iq="foundry" /></span>
              </div>
              <div className="cd-review-grid">
                <div className="cd-card cd-review">
                  <div className="cd-review-top">
                    <div>
                      <small>Reviewer verdict</small>
                      {parsed.verdict
                        ? <span className={`cd-rv cd-rv-${parsed.verdict.split(" ")[0].toLowerCase()}`}>{parsed.verdict}</span>
                        : <span className="cd-rv cd-rv-none">{reviewing ? "Reviewing…" : "Not reviewed yet"}</span>}
                      {stale && <small className="cd-stale">Reviewed an earlier version</small>}
                    </div>
                    <button type="button" className={`cd-btn${review ? "" : " cd-btn-primary"}`} disabled={reviewing} onClick={runReview}>
                      {review ? "Re-run review" : "Run compliance review"}
                    </button>
                  </div>
                  {reviewing && !review && <div aria-busy="true"><div className="cd-skel cd-skel-line" /><div className="cd-skel cd-skel-line short" /></div>}
                  {review && <div className="cd-review-body"><Markdown text={parsed.shown} /></div>}
                  {parsed.corrected && !reviewing && (
                    <div className="cd-review-fix">
                      <button type="button" className="cd-btn cd-btn-primary" disabled={usedCorrection} onClick={useCorrected}>
                        {usedCorrection ? "Corrected draft applied" : "Use corrected draft"}
                      </button>
                      <small className="cd-muted">Replaces the subject and message, then re-runs the checks.</small>
                    </div>
                  )}
                  {!review && !reviewing && <p className="cd-muted cd-small">The reviewer reads the draft with the deterministic findings as authoritative, then judges tone, implied promises, fairness and privacy.</p>}
                </div>
                <aside className="cd-guard">
                  <div className="cd-guard-head"><b>Deterministic checks</b>{checking ? <small className="cd-muted">checking…</small> : <VerdictBadge v={verdict} />}</div>
                  <CheckList checks={checks} />
                  {usedCorrection && <details className="cd-preview"><summary>Current draft</summary><p><b>{subject}</b></p><pre>{body}</pre></details>}
                </aside>
              </div>
              <div className="cd-step-actions">
                <button type="button" className="cd-btn" onClick={() => go(2)}>‹ Edit draft</button>
                <button type="button" className="cd-btn cd-btn-primary" onClick={() => go(4)}>Done ›</button>
              </div>
            </section>
          )}

          {step === 4 && draft && (
            <section className="cd-step" aria-labelledby="cd-s4">
              <div className="cd-step-head"><h3 id="cd-s4">Done</h3><VerdictBadge v={verdict} /></div>
              <div className="cd-review-grid">
                <div className="cd-card">
                  <div className="cd-preview-mail">
                    <small>Email draft · {play?.play_type} · {play?.play}</small>
                    <b>{subject}</b>
                    <pre>{body}</pre>
                  </div>
                </div>
                <aside className="cd-guard">
                  <div className="cd-guard-head"><b>Release gate</b><VerdictBadge v={verdict} /></div>
                  <ul className="cd-gate">
                    <li className={verdict !== "blocked" ? "ok" : "no"}>{verdict !== "blocked" ? "✓" : "✕"} No blocking findings</li>
                    <li className={review && !stale ? "ok" : "no"}>{review && !stale ? "✓" : "○"} Compliance review on this version</li>
                    <li className={play && isEligible(play.eligibility) ? "ok" : "no"}>{play && isEligible(play.eligibility) ? "✓" : "✕"} Play is eligible</li>
                  </ul>
                  <div className="cd-wrap-actions">
                    <button type="button" className="cd-btn cd-btn-primary" disabled={!canCopy} onClick={copyFinal}
                            title={canCopy ? "" : "Blocked by the checks - fix the draft first"}>
                      Copy final text
                    </button>
                    <small className="cd-muted">Nothing is sent from here. Copy the reviewed text into your approved channel and send it yourself.</small>
                    {msg && <p className={`cd-msg cd-msg-${msg.tone}`} role="status">{msg.text}</p>}
                  </div>
                </aside>
              </div>
              <div className="cd-step-actions">
                <button type="button" className="cd-btn" onClick={() => go(3)}>‹ Review</button>
              </div>
            </section>
          )}
          {msg && step !== 4 && <p className={`cd-msg cd-msg-${msg.tone}`} role="status">{msg.text}</p>}
          <p className="cd-foot">Synthetic demo data. Card-fit values are illustrative. Internal signals (behaviour, wellness, fraud) are for the advisor and never go in client copy (RP-016).</p>
        </>}
      </div>
      {split.open
        ? <SplitHandle split={split} container={shell} controls={aiId} label="Cards AI" />
        : <SplitRail split={split} controls={aiId} label="Cards AI" />}
      {c ? <AiPanel c={c} id={aiId} hidden={!split.open} /> : <aside className="cd-ai" id={aiId} hidden={!split.open} aria-busy="true" />}
    </div>
  );
}
