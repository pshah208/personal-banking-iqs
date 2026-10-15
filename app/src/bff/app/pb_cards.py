"""Cards book - portfolio intelligence, plays and outreach guardrails (deterministic core).

Data = governed Fabric IQ card tables (bundled in cards_data). For card holders
who also hold a mortgage, wellness / consent / TDS come from the personal-banking
tables, so a client flagged support-first in the mortgage book is support-first
on their card too (RP-012, RP-020, RP-021). SYNTHETIC demo data.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .cards_data import CARDS
from .pb_customers import BANNED

ACC = {a["account_id"]: a for a in CARDS["card_accounts"]}
PROD = {p["product_id"]: p for p in CARDS["card_products"]}
SPEND = defaultdict(list)
for _r in CARDS["card_spend_monthly"]:
    SPEND[_r["account_id"]].append(_r)
PLAYS = defaultdict(list)
for _r in CARDS["card_next_actions"]:
    PLAYS[_r["account_id"]].append(_r)
CATS = ["groceries", "dining", "travel", "gas_transit", "bills", "online", "other"]


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _row(a: dict) -> dict[str, Any]:
    plays = PLAYS[a["account_id"]]
    return {**{k: a[k] for k in ("account_id", "customer_id", "customer_name", "segment", "branch", "product_id", "product_name",
                                 "behaviour", "wellness_band", "email_consent", "linked_mortgage", "top_category")},
            "credit_limit": _num(a["credit_limit"]), "balance": _num(a["balance"]), "utilization_pct": _num(a["utilization_pct"]),
            "monthly_spend_avg": _num(a["monthly_spend_avg"]), "spend_trend_pct": _num(a["spend_trend_pct"]),
            "annual_fee": _num(a["annual_fee"]), "fee_anniversary_days": int(a["fee_anniversary_days"]),
            "days_past_due": int(a["days_past_due"]), "fraud_alerts_90d": int(a["fraud_alerts_90d"]),
            "top_play": plays[0] if plays else None, "plays": len(plays)}


def overview() -> dict[str, Any]:
    accs = list(ACC.values())
    bal = sum(_num(a["balance"]) for a in accs)
    lim = sum(_num(a["credit_limit"]) for a in accs)
    spend12 = sum(_num(r["spend"]) for r in CARDS["card_spend_monthly"])
    by_month = defaultdict(float)
    for r in CARDS["card_spend_monthly"]:
        by_month[r["month"]] += _num(r["spend"])
    cat = {c: sum(_num(r[c]) for r in CARDS["card_spend_monthly"]) for c in CATS}
    beh = Counter(a["behaviour"] for a in accs)
    plays = Counter()
    blocked = Counter()
    for r in CARDS["card_next_actions"]:
        (plays if r["eligibility"] == "Eligible" else blocked)[r["play"]] += 1
    mix = defaultdict(lambda: {"accounts": 0, "balance": 0.0, "spend": 0.0})
    for a in accs:
        m = mix[a["product_name"]]
        m["accounts"] += 1
        m["balance"] += _num(a["balance"])
        m["spend"] += _num(a["monthly_spend_avg"]) * 12
    return {
        "as_of": accs[0]["as_of_date"],
        "kpis": {"accounts": len(accs), "linked_to_mortgage": sum(a["linked_mortgage"] == "Y" for a in accs),
                 "balances": round(bal), "limits": round(lim), "utilization_pct": round(bal / lim * 100, 1),
                 "spend_12m": round(spend12), "revolving_share_pct": round(100 * (beh["Revolver"] + beh["Persistent debt"]) / len(accs)),
                 "persistent_debt": beh["Persistent debt"], "past_due_30": sum(int(a["days_past_due"]) >= 30 for a in accs),
                 "fraud_alerts": sum(int(a["fraud_alerts_90d"]) > 0 for a in accs),
                 "rewards_liability": round(sum(_num(a["rewards_points"]) for a in accs) / 100),
                 "fee_renewals_60d": sum(int(a["fee_anniversary_days"]) <= 60 and _num(a["annual_fee"]) > 0 for a in accs)},
        "behaviour": [{"behaviour": k, "accounts": beh[k]} for k in ("Transactor", "Revolver", "Persistent debt")],
        "products": [{"product": k, **{x: round(y) if isinstance(y, float) else y for x, y in v.items()}} for k, v in mix.items()],
        "spend_by_month": [{"month": m, "spend": round(v)} for m, v in sorted(by_month.items())],
        "spend_by_category": [{"category": c, "spend": round(v)} for c, v in sorted(cat.items(), key=lambda x: -x[1])],
        "plays": [{"play": p, "eligible": plays[p], "blocked": blocked[p]} for p in
                  ("Persistent-debt support", "Security check-in", "Fee renewal at risk", "Spend decline", "Upgrade fit: travel", "Credit limit increase")],
    }


def accounts() -> dict[str, Any]:
    order = {"Support": 0, "Protect": 1, "Retain": 2, "Grow": 3, None: 4}
    rows = [_row(a) for a in ACC.values()]
    rows.sort(key=lambda r: (order[r["top_play"]["play_type"] if r["top_play"] else None], -r["balance"]))
    return {"accounts": rows, "products": CARDS["card_products"]}


def account(aid: str) -> dict[str, Any] | None:
    a = ACC.get(aid)
    if not a:
        return None
    rid = a["customer_id"]
    return {**_row(a), "account": a, "product": PROD[a["product_id"]], "spend": SPEND[aid], "plays": PLAYS[aid],
            "prompts": [
                {"label": "Brief me on this card", "prompt": f"Brief me on card account {aid} ({rid}): product, limit, balance, payment behaviour, "
                 "12-month spend trend and categories, and any linked mortgage or wellness signals. Verify in Fabric IQ."},
                {"label": "Is this card a good fit?", "prompt": f"Given the spending pattern on card account {aid}, is the current card the best fit? "
                 "Compare expected rewards net of fees across the card shelf and cite RP-019."},
                {"label": "What may I offer?", "prompt": f"For card account {aid}, which plays are eligible and which are blocked, and why? "
                 "Cite RP-011, RP-012, RP-019, RP-020, RP-021 and RP-022 as relevant."},
                {"label": "Compare competitor cards", "prompt": "Use the public web to summarise current Canadian credit-card welcome offers for "
                 "premium travel and cash-back cards (issuer-neutral, dated, with sources). Do not use internal data."},
            ]}


def draft(aid: str, play_index: int = 0, bank: str = "the Bank") -> dict[str, Any] | None:
    a = ACC.get(aid)
    if not a or not PLAYS[aid]:
        return None
    p = PLAYS[aid][max(0, min(play_index, len(PLAYS[aid]) - 1))]
    first = a["customer_name"].split()[0]
    sign = "Kind regards,\nYour card services team"
    if p["play_type"] == "Support":
        bal = _num(a["balance"])
        subject, purpose = "Options to bring your card balance down", "Service"
        body = (f"Hi {first},\n\nWe noticed your card balance has been carried for a while, and we'd like to help make it more manageable. "
                f"Paying only the minimum on a balance of about ${bal:,.0f} can take many years and cost significantly more in interest.\n\n"
                "There are options that may lower your cost - such as a lower-interest card or a fixed instalment plan - and we also offer free "
                "one-on-one budgeting support. There's no obligation.\n\nReply to this message or call us to book a time.\n\n" + sign)
    elif p["play_type"] == "Protect":
        subject, purpose = "A quick security check-in for your card", "Service"
        body = (f"Hi {first},\n\nWe recently flagged unusual activity on your card. You can review recent transactions, lock or unlock your card "
                "and turn on real-time alerts in the mobile app.\n\nWe will never ask you for your PIN, full card number, one-time passcode or "
                "online banking password. If anyone does, it isn't us.\n\n" + sign)
    elif p["play_type"] == "Retain":
        subject, purpose = "Getting the most from your card", "Service" if p["play"] == "Fee renewal at risk" else "Marketing"
        body = (f"Hi {first},\n\nYour card's annual fee comes up soon. We'd like to make sure your card still suits how you spend - "
                "we can review your rewards with you or look at another card in the same family, at no cost to switch.\n\n"
                "Reply to this message or call us if you'd like to talk it through.\n\n" + sign)
        if purpose == "Marketing":
            body += f"\n\nYou are receiving this because you agreed to hear from {bank}. Reply STOP or use the unsubscribe link to opt out."
    else:
        subject, purpose = f"An idea for you: {p['recommended_product']}", "Marketing"
        body = (f"Hi {first},\n\nBased on how you use your card, the {p['recommended_product']} may be a better fit. {p['rationale']}.\n\n"
                "Any product or limit change is subject to approval and your consent. Interest rate and annual fee details are in the "
                "disclosure statement.\n\n" + sign +
                f"\n\nYou are receiving this because you agreed to hear from {bank}. Reply STOP or use the unsubscribe link to opt out.")
    d = {"account_id": aid, "play": p, "channel": "Email", "purpose": purpose, "subject": subject, "body": body}
    return {**d, "checks": checks(aid, d)}


def checks(aid: str, d: dict[str, Any]) -> list[dict[str, str]]:
    a = ACC[aid]
    text = f"{d.get('subject', '')}\n{d.get('body', '')}"
    play = d.get("play") or {}
    out = []
    if d.get("purpose") == "Marketing":
        ok = a["email_consent"] == "Granted"
        out.append({"rule": "RP-011", "name": "Marketing consent", "status": "pass" if ok else "block",
                    "detail": f"Email marketing consent is {a['email_consent']}."})
        unsub = bool(re.search(r"unsubscribe|reply stop", text, re.I))
        out.append({"rule": "RP-011", "name": "Unsubscribe mechanism", "status": "pass" if unsub else "block",
                    "detail": "Present." if unsub else "Missing from a promotional message."})
    support = a["behaviour"] == "Persistent debt" or a["wellness_band"] == "Vulnerable" or int(a["days_past_due"]) > 0
    selling = play.get("play_type") == "Grow" or bool(re.search(r"\b(upgrade|limit increase|higher limit|bonus points|rewards card)\b", text, re.I))
    out.append({"rule": "RP-021", "name": "Persistent debt / support-first", "status": "block" if support and selling else "pass",
                "detail": "Client is support-first: no upgrade, limit increase or new credit." if support and selling else
                ("Support-first client - service message only." if support else "Not a support-first client.")})
    target = next((p for p in PROD.values() if p["product_name"] == play.get("recommended_product")), None)
    if target and _num(a["income"]) < _num(target["min_income"]):
        out.append({"rule": "RP-019", "name": "Product eligibility", "status": "block",
                    "detail": f"{target['product_name']} needs income of ${_num(target['min_income']):,.0f}; recorded ${_num(a['income']):,.0f}."})
    if play.get("play") == "Credit limit increase":
        if a["tds_renewal_pct"] not in ("", None) and _num(a["tds_renewal_pct"]) > 44:
            out.append({"rule": "RP-020", "name": "Affordability for limit increase", "status": "block",
                        "detail": f"Household TDS {a['tds_renewal_pct']}% exceeds the 44% guideline (RP-013)."})
        ok = a["cli_express_consent"] == "Y"
        out.append({"rule": "RP-020", "name": "Express consent for limit increase", "status": "pass" if ok else "block",
                    "detail": "Express consent on file." if ok else "No express consent recorded - the limit cannot be raised."})
    if int(a["fraud_alerts_90d"]) and play.get("play_type") in ("Grow", "Retain"):
        out.append({"rule": "RP-022", "name": "Security before sales", "status": "block", "detail": "Open fraud alert - security check-in first."})
    if re.search(r"\b(pin|passcode|password|full card number)\b", text, re.I) and not re.search(r"never ask", text, re.I):
        out.append({"rule": "RP-022", "name": "Never ask for secrets", "status": "block", "detail": "Message mentions credentials without the 'we will never ask' statement."})
    hits = []
    for pat, rule, why in BANNED:
        m = re.search(pat, text, re.I)
        if m:
            hits.append({"rule": rule, "name": why, "status": "block", "detail": f"Found: \"{m.group(0)}\""})
    out.extend(hits or [{"rule": "RP-016", "name": "Prohibited words and internal data", "status": "pass", "detail": "None found."}])
    return out


def verdict(cks: list[dict[str, str]]) -> str:
    return "blocked" if any(c["status"] == "block" for c in cks) else "needs_approval" if any(c["status"] == "warn" for c in cks) else "pass"


def review_prompt(aid: str, d: dict[str, Any], cks: list[dict[str, str]]) -> str:
    a = ACC[aid]
    det = "\n".join(f"- {c['rule']} {c['name']}: {c['status'].upper()} - {c['detail']}" for c in cks)
    play = d.get("play") or {}
    return (
        f"Review this credit-card client communication before it can be saved as a draft. Internal context (do NOT repeat to the client): "
        f"behaviour {a['behaviour']}, wellness band {a['wellness_band']}, fraud alerts {a['fraud_alerts_90d']}, purpose {d.get('purpose')}, "
        f"play {play.get('play_type')} / {play.get('play')}.\nDeterministic checks already run (authoritative):\n{det}\n\n"
        f"DRAFT SUBJECT: {d.get('subject', '')}\nDRAFT BODY:\n{d.get('body', '')}\n\n"
        "Return 'VERDICT: PASS', 'VERDICT: NEEDS FIXES' or 'VERDICT: BLOCKED' first (never weaker than the checks), then a findings table "
        "(exact text, policy RP-011/RP-012/RP-016/RP-019/RP-020/RP-021/RP-022, why), then a corrected draft in a ```text block if fixable. "
        "Refer to the firm as 'the Bank'. You review; you never send or approve."
    )
