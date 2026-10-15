"""Print a Markdown summary of a brand pack (used for the GitHub job summary).

    python tools/brand/summarize_brand.py <bank-id>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BRAND_DIR = Path(__file__).resolve().parents[2] / "app" / "src" / "web" / "public" / "brand"


def main(bank_id: str) -> int:
    p = json.loads((BRAND_DIR / bank_id / "brand.json").read_text(encoding="utf-8"))
    c, s = p["colors"], p.get("source", {})
    print(f"## Brand: {p['name']} (`{bank_id}`)\n")
    print(f"Short name in copy: **{p['short']}** · aliases: {', '.join(p.get('aliases', []))}\n")
    print("| token | colour |\n|---|---|")
    for k, v in c.items():
        print(f"| `{k}` | `{v}` |")
    print()
    for label, key in (("Logo", "logo"), ("Icon", "icon"), ("Website", "website"),
                       ("Wikidata", "wikidata"), ("Primary colour from", "primaryFrom")):
        print(f"- {label}: `{s.get(key)}`")
    print("\n> Download the **brand-pack** artifact to check the images. If anything is off, re-run "
          "with `bank_domain` / `bank_short`, or run `tools/brand/fetch_brand.py` locally with "
          "`--logo` / `--primary`. Use bank marks only where you are permitted to.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
