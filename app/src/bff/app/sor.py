"""Systems of record - shared framework for simulated line-of-business systems.

Each book that talks to a system of record (the card processor for Cards, the
mortgage servicing platform for the renewal book) plugs in a subclass of
`SystemOfRecord`. The framework owns what must behave identically everywhere:

  * vendor profile  - labels and API shape only, chosen at deploy time;
  * guarded actions - preview the vendor-style request and the policy guards,
                      execute only when every guard passes and a named human
                      approver (the signed-in user, never a client value) is given;
  * audit log       - per record: request, response, approver, reason, reference;
  * event bus       - one stream across systems, newest first, so a household's
                      card and mortgage events can be read together.

Nothing leaves the BFF: every system here is a simulator over synthetic data.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

_lock = threading.RLock()
_bus: dict[str, Any] = {"events": [], "seq": 0}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def publish(system: str, source: str, key: str, kind: str, detail: str, ref: str) -> dict[str, Any]:
    with _lock:
        _bus["seq"] += 1
        e = {"id": f"EVT-{_bus['seq']:05d}", "ts": _now(), "type": kind, "system": system, "account_id": key,
             "detail": detail, "ref": ref, "source": source}
        _bus["events"].append(e)
        return e


def events(n: int = 20, system: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        live = [e for e in reversed(_bus["events"]) if system is None or e["system"] == system]
    return live[:n]


class SystemOfRecord:
    """Base class: subclasses define `system`, `actions` and the three hooks."""

    system = "sor"
    ref_prefix = "SOR"
    actions: dict[str, dict[str, Any]] = {}

    def __init__(self) -> None:
        self.overrides: dict[str, dict[str, Any]] = defaultdict(dict)
        self.log: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._refs = 0

    # ------------------------------------------------------------ hooks ---
    def profile(self) -> dict[str, Any]:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def request(self, key: str, action: str, reason: str) -> dict[str, Any]:
        """Vendor-style request (method, url, headers, body)."""
        raise NotImplementedError

    def guards(self, key: str, action: str) -> list[dict[str, str]]:
        """Policy guards; any `block` stops execution."""
        raise NotImplementedError

    def apply(self, key: str, action: str, req: dict[str, Any], approver: str) -> tuple[int, dict[str, Any], str, str]:
        """Change simulator state; return (http status, response body, event type, event detail)."""
        raise NotImplementedError

    def on_reset(self) -> None:
        """Clear subclass-specific state."""

    # ------------------------------------------------------------ shared ---
    @staticmethod
    def guard(rule: str, name: str, ok: bool, detail: str) -> dict[str, str]:
        return {"rule": rule, "name": name, "status": "pass" if ok else "block", "detail": detail}

    def done(self, key: str, actions: list[str]) -> list[str]:
        return [f"{e['label']} · {e['approver']} · {e['reference']}" for e in self.log[key] if e["action"] in actions]

    def allowed(self, key: str, actions: list[str]) -> list[str]:
        return [a for a in actions if not any(g["status"] == "block" for g in self.guards(key, a))]

    def run_action(self, key: str, action: str, *, reason: str = "", approver: str = "", execute: bool = False) -> dict[str, Any]:
        if not self.exists(key):
            raise KeyError(key)
        if action not in self.actions:
            raise ValueError(f"unknown action '{action}'")
        spec = self.actions[action]
        with _lock:
            req = self.request(key, action, reason)
            guards = [self.guard(spec.get("policy", "RP-035"), "Human approval", True,
                                 "A named colleague must approve before the request is sent.")] + self.guards(key, action)
            blocked = any(g["status"] == "block" for g in guards)
            result: dict[str, Any] = {"action": action, "label": spec["label"], "effect": spec["effect"], "request": req,
                                      "guards": guards, "verdict": "blocked" if blocked else "ready", "executed": False}
            if not execute:
                return result
            if blocked:
                result["error"] = "Blocked by policy - nothing was sent."
                return result
            if not approver.strip():
                result["error"] = f"A named approver is required ({spec.get('policy', 'RP-035')})."
                return result
            self._refs += 1
            ref = f"{self.ref_prefix}-{key.split('-')[-1]}-{self._refs:05d}"
            status, body, kind, detail = self.apply(key, action, req, approver)
            event = publish(self.system, self.profile()["name"], key, kind, detail, ref)
            response = {"status": status, "body": {"reference": ref, **body}}
            self.log[key].append({"ts": event["ts"], "action": action, "label": spec["label"], "approver": approver,
                                  "reason": reason, "reference": ref, "request": req, "response": response, "event": event})
            result.update(executed=True, response=response, event=event)
            return result

    def reset(self) -> None:
        with _lock:
            self.overrides.clear()
            self.log.clear()
            self._refs = 0
            _bus["events"] = [e for e in _bus["events"] if e["system"] != self.system]
            self.on_reset()
