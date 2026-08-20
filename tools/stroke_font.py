#!/usr/bin/env python3
"""Measured metrics for KiCad's built-in stroke font (newstroke).

Microprinting is the one place in this pipeline where the QUESTION IS THE FONT.
Everything else emits polygons whose geometry we computed ourselves, so we know
exactly how wide the narrowest thing is. `fp_text` hands the geometry to KiCad,
and at 0.7 mm cap height the difference between "this images" and "this fills in
solid" is a property of the letterforms, not of anything emit_art.py drew.

So the letterforms are MEASURED, not estimated. `--calibrate` renders every
printable ASCII glyph through `kicad-cli fp export svg`, which writes the stroke
CENTRELINES as `<path d="M .. L .."/>` at `stroke-width` = the text thickness,
and reads three things off them. The table below is the output of that run; it
can be regenerated on any machine with kicad-cli, and `--calibrate` diffs the
fresh measurement against it so the numbers cannot quietly rot.

What is measured, per glyph, in EM (fraction of the cap height)
---------------------------------------------------------------
advance   pen movement. Obtained by difference: ink width of "H"+c*4+"H" minus
          the ink width of "HH", over 4. Works for the space, which has no ink
          of its own, and needs no assumption about side bearings.

ink box   x0,y0,x1,y1 of the glyph's centrelines relative to the text anchor.
          This is what a mask opening has to cover. `None` for the space.

counter   the radius of the largest circle inscribed in the narrowest ENCLOSED
          void of the glyph, measured from the centrelines -- i.e. at zero
          stroke width.

The gap model: ONE equation for every void in the artwork
---------------------------------------------------------
Ink is centred on the centreline, so two centrelines a distance G apart (in em)
leave, at cap height h and stroke width w:

    clear = G*h - w

and the copper merges into one region once G*h <= w. A minimum-feature floor is
minimum trace width AND SPACING, so EVERY G in the letterforms has to clear it,
not just the ones inside a glyph. There are four kinds and they are all the same
equation:

    stroke        w                >= floor          (G is not involved)
    inter-glyph   (G_adv - r)*h    >= floor          G_adv from the advances
    intra-glyph   (G_own - r)*h    >= floor          a glyph's OWN loose pieces
    counter       (2*D  - r)*h     >= floor          an enclosed void

with r = w/h. This file used to model the first and the last of those, and
nothing else. That is not a conservative simplification, it is the loosest
constraint of the four: at the character set of a body of English prose the
tightest counter is 'e' at 2*D = 0.29488 em, while the tightest inter-glyph gap
is 4/21 = 0.19048 em and the tightest intra-glyph gap is 'i' stem-to-tittle at
5/21 = 0.23810 em. Sizing a part on the counter alone put copper 0.026 mm apart
on a process whose floor is 0.0889, and nothing complained, because the only
gap anyone had written down was the one that did not bind.

Every one of those numbers is measured off a kicad-cli render, the same way the
advances and counters are -- see INTER_GLYPH_GAP_EM and INTRA_GAP_EM below.

What letter-spacing can and cannot fix
--------------------------------------
Tracking T em added between glyphs widens G_adv to G_adv + T and touches
NOTHING else: a glyph's own pieces and its counters move together with it. So
the achievable gap is

    A(T) = min(G_adv + T, G_own, 2*D, ...)

and the cap height that clears a floor is minimised over stroke ratio at
r = A/2, giving h = 2*floor/A. Past T = G_own - G_adv the tracking buys nothing
at all, because the glyph's own geometry has taken over as the binding
constraint. For English prose that saturation point is exactly 1/21 em.

Dots are not counters -- but that has to be CHECKED
---------------------------------------------------
The stroke font draws a period, a colon and the tittle of 'i', '!' and '?' as
tiny closed loops. Those are enclosed voids by topology, and they are dropped
from the counter table because at every legible stroke ratio they are solid
ink. That is only true while 2*D_dot <= r. DOT_VOID_MAX_EM is the largest of
them measured over printable ASCII, so dots_are_solid() can test the claim at
the ratio actually in use instead of assuming it: a dot that is neither solid
nor a full counter is a sub-floor void, which is precisely the failure this
file exists to prevent.

Where the anchor actually is
----------------------------
`justify left` does NOT put the first glyph's centreline at the anchor: KiCad
justifies the text BOX, which includes the pen, so the whole string slides right
and up as the stroke gets heavier. Measured over a 90x range of stroke ratio and
across cap heights and strings, the shift is exactly linear and the string's own
extent (x1-x0) does not change at all -- it is a pure translation:

    x += 0.657895 * stroke        y -= 0.052000 * stroke      (mm)

This is not a detail. At the 0.105 mm stroke of 0.7 mm microtext the x shift is
0.069 mm, which is MORE than the +/-0.05 mm mask registration tolerance the
block opening exists to absorb. Ignoring it puts the opening 0.069 mm off the
letterforms and spends the entire registration budget before the fab has done
anything -- which is exactly what the first render of this module showed. The
table below is measured at CAL_STROKE_RATIO and measure_string() corrects to
whatever ratio is actually being used.

Dots are not counters
---------------------
The stroke font draws a period, a colon and the tittle of 'i', '!' and '?' as
tiny closed loops -- D = 0.019 em. Those are ENCLOSED voids by topology, but at
every legible stroke ratio (1:6 to 1:8, r = 0.125..0.167) 2*D < r, so they are
solid ink at every cap height. They are how the font draws a dot, not counters
that failed. Voids under DOT_VOID_EM of inscribed diameter are classified as
dots and excluded, and the classification is reported rather than assumed: the
gap in the measured data is 6x wide (0.038 em of dot vs 0.255 em of the tightest
real counter, '%'), so nothing sits near the line.

Provenance
----------
Measured with kicad-cli 10.0 on 2026-08-16, cap height 10 mm, stroke 0.05 mm,
distance field on a 0.004 em grid with the inscribed radius then hill-climbed
off-grid so the baked number is not quantised to the cell size. The advances and
ink boxes come back as exact 21ths (newstroke is on a 21-unit em grid: 'm' is
28/21, '0' is 20/21) and the counters as exact half-21ths (6/21, 5/21, 4.5/21)
wherever the void is bounded by grid-aligned strokes, which is the check that
the measurement is reading the font rather than reading its own grid.

Usage
    python tools/stroke_font.py                 # summary of the baked table
    python tools/stroke_font.py --calibrate     # re-measure, diff, print table
"""

from __future__ import annotations

import argparse
import math
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass, field

# --- the measured table ----------------------------------------------------
# char: (advance_em, ink_box_em | None, narrowest_counter_em | None)
# ink_box is (x0, y0, x1, y1) relative to the text anchor, KiCad orientation
# (y grows DOWNWARD). Regenerate with --calibrate.
GLYPHS: dict[str, tuple[float, tuple[float, float, float, float] | None,
                        float | None]] = {
    ' ':  (0.76190, None, None),
    '!':  (0.47619, ( 0.19377, -0.53764,  0.28900,  0.46236), None),
    '"':  (0.76190, ( 0.19377, -0.53764,  0.57472, -0.34716), None),
    '#':  (1.00000, ( 0.09853, -0.63288,  0.90805,  0.65284), 0.16270),
    '$':  (0.95238, ( 0.19377, -0.68050,  0.76519,  0.60522), 0.14285),
    '%':  (1.14286, ( 0.19377, -0.53764,  0.95567,  0.46236), 0.12777),
    '&':  (1.23810, ( 0.24138, -0.53764,  1.05091,  0.46236), 0.15972),
    "'":  (0.47619, ( 0.19377, -0.53764,  0.28900, -0.34716), None),
    '(':  (0.66667, ( 0.24138, -0.68050,  0.52710,  0.84331), None),
    ')':  (0.66667, ( 0.14615, -0.68050,  0.43186,  0.84331), None),
    '*':  (0.76190, ( 0.14615, -0.53764,  0.62234, -0.10907), None),
    '+':  (1.23810, ( 0.24138, -0.29955,  1.00329,  0.46236), None),
    ',':  (0.47619, ( 0.19377,  0.41474,  0.28900,  0.60522), None),
    '-':  (1.23810, ( 0.24138,  0.08141,  1.00329,  0.08141), None),
    '.':  (0.47619, ( 0.19377,  0.36712,  0.28900,  0.46236), None),
    '/':  (1.04762, ( 0.09853, -0.58526,  0.95567,  0.70045), None),
    '0':  (0.95238, ( 0.19377, -0.53764,  0.76519,  0.46236), 0.28571),
    '1':  (0.95238, ( 0.19377, -0.53764,  0.76519,  0.46236), None),
    '2':  (0.95238, ( 0.14615, -0.53764,  0.76519,  0.46236), None),
    '3':  (0.95238, ( 0.14615, -0.53764,  0.76519,  0.46236), None),
    '4':  (0.95238, ( 0.19377, -0.58526,  0.81281,  0.46236), None),
    '5':  (0.95238, ( 0.19377, -0.53764,  0.76519,  0.46236), None),
    '6':  (0.95238, ( 0.19377, -0.53764,  0.76519,  0.46236), 0.28571),
    '7':  (0.95238, ( 0.14615, -0.53764,  0.81281,  0.46236), None),
    '8':  (0.95238, ( 0.19377, -0.53764,  0.76519,  0.46236), 0.21428),
    '9':  (0.95238, ( 0.19377, -0.53764,  0.76519,  0.46236), 0.28571),
    ':':  (0.47619, ( 0.19377, -0.15669,  0.28900,  0.46236), None),
    ';':  (0.47619, ( 0.19377, -0.15669,  0.28900,  0.60522), None),
    '<':  (1.23810, ( 0.24138, -0.20431,  1.00329,  0.36712), None),
    '=':  (1.23810, ( 0.24138, -0.06145,  1.00329,  0.22426), None),
    '>':  (1.23810, ( 0.24138, -0.20431,  1.00329,  0.36712), None),
    '?':  (0.85714, ( 0.19377, -0.53764,  0.66996,  0.46236), None),
    '@':  (1.28571, ( 0.19377, -0.34716,  1.09853,  0.60522), 0.21358),
    'A':  (0.85714, ( 0.09853, -0.53764,  0.76519,  0.46236), 0.17160),
    'B':  (1.00000, ( 0.24138, -0.53764,  0.81281,  0.46236), 0.23809),
    'C':  (1.00000, ( 0.19377, -0.53764,  0.81281,  0.46236), None),
    'D':  (1.00000, ( 0.24138, -0.53764,  0.81281,  0.46236), 0.28571),
    'E':  (0.90476, ( 0.24138, -0.53764,  0.71758,  0.46236), None),
    'F':  (0.85714, ( 0.24138, -0.53764,  0.71758,  0.46236), None),
    'G':  (1.00000, ( 0.19377, -0.53764,  0.81281,  0.46236), None),
    'H':  (1.04762, ( 0.24138, -0.53764,  0.81281,  0.46236), None),
    'I':  (0.47619, ( 0.24138, -0.53764,  0.24138,  0.46236), None),
    'J':  (0.76190, ( 0.14615, -0.53764,  0.52710,  0.46236), None),
    'K':  (1.00000, ( 0.24138, -0.53764,  0.81281,  0.46236), None),
    'L':  (0.80952, ( 0.24138, -0.53764,  0.71758,  0.46236), None),
    'M':  (1.14286, ( 0.24138, -0.53764,  0.90805,  0.46236), None),
    'N':  (1.04762, ( 0.24138, -0.53764,  0.81281,  0.46236), None),
    'O':  (1.04762, ( 0.19377, -0.53764,  0.86043,  0.46236), 0.33333),
    'P':  (1.00000, ( 0.24138, -0.53764,  0.81281,  0.46236), 0.26190),
    'Q':  (1.04762, ( 0.19377, -0.53764,  0.90805,  0.55760), 0.33333),
    'R':  (1.00000, ( 0.24138, -0.53764,  0.81281,  0.46236), 0.26190),
    'S':  (0.95238, ( 0.19377, -0.53764,  0.76519,  0.46236), None),
    'T':  (0.76190, ( 0.09853, -0.53764,  0.66996,  0.46236), None),
    'U':  (1.04762, ( 0.24138, -0.53764,  0.81281,  0.46236), None),
    'V':  (0.85714, ( 0.09853, -0.53764,  0.76519,  0.46236), None),
    'W':  (1.14286, ( 0.14615, -0.53764,  1.00329,  0.46236), None),
    'X':  (0.95238, ( 0.14615, -0.53764,  0.81281,  0.46236), None),
    'Y':  (0.85714, ( 0.09853, -0.53764,  0.76519,  0.46236), None),
    'Z':  (0.95238, ( 0.14615, -0.53764,  0.81281,  0.46236), None),
    '[':  (0.66667, ( 0.28900, -0.63288,  0.52710,  0.79569), None),
    '\\': (0.66667, (-0.09195, -0.63288,  0.76519,  0.65284), None),
    ']':  (0.66667, ( 0.14615, -0.63288,  0.38424,  0.79569), None),
    '^':  (0.57143, ( 0.09853, -0.58526,  0.47948, -0.44240), None),
    '_':  (0.76190, ( 0.00329,  0.55760,  0.76519,  0.55760), None),
    '`':  (0.38095, ( 0.09853, -0.58526,  0.24138, -0.44240), None),
    'a':  (0.90476, ( 0.19377, -0.20431,  0.66996,  0.46236), 0.19047),
    'b':  (0.90476, ( 0.24138, -0.53764,  0.71758,  0.46236), 0.23809),
    'c':  (0.85714, ( 0.19377, -0.20431,  0.66996,  0.46236), None),
    'd':  (0.90476, ( 0.19377, -0.53764,  0.66996,  0.46236), 0.23809),
    'e':  (0.85714, ( 0.19377, -0.20431,  0.66996,  0.46236), 0.14744),
    'f':  (0.57143, ( 0.09853, -0.53764,  0.47948,  0.46236), None),
    'g':  (0.90476, ( 0.19377, -0.20431,  0.66996,  0.79569), 0.23809),
    'h':  (0.90476, ( 0.24138, -0.53764,  0.66996,  0.46236), None),
    'i':  (0.47619, ( 0.19377, -0.53764,  0.28900,  0.46236), None),
    'j':  (0.47619, ( 0.05091, -0.53764,  0.28900,  0.79569), None),
    'k':  (0.80952, ( 0.24138, -0.53764,  0.62234,  0.46236), None),
    'l':  (0.52381, ( 0.24138, -0.53764,  0.38424,  0.46236), None),
    'm':  (1.33333, ( 0.24138, -0.20431,  1.09853,  0.46236), None),
    'n':  (0.90476, ( 0.24138, -0.20431,  0.66996,  0.46236), None),
    'o':  (0.90476, ( 0.19377, -0.20431,  0.71758,  0.46236), 0.26190),
    'p':  (0.90476, ( 0.24138, -0.20431,  0.71758,  0.79569), 0.23809),
    'q':  (0.90476, ( 0.19377, -0.20431,  0.66996,  0.79569), 0.23809),
    'r':  (0.61905, ( 0.24138, -0.20431,  0.52710,  0.46236), None),
    's':  (0.80952, ( 0.19377, -0.20431,  0.62234,  0.46236), None),
    't':  (0.57143, ( 0.09853, -0.53764,  0.47948,  0.46236), None),
    'u':  (0.90476, ( 0.24138, -0.20431,  0.66996,  0.46236), None),
    'v':  (0.76190, ( 0.14615, -0.20431,  0.62234,  0.46236), None),
    'w':  (1.04762, ( 0.14615, -0.20431,  0.90805,  0.46236), None),
    'x':  (0.80952, ( 0.14615, -0.20431,  0.66996,  0.46236), None),
    'y':  (0.76190, ( 0.14615, -0.20431,  0.62234,  0.79569), None),
    'z':  (0.80952, ( 0.14615, -0.20431,  0.66996,  0.46236), None),
    '{':  (0.66667, ( 0.19377, -0.68050,  0.52710,  0.84331), None),
    '|':  (0.95238, ( 0.47948, -0.63288,  0.47948,  0.79569), None),
    '}':  (0.66667, ( 0.14615, -0.68050,  0.47948,  0.84331), None),
    '~':  (0.71429, ( 0.09853, -0.01383,  0.57472,  0.08141), None),
    # Beyond printable ASCII. Only characters this project actually sets are
    # added, and only after the same rig has re-measured the ASCII table and
    # reproduced it exactly -- see the provenance note on GLYPH_PATHS.
    '·': (0.76190, ( 0.33662,  0.03379,  0.43186,  0.12903), None),
    'α': (1.00000, ( 0.19377, -0.20431,  0.86043,  0.46236), 0.24819),
    'β': (0.90476, ( 0.14615, -0.53764,  0.71758,  0.79569), 0.23809),
}

# Derived from the table, not asserted independently. The capital ink box runs
# -0.53764..+0.46236 = exactly 1.00000 em, which is the statement that KiCad's
# `(size h h)` IS the cap height for the stroke font -- the assumption the whole
# "cap height" vocabulary in docs/pcb-palette.md rests on.
CAP_HEIGHT_EM = round(GLYPHS['H'][1][3] - GLYPHS['H'][1][1], 5)          # 1.0
BASELINE_EM = GLYPHS['H'][1][3]                                          # 0.46236
X_HEIGHT_EM = round(GLYPHS['x'][1][3] - GLYPHS['x'][1][1], 5)            # 0.66667
DESCENDER_EM = round(GLYPHS['g'][1][3] - BASELINE_EM, 5)                 # 0.33333
MAX_ADVANCE_EM = max(g[0] for g in GLYPHS.values())                      # 1.33333 'm'

# A void narrower than this INSCRIBED DIAMETER, in em, is solid ink at every
# legible stroke ratio and every cap height -- it is how the stroke font draws a
# dot. See the module docstring.
DOT_VOID_EM = 0.08

# The largest dot actually in the font, as an inscribed DIAMETER in em, measured
# over every printable ASCII glyph. DOT_VOID_EM is the CLASSIFIER; this is the
# MEASUREMENT, and they are not the same kind of number. A dot is solid ink only
# while the pen is at least this wide, so dots_are_solid() can test the
# classification at the ratio in use rather than assert it.
#
# Widest dot: 0.045794 em, a sliver beside the tapering stem of '!' (the round
# tittles of '!', 'i' and '.' come in at 0.039059). Tightest real counter:
# 0.252484 em, in '%'. A 5.5x separation, so the 0.08 classifier line sits in
# empty space and nothing in the font is near it.
DOT_VOID_MAX_EM = 0.045794

# Derived, not asserted: the tightest counter the font has, as a diameter.
COUNTER_MIN_EM = 2.0 * min(g[2] for g in GLYPHS.values() if g[2] is not None)

# The narrowest gap between a glyph's OWN separate pieces of copper, in em.
#
# This is the constraint nothing in this repo had: an 'i' is a stem and a
# tittle, they are two pieces of copper 5/21 em apart, and no amount of
# letter-spacing moves them relative to each other. Measured the same way as
# everything else -- `kicad-cli fp export svg` per glyph, centrelines split into
# maximal pieces that touch EXACTLY, then the narrowest distance between two
# different pieces. Splitting on exact contact rather than at some stroke ratio
# is what makes this table ratio-independent: a heavier pen can only merge
# pieces, never separate them, so these numbers are the finest partition any
# legible stroke can produce and can only be conservative.
#
# 9 of the 95 printable ASCII glyphs are more than one piece. The other 86 are
# a single connected chain and have no intra-glyph gap at all.
#
# Measured with kicad-cli 10.0.0 on 2026-08-17, cap height 10 mm.
INTRA_GAP_EM: dict[str, float] = {
    '!': 0.285714,     # 6/21   stem to tittle
    '"': 0.380952,     # 8/21
    '%': 0.272359,     # the slash to the lower zero
    ':': 0.428571,     # 9/21
    ';': 0.478565,
    '=': 0.285714,     # 6/21   bar to bar
    '?': 0.285714,     # 6/21
    'i': 0.238095,     # 5/21   stem to tittle -- the tightest in the font
    'j': 0.238095,     # 5/21
}

# The tightest inter-glyph gap the font can produce, in em, over every ordered
# pair of printable ASCII: 4/21, from 'rt', 'tt', 'ff', 'TA' and their kin.
# Recorded as a constant so a caller can reason about the font before it has a
# string; measure_string() reports the gap of the string actually being set,
# which is this or looser.
INTER_GLYPH_GAP_MIN_EM = 4.0 / 21.0

# How far `justify left` slides the letterforms per em of stroke width. See "Where
# the anchor actually is" above. Fitted over stroke ratios 0.002..0.18 at three
# cap heights and two strings; the residual is below 1e-6 em, and x1-x0 is
# invariant, so this really is a translation and not a layout change.
ANCHOR_SHIFT_X_PER_EM_STROKE = 0.657895
ANCHOR_SHIFT_Y_PER_EM_STROKE = -0.052000

# The stroke ratio the ink boxes in GLYPHS were measured at (CAL_T / CAL_H).
CAL_STROKE_RATIO = 0.005

CALIBRATED_WITH = "kicad-cli 10.0"


class UnmeasuredGlyph(KeyError):
    """A character with no entry in GLYPHS. Never silently skipped."""




# --- the measured centreline table -----------------------------------------
# char: the glyph's stroke CENTRELINES as chains of points, in em, relative to
# the text anchor, in KiCad orientation (y grows DOWNWARD) -- the same frame as
# the ink boxes in GLYPHS above. Regenerate with --calibrate-paths.
#
# Why a second table
# ------------------
# GLYPHS answers "how much room does this string need". It cannot answer "how
# close does this ink get to other ink", and a copper SPACING floor asks
# exactly that. FabProfile.min_copper_mm is minimum trace width AND spacing;
# tools/verify_art.py could only ever check the width half, because it read the
# (thickness ...) attribute back out of the file it was checking -- which is
# not a measurement of anything -- and its gap check collected fp_line, fp_poly
# and fp_rect only, so an fp_text was structurally invisible to it. A
# microprinted part sat at 29% of its own fab spacing floor and passed 7/7.
# With the letterforms in hand, the gap between the crossbar of an 'f' and the
# next 'f' is a number that can be computed instead of assumed.
#
# newstroke stores glyphs as POLYLINES -- there are no curves to flatten -- so
# this table is scale invariant. That is checked, not assumed: re-rendering
# every glyph at a 0.6030 mm cap instead of 10 mm reproduces every one of the
# 788 segments with a maximum coordinate deviation of 1e-5 em.
#
# Provenance: kicad-cli 10.0.0 `fp export svg`, cap height 10 mm, stroke
# CAL_STROKE_RATIO, one glyph per footprint with two reference fp_lines at
# known coordinates to fix the plot origin -- the same rig calibrate() uses.
# 95 printable ASCII glyphs, 146 chains, 788 segments, 934 points, plus three
# characters this project sets outside ASCII -- U+00B7 MIDDLE DOT, U+03B1 GREEK
# SMALL LETTER ALPHA, U+03B2 GREEK SMALL LETTER BETA -- measured on the same rig
# on 2026-08-19: 98 glyphs, 150 chains, 834 segments, 984 points. The extraction
# was validated before it was trusted: re-running it over all 95 ASCII glyphs
# reproduced the segment multiset of every one of them (the chaining differs on
# '*', '@', 'Q', 'Y' and 'y', where the plot walks a shared vertex in a
# different order than the source did; the segments are identical), so the three
# new rows come from a reader that is known to agree with the baked table.
#
# U+20BF BITCOIN SIGN is deliberately NOT here: KiCad 10.0.0 has no such glyph
# and plots a 1 em x 1 em placeholder box for it -- 4 segments, no letterform.
# Anything that needs it must draw it, not set it.
GLYPH_PATHS: dict[str, tuple[tuple[tuple[float, float], ...], ...]] = {
    ' ':  (),
    '!':  (((0.241385,0.367121),(0.289004,0.414740),(0.241385,0.462359),
           (0.193765,0.414740),(0.241385,0.367121),(0.241385,0.462359),),(
           (0.241385,0.081407),(0.193765,-0.490022),(0.241385,-0.537641),
           (0.289004,-0.490022),(0.241385,0.081407),(0.241385,-0.537641),),),
    '"':  (((0.193765,-0.537641),(0.193765,-0.347165),),(
           (0.574718,-0.537641),(0.574718,-0.347165),),),
    '#':  (((0.193765,-0.204308),(0.908051,-0.204308),),(
           (0.479480,-0.632879),(0.193765,0.652835),),((0.812813,0.224264),
           (0.098527,0.224264),),((0.527099,0.652835),(0.812813,-0.632879),
           ),),
    '$':  (((0.193765,0.414740),(0.336623,0.462359),(0.574718,0.462359),
           (0.669956,0.414740),(0.717575,0.367121),(0.765194,0.271883),
           (0.765194,0.176645),(0.717575,0.081407),(0.669956,0.033788),
           (0.574718,-0.013831),(0.384242,-0.061450),(0.289004,-0.109070),
           (0.241385,-0.156688),(0.193765,-0.251927),(0.193765,-0.347165),
           (0.241385,-0.442403),(0.289004,-0.490022),(0.384242,-0.537641),
           (0.622337,-0.537641),(0.765194,-0.490022),),(
           (0.479480,-0.680498),(0.479480,0.605216),),),
    '%':  (((0.193765,0.462359),(0.955670,-0.537641),),(
           (0.336623,-0.537641),(0.431861,-0.490022),(0.479480,-0.394784),
           (0.431861,-0.299546),(0.336623,-0.251927),(0.241385,-0.299546),
           (0.193765,-0.394784),(0.241385,-0.490022),(0.336623,-0.537641),),
           ((0.908051,0.414740),(0.955670,0.319502),(0.908051,0.224264),
           (0.812813,0.176645),(0.717575,0.224264),(0.669956,0.319502),
           (0.717575,0.414740),(0.812813,0.462359),(0.908051,0.414740),),),
    '&':  (((1.050908,0.462359),(1.003289,0.462359),(0.908051,0.414740),
           (0.765194,0.271883),(0.527099,-0.013831),(0.431861,-0.156688),
           (0.384242,-0.299546),(0.384242,-0.394784),(0.431861,-0.490022),
           (0.527099,-0.537641),(0.574718,-0.537641),(0.669956,-0.490022),
           (0.717575,-0.394784),(0.717575,-0.347165),(0.669956,-0.251927),
           (0.622337,-0.204308),(0.336623,-0.013831),(0.289004,0.033788),
           (0.241385,0.129026),(0.241385,0.271883),(0.289004,0.367121),
           (0.336623,0.414740),(0.431861,0.462359),(0.574718,0.462359),
           (0.669956,0.414740),(0.717575,0.367121),(0.860432,0.176645),
           (0.908051,0.033788),(0.908051,-0.061450),),),
    "'":  (((0.289004,-0.537641),(0.193765,-0.347165),),),
    '(':  (((0.527099,0.843311),(0.479480,0.795692),(0.384242,0.652835),
           (0.336623,0.557597),(0.289004,0.414740),(0.241385,0.176645),
           (0.241385,-0.013831),(0.289004,-0.251927),(0.336623,-0.394784),
           (0.384242,-0.490022),(0.479480,-0.632879),(0.527099,-0.680498),),),
    ')':  (((0.146146,0.843311),(0.193765,0.795692),(0.289004,0.652835),
           (0.336623,0.557597),(0.384242,0.414740),(0.431861,0.176645),
           (0.431861,-0.013831),(0.384242,-0.251927),(0.336623,-0.394784),
           (0.289004,-0.490022),(0.193765,-0.632879),(0.146146,-0.680498),),),
    '*':  (((0.384242,-0.537641),(0.384242,-0.299546),(0.146146,-0.394784),
           ),((0.384242,-0.299546),(0.622337,-0.394784),),(
           (0.384242,-0.299546),(0.241385,-0.109070),),(
           (0.384242,-0.299546),(0.527099,-0.109070),),),
    '+':  (((0.241385,0.081407),(1.003289,0.081407),),((0.622337,0.462359),
           (0.622337,-0.299546),),),
    ',':  (((0.289004,0.414740),(0.289004,0.462359),(0.241385,0.557597),
           (0.193765,0.605216),),),
    '-':  (((0.241385,0.081407),(1.003289,0.081407),),),
    '.':  (((0.241385,0.367121),(0.289004,0.414740),(0.241385,0.462359),
           (0.193765,0.414740),(0.241385,0.367121),(0.241385,0.462359),),),
    '/':  (((0.955670,-0.585260),(0.098527,0.700454),),),
    '0':  (((0.431861,-0.537641),(0.527099,-0.537641),(0.622337,-0.490022),
           (0.669956,-0.442403),(0.717575,-0.347165),(0.765194,-0.156688),
           (0.765194,0.081407),(0.717575,0.271883),(0.669956,0.367121),
           (0.622337,0.414740),(0.527099,0.462359),(0.431861,0.462359),
           (0.336623,0.414740),(0.289004,0.367121),(0.241385,0.271883),
           (0.193765,0.081407),(0.193765,-0.156688),(0.241385,-0.347165),
           (0.289004,-0.442403),(0.336623,-0.490022),(0.431861,-0.537641),),),
    '1':  (((0.765194,0.462359),(0.193765,0.462359),),((0.479480,0.462359),
           (0.479480,-0.537641),(0.384242,-0.394784),(0.289004,-0.299546),
           (0.193765,-0.251927),),),
    '2':  (((0.193765,-0.442403),(0.241385,-0.490022),(0.336623,-0.537641),
           (0.574718,-0.537641),(0.669956,-0.490022),(0.717575,-0.442403),
           (0.765194,-0.347165),(0.765194,-0.251927),(0.717575,-0.109070),
           (0.146146,0.462359),(0.765194,0.462359),),),
    '3':  (((0.146146,-0.537641),(0.765194,-0.537641),(0.431861,-0.156688),
           (0.574718,-0.156688),(0.669956,-0.109070),(0.717575,-0.061450),
           (0.765194,0.033788),(0.765194,0.271883),(0.717575,0.367121),
           (0.669956,0.414740),(0.574718,0.462359),(0.289004,0.462359),
           (0.193765,0.414740),(0.146146,0.367121),),),
    '4':  (((0.669956,-0.204308),(0.669956,0.462359),),(
           (0.431861,-0.585260),(0.193765,0.129026),(0.812813,0.129026),),),
    '5':  (((0.717575,-0.537641),(0.241385,-0.537641),(0.193765,-0.061450),
           (0.241385,-0.109070),(0.336623,-0.156688),(0.574718,-0.156688),
           (0.669956,-0.109070),(0.717575,-0.061450),(0.765194,0.033788),
           (0.765194,0.271883),(0.717575,0.367121),(0.669956,0.414740),
           (0.574718,0.462359),(0.336623,0.462359),(0.241385,0.414740),
           (0.193765,0.367121),),),
    '6':  (((0.669956,-0.537641),(0.479480,-0.537641),(0.384242,-0.490022),
           (0.336623,-0.442403),(0.241385,-0.299546),(0.193765,-0.109070),
           (0.193765,0.271883),(0.241385,0.367121),(0.289004,0.414740),
           (0.384242,0.462359),(0.574718,0.462359),(0.669956,0.414740),
           (0.717575,0.367121),(0.765194,0.271883),(0.765194,0.033788),
           (0.717575,-0.061450),(0.669956,-0.109070),(0.574718,-0.156688),
           (0.384242,-0.156688),(0.289004,-0.109070),(0.241385,-0.061450),
           (0.193765,0.033788),),),
    '7':  (((0.146146,-0.537641),(0.812813,-0.537641),(0.384242,0.462359),),),
    '8':  (((0.384242,-0.109070),(0.289004,-0.156688),(0.241385,-0.204308),
           (0.193765,-0.299546),(0.193765,-0.347165),(0.241385,-0.442403),
           (0.289004,-0.490022),(0.384242,-0.537641),(0.574718,-0.537641),
           (0.669956,-0.490022),(0.717575,-0.442403),(0.765194,-0.347165),
           (0.765194,-0.299546),(0.717575,-0.204308),(0.669956,-0.156688),
           (0.574718,-0.109070),(0.384242,-0.109070),(0.289004,-0.061450),
           (0.241385,-0.013831),(0.193765,0.081407),(0.193765,0.271883),
           (0.241385,0.367121),(0.289004,0.414740),(0.384242,0.462359),
           (0.574718,0.462359),(0.669956,0.414740),(0.717575,0.367121),
           (0.765194,0.271883),(0.765194,0.081407),(0.717575,-0.013831),
           (0.669956,-0.061450),(0.574718,-0.109070),),),
    '9':  (((0.289004,0.462359),(0.479480,0.462359),(0.574718,0.414740),
           (0.622337,0.367121),(0.717575,0.224264),(0.765194,0.033788),
           (0.765194,-0.347165),(0.717575,-0.442403),(0.669956,-0.490022),
           (0.574718,-0.537641),(0.384242,-0.537641),(0.289004,-0.490022),
           (0.241385,-0.442403),(0.193765,-0.347165),(0.193765,-0.109070),
           (0.241385,-0.013831),(0.289004,0.033788),(0.384242,0.081407),
           (0.574718,0.081407),(0.669956,0.033788),(0.717575,-0.013831),
           (0.765194,-0.109070),),),
    ':':  (((0.241385,0.367121),(0.289004,0.414740),(0.241385,0.462359),
           (0.193765,0.414740),(0.241385,0.367121),(0.241385,0.462359),),(
           (0.241385,-0.156688),(0.289004,-0.109070),(0.241385,-0.061450),
           (0.193765,-0.109070),(0.241385,-0.156688),(0.241385,-0.061450),),),
    ';':  (((0.289004,0.414740),(0.289004,0.462359),(0.241385,0.557597),
           (0.193765,0.605216),),((0.241385,-0.156688),(0.289004,-0.109070),
           (0.241385,-0.061450),(0.193765,-0.109070),(0.241385,-0.156688),
           (0.241385,-0.061450),),),
    '<':  (((1.003289,-0.204308),(0.241385,0.081407),(1.003289,0.367121),),),
    '=':  (((0.241385,-0.061450),(1.003289,-0.061450),),(
           (1.003289,0.224264),(0.241385,0.224264),),),
    '>':  (((0.241385,-0.204308),(1.003289,0.081407),(0.241385,0.367121),),),
    '?':  (((0.384242,0.367121),(0.431861,0.414740),(0.384242,0.462359),
           (0.336623,0.414740),(0.384242,0.367121),(0.384242,0.462359),),(
           (0.193765,-0.490022),(0.289004,-0.537641),(0.527099,-0.537641),
           (0.622337,-0.490022),(0.669956,-0.394784),(0.669956,-0.299546),
           (0.622337,-0.204308),(0.574718,-0.156688),(0.479480,-0.109070),
           (0.431861,-0.061450),(0.384242,0.033788),(0.384242,0.081407),),),
    '@':  (((0.860432,-0.013831),(0.812813,-0.061450),(0.717575,-0.109070),
           (0.622337,-0.109070),(0.527099,-0.061450),(0.479480,-0.013831),
           (0.431861,0.081407),(0.431861,0.176645),(0.479480,0.271883),
           (0.527099,0.319502),(0.622337,0.367121),(0.717575,0.367121),
           (0.812813,0.319502),(0.860432,0.271883),(0.860432,-0.109070),),(
           (0.860432,0.271883),(0.908051,0.319502),(0.955670,0.319502),
           (1.050908,0.271883),(1.098527,0.176645),(1.098527,-0.061450),
           (1.003289,-0.204308),(0.860432,-0.299546),(0.669956,-0.347165),
           (0.479480,-0.299546),(0.336623,-0.204308),(0.241385,-0.061450),
           (0.193765,0.129026),(0.241385,0.319502),(0.336623,0.462359),
           (0.479480,0.557597),(0.669956,0.605216),(0.860432,0.557597),
           (1.003289,0.462359),),),
    'A':  (((0.193765,0.176645),(0.669956,0.176645),),((0.098527,0.462359),
           (0.431861,-0.537641),(0.765194,0.462359),),),
    'B':  (((0.574718,-0.061450),(0.717575,-0.013831),(0.765194,0.033788),
           (0.812813,0.129026),(0.812813,0.271883),(0.765194,0.367121),
           (0.717575,0.414740),(0.622337,0.462359),(0.241385,0.462359),
           (0.241385,-0.537641),(0.574718,-0.537641),(0.669956,-0.490022),
           (0.717575,-0.442403),(0.765194,-0.347165),(0.765194,-0.251927),
           (0.717575,-0.156688),(0.669956,-0.109070),(0.574718,-0.061450),
           (0.241385,-0.061450),),),
    'C':  (((0.812813,0.367121),(0.765194,0.414740),(0.622337,0.462359),
           (0.527099,0.462359),(0.384242,0.414740),(0.289004,0.319502),
           (0.241385,0.224264),(0.193765,0.033788),(0.193765,-0.109070),
           (0.241385,-0.299546),(0.289004,-0.394784),(0.384242,-0.490022),
           (0.527099,-0.537641),(0.622337,-0.537641),(0.765194,-0.490022),
           (0.812813,-0.442403),),),
    'D':  (((0.241385,0.462359),(0.241385,-0.537641),(0.479480,-0.537641),
           (0.622337,-0.490022),(0.717575,-0.394784),(0.765194,-0.299546),
           (0.812813,-0.109070),(0.812813,0.033788),(0.765194,0.224264),
           (0.717575,0.319502),(0.622337,0.414740),(0.479480,0.462359),
           (0.241385,0.462359),),),
    'E':  (((0.241385,-0.061450),(0.574718,-0.061450),),(
           (0.717575,0.462359),(0.241385,0.462359),(0.241385,-0.537641),
           (0.717575,-0.537641),),),
    'F':  (((0.574718,-0.061450),(0.241385,-0.061450),),(
           (0.241385,0.462359),(0.241385,-0.537641),(0.717575,-0.537641),),),
    'G':  (((0.765194,-0.490022),(0.669956,-0.537641),(0.527099,-0.537641),
           (0.384242,-0.490022),(0.289004,-0.394784),(0.241385,-0.299546),
           (0.193765,-0.109070),(0.193765,0.033788),(0.241385,0.224264),
           (0.289004,0.319502),(0.384242,0.414740),(0.527099,0.462359),
           (0.622337,0.462359),(0.765194,0.414740),(0.812813,0.367121),
           (0.812813,0.033788),(0.622337,0.033788),),),
    'H':  (((0.241385,0.462359),(0.241385,-0.537641),),(
           (0.241385,-0.061450),(0.812813,-0.061450),),((0.812813,0.462359),
           (0.812813,-0.537641),),),
    'I':  (((0.241385,0.462359),(0.241385,-0.537641),),),
    'J':  (((0.527099,-0.537641),(0.527099,0.176645),(0.479480,0.319502),
           (0.384242,0.414740),(0.241385,0.462359),(0.146146,0.462359),),),
    'K':  (((0.241385,0.462359),(0.241385,-0.537641),),((0.812813,0.462359),
           (0.384242,-0.109070),),((0.812813,-0.537641),(0.241385,0.033788),
           ),),
    'L':  (((0.717575,0.462359),(0.241385,0.462359),(0.241385,-0.537641),),),
    'M':  (((0.241385,0.462359),(0.241385,-0.537641),(0.574718,0.176645),
           (0.908051,-0.537641),(0.908051,0.462359),),),
    'N':  (((0.241385,0.462359),(0.241385,-0.537641),(0.812813,0.462359),
           (0.812813,-0.537641),),),
    'O':  (((0.431861,-0.537641),(0.622337,-0.537641),(0.717575,-0.490022),
           (0.812813,-0.394784),(0.860432,-0.204308),(0.860432,0.129026),
           (0.812813,0.319502),(0.717575,0.414740),(0.622337,0.462359),
           (0.431861,0.462359),(0.336623,0.414740),(0.241385,0.319502),
           (0.193765,0.129026),(0.193765,-0.204308),(0.241385,-0.394784),
           (0.336623,-0.490022),(0.431861,-0.537641),),),
    'P':  (((0.241385,0.462359),(0.241385,-0.537641),(0.622337,-0.537641),
           (0.717575,-0.490022),(0.765194,-0.442403),(0.812813,-0.347165),
           (0.812813,-0.204308),(0.765194,-0.109070),(0.717575,-0.061450),
           (0.622337,-0.013831),(0.241385,-0.013831),),),
    'Q':  (((0.908051,0.557597),(0.812813,0.509978),(0.717575,0.414740),
           (0.574718,0.271883),(0.479480,0.224264),(0.384242,0.224264),),(
           (0.717575,0.414740),(0.812813,0.319502),(0.860432,0.129026),
           (0.860432,-0.204308),(0.812813,-0.394784),(0.717575,-0.490022),
           (0.622337,-0.537641),(0.431861,-0.537641),(0.336623,-0.490022),
           (0.241385,-0.394784),(0.193765,-0.204308),(0.193765,0.129026),
           (0.241385,0.319502),(0.336623,0.414740),(0.431861,0.462359),
           (0.622337,0.462359),(0.717575,0.414740),),),
    'R':  (((0.812813,0.462359),(0.479480,-0.013831),),((0.241385,0.462359),
           (0.241385,-0.537641),(0.622337,-0.537641),(0.717575,-0.490022),
           (0.765194,-0.442403),(0.812813,-0.347165),(0.812813,-0.204308),
           (0.765194,-0.109070),(0.717575,-0.061450),(0.622337,-0.013831),
           (0.241385,-0.013831),),),
    'S':  (((0.193765,0.414740),(0.336623,0.462359),(0.574718,0.462359),
           (0.669956,0.414740),(0.717575,0.367121),(0.765194,0.271883),
           (0.765194,0.176645),(0.717575,0.081407),(0.669956,0.033788),
           (0.574718,-0.013831),(0.384242,-0.061450),(0.289004,-0.109070),
           (0.241385,-0.156688),(0.193765,-0.251927),(0.193765,-0.347165),
           (0.241385,-0.442403),(0.289004,-0.490022),(0.384242,-0.537641),
           (0.622337,-0.537641),(0.765194,-0.490022),),),
    'T':  (((0.098527,-0.537641),(0.669956,-0.537641),),(
           (0.384242,0.462359),(0.384242,-0.537641),),),
    'U':  (((0.241385,-0.537641),(0.241385,0.271883),(0.289004,0.367121),
           (0.336623,0.414740),(0.431861,0.462359),(0.622337,0.462359),
           (0.717575,0.414740),(0.765194,0.367121),(0.812813,0.271883),
           (0.812813,-0.537641),),),
    'V':  (((0.098527,-0.537641),(0.431861,0.462359),(0.765194,-0.537641),),),
    'W':  (((0.146146,-0.537641),(0.384242,0.462359),(0.574718,-0.251927),
           (0.765194,0.462359),(1.003289,-0.537641),),),
    'X':  (((0.146146,-0.537641),(0.812813,0.462359),),(
           (0.812813,-0.537641),(0.146146,0.462359),),),
    'Y':  (((0.431861,-0.013831),(0.431861,0.462359),),(
           (0.431861,-0.013831),(0.098527,-0.537641),),(
           (0.431861,-0.013831),(0.765194,-0.537641),),),
    'Z':  (((0.146146,-0.537641),(0.812813,-0.537641),(0.146146,0.462359),
           (0.812813,0.462359),),),
    '[':  (((0.527099,0.795692),(0.289004,0.795692),(0.289004,-0.632879),
           (0.527099,-0.632879),),),
    '\\': (((-0.091949,-0.632879),(0.765194,0.652835),),),
    ']':  (((0.146146,0.795692),(0.384242,0.795692),(0.384242,-0.632879),
           (0.146146,-0.632879),),),
    '^':  (((0.098527,-0.442403),(0.289004,-0.585260),(0.479480,-0.442403),
           ),),
    '_':  (((0.003289,0.557597),(0.765194,0.557597),),),
    '`':  (((0.098527,-0.585260),(0.241385,-0.442403),),),
    'a':  (((0.669956,0.462359),(0.669956,-0.061450),(0.622337,-0.156688),
           (0.527099,-0.204308),(0.336623,-0.204308),(0.241385,-0.156688),),
           ((0.669956,0.414740),(0.574718,0.462359),(0.336623,0.462359),
           (0.241385,0.414740),(0.193765,0.319502),(0.193765,0.224264),
           (0.241385,0.129026),(0.336623,0.081407),(0.574718,0.081407),
           (0.669956,0.033788),),),
    'b':  (((0.241385,0.462359),(0.241385,-0.537641),),(
           (0.241385,-0.156688),(0.336623,-0.204308),(0.527099,-0.204308),
           (0.622337,-0.156688),(0.669956,-0.109070),(0.717575,-0.013831),
           (0.717575,0.271883),(0.669956,0.367121),(0.622337,0.414740),
           (0.527099,0.462359),(0.336623,0.462359),(0.241385,0.414740),),),
    'c':  (((0.669956,0.414740),(0.574718,0.462359),(0.384242,0.462359),
           (0.289004,0.414740),(0.241385,0.367121),(0.193765,0.271883),
           (0.193765,-0.013831),(0.241385,-0.109070),(0.289004,-0.156688),
           (0.384242,-0.204308),(0.574718,-0.204308),(0.669956,-0.156688),),),
    'd':  (((0.669956,0.462359),(0.669956,-0.537641),),((0.669956,0.414740),
           (0.574718,0.462359),(0.384242,0.462359),(0.289004,0.414740),
           (0.241385,0.367121),(0.193765,0.271883),(0.193765,-0.013831),
           (0.241385,-0.109070),(0.289004,-0.156688),(0.384242,-0.204308),
           (0.574718,-0.204308),(0.669956,-0.156688),),),
    'e':  (((0.622337,0.414740),(0.527099,0.462359),(0.336623,0.462359),
           (0.241385,0.414740),(0.193765,0.319502),(0.193765,-0.061450),
           (0.241385,-0.156688),(0.336623,-0.204308),(0.527099,-0.204308),
           (0.622337,-0.156688),(0.669956,-0.061450),(0.669956,0.033788),
           (0.193765,0.129026),),),
    'f':  (((0.098527,-0.204308),(0.479480,-0.204308),),(
           (0.241385,0.462359),(0.241385,-0.394784),(0.289004,-0.490022),
           (0.384242,-0.537641),(0.479480,-0.537641),),),
    'g':  (((0.669956,-0.204308),(0.669956,0.605216),(0.622337,0.700454),
           (0.574718,0.748073),(0.479480,0.795692),(0.336623,0.795692),
           (0.241385,0.748073),),((0.669956,0.414740),(0.574718,0.462359),
           (0.384242,0.462359),(0.289004,0.414740),(0.241385,0.367121),
           (0.193765,0.271883),(0.193765,-0.013831),(0.241385,-0.109070),
           (0.289004,-0.156688),(0.384242,-0.204308),(0.574718,-0.204308),
           (0.669956,-0.156688),),),
    'h':  (((0.241385,0.462359),(0.241385,-0.537641),),((0.669956,0.462359),
           (0.669956,-0.061450),(0.622337,-0.156688),(0.527099,-0.204308),
           (0.384242,-0.204308),(0.289004,-0.156688),(0.241385,-0.109070),),),
    'i':  (((0.241385,0.462359),(0.241385,-0.204308),),(
           (0.241385,-0.537641),(0.193765,-0.490022),(0.241385,-0.442403),
           (0.289004,-0.490022),(0.241385,-0.537641),(0.241385,-0.442403),),),
    'j':  (((0.241385,-0.204308),(0.241385,0.652835),(0.193765,0.748073),
           (0.098527,0.795692),(0.050908,0.795692),),((0.241385,-0.537641),
           (0.193765,-0.490022),(0.241385,-0.442403),(0.289004,-0.490022),
           (0.241385,-0.537641),(0.241385,-0.442403),),),
    'k':  (((0.241385,0.462359),(0.241385,-0.537641),),((0.336623,0.081407),
           (0.622337,0.462359),),((0.622337,-0.204308),(0.241385,0.176645),
           ),),
    'l':  (((0.384242,0.462359),(0.289004,0.414740),(0.241385,0.319502),
           (0.241385,-0.537641),),),
    'm':  (((0.241385,0.462359),(0.241385,-0.204308),),(
           (0.241385,-0.109070),(0.289004,-0.156688),(0.384242,-0.204308),
           (0.527099,-0.204308),(0.622337,-0.156688),(0.669956,-0.061450),
           (0.669956,0.462359),),((0.669956,-0.061450),(0.717575,-0.156688),
           (0.812813,-0.204308),(0.955670,-0.204308),(1.050908,-0.156688),
           (1.098527,-0.061450),(1.098527,0.462359),),),
    'n':  (((0.241385,-0.204308),(0.241385,0.462359),),(
           (0.241385,-0.109070),(0.289004,-0.156688),(0.384242,-0.204308),
           (0.527099,-0.204308),(0.622337,-0.156688),(0.669956,-0.061450),
           (0.669956,0.462359),),),
    'o':  (((0.384242,0.462359),(0.289004,0.414740),(0.241385,0.367121),
           (0.193765,0.271883),(0.193765,-0.013831),(0.241385,-0.109070),
           (0.289004,-0.156688),(0.384242,-0.204308),(0.527099,-0.204308),
           (0.622337,-0.156688),(0.669956,-0.109070),(0.717575,-0.013831),
           (0.717575,0.271883),(0.669956,0.367121),(0.622337,0.414740),
           (0.527099,0.462359),(0.384242,0.462359),),),
    'p':  (((0.241385,-0.204308),(0.241385,0.795692),),(
           (0.241385,-0.156688),(0.336623,-0.204308),(0.527099,-0.204308),
           (0.622337,-0.156688),(0.669956,-0.109070),(0.717575,-0.013831),
           (0.717575,0.271883),(0.669956,0.367121),(0.622337,0.414740),
           (0.527099,0.462359),(0.336623,0.462359),(0.241385,0.414740),),),
    'q':  (((0.669956,-0.204308),(0.669956,0.795692),),((0.669956,0.414740),
           (0.574718,0.462359),(0.384242,0.462359),(0.289004,0.414740),
           (0.241385,0.367121),(0.193765,0.271883),(0.193765,-0.013831),
           (0.241385,-0.109070),(0.289004,-0.156688),(0.384242,-0.204308),
           (0.574718,-0.204308),(0.669956,-0.156688),),),
    'r':  (((0.241385,0.462359),(0.241385,-0.204308),),(
           (0.241385,-0.013831),(0.289004,-0.109070),(0.336623,-0.156688),
           (0.431861,-0.204308),(0.527099,-0.204308),),),
    's':  (((0.193765,0.414740),(0.289004,0.462359),(0.479480,0.462359),
           (0.574718,0.414740),(0.622337,0.319502),(0.622337,0.271883),
           (0.574718,0.176645),(0.479480,0.129026),(0.336623,0.129026),
           (0.241385,0.081407),(0.193765,-0.013831),(0.193765,-0.061450),
           (0.241385,-0.156688),(0.336623,-0.204308),(0.479480,-0.204308),
           (0.574718,-0.156688),),),
    't':  (((0.098527,-0.204308),(0.479480,-0.204308),),(
           (0.241385,-0.537641),(0.241385,0.319502),(0.289004,0.414740),
           (0.384242,0.462359),(0.479480,0.462359),),),
    'u':  (((0.669956,-0.204308),(0.669956,0.462359),),(
           (0.241385,-0.204308),(0.241385,0.319502),(0.289004,0.414740),
           (0.384242,0.462359),(0.527099,0.462359),(0.622337,0.414740),
           (0.669956,0.367121),),),
    'v':  (((0.146146,-0.204308),(0.384242,0.462359),(0.622337,-0.204308),),),
    'w':  (((0.146146,-0.204308),(0.336623,0.462359),(0.527099,-0.013831),
           (0.717575,0.462359),(0.908051,-0.204308),),),
    'x':  (((0.146146,0.462359),(0.669956,-0.204308),),(
           (0.146146,-0.204308),(0.669956,0.462359),),),
    'y':  (((0.146146,-0.204308),(0.384242,0.462359),(0.622337,-0.204308),),
           ((0.384242,0.462359),(0.289004,0.700454),(0.241385,0.748073),
           (0.146146,0.795692),),),
    'z':  (((0.146146,-0.204308),(0.669956,-0.204308),(0.146146,0.462359),
           (0.669956,0.462359),),),
    '{':  (((0.527099,0.843311),(0.479480,0.843311),(0.384242,0.795692),
           (0.336623,0.700454),(0.336623,0.224264),(0.289004,0.129026),
           (0.193765,0.081407),(0.289004,0.033788),(0.336623,-0.061450),
           (0.336623,-0.537641),(0.384242,-0.632879),(0.479480,-0.680498),
           (0.527099,-0.680498),),),
    '|':  (((0.479480,0.795692),(0.479480,-0.632879),),),
    '}':  (((0.146146,0.843311),(0.193765,0.843311),(0.289004,0.795692),
           (0.336623,0.700454),(0.336623,0.224264),(0.384242,0.129026),
           (0.479480,0.081407),(0.384242,0.033788),(0.336623,-0.061450),
           (0.336623,-0.537641),(0.289004,-0.632879),(0.193765,-0.680498),
           (0.146146,-0.680498),),),
    '~':  (((0.098527,0.081407),(0.146146,0.033788),(0.241385,-0.013831),
           (0.431861,0.081407),(0.527099,0.033788),(0.574718,-0.013831),),),
    # Beyond printable ASCII -- see the GLYPHS table above.
    '·': (((0.384242,0.033788),(0.336623,0.081407),(0.384242,0.129026),(
           0.431861,0.081407),(0.384242,0.033788),(0.384242,0.129026),),),
    'α': (((0.812813,-0.204308),(0.669956,0.271883),(0.622337,0.367121),(
           0.574718,0.414740),(0.479480,0.462359),(0.384242,0.462359),(
           0.289004,0.414740),(0.241385,0.367121),(0.193765,0.224264),(
           0.193765,0.033788),(0.241385,-0.109070),(0.289004,-0.156688),(
           0.384242,-0.204308),(0.479480,-0.204308),(0.574718,-0.156688),(
           0.622337,-0.109070),(0.669956,-0.013831),(0.717575,0.319502),(
           0.765194,0.414740),(0.860432,0.462359),),),
    'β': (((0.527099,-0.109070),(0.622337,-0.061450),(0.669956,-0.013831),(
           0.717575,0.081407),(0.717575,0.271883),(0.669956,0.367121),(
           0.622337,0.414740),(0.527099,0.462359),(0.384242,0.462359),(
           0.289004,0.414740),(0.241385,0.367121),),((0.146146,0.795692),(
           0.193765,0.748073),(0.241385,0.652835),(0.241385,-0.394784),(
           0.289004,-0.490022),(0.384242,-0.537641),(0.527099,-0.537641),(
           0.622337,-0.490022),(0.669956,-0.394784),(0.669956,-0.251927),(
           0.622337,-0.156688),(0.527099,-0.109070),(0.431861,-0.109070),),),
}

# Half of KiCad's single-line text box, in em: what `justify top` and
# `justify bottom` move the text by. It is a constant of the FONT, not a
# property of the string -- measured as 0.58500004 em over 'Hxy8e' and 'gjQ,|'
# at cap heights 0.6030, 2.5 and 100 mm, which is why it is not derived from
# the ink box of whatever string happens to be passed.
VBOX_HALF_EM = 0.585


def glyph_chains(ch: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    """One glyph's centreline chains, em, pen at the origin, y downward.

    A character with no entry is a hard error, never an empty glyph: silently
    dropping ink is how a spacing check ends up measuring a gap that is not
    there. The space is a real entry and is legitimately empty.
    """
    try:
        return GLYPH_PATHS[ch]
    except KeyError:
        raise UnmeasuredGlyph(ch) from None


def string_chains(s: str, cap_mm: float, stroke_mm: float,
                  justify=()) -> list[list[tuple[float, float]]]:
    """Centrelines of `s` in mm, relative to the fp_text anchor.

    Returns chains of points. The pen is NOT applied: every chain is a
    centreline that the caller strokes at `stroke_mm`.

    Placement, all of it measured against `kicad-cli fp export svg` rather than
    read off the KiCad source:

      pen advance   GLYPHS[ch][0], the same advances measure_string() uses.

      pen shift     `justify left` justifies the text BOX, which includes the
                    pen, so heavier text slides right and up by
                    ANCHOR_SHIFT_{X,Y}_PER_EM_STROKE * stroke. `justify right`
                    slides the opposite way by the same amount and centred
                    text does not move at all, because the box grows
                    symmetrically about the centre. GLYPH_PATHS was measured
                    at CAL_STROKE_RATIO with `justify left`, so that shift is
                    already baked into the table and is subtracted back out
                    here -- otherwise every string would sit ~0.002 mm right of
                    where KiCad puts it, at every cap height.

      horizontal    left -> 0, right -> -advance, neither -> -advance/2.

      vertical      top -> +VBOX_HALF_EM, bottom -> -VBOX_HALF_EM, neither -> 0.

      mirror        x -> -x about the anchor, applied last.

    Rotation and the fp_text `at` translation are deliberately NOT applied:
    they are footprint-level, not font-level, and belong to the caller.

    Validated against kicad-cli 10.0.0 on the real 1712-character part this was
    written for: 14,461 of 14,461 plotted segments matched, maximum deviation
    0.00007 mm, which is accumulated rounding in the 5-decimal advances.
    """
    just = set(justify)
    cap = float(cap_mm)
    chains: list[list[tuple[float, float]]] = []
    pen = 0.0
    for ch in s:
        for c in glyph_chains(ch):
            chains.append([((x + pen) * cap, y * cap) for (x, y) in c])
        pen += GLYPHS[ch][0]
    adv = pen * cap

    kx = ANCHOR_SHIFT_X_PER_EM_STROKE
    ky = ANCHOR_SHIFT_Y_PER_EM_STROKE
    if "right" in just:
        bx = -adv - kx * stroke_mm
    elif "left" in just:
        bx = kx * stroke_mm
    else:
        bx = -adv / 2.0
    by = ky * stroke_mm
    if "top" in just:
        by += VBOX_HALF_EM * cap
    elif "bottom" in just:
        by -= VBOX_HALF_EM * cap
    # Undo the left-justified pen shift the table was measured with.
    ox = bx - kx * CAL_STROKE_RATIO * cap
    oy = by - ky * CAL_STROKE_RATIO * cap

    mirror = "mirror" in just
    out = []
    for c in chains:
        if mirror:
            out.append([(-(x + ox), y + oy) for (x, y) in c])
        else:
            out.append([(x + ox, y + oy) for (x, y) in c])
    return out

# --- KiCad text markup hazards ---------------------------------------------
# Both of these make KiCad render something OTHER than the string that was
# asked for, silently. In art that is a wrong picture; in microprinting, where
# nobody can read the result without a loupe, it is a wrong picture nobody will
# ever notice. Detected and refused rather than escaped, because the escape
# would change the glyph count and therefore the geometry the caller asked for.
MARKUP_HAZARDS = (
    ("${", "KiCad text-variable substitution -- '${NAME}' is replaced at plot "
           "time, so the fabricated string is not the string you passed"),
    ("~{", "KiCad overbar markup -- '~{...}' renders as an overbar and the "
           "braces themselves disappear"),
)


def markup_hazards(s: str) -> list[str]:
    out = [f"contains {tok!r}: {why}" for tok, why in MARKUP_HAZARDS if tok in s]
    if "\n" in s or "\r" in s:
        out.append("contains a line break -- multi-line fp_text breaks the "
                   "advance and mask-block arithmetic here; place one line at "
                   "a time")
    if "\t" in s:
        out.append("contains a tab -- the stroke font has no tab metric")
    return out


# --- string metrics ---------------------------------------------------------

@dataclass
class StringMetrics:
    """Everything about a string that is a property of the FONT, in em.

    Nothing here knows about millimetres, layers or floors; scaling by the cap
    height happens in microtext.py, so this stays a pure font question.
    """
    text: str
    advance_em: float
    ink_em: tuple[float, float, float, float] | None
    counter_em: float | None
    counter_char: str | None
    counter_chars: dict[str, float] = field(default_factory=dict)
    unmeasured: list[str] = field(default_factory=list)
    # --- spacing, all in em at zero stroke --------------------------------
    # tracking is already folded into inter_gap_em: it is the gap this string
    # WILL have, not the gap the font would give it untracked. inter_gap_pair
    # names the two glyphs so a refusal can say which pair binds.
    tracking_em: float = 0.0
    inter_gap_em: float | None = None
    inter_gap_pair: str | None = None
    intra_gap_em: float | None = None
    intra_gap_char: str | None = None

    @property
    def has_counters(self) -> bool:
        return self.counter_em is not None


def measure_string(s: str, *, allow_unmeasured: bool = False,
                   stroke_ratio: float | None = None,
                   tracking: float = 0.0) -> StringMetrics:
    """Lay `s` out at 1 em cap height and report its metrics.

    `stroke_ratio` is stroke width / cap height. Pass it whenever the ink box
    is going to be used for anything physical -- a mask opening, a region fit,
    a collision -- because `justify left` justifies the text BOX and the box
    grows with the pen, so the letterforms sit further right and higher as the
    stroke gets heavier. Omitting it returns the box as measured at
    CAL_STROKE_RATIO, which is only right for hairline text.

    `tracking` is extra advance in em inserted BETWEEN glyphs -- n-1 times for
    an n-glyph string, never after the last one, so the reported advance and
    ink box are the width of the ink and not the width of the ink plus a
    trailing space. It widens the inter-glyph gap and nothing else.

    An unmeasured character is a hard error by default. With
    allow_unmeasured=True it is listed, given the widest measured advance so
    the layout cannot under-reserve space, and contributes NO counter -- which
    is why the caller must treat `unmeasured` as "the counter check did not
    cover the whole string", never as "no counters found".
    """
    track = float(tracking)
    pen = 0.0
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    counters: dict[str, float] = {}
    missing: list[str] = []
    # Running end of the last INKED glyph, in pen coordinates. Carrying it
    # rather than comparing neighbouring characters is what makes a space or an
    # unmeasured glyph behave correctly: the gap is between the two nearest
    # pieces of ink, however many advance-only characters sit between them.
    prev_x1: float | None = None
    gap_em: float | None = None
    gap_pair: str | None = None
    prev_ch = ""
    for i, ch in enumerate(s):
        if i:
            pen += track
        g = GLYPHS.get(ch)
        if g is None:
            if not allow_unmeasured:
                raise UnmeasuredGlyph(ch)
            missing.append(ch)
            pen += MAX_ADVANCE_EM
            # An unmeasured glyph has no ink box, so no gap either side of it
            # can be stated. Forget the previous ink rather than measure across
            # it, or the report would claim a gap it has not seen.
            prev_x1, prev_ch = None, ""
            continue
        adv, ink, ctr = g
        if ink is not None:
            x0 = min(x0, pen + ink[0])
            x1 = max(x1, pen + ink[2])
            y0 = min(y0, ink[1])
            y1 = max(y1, ink[3])
            if prev_x1 is not None:
                g_em = (pen + ink[0]) - prev_x1
                if gap_em is None or g_em < gap_em:
                    gap_em, gap_pair = g_em, prev_ch + ch
            prev_x1, prev_ch = pen + ink[2], ch
        if ctr is not None and (ch not in counters or ctr < counters[ch]):
            counters[ch] = ctr
        pen += adv
    box = None if x0 is math.inf else (x0, y0, x1, y1)
    if box is not None and stroke_ratio is not None:
        dr = float(stroke_ratio) - CAL_STROKE_RATIO
        dx = ANCHOR_SHIFT_X_PER_EM_STROKE * dr
        dy = ANCHOR_SHIFT_Y_PER_EM_STROKE * dr
        box = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
    if counters:
        cch = min(counters, key=lambda c: counters[c])
        cem = counters[cch]
    else:
        cch, cem = None, None
    own = [(INTRA_GAP_EM[c], c) for c in set(s) if c in INTRA_GAP_EM]
    iem, ich = min(own) if own else (None, None)
    return StringMetrics(s, pen, box, cem, cch, counters,
                         sorted(set(missing), key=ord),
                         tracking_em=track,
                         inter_gap_em=gap_em, inter_gap_pair=gap_pair,
                         intra_gap_em=iem, intra_gap_char=ich)


def counter_clear_mm(counter_em: float, cap_mm: float, stroke_mm: float) -> float:
    """Clear width of a counter. Negative means the stroke has closed it."""
    return 2.0 * counter_em * cap_mm - stroke_mm


# --- the constraint set -----------------------------------------------------

@dataclass(frozen=True)
class GapConstraint:
    """One thing that has to stay above the fabrication floor.

    `em` is the CENTRELINE separation of the two pieces of copper at zero
    stroke; None means this constraint IS the stroke width. Everything else --
    the clear width, the smallest cap height that satisfies it -- follows from
    that one number, which is why the four kinds can share a class instead of
    four formulas scattered across two modules.
    """
    name: str
    em: float | None
    detail: str = ""
    trackable: bool = False

    def coeff(self, ratio: float) -> float:
        """Clear width per em of cap height. cap = floor / coeff."""
        return float(ratio) if self.em is None else self.em - float(ratio)

    def clear_mm(self, cap_mm: float, stroke_mm: float) -> float:
        if self.em is None:
            return stroke_mm
        return self.em * cap_mm - stroke_mm

    def min_cap_mm(self, floor_mm: float, ratio: float) -> float:
        c = self.coeff(ratio)
        return math.inf if c <= 0 else floor_mm / c


def gap_constraints(metrics: "StringMetrics | None") -> list[GapConstraint]:
    """Every gap in `metrics` that a minimum-feature floor governs.

    The stroke is always present. The other three appear only when the string
    actually contains them, and a constraint that is absent is absent because
    it was LOOKED FOR, not because nobody thought of it -- an empty list past
    the stroke means the string is straight-stroked, well-spaced and has no
    closed letterforms, which is a real and reportable fact about it.
    """
    out = [GapConstraint("stroke", None, "stroke width itself")]
    if metrics is None:
        return out
    if metrics.inter_gap_em is not None:
        t = metrics.tracking_em
        out.append(GapConstraint(
            "inter-glyph", metrics.inter_gap_em,
            f"{metrics.inter_gap_pair!r} sidebearings"
            + (f" + {t:.6f} em tracking" if t else ""),
            trackable=True))
    if metrics.intra_gap_em is not None:
        out.append(GapConstraint(
            "intra-glyph", metrics.intra_gap_em,
            f"{metrics.intra_gap_char!r}'s own pieces -- tracking cannot widen "
            f"this"))
    if metrics.counter_em is not None:
        out.append(GapConstraint(
            "counter", 2.0 * metrics.counter_em,
            f"{metrics.counter_char!r}, inscribed radius "
            f"{metrics.counter_em:.5f} em"))
    return out


def dots_are_solid(ratio: float) -> bool:
    """Is every dot in the font filled in at this stroke ratio?

    The counter table drops dot-sized voids on the grounds that they are how
    the font draws a dot rather than counters that failed. True only while the
    pen is at least as wide as the dot: a half-open dot is a sub-floor void
    that nothing in this file would otherwise report.
    """
    return float(ratio) >= DOT_VOID_MAX_EM - 1e-12


def min_cap_for_floor(floor_mm: float, ratio: float,
                      metrics: "StringMetrics | None" = None
                      ) -> tuple[float, str]:
    """Smallest cap height at which EVERY gap in `metrics` clears `floor_mm`.

    -> (mm, the name of the constraint that binds).

    This used to take a bare counter radius as its third argument and model two
    constraints, stroke and counter. It now takes the whole StringMetrics,
    because the two it modelled were not the two that bind: passing a float
    here is refused rather than quietly re-creating the partial model that
    sized a part at 0.026 mm of copper-to-copper spacing against a 0.0889 mm
    floor and reported PASS.

    Legibility is deliberately not folded in here: it is a different kind of
    limit (can a human read it) from a fabrication floor (can a fab make it),
    and microtext.py reports them separately.
    """
    if metrics is not None and not isinstance(metrics, StringMetrics):
        raise TypeError(
            "min_cap_for_floor() takes a StringMetrics, not a bare counter "
            "radius. A counter is one of four constraints and it is the "
            "loosest of them; sizing on it alone is the defect this signature "
            "change exists to make impossible. Call measure_string() first.")
    cons = gap_constraints(metrics)
    worst = max(cons, key=lambda c: c.min_cap_mm(floor_mm, ratio))
    h = worst.min_cap_mm(floor_mm, ratio)
    if math.isinf(h):
        return h, f"{worst.name} (closed at every cap height at this ratio)"
    return h, worst.name


def optimum_ratio(metrics: "StringMetrics | None") -> tuple[float, float]:
    """The stroke ratio that minimises the cap height. -> (ratio, coeff).

    Every constraint but the stroke gets LOOSER as the pen gets lighter and the
    stroke gets tighter, so the smallest cap sits where they cross:

        r* = A/2      A = min(em) over the non-stroke constraints
        cap = floor / (A/2) = 2*floor/A

    `coeff` is A/2, the clear width per em of cap height at that ratio, so
    cap = floor/coeff for any floor.
    """
    ems = [c.em for c in gap_constraints(metrics) if c.em is not None]
    if not ems:
        raise ValueError(
            "this string has no gap of any kind -- only the stroke width "
            "constrains it, and a stroke alone has no optimum: the lighter the "
            "pen, the larger the cap it needs. Pick a ratio.")
    A = min(ems)
    return A / 2.0, A / 2.0


# --- calibration ------------------------------------------------------------
# Everything below this line is only used by --calibrate. It re-derives the
# table above from a live kicad-cli so the numbers can be checked rather than
# believed. numpy is imported inside, so the metrics path above has no
# dependency at all.

CAL_H = 10.0
CAL_T = 0.05
CAL_GRID = 0.004
CAL_NREP = 4
CAL_REF = -60.0
_PATH_RE = re.compile(r'<path\s+d="([^"]*)"')
_TEXTG_RE = re.compile(r'<g class="stroked-text">(.*?)</g>', re.S)


def _cal_fp(name: str, s: str) -> str:
    esc = s.replace("\\", "\\\\").replace('"', '\\"')
    r = CAL_REF
    return (f'(footprint "{name}"\n\t(version 20241229)\n'
            f'\t(generator "stroke_font")\n\t(layer "F.Cu")\n'
            f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
            f'\t(fp_line (start {r} {r}) (end {r+10} {r}) (stroke (width 0.01) '
            f'(type solid)) (layer "F.Cu"))\n'
            f'\t(fp_line (start {r} {r}) (end {r} {r+10}) (stroke (width 0.01) '
            f'(type solid)) (layer "F.Cu"))\n'
            f'\t(fp_text user "{esc}" (at 0 0) (layer "F.Cu")\n'
            f'\t\t(effects (font (size {CAL_H} {CAL_H}) (thickness {CAL_T})) '
            f'(justify left)))\n)\n')


def _parse_paths(svg: str):
    import numpy as np
    out = []
    for d in _PATH_RE.findall(svg):
        pts = []
        for t in d.replace("\n", " ").split():
            if t[0].isalpha():
                if t[0] not in ("M", "L"):
                    raise RuntimeError(f"unexpected SVG path command {t[0]!r}; "
                                       f"this reader only handles the polyline "
                                       f"form KiCad emits for stroke text")
                if t[1:]:
                    pts.append([float(t[1:]), None])
            else:
                if pts and pts[-1][1] is None:
                    pts[-1][1] = float(t)
                else:
                    pts.append([float(t), None])
        if any(p[1] is None for p in pts):
            raise RuntimeError("odd coordinate count in an SVG path")
        if len(pts) >= 2:
            out.append(np.array(pts, dtype=float))
    return out


def _glyph_polys(svg: str):
    """Glyph centrelines in footprint mm, anchor at the origin.

    KiCad tags every plotted stroke-font string with <g class="stroked-text">,
    which is what separates glyph strokes from the reference markers. Geometry
    cannot do it: the stem of an 'H' at a 10 mm cap height IS a 10 mm
    axis-aligned segment, identical to a marker.
    """
    import numpy as np
    glyph = _parse_paths("".join(_TEXTG_RE.findall(svg)))
    marks = [p for p in _parse_paths(_TEXTG_RE.sub("", svg)) if len(p) == 2]
    if len(marks) < 2:
        raise RuntimeError(f"reference markers not found in the SVG ({len(marks)})")
    mp = np.concatenate(marks)
    off = np.array([CAL_REF - mp[:, 0].min(), CAL_REF - mp[:, 1].min()])
    return [p + off for p in glyph]


def _dist_field(segs, X, Y):
    import numpy as np
    best = None
    for a, b in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        if L2 <= 0:
            d = np.hypot(X - a[0], Y - a[1])
        else:
            t = ((X - a[0]) * dx + (Y - a[1]) * dy) / L2
            np.clip(t, 0.0, 1.0, out=t)
            d = np.hypot(X - (a[0] + t * dx), Y - (a[1] + t * dy))
        best = d if best is None else np.minimum(best, d)
    return best


def _label4(mask):
    """4-connected labelling, scanline + union-find. Background is deliberately
    4-connected so a void cannot leak out diagonally between two strokes --
    same convention as emit_art.trace_contours()."""
    import numpy as np
    h, w = mask.shape
    parent = [0]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    m = mask.tolist()
    L = [[0] * w for _ in range(h)]
    nxt = 0
    for y in range(h):
        row, prow = m[y], (m[y - 1] if y else None)
        Lrow, Lprow = L[y], (L[y - 1] if y else None)
        for x in range(w):
            if not row[x]:
                continue
            up = Lprow[x] if prow is not None and prow[x] else 0
            left = Lrow[x - 1] if x and row[x - 1] else 0
            if up and left:
                Lrow[x] = min(up, left)
                ra, rb = find(up), find(left)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            elif up or left:
                Lrow[x] = up or left
            else:
                nxt += 1
                parent.append(nxt)
                Lrow[x] = nxt
    lab = np.array(L, dtype=np.int32)
    if nxt == 0:
        return lab, 0
    root = np.array([find(i) if i else 0 for i in range(nxt + 1)], dtype=np.int32)
    return root[lab], nxt


def _refine_max(segs, cx, cy, r0, rounds=8):
    """Hill-climb the inscribed radius off the grid, so the baked counter is
    not quantised to the cell size."""
    import numpy as np
    best = float(_dist_field(segs, np.array([[cx]]), np.array([[cy]]))[0, 0])
    r = r0
    for _ in range(rounds):
        k = np.linspace(-r, r, 9)
        gx, gy = np.meshgrid(cx + k, cy + k)
        d = _dist_field(segs, gx, gy)
        iy, ix = np.unravel_index(int(np.argmax(d)), d.shape)
        if float(d[iy, ix]) > best:
            best, cx, cy = float(d[iy, ix]), float(gx[iy, ix]), float(gy[iy, ix])
        r *= 0.5
    return best


def _measure_glyph(polys):
    import numpy as np
    segs = []
    for p in polys:
        q = p / CAL_H
        segs += [(q[i], q[i + 1]) for i in range(len(q) - 1)]
    if not segs:
        return None, None, 0
    allp = np.concatenate([np.asarray(s) for s in segs])
    x0, y0 = float(allp[:, 0].min()), float(allp[:, 1].min())
    x1, y1 = float(allp[:, 0].max()), float(allp[:, 1].max())
    pad = 4 * CAL_GRID
    xs = np.arange(x0 - pad, x1 + pad + CAL_GRID, CAL_GRID)
    ys = np.arange(y0 - pad, y1 + pad + CAL_GRID, CAL_GRID)
    X, Y = np.meshgrid(xs, ys)
    d = _dist_field(segs, X, Y)
    free = ~(d <= CAL_GRID * math.sqrt(2) / 2 + 1e-12)
    lab, n = _label4(free)
    border = set(lab[0, :].tolist()) | set(lab[-1, :].tolist()) | \
        set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    counter, dots = None, 0
    for k in range(1, n + 1):
        if k in border:
            continue
        sel = lab == k
        if int(sel.sum()) < 4:
            continue
        dm = np.where(sel, d, -1.0)
        iy, ix = np.unravel_index(int(np.argmax(dm)), dm.shape)
        r = _refine_max(segs, float(X[iy, ix]), float(Y[iy, ix]), 2 * CAL_GRID)
        if 2 * r < DOT_VOID_EM:
            dots += 1
        elif counter is None or r < counter:
            counter = r
    return (round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5)), counter, dots


def calibrate(cli: str, workdir: pathlib.Path, chars=None, verbose=True):
    """Re-measure the font. -> {char: (adv, ink, counter, dots)}."""
    import numpy as np
    chars = chars or [chr(c) for c in range(0x20, 0x7F)]
    pretty = workdir / "strokecal.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    for f in pretty.glob("*.kicad_mod"):
        f.unlink()
    (pretty / "base.kicad_mod").write_text(_cal_fp("base", "HH"), encoding="utf-8")
    for i, ch in enumerate(chars):
        (pretty / f"a_{i:03d}.kicad_mod").write_text(
            _cal_fp(f"a_{i:03d}", ch), encoding="utf-8")
        (pretty / f"b_{i:03d}.kicad_mod").write_text(
            _cal_fp(f"b_{i:03d}", "H" + ch * CAL_NREP + "H"), encoding="utf-8")

    out = workdir / "strokecal_svg"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.svg"):
        f.unlink()
    hp = _host_path
    r = subprocess.run([cli, "fp", "export", "svg", "--output", hp(out),
                        "--layers", "F.Cu", hp(pretty)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"kicad-cli failed:\n{r.stdout}\n{r.stderr}")

    def load(nm):
        return _glyph_polys((out / f"{nm}.svg").read_text(encoding="utf-8",
                                                          errors="replace"))

    def ink_w(ps):
        if not ps:
            return 0.0
        a = np.concatenate(ps)
        return float(a[:, 0].max() - a[:, 0].min())

    base_w = ink_w(load("base"))
    res = {}
    for i, ch in enumerate(chars):
        adv = (ink_w(load(f"b_{i:03d}")) - base_w) / CAL_NREP / CAL_H
        ink, ctr, dots = _measure_glyph(load(f"a_{i:03d}"))
        res[ch] = (round(adv, 5), ink, (round(ctr, 5) if ctr else None), dots)
        if verbose:
            print(f"  U+{ord(ch):04X} {ch!r:5} adv={adv:7.5f}em  "
                  f"counter={'-' if ctr is None else f'{ctr:.5f}'}  dots={dots}",
                  file=sys.stderr)
    return res


def calibrate_anchor_shift(cli: str, workdir: pathlib.Path,
                           text: str = "HxH") -> tuple[float, float, float]:
    """Re-derive ANCHOR_SHIFT_*_PER_EM_STROKE. -> (kx, ky, max_residual_em).

    Two thicknesses would give the constants; six are used so the residual can
    be reported. If the shift ever stopped being linear -- a KiCad change to how
    text is justified -- the residual is what would say so, instead of the fit
    quietly averaging the difference away.
    """
    import numpy as np
    ratios = [0.002, 0.02, 0.06, 0.10, 0.14, 0.18]
    pretty = workdir / "anchorcal.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    for f in pretty.glob("*.kicad_mod"):
        f.unlink()
    for i, r in enumerate(ratios):
        s = _cal_fp(f"k{i}", text).replace(f"(thickness {CAL_T})",
                                           f"(thickness {r * CAL_H:.6f})")
        (pretty / f"k{i}.kicad_mod").write_text(s, encoding="utf-8")
    out = workdir / "anchorcal_svg"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.svg"):
        f.unlink()
    res = subprocess.run([cli, "fp", "export", "svg", "--output", _host_path(out),
                          "--layers", "F.Cu", _host_path(pretty)],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if res.returncode != 0:
        raise RuntimeError(f"kicad-cli failed:\n{res.stdout}\n{res.stderr}")
    xs, ys = [], []
    for i in range(len(ratios)):
        a = np.concatenate(_glyph_polys(
            (out / f"k{i}.svg").read_text(encoding="utf-8", errors="replace")))
        xs.append(float(a[:, 0].min()) / CAL_H)
        ys.append(float(a[:, 1].min()) / CAL_H)
    R = np.asarray(ratios)
    kx = float(np.polyfit(R, np.asarray(xs), 1)[0])
    ky = float(np.polyfit(R, np.asarray(ys), 1)[0])
    resid = 0.0
    for k, vals in ((kx, xs), (ky, ys)):
        c = np.polyfit(R, np.asarray(vals), 1)
        resid = max(resid, float(np.max(np.abs(np.polyval(c, R) - vals))))
    return kx, ky, resid


def _host_path(p: pathlib.Path) -> str:
    """kicad-cli on Windows driven from WSL gets its arguments verbatim."""
    import shutil
    s = str(p)
    if sys.platform != "win32" and shutil.which("wslpath"):
        try:
            r = subprocess.run(["wslpath", "-w", s], capture_output=True,
                               text=True, timeout=20, stdin=subprocess.DEVNULL)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return s


def _table_literal(res) -> str:
    lines = []
    for ch in sorted(res, key=ord):
        adv, ink, ctr, _ = res[ch]
        inks = "None" if ink is None else "(%8.5f, %8.5f, %8.5f, %8.5f)" % ink
        lines.append("    %-5s (%.5f, %s, %s)," %
                     (repr(ch) + ":", adv, inks, "None" if ctr is None
                      else "%.5f" % ctr))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calibrate", action="store_true",
                    help="re-measure the font with kicad-cli and diff against "
                         "the baked table")
    ap.add_argument("--kicad-cli", default=None)
    ap.add_argument("--workdir", default=None,
                    help="where to put the calibration footprints and SVGs")
    ap.add_argument("--print-table", action="store_true",
                    help="with --calibrate, print the fresh table literal")
    ap.add_argument("--string", default=None, help="measure one string and stop")
    ap.add_argument("--string-file", default=None, metavar="FILE",
                    help="read the string from FILE (whitespace collapsed)")
    ap.add_argument("--tracking", type=float, default=0.0, metavar="EM",
                    help="letter-spacing in em, inserted between glyphs")
    ap.add_argument("--floor", type=float, default=None, metavar="MM",
                    help="with --string: solve the constraint set against this "
                         "minimum feature (width AND spacing) and report the "
                         "binding constraint")
    ap.add_argument("--ratio", type=float, default=None, metavar="R",
                    help="stroke/cap for --floor. Default: the ratio that "
                         "minimises the cap height")
    ap.add_argument("--sweep-tracking", default=None, metavar="LO,HI,N",
                    help="with --string --floor: sweep tracking over N steps "
                         "and print the minimum cap at each")
    a = ap.parse_args(argv)

    if a.string_file:
        if a.string is not None:
            ap.error("--string and --string-file both given; pick one")
        a.string = " ".join(pathlib.Path(a.string_file)
                            .read_text(encoding="utf-8").split())

    if a.string is not None:
        m = measure_string(a.string, allow_unmeasured=True, tracking=a.tracking)
        short = (repr(a.string) if len(a.string) <= 60
                 else f"{len(a.string)} chars starting {a.string[:40]!r}")
        print(short)
        print(f"  advance        {m.advance_em:.5f} em "
              f"(tracking {m.tracking_em:.6f} em)")
        print(f"  ink box        {m.ink_em}")
        print(f"  counters       " + (", ".join(
            f"{c!r}={v:.5f}" for c, v in sorted(m.counter_chars.items(),
                                                key=lambda kv: kv[1]))
            or "none - no closed letterforms in this string"))
        if m.counter_em is not None:
            print(f"  narrowest      {m.counter_char!r} at {m.counter_em:.5f} em")
        if m.unmeasured:
            print(f"  UNMEASURED     {m.unmeasured}")
        for h in markup_hazards(a.string):
            print(f"  !! {h}")

        cons = gap_constraints(m)
        print("\n  the constraint set -- every gap a min-feature floor governs")
        print(f"    {'constraint':<14}{'em':>11}  {'x/21':>8}  track?  detail")
        for c in cons:
            em = "-" if c.em is None else f"{c.em:.6f}"
            t21 = "-" if c.em is None else f"{c.em*21:.4f}"
            print(f"    {c.name:<14}{em:>11}  {t21:>8}  "
                  f"{'yes' if c.trackable else 'no ':<6}  {c.detail}")

        if a.floor is not None:
            r = a.ratio
            if r is None:
                r, _ = optimum_ratio(m)
                why = "the ratio that minimises the cap"
            else:
                why = "given"
            cap, binding = min_cap_for_floor(a.floor, r, m)
            stroke = cap * r
            print(f"\n  floor {a.floor:.4f} mm, ratio {r:.7f} = 1:{1/r:.4f} ({why})")
            print(f"    minimum cap  {cap:.6f} mm   stroke {stroke:.6f} mm")
            print(f"    BINDS ON     {binding}")
            print(f"    {'constraint':<14}{'clear mm':>11}{'margin':>11}  "
                  f"{'min cap mm':>11}")
            for c in cons:
                print(f"    {c.name:<14}{c.clear_mm(cap, stroke):11.6f}"
                      f"{c.clear_mm(cap, stroke)-a.floor:+11.6f}  "
                      f"{c.min_cap_mm(a.floor, r):11.6f}")
            if not dots_are_solid(r):
                print(f"    !! at 1:{1/r:.2f} the font's dots are NOT solid "
                      f"(widest {DOT_VOID_MAX_EM:.6f} em > ratio {r:.6f}): a "
                      f"tittle is a half-open void of "
                      f"{(DOT_VOID_MAX_EM - r) * cap:.6f} mm")

            if a.sweep_tracking:
                lo, hi, n = a.sweep_tracking.split(",")
                lo, hi, n = float(lo), float(hi), int(n)
                print(f"\n  tracking sweep, floor {a.floor:.4f} mm, "
                      f"ratio re-optimised at each step")
                print(f"    {'tracking em':>12}{'x/21':>8}{'ratio':>11}"
                      f"{'1:x':>9}{'min cap mm':>12}{'stroke mm':>11}  binds on")
                for i in range(n + 1):
                    T = lo + (hi - lo) * i / n
                    mm = measure_string(a.string, allow_unmeasured=True,
                                        tracking=T)
                    rr, _ = optimum_ratio(mm)
                    cc, bb = min_cap_for_floor(a.floor, rr, mm)
                    print(f"    {T:12.6f}{T*21:8.4f}{rr:11.7f}{1/rr:9.4f}"
                          f"{cc:12.6f}{cc*rr:11.6f}  {bb}")
        return 0

    if not a.calibrate:
        n_ctr = sum(1 for g in GLYPHS.values() if g[2] is not None)
        print(f"stroke_font: {len(GLYPHS)} glyphs measured with {CALIBRATED_WITH}")
        print(f"  cap height   {CAP_HEIGHT_EM:.5f} em (KiCad `size` == cap height)")
        print(f"  x-height     {X_HEIGHT_EM:.5f} em")
        print(f"  descender    {DESCENDER_EM:.5f} em below the baseline")
        print(f"  widest       {MAX_ADVANCE_EM:.5f} em advance")
        print(f"  counters     {n_ctr} glyphs have a closed counter")
        tight = sorted(((v[2], k) for k, v in GLYPHS.items() if v[2] is not None))
        print("  tightest     " + ", ".join(f"{c!r} {d:.5f}" for d, c in tight[:8]))
        print("\n  At a 1:6.7 stroke ratio a counter tighter than 0.15000 em "
              "fails before\n  the glyph's own strokes do: " +
              ", ".join(f"{c!r}" for d, c in tight if d < 0.15))
        print(f"\n  SPACING -- and it is tighter than any of those. A "
              f"min-feature floor is\n  minimum width AND spacing, and the "
              f"counter is the LOOSEST of the four gaps:")
        print(f"    inter-glyph  {INTER_GLYPH_GAP_MIN_EM:.6f} em = 4/21   "
              f"tightest ordered pair in the font ('rt', 'tt', 'ff', 'TA')")
        it = sorted((v, k) for k, v in INTRA_GAP_EM.items())
        print(f"    intra-glyph  {it[0][0]:.6f} em = 5/21   {it[0][1]!r} and "
              f"{it[1][1]!r}, stem to tittle; "
              f"{len(INTRA_GAP_EM)} of {len(GLYPHS)} glyphs are >1 piece")
        print(f"    counter      {COUNTER_MIN_EM:.6f} em          "
              f"tightest 2D in the font")
        print(f"    dots         {DOT_VOID_MAX_EM:.6f} em          solid ink "
              f"only while the ratio is at least this")
        print("\n  Only the inter-glyph gap responds to letter-spacing. Past "
              "1/21 em of\n  tracking the glyphs' own pieces bind and more "
              "spacing buys nothing.")
        return 0

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from verify_art import find_kicad_cli
    choice = find_kicad_cli(a.kicad_cli)
    if not choice.path:
        print("stroke_font: no kicad-cli found; cannot calibrate", file=sys.stderr)
        return 2
    wd = pathlib.Path(a.workdir) if a.workdir else \
        pathlib.Path(__file__).resolve().parent.parent / "output" / "strokecal"
    wd.mkdir(parents=True, exist_ok=True)
    print(f"calibrating with {choice.path} ({choice.version}) in {wd}",
          file=sys.stderr)
    res = calibrate(choice.path, wd)

    diffs = []
    try:
        kx, ky, resid = calibrate_anchor_shift(choice.path, wd)
        print(f"\nanchor shift: x {kx:.6f}  y {ky:.6f} em per em of stroke "
              f"(linear fit residual {resid:.2e} em)", file=sys.stderr)
        if resid > 1e-5:
            diffs.append(f"anchor shift is no longer LINEAR in the stroke "
                         f"(residual {resid:.2e} em) -- measure_string()'s "
                         f"correction is a straight line and would now be wrong")
        for name, got, want in (("x", kx, ANCHOR_SHIFT_X_PER_EM_STROKE),
                                ("y", ky, ANCHOR_SHIFT_Y_PER_EM_STROKE)):
            if abs(got - want) > 1e-4:
                diffs.append(f"anchor shift {name}: {want:.6f} -> {got:.6f} "
                             f"em per em of stroke")
    except Exception as e:
        diffs.append(f"could not re-measure the anchor shift: {e}")

    for ch in sorted(set(res) | set(GLYPHS), key=ord):
        new = res.get(ch)
        old = GLYPHS.get(ch)
        if new is None or old is None:
            diffs.append(f"{ch!r}: {'only in the baked table' if new is None else 'only in the fresh measurement'}")
            continue
        if abs(new[0] - old[0]) > 1e-4:
            diffs.append(f"{ch!r}: advance {old[0]:.5f} -> {new[0]:.5f} em")
        if (new[2] is None) != (old[2] is None):
            diffs.append(f"{ch!r}: counter {old[2]} -> {new[2]}")
        elif new[2] is not None and abs(new[2] - old[2]) > 1e-3:
            diffs.append(f"{ch!r}: counter {old[2]:.5f} -> {new[2]:.5f} em")
    print()
    if diffs:
        print(f"!! {len(diffs)} DIFFERENCE(S) from the baked table "
              f"(measured with {CALIBRATED_WITH}):")
        for d in diffs:
            print(f"  !! {d}")
        print("!! The baked table is stale. Re-run with --print-table and "
              "replace GLYPHS.")
    else:
        print(f"baked table matches this kicad-cli exactly ({len(res)} glyphs)")
    if a.print_table:
        print("\nGLYPHS = {\n" + _table_literal(res) + "\n}")
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
