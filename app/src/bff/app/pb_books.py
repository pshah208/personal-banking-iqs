"""Product books - Everyday banking, Borrowing, Investing, Newcomers, Insurance, Security (one deterministic engine).

Data = governed Fabric IQ book tables (bundled in books_data). Every client in
these books is also in the mortgage book (CUST-10xx) or the cards book
(CUST-20xx), or is a newcomer-only client (CUST-30xx, Newcomers and Security
books), and carries the same wellness band, marketing consent and TDS, so a
support-first client is support-first everywhere. Plays are ranked Support >
Protect > Retain > Grow; each is gated by deterministic rules (consent RP-011,
support-first RP-012, affordability RP-013, overdraft consent RP-024, secured
lending RP-025, rate notices RP-026, KYC RP-027, registered plans RP-028,
newcomer packages RP-029, transfer cost disclosure RP-030, optional insurance
RP-031, security before sales RP-032) that checks() re-derives from the data for
any draft. SYNTHETIC demo data.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .books_data import BOOKS as D
from .cards_data import CARDS
from .pb_customers import BANNED

AS_OF = D["as_of"]
MONTHS = D["months"]
PRIME = D["prime_rate_pct"]
PACKAGES = D["packages"]
TDS_LIMIT = 44.0
ORDER = {"Support": 0, "Protect": 1, "Retain": 2, "Grow": 3, None: 4}
FAB, FOUNDRY = "Fabric IQ", "Foundry IQ"


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


# --------------------------------------------------------------------------- #
# Indexes
# --------------------------------------------------------------------------- #
CLIENT = {a["customer_id"]: a for a in D["deposit_accounts"]}  # every mortgage / card client has exactly one deposit relationship
NJ = {j["customer_id"]: j for j in D["newcomer_journey"]}
for _j in D["newcomer_journey"]:
    CLIENT.setdefault(_j["customer_id"], _j)  # newcomer-only clients CUST-30xx
ROOM = {r["customer_id"]: r for r in D["registered_room"]}
CARD = {a["customer_id"]: a for a in CARDS["card_accounts"]}
CAND = {c["customer_id"]: c for c in D["debt_consolidation_candidates"]}
FLOWS = _group(D["deposit_flows_monthly"], "account_id")
FACS_BY_CUST = _group(D["credit_facilities"], "customer_id")
HOLD_BY_CUST = _group(D["investment_accounts"], "customer_id")
TX = _group(D["transfers_out_monthly"], "account_id")
POL_BY_CUST = _group(D["insurance_policies"], "customer_id")
COVER = {g["customer_id"]: g for g in D["coverage_gaps"]}
EV_BY_CUST = _group(D["security_events"], "customer_id")
POSTURE = {s["customer_id"]: s for s in D["customer_security_posture"]}
OPEN_CASE = {cid for cid, s in POSTURE.items() if s["open_events"]}
SERIES = D["_series"]


def _investing_rows() -> tuple[dict[str, dict], dict[str, str]]:
    rows, alias = {}, {}
    for cid, holds in HOLD_BY_CUST.items():
        prim = max(holds, key=lambda a: a["market_value_cad"])
        gic90 = [a for a in holds if a["holding_type"] == "GIC" and a["days_to_maturity"] != "" and int(a["days_to_maturity"]) <= 90]
        plans = sorted({a["plan"] for a in holds}, key=["TFSA", "RRSP", "FHSA", "RESP", "Non-registered"].index)
        rows[prim["account_id"]] = {**{k: prim[k] for k in ("account_id", "customer_id", "customer_name", "segment", "branch", "linked_mortgage",
                                                           "linked_cards", "risk_profile", "kyc_last_updated", "kyc_age_months", "kyc_status",
                                                           "wellness_band", "email_consent", "tds_renewal_pct")},
                                    "plans": ", ".join(plans), "holdings": len(holds), "total_value": sum(a["market_value_cad"] for a in holds),
                                    "gic_maturing_90d": sum(a["market_value_cad"] for a in gic90),
                                    "tfsa_room_unused_cad": ROOM[cid]["tfsa_room_unused_cad"],
                                    "cesg_missed_per_year_cad": ROOM[cid]["cesg_missed_per_year_cad"]}
        for a in holds:
            alias[a["account_id"]] = prim["account_id"]
    return rows, alias


_INV_ROWS, _INV_ALIAS = _investing_rows()

BOOK = {
    "banking": {
        "title": "Everyday banking", "tagline": "Chequing packages, fees, payroll and deposit flows - support first, then keep the primary relationship.",
        "tables": ["deposit_accounts", "deposit_flows_monthly", "banking_next_actions"],
        "policies": ["RP-011", "RP-012", "RP-016", "RP-018", "RP-023", "RP-024"],
        "accounts": {a["account_id"]: a for a in D["deposit_accounts"]}, "alias": {}, "actions": D["banking_next_actions"],
        "plays": [("Overdraft/NSF support", "Support", "RP-024", "NSF item or 10+ overdraft days in 3 months, or Vulnerable band - fee refunds and budgeting first."),
                  ("Primary banking at risk", "Retain", "RP-018", "10%+ of payroll moving to another institution 2 months running, or payroll falling - relationship review."),
                  ("Package fit", "Retain", "RP-023", "Paying more than the lowest-cost package for recorded usage - recommend it even if fee revenue falls."),
                  ("Package fit", "Grow", "RP-023", "A higher package would cost less for this usage (waiver met, extra transactions avoided) - promotional, consent needed."),
                  ("Savings sweep", "Grow", "RP-011", "Chequing balance above $15k and no savings account - consent needed."),
                  ("Bundle completion", "Grow", "RP-011", "Holds 2 of chequing / savings / card - consent needed, suppressed for Vulnerable, card offers need affordability.")],
        "sign": "Kind regards,\nYour everyday banking team",
    },
    "borrowing": {
        "title": "Borrowing", "tagline": "Lines of credit and loans - arrears support, cheaper ways to carry card debt, maturities and rate-change notices.",
        "tables": ["credit_facilities", "debt_consolidation_candidates", "borrowing_next_actions"],
        "policies": ["RP-011", "RP-012", "RP-013", "RP-014", "RP-016", "RP-025", "RP-026"],
        "accounts": {a["account_id"]: a for a in D["credit_facilities"]}, "alias": {}, "actions": D["borrowing_next_actions"],
        "plays": [("Arrears support", "Support", "RP-014", "A facility is past due - hardship options and Client Assistance."),
                  ("Debt consolidation", "Support", "RP-025", "Persistent card debt or Vulnerable - consolidation only where affordable, Client Assistance for hardship."),
                  ("Prime-rate change notice", "Protect", "RP-026", "Variable line of $10k+ - notice within 30 days of a prime change with the payment impact; never a sales message."),
                  ("Auto loan maturing", "Retain", "RP-011", "Auto loan pays off within 90 days - maturity check-in (promotional, consent needed)."),
                  ("Debt consolidation", "Grow", "RP-025", "Revolving card balance a cheaper facility could carry - TDS within 44% (mortgage) or payment falls; consent needed."),
                  ("Home-equity re-advance", "Grow", "RP-025", "Secured line well used or a life event - combined LTV within 65%, TDS within 44%, consent, not for Vulnerable.")],
        "sign": "Kind regards,\nYour lending team",
    },
    "investing": {
        "title": "Investing", "tagline": "Registered plans, GIC maturities and KYC - only a licensed advisor recommends, never with a return promise.",
        "tables": ["investment_accounts", "registered_room", "investing_next_actions"],
        "policies": ["RP-011", "RP-012", "RP-016", "RP-027", "RP-028"],
        "accounts": _INV_ROWS, "alias": _INV_ALIAS, "actions": D["investing_next_actions"],
        "plays": [("KYC refresh required", "Protect", "RP-027", "KYC older than 36 months - every recommendation is paused until it is refreshed."),
                  ("GIC maturing", "Retain", "RP-027", "A GIC matures within 90 days - maturity conversation with a licensed advisor."),
                  ("RESP grant left on the table", "Grow", "RP-028", "Dependents and no RESP - up to $500 per child per year of grant not collected."),
                  ("FHSA for first-time buyers", "Grow", "RP-028", "Renters only (mortgage clients are not eligible), age 18-70, no FHSA yet."),
                  ("Idle cash to TFSA", "Grow", "RP-028", "More than $20k in taxable savings and more than $10k of TFSA room.")],
        "sign": "Kind regards,\nYour investment advisory team",
    },
    "newcomers": {
        "title": "Newcomers & money transfer", "tagline": "New to Canada clients - fee-free periods, credit building and the true cost of sending money home, scam-safe.",
        "tables": ["newcomer_journey", "transfers_out_monthly", "newcomers_next_actions"],
        "policies": ["RP-011", "RP-012", "RP-013", "RP-016", "RP-022", "RP-029", "RP-030", "RP-032"],
        "accounts": {j["account_id"]: j for j in D["newcomer_journey"]}, "alias": {}, "actions": D["newcomers_next_actions"],
        "plays": [("Remittance scam awareness", "Protect", "RP-030", "Frequent transfers to new recipients on a scam-alert corridor - scam education and recipient checks, never a sale."),
                  ("Package expiry", "Retain", "RP-029", "Fee-free newcomer period ends within 60 days - explain the lowest-cost next package in plain language."),
                  ("Cheaper money transfer", "Retain", "RP-030", "Already sends with the Bank - fewer, larger transfers cut fees; full cost disclosed."),
                  ("Cheaper money transfer", "Grow", "RP-030", "Pays another provider more in fees + FX margin - show the annual saving with total cost disclosed; consent needed."),
                  ("Credit-building next step", "Grow", "RP-029", "Secured card 12+ months paid on time - unsecured card; consent needed, not for Vulnerable, paused during a fraud case."),
                  ("Mortgage readiness", "Grow", "RP-013", "Permanent resident, 24+ month credit file, income $70k+, renting - affordability first; consent needed.")],
        "sign": "Kind regards,\nYour newcomer banking team",
        "work_topic": "newcomer clients - newcomer package expiries, credit building, money transfers and remittance scams",
        "web": "Using the public web only, summarise current international money-transfer fees and exchange-rate margins from Canada (e.g. to India, the Philippines, Nigeria, Mexico, China) and current newcomer bank-account offers in Canada (issuer-neutral, dated, with sources). Do not use internal data.",
        "web_short": "international money-transfer fees and exchange-rate margins, and newcomer bank-account offers",
    },
    "insurance": {
        "title": "Insurance", "tagline": "Creditor and optional insurance - optional, never a condition of credit; affordability and suitability first.",
        "tables": ["insurance_policies", "coverage_gaps", "insurance_next_actions"],
        "policies": ["RP-011", "RP-012", "RP-013", "RP-016", "RP-031", "RP-032"],
        "accounts": {g["account_id"]: g for g in D["coverage_gaps"]},
        "alias": {q["policy_id"]: f"CV-{q['customer_id'][5:]}" for q in D["insurance_policies"]}, "actions": D["insurance_next_actions"],
        "plays": [("Premium affordability review", "Support", "RP-031", "Stretched or Vulnerable and paying optional creditor premiums - review need and cost; never auto-cancel."),
                  ("Travel cover check", "Protect", "RP-031", "Travel-heavy card spend on a card without travel insurance - information only, no sale."),
                  ("Lapsed policy", "Retain", "RP-031", "Cover lapsed in the last 90 days - check it was intended; insurance is optional."),
                  ("Coverage gap on renewing mortgage", "Grow", "RP-031", "Dependents and mortgage life cover below the balance - optional cover; consent, TDS within 44%, not for Vulnerable.")],
        "sign": "Kind regards,\nYour insurance team (authorised insurance representatives)",
        "work_topic": "creditor and optional insurance - complaints about cover being 'required', lapsed policies and premium affordability",
        "web": "Using the public web only, summarise current Financial Consumer Agency of Canada (FCAC) consumer guidance on creditor insurance (mortgage life and disability, line of credit and card balance protection) and typical premium levels (issuer-neutral, dated, with sources). Do not use internal data.",
        "web_short": "creditor-insurance consumer guidance (FCAC) and typical premiums",
    },
    "security": {
        "title": "Security & fraud", "tagline": "Cross-book view of fraud alerts and scams - protection and support only; security comes before sales.",
        "tables": ["security_events", "customer_security_posture", "security_next_actions"],
        "policies": ["RP-012", "RP-016", "RP-017", "RP-022", "RP-032"],
        "accounts": {s["account_id"]: s for s in D["customer_security_posture"]},
        "alias": {e["event_id"]: f"SC-{e['customer_id'][5:]}" for e in D["security_events"]}, "actions": D["security_next_actions"],
        "plays": [("Scam coaching", "Support", "RP-032", "Stretched or Vulnerable client with a scam-type event - coaching, trusted contact person, hold-and-verify."),
                  ("Open fraud case follow-up", "Protect", "RP-032", "Open high-severity event - verified call-back; email blocked if contact details changed."),
                  ("Security check-in", "Protect", "RP-022", "Medium-severity events, or sign-in activity without 2-step verification."),
                  ("Enable alerts & 2-step", "Protect", "RP-022", "Transaction alerts or 2-step verification off.")],
        "sign": "Kind regards,\nYour account security team",
        "work_topic": "fraud and scams - phishing waves, remittance scams, held e-Transfers and older clients",
        "web": "Using the public web only, summarise the current scam alerts from the Canadian Anti-Fraud Centre and Canadian banks (phishing texts, bank-investigator scams, e-Transfer and remittance scams), with dates and sources. Do not use internal data.",
        "web_short": "scam alerts from the Canadian Anti-Fraud Centre and banks",
    },
}
for _b in BOOK.values():
    _b["by_account"] = _group(_b["actions"], "account_id")


def books() -> list[dict[str, Any]]:
    return [{"book": k, "title": v["title"], "tagline": v["tagline"], "tables": v["tables"], "policies": v["policies"]} for k, v in BOOK.items()]


def resolve(book: str, aid: str) -> str | None:
    b = BOOK.get(book)
    if not b:
        return None
    aid = b["alias"].get(aid, aid)
    return aid if aid in b["accounts"] else None


def _plays(book: str, aid: str) -> list[dict]:
    return [{**p, "recommendation": p["recommended_product"]} for p in BOOK[book]["by_account"].get(aid, [])]


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #
COLUMNS = {
    "banking": [("package", "Package", "text"), ("monthly_fee", "Monthly fee", "cad"), ("avg_chequing_balance", "Avg chequing", "cad"),
                ("savings_balance", "Savings", "cad"), ("fees_charged_12m", "Fees 12m", "cad"), ("outflow_share_pct", "Payroll moving out", "pct"),
                ("nsf_3m", "NSF 3m", "number"), ("overdraft_days_3m", "Overdraft days 3m", "number"), ("primary_banking", "Primary", "text")],
    "borrowing": [("facility_type", "Facility", "text"), ("balance_cad", "Balance", "cad"), ("limit_or_original_cad", "Limit / original", "cad"),
                  ("rate_pct", "Rate", "pct"), ("utilisation_pct", "Utilisation", "pct"), ("monthly_payment_cad", "Payment", "cad"),
                  ("days_past_due", "Days past due", "number"), ("maturity_date", "Matures", "text")],
    "investing": [("plans", "Plans", "text"), ("total_value", "Total value", "cad"), ("gic_maturing_90d", "GICs maturing 90d", "cad"),
                  ("risk_profile", "Risk profile", "text"), ("kyc_age_months", "KYC age (months)", "number"),
                  ("tfsa_room_unused_cad", "TFSA room", "cad"), ("cesg_missed_per_year_cad", "RESP grant missed / yr", "cad")],
    "newcomers": [("months_in_canada", "Months in Canada", "number"), ("status", "Status", "text"),
                  ("credit_building_stage", "Credit stage", "text"), ("credit_file_months", "Credit file (months)", "number"),
                  ("newcomer_package_active", "Fee-free package", "text"), ("transfer_provider", "Sends with", "text"),
                  ("sent_12m_cad", "Sent abroad 12m", "cad"), ("transfer_cost_12m_cad", "Transfer cost 12m", "cad"),
                  ("new_recipients_90d", "New recipients 90d", "number")],
    "insurance": [("policy_types", "Active cover", "text"), ("mortgage_balance_cad", "Mortgage balance", "cad"),
                  ("mortgage_life_coverage_cad", "Life cover", "cad"), ("gap_amount_cad", "Coverage gap", "cad"),
                  ("dependents", "Dependents", "number"), ("optional_premiums_monthly_cad", "Optional premiums / mo", "cad"),
                  ("travel_spend_12m_cad", "Travel spend 12m", "cad")],
    "security": [("events_90d", "Events 90d", "number"), ("open_events", "Open", "number"), ("high_events", "High", "number"),
                 ("latest_event", "Latest event", "text"), ("latest_event_date", "Latest date", "text"),
                 ("two_step_verification", "2-step", "text"), ("alerts_enabled", "Alerts", "text"),
                 ("trusted_contact_on_file", "Trusted contact", "text"), ("amount_at_risk_cad", "Open amount", "cad")],
}


def _flags(book: str, a: dict) -> list[str]:
    cid = a["customer_id"]
    c, f = CLIENT[cid], []
    if c["wellness_band"] == "Vulnerable":
        f.append("Support first")
    if c["tds_renewal_pct"] != "" and _num(c["tds_renewal_pct"]) > TDS_LIMIT:
        f.append("Above TDS guideline")
    if CARD.get(cid, {}).get("behaviour") == "Persistent debt":
        f.append("Persistent card debt")
    if book == "banking":
        if _num(a["outflow_share_pct"]) >= 10:
            f.append("Deposit flight")
        if a["nsf_3m"] or a["overdraft_days_3m"] >= 10:
            f.append("NSF / overdraft")
        if a["best_fit_package"] != a["package"] and a["package_cost_12m"] - a["best_fit_cost_12m"] >= 120:
            f.append("Overpaying fees")
    elif book == "borrowing":
        if a["days_past_due"]:
            f.append("Past due")
        if a["rate_type"] == "Variable":
            f.append("Variable rate")
        if a["days_to_maturity"] != "" and int(a["days_to_maturity"]) <= 90:
            f.append("Matures in 90 days")
    elif book == "investing":
        if a["kyc_status"] == "Stale":
            f.append("KYC stale")
        if a["gic_maturing_90d"]:
            f.append("GIC maturing 90d")
        if ROOM[cid]["fhsa_eligible"] == "Y":
            f.append("Renter - FHSA eligible")
    elif book == "newcomers":
        if a["newcomer_package_active"] == "Y" and int(a["days_to_package_expiry"]) <= 60:
            f.append("Fee-free period ending")
        if a["credit_building_stage"] in ("No file", "Secured card"):
            f.append("Building credit")
        if a["transfer_provider"] == "Other provider":
            f.append("Sends with another provider")
        if a["scam_risk_sender"] == "Y":
            f.append("Scam-risk sender")
    elif book == "insurance":
        if a["linked_mortgage"] == "Y" and a["dependents"] and a["gap_amount_cad"] > 0:
            f.append("Life-cover gap")
        if a["lapsed_90d"]:
            f.append("Lapsed in 90 days")
        if a["optional_premiums_monthly_cad"] and c["wellness_band"] in ("Vulnerable", "Stretched"):
            f.append("Premiums under strain")
    else:
        if a["open_high_events"]:
            f.append("Open high-severity case")
        if a["contact_email_changed_30d"] == "Y":
            f.append("Contact details changed")
        if a["two_step_verification"] == "N":
            f.append("No 2-step")
        if a["scam_type_events"]:
            f.append("Scam exposure")
    if book != "security" and cid in OPEN_CASE:
        f.append("Open fraud case - sales paused")
    return f


def _product(book: str, a: dict) -> str:
    if book == "banking":
        return f"{a['package']} package"
    if book == "borrowing":
        return a["facility_type"]
    if book == "investing":
        return a["plans"]
    if book == "newcomers":
        return f"{a['credit_building_stage']} - {a['status']}"
    if book == "insurance":
        return a["policy_types"]
    return f"{a['events_90d']} event(s) - latest {a['latest_event'].lower()}"


def _row(book: str, a: dict) -> dict[str, Any]:
    plays = _plays(book, a["account_id"])
    top = plays[0] if plays else None
    return {"account_id": a["account_id"], "customer_id": a["customer_id"], "customer_name": a["customer_name"], "segment": a["segment"],
            "branch": a["branch"], "product": _product(book, a), "wellness_band": a["wellness_band"], "email_consent": a["email_consent"],
            "linked_mortgage": a["linked_mortgage"], "linked_cards": a["linked_cards"], "flags": _flags(book, a),
            "values": {k: a[k] for k, _, _ in COLUMNS[book]},
            "top_play": {k: top[k] for k in ("rank", "play_type", "play", "recommendation", "rationale", "eligibility", "value_at_stake_cad", "policy")}
            if top else None, "plays": len(plays)}


def accounts(book: str) -> dict[str, Any] | None:
    b = BOOK.get(book)
    if not b:
        return None
    rows = [_row(book, a) for a in b["accounts"].values()]
    rows.sort(key=lambda r: (ORDER[r["top_play"]["play_type"] if r["top_play"] else None],
                             -(r["top_play"]["value_at_stake_cad"] if r["top_play"] else 0), r["account_id"]))
    return {"book": book, "columns": [{"key": k, "label": l, "format": f} for k, l, f in COLUMNS[book]], "accounts": rows}


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
def _kpi(i: str, label: str, value: Any, fmt: str, hint: str) -> dict:
    return {"id": i, "label": label, "value": value, "format": fmt, "hint": hint, "source": FAB}


def _chart(i: str, title: str, kind: str, data: list[tuple[str, float]]) -> dict:
    return {"id": i, "title": title, "kind": kind, "source": FAB, "data": [{"label": l, "value": round(v)} for l, v in data]}


def overview(book: str) -> dict[str, Any] | None:
    b = BOOK.get(book)
    if not b:
        return None
    acts = b["actions"]
    accs = list(b["accounts"].values())
    by_play = Counter((a["play"], a["play_type"]) for a in acts)
    el = Counter((a["play"], a["play_type"]) for a in acts if a["eligibility"] == "Eligible")
    plays = [{"play": p, "play_type": t, "eligible": el[(p, t)], "blocked": by_play[(p, t)] - el[(p, t)], "policy": pol, "explain": ex}
             for p, t, pol, ex in b["plays"]]
    pcount = lambda name: sum(1 for a in acts if a["play"] == name)  # noqa: E731
    stack = _chart("plays", "Plays by type", "stack", [(t, sum(1 for a in acts if a["play_type"] == t)) for t in ("Support", "Protect", "Retain", "Grow")])
    if book == "banking":
        dep = sum(a["avg_chequing_balance"] + a["savings_balance"] for a in accs)
        by_month = defaultdict(float)
        for r in D["deposit_flows_monthly"]:
            by_month[r["month"]] += r["end_balance"]
        saving = sum(a["package_cost_12m"] - a["best_fit_cost_12m"] for a in accs if a["best_fit_package"] != a["package"]
                     and a["package_cost_12m"] - a["best_fit_cost_12m"] >= 120)
        kpis = [_kpi("clients", "Clients", len(accs), "number", "One everyday-banking relationship per client (mortgage and card-only)."),
                _kpi("deposits", "Deposit balances", round(dep), "cad", "Average chequing plus savings balances."),
                _kpi("primary", "Primary banking", round(100 * sum(a["primary_banking"] == "Y" for a in accs) / len(accs), 1), "pct",
                     "Share of clients whose payroll lands here."),
                _kpi("at_risk", "Primary banking at risk", pcount("Primary banking at risk"), "number", "Payroll moving out or falling (RP-018)."),
                _kpi("flight", "Deposit-flight cohort", sum(_num(a["outflow_share_pct"]) >= 10 for a in accs), "number",
                     "Same cohort as the mortgage book: 10%+ of payroll moving to another institution."),
                _kpi("fees", "Fees charged 12m", round(sum(a["fees_charged_12m"] for a in accs)), "cad", "Package, transaction, NSF and overdraft fees."),
                _kpi("nsf", "NSF / overdraft clients", pcount("Overdraft/NSF support"), "number", "Support first (RP-024)."),
                _kpi("saving", "Fee savings available", round(saving), "cad", "Annual saving if overpaying clients moved to the lowest-cost fit (RP-023).")]
        charts = [_chart("balances", "Month-end chequing balances", "bars", sorted(by_month.items())),
                  _chart("packages", "Clients by package", "hbars", Counter(a["package"] for a in accs).most_common()), stack]
        web = "Using the public web only, summarise current Canadian chequing-package monthly fees, fee-waiver balances and high-interest savings rates (issuer-neutral, dated, with sources). Do not use internal data."
    elif book == "borrowing":
        var = [a for a in accs if a["rate_type"] == "Variable"]
        kpis = [_kpi("facilities", "Facilities", len(accs), "number", f"{len({a['customer_id'] for a in accs})} clients."),
                _kpi("balances", "Balances", round(sum(a["balance_cad"] for a in accs)), "cad", "Outstanding lines and loans."),
                _kpi("variable", "Variable-rate balances", round(sum(a["balance_cad"] for a in var)), "cad", f"Priced off prime {PRIME}% (RP-026)."),
                _kpi("bp25", "+25bp payment impact / month", round(sum(a["balance_cad"] for a in var) * 0.0025 / 12), "cad", "Illustration only, across variable lines."),
                _kpi("past_due", "Past due", sum(a["days_past_due"] > 0 for a in accs), "number", "Arrears support first (RP-014)."),
                _kpi("consol", "Consolidation candidates", len(D["debt_consolidation_candidates"]), "number", "Persistent-debt / revolving card balances."),
                _kpi("saved", "Consolidation interest saved / yr", sum(c["interest_saved_annual_cad"] for c in D["debt_consolidation_candidates"]), "cad",
                     "If every candidate moved to the cheaper facility (before gates)."),
                _kpi("auto90", "Auto loans maturing 90d", pcount("Auto loan maturing"), "number", "Retain conversation.")]
        bt = defaultdict(float)
        for a in accs:
            bt[a["facility_type"]] += a["balance_cad"]
        charts = [_chart("by_type", "Balance by facility type", "hbars", sorted(bt.items(), key=lambda x: -x[1])),
                  _chart("utilisation", "Lines by utilisation", "bars", [(lbl, sum(1 for a in var if lo <= a["utilisation_pct"] < hi))
                                                                          for lbl, lo, hi in (("<25%", 0, 25), ("25-50%", 25, 50), ("50-75%", 50, 75), ("75%+", 75, 1000))]),
                  stack]
        web = "Using the public web only, summarise the current Canadian prime rate, the next Bank of Canada announcement date, and typical unsecured line-of-credit, home-equity line and auto-loan rates (issuer-neutral, dated, with sources). Do not use internal data."
    elif book == "investing":
        holds = D["investment_accounts"]
        kpis = [_kpi("clients", "Investing clients", len(accs), "number", f"{len(holds)} holdings."),
                _kpi("aum", "Assets", round(sum(a["market_value_cad"] for a in holds)), "cad", "Market value across plans."),
                _kpi("gic90", "GICs maturing 90d", round(sum(a["gic_maturing_90d"] for a in accs)), "cad", "Maturity conversations (RP-027)."),
                _kpi("kyc", "KYC stale", sum(a["kyc_status"] == "Stale" for a in accs), "number", "Older than 36 months - recommendations paused (RP-027)."),
                _kpi("tfsa", "TFSA room unused", round(sum(r["tfsa_room_unused_cad"] for r in ROOM.values() if r["customer_id"] in HOLD_BY_CUST)), "cad", "Room on record."),
                _kpi("resp", "RESP grant missed / yr", round(sum(r["cesg_missed_per_year_cad"] for r in ROOM.values())), "cad",
                     "Across all clients with dependents and no RESP (RP-028)."),
                _kpi("fhsa", "FHSA eligible, not opened", sum(r["fhsa_eligible"] == "Y" and r["fhsa_opened"] == "N" for r in ROOM.values()), "number",
                     "Renters only - mortgage clients are not eligible.")]
        bp = defaultdict(float)
        for a in holds:
            bp[a["plan"]] += a["market_value_cad"]
        charts = [_chart("by_plan", "Assets by plan", "hbars", sorted(bp.items(), key=lambda x: -x[1])),
                  _chart("by_holding", "Holdings by type", "bars", Counter(a["holding_type"] for a in holds).most_common()), stack]
        web = "Using the public web only, summarise current Canadian GIC rates by term (1-5 years), and the 2026 TFSA, RRSP, FHSA limits and the CESG grant rules (issuer-neutral, dated, with sources). Do not use internal data."
    elif book == "newcomers":
        send = [a for a in accs if a["sends_abroad"] == "Y"]
        other = [a for a in send if a["transfer_provider"] == "Other provider"]
        only = sum(a["customer_id"].startswith("CUST-3") for a in accs)
        kpis = [_kpi("clients", "Newcomer clients", len(accs), "number", f"{len(accs) - only} also in the mortgage / card books, {only} newcomer-only."),
                _kpi("senders", "Send money abroad", len(send), "number", f"{len(other)} use another provider."),
                _kpi("sent", "Sent abroad 12m", round(sum(a["sent_12m_cad"] for a in send)), "cad", "All corridors, all providers."),
                _kpi("cost", "Transfer cost 12m", round(sum(a["transfer_cost_12m_cad"] for a in send)), "cad", "Fees plus FX margin - the total cost (RP-030)."),
                _kpi("saving", "Saving with the Bank / yr", round(sum(a["transfer_cost_12m_cad"] - a["bank_equivalent_cost_12m_cad"] for a in other)), "cad",
                     "What clients using another provider would save at the Bank's fee and margin."),
                _kpi("expiring", "Fee-free periods ending 60d", pcount("Package expiry"), "number", "Explain the next package before it starts (RP-029)."),
                _kpi("credit", "Ready for an unsecured card", pcount("Credit-building next step"), "number", "Secured card 12+ months on time (RP-029)."),
                _kpi("scam", "Scam-risk senders", sum(a["scam_risk_sender"] == "Y" for a in accs), "number", "Frequent transfers to new recipients on a watch-list corridor (RP-030).")]
        cor = defaultdict(float)
        for a in send:
            cor[a["corridor"]] += a["sent_12m_cad"]
        charts = [_chart("stage", "Clients by credit-building stage", "hbars",
                         [(s, sum(a["credit_building_stage"] == s for a in accs)) for s in ("No file", "Secured card", "Unsecured card", "Established")]),
                  _chart("corridors", "Money sent by corridor (12m)", "hbars", sorted(cor.items(), key=lambda x: -x[1])), stack]
        web = b["web"]
    elif book == "insurance":
        pols = D["insurance_policies"]
        active = [q for q in pols if q["status"] == "Active"]
        gap = [a for a in accs if a["linked_mortgage"] == "Y" and a["dependents"] and a["gap_amount_cad"] > 0]
        kpis = [_kpi("clients", "Clients", len(accs), "number", "Mortgage clients plus clients with a line or loan."),
                _kpi("active", "Active policies", len(active), "number", f"{len(pols)} policies on record incl. lapsed and declined."),
                _kpi("premiums", "Optional premiums / month", round(sum(a["optional_premiums_monthly_cad"] for a in accs)), "cad",
                     "Creditor insurance: mortgage life and disability, line and card protection."),
                _kpi("gap_clients", "Families with a life-cover gap", len(gap), "number", "Dependents and mortgage life cover below the balance."),
                _kpi("gap", "Life-cover gap", round(sum(a["gap_amount_cad"] for a in gap)), "cad", "Mortgage balance not covered, for those families."),
                _kpi("lapsed", "Lapsed in 90 days", sum(a["lapsed_90d"] for a in accs), "number", "Check each lapse was intended."),
                _kpi("review", "Premium reviews (support)", pcount("Premium affordability review"), "number", "Stretched / Vulnerable clients paying optional premiums."),
                _kpi("declined", "Declined at origination", sum(q["status"] == "Declined" for q in pols), "number", "Optional - declining never affects credit (RP-031).")]
        bt = Counter(q["policy_type"] for q in active)
        charts = [_chart("by_type", "Active policies by type", "hbars", bt.most_common()),
                  _chart("gap_window", "Life-cover gap by renewal window", "bars",
                         [(lbl, sum(a["gap_amount_cad"] for a in gap if lo <= int(a["days_to_renewal"]) < hi))
                          for lbl, lo, hi in (("<=90 days", -10000, 91), ("91-180 days", 91, 181), ("181+ days", 181, 100000))]), stack]
        web = b["web"]
    else:
        evs = D["security_events"]
        kpis = [_kpi("clients", "Clients with a security event", len(accs), "number", "Across every book (cards, banking, newcomers) - last 90 days."),
                _kpi("events", "Events 90d", len(evs), "number", f"{sum(e['severity'] == 'High' for e in evs)} high severity."),
                _kpi("open", "Open events", sum(a["open_events"] for a in accs), "number", "Sales paused in the selling books while a case is open (RP-032)."),
                _kpi("open_high", "Open high-severity cases", sum(a["open_high_events"] > 0 for a in accs), "number", "Verified call-back first."),
                _kpi("at_risk", "Amount in open cases", round(sum(a["amount_at_risk_cad"] for a in accs)), "cad", "Disputed or held amounts."),
                _kpi("no2sv", "Without 2-step verification", round(100 * sum(a["two_step_verification"] == "N" for a in accs) / max(1, len(accs)), 1), "pct",
                     "Share of clients with an event."),
                _kpi("held", "Large e-Transfers held and verified", sum(e["event_type"] == "Large e-Transfer to new payee" for e in evs), "number",
                     "Hold-and-verify on large transfers to new payees (RP-032)."),
                _kpi("channel", "Email blocked - contact changed", sum(a["contact_email_changed_30d"] == "Y" for a in accs), "number",
                     "Contact only via verified channels (RP-032).")]
        charts = [_chart("by_type", "Events by type (90d)", "hbars", Counter(e["event_type"] for e in evs).most_common()),
                  _chart("by_month", "Events by month", "bars", [(m, sum(e["event_date"][:7] == m for e in evs)) for m in MONTHS[-4:]]), stack]
        web = b["web"]
    topic = b.get("work_topic", f"{b['title'].lower()} clients, complaints or campaigns")
    return {"book": book, "title": b["title"], "tagline": b["tagline"], "as_of": AS_OF, "kpis": kpis, "charts": charts, "plays": plays,
            "iq": {"fabric": b["tables"], "foundry": b["policies"],
                   "work_prompt": f"What have colleagues said recently (email, Teams, meeting notes) about {topic}? Internal only - summarise themes and who said it.",
                   "web_prompt": web}}


# --------------------------------------------------------------------------- #
# Account detail
# --------------------------------------------------------------------------- #
def _it(label: str, value: Any, fmt: str = "text") -> dict:
    return {"label": label, "value": value, "format": fmt}


def _client_section(a: dict) -> dict:
    c = CLIENT[a["customer_id"]]
    card = CARD.get(a["customer_id"])
    return {"title": "Client (same in every book)", "source": FAB, "items": [
        _it("Wellness band", c["wellness_band"]), _it("Email marketing consent", c["email_consent"]),
        _it("Linked mortgage", c["linked_mortgage"]), _it("Card", f"{card['product_name']} - {card['behaviour']}" if card else "None"),
        _it("TDS at renewal", c["tds_renewal_pct"] if c["tds_renewal_pct"] != "" else "n/a - no mortgage", "pct" if c["tds_renewal_pct"] != "" else "text"),
        _it("Internal only", "Wellness, TDS and scores are never shown to the client (RP-016).")]}


def account(book: str, aid: str) -> dict[str, Any] | None:
    aid = resolve(book, aid) or ""
    if not aid:
        return None
    b = BOOK[book]
    a = b["accounts"][aid]
    cid = a["customer_id"]
    if book == "banking":
        sections = [
            {"title": "Package and fees", "source": FAB, "items": [
                _it("Package", a["package"]), _it("Monthly fee", a["monthly_fee"], "cad"),
                _it("Fee waiver balance", a["fee_waiver_min_balance"] or "none", "cad" if a["fee_waiver_min_balance"] else "text"),
                _it("Transactions / month", a["avg_monthly_transactions"], "number"), _it("Package cost 12m", a["package_cost_12m"], "cad"),
                _it("Best-fit package", a["best_fit_package"]), _it("Best-fit cost 12m", a["best_fit_cost_12m"], "cad"),
                _it("All fees charged 12m", a["fees_charged_12m"], "cad")]},
            {"title": "Balances and products", "source": FAB, "items": [
                _it("Average chequing", a["avg_chequing_balance"], "cad"), _it("Savings (HISA)", a["savings_balance"], "cad"),
                _it("Holds HISA", a["has_hisa"]), _it("Holds card", a["has_card"]), _it("Overdraft protection", a["overdraft_protection"]),
                _it("Primary banking", a["primary_banking"])]},
            {"title": "Signals - last 3 months", "source": FAB, "items": [
                _it("NSF items", a["nsf_3m"], "number"), _it("Overdraft days", a["overdraft_days_3m"], "number"),
                _it("Payroll moving out", a["outflow_share_pct"], "pct")]}]
    elif book == "borrowing":
        sections = [{"title": "Facility", "source": FAB, "items": [
            _it("Type", a["facility_type"]), _it("Rate", a["rate_pct"], "pct"),
            _it("Pricing", f"prime {PRIME}% + {a['prime_spread_pct']}%" if a["rate_type"] == "Variable" else "Fixed"),
            _it("Limit / original", a["limit_or_original_cad"], "cad"), _it("Balance", a["balance_cad"], "cad"),
            _it("Utilisation", a["utilisation_pct"], "pct"), _it("Monthly payment", a["monthly_payment_cad"], "cad"),
            _it("Matures", a["maturity_date"] or "revolving"), _it("Days past due", a["days_past_due"], "number")]
            + ([_it("Combined LTV", a["combined_ltv_pct"], "pct")] if a["combined_ltv_pct"] != "" else [])}]
        others = [f for f in FACS_BY_CUST[cid] if f["account_id"] != aid]
        if others:
            sections.append({"title": "Other facilities", "source": FAB,
                             "items": [_it(f"{f['account_id']} {f['facility_type']}", f["balance_cad"], "cad") for f in others]})
        c = CAND.get(cid)
        if c:
            sections.append({"title": "Debt consolidation (both ways - RP-025)", "source": FAB, "items": [
                _it("Card balance", c["card_balance_cad"], "cad"), _it("Card rate", c["card_apr_pct"], "pct"),
                _it("At minimum: payment", c["card_min_payment_cad"], "cad"), _it("At minimum: months to repay", c["card_months_to_repay_at_minimum"], "number"),
                _it("At minimum: total interest", c["card_total_interest_at_minimum_cad"], "cad"), _it("Proposed", c["target_type"]),
                _it("Proposed rate", c["target_rate_pct"], "pct"), _it("Proposed term (months)", c["term_months"], "number"),
                _it("Proposed payment", c["new_payment_cad"], "cad"), _it("Proposed total interest", c["new_total_interest_cad"], "cad"),
                _it("Interest saved / yr", c["interest_saved_annual_cad"], "cad"), _it("Affordability", c["tds_check"]),
                _it("Payment falls", c["payment_falls"]), _it("Treatment", c["treatment"])]})
    elif book == "investing":
        r = ROOM[cid]
        sections = [
            {"title": "Holdings", "source": FAB, "items": [
                _it(f"{h['account_id']} {h['plan']} - {h['holding_type']}" + (f" (matures {h['gic_maturity_date']})" if h["gic_maturity_date"] else ""),
                    h["market_value_cad"], "cad") for h in HOLD_BY_CUST[cid]]},
            {"title": "Registered room", "source": FAB, "items": [
                _it("Age", r["age"], "number"), _it("Homeowner", r["homeowner"]), _it("TFSA room unused", r["tfsa_room_unused_cad"], "cad"),
                _it("RRSP room unused", r["rrsp_room_unused_cad"], "cad"), _it("FHSA eligible", r["fhsa_eligible"]), _it("FHSA opened", r["fhsa_opened"]),
                _it("Dependents", r["dependents"], "number"), _it("Has RESP", r["has_resp"]),
                _it("CESG missed / yr", r["cesg_missed_per_year_cad"], "cad"), _it("Taxable savings (HISA)", r["savings_balance_cad"], "cad")]},
            {"title": "Suitability", "source": FAB, "items": [
                _it("Risk profile", a["risk_profile"]), _it("KYC last updated", a["kyc_last_updated"]),
                _it("KYC age (months)", a["kyc_age_months"], "number"), _it("KYC status", a["kyc_status"])]}]
    elif book == "newcomers":
        sections = [
            {"title": "Arrival and status", "source": FAB, "items": [
                _it("Origin", a["origin_country"]), _it("Arrived", a["arrival_month"]), _it("Months in Canada", a["months_in_canada"], "number"),
                _it("Status", a["status"]), _it("Products held", a["products_held"])]},
            {"title": "Credit building", "source": FAB, "items": [
                _it("Stage", a["credit_building_stage"]), _it("Credit file (months)", a["credit_file_months"], "number"),
                _it("Secured card (months)", a["secured_card_months"] or "n/a", "number" if a["secured_card_months"] else "text"),
                _it("Paid on time", a["secured_card_on_time"] or "n/a"), _it("Income", a["income"], "cad")]},
            {"title": "Newcomer package (RP-029)", "source": FAB, "items": [
                _it("Fee-free period active", a["newcomer_package_active"]), _it("Fee-free period ends", a["package_expiry_month"]),
                _it("Days left", a["days_to_package_expiry"] if a["days_to_package_expiry"] != "" else "n/a",
                    "number" if a["days_to_package_expiry"] != "" else "text"),
                _it("Lowest-cost next package", a["next_package"]), _it("Next package cost 12m", a["next_package_cost_12m"], "cad"),
                _it("Average chequing", a["avg_chequing_balance"], "cad")]}]
        if a["sends_abroad"] == "Y":
            sections.append({"title": "Money transfer - total cost (RP-030)", "source": FAB, "items": [
                _it("Corridor", a["corridor"]), _it("Sends with", a["transfer_provider"]), _it("Transfers 12m", a["transfers_12m"], "number"),
                _it("Sent 12m", a["sent_12m_cad"], "cad"), _it("Fees 12m", a["transfer_fees_12m_cad"], "cad"), _it("FX margin cost 12m", a["fx_cost_12m_cad"], "cad"),
                _it("Total cost 12m", a["transfer_cost_12m_cad"], "cad"), _it("Same transfers with the Bank", a["bank_equivalent_cost_12m_cad"], "cad"),
                _it("Transfers / month (last 3)", a["avg_transfers_last_3m"], "number"), _it("New recipients 90d", a["new_recipients_90d"], "number"),
                _it("Scam-alert watch-list corridor", a["scam_watch_corridor"])]})
    elif book == "insurance":
        sections = [
            {"title": "Policies", "source": FAB, "items": [
                _it(f"{q['policy_id']} {q['policy_type']} - {q['status']}" + (f" ({q['lapse_date']})" if q["lapse_date"] else "")
                    + (f", ${q['monthly_premium_cad']:,.2f}/mo" if q["monthly_premium_cad"] else ""), q["covered_amount_cad"], "cad")
                for q in POL_BY_CUST.get(cid, [])] or [_it("Policies", "None on record")]},
            {"title": "Coverage", "source": FAB, "items": [
                _it("Mortgage balance", a["mortgage_balance_cad"], "cad"), _it("Mortgage life cover", a["mortgage_life_coverage_cad"], "cad"),
                _it("Gap", a["gap_amount_cad"], "cad"), _it("Dependents", a["dependents"], "number"), _it("Disability cover", a["has_disability_cover"]),
                _it("Days to renewal", a["days_to_renewal"] if a["days_to_renewal"] != "" else "n/a", "number" if a["days_to_renewal"] != "" else "text")]},
            {"title": "Premiums and affordability (RP-031)", "source": FAB, "items": [
                _it("Optional premiums / month", a["optional_premiums_monthly_cad"], "cad"), _it("Credit balances", a["credit_balances_cad"], "cad"),
                _it("Premium affordability flag (TDS > 44%)", a["premium_affordability_flag"]),
                _it("Rule", "Insurance is optional and never a condition of credit; 30-day cooling-off; never auto-cancel.")]}]
        if a["card_product"]:
            sections.append({"title": "Travel", "source": FAB, "items": [
                _it("Card", a["card_product"]), _it("Card includes travel insurance", a["card_includes_travel"]),
                _it("Travel spend 12m", a["travel_spend_12m_cad"], "cad"), _it("Foreign spend share", a["foreign_spend_share_pct"], "pct")]})
    else:
        sections = [
            {"title": "Events - last 90 days", "source": FAB, "items": [
                _it(f"{e['event_date']} {e['event_type']} ({e['severity']}, {e['status']})" + (f" ${e['amount_cad']:,.0f}" if e["amount_cad"] else ""),
                    e["note"]) for e in EV_BY_CUST[cid]]},
            {"title": "Security posture", "source": FAB, "items": [
                _it("Transaction alerts", a["alerts_enabled"]), _it("2-step verification", a["two_step_verification"]),
                _it("Digital wallet", a["digital_wallet"]), _it("Trusted contact person", a["trusted_contact_on_file"]),
                _it("Contact email changed (30d)", a["contact_email_changed_30d"]), _it("Last security check-in", a["last_security_checkin"])]},
            {"title": "Rules (RP-032)", "source": FAB, "items": [
                _it("Channel", "Verified channels only; never ask for a PIN, passcode or password."),
                _it("Sales", "No marketing in this book; Grow plays in other books are paused while a case is open."),
                _it("Open events", a["open_events"], "number")]}]
    sections.append(_client_section(a))
    s = SERIES[book].get(aid) or {"title": "No series", "lines": []}
    name = a["customer_name"]
    label = b["title"].lower()
    pol = ", ".join(b["policies"])
    web = {"banking": "chequing-package fees, fee waivers and high-interest savings rates",
           "borrowing": "prime rate, line-of-credit, home-equity line and auto-loan rates",
           "investing": "GIC rates by term and 2026 TFSA / RRSP / FHSA / RESP limits and grant rules"}.get(book) or b["web_short"]
    return {**_row(book, a), "sections": sections,
            "series": {"title": s["title"], "source": FAB, "months": MONTHS, "lines": s["lines"]},
            "plays": _plays(book, aid),
            "prompts": [
                {"label": "Brief me on this client", "prompt": f"Brief me on {label} account {aid} ({cid}, {name}): balances, 12-month trend, flags and "
                 f"ranked plays, plus any linked mortgage or card signals. Verify in Fabric IQ ({', '.join(b['tables'])})."},
                {"label": "What may I offer?", "prompt": f"For {label} account {aid} ({cid}), which plays are eligible and which are blocked, and why? "
                 f"Use the Foundry IQ policies and cite {pol} as relevant."},
                {"label": "How does the market compare?", "prompt": f"Using the public web only, summarise current Canadian {web} "
                 "(issuer-neutral, dated, with sources). Do not use internal data or name this client."},
                {"label": "What have colleagues said?", "prompt": f"Using Work IQ, what have colleagues said about {name} ({cid}) in recent emails, Teams "
                 f"chats or meeting notes relevant to {label}? Internal only - summarise and cite who and when."},
            ]}


# --------------------------------------------------------------------------- #
# Drafts and checks
# --------------------------------------------------------------------------- #
UNSUB = "\n\nYou are receiving this because you agreed to hear from {bank}. Reply STOP or use the unsubscribe link to opt out."


def _governed(book: str, aid: str, play: dict) -> dict:
    """The governed play behind a draft - never trust eligibility sent by the client."""
    for p in BOOK[book]["by_account"].get(aid, []):
        if p["play"] == play.get("play") and p["play_type"] == play.get("play_type"):
            return p
    return play or {}


def _template(book: str, a: dict, p: dict, bank: str) -> tuple[str, str]:
    first = a["customer_name"].split()[0]
    cid = a["customer_id"]
    name = p["play"]
    hi = f"Hi {first},\n\n"
    if name == "Overdraft/NSF support":
        body = (hi + "We noticed a few recent payments came back unpaid or your account dipped into overdraft. That can happen to anyone, and we'd like "
                "to help. We can refund up to two recent fees, line up your bill dates with your payday, and set up low-balance alerts.")
        if a["overdraft_protection"] != "Y":
            body += " If it would help, we can also talk about overdraft protection - it is only ever added with your express consent."
        return "We're here to help with your account", body + "\n\nThere's no obligation. Reply to this message or call us to book a time."
    if name == "Primary banking at risk":
        return ("Is your everyday banking still working for you?",
                hi + "We'd value a short review of your everyday banking to make sure your account, fees and bill payments still suit you. "
                "Depending on what we find, we may be able to waive your monthly account fee for up to 12 months.\n\n"
                "Reply to this message or call us to pick a time.")
    if name == "Package fit":
        best = PACKAGES[a["best_fit_package"]]
        waiver = f", waived in any month your balance stays above ${best['waiver']:,}" if best["waiver"] else ""
        tx = f"{best['included_tx']} transactions included, then ${1.25:.2f} each" if best["included_tx"] else "unlimited transactions"
        return (f"You could pay less with the {a['best_fit_package']} package",
                hi + f"Based on how you used your account over the last 12 months, the {a['best_fit_package']} package would have cost about "
                f"${a['best_fit_cost_12m']:,.0f} a year instead of ${a['package_cost_12m']:,.0f} on your current {a['package']} package - a saving of "
                f"about ${a['package_cost_12m'] - a['best_fit_cost_12m']:,.0f}.\n\nThe {a['best_fit_package']} package costs ${best['fee']:.2f} a month{waiver}, "
                f"with {tx}. Switching is free and you keep your account number.\n\nReply or call us if you'd like to switch.")
    if name == "Savings sweep":
        return ("Put your everyday balance to work",
                hi + f"Your chequing balance has averaged about ${a['avg_chequing_balance']:,.0f} over the last year. A high-interest savings account "
                "with an automatic sweep could earn interest on money you don't need day to day, while keeping it easy to reach. Rates are variable; "
                "current rates and terms are in the account disclosure.\n\nReply or call us if you'd like to talk it through.")
    if name == "Bundle completion":
        if "card" in p["recommended_product"].lower():
            return ("A card to round out your everyday banking",
                    hi + "You already bank and save with us. A no-fee rewards card could round this out. Any card is subject to approval; interest "
                    "rate and fee details are in the disclosure statement.\n\nReply or call us if you'd like to talk it through.")
        return ("A savings account to go with your chequing",
                hi + "A high-interest savings account alongside your chequing account can make it easier to set money aside automatically. Rates are "
                "variable; current rates and terms are in the account disclosure.\n\nReply or call us if you'd like to talk it through.")
    if name == "Arrears support":
        return ("Let's find a payment plan that works",
                hi + f"We noticed a recent payment on your {a['facility_type'].lower()} hasn't come in. If things are tight right now, you're not alone "
                "and there are options - such as a short payment deferral or a revised payment plan - and our Client Assistance team can help.\n\n"
                "Please reply or call us so we can find something that works for you.")
    if name == "Debt consolidation":
        c = CAND[cid]
        if c["treatment"] == "Support - Client Assistance":
            return ("Help making your card balance more manageable",
                    hi + "We'd like to help make your card balance more manageable. Our Client Assistance team offers free, confidential budgeting "
                    "support and can look at options with you, including lowering what you pay in interest.\n\nThere's no obligation. Reply or call us "
                    "to book a time.")
        yrs = c["card_months_to_repay_at_minimum"] / 12
        target = c["target_type"].replace("Existing ", "").replace("New ", "")
        art = "an" if target[0].lower() in "aeiou" else "a"
        return ("A lower-cost way to pay down your card balance",
                hi + f"Paying the minimum of about ${c['card_min_payment_cad']:,.0f} a month on your card balance of about ${c['card_balance_cad']:,.0f} "
                f"would take about {yrs:.0f} years and cost about ${c['card_total_interest_at_minimum_cad']:,.0f} in interest.\n\n"
                f"Moving it to {art} {target} at {c['target_rate_pct']}% over {c['term_months']} months "
                f"would mean a payment of about ${c['new_payment_cad']:,.0f} a month and about ${c['new_total_interest_cad']:,.0f} in interest in total.\n\n"
                "Any new credit is subject to approval and a review of what is affordable for you. There's no obligation - reply or call us to talk "
                "it through.")
    if name == "Auto loan maturing":
        return ("Your auto loan is almost paid off",
                hi + f"Your auto loan is scheduled to be paid off on {a['maturity_date']}. Nicely done. If you're thinking about your next vehicle, "
                "we're happy to talk through your options; any new loan is subject to approval.\n\nReply or call us any time.")
    if name == "Prime-rate change notice":
        d = a["balance_cad"] * 0.0025 / 12
        return (f"How a prime-rate change would affect your {a['facility_type'].lower()}",
                hi + f"Your {a['facility_type'].lower()} has a variable rate of prime + {a['prime_spread_pct']}%, currently {a['rate_pct']}%. "
                f"For illustration only: if prime moved up or down by 0.25%, your interest would change by about ${d:,.2f} a month on your current "
                f"balance of ${a['balance_cad']:,.0f}.\n\nWe will write to you within 30 days of any change to prime with your new rate and payment. "
                "If a change would make payments hard to manage, please contact us.")
    if name == "Home-equity re-advance":
        return ("Planning a project at home?",
                hi + "If you're planning a project, you may be able to draw more on your home-equity line. Any additional borrowing is subject to "
                "approval and a review of what is affordable for you. Rates are variable.\n\nReply or call us if you'd like to talk it through.")
    if name == "KYC refresh required":
        return ("Time to refresh your investment profile",
                hi + "It's been a while since we last reviewed your investment profile. Please book about 20 minutes with a licensed advisor to "
                "update your goals, time horizon and comfort with investment risk. Until then we won't make new investment recommendations.\n\n"
                "Reply or call us to book a time.")
    if name == "GIC maturing":
        gics = [h for h in HOLD_BY_CUST[cid] if h["holding_type"] == "GIC" and h["days_to_maturity"] != "" and int(h["days_to_maturity"]) <= 90]
        first_m = min(gics, key=lambda h: int(h["days_to_maturity"]))["gic_maturity_date"] if gics else "soon"
        v = sum(h["market_value_cad"] for h in gics)
        return ("Your GIC matures soon",
                hi + f"Your GIC of about ${v:,.0f} matures on {first_m}. A licensed advisor can walk you through your options before then, including "
                "what happens automatically if we don't hear from you. Rates offered at maturity apply; past rates don't indicate future rates.\n\n"
                "Reply or call us to book a time.")
    if name == "RESP grant left on the table":
        r = ROOM[cid]
        return ("Education savings grant for your family",
                hi + f"Families can collect the Canada Education Savings Grant: 20% on the first $2,500 contributed per child each year, up to $500 "
                f"per child. With {r['dependents']} child{'ren' if r['dependents'] > 1 else ''}, that is up to ${r['cesg_missed_per_year_cad']:,.0f} a year "
                "in grant. A licensed advisor can help you set up an RESP and choose investments that suit you.\n\nReply or call us to book a time.")
    if name == "FHSA for first-time buyers":
        return ("Saving for your first home?",
                hi + "If you're saving for your first home, a First Home Savings Account (FHSA) lets you contribute up to $8,000 a year. "
                "Contributions are tax-deductible, and qualifying withdrawals for a first home are tax-free. Eligibility rules apply. A licensed "
                "advisor can help you check them and choose investments that suit you.\n\nReply or call us to book a time.")
    if name == "Idle cash to TFSA":
        r = ROOM[cid]
        return ("Making use of your TFSA room",
                hi + f"Our records show about ${r['tfsa_room_unused_cad']:,.0f} of unused TFSA room. Investment growth inside a TFSA isn't taxed. "
                "Please confirm your room in your CRA account before contributing - over-contributions are taxed at 1% a month. A licensed advisor "
                "can help you choose investments that suit you.\n\nReply or call us to book a time.")
    never = "We will never ask for your PIN, passcode or password, and we will never ask you to move money to keep it safe."
    verified = "call us using the number on the back of your card or on our official website - not a number or link from a text or email"
    if name == "Package expiry":
        nxt = PACKAGES[a["next_package"]]
        waiver = f", waived in any month your balance stays above ${nxt['waiver']:,}" if nxt["waiver"] else ""
        tx = f"{nxt['included_tx']} transactions included, then $1.25 each" if nxt["included_tx"] else "unlimited transactions"
        return ("Your newcomer fee-free period ends soon",
                hi + f"Your newcomer banking package has no monthly fee until {a['package_expiry_month']}. After that, based on how you have used your "
                f"account, the {a['next_package']} package would cost you the least: ${nxt['fee']:.2f} a month{waiver}, with {tx} - about "
                f"${a['next_package_cost_12m']:,.0f} a year for your usage. Changing package is free and you keep your account number.\n\n"
                "We're happy to explain this in your preferred language. Reply or call us with any questions.")
    if name == "Credit-building next step":
        return ("You've reached a credit-building milestone",
                hi + f"You've used your secured card for {a['secured_card_months']} months and made every payment on time - well done. You may now be "
                "able to move to a no-fee card that doesn't need a security deposit, and get your deposit back. Any card is subject to approval; "
                "interest rate and fee details are in the disclosure statement.\n\nThere's no obligation. Reply or call us if you'd like to talk it through.")
    if name == "Cheaper money transfer":
        if a["transfer_provider"] == "Other provider":
            saving = a["transfer_cost_12m_cad"] - a["bank_equivalent_cost_12m_cad"]
            fx = a["fx_cost_12m_cad"] / a["sent_12m_cad"] * 100 if a["sent_12m_cad"] else 0
            return ("Sending money home for less",
                    hi + f"Over the last 12 months you sent about ${a['sent_12m_cad']:,.0f} abroad through another provider. Fees of about "
                    f"${a['transfer_fees_12m_cad']:,.0f} plus an exchange rate margin of about {fx:.1f}% (about ${a['fx_cost_12m_cad']:,.0f}) brought the "
                    f"total cost to about ${a['transfer_cost_12m_cad']:,.0f}.\n\nSending the same amounts with us would have cost about "
                    f"${a['bank_equivalent_cost_12m_cad']:,.0f}: a ${3.99:.2f} fee per transfer plus an exchange rate margin of 1.5% - about "
                    f"${saving:,.0f} less a year. Most transfers are delivered within 1-2 business days. Before you confirm every transfer we show the "
                    "fee, the exchange rate margin, the total cost and the delivery time.\n\nReply or call us if you'd like to talk it through.")
        return ("You could pay less in transfer fees",
                hi + f"You made {a['transfers_12m']} international transfers with us in the last 12 months, each with a $3.99 fee. Sending the same "
                f"total in fewer, larger transfers would save about ${a['transfer_fees_12m_cad'] / 2:,.0f} a year in fees. The exchange rate margin "
                "(1.5%) stays the same, and the total cost and delivery time (usually 1-2 business days) are shown before you confirm each transfer."
                "\n\nReply or call us with any questions.")
    if name == "Remittance scam awareness":
        return ("Protecting the money you send home",
                hi + "We noticed you've been sending money abroad more often lately, including to new recipients. Most transfers are exactly what "
                "they look like, but scammers often target people who send money to family. Before you send to someone new, confirm the request "
                "by calling the person on a number you already know, and be careful with urgent requests, job or immigration offers, or anyone who "
                f"asks you to pay a fee to release money.\n\n{never} If something feels wrong, {verified}.")
    if name == "Mortgage readiness":
        return ("Thinking about buying your first home in Canada?",
                hi + "You've built a solid banking and credit history since you arrived. If owning a home is part of your plans, a mortgage advisor "
                "can walk you through what you could comfortably afford, the down payment and closing costs, and each step of the process. Any "
                "mortgage is subject to approval and a review of what is affordable for you.\n\nThere's no obligation. Reply or call us to book a time.")
    if name == "Premium affordability review":
        types = sorted({q["policy_type"].lower() for q in POL_BY_CUST.get(cid, []) if q["optional_creditor"] == "Y" and q["status"] == "Active"})
        return ("Making sure your optional cover still fits your budget",
                hi + f"You currently pay about ${a['optional_premiums_monthly_cad']:,.2f} a month for {', '.join(types)}. This insurance is optional, "
                "and we want to make sure it still meets your needs and fits your budget. An authorised advisor can go through what it covers and "
                "what it costs, and your choice to keep, reduce or cancel it. We will never cancel cover without your instruction.\n\n"
                "Reply or call us to book a time.")
    if name == "Lapsed policy":
        q = min((x for x in POL_BY_CUST.get(cid, []) if x["status"] == "Lapsed" and x["days_since_lapse"] != "" and x["days_since_lapse"] <= 90),
                key=lambda x: x["days_since_lapse"])
        what = "your mortgage" if q["policy_type"].startswith("Mortgage") else "your credit"
        return (f"Your {q['policy_type'].lower()} cover has ended",
                hi + f"Our records show your {q['policy_type'].lower()} cover ended on {q['lapse_date']} because premiums stopped. If you meant to "
                f"cancel, there's nothing more to do. If not, an authorised advisor can explain your options. This insurance is optional and is "
                f"never a condition of {what}.\n\nReply or call us with any questions.")
    if name == "Coverage gap on renewing mortgage":
        return ("Protecting your family as your mortgage renews",
                hi + f"Your mortgage renews in about {a['days_to_renewal']} days - a good moment to check whether your family would be protected if "
                f"something happened to you. Our records show "
                + (f"about ${a['mortgage_life_coverage_cad']:,.0f} of mortgage life cover against" if a["mortgage_life_coverage_cad"] else "no mortgage life cover on")
                + f" a balance of about ${a['mortgage_balance_cad']:,.0f}.\n\nThis insurance is optional and is never a condition of your mortgage or any other "
                "credit. An authorised advisor can explain the cost, what is and isn't covered (including pre-existing conditions), and how it "
                "compares with life insurance you may already have. If you buy cover, you have 30 days to cancel for a full refund.\n\n"
                "Reply or call us if you'd like to talk it through.")
    if name == "Travel cover check":
        return ("Before your next trip",
                hi + "You've been travelling recently. Your current card does not include travel medical insurance, so it's worth checking what "
                "cover you already have - for example through an employer plan or another policy - before your next trip. This is information "
                "only; we're not offering you a product.\n\nIf you have questions, reply or call us.")
    if name == "Open fraud case follow-up":
        e = next(x for x in EV_BY_CUST[cid] if x["status"] == "Open" and x["severity"] == "High")
        return ("Following up on recent activity on your account",
                hi + f"We're following up on unusual activity we flagged on {e['event_date']} ({e['event_type'].lower()}). We have taken steps to "
                f"protect your account while we check it with you. To confirm it's safe, please {verified}.\n\n{never}")
    if name == "Scam coaching":
        return ("Staying safe from scams",
                hi + "Scams are getting harder to spot, and anyone can be targeted. A few habits help: hang up and call us back on a number you "
                "trust; never share codes sent to your phone; and be wary of anyone who rushes you or asks you to keep a payment secret.\n\n"
                "If you'd like, you can name a trusted contact person we can reach if we're ever worried about unusual activity, and we can pause "
                f"large transfers to new payees until we've checked them with you.\n\n{never} To talk it through, please {verified}.")
    if name == "Security check-in":
        return ("A quick security check-in",
                hi + "We'd like to do a short security check-in with you: review the devices signed in to your account, your saved payees and your "
                f"alert settings, and make sure everything looks right. It takes about 10 minutes. To book it, please {verified}.\n\n{never}")
    if name == "Enable alerts & 2-step":
        want = [x for x, on in (("transaction alerts", a["alerts_enabled"] == "Y"), ("2-step verification", a["two_step_verification"] == "Y")) if not on]
        return ("Two quick settings that help protect your account",
                hi + f"Turning on {' and '.join(want)} is one of the simplest ways to protect your account. Alerts tell you about activity as it "
                "happens, and 2-step verification adds a check when someone signs in from a new device. You can turn them on in the app's "
                f"security settings, or {verified}, and we'll help.\n\n{never}")
    return f"About your {BOOK[book]['title'].lower()}", hi + "We'd like to check in with you.\n\nReply or call us any time."


def draft(book: str, aid: str, play_index: int = 0, bank: str = "the Bank") -> dict[str, Any] | None:
    aid = resolve(book, aid) or ""
    plays = _plays(book, aid) if aid else []
    if not plays:
        return None
    p = plays[max(0, min(play_index, len(plays) - 1))]
    a = BOOK[book]["accounts"][aid]
    subject, body = _template(book, a, p, bank)
    body += "\n\n" + BOOK[book]["sign"]
    if p["purpose"] == "Marketing":
        body += UNSUB.format(bank=bank)
    d = {"account_id": aid, "play": p, "channel": "Email", "purpose": p["purpose"], "subject": subject, "body": body}
    cks = checks(book, aid, d)
    return {**d, "checks": cks, "verdict": verdict(cks)}


SELLING = r"\b(upgrade|re-?advance|draw more|limit increase|apply (now|today)|bonus points|rewards card)\b"
RETURN_PROMISE = r"\b(will (earn|grow|return|double)|returns? of \d|\d+(\.\d+)?% (annual )?return|no risk|can't lose)\b"
FHSA = r"\b(FHSA|first home savings)\b"
SECRETS = (r"(?<!never )(?<!not )(?<!don't )\b(send|share|confirm|provide|reply with|tell us|enter|give us)\b( us)?( your)? "
           r"(PIN|passcode|password|one-time (pass)?code|verification code)\b")
NEVER_ASK = r"never ask for your PIN, passcode or password"
PRESSURE = r"\b(required|mandatory|compulsory|must (buy|have|purchase|keep))\b"
TRANSFER_COST = (("fee", r"\bfees?\b"), ("exchange rate margin", r"exchange rate margin|FX margin"), ("total cost", r"total cost"),
                 ("delivery time", r"deliver"))


def _new_credit(p: dict) -> bool:
    if p.get("play") in ("Home-equity re-advance", "Credit-building next step", "Mortgage readiness"):
        return True
    if p.get("play") == "Debt consolidation":
        return "Client Assistance" not in p.get("recommended_product", "")
    return p.get("play") == "Bundle completion" and "card" in p.get("recommended_product", "").lower()


def checks(book: str, aid: str, d: dict[str, Any]) -> list[dict[str, str]]:
    aid = resolve(book, aid) or aid
    a = BOOK[book]["accounts"][aid]
    cid = a["customer_id"]
    c = CLIENT[cid]
    text = f"{d.get('subject', '')}\n{d.get('body', '')}"
    p = _governed(book, aid, d.get("play") or {})
    out: list[dict[str, str]] = []
    add = lambda rule, name, ok, detail, sev="block": out.append(  # noqa: E731
        {"rule": rule, "name": name, "status": "pass" if ok else sev, "detail": detail})
    if d.get("purpose") == "Marketing":
        add("RP-011", "Marketing consent", c["email_consent"] == "Granted", f"Email marketing consent is {c['email_consent']}.")
        unsub = bool(re.search(r"unsubscribe|reply stop", text, re.I))
        add("RP-011", "Unsubscribe mechanism", unsub, "Present." if unsub else "Missing from a promotional message.")
    vul = c["wellness_band"] == "Vulnerable"
    selling = p.get("play_type") == "Grow" or d.get("purpose") == "Marketing" or bool(re.search(SELLING, text, re.I))
    add("RP-012", "Support first", not (vul and selling),
        "Support-first client: sales suppressed - no promotional message, product sale or new credit." if vul and selling else
        "Support-first client - service and support only." if vul else "Not a support-first client.")
    if _new_credit(p):
        tds = c["tds_renewal_pct"]
        if c["linked_mortgage"] == "Y":
            ok = tds == "" or _num(tds) <= TDS_LIMIT
            add("RP-013", "Affordability for new credit", ok, f"Household TDS at renewal {tds}% {'within' if ok else 'exceeds'} the 44% guideline.")
        if p.get("play") == "Debt consolidation" and c["linked_mortgage"] == "N":
            cand = CAND.get(cid, {})
            ok = cand.get("payment_falls") == "Y"
            add("RP-025", "New payment lower than today", ok,
                f"Payment ${_num(cand.get('card_min_payment_cad')):,.0f} -> ${_num(cand.get('new_payment_cad')):,.0f} a month.")
        if p.get("play") == "Home-equity re-advance":
            ltv = _num(a.get("combined_ltv_pct"))
            add("RP-025", "Combined LTV within 65%", ltv <= 65, f"Combined LTV {ltv:.1f}%.")
        if re.search(r"\bpre-?approved\b", text, re.I):
            add("RP-025", "No pre-approval language", False, "Credit is never described as pre-approved.")
    if book == "banking" and re.search(r"overdraft protection", text, re.I):
        ok = a["overdraft_protection"] == "Y" or bool(re.search(r"consent", text, re.I))
        add("RP-024", "Overdraft protection - express consent", ok,
            "Protection on file." if a["overdraft_protection"] == "Y" else
            "Mentions overdraft protection with the express-consent statement." if ok else "Overdraft protection mentioned without express consent.")
    if p.get("play") == "Package fit":
        ok = bool(re.search(r"\$\d", text)) and bool(re.search(r"month", text, re.I))
        add("RP-023", "Fee disclosure", ok, "Monthly fee and cost shown." if ok else "State the monthly fee and expected annual cost.", "warn")
    if p.get("play") == "Prime-rate change notice":
        ok = d.get("purpose") != "Marketing" and not re.search(SELLING + r"|\b(special offer|switch to|limited)\b", text, re.I)
        add("RP-026", "Rate notice is service-only", ok, "No promotional content." if ok else "A rate-change notice must not carry a sales message.")
    if book == "investing":
        h0 = BOOK["investing"]["accounts"][aid]
        if p.get("play") != "KYC refresh required":
            ok = h0["kyc_status"] != "Stale"
            add("RP-027", "KYC current (36 months)", ok, f"KYC last updated {h0['kyc_last_updated']} ({h0['kyc_age_months']} months).")
        m = re.search(RETURN_PROMISE, text, re.I)
        add("RP-027", "No return promises", not m, f"Found: \"{m.group(0)}\"" if m else "None found.")
    if re.search(FHSA, text, re.I):
        ok = ROOM.get(cid, {}).get("fhsa_eligible") == "Y"
        add("RP-028", "FHSA eligibility (renters only)", ok, "Renter, age 18-70." if ok else "Client owns a home or is outside 18-70 - not FHSA eligible.")
    if p.get("play") == "RESP grant left on the table":
        ok = ROOM[cid]["dependents"] > 0
        add("RP-028", "RESP beneficiary", ok, f"{ROOM[cid]['dependents']} dependent(s) on record.")
    selling_play = p.get("play_type") == "Grow" or d.get("purpose") == "Marketing"
    if book != "security" and selling_play:
        ok = cid not in OPEN_CASE
        add("RP-032", "No sales during an open fraud case", ok,
            "No open security event." if ok else "Client has an open security event - sales are paused until it is resolved.")
    if book in ("newcomers", "security"):
        m = re.search(SECRETS, text, re.I)
        add("RP-032", "Never ask for secrets", not m, f"Found: \"{m.group(0)}\"" if m else "No request for a PIN, passcode, password or code.")
    if book == "newcomers":
        j = NJ[cid]
        if p.get("play") == "Cheaper money transfer":
            missing = [n for n, pat in TRANSFER_COST if not re.search(pat, text, re.I)]
            add("RP-030", "Total cost disclosure (fee + FX margin + delivery)", not missing,
                "Fee, exchange rate margin, total cost and delivery time disclosed." if not missing else "Missing: " + ", ".join(missing) + ".")
        if p.get("play") == "Package expiry":
            ok = bool(re.search(r"\$\d", text)) and bool(re.search(r"month", text, re.I))
            add("RP-029", "Fee-free period and next fee disclosed", ok, "End date and monthly fee shown." if ok else "State when the fee-free period ends and the next fee.", "warn")
        if p.get("play") == "Credit-building next step":
            ok = j["credit_building_stage"] == "Secured card" and j["secured_card_months"] >= 12 and j["secured_card_on_time"] == "Y"
            add("RP-029", "Credit-building eligibility", ok, f"{j['credit_building_stage']}, {j['secured_card_months']} months, on time {j['secured_card_on_time'] or 'n/a'}.")
        if p.get("play") == "Mortgage readiness":
            ok = j["status"] == "Permanent resident" and j["credit_file_months"] >= 24 and j["income"] >= 70000 and j["linked_mortgage"] == "N"
            add("RP-013", "Mortgage readiness criteria", ok, f"{j['status']}, {j['credit_file_months']}-month credit file, income ${j['income']:,.0f}.")
    if book == "insurance":
        g = COVER[cid]
        m = re.search(PRESSURE, text, re.I)
        add("RP-031", "Insurance never presented as required", not m, f"Found: \"{m.group(0)}\"" if m else "No pressure or 'required' language.")
        if d.get("purpose") == "Marketing" or p.get("play_type") == "Grow":
            ok = bool(re.search(r"\binsurance is optional\b", text, re.I))
            add("RP-031", "States 'insurance is optional'", ok, "Present." if ok else "Every insurance marketing message must say the insurance is optional.")
            ok = bool(re.search(r"30 days", text)) and bool(re.search(r"pre-existing", text, re.I))
            add("RP-031", "Cooling-off and pre-existing condition disclosure", ok,
                "30-day cooling-off and pre-existing conditions mentioned." if ok else "Mention the 30-day cooling-off period and pre-existing conditions.", "warn")
        if p.get("play") == "Coverage gap on renewing mortgage":
            ok = g["premium_affordability_flag"] != "Y"
            add("RP-031", "Premium affordability", ok, f"Household TDS at renewal {c['tds_renewal_pct']}% {'within' if ok else 'exceeds'} the 44% guideline.")
    if book == "security":
        s = POSTURE[cid]
        add("RP-032", "Security before sales", d.get("purpose") != "Marketing", "Service message." if d.get("purpose") != "Marketing" else
            "No marketing in a security conversation.")
        m = re.search(SELLING + r"|\b(special offer|switch to|pre-?qualified)\b", text, re.I)
        add("RP-032", "No selling in security outreach", not m, f"Found: \"{m.group(0)}\"" if m else "None found.")
        ok = bool(re.search(NEVER_ASK, text, re.I))
        add("RP-032", "'We will never ask for your PIN, passcode or password'", ok, "Present." if ok else "Every security message must include it.")
        ok = s["contact_email_changed_30d"] != "Y"
        add("RP-032", "Verified channel", ok, "Email on file unchanged." if ok else "Email changed during a security event - call the verified number on file instead.")
    hits = []
    for pat, rule, why in BANNED:
        m = re.search(pat, text, re.I)
        if m:
            hits.append({"rule": rule, "name": why, "status": "block", "detail": f"Found: \"{m.group(0)}\""})
    out.extend(hits or [{"rule": "RP-016", "name": "Prohibited words and internal data", "status": "pass", "detail": "None found."}])
    return out


def verdict(cks: list[dict[str, str]]) -> str:
    return "blocked" if any(c["status"] == "block" for c in cks) else "needs_approval" if any(c["status"] == "warn" for c in cks) else "pass"


def review_prompt(book: str, aid: str, d: dict[str, Any], cks: list[dict[str, str]]) -> str:
    aid = resolve(book, aid) or aid
    a = BOOK[book]["accounts"][aid]
    c = CLIENT[a["customer_id"]]
    det = "\n".join(f"- {k['rule']} {k['name']}: {k['status'].upper()} - {k['detail']}" for k in cks)
    play = d.get("play") or {}
    return (
        f"Review this {BOOK[book]['title'].lower()} client communication before it can be saved as a draft. Internal context (do NOT repeat to the "
        f"client): wellness band {c['wellness_band']}, email consent {c['email_consent']}, purpose {d.get('purpose')}, "
        f"play {play.get('play_type')} / {play.get('play')}.\nDeterministic checks already run (authoritative):\n{det}\n\n"
        f"DRAFT SUBJECT: {d.get('subject', '')}\nDRAFT BODY:\n{d.get('body', '')}\n\n"
        "Return 'VERDICT: PASS', 'VERDICT: NEEDS FIXES' or 'VERDICT: BLOCKED' first (never weaker than the checks), then a findings table "
        f"(exact text, policy {', '.join(BOOK[book]['policies'])}, why), then a corrected draft in a ```text block if fixable. "
        "Refer to the firm as 'the Bank'. You review; you never send or approve."
    )
