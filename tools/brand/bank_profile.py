"""The bank this deployment is branded as, for the Python data and agent scripts.

The repository's synthetic copy (emails, meetings, policies, agent
instructions, story) is authored for the fictional "CFC Bank". Scripts that
push that copy somewhere a user will read it - Microsoft 365 (Work IQ), AI
Search (Foundry IQ), Fabric (Fabric IQ) and the Foundry agent - pass it
through `rebrand()` so it names the deploying bank instead.

Resolution order:
  1. BANK_NAME / BANK_SHORT environment variables (explicit override);
  2. BANK_ID environment variable -> app/src/web/public/brand/<id>/brand.json;
  3. the default in app/src/web/public/brand/brands.json
     (written by tools/brand/fetch_brand.py);
  4. CFC Bank.

    from bank_profile import active_bank, rebrand
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BRAND_DIR = ROOT / "app" / "src" / "web" / "public" / "brand"
AUTHORED = "CFC Bank"
_AUTHORED_RE = re.compile(r"\bCFC Bank\b")


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=1)
def active_bank() -> dict:
    """{'id', 'name', 'short'} for the deployed bank."""
    bank_id = os.environ.get("BANK_ID", "").strip().lower()
    if not bank_id:
        manifest = _read(BRAND_DIR / "brands.json") or {}
        bank_id = manifest.get("default") or "cfc"
    pack = _read(BRAND_DIR / bank_id / "brand.json") or {}
    name = os.environ.get("BANK_NAME") or pack.get("name") or AUTHORED
    short = os.environ.get("BANK_SHORT") or pack.get("short") or name
    return {"id": bank_id, "name": name, "short": short}


def rebrand_text(text: str) -> str:
    short = active_bank()["short"]
    return text if short == AUTHORED or not text else _AUTHORED_RE.sub(short, text)


def rebrand(value: Any) -> Any:
    """Deep-relabel every string in a JSON-shaped value."""
    if isinstance(value, str):
        return rebrand_text(value)
    if isinstance(value, list):
        return [rebrand(v) for v in value]
    if isinstance(value, dict):
        return {k: rebrand(v) for k, v in value.items()}
    return value


if __name__ == "__main__":
    print(json.dumps(active_bank()))
