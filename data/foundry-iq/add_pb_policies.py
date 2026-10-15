"""Append the personal-banking policies RP-011..RP-018 to renewal_policies.json.

Synthetic, illustrative policy text for the demo. Regulators and statutes
(FCAC, CASL, PIPEDA, OSFI B-20 / E-23) are cited by name only; the rules
around them are invented. Idempotent: re-running replaces these ids.

    python add_pb_policies.py
"""

from __future__ import annotations

import json
from pathlib import Path

P = Path(__file__).parent / "renewal_policies.json"

NEW = [
    {
        "id": "RP-011", "category": "regulatory_reference", "effective_date": "2026-05-01",
        "owner": "Chief Compliance Officer - Retail",
        "title": "Marketing Consent and Channel Use (CASL)",
        "content": (
            "SCOPE. Applies to every promotional message about a product the client does not already hold, by email, SMS or "
            "outbound phone, including renewal flyers that carry a cross-sell offer.\n\n"
            "RULE 1 - CONSENT BEFORE PROMOTION. A promotional message may be sent only on a channel where the client's marketing "
            "consent is recorded as Granted in the consent register (Fabric table consent_preferences). Withdrawn or Not captured "
            "means no promotional content on that channel. Express consent does not expire; implied consent is valid for two years "
            "from the last transaction and must be re-confirmed after that.\n\n"
            "RULE 2 - SERVICE IS NOT MARKETING. Renewal reminders, payment-change notices and hardship outreach are service "
            "communications and may be sent without marketing consent, provided they contain NO promotional call to action. "
            "Adding a product offer to a service message turns it into a promotional message under Rule 1.\n\n"
            "RULE 3 - IDENTIFICATION AND UNSUBSCRIBE. Every promotional email or SMS must identify the Bank, include a working "
            "unsubscribe mechanism and be honoured within 10 business days.\n\n"
            "CONTROL. The outreach approval step checks the register before a draft is generated. Drafts that fail are blocked, "
            "not edited silently. Canada's Anti-Spam Legislation (CASL) is the statutory anchor."
        ),
    },
    {
        "id": "RP-012", "category": "risk_consideration", "effective_date": "2026-05-01",
        "owner": "Head of Client Care and Fair Treatment",
        "title": "Vulnerable Clients - Support-First Treatment",
        "content": (
            "SCOPE. Applies to any client whose financial-wellness band is Vulnerable (Fabric table financial_wellness) or who "
            "discloses a circumstance such as job loss, illness, separation or bereavement.\n\n"
            "RULE 1 - SUPPORT FIRST. The first contact with a vulnerable client must be a support conversation: affordability, "
            "relief options under RP-006 or RP-014, and signposting to free budgeting help. No product sale, cross-sell or "
            "upgrade may be proposed while the flag is active.\n\n"
            "RULE 2 - SALES SUPPRESSION. Next-best-action engines must suppress every Deepen action for a vulnerable client. "
            "A retention rate offer on the maturing mortgage is permitted because it lowers the client's cost, but it must "
            "not be bundled with a product requirement.\n\n"
            "RULE 3 - LANGUAGE. Communications must be plain, empathetic and non-coercive. Never use urgency or scarcity "
            "framing, and never describe the client as vulnerable in client-facing content.\n\n"
            "RULE 4 - HUMAN APPROVAL. Any outbound draft to a vulnerable client requires Branch Manager approval before "
            "sending. Financial Consumer Agency of Canada (FCAC) fair-treatment expectations are the regulatory anchor."
        ),
    },
    {
        "id": "RP-013", "category": "risk_consideration", "effective_date": "2026-05-01",
        "owner": "VP Real Estate Secured Lending",
        "title": "Affordability and Suitability for Household Recommendations",
        "content": (
            "SCOPE. Applies to every renewal decision and every product recommendation made to a household.\n\n"
            "RULE 1 - AFFORDABILITY GUIDELINE. The Bank's internal guideline is a Gross Debt Service (GDS) ratio of at most 39% "
            "and a Total Debt Service (TDS) ratio of at most 44%, measured on the renewal payment. A renewal above either limit "
            "is not refused - straight renewals do not require re-qualification under OSFI B-20 (see RP-004) - but it must be "
            "routed to an affordability conversation before any product is recommended.\n\n"
            "RULE 2 - NO NEW CREDIT ABOVE THE GUIDELINE. A HELOC, credit-limit increase or new card may not be recommended to a "
            "household whose renewal TDS exceeds 44%.\n\n"
            "RULE 3 - NOT PRE-APPROVED. A recommendation is never an approval. Language such as 'pre-approved' or 'guaranteed' "
            "is prohibited unless adjudication is complete.\n\n"
            "RULE 4 - JOINT BORROWERS. Where a co-borrower exists, both parties must be represented in the conversation and in "
            "any written summary."
        ),
    },
    {
        "id": "RP-014", "category": "approval_requirement", "effective_date": "2026-05-01",
        "owner": "Head of Collections and Client Assistance",
        "title": "Hardship Relief - Payment Deferral, Skip-a-Payment and Escalation",
        "content": (
            "SCOPE. Applies to clients who cannot meet the renewal payment and do not qualify for the RP-006 amortization fast path.\n\n"
            "RULE 1 - OPTIONS. Available relief, in order of preference: (a) amortization extension under RP-006; (b) a payment "
            "deferral of up to three months with interest capitalised; (c) a temporary interest-only period of up to six months; "
            "(d) referral to the Client Assistance specialist team.\n\n"
            "RULE 2 - APPROVAL. Option (b) up to two months: Branch Manager. Option (b) three months or option (c): Regional "
            "Director. Option (d) is a referral, not an approval.\n\n"
            "RULE 3 - TRIGGERS. Relief requires a documented trigger: payroll reduction of 10% or more, a missed payment, two or "
            "more NSF items in three months, or a client-stated hardship event.\n\n"
            "RULE 4 - FOLLOW-UP. Every relief case is reviewed at 30 days. A client in relief remains sales-suppressed under RP-012."
        ),
    },
    {
        "id": "RP-015", "category": "regulatory_reference", "effective_date": "2026-06-01",
        "owner": "Chief Risk Officer - Retail",
        "title": "Rate Scenario Use, Model Limits and Disclosure",
        "content": (
            "SCOPE. Applies to the renewal scenario engine and every decision informed by it.\n\n"
            "RULE 1 - DECISION SUPPORT ONLY. Scenario outputs (payment shock, affordability, delinquency and attrition "
            "probabilities, value at risk) prioritise outreach and inform committee discussion. They do not set individual "
            "pricing and are never used to decline a renewal.\n\n"
            "RULE 2 - GOVERNED INPUTS. Factor shocks come from the governed preset library or a documented custom run. "
            "Live web information may only select a severity band for a governed world-event preset; it never sets a number. "
            "Risks proposed from the web that are not in the library are proxies and must be labelled as such.\n\n"
            "RULE 3 - ASSUMPTIONS DISCLOSED. Any committee paper using a scenario must state the factor values, the affordability "
            "limits used (RP-013) and the known limitations of the attrition model (RP-005).\n\n"
            "RULE 4 - HOUSE VIEW. The Retail Risk Committee's current house view is that fixed renewal rates track the GoC "
            "5-year yield with roughly 90% pass-through, and that payment shock is the primary driver of both attrition and "
            "early delinquency in the FY26 book. OSFI Guideline E-23 is the model-risk anchor."
        ),
    },
    {
        "id": "RP-016", "category": "pricing_guardrail", "effective_date": "2026-05-01",
        "owner": "Head of Retail Marketing Compliance",
        "title": "Client Communications - Required Disclosures and Prohibited Claims",
        "content": (
            "SCOPE. Applies to flyers, emails, SMS, call scripts and letters sent to clients about renewals or products.\n\n"
            "RULE 1 - RATE STATEMENTS. Any rate shown must state the term, the product type, that it is subject to approval and "
            "the date the offer expires. Payment illustrations must state the amortization and frequency assumed.\n\n"
            "RULE 2 - COMPETITOR CLAIMS. Comparisons with other lenders require dated, documented evidence (see RP-002) and may "
            "not name a competitor in client-facing material.\n\n"
            "RULE 3 - PROHIBITED WORDS. 'Guaranteed', 'pre-approved', 'risk-free', 'best rate in Canada' and urgency such as "
            "'act now or lose' are prohibited.\n\n"
            "RULE 4 - INTERNAL DATA. Client-facing content must never expose internal scores, wellness bands, attrition "
            "probabilities, approval tiers or staff notes.\n\n"
            "RULE 5 - REVIEW. Every client-facing draft passes the compliance review step before it can be saved or sent. "
            "A blocked draft cannot be overridden by the drafter."
        ),
    },
    {
        "id": "RP-017", "category": "regulatory_reference", "effective_date": "2026-05-01",
        "owner": "Chief Privacy Officer",
        "title": "Privacy, Purpose Limitation and Recordkeeping",
        "content": (
            "SCOPE. Applies to the use of client data in analytics, AI assistants and call notes.\n\n"
            "RULE 1 - PURPOSE. Client data may be used only for the servicing or advisory purpose for which it was collected. "
            "Transaction-pattern inferences (for example a likely life event) may inform a conversation but must not be stated "
            "to the client as a fact about them.\n\n"
            "RULE 2 - MINIMISATION. Outbound drafts include only the data needed for the message. Household members' data is "
            "never disclosed to another member without their consent.\n\n"
            "RULE 3 - NOTES. Call notes separate facts from the system of record, what the client said, and AI-generated "
            "summaries, which must be labelled as such. Work IQ content may inform preparation but never overrides the system "
            "of record.\n\n"
            "RULE 4 - RETENTION. Notes and drafts are retained per the records schedule; nothing is sent automatically by any "
            "AI assistant. The Personal Information Protection and Electronic Documents Act (PIPEDA) is the statutory anchor."
        ),
    },
    {
        "id": "RP-018", "category": "approval_requirement", "effective_date": "2026-06-01",
        "owner": "VP Personal Banking Distribution",
        "title": "Next-Best-Action Governance and Primary-Banking Retention",
        "content": (
            "SCOPE. Applies to ranked next-best actions shown to advisors and to deposit-retention outreach.\n\n"
            "RULE 1 - ORDER OF PRIORITY. Support (RP-012/RP-014) outranks Retain, which outranks Deepen. An action that fails a "
            "gate (consent RP-011, vulnerability RP-012, affordability RP-013) is shown as blocked with its reason - never hidden "
            "and never re-labelled as eligible.\n\n"
            "RULE 2 - PRIMARY BANKING. When 10% or more of a client's payroll moves to another institution for two consecutive "
            "months, the advisor should hold a relationship review within 30 days. Fee waivers on the operating account up to "
            "12 months may be approved by the advisor; longer waivers need Branch Manager approval.\n\n"
            "RULE 3 - ADVISOR JUDGEMENT. Actions are recommendations. The advisor records the outcome and reason; outcomes feed "
            "the quarterly model review under RP-005.\n\n"
            "RULE 4 - FAIRNESS. Rankings must not use protected characteristics or proxies for them."
        ),
    },
]


def main() -> None:
    docs = json.loads(P.read_text(encoding="utf-8"))
    ids = {d["id"] for d in NEW}
    docs = [d for d in docs if d["id"] not in ids] + [{k: d[k] for k in ("id", "title", "category", "effective_date", "owner", "content")} for d in NEW]
    docs.sort(key=lambda d: d["id"])
    P.write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(docs)} policies: {', '.join(d['id'] for d in docs)}")


if __name__ == "__main__":
    main()
