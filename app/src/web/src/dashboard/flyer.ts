/**
 * The flyer draft: choosing an offer, pricing it, and saying what is not
 * known.
 *
 * WHAT THIS IS
 * ------------
 * A reviewable draft for a human, produced entirely from the local snapshot. It
 * is never an approved price. Every offer in RP-003 carries an approval level
 * and most carry a condition; this module selects between offers, states the
 * arithmetic, and names the approval and the evidence that is still missing.
 *
 * WHY THE SELECTION IS NOT SIMPLY "THE BIGGEST DISCOUNT THEY ARE ELIGIBLE FOR"
 * ---------------------------------------------------------------------------
 * Segment eligibility is only the first gate. RP-003 conditions are part of the
 * offer, and RP-002 requires documented competitor evidence before discretionary
 * pricing is granted. Three of the eight offers rest on facts this repository
 * does not hold — a written competitor offer (OFR-01, OFR-08) or verified
 * investable assets (OFR-05) — so drafting them would put a number in front of a
 * customer on the strength of evidence nobody has. They are shown, with the
 * exact missing evidence named, and not selected.
 *
 * OFR-07 is excluded from selection for a different reason: it is amortization
 * relief under RP-006, a hardship path. It is surfaced separately as an
 * affordability conversation, never as a promotion.
 *
 * Ranking among what survives reuses `richerOf` from `lib/offerPolicy`, so this
 * page and the agent-driven flyer agree on what "better" means — basis points
 * first because they apply for the whole term, cash only as a tie-break, and no
 * invented exchange rate between the two.
 */

import { bestUnlockableOffer, buildFlyerSpec, richerOf } from "../lib/offerPolicy";
import type { CatalogueOffer, FlyerSpec } from "../types";
import {
  clockBasis, crossSellBasis, flyerBasis, holdingsBasis, marketRateBasis, money,
  offerBasis, offerCatalogue, percent, renewals, snapshotAsOf,
  type CrossSell, type EligibleOffer, type Holding, type Renewal,
} from "./data";

/** Stated once per artifact, exactly as the local chat answers do. */
export const FLYER_DISCLOSURE =
  "SYNTHETIC DEMO ONLY: this customer, mortgage, rate, score, product holding and "
  + "offer are invented, and the product holdings and catalogue are generated for "
  + "this dashboard. Not advice, not pricing approval, not a credit decision.";

export type ConditionStatus = "supported" | "unmet" | "unevidenced" | "excluded";

export interface OfferAssessment {
  id: string;
  name: string;
  maxDiscountBps: number;
  cashbackCad: number;
  approvalLevel: string;
  status: ConditionStatus;
  /** Why it was kept or set aside, in the words of the condition it turns on. */
  reason: string;
  selected: boolean;
}

export interface FlyerDraft {
  renewalId: string;
  customerName: string;
  segment: string;
  asOf: string;
  offer: EligibleOffer | null;
  discountBps: number;
  cashbackCad: number;
  offeredRatePct: number;
  /** Null when the selected offer carries no rate discount, never zero. */
  effectiveRatePct: number | null;
  rateLine: string;
  approvalLevel: string;
  assessments: OfferAssessment[];
  why: string[];
  value: { label: string; value: string }[];
  marketNote: string;
  spec: FlyerSpec | null;
  alternativeNote: string;
  holdings: Holding[];
  crossSell: CrossSell[];
  relief: Renewal["reliefReview"];
  disclosure: string;
  basis: string[];
}

/** The snapshot catalogue in the shape the shared policy rules expect. */
export const flyerCatalogue: CatalogueOffer[] = offerCatalogue.map((offer) => ({
  code: offer.id,
  name: offer.name,
  max_bps: offer.maxDiscountBps,
  max_cash: offer.cashbackCad,
  segments: offer.segments,
  approver: offer.approvalLevel,
  condition: offer.notes,
}));

/**
 * Whether an offer's own condition can be shown to hold from local facts.
 *
 * Every branch names the condition it is testing and the field it tested it
 * against, so the panel can print the reason rather than a verdict.
 */
function assess(offer: EligibleOffer, renewal: Renewal): { status: ConditionStatus; reason: string } {
  const chequing = renewal.holdings.some((held) => held.id === "PRD-CHQ");
  switch (offer.id) {
    case "OFR-01":
      return {
        status: "unevidenced",
        reason:
          "Matches a documented written competitor offer. RP-002 requires that document "
          + `before discretionary pricing is granted, and none is held here: the `
          + `${renewal.competitorGapBps} bps competitor gap is a scored field in `
          + "renewal_risk_scores.csv, not a customer's written quote.",
      };
    case "OFR-02":
      return chequing && renewal.productsHeld >= 3
        ? {
            status: "supported",
            reason:
              `Condition met from the authored holdings list: ${renewal.productsHeld} products `
              + "including an everyday chequing account.",
          }
        : {
            status: "unmet",
            reason:
              `Needs three or more products including a chequing account. The authored `
              + `holdings list records ${renewal.productsHeld} product`
              + `${renewal.productsHeld === 1 ? "" : "s"}`
              + `${chequing ? "" : " and no chequing account"}.`,
          };
    case "OFR-03":
      return renewal.daysToMaturity >= 0 && renewal.daysToMaturity <= 120
        ? {
            status: "supported",
            reason:
              `Inside the 120-day early-renewal window: matures ${renewal.maturityDate}, `
              + `${renewal.daysToMaturity} days after the ${snapshotAsOf} snapshot.`,
          }
        : {
            status: "unmet",
            reason:
              `Outside the 120-day early-renewal window: ${renewal.daysToMaturity} days to `
              + `maturity from the ${snapshotAsOf} snapshot.`,
          };
    case "OFR-04":
      return {
        status: "supported",
        reason:
          "Cash in lieu of a rate discount. The clawback on early payout must be disclosed "
          + "in writing before acceptance; that disclosure is a duty at presentation, not "
          + "evidence to gather first.",
      };
    case "OFR-05":
      return {
        status: "unevidenced",
        reason:
          "Requires CAD 1M or more investable assets held at the bank, verified at offer. "
          + "No investable-asset balance is recorded anywhere in this snapshot, so the "
          + "condition can be neither met nor ruled out here.",
      };
    case "OFR-06":
      return {
        status: "supported",
        reason:
          "A straight blend of the existing rate with the new term needs no "
          + "re-qualification, so nothing outside this snapshot gates it.",
      };
    case "OFR-07":
      return {
        status: "excluded",
        reason:
          "Amortization relief under RP-006: Credit Risk approval and a TDS/GDS re-test. "
          + "It is a hardship path, not a promotion, so it is never drafted onto a flyer. "
          + "It is raised separately as an affordability conversation where the local "
          + "facts point that way.",
      };
    case "OFR-08":
      return {
        status: "unevidenced",
        reason:
          "Deployed only where a confirmed competitor switch package exists, evidenced per "
          + `RP-002. This snapshot holds no such package${renewal.rateShopping
            ? "; a rate-shopping signal is recorded, but a signal is not a documented offer"
            : ""}.`,
      };
    default:
      return {
        status: "unevidenced",
        reason: "Not a recognised RP-003 offer in this snapshot, so it is not drafted.",
      };
  }
}

const round2 = (value: number): number => Math.round(value * 100) / 100;

/**
 * Build the flyer draft for one renewal.
 *
 * Pure: a local lookup over the snapshot, with no model, no service, no
 * simulated tool call and no reading of the current clock.
 */
export function buildFlyerDraft(renewal: Renewal | string): FlyerDraft | null {
  const id = typeof renewal === "string" ? renewal : renewal.id;
  // Never trust caller-supplied figures; resolve the canonical snapshot entry.
  const cached = renewals.find(
    (entry) => entry.id === id || entry.customerId === id || entry.customerName === id,
  );
  if (!cached) return null;

  const assessments: OfferAssessment[] = cached.eligibleOffers.map((offer) => ({
    id: offer.id,
    name: offer.name,
    maxDiscountBps: offer.maxDiscountBps,
    cashbackCad: offer.cashbackCad,
    approvalLevel: offer.approvalLevel,
    selected: false,
    ...assess(offer, cached),
  }));

  const supported = assessments.filter((item) => item.status === "supported");
  const byId = new Map(flyerCatalogue.map((offer) => [offer.code, offer]));
  const winner = supported.length
    ? supported
        .map((item) => byId.get(item.id)!)
        .reduce(richerOf)
    : undefined;
  const chosen = winner
    ? cached.eligibleOffers.find((offer) => offer.id === winner.code) ?? null
    : null;
  for (const item of assessments) item.selected = item.id === chosen?.id;

  const discountBps = chosen?.maxDiscountBps ?? 0;
  const effective = chosen && discountBps > 0
    ? round2(cached.offeredRatePct - discountBps / 100)
    : null;
  const rateLine = !chosen
    ? "No offer can be drafted from the local facts, so no rate is shown."
    : discountBps > 0
      ? `${percent(cached.offeredRatePct, 2)} offered renewal rate less `
        + `${discountBps} bps (${(discountBps / 100).toFixed(2)}%) = `
        + `${percent(effective, 2)} — the maximum discount available under ${chosen.id}, `
        + `subject to ${chosen.approvalLevel} approval. Not a quoted or guaranteed rate.`
      : `${chosen.id} carries no rate discount, so the rate stays at the offered renewal `
        + `rate of ${percent(cached.offeredRatePct, 2)}; the value is `
        + `${money(chosen.cashbackCad)} cashback, subject to ${chosen.approvalLevel} approval.`;

  const spec = chosen
    ? buildFlyerSpec({
        customer: cached.customerName,
        segment: cached.segment,
        offerText: `${chosen.id} ${chosen.name}`,
        approval: chosen.approvalLevel,
        maturity: cached.maturityDate,
      }, flyerCatalogue)
    : null;
  const bundle = chosen
    ? bestUnlockableOffer(cached.segment, byId.get(chosen.id), flyerCatalogue)
    : undefined;

  const why = [
    `Renewal increase: ${percent(cached.currentRatePct, 2)} now against an offered renewal `
    + `rate of ${percent(cached.offeredRatePct, 2)} (+${cached.rateIncreaseBps} bps), maturing `
    + `${cached.maturityDate}, ${cached.daysToMaturity} days after the ${snapshotAsOf} snapshot.`,
    `Attrition: ${cached.riskBand} band, score ${cached.riskScore.toFixed(3)}, renewal `
    + `likelihood ${percent(cached.renewalLikelihoodPct)} from ${cached.modelVersion}. `
    + `Recorded drivers: ${cached.riskDrivers.length ? cached.riskDrivers.join("; ") : "none recorded"}. `
    + "A model score is not a decision and not a prediction of this customer's behaviour.",
    `Competitor position: ${cached.competitorGapBps} bps scored gap, rate-shopping signal `
    + `${cached.rateShopping ? "recorded" : "not recorded"}, service complaint in the last `
    + `12 months ${cached.serviceComplaint ? "recorded" : "not recorded"}.`,
    `Relationship value: ${money(cached.balanceCad)} balance on a property recorded at `
    + `${money(cached.propertyValueCad)} (LTV ${percent(cached.ltvPct)}), `
    + `${cached.tenureYears} years tenure, ${cached.productsHeld} products held, `
    + `${cached.primaryRelationship ? "primary" : "not the primary"} relationship, NPS `
    + `${cached.npsScore}, segment ${cached.segment}. Annual revenue exposure `
    + `${money(cached.annualRevenueCad)}; five-year lifetime value ${money(cached.lifetimeValueCad)}.`,
    chosen
      ? `Selection: ${cached.segment} is eligible for ${cached.eligibleOffers.length} of `
        + `${offerCatalogue.length} catalogue offers; ${supported.length} of those have a `
        + `condition this snapshot can support. ${chosen.id} ${chosen.name} carries the `
        + "largest rate discount among them — rate discount decides first because it applies "
        + "for the whole term, and cashback only breaks a tie, because basis points and "
        + "dollars cannot be compared without assuming how long this customer stays."
      : `Selection: none of the ${cached.eligibleOffers.length} offers ${cached.segment} is `
        + "eligible for has a condition this snapshot can support, so no offer is drafted. "
        + "The list below names the evidence each one is waiting on.",
    "RP-003: discounts do not stack, so exactly one offer is drafted and any alternative is a "
    + "swap rather than an addition. RP-002: the discount above is a ceiling, not a grant — "
    + `${chosen ? chosen.approvalLevel : "the named approver"} still has to approve it.`,
    "RP-007, fair treatment at renewal: the only deadline used is the recorded maturity date, "
    + "the conditions are shown with the offer rather than after it, and nothing here is "
    + "worded to hurry the customer.",
  ];

  const value = [
    { label: "Balance maturing", value: money(cached.balanceCad) },
    { label: "Property value", value: money(cached.propertyValueCad) },
    { label: "Loan to value", value: percent(cached.ltvPct) },
    { label: "Tenure", value: `${cached.tenureYears} years` },
    { label: "Products held", value: `${cached.productsHeld}` },
    { label: "Primary relationship", value: cached.primaryRelationship ? "Yes" : "No" },
    { label: "NPS", value: `${cached.npsScore}` },
    { label: "Digital engagement", value: `${cached.digitalEngagementScore} of 100` },
    { label: "Annual revenue exposure", value: money(cached.annualRevenueCad) },
    { label: "Five-year lifetime value", value: money(cached.lifetimeValueCad) },
  ];

  return {
    renewalId: cached.id,
    customerName: cached.customerName,
    segment: cached.segment,
    asOf: snapshotAsOf,
    offer: chosen,
    discountBps,
    cashbackCad: chosen?.cashbackCad ?? 0,
    offeredRatePct: cached.offeredRatePct,
    effectiveRatePct: effective,
    rateLine,
    approvalLevel: chosen?.approvalLevel ?? "Unavailable",
    assessments,
    why,
    value,
    marketNote: marketRateBasis,
    spec,
    alternativeNote: bundle
      ? `${bundle.code} ${bundle.headline} is drawn on the flyer as an alternative route - `
        + `"${bundle.action}". ${bundle.detail} It replaces the offer above `
        + "rather than adding to it, because RP-003 discounts do not stack."
      : "No alternative relationship offer beats the drafted one for this segment, so none is "
        + "drawn. An alternative is only shown when it is better on every axis.",
    holdings: cached.holdings,
    crossSell: cached.crossSell,
    relief: cached.reliefReview,
    disclosure: FLYER_DISCLOSURE,
    basis: [flyerBasis, offerBasis, holdingsBasis, crossSellBasis, clockBasis],
  };
}

/** Flat transcript of the same draft: used for assertions and plain-text copy. */
export function flyerTranscript(renewal: Renewal | string): string {
  const draft = buildFlyerDraft(renewal);
  if (!draft) {
    return `Renewal not in this snapshot — snapshot ${snapshotAsOf}\n\n${FLYER_DISCLOSURE}`;
  }
  const parts = [
    `${draft.customerName} · ${draft.renewalId} — flyer draft, snapshot ${draft.asOf}`,
    `Drafted offer:\n  ${draft.offer ? `${draft.offer.id} ${draft.offer.name}` : "None"}\n  ${draft.rateLine}`,
    `Approval required:\n  ${draft.approvalLevel}`,
    `Why this offer:\n${draft.why.map((line) => `  ${line}`).join("\n")}`,
    `Offers considered:\n${draft.assessments.map((item) =>
      `  ${item.id} ${item.name} (${item.maxDiscountBps} bps, ${item.approvalLevel}) — `
      + `${item.status}${item.selected ? ", drafted" : ""}: ${item.reason}`).join("\n")}`,
    `Market rates:\n  ${draft.marketNote}`,
    `Alternative:\n  ${draft.alternativeNote}`,
    `Products held:\n${draft.holdings.map((held) => `  ${held.id} ${held.name}`).join("\n")}`,
    `Cross-sell propensity:\n${draft.crossSell.map((item) =>
      `  ${item.rank}. ${item.id} ${item.name} — ${item.signals.join(" ")}`).join("\n")}`,
  ];
  if (draft.relief) {
    parts.push(`Affordability conversation:\n  ${draft.relief.name} — ${draft.relief.signals.join(" ")}`);
  }
  parts.push(`Basis:\n${draft.basis.map((line) => `  ${line}`).join("\n")}`);
  parts.push(draft.disclosure);
  return parts.join("\n\n");
}
