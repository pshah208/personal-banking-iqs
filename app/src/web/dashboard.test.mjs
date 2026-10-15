import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";

const snapshot = JSON.parse(readFileSync(new URL("./src/dashboard/snapshot.json", import.meta.url)));

/* One sandbox realm for every module under test, so modules that import each
   other (dashboard/flyer imports dashboard/data and lib/offerPolicy) share the
   same instances rather than each getting a private copy of the snapshot.
   Arrays built inside the sandbox are still a different realm from this file's,
   so assertions below compare joined strings rather than using deepEqual. */
const context = vm.createContext({ Intl, console });
const loaded = new Map();
const resolve = (from, request) => {
  const parts = from.split("/").slice(0, -1);
  for (const segment of request.split("/")) {
    if (segment === ".") continue;
    else if (segment === "..") parts.pop();
    else parts.push(segment);
  }
  return parts.join("/");
};

function load(id) {
  if (loaded.has(id)) return loaded.get(id);
  const source = readFileSync(new URL(`./src/${id}.ts`, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const moduleExports = {};
  loaded.set(id, moduleExports);
  const factory = vm.runInContext(
    `(function (exports, require) {\n${compiled}\n})`, context, { filename: `${id}.ts` },
  );
  factory(moduleExports, (request) => {
    if (request.endsWith("snapshot.json")) return { default: snapshot };
    return load(resolve(id, request));
  });
  return moduleExports;
}

const exports = load("dashboard/data");
const flyer = load("dashboard/flyer");
const policy = load("lib/offerPolicy");

// Renewals whose Work IQ card is backed by a local record that names the renewal
// ID explicitly. Every other renewal must stay honestly "unavailable".
const LOCAL_WORK = {
  "RNW-5008": ["EM-017", "TC-304"],
  "RNW-5014": ["EM-008", "EM-009", "TC-301"],
  "RNW-5021": ["EM-017", "TC-304"],
  "RNW-5033": ["EM-011", "TC-302"],
  "RNW-5044": ["EM-017", "TC-304"],
};
const TOPICS = ["call plan", "risk", "offers", "maturity"];
const iq = (renewal, name) => renewal.evidence.find((item) => item.iq === name);

test("fifty distinct renewals with the declared shape and units", () => {
  assert.equal(exports.renewals.length, 50);
  assert.equal(new Set(exports.renewals.map((r) => r.id)).size, 50);
  assert.equal(new Set(exports.renewals.map((r) => r.customerId)).size, 50);
  // The snapshot is authored as at 2026-08-03 and moved to the current week by lib/evergreen.
  assert.equal(exports.snapshotAsOf, load("lib/evergreen").shiftText("2026-08-03"));
  assert.match(exports.snapshotDisclaimer, /SYNTHETIC DEMO ONLY/);
  assert.match(exports.clockBasis, /never from the current clock/);
  assert.equal(
    exports.renewals.map((r) => r.priorityRank).sort((a, b) => a - b).join(","),
    Array.from({ length: 50 }, (_, index) => index + 1).join(","),
  );
  for (const renewal of exports.renewals) {
    assert.ok(renewal.balanceCad > 0 && renewal.propertyValueCad > 0);
    assert.ok(Math.abs(renewal.balanceCad / renewal.propertyValueCad * 100 - renewal.ltvPct) <= 0.1);
    assert.equal(renewal.rateIncreaseBps, Math.round((renewal.offeredRatePct - renewal.currentRatePct) * 100));
    assert.ok(["High", "Medium", "Low"].includes(renewal.riskBand));
    // Unknown values must be null so the UI can print "Unavailable", never zero.
    assert.ok(renewal.paymentShockRecomputedPct === null || typeof renewal.paymentShockRecomputedPct === "number");
    assert.ok(renewal.eligibleOffers.some((offer) => offer.recommended));
    assert.equal(
      renewal.eligibleOffers.filter((offer) => offer.recommended)[0].id,
      renewal.recommendedOffer.id,
    );
    assert.equal(renewal.evidence.map((item) => item.iq).join(" | "),
      ["Fabric IQ", "Work IQ", "Foundry IQ", "Web IQ"].join(" | "));
  }
});

test("branch cards reconcile against the renewal rows and never double count", () => {
  assert.equal(exports.branches.length, 3);
  let renewalTotal = 0, balanceTotal = 0, highTotal = 0;
  for (const branch of exports.branches) {
    const rows = exports.renewals.filter((renewal) => renewal.branchId === branch.id);
    assert.equal(branch.renewalsCounted, rows.length);
    assert.equal(branch.balanceMaturingCountedCad, rows.reduce((sum, r) => sum + r.balanceCad, 0));
    assert.equal(branch.highRiskCounted, rows.filter((r) => r.riskBand === "High").length);
    assert.equal(branch.revenueAtRiskCountedCad, rows.reduce((sum, r) => sum + r.annualRevenueCad, 0));
    assert.equal(branch.maturingWithin30, rows.filter((r) => r.daysToMaturity <= 30).length);
    // A disagreement between the branch row and the renewal rows must be stated,
    // never silently resolved by preferring one source.
    const disagreements = [
      branch.renewalsStated !== branch.renewalsCounted,
      branch.balanceMaturingStatedCad !== branch.balanceMaturingCountedCad,
      branch.highRiskStated !== branch.highRiskCounted,
      branch.revenueAtRiskStatedCad !== branch.revenueAtRiskCountedCad,
    ].filter(Boolean).length;
    assert.equal(branch.reconciliation.length, disagreements);
    renewalTotal += branch.renewalsCounted;
    balanceTotal += branch.balanceMaturingCountedCad;
    highTotal += branch.highRiskCounted;
  }
  assert.equal(renewalTotal, 50);
  assert.equal(balanceTotal, exports.renewals.reduce((sum, r) => sum + r.balanceCad, 0));
  assert.equal(highTotal, exports.bandCounts.High);
  assert.equal(
    exports.bandCounts.High + exports.bandCounts.Medium + exports.bandCounts.Low,
    50,
  );
});

test("Web IQ is never presented as available and Fabric IQ is always the local CSV snapshot", () => {
  for (const renewal of exports.renewals) {
    assert.equal(iq(renewal, "Web IQ").status, "unavailable");
    assert.match(iq(renewal, "Web IQ").text, /no Web IQ records/i);
    assert.ok(!/rate|news/i.test(iq(renewal, "Web IQ").text.replace(/competitor rates, market news/i, "")));
    assert.equal(iq(renewal, "Fabric IQ").status, "synthetic");
    assert.match(iq(renewal, "Fabric IQ").text, /No Fabric service was queried/);
  }
});

test("exactly the five renewals named in local Work IQ records carry Work evidence", () => {
  const held = exports.renewals
    .filter((renewal) => iq(renewal, "Work IQ").status === "synthetic")
    .map((renewal) => renewal.id);
  assert.equal(held.sort().join(","), Object.keys(LOCAL_WORK).join(","));
});

test("Foundry IQ policies are labelled firm-wide and never named as customer documents", () => {
  const names = new Set(exports.renewals.map((renewal) => renewal.customerName));
  for (const renewal of exports.renewals) {
    const card = iq(renewal, "Foundry IQ");
    assert.equal(card.status, "synthetic");
    assert.match(card.text, /Firm-wide standard RP-\d+/);
    assert.match(card.text, /not a\s+customer-specific document/);
    assert.match(card.text, /Not a live retrieval\.$/);
    for (const name of names) assert.ok(!card.text.includes(name));
    assert.ok(renewal.sources.some((s) => /foundry-iq\/renewal_policies\.json#RP-\d+/.test(s)));
  }
});

for (const renewal of exports.renewals) {
  const expected = LOCAL_WORK[renewal.id];
  test(`${renewal.id}: Work IQ evidence is ${expected ? "held locally and cited" : "honestly unavailable"}`, () => {
    const card = iq(renewal, "Work IQ");
    if (!expected) {
      assert.equal(card.status, "unavailable");
      assert.equal(card.text, "No Work IQ record references this renewal ID.");
      assert.ok(!renewal.sources.some((source) => source.includes("work-iq")));
      for (const topic of TOPICS) {
        assert.ok(exports.answerQuestion(renewal, topic).includes("No Work IQ record references this renewal ID"));
      }
      return;
    }
    assert.equal(card.status, "synthetic");
    assert.match(card.text, /Not a live retrieval\.$/);
    assert.ok(card.text.includes(renewal.id));
    for (const reference of expected) {
      assert.ok(card.text.includes(reference));
      assert.ok(renewal.sources.some((source) => source.endsWith(`#${reference}`)));
    }
    // The local evidence has to reach the answers the dashboard actually serves.
    const answer = exports.answerQuestion(renewal, "call plan");
    for (const reference of expected) assert.ok(answer.includes(reference));
    assert.ok(answer.includes("not live retrievals"));
  });
}

for (const renewal of exports.renewals) {
  test(`${renewal.id}: deterministic, grounded answers and an explicit scope fallback`, () => {
    for (const topic of TOPICS) {
      const answer = exports.answerQuestion(renewal, topic);
      assert.equal(answer, exports.answerQuestion(renewal.id, topic));
      assert.ok(answer.includes(renewal.id));
      assert.ok(answer.includes(exports.snapshotAsOf));
      assert.ok(answer.includes("Sources:"));
      assert.ok(!answer.includes("undefined"));
      assert.ok(!answer.includes("NaN"));
      // One synthetic disclosure per answer, not one per line.
      assert.equal(answer.match(/SYNTHETIC/g).length, 1);
    }
    for (const unsupported of [
      "latest mortgage rates", "what will this customer do", "email the customer",
      "compare us to the credit union", "risks and a discount recommendation",
    ]) {
      const answer = exports.answerQuestion(renewal, unsupported);
      assert.ok(answer.includes("Supported topics:"));
      assert.ok(!answer.includes("Attrition risk\n"));
    }
    // Caller-supplied figures can never override the snapshot.
    const spoofed = { ...renewal, balanceCad: 99999999, riskBand: "Low" };
    assert.equal(exports.answerQuestion(spoofed, "call plan"), exports.answerQuestion(renewal.id, "call plan"));
  });
}

test("answers are sectioned and different renewals give genuinely different answers", () => {
  const plans = new Set();
  for (const renewal of exports.renewals) {
    const answer = exports.buildAnswer(renewal, "call plan");
    assert.equal(answer.renewal, renewal.id);
    assert.equal(answer.supported, true);
    // Joined because arrays built inside the vm sandbox are a different realm.
    assert.equal(answer.blocks.map((block) => block.title).join(" | "), [
      "Why this file", "Position", "Attrition risk", "Retention offers and approvals",
      "Maturity, rate and payment", "Evidence", "Basis and caveats", "Sources",
    ].join(" | "));
    const evidence = answer.blocks.find((block) => block.title === "Evidence");
    assert.equal(evidence.evidence.length, 4);
    assert.match(evidence.note, /not live retrievals/);
    // The per-line repetition is stripped from the rendered evidence.
    for (const item of evidence.evidence) assert.ok(!item.text.includes("Not a live retrieval"));
    for (const title of ["Basis and caveats", "Sources"]) {
      assert.equal(answer.blocks.find((block) => block.title === title).collapsible, true);
    }
    assert.ok(answer.blocks.find((block) => block.title === "Position").figures.length >= 8);
    assert.match(answer.footnote, /SYNTHETIC DEMO ONLY/);
    plans.add(exports.answerQuestion(renewal, "call plan"));
  }
  assert.equal(plans.size, 50);
  assert.equal(new Set(exports.renewals.map((r) => exports.answerQuestion(r, "offers"))).size > 20, true);
});

test("unsupported and unknown subjects fall back to scope, never invented analysis", () => {
  const unsupported = exports.buildAnswer(exports.renewals[0], "what should I say on the call");
  assert.equal(unsupported.supported, false);
  assert.equal(unsupported.blocks.map((block) => block.title).join(" | "), "Supported questions | Sources");
  const unknown = exports.buildAnswer("RNW-9999", "call plan");
  assert.equal(unknown.supported, false);
  assert.equal(unknown.renewal, "Renewal not in this snapshot");
  assert.ok(exports.answerQuestion("RNW-9999", "call plan").includes("Supported topics:"));
});

test("offer eligibility is segment-based only and approval levels are always stated", () => {
  const catalogue = new Map(exports.offerCatalogue.map((offer) => [offer.id, offer]));
  for (const renewal of exports.renewals) {
    for (const offer of renewal.eligibleOffers) {
      assert.ok(catalogue.get(offer.id).segments.includes(renewal.segment));
      assert.ok(offer.approvalLevel.length > 0);
    }
    const eligibleIds = renewal.eligibleOffers.map((offer) => offer.id).join(",");
    const expected = exports.offerCatalogue
      .filter((offer) => offer.segments.includes(renewal.segment))
      .map((offer) => offer.id).join(",");
    assert.equal(eligibleIds, expected);
    const answer = exports.answerQuestion(renewal, "offers");
    assert.ok(answer.includes(renewal.recommendedOffer.approvalLevel));
    assert.ok(answer.includes("cannot be verified from this snapshot"));
  }
});

test("money and percent formatting never renders a missing value as zero", () => {
  assert.equal(exports.money(null), "Unavailable");
  assert.equal(exports.percent(null), "Unavailable");
  assert.equal(exports.money(0), "CAD 0");
  assert.equal(exports.percent(0), "0.0%");
});

/* ------------------------------------------------- flyer draft and cross-sell --- */

const CATALOGUE = new Map(exports.productCatalogue.map((product) => [product.id, product]));
const OFFERS = new Map(exports.offerCatalogue.map((offer) => [offer.id, offer]));
// Conditions these offers turn on are not held anywhere in this repository, so
// they may be shown with the missing evidence named but never drafted.
const NEVER_DRAFTED = ["OFR-01", "OFR-05", "OFR-07", "OFR-08"];

test("authored holdings reconcile with products_held for all fifty customers", () => {
  assert.ok(exports.productCatalogue.length > 0);
  for (const renewal of exports.renewals) {
    const ids = renewal.holdings.map((held) => held.id);
    // The reconciliation the generator enforces, asserted again on the output.
    assert.equal(ids.length, renewal.productsHeld, renewal.id);
    assert.equal(new Set(ids).size, ids.length, renewal.id);
    assert.equal(ids[0], "PRD-MTG", renewal.id);
    for (const held of renewal.holdings) {
      const product = CATALOGUE.get(held.id);
      assert.ok(product, `${renewal.id} holds an uncatalogued ${held.id}`);
      assert.equal(product.holdable, true);
      assert.equal(product.name, held.name);
      if (product.segments.length) assert.ok(product.segments.includes(renewal.segment));
    }
  }
  assert.match(exports.holdingsBasis, /only how many products/);
  assert.match(exports.holdingsBasis, /Which products they are is invented/);
});

test("cross-sell never recommends a product the customer already holds", () => {
  for (const renewal of exports.renewals) {
    const held = new Set(renewal.holdings.map((item) => item.id));
    assert.ok(renewal.crossSell.length > 0 && renewal.crossSell.length <= 3, renewal.id);
    assert.equal(
      renewal.crossSell.map((item) => item.rank).join(","),
      renewal.crossSell.map((_, index) => index + 1).join(","),
    );
    for (const item of renewal.crossSell) {
      assert.ok(!held.has(item.id), `${renewal.id} cross-sells held ${item.id}`);
      const product = CATALOGUE.get(item.id);
      assert.ok(product && product.holdable);
      if (product.segments.length) assert.ok(product.segments.includes(renewal.segment));
      assert.ok(item.signals.length > 0, `${renewal.id} ${item.id} has no stated signal`);
    }
    // The relief conversation is never a holding and never a cross-sell line.
    assert.ok(!renewal.crossSell.some((item) => item.id === "PRD-REL"));
    assert.ok(!held.has("PRD-REL"));
    if (renewal.reliefReview) {
      assert.equal(renewal.reliefReview.id, "PRD-REL");
      assert.match(renewal.reliefReview.signals.join(" "), /RP-006/);
    }
  }
  assert.match(exports.crossSellBasis, /credit decision/);
  assert.match(exports.crossSellBasis, /propensity indicators/);
});

test("the drafted offer is segment-eligible, condition-supported and approval-stamped", () => {
  for (const renewal of exports.renewals) {
    const draft = flyer.buildFlyerDraft(renewal);
    assert.ok(draft, renewal.id);
    assert.equal(
      draft.assessments.map((item) => item.id).join(","),
      renewal.eligibleOffers.map((offer) => offer.id).join(","),
    );
    for (const item of draft.assessments) {
      assert.ok(OFFERS.get(item.id).segments.includes(renewal.segment));
      assert.ok(item.reason.length > 20, `${renewal.id} ${item.id} has no stated reason`);
      assert.ok(item.approvalLevel.length > 0);
      assert.equal(item.approvalLevel, OFFERS.get(item.id).approvalLevel);
    }
    const drafted = draft.assessments.filter((item) => item.selected);
    // RP-003: discounts do not stack, so exactly one offer is ever drafted.
    assert.ok(drafted.length <= 1, renewal.id);
    if (!draft.offer) {
      assert.equal(drafted.length, 0);
      assert.equal(draft.spec, null);
      assert.equal(draft.effectiveRatePct, null);
      continue;
    }
    assert.equal(drafted.length, 1);
    assert.equal(drafted[0].id, draft.offer.id);
    assert.equal(drafted[0].status, "supported");
    assert.ok(OFFERS.get(draft.offer.id).segments.includes(renewal.segment));
    assert.equal(draft.approvalLevel, OFFERS.get(draft.offer.id).approvalLevel);
    assert.ok(!NEVER_DRAFTED.includes(draft.offer.id), `${renewal.id} drafted ${draft.offer.id}`);
    assert.equal(draft.spec.offers.length, 1);
    assert.equal(draft.spec.offers[0].code, draft.offer.id);
    assert.equal(draft.spec.approval, draft.offer.approvalLevel);
    // The alternative is a swap, never a second discount on the same flyer.
    if (draft.spec.bundle) {
      assert.notEqual(draft.spec.bundle.code, draft.offer.id);
      assert.ok(["OFR-02", "OFR-05"].includes(draft.spec.bundle.code));
      assert.ok(OFFERS.get(draft.spec.bundle.code).segments.includes(renewal.segment));
      assert.match(draft.alternativeNote, /do not stack/);
    }
  }
});

test("offers whose evidence this snapshot does not hold are named, never drafted", () => {
  const seen = new Set();
  for (const renewal of exports.renewals) {
    for (const item of flyer.buildFlyerDraft(renewal).assessments) {
      if (NEVER_DRAFTED.includes(item.id)) {
        assert.notEqual(item.status, "supported", `${renewal.id} ${item.id}`);
        assert.equal(item.selected, false);
        seen.add(item.id);
      }
    }
  }
  assert.equal([...seen].sort().join(","), NEVER_DRAFTED.join(","));
});

test("the effective rate is the offered rate less the offer ceiling, or Unavailable", () => {
  for (const renewal of exports.renewals) {
    const draft = flyer.buildFlyerDraft(renewal);
    assert.equal(draft.offeredRatePct, renewal.offeredRatePct);
    if (!draft.offer || draft.discountBps === 0) {
      // Never rendered as zero: a missing rate is missing.
      assert.equal(draft.effectiveRatePct, null);
      assert.equal(exports.percent(draft.effectiveRatePct, 2), "Unavailable");
      continue;
    }
    assert.equal(draft.discountBps, OFFERS.get(draft.offer.id).maxDiscountBps);
    assert.equal(
      draft.effectiveRatePct,
      Math.round((renewal.offeredRatePct - draft.discountBps / 100) * 100) / 100,
    );
    assert.ok(draft.effectiveRatePct < renewal.offeredRatePct);
    assert.match(draft.rateLine, /maximum discount available/);
    assert.match(draft.rateLine, /Not a quoted or guaranteed rate/);
    assert.ok(draft.rateLine.includes(`${draft.discountBps} bps`));
    assert.ok(draft.rateLine.includes(draft.approvalLevel));
  }
});

test("a flyer draft is deterministic and cannot be steered by caller-supplied figures", () => {
  for (const renewal of exports.renewals) {
    const transcript = flyer.flyerTranscript(renewal);
    assert.equal(transcript, flyer.flyerTranscript(renewal.id));
    assert.equal(transcript, flyer.flyerTranscript(renewal.customerId));
    const spoofed = { ...renewal, offeredRatePct: 0.01, segment: "High Net Worth", productsHeld: 9 };
    assert.equal(flyer.flyerTranscript(spoofed), transcript);
    assert.ok(!transcript.includes("undefined"));
    assert.ok(!transcript.includes("NaN"));
  }
  assert.equal(flyer.buildFlyerDraft("RNW-9999"), null);
  assert.match(flyer.flyerTranscript("RNW-9999"), /Renewal not in this snapshot/);
});

test("a flyer draft states the synthetic disclosure once and never claims a market rate", () => {
  for (const renewal of exports.renewals) {
    const transcript = flyer.flyerTranscript(renewal);
    // One disclosure per artifact, not one per line.
    assert.equal(transcript.match(/SYNTHETIC/g).length, 1);
    assert.match(transcript, /Live market rates are unavailable in this local scope/);
    assert.match(transcript, /not a quoted competitor rate/);
    assert.match(transcript, /RP-002/);
    assert.match(transcript, /RP-003/);
    assert.match(transcript, /RP-007/);
    assert.ok(transcript.includes(`${renewal.competitorGapBps} bps`));
    // Web IQ contributes nothing to a flyer. It is named only to say the records
    // do not exist, and never as a source of anything on the draft.
    assert.match(transcript, /holds no Web IQ records/);
    assert.equal(transcript.match(/Web IQ/g).length, 1);
    assert.equal(iq(renewal, "Web IQ").status, "unavailable");
    // Work IQ references belong only to the five renewals that carry them, and a
    // flyer draft does not quote them at all.
    assert.ok(!/\bEM-\d{3}\b/.test(transcript));
    assert.ok(!/\bTC-\d{3}\b/.test(transcript));
  }
});

test("the flyer draft reuses the shared RP-003 rules rather than a second engine", () => {
  const catalogue = flyer.flyerCatalogue;
  assert.equal(catalogue.length, exports.offerCatalogue.length);
  for (const offer of catalogue) {
    const source = OFFERS.get(offer.code);
    assert.equal(offer.max_bps, source.maxDiscountBps);
    assert.equal(offer.max_cash, source.cashbackCad);
    assert.equal(offer.approver, source.approvalLevel);
    assert.equal(offer.segments.join("|"), source.segments.join("|"));
  }
  // The judgements preserved from the agent-driven flyer: a rate discount wins
  // before cash, and "better" means better on one axis and worse on none.
  const a = { code: "A", name: "A", max_bps: 20, max_cash: 0, segments: [], approver: "x", condition: "" };
  const b = { code: "B", name: "B", max_bps: 10, max_cash: 5000, segments: [], approver: "x", condition: "" };
  assert.equal(policy.richerOf(a, b).code, "A");
  assert.equal(policy.beats(b, a), false);
  assert.equal(policy.beats(a, b), false);
});

test("no 'cached' label survives anywhere the dashboard is rendered or printed", () => {
  // Every string the dashboard can show: the snapshot it renders from, the
  // flattened transcript of every supported and unsupported answer, and every
  // flyer draft transcript and assessment reason.
  const drafts = exports.renewals.map((renewal) => flyer.buildFlyerDraft(renewal));
  const rendered = [
    JSON.stringify(snapshot),
    ...exports.renewals.flatMap((renewal) =>
      [...TOPICS, "latest mortgage rates"].map((topic) => exports.answerQuestion(renewal, topic))),
    exports.answerQuestion("RNW-9999", "call plan"),
    ...exports.renewals.map((renewal) => flyer.flyerTranscript(renewal)),
    flyer.flyerTranscript("RNW-9999"),
    ...drafts.flatMap((draft) => [
      draft.rateLine, draft.marketNote, draft.alternativeNote,
      ...draft.why, ...draft.assessments.map((item) => item.reason),
    ]),
    exports.snapshotDisclaimer,
  ].join("\n");
  assert.equal(rendered.match(/cach(e|ed|ing)/gi), null);
  // Removing the label must not have removed the honesty it sat next to.
  assert.match(rendered, /SYNTHETIC DEMO ONLY/);
  assert.match(rendered, /no API calls, no live retrieval, no external facts/);
  assert.match(rendered, /Live market rates are unavailable/);
  assert.match(rendered, /No Work IQ record references this renewal ID\./);
  for (const renewal of exports.renewals) {
    // Still exactly one synthetic disclosure per answer and per artifact.
    assert.equal(exports.answerQuestion(renewal, "call plan").match(/SYNTHETIC/g).length, 1);
    assert.equal(flyer.flyerTranscript(renewal).match(/SYNTHETIC/g).length, 1);
  }
});
