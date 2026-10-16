"""Mortgage servicing (system of record) - simulated vendor integration for the renewal book.

The second system of record on the shared framework (sor.py), after the card
processor. A lender's servicing platform, origination channel and credit-bureau
trigger service know what the monthly renewal book cannot:

  * a payout / discharge statement requested by another lender's lawyer - the
    client is leaving, often before the attrition model notices;
  * hard credit inquiries by other lenders (only where the client consented to
    bureau triggers, RP-038) - the client is shopping;
  * renewal offers never opened and rate holds about to expire;
  * returned pre-authorised debits - a support signal, never a sales one (RP-014, RP-012);
  * lump-sum prepayments just before maturity.

Each insight is tied to a policy, and servicing actions (retention review of a
payout request, retention offer within the RP-002 approval matrix, rate hold,
e-sign resend, payment deferral) go through preview -> guards -> named approval
-> vendor-style response -> event and audit. The vendor profile
(MORTGAGE_SERVICER = generic | msp | fis | inhouse) changes labels only.
SYNTHETIC demo data; not affiliated with or endorsed by any vendor.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from . import evergreen, sor
from .pb_data import PB
from .servicing_data import SVC

PROFILES: dict[str, dict[str, Any]] = {
    "generic": {"id": "generic", "name": "Mortgage servicing platform", "api_base": "https://servicing.sim/api/v1"},
    "msp": {"id": "msp", "name": "MSP-style mortgage servicer", "api_base": "https://msp-style.sim/servicing/v2"},
    "fis": {"id": "fis", "name": "FIS-style mortgage servicer", "api_base": "https://fis-style.sim/lending/v1"},
    "inhouse": {"id": "inhouse", "name": "In-house mortgage servicing", "api_base": "https://mortgage-core.sim/api/v1"},
}


def profile() -> dict[str, Any]:
    p = PROFILES.get(os.getenv("MORTGAGE_SERVICER", "generic").strip().lower(), PROFILES["generic"])
    return {**p, "simulated": True, "feeds": "Servicing master, PAD results, payout requests, bureau triggers, offer events",
            "disclaimer": "Simulated system of record. Synthetic data; not connected to, affiliated with or endorsed by any vendor."}


# Indexes over rows that evergreen shifts in place.
REN = {r["customer_id"]: r for r in PB["renewals"].values()}
RISK = {r["customer_id"]: r for r in PB["risk"].values()}
CUST = PB["customers"]
WELL = {r["customer_id"]: r for r in PB["financial_wellness"]}
_by = defaultdict
PAY: dict[str, list[dict]] = _by(list)
for _r in SVC["svc_payment_history"]:
    PAY[_r["customer_id"]].append(_r)
PAYOUT: dict[str, list[dict]] = _by(list)
for _r in SVC["svc_payout_requests"]:
    PAYOUT[_r["customer_id"]].append(_r)
INQ: dict[str, list[dict]] = _by(list)
for _r in SVC["svc_bureau_inquiries"]:
    INQ[_r["customer_id"]].append(_r)
OFFER = {r["customer_id"]: r for r in SVC["svc_renewal_offers"]}

ORDER = {"Support": 0, "Retain": 1, "Service": 2}
# RP-002 approval matrix and the retention offer shelf (retention_offers.csv).
OFFERS = {  # id: (name, max discount bps, approval level from retention_offers.csv)
    "OFR-01": ("Loyalty Rate Match", 15, "Mortgage Advisor"), "OFR-02": ("Relationship Bundle Discount", 20, "Branch Manager"),
    "OFR-03": ("Early Renewal Lock (120-day)", 10, "Mortgage Advisor"), "OFR-04": ("Cashback Retention Offer", 0, "Branch Manager"),
    "OFR-05": ("Private Wealth Preferred Pricing", 35, "Regional Director"), "OFR-06": ("Blend & Extend", 12, "Branch Manager"),
    "OFR-07": ("Amortization Relief Renewal", 5, "Credit Risk"), "OFR-08": ("Switch-In Defence Pricing", 25, "Mortgage Pricing Committee"),
}
RANK = ["Mortgage Advisor", "Branch Manager", "Regional Director", "Credit Risk", "Mortgage Pricing Committee"]


def approver_for(bps: int, segment: str) -> str:
    if segment == "High Net Worth" and bps <= 35:
        return "Regional Director"
    return "Mortgage Advisor" if bps <= 20 else "Branch Manager" if bps <= 25 else "Mortgage Pricing Committee"


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _d(s: str) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _as_of() -> date:
    return evergreen.as_of()


def state(cid: str) -> dict[str, Any]:
    """Live servicing state: generated rows plus changes made through the simulator."""
    o = OFFER.get(cid)
    ov = SERVICER.overrides.get(cid, {})
    return {
        "offer": {**o, **ov.get("offer", {})} if o else None,
        "payouts": [{**p, **ov.get("payout", {}).get(p["request_id"], {})} for p in PAYOUT[cid]],
        "deferral": ov.get("deferral"),
        "retention_offer": ov.get("retention_offer"),
    }


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #
def insights(cid: str) -> list[dict[str, Any]]:
    if cid not in REN:
        return []
    r, rk, w = REN[cid], RISK[cid], WELL[cid]
    st = state(cid)
    as_of = _as_of()
    bal = _num(r["mortgage_balance_cad"])
    out: list[dict[str, Any]] = []

    def add(code, kind, title, detail, *, evidence=(), value=0.0, policy="", actions=(), new_signal=False):
        out.append({"code": code, "type": kind, "title": title, "detail": detail, "evidence": list(evidence),
                    "value_cad": round(value), "policy": policy, "actions": list(actions), "new_signal": new_signal})

    for p in st["payouts"]:
        due = _d(p["statement_due"])
        days = (due - as_of).days if due else 0
        unseen = rk["attrition_risk_band"] != "High" or rk["rate_shopping_signal"] != "Y"
        leaving = "another lender" in p["purpose"]
        add("PAYOUT_REQUESTED", "Retain" if leaving else "Service",
            "Payout statement requested" + (" - the attrition model has not flagged this client" if unseen else ""),
            f"{p['requested_by']} asked for a discharge figure on {p['requested_on']} ({p['purpose'].lower()}); "
            f"${_num(p['payout_amount_cad']):,.0f} - statement due {p['statement_due']} ({days} days). Status: {p['status']}."
            + (" The book scores this renewal " + rk["attrition_risk_band"] + " with no rate-shopping signal." if unseen else "")
            + ("" if leaving else " Sale of property - a service conversation, not retention."),
            evidence=[p["request_id"]], value=_num(rk["five_year_lifetime_value_cad"]), policy="RP-037 · RP-002",
            actions=["route_payout_to_retention", "send_retention_offer"] if leaving else [], new_signal=unseen)

    recent = [q for q in INQ[cid] if (as_of - _d(q["inquiry_date"])).days <= 45]
    if recent:
        consent = recent[0]["trigger_consent"] == "Y"
        if consent:
            add("SHOPPING", "Retain", f"Shopping: {len(recent)} credit inquir{'y' if len(recent) == 1 else 'ies'} by other lenders",
                ", ".join(f"{q['inquirer']} ({q['inquirer_type'].lower()}, {q['inquiry_date']})" for q in recent)
                + f". Renewal in {r['days_to_maturity']} days at {r['offered_renewal_rate_pct']}% offered.",
                evidence=[q["inquiry_id"] for q in recent], value=_num(rk["annual_revenue_exposure_cad"]), policy="RP-038 · RP-002",
                actions=["issue_rate_hold", "send_retention_offer"], new_signal=rk["rate_shopping_signal"] != "Y")
        else:
            add("SHOPPING_NO_CONSENT", "Service", "Bureau trigger received - not usable without consent",
                "The client has not consented to bureau trigger monitoring, so inquiry details are withheld and may not be "
                "used for outreach (RP-038). Use the ordinary renewal conversation.", policy="RP-038")

    o = st["offer"]
    if o and o["status"] not in ("Accepted",):
        hold = _d(o["rate_hold_expiry"])
        days = (hold - as_of).days if hold else 99
        if 0 <= days <= 10:
            add("RATE_HOLD_EXPIRING", "Retain", f"Rate hold expires in {days} days",
                f"Offer {o['offer_ref']} at {o['offered_rate_pct']}% (hold to {o['rate_hold_expiry']}); status {o['status']}.",
                evidence=[o["offer_ref"]], value=_num(rk["annual_revenue_exposure_cad"]), policy="RP-002",
                actions=["extend_rate_hold"])
        sent = _d(o["sent_on"])
        if o["opened"] == "N" and sent and (as_of - sent).days >= 5:
            add("OFFER_NOT_OPENED", "Service", f"Renewal offer not opened after {(as_of - sent).days} days",
                f"Sent by {o['channel'].lower()} on {o['sent_on']}; never opened. Resend for e-signature through another channel "
                f"(preferred language {o['preferred_language']}).", evidence=[o["offer_ref"]], policy="RP-016",
                actions=["resend_offer_esign"])

    pays = sorted(PAY[cid], key=lambda p: p["due_date"], reverse=True)
    nsf = [p for p in pays[:3] if p["status"].startswith("Returned")]
    if nsf:
        add("MISSED_PAYMENTS", "Support", f"{len(nsf)} returned mortgage payment{'s' if len(nsf) > 1 else ''} in 3 months",
            "Pre-authorised debits returned NSF on " + ", ".join(p["due_date"] for p in nsf)
            + f". Wellness band {w['wellness_band']}. Lead with hardship options - deferral, interest-only, Client Assistance - "
              "never a retention or sales pitch (RP-014, RP-012).",
            evidence=[p["due_date"] for p in nsf], value=sum(_num(p["scheduled_cad"]) for p in nsf), policy="RP-014 · RP-012",
            actions=["arrange_payment_deferral"])

    prepay = sum(_num(p["prepayment_cad"]) for p in pays[:2])
    if bal and prepay / bal >= 0.04:
        add("PREPAYMENT_SURGE", "Retain", f"${prepay:,.0f} prepaid in the last two months",
            f"{prepay / bal * 100:.1f}% of the balance paid down just before maturity in {r['days_to_maturity']} days - "
            "often a client lowering the amount to move or refinance elsewhere.",
            value=prepay, policy="RP-002", actions=["issue_rate_hold"])

    for i in out:
        cands = i["actions"]
        i["actions"] = SERVICER.allowed(cid, cands)
        i["done"] = SERVICER.done(cid, cands)
    out.sort(key=lambda x: (ORDER[x["type"]], not x["new_signal"], -x["value_cad"]))
    return out


def merge_live(d: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Fold live Eventstream signals (pb_stream.servicing_live) into a client's insights.

    A payout request or a consented lender inquiry that arrived minutes ago is
    not in the daily files yet; it is the most urgent thing on the file.
    """
    if not live.get("connected"):
        return d
    cid = d["customer_id"]
    have = {i["code"] for i in d["insights"]}
    extra = []
    for p in live.get("payouts", []):
        if p["customer_id"] == cid and "PAYOUT_REQUESTED" not in have:
            unseen = RISK[cid]["attrition_risk_band"] != "High" or RISK[cid]["rate_shopping_signal"] != "Y"
            extra.append({"code": "PAYOUT_REQUESTED", "type": "Retain", "live": True,
                          "title": "Payout statement requested - live" + (" (the attrition model has not flagged this client)" if unseen else ""),
                          "detail": f"{p['requested_by']} asked for a discharge figure ({p['purpose'].lower()}) for ${_num(p['payout_amount_cad']):,.0f}, "
                                    f"streamed at {p['last_seen']}. The statement is due within 7 days; route to retention now (RP-037).",
                          "evidence": [p["renewal_id"]], "value_cad": round(_num(RISK[cid]["five_year_lifetime_value_cad"])),
                          "policy": "RP-037 · RP-002", "actions": SERVICER.allowed(cid, ["send_retention_offer", "issue_rate_hold"]),
                          "done": SERVICER.done(cid, ["send_retention_offer", "issue_rate_hold"]), "new_signal": unseen})
    for s in live.get("shopping", []):
        if s["customer_id"] == cid and "SHOPPING" not in have:
            lenders = s["lenders"] if isinstance(s["lenders"], list) else [s["lenders"]]
            extra.append({"code": "SHOPPING", "type": "Retain", "live": True,
                          "title": f"Shopping - live: {s['inquiries']} lender inquir{'y' if s['inquiries'] == 1 else 'ies'}",
                          "detail": f"{', '.join(lenders)} pulled credit (consented bureau trigger, RP-038). Never tell the client how we know.",
                          "evidence": [s["renewal_id"]], "value_cad": round(_num(RISK[cid]["annual_revenue_exposure_cad"])),
                          "policy": "RP-038 · RP-002", "actions": SERVICER.allowed(cid, ["issue_rate_hold", "send_retention_offer"]),
                          "done": [], "new_signal": RISK[cid]["rate_shopping_signal"] != "Y"})
    d["insights"] = extra + d["insights"]
    return d


def merge_live_overview(o: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Put live payout requests and shopping signals at the top of the portfolio insights."""
    if not live.get("connected"):
        return o
    extra = []
    for cid in dict.fromkeys([p["customer_id"] for p in live.get("payouts", [])] + [s["customer_id"] for s in live.get("shopping", [])]):
        if cid not in REN:
            continue
        d = merge_live({"customer_id": cid, "insights": insights(cid)}, live)
        for i in d["insights"]:
            if i.get("live"):
                extra.append({**i, "customer_id": cid, "customer_name": CUST[cid]["full_name"], "renewal_id": REN[cid]["renewal_id"],
                              "days_to_maturity": int(REN[cid]["days_to_maturity"])})
    o["insights"] = extra + o["insights"]
    o["kpis"]["live_signals"] = len(extra)
    return o


def annotate(rows: list[dict]) -> list[dict]:
    for r in rows:
        ins = insights(r["customer_id"])
        r["servicing_signals"] = len(ins)
        r["servicing_top"] = ins[0]["title"] if ins else None
        r["servicing_new"] = any(i["new_signal"] for i in ins)
        if ins and "Servicing signal" not in r.get("flags", []):
            r.setdefault("flags", []).append("Servicing signal")
    return rows


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
def overview() -> dict[str, Any]:
    per = {cid: insights(cid) for cid in REN}
    flat = [{**i, "customer_id": cid, "customer_name": CUST[cid]["full_name"], "renewal_id": REN[cid]["renewal_id"],
             "days_to_maturity": int(REN[cid]["days_to_maturity"])} for cid, ins in per.items() for i in ins]
    flat.sort(key=lambda x: (not x["new_signal"], ORDER[x["type"]], -x["value_cad"]))
    picked = [i for i in flat if i["new_signal"]]
    for code in dict.fromkeys(i["code"] for i in flat):
        picked += [i for i in flat if i["code"] == code and not i["new_signal"]][:2]
    picked += [i for i in flat if i not in picked]
    codes = Counter(i["code"] for i in flat)
    payouts = [p for cid in REN for p in state(cid)["payouts"]]
    pays = SVC["svc_payment_history"]
    as_of = _as_of()
    recent = [p for p in pays if (as_of - _d(p["due_date"])).days <= 92]
    return {
        "profile": profile(), "as_of": as_of.isoformat(), "feeds": SVC["svc_feed_files"],
        "kpis": {
            "payout_requests": len(payouts), "payout_balance": round(sum(_num(p["payout_amount_cad"]) for p in payouts)),
            "unseen_by_book": sum(1 for ins in per.values() if any(i["new_signal"] for i in ins)),
            "shopping_clients": codes["SHOPPING"], "holds_expiring": codes["RATE_HOLD_EXPIRING"],
            "offers_unopened": codes["OFFER_NOT_OPENED"], "missed_payments": codes["MISSED_PAYMENTS"],
            "prepay_surge": codes["PREPAYMENT_SURGE"],
            "pad_success_pct": round(100 * sum(p["status"] != "Returned - NSF" for p in recent) / max(1, len(recent)), 1),
            "inquiries_without_consent": codes["SHOPPING_NO_CONSENT"],
        },
        "insight_counts": [{"code": c, "count": n} for c, n in codes.most_common()],
        "insights": picked[:16],
        "events": events(12),
    }


def customer(cid: str) -> dict[str, Any] | None:
    if cid not in REN:
        return None
    st = state(cid)
    inq = INQ[cid]
    consent = bool(inq) and inq[0]["trigger_consent"] == "Y"
    return {
        "profile": profile(), "customer_id": cid, "customer_name": CUST[cid]["full_name"], "renewal": REN[cid], "risk": RISK[cid],
        "wellness_band": WELL[cid]["wellness_band"], "insights": insights(cid),
        "payments": sorted(PAY[cid], key=lambda p: p["due_date"], reverse=True),
        "payouts": st["payouts"], "offer": st["offer"], "deferral": st["deferral"], "retention_offer": st["retention_offer"],
        "inquiries": inq if consent else [], "inquiries_withheld": 0 if consent else len(inq),
        "actions": [dict(SERVICER.actions[k], id=k) for k in SERVICER.actions],
        "log": list(reversed(SERVICER.log[cid])),
        "prompts": [
            {"label": "Explain the servicing signals", "prompt": f"For customer {cid} ({REN[cid]['renewal_id']}), explain what the mortgage "
             "servicing feed shows that the renewal book does not: payout requests, bureau inquiries (only with consent), offer and rate "
             "hold status, returned payments and prepayments. Use the Fabric IQ svc_* tables and cite RP-002, RP-014, RP-037 and RP-038."},
            {"label": "What may I offer to keep them?", "prompt": f"Customer {cid} has servicing signals. Which retention offer is "
             "eligible, what discount, and who must approve it under RP-002? Respect RP-012 if the client is support-first."},
        ],
    }


def events(n: int = 20) -> list[dict[str, Any]]:
    live = sor.events(n, "mortgage")
    if len(live) >= n:
        return live
    feed = []
    for p in sorted(SVC["svc_payout_requests"], key=lambda p: p["requested_on"], reverse=True):
        feed.append({"id": p["request_id"], "ts": p["requested_on"], "type": "payout.requested", "account_id": p["customer_id"],
                     "detail": f"{p['requested_by']} · ${_num(p['payout_amount_cad']):,.0f} · {p['purpose']}", "ref": p["renewal_id"],
                     "source": "feed"})
    for q in sorted(SVC["svc_bureau_inquiries"], key=lambda q: q["inquiry_date"], reverse=True)[:6]:
        if q["trigger_consent"] == "Y":
            feed.append({"id": q["inquiry_id"], "ts": q["inquiry_date"], "type": "bureau.inquiry", "account_id": q["customer_id"],
                         "detail": f"{q['inquirer']} ({q['inquirer_type']})", "ref": q["renewal_id"], "source": "feed"})
    for p in sorted(SVC["svc_payment_history"], key=lambda p: p["due_date"], reverse=True):
        if p["status"].startswith("Returned"):
            feed.append({"id": f"{p['renewal_id']}-{p['due_date']}", "ts": p["due_date"], "type": "pad.returned",
                         "account_id": p["customer_id"], "detail": f"PAD returned NSF · ${_num(p['scheduled_cad']):,.2f}",
                         "ref": p["renewal_id"], "source": "feed"})
    feed.sort(key=lambda e: e["ts"], reverse=True)
    return live + feed[: n - len(live)]


# --------------------------------------------------------------------------- #
# Simulated servicing API on the shared framework
# --------------------------------------------------------------------------- #
ACTIONS: dict[str, dict[str, Any]] = {
    "route_payout_to_retention": {"label": "Route payout request to retention", "method": "POST",
                                  "path": "/payouts/{request}/retention-review", "policy": "RP-037",
                                  "effect": "The retention team gets the file before the statement is released. The statement is still "
                                            "issued by its due date - the client's right to discharge is never delayed."},
    "send_retention_offer": {"label": "Send a retention offer", "method": "POST", "path": "/renewals/{renewal}/retention-offers",
                             "policy": "RP-002",
                             "effect": "Issues the recommended retention offer within the advisor's authority, or submits it to the "
                                       "approver the RP-002 matrix requires."},
    "issue_rate_hold": {"label": "Issue a 30-day rate hold", "method": "POST", "path": "/renewals/{renewal}/rate-holds", "policy": "RP-002",
                        "effect": "Holds the offered renewal rate for 30 days while the client decides."},
    "extend_rate_hold": {"label": "Extend the rate hold 15 days", "method": "PATCH", "path": "/renewals/{renewal}/rate-holds/current",
                         "policy": "RP-002", "effect": "Extends the current hold once by 15 days."},
    "resend_offer_esign": {"label": "Resend for e-signature", "method": "POST", "path": "/renewals/{renewal}/documents/esign",
                           "policy": "RP-016", "effect": "Sends the renewal agreement for e-signature by another channel, in the "
                                                         "client's preferred language, with the full disclosure."},
    "arrange_payment_deferral": {"label": "Request a 2-month payment deferral", "method": "POST",
                                 "path": "/loans/{renewal}/hardship/deferrals", "policy": "RP-014",
                                 "effect": "Submits a two-month deferral with interest capitalised for Branch Manager approval (RP-014)."},
}


class MortgageServicer(sor.SystemOfRecord):
    system = "mortgage"
    ref_prefix = "SVC"
    actions = ACTIONS

    def profile(self) -> dict[str, Any]:
        return profile()

    def exists(self, key: str) -> bool:
        return key in REN

    def _offer_choice(self, cid: str) -> tuple[str, str, int, str]:
        """Recommended offer; the approver is the stricter of the offer's own level and the RP-002 matrix."""
        rk = RISK[cid]
        oid = rk["recommended_offer_id"] if rk["recommended_offer_id"] in OFFERS else "OFR-01"
        name, bps, level = OFFERS[oid]
        matrix = approver_for(bps, rk["segment"])
        return oid, name, bps, max(level, matrix, key=RANK.index)

    def request(self, cid: str, action: str, reason: str) -> dict[str, Any]:
        r = REN[cid]
        st = state(cid)
        spec = ACTIONS[action]
        req_id = st["payouts"][0]["request_id"] if st["payouts"] else "none"
        path = spec["path"].format(request=req_id, renewal=r["renewal_id"])
        if action == "route_payout_to_retention":
            body = {"requestId": req_id, "reviewWindowHours": 48, "releaseStatementBy": st["payouts"][0]["statement_due"] if st["payouts"] else None,
                    "note": reason}
        elif action == "send_retention_offer":
            oid, name, bps, appr = self._offer_choice(cid)
            body = {"offerId": oid, "offerName": name, "discountBps": bps, "fromRatePct": _num(r["offered_renewal_rate_pct"]),
                    "toRatePct": round(_num(r["offered_renewal_rate_pct"]) - bps / 100, 2), "requiredApprover": appr,
                    "straightRenewal": oid != "OFR-07",
                    "requalification": "TDS/GDS re-test required - amortization is extended (OFR-07)" if oid == "OFR-07"
                    else "Not required - straight renewal (RP-004)"}
        elif action in ("issue_rate_hold", "extend_rate_hold"):
            body = {"ratePct": _num(r["offered_renewal_rate_pct"]), "holdDays": 30 if action == "issue_rate_hold" else 15}
        elif action == "resend_offer_esign":
            o = st["offer"] or {}
            body = {"offerRef": o.get("offer_ref"), "channel": "Client portal + SMS link" if o.get("channel") != "Client portal" else "Email",
                    "language": o.get("preferred_language", "EN"), "disclosure": "Full renewal disclosure attached"}
        else:
            body = {"months": 2, "interest": "Capitalised", "trigger": "Missed payment (NSF)", "approver": "Branch Manager"}
        return {"method": spec["method"], "url": profile()["api_base"] + path,
                "headers": {"Authorization": "Bearer <managed-identity token via API Management>",
                            "Idempotency-Key": f"{cid}-{action}-<uuid>"}, "body": body}

    def guards(self, cid: str, action: str) -> list[dict[str, str]]:
        g = self.guard
        st = state(cid)
        w = WELL[cid]
        vulnerable = w["wellness_band"] == "Vulnerable"
        out = []
        if action == "route_payout_to_retention":
            open_po = [p for p in st["payouts"] if p["status"] in ("Received", "Statement issued")]
            out.append(g("RP-037", "Open payout request", bool(open_po),
                         f"{len(open_po)} open request(s)." if open_po else "No open payout request (already routed or none)."))
            out.append(g("RP-037", "Statement deadline respected", True, "Review window ends before the statement due date; release is never delayed."))
        if action == "send_retention_offer":
            out.append(g("RP-012", "Not a support-first client", not vulnerable,
                         "Vulnerable band - hardship conversation first; pricing follows a hardship review." if vulnerable else
                         f"Wellness band {w['wellness_band']}."))
            out.append(g("RP-002", "Within the approval matrix", True,
                         f"{self._offer_choice(cid)[2]} bps needs {self._offer_choice(cid)[3]} approval - submitted to them if above your authority."))
            out.append(g("RP-002", "Not already sent", not st["retention_offer"], "A retention offer is already out." if st["retention_offer"] else "None sent yet."))
            ofr = self._offer_choice(cid)[0]
            out.append(g("RP-004", "Re-qualification", True, "Amortization relief (OFR-07) is not a straight renewal - TDS/GDS re-test "
                         "with Credit Risk." if ofr == "OFR-07" else "Straight renewal - no re-qualification."))
        if action in ("issue_rate_hold", "extend_rate_hold"):
            o = st["offer"]
            hold = _d(o["rate_hold_expiry"]) if o else None
            left = (hold - _as_of()).days if hold else -1
            if action == "issue_rate_hold":
                out.append(g("RP-002", "No hold longer than 20 days already", left <= 20,
                             f"Current hold runs {left} more days." if left > 0 else "No current hold."))
            else:
                ext = (SERVICER.overrides.get(cid, {}).get("offer") or {}).get("extended")
                out.append(g("RP-002", "Hold not already extended", not ext, "Already extended once." if ext else "First extension."))
        if action == "resend_offer_esign":
            o = st["offer"]
            out.append(g("RP-016", "Offer exists and is not accepted", bool(o) and o["status"] != "Accepted",
                         f"Offer status {o['status']}." if o else "No renewal offer on file."))
        if action == "arrange_payment_deferral":
            nsf = [p for p in PAY[cid] if p["status"].startswith("Returned")]
            out.append(g("RP-014", "Documented trigger", bool(nsf), f"{len(nsf)} returned payment(s) on file." if nsf else "No missed payment on file."))
            out.append(g("RP-014", "No deferral already requested", not st["deferral"], "Already requested." if st["deferral"] else "None requested."))
        return out

    def apply(self, cid: str, action: str, req: dict[str, Any], approver: str) -> tuple[int, dict[str, Any], str, str]:
        ov = self.overrides[cid]
        r = REN[cid]
        if action == "route_payout_to_retention":
            rid = req["body"]["requestId"]
            ov.setdefault("payout", {})[rid] = {"status": "Retention review"}
            return 202, {"requestId": rid, "status": "RETENTION_REVIEW", "statementDue": req["body"]["releaseStatementBy"]}, \
                "payout.retention_review", f"Payout {rid} routed to retention; statement still due {req['body']['releaseStatementBy']}"
        if action == "send_retention_offer":
            b = req["body"]
            pending = b["requiredApprover"] != "Mortgage Advisor"
            ov["retention_offer"] = {**b, "status": f"Pending {b['requiredApprover']}" if pending else "Issued", "by": approver}
            return (202 if pending else 201), {"offerId": b["offerId"], "status": "PENDING_APPROVAL" if pending else "ISSUED",
                                               "approver": b["requiredApprover"], "toRatePct": b["toRatePct"]}, \
                "retention.offer", f"{b['offerName']} {b['discountBps']} bps {'submitted to ' + b['requiredApprover'] if pending else 'issued'}"
        if action in ("issue_rate_hold", "extend_rate_hold"):
            o = state(cid)["offer"] or {"offer_ref": f"RO-{r['renewal_id'][4:]}", "rate_hold_expiry": _as_of().isoformat()}
            base = max(_as_of(), _d(o["rate_hold_expiry"]) or _as_of())
            new = (base if action == "extend_rate_hold" else _as_of()) + timedelta(days=req["body"]["holdDays"])
            ov["offer"] = {**ov.get("offer", {}), "rate_hold_expiry": new.isoformat(), "extended": action == "extend_rate_hold"}
            return 200, {"rateHoldExpiry": new.isoformat(), "ratePct": req["body"]["ratePct"]}, "rate.hold", f"Rate {req['body']['ratePct']}% held to {new.isoformat()}"
        if action == "resend_offer_esign":
            ov["offer"] = {**ov.get("offer", {}), "status": "Re-sent for e-signature", "channel": req["body"]["channel"]}
            return 202, {"envelope": f"ENV-{r['renewal_id'][4:]}-{self._refs:03d}", "status": "SENT"}, "offer.esign_sent", \
                f"Renewal agreement re-sent for e-signature ({req['body']['channel']})"
        ov["deferral"] = {"months": 2, "status": "Pending Branch Manager", "by": approver}
        return 202, {"status": "PENDING_APPROVAL", "approver": "Branch Manager", "months": 2}, "hardship.deferral_requested", \
            "Two-month payment deferral submitted for Branch Manager approval"


SERVICER = MortgageServicer()


def run_action(cid: str, action: str, *, reason: str = "", approver: str = "", execute: bool = False) -> dict[str, Any]:
    return SERVICER.run_action(cid, action, reason=reason, approver=approver, execute=execute)


def reset() -> None:
    SERVICER.reset()
