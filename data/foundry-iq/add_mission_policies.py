"""Append the agent-mission policies RP-033..RP-034 to renewal_policies.json (idempotent).

    python add_mission_policies.py

RP-033 governs the agent harness itself (what an AI agent may do, the guardrails, human approval and audit).
RP-034 covers payroll / direct-deposit redirection, a fraud pattern the quiet-leaver and security missions surface.
Re-index afterwards with index_renewal_policies.py.
"""
import json
import pathlib

P = pathlib.Path(__file__).resolve().parent / "renewal_policies.json"
NEW = [
 {"id": "RP-033", "category": "regulatory_reference", "effective_date": "2026-10-01", "owner": "Chief Data and AI Officer",
  "title": "AI Agents in Client Decisions - Harness, Guardrails and Human Approval",
  "content": "SCOPE. Applies to every AI agent that prepares a client decision, client communication or case file in personal banking, including the mission agent, the Compliance Reviewer and the Scenario Analyst. Aligned with OSFI Guideline E-23 (model risk) and the Bank's responsible-AI standard.\n\nRULE 1 - PREPARE, NEVER ACT. An agent may research, reconcile and draft. It may never send a communication, approve or decline credit, set or promise a price, freeze or release funds, cancel cover, or contact a client. Any output that claims such an action is rejected.\n\nRULE 2 - GOVERNED DATA IS AUTHORITATIVE. The agent works from a governed packet assembled from the system of record (Fabric IQ). Colleague correspondence (Work IQ) and the public web (Web IQ) may change the decision but never overwrite a governed figure. Every figure the agent uses must be traceable to the governed packet or cited with its source; untraced figures are flagged for the human reviewer.\n\nRULE 3 - DETERMINISTIC GUARDRAILS, THEN REVIEW. Before any human sees a client message, deterministic checks run in code (consent RP-011, support-first RP-012, affordability RP-013, prohibited claims and internal data RP-016, privacy RP-017, security RP-032) and the Compliance Reviewer agent reviews it. A guardrail block cannot be overridden by the agent or the reviewer; the human may approve the plan but not blocked client copy.\n\nRULE 4 - HUMAN DECISION AND AUDIT. A named employee approves, sends back or escalates every agent recommendation. The decision, the run identifier, the guardrail verdict and the reviewer verdict are logged and retained under RP-017. Agents are tested against a fixed case set before each instruction change, and recovery actions (for example a retry after a tool failure) are visible in the run trace."},
 {"id": "RP-034", "category": "risk_consideration", "effective_date": "2026-10-01", "owner": "Chief Fraud Officer",
  "title": "Payroll and Direct-Deposit Changes - Verification Before Retention",
  "content": "SCOPE. Applies when a client's payroll or other recurring deposit stops, falls, or is redirected to another institution, and to any request to change direct-deposit details.\n\nRULE 1 - RULE OUT FRAUD FIRST. A payroll redirect in the same 30 days as a new-device login, a contact-detail change or a new payee is treated as possible account takeover or payroll-diversion fraud (RP-032), not as attrition. Verify with the client by the verified phone number on file before any retention or relationship outreach.\n\nRULE 2 - THEN UNDERSTAND THE REASON. Once fraud is ruled out, a payroll move is a relationship conversation (RP-018): new employer, fees (RP-023), a competitor offer, or financial strain (RP-012, RP-014). One relationship conversation replaces separate product calls.\n\nRULE 3 - NO PRESSURE. Never imply that keeping payroll with the Bank is a condition of a mortgage rate, renewal or other service unless it is a written, approved pricing condition (RP-002), and never use the client's deposit data in client copy beyond what the client already knows."},
]
docs = json.loads(P.read_text(encoding="utf-8"))
docs = [d for d in docs if d["id"] not in {n["id"] for n in NEW}] + NEW
docs.sort(key=lambda d: d["id"])
P.write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(len(docs), "policies:", ", ".join(d["id"] for d in docs[-4:]))
