/**
 * Book workspace - one account in Everyday banking, Borrowing or Investing.
 *
 *   1 Play               Support › Protect › Retain › Grow. Blocked plays stay
 *                        visible with the reason (lock + eligibility text).
 *   2 Draft              deterministic draft from the BFF, editable, with live
 *                        guardrail checks re-run as you type.
 *   3 Compliance review  the Compliance Reviewer agent (SSE) can block, never approve.
 *   4 Done               copy the final text - nothing is ever sent from here.
 *
 * The AI panel on the right is the live main agent, scoped by the account's
 * four suggested prompts, with a "Sources used" footer.
 */
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { apiGet, apiPost, streamChat, streamSSE } from "../api";
import { Markdown } from "../components/Markdown";
import { SplitHandle, SplitRail, SplitToggle, type ChatSplit } from "../components/ChatSplit";
import {
  BOOK_META, IQ_NAME, TYPE_ORDER, cad, cadShort, fmt, isEligible, isIQLayer, monthLabel, num, slug,
  type BookAccountDetail, type BookDraft, type BookId, type Check, type IQLayer, type Section, type Series, type Verdict,
} from "./types";
import "./books.css";

/* ------------------------------------------------------------ shared atoms */
export const Lock = () => (
  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden fill="none" stroke="currentColor" strokeWidth="1.6">
    <rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
  </svg>
);

export function PlayTag({ t }: { t: string }) {
  return <span className={`bk-ptype bk-ptype-${t.toLowerCase()}`}>{t}</span>;
}

/** Which IQ layer powers a section. Children replace the default label (e.g. "Foundry IQ · RP-024"). */
export function IQBadge({ iq, children, title }: { iq: IQLayer; children?: ReactNode; title?: string }) {
  return (
    <span className={`bk-iq bk-iq-${iq}`} title={title ?? `Source: ${IQ_NAME[iq]}`}>
      <i aria-hidden />{children ?? IQ_NAME[iq]}
    </span>
  );
}

export function WellnessPill({ band }: { band: string }) {
  return <span className={`bk-pill bk-band-${slug(band)}`}><i aria-hidden />{band}</span>;
}

export function Flag({ f }: { f: string }) {
  return <span className={`bk-flag bk-flag-${slug(f)}`}>{f}</span>;
}

export function LayerChips({ layers }: { layers: string[] }) {
  if (!layers.length) return null;
  return (
    <div className="bk-ai-layers" aria-label="IQ layers used">
      {layers.map((l) => <span key={l} className={`bk-ai-layer l-${l}`}>{isIQLayer(l) ? IQ_NAME[l] : `${l} IQ`}</span>)}
    </div>
  );
}

type Step = 1 | 2 | 3 | 4;
const STEPS: { id: Step; label: string }[] = [
  { id: 1, label: "Play" }, { id: 2, label: "Draft" }, { id: 3, label: "Compliance review" }, { id: 4, label: "Done" },
];
const VERDICT_LABEL: Record<Verdict, string> = { pass: "Ready", needs_approval: "Needs approval", blocked: "Blocked" };
const LINE_COLORS = ["#2c3e63", "#7c75e8", "#2f9b8f", "#b9a77f"];

/* ------------------------------------------------------------------ AI panel */
function AiPanel({ c, book, id, hidden }: { c: BookAccountDetail; book: BookId; id: string; hidden?: boolean }) {
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
      onStatus: (t) => setStatus(t ?? ""),
      onIQ: (iq, st) => { if (st === "active") setLayers((l) => (l.includes(iq) ? l : [...l, iq])); },
      onToken: (t) => setAnswer((a) => a + t),
      onMessage: (t) => setAnswer(t),
      onError: (t, d) => setAnswer(`**${t}**\n\n${d}`),
      onDone: (p) => {
        setBusy(false); setStatus("");
        if (typeof p.threadId === "string") thread.current = p.threadId;
      },
    }, ctrl.signal).catch(() => setBusy(false));
  };

  const iqs = layers.filter(isIQLayer);
  return (
    <aside className="bk-ai" id={id} hidden={hidden} aria-label={`AI assistant for ${c.customer_name}`}>
      <header>
        <span className="bk-ai-mark" aria-hidden>✦</span>
        <div><b>{BOOK_META[book].aiName}</b><small>Live agent · {c.customer_name} · {c.account_id}</small></div>
      </header>
      <div className="bk-ai-prompts">
        {c.prompts.map((p) => (
          <button key={p.label} type="button" disabled={busy} onClick={() => ask(p.prompt, p.label)}>{p.label} <span aria-hidden>↗</span></button>
        ))}
      </div>
      <div className="bk-ai-body" aria-live="polite">
        {!asked && <p className="bk-muted">Pick a prompt or ask anything about this client. Answers are grounded in Fabric IQ and policy, under your identity. "How does the market compare?" is the only prompt that uses the live web.</p>}
        {asked && <div className="bk-ai-q">{asked}</div>}
        <LayerChips layers={layers} />
        {busy && !answer && <div aria-busy="true"><div className="bk-skel bk-skel-line" /><div className="bk-skel bk-skel-line short" /><small className="bk-muted">{status}</small></div>}
        {answer && <div className="bk-ai-answer"><Markdown text={answer} /></div>}
        {answer && !busy && (
          <footer className="bk-sources" aria-label="Sources used">
            <small>Sources used</small>
            {iqs.length ? iqs.map((l) => <IQBadge key={l} iq={l} />) : <small className="bk-muted">No IQ layer reported for this answer</small>}
          </footer>
        )}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); setQ(""); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${c.customer_name.split(" ")[0]}…`} aria-label="Ask the agent" />
        <button type="submit" className="bk-btn bk-btn-primary" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </aside>
  );
}

/* -------------------------------------------------------------- 360 panels */
function domain(values: number[]): [number, number] {
  const lo = Math.min(...values), hi = Math.max(...values);
  if (!Number.isFinite(lo)) return [0, 1];
  // Tight values far from zero (an invested balance) get a padded window; everything else starts at zero.
  if (lo > 0 && lo / Math.max(hi, 1) > 0.6) {
    const pad = Math.max((hi - lo) * 0.25, hi * 0.005, 1);
    return [lo - pad, hi + pad];
  }
  const min = Math.min(0, lo), max = Math.max(0, hi);
  return [min, max === min ? min + 1 : max];
}

function SeriesChart({ s }: { s: Series }) {
  const all = s.lines.flatMap((l) => l.values.map(num));
  const [lo, hi] = domain(all);
  const y = (v: number) => 96 - ((v - lo) / (hi - lo)) * 90;
  const x = (i: number) => ((i + 0.5) / s.months.length) * 100;
  const single = s.lines.length === 1;
  const zero = lo < 0 ? y(0) : null;
  const ticks = [hi, (hi + lo) / 2, lo];
  return (
    <article className="bk-card bk-series">
      <div className="bk-card-head">
        <h3>{s.title}</h3>
        <span className="bk-legend">
          {s.lines.map((l, i) => <span key={l.label}><i style={{ background: LINE_COLORS[i % LINE_COLORS.length] }} />{l.label}</span>)}
        </span>
      </div>
      <div className="bk-sp">
        <div className="bk-sp-axis" aria-hidden>{ticks.map((t, i) => <span key={i}>{cadShort(t)}</span>)}</div>
        <div className="bk-sp-plot" role="img" aria-label={`${s.title}, ${monthLabel(s.months[0] ?? "")} to ${monthLabel(s.months[s.months.length - 1] ?? "")}`}>
          <svg className="bk-sp-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
            {zero !== null && <line x1="0" x2="100" y1={zero} y2={zero} className="bk-zero" vectorEffect="non-scaling-stroke" />}
            {single && s.lines[0] && (
              <polygon className="bk-area" points={`${x(0)},96 ${s.lines[0].values.map((v, i) => `${x(i)},${y(num(v))}`).join(" ")} ${x(s.months.length - 1)},96`} />
            )}
            {s.lines.map((l, li) => (
              <polyline key={l.label} points={l.values.map((v, i) => `${x(i)},${y(num(v))}`).join(" ")}
                        style={{ stroke: LINE_COLORS[li % LINE_COLORS.length] }} className="bk-line" vectorEffect="non-scaling-stroke" />
            ))}
          </svg>
          {s.lines.map((l, li) => {
            const last = l.values.length - 1;
            return <i key={l.label} className="bk-sp-dot" style={{ left: `${x(last)}%`, top: `${y(num(l.values[last]))}%`, background: LINE_COLORS[li % LINE_COLORS.length] }} aria-hidden />;
          })}
          <div className="bk-sp-hits" aria-hidden>
            {s.months.map((m, i) => (
              <span key={m} title={`${m}\n${s.lines.map((l) => `${l.label}: ${cad(l.values[i] ?? 0, 0)}`).join("\n")}`} />
            ))}
          </div>
        </div>
        <div className="bk-sp-months" aria-hidden>{s.months.map((m) => <span key={m}>{monthLabel(m)}</span>)}</div>
      </div>
      <details className="bk-sp-table">
        <summary>Show as table</summary>
        <div className="bk-table-wrap">
          <table>
            <thead><tr><th>Month</th>{s.lines.map((l) => <th key={l.label}>{l.label}</th>)}</tr></thead>
            <tbody>
              {s.months.map((m, i) => (
                <tr key={m}><td>{m}</td>{s.lines.map((l) => <td key={l.label}>{cad(l.values[i] ?? 0, 0)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </article>
  );
}

function SectionCard({ s }: { s: Section }) {
  const client = /same in every book/i.test(s.title);
  return (
    <article className={`bk-card bk-section${client ? " bk-section-client" : ""}`}>
      <div className="bk-card-head"><h3>{s.title}</h3><IQBadge iq="fabric" /></div>
      <dl className="bk-dl">
        {s.items.map((it) => {
          const long = typeof it.value === "string" && it.value.length > 34;
          return (
            <div key={it.label} className={long ? "bk-dl-long" : ""}>
              <dt>{it.label}</dt>
              <dd>{it.label === "Wellness band" ? <WellnessPill band={String(it.value)} /> : fmt(it.value, it.format)}</dd>
            </div>
          );
        })}
      </dl>
    </article>
  );
}

/* ----------------------------------------------------------------- outreach */
const ICON: Record<Check["status"], string> = { pass: "✓", warn: "!", block: "✕" };
function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="bk-checks">
      {checks.map((k, i) => (
        <li key={`${k.rule}-${k.name}-${i}`} className={`bk-check bk-check-${k.status}`}>
          <span className="bk-check-icon" aria-label={k.status}>{ICON[k.status]}</span>
          <div><b>{k.name}</b><small>{k.detail}</small></div>
          <code>{k.rule}</code>
        </li>
      ))}
    </ul>
  );
}

function VerdictBadge({ v }: { v: Verdict }) {
  return <span className={`bk-verdict bk-verdict-${v}`}>{v === "blocked" && <Lock />}{VERDICT_LABEL[v] ?? v}</span>;
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
export function BookAccount({ book, aid, split, onBack }: {
  book: BookId;
  aid: string;
  split: ChatSplit;
  onBack: () => void;
}) {
  const meta = BOOK_META[book];
  const base = `/api/books/${book}/account/${encodeURIComponent(aid)}`;
  const [c, setC] = useState<BookAccountDetail | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>(1);
  const [show360, setShow360] = useState(true);
  const [selIdx, setSelIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState<BookDraft | null>(null);
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
  const aiId = `bk-ai-${book}-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  useEffect(() => {
    let live = true;
    apiGet<BookAccountDetail>(base).then((r) => { if (live) setC(r); }).catch((e) => live && setError(String(e)));
    return () => { live = false; reviewAbort.current?.abort(); };
  }, [base]);

  const ordered = useMemo(() => (c?.plays ?? []).map((p, i) => ({ p, i }))
    .sort((x, y) => (TYPE_ORDER[x.p.play_type] ?? 9) - (TYPE_ORDER[y.p.play_type] ?? 9) || x.p.rank - y.p.rank), [c]);
  const play = draft?.play ?? (selIdx !== null && c ? c.plays[selIdx] : null);
  const payload = () => ({ channel: "Email", purpose: draft?.purpose ?? "Service", subject, body, play: draft?.play ?? {} });

  // Live guardrails: re-run the deterministic checks whenever the text changes.
  useEffect(() => {
    if (!draft) return;
    const seq = ++checkSeq.current;
    setChecking(true);
    const h = window.setTimeout(() => {
      apiPost<{ checks: Check[]; verdict: Verdict }>(`${base}/checks`,
        { channel: "Email", purpose: draft.purpose, subject, body, play: draft.play })
        .then((r) => { if (seq === checkSeq.current && r?.checks) { setChecks(r.checks); setVerdict(r.verdict); } })
        .catch(() => undefined)
        .finally(() => { if (seq === checkSeq.current) setChecking(false); });
    }, 350);
    return () => window.clearTimeout(h);
  }, [base, draft, subject, body]);

  const go = (s: Step) => {
    setStep(s);
    if (s > 1) setShow360(false);
    mainRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  const generate = async (idx: number) => {
    setDrafting(true); setMsg(null);
    try {
      const d = await apiPost<BookDraft>(`${base}/draft`, { playIndex: idx });
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
    await streamSSE(`${base}/review`, payload(), {
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
  const supportPlays = (c?.plays ?? []).filter((p) => p.play_type === "Support");
  const support = !!c && (c.wellness_band === "Vulnerable" || c.flags.includes("Support first") || supportPlays.length > 0);
  const kycStale = !!c && c.flags.includes("KYC stale");
  const rec = (p: { recommendation?: string; recommended_product?: string }) => p.recommendation || p.recommended_product || "";

  return (
    <div ref={shell} className={`bk-ws${split.open ? "" : " bk-ws-collapsed"}`} style={{ "--split-w": `${split.width}%` } as CSSProperties}>
      <div className="bk-ws-main" ref={mainRef}>
        <div className="bk-ws-top">
          <button type="button" className="bk-link bk-back" onClick={onBack}>← {meta.title}</button>
          <ol className="bk-steps" aria-label={`${meta.title} outreach workflow`}>
            {STEPS.map((s) => (
              <li key={s.id} className={s.id === step ? "on" : s.id < step ? "done" : ""}>
                <button type="button" disabled={locked(s.id)} aria-current={s.id === step ? "step" : undefined}
                        title={locked(s.id) ? "Choose a play and draft first" : ""}
                        onClick={() => go(s.id)}><i>{s.id < step ? "✓" : s.id}</i>{s.label}</button>
              </li>
            ))}
          </ol>
        </div>

        {error && <p className="bk-error" role="alert">Could not load {aid} ({error}).</p>}
        {!c && !error && <div aria-busy="true"><div className="bk-skel bk-skel-title" /><div className="bk-skel" /><div className="bk-skel" /></div>}

        {c && <>
          <header className="bk-ws-head">
            <div>
              <div className="bk-eyebrow">{c.account_id} · {c.customer_id} · {c.segment} · {c.branch}</div>
              <h2>{c.customer_name} <small>{c.product}</small></h2>
              <div className="bk-ws-pills">
                <WellnessPill band={c.wellness_band} />
                {c.linked_mortgage === "Y" && <span className="bk-carry" title="Wellness, consent and TDS come from the mortgage book"><b>Mortgage</b>linked · same client in every book</span>}
                {c.linked_cards === "Y" && <span className="bk-carry bk-carry-soft"><b>Card</b>linked</span>}
                {c.flags.map((f) => <Flag key={f} f={f} />)}
                <span className="bk-tag">Email marketing {c.email_consent.toLowerCase()}</span>
              </div>
            </div>
            <SplitToggle split={split} controls={aiId} className="bk-btn bk-btn-ghost" />
          </header>

          {book === "investing" && (
            <div className="bk-banner bk-banner-advisor" role="note">
              <span className="bk-banner-mark" aria-hidden>⚖</span>
              <div><b>Recommendations go through a licensed advisor (RP-027)</b>
                <p>
                  This workspace prepares the conversation - it never recommends a product. A licensed advisor confirms suitability and the
                  risk profile first, and nothing here may promise a return.
                  {kycStale ? " KYC is older than 36 months: every recommendation is blocked until it is refreshed." : ""}
                </p>
              </div>
            </div>
          )}
          {support && (
            <div className="bk-banner" role="note">
              <span className="bk-banner-mark" aria-hidden>◐</span>
              <div><b>Support first · lead with help, not products (RP-012)</b>
                <p>
                  {supportPlays.length
                    ? supportPlays.map((p) => `${p.play}: ${p.rationale}.`).join(" ")
                    : `Wellness band ${c.wellness_band}.`}
                  {" "}Keep the tone helpful, never urgent. Growth offers wait until the client is on steady ground.
                </p>
              </div>
            </div>
          )}

          <section className={`bk-360${show360 ? "" : " bk-360-closed"}`} aria-label="Account 360">
            <button type="button" className="bk-360-toggle" aria-expanded={show360} onClick={() => setShow360(!show360)}>
              <span>Account 360</span><small>12-month trend · {c.sections.map((s) => s.title.replace(/\s*\(.*\)$/, "").toLowerCase()).join(" · ")}</small>
              <IQBadge iq="fabric" /><i aria-hidden>{show360 ? "−" : "+"}</i>
            </button>
            {show360 && (
              <div className="bk-360-grid">
                <SeriesChart s={c.series} />
                {c.sections.map((s) => <SectionCard key={s.title} s={s} />)}
              </div>
            )}
          </section>

          {step === 1 && (
            <section className="bk-step" aria-labelledby={`${aiId}-s1`}>
              <div className="bk-step-head">
                <h3 id={`${aiId}-s1`}>Plays</h3><span>Support › Protect › Retain › Grow · rules applied before AI</span>
                <span className="bk-iqs"><IQBadge iq="fabric" /><IQBadge iq="foundry">Foundry IQ · {[...new Set(c.plays.map((p) => p.policy))].join(" · ") || "policies"}</IQBadge></span>
              </div>
              {!ordered.length && <p className="bk-empty bk-card">No play for this client - they look well served. Nothing to send.</p>}
              <ol className="bk-actions">
                {ordered.map(({ p, i }) => {
                  const ok = isEligible(p.eligibility);
                  const sel = selIdx === i;
                  return (
                    <li key={i} className={`bk-action${ok ? "" : " bk-action-blocked"}${sel ? " bk-action-sel" : ""}`}>
                      <PlayTag t={p.play_type} />
                      <div className="bk-action-body">
                        <b>{p.play}{rec(p) && <span> · {rec(p)}</span>}</b>
                        <small>{p.rationale}</small>
                        {!ok && <small className="bk-lock"><Lock />{p.eligibility}</small>}
                      </div>
                      <span className="bk-action-val" title="Value at stake">{num(p.value_at_stake_cad) ? cad(p.value_at_stake_cad, 0) : ""}<code>{p.policy}</code></span>
                      <button type="button" className={`bk-btn${ok ? " bk-btn-primary" : ""}`} disabled={drafting}
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
            <section className="bk-step" aria-labelledby={`${aiId}-s2`}>
              <div className="bk-step-head">
                <h3 id={`${aiId}-s2`}>Draft</h3><span>Deterministic draft · edit freely · checks re-run as you type</span>
                <span className="bk-iqs"><IQBadge iq="fabric" /><IQBadge iq="foundry">Foundry IQ · checks</IQBadge></span>
              </div>
              <div className="bk-compose-controls">
                <label className="bk-field">
                  <span>Play</span>
                  <select value={selIdx ?? ""} disabled={drafting}
                          onChange={(e) => { const i = Number(e.target.value); if (Number.isFinite(i)) generate(i); }}>
                    {selIdx === null && <option value="">Choose a play…</option>}
                    {ordered.map(({ p, i }) => (
                      <option key={i} value={i}>{p.play_type} · {p.play}{isEligible(p.eligibility) ? "" : ` (blocked: ${p.eligibility})`}</option>
                    ))}
                  </select>
                </label>
                <div className="bk-field"><span>Channel · purpose</span><div className="bk-purpose">Email · {draft?.purpose ?? "—"}</div></div>
              </div>
              {play && !isEligible(play.eligibility) && (
                <p className="bk-inline-warn"><Lock /> This play is not eligible ({play.eligibility}). The draft is shown so you can see why it cannot be used.</p>
              )}
              {!draft ? <p className="bk-empty">{drafting ? "Drafting…" : "Choose a play to draft the outreach."}</p> : (
                <div className="bk-compose">
                  <div className="bk-editor">
                    <label className="bk-field"><span>Subject</span>
                      <input value={subject} onChange={(e) => setSubject(e.target.value)} />
                    </label>
                    <label className="bk-field"><span>Message · {draft.purpose.toLowerCase()} email</span>
                      <textarea className="bk-body" value={body} rows={14} onChange={(e) => setBody(e.target.value)} />
                    </label>
                    <small className="bk-muted">Drafted deterministically from Fabric IQ facts. Edit freely - the checks re-run as you type. AI-assisted text is labelled as a draft (RP-017).</small>
                  </div>
                  <aside className="bk-guard" aria-live="polite">
                    <div className="bk-guard-head"><b>Pre-send checks</b>{checking ? <small className="bk-muted">checking…</small> : <VerdictBadge v={verdict} />}</div>
                    <CheckList checks={checks} />
                  </aside>
                </div>
              )}
              <div className="bk-step-actions">
                <button type="button" className="bk-btn" onClick={() => go(1)}>‹ Plays</button>
                <button type="button" className="bk-btn bk-btn-primary" disabled={!draft} onClick={() => go(3)}>Compliance review ›</button>
              </div>
            </section>
          )}

          {step === 3 && draft && (
            <section className="bk-step" aria-labelledby={`${aiId}-s3`}>
              <div className="bk-step-head">
                <h3 id={`${aiId}-s3`}>Compliance review</h3><span>Compliance Reviewer agent · can block, never approves</span>
                <span className="bk-iqs"><IQBadge iq="foundry" /></span>
              </div>
              <div className="bk-review-grid">
                <div className="bk-card bk-review">
                  <div className="bk-review-top">
                    <div>
                      <small>Reviewer verdict</small>
                      {parsed.verdict
                        ? <span className={`bk-rv bk-rv-${parsed.verdict.split(" ")[0].toLowerCase()}`}>{parsed.verdict}</span>
                        : <span className="bk-rv bk-rv-none">{reviewing ? "Reviewing…" : "Not reviewed yet"}</span>}
                      {stale && <small className="bk-stale">Reviewed an earlier version</small>}
                    </div>
                    <button type="button" className={`bk-btn${review ? "" : " bk-btn-primary"}`} disabled={reviewing} onClick={runReview}>
                      {review ? "Re-run review" : "Run compliance review"}
                    </button>
                  </div>
                  {reviewing && !review && <div aria-busy="true"><div className="bk-skel bk-skel-line" /><div className="bk-skel bk-skel-line short" /></div>}
                  {review && <div className="bk-review-body"><Markdown text={parsed.shown} /></div>}
                  {parsed.corrected && !reviewing && (
                    <div className="bk-review-fix">
                      <button type="button" className="bk-btn bk-btn-primary" disabled={usedCorrection} onClick={useCorrected}>
                        {usedCorrection ? "Corrected draft applied" : "Use corrected draft"}
                      </button>
                      <small className="bk-muted">Replaces the subject and message, then re-runs the checks.</small>
                    </div>
                  )}
                  {!review && !reviewing && <p className="bk-muted bk-small">The reviewer reads the draft with the deterministic findings as authoritative, then judges tone, implied promises, fairness and privacy.</p>}
                </div>
                <aside className="bk-guard">
                  <div className="bk-guard-head"><b>Deterministic checks</b>{checking ? <small className="bk-muted">checking…</small> : <VerdictBadge v={verdict} />}</div>
                  <CheckList checks={checks} />
                  {usedCorrection && <details className="bk-preview"><summary>Current draft</summary><p><b>{subject}</b></p><pre>{body}</pre></details>}
                </aside>
              </div>
              <div className="bk-step-actions">
                <button type="button" className="bk-btn" onClick={() => go(2)}>‹ Edit draft</button>
                <button type="button" className="bk-btn bk-btn-primary" onClick={() => go(4)}>Done ›</button>
              </div>
            </section>
          )}

          {step === 4 && draft && (
            <section className="bk-step" aria-labelledby={`${aiId}-s4`}>
              <div className="bk-step-head"><h3 id={`${aiId}-s4`}>Done</h3><VerdictBadge v={verdict} /></div>
              <div className="bk-review-grid">
                <div className="bk-card">
                  <div className="bk-preview-mail">
                    <small>Email draft · {play?.play_type} · {play?.play}</small>
                    <b>{subject}</b>
                    <pre>{body}</pre>
                  </div>
                </div>
                <aside className="bk-guard">
                  <div className="bk-guard-head"><b>Release gate</b><VerdictBadge v={verdict} /></div>
                  <ul className="bk-gate">
                    <li className={verdict !== "blocked" ? "ok" : "no"}>{verdict !== "blocked" ? "✓" : "✕"} No blocking findings</li>
                    <li className={review && !stale ? "ok" : "no"}>{review && !stale ? "✓" : "○"} Compliance review on this version</li>
                    <li className={play && isEligible(play.eligibility) ? "ok" : "no"}>{play && isEligible(play.eligibility) ? "✓" : "✕"} Play is eligible</li>
                    {book === "investing" && <li className="no">○ Licensed advisor confirms suitability before any recommendation</li>}
                  </ul>
                  <div className="bk-wrap-actions">
                    <button type="button" className="bk-btn bk-btn-primary" disabled={!canCopy} onClick={copyFinal}
                            title={canCopy ? "" : "Blocked by the checks - fix the draft first"}>
                      Copy final text
                    </button>
                    <small className="bk-muted">Nothing is sent from here. Copy the reviewed text into your approved channel and send it yourself.</small>
                    {msg && <p className={`bk-msg bk-msg-${msg.tone}`} role="status">{msg.text}</p>}
                  </div>
                </aside>
              </div>
              <div className="bk-step-actions">
                <button type="button" className="bk-btn" onClick={() => go(3)}>‹ Review</button>
              </div>
            </section>
          )}
          {msg && step !== 4 && <p className={`bk-msg bk-msg-${msg.tone}`} role="status">{msg.text}</p>}
          <p className="bk-foot">Synthetic demo data. Internal signals (wellness, TDS, flags) are for the advisor and never go in client copy (RP-016).</p>
        </>}
      </div>
      {split.open
        ? <SplitHandle split={split} container={shell} controls={aiId} label={meta.aiName} />
        : <SplitRail split={split} controls={aiId} label={meta.aiName} />}
      {c ? <AiPanel c={c} book={book} id={aiId} hidden={!split.open} /> : <aside className="bk-ai" id={aiId} hidden={!split.open} aria-busy="true" />}
    </div>
  );
}
