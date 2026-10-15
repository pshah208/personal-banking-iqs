"""Resolve a bank's public branding and write a brand pack for the web app.

    python tools/brand/fetch_brand.py --bank "Royal Bank of Canada"
    python tools/brand/fetch_brand.py --bank "BMO" --domain bmo.com --short BMO
    python tools/brand/fetch_brand.py --bank "Contoso Bank" --logo ./logo.png --primary "#0b5cab" --offline
    python tools/brand/fetch_brand.py --list
    python tools/brand/fetch_brand.py --manifest-only --default cfc --exclusive

Given only a bank name, the script:

  1. looks the bank up on Wikidata (official name, short name, aliases,
     official website, logo file on Wikimedia Commons, official colour);
  2. reads the bank's home page for <meta name="theme-color">, the
     apple-touch-icon and site icons;
  3. downloads the logo (Wikimedia Commons render, else the site icon, else
     og:image) and derives a lockup, a top-bar mark and a favicon;
  4. picks a primary and accent colour (flag > Wikidata official colour >
     theme-color > dominant logo colour) and derives every shade the CSS uses;
  5. writes  app/src/web/public/brand/<id>/{brand.json,lockup.png,mark.png,favicon.png}
     and rebuilds  app/src/web/public/brand/brands.json  (the manifest the app
     loads at start-up), making the new bank the default.

Every value can be overridden by a flag, and --offline skips the network
entirely (pass --logo and --primary). Packs other than the fictional "cfc"
default are git-ignored: real bank marks are fetched at deploy time for the
deploying organisation's own demo and are not redistributed in the repo.
Use them only where you are permitted to.

Requires: requests, pillow  (pip install -r requirements.txt)
"""

from __future__ import annotations

import argparse
import colorsys
import datetime as dt
import io
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2]
BRAND_DIR = ROOT / "app" / "src" / "web" / "public" / "brand"
MANIFEST = BRAND_DIR / "brands.json"
DEFAULT_ID = "cfc"

UA = "mortgage-renewal-iqs-brand-fetch/1.0 (https://github.com/pshah208/mortgage-renewal-iqs)"
TIMEOUT = 20

# Wikidata classes that identify a bank or close relative (bank, commercial
# bank, retail bank, credit union, financial institution, savings bank, ...).
BANK_CLASSES = {"Q22687", "Q1349397", "Q1621043", "Q745877", "Q650241", "Q837171",
                "Q2111088", "Q4830453", "Q891723", "Q15911314", "Q6881511"}
HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ------------------------------------------------------------------ net ---

def _session():
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return s


def get_json(s, url: str, **params):
    r = s.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_bytes(s, url: str) -> bytes | None:
    try:
        r = s.get(url, timeout=TIMEOUT)
        if r.ok and r.content:
            return r.content
        log(f"   ! {url} -> HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001 - network faults fall through to the next source
        log(f"   ! {url} -> {e.__class__.__name__}")
    return None


# ------------------------------------------------------------- wikidata ---

WD_API = "https://www.wikidata.org/w/api.php"


def _claim_values(entity: dict, prop: str) -> list:
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if v is not None:
            out.append(v)
    return out


def wikidata_lookup(s, bank: str) -> dict:
    """Best Wikidata match for a bank name, or {} when nothing plausible is found."""
    try:
        hits = get_json(s, WD_API, action="wbsearchentities", search=bank, language="en",
                        type="item", limit=8, format="json").get("search", [])
        if not hits:
            return {}
        ents = get_json(s, WD_API, action="wbgetentities", ids="|".join(h["id"] for h in hits),
                        props="claims|labels|aliases|descriptions", languages="en",
                        format="json")["entities"]
    except Exception as e:  # noqa: BLE001
        log(f"   ! wikidata lookup failed: {e.__class__.__name__}")
        return {}

    def score(qid: str, rank: int) -> float:
        e = ents.get(qid, {})
        classes = {v.get("id") for v in _claim_values(e, "P31") if isinstance(v, dict)}
        desc = e.get("descriptions", {}).get("en", {}).get("value", "").lower()
        sc = 10 - rank
        if classes & BANK_CLASSES:
            sc += 20
        if any(w in desc for w in ("bank", "financial", "credit union", "lender")):
            sc += 12
        if _claim_values(e, "P856"):
            sc += 5
        if _claim_values(e, "P154"):
            sc += 5
        return sc

    best = max(((h["id"], i) for i, h in enumerate(hits)), key=lambda t: score(*t))
    if score(*best) < 20:
        log(f"   ! no Wikidata item for '{bank}' looks like a bank - continuing without it")
        return {}
    e = ents[best[0]]
    label = e.get("labels", {}).get("en", {}).get("value", bank)
    aliases = [a["value"] for a in e.get("aliases", {}).get("en", [])]
    shorts = [v.get("text") for v in _claim_values(e, "P1813")
              if isinstance(v, dict) and v.get("language") == "en"]
    sites = [v for v in _claim_values(e, "P856") if isinstance(v, str)]
    logos = [v for v in _claim_values(e, "P154") if isinstance(v, str)]
    color_hex = None
    color_items = [v.get("id") for v in _claim_values(e, "P6364") if isinstance(v, dict)]
    if color_items:
        try:
            ce = get_json(s, WD_API, action="wbgetentities", ids=color_items[0], props="claims",
                          format="json")["entities"][color_items[0]]
            hexes = [v for v in _claim_values(ce, "P465") if isinstance(v, str)]
            color_hex = f"#{hexes[0]}" if hexes else None
        except Exception:  # noqa: BLE001
            pass
    desc = e.get("descriptions", {}).get("en", {}).get("value", "")
    log(f"   wikidata {best[0]}: {label} ({desc})")
    return {"qid": best[0], "label": label, "aliases": aliases, "short": shorts[0] if shorts else None,
            "website": sites[0] if sites else None, "logo_file": logos[0] if logos else None,
            "color": color_hex}


def commons_png(s, filename: str, width: int = 1024) -> bytes | None:
    """PNG render of a Commons file (SVG logos are rasterised server-side)."""
    url = (f"https://commons.wikimedia.org/w/index.php?title=Special:Redirect/file/"
           f"{quote(filename)}&width={width}")
    return get_bytes(s, url)


# -------------------------------------------------------------- website ---

class _HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.theme: str | None = None
        self.icons: list[tuple[int, str]] = []
        self.og: str | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "theme-color" and a.get("content"):
                self.theme = self.theme or a["content"].strip()
            elif name == "og:image" and a.get("content"):
                self.og = self.og or a["content"].strip()
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower()
            if "icon" in rel and not a["href"].lower().split("?")[0].endswith(".svg"):
                m = re.match(r"(\d+)x\d+", a.get("sizes", ""))
                size = int(m.group(1)) if m else (180 if "apple-touch-icon" in rel else 16)
                self.icons.append((size, a["href"]))


def read_site(s, website: str) -> dict:
    try:
        r = s.get(website, timeout=TIMEOUT)
        base = r.url
        p = _HeadParser()
        p.feed(r.text[:400_000])
    except Exception as e:  # noqa: BLE001
        log(f"   ! could not read {website}: {e.__class__.__name__}")
        return {}
    icons = [urljoin(base, h) for _, h in sorted(p.icons, key=lambda t: -t[0])]
    log(f"   site {base}: theme-color={p.theme} icons={len(icons)}")
    return {"url": base, "theme": p.theme, "icons": icons, "og": urljoin(base, p.og) if p.og else None}


# --------------------------------------------------------------- images ---

def load_image(data: bytes | None):
    """RGBA image from bytes, or None for anything Pillow cannot decode (e.g. SVG)."""
    if not data:
        return None
    from PIL import Image

    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


def unmatte_white(im):
    """Turn a white background transparent, keeping anti-aliased edges."""
    from PIL import Image

    px = im.load()
    out = Image.new("RGBA", im.size)
    po = out.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a0 = px[x, y]
            a = max(255 - r, 255 - g, 255 - b)
            if a == 0 or a0 == 0:
                po[x, y] = (255, 255, 255, 0)
                continue
            f = 255 / a
            po[x, y] = (max(0, min(255, round(255 - (255 - r) * f))),
                        max(0, min(255, round(255 - (255 - g) * f))),
                        max(0, min(255, round(255 - (255 - b) * f))), min(a, a0))
    return out


def has_transparency(im) -> bool:
    lo, _ = im.getchannel("A").getextrema()
    return lo < 250


def corners_white(im) -> bool:
    w, h = im.size
    return all(min(im.getpixel(p)[:3]) > 235 for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)])


def trim(im):
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return im.crop(bbox) if bbox else im


def square(im, size: int, pad: float = 0.0):
    from PIL import Image

    inner = max(1, int(size * (1 - pad)))
    sc = min(inner / im.width, inner / im.height)
    w, h = max(1, round(im.width * sc)), max(1, round(im.height * sc))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(im.resize((w, h), Image.LANCZOS), ((size - w) // 2, (size - h) // 2))
    return canvas


def fit(im, max_w: int, max_h: int):
    from PIL import Image

    sc = min(max_w / im.width, max_h / im.height, 1.0)
    if sc == 1.0:
        return im
    return im.resize((max(1, round(im.width * sc)), max(1, round(im.height * sc))), Image.LANCZOS)


def whiten(im):
    """Mono-white silhouette with the alpha preserved (for the brand-coloured top bar)."""
    from PIL import Image

    white = Image.new("RGBA", im.size, (255, 255, 255, 255))
    white.putalpha(im.getchannel("A"))
    return white


def prepare(im):
    if im is None:
        return None
    if not has_transparency(im) and corners_white(im):
        im = unmatte_white(im)
    return trim(im)


def dominant_colours(im, n: int = 6) -> list[str]:
    """Saturated, non-neutral colours of an image, most frequent first, one per hue family."""
    small = im.copy()
    small.thumbnail((160, 160))
    counts: dict[tuple[int, int, int], int] = {}
    pixels = small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata()
    for r, g, b, a in pixels:
        if a < 200:
            continue
        _, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s < 0.25 or l < 0.08 or l > 0.92:
            continue
        key = (r // 8 * 8, g // 8 * 8, b // 8 * 8)
        counts[key] = counts.get(key, 0) + 1
    out: list[str] = []
    for (r, g, b), _ in sorted(counts.items(), key=lambda kv: -kv[1]):
        hx = "#%02x%02x%02x" % (r, g, b)
        if all(_hue_gap(hx, o) > 25 for o in out):
            out.append(hx)
        if len(out) >= n:
            break
    return out


# --------------------------------------------------------------- colour ---

def norm_hex(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    m = HEX.match(v)
    if m:
        return "#" + m.group(1).lower()
    m = re.match(r"^#?([0-9a-fA-F]{3})$", v)
    return "#" + "".join(c * 2 for c in m.group(1)).lower() if m else None


def _rgb(h: str) -> tuple[int, int, int]:
    n = int(h[1:], 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def _hue_gap(a: str, b: str) -> float:
    ha = colorsys.rgb_to_hls(*[c / 255 for c in _rgb(a)])[0] * 360
    hb = colorsys.rgb_to_hls(*[c / 255 for c in _rgb(b)])[0] * 360
    d = abs(ha - hb) % 360
    return min(d, 360 - d)


def mix(h: str, toward: str, t: float) -> str:
    a, b = _rgb(h), _rgb(toward)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def luminance(h: str) -> float:
    def lin(c):
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def usable_primary(h: str | None) -> bool:
    if not h:
        return False
    _, l, s = colorsys.rgb_to_hls(*[c / 255 for c in _rgb(h)])
    return s >= 0.2 and 0.08 <= l <= 0.85


def derive_colours(primary: str, accent: str | None) -> dict:
    # The top bar puts white text on the primary colour, so keep it dark enough.
    brand = primary
    for _ in range(12):
        if contrast(brand, "#ffffff") >= 3.0:
            break
        brand = mix(brand, "#000000", 0.12)
    accent = accent or "#333333"
    accent_ink = accent
    for _ in range(12):
        if contrast(accent_ink, "#ffffff") >= 4.5:
            break
        accent_ink = mix(accent_ink, "#000000", 0.15)
    return {
        "brand": brand,
        "brandDeep": mix(brand, "#000000", 0.25),
        "brandTint": mix(brand, "#ffffff", 0.9),
        "brandLine": mix(brand, "#ffffff", 0.75),
        "brandInk": mix(brand, "#000000", 0.55),
        "accent": accent,
        "accentInk": accent_ink,
        "accentFg": mix(brand, "#000000", 0.55) if luminance(accent) > 0.45 else "#ffffff",
    }


# ------------------------------------------------------------- manifest ---

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "bank"


def read_pack(d: Path) -> dict | None:
    f = d / "brand.json"
    if not f.is_file():
        return None
    try:
        p = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log(f"   ! skipping {f} - not valid JSON")
        return None
    p["id"] = d.name
    return p


def write_manifest(default: str | None = None, exclusive: bool = False) -> dict:
    packs = {d.name: p for d in sorted(BRAND_DIR.iterdir()) if d.is_dir() and (p := read_pack(d))}
    prev = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    default = default or prev.get("default") or DEFAULT_ID
    if default not in packs:
        raise SystemExit(f"no brand pack '{default}' under {BRAND_DIR}")
    if exclusive:
        order = [default]
    else:
        prev_order = [i for i in prev.get("order", []) if i in packs]
        order = [default] + [i for i in prev_order if i != default] + \
                [i for i in packs if i != default and i not in prev_order]
    doc = {
        "$comment": "Generated by tools/brand/fetch_brand.py - the bank brands this deployment offers.",
        "default": default,
        "order": order,
        "brands": [{k: v for k, v in packs[i].items() if k != "source"} for i in order],
    }
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    log(f"   manifest: default={default} order={order}")
    return doc


# ------------------------------------------------------------------ main ---

def build_pack(args) -> str:
    import PIL  # noqa: F401 - fail early with a clear message if pillow is missing

    bank = args.bank.strip()
    wd: dict = {}
    site: dict = {}
    s = None if args.offline else _session()

    if s:
        log(f"-> resolving '{bank}'")
        if not args.no_wikidata:
            wd = wikidata_lookup(s, bank)
        website = args.domain or wd.get("website")
        if website:
            if not urlparse(website).scheme:
                website = "https://" + website.strip("/")
            site = read_site(s, website)

    name = args.name or wd.get("label") or bank
    acronyms = [a for a in wd.get("aliases", []) if re.fullmatch(r"[A-Z][A-Z&]{1,5}", a)]
    query_is_shorter = bank.lower() != name.lower() and len(bank) < len(name)
    short = args.short or wd.get("short") or (acronyms[0] if acronyms else None) or \
        (bank if query_is_shorter else name)
    bank_id = slug(args.id or short)
    if bank_id == DEFAULT_ID and not args.id:
        bank_id = slug(name) if slug(name) != DEFAULT_ID else "cfc-custom"
    out = BRAND_DIR / bank_id
    out.mkdir(parents=True, exist_ok=True)

    def fetch(v: str | None) -> bytes | None:
        if not v:
            return None
        p = Path(v)
        if p.is_file():
            return p.read_bytes()
        return get_bytes(s, v) if s else None

    # ---- logo + icon sources (first decodable one wins) -----------------
    logo = icon = None
    logo_from = icon_from = None
    if args.logo:
        logo, logo_from = prepare(load_image(fetch(args.logo))), args.logo
    if args.icon:
        icon, icon_from = prepare(load_image(fetch(args.icon))), args.icon
    if s and logo is None and wd.get("logo_file"):
        logo, logo_from = prepare(load_image(commons_png(s, wd["logo_file"]))), f"commons:{wd['logo_file']}"
    if s and icon is None:
        candidates = list(site.get("icons", []))
        if site.get("url"):
            host = urlparse(site["url"]).hostname
            candidates.append(f"https://www.google.com/s2/favicons?domain={host}&sz=256")
        for u in candidates:
            icon = prepare(load_image(get_bytes(s, u)))
            if icon is not None and icon.width >= 32:
                icon_from = u
                break
            icon = None
    if logo is None and icon is not None:
        logo, logo_from = icon, icon_from
    if s and logo is None and site.get("og"):
        logo, logo_from = prepare(load_image(get_bytes(s, site["og"]))), site["og"]
    if logo is None:
        raise SystemExit(
            f"Could not find a logo for '{bank}'. Pass --logo <file-or-url> (and --domain if the "
            "website was not found), or use --offline with --logo and --primary.")

    # ---- colours --------------------------------------------------------
    logo_cols = dominant_colours(logo)
    primary = norm_hex(args.primary)
    primary_from = "flag" if primary else None
    for cand, src in ((wd.get("color"), "wikidata"), (site.get("theme"), "theme-color"),
                      (logo_cols[0] if logo_cols else None, "logo"),
                      ((dominant_colours(icon) or [None])[0] if icon is not None else None, "icon")):
        if primary:
            break
        if usable_primary(norm_hex(cand)):
            primary, primary_from = norm_hex(cand), src
    if not primary:
        primary, primary_from = "#1f4e8c", "fallback"
        log("   ! no brand colour found - using a neutral blue; pass --primary to set one")
    accent = norm_hex(args.accent)
    if not accent:
        others = [c for c in logo_cols if _hue_gap(c, primary) > 40]
        accent = others[0] if others else None
    colours = derive_colours(primary, accent)

    # ---- assets ---------------------------------------------------------
    lockup = fit(logo, 640, 256)
    aspect = logo.width / max(1, logo.height)
    mark_src = logo if 0.6 <= aspect <= 1.6 else (icon if icon is not None else logo)
    mark = square(mark_src, 128, pad=0.04)
    mark_cols = dominant_colours(mark, 1)
    # The mark sits on the brand-coloured top bar; a same-colour mark would vanish.
    if not mark_cols or contrast(mark_cols[0], colours["brand"]) < 2.0:
        mark = whiten(mark)
    favicon = square(icon if icon is not None else mark_src, 64, pad=0.04)

    lockup.save(out / "lockup.png", optimize=True)
    mark.save(out / "mark.png", optimize=True)
    favicon.save(out / "favicon.png", optimize=True)

    aliases = sorted({a.strip().lower() for a in [short, name, *wd.get("aliases", []), *(args.alias or [])]
                      if a and a.strip()})
    pack = {
        "name": name,
        "short": short,
        "aliases": aliases,
        "colors": colours,
        "assets": {"lockup": "lockup.png", "mark": "mark.png", "favicon": "favicon.png"},
        "source": {
            "query": bank,
            "wikidata": wd.get("qid"),
            "website": site.get("url"),
            "logo": logo_from,
            "icon": icon_from,
            "primaryFrom": primary_from,
            "retrieved": dt.date.today().isoformat(),
            "note": "Public brand marks retrieved for a synthetic demo. Confirm you may use them.",
        },
    }
    (out / "brand.json").write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    log(f"   wrote {out.relative_to(ROOT).as_posix()}  name={name!r} short={short!r} "
        f"brand={colours['brand']} accent={colours['accent']} (primary from {primary_from})")
    return bank_id


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bank", help="bank name to look up, e.g. 'Royal Bank of Canada'")
    ap.add_argument("--id", help="pack id and URL ?bank= value (default: slug of the short name)")
    ap.add_argument("--name", help="display name override (e.g. 'RBC Personal Banking')")
    ap.add_argument("--short", help="short name used in narrative copy (e.g. 'RBC')")
    ap.add_argument("--alias", action="append", help="extra name the bank goes by (repeatable)")
    ap.add_argument("--domain", help="official website, if Wikidata does not resolve it")
    ap.add_argument("--logo", help="logo file or URL (skips the logo lookup)")
    ap.add_argument("--icon", help="square icon file or URL (skips the site icon lookup)")
    ap.add_argument("--primary", help="primary brand colour, #rrggbb")
    ap.add_argument("--accent", help="accent colour, #rrggbb")
    ap.add_argument("--offline", action="store_true", help="no network; requires --logo and --primary")
    ap.add_argument("--no-wikidata", action="store_true", help="skip the Wikidata lookup")
    ap.add_argument("--no-default", action="store_true", help="add the pack without making it the default")
    ap.add_argument("--exclusive", action="store_true",
                    help="the manifest offers only the default bank (hides the in-app bank switcher)")
    ap.add_argument("--manifest-only", action="store_true", help="only rebuild brands.json from packs on disk")
    ap.add_argument("--default", help="with --manifest-only: the pack id to make the default")
    ap.add_argument("--list", action="store_true", help="list packs on disk and the manifest default")
    args = ap.parse_args(argv)

    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    if args.list:
        prev = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
        listed = set(prev.get("order", []))
        for d in sorted(BRAND_DIR.iterdir()):
            if d.is_dir() and (p := read_pack(d)):
                flag = "*" if d.name == prev.get("default") else ("+" if d.name in listed else " ")
                print(f"{flag} {d.name:<20} {p.get('name')}  ({p.get('colors', {}).get('brand')})")
        print("\n* default   + offered in the app switcher")
        return 0
    if args.manifest_only:
        write_manifest(args.default, args.exclusive)
        return 0
    if not args.bank:
        ap.error("--bank is required (or use --manifest-only / --list)")
    if args.offline and not (args.logo and args.primary):
        ap.error("--offline needs --logo and --primary")

    bank_id = build_pack(args)
    write_manifest(None if args.no_default else bank_id, args.exclusive)
    print(bank_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
