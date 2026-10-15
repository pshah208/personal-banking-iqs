"""Build the offline renewal dashboard snapshot; --check validates sources and exact output.

Reads only the synthetic files under data/ and writes a typed snapshot consumed by
app/src/web/src/dashboard. Every figure in the snapshot is copied or aggregated
from those files; nothing is invented here and nothing is fetched.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE.parent / "app" / "src" / "web" / "src" / "dashboard" / "snapshot.json"
AS_OF = "2026-08-03"
D = Decimal

DISCLAIMER = (
    "SYNTHETIC DEMO ONLY: CFC Bank is a fictional bank and every customer, "
    "advisor, mortgage, rate, risk score and offer below is invented for this "
    "demonstration. No real customer data is present. Local snapshot scope only: "
    "no API calls, no live retrieval, no external facts."
)
UNITS = (
    "Balances, property values, revenue and lifetime value are CAD dollars (not "
    "thousands or millions). Rates are annual percentages; rate gaps and discounts "
    "are basis points (100 bps = 1.00%). Likelihood, LTV and payment shock are "
    "percentages, not fractions."
)
CLOCK = (
    f"All timing is measured from the snapshot date {AS_OF} recorded in the source "
    "rows, never from the current clock. \"This week\" means the top of the derived "
    "call order, not a calendar week."
)
PRIORITY_BASIS = (
    "Call order is derived in this generator from snapshot fields: attrition risk band "
    "(High, then Medium, then Low), then fewest days to maturity, then largest "
    "balance, then renewal ID. It is an ordering aid, not a model output; the only "
    "model output in this data is attrition_risk_score from attrition-renewal-v2.3."
)
PAYMENT_SHOCK_BASIS = (
    "payment_shock_pct is reproduced from mortgage_renewals.csv. Its basis is not "
    "documented in the source and a standard annuity recomputation from balance, "
    "current rate, offered rate and remaining amortization does not reproduce it, so "
    "it is shown as a source-provided figure and is not used in any derived number."
)
OFFER_BASIS = (
    "Offer eligibility shown here is segment membership from retention_offers.csv "
    "only. The conditions in each offer's notes (products held and account types, "
    "investable assets, documented competitor evidence, TDS/GDS re-test) cannot be "
    "verified from this snapshot and are not treated as met."
)
HOLDINGS_BASIS = (
    "customers.csv records only how many products each customer holds "
    "(products_held), never which ones. The product catalogue and the per-customer "
    "holdings list on this page are additional synthetic data authored by this "
    "generator: derived deterministically from customer_id, segment, tenure, "
    "origination channel, digital engagement, province and the mortgage row, then "
    "reconciled so that each list is exactly as long as that customer's recorded "
    "products_held. Which products they are is invented; only the count is sourced."
)
CROSS_SELL_BASIS = (
    "Next-best-product entries are propensity indicators for an advisor "
    "conversation, drawn from products the customer is not recorded as holding and "
    "ordered by a fixed weighting of the snapshot signals listed against each one. "
    "The weighting is an ordering aid authored in this generator, not a model "
    "output. Nothing here is pre-qualification, an approved offer, a guarantee of "
    "eligibility or a credit decision; affordability, suitability and adjudication "
    "are unchanged and still sit with the advisor and the relevant credit policy."
)
MARKET_RATE_BASIS = (
    "Live market rates are unavailable in this local scope: this repository holds "
    "no Web IQ records, no posted-rate feed and no bond yields, and none were "
    "retrieved or inferred. competitor_rate_gap_bps is a scored field from "
    "renewal_risk_scores.csv as of the snapshot date - a Fabric-sourced synthetic "
    "gap, not a quoted competitor rate and not the documented written competitor "
    "offer RP-002 requires before discretionary pricing is granted. Where that "
    "evidence is absent it is named as absent rather than assumed."
)
FLYER_BASIS = (
    "A flyer built here is a reviewable draft for a human, not an approved price. "
    "The rate shown is the offered renewal rate from mortgage_renewals.csv less the "
    "full max_discount_bps ceiling of the selected offer from retention_offers.csv - "
    "the maximum discount available under that offer, subject to the approval level "
    "named on it (RP-003), and under RP-002 to documented evidence where the offer "
    "requires it. It is not a quoted, granted or guaranteed rate. RP-003 discounts "
    "do not stack, so exactly one offer is presented and any alternative is shown as "
    "a swap, never an addition. RP-007 applies: no deadline pressure beyond the real "
    "maturity date, and every condition is disclosed with the offer."
)

FABRIC_TEXT = (
    "Local CSV snapshot of customers, mortgage_renewals, renewal_risk_scores, "
    "retention_offers and branch_performance. No Fabric service was queried."
)
WEB_TEXT = (
    "This repository holds no Web IQ records. No competitor rates, market news, "
    "bond yields or external facts were retrieved or inferred."
)
WORK_NONE = "No Work IQ record references this renewal ID."
PERIODS = {"Monthly": 12, "Semi-monthly": 24, "Bi-weekly": 26, "Accelerated Bi-weekly": 26,
           "Weekly": 52, "Accelerated Weekly": 52}
ID_PATTERN = re.compile(r"RNW-\d+")
# Renewals that genuinely carry Work IQ evidence, verified below against the
# records themselves. Attribution is by an explicit renewal ID written in the
# record, never by a name or a topic that merely looks related.
EXPECTED_WORK = {
    "RNW-5008": ["EM-017", "TC-304"],
    "RNW-5014": ["EM-008", "EM-009", "TC-301"],
    "RNW-5021": ["EM-017", "TC-304"],
    "RNW-5033": ["EM-011", "TC-302"],
    "RNW-5044": ["EM-017", "TC-304"],
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def number(value: Decimal, places: str = "0.01") -> float:
    return float(value.quantize(D(places), rounding=ROUND_HALF_UP))


def read_table(name: str) -> list[dict]:
    with (HERE / "fabric-iq" / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def money(amount: Decimal | int) -> str:
    return f"CAD {int(amount):,}"


def maturity_window(days: int) -> str:
    return ("Within 30 days" if days <= 30 else "31-60 days" if days <= 60
            else "61-90 days" if days <= 90 else "91-180 days" if days <= 180
            else "Beyond 180 days")


def annuity_payment(balance: Decimal, rate: Decimal, years: int, periods: int) -> Decimal | None:
    """Level payment for a fully amortizing loan; None when inputs cannot support it."""
    if years <= 0 or rate <= 0:
        return None
    i = rate / 100 / periods
    n = years * periods
    factor = (1 + i) ** n
    return balance * i * factor / (factor - 1)


def work_index() -> dict[str, list[tuple[str, str]]]:
    """Map renewal ID -> local Work IQ records that explicitly name it."""
    emails = json.loads((HERE / "work-iq" / "emails.json").read_text(encoding="utf-8"))
    teams = json.loads((HERE / "work-iq" / "teams_messages.json").read_text(encoding="utf-8"))
    require(emails["as_of"] == AS_OF, "Stale work-iq/emails.json")
    found: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for item in emails["emails"]:
        for renewal in sorted(set(ID_PATTERN.findall(json.dumps(item, ensure_ascii=False)))):
            found[renewal].append((item["id"], f"email \"{item['subject']}\""))
    for channel in teams["channels"]:
        for conversation in channel["conversations"]:
            blob = json.dumps(conversation, ensure_ascii=False)
            for renewal in sorted(set(ID_PATTERN.findall(blob))):
                found[renewal].append((
                    conversation["id"],
                    f"Teams thread \"{conversation['subject']}\" in {channel['displayName']}",
                ))
    resolved = {key: sorted(value) for key, value in found.items()}
    require({k: [i for i, _ in v] for k, v in resolved.items()} == EXPECTED_WORK,
            f"Work IQ attribution changed: {sorted(resolved)}")
    return resolved


def policy_index(customer_names: list[str]) -> dict[str, dict]:
    documents = json.loads((HERE / "foundry-iq" / "renewal_policies.json").read_text(encoding="utf-8"))
    policies = {}
    for document in documents:
        blob = json.dumps(document, ensure_ascii=False)
        # A firm-wide standard must never be presented as a customer-specific file.
        require(not ID_PATTERN.search(blob), f"Policy {document['id']} names a renewal")
        require(not re.search(r"CUST-\d+", blob), f"Policy {document['id']} names a customer")
        require(not any(name in blob for name in customer_names),
                f"Policy {document['id']} names a synthetic customer")
        policies[document["id"]] = document
    return policies


# ---------------------------------------------------------------- products ---
# Synthetic product catalogue. customers.csv carries only a count of products
# held, so a catalogue and a per-customer holdings list are authored here rather
# than silently invented in the UI. `holdable` products are the ones the count
# can be made of; the relief review is an advisory conversation, never a holding,
# so it can be surfaced as a next-best action without corrupting the reconciliation.
PRODUCT_CATALOGUE = [
    {"id": "PRD-MTG", "name": "Mortgage", "category": "Lending", "holdable": True,
     "segments": [], "summary": "The maturing mortgage itself, from mortgage_renewals.csv."},
    {"id": "PRD-CHQ", "name": "Everyday Chequing Account", "category": "Day-to-day banking",
     "holdable": True, "segments": [],
     "summary": "Core operating account. Named in the OFR-02 condition as part of a three-product relationship."},
    {"id": "PRD-SAV", "name": "High-Interest Savings Account", "category": "Day-to-day banking",
     "holdable": True, "segments": [], "summary": "Short-horizon savings held alongside the operating account."},
    {"id": "PRD-CRD", "name": "CFC Bank Credit Card", "category": "Day-to-day banking",
     "holdable": True, "segments": [], "summary": "Everyday spend and rewards card."},
    {"id": "PRD-TFSA", "name": "Tax-Free Savings Account", "category": "Registered investing",
     "holdable": True, "segments": [], "summary": "Registered plan for tax-sheltered growth."},
    {"id": "PRD-RSP", "name": "Retirement Savings Plan", "category": "Registered investing",
     "holdable": True, "segments": [], "summary": "Registered retirement plan."},
    {"id": "PRD-INV", "name": "Managed Investment Portfolio", "category": "Investing",
     "holdable": True, "segments": [], "summary": "Non-registered managed portfolio."},
    {"id": "PRD-WLT", "name": "Private Wealth Advisory Relationship", "category": "Wealth",
     "holdable": True, "segments": ["High Net Worth"],
     "summary": "Dedicated wealth advisory relationship. Named in the OFR-05 condition."},
    {"id": "PRD-HEL", "name": "Home Equity Line of Credit", "category": "Lending",
     "holdable": True, "segments": [], "summary": "Revolving credit secured against the property."},
    {"id": "PRD-INS", "name": "Creditor and Home Insurance", "category": "Protection",
     "holdable": True, "segments": [], "summary": "Protection cover attached to the mortgage and property."},
    {"id": "PRD-BIZ", "name": "Small Business Banking Package", "category": "Business banking",
     "holdable": True, "segments": ["Self-Employed"],
     "summary": "Operating account, merchant services and business lending for an owner-operator."},
    {"id": "PRD-NEW", "name": "Newcomer Banking Package", "category": "Day-to-day banking",
     "holdable": True, "segments": ["New to Canada"],
     "summary": "Bundled account, card and credit-building package for recent arrivals."},
    {"id": "PRD-REL", "name": "Amortization and Payment Relief Review", "category": "Advisory conversation",
     "holdable": False, "segments": [],
     "summary": "A structured affordability conversation under RP-006, not a product sale. Any amortization change needs Credit Risk approval and a TDS/GDS re-test."},
]
PRODUCTS_BY_ID = {product["id"]: product for product in PRODUCT_CATALOGUE}


def seeded(*parts: str) -> int:
    """Stable small integer from the given key parts; no randomness, no clock."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def product_allowed(product: dict, segment: str) -> bool:
    return not product["segments"] or segment in product["segments"]


def holdings_for(customer: dict, row: dict, ltv: float) -> list[str]:
    """Authored holdings for one customer, exactly as long as products_held.

    Ranked by a fixed affinity weighting over snapshot customer and mortgage fields
    plus a deterministic per-customer tie-break, so the same CSV always produces
    the same list. The mortgage is always the first holding: every customer in
    this book has one, which is what makes a count of one reconcile.
    """
    segment = customer["segment"]
    tenure = int(customer["tenure_years"])
    digital = int(customer["digital_engagement_score"])
    primary = customer["primary_relationship_flag"] == "Y"
    channel = customer["origination_channel"]

    def affinity(product: dict) -> int:
        pid, score = product["id"], 0
        if pid == "PRD-CHQ":
            score = 60 + (20 if primary else 0) + (10 if channel == "Branch" else 0)
        elif pid == "PRD-SAV":
            score = 40 + (10 if tenure >= 10 else 0)
        elif pid == "PRD-CRD":
            score = 45 + (10 if digital >= 50 else 0)
        elif pid == "PRD-TFSA":
            score = 30 + (15 if segment in ("Mass Affluent", "High Net Worth") else 0) + (10 if tenure >= 8 else 0)
        elif pid == "PRD-RSP":
            score = 25 + (15 if segment in ("Mass Affluent", "High Net Worth") else 0) + (10 if tenure >= 12 else 0)
        elif pid == "PRD-INV":
            score = 15 + (25 if segment == "High Net Worth" else 10 if segment == "Mass Affluent" else 0)
        elif pid == "PRD-WLT":
            score = 30 + (10 if tenure >= 10 else 0)
        elif pid == "PRD-HEL":
            score = 15 + (15 if ltv <= 65 else 0)
        elif pid == "PRD-INS":
            score = 20 + (10 if row["insured_flag"] == "Y" else 0)
        elif pid == "PRD-BIZ":
            score = 50 + (10 if channel != "Digital" else 0)
        elif pid == "PRD-NEW":
            score = 55 + (10 if tenure <= 3 else 0)
        # Deterministic tie-break so two customers with identical profiles still
        # differ, without ever reaching for a random source.
        return score * 100 + seeded(customer["customer_id"], pid) % 100

    count = int(customer["products_held"])
    pool = [product for product in PRODUCT_CATALOGUE
            if product["holdable"] and product["id"] != "PRD-MTG"
            and product_allowed(product, segment)]
    ranked = sorted(pool, key=lambda product: (-affinity(product), product["id"]))
    held = ["PRD-MTG"] + [product["id"] for product in ranked[:count - 1]]
    # The whole point of authoring this list: it must not contradict the CSV.
    require(len(held) == count,
            f"Authored holdings for {customer['customer_id']} total {len(held)} "
            f"against products_held {count}")
    require(len(set(held)) == len(held), f"Duplicate holding for {customer['customer_id']}")
    return held


def cross_sell_for(customer: dict, row: dict, score_row: dict, held: list[str],
                   ltv: float) -> list[dict]:
    """Next-best products the customer is not recorded as holding, with the signals."""
    segment = customer["segment"]
    tenure = int(customer["tenure_years"])
    digital = int(customer["digital_engagement_score"])
    nps = int(customer["nps_score"])
    primary = customer["primary_relationship_flag"] == "Y"
    ltv_value = D(str(ltv))
    equity = int(D(row["property_value_cad"]) - D(row["mortgage_balance_cad"]))
    lifetime = int(score_row["five_year_lifetime_value_cad"])
    deepening = nps >= 50 and tenure >= 10 and primary

    ranked: list[tuple[int, dict]] = []
    for product in PRODUCT_CATALOGUE:
        pid = product["id"]
        if (pid in held or pid == "PRD-MTG" or not product["holdable"]
                or not product_allowed(product, segment)):
            continue
        signals: list[str] = []
        score = 0
        if pid == "PRD-CHQ":
            score = 70
            signals.append("No chequing account in the authored holdings list.")
            if not primary:
                score += 20
                signals.append("primary_relationship_flag is N: the day-to-day relationship sits elsewhere.")
            if segment in ("Mass Affluent", "High Net Worth", "Self-Employed"):
                score += 25
                signals.append(
                    "OFR-02 Relationship Bundle Discount names a chequing account inside a "
                    "three-product relationship, and this segment is eligible for OFR-02.")
        elif pid == "PRD-NEW":
            score = 85 if tenure <= 5 else 45
            signals.append(f"Segment New to Canada with {tenure} years tenure recorded.")
        elif pid == "PRD-BIZ":
            score = 80
            signals.append(f"Segment Self-Employed, {customer['origination_channel']} originated.")
        elif pid == "PRD-WLT":
            score = 80
            signals.append(
                f"Segment High Net Worth; five-year lifetime value {money(D(lifetime))} recorded. "
                "OFR-05 names a wealth relationship with CAD 1M or more investable assets.")
        elif pid == "PRD-INV":
            score = 45 + (20 if lifetime >= 40000 else 0) + (15 if segment in ("Mass Affluent", "High Net Worth") else 0)
            signals.append(f"Five-year lifetime value {money(D(lifetime))}; segment {segment}.")
        elif pid == "PRD-TFSA":
            score = 45 + (10 if tenure >= 8 else 0)
            signals.append(f"{tenure} years tenure with no registered savings plan in the holdings list.")
        elif pid == "PRD-RSP":
            score = 40 + (10 if tenure >= 12 else 0)
            signals.append(f"{tenure} years tenure with no retirement plan in the holdings list.")
        elif pid == "PRD-CRD":
            score = 40 + (25 if digital >= 60 else 0)
            signals.append(f"Digital engagement score {digital} of 100.")
        elif pid == "PRD-SAV":
            score = 35 + (15 if digital >= 60 else 0)
            signals.append(f"Digital engagement score {digital} of 100; no savings account held.")
        elif pid == "PRD-HEL":
            if ltv_value >= 80:
                continue
            score = 30 + (30 if ltv_value <= 65 else 0)
            signals.append(f"LTV {ltv}% leaves {money(D(equity))} of recorded equity in the property.")
        elif pid == "PRD-INS":
            score = 40 + (20 if ltv_value >= 75 else 0)
            signals.append(
                f"LTV {ltv}%; mortgage recorded as "
                f"{'insured' if row['insured_flag'] == 'Y' else 'uninsured'} in the source row.")
        if not score:
            continue
        if deepening:
            score += 10
            signals.append(
                f"Relationship depth: {tenure} years tenure, NPS {nps}, primary relationship with the bank.")
        ranked.append((score * 100 + seeded(customer["customer_id"], "xs", pid) % 100, product | {"signals": signals}))

    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [{
        "id": product["id"], "name": product["name"], "category": product["category"],
        "summary": product["summary"], "signals": product["signals"], "rank": index + 1,
    } for index, (_, product) in enumerate(ranked[:3])]


def relief_for(row: dict, ltv: float, increase: int) -> dict | None:
    """The RP-006 relief conversation, kept out of cross-sell because it is not a sale."""
    shock = float(row["payment_shock_pct"])
    if D(str(ltv)) < 80 and increase < 100 and shock < 15:
        return None
    product = PRODUCTS_BY_ID["PRD-REL"]
    return {
        "id": product["id"], "name": product["name"], "category": product["category"],
        "summary": product["summary"],
        "signals": [
            f"Renewal rate moves {row['current_rate_pct']}% to {row['offered_renewal_rate_pct']}% "
            f"(+{increase} bps), recorded payment shock {shock}%, LTV {ltv}%.",
            "RP-006 governs amortization relief: Credit Risk approval and a TDS/GDS re-test. "
            "It is an affordability conversation to offer, never a product to promote, and "
            "nothing here pre-qualifies this customer for it.",
        ],
    }



def choose_policy(offer: dict, band: str, province: str, gap: int) -> str:
    """Deterministic firm-wide standard for the situation, not a customer document."""
    if offer["required_approval_level"] in ("Pricing Committee", "Regional Director"):
        return "RP-002"
    if offer["required_approval_level"] == "Credit Risk":
        return "RP-006"
    if band == "High":
        return "RP-009"
    if province == "QC" and gap > 0:
        return "RP-008"
    return "RP-003"


def build_snapshot() -> dict:
    customers = {row["customer_id"]: row for row in read_table("customers")}
    renewals = read_table("mortgage_renewals")
    scores = {row["renewal_id"]: row for row in read_table("renewal_risk_scores")}
    offers = {row["offer_id"]: row for row in read_table("retention_offers")}
    branches = read_table("branch_performance")
    require(len(customers) == 50 and len(renewals) == 50 and len(scores) == 50,
            "Expected fifty customers, renewals and risk scores")
    require(len({row["renewal_id"] for row in renewals}) == 50, "Duplicate renewal rows")
    require({row["as_of_date"] for row in renewals} == {AS_OF}, "Mixed renewal snapshot dates")
    require({row["scored_on"] for row in scores.values()} == {AS_OF}, "Mixed risk scoring dates")
    require({row["as_of_date"] for row in branches} == {AS_OF}, "Mixed branch snapshot dates")

    branch_names = {row["branch_id"]: row["branch_name"] for row in branches}
    require(all(customer["branch_name"] == branch_names[customer["branch_id"]]
                for customer in customers.values()), "Branch name disagreement")
    names = sorted({row["full_name"] for row in customers.values()})
    work = work_index()
    policies = policy_index(names)
    require(set(EXPECTED_WORK) <= {row["renewal_id"] for row in renewals},
            "Work IQ references a renewal that is not in the book")

    ordered = sorted(renewals, key=lambda row: (
        {"High": 0, "Medium": 1, "Low": 2}[scores[row["renewal_id"]]["attrition_risk_band"]],
        int(row["days_to_maturity"]),
        -int(row["mortgage_balance_cad"]),
        row["renewal_id"],
    ))
    rank_by_id = {row["renewal_id"]: index + 1 for index, row in enumerate(ordered)}

    counted: dict[str, Counter] = defaultdict(Counter)
    shock_gaps: list[tuple[str, float, float]] = []
    records = []
    for row in sorted(renewals, key=lambda item: item["renewal_id"]):
        rid = row["renewal_id"]
        customer = customers[row["customer_id"]]
        score = scores[rid]
        require(customer["segment"] == score["segment"], f"Segment disagreement for {rid}")
        require(customer["branch_id"] == row["branch_id"], f"Branch disagreement for {rid}")
        require(customer["primary_advisor_id"] == row["advisor_id"], f"Advisor disagreement for {rid}")
        balance, value = D(row["mortgage_balance_cad"]), D(row["property_value_cad"])
        require(balance > 0 and value > 0, f"Invalid balance or property value for {rid}")
        ltv = number(balance / value * 100, "0.1")
        require(abs(D(str(ltv)) - D(row["ltv_pct"])) <= D("0.1"), f"LTV does not reconcile for {rid}")
        days = int(row["days_to_maturity"])
        elapsed = (date.fromisoformat(row["maturity_date"]) - date.fromisoformat(AS_OF)).days
        require(elapsed == days, f"days_to_maturity does not match maturity_date for {rid}")
        current, offered = D(row["current_rate_pct"]), D(row["offered_renewal_rate_pct"])
        increase = int((offered - current) * 100)
        periods = PERIODS[row["payment_frequency"]]
        years = int(row["amortization_remaining_years"])
        before = annuity_payment(balance, current, years, periods)
        after = annuity_payment(balance, offered, years, periods)
        recomputed = number((after / before - 1) * 100, "0.1") if before and after else None
        recorded = float(row["payment_shock_pct"])
        if recomputed is not None and abs(recomputed - recorded) > 0.5:
            shock_gaps.append((rid, recorded, recomputed))

        branch = row["branch_id"]
        counted[branch]["renewals"] += 1
        counted[branch]["balance"] += int(balance)
        counted[branch]["revenue"] += int(score["annual_revenue_exposure_cad"])
        band = score["attrition_risk_band"]
        require(band in ("High", "Medium", "Low"), f"Unknown risk band for {rid}")
        if band == "High":
            counted[branch]["high"] += 1

        segment = customer["segment"]
        recommended = offers[score["recommended_offer_id"]]
        eligible = [offer for offer in offers.values()
                    if segment in offer["eligible_segments"].split("|")]
        require(recommended in eligible,
                f"Recommended offer {recommended['offer_id']} is not eligible for {segment}")
        gap = int(score["competitor_rate_gap_bps"])
        shopping = score["rate_shopping_signal"] == "Y"
        complaint = score["service_complaint_last_12m"] == "Y"
        drivers = [part.strip() for part in score["top_risk_drivers"].split(";") if part.strip()]
        held = holdings_for(customer, row, ltv)
        cross_sell = cross_sell_for(customer, row, score, held, ltv)
        relief = relief_for(row, ltv, increase)
        require(not any(item["id"] in held for item in cross_sell),
                f"Cross-sell for {rid} recommends a product already held")
        holdings = [{"id": pid, "name": PRODUCTS_BY_ID[pid]["name"],
                     "category": PRODUCTS_BY_ID[pid]["category"]} for pid in held]

        quality: list[str] = [OFFER_BASIS]
        if recomputed is not None and abs(recomputed - recorded) > 0.5:
            quality.append(
                f"Recorded payment shock {recorded:.1f}% does not match a standard annuity "
                f"recomputation of {recomputed:.1f}% from this row's balance, rates and "
                "remaining amortization. Both figures are shown; neither is corrected."
            )
        if shopping and gap == 0:
            quality.append(
                "A rate-shopping signal is recorded while competitor_rate_gap_bps is 0. "
                "The source does not reconcile these, and no documented competitor offer "
                "exists in this snapshot."
            )
        if gap > 0 and not shopping:
            quality.append(
                f"A {gap} bps competitor rate gap is recorded with no rate-shopping signal; "
                "the gap is a scored field, not evidence that this customer has shopped."
            )
        if recommended["required_approval_level"] != "Advisor":
            quality.append(
                f"The recommended offer needs {recommended['required_approval_level']} "
                "approval. Nothing here constitutes that approval."
            )

        sources = [
            "data/fabric-iq/customers.csv", "data/fabric-iq/mortgage_renewals.csv",
            "data/fabric-iq/renewal_risk_scores.csv", "data/fabric-iq/retention_offers.csv",
            "data/fabric-iq/branch_performance.csv",
        ]
        policy_id = choose_policy(recommended, band, customer["province"], gap)
        policy = policies[policy_id]
        evidence = [
            {"iq": "Fabric IQ", "status": "synthetic", "text": FABRIC_TEXT},
            {"iq": "Work IQ", "status": "unavailable", "text": WORK_NONE},
            {"iq": "Foundry IQ", "status": "synthetic", "text": (
                f"Firm-wide standard {policy_id}: {policy['title']} (effective "
                f"{policy['effective_date']}, owner {policy['owner']}). Applies to this "
                "situation by policy scope; it is a firm-wide standard, not a "
                "customer-specific document. Not a live retrieval."
            )},
            {"iq": "Web IQ", "status": "unavailable", "text": WEB_TEXT},
        ]
        sources.append(f"data/foundry-iq/renewal_policies.json#{policy_id}")
        if rid in work:
            cited = "; ".join(f"{ref} {label}" for ref, label in work[rid])
            evidence[1] = {"iq": "Work IQ", "status": "synthetic", "text": (
                f"Local record(s) naming {rid}: {cited}. Local seed files, not "
                "Microsoft 365. Not a live retrieval."
            )}
            for ref, _ in work[rid]:
                sources.append(
                    f"data/work-iq/{'emails.json' if ref.startswith('EM-') else 'teams_messages.json'}#{ref}"
                )

        records.append({
            "id": rid,
            "customerId": customer["customer_id"],
            "customerName": customer["full_name"],
            "segment": segment,
            "province": customer["province"],
            "branchId": branch,
            "branchName": customer["branch_name"],
            "advisorName": customer["primary_advisor_name"],
            "tenureYears": int(customer["tenure_years"]),
            "productsHeld": int(customer["products_held"]),
            "primaryRelationship": customer["primary_relationship_flag"] == "Y",
            "digitalEngagementScore": int(customer["digital_engagement_score"]),
            "npsScore": int(customer["nps_score"]),
            "originationChannel": customer["origination_channel"],
            "holdings": holdings,
            "crossSell": cross_sell,
            "reliefReview": relief,
            "preferredLanguage": customer["preferred_language"],
            "productType": row["product_type"],
            "termMonths": int(row["term_months"]),
            "balanceCad": int(balance),
            "propertyValueCad": int(value),
            "ltvPct": ltv,
            "insured": row["insured_flag"] == "Y",
            "currentRatePct": float(current),
            "offeredRatePct": float(offered),
            "rateIncreaseBps": increase,
            "paymentFrequency": row["payment_frequency"],
            "amortizationYears": years,
            "originationDate": row["origination_date"],
            "maturityDate": row["maturity_date"],
            "daysToMaturity": days,
            "maturityWindow": maturity_window(days),
            "paymentShockPct": recorded,
            "paymentShockRecomputedPct": recomputed,
            "stage": row["renewal_stage"],
            "riskScore": float(score["attrition_risk_score"]),
            "riskBand": band,
            "renewalLikelihoodPct": float(score["renewal_likelihood_pct"]),
            "riskDrivers": drivers,
            "competitorGapBps": gap,
            "rateShopping": shopping,
            "serviceComplaint": complaint,
            "annualRevenueCad": int(score["annual_revenue_exposure_cad"]),
            "lifetimeValueCad": int(score["five_year_lifetime_value_cad"]),
            "modelVersion": score["model_version"],
            "priorityRank": rank_by_id[rid],
            "recommendedOffer": {
                "id": recommended["offer_id"], "name": recommended["offer_name"],
                "maxDiscountBps": int(recommended["max_discount_bps"]),
                "cashbackCad": int(recommended["cashback_cad"]),
                "approvalLevel": recommended["required_approval_level"],
                "notes": recommended["notes"],
            },
            "eligibleOffers": [{
                "id": offer["offer_id"], "name": offer["offer_name"],
                "maxDiscountBps": int(offer["max_discount_bps"]),
                "cashbackCad": int(offer["cashback_cad"]),
                "approvalLevel": offer["required_approval_level"],
                "notes": offer["notes"],
                "recommended": offer["offer_id"] == recommended["offer_id"],
            } for offer in sorted(eligible, key=lambda item: item["offer_id"])],
            "callReason": (
                f"Derived call order {rank_by_id[rid]} of 50. {band} attrition band "
                f"(score {score['attrition_risk_score']}, renewal likelihood "
                f"{score['renewal_likelihood_pct']}%). Matures {row['maturity_date']}, "
                f"{days} days after the {AS_OF} snapshot ({maturity_window(days).lower()}). "
                f"Balance {money(balance)}; competitor rate gap {gap} bps; renewal stage "
                f"{row['renewal_stage']}. This is a contact-order aid, not an instruction "
                "or an approval."
            ),
            "riskSummary": (
                f"Band {band} from {score['model_version']} scored {score['scored_on']}: "
                f"attrition score {score['attrition_risk_score']}, renewal likelihood "
                f"{score['renewal_likelihood_pct']}%. Recorded drivers: "
                f"{'; '.join(drivers) if drivers else 'none recorded'}. Competitor rate gap "
                f"{gap} bps; rate-shopping signal {'yes' if shopping else 'no'}; service "
                f"complaint in the last 12 months {'yes' if complaint else 'no'}. Annual "
                f"revenue exposure {money(D(score['annual_revenue_exposure_cad']))}; "
                f"five-year lifetime value {money(D(score['five_year_lifetime_value_cad']))}. "
                "A model score is not a decision and not a prediction of this customer's "
                "behaviour."
            ),
            "offerSummary": (
                f"Recommended in the source data: {recommended['offer_id']} "
                f"{recommended['offer_name']} - up to {recommended['max_discount_bps']} bps"
                + (f" plus {money(D(recommended['cashback_cad']))} cashback"
                   if int(recommended["cashback_cad"]) else "")
                + f", {recommended['required_approval_level']} approval required. "
                f"{recommended['notes']} Segment {segment} is listed as eligible for "
                f"{len(eligible)} of {len(offers)} catalogue offers: "
                + "; ".join(
                    f"{offer['offer_id']} {offer['offer_name']} "
                    f"({offer['max_discount_bps']} bps, {offer['required_approval_level']})"
                    for offer in sorted(eligible, key=lambda item: item["offer_id"])
                ) + "."
            ),
            "maturitySummary": (
                f"Matures {row['maturity_date']}, {days} days after the {AS_OF} snapshot "
                f"({maturity_window(days).lower()}). {row['product_type']}, "
                f"{row['term_months']}-month term, {row['payment_frequency']} payments, "
                f"{years} years amortization remaining, "
                f"{'insured' if row['insured_flag'] == 'Y' else 'uninsured'}, LTV {ltv}%. "
                f"Current rate {current}% against an offered renewal rate of {offered}% "
                f"(+{increase} bps). Recorded payment shock {recorded}%"
                + (f"; annuity recomputation from this row gives {recomputed}%."
                   if recomputed is not None else "; not recomputable from this row.")
            ),
            "evidence": evidence,
            "dataQuality": quality,
            "sources": sources,
        })

    branch_records = []
    for branch in sorted(branches, key=lambda row: row["branch_id"]):
        bid = branch["branch_id"]
        tally = counted[bid]
        reconciliation = []
        for label, source_field, key in [
            ("Renewals in the next 180 days", "renewals_next_180d", "renewals"),
            ("Balance maturing", "balance_maturing_cad", "balance"),
            ("High-risk files", "high_risk_count", "high"),
            ("Annual revenue at risk", "annual_revenue_at_risk_cad", "revenue"),
        ]:
            stated, actual = int(branch[source_field]), tally[key]
            if stated != actual:
                reconciliation.append(
                    f"{label}: branch_performance.csv states {stated:,} but the renewal "
                    f"rows for this branch total {actual:,}. The source rows disagree; "
                    "both figures are shown and neither is corrected."
                )
        branch_records.append({
            "id": bid, "name": branch["branch_name"], "province": branch["province"],
            "manager": branch["branch_manager"],
            "renewalsStated": int(branch["renewals_next_180d"]),
            "renewalsCounted": tally["renewals"],
            "balanceMaturingStatedCad": int(branch["balance_maturing_cad"]),
            "balanceMaturingCountedCad": tally["balance"],
            "highRiskStated": int(branch["high_risk_count"]),
            "highRiskCounted": tally["high"],
            "revenueAtRiskStatedCad": int(branch["annual_revenue_at_risk_cad"]),
            "revenueAtRiskCountedCad": tally["revenue"],
            "retentionRatePct": float(branch["retention_rate_last_quarter_pct"]),
            "avgDiscountBps": int(branch["avg_discount_granted_bps"]),
            "advisorCapacity": int(branch["advisor_capacity_files_per_fte"]),
            "maturingWithin30": sum(
                1 for record in records
                if record["branchId"] == bid and record["daysToMaturity"] <= 30
            ),
            "reconciliation": reconciliation,
        })
    require(sum(item["renewalsCounted"] for item in branch_records) == 50,
            "Branch renewal counts do not cover the book exactly once")
    require(sum(item["highRiskCounted"] for item in branch_records)
            == sum(1 for record in records if record["riskBand"] == "High"),
            "High-risk counts do not reconcile")

    shock_note = (
        f"{len(shock_gaps)} of 50 renewals carry a payment_shock_pct that a standard "
        "annuity recomputation does not reproduce (for example "
        + "; ".join(f"{rid} records {recorded:.1f}% against {recomputed:.1f}% recomputed"
                    for rid, recorded, recomputed in shock_gaps[:2])
        + "). Both figures are shown per renewal."
    ) if shock_gaps else "Recorded payment shock reconciles with an annuity recomputation."

    return {
        "snapshotAsOf": AS_OF,
        "units": UNITS,
        "clockBasis": CLOCK,
        "disclaimer": DISCLAIMER,
        "priorityBasis": PRIORITY_BASIS,
        "paymentShockBasis": PAYMENT_SHOCK_BASIS + " " + shock_note,
        "offerBasis": OFFER_BASIS,
        "holdingsBasis": HOLDINGS_BASIS,
        "crossSellBasis": CROSS_SELL_BASIS,
        "marketRateBasis": MARKET_RATE_BASIS,
        "flyerBasis": FLYER_BASIS,
        "productCatalogue": [{
            "id": product["id"], "name": product["name"], "category": product["category"],
            "summary": product["summary"], "holdable": product["holdable"],
            "segments": product["segments"],
        } for product in PRODUCT_CATALOGUE],
        "bandCounts": {band: sum(1 for record in records if record["riskBand"] == band)
                       for band in ("High", "Medium", "Low")},
        "offers": [{
            "id": offer["offer_id"], "name": offer["offer_name"],
            "segments": offer["eligible_segments"].split("|"),
            "maxDiscountBps": int(offer["max_discount_bps"]),
            "cashbackCad": int(offer["cashback_cad"]),
            "approvalLevel": offer["required_approval_level"],
            "notes": offer["notes"],
        } for offer in sorted(offers.values(), key=lambda item: item["offer_id"])],
        "branches": branch_records,
        "renewals": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Read-only: validate the sources and fail on a stale snapshot")
    args = parser.parse_args()
    try:
        snapshot = build_snapshot()
        content = (json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if args.check:
            require(OUTPUT.exists() and OUTPUT.read_bytes() == content,
                    "Missing or stale snapshot.json; run python data\\generate_dashboard_snapshot.py")
            print("PASS: 50 renewals, 3 branches, 8 offers; branch reconciliation, LTV, "
                  "maturity arithmetic, offer eligibility, authored product holdings "
                  "against products_held, cross-sell exclusion of held products, Work IQ "
                  "attribution and firm-wide policy scope verified against the CSV and "
                  "JSON sources.")
        else:
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT.write_bytes(content)
            print(f"Generated {OUTPUT}")
        return 0
    except (ValueError, KeyError, StopIteration, OSError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
