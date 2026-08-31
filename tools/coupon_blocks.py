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
    BLOCK_LABEL_H, BOX_MARGIN, FACE_DISPLAY, FACE_NUM, FACE_PROSE,
    FLOOR_COPPER, FLOOR_MASK_DAM, FLOOR_SILK, LABEL_H,
    SWEEP_BAND_SLACK, SWEEP_MIN,
    Fp, report_floors, write_footprint,
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


# The tone label as it is PRINTED, which is not the tone id as it is CODED.
#
# `_` was the whole of the y = -24.1 defect on the beta coupon. An underscore
# sits one sidebearing from its neighbour -- '1_' is 0.19048 em, '7_' is
# 0.14286 em and '_f' is 0.09524 em -- so at a 0.9 mm cap with a 0.15 mm pen
# those gaps measure 0.0214 mm, -0.0214 mm and -0.0643 mm against a 0.150 mm
# floor. Negative means the ink already overlaps in the design. That produced
# ten sub-floor components, eight sub-floor necks, eight sub-floor gaps and 38
# places where a closing at the floor genuinely bridges.
#
# Solving the cap against '_f' instead would need 3.15 mm of cap and a 24 mm
# label on an 11 mm patch pitch, which is not a label. The underscore is a code
# identifier that leaked onto a silkscreen; a space carries the same reading,
# costs nothing, and drops the binding constraint to 'T4'/'i', which a 1.386 mm
# cap clears. TONE_RECIPE's keys are untouched -- they are the protocol's
# names and COUPON.md quotes them.
def tone_label(name: str) -> str:
    return name.replace("_", " ")


def tone_patches(fp, x0, y0, size=8.0, gap=3.0):
    """8 mm patches — big enough to sample well inside the edge (issue #1)."""
    # Names in UBUNTU (general text; Orbitron is ruled out by measurement:
    # its T+7 pair leaves 0.046 mm of inter-glyph gap at a 1.5 mm cap, so
    # 'T7 mask buried' in Orbitron cannot clear the silk floor under a 5 mm
    # cap).  One cap for the whole row, solved for the WORST of the seven
    # names, so the legend reads as one row of type rather than seven sizes.
    names = [tone_label(n) for n in TONE_RECIPE]
    cap = max(Fp.face_box(nl, FACE_PROSE, minimum=LABEL_H)[0]
              for nl in names)
    boxes = [Fp.face_box(nl, FACE_PROSE, minimum=LABEL_H, cap=cap)
             for nl in names]
    # Stagger puts even-index names on row 0 and odd on row 1; by content
    # that gives row 0 no descenders and row 1 the 'enig' g, so each row's
    # height is measured off its own names rather than assumed.
    row_h = [0.0, 0.0]
    for i, (_c, _w, h) in enumerate(boxes):
        row_h[i % 2] = max(row_h[i % 2], h)

    cwhat = "TONE PATCHES 8mm - sample well inside the edge"
    _cc, _cw, chh = Fp.face_box(cwhat, FACE_PROSE, minimum=BLOCK_LABEL_H)
    fp.label_face(cwhat, x0, y0 - 0.5 - chh / 2.0, FACE_PROSE,
                  minimum=BLOCK_LABEL_H)

    # The first row must clear the T5 outline, which is drawn AT the silk
    # floor along y0 + size; rows are placed off the measured ink boxes and
    # TOP-ALIGNED (all names start with a capital T, so their ascents agree
    # and the baselines stay level to within the ascender differences).
    row_top = [y0 + size + FLOOR_SILK / 2.0 + FLOOR_SILK * (1.0 + 0.05), 0.0]
    row_top[1] = row_top[0] + row_h[0] + FLOOR_SILK + 0.05
    x = x0
    for i, (name, layers) in enumerate(TONE_RECIPE.items()):
        for layer in layers:
            fp.rect(x, y0, size, size, layer)
        if not layers:  # T5: outline only, so the empty patch is findable
            # This outline is the ONLY thing marking the T5 patch, so it is the
            # last line on the coupon that may be allowed to drop out. At the
            # silk floor, never under it.
            for a, b in (((x, y0), (x + size, y0)), ((x + size, y0), (x + size, y0 + size)),
                         ((x + size, y0 + size), (x, y0 + size)), ((x, y0 + size), (x, y0))):
                fp.line(a[0], a[1], b[0], b[1], FLOOR_SILK, "F.SilkS")
        _c, _w, h = boxes[i]
        fp.label_face(tone_label(name), x, row_top[i % 2] + h / 2.0,
                      FACE_PROSE, minimum=LABEL_H, cap=cap)
        x += size + gap
    return row_top[1] + row_h[1] + 1.2


def buried_wedge(fp, x0, y0, length=24.0, w0=3.0, w1=0.2, over_mask=True):
    """In1 copper narrowing 3.0 -> 0.2 mm.

    Continuous rather than stepped because the wanted answer is a threshold —
    where does shadow blur through 0.1 mm of prepreg swallow the feature — not
    a go/no-go at named widths.
    """
    tag = "T7 under mask" if over_mask else "T4 under opening"
    # The caption's ink bottom clears the wedge top by 0.3 mm -- and for the
    # T4 variant, the F.Mask opening that reaches 0.2 mm past the wedge:
    # silk over an opening is stripped by the fab (KiCad DRC:
    # silk_over_copper; 22 of them when the old fixed -1.6 anchor was used).
    # Positioned off the measured ink box, since an outline face's ink height
    # is not a function of its cap alone.
    cwhat = f"BURIED WEDGE {tag} 3.0-0.2mm"
    _c, _w, ch = Fp.face_box(cwhat, FACE_PROSE, minimum=BLOCK_LABEL_H)
    over = 0.0 if over_mask else 0.2
    fp.label_face(cwhat, x0, y0 - w0 / 2.0 - over - 0.3 - ch / 2.0,
                  FACE_PROSE, minimum=BLOCK_LABEL_H)
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
    # 'rule areas', not 'keepouts': same KiCad concept (the dialog's own
    # name), and Ubuntu's k-junction is the thin spot that drives any
    # k-bearing string to a 2.11 mm cap and this caption to 74 mm of ink.
    head = "T8 WINDOWS"
    sub = "draw Cu rule areas on the board, outline on Dwgs.User"
    _cs, _ws, hs = Fp.face_box(sub, FACE_PROSE, minimum=BLOCK_LABEL_H)
    _ch, _wh, hh = Fp.face_box(head, FACE_DISPLAY, minimum=BLOCK_LABEL_H)
    y_sub = y0 - 0.6 - hs / 2.0
    fp.label_face(head, x0, y_sub - hs / 2.0 - 0.4 - hh / 2.0, FACE_DISPLAY,
                  minimum=BLOCK_LABEL_H)
    fp.label_face(sub, x0, y_sub, FACE_PROSE, minimum=BLOCK_LABEL_H)
    x = x0
    for s in (2.0, 4.0, 8.0, 16.0):
        fp.rect(x, y0, s, s, "F.Mask")
        fp.rect(x, y0, s, s, "B.Mask")
        # Dwgs.User is documentation, never fabricated, so no floor applies —
        # 0.12 mm here is a drawing weight, not a feature size.
        for a, b in (((x, y0), (x + s, y0)), ((x + s, y0), (x + s, y0 + s)),
                     ((x + s, y0 + s), (x, y0 + s)), ((x, y0 + s), (x, y0))):
            fp.line(a[0], a[1], b[0], b[1], 0.12, "Dwgs.User")
        _c, _w, lh = Fp.face_box(f"{s:.0f}mm", FACE_NUM)
        fp.label_face(f"{s:.0f}mm", x, y0 + s + 0.3 + lh / 2.0, FACE_NUM)
        x += s + 3.0

    # The pair sweep is the important one: it measures BLEED, which sets the
    # minimum spacing between windows and decides whether T8 renders a shape or
    # only a blob.
    y = y0 + 20.0
    bwhat = "BLEED PAIRS - gap 1/2/3/5mm"
    _cb, _wb, hb = Fp.face_box(bwhat, FACE_PROSE)
    fp.label_face(bwhat, x0, y - 0.4 - hb / 2.0, FACE_PROSE)
    x = x0
    for g in (1.0, 2.0, 3.0, 5.0):
        for k in (0, 1):
            xx = x + k * (4.0 + g)
            fp.rect(xx, y, 4.0, 4.0, "F.Mask")
            fp.rect(xx, y, 4.0, 4.0, "B.Mask")
        _c, _w, lh = Fp.face_box(f"{g:.0f}", FACE_NUM)
        fp.label_face(f"{g:.0f}", x, y + 4.0 + 0.4 + lh / 2.0, FACE_NUM)
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
    # Ubuntu, not Orbitron, despite the display role: Orbitron's periods
    # vanish whole at label caps and its tight pairs push the solve to an
    # 8 mm cap for this string; Ubuntu sets it clean.
    cwhat = "T9 CUTOUTS sharp / r0.5 / r1.0 + slots 1.0 / 0.8"
    _cc, _cw, chh = Fp.face_box(cwhat, FACE_PROSE, minimum=BLOCK_LABEL_H)
    fp.label_face(cwhat, x0, y0 - 0.4 - chh / 2.0, FACE_PROSE,
                  minimum=BLOCK_LABEL_H)
    # On Edge.Cuts the fabricated feature is the routed slot width, not the
    # stroke, so no stroke floor applies; 0.1 mm is a drawing weight.
    x = x0
    for r in (0.0, 0.5, 1.0):
        pts = _rounded_rect_pts(x, y0, 6.0, r)
        for i in range(len(pts) - 1):
            fp.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.1, "Edge.Cuts")
        _c, _w, lh = Fp.face_box(f"r{r:.1f}", FACE_NUM)
        fp.label_face(f"r{r:.1f}", x, y0 + 6.4 + lh / 2.0, FACE_NUM)
        x += 10.0
    for w in (1.0, 0.8):
        pts = [(x, y0), (x + 8.0, y0), (x + 8.0, y0 + w), (x, y0 + w), (x, y0)]
        for i in range(len(pts) - 1):
            fp.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 0.1, "Edge.Cuts")
        _c, _w2, lh = Fp.face_box(f"slot{w:.1f}", FACE_NUM)
        fp.label_face(f"slot{w:.1f}", x, y0 + w + 0.7 + lh / 2.0, FACE_NUM)
        x += 11.0
    return y0 + 10.0


def registration(fp, x0, y0):
    """Mask openings offset from their copper. Measures the fab's real
    registration rather than its published tolerance."""
    # 'opening offset', not 'mask offset': the same fact ('mask' is the word
    # ON the patch row above), and Ubuntu's k-junction drives any k-bearing
    # string to a 2.11 mm cap -- this caption is the lowest ink of cal_tones,
    # and 0.65 mm of its height is what kept cal_minfeature_copper from
    # fitting below it on the beta card.
    cwhat = "REGISTRATION - opening offset 0 / .05 / .10 / .15mm"
    _cc, _cw, chh = Fp.face_box(cwhat, FACE_PROSE, minimum=BLOCK_LABEL_H)
    fp.label_face(cwhat, x0, y0 - 0.4 - chh / 2.0, FACE_PROSE,
                  minimum=BLOCK_LABEL_H)
    x = x0
    for off in (0.0, 0.05, 0.10, 0.15):
        fp.rect(x, y0, 4.0, 4.0, "F.Cu")
        fp.rect(x + off, y0 + off, 4.0, 4.0, "F.Mask")
        _c, _w, lh = Fp.face_box(f"{off:.2f}", FACE_NUM)
        fp.label_face(f"{off:.2f}", x, y0 + 4.3 + lh / 2.0, FACE_NUM)
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
    # items: block label / crossing label / tick / field, every position off
    # the measured ink boxes.  A coupon that polices the silk floor cannot
    # crowd its own annotation under it.
    cwhat = "STIPPLE (Cu+mask) + HATCH (silk), duty 10-90%"
    tkwhat = "<%.2f" % FLOOR_MASK_DAM
    _ct, _wt, ht = Fp.face_box(tkwhat, FACE_NUM)
    _cc, _cw, chh = Fp.face_box(cwhat, FACE_PROSE, minimum=BLOCK_LABEL_H)
    y_tk = y0 - 1.05 - 0.25 - ht / 2.0        # tick line spans y0-1.05..-0.30
    fp.label_face(cwhat, x0, y_tk - ht / 2.0 - 0.4 - chh / 2.0, FACE_PROSE,
                  minimum=BLOCK_LABEL_H)

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
        fp.label_face(tkwhat, xc, y_tk, FACE_NUM)

    # --- hatch: silk line-width ramp ----------------------------------------
    x2, hp = x0 + block + 4.0, 0.4
    m = int(block / hp)

    def w_of(i):
        return max(hp * (0.10 + 0.80 * (i / max(m - 1, 1))), SWEEP_MIN)

    # The ramp goes under the silk floor at its low end on purpose, so it says
    # so where verify_art can read it. Band and box both come from hp, block
    # and SWEEP_MIN -- the numbers that decide the ramp, not a reading of it.
    wlo, whi = min(w_of(i) for i in range(m)), max(w_of(i) for i in range(m))
    hbox = (x2 - whi / 2.0 - BOX_MARGIN, y0 - whi / 2.0 - BOX_MARGIN,
            x2 + block + whi / 2.0 + BOX_MARGIN,
            y0 + (m - 1) * hp + whi / 2.0 + BOX_MARGIN)
    fp.declare_sweep("width", "F.SilkS", wlo - SWEEP_BAND_SLACK,
                     whi + SWEEP_BAND_SLACK, hbox, "hatchramp")
    fp.declare_sweep("vanish", "F.SilkS", wlo - SWEEP_BAND_SLACK,
                     whi + SWEEP_BAND_SLACK, hbox, "hatchramp")

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
        fp.label_face(tag, xr + 1.3, yy, FACE_NUM)

    # Captions STACKED, not placed under their own block. At 0.9 mm the stipple
    # caption is ~40 mm of text over a 10 mm field, so side-by-side captions
    # collide -- confirmed by rendering, which is the only way to catch it.
    cap1 = (f"stipple Cu+mask {pitch:.1f}mm - dam "
            f"{pitch - 2 * r_of(duty_of(0)):.2f} to "
            f"{pitch - 2 * r_of(duty_of(n - 1)):.3f}mm, tick at "
            f"{FLOOR_MASK_DAM:.2f} dam floor")
    cap2 = (f"hatch silk {hp:.1f}mm - stroke {w_of(0):.2f} to "
            f"{w_of(m - 1):.2f}mm, ticks at {FLOOR_SILK:.2f} silk floor")
    _c1, _w1, h1 = Fp.face_box(cap1, FACE_PROSE)
    _c2, _w2, h2 = Fp.face_box(cap2, FACE_PROSE)
    yc1 = y0 + block + 0.4 + h1 / 2.0
    yc2 = yc1 + h1 / 2.0 + 0.4 + h2 / 2.0
    fp.label_face(cap1, x0, yc1, FACE_PROSE)
    fp.label_face(cap2, x0, yc2, FACE_PROSE)
    return yc2 + h2 / 2.0 + 1.0


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
