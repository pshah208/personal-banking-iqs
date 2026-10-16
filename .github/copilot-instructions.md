# Mortgage Renewal Concierge / IQs

## What this is

This repo is a synthetic demo for a mortgage-renewal concierge that grounds answers across Microsoft Work IQ, Fabric analytics, and policy knowledge in Azure AI Foundry. The app is a browser + React UI backed by a FastAPI BFF that performs user-delegated OBO token exchange so Work IQ resolves as the signed-in user instead of the app identity.

## Read these first

- `README.md` — top-level overview, demo scope, and deployment flow.
- `docs/products/mortgage-iq/README.md` — living doc entry point and product summary.
- `app/README.md` — web app architecture, local setup, OBO flow, and troubleshooting.
- `infra/README.md` — Azure control-plane split, Bicep scope, and live-estate caveats.

## Build, test and run

Use the repo's documented local flow rather than inventing a new one.

```powershell
# root setup
cd mortgage-renewal - IQs
pip install -r requirements.txt
az login

# local agent smoke check
cd agent
python create_agent.py --local-smoke

# local BFF
cd ..\app\src\bff
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:AAD_TENANT_ID = "<tenant>"
$env:AAD_CLIENT_ID = "<bff-client-id>"
$env:AAD_CLIENT_SECRET = "<secret>"
$env:AAD_API_SCOPE = "api://<bff-client-id>/access_as_user"
$env:FOUNDRY_PROJECT_ENDPOINT = "https://mortgage-iqs.services.ai.azure.com/api/projects/proj-conceirge"
uvicorn app.main:app --reload --port 8000

# local SPA (second terminal)
cd ..\web
npm install
"VITE_AAD_TENANT_ID=<tenant>`nVITE_AAD_CLIENT_ID=<spa-client-id>`nVITE_API_SCOPE=api://<bff-client-id>/access_as_user" | Set-Content .env
npm run dev
```

For UI-only work without Azure, set `MOCK_MODE=true` in the BFF and skip the `VITE_*` values.

## Layout

- `agent/` — agent instructions, tool contract, and creation/smoke scripts.
- `data/work-iq/` — Graph seeding data and Work IQ provisioning scripts.
- `data/fabric-iq/` — synthetic mortgage/renewal datasets and Fabric deployment notebooks.
- `data/foundry-iq/` — policy corpus and Azure AI Search indexing assets.
- `app/src/bff/` — FastAPI backend and OBO/auth logic.
- `app/src/web/` — React/Vite/MSAL frontend.
- `infra/` — Bicep resources and Azure control-plane wiring.
- `docs/products/mortgage-iq/` — living documentation / product notes.
- `deploy.ps1` — end-to-end orchestration entry point (`-Bank "<name>"` brands the deployment).
- `tools/brand/` — `fetch_brand.py` (bank name → brand pack + `brands.json`) and `bank_profile.py` (deployed bank for Python scripts).
- `app/src/bff/app/pb_processor.py` + `data/fabric-iq/generate_processor_tables.py` — simulated card processor (system of record) for the Cards book; see `docs/card-processor-simulator.md`. Servicing actions always need preview → policy guards → named human approval.
- `app/src/bff/app/sor.py` — shared system-of-record framework (profiles, guarded actions, audit, event bus); `pb_servicing.py` + `generate_servicing_tables.py` add mortgage servicing; `data/fabric-iq/deploy_realtime.py` streams both through Fabric Eventstream; see `docs/systems-of-record.md`.
- `.github/workflows/` — `deploy.yml` ("Deploy for a bank", workflow_dispatch) and `ci.yml`.

## Conventions

- Treat all data as synthetic unless explicitly confirmed otherwise.
- Keep answer text and citations separate; do not splice citations into text strings.
- Use user-delegated identity for Work IQ and Fabric access rather than app-only access.
- Bicep covers Azure control plane only; Python scripts create the data-plane objects (Fabric, AI Search, M365 content, agent).
- Prefer repo docs and existing scripts over creating alternate deployment or architecture flows.
- The repo is bank-neutral: author copy for the fictional "CFC Bank" and never hard-code a real bank. The web app relabels it via `app/src/web/src/brand.ts`; scripts that push content (agent, Fabric, AI Search, Microsoft 365) must pass it through `bank_profile.rebrand()`.
- Only `app/src/web/public/brand/cfc/` is committed; real bank packs are fetched at deploy time and git-ignored.

## Land mines

- The repo is a demo and may still carry stale live-estate details or outdated resource names.
- The root README currently references a missing `mortgage-iq-app/README.md` path; verify before linking or citing it.
- Work IQ and Fabric access are identity-sensitive; changes to auth or OBO logic can silently break grounded answers.
- Agent behavior is defined by `agent/agent_instructions.md` and the BFF call flow; do not assume the Foundry playground behavior matches this app.
- CI (`.github/workflows/ci.yml`) covers the web build + `dashboard.test.mjs`, Python byte-compile, generator `--check`s, offline brand tooling and Bicep build; there is no formal API contract, so still smoke-test grounded answers manually.

## Don't

- Do not present synthetic CFC Bank data as real customer or policy data.
- Do not claim production readiness or current tenant ownership without checking the docs and live configuration.
- Do not edit generated ARM/Bicep artifacts or seeded data files casually; they are part of the demo flow.
- Do not assume the docs are fresh; confirm the live environment and resource names before relying on them.
