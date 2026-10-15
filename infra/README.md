# Infrastructure — Mortgage Renewal Concierge

> **SYNTHETIC DEMO DATA.** CFC Bank is used only as a branding label. Nothing in
> this solution reflects real CFC Bank customers, pricing, policy or systems.

## What Bicep covers — and what it can't

Bicep expresses **ARM control-plane** resources only. This solution spans three
Microsoft clouds, and most of it lives outside ARM:

| Layer | Resource | Bicep? | Created by |
|---|---|:--:|---|
| — | Azure AI Search **service** | ✅ | `modules/search.bicep` |
| — | Foundry (AIServices) **account** | ✅ | `modules/foundry.bicep` |
| — | Foundry **project** | ✅ | `modules/foundry.bicep` |
| — | **Model deployments** (`gpt-5.4`, `text-embedding-3-small`) | ✅ | `modules/foundry.bicep` |
| — | Foundry **storage / key vault / app insights** | ✅ | `modules/foundry-platform.bicep` |
| — | Fabric **capacity** | ✅ | `modules/fabric-capacity.bicep` |
| — | **Role assignments** | ✅ | `modules/rbac.bicep`, `modules/rbac-search.bicep` |
| — | Event Grid **system topic** on the storage account | ⚠️ | platform-created, left unmanaged (see below) |
| Foundry | the 15 **project connections** (Work IQ MCP servers, Fabric semantic model, AI Search knowledge base, SharePoint grounding) | ❌ | Foundry portal / data plane |
| Fabric IQ | workspace, lakehouse, notebooks, Delta tables, semantic model | ❌ | `data/fabric-iq/deploy_fabric.py` |
| Foundry IQ | search **index** + 10 policy documents | ❌ | `data/foundry-iq/index_renewal_policies.py` |
| Work IQ | Entra app registration + Graph consent | ❌ | `data/work-iq/provision_seeder_app.py` |
| Work IQ | mail, Teams messages, files, persona renames | ❌ | `data/work-iq/seed_work_iq.py` |
| Agent | agent + 3 function tools | ❌ | `agent/create_agent.py` |

The ❌ rows are **data-plane or Microsoft Graph** objects with no ARM provider.
They are not gaps in this template — they cannot be expressed in Bicep at all.
The Python scripts are the reproducible artefact for those, and each is
idempotent, so the whole stack is re-runnable end to end.

The ⚠️ row is the Event Grid system topic `bnsiqs-<guid>`, created implicitly by
the Foundry-to-storage integration. Its name carries a platform-generated GUID,
so declaring it would put the template in a fight with the platform for
ownership. It is documented here rather than managed.

## The live estate is not one resource group

Verified against Azure on **2026-08-21**. The demo was stood up under time
pressure and its resources landed in three resource groups across three regions:

| Resource group | Region | Contents |
|---|---|---|
| `rg-scotia-iqs` | `eastus` | Foundry account `mortgage-iqs` + project `proj-conceirge`, both model deployments, storage `bnsiqs`, key vault `kvrgscotiaiqsa7d3b8`, app insights `airgscotiaiqsa7d3b8`, Event Grid system topic |
| `rg-scotia-iqs` | `eastus2` | the **app tier** — ACR, Log Analytics, App Insights, Container Apps environment, `ca-mrc-web`, `ca-mrc-bff`, managed identity (see `../app/infra`) |
| `rg-mortgage-iq` | `canadacentral` | AI Search `aisearchrgmortgageiqa7d3b8` (Standard, apiKeyOnly, free semantic tier) |
| `rg-Fabric` | `centralus` | Fabric capacity `fabcap26` (**F8**, admin `admin@m365cpi65678641.onmicrosoft.com`) |

`main.bicep` handles this with `searchResourceGroupName` / `fabricResourceGroupName`
(plus matching `*Location` params). When the name differs from the current
resource group, the module is deployed at `scope: resourceGroup(<name>)` instead
of locally. **This is why `rbac.bicep` was split**: a role assignment must be
authored in the same deployment scope as the resource it targets, so the two
Search grants moved into `rbac-search.bicep`, deployed into the Search RG.

## Files

```
infra/
├── main.bicep                          orchestrator (resourceGroup scope)
├── main.json                           compiled ARM (checked in for auditability)
├── main.parameters.json                matches the LIVE estate - all create* = false
├── main.parameters.greenfield.json     clean-room rebuild - all create* = true
└── modules/
    ├── search.bicep                    AI Search + semantic ranker
    ├── foundry.bicep                   AIServices account + project + 2 model deployments
    ├── foundry-platform.bicep          storage + key vault + app insights
    ├── fabric-capacity.bicep           Fabric F-SKU capacity
    ├── rbac.bicep                      Azure AI User on the Foundry account
    └── rbac-search.bicep               Search grants, deployed into the Search RG
```

## Two parameter files, deliberately

**`main.parameters.json`** — every `create*` flag is `false`. The demo estate was
stood up by hand, so this file makes the template *converge on what exists* rather
than trying to recreate it. It also carries the cross-RG and cross-region facts
(`searchResourceGroupName`, `searchLocation`, `fabricResourceGroupName`,
`fabricLocation`) and the live SKUs (`standard` Search, `F8` Fabric, regional
`Standard` embedding deployment). Use it to manage drift.

**`main.parameters.greenfield.json`** — every `create*` flag is `true`, and every
resource lands in a single resource group. Use this to rebuild from nothing in an
empty resource group. Replace the two `REPLACE-WITH-ENTRA-OBJECT-ID` placeholders
first:

```powershell
az ad signed-in-user show --query id -o tsv
```

## Deploy

Always what-if before applying:

```powershell
az deployment group what-if -g <resource-group> `
  --template-file infra/main.bicep --parameters infra/main.parameters.json

az deployment group create -g <resource-group> `
  --template-file infra/main.bicep --parameters infra/main.parameters.json
```

Or run the whole stack, Bicep through agent:

```powershell
.\deploy.ps1 -Bank "<bank name>" -ResourceGroup rg-mtgrenewal-dev-eastus-001 -WhatIf   # greenfield
.\deploy.ps1 -Bank "<bank name>" -ResourceGroup rg-mtgrenewal-dev-eastus-001
# the original reference estate:
.\deploy.ps1 -ResourceGroup rg-scotia-iqs -ParametersFile infra/main.parameters.json -FabricCapacity fabcap26
.\deploy.ps1 -Only agent          # single stage
```

## Outputs → environment variables

The template outputs exactly what the downstream scripts read:

| Output | Environment variable | Consumed by |
|---|---|---|
| `searchEndpoint` | `SEARCH_ENDPOINT` | `index_renewal_policies.py`, `create_agent.py` |
| `searchIndexName` | `SEARCH_INDEX` | same |
| `foundryProjectEndpoint` | `FOUNDRY_PROJECT_ENDPOINT` | `create_agent.py` |
| `modelDeploymentName` | `FOUNDRY_MODEL` | `create_agent.py` |
| `embeddingDeploymentName` | — | vectoriser on the search index |

`deploy.ps1` wires these automatically from the deployment outputs.

`searchResourceGroupName` and `fabricResourceGroupName` are also emitted, so a
caller can locate the cross-RG resources without hard-coding them.

## Design decisions

**Create-or-reference on every resource.** Real demo estates get built by hand
under time pressure. A template that only does greenfield is useless the moment
that happens, so each resource has a `create*` flag and falls back to referencing
an existing name.

**Semantic ranking is not optional.** `searchSemanticTier` disallows `disabled`.
If the ranker is off, index creation still succeeds but the agent's semantic query
fails at run time and the tool **silently falls back to the local JSON corpus** —
you would get plausible answers and never know it wasn't querying Azure.

**RBAC is per-resource, not resource-group.** `rbac.bicep` scopes *Azure AI User*
to the Foundry account, and `rbac-search.bicep` scopes the two Search roles to the
Search service, rather than granting broadly at the resource group. The split into
two modules is forced by the cross-RG layout, not chosen.

**Portal-created resources are adopted, not ignored.** The Foundry wizard created
the storage account, key vault and Application Insights on 2026-08-03
(deployment `AIFoundryCreate-20260803161911`). `foundry-platform.bicep` declares
them with `create* = false` in the live parameter file, so the repo documents them
and a greenfield rebuild reproduces them, without the template trying to take
them over.

**`main.json` is committed.** The compiled ARM gives you a reviewable diff when
the Bicep changes, and lets anyone deploy without the Bicep CLI.

## Known what-if noise

What-if reports `properties.currentCapacity` as being removed from **both** model
deployments. That property is **read-only and computed** — it cannot be set from a
template. This is a documented what-if false positive; the deployment does not
change capacity as long as `modelCapacity` / `embeddingCapacity` match the live
values.

As of 2026-08-21 this is the *only* difference what-if reports against
`rg-scotia-iqs` with `main.parameters.json`. Two `Modify` entries, both
`currentCapacity` — anything beyond that is real drift and should be
investigated before applying.

## Cost

| Resource | Note |
|---|---|
| Fabric capacity `fabcap26` | **F8 — bills while Active.** Suspend between demos |
| AI Search `aisearchrgmortgageiqa7d3b8` | Standard tier; free semantic tier covers 1,000 queries/mo |
| Foundry models | Pay-per-token; the deployments themselves cost nothing idle |
| Container Apps `cae-mrc` | Consumption plan; scales to zero |
| Storage / Key Vault / App Insights | Negligible at demo volume |

```powershell
# suspend Fabric when finished
az rest --method post --url "https://management.azure.com<capacity-id>/suspend?api-version=2023-11-01"
```

## Teardown

```powershell
python data/work-iq/seed_work_iq.py --auth cli --restore-users   # undo persona renames
python data/work-iq/provision_seeder_app.py --delete             # drop the app registration
az deployment group delete -g <rg> -n main                       # remove the deployment record
```

Deleting the Fabric **workspace** and the **AI Search index** is manual — neither
is ARM-managed.
