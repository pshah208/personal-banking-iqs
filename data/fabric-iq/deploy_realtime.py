"""Real-time card processor feed: Fabric Eventstream -> Eventhouse -> insights.

Builds the streaming path for the simulated issuer processor in the Fabric
workspace that deploy_fabric.py created:

    processor (simulator: stream_processor_events.py)
        -> Eventstream  es_card_processor   custom endpoint (Event Hubs protocol)
        -> Eventhouse   eh_card_processor   KQL table auth_stream (+ JSON mapping)
        -> KQL functions LiveAuthKpis, CardTestingLive, DeclinesAtLimitLive, RecentAuths
        -> OneLake availability -> Lakehouse shortcut proc_auth_stream
           (so the semantic model, and the agents' Fabric IQ tool, see the stream)
        -> BFF /api/cards/processor/live (Cards book live panel)

    python deploy_realtime.py                        # create / update everything
    python deploy_realtime.py --grant-principal <object-id>   # let the BFF identity read the KQL DB
    python deploy_realtime.py --status

Idempotent. Writes the Eventstream custom-endpoint connection and the KQL URI to
data/fabric-iq/.env.realtime (git-ignored: it holds a send key). SYNTHETIC data.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

from deploy_fabric import fab, get_item, get_workspace, token, LAKEHOUSE  # noqa: F401 - shared Fabric client

HERE = Path(__file__).parent
EVENTHOUSE = "eh_card_processor"
EVENTSTREAM = "es_card_processor"
SOURCE = "CardProcessorFeed"
TABLE = "auth_stream"
MAPPING = "auth_json"
SHORTCUT = "proc_auth_stream"
ENV_FILE = HERE / ".env.realtime"

COLUMNS = [
    ("event_ts", "datetime"), ("auth_id", "string"), ("account_id", "string"), ("card_token", "string"),
    ("merchant_name", "string"), ("mcc", "string"), ("mcc_desc", "string"), ("merchant_country", "string"),
    ("txn_currency", "string"), ("amount_cad", "real"), ("pos_entry_mode", "string"), ("channel", "string"),
    ("wallet", "string"), ("recurring", "string"), ("three_ds", "string"), ("response_code", "string"),
    ("response_text", "string"), ("decision", "string"), ("risk_score", "int"), ("fx_fee_cad", "real"),
    ("scenario", "string"), ("source", "string"),
]

KQL_SETUP = [
    f".create-merge table {TABLE} (" + ", ".join(f"{c}:{t}" for c, t in COLUMNS) + ")",
    f".create-or-alter table {TABLE} ingestion json mapping '{MAPPING}' '"
    + json.dumps([{"column": c, "path": f"$.{c}", "datatype": t} for c, t in COLUMNS]) + "'",
    f".alter-merge table {TABLE} policy retention softdelete = 30d",
    f".alter table {TABLE} policy streamingingestion enable",
    # OneLake availability: the table is mirrored to Delta so a Lakehouse shortcut can read it.
    f".alter-merge table {TABLE} policy mirroring dataformat=parquet with (IsEnabled=true)",
    """.create-or-alter function with (folder="cards", docstring="Live authorisation KPIs over a look-back window")
LiveAuthKpis(lookback:timespan=15m) {
    auth_stream
    | where event_ts > ago(lookback)
    | summarize events=count(), approved=countif(decision == "Approved"), declined=countif(decision == "Declined"),
                cnp=countif(channel == "CNP"), cross_border=countif(merchant_country != "CA"),
                fraud_declines=countif(response_code == "59"), limit_declines=countif(response_code == "51"),
                amount_cad=round(sum(amount_cad), 2), accounts=dcount(account_id), last_event=max(event_ts)
    | extend approval_rate=round(100.0 * approved / iff(events == 0, 1, events), 1),
             cnp_share=round(100.0 * cnp / iff(events == 0, 1, events), 1)
}""",
    """.create-or-alter function with (folder="cards", docstring="Card testing: 3+ card-not-present attempts under $5 within an hour (RP-035)")
CardTestingLive(lookback:timespan=60m) {
    auth_stream
    | where event_ts > ago(lookback) and channel == "CNP" and amount_cad < 5 and recurring == "N"
    | summarize attempts=count(), approved=countif(decision == "Approved"), merchants=dcount(merchant_name),
                countries=make_set(merchant_country), first_seen=min(event_ts), last_seen=max(event_ts),
                max_risk=max(risk_score), auth_ids=make_list(auth_id, 20) by account_id
    | where attempts >= 3 and last_seen - first_seen <= 1h
    | order by last_seen desc
}""",
    """.create-or-alter function with (folder="cards", docstring="Repeated insufficient-funds declines - support, never a limit increase (RP-021)")
DeclinesAtLimitLive(lookback:timespan=24h) {
    auth_stream
    | where event_ts > ago(lookback) and response_code == "51"
    | summarize declines=count(), amount_cad=round(sum(amount_cad), 2), last_seen=max(event_ts) by account_id
    | where declines >= 2
    | order by last_seen desc
}""",
    """.create-or-alter function with (folder="cards", docstring="Most recent authorisations, optionally for one account")
RecentAuths(n:int=25, account:string="") {
    auth_stream
    | where isempty(account) or account_id == account
    | top n by event_ts desc
}""",
]


def b64(obj) -> str:
    return base64.b64encode(json.dumps(obj, indent=2).encode()).decode()


# --------------------------------------------------------------------------- #
# Eventhouse + KQL database
# --------------------------------------------------------------------------- #
def ensure_eventhouse(ws_id: str) -> tuple[dict, dict]:
    eh = get_item(ws_id, EVENTHOUSE, "Eventhouse")
    if not eh:
        fab.call("POST", f"/workspaces/{ws_id}/eventhouses",
                 json_body={"displayName": EVENTHOUSE, "description": "SYNTHETIC - simulated card processor stream."})
        for _ in range(30):
            time.sleep(4)
            eh = get_item(ws_id, EVENTHOUSE, "Eventhouse")
            if eh:
                break
        print(f"+ eventhouse {EVENTHOUSE} ({eh['id']})")
    else:
        print(f"= eventhouse {EVENTHOUSE} ({eh['id']})")
    db = None
    for _ in range(30):
        db = get_item(ws_id, EVENTHOUSE, "KQLDatabase")
        if db:
            break
        time.sleep(4)
    if not db:
        sys.exit("the eventhouse's default KQL database did not appear")
    detail = fab.call("GET", f"/workspaces/{ws_id}/kqlDatabases/{db['id']}")
    print(f"  kql database {detail['displayName']} ({db['id']}) {detail['properties']['queryServiceUri']}")
    return eh, detail


def kusto(uri: str, db: str, csl: str, *, mgmt: bool = True) -> dict:
    path = "/v1/rest/mgmt" if mgmt else "/v2/rest/query"
    last = None
    for resource in (uri, "https://kusto.kusto.windows.net"):
        r = requests.post(uri + path, headers={"Authorization": f"Bearer {token(resource)}", "Content-Type": "application/json"},
                          json={"db": db, "csl": csl}, timeout=120)
        if r.status_code == 200:
            return r.json()
        last = r
        if r.status_code not in (401, 403):
            break
    raise RuntimeError(f"KQL {'mgmt' if mgmt else 'query'} -> {last.status_code}: {last.text[:600]}\n{csl[:200]}")


def setup_kql(uri: str, db: str) -> None:
    for cmd in KQL_SETUP:
        head = cmd.splitlines()[0][:90]
        try:
            kusto(uri, db, cmd)
            print(f"  kql: {head}")
        except RuntimeError as e:
            if "mirroring" in cmd:
                print(f"  ! OneLake availability not enabled ({str(e).splitlines()[0][:160]}) - enable it on the database in the portal")
            else:
                raise


# --------------------------------------------------------------------------- #
# Eventstream: custom endpoint -> Eventhouse
# --------------------------------------------------------------------------- #
def eventstream_definition(ws_id: str, db: dict) -> dict:
    stream = f"{EVENTSTREAM}-stream"
    topology = {
        "sources": [{"name": SOURCE, "type": "CustomEndpoint", "properties": {}}],
        "destinations": [{
            "name": "AuthStreamEventhouse", "type": "Eventhouse",
            "properties": {"dataIngestionMode": "ProcessedIngestion", "workspaceId": ws_id, "itemId": db["id"],
                           "databaseName": db["displayName"], "tableName": TABLE,
                           "inputSerialization": {"type": "Json", "properties": {"encoding": "UTF8"}}},
            "inputNodes": [{"name": stream}],
        }],
        "streams": [{"name": stream, "type": "DefaultStream", "properties": {}, "inputNodes": [{"name": SOURCE}]}],
        "operators": [],
        "compatibilityLevel": "1.0",
    }
    return {"parts": [
        {"path": "eventstream.json", "payload": b64(topology), "payloadType": "InlineBase64"},
        {"path": "eventstreamProperties.json", "payload": b64({"retentionTimeInDays": 1, "eventThroughputLevel": "Low"}),
         "payloadType": "InlineBase64"},
    ]}


def ensure_eventstream(ws_id: str, db: dict) -> dict:
    es = get_item(ws_id, EVENTSTREAM, "Eventstream")
    definition = eventstream_definition(ws_id, db)
    if not es:
        fab.call("POST", f"/workspaces/{ws_id}/eventstreams",
                 json_body={"displayName": EVENTSTREAM, "description": "SYNTHETIC - card processor authorisations, live.",
                            "definition": definition})
        for _ in range(30):
            time.sleep(4)
            es = get_item(ws_id, EVENTSTREAM, "Eventstream")
            if es:
                break
        print(f"+ eventstream {EVENTSTREAM} ({es['id']})")
    else:
        fab.call("POST", f"/workspaces/{ws_id}/eventstreams/{es['id']}/updateDefinition", json_body={"definition": definition})
        print(f"= eventstream {EVENTSTREAM} ({es['id']}) definition updated")
    return es


def source_connection(ws_id: str, es_id: str) -> dict:
    for _ in range(20):
        topo = fab.call("GET", f"/workspaces/{ws_id}/eventstreams/{es_id}/topology")
        src = next((s for s in topo.get("sources", []) if s.get("name") == SOURCE), None)
        if src and src.get("id"):
            try:
                return fab.call("GET", f"/workspaces/{ws_id}/eventstreams/{es_id}/sources/{src['id']}/connection")
            except RuntimeError as e:
                print(f"    waiting for the custom endpoint ({str(e)[:80]})")
        time.sleep(6)
    sys.exit("could not read the custom endpoint connection - open the eventstream in the portal once and retry")


# --------------------------------------------------------------------------- #
# Lakehouse shortcut (OneLake availability) and access for the BFF identity
# --------------------------------------------------------------------------- #
def ensure_shortcut(ws_id: str, db: dict) -> None:
    lh = get_item(ws_id, LAKEHOUSE, "Lakehouse")
    if not lh:
        print("  ! lakehouse not found - shortcut skipped")
        return
    body = {"path": "Tables", "name": SHORTCUT,
            "target": {"oneLake": {"workspaceId": ws_id, "itemId": db["id"], "path": f"Tables/{TABLE}"}}}
    try:
        fab.call("POST", f"/workspaces/{ws_id}/items/{lh['id']}/shortcuts", json_body=body,
                 params={"shortcutConflictPolicy": "CreateOrOverwrite"})
        print(f"  shortcut {LAKEHOUSE}/Tables/{SHORTCUT} -> {db['displayName']}/{TABLE}")
    except RuntimeError as e:
        print(f"  ! shortcut not created ({str(e)[:200]})")


def grant(ws_id: str, principal: str) -> None:
    try:
        fab.call("POST", f"/workspaces/{ws_id}/roleAssignments",
                 json_body={"principal": {"id": principal, "type": "ServicePrincipal"}, "role": "Viewer"})
        print(f"  granted Viewer on the workspace to {principal}")
    except RuntimeError as e:
        msg = str(e)
        print("  = principal already has a workspace role" if "PrincipalAlreadyHasWorkspaceRolePermissions" in msg or "409" in msg
              else f"  ! grant failed: {msg[:300]}")


def write_env(conn: dict, uri: str, db: str) -> None:
    keys = conn.get("accessKeys", {})
    lines = [
        "# GENERATED by deploy_realtime.py - holds an Eventstream send key. Never commit.",
        f"EVENTSTREAM_NAMESPACE={conn.get('fullyQualifiedNamespace', '')}",
        f"EVENTSTREAM_HUB={conn.get('eventHubName', '')}",
        f"EVENTSTREAM_CONNECTION={keys.get('primaryConnectionString', '')}",
        f"PROCESSOR_KQL_URI={uri}",
        f"PROCESSOR_KQL_DB={db}",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {ENV_FILE.name} (send key not printed)")


def status(ws_id: str) -> None:
    for t in ("Eventhouse", "KQLDatabase", "Eventstream"):
        name = EVENTSTREAM if t == "Eventstream" else EVENTHOUSE
        it = get_item(ws_id, name, t)
        print(f"  {t:<12} {name:<20} {it['id'] if it else 'NOT CREATED'}")
    db = get_item(ws_id, EVENTHOUSE, "KQLDatabase")
    if db:
        d = fab.call("GET", f"/workspaces/{ws_id}/kqlDatabases/{db['id']}")
        uri = d["properties"]["queryServiceUri"]
        res = kusto(uri, d["displayName"], "LiveAuthKpis(24h)", mgmt=False)
        rows = next((t for t in res if t.get("TableKind") == "PrimaryResult"), {}).get("Rows", [])
        print(f"  {TABLE} last 24h: {rows[0] if rows else 'no rows'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grant-principal", help="Entra object ID (e.g. the BFF managed identity) to get Viewer on the workspace")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--skip-shortcut", action="store_true")
    args = ap.parse_args()

    ws = get_workspace() or sys.exit("workspace not found - run deploy_fabric.py first")
    if args.status:
        status(ws["id"])
        return 0
    _, db = ensure_eventhouse(ws["id"])
    uri = db["properties"]["queryServiceUri"]
    setup_kql(uri, db["displayName"])
    es = ensure_eventstream(ws["id"], db)
    conn = source_connection(ws["id"], es["id"])
    write_env(conn, uri, db["displayName"])
    if not args.skip_shortcut:
        ensure_shortcut(ws["id"], db)
    if args.grant_principal:
        grant(ws["id"], args.grant_principal)
    print("\nNext: python data/fabric-iq/stream_processor_events.py --scenario card-testing --account CA-2009")
    return 0


if __name__ == "__main__":
    sys.exit(main())
