"""Deploy the Mortgage Renewal Concierge dataset into Microsoft Fabric.

Creates, end to end and idempotently:

  1. workspace   ws-mortgage-renewals-demo   (bound to a named capacity)
  2. lakehouse   lh_mortgage_renewals
  3. OneLake     Files/renewals/*.csv        (the five synthetic CSVs)
  4. notebook    nb_load_renewals            (runs load_renewals_fabric.py logic:
                                              5 Delta tables + 2 curated views,
                                              dates moved to the current week)
  5. schedule    nb_load_renewals runs daily so the dates stay evergreen
  6. semantic    sm_mortgage_renewals        Direct Lake model over the SQL
     model                                   analytics endpoint, with measures

Auth uses the Azure CLI login (`az login`) - no secrets. The signed-in user must
be a Fabric workspace creator and an admin/contributor on the target capacity.

    python deploy_fabric.py --capacity fabcap26
    python deploy_fabric.py --capacity fabcap26 --only semantic-model
    python deploy_fabric.py --status
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "tools" / "brand"))
from bank_profile import rebrand_text  # noqa: E402  - names the deployed bank

FABRIC_API = "https://api.fabric.microsoft.com/v1"
ONELAKE_DFS = "https://onelake.dfs.fabric.microsoft.com"

WORKSPACE = "ws-mortgage-renewals-demo"
LAKEHOUSE = "lh_mortgage_renewals"
NOTEBOOK = "nb_load_renewals"
LOAD_SOURCE = "load_renewals_fabric.py"
SEMANTIC_NOTEBOOK = "nb_create_semantic_model"
SEMANTIC_MODEL = "sm_mortgage_renewals"

# The app's date-shift module, inlined into the load notebook so Fabric IQ and the
# app move the snapshot forward by exactly the same rule.
EVERGREEN = HERE.parents[1] / "app" / "src" / "bff" / "app" / "evergreen.py"
# UTC run times for the load notebook. The offset only changes on the snapshot
# weekday, but a capacity paused through one run catches up at the next.
REFRESH_TIMES = ["00:20", "12:20"]

WORKSPACE_DESC = (
    "SYNTHETIC DEMO DATA - Mortgage Renewal Concierge. CFC Bank is used only as "
    "a branding label; no customer, balance, rate or policy here reflects real "
    "CFC Bank data. Do not use for any operational or reporting purpose."
)

CSVS = [
    "customers.csv",
    "mortgage_renewals.csv",
    "renewal_risk_scores.csv",
    "retention_offers.csv",
    "branch_performance.csv",
    "households.csv",
    "credit_capacity.csv",
    "customer_products.csv",
    "financial_signals_monthly.csv",
    "life_events.csv",
    "consent_preferences.csv",
    "financial_wellness.csv",
    "next_best_actions.csv",
    "rate_scenario_presets.csv",
    "renewal_scenario_sensitivity.csv",
    "card_products.csv",
    "card_accounts.csv",
    "card_spend_monthly.csv",
    "card_next_actions.csv",
    "deposit_accounts.csv",
    "deposit_flows_monthly.csv",
    "banking_next_actions.csv",
    "credit_facilities.csv",
    "debt_consolidation_candidates.csv",
    "borrowing_next_actions.csv",
    "investment_accounts.csv",
    "registered_room.csv",
    "investing_next_actions.csv",
    "newcomer_journey.csv",
    "transfers_out_monthly.csv",
    "newcomers_next_actions.csv",
    "insurance_policies.csv",
    "coverage_gaps.csv",
    "insurance_next_actions.csv",
    "security_events.csv",
    "customer_security_posture.csv",
    "security_next_actions.csv",
]


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
def token(resource: str) -> str:
    out = subprocess.run(
        ["az", "account", "get-access-token", "--resource", resource,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True, shell=True,
    )
    if out.returncode != 0:
        sys.exit(f"az token failed for {resource}: {out.stderr}")
    return out.stdout.strip()


class Api:
    def __init__(self, resource: str, base: str):
        self._resource, self.base = resource, base
        self._tok, self._at = "", 0.0

    def h(self, extra: dict | None = None) -> dict:
        if time.time() - self._at > 1800:
            self._tok, self._at = token(self._resource), time.time()
        head = {"Authorization": f"Bearer {self._tok}"}
        head.update(extra or {})
        return head

    def call(self, method: str, path: str, *, json_body: Any = None,
             data: bytes | None = None, headers: dict | None = None,
             params: dict | None = None, ok: tuple[int, ...] = (200, 201, 202)) -> Any:
        url = path if path.startswith("http") else f"{self.base}{path}"
        r = requests.request(method, url, headers=self.h(headers),
                             json=json_body, data=data, params=params, timeout=180)
        if r.status_code == 202 and "Location" in r.headers:
            return self._poll(r)
        if r.status_code not in ok:
            raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:900]}")
        return r.json() if r.content and "json" in r.headers.get("Content-Type", "") else None

    def _poll(self, resp) -> Any:
        loc = resp.headers["Location"]
        for _ in range(120):
            time.sleep(int(resp.headers.get("Retry-After", 5)))
            p = requests.get(loc, headers=self.h(), timeout=120)
            if p.status_code in (200, 201):
                body = p.json() if p.content else {}
                state = body.get("status")
                if state in (None, "Succeeded"):
                    if body.get("status") == "Succeeded":
                        res = requests.get(f"{loc}/result", headers=self.h(), timeout=120)
                        return res.json() if res.status_code == 200 and res.content else body
                    return body
                if state in ("Failed", "Undefined"):
                    raise RuntimeError(f"LRO failed: {json.dumps(body)[:900]}")
            resp.headers["Retry-After"] = "5"
        raise RuntimeError("LRO timed out")


fab = Api("https://api.fabric.microsoft.com", FABRIC_API)
lake = Api("https://storage.azure.com", ONELAKE_DFS)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def find(items: list[dict], name: str, key: str = "displayName") -> dict | None:
    return next((i for i in items if i.get(key) == name), None)


def get_workspace() -> dict | None:
    return find(fab.call("GET", "/workspaces")["value"], WORKSPACE)


def get_item(ws_id: str, name: str, item_type: str) -> dict | None:
    items = fab.call("GET", f"/workspaces/{ws_id}/items",
                     params={"type": item_type})["value"]
    return find(items, name)


# --------------------------------------------------------------------------- #
# 1. workspace
# --------------------------------------------------------------------------- #
def ensure_workspace(capacity_name: str) -> str:
    ws = get_workspace()
    if ws:
        print(f"= workspace {WORKSPACE} ({ws['id']})")
        ws_id = ws["id"]
    else:
        ws = fab.call("POST", "/workspaces",
                      json_body={"displayName": WORKSPACE, "description": WORKSPACE_DESC})
        ws_id = ws["id"]
        print(f"+ workspace {WORKSPACE} ({ws_id})")

    caps = fab.call("GET", "/capacities")["value"]
    cap = find(caps, capacity_name)
    if not cap:
        sys.exit(f"capacity '{capacity_name}' not found. Available: "
                 + ", ".join(c["displayName"] for c in caps))
    if cap.get("state") != "Active":
        sys.exit(f"capacity '{capacity_name}' is {cap.get('state')} - resume it first")

    current = fab.call("GET", f"/workspaces/{ws_id}").get("capacityId")
    if (current or "").lower() != cap["id"].lower():
        fab.call("POST", f"/workspaces/{ws_id}/assignToCapacity",
                 json_body={"capacityId": cap["id"]}, ok=(200, 202))
        print(f"  assigned to capacity {capacity_name} ({cap['sku']}, {cap['region']})")
    else:
        print(f"  already on capacity {capacity_name} ({cap['sku']})")
    return ws_id


# --------------------------------------------------------------------------- #
# 2. lakehouse
# --------------------------------------------------------------------------- #
def ensure_lakehouse(ws_id: str) -> dict:
    lh = get_item(ws_id, LAKEHOUSE, "Lakehouse")
    if not lh:
        fab.call("POST", f"/workspaces/{ws_id}/lakehouses",
                 json_body={"displayName": LAKEHOUSE,
                            "description": "SYNTHETIC DEMO DATA - renewal campaign dataset."})
        for _ in range(30):
            time.sleep(4)
            lh = get_item(ws_id, LAKEHOUSE, "Lakehouse")
            if lh:
                break
        print(f"+ lakehouse {LAKEHOUSE} ({lh['id']})")
    else:
        print(f"= lakehouse {LAKEHOUSE} ({lh['id']})")

    detail = fab.call("GET", f"/workspaces/{ws_id}/lakehouses/{lh['id']}")
    return detail or lh


# --------------------------------------------------------------------------- #
# 3. OneLake upload
# --------------------------------------------------------------------------- #
def upload_csvs(ws_id: str, lh_id: str) -> None:
    print("  uploading CSVs to Files/renewals/")
    for name in CSVS:
        content = rebrand_text((HERE / name).read_text(encoding="utf-8")).encode("utf-8")
        path = f"/{ws_id}/{lh_id}/Files/renewals/{name}"
        lake.call("PUT", f"{ONELAKE_DFS}{path}", params={"resource": "file"},
                  ok=(201, 202))
        lake.call("PATCH", f"{ONELAKE_DFS}{path}",
                  params={"action": "append", "position": "0"},
                  data=content,
                  headers={"Content-Type": "application/octet-stream"},
                  ok=(202,))
        lake.call("PATCH", f"{ONELAKE_DFS}{path}",
                  params={"action": "flush", "position": str(len(content))},
                  ok=(200,))
        print(f"    {name:<26} {len(content):>7,} bytes")


# --------------------------------------------------------------------------- #
# 4. notebook
# --------------------------------------------------------------------------- #
def notebook_payload(ws_id: str, lh_id: str, source: str) -> str:
    code = (HERE / source).read_text(encoding="utf-8")
    if source == LOAD_SOURCE:
        code = evergreen_source() + "\n\n" + code
    # %pip magics must sit in their own cell and run first
    lines = code.splitlines(keepends=True)
    magic, body, cells = [], [], []
    for ln in lines:
        if ln.startswith("# MAGIC %"):
            magic.append(ln.replace("# MAGIC ", "", 1))
        else:
            body.append(ln)
    if magic:
        cells.append({"cell_type": "code", "source": magic,
                      "execution_count": None, "outputs": [], "metadata": {}})
    cells.append({"cell_type": "code", "source": body,
                  "execution_count": None, "outputs": [], "metadata": {}})

    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": cells,
        "metadata": {
            "language_info": {"name": "python"},
            "dependencies": {
                "lakehouse": {
                    "default_lakehouse": lh_id,
                    "default_lakehouse_name": LAKEHOUSE,
                    "default_lakehouse_workspace_id": ws_id,
                }
            },
        },
    }
    return base64.b64encode(json.dumps(nb).encode()).decode()


def ensure_notebook(ws_id: str, lh_id: str, name: str, source: str,
                    description: str) -> str:
    payload = notebook_payload(ws_id, lh_id, source)
    definition = {"format": "ipynb",
                  "parts": [{"path": "notebook-content.ipynb",
                             "payload": payload, "payloadType": "InlineBase64"}]}
    nb = get_item(ws_id, name, "Notebook")
    if nb:
        fab.call("POST", f"/workspaces/{ws_id}/notebooks/{nb['id']}/updateDefinition",
                 json_body={"definition": definition}, ok=(200, 202))
        print(f"= notebook {name} ({nb['id']}) definition updated")
        return nb["id"]
    created = fab.call("POST", f"/workspaces/{ws_id}/notebooks",
                       json_body={"displayName": name, "description": description,
                                  "definition": definition})
    nb_id = (created or {}).get("id")
    if not nb_id:
        for _ in range(30):
            time.sleep(4)
            nb = get_item(ws_id, name, "Notebook")
            if nb:
                nb_id = nb["id"]
                break
    print(f"+ notebook {name} ({nb_id})")
    return nb_id


def run_notebook(ws_id: str, nb_id: str) -> None:
    print("  running notebook (Spark session start can take 2-4 minutes)…")
    r = requests.post(
        f"{FABRIC_API}/workspaces/{ws_id}/items/{nb_id}/jobs/instances",
        headers=fab.h({"Content-Type": "application/json"}),
        params={"jobType": "RunNotebook"}, json={}, timeout=120,
    )
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"job start -> {r.status_code}: {r.text[:900]}")
    loc = r.headers.get("Location")
    if not loc:
        print("  (no job location returned; check the notebook run in the portal)")
        return
    for i in range(160):
        time.sleep(15)
        s = requests.get(loc, headers=fab.h(), timeout=60)
        if s.status_code != 200:
            continue
        st = s.json().get("status")
        if i % 4 == 0:
            print(f"    [{i*15:>4}s] {st}")
        if st in ("Completed", "Succeeded"):
            print("  notebook completed")
            return
        if st in ("Failed", "Cancelled", "Deduped"):
            raise RuntimeError(f"notebook run {st}: {json.dumps(s.json())[:900]}")
    raise RuntimeError("notebook run timed out")


def evergreen_source() -> str:
    """evergreen.py as notebook code: the future import must be a file's first
    statement, which it no longer is once inlined, and nothing needs it at runtime."""
    src = EVERGREEN.read_text(encoding="utf-8")
    return "\n".join(ln for ln in src.splitlines() if ln.strip() != "from __future__ import annotations")


def ensure_schedule(ws_id: str, nb_id: str) -> None:
    """Run the load notebook on a timer so the tables roll forward each week."""
    base = f"/workspaces/{ws_id}/items/{nb_id}/jobs/RunNotebook/schedules"
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 300))
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 5 * 365 * 86400))
    body = {"enabled": True,
            "configuration": {"type": "Daily", "times": REFRESH_TIMES, "localTimeZoneId": "UTC",
                              "startDateTime": start, "endDateTime": end}}
    existing = (fab.call("GET", base) or {}).get("value", [])
    if existing:
        sid = existing[0]["id"]
        fab.call("PATCH", f"{base}/{sid}", json_body=body, ok=(200,))
        print(f"= schedule {sid}: daily at {', '.join(REFRESH_TIMES)} UTC")
        return
    created = fab.call("POST", base, json_body=body, ok=(200, 201))
    print(f"+ schedule {(created or {}).get('id')}: daily at {', '.join(REFRESH_TIMES)} UTC")


# --------------------------------------------------------------------------- #
# 5. semantic model (Direct Lake)
# --------------------------------------------------------------------------- #
def read_log(ws_id: str, lh_id: str,
             path: str = "Files/_deploy/semantic_model_log.txt") -> None:
    """Notebook job failures are opaque from the REST API - the notebooks write a
    full traceback into OneLake, so print it here."""
    url = f"{ONELAKE_DFS}/{ws_id}/{lh_id}/{path}"
    r = requests.get(url, headers=lake.h(), timeout=60)
    if r.status_code != 200:
        print(f"  (no log at {path}: {r.status_code})")
        return
    print("---- notebook log " + "-" * 58)
    text = r.content.decode("utf-8", errors="replace")
    # strip pip's ANSI/box-drawing progress art and anything the console codec
    # cannot render (Windows consoles default to cp1252)
    text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
    enc = sys.stdout.encoding or "utf-8"
    print(text.encode(enc, errors="replace").decode(enc))
    print("-" * 76)


def ensure_semantic_model(ws_id: str, lh_id: str) -> None:
    """Build the Direct Lake model by running a notebook that uses semantic-link-labs.

    Writing TMDL by hand over the REST API is brittle across Fabric releases; the
    in-notebook path uses the supported library and runs with the workspace's own
    identity and context.
    """
    nb_id = ensure_notebook(
        ws_id, lh_id, SEMANTIC_NOTEBOOK, "create_semantic_model_fabric.py",
        "Builds the Direct Lake semantic model and its business measures.",
    )
    try:
        run_notebook(ws_id, nb_id)
    finally:
        read_log(ws_id, lh_id)
    sm = get_item(ws_id, SEMANTIC_MODEL, "SemanticModel")
    print(f"  semantic model {SEMANTIC_MODEL}: {'created ' + sm['id'] if sm else 'NOT FOUND'}")


# --------------------------------------------------------------------------- #
def sql_endpoint(lh: dict) -> tuple[str, str]:
    props = lh.get("properties", {}).get("sqlEndpointProperties", {})
    return props.get("connectionString", ""), props.get("id", "")


def status() -> None:
    ws = get_workspace()
    if not ws:
        print(f"workspace {WORKSPACE}: NOT CREATED")
        return
    print(f"workspace  {WORKSPACE}  {ws['id']}")
    items = fab.call("GET", f"/workspaces/{ws['id']}/items")["value"]
    for i in sorted(items, key=lambda x: (x["type"], x["displayName"])):
        print(f"  {i['type']:<16} {i['displayName']}")
    lh = get_item(ws["id"], LAKEHOUSE, "Lakehouse")
    if lh:
        detail = fab.call("GET", f"/workspaces/{ws['id']}/lakehouses/{lh['id']}")
        server, db = sql_endpoint(detail)
        print(f"\nFABRIC_SQL_ENDPOINT = {server}")
        print(f"FABRIC_DATABASE     = {LAKEHOUSE}")
        print(f"sql endpoint id     = {db}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capacity", default="fabcap26")
    ap.add_argument("--only", choices=["workspace", "lakehouse", "upload",
                                       "notebook", "schedule", "semantic-model"])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--skip-run", action="store_true",
                    help="create the notebook but do not execute it")
    args = ap.parse_args()

    if args.status:
        status()
        return

    steps = [args.only] if args.only else ["workspace", "lakehouse", "upload",
                                           "notebook", "schedule", "semantic-model"]

    ws_id = ensure_workspace(args.capacity) if "workspace" in steps else \
        (get_workspace() or sys.exit("workspace not found - run --only workspace"))["id"]

    lh = None
    if any(s in steps for s in ("lakehouse", "upload", "notebook", "semantic-model")):
        lh = ensure_lakehouse(ws_id)

    if "upload" in steps:
        upload_csvs(ws_id, lh["id"])

    if "notebook" in steps:
        nb_id = ensure_notebook(ws_id, lh["id"], NOTEBOOK, LOAD_SOURCE,
                                "Loads the renewal CSVs into Delta tables, dates moved to the current week.")
        if not args.skip_run:
            run_notebook(ws_id, nb_id)

    if "schedule" in steps:
        nb = get_item(ws_id, NOTEBOOK, "Notebook") or sys.exit("notebook not found - run --only notebook")
        ensure_schedule(ws_id, nb["id"])

    if "semantic-model" in steps:
        ensure_semantic_model(ws_id, lh["id"])

    print()
    status()


if __name__ == "__main__":
    main()
