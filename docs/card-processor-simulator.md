# Card processor simulator - Cards book

A simulated **issuer card processor** (the system of record behind a bank's
cards - TSYS, Fiserv, Global Payments or an in-house platform) wired into the
Cards book. The Fabric card tables are monthly roll-ups. This feed shows what only
the processor knows, and turns it into insights and human-approved servicing
actions.

> Everything is synthetic. The vendor profiles shape labels and the API style only.
> The simulator is not connected to, affiliated with or endorsed by any processor.

## What it adds

| Where | What |
|---|---|
| Cards book · **System of record** section | The integration path (processor → API Management → OneLake → Fabric IQ → book and agents). It also shows the six files the processor delivered today, processor-only KPIs, declines by response code, an event stream, and the insights list |
| Accounts list | A **Processor signal** filter and flag. Accounts where the processor sees something the book has not are marked **New** |
| Card workspace · **Card processor** panel | Card status and controls, insights with servicing actions, 30 days of authorisations (filter: flagged, declined, online, cross-border), billers on file, disputes, and the activity log |
| Fabric IQ | Five new tables: `proc_authorizations`, `proc_card_controls`, `proc_card_on_file`, `proc_disputes` and `proc_feed_files`. Four of them are joined to `card_accounts` in the semantic model, which gains measures for approval rate, declines at the limit, suspected-fraud declines, open disputes and stopped billers |
| Foundry IQ | **RP-035** (card controls, locks and reissue: authority and evidence) and **RP-036** (disputes, chargebacks and card-on-file billers) |
| Agent | Instructions describe the `proc_*` tables. The agent may recommend an action but never takes one |

## Insights (deterministic, `app/src/bff/app/pb_processor.py`)

| Code | Signal | Play / policy | Action offered |
|---|---|---|---|
| `CARD_TESTING` | 3+ card-not-present attempts under $5 within an hour. Two accounts have **no fraud alert in the book yet** | Security check-in · RP-022, RP-035 | Lock · block and reissue · open fraud dispute |
| `DECLINES_AT_LIMIT` | 2+ declines with response 51 (insufficient funds) | Persistent-debt support · RP-021 (never a limit increase, RP-020) | None |
| `BILLERS_STOPPED` | Recurring merchants on file stopped billing | Spend decline · RP-019, RP-011 | None |
| `EXPIRY_BILLERS` | Card expires within 60 days, billers on file, Account Updater off | RP-036 | Push new details to billers |
| `FX_FEES` | 2.5% FX fees on cross-border spend (suppressed for support-first clients) | Upgrade fit: travel · RP-019 | None |
| `DISPUTE_DUE` | Open dispute within 10 days of its deadline | RP-036 | None |
| `ALERTS_OFF` | Fraud signal and real-time alerts not enrolled | RP-022 | Enrol alerts |

## Servicing actions (simulated vendor API)

`POST /api/cards/account/{id}/processor/action`

1. **Preview** (`execute: false`). Returns the vendor-style request (method, URL, headers, body), the policy guards and their verdict.
2. **Execute** (`execute: true, confirm: true`). Policy guards must pass. The approver is the **signed-in user**, taken from the token and never from the client. The call returns a vendor-style response with a reference, raises an event on the stream, and records the change in the account's activity log and in the BFF audit log.

`POST /api/cards/processor/reset` clears simulated state between demos. State lives in memory in the BFF, so a restart also resets it.

## Vendor profile

`CARD_PROCESSOR` = `generic` (default) | `tsys` | `fiserv` | `globalpayments`. Set it with:

- `app\deploy.ps1 -CardProcessor fiserv`
- the `card_processor` input of the *Deploy for a bank* workflow
- the `cardProcessor` Bicep parameter

The profile changes the name, the API base path and the labels. The data stays the same.

## Data

`data/fabric-iq/generate_processor_tables.py` is deterministic: it uses no randomness and no clock. Run it with `--check` in CI. It derives every scenario from the card tables:

- fraud alerts → card-testing bursts and fraud declines
- persistent debt → declines at the limit
- spend decline → stopped billers
- foreign spend → cross-border authorisations and FX fees

It writes the CSVs and `app/src/bff/app/processor_data.py`. Dates use the same evergreen base (2026-08-03) as the rest of the demo.

## Demo script

1. Open **Cards**. The *Card testing* KPI reads "2 not flagged in the book".
2. Click *Card-testing pattern the book has not flagged*.
3. In the workspace, select *Temporarily lock the card…*.
4. Show the request, then the RP-035 guards.
5. Tick the approval box and choose *Approve and send*.
6. Show the 200 response and its reference, the `card.status.changed` event and the activity log.
7. Open a fraud dispute for the approved test charges.
8. Block and reissue the card. Account Updater pushes the new card number to the billers on file.

## Live stream - Fabric Eventstream → Eventhouse

The daily files above are batch. Authorisations also stream in real time:

```
stream_processor_events.py  (the processor, simulated)
   └─► Eventstream es_card_processor      custom endpoint, Event Hubs protocol
         └─► Eventhouse eh_card_processor  KQL table auth_stream (JSON mapping auth_json)
               ├─ KQL functions: LiveAuthKpis · CardTestingLive · DeclinesAtLimitLive · RecentAuths
               ├─ OneLake availability → Lakehouse shortcut proc_auth_stream
               │     └─ semantic model (Live Authorisations 24h, Live Fraud Declines 24h,
               │        Live Card Testing Attempts 1h) → the agents' Fabric IQ tool
               └─ BFF /api/cards/processor/live (managed identity, workspace Viewer)
                     └─ Cards book: live panel (10 s refresh) + per-card live feed
```

Set up (idempotent) and stream:

```powershell
python data/fabric-iq/deploy_realtime.py                                   # or: .\deploy.ps1 -Only realtime
python data/fabric-iq/deploy_realtime.py --grant-principal <BFF managed identity object id>
python data/fabric-iq/stream_processor_events.py --replay --minutes 10 --rate 3          # background traffic
python data/fabric-iq/stream_processor_events.py --scenario card-testing --account CA-2009
python data/fabric-iq/stream_processor_events.py --scenario declines-at-limit --account CA-1010
python data/fabric-iq/deploy_realtime.py --status
```

`deploy_realtime.py` writes `data/fabric-iq/.env.realtime`, which is git-ignored because it holds the Eventstream send key. `app\deploy.ps1` reads `PROCESSOR_KQL_URI` and `PROCESSOR_KQL_DB` from that file. To change the settings on a running app, update the BFF container app with `az containerapp update --set-env-vars PROCESSOR_KQL_URI=… PROCESSOR_KQL_DB=…`.

After the first events arrive, re-run `deploy_fabric.py --only semantic-model` once. The model picks up the `proc_auth_stream` shortcut and its live measures automatically. Without the stream configured, the live panel shows "not connected" and everything else works as before.

Live demo moment:

1. Run the card-testing scenario for **CA-2009**, an account with no fraud alert in the card book.
2. Within seconds it appears in the Cards live panel and in the card's own live feed, with an in-progress banner.
3. Ask the concierge: *"Which cards show a card-testing pattern in the live stream in the last hour, and is any not flagged in the card book?"* It answers from `proc_auth_stream`, notes the missing fraud alert, and recommends a temporary lock under RP-035 with named approval.
4. Lock the card in the workspace.

Cost: the Eventhouse and the Eventstream consume Fabric capacity units while they run. Pause the capacity after a demo.

## Moving to a real processor

Put API Management in front of the vendor's sandbox or production APIs and point `pb_processor._request` at it, keeping the preview, guards and approval steps. Land the vendor's daily files in `OneLake Files/processor/*`, using Data Factory or a shortcut. Point the vendor's authorisation or fraud-score webhook (or its Kafka / Event Hubs feed) at the same Eventstream source in place of `stream_processor_events.py`. The tables, KQL functions, insights and UI stay the same.
