# Systems of record - mortgage servicing (and the shared framework)

The demo connects each product book to the **line-of-business system behind it**. The systems are simulated, and the integration is done with real Microsoft tooling. Two systems are live today:

| Book | System of record | Docs |
|---|---|---|
| Cards | Issuer card processor (TSYS-, Fiserv- or Global Payments-style) | [card-processor-simulator.md](card-processor-simulator.md) |
| Mortgage renewals | Mortgage servicing platform, origination channel, credit-bureau triggers | this page |

> Everything is synthetic. Vendor profiles change labels and the API shape only. No system is connected to, affiliated with or endorsed by any vendor.

## Shared framework - `app/src/bff/app/sor.py`

Every system plugs into one base class, `SystemOfRecord`, and gets the same behaviour:

- **Vendor profile.** Chosen at deploy time; it changes labels and the API base only.
- **Guarded actions.** Each action follows the same steps:
  1. Preview the vendor-style request together with its policy guards.
  2. Execute only if every guard passes.
  3. Require a named human approver. The approver is the signed-in user, never a value sent by the client.
- **Audit log.** One per record: request, response, approver, reason and reference.
- **Event bus.** A single stream across systems, so a household's card events and mortgage events can be read together.

To add a system, implement four methods: `request`, `guards`, `apply` and `profile`. Then add a generator under `data/fabric-iq/` and an entry in `STREAMS` in `deploy_realtime.py`.

## Mortgage servicing

### What it knows that the renewal book does not

| Insight | Source table | Policy | Action offered |
|---|---|---|---|
| **Payout statement requested.** Another lender's lawyer has asked for a discharge figure, so the client is leaving. Two clients the attrition model scores *Medium* with no shopping signal are flagged **new to the book**. | `svc_payout_requests` | RP-037 · RP-002 | Route the payout request to retention · send a retention offer |
| **Shopping.** Other lenders have run hard inquiries. Only shown where the client gave **bureau-trigger consent**; otherwise withheld. | `svc_bureau_inquiries` | RP-038 · RP-002 | Rate hold · retention offer |
| **Rate hold expiring** within 10 days | `svc_renewal_offers` | RP-002 | Extend the hold |
| **Renewal offer not opened** 5 or more days after it was sent | `svc_renewal_offers` | RP-016 | Resend for e-signature through another channel, in the client's language |
| **Returned payments.** NSF pre-authorised debits in the last 3 months. Treated as a support signal only. | `svc_payment_history` | RP-014 · RP-012 | Request a 2-month payment deferral (Branch Manager) |
| **Prepayment surge.** 4% or more of the balance paid down just before maturity. | `svc_payment_history` | RP-002 | Rate hold |

### Guards that always apply

- **RP-037.** The payout statement is never delayed. A retention review has to fit inside the statement window.
- **RP-012.** A client in the Vulnerable band cannot be sent a retention offer; the hardship conversation comes first.
- **RP-002.** Which approver is needed is decided by the stricter of the RP-002 discount matrix and the offer's own approval level:
  - up to 20 bps: Advisor
  - 21-25 bps: Branch Manager
  - 26 bps or more: Pricing Committee
  - Amortization relief: Credit Risk, plus a TDS/GDS re-test (it is not a straight renewal under RP-004)
- **RP-038.** Bureau triggers are used only with consent, and outreach never reveals the source.

### Where it shows

- **Mortgage → Customers.** A *System of record · mortgage servicing* section with:
  - the integration path and the servicing feeds
  - processor-only KPIs and an insights list
  - an event stream and a live Eventstream panel
  - a *Servicing signal* filter on the customer list
- **Customer workspace → Mortgage servicing panel.**
  - Offer and rate-hold status, payout requests, lender inquiries (consented only) and 12 months of payments.
  - Insights with guarded actions and the activity log.
  - The client's live events. Live payout and shopping signals are merged into the insights and labelled **live**.

### Live stream

`stream_servicing_events.py` → Eventstream `es_mortgage_servicing` → Eventhouse table `svc_stream`.

- **KQL functions:**
  - `ServicingKpis`
  - `PayoutRequestsLive`
  - `ShoppingSignalsLive` (consented inquiries only)
  - `PadReturnsLive`
  - `RecentServicingEvents`
- **Into the agents:** OneLake availability exposes the stream as the Lakehouse shortcut `svc_event_stream`. That table carries the live measures *Live Payout Requests 7d* and *Live Lender Inquiries 14d* in the semantic model, which the agents use.
- **Into the app:** `/api/mortgage/servicing/live`, using the BFF's managed identity.

```powershell
python data/fabric-iq/deploy_realtime.py                                        # both streams (or --only mortgage)
python data/fabric-iq/stream_servicing_events.py --scenario payout-request --customer CUST-1006
python data/fabric-iq/stream_servicing_events.py --scenario shopping --customer CUST-1006
python data/fabric-iq/stream_servicing_events.py --scenario pad-returned --customer CUST-1016
python data/fabric-iq/stream_servicing_events.py --replay --minutes 5 --rate 1
```

### Demo script

1. Open **Mortgage → Customers**.
2. Stream `--scenario payout-request --customer CUST-1006`. CUST-1006 is a *Thriving* client the model scores *Medium* with no shopping signal.
3. Within seconds the live panel shows the payout request. The insights list now starts with *Payout statement requested - live (the attrition model has not flagged this client)*.
4. Open the client and choose **Send a retention offer**. The preview shows the RP-002 approver and whether the client must re-qualify.
5. Approve it. You get a vendor-style `202 PENDING_APPROVAL` response, a `retention.offer` event and an audit entry.
6. Ask the concierge: *"Who is leaving this week that the attrition model has not flagged, and what may I offer them?"* It answers from `svc_event_stream` and `svc_payout_requests` and applies RP-037 and RP-002.

### Agents

- The concierge (`agent/update_concierge.py`) and the mission agent (`agent/pb_agents.md`) know the `svc_*` tables, the live stream and policies RP-037 and RP-038.
- They recommend actions and never claim to have taken them.

### Configuration

| Setting | Values |
|---|---|
| `MORTGAGE_SERVICER` (BFF) | `generic`, `msp`, `fis` or `inhouse`. Set it with `app\deploy.ps1 -MortgageServicer` or the Bicep parameter `mortgageServicer`. |
| `PROCESSOR_KQL_URI`, `PROCESSOR_KQL_DB` | The shared Eventhouse used by both streams. Written to `.env.realtime` by `deploy_realtime.py`. |

### Data

`data/fabric-iq/generate_servicing_tables.py` is deterministic and has a `--check` mode, which CI runs. It derives its rows from the renewal tables:

- high attrition with a shopping signal produces payout requests and bureau inquiries
- the Vulnerable and Stretched wellness bands produce returned payments
- high attrition near maturity produces prepayments

It writes:

- `svc_payment_history`
- `svc_payout_requests`
- `svc_bureau_inquiries`
- `svc_renewal_offers`
- `svc_feed_files`
- `app/src/bff/app/servicing_data.py`
