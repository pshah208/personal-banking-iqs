"""Card processor (system of record) - simulated vendor integration for the Cards book.

The Fabric card tables are monthly roll-ups. The issuer processor - TSYS, Fiserv,
Global Payments or an in-house platform at a real bank - holds what happens in
between: every authorisation and decline, card status and controls, card-on-file
billers and the dispute lifecycle. This module

  * reads the simulated processor feed (processor_data.PROC, the same rows as the
    Fabric IQ proc_* tables) and joins it to the card book;
  * derives deterministic insights that only the system of record can show
    (card testing the book has not flagged, declines at the limit, billers that
    stopped, cards about to expire with billers on file, FX fees, dispute deadlines),
    each tied to an existing play and policy;
  * exposes a vendor-style API (preview + execute) for servicing actions - lock,
    reissue, alerts, Account Updater push, open a dispute. Every action needs a
    named human approver, is checked against policy first, and is written to an
    audit log and an event stream. Nothing leaves this process: it is a simulator.

The vendor is a deploy-time profile (CARD_PROCESSOR = generic | tsys | fiserv |
globalpayments) that changes labels and API shape only - the data is the same.
SYNTHETIC demo data; not affiliated with or endorsed by any vendor.
"""

from __future__ import annotations

import os
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import evergreen
from .pb_cards import ACC
from .processor_data import PROC

# --------------------------------------------------------------------------- #
# Vendor profiles - presentation and API shape only.
# --------------------------------------------------------------------------- #
PROFILES: dict[str, dict[str, Any]] = {
    "generic": {"id": "generic", "name": "Issuer processor", "style": "Vendor-neutral issuer processing platform",
                "api_base": "https://issuer-processor.sim/api/v1", "auth_format": "ISO 8583-style authorisation extract",
                "events": "Webhook events (JSON)"},
    "tsys": {"id": "tsys", "name": "TSYS-style issuer processor", "style": "Modelled on a TSYS-style issuing platform",
             "api_base": "https://tsys-style.sim/issuing/v2", "auth_format": "ISO 8583-style authorisation extract",
             "events": "Event notifications (JSON)"},
    "fiserv": {"id": "fiserv", "name": "Fiserv-style issuer processor", "style": "Modelled on a Fiserv-style card platform",
               "api_base": "https://fiserv-style.sim/card-services/v1", "auth_format": "ISO 8583-style authorisation extract",
               "events": "Webhooks (JSON)"},
    "globalpayments": {"id": "globalpayments", "name": "Global Payments-style issuer processor",
                       "style": "Modelled on a Global Payments-style issuing platform",
                       "api_base": "https://gp-style.sim/issuing/v1", "auth_format": "ISO 8583-style authorisation extract",
                       "events": "Event notifications (JSON)"},
}


def profile() -> dict[str, Any]:
    p = PROFILES.get(os.getenv("CARD_PROCESSOR", "generic").strip().lower(), PROFILES["generic"])
    return {**p, "simulated": True,
            "disclaimer": "Simulated system of record. Synthetic data; not connected to, affiliated with or endorsed by any processor."}


# --------------------------------------------------------------------------- #
# Feed indexes (rows are shifted in place by evergreen, so index references)
# --------------------------------------------------------------------------- #
AUTHS: dict[str, list[dict]] = defaultdict(list)
for _r in PROC["proc_authorizations"]:
    AUTHS[_r["account_id"]].append(_r)
CTRL = {r["account_id"]: r for r in PROC["proc_card_controls"]}
COF: dict[str, list[dict]] = defaultdict(list)
for _r in PROC["proc_card_on_file"]:
    COF[_r["account_id"]].append(_r)
DISPUTES: dict[str, list[dict]] = defaultdict(list)
for _r in PROC["proc_disputes"]:
    DISPUTES[_r["account_id"]].append(_r)

ORDER = {"Protect": 0, "Support": 1, "Service": 2, "Retain": 3, "Grow": 4}
OPEN_STAGES = {"Inquiry", "Chargeback filed", "Representment received", "Pre-arbitration"}

# Simulator state: controls changed by actions, new disputes, audit log, events.
_lock = threading.Lock()
_state: dict[str, Any] = {"controls": {}, "disputes": defaultdict(list), "log": defaultdict(list), "events": [], "seq": 0}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _as_of() -> date:
    return evergreen.as_of()


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace(" ", "T"))


def _d(s: str) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _support_first(a: dict) -> bool:
    return a["behaviour"] == "Persistent debt" or a["wellness_band"] == "Vulnerable" or int(a["days_past_due"]) > 0


def controls(aid: str) -> dict[str, Any]:
    base = CTRL[aid]
    return {**base, **_state["controls"].get(aid, {})}


def disputes(aid: str) -> list[dict]:
    return DISPUTES[aid] + _state["disputes"][aid]


# --------------------------------------------------------------------------- #
# Insights - deterministic, each tied to a play and a policy
# --------------------------------------------------------------------------- #
def _card_testing(rows: list[dict]) -> list[dict]:
    """Small card-not-present attempts (< $5) at digital merchants, three or more inside an hour."""
    small = sorted((r for r in rows if r["channel"] == "CNP" and _num(r["amount_cad"]) < 5 and r["recurring"] == "N"),
                   key=lambda r: r["auth_ts"])
    for i in range(len(small)):
        window = [r for r in small[i:] if (_dt(r["auth_ts"]) - _dt(small[i]["auth_ts"])) <= timedelta(minutes=60)]
        if len(window) >= 3:
            return window
    return []


def insights(aid: str) -> list[dict[str, Any]]:
    a = ACC[aid]
    rows = AUTHS[aid]
    ctl = controls(aid)
    as_of = _as_of()
    support = _support_first(a)
    out: list[dict[str, Any]] = []

    def add(code, kind, title, detail, *, evidence=(), value=0.0, policy="", play=None, actions=(), new_signal=False):
        out.append({"code": code, "type": kind, "title": title, "detail": detail, "evidence": list(evidence),
                    "value_cad": round(value), "policy": policy, "play": play, "actions": list(actions), "new_signal": new_signal})

    burst = _card_testing(rows)
    if burst:
        approved = [r for r in burst if r["decision"] == "Approved"]
        big = [r for r in rows if r["channel"] == "CNP" and r["response_code"] == "59" and _num(r["amount_cad"]) >= 100]
        unseen = int(a["fraud_alerts_90d"]) == 0
        add("CARD_TESTING", "Protect",
            "Card-testing pattern" + (" the book has not flagged" if unseen else ""),
            f"{len(burst)} card-not-present attempts under $5 within an hour at {len({r['merchant_name'] for r in burst})} digital "
            f"merchants abroad; {len(approved)} approved" + (f", then a ${_num(big[0]['amount_cad']):,.0f} attempt declined as suspected fraud" if big else "")
            + (". No fraud alert in the Fabric book yet - the processor sees it first." if unseen else "."),
            evidence=[r["auth_id"] for r in burst + big], value=sum(_num(r["amount_cad"]) for r in burst + big),
            policy="RP-022 · RP-035", play="Security check-in", actions=["temp_lock", "reissue", "open_dispute"], new_signal=unseen)

    nsf = [r for r in rows if r["response_code"] == "51"]
    if len(nsf) >= 2:
        add("DECLINES_AT_LIMIT", "Support", f"Declined at the limit {len(nsf)} times in 30 days",
            f"Everyday purchases (groceries, fuel) declined for insufficient credit; utilisation {_num(a['utilization_pct']):.0f}%. "
            "Lead with a lower-cost path - never a limit increase (RP-020, RP-021).",
            evidence=[r["auth_id"] for r in nsf], value=sum(_num(r["amount_cad"]) for r in nsf),
            policy="RP-021 · RP-020", play="Persistent-debt support")

    stopped = [b for b in COF[aid] if b["status"] == "Stopped"]
    if stopped:
        yearly = sum(_num(b["amount_cad"]) for b in stopped) * 12
        flagged = _num(a["spend_trend_pct"]) < -35
        add("BILLERS_STOPPED", "Retain", f"{len(stopped)} recurring biller{'s' if len(stopped) > 1 else ''} stopped billing this card",
            ", ".join(f"{b['merchant_name']} (last {b['last_billed']})" for b in stopped)
            + f" - about ${yearly:,.0f} a year of recurring spend has likely moved to another card.",
            evidence=[b["merchant_name"] for b in stopped], value=yearly, policy="RP-019 · RP-011",
            play="Spend decline", new_signal=not flagged)

    exp = date.fromisoformat(ctl["card_expiry"] + "-01")
    days_to_exp = (exp - as_of).days
    active_cof = [b for b in COF[aid] if b["status"] == "Active"]
    if 0 <= days_to_exp <= 62 and active_cof and ctl["account_updater_enrolled"] != "Y":
        add("EXPIRY_BILLERS", "Service", f"Card expires {ctl['card_expiry']} with {len(active_cof)} billers on file",
            "Account Updater is not enrolled, so these billers will decline after reissue: "
            + ", ".join(b["merchant_name"] for b in active_cof) + ". Push the new card details before expiry.",
            evidence=[b["merchant_name"] for b in active_cof], value=sum(_num(b["amount_cad"]) for b in active_cof) * 12,
            policy="RP-036", play=None, actions=["account_updater_push"])

    fx = [r for r in rows if r["merchant_country"] != "CA" and r["decision"] == "Approved" and _num(r["amount_cad"]) >= 5]
    fx_fees = sum(_num(r["fx_fee_cad"]) for r in fx)
    if fx_fees >= 10:
        add("FX_FEES", "Grow", f"${fx_fees:,.2f} in FX fees in 30 days",
            f"{len(fx)} cross-border purchases ({', '.join(sorted({r['merchant_country'] for r in fx}))}) on a card that charges 2.5%."
            + (" Suppressed: support-first client (RP-012, RP-021)." if support else " A no-FX card would remove this cost (RP-019)."),
            evidence=[r["auth_id"] for r in fx], value=fx_fees * 12, policy="RP-019", play="Upgrade fit: travel")

    for dsp in disputes(aid):
        due = _d(dsp.get("response_due", ""))
        if dsp["stage"] in OPEN_STAGES and due and (due - as_of).days <= 10:
            add("DISPUTE_DUE", "Service", f"Dispute {dsp['dispute_id']} - response due in {(due - as_of).days} days",
                f"{dsp['reason']} ({dsp['reason_code']}) for ${_num(dsp['amount_cad']):,.2f} at {dsp['merchant_name']}; stage {dsp['stage']}. "
                "Keep the client informed and meet the network deadline.",
                evidence=[dsp["dispute_id"]], value=_num(dsp["amount_cad"]), policy="RP-036")

    if ctl["alerts_enrolled"] != "Y" and (burst or int(a["fraud_alerts_90d"]) > 0):
        add("ALERTS_OFF", "Protect", "Real-time alerts are off",
            "Transaction alerts would have shown the client the test charges as they happened.",
            policy="RP-022", play="Security check-in", actions=["enrol_alerts"])

    # Offer only the actions policy allows right now; record what has already been done.
    done = defaultdict(list)
    for entry in _state["log"][aid]:
        done[entry["action"]].append(f"{entry['label']} · {entry['approver']} · {entry['reference']}")
    for i in out:
        cands = i["actions"]
        i["actions"] = [x for x in cands if not any(g["status"] == "block" for g in _guards(aid, x))]
        i["done"] = [d for x in cands for d in done[x]]
    out.sort(key=lambda x: (ORDER[x["type"]], -x["value_cad"]))
    return out


def annotate(rows: list[dict]) -> list[dict]:
    """Add the processor signal to the card-book list rows."""
    for r in rows:
        ins = insights(r["account_id"])
        r["processor_signals"] = len(ins)
        r["processor_top"] = ins[0]["title"] if ins else None
        r["processor_new"] = any(i["new_signal"] for i in ins)
    return rows


# --------------------------------------------------------------------------- #
# Portfolio and account views
# --------------------------------------------------------------------------- #
def overview() -> dict[str, Any]:
    auths = PROC["proc_authorizations"]
    total = len(auths)
    approved = sum(r["decision"] == "Approved" for r in auths)
    declines = Counter((r["response_code"], r["response_text"]) for r in auths if r["decision"] == "Declined")
    cnp = sum(r["channel"] == "CNP" for r in auths)
    xb = sum(r["merchant_country"] != "CA" for r in auths)
    wallet = sum(bool(r["wallet"]) for r in auths)
    dsp = [d for aid in ACC for d in disputes(aid)]
    by_stage = Counter(d["stage"] for d in dsp)
    per_acc = {aid: insights(aid) for aid in ACC}
    flat = [{**i, "account_id": aid, "customer_name": ACC[aid]["customer_name"], "product_name": ACC[aid]["product_name"]}
            for aid, ins in per_acc.items() for i in ins]
    flat.sort(key=lambda x: (not x["new_signal"], ORDER[x["type"]], -x["value_cad"]))
    # Show the range of signals: every new-to-the-book insight, then the top two of each kind.
    picked = [i for i in flat if i["new_signal"]]
    for code in dict.fromkeys(i["code"] for i in flat):
        picked += [i for i in flat if i["code"] == code and not i["new_signal"]][:2]
    picked += [i for i in flat if i not in picked]
    codes = Counter(i["code"] for i in flat)
    as_of = _as_of()
    expiring = sum(0 <= (date.fromisoformat(controls(a)["card_expiry"] + "-01") - as_of).days <= 62 for a in ACC)
    return {
        "profile": profile(),
        "as_of": as_of.isoformat(),
        "feeds": PROC["proc_feed_files"],
        "kpis": {
            "auths_30d": total, "approval_rate": round(approved / total * 100, 1) if total else 0,
            "declines": total - approved, "cnp_share": round(cnp / total * 100, 1) if total else 0,
            "cross_border_share": round(xb / total * 100, 1) if total else 0, "wallet_share": round(wallet / total * 100, 1) if total else 0,
            "disputes_open": sum(d["stage"] in OPEN_STAGES for d in dsp),
            "card_testing": codes["CARD_TESTING"], "unseen_by_book": sum(1 for aid, ins in per_acc.items() if any(i["new_signal"] for i in ins)),
            "declines_at_limit": codes["DECLINES_AT_LIMIT"], "billers_stopped": sum(b["status"] == "Stopped" for b in PROC["proc_card_on_file"]),
            "expiring_60d": expiring, "alerts_off": sum(controls(a)["alerts_enrolled"] != "Y" for a in ACC),
            "fx_fees_30d": round(sum(_num(r["fx_fee_cad"]) for r in auths), 2),
        },
        "declines_by_code": [{"code": c, "text": t, "count": n} for (c, t), n in declines.most_common()],
        "disputes_by_stage": [{"stage": s, "count": n} for s, n in by_stage.most_common()],
        "insight_counts": [{"code": c, "count": n} for c, n in codes.most_common()],
        "insights": picked[:16],
        "events": events(12),
    }


def account(aid: str) -> dict[str, Any] | None:
    if aid not in ACC:
        return None
    a = ACC[aid]
    rows = sorted(AUTHS[aid], key=lambda r: r["auth_ts"], reverse=True)
    ins = insights(aid)
    flagged = {e for i in ins for e in i["evidence"]}
    return {
        "profile": profile(),
        "account_id": aid, "customer_name": a["customer_name"], "support_first": _support_first(a),
        "controls": controls(aid),
        "insights": ins,
        "authorizations": [{**r, "flagged": r["auth_id"] in flagged} for r in rows],
        "summary": {"auths": len(rows), "declined": sum(r["decision"] == "Declined" for r in rows),
                    "cnp": sum(r["channel"] == "CNP" for r in rows), "cross_border": sum(r["merchant_country"] != "CA" for r in rows),
                    "spend_approved": round(sum(_num(r["amount_cad"]) for r in rows if r["decision"] == "Approved"), 2)},
        "card_on_file": COF[aid],
        "disputes": disputes(aid),
        "actions": [dict(ACTIONS[k], id=k) for k in ACTIONS],
        "log": list(reversed(_state["log"][aid])),
        "prompts": [
            {"label": "Explain the processor signals", "prompt": f"For card account {aid}, explain what the card processor feed shows that the "
             "monthly card tables do not: declines, card-not-present activity, card-on-file billers and disputes. Use the Fabric IQ proc_* tables "
             "and cite RP-022, RP-035 and RP-036 where relevant."},
            {"label": "Draft a security call script", "prompt": f"Draft a short security call script for card account {aid} based on the processor "
             "evidence. Never ask for a PIN, passcode or full card number (RP-022). Do not mention internal risk scores."},
        ],
    }


# --------------------------------------------------------------------------- #
# Simulated vendor API - preview and execute servicing actions
# --------------------------------------------------------------------------- #
ACTIONS: dict[str, dict[str, Any]] = {
    "temp_lock": {"label": "Temporarily lock the card", "method": "PATCH", "path": "/cards/{token}/status", "policy": "RP-035",
                  "effect": "Blocks new authorisations; recurring billers keep working; reversible by the client in the app."},
    "unlock": {"label": "Unlock the card", "method": "PATCH", "path": "/cards/{token}/status", "policy": "RP-035",
               "effect": "Restores authorisations."},
    "reissue": {"label": "Block and reissue (compromised)", "method": "POST", "path": "/cards/{token}/reissue", "policy": "RP-035",
                "effect": "Permanently blocks the current card number and orders a new card; Account Updater pushes the new number to enrolled billers."},
    "enrol_alerts": {"label": "Enrol real-time alerts", "method": "PUT", "path": "/cards/{token}/alerts", "policy": "RP-022",
                     "effect": "Push and SMS alerts for card-not-present, cross-border and declined transactions."},
    "account_updater_push": {"label": "Push new card details to billers", "method": "POST", "path": "/cards/{token}/account-updater",
                             "policy": "RP-036", "effect": "Sends updated card details to card-on-file billers through the network updater service."},
    "open_dispute": {"label": "Open a fraud dispute", "method": "POST", "path": "/disputes", "policy": "RP-036",
                     "effect": "Files a card-absent fraud dispute (reason 10.4) for the approved test charges and grants provisional credit."},
}


def _request(aid: str, action: str, reason: str) -> dict[str, Any]:
    p = profile()
    spec = ACTIONS[action]
    ctl = controls(aid)
    tok = ctl["card_token"]
    body: dict[str, Any]
    if action == "temp_lock":
        body = {"status": "TEMP_LOCKED", "reasonCode": "SUSPECTED_FRAUD", "note": reason}
    elif action == "unlock":
        body = {"status": "ACTIVE", "note": reason}
    elif action == "reissue":
        body = {"reason": "COMPROMISED", "blockCurrent": True, "expedite": True, "deliveryAddress": "ON_FILE", "pushToAccountUpdater": True}
    elif action == "enrol_alerts":
        body = {"channels": ["PUSH", "SMS"], "triggers": ["CARD_NOT_PRESENT", "CROSS_BORDER", "DECLINED", "AMOUNT_OVER:100"]}
    elif action == "account_updater_push":
        body = {"merchants": [b["merchant_name"] for b in COF[aid] if b["status"] == "Active"], "enrolCard": True}
    else:
        burst = [r for r in _card_testing(AUTHS[aid]) if r["decision"] == "Approved"]
        body = {"cardToken": tok, "authIds": [r["auth_id"] for r in burst], "reasonCode": "10.4",
                "amount": round(sum(_num(r["amount_cad"]) for r in burst), 2), "currency": "CAD", "provisionalCredit": True}
    return {"method": spec["method"], "url": p["api_base"] + spec["path"].format(token=tok),
            "headers": {"Authorization": "Bearer <managed-identity token via API Management>", "Idempotency-Key": f"{aid}-{action}-<uuid>"},
            "body": body}


def _guards(aid: str, action: str) -> list[dict[str, str]]:
    ctl = controls(aid)
    out = []

    def g(rule, name, ok, detail):
        out.append({"rule": rule, "name": name, "status": "pass" if ok else "block", "detail": detail})

    g("RP-035", "Human approval", True, "A named colleague must approve before the request is sent.")
    if action == "temp_lock":
        g("RP-035", "Card is active", ctl["card_status"] == "Active", f"Card status is {ctl['card_status']}.")
    if action == "unlock":
        g("RP-035", "Card is locked (not blocked)", ctl["card_status"] == "Temporarily locked",
          "Only a temporary lock can be lifted; a blocked card needs the reissued card." if ctl["card_status"] != "Temporarily locked" else "Temporary lock in place.")
    if action == "reissue":
        g("RP-035", "Evidence of compromise", bool(_card_testing(AUTHS[aid])) or int(ACC[aid]["fraud_alerts_90d"]) > 0,
          "Card-testing pattern or fraud alert on record." if (_card_testing(AUTHS[aid]) or int(ACC[aid]["fraud_alerts_90d"])) else
          "No compromise evidence - reissue needs a fraud signal or a client request.")
        g("RP-035", "Not already reissued", ctl["card_status"] != "Blocked - reissued", f"Card status is {ctl['card_status']}.")
    if action == "enrol_alerts":
        g("RP-022", "Not already enrolled", ctl["alerts_enrolled"] != "Y", f"Alerts enrolled: {ctl['alerts_enrolled']}.")
    if action == "account_updater_push":
        active = [b for b in COF[aid] if b["status"] == "Active"]
        g("RP-036", "Billers on file", bool(active), f"{len(active)} active card-on-file billers.")
    if action == "open_dispute":
        burst = [r for r in _card_testing(AUTHS[aid]) if r["decision"] == "Approved"]
        disputed = {x for d in disputes(aid) for x in d["auth_ids"].split(";")}
        fresh = [r for r in burst if r["auth_id"] not in disputed]
        g("RP-036", "Undisputed fraudulent charges", bool(fresh),
          f"{len(fresh)} approved test charge(s) not yet disputed." if fresh else "All approved test charges are already in a dispute.")
    return out


def _event(aid: str, kind: str, detail: str, ref: str) -> dict[str, Any]:
    _state["seq"] += 1
    e = {"id": f"EVT-{_state['seq']:05d}", "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "type": kind,
         "account_id": aid, "detail": detail, "ref": ref, "source": profile()["name"]}
    _state["events"].append(e)
    return e


def run_action(aid: str, action: str, *, reason: str = "", approver: str = "", execute: bool = False) -> dict[str, Any]:
    """Preview (execute=False) or execute a servicing action against the simulated processor."""
    if aid not in ACC:
        raise KeyError(aid)
    if action not in ACTIONS:
        raise ValueError(f"unknown action '{action}'")
    with _lock:
        req = _request(aid, action, reason)
        guards = _guards(aid, action)
        blocked = any(x["status"] == "block" for x in guards)
        result: dict[str, Any] = {"action": action, "label": ACTIONS[action]["label"], "effect": ACTIONS[action]["effect"],
                                  "request": req, "guards": guards, "verdict": "blocked" if blocked else "ready", "executed": False}
        if not execute:
            return result
        if blocked:
            result["error"] = "Blocked by policy - nothing was sent."
            return result
        if not approver.strip():
            result["error"] = "A named approver is required (RP-035)."
            return result

        ctl = _state["controls"].setdefault(aid, {})
        ref = f"PRC-{aid[3:]}-{_state['seq'] + 1:05d}"
        if action == "temp_lock":
            ctl["card_status"] = "Temporarily locked"
            body, ev = {"cardToken": req["url"].split("/")[-2], "status": "TEMP_LOCKED"}, ("card.status.changed", "Card temporarily locked")
        elif action == "unlock":
            ctl["card_status"] = "Active"
            body, ev = {"status": "ACTIVE"}, ("card.status.changed", "Card unlocked")
        elif action == "reissue":
            old = controls(aid)
            last4 = f"{(int(old['masked_pan'][-4:]) * 7 + 13) % 10000:04d}"
            exp = _as_of().replace(day=1) + timedelta(days=365 * 4)
            ctl.update(card_status="Blocked - reissued", reissue_pending="Y", new_masked_pan=f"4520 •••• •••• {last4}",
                       new_card_expiry=f"{exp.year:04d}-{exp.month:02d}", account_updater_enrolled="Y")
            body = {"oldCardStatus": "BLOCKED", "newCard": {"maskedPan": ctl["new_masked_pan"], "expiry": ctl["new_card_expiry"],
                                                           "delivery": "EXPEDITED_2_DAYS"}, "accountUpdater": "QUEUED"}
            ev = ("card.reissued", f"Card blocked and reissued ending {last4}; Account Updater queued")
        elif action == "enrol_alerts":
            ctl["alerts_enrolled"] = "Y"
            body, ev = {"alerts": "ENROLLED", "channels": ["PUSH", "SMS"]}, ("card.alerts.enrolled", "Real-time alerts enrolled")
        elif action == "account_updater_push":
            ctl["account_updater_enrolled"] = "Y"
            n = len(req["body"]["merchants"])
            body, ev = {"submitted": n, "status": "ACCEPTED"}, ("accountupdater.submitted", f"{n} billers sent updated card details")
        else:
            dsp = {"dispute_id": f"DSP-{(_state['seq'] + 1) * 7919 % 90000 + 10000}", "account_id": aid,
                   "auth_ids": ";".join(req["body"]["authIds"]), "merchant_name": "Multiple (card testing)",
                   "amount_cad": req["body"]["amount"], "reason_code": "10.4", "reason": "Fraud - card-absent environment",
                   "stage": "Chargeback filed", "opened": _as_of().isoformat(),
                   "response_due": (_as_of() + timedelta(days=30)).isoformat(), "provisional_credit": "Y",
                   "channel": "Cards workspace", "owner": approver}
            _state["disputes"][aid].append(dsp)
            body, ev = {"disputeId": dsp["dispute_id"], "stage": "CHARGEBACK_FILED", "provisionalCredit": dsp["amount_cad"]}, \
                ("dispute.created", f"Dispute {dsp['dispute_id']} filed for ${dsp['amount_cad']:,.2f}")
        event = _event(aid, ev[0], ev[1], ref)
        response = {"status": 200 if action != "open_dispute" else 201, "body": {"reference": ref, **body}}
        entry = {"ts": event["ts"], "action": action, "label": ACTIONS[action]["label"], "approver": approver, "reason": reason,
                 "reference": ref, "request": req, "response": response, "event": event}
        _state["log"][aid].append(entry)
        result.update(executed=True, response=response, event=event, controls=controls(aid))
        return result


def events(n: int = 20) -> list[dict[str, Any]]:
    """Most recent simulator events, newest first, padded with the feed's own signals."""
    live = list(reversed(_state["events"]))[:n]
    if len(live) >= n:
        return live
    feed = []
    for r in sorted(PROC["proc_authorizations"], key=lambda r: r["auth_ts"], reverse=True):
        if r["risk_score"] >= 850 or r["response_code"] == "51":
            feed.append({"id": r["auth_id"], "ts": r["auth_ts"], "type": "auth.declined" if r["decision"] == "Declined" else "auth.approved",
                         "account_id": r["account_id"], "detail": f"{r['response_text']} · {r['merchant_name']} · ${_num(r['amount_cad']):,.2f}"
                         f" · risk {r['risk_score']}", "ref": r["auth_id"], "source": "feed"})
        if len(live) + len(feed) >= n:
            break
    return live + feed


def reset() -> None:
    with _lock:
        _state["controls"].clear()
        _state["disputes"].clear()
        _state["log"].clear()
        _state["events"].clear()
        _state["seq"] = 0
