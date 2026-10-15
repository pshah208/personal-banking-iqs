"""Create (or update) the **Mortgage Renewal Concierge** agent in Azure AI Foundry
and run it interactively.

The agent gets three function tools, one per IQ layer:

    search_work_iq            -> Microsoft Graph Search   (Work IQ)
    query_renewal_analytics   -> Fabric SQL endpoint      (Fabric IQ)
    lookup_renewal_policy     -> Azure AI Search          (Foundry IQ)

Each tool degrades gracefully: if its backend is not configured it reads the
local synthetic files under ../data instead, so the agent is demonstrable before
every backend is wired up.

--------------------------------------------------------------------------------
INSTALL
--------------------------------------------------------------------------------
    pip install azure-ai-agents==1.1.0 azure-identity==1.19.0 \
                azure-search-documents==11.5.2 requests pyodbc

--------------------------------------------------------------------------------
CONFIGURE (all optional except the first two)
--------------------------------------------------------------------------------
    $env:FOUNDRY_PROJECT_ENDPOINT = "https://<res>.services.ai.azure.com/api/projects/<proj>"
    $env:FOUNDRY_MODEL            = "gpt-4.1"          # a deployment in that project

    # Foundry IQ
    $env:SEARCH_ENDPOINT          = "https://<svc>.search.windows.net"
    $env:SEARCH_ADMIN_KEY         = "<key>"            # or use RBAC
    $env:SEARCH_INDEX             = "renewal-policies"

    # Fabric IQ
    $env:FABRIC_SQL_ENDPOINT      = "<ws>.datawarehouse.fabric.microsoft.com"
    $env:FABRIC_DATABASE          = "lh_mortgage_renewals"

    # Work IQ  (delegated Graph auth - the signed-in user's M365 search)
    $env:WORKIQ_TENANT_ID         = "<tenant-guid>"
    $env:WORKIQ_CLIENT_ID         = "<app-client-id>"   # needs Mail.Read, ChannelMessage.Read.All, Files.Read.All (delegated)

--------------------------------------------------------------------------------
RUN
--------------------------------------------------------------------------------
    python create_agent.py --create            # create/update the agent only
    python create_agent.py --ask "Analyze mortgage renewals occurring in the next 180 days and identify customers most at risk of attrition."
    python create_agent.py --demo              # run all three demo questions
    python create_agent.py --chat              # interactive
"""

from __future__ import annotations

import argparse
import csv
import functools
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "tools" / "brand"))
from bank_profile import rebrand, rebrand_text  # noqa: E402  - names the deployed bank
DATA = HERE.parent / "data"

AGENT_NAME = os.getenv("AGENT_NAME", "mortgage-renewal-concierge")
MODEL = os.getenv("FOUNDRY_MODEL", "gpt-4.1")
PROJECT_ENDPOINT = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")

SEARCH_ENDPOINT = os.getenv("SEARCH_ENDPOINT", "")
SEARCH_INDEX = os.getenv("SEARCH_INDEX", "renewal-policies")
SEARCH_KEY = os.getenv("SEARCH_ADMIN_KEY", "")

FABRIC_SQL = os.getenv("FABRIC_SQL_ENDPOINT", "")
FABRIC_DB = os.getenv("FABRIC_DATABASE", "")
FABRIC_WORKSPACE_ID = os.getenv("FABRIC_WORKSPACE_ID", "")
FABRIC_SEMANTIC_MODEL = os.getenv("FABRIC_SEMANTIC_MODEL", "sm_mortgage_renewals")
FABRIC_DATASET_ID = os.getenv("FABRIC_DATASET_ID", "")

WORKIQ_TENANT = os.getenv("WORKIQ_TENANT_ID", "")
WORKIQ_CLIENT = os.getenv("WORKIQ_CLIENT_ID", "")

DEMO_QUESTIONS = [
    "Summarize discussions from emails, Teams and meetings related to upcoming mortgage renewals.",
    "Analyze mortgage renewals occurring in the next 180 days and identify customers most at risk of attrition.",
    "Review renewal pricing and retention policies and identify approvals required.",
]


def instructions() -> str:
    md = rebrand_text((HERE / "agent_instructions.md").read_text(encoding="utf-8"))
    m = re.search(r"<!-- INSTRUCTIONS-START -->(.*?)<!-- INSTRUCTIONS-END -->", md, re.S)
    return (m.group(1) if m else md).strip()


# =========================================================================== #
# Tool 1 - Work IQ
# =========================================================================== #
def search_work_iq(query: str, category: str = "") -> str:
    """Search Microsoft 365 (emails, Teams messages, meeting notes) for renewal discussions. Use for concerns, feedback, escalations and executive guidance. Optional category filter: branch_leader_concern, advisor_feedback, rate_escalation, executive_guidance."""
    hits = _work_iq_graph(query) if WORKIQ_CLIENT else None
    if hits is None:
        hits = _work_iq_local(query, category)
    return json.dumps({"source": "Work IQ", "query": query,
                       "category": category or "all", "results": hits}, ensure_ascii=False)


def _work_iq_graph(query: str) -> list[dict] | None:
    try:
        import requests
        from azure.identity import DeviceCodeCredential

        cred = _graph_cred(DeviceCodeCredential)
        token = cred.get_token(
            "https://graph.microsoft.com/Mail.Read",
            "https://graph.microsoft.com/ChannelMessage.Read.All",
            "https://graph.microsoft.com/Files.Read.All",
        ).token
        body = {
            "requests": [
                {
                    "entityTypes": ["message", "chatMessage", "driveItem"],
                    "query": {"queryString": query},
                    "from": 0,
                    "size": 25,
                }
            ]
        }
        r = requests.post(
            "https://graph.microsoft.com/v1.0/search/query",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=body, timeout=60,
        )
        r.raise_for_status()
        out: list[dict] = []
        for c in r.json().get("value", []):
            for hc in c.get("hitsContainers", []):
                for hit in hc.get("hits", []):
                    res = hit.get("resource", {})
                    out.append({
                        "type": res.get("@odata.type", "").split(".")[-1],
                        "subject": res.get("subject") or res.get("name"),
                        "from": (res.get("from") or res.get("sender") or {})
                                .get("emailAddress", {}).get("name"),
                        "date": res.get("receivedDateTime") or res.get("createdDateTime")
                                or res.get("lastModifiedDateTime"),
                        "excerpt": hit.get("summary", "")[:1200],
                    })
        return out
    except Exception as exc:  # noqa: BLE001 - graceful degradation is intentional
        print(f"  [work-iq] Graph search unavailable ({exc}); using local corpus")
        return None


@functools.lru_cache(maxsize=1)
def _work_corpus() -> list[dict]:
    docs: list[dict] = []
    wi = DATA / "work-iq"

    emails = json.loads((wi / "emails.json").read_text(encoding="utf-8"))
    people = {p["alias"]: p["displayName"] for p in emails["people"]}
    for e in emails["emails"]:
        docs.append({"type": "email", "id": e["id"], "category": e["category"],
                     "subject": e["subject"], "from": people[e["from"]],
                     "date": e["sentDateTime"], "text": e["body"]})

    teams = json.loads((wi / "teams_messages.json").read_text(encoding="utf-8"))
    for ch in teams["channels"]:
        for conv in ch["conversations"]:
            docs.append({"type": "teams", "id": conv["id"], "category": conv["category"],
                         "subject": f"[{ch['displayName']}] {conv.get('subject','')}",
                         "from": people.get(conv["from"], conv["from"]),
                         "date": conv["createdDateTime"], "text": conv["message"]})
            for i, rep in enumerate(conv.get("replies", []), 1):
                docs.append({"type": "teams_reply", "id": f"{conv['id']}-r{i}",
                             "category": conv["category"],
                             "subject": f"[{ch['displayName']}] re: {conv.get('subject','')}",
                             "from": people.get(rep["from"], rep["from"]),
                             "date": rep["createdDateTime"], "text": rep["message"]})

    for f in sorted((wi / "meetings").glob("*.md")):
        docs.append({"type": "meeting", "id": f.stem, "category": "meeting",
                     "subject": f.stem, "from": "Meeting record",
                     "date": f.stem[:10], "text": f.read_text(encoding="utf-8")})
    return rebrand(docs)


_STOP = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "our",
         "what", "which", "who", "how", "about", "related", "discussions", "please",
         "summarize", "summarise", "upcoming", "any", "all"}


def _work_iq_local(query: str, category: str) -> list[dict]:
    terms = [t for t in re.findall(r"[a-z0-9\-]{3,}", query.lower()) if t not in _STOP]
    scored = []
    for d in _work_corpus():
        if category and d["category"] != category:
            continue
        blob = f"{d['subject']} {d['text']}".lower()
        score = sum(blob.count(t) for t in terms)
        if category and not terms:
            score = 1
        if score:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    if not scored:  # broad ask - return the whole corpus, newest first
        scored = [(0, d) for d in sorted(_work_corpus(), key=lambda d: d["date"])]
    return [
        {"type": d["type"], "id": d["id"], "category": d["category"],
         "subject": d["subject"], "from": d["from"], "date": d["date"],
         "excerpt": d["text"][:2000]}
        for _, d in scored[:20]
    ]


def _graph_cred(cls):
    return cls(client_id=WORKIQ_CLIENT, tenant_id=WORKIQ_TENANT)


# =========================================================================== #
# Tool 2 - Fabric IQ
# =========================================================================== #
def query_renewal_analytics(question: str, segment: str = "", risk_band: str = "",
                            branch_id: str = "", top: int = 20) -> str:
    """Query governed mortgage renewal analytics from Microsoft Fabric (OneLake): renewals maturing within 180 days with customer segment, attrition risk score and band, renewal likelihood, revenue exposure, lifetime value and recommended retention offer. Optional filters: segment, risk_band (High/Medium/Low), branch_id."""
    # Preference order: the governed semantic model (Direct Lake, business
    # measures) -> the SQL analytics endpoint -> the local CSVs.
    result = _fabric_dax(segment, risk_band, branch_id, top) if FABRIC_WORKSPACE_ID else None
    mode = "semantic model (Direct Lake, DAX)"

    if result is None:
        rows = _fabric_sql(segment, risk_band, branch_id, top) if (FABRIC_SQL and FABRIC_DB) else None
        if rows is not None:
            result = {"renewals": rows, "segment_summary": None}
            mode = "SQL analytics endpoint"

    if result is None:
        result = {"renewals": _fabric_local(segment, risk_band, branch_id, top),
                  "segment_summary": None}
        mode = "local synthetic CSVs (no Fabric backend configured)"

    return json.dumps({
        "source": "Fabric IQ (OneLake)",
        "mode": mode,
        "population": "renewals maturing within 180 days of the as_of_date in the data",
        "question": question,
        "portfolio_measures": result.get("measures"),
        "segment_summary": result.get("segment_summary") or _segment_summary(),
        "renewals": result["renewals"],
    }, ensure_ascii=False)


# ----- semantic model (preferred) ----- #
FACT = "renewal_attrition_risk"

_PORTFOLIO_MEASURES = [
    "Renewals in 180 Days", "Balance Maturing", "Annual Revenue Exposure",
    "Five Year Lifetime Value", "Value at Risk", "High Risk Renewals",
    "High Risk Exposure", "Pct Balance At High Risk", "Avg Renewal Likelihood Pct",
    "Avg Payment Shock Pct", "Avg Competitor Gap Bps", "Avg LTV Pct",
    "Rate Shopping Signals", "Balance Above 80 LTV",
    "Balance Above 60 Pct Payment Shock",
]


def _dax_filter(segment: str, risk_band: str, branch_id: str) -> str:
    clauses = []
    if segment:
        clauses.append(f"'{FACT}'[segment] = \"{segment}\"")
    if risk_band:
        clauses.append(f"'{FACT}'[attrition_risk_band] = \"{risk_band}\"")
    if branch_id:
        clauses.append(f"'{FACT}'[branch_id] = \"{branch_id.upper()}\"")
    return ", ".join(clauses)


def _execute_dax(queries: list[str]) -> list[list[dict]] | None:
    """Run each DAX query. The Power BI executeQueries endpoint accepts exactly
    one query per request, so these are issued sequentially on one token."""
    try:
        import requests
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token(
            "https://analysis.windows.net/powerbi/api/.default").token
        ds_id = FABRIC_DATASET_ID or _resolve_dataset_id(token)
        if not ds_id:
            return None
        url = (f"https://api.powerbi.com/v1.0/myorg/groups/{FABRIC_WORKSPACE_ID}"
               f"/datasets/{ds_id}/executeQueries")
        headers = {"Authorization": f"Bearer {token}",
                   "Content-Type": "application/json"}

        out: list[list[dict]] = []
        for q in queries:
            r = requests.post(
                url, headers=headers,
                json={"queries": [{"query": q}],
                      "serializerSettings": {"includeNulls": True}},
                timeout=120,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"{r.status_code}: {r.text[:500]} :: {q[:200]}")
            out.append(r.json()["results"][0]["tables"][0]["rows"])
        return out
    except Exception as exc:  # noqa: BLE001 - graceful degradation is intentional
        print(f"  [fabric-iq] semantic model unavailable ({exc}); falling back")
        return None


def _resolve_dataset_id(token: str) -> str | None:
    import requests

    r = requests.get(
        f"https://api.powerbi.com/v1.0/myorg/groups/{FABRIC_WORKSPACE_ID}/datasets",
        headers={"Authorization": f"Bearer {token}"}, timeout=60,
    )
    r.raise_for_status()
    ds = next((d for d in r.json()["value"] if d["name"] == FABRIC_SEMANTIC_MODEL), None)
    return ds["id"] if ds else None


def _fabric_dax(segment: str, risk_band: str, branch_id: str, top: int) -> dict | None:
    flt = _dax_filter(segment, risk_band, branch_id)
    measures = ", ".join(f'"{m}", [{m}]' for m in _PORTFOLIO_MEASURES)
    portfolio_q = (f"EVALUATE CALCULATETABLE(ROW({measures}){', ' + flt if flt else ''})")

    segment_q = (
        "EVALUATE\nSUMMARIZECOLUMNS(\n"
        f"    '{FACT}'[segment],\n"
        + (f"    FILTER(ALL('{FACT}'), {flt.replace(', ', ' && ')}),\n" if flt else "")
        + '    "renewals", [Renewals in 180 Days],\n'
        '    "balance_maturing_cad", [Balance Maturing],\n'
        '    "annual_revenue_exposure_cad", [Annual Revenue Exposure],\n'
        '    "five_year_ltv_cad", [Five Year Lifetime Value],\n'
        '    "value_at_risk_cad", [Value at Risk],\n'
        '    "high_risk_count", [High Risk Renewals],\n'
        '    "avg_renewal_likelihood_pct", [Avg Renewal Likelihood Pct],\n'
        '    "avg_payment_shock_pct", [Avg Payment Shock Pct],\n'
        '    "avg_competitor_gap_bps", [Avg Competitor Gap Bps]\n)\n'
        'ORDER BY [annual_revenue_exposure_cad] DESC'
    )

    cols = ["renewal_id", "full_name", "segment", "province", "branch_name", "advisor",
            "product_type", "mortgage_balance_cad", "ltv_pct", "current_rate_pct",
            "offered_renewal_rate_pct", "payment_shock_pct", "maturity_date",
            "days_to_maturity", "renewal_stage", "attrition_risk_score",
            "attrition_risk_band", "renewal_likelihood_pct", "top_risk_drivers",
            "competitor_rate_gap_bps", "rate_shopping_signal",
            "annual_revenue_exposure_cad", "five_year_lifetime_value_cad",
            "recommended_offer", "required_approval_level", "max_discount_bps",
            "cashback_cad"]
    select = ", ".join(f"\"{c}\", '{FACT}'[{c}]" for c in cols)
    base = f"FILTER('{FACT}', {flt.replace(', ', ' && ')})" if flt else f"'{FACT}'"
    # Explicit aliases give clean column names back, and TOPN does not guarantee
    # output order - the trailing ORDER BY does.
    detail_q = (
        f"EVALUATE\nTOPN({int(top)}, SELECTCOLUMNS({base}, {select}), "
        f"[annual_revenue_exposure_cad], DESC)\n"
        f"ORDER BY [annual_revenue_exposure_cad] DESC"
    )

    out = _execute_dax([portfolio_q, segment_q, detail_q])
    if out is None:
        return None

    def clean(rows: list[dict]) -> list[dict]:
        return [{k.split("[")[-1].rstrip("]"): v for k, v in r.items()} for r in rows]

    return {
        "measures": clean(out[0])[0] if out[0] else None,
        "segment_summary": clean(out[1]),
        "renewals": clean(out[2]),
    }


def _fabric_sql(segment: str, risk_band: str, branch_id: str, top: int) -> list[dict] | None:
    try:
        import pyodbc
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token(
            "https://database.windows.net/.default").token
        import struct

        tok = token.encode("utf-16-le")
        attr = {1256: struct.pack("<i", len(tok)) + tok}
        cn = pyodbc.connect(
            f"Driver={{ODBC Driver 18 for SQL Server}};Server={FABRIC_SQL},1433;"
            f"Database={FABRIC_DB};Encrypt=yes;TrustServerCertificate=no;",
            attrs_before=attr, timeout=30,
        )
        where, params = ["days_to_maturity BETWEEN 0 AND 180"], []
        if segment:
            where.append("segment = ?"); params.append(segment)
        if risk_band:
            where.append("attrition_risk_band = ?"); params.append(risk_band)
        if branch_id:
            where.append("branch_id = ?"); params.append(branch_id)
        sql = (f"SELECT TOP {int(top)} * FROM dbo.renewal_attrition_risk "
               f"WHERE {' AND '.join(where)} ORDER BY annual_revenue_exposure_cad DESC")
        cur = cn.cursor().execute(sql, *params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        print(f"  [fabric-iq] live query unavailable ({exc}); using local CSVs")
        return None


@functools.lru_cache(maxsize=1)
def _fabric_local_all() -> list[dict]:
    fi = DATA / "fabric-iq"

    def read(name):
        with (fi / name).open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    cust = {c["customer_id"]: c for c in read("customers.csv")}
    risk = {r["renewal_id"]: r for r in read("renewal_risk_scores.csv")}
    offers = {o["offer_id"]: o for o in read("retention_offers.csv")}

    rows = []
    for r in read("mortgage_renewals.csv"):
        c, s = cust[r["customer_id"]], risk[r["renewal_id"]]
        o = offers.get(s["recommended_offer_id"], {})
        rows.append({
            "renewal_id": r["renewal_id"], "full_name": c["full_name"],
            "segment": c["segment"], "province": c["province"],
            "branch_id": r["branch_id"], "branch_name": c["branch_name"],
            "advisor": c["primary_advisor_name"],
            "products_held": int(c["products_held"]),
            "tenure_years": int(c["tenure_years"]),
            "origination_channel": c["origination_channel"],
            "product_type": r["product_type"],
            "mortgage_balance_cad": int(r["mortgage_balance_cad"]),
            "ltv_pct": float(r["ltv_pct"]),
            "current_rate_pct": float(r["current_rate_pct"]),
            "offered_renewal_rate_pct": float(r["offered_renewal_rate_pct"]),
            "payment_shock_pct": float(r["payment_shock_pct"]),
            "maturity_date": r["maturity_date"],
            "days_to_maturity": int(r["days_to_maturity"]),
            "renewal_stage": r["renewal_stage"],
            "attrition_risk_score": float(s["attrition_risk_score"]),
            "attrition_risk_band": s["attrition_risk_band"],
            "renewal_likelihood_pct": float(s["renewal_likelihood_pct"]),
            "top_risk_drivers": s["top_risk_drivers"],
            "competitor_rate_gap_bps": int(s["competitor_rate_gap_bps"]),
            "rate_shopping_signal": s["rate_shopping_signal"],
            "annual_revenue_exposure_cad": int(s["annual_revenue_exposure_cad"]),
            "five_year_lifetime_value_cad": int(s["five_year_lifetime_value_cad"]),
            "recommended_offer_id": s["recommended_offer_id"],
            "recommended_offer": o.get("offer_name"),
            "max_discount_bps": int(o.get("max_discount_bps", 0) or 0),
            "cashback_cad": int(o.get("cashback_cad", 0) or 0),
            "required_approval_level": o.get("required_approval_level"),
        })
    return rows


def _fabric_local(segment: str, risk_band: str, branch_id: str, top: int) -> list[dict]:
    rows = _fabric_local_all()
    if segment:
        rows = [r for r in rows if r["segment"].lower() == segment.lower()]
    if risk_band:
        rows = [r for r in rows if r["attrition_risk_band"].lower() == risk_band.lower()]
    if branch_id:
        rows = [r for r in rows if r["branch_id"].upper() == branch_id.upper()]
    rows.sort(key=lambda r: -r["annual_revenue_exposure_cad"])
    return rows[: int(top)]


def _segment_summary() -> list[dict]:
    agg: dict[str, dict] = {}
    for r in _fabric_local_all():
        a = agg.setdefault(r["segment"], {
            "segment": r["segment"], "renewals_next_180d": 0,
            "balance_maturing_cad": 0, "high_risk_count": 0,
            "annual_revenue_exposure_cad": 0, "five_year_ltv_cad": 0,
            "_lik": 0.0, "_shock": 0.0, "_gap": 0,
        })
        a["renewals_next_180d"] += 1
        a["balance_maturing_cad"] += r["mortgage_balance_cad"]
        a["high_risk_count"] += 1 if r["attrition_risk_band"] == "High" else 0
        a["annual_revenue_exposure_cad"] += r["annual_revenue_exposure_cad"]
        a["five_year_ltv_cad"] += r["five_year_lifetime_value_cad"]
        a["_lik"] += r["renewal_likelihood_pct"]
        a["_shock"] += r["payment_shock_pct"]
        a["_gap"] += r["competitor_rate_gap_bps"]
    out = []
    for a in agg.values():
        n = a["renewals_next_180d"]
        a["avg_renewal_likelihood_pct"] = round(a.pop("_lik") / n, 1)
        a["avg_payment_shock_pct"] = round(a.pop("_shock") / n, 1)
        a["avg_competitor_gap_bps"] = round(a.pop("_gap") / n, 1)
        out.append(a)
    out.sort(key=lambda a: -a["annual_revenue_exposure_cad"])
    return out


# =========================================================================== #
# Tool 3 - Foundry IQ
# =========================================================================== #
def lookup_renewal_policy(query: str, category: str = "") -> str:
    """Look up renewal pricing guardrails, retention offer eligibility, discretionary pricing approval requirements, OSFI regulatory references and risk considerations. Optional category filter: pricing_guardrail, approval_requirement, regulatory_reference, risk_consideration."""
    docs = _policy_search(query, category) if SEARCH_ENDPOINT else None
    live = docs is not None
    if docs is None:
        docs = _policy_local(query, category)
    return json.dumps({"source": "Foundry IQ (Azure AI Search)", "live": live,
                       "query": query, "category": category or "all",
                       "policies": docs}, ensure_ascii=False)


def _policy_search(query: str, category: str) -> list[dict] | None:
    try:
        from azure.search.documents import SearchClient

        if SEARCH_KEY:
            from azure.core.credentials import AzureKeyCredential
            cred: Any = AzureKeyCredential(SEARCH_KEY)
        else:
            from azure.identity import DefaultAzureCredential
            cred = DefaultAzureCredential()
        client = SearchClient(SEARCH_ENDPOINT, SEARCH_INDEX, cred)
        results = client.search(
            search_text=query, top=6,
            filter=f"category eq '{category}'" if category else None,
            query_type="semantic", semantic_configuration_name="default",
        )
        return [{"id": d["id"], "title": d["title"], "category": d["category"],
                 "owner": d.get("owner"), "effective_date": d.get("effective_date"),
                 "content": d["content"]} for d in results]
    except Exception as exc:  # noqa: BLE001
        print(f"  [foundry-iq] AI Search unavailable ({exc}); using local corpus")
        return None


@functools.lru_cache(maxsize=1)
def _policies() -> list[dict]:
    return rebrand(json.loads((DATA / "foundry-iq" / "renewal_policies.json")
                              .read_text(encoding="utf-8")))


def _policy_local(query: str, category: str) -> list[dict]:
    terms = [t for t in re.findall(r"[a-z0-9\-]{3,}", query.lower()) if t not in _STOP]
    scored = []
    for d in _policies():
        if category and d["category"] != category:
            continue
        blob = f"{d['title']} {d['content']}".lower()
        scored.append((sum(blob.count(t) for t in terms), d))
    scored.sort(key=lambda x: -x[0])
    hits = [d for s, d in scored if s] or [d for _, d in scored]
    return hits[:6]


TOOLS = [search_work_iq, query_renewal_analytics, lookup_renewal_policy]
TOOL_MAP = {f.__name__: f for f in TOOLS}


# =========================================================================== #
# Foundry agent
# =========================================================================== #
def get_client():
    from azure.ai.agents import AgentsClient
    from azure.identity import DefaultAzureCredential

    if not PROJECT_ENDPOINT:
        sys.exit("Set FOUNDRY_PROJECT_ENDPOINT.")
    return AgentsClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())


def ensure_agent(client) -> str:
    from azure.ai.agents.models import FunctionTool, ToolSet

    toolset = ToolSet()
    toolset.add(FunctionTool(functions=set(TOOLS)))
    client.enable_auto_function_calls(toolset)

    for a in client.list_agents():
        if a.name == AGENT_NAME:
            client.update_agent(agent_id=a.id, model=MODEL, name=AGENT_NAME,
                                instructions=instructions(), toolset=toolset)
            print(f"Updated agent {AGENT_NAME} ({a.id})")
            return a.id

    agent = client.create_agent(model=MODEL, name=AGENT_NAME,
                                instructions=instructions(), toolset=toolset)
    print(f"Created agent {AGENT_NAME} ({agent.id})")
    return agent.id


def ask(client, agent_id: str, question: str) -> str:
    thread = client.threads.create()
    client.messages.create(thread_id=thread.id, role="user", content=question)
    run = client.runs.create_and_process(thread_id=thread.id, agent_id=agent_id)
    if run.status == "failed":
        return f"[run failed] {run.last_error}"
    msgs = list(client.messages.list(thread_id=thread.id))
    for m in msgs:
        if m.role == "assistant" and m.text_messages:
            return m.text_messages[-1].text.value
    return "[no assistant message]"


def local_smoke() -> None:
    """Exercise the three tools against the local synthetic data - no Azure needed."""
    print("\n--- search_work_iq (executive guidance) ---")
    r = json.loads(search_work_iq("renewal guidance", "executive_guidance"))
    for h in r["results"][:5]:
        print(f"  {h['date'][:10]}  {h['from']:<20} {h['subject'][:70]}")

    print("\n--- query_renewal_analytics (High risk) ---")
    r = json.loads(query_renewal_analytics("most at risk", risk_band="High", top=8))
    for s in r["segment_summary"]:
        print(f"  {s['segment']:<16} n={s['renewals_next_180d']:<3} "
              f"exposure=CAD {s['annual_revenue_exposure_cad']:>8,}  "
              f"avg likelihood {s['avg_renewal_likelihood_pct']}%")
    print()
    for x in r["renewals"]:
        print(f"  {x['full_name']:<22} {x['segment']:<16} "
              f"score {x['attrition_risk_score']:.2f}  "
              f"exposure CAD {x['annual_revenue_exposure_cad']:>7,}  "
              f"-> {x['recommended_offer']} ({x['required_approval_level']})")

    print("\n--- lookup_renewal_policy (approvals) ---")
    r = json.loads(lookup_renewal_policy("approval authority for a rate discount above 25 bps"))
    for p in r["policies"][:5]:
        print(f"  {p['id']}  {p['title']}  [{p['category']}]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--ask")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--chat", action="store_true")
    ap.add_argument("--local-smoke", action="store_true",
                    help="test the three tools against local data, no Azure")
    args = ap.parse_args()

    if args.local_smoke or not any([args.create, args.ask, args.demo, args.chat]):
        local_smoke()
        return

    client = get_client()
    with client:
        agent_id = ensure_agent(client)
        if args.create and not (args.ask or args.demo or args.chat):
            return
        if args.ask:
            print("\n" + ask(client, agent_id, args.ask))
        if args.demo:
            for q in DEMO_QUESTIONS:
                print(f"\n{'='*78}\nQ: {q}\n{'='*78}")
                print(ask(client, agent_id, q))
        if args.chat:
            print("Type a question, or 'quit'.")
            while True:
                q = input("\n> ").strip()
                if q.lower() in {"quit", "exit"}:
                    break
                if q:
                    print("\n" + ask(client, agent_id, q))


if __name__ == "__main__":
    main()
