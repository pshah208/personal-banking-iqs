"""Stream simulated card-processor authorisations into the Fabric Eventstream.

Plays the issuer processor: sends authorisation events (JSON, the auth_stream
schema) to the Eventstream custom endpoint created by deploy_realtime.py, so the
Eventhouse, the KQL insight functions, the Cards book live panel and the agents
see them within seconds.

    # steady background traffic from the synthetic book (all 60 accounts)
    python stream_processor_events.py --replay --minutes 10 --rate 3

    # demo moments, stamped "now"
    python stream_processor_events.py --scenario card-testing --account CA-2009
    python stream_processor_events.py --scenario declines-at-limit --account CA-1010

    # no Eventstream yet? ingest straight into the KQL table instead
    python stream_processor_events.py --scenario card-testing --account CA-2009 --direct

Reads EVENTSTREAM_CONNECTION / EVENTSTREAM_HUB / PROCESSOR_KQL_URI / PROCESSOR_KQL_DB
from the environment or data/fabric-iq/.env.realtime. SYNTHETIC data only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
ENV_FILE = HERE / ".env.realtime"
FIELDS = ["event_ts", "auth_id", "account_id", "card_token", "merchant_name", "mcc", "mcc_desc", "merchant_country",
          "txn_currency", "amount_cad", "pos_entry_mode", "channel", "wallet", "recurring", "three_ds", "response_code",
          "response_text", "decision", "risk_score", "fx_fee_cad", "scenario", "source"]
TESTERS = [("DIGITAL GOODS LTD", "GB", "5818"), ("GIFTCARD ONLINE*", "US", "5999"), ("APP CREDITS BV", "NL", "5816"),
           ("GAME TOKENS INC", "US", "5816")]
EVERYDAY = [("FreshMart Grocery", "5411", "Grocery stores"), ("TransCanada Fuel", "5541", "Service stations"),
            ("Hardware Depot", "5200", "Home supply")]


def env(name: str) -> str:
    if os.getenv(name):
        return os.environ[name]
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return ""


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def token_for(aid: str) -> str:
    return "tok_" + hashlib.sha256(f"{aid}|tok".encode()).hexdigest()[:8]


def event(aid: str, *, merchant: str, mcc: str, desc: str, country: str = "CA", currency: str = "CAD", amount: float,
          entry: str = "contactless", code: str = "00", risk: int = 120, recurring: str = "N", three_ds: str = "NA",
          scenario: str = "replay", ts: datetime | None = None) -> dict:
    text = {"00": "Approved", "05": "Do not honour", "51": "Insufficient funds / over limit", "59": "Suspected fraud"}[code]
    seq = hashlib.sha256(f"{aid}{merchant}{amount}{time.time_ns()}".encode()).hexdigest()[:8].upper()
    return {
        "event_ts": iso(ts or now()), "auth_id": f"LIV-{seq}", "account_id": aid, "card_token": token_for(aid),
        "merchant_name": merchant, "mcc": mcc, "mcc_desc": desc, "merchant_country": country, "txn_currency": currency,
        "amount_cad": round(amount, 2), "pos_entry_mode": entry, "channel": "CNP" if entry in ("ecommerce", "card_on_file") else "CP",
        "wallet": "", "recurring": recurring, "three_ds": three_ds, "response_code": code, "response_text": text,
        "decision": "Approved" if code == "00" else "Declined", "risk_score": risk,
        "fx_fee_cad": round(amount * 0.025, 2) if country != "CA" and code == "00" else 0.0,
        "scenario": scenario, "source": "processor-simulator",
    }


def card_testing(aid: str) -> list[dict]:
    t0 = now()
    out = []
    for i in range(5):
        name, country, mcc = TESTERS[i % len(TESTERS)]
        caught = i >= 3
        out.append(event(aid, merchant=name, mcc=mcc, desc="Digital goods (card-not-present)", country=country, currency="USD",
                         amount=0.5 + 4.2 * random.random(), entry="ecommerce", code="59" if caught else "00",
                         risk=900 + 15 * i if caught else 620 + 35 * i, three_ds="N", scenario="card-testing",
                         ts=t0 + timedelta(seconds=40 * i)))
    out.append(event(aid, merchant="ByteBox Electronics US", mcc="5732", desc="Electronics (card-not-present)", country="US",
                     currency="USD", amount=480 + 200 * random.random(), entry="ecommerce", code="59", risk=968, three_ds="N",
                     scenario="card-testing", ts=t0 + timedelta(seconds=240)))
    return out


def declines_at_limit(aid: str) -> list[dict]:
    t0 = now()
    return [event(aid, merchant=m, mcc=mcc, desc=d, amount=40 + 120 * random.random(), entry="chip", code="51", risk=110,
                  scenario="declines-at-limit", ts=t0 + timedelta(minutes=3 * i)) for i, (m, mcc, d) in enumerate(EVERYDAY)]


def replay_rows() -> list[dict]:
    with (HERE / "proc_authorizations.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: r["auth_ts"])
    return rows


def from_row(r: dict) -> dict:
    e = event(r["account_id"], merchant=r["merchant_name"], mcc=r["mcc"], desc=r["mcc_desc"], country=r["merchant_country"],
              currency=r["txn_currency"], amount=float(r["amount_cad"]), entry=r["pos_entry_mode"], code=r["response_code"]
              if r["response_code"] in ("00", "05", "51", "59") else "00", risk=int(r["risk_score"]), recurring=r["recurring"],
              three_ds=r["three_ds"], scenario="replay")
    e["wallet"] = r["wallet"]
    return e


# --------------------------------------------------------------------------- #
def send_eventstream(events: list[dict]) -> None:
    conn = env("EVENTSTREAM_CONNECTION")
    if not conn:
        sys.exit("EVENTSTREAM_CONNECTION not set - run deploy_realtime.py first, or use --direct")
    try:
        from azure.eventhub import EventData, EventHubProducerClient
    except ImportError:
        sys.exit("pip install azure-eventhub")
    hub = env("EVENTSTREAM_HUB") or None
    with EventHubProducerClient.from_connection_string(conn, eventhub_name=hub) as producer:
        batch = producer.create_batch()
        for e in events:
            data = EventData(json.dumps(e))
            try:
                batch.add(data)
            except ValueError:
                producer.send_batch(batch)
                batch = producer.create_batch()
                batch.add(data)
        producer.send_batch(batch)


def send_direct(events: list[dict]) -> None:
    import subprocess

    import requests

    uri, db = env("PROCESSOR_KQL_URI"), env("PROCESSOR_KQL_DB")
    if not (uri and db):
        sys.exit("PROCESSOR_KQL_URI / PROCESSOR_KQL_DB not set - run deploy_realtime.py first")
    tok = subprocess.run(["az", "account", "get-access-token", "--resource", uri, "--query", "accessToken", "-o", "tsv"],
                         capture_output=True, text=True, shell=True).stdout.strip()
    body = "\n".join(json.dumps(e) for e in events)
    csl = f".ingest inline into table auth_stream with (format='multijson', ingestionMappingReference='auth_json') <|\n{body}"
    r = requests.post(f"{uri}/v1/rest/mgmt", headers={"Authorization": f"Bearer {tok}"}, json={"db": db, "csl": csl}, timeout=120)
    if r.status_code != 200:
        sys.exit(f"direct ingest -> {r.status_code}: {r.text[:400]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulated card processor -> Fabric Eventstream")
    ap.add_argument("--scenario", choices=["card-testing", "declines-at-limit"])
    ap.add_argument("--account", default="CA-2009")
    ap.add_argument("--replay", action="store_true", help="replay the synthetic book's authorisations as live traffic")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--rate", type=float, default=3, help="events per second during --replay")
    ap.add_argument("--direct", action="store_true", help="ingest into the KQL table directly instead of the Eventstream")
    args = ap.parse_args()
    send = send_direct if args.direct else send_eventstream

    if args.scenario:
        events = card_testing(args.account) if args.scenario == "card-testing" else declines_at_limit(args.account)
        send(events)
        print(f"sent {len(events)} {args.scenario} events for {args.account} via {'KQL' if args.direct else 'Eventstream'}")
        return 0
    if args.replay:
        rows = replay_rows()
        end = time.time() + args.minutes * 60
        i, sent = 0, 0
        while time.time() < end:
            chunk = [from_row(rows[(i + k) % len(rows)]) for k in range(max(1, int(args.rate * 5)))]
            i += len(chunk)
            send(chunk)
            sent += len(chunk)
            print(f"  {sent} events sent", end="\r")
            time.sleep(5)
        print(f"\nreplayed {sent} events in {args.minutes} min")
        return 0
    ap.error("choose --scenario or --replay")
    return 2


if __name__ == "__main__":
    sys.exit(main())
