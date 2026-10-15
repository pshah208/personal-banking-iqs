"""World-event scenarios layered with live Web IQ.

The governed preset library (sensitivities.json -> Fabric IQ market_scenarios)
fixes each world event's factor shock at "high" severity. This module asks the
Foundry agent - public web only - how severe each theme is *today*, with a dated,
sourced headline, and scales the governed shock by a fixed intensity table:

    dormant 0.25 · low 0.5 · elevated 0.75 · high 1.0 · severe 1.3

The agent only classifies severity; it never sets a number. If Web IQ is
unavailable the presets run at their governed baseline and say so.

Emerging-risk radar: the same call may return up to three market-relevant themes
that are NOT in the governed library. They are surfaced for review only - each is
mapped to the closest governed preset as a labelled proxy, and becomes a real
scenario only when someone adds it to sensitivities.json (and so to Fabric IQ).

Public information, identical for every user, so one cached answer is shared
(the run still goes through the caller's identity, like every agent call).
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
from .pb_data import PB

logger = logging.getLogger("bff.world_scenarios")

SENS = PB
INTENSITY: dict[str, float] = SENS.get("world_severity") or {
    "dormant": 0.25, "low": 0.5, "elevated": 0.75, "high": 1.0, "severe": 1.3}
WORLD = [p for p in SENS["presets"] if p.get("group") == "world"]
LIMITS = {f["id"]: (f["min"], f["max"], f["step"]) for f in SENS["factors"]}
PRESETS = {p["id"]: p for p in SENS["presets"]}
MAX_EMERGING = 3

TTL_SECONDS = int(os.getenv("WORLD_PULSE_TTL_MIN", "360")) * 60
FAILURE_TTL_SECONDS = 5 * 60
STATUSES = ("active", "emerging", "dormant")


def _prompt() -> str:
    themes = "\n".join(f'- id "{p["id"]}": {p["web_query"]}' for p in WORLD)
    return (
        "Use ONLY the public web for this answer (Grounding with Bing / web search). Do not query Work IQ, "
        "Fabric IQ or Foundry IQ and do not mention any internal data, clients or the Bank.\n"
        "For each theme below, search for the most recent reporting (last 30 days where possible) and assess how "
        "strongly each signal is showing up for Canadian households right now (rates, living costs, jobs, housing, lender pricing).\n"
        f"{themes}\n\n"
        "Then list up to three OTHER live household-finance signals (not covered above, and not geopolitical or disaster news) that could move Canadian "
        "household finances - mortgage rates, inflation, employment or house prices - in the next quarter. For each, name the closest existing scenario "
        f"id from this list, or \"none\": {', '.join(PRESETS)}.\n"
        "Reply with ONE JSON object and nothing else, in this exact shape:\n"
        '{"themes":[{"id":"<theme id>","status":"active|emerging|dormant",'
        '"severity":"dormant|low|elevated|high|severe","headline":"<one factual sentence, max 25 words>",'
        '"date":"YYYY-MM-DD","source":"<publisher name>","url":"<source url>"}],'
        '"emerging":[{"title":"<risk, max 6 words>","severity":"low|elevated|high|severe",'
        '"headline":"<one factual sentence, max 25 words>","why":"<market channel, max 20 words>",'
        '"closest":"<scenario id or none>","date":"YYYY-MM-DD","source":"<publisher>","url":"<source url>"}]}\n'
        "Include every theme id exactly once. Severity means how strongly the signal is present for Canadian household finances (low = faint, high = clearly under way). If you find "
        "nothing recent for a theme, use status dormant, severity low and say so in the headline."
    )


def _parse_frame(frame: str) -> tuple[str, Any]:
    event, data = "", None
    for line in frame.splitlines():
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                data = None
    return event, data


def _extract_json(text: str) -> dict[str, Any] | None:
    text = re.sub(r"【[^】]*】", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def scale(preset: dict[str, Any], severity: str) -> dict[str, float]:
    """Governed preset shock x intensity, snapped to the slider step and clamped to its range."""
    k = INTENSITY.get(severity, 1.0)
    out = {}
    for fid, v in preset["factors"].items():
        lo, hi, step = LIMITS[fid]
        x = round(v * k / step) * step
        out[fid] = round(max(lo, min(hi, x)), 2)
    return out


def _themes(found: dict[str, dict[str, Any]], live: bool) -> list[dict[str, Any]]:
    rows = []
    for p in WORLD:
        w = found.get(p["id"], {})
        sev = str(w.get("severity", "")).lower()
        sev = sev if sev in INTENSITY else "high"
        status = str(w.get("status", "")).lower()
        url = str(w.get("url") or "")
        rows.append({
            "id": p["id"], "name": p["name"], "note": p["note"], "channels": p["channels"],
            "status": status if status in STATUSES else ("unknown" if not live else "dormant"),
            "severity": sev, "intensity": INTENSITY[sev],
            "headline": str(w.get("headline") or "")[:220],
            "date": str(w.get("date") or "")[:10],
            "source": str(w.get("source") or "")[:80],
            "url": url if url.startswith("http") else "",
            "base_factors": p["factors"],
            "factors": scale(p, sev),
            "live": live and bool(w),
        })
    return rows


def _emerging(items: Any) -> list[dict[str, Any]]:
    out = []
    for e in items if isinstance(items, list) else []:
        if not isinstance(e, dict) or not str(e.get("title") or "").strip():
            continue
        title = str(e["title"]).strip()[:60]
        if any(title.lower() in (p["name"].lower(), p["id"]) for p in PRESETS.values()):
            continue
        sev = str(e.get("severity", "")).lower()
        sev = sev if sev in INTENSITY else "elevated"
        closest = str(e.get("closest") or "none")
        proxy = PRESETS.get(closest)
        url = str(e.get("url") or "")
        out.append({
            "title": title, "severity": sev,
            "headline": str(e.get("headline") or "")[:220], "why": str(e.get("why") or "")[:160],
            "date": str(e.get("date") or "")[:10], "source": str(e.get("source") or "")[:80],
            "url": url if url.startswith("http") else "",
            "closest": proxy["id"] if proxy else None, "closest_name": proxy["name"] if proxy else None,
            "proxy_factors": scale(proxy, sev) if proxy else None,
        })
        if len(out) == MAX_EMERGING:
            break
    return out


def baseline(detail: str = "") -> dict[str, Any]:
    return {"status": "baseline", "detail": detail or "Web IQ not yet queried.",
            "themes": _themes({}, live=False), "emerging": [], "intensity": INTENSITY}


async def _fetch(user: User) -> dict[str, Any]:
    text, citations, web_used, error = "", [], False, ""
    async for frame in run_agent(user, _prompt()):
        event, data = _parse_frame(frame)
        if not isinstance(data, dict):
            continue
        if event == "iq_active" and data.get("iq") == "web":
            web_used = True
        elif event == "message":
            text = data.get("text") or ""
            citations = [c for c in data.get("citations") or [] if c.get("url")]
        elif event == "error":
            error = f"{data.get('text', '')} {data.get('detail', '')}".strip()
    parsed = _extract_json(text) if text else None
    items = parsed.get("themes") if isinstance(parsed, dict) else None
    if not isinstance(items, list) or not items:
        return baseline(error[:300] or "Web IQ did not return a parsable assessment.")
    found = {str(t.get("id")): t for t in items if isinstance(t, dict)}
    return {
        "status": "live", "themes": _themes(found, live=True), "intensity": INTENSITY,
        "emerging": _emerging(parsed.get("emerging")),
        "webUsed": web_used or bool(citations), "citations": citations[:10],
        "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


_cache: dict[str, Any] = {}
_lock = asyncio.Lock()


async def world(user: User, refresh: bool = False) -> dict[str, Any]:
    hit = _cache.get("v")
    if hit and not refresh and time.monotonic() < hit["expires"]:
        return hit["value"]
    async with _lock:
        hit = _cache.get("v")
        if hit and not refresh and time.monotonic() < hit["expires"]:
            return hit["value"]
        try:
            value = await _fetch(user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("world pulse failed: %s", str(exc)[:200])
            value = baseline(str(exc)[:300])
        if value["status"] != "live" and hit and hit["value"].get("status") == "live":
            value = {**hit["value"], "stale": True}
        ttl = TTL_SECONDS if value["status"] == "live" else FAILURE_TTL_SECONDS
        _cache["v"] = {"value": value, "expires": time.monotonic() + ttl}
        return value


def cached() -> dict[str, Any]:
    """Last answer without triggering a fetch (or the governed baseline)."""
    hit = _cache.get("v")
    return hit["value"] if hit else baseline()
