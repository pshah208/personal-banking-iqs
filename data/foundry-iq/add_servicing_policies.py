"""Add the mortgage-servicing policies the servicing console relies on (RP-037, RP-038).

    cd data/foundry-iq && python add_servicing_policies.py

Idempotent: replaces the two documents if present. SYNTHETIC policy text; the
Bank Act cost-of-borrowing and prepayment disclosure rules, PIPEDA and the credit
bureaus' consumer-consent requirements are real public frameworks cited by name only.
"""

import json
import pathlib

P = pathlib.Path(__file__).with_name("renewal_policies.json")
NEW = [
    {"id": "RP-037", "category": "approval_requirement", "effective_date": "2026-10-01", "owner": "Head of Mortgage Servicing",
     "title": "Payout and Discharge Statement Requests - Retention Review Without Delay",
     "content": "SCOPE. Applies when a lawyer, notary or another lender requests a payout (discharge) statement for a mortgage.\n\n"
                "RULE 1 - NEVER DELAY THE CLIENT. The statement is issued by its due date (normally within 7 days of the request) "
                "whatever retention activity happens. The client's right to pay off and discharge the mortgage, and the prepayment "
                "charge disclosure, are never conditional on a retention conversation.\n\n"
                "RULE 2 - RETENTION REVIEW. When the stated purpose is a transfer to another lender, the file may be routed to the "
                "retention team for up to 48 hours inside the statement window. A colleague approves the routing; the retention "
                "team contacts the client through their usual advisor, never through the lawyer.\n\n"
                "RULE 3 - WHAT MAY BE OFFERED. Retention offers follow the RP-002 approval matrix and the retention offer shelf; "
                "a straight renewal needs no re-qualification (RP-004). Clients in the Vulnerable band are offered hardship support "
                "first (RP-012, RP-014).\n\n"
                "RULE 4 - SALE OF PROPERTY. A payout for the sale of the property is a service conversation (portability, "
                "bridge financing), not retention.\n\n"
                "RULE 5 - AUDIT. The request, the routing decision, the approver and any offer are recorded."},
    {"id": "RP-038", "category": "regulatory_reference", "effective_date": "2026-10-01", "owner": "Chief Privacy Officer",
     "title": "Credit-Bureau Trigger Alerts - Consent and Use",
     "content": "SCOPE. Applies to alerts from the credit bureaus that another lender or broker has made a hard inquiry on an "
                "existing mortgage client (trigger alerts).\n\n"
                "RULE 1 - CONSENT. Trigger alerts are used only where the client gave express consent to ongoing credit "
                "monitoring for relationship management, consistent with PIPEDA and the bureaus' consumer-consent requirements. "
                "Without consent the alert is suppressed: no lender names, no outreach based on it.\n\n"
                "RULE 2 - NEVER REVEAL THE SOURCE. Outreach never tells the client the Bank saw their credit inquiry. It is framed "
                "as the ordinary renewal conversation.\n\n"
                "RULE 3 - WHAT IT JUSTIFIES. A consented trigger supports a rate hold or a retention offer within RP-002; it never "
                "justifies a credit decision or a change to the client's limits.\n\n"
                "RULE 4 - RETENTION. Trigger data is kept no longer than 90 days."},
]

docs = json.loads(P.read_text(encoding="utf-8"))
ids = {n["id"] for n in NEW}
docs = [d for d in docs if d["id"] not in ids] + [{k: d[k] for k in ("id", "title", "category", "effective_date", "owner", "content")} for d in NEW]
docs.sort(key=lambda d: d["id"])
P.write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(len(docs))
