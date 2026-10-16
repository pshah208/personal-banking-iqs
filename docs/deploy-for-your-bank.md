# Deploy the demo for your bank

The repository ships bank-neutral. All copy — emails, meetings, Teams threads,
policies, agent instructions, the guided story and the dashboard — is written
for the fictional **CFC Bank**. When you deploy, you name a real or fictional
bank and the deployment is branded for it end to end:

| Layer | What changes | How |
|---|---|---|
| Web app | logo, top-bar mark, favicon, colour palette, bank name in every view | brand pack in `app/src/web/public/brand/<id>/`, loaded at start-up from `brands.json` |
| Foundry agent | instructions name the bank | `agent/create_agent.py` → `tools/brand/bank_profile.py` |
| Fabric IQ | CSV text uploaded to OneLake | `data/fabric-iq/deploy_fabric.py` |
| Foundry IQ | policy documents indexed in AI Search | `data/foundry-iq/index_renewal_policies.py` |
| Work IQ | mail, Teams messages and files seeded into Microsoft 365 | `data/work-iq/seed_work_iq.py` |
| BFF | `/api/config` bank name | `BANK_NAME` app setting (`bankName` Bicep parameter) |

> Everything is synthetic. Public bank logos are retrieved only for the
> deploying organisation's own demo and are **never committed** to this repo
> (`.gitignore` keeps every pack except `cfc/`). Make sure you are permitted to
> show a bank's marks before you present them.

---

## 1. How the branding is resolved

`tools/brand/fetch_brand.py --bank "<name>"`:

1. **Wikidata** — finds the bank's item (preferring items that are banks or
   financial institutions) for its official name, short name / acronym
   (`RBC`, `TD`), aliases, official website, logo file and official colour.
2. **Bank website** — `<meta name="theme-color">`, `apple-touch-icon` and site
   icons.
3. **Logo** — the Wikimedia Commons render of the official logo, else the site
   icon, else `og:image`. White backgrounds are removed and the image trimmed.
4. **Colours** — `--primary` flag › Wikidata official colour › `theme-color` ›
   dominant logo colour; accent = the next distinct logo hue. Every CSS shade
   (deep, tint, line, ink, accent-ink, accent-fg) is derived with contrast
   checks so white text on the top bar stays legible.
5. **Output** — `lockup.png` (sign-in card), `mark.png` (top bar; turned white
   when it would vanish on the brand colour), `favicon.png`, `brand.json`
   (with provenance), and `brands.json`, the manifest the app loads.

Preview without deploying anything:

```powershell
python tools/brand/fetch_brand.py --bank "Royal Bank of Canada"
python tools/brand/fetch_brand.py --list
cd app/src/web; npm install; npm run dev      # http://localhost:5173/?bank=rbc
```

When the lookup is wrong or the bank is fictional, override any piece:

```powershell
python tools/brand/fetch_brand.py --bank "TD Bank" --short TD --domain td.com
python tools/brand/fetch_brand.py --bank "Contoso Bank" --offline --logo .\contoso.png --primary "#0b5cab"
python tools/brand/fetch_brand.py --bank "BMO" --name "BMO Personal Banking" --accent "#ed1c24"
```

| Flag | Purpose |
|---|---|
| `--domain` | website, when Wikidata does not list one |
| `--short` / `--name` | narrative short name / display name |
| `--alias` | extra names (used to hide the bank's own offers in competitor views) |
| `--logo` / `--icon` | file or URL instead of the lookup |
| `--primary` / `--accent` | colours instead of the lookup |
| `--exclusive` | offer only this bank (hides the in-app bank switcher) |
| `--no-default` | add a pack without making it the default (multi-bank switcher) |
| `--offline` | no network at all (needs `--logo` and `--primary`) |

Several packs can coexist: without `--exclusive` the app shows a **Bank**
switcher, and `?bank=<id>` selects one in a shareable link.

---

## 2. Deploy from GitHub Actions

### One-time setup

1. **Fork** (or use as a template) into your organisation.
2. Create an Entra app registration for the workflow and add a **federated
   credential** for `repo:<owner>/<repo>:ref:refs/heads/main` (and for any
   environment you use). No client secret is stored.
3. Grant it **Owner** on the target subscription, or **Contributor** plus
   **User Access Administrator** — the Bicep creates role assignments.
   For the web-app stage it also needs Microsoft Graph `Application.Read.All`
   to look up the SPA app registration.
4. Add repository secrets:

   | Secret | Value |
   |---|---|
   | `AZURE_CLIENT_ID` | the workflow app registration's client ID |
   | `AZURE_TENANT_ID` | your tenant ID |
   | `AZURE_SUBSCRIPTION_ID` | target subscription |
   | `AAD_CLIENT_ID`, `AAD_CLIENT_SECRET`, `AAD_API_SCOPE` | web app sign-in; printed by `python app/infra/provision_app_registrations.py` (run once from a workstation) |

### Run

*Actions → **Deploy for a bank** → Run workflow*:

| Input | Notes |
|---|---|
| `bank_name` | e.g. `Royal Bank of Canada` |
| `bank_domain`, `bank_short` | only if the preview is wrong |
| `stages` | `brand` (preview only, no Azure access) → `preflight` → `core` → `core+app` / `app` |
| `resource_group`, `location`, `app_location` | CAF-style default `rg-mtgrenewal-dev-eastus-001`; created if missing |
| `include_fabric` | Fabric IQ needs a Fabric-enabled tenant and *Service principals can use Fabric APIs* turned on |
| `mortgage_servicer` (app deploy `-MortgageServicer`) | Simulated mortgage-servicing profile: `generic`, `msp`, `fis`, `inhouse` (labels only - see [systems-of-record.md](systems-of-record.md)) |
| `card_processor` | Simulated card-processor profile in the Cards book: `generic`, `tsys`, `fiserv`, `globalpayments` (labels only - see [card-processor-simulator.md](card-processor-simulator.md)) |

Jobs:

1. **brand** — resolves the brand, publishes a summary and a `brand-pack`
   artifact (download it to check the images).
2. **preflight** — policy assignments, compliance posture, the caller's roles
   in scope, `docs/allowed.md` / `docs/naming.md` when present, then a Bicep
   **what-if**. Fails before anything is created if the caller cannot deploy.
3. **core** — `deploy.ps1`: resource group, Bicep (AI Search, Foundry account +
   project + models, optional Fabric capacity, RBAC), Foundry IQ index, agent,
   optional Fabric IQ.
4. **app** — `app/deploy.ps1`: ACR, Container Apps, images built with the brand
   pack baked in.

Work IQ (Microsoft 365 seeding) is deliberately not run in CI: it writes into
mailboxes and the Teams step needs a delegated sign-in. Run it from a
workstation (below).

---

## 3. Deploy from a workstation

```powershell
pip install -r requirements.txt
az login

# optional: governance report first
.\tools\preflight.ps1 -ResourceGroup rg-mtgrenewal-dev-eastus-001 -Locations eastus,eastus2

.\deploy.ps1 -Bank "Royal Bank of Canada" -ResourceGroup rg-mtgrenewal-dev-eastus-001 -WhatIf
.\deploy.ps1 -Bank "Royal Bank of Canada" -ResourceGroup rg-mtgrenewal-dev-eastus-001

# web app
python app\infra\provision_app_registrations.py --spa-redirect http://localhost:5173
.\app\deploy.ps1 -ResourceGroup rg-mtgrenewal-dev-eastus-001 -AadClientId <id> -AadClientSecret <secret> -AadApiScope api://<id>/access_as_user
```

`deploy.ps1` defaults to `infra/main.parameters.greenfield.json`, creates the
resource group, and fills the greenfield principal placeholders with the
signed-in user (or pass `-PrincipalId`). Useful switches:

| Switch | Effect |
|---|---|
| `-Only brand` | rebrand only (then redeploy the app with `app\deploy.ps1 -Only images`) |
| `-Skip fabric,work-iq` | leave stages out of a full run |
| `-FabricCapacity <name>` | use an existing capacity |
| `-ParametersFile infra/main.parameters.json` | target the original reference estate |

To rebrand an existing deployment: `.\deploy.ps1 -Only brand -Bank "<name>"`,
then `.\app\deploy.ps1 -Only images`, and re-run the `agent`, `foundry-iq`,
`fabric` and `work-iq` stages for the back-end content to follow.

---

## 4. Costs and clean-up

AI Search (Basic), the Foundry model deployments, Container Apps and — when
created — the Fabric capacity bill while they exist; Fabric bills while
**Active**, so pause it after a demo. Remove everything with:

```powershell
az group delete -n rg-mtgrenewal-dev-eastus-001
python data/work-iq/provision_seeder_app.py --delete   # if Work IQ was seeded
```
