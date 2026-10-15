"""Create or update the personal-banking Foundry prompt agents defined in agent/pb_agents.md.

Each agent reuses the project's EXISTING connections, copied verbatim from the
main concierge agent so all agents point at the same governed sources:
  fabric -> the `fabric_iq_preview` tool (smmortgagerenewals semantic model)
  kb     -> the Foundry IQ knowledge-base MCP tool (renewal-policies index)
  work   -> the Work IQ MCP tools (mail, Teams, calendar, SharePoint, OneDrive)
  web    -> web search (Web IQ)
Scenario briefs and compliance reviews use fabric/kb only; the mission agent uses all four layers.

    python agent/create_pb_agents.py           # dry run
    python agent/create_pb_agents.py --apply
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import requests

ENDPOINT = "https://mortgage-iqs.services.ai.azure.com/api/projects/proj-conceirge"
SOURCE = "mortgage-renewal-concierge"
API = "2025-05-15-preview"
SPEC = Path(__file__).parent / "pb_agents.md"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "brand"))
from bank_profile import rebrand_text  # noqa: E402  - names the deployed bank


def token() -> str:
    out = subprocess.run("az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv",
                         capture_output=True, text=True, shell=True)
    if out.returncode:
        sys.exit(out.stderr[:300])
    return out.stdout.strip()


def latest(h: dict, name: str) -> dict | None:
    r = requests.get(f"{ENDPOINT}/agents/{name}?api-version={API}", headers=h, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    ver = r.json()["versions"]["latest"]["version"]
    v = requests.get(f"{ENDPOINT}/agents/{name}/versions/{ver}?api-version={API}", headers=h, timeout=60)
    v.raise_for_status()
    return v.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    h = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}
    src = latest(h, SOURCE) or sys.exit(f"{SOURCE} not found")
    sdef = src["definition"]
    pool = {"fabric": [t for t in sdef["tools"] if t.get("type") == "fabric_iq_preview"],
            "kb": [t for t in sdef["tools"] if t.get("type") == "mcp" and str(t.get("server_label", "")).startswith("kb-")],
            "work": [t for t in sdef["tools"] if str(t.get("server_label", "")).lower().startswith("workiq")],
            "web": [t for t in sdef["tools"] if t.get("type") in ("web_search", "web_search_preview", "bing_grounding")]}
    spec = rebrand_text(SPEC.read_text(encoding="utf-8"))
    for m in re.finditer(r"<!-- AGENT (\S+) tools=(\S+) -->\n(.*?)<!-- END -->", spec, re.S):
        name, kinds, body = m.group(1), m.group(2).split(","), m.group(3).strip()
        missing = [k for k in kinds if not pool.get(k)]
        if missing:
            sys.exit(f"{name}: no {missing} tool on {SOURCE}")
        tools = [t for k in kinds for t in pool[k]]
        cur = latest(h, name)
        print(f"{name:24} tools={[t.get('server_label') or t['type'] for t in tools]} model={sdef['model']} "
              f"{'new' if not cur else 'v' + str(cur.get('version'))} instructions={len(body)}")
        if not args.apply:
            continue
        r = requests.post(f"{ENDPOINT}/agents/{name}/versions?api-version={API}", headers=h, timeout=120,
                          json={"definition": {"kind": sdef.get("kind", "prompt"), "model": sdef["model"],
                                               "instructions": body, "tools": tools},
                                "description": f"Personal banking - {name}"})
        if r.status_code >= 400:
            sys.exit(f"{name}: {r.status_code} {r.text[:400]}")
        print(f"  -> created version {r.json().get('version')}")
    if not args.apply:
        print("Dry run. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
