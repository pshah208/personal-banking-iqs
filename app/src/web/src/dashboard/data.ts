import rawSnapshot from "./snapshot.json";
import { evergreen } from "../lib/evergreen";
import { initialBrand, rebrand } from "../brand";

/** The generated snapshot, moved forward to the current week (see lib/evergreen)
 *  and relabelled from the authored "CFC Bank" to the bank this page opened as.
 *  main.tsx loads the brand manifest before this module is first imported. */
const snapshot = rebrand(evergreen(rawSnapshot), initialBrand());

export interface Offer {
  id: string;
  name: string;
  maxDiscountBps: number;
  cashbackCad: number;
  approvalLevel: string;
  notes: string;
}

export interface EligibleOffer extends Offer {
  recommended: boolean;
}

export interface CatalogueOffer extends Offer {
  segments: string[];
}

export interface Branch {
  id: string;
  name: string;
  province: string;
  manager: string;
  /** Figures as stated in branch_performance.csv. */
  renewalsStated: number;
  balanceMaturingStatedCad: number;
  highRiskStated: number;
  revenueAtRiskStatedCad: number;
  /** The same figures recounted from the renewal and risk rows. */
  renewalsCounted: number;
  balanceMaturingCountedCad: number;
  highRiskCounted: number;
  revenueAtRiskCountedCad: number;
  retentionRatePct: number;
  avgDiscountBps: number;
  advisorCapacity: number;
  maturingWithin30: number;
  /** Non-empty only where the two source views disagree. */
  reconciliation: string[];
}

export interface Product {
  id: string;
  name: string;
  category: string;
  summary: string;
  /** False for entries that are an advisory conversation, never a holding. */
  holdable: boolean;
  /** Empty means every segment; otherwise the only segments it is offered to. */
  segments: string[];
}

export interface Holding {
  id: string;
  name: string;
  category: string;
}

export interface CrossSell {
  id: string;
  name: string;
  category: string;
  summary: string;
  /** Local facts behind the recommendation, each carrying its own figures. */
  signals: string[];
  rank: number;
}

export interface Renewal {
  id: string;
  customerId: string;
  customerName: string;
  segment: string;
  province: string;
  branchId: string;
  branchName: string;
  advisorName: string;
  tenureYears: number;
  productsHeld: number;
  primaryRelationship: boolean;
  digitalEngagementScore: number;
  npsScore: number;
  originationChannel: string;
  /** Authored holdings, always exactly as long as productsHeld. Synthetic. */
  holdings: Holding[];
  crossSell: CrossSell[];
  /** Null when no local fact triggers the RP-006 affordability conversation. */
  reliefReview: { id: string; name: string; category: string; summary: string; signals: string[] } | null;
  preferredLanguage: string;
  productType: string;
  termMonths: number;
  balanceCad: number;
  propertyValueCad: number;
  ltvPct: number;
  insured: boolean;
  currentRatePct: number;
  offeredRatePct: number;
  rateIncreaseBps: number;
  paymentFrequency: string;
  amortizationYears: number;
  originationDate: string;
  maturityDate: string;
  /** Days from the snapshot date, never from the current clock. */
  daysToMaturity: number;
  maturityWindow: string;
  paymentShockPct: number;
  /** Null means the row cannot support an annuity recomputation, never zero. */
  paymentShockRecomputedPct: number | null;
  stage: string;
  riskScore: number;
  riskBand: string;
  renewalLikelihoodPct: number;
  riskDrivers: string[];
  competitorGapBps: number;
  rateShopping: boolean;
  serviceComplaint: boolean;
  annualRevenueCad: number;
  lifetimeValueCad: number;
  modelVersion: string;
  priorityRank: number;
  recommendedOffer: Offer;
  eligibleOffers: EligibleOffer[];
  callReason: string;
  riskSummary: string;
  offerSummary: string;
  maturitySummary: string;
  evidence: { iq: string; status: string; text: string }[];
  dataQuality: string[];
  sources: string[];
}

export const renewals: Renewal[] = snapshot.renewals;
export const branches: Branch[] = snapshot.branches;
export const offerCatalogue: CatalogueOffer[] = snapshot.offers;
export const bandCounts: Record<string, number> = snapshot.bandCounts;
export const snapshotAsOf: string = snapshot.snapshotAsOf;
export const snapshotDisclaimer: string = snapshot.disclaimer;
export const snapshotUnits: string = snapshot.units;
export const priorityBasis: string = snapshot.priorityBasis;
export const paymentShockBasis: string = snapshot.paymentShockBasis;
export const offerBasis: string = snapshot.offerBasis;
export const holdingsBasis: string = snapshot.holdingsBasis;
export const crossSellBasis: string = snapshot.crossSellBasis;
export const marketRateBasis: string = snapshot.marketRateBasis;
export const flyerBasis: string = snapshot.flyerBasis;
export const productCatalogue: Product[] = snapshot.productCatalogue;
export const clockBasis: string = snapshot.clockBasis;

const cad = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 0 });
export const money = (amount: number | null): string =>
  amount === null ? "Unavailable" : `CAD ${cad.format(amount)}`;
export const percent = (amount: number | null, places = 1): string =>
  amount === null ? "Unavailable" : `${amount.toFixed(places)}%`;
const normalize = (text: string): string =>
  text.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();

function topicFor(question: string, renewal: Renewal): string | undefined {
  let query = normalize(question);
  // Only whole supported requests are recognized, never arbitrary keyword hits.
  for (const label of [renewal.customerName, renewal.id, renewal.customerId]) {
    const name = normalize(label);
    if (query.endsWith(` for ${name}`)) query = query.slice(0, -name.length - 5);
    if (query.endsWith(` about ${name}`)) query = query.slice(0, -name.length - 7);
    if (query.endsWith(` on ${name}`)) query = query.slice(0, -name.length - 4);
  }
  query = query.replace(/^(please )?(give me |show me |show |prepare |summarize |summarise |what are |what is |why )?(the |a |an )?/, "");
  const topics: Record<string, string[]> = {
    callplan: ["call plan", "call this week", "should i call this week", "call priority",
      "why call this week", "why this file", "brief", "briefing", "customer brief",
      "renewal brief", "prep me", "summary", "overview", "snapshot"],
    risk: ["risk", "risks", "attrition risk", "risk drivers", "why is this at risk",
      "retention risk", "risk summary"],
    offers: ["offers", "offer", "retention offers", "what can i offer", "eligible offers",
      "offer options", "approvals", "approval level", "discount"],
    maturity: ["maturity", "maturities", "maturity timing", "payment shock", "rate change",
      "when does this mature", "renewal timing", "rate and payment"],
  };
  return Object.keys(topics).find((topic) => topics[topic].includes(query));
}

export interface AnswerFigure { label: string; value: string }
export interface AnswerBlock {
  title: string;
  figures?: AnswerFigure[];
  lines?: string[];
  evidence?: { iq: string; status: string; text: string }[];
  /** Small qualifying note shown once under the block heading. */
  note?: string;
  /** Rendered folded away so provenance stays available without crowding. */
  collapsible?: boolean;
}
export interface Answer {
  renewal: string;
  subject: string;
  asOf: string;
  supported: boolean;
  blocks: AnswerBlock[];
  footnote: string;
}

const SCOPE = "Supported topics: call plan, attrition risk, retention offers and maturity timing for the selected renewal only. Ask for one supported topic; freeform analysis, live rates, competitor pricing and news are unavailable.";
// Stated once per answer instead of on every line, so the figures stay readable.
// The dashboard header carries the full disclaimer.
const EVIDENCE_NOTE = "Records held in the local snapshot; not live retrievals.";
const FOOTNOTE = "SYNTHETIC DEMO ONLY: every customer, rate, score and offer here is invented. Not advice, pricing approval or a credit decision.";
const stripLiveNote = (text: string): string => text.replace(/\s*Not a live retrieval\.\s*$/, "");

/** Pure local lookup: no model, service, simulated tool execution or current clock. */
export function buildAnswer(renewal: Renewal | string, question: string): Answer {
  // Resolve the canonical snapshot entry; never trust caller-supplied figures.
  const id = typeof renewal === "string" ? renewal : renewal.id;
  const cached = snapshot.renewals.find(
    (entry) => entry.id === id || entry.customerId === id || entry.customerName === id,
  );
  if (!cached) {
    return {
      renewal: "Renewal not in this snapshot", subject: "", asOf: snapshotAsOf, supported: false,
      blocks: [
        { title: "Supported questions", lines: [SCOPE] },
        {
          title: "Sources", collapsible: true,
          lines: ["local snapshot.json generated from data/fabric-iq CSVs, data/work-iq and data/foundry-iq", snapshotUnits],
        },
      ],
      footnote: FOOTNOTE,
    };
  }
  const topic = topicFor(question, cached);
  const position: AnswerBlock = {
    title: "Position",
    figures: [
      { label: "Branch", value: `${cached.branchName} (${cached.province})` },
      { label: "Segment", value: cached.segment },
      { label: "Balance maturing", value: money(cached.balanceCad) },
      { label: "Loan to value", value: percent(cached.ltvPct) },
      { label: "Attrition band", value: `${cached.riskBand} · score ${cached.riskScore.toFixed(3)}` },
      { label: "Renewal likelihood", value: percent(cached.renewalLikelihoodPct) },
      { label: "Competitor rate gap", value: `${cached.competitorGapBps} bps` },
      { label: "Days to maturity", value: `${cached.daysToMaturity} from ${snapshotAsOf}` },
      { label: "Renewal stage", value: cached.stage },
    ],
  };
  const priority: AnswerBlock = { title: "Why this file", lines: [cached.callReason] };
  const risk: AnswerBlock = {
    title: "Attrition risk",
    lines: [cached.riskSummary],
  };
  const offers: AnswerBlock = {
    title: "Retention offers and approvals",
    figures: cached.eligibleOffers.map((offer) => ({
      label: `${offer.id}${offer.recommended ? " · recommended" : ""}`,
      value: `${offer.name} · ${offer.maxDiscountBps} bps${offer.cashbackCad ? ` + ${money(offer.cashbackCad)}` : ""} · ${offer.approvalLevel}`,
    })),
    lines: [cached.offerSummary, offerBasis],
  };
  const maturity: AnswerBlock = {
    title: "Maturity, rate and payment",
    figures: [
      { label: "Matures", value: `${cached.maturityDate} · ${cached.maturityWindow}` },
      { label: "Current rate", value: percent(cached.currentRatePct, 2) },
      { label: "Offered renewal rate", value: `${percent(cached.offeredRatePct, 2)} (+${cached.rateIncreaseBps} bps)` },
      { label: "Payment shock (recorded)", value: percent(cached.paymentShockPct) },
      { label: "Payment shock (recomputed)", value: percent(cached.paymentShockRecomputedPct) },
      { label: "Amortization remaining", value: `${cached.amortizationYears} years · ${cached.paymentFrequency}` },
    ],
    lines: [cached.maturitySummary],
  };
  const evidence: AnswerBlock = {
    title: "Evidence", note: EVIDENCE_NOTE,
    evidence: cached.evidence.map((item) => ({ ...item, text: stripLiveNote(item.text) })),
  };
  const basis: AnswerBlock = {
    title: "Basis and caveats", collapsible: true,
    lines: [priorityBasis, clockBasis, paymentShockBasis, ...cached.dataQuality, snapshotUnits],
  };
  const sources: AnswerBlock = { title: "Sources", collapsible: true, lines: cached.sources };
  const blocks = topic === "callplan"
    ? [priority, position, risk, offers, maturity, evidence, basis, sources]
    : topic === "risk"
      ? [risk, position, evidence, basis, sources]
      : topic === "offers"
        ? [offers, evidence, basis, sources]
        : topic === "maturity"
          ? [maturity, evidence, basis, sources]
          : [{ title: "Supported questions", lines: [SCOPE] }, sources];
  return {
    renewal: cached.id,
    subject: `${cached.customerName} · ${cached.id}`,
    asOf: snapshotAsOf,
    supported: Boolean(topic),
    blocks,
    footnote: FOOTNOTE,
  };
}

/** Flat transcript of the same answer: used for assertions and plain-text copy. */
export function answerQuestion(renewal: Renewal | string, question: string): string {
  const answer = buildAnswer(renewal, question);
  const parts = [`${answer.subject || answer.renewal} — snapshot ${answer.asOf}`];
  for (const block of answer.blocks) {
    const body: string[] = [];
    if (block.note) body.push(block.note);
    block.figures?.forEach((figure) => body.push(`${figure.label}: ${figure.value}`));
    block.lines?.forEach((line) => body.push(line));
    block.evidence?.forEach((item) => body.push(`${item.iq} (${item.status}): ${item.text}`));
    if (!body.length) continue;
    const heading = block.title === "Sources" ? "Sources:" : block.title;
    parts.push(`${heading}\n${body.map((line) => `  ${line}`).join("\n")}`);
  }
  parts.push(answer.footnote);
  return parts.join("\n\n");
}
