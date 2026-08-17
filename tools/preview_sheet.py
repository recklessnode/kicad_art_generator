#!/usr/bin/env python3
"""Contact sheet of a .pretty library, rendered from the EMITTED geometry.

    python3 tools/preview_sheet.py output/RecklessArt.pretty -o sheet.png

Why not reuse emit_art --preview: that paints the quantiser's label array, which
is what the emitter was ASKED to draw. This paints what actually came out the
other end -- the polygons in the .kicad_mod, after simplification, hole
bridging and any area culling -- so a piece that lost its holes, or emitted
nothing at all, shows up here instead of looking fine.

Each fp_poly is written once per layer, so a tone that maps to two layers
(T2 = F.Cu + F.Mask) appears twice. Polygons are regrouped by the SET of layers
their geometry appears on and matched back to the palette recipe in
coupon_blocks.TONE_RECIPE, which recovers the tone exactly rather than guessing
a colour per layer. Tones partition the image, so the groups never overlap.

Rendering goes through SVG + cairosvg because the outlines are fractured
polygons that must be filled even-odd; a naive scanline fill closes the holes.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from w0_spike import TONES                       # noqa: E402
from coupon_blocks import TONE_RECIPE            # noqa: E402
import verify_art as V                           # noqa: E402

TONE_RGB = {t[0]: t[2] for t in TONES}
TONE_DESC = {t[0]: t[1] for t in TONES}
BOARD = TONE_RGB["T5"]

# recipe key "T1_silk" -> tone id "T1"
LAYERSET_TO_TONE = {frozenset(v): k.split("_")[0]
                    for k, v in TONE_RECIPE.items() if v}


def tone_groups(path: pathlib.Path):
    """-> {tone_id: [polygon, ...]}, plus any layer set with no recipe."""
    fp = V.load_footprint(path)
    by_geom: dict[tuple, list] = {}
    for _, it in V.polys_of(fp):
        key = tuple((round(x, 6), round(y, 6)) for x, y in it.pts)
        by_geom.setdefault(key, []).extend(it.layers)
    groups: dict[str, list] = {}
    unknown: dict[frozenset, int] = {}
    for pts, layers in by_geom.items():
        ls = frozenset(layers)
        tone = LAYERSET_TO_TONE.get(ls)
        if tone is None:
            unknown[ls] = unknown.get(ls, 0) + 1
            continue
        groups.setdefault(tone, []).append(pts)
    return groups, unknown, V.overall_bbox(fp)


def render(path: pathlib.Path, px: int):
    groups, unknown, bbox = tone_groups(path)
    if bbox is None:
        return None, {}, unknown
    x0, y0, x1, y1 = bbox
    w_mm, h_mm = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    pad = 0.04 * max(w_mm, h_mm)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    w_mm, h_mm = x1 - x0, y1 - y0
    scale = px / max(w_mm, h_mm)
    W, H = max(1, round(w_mm * scale)), max(1, round(h_mm * scale))

    body = []
    for tone, polys in sorted(groups.items()):
        r, g, b = TONE_RGB[tone]
        d = " ".join("M " + " L ".join(f"{x:.4f},{y:.4f}" for x, y in p) + " Z"
                     for p in polys)
        body.append(f'<path d="{d}" fill="rgb({r},{g},{b})" '
                    f'fill-rule="evenodd" stroke="none"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="{x0:.4f} {y0:.4f} {w_mm:.4f} {h_mm:.4f}">'
           f'<rect x="{x0:.4f}" y="{y0:.4f}" width="{w_mm:.4f}" '
           f'height="{h_mm:.4f}" fill="rgb{BOARD}"/>'
           + "".join(body) + "</svg>")
    import cairosvg
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=W, output_height=H)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    counts = {t: len(p) for t, p in groups.items()}
    return img, counts, unknown


def _font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "C:/Windows/Fonts/segoeui.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("library")
    ap.add_argument("-o", "--output", default="preview_sheet.png")
    ap.add_argument("--cell", type=int, default=340, help="art box, px")
    ap.add_argument("--cols", type=int, default=6)
    a = ap.parse_args(argv)

    lib = pathlib.Path(a.library)
    files = sorted(lib.glob("*.kicad_mod"))
    if not files:
        sys.exit(f"no .kicad_mod in {lib}")

    cell, cols = a.cell, a.cols
    labh = 46
    rows = (len(files) + cols - 1) // cols
    margin, gap = 28, 14
    title_h = 70
    W = margin * 2 + cols * cell + (cols - 1) * gap
    H = margin * 2 + title_h + rows * (cell + labh) + (rows - 1) * gap

    sheet = Image.new("RGB", (W, H), (16, 16, 18))
    dr = ImageDraw.Draw(sheet)
    f_title = _font(30)
    f_name = _font(19)
    f_sub = _font(15)

    dr.text((margin, margin), f"RecklessArt.pretty  --  {len(files)} footprints",
            font=f_title, fill=(238, 238, 234))

    problems = []
    for k, path in enumerate(files):
        r, c = divmod(k, cols)
        cx = margin + c * (cell + gap)
        cy = margin + title_h + r * (cell + labh + gap)
        dr.rectangle([cx, cy, cx + cell, cy + cell], fill=BOARD)
        img, counts, unknown = render(path, cell - 16)
        if img is None:
            problems.append(f"{path.stem}: EMPTY -- no geometry")
            dr.text((cx + 12, cy + cell // 2), "EMPTY", font=f_name,
                    fill=(255, 90, 90))
        else:
            img.thumbnail((cell - 16, cell - 16), Image.LANCZOS)
            sheet.paste(img, (cx + (cell - img.width) // 2,
                              cy + (cell - img.height) // 2))
        if unknown:
            problems.append(f"{path.stem}: layer set with no palette recipe: "
                            f"{[sorted(u) for u in unknown]}")
        dr.text((cx + 4, cy + cell + 6), path.stem, font=f_name,
                fill=(238, 238, 234))
        kb = path.stat().st_size / 1024.0
        tones = " ".join(f"{t}:{n}" for t, n in sorted(counts.items()))
        dr.text((cx + 4, cy + cell + 27), f"{kb:,.1f} kB   {tones}",
                font=f_sub, fill=(150, 150, 155))

    out = pathlib.Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    print(f"wrote {out}  ({W}x{H}, {out.stat().st_size:,} B)")
    for p in problems:
        print(f"  !! {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
