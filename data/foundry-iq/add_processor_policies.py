"""Add the card-servicing policies the processor console relies on (RP-035, RP-036).

    cd data/foundry-iq && python add_processor_policies.py

Idempotent: replaces the two documents if present. SYNTHETIC policy text; the
Code of Conduct for the Credit and Debit Card Industry in Canada and card-network
dispute rules are real public references cited by name only.
"""

import json
import pathlib

P = pathlib.Path(__file__).with_name("renewal_policies.json")
NEW = [
    {"id": "RP-035", "category": "approval_requirement", "effective_date": "2026-09-01", "owner": "Head of Fraud Management - Retail",
     "title": "Card Controls, Locks and Reissue - Authority and Evidence",
     "content": "SCOPE. Applies to any change a colleague makes to a client's card through the card processor: temporary lock, unlock, "
                "block and reissue, and changes to e-commerce, international or contactless controls.\n\n"
                "RULE 1 - EVIDENCE. A lock or reissue must be backed by evidence in the system of record: a card-testing pattern (three or more "
                "card-not-present attempts under CAD 5 within an hour), a fraud decline, a fraud alert, or the client's own request. The evidence "
                "is referenced on the request.\n\n"
                "RULE 2 - HUMAN APPROVAL. Every change is approved by a named colleague before it is sent to the processor. Agents and automated "
                "tools may prepare and preview a request; they may never send one.\n\n"
                "RULE 3 - LEAST DISRUPTION. Prefer a temporary lock while the client is contacted; block and reissue when compromise is "
                "confirmed or test charges were approved. Recurring billers enrolled in the network account updater receive the new card "
                "details automatically.\n\n"
                "RULE 4 - CLIENT CONTACT. The client is told about the change through the app or a verified phone number (RP-022). Never ask for "
                "a PIN, passcode or full card number.\n\n"
                "RULE 5 - AUDIT. The request, the response reference, the approver and the evidence are retained for seven years."},
    {"id": "RP-036", "category": "regulatory_reference", "effective_date": "2026-09-01", "owner": "Head of Card Operations",
     "title": "Card Disputes, Chargebacks and Card-on-File Billers",
     "content": "SCOPE. Applies to disputed card transactions and to recurring merchants that bill a client's card (card-on-file).\n\n"
                "RULE 1 - OPEN PROMPTLY. A dispute for unauthorised card-not-present charges is opened as soon as the client or the fraud team "
                "confirms them, with provisional credit for the disputed amount while it is investigated, consistent with the zero-liability "
                "commitments in the Code of Conduct for the Credit and Debit Card Industry in Canada.\n\n"
                "RULE 2 - DEADLINES. Network response deadlines (typically 30 days for a chargeback response and 10 days at pre-arbitration) "
                "are tracked from the system of record; a dispute within 10 days of its deadline is escalated to the disputes team lead.\n\n"
                "RULE 3 - KEEP THE CLIENT INFORMED. The client is told when a dispute opens, when provisional credit is granted or reversed, "
                "and how it closes.\n\n"
                "RULE 4 - CARD-ON-FILE. Before a card expires or is reissued, billers on file are updated through the network account updater "
                "where the client is enrolled. A recurring biller that stops billing is a service signal (possible card switch) - outreach "
                "about it follows RP-011 consent and RP-019 suitability."},
]

docs = json.loads(P.read_text(encoding="utf-8"))
ids = {n["id"] for n in NEW}
docs = [d for d in docs if d["id"] not in ids] + [{k: d[k] for k in ("id", "title", "category", "effective_date", "owner", "content")} for d in NEW]
docs.sort(key=lambda d: d["id"])
P.write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(len(docs))
