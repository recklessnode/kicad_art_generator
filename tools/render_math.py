#!/usr/bin/env python3
"""Render a mathematical expression to a tight SVG for tools/emit_art.py.

WHY THIS EXISTS
---------------
The Bitcoin emission formula shipped as 47 frozen outline paths exported from
LibreOffice Math in its default serif face (Latin Modern). Measured on a board,
that art's narrowest silk ink is 0.078 mm against a 0.150 mm floor -- less than
HALF -- and the sub-floor sites are spread across the whole strip rather than
confined to the small type, because a serif face's thick/thin modulation puts a
hairline in every glyph. Reaching the floor by scaling alone needs 138 mm.

The fix is the typeface, not the size: a uniform-stroke face reaches the floor
at 79 mm. Recovering that means re-rendering from the MATH, which is why this
file exists -- the expression is the source of truth, the outlines are output.

WHY NOT EMBOLDEN
----------------
Growing strokes closes gaps at the same rate it thickens ink, so it moves which
floor you violate rather than clearing both. Measured at 72 mm, DejaVu Sans
grown 1 pt lifts ink over the floor and drops the narrowest gap to 0.124 mm.
There is no weight that fixes a face whose gaps are already tight; pick a face
whose ink and gaps are both comfortable and then scale.

FONT SETS
---------
matplotlib's mathtext, not a LaTeX install -- no external toolchain. 'stixsans'
and 'dejavusans' are the uniform-stroke options; 'cm' and 'stix' are serif and
are here only so a caller can reproduce the problem. Measured narrowest silk
ink at 72 mm: stixsans 0.137, dejavusans 0.130, cm 0.017.
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("svg")
import matplotlib.pyplot as plt          # noqa: E402
import matplotlib.patheffects as pe      # noqa: E402

FONTSETS = ("stixsans", "dejavusans", "stix", "cm", "dejavuserif")


def render(expr, out, fontset="stixsans", fontsize=60.0, grow=0.0, pad=0.05):
    """Write `expr` to `out` as a tightly-cropped, transparent SVG.

    `expr` is mathtext WITHOUT the surrounding $...$; they are added here so a
    caller cannot accidentally emit literal dollar signs into the artwork.
    `grow` is a stroke in points added around every glyph -- available because
    it is occasionally the right tool, but see WHY NOT EMBOLDEN above.
    """
    if fontset not in FONTSETS:
        raise SystemExit("unknown fontset %r; choose from %s"
                         % (fontset, ", ".join(FONTSETS)))
    matplotlib.rcParams["mathtext.fontset"] = fontset
    fig = plt.figure(figsize=(12, 4))
    effects = [pe.withStroke(linewidth=grow, foreground="black")] if grow else None
    fig.text(0.01, 0.5, "$%s$" % expr, fontsize=fontsize, color="black",
             va="center", ha="left", path_effects=effects)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    # bbox_inches="tight" is what makes this usable as an emit_art label: the
    # SVG carries no margin of its own, so --width-mm means the ART is that
    # wide rather than the art plus whatever padding the renderer felt like.
    fig.savefig(out, format="svg", bbox_inches="tight", pad_inches=pad,
                transparent=True)
    plt.close(fig)
    return os.path.getsize(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expr", required=True,
                    help="mathtext expression, without the surrounding $")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--fontset", default="stixsans", choices=FONTSETS)
    ap.add_argument("--fontsize", type=float, default=60.0)
    ap.add_argument("--grow", type=float, default=0.0,
                    help="stroke in pt added around every glyph (see module docstring)")
    a = ap.parse_args(argv)
    n = render(a.expr, a.output, a.fontset, a.fontsize, a.grow)
    print("  %s  %s %gpt%s  ->  %d B"
          % (os.path.basename(a.output), a.fontset, a.fontsize,
             " +%gpt" % a.grow if a.grow else "", n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
