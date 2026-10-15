"""Pause / resume the Fabric capacity behind Fabric IQ, from the top bar.

An F-SKU bills by the hour whether or not anyone is querying it, so the demo
needs an off switch that does not require the Azure portal. Calls go to ARM with
the app's managed identity, which holds a custom role scoped to this one
capacity that can only read, suspend and resume it (see
infra/modules/fabric-capacity-control.bicep).

Pausing takes Fabric IQ offline for every user, so every state change is logged
with the signed-in user's UPN, and FABRIC_CAPACITY_OPERATORS can restrict who
may change it (comma-separated UPNs; empty = any signed-in user, which is fine
because sign-in already requires an app-role assignment).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("bff.fabric_capacity")

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
API = "2023-11-01"

CAPACITY_ID = os.getenv("FABRIC_CAPACITY_ID", "").strip()
OPERATORS = {u.strip().lower() for u in os.getenv("FABRIC_CAPACITY_OPERATORS", "").split(",") if u.strip()}

# ARM states, mapped to what the UI shows.
_STEADY = {"Active": "active", "Paused": "paused"}
_TRANSIENT = {"Resuming": "resuming", "Pausing": "pausing", "Provisioning": "resuming",
              "Updating": "resuming", "Deleting": "pausing"}

_token: tuple[str, float] | None = None
_lock = asyncio.Lock()


async def _access_token() -> str:
    global _token
    async with _lock:
        if _token and _token[1] - 120 > time.time():
            return _token[0]

        def fetch():
            from azure.identity import DefaultAzureCredential
            cred = DefaultAzureCredential()
            try:
                return cred.get_token(ARM_SCOPE)
            finally:
                cred.close()

        tok = await asyncio.to_thread(fetch)
        _token = (tok.token, float(tok.expires_on))
        return tok.token


def can_operate(upn: str) -> bool:
    return not OPERATORS or (upn or "").lower() in OPERATORS


def _shape(body: dict[str, Any], upn: str) -> dict[str, Any]:
    raw = (body.get("properties") or {}).get("state", "Unknown")
    return {
        "configured": True,
        "name": body.get("name") or CAPACITY_ID.rsplit("/", 1)[-1],
        "sku": (body.get("sku") or {}).get("name", ""),
        "region": body.get("location", ""),
        "rawState": raw,
        "state": _STEADY.get(raw) or _TRANSIENT.get(raw) or "unknown",
        "canOperate": can_operate(upn),
    }


async def status(upn: str) -> dict[str, Any]:
    if not CAPACITY_ID:
        return {"configured": False, "state": "unknown", "canOperate": False}
    try:
        token = await _access_token()
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{ARM}{CAPACITY_ID}?api-version={API}",
                                 headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            logger.warning("capacity status %s: %s", r.status_code, r.text[:300])
            return {"configured": True, "state": "unknown", "canOperate": False,
                    "error": f"ARM {r.status_code}"}
        return _shape(r.json(), upn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("capacity status failed: %s", str(exc)[:300])
        return {"configured": True, "state": "unknown", "canOperate": False,
                "error": "Capacity status unavailable"}


async def change(action: str, upn: str) -> dict[str, Any]:
    """Start a suspend or resume. ARM returns 202 and completes asynchronously."""
    if action not in ("suspend", "resume"):
        raise ValueError("action must be suspend or resume")
    if not CAPACITY_ID:
        raise PermissionError("No Fabric capacity is configured for this app.")
    if not can_operate(upn):
        raise PermissionError("You are not permitted to change the Fabric capacity.")

    token = await _access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{ARM}{CAPACITY_ID}/{action}?api-version={API}",
                              headers={"Authorization": f"Bearer {token}"})
    logger.info("fabric capacity %s requested by %s -> %s", action, upn, r.status_code)
    if r.status_code not in (200, 202):
        # A suspend on an already-paused capacity (or the reverse) is a 400 from
        # ARM; report the real state rather than an error.
        current = await status(upn)
        if current.get("state") in ("paused", "active"):
            return {**current, "note": r.text[:200]}
        raise RuntimeError(f"ARM {r.status_code}: {r.text[:300]}")

    current = await status(upn)
    # ARM can report the old steady state for a moment after accepting; show the
    # transition the user asked for so the UI does not appear to ignore the click.
    if current.get("state") in ("active", "paused"):
        current["state"] = "pausing" if action == "suspend" else "resuming"
    return current
