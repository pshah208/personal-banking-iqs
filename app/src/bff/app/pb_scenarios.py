"""Renewal scenario engine - market factors -> payment shock -> affordability -> risk -> value.

Deterministic and governed: inputs are the presets / sensitivities served by
Fabric IQ (rate_scenario_presets, renewal_scenario_sensitivity, credit_capacity)
and the RP-013 affordability limits. For every renewal:

  1. Renewal rate  r1 = offered rate + pass-through x (GoC 5Y move, or BoC move
                   for variable) + mortgage-spread move.
  2. Payment       renewal payment scales by annuity(r1) / annuity(offered rate);
                   payment shock is measured against today's payment, so the
                   unshocked run reproduces mortgage_renewals.payment_shock_pct.
  3. Affordability income falls with unemployment (segment beta), obligations rise
                   with inflation; GDS/TDS re-tested against 39% / 44% (RP-013).
  4. Risk          12-month delinquency PD = bureau base PD x TDS multiplier x
                   unemployment uplift (x1.5 if already Vulnerable);
                   attrition = model score + competitor-undercut and shock effects.
  5. Value         retained annual relationship revenue (risk table; mortgage share re-priced by margin) x (1 - attrition)
                   minus expected loss (PD x LGD x balance, LGD from scenario LTV;
                   insured loans 2%), discounted over 5 years.

A renewal "flips" to support-first when its scenario TDS exceeds 44% or it is
already Vulnerable - those clients leave the retention queue (RP-012/RP-013).
SYNTHETIC demo data; decision support only (RP-015).
"""

from __future__ import annotations

from typing import Any

from .pb_data import PB

V = PB["valuation"]
FACTORS = PB["factors"]
FIDS = [f["id"] for f in FACTORS]
LIMITS = {f["id"]: (f["min"], f["max"]) for f in FACTORS}
CAP = {r["customer_id"]: r for r in PB["credit_capacity"]}
WELL = {r["customer_id"]: r for r in PB["financial_wellness"]}
SENS = {r["renewal_id"]: r for r in PB["renewal_scenario_sensitivity"]}
PERIODS = {"Monthly": 12, "Semi-monthly": 24, "Bi-weekly": 26, "Accelerated Bi-weekly": 26, "Weekly": 52}


def library() -> dict[str, Any]:
    return {"factors": FACTORS, "presets": PB["presets"], "good_dir": PB["good_dir"], "as_of": PB["as_of"],
            "valuation": V, "source": "Fabric IQ - rate_scenario_presets, renewal_scenario_sensitivity, credit_capacity"}


def _clean(f: dict[str, Any] | None) -> dict[str, float]:
    out = {}
    for k in FIDS:
        try:
            v = float((f or {}).get(k, 0.0))
        except (TypeError, ValueError):
            v = 0.0
        lo, hi = LIMITS[k]
        out[k] = max(lo, min(hi, v))
    return out


def _annuity_factor(rate_pct: float, years: int, per: int) -> float:
    r = rate_pct / 100 / per
    n = max(1, years * per)
    return r / (1 - (1 + r) ** -n) if r else 1 / n


def _tds_mult(tds: float) -> float:
    return 1.0 if tds < 0.40 else 1.8 if tds < 0.44 else 3.2 if tds < 0.50 else 5.5


def renewal_result(rid: str, fx: dict[str, float]) -> dict[str, Any]:
    r = PB["renewals"][rid]
    cid = r["customer_id"]
    c, rk, cap, s, w = PB["customers"][cid], PB["risk"][rid], CAP[cid], SENS[rid], WELL[cid]
    bal, value = float(r["mortgage_balance_cad"]), float(r["property_value_cad"])
    years, per = int(r["amortization_remaining_years"]), PERIODS.get(r["payment_frequency"], 12)
    r0 = float(r["offered_renewal_rate_pct"])
    move = fx["boc_bp"] if s["rate_index"] == "BoC overnight" else fx["goc5_bp"]
    r1 = r0 + (float(s["rate_pass_through"]) * move + fx["spread_bp"]) / 100
    r1 = max(0.5, r1)

    p_now = float(cap["current_payment_monthly_cad"])
    p0 = float(cap["renewal_payment_monthly_cad"])
    p1 = p0 * _annuity_factor(r1, years, per) / _annuity_factor(r0, years, per)
    shock0 = float(r["payment_shock_pct"])
    shock1 = ((1 + shock0 / 100) * p1 / p0 - 1) * 100

    income0 = float(cap["gross_income_cad"]) / 12
    haircut = float(s["income_beta_unemployment"]) * fx["unemployment_pp"] * V["unemployment_income_haircut"] / 100
    income1 = income0 * max(0.4, 1 - haircut)
    infl = 1 + fx["inflation_pp"] * V["inflation_obligation_uplift"] / 100
    tax, other = float(cap["monthly_tax_heat_cad"]) * infl, float(cap["monthly_other_debt_cad"]) * infl
    tax0, other0 = float(cap["monthly_tax_heat_cad"]), float(cap["monthly_other_debt_cad"])
    gds0, tds0 = (p0 + tax0) / income0, (p0 + tax0 + other0) / income0
    gds1, tds1 = (p1 + tax) / income1, (p1 + tax + other) / income1

    vul = w["vulnerability_flag"] == "Y"
    base_pd = float(cap["base_pd_12m_pct"]) / 100
    pd0 = min(0.35, base_pd * _tds_mult(tds0) * (1.5 if vul else 1))
    pd1 = min(0.35, base_pd * _tds_mult(tds1) * (1 + 0.15 * max(0.0, fx["unemployment_pp"])) * (1.5 if vul else 1))

    att0 = float(rk["attrition_risk_score"])
    att1 = att0 + float(s["attrition_beta_competitor_bp"]) * fx["competitor_gap_bp"] + 0.0012 * max(0.0, shock1 - shock0)
    att1 = max(0.02, min(0.97, att1))

    ltv0, ltv1 = bal / value, bal / (value * (1 + fx["house_price_pct"] / 100))
    def lgd(ltv: float) -> float:
        return V["lgd_insured"] if r["insured_flag"] == "Y" else max(V["lgd_floor"], 0.15 + 0.7 * max(0.0, ltv - 0.6))
    margin0 = V["funding_margin_bps"] / 10000
    margin1 = (V["funding_margin_bps"] + V["spread_share"] * fx["spread_bp"] - fx["competitor_gap_bp"] * 0.3) / 10000
    disc = V["discount_pct"] / 100
    ann = sum(1 / (1 + disc) ** t for t in range(1, V["horizon_years"] + 1))

    def econ(att: float, pd_: float, ltv: float, margin: float) -> dict[str, float]:
        nii = bal * margin * (1 - att)
        el = pd_ * V["default_given_delinquency"] * lgd(ltv) * bal
        return {"nii": nii, "el": el, "value": (nii - el) * ann}
    e0, e1 = econ(att0, pd0, ltv0, margin0), econ(att1, pd1, ltv1, margin1)

    def action(tds: float) -> str:
        return "Support first" if vul or tds > 0.44 else "Retain" if att1 >= 0.5 else "Renew"
    a0 = "Support first" if vul or tds0 > 0.44 else "Retain" if att0 >= 0.5 else "Renew"
    a1 = action(tds1)
    return {
        "renewal_id": rid, "customer_id": cid, "name": c["full_name"], "segment": c["segment"],
        "branch_id": r["branch_id"], "branch": c["branch_name"], "product": r["product_type"],
        "days_to_maturity": int(r["days_to_maturity"]), "balance": bal, "insured": r["insured_flag"] == "Y",
        "rate_before": round(r0, 2), "rate_after": round(r1, 2),
        "payment_now": round(p_now), "payment_before": round(p0), "payment_after": round(p1),
        "shock_before_pct": round(shock0, 1), "shock_after_pct": round(shock1, 1),
        "gds_before_pct": round(gds0 * 100, 1), "gds_after_pct": round(gds1 * 100, 1),
        "tds_before_pct": round(tds0 * 100, 1), "tds_after_pct": round(tds1 * 100, 1),
        "pd_before_pct": round(pd0 * 100, 2), "pd_after_pct": round(pd1 * 100, 2),
        "attrition_before": round(att0, 3), "attrition_after": round(att1, 3),
        "ltv_before_pct": round(ltv0 * 100, 1), "ltv_after_pct": round(ltv1 * 100, 1),
        "nii_before": round(e0["nii"]), "nii_after": round(e1["nii"]),
        "el_before": round(e0["el"]), "el_after": round(e1["el"]),
        "value_before": round(e0["value"]), "value_after": round(e1["value"]),
        "value_change": round(e1["value"] - e0["value"]),
        "wellness_band": w["wellness_band"], "vulnerable": vul,
        "action_before": a0, "action_after": a1, "flipped": a0 != "Support first" and a1 == "Support first",
    }


def run(factors: dict[str, Any] | None, name: str = "Custom") -> dict[str, Any]:
    fx = _clean(factors)
    rows = [renewal_result(rid, fx) for rid in PB["renewals"]]
    rows.sort(key=lambda x: (not x["flipped"], x["value_change"]))
    tot = lambda k: sum(x[k] for x in rows)  # noqa: E731
    bal = tot("balance")
    w_avg = lambda k: sum(x[k] * x["balance"] for x in rows) / bal  # noqa: E731

    def roll(key: str) -> list[dict]:
        g: dict[str, dict] = {}
        for x in rows:
            b = g.setdefault(x[key], {"key": x[key], "count": 0, "balance": 0.0, "value_before": 0.0, "value_after": 0.0,
                                      "above_tds": 0, "flipped": 0, "shock_after_w": 0.0})
            b["count"] += 1
            b["balance"] += x["balance"]
            b["value_before"] += x["value_before"]
            b["value_after"] += x["value_after"]
            b["above_tds"] += x["tds_after_pct"] > V["tds_limit_pct"]
            b["flipped"] += x["flipped"]
            b["shock_after_w"] += x["shock_after_pct"] * x["balance"]
        return [{**b, "avg_shock_after_pct": round(b["shock_after_w"] / b["balance"], 1),
                 "value_change": round(b["value_after"] - b["value_before"])} for b in g.values()]

    return {
        "name": name, "factors": fx, "as_of": PB["as_of"],
        "portfolio": {
            "renewals": len(rows), "balance": round(bal),
            "avg_shock_before_pct": round(w_avg("shock_before_pct"), 1), "avg_shock_after_pct": round(w_avg("shock_after_pct"), 1),
            "above_tds_before": sum(x["tds_before_pct"] > V["tds_limit_pct"] for x in rows),
            "above_tds_after": sum(x["tds_after_pct"] > V["tds_limit_pct"] for x in rows),
            "expected_delinquencies_before": round(sum(x["pd_before_pct"] for x in rows) / 100, 2),
            "expected_delinquencies_after": round(sum(x["pd_after_pct"] for x in rows) / 100, 2),
            "expected_attrition_before": round(sum(x["attrition_before"] for x in rows), 1),
            "expected_attrition_after": round(sum(x["attrition_after"] for x in rows), 1),
            "balance_at_risk_after": round(sum(x["balance"] * x["attrition_after"] for x in rows)),
            "nii_before": round(tot("nii_before")), "nii_after": round(tot("nii_after")),
            "el_before": round(tot("el_before")), "el_after": round(tot("el_after")),
            "value_before": round(tot("value_before")), "value_after": round(tot("value_after")),
            "value_change": round(tot("value_after") - tot("value_before")),
            "value_change_pct": round((tot("value_after") / tot("value_before") - 1) * 100, 1),
            "support_first_before": sum(x["action_before"] == "Support first" for x in rows),
            "support_first_after": sum(x["action_after"] == "Support first" for x in rows),
            "flipped": sum(x["flipped"] for x in rows),
        },
        "branches": roll("branch"), "segments": roll("segment"),
        "renewals": rows,
        "method": __doc__.split("SYNTHETIC")[0].strip(),
    }


def narrative_prompt(result: dict[str, Any], context: str = "") -> str:
    f, p = result["factors"], result["portfolio"]
    lab = {x["id"]: (x["label"], x["unit"]) for x in FACTORS}
    moves = ", ".join(f"{lab[k][0]} {v:+g}{lab[k][1]}" for k, v in f.items() if v) or "no factor moves"
    top = [x for x in result["renewals"] if x["flipped"]][:4] + sorted(result["renewals"], key=lambda x: x["value_change"])[:4]
    seen, lines = set(), []
    for x in top:
        if x["renewal_id"] in seen:
            continue
        seen.add(x["renewal_id"])
        lines.append(f"{x['renewal_id']} ({x['segment']}, {x['branch']}): payment shock {x['shock_before_pct']:.0f}%->{x['shock_after_pct']:.0f}%, "
                     f"TDS {x['tds_before_pct']:.1f}%->{x['tds_after_pct']:.1f}%, 12m delinquency PD {x['pd_before_pct']:.2f}%->{x['pd_after_pct']:.2f}%, "
                     f"attrition {x['attrition_before']:.2f}->{x['attrition_after']:.2f}, action {x['action_before']} -> {x['action_after']}")
    br = "; ".join(f"{b['key']}: {b['above_tds']} above TDS, {b['flipped']} flipped, value {b['value_change']:+,} CAD"
                   for b in result["branches"])
    return (
        f"Renewal scenario '{result['name']}' as at {result['as_of']} (synthetic): {moves}. Treat the scenario as given.\n"
        + (f"{context}\n" if context else "")
        + f"Engine results (deterministic, governed inputs from Fabric IQ): balance-weighted payment shock "
        f"{p['avg_shock_before_pct']}% -> {p['avg_shock_after_pct']}%; renewals above the 44% TDS guideline {p['above_tds_before']} -> "
        f"{p['above_tds_after']}; expected delinquencies {p['expected_delinquencies_before']} -> {p['expected_delinquencies_after']}; "
        f"expected attrition {p['expected_attrition_before']} -> {p['expected_attrition_after']} renewals; support-first clients "
        f"{p['support_first_before']} -> {p['support_first_after']} ({p['flipped']} newly flipped from retention); 5-year relationship value "
        f"CAD {p['value_before']:,} -> {p['value_after']:,} ({p['value_change_pct']:+.1f}%).\nBranches: {br}.\n"
        + "\n".join(lines)
        + "\n\nWrite a short brief for the Retail Risk Committee: (1) one-sentence headline; (2) which branches and segments are most "
        "exposed and why, verifying affordability and wellness in Fabric IQ; (3) what RP-013, RP-012, RP-014 and RP-015 require; "
        "(4) three concrete actions with owner roles. Refer to the firm as 'the Bank'. Refer to clients by renewal ID, never by name."
    )
