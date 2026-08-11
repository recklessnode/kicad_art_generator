#!/usr/bin/env python3
"""Coupon blocks beyond the ladders: tone patches, buried wedges, T8 windows,
T9 cutouts, registration, and shading ramps. Issue #6.

Companion to coupon_ladders.py, which covers minimum-feature, hatch-pitch and
microtext. Split only for readability; run both to fill RecklessArt.pretty.

Layer recipes come straight from the palette table in docs/pcb-palette.md.

Usage:  python coupon_blocks.py -o RecklessArt.pretty
"""

import argparse
import math
import pathlib

from coupon_ladders import Fp, block_label

# T5 is the background and is drawn as NOTHING. It still gets a labelled square
# on silk so the coupon carries a reference patch of bare board to sample.
TONE_RECIPE = {
    "T1_silk":        ["F.SilkS"],
    "T2_enig":        ["F.Cu", "F.Mask"],
    "T3_fr4":         ["F.Mask"],
    "T4_fr4_buried":  ["F.Mask", "In1.Cu"],
    "T5_mask":        [],
    "T6_mask_cu":     ["F.Cu"],
    "T7_mask_buried": ["In1.Cu"],
}


def tone_patches(fp, x0, y0, size=8.0, gap=3.0):
    """8 mm patches — big enough to sample well inside the edge (issue #1)."""
    block_label(fp, "TONE PATCHES 8mm - sample well inside the edge", x0, y0 - 1.6)
    x = x0
    for name, layers in TONE_RECIPE.items():
        for layer in layers:
            fp.rect(x, y0, size, size, layer)
        if not layers:  # T5: outline only, so the empty patch is findable
            for a, b in (((x, y0), (x + size, y0)), ((x + size, y0), (x + size, y0 + size)),
                         ((x + size, y0 + size), (x, y0 + size)), ((x, y0 + size), (x, y0))):
                fp.line(a[0], a[1], b[0], b[1], 0.12, "F.SilkS")
        fp.text(name, x, y0 + size + 0.9, 0.9, "F.SilkS")
        x += size + gap
    return y0 + size + 3.0


def buried_wedge(fp, x0, y0, length=24.0, w0=3.0, w1=0.2, over_mask=True):
    """In1 copper narrowing 3.0 -> 0.2 mm.

    Continuous rather than stepped because the wanted answer is a threshold —
    where does shadow blur through 0.1 mm of prepreg swallow the feature — not
    a go/no-go at named widths.
    """
    tag = "T7 under mask" if over_mask else "T4 under opening"
    block_label(fp, f"BURIED WEDGE {tag} 3.0-0.2mm", x0, y0 - 1.6)
    steps = 48
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        w = (w0 + (w1 - w0) * t0 + w0 + (w1 - w0) * t1) / 2
        xa, xb = x0 + length * t0, x0 + length * t1
        fp.rect(xa, y0 - w / 2, xb - xa, w, "In1.Cu")
        if not over_mask:
            fp.rect(xa, y0 - w / 2 - 0.2, xb - xa, w + 0.4, "F.Mask")
    return y0 + w0 / 2 + 2.5


def windows(fp, x0, y0):
    """T8. Mask opened on BOTH faces.

    Copper keepouts are deliberately NOT emitted here: a footprint-borne keepout
    segfaults ZONE_FILLER (see the audit), so this places the mask apertures and
    marks the keepout outline on Dwgs.User for a rule area to be drawn on the
    board. Safer, and the board owner is drawing the board anyway.
    """
    block_label(fp, "T8 WINDOWS - draw Cu keepouts on the board, outline on Dwgs.User",
                x0, y0 - 1.6)
    x = x0
    for s in (2.0, 4.0, 8.0, 16.0):
        fp.rect(x, y0, s, s, "F.Mask")
        fp.rect(x, y0, s, s, "B.Mask")
        for a, b in (((x, y0), (x + s, y0)), ((x + s, y0), (x + s, y0 + s)),
                     ((x + s, y0 + s), (x, y0 + s)), ((x, y0 + s), (x, y0))):
            fp.line(a[0], a[1], b[0], b[1], 0.12, "Dwgs.User")
        fp.text(f"{s:.0f}mm", x, y0 + s + 0.9, 0.9, "F.SilkS")
        x += s + 3.0

    # The pair sweep is the important one: it measures BLEED, which sets the
    # minimum spacing between windows and decides whether T8 renders a shape or
    # only a blob.
    y = y0 + 20.0
    fp.text("BLEED PAIRS - gap 1/2/3/5mm", x0, y - 1.2, 0.9, "F.SilkS")
    x = x0
    for g in (1.0, 2.0, 3.0, 5.0):
        for k in (0, 1):
            xx = x + k * (4.0 + g)
            fp.rect(xx, y, 4.0, 4.0, "F.Mask")
            fp.rect(xx, y, 4.0, 4.0, "B.Mask")
        fp.text(f"{g:.0f}", x, y + 5.0, 0.9, "F.SilkS")
        x += 8.0 + g + 3.0
    return y + 8.0


def _rounded_rect_pts(x, y, s, r, seg=8):
    if r <= 0:
        return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]
    pts = []
    for cx, cy, a0 in ((x + r, y + r, 180), (x + s - r, y + r, 270),
                       (x + s - r, y + s - r, 0), (x + r, y + s - r, 90)):
        for k in range(seg + 1):
            a = math.radians(a0 + k * 90 / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return pts


def cutouts(fp, x0, y0):
    """T9 on Edge.Cuts. Sharp vs r0.5 vs r1.0 shows what the router actually
    does to an inside corner it cannot cut."""
    block_label(fp, "T9 CUTOUTS sharp / r0.5 / r1.0 + slots 1.0 / 0.8", x0, y0 - 1.6)
    x = x0
    for r in (0.0, 0.5, 1.0):
        pts = _rounded_rect_pts(x, y0, 6.0, r)
        for i in range(len(pts) - 1):
            fp.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.1, "Edge.Cuts")
        fp.text(f"r{r:.1f}", x, y0 + 6.9, 0.9, "F.SilkS")
        x += 10.0
    for w in (1.0, 0.8):
        pts = [(x, y0), (x + 8.0, y0), (x + 8.0, y0 + w), (x, y0 + w), (x, y0)]
        for i in range(len(pts) - 1):
            fp.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.1, "Edge.Cuts")
        fp.text(f"slot{w:.1f}", x, y0 + w + 1.2, 0.9, "F.SilkS")
        x += 11.0
    return y0 + 10.0


def registration(fp, x0, y0):
    """Mask openings offset from their copper. Measures the fab's real
    registration rather than its published tolerance."""
    block_label(fp, "REGISTRATION - mask offset 0 / .05 / .10 / .15mm", x0, y0 - 1.6)
    x = x0
    for off in (0.0, 0.05, 0.10, 0.15):
        fp.rect(x, y0, 4.0, 4.0, "F.Cu")
        fp.rect(x + off, y0 + off, 4.0, 4.0, "F.Mask")
        fp.text(f"{off:.2f}", x, y0 + 4.9, 0.9, "F.SilkS")
        x += 7.0
    return y0 + 7.0


def shading_fields(fp, x0, y0, block=10.0):
    """Stipple and hatch as rectangular duty ramps rather than a logo.

    Deliberate: a calibration measurement wants a monotonic sweep it can read a
    threshold off. Logo versions come with the asset pipeline.
    """
    block_label(fp, "STIPPLE (Cu) + HATCH (silk), duty 10-90%", x0, y0 - 1.6)
    pitch, n = 0.5, int(block / 0.5)
    for i in range(n):
        for j in range(n):
            duty = 0.10 + 0.80 * (j / max(n - 1, 1))
            r = (pitch * 0.48) * math.sqrt(duty)
            if 2 * r < 0.10:          # below copper minimum: omit, do not fake
                continue
            cx = x0 + j * pitch + pitch / 2
            cy = y0 + i * pitch + pitch / 2
            fp.rect(cx - r, cy - r, 2 * r, 2 * r, "F.Cu")
            fp.rect(cx - r, cy - r, 2 * r, 2 * r, "F.Mask")
    fp.text("stipple Cu 0.5mm", x0, y0 + block + 0.9, 0.9, "F.SilkS")

    x2, hp = x0 + block + 4.0, 0.4
    m = int(block / hp)
    for i in range(m):
        duty = 0.10 + 0.80 * (i / max(m - 1, 1))
        fp.line(x2, y0 + i * hp, x2 + block, y0 + i * hp,
                max(hp * duty, 0.05), "F.SilkS")
    fp.text("hatch silk 0.4mm", x2, y0 + block + 0.9, 0.9, "F.SilkS")
    return y0 + block + 3.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--outdir", default="RecklessArt.pretty")
    a = ap.parse_args()
    out = pathlib.Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)

    built = []

    fp = Fp("cal_tones")
    y = tone_patches(fp, 0, 0)
    registration(fp, 0, y + 3.0)
    built.append((fp, "cal_tones"))

    fp = Fp("cal_buried")
    y = buried_wedge(fp, 0, 4.0, over_mask=True)
    buried_wedge(fp, 0, y + 5.0, over_mask=False)
    built.append((fp, "cal_buried"))

    fp = Fp("cal_windows")
    windows(fp, 0, 0)
    built.append((fp, "cal_windows"))

    fp = Fp("cal_cutouts")
    cutouts(fp, 0, 0)
    built.append((fp, "cal_cutouts"))

    fp = Fp("cal_shading")
    shading_fields(fp, 0, 0)
    built.append((fp, "cal_shading"))

    for fp, name in built:
        p = out / f"{name}.kicad_mod"
        p.write_text(fp.dumps(), encoding="utf-8")
        print(f"  {p}  {p.stat().st_size:,} B")


if __name__ == "__main__":
    main()
