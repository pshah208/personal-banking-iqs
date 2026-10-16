# Personal Banking Concierge — synthetic data + ingestion runbook

A complete, ready-to-load synthetic dataset and upload runbook for building a
**Mortgage Renewal Concierge** agent in Azure AI Foundry, grounded across three
Microsoft intelligence layers.

Scenario: a retail bank's FY26 180-day mortgage renewal campaign, three pilot
branches, as at **2026-08-03**. The repository is **bank-neutral**: its copy is
written for the fictional **CFC Bank**, and every deployment is branded for the
bank you name at deploy time (see [Deploy it for your bank](#deploy-it-for-your-bank)).

> ⚠️ **Everything in this dataset is synthetic and illustrative.** The bank name
> and marks are used only as a branding label for a demo. No person, customer,
> branch, balance, rate, internal policy, pricing guardrail, approval limit or
> governance decision here reflects any actual bank's data, product, process or
> position — all of it was generated for this demo. OSFI guideline numbers
> (B-20, B-21, E-21, E-23) are real public guidelines cited by name only; the
> policy text around them is invented. Do not present this as real bank
> information.

---

## Deploy it for your bank

Give the deployment a bank name and it picks up that bank's public branding —
official name, short name, logo, icon and colours — from Wikidata, Wikimedia
Commons and the bank's own website. The web app, the Foundry agent's
instructions, and the content seeded into Fabric IQ, Foundry IQ and Work IQ all
name that bank.

**From GitHub (no local tooling):** fork the repo, add the OIDC secrets, then
*Actions → Deploy for a bank → Run workflow*, enter the bank name and pick the
stages. Start with `stages = brand` to preview the logo and colours.

**From a workstation:**

```powershell
pip install -r requirements.txt
az login
.\deploy.ps1 -Bank "Royal Bank of Canada" -ResourceGroup rg-mtgrenewal-dev-eastus-001 -WhatIf
.\deploy.ps1 -Bank "Royal Bank of Canada" -ResourceGroup rg-mtgrenewal-dev-eastus-001
.\app\deploy.ps1 -ResourceGroup rg-mtgrenewal-dev-eastus-001 -AadClientId ... -AadClientSecret ... -AadApiScope ...
```

Full walkthrough, prerequisites and overrides (`-BankDomain`, `-BankShort`,
`--logo`, `--primary`): **[docs/deploy-for-your-bank.md](docs/deploy-for-your-bank.md)**.

The Cards book also includes a **simulated card processor** (system of record) with
authorisations, declines, billers on file, disputes and human-approved servicing
actions - see **[docs/card-processor-simulator.md](docs/card-processor-simulator.md)** - and the renewal book a
**simulated mortgage servicing platform** (payout requests, bureau shopping signals, offers and rate holds, returned
payments), both streamed live through Fabric Eventstream - see **[docs/systems-of-record.md](docs/systems-of-record.md)**.

---

## What the agent answers

| Ask | IQ layer | Tool | Returns |
|---|---|---|---|
| "Summarize discussions from emails, Teams and meetings related to upcoming mortgage renewals." | **Work IQ** | `search_work_iq` | Concerns from branch leaders · Feedback from advisors · Escalations around renewal rates · Executive guidance |
| "Analyze mortgage renewals occurring in the next 180 days and identify customers most at risk of attrition." | **Fabric IQ** | `query_renewal_analytics` | Customer segments · Renewal likelihood · Revenue exposure · Recommended offers |
| "Review renewal pricing and retention policies and identify approvals required." | **Foundry IQ** | `lookup_renewal_policy` | Pricing guardrails · OSFI policy references · Approval requirements · Risk considerations |

---

## Repository layout

```
mortgage-renewal-concierge/
├── README.md                     ← you are here
├── deploy.ps1                    end-to-end orchestration (brand → Bicep → data → agent)
├── requirements.txt              Python dependencies
├── .github/workflows/            deploy.yml (Deploy for a bank) · ci.yml (build + checks)
├── tools/
│   ├── brand/fetch_brand.py            bank name → brand pack (logo, colours, names)
│   ├── brand/bank_profile.py           the deployed bank, for the Python scripts
│   └── preflight.ps1                   policy / RBAC / allow-list report before deploying
├── infra/                        → Azure control plane (Bicep)
│   ├── README.md                       what Bicep can and cannot cover
│   ├── main.bicep · main.json          orchestrator + compiled ARM
│   ├── main.parameters.json            matches the live estate (create* = false)
│   ├── main.parameters.greenfield.json clean-room rebuild (create* = true)
│   └── modules/                        search · foundry · fabric-capacity · rbac
├── data/
│   ├── work-iq/                  → Microsoft 365 (Exchange · Teams · SharePoint/OneDrive)
│   │   ├── emails.json                 18 emails, 14 personas, 4 categories
│   │   ├── teams_messages.json         1 team, 3 channels, 12 threads + 31 replies
│   │   ├── meetings/                   4 meeting records (minutes + transcript)
│   │   ├── user_mapping.json           persona → licensed tenant account + demo driver
│   │   ├── provision_seeder_app.py     creates the Entra app + grants + consent
│   │   └── seed_work_iq.py             Microsoft Graph seeding script
│   ├── fabric-iq/                → Microsoft Fabric OneLake Lakehouse
│   │   ├── generate_fabric_data.py         deterministic generator (re-runnable)
│   │   ├── deploy_fabric.py                one-command Fabric deployment
│   │   ├── customers.csv                   50 customers · 5 segments · 3 branches
│   │   ├── mortgage_renewals.csv           50 mortgages maturing within 180 days
│   │   ├── renewal_risk_scores.csv         attrition score, exposure, recommended offer
│   │   ├── retention_offers.csv            8-offer catalogue with approval levels
│   │   ├── branch_performance.csv          branch rollup
│   │   ├── load_renewals_fabric.py         notebook → 7 Delta tables
│   │   └── create_semantic_model_fabric.py notebook → Direct Lake model + measures
│   └── foundry-iq/               → Azure AI Search knowledge index
│       ├── renewal_policies.json       10 policy documents (RP-001 … RP-010)
│       └── index_renewal_policies.py   index creation + upload
└── agent/
    ├── agent_instructions.md     agent system prompt + tool contract
    └── create_agent.py           creates the Foundry agent with 3 function tools
```

---

## Step 0 — Try it with zero Azure setup

Every tool falls back to the local synthetic files, so you can validate the whole
agent contract before wiring any backend:

```powershell
cd mortgage-renewal-concierge\agent
python create_agent.py --local-smoke
```

You should see segment rollups, the ranked high-risk customers with their
recommended offer and approval level, and the matching policy documents.

---

## Deploy everything (the short version)

```powershell
pip install -r requirements.txt
az login

.\deploy.ps1 -ResourceGroup <rg> -FabricCapacity <capacity> -WhatIf   # preview
.\deploy.ps1 -ResourceGroup <rg> -FabricCapacity <capacity>           # apply
```

`deploy.ps1` runs Bicep → Fabric IQ → Foundry IQ → Work IQ → agent in dependency
order, wiring each stage's outputs into the next. Use `-Only <stage>` to run one
stage, `-SkipWorkIq` to leave Microsoft 365 alone.

**Bicep covers the Azure control plane only** — AI Search service, Foundry account,
project, model deployment, Fabric capacity and role assignments. The Fabric
workspace, the search index, the M365 content and the agent itself are data-plane
or Graph objects with no ARM provider, so they come from the Python scripts. See
[`infra/README.md`](infra/README.md) for the full split.

The rest of this document is the **manual walkthrough**, layer by layer.

---

## Step 1 — Fabric IQ → Microsoft Fabric (OneLake + semantic model)

**Data:** `data/fabric-iq/*.csv` · **Target:** workspace `ws-mortgage-renewals-demo`

### Automated (recommended)

`deploy_fabric.py` does the whole thing idempotently using your `az login`:

```powershell
cd mortgage-renewal-concierge\data\fabric-iq
pip install requests
az login

python deploy_fabric.py --capacity <your-capacity-name>
python deploy_fabric.py --status          # show what exists + the env vars to set
```

It creates, in order:

| # | Artifact | Notes |
|---|---|---|
| 1 | Workspace `ws-mortgage-renewals-demo` | bound to the named capacity; the synthetic-data disclaimer goes in the workspace description |
| 2 | Lakehouse `lh_mortgage_renewals` | plus its SQL analytics endpoint |
| 3 | `Files/renewals/*.csv` in OneLake | uploaded via the OneLake ADLS Gen2 API |
| 4 | Notebook `nb_load_renewals` | run as a job → 5 base + 2 curated Delta tables |
| 5 | Notebook `nb_create_semantic_model` | run as a job → Direct Lake model `sm_mortgage_renewals` with 2 relationships and 15 measures |

Individual steps: `--only workspace|lakehouse|upload|notebook|semantic-model`.

> The capacity must be **Active**. If it is paused:
> `az rest --method post --url "https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Fabric/capacities/<name>/resume?api-version=2023-11-01"`

### Tables produced

| Table | Rows | Purpose |
|---|---|---|
| `customers` · `mortgage_renewals` · `renewal_risk_scores` · `retention_offers` · `branch_performance` | 50 / 50 / 50 / 8 / 3 | raw synthetic source |
| `renewal_attrition_risk` | 50 | **curated fact** — everything joined, filtered to 180 days, plus `ltv_band`, `payment_shock_band` and `maturity_bucket` |
| `renewal_segment_summary` | 5 | segment rollup |

> Why tables and not views: Spark SQL views live only in the Spark metastore. They
> are **not** visible through the SQL analytics endpoint and cannot back a Direct
> Lake semantic model. Materialising the curated layer as Delta tables means the
> same objects serve the SQL endpoint, the semantic model and the agent.

### Semantic model `sm_mortgage_renewals`

Direct Lake over the curated tables — reads the Parquet in OneLake directly, so
there is no import and no refresh schedule. It carries the business definitions so
they are stated once rather than re-derived in every query:

| Measure | Meaning |
|---|---|
| `Renewals in 180 Days`, `Balance Maturing` | population and size of the book |
| `Annual Revenue Exposure`, `Five Year Lifetime Value` | what is at stake |
| **`Value at Risk`** | `SUMX(exposure × attrition_risk_score)` — probability-weighted. This is the sort order the 20 July Renewal Council asked for |
| `High Risk Renewals`, `High Risk Exposure`, `Pct Balance At High Risk` | risk concentration |
| `Balance Above 80 LTV`, `Balance Above 60 Pct Payment Shock` | the CRO's monthly-pack splits required by policy RP-009 |
| `Avg Renewal Likelihood Pct`, `Avg Payment Shock Pct`, `Avg Competitor Gap Bps`, `Avg LTV Pct`, `Rate Shopping Signals` | campaign diagnostics |

Relationships: `renewal_attrition_risk` → `retention_offers` (offer catalogue) and
→ `branch_performance` (branch rollup).

### Wire the agent

```powershell
$env:FABRIC_WORKSPACE_ID    = "<workspace guid from --status>"
$env:FABRIC_SEMANTIC_MODEL  = "sm_mortgage_renewals"
# optional SQL fallback
$env:FABRIC_SQL_ENDPOINT    = "<...>.datawarehouse.fabric.microsoft.com"
$env:FABRIC_DATABASE        = "lh_mortgage_renewals"
```

The `query_renewal_analytics` tool resolves its backend in this order:

1. **Semantic model** via the Power BI `executeQueries` DAX endpoint — preferred,
   because the agent then consumes the *governed measures* rather than re-deriving
   business logic in SQL. Needs no ODBC driver.
2. **SQL analytics endpoint** via `pyodbc` — requires **ODBC Driver 18 for SQL Server**.
3. **Local CSVs** — so a demo never hard-fails.

The tool reports which one it used in its `mode` field.

### Manual alternative

If you'd rather click through it: create the workspace and assign capacity, create
the Lakehouse, upload the CSVs to `Files/renewals/`, create a notebook from
`load_renewals_fabric.py` and run it, then a second notebook from
`create_semantic_model_fabric.py` and run that.

**Verify:** `python deploy_fabric.py --status`, then in the Fabric portal open
`sm_mortgage_renewals` and check the measures appear on `renewal_attrition_risk`.

> 💸 **Pause the capacity when you're done.** The live `fabcap26` is an **F8** and
> bills while Active.
> `az rest --method post --url "https://management.azure.com/<capacity-resource-id>/suspend?api-version=2023-11-01"`

---

## Step 2 — Work IQ → Microsoft 365 (Exchange · Teams · SharePoint)

**Data:** `data/work-iq/` · **Target:** a **non-production / demo tenant**

> ⚠️ This writes into user mailboxes and creates a Team. Do not run it in a
> production tenant.

### 2a. Provision the app registration

```powershell
cd mortgage-renewal-concierge\data\work-iq
pip install azure-identity requests
az login                                   # as Global Administrator

python provision_seeder_app.py             # creates app + SP, grants + consents, issues secret
python provision_seeder_app.py --show      # report state, change nothing
python provision_seeder_app.py --enable-device-code --no-secret
python provision_seeder_app.py --delete    # tear down when the demo is over
```

Application permissions granted (admin consent applied directly via
`appRoleAssignments`): `User.Read.All` · `User.ReadWrite.All` · `Mail.ReadWrite` ·
`Group.ReadWrite.All` · `Team.Create` · `TeamMember.ReadWrite.All` ·
`Channel.Create` · `ChannelMessage.Read.All` · `Files.ReadWrite.All` ·
`Sites.ReadWrite.All`.

> **`ChannelMessage.Send` does not exist as an application permission** — it is
> delegated-only. App-only posting instead requires `Teamwork.Migrate.All` and
> works only against a team created in *migration mode*; Graph otherwise returns
> *"Message POST is allowed in application-only context only for import purposes."*
> So the Teams **messages** step uses delegated device-code auth. Everything else
> (team, channels, members, mail, files) runs app-only.

> Treat the client secret as sensitive: it is printed once, never written to disk
> by the script, and should not be committed. Delete the app when finished.

### 2b. Map the personas onto licensed accounts

> **Do not create 14 new users.** A user without an Exchange Online licence has no
> mailbox (the mail import fails), and without a Microsoft 365 Copilot licence
> Work IQ cannot ground on their content. Check your headroom first:
>
> ```powershell
> az rest --method get --url "https://graph.microsoft.com/v1.0/subscribedSkus" `
>   --query "value[].{sku:skuPartNumber,enabled:prepaidUnits.enabled,used:consumedUnits}" -o table
> ```
>
> Most demo tenants are fully consumed. The supported path is to **map the personas
> onto existing licensed users**.

`user_mapping.json` holds that mapping — persona alias → real UPN, display name,
job title and department. Edit it for your tenant, then:

```powershell
python seed_work_iq.py --auth cli --check-users          # confirm all 14 resolve
python seed_work_iq.py --auth cli --map-users --dry-run  # preview the renames
python seed_work_iq.py --auth cli --map-users            # apply
```

`--map-users` snapshots each account's original `displayName` / `jobTitle` /
`department` to **`user_mapping.restore.json`** before patching. Keep that file —
it is how you undo the change:

```powershell
python seed_work_iq.py --auth cli --restore-users
```

Mail renders `displayName`, so renaming is what makes the narrative read correctly
without creating unlicensable users. UPNs, mailboxes and licences are untouched.

### 2c. Pick the demo driver

Work IQ grounds **only on content the signed-in user can access**, so the account
you sign in as to ask the question matters more than where the data nominally sits.

`driver_alias` in `user_mapping.json` names that account — **Raj Balakrishnan**
(VP, Real Estate Secured Lending) by default. He chairs the Renewal Council, so he
legitimately sits across all four categories the demo question asks for, and he is
the most-connected persona in the corpus (on 11 of 18 emails and 5 Teams threads).
The seeder **cc's the driver on any email he is not already party to**, so nothing
in the corpus is invisible to him.

### 2d. Seed

```powershell
cd mortgage-renewal-concierge\data\work-iq
pip install azure-identity requests

$env:WORKIQ_TENANT_ID     = "<tenant-guid>"
$env:WORKIQ_CLIENT_ID     = "<app-client-id>"
$env:WORKIQ_CLIENT_SECRET = "<client-secret>"

python seed_work_iq.py --all --dry-run                              # preview every Graph call
python seed_work_iq.py --only mail --purge                         # 18 emails → inboxes + sent
python seed_work_iq.py --only teams                                # team + 3 channels + 14 members
python seed_work_iq.py --only teams --messages-only --auth device  # 43 channel messages
python seed_work_iq.py --only files                                # notes → SharePoint + OneDrive
```

`--purge` deletes previously seeded copies (matched on subject) first, so
re-running does not duplicate the corpus.

What lands where:

| Content | Destination |
|---|---|
| 18 emails | each recipient's **Inbox** and the author's **Sent Items**, with original sender, recipients, importance and **original timestamp** |
| 1 team, 3 channels, 12 threads + 31 replies (**43 messages**) | Team **Retail Mortgage Renewals FY26** → *Renewal Campaign - 180 Day*, *Branch Leaders Forum*, *Pricing Exceptions* |
| 4 meeting records + the source JSON | the team's SharePoint library under `Renewal Campaign/Meetings` and `Renewal Campaign/Source`, plus the driver's OneDrive |

> **Timestamp fidelity.** Exchange silently rewrites `sentDateTime` /
> `receivedDateTime` to *now* on create, collapsing the June–August narrative into
> a single day. The seeder therefore also sets the underlying MAPI properties —
> `PR_CLIENT_SUBMIT_TIME` (`SystemTime 0x0039`) and `PR_MESSAGE_DELIVERY_TIME`
> (`SystemTime 0x0E06`) — which Exchange does honour. The story arc then reads and
> sorts correctly.

> **App-only team creation accepts exactly one member.** The team is created with
> the owner and the other 13 are added via the members collection. Membership is
> re-ensured on every run, so `--only teams` is safe to repeat.

> The delegated account used for the messages step must be a **member of the
> team**, otherwise posting returns 403.

**Verify:** sign in as the driver, confirm the inbox shows the campaign threads
dated June–August, and the Team shows all three channels. Allow **15–30 minutes**
for Microsoft 365 / Copilot indexing before querying Work IQ.

---

## Step 3 — Foundry IQ → Azure AI Search

**Data:** `data/foundry-iq/renewal_policies.json` · **Target:** index `renewal-policies`

```powershell
# 1. Reuse an existing Search service if you have one - check first
az resource list --resource-type Microsoft.Search/searchServices -o table

# ...or provision one (Basic tier is sufficient for this corpus)
az search service create -g <rg> -n <search-name> --sku Basic -l canadacentral

# 2. Semantic ranking must be enabled for the agent's semantic query path.
#    The 'free' tier allows 1,000 semantic queries/month at no cost.
az search service update -g <rg> -n <search-name> --semantic-search free

# 3. (optional) enable Entra auth alongside keys
az search service update -g <rg> -n <search-name> --auth-options aadOrApiKey

# 4. Create the index and upload the corpus
cd mortgage-renewal-concierge\data\foundry-iq
pip install azure-search-documents==11.5.2 azure-identity

$env:SEARCH_ENDPOINT  = "https://<search-name>.search.windows.net"
$env:SEARCH_ADMIN_KEY = (az search admin-key show -g <rg> --service-name <search-name> --query primaryKey -o tsv)
$env:SEARCH_INDEX     = "renewal-policies"
python index_renewal_policies.py
```

> If `--semantic-search` is left disabled, index creation still succeeds but the
> agent's semantic query fails at run time and silently falls back to the local
> JSON corpus. Check the `live` field in the tool's response to confirm.

The corpus (10 documents, keyword + semantic ranking):

| Id | Title | Category |
|---|---|---|
| RP-001 | Renewal Pricing Guardrails — National Discount Grid | `pricing_guardrail` |
| RP-002 | Discretionary Pricing Approval Matrix and Competitor Evidence Standard | `approval_requirement` |
| RP-003 | Retention Offer Catalogue — Eligibility and Approval | `approval_requirement` |
| RP-004 | OSFI Guideline B-20 — Application to Mortgage Renewals | `regulatory_reference` |
| RP-005 | OSFI Guideline E-23 — Model Risk Management for the Attrition Model | `regulatory_reference` |
| RP-006 | Amortization Relief Fast Path for Straight Renewals | `approval_requirement` |
| RP-007 | Fair Treatment of Clients at Renewal — Conduct and Disclosure | `risk_consideration` |
| RP-008 | Regional Pricing Variation — Governance and Evidence | `pricing_guardrail` |
| RP-009 | Renewal Portfolio Risk Considerations and Concentration Limits | `risk_consideration` |
| RP-010 | Renewal Escalation Procedure and Service Standards | `approval_requirement` |

**Verify:** in the portal, *Search explorer* on `renewal-policies`, query
`approval authority above 25 bps` — RP-001 and RP-002 should rank top. Or check
the tool end to end (`live: true` means it reached AI Search):

```powershell
python ..\..\agent\create_agent.py --local-smoke
```

Retrieval spot-checks that should each return the named policy first:

| Question | Expected top hit |
|---|---|
| who approves a rate discount above 25 basis points | RP-001 / RP-002 |
| what evidence is needed for a competitor rate match | RP-002 |
| does the stress test apply to a straight mortgage renewal | RP-004 (B-20) |
| can we extend amortization without re-underwriting | RP-006 |
| model governance for the attrition score | RP-005 (E-23) |
| concentration risk from retaining high LTV borrowers | RP-009 |

To use it as a **Foundry knowledge source** instead of a function tool: in the
Foundry portal go to your project → **Knowledge → + Add → Azure AI Search**,
point it at this index, and attach it to the agent.

---

## Step 4 — Build the Foundry agent

```powershell
cd mortgage-renewal-concierge\agent
pip install azure-ai-agents==1.1.0 azure-identity==1.19.0 azure-search-documents==11.5.2 requests pyodbc

$env:FOUNDRY_PROJECT_ENDPOINT = "https://<res>.services.ai.azure.com/api/projects/<proj>"
$env:FOUNDRY_MODEL            = "gpt-4.1"     # any deployment in that project

python create_agent.py --create      # create/update the agent + its 3 tools
python create_agent.py --demo        # run all three demo questions
python create_agent.py --chat        # interactive
```

The three function tools appear in the Foundry portal under
**Agents → mortgage-renewal-concierge → Tools**. The system prompt lives in
`agent/agent_instructions.md` between the `INSTRUCTIONS-START/END` markers —
edit there and re-run `--create` to update.

### Identity and roles

| To do this | Grant |
|---|---|
| Create/run agents from your user | **Azure AI User** (or Contributor) on the Foundry project |
| Run agents from a managed identity | see `mortgage-iq-app/README.md` → *Required role (agents data plane)* — needs a custom role with `Microsoft.CognitiveServices/accounts/AIServices/*` data actions |
| Read the AI Search index with Entra | **Search Index Data Reader** on the search service |
| Query the Fabric semantic model | **Viewer** on the workspace + **Read** on the semantic model (workspace Member/Contributor covers both) |
| Query the Fabric SQL endpoint | workspace **Viewer**/**Member**, plus ODBC Driver 18 locally |
| Search M365 content | delegated `Mail.Read`, `ChannelMessage.Read.All`, `Files.Read.All` |

---

## Data design notes

**Fabric IQ.** 50 renewals maturing 6–180 days out, across 5 segments and
3 branches. Legacy rates 1.79–3.24% renewing into 4.09–5.34%, producing payment
shock of roughly 30–140%. The attrition score is a transparent weighted function
of competitor rate gap, payment shock, product depth, primary-relationship flag,
origination channel, digital engagement, rate-shopping signal, complaints and
tenure — so any score the agent quotes is explainable, which is the point of the
OSFI E-23 thread in the policy corpus. Risk mix is roughly 16 High / 22 Medium /
12 Low. Recommended offers are validated against the eligibility rules in
`retention_offers.csv`.

**Work IQ.** The corpus is deliberately built so the four requested return
categories are each discoverable and *conflict with one another*:

- **Branch leader concerns** — three genuinely different problems: BR-101 advisor
  capacity, BR-202 competitor pricing in Québec, BR-303 payment shock among
  self-employed clients. Plus a cross-branch gap: unowned broker-originated renewals.
- **Advisor feedback** — approval latency, no view of relationship value, lists
  sorted by maturity rather than value at risk, stale pricing grid, French-language
  gaps, clients asking about *payment* while the script leads with *rate*.
- **Rate escalations** — RNW-5014 (32 bps requested → 28 bps approved with three
  conditions), RNW-5033 (what counts as competitor evidence), three BR-303
  amortization-relief files, and the Québec regional grid request.
- **Executive guidance** — Diane Lafleur's three non-negotiables and 60-day
  direction, Karen Whitfield's four risk conditions, Helena Vasquez's compliance
  items. Threads recur across email, Teams and meetings so a summary has to
  reconcile them rather than repeat one source.

**Foundry IQ.** Written so the answers to "what's allowed / who approves" are
unambiguous and interlocking: RP-001 sets the guardrails, RP-002 the approval
matrix and tiered evidence standard, RP-003 offer eligibility, RP-004/RP-005/RP-009
the OSFI B-20, E-23 and E-21 hooks, RP-006 the amortization fast path with its
three hard conditions, RP-007 conduct, RP-008 regional grid governance and
RP-010 the escalation procedure.

## Regenerating

```powershell
python data\fabric-iq\generate_fabric_data.py   # deterministic - same output every run
```

Change `SEED`, `AS_OF` or the segment/branch tables at the top of that file to
reshape the dataset. The Work IQ and Foundry IQ corpora are hand-authored JSON —
edit them directly and re-run the seeding/indexing scripts.
