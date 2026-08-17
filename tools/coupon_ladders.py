#!/usr/bin/env python3
"""Generate the calibration ladders for the art test coupon (issue #6).

These are the parts of the coupon that are PARAMETRIC GEOMETRY, not image
conversion — so they depend on nothing that is still being calibrated, and can
be built before the quantiser is finished. The real-asset comparisons are placed
separately.

Every block is self-labelling. A measurement that needs a drawing to interpret
does not get made.

This module also owns the footprint writer (`Fp`) shared with coupon_blocks.py
and emit_art.py, and with it the fabrication-floor guard — see below.

Usage:  python coupon_ladders.py -o RecklessArt.pretty
"""

import argparse
import pathlib
import re
import sys

MM = 1.0

# --- Fabrication floors ----------------------------------------------------
# AUTHORITY: docs/pcb-palette.md — table "Practical limits", plus "Mask dams"
# in the shading section. The values below are only the fallback for when that
# file cannot be read; _load_floors() prefers the doc and records a note if the
# two ever disagree, so this writer and tools/verify_art.py cannot drift apart
# on what the floor is.
#
# None of these is a style preference. Silk narrower than the silk floor is ink
# the screen may not carry; copper or mask narrower than theirs is metal or an
# opening the fab may not hold. A coupon may cross these lines ON PURPOSE —
# that is exactly what cal_minfeature_*, cal_text and the duty ramps are for —
# but it has to SAY so, by passing allow_below_floor=True, so that an accident
# can never be mistaken for an experiment.
FLOOR_SILK = 0.15         # silkscreen minimum feature
FLOOR_MASK = 0.10         # mask-opening minimum feature
FLOOR_COPPER = 0.10       # copper minimum feature
FLOOR_MASK_DAM = 0.10     # mask REMAINING between two adjacent openings

# Layers the doc gives no floor for, left unchecked rather than guessed at:
#   In*.Cu     "considerably larger — see below", no number. cal_buried exists
#              to measure it; verify_art.py carries a PROVISIONAL 0.50 mm.
#   Edge.Cuts  the feature is the routed slot width, not the stroke.
#   Dwgs.User and friends — annotation, never fabricated.
STROKE_ABS_MIN = 0.05     # KiCad sanity value for unfloored layers, NOT a fab number

# Stroke-to-height for KiCad's built-in stroke font. The doc puts legible text
# at 1:6 to 1:8; 0.15 is 1:6.7 and sits inside that.
TEXT_STROKE_RATIO = 0.15

# Label geometry. The doc's legibility floor for silk text is 0.9 mm, and a
# label must never be the thing that fails, so nothing annotates below it.
LABEL_H = 0.9
BLOCK_LABEL_H = 1.2

# The deliberate bottom of a sweep: below every fabrication floor, on purpose.
SWEEP_MIN = 0.05

FLOOR_SOURCE = "built-in defaults"
FLOOR_NOTES: list[str] = []


def _load_floors(doc: pathlib.Path | None = None) -> None:
    """Read the floors out of docs/pcb-palette.md, which is the authority.

    Deliberately the same table and the same regexes as verify_art.py's
    load_palette(): if the doc changes, the emitter and the acceptance harness
    move together instead of one of them silently lagging.
    """
    global FLOOR_SILK, FLOOR_MASK, FLOOR_COPPER, FLOOR_MASK_DAM, FLOOR_SOURCE
    doc = doc or (pathlib.Path(__file__).resolve().parent.parent
                  / "docs" / "pcb-palette.md")
    if not doc.is_file():
        FLOOR_NOTES.append(f"palette doc not found at {doc} -- using built-in "
                           f"floors. FIX THIS: the doc is the authority.")
        return

    text = doc.read_text(encoding="utf-8", errors="replace")
    cur = {"silk": FLOOR_SILK, "mask": FLOOR_MASK,
           "copper": FLOOR_COPPER, "dam": FLOOR_MASK_DAM}
    for key, pat in (
        ("silk",   r"\|\s*silkscreen\s*\|\s*~?([\d.]+)\s*mm"),
        ("mask",   r"\|\s*mask opening\s*\|\s*~?([\d.]+)\s*mm"),
        ("copper", r"\|\s*copper\s*\|\s*~?([\d.]+)\s*mm"),
        ("dam",    r"must stay above\s+roughly\s*([\d.]+)\s*mm"),
    ):
        m = re.search(pat, text, re.I)
        if not m:
            FLOOR_NOTES.append(f"could not read the {key} floor from {doc.name}; "
                               f"keeping built-in {cur[key]} mm")
            continue
        v = float(m.group(1))
        if abs(v - cur[key]) > 1e-9:
            FLOOR_NOTES.append(f"{key} floor: doc says {v} mm, built-in default "
                               f"was {cur[key]} mm -- using the doc")
        cur[key] = v

    FLOOR_SILK, FLOOR_MASK, FLOOR_COPPER, FLOOR_MASK_DAM = (
        cur["silk"], cur["mask"], cur["copper"], cur["dam"])
    FLOOR_SOURCE = str(doc)


_load_floors()


def floor_for(layer: str) -> tuple[float | None, str]:
    """(floor_mm, class) for a layer. floor is None where the doc gives none."""
    if layer.endswith(".SilkS"):
        return FLOOR_SILK, "silk"
    if layer.endswith(".Mask"):
        return FLOOR_MASK, "mask"
    if layer in ("F.Cu", "B.Cu"):
        return FLOOR_COPPER, "copper"
    if re.fullmatch(r"In\d+\.Cu", layer or ""):
        return None, "buried"
    if layer == "Edge.Cuts":
        return None, "edge"
    return None, "other"


# --- what gets swept -------------------------------------------------------
# Discrete rungs answer "does 0.1 mm work?" -- a value you can quote to a fab.
# The converging wedges answer "where exactly does it stop?" Both are wanted;
# they are different questions.
FEATURE_STEPS = [0.05, 0.075, 0.10, 0.125, 0.15, 0.20, 0.30]
HATCH_PITCHES = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
TEXT_CU = [0.4, 0.5, 0.6, 0.8, 1.0, 1.5]
TEXT_SILK = [0.6, 0.8, 1.0, 1.2, 1.5, 2.0]

# Closed counters fail before straight strokes do, so the string has to contain
# some. A row of capitals would flatter the result.
SPECIMEN = "Reckless 0123 mkgB8@"

LAYERS = {"silk": "F.SilkS", "copper": "F.Cu", "mask": "F.Mask"}


class Fp:
    """Minimal KiCad footprint writer. Modern (footprint ...) form, 20241229.

    Guards the fabrication floor: every drawn feature is measured against the
    floor for its layer, and anything under it warns to stderr naming the call
    site that asked for it. Deliberate sub-floor geometry passes
    allow_below_floor=True and is silent.

    The guard's scope is FEATURE SIZE, not gaps. A mask dam is the space
    *between* two features and cannot be seen from inside a single write call;
    that is verify_art.py's clearance check, which reasons over the whole
    footprint at once. The two together cover both halves.
    """

    def __init__(self, name):
        self.name = name
        self.items = []
        self._n = 0
        # (call site, layer, width, what) -> count, for the end-of-run tally
        self.floor_hits: dict[tuple, int] = {}

    def _uuid(self):
        self._n += 1
        return f"c0up0n00-0000-0000-0000-{self._n:012d}"

    # --- fabrication-floor guard -------------------------------------------

    def _caller(self) -> str:
        """The nearest frame that is not a method call on this writer.

        Walks by object identity rather than by filename, because the block
        functions below live in the same module as Fp — a filename test would
        skip straight past them and blame main().
        """
        f = sys._getframe(1)
        while f is not None and f.f_locals.get("self", None) is self:
            f = f.f_back
        if f is None:
            return "<unknown caller>"
        return (f"{pathlib.Path(f.f_code.co_filename).name}:{f.f_lineno} "
                f"in {f.f_code.co_name}()")

    def _floor_check(self, w, layer, what, allow_below_floor):
        if allow_below_floor or w is None or w <= 0:
            return
        floor, cls = floor_for(layer)
        if floor is None or w >= floor - 1e-9:
            return
        site = self._caller()
        key = (site, layer, round(float(w), 4), what)
        seen = self.floor_hits.get(key, 0)
        self.floor_hits[key] = seen + 1
        if seen == 0:   # first of its kind: say it once, loudly
            print(f"FLOOR: {self.name}: {what} {w:.4f} mm on {layer} is under "
                  f"the {floor:.3f} mm {cls} floor -- {site}  "
                  f"[pass allow_below_floor=True if this is deliberate]",
                  file=sys.stderr)

    # --- geometry ----------------------------------------------------------

    def line(self, x0, y0, x1, y1, width, layer, *, allow_below_floor=False):
        self._floor_check(width, layer, "line stroke", allow_below_floor)
        self.items.append(
            f'\t(fp_line (start {x0:.4f} {y0:.4f}) (end {x1:.4f} {y1:.4f})\n'
            f'\t\t(stroke (width {width:.4f}) (type solid)) (layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}"))'
        )

    def rect(self, x, y, w, h, layer, *, allow_below_floor=False):
        self._floor_check(min(abs(w), abs(h)), layer, "rect min dimension",
                          allow_below_floor)
        self.items.append(
            f'\t(fp_poly (pts (xy {x:.4f} {y:.4f}) (xy {x+w:.4f} {y:.4f}) '
            f'(xy {x+w:.4f} {y+h:.4f}) (xy {x:.4f} {y+h:.4f}))\n'
            f'\t\t(stroke (width 0) (type solid)) (fill solid) (layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}"))'
        )

    def text(self, s, x, y, height, layer, thickness=None, *,
             allow_below_floor=False):
        """Draw text. The DEFAULT thickness can never breach the floor.

        thickness=None gives the 1:6.7 stroke ratio raised to the layer's floor,
        so an ordinary label is safe by construction and needs no vigilance from
        the caller. Passing an explicit thickness is how a sweep goes below the
        floor deliberately; that path is checked, and wants allow_below_floor.
        """
        floor, _ = floor_for(layer)
        if thickness is None:
            t = max(height * TEXT_STROKE_RATIO,
                    floor if floor is not None else STROKE_ABS_MIN)
        else:
            t = thickness
            self._floor_check(t, layer, "text stroke", allow_below_floor)
        self.items.append(
            f'\t(fp_text user "{s}" (at {x:.4f} {y:.4f}) (layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}")\n'
            f'\t\t(effects (font (size {height:.4f} {height:.4f}) '
            f'(thickness {t:.4f})) (justify left)))'
        )

    def dumps(self):
        body = "\n".join(self.items)
        return (
            f'(footprint "{self.name}"\n\t(version 20241229)\n\t(generator "coupon_ladders")\n'
            f'\t(layer "F.Cu")\n'
            f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
            f'\t(descr "Art calibration ladder - see kicad_art_generator#6")\n'
            f'\t(tags "recklessart calibration")\n{body}\n)\n'
        )


def write_footprint(fp: Fp, outdir) -> pathlib.Path:
    """Write, then report size and any declared-deliberate floor breaches.

    Each breach already went to stderr as it happened; this is the tally, so a
    long run cannot end with the evidence scrolled off the top.
    """
    p = pathlib.Path(outdir) / f"{fp.name}.kicad_mod"
    p.write_text(fp.dumps(), encoding="utf-8")
    n = sum(fp.floor_hits.values())
    flag = (f"   ** {n} sub-floor feature(s) at {len(fp.floor_hits)} site(s)"
            if n else "")
    print(f"  {p}  {p.stat().st_size:,} B{flag}")
    return p


def report_floors():
    print(f"floors: silk {FLOOR_SILK:.3f}  mask {FLOOR_MASK:.3f}  "
          f"copper {FLOOR_COPPER:.3f}  mask-dam {FLOOR_MASK_DAM:.3f} mm "
          f"({FLOOR_SOURCE})")
    for n in FLOOR_NOTES:
        print(f"  ! {n}")


def block_label(fp, s, x, y):
    """Labels are deliberately large: they must never be the thing that fails."""
    fp.text(s, x, y, BLOCK_LABEL_H, "F.SilkS")


def isolated_features(fp, x0, y0, layer_key):
    """Discrete dots and lines. Finds dropout, which is the failure that matters."""
    layer = LAYERS[layer_key]
    floor = floor_for(layer)[0] or STROKE_ABS_MIN
    block_label(fp, f"MIN FEATURE / {layer_key.upper()} - sweeps under "
                    f"{floor:.2f}mm on purpose", x0, y0 - 1.6)
    y = y0
    for d in FEATURE_STEPS:
        fp.text(f"{d:.3f}", x0, y + 0.4, LABEL_H, "F.SilkS")
        # A dot and a 4 mm line at the same dimension. The bottom rungs are
        # under the floor and are meant to be: the rung that disappears IS the
        # measurement. Declared, so the guard stays quiet about it.
        fp.rect(x0 + 5.0, y, d, d, layer, allow_below_floor=True)
        fp.line(x0 + 7.0, y + d / 2, x0 + 11.0, y + d / 2, d, layer,
                allow_below_floor=True)
        y += 1.6
    return y


def converging_pair(fp, x0, y0, layer_key, length=14.0, start_gap=1.0):
    """Continuous wedge: read the merge point directly instead of interpolating."""
    layer = LAYERS[layer_key]
    block_label(fp, f"CONVERGE / {layer_key.upper()} 1.0-0mm", x0, y0 - 1.6)
    # The GAP is what is being swept here, so the stroke is held at the silk
    # floor — at or above every layer's floor — to keep the stroke from being
    # the thing that fails first.
    w = FLOOR_SILK
    steps = 60
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        g0, g1 = start_gap * (1 - t0), start_gap * (1 - t1)
        xa, xb = x0 + length * t0, x0 + length * t1
        fp.line(xa, y0 - g0 / 2, xb, y0 - g1 / 2, w, layer)
        fp.line(xa, y0 + g0 / 2, xb, y0 + g1 / 2, w, layer)
    return y0 + 2.0


def hatch_ladder(fp, x0, y0, layer_key="silk", block=8.0):
    """Pitch sweep, each block ramping duty 20->80% by line width."""
    layer = LAYERS[layer_key]
    floor = floor_for(layer)[0] or STROKE_ABS_MIN
    block_label(fp, f"HATCH PITCH / {layer_key.upper()} duty 20-80% - ramp "
                    f"runs under {floor:.2f}mm", x0, y0 - 1.6)
    x = x0
    for pitch in HATCH_PITCHES:
        fp.text(f"{pitch:.1f}", x, y0 - 0.4, LABEL_H, "F.SilkS")
        n = int(block / pitch)
        for i in range(n):
            yy = y0 + i * pitch
            duty = 0.2 + 0.6 * (i / max(n - 1, 1))
            # At the tight pitches the low-duty end lands under the floor. That
            # is the question the ladder exists to answer — at what pitch and
            # duty does hatch stop rendering as tone — so it is declared here
            # rather than clamped, and the block label says so on silk.
            w = max(pitch * duty, SWEEP_MIN)
            fp.line(x, yy, x + block, yy, w, layer, allow_below_floor=True)
        x += block + 2.0
    return y0 + block + 2.0


def text_ladder(fp, x0, y0, layer_key, sizes):
    layer = LAYERS[layer_key]
    floor = floor_for(layer)[0] or STROKE_ABS_MIN
    block_label(fp, f"MICROTEXT / {layer_key.upper()} - stroke sweeps under "
                    f"{floor:.2f}mm", x0, y0 - 1.6)
    y = y0
    for h in sizes:
        fp.text(f"{h:.1f}", x0, y, LABEL_H, "F.SilkS")
        # The specimen IS the sweep. Hold the 1:6.7 stroke ratio all the way
        # down, through the floor, and let the coupon report where the glyphs
        # stop resolving. Passed explicitly rather than taking the floor-raised
        # default, which would flatten the bottom of the ladder into a row of
        # identical strokes and destroy the measurement.
        fp.text(SPECIMEN, x0 + 4.0, y, h, layer,
                thickness=h * TEXT_STROKE_RATIO, allow_below_floor=True)
        y += h + 1.2
    return y


def scale_bar(fp, x0, y0, length=20.0):
    """Self-calibrating: features can be measured off a photograph."""
    # The major ticks rise 1.2 mm from the baseline, so the standard -1.6 mm
    # label position puts the caption straight through them (visible in a
    # render, invisible in the numbers). Cleared to -2.6.
    block_label(fp, "SCALE 20mm / 1mm ticks", x0, y0 - 2.6)
    # The ruler must survive whatever else on the coupon does not, so it is
    # drawn at the floor, never below it.
    fp.line(x0, y0, x0 + length, y0, FLOOR_SILK, "F.SilkS")
    for i in range(int(length) + 1):
        h = 1.2 if i % 5 == 0 else 0.6
        fp.line(x0 + i, y0, x0 + i, y0 - h, FLOOR_SILK, "F.SilkS")
    return y0 + 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--outdir", default="RecklessArt.pretty")
    args = ap.parse_args()
    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    report_floors()

    built = []
    for key in ("silk", "copper", "mask"):
        fp = Fp(f"cal_minfeature_{key}")
        y = isolated_features(fp, 0, 0, key)
        converging_pair(fp, 0, y + 3.0, key)
        built.append(fp)

    fp = Fp("cal_hatch_silk")
    hatch_ladder(fp, 0, 0, "silk")
    built.append(fp)

    fp = Fp("cal_hatch_copper")
    hatch_ladder(fp, 0, 0, "copper")
    built.append(fp)

    fp = Fp("cal_text")
    y = text_ladder(fp, 0, 0, "copper", TEXT_CU)
    y = text_ladder(fp, 0, y + 3.0, "silk", TEXT_SILK)
    scale_bar(fp, 0, y + 3.0)
    built.append(fp)

    for fp in built:
        write_footprint(fp, out)


if __name__ == "__main__":
    main()
