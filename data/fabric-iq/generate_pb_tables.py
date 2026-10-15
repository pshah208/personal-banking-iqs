"""Personal-banking tables for Fabric IQ, derived from the existing renewal book.

The 50 customers / 50 renewals / risk scores stay the source of truth. This
script adds the household, product, behavioural, consent and scenario data the
Customer 360, Financial Wellness and Scenarios features need - deterministically
(no randomness, no clock), so every run produces identical CSVs.

    households.csv                one row per customer household
    credit_capacity.csv           income, obligations, GDS/TDS now and at renewal
    customer_products.csv         holdings (same list the dashboard authors) + balances
    financial_signals_monthly.csv 12 months of behavioural signals per customer
    life_events.csv               dated life events (advisor notes / transaction patterns)
    consent_preferences.csv       CASL marketing consent per customer x channel
    financial_wellness.csv        wellness score, band, drivers, support pathway
    next_best_actions.csv         ranked, rule-gated actions per customer
    rate_scenario_presets.csv     governed scenario library (preset x factor)
    renewal_scenario_sensitivity.csv  per-renewal rate index + factor sensitivities

It also writes app/src/bff/app/pb_data.py so the BFF engines run on exactly the
same numbers Fabric IQ serves.

    python generate_pb_tables.py          # write
    python generate_pb_tables.py --check  # fail if anything is stale
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
BFF_OUT = DATA.parent / "app" / "src" / "bff" / "app" / "pb_data.py"
AS_OF = date(2026, 8, 3)
PERIODS = {"Monthly": 12, "Semi-monthly": 24, "Bi-weekly": 26, "Accelerated Bi-weekly": 26, "Weekly": 52}

spec = importlib.util.spec_from_file_location("snap", DATA / "generate_dashboard_snapshot.py")
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)  # type: ignore[union-attr]


def h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def u(*parts: str) -> float:
    """Stable pseudo-uniform in [0, 1)."""
    return h(*parts) / 0xFFFFFFFF


def read(name: str) -> list[dict]:
    with (HERE / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def annuity(balance: float, rate_pct: float, years: int, periods: int) -> float:
    r = rate_pct / 100 / periods
    n = max(1, years * periods)
    return balance * r / (1 - (1 + r) ** -n) if r else balance / n


CUSTOMERS = {r["customer_id"]: r for r in read("customers.csv")}
RENEWALS = read("mortgage_renewals.csv")
RISK = {r["renewal_id"]: r for r in read("renewal_risk_scores.csv")}
BY_CUST = {r["customer_id"]: r for r in RENEWALS}

# --------------------------------------------------------------------------- #
# Narrative cohorts - chosen from the data, not hand-picked names.
#   vulnerable : the highest payment shocks in budget-sensitive segments
#   flight     : rate shoppers / high attrition already moving deposits out
# --------------------------------------------------------------------------- #
_budget = [r for r in RENEWALS if CUSTOMERS[r["customer_id"]]["segment"] in ("Mass Market", "New to Canada", "Self-Employed")]
VULNERABLE = {r["customer_id"] for r in sorted(_budget, key=lambda r: -float(r["payment_shock_pct"]))[:8]}
FLIGHT = {r["customer_id"] for r in sorted(
    RENEWALS, key=lambda r: (-(RISK[r["renewal_id"]]["rate_shopping_signal"] == "Y"), -float(RISK[r["renewal_id"]]["attrition_risk_score"])))
    if r["customer_id"] not in VULNERABLE}
FLIGHT = {cid for cid in sorted(FLIGHT, key=lambda c: -float(RISK[BY_CUST[c]["renewal_id"]]["attrition_risk_score"]))[:7]}

SEG_INCOME_BETA = {"Self-Employed": 1.6, "New to Canada": 1.4, "Mass Market": 1.2, "Mass Affluent": 0.8, "High Net Worth": 0.4}
BUREAU = ["A", "B", "C", "D"]
BASE_PD = {"A": 0.004, "B": 0.009, "C": 0.020, "D": 0.045}
MONTHS = [f"{y}-{m:02d}" for y, m in
          [(2025, 9), (2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6), (2026, 7), (2026, 8)]]
LIFE_EVENTS = [
    ("New baby", "Transaction pattern", "Support"), ("Child starting university", "Customer stated", "Deepen"),
    ("Job change", "Payroll change", "Neutral"), ("Marriage", "Customer stated", "Deepen"),
    ("Retirement approaching", "Advisor note", "Deepen"), ("Home renovation", "Transaction pattern", "Deepen"),
    ("Inheritance received", "Transaction pattern", "Deepen"), ("Relocation", "Customer stated", "Neutral"),
]
VULN_EVENTS = [("Job loss", "Payroll change"), ("Reduced hours", "Payroll change"), ("Separation", "Advisor note"),
               ("Medical leave", "Customer stated")]


def build() -> dict[str, list[dict]]:
    households, capacity, products, signals, events, consent, wellness, nba = [], [], [], [], [], [], [], []
    for cid, c in CUSTOMERS.items():
        r = BY_CUST[cid]
        rk = RISK[r["renewal_id"]]
        seg = c["segment"]
        vul, fl = cid in VULNERABLE, cid in FLIGHT
        bal, value = float(r["mortgage_balance_cad"]), float(r["property_value_cad"])
        years, per = int(r["amortization_remaining_years"]), PERIODS.get(r["payment_frequency"], 12)
        p_now = annuity(bal, float(r["current_rate_pct"]), years, per) * per / 12
        p_renew = p_now * (1 + float(r["payment_shock_pct"]) / 100)
        tax_heat = value * 0.0085 / 12 + 150
        gds_target = (0.43 + 0.05 * u(cid, "g")) if vul else (0.36 + 0.035 * u(cid, "g")) if u(cid, "s") < 0.3 else (0.24 + 0.11 * u(cid, "g"))
        income = round((p_renew + tax_heat) / gds_target * 12, -2)
        other = round(income / 12 * (0.035 + 0.045 * u(cid, "o") + (0.07 if vul else 0)), -1)
        gds_now = (p_now + tax_heat) / (income / 12)
        gds_r = (p_renew + tax_heat) / (income / 12)
        tds_now, tds_r = gds_now + other / (income / 12), gds_r + other / (income / 12)
        bureau = "D" if vul and u(cid, "b") < 0.5 else "C" if vul else BUREAU[min(2, int(u(cid, "b") * 3))] if seg != "High Net Worth" else "A"
        hh = f"HH-{cid[5:]}"
        last = c["full_name"].split()[-1]
        members = 1 + (1 if u(cid, "m") < 0.65 else 0) + int(u(cid, "d") * 3) * (1 if seg != "New to Canada" else 1)
        dependents = max(0, members - 2) if members > 2 else 0
        households.append({
            "household_id": hh, "primary_customer_id": cid, "household_name": f"{last} household",
            "members": members, "dependents": dependents, "co_borrower_flag": "Y" if members >= 2 and u(cid, "cb") < 0.55 else "N",
            "gross_household_income_cad": int(income), "life_stage": (
                "Young family" if dependents and c["tenure_years"] and int(c["tenure_years"]) < 10 else
                "Established family" if dependents else "Pre-retirement" if int(c["tenure_years"]) >= 18 else "Couple / single"),
            "province": c["province"], "branch_id": c["branch_id"],
        })
        capacity.append({
            "customer_id": cid, "renewal_id": r["renewal_id"], "gross_income_cad": int(income),
            "monthly_other_debt_cad": int(other), "monthly_tax_heat_cad": round(tax_heat),
            "current_payment_monthly_cad": round(p_now), "renewal_payment_monthly_cad": round(p_renew),
            "gds_now_pct": round(gds_now * 100, 1), "tds_now_pct": round(tds_now * 100, 1),
            "gds_renewal_pct": round(gds_r * 100, 1), "tds_renewal_pct": round(tds_r * 100, 1),
            "bureau_band": bureau, "base_pd_12m_pct": round(BASE_PD[bureau] * 100, 2), "as_of_date": AS_OF.isoformat(),
        })

        held = snap.holdings_for(c, r, float(r["ltv_pct"]))
        for i, pid in enumerate(held):
            pr = snap.PRODUCTS_BY_ID[pid]
            scale = {"High Net Worth": 6, "Mass Affluent": 2.5}.get(seg, 1)
            bal_p = {"PRD-MTG": bal, "PRD-CHQ": 4200 * scale, "PRD-SAV": 15000 * scale, "PRD-CRD": 2600 * (1.6 if vul else 1),
                     "PRD-TFSA": 32000 * scale, "PRD-RSP": 58000 * scale, "PRD-INV": 140000 * scale, "PRD-WLT": 1_250_000,
                     "PRD-HEL": 38000, "PRD-INS": 0, "PRD-BIZ": 46000, "PRD-NEW": 2100}.get(pid, 0)
            bal_p *= 0.55 + 0.9 * u(cid, pid)
            if pid in ("PRD-CHQ", "PRD-SAV") and fl:
                bal_p *= 0.45
            products.append({"account_id": f"ACC-{cid[5:]}-{i + 1:02d}", "customer_id": cid, "household_id": hh,
                             "product_id": pid, "product_name": pr["name"].replace("CFC Bank ", ""), "category": pr["category"],
                             "balance_cad": round(bal_p, -1), "status": "Active",
                             "opened_year": max(1995, 2026 - int(c["tenure_years"]) + (i if i else 0))})

        sav0 = 15000 * {"High Net Worth": 6, "Mass Affluent": 2.5}.get(seg, 1)
        pay0 = income / 12 * 0.72
        for k, m in enumerate(MONTHS):
            late = max(0, k - 7)  # stress builds in the last 4 months
            stress = late / 4 if vul else 0
            payroll = pay0 * (1 - (0.35 * stress if u(cid, "jl") < 0.5 else 0.12 * stress)) * (0.97 + 0.06 * u(cid, m, "p"))
            outflow = (pay0 * (0.08 + 0.10 * late / 4) if fl else 0) * (0.8 + 0.4 * u(cid, m, "f"))
            signals.append({
                "customer_id": cid, "month": m, "payroll_inflow_cad": round(payroll, -1),
                "competitor_outflow_cad": round(outflow, -1),
                "overdraft_days": int(round(stress * (6 + 10 * u(cid, m, "od")))) + (1 if u(cid, m, "o1") < 0.08 else 0),
                "nsf_count": 1 if vul and late >= 3 and u(cid, m, "nsf") < 0.6 else 0,
                "missed_payments": 1 if vul and late == 4 and u(cid, "mp") < 0.6 else 0,
                "card_utilization_pct": round(min(99, (22 + 30 * u(cid, "cu")) + (45 * stress)), 1),
                "savings_balance_cad": round(max(0, sav0 * (1 - 0.6 * stress) * (0.9 + 0.2 * u(cid, m, "s"))), -1),
            })

        if vul:
            ev, src = VULN_EVENTS[h(cid, "ve") % len(VULN_EVENTS)]
            events.append({"event_id": f"LE-{cid[5:]}-1", "customer_id": cid, "event_type": ev,
                           "event_date": f"2026-0{4 + h(cid, 'vd') % 3}-{10 + h(cid, 'vdd') % 18}", "source": src,
                           "confidence": "High" if src != "Advisor note" else "Medium", "implication": "Support"})
        elif u(cid, "le") < 0.55:
            ev, src, imp = LIFE_EVENTS[h(cid, "e") % len(LIFE_EVENTS)]
            events.append({"event_id": f"LE-{cid[5:]}-1", "customer_id": cid, "event_type": ev,
                           "event_date": f"2026-0{2 + h(cid, 'ed') % 6}-{10 + h(cid, 'edd') % 18}", "source": src,
                           "confidence": "High" if src == "Customer stated" else "Medium", "implication": imp})

        for ch in ("Email", "SMS", "Phone"):
            x = u(cid, ch, "c")
            status = "Granted" if x < (0.72 if ch == "Email" else 0.5 if ch == "SMS" else 0.62) else "Withdrawn" if x < 0.86 else "Not captured"
            consent.append({"customer_id": cid, "purpose": "Marketing", "channel": ch, "consent_status": status,
                            "consent_type": "Express" if status == "Granted" and u(cid, ch, "t") < 0.7 else "Implied" if status == "Granted" else "",
                            "captured_date": f"20{22 + h(cid, ch) % 4}-0{1 + h(cid, ch, 'm') % 9}-15" if status != "Not captured" else "",
                            "expiry_date": "" if status != "Granted" else "none (express)" if False else ""})

        # wellness - computed from the signals just written
        rows = [s for s in signals if s["customer_id"] == cid]
        last3, prior = rows[-3:], rows[:6]
        pay_drop = 1 - (sum(s["payroll_inflow_cad"] for s in last3) / 3) / max(1, sum(s["payroll_inflow_cad"] for s in prior) / 6)
        od = sum(s["overdraft_days"] for s in last3)
        missed = sum(s["missed_payments"] for s in rows)
        nsf = sum(s["nsf_count"] for s in last3)
        util = last3[-1]["card_utilization_pct"]
        out_share = sum(s["competitor_outflow_cad"] for s in last3) / max(1, sum(s["payroll_inflow_cad"] for s in last3))
        sav_drop = 1 - last3[-1]["savings_balance_cad"] / max(1, rows[0]["savings_balance_cad"])
        drivers = []
        pts = 0.0
        for cond, w, label in [(pay_drop > 0.10, min(16, pay_drop * 45), f"Payroll down {pay_drop:.0%} vs prior 6 months"),
                               (od > 3, min(12, od * 0.5), f"{od} overdraft days in 3 months"),
                               (missed > 0, 10 * missed, f"{missed} missed payment(s)"),
                               (nsf > 0, 4 * nsf, f"{nsf} NSF item(s)"),
                               (util > 70, (util - 70) * 0.35, f"Card utilisation {util:.0f}%"),
                               (tds_r > 0.40, min(18, (tds_r - 0.40) * 160),
                                f"TDS at renewal {tds_r * 100:.1f}%" + (" (above 44% guideline)" if tds_r > 0.44 else "")),
                               (sav_drop > 0.35, sav_drop * 10, f"Savings down {sav_drop:.0%}"),
                               (out_share > 0.08, min(10, out_share * 50), f"{out_share:.0%} of payroll moving to another institution")]:
            if cond:
                pts += w
                drivers.append(label)
        score = max(12, round(94 - pts - 6 * u(cid, "w")))
        band = ("Vulnerable" if score < 45 or missed >= 1 or nsf >= 2 or (od > 15 and tds_r > 0.5) else "Stretched" if score < 72 or tds_r > 0.44 or out_share > 0.12
                else "Stable" if score < 90 else "Thriving")
        pathway = ("Amortization relief review (RP-006)" if band == "Vulnerable" and tds_r > 0.44 else
                   "Payment deferral assessment (RP-014)" if band == "Vulnerable" else
                   "Budgeting and renewal planning session" if band == "Stretched" else "None")
        wellness.append({"customer_id": cid, "wellness_score": score, "wellness_band": band,
                         "vulnerability_flag": "Y" if band == "Vulnerable" else "N",
                         "primary_driver": drivers[0] if drivers else "No adverse signals",
                         "drivers": "; ".join(drivers), "support_pathway": pathway,
                         "sales_suppressed": "Y" if band == "Vulnerable" else "N",
                         "competitor_outflow_share_pct": round(out_share * 100, 1), "as_of_date": AS_OF.isoformat()})

        # next best actions - rule-gated, ranked
        w = wellness[-1]
        email_ok = any(x["customer_id"] == cid and x["channel"] == "Email" and x["consent_status"] == "Granted" for x in consent)
        cands = []
        if w["vulnerability_flag"] == "Y":
            cands.append(("Support", "PRD-REL", 100, w["support_pathway"], "Eligible"))
        cands.append(("Retain", "PRD-MTG", 70 + float(rk["attrition_risk_score"]) * 30,
                      f"Renewal in {r['days_to_maturity']} days; attrition {rk['attrition_risk_band'].lower()} ({float(rk['attrition_risk_score']):.2f})",
                      "Eligible"))
        if fl:
            cands.append(("Retain", "PRD-CHQ", 72, f"{w['competitor_outflow_share_pct']}% of payroll moving to another institution", "Eligible"))
        heldset = set(held)
        ev = next((e for e in events if e["customer_id"] == cid), None)
        for pid, why, base in [("PRD-TFSA", "No TFSA; savings capacity", 40), ("PRD-HEL", "Equity available (LTV under 65%)", 38),
                               ("PRD-INS", "Mortgage not protected", 36), ("PRD-CRD", "No credit card with the Bank", 30),
                               ("PRD-RSP", "No retirement plan", 34)]:
            if pid in heldset:
                continue
            if pid == "PRD-HEL" and float(r["ltv_pct"]) > 65:
                continue
            boost = 18 if ev and ev["implication"] == "Deepen" and pid in ("PRD-TFSA", "PRD-RSP", "PRD-HEL", "PRD-INS") else 0
            gate = ("Suppressed - vulnerable customer (RP-012)" if w["vulnerability_flag"] == "Y" else
                    "Needs marketing consent (RP-011)" if not email_ok else "Eligible")
            cands.append(("Deepen", pid, base + boost + 10 * u(cid, pid, "n"),
                          why + (f"; life event: {ev['event_type'].lower()}" if boost else ""), gate))
        cands.sort(key=lambda x: (x[4] != "Eligible", -x[2]))
        for rank, (kind, pid, sc, why, gate) in enumerate(cands[:4], 1):
            nba.append({"customer_id": cid, "rank": rank, "action_type": kind, "product_id": pid,
                        "product_name": snap.PRODUCTS_BY_ID[pid]["name"].replace("CFC Bank ", ""),
                        "score": round(sc, 1), "rationale": why, "eligibility": gate})

    presets = scenario_presets()
    lib = [{"scenario_id": p["id"], "scenario_name": p["name"], "group": p["group"], "factor": f, "value": v,
            "note": p["note"], "as_of_date": AS_OF.isoformat()} for p in presets for f, v in p["factors"].items()]
    sens = []
    for r in RENEWALS:
        c = CUSTOMERS[r["customer_id"]]
        variable = "Variable" in r["product_type"]
        sens.append({"renewal_id": r["renewal_id"], "customer_id": r["customer_id"],
                     "rate_index": "BoC overnight" if variable else "GoC 5Y",
                     "rate_pass_through": 1.0 if variable else 0.9,
                     "income_beta_unemployment": SEG_INCOME_BETA[c["segment"]],
                     "attrition_beta_competitor_bp": round(0.0022 + 0.002 * (r["customer_id"] in FLIGHT), 4),
                     "insured_flag": r["insured_flag"], "as_of_date": AS_OF.isoformat()})
    return {"households": households, "credit_capacity": capacity, "customer_products": products,
            "financial_signals_monthly": signals, "life_events": events, "consent_preferences": consent,
            "financial_wellness": wellness, "next_best_actions": nba, "rate_scenario_presets": lib,
            "renewal_scenario_sensitivity": sens}


FACTORS = [
    {"id": "boc_bp", "label": "BoC overnight rate", "unit": "bp", "min": -200, "max": 200, "step": 25},
    {"id": "goc5_bp", "label": "GoC 5-year yield", "unit": "bp", "min": -150, "max": 150, "step": 5},
    {"id": "spread_bp", "label": "Mortgage spread", "unit": "bp", "min": -50, "max": 100, "step": 5},
    {"id": "competitor_gap_bp", "label": "Competitor undercut", "unit": "bp", "min": -20, "max": 80, "step": 5},
    {"id": "unemployment_pp", "label": "Unemployment rate", "unit": "pp", "min": -1, "max": 5, "step": 0.25},
    {"id": "inflation_pp", "label": "CPI inflation", "unit": "pp", "min": -1, "max": 5, "step": 0.25},
    {"id": "house_price_pct", "label": "House prices", "unit": "%", "min": -30, "max": 15, "step": 1},
]
GOOD_DIR = {"boc_bp": -1, "goc5_bp": -1, "spread_bp": -1, "competitor_gap_bp": -1, "unemployment_pp": -1,
            "inflation_pp": -1, "house_price_pct": 1}


def _f(**kw):
    out = {f["id"]: 0.0 for f in FACTORS}
    out.update(kw)
    return out


def scenario_presets() -> list[dict]:
    return [
        {"id": "base", "group": "market", "name": "Today's renewal book", "note": "Offered renewal rates as at 2026-08-03; no shock.", "factors": _f()},
        {"id": "soft-landing", "group": "market", "name": "Soft landing", "note": "BoC eases gradually; jobs hold; housing firms.",
         "factors": _f(boc_bp=-50, goc5_bp=-25, unemployment_pp=-0.25, house_price_pct=3)},
        {"id": "sticky-inflation", "group": "market", "name": "Sticky inflation", "note": "No cuts; yields and living costs higher for longer.",
         "factors": _f(boc_bp=50, goc5_bp=40, spread_bp=10, inflation_pp=1.5)},
        {"id": "housing-correction", "group": "market", "name": "Housing correction", "note": "Prices fall; spreads widen; modest job losses.",
         "factors": _f(goc5_bp=-10, spread_bp=20, unemployment_pp=1, house_price_pct=-15)},
        {"id": "recession", "group": "market", "name": "Recession watch", "note": "Unemployment jumps; BoC cuts hard; collateral falls.",
         "factors": _f(boc_bp=-100, goc5_bp=-50, spread_bp=35, unemployment_pp=2.5, house_price_pct=-10, inflation_pp=-0.5)},
        {"id": "price-war", "group": "market", "name": "Competitor price war", "note": "Big-bank and broker channel undercut renewals.",
         "factors": _f(spread_bp=-15, competitor_gap_bp=35)},
        {"id": "boc-easing", "group": "world", "name": "Bank of Canada easing",
         "note": "Rate cuts continue: variable payments ease and fixed rates drift lower.",
         "web_query": "latest Bank of Canada interest rate decision, forward guidance and market expectations for further cuts or hikes",
         "channels": "Lower overnight rate eases variable and prime-linked payments; 5-year yields follow partly.",
         "factors": _f(boc_bp=-50, goc5_bp=-20, inflation_pp=-0.25)},
        {"id": "fixed-rates-rise", "group": "world", "name": "Fixed mortgage rates rising",
         "note": "Bond yields push 5-year fixed rates up ahead of renewal.",
         "web_query": "Government of Canada 5-year bond yield moves and changes to 5-year fixed mortgage rates at Canadian lenders",
         "channels": "Higher 5-year yields re-price fixed renewals; payment shock grows for fixed-rate clients.",
         "factors": _f(goc5_bp=40, spread_bp=10)},
        {"id": "cost-of-living", "group": "world", "name": "Cost-of-living pressure",
         "note": "Grocery, rent and utility inflation squeezes household budgets.",
         "web_query": "latest Canadian CPI release, grocery and shelter inflation, and household cost-of-living pressure",
         "channels": "Higher living costs raise obligations in TDS; the BoC leans cautious.",
         "factors": _f(inflation_pp=1.25, boc_bp=25)},
        {"id": "jobs-softening", "group": "world", "name": "Labour market softening",
         "note": "Hiring slows and unemployment ticks up, especially for newer workers.",
         "web_query": "latest Statistics Canada Labour Force Survey: unemployment rate, job gains or losses and wage growth",
         "channels": "Income risk rises for budget-sensitive segments; affordability tightens.",
         "factors": _f(unemployment_pp=1.0, boc_bp=-25)},
        {"id": "housing-cooling", "group": "world", "name": "Housing market cooling",
         "note": "Sales slow and prices soften in major Canadian markets.",
         "web_query": "latest CREA home sales and price data and Canadian housing market outlook",
         "channels": "Lower prices raise loan-to-value; equity-based options narrow.",
         "factors": _f(house_price_pct=-6, spread_bp=5)},
        {"id": "lender-promotions", "group": "world", "name": "Lender rate promotions",
         "note": "Other lenders and brokers advertise sharp renewal and switch rates.",
         "web_query": "current mortgage renewal and switch rate promotions advertised by Canadian banks, credit unions and mortgage brokers",
         "channels": "Competitor undercut raises attrition, especially for rate-shopping clients.",
         "factors": _f(competitor_gap_bp=30, spread_bp=-5)},
    ]


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def bff_module(tables: dict[str, list[dict]]) -> str:
    payload = {
        "as_of": AS_OF.isoformat(), "factors": FACTORS, "good_dir": GOOD_DIR,
        "presets": scenario_presets(),
        "world_severity": {"dormant": 0.25, "low": 0.5, "elevated": 0.75, "high": 1.0, "severe": 1.3},
        "valuation": {"funding_margin_bps": 125, "default_given_delinquency": 0.2, "mortgage_revenue_share": 0.7, "spread_share": 0.15, "discount_pct": 6.0, "horizon_years": 5,
                      "gds_limit_pct": 39.0, "tds_limit_pct": 44.0, "lgd_insured": 0.02, "lgd_floor": 0.12,
                      "unemployment_income_haircut": 2.5, "inflation_obligation_uplift": 1.5},
        "customers": CUSTOMERS, "renewals": {r["renewal_id"]: r for r in RENEWALS}, "risk": RISK,
        "products_catalogue": {k: {"name": v["name"].replace("CFC Bank ", ""), "category": v["category"], "summary": v["summary"]}
                               for k, v in snap.PRODUCTS_BY_ID.items()},
        **tables,
    }
    body = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True)
    return ('"""Personal-banking data for the BFF engines. GENERATED by data/fabric-iq/generate_pb_tables.py - do not edit.\n\n'
            'Same rows as the Fabric IQ tables (synthetic demo data)."""\n\nimport json\n\nPB = json.loads(r\'\'\'' + body + "''')\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    tables = build()
    out = {HERE / f"{k}.csv": to_csv(v) for k, v in tables.items()}
    out[BFF_OUT] = bff_module(tables)
    if args.check:
        stale = [p.name for p, c in out.items() if not p.exists() or p.read_text(encoding="utf-8") != c]
        print("FAIL stale: " + ", ".join(stale) if stale else "OK   personal-banking tables match the source")
        return 1 if stale else 0
    for p, c in out.items():
        p.write_text(c, encoding="utf-8", newline="")
    for k, v in tables.items():
        print(f"  {k:30} {len(v):4} rows")
    w = tables["financial_wellness"]
    print("  wellness bands:", {b: sum(1 for x in w if x["wellness_band"] == b) for b in ("Thriving", "Stable", "Stretched", "Vulnerable")})
    print("  vulnerable:", sorted(VULNERABLE), "\n  deposit flight:", sorted(FLIGHT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
