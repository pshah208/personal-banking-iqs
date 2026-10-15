/**
 * Product book - Everyday banking, Borrowing or Investing, from one contract.
 *
 * Overview KPIs and charts (Fabric IQ), the IQ strip (Fabric tables, Foundry
 * policies, and Work IQ / Web IQ questions streamed live), plays in
 * Support → Protect → Retain → Grow order (click to filter), and every account
 * with its top play and eligibility. Clicking a row opens the workspace
 * (BookAccount). Everything renders from `/api/books/{book}/*`.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { apiGet, streamChat } from "../api";
import { useChatSplit } from "../components/ChatSplit";
import { Markdown } from "../components/Markdown";
import { MissionPanel } from "../components/MissionPanel";
import { BookAccount, Flag, IQBadge, LayerChips, Lock, PlayTag } from "./BookAccount";
import {
  BOOK_META, TYPE_ORDER, cad, cadShort, fmt, fmtKpi, isEligible, monthLabel, num, playKey, supportBand,
  type BookAccountDetail, type BookId, type BookOverview, type BookRow, type Chart, type Column, type IQLayer, type Play,
} from "./types";
import "./books.css";

type Filter = "All" | "Support first" | "Blocked" | "Linked mortgage" | "Linked card";
const FILTERS: Filter[] = ["All", "Support first", "Blocked", "Linked mortgage", "Linked card"];

function matches(r: BookRow, f: Filter): boolean {
  switch (f) {
    case "Support first": return r.flags.includes("Support first") || r.top_play?.play_type === "Support" || r.wellness_band === "Vulnerable";
    case "Blocked": return !!r.top_play && !isEligible(r.top_play.eligibility);
    case "Linked mortgage": return r.linked_mortgage === "Y";
    case "Linked card": return r.linked_cards === "Y";
    default: return true;
  }
}

const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function jumpTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  // Scroll only the page pane - scrollIntoView would also shift overflow:hidden ancestors (the app shell).
  const pane = el.closest<HTMLElement>(".bk-page");
  if (pane) {
    const top = el.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop - 12;
    pane.scrollTo({ top, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }
  el.focus({ preventScroll: true });
}

const hhmm = (iso?: string) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
};

/* ------------------------------------------------------------------ charts */
const isMonth = (s: string) => /^\d{4}-\d{2}$/.test(s);
const TYPE_COLOR: Record<string, string> = { Support: "#7c75e8", Protect: "#3a9bb0", Retain: "#8a9bb4", Grow: "#2f9b8f" };
/** Support-first KPIs get the calm indigo tint (never red). */
const SUPPORT_KPIS = new Set(["nsf", "past_due", "kyc"]);
const PALETTE = ["var(--brand)", "#7c75e8", "#2f9b8f", "#3a9bb0", "#b9a77f", "#8a8a93"];

function moneyish(c: Chart) {
  return c.data.some((d) => Math.abs(d.value) >= 1000);
}
const chartVal = (c: Chart, v: number) => (moneyish(c) ? cadShort(v) : num(v).toLocaleString("en-CA"));

function ChartCard({ c }: { c: Chart }) {
  const max = Math.max(1, ...c.data.map((d) => d.value));
  const total = c.data.reduce((s, d) => s + d.value, 0);
  if (c.kind === "bars") {
    const first = c.data[0]?.value ?? 0, last = c.data[c.data.length - 1]?.value ?? 0;
    const months = c.data.every((d) => isMonth(d.label));
    const chg = first ? ((last - first) / Math.abs(first)) * 100 : 0;
    return (
      <article className="bk-card bk-chart">
        <div className="bk-card-head">
          <h3>{c.title}</h3>
          {months ? <span className={chg < 0 ? "bk-down" : "bk-up"}>{chg < 0 ? "▼" : "▲"} {Math.abs(chg).toFixed(1)}% vs 12 mo ago</span> : <IQBadge iq="fabric" />}
        </div>
        <div className="bk-vbars" style={{ gridTemplateColumns: `repeat(${c.data.length}, minmax(0, 1fr))` }}
             role="img" aria-label={`${c.title}: ${c.data.map((d) => `${d.label} ${chartVal(c, d.value)}`).join(", ")}`}>
          {c.data.map((d, i) => (
            <div key={d.label} className="bk-vbar" title={`${d.label}: ${chartVal(c, d.value)}`}>
              {!months && <em>{chartVal(c, d.value)}</em>}
              <span style={{ height: `${(Math.max(0, d.value) / max) * 100}%`, animationDelay: `${i * 18}ms` }} className={months && i === c.data.length - 1 ? "bk-last" : ""} />
              <small title={d.label}>{months ? monthLabel(d.label).slice(0, 1) : d.label}</small>
            </div>
          ))}
        </div>
        <p className="bk-chart-foot">{months ? <><b>{chartVal(c, last)}</b> last month · peak {chartVal(c, max)}</> : <>{c.source} · total <b>{chartVal(c, total)}</b></>}</p>
      </article>
    );
  }
  if (c.kind === "hbars") {
    return (
      <article className="bk-card bk-chart">
        <div className="bk-card-head"><h3>{c.title}</h3><IQBadge iq="fabric" /></div>
        <ul className="bk-hbars">
          {c.data.map((d, i) => (
            <li key={d.label}>
              <span className="bk-hbar-label" title={d.label}>{d.label}</span>
              <span className="bk-hbar-track"><i style={{ width: `${(Math.max(0, d.value) / max) * 100}%`, animationDelay: `${i * 30}ms` }} /></span>
              <b>{chartVal(c, d.value)}</b>
            </li>
          ))}
        </ul>
        <p className="bk-chart-foot">{c.source} · total <b>{chartVal(c, total)}</b></p>
      </article>
    );
  }
  const color = (label: string, i: number) => TYPE_COLOR[label] ?? PALETTE[i % PALETTE.length];
  return (
    <article className="bk-card bk-chart">
      <div className="bk-card-head"><h3>{c.title}</h3><IQBadge iq="fabric" /></div>
      <div className="bk-stack" role="img" aria-label={c.data.map((d) => `${d.label} ${d.value}`).join(", ")}>
        {c.data.filter((d) => d.value > 0).map((d, i) => <span key={d.label} style={{ flexGrow: d.value, background: color(d.label, i), animationDelay: `${i * 30}ms` }} title={`${d.label}: ${d.value}`} />)}
      </div>
      <ul className="bk-stack-legend">
        {c.data.map((d, i) => (
          <li key={d.label} className={d.value ? "" : "bk-zero-row"}>
            <i style={{ background: color(d.label, i) }} aria-hidden />
            <span>{d.label}</span>
            <b>{chartVal(c, d.value)}</b>
            <small>{total ? Math.round((d.value / total) * 100) : 0}%</small>
          </li>
        ))}
      </ul>
    </article>
  );
}

/* ------------------------------------------------ Work IQ / Web IQ answers */
interface Ask { answer: string; layers: string[]; status: string; busy: boolean; error: string; doneAt: string }
const EMPTY: Ask = { answer: "", layers: [], status: "", busy: false, error: "", doneAt: "" };

function useAsk() {
  const [s, setS] = useState<Ask>(EMPTY);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  const ask = async (prompt: string) => {
    if (s.busy || !prompt) return;
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setS({ ...EMPTY, busy: true });
    await streamChat(prompt, null, {
      onStatus: (t) => setS((x) => ({ ...x, status: t ?? "" })),
      onIQ: (iq, st) => { if (st === "active") setS((x) => (x.layers.includes(iq) ? x : { ...x, layers: [...x.layers, iq] })); },
      onToken: (t) => setS((x) => ({ ...x, answer: x.answer + t })),
      onMessage: (t) => setS((x) => ({ ...x, answer: t })),
      onError: (t, d) => setS((x) => ({ ...x, error: [t, d].filter(Boolean).join(" ") })),
      onDone: () => setS((x) => ({ ...x, busy: false, status: "", doneAt: new Date().toISOString() })),
    }, ctrl.signal).catch((e) => { if (!ctrl.signal.aborted) setS((x) => ({ ...x, error: String(e) })); });
    if (!ctrl.signal.aborted) setS((x) => ({ ...x, busy: false }));
  };
  return { s, ask };
}

function AskPanel({ id, iq, title, button, note, prompt, state, onAsk }: {
  id: string; iq: IQLayer; title: string; button: string; note: string; prompt: string; state: Ask; onAsk: () => void;
}) {
  const { answer, busy, error, layers, status, doneAt } = state;
  return (
    <section id={id} className={`bk-card bk-panel bk-ask bk-ask-${iq}`} aria-labelledby={`${id}-h`} tabIndex={-1}>
      <div className="bk-card-head">
        <div className="bk-panel-title"><h3 id={`${id}-h`}>{title}</h3><IQBadge iq={iq} /></div>
        <button type="button" className={`bk-btn bk-btn-sm${answer ? " bk-btn-ghost" : " bk-btn-primary"}`} disabled={busy} onClick={onAsk}>
          {busy ? "Asking…" : answer ? "Ask again" : button}
        </button>
      </div>
      <p className="bk-panel-note">{note}</p>
      <LayerChips layers={layers} />
      {busy && <p className="bk-iq-status" role="status"><span className="bk-spin" aria-hidden />{status || `${iq === "work" ? "Work IQ is reading recent mail and chats" : "Web IQ is searching the public web"}…`}</p>}
      <div aria-live="polite">
        {busy && !answer && <div aria-busy="true"><div className="bk-skel bk-skel-line" /><div className="bk-skel bk-skel-line" /><div className="bk-skel bk-skel-line short" /></div>}
        {error && <p className="bk-error" role="alert">{iq === "work" ? "Work IQ" : "Web IQ"} could not answer: {error}</p>}
        {answer && <div className="bk-ask-answer"><Markdown text={answer} /></div>}
      </div>
      {!answer && !busy && !error && <p className="bk-ask-empty">{prompt}</p>}
      {doneAt && !busy && answer && (
        <p className="bk-iq-status bk-iq-done">Answered at {hhmm(doneAt)} · internal context for the advisor, never for client copy (RP-016)</p>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------- view */
export function BookView({ book, active, bankName }: { book: BookId; active: boolean; bankName?: string }) {
  const meta = BOOK_META[book];
  const [overview, setOverview] = useState<BookOverview | null>(null);
  const [rows, setRows] = useState<BookRow[] | null>(null);
  const [columns, setColumns] = useState<Column[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("All");
  const [play, setPlay] = useState<string | null>(null);
  const [allPlays, setAllPlays] = useState<Record<string, Play[]> | null>(null);
  const [loadingPlays, setLoadingPlays] = useState(false);
  const [q, setQ] = useState("");
  const [openAid, setOpenAid] = useState<string | null>(null);
  const split = useChatSplit(`pb.${book}.ai`, 32, 22, 60);
  const work = useAsk();
  const web = useAsk();
  const sec = (s: string) => `bk-${book}-${s}`;

  useEffect(() => {
    if (!active || rows) return;
    apiGet<{ columns: Column[]; accounts: BookRow[] }>(`/api/books/${book}/accounts`)
      .then((r) => { setRows(r.accounts ?? []); setColumns(r.columns ?? []); })
      .catch((e) => setError(String(e)));
    apiGet<BookOverview>(`/api/books/${book}/overview`).then(setOverview).catch(() => undefined);
  }, [active, rows, book]);

  // A play can sit below the top play, so filtering needs every account's full play list.
  const choosePlay = (key: string) => {
    const next = play === key ? null : key;
    setPlay(next);
    if (next) window.setTimeout(() => jumpTo(sec("accounts")), 60);
    if (!next || allPlays || loadingPlays || !rows) return;
    setLoadingPlays(true);
    const base: Record<string, Play[]> = {};
    rows.forEach((r) => { base[r.account_id] = r.top_play ? [r.top_play] : []; });
    Promise.all(rows.filter((r) => r.plays > 1).map((r) =>
      apiGet<BookAccountDetail>(`/api/books/${book}/account/${encodeURIComponent(r.account_id)}`)
        .then((d) => { base[r.account_id] = d.plays ?? base[r.account_id]; }).catch(() => undefined)))
      .then(() => setAllPlays(base))
      .finally(() => setLoadingPlays(false));
  };

  const listFor = (r: BookRow) => allPlays?.[r.account_id] ?? (r.top_play ? [r.top_play] : []);
  const playFor = (r: BookRow): Play | null => (play ? listFor(r).find((p) => playKey(p) === play) ?? null : r.top_play);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter((r) => {
      if (!matches(r, filter)) return false;
      if (play && !listFor(r).some((p) => playKey(p) === play)) return false;
      return `${r.customer_name} ${r.account_id} ${r.customer_id} ${r.segment} ${r.branch} ${r.product} ${r.flags.join(" ")}`.toLowerCase().includes(needle);
    });
  }, [rows, filter, play, allPlays, q]);

  const plays = useMemo(() => [...(overview?.plays ?? [])]
    .sort((a, b) => (TYPE_ORDER[a.play_type] ?? 9) - (TYPE_ORDER[b.play_type] ?? 9)), [overview]);
  const policies = overview?.iq.foundry ?? [];
  const tables = overview?.iq.fabric ?? [];
  const playLabel = plays.find((p) => playKey(p) === play);

  const askWork = () => { jumpTo(sec("work")); work.ask(overview?.iq.work_prompt ?? ""); };
  const askWeb = () => { jumpTo(sec("web")); web.ask(overview?.iq.web_prompt ?? ""); };

  return (
    <section className={`bk-root bk-book-${book}`} hidden={!active} aria-label={`${meta.title} book`}>
      <header className={`bk-head${openAid ? " bk-head-tight" : ""}`}>
        <div>
          <div className="bk-eyebrow">{meta.title} book · Fabric IQ</div>
          <h1><span className="bk-h1-book">{meta.title} ·</span> {meta.headline}</h1>
          <p>
            {rows ? rows.length : "–"} {meta.noun}{bankName ? ` at ${bankName}` : ""} · {overview?.tagline ?? "loading…"}
          </p>
        </div>
        <div className="bk-head-meta">
          <span className="bk-badge">Synthetic data</span>
          {overview?.as_of && <IQBadge iq="fabric" title="KPIs, charts and accounts come from Fabric IQ">Fabric IQ · as of <time dateTime={overview.as_of}>{overview.as_of}</time></IQBadge>}
        </div>
      </header>

      <div className="bk-page" hidden={!!openAid}>
        <section className="bk-kpis" aria-label={`${meta.title} summary`} style={{ "--n": Math.max(1, overview?.kpis.length ?? 8) } as CSSProperties}>
          {(overview?.kpis ?? Array.from({ length: 8 }, () => null)).map((k, i) => k ? (
            <div key={k.id} className={`bk-kpi${SUPPORT_KPIS.has(k.id) ? " bk-kpi-support" : ""}`} title={k.hint}>
              <small>{k.label}</small>
              <b>{fmtKpi(k.value, k.format)}</b>
              <span>{k.hint}</span>
            </div>
          ) : <div key={i} className="bk-kpi bk-skel" />)}
        </section>

        <MissionPanel book={book} active={active} bankName={bankName} />

        <section className="bk-iqstrip" aria-label="How the IQ layers work here">
          <div className="bk-iqstrip-head"><h2>How the IQ layers work here</h2><span>Fabric and Foundry tiles jump to what they power · Work and Web IQ ask live</span></div>
          <ul>
            <li>
              <button type="button" className="bk-iqtile bk-iqtile-fabric" onClick={() => jumpTo(sec("portfolio"))}>
                <span className="bk-iqtile-top"><IQBadge iq="fabric" /><span className="bk-iqtile-go">Portfolio & accounts <span aria-hidden>↓</span></span></span>
                <b>The {meta.title.toLowerCase()} book - {rows?.length ?? "–"} accounts, 12 months of history, ranked plays.</b>
                <small className="bk-mono">{tables.join(" · ") || "…"}</small>
              </button>
            </li>
            <li>
              <button type="button" className="bk-iqtile bk-iqtile-foundry" onClick={() => jumpTo(sec("plays"))}>
                <span className="bk-iqtile-top"><IQBadge iq="foundry" /><span className="bk-iqtile-go">Plays <span aria-hidden>↓</span></span></span>
                <b>What we may do - eligibility, consent and support-first rules applied before any AI.</b>
                <small className="bk-mono">{policies.join(" · ") || "…"}</small>
              </button>
            </li>
            <li>
              <button type="button" className="bk-iqtile bk-iqtile-work" onClick={askWork} disabled={!overview || work.s.busy}>
                <span className="bk-iqtile-top"><IQBadge iq="work" /><span className="bk-iqtile-go">{work.s.busy ? "Asking…" : work.s.answer ? "Answered ↓" : "Ask live"}</span></span>
                <b>What are colleagues saying?</b>
                <small>Email, Teams and meeting notes under your identity · internal only</small>
              </button>
            </li>
            <li>
              <button type="button" className="bk-iqtile bk-iqtile-web" onClick={askWeb} disabled={!overview || web.s.busy}>
                <span className="bk-iqtile-top"><IQBadge iq="web" /><span className="bk-iqtile-go">{web.s.busy ? "Searching…" : web.s.answer ? "Answered ↓" : "Ask live"}</span></span>
                <b>What is the market doing?</b>
                <small>Public web only · dated, sourced, issuer-neutral</small>
              </button>
            </li>
          </ul>
        </section>

        <div className="bk-section-head bk-section-head-iq bk-portfolio-head" id={sec("portfolio")} tabIndex={-1}>
          <h2>Portfolio</h2>
          <span>{overview?.tagline ?? ""}</span>
          <IQBadge iq="fabric" />
        </div>
        {overview && (
          <section className="bk-charts" aria-label="Portfolio charts" style={{ "--n": Math.max(1, overview.charts.length) } as CSSProperties}>
            {overview.charts.map((c) => <ChartCard key={c.id} c={c} />)}
          </section>
        )}
        {!overview && !error && <div className="bk-skel-row" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="bk-skel bk-skel-chart" />)}</div>}

        <section className="bk-plays-wrap" aria-labelledby={`${sec("plays")}-h`} id={sec("plays")} tabIndex={-1}>
          <div className="bk-section-head bk-section-head-iq">
            <h2 id={`${sec("plays")}-h`}>Plays</h2>
            <span>Support › Protect › Retain › Grow · click a play to filter the accounts</span>
            <span className="bk-iqs"><IQBadge iq="fabric" /><IQBadge iq="foundry" title="Each play leans on a policy in the Foundry IQ knowledge base">Foundry IQ · {policies.length ? `${policies[0]}–${policies[policies.length - 1].replace("RP-", "")}` : "policies"}</IQBadge></span>
          </div>
          <div className="bk-plays" style={{ "--n": Math.max(1, plays.length) } as CSSProperties}>
            {plays.map((m) => {
              const key = playKey(m);
              return (
                <button key={key} type="button" className={`bk-play bk-play-${m.play_type.toLowerCase()}`} aria-pressed={play === key}
                        onClick={() => choosePlay(key)}>
                  <span className="bk-play-top"><PlayTag t={m.play_type} /><code>{m.policy}</code></span>
                  <b>{m.play}</b>
                  <span className="bk-play-counts">
                    <span><strong>{m.eligible}</strong> eligible</span>
                    <span className={m.blocked ? "bk-play-blocked" : "bk-muted"}>{m.blocked ? <Lock /> : null}<strong>{m.blocked}</strong> blocked</span>
                  </span>
                  <small>{m.explain}</small>
                </button>
              );
            })}
            {!overview && [0, 1, 2, 3, 4].map((i) => <div key={i} className="bk-skel bk-skel-play" />)}
          </div>
        </section>

        <section className="bk-context" aria-label="Colleague and market context">
          <AskPanel id={sec("work")} iq="work" title="What are colleagues saying?" button="Ask Work IQ"
                    note="Grounded on the signed-in user's mail, Teams and meeting notes (Work IQ). Internal context only."
                    prompt={overview?.iq.work_prompt ?? ""} state={work.s} onAsk={askWork} />
          <AskPanel id={sec("web")} iq="web" title="What is the market doing?" button="Ask Web IQ"
                    note="Public web only - the one live external source. Issuer-neutral, dated and sourced; never for client copy (RP-016)."
                    prompt={overview?.iq.web_prompt ?? ""} state={web.s} onAsk={askWeb} />
        </section>

        <div className="bk-section-head bk-section-head-iq bk-accounts-head" id={sec("accounts")} tabIndex={-1}>
          <h2>Accounts</h2>
          <span>every account with the play that decides the conversation · click to open</span>
          <IQBadge iq="fabric" />
        </div>
        <div className="bk-toolbar">
          <div className="bk-chips" role="group" aria-label={`Filter ${meta.title} accounts`}>
            {FILTERS.map((f) => (
              <button key={f} type="button" className="bk-chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f === "Blocked" && <Lock />}{f}<b>{(rows ?? []).filter((r) => matches(r, f)).length}</b>
              </button>
            ))}
            {play && (
              <button type="button" className="bk-chip bk-chip-play" onClick={() => setPlay(null)} aria-label={`Clear play filter ${playLabel?.play ?? play}`}>
                Play: {playLabel ? `${playLabel.play_type} · ${playLabel.play}` : play}{loadingPlays ? <small>loading…</small> : <b aria-hidden>✕</b>}
              </button>
            )}
          </div>
          <label className="bk-search">
            <span className="bk-sr">Search {meta.title} accounts</span>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, branch, flag…" />
          </label>
        </div>

        {error && <p className="bk-error" role="alert">Could not load {meta.title} accounts ({error}).</p>}

        <div className="bk-card bk-list-card">
          {!rows && !error && <div className="bk-skel-list" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="bk-skel" />)}</div>}
          {rows && (
            <div className="bk-table-scroll">
              <table className="bk-table">
                <thead>
                  <tr>
                    <th scope="col" className="bk-th-who">Client</th>
                    {columns.map((c) => <th key={c.key} scope="col" className={c.format === "text" ? "" : "bk-num"}>{c.label}</th>)}
                    <th scope="col" className="bk-th-play">{play ? "Play" : "Top play"}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const p = playFor(r);
                    const ok = p ? isEligible(p.eligibility) : true;
                    const support = r.top_play?.play_type === "Support" || supportBand(r.wellness_band) && r.flags.includes("Support first");
                    return (
                      <tr key={r.account_id} className={`bk-row${support ? " bk-row-support" : ""}`} onClick={() => setOpenAid(r.account_id)}>
                        <td className="bk-c-who">
                          <button type="button" className="bk-row-open" onClick={(e) => { e.stopPropagation(); setOpenAid(r.account_id); }}
                                  aria-label={`Open ${r.customer_name}, ${r.account_id}`}>
                            {r.customer_name}
                          </button>
                          <small>{r.account_id} · {r.branch}</small>
                          {r.flags.length > 0 && <span className="bk-c-flags">{r.flags.map((f) => <Flag key={f} f={f} />)}</span>}
                        </td>
                        {columns.map((c) => {
                          const v = r.values[c.key];
                          const zero = c.format !== "text" && num(v) === 0;
                          return <td key={c.key} className={`${c.format === "text" ? "" : "bk-num"}${zero ? " bk-zero-val" : ""}`}>{c.format === "cad" ? (zero ? "—" : cad(v)) : fmt(v, c.format)}</td>;
                        })}
                        <td className={`bk-c-play${ok ? "" : " bk-blocked"}`}>
                          {p ? <>
                            <span className="bk-c-playline"><PlayTag t={p.play_type} /><span className="bk-c-playname">{p.play}</span></span>
                            {ok
                              ? <small>{num(p.value_at_stake_cad) ? `${cad(p.value_at_stake_cad, 0)} at stake · ` : ""}{p.policy}</small>
                              : <small className="bk-lock"><Lock />{p.eligibility}</small>}
                          </> : <small className="bk-muted">No play - well served</small>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {rows && !shown.length && !loadingPlays && (
            <p className="bk-empty">No accounts match. <button type="button" className="bk-link" onClick={() => { setFilter("All"); setPlay(null); setQ(""); }}>Clear filters</button></p>
          )}
          {rows && !shown.length && loadingPlays && <p className="bk-empty">Loading every account's plays…</p>}
        </div>
        <p className="bk-foot">
          Synthetic demo data · {rows?.length ?? 0} accounts · {shown.length} shown{overview?.as_of ? ` · Fabric IQ as of ${overview.as_of}` : ""}.
          The same clients appear in every book - wellness band, consent and TDS are identical across books. Internal signals are for the advisor only (RP-016).
        </p>
      </div>

      {openAid && (
        <BookAccount key={openAid} book={book} aid={openAid} split={split} onBack={() => setOpenAid(null)} />
      )}
    </section>
  );
}
