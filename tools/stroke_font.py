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

The counter model
-----------------
Ink is centred on the centreline, so a void whose inscribed circle has radius D
(in em) has, at cap height h and stroke width w:

    clear = 2*D*h - w

D is a pure geometric constant of the glyph: the stroke eats w/2 from each side
of the void no matter how big the text is. That one line is why the table can be
three numbers per glyph instead of a font renderer.

It also predicts the thing docs/pcb-palette.md and coupon_ladders.SPECIMEN are
both pointing at. The stroke fails when w < floor, i.e. h < floor/ratio. The
counter fails when 2*D*h - w < floor, i.e. h < floor/(2*D - ratio). At the 1:6.7
ratio those cross over at D = ratio, i.e. D = 0.15 em: any glyph with a counter
tighter than that fails BEFORE its own strokes do. 'e' (D = 0.147) is under it.
'8' (0.214), 'B' (0.238), '@' (0.214) are over it but not by much, and all four
are far tighter than the straight-stroked glyphs, which have no counter at all
and never fail this way. Closed letterforms fail first, and now with a number.

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

    @property
    def has_counters(self) -> bool:
        return self.counter_em is not None


def measure_string(s: str, *, allow_unmeasured: bool = False,
                   stroke_ratio: float | None = None) -> StringMetrics:
    """Lay `s` out at 1 em cap height and report its metrics.

    `stroke_ratio` is stroke width / cap height. Pass it whenever the ink box
    is going to be used for anything physical -- a mask opening, a region fit,
    a collision -- because `justify left` justifies the text BOX and the box
    grows with the pen, so the letterforms sit further right and higher as the
    stroke gets heavier. Omitting it returns the box as measured at
    CAL_STROKE_RATIO, which is only right for hairline text.

    An unmeasured character is a hard error by default. With
    allow_unmeasured=True it is listed, given the widest measured advance so
    the layout cannot under-reserve space, and contributes NO counter -- which
    is why the caller must treat `unmeasured` as "the counter check did not
    cover the whole string", never as "no counters found".
    """
    pen = 0.0
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    counters: dict[str, float] = {}
    missing: list[str] = []
    for ch in s:
        g = GLYPHS.get(ch)
        if g is None:
            if not allow_unmeasured:
                raise UnmeasuredGlyph(ch)
            missing.append(ch)
            pen += MAX_ADVANCE_EM
            continue
        adv, ink, ctr = g
        if ink is not None:
            x0 = min(x0, pen + ink[0])
            x1 = max(x1, pen + ink[2])
            y0 = min(y0, ink[1])
            y1 = max(y1, ink[3])
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
    return StringMetrics(s, pen, box, cem, cch, counters,
                         sorted(set(missing), key=ord))


def counter_clear_mm(counter_em: float, cap_mm: float, stroke_mm: float) -> float:
    """Clear width of a counter. Negative means the stroke has closed it."""
    return 2.0 * counter_em * cap_mm - stroke_mm


def min_cap_for_floor(floor_mm: float, ratio: float,
                      counter_em: float | None) -> tuple[float, str]:
    """Smallest cap height at which BOTH the stroke and the counter clear
    `floor_mm`. -> (mm, which constraint binds).

    Legibility is deliberately not folded in here: it is a different kind of
    limit (can a human read it) from a fabrication floor (can a fab make it),
    and microtext.py reports them separately.
    """
    h_stroke = floor_mm / ratio
    if counter_em is None:
        return h_stroke, "stroke"
    denom = 2.0 * counter_em - ratio
    if denom <= 0:
        return math.inf, "counter (closed at every cap height at this ratio)"
    h_counter = floor_mm / denom
    return ((h_counter, "counter") if h_counter > h_stroke
            else (h_stroke, "stroke"))


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
    a = ap.parse_args(argv)

    if a.string is not None:
        m = measure_string(a.string, allow_unmeasured=True)
        print(f"{a.string!r}")
        print(f"  advance        {m.advance_em:.5f} em")
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
