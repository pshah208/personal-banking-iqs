# A day in the life of Derek Fontaine

**Personal Banking IQ: how agents multiply productivity across eight product books**

*Personal-banking app in rg-scotia-iqs · Product books: Mortgage, Cards, Everyday banking, Borrowing, Investing, Newcomers & transfers, Insurance, Security & fraud*

> Everything is synthetic demo data and the firm is always "the Bank". Client names, figures, policy ids (RP-001 to RP-034) and colleague threads come from the governed data the app already serves (Fabric IQ tables, Foundry IQ policies, Work IQ mail seeded into Derek's inbox, Web IQ live search). Times saved are illustrative talk-track estimates, not measured results. Moments tagged "Live" run in the app today. Moments tagged "Extension" are built from the same harness and agents but are not yet built.

---

## The hero

Derek Fontaine is Director, Mortgage Pricing. Work IQ knows him as the person who asks for "evidence, not anecdote" and who warned the Renewal Council that 41 pricing exceptions in a quarter are an undocumented grid change.

For this storyline Diane Lafleur (EVP, Personal Banking) has made Derek the executive sponsor of the household-first pilot. His job for the day is to work every product book with its agents, then hand each decision to the right human owner. He doesn't do the advisors' work. He checks that every book makes one decision per household, not eight product calls.

The day is Monday 3 August 2026, the as-of date of the data. Derek's inbox holds a copy of every case thread the branches sent last week.

## The agent cast

| Agent | What it does for Derek | What it never does |
|---|---|---|
| **Concierge (mortgage-renewal-concierge)** | Answers questions across Fabric, Foundry, Work and Web IQ, and checks a colleague's claim against the governed data | Edits data |
| **Mission Agent (pb-mission-agent)** | Takes one client case per book: reads colleague mail, interprets policy, adds dated market context, reconciles plays that disagree, and ends with one decision | Sends, approves, declines, freezes or contacts anyone |
| **Compliance Reviewer (pb-compliance-reviewer)** | Reviews every client draft: PASS, NEEDS FIXES or BLOCKED, with findings and a corrected draft | Approves a send |
| **Scenario Analyst (pb-scenario-analyst)** | Turns a rate, jobs or competitor scenario into a Risk Committee brief | Sets prices or declines renewals |
| **Deterministic checks (code)** | Consent (RP-011), vulnerability (RP-012), affordability (RP-013) and prohibited words (RP-016), run before any agent sees a draft | Gets overruled by an agent |

**Every mission runs through the same visible harness:**

1. Plan: the steps are fixed in code.
2. Packet: governed cross-book facts plus every book's siloed plays, which is what an API would return.
3. Agent: live tool calls, traced one by one.
4. Guardrails: every figure is traced, every policy id is valid, no autonomous action, sales pause where they should, and contact only through a verified channel.
5. Compliance review of any client message.
6. Human decision: approve, send back or escalate. Every decision is audit-logged.

## Derek's day at a glance

| Time | Product book | Hero case | Agent moments |
|---|---|---|---|
| 07:30 – 08:45 | Mortgage | Josephine Novak | 8 agent moments (7 live, 1 extension) |
| 08:45 – 09:45 | Cards | Sana Moreau | 8 agent moments (7 live, 1 extension) |
| 09:45 – 10:45 | Everyday banking | Tariq Marchetti | 8 agent moments (7 live, 1 extension) |
| 10:45 – 11:45 | Borrowing | Nikhil Petrov | 8 agent moments (6 live, 2 extension) |
| 11:45 – 12:45 | Investing | Simone Fitzgerald | 8 agent moments (7 live, 1 extension) |
| 13:30 – 14:30 | Newcomers & transfers | Joseph Mendoza | 8 agent moments (7 live, 1 extension) |
| 14:30 – 15:30 | Insurance | Henrik Thibault | 8 agent moments (7 live, 1 extension) |
| 15:30 – 16:30 | Security & fraud | Farah Leclair | 8 agent moments (7 live, 1 extension) |

---

## 07:30 – 08:45 · Mortgage: "The exception I approved myself"

*Renewal book, customers and wellness*

**Book at a glance (Fabric IQ):** 50 households · $26.4M renewing balance · 8 Vulnerable and 11 Stretched households · 13 above the 44% TDS guideline at renewal · 7 in the deposit-flight cohort · 57 eligible Retain plays, 82 Deepen, 8 Support · 22 plays blocked for consent and 16 for vulnerability

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 07:30 | **Morning brief** | Concierge · Fabric + Work IQ | Derek asks: "What changed in my renewal book since Friday and what needs me today?" He gets a ranked list: the RNW-5014 exception conditions, the Québec grid paper due 10 August and the 13 renewals above the TDS guideline, each linked to its source. | 🟢 Live |
| 07:38 | **Verify before trusting** | Concierge · Work + Fabric IQ | Nadia Osei told the branch leaders that self-employed Calgary clients face 70–130% payment increases. Fabric IQ shows BR-303 self-employed: 5 files, $3,028,000, payment shock of 45.6% to 154.7%. The direction is right, but the real range is wider at both ends. Derek corrects the record before it reaches Council. | 🟢 Live |
| 07:45 | **Pricing-exception mission** | Mission Agent · all four IQs | Hero case below: Josephine Novak, RNW-5014. | 🟢 Live |
| 08:05 | **Competitor price-war scenario** | Scenario Analyst · Fabric + Foundry IQ | Derek runs the "Competitor price war" preset. The engine shows payment shock, GDS/TDS and which renewals flip from retention to support-first. The analyst writes a Risk Committee brief citing RP-013 and RP-015, with renewal ids only and no client names. | 🟢 Live |
| 08:15 | **Household signals** | Web IQ · Scenarios | Today's rate decision, bond yields and lender promotions arrive as dated headlines. They give the scenario context but never add a number to it. | 🟢 Live |
| 08:20 | **Support-first sweep** | Financial wellness · Compliance Reviewer | For the 8 Vulnerable households, the 16 suppressed Deepen plays stay suppressed. Derek opens Sana Moreau's relief-review draft. The checks and the reviewer strip any product language before it can be saved. | 🟢 Live |
| 08:30 | **Conversation note and Outlook draft** | Customer workspace | For Wei Zhang's call with Josephine he exports a Word conversation note and saves the reviewed message to his own Outlook Drafts, with no recipient and nothing sent. | 🟢 Live |
| 08:40 | **Council evidence pack** | Mission Agent + Scenario Analyst | The agent assembles the Québec regional grid recommendation from Sophie Tremblay's competitor sheets, the BR-202 exception log and the price-war brief, and drafts "a recommendation, not options" for 10 August. | 🔷 Extension |

### Hero case: Josephine Novak · RNW-5014 · Montréal Plateau (BR-202) · 11-year client

**Mission:** Pricing exception: match, partly match, or support?

**Situation.** Josephine's $612,000 five-year fixed renews on 13 September, 41 days away. It moves from 2.19% to the 4.94% floor, so her payment goes from $2,503 to $5,646, a 125.6% shock. She holds a written competitor offer at 4.62%, a 32 bps gap. Attrition is High (0.68) and renewal likelihood is 32%.

**Without agents.** The API offers "Retain — mortgage" and a templated retention email. The system of record doesn't show that Derek ruled on this file himself three weeks ago.

**With agents.**

1. Work IQ, searched narrowly by name and then by RNW-5014, finds Wei Zhang's 13 July request and Derek's own 14 July ruling: approved at 28 bps, not 32. The conditions were a PDF of the competitor offer, chequing kept as the primary payment account, and the exception logged in the quarterly report to Risk. It was the sixth BR-202 exception of the quarter.
2. Fabric IQ confirms this is a pricing case, not hardship: TDS at renewal is 35.7% and wellness is Thriving (93).
3. Foundry IQ applies the evidence standard. The committee's screenshot ruling allows up to 15 bps on a screenshot, so 28 bps needs the PDF.
4. Web IQ adds this month's posted 5-year fixed rates, dated and for the advisor only.
5. Output: a committee-ready memo and talking points. The client message goes by SMS, the channel she consented to, and promises no unapproved rate. Reviewer: PASS.

**Derek's decision.** Derek approves with a note: "Condition 1 is outstanding. No rate is confirmed to the client until the PDF is on file."

**Productivity win.** He has the history of his own decision back in minutes. The pattern across six exceptions becomes his argument for a Québec grid.

### Productivity ledger

- **Agent moments:** 8 agent moments (7 live, 1 extension)
- **Mistakes avoided:** One rate confirmed without the required evidence; one unverified claim headed for Council
- **Time back (illustrative):** About 3 hours of searching, cross-checking and drafting cut to about 75 minutes

---

## 08:45 – 09:45 · Cards: "The table says email. The branch says phone only."

*Card portfolio, spend and fit*

**Book at a glance (Fabric IQ):** 60 accounts (22 linked to a mortgage) · $289,300 in balances · 13 persistent-debt accounts · 10 fraud alerts · 15 fees renewing within 60 days · monthly spend down from $180,990 (Sep 2025) to $170,010 (Aug 2026) · credit-limit increase: 4 eligible, 10 blocked

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 08:45 | **Blocked-play explainer** | Concierge · Fabric + Foundry IQ | "Why are 10 limit increases blocked?" Express consent isn't recorded (RP-020). Work IQ adds that the summer campaign was paused after pre-filled consent wording turned up in two branch scripts. | 🟢 Live |
| 08:52 | **Competitor watch** | Web IQ · Cards market | Live competitor card offers come in, dated and for internal context. Work IQ links them to a colleague's warning about 50,000-point welcome bonuses and 6 transactor accounts whose spend fell by more than a third. | 🟢 Live |
| 09:00 | **Support-or-retention mission** | Mission Agent · all four IQs | Hero case below: Sana Moreau, CA-1049. | 🟢 Live |
| 09:15 | **Persistent-debt cohort** | Draft + checks + Compliance Reviewer | Derek opens three of the 13 persistent-debt accounts. On one, an upgrade draft is BLOCKED and rewritten as a lower-cost-of-debt message (RP-021). Account by account is live; a batch pass over all 13 is an extension. | 🟢 Live |
| 09:22 | **Cross-book stress list** | Concierge · Work + Fabric IQ | The July risk pack named CA-1025, CA-1034, CA-1044 and CA-1049 at 98% utilisation. The agent joins them to renewal dates and TDS, giving one support-first household list for the mortgage team. | 🟢 Live |
| 09:28 | **Fee-waiver question** | Concierge · Work + Foundry IQ | Branches ask whether advisors can waive Gold Rewards fees. The agent answers from RP-019 (card fit and fee renewal) and compares points earned with the fee. If the card doesn't fit, it recommends the better card instead of a waiver. | 🟢 Live |
| 09:34 | **Travel fit, consent-aware** | Draft · Compliance Reviewer | Frequent travellers pay a 2.5% FX fee on the wrong card. Two of them withdrew email marketing consent, so the agent writes phone talking points for them and an email only where consent exists. | 🟢 Live |
| 09:40 | **Script audit** | Compliance Reviewer | Every branch CLI script runs through the reviewer, which flags pre-ticked or implied consent before the campaign restarts. | 🔷 Extension |

### Hero case: Sana Moreau · CA-1049 · Bay & Bloor · 14-year client

**Mission:** Support or retention? One answer for the household

**Situation.** Sana's Low-Rate Card is at 98% of an $11,800 limit. She has paid only the minimum in 12 of the last 12 months and is 30 days past due. Her variable mortgage (RNW-5049) renews on 2 December, and her payment goes from $1,238 to $2,987 (+141%), taking TDS to 58.1%. She has had 20 overdraft days and 2 NSF items in three months, and an advisor noted a separation in June. Wellness: Vulnerable (46).

**Without agents.** Ten plays across six books, including Mortgage Retain, and Fabric IQ shows email consent "Granted".

**With agents.**

1. The agent notices the books disagree: the mortgage model still says Retain while every other book says support.
2. Work IQ finds Priya Raghavan's note: "Phone only — her partner reads her email." Sana had also asked about skipping a payment.
3. Policy decides it: RP-012 support before sales, RP-021 persistent-debt support, RP-006 amortization relief and RP-014 hardship. No upgrade and no limit increase.
4. Minimum-payment cost and the renewal shock are shown side by side, and she is routed to Client Assistance.
5. Client message: NONE — phone only. The guardrails accept it, and a call plan goes to Priya.

**Derek's decision.** Derek approves and adds Sana to Thursday's huddle.

**Productivity win.** Ten plays become one support plan, and an email that would have reached the wrong reader is never drafted.

### Productivity ledger

- **Agent moments:** 8 agent moments (7 live, 1 extension)
- **Mistakes avoided:** An email sent to a shared inbox; an upgrade pitched to a persistent-debt client; a limit increase without consent
- **Time back (illustrative):** About 2.5 hours cut to about 60 minutes

---

## 09:45 – 10:45 · Everyday banking: "Quietly leaving, or just a new job?"

*Packages, fees and deposit flows*

**Book at a glance (Fabric IQ):** 88 clients · $1.45M in deposits · 86.4% primary banking · 13 at risk, 7 in the deposit-flight cohort · $13,905 in fees over 12 months · 14 NSF/overdraft clients · $3,804 a year of fee savings available on a better-fitting package

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 09:45 | **Leaver radar** | Concierge · Fabric IQ | "Who in the flight cohort also renews within 60 days?" The agent joins the 7 deposit-flight clients to the mortgage book and ranks them by payroll share, days to renewal, card behaviour and any open case. | 🟢 Live |
| 09:52 | **Fraud before retention** | Mission Agent · Security + Work IQ | Under RP-034, a payroll or deposit redirect is screened for fraud first. Clara Thibault (RNW-5040) is on the list for "Retain — match 30 bps", but she told the branch she doesn't recognise a new-device login. The retention call is held. | 🟢 Live |
| 10:00 | **Quiet-leaver mission** | Mission Agent · all four IQs | Hero case below: Tariq Marchetti, DA-1044. | 🟢 Live |
| 10:15 | **Fee-fit sweep** | Draft + Compliance Reviewer | $3,804 a year in savings is sitting in the book. The agent drafts package-fit notes that recommend the cheaper package even though fee revenue falls (RP-023). Work IQ shows leadership has already backed that stance. | 🟢 Live |
| 10:22 | **NSF and overdraft support** | Draft · checks | Support-first notes go to the 14 NSF/overdraft clients (RP-024). The deterministic checks remove every product promotion before review. | 🟢 Live |
| 10:28 | **Switching-bonus context** | Web IQ · IQ strip | Current bank switching bonuses and chequing package offers, dated and issuer-neutral. They help the advisor prepare but are never quoted to a client. | 🟢 Live |
| 10:33 | **Branch voice** | Work IQ | A summary of fee complaints and "leaving" signals from branch mail and Teams, with sources, that no table holds. | 🟢 Live |
| 10:40 | **Consent capture queue** | Concierge + workflow | For bundle-completion plays blocked by RP-011, the agent queues a consent question for the client's next service interaction. It never sends marketing. | 🔷 Extension |

### Hero case: Tariq Marchetti · DA-1044 · Montréal Plateau · 13-year client

**Mission:** Who is quietly leaving us, and what one conversation keeps them?

**Situation.** 16.4% of Tariq's payroll now goes to another institution: $3,040, $3,610, then $3,860 from June to August. His mortgage (RNW-5044) renews on 29 August, 26 days away, and his payment goes from $3,346 to $6,969 (+108%). There's a 41 bps competitor gap and attrition is 0.82 (High). His Low-Rate Card is at 98% of $40,000, and Basic would cost him $84 a year less than his Preferred package.

**Without agents.** Eight siloed plays: two Mortgage Retain, Card Support, Primary-banking Retain, Bundle Grow, Consolidation and a Premium review. That could mean three messages in one week.

**With agents.**

1. RP-034 check: no new device, contact change or new payee. Not fraud.
2. Work IQ finds Sophie Tremblay's mail. Tariq has a new job and his employer pays part of his salary into its own bank. "He is not unhappy with us." She asks for one conversation, support first, with nothing conditional on payroll.
3. The deposit flow, the renewal in 26 days, the maxed card and his April marriage become one household explanation.
4. Package fit under RP-023: recommend Basic.
5. Output: one consolidated outreach. The reviewer removes "keep your pay with us" as an implied condition: NEEDS FIXES, with a corrected draft.

**Derek's decision.** Derek approves the corrected draft for Camille Fortin and holds every retention campaign until after the conversation.

**Productivity win.** Eight plays become one conversation. The Bank avoids a false "leaver" alarm and doesn't push harder on a stretched client.

### Productivity ledger

- **Agent moments:** 8 agent moments (7 live, 1 extension)
- **Mistakes avoided:** A retention call during a possible account takeover; three overlapping emails; a fee-heavy package left in place
- **Time back (illustrative):** About 2.5 hours cut to about 60 minutes

---

## 10:45 – 11:45 · Borrowing: "The numbers work. The timing doesn't."

*Lines, loans and consolidation*

**Book at a glance (Fabric IQ):** 93 facilities across 64 clients · $1.35M outstanding · $741,610 variable, priced off prime at 4.95% · a 25 bp move is about $155 a month across the book · 5 past due · 20 consolidation candidates · $16,447 a year of interest saved before any gate · 7 auto loans maturing within 90 days

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 10:45 | **Campaign pre-flight** | Mission Agent · Fabric + Security | Before the 4 August lending batch goes out, every queued name is screened for open fraud cases, missing consent, Vulnerable status and TDS above 44%. The agent produces a list of names to pull, with reasons. | 🔷 Extension |
| 10:52 | **Gate the headline** | Concierge · Fabric IQ | "How much of the $16,447 survives the gates?" The agent separates Offer from Support treatment and shows which candidates are blocked by RP-013 and which are paused by RP-032. | 🟢 Live |
| 11:00 | **Consolidation mission** | Mission Agent · all four IQs | Hero case below: Nikhil Petrov. | 🟢 Live |
| 11:15 | **Refer, don't sell** | Mission Agent | Henrik Thibault is above the TDS guideline (44.8%) and renews in 75 days. Callum Singh is Vulnerable and recently had a bank-investigator scam attempt. Both go to Client Assistance, not a credit offer. | 🟢 Live |
| 11:22 | **Prime-rate readiness** | Web IQ + Draft | Web IQ brings the Bank of Canada's latest decision and prime rate, dated. The agent pre-drafts RP-026 notices with each client's new payment as service messages with no cross-sell, to go out within 30 days of a move. | 🟢 Live |
| 11:30 | **Arrears support** | Draft · Compliance Reviewer | The 5 past-due clients get hardship options (RP-014) in plain language. The reviewer blocks any wording that implies approval. | 🟢 Live |
| 11:36 | **Auto loans maturing** | Concierge · Fabric IQ | For the 7 auto loans maturing within 90 days, the agent prepares conversations with the affordability check done first. | 🟢 Live |
| 11:40 | **Prime-shock scenario** | Scenario Analyst | The renewal scenario engine is reused for variable lines: a prime shock re-prices each line and the agent flags which households cross the TDS guideline. | 🔷 Extension |

### Hero case: Nikhil Petrov · LN-5021 · Calgary Centre Street

**Mission:** Consolidation case file: help, hold or refer?

**Situation.** The engine says Offer. Moving his $1,670 card balance from 19.99% to his existing line at 11.1% saves $148 a year and lowers the payment from $50.10 to $43.24, and TDS is within the guideline. The 4 August campaign batch has already queued the email.

**Without agents.** The email goes out tomorrow during an open card fraud dispute (SE-9009, High), to a client whose email marketing consent was never captured.

**With agents.**

1. The agent sees what the candidate table can't: an open fraud case, three alerts in 90 days, no 2-step verification and no alerts.
2. Work IQ finds Nadia Osei's mail: "Pull him from the batch. No offers in any book while a security case is open."
3. Policy: RP-032 security before sales, RP-011 consent before marketing, RP-026 prime notices are service-only.
4. Decision: HOLD. The case file shows both paths for when the case closes, as a conversation, not a campaign.
5. Client message: NONE — open fraud case; no marketing consent.

**Derek's decision.** Derek escalates to Credit: "Remove from the 4 August batch." A human makes that change, not the agent.

**Productivity win.** A batch-day mistake is caught a day early, and the same check, run book-wide, becomes the pre-flight extension.

### Productivity ledger

- **Agent moments:** 8 agent moments (6 live, 2 extension)
- **Mistakes avoided:** A credit offer during a fraud case; credit sold to clients above the guideline; prime notices that read like sales
- **Time back (illustrative):** About 3 hours cut to about 60 minutes

---

## 11:45 – 12:45 · Investing: "Can she put the GIC against the mortgage?"

*Registered plans, GICs and KYC*

**Book at a glance (Fabric IQ):** 51 clients · $6.51M in assets · $551,760 of GICs maturing within 90 days · 14 clients with stale KYC (recommendations paused) · $2.91M of unused TFSA room · $21,000 a year of RESP grants missed · 36 FHSA-eligible renters without an account

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 11:45 | **Maturity ladder brief** | Concierge · Fabric IQ | "Which GICs mature in the next 90 days, and whose KYC is stale?" The ladder comes back with the KYC status and any open case beside each maturity. | 🟢 Live |
| 11:52 | **KYC first** | Draft · Compliance Reviewer | The agent drafts KYC-refresh invitations for the 14 stale clients as service messages with no product language. Every recommendation stays paused until KYC is current (RP-027). | 🟢 Live |
| 12:00 | **GIC-maturity mission** | Mission Agent · all four IQs | Hero case below: Simone Fitzgerald. | 🟢 Live |
| 12:15 | **Investment-scam guard** | Mission Agent · Web + Work IQ | Caleb Yusuf wants both GICs paid out to a "2% a month" platform a friend recommended in a messaging group. The agent names the investment-scam typology, matches it to current Canadian Anti-Fraud Centre warnings and recommends hold-and-verify. | 🟢 Live |
| 12:22 | **Security before the maturity** | Mission Agent | Quinn Singh's TFSA GIC matures on 29 August, but her KYC is out of date and a card fraud case (SE-9030) is open. Recommendations pause and security comes first. | 🟢 Live |
| 12:28 | **RESP grants left on the table** | Draft · consent gate | $21,000 a year of grant is being missed. The agent drafts education notes only for clients with consent, citing RP-028 and RP-011, with no promised returns. | 🟢 Live |
| 12:34 | **Rate context** | Web IQ | Posted 1-year and 5-year GIC rates and high-interest savings rates, dated and for the advisor only. They never appear in client copy as a promised return (RP-016). | 🟢 Live |
| 12:40 | **Advisor-ready calendar pack** | Mission Agent + Graph | The suitability brief is attached to the licensed advisor's meeting invite, with the questions listed and no recommendation. | 🔷 Extension |

### Hero case: Simone Fitzgerald · IV-7006 / RNW-5008 · Montréal Plateau

**Mission:** GIC maturity: prepare the advisor, never the trade

**Situation.** Simone's $86,640 TFSA GIC at 3.46% matures on 26 August. Her $517,000 mortgage renews on 25 August, one day earlier. Her payment goes from $2,862 to $6,888 (+141%) and TDS rises to 41.1%. Her KYC was last updated in August 2023 and attrition is High (0.79).

**Without agents.** Three unconnected plays (GIC Retain, Idle cash to TFSA and Mortgage Retain) and a templated maturity email.

**With agents.**

1. KYC first under RP-027: every recommendation pauses.
2. Work IQ finds Wei Zhang's open points: the prepayment limit on a straight renewal, the one-day gap, TFSA room returning only next calendar year, and whether she wants an emergency cushion. He asks for one joint appointment.
3. Fabric IQ verifies the dates and amounts. Web IQ adds posted GIC rates for the advisor only.
4. Output: a suitability-ready brief with no recommendation. Client copy says "GIC", never "guaranteed".

**Derek's decision.** Derek approves and asks Sophie Tremblay to book the joint slot before 25 August.

**Productivity win.** A question that crossed two licences and two systems becomes one appointment with one brief.

### Productivity ledger

- **Agent moments:** 8 agent moments (7 live, 1 extension)
- **Mistakes avoided:** A recommendation on stale KYC; GIC funds paid to a likely scam; a maturity email blind to the renewal
- **Time back (illustrative):** About 2.5 hours cut to about 60 minutes

---

## 13:30 – 14:30 · Newcomers & transfers: "A relative who isn't"

*Packages, credit building, remittances*

**Book at a glance (Fabric IQ):** 30 newcomer clients (15 also in the mortgage or card books) · 23 send money abroad, 12 through another provider · $251,510 sent in 12 months at a total cost of $8,184 · $2,221 a year cheaper at the Bank · 2 fee-free periods ending within 60 days · 4 ready for an unsecured card · 6 scam-risk senders

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 13:30 | **Scam-risk sender sweep** | Concierge · Fabric + Security | The 6 scam-risk senders are ranked by new recipients, watch-list corridor and any open case. Joseph Mendoza is at the top. | 🟢 Live |
| 13:35 | **Newcomer mission** | Mission Agent · all four IQs | Hero case below: Joseph Mendoza. | 🟢 Live |
| 13:55 | **Fee-free notice, security first** | Mission Agent | Olena Kovalenko's fee-free period ends in September and Basic is her lowest-cost fit, but a new-device alert is open. RP-029 notice is still owed, so it goes by phone to the verified number. | 🟢 Live |
| 14:02 | **Card graduation** | Draft · Compliance Reviewer | Kateryna Bondar is ready to graduate with consent on file, and her draft passes review. Maria Santos's graduation stays paused while a remittance check is open (RP-032). | 🟢 Live |
| 14:08 | **True cost of sending** | Draft · RP-030 | For other-provider senders without an open case, the agent drafts total-cost education (fees plus FX margin). Aarav Sharma's note includes the scam-awareness message Marcus Delaney asked for. | 🟢 Live |
| 14:15 | **Plain-language check** | Compliance Reviewer | Every newcomer note is checked for plain language and an interpreter offer. Any request for a code, PIN or password is blocked. | 🟢 Live |
| 14:20 | **Corridor warnings** | Web IQ | Current remittance and relative-impersonation scam warnings for each corridor, dated and sourced, go into the advisor's briefing. | 🟢 Live |
| 14:25 | **Journey tracker** | Mission Agent | Credit-file months, on-time history and package milestones are watched, and the agent flags mortgage readiness when the journey supports it. | 🔷 Extension |

### Hero case: Joseph Mendoza · NC-3012 · Bay & Bloor · 10 months in Canada

**Mission:** Newcomer next conversation: what to say, and what not to

**Situation.** Joseph's secured card is 8 months in and always paid on time, and his fee-free package ends in 61 days. He sent $4,780 to the Philippines in 35 transfers, paying $549 against about $211 at the Bank. He has 4 new recipients in 90 days, and a $110 transfer is held pending a call-back (SE-9069).

**Without agents.** "Cheaper money transfer" and package-expiry plays, each helpful taken alone.

**With agents.**

1. Work IQ finds Marcus Delaney's mail: someone posing as a relative is pushing urgent transfers to new recipients.
2. Security first under RP-022 and RP-032, with a scam warning before every first transfer (RP-030). The cheaper-transfer play is paused, but the RP-029 fee-free notice is still owed as a service note.
3. Web IQ brings the Canadian Anti-Fraud Centre's corridor warnings.
4. Output: a call plan (2-step verification, alerts, a trusted contact, scam coaching, an interpreter offer) and a plain-language note that never asks for a code. Reviewer: PASS.

**Derek's decision.** Derek approves. Card graduation and transfer pricing wait until the case closes.

**Productivity win.** A scam case, a credit-building journey and a package deadline become one call, in the right order.

### Productivity ledger

- **Agent moments:** 8 agent moments (7 live, 1 extension)
- **Mistakes avoided:** A price pitch during an active scam; card graduation during an open check; client copy that asks for a code
- **Time back (illustrative):** About 2 hours cut to about 50 minutes

---

## 14:30 – 15:30 · Insurance: "Put it right, don't re-sell"

*Creditor, home and travel cover*

**Book at a glance (Fabric IQ):** 75 clients · 93 active policies (118 on record) · $6,676 a month in optional premiums · 12 families with a life-cover gap ($5.87M) · 5 lapses in 90 days · 16 premium-affordability reviews · 9 declined at origination

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 14:30 | **Complaint pattern** | Concierge · Work + Foundry IQ | Three June complaints say cover was "required". The agent links them to RP-031 (insurance is optional and never a condition of credit) and lists each client's origination branch and date for Complaints. | 🟢 Live |
| 14:37 | **Remediation mission** | Mission Agent · all four IQs | Hero case below: Henrik Thibault. | 🟢 Live |
| 14:55 | **Lapse-intent checks** | Draft · consent-aware | Five lapses. Simone Marchetti withdrew email and SMS consent, so she gets a phone-only service script. Noah Singh gets a service note. Farah Leclair waits because her fraud case is open. | 🟢 Live |
| 15:02 | **Premium affordability** | Draft · Compliance Reviewer | The 16 Stretched or Vulnerable clients paying optional premiums get support-first review notes. The agent never cancels and never pressures. | 🟢 Live |
| 15:08 | **Gap families, gated** | Concierge · Fabric IQ | The 12 families with a life-cover gap are ranked. Anyone above the 44% TDS guideline or without consent is blocked, and education goes out only where it's allowed. | 🟢 Live |
| 15:14 | **Travel cover check** | Fabric IQ | Clients whose premium card already includes travel cover are spotted, so nobody is sold cover they already hold. | 🟢 Live |
| 15:20 | **Regulator context** | Web IQ | Current FCAC guidance on optional creditor insurance and cancellation, dated, goes into the advisor's briefing. | 🟢 Live |
| 15:25 | **Remediation tracker** | Mission Agent + Work IQ | Complaint CMP-2207 is watched, and paused plays stay paused until Complaints replies. | 🔷 Extension |

### Hero case: Henrik Thibault · CV-1025 · Calgary Centre Street

**Mission:** Complaint and lapse remediation: put it right, don't re-sell

**Situation.** Henrik's mortgage life cover (IN-8047, $753,000) lapsed on 9 June when he stopped paying $102.41 a month. Derek knows him from the cards book: his card is at 98% of $15,200, his renewal (RNW-5025) is 75 days away and TDS at renewal is 44.8%.

**Without agents.** A templated reinstatement email goes to a client with a live complaint that he was told the cover was "required".

**With agents.**

1. Work IQ finds Raj Balakrishnan's mail: complaint CMP-2207 is with Complaints, who are reviewing a refund, and there is to be no insurance contact of any kind until they reply.
2. Policy: RP-031 (optional, never a condition of credit), RP-007 fair treatment and RP-013 (no new cover above the guideline). The book had already blocked the coverage-gap Grow play.
3. The agent links the lapse to the renewal shock and the card debt as context for Complaints, not for sales.
4. Client message: NONE — complaint open; Complaints will contact the client.

**Derek's decision.** Derek escalates to Complaints with the cross-book context attached.

**Productivity win.** A possible repeat of the mis-selling becomes a clean remediation file with the evidence chain already built.

### Productivity ledger

- **Agent moments:** 8 agent moments (7 live, 1 extension)
- **Mistakes avoided:** A reinstatement push during a complaint; cover sold above the guideline; travel cover sold twice
- **Time back (illustrative):** About 2.5 hours cut to about 60 minutes

---

## 15:30 – 16:30 · Security & fraud: "Correlate, hold, hand to a human"

*Cross-book alerts and scam protection*

**Book at a glance (Fabric IQ):** 46 clients with a security event · 72 events in 90 days (19 high) · 18 open, 10 open and high-severity · $6,930 in open cases · 39.1% without 2-step verification · 7 large e-Transfers held and verified · 4 clients whose email is blocked after a contact change

### Agent moments

| Time | Moment | Agents & IQ | What Derek gets | Status |
|---|---|---|---|---|
| 15:30 | **Fraud stand-up** | Concierge · Fabric IQ | "Which open high-severity cases still have sales plays live in other books?" The answer is one list with the cross-book exposure for each case. | 🟢 Live |
| 15:36 | **Scam-case mission** | Mission Agent · all four IQs | Hero case below: Farah Leclair. | 🟢 Live |
| 15:55 | **Typology library** | Work IQ | Callum Singh, 63, was stopped from sending a $7,160 e-Transfer to a "bank investigator" on 15 June. The agent keeps the case as a worked example of hold-and-verify for advisor coaching. | 🟢 Live |
| 16:00 | **Stop the student campaign** | Mission Agent | Jun Pelletier (20) had his email changed and a new device added, yet he is still in a student card campaign. The agent adds him to the stop list. | 🟢 Live |
| 16:06 | **Transfers she never set up** | Mission Agent | Clara Thibault's case is open, so her RNW-5040 retention call stays on hold. This matches the Everyday banking finding from the morning. | 🟢 Live |
| 16:12 | **Phishing-wave briefing** | Web + Work IQ | This month's scam campaigns are combined with the July wave of texts impersonating the Bank (10 clients since 5 July) into a one-page advisor briefing. It includes: "We will never ask for your password or passcode." | 🟢 Live |
| 16:18 | **2-step uplift** | Draft · Compliance Reviewer | Security check-in notes go to clients without 2-step verification who have no open case (RP-022), sent only through a verified channel. | 🟢 Live |
| 16:24 | **Stop-list sync** | Mission Agent + campaign tools | With human approval, the cross-book stop list goes to every campaign queue and comes off when the case closes. | 🔷 Extension |

### Hero case: Farah Leclair · SC-1018 · Bay & Bloor · High Net Worth, 55

**Mission:** Scam case investigation: correlate, hold, hand to a human

**Situation.** A new-device login and a new payee appeared on 24 July (SE-9007, High, open), and Farah's email address was changed the same week. Payees are frozen. She has no 2-step verification, no alerts and no trusted contact.

**Without agents.** Mortgage still ranks Retain plus two Deepen plays (RRSP, Creditor insurance), and Insurance ranks Lapsed-policy Retain. Every security play is blocked because the email changed.

**With agents.**

1. The agent builds a timeline from the events, the contact change and Priya Raghavan's verified call. Farah didn't recognise the device. Likely typology: account takeover.
2. Web IQ campaigns and the July phishing wave in Work IQ fit the pattern.
3. Recommendation: hold and verify through the verified phone number only; email is blocked (RP-032), and RP-034 applies to any deposit redirect.
4. Cross-book stop list: no mortgage Deepen, no insurance reinstatement, no investing outreach and no bundle until the case closes.
5. Client message: NONE — contact email changed during a security event.

**Derek's decision.** Derek hands the case to the Fraud Analyst and sends the stop list to Marcus Delaney.

**Productivity win.** Signals scattered across six books become one narrative, with sales stopped to an account that may not be in Farah's hands.

### Productivity ledger

- **Agent moments:** 8 agent moments (7 live, 1 extension)
- **Mistakes avoided:** Sales to a possibly compromised account; a student campaign to a hijacked profile; email to a changed address
- **Time back (illustrative):** About 3 hours cut to about 60 minutes

---

## 16:30 · Wrap-up: what Derek's day added up to

By 16:30 Derek has worked 64 agent moments across eight books: 55 live in the app today and 9 extensions on the same harness. Every decision is in the audit log, every agent tool call is traced, every figure is traced to the packet or a cited source, and no agent acted on its own.

| Book | What the siloed APIs returned | What actually happens |
|---|---|---|
| Mortgage | Retain + templated email | Exception memo with 3 open conditions; no rate until the PDF is on file |
| Cards | 10 plays; email consent "Granted" | One support plan; no email (phone only) |
| Everyday banking | 8 plays incl. Retain, Bundle, Consolidation | One support-first conversation; Basic package; Clara's retention call held |
| Borrowing | "Offer" queued in tomorrow's batch | HOLD; removed from batch; two clients referred to Client Assistance |
| Investing | GIC Retain + TFSA Grow + email | KYC first; one joint appointment; scam payout held |
| Newcomers | Cheaper transfer + package plays | Security first; service-only fee-free notice; one graduation approved |
| Insurance | "Lapsed policy" reinstatement | No contact; remediation file to Complaints |
| Security | Security plays blocked; sales live elsewhere | Hold-and-verify by phone; cross-book stop list |

**Last ask of the day.** "How many pricing exceptions has BR-202 granted this quarter, and what would a Québec regional grid at 20 bps of advisor discretion do to 5-year attrition exposure?" The Concierge pulls the Work IQ trail and Fabric IQ branch performance. The Scenario Analyst writes the committee brief, citing RP-015 and RP-005 and never setting a price. It becomes the first draft of Derek's 10 August recommendation.

> **Closing line:** *"The books tell me what the data says. The agents tell me what we already know, what we must not do, and the one decision a human should make. Today that was 64 moments across eight books, with an audit trail."*

## Demo click path (about 25 minutes)

1. Mortgage: Concierge morning brief, then the Agent mission for Josephine Novak. Show the Work IQ hit on Derek's own 14 July ruling.
2. Cards: blocked-play explainer, then Sana Moreau's mission. Show NONE — phone only passing the guardrails.
3. Everyday banking: Tariq Marchetti's mission. Show the reviewer's NEEDS FIXES and the corrected draft.
4. Borrowing: Nikhil Petrov's mission. Show HOLD against the engine's "Offer".
5. Security & fraud: Farah Leclair's mission. Show the cross-book stop list.
6. If time allows: Investing (Caleb Yusuf's "2% a month" platform), Newcomers (Joseph Mendoza), Insurance (Henrik Thibault).
7. Close with the Concierge question about the Québec grid and the Scenario Analyst brief.

> Live agent output varies from run to run. The decisions above are the ones the governed data, colleague threads and policies support. Rehearse each case once before presenting. Moments tagged Extension are roadmap items and should be presented that way.
