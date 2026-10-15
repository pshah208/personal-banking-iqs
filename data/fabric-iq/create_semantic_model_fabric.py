# Fabric notebook - build the Direct Lake semantic model for the Mortgage Renewal
# Concierge, then add business measures on top.
#
# SYNTHETIC DEMO DATA. CFC Bank is a branding label only.
#
# Run AFTER nb_load_renewals has created the Delta tables.
#   Automated:  python deploy_fabric.py --only semantic-model
#
# Direct Lake means the model reads the Delta/Parquet files in OneLake directly -
# no import, no refresh schedule, no data duplication. The measures defined here
# are what makes the model useful to Fabric IQ and to the agent: they encode the
# business definitions (revenue exposure, value at risk, the CRO's LTV and
# payment-shock splits) once, in the semantic layer, rather than in every query.
#
# The whole body is wrapped so that a full traceback is written to
# Files/_deploy/semantic_model_log.txt in the lakehouse - notebook job failures
# are otherwise opaque from the REST API.

import subprocess
import sys
import traceback

LOG: list[str] = []


def log(msg: object) -> None:
    print(msg)
    LOG.append(str(msg))


def flush_log() -> None:
    try:
        from notebookutils import mssparkutils

        mssparkutils.fs.put(
            "Files/_deploy/semantic_model_log.txt", "\n".join(LOG), True
        )
    except Exception as exc:  # noqa: BLE001
        print(f"could not write log: {exc}")


DATASET = "sm_mortgage_renewals"
LAKEHOUSE = "lh_mortgage_renewals"
FACT = "renewal_attrition_risk"

TABLES = [
    "renewal_attrition_risk",
    "renewal_segment_summary",
    "retention_offers",
    "branch_performance",
    "households",
    "credit_capacity",
    "customer_products",
    "financial_signals_monthly",
    "life_events",
    "consent_preferences",
    "financial_wellness",
    "next_best_actions",
    "rate_scenario_presets",
    "renewal_scenario_sensitivity",
    "card_products",
    "card_accounts",
    "card_spend_monthly",
    "card_next_actions",
    "deposit_accounts",
    "deposit_flows_monthly",
    "banking_next_actions",
    "credit_facilities",
    "debt_consolidation_candidates",
    "borrowing_next_actions",
    "investment_accounts",
    "registered_room",
    "investing_next_actions",
    "newcomer_journey",
    "transfers_out_monthly",
    "newcomers_next_actions",
    "insurance_policies",
    "coverage_gaps",
    "insurance_next_actions",
    "security_events",
    "customer_security_posture",
    "security_next_actions",
]

try:
    # ----------------------------------------------------------------------- #
    # 0. Dependency. Installed via subprocess rather than the %pip magic so the
    #    failure is catchable and lands in the log.
    # ----------------------------------------------------------------------- #
    try:
        import sempy_labs  # noqa: F401
        log("semantic-link-labs already present")
    except ImportError:
        log("installing semantic-link-labs…")
        out = subprocess.run(
            [sys.executable, "-m", "pip", "install", "semantic-link-labs"],
            capture_output=True, text=True,
        )
        log(out.stdout[-3000:])
        if out.returncode != 0:
            log(out.stderr[-4000:])
            raise RuntimeError("pip install semantic-link-labs failed")

    import sempy_labs as labs
    from sempy_labs.tom import connect_semantic_model

    log(f"sempy_labs {getattr(labs, '__version__', 'unknown')}")

    # ----------------------------------------------------------------------- #
    # 1. Generate the Direct Lake model over the curated tables.
    #    The signature of generate_direct_lake_semantic_model has changed across
    #    releases (0.17 requires both `tables` and `source`; earlier builds used
    #    `lakehouse` / `lakehouse_tables`). Introspect it and bind by alias rather
    #    than hard-coding, so this survives a library upgrade.
    # ----------------------------------------------------------------------- #
    import inspect

    gen = labs.directlake.generate_direct_lake_semantic_model
    sig = inspect.signature(gen)
    log(f"signature: generate_direct_lake_semantic_model{sig}")

    ALIASES = {
        "dataset": DATASET,
        "semantic_model": DATASET,
        "tables": TABLES,
        "lakehouse_tables": TABLES,
        "source": LAKEHOUSE,
        "lakehouse": LAKEHOUSE,
        "source_type": "Lakehouse",
        "overwrite": True,
        "refresh": True,
    }
    kwargs = {name: ALIASES[name] for name in sig.parameters if name in ALIASES}

    missing = [
        n for n, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        and n not in kwargs
    ]
    if missing:
        raise RuntimeError(f"unmapped required parameters {missing} - signature: {sig}")

    log(f"calling with: { {k: (v if not isinstance(v, list) else f'{len(v)} tables') for k, v in kwargs.items()} }")
    gen(**kwargs)
    log(f"semantic model '{DATASET}' generated")

    # --------------------------------------------------------------------------- #
    # 2. Relationships + measures.
    # --------------------------------------------------------------------------- #
    MEASURES = [
        # (name, DAX, format string, description)
        ("Renewals in 180 Days",
         f"COUNTROWS('{FACT}')", "#,0",
         "Count of mortgages maturing within the next 180 days."),

        ("Balance Maturing",
         f"SUM('{FACT}'[mortgage_balance_cad])", '"CAD "#,0',
         "Total mortgage balance maturing in the window."),

        ("Annual Revenue Exposure",
         f"SUM('{FACT}'[annual_revenue_exposure_cad])", '"CAD "#,0',
         "Annual net interest plus ancillary margin at risk if these renewals are lost."),

        ("Five Year Lifetime Value",
         f"SUM('{FACT}'[five_year_lifetime_value_cad])", '"CAD "#,0',
         "Modelled five-year relationship value of the maturing book."),

        ("Avg Renewal Likelihood Pct",
         f"AVERAGE('{FACT}'[renewal_likelihood_pct])", "0.0",
         "Average modelled probability the client renews with us."),

        ("High Risk Renewals",
         f"CALCULATE(COUNTROWS('{FACT}'), '{FACT}'[attrition_risk_band] = \"High\")", "#,0",
         "Renewals scored in the High attrition band."),

        ("High Risk Exposure",
         f"CALCULATE(SUM('{FACT}'[annual_revenue_exposure_cad]), "
         f"'{FACT}'[attrition_risk_band] = \"High\")", '"CAD "#,0',
         "Annual revenue exposure concentrated in High-risk renewals."),

        ("Value at Risk",
         f"SUMX('{FACT}', '{FACT}'[annual_revenue_exposure_cad] * "
         f"'{FACT}'[attrition_risk_score])", '"CAD "#,0',
         "Probability-weighted revenue exposure. This is the measure advisor worklists "
         "should be sorted by - see the 20 July Renewal Council decision."),

        ("Pct Balance At High Risk",
         f"DIVIDE(CALCULATE(SUM('{FACT}'[mortgage_balance_cad]), "
         f"'{FACT}'[attrition_risk_band] = \"High\"), SUM('{FACT}'[mortgage_balance_cad]))",
         "0.0%",
         "Share of maturing balance sitting in the High attrition band."),

        ("Avg Payment Shock Pct",
         f"AVERAGE('{FACT}'[payment_shock_pct])", "0.0",
         "Average increase in monthly payment at renewal."),

        ("Avg Competitor Gap Bps",
         f"AVERAGE('{FACT}'[competitor_rate_gap_bps])", "0.0",
         "Average gap in basis points between our offer and the best competitor quote."),

        ("Avg LTV Pct",
         f"AVERAGE('{FACT}'[ltv_pct])", "0.0",
         "Average loan-to-value of the maturing book."),

        ("Rate Shopping Signals",
         f"CALCULATE(COUNTROWS('{FACT}'), '{FACT}'[rate_shopping_signal] = \"Y\")", "#,0",
         "Renewals where a rate-shopping behavioural signal was detected."),

        ("Balance Above 80 LTV",
         f"CALCULATE(SUM('{FACT}'[mortgage_balance_cad]), '{FACT}'[ltv_band] = \"Above 80\")",
         '"CAD "#,0',
         "Maturing balance above 80 percent LTV - required by the CRO monthly pack (RP-009)."),

        ("Balance Above 60 Pct Payment Shock",
         f"CALCULATE(SUM('{FACT}'[mortgage_balance_cad]), "
         f"'{FACT}'[payment_shock_band] = \"Above 60 pct\")", '"CAD "#,0',
         "Maturing balance facing a payment increase above 60 percent - required by the "
         "CRO monthly pack (RP-009)."),
        # --- Personal banking: wellness, affordability, consent ---------------- #
        ("Vulnerable Clients",
         "CALCULATE(COUNTROWS(financial_wellness), financial_wellness[vulnerability_flag] = \"Y\")", "0",
         "Clients in the Vulnerable wellness band - support-first, sales suppressed (RP-012)."),
        ("Avg Wellness Score", "AVERAGE(financial_wellness[wellness_score])", "0.0",
         "Average financial-wellness score (0-100, higher is healthier)."),
        ("Renewals Above TDS Guideline",
         "CALCULATE(COUNTROWS(credit_capacity), credit_capacity[tds_renewal_pct] > 44)", "0",
         "Renewals whose TDS on the renewal payment exceeds the 44% guideline (RP-013)."),
        ("Clients With Deposit Flight",
         "CALCULATE(COUNTROWS(financial_wellness), financial_wellness[competitor_outflow_share_pct] >= 10)", "0",
         "Clients moving 10%+ of payroll to another institution (RP-018)."),
        ("Email Marketing Consent Pct",
         "DIVIDE(CALCULATE(COUNTROWS(consent_preferences), consent_preferences[channel] = \"Email\", consent_preferences[consent_status] = \"Granted\"), CALCULATE(COUNTROWS(consent_preferences), consent_preferences[channel] = \"Email\")) * 100", "0.0",
         "Share of clients with Granted email marketing consent (RP-011)."),
        # --- Cards book ------------------------------------------------------- #
        ("Card Balances", "SUM(card_accounts[balance])", "#,0", "Outstanding card balances (CAD)."),
        ("Card Utilization Pct", "DIVIDE(SUM(card_accounts[balance]), SUM(card_accounts[credit_limit])) * 100", "0.0",
         "Balances as a share of credit limits."),
        ("Card Spend 12m", "SUM(card_spend_monthly[spend])", "#,0", "Card purchase volume over the last 12 months (CAD)."),
        ("Persistent Debt Accounts",
         "CALCULATE(COUNTROWS(card_accounts), card_accounts[behaviour] = \"Persistent debt\")", "0",
         "Accounts at or near minimum payment for 6+ of 12 months - support first (RP-021)."),
        ("Card Plays Blocked",
         "CALCULATE(COUNTROWS(card_next_actions), card_next_actions[eligibility] <> \"Eligible\")", "0",
         "Card plays blocked by consent, suitability, express-consent or support-first rules."),
        # --- Product books: Everyday banking, Borrowing, Investing ------------ #
        ("Deposit Balances",
         "SUM(deposit_accounts[avg_chequing_balance]) + SUM(deposit_accounts[savings_balance])", "#,0",
         "Average chequing plus savings balances across everyday-banking clients (CAD)."),
        ("Primary Banking At Risk",
         "CALCULATE(COUNTROWS(banking_next_actions), banking_next_actions[play] = \"Primary banking at risk\")", "0",
         "Clients with 10%+ of payroll moving out 2 months running, or payroll falling (RP-018)."),
        ("Package Fee Savings Available",
         "SUMX(FILTER(deposit_accounts, deposit_accounts[best_fit_package] <> deposit_accounts[package] && "
         "deposit_accounts[package_cost_12m] - deposit_accounts[best_fit_cost_12m] >= 120), "
         "deposit_accounts[package_cost_12m] - deposit_accounts[best_fit_cost_12m])", "#,0",
         "Annual fees overpaying clients (saving of $120+/yr) would save on the lowest-cost package for their usage (RP-023)."),
        ("Consolidation Interest Saved",
         "SUM(debt_consolidation_candidates[interest_saved_annual_cad])", "#,0",
         "Annual interest clients would save moving card balances to a cheaper facility, before gates (RP-025)."),
        ("Variable Rate Balances",
         "CALCULATE(SUM(credit_facilities[balance_cad]), credit_facilities[rate_type] = \"Variable\")", "#,0",
         "Line balances priced off prime - each needs a rate-change notice within 30 days (RP-026)."),
        ("GICs Maturing 90d",
         "CALCULATE(SUM(investment_accounts[market_value_cad]), investment_accounts[holding_type] = \"GIC\", "
         "investment_accounts[days_to_maturity] <= 90, NOT ISBLANK(investment_accounts[days_to_maturity]))", "#,0",
         "GIC value maturing in the next 90 days (CAD)."),
        ("RESP Grant Missed",
         "SUM(registered_room[cesg_missed_per_year_cad])", "#,0",
         "Canada Education Savings Grant not collected per year by families with no RESP (RP-028)."),
        ("Book Plays Blocked",
         "CALCULATE(COUNTROWS(banking_next_actions), banking_next_actions[eligibility] <> \"Eligible\") + "
         "CALCULATE(COUNTROWS(borrowing_next_actions), borrowing_next_actions[eligibility] <> \"Eligible\") + "
         "CALCULATE(COUNTROWS(investing_next_actions), investing_next_actions[eligibility] <> \"Eligible\")", "0",
         "Banking, borrowing and investing plays blocked by consent, support-first, affordability, LTV or KYC rules."),
        # --- Product books: Newcomers, Insurance, Security -------------------- #
        ("Newcomer Packages Expiring 60d",
         "CALCULATE(COUNTROWS(newcomer_journey), newcomer_journey[newcomer_package_active] = \"Y\", "
         "newcomer_journey[days_to_package_expiry] <= 60)", "0",
         "Newcomer fee-free periods ending within 60 days - explain the next package (RP-029)."),
        ("Transfer Cost 12m",
         "SUM(transfers_out_monthly[total_cost_cad])", "#,0",
         "What clients paid to send money abroad: fees plus FX margin (RP-030)."),
        ("Transfer Saving Available",
         "SUMX(FILTER(newcomer_journey, newcomer_journey[transfer_provider] = \"Other provider\"), "
         "newcomer_journey[transfer_cost_12m_cad] - newcomer_journey[bank_equivalent_cost_12m_cad])", "#,0",
         "Annual saving for clients using another provider at the Bank's fee and FX margin (RP-030)."),
        ("Life Cover Gap",
         "SUMX(FILTER(coverage_gaps, coverage_gaps[linked_mortgage] = \"Y\" && coverage_gaps[dependents] > 0), coverage_gaps[gap_amount_cad])", "#,0",
         "Mortgage balance not covered by mortgage life insurance for families with dependents (RP-031)."),
        ("Optional Premiums Monthly",
         "SUM(coverage_gaps[optional_premiums_monthly_cad])", "#,0.00",
         "Monthly optional creditor-insurance premiums (mortgage life / disability, line and card protection)."),
        ("Lapsed Policies 90d",
         "CALCULATE(COUNTROWS(insurance_policies), insurance_policies[status] = \"Lapsed\", insurance_policies[days_since_lapse] <= 90)", "0",
         "Policies lapsed in the last 90 days - confirm the lapse was intended (RP-031)."),
        ("Open Security Events",
         "CALCULATE(COUNTROWS(security_events), security_events[status] = \"Open\")", "0",
         "Open security events - sales are paused for these clients (RP-032)."),
        ("Clients Without 2-Step",
         "CALCULATE(COUNTROWS(customer_security_posture), customer_security_posture[two_step_verification] = \"N\")", "0",
         "Clients with a security event and no 2-step verification (RP-022)."),
        ("Security Amount At Risk",
         "SUM(customer_security_posture[amount_at_risk_cad])", "#,0",
         "Disputed or held amounts in open security events (CAD)."),
    ]

    with connect_semantic_model(dataset=DATASET, readonly=False) as tom:
        for from_table, from_col, to_table, to_col in (
            (FACT, "recommended_offer_id", "retention_offers", "offer_id"),
            (FACT, "branch_id", "branch_performance", "branch_id"),
            # Personal-banking tables hang off the renewal fact by customer.
            ("households", "primary_customer_id", FACT, "customer_id"),
            ("credit_capacity", "customer_id", FACT, "customer_id"),
            ("customer_products", "customer_id", FACT, "customer_id"),
            ("financial_signals_monthly", "customer_id", FACT, "customer_id"),
            ("life_events", "customer_id", FACT, "customer_id"),
            ("consent_preferences", "customer_id", FACT, "customer_id"),
            ("financial_wellness", "customer_id", FACT, "customer_id"),
            ("next_best_actions", "customer_id", FACT, "customer_id"),
            ("renewal_scenario_sensitivity", "customer_id", FACT, "customer_id"),
            # Cards book: its own star (card-only clients have no renewal).
            ("card_spend_monthly", "account_id", "card_accounts", "account_id"),
            ("card_next_actions", "account_id", "card_accounts", "account_id"),
            ("card_accounts", "product_id", "card_products", "product_id"),
            # Product books: each its own star keyed by account_id. Accounts carry
            # customer_id but are NOT related to the renewal fact (card-only clients
            # CUST-20xx have no renewal).
            ("deposit_flows_monthly", "account_id", "deposit_accounts", "account_id"),
            ("banking_next_actions", "account_id", "deposit_accounts", "account_id"),
            ("borrowing_next_actions", "account_id", "credit_facilities", "account_id"),
            ("debt_consolidation_candidates", "attach_account_id", "credit_facilities", "account_id"),
            ("investing_next_actions", "account_id", "investment_accounts", "account_id"),
            ("investment_accounts", "customer_id", "registered_room", "customer_id"),
            ("transfers_out_monthly", "account_id", "newcomer_journey", "account_id"),
            ("newcomers_next_actions", "account_id", "newcomer_journey", "account_id"),
            ("insurance_policies", "customer_id", "coverage_gaps", "customer_id"),
            ("insurance_next_actions", "account_id", "coverage_gaps", "account_id"),
            ("security_events", "customer_id", "customer_security_posture", "customer_id"),
            ("security_next_actions", "account_id", "customer_security_posture", "account_id"),
        ):
            try:
                tom.add_relationship(
                    from_table=from_table, from_column=from_col,
                    to_table=to_table, to_column=to_col,
                    from_cardinality="Many", to_cardinality="One",
                    cross_filtering_behavior="OneDirection", is_active=True,
                )
                log(f"+ relationship {from_table} -> {to_table}")
            except Exception as exc:  # noqa: BLE001
                log(f"= relationship {to_table} skipped: {exc}")

        existing = {m.Name for m in tom.all_measures()}
        for name, dax, fmt, desc in MEASURES:
            if name in existing:
                log(f"= measure {name}")
                continue
            tom.add_measure(table_name=FACT, measure_name=name, expression=dax,
                            format_string=fmt, description=desc)
            log(f"+ measure {name}")

        tom.model.Description = (
            "SYNTHETIC DEMO DATA - Mortgage Renewal Concierge. Direct Lake model over "
            "the 180-day renewal book. CFC Bank is a branding label only; nothing "
            "here reflects real CFC Bank customers, pricing or policy."
        )

    log(f"semantic model '{DATASET}' ready with {len(MEASURES)} measures")
    log("STATUS: SUCCESS")

except Exception:  # noqa: BLE001
    log("STATUS: FAILED")
    log(traceback.format_exc())
    flush_log()
    raise
else:
    flush_log()
