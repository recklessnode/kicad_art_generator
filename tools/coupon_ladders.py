#!/usr/bin/env python3
"""Generate the calibration ladders for the art test coupon (issue #6).

These are the parts of the coupon that are PARAMETRIC GEOMETRY, not image
conversion — so they depend on nothing that is still being calibrated, and can
be built before the quantiser is finished. The real-asset comparisons are placed
separately.

Every block is self-labelling. A measurement that needs a drawing to interpret
does not get made.

Usage:  python coupon_ladders.py -o RecklessArt.pretty
"""

import argparse
import pathlib

MM = 1.0

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
    """Minimal KiCad footprint writer. Modern (footprint ...) form, 20241229."""

    def __init__(self, name):
        self.name = name
        self.items = []
        self._n = 0

    def _uuid(self):
        self._n += 1
        return f"c0up0n00-0000-0000-0000-{self._n:012d}"

    def line(self, x0, y0, x1, y1, width, layer):
        self.items.append(
            f'\t(fp_line (start {x0:.4f} {y0:.4f}) (end {x1:.4f} {y1:.4f})\n'
            f'\t\t(stroke (width {width:.4f}) (type solid)) (layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}"))'
        )

    def rect(self, x, y, w, h, layer):
        self.items.append(
            f'\t(fp_poly (pts (xy {x:.4f} {y:.4f}) (xy {x+w:.4f} {y:.4f}) '
            f'(xy {x+w:.4f} {y+h:.4f}) (xy {x:.4f} {y+h:.4f}))\n'
            f'\t\t(stroke (width 0) (type solid)) (fill solid) (layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}"))'
        )

    def text(self, s, x, y, height, layer, thickness=None):
        t = thickness if thickness else max(height * 0.15, 0.05)
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


def block_label(fp, s, x, y):
    """Labels are deliberately large: they must never be the thing that fails."""
    fp.text(s, x, y, 1.2, "F.SilkS")


def isolated_features(fp, x0, y0, layer_key):
    """Discrete dots and lines. Finds dropout, which is the failure that matters."""
    layer = LAYERS[layer_key]
    block_label(fp, f"MIN FEATURE / {layer_key.upper()}", x0, y0 - 1.6)
    y = y0
    for d in FEATURE_STEPS:
        fp.text(f"{d:.3f}", x0, y + 0.4, 0.8, "F.SilkS")
        # a dot and a 4 mm line at the same dimension
        fp.rect(x0 + 5.0, y, d, d, layer)
        fp.line(x0 + 7.0, y + d / 2, x0 + 11.0, y + d / 2, d, layer)
        y += 1.6
    return y


def converging_pair(fp, x0, y0, layer_key, length=14.0, start_gap=1.0):
    """Continuous wedge: read the merge point directly instead of interpolating."""
    layer = LAYERS[layer_key]
    block_label(fp, f"CONVERGE / {layer_key.upper()} 1.0-0mm", x0, y0 - 1.6)
    w = 0.15
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
    block_label(fp, f"HATCH PITCH / {layer_key.upper()}", x0, y0 - 1.6)
    x = x0
    for pitch in HATCH_PITCHES:
        fp.text(f"{pitch:.1f}", x, y0 - 0.4, 0.8, "F.SilkS")
        n = int(block / pitch)
        for i in range(n):
            yy = y0 + i * pitch
            duty = 0.2 + 0.6 * (i / max(n - 1, 1))
            w = max(pitch * duty, 0.05)
            fp.line(x, yy, x + block, yy, w, layer)
        x += block + 2.0
    return y0 + block + 2.0


def text_ladder(fp, x0, y0, layer_key, sizes):
    layer = LAYERS[layer_key]
    block_label(fp, f"MICROTEXT / {layer_key.upper()}", x0, y0 - 1.6)
    y = y0
    for h in sizes:
        fp.text(f"{h:.1f}", x0, y, 0.8, "F.SilkS")
        fp.text(SPECIMEN, x0 + 4.0, y, h, layer)
        y += h + 1.2
    return y


def scale_bar(fp, x0, y0, length=20.0):
    """Self-calibrating: features can be measured off a photograph."""
    block_label(fp, "SCALE 20mm / 1mm ticks", x0, y0 - 1.6)
    fp.line(x0, y0, x0 + length, y0, 0.15, "F.SilkS")
    for i in range(int(length) + 1):
        h = 1.2 if i % 5 == 0 else 0.6
        fp.line(x0 + i, y0, x0 + i, y0 - h, 0.15, "F.SilkS")
    return y0 + 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--outdir", default="RecklessArt.pretty")
    args = ap.parse_args()
    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    made = []
    for key in ("silk", "copper", "mask"):
        fp = Fp(f"cal_minfeature_{key}")
        y = isolated_features(fp, 0, 0, key)
        converging_pair(fp, 0, y + 3.0, key)
        (out / f"{fp.name}.kicad_mod").write_text(fp.dumps(), encoding="utf-8")
        made.append(fp.name)

    fp = Fp("cal_hatch_silk")
    hatch_ladder(fp, 0, 0, "silk")
    (out / "cal_hatch_silk.kicad_mod").write_text(fp.dumps(), encoding="utf-8")
    made.append("cal_hatch_silk")

    fp = Fp("cal_hatch_copper")
    hatch_ladder(fp, 0, 0, "copper")
    (out / "cal_hatch_copper.kicad_mod").write_text(fp.dumps(), encoding="utf-8")
    made.append("cal_hatch_copper")

    fp = Fp("cal_text")
    y = text_ladder(fp, 0, 0, "copper", TEXT_CU)
    y = text_ladder(fp, 0, y + 3.0, "silk", TEXT_SILK)
    scale_bar(fp, 0, y + 3.0)
    (out / "cal_text.kicad_mod").write_text(fp.dumps(), encoding="utf-8")
    made.append("cal_text")

    for n in made:
        p = out / f"{n}.kicad_mod"
        print(f"  {p}  {p.stat().st_size:,} B")


if __name__ == "__main__":
    main()
