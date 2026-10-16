# Fabric notebook - load the Mortgage Renewal Concierge dataset into a Lakehouse
#
# SYNTHETIC DEMO DATA. CFC Bank is used only as a branding label; nothing here
# reflects real CFC Bank customers, pricing or policy.
#
# HOW TO USE
#   Automated:  python deploy_fabric.py --only notebook
#   Manual:     create a Lakehouse `lh_mortgage_renewals`, upload the five CSVs to
#               Files/renewals/, create a Notebook attached to it, paste this file,
#               Run all.
#
# EVERGREEN DATES
#   The CSVs are one fixed snapshot dated 2026-08-03. deploy_fabric.py inlines
#   app/src/bff/app/evergreen.py above this cell, and the load below moves every
#   date forward by whole weeks to the current week before writing the tables -
#   the same rule the app uses, so the agent and the app agree on "today".
#   deploy_fabric.py also schedules this notebook, so the tables roll forward on
#   their own. Pasted manually without the inlined module, dates load unshifted.
#
# WHY TABLES AND NOT VIEWS
#   Spark SQL views live only in the Spark metastore. They are NOT visible through
#   the SQL analytics endpoint and cannot back a Direct Lake semantic model. The
#   curated layer is therefore materialised as Delta *tables*, so the same objects
#   serve the SQL endpoint, the semantic model and the agent's Fabric IQ tool.

import os
from datetime import datetime, timedelta, timezone

try:
    shift_text, offset_days, BASE  # noqa: B018 - inlined by deploy_fabric.py
except NameError:
    from datetime import date as _date

    BASE = _date(2026, 8, 3)

    def offset_days():
        return 0

    def shift_text(text, days=None):
        return text

SOURCE = "Files/renewals"
CURRENT = "Files/renewals_current"
MOUNT = "/lakehouse/default"

BASE_TABLES = {
    "customers": "customers.csv",
    "mortgage_renewals": "mortgage_renewals.csv",
    "renewal_risk_scores": "renewal_risk_scores.csv",
    "retention_offers": "retention_offers.csv",
    "branch_performance": "branch_performance.csv",
    # Personal-banking expansion (generate_pb_tables.py)
    "households": "households.csv",
    "credit_capacity": "credit_capacity.csv",
    "customer_products": "customer_products.csv",
    "financial_signals_monthly": "financial_signals_monthly.csv",
    "life_events": "life_events.csv",
    "consent_preferences": "consent_preferences.csv",
    "financial_wellness": "financial_wellness.csv",
    "next_best_actions": "next_best_actions.csv",
    "rate_scenario_presets": "rate_scenario_presets.csv",
    "renewal_scenario_sensitivity": "renewal_scenario_sensitivity.csv",
    # Cards book (generate_cards_tables.py)
    "card_products": "card_products.csv",
    "card_accounts": "card_accounts.csv",
    "card_spend_monthly": "card_spend_monthly.csv",
    "card_next_actions": "card_next_actions.csv",
    # Card processor feed - simulated system of record (generate_processor_tables.py)
    "proc_authorizations": "proc_authorizations.csv",
    "proc_card_controls": "proc_card_controls.csv",
    "proc_card_on_file": "proc_card_on_file.csv",
    "proc_disputes": "proc_disputes.csv",
    "proc_feed_files": "proc_feed_files.csv",
    # Mortgage servicing feed - simulated system of record (generate_servicing_tables.py)
    "svc_payment_history": "svc_payment_history.csv",
    "svc_payout_requests": "svc_payout_requests.csv",
    "svc_bureau_inquiries": "svc_bureau_inquiries.csv",
    "svc_renewal_offers": "svc_renewal_offers.csv",
    "svc_feed_files": "svc_feed_files.csv",
    "deposit_accounts": "deposit_accounts.csv",
    "deposit_flows_monthly": "deposit_flows_monthly.csv",
    "banking_next_actions": "banking_next_actions.csv",
    "credit_facilities": "credit_facilities.csv",
    "debt_consolidation_candidates": "debt_consolidation_candidates.csv",
    "borrowing_next_actions": "borrowing_next_actions.csv",
    "investment_accounts": "investment_accounts.csv",
    "registered_room": "registered_room.csv",
    "investing_next_actions": "investing_next_actions.csv",
    "newcomer_journey": "newcomer_journey.csv",
    "transfers_out_monthly": "transfers_out_monthly.csv",
    "newcomers_next_actions": "newcomers_next_actions.csv",
    "insurance_policies": "insurance_policies.csv",
    "coverage_gaps": "coverage_gaps.csv",
    "insurance_next_actions": "insurance_next_actions.csv",
    "security_events": "security_events.csv",
    "customer_security_posture": "customer_security_posture.csv",
    "security_next_actions": "security_next_actions.csv",
}

DAYS = offset_days()
os.makedirs(f"{MOUNT}/{CURRENT}", exist_ok=True)
for filename in BASE_TABLES.values():
    with open(f"{MOUNT}/{SOURCE}/{filename}", encoding="utf-8") as fh:
        text = fh.read()
    with open(f"{MOUNT}/{CURRENT}/{filename}", "w", encoding="utf-8") as fh:
        fh.write(shift_text(text, DAYS))
print(f"evergreen: snapshot {BASE} -> {(BASE + timedelta(days=DAYS))} (+{DAYS} days)")

for table, filename in BASE_TABLES.items():
    df = (
        spark.read.option("header", "true")
        .option("inferSchema", "true")
        .csv(f"{CURRENT}/{filename}")
    )
    df.write.mode("overwrite").option("overwriteSchema", "true") \
        .format("delta").saveAsTable(table)
    print(f"{table:<24} {df.count():>4} rows")

# One row recording which week the tables represent, so a stale load (capacity
# paused through a scheduled run) is visible from the SQL endpoint.
spark.createDataFrame(
    [(BASE.isoformat(), (BASE + timedelta(days=DAYS)).isoformat(), DAYS,
      datetime.now(timezone.utc).isoformat(timespec="seconds"))],
    "snapshot_base_date string, as_of_date string, offset_days int, loaded_utc string",
).write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable("data_as_of")

# --------------------------------------------------------------------------- #
# Curated fact table - one row per renewal maturing within 180 days, with the
# customer, risk score and recommended offer joined in. This is what the agent's
# Fabric IQ tool queries and what the semantic model is built on. The banded
# columns (ltv_band, payment_shock_band) exist because the CRO's monthly renewal
# pack requires reporting on exactly those splits - see policy RP-009.
# --------------------------------------------------------------------------- #
renewal_attrition_risk = spark.sql(
    """
    SELECT
        r.renewal_id,
        c.customer_id,
        c.full_name,
        c.segment,
        c.province,
        c.preferred_language,
        c.origination_channel,
        c.tenure_years,
        c.products_held,
        c.primary_relationship_flag,
        c.digital_engagement_score,
        c.nps_score,
        r.branch_id,
        b.branch_name,
        b.branch_manager,
        c.primary_advisor_name                AS advisor,
        r.product_type,
        r.term_months,
        r.mortgage_balance_cad,
        r.property_value_cad,
        r.ltv_pct,
        r.insured_flag,
        r.current_rate_pct,
        r.offered_renewal_rate_pct,
        r.amortization_remaining_years,
        r.payment_shock_pct,
        r.maturity_date,
        r.days_to_maturity,
        r.renewal_stage,
        s.attrition_risk_score,
        s.attrition_risk_band,
        s.renewal_likelihood_pct,
        s.top_risk_drivers,
        s.competitor_rate_gap_bps,
        s.rate_shopping_signal,
        s.service_complaint_last_12m,
        s.annual_revenue_exposure_cad,
        s.five_year_lifetime_value_cad,
        s.model_version,
        s.recommended_offer_id,
        o.offer_name                          AS recommended_offer,
        o.max_discount_bps,
        o.cashback_cad,
        o.required_approval_level,
        CASE
            WHEN r.days_to_maturity <=  30 THEN '0-30 days'
            WHEN r.days_to_maturity <=  60 THEN '31-60 days'
            WHEN r.days_to_maturity <=  90 THEN '61-90 days'
            WHEN r.days_to_maturity <= 120 THEN '91-120 days'
            ELSE '121-180 days'
        END                                   AS maturity_bucket,
        CASE
            WHEN r.ltv_pct <  65 THEN 'Below 65'
            WHEN r.ltv_pct <= 80 THEN '65 to 80'
            ELSE 'Above 80'
        END                                   AS ltv_band,
        CASE
            WHEN r.payment_shock_pct <  25 THEN 'Below 25 pct'
            WHEN r.payment_shock_pct <= 60 THEN '25 to 60 pct'
            ELSE 'Above 60 pct'
        END                                   AS payment_shock_band
    FROM mortgage_renewals      r
    JOIN customers              c ON c.customer_id = r.customer_id
    JOIN renewal_risk_scores    s ON s.renewal_id  = r.renewal_id
    JOIN branch_performance     b ON b.branch_id   = r.branch_id
    LEFT JOIN retention_offers  o ON o.offer_id    = s.recommended_offer_id
    WHERE r.days_to_maturity BETWEEN 0 AND 180
    """
)
renewal_attrition_risk.write.mode("overwrite").option("overwriteSchema", "true") \
    .format("delta").saveAsTable("renewal_attrition_risk")
print(f"{'renewal_attrition_risk':<24} {renewal_attrition_risk.count():>4} rows")

# --------------------------------------------------------------------------- #
# Curated segment rollup - powers the "customer segments / revenue exposure"
# answer without the agent having to aggregate.
# --------------------------------------------------------------------------- #
renewal_segment_summary = spark.sql(
    """
    SELECT
        segment,
        COUNT(*)                                                        AS renewals_next_180d,
        SUM(mortgage_balance_cad)                                       AS balance_maturing_cad,
        ROUND(AVG(renewal_likelihood_pct), 1)                           AS avg_renewal_likelihood_pct,
        SUM(CASE WHEN attrition_risk_band = 'High'   THEN 1 ELSE 0 END) AS high_risk_count,
        SUM(CASE WHEN attrition_risk_band = 'Medium' THEN 1 ELSE 0 END) AS medium_risk_count,
        SUM(CASE WHEN attrition_risk_band = 'Low'    THEN 1 ELSE 0 END) AS low_risk_count,
        SUM(annual_revenue_exposure_cad)                                AS annual_revenue_exposure_cad,
        SUM(five_year_lifetime_value_cad)                               AS five_year_ltv_cad,
        ROUND(AVG(payment_shock_pct), 1)                                AS avg_payment_shock_pct,
        ROUND(AVG(competitor_rate_gap_bps), 1)                          AS avg_competitor_gap_bps,
        ROUND(AVG(ltv_pct), 1)                                          AS avg_ltv_pct
    FROM renewal_attrition_risk
    GROUP BY segment
    """
)
renewal_segment_summary.write.mode("overwrite").option("overwriteSchema", "true") \
    .format("delta").saveAsTable("renewal_segment_summary")
print(f"{'renewal_segment_summary':<24} {renewal_segment_summary.count():>4} rows")

# --------------------------------------------------------------------------- #
display(
    spark.sql(
        "SELECT * FROM renewal_segment_summary ORDER BY annual_revenue_exposure_cad DESC"
    )
)
display(
    spark.sql(
        """
        SELECT full_name, segment, branch_name, maturity_date, days_to_maturity,
               attrition_risk_score, renewal_likelihood_pct,
               annual_revenue_exposure_cad, recommended_offer, required_approval_level
        FROM renewal_attrition_risk
        WHERE attrition_risk_band = 'High'
        ORDER BY annual_revenue_exposure_cad DESC
        """
    )
)
