"""
Generate the CFC Bank demo brand marks.

The mark is an original geometric device drawn from scratch here - a shield
with three ascending bars knocked out of it. Nothing is traced from, or
derived from, any real institution's logo.

Knocking the bars out to full transparency rather than painting them white is
deliberate: the white variant sits on the brand-blue top bar, and letting the
bar show through keeps the mark legible at 26px instead of flattening it into
a solid blob.

    python tools/make_brand.py

Writes the fictional default brand pack: public/brand/cfc/{lockup,mark,favicon}.png
(plus the neutral public/brand/favicon.png). Real banks are fetched with
tools/brand/fetch_brand.py at deploy time.
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

SIZE = 512
SS = 4  # supersample factor; the shield is all curves and needs the help
BRAND = (3, 70, 148, 255)
WHITE = (255, 255, 255, 255)

OUT = pathlib.Path(__file__).resolve().parent.parent / "public" / "brand"


def quad(p0, p1, p2, steps=64):
    """Quadratic bezier as a point list."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append((
            u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
            u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
        ))
    return out


def shield_outline():
    """Flat-shouldered shield, straight sides, tapering to a point."""
    left, right, top = 96, 416, 76
    shoulder, waist, tip = 30, 272, 452
    mid = (left + right) / 2

    pts = [(left + shoulder, top), (right - shoulder, top)]
    pts += quad((right - shoulder, top), (right, top), (right, top + shoulder))
    pts += [(right, waist)]
    pts += quad((right, waist), (right, tip - 40), (mid, tip))
    pts += quad((mid, tip), (left, tip - 40), (left, waist))
    pts += [(left, top + shoulder)]
    pts += quad((left, top + shoulder), (left, top), (left + shoulder, top))
    return pts


def bars():
    """Three ascending rounded bars, cut out of the shield."""
    width, gap, base, radius = 44, 28, 316, 14
    heights = (78, 116, 154)
    start = 256 - (3 * width + 2 * gap) / 2
    for i, h in enumerate(heights):
        x = start + i * (width + gap)
        yield (x, base - h, x + width, base), radius


def render(colour: tuple[int, int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.polygon([(x * SS, y * SS) for x, y in shield_outline()], fill=colour)

    # Cut the bars straight out of the alpha channel.
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    for (x0, y0, x1, y1), r in bars():
        md.rounded_rectangle(
            (x0 * SS, y0 * SS, x1 * SS, y1 * SS), radius=r * SS, fill=255
        )
    img.putalpha(
        Image.composite(Image.new("L", img.size, 0), img.getchannel("A"), mask)
    )

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    pack = OUT / "cfc"
    pack.mkdir(parents=True, exist_ok=True)
    blue = render(BRAND)
    blue.save(pack / "lockup.png")
    render(WHITE).save(pack / "mark.png")
    favicon = blue.resize((64, 64), Image.LANCZOS)
    favicon.save(pack / "favicon.png")
    favicon.save(OUT / "favicon.png")
    print(f"wrote the CFC Bank pack to {pack} (brand.json is hand-maintained)")


if __name__ == "__main__":
    main()
