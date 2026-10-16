"""Simulated issuer-processor feed for the Cards book - deterministic, linked to the card tables.

A bank's card platform (TSYS, Fiserv, Global Payments or in-house) is the system of
record for authorisations, card status and disputes; the Fabric card tables are
monthly roll-ups. This generator produces what a processor would deliver for the
same 60 accounts - shaped like vendor extracts, never copied from one - so the
Cards book can show what only the system of record knows:

    proc_authorizations.csv   30 days of authorisation messages (ISO 8583-style fields:
                              MTI, response code, MCC, POS entry mode, risk score)
    proc_card_controls.csv    card status and controls per account (lock, e-commerce,
                              international, alerts, wallet tokens, expiry, updater)
    proc_card_on_file.csv     recurring merchants billing each card (card-on-file)
    proc_disputes.csv         dispute / chargeback lifecycle (network-style reason codes)
    proc_feed_files.csv       the daily files the processor delivered to the landing zone

Scenarios come from the existing card tables, so the signals line up with the plays:
fraud alerts -> card-testing bursts and fraud declines; persistent debt -> over-limit
declines; spend decline -> recurring billers that stopped; foreign spend -> cross-border
authorisations and FX fees. Two accounts with no fraud alert in Fabric carry a quiet
card-testing pattern that only the processor feed reveals.

Also writes app/src/bff/app/processor_data.py (same rows, for the BFF). No randomness,
no clock: hashes of stable keys only.

    python generate_processor_tables.py [--check]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_BFF = HERE.parent.parent / "app" / "src" / "bff" / "app" / "processor_data.py"
AS_OF = datetime(2026, 8, 3)
WINDOW_DAYS = 30
LAST_MONTH = "2026-07"


def h(*p: str) -> int:
    return int(hashlib.sha256("|".join(p).encode()).hexdigest()[:8], 16)


def u(*p: str) -> float:
    return h(*p) / 0xFFFFFFFF


def read(name: str) -> list[dict]:
    with (HERE / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# Fictional merchants by spend category: (name, MCC, MCC description).
MERCHANTS = {
    "groceries": [("FreshMart Grocery", "5411", "Grocery stores"), ("Northern Harvest Foods", "5411", "Grocery stores"),
                  ("Corner Fine Foods", "5411", "Grocery stores")],
    "dining": [("Maple Leaf Coffee Co", "5814", "Fast food"), ("Harbourview Bistro", "5812", "Restaurants"),
               ("Noodle Lane", "5812", "Restaurants")],
    "travel": [("Northern Air", "4511", "Airlines"), ("Lakeside Hotels", "7011", "Lodging"), ("CityRide", "4121", "Taxis and rideshare")],
    "gas_transit": [("TransCanada Fuel", "5541", "Service stations"), ("Metro Transit Pass", "4111", "Commuter transport")],
    "bills": [("Aurora Mobile", "4814", "Telecom"), ("Provincial Hydro", "4900", "Utilities"), ("HomeShield Insurance", "6300", "Insurance")],
    "online": [("ShopNorth Online", "5999", "Online retail"), ("ByteBox Electronics", "5732", "Electronics"),
               ("DeliverEats", "5814", "Food delivery")],
    "other": [("Hardware Depot", "5200", "Home supply"), ("Wellness Pharmacy", "5912", "Drug stores"), ("Great North Outfitters", "5651", "Clothing")],
}
RECURRING = [("StreamFlix", "4899", "Streaming", 18.99), ("TuneBox Music", "5815", "Digital media", 11.99),
             ("Aurora Mobile", "4814", "Telecom", 85.00), ("FitLife Gyms", "7997", "Fitness clubs", 54.99),
             ("CloudVault Storage", "5818", "Digital services", 3.99), ("HomeShield Insurance", "6300", "Insurance", 112.40),
             ("DailyNews Digital", "5994", "News", 16.00), ("Provincial Hydro", "4900", "Utilities", 96.00)]
FOREIGN = [("ShopNorth US", "US", "USD", "5999"), ("Sunset Resort Lisbon", "PT", "EUR", "7011"),
           ("CityRide US", "US", "USD", "4121"), ("Gallery Café Paris", "FR", "EUR", "5812"), ("Outlet Mall NY", "US", "USD", "5651")]
TESTERS = [("DIGITAL GOODS LTD", "GB", "5818"), ("GIFTCARD ONLINE*", "US", "5999"), ("APP CREDITS BV", "NL", "5816")]
RESPONSE = {"00": "Approved", "05": "Do not honour", "51": "Insufficient funds / over limit", "54": "Expired card",
            "59": "Suspected fraud", "61": "Exceeds amount limit", "14": "Invalid card number"}
QUIET_TESTING = 2   # accounts with a card-testing pattern the Fabric book has not flagged


def ts(day_offset: float) -> str:
    """ISO timestamp `day_offset` days before AS_OF (fractional days carry the time)."""
    return (AS_OF - timedelta(days=day_offset)).strftime("%Y-%m-%dT%H:%M:%S")


def build() -> dict[str, list[dict]]:
    accounts = read("card_accounts.csv")
    products = {p["product_id"]: p for p in read("card_products.csv")}
    spend = {(r["account_id"], r["month"]): r for r in read("card_spend_monthly.csv")}

    quiet = [a["account_id"] for a in sorted(
        (a for a in accounts if a["fraud_alerts_90d"] == "0" and a["behaviour"] == "Transactor" and a["wellness_band"] != "Vulnerable"),
        key=lambda a: h(a["account_id"], "quiet"))][:QUIET_TESTING]

    auths, controls, on_file, disputes = [], [], [], []
    seq = 0

    def add_auth(a: dict, when: float, merchant: str, mcc: str, mcc_desc: str, amount: float, *, country="CA",
                 currency="CAD", entry="contactless", code="00", risk=None, recurring=False, three_ds="NA") -> dict:
        nonlocal seq
        seq += 1
        aid = a["account_id"]
        cnp = entry in ("ecommerce", "card_on_file")
        fx_fee = round(amount * 0.025, 2) if country != "CA" and code == "00" and products[a["product_id"]]["fx_fee"] != "none" else 0.0
        row = {
            "auth_id": f"AUT-{seq:06d}", "account_id": aid, "card_token": f"tok_{h(aid, 'tok'):08x}",
            "auth_ts": ts(when), "mti": "0100", "processing_code": "000000", "amount_cad": round(amount, 2),
            "txn_currency": currency, "merchant_name": merchant, "mcc": mcc, "mcc_desc": mcc_desc,
            "merchant_country": country, "pos_entry_mode": entry, "channel": "CNP" if cnp else "CP",
            "wallet": "", "recurring": "Y" if recurring else "N", "three_ds": three_ds,
            "response_code": code, "response_text": RESPONSE[code], "decision": "Approved" if code == "00" else "Declined",
            "risk_score": risk if risk is not None else int(40 + 300 * u(aid, str(seq), "risk") + (180 if country != "CA" and cnp else 0)),
            "fx_fee_cad": fx_fee,
        }
        auths.append(row)
        return row

    for a in accounts:
        aid = a["account_id"]
        limit, bal = float(a["credit_limit"]), float(a["balance"])
        util = float(a["utilization_pct"])
        persistent = a["behaviour"] == "Persistent debt"
        foreign_share = float(a["foreign_spend_share_pct"])
        decline_trend = float(a["spend_trend_pct"]) < -35
        fraud = int(a["fraud_alerts_90d"]) > 0
        m = spend.get((aid, LAST_MONTH)) or spend.get((aid, "2026-08"))
        month_spend = float(m["spend"]) if m else float(a["monthly_spend_avg"])

        # ---- card controls ------------------------------------------------
        exp_months = (1 + h(aid, "exp1") % 2) if u(aid, "soon") < 0.15 else 1 + h(aid, "exp") % 30
        exp = (AS_OF.year * 12 + AS_OF.month - 1) + exp_months
        wallet_tokens = 0 if u(aid, "wal") < 0.3 else 1 + h(aid, "walN") % 3
        ctrl = {
            "account_id": aid, "card_token": f"tok_{h(aid, 'tok'):08x}", "masked_pan": f"4520 •••• •••• {h(aid, 'pan') % 10000:04d}",
            "card_status": "Active", "ecommerce_enabled": "Y", "international_enabled": "Y" if foreign_share > 2 or u(aid, "intl") < 0.7 else "N",
            "contactless_enabled": "Y", "alerts_enrolled": "N" if (fraud and u(aid, "al") < 0.6) or u(aid, "al2") < 0.25 else "Y",
            "wallet_tokens": wallet_tokens, "card_expiry": f"{exp // 12:04d}-{exp % 12 + 1:02d}",
            "account_updater_enrolled": "Y" if u(aid, "vau") < 0.55 else "N",
            "atm_daily_limit": 500 if limit < 10000 else 1000,
            "last_reissue": (AS_OF - timedelta(days=200 + h(aid, "re") % 700)).strftime("%Y-%m-%d"),
            "network": "Visa-style",
        }
        controls.append(ctrl)

        # ---- card-on-file billers -----------------------------------------
        n_bill = 2 + h(aid, "nb") % 4
        picks = sorted(RECURRING, key=lambda r: h(aid, r[0]))[:n_bill]
        stopped = set()
        if decline_trend:
            stopped = {p[0] for p in picks[: max(1, n_bill // 2)]}
        for i, (name, mcc, desc, amt) in enumerate(picks):
            amount = round(amt * (0.9 + 0.3 * u(aid, name, "amt")), 2)
            first = AS_OF - timedelta(days=200 + h(aid, name, "f") % 900)
            if name in stopped:
                last = AS_OF - timedelta(days=38 + h(aid, name, "l") % 40)
                status = "Stopped"
            else:
                last = AS_OF - timedelta(days=1 + h(aid, name, "d") % 28)
                status = "Active"
            on_file.append({"account_id": aid, "merchant_name": name, "mcc": mcc, "mcc_desc": desc, "amount_cad": amount,
                            "cadence": "Monthly", "first_billed": first.strftime("%Y-%m-%d"), "last_billed": last.strftime("%Y-%m-%d"),
                            "status": status, "account_updater": ctrl["account_updater_enrolled"]})
            if status == "Active":
                add_auth(a, (AS_OF - last).days + 0.3, name, mcc, desc, amount, entry="card_on_file", recurring=True)

        # ---- everyday authorisations ---------------------------------------
        mix = {c: float(m[c]) for c in MERCHANTS} if m else {c: 1.0 for c in MERCHANTS}
        mix["bills"] *= 0.3  # most bills arrive as card-on-file above
        total = sum(mix.values()) or 1.0
        n = max(6, min(42, int(month_spend / 85)))
        cats = list(MERCHANTS)
        for i in range(n):
            r = u(aid, str(i), "cat") * total
            cat = cats[-1]
            for c in cats:
                r -= mix[c]
                if r <= 0:
                    cat = c
                    break
            mname, mcc, desc = MERCHANTS[cat][h(aid, str(i), "m") % len(MERCHANTS[cat])]
            amount = max(3.0, month_spend / n * (0.5 + u(aid, str(i), "amt")))
            entry = ("ecommerce" if cat == "online" else
                     "contactless" if u(aid, str(i), "e") < 0.65 else "chip")
            when = WINDOW_DAYS * u(aid, str(i), "t")
            row = add_auth(a, when, mname, mcc, desc, amount, entry=entry, three_ds="Y" if entry == "ecommerce" else "NA")
            if entry == "contactless" and wallet_tokens and u(aid, str(i), "w") < 0.5:
                row["wallet"] = "Mobile wallet"
            if not persistent and u(aid, str(i), "d05") < 0.012:
                row.update(response_code="05", response_text=RESPONSE["05"], decision="Declined")

        # ---- cross-border ---------------------------------------------------
        n_fx = int(round(foreign_share / 3)) if foreign_share > 2 else 0
        for i in range(min(n_fx, 9)):
            fname, country, cur, mcc = FOREIGN[h(aid, str(i), "fx") % len(FOREIGN)]
            amount = month_spend * foreign_share / 100 / max(1, n_fx) * (0.6 + 0.8 * u(aid, str(i), "fxa"))
            entry = "ecommerce" if mcc == "5999" else "chip"
            add_auth(a, WINDOW_DAYS * u(aid, str(i), "fxt"), fname, mcc, "Cross-border purchase", amount,
                     country=country, currency=cur, entry=entry, three_ds="Y" if entry == "ecommerce" else "NA")

        # ---- over-limit declines (persistent debt / high utilisation) -------
        if persistent or util >= 90:
            for i in range(2 + h(aid, "nsf") % 3):
                cat = ["groceries", "gas_transit", "other"][i % 3]
                mname, mcc, desc = MERCHANTS[cat][h(aid, str(i), "nsfm") % len(MERCHANTS[cat])]
                add_auth(a, 1 + 12 * u(aid, str(i), "nsft"), mname, mcc, desc, 40 + 160 * u(aid, str(i), "nsfa"),
                         entry="chip", code="51", risk=int(80 + 120 * u(aid, str(i), "nsfr")))

        # ---- card testing ----------------------------------------------------
        if fraud or aid in quiet:
            start = 2 + 7 * u(aid, "ct")
            burst = []
            for i in range(5 if fraud else 4):
                tname, country, mcc = TESTERS[i % len(TESTERS)]
                caught = fraud and i >= 2
                burst.append(add_auth(a, start - i * 0.007, tname, mcc, "Digital goods (card-not-present)", 0.5 + 4.4 * u(aid, str(i), "cta"),
                                      country=country, currency="USD", entry="ecommerce", three_ds="N",
                                      code="59" if caught else "00",
                                      risk=(880 + i * 20) if caught else int(610 + 30 * i + 40 * u(aid, str(i), "ctr"))))
            if fraud:
                big = add_auth(a, start - 0.04, "ByteBox Electronics US", "5732", "Electronics (card-not-present)",
                               420 + 300 * u(aid, "big"), country="US", currency="USD", entry="ecommerce", three_ds="N",
                               code="59", risk=965)
                approved = [b for b in burst if b["decision"] == "Approved"]
                opened = AS_OF - timedelta(days=start - 0.5)
                disputes.append({
                    "dispute_id": f"DSP-{h(aid, 'dsp') % 90000 + 10000}", "account_id": aid,
                    "auth_ids": ";".join(b["auth_id"] for b in approved), "merchant_name": approved[0]["merchant_name"] if approved else big["merchant_name"],
                    "amount_cad": round(sum(b["amount_cad"] for b in approved), 2), "reason_code": "10.4",
                    "reason": "Fraud - card-absent environment", "stage": "Chargeback filed", "opened": opened.strftime("%Y-%m-%d"),
                    "response_due": (opened + timedelta(days=30)).strftime("%Y-%m-%d"), "provisional_credit": "Y",
                    "channel": "Contact centre", "owner": "Card disputes team",
                })

    # ---- other disputes (service, not fraud) ---------------------------------
    others = sorted((a for a in accounts if a["fraud_alerts_90d"] == "0"), key=lambda a: h(a["account_id"], "disp"))[:5]
    kinds = [("13.1", "Merchandise / services not received", "Inquiry", 45), ("12.6.1", "Duplicate processing", "Representment received", 10),
             ("13.3", "Not as described", "Chargeback filed", 30), ("13.7", "Cancelled merchandise / services", "Pre-arbitration", 10),
             ("12.6.1", "Duplicate processing", "Closed - client won", 0)]
    for a, (code, reason, stage, due_days) in zip(others, kinds):
        aid = a["account_id"]
        mine = [x for x in auths if x["account_id"] == aid and x["decision"] == "Approved"]
        ref = sorted(mine, key=lambda x: h(x["auth_id"], "pick"))[0]
        opened = AS_OF - timedelta(days=5 + h(aid, "do") % 30)
        disputes.append({
            "dispute_id": f"DSP-{h(aid, 'dsp') % 90000 + 10000}", "account_id": aid, "auth_ids": ref["auth_id"],
            "merchant_name": ref["merchant_name"], "amount_cad": ref["amount_cad"], "reason_code": code, "reason": reason, "stage": stage,
            "opened": opened.strftime("%Y-%m-%d"),
            "response_due": (AS_OF + timedelta(days=2 + h(aid, "due") % 9)).strftime("%Y-%m-%d") if due_days else "",
            "provisional_credit": "Y" if stage != "Inquiry" else "N", "channel": "Mobile app" if u(aid, "ch") < 0.6 else "Branch",
            "owner": "Card disputes team",
        })

    auths.sort(key=lambda x: (x["account_id"], x["auth_ts"]))

    # ---- delivered files(the integration story) ------------------------------
    last_day = [x for x in auths if x["auth_ts"] >= ts(1)]
    feeds = [
        ("AUTH-DAILY", "Authorisation extract", "ISO 8583-style, pipe-delimited", len(last_day), "05:12", 0),
        ("POSTED-TXN", "Posted transactions", "Fixed-width", sum(x["decision"] == "Approved" for x in last_day), "05:20", 0),
        ("NONMON", "Non-monetary maintenance (status, controls, address)", "Fixed-width", 7, "05:24", 0),
        ("CHARGEBACK", "Dispute lifecycle", "CSV", len(disputes), "05:31", 0),
        ("ACCT-UPDATER", "Account Updater responses", "CSV", sum(r["account_updater"] == "Y" for r in on_file), "05:40", 2),
        ("FRAUD-SCORES", "Real-time fraud scores (stream)", "JSON events", sum(x["risk_score"] >= 600 for x in auths), "continuous", 0),
    ]
    files = [{"file_id": f"{code}.{AS_OF:%Y-%m-%d}", "feed": code, "description": d, "format": fmt, "records": n,
              "received": f"{AS_OF:%Y-%m-%d} {at}" if at != "continuous" else "continuous", "status": "Loaded" if not warn else "Loaded with warnings",
              "warnings": warn, "landing": f"OneLake Files/processor/{code.lower()}/"} for code, d, fmt, n, at, warn in feeds]

    return {"proc_authorizations": auths, "proc_card_controls": controls, "proc_card_on_file": on_file,
            "proc_disputes": disputes, "proc_feed_files": files}


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
    out[OUT_BFF] = ('"""Simulated card-processor feed for the BFF. GENERATED by data/fabric-iq/generate_processor_tables.py - do not edit.\n\n'
                    'Same rows as the Fabric IQ proc_* tables (synthetic demo data)."""\n\nimport json\n\nPROC = json.loads(r\'\'\''
                    + json.dumps(t, indent=1, ensure_ascii=False, sort_keys=True) + "''')\n")
    if args.check:
        stale = [p.name for p, c in out.items() if not p.exists() or p.read_text(encoding="utf-8") != c]
        print("FAIL stale: " + ", ".join(stale) if stale else "OK   processor tables match the source")
        return 1 if stale else 0
    for p, c in out.items():
        p.write_text(c, encoding="utf-8", newline="")
    for k, v in t.items():
        print(f"  {k:22} {len(v):5} rows")
    import collections
    print("  decisions:", collections.Counter((x["decision"], x["response_code"]) for x in t["proc_authorizations"]))
    print("  disputes:", collections.Counter(x["stage"] for x in t["proc_disputes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
