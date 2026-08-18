#!/usr/bin/env python3
"""Acceptance harness for generated art footprints.

    python tools/verify_art.py <file.kicad_mod> [more...]

Answers one question per file: *would we ship this?* A footprint passes only if
KiCad 10 loads it, it fits the size budget, its geometry is well formed, it
draws only on layers the palette actually defines, and its features survive
fabrication.

Checks, one reported line each:

  1. kicad-load   -- kicad-cli really parses it (fp upgrade, plus fp export svg)
  2. size         -- WARN >250 kB, FAIL >1 MB for an asset under 60 mm
  3. geometry     -- degenerate polys, duplicate points, runaway outliers
  4. layers       -- every layer used is one docs/pcb-palette.md names
  5. self-isect   -- self-intersecting polygons fill unpredictably
  6. min-feature  -- narrowest feature per layer vs the fabrication floors
  7. clearance    -- gaps between features (mask dams, copper spacing); beyond
                     the original spec, but docs/pcb-palette.md makes 0.1 mm
                     dams a hard constraint and every FabProfile.min_copper_mm
                     is a spacing limit as well as a width one, so a harness
                     that ignores gaps misses real dropout. --no-clearance.

Exit status: 0 = every file passed, 1 = at least one FAIL, 2 = harness error.
WARNs do not fail the run unless --strict is given. A feature or gap under a
floor that came from a NAMED FABRICATOR is a FAIL, not a WARN: the palette
doc's numbers are house guidance, but a vendor's published limit is what that
process images, and art under it is missing from the delivered board.

TEXT IS EXPANDED, NOT SUMMARISED
--------------------------------
Checks 6 and 7 used to be blind to fp_text in two different ways, and a
microprinted part passed 7/7 while its narrowest copper-to-copper gap was 29%
of its own fabricator's floor:

  * check_min_feature reported it.thickness -- the attribute the emitter had
    written into the file being checked. Nothing was measured, so no text item
    could ever contradict the tool that produced it.
  * check_clearance collected fp_line, fp_poly and fp_rect. An fp_text was not
    in the list, so copper spacing between letterforms was unreachable, and
    the layer that held nothing else printed a PASS over zero pairs.

Both now go through expand_text(), which places the newstroke centrelines from
tools/stroke_font.GLYPH_PATHS. Where kicad-cli is available the expansion is
cross-checked against the plot KiCad itself produces, so the letterforms being
measured are demonstrably the letterforms that will be imaged.

Fabrication floors and legal layers are read from docs/pcb-palette.md at
startup, not hardcoded here -- the doc is the authority. Where the doc gives no
number (the buried-tone floor) the value used is marked PROVISIONAL in output.

Nothing is ever quietly ignored: every check that cannot run says so, loudly,
and a check that cannot run is never reported as a pass.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# The vendor processes. This module keeps its own copy of the palette-doc
# parsing on purpose -- see load_palette() -- but the fabrication profiles are
# NOT duplicated: a second table of vendor limits is a second thing to go
# stale, and the whole point of the fab tag is that the emitter and this
# harness resolve one number from one place.
import fab_profiles                                       # noqa: E402

# --------------------------------------------------------------------------
# Levels. Ordered so max() picks the worst.
# --------------------------------------------------------------------------

PASS, INFO, SKIP, WARN, FAIL = "PASS", "INFO", "SKIP", "WARN", "FAIL"
_RANK = {PASS: 0, INFO: 1, SKIP: 2, WARN: 3, FAIL: 4}


def worst(*levels: str) -> str:
    return max(levels, key=lambda x: _RANK[x], default=PASS)


# --------------------------------------------------------------------------
# Defaults. Overridden by docs/pcb-palette.md where the doc states a number.
# --------------------------------------------------------------------------

# Size budget. Scoped by the task to "an asset under 60 mm".
WARN_BYTES = 250 * 1000
FAIL_BYTES = 1000 * 1000
ASSET_MM = 60.0

# Fabrication floors, mm. Parsed from the doc's "Practical limits" table; these
# are the fallbacks if parsing fails.
FLOOR_SILK = 0.15
FLOOR_MASK = 0.10
FLOOR_COPPER = 0.10

# The doc says buried tones need features "considerably larger" but gives no
# number -- cal_buried exists precisely to measure it. Anything here is a guess,
# so it is labelled PROVISIONAL everywhere it is used and is overridable.
FLOOR_BURIED = 0.50
FLOOR_BURIED_PROVISIONAL = True

# Router: "minimum slot width = bit diameter", smaller bit 1.0 mm dia.
FLOOR_EDGE_SLOT = 1.00
# "minimum internal radius = bit radius, 0.8-1.0 mm" -- a corner sharper than
# this cannot be cut and the fab will fillet it.
EDGE_SHARP_CORNER_DEG = 60.0

# Minimum legible character height, mm. Doc: silk ~0.9-1.2, copper reliable
# zone 0.6-0.8 (0.5 best case).
CHAR_H_SILK = 0.9
CHAR_H_COPPER = 0.6

# Geometry
OUTLIER_MM = 1.0          # bbox escape allowance
OUTLIER_DOMINANCE = 0.25  # a lone outlier must also dominate the bbox
DUP_EPS = 1e-6            # mm, duplicate-point tolerance
COORD_SANITY_MM = 1000.0  # a vertex beyond this is a transform blowup

# --------------------------------------------------------------------------
# Layer taxonomy
# --------------------------------------------------------------------------

# Every layer KiCad knows. Used only to tell "known layer, wrong for art" from
# "not a layer at all" -- kicad-cli silently rescues the latter (verified: an
# unknown layer name is remapped to "Rescue" and fp upgrade still exits 0), so
# the harness has to catch it because KiCad will not.
KNOWN_LAYERS = {
    "F.Cu", "B.Cu", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS",
    "F.Paste", "B.Paste", "F.Adhes", "B.Adhes", "F.CrtYd", "B.CrtYd",
    "F.Fab", "B.Fab", "Edge.Cuts", "Margin", "Dwgs.User", "Cmts.User",
    "Eco1.User", "Eco2.User",
}
KNOWN_LAYERS |= {f"In{i}.Cu" for i in range(1, 31)}
KNOWN_LAYERS |= {f"User.{i}" for i in range(1, 10)}

# Documentation layers: not fabricated as art, but legitimate annotation.
# WARN rather than FAIL -- coupon_blocks.py deliberately marks T8 keepout
# outlines on Dwgs.User for a rule area to be drawn on the board.
ANNOTATION_LAYERS = {
    "Dwgs.User", "Cmts.User", "Eco1.User", "Eco2.User", "Margin",
    "F.Fab", "B.Fab", "F.CrtYd", "B.CrtYd",
} | {f"User.{i}" for i in range(1, 10)}

# Graphic items worth reading out of a footprint.
GRAPHIC_HEADS = {
    "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly",
    "fp_text", "fp_text_box", "pad", "property",
}


def layer_class(layer: str) -> str:
    """Which fabrication floor governs this layer."""
    if layer.endswith(".SilkS"):
        return "silk"
    if layer.endswith(".Mask"):
        return "mask"
    if layer in ("F.Cu", "B.Cu"):
        return "copper"
    if re.fullmatch(r"In\d+\.Cu", layer or ""):
        return "buried"
    if layer == "Edge.Cuts":
        return "edge"
    return "other"


# --------------------------------------------------------------------------
# S-expression parser
# --------------------------------------------------------------------------

class ParseError(Exception):
    pass


def parse_sexpr(text: str):
    """Parse KiCad s-expressions into nested lists of str. Iterative, so a
    pathological file cannot blow the Python stack."""
    stack: list[list] = []
    out: list = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "(":
            node: list = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            i += 1
        elif c == ")":
            if not stack:
                raise ParseError(f"unbalanced ')' at offset {i}")
            node = stack.pop()
            if not stack:
                out.append(node)
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            if i >= n:
                raise ParseError("unterminated string")
            i += 1
            (stack[-1] if stack else out).append("".join(buf))
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            (stack[-1] if stack else out).append(text[i:j])
            i = j
    if stack:
        raise ParseError("unbalanced '(' -- missing closing paren")
    return out


def kids(node, head):
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def kid(node, head):
    got = kids(node, head)
    return got[0] if got else None


def fnum(tok, default=None):
    try:
        v = float(tok)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def node_xy(node, default=(0.0, 0.0)):
    if node is None or len(node) < 3:
        return default
    return (fnum(node[1], 0.0), fnum(node[2], 0.0))


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def bbox_of(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def bbox_inflate(b, d):
    return None if b is None else (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def convex_hull(pts):
    p = sorted(set((round(x, 9), round(y, 9)) for x, y in pts))
    if len(p) < 3:
        return p

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper = []
    for q in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def min_width(pts):
    """Minimum width of a point set, via rotating calipers on the convex hull.

    For a rectangle this is exactly the short side. For a CONCAVE polygon the
    hull overestimates -- i.e. it under-reports risk, never over-reports it.
    Callers surface that caveat.
    """
    h = convex_hull(pts)
    if len(h) < 2:
        return 0.0
    if len(h) == 2:
        return 0.0
    best = float("inf")
    m = len(h)
    for i in range(m):
        ax, ay = h[i]
        bx, by = h[(i + 1) % m]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L < 1e-12:
            continue
        far = 0.0
        for (px, py) in h:
            d = abs((px - ax) * ey - (py - ay) * ex) / L
            if d > far:
                far = d
        best = min(best, far)
    return 0.0 if best == float("inf") else best


def seg_seg_intersect(p1, p2, p3, p4, eps=1e-12):
    """True for a proper crossing or a collinear overlap of positive length."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def on_seg(a, b, c):
        return (min(a[0], b[0]) - eps <= c[0] <= max(a[0], b[0]) + eps and
                min(a[1], b[1]) - eps <= c[1] <= max(a[1], b[1]) + eps)

    d1, d2 = cross(p3, p4, p1), cross(p3, p4, p2)
    d3, d4 = cross(p1, p2, p3), cross(p1, p2, p4)
    if ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and \
       ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)):
        return True
    # collinear overlap
    if abs(d1) <= eps and abs(d2) <= eps and abs(d3) <= eps and abs(d4) <= eps:
        for a, b, c in ((p1, p2, p3), (p1, p2, p4), (p3, p4, p1), (p3, p4, p2)):
            if on_seg(a, b, c):
                # touching only at a shared endpoint is not an overlap
                if c in (p1, p2, p3, p4):
                    others = [q for q in (p1, p2, p3, p4) if q != c]
                    if all(abs(q[0] - c[0]) < eps and abs(q[1] - c[1]) < eps
                           for q in others):
                        continue
                return True
    return False


def point_seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def seg_seg_dist(p1, p2, p3, p4):
    if seg_seg_intersect(p1, p2, p3, p4):
        return 0.0
    return min(point_seg_dist(p1, p3, p4), point_seg_dist(p2, p3, p4),
               point_seg_dist(p3, p1, p2), point_seg_dist(p4, p1, p2))


def edges_of(pts, closed=True):
    e = []
    n = len(pts)
    if n < 2:
        return e
    for i in range(n - 1):
        e.append((pts[i], pts[i + 1]))
    if closed and n > 2:
        e.append((pts[-1], pts[0]))
    return e


# --------------------------------------------------------------------------
# Item model
# --------------------------------------------------------------------------

@dataclass
class Item:
    kind: str
    layers: list[str] = field(default_factory=list)
    pts: list[tuple[float, float]] = field(default_factory=list)
    width: float = 0.0          # stroke width, mm
    filled: bool = False
    text: str = ""
    char_h: float = 0.0
    thickness: float = 0.0
    approx_bbox: bool = False   # True when extents are estimated (text)
    has_curves: bool = False    # poly contained arc/bezier pts we could not read
    # Text placement, kept so the letterforms can be EXPANDED rather than
    # summarised by a bounding box. See expand_text().
    at: tuple[float, float] = (0.0, 0.0)
    angle: float = 0.0
    justify: frozenset = frozenset()
    font_flags: tuple = ()      # ('bold',) / ('italic',) -- unmodelled shapes
    hidden: bool = False        # KiCad does not plot it, so the fab never sees it
    _ink: "TextInk | None" = None

    def bbox(self):
        b = bbox_of(self.pts)
        if b is None:
            return None
        return bbox_inflate(b, self.width / 2.0) if self.width else b


@dataclass
class Footprint:
    name: str
    version: str
    generator: str
    items: list[Item]
    raw_layer: str = ""
    tags: str = ""


def _layers_of(node) -> list[str]:
    out = []
    for head in ("layer", "layers"):
        for ln in kids(node, head):
            for tok in ln[1:]:
                if isinstance(tok, str):
                    out.append(tok)
    return out


def _stroke_width(node) -> float:
    st = kid(node, "stroke")
    if st is not None:
        w = kid(st, "width")
        if w is not None and len(w) > 1:
            return fnum(w[1], 0.0) or 0.0
    w = kid(node, "width")  # legacy form
    if w is not None and len(w) > 1:
        return fnum(w[1], 0.0) or 0.0
    return 0.0


def _is_filled(node) -> bool:
    f = kid(node, "fill")
    if f is None:
        return False
    if len(f) > 1 and isinstance(f[1], str):
        return f[1] in ("solid", "yes", "true")
    return False


# --- text extents -----------------------------------------------------------
# The old estimate here was "roughly 0.75 em advance per character", which is a
# rule of thumb and reads about 15% narrow for lowercase-heavy strings. That
# under-reports the extent, and under-reporting is the dangerous direction for a
# harness: it made a mask block that correctly framed a row of microtext look
# like a polygon flung off on its own, and failed a good footprint.
#
# tools/stroke_font.py now carries the newstroke metrics MEASURED off a
# kicad-cli render -- per-glyph advance, per-glyph ink box, and the amount
# `justify left` slides the text as the pen gets heavier. Use them when they
# apply, and stay deliberately conservative when they do not: an over-large box
# can only make this harness less trigger-happy, never blind.

_SF = None
_SF_TRIED = False
_SF_NOTE = ""


def _stroke_font():
    global _SF, _SF_TRIED, _SF_NOTE
    if not _SF_TRIED:
        _SF_TRIED = True
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import stroke_font as sf
            _SF = sf
        except Exception as e:                      # pragma: no cover
            _SF_NOTE = (f"tools/stroke_font.py could not be imported ({e}); "
                        f"text extents fall back to a conservative estimate")
    return _SF


def _justify_of(node) -> set[str]:
    eff = kid(node, "effects")
    out: set[str] = set()
    if eff is None:
        return out
    for j in kids(eff, "justify"):
        for tok in j[1:]:
            if isinstance(tok, str):
                out.add(tok)
    return out


def _text_box(s: str, h: float, t: float, just: set[str]):
    """Ink box of `s` relative to its anchor -> ((x0,y0,x1,y1), exact).

    `exact` is False whenever anything had to be assumed, which is what keeps
    Item.approx_bbox honest instead of blanket-true.
    """
    if h <= 0:
        return (0.0, 0.0, 0.0, 0.0), False
    sf = _stroke_font()
    if sf is not None:
        try:
            m = sf.measure_string(s, allow_unmeasured=False,
                                  stroke_ratio=(t / h) if t > 0 else None)
        except Exception:
            m = None
        if m is not None and m.ink_em is not None:
            x0, y0, x1, y1 = (v * h for v in m.ink_em)
            pen = (t or 0.0) / 2.0        # ink is centred on the centreline
            if "left" in just:
                return (x0 - pen, y0 - pen, x1 + pen, y1 + pen), True
            # Only `justify left` has been measured against a render; every
            # other justification is placed from the advance width, which is
            # right to within the side bearings but has not been confirmed.
            adv = m.advance_em * h
            if "right" in just:
                return (-adv + x0 - pen, y0 - pen, -adv + x1 + pen, y1 + pen), False
            return (-adv / 2 - pen, y0 - pen, adv / 2 + pen, y1 + pen), False
    # No metrics: reserve the WIDEST glyph in the font for every character, and
    # a full ascender-to-descender band. Too big on purpose.
    w = max(len(s), 1) * h * (getattr(sf, "MAX_ADVANCE_EM", 1.34) if sf else 1.34)
    asc, desc = 0.69 * h, 0.85 * h
    if "left" in just:
        return (0.0, -asc, w, desc), False
    if "right" in just:
        return (-w, -asc, 0.0, desc), False
    return (-w / 2, -asc, w / 2, desc), False


# --- text EXPANSION ---------------------------------------------------------
# The bounding box above answers "where is this text". It cannot answer "how
# close does this ink get to other ink", and copper spacing is exactly that
# question. FabProfile.min_copper_mm is minimum trace width AND SPACING, and
# only the width half was ever modelled here -- by reading the (thickness ...)
# attribute back out of the file under test, which measures nothing at all.
# Meanwhile the gap check collected fp_line, fp_poly and fp_rect, so an fp_text
# could not participate in it even in principle. A 1712-character microprinted
# part therefore passed every check while its narrowest copper-to-copper gap
# was 29% of its own fabricator's floor.
#
# So the letterforms get expanded. tools/stroke_font.GLYPH_PATHS carries the
# newstroke centrelines measured off kicad-cli, and string_chains() places them
# with the advance, pen-shift and justification model validated against the
# same renderer. Everything below turns that into footprint coordinates.

@dataclass
class TextInk:
    """Expanded letterforms of one text item, in footprint mm."""
    chains: list[list[tuple[float, float]]] = field(default_factory=list)
    width: float = 0.0                  # pen width, mm -- the ink is this wide
    counters: dict[str, float] = field(default_factory=dict)  # char -> em
    why: str = ""                       # why it could NOT be expanded

    @property
    def ok(self) -> bool:
        return not self.why

    @property
    def n_seg(self) -> int:
        return sum(max(0, len(c) - 1) for c in self.chains)


def _draw_angle(ang: float) -> float:
    """The angle KiCad actually PLOTS text at.

    KiCad refuses to draw footprint text upside down: an item whose angle lands
    in (90, 270] is plotted rotated a further 180 degrees. Measured, not read
    off the source -- rendering 'Hxy8e j' at 0/60/89/90/91/120/179/180/181/240/
    269/270/271/300/-30/-90/-120 degrees and matching each plot against both
    candidates puts the switch between 90 (no flip) and 91 (flip), and between
    270 (flip) and 271 (no flip). Ignoring it puts a rotated string 180 degrees
    away from its own letterforms, which is a wrong answer, not a rough one.
    """
    a = ang % 360.0
    return ang + 180.0 if 90.0 < a <= 270.0 else ang


def expand_text(it: Item) -> TextInk:
    """Stroke centrelines of a text item in footprint coordinates.

    Never guesses. Anything this cannot model -- an unmeasured character, a
    bold or italic face whose letterforms are not the ones in the table, a
    wrapped fp_text_box -- comes back with `why` set, and every caller must
    report that as NOT MEASURED rather than treating the item as absent. An
    item silently treated as absent is precisely how the gap check managed to
    pass a part it had never looked at.
    """
    if it._ink is not None:
        return it._ink
    sf = _stroke_font()
    ink = TextInk(width=it.thickness)
    if it.hidden or not it.text.strip(" "):
        # Not an inability -- an absence. Hidden text is never plotted, and an
        # empty or all-space string draws nothing whatever its size and pen, so
        # neither has geometry to measure or to keep clear of. Checked BEFORE
        # the size and thickness tests below: an empty (property "Reference" "")
        # carries no thickness, and calling that "could not be measured" is a
        # loud unknown about a thing that is not there.
        it._ink = ink
        return ink
    if sf is None:
        ink.why = f"tools/stroke_font.py could not be imported ({_SF_NOTE})"
    elif not hasattr(sf, "string_chains"):
        ink.why = ("tools/stroke_font.py has no GLYPH_PATHS table, so there are "
                   "no letterforms to place (an older copy of the module?)")
    elif it.kind == "fp_text_box":
        ink.why = ("fp_text_box wraps its own text; the line breaks KiCad picks "
                   "are not modelled here")
    elif it.font_flags:
        ink.why = (f"font is {'+'.join(it.font_flags)}; GLYPH_PATHS holds the "
                   f"regular face only, and a different face is different "
                   f"letterforms")
    elif it.char_h <= 0:
        ink.why = "text has no font size"
    elif it.thickness <= 0:
        ink.why = "text has no font thickness, so its ink has no width"
    elif "\n" in it.text or "\r" in it.text:
        ink.why = "multi-line text; line placement is not modelled here"
    else:
        missing = sorted({c for c in it.text if c not in sf.GLYPH_PATHS})
        if missing:
            ink.why = (f"characters with no measured letterform: "
                       f"{''.join(missing)!r}")
    if ink.why:
        it._ink = ink
        return ink

    local = sf.string_chains(it.text, it.char_h, it.thickness, it.justify)
    ang = _draw_angle(it.angle)
    x0, y0 = it.at
    if ang:
        # KiCad text angles are counter-clockwise as displayed and file y grows
        # downward, so this is the transpose of the usual rotation -- the same
        # convention build_item() uses for the bounding box.
        a = math.radians(ang)
        c, s = math.cos(a), math.sin(a)
        ink.chains = [[(x * c + y * s + x0, -x * s + y * c + y0) for (x, y) in ch]
                      for ch in local]
    else:
        ink.chains = [[(x + x0, y + y0) for (x, y) in ch] for ch in local]

    for ch in set(it.text):
        g = sf.GLYPHS.get(ch)
        if g and g[2] is not None:
            ink.counters[ch] = g[2]
    it._ink = ink
    return ink


# --- what kicad-cli actually plotted ----------------------------------------

_SVG_PATH_RE = re.compile(r'<path\s+d="([^"]*)"')
_SVG_TEXTG_RE = re.compile(r'<g class="stroked-text">(.*?)</g>', re.S)
_SVG_SW_RE = re.compile(r"stroke-width:\s*([0-9.eE+-]+)")


def svg_text_segments(svg: str) -> list[tuple[float, float, float, float]] | None:
    """Every stroke-font segment kicad-cli drew, as (x0,y0,x1,y1) bounding
    boxes in the SVG's own frame (mm, but translated by the plot origin).

    KiCad tags stroke-font strings with <g class="stroked-text">, which is what
    separates glyph strokes from ordinary graphics -- geometry cannot, since
    the stem of an 'H' is just a line.

    None means the plot could not be read, which is a different answer from []
    ("the plot contains no stroke text") and must not be allowed to masquerade
    as a disagreement with the model.
    """
    out = []
    for body in _SVG_TEXTG_RE.findall(svg):
        for d in _SVG_PATH_RE.findall(body):
            nums = []
            for tok in d.replace("\n", " ").split():
                if tok[:1].isalpha():
                    if tok[0] not in ("M", "L"):
                        return None         # not the polyline form we can read
                    tok = tok[1:]
                    if not tok:
                        continue
                try:
                    nums.append(float(tok))
                    continue
                except ValueError:
                    return None
            pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
            for i in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[i], pts[i + 1]
                out.append((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
    return out


def svg_text_pen_widths(svg: str) -> list[float]:
    """The stroke-width in force for each stroke-text group KiCad emitted.

    This is the number that decides how wide the ink really is. Comparing it to
    the (thickness ...) in the file is the difference between measuring the
    plot and quoting the request back.
    """
    out = []
    for m in _SVG_TEXTG_RE.finditer(svg):
        before = svg[:m.start()]
        sw = _SVG_SW_RE.findall(before)
        if sw:
            try:
                out.append(float(sw[-1]))
            except ValueError:
                pass
    return out


def cross_check_expansion(fp: "Footprint", svg: str) -> str:
    """Compare the expanded letterforms against the ones kicad-cli plotted.

    Alignment is by bounding-box corner, because `fp export svg` translates the
    plot to the origin and the offset is not recorded in the file. That makes
    this a check of SHAPE and COUNT, not of absolute position -- which is the
    honest description of what it proves, and it is still the thing that would
    catch a wrong advance, a wrong justification model or a missing glyph.
    """
    got = svg_text_segments(svg)
    if got is None:
        return ("expansion NOT cross-checked: this kicad-cli writes stroke text "
                "in a form this reader does not handle")
    mine: list[tuple[float, float, float, float]] = []
    unmeasured = 0
    for it in fp.items:
        if it.kind not in ("fp_text", "fp_text_box", "property") or it.hidden:
            continue
        ink = expand_text(it)
        if not ink.ok:
            unmeasured += 1
            continue
        for ch in ink.chains:
            for i in range(len(ch) - 1):
                (ax, ay), (bx, by) = ch[i], ch[i + 1]
                mine.append((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
    if not got and not mine:
        return ""
    if unmeasured:
        return (f"expansion NOT cross-checked: {unmeasured} text item(s) could "
                f"not be expanded, so the plot and the model are not comparable")
    if len(got) != len(mine):
        return (f"EXPANSION DISAGREES WITH KICAD: kicad-cli plotted {len(got)} "
                f"stroke segment(s), the expansion produced {len(mine)}. Treat "
                f"every width and gap below as unreliable; "
                f"tests/test_verify_art.py::"
                f"test_every_baked_glyph_still_matches_this_kicad re-measures "
                f"the whole table against this renderer and will say which "
                f"glyphs moved")
    dx = min(g[0] for g in got) - min(m[0] for m in mine)
    dy = min(g[1] for g in got) - min(m[1] for m in mine)
    Q = 0.001
    buckets: dict[tuple, list] = {}
    for m in mine:
        k = (int(round((m[0] + dx) / Q)), int(round((m[1] + dy) / Q)),
             int(round((m[2] + dx) / Q)), int(round((m[3] + dy) / Q)))
        buckets.setdefault(k, []).append((m[0] + dx, m[1] + dy,
                                          m[2] + dx, m[3] + dy))
    worst, unmatched = 0.0, 0
    for g in got:
        k0 = (int(round(g[0] / Q)), int(round(g[1] / Q)),
              int(round(g[2] / Q)), int(round(g[3] / Q)))
        best = None
        # The exact bucket answers for anything agreeing to better than half a
        # quantum, which is every segment when the model is right. Widening to
        # the 3^4 neighbourhood costs 81x and is only needed for a value that
        # happens to straddle a bucket edge, so it is the fallback, not the path.
        for c in buckets.get(k0, ()):
            e = max(abs(c[i] - g[i]) for i in range(4))
            if best is None or e < best:
                best = e
        if best is None or best > Q / 2:
            for d0 in (-1, 0, 1):
                for d1 in (-1, 0, 1):
                    for d2 in (-1, 0, 1):
                        for d3 in (-1, 0, 1):
                            for c in buckets.get((k0[0] + d0, k0[1] + d1,
                                                  k0[2] + d2, k0[3] + d3), ()):
                                e = max(abs(c[i] - g[i]) for i in range(4))
                                if best is None or e < best:
                                    best = e
        if best is None:
            unmatched += 1
        else:
            worst = max(worst, best)
    if unmatched:
        return (f"EXPANSION DISAGREES WITH KICAD: {unmatched} of {len(got)} "
                f"plotted segment(s) have no counterpart in the expansion")
    return (f"expansion cross-checked against kicad-cli's own plot: "
            f"{len(got)}/{len(got)} segments matched, worst deviation "
            f"{worst:.6f} mm")


def build_item(node) -> Item | None:
    head = node[0]
    layers = _layers_of(node)
    width = _stroke_width(node)

    if head == "fp_line":
        a = node_xy(kid(node, "start"))
        b = node_xy(kid(node, "end"))
        return Item("fp_line", layers, [a, b], width)

    if head == "fp_rect":
        (x0, y0) = node_xy(kid(node, "start"))
        (x1, y1) = node_xy(kid(node, "end"))
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return Item("fp_rect", layers, pts, width, _is_filled(node))

    if head == "fp_circle":
        (cx, cy) = node_xy(kid(node, "center"))
        (ex, ey) = node_xy(kid(node, "end"))
        r = math.hypot(ex - cx, ey - cy)
        pts = [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
        it = Item("fp_circle", layers, pts, width, _is_filled(node))
        it.char_h = r  # stash radius; used by min-feature
        return it

    if head == "fp_arc":
        pts = [node_xy(kid(node, "start")), node_xy(kid(node, "mid")),
               node_xy(kid(node, "end"))]
        it = Item("fp_arc", layers, pts, width)
        it.approx_bbox = True  # true arc bulge is not bounded by its 3 points
        return it

    if head == "fp_poly":
        p = kid(node, "pts")
        pts, curves = [], False
        if p is not None:
            for c in p[1:]:
                if isinstance(c, list) and c:
                    if c[0] == "xy" and len(c) >= 3:
                        pts.append((fnum(c[1], 0.0), fnum(c[2], 0.0)))
                    elif c[0] in ("arc", "bezier"):
                        curves = True
        it = Item("fp_poly", layers, pts, width, _is_filled(node))
        it.has_curves = curves
        return it

    if head in ("fp_text", "fp_text_box", "property"):
        s = ""
        if head == "property":
            # (property "Name" "Value" ...): the SECOND string is the text that
            # gets drawn. Taking the first one made every property render as
            # its own field name -- harmless while text was only a bounding
            # box, wrong the moment the letterforms are expanded.
            if len(node) > 2 and isinstance(node[2], str):
                s = node[2]
        else:
            for tok in node[1:]:
                if isinstance(tok, str) and tok not in (
                        "user", "reference", "value", "hide", "unlocked",
                        "knockout"):
                    s = tok
                    break
        at = kid(node, "at")
        x, y = node_xy(at)
        h = t = 0.0
        eff = kid(node, "effects")
        if eff is not None:
            font = kid(eff, "font")
            if font is not None:
                sz = kid(font, "size")
                if sz is not None and len(sz) > 1:
                    h = fnum(sz[1], 0.0) or 0.0
                th = kid(font, "thickness")
                if th is not None and len(th) > 1:
                    t = fnum(th[1], 0.0) or 0.0
        flags = []
        if eff is not None:
            font = kid(eff, "font")
            if font is not None:
                for tok in font[1:]:
                    if isinstance(tok, str) and tok in ("bold", "italic"):
                        flags.append(tok)
                for f in ("bold", "italic"):
                    fk = kid(font, f)
                    if fk is not None and (len(fk) < 2 or fk[1] in ("yes", "true")):
                        if f not in flags:
                            flags.append(f)
        ang = fnum(at[3], 0.0) if at is not None and len(at) > 3 else 0.0
        just = _justify_of(node)
        box, exact = _text_box(s, h, t, just)
        pts = []
        for (dx, dy) in ((box[0], box[1]), (box[2], box[1]),
                         (box[2], box[3]), (box[0], box[3])):
            if ang:
                # KiCad text angles are counter-clockwise as displayed and file
                # y grows downward, so this is the transpose of the usual form.
                a = math.radians(ang)
                c, sn = math.cos(a), math.sin(a)
                dx, dy = dx * c + dy * sn, -dx * sn + dy * c
            pts.append((x + dx, y + dy))
        it = Item(head, layers, pts, 0.0, False, s, h, t)
        it.approx_bbox = not exact
        it.at = (x, y)
        it.angle = ang
        it.justify = frozenset(just)
        it.font_flags = tuple(flags)
        # Hidden text is not plotted, so it is not on the board and cannot be
        # too fine, too close or too small. Both spellings: the bare `hide`
        # token of the old format and the `(hide yes)` of the new one.
        hk = kid(node, "hide")
        it.hidden = (any(t == "hide" for t in node[1:] if isinstance(t, str))
                     or (hk is not None and (len(hk) < 2 or hk[1] in ("yes", "true"))))
        return it

    if head == "pad":
        at = kid(node, "at")
        x, y = node_xy(at)
        sz = kid(node, "size")
        w = h = 0.0
        if sz is not None and len(sz) > 2:
            w, h = fnum(sz[1], 0.0) or 0.0, fnum(sz[2], 0.0) or 0.0
        pts = [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2),
               (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)]
        return Item("pad", layers, pts, 0.0, True)

    return None


def load_footprint(path: Path) -> Footprint:
    text = path.read_text(encoding="utf-8", errors="replace")
    nodes = parse_sexpr(text)
    fps = [n for n in nodes if isinstance(n, list) and n and n[0] in ("footprint", "module")]
    if not fps:
        raise ParseError("no (footprint ...) node found")
    if len(fps) > 1:
        raise ParseError(f"{len(fps)} footprint nodes in one file (expected 1)")
    fp = fps[0]

    name = fp[1] if len(fp) > 1 and isinstance(fp[1], str) else "?"
    v = kid(fp, "version")
    g = kid(fp, "generator")
    lay = kid(fp, "layer")
    tg = kid(fp, "tags")

    items = []
    for c in fp:
        if isinstance(c, list) and c and c[0] in GRAPHIC_HEADS:
            it = build_item(c)
            if it is not None:
                items.append(it)

    return Footprint(
        name=name,
        version=(v[1] if v and len(v) > 1 else "?"),
        generator=(g[1] if g and len(g) > 1 else "?"),
        items=items,
        raw_layer=(lay[1] if lay and len(lay) > 1 else ""),
        tags=(tg[1] if tg and len(tg) > 1 and isinstance(tg[1], str) else ""),
    )


# --------------------------------------------------------------------------
# Palette: read the floors and the legal layer set out of the doc
# --------------------------------------------------------------------------

@dataclass
class Palette:
    recipe_layers: set[str]
    floors: dict[str, float]
    buried_provisional: bool
    source: str
    notes: list[str]
    # Floor classes whose number came from a NAMED FABRICATOR rather than from
    # the palette doc. The distinction decides severity: the doc's numbers are
    # house guidance and a part under them is a risk to review, but a vendor's
    # published limit is what the vendor will actually image, and a part under
    # THAT is not a risk -- it is a part that cannot be built. See _severity().
    hard: set[str] = field(default_factory=set)


def load_palette(doc: Path | None, side: str) -> Palette:
    notes: list[str] = []
    recipe: set[str] = set()
    floors = {
        "silk": FLOOR_SILK, "mask": FLOOR_MASK, "copper": FLOOR_COPPER,
        "buried": FLOOR_BURIED, "edge": FLOOR_EDGE_SLOT,
    }
    buried_prov = FLOOR_BURIED_PROVISIONAL
    src = "built-in defaults"

    if doc and doc.is_file():
        text = doc.read_text(encoding="utf-8", errors="replace")
        src = str(doc)

        # T1..T7 come from the machine-readable recipe fence.
        m = re.search(r"###\s*How to draw each in a footprint\s*\n+```(.*?)```",
                      text, re.S)
        if m:
            recipe |= set(re.findall(r"\b([A-Z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9]*)\b",
                                     m.group(1)))
            recipe |= set(re.findall(r"\b(In\d+\.Cu)\b", m.group(1)))
        else:
            notes.append("could not find the 'How to draw each in a footprint' "
                         "recipe block -- falling back to built-in layer set")

        # T8/T9 are prose, not a fence. Named explicitly, verified present.
        for lyr, why in (("B.Mask", "T8 -- mask must come off both faces"),
                         ("Edge.Cuts", "T9 -- cuts")):
            if lyr in text or (lyr == "B.Mask" and "both faces" in text):
                recipe.add(lyr)
            else:
                notes.append(f"{lyr} ({why}) no longer mentioned in the palette doc")

        # Practical-limits table.
        for key, pat in (
            ("silk", r"\|\s*silkscreen\s*\|\s*~?([\d.]+)\s*mm"),
            ("mask", r"\|\s*mask opening\s*\|\s*~?([\d.]+)\s*mm"),
            ("copper", r"\|\s*copper\s*\|\s*~?([\d.]+)\s*mm"),
        ):
            mm = re.search(pat, text, re.I)
            if mm:
                floors[key] = float(mm.group(1))
            else:
                notes.append(f"could not read the {key} floor from the doc; "
                             f"using built-in {floors[key]} mm")

        if re.search(r"buried tone.*considerably larger", text, re.I):
            buried_prov = True
    else:
        notes.append(f"palette doc not found at {doc} -- using built-in floors "
                     f"and layer set. FIX THIS: the doc is the authority.")

    if not recipe:
        recipe = {"F.SilkS", "F.Mask", "F.Cu", "In1.Cu", "B.Mask", "Edge.Cuts"}

    # The doc states the two sides are symmetric: In1 shades the front, In2 the
    # back. Mirror the recipe set for back-side or double-sided art.
    def mirror(s: str) -> str:
        if s.startswith("F."):
            return "B." + s[2:]
        if s.startswith("B."):
            return "F." + s[2:]
        if s == "In1.Cu":
            return "In2.Cu"
        if s == "In2.Cu":
            return "In1.Cu"
        return s

    if side == "back":
        recipe = {mirror(s) for s in recipe}
    elif side == "both":
        recipe = recipe | {mirror(s) for s in recipe}

    return Palette(recipe, floors, buried_prov, src, notes)


# --------------------------------------------------------------------------
# kicad-cli discovery and invocation
# --------------------------------------------------------------------------

MIN_KICAD_MAJOR = 10


def _candidates() -> list[str]:
    out = []
    env = os.environ.get("KICAD_CLI")
    if env and (Path(env).is_file() or shutil.which(env)):
        out.append(env)
    for exe in ("kicad-cli", "kicad-cli.exe"):
        p = shutil.which(exe)
        if p:
            out.append(p)
    globs = [
        "/mnt/c/Program Files/KiCad/*/bin/kicad-cli.exe",
        "/mnt/c/Program Files (x86)/KiCad/*/bin/kicad-cli.exe",
        "C:/Program Files/KiCad/*/bin/kicad-cli.exe",
        "C:/Program Files (x86)/KiCad/*/bin/kicad-cli.exe",
        "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
        "/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli",
    ]
    for g in globs:
        if "*" in g:
            base, _, tail = g.partition("*")
            root = Path(base)
            parent = root if root.is_dir() else root.parent
            if parent.is_dir():
                out += [str(p) for p in sorted(parent.glob("*" + tail))]
        elif Path(g).is_file():
            out.append(g)
    seen, uniq = set(), []
    for p in out:
        rp = str(Path(p))
        if rp not in seen:
            seen.add(rp)
            uniq.append(rp)
    return uniq


def _probe_version(path: str) -> tuple[str, int]:
    try:
        r = run_cli(path, ["version"], timeout=60)
    except Exception:
        return "?", -1
    v = (r.stdout or "").strip().splitlines()
    v = v[0].strip() if v else "?"
    m = re.match(r"(\d+)", v)
    return v, (int(m.group(1)) if m else -1)


@dataclass
class CliChoice:
    path: str | None = None
    version: str = "?"
    major: int = -1
    rejected: list[str] = field(default_factory=list)


def find_kicad_cli(explicit: str | None) -> CliChoice:
    """Pick the NEWEST kicad-cli available, not merely the first on PATH.

    This matters: a distro kicad-cli 7 sitting earlier on PATH cannot parse a
    version-20241229 footprint and reports 'Unable to load library'. Selecting
    it would make the harness fail perfectly good art -- the exact failure mode
    this tool exists to prevent.
    """
    if explicit:
        if Path(explicit).is_file() or shutil.which(explicit):
            v, mj = _probe_version(explicit)
            return CliChoice(explicit, v, mj)
        return CliChoice(None, "?", -1, [f"{explicit} (not found)"])

    best, rejected = None, []
    for c in _candidates():
        v, mj = _probe_version(c)
        if mj < 0:
            rejected.append(f"{c} (would not report a version)")
            continue
        if best is None or mj > best.major:
            if best is not None:
                rejected.append(f"{best.path} ({best.version})")
            best = CliChoice(c, v, mj)
        else:
            rejected.append(f"{c} ({v})")
    if best is None:
        return CliChoice(None, "?", -1, rejected)
    best.rejected = rejected
    return best


_NEEDS_WSLPATH: bool | None = None


def _needs_wslpath(cli: str) -> bool:
    """A Windows kicad-cli.exe driven from a Linux (WSL) Python gets its
    arguments verbatim -- POSIX paths must be translated or it silently fails."""
    global _NEEDS_WSLPATH
    if _NEEDS_WSLPATH is None:
        _NEEDS_WSLPATH = (sys.platform != "win32"
                          and cli.lower().endswith(".exe")
                          and shutil.which("wslpath") is not None)
    return _NEEDS_WSLPATH


def host_path(p: Path, cli: str) -> str:
    if _needs_wslpath(cli):
        try:
            r = subprocess.run(["wslpath", "-w", str(p)], capture_output=True,
                               text=True, timeout=20, stdin=subprocess.DEVNULL)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return str(p)


def run_cli(cli: str, args: list[str], timeout: int = 180):
    # stdin MUST be devnull: kicad-cli inherits and drains stdin, which eats a
    # piped script out from under the shell running it.
    return subprocess.run([cli] + args, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


# --------------------------------------------------------------------------
# Check results
# --------------------------------------------------------------------------

@dataclass
class Check:
    key: str
    level: str
    headline: str
    details: list[str] = field(default_factory=list)


# --- 1. loads in KiCad ------------------------------------------------------

def check_kicad_load(path: Path, cfg) -> Check:
    cli = cfg.cli
    if not cli:
        return Check("kicad-load", SKIP,
                     "kicad-cli NOT FOUND -- this file is UNVERIFIED against KiCad",
                     ["searched PATH, $KICAD_CLI and the usual install dirs",
                      "pass --kicad-cli /path/to/kicad-cli to fix",
                      "this is NOT a pass: nothing confirmed the file loads"])
    if cfg.cli_major < MIN_KICAD_MAJOR:
        return Check("kicad-load", SKIP,
                     f"kicad-cli is version {cfg.kicad_version}, need "
                     f"{MIN_KICAD_MAJOR}+ -- this file is UNVERIFIED",
                     [f"using {cli}",
                      f"KiCad {cfg.cli_major} cannot parse a modern "
                      f"(version 20241229) footprint and would report a bogus "
                      f"failure, so the check was not run at all",
                      "pass --kicad-cli /path/to/kicad-10/kicad-cli to fix",
                      "this is NOT a pass"])

    details = []
    with tempfile.TemporaryDirectory(prefix="verify_art_") as td:
        tmp = Path(td)
        lib = tmp / "in.pretty"
        lib.mkdir()
        # fp upgrade operates on a LIBRARY DIRECTORY, not a single file, and
        # refuses an output path that already exists.
        shutil.copy2(path, lib / path.name)
        out = tmp / "out.pretty"

        try:
            r = run_cli(cli, ["fp", "upgrade", "--force",
                              "-o", host_path(out, cli), host_path(lib, cli)])
        except subprocess.TimeoutExpired:
            return Check("kicad-load", FAIL, "fp upgrade timed out")
        except OSError as e:
            return Check("kicad-load", FAIL, f"could not run kicad-cli: {e}")

        so = (r.stdout or "").replace("\r", "").strip()
        se = (r.stderr or "").replace("\r", "").strip()

        if r.returncode != 0:
            d = [f"exit={r.returncode}"]
            if se:
                d.append(f"stderr: {se}")
            if so:
                d.append(f"stdout: {so}")
            return Check("kicad-load", FAIL, "KiCad REJECTED this footprint", d)
        if se:
            return Check("kicad-load", FAIL, "fp upgrade wrote to stderr",
                         [f"stderr: {se}"])

        produced = out / path.name
        if not produced.is_file():
            # Guards against a vacuous pass: an empty library also exits 0 on
            # some paths, and "nothing converted" must never read as "ok".
            return Check("kicad-load", FAIL,
                         "fp upgrade exited 0 but produced no output footprint",
                         [f"expected {produced}"])
        details.append("fp upgrade: parsed and re-serialised cleanly")

        # KiCad silently remaps an unknown layer name onto a layer called
        # "Rescue" and still exits 0 -- verified on this install. Art that
        # lands there is gone. Catch it here since kicad-cli will not.
        up = produced.read_text(encoding="utf-8", errors="replace")
        if re.search(r'"Rescue"', up):
            return Check("kicad-load", FAIL,
                         "KiCad RESCUED an unrecognised layer -- art would be lost",
                         ['the upgraded file contains (layer "Rescue")',
                          "an unknown layer name was silently remapped; see the "
                          "layers check for which"])

        if cfg.render:
            # fp export svg wants its output dir to ALREADY EXIST -- the exact
            # opposite of fp upgrade. Get it wrong and the command exits 0
            # while writing nothing but "Error creating svg file" on stderr,
            # which is why this check treats any stderr as a failure.
            svg = tmp / "svg"
            svg.mkdir(parents=True, exist_ok=True)
            try:
                r2 = run_cli(cli, ["fp", "export", "svg",
                                   "-o", host_path(svg, cli), host_path(lib, cli)])
            except subprocess.TimeoutExpired:
                return Check("kicad-load", FAIL, "fp export svg timed out", details)
            se2 = (r2.stderr or "").replace("\r", "").strip()
            if r2.returncode != 0 or se2:
                return Check("kicad-load", FAIL,
                             "footprint parses but will not PLOT",
                             details + [f"fp export svg exit={r2.returncode}",
                                        f"stderr: {se2}" if se2 else ""])
            svgs = list(svg.glob("*.svg")) if svg.is_dir() else []
            if not svgs:
                return Check("kicad-load", FAIL,
                             "fp export svg exited 0 but rendered nothing", details)
            details.append(f"fp export svg: rendered {svgs[0].name} "
                           f"({svgs[0].stat().st_size:,} B)")
            # Keep the plot. It is the only independent statement of what KiCad
            # will actually draw, and the min-feature check uses it to confirm
            # that the letterforms it expanded are the letterforms KiCad emits.
            # The temp dir dies with this `with`, so read it now or not at all.
            try:
                cfg.render_svg = svgs[0].read_text(encoding="utf-8",
                                                   errors="replace")
            except OSError:
                cfg.render_svg = None
        else:
            details.append("fp export svg: skipped (--no-render)")

    return Check("kicad-load", PASS, f"loads in KiCad {cfg.kicad_version}", details)


# --- 2. size budget ---------------------------------------------------------

def check_size(path: Path, fp: Footprint, cfg) -> Check:
    n = path.stat().st_size
    bb = overall_bbox(fp)
    span = max(bb[2] - bb[0], bb[3] - bb[1]) if bb else 0.0
    human = f"{n:,} B ({n/1000:.1f} kB)"
    dims = f"{bb[2]-bb[0]:.1f} x {bb[3]-bb[1]:.1f} mm" if bb else "no geometry"
    approx = [it for it in fp.items if it.approx_bbox]
    d = [f"extent {dims}" + (f" ({len(approx)} item(s) with ESTIMATED extents "
                             f"-- arcs, or text this harness has no measured "
                             f"metrics for)" if approx else "")]
    if _SF_NOTE:
        d.append(_SF_NOTE)

    if span > ASSET_MM:
        d.append(f"NOTE: longest side {span:.1f} mm exceeds the {ASSET_MM:.0f} mm "
                 f"scope of the budget -- thresholds still applied, but a larger "
                 f"asset may legitimately need more bytes")
    if n > cfg.fail_bytes:
        return Check("size", FAIL,
                     f"{human} -- over the {cfg.fail_bytes/1000:.0f} kB hard limit", d)
    if n > cfg.warn_bytes:
        return Check("size", WARN,
                     f"{human} -- over the {cfg.warn_bytes/1000:.0f} kB budget", d)
    return Check("size", PASS, f"{human}", d)


# --- geometry helpers over a footprint -------------------------------------

def overall_bbox(fp: Footprint):
    b = None
    for it in fp.items:
        b = bbox_union(b, it.bbox())
    return b


def polys_of(fp: Footprint):
    """(index, item) for every filled-area item, which is what the geometry,
    self-intersection and clearance checks reason about."""
    return [(i, it) for i, it in enumerate(fp.items)
            if it.kind in ("fp_poly", "fp_rect")]


def reference_extent(fp: Footprint):
    """An extent independent of the polygons being tested. Courtyard first; a
    single closed Edge.Cuts loop (a board outline) second. Internal cutouts --
    several loops -- are deliberately NOT used: they bound holes, not the art."""
    crt = [it for it in fp.items if any(l in ("F.CrtYd", "B.CrtYd") for l in it.layers)]
    if crt:
        b = None
        for it in crt:
            b = bbox_union(b, it.bbox())
        if b:
            return b, "courtyard"
    edge = [it for it in fp.items if "Edge.Cuts" in it.layers]
    if edge:
        loops = closed_loops([it for it in edge if it.kind == "fp_line"])
        polys = [it for it in edge if it.kind in ("fp_poly", "fp_rect")]
        if len(loops) + len(polys) == 1:
            b = None
            for it in edge:
                b = bbox_union(b, it.bbox())
            if b:
                return b, "Edge.Cuts board outline"
    return None, None


def closed_loops(line_items, tol=1e-4):
    """Chain fp_line segments into closed loops. Needed because an Edge.Cuts
    slot's real feature size is the loop width, not the stroke width."""
    from collections import defaultdict
    adj = defaultdict(list)

    def key(p):
        return (round(p[0] / tol), round(p[1] / tol))

    segs = []
    for it in line_items:
        if len(it.pts) == 2:
            a, b = it.pts
            if key(a) != key(b):
                idx = len(segs)
                segs.append((a, b))
                adj[key(a)].append(idx)
                adj[key(b)].append(idx)

    used = [False] * len(segs)
    loops = []
    for s0 in range(len(segs)):
        if used[s0]:
            continue
        a, b = segs[s0]
        used[s0] = True
        chain = [a, b]
        cur = b
        while True:
            nxt = None
            for idx in adj[key(cur)]:
                if not used[idx]:
                    p, q = segs[idx]
                    nxt = (idx, q if key(p) == key(cur) else p)
                    break
            if nxt is None:
                break
            used[nxt[0]] = True
            cur = nxt[1]
            chain.append(cur)
            if key(cur) == key(chain[0]):
                break
        if len(chain) > 3 and key(chain[0]) == key(chain[-1]):
            loops.append(chain[:-1])
    return loops


# --- 3. geometry sanity -----------------------------------------------------

def check_geometry(fp: Footprint, cfg) -> Check:
    from collections import Counter
    per_layer = Counter()
    for _, it in polys_of(fp):
        if it.kind != "fp_poly":
            continue
        for l in (it.layers or ["<no layer>"]):
            per_layer[l] += 1

    counts = ", ".join(f"{l}={n}" for l, n in sorted(per_layer.items())) or "none"
    details = [f"fp_poly per layer: {counts}"]
    level = PASS
    problems: list[str] = []

    curved = sum(1 for _, it in polys_of(fp) if it.has_curves)
    if curved:
        level = worst(level, WARN)
        problems.append(f"{curved} fp_poly contain arc/bezier points that this "
                        f"harness does not evaluate -- their geometry is UNCHECKED")

    # degenerate / duplicate / non-finite
    thin, dups, bad = [], [], []
    for i, it in polys_of(fp):
        if it.kind == "fp_poly" and len(it.pts) < 3:
            thin.append(f"#{i} on {'/'.join(it.layers) or '?'} has "
                        f"{len(it.pts)} vertices")
        n = len(it.pts)
        for j in range(n):
            a, b = it.pts[j], it.pts[(j + 1) % n]
            if n > 1 and abs(a[0] - b[0]) < DUP_EPS and abs(a[1] - b[1]) < DUP_EPS:
                where = "closing point repeats the first" if j == n - 1 else \
                        f"vertices {j},{j+1} coincide"
                dups.append(f"#{i} on {'/'.join(it.layers) or '?'}: {where} "
                            f"at ({a[0]:.4f},{a[1]:.4f})")
                break
        for (x, y) in it.pts:
            if not (math.isfinite(x) and math.isfinite(y)) or \
               abs(x) > COORD_SANITY_MM or abs(y) > COORD_SANITY_MM:
                bad.append(f"#{i} vertex ({x},{y}) is non-finite or beyond "
                           f"+/-{COORD_SANITY_MM:.0f} mm")
                break

    tally: dict[str, int] = {}
    if curved:
        tally["arc/bezier unchecked"] = curved
    if thin:
        level = worst(level, FAIL)
        tally["degenerate"] = len(thin)
        problems += [f"DEGENERATE: {t}" for t in thin[:cfg.max_report]]
    if bad:
        level = worst(level, FAIL)
        tally["runaway coordinate"] = len(bad)
        problems += [f"RUNAWAY COORDINATE: {t}" for t in bad[:cfg.max_report]]
    if dups:
        level = worst(level, WARN)
        tally["duplicate point"] = len(dups)
        problems += [f"duplicate point: {t}" for t in dups[:cfg.max_report]]

    # bbox escape
    ref, ref_src = reference_extent(fp)
    if ref:
        esc = []
        for i, it in polys_of(fp):
            b = it.bbox()
            if not b:
                continue
            e = max(ref[0] - b[0], b[2] - ref[2], ref[1] - b[1], b[3] - ref[3])
            if e > cfg.outlier_mm:
                esc.append(f"#{i} on {'/'.join(it.layers) or '?'} escapes the "
                           f"{ref_src} by {e:.3f} mm")
        details.append(f"bbox escape measured against the {ref_src}")
        if esc:
            level = worst(level, FAIL)
            tally["escapes extent"] = len(esc)
            problems += [f"ESCAPES EXTENT: {t}" for t in esc[:cfg.max_report]]
    else:
        details.append("no courtyard and no single Edge.Cuts outline, so there is "
                       "no extent independent of the art itself; ran lone-outlier "
                       "detection instead")
        outliers = _lone_outliers(fp, cfg)
        if outliers:
            level = worst(level, FAIL)
            tally["lone outlier"] = len(outliers)
            problems += outliers

    total = sum(tally.values())
    if total > cfg.max_report:
        details.append(f"({total} geometry problems total; showing first "
                       f"{cfg.max_report} per category)")

    head = "clean" if level == PASS else \
        f"{total} issue(s): " + ", ".join(f"{n} {k}" for k, n in sorted(tally.items()))
    return Check("geometry", level, head, details + problems)


def _encloses(me, others) -> bool:
    """Does bbox `me` contain the union bbox of `others`?

    This is what separates a runaway polygon from a frame. The check is looking
    for a bad transform -- one polygon flung off on its own, adding extent while
    contributing nothing. A border, a badge disc or a logo's outer hexagon also
    reaches past every other polygon, by definition: it is the thing the rest
    sits inside. Every enclosing shape in this library was being reported as a
    defect (reckless_mono's hexagon, both MFB node badge discs).

    A stray never encloses the art it strayed from, so containment separates the
    two cleanly without needing a size or position rule. Containment is measured
    against the art only -- other suspected strays are excluded, otherwise one
    runaway polygon outside the frame would drag the frame in with it.
    """
    if not others:
        return False
    return (me[0] <= min(b[0] for b in others)
            and me[1] <= min(b[1] for b in others)
            and me[2] >= max(b[2] for b in others)
            and me[3] >= max(b[3] for b in others))


def _lone_outliers(fp: Footprint, cfg) -> list[str]:
    """A polygon that alone drags the footprint bbox out. Catches a bad
    transform without false-firing on ordinary tiled layouts, or on art whose
    outermost element encloses everything else (see _encloses_the_rest)."""
    boxes = [(i, it.bbox()) for i, it in enumerate(fp.items) if it.bbox()]
    if len(boxes) < 3:
        return []

    def extremes(axis, want_min):
        vals = sorted(((b[axis], i) for i, b in boxes), reverse=not want_min)
        return vals[0], vals[1]

    (x0v, x0i), (x0v2, _) = extremes(0, True)
    (y0v, y0i), (y0v2, _) = extremes(1, True)
    (x1v, x1i), (x1v2, _) = extremes(2, False)
    (y1v, y1i), (y1v2, _) = extremes(3, False)
    ow, oh = x1v - x0v, y1v - y0v
    poly_ix = {i for i, _ in polys_of(fp)}

    # Pass 1 -- who reaches out past everything else, and by how much.
    cand = []
    for i, b in boxes:
        if i not in poly_ix:
            continue
        ex0 = (x0v2 - b[0]) if i == x0i else 0.0
        ey0 = (y0v2 - b[1]) if i == y0i else 0.0
        ex1 = (b[2] - x1v2) if i == x1i else 0.0
        ey1 = (b[3] - y1v2) if i == y1i else 0.0
        e = max(ex0, ey0, ex1, ey1)
        if e <= cfg.outlier_mm:
            continue
        sx = (e / ow) if ow > 0 and max(ex0, ex1) > 0 else 0.0
        sy = (e / oh) if oh > 0 and max(ey0, ey1) > 0 else 0.0
        if max(sx, sy) > OUTLIER_DOMINANCE:
            cand.append((i, e, max(sx, sy)))

    # Pass 2 -- drop the ones that are frames. "The art" is everything that is
    # not itself a suspect, so a stray sitting outside the frame cannot make the
    # frame look like a stray too.
    suspect = {i for i, _, _ in cand}
    art = [b for j, b in boxes if j not in suspect]
    out = []
    for i, e, dom in cand:
        if _encloses(dict(boxes)[i], art):
            continue
        it = fp.items[i]
        out.append(f"LONE OUTLIER: #{i} on {'/'.join(it.layers) or '?'} sits "
                   f"{e:.3f} mm past everything else and accounts for "
                   f"{dom*100:.0f}% of the footprint extent")
    return out[:cfg.max_report]


# --- 4. layer legality ------------------------------------------------------

def check_layers(fp: Footprint, cfg) -> Check:
    from collections import Counter
    used = Counter()
    for it in fp.items:
        for l in it.layers:
            used[l] += 1

    pal = cfg.palette
    details = [f"palette recipes ({cfg.side}-side): "
               f"{', '.join(sorted(pal.recipe_layers))}"]
    legal, annot, illegal, unknown = [], [], [], []
    for l, n in sorted(used.items()):
        if l in pal.recipe_layers or l in cfg.allow_layers:
            legal.append(f"{l}({n})")
        elif l not in KNOWN_LAYERS:
            unknown.append(f"{l}({n})")
        elif l in ANNOTATION_LAYERS:
            annot.append(f"{l}({n})")
        else:
            illegal.append(f"{l}({n})")

    if legal:
        details.append(f"palette layers used: {', '.join(legal)}")
    level = PASS
    if annot:
        level = worst(level, WARN)
        details.append(f"ANNOTATION layers (not art, not fabricated as tone): "
                       f"{', '.join(annot)} -- legitimate for markup, but nothing "
                       f"drawn here becomes a palette tone")
    if illegal:
        level = worst(level, FAIL)
        details.append(f"OFF-PALETTE layers: {', '.join(illegal)} -- real KiCad "
                       f"layers, but no recipe in {Path(pal.source).name} draws "
                       f"on them for {cfg.side}-side art")
    if unknown:
        level = worst(level, FAIL)
        details.append(f"UNKNOWN layers: {', '.join(unknown)} -- not KiCad layer "
                       f"names; KiCad remaps these to 'Rescue' and the art is LOST")
    if not used:
        level = worst(level, WARN)
        details.append("no layers used at all -- the footprint draws nothing")

    if level == PASS:
        head = "all layers on-palette"
    else:
        bits = []
        if unknown:
            bits.append(f"{len(unknown)} unknown-to-KiCad")
        if illegal:
            bits.append(f"{len(illegal)} off-palette")
        if annot:
            bits.append(f"{len(annot)} annotation")
        head = ", ".join(bits)
    return Check("layers", level, head, details)


# --- 5. self-intersection ---------------------------------------------------
#
# What this check is actually for: a self-intersection is a defect because it
# makes the FILL AMBIGUOUS -- even-odd and nonzero disagree, so the plotter,
# the DRC engine and the fab's raster may each pick a different answer.
# "Two edges share a point" is a proxy for that, and it is the wrong proxy in
# two specific ways that matter for real art:
#
#   1. A vertex inserted in the middle of a straight edge splits it into two
#      collinear halves that touch at one point. Overlap length is ZERO. No
#      fill rule cares. Bridging inserts exactly this at every hole.
#
#   2. A polygon with holes is serialised to KiCad as one FRACTURED outline:
#      each hole is joined to the boundary by a zero-width slit traversed once
#      inward and once outward. KiCad's own zone filler does this
#      (SHAPE_POLY_SET::Fracture) and plots the result fill-rule:evenodd. An
#      edge traversed once in each direction changes the winding number of no
#      point off the segment, so both rules agree -- proven by rasterisation
#      in tests/test_keyhole_fill.py.
#
# So the pair classifier below separates the harmless degeneracies from the
# real hazards instead of lumping them together. Slits are COUNTED AND
# REPORTED, never silently swallowed, and anything else -- a proper crossing,
# a same-direction double traversal, a partial/unbalanced reverse overlap --
# still fails. tests/test_self_isect.py holds that line.

_SLIT = "slit"        # collinear, exact reverse traversal: zero-area fracture
_CROSS = "cross"      # proper crossing
_OVERLAP = "overlap"  # collinear overlap that is NOT a balanced reverse pair


def classify_edge_pair(p1, p2, p3, p4, tol=1e-9):
    """Classify how two polygon edges interact. None means 'no fill hazard'.

    Returns _CROSS, _OVERLAP, _SLIT, or None (disjoint, or contact over zero
    length). tol is in mm; 1e-9 is a nanometre, four orders below the 1e-5 mm
    KiCad file resolution, so it separates 'same point' from 'different point'
    without ever merging two distinct vertices.
    """
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1, d2 = cross(p3, p4, p1), cross(p3, p4, p2)
    d3, d4 = cross(p1, p2, p3), cross(p1, p2, p4)

    # Proper crossing: each segment strictly straddles the other's line.
    if ((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol)) and \
       ((d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol)):
        return _CROSS

    # Collinear? Use perpendicular DISTANCE, not the raw cross product, so the
    # test does not get stricter as the segments get longer.
    L1 = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    L2 = math.hypot(p4[0] - p3[0], p4[1] - p3[1])
    if L1 < tol or L2 < tol:
        return None                      # degenerate zero-length edge
    if max(abs(d3), abs(d4)) / L1 > tol or max(abs(d1), abs(d2)) / L2 > tol:
        return None                      # not collinear, and not crossing

    # Collinear: project both onto the first segment's direction and measure
    # the overlap. Zero-length contact (case 1 above) is not an intersection.
    ux, uy = (p2[0] - p1[0]) / L1, (p2[1] - p1[1]) / L1
    t3 = (p3[0] - p1[0]) * ux + (p3[1] - p1[1]) * uy
    t4 = (p4[0] - p1[0]) * ux + (p4[1] - p1[1]) * uy
    lo, hi = (t3, t4) if t3 <= t4 else (t4, t3)
    overlap = min(L1, hi) - max(0.0, lo)
    if overlap <= tol:
        return None

    # Positive overlap. A balanced fracture slit is the EXACT reverse of the
    # edge it doubles: same endpoints, opposite direction. Anything else --
    # same direction, or a partial overlap -- leaves a region whose traversal
    # count is odd, and the two fill rules part company there.
    if t4 < t3 and abs(t4) <= tol and abs(t3 - L1) <= tol:
        return _SLIT
    return _OVERLAP


def check_self_intersection(fp: Footprint, cfg) -> Check:
    hits = []
    slits = 0
    checked = skipped = 0
    for i, it in polys_of(fp):
        pts = [p for j, p in enumerate(it.pts)
               if j == 0 or abs(p[0] - it.pts[j-1][0]) > DUP_EPS
               or abs(p[1] - it.pts[j-1][1]) > DUP_EPS]
        if len(pts) < 4:
            continue
        if len(pts) > cfg.max_poly_pts:
            skipped += 1
            continue
        checked += 1
        e = edges_of(pts, closed=True)
        m = len(e)
        found = None
        for a in range(m):
            for b in range(a + 2, m):
                if a == 0 and b == m - 1:
                    continue  # adjacent across the closing edge
                k = classify_edge_pair(e[a][0], e[a][1], e[b][0], e[b][1])
                if k is None:
                    continue
                if k is _SLIT:
                    slits += 1
                    continue
                if found is None:
                    found = (a, b, k)
        if found:
            a, b, k = found
            what = "cross" if k is _CROSS else "overlap"
            hits.append(f"#{i} on {'/'.join(it.layers) or '?'}: edges "
                        f"{a} and {b} {what} ({len(pts)} vertices)")

    details = [f"{checked} polygon(s) tested"]
    level = PASS
    if skipped:
        level = worst(level, WARN)
        details.append(f"{skipped} polygon(s) over {cfg.max_poly_pts} vertices were "
                       f"NOT tested (O(n^2)); raise --max-poly-pts to include them "
                       f"-- these are UNCHECKED, not clean")
    if slits:
        details.append(f"{slits} zero-width fracture slit(s) -- hole bridges, "
                       f"each traversed once in each direction; zero area, and "
                       f"even-odd and nonzero agree, so the fill is unambiguous")
    if hits:
        level = worst(level, FAIL)
        details += [f"SELF-INTERSECTING: {h}" for h in hits[:cfg.max_report]]
        if len(hits) > cfg.max_report:
            details.append(f"({len(hits)} total; showing first {cfg.max_report})")
    if hits:
        head = f"{len(hits)} self-intersecting"
    elif slits:
        head = f"no self-intersections ({slits} hole-bridge slits)"
    else:
        head = "no self-intersections"
    return Check("self-isect", level, head, details)


# --- 6. minimum feature -----------------------------------------------------

def _floor_for(layer: str, pal: Palette) -> tuple[float | None, str, bool]:
    c = layer_class(layer)
    if c == "other":
        return None, c, False
    return pal.floors[c], c, (c == "buried" and pal.buried_provisional)


def _severity(cls: str, pal: Palette) -> str:
    """How bad is a feature under the floor of class `cls`?

    The palette doc's numbers are house guidance, and art under them is a risk
    worth reviewing -- WARN. A number taken from a NAMED FABRICATOR is not
    guidance: it is the finest thing that process images, published by the
    people who will run it. Art under that is not risky, it is missing from the
    delivered board, and calling that a warning is how an unbuildable part gets
    shipped past a green run. So a fab-sourced floor FAILs.
    """
    return FAIL if cls in pal.hard else WARN


def _ink_min_width(ink: TextInk) -> float | None:
    """Narrowest ink dimension of an expanded text item, mm. None if no ink.

    Walked over the expanded geometry rather than read off the file, and the
    answer being the pen width is a theorem, not a coincidence: the ink is the
    union of capsules of diameter `w` swept along the centrelines this function
    iterates, no capsule is anywhere narrower than `w`, and a union is never
    narrower than its narrowest member. A stroke shorter than `w` images as a
    disc of diameter `w`, which is the same number a third time.

    None matters. A string of spaces expands to no segments at all, and an item
    that contributes NO ink must not be quietly folded into a pass -- it has to
    surface as "there was nothing here to measure".
    """
    best = None
    for ch in ink.chains:
        for _ in range(len(ch) - 1):
            if best is None or ink.width < best:
                best = ink.width
    return best


def check_min_feature(fp: Footprint, cfg) -> Check:
    pal = cfg.palette
    # narrowest[layer] = (width, description)
    narrowest: dict[str, tuple[float, str]] = {}
    # Mask geometry is an OPENING and the mask floor is a DAM. Held apart on
    # purpose -- see the report below.
    openings: dict[str, tuple[float, str]] = {}
    unmeasured: dict[str, list[str]] = {}
    no_ink: list[str] = []
    concave_caveat = False
    n_text = n_chain = n_seg = 0

    def note(layer, w, desc):
        if w is None or w <= 0:
            return
        cur = narrowest.get(layer)
        if cur is None or w < cur[0]:
            narrowest[layer] = (w, desc)

    def note_opening(layer, w, desc):
        if w is None or w <= 0:
            return
        cur = openings.get(layer)
        if cur is None or w < cur[0]:
            openings[layer] = (w, desc)

    def cannot(layer, why):
        # Only meaningful where a floor exists. F.Fab and the User layers are
        # not fabricated, so "the narrowest feature is unknown" there is a
        # sentence about nothing and would bury the real ones.
        if _floor_for(layer, pal)[0] is None:
            return
        unmeasured.setdefault(layer, []).append(why)

    for i, it in enumerate(fp.items):
        for layer in it.layers:
            if layer == "Edge.Cuts":
                continue  # handled separately: stroke width is not the feature
            # On a mask layer the drawn shape is the HOLE, not the material, so
            # its width is an aperture and the only mask number in hand is a
            # dam. Routed to note_opening() and never compared to it.
            put = note_opening if layer_class(layer) == "mask" else note
            if it.kind == "fp_line":
                put(layer, it.width, f"fp_line #{i} stroke")
            elif it.kind in ("fp_poly", "fp_rect"):
                if it.filled:
                    w = min_width(it.pts)
                    if len(it.pts) > 4:
                        concave_caveat = True
                    put(layer, w, f"{it.kind} #{i} min width")
                else:
                    put(layer, it.width, f"{it.kind} #{i} stroke")
            elif it.kind == "fp_circle":
                put(layer, it.width if not it.filled else 2 * it.char_h,
                    f"fp_circle #{i}")
            elif it.kind == "fp_arc":
                put(layer, it.width, f"fp_arc #{i} stroke")
            elif it.kind in ("fp_text", "fp_text_box", "property"):
                if it.hidden:
                    continue        # never plotted, so never fabricated
                # EXPAND, then measure. Echoing it.thickness here WAS the
                # defect: it hands back the attribute the emitter wrote, so a
                # text item could never disagree with the file that made it.
                ink = expand_text(it)
                if not ink.ok:
                    cannot(layer, f"{it.kind} #{i} {it.text[:18]!r}: {ink.why}")
                    continue
                w = _ink_min_width(ink)
                if w is None:
                    # Measured, and the answer is "none". An empty or all-space
                    # string draws nothing, so there is no feature here to be
                    # too fine -- said out loud so it cannot be confused with
                    # the NOT MEASURED case below, but not a finding.
                    no_ink.append(f"  {layer:<10} {it.kind} #{i} "
                                  f"{it.text[:18]!r} draws no ink at all "
                                  f"(nothing to measure)")
                    continue
                put(layer, w, f"{it.kind} #{i} expanded letterforms "
                              f"({ink.n_seg} strokes, {it.text[:14]!r})")

    for it in fp.items:
        if it.kind in ("fp_text", "fp_text_box", "property") and not it.hidden:
            ink = expand_text(it)
            if ink.ok and ink.chains:
                n_text += 1
                n_chain += len(ink.chains)
                n_seg += ink.n_seg

    details, problems = [], []
    level = PASS

    if n_text:
        details.append(f"  text       {n_text} item(s) EXPANDED into {n_chain} "
                       f"stroke path(s) / {n_seg} segments and measured; the "
                       f"file's (thickness ...) is not taken on trust")
        svg = getattr(cfg, "render_svg", None)
        if svg:
            asked = sorted({round(it.thickness, 6) for it in fp.items
                            if it.kind in ("fp_text", "fp_text_box", "property")
                            and it.thickness > 0})
            plotted = sorted({round(p, 6) for p in svg_text_pen_widths(svg)})
            if plotted and plotted != asked:
                level = worst(level, _severity("copper", pal))
                problems.append(
                    f"PEN WIDTH DISAGREES: the file asks for "
                    f"{', '.join(f'{v:.4f}' for v in asked)} mm of stroke but "
                    f"kicad-cli plots {', '.join(f'{v:.4f}' for v in plotted)} "
                    f"mm. The board gets KiCad's number, not the file's")
            elif plotted:
                details.append(f"  text       kicad-cli plots it at "
                               f"{', '.join(f'{v:.4f}' for v in plotted)} mm, "
                               f"which is what the file asks for")
            xnote = cross_check_expansion(fp, svg)
            if xnote.startswith("EXPANSION DISAGREES"):
                level = worst(level, FAIL)
                problems.append(xnote)
            elif xnote:
                details.append("  text       " + xnote)
        else:
            details.append("  text       no plot to compare against "
                           "(--no-render, or no kicad-cli), so the letterforms "
                           "are modelled but NOT confirmed against KiCad")

    for layer in sorted(narrowest):
        w, desc = narrowest[layer]
        floor, cls, prov = _floor_for(layer, pal)
        tag = f"  {layer:<10} narrowest {w:.4f} mm  [{desc}]"
        if floor is None:
            details.append(tag + "  (no fabrication floor for this layer)")
            continue
        mark = f"{floor:.4f} mm{' PROVISIONAL' if prov else ''}"
        if w < floor - 1e-9:
            level = worst(level, _severity(cls, pal))
            problems.append(f"BELOW FLOOR: {layer} {w:.4f} mm < {mark} ({cls}) "
                            f"-- {desc}; this may vanish at fab")
        else:
            details.append(tag + f"  (floor {mark})")

    for layer in sorted(openings):
        w, desc = openings[layer]
        dam = pal.floors["mask"]
        details.append(
            f"  {layer:<10} narrowest OPENING {w:.4f} mm  [{desc}]  -- NOT "
            f"JUDGED against a floor: the {dam:.4f} mm mask number is a DAM "
            f"limit, the web of mask left BETWEEN two openings. That is a gap, "
            f"and the clearance check applies it. Holding an aperture width up "
            f"against it answers a different question. No profile in "
            f"tools/fab_profiles.py publishes a minimum mask OPENING, so there "
            f"is no floor here to compare with")
        if w < dam - 1e-9:
            # Not a floor violation -- there is no floor. But the dam limit is
            # the finest mask feature the process publishes ANYWHERE, so an
            # opening below it is outside everything the fab has stated, and
            # "unstated" must not read the same as "fine". Reported at SKIP,
            # which is this harness's word for "nothing confirmed this".
            level = worst(level, SKIP)
            problems.append(
                f"OPENING OUTSIDE THE PUBLISHED ENVELOPE: {layer} narrowest "
                f"opening {w:.4f} mm is finer than the {dam:.4f} mm mask dam, "
                f"which is the finest mask feature this process publishes at "
                f"all. That is NOT a floor violation -- no fabricator states a "
                f"minimum opening -- but nothing here can say this images "
                f"either. Ask them before ordering")

    details += no_ink
    for layer in sorted(unmeasured):
        why = unmeasured[layer]
        level = worst(level, SKIP)
        problems.append(f"NOT MEASURED: {layer} has {len(why)} item(s) whose "
                        f"geometry could not be derived, so the narrowest "
                        f"feature on this layer is UNKNOWN -- which is not the "
                        f"same as clean: " + "; ".join(why[:3])
                        + (f" (+{len(why)-3} more)" if len(why) > 3 else ""))

    # Text height is a legibility floor separate from stroke width. Aggregated
    # per layer: a ladder of small labels would otherwise bury everything else.
    small_text: dict[str, list] = {}
    for i, it in enumerate(fp.items):
        if (it.kind not in ("fp_text", "fp_text_box", "property")
                or it.char_h <= 0 or it.hidden):
            continue        # hidden text is not plotted, so it is not illegible
        for layer in it.layers:
            c = layer_class(layer)
            lim = CHAR_H_SILK if c == "silk" else (CHAR_H_COPPER if c == "copper"
                                                   else None)
            if lim and it.char_h < lim - 1e-9:
                rec = small_text.setdefault(layer, [lim, it.char_h, 0, it.text])
                rec[2] += 1
                if it.char_h < rec[1]:
                    rec[1], rec[3] = it.char_h, it.text
    for layer, (lim, smallest, n, sample) in sorted(small_text.items()):
        level = worst(level, WARN)
        problems.append(f"TEXT TOO SMALL: {layer} {n} string(s) below the "
                        f"{lim:.2f} mm legibility floor, smallest "
                        f"{smallest:.2f} mm -- e.g. {sample[:24]!r}")

    # Edge.Cuts: the feature is the routed slot width and the corner radius.
    edge_judged = 0
    edge_items = [it for it in fp.items if "Edge.Cuts" in it.layers]
    if edge_items:
        loops = closed_loops([it for it in edge_items if it.kind == "fp_line"])
        for it in edge_items:
            if it.kind in ("fp_poly", "fp_rect") and len(it.pts) >= 3:
                loops.append(it.pts)
        if not loops:
            details.append("  Edge.Cuts  present but no closed loop found -- slot "
                           "width NOT checked (open outline?)")
            level = worst(level, WARN)
        for k, loop in enumerate(loops):
            edge_judged += 1
            w = min_width(loop)
            if w < pal.floors["edge"] - 1e-9:
                level = worst(level, WARN)
                problems.append(f"UNROUTABLE: Edge.Cuts loop {k} is {w:.3f} mm "
                                f"across, under the {pal.floors['edge']:.2f} mm "
                                f"minimum slot width (= router bit diameter)")
            else:
                details.append(f"  Edge.Cuts  loop {k} min width {w:.3f} mm "
                               f"(floor {pal.floors['edge']:.2f} mm)")
            sharp = _sharp_corners(loop)
            if sharp:
                level = worst(level, WARN)
                problems.append(f"SHARP CORNER: Edge.Cuts loop {k} has {sharp} "
                                f"corner(s) turning >{180-EDGE_SHARP_CORNER_DEG:.0f} "
                                f"deg -- an internal corner cannot be cut sharper "
                                f"than the bit radius (0.8-1.0 mm) and the fab will "
                                f"fillet it")

    if concave_caveat:
        details.append("  note: min width uses the convex hull, so concave "
                       "polygons are UNDER-reported (never over-reported)")
    if pal.buried_provisional and any(layer_class(l) == "buried" for l in narrowest):
        details.append(f"  note: the buried-tone floor ({pal.floors['buried']:.2f} mm) "
                       f"is PROVISIONAL -- docs/pcb-palette.md gives no number and "
                       f"cal_buried exists to measure it. Override --floor-buried.")

    # A check that judged nothing must not report as one that judged everything.
    # `openings` and Edge.Cuts loops are reported, not compared, so they do not
    # count as a floor having been exercised.
    judged = len(narrowest) + edge_judged
    if level != PASS:
        head = f"{len(problems)} fabrication risk(s)"
    elif judged:
        head = f"all features above floor ({judged} layer(s) judged)"
    else:
        level = SKIP
        head = ("NO FLOOR WAS EXERCISED -- no layer here has a feature width to "
                "compare against a limit")
    return Check("min-feature", level, head, details + problems)


def _sharp_corners(loop) -> int:
    n = len(loop)
    if n < 3:
        return 0
    count = 0
    for i in range(n):
        a, b, c = loop[(i - 1) % n], loop[i], loop[(i + 1) % n]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cosang = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cosang)) < 180 - EDGE_SHARP_CORNER_DEG:
            count += 1
    return count


# --- 7. clearance / mask dams ----------------------------------------------

# How precisely the expanded letterforms are known, in mm. GLYPH_PATHS is
# stored to 1e-6 em and the advances to 1e-5 em, and the advances accumulate
# along a string, so a placed stroke sits within about a tenth of a micron of
# where KiCad puts it -- measured, on the largest part in this repo: 14,461 of
# 14,461 plotted segments matched to a worst deviation of 0.000071 mm.
#
# A gap that misses a floor by LESS than this is not a finding, it is the model
# reading its own rounding. Without it a coupon whose silk gap is exactly
# 0.150000 mm by construction reports 0.149999 mm and a violation of 1.2
# NANOMETRES, which is how a real finding gets lost in a list of noise.
TEXT_MODEL_EPS_MM = 1e-4


@dataclass
class Feat:
    """One thing on a layer that other things have to keep away from."""
    label: str
    edges: list                      # edges_bb_of(...) output
    width: float                     # stroke width; 0 for a filled outline
    bb: tuple                        # bbox ALREADY inflated by width/2
    from_text: bool = False          # expanded letterform, not drawn geometry


CIRCLE_SEGMENTS = 64


def _circle_pts(cx, cy, r, n=CIRCLE_SEGMENTS):
    """A CIRCUMSCRIBED polygon, deliberately.

    An inscribed polygon sits inside the real circle, which would make the ink
    smaller and every gap around it LARGER than it is. Erring in that direction
    hides violations; erring the other way at worst reports one that is not
    quite there, so the polygon is pushed out to touch the circle at its edge
    midpoints instead of at its vertices.
    """
    rr = r / math.cos(math.pi / n)
    return [(cx + rr * math.cos(2 * math.pi * k / n),
             cy + rr * math.sin(2 * math.pi * k / n)) for k in range(n)]


def clearance_features(fp: Footprint, cfg):
    """Everything on every layer that the gap check can compare, plus a list of
    everything it CANNOT -- because silently dropping an item is exactly how an
    fp_text ended up outside this check for the whole life of the tool.
    """
    from collections import defaultdict
    by_layer = defaultdict(list)
    excluded = defaultdict(list)
    expanded = [0, 0]                # text items, stroke paths

    def add(layer, label, pts, width, closed, from_text=False):
        b = bbox_of(pts)
        if b is None:
            return
        if width:
            b = bbox_inflate(b, width / 2.0)
        by_layer[layer].append(Feat(label, edges_bb_of(pts, closed), width, b,
                                    from_text))

    for i, it in enumerate(fp.items):
        for l in it.layers:
            if layer_class(l) not in ("silk", "mask", "copper", "buried"):
                continue
            if it.kind == "fp_line":
                add(l, f"fp_line #{i}", it.pts, it.width, False)
            elif it.kind in ("fp_poly", "fp_rect"):
                add(l, f"{it.kind} #{i}", it.pts, it.width, True)
            elif it.kind == "fp_circle":
                # Item stashes the radius in char_h; pts are the bbox corners.
                cx = (it.pts[0][0] + it.pts[2][0]) / 2.0
                cy = (it.pts[0][1] + it.pts[2][1]) / 2.0
                add(l, f"fp_circle #{i}", _circle_pts(cx, cy, it.char_h),
                    0.0 if it.filled else it.width, True)
            elif it.kind in ("fp_text", "fp_text_box", "property"):
                if it.hidden:
                    continue        # never plotted, so never fabricated
                ink = expand_text(it)
                if not ink.ok:
                    excluded[l].append(f"{it.kind} #{i} {it.text[:14]!r}: "
                                       f"{ink.why}")
                    continue
                if not ink.chains:
                    continue                      # whitespace: genuinely no ink
                expanded[0] += 1
                # One feature per stroke PATH, not per string and not per
                # character. Per string would hide the gap between an 'r' and
                # the 't' beside it; per character would hide the gap between
                # the stem of an 'i' and its own tittle, which is 109 of the
                # sub-floor pairs in the part that prompted all this. Paths of
                # one glyph that genuinely touch come back with a gap of zero
                # and are dropped below as one feature, which is what they are.
                for k, ch in enumerate(ink.chains):
                    expanded[1] += 1
                    add(l, f"{it.kind} #{i} stroke {k} ({it.text[:10]!r})",
                        ch, ink.width, False, from_text=True)
            else:
                excluded[l].append(f"{it.kind} #{i}: this shape is not modelled "
                                   f"by the gap check")
    return by_layer, excluded, expanded


def _candidate_pairs(feats: list[Feat], reach: float, max_span=16):
    """Index pairs whose (already pen-inflated) bboxes come within `reach`.

    A uniform grid, not the x-sweep this used to be. Microprinted text turns
    one fp_text into thousands of tiny features stacked in rows at similar x,
    and an x-sweep compares every glyph against every glyph of every row --
    quadratic in the number of ROWS for no benefit. The grid keeps the work
    proportional to the number of actual neighbours.

    A feature far larger than the cell (a background polygon) would be inserted
    into thousands of cells, so anything spanning more than `max_span` cells is
    held out and compared against everything. There are never many of those.
    """
    n = len(feats)
    if n < 2:
        return
    sizes = sorted(max(f.bb[2] - f.bb[0], f.bb[3] - f.bb[1]) for f in feats)
    cell = max(sizes[n // 2], reach * 2.0, 1e-6)

    from collections import defaultdict
    grid = defaultdict(list)
    bigset = set()
    for i, f in enumerate(feats):
        gx0, gy0 = int(math.floor(f.bb[0] / cell)), int(math.floor(f.bb[1] / cell))
        gx1, gy1 = int(math.floor(f.bb[2] / cell)), int(math.floor(f.bb[3] / cell))
        if (gx1 - gx0 + 1) * (gy1 - gy0 + 1) > max_span:
            bigset.add(i)
            continue
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                grid[(gx, gy)].append(i)

    for i, f in enumerate(feats):
        if i in bigset:
            continue
        seen = set()
        gx0 = int(math.floor((f.bb[0] - reach) / cell))
        gy0 = int(math.floor((f.bb[1] - reach) / cell))
        gx1 = int(math.floor((f.bb[2] + reach) / cell))
        gy1 = int(math.floor((f.bb[3] + reach) / cell))
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                for j in grid.get((gx, gy), ()):
                    if j > i and j not in seen:
                        seen.add(j)
                        yield i, j
    # Anything too big for the grid is compared against everything, once.
    for i in sorted(bigset):
        for j in range(n):
            if j == i or (j in bigset and j < i):
                continue
            yield (i, j) if i < j else (j, i)


GAP_MARGIN_REACH = 2.0
GAP_MARGIN_BUDGET = 2_000_000


def _narrowest_separated_gap(feats: list, reach: float, budget: int):
    """The narrowest real gap on a layer, looking PAST the floor. -> (mm, desc).

    The judging pass only searches out to the floor, because that is all a
    verdict needs. The consequence is that a part which comfortably clears its
    floor produces no measured number at all, and the check can only say "all
    gaps >= floor" -- the same sentence it would print for a part sitting
    exactly ON the floor with nothing to spare. Those are very different parts
    and the report should not render them identically.

    So this walks the same geometry with a wider search radius purely to put a
    number and a margin on the report. It CANNOT change a verdict: it is called
    only where the judging pass already reached one, it compares nothing to a
    floor, and it has its own budget so that a part large enough to make the
    wider search expensive gives up and reports nothing rather than slowing the
    run or timing out. (None, "") means "not measured", never "no gap".
    """
    best, desc, ops = None, "", 0
    r2 = reach * reach
    for a, b in _candidate_pairs(feats, reach):
        fa, fb = feats[a], feats[b]
        ba, bb = fa.bb, fb.bb
        dx = max(0.0, ba[0] - bb[2], bb[0] - ba[2])
        dy = max(0.0, ba[1] - bb[3], bb[1] - ba[3])
        if dx * dx + dy * dy >= r2:
            continue
        ops += len(fa.edges) * len(fb.edges)
        if ops > budget:
            return None, ""
        g = _feature_gap(fa.edges, fb.edges, fa.width, fb.width,
                         reach + (fa.width + fb.width) / 2.0)
        if g is None or g <= 1e-9:
            continue          # touching: one feature, not a gap
        if best is None or g < best:
            best, desc = g, f"{fa.label} vs {fb.label}"
    return best, desc


def check_clearance(fp: Footprint, cfg) -> Check:
    """Gaps between separate features on the same layer.

    docs/pcb-palette.md: mask left between adjacent openings must stay above
    ~0.1 mm 'or it washes away in processing', collapsing a hatch into one flat
    opening. Same logic bounds silk gaps (knockout: 'ink bleeds inward and can
    close a fine gap'). On copper the number is the same one the width check
    uses: FabProfile.min_copper_mm is minimum trace width AND SPACING, and only
    the width half of that sentence used to be implemented.

    Text participates. It has to: a microprinted string is thousands of copper
    features a tenth of a millimetre apart, and it was the only kind of item
    this check could not see.
    """
    if not cfg.clearance:
        return Check("clearance", SKIP, "skipped (--no-clearance)")

    by_layer, excluded, expanded = clearance_features(fp, cfg)

    details, problems = [], []
    level = PASS
    n_skipped = 0
    n_tested_layers = 0
    n_untested_layers = 0
    total_pairs = 0

    if expanded[0]:
        details.append(f"  text       {expanded[0]} text item(s) expanded into "
                       f"{expanded[1]} stroke path(s), each one a feature in "
                       f"the comparison below")

    for layer in sorted(by_layer):
        feats = by_layer[layer]
        floor, cls, prov = _floor_for(layer, cfg.palette)
        if floor is None:
            continue
        n = len(feats)
        n_possible = n * (n - 1) // 2
        if n_possible == 0:
            # THE VACUOUS PASS. One feature forms no pairs, so the floor was
            # never applied to anything -- and "all gaps >= 0.200 mm" over zero
            # gaps reads exactly like a check that ran. It did not.
            n_untested_layers += 1
            details.append(f"  {layer:<10} {n} feature(s) -> 0 pairs. NOT "
                           f"TESTED: a gap needs two features, so the "
                           f"{floor:.4f} mm {cls} limit was not applied to "
                           f"anything on this layer")
            continue
        if n > cfg.max_clearance_items:
            level = worst(level, WARN)
            n_skipped += 1
            details.append(f"  {layer:<10} {n} features -- OVER the "
                           f"{cfg.max_clearance_items} limit, gap check NOT RUN "
                           f"(raise --max-clearance-items). These gaps are "
                           f"UNCHECKED, not clean.")
            continue

        f2 = floor * floor
        worst_gap, worst_desc, n_bad = None, "", 0
        ops, incomplete, n_close, n_merged, n_pairs = 0, False, 0, 0, 0
        # The narrowest SEPARATED gap on this layer whether or not it is legal.
        # Reporting only the sub-floor worst is how "PASS: all gaps >= 0.0889 mm"
        # got written about a part whose tightest gap was 0.0889 mm exactly --
        # true, and indistinguishable from a part with a comfortable margin. A
        # design sitting on the floor is a design with no margin for etch
        # variation, and the reader cannot see that from a verdict alone.
        tight_gap, tight_desc = None, ""

        for a, b in _candidate_pairs(feats, floor):
            fa, fb = feats[a], feats[b]
            ba, bb = fa.bb, fb.bb
            dx = max(0.0, ba[0] - bb[2], bb[0] - ba[2])
            dy = max(0.0, ba[1] - bb[3], bb[1] - ba[3])
            n_pairs += 1
            if dx * dx + dy * dy >= f2:
                continue      # pen-inflated bboxes are already further apart
            ops += len(fa.edges) * len(fb.edges)
            if ops > cfg.clearance_budget:
                incomplete = True
                break
            n_close += 1
            g = _feature_gap(fa.edges, fb.edges, fa.width, fb.width,
                             floor + (fa.width + fb.width) / 2.0)
            if g is None or g <= 1e-9:
                n_merged += 1
                continue      # touching/merged: one feature, not a dam
            if tight_gap is None or g < tight_gap:
                tight_gap = g
                tight_desc = f"{fa.label} vs {fb.label}"
            eps = (TEXT_MODEL_EPS_MM if (fa.from_text or fb.from_text)
                   else 1e-9)
            if g < floor - eps:
                n_bad += 1
                if worst_gap is None or g < worst_gap:
                    worst_gap = g
                    worst_desc = f"{fa.label} vs {fb.label}"

        total_pairs += n_pairs
        if incomplete:
            level = worst(level, WARN)
            n_skipped += 1
            details.append(f"  {layer:<10} gap check INCOMPLETE -- exhausted the "
                           f"{cfg.clearance_budget:,}-operation budget with "
                           f"{n} features. Remaining gaps are UNCHECKED "
                           f"(raise --clearance-budget).")
        else:
            n_tested_layers += 1
        if n_bad:
            level = worst(level, _severity(cls, cfg.palette))
            problems.append(f"GAP BELOW FLOOR: {layer} narrowest gap "
                            f"{worst_gap:.6f} mm < {floor:.4f} mm"
                            f"{' PROVISIONAL' if prov else ''} ({cls}) in {n_bad} "
                            f"of {n_close - n_merged} separated pair(s), worst "
                            f"{worst_desc}"
                            + {"mask": " -- mask dams this thin wash away and "
                                       "the openings merge",
                               "silk": " -- silk ink bleeds inward and closes a "
                                       "gap this fine (docs/pcb-palette.md: a "
                                       "silk gap is at least as hard to hold as "
                                       "a silk line)",
                               }.get(cls, " -- the etchant cannot clear a gap "
                                          "this fine and the features bridge"))
        elif not incomplete:
            # State the margin, not just the verdict. `tight_gap` is the
            # narrowest gap among the pairs that came within the floor of each
            # other; if nothing did, there is no measured number to quote and
            # saying so is better than quoting the floor back.
            if tight_gap is None:
                tight_gap, tight_desc = _narrowest_separated_gap(
                    feats, floor * GAP_MARGIN_REACH, GAP_MARGIN_BUDGET)
            if tight_gap is None:
                margin = (f"all gaps >= {floor:.4f} mm -- and no separated pair "
                          f"was found within {GAP_MARGIN_REACH:g}x the floor, so "
                          f"the narrowest gap is NOT MEASURED here; it is "
                          f"further out than this check looked")
            else:
                over = tight_gap - floor
                margin = (f"narrowest gap {tight_gap:.6f} mm vs the "
                          f"{floor:.4f} mm floor: +{over:.6f} mm "
                          f"({over / floor * 100:.1f}%) [{tight_desc}]")
                if over <= TEXT_MODEL_EPS_MM:
                    margin += (" -- ON THE FLOOR: this margin is inside the "
                               f"{TEXT_MODEL_EPS_MM:g} mm precision of the "
                               "geometry model itself, so it is a pass with "
                               "no headroom, not a clean pass")
            details.append(f"  {layer:<10} {n} features, {n_pairs} pair(s) "
                           f"compared ({n_close} close enough to measure, "
                           f"{n_merged} touching), " + margin)

    for layer in sorted(excluded):
        if layer_class(layer) not in ("silk", "mask", "copper", "buried"):
            continue
        why = excluded[layer]
        level = worst(level, SKIP)
        problems.append(f"NOT COMPARED: {layer} has {len(why)} item(s) the gap "
                        f"check cannot represent, so any gap involving them is "
                        f"UNCHECKED rather than clean: " + "; ".join(why[:3])
                        + (f" (+{len(why)-3} more)" if len(why) > 3 else ""))

    counter_problems, n_counters = _counter_problems(fp, cfg, details)
    problems += counter_problems
    if counter_problems:
        level = worst(level, _severity("copper", cfg.palette))

    if n_tested_layers == 0 and n_counters == 0 and level == PASS:
        level = SKIP
        head = ("NOTHING TESTED -- no layer here has two features to form a "
                "gap between")
    elif level == PASS:
        head = (f"all gaps above floor ({total_pairs} pair(s) over "
                f"{n_tested_layers} layer(s)"
                + (f", {n_counters} glyph counter(s)" if n_counters else "")
                + (f"; {n_untested_layers} layer(s) had nothing to compare"
                   if n_untested_layers else "") + ")")
    elif problems and n_skipped:
        head = (f"{len(problems)} clearance problem(s), "
                f"{n_skipped} layer(s) not fully checked")
    elif problems:
        head = f"{len(problems)} clearance problem(s)"
    else:
        head = f"{n_skipped} layer(s) NOT FULLY CHECKED -- see details"
    return Check("clearance", level, head, details + problems)


def _counter_problems(fp: Footprint, cfg, details: list) -> tuple[list[str], int]:
    """Copper-to-copper clearance INSIDE a glyph: the counter of an 'e'.

    An enclosed void is bounded by the same stroke on all sides, so it is one
    connected feature and the pairwise gap test above cannot see it -- the two
    sides of the bowl are the same path. The void width is a measured property
    of the letterform instead: stroke_font measures the largest circle that
    fits in each glyph's tightest enclosed void, at zero pen, and ink centred
    on the centreline eats half the pen from each side, so

        clear = 2 * D * cap - stroke

    Below the floor the counter fills in and the glyph images as a blob.
    """
    sf = _stroke_font()
    if sf is None:
        return [], 0
    worst_by_layer: dict[str, tuple[float, str, float]] = {}
    for it in fp.items:
        if it.kind not in ("fp_text", "fp_text_box", "property"):
            continue
        ink = expand_text(it)
        if not ink.ok or not ink.counters:
            continue
        for layer in it.layers:
            if layer_class(layer) not in ("silk", "copper", "buried"):
                continue
            for ch, d_em in ink.counters.items():
                clear = 2.0 * d_em * it.char_h - it.thickness
                cur = worst_by_layer.get(layer)
                if cur is None or clear < cur[0]:
                    worst_by_layer[layer] = (clear, ch, d_em)
    out, n_judged = [], 0
    for layer in sorted(worst_by_layer):
        clear, ch, d_em = worst_by_layer[layer]
        floor, cls, _ = _floor_for(layer, cfg.palette)
        if floor is None:
            continue
        n_judged += 1
        if clear < floor - TEXT_MODEL_EPS_MM:
            out.append(f"COUNTER TOO TIGHT: {layer} the enclosed void of {ch!r} "
                       f"clears {clear:.6f} mm < {floor:.4f} mm ({cls}) -- "
                       f"2*{d_em:.5f} em * cap - stroke; this letterform fills "
                       f"in solid")
        else:
            details.append(f"  {layer:<10} tightest glyph counter {ch!r} clears "
                           f"{clear:.6f} mm (floor {floor:.4f} mm)")
    return out, n_judged


def edges_bb_of(pts, closed=True):
    """Edges as (p1, p2, x0, y0, x1, y1) so the gap test can reject a pair on
    bounding boxes before paying for a segment-distance computation."""
    out = []
    for (a, b) in edges_of(pts, closed):
        out.append((a, b,
                    a[0] if a[0] < b[0] else b[0], a[1] if a[1] < b[1] else b[1],
                    a[0] if a[0] > b[0] else b[0], a[1] if a[1] > b[1] else b[1]))
    return out


def _feature_gap(ea, eb, wa: float, wb: float, cutoff: float):
    """Edge-to-edge distance between two features, accounting for stroke width
    (a line is a capsule, not a zero-width segment).

    Only distances below `cutoff` matter, so `best` starts there and every edge
    pair further apart than the running best is rejected on bboxes alone. On
    the April pipeline's thousand-vertex polygons this is the difference
    between seconds and minutes.
    """
    if not ea or not eb:
        return None
    best = cutoff
    for (p1, p2, ax0, ay0, ax1, ay1) in ea:
        for (p3, p4, bx0, by0, bx1, by1) in eb:
            dx = bx0 - ax1 if bx0 > ax1 else (ax0 - bx1 if ax0 > bx1 else 0.0)
            dy = by0 - ay1 if by0 > ay1 else (ay0 - by1 if ay0 > by1 else 0.0)
            if dx >= best or dy >= best or dx * dx + dy * dy >= best * best:
                continue
            d = seg_seg_dist(p1, p2, p3, p4)
            if d < best:
                best = d
                if best <= 0:
                    break
        if best <= 0:
            break
    return max(0.0, best - wa / 2.0 - wb / 2.0)


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def apply_fab(palette: Palette, key: str) -> list[str]:
    """Overwrite a palette's fabrication floors from a named process.

    Mutates `palette` and returns the lines describing what moved.

    Only numbers the fab actually publishes are taken, and only onto the floor
    they describe:

      copper  <- min_copper_mm. Trace width and spacing, stated by every profile.
      silk    <- min_silk_mm, where stated. OSH Park publishes none.
      mask    <- min_mask_dam_mm, the web BETWEEN two openings, which is what
                 the gap check measures. No profile publishes a minimum opening
                 WIDTH, so nothing here infers one from the copper number: that
                 would loosen a check using a limit quoted for a different
                 process step, which is how a part ends up sized against a
                 figure nobody sells.
      buried  untouched. No profile publishes a buried-layer limit, and
                 FabProfile.floor_for() would hand back the outer-layer etch
                 number -- finer than the doc's provisional 0.50, so taking it
                 would loosen the one floor already flagged as a guess.
      edge    untouched. That is the router's bit diameter, not an imaging limit.
    """
    prof = fab_profiles.PROFILES[key]
    out = [f"fab: {prof.name} [{key}] -- {prof.source}"]
    if prof.surcharge:
        out.append(f"fab: SURCHARGE {prof.surcharge}")
    for cls, val, what in (("copper", prof.min_copper_mm, "trace width/spacing"),
                           ("silk", prof.min_silk_mm, "silkscreen stroke"),
                           ("mask", prof.min_mask_dam_mm, "mask dam")):
        if val is None:
            out.append(f"fab: {prof.name} publishes no {what} -- keeping the "
                       f"palette's {palette.floors[cls]:.3f} mm, which is NOT "
                       f"this fab's number. Ask them before ordering.")
            continue
        was = palette.floors[cls]
        palette.floors[cls] = val
        palette.hard.add(cls)
        if abs(was - val) > 1e-9:
            out.append(f"fab: {cls} floor {was:.4f} -> {val:.4f} mm ({what}; "
                       f"{'tighter' if val > was else 'looser'} than the doc)")
    return out


def verify_file(path: Path, cfg) -> tuple[str, list[Check]]:
    checks: list[Check] = []
    try:
        fp = load_footprint(path)
    except (ParseError, OSError) as e:
        return FAIL, [Check("parse", FAIL, f"cannot read as a footprint: {e}")]

    checks.append(Check("info", INFO,
                        f'"{fp.name}"  version={fp.version}  '
                        f'generator={fp.generator}  items={len(fp.items)}'))

    # THE FLOOR COMES FROM THE PART.
    #
    # A part sized against a vendor process and checked against the palette
    # doc's generic floor is a part that can emit cleanly and then fail its own
    # acceptance run -- or, worse, pass it while being finer than anything the
    # fab sells. tools/microtext.py stamps the process it sized for into the
    # footprint's tags, and this reads it back, so the two halves resolve the
    # same number without anybody having to remember to type it twice.
    #
    # cfg.palette is never mutated: each file gets its own copy, because a
    # directory can hold parts built for different processes and the second
    # file must not inherit the first one's floors.
    cfg = copy.copy(cfg)
    cfg.palette = replace(cfg.palette, floors=dict(cfg.palette.floors),
                          notes=list(cfg.palette.notes),
                          hard=set(cfg.palette.hard))
    cfg.render_svg = None
    try:
        tagged = fab_profiles.from_tags(fp.tags)
    except ValueError as e:
        return FAIL, checks + [Check("fab", FAIL, f"unusable fab tag: {e}")]

    want = getattr(cfg, "fab", None)
    key, why = None, None
    if tagged and want and tagged[0] != want:
        return FAIL, checks + [Check(
            "fab", FAIL,
            f"--fab {want} contradicts the part",
            [f"this footprint is tagged {fab_profiles.tag_for(tagged[0])}, i.e. "
             f"it was SIZED for {tagged[1].name}.",
             f"Checking it against {fab_profiles.PROFILES[want].name} would "
             f"test it against a process it was not built for, and whichever "
             f"answer came back would be about the wrong board.",
             "Re-emit the part for the process you mean, or drop --fab and let "
             "the part speak for itself."])]
    if tagged:
        key, why = tagged[0], "read from the footprint's own tags"
    elif want:
        key, why = want, ("--fab on the command line; this part carries no "
                          "fab tag, so nothing in the file corroborates it")

    if key:
        lines = apply_fab(cfg.palette, key)
        checks.append(Check("fab", INFO, f"floors from {key} ({why})", lines))
    checks.append(check_kicad_load(path, cfg))
    checks.append(check_size(path, fp, cfg))
    checks.append(check_geometry(fp, cfg))
    checks.append(check_layers(fp, cfg))
    checks.append(check_self_intersection(fp, cfg))
    checks.append(check_min_feature(fp, cfg))
    checks.append(check_clearance(fp, cfg))

    lv = PASS
    for c in checks:
        eff = c.level
        if cfg.strict and eff in (WARN, SKIP):
            eff = FAIL
        lv = worst(lv, eff)
    verdict = FAIL if lv == FAIL else (WARN if lv in (WARN, SKIP) else PASS)
    return verdict, checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Acceptance harness for generated KiCad art footprints.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help=".kicad_mod files (or directories)")
    ap.add_argument("--palette", default=None,
                    help="path to pcb-palette.md (default: ../docs/pcb-palette.md)")
    ap.add_argument("--kicad-cli", default=None, help="path to kicad-cli")
    ap.add_argument("--side", choices=("front", "back", "both"), default="front",
                    help="which side the art lives on (default front)")
    ap.add_argument("--allow-layer", action="append", default=[],
                    metavar="LAYER", help="treat LAYER as on-palette (repeatable)")
    ap.add_argument("--strict", action="store_true",
                    help="treat WARN and SKIP as failures")
    ap.add_argument("--no-render", action="store_true",
                    help="skip the fp export svg plot check (faster)")
    ap.add_argument("--no-clearance", action="store_true",
                    help="skip the gap / mask-dam check")
    ap.add_argument("--warn-bytes", type=int, default=WARN_BYTES)
    ap.add_argument("--fail-bytes", type=int, default=FAIL_BYTES)
    ap.add_argument("--floor-buried", type=float, default=None,
                    help=f"buried-tone min feature, mm (default {FLOOR_BURIED} "
                         f"PROVISIONAL)")
    ap.add_argument("--fab", default=None, choices=sorted(fab_profiles.PROFILES),
                    metavar="PROFILE",
                    help="check copper/mask/silk against a named process from "
                         "tools/fab_profiles.py instead of the palette doc: " +
                         ", ".join(sorted(fab_profiles.PROFILES)) +
                         ". Usually unnecessary -- a part emitted with "
                         "--microtext-fab carries its process in its tags and "
                         "is checked against it automatically. Refused if it "
                         "contradicts what the part says")
    ap.add_argument("--outlier-mm", type=float, default=OUTLIER_MM)
    ap.add_argument("--max-poly-pts", type=int, default=2000,
                    help="skip self-intersection above this vertex count")
    ap.add_argument("--max-clearance-items", type=int, default=100_000,
                    help="skip the gap check on a layer with more features. "
                         "Was 4000, which predates text expansion: one page of "
                         "microprint is thousands of copper features, and a "
                         "limit that turns the check off on exactly the parts "
                         "that need it is a limit that hides defects. The "
                         "spatial index made item count cheap; "
                         "--clearance-budget is the real guard")
    ap.add_argument("--clearance-budget", type=int, default=4_000_000,
                    help="max edge-comparison operations per layer in the gap "
                         "check before it reports itself INCOMPLETE")
    ap.add_argument("--max-report", type=int, default=8,
                    help="max individual problems listed per check")
    ap.add_argument("--quiet", action="store_true",
                    help="only print the per-file verdict line and the summary")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="emit machine-readable JSON instead of text")
    a = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    doc = Path(a.palette) if a.palette else here.parent / "docs" / "pcb-palette.md"
    palette = load_palette(doc, a.side)
    if a.floor_buried is not None:
        palette.floors["buried"] = a.floor_buried
        palette.buried_provisional = False

    choice = find_kicad_cli(a.kicad_cli)
    cli, kver = choice.path, choice.version

    class Cfg:
        pass
    cfg = Cfg()
    cfg.cli, cfg.kicad_version, cfg.cli_major = cli, kver, choice.major
    cfg.palette, cfg.side = palette, a.side
    cfg.fab = a.fab
    cfg.allow_layers = set(a.allow_layer)
    cfg.strict = a.strict
    cfg.render = not a.no_render
    cfg.clearance = not a.no_clearance
    cfg.warn_bytes, cfg.fail_bytes = a.warn_bytes, a.fail_bytes
    cfg.outlier_mm = a.outlier_mm
    cfg.max_poly_pts = a.max_poly_pts
    cfg.max_clearance_items = a.max_clearance_items
    cfg.clearance_budget = a.clearance_budget
    cfg.max_report = a.max_report

    targets: list[Path] = []
    for f in a.files:
        p = Path(f)
        if p.is_dir():
            targets += sorted(p.glob("*.kicad_mod"))
        else:
            targets.append(p)
    targets = [t for t in targets if t.suffix == ".kicad_mod" or t.is_file()]
    if not targets:
        print("verify_art: no .kicad_mod files given", file=sys.stderr)
        return 2

    if not a.as_json:
        print(f"verify_art -- {len(targets)} file(s)")
        print(f"  palette : {palette.source}")
        print(f"  kicad   : {cli or 'NOT FOUND'}"
              + (f"  ({kver})" if cli else ""))
        if cli and choice.major < MIN_KICAD_MAJOR:
            print(f"  ! this kicad-cli is older than {MIN_KICAD_MAJOR}; the load "
                  f"check will be SKIPPED, not passed")
        for r in choice.rejected:
            print(f"  - ignored older/unusable kicad-cli: {r}")
        print(f"  floors  : silk {palette.floors['silk']:.3f}  "
              f"mask {palette.floors['mask']:.3f}  "
              f"copper {palette.floors['copper']:.3f}  "
              f"buried {palette.floors['buried']:.3f}"
              f"{'*PROVISIONAL' if palette.buried_provisional else ''}  "
              f"edge {palette.floors['edge']:.2f} mm")
        for n in palette.notes:
            print(f"  ! {n}")
        print()

    results = []
    for t in targets:
        verdict, checks = verify_file(t, cfg)
        results.append((t, verdict, checks))
        if a.as_json:
            continue
        print(f"=== {t.name}  ->  {verdict}")
        for c in checks:
            if c.key == "info":
                print(f"      {c.headline}")
                continue
            print(f"  [{c.level:<4}] {c.key:<12} {c.headline}")
            if not a.quiet:
                for d in c.details:
                    if d:
                        print(f"             {d}")
        print()

    n_fail = sum(1 for _, v, _ in results if v == FAIL)
    n_warn = sum(1 for _, v, _ in results if v == WARN)
    n_pass = sum(1 for _, v, _ in results if v == PASS)

    if a.as_json:
        print(json.dumps({
            "palette": palette.source,
            "kicad_cli": cli,
            "kicad_version": kver,
            "floors": palette.floors,
            "buried_floor_provisional": palette.buried_provisional,
            "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail,
                        "total": len(results)},
            "files": [{
                "path": str(t), "verdict": v,
                "checks": [{"key": c.key, "level": c.level,
                            "headline": c.headline, "details": c.details}
                           for c in cs],
            } for t, v, cs in results],
        }, indent=2))
    else:
        print("-" * 72)
        print(f"SUMMARY: {n_pass} pass, {n_warn} warn, {n_fail} fail "
              f"of {len(results)}")
        for t, v, _ in results:
            if v != PASS:
                print(f"  {v:<4} {t.name}")
        if n_fail:
            print("\nFAIL -- do not ship these.")
        elif n_warn:
            print("\nNo hard failures. Warnings above are fabrication risks, not "
                  "KiCad errors; review before shipping (--strict to enforce).")

    return 1 if n_fail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
