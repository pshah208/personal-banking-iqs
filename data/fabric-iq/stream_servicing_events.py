"""Stream simulated mortgage-servicing events into the Fabric Eventstream.

Plays the lender's servicing platform and bureau-trigger service: sends events
(JSON, the svc_stream schema) to the es_mortgage_servicing custom endpoint that
deploy_realtime.py created. The Eventhouse KQL functions (PayoutRequestsLive,
ShoppingSignalsLive, PadReturnsLive), the renewal book's live panel and the
agents see them within seconds.

    # background traffic replayed from the synthetic servicing tables
    python stream_servicing_events.py --replay --minutes 5 --rate 1

    # demo moments, stamped "now"
    python stream_servicing_events.py --scenario payout-request --customer CUST-1006
    python stream_servicing_events.py --scenario shopping --customer CUST-1006
    python stream_servicing_events.py --scenario pad-returned --customer CUST-1016

    # no Eventstream yet? ingest straight into the KQL table
    python stream_servicing_events.py --scenario payout-request --customer CUST-1006 --direct

Reads SERVICING_EVENTSTREAM_CONNECTION / SERVICING_EVENTSTREAM_HUB / PROCESSOR_KQL_URI /
PROCESSOR_KQL_DB from the environment or data/fabric-iq/.env.realtime. SYNTHETIC data only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stream_processor_events import env, iso

HERE = Path(__file__).parent
LAWYERS = ["Harbourfront Law LLP", "Côté & Lam Notaires", "Lakeshore Real Estate Law"]
LENDERS = [("Northstar Mortgage Co", "Monoline lender"), ("Maple Digital Bank", "Digital bank"),
           ("RateWise Mortgage Brokers", "Mortgage broker")]


def renewals() -> dict[str, dict]:
    with (HERE / "mortgage_renewals.csv").open(encoding="utf-8") as f:
        return {r["customer_id"]: r for r in csv.DictReader(f)}


def ev(kind: str, cid: str, rid: str, *, amount: float = 0.0, counterparty: str = "", ctype: str = "", detail: str = "",
       consent: str = "Y", scenario: str = "replay", ts: datetime | None = None) -> dict:
    seq = hashlib.sha256(f"{cid}{kind}{time.time_ns()}".encode()).hexdigest()[:8].upper()
    return {"event_ts": iso(ts or datetime.now(timezone.utc)), "event_id": f"SVE-{seq}", "event_type": kind, "renewal_id": rid,
            "customer_id": cid, "amount_cad": round(amount, 2), "counterparty": counterparty, "counterparty_type": ctype,
            "detail": detail, "trigger_consent": consent, "scenario": scenario, "source": "servicing-simulator"}


def scenario(name: str, cid: str) -> list[dict]:
    r = renewals().get(cid) or sys.exit(f"no renewal for {cid}")
    rid, bal = r["renewal_id"], float(r["mortgage_balance_cad"])
    t0 = datetime.now(timezone.utc)
    pick = int(hashlib.sha256(cid.encode()).hexdigest(), 16)
    if name == "payout-request":
        return [ev("bureau.inquiry", cid, rid, counterparty=LENDERS[pick % 3][0], ctype=LENDERS[pick % 3][1],
                   detail="Hard - mortgage", scenario=name, ts=t0 - timedelta(days=6)),
                ev("payout.requested", cid, rid, amount=round(bal * 0.995, -2), counterparty=LAWYERS[pick % 3],
                   ctype="Lawyer / notary", detail="Discharge - transfer to another lender", scenario=name, ts=t0)]
    if name == "shopping":
        return [ev("bureau.inquiry", cid, rid, counterparty=LENDERS[(pick + i) % 3][0], ctype=LENDERS[(pick + i) % 3][1],
                   detail="Hard - mortgage", scenario=name, ts=t0 - timedelta(hours=30 * i)) for i in range(2)]
    if name == "pad-returned":
        return [ev("pad.returned", cid, rid, amount=round(bal * 0.0055, 2), detail="PAD returned NSF", scenario=name, ts=t0)]
    return [ev("offer.opened", cid, rid, detail="Renewal offer opened in client portal", scenario=name, ts=t0)]


def replay_events() -> list[dict]:
    out = []
    for name, kind in (("svc_payout_requests.csv", "payout.requested"), ("svc_bureau_inquiries.csv", "bureau.inquiry"),
                       ("svc_payment_history.csv", "pad.returned"), ("svc_renewal_offers.csv", "offer.opened")):
        with (HERE / name).open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if kind == "payout.requested":
                    out.append(ev(kind, r["customer_id"], r["renewal_id"], amount=float(r["payout_amount_cad"]),
                                  counterparty=r["requested_by"], ctype="Lawyer / notary", detail=r["purpose"]))
                elif kind == "bureau.inquiry":
                    out.append(ev(kind, r["customer_id"], r["renewal_id"], counterparty=r["inquirer"], ctype=r["inquirer_type"],
                                  detail=r["inquiry_kind"], consent=r["trigger_consent"]))
                elif kind == "pad.returned" and r["status"].startswith("Returned"):
                    out.append(ev(kind, r["customer_id"], r["renewal_id"], amount=float(r["scheduled_cad"]), detail="PAD returned NSF"))
                elif kind == "offer.opened" and r["opened"] == "Y":
                    out.append(ev(kind, r["customer_id"], r["renewal_id"], detail=f"Renewal offer opened ({r['channel']})"))
    return out


def send_eventstream(events: list[dict]) -> None:
    conn = env("SERVICING_EVENTSTREAM_CONNECTION")
    if not conn:
        sys.exit("SERVICING_EVENTSTREAM_CONNECTION not set - run deploy_realtime.py first, or use --direct")
    from azure.eventhub import EventData, EventHubProducerClient

    with EventHubProducerClient.from_connection_string(conn, eventhub_name=env("SERVICING_EVENTSTREAM_HUB") or None) as p:
        batch = p.create_batch()
        for e in events:
            batch.add(EventData(json.dumps(e)))
        p.send_batch(batch)


def send_direct(events: list[dict]) -> None:
    import requests

    uri, db = env("PROCESSOR_KQL_URI"), env("PROCESSOR_KQL_DB")
    tok = subprocess.run(["az", "account", "get-access-token", "--resource", uri, "--query", "accessToken", "-o", "tsv"],
                         capture_output=True, text=True, shell=True).stdout.strip()
    body = "\n".join(json.dumps(e) for e in events)
    csl = f".ingest inline into table svc_stream with (format='multijson', ingestionMappingReference='svc_json') <|\n{body}"
    r = requests.post(f"{uri}/v1/rest/mgmt", headers={"Authorization": f"Bearer {tok}"}, json={"db": db, "csl": csl}, timeout=120)
    if r.status_code != 200:
        sys.exit(f"direct ingest -> {r.status_code}: {r.text[:400]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulated mortgage servicing -> Fabric Eventstream")
    ap.add_argument("--scenario", choices=["payout-request", "shopping", "pad-returned", "offer-opened"])
    ap.add_argument("--customer", default="CUST-1006")
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--minutes", type=float, default=2)
    ap.add_argument("--rate", type=float, default=1, help="events per second during --replay")
    ap.add_argument("--direct", action="store_true")
    args = ap.parse_args()
    send = send_direct if args.direct else send_eventstream
    if args.scenario:
        events = scenario(args.scenario, args.customer)
        send(events)
        print(f"sent {len(events)} {args.scenario} events for {args.customer} via {'KQL' if args.direct else 'Eventstream'}")
        return 0
    if args.replay:
        rows, i, sent = replay_events(), 0, 0
        end = time.time() + args.minutes * 60
        while time.time() < end:
            chunk = [dict(rows[(i + k) % len(rows)], event_ts=iso(datetime.now(timezone.utc))) for k in range(max(1, int(args.rate * 5)))]
            i += len(chunk)
            send(chunk)
            sent += len(chunk)
            time.sleep(5)
        print(f"replayed {sent} servicing events in {args.minutes} min")
        return 0
    ap.error("choose --scenario or --replay")
    return 2


if __name__ == "__main__":
    sys.exit(main())
