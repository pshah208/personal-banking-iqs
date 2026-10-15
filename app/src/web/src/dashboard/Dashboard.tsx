import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  bandCounts, branches, buildAnswer, clockBasis, money, offerBasis, paymentShockBasis,
  percent, priorityBasis, renewals, snapshotAsOf, snapshotDisclaimer, snapshotUnits,
  type Answer, type AnswerBlock,
} from "./data";
import { buildFlyerDraft, flyerCatalogue, type FlyerDraft } from "./flyer";
import { Flyer } from "../components/Flyer";
import { SplitHandle, SplitRail, useChatSplit } from "../components/ChatSplit";
import { CustomersView } from "../customers/CustomersView";
import { CustomerWorkspace } from "../customers/CustomerWorkspace";
import { WellnessView } from "../customers/WellnessView";
import { MissionPanel } from "../components/MissionPanel";
import "./dashboard.css";

type SubView = "book" | "customers" | "wellness" | "mission";
const SUBVIEWS: { id: SubView; label: string }[] = [
  { id: "book", label: "Renewal book" },
  { id: "customers", label: "Customers" },
  { id: "wellness", label: "Financial wellness" },
  { id: "mission", label: "Agent mission" },
];
type OpenCustomer = { cid: string; preferSupport: boolean } | null;

type SortKey = "priorityRank" | "customerName" | "branchName" | "daysToMaturity"
  | "balanceCad" | "riskScore" | "renewalLikelihoodPct" | "competitorGapBps";
type Exchange = { question: string; answer: Answer };

/**
 * The countdown anchor for a drafted flyer.
 *
 * Fixed to the snapshot date so the artwork measures the same number of days
 * whenever it is opened. Noon, because a bare ISO date parses as UTC and a
 * midnight anchor lands a day early west of Greenwich.
 */
const SNAPSHOT_NOW = (() => {
  const [year, month, day] = snapshotAsOf.split("-").map(Number);
  return new Date(year, month - 1, day, 12);
})();
const DRAFT_STAMP = "NOT APPROVED PRICING";

const BANDS = ["High", "Medium", "Low"] as const;
const WINDOWS = ["Within 30 days", "31-60 days", "61-90 days", "91-180 days"] as const;
const ACTIONS = [
  ["Why call this file", "call plan"],
  ["Attrition risk", "risk"],
  ["Retention offers", "offers"],
  ["Maturity and payment", "maturity"],
] as const;
const COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: "priorityRank", label: "Order", numeric: true },
  { key: "customerName", label: "Customer", numeric: false },
  { key: "branchName", label: "Branch", numeric: false },
  { key: "daysToMaturity", label: "Days to maturity", numeric: true },
  { key: "balanceCad", label: "Balance", numeric: true },
  { key: "riskScore", label: "Attrition", numeric: true },
  { key: "renewalLikelihoodPct", label: "Renewal likelihood", numeric: true },
  { key: "competitorGapBps", label: "Competitor gap", numeric: true },
];

function BlockBody({ block }: { block: AnswerBlock }) {
  return <>
    {block.note && <p className="mrcd-block-note">{block.note}</p>}
    {block.figures?.length ? <dl className="mrcd-figures">{block.figures.map((figure) =>
      <div key={figure.label}><dt>{figure.label}</dt><dd>{figure.value}</dd></div>)}</dl> : null}
    {block.lines?.map((line, index) => <p className="mrcd-block-line" key={index}>{line}</p>)}
    {block.evidence?.length ? <ul className="mrcd-evidence-list">{block.evidence.map((item) =>
      <li key={item.iq}>
        <span className={`mrcd-ev-badge mrcd-ev-${item.iq.split(" ")[0].toLowerCase()}${item.status === "unavailable" ? " mrcd-ev-off" : ""}`}>
          {item.iq.replace(" IQ", "")}
        </span>
        <span>{item.text}</span>
      </li>)}</ul> : null}
  </>;
}

function AnswerBlockView({ block }: { block: AnswerBlock }) {
  if (!block.note && !block.figures?.length && !block.lines?.length && !block.evidence?.length) return null;
  if (block.collapsible) {
    return <details className="mrcd-block mrcd-block-fold"><summary>{block.title}</summary><BlockBody block={block} /></details>;
  }
  return <section className="mrcd-block"><h4>{block.title}</h4><BlockBody block={block} /></section>;
}

const STATUS_LABEL: Record<string, string> = {
  supported: "Condition supported by local facts",
  unmet: "Condition not met",
  unevidenced: "Evidence not held in this snapshot",
  excluded: "Not drafted onto a flyer",
};

/**
 * The drafted flyer, its reasoning and the cross-sell read.
 *
 * Laid out so the caveats arrive with the number rather than after it: the
 * approval level and the "draft, not approved" statement sit above the artwork,
 * and every offer that was set aside is listed with the reason it was.
 */
function FlyerPanel({ draft }: { draft: FlyerDraft }) {
  return (
    <div className="mrcd-flyer">
      <div className="mrcd-flyer-verdict">
        <span className="mrcd-badge mrcd-badge-warn">Draft for review</span>
        <span className="mrcd-approval">{draft.approvalLevel} approval required</span>
      </div>
      <article className="mrcd-card">
        <h3>Drafted offer</h3>
        {draft.offer
          ? <p className="mrcd-flyer-offer"><strong>{draft.offer.id} {draft.offer.name}</strong></p>
          : <p className="mrcd-flyer-offer"><strong>No offer drafted</strong></p>}
        <dl className="mrcd-figures">
          <div><dt>Offered renewal rate</dt><dd>{percent(draft.offeredRatePct, 2)}</dd></div>
          <div><dt>Maximum discount</dt><dd>{draft.discountBps ? `${draft.discountBps} bps` : "None"}</dd></div>
          <div><dt>Rate after discount</dt><dd>{percent(draft.effectiveRatePct, 2)}</dd></div>
          <div><dt>Cashback</dt><dd>{draft.cashbackCad ? money(draft.cashbackCad) : "None"}</dd></div>
        </dl>
        <p className="mrcd-block-line">{draft.rateLine}</p>
        <p className="mrcd-note">
          Nothing on this page approves a price. The discount shown is the RP-003 ceiling for the
          drafted offer, and RP-002 still requires {draft.approvalLevel} approval before it is put
          to the customer.
        </p>
      </article>

      <article className="mrcd-card mrcd-flyer-market">
        <h3>Market rates · unavailable</h3>
        <p>{draft.marketNote}</p>
      </article>

      {draft.spec
        ? <Flyer spec={draft.spec} catalogue={flyerCatalogue} now={SNAPSHOT_NOW} draft={DRAFT_STAMP} />
        : <p className="mrcd-empty" role="status">
            No artwork is drawn, because no offer could be drafted from the local facts. The
            offers considered below name the evidence each one is waiting on.
          </p>}
      <p className="mrcd-note">{draft.alternativeNote}</p>

      <details className="mrcd-card" open>
        <summary>Why this offer was chosen</summary>
        {draft.why.map((line) => <p className="mrcd-block-line" key={line}>{line}</p>)}
        <dl className="mrcd-figures">
          {draft.value.map((figure) =>
            <div key={figure.label}><dt>{figure.label}</dt><dd>{figure.value}</dd></div>)}
        </dl>
      </details>

      <article className="mrcd-card">
        <h3>Offers considered</h3>
        <ul className="mrcd-offers">
          {draft.assessments.map((item) => (
            <li key={item.id} className={item.selected ? "mrcd-offer-rec" : ""}>
              <div>
                <strong>{item.id} {item.name}</strong>
                {item.selected && <span className="mrcd-badge">Drafted</span>}
              </div>
              <div className="mrcd-offer-meta">
                <span>Up to {item.maxDiscountBps} bps</span>
                <span>{item.cashbackCad ? `${money(item.cashbackCad)} cashback` : "no cashback"}</span>
                <span className="mrcd-approval">{item.approvalLevel} approval</span>
                <span className={`mrcd-status mrcd-status-${item.status}`}>{STATUS_LABEL[item.status]}</span>
              </div>
              <small>{item.reason}</small>
            </li>
          ))}
        </ul>
      </article>

      <article className="mrcd-card">
        <h3>Products held · authored for this dashboard</h3>
        <ul className="mrcd-holdings">
          {draft.holdings.map((held) => (
            <li key={held.id}><strong>{held.name}</strong><small>{held.category} · {held.id}</small></li>
          ))}
        </ul>
      </article>

      <article className="mrcd-card">
        <h3>Cross-sell · propensity indicators, not pre-qualification</h3>
        <ul className="mrcd-crosssell">
          {draft.crossSell.map((item) => (
            <li key={item.id}>
              <div><strong>{item.rank}. {item.name}</strong><span className="mrcd-badge">{item.category}</span></div>
              <small>{item.summary}</small>
              <ul className="mrcd-drivers">
                {item.signals.map((signal) => <li key={signal}>{signal}</li>)}
              </ul>
            </li>
          ))}
        </ul>
        {draft.relief && (
          <div className="mrcd-relief">
            <h4>{draft.relief.name}</h4>
            <p className="mrcd-note">{draft.relief.summary}</p>
            <ul className="mrcd-drivers">
              {draft.relief.signals.map((signal) => <li key={signal}>{signal}</li>)}
            </ul>
          </div>
        )}
      </article>

      <details className="mrcd-card">
        <summary>Basis, caveats and sources</summary>
        {draft.basis.map((line) => <p key={line}>{line}</p>)}
      </details>
      <p className="mrcd-footnote">{draft.disclosure}</p>
    </div>
  );
}

export function Dashboard({ active }: { active: boolean }) {
  const [selectedId, setSelectedId] = useState(
    () => [...renewals].sort((a, b) => a.priorityRank - b.priorityRank)[0].id,
  );
  const [search, setSearch] = useState("");
  const [branch, setBranch] = useState("all");
  const [band, setBand] = useState("all");
  const [window_, setWindow] = useState("all");
  const [sort, setSort] = useState<{ key: SortKey; direction: 1 | -1 }>({ key: "priorityRank", direction: 1 });
  const split = useChatSplit("mrcd.chat", 34, 22, 65);
  const chatOpen = split.open;
  const setChatOpen = split.setOpen;
  const wsSplit = useChatSplit("pb.customer.ai", 34, 22, 60);
  const [sub, setSub] = useState<SubView>("book");
  const [openC, setOpenC] = useState<OpenCustomer>(null);
  const [openW, setOpenW] = useState<OpenCustomer>(null);
  const inWorkspace = (sub === "customers" && !!openC) || (sub === "wellness" && !!openW);
  const [conversations, setConversations] = useState<Record<string, Exchange[]>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  // Flyer drafts are kept per renewal exactly as conversations are, so switching
  // renewal, filtering, or leaving for Guided and coming back never loses one.
  const [flyers, setFlyers] = useState<Record<string, FlyerDraft>>({});
  const [panel, setPanel] = useState<"chat" | "flyer">("chat");
  const shell = useRef<HTMLDivElement>(null);
  const log = useRef<HTMLDivElement>(null);

  const selected = renewals.find((renewal) => renewal.id === selectedId)!;
  const conversation = conversations[selectedId] ?? [];
  const flyer = flyers[selectedId];
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return renewals.filter((renewal) =>
      (branch === "all" || renewal.branchId === branch) &&
      (band === "all" || renewal.riskBand === band) &&
      (window_ === "all" || renewal.maturityWindow === window_) &&
      `${renewal.customerName} ${renewal.id} ${renewal.customerId} ${renewal.segment} ${renewal.branchName} ${renewal.advisorName} ${renewal.stage}`
        .toLowerCase().includes(needle),
    ).sort((a, b) => {
      const left = a[sort.key], right = b[sort.key];
      const order = typeof left === "number" && typeof right === "number"
        ? left - right : String(left).localeCompare(String(right));
      return order * sort.direction;
    });
  }, [search, branch, band, window_, sort]);

  const balanceVisible = visible.reduce((total, renewal) => total + renewal.balanceCad, 0);
  const revenueVisible = visible.reduce((total, renewal) => total + renewal.annualRevenueCad, 0);
  const highVisible = visible.filter((renewal) => renewal.riskBand === "High").length;
  const soonVisible = visible.filter((renewal) => renewal.daysToMaturity <= 30).length;
  const filtered = visible.length !== renewals.length;
  const selectedVisible = visible.some((renewal) => renewal.id === selectedId);

  useEffect(() => {
    if (active && sub === "book" && chatOpen && panel === "chat" && log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [active, sub, chatOpen, panel, selectedId, conversation.length]);

  function ask(question: string) {
    const text = question.trim();
    if (!text) return;
    setConversations((previous) => ({
      ...previous,
      [selectedId]: [...(previous[selectedId] ?? []), { question: text, answer: buildAnswer(selected, text) }],
    }));
    setChatOpen(true);
    setPanel("chat");
  }
  /**
   * Build a flyer draft for the selected renewal.
   *
   * Same shape as `ask`: an action that produces a reviewable artifact, filed
   * against this renewal and this renewal only. It never changes workspace mode
   * and never reaches the live agent.
   */
  function draftFlyer() {
    const built = buildFlyerDraft(selected);
    if (!built) return;
    setFlyers((previous) => ({ ...previous, [selectedId]: built }));
    setChatOpen(true);
    setPanel("flyer");
  }
  function sortBy(key: SortKey) {
    setSort((previous) => ({
      key,
      direction: previous.key === key ? (previous.direction === 1 ? -1 : 1) : key === "customerName" || key === "branchName" || key === "priorityRank" ? 1 : -1,
    }));
  }
  function reset() {
    setSearch(""); setBranch("all"); setBand("all"); setWindow("all");
  }

  return (
    <section className="mrcd" hidden={!active} aria-label="Renewal snapshot dashboard">
      <div className={`mrcd-head${inWorkspace ? " mrcd-head-tight" : ""}`}>
        {sub === "book" ? (
          <div>
            <div className="mrcd-eyebrow">Fabric IQ · local snapshot</div>
            <h1>Which renewals do I call, and what can I offer?</h1>
            <p>
              {renewals.length} mortgage renewals maturing within 180 days of {snapshotAsOf} across{" "}
              {branches.length} pilot branches · {bandCounts.High} High, {bandCounts.Medium} Medium,{" "}
              {bandCounts.Low} Low attrition risk
            </p>
          </div>
        ) : sub === "customers" ? (
          <div>
            <div className="mrcd-eyebrow">Customer 360 · Fabric IQ</div>
            <h1>Who needs a conversation, and what is appropriate?</h1>
            <p>
              Every renewing customer with wellness, risk and the next-best action the rules allow · consent (RP-011)
              and vulnerability (RP-012) gates are applied before any AI is involved
            </p>
          </div>
        ) : sub === "mission" ? (
          <div>
            <div className="mrcd-eyebrow">Agent mission · harness</div>
            <h1>What does the agent do that the dashboard cannot?</h1>
            <p>One renewal case end to end: governed facts and siloed plays, a live agent across Work, Foundry, Web and Fabric IQ, deterministic guardrails, the Compliance Reviewer and your decision</p>
          </div>
        ) : (
          <div>
            <div className="mrcd-eyebrow">Financial wellness · RP-012 support-first</div>
            <h1>Who needs support before any sales conversation?</h1>
            <p>Vulnerable and Stretched customers, lowest wellness score first · signals are for the advisor only and never go in client copy</p>
          </div>
        )}
        <div className="mrcd-head-meta">
          <span className="mrcd-badge mrcd-badge-warn">Synthetic data</span>
          {sub === "book" && <>
            <span>Snapshot <time dateTime={snapshotAsOf}>{snapshotAsOf}</time></span>
            <button type="button" aria-expanded={chatOpen} aria-controls="mrcd-chat"
              onClick={() => setChatOpen(!chatOpen)}>
              {chatOpen ? "Collapse panel" : "Expand panel"}
            </button>
          </>}
        </div>
      </div>
      <nav className="mrcd-subtabs" role="tablist" aria-label="Dashboard views">
        {SUBVIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" id={`mrcd-sub-${v.id}`} aria-selected={sub === v.id}
            aria-controls={`mrcd-subview-${v.id}`}
            onClick={() => {
              if (sub === v.id) { if (v.id === "customers") setOpenC(null); if (v.id === "wellness") setOpenW(null); }
              setSub(v.id);
            }}>
            {v.label}
          </button>
        ))}
      </nav>
      {sub === "book" && <p className="mrcd-disclaimer">{snapshotDisclaimer}</p>}

      <div ref={shell} id="mrcd-subview-book" role="tabpanel" aria-labelledby="mrcd-sub-book" hidden={sub !== "book"}
        className={`mrcd-workspace${chatOpen ? "" : " mrcd-chat-collapsed"}`}
        style={{ "--split-w": `${split.width}%` } as CSSProperties}>
        <main className="mrcd-book" tabIndex={0} aria-label="Renewal book, independently scrollable">
          <div className="mrcd-section-head">
            <div><h2>Branch book</h2><p>Figures as recorded on {snapshotAsOf}; both the branch row and the recounted renewal rows are shown.</p></div>
          </div>
          <div className="mrcd-branches">
            {branches.map((item) => {
              const active_ = branch === item.id;
              return (
                <article className={`mrcd-card mrcd-branch${active_ ? " mrcd-on" : ""}`} key={item.id}>
                  <div className="mrcd-branch-top">
                    <div>
                      <h3>{item.name}</h3>
                      <small>{item.province} · {item.manager} · {item.id}</small>
                    </div>
                    <button type="button" aria-pressed={active_}
                      onClick={() => setBranch(active_ ? "all" : item.id)}>
                      {active_ ? "Filtered" : "Filter"}
                    </button>
                  </div>
                  <dl className="mrcd-branch-figures">
                    <div><dt>Renewals</dt><dd>{item.renewalsCounted}</dd><span>{item.maturingWithin30} within 30 days</span></div>
                    <div><dt>Balance maturing</dt><dd>{money(item.balanceMaturingCountedCad)}</dd><span>summed from renewal rows</span></div>
                    <div><dt>High risk</dt><dd>{item.highRiskCounted}</dd><span>counted from risk bands</span></div>
                    <div><dt>Revenue at risk</dt><dd>{money(item.revenueAtRiskCountedCad)}</dd><span>annual exposure, summed</span></div>
                  </dl>
                  <p className="mrcd-note">
                    Branch row: retention {percent(item.retentionRatePct)} last quarter · average discount{" "}
                    {item.avgDiscountBps} bps · {item.advisorCapacity} files per advisor FTE.
                  </p>
                  {item.reconciliation.length
                    ? <ul className="mrcd-flags">{item.reconciliation.map((issue) => <li key={issue}>{issue}</li>)}</ul>
                    : <p className="mrcd-note mrcd-ok">Branch row and renewal rows agree on renewals, balance, high-risk count and revenue at risk.</p>}
                </article>
              );
            })}
          </div>

          <div className="mrcd-section-head">
            <div><h2>Call order</h2><p>{priorityBasis}</p></div>
            <span className="mrcd-badge">{visible.length} of {renewals.length} renewals</span>
          </div>
          <div className="mrcd-filters">
            <label>Search
              <input type="search" value={search} placeholder="Customer, renewal ID, advisor, segment, stage"
                onChange={(event) => setSearch(event.target.value)} />
            </label>
            <label>Branch
              <select value={branch} onChange={(event) => setBranch(event.target.value)}>
                <option value="all">All branches</option>
                {branches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label>Attrition band
              <select value={band} onChange={(event) => setBand(event.target.value)}>
                <option value="all">All bands</option>
                {BANDS.map((name) => <option key={name}>{name}</option>)}
              </select>
            </label>
            <label>Maturity window
              <select value={window_} onChange={(event) => setWindow(event.target.value)}>
                <option value="all">All windows</option>
                {WINDOWS.map((name) => <option key={name}>{name}</option>)}
              </select>
            </label>
            <button type="button" onClick={reset}>Reset filters</button>
          </div>
          <div className="mrcd-kpis">
            <article className="mrcd-card mrcd-kpi"><h3>Balance maturing</h3><strong>{money(balanceVisible)}</strong><small>{filtered ? "filtered subset" : "whole book"} · summed from renewal rows</small></article>
            <article className="mrcd-card mrcd-kpi"><h3>Annual revenue exposure</h3><strong>{money(revenueVisible)}</strong><small>scored exposure, not booked revenue</small></article>
            <article className="mrcd-card mrcd-kpi"><h3>High attrition band</h3><strong>{highVisible}</strong><small>of {visible.length} shown</small></article>
            <article className="mrcd-card mrcd-kpi"><h3>Maturing within 30 days</h3><strong>{soonVisible}</strong><small>measured from {snapshotAsOf}</small></article>
          </div>
          <div className="mrcd-card mrcd-table-card">
            <div className="mrcd-table-scroll" tabIndex={0} role="region" aria-label="Renewal table, scroll horizontally for all columns">
              <table>
                <caption>Renewals ranked by derived call order · select a row for the customer brief</caption>
                <thead>
                  <tr>{COLUMNS.map((column) => (
                    <th key={column.key} scope="col" className={column.numeric ? "mrcd-num" : undefined}
                      aria-sort={sort.key === column.key ? (sort.direction === 1 ? "ascending" : "descending") : "none"}>
                      <button type="button" onClick={() => sortBy(column.key)}>
                        {column.label} {sort.key === column.key ? (sort.direction === 1 ? "↑" : "↓") : "↕"}
                      </button>
                    </th>
                  ))}<th scope="col">Band</th><th scope="col">Recommended offer</th></tr>
                </thead>
                <tbody>
                  {visible.map((renewal) => (
                    <tr key={renewal.id} className={selectedId === renewal.id ? "mrcd-selected" : ""}>
                      <td className="mrcd-num">{renewal.priorityRank}</td>
                      <th scope="row">
                        <button type="button" aria-pressed={selectedId === renewal.id}
                          onClick={() => setSelectedId(renewal.id)}>
                          {renewal.customerName}
                          <small>{renewal.id} · {renewal.segment}{selectedId === renewal.id ? " · selected" : ""}</small>
                        </button>
                      </th>
                      <td>{renewal.branchName}</td>
                      <td className="mrcd-num">{renewal.daysToMaturity}</td>
                      <td className="mrcd-num">{money(renewal.balanceCad)}</td>
                      <td className="mrcd-num">{renewal.riskScore.toFixed(3)}</td>
                      <td className="mrcd-num">{percent(renewal.renewalLikelihoodPct)}</td>
                      <td className="mrcd-num">{renewal.competitorGapBps} bps</td>
                      <td><span className={`mrcd-band mrcd-band-${renewal.riskBand.toLowerCase()}`}>{renewal.riskBand}</span></td>
                      <td>{renewal.recommendedOffer.id} · {renewal.recommendedOffer.approvalLevel}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!visible.length && <p className="mrcd-empty" role="status">No renewals match these filters. Reset filters to restore the book; the selected customer brief is preserved.</p>}
          </div>

          <section className="mrcd-detail" aria-label="Selected customer brief">
            <div className="mrcd-section-head">
              <div>
                <div className="mrcd-eyebrow">Customer brief</div>
                <h2>{selected.customerName}</h2>
                <p>
                  {selected.id} · {selected.segment} · {selected.branchName} ({selected.province}) ·
                  advisor {selected.advisorName} · {selected.preferredLanguage === "FR" ? "French-preferred" : "English-preferred"} ·
                  {" "}{selected.tenureYears} years tenure · {selected.productsHeld} products held
                </p>
              </div>
              <span className={`mrcd-band mrcd-band-${selected.riskBand.toLowerCase()}`}>{selected.riskBand} attrition band</span>
            </div>
            {!selectedVisible && (
              <p className="mrcd-outside" role="status">
                This renewal is outside the current filters. The brief and its conversation stay with {selected.customerName}; the totals above exclude it.
              </p>
            )}
            <div className="mrcd-actions">
              {ACTIONS.map(([label, question]) => (
                <button type="button" key={question} onClick={() => ask(question)}>{label} ↗</button>
              ))}
              <button type="button" className="mrcd-primary" onClick={draftFlyer}>
                {flyer ? "Rebuild flyer draft" : "Build flyer draft"} ↗
              </button>
            </div>
            <dl className="mrcd-figures mrcd-detail-figures">
              <div><dt>Balance maturing</dt><dd>{money(selected.balanceCad)}</dd></div>
              <div><dt>Matures</dt><dd>{selected.maturityDate}</dd></div>
              <div><dt>Days to maturity</dt><dd>{selected.daysToMaturity}</dd></div>
              <div><dt>Rate change</dt><dd>{percent(selected.currentRatePct, 2)} → {percent(selected.offeredRatePct, 2)}</dd></div>
              <div><dt>Competitor gap</dt><dd>{selected.competitorGapBps} bps</dd></div>
              <div><dt>Renewal likelihood</dt><dd>{percent(selected.renewalLikelihoodPct)}</dd></div>
              <div><dt>Loan to value</dt><dd>{percent(selected.ltvPct)}</dd></div>
              <div><dt>Stage</dt><dd>{selected.stage}</dd></div>
            </dl>
            <div className="mrcd-grid">
              <article className="mrcd-card">
                <h3>Why this file</h3>
                <p>{selected.callReason}</p>
              </article>
              <article className="mrcd-card">
                <h3>Risk drivers · model output, not a decision</h3>
                <ul className="mrcd-drivers">
                  {selected.riskDrivers.length
                    ? selected.riskDrivers.map((driver) => <li key={driver}>{driver}</li>)
                    : <li>No drivers recorded for this renewal.</li>}
                </ul>
                <p className="mrcd-note">
                  Rate-shopping signal {selected.rateShopping ? "recorded" : "not recorded"} · service complaint in the last 12 months {selected.serviceComplaint ? "recorded" : "not recorded"} · {selected.modelVersion}.
                </p>
              </article>
            </div>
            <article className="mrcd-card">
              <h3>Retention offers this segment is eligible for</h3>
              <ul className="mrcd-offers">
                {selected.eligibleOffers.map((offer) => (
                  <li key={offer.id} className={offer.recommended ? "mrcd-offer-rec" : ""}>
                    <div>
                      <strong>{offer.id} {offer.name}</strong>
                      {offer.recommended && <span className="mrcd-badge">Recommended in source</span>}
                    </div>
                    <div className="mrcd-offer-meta">
                      <span>Up to {offer.maxDiscountBps} bps</span>
                      <span>{offer.cashbackCad ? money(offer.cashbackCad) + " cashback" : "no cashback"}</span>
                      <span className="mrcd-approval">{offer.approvalLevel} approval</span>
                    </div>
                    <small>{offer.notes}</small>
                  </li>
                ))}
              </ul>
              <p className="mrcd-note">{offerBasis}</p>
            </article>
            <div className="mrcd-grid mrcd-evidence-grid">
              {selected.evidence.map((item) => (
                <article className="mrcd-card" key={item.iq}>
                  <div className="mrcd-evidence-title">
                    <h3>{item.iq}</h3>
                    <span className={`mrcd-badge${item.status === "unavailable" ? " mrcd-badge-off" : ""}`}>{item.status}</span>
                  </div>
                  <p>{item.text}</p>
                </article>
              ))}
            </div>
            <details className="mrcd-card">
              <summary>Basis, caveats and sources</summary>
              <p>{snapshotUnits}</p>
              <p>{clockBasis}</p>
              <p>{priorityBasis}</p>
              <p>{paymentShockBasis}</p>
              {selected.dataQuality.map((issue) => <p key={issue}>{issue}</p>)}
              <ul>{selected.sources.map((source) => <li key={source}>{source}</li>)}</ul>
            </details>
          </section>
        </main>

        {chatOpen
          ? <SplitHandle split={split} container={shell} controls="mrcd-chat" label="brief panel" />
          : <SplitRail split={split} controls="mrcd-chat" label="Brief" />}

        <aside id="mrcd-chat" className="mrcd-chat" hidden={!chatOpen} aria-label="Renewal workspace panel">
          <header className="mrcd-chat-head">
            <div className="mrcd-eyebrow">Local answers · no API calls</div>
            <h2>{selected.customerName}</h2>
            <p>{selected.id} · snapshot {snapshotAsOf}</p>
            <div className="mrcd-tabs" role="tablist" aria-label="Panel view">
              <button type="button" role="tab" id="mrcd-tab-chat" aria-selected={panel === "chat"}
                aria-controls="mrcd-view-chat" onClick={() => setPanel("chat")}>
                Brief{conversation.length ? ` · ${conversation.length}` : ""}
              </button>
              <button type="button" role="tab" id="mrcd-tab-flyer" aria-selected={panel === "flyer"}
                aria-controls="mrcd-view-flyer" onClick={() => setPanel("flyer")}>
                Flyer draft{flyer ? " · 1" : ""}
              </button>
            </div>
          </header>

          <div id="mrcd-view-flyer" role="tabpanel" aria-labelledby="mrcd-tab-flyer"
            className="mrcd-chat-log" hidden={panel !== "flyer"} tabIndex={0}
            aria-label={`Flyer draft for ${selected.customerName}`}>
            {flyer
              ? <FlyerPanel draft={flyer} />
              : <div className="mrcd-welcome">
                  <span className="mrcd-badge">Local snapshot</span>
                  <h3>Draft a renewal flyer.</h3>
                  <p>
                    Builds a reviewable draft for {selected.customerName} from the local renewal,
                    risk and offer rows: the best offer their segment is eligible for and whose
                    condition this snapshot can actually support, the rate after the maximum discount,
                    the approval it still needs, and the products they do not already hold.
                  </p>
                  <p>
                    Live market and competitor rates are unavailable here, and the draft says so
                    rather than filling the gap. Nothing is sent anywhere; the draft stays with this
                    renewal and never reaches the live agent.
                  </p>
                  <button type="button" className="mrcd-primary" onClick={draftFlyer}>Build flyer draft</button>
                </div>}
          </div>

          <div id="mrcd-view-chat" role="tabpanel" aria-labelledby="mrcd-tab-chat"
            className="mrcd-chat-log" ref={log} hidden={panel !== "chat"}
            aria-live="polite" tabIndex={0}
            aria-label={`Local answers for ${selected.customerName}`}>
            {!conversation.length && (
              <div className="mrcd-welcome">
                <span className="mrcd-badge">Local snapshot</span>
                <h3>Start with the evidence.</h3>
                <p>Ask for the call plan, attrition risk, retention offers or maturity timing. Anything else gets a scope explanation rather than an invented answer.</p>
                <p>This renewal's conversation stays separate from other renewals and from the live agent chat in Guided and Explore.</p>
              </div>
            )}
            {conversation.map((exchange, index) => (
              <div className="mrcd-exchange" key={index}>
                <div className="mrcd-question"><strong>You</strong><p>{exchange.question}</p></div>
                <article className="mrcd-answer">
                  <header className="mrcd-answer-head">
                    <strong>{exchange.answer.subject}</strong>
                    <span className="mrcd-answer-meta">Snapshot {exchange.answer.asOf}</span>
                  </header>
                  {exchange.answer.blocks.map((block) => <AnswerBlockView block={block} key={block.title} />)}
                  <p className="mrcd-footnote">{exchange.answer.footnote}</p>
                </article>
              </div>
            ))}
          </div>
          <div className="mrcd-composer" hidden={panel !== "chat"}>
            <div className="mrcd-actions">
              {ACTIONS.map(([label, question]) => (
                <button type="button" key={question} onClick={() => ask(question)}>{label}</button>
              ))}
              <button type="button" onClick={draftFlyer}>Flyer draft</button>
            </div>
            <form onSubmit={(event) => {
              event.preventDefault();
              ask(drafts[selectedId] ?? "");
              setDrafts((previous) => ({ ...previous, [selectedId]: "" }));
            }}>
              <label htmlFor="mrcd-input">Ask about {selected.customerName}</label>
              <textarea id="mrcd-input" rows={3} value={drafts[selectedId] ?? ""}
                placeholder="e.g. What can I offer?"
                onChange={(event) => setDrafts((previous) => ({ ...previous, [selectedId]: event.target.value }))} />
              <div className="mrcd-submit-row">
                <small>Local answers only · no live retrieval</small>
                <button className="mrcd-primary" type="submit" disabled={!(drafts[selectedId] ?? "").trim()}>Ask</button>
              </div>
            </form>
          </div>
        </aside>
      </div>

      <div id="mrcd-subview-customers" role="tabpanel" aria-labelledby="mrcd-sub-customers" className="mrcd-sub" hidden={sub !== "customers"}>
        <CustomersView active={active && sub === "customers" && !openC} onOpen={(cid) => setOpenC({ cid, preferSupport: false })} />
        {openC && <CustomerWorkspace key={openC.cid} cid={openC.cid} preferSupport={openC.preferSupport}
          split={wsSplit} backLabel="Customers" onBack={() => setOpenC(null)} />}
      </div>
      <div id="mrcd-subview-wellness" role="tabpanel" aria-labelledby="mrcd-sub-wellness" className="mrcd-sub" hidden={sub !== "wellness"}>
        <WellnessView active={active && sub === "wellness" && !openW} onOpen={(cid) => setOpenW({ cid, preferSupport: true })} />
        {openW && <CustomerWorkspace key={openW.cid} cid={openW.cid} preferSupport={openW.preferSupport}
          split={wsSplit} backLabel="Financial wellness" onBack={() => setOpenW(null)} />}
      </div>
      <div id="mrcd-subview-mission" role="tabpanel" aria-labelledby="mrcd-sub-mission" className="mrcd-sub mrcd-mission" hidden={sub !== "mission"}>
        <MissionPanel book="mortgage" active={active && sub === "mission"} />
      </div>
    </section>
  );
}
