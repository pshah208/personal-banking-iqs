/**
 * The RP-003 offer catalogue rules, with no React and no I/O.
 *
 * Extracted from `lib/offers.ts` unchanged so that two very different callers can
 * share one set of judgements:
 *
 *   - the agent path, where `Markdown` renders a ```flyer block the agent emitted
 *     and the catalogue arrives from `/api/offers`;
 *   - the snapshot dashboard, which must not make a request at all and supplies the
 *     same catalogue out of its local snapshot.
 *
 * `lib/offers.ts` re-exports everything here, so every existing import keeps
 * working and there is still exactly one place where "does this offer beat that
 * one" is decided.
 */

import type { BundleOffer, CatalogueOffer, FlyerSpec } from "../types";
import { currentBrand, getBrand } from "../brand";

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

/**
 * Resolve a "Recommended Offer" cell to a catalogue entry.
 *
 * The cell is written for a human — "Private Wealth Preferred Pricing", or
 * sometimes "OFR-05 Private Wealth Preferred Pricing" — so match on an explicit
 * code first, then on the offer name with punctuation and case flattened.
 *
 * Returns undefined when nothing matches, which is deliberate: an unrecognised
 * offer must fail the policy check rather than quietly resolve to the nearest
 * thing, since "close enough" is exactly what RP-003 forbids.
 */
export function resolveOffer(
  text: string, catalogue: CatalogueOffer[],
): CatalogueOffer | undefined {
  if (!text) return undefined;
  const clean = text.replace(/[*`]/g, "").trim();

  const code = clean.match(/OFR-\d{2}/i);
  if (code) {
    const hit = catalogue.find(
      (o) => o.code.toLowerCase() === code[0].toLowerCase(),
    );
    if (hit) return hit;
  }

  const n = norm(clean);
  if (!n) return undefined;
  return catalogue.find((o) => {
    const on = norm(o.name);
    return on === n || n.includes(on) || on.includes(n);
  });
}

/** A headline that states the offer's ceiling in the units it is capped in. */
export function offerHeadline(o: CatalogueOffer): string {
  const rate = o.max_bps > 0 ? `Up to ${(o.max_bps / 100).toFixed(2)}% rate discount` : "";
  const cash = o.max_cash > 0 ? `CAD ${o.max_cash.toLocaleString("en-CA")} cashback` : "";
  if (rate && cash) return `${rate} plus ${cash}`;
  return rate || cash || o.name;
}

/* ----------------------------------------------------------------- build --- */

/**
 * Offers a customer can unlock by deepening their relationship with the bank,
 * mapped to the customer-facing action that unlocks each.
 *
 * WHY AN ALLOW-LIST AND NOT "THE BEST OFFER THEY QUALIFY FOR"
 * ----------------------------------------------------------
 * Most of RP-003 is not upsellable, and picking purely on value would surface
 * offers that are wrong to put in front of a customer as an invitation:
 *
 *   OFR-01 / OFR-08  are unlocked by producing a competitor's offer. Inviting a
 *                    customer to go shopping is a strange retention play, and
 *                    the higher number on OFR-08 would make it win on value
 *                    almost every time.
 *   OFR-04           its condition is a clawback disclosure, not something the
 *                    customer can go and satisfy.
 *   OFR-07           is amortisation relief governed by RP-006 credit risk. It
 *                    is a hardship path, and advertising it as an upgrade would
 *                    be crass as well as wrong.
 *   OFR-03 / OFR-06  are choices about the mortgage itself rather than about
 *                    bringing more to the bank.
 *
 * That leaves the two entries whose conditions really are "hold more with us".
 * They are listed explicitly so that adding an offer to the catalogue can never
 * silently start advertising it.
 */
export const RELATIONSHIP_OFFERS: Record<string, string> = {
  "OFR-02": "Bring your day-to-day banking across",
  "OFR-05": "Bring your investments under one roof",
};

/**
 * Whether `candidate` is unambiguously a better deal than `primary`.
 *
 * Strictly better on at least one axis and worse on neither. Anything else is
 * a trade-off the flyer is not entitled to make on the customer's behalf: an
 * offer with a higher rate discount but less cash might be better or worse
 * depending on the balance and how long they stay, and the flyer knows neither.
 */
export function beats(candidate: CatalogueOffer, primary: CatalogueOffer): boolean {
  const better =
    candidate.max_bps > primary.max_bps || candidate.max_cash > primary.max_cash;
  const worse =
    candidate.max_bps < primary.max_bps || candidate.max_cash < primary.max_cash;
  return better && !worse;
}

/**
 * Pick the more valuable of two candidates.
 *
 * Basis points and dollars are not comparable without the mortgage balance,
 * which the flyer does not have. Rather than invent an exchange rate, rate
 * discount wins first — it applies for the whole term, where cashback is paid
 * once — and cash breaks the tie.
 */
export function richerOf(a: CatalogueOffer, b: CatalogueOffer): CatalogueOffer {
  if (a.max_bps !== b.max_bps) return a.max_bps > b.max_bps ? a : b;
  return a.max_cash >= b.max_cash ? a : b;
}

/**
 * The best offer this customer could unlock, or undefined.
 *
 * The selection workflow, in order:
 *
 *   1. Require a known segment. Step 2 cannot be evaluated without it, and an
 *      offer whose eligibility cannot be verified is not presented.
 *   2. Keep only relationship-deepening offers (see RELATIONSHIP_OFFERS).
 *   3. Keep only those eligible for the segment. RP-003's SEGMENT INTEGRITY
 *      rule applies to a "you could also qualify" panel exactly as it does to
 *      the main offer — it is still material put in front of a client.
 *   4. Drop the offer already recommended, or the flyer shows the same thing
 *      twice and implies it can be claimed twice.
 *   5. Drop anything that does not clearly beat the current offer. Because
 *      offers do not stack, this panel is a swap — without this step a High Net
 *      Worth client already offered 35 bps gets invited to take on more products
 *      in exchange for 20.
 *   6. Of whatever survives, take the most valuable.
 */
export function bestUnlockableOffer(
  segment: string | undefined, primary: CatalogueOffer | undefined,
  catalogue: CatalogueOffer[],
): BundleOffer | undefined {
  if (!segment) return undefined;

  const candidates = catalogue.filter(
    (o) =>
      o.code in RELATIONSHIP_OFFERS
      && o.segments.includes(segment)
      && o.code !== primary?.code
      && (!primary || beats(o, primary)),
  );
  if (!candidates.length) return undefined;

  const best = candidates.reduce(richerOf);
  return {
    headline: offerHeadline(best),
    detail: best.condition,
    action: RELATIONSHIP_OFFERS[best.code],
    code: best.code,
    ...(best.max_bps > 0 ? { bps: best.max_bps } : {}),
    ...(best.max_cash > 0 ? { cash: best.max_cash } : {}),
  };
}

/**
 * Build a flyer from one row of a renewal table.
 *
 * Only the offer named in the row is presented as *the* offer. It would be easy
 * to bundle in every offer the segment is eligible for and produce a
 * fuller-looking flyer, but RP-003 is explicit that discounts do not stack and
 * that the recommendation carries a specific approval level — so inventing a
 * second offer would put a number in front of a customer that nobody approved.
 *
 * The bundle path is carried separately and drawn as an alternative for exactly
 * that reason: it is a route to a different approved offer, not a top-up of this
 * one.
 */
export function buildFlyerSpec(
  row: RowFacts, catalogue: CatalogueOffer[],
): FlyerSpec {
  const offer = resolveOffer(row.offerText ?? "", catalogue);
  const year = row.maturity?.match(/(20\d{2})/)?.[1];

  return {
    eyebrow: "Mortgage Renewal",
    title: year ? `${getBrand(currentBrand()).short} ${year} Renewal Event` : `${getBrand(currentBrand()).short} Renewal Event`,
    subtitle: "Renew early and lock in your rate",
    customer: row.customer,
    segment: row.segment,
    offers: [
      offer
        ? {
            headline: offerHeadline(offer),
            detail: offer.name,
            code: offer.code,
            // Set explicitly so the policy check compares numbers rather than
            // re-parsing the prose it was just handed.
            ...(offer.max_bps > 0 ? { bps: offer.max_bps } : {}),
            ...(offer.max_cash > 0 ? { cash: offer.max_cash } : {}),
          }
        : {
            // Unresolved on purpose — the flyer will mark it as unapproved.
            headline: row.offerText || "Retention offer to be confirmed",
            detail: "Not matched to an approved RP-003 offer",
          },
    ],
    bundle: bestUnlockableOffer(row.segment, offer, catalogue),
    approval: row.approval || offer?.approver || "Pricing Committee",
    conditions: offer ? [offer.condition] : [],
    // The renewal decision is moot after maturity, so that date is the deadline
    // the customer is actually working to.
    expiry: row.maturity,
  };
}

export interface RowFacts {
  customer: string;
  segment?: string;
  offerText?: string;
  approval?: string;
  maturity?: string;
}
