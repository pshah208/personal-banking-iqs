"""Web IQ market intelligence for the Cards book - competitor card offers.

The Foundry agent reads ONLY the public web for current Canadian credit-card
welcome offers and returns structured, dated, sourced rows. Internal use only
(market context for advisors and product owners); nothing here feeds a number in
the governed card book or a client-facing message (RP-016). Cached, shared by all
users, fetched under the caller's identity like every agent call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from .agent_client import run_agent
from .auth import User

logger = logging.getLogger("bff.card_market")
TTL = int(os.getenv("CARD_MARKET_TTL_MIN", "720")) * 60
CATEGORIES = ["Premium travel", "Premium rewards", "Cash back", "No annual fee", "Low rate"]

PROMPT = (
    "Use ONLY the public web for this answer (Grounding with Bing / web search). Do not query Work IQ, Fabric IQ or Foundry IQ "
    "and do not mention any internal data, clients or the Bank.\n"
    "Find the current (last 60 days) consumer credit-card offers in Canada for these categories: "
    + ", ".join(CATEGORIES) + ". For each category give up to two cards from different Canadian issuers with the headline welcome "
    "offer, annual fee and purchase interest rate as published.\n"
    "Then give up to three short market observations relevant to card retention (e.g. bonus inflation, fee waivers, cash-back rates).\n"
    "Reply with ONE JSON object and nothing else:\n"
    '{"offers":[{"category":"<one of the categories>","issuer":"<issuer>","card":"<card name>","welcome_offer":"<max 20 words>",'
    '"annual_fee":"<as published>","purchase_rate":"<as published>","date":"YYYY-MM-DD","source":"<publisher>","url":"<url>"}],'
    '"observations":[{"text":"<max 25 words>","source":"<publisher>","date":"YYYY-MM-DD","url":"<url>"}]}'
)

_cache: dict[str, Any] = {}
_lock = asyncio.Lock()


def _frame(f: str) -> tuple[str, Any]:
    ev, data = "", None
    for line in f.splitlines():
        if line.startswith("event: "):
            ev = line[7:].strip()
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                data = None
    return ev, data


def _parse(text: str) -> dict | None:
    text = re.sub(r"【[^】]*】", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def _clean(d: dict) -> dict:
    s = lambda v, n: str(v or "")[:n]  # noqa: E731
    offers = [{"category": s(o.get("category"), 30), "issuer": s(o.get("issuer"), 40), "card": s(o.get("card"), 60),
               "welcome_offer": s(o.get("welcome_offer"), 160), "annual_fee": s(o.get("annual_fee"), 30),
               "purchase_rate": s(o.get("purchase_rate"), 30), "date": s(o.get("date"), 10), "source": s(o.get("source"), 60),
               "url": s(o.get("url"), 300) if str(o.get("url", "")).startswith("http") else ""}
              for o in d.get("offers") or [] if isinstance(o, dict) and o.get("card")][:10]
    obs = [{"text": s(o.get("text"), 220), "source": s(o.get("source"), 60), "date": s(o.get("date"), 10),
            "url": s(o.get("url"), 300) if str(o.get("url", "")).startswith("http") else ""}
           for o in d.get("observations") or [] if isinstance(o, dict) and o.get("text")][:3]
    return {"offers": offers, "observations": obs}


def baseline(detail: str = "") -> dict[str, Any]:
    return {"status": "baseline", "detail": detail or "Web IQ not yet queried.", "offers": [], "observations": []}


async def _fetch(user: User) -> dict[str, Any]:
    text, err = "", ""
    async for f in run_agent(user, PROMPT):
        ev, data = _frame(f)
        if isinstance(data, dict):
            if ev == "message":
                text = data.get("text") or ""
            elif ev == "error":
                err = f"{data.get('text', '')} {data.get('detail', '')}".strip()
    d = _parse(text) if text else None
    if not isinstance(d, dict):
        return baseline(err[:300] or "Web IQ did not return a parsable answer.")
    return {"status": "live", **_clean(d), "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}


async def market(user: User, refresh: bool = False) -> dict[str, Any]:
    hit = _cache.get("v")
    if hit and not refresh and time.monotonic() < hit["exp"]:
        return hit["val"]
    async with _lock:
        hit = _cache.get("v")
        if hit and not refresh and time.monotonic() < hit["exp"]:
            return hit["val"]
        try:
            val = await _fetch(user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("card market failed: %s", str(exc)[:200])
            val = baseline(str(exc)[:300])
        if val["status"] != "live" and hit and hit["val"].get("status") == "live":
            val = {**hit["val"], "stale": True}
        _cache["v"] = {"val": val, "exp": time.monotonic() + (TTL if val["status"] == "live" else 300)}
        return val


def cached() -> dict[str, Any]:
    hit = _cache.get("v")
    return hit["val"] if hit else baseline()
