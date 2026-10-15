"""Product books for Fabric IQ - Everyday banking, Borrowing, Investing, Newcomers, Insurance, Security (deterministic, synthetic).

The first three books draw on the SAME clients as the mortgage and cards books: the 50
mortgage customers (CUST-1001..1050, homeowners) and the 38 card-only customers
(CUST-2001..2038, renters). Wellness band, marketing consent, TDS and linked
products are copied from the existing tables, so a client who is support-first in
one book is support-first in every book. Product names are brand-neutral. No
randomness, no clock. The Newcomers book adds 15 newcomer-only clients (CUST-3001..3015)
who also appear in the Security book; books 4-6 only read books 1-3 (their rows never change).

    deposit_accounts.csv               one chequing relationship per client: package, fee, balances, overdraft protection
    deposit_flows_monthly.csv          12 months x client: payroll, transfers out, bills, NSF, overdraft days, fees
    banking_next_actions.csv           plays: Overdraft/NSF support, Primary banking at risk, Package fit, Savings sweep, Bundle completion
    credit_facilities.csv              secured / unsecured lines, auto and personal loans
    debt_consolidation_candidates.csv  card balances (persistent debt / revolver) that a cheaper facility could carry
    borrowing_next_actions.csv         plays: Arrears support, Debt consolidation, Auto loan maturing, Prime-rate change notice, Home-equity re-advance
    investment_accounts.csv            TFSA / RRSP / FHSA / RESP / Non-registered holdings, GIC maturities, KYC date
    registered_room.csv                per client: TFSA / RRSP room, FHSA eligibility, RESP grant missed
    investing_next_actions.csv         plays: KYC refresh required, GIC maturing, RESP grant left on the table, FHSA for first-time buyers, Idle cash to TFSA
    newcomer_journey.csv               New to Canada clients: arrival, status, products, credit-building stage, newcomer package, transfer totals
    transfers_out_monthly.csv          12 months x sender: corridor, provider, count, amount, fees, FX margin, total cost, new recipients
    newcomers_next_actions.csv         plays: Package expiry, Credit-building next step, Cheaper money transfer, Remittance scam awareness, Mortgage readiness
    insurance_policies.csv             mortgage life / disability, line and card protection, home, travel (card benefit)
    coverage_gaps.csv                  per client: mortgage balance vs life cover, dependents, optional premiums, affordability flag, travel spend
    insurance_next_actions.csv         plays: Premium affordability review, Lapsed policy, Coverage gap on renewing mortgage, Travel cover check
    security_events.csv                last 90 days: card fraud alerts, phishing, new device + payee, large e-Transfer, remittance, password reset
    customer_security_posture.csv      per client with an event: alerts, 2-step, wallet, trusted contact, open / high events
    security_next_actions.csv          plays: Scam coaching, Open fraud case follow-up, Security check-in, Enable alerts & 2-step (no selling)

Also writes app/src/bff/app/books_data.py (BOOKS = the same rows + 12-month series).

    python generate_books_tables.py [--check]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_BFF = HERE.parent.parent / "app" / "src" / "bff" / "app" / "books_data.py"
AS_OF = "2026-08-03"
AS_OF_D = date.fromisoformat(AS_OF)
MONTHS = ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
PRIME = 4.95
TDS_LIMIT = 44.0
ORDER = {"Support": 0, "Protect": 1, "Retain": 2, "Grow": 3}

# Brand-neutral everyday-banking packages. Basic includes 12 transactions/month; extras $1.25.
PACKAGES = {
    "Basic": {"fee": 4.95, "waiver": None, "included_tx": 12},
    "Preferred": {"fee": 16.95, "waiver": 4000, "included_tx": None},
    "Ultimate": {"fee": 30.95, "waiver": 6000, "included_tx": None},
    "Student": {"fee": 0.0, "waiver": None, "included_tx": None},
}
EXTRA_TX_FEE = 1.25
NSF_FEE = 48.0
OD_FEE_PER_DAY = 5.0
HISA_RATE = 2.75
TFSA_CUMULATIVE_2026 = 109000
RRSP_MAX_2026 = 33810
FHSA_ANNUAL = 8000
CESG_PER_CHILD = min(500, 0.2 * 2500)

# Gate strings - pb_books.checks() re-derives each one from the data (test: Eligible <=> draft not blocked).
G_CONSENT = "Needs marketing consent (RP-011)"
G_SUPPORT = "Suppressed - support-first client (RP-012)"
G_TDS = "Blocked - TDS above 44% guideline (RP-013)"
G_PAYMENT = "Blocked - new payment would not be lower (RP-025)"
G_LTV = "Blocked - combined LTV above 65% (RP-025)"
G_KYC = "Blocked - KYC older than 36 months (RP-027)"


def h(*p: str) -> int:
    return int(hashlib.sha256("|".join(p).encode()).hexdigest()[:8], 16)


def u(*p: str) -> float:
    return h(*p) / 0xFFFFFFFF


def read(name: str) -> list[dict]:
    with (HERE / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def amort(principal: float, rate_pct: float, months: int) -> float:
    r = rate_pct / 100 / 12
    return principal / months if r == 0 else principal * r / (1 - (1 + r) ** -months)


def remaining(principal: float, rate_pct: float, months: int, paid: int) -> float:
    r = rate_pct / 100 / 12
    pay = amort(principal, rate_pct, months)
    return max(0.0, principal * (1 + r) ** paid - pay * ((1 + r) ** paid - 1) / r)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


# --------------------------------------------------------------------------- #
# Shared population
# --------------------------------------------------------------------------- #
def population() -> list[dict]:
    cust = {r["customer_id"]: r for r in read("customers.csv")}
    well = {r["customer_id"]: r for r in read("financial_wellness.csv")}
    cap = {r["customer_id"]: r for r in read("credit_capacity.csv")}
    hh = {r["primary_customer_id"]: r for r in read("households.csv")}
    ren = {r["customer_id"]: r for r in read("mortgage_renewals.csv")}
    consent = {(r["customer_id"], r["channel"]): r["consent_status"] for r in read("consent_preferences.csv")}
    prods = defaultdict(dict)
    for r in read("customer_products.csv"):
        prods[r["customer_id"]][r["product_id"]] = float(r["balance_cad"])
    sig = defaultdict(list)
    for r in read("financial_signals_monthly.csv"):
        sig[r["customer_id"]].append(r)
    events = defaultdict(list)
    for r in read("life_events.csv"):
        events[r["customer_id"]].append(r["event_type"])
    cards = {r["customer_id"]: r for r in read("card_accounts.csv")}

    people = []
    for cid, c in cust.items():
        w, k, hd = well[cid], cap[cid], hh[cid]
        stage = hd["life_stage"]
        lo, span = {"Young family": (30, 10), "Established family": (40, 12), "Pre-retirement": (56, 9)}.get(stage, (28, 30))
        people.append({
            "customer_id": cid, "name": c["full_name"], "segment": c["segment"], "branch_id": c["branch_id"], "branch": c["branch_name"],
            "province": c["province"], "homeowner": "Y", "linked_mortgage": "Y", "linked_cards": "Y" if cid in cards else "N",
            "wellness_band": w["wellness_band"], "outflow_share": float(w["competitor_outflow_share_pct"]),
            "email_consent": consent.get((cid, "Email"), "Not captured"), "income": float(k["gross_income_cad"]),
            "tds": float(k["tds_renewal_pct"]), "dependents": int(hd["dependents"]), "age": lo + h(cid, "age") % span,
            "tenure": int(c["tenure_years"]), "products": prods[cid], "signals": sig[cid], "events": events[cid],
            "mortgage": ren[cid], "card": cards.get(cid),
        })
    for cid, a in sorted(cards.items()):
        if a["linked_mortgage"] == "Y":
            continue
        seg = a["segment"]
        lo, span = {"Student / Young professional": (19, 7), "New to Canada": (24, 18), "High Net Worth": (40, 26)}.get(seg, (24, 38))
        x = h(cid, "dep") % 10
        people.append({
            "customer_id": cid, "name": a["customer_name"], "segment": seg, "branch_id": a["branch_id"], "branch": a["branch"],
            "province": a["province"], "homeowner": "N", "linked_mortgage": "N", "linked_cards": "Y",
            "wellness_band": a["wellness_band"], "outflow_share": 0.0, "email_consent": a["email_consent"],
            "income": float(a["income"]), "tds": None, "dependents": 0 if seg.startswith("Student") else 0 if x < 5 else 1 if x < 8 else 2,
            "age": lo + h(cid, "age") % span, "tenure": 1 + h(cid, "ten") % (3 if seg == "New to Canada" else 15),
            "products": {}, "signals": [], "events": [], "mortgage": None, "card": a,
        })
    return people


def base(p: dict) -> dict:
    return {"customer_id": p["customer_id"], "customer_name": p["name"], "segment": p["segment"], "branch_id": p["branch_id"],
            "branch": p["branch"], "province": p["province"], "linked_mortgage": p["linked_mortgage"], "linked_cards": p["linked_cards"]}


def client(p: dict) -> dict:
    return {"wellness_band": p["wellness_band"], "email_consent": p["email_consent"],
            "tds_renewal_pct": p["tds"] if p["tds"] is not None else ""}


def finish(out: list[dict]) -> list[dict]:
    out.sort(key=lambda x: (ORDER[x["play_type"]], x["eligibility"] != "Eligible", -x["value_at_stake_cad"]))
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return out


def grow_gate(p: dict, *extra: str | None) -> str:
    """Gate order for every promotional play: support-first (sales suppressed, RP-012), then hard blocks, then consent."""
    if p["wellness_band"] == "Vulnerable":
        return G_SUPPORT
    for e in extra:
        if e:
            return e
    return "Eligible" if p["email_consent"] == "Granted" else G_CONSENT


def play_row(acc_id: str, p: dict, book: str, kind: str, play: str, rec: str, why: str, gate: str, value: float, policy: str,
             purpose: str) -> dict:
    return {"account_id": acc_id, "customer_id": p["customer_id"], "book": book, "play_type": kind, "play": play,
            "recommended_product": rec, "rationale": why, "eligibility": gate, "value_at_stake_cad": round(value),
            "policy": policy, "purpose": purpose}


# --------------------------------------------------------------------------- #
# Book 1 - Everyday banking
# --------------------------------------------------------------------------- #
def banking(people: list[dict]) -> tuple[list, list, list, dict]:
    accounts, flows, actions, series = [], [], [], {}
    for p in people:
        cid, seg, band = p["customer_id"], p["segment"], p["wellness_band"]
        aid = f"DA-{cid[5:]}"
        x = u(cid, "pkg")
        pkg = ("Student" if seg.startswith("Student") and x < 0.7 else "Basic" if seg.startswith("Student") else
               "Ultimate" if seg == "High Net Worth" else
               ("Ultimate" if x < 0.4 else "Preferred") if seg == "Mass Affluent" else
               ("Preferred" if x < 0.6 else "Basic") if band in ("Vulnerable", "Stretched") else
               "Preferred" if x < 0.55 else "Basic" if x < 0.85 else "Ultimate")
        pk = PACKAGES[pkg]
        if p["linked_mortgage"] == "Y":
            chq = p["products"].get("PRD-CHQ") or p["products"].get("PRD-NEW") or round(p["income"] / 12 * (0.2 + 0.4 * u(cid, "chq")), -1)
            has_hisa = "PRD-SAV" in p["products"]
            sav = p["products"].get("PRD-SAV", 0.0)
            primary = True
        else:
            chq = round(p["income"] / 12 * (0.15 + 0.55 * u(cid, "chq")) * (2.5 if seg == "High Net Worth" else 1.6 if seg == "Mass Affluent" else 1), -1)
            has_hisa = u(cid, "hisa") < 0.35
            sav = round(p["income"] * (0.05 + 0.3 * u(cid, "sav")), -2) if has_hisa else 0.0
            primary = u(cid, "prim") < 0.65
        if band in ("Vulnerable", "Stretched"):
            chq = min(chq, 2400 + 1600 * u(cid, "cap"))
        tx = 6 + h(cid, "tx") % 26
        od_prot = u(cid, "odp") < 0.45
        has_card = p["linked_cards"] == "Y"
        falling = p["linked_mortgage"] == "N" and primary and band != "Vulnerable" and u(cid, "fall") < 0.15
        rows = []
        for k, m in enumerate(MONTHS):
            if p["signals"]:
                s = p["signals"][k]
                pay, out_ = float(s["payroll_inflow_cad"]), float(s["competitor_outflow_cad"])
                od, nsf = int(s["overdraft_days"]), int(s["nsf_count"])
            else:
                pay = (p["income"] / 12 * 0.72 * (0.97 + 0.06 * u(cid, m, "pay")) * (0.65 if falling and k >= 9 else 1)) if primary else 0.0
                out_ = pay * 0.03 * u(cid, m, "out")
                stress = band == "Vulnerable" or (p["card"] and p["card"]["behaviour"] == "Persistent debt" and u(cid, "odx") < 0.5)
                od = (h(cid, m, "od") % 7 + (3 if k >= 9 else 0)) if stress else (1 if u(cid, m, "od1") < 0.06 else 0)
                nsf = 1 if stress and k >= 9 and u(cid, m, "nsf") < 0.45 else 0
            end = chq * (0.85 + 0.3 * u(cid, m, "bal"))
            if od >= 5:
                end = -round(60 + 340 * u(cid, m, "neg"), -1)
            waived = pk["waiver"] is not None and end >= pk["waiver"]
            extra = max(0, tx - pk["included_tx"]) * EXTRA_TX_FEE if pk["included_tx"] else 0.0
            fees = (0 if waived else pk["fee"]) + extra + nsf * NSF_FEE + (od * OD_FEE_PER_DAY if od_prot else 0)
            rows.append({"account_id": aid, "customer_id": cid, "month": m, "payroll_in": round(pay, -1),
                         "transfers_to_other_institutions": round(out_, -1),
                         "bill_payments": round(p["income"] / 12 * 0.22 * (0.9 + 0.2 * u(cid, m, "bill")), -1),
                         "etransfers_out": round(p["income"] / 12 * 0.05 * (0.5 + u(cid, m, "et")), -1),
                         "nsf_count": nsf, "overdraft_days": od, "fees_charged": round(fees, 2), "end_balance": round(end, -1)})
        flows.extend(rows)
        series[aid] = {"title": "Payroll, transfers out and month-end balance", "lines": [
            {"label": "Payroll in", "values": [r["payroll_in"] for r in rows]},
            {"label": "Transfers to other institutions", "values": [r["transfers_to_other_institutions"] for r in rows]},
            {"label": "Month-end balance", "values": [r["end_balance"] for r in rows]}]}

        def cost(name: str) -> float:
            q = PACKAGES[name]
            ex = max(0, tx - q["included_tx"]) * EXTRA_TX_FEE * 12 if q["included_tx"] else 0.0
            return sum(0 if q["waiver"] is not None and r["end_balance"] >= q["waiver"] else q["fee"] for r in rows) + ex

        options = [n for n in PACKAGES if n != "Student" or seg.startswith("Student")]
        best = min(options, key=lambda n: (round(cost(n), 2), PACKAGES[n]["fee"]))
        acc = {"account_id": aid, **base(p), "package": pkg, "monthly_fee": pk["fee"],
               "fee_waiver_min_balance": pk["waiver"] or "", "avg_monthly_transactions": tx,
               "avg_chequing_balance": round(sum(r["end_balance"] for r in rows) / 12, -1), "savings_balance": round(sav, -1),
               "has_hisa": "Y" if has_hisa else "N", "has_card": "Y" if has_card else "N",
               "overdraft_protection": "Y" if od_prot else "N", "primary_banking": "Y" if primary else "N",
               "package_cost_12m": round(cost(pkg), 2), "best_fit_package": best, "best_fit_cost_12m": round(cost(best), 2),
               "fees_charged_12m": round(sum(r["fees_charged"] for r in rows), 2),
               "nsf_3m": sum(r["nsf_count"] for r in rows[-3:]), "overdraft_days_3m": sum(r["overdraft_days"] for r in rows[-3:]),
               "outflow_share_pct": p["outflow_share"], **client(p), "as_of_date": AS_OF}
        accounts.append(acc)
        actions.extend(banking_plays(acc, p, rows))
    return accounts, flows, actions, series


def banking_plays(a: dict, p: dict, rows: list[dict]) -> list[dict]:
    out = []
    aid, vul = a["account_id"], p["wellness_band"] == "Vulnerable"

    def add(*args):
        out.append(play_row(aid, p, "banking", *args))

    if a["nsf_3m"] > 0 or a["overdraft_days_3m"] >= 10 or vul:
        nsf_od_fees = sum(r["nsf_count"] * NSF_FEE + (r["overdraft_days"] * OD_FEE_PER_DAY if a["overdraft_protection"] == "Y" else 0) for r in rows)
        add("Support", "Overdraft/NSF support", "Fee refund (up to 2 per 12 months) and a budgeting conversation",
            f"{a['nsf_3m']} NSF item(s) and {a['overdraft_days_3m']} overdraft days in 3 months; overdraft protection "
            + ("on file" if a["overdraft_protection"] == "Y" else "not on file - only with express consent"),
            "Eligible", nsf_od_fees, "RP-024", "Service")
    shares = [r["transfers_to_other_institutions"] / r["payroll_in"] if r["payroll_in"] else 0 for r in rows[-6:]]
    consec = any(shares[i] >= 0.10 and shares[i + 1] >= 0.10 for i in range(len(shares) - 1))
    pay3 = sum(r["payroll_in"] for r in rows[-3:]) / 3
    pay6 = sum(r["payroll_in"] for r in rows[:6]) / 6
    falling = a["primary_banking"] == "Y" and pay6 > 0 and pay3 < pay6 * 0.85
    if a["primary_banking"] == "Y" and (consec or falling):
        why = (f"{max(shares) * 100:.0f}% of payroll moved to another institution, 2+ consecutive months" if consec else
               f"Payroll down {(1 - pay3 / pay6) * 100:.0f}% (last 3 vs first 6 months)")
        add("Retain", "Primary banking at risk", "Relationship review within 30 days (fee waiver up to 12 months)", why, grow_gate(p),
            (a["avg_chequing_balance"] + a["savings_balance"]) * 0.02 + a["monthly_fee"] * 12, "RP-018", "Marketing")
    saving = a["package_cost_12m"] - a["best_fit_cost_12m"]
    if saving >= 120 and a["best_fit_package"] != a["package"]:
        up = PACKAGES[a["best_fit_package"]]["fee"] > a["monthly_fee"]
        why = (f"Paying ${a['package_cost_12m']:,.0f}/yr on {a['package']}; {a['best_fit_package']} would cost ${a['best_fit_cost_12m']:,.0f} "
               f"for the same usage ({a['avg_monthly_transactions']} transactions/month) - saves ${saving:,.0f}/yr")
        if up:
            add("Grow", "Package fit", f"{a['best_fit_package']} package (balance waiver applies)", why, grow_gate(p), saving, "RP-023", "Marketing")
        else:
            add("Retain", "Package fit", f"{a['best_fit_package']} package", why, "Eligible", saving, "RP-023", "Service")
    sweep = a["avg_chequing_balance"] > 15000 and a["has_hisa"] == "N"
    if sweep:
        add("Grow", "Savings sweep", "High-interest savings account with automatic sweep",
            f"Average chequing balance ${a['avg_chequing_balance']:,.0f} earning no interest; no savings account",
            grow_gate(p), (a["avg_chequing_balance"] - 5000) * HISA_RATE / 100, "RP-011", "Marketing")
    held = 1 + (a["has_hisa"] == "Y") + (a["has_card"] == "Y")
    if held == 2 and not sweep:
        missing = "high-interest savings account" if a["has_hisa"] == "N" else "no-fee rewards card"
        credit = a["has_hisa"] == "Y"
        add("Grow", "Bundle completion", missing.capitalize(), f"Holds 2 of 3 everyday products (chequing, savings, card); missing a {missing}",
            grow_gate(p, G_TDS if credit and p["tds"] is not None and p["tds"] > TDS_LIMIT else None),
            120 if a["has_hisa"] == "N" else 150, "RP-013" if credit else "RP-011", "Marketing")
    return finish(out)


# --------------------------------------------------------------------------- #
# Book 2 - Borrowing
# --------------------------------------------------------------------------- #
def borrowing(people: list[dict], dep: dict[str, dict]) -> tuple[list, list, list, dict]:
    facilities, cands, actions, series = [], [], [], {}
    n = 5000
    for p in people:
        cid, band, card = p["customer_id"], p["wellness_band"], p["card"]
        rows = []

        def fac(kind: str, **kw) -> None:
            nonlocal n
            n += 1
            rows.append({"account_id": f"LN-{n}", **base(p), "facility_type": kind, **kw})

        m = p["mortgage"]
        if m:
            prop, mbal = float(m["property_value_cad"]), float(m["mortgage_balance_cad"])
            room = 0.8 * prop - mbal
            if u(cid, "hel") < 0.5 and room >= 25000:
                lim = round(min(250000, room) * (0.3 + 0.4 * u(cid, "hl")), -3)
                util = (0.45 + 0.4 * u(cid, "hu")) if band in ("Vulnerable", "Stretched") else 0.6 * u(cid, "hu")
                spread = 0.5 + round(0.5 * u(cid, "hs"), 2)
                fac("Secured line of credit (home equity)", rate_type="Variable", limit=lim, bal=lim * util, spread=spread,
                    combined_ltv=round((mbal + lim) / prop * 100, 1))
        revolving_card = card and card["behaviour"] in ("Revolver", "Persistent debt")
        if (revolving_card and not rows) or (not rows and u(cid, "ul") < 0.18):
            lim = round(5000 + 20000 * u(cid, "ull"), -3)
            util = (0.55 + 0.4 * u(cid, "ulu")) if band in ("Vulnerable", "Stretched") else 0.15 + 0.5 * u(cid, "ulu")
            spread = round((4.5 if band in ("Thriving", "Stable") else 6.0) + 2 * u(cid, "uls"), 2)
            fac("Unsecured line of credit", rate_type="Variable", limit=lim, bal=lim * util, spread=spread, combined_ltv="")
        if not p["segment"].startswith("Student") and u(cid, "auto") < 0.32:
            term = [60, 72, 84][h(cid, "at") % 3]
            left = 1 + h(cid, "al") % 3 if u(cid, "am") < 0.35 else 6 + h(cid, "al") % (term - 12)
            fac("Auto loan", rate_type="Fixed", original=round(22000 + 36000 * u(cid, "ao"), -2), rate=round(6.49 + 2.5 * u(cid, "ar"), 2),
                term=term, left=left)
        if u(cid, "pl") < 0.1 or (band == "Stretched" and u(cid, "pl") < 0.25):
            term = [36, 48, 60][h(cid, "pt") % 3]
            fac("Personal loan", rate_type="Fixed", original=round(8000 + 22000 * u(cid, "po"), -2), rate=round(9.49 + 3.5 * u(cid, "pr"), 2),
                term=term, left=8 + h(cid, "pll") % (term - 8))
        if not rows:
            continue
        missed = sum(int(s["missed_payments"]) for s in p["signals"][-3:]) if p["signals"] else 0
        dpd = (30 if missed or u(cid, "dpd") < 0.6 else 0) if band == "Vulnerable" else (15 if band == "Stretched" and u(cid, "dpd") < 0.12 else 0)
        if card and int(card["days_past_due"]):
            dpd = max(dpd, 30)
        out_rows = []
        for i, r in enumerate(rows):
            kind = r.pop("facility_type")
            if r.pop("rate_type") == "Variable":
                lim, bal = r.pop("limit"), round(r.pop("bal"), -1)
                rate = round(PRIME + r["spread"], 2)
                pay = bal * rate / 100 / 12 if kind.startswith("Secured") else max(50.0, bal * 0.03)
                rec = {"facility_type": kind, "rate_type": "Variable", "rate_pct": rate, "prime_spread_pct": r.pop("spread"),
                       "limit_or_original_cad": lim, "balance_cad": bal, "utilisation_pct": round(bal / lim * 100, 1),
                       "monthly_payment_cad": round(pay, 2), "term_months": "", "maturity_date": "", "days_to_maturity": "",
                       "combined_ltv_pct": r.pop("combined_ltv")}
                hist = [round(bal * (0.88 + 0.12 * k / 11 + 0.04 * (u(cid, kind, MONTHS[k]) - 0.5)), -1) for k in range(11)] + [bal]
            else:
                orig, rate, term, left = r.pop("original"), r.pop("rate"), r.pop("term"), r.pop("left")
                paid = term - left
                bal = round(remaining(orig, rate, term, paid), -1)
                mat = add_months(AS_OF_D, left)
                rec = {"facility_type": kind, "rate_type": "Fixed", "rate_pct": rate, "prime_spread_pct": "",
                       "limit_or_original_cad": orig, "balance_cad": bal, "utilisation_pct": round(bal / orig * 100, 1),
                       "monthly_payment_cad": round(amort(orig, rate, term), 2), "term_months": term,
                       "maturity_date": mat.isoformat(), "days_to_maturity": (mat - AS_OF_D).days, "combined_ltv_pct": ""}
                hist = [round(remaining(orig, rate, term, max(0, paid - (11 - k))), -1) for k in range(12)]
            f = {**r, **rec, "days_past_due": dpd if i == len(rows) - 1 else 0, **client(p), "as_of_date": AS_OF}
            out_rows.append(f)
            series[f["account_id"]] = {"title": "Balance - last 12 months", "lines": [{"label": "Balance", "values": hist}]}
        facilities.extend(out_rows)
        cand = consolidation(p, out_rows) if revolving_card else None
        if cand:
            cands.append(cand)
        for f in out_rows:
            actions.extend(borrowing_plays(f, p, cand if cand and cand["attach_account_id"] == f["account_id"] else None))
    return facilities, cands, actions, series


def consolidation(p: dict, facs: list[dict]) -> dict | None:
    card = p["card"]
    bal = float(card["balance"])
    if bal < 1500:
        return None
    apr = float(card["purchase_apr"])
    card_pay = max(10.0, bal * 0.03)
    target = next((f for f in facs if f["facility_type"].startswith("Secured")
                   and float(f["limit_or_original_cad"]) - float(f["balance_cad"]) >= bal), None)
    term = 60
    if not target:
        target = next((f for f in facs if f["facility_type"] == "Unsecured line of credit"
                       and float(f["limit_or_original_cad"]) - float(f["balance_cad"]) >= bal), None)
        term = 48
    if target:
        ttype, rate, attach = f"Existing {target['facility_type'].lower()}", float(target["rate_pct"]), target["account_id"]
    else:
        ttype, rate, term = "New personal loan", 9.99, 36
        attach = next((f["account_id"] for f in facs if f["rate_type"] == "Variable"), facs[0]["account_id"])
    new_pay = amort(bal, rate, term)
    # Cost at the card minimum: simulate repayment month by month (3% or $10 minimum).
    b, months, tot = bal, 0, 0.0
    while b > 0.5 and months < 600:
        i = b * apr / 100 / 12
        tot += i
        b = b + i - max(10.0, (b + i) * 0.03)
        months += 1
    new_tot = new_pay * term - bal
    tds = p["tds"]
    vul = p["wellness_band"] == "Vulnerable"
    return {"customer_id": p["customer_id"], "customer_name": p["name"], "card_account_id": card["account_id"],
            "card_behaviour": card["behaviour"], "card_balance_cad": round(bal), "card_apr_pct": apr,
            "card_min_payment_cad": round(card_pay, 2), "card_months_to_repay_at_minimum": months,
            "card_total_interest_at_minimum_cad": round(tot), "target_type": ttype, "target_rate_pct": rate, "term_months": term,
            "new_payment_cad": round(new_pay, 2), "new_total_interest_cad": round(new_tot),
            "interest_saved_annual_cad": round(bal * (apr - rate) / 100), "payment_falls": "Y" if new_pay < card_pay else "N",
            "linked_mortgage": p["linked_mortgage"], "tds_renewal_pct": tds if tds is not None else "",
            "tds_check": "n/a - no mortgage" if tds is None else "Within 44%" if tds <= TDS_LIMIT else "Above 44%",
            "treatment": "Support - Client Assistance" if vul else "Support - consolidation" if card["behaviour"] == "Persistent debt" else "Offer",
            "wellness_band": p["wellness_band"], "email_consent": p["email_consent"], "attach_account_id": attach, "as_of_date": AS_OF}


def afford_gate(tds, linked_mortgage: str, payment_falls: str) -> str | None:
    if linked_mortgage == "Y":
        return G_TDS if tds not in ("", None) and float(tds) > TDS_LIMIT else None
    return None if payment_falls == "Y" else G_PAYMENT


def borrowing_plays(f: dict, p: dict, cand: dict | None) -> list[dict]:
    out = []
    aid = f["account_id"]

    def add(*args):
        out.append(play_row(aid, p, "borrowing", *args))

    if f["days_past_due"]:
        add("Support", "Arrears support", "Hardship options and Client Assistance referral",
            f"{f['days_past_due']} days past due on {f['facility_type'].lower()} (payment ${f['monthly_payment_cad']:,.0f}/month)",
            "Eligible", f["monthly_payment_cad"] * max(1, f["days_past_due"] / 30), "RP-014", "Service")
    if cand:
        why = (f"Card balance ${cand['card_balance_cad']:,.0f} at {cand['card_apr_pct']}% -> {cand['target_type']} at {cand['target_rate_pct']}% "
               f"over {cand['term_months']} months: saves ~${cand['interest_saved_annual_cad']:,.0f}/yr; payment "
               f"${cand['card_min_payment_cad']:,.0f} -> ${cand['new_payment_cad']:,.0f}")
        aff = afford_gate(cand["tds_renewal_pct"], cand["linked_mortgage"], cand["payment_falls"])
        if cand["treatment"] == "Support - Client Assistance":
            add("Support", "Debt consolidation", "Client Assistance conversation (no new credit offered)", why, "Eligible",
                cand["interest_saved_annual_cad"], "RP-025", "Service")
        elif cand["treatment"] == "Support - consolidation":
            add("Support", "Debt consolidation", cand["target_type"], why, aff or "Eligible", cand["interest_saved_annual_cad"], "RP-025", "Service")
        else:
            add("Grow", "Debt consolidation", cand["target_type"], why, grow_gate(p, aff), cand["interest_saved_annual_cad"], "RP-025", "Marketing")
    if f["facility_type"] == "Auto loan" and f["days_to_maturity"] != "" and int(f["days_to_maturity"]) <= 90:
        add("Retain", "Auto loan maturing", "Maturity check-in and next-vehicle financing conversation",
            f"Auto loan matures {f['maturity_date']} ({f['days_to_maturity']} days); ${f['balance_cad']:,.0f} left",
            grow_gate(p), f["limit_or_original_cad"] * 0.03, "RP-011", "Marketing")
    if f["rate_type"] == "Variable" and f["balance_cad"] >= 10000:
        delta = f["balance_cad"] * 0.0025 / 12
        add("Protect", "Prime-rate change notice", "Payment-impact notice within 30 days of a prime change",
            f"Variable at prime + {f['prime_spread_pct']}% on ${f['balance_cad']:,.0f}: +/-25bp moves interest by ~${delta:,.2f}/month",
            "Eligible", f["balance_cad"] * 0.0025, "RP-026", "Service")
    if f["facility_type"].startswith("Secured") and (f["utilisation_pct"] >= 50 or set(p["events"]) & {"Home renovation", "Child starting university", "New baby", "Marriage"}):
        ltv = float(f["combined_ltv_pct"])
        block = G_LTV if ltv > 65 else G_TDS if p["tds"] is not None and p["tds"] > TDS_LIMIT else None
        add("Grow", "Home-equity re-advance", "Secured line re-advance (subject to approval)",
            f"Line {f['utilisation_pct']:.0f}% used; combined LTV {ltv:.0f}%", grow_gate(p, block),
            f["limit_or_original_cad"] * 0.15 * f["rate_pct"] / 100, "RP-025", "Marketing")
    return finish(out)


# --------------------------------------------------------------------------- #
# Book 3 - Investing
# --------------------------------------------------------------------------- #
def investing(people: list[dict], dep: dict[str, dict]) -> tuple[list, list, list, dict]:
    accounts, room, actions, series = [], [], [], {}
    n = 7000
    for p in people:
        cid, seg, band = p["customer_id"], p["segment"], p["wellness_band"]
        renter = p["homeowner"] == "N"
        holds = []
        if p["linked_mortgage"] == "Y":
            for pid, plan in (("PRD-TFSA", "TFSA"), ("PRD-RSP", "RRSP"), ("PRD-INV", "Non-registered")):
                if pid in p["products"]:
                    holds.append((plan, p["products"][pid]))
            if p["dependents"] and u(cid, "resp") < 0.4:
                holds.append(("RESP", round(4000 + 30000 * u(cid, "rv"), -2)))
            if seg == "High Net Worth" and u(cid, "nrg") < 0.6:
                holds.append(("Non-registered", round(50000 + 150000 * u(cid, "ng"), -3)))
        else:
            if u(cid, "tfsa") < 0.55:
                holds.append(("TFSA", round(p["income"] * (0.05 + 0.4 * u(cid, "tv")), -2)))
            if not seg.startswith("Student") and u(cid, "rrsp") < 0.3:
                holds.append(("RRSP", round(p["income"] * (0.1 + 0.6 * u(cid, "rrv")), -2)))
            if p["age"] <= 40 and u(cid, "fhsa") < 0.15:
                holds.append(("FHSA", round(FHSA_ANNUAL * (0.5 + 1.5 * u(cid, "fv")), -2)))
            if p["dependents"] and u(cid, "resp") < 0.3:
                holds.append(("RESP", round(3000 + 15000 * u(cid, "rv"), -2)))
            if seg == "High Net Worth":
                holds.append(("Non-registered", round(80000 + 200000 * u(cid, "ng"), -3)))
        kyc_months = 2 + h(cid, "kyc") % 52
        kyc_date = add_months(AS_OF_D, -kyc_months)
        risk = ("Conservative" if p["age"] >= 58 or band in ("Vulnerable", "Stretched") else
                ["Conservative", "Balanced", "Growth"][h(cid, "risk") % 3] if not seg.startswith("Student") else "Growth")
        mine = []
        for k, (plan, value) in enumerate(holds):
            n += 1
            x = u(cid, plan, str(k), "ht")
            ht = ("high-interest savings" if plan == "FHSA" and x < 0.5 else
                  "GIC" if (plan in ("TFSA", "RRSP") and x < 0.4) or (plan == "Non-registered" and x < 0.35) or (plan == "FHSA") else
                  "self-directed" if x > 0.85 and seg != "New to Canada" else "mutual fund" if plan != "TFSA" or x < 0.7 else "high-interest savings")
            mat, days, grate = "", "", ""
            if ht == "GIC":
                days = 5 + h(cid, plan, str(k), "md") % 84 if u(cid, plan, str(k), "mat") < 0.35 else 95 + h(cid, plan, str(k), "md") % 620
                mat = (AS_OF_D + timedelta(days=days)).isoformat()
                grate = round(3.1 + 1.2 * u(cid, plan, str(k), "gr"), 2)
            mine.append({"account_id": f"IV-{n}", **base(p), "plan": plan, "holding_type": ht, "market_value_cad": round(value, -1),
                         "gic_rate_pct": grate, "gic_maturity_date": mat, "days_to_maturity": days, "risk_profile": risk,
                         "kyc_last_updated": kyc_date.isoformat(), "kyc_age_months": kyc_months,
                         "kyc_status": "Stale" if kyc_months > 36 else "Current", "opened_year": 2026 - h(cid, plan, "oy") % max(1, min(p["tenure"], 15)),
                         **client(p), "as_of_date": AS_OF})
        tfsa_eligible = TFSA_CUMULATIVE_2026 if seg != "New to Canada" else 7000 * min(p["tenure"] + 1, 15)
        if p["age"] < 35:
            tfsa_eligible = min(tfsa_eligible, 7000 * max(1, p["age"] - 17))
        tfsa_value = sum(v for pl, v in holds if pl == "TFSA")
        has_resp = any(pl == "RESP" for pl, _ in holds)
        fhsa_open = any(pl == "FHSA" for pl, _ in holds)
        fhsa_elig = renter and 18 <= p["age"] < 71
        rr = {"customer_id": cid, "customer_name": p["name"], "age": p["age"], "homeowner": p["homeowner"],
              "tfsa_room_unused_cad": round(max(0, tfsa_eligible - tfsa_value * 0.85), -2),
              "rrsp_room_unused_cad": round(max(0, min(RRSP_MAX_2026, 0.18 * p["income"]) * (1 + 5 * u(cid, "rr"))
                                                - sum(v for pl, v in holds if pl == "RRSP") * 0.15), -2),
              "fhsa_eligible": "Y" if fhsa_elig else "N", "fhsa_opened": "Y" if fhsa_open else "N",
              "fhsa_room_unused_cad": (FHSA_ANNUAL * 2 - (sum(v for pl, v in holds if pl == "FHSA") if fhsa_open else 0)) if fhsa_elig else 0,
              "dependents": p["dependents"], "has_resp": "Y" if has_resp else "N",
              "cesg_missed_per_year_cad": 0 if has_resp else int(CESG_PER_CHILD * p["dependents"]),
              "savings_balance_cad": dep[cid]["savings_balance"], "kyc_status": "Stale" if kyc_months > 36 else "Current",
              "wellness_band": band, "email_consent": p["email_consent"], "as_of_date": AS_OF}
        room.append(rr)
        if not mine:
            continue
        accounts.extend(mine)
        primary = max(mine, key=lambda a: a["market_value_cad"])
        growth = {"Conservative": 0.0025, "Balanced": 0.004, "Growth": 0.0055}[risk]
        tot = sum(a["market_value_cad"] for a in mine)
        series[primary["account_id"]] = {"title": "Total invested value - last 12 months", "lines": [
            {"label": "Market value", "values": [round(tot / (1 + growth) ** (11 - k) * (1 + 0.01 * (u(cid, MONTHS[k], "mv") - 0.5)) if k < 11 else tot, -1)
                                                for k in range(12)]}]}
        actions.extend(investing_plays(primary, mine, rr, p))
    return accounts, room, actions, series


def investing_plays(prim: dict, mine: list[dict], rr: dict, p: dict) -> list[dict]:
    out = []
    aid = prim["account_id"]
    stale = prim["kyc_status"] == "Stale"
    kyc = G_KYC if stale else None

    def add(*args):
        out.append(play_row(aid, p, "investing", *args))

    total = sum(a["market_value_cad"] for a in mine)
    if stale:
        add("Protect", "KYC refresh required", "Know-your-client and risk-profile refresh with a licensed advisor",
            f"KYC last updated {prim['kyc_last_updated']} ({prim['kyc_age_months']} months) - recommendations paused", "Eligible", total, "RP-027", "Service")
    gics = [a for a in mine if a["holding_type"] == "GIC" and a["days_to_maturity"] != "" and int(a["days_to_maturity"]) <= 90]
    if gics:
        v = sum(a["market_value_cad"] for a in gics)
        first = min(gics, key=lambda a: int(a["days_to_maturity"]))
        add("Retain", "GIC maturing", "Maturity conversation with a licensed advisor",
            f"{len(gics)} GIC(s) worth ${v:,.0f} mature from {first['gic_maturity_date']} ({first['days_to_maturity']} days)",
            kyc or "Eligible", v, "RP-027", "Service")
    if rr["dependents"] and rr["has_resp"] == "N":
        add("Grow", "RESP grant left on the table", "RESP with the Canada Education Savings Grant",
            f"{rr['dependents']} dependent(s), no RESP: ~${rr['cesg_missed_per_year_cad']:,.0f}/yr of grant not collected",
            grow_gate(p, kyc), rr["cesg_missed_per_year_cad"], "RP-028", "Marketing")
    if rr["fhsa_eligible"] == "Y" and rr["fhsa_opened"] == "N" and rr["age"] <= 45:
        add("Grow", "FHSA for first-time buyers", "First Home Savings Account",
            f"Renter, age {rr['age']}, no FHSA: ${FHSA_ANNUAL:,}/yr tax-deductible room unused", grow_gate(p, kyc),
            FHSA_ANNUAL * 0.25, "RP-028", "Marketing")
    if rr["savings_balance_cad"] > 20000 and rr["tfsa_room_unused_cad"] > 10000:
        add("Grow", "Idle cash to TFSA", "TFSA contribution (within unused room)",
            f"${rr['savings_balance_cad']:,.0f} in taxable savings; ${rr['tfsa_room_unused_cad']:,.0f} TFSA room unused",
            grow_gate(p, kyc), min(rr["savings_balance_cad"], rr["tfsa_room_unused_cad"]) * HISA_RATE / 100 * 0.3, "RP-028", "Marketing")
    return finish(out)


# --------------------------------------------------------------------------- #
# Books 4-6 share these. New hash salts only, so books 1-3 are untouched.
# --------------------------------------------------------------------------- #
G_CASE = "Paused - open fraud case, no sales until resolved (RP-032)"
G_PREMIUM = "Blocked - premium not affordable, TDS above 44% (RP-031)"
G_CHANNEL = "Blocked - contact email changed during a security event; call the verified number on file (RP-032)"

BANK_TRANSFER_FEE = 3.99
BANK_FX_MARGIN = 1.5
# Synthetic quarterly scam-alert watch list (corridors named in recent fraud bulletins) - behaviour drives the play, not origin.
SCAM_WATCH = {"CA→IN", "CA→NG", "CA→PH"}
CORRIDOR = {"India": "CA→IN", "Philippines": "CA→PH", "Nigeria": "CA→NG", "China": "CA→CN", "Brazil": "CA→BR",
            "Ukraine": "CA→UA", "Mexico": "CA→MX", "Pakistan": "CA→PK", "Vietnam": "CA→VN", "Syria": "CA→JO"}
ORIGINS = list(CORRIDOR)
BRANCHES = {"BR-101": ("Toronto Bay & Bloor", "ON"), "BR-202": ("Montreal Plateau", "QC"), "BR-303": ("Calgary Centre Street", "AB")}
NEWCOMER_FREE_MONTHS = 12

# Newcomer-only clients CUST-3001..3015 (not in the mortgage, card, banking, borrowing or investing books).
# (name, origin, months in Canada, status, branch, income, wellness band, email consent, dependents, transfer provider, high-frequency sender)
NEWCOMERS = [
    ("Aarav Sharma", "India", 11, "Work permit", "BR-101", 78000, "Stable", "Granted", 0, "Other", True),
    ("Maria Santos", "Philippines", 14, "Permanent resident", "BR-303", 52000, "Stable", "Granted", 1, "Bank", True),
    ("Chinedu Okafor", "Nigeria", 30, "Permanent resident", "BR-101", 84000, "Thriving", "Granted", 2, "Other", False),
    ("Li Na Chen", "China", 3, "Study permit", "BR-202", 18000, "Stable", "Not captured", 0, None, False),
    ("Rafael Almeida", "Brazil", 26, "Permanent resident", "BR-202", 91000, "Thriving", "Not captured", 1, "Other", False),
    ("Olena Kovalenko", "Ukraine", 11, "Work permit", "BR-303", 46000, "Stretched", "Granted", 1, "Bank", False),
    ("Diego Hernandez", "Mexico", 19, "Work permit", "BR-303", 61000, "Stable", "Withdrawn", 0, "Other", False),
    ("Ayesha Siddiqui", "Pakistan", 40, "Permanent resident", "BR-101", 72000, "Stable", "Granted", 2, "Bank", False),
    ("Minh Nguyen", "Vietnam", 7, "Study permit", "BR-202", 22000, "Stretched", "Granted", 0, "Other", False),
    ("Omar Al-Khatib", "Syria", 15, "Permanent resident", "BR-202", 38000, "Vulnerable", "Not captured", 3, None, False),
    ("Priyanka Iyer", "India", 52, "Permanent resident", "BR-303", 98000, "Thriving", "Granted", 1, "Other", True),
    ("Joseph Mendoza", "Philippines", 10, "Work permit", "BR-101", 44000, "Stretched", "Granted", 0, "Other", True),
    ("Ngozi Adeyemi", "Nigeria", 2, "Permanent resident", "BR-303", 65000, "Stable", "Not captured", 1, "Other", True),
    ("Jun Hao Lin", "China", 33, "Work permit", "BR-101", 88000, "Thriving", "Granted", 0, "Bank", False),
    ("Kateryna Bondar", "Ukraine", 20, "Work permit", "BR-202", 57000, "Stable", "Granted", 2, "Bank", False),
]


def newcomer_people() -> list[dict]:
    out = []
    for i, (name, origin, months, status, br, inc, band, cons, deps, prov, hf) in enumerate(NEWCOMERS, 1):
        cid = f"CUST-{3000 + i}"
        out.append({"customer_id": cid, "name": name, "segment": "New to Canada", "branch_id": br, "branch": BRANCHES[br][0],
                    "province": BRANCHES[br][1], "homeowner": "N", "linked_mortgage": "N", "linked_cards": "N", "wellness_band": band,
                    "outflow_share": 0.0, "email_consent": cons, "income": float(inc), "tds": None, "dependents": deps,
                    "age": (19 + h(cid, "age") % 6) if status == "Study permit" else 24 + h(cid, "age") % 20, "tenure": months // 12,
                    "products": {}, "signals": [], "events": [], "mortgage": None, "card": None,
                    "origin": origin, "months": months, "status": status, "provider": prov, "hf": hf})
    return out


# --------------------------------------------------------------------------- #
# Book 4 - Newcomers & international money transfer (journey + transfers; plays after security)
# --------------------------------------------------------------------------- #
def newcomers_base(people: list[dict], nc_people: list[dict], dep: dict[str, dict], inv_cids: set[str]) -> tuple[list, list, dict]:
    journey, transfers, series = [], [], {}
    pop = [p for p in people if p["segment"] == "New to Canada"] + nc_people
    for p in pop:
        cid, only = p["customer_id"], p["customer_id"].startswith("CUST-3")
        aid = f"NC-{cid[5:]}"
        if only:
            origin, months, status, prov, hf = p["origin"], p["months"], p["status"], p["provider"], p["hf"]
            chq = round(p["income"] / 12 * (0.2 + 0.4 * u(cid, "nchq")), -1)
            has_sav = u(cid, "nsav") < 0.3
            sec_months = months - 2 if 4 <= months < 24 else 0
            stage = "No file" if months < 4 else "Secured card" if months < 24 else "Unsecured card"
            file_m = 0 if months < 4 else months - 2
            card_held = "secured card" if stage == "Secured card" else "unsecured card" if stage == "Unsecured card" else ""
            tx = 6 + h(cid, "ntx") % 26
        else:
            origin = ORIGINS[h(cid, "origin") % len(ORIGINS)]
            if p["linked_mortgage"] == "Y":
                months = min(60, 12 * max(2, p["tenure"]) + h(cid, "mic") % 12)
                status = "Permanent resident" if u(cid, "status") < 0.8 else "Work permit"
                stage, file_m = "Established", months - 1
            else:
                months = min(60, 12 * p["tenure"] + h(cid, "mic") % 12)
                x = u(cid, "status")
                status = "Permanent resident" if x < 0.5 else "Work permit" if x < 0.85 else "Study permit"
                file_m = months - 1
                stage = "Established" if file_m >= 36 else "Unsecured card"
            sec_months = 0
            d = dep[cid]
            chq, has_sav, tx = d["avg_chequing_balance"], d["has_hisa"] == "Y", d["avg_monthly_transactions"]
            card_held = "unsecured card" if p["linked_cards"] == "Y" or "PRD-CRD" in p["products"] else ""
            prov = None if u(cid, "send") >= 0.7 else "Other" if u(cid, "prov") < 0.45 else "Bank"
            hf = prov is not None and u(cid, "hf") < 0.35
        arrival = add_months(AS_OF_D, -months)
        expiry = add_months(arrival, NEWCOMER_FREE_MONTHS)
        active = only and expiry > AS_OF_D
        corridor = CORRIDOR[origin] if prov else ""
        products = ["chequing"] + (["savings"] if has_sav else []) + ([card_held] if card_held else []) \
            + (["mortgage"] if p["linked_mortgage"] == "Y" else []) + (["investing"] if cid in inv_cids else [])

        def pkg_cost(name: str) -> float:
            q = PACKAGES[name]
            ex = max(0, tx - q["included_tx"]) * EXTRA_TX_FEE * 12 if q["included_tx"] else 0.0
            return (0 if q["waiver"] is not None and chq >= q["waiver"] else q["fee"]) * 12 + ex

        nxt = min(("Basic", "Preferred", "Ultimate"), key=lambda n: (round(pkg_cost(n), 2), PACKAGES[n]["fee"]))
        rows = []
        if prov:
            other_fee = 0.0 if u(cid, "zfee") < 0.3 else round(2.99 + 9 * u(cid, "ofee"), 2)
            fx = BANK_FX_MARGIN if prov == "Bank" else round(2.4 + 1.6 * u(cid, "ofx"), 2)
            base_amt = p["income"] / 12 * (0.05 + 0.07 * u(cid, "amt"))
            for k, m in enumerate(MONTHS):
                here = months - (11 - k) > 0
                cnt = 0 if not here else (4 + h(cid, m, "cnt") % 3) if hf and k >= 9 else 1 + h(cid, m, "cnt") % 2 + (1 if hf else 0)
                amt = 0.0 if not cnt else round(base_amt * (0.85 + 0.3 * u(cid, m, "amt")) * (1.6 if hf and k >= 9 else 1), -1)
                fee = cnt * (BANK_TRANSFER_FEE if prov == "Bank" else other_fee)
                newr = (1 + h(cid, m, "nr") % 2 if hf and k >= 9 and k % 2 else 0) if cnt else 0
                rows.append({"account_id": aid, "customer_id": cid, "month": m, "corridor": corridor,
                             "provider": "Bank" if prov == "Bank" else "Other provider (remittance debit)",
                             "transfers_count": cnt, "amount_cad": amt, "fees_cad": round(fee, 2), "fx_margin_pct": fx,
                             "fx_cost_cad": round(amt * fx / 100, 2), "total_cost_cad": round(fee + amt * fx / 100, 2),
                             "bank_equivalent_cost_cad": round(cnt * BANK_TRANSFER_FEE + amt * BANK_FX_MARGIN / 100, 2),
                             "new_recipients": newr})
            transfers.extend(rows)
        last3 = rows[-3:]
        n12 = sum(r["transfers_count"] for r in rows)
        avg3 = sum(r["transfers_count"] for r in last3) / 3 if rows else 0
        newr90 = sum(r["new_recipients"] for r in last3)
        j = {"account_id": aid, **base(p), "origin_country": origin, "arrival_month": arrival.isoformat()[:7], "months_in_canada": months,
             "status": status, "products_held": "; ".join(products), "credit_file_months": file_m, "credit_building_stage": stage,
             "secured_card_months": sec_months, "secured_card_on_time": ("Y" if u(cid, "ontime") < 0.85 else "N") if sec_months else "",
             "newcomer_package_active": "Y" if active else "N", "package_expiry_month": expiry.isoformat()[:7],
             "days_to_package_expiry": (expiry - AS_OF_D).days if active else "", "next_package": nxt,
             "next_package_cost_12m": round(pkg_cost(nxt), 2), "avg_chequing_balance": chq, "avg_monthly_transactions": tx,
             "income": p["income"], "sends_abroad": "Y" if prov else "N", "corridor": corridor,
             "transfer_provider": "" if not prov else "Bank" if prov == "Bank" else "Other provider",
             "transfers_12m": n12, "sent_12m_cad": round(sum(r["amount_cad"] for r in rows)),
             "transfer_fees_12m_cad": round(sum(r["fees_cad"] for r in rows), 2),
             "fx_cost_12m_cad": round(sum(r["fx_cost_cad"] for r in rows), 2),
             "transfer_cost_12m_cad": round(sum(r["total_cost_cad"] for r in rows), 2),
             "bank_equivalent_cost_12m_cad": round(sum(r["bank_equivalent_cost_cad"] for r in rows), 2),
             "avg_transfers_last_3m": round(avg3, 1), "new_recipients_90d": newr90,
             "scam_watch_corridor": "Y" if corridor in SCAM_WATCH else "N",
             "scam_risk_sender": "Y" if avg3 >= 4 and newr90 >= 1 and corridor in SCAM_WATCH else "N",
             **client(p), "as_of_date": AS_OF}
        journey.append(j)
        if rows:
            series[aid] = {"title": "Money sent abroad and what it cost", "lines": [
                {"label": "Sent abroad", "values": [r["amount_cad"] for r in rows]},
                {"label": "Total cost (fees + FX margin)", "values": [r["total_cost_cad"] for r in rows]}]}
        else:
            series[aid] = {"title": "Chequing balance - last 12 months", "lines": [
                {"label": "Month-end balance", "values": [round(chq * (0.85 + 0.3 * u(cid, m, "ncb")), -1) if months - (11 - k) > 0 else 0
                                                          for k, m in enumerate(MONTHS)]}]}
    return journey, transfers, series


def newcomer_plays(j: dict, p: dict, case: str | None) -> list[dict]:
    out = []
    aid = j["account_id"]

    def add(*args):
        out.append(play_row(aid, p, "newcomers", *args))

    if j["newcomer_package_active"] == "Y" and int(j["days_to_package_expiry"]) <= 60:
        add("Retain", "Package expiry", f"{j['next_package']} package from {j['package_expiry_month']}",
            f"Fee-free newcomer period ends {j['package_expiry_month']} ({j['days_to_package_expiry']} days); lowest-cost fit for recorded usage is "
            f"{j['next_package']} (~${j['next_package_cost_12m']:,.0f}/yr)", "Eligible", j["next_package_cost_12m"], "RP-029", "Service")
    if j["credit_building_stage"] == "Secured card" and j["secured_card_months"] >= 12 and j["secured_card_on_time"] == "Y":
        add("Grow", "Credit-building next step", "Unsecured no-fee card (subject to approval)",
            f"Secured card {j['secured_card_months']} months, every payment on time - ready to graduate", grow_gate(p, case), 150, "RP-029", "Marketing")
    if j["sends_abroad"] == "Y":
        saving = j["transfer_cost_12m_cad"] - j["bank_equivalent_cost_12m_cad"]
        if j["transfer_provider"] == "Other provider" and saving >= 50:
            add("Grow", "Cheaper money transfer", f"International transfer with the Bank ({j['corridor']})",
                f"Sent ${j['sent_12m_cad']:,.0f} via another provider; fees ${j['transfer_fees_12m_cad']:,.0f} + FX margin ${j['fx_cost_12m_cad']:,.0f} "
                f"= ${j['transfer_cost_12m_cad']:,.0f}/yr vs ~${j['bank_equivalent_cost_12m_cad']:,.0f} with the Bank - saves ~${saving:,.0f}/yr",
                grow_gate(p, case), saving, "RP-030", "Marketing")
        elif j["transfer_provider"] == "Bank" and j["transfers_12m"] >= 30 and j["transfer_fees_12m_cad"] / 2 >= 50:
            add("Retain", "Cheaper money transfer", "Fewer, larger transfers (same FX margin)",
                f"{j['transfers_12m']} transfers in 12 months; combining them would save ~${j['transfer_fees_12m_cad'] / 2:,.0f}/yr in fees",
                "Eligible", j["transfer_fees_12m_cad"] / 2, "RP-030", "Service")
        if j["scam_risk_sender"] == "Y":
            add("Protect", "Remittance scam awareness", "Scam-awareness conversation and recipient verification",
                f"{j['avg_transfers_last_3m']:.0f} transfers/month lately to {j['corridor']} (on the scam-alert watch list); "
                f"{j['new_recipients_90d']} new recipient(s) in 90 days", "Eligible", j["sent_12m_cad"] * 0.25, "RP-030", "Service")
    if (j["status"] == "Permanent resident" and j["credit_file_months"] >= 24 and j["income"] >= 70000 and j["linked_mortgage"] == "N"):
        add("Grow", "Mortgage readiness", "First-home mortgage conversation (subject to approval and affordability)",
            f"Permanent resident, {j['credit_file_months']}-month credit file, income ${j['income']:,.0f}, renting",
            grow_gate(p, case), j["income"] * 0.01, "RP-013", "Marketing")
    return finish(out)


# --------------------------------------------------------------------------- #
# Book 6 - Security & fraud (cross-book). Built before the selling books so an open case pauses sales (RP-032).
# --------------------------------------------------------------------------- #
SCAM_TYPES = ("Phishing text reported", "New device login + payee added", "Large e-Transfer to new payee", "Remittance to new recipient")


def security(everyone: list[dict], dep: dict[str, dict], nj: dict[str, dict], tx: dict[str, list],
             depflows: dict[str, list]) -> tuple[list, list, dict]:
    events, posture, series = [], [], {}
    n = 9000
    for p in everyone:
        cid, card = p["customer_id"], p["card"]
        acc_dep = dep[cid]["account_id"] if cid in dep else nj[cid]["account_id"]
        mine = []

        def ev(acc: str, days: int, typ: str, sev: str, status: str, channel: str, amount: float, note: str) -> None:
            nonlocal n
            n += 1
            mine.append({"event_id": f"SE-{n}", "customer_id": cid, "customer_name": p["name"], "account_id": acc,
                         "event_date": (AS_OF_D - timedelta(days=days)).isoformat(), "days_ago": days, "event_type": typ,
                         "severity": sev, "status": status, "channel": channel, "amount_cad": round(amount, -1), "note": note})

        if card and int(card["fraud_alerts_90d"]):
            k = int(card["fraud_alerts_90d"])
            days = sorted(3 + h(cid, str(i), "fd") % 85 for i in range(k))
            for i, d in enumerate(days):
                sev = ("High" if k >= 3 else "Medium") if i == 0 else "Medium" if i == 1 else "Low"
                st = "Open" if i == 0 and d <= 30 else "Resolved"
                ev(card["account_id"], d, "Card fraud alert", sev, st, "Card monitoring", 80 + 1400 * u(cid, str(i), "fa"),
                   "Card blocked and reissued; disputed charges under review" if st == "Open" else "Client confirmed; charges reversed")
        if cid in nj and nj[cid]["scam_risk_sender"] == "Y":
            for i, r in enumerate(m for m in tx[cid][-3:] if m["new_recipients"]):
                d = 2 + h(cid, r["month"], "rd") % 25 + 30 * (11 - MONTHS.index(r["month"]))
                d = min(d, 89)
                big = r["amount_cad"] / max(1, r["transfers_count"]) >= 1500
                ev(nj[cid]["account_id"], d, "Remittance to new recipient", "High" if big else "Medium", "Open" if d <= 14 else "Resolved",
                   "International transfer", r["amount_cad"] / max(1, r["transfers_count"]),
                   "First transfer to this recipient - scam warning shown" + ("; held pending call-back" if d <= 14 else "; client confirmed recipient"))
        if p["age"] >= 58 and u(cid, "etx") < 0.4 or u(cid, "etx") < 0.04:
            held = p["age"] >= 58
            ev(acc_dep, 4 + h(cid, "etd") % 80, "Large e-Transfer to new payee", "High", "Resolved", "Online banking",
               2500 + 9500 * u(cid, "eta"),
               "Held and verified - client confirmed a scam, transfer cancelled" if held else "Held and verified - legitimate payee, released")
        if u(cid, "ndl") < 0.07:
            open_ = u(cid, "ndl2") < 0.6
            ev(acc_dep, 1 + h(cid, "ndd") % (20 if open_ else 85), "New device login + payee added", "High", "Open" if open_ else "Resolved",
               "Mobile app", 0, "Device not recognised; payee additions frozen pending verification" if open_ else "Client confirmed new phone")
        if u(cid, "phish") < 0.13:
            ev(acc_dep, 5 + h(cid, "phd") % 30, "Phishing text reported", "Low", "Resolved", "Reported via app", 0,
               "Client reported a text impersonating the Bank (July phishing wave); no details shared")
        if u(cid, "pwd") < 0.1:
            ev(acc_dep, 2 + h(cid, "pwdd") % 88, "Password reset", "Low", "Resolved", "Online banking", 0, "Reset completed from a known device")
        if not mine:
            continue
        mine.sort(key=lambda e: (e["days_ago"], e["event_id"]))
        events.extend(mine)
        open_dev = any(e["event_type"].startswith("New device") and e["status"] == "Open" for e in mine)
        old = p["age"] >= 58
        sid = f"SC-{cid[5:]}"
        posture.append({
            "account_id": sid, **base(p),
            "alerts_enabled": "Y" if u(cid, "alrt") < 0.6 else "N",
            "two_step_verification": "Y" if u(cid, "2sv") < (0.35 if old else 0.6) else "N",
            "digital_wallet": "Y" if card and u(cid, "wal") < 0.55 else "N",
            "trusted_contact_on_file": "Y" if old and u(cid, "tcp") < 0.4 else "N",
            "contact_email_changed_30d": "Y" if open_dev and u(cid, "emc") < 0.35 else "N",
            "last_security_checkin": (AS_OF_D - timedelta(days=30 + h(cid, "chk") % 700)).isoformat(),
            "events_90d": len(mine), "open_events": sum(e["status"] == "Open" for e in mine),
            "open_high_events": sum(e["status"] == "Open" and e["severity"] == "High" for e in mine),
            "high_events": sum(e["severity"] == "High" for e in mine), "scam_type_events": sum(e["event_type"] in SCAM_TYPES for e in mine),
            "latest_event": mine[0]["event_type"], "latest_event_date": mine[0]["event_date"],
            "amount_at_risk_cad": round(sum(e["amount_cad"] for e in mine if e["status"] == "Open")),
            "age": p["age"], **client(p), "as_of_date": AS_OF})
        flows = [r["etransfers_out"] for r in depflows[dep[cid]["account_id"]]] if cid in dep else None
        series[sid] = {"title": "Security events and e-Transfers - last 12 months", "lines": [
            {"label": "Security events", "values": [sum(e["event_date"][:7] == m for e in mine) for m in MONTHS]}]
            + ([{"label": "e-Transfers out ($)", "values": flows}] if flows else [])}
    return events, posture, series


def security_plays(s: dict, p: dict, evs: list[dict]) -> list[dict]:
    out = []
    aid = s["account_id"]
    gate = G_CHANNEL if s["contact_email_changed_30d"] == "Y" else "Eligible"

    def add(*args):
        out.append(play_row(aid, p, "security", *args))

    opened = [e for e in evs if e["status"] == "Open" and e["severity"] == "High"]
    if opened:
        add("Protect", "Open fraud case follow-up", "Verified call-back, close the case, confirm the client is safe",
            f"{len(opened)} open high-severity event(s): {opened[0]['event_type'].lower()} on {opened[0]['event_date']} - {opened[0]['note']}",
            gate, sum(e["amount_cad"] for e in opened), "RP-032", "Service")
    scam = [e for e in evs if e["event_type"] in SCAM_TYPES]
    if p["wellness_band"] in ("Vulnerable", "Stretched") and scam:
        add("Support", "Scam coaching", "Scam-coaching conversation; offer a trusted contact person and hold-and-verify",
            f"{len(scam)} scam-type event(s) (latest: {scam[0]['event_type'].lower()}); trusted contact on file: {s['trusted_contact_on_file']}",
            gate, sum(e["amount_cad"] for e in scam), "RP-032", "Service")
    med = [e for e in evs if e["severity"] == "Medium"]
    weak = s["two_step_verification"] == "N" and any(e["event_type"] in ("New device login + payee added", "Password reset") for e in evs)
    if med or weak:
        add("Protect", "Security check-in", "Review recent activity, devices and payees with the client",
            f"{len(med)} medium-severity event(s)" + ("; sign-in activity without 2-step verification" if weak else ""),
            gate, sum(e["amount_cad"] for e in med), "RP-022", "Service")
    gaps = [g for g, ok in (("transaction alerts", s["alerts_enabled"] == "Y"), ("2-step verification", s["two_step_verification"] == "Y")) if not ok]
    if gaps:
        add("Protect", "Enable alerts & 2-step", "Turn on " + " and ".join(gaps), f"Posture gap: {' and '.join(gaps)} off; last security check-in "
            f"{s['last_security_checkin']}", gate, 100 * len(gaps), "RP-022", "Service")
    return finish(out)


# --------------------------------------------------------------------------- #
# Book 5 - Insurance
# --------------------------------------------------------------------------- #
OPTIONAL_CREDITOR = ("Mortgage life", "Mortgage disability", "Line of credit protection", "Card balance protection")


def insurance(people: list[dict], cf: list[dict], open_case: set[str]) -> tuple[list, list, list, dict]:
    pols, gaps, actions, series = [], [], [], {}
    fac = defaultdict(list)
    for f in cf:
        fac[f["customer_id"]].append(f)
    hh = {r["primary_customer_id"]: r for r in read("households.csv")}
    travel = defaultdict(float)
    for r in read("card_spend_monthly.csv"):
        travel[r["account_id"]] += float(r["travel"])
    n = 8000
    for p in people:
        cid, card, m = p["customer_id"], p["card"], p["mortgage"]
        if not m and cid not in fac:
            continue
        mine = []

        def pol(typ: str, status: str, covered: float, premium: float, linked: str, start: date, lapse_days: int | None = None) -> None:
            nonlocal n
            n += 1
            lapse = (AS_OF_D - timedelta(days=lapse_days)).isoformat() if lapse_days is not None else ""
            mine.append({"policy_id": f"IN-{n}", "customer_id": cid, "customer_name": p["name"], "policy_type": typ,
                         "optional_creditor": "Y" if typ in OPTIONAL_CREDITOR else "N", "status": status,
                         "covered_amount_cad": round(covered, -2) if status != "Declined" else 0,
                         "monthly_premium_cad": round(premium, 2) if status == "Active" else 0.0,
                         "premium_when_active_cad": round(premium, 2) if status != "Declined" else 0.0,
                         "start_date": start.isoformat(), "lapse_date": lapse, "days_since_lapse": lapse_days if lapse_days is not None else "",
                         "linked_account_id": linked, "as_of_date": AS_OF})

        mbal = pay = 0.0
        if m:
            mbal = float(m["mortgage_balance_cad"])
            orig = date.fromisoformat(m["origination_date"])
            pay = amort(mbal, float(m["current_rate_pct"]), int(m["amortization_remaining_years"]) * 12)
            x = u(cid, "ml")
            share = 0.5 if hh[cid]["co_borrower_flag"] == "Y" and u(cid, "mls") < 0.4 else 1.0
            prem = mbal / 1000 * (0.10 + 0.006 * max(0, p["age"] - 30)) * share
            if x < 0.45:
                pol("Mortgage life", "Active", mbal * share, prem, m["renewal_id"], orig)
            elif x < 0.56:
                pol("Mortgage life", "Lapsed", mbal * share, prem, m["renewal_id"], orig, 10 + h(cid, "mlx") % 190)
            elif x < 0.75:
                pol("Mortgage life", "Declined", 0, 0, m["renewal_id"], orig)
            y = u(cid, "md")
            if y < 0.25:
                pol("Mortgage disability", "Active", pay, pay * 0.06, m["renewal_id"], orig)
            elif y < 0.31:
                pol("Mortgage disability", "Lapsed", pay, pay * 0.06, m["renewal_id"], orig, 10 + h(cid, "mdx") % 190)
            if u(cid, "home") < 0.35:
                pol("Home", "Active", float(m["property_value_cad"]) * 0.6, 90 + float(m["property_value_cad"]) / 1e6 * 60,
                    m["renewal_id"], add_months(AS_OF_D, -(2 + h(cid, "hst") % 30)))
        for f in fac.get(cid, []):
            if f["rate_type"] != "Variable":
                continue
            z = u(cid, f["account_id"], "lp")
            st = add_months(AS_OF_D, -(3 + h(cid, f["account_id"], "lps") % 60))
            if z < 0.3:
                pol("Line of credit protection", "Active", f["balance_cad"], f["balance_cad"] * 0.009, f["account_id"], st)
            elif z < 0.37:
                pol("Line of credit protection", "Lapsed", f["balance_cad"], f["balance_cad"] * 0.009, f["account_id"], st,
                    10 + h(cid, f["account_id"], "lpx") % 190)
        if card:
            cb = float(card["balance"])
            z = u(cid, "cbp")
            st = add_months(AS_OF_D, -(3 + h(cid, "cbs") % 48))
            if z < 0.22 and cb > 0:
                pol("Card balance protection", "Active", cb, cb * 0.0099, card["account_id"], st)
            elif z < 0.28 and cb > 0:
                pol("Card balance protection", "Lapsed", cb, cb * 0.0099, card["account_id"], st, 10 + h(cid, "cbx") % 190)
            if card["product_id"] == "CRD-TRVL":
                pol("Travel (card benefit)", "Active", 1000000, 0, card["account_id"], date(int(card["opened_year"]), 1, 15))
        pols.extend(mine)
        life = sum(q["covered_amount_cad"] for q in mine if q["policy_type"] == "Mortgage life" and q["status"] == "Active")
        opt = sum(q["monthly_premium_cad"] for q in mine if q["optional_creditor"] == "Y" and q["status"] == "Active")
        tr = travel[card["account_id"]] if card else 0.0
        aid = f"CV-{cid[5:]}"
        g = {"account_id": aid, **base(p), "mortgage_account_id": m["renewal_id"] if m else "",
             "mortgage_balance_cad": mbal, "days_to_renewal": int(m["days_to_maturity"]) if m else "",
             "mortgage_life_coverage_cad": life, "gap_amount_cad": round(max(0.0, mbal - life), -2),
             "dependents": p["dependents"], "has_disability_cover": "Y" if any(q["policy_type"] == "Mortgage disability" and q["status"] == "Active" for q in mine) else "N",
             "credit_balances_cad": round(sum(f["balance_cad"] for f in fac.get(cid, [])) + (float(card["balance"]) if card else 0)),
             "active_policies": sum(q["status"] == "Active" for q in mine),
             "policy_types": ", ".join(sorted({q["policy_type"] for q in mine if q["status"] == "Active"})) or "No active cover",
             "optional_premiums_monthly_cad": round(opt, 2), "lapsed_90d": sum(q["status"] == "Lapsed" and q["days_since_lapse"] <= 90 for q in mine),
             "premium_affordability_flag": "Y" if p["tds"] is not None and p["tds"] > TDS_LIMIT else "N",
             "card_product": card["product_name"] if card else "", "card_includes_travel": "Y" if card and card["product_id"] == "CRD-TRVL" else "N",
             "travel_spend_12m_cad": round(tr), "foreign_spend_share_pct": float(card["foreign_spend_share_pct"]) if card else 0.0,
             **client(p), "as_of_date": AS_OF}
        gaps.append(g)
        prem_series = [round(sum(q["premium_when_active_cad"] for q in mine if q["start_date"][:7] <= mo and q["status"] != "Declined"
                                 and (q["status"] == "Active" or mo < q["lapse_date"][:7])), 2) for mo in MONTHS]
        series[aid]= {"title": "Insurance premiums paid - last 12 months", "lines": [{"label": "Monthly premiums", "values": prem_series}]}
        actions.extend(insurance_plays(g, p, mine, G_CASE if cid in open_case else None))
    return pols, gaps, actions, series


def insurance_plays(g: dict, p: dict, mine: list[dict], case: str | None) -> list[dict]:
    out = []
    aid = g["account_id"]

    def add(*args):
        out.append(play_row(aid, p, "insurance", *args))

    if p["wellness_band"] in ("Vulnerable", "Stretched") and g["optional_premiums_monthly_cad"] > 0:
        types = sorted({q["policy_type"] for q in mine if q["optional_creditor"] == "Y" and q["status"] == "Active"})
        add("Support", "Premium affordability review", "Review whether optional cover is still needed and affordable - never auto-cancel",
            f"Pays ${g['optional_premiums_monthly_cad']:,.2f}/month for optional {', '.join(t.lower() for t in types)}; budget under pressure",
            "Eligible", g["optional_premiums_monthly_cad"] * 12, "RP-031", "Service")
    lapsed = [q for q in mine if q["status"] == "Lapsed" and q["days_since_lapse"] <= 90]
    if lapsed:
        q = min(lapsed, key=lambda x: x["days_since_lapse"])
        add("Retain", "Lapsed policy", "Check the lapse was intended (insurance is optional)",
            f"{q['policy_type']} lapsed {q['lapse_date']} ({q['days_since_lapse']} days ago) - ${q['covered_amount_cad']:,.0f} cover ended",
            "Eligible", sum(x["covered_amount_cad"] for x in lapsed) * 0.001 * 12, "RP-031", "Service")
    if g["linked_mortgage"] == "Y" and g["dependents"] > 0 and g["gap_amount_cad"] > 0:
        add("Grow", "Coverage gap on renewing mortgage", "Optional mortgage life cover conversation with an authorised advisor",
            f"{g['dependents']} dependent(s); mortgage ${g['mortgage_balance_cad']:,.0f} renews in {g['days_to_renewal']} days with "
            f"${g['mortgage_life_coverage_cad']:,.0f} life cover - gap ${g['gap_amount_cad']:,.0f}",
            grow_gate(p, case, G_PREMIUM if g["premium_affordability_flag"] == "Y" else None), g["gap_amount_cad"] * 0.001, "RP-031", "Marketing")
    if g["card_product"] and g["card_includes_travel"] == "N" and (g["travel_spend_12m_cad"] >= 3000 or g["foreign_spend_share_pct"] >= 14):
        add("Protect", "Travel cover check", "Information only: check what travel cover you already have",
            f"${g['travel_spend_12m_cad']:,.0f} travel spend in 12 months ({g['foreign_spend_share_pct']:.0f}% foreign) on a card without travel insurance",
            "Eligible", g["travel_spend_12m_cad"] * 0.05, "RP-031", "Service")
    return finish(out)


# --------------------------------------------------------------------------- #
def build() -> dict:
    people = population()
    da, flows, bna, s1 = banking(people)
    dep = {a["customer_id"]: a for a in da}
    cf, dcc, lna, s2 = borrowing(people, dep)
    ia, rr, ina, s3 = investing(people, dep)
    # Books 4-6 (read-only on the rows above).
    nc_people = newcomer_people()
    everyone = people + nc_people
    by_cid = {p["customer_id"]: p for p in everyone}
    depflows = defaultdict(list)
    for r in flows:
        depflows[r["account_id"]].append(r)
    nj, ntx, s4= newcomers_base(people, nc_people, dep, {a["customer_id"] for a in ia})
    nj_by = {j["customer_id"]: j for j in nj}
    tx_by = defaultdict(list)
    for r in ntx:
        tx_by[r["customer_id"]].append(r)
    se, sp, s6 = security(everyone, dep, nj_by, tx_by, depflows)
    ev_by = defaultdict(list)
    for e in se:
        ev_by[e["customer_id"]].append(e)
    open_case = {s["customer_id"] for s in sp if s["open_events"]}
    # RP-032 applies to every selling book: pause sales for clients with an open case, then re-rank.
    for plays in (bna, lna, ina):
        by_acct = defaultdict(list)
        for x in plays:
            if x["customer_id"] in open_case and x["eligibility"] == "Eligible" and (x["play_type"] == "Grow" or x["purpose"] == "Marketing"):
                x["eligibility"] = G_CASE
            by_acct[x["account_id"]].append(x)
        for grp in by_acct.values():
            finish(grp)
        plays.sort(key=lambda x: (x["account_id"], x["rank"]))
    sna = [a for s in sp for a in security_plays(s, by_cid[s["customer_id"]], ev_by[s["customer_id"]])]
    nna = [a for j in nj for a in newcomer_plays(j, by_cid[j["customer_id"]], G_CASE if j["customer_id"] in open_case else None)]
    ip, cg, ana, s5 = insurance(people, cf, open_case)
    return {"deposit_accounts": da, "deposit_flows_monthly": flows, "banking_next_actions": bna,
            "credit_facilities": cf, "debt_consolidation_candidates": dcc, "borrowing_next_actions": lna,
            "investment_accounts": ia, "registered_room": rr, "investing_next_actions": ina,
            "newcomer_journey": nj, "transfers_out_monthly": ntx, "newcomers_next_actions": nna,
            "insurance_policies": ip, "coverage_gaps": cg, "insurance_next_actions": ana,
            "security_events": se, "customer_security_posture": sp, "security_next_actions": sna,
            "_series": {"banking": s1, "borrowing": s2, "investing": s3, "newcomers": s4, "insurance": s5, "security": s6}}


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def summary(t: dict) -> None:
    for k, v in t.items():
        if not k.startswith("_"):
            print(f"  {k:34} {len(v):5} rows")
    band = {x["customer_id"]: x["wellness_band"] for k in ("deposit_accounts", "newcomer_journey") for x in t[k]}
    for book in ("banking", "borrowing", "investing", "newcomers", "insurance", "security"):
        acts = t[f"{book}_next_actions"]
        el = sum(a["eligibility"] == "Eligible" for a in acts)
        print(f"\n  [{book}] plays {len(acts)}  eligible {el}  blocked {len(acts) - el} ({(len(acts) - el) / max(1, len(acts)) * 100:.0f}%)")
        for (pt, pl), c in sorted(Counter((a["play_type"], a["play"]) for a in acts).items(), key=lambda x: ORDER[x[0][0]]):
            gates = Counter(a["eligibility"] for a in acts if a["play"] == pl and a["play_type"] == pt)
            print(f"    {pt:8} {pl:34} {c:3}  " + ", ".join(f"{g.split(' (')[0]}={n}" for g, n in gates.most_common()))
        sup = [a for a in acts if a["play_type"] == "Support"]
        bands = Counter(band[a["customer_id"]] for a in sup)
        print(f"    support plays by wellness band: {dict(bands)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    t = build()
    out = {HERE / f"{k}.csv": to_csv(v) for k, v in t.items() if not k.startswith("_")}
    bundle = {"as_of": AS_OF, "months": MONTHS, "prime_rate_pct": PRIME, "packages": PACKAGES, **t}
    out[OUT_BFF] = ('"""Product books (Everyday banking, Borrowing, Investing, Newcomers, Insurance, Security) for the BFF. GENERATED by '
                    'data/fabric-iq/generate_books_tables.py - do not edit.\n\n'
                    'Same rows as the Fabric IQ book tables plus 12-month series (synthetic demo data)."""\n\nimport json\n\nBOOKS = json.loads(r\'\'\''
                    + json.dumps(bundle, indent=1, ensure_ascii=False, sort_keys=True) + "''')\n")
    if a.check:
        stale = [p.name for p, c in out.items() if not p.exists() or p.read_text(encoding="utf-8") != c]
        print("FAIL stale: " + ", ".join(stale) if stale else "OK   book tables match the source")
        return 1 if stale else 0
    for p, c in out.items():
        p.write_text(c, encoding="utf-8", newline="")
    summary(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
