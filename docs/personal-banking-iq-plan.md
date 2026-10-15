# Personal Banking Intelligence - what the IQ layers offer across the business

**Status:** plan, 2026-10-02. Built so far: **Mortgage** (renewal book, customers, financial wellness, scenarios) and **Cards**. Everything is synthetic; bank names are presentation labels only.

The product lines below follow what a Canadian bank's personal-banking site leads with: everyday banking bundles, credit cards with a loyalty programme, mortgages, borrowing, registered investing, international money transfer, newcomer and student offers, and security. Each book reuses the same pattern already proven in Mortgage and Cards:

> **Governed data (Fabric IQ) → deterministic rules in code → AI that narrates, drafts and reviews → a human approves.**
> Live web (Web IQ) only adds context or a strength reading, never a number. Every client-facing draft passes the Compliance Reviewer.

## 1. What each IQ layer contributes, everywhere

| Layer | What it brings to any product book | It never... |
|---|---|---|
| **Work IQ** (mail, Teams, meetings) | Branch and contact-centre signal: complaints, escalations, manager guidance, campaign feedback. "What are advisors hearing about X?" | Overrides the system of record (RP-017) |
| **Fabric IQ** (governed semantic model) | The book itself: balances, behaviour, eligibility, consent, wellness, next-best actions, scenario sensitivities. One household key joins every book. | Gets edited by an agent |
| **Foundry IQ** (policy corpus) | What the Bank may do: suitability, consent, disclosure, approval authority, fair treatment, privacy. Cited by id. | Is paraphrased without a citation |
| **Web IQ** (public web) | Competitor offers and rates, macro releases (BoC, CPI, jobs, housing), scam alerts. Dated and sourced. | Sets a price, a limit or a scenario number (RP-015) |
| **Agents** | Concierge (Q&A across layers), Scenario Analyst (committee brief), Compliance Reviewer (gate on every draft); one specialist per book where it earns its keep | Sends, approves or contacts anyone |

The cross-book layer is the differentiator: a client who is **Vulnerable** in the mortgage book is support-first on their card, their line of credit and in investment conversations; consent recorded once applies everywhere; a payroll moving to another bank shows up in the everyday-banking book *and* as attrition risk on the mortgage.

## 2. Product books

### Mortgage (built)
Renewal book (180-day maturities, attrition, offers, approvals), Customers (household 360, next-best action, outreach and compliance review), Financial wellness (support before sales), Scenarios (rates, jobs, prices, household signals via Web IQ). Policies RP-001 to RP-018.

### Cards (built)
Tables `card_products`, `card_accounts`, `card_spend_monthly`, `card_next_actions` (60 accounts, 22 linked to mortgage clients). Plays ranked **Support → Protect → Retain → Grow**: persistent-debt support (RP-021), security check-in (RP-022), fee renewal at risk and card fit (RP-019), credit-limit increase with express consent (RP-020). Wow moment: an upgrade draft to a persistent-debt client is blocked by the reviewer and rewritten as a lower-cost-of-debt message.

### Everyday banking - chequing, savings, bundles (next, highest value)
- **Question it answers:** who is moving their day-to-day banking away, and who would be better off in a different package?
- **Fabric IQ tables:** `deposit_accounts` (package, monthly fee, waiver condition, balance), `deposit_flows_monthly` (payroll in, transfers to other institutions, bill payments, e-Transfers, NSF), `package_fit` (fees paid vs a better-fitting package), `bundle_status` (chequing + savings + card bundle offer progress).
- **Plays:** primary-banking at risk (payroll leaving, RP-018); fee-fit switch (paying fees a different package would waive); bundle completion (two of three products held - consent-gated); savings sweep for idle chequing balances; overdraft support (support-first).
- **Web IQ:** competitor package fees and bonus offers. **Work IQ:** branch complaints about fees.
- **Policies to add:** fee disclosure and package switching; overdraft protection consent; bonus-offer eligibility.
- **Wow moment:** the agent links a payroll that stopped arriving to a mortgage renewal in 60 days and proposes one relationship conversation instead of two product calls.

### Borrowing - lines of credit, personal and auto loans, home-equity plan
- **Question:** who is paying too much for credit, and who should not be offered more?
- **Fabric IQ:** `credit_lines` (secured / unsecured, limit, rate, utilisation), `loans` (auto/personal, term, rate, arrears), `consolidation_candidates` (high-rate card balances that fit inside existing equity at a lower rate).
- **Plays:** debt consolidation (cost saving shown; affordability RP-013 gated); renewal of a maturing auto loan; home-equity re-advance only below the TDS guideline; arrears support (RP-014).
- **Scenarios:** reuse the scenario engine - prime-rate shocks re-price variable credit lines exactly as BoC moves re-price variable mortgages.
- **Wow moment:** one household view shows the mortgage, the line of credit and two cards; the engine shows the interest saved by consolidating and the reviewer checks the outreach does not imply approval.

### Investing - GICs, mutual funds, TFSA / RRSP / FHSA / RESP, self-directed
- **Question:** whose savings are about to mature or sit idle, and what is suitable given their goals and risk profile?
- **Fabric IQ:** `investment_holdings` (plan type, product, value, maturity date), `contribution_room` (TFSA/RRSP/FHSA room, RESP grant eligibility), `kyc_profile` (risk tolerance, horizon, last updated), `gic_maturities` (90-day ladder).
- **Plays:** GIC maturity retention; unused FHSA for first-time-buyer households (links to the mortgage book); RESP grant left on the table for families with dependents; KYC refresh before any recommendation.
- **Foundry IQ:** suitability and KYC refresh rules, registered-plan rules, transfer-bonus conditions. **Web IQ:** posted GIC and high-interest savings rates.
- **Guardrail:** recommendations route to a licensed advisor; the agent prepares the conversation, never the trade.

### International money transfer and newcomers
- **Question:** which newcomer clients are building a full relationship, and who is sending money abroad at a cost?
- **Fabric IQ:** `transfers_out` (corridor, frequency, fees, FX margin), `newcomer_journey` (months in Canada, products opened, credit-building progress).
- **Plays:** cheaper-corridor education; credit-building next step (secured card → unsecured); newcomer mortgage readiness.
- **Web IQ:** corridor fee comparisons and scam warnings for remittances.

### Insurance (creditor, home, travel)
- Coverage gaps on mortgages and lines of credit; travel cover attached to premium cards; claims sentiment from Work IQ. Strict suitability and disclosure rules; no bundling with credit decisions.

### Security and fraud (cross-cutting)
- `fraud_alerts`, `scam_typologies`, device and login risk. Security check-ins come before any sales contact (RP-022). Web IQ brings current scam campaigns (for example, fake bank-text and investment scams) into advisor briefings. Every outreach states "we will never ask for your password or passcode".

## 3. Shared building blocks

- **Agent missions (built 2026-10-04).** Every book page, and the Mortgage "Agent mission" tab, has one mission that an API cannot do. The mission runs through a visible harness (`pb_missions.py`, `/api/missions/{book}/run`, SSE): the plan is fixed in code → a governed cross-book packet plus every book's siloed plays ("what an API returns") → `pb-mission-agent` (Fabric, Foundry, Work and Web IQ) with a per-call tool trace → deterministic guardrails over its output (figures traced to the packet or cited in Evidence, policy ids that exist, no autonomous action, client-copy rules, sales pause, verified channel) → `pb-compliance-reviewer` over any client message → a human approves, sends back or escalates (audit-logged). If a Work IQ search exceeds the 51,200-byte tool cap, the harness retries once with narrower searches. Missions: pricing exception (Mortgage), support-or-retention (Cards), quiet leavers (Everyday banking), consolidation case file (Borrowing), GIC meeting prep (Investing), next newcomer conversation (Newcomers), complaint/lapse remediation (Insurance), scam case investigation (Security).
  - **Mission data (2026-10-04).** Foundry IQ: RP-033 (AI agents in client decisions - harness, guardrails, human approval) and RP-034 (payroll/direct-deposit changes - rule out fraud before retention), via `data/foundry-iq/add_mission_policies.py` + `index_renewal_policies.py` (34 policies). Work IQ: 10 case threads in `data/work-iq/mission_emails.json` (`make_mission_emails.py`, seeded with `SEED_FILE=mission_emails.json python seed_card_mail.py`), cc'd to the demo driver and the tenant admin; Derek Fontaine also holds an Inbox copy of every seeded thread (`data/work-iq/add_persona_copies.py derek.fontaine`). Fabric IQ needed no new tables - every case is consistent with the existing book tables, and the harness warns if the agent skips a Fabric, Foundry or Work IQ call (RP-033). The gpt-5.4 deployment was raised to 600K TPM; the harness also waits and retries once on a 429.
- **Household key** across every book, so every new book gets Customer 360 for free.
- **One plays engine** (Support → Protect → Retain → Grow; blocked plays shown with reasons, never hidden) and **one compliance gate** (deterministic checks + the Compliance Reviewer agent).
- **Scenario engine** generalised: each book supplies sensitivities to the same factors (rates, jobs, prices, household signals).
- **Book specialists only where needed:** for example a `pb-investing-advisor-prep` agent that drafts a suitability-ready brief. Otherwise the Concierge plus Fabric IQ is enough.

## 4. Suggested phasing

| Phase | Deliver | Why first |
|---|---|---|
| 1 (done) | Mortgage, Cards, Scenarios, compliance gate, bank switcher | Anchor story plus the highest-volume consumer book |
| 2 | Everyday banking (primary-banking retention, package fit) | Ties every other book together; easiest data story |
| 3 | Borrowing (consolidation, home-equity re-advance) | Reuses scenarios and affordability rules directly |
| 4 | Investing (GIC maturities, FHSA/RESP gaps) | Strong household narrative; needs suitability guardrails |
| 5 | Newcomers, transfers, insurance, fraud views | Breadth; mostly reuses the same patterns |

## 5. Demo storyline additions (one chapter per book)

1. *"Who is quietly leaving us?"* - payroll redirect + mortgage renewal + card spend decline, one household.
2. *"Help, don't sell"* - a persistent-debt card client with a cheaper consolidation path; reviewer blocks the upgrade.
3. *"Money waiting to be invested"* - GIC maturities and unused FHSA room for first-time buyers in the renewal book's families.
