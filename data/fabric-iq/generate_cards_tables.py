"""Cards book for Fabric IQ - deterministic synthetic data linked to the mortgage book.

Card products are brand-neutral (the demo switches between banks). 22 card
accounts belong to existing mortgage customers (customer_products PRD-CRD), so
their financial-wellness band and consent carry across books; 38 more belong to
card-only customers. No randomness, no clock.

    card_products.csv       product shelf (fee, APR, rewards, eligibility)
    card_accounts.csv       one row per account: limit, balance, behaviour, fee date, consent
    card_spend_monthly.csv  12 months of spend by category, payments, statement balance
    card_next_actions.csv   rule-gated plays per account (support / retain / grow / protect)

Also extends app/src/bff/app/pb_data.py via generate_pb_tables (imported).

    python generate_cards_tables.py [--check]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_BFF = HERE.parent.parent / "app" / "src" / "bff" / "app" / "cards_data.py"
AS_OF = "2026-08-03"
MONTHS = ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]


def h(*p: str) -> int:
    return int(hashlib.sha256("|".join(p).encode()).hexdigest()[:8], 16)


def u(*p: str) -> float:
    return h(*p) / 0xFFFFFFFF


def read(name: str) -> list[dict]:
    with (HERE / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


PRODUCTS = [
    {"product_id": "CRD-GOLD", "product_name": "Gold Rewards Card", "tier": "Premium rewards", "annual_fee": 120, "purchase_apr": 21.99,
     "rewards": "5x groceries and dining, 3x streaming, 1x everything else", "fx_fee": "2.5%", "min_income": 12000, "welcome_bonus_points": 50000},
    {"product_id": "CRD-TRVL", "product_name": "Travel Infinite Card", "tier": "Premium travel", "annual_fee": 150, "purchase_apr": 20.99,
     "rewards": "3x groceries and dining, 2x transit, lounge passes", "fx_fee": "none", "min_income": 60000, "welcome_bonus_points": 40000},
    {"product_id": "CRD-CASH", "product_name": "Cash Back Card", "tier": "Cash back", "annual_fee": 39, "purchase_apr": 20.99,
     "rewards": "4% groceries and recurring bills, 1% everything else", "fx_fee": "2.5%", "min_income": 12000, "welcome_bonus_points": 0},
    {"product_id": "CRD-NOFEE", "product_name": "No-Fee Rewards Card", "tier": "Everyday", "annual_fee": 0, "purchase_apr": 19.99,
     "rewards": "2x groceries and dining, 1x everything else", "fx_fee": "2.5%", "min_income": 12000, "welcome_bonus_points": 5000},
    {"product_id": "CRD-LOW", "product_name": "Low-Rate Card", "tier": "Low rate", "annual_fee": 29, "purchase_apr": 12.99,
     "rewards": "none - lower interest", "fx_fee": "2.5%", "min_income": 12000, "welcome_bonus_points": 0},
    {"product_id": "CRD-STU", "product_name": "Student Card", "tier": "Starter", "annual_fee": 0, "purchase_apr": 19.99,
     "rewards": "1x everything", "fx_fee": "2.5%", "min_income": 0, "welcome_bonus_points": 0},
]
PBY = {p["product_id"]: p for p in PRODUCTS}
CATS = ["groceries", "dining", "travel", "gas_transit", "bills", "online", "other"]
FIRST = ["Amara", "Bianca", "Callum", "Dev", "Elena", "Felix", "Grace", "Hamza", "Isla", "Jun", "Kiran", "Lucas", "Maya", "Noah",
         "Olivia", "Pierre", "Quinn", "Rosa", "Samir", "Tara", "Uma", "Victor", "Wen", "Ximena", "Yara", "Zane", "Ana", "Ben",
         "Chloe", "Diego", "Emma", "Farid", "Gia", "Hugo", "Ines", "Jonah", "Keira", "Liam"]
LAST = ["Abara", "Bouchard", "Chen", "Desrosiers", "Ellis", "Fortin", "Gill", "Haddad", "Ito", "Jansen", "Khan", "Lavoie", "Mensah",
        "Nguyen", "Okafor", "Pelletier", "Qureshi", "Roy", "Singh", "Tremblay", "Ueda", "Vasquez", "Walsh", "Xu", "Yilmaz", "Zhang"]
BRANCHES = [("BR-101", "Toronto Bay & Bloor", "ON"), ("BR-202", "Montreal Plateau", "QC"), ("BR-303", "Calgary Centre Street", "AB")]


def build() -> dict[str, list[dict]]:
    cust = {r["customer_id"]: r for r in read("customers.csv")}
    well = {r["customer_id"]: r for r in read("financial_wellness.csv")}
    cap = {r["customer_id"]: r for r in read("credit_capacity.csv")}
    consent = {(r["customer_id"], r["channel"]): r["consent_status"] for r in read("consent_preferences.csv")}
    holders = [r["customer_id"] for r in read("customer_products.csv") if r["product_id"] == "PRD-CRD"]

    people = []
    for cid in holders:
        c = cust[cid]
        people.append({"customer_id": cid, "name": c["full_name"], "segment": c["segment"], "branch_id": c["branch_id"],
                       "branch": c["branch_name"], "province": c["province"], "linked_mortgage": "Y",
                       "wellness_band": well[cid]["wellness_band"], "email_consent": consent.get((cid, "Email"), "Not captured"),
                       "income": float(cap[cid]["gross_income_cad"]), "tds": float(cap[cid]["tds_renewal_pct"])})
    for i in range(38):
        cid = f"CUST-{2001 + i}"
        seg = ["Mass Market", "Mass Affluent", "Student / Young professional", "New to Canada", "High Net Worth"][h(cid, "s") % 5 if i % 7 else 2]
        br = BRANDS_IDX = BRANCHES[h(cid, "b") % 3]
        stress = u(cid, "st")
        band = "Vulnerable" if stress < 0.10 else "Stretched" if stress < 0.28 else "Stable" if stress < 0.55 else "Thriving"
        x = u(cid, "c")
        people.append({"customer_id": cid, "name": f"{FIRST[i]} {LAST[h(cid, 'l') % len(LAST)]}", "segment": seg, "branch_id": br[0],
                       "branch": br[1], "province": br[2], "linked_mortgage": "N", "wellness_band": band,
                       "email_consent": "Granted" if x < 0.7 else "Withdrawn" if x < 0.85 else "Not captured",
                       "income": round({"High Net Worth": 260000, "Mass Affluent": 135000, "Student / Young professional": 38000,
                                        "New to Canada": 62000}.get(seg, 78000) * (0.75 + 0.5 * u(cid, "i")), -2), "tds": None})
        del BRANDS_IDX

    accounts, spend, actions = [], [], []
    for n, p in enumerate(people):
        cid = p["customer_id"]
        seg, band = p["segment"], p["wellness_band"]
        prod = ("CRD-STU" if seg.startswith("Student") else
                "CRD-TRVL" if seg == "High Net Worth" or (seg == "Mass Affluent" and u(cid, "p") < 0.35) else
                "CRD-GOLD" if seg == "Mass Affluent" or u(cid, "p") < 0.25 else
                "CRD-CASH" if u(cid, "p") < 0.55 else "CRD-LOW" if band in ("Vulnerable", "Stretched") and u(cid, "lr") < 0.4 else "CRD-NOFEE")
        pr = PBY[prod]
        limit = round(min(40000, max(1500, p["income"] * (0.035 + 0.10 * u(cid, "lim")))), -2)
        base_spend = min(limit * 0.55, p["income"] / 12 * (0.10 + 0.14 * u(cid, "sp"))) * (1.4 if prod in ("CRD-GOLD", "CRD-TRVL") else 1)
        behaviour = ("Persistent debt" if band == "Vulnerable" or (band == "Stretched" and u(cid, "pd") < 0.6) else
                     "Revolver" if u(cid, "rv") < 0.25 else "Transactor")
        decline = (u(cid, "dc") < 0.12 and behaviour == "Transactor")
        travel_heavy = u(cid, "tv") < 0.25
        bal = 0.0
        min_only = 0
        fx_total = 0.0
        rows = []
        for k, m in enumerate(MONTHS):
            f = 1.0 - (0.55 * max(0, k - 7) / 4 if decline else 0) + 0.12 * (u(cid, m, "seas") - 0.5) + (0.25 if m in ("2025-12",) else 0)
            s = max(0.0, base_spend * f)
            mix = {"groceries": 0.24, "dining": 0.12, "travel": 0.16 if travel_heavy else 0.04, "gas_transit": 0.1, "bills": 0.16,
                   "online": 0.12, "other": 0.1}
            tot = sum(mix.values())
            cats = {c: round(s * mix[c] / tot, -1) for c in CATS}
            fx = s * (0.14 if travel_heavy else 0.03)
            fx_total += fx
            interest = bal * pr["purchase_apr"] / 100 / 12 if behaviour != "Transactor" else 0
            if behaviour == "Transactor":
                pay = bal + s if k else s
                bal_end = s
            elif behaviour == "Revolver":
                pay = (bal + s + interest) * (0.45 + 0.2 * u(cid, m, "pp"))
                bal_end = bal + s + interest - pay
            else:
                pay = max(10.0, (bal + s + interest) * 0.03)
                min_only += 1
                bal_end = min(limit * 0.98, bal + s + interest - pay + (limit * 0.03 if k > 6 else 0))
            if k == 0 and behaviour != "Transactor":
                bal_end = limit * (0.35 if behaviour == "Revolver" else 0.72)
            bal = bal_end
            rows.append({"account_id": f"CA-{cid[5:]}", "month": m, "spend": round(s, -1), **{c: cats[c] for c in CATS},
                         "foreign_spend": round(fx, -1), "payment": round(pay, -1), "interest_charged": round(interest, 2),
                         "statement_balance": round(bal_end, -1)})
        spend.extend(rows)
        last3 = sum(r["spend"] for r in rows[-3:]) / 3
        prior6 = sum(r["spend"] for r in rows[:6]) / 6 or 1
        trend = (last3 / prior6 - 1) * 100
        util = bal / limit * 100
        fee_days = 10 + h(cid, "fee") % 200
        dpd = 30 if behaviour == "Persistent debt" and band == "Vulnerable" and u(cid, "dpd") < 0.6 else 0
        points = round(sum(r["spend"] for r in rows) * (3 if prod in ("CRD-GOLD", "CRD-TRVL") else 1.5 if prod != "CRD-LOW" else 0))
        acc = {
            "account_id": f"CA-{cid[5:]}", "customer_id": cid, "customer_name": p["name"], "segment": seg,
            "branch_id": p["branch_id"], "branch": p["branch"], "province": p["province"], "linked_mortgage": p["linked_mortgage"],
            "product_id": prod, "product_name": pr["product_name"], "annual_fee": pr["annual_fee"], "purchase_apr": pr["purchase_apr"],
            "opened_year": 2026 - (1 + h(cid, "o") % 14) if not seg.startswith("Student") else 2025,
            "credit_limit": limit, "balance": round(bal, -1), "utilization_pct": round(util, 1),
            "behaviour": behaviour, "min_payment_months_12m": min_only, "days_past_due": dpd,
            "monthly_spend_avg": round(sum(r["spend"] for r in rows) / 12, -1), "spend_trend_pct": round(trend, 1),
            "foreign_spend_share_pct": round(fx_total / max(1, sum(r["spend"] for r in rows)) * 100, 1),
            "top_category": max(CATS, key=lambda c: sum(r[c] for r in rows)),
            "rewards_points": points, "fee_anniversary_days": fee_days,
            "autopay": "Y" if behaviour == "Transactor" and u(cid, "ap") < 0.6 else "N",
            "cli_express_consent": "Y" if u(cid, "cli") < 0.35 else "N",
            "fraud_alerts_90d": (1 + h(cid, "fr") % 3) if u(cid, "fra") < 0.07 else 0,
            "wellness_band": band, "email_consent": p["email_consent"], "income": int(p["income"]),
            "tds_renewal_pct": p["tds"] if p["tds"] is not None else "", "as_of_date": AS_OF,
        }
        accounts.append(acc)
        actions.extend(plays(acc))
    return {"card_products": PRODUCTS, "card_accounts": accounts, "card_spend_monthly": spend, "card_next_actions": actions}


def plays(a: dict) -> list[dict]:
    """Deterministic plays, ranked Support > Protect > Retain > Grow (RP-018 order + fraud)."""
    out = []
    vul = a["wellness_band"] == "Vulnerable"
    support = a["behaviour"] == "Persistent debt" or vul or a["days_past_due"] > 0
    consent_ok = a["email_consent"] == "Granted"
    tds = float(a["tds_renewal_pct"]) if a["tds_renewal_pct"] != "" else None

    def add(kind, play, rec, why, gate, value):
        out.append({"account_id": a["account_id"], "customer_id": a["customer_id"], "play_type": kind, "play": play,
                    "recommended_product": rec, "rationale": why, "eligibility": gate, "value_at_stake_cad": round(value)})

    if support:
        interest = a["balance"] * a["purchase_apr"] / 100
        add("Support", "Persistent-debt support", "Low-Rate Card or instalment plan",
            f"{a['min_payment_months_12m']} of 12 months at minimum payment; utilisation {a['utilization_pct']:.0f}%"
            + (f"; {a['days_past_due']} days past due" if a['days_past_due'] else ""),
            "Eligible", interest - a["balance"] * 0.1299)
    if a["fraud_alerts_90d"]:
        add("Protect", "Security check-in", "Card lock, alerts and digital wallet",
            f"{a['fraud_alerts_90d']} fraud alert(s) in 90 days", "Eligible", 0)
    if a["annual_fee"] > 0 and a["fee_anniversary_days"] <= 60 and not support:
        earn = a["rewards_points"] / 100
        weak = a["spend_trend_pct"] < -25 or earn < a["annual_fee"] * 1.5
        if weak:
            add("Retain", "Fee renewal at risk", "One-year fee waiver or switch within the card family",
                f"Annual fee ${a['annual_fee']} due in {a['fee_anniversary_days']} days; rewards earned ~${earn:,.0f}; spend {a['spend_trend_pct']:+.0f}%",
                "Eligible", a["annual_fee"] + a["monthly_spend_avg"] * 12 * 0.015)
    if a["spend_trend_pct"] < -35 and not support:
        add("Retain", "Spend decline", "Re-engagement conversation",
            f"Spend down {abs(a['spend_trend_pct']):.0f}% (last 3 vs prior 6 months) - possible card switch",
            "Eligible" if consent_ok else "Needs marketing consent (RP-011)", a["monthly_spend_avg"] * 12 * 0.02)
    if a["foreign_spend_share_pct"] > 8 and a["product_id"] != "CRD-TRVL" and not support:
        gate = ("Suppressed - support-first client (RP-012)" if vul else
                "Needs marketing consent (RP-011)" if not consent_ok else
                "Fails income minimum (RP-019)" if a["income"] < PBY["CRD-TRVL"]["min_income"] else "Eligible")
        add("Grow", "Upgrade fit: travel", "Travel Infinite Card",
            f"{a['foreign_spend_share_pct']:.0f}% of spend is foreign - paying ~${a['monthly_spend_avg'] * 12 * a['foreign_spend_share_pct'] / 100 * 0.025:,.0f}/yr in FX fees",
            gate, a["monthly_spend_avg"] * 12 * a["foreign_spend_share_pct"] / 100 * 0.025 + 40)
    spend_to_limit = a["monthly_spend_avg"] / a["credit_limit"] * 100
    if a["behaviour"] == "Transactor" and spend_to_limit >= 22 and a["days_past_due"] == 0:
        gate = ("Blocked - TDS above 44% guideline (RP-013)" if tds is not None and tds > 44 else
                "Needs express consent (RP-020)" if a["cli_express_consent"] != "Y" else "Eligible")
        add("Grow", "Credit limit increase", f"Limit to ${a['credit_limit'] * 1.3:,.0f}",
            f"Pays in full; monthly spend is {spend_to_limit:.0f}% of the ${a['credit_limit']:,.0f} limit", gate, a["monthly_spend_avg"] * 12 * 0.004)
    order = {"Support": 0, "Protect": 1, "Retain": 2, "Grow": 3}
    out.sort(key=lambda x: (order[x["play_type"]], x["eligibility"] != "Eligible", -x["value_at_stake_cad"]))
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    t = build()
    out = {HERE / f"{k}.csv": to_csv(v) for k, v in t.items()}
    out[OUT_BFF] = ('"""Cards book for the BFF. GENERATED by data/fabric-iq/generate_cards_tables.py - do not edit.\n\n'
                    'Same rows as the Fabric IQ card tables (synthetic demo data)."""\n\nimport json\n\nCARDS = json.loads(r\'\'\''
                    + json.dumps(t, indent=1, ensure_ascii=False, sort_keys=True) + "''')\n")
    if a.check:
        stale = [p.name for p, c in out.items() if not p.exists() or p.read_text(encoding="utf-8") != c]
        print("FAIL stale: " + ", ".join(stale) if stale else "OK   cards tables match the source")
        return 1 if stale else 0
    for p, c in out.items():
        p.write_text(c, encoding="utf-8", newline="")
    for k, v in t.items():
        print(f"  {k:22} {len(v):4} rows")
    import collections
    print("  behaviour:", collections.Counter(x["behaviour"] for x in t["card_accounts"]))
    print("  plays:", collections.Counter((x["play"], x["eligibility"].split(" (")[0]) for x in t["card_next_actions"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
