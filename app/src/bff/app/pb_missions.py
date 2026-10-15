"""Agent missions - one job per product book that an API cannot do, run through a visible harness.

Each product book already answers "what does the data say?" deterministically: KPIs, ranked plays,
eligibility and a templated draft. An API can do all of that without an agent. A mission is the part
an API cannot do. It reads what colleagues wrote about a client (Work IQ), interprets the policy for this
specific case (Foundry IQ), adds dated market context (Web IQ), and reconciles plays from different books
that contradict each other. It ends with one decision a human can act on.

The harness wraps the agent so its autonomy is bounded and visible:

    1 plan          what the run will do, fixed in code
    2 packet        cross-book governed facts (Fabric IQ) + every book's siloed plays = "what an API returns"
    3 agent         pb-mission-agent investigates with live tool calls (traced call by call)
    4 guardrails    deterministic checks over the agent's output: figures traced to data or a cited source,
                    valid policy ids, no autonomous action, client-copy rules, sales pause, verified channel
    5 review        the Compliance Reviewer agent over the client message (skipped when there is none)
    6 human         an advisor approves, sends back or escalates; the decision is audit-logged

The agent never sends, approves, declines, freezes or contacts anyone. SYNTHETIC demo data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from . import pb_books as B
from . import pb_cards as K
from . import pb_customers as C
from .agent_client import run_agent
from .auth import User
from .config import settings
from .iq import sse

logger = logging.getLogger("missions")

AS_OF = B.AS_OF
DEPOSIT = {a["customer_id"]: a for a in B.D["deposit_accounts"]}
INV_BY_CUST = {r["customer_id"]: r for r in B._INV_ROWS.values()}
REN = C.REN_BY_CUST
KNOWN_POLICIES = {f"RP-{i:03d}" for i in range(1, 35)}
SUPPORT_TYPES = {"Support", "Protect"}
SELL_TYPES = {"Retain", "Grow", "Deepen", "Acquire"}

RUNS: "OrderedDict[str, dict]" = OrderedDict()
AUDIT: deque = deque(maxlen=200)


# --------------------------------------------------------------------------- #
# Cross-book customer view
# --------------------------------------------------------------------------- #
def _pick(d: dict, keys: list[str]) -> dict:
    return {k: d[k] for k in keys if k in d and d[k] not in ("", None)}


def name_of(cid: str) -> str:
    for src in (DEPOSIT.get(cid), B.NJ.get(cid), B.CARD.get(cid), B.POSTURE.get(cid), B.COVER.get(cid)):
        if src and src.get("customer_name"):
            return src["customer_name"]
    if cid in C.CUST:
        return C.CUST[cid]["full_name"]
    return cid


def book_accounts(cid: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if cid in REN:
        out["mortgage"] = [REN[cid]["renewal_id"]]
    if cid in B.CARD:
        out["cards"] = [B.CARD[cid]["account_id"]]
    if cid in DEPOSIT:
        out["banking"] = [DEPOSIT[cid]["account_id"]]
    if cid in B.FACS_BY_CUST:
        out["borrowing"] = [f["account_id"] for f in B.FACS_BY_CUST[cid]]
    if cid in INV_BY_CUST:
        out["investing"] = [INV_BY_CUST[cid]["account_id"]]
    if cid in B.NJ:
        out["newcomers"] = [B.NJ[cid]["account_id"]]
    if cid in B.COVER:
        out["insurance"] = [B.COVER[cid]["account_id"]]
    if cid in B.POSTURE:
        out["security"] = [B.POSTURE[cid]["account_id"]]
    return out


BOOK_TITLE = {"mortgage": "Mortgage", "cards": "Cards", **{k: v["title"] for k, v in B.BOOK.items()}}


def siloed_plays(cid: str) -> list[dict]:
    """Every book's own ranked plays for this client - what each book's API returns, independently."""
    rows: list[dict] = []
    for book, ids in book_accounts(cid).items():
        if book == "mortgage":
            for a in C.NBA.get(cid, [])[:3]:
                rows.append({"book": "Mortgage", "account_id": ids[0], "play_type": a["action_type"], "play": a["product_name"],
                             "eligibility": a["eligibility"], "rationale": a["rationale"], "policy": ""})
        elif book == "cards":
            for p in K.PLAYS.get(ids[0], []):
                rows.append({"book": "Cards", "account_id": ids[0], "play_type": p["play_type"], "play": p["play"],
                             "eligibility": p["eligibility"], "rationale": p["rationale"], "policy": p.get("policy", "")})
        else:
            for aid in ids:
                for p in B._plays(book, aid):
                    rows.append({"book": BOOK_TITLE[book], "account_id": aid, "play_type": p["play_type"], "play": p["play"],
                                 "eligibility": p["eligibility"], "rationale": p["rationale"], "policy": p["policy"]})
    return rows


def _client(cid: str) -> dict:
    c = B.CLIENT.get(cid) or {}
    w = C.WELL.get(cid, {})
    band = w.get("wellness_band") or c.get("wellness_band", "")
    return {
        "customer_id": cid, "name": name_of(cid), "segment": c.get("segment", ""), "branch": c.get("branch", ""),
        "wellness_band": band, "email_consent": c.get("email_consent", ""), "tds_renewal_pct": c.get("tds_renewal_pct", ""),
        "open_fraud_case": cid in B.OPEN_CASE,
        "sales_paused": band == "Vulnerable" or w.get("sales_suppressed") == "Y" or cid in B.OPEN_CASE,
    }


def packet(cid: str) -> list[dict]:
    """Governed cross-book facts for one client (Fabric IQ tables, bundled). Compact on purpose."""
    out: list[dict] = [{"book": "Client", "table": "household key across every book", "facts": _client(cid)}]
    if cid in C.CUST:
        cu = C.customer(cid)
        r, cap, w = cu["renewal"], cu["capacity"], cu["wellness"]
        out.append({"book": "Mortgage", "table": "renewals · renewal_attrition_risk · credit_capacity", "facts": {
            **_pick(r, ["renewal_id", "maturity_date", "days_to_maturity", "product_type", "mortgage_balance_cad", "current_rate_pct",
                        "offered_renewal_rate_pct", "payment_shock_pct", "ltv_pct", "renewal_stage", "attrition_risk_score",
                        "renewal_likelihood_pct", "top_risk_drivers", "competitor_rate_gap_bps", "recommended_offer_id",
                        "annual_revenue_exposure_cad"]),
            "attrition_band": cu["attrition_band"], "five_year_lifetime_value_cad": cu["lifetime_value"],
            **_pick(cap, ["current_payment_monthly_cad", "renewal_payment_monthly_cad", "gds_renewal_pct", "tds_now_pct", "tds_renewal_pct",
                          "gross_income_cad"]),
            "tenure_years": cu["tenure_years"], "advisor": cu["advisor"]}})
        out.append({"book": "Customer 360", "table": "financial_wellness · consent_preferences · life_events · customer_products", "facts": {
            "wellness_score": w.get("wellness_score"), "drivers": w.get("drivers"), "support_pathway": w.get("support_pathway"),
            "sales_suppressed": w.get("sales_suppressed"), "consent": cu["consent"],
            "life_events": [_pick(e, ["event_type", "event_date", "implication", "source"]) for e in cu["life_events"]],
            "products": [f"{p['product_name']} ({p['balance_cad']:,.0f})" for p in cu["products"]],
            "signals_last_3m": [_pick(s, ["month", "payroll_inflow_cad", "competitor_outflow_cad", "card_utilization_pct", "overdraft_days",
                                          "nsf_count", "missed_payments", "savings_balance_cad"]) for s in cu["signals"][-3:]]}})
    if cid in B.CARD:
        a = B.CARD[cid]
        out.append({"book": "Cards", "table": "card_accounts", "facts": _pick(a, [
            "account_id", "product_name", "behaviour", "credit_limit", "balance", "utilization_pct", "min_payment_months_12m", "purchase_apr",
            "annual_fee", "fee_anniversary_days", "spend_trend_pct", "monthly_spend_avg", "foreign_spend_share_pct", "days_past_due",
            "fraud_alerts_90d", "cli_express_consent", "income"])})
    if cid in DEPOSIT:
        a = DEPOSIT[cid]
        flows = B.FLOWS.get(a["account_id"], [])[-3:]
        out.append({"book": "Everyday banking", "table": "deposit_accounts · deposit_flows_monthly", "facts": {
            **_pick(a, ["account_id", "package", "monthly_fee", "best_fit_package", "package_cost_12m", "best_fit_cost_12m", "fees_charged_12m",
                        "avg_chequing_balance", "savings_balance", "outflow_share_pct", "primary_banking", "nsf_3m", "overdraft_days_3m",
                        "overdraft_protection"]),
            "flows_last_3m": [_pick(f, ["month", "payroll_in", "transfers_to_other_institutions", "bill_payments", "nsf_count", "end_balance"])
                              for f in flows]}})
    if cid in B.FACS_BY_CUST:
        out.append({"book": "Borrowing", "table": "credit_facilities · debt_consolidation_candidates", "facts": {
            "facilities": [_pick(f, ["account_id", "facility_type", "balance_cad", "limit_or_original_cad", "rate_pct", "rate_type",
                                     "utilisation_pct", "monthly_payment_cad", "days_past_due", "days_to_maturity", "combined_ltv_pct"])
                           for f in B.FACS_BY_CUST[cid]],
            "consolidation": _pick(B.CAND.get(cid, {}), ["card_balance_cad", "card_apr_pct", "card_min_payment_cad",
                                                          "card_months_to_repay_at_minimum", "card_total_interest_at_minimum_cad",
                                                          "target_type", "target_rate_pct", "new_payment_cad", "new_total_interest_cad",
                                                          "interest_saved_annual_cad", "payment_falls", "tds_check", "treatment"])}})
    if cid in INV_BY_CUST:
        r = INV_BY_CUST[cid]
        out.append({"book": "Investing", "table": "investment_accounts · registered_room", "facts": {
            **_pick(r, ["account_id", "plans", "total_value", "gic_maturing_90d", "risk_profile", "kyc_last_updated", "kyc_age_months",
                        "kyc_status"]),
            "holdings": [_pick(h, ["plan", "holding_type", "market_value_cad", "gic_maturity_date", "gic_rate_pct", "days_to_maturity"])
                         for h in B.HOLD_BY_CUST[cid]],
            "room": _pick(B.ROOM.get(cid, {}), ["age", "dependents", "homeowner", "fhsa_eligible", "tfsa_room_unused_cad",
                                                 "rrsp_room_unused_cad", "has_resp", "cesg_missed_per_year_cad", "savings_balance_cad"])}})
    if cid in B.NJ:
        j = B.NJ[cid]
        out.append({"book": "Newcomers & transfers", "table": "newcomer_journey · transfers_out_monthly", "facts": {
            **_pick(j, ["account_id", "origin_country", "months_in_canada", "status", "credit_building_stage", "credit_file_months",
                        "secured_card_months", "secured_card_on_time", "newcomer_package_active", "days_to_package_expiry", "next_package",
                        "next_package_cost_12m", "corridor", "transfer_provider", "transfers_12m", "sent_12m_cad", "transfer_cost_12m_cad",
                        "bank_equivalent_cost_12m_cad", "new_recipients_90d", "scam_watch_corridor", "scam_risk_sender", "income"]),
            "transfers_last_3m": [_pick(t, ["month", "provider", "transfers_count", "amount_cad", "total_cost_cad", "new_recipients"])
                                  for t in B.TX.get(j["account_id"], [])[-3:]]}})
    if cid in B.COVER:
        g = B.COVER[cid]
        out.append({"book": "Insurance", "table": "insurance_policies · coverage_gaps", "facts": {
            **_pick(g, ["account_id", "policy_types", "mortgage_balance_cad", "mortgage_life_coverage_cad", "gap_amount_cad", "dependents",
                        "optional_premiums_monthly_cad", "premium_affordability_flag", "lapsed_90d", "days_to_renewal",
                        "card_includes_travel", "travel_spend_12m_cad"]),
            "policies": [_pick(p, ["policy_id", "policy_type", "status", "start_date", "lapse_date", "days_since_lapse", "monthly_premium_cad",
                                   "premium_when_active_cad", "covered_amount_cad", "optional_creditor"]) for p in B.POL_BY_CUST.get(cid, [])]}})
    if cid in B.POSTURE:
        s = B.POSTURE[cid]
        out.append({"book": "Security & fraud", "table": "customer_security_posture · security_events", "facts": {
            **_pick(s, ["account_id", "age", "events_90d", "open_events", "open_high_events", "latest_event", "latest_event_date",
                        "contact_email_changed_30d", "two_step_verification", "alerts_enabled", "trusted_contact_on_file",
                        "last_security_checkin", "amount_at_risk_cad"]),
            "events": [_pick(e, ["event_id", "event_date", "event_type", "channel", "amount_cad", "severity", "status", "note"])
                       for e in B.EV_BY_CUST.get(cid, [])]}})
    return out


# --------------------------------------------------------------------------- #
# Missions
# --------------------------------------------------------------------------- #
def _gic_cases() -> list[str]:
    rows = [r for r in INV_BY_CUST.values() if r["gic_maturing_90d"]]
    rows.sort(key=lambda r: (r["kyc_status"] != "Stale", r["customer_id"] not in B.OPEN_CASE,
                             int(REN[r["customer_id"]]["days_to_maturity"]) if r["customer_id"] in REN else 999, -r["gic_maturing_90d"]))
    return [r["customer_id"] for r in rows]


def _leaver_cases() -> list[str]:
    def score(a: dict) -> float:
        cid = a["customer_id"]
        days = int(REN[cid]["days_to_maturity"]) if cid in REN else 999
        return (a["outflow_share_pct"] + (25 if days <= 60 else 10 if days <= 120 else 0)
                + (10 if B.CARD.get(cid, {}).get("behaviour") == "Persistent debt" else 0) + (15 if cid in B.OPEN_CASE else 0))
    rows = [a for a in DEPOSIT.values() if a["outflow_share_pct"] >= 10]
    return [a["customer_id"] for a in sorted(rows, key=lambda a: -score(a))]


def _pricing_cases() -> list[str]:
    rows = [(cid, r) for cid, r in REN.items()
            if C.RISK[r["renewal_id"]]["attrition_risk_band"] == "High" and float(C.RISK[r["renewal_id"]]["competitor_rate_gap_bps"] or 0) > 0]
    rows.sort(key=lambda x: -float(C.RISK[x[1]["renewal_id"]]["competitor_rate_gap_bps"]))
    return [cid for cid, _ in rows]


def _card_cases() -> list[str]:
    return [a["customer_id"] for a in K.ACC.values() if a["behaviour"] == "Persistent debt" and a["linked_mortgage"] == "Y"]


def _consolidation_cases() -> list[str]:
    rows = list(B.CAND.values())
    rows.sort(key=lambda c: (c["customer_id"] not in B.OPEN_CASE, c["treatment"] == "Offer", -c["interest_saved_annual_cad"]))
    return [c["customer_id"] for c in rows]


def _insurance_cases() -> list[str]:
    return [g["customer_id"] for g in B.COVER.values() if g["lapsed_90d"] or (g["optional_premiums_monthly_cad"] and g["premium_affordability_flag"] == "Y")]


def _security_cases() -> list[str]:
    rows = [s for s in B.POSTURE.values() if s["open_events"] or s["scam_type_events"]]
    rows.sort(key=lambda s: (-s["open_high_events"], s["contact_email_changed_30d"] != "Y", -s["age"]))
    return [s["customer_id"] for s in rows]


def _newcomer_cases() -> list[str]:
    rows = [j for j in B.NJ.values() if j["scam_risk_sender"] == "Y" or (j["newcomer_package_active"] == "Y" and j["days_to_package_expiry"] != ""
                                                                         and int(j["days_to_package_expiry"]) <= 60)
            or (j["credit_building_stage"] == "Secured card" and j["secured_card_months"] >= 12)]
    rows.sort(key=lambda j: (j["customer_id"] not in B.OPEN_CASE, j["scam_risk_sender"] != "Y"))
    return [j["customer_id"] for j in rows]


MISSIONS: dict[str, dict[str, Any]] = {
    "mortgage": {
        "title": "Pricing exception: match, partly match, or support?",
        "question": "A renewal client has a competitor quote below our floor. Should we match it? If so, under whose authority, on what evidence and with what conditions? Or is this really a payment-shock conversation?",
        "deliverable": "Committee-ready exception memo + advisor talking points",
        "owner": "Branch Manager → Pricing Committee",
        "api": ["Attrition score, competitor gap in bps and the discount grid", "'Retain - mortgage' ranked first by the next-best-action model",
                "A templated retention email"],
        "agent": ["Finds the escalation thread in mail and Teams, including a conditional committee decision that the system of record does not hold",
                  "Applies the competitor-evidence standard to what the client actually supplied (PDF or screenshot) and to the approval authority",
                  "Weighs payment shock and household strain against relationship value, and may turn a rate match into a support conversation",
                  "Writes the memo and talking points and never promises a rate the Bank has not approved"],
        "policies": ["RP-001", "RP-002", "RP-003", "RP-007", "RP-010", "RP-012", "RP-013", "RP-016"],
        "work": "the pricing exception or rate-match request for this renewal, the competitor evidence supplied, and any approval or committee decision",
        "web": "posted 5-year fixed mortgage rates at Canadian lenders this month (issuer-neutral, dated, sourced)",
        "anchors": {"CUST-1014": "Escalation thread: 32 bps exception request", "CUST-1033": "Committee ruling on screenshot evidence"},
        "auto": _pricing_cases,
    },
    "cards": {
        "title": "Support or retention? One answer for the household",
        "question": "The card book says this client needs persistent-debt support. The mortgage model says retain them at renewal with an offer. Which conversation should happen, and what must not be said?",
        "deliverable": "One cross-book support plan + a support-first client note",
        "owner": "Advisor → Client Assistance",
        "api": ["Card behaviour 'Persistent debt' and a Support play (RP-021)", "A separate mortgage 'Retain' play and any 'Deepen' plays",
                "Two independent templated drafts that contradict each other"],
        "agent": ["Notices that the books disagree and resolves it for the whole household, not one product at a time",
                  "Reads branch mail about persistent debt and renewal stress and the manager's guidance on this client",
                  "Puts minimum-payment cost next to the renewal payment shock and routes the client to hardship or amortization relief",
                  "Writes one plain-language, support-first message with no rewards, upgrade or limit-increase content"],
        "policies": ["RP-006", "RP-012", "RP-013", "RP-014", "RP-019", "RP-020", "RP-021"],
        "work": "this client's card debt, renewal stress and whether to treat them as support-first across books",
        "web": "current Canadian consumer guidance on paying only the credit-card minimum (FCAC), dated and sourced",
        "anchors": {"CUST-1025": "Branch mail: persistent debt + renewal stress", "CUST-1034": "Branch mail: 98% utilisation, renewal in 134 days",
                    "CUST-1044": "Branch mail: renewal in 26 days", "CUST-1049": "Advisor note: phone only - partner reads her email"},
        "auto": _card_cases,
    },
    "banking": {
        "title": "Who is quietly leaving us, and what one conversation keeps them?",
        "question": "Payroll is moving to another institution. Is this client leaving the whole relationship? What sits behind it, and what single conversation should replace three product calls?",
        "deliverable": "Relationship review brief + one consolidated outreach",
        "owner": "Advisor → Branch Manager",
        "api": ["'Payroll moving out' % from deposit flows (RP-018)", "A Package-fit or Bundle play in banking",
                "Separate mortgage, card and lending plays, each sent on its own"],
        "agent": ["Connects deposit flight, an upcoming renewal, card behaviour and an open fraud case into one explanation",
                  "Checks colleague mail for what the client has told the branch, which no table holds",
                  "Decides whether the right move is retention, support or security first, and says what NOT to send",
                  "Replaces several product emails with one relationship conversation"],
        "policies": ["RP-011", "RP-012", "RP-018", "RP-023", "RP-024", "RP-032", "RP-034"],
        "work": "this client's payroll or deposits moving to another bank, fee complaints, and anything the branch has heard about them leaving",
        "web": "current Canadian bank switching bonuses and chequing package offers (issuer-neutral, dated, sourced)",
        "anchors": {"CUST-1040": "Branch: client never set up the outgoing transfers", "CUST-1044": "Advisor note: new employer pays into another bank"},
        "auto": _leaver_cases,
    },
    "borrowing": {
        "title": "Consolidation case file: help, hold or refer?",
        "question": "The engine says this client could save interest by consolidating card debt into a cheaper facility. Should anyone make that offer now, or is the right answer Client Assistance, a fraud hold or nothing at all?",
        "deliverable": "Lending case file + advisor next step",
        "owner": "Lending Advisor → Credit / Client Assistance",
        "api": ["Interest saved, new payment and the TDS check per candidate (RP-025)", "Treatment 'Offer' or 'Support' from the candidate table",
                "A templated consolidation email"],
        "agent": ["Spots what the candidate table cannot see, such as an open fraud case, a scam-victim history or a renewal shock",
                  "Reads the lending team's guidance on prime notices and consolidation tone",
                  "Shows both paths (cost at the card minimum vs the new facility) and never implies approval",
                  "Routes Vulnerable or above-guideline clients to Client Assistance instead of selling credit"],
        "policies": ["RP-012", "RP-013", "RP-014", "RP-021", "RP-025", "RP-026", "RP-032"],
        "work": "this client's card debt, consolidation, hardship or Client Assistance referral, and any fraud or scam case",
        "web": "the Bank of Canada's latest policy-rate decision and the current prime rate (dated, sourced)",
        "anchors": {"CUST-1020": "Engine says 'Offer' - queued in a campaign during a fraud case", "CUST-1025": "Above the 44% TDS guideline, renewal in 75 days",
                    "CUST-2003": "Client Assistance; recent bank-investigator scam attempt"},
        "auto": _consolidation_cases,
    },
    "investing": {
        "title": "GIC maturity: prepare the advisor, never the trade",
        "question": "A GIC matures within 90 days. What must happen before any recommendation, what does the household picture say about liquidity needs, and what should the licensed advisor ask?",
        "deliverable": "Suitability-ready meeting brief (no recommendation)",
        "owner": "Licensed Advisor",
        "api": ["GIC maturity amount and date, KYC age and status", "A 'GIC maturing' Retain play and a TFSA or RESP Grow play",
                "A templated maturity email"],
        "agent": ["Puts KYC refresh first and pauses every recommendation while KYC is stale (RP-027)",
                  "Links the maturity to the mortgage renewal, payment shock or an open fraud case that changes liquidity needs",
                  "Brings in dated posted GIC rates as advisor context only, never as a promised return",
                  "Writes the questions the advisor must ask and does not recommend a product"],
        "policies": ["RP-012", "RP-016", "RP-027", "RP-028", "RP-032"],
        "work": "this client's GIC maturity, KYC refresh and any advisor notes",
        "web": "posted 1-year and 5-year GIC rates and high-interest savings rates in Canada this month (issuer-neutral, dated, sourced)",
        "anchors": {"CUST-1041": "Wants maturities paid to a '2% a month' platform", "CUST-1008": "Asked to use the GIC against her renewal",
                    "CUST-2017": "KYC stale + open card fraud case"},
        "auto": _gic_cases,
    },
    "newcomers": {
        "title": "Newcomer next conversation: what to say, and what not to",
        "question": "The book ranks a package-expiry or credit-building play for this newcomer. Colleagues may know about a scam attempt, a held transfer or an open security case. What is the next conversation, in plain language?",
        "deliverable": "Advisor call plan + plain-language client note (or no email, call only)",
        "owner": "Newcomer Advisor",
        "api": ["Fee-free period end date and the lowest-cost next package", "Credit-building stage and secured-card history",
                "Transfer corridor, fees and FX cost"],
        "agent": ["Reads the branch thread about this client (held transfer, relative-impersonation scam, open device alert)",
                  "Puts security first and pauses card graduation or offers while a case is open (RP-032)",
                  "Checks live remittance-scam warnings for the client's corridor",
                  "Writes in plain language, offers an interpreter, and never asks for a code"],
        "policies": ["RP-011", "RP-012", "RP-016", "RP-022", "RP-029", "RP-030", "RP-032"],
        "work": "this newcomer client - package expiry, credit building, remittances, held transfers or scam reports",
        "web": "current remittance and relative-impersonation scam warnings from the Canadian Anti-Fraud Centre for the client's corridor (dated, sourced)",
        "anchors": {"CUST-3012": "Branch mail: remittance scam, transfer held", "CUST-3002": "Card graduation paused - open remittance check",
                    "CUST-3006": "Fee-free period ending + open device alert", "CUST-3001": "Frequent sender, fee-free period ending",
                    "CUST-3015": "Ready to graduate, consent on file"},
        "auto": _newcomer_cases,
    },
    "insurance": {
        "title": "Complaint and lapse remediation: put it right, don't re-sell",
        "question": "Cover lapsed and the book's rules may still rank a coverage-gap play. Was the client mis-sold ('cover was required')? What remediation is owed, and what must the Bank not offer?",
        "deliverable": "Complaint/remediation note + service-only client message",
        "owner": "Authorised Insurance Rep → Complaints",
        "api": ["Lapse date, coverage gap and premium-affordability flag", "A 'Lapsed policy' Retain play and a 'Coverage gap' Grow play",
                "A templated reinstatement-style email"],
        "agent": ["Reads the complaint thread and recognises a potential mis-selling case, not a retention opportunity",
                  "Applies RP-031 to this household: optional, never a condition of credit, no new cover above the 44% guideline",
                  "Links the lapse to the renewal payment and card debt to explain why the client stopped paying",
                  "Writes a service-only message: confirm intent, say insurance is optional, no reinstatement push"],
        "policies": ["RP-007", "RP-012", "RP-013", "RP-016", "RP-017", "RP-031"],
        "work": "complaints or notes about this client's insurance lapse and whether they were told cover was required",
        "web": "current FCAC guidance on creditor insurance being optional and on cancelling it (dated, sourced)",
        "anchors": {"CUST-1025": "Complaint: told mortgage life cover was 'required'", "CUST-1021": "Lapsed mortgage disability - check intent",
                    "CUST-2014": "Lapsed card balance protection", "CUST-1018": "LOC protection lapsed during a fraud case"},
        "auto": _insurance_cases,
    },
    "security": {
        "title": "Scam case investigation: correlate, hold, hand to a human",
        "question": "Signals are spread across security events, contact changes, payees, transfers and other books' plays. Is this account takeover or a scam in progress? What should a fraud analyst do next, and what must every other book stop doing?",
        "deliverable": "Fraud case narrative + hold/verify recommendation + cross-book stop list",
        "owner": "Fraud Analyst",
        "api": ["Security events and posture (2-step, alerts, trusted contact)", "'Open fraud case follow-up' or 'Scam coaching' plays",
                "Other books still ranking sales plays for the same client"],
        "agent": ["Builds a timeline from events, contact-detail changes and colleague mail, and names the likely typology",
                  "Matches it against the scam campaigns running this week (live Web IQ)",
                  "Recommends hold-and-verify through the verified phone number, and blocks email if contact details changed",
                  "Produces a stop list of every other book's sales play until the case closes"],
        "policies": ["RP-012", "RP-016", "RP-017", "RP-022", "RP-032", "RP-034"],
        "work": "this client's fraud or scam case - new device, payee added, contact change, held transfer, call-backs",
        "web": "scam campaigns the Canadian Anti-Fraud Centre and Canadian banks have warned about this month (dated, sourced)",
        "anchors": {"CUST-1018": "New device + payee + email changed same week", "CUST-2003": "Bank-investigator scam, transfer held",
                    "CUST-1040": "Open case; outgoing transfers she never set up", "CUST-2010": "Email changed; still on a student card campaign",
                    "CUST-3012": "Remittance scam, password reset"},
        "auto": _security_cases,
    },
}

PRIMARY_BOOK = {"mortgage": "mortgage", "cards": "cards", "banking": "banking", "borrowing": "borrowing", "investing": "investing",
                "newcomers": "newcomers", "insurance": "insurance", "security": "security"}


def _case(book: str, cid: str, why: str, anchored: bool) -> dict:
    acc = book_accounts(cid)
    plays = siloed_plays(cid)
    eligible = [p for p in plays if p["eligibility"].strip().lower() == "eligible"]
    support = any(p["play_type"] in SUPPORT_TYPES for p in plays)
    sell = any(p["play_type"] in SELL_TYPES for p in eligible)
    cl = _client(cid)
    return {"caseId": cid, "name": name_of(cid), "accountId": (acc.get(PRIMARY_BOOK[book]) or [cid])[0],
            "books": [BOOK_TITLE[b] for b in acc], "plays": len(plays), "why": why, "colleagueThread": anchored,
            "conflict": support and sell, "salesPaused": cl["sales_paused"], "openFraudCase": cl["open_fraud_case"],
            "wellnessBand": cl["wellness_band"]}


def _why(book: str, cid: str) -> str:
    bits = []
    if cid in REN:
        bits.append(f"renewal in {REN[cid]['days_to_maturity']} days")
    if B.CARD.get(cid, {}).get("behaviour") == "Persistent debt":
        bits.append("persistent card debt")
    if cid in DEPOSIT and DEPOSIT[cid]["outflow_share_pct"] >= 10:
        bits.append(f"{DEPOSIT[cid]['outflow_share_pct']:.0f}% of payroll moving out")
    if cid in B.OPEN_CASE:
        bits.append("open fraud case")
    if book == "investing" and cid in INV_BY_CUST:
        r = INV_BY_CUST[cid]
        bits.insert(0, f"${r['gic_maturing_90d']:,.0f} GIC maturing, KYC {r['kyc_status'].lower()}")
    if book == "borrowing" and cid in B.CAND:
        bits.insert(0, f"engine treatment '{B.CAND[cid]['treatment']}'")
    if book == "mortgage" and cid in REN:
        bits.insert(0, f"{C.RISK[REN[cid]['renewal_id']]['competitor_rate_gap_bps']} bps competitor gap")
    return " · ".join(bits[:3]) or "flagged by the book's rules"


def cases(book: str, limit: int = 6) -> list[dict]:
    m = MISSIONS[book]
    out, seen = [], set()
    for cid, why in m["anchors"].items():
        out.append(_case(book, cid, why, True))
        seen.add(cid)
    for cid in m["auto"]():
        if len(out) >= limit:
            break
        if cid not in seen:
            out.append(_case(book, cid, _why(book, cid), False))
            seen.add(cid)
    return out[:limit]


def catalogue() -> list[dict]:
    return [{"book": k, "title": v["title"], "deliverable": v["deliverable"]} for k, v in MISSIONS.items()]


def mission(book: str) -> dict | None:
    m = MISSIONS.get(book)
    if not m:
        return None
    return {"book": book, "bookTitle": BOOK_TITLE[book], "asOf": AS_OF, "agentName": settings.mission_agent_name,
            "reviewer": settings.compliance_agent_name, "agentCan": m["agent"],
            **{k: m[k] for k in ("title", "question", "deliverable", "owner", "api", "policies")},
            "cases": cases(book),
            "harness": [{"step": s, "title": t, "detail": d} for s, t, d in HARNESS]}


HARNESS = [
    ("plan", "Plan", "Fixed in code: which layers to use, which policies apply, what the agent may not do."),
    ("packet", "Governed packet", "Cross-book Fabric IQ facts and every book's own plays. This is what an API returns."),
    ("agent", "Agent investigation", "pb-mission-agent calls Work IQ, Foundry IQ, Web IQ and Fabric IQ, then reconciles."),
    ("guardrails", "Guardrails", "Deterministic checks over the agent's output. Can block, never approve."),
    ("review", "Compliance review", "pb-compliance-reviewer over the client message, if there is one."),
    ("human", "Human decision", "An advisor approves, sends back or escalates. Nothing is sent from here."),
]


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
HEADINGS = ["Decision", "What changed the decision", "Conflicts resolved", "What we will not do", "Advisor brief", "Client message", "Evidence"]
RETRY_HINT = ("\n\nHARNESS RETRY: your previous run failed because a Work IQ mail search returned more than the tool's 51,200-byte cap. "
              "Search mail ONLY with the client's full name in quotes, at most 3 results, subject and preview fields only. "
              "Do not run any broader mail search.")


def prompt(book: str, cid: str, pk: list[dict], plays: list[dict]) -> str:
    m = MISSIONS[book]
    ids = sorted({i for v in book_accounts(cid).values() for i in v} | {cid})
    cl = _client(cid)
    play_lines = "\n".join(f"- [{p['book']} · {p['account_id']}] {p['play_type']} / {p['play']} - {p['eligibility']} - {p['rationale']}"
                           + (f" ({p['policy']})" if p["policy"] else "") for p in plays) or "- (no plays)"
    return (
        f"MISSION - {BOOK_TITLE[book]} book: {m['title']}\n{m['question']}\n\n"
        f"CASE: {cl['name']} ({cid}); identifiers {', '.join(ids)}. As of {AS_OF}. Deliverable: {m['deliverable']} for {m['owner']}.\n\n"
        "You run inside the Bank's agent harness. The harness has already assembled the GOVERNED PACKET below from Fabric IQ "
        "(authoritative - never contradict it) and run every product book's deterministic rules: the SILOED PLAYS are what each "
        "book's API returns on its own. After you answer, deterministic guardrails check your output and the Compliance Reviewer "
        "reviews your client message; then a human decides. You never send, approve, decline, freeze, cancel or contact anyone. "
        "The harness and your limits are governed by RP-033.\n\n"
        "Do this, in order:\n"
        f"1. Work IQ - search mail, Teams and meeting notes for {m['work']}. Search narrowly: first \"{cl['name']}\" in quotes, then one "
        "identifier at a time; 3-5 results, subjects and previews only (a broad search exceeds the tool's size cap and fails). "
        "Quote (briefly) anything that changes the decision. If nothing is found, say so.\n"
        f"2. Foundry IQ - retrieve and cite by id the policies that govern this case (start with {', '.join(m['policies'])}).\n"
        f"3. Web IQ - {m['web']}. Context for the advisor only: dated, sourced, never a client-facing number.\n"
        "4. Fabric IQ - run at least one Fabric IQ query that verifies a key figure from the packet (the harness checks that you did).\n"
        "5. Reconcile - where the siloed plays conflict with each other, with colleagues or with policy, make one call.\n\n"
        "OUTPUT - markdown, exactly these level-2 headings in this order, under ~500 words:\n"
        "## Decision\nOne short paragraph: the single recommended path, the owner role and by when.\n"
        "## What changed the decision\n3-5 bullets the book rules alone would miss, each tagged [Work IQ], [Foundry IQ RP-0xx], [Web IQ <date>] or [Fabric IQ].\n"
        "## Conflicts resolved\nTable | Siloed play | Agent call | Why | covering every siloed play that is not the decision.\n"
        "## What we will not do\nBullets.\n"
        "## Advisor brief\n3-6 bullets the advisor says or asks; internal language is fine here.\n"
        "## Client message\nEither 'SUBJECT: ...' then 'BODY:' and a short plain-language email signed 'the Bank', or 'NONE - <reason>' "
        "when email is the wrong channel (for example a verified phone call only, or no contact until a case closes). The client "
        "message must never contain internal data (bands, scores, TDS, model outputs, account or renewal ids), competitor or bank names, "
        "or a rate or approval the Bank has not committed to.\n"
        "## Evidence\nBullets: every figure you used that is NOT in the governed packet (or is computed from it), with its source "
        "([Work IQ] sender/date, [Web IQ] publisher/date, or 'computed from packet').\n\n"
        f"Client context: wellness band {cl['wellness_band'] or 'n/a'}, email marketing consent {cl['email_consent'] or 'n/a'}, "
        f"open fraud case {'YES' if cl['open_fraud_case'] else 'no'}, sales paused {'YES' if cl['sales_paused'] else 'no'}.\n"
        "Always call the firm 'the Bank'. Synthetic demo data.\n\n"
        f"SILOED PLAYS (what each book's API returns):\n{play_lines}\n\n"
        f"GOVERNED PACKET (Fabric IQ, JSON):\n{json.dumps(pk, separators=(',', ':'), default=str)}\n"
    )


# --------------------------------------------------------------------------- #
# Guardrails - deterministic, over the agent's output
# --------------------------------------------------------------------------- #
def sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    parts = re.split(r"^#{2,3}\s*(.+?)\s*#*\s*$", text, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        head = re.sub(r"[*_`]", "", parts[i]).strip().lower()
        for h in HEADINGS:
            if head.startswith(h.lower()[:14]):
                out.setdefault(h, parts[i + 1].strip())
                break
    return out


def client_message(secs: dict[str, str]) -> dict | None:
    raw = secs.get("Client message", "").strip()
    raw = re.sub(r"^```\w*\s*|\s*```$", "", raw).strip()
    if not raw or re.match(r"^\**\s*none\b", raw, re.I):
        return None
    sm = re.search(r"SUBJECT\**\s*:\s*\**\s*(.+)", raw, re.I)
    bm = re.search(r"BODY\**\s*:\s*\**\s*(.*)", raw, re.I | re.S)
    subject = sm.group(1).strip().strip("*") if sm else ""
    body = (bm.group(1) if bm else re.sub(r".*SUBJECT\**\s*:.*\n?", "", raw, flags=re.I)).strip()
    body = re.sub(r"^```\w*\s*|\s*```$", "", body).strip()
    return {"subject": subject, "body": body}


def none_reason(secs: dict[str, str]) -> str:
    raw = secs.get("Client message", "").strip()
    m = re.match(r"^\**\s*none\b\**\s*[-–—:]*\s*(.*)", raw, re.I | re.S)
    return (m.group(1).strip() if m else "").split("\n")[0][:240]


FIG = re.compile(r"(?<![\w.])\$\s?(\d[\d,]*(?:\.\d+)?)\s?([kKmM]\b)?|(?<![\w.$-])(\d+(?:\.\d+)?)\s?(%|bps\b|bp\b|basis points)")


def _figures(text: str) -> list[tuple[str, float, bool]]:
    out = []
    for m in FIG.finditer(text):
        if m.group(1):
            v = float(m.group(1).replace(",", ""))
            suf = (m.group(2) or "").lower()
            v *= 1000 if suf == "k" else 1_000_000 if suf == "m" else 1
            out.append((m.group(0).strip(), v, bool(suf)))
        else:
            out.append((m.group(0).strip(), float(m.group(3)), False))
    return out


def _packet_numbers(obj: Any, acc: list[float]) -> list[float]:
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, str):
        for n in re.findall(r"-?\d[\d,]*(?:\.\d+)?", obj):
            try:
                acc.append(float(n.replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _packet_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _packet_numbers(v, acc)
    return acc


def _traced(v: float, rounded: bool, nums: list[float]) -> bool:
    for p in nums:
        tol = max(0.051, abs(p) * 0.005)
        if rounded:
            tol = max(tol, abs(p) * 0.05)
        if v == int(v) and abs(p) >= 10:
            tol = max(tol, 0.5)
        if abs(p - v) <= tol or abs(abs(p) - v) <= tol:
            return True
    return False


SELL_COPY = B.SELLING + r"|\b(special offer|exclusive offer|switch to our|rewards|bonus|welcome offer|limit increase|upgrade)\b"
AUTONOMY = re.compile(r"\bI(?:\s+have|'ve)?\s+(sent|emailed|approved|declined|cancelled|canceled|froze|frozen|blocked|called|contacted|"
                      r"submitted|filed|reinstated|moved)\b", re.I)
INTERNAL_ID = re.compile(r"\b(CUST|RNW|DA|LN|IV|NC|CV|SC|CA|SE|IN|OFR)-\d{3,5}\b")
RATE_PROMISE = re.compile(r"\b(we (can|will|are able to) (offer|match|give you|beat)|you will (get|receive|pay))\b[^.\n]{0,60}\d+(\.\d+)?\s?%", re.I)


def guardrails(book: str, cid: str, text: str, secs: dict[str, str], msg: dict | None, pk: list[dict]) -> list[dict]:
    out: list[dict] = []

    def add(rule: str, name: str, ok: bool, detail: str, sev: str = "block") -> None:
        out.append({"rule": rule, "name": name, "status": "pass" if ok else sev, "detail": detail})

    cl = _client(cid)
    missing = [h for h in HEADINGS if h not in secs]
    add("Harness", "Output contract (7 sections)", not missing, "All sections present." if not missing else "Missing: " + ", ".join(missing), "warn")
    dec = secs.get("Decision", "")
    add("Harness", "One decision, owned", len(dec) >= 40, "Decision stated." if len(dec) >= 40 else "No clear decision - send back.", "warn")

    nums = _packet_numbers(pk, [])
    evidence = re.sub(r"(?<=\d),(?=\d)", "", secs.get("Evidence", ""))
    body_text = "\n".join(v for k, v in secs.items() if k != "Evidence") or text
    figs = _figures(body_text)
    traced, sourced, unsourced = 0, 0, []
    for raw, v, rounded in figs:
        if _traced(v, rounded, nums):
            traced += 1
        elif re.search(re.escape(re.sub(r"[^\d.]", "", raw.split()[0]) or raw), evidence):
            sourced += 1
        else:
            unsourced.append(raw)
    uniq = list(dict.fromkeys(unsourced))
    add("Harness", "Every figure traced to governed data or a cited source", not uniq,
        f"{traced} traced to Fabric IQ, {sourced} cited in Evidence." + (f" Unsourced: {', '.join(uniq[:6])}." if uniq else ""), "warn")

    cited = set(re.findall(r"\bRP-\d{3}\b", text))
    bogus = sorted(cited - KNOWN_POLICIES)
    add("RP-018", "Policy citations exist in Foundry IQ", bool(cited) and not bogus,
        f"Cited {', '.join(sorted(cited)) or 'none'}." + (f" Unknown: {', '.join(bogus)}." if bogus else ""), "warn" if not bogus else "block")
    m = AUTONOMY.search(text)
    add("Harness", "No autonomous action claimed", not m, f"Found: \"{m.group(0)}\" - the agent may only prepare." if m else "Prepares only.")

    if not msg:
        add("RP-016", "Client message", True, "None - the agent chose no email (" + (none_reason(secs) or "reason not given") + ").")
        return out
    copy = f"{msg['subject']}\n{msg['body']}"
    hits = [(why, mm.group(0)) for pat, _, why in C.BANNED for mm in [re.search(pat, copy, re.I)] if mm]
    add("RP-016", "Prohibited claims, internal data, bank names", not hits,
        "None found." if not hits else "; ".join(f"{w}: \"{t}\"" for w, t in hits[:4]))
    m = INTERNAL_ID.search(copy)
    add("RP-017", "No internal identifiers in client copy", not m, f"Found: \"{m.group(0)}\"" if m else "None found.")
    m = re.search(SELL_COPY, copy, re.I)
    if cl["sales_paused"]:
        add("RP-012", "Support/security before sales", not m,
            f"Sales are paused for this client - found \"{m.group(0)}\"." if m else "Sales paused and none present.")
    elif m and cl["email_consent"] != "Granted":
        add("RP-011", "Marketing consent", False, f"Promotional content (\"{m.group(0)}\") without email marketing consent.")
    m = RATE_PROMISE.search(copy)
    add("RP-002", "No rate or approval promised", not m, f"Found: \"{m.group(0)}\" - needs an approved exception." if m else "None found.")
    m = re.search(B.SECRETS, copy, re.I)
    add("RP-032", "Never asks for secrets", not m, f"Found: \"{m.group(0)}\"" if m else "No request for a PIN, passcode, password or code.")
    if book in ("security", "newcomers") or cl["open_fraud_case"]:
        ok = bool(re.search(r"never ask (you )?for your (PIN|passcode|password)", copy, re.I))
        add("RP-032", "'We will never ask for your PIN, passcode or password'", ok, "Present." if ok else "Required in any security-adjacent message.")
    if B.POSTURE.get(cid, {}).get("contact_email_changed_30d") == "Y":
        add("RP-032", "Verified channel", False, "Email changed during a security event - use the verified phone number, not email.")
    if re.search(r"\binsurance|cover(age)?\b|protection", copy, re.I) and book == "insurance":
        m = re.search(B.PRESSURE, copy, re.I)
        add("RP-031", "Insurance never presented as required", not m, f"Found: \"{m.group(0)}\"" if m else "None found.")
        ok = bool(re.search(r"\b(insurance|cover(age)?|it) is optional\b|\boptional\b", copy, re.I))
        add("RP-031", "Says insurance is optional", ok, "Present." if ok else "Every insurance message must say it is optional.", "warn")
    if book == "investing":
        m = re.search(B.RETURN_PROMISE, copy, re.I)
        add("RP-027", "No return promises", not m, f"Found: \"{m.group(0)}\"" if m else "None found.")
    if re.search(r"\bpre-?approved\b|\bapproved for\b", copy, re.I):
        add("RP-025", "No approval implied", False, "Credit is never described as approved before adjudication.")
    return out


def review_prompt(book: str, cid: str, msg: dict, cks: list[dict]) -> str:
    cl = _client(cid)
    det = "\n".join(f"- {k['rule']} {k['name']}: {k['status'].upper()} - {k['detail']}" for k in cks)
    return (
        f"Review this {BOOK_TITLE[book].lower()} client communication drafted by the mission agent before an advisor can use it. "
        f"Internal context (do NOT repeat to the client): wellness band {cl['wellness_band'] or 'n/a'}, email consent {cl['email_consent'] or 'n/a'}, "
        f"open fraud case {'yes' if cl['open_fraud_case'] else 'no'}, sales paused {'yes' if cl['sales_paused'] else 'no'}, "
        f"mission '{MISSIONS[book]['title']}'.\nDeterministic harness checks already run (authoritative):\n{det}\n\n"
        f"DRAFT SUBJECT: {msg['subject']}\nDRAFT BODY:\n{msg['body']}\n\n"
        "Return 'VERDICT: PASS', 'VERDICT: NEEDS FIXES' or 'VERDICT: BLOCKED' first (never weaker than the checks), then a findings table "
        f"(exact text, policy {', '.join(MISSIONS[book]['policies'])}, why), then a corrected draft in a ```text block if fixable. "
        "Refer to the firm as 'the Bank'. You review; you never send or approve."
    )


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
def _parse(frame: str) -> tuple[str, dict]:
    ev, data = "message", {}
    for line in frame.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                data = {}
    return ev, data


async def _mock_agent(book: str, cid: str, plays: list[dict]) -> AsyncGenerator[str, None]:
    """Offline stand-in so the harness UI can be exercised without Azure. Clearly labelled."""
    from .iq import iq_event, message_event, status_event, token_event
    yield status_event("Mock mode - no Azure calls")
    for iq, d in (("work", f'"{name_of(cid)}"'), ("foundry", f'"{MISSIONS[book]["policies"][0]}"'), ("web", '"market context"'), ("fabric", '"verify"')):
        await asyncio.sleep(0.25)
        yield sse("tool_call", {"iq": iq, "tool": f"mock-{iq}", "detail": d, "error": ""})
        yield iq_event(iq, "active", d)
    rows = "\n".join(f"| {p['book']}: {p['play_type']} / {p['play']} | Hold | Mock mode |" for p in plays[:4])
    text = (f"## Decision\nMOCK MODE - no agent ran. A real run would make one decision for {name_of(cid)} here.\n\n"
            "## What changed the decision\n- [Fabric IQ] mock\n\n## Conflicts resolved\n| Siloed play | Agent call | Why |\n|---|---|---|\n"
            f"{rows}\n\n## What we will not do\n- Anything - mock mode.\n\n## Advisor brief\n- Configure Foundry to run the mission.\n\n"
            "## Client message\nNONE - mock mode.\n\n## Evidence\n- none")
    for chunk in re.findall(r".{1,80}", text, re.S):
        yield token_event(chunk)
    yield message_event(text, [])
    yield sse("done", {"ok": True, "layers": ["work", "foundry", "web", "fabric"], "toolErrors": []})


async def run(user: User, book: str, cid: str) -> AsyncGenerator[str, None]:
    m = MISSIONS[book]
    run_id = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()

    def h(step: str, state: str, title: str, detail: str = "", **data: Any) -> str:
        return sse("harness", {"runId": run_id, "step": step, "state": state, "title": title, "detail": detail,
                               "ms": round((time.perf_counter() - t0) * 1000), "data": data})

    logger.info("AUDIT mission %s run %s by %s for %s", book, run_id, user.upn, cid)
    cl = _client(cid)
    yield h("plan", "done", "Plan fixed in code", f"Agent {settings.mission_agent_name} · layers Work, Foundry, Web, Fabric IQ · "
            f"policies {', '.join(m['policies'])} · may prepare, never act",
            steps=[t for _, t, _ in HARNESS], limits=["No sending, approving, declining, freezing or contacting",
                                                       "Governed packet is authoritative", "Web IQ is context only - never a client number",
                                                       "Client copy passes guardrails and the Compliance Reviewer", "A human decides"])
    yield h("packet", "running", "Assembling the governed packet")
    pk = packet(cid)
    plays = siloed_plays(cid)
    nfacts = sum(len(s["facts"]) for s in pk)
    yield h("packet", "done", f"{nfacts} governed facts from {len(pk) - 1} books · {len(plays)} siloed plays",
            "Deterministic. This is everything an API can return.", packet=pk, plays=plays, client=cl)

    yield h("agent", "running", "Agent investigating", f"{settings.mission_agent_name} - Work IQ, Foundry IQ, Web IQ, Fabric IQ")
    text, layers, tool_errors, calls = "", [], [], 0
    traced_layers: set = set()
    base_prompt = prompt(book, cid, pk, plays)
    hint = ""
    for attempt in (1, 2):
        held: list[str] = []
        src = _mock_agent(book, cid, plays) if settings.mock_mode else run_agent(
            user, base_prompt + hint, None, settings.mission_agent_name, trace=True)
        async for frame in src:
            ev, data = _parse(frame)
            if ev == "done":
                layers, tool_errors = data.get("layers", []) or [], data.get("toolErrors", []) or []
                continue
            if ev == "error":
                held.append(frame)
                tool_errors.append(f"{data.get('text', '')} {data.get('detail', '')}".strip())
                continue
            if ev == "message":
                text = data.get("text", "")
            if ev == "tool_call":
                calls += 1
                traced_layers.add(data.get("iq"))
            yield frame
        retryable = any(re.search(r"maximum allowed size|tool_user_error|exceeds", e, re.I) for e in tool_errors)
        throttled = any(re.search(r"\b429\b|rate.?limit", e, re.I) for e in tool_errors)
        if text or attempt == 2 or not (retryable or throttled):
            for f in held if not text else []:
                yield f
            break
        if throttled:
            yield h("agent", "running", "Harness recovery: model rate limit hit - waiting 20s, then retrying once", tool_errors[-1][:240])
            await asyncio.sleep(20)
            tool_errors = []
            continue
        yield h("agent", "running", "Harness recovery: a Work IQ search was too large - retrying with narrower searches",
                tool_errors[-1][:240])
        hint = RETRY_HINT
        tool_errors = []
    if not text:
        yield h("agent", "failed", "The agent returned no answer", "; ".join(tool_errors)[:400])
        yield sse("done", {"ok": False, "runId": run_id})
        return
    yield h("agent", "done", f"{calls or len(layers)} tool call(s) across {len(layers)} IQ layer(s)",
            ("Tool errors: " + "; ".join(tool_errors))[:400] if tool_errors else "", layers=layers, calls=calls)

    secs = sections(text)
    msg = client_message(secs)
    cks = guardrails(book, cid, text, secs, msg, pk)
    used = set(layers) | {t for t in traced_layers if t}
    for iq, name, why in (("work", "Colleague correspondence searched (Work IQ)", "the decision must consider what colleagues wrote"),
                          ("foundry", "Policy retrieved (Foundry IQ)", "policy must be retrieved, not recalled"),
                          ("fabric", "Governed figure verified (Fabric IQ)", "at least one packet figure must be re-verified")):
        cks.insert(2, {"rule": "RP-033", "name": name, "status": "pass" if iq in used else "warn",
                       "detail": "Called during the run." if iq in used else f"Not called - {why}."})
    v = B.verdict(cks)
    blocks = sum(c["status"] == "block" for c in cks)
    warns = sum(c["status"] == "warn" for c in cks)
    yield h("guardrails", "done", {"pass": "All guardrails passed", "needs_approval": f"{warns} warning(s) - human attention",
                                   "blocked": f"{blocks} block(s) - client copy cannot be used"}[v], "", checks=cks, verdict=v,
            clientMessage=msg)

    review_verdict = ""
    if not msg:
        yield h("review", "skipped", "No client message to review", none_reason(secs) or "The agent chose not to email.")
    elif v == "blocked":
        yield h("review", "skipped", "Blocked before review", "The guardrails blocked the client copy, so the reviewer is not asked to polish it.")
    else:
        yield h("review", "running", "Compliance Reviewer reading the client message", settings.compliance_agent_name)
        review = ""
        rsrc = _mock_review() if settings.mock_mode else run_agent(user, review_prompt(book, cid, msg, cks), None, settings.compliance_agent_name)
        async for frame in rsrc:
            ev, data = _parse(frame)
            if ev in ("token", "message", "error"):
                if ev == "message":
                    review = data.get("text", "")
                yield sse(f"review_{ev}", data)
        mv = re.search(r"VERDICT:\s*(PASS|NEEDS FIXES|BLOCKED)", review, re.I)
        review_verdict = mv.group(1).upper() if mv else ""
        yield h("review", "done" if review else "failed", f"Reviewer verdict: {review_verdict or 'none returned'}", verdict=review_verdict)

    RUNS[run_id] = {"book": book, "caseId": cid, "user": user.upn, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "guardrails": v, "review": review_verdict, "layers": layers, "calls": calls}
    while len(RUNS) > 200:
        RUNS.popitem(last=False)
    yield h("human", "waiting", "Awaiting your decision", f"{m['owner']} · approve, send back or escalate")
    yield sse("done", {"ok": True, "runId": run_id})


async def _mock_review() -> AsyncGenerator[str, None]:
    from .iq import message_event
    yield message_event("VERDICT: NEEDS FIXES\n\nMock mode - the Compliance Reviewer did not run.", [])


def decide(user: User, book: str, run_id: str, case_id: str, decision: str, note: str) -> dict:
    r = RUNS.get(run_id, {})
    rec = {"runId": run_id, "book": book, "caseId": case_id, "decision": decision, "note": note[:500], "by": user.upn,
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "guardrails": r.get("guardrails", ""),
           "review": r.get("review", ""), "runFound": bool(r)}
    if r and (r["book"] != book or r["caseId"] != case_id):
        raise ValueError("Run does not match this book and case.")
    AUDIT.appendleft(rec)
    logger.info("AUDIT mission decision %s", json.dumps(rec))
    return rec


def audit(book: str | None = None) -> list[dict]:
    return [a for a in AUDIT if not book or a["book"] == book][:25]
