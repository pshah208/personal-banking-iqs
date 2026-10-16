"""Live card-processor stream - Fabric Eventstream -> Eventhouse (KQL) -> Cards book.

The processor simulator (data/fabric-iq/stream_processor_events.py) sends
authorisations to a Fabric Eventstream custom endpoint; the Eventstream lands
them in the Eventhouse table `auth_stream`, where KQL functions compute live
insights (data/fabric-iq/deploy_realtime.py). This module reads those functions
for the Cards book's live panel.

Configured by PROCESSOR_KQL_URI and PROCESSOR_KQL_DB. Authenticates with the
app's identity (DefaultAzureCredential: the container's managed identity in
Azure, the developer's az login locally), which needs Viewer on the Fabric
workspace. Unconfigured or unreachable, it reports "not connected" and the rest
of the Cards book is unaffected. SYNTHETIC data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from .pb_cards import ACC
from .pb_data import PB

logger = logging.getLogger("bff.stream")

KQL_URI = os.getenv("PROCESSOR_KQL_URI", "").rstrip("/")
KQL_DB = os.getenv("PROCESSOR_KQL_DB", "")
TTL = 8.0

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cred = None
_tok: dict[str, Any] = {"value": "", "expires": 0.0}


def configured() -> bool:
    return bool(KQL_URI and KQL_DB)


def _token() -> str:
    """Token for the Eventhouse, reused until five minutes before it expires."""
    global _cred
    if _tok["value"] and time.time() < _tok["expires"] - 300:
        return _tok["value"]
    if _cred is None:
        from azure.identity import DefaultAzureCredential
        _cred = DefaultAzureCredential()
    t = _cred.get_token(f"{KQL_URI}/.default")
    _tok.update(value=t.token, expires=float(t.expires_on))
    return t.token


def _tables(body: dict) -> list[list[dict[str, Any]]]:
    out = []
    for t in body.get("Tables", []):
        cols = [c["ColumnName"] for c in t.get("Columns", [])]
        out.append([dict(zip(cols, r)) for r in t.get("Rows", [])])
    return out


async def _query(csl: str) -> list[list[dict[str, Any]]]:
    tok = await asyncio.to_thread(_token)
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{KQL_URI}/v1/rest/query", headers={"Authorization": f"Bearer {tok}"},
                         json={"db": KQL_DB, "csl": csl})
    if r.status_code != 200:
        raise RuntimeError(f"KQL {r.status_code}: {r.text[:300]}")
    return _tables(r.json())


def _name(aid: str) -> dict[str, str]:
    a = ACC.get(aid)
    return {"customer_name": a["customer_name"], "product_name": a["product_name"]} if a else {"customer_name": "", "product_name": ""}


async def live(account: str = "") -> dict[str, Any]:
    src = {"eventstream": "es_card_processor", "eventhouse": "eh_card_processor", "database": KQL_DB, "table": "auth_stream",
           "uri": KQL_URI}
    if not configured():
        return {"connected": False, "source": src, "reason": "PROCESSOR_KQL_URI / PROCESSOR_KQL_DB not set"}
    key = account or "*"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    acct = account.replace('"', "")
    csl = (f'LiveAuthKpis(15m); LiveAuthKpis(24h); CardTestingLive(60m); DeclinesAtLimitLive(24h); '
           f'RecentAuths(25, "{acct}") | project event_ts, auth_id, account_id, merchant_name, merchant_country, amount_cad, '
           'pos_entry_mode, channel, response_code, response_text, decision, risk_score, scenario')
    try:
        k15, k24, testing, limit, recent = (await _query(csl))[:5]
    except Exception as e:  # noqa: BLE001 - the live panel degrades, the page does not
        logger.warning("live stream query failed: %s", e)
        return {"connected": False, "source": src, "reason": str(e)[:300]}
    out = {
        "connected": True, "source": src, "queried_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kpis_15m": k15[0] if k15 else {}, "kpis_24h": k24[0] if k24 else {},
        "card_testing": [{**r, **_name(r["account_id"]), "in_book": r["account_id"] in ACC} for r in testing],
        "declines_at_limit": [{**r, **_name(r["account_id"])} for r in limit],
        "recent": [{**r, **_name(r["account_id"])} for r in recent],
    }
    _cache[key] = (time.time(), out)
    return out


async def self_test() -> None:
    """Log once at start-up whether the live stream is reachable (visible in the container logs)."""
    if not configured():
        logger.info("live stream: not configured")
        return
    r = await live()
    if r["connected"]:
        logger.info("live stream: connected to %s/%s - %s events in 24h", KQL_URI, KQL_DB, r["kpis_24h"].get("events"))
    else:
        logger.warning("live stream: NOT connected - %s", r.get("reason"))


async def servicing_live(customer: str = "") -> dict[str, Any]:
    """Live mortgage-servicing events (es_mortgage_servicing -> svc_stream) for the renewal book."""
    src = {"eventstream": "es_mortgage_servicing", "eventhouse": "eh_card_processor", "database": KQL_DB, "table": "svc_stream",
           "uri": KQL_URI}
    if not configured():
        return {"connected": False, "source": src, "reason": "PROCESSOR_KQL_URI / PROCESSOR_KQL_DB not set"}
    key = f"svc:{customer or '*'}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    cust = customer.replace('"', "")
    csl = (f'ServicingKpis(24h); ServicingKpis(7d); PayoutRequestsLive(7d); ShoppingSignalsLive(14d); PadReturnsLive(30d); '
           f'RecentServicingEvents(25, "{cust}") | project event_ts, event_id, event_type, customer_id, renewal_id, amount_cad, '
           'counterparty, counterparty_type, detail, trigger_consent, scenario')
    try:
        k24, k7, payouts, shopping, pad, recent = (await _query(csl))[:6]
    except Exception as e:  # noqa: BLE001
        logger.warning("servicing stream query failed: %s", e)
        return {"connected": False, "source": src, "reason": str(e)[:300]}

    def nm(rows: list[dict]) -> list[dict]:
        return [{**r, "customer_name": PB["customers"].get(r["customer_id"], {}).get("full_name", "")} for r in rows]

    # Bureau detail is only shown for consented clients (RP-038).
    recent = [r if r.get("trigger_consent") != "N" or r.get("event_type") != "bureau.inquiry"
              else {**r, "counterparty": "withheld - no consent", "counterparty_type": ""} for r in recent]
    out = {"connected": True, "source": src, "queried_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "kpis_24h": k24[0] if k24 else {}, "kpis_7d": k7[0] if k7 else {},
           "payouts": nm(payouts), "shopping": nm(shopping), "pad_returns": nm(pad), "recent": nm(recent)}
    _cache[key] = (time.time(), out)
    return out
