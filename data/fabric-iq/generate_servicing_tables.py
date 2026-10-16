"""Simulated mortgage servicing feed for the renewal book - deterministic, linked to the mortgage tables.

The second system of record after the card processor (generate_processor_tables.py).
A lender's mortgage servicing platform, origination/broker channel and credit-bureau
trigger service know things the monthly renewal book does not. This generator
produces, for the same 50 renewals, what those systems would deliver - shaped
like vendor extracts, never copied from one:

    svc_payment_history.csv   12 months of pre-authorised debits (PAD): paid, returned NSF,
                              late; lump-sum prepayments
    svc_payout_requests.csv   payout / discharge statement requests (another lender's
                              lawyer asking for the figure to pay the mortgage off)
    svc_bureau_inquiries.csv  hard credit inquiries by other lenders and brokers (bureau
                              trigger service; only where the client consented)
    svc_renewal_offers.csv    renewal offers sent, opened, rate holds and their expiry
    svc_feed_files.csv        the daily files the servicing systems delivered

Scenarios follow the existing book: high attrition with a rate-shopping signal ->
payout requests and bureau inquiries; Vulnerable / Stretched wellness -> returned
debits; high attrition near maturity -> prepayment surge. Two renewals the book
scores Medium with no shopping signal carry a payout request and a bureau inquiry
that only the servicing feed reveals.

Also writes app/src/bff/app/servicing_data.py. No randomness, no clock.

    python generate_servicing_tables.py [--check]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_BFF = HERE.parent.parent / "app" / "src" / "bff" / "app" / "servicing_data.py"
AS_OF = date(2026, 8, 3)
QUIET = 2

LAWYERS = ["Harbourfront Law LLP", "Côté & Lam Notaires", "Prairie Title & Closing", "Lakeshore Real Estate Law",
           "Bellevue Notarial Services"]
LENDERS = [("Northstar Mortgage Co", "Monoline lender"), ("Maple Digital Bank", "Digital bank"),
           ("Summit Credit Union", "Credit union"), ("RateWise Mortgage Brokers", "Mortgage broker"),
           ("TrueNorth Home Loans", "Monoline lender")]


def h(*p: str) -> int:
    return int(hashlib.sha256("|".join(p).encode()).hexdigest()[:8], 16)


def u(*p: str) -> float:
    return h(*p) / 0xFFFFFFFF


def read(name: str) -> list[dict]:
    with (HERE / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def monthly_payment(balance: float, rate_pct: float, years: float) -> float:
    r = rate_pct / 100 / 12
    n = max(12, int(years * 12))
    return balance * r / (1 - (1 + r) ** -n) if r else balance / n


def build() -> dict[str, list[dict]]:
    ren = read("mortgage_renewals.csv")
    risk = {r["renewal_id"]: r for r in read("renewal_risk_scores.csv")}
    well = {r["customer_id"]: r for r in read("financial_wellness.csv")}
    cust = {r["customer_id"]: r for r in read("customers.csv")}

    shoppers = [r for r in ren if risk[r["renewal_id"]]["attrition_risk_band"] == "High"
                and risk[r["renewal_id"]]["rate_shopping_signal"] == "Y"]
    shoppers.sort(key=lambda r: int(r["days_to_maturity"]))
    quiet = sorted((r for r in ren if risk[r["renewal_id"]]["attrition_risk_band"] == "Medium"
                    and risk[r["renewal_id"]]["rate_shopping_signal"] == "N"
                    and well[r["customer_id"]]["wellness_band"] in ("Thriving", "Stable")),
                   key=lambda r: h(r["renewal_id"], "quiet"))[:QUIET]
    quiet_ids = {r["renewal_id"] for r in quiet}

    payments, payouts, inquiries, offers = [], [], [], []
    for r in ren:
        rid, cid = r["renewal_id"], r["customer_id"]
        bal, rate = float(r["mortgage_balance_cad"]), float(r["current_rate_pct"])
        pmt = round(monthly_payment(bal, rate, float(r["amortization_remaining_years"])), 2)
        band = well[cid]["wellness_band"]
        rk = risk[rid]
        # ---- PAD history ---------------------------------------------------
        nsf_months = set()
        if band == "Vulnerable":
            nsf_months = {1, 2} if u(rid, "nsf") < 0.6 else {1}
        elif band == "Stretched" and u(rid, "nsf") < 0.35:
            nsf_months = {2}
        surge = rk["attrition_risk_band"] == "High" and int(r["days_to_maturity"]) <= 120 and u(rid, "pp") < 0.4
        for k in range(12):
            # the 15th of each of the last 12 months that have already come due
            m_index = AS_OF.year * 12 + AS_OF.month - 1 - k - (1 if AS_OF.day < 15 else 0)
            due = date(m_index // 12, m_index % 12 + 1, 15)
            status = "Paid"
            paid_on = due
            if k in nsf_months:
                status = "Returned - NSF"
                paid_on = None
            elif band in ("Stretched", "Vulnerable") and k == 4 and u(rid, "late") < 0.5:
                status = "Paid late"
                paid_on = due + timedelta(days=9)
            prepay = 0.0
            if surge and k in (0, 1):
                prepay = round(bal * (0.04 + 0.05 * u(rid, str(k), "pp")), -2)
            elif k == 7 and u(rid, "annual") < 0.25:
                prepay = round(bal * 0.02, -2)
            payments.append({"renewal_id": rid, "customer_id": cid, "due_date": due.isoformat(), "scheduled_cad": pmt,
                             "status": status, "paid_on": paid_on.isoformat() if paid_on else "",
                             "prepayment_cad": prepay, "channel": "Pre-authorised debit"})
        # ---- payout requests -------------------------------------------------
        if r in shoppers[:3] or rid in quiet_ids:
            req = AS_OF - timedelta(days=1 + h(rid, "po") % 9)
            switch = u(rid, "sale") < 0.8
            payouts.append({
                "request_id": f"PO-{h(rid, 'poid') % 90000 + 10000}", "renewal_id": rid, "customer_id": cid,
                "requested_on": req.isoformat(), "requested_by": LAWYERS[h(rid, "law") % len(LAWYERS)],
                "purpose": "Discharge - transfer to another lender" if switch else "Discharge - sale of property",
                "payout_amount_cad": round(bal * (1 - 0.01 * u(rid, "amt")), -2),
                "statement_due": (req + timedelta(days=7)).isoformat(),
                "status": "Statement issued" if u(rid, "iss") < 0.25 else "Received",
                "prepayment_penalty_cad": 0 if r["product_type"].startswith("Variable") or int(r["days_to_maturity"]) <= 120
                else round(bal * float(r["current_rate_pct"]) / 100 / 4, -1),
            })
        # ---- bureau inquiries ------------------------------------------------
        consent = "Y" if u(cid, "bureau") < 0.75 or rid in quiet_ids else "N"
        if (rk["rate_shopping_signal"] == "Y" or rid in quiet_ids) and u(rid, "inq") < 0.85:
            n = 1 + h(rid, "nq") % 3
            for i in range(n):
                lender, kind = LENDERS[h(rid, str(i), "lend") % len(LENDERS)]
                inquiries.append({
                    "inquiry_id": f"BQ-{h(rid, str(i), 'bq') % 900000 + 100000}", "renewal_id": rid, "customer_id": cid,
                    "inquiry_date": (AS_OF - timedelta(days=2 + h(rid, str(i), "d") % 40)).isoformat(),
                    "inquirer": lender, "inquirer_type": kind, "inquiry_kind": "Hard - mortgage",
                    "bureau": "Bureau A" if h(cid, "b") % 2 else "Bureau B", "trigger_consent": consent,
                })
        # ---- renewal offers ------------------------------------------------------
        stage = r["renewal_stage"]
        if stage in ("Offer Sent", "In Negotiation", "Advisor Contacted"):
            sent = AS_OF - timedelta(days=3 + h(rid, "sent") % 25)
            opened = stage != "Offer Sent" or u(rid, "open") < 0.45
            hold_days = 120 if int(r["days_to_maturity"]) > 60 else 60
            hold_exp = sent + timedelta(days=min(hold_days, max(10, int(r["days_to_maturity"]) - 5)))
            if r in shoppers[:6] and u(rid, "holdsoon") < 0.6:
                hold_exp = AS_OF + timedelta(days=2 + h(rid, "hs") % 6)
            offers.append({
                "offer_ref": f"RO-{rid[4:]}", "renewal_id": rid, "customer_id": cid, "sent_on": sent.isoformat(),
                "channel": ["Client portal", "Email", "Mail"][h(rid, "ch") % 3],
                "offered_rate_pct": r["offered_renewal_rate_pct"], "opened": "Y" if opened else "N",
                "opened_on": (sent + timedelta(days=1 + h(rid, "op") % 4)).isoformat() if opened else "",
                "rate_hold_expiry": hold_exp.isoformat(),
                "status": "Opened" if opened else "Sent - not opened",
                "preferred_language": cust[cid]["preferred_language"],
            })

    feeds = [
        ("PAD-DAILY", "Pre-authorised debit results", "CPA-005-style fixed width", sum(p["due_date"] >= (AS_OF - timedelta(days=31)).isoformat() for p in payments), "04:40", 0),
        ("PAYOUT-REQ", "Payout / discharge statement requests", "CSV", len(payouts), "05:05", 0),
        ("BUREAU-TRIG", "Credit-bureau trigger alerts", "JSON", len(inquiries), "05:15", 1),
        ("OFFER-EVENTS", "Renewal offer delivery and portal views", "JSON events", len(offers), "continuous", 0),
        ("SERVICING-MASTER", "Servicing master (balance, rate, payment, arrears)", "Fixed width", len(ren), "04:30", 0),
    ]
    files = [{"file_id": f"{code}.{AS_OF.isoformat()}", "feed": code, "description": d, "format": fmt, "records": n,
              "received": f"{AS_OF.isoformat()} {at}" if at != "continuous" else "continuous",
              "status": "Loaded" if not warn else "Loaded with warnings", "warnings": warn,
              "landing": f"OneLake Files/servicing/{code.lower()}/"} for code, d, fmt, n, at, warn in feeds]

    return {"svc_payment_history": payments, "svc_payout_requests": payouts, "svc_bureau_inquiries": inquiries,
            "svc_renewal_offers": offers, "svc_feed_files": files}


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    t = build()
    out = {HERE / f"{k}.csv": to_csv(v) for k, v in t.items()}
    out[OUT_BFF] = ('"""Simulated mortgage servicing feed for the BFF. GENERATED by data/fabric-iq/generate_servicing_tables.py - do not edit.\n\n'
                    'Same rows as the Fabric IQ svc_* tables (synthetic demo data)."""\n\nimport json\n\nSVC = json.loads(r\'\'\''
                    + json.dumps(t, indent=1, ensure_ascii=False, sort_keys=True) + "''')\n")
    if args.check:
        stale = [p.name for p, c in out.items() if not p.exists() or p.read_text(encoding="utf-8") != c]
        print("FAIL stale: " + ", ".join(stale) if stale else "OK   servicing tables match the source")
        return 1 if stale else 0
    for p, c in out.items():
        p.write_text(c, encoding="utf-8", newline="")
    for k, v in t.items():
        print(f"  {k:22} {len(v):5} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
