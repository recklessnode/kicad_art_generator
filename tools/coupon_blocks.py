#!/usr/bin/env python3
"""Coupon blocks beyond the ladders: tone patches, buried wedges, T8 windows,
T9 cutouts, registration, and shading ramps. Issue #6.

Companion to coupon_ladders.py, which covers minimum-feature, hatch-pitch and
microtext. Split only for readability; run both to fill RecklessArt.pretty.

Layer recipes come straight from the palette table in docs/pcb-palette.md, and
so do the fabrication floors — imported from coupon_ladders rather than
restated, so there is one number per floor in the tree.

Usage:  python coupon_blocks.py -o RecklessArt.pretty
"""

import argparse
import math
import pathlib

from coupon_ladders import (
    FLOOR_COPPER, FLOOR_MASK_DAM, FLOOR_SILK, LABEL_H, SWEEP_MIN,
    Fp, block_label, report_floors, write_footprint,
)

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
            # This outline is the ONLY thing marking the T5 patch, so it is the
            # last line on the coupon that may be allowed to drop out. At the
            # silk floor, never under it.
            for a, b in (((x, y0), (x + size, y0)), ((x + size, y0), (x + size, y0 + size)),
                         ((x + size, y0 + size), (x, y0 + size)), ((x, y0 + size), (x, y0))):
                fp.line(a[0], a[1], b[0], b[1], FLOOR_SILK, "F.SilkS")
        fp.text(name, x, y0 + size + 0.9, LABEL_H, "F.SilkS")
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
        # Dwgs.User is documentation, never fabricated, so no floor applies —
        # 0.12 mm here is a drawing weight, not a feature size.
        for a, b in (((x, y0), (x + s, y0)), ((x + s, y0), (x + s, y0 + s)),
                     ((x + s, y0 + s), (x, y0 + s)), ((x, y0 + s), (x, y0))):
            fp.line(a[0], a[1], b[0], b[1], 0.12, "Dwgs.User")
        fp.text(f"{s:.0f}mm", x, y0 + s + 0.9, LABEL_H, "F.SilkS")
        x += s + 3.0

    # The pair sweep is the important one: it measures BLEED, which sets the
    # minimum spacing between windows and decides whether T8 renders a shape or
    # only a blob.
    y = y0 + 20.0
    fp.text("BLEED PAIRS - gap 1/2/3/5mm", x0, y - 1.2, LABEL_H, "F.SilkS")
    x = x0
    for g in (1.0, 2.0, 3.0, 5.0):
        for k in (0, 1):
            xx = x + k * (4.0 + g)
            fp.rect(xx, y, 4.0, 4.0, "F.Mask")
            fp.rect(xx, y, 4.0, 4.0, "B.Mask")
        fp.text(f"{g:.0f}", x, y + 5.0, LABEL_H, "F.SilkS")
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
    # On Edge.Cuts the fabricated feature is the routed slot width, not the
    # stroke, so no stroke floor applies; 0.1 mm is a drawing weight.
    x = x0
    for r in (0.0, 0.5, 1.0):
        pts = _rounded_rect_pts(x, y0, 6.0, r)
        for i in range(len(pts) - 1):
            fp.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.1, "Edge.Cuts")
        fp.text(f"r{r:.1f}", x, y0 + 6.9, LABEL_H, "F.SilkS")
        x += 10.0
    for w in (1.0, 0.8):
        pts = [(x, y0), (x + 8.0, y0), (x + 8.0, y0 + w), (x, y0 + w), (x, y0)]
        for i in range(len(pts) - 1):
            fp.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.1, "Edge.Cuts")
        fp.text(f"slot{w:.1f}", x, y0 + w + 1.2, LABEL_H, "F.SilkS")
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
        fp.text(f"{off:.2f}", x, y0 + 4.9, LABEL_H, "F.SilkS")
        x += 7.0
    return y0 + 7.0


def shading_fields(fp, x0, y0, block=10.0):
    """Stipple and hatch as rectangular duty ramps rather than a logo.

    Deliberate: a calibration measurement wants a monotonic sweep it can read a
    threshold off. Logo versions come with the asset pipeline.

    NEITHER RAMP IS CLAMPED AT ITS FABRICATION LIMIT, and both are ticked and
    labelled on silk where they cross it. The reasoning:

      * The palette gives the mask-dam minimum as "roughly 0.1 mm", and derives
        the 60-70 % duty cap from it. "Roughly" is precisely the kind of number
        a coupon exists to replace with a measured one. Clamping the ramp at
        the estimate would freeze the estimate in place — the board would come
        back proving only that 0.1 mm works, which is already assumed.
      * A washed-out dam is not an invisible failure. It collapses the hatch
        into flat T2, which is obvious on the returned board and is exactly the
        threshold being sought. Sweeping past a limit and reading where it
        breaks is what every other block on this coupon does; clamping would
        make this the one block that refuses to answer its own question.
      * The risk clamping guards against is a sub-floor feature being mistaken
        for an intended tone. A silk tick at the crossing, plus the range
        printed in the caption, removes that risk without removing the data.

    So: full ramp, labelled crossings. Silk markers are kept clear of the mask
    openings — silk over an opening is stripped by the fab.
    """
    # Vertical stack above the field, laid out with >= 0.4 mm between silk
    # items: block label (h 1.2) / crossing label (h 0.9) / tick / field.
    # A coupon that polices the silk floor cannot crowd its own annotation
    # under it.
    block_label(fp, "STIPPLE (Cu+mask) + HATCH (silk), duty 10-90%", x0, y0 - 3.35)

    # --- stipple: copper squares under matching mask openings (T2) ----------
    pitch, n = 0.5, int(block / 0.5)

    def duty_of(j):
        return 0.10 + 0.80 * (j / max(n - 1, 1))

    def r_of(duty):
        return (pitch * 0.48) * math.sqrt(duty)

    # dam = pitch - 2r and r = pitch*0.48*sqrt(duty), so the dam minimum fixes
    # a duty exactly. At pitch 0.5 / dam 0.10 this is 0.694 -- the palette's
    # "caps mask-hatch duty cycle at roughly 60-70%", arrived at from geometry.
    duty_dam = ((pitch - FLOOR_MASK_DAM) / (2 * pitch * 0.48)) ** 2
    j_dam = next((j for j in range(n) if duty_of(j) > duty_dam), n)

    for i in range(n):
        for j in range(n):
            r = r_of(duty_of(j))
            if 2 * r < FLOOR_COPPER:  # below copper minimum: omit, do not fake
                continue
            cx = x0 + j * pitch + pitch / 2
            cy = y0 + i * pitch + pitch / 2
            # The dot itself stays above the copper/mask floor across the whole
            # ramp; it is the DAM BETWEEN dots that goes under. A gap is not
            # visible from inside a single write call, so the writer's floor
            # guard cannot see this one -- verify_art.py's clearance check is
            # what catches it, and the tick below is what declares it.
            fp.rect(cx - r, cy - r, 2 * r, 2 * r, "F.Cu")
            fp.rect(cx - r, cy - r, 2 * r, 2 * r, "F.Mask")

    # Tick label is kept to five characters on purpose: the sub-minimum region
    # is only (n - j_dam) * pitch wide, and a long string here would run right
    # across the hatch field. The full statement goes in the caption stack.
    if j_dam < n:
        xc = x0 + j_dam * pitch
        fp.line(xc, y0 - 1.05, xc, y0 - 0.30, FLOOR_SILK, "F.SilkS")
        fp.text(f"<{FLOOR_MASK_DAM:.2f}", xc, y0 - 1.90, LABEL_H, "F.SilkS")

    # --- hatch: silk line-width ramp ----------------------------------------
    x2, hp = x0 + block + 4.0, 0.4
    m = int(block / hp)

    def w_of(i):
        return max(hp * (0.10 + 0.80 * (i / max(m - 1, 1))), SWEEP_MIN)

    for i in range(m):
        fp.line(x2, y0 + i * hp, x2 + block, y0 + i * hp, w_of(i), "F.SilkS",
                allow_below_floor=True)

    # Both ends of this ramp are outside what silk holds: the low end is a
    # stroke under the floor, the high end leaves a GAP under it (the doc's
    # knockout note -- "ink bleeds inward and can close a fine gap"). Tick both
    # crossings, to the right of the field where nothing else is drawn.
    i_thin = next((i for i in range(m) if w_of(i) >= FLOOR_SILK), None)
    i_gap = next((i for i in range(m) if hp - w_of(i) < FLOOR_SILK), None)
    xr = x2 + block + 1.0
    for ii, tag in ((i_thin, f"stroke >= {FLOOR_SILK:.2f}"),
                    (i_gap, f"gap < {FLOOR_SILK:.2f}")):
        if ii is None:
            continue
        yy = y0 + ii * hp
        fp.line(xr, yy, xr + 1.0, yy, FLOOR_SILK, "F.SilkS")
        fp.text(tag, xr + 1.3, yy, LABEL_H, "F.SilkS")

    # Captions STACKED, not placed under their own block. At 0.9 mm the stipple
    # caption is ~40 mm of text over a 10 mm field, so side-by-side captions
    # collide -- confirmed by rendering, which is the only way to catch it.
    fp.text(f"stipple Cu+mask {pitch:.1f}mm - dam "
            f"{pitch - 2 * r_of(duty_of(0)):.2f} to "
            f"{pitch - 2 * r_of(duty_of(n - 1)):.3f}mm, tick at "
            f"{FLOOR_MASK_DAM:.2f} dam floor",
            x0, y0 + block + 0.9, LABEL_H, "F.SilkS")
    fp.text(f"hatch silk {hp:.1f}mm - stroke {w_of(0):.2f} to {w_of(m - 1):.2f}mm, "
            f"ticks at {FLOOR_SILK:.2f} silk floor",
            x0, y0 + block + 2.2, LABEL_H, "F.SilkS")
    return y0 + block + 4.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--outdir", default="RecklessArt.pretty")
    a = ap.parse_args()
    out = pathlib.Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    report_floors()

    built = []

    fp = Fp("cal_tones")
    y = tone_patches(fp, 0, 0)
    registration(fp, 0, y + 3.0)
    built.append(fp)

    fp = Fp("cal_buried")
    y = buried_wedge(fp, 0, 4.0, over_mask=True)
    buried_wedge(fp, 0, y + 5.0, over_mask=False)
    built.append(fp)

    fp = Fp("cal_windows")
    windows(fp, 0, 0)
    built.append(fp)

    fp = Fp("cal_cutouts")
    cutouts(fp, 0, 0)
    built.append(fp)

    fp = Fp("cal_shading")
    shading_fields(fp, 0, 0)
    built.append(fp)

    for fp in built:
        write_footprint(fp, out)


if __name__ == "__main__":
    main()
