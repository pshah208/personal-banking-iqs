/**
 * Cards book - portfolio intelligence for the card portfolio.
 *
 * Overview (KPIs, spend, behaviour and product mix), the six plays in
 * Support → Protect → Retain → Grow order (click to filter), and every card
 * account with the signal that decides the conversation. Clicking a row opens
 * the card workspace (CardAccount). Card holders who also hold a mortgage carry
 * their wellness band, consent and TDS across from the mortgage book.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, streamChat } from "../api";
import { useBrand } from "../useBrand";
import { useChatSplit } from "../components/ChatSplit";
import { Markdown } from "../components/Markdown";
import { MissionPanel } from "../components/MissionPanel";
import { BehaviourPill, CardAccount, IQBadge, Lock, PlayTag } from "./CardAccount";
import {
  CAT_LABEL, OFFER_CATEGORIES, PLAY_META, cad, cadShort, isEligible, isIQLayer, isOwnBankOffer, monthLabel, normaliseMarket, safeUrl, slug, supportBand,
  type CardAccountDetail, type CardProduct, type CardRow, type CardsOverview, type IQLayer, type MarketData, type MarketOffer, type Play,
} from "./types";
import "./cards.css";

type Flag = "Support-first" | "Linked mortgage" | "Fraud alert" | "Fee due ≤60d";
const FILTERS: ("All" | Flag)[] = ["All", "Support-first", "Linked mortgage", "Fraud alert", "Fee due ≤60d"];

function flagsOf(r: CardRow): Flag[] {
  const f: Flag[] = [];
  if (supportBand(r.wellness_band) || r.behaviour === "Persistent debt") f.push("Support-first");
  if (r.linked_mortgage === "Y") f.push("Linked mortgage");
  if (r.fraud_alerts_90d > 0) f.push("Fraud alert");
  if (r.annual_fee > 0 && r.fee_anniversary_days <= 60) f.push("Fee due ≤60d");
  return f;
}

/* ------------------------------------------------------------------ charts */
function SpendTrend({ data }: { data: CardsOverview["spend_by_month"] }) {
  const max = Math.max(1, ...data.map((d) => d.spend));
  const first = data[0]?.spend ?? 0, last = data[data.length - 1]?.spend ?? 0;
  const chg = first ? ((last - first) / first) * 100 : 0;
  return (
    <article className="cd-card cd-chart">
      <div className="cd-card-head"><h3>12-month spend</h3><span className={chg < 0 ? "cd-down" : "cd-up"}>{chg < 0 ? "▼" : "▲"} {Math.abs(chg).toFixed(1)}% vs 12 mo ago</span></div>
      <div className="cd-vbars" role="img" aria-label={`Monthly card spend, ${monthLabel(data[0]?.month ?? "")} to ${monthLabel(data[data.length - 1]?.month ?? "")}`}>
        {data.map((d, i) => (
          <div key={d.month} className="cd-vbar" title={`${d.month}: ${cad(d.spend)}`}>
            <span style={{ height: `${(d.spend / max) * 100}%`, animationDelay: `${i * 18}ms` }} className={i === data.length - 1 ? "cd-last" : ""} />
            <small>{monthLabel(d.month).slice(0, 1)}</small>
          </div>
        ))}
      </div>
      <p className="cd-chart-foot"><b>{cadShort(last)}</b> last month · peak {cadShort(max)}</p>
    </article>
  );
}

function HBars({ title, note, rows }: { title: string; note?: string; rows: { label: string; value: number; text: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <article className="cd-card cd-chart">
      <div className="cd-card-head"><h3>{title}</h3>{note && <span>{note}</span>}</div>
      <ul className="cd-hbars">
        {rows.map((r, i) => (
          <li key={r.label}>
            <span className="cd-hbar-label" title={r.label}>{r.label}</span>
            <span className="cd-hbar-track"><i style={{ width: `${(r.value / max) * 100}%`, animationDelay: `${i * 30}ms` }} /></span>
            <b>{r.text}</b>
          </li>
        ))}
      </ul>
    </article>
  );
}

function BehaviourMix({ data, total }: { data: CardsOverview["behaviour"]; total: number }) {
  return (
    <article className="cd-card cd-chart">
      <div className="cd-card-head"><h3>Behaviour mix</h3><span>how balances are paid</span></div>
      <div className="cd-stack" role="img" aria-label={data.map((d) => `${d.behaviour} ${d.accounts}`).join(", ")}>
        {data.map((d) => <span key={d.behaviour} className={`cd-seg-${slug(d.behaviour)}`} style={{ flexGrow: d.accounts }} title={`${d.behaviour}: ${d.accounts}`} />)}
      </div>
      <ul className="cd-stack-legend">
        {data.map((d) => (
          <li key={d.behaviour}>
            <i className={`cd-seg-${slug(d.behaviour)}`} aria-hidden />
            <span>{d.behaviour}</span>
            <b>{d.accounts}</b>
            <small>{total ? Math.round((d.accounts / total) * 100) : 0}%</small>
          </li>
        ))}
      </ul>
      <p className="cd-chart-foot">Transactors pay in full. Persistent debt = minimum payments most months - support-first (RP-021).</p>
    </article>
  );
}

/* ------------------------------------------------------------ IQ layers */
const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function jumpTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  // Scroll only the page pane - scrollIntoView would also shift overflow:hidden ancestors (the app shell).
  const pane = el.closest<HTMLElement>(".cd-page");
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

function IQStrip({ accounts, linked }: { accounts?: number; linked?: number }) {
  const tiles: { iq: IQLayer; body: string; detail: string; target: string; go: string }[] = [
    { iq: "fabric", target: "cd-sec-portfolio", go: "Portfolio & accounts",
      body: `The card book - ${accounts ?? 60} accounts, 12 months of spend, plays. ${linked ?? 22} linked to mortgage clients.`,
      detail: "card_accounts · card_spend_monthly · card_next_actions · card_products" },
    { iq: "foundry", target: "cd-sec-plays", go: "Plays",
      body: "What we may do - RP-019 suitability, RP-020 express consent, RP-021 persistent debt, RP-022 fraud.",
      detail: "Grounds the plays, pre-send checks and Compliance Reviewer" },
    { iq: "web", target: "cd-sec-market", go: "Competitor offers",
      body: "What competitors are offering - live, dated, sourced.",
      detail: "Public web only · internal market context (RP-016)" },
    { iq: "work", target: "cd-sec-branches", go: "What branches are saying",
      body: "What branches and advisors are saying - from email.",
      detail: "The signed-in user's mailbox, under their identity" },
  ];
  return (
    <section className="cd-iqstrip" aria-label="How the IQ layers work here">
      <div className="cd-iqstrip-head"><h2>How the IQ layers work here</h2><span>each tile jumps to the part of the page it powers</span></div>
      <ul>
        {tiles.map((t) => (
          <li key={t.iq}>
            <button type="button" className={`cd-iqtile cd-iqtile-${t.iq}`} onClick={() => jumpTo(t.target)}>
              <span className="cd-iqtile-top"><IQBadge iq={t.iq} /><span className="cd-iqtile-go">{t.go} <span aria-hidden>↓</span></span></span>
              <b>{t.body}</b>
              <small className={t.iq === "fabric" ? "cd-mono" : ""}>{t.detail}</small>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ----------------------------------------------- Web IQ: competitor offers */
const hostOf = (u: string) => {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; }
};

function Source({ source, date, url }: { source: string; date: string; url: string }) {
  const href = safeUrl(url);
  const label = source || (href ? hostOf(href) : "");
  return (
    <span className="cd-src">
      {href ? <a href={href} target="_blank" rel="noopener noreferrer">{label || "source"}<span aria-hidden> ↗</span></a> : label && <span>{label}</span>}
      {date && <time dateTime={date}>{date}</time>}
    </span>
  );
}

function OfferRow({ o }: { o: MarketOffer }) {
  return (
    <li className="cd-offer">
      <div className="cd-offer-main">
        <span className="cd-offer-name"><b>{o.card}</b>{o.issuer && <small>{o.issuer}</small>}</span>
        <p>{o.welcome_offer || "No welcome offer published"}</p>
      </div>
      <div className="cd-offer-side">
        <dl className="cd-offer-terms">
          <div><dt>Fee</dt><dd>{o.annual_fee || "—"}</dd></div>
          <div><dt>Rate</dt><dd>{o.purchase_rate || "—"}</dd></div>
        </dl>
        <Source source={o.source} date={o.date} url={o.url} />
      </div>
    </li>
  );
}

function MarketPanel({ active }: { active: boolean }) {
  const brand = useBrand();
  const [data, setData] = useState<MarketData | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const started = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const search = async (path: string) => {
    setSearching(true); setError("");
    try {
      const d = normaliseMarket(await apiGet<unknown>(path));
      if (!alive.current) return;
      if (!d) setError("Web IQ returned an unexpected payload.");
      // A failed refresh must not wipe good live results - keep them, marked stale.
      else setData((cur) => (d.status !== "live" && cur?.status === "live" ? { ...cur, stale: true, detail: d.detail } : d));
    } catch (e) {
      if (alive.current) setError(String(e));
    } finally {
      if (alive.current) setSearching(false);
    }
  };

  useEffect(() => {
    if (!active || started.current) return;
    started.current = true;
    (async () => {
      let cached: MarketData | null = null;
      try { cached = normaliseMarket(await apiGet<unknown>("/api/cards/market?cached=true")); } catch { /* go live */ }
      if (!alive.current) return;
      if (cached) setData(cached);
      if (cached?.status !== "live") await search("/api/cards/market");
    })();
  }, [active]);

  const offers = data?.offers ?? [];
  const shown = offers.filter((o) => !isOwnBankOffer(o, brand.aliases));
  const hiddenCount = offers.length - shown.length;
  const catOf = (o: MarketOffer) => o.category || "Other";
  const known: string[] = [...OFFER_CATEGORIES];
  const cats = [...known, ...new Set(shown.map(catOf).filter((c) => !known.includes(c)))];
  const groups = cats.map((cat) => ({ cat, rows: shown.filter((o) => catOf(o) === cat) })).filter((g) => g.rows.length);
  const live = data?.status === "live";
  const badge = live ? `Web IQ · ${hhmm(data?.fetchedAt) || "live"}${data?.stale ? " · stale" : ""}` : "Web IQ · baseline";

  return (
    <section id="cd-sec-market" className="cd-card cd-panel cd-mkt" aria-labelledby="cd-mkt-h" tabIndex={-1}>
      <div className="cd-card-head">
        <div className="cd-panel-title"><h3 id="cd-mkt-h">Competitor offers</h3><IQBadge iq="web" title={data?.fetchedAt ? `Fetched ${data.fetchedAt}` : "Public web"}>{badge}</IQBadge></div>
        <button type="button" className="cd-btn cd-btn-ghost cd-btn-sm" disabled={searching} onClick={() => search("/api/cards/market?refresh=true")}>
          <span aria-hidden>↻</span> {searching ? "Searching…" : "Refresh"}
        </button>
      </div>
      <p className="cd-panel-note">
        Other issuers · public web · internal market context, never for client copy (RP-016)
        {hiddenCount > 0 && <> · <span className="cd-mkt-hidden">{hiddenCount} {brand.short} offer{hiddenCount === 1 ? "" : "s"} hidden</span></>}
      </p>
      {searching && (
        <p className="cd-iq-status" role="status"><span className="cd-spin" aria-hidden />Web IQ searching… {shown.length ? "showing the last results meanwhile" : "this can take up to a minute and a half"}</p>
      )}
      {searching && !shown.length && (
        <div className="cd-mkt-skel" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="cd-skel cd-skel-offer" />)}</div>
      )}
      {!searching && error && <p className="cd-error" role="alert">Web IQ is unavailable right now ({error}).</p>}
      {!searching && !error && data && !shown.length && (
        <p className="cd-empty">{data.detail || "No competitor offers yet."} <button type="button" className="cd-link" onClick={() => search("/api/cards/market?refresh=true")}>Search the web now</button></p>
      )}
      {data?.stale && !searching && <p className="cd-iq-status cd-iq-stale">Latest refresh failed - showing the previous live results{data.detail ? ` (${data.detail})` : ""}.</p>}
      {groups.length > 0 && (
        <div className="cd-mkt-groups">
          {groups.map((g) => (
            <div key={g.cat} className="cd-mkt-group">
              <h4>{g.cat}</h4>
              <ul>{g.rows.map((o, i) => <OfferRow key={`${o.issuer}-${o.card}-${i}`} o={o} />)}</ul>
            </div>
          ))}
        </div>
      )}
      {(data?.observations.length ?? 0) > 0 && (
        <div className="cd-mkt-notes">
          <h4>Market notes</h4>
          <ul>
            {data!.observations.map((n, i) => (
              <li key={i}><p>{n.text}</p><Source source={n.source} date={n.date} url={n.url} /></li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------- Work IQ: what branches are saying */
const WORK_PROMPT = "Search my email for what branch managers, advisors, risk and pricing have said about credit cards in the last two months - limit increases, persistent debt, annual fees, fraud, travel cards and competitor offers. Summarise by theme with who said it and when, and cite the policy each theme touches (RP-019 to RP-022).";

function WorkIQPanel() {
  const [answer, setAnswer] = useState("");
  const [layers, setLayers] = useState<IQLayer[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [doneAt, setDoneAt] = useState("");
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  const ask = async () => {
    if (busy) return;
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setAnswer(""); setLayers([]); setError(""); setStatus(""); setDoneAt(""); setBusy(true);
    await streamChat(WORK_PROMPT, null, {
      onStatus: (t) => setStatus(t ?? ""),
      onIQ: (iq) => { if (isIQLayer(iq)) setLayers((l) => (l.includes(iq) ? l : [...l, iq])); },
      onToken: (t) => setAnswer((a) => a + t),
      onMessage: (t) => setAnswer(t),
      onError: (t, d) => setError([t, d].filter(Boolean).join(" ")),
      onDone: () => { setBusy(false); setStatus(""); setDoneAt(new Date().toISOString()); },
    }, ctrl.signal).catch((e) => { if (!ctrl.signal.aborted) setError(String(e)); });
    if (!ctrl.signal.aborted) setBusy(false);
  };

  return (
    <section id="cd-sec-branches" className="cd-card cd-panel cd-work" aria-labelledby="cd-work-h" tabIndex={-1}>
      <div className="cd-card-head">
        <div className="cd-panel-title"><h3 id="cd-work-h">What branches are saying</h3><IQBadge iq="work" /></div>
        <button type="button" className={`cd-btn cd-btn-sm${answer ? " cd-btn-ghost" : " cd-btn-primary"}`} disabled={busy} onClick={ask}>
          {busy ? "Asking…" : answer ? "Ask again" : "Ask Work IQ"}
        </button>
      </div>
      <p className="cd-panel-note">Grounded on the signed-in user's mailbox (Work IQ) - e.g. seven card emails from June-July 2026.</p>
      {layers.length > 0 && <div className="cd-ai-layers" aria-label="IQ layers used">{layers.map((l) => <span key={l} className={`cd-ai-layer l-${l}`}>{l} IQ</span>)}</div>}
      {busy && <p className="cd-iq-status" role="status"><span className="cd-spin" aria-hidden />{status || "Work IQ is reading your card emails…"}</p>}
      <div aria-live="polite">
        {busy && !answer && <div aria-busy="true"><div className="cd-skel cd-skel-line" /><div className="cd-skel cd-skel-line" /><div className="cd-skel cd-skel-line short" /></div>}
        {error && <p className="cd-error" role="alert">Work IQ could not answer: {error}</p>}
        {answer && <div className="cd-work-answer"><Markdown text={answer} /></div>}
      </div>
      {!answer && !busy && !error && (
        <div className="cd-work-empty">
          <p>Ask Work IQ to summarise what branch managers, advisors, risk and pricing have said about cards, by theme, with who said it and when.</p>
          <ul>{["Limit increases", "Persistent debt", "Annual fees", "Fraud", "Travel cards", "Competitor offers"].map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}
      {doneAt && !busy && answer && <p className="cd-iq-status cd-iq-done">Answered at {hhmm(doneAt)} · internal context for the advisor, never for client copy (RP-016)</p>}
    </section>
  );
}

/* -------------------------------------------------------------------- view */
export function CardsView({ active, bankName }: { active: boolean; bankName: string }) {
  const [overview, setOverview] = useState<CardsOverview | null>(null);
  const [rows, setRows] = useState<CardRow[] | null>(null);
  const [shelf, setShelf] = useState<CardProduct[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("All");
  const [play, setPlay] = useState<string | null>(null);
  const [allPlays, setAllPlays] = useState<Record<string, Play[]> | null>(null);
  const [loadingPlays, setLoadingPlays] = useState(false);
  const [q, setQ] = useState("");
  const [openAid, setOpenAid] = useState<string | null>(null);
  const split = useChatSplit("pb.cards.ai", 32, 22, 60);

  useEffect(() => {
    if (!active || rows) return;
    apiGet<{ accounts: CardRow[]; products: CardProduct[] }>("/api/cards/accounts")
      .then((r) => { setRows(r.accounts ?? []); setShelf(r.products ?? []); })
      .catch((e) => setError(String(e)));
    apiGet<CardsOverview>("/api/cards/overview").then(setOverview).catch(() => undefined);
  }, [active, rows]);

  // A play can sit below the top play, so filtering needs every account's full play list.
  // Single-play accounts already carry it as top_play; only multi-play accounts are fetched.
  const choosePlay = (p: string | null) => {
    setPlay((cur) => (cur === p ? null : p));
    if (!p || allPlays || loadingPlays || !rows) return;
    setLoadingPlays(true);
    const base: Record<string, Play[]> = {};
    rows.forEach((r) => { base[r.account_id] = r.top_play ? [r.top_play] : []; });
    Promise.all(rows.filter((r) => r.plays > 1).map((r) =>
      apiGet<CardAccountDetail>(`/api/cards/account/${r.account_id}`).then((d) => { base[r.account_id] = d.plays ?? base[r.account_id]; }).catch(() => undefined)))
      .then(() => setAllPlays(base))
      .finally(() => setLoadingPlays(false));
  };

  const playFor = (r: CardRow): Play | null => {
    if (!play) return r.top_play;
    const list = allPlays?.[r.account_id] ?? (r.top_play ? [r.top_play] : []);
    return list.find((p) => p.play === play) ?? null;
  };

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter((r) => {
      if (filter !== "All" && !flagsOf(r).includes(filter)) return false;
      if (play) {
        const list = allPlays?.[r.account_id] ?? (r.top_play ? [r.top_play] : []);
        if (!list.some((p) => p.play === play)) return false;
      }
      return `${r.customer_name} ${r.account_id} ${r.customer_id} ${r.segment} ${r.branch} ${r.product_name}`.toLowerCase().includes(needle);
    });
  }, [rows, filter, play, allPlays, q]);

  const k = overview?.kpis;
  const total = k?.accounts ?? 0;
  const playStats = (p: string) => overview?.plays.find((x) => x.play === p);

  return (
    <section className="cd-root" hidden={!active} aria-label="Cards book">
      <header className={`cd-head${openAid ? " cd-head-tight" : ""}`}>
        <div>
          <div className="cd-eyebrow">Cards book · Fabric IQ</div>
          <h1>Who needs help, who might leave, who is a better fit?</h1>
          <p>
            {total || "–"} card accounts at {bankName} · {k?.linked_to_mortgage ?? "–"} linked to a mortgage, so wellness and consent carry across books ·
            plays run Support › Protect › Retain › Grow with rules applied before any AI
          </p>
        </div>
        <div className="cd-head-meta">
          <span className="cd-badge">Synthetic data</span>
          {overview?.as_of && <IQBadge iq="fabric" title="KPIs, charts and accounts come from Fabric IQ">Fabric IQ · as of <time dateTime={overview.as_of}>{overview.as_of}</time></IQBadge>}
        </div>
      </header>

      <div className="cd-page" hidden={!!openAid}>
        <section className="cd-kpis" aria-label="Cards book summary">
          <div className="cd-kpi"><small>Accounts</small><b>{k?.accounts ?? "–"}</b><span>{k ? `${k.linked_to_mortgage} linked to a mortgage` : " "}</span></div>
          <div className="cd-kpi">
            <small>Balances / limits</small>
            <b>{k ? <>{cadShort(k.balances)}<em> / {cadShort(k.limits)}</em></> : "–"}</b>
            <span className="cd-kpi-bar" aria-label={k ? `${k.utilization_pct}% utilised` : undefined}>
              <i style={{ width: `${Math.min(100, k?.utilization_pct ?? 0)}%` }} />
            </span>
            <span>{k ? `${k.utilization_pct.toFixed(1)}% utilised` : " "}</span>
          </div>
          <div className="cd-kpi"><small>12-month spend</small><b>{k ? cadShort(k.spend_12m) : "–"}</b><span>{k ? `${cadShort(k.spend_12m / 12)} a month` : " "}</span></div>
          <div className="cd-kpi"><small>Revolving share</small><b>{k ? `${k.revolving_share_pct}%` : "–"}</b><span>carry a balance</span></div>
          <div className="cd-kpi cd-kpi-support"><small>Persistent debt</small><b>{k?.persistent_debt ?? "–"}</b><span>{k ? `support-first · RP-021` : " "}</span></div>
          <div className="cd-kpi"><small>Fraud alerts</small><b>{k?.fraud_alerts ?? "–"}</b><span>{k ? `in 90 days · ${k.past_due_30} past due 30+` : " "}</span></div>
          <div className="cd-kpi"><small>Rewards liability</small><b>{k ? cadShort(k.rewards_liability) : "–"}</b><span>points at ≈ 1¢ each</span></div>
          <div className="cd-kpi"><small>Fee renewals</small><b>{k?.fee_renewals_60d ?? "–"}</b><span>annual fees due in 60 days</span></div>
        </section>

        <MissionPanel book="cards" active={active} bankName={bankName} />

        <IQStrip accounts={k?.accounts} linked={k?.linked_to_mortgage} />

        <div className="cd-section-head cd-section-head-iq" id="cd-sec-portfolio" tabIndex={-1}>
          <h2>Portfolio</h2>
          <span>KPIs, spend, behaviour and product mix · synthetic</span>
          <IQBadge iq="fabric" />
        </div>
        {overview && (
          <section className="cd-charts" aria-label="Portfolio charts">
            <SpendTrend data={overview.spend_by_month} />
            <HBars title="Spend by category" note="12 months"
                   rows={overview.spend_by_category.map((c) => ({ label: CAT_LABEL[c.category] ?? c.category, value: c.spend, text: cadShort(c.spend) }))} />
            <BehaviourMix data={overview.behaviour} total={total} />
            <HBars title="Product mix" note="accounts · balance"
                   rows={[...overview.products].sort((a, b) => b.accounts - a.accounts).map((p) => ({ label: p.product.replace(/ Card$/, ""), value: p.accounts, text: `${p.accounts} · ${cadShort(p.balance)}` }))} />
          </section>
        )}
        {!overview && !error && <div className="cd-skel-row" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="cd-skel cd-skel-chart" />)}</div>}

        <section className="cd-plays-wrap" aria-labelledby="cd-plays-h" id="cd-sec-plays" tabIndex={-1}>
          <div className="cd-section-head cd-section-head-iq">
            <h2 id="cd-plays-h">Plays</h2>
            <span>Support › Protect › Retain › Grow · click a play to filter the accounts</span>
            <span className="cd-iqs"><IQBadge iq="fabric" /><IQBadge iq="foundry" title="Each play leans on a policy in the Foundry IQ knowledge base">Foundry IQ · RP-019–022</IQBadge></span>
          </div>
          <div className="cd-plays">
            {PLAY_META.map((m) => {
              const s = playStats(m.play);
              const on = play === m.play;
              return (
                <button key={m.play} type="button" className={`cd-play cd-play-${m.type.toLowerCase()}`} aria-pressed={on}
                        onClick={() => choosePlay(m.play)}>
                  <span className="cd-play-top"><PlayTag t={m.type} /><code>{m.policy}</code></span>
                  <b>{m.play}</b>
                  <span className="cd-play-counts">
                    <span><strong>{s?.eligible ?? "–"}</strong> eligible</span>
                    <span className={s?.blocked ? "cd-play-blocked" : "cd-muted"}>{s?.blocked ? <Lock /> : null}<strong>{s?.blocked ?? 0}</strong> blocked</span>
                  </span>
                  <small>{m.blurb}</small>
                </button>
              );
            })}
          </div>
        </section>

        <section className="cd-context" aria-label="Market and branch context">
          <MarketPanel active={active} />
          <WorkIQPanel />
        </section>

        <div className="cd-section-head cd-section-head-iq cd-accounts-head">
          <h2>Accounts</h2>
          <span>every card account with the signal that decides the conversation · click to open</span>
          <IQBadge iq="fabric" />
        </div>
        <div className="cd-toolbar">
          <div className="cd-chips" role="group" aria-label="Filter card accounts">
            {FILTERS.map((f) => (
              <button key={f} type="button" className="cd-chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f}<b>{f === "All" ? rows?.length ?? 0 : (rows ?? []).filter((r) => flagsOf(r).includes(f)).length}</b>
              </button>
            ))}
            {play && (
              <button type="button" className="cd-chip cd-chip-play" onClick={() => setPlay(null)} aria-label={`Clear play filter ${play}`}>
                Play: {play}{loadingPlays ? <small>loading…</small> : <b aria-hidden>✕</b>}
              </button>
            )}
          </div>
          <label className="cd-search">
            <span className="cd-sr">Search card accounts</span>
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, branch, product…" />
          </label>
        </div>

        {error && <p className="cd-error" role="alert">Could not load card accounts ({error}).</p>}

        <div className="cd-card cd-list-card">
          <div className="cd-list-head" aria-hidden>
            <span>Client</span><span>Product</span><span>Behaviour</span><span>Utilisation</span><span>Spend / mo</span><span>Annual fee</span><span>Flags</span><span>{play ? "Play" : "Top play"}</span>
          </div>
          {!rows && !error && <div className="cd-skel-list" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="cd-skel" />)}</div>}
          {rows && !shown.length && !loadingPlays && (
            <p className="cd-empty">No accounts match. <button type="button" className="cd-link" onClick={() => { setFilter("All"); setPlay(null); setQ(""); }}>Clear filters</button></p>
          )}
          <ul className="cd-list">
            {shown.map((r) => {
              const p = playFor(r);
              const ok = p ? isEligible(p.eligibility) : true;
              const fl = flagsOf(r);
              const up = r.spend_trend_pct >= 0;
              return (
                <li key={r.account_id}>
                  <button type="button" className={`cd-row${r.behaviour === "Persistent debt" ? " cd-row-support" : ""}`} onClick={() => setOpenAid(r.account_id)}
                          aria-label={`Open ${r.customer_name}, ${r.product_name}, ${r.behaviour}`}>
                    <span className="cd-c-who"><b>{r.customer_name}</b><small>{r.segment} · {r.branch}</small></span>
                    <span className="cd-c-prod"><b>{r.product_name}</b><small>{r.account_id}</small></span>
                    <span><BehaviourPill b={r.behaviour} /></span>
                    <span className="cd-c-util">
                      <b>{r.utilization_pct.toFixed(0)}%</b>
                      <i className="cd-minibar" aria-hidden><i style={{ width: `${Math.min(100, r.utilization_pct)}%` }} className={r.utilization_pct >= 80 ? "cd-hi" : ""} /></i>
                      <small>{cadShort(r.balance)} of {cadShort(r.credit_limit)}</small>
                    </span>
                    <span className="cd-c-spend">
                      <b>{cad(r.monthly_spend_avg)}</b>
                      <small className={up ? "cd-up" : "cd-down"}>{up ? "▲" : "▼"} {Math.abs(r.spend_trend_pct).toFixed(1)}%</small>
                    </span>
                    <span className="cd-c-fee">
                      {r.annual_fee > 0
                        ? <><b>{cad(r.annual_fee)}</b><small className={r.fee_anniversary_days <= 60 ? "cd-soon" : ""}>due in {r.fee_anniversary_days}d</small></>
                        : <small>No fee</small>}
                    </span>
                    <span className="cd-c-flags">
                      {fl.length ? fl.filter((f) => f !== "Fee due ≤60d").map((f) => <span key={f} className={`cd-flag cd-flag-${slug(f)}`}>{f}</span>) : null}
                      {!fl.filter((f) => f !== "Fee due ≤60d").length && <small className="cd-muted">—</small>}
                    </span>
                    <span className={`cd-c-play${ok ? "" : " cd-blocked"}`}>
                      {p ? <>
                        <PlayTag t={p.play_type} />
                        <span className="cd-c-playname">{p.play}</span>
                        {!ok && <small className="cd-lock"><Lock />{p.eligibility}</small>}
                      </> : <small className="cd-muted">No play - healthy</small>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
        <p className="cd-foot">
          Synthetic demo data · {rows?.length ?? 0} card accounts · {shelf.length} cards on the shelf{overview?.as_of ? ` · Fabric IQ as of ${overview.as_of}` : ""}.
          Wellness band on linked accounts is carried from the mortgage book. Internal signals are for the advisor only (RP-016).
        </p>
      </div>

      {openAid && (
        <CardAccount key={openAid} aid={openAid} shelf={shelf} split={split} onBack={() => setOpenAid(null)} />
      )}
    </section>
  );
}
