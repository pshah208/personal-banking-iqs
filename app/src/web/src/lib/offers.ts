/**
 * Fetching the RP-003 offer catalogue, and re-exporting the rules that govern it.
 *
 * Shared because two callers need the same catalogue: `Flyer` checks the offer
 * it is about to draw, and `DataTable` resolves a "Recommended Offer" cell into
 * a real offer before it can build anything. Fetching in both would mean two
 * requests and, worse, two chances to disagree about what is approved.
 *
 * The fetch is a module-level promise rather than per-component state, so the
 * catalogue is fetched once per page load however many tables and flyers appear.
 *
 * The rules themselves live in `offerPolicy.ts`, which imports nothing and
 * fetches nothing, so the snapshot dashboard can apply exactly the same judgements
 * to its local snapshot without a request. They are re-exported from here so
 * every existing import site is unchanged.
 */

import { useEffect, useState } from "react";
import type { CatalogueOffer } from "../types";

export {
  beats, bestUnlockableOffer, buildFlyerSpec, offerHeadline, RELATIONSHIP_OFFERS,
  resolveOffer, richerOf,
} from "./offerPolicy";
export type { RowFacts } from "./offerPolicy";

let cached: Promise<CatalogueOffer[]> | null = null;

export function loadCatalogue(): Promise<CatalogueOffer[]> {
  if (!cached) {
    cached = fetch("/api/offers")
      .then((r) => (r.ok ? r.json() : []))
      .catch(() => [] as CatalogueOffer[]);
  }
  return cached;
}

/**
 * The catalogue, fetched once.
 *
 * `supplied` short-circuits the fetch entirely for callers that already hold a
 * catalogue — the snapshot dashboard, which is offline by design. It is not a
 * default or a fallback: when it is present no request is made at all, and when
 * it is absent the behaviour is exactly what it always was.
 */
export function useOfferCatalogue(supplied?: CatalogueOffer[]): CatalogueOffer[] {
  const [catalogue, setCatalogue] = useState<CatalogueOffer[]>([]);
  useEffect(() => {
    if (supplied) return;
    let live = true;
    loadCatalogue().then((c) => { if (live) setCatalogue(c); });
    return () => { live = false; };
  }, [supplied]);
  return supplied ?? catalogue;
}
