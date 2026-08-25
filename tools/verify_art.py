#!/usr/bin/env python3
"""Acceptance harness for generated art footprints AND for whole boards.

    python tools/verify_art.py <file.kicad_mod|file.kicad_pcb> [more...]

Answers one question per file: *would we ship this?* A footprint passes only if
KiCad 10 loads it, it fits the size budget, its geometry is well formed, it
draws only on layers the palette actually defines, and its features survive
fabrication.

BOARDS, AND THE HOLE THAT MADE THEM NECESSARY
---------------------------------------------
This tool read .kicad_mod and nothing else, through three independent gates:
main() globbed *.kicad_mod, load_footprint() demanded a (footprint ...) root,
and GRAPHIC_HEADS listed only fp_* items. A .kicad_pcb therefore had no route
to any check -- and a board is where the art actually ships. Two coupon boards
carried 981 board-level gr_poly between them, written by a script that never
went through emit_art's floor enforcement, and not one of them had ever been
compared to a fabrication floor by anything. 128 of 823 silk components were
under the 0.15 mm floor and six sub-floor gaps sat on the portfolio face.

A board is now read into the SAME Item objects a footprint is read into --
gr_poly becomes fp_poly, a track segment becomes fp_line, a via becomes a
filled circle with a hole, and a placed footprint is expanded into board
coordinates -- so every check below applies to a board unchanged. Three new
ones are board-only:

  8. ink-floor    -- the REGION measurement. See below; this is the one that
                     catches the defect.
  9. inventory    -- every node in the file classified measured / NOT
                     MEASURED, including heads this harness has never seen.
 10. project-rules -- whether the DRC guarding this board is even armed.

WHY A REGION MEASUREMENT AND NOT A BETTER PER-ITEM ONE
-------------------------------------------------------
Two of the checks below are structurally incapable of finding this defect and
would have gone green over it:

  * check_min_feature measures a filled polygon with min_width(), a rotating
    caliper on the CONVEX HULL. On a traced letterform that is the glyph's
    overall width, ~1.2 mm, while the stem the glyph is drawn with is 0.117 mm.
  * check_clearance compares ITEMS. A keyhole-bridged glyph is one polygon: its
    counter is bounded by the same ring as its outline, so the void inside it
    is intra-item and unreachable. All six sub-floor gaps on the alpha coupon's
    front face are of exactly that kind.

tools/ink_measure.py measures the ink as a REGION instead: the inscribed width
of the material, the real separation between boundary points wherever they lie,
and which whole components an opening at the floor deletes. On a board,
check_min_feature now REFUSES to report a concave filled area at all and says
so, rather than handing back a hull number that cannot fail.

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
  8. ink-floor    -- BOARDS ONLY. Inscribed width and real gaps measured on the
                     unioned ink of each layer, plus which components an
                     opening at the floor deletes. Needs shapely; without it
                     the check reports SKIP and says so. --no-ink.
  9. inventory    -- BOARDS ONLY. Every node head in the file, and what became
                     of it. A construct this harness does not model is named
                     here at SKIP rather than skipped in silence, because "a
                     class of object nothing knew about" is what the defect
                     was, not a wrong number.
 10. project-rules -- BOARDS ONLY. The sibling .kicad_pro's design rules
                     against the active floors. A rule set to 0.0 does not
                     default to something sensible, it switches the
                     corresponding DRC test off, and "DRC: 0 violations" on a
                     board like that tested nothing.

A SKIPPED CHECK CANNOT CONTRIBUTE TO A PASS
-------------------------------------------
The sentence at the bottom of this docstring used to read "a check that cannot
run is never reported as a pass". It was false, and it was false in the only
place that decides anything -- the summary and the exit code. Run under an
interpreter without shapely, the ink-floor check reported SKIP, and this
harness printed

    SUMMARY: 0 pass, 1 warn, 0 fail of 1
    No hard failures. Warnings above are fabrication risks ...

and exited 0, on a board it FAILs when shapely is present. Every check line was
honest; the verdict folded SKIP into WARN and WARN into "not a failure".

Coverage is now a SECOND AXIS, independent of level. Every place a check can
not happen -- a missing optional import, a missing kicad-cli, --no-ink /
--no-clearance / --no-render / --ink-layers, a layer whose items cannot be
turned into geometry, a budget exhausted part-way, a floor that is a guess
rather than a published number, a layer with too few features to form a pair --
records a Gap saying what was not measured, why, and HOW MUCH of the board that
was. A file with any Gap is INCOMPLETE, which is not a pass and cannot become
one, and the run exits 3 unless the caller passes --accept-gaps. See the
COVERAGE block below the level table.

"Not applicable" is not a gap: check_inventory on a footprint has nothing to
measure and records nothing.

Exit status: 0 = every file passed and every check ran, 1 = at least one FAIL,
2 = harness error, 3 = nothing failed but at least one check did not run (or
did not finish). WARNs do not fail the run unless --strict is given. A feature
or gap under a floor that came from a NAMED FABRICATOR is a FAIL, not a WARN:
the palette doc's numbers are house guidance, but a vendor's published limit is
what that process images, and art under it is missing from the delivered board.

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
it records what it did not measure and how much of the board that was, and the
run it belongs to cannot report a pass while it is there. A missing hard
dependency is announced at STARTUP, naming the interpreter that lacks it and
the one in this repo's .venv that does not.
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

# Sweep declarations: how a calibration ladder states, in the artefact, that it
# goes under the floor on purpose. Lives in the same `tags` field as the fab
# tag and is parsed with the same discipline -- malformed is FAIL, never
# ignored. See tools/sweep_decls.py for why every field is load-bearing.
import sweep_decls                                        # noqa: E402

# The region measurement. Optional on purpose: where it cannot be imported the
# board ink check reports NOT MEASURED at SKIP and says why. It never falls
# back to an estimate -- an estimated floor comparison is not a floor.
try:
    import ink_measure                                    # noqa: E402
except Exception as _ink_err:                             # pragma: no cover
    ink_measure = None
    _INK_IMPORT_ERR = f"{type(_ink_err).__name__}: {_ink_err}"
else:
    _INK_IMPORT_ERR = ""

# --------------------------------------------------------------------------
# Levels. Ordered so max() picks the worst.
# --------------------------------------------------------------------------

PASS, INFO, SKIP, WARN, FAIL = "PASS", "INFO", "SKIP", "WARN", "FAIL"
_RANK = {PASS: 0, INFO: 1, SKIP: 2, WARN: 3, FAIL: 4}


def worst(*levels: str) -> str:
    return max(levels, key=lambda x: _RANK[x], default=PASS)


# A FILE verdict only -- never a check level. See _verdict().
INCOMPLETE = "INCOMPLETE"


# --------------------------------------------------------------------------
# COVERAGE: the second axis, and why one axis was not enough
# --------------------------------------------------------------------------
#
# THE TWELFTH INSTANCE. This harness ran under an interpreter with no shapely,
# the ink-floor check reported SKIP, and the run summarised
#
#     SUMMARY: 0 pass, 1 warn, 0 fail of 1
#     No hard failures. Warnings above are fabrication risks ...
#
# and exited 0, on a board that the SAME harness on the SAME profile FAILs when
# shapely is present. Every individual line was honest -- check_ink() literally
# printed "this is not a pass" -- and the run still reported green, because the
# only thing a caller reads is the exit code and the last line.
#
# The root cause is that SEVERITY and COVERAGE were crammed onto one axis.
# `SKIP` sat between INFO and WARN in _RANK, so "nothing measured this" was
# folded into the same number as "this is a bit risky", and at the summary the
# fold became a lie: WARN means the harness looked and did not like what it
# saw, SKIP means the harness did not look. Those must never collapse.
#
# So coverage is now its own axis. A check reports, independently of its level:
#
#   * level  -- what it FOUND. Unchanged; PASS/WARN/FAIL still mean what they
#               meant, and a check that found nothing wrong still says PASS.
#   * gaps   -- what it did NOT MEASURE, and how much of the board that was.
#
# A Gap NEVER improves and never worsens `level`; it is not a finding. What it
# does is bind the run: a file with any gap cannot be reported as a pass, and a
# run with any gap exits non-zero unless the caller passes --accept-gaps. That
# is deliberately not something --strict already did: --strict is opt-in, and a
# defect class that has now recurred twelve times does not get to depend on
# somebody remembering a flag. Nor would --strict have been enough if somebody
# had remembered it: several of the holes below sit on checks whose LEVEL is
# PASS -- a layer holding one feature reports "all gaps above floor" over zero
# pairs, a --no-render run reports "loads in KiCad" without the plot
# cross-check -- and --strict only promotes WARN and SKIP.
#
# NOT APPLICABLE IS NOT A GAP. check_inventory on a footprint reports SKIP
# "not a board": there is nothing there to measure and no board went
# unmeasured. Sites like that carry NO Gap, and that is the whole distinction
# the old single axis could not express.

# What kind of hole this is. The wording of each is load-bearing in the report.
GAP_NOT_RUN = "did not run"        # the check never executed at all
GAP_INCOMPLETE = "incomplete"      # it started, ran out of budget, stopped
GAP_VACUOUS = "nothing to test"    # it ran over zero inputs; a floor unapplied
GAP_UNJUDGED = "no published limit"  # measured, but nothing to compare against


@dataclass
class Gap:
    """One thing this run did not measure, and how much of the board that was.

    `extent` is required in spirit even where it is empty in type: "the gap
    check was incomplete" is not actionable and "2,317,884 of 4,010,552
    candidate pairs on F.Cu were never compared" is. Requirement 4 of the task
    that produced this file is exactly that -- budget exhaustion is not a skip,
    it is an INCOMPLETE MEASUREMENT, and a measurement reports its extent.
    """
    check: str                  # which check has the hole
    scope: str                  # "whole check", or the layer / object it is on
    kind: str                   # one of the GAP_* constants above
    why: str                    # why it did not happen
    fix: str = ""               # what the caller does about it
    extent: str = ""            # HOW MUCH went unmeasured

    def line(self) -> str:
        s = f"{self.check} / {self.scope}: {self.kind.upper()} -- {self.why}"
        if self.extent:
            s += f"\n        UNMEASURED: {self.extent}"
        if self.fix:
            s += f"\n        FIX: {self.fix}"
        return s

    def as_dict(self) -> dict:
        return {"check": self.check, "scope": self.scope, "kind": self.kind,
                "why": self.why, "fix": self.fix, "extent": self.extent}


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
# Slack on that comparison, degrees. See _sharp_corners().
EDGE_CORNER_EPS_DEG = 0.01

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
    # Board context. A footprint file leaves all of these at their defaults, so
    # nothing below changes how a .kicad_mod is read.
    src: str = ""               # human label; "" means f"{kind} #{index}"
    mirror: bool = False        # text plotted mirrored (a back-side item)
    hole_r: float = 0.0         # via/pad drill radius: the ink is an ANNULUS
    stale_hole: bool = False    # unplated, or drill >= pad: no copper ring at all
    holes: list = field(default_factory=list)   # inner rings of a filled area
    stale: str = ""             # provenance caveat, e.g. a stored zone fill
    # KiCad net number as a string, "" for none. Copper on the SAME net is
    # allowed to touch -- it is one conductor -- so a gap between two pieces
    # of it is not a spacing violation. Copper with no net is not exempt: two
    # unconnected art tiles a hundredth of a millimetre apart still have to be
    # etched apart. See _same_net().
    net: str = ""
    # Which footprint instance on the board this item came from, as an index
    # into Footprint.instances; -1 for a board-level graphic and for every
    # item of a .kicad_mod (where there is only one footprint anyway). This is
    # the ONLY identity a sweep declaration can be attributed through: uuids do
    # not survive (fp upgrade, SaveBoard and canonicalise.py each renumber
    # them) and the item labels are strings built for humans.
    owner: int = -1
    _ink: "TextInk | None" = None

    def bbox(self):
        b = bbox_of(self.pts)
        if b is None:
            return None
        return bbox_inflate(b, self.width / 2.0) if self.width else b


@dataclass
class FpInstance:
    """One placed footprint on a board, and the metadata it carries.

    THE HOLE THIS CLOSES. `tags` and `descr` are in FP_INERT_HEADS, and
    load_board() built its Footprint with tags="" -- so until now NO footprint
    metadata except the library id reached any check on a .kicad_pcb. That is
    also why `fab:`, `palette:` and `tonemap:` are silently inert on boards and
    check_colourway always falls back to "checked as black mask". Reading tags
    here for `sweep:` fixes it for the other three at the same time.
    """
    idx: int
    lib: str
    ref: str
    tags: str = ""
    descr: str = ""
    placement: "Placement | None" = None
    source: str = "board-embedded copy"


@dataclass
class Footprint:
    name: str
    version: str
    generator: str
    items: list[Item]
    raw_layer: str = ""
    tags: str = ""
    # Board context, all inert for a .kicad_mod.
    is_board: bool = False
    path: "Path | None" = None
    head_counts: dict = field(default_factory=dict)
    unmeasured: list = field(default_factory=list)  # (label, layer, reason)
    board_layers: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    instances: list = field(default_factory=list)   # [FpInstance]


def _net_of(node) -> str:
    """The KiCad net number on a copper object, "" when it has none.

    Net 0 IS "no net" in KiCad's numbering, and it is deliberately mapped to
    "" here so that two unconnected pieces of copper are never treated as one
    conductor. Everything on the coupons is net 0.
    """
    n = kid(node, "net")
    if n is None or len(n) < 2:
        return ""
    v = str(n[1]).strip('"')
    return "" if v in ("0", "") else v


def _same_net(a: Item, b: Item) -> bool:
    return bool(a.net) and a.net == b.net


def item_label(i: int, it: Item) -> str:
    """What to call an item in a report. Board items carry their own name --
    'gr_poly #12' or 'FP R14/fp_line #3' -- because "#3" alone is useless when
    the file holds 156 footprints and 495 board graphics."""
    return it.src or f"{it.kind} #{i}"


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

    # `(justify mirror)` -- what KiCad writes on every back-side string so it
    # reads correctly through the board -- is already applied by
    # stroke_font.string_chains(), which reflects the laid-out line about the
    # anchor's vertical axis. Nothing more is needed here, and reflection is an
    # isometry anyway: widths, inter-glyph gaps and counters are identical
    # either way, so only POSITION depends on getting it right, and position is
    # what the gap check compares against the neighbours.

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
        it = build_pad(node)
        return None if it is None else place_pad(it)

    return None


# --------------------------------------------------------------------------
# Curves and pads: outlines, not bounding boxes
# --------------------------------------------------------------------------
#
# Everything below CIRCUMSCRIBES. A polygon drawn through the vertices of a
# circle sits inside it, which makes the ink smaller and every gap around it
# wider than it really is -- the direction that hides violations. Pushing the
# polygon out to touch at the edge midpoints instead can only cost margin.

def _poly_circle(cx: float, cy: float, r: float, n: int = 64):
    if r <= 0:
        return []
    rr = r / math.cos(math.pi / max(n, 3))
    return [(cx + rr * math.cos(2 * math.pi * k / n),
             cy + rr * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _arc_center(a, m, b):
    """Centre and radius of the circle through three points. None if collinear."""
    (x1, y1), (x2, y2), (x3, y3) = a, m, b
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return None
    s1 = x1 * x1 + y1 * y1
    s2 = x2 * x2 + y2 * y2
    s3 = x3 * x3 + y3 * y3
    ux = (s1 * (y2 - y3) + s2 * (y3 - y1) + s3 * (y1 - y2)) / d
    uy = (s1 * (x3 - x2) + s2 * (x1 - x3) + s3 * (x2 - x1)) / d
    return (ux, uy), math.hypot(x1 - ux, y1 - uy)


def flatten_arc(a, m, b, max_sag: float = 0.002):
    """Polyline through a KiCad start/mid/end arc, bulging OUTWARD.

    `max_sag` is the chord sag budget in mm; the segment count is chosen from
    it and then the INTERIOR vertices are pushed out by the sag so the polyline
    contains the true arc rather than cutting the corner off it.

    THE ENDPOINTS ARE EXACT, and that is a fix, not a detail. Inflating them
    too moved each end of the arc 1.9 um off the point KiCad stores -- and on
    the beta coupon, whose outline is four gr_line and four gr_arc, that meant
    no arc endpoint ever met a line endpoint. closed_loops() found no loop,
    check_min_feature printed "Edge.Cuts present but no closed loop found --
    slot width NOT CHECKED", and the board outline of every rounded-rectangle
    card went unmeasured. A check that cannot see the most common outline shape
    in the tree is a check that cannot fail.

    Containment is not lost: only the first and last sub-segment now sit inside
    the true arc, by at most the same `max_sag` the segment count was chosen to
    respect. Every interior vertex still circumscribes.
    """
    got = _arc_center(a, m, b)
    if got is None:
        return [a, m, b]
    (cx, cy), r = got
    if r <= 0:
        return [a, m, b]
    a0 = math.atan2(a[1] - cy, a[0] - cx)
    am = math.atan2(m[1] - cy, m[0] - cx)
    a1 = math.atan2(b[1] - cy, b[0] - cx)

    def norm(t):
        while t < 0:
            t += 2 * math.pi
        while t >= 2 * math.pi:
            t -= 2 * math.pi
        return t
    # Direction is whichever way passes through the mid point.
    ccw = norm(am - a0) < norm(a1 - a0)
    sweep = norm(a1 - a0) if ccw else -norm(a0 - a1)
    if abs(sweep) < 1e-12:
        sweep = 2 * math.pi if ccw else -2 * math.pi
    n = max(4, int(math.ceil(abs(sweep) / (2.0 * math.acos(
        max(-1.0, min(1.0, 1.0 - max_sag / max(r, 1e-9))))))))
    n = min(n, 512)
    rr = r / math.cos(abs(sweep) / (2.0 * n))
    out = []
    for k in range(n + 1):
        rk = r if k in (0, n) else rr
        out.append((cx + rk * math.cos(a0 + sweep * k / n),
                    cy + rk * math.sin(a0 + sweep * k / n)))
    # Snap the ends to the coordinates KiCad actually stored, so a chain of
    # arcs and segments closes on equality rather than on a tolerance.
    out[0], out[-1] = (a[0], a[1]), (b[0], b[1])
    return out


def flatten_bezier(p0, p1, p2, p3, n: int = 48):
    out = []
    for k in range(n + 1):
        t = k / n
        u = 1.0 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0]
                    + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1]
                    + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def _rounded_rect(cx, cy, w, h, rad, ang, n=8):
    """Corner-rounded rectangle, circumscribed, rotated `ang` degrees."""
    hw, hh = w / 2.0, h / 2.0
    rad = max(0.0, min(rad, hw, hh))
    pts = []
    if rad <= 1e-9:
        pts = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    else:
        rr = rad / math.cos(math.pi / (4.0 * max(n, 1)))
        for (sx, sy, base) in ((1, 1, 0.0), (-1, 1, math.pi / 2),
                               (-1, -1, math.pi), (1, -1, 3 * math.pi / 2)):
            ox, oy = sx * (hw - rad), sy * (hh - rad)
            for k in range(n + 1):
                t = base + (math.pi / 2) * k / n
                pts.append((ox + rr * math.cos(t), oy + rr * math.sin(t)))
    if ang:
        a = math.radians(ang)
        c, s = math.cos(a), math.sin(a)
        pts = [(x * c + y * s, -x * s + y * c) for (x, y) in pts]
    return [(cx + x, cy + y) for (x, y) in pts]


def build_pad(node) -> Item | None:
    """A pad as its real outline, not its bounding box.

    A bbox is not a conservative stand-in for a pad: it is LARGER than the pad,
    so it over-states ink and under-states every gap around it, which is the
    direction that invents violations. It is also the wrong shape for a drilled
    pad, where the feature that can actually fail is the annular ring.

    Anything not modelled here -- a custom pad whose primitives this does not
    read -- comes back with `stale` set naming what is unknown, and the caller
    must report it as NOT MEASURED.
    """
    layers = _layers_of(node)
    shape = node[3] if len(node) > 3 and isinstance(node[3], str) else "?"
    at = kid(node, "at")
    x, y = node_xy(at)
    ang = fnum(at[3], 0.0) if at is not None and len(at) > 3 else 0.0
    sz = kid(node, "size")
    w = fnum(sz[1], 0.0) or 0.0 if sz is not None and len(sz) > 1 else 0.0
    h = fnum(sz[2], 0.0) or 0.0 if sz is not None and len(sz) > 2 else 0.0
    dr = kid(node, "drill")
    hole_r = 0.0
    if dr is not None:
        # (drill D) or (drill oval W H); the oval hole is bounded by its larger
        # dimension, which is the conservative reading of the annular ring.
        nums = [fnum(t) for t in dr[1:] if isinstance(t, str) and fnum(t) is not None]
        if nums:
            hole_r = max(nums) / 2.0

    # THE PAD ANGLE IS ABSOLUTE, NOT LOCAL. KiCad writes a pad's `at` angle as
    # the orientation it has ON THE BOARD -- a footprint placed at 90 degrees
    # whose pads carry no rotation of their own has every pad written as 90
    # (verified across the product board's 553 pads: footprint -90 -> pad 270,
    # footprint 180 -> pad 180, footprint 90 -> pad 90). So the outline is
    # built UNROTATED here and the angle is stashed; place_pad() applies it
    # once, in board coordinates. Applying it here as well rotated every SMD
    # pad twice: on the USB-C receptacle that turned 0.5842 x 1.143 mm contacts
    # 90 degrees the wrong way, overlapped VBUS with GND, and merged 44
    # separate pads into one 1-component blob.
    pts, unknown = [], ""
    if shape == "circle":
        pts = _poly_circle(x, y, w / 2.0)
    elif shape == "rect":
        pts = _rounded_rect(x, y, w, h, 0.0, 0.0)
    elif shape == "oval":
        pts = _rounded_rect(x, y, w, h, min(w, h) / 2.0, 0.0)
    elif shape == "roundrect":
        rr = kid(node, "roundrect_rratio")
        ratio = fnum(rr[1], 0.25) if rr is not None and len(rr) > 1 else 0.25
        pts = _rounded_rect(x, y, w, h, (ratio or 0.0) * min(w, h), 0.0)
    elif shape == "trapezoid":
        rd = kid(node, "rect_delta")
        dx = fnum(rd[1], 0.0) or 0.0 if rd is not None and len(rd) > 1 else 0.0
        dy = fnum(rd[2], 0.0) or 0.0 if rd is not None and len(rd) > 2 else 0.0
        hw, hh = w / 2.0, h / 2.0
        loc = [(-hw - dy / 2, -hh + dx / 2), (hw + dy / 2, -hh - dx / 2),
               (hw - dy / 2, hh + dx / 2), (-hw + dy / 2, hh - dx / 2)]
        pts = [(x + px, y + py) for (px, py) in loc]
    elif shape == "custom":
        # The anchor shape is real copper too; the primitives sit on top of it.
        opt = kid(node, "options")
        anchor = "circle"
        if opt is not None:
            ak = kid(opt, "anchor")
            if ak is not None and len(ak) > 1:
                anchor = ak[1]
        pts = (_poly_circle(x, y, min(w, h) / 2.0) if anchor == "circle"
               else _rounded_rect(x, y, w, h, 0.0, 0.0))
        prim = kid(node, "primitives")
        heads = sorted({p[0] for p in (prim[1:] if prim else [])
                        if isinstance(p, list) and p})
        unknown = (f"custom pad: its anchor is measured but the "
                   f"{len(heads)} primitive kind(s) it draws on top "
                   f"({', '.join(heads) or 'none'}) are NOT expanded here, so "
                   f"this pad's true outline is UNKNOWN")
    else:
        hw, hh = w / 2.0, h / 2.0
        pts = [(x - hw, y - hh), (x + hw, y - hh), (x + hw, y + hh), (x - hw, y + hh)]
        unknown = (f"pad shape {shape!r} is not modelled; the bounding box is "
                   f"used, which OVER-states ink, so any gap round this pad is "
                   f"NOT MEASURED")
    if not pts:
        return None
    it = Item("pad", layers, pts, 0.0, True)
    it.hole_r = hole_r
    it.char_h = min(w, h) / 2.0 if (w and h) else 0.0
    it.stale = unknown
    it.at = (x, y)
    it.angle = ang
    ptype = node[2] if len(node) > 2 and isinstance(node[2], str) else ""
    # A HOLE IS NOT A RING. An np_thru_hole -- a mounting hole, a connector's
    # locating peg -- has no plating, and KiCad's own libraries give several of
    # them a drill AT LEAST as large as the pad, so subtracting the hole from
    # the pad leaves nothing, or a crescent where an oval pad is longer than it
    # is wide. Measured as copper, those produced 45 "components of 0.0000 mm2
    # whose thickest ink is 0.000000 mm" on the product board and one 0.070 mm
    # "narrowest copper feature" that is not copper at all. There is no annular
    # ring here to be too thin, and saying there is is a false alarm.
    it.stale_hole = (ptype == "np_thru_hole"
                     or (hole_r > 0 and it.char_h > 0 and hole_r >= it.char_h - 1e-9))
    return it


def place_pad(it: Item, pl: "Placement | None" = None) -> Item:
    """Put a pad outline where it really is: centre through the footprint's
    frame, shape rotated by the pad's own ABSOLUTE angle about that centre.

    Called for both a standalone .kicad_mod (where the footprint frame is the
    identity, so the stored angle is already absolute) and a placed instance.
    """
    cx, cy = it.at if pl is None else pl.pt(it.at)
    ox, oy = it.at
    if it.angle:
        a = math.radians(it.angle)
        c, s = math.cos(a), math.sin(a)
        it.pts = [(cx + (px - ox) * c + (py - oy) * s,
                   cy - (px - ox) * s + (py - oy) * c) for (px, py) in it.pts]
    else:
        it.pts = [(cx + px - ox, cy + py - oy) for (px, py) in it.pts]
    it.at = (cx, cy)
    return it


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
    ds = kid(fp, "descr")

    items = []
    for c in fp:
        if isinstance(c, list) and c and c[0] in GRAPHIC_HEADS:
            it = build_item(c)
            if it is not None:
                it.owner = 0
                items.append(it)

    tags = (tg[1] if tg and len(tg) > 1 and isinstance(tg[1], str) else "")
    return Footprint(
        name=name,
        version=(v[1] if v and len(v) > 1 else "?"),
        generator=(g[1] if g and len(g) > 1 else "?"),
        items=items,
        raw_layer=(lay[1] if lay and len(lay) > 1 else ""),
        tags=tags,
        path=path,
        instances=[FpInstance(
            idx=0, lib=name, ref="-", tags=tags,
            descr=(ds[1] if ds and len(ds) > 1 and isinstance(ds[1], str)
                   else ""),
            placement=None, source="library file")],
    )


# ==========================================================================
# BOARD INGEST
# ==========================================================================
#
# WHY A BOARD AT ALL. This harness read .kicad_mod and only .kicad_mod, by
# three independent gates: main() globbed *.kicad_mod, load_footprint()
# demanded a (footprint ...) root, and GRAPHIC_HEADS listed fp_* items. A
# .kicad_pcb therefore had no route through any check -- and a board is where
# the art actually ships. The coupon boards carry 981 gr_poly between them,
# every one of them written by a script that never touched emit_art's floor
# enforcement, and not one of them was ever compared to a floor by anything.
#
# The whole point of the model below is that a board is read into the SAME
# Item objects a footprint is read into. gr_poly BECOMES fp_poly, a track
# segment BECOMES fp_line, a via BECOMES a filled circle with a hole. Every
# existing check -- geometry, layers, self-intersection, min-feature,
# clearance, text expansion, the fab-tag severity logic -- then applies to a
# board with no changes at all, which is the only way to be sure the board is
# being held to the same numbers the footprints are.
#
# The one thing that does NOT transfer is the filled-polygon width measure.
# min_width() is a rotating caliper on the convex hull; on a traced letterform
# it reports the glyph's overall width, not its stem, and reading a board
# without saying so would have produced a green min-feature check written
# directly over this defect. So on a board, concave filled areas are handed to
# the region measurement in tools/ink_measure.py and min-feature refuses to
# claim it measured them. See check_min_feature() and check_ink().

# Board-level nodes with no plotted geometry whatsoever.
BOARD_INERT_HEADS = {
    "version", "generator", "generator_version", "general", "paper",
    "title_block", "layers", "setup", "property", "net", "net_class",
    "netclass", "group", "embedded_fonts", "embedded_files", "uuid",
    "links", "private_layers", "tenting", "models", "teardrops",
}

# Footprint-level nodes with no plotted geometry.
FP_INERT_HEADS = {
    "layer", "uuid", "tstamp", "at", "descr", "tags", "path", "sheetname",
    "sheetfile", "units", "attr", "model", "locked", "placed", "autoplace_cost90",
    "autoplace_cost180", "solder_mask_margin", "solder_paste_margin",
    "solder_paste_ratio", "clearance", "zone_connect", "thermal_width",
    "thermal_gap", "net_tie_pad_groups", "private_layers", "embedded_fonts",
    "embedded_files", "duplicate_pad_numbers_are_jumpers", "component_classes",
    "jumper_pad_groups", "sheetname_", "version", "generator",
    "generator_version", "property_", "allow_solder_mask_bridges", "group",
}

# Geometry-bearing nodes this harness cannot turn into a measurable outline.
# Each entry is the sentence the report prints. NOTHING is silently dropped:
# an entry here becomes a NOT MEASURED line and drags its layer to SKIP.
UNMEASURED_HEADS = {
    "dimension": ("a dimension draws arrows, extension lines and a value "
                  "string; only its stated (style (thickness)) is readable "
                  "here, the drawn geometry is not expanded"),
    "table": ("a table draws cell borders and text on its layer; neither is "
              "modelled here"),
    "target": ("a PCB target draws a cross or plus at a stated size and "
               "stroke; not modelled here"),
    "generated": ("a generated item (length-tuning meander) regenerates its "
                  "own child geometry; the stored children are read but the "
                  "generator is not run, so the shipped shape may differ"),
    "image": ("a bitmap reference image is NEVER PLOTTED to a fabrication "
              "layer, so it is not ink -- recorded so nobody expects it to be"),
}

_ANY_CU = re.compile(r"^\*\.Cu$")


def _copper_layers(board_layers: list[str]) -> list[str]:
    return [l for l in board_layers if layer_class(l) in ("copper", "buried")]


def expand_layer_tokens(toks: list[str], board_layers: list[str]) -> list[str]:
    """Resolve KiCad's layer wildcards against the board's own layer table.

    A through-hole pad says (layers "*.Cu" "*.Mask"), and leaving that literal
    would make the layer check call "*.Cu" an unknown layer and the ink check
    put copper on a layer that does not exist. Both are wrong in the same way:
    the pad is on EVERY copper layer, and the fab images it on every one.
    """
    out: list[str] = []
    cu = _copper_layers(board_layers) or ["F.Cu", "B.Cu"]
    for t in toks:
        if t in ("*.Cu", "*.Mask", "*.Paste", "*.SilkS", "*.Adhes", "*.CrtYd",
                 "*.Fab"):
            suffix = t[1:]
            if suffix == ".Cu":
                out += cu
            else:
                out += [f"F{suffix}", f"B{suffix}"]
        elif t.startswith("F&B."):
            out += [f"F.{t[4:]}", f"B.{t[4:]}"]
        elif t in ("F.Mask", "B.Mask", "F.Paste", "B.Paste") or t in KNOWN_LAYERS:
            out.append(t)
        else:
            out.append(t)
    seen, uniq = set(), []
    for l in out:
        if l not in seen:
            seen.add(l)
            uniq.append(l)
    return uniq


@dataclass
class Placement:
    """A footprint instance's frame on the board."""
    x: float = 0.0
    y: float = 0.0
    ang: float = 0.0
    back: bool = False
    ref: str = "?"

    def pt(self, p):
        # Same convention build_item() uses for rotated text, and the one
        # validated against this project's product board: of 497 DANGLING
        # track endpoints (endpoints not shared with a second segment, so they
        # can only terminate on a pad or a via), 495 land on a pad or via under
        # this transform and 462 under the opposite sign. Footprint children
        # are stored in the footprint's own frame ALREADY MIRRORED when the
        # part is on the back, so there is no reflection to apply here -- only
        # rotation and translation.
        if not self.ang:
            return (self.x + p[0], self.y + p[1])
        a = math.radians(self.ang)
        c, s = math.cos(a), math.sin(a)
        return (self.x + p[0] * c + p[1] * s, self.y - p[0] * s + p[1] * c)


def _place_item(it: Item, pl: Placement, label: str) -> Item:
    if it.kind == "pad":
        place_pad(it, pl)
        it.src = label
        return it
    it.pts = [pl.pt(p) for p in it.pts]
    it.holes = [[pl.pt(p) for p in ring] for ring in it.holes]
    if it.kind in ("fp_text", "fp_text_box", "property"):
        # Text POSITION is stored in the footprint frame; the text ANGLE is
        # stored absolute (a reference on a footprint rotated 180 with "keep
        # upright" set reads 0, not 180). So rotate the anchor, keep the angle.
        it.at = pl.pt(it.at)
        it.mirror = "mirror" in it.justify
    it.src = label
    return it


def _board_item_from(node, board_layers: list[str]) -> Item | None:
    """Every board graphic mapped onto the footprint Item vocabulary."""
    head = node[0]
    layers = expand_layer_tokens(_layers_of(node), board_layers)
    width = _stroke_width(node)

    if head == "gr_line":
        return Item("fp_line", layers,
                    [node_xy(kid(node, "start")), node_xy(kid(node, "end"))],
                    width)
    if head == "gr_rect":
        (x0, y0) = node_xy(kid(node, "start"))
        (x1, y1) = node_xy(kid(node, "end"))
        return Item("fp_rect", layers,
                    [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], width,
                    _is_filled(node))
    if head == "gr_circle":
        (cx, cy) = node_xy(kid(node, "center"))
        (ex, ey) = node_xy(kid(node, "end"))
        r = math.hypot(ex - cx, ey - cy)
        it = Item("fp_circle", layers,
                  [(cx - r, cy - r), (cx + r, cy - r),
                   (cx + r, cy + r), (cx - r, cy + r)], width, _is_filled(node))
        it.char_h = r
        return it
    if head == "gr_arc":
        it = Item("fp_arc", layers,
                  flatten_arc(node_xy(kid(node, "start")),
                              node_xy(kid(node, "mid")),
                              node_xy(kid(node, "end"))), width)
        return it
    if head == "gr_curve":
        p = kid(node, "pts")
        cps = [(fnum(c[1], 0.0), fnum(c[2], 0.0)) for c in (p[1:] if p else [])
               if isinstance(c, list) and c and c[0] == "xy"]
        if len(cps) < 4:
            return None
        it = Item("fp_line", layers, flatten_bezier(*cps[:4]), width)
        it.approx_bbox = True
        return it
    if head == "gr_poly":
        p = kid(node, "pts")
        pts, curves = [], False
        for c in (p[1:] if p else []):
            if isinstance(c, list) and c:
                if c[0] == "xy" and len(c) >= 3:
                    pts.append((fnum(c[1], 0.0), fnum(c[2], 0.0)))
                elif c[0] in ("arc", "bezier"):
                    curves = True
        it = Item("fp_poly", layers, pts, width, _is_filled(node))
        it.has_curves = curves
        return it
    if head in ("gr_text", "gr_text_box"):
        it = build_item(["fp_text" if head == "gr_text" else "fp_text_box"]
                        + list(node[1:]))
        if it is not None:
            it.layers = layers
            it.mirror = "mirror" in it.justify
        return it
    if head == "segment":
        it = Item("fp_line", layers,
                  [node_xy(kid(node, "start")), node_xy(kid(node, "end"))],
                  width or _num_kid(node, "width"))
        it.net = _net_of(node)
        return it
    if head == "arc":
        it = Item("fp_arc", layers,
                  flatten_arc(node_xy(kid(node, "start")),
                              node_xy(kid(node, "mid")),
                              node_xy(kid(node, "end"))),
                  width or _num_kid(node, "width"))
        it.net = _net_of(node)
        return it
    if head == "via":
        (cx, cy) = node_xy(kid(node, "at"))
        size = _num_kid(node, "size")
        drill = _num_kid(node, "drill")
        span = expand_layer_tokens(_layers_of(node), board_layers)
        # (layers F.Cu B.Cu) on a via names the SPAN, not two layers: the
        # barrel and its ring exist on every copper layer in between.
        cu = _copper_layers(board_layers)
        if len(span) == 2 and all(s in cu for s in span):
            i0, i1 = sorted((cu.index(span[0]), cu.index(span[1])))
            span = cu[i0:i1 + 1]
        it = Item("fp_circle", span,
                  [(cx - size / 2, cy - size / 2), (cx + size / 2, cy - size / 2),
                   (cx + size / 2, cy + size / 2), (cx - size / 2, cy + size / 2)],
                  0.0, True)
        it.char_h = size / 2.0
        it.hole_r = drill / 2.0
        it.net = _net_of(node)
        return it
    if head == "pad":
        it = build_pad(node)
        if it is not None:
            it.layers = expand_layer_tokens(it.layers, board_layers)
            it.net = _net_of(node)
        return it
    if head in GRAPHIC_HEADS:
        it = build_item(node)
        if it is not None and it.layers:
            it.layers = expand_layer_tokens(it.layers, board_layers)
        return it
    return None


def _num_kid(node, head, default=0.0) -> float:
    k = kid(node, head)
    if k is None or len(k) < 2:
        return default
    return fnum(k[1], default) or default


def _zone_items(node, board_layers, label) -> tuple[list[Item], list[tuple]]:
    """A zone contributes the polygons KiCad LAST FILLED, plus a caveat.

    The fill stored in the file is a cache. Nothing here can tell a fresh fill
    from a stale one -- pcbnew's own NeedRefill() answers False for a board
    loaded off disk -- so the fill is measured AND the reader is told it is
    reading a cache. A zone with no stored fill contributes no ink at all and
    is reported as NOT MEASURED rather than as empty.
    """
    items, unmeasured = [], []
    keep = kid(node, "keepout")
    zl = expand_layer_tokens(_layers_of(node), board_layers)
    fills = kids(node, "filled_polygon")
    if keep is not None:
        unmeasured.append((label, "/".join(zl) or "?",
                           "rule area (keepout): it draws no copper, but the "
                           "rules it imposes are DRC's business and are not "
                           "evaluated here"))
        return items, unmeasured
    if not fills:
        unmeasured.append((label, "/".join(zl) or "?",
                           "zone has NO STORED FILL, so the copper it will "
                           "contribute is UNKNOWN -- refill the board and save "
                           "before measuring it"))
        return items, unmeasured
    for k, f in enumerate(fills):
        fl = expand_layer_tokens(_layers_of(f), board_layers) or zl
        p = kid(f, "pts")
        pts, curves = [], False
        for c in (p[1:] if p else []):
            if isinstance(c, list) and c:
                if c[0] == "xy" and len(c) >= 3:
                    pts.append((fnum(c[1], 0.0), fnum(c[2], 0.0)))
                elif c[0] in ("arc", "bezier"):
                    curves = True
        if len(pts) < 3:
            continue
        it = Item("fp_poly", fl, pts, 0.0, True)
        it.has_curves = curves
        it.net = _net_of(node)
        it.src = f"{label} fill {k}"
        it.stale = ("stored zone fill: this is the polygon the last fill "
                    "produced, not necessarily the one this board would "
                    "produce now")
        items.append(it)
    return items, unmeasured


def load_board(path: Path) -> Footprint:
    """Read a .kicad_pcb into the same Item model a footprint uses.

    Returns a Footprint with is_board=True. `unmeasured` carries one entry per
    construct whose geometry could not be derived -- including any node head
    this harness has never seen, because "a construct KiCad added after this
    was written" is exactly the blind spot that let the defect through, and a
    reader that silently ignores what it does not recognise has the same hole
    the .kicad_mod-only glob had.
    """
    from collections import Counter
    text = path.read_text(encoding="utf-8", errors="replace")
    nodes = parse_sexpr(text)
    roots = [n for n in nodes if isinstance(n, list) and n and n[0] == "kicad_pcb"]
    if not roots:
        raise ParseError("no (kicad_pcb ...) node found")
    if len(roots) > 1:
        raise ParseError(f"{len(roots)} kicad_pcb nodes in one file (expected 1)")
    b = roots[0]

    v = kid(b, "version")
    g = kid(b, "generator")
    lt = kid(b, "layers")
    board_layers = []
    if lt is not None:
        for row in lt[1:]:
            if isinstance(row, list) and len(row) > 1 and isinstance(row[1], str):
                board_layers.append(row[1])

    items: list[Item] = []
    unmeasured: list[tuple] = []
    heads = Counter()
    notes: list[str] = []
    instances: list[FpInstance] = []
    cur_owner = [-1]

    setup = kid(b, "setup")
    if setup is not None:
        pp = kid(setup, "pcbplotparams")
        if pp is not None:
            sm = kid(pp, "subtractmaskfromsilk")
            if sm is not None and len(sm) > 1 and sm[1] in ("yes", "true"):
                notes.append(
                    "(subtractmaskfromsilk yes): the plotted silk is this "
                    "board's silk MINUS the mask openings, so the silk "
                    "measured here is not the silk the fab receives. Measure "
                    "the plotted gerber for that")
        if kid(setup, "stackup") is None:
            notes.append(
                "no (stackup ...) in setup: the .gbrjob this board plots will "
                "declare Finish 'None' and synthesised dielectrics")

    def take(node, prefix: str, pl: Placement | None, idx: int):
        head = node[0]
        label = f"{prefix}{head} #{idx}"
        if head in UNMEASURED_HEADS:
            lay = "/".join(expand_layer_tokens(_layers_of(node), board_layers)) or "?"
            extra = ""
            if head == "dimension":
                st = kid(node, "style")
                if st is not None:
                    extra = f" (stated thickness {_num_kid(st, 'thickness'):.4f} mm)"
            unmeasured.append((label, lay, UNMEASURED_HEADS[head] + extra))
            return
        if head == "zone":
            zi, zu = _zone_items(node, board_layers, label)
            for it in zi:
                if pl is not None:
                    _place_item(it, pl, it.src)
                it.owner = cur_owner[0]
                items.append(it)
            unmeasured.extend(zu)
            return
        it = _board_item_from(node, board_layers)
        if it is None:
            unmeasured.append((label, "?", "this node head carries geometry "
                                           "but produced no readable outline"))
            return
        if pl is not None:
            _place_item(it, pl, label)
        else:
            if it.kind == "pad":
                place_pad(it)
            it.src = label
        if it.stale and it.kind == "pad":
            unmeasured.append((label, "/".join(it.layers) or "?", it.stale))
        it.owner = cur_owner[0]
        items.append(it)

    for i, c in enumerate(b):
        if not (isinstance(c, list) and c):
            continue
        head = c[0]
        heads[head] += 1
        if head in BOARD_INERT_HEADS:
            continue
        if head == "footprint":
            at = kid(c, "at")
            fx, fy = node_xy(at)
            fang = fnum(at[3], 0.0) if at is not None and len(at) > 3 else 0.0
            flay = kid(c, "layer")
            ref = "?"
            for pr in kids(c, "property"):
                if len(pr) > 2 and pr[1] == "Reference" and isinstance(pr[2], str):
                    ref = pr[2]
                    break
            pl = Placement(fx, fy, fang or 0.0,
                           bool(flay and len(flay) > 1 and flay[1] == "B.Cu"), ref)
            lib = c[1] if len(c) > 1 and isinstance(c[1], str) else "?"
            # METADATA, NOT AN ITEM. `tags` and `descr` carry no geometry, so
            # they stay out of GRAPHIC_HEADS and out of the item list -- a
            # field that is metadata on one code path and ink on another is
            # the shape of the defect where an emitter attribute was read back
            # as a measurement, and there must not be a second one.
            ftags = kid(c, "tags")
            fdescr = kid(c, "descr")
            inst = FpInstance(
                idx=len(instances), lib=lib, ref=ref,
                tags=(ftags[1] if ftags and len(ftags) > 1
                      and isinstance(ftags[1], str) else ""),
                descr=(fdescr[1] if fdescr and len(fdescr) > 1
                       and isinstance(fdescr[1], str) else ""),
                placement=pl)
            instances.append(inst)
            cur_owner[0] = inst.idx
            for k, ch in enumerate(c):
                if not (isinstance(ch, list) and ch):
                    continue
                h2 = ch[0]
                heads[f"footprint/{h2}"] += 1
                if h2 in FP_INERT_HEADS:
                    continue
                if h2 in GRAPHIC_HEADS or h2 in UNMEASURED_HEADS or h2 == "zone":
                    take(ch, f"FP {ref} [{lib}] ", pl, k)
                else:
                    unmeasured.append(
                        (f"FP {ref} [{lib}] {h2} #{k}", "?",
                         f"unknown footprint node head {h2!r}: this harness has "
                         f"never seen it, so whatever geometry it carries is "
                         f"NOT MEASURED"))
            cur_owner[0] = -1
            continue
        if head in UNMEASURED_HEADS or head == "zone" or head.startswith("gr_") \
                or head in ("segment", "arc", "via", "pad"):
            take(c, "", None, i)
            continue
        unmeasured.append((f"{head} #{i}", "?",
                           f"unknown board node head {head!r}: this harness has "
                           f"never seen it, so whatever geometry it carries is "
                           f"NOT MEASURED"))

    return Footprint(
        name=path.stem,
        version=(v[1] if v and len(v) > 1 else "?"),
        generator=(g[1] if g and len(g) > 1 else "?"),
        items=items,
        raw_layer="",
        tags="",
        is_board=True,
        path=path,
        head_counts=dict(heads),
        unmeasured=unmeasured,
        board_layers=board_layers,
        notes=notes,
        instances=instances,
    )


def sniff_root(path: Path) -> str:
    """'board', 'footprint' or '' -- decided on the file's own root node."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return ""
    m = re.search(r"\(\s*(kicad_pcb|footprint|module)\b", head)
    return {"kicad_pcb": "board", "footprint": "footprint",
            "module": "footprint"}.get(m.group(1) if m else "", "")


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


# --------------------------------------------------------------------------
# Startup preflight: a missing hard dependency is loud HERE, not silent later
# --------------------------------------------------------------------------

def _venv_interpreters() -> list[str]:
    """Interpreters in this repo's own .venv, if there is one. Named in the
    preflight because "install shapely" is useless advice to somebody who ran
    the right command under the wrong python -- they do not need a package,
    they need the other interpreter, and it is already on their disk."""
    root = Path(__file__).resolve().parent.parent
    out = []
    for rel in (".venv/bin/python3", ".venv/bin/python",
                ".venv/Scripts/python.exe"):
        p = root / rel
        if p.exists():
            out.append(str(p))
    return out


def preflight() -> tuple[list[str], list[Gap]]:
    """What this interpreter can and cannot do, reported BEFORE any file.

    THE SHAPE OF THE DEFECT THIS EXISTS FOR. The ink-floor check is the only
    check in this harness that measures the INSCRIBED width of a filled region
    and the only one that can see a gap inside a single polygon. It needs
    shapely. Run under an interpreter without shapely -- KiCad's bundled
    python, say -- it reported SKIP at check time, three hundred lines into a
    report nobody reads to the end, and the run summarised green.

    Saying it at startup does not by itself fix that (the gap machinery does),
    but it moves the sentence to where the operator is still looking at the
    screen, and it names the interpreter that WOULD work.

    -> (lines to print, gaps to attach to every file in the run)
    """
    lines, gaps = [], []
    if ink_measure is None:
        why = (f"tools/ink_measure.py could not be imported: {_INK_IMPORT_ERR}")
        ok = False
    else:
        ok, w = ink_measure.available()
        why = w
    if ok:
        return lines, gaps

    alts = _venv_interpreters()
    lines.append("")
    lines.append("  !!  THE INK-FLOOR CHECK CANNOT RUN UNDER THIS INTERPRETER")
    lines.append(f"      python     : {sys.executable}")
    lines.append(f"      reason     : {why}")
    lines.append("      ink-floor is the ONLY check that measures the inscribed")
    lines.append("      width of a filled region, and the ONLY one that can see")
    lines.append("      a gap inside a single polygon. Traced letterforms,")
    lines.append("      dithered stipple and keyhole-bridged glyphs are")
    lines.append("      measured by it and by nothing else. Without it this run")
    lines.append("      does not measure them AT ALL -- it does not measure")
    lines.append("      them approximately.")
    fix = "install shapely, or run under an interpreter that has it"
    if alts:
        lines.append("      this repo already has an interpreter for it:")
        for a in alts:
            lines.append(f"        {a} tools/verify_art.py ...")
        fix = f"run under {alts[0]} (this repo's .venv), which has shapely"
    else:
        lines.append("      fix        : pip install shapely, in the venv you")
        lines.append("                   run this harness from")
    lines.append("      the run continues, but it CANNOT report a pass: see")
    lines.append("      the CHECKS THAT DID NOT RUN block at the end.")
    lines.append("")
    gaps.append(Gap("ink-floor", "whole check", GAP_NOT_RUN, why, fix,
                    "every floor-bearing layer of every file in this run"))
    return lines, gaps


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
    # Set only by the "exempt" check. Carried on the Check rather than in a
    # side channel so the count travels with the report it describes.
    exempt: int = 0
    stale: int = 0
    exemptions: list = field(default_factory=list)
    # COVERAGE, the second axis. Everything this check did NOT measure. See
    # the Gap docstring above: a gap never moves `level`, it binds the run.
    gaps: list = field(default_factory=list)

    def gap(self, scope: str, kind: str, why: str, fix: str = "",
            extent: str = "") -> "Check":
        """Record a hole and return self, so a `return Check(...).gap(...)`
        reads as one statement at the site that could not measure."""
        self.gaps.append(Gap(self.key, scope, kind, why, fix, extent))
        return self


# --- 1. loads in KiCad ------------------------------------------------------

def check_kicad_load(path: Path, cfg) -> Check:
    cli = cfg.cli
    if not cli:
        return Check("kicad-load", SKIP,
                     "kicad-cli NOT FOUND -- this file is UNVERIFIED against KiCad",
                     ["searched PATH, $KICAD_CLI and the usual install dirs",
                      "pass --kicad-cli /path/to/kicad-cli to fix",
                      "this is NOT a pass: nothing confirmed the file loads"]
                     ).gap("whole check", GAP_NOT_RUN,
                           "no kicad-cli was found, so KiCad itself never "
                           "parsed this file",
                           "pass --kicad-cli /path/to/kicad-cli",
                           "whether this file loads in KiCad at all, and the "
                           "fp export svg cross-check of every letterform")
    if cfg.cli_major < MIN_KICAD_MAJOR:
        return Check("kicad-load", SKIP,
                     f"kicad-cli is version {cfg.kicad_version}, need "
                     f"{MIN_KICAD_MAJOR}+ -- this file is UNVERIFIED",
                     [f"using {cli}",
                      f"KiCad {cfg.cli_major} cannot parse a modern "
                      f"(version 20241229) footprint and would report a bogus "
                      f"failure, so the check was not run at all",
                      "pass --kicad-cli /path/to/kicad-10/kicad-cli to fix",
                      "this is NOT a pass"]
                     ).gap("whole check", GAP_NOT_RUN,
                           f"kicad-cli {cfg.kicad_version} is older than "
                           f"{MIN_KICAD_MAJOR} and cannot parse this format",
                           "pass --kicad-cli /path/to/kicad-10/kicad-cli",
                           "whether this file loads in KiCad at all, and the "
                           "fp export svg cross-check of every letterform")

    details = []
    no_plot = False
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
            no_plot = True

    c = Check("kicad-load", PASS, f"loads in KiCad {cfg.kicad_version}", details)
    if no_plot:
        # The load succeeded, so the LEVEL is a genuine pass -- but the plot
        # cross-check did not happen, and that cross-check is the only evidence
        # that the letterforms this harness measured are the letterforms KiCad
        # will image. A pass with that missing is a smaller pass than a pass
        # with it, and the report has to be able to tell them apart.
        c.gap("fp export svg", GAP_NOT_RUN,
              "--no-render: KiCad was not asked to plot the part",
              "drop --no-render",
              "the cross-check of every expanded letterform against KiCad's "
              "own plot -- the expansion is modelled but not corroborated")
    return c


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


def _point_in_loop(p, loop) -> bool:
    """Even-odd point-in-polygon. A point exactly on the boundary is not
    decided reliably, which is acceptable here: the callers ask only about art
    that stands clear of the edge by a measurable margin."""
    x, y = p
    inside = False
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            if x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
                inside = not inside
    return inside


def _area_outside_loop(pts, loop) -> bool:
    """True when a filled area lies WHOLLY outside `loop` -- no vertex inside
    it and no edge crossing it. Both halves are needed: a ring straddling the
    loop has no vertex inside, and a shape swallowing the loop has none either.
    """
    a = bbox_of(pts)
    b = bbox_of(loop)
    if a and b and (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3]):
        return True                      # bboxes disjoint; no need to pay for edges
    if any(_point_in_loop(p, loop) for p in pts):
        return False
    if _point_in_loop(loop[0], pts):
        return False                     # the loop is inside the area, not outside it
    for p1, p2 in edges_of(pts):
        for p3, p4 in edges_of(loop):
            if seg_seg_intersect(p1, p2, p3, p4):
                return False
    return True


def cutout_loops(fp: Footprint) -> list:
    """Closed Edge.Cuts loops that bound a HOLE rather than the board.

    Loop COUNT cannot tell an outline from a cutout, which is the assumption
    this replaces. A window part has exactly one closed loop too -- one hex
    routed clean through -- and its art sits outside that loop on purpose.
    Containment does tell them apart: art sits INSIDE a board outline and
    OUTSIDE a cutout. A loop that every filled area stands clear of bounds a
    hole the art surrounds, so it is not an extent the art can be measured
    against; asking whether the art fits inside the window it frames is the
    wrong question, and the answer is always no.
    """
    edge = [it for it in fp.items if "Edge.Cuts" in it.layers]
    loops = [lp for lp in closed_loops([it for it in edge if it.kind == "fp_line"])
             if len(lp) >= 3]
    areas = [it.pts for _, it in polys_of(fp) if len(it.pts) >= 3]
    if not areas or not loops:
        return []
    return [lp for lp in loops
            if all(_area_outside_loop(pts, lp) for pts in areas)]


def clearance_to_cut(fp: Footprint, loop) -> tuple[float, int] | None:
    """Closest approach of any filled area to a routed edge, and whose it is.
    For a window part this is the measurement that matters -- copper has to
    clear the cut, and containment never had anything to say about it."""
    best = None
    for i, it in polys_of(fp):
        if len(it.pts) < 2:
            continue
        for p1, p2 in edges_of(it.pts):
            for p3, p4 in edges_of(loop):
                d = seg_seg_dist(p1, p2, p3, p4)
                if best is None or d < best[0]:
                    best = (d, i)
    return best


def reference_extent(fp: Footprint):
    """An extent independent of the polygons being tested. Courtyard first; a
    single closed Edge.Cuts loop second, but ONLY once it has been shown to be
    a board outline and not a cutout -- see cutout_loops(). Several loops are
    deliberately NOT used either: they bound holes, not the art."""
    if fp.is_board:
        # On a BOARD the extent is the board. A courtyard bounds ONE placed
        # part, so measuring a whole board against a courtyard calls every
        # other part on it an escape -- 520 of them on the alpha coupon, all
        # of them false. What IS a defect here is geometry outside the routed
        # outline, because the router cuts it off.
        b = None
        for it in fp.items:
            if "Edge.Cuts" in it.layers:
                b = bbox_union(b, it.bbox())
        return (b, "Edge.Cuts board outline") if b else (None, None)
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
            if loops and loops[0] in cutout_loops(fp):
                return None, "Edge.Cuts cutout"
            b = None
            for it in edge:
                b = bbox_union(b, it.bbox())
            if b:
                return b, "Edge.Cuts board outline"
    return None, None


def closed_loops(line_items, tol=1e-4):
    """Chain fp_line / flattened fp_arc runs into closed loops.

    Needed because an Edge.Cuts slot's real feature size is the loop width,
    not the stroke width. Runs of more than two points (a flattened arc) chain
    on their endpoints and contribute every intermediate vertex to the loop,
    so a rounded outline measures as the rounded shape it is.
    """
    from collections import defaultdict
    adj = defaultdict(list)

    def key(p):
        return (round(p[0] / tol), round(p[1] / tol))

    segs = []                       # (a, b, forward-point-run without a)
    for it in line_items:
        if len(it.pts) < 2:
            continue
        a, b = it.pts[0], it.pts[-1]
        if key(a) == key(b):
            continue
        idx = len(segs)
        segs.append((a, b, list(it.pts)))
        adj[key(a)].append(idx)
        adj[key(b)].append(idx)

    used = [False] * len(segs)
    loops = []
    for s0 in range(len(segs)):
        if used[s0]:
            continue
        a, b, run = segs[s0]
        used[s0] = True
        chain = list(run)
        cur = b
        while True:
            nxt = None
            for idx in adj[key(cur)]:
                if not used[idx]:
                    p, q, r = segs[idx]
                    fwd = key(p) == key(cur)
                    nxt = (idx, q if fwd else p, r[1:] if fwd else r[-2::-1])
                    break
            if nxt is None:
                break
            used[nxt[0]] = True
            cur = nxt[1]
            chain.extend(nxt[2])
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
            thin.append(f"{item_label(i, it)} on {'/'.join(it.layers) or '?'} has "
                        f"{len(it.pts)} vertices")
        n = len(it.pts)
        for j in range(n):
            a, b = it.pts[j], it.pts[(j + 1) % n]
            if n > 1 and abs(a[0] - b[0]) < DUP_EPS and abs(a[1] - b[1]) < DUP_EPS:
                where = "closing point repeats the first" if j == n - 1 else \
                        f"vertices {j},{j+1} coincide"
                dups.append(f"{item_label(i, it)} on {'/'.join(it.layers) or '?'}: {where} "
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

    # A window part frames a hole. Report the hole and the one number that
    # governs it -- how close copper comes to the routed edge -- whichever
    # reference the escape test below ends up using. Containment cannot speak
    # to a cutout, so without this the class would go entirely unmeasured.
    cuts = cutout_loops(fp)
    for lp in cuts:
        cb = bbox_of(lp)
        near = clearance_to_cut(fp, lp)
        span = f"{cb[2]-cb[0]:.3f} x {cb[3]-cb[1]:.3f} mm" if cb else "?"
        details.append(
            f"Edge.Cuts cutout {span}: the art surrounds this hole rather than "
            f"sitting inside it, so it is NOT used as an extent"
            + (f"; closest approach of any filled area to the cut "
               f"{near[0]:.4f} mm (#{near[1]})" if near else ""))

    # bbox escape
    ref, ref_src = reference_extent(fp)
    if ref:
        esc = []
        for i, it in polys_of(fp):
            b = it.bbox()
            if not b:
                continue
            if fp.is_board and not any(layer_class(l) in
                                       ("silk", "mask", "copper", "buried")
                                       for l in it.layers):
                # A courtyard or a fab outline is ALLOWED to hang off the
                # board: an edge-mounted potentiometer's body does exactly
                # that, and the four "escapes" it produced on the product
                # board are the part being where the designer put it. What is
                # a defect is FABRICATED geometry past the routed outline,
                # because the router removes it.
                continue
            e = max(ref[0] - b[0], b[2] - ref[2], ref[1] - b[1], b[3] - ref[3])
            if e > cfg.outlier_mm:
                esc.append(f"{item_label(i, it)} on {'/'.join(it.layers) or '?'} escapes the "
                           f"{ref_src} by {e:.3f} mm")
        details.append(f"bbox escape measured against the {ref_src}"
                       + (" (fabricated layers only)" if fp.is_board else ""))
        if esc:
            level = worst(level, FAIL)
            tally["escapes extent"] = len(esc)
            problems += [f"ESCAPES EXTENT: {t}" for t in esc[:cfg.max_report]]
    elif ref_src == "Edge.Cuts cutout":
        details.append("no courtyard, and the only Edge.Cuts loop is a cutout "
                       "rather than a board outline, so there is no extent "
                       "independent of the art itself; ran lone-outlier "
                       "detection instead")
        outliers = _lone_outliers(fp, cfg)
        if outliers:
            level = worst(level, FAIL)
            tally["lone outlier"] = len(outliers)
            problems += outliers
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
        out.append(f"LONE OUTLIER: {item_label(i, it)} on {'/'.join(it.layers) or '?'} sits "
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

    if fp.is_board:
        # SCOPE, stated rather than assumed. The palette's recipe list says
        # which layers a piece of ART may draw on. A BOARD legitimately draws
        # on paste, courtyard, fab and user layers -- that is not off-palette
        # art, it is a board being a board. Judging a board against the art
        # recipe would produce a FAIL on every real file and teach the reader
        # to ignore this line. What is still a genuine defect on a board is a
        # layer name KiCad does not know, because KiCad rescues those silently
        # and whatever was drawn there is gone.
        unknown = [f"{l}({n})" for l, n in sorted(used.items())
                   if l not in KNOWN_LAYERS]
        declared = [l for l in fp.board_layers if l not in KNOWN_LAYERS]
        details = [f"layers drawn on: "
                   + ", ".join(f"{l}({n})" for l, n in sorted(used.items()))]
        details.append("board scope: layer LEGALITY is an art-palette question "
                       "and is not applied to a board; what is checked here is "
                       "that every layer name is one KiCad recognises")
        if declared:
            details.append(f"board layer table declares {len(declared)} "
                           f"non-standard layer name(s): {', '.join(declared)}")
        if unknown:
            return Check("layers", FAIL,
                         f"{len(unknown)} unknown-to-KiCad layer(s)",
                         details + [f"UNKNOWN layers: {', '.join(unknown)} -- "
                                    f"KiCad remaps these to 'Rescue' and "
                                    f"whatever is drawn on them is LOST"])
        if not used:
            return Check("layers", WARN, "the board draws nothing", details)
        return Check("layers", INFO,
                     f"{len(used)} layer(s) in use, all recognised by KiCad",
                     details)

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
    checked = skipped = skipped_pts = 0
    skipped_where: list[str] = []
    for i, it in polys_of(fp):
        pts = [p for j, p in enumerate(it.pts)
               if j == 0 or abs(p[0] - it.pts[j-1][0]) > DUP_EPS
               or abs(p[1] - it.pts[j-1][1]) > DUP_EPS]
        if len(pts) < 4:
            continue
        if len(pts) > cfg.max_poly_pts:
            skipped += 1
            skipped_pts += len(pts)
            skipped_where.append(f"{item_label(i, it)} on "
                                 f"{'/'.join(it.layers) or '?'} "
                                 f"({len(pts):,} vertices)")
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
            hits.append(f"{item_label(i, it)} on {'/'.join(it.layers) or '?'}: edges "
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
    c = Check("self-isect", level, head, details)
    if skipped:
        c.gap("large polygons", GAP_NOT_RUN,
              f"{skipped} polygon(s) exceed the {cfg.max_poly_pts:,}-vertex "
              f"limit and the O(n^2) pair scan was not run on them",
              "raise --max-poly-pts",
              f"{skipped} of {checked + skipped} polygon(s), "
              f"{skipped_pts:,} vertices: " + "; ".join(skipped_where[:3])
              + (f" (+{len(skipped_where)-3} more)"
                 if len(skipped_where) > 3 else ""))
    return c


# --------------------------------------------------------------------------
# Sweep declarations: judgement suspended, in the artefact, and counted
# --------------------------------------------------------------------------
#
# NARROW IS ENFORCED STRUCTURALLY, NOT BY GOOD INTENTIONS.
#
#   (a) Only THREE functions are ever handed this table: check_min_feature,
#       check_clearance and check_ink. check_kicad_load, check_size,
#       check_geometry, check_layers, check_self_intersection, check_colourway,
#       check_inventory, check_project_rules and every NOT MEASURED / SKIP path
#       never see it. A ladder that lands on "Rescue", self-intersects or
#       contradicts its own fab: tag fails exactly as it does today.
#   (b) One layer per declaration. On the beta coupon the same three footprints
#       carry deliberate sub-floor COPPER and five accidental sub-floor SILK
#       defects; a footprint- or keyword-granularity exemption would have
#       swallowed all five.
#   (c) A box, not a footprint. Sub-footprint granularity is unreachable
#       per-item -- no per-item field survives a KiCad round-trip -- so it is
#       reached geometrically. The box is clipped to the declaring footprint's
#       own geometry, so a footprint can never exempt anything outside itself.
#   (d) The box is also the ONLY key the ink measurement can be scoped by:
#       ink_measure.measure_layer() returns a Witness(value, x, y) with no part
#       identity at all.
#
# AND IT MAKES ONE CHECK SEE. check_min_feature keeps only the narrowest value
# per layer, so today the ladder's 0.0500 mm F.Cu rung occupies that slot and
# ANY other F.Cu defect between 0.05 and 0.0889 mm on beta is invisible. Exempt
# measurements are removed from that slot and tallied separately, so the
# reported minimum becomes the narrowest NON-EXEMPT feature.

SWEEP_TIGHTNESS = 1.25          # box area / fenced-geometry bbox area
SWEEP_BAND_USE = 1.0 / 3.0      # observed span below this fraction -> tighten


class SweepTable:
    """Every declaration on one file, plus what the run made of each.

    Construction NEVER silently drops a token: a malformed one raises
    sweep_decls.SweepError, which the caller turns into a FAIL check.
    """

    def __init__(self, fp: Footprint, cfg=None, enabled: bool = True):
        self.enabled = bool(enabled)
        self.is_board = bool(fp.is_board)
        self.cfg = cfg
        self.decls: list = []
        self.owners: dict = {}
        self._fp = fp
        self._ink_parts: dict = {}
        self._geo_cache: dict = {}
        for inst in fp.instances:
            ds = sweep_decls.from_tags(inst.tags, KNOWN_LAYERS)
            for d in ds:
                d.owner = inst.idx
                d.owner_name = inst.lib
                d.source = inst.source
                pl = inst.placement
                d.board_box = (d.box.transformed(pl.pt) if pl is not None
                               else d.box)
                self.decls.append(d)
            self.owners[inst.idx] = inst
        # Two declarations of the same (quantity, layer) may not overlap even
        # across footprints: exactly one may match a finding.
        for i, a in enumerate(self.decls):
            for b in self.decls[i + 1:]:
                if (a.quantity == b.quantity and a.layer == b.layer
                        and a.active_box.overlaps(b.active_box)):
                    raise sweep_decls.SweepError(
                        f"{a.owner_name}:{a.block} and {b.owner_name}:{b.block} "
                        f"both declare {a.quantity} on {a.layer} over "
                        f"overlapping boxes. A finding may match exactly one "
                        f"declaration")
        self._measure_fences(fp)
        # USABILITY IS DECIDED BEFORE ANY CHECK RUNS, and an unusable
        # declaration matches NOTHING. Deciding it afterwards would leave a
        # land-grab box FAILing the exempt check while still quietly pulling
        # every finding it claimed out of min-feature -- loud in one place and
        # silent in the one the reader is looking at.
        for d in self.decls:
            d.unusable_why = self._unusable_why(d, fp)

    def __bool__(self):
        return bool(self.decls)

    def _unusable_why(self, d, fp: Footprint) -> str:
        if getattr(d, "clipped_away", False):
            return ("the box lies entirely outside the declaring footprint's "
                    "own geometry -- a footprint can never exempt anything "
                    "outside itself")
        if d.n_fenced == 0:
            return (f"fences 0 item(s) of {d.owner_name} on {d.layer} -- a "
                    f"declaration over nothing is a typo or a land-grab, and "
                    f"in either case it decays")
        ratio = self._tightness_ratio(d)
        if ratio > SWEEP_TIGHTNESS + 1e-9:
            return (f"box is {ratio:.2f}x the bounding box of the geometry it "
                    f"fences, over the {SWEEP_TIGHTNESS:.2f}x limit -- a box "
                    f"drawn round more than the block it names is a land-grab")
        if self.cfg is None:
            return ""
        floor, _c, _p = _floor_for(d.layer, self.cfg.palette, fp.is_board)
        if floor is None:
            return (f"{d.layer} has no fabrication floor, so there is nothing "
                    f"here for a sweep to go under")
        if d.lo >= floor - 1e-12:
            return (f"lo {d.lo:.4f} mm is not under the {floor:.4f} mm floor, "
                    f"so this band exempts nothing that was ever a finding")
        return ""

    # -- fencing, tightness, containment ---------------------------------

    def _measure_fences(self, fp: Footprint):
        own_bb: dict = {}
        for it in fp.items:
            b = it.bbox()
            if b is None:
                continue
            own_bb[it.owner] = bbox_union(own_bb.get(it.owner), b)
        for d in self.decls:
            # CLIP FIRST. Everything below -- fencing, tightness, matching --
            # then works on a box that provably cannot reach outside the
            # footprint that declared it.
            d.owner_bbox = own_bb.get(d.owner)
            before = d.active_box.area
            clipped = d.active_box.clipped_to_bbox(d.owner_bbox)
            if clipped is None:
                d.clipped_away = True
            else:
                d.clipped_away = False
                if before - clipped.area > 1e-9:
                    d.notes.append(
                        f"box clipped to the declaring footprint's own "
                        f"geometry: {before:.3f} -> {clipped.area:.3f} mm2. A "
                        f"footprint can never exempt anything outside itself")
                d.board_box = clipped
            box = d.active_box
            fenced = None
            n = 0
            for it in fp.items:
                if it.owner != d.owner or d.layer not in it.layers:
                    continue
                b = it.bbox()
                if b is None or not box.contains_bbox(b):
                    continue
                n += 1
                fenced = bbox_union(fenced, b)
            d.n_fenced = n
            d.fenced_area = ((fenced[2] - fenced[0]) * (fenced[3] - fenced[1])
                             if fenced else 0.0)

    def _tightness_ratio(self, d) -> float:
        if d.fenced_area <= 1e-12:
            return float("inf")
        return d.active_box.area / d.fenced_area

    # -- matching --------------------------------------------------------

    def _candidates(self, owner: int, layer: str, quantity: str):
        if not self.enabled:
            return
        for d in self.decls:
            if (d.quantity == quantity and d.layer == layer
                    and d.owner == owner and not d.unusable_why):
                yield d

    def judge_item(self, owner: int, layer: str, quantity: str,
                   value: float, bbox, where: str):
        """-> (decl, 'exempt' | 'out-of-band') or (None, None).

        `bbox` must be the item's WHOLE extent: a declaration fences a region,
        and half an item inside it is not inside it.
        """
        for d in self._candidates(owner, layer, quantity):
            if not d.active_box.contains_bbox(bbox):
                continue
            if d.in_band(value):
                d.observe(value)
                return d, "exempt"
            if value < d.lo:
                d.out_of_band.append((value, where))
                return d, "out-of-band"
        return None, None

    def judge_pair(self, a_owner: int, b_owner: int, layer: str,
                   value: float, bb_a, bb_b, where: str, record: bool = True):
        """A clearance pair. BOTH features must belong to the declaring
        footprint and both must lie wholly inside the box.

        `record=False` is a PROBE: the margin pass walks the same geometry a
        second time with a wider reach, and letting it observe again would
        double the exempt count and widen the observed range with values the
        judging pass never saw.
        """
        if a_owner != b_owner:
            return None, None
        for d in self._candidates(a_owner, layer, "gap"):
            if not (d.active_box.contains_bbox(bb_a)
                    and d.active_box.contains_bbox(bb_b)):
                continue
            if d.in_band(value):
                if record:
                    d.observe(value)
                return d, "exempt"
            if value < d.lo:
                if record:
                    d.out_of_band.append((value, where))
                return d, "out-of-band"
        return None, None

    # -- ink witnesses ---------------------------------------------------

    def set_ink_parts(self, layer: str, parts):
        self._ink_parts[layer] = list(parts)

    def _part_geom(self, part):
        g = self._geo_cache.get(id(part))
        if g is None:
            try:
                g = ink_measure.build_geometry([part])
            except Exception:
                g = False
            self._geo_cache[id(part)] = g
        return g

    def _foreign_at(self, layer: str, x: float, y: float, radius: float,
                    owner: int) -> str:
        """The label of a part near (x, y) that is NOT the declaring
        footprint's, or "" if every contributor there is its own.

        THE ANTI-COLLISION RULE. If a foreign part contributes to the merged
        region at a witness, the finding is not the ladder's to claim: the
        neck or gap being measured is between the ladder and something else,
        and that is a real spacing question. ONE foreign contributor voids the
        match.
        """
        for p in self._ink_parts.get(layer, ()):
            if getattr(p, "owner", -1) == owner:
                continue
            b = bbox_of(p.pts)
            if b is None:
                continue
            if p.width:
                b = bbox_inflate(b, p.width / 2.0)
            if (x < b[0] - radius or x > b[2] + radius
                    or y < b[1] - radius or y > b[3] + radius):
                continue
            g = self._part_geom(p)
            if g is False or g is None:
                return p.label          # cannot prove it is far: not exempt
            try:
                from shapely.geometry import Point as _Pt
                if g.distance(_Pt(x, y)) <= radius:
                    return p.label
            except Exception:
                return p.label
            continue
        return ""

    def judge_point(self, layer: str, quantity: str, value: float,
                    x: float, y: float, radius: float, where: str):
        """An ink witness, which has coordinates and no item identity."""
        if not self.enabled:
            return None, None
        for d in self.decls:
            if (d.quantity != quantity or d.layer != layer or d.unusable_why
                    or not d.active_box.contains_point((x, y))):
                continue
            if not (d.in_band(value) or value < d.lo):
                continue
            foreign = self._foreign_at(layer, x, y, radius, d.owner)
            if foreign:
                d.notes.append(
                    f"a witness at ({x:.3f}, {y:.3f}) was NOT exempted: "
                    f"{foreign} is within {radius:.4f} mm of it and does not "
                    f"belong to {d.owner_name}")
                return None, None
            if d.in_band(value):
                d.observe(value)
                return d, "exempt"
            d.out_of_band.append((value, where))
            return d, "out-of-band"
        return None, None

    def mark_exercised(self, layer: str, quantities=None):
        """A check says: I really measured this layer.

        Without it a declaration on a layer the check SKIPPED would report as
        stale, which reads as "delete me" when the truth is "nothing looked".
        """
        for d in self.decls:
            if d.layer == layer and (quantities is None
                                     or d.quantity in quantities):
                d.exercised = True

    # -- the report ------------------------------------------------------

    def render(self, cfg, fp: Footprint) -> Check:
        """One line per declaration, always, whether it matched or not.

        Nothing is removed from the run: findings are MOVED, counted and
        attributed. A run where judgement was suspended must never be
        byte-similar to one where it was not.
        """
        details, problems = [], []
        level = INFO
        n_exempt = n_stale = 0
        rows = []
        gaps: list[Gap] = []
        for d in sorted(self.decls, key=lambda z: (z.owner_name, z.block,
                                                   z.quantity, z.layer)):
            floor, cls, _prov = _floor_for(d.layer, cfg.palette, fp.is_board)
            state, why, lv = self._state(d, floor)
            if state == "USED":
                n_exempt += d.n_matched
            if state == "STALE":
                n_stale += 1
            if state == "NOT EXERCISED" and lv == SKIP:
                # The declaration says "this rung is deliberately under the
                # floor". The check that would have measured the rung did not
                # run, so the artefact's claim about itself is UNTESTED -- and
                # an untested claim in a calibration ladder is the whole thing
                # the ladder exists to produce.
                gaps.append(Gap(
                    "exempt", f"{d.block} {d.quantity} on {d.layer}",
                    GAP_NOT_RUN,
                    "the check that would judge this declaration did not run, "
                    "so the declaration proves nothing",
                    "run the check this declaration is about",
                    f"the artefact declares {d.quantity} {d.band_str()} mm on "
                    f"{d.layer} and NOTHING in this run measured whether that "
                    f"is what it actually built"))
            level = worst(level, lv)
            head = (f"  {d.block:<10} {d.layer:<8} {d.quantity:<6} "
                    f"{d.band_str():<14} {d.active_box}  "
                    f"fences {d.n_fenced} item(s)  [{state}]")
            body = [f"      {why}"] if why else []
            if d.n_matched:
                body.append(f"      {d.n_matched} exempt, observed "
                            f"{d.obs_lo:.6f}..{d.obs_hi:.6f}   "
                            f"ref {d.ref}   [{d.owner_name}, {d.source}]")
                # Measured against the part of the band that could EVER have
                # matched: a value above the floor was never a finding, so the
                # band above the floor is inert and nagging about it would be
                # nagging about nothing.
                cap = d.hi if floor is None else min(d.hi, floor)
                usable = cap - d.lo
                span = (d.obs_hi - d.obs_lo) / usable if usable > 1e-12 else 1.0
                if span < SWEEP_BAND_USE:
                    body.append(
                        f"      declared {d.band_str()}, of which "
                        f"{d.lo:.4f}..{cap:.4f} is under the "
                        f"floor and could ever match; only "
                        f"{d.obs_lo:.4f}..{d.obs_hi:.4f} observed "
                        f"({span * 100:.0f}% of it) -- tighten it")
            else:
                body.append(f"      0 exempt   ref {d.ref}   "
                            f"[{d.owner_name}, {d.source}]")
            body.append(f"      tightness {self._tightness_ratio(d):.2f}x "
                        f"(box {d.active_box.area:.3f} mm2 / fenced "
                        f"{d.fenced_area:.3f} mm2, limit "
                        f"{SWEEP_TIGHTNESS:.2f}x)")
            body.append(f"      token: {d.token}")
            for n in d.notes[:cfg.max_report]:
                body.append(f"      ! {n}")
            for v, w in d.out_of_band[:cfg.max_report]:
                problems.append(
                    f"OUT OF DECLARED BAND: {d.block} declares "
                    f"{d.quantity} {d.band_str()} mm on {d.layer} and a "
                    f"measurement came back {v:.6f} mm, under its own lo -- "
                    f"{w}. The part promised a range and broke its own "
                    f"promise, which is worse than never promising")
                level = worst(level, FAIL)
            if state in ("VOID",):
                problems.append(f"DECLARATION OVER NOTHING: {d.block} "
                                f"{d.quantity} on {d.layer} -- {why}")
            rows.append((head, body))
            details.append(head)
            details += body
        if not self.enabled:
            details.insert(0, "NOT HONOURED (--no-sweep): every declaration "
                              "below is listed and none of it is applied. "
                              "Refusing to honour is available; hiding is not")
        n_ex_total = sum(d.n_matched for d in self.decls) if self.enabled else 0
        head = (f"{len(self.decls)} declaration(s), {n_ex_total} finding(s) "
                f"exempt, {n_stale} stale")
        if not self.enabled:
            head += "  -- NOT HONOURED (--no-sweep)"
        c = Check("exempt", level, head, details + problems)
        c.exempt = n_ex_total
        c.stale = n_stale
        c.exemptions = [self._as_json(d, cfg, fp) for d in self.decls]
        c.gaps = gaps
        return c

    def _state(self, d, floor):
        """USED / STALE / VOID / NOT EXERCISED / UNUSABLE, and why.

        The unusable cases were all decided before the run and nothing matched
        them, so these branches only NAME what already happened.
        """
        if d.unusable_why:
            kind = "VOID" if d.n_fenced == 0 else "UNUSABLE"
            return kind, (d.unusable_why + ". It exempted nothing: every "
                          "finding inside it was judged normally"), FAIL
        if not self.enabled:
            return "NOT HONOURED", "--no-sweep: listed, not applied", INFO
        if not d.exercised:
            if not self.is_board and d.quantity == "vanish":
                # The region measurement is a BOARD check. Saying "this proves
                # nothing" is true, but on a .kicad_mod it is true of every run
                # forever, and a permanent WARN is a WARN nobody reads.
                return ("NOT EXERCISED",
                        "the ink-floor region measurement is a board check and "
                        "does not run on a .kicad_mod, so nothing here has "
                        "tested this claim. Verify the board", INFO)
            return ("NOT EXERCISED",
                    "the check that would judge this layer did not run; this "
                    "declaration proves nothing", SKIP)
        if d.hi < floor - 1e-12:
            return ("STALE",
                    f"the whole band {d.band_str()} is under the "
                    f"{floor:.4f} mm floor, so the block no longer BRACKETS "
                    f"the floor -- it has stopped answering its question. The "
                    f"profile moved, or the part did", WARN)
        if d.n_matched == 0:
            return ("STALE",
                    f"exempted nothing -- the block no longer sweeps below the "
                    f"{floor:.4f} mm floor (the part changed, or the floor "
                    f"moved). Delete the declaration or fix the part", WARN)
        return "USED", "", INFO

    def _as_json(self, d, cfg, fp):
        floor, _c, _p = _floor_for(d.layer, cfg.palette, fp.is_board)
        state, why, _lv = self._state(d, floor)
        x0, y0, x1, y1 = d.active_box.extents
        return {
            "token": d.token, "block": d.block, "layer": d.layer,
            "quantity": d.quantity, "lo": d.lo, "hi": d.hi,
            "box": [x0, y0, x1, y1], "ref": d.ref,
            "footprint": d.owner_name, "source": d.source,
            "matched": d.n_matched, "observed_min": d.obs_lo,
            "observed_max": d.obs_hi, "fenced_items": d.n_fenced,
            "tightness": self._tightness_ratio(d),
            "state": state, "why": why,
            "out_of_band": [{"value": v, "where": w} for v, w in d.out_of_band],
        }


# --- 6. minimum feature -----------------------------------------------------

def _floor_for(layer: str, pal: Palette,
               board: bool = False) -> tuple[float | None, str, bool]:
    c = layer_class(layer)
    if c == "other":
        return None, c, False
    if board and c == "buried":
        # On a FOOTPRINT, In*.Cu is buried tone art and the number that matters
        # is how coarse a feature has to be to read through the laminate -- the
        # PROVISIONAL 0.50 mm the palette doc will not commit to.
        #
        # On a BOARD, In*.Cu is where the router put the power planes. Holding
        # a 0.20 mm inner trace up against a 0.50 mm art-visibility guess would
        # fail every functional board ever drawn, and a check that fails
        # everything is as useless as one that fails nothing. So the FLOOR
        # applied here is the copper etch limit, which is what decides whether
        # the layer images at all, and the visibility number is reported
        # separately as an advisory by check_ink().
        return pal.floors["copper"], "copper", False
    return pal.floors[c], c, (c == "buried" and pal.buried_provisional)


def _is_convex(pts) -> bool:
    """True when the polygon has no reflex vertex.

    This is the whole question for min_width(): a rotating caliper on the
    convex hull is EXACT for a convex polygon and an over-estimate for any
    other, and over-estimating a feature width is under-reporting risk.
    """
    n = len(pts)
    if n < 4:
        return True
    sign = 0
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        cx, cy = pts[(i + 2) % n]
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cr) < 1e-15:
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


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
    board = bool(fp.is_board)
    # Concave filled areas whose width this function REFUSES to claim. See the
    # deferral note where they are reported.
    deferred: dict[str, list[float]] = {}
    ink_done = set(getattr(cfg, "ink_measured_layers", ()) or ())
    sweeps = getattr(cfg, "sweeps", None)
    # Exempt measurements, per layer: (value, desc, block). Kept OUT of
    # `narrowest` on purpose -- that slot holds one value per layer, so leaving
    # a declared 0.0500 mm rung in it makes every other sub-floor feature on
    # that layer invisible. Removing it is what turns this check from blind to
    # sighted on F.Cu.
    exempted: dict[str, list] = {}
    cur_item = {"i": 0, "it": None}
    gaps: list[Gap] = []

    def note(layer, w, desc):
        if w is None or w <= 0:
            return
        it = cur_item["it"]
        fl = _floor_for(layer, pal, board)[0]
        # ONLY A FINDING CAN BE EXEMPTED. A measurement above the floor was
        # never going to be reported, so routing it through the declaration
        # would inflate the exempt count with things nobody was judging AND
        # pull a perfectly good measurement out of the narrowest slot.
        if (sweeps is not None and it is not None
                and fl is not None and w < fl - 1e-9):
            bb = it.bbox()
            d, verdict = sweeps.judge_item(
                it.owner, layer, "width", w, bb,
                f"{layer} {desc} measured {w:.6f} mm")
            if verdict == "exempt":
                exempted.setdefault(layer, []).append((w, desc, d.block))
                return
            if verdict == "out-of-band":
                return          # reported by the exempt check, attributed
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
        if _floor_for(layer, pal, board)[0] is None:
            return
        unmeasured.setdefault(layer, []).append(why)

    for i, it in enumerate(fp.items):
        cur_item["i"], cur_item["it"] = i, it
        for layer in it.layers:
            if layer == "Edge.Cuts":
                continue  # handled separately: stroke width is not the feature
            # On a mask layer the drawn shape is the HOLE, not the material, so
            # its width is an aperture and the only mask number in hand is a
            # dam. Routed to note_opening() and never compared to it.
            put = note_opening if layer_class(layer) == "mask" else note
            if it.kind == "fp_line":
                put(layer, it.width, f"{item_label(i, it)} stroke")
            elif it.kind in ("fp_poly", "fp_rect"):
                if it.filled:
                    w = min_width(it.pts)
                    if len(it.pts) > 4:
                        concave_caveat = True
                    if board and not _is_convex(it.pts):
                        # THE HOLE THIS CHECK USED TO HAVE. min_width() is a
                        # rotating caliper on the CONVEX HULL. On a concave
                        # outline it answers a different question -- for a
                        # traced letterform it returns the glyph's overall
                        # width, roughly 1.2 mm, while the stem the glyph is
                        # made of is 0.117 mm. Reporting that as "narrowest
                        # feature ... above floor" would be a green check
                        # written over the exact defect a board verifier
                        # exists to find. So it is NOT reported as a
                        # measurement here; it is handed to check_ink(), which
                        # measures the inscribed width of the region.
                        deferred.setdefault(layer, []).append(w)
                    else:
                        put(layer, w, f"{item_label(i, it)} min width")
                else:
                    put(layer, it.width, f"{item_label(i, it)} stroke")
            elif it.kind == "fp_circle":
                if it.filled and it.hole_r > 0:
                    # A via or a drilled round pad: the feature that can fail
                    # is the ANNULAR RING, not the pad diameter.
                    put(layer, it.char_h - it.hole_r,
                        f"{item_label(i, it)} annular ring "
                        f"(({2*it.char_h:.3f} - {2*it.hole_r:.3f})/2)")
                else:
                    put(layer, it.width if not it.filled else 2 * it.char_h,
                        f"{item_label(i, it)}")
            elif it.kind == "pad":
                if it.stale:
                    cannot(layer, f"{item_label(i, it)}: {it.stale}")
                    continue
                if it.stale_hole and layer_class(layer) in ("copper", "buried"):
                    continue        # an unplated hole: no copper ring to judge
                if it.hole_r > 0 and it.char_h > 0:
                    put(layer, it.char_h - it.hole_r,
                        f"{item_label(i, it)} annular ring")
                elif it.filled:
                    put(layer, min_width(it.pts), f"{item_label(i, it)} min width")
            elif it.kind == "fp_arc":
                put(layer, it.width, f"{item_label(i, it)} stroke")
            elif it.kind in ("fp_text", "fp_text_box", "property"):
                if it.hidden:
                    continue        # never plotted, so never fabricated
                # EXPAND, then measure. Echoing it.thickness here WAS the
                # defect: it hands back the attribute the emitter wrote, so a
                # text item could never disagree with the file that made it.
                ink = expand_text(it)
                if not ink.ok:
                    cannot(layer, f"{item_label(i, it)} {it.text[:18]!r}: {ink.why}")
                    continue
                w = _ink_min_width(ink)
                if w is None:
                    # Measured, and the answer is "none". An empty or all-space
                    # string draws nothing, so there is no feature here to be
                    # too fine -- said out loud so it cannot be confused with
                    # the NOT MEASURED case below, but not a finding.
                    no_ink.append(f"  {layer:<10} {item_label(i, it)} "
                                  f"{it.text[:18]!r} draws no ink at all "
                                  f"(nothing to measure)")
                    continue
                put(layer, w, f"{item_label(i, it)} expanded letterforms "
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

    for layer in sorted(deferred):
        ws = deferred[layer]
        floor, cls, prov = _floor_for(layer, pal, board)
        ub = min(ws)
        if layer in ink_done:
            details.append(
                f"  {layer:<10} {len(ws)} concave filled area(s): width NOT "
                f"measured here -- min_width() is a convex-hull caliper and "
                f"over-states a concave outline (upper bound {ub:.4f} mm). "
                f"Measured for real by the ink-floor check below")
        else:
            level = worst(level, SKIP)
            problems.append(
                f"NOT MEASURED: {layer} has {len(ws)} concave filled area(s) "
                f"whose narrowest feature is UNKNOWN. A convex-hull caliper "
                f"over-states them (upper bound {ub:.4f} mm, which is NOT a "
                f"measurement of the ink), and the ink-floor check did not run "
                f"on this layer, so nothing here measured them. This is the "
                f"case that shipped 0.117 mm silk past a green run")
            gaps.append(Gap(
                "min-feature", layer, GAP_NOT_RUN,
                "concave filled areas cannot be measured by a convex-hull "
                "caliper, and the ink-floor check did not run on this layer",
                "run the ink-floor check (shapely, and not --no-ink)",
                f"{len(ws)} concave filled area(s) on {layer}; the narrowest "
                f"feature on each is UNKNOWN, bounded above by {ub:.4f} mm"))

    n_exempt = 0
    for layer in sorted(set(narrowest) | set(exempted)):
        if sweeps is not None:
            sweeps.mark_exercised(layer, ("width",))
    for layer in sorted(exempted):
        rows = sorted(exempted[layer])
        n_exempt += len(rows)
        floor, cls, _p = _floor_for(layer, pal, board)
        by_block: dict[str, list] = {}
        for w, desc, block in rows:
            by_block.setdefault(block, []).append((w, desc))
        for block, ws in sorted(by_block.items()):
            details.append(
                f"  {layer:<10} {len(ws)} measurement(s) EXEMPT by declaration "
                f"[{block}], {ws[0][0]:.4f}..{ws[-1][0]:.4f} mm against the "
                f"{floor:.4f} mm floor -- and removed from this layer's "
                f"narrowest slot, so the number below is the narrowest "
                f"NON-EXEMPT feature")
            for w, desc in ws[:cfg.max_report]:
                details.append(f"               {w:.4f} mm  [{desc}]")
            if len(ws) > cfg.max_report:
                details.append(f"               (+{len(ws)-cfg.max_report} more)")

    for layer in sorted(narrowest):
        w, desc = narrowest[layer]
        floor, cls, prov = _floor_for(layer, pal, board)
        tag = f"  {layer:<10} narrowest {w:.4f} mm  [{desc}]"
        if floor is None:
            details.append(tag + "  (no fabrication floor for this layer)")
            continue
        mark = f"{floor:.4f} mm{' PROVISIONAL' if prov else ''}"
        if prov:
            # NO PUBLISHED FLOOR. docs/pcb-palette.md states no buried-tone
            # number at all; FLOOR_BURIED is a guess this file made up, and
            # cal_buried exists precisely because nobody knows it yet. Passing
            # a feature against an invented limit is not a measurement against
            # a limit, and the run must not be able to call it one.
            gaps.append(Gap(
                "min-feature", layer, GAP_UNJUDGED,
                f"the buried-tone floor ({floor:.2f} mm) is PROVISIONAL -- "
                f"docs/pcb-palette.md publishes no number for it and this one "
                f"is a guess made by this harness",
                "--floor-buried <mm> once cal_buried has been read, which "
                "also marks the number as no longer provisional",
                f"{layer}: the narrowest feature ({w:.4f} mm) was compared "
                f"against an invented limit, so neither a pass nor a fail on "
                f"this layer means anything yet"))
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
            gaps.append(Gap(
                "min-feature", layer, GAP_UNJUDGED,
                f"no profile in tools/fab_profiles.py publishes a minimum "
                f"mask OPENING, and this one ({w:.4f} mm) is finer than the "
                f"{dam:.4f} mm dam, the finest mask feature the process "
                f"states anywhere",
                "ask the fabricator what their minimum mask opening is, "
                "before ordering",
                f"{layer}: the narrowest opening is outside every number "
                f"this process publishes, so nothing here judged it"))

    details += no_ink
    for layer in sorted(unmeasured):
        why = unmeasured[layer]
        level = worst(level, SKIP)
        problems.append(f"NOT MEASURED: {layer} has {len(why)} item(s) whose "
                        f"geometry could not be derived, so the narrowest "
                        f"feature on this layer is UNKNOWN -- which is not the "
                        f"same as clean: " + "; ".join(why[:3])
                        + (f" (+{len(why)-3} more)" if len(why) > 3 else ""))
        gaps.append(Gap(
            "min-feature", layer, GAP_NOT_RUN,
            f"{len(why)} item(s) on this layer have geometry this harness "
            f"could not derive: " + "; ".join(why[:3])
            + (f" (+{len(why)-3} more)" if len(why) > 3 else ""),
            "model the construct, or remove it from the artwork",
            f"{layer}: the narrowest feature is UNKNOWN, not clean"))

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
        # Arcs close outlines too. A coupon whose corners are gr_arc has no
        # closed loop at all if only straight segments are chained, and "no
        # closed loop found" over a perfectly good hexagon is a false alarm
        # that teaches the reader to skip this line. The arc arrives already
        # flattened, so its endpoints chain like any other run.
        loops = closed_loops([it for it in edge_items
                              if it.kind in ("fp_line", "fp_arc")])
        for it in edge_items:
            if it.kind in ("fp_poly", "fp_rect") and len(it.pts) >= 3:
                loops.append(it.pts)
        if not loops:
            details.append("  Edge.Cuts  present but no closed loop found -- slot "
                           "width NOT checked (open outline?)")
            level = worst(level, WARN)
        # WHICH LOOP IS THE BOARD. The corner rule depends on which side of a
        # loop the material lies (see _sharp_corners), so the outermost loop --
        # the one whose bbox contains every other -- is treated as the outline
        # and the rest as holes. With no containment relation every loop is a
        # hole, which is the art-footprint case this check grew up on.
        boxes = [bbox_of(lp) for lp in loops]
        outer = None
        for k, b in enumerate(boxes):
            if b is None:
                continue
            if all(j == k or (b[0] <= o[0] and b[1] <= o[1]
                              and b[2] >= o[2] and b[3] >= o[3])
                   for j, o in enumerate(boxes) if o is not None):
                outer = k
                break
        for k, loop in enumerate(loops):
            edge_judged += 1
            w = min_width(loop)
            is_outline = (k == outer and len(loops) >= 1 and fp.is_board)
            if is_outline:
                details.append(f"  Edge.Cuts  loop {k} is the OUTLINE, "
                               f"{w:.3f} mm across at its narrowest")
            elif w < pal.floors["edge"] - 1e-9:
                level = worst(level, WARN)
                problems.append(f"UNROUTABLE: Edge.Cuts loop {k} is {w:.3f} mm "
                                f"across, under the {pal.floors['edge']:.2f} mm "
                                f"minimum slot width (= router bit diameter)")
            else:
                details.append(f"  Edge.Cuts  loop {k} min width {w:.3f} mm "
                               f"(floor {pal.floors['edge']:.2f} mm)")
            sharp = _sharp_corners(loop, cutout=not is_outline)
            if sharp:
                level = worst(level, WARN)
                problems.append(
                    f"SHARP CORNER: Edge.Cuts loop {k} has {sharp} "
                    + ("REFLEX corner(s) -- a notch cut into the board outline"
                       if is_outline else
                       f"corner(s) turning >{180-EDGE_SHARP_CORNER_DEG:.0f} deg")
                    + " -- an internal corner cannot be cut sharper than the "
                      "bit radius (0.8-1.0 mm) and the fab will fillet it")

    if concave_caveat:
        details.append("  note: min width is a rotating caliper on the CONVEX "
                       "HULL. That is exact for a convex outline and an "
                       "OVER-estimate for a concave one -- i.e. it under-"
                       "reports risk on concave shapes, which is why a board's "
                       "concave filled areas are deferred to the ink-floor "
                       "check instead of being judged here")
    if (pal.buried_provisional and not board
            and any(layer_class(l) == "buried" for l in narrowest)):
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
        gaps.append(Gap(
            "min-feature", "whole check", GAP_VACUOUS,
            "no layer in this file produced a feature width, so no floor was "
            "ever applied to anything",
            "check that the artwork is on the layers you think it is",
            "every fabrication floor: this check compared 0 measurements"))
    if n_exempt:
        # The level is NOT touched by exempt findings: an exemption moves a
        # finding, it never changes how bad the rest of the check was.
        head += f" ({n_exempt} exempt by declaration)"
    c = Check("min-feature", level, head, details + problems)
    c.gaps = gaps
    return c


def _signed_area2(loop) -> float:
    s = 0.0
    n = len(loop)
    for i in range(n):
        x1, y1 = loop[i]
        x2, y2 = loop[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s


def _sharp_corners(loop, cutout: bool = True) -> int:
    """Corners the router physically cannot cut, counted.

    THE RULE IS ABOUT THE MATERIAL, NOT THE LOOP. A bit of radius R cutting
    along a path leaves a fillet wherever the MATERIAL wraps around it -- a
    notch, a slot end, an inside corner. Where the material comes to a point
    the bit passes on the outside and the corner comes out as drawn.

    Which of those a vertex is depends on which side of the loop the material
    is on, and that flips between the two kinds of loop:

      cutout=True   the loop encloses a HOLE, so the material is outside it and
                    a vertex the loop turns sharply AT is an inside corner of
                    the material. This is every Edge.Cuts loop in an art
                    footprint, and it is the case this check was written for.
      cutout=False  the loop is the BOARD OUTLINE, material inside. Now a sharp
                    convex vertex is a corner of the board -- routed from the
                    outside, achievable, and flagging it called all four
                    corners of every rectangular board unroutable. What is
                    unroutable here is the opposite: a REFLEX vertex, a notch
                    cut into the board, which the bit fillets.

    The tolerance is not slack, it is the difference between a corner and a
    rounding error. A hexagonal coupon outline written as 27.135462 / 54.270925
    has vertices a nanometre off regular, which puts its 120.0 degree corners
    at 119.9999996; a bare `< 120` then reports two unroutable corners on a
    shape a router cuts without noticing.
    """
    n = len(loop)
    if n < 3:
        return 0
    ccw = _signed_area2(loop) > 0
    limit = 180 - EDGE_SHARP_CORNER_DEG - EDGE_CORNER_EPS_DEG
    count = 0
    for i in range(n):
        a, b, c = loop[(i - 1) % n], loop[i], loop[(i + 1) % n]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cosang = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (l1 * l2)))
        ang = math.degrees(math.acos(cosang))          # 0..180, unsigned
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        convex = (cross > 0) == ccw                    # convex w.r.t. the loop
        interior = ang if convex else 360.0 - ang
        if cutout:
            if interior < limit:
                count += 1
        else:
            if interior > 360.0 - limit:
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
    net: str = ""                    # KiCad net number, "" for none
    owner: int = -1                  # footprint instance, for sweep matching


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

    cur = {"net": "", "owner": -1}

    def add(layer, label, pts, width, closed, from_text=False):
        b = bbox_of(pts)
        if b is None:
            return
        if width:
            b = bbox_inflate(b, width / 2.0)
        by_layer[layer].append(Feat(label, edges_bb_of(pts, closed), width, b,
                                    from_text, cur["net"], cur["owner"]))

    for i, it in enumerate(fp.items):
        cur["net"] = it.net
        cur["owner"] = it.owner
        for l in it.layers:
            if layer_class(l) not in ("silk", "mask", "copper", "buried"):
                continue
            if it.kind == "fp_line":
                add(l, item_label(i, it), it.pts, it.width, False)
            elif it.kind in ("fp_poly", "fp_rect"):
                add(l, item_label(i, it), it.pts, it.width, True)
            elif it.kind == "fp_circle":
                # Item stashes the radius in char_h; pts are the bbox corners.
                cx = (it.pts[0][0] + it.pts[2][0]) / 2.0
                cy = (it.pts[0][1] + it.pts[2][1]) / 2.0
                add(l, item_label(i, it), _circle_pts(cx, cy, it.char_h),
                    0.0 if it.filled else it.width, True)
            elif it.kind == "pad":
                if it.stale:
                    excluded[l].append(f"{item_label(i, it)}: {it.stale}")
                    continue
                if it.stale_hole and layer_class(l) in ("copper", "buried"):
                    continue        # an unplated hole: no copper to keep clear of
                # The drill is a hole INSIDE the pad. The distance from its rim
                # to the pad edge is the annular ring, which is a WIDTH and is
                # judged as one by check_min_feature; feeding it to a gap check
                # would report the same number under the wrong name.
                add(l, item_label(i, it), it.pts, 0.0, True)
            elif it.kind in ("fp_text", "fp_text_box", "property"):
                if it.hidden:
                    continue        # never plotted, so never fabricated
                ink = expand_text(it)
                if not ink.ok:
                    excluded[l].append(f"{item_label(i, it)} {it.text[:14]!r}: "
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
                    add(l, f"{item_label(i, it)} stroke {k} ({it.text[:10]!r})",
                        ch, ink.width, False, from_text=True)
            else:
                excluded[l].append(f"{item_label(i, it)}: this shape is not modelled "
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

# How many un-examined candidate pairs to count before giving up and reporting
# a lower bound instead. Counting is index-only -- no geometry, no _feature_gap
# -- so this is cheap next to the work the check already did before it ran out.
_DRAIN_CAP = 20_000_000


def _drain_count(gen, cap: int) -> tuple[int, bool]:
    """How many items are LEFT in a generator that was stopped early.

    -> (count, capped). `capped` True means the real number is at least
    `count`, and the report must say so rather than quote a total it does not
    have. Existing to answer requirement 4: a measurement that ran out of
    budget has to say how much of the board it did not measure, and "how much"
    for the gap check is exactly this.
    """
    n = 0
    for _ in gen:
        n += 1
        if n >= cap:
            return n, True
    return n, False


def _narrowest_separated_gap(feats: list, reach: float, budget: int,
                             skip=None):
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
        if skip is not None and skip(fa, fb, g):
            # A declared sweep gap. Left out of the MARGIN number as well as
            # out of the verdict, because "narrowest gap 0.016 mm, +-0.072 mm
            # of margin" is not a sentence about the part the reader is being
            # asked to judge.
            continue
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
        return Check("clearance", SKIP, "skipped (--no-clearance)",
                     ["nothing measured any gap on any layer; this is not a "
                      "pass"]
                     ).gap("whole check", GAP_NOT_RUN,
                           "--no-clearance", "drop --no-clearance",
                           "every mask dam and every copper-to-copper spacing "
                           "on every layer of this file")

    by_layer, excluded, expanded = clearance_features(fp, cfg)
    sweeps = getattr(cfg, "sweeps", None)

    def _sweep_gap(fa, fb, g, record=True):
        """-> (decl, verdict). Both features must be the declaring
        footprint's own and both wholly inside its box."""
        if sweeps is None:
            return None, None
        return sweeps.judge_pair(
            fa.owner, fb.owner, _sweep_layer[0], g, fa.bb, fb.bb,
            f"{_sweep_layer[0]} {fa.label} vs {fb.label} measured {g:.6f} mm",
            record=record)

    _sweep_layer = [""]

    details, problems = [], []
    level = PASS
    n_skipped = 0
    n_exempt_total = 0
    n_tested_layers = 0
    n_untested_layers = 0
    total_pairs = 0
    gaps: list[Gap] = []

    if expanded[0]:
        details.append(f"  text       {expanded[0]} text item(s) expanded into "
                       f"{expanded[1]} stroke path(s), each one a feature in "
                       f"the comparison below")

    for layer in sorted(by_layer):
        feats = by_layer[layer]
        _sweep_layer[0] = layer
        floor, cls, prov = _floor_for(layer, cfg.palette, fp.is_board)
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
            gaps.append(Gap(
                "clearance", layer, GAP_VACUOUS,
                f"{n} feature(s) form 0 pairs, so the {floor:.4f} mm {cls} "
                f"limit was never applied to anything on this layer",
                "nothing to fix in the tool -- but a layer whose spacing was "
                "never tested has not been cleared for spacing",
                f"{layer}: 0 of 0 pair(s) compared. Note this does NOT mean "
                f"the layer is clean; a single polygon can still contain a "
                f"sub-floor void, which only the ink-floor check can see"))
            continue
        if n > cfg.max_clearance_items:
            level = worst(level, WARN)
            n_skipped += 1
            details.append(f"  {layer:<10} {n} features -- OVER the "
                           f"{cfg.max_clearance_items} limit, gap check NOT RUN "
                           f"(raise --max-clearance-items). These gaps are "
                           f"UNCHECKED, not clean.")
            gaps.append(Gap(
                "clearance", layer, GAP_NOT_RUN,
                f"{n:,} features is over the "
                f"{cfg.max_clearance_items:,} --max-clearance-items limit",
                "raise --max-clearance-items",
                f"{layer}: all {n_possible:,} possible pair(s) -- 100% of "
                f"this layer's spacing -- went uncompared"))
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
        n_samenet = 0
        n_exempt = 0
        exempt_blocks: dict = {}

        # The generator is held in a name so that, when the budget runs out,
        # the REMAINDER can be counted. See the incomplete branch below: a
        # measurement that stopped early has to say how much it did not do,
        # and "how much" here is exactly the pairs left in this generator.
        cand = _candidate_pairs(feats, floor)
        n_cand_seen = 0
        stopped_at = -1
        for a, b in cand:
            n_cand_seen += 1
            stopped_at = a
            fa, fb = feats[a], feats[b]
            if fa.net and fa.net == fb.net:
                # SAME NET. A track, the via it lands on and the pour it feeds
                # are one conductor: they are ALLOWED to touch, and the gap
                # between two pieces of them is not a spacing limit. Counted,
                # because "we skipped 81 pairs" is a fact the reader needs, and
                # not judged, because judging it produced 81 findings on the
                # product board about copper that is deliberately continuous.
                n_samenet += 1
                continue
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
            # _feature_gap() starts its running best AT the cutoff and returns
            # it untouched when nothing came closer, so a pair that is
            # comfortably clear comes back as EXACTLY the floor. Taking that as
            # a measurement is how a layer whose real dam is 0.25 mm reported
            # "narrowest gap 0.200000 mm ... ON THE FLOOR ... a pass with no
            # headroom" -- the same false equivalence between a tight part and
            # a roomy one that this variable was introduced to remove, arriving
            # from the other direction. A saturated result is NOT MEASURED, so
            # it is left to the margin pass below, which searches wider and can
            # produce the real number.
            #
            # A gap that genuinely sits on the floor is not lost by this: it is
            # indistinguishable from saturation here, and the margin pass then
            # measures it exactly and reports it as ON THE FLOOR.
            if g >= floor - 1e-12:
                continue
            decl, verdict = _sweep_gap(fa, fb, g)
            if verdict is not None:
                # Moved, not removed: counted here, attributed and printed by
                # the exempt check, and out-of-band is a FAIL there.
                if verdict == "exempt":
                    n_exempt += 1
                    rec = exempt_blocks.setdefault(decl.block, [g, g, 0])
                    rec[0] = min(rec[0], g)
                    rec[1] = max(rec[1], g)
                    rec[2] += 1
                continue
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
            # BUDGET EXHAUSTION IS NOT A SKIP, IT IS AN INCOMPLETE MEASUREMENT,
            # and a measurement that stopped early states how far it got. The
            # generator is still live at the break, so draining it counts the
            # candidate pairs that were never reached -- index work only, no
            # geometry, so this costs a fraction of what the check already
            # spent. Capped, because on a pathological layer the remainder can
            # itself be enormous, and then the honest report is a lower bound.
            n_left, capped = _drain_count(cand, _DRAIN_CAP)
            tot = n_cand_seen + n_left
            frac = (f"{n_cand_seen:,} of {'>=' if capped else ''}{tot:,} "
                    f"candidate pair(s)")
            pct = (100.0 * n_left / tot) if tot else 0.0
            extent = (f"{layer}: examined {frac}; "
                      f"{'>=' if capped else ''}{n_left:,} pair(s) "
                      f"({'<=' if capped else ''}{pct:.1f}% of this layer's "
                      f"candidates) were NEVER COMPARED. It stopped while "
                      f"examining feature {stopped_at:,} of {n:,}; the grid "
                      f"walk is mostly in index order, so the spacing around "
                      f"the later features on {layer} is where the unmeasured "
                      f"pairs are concentrated")
            details.append(f"  {layer:<10} gap check INCOMPLETE -- exhausted the "
                           f"{cfg.clearance_budget:,}-operation budget with "
                           f"{n} features after {frac}. Remaining gaps are "
                           f"UNCHECKED (raise --clearance-budget).")
            details.append(f"  {layer:<10} UNMEASURED: {extent}")
            gaps.append(Gap(
                "clearance", layer, GAP_INCOMPLETE,
                f"the {cfg.clearance_budget:,}-operation budget ran out "
                f"part-way through this layer",
                "raise --clearance-budget",
                extent))
        else:
            n_tested_layers += 1
            if sweeps is not None:
                sweeps.mark_exercised(layer, ("gap",))
        n_exempt_total += n_exempt
        for block, (lo_g, hi_g, cnt) in sorted(exempt_blocks.items()):
            details.append(
                f"  {layer:<10} {cnt} sub-floor pair(s) EXEMPT by declaration "
                f"[{block}], observed {lo_g:.6f}..{hi_g:.6f} mm against the "
                f"{floor:.4f} mm floor -- and left out of the narrowest-gap "
                f"number below, which is therefore the narrowest NON-EXEMPT "
                f"gap on this layer")
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
                    feats, floor * GAP_MARGIN_REACH, GAP_MARGIN_BUDGET,
                    skip=(lambda fa, fb, g: _sweep_gap(fa, fb, g, False)[1]
                          == "exempt") if sweeps is not None else None)
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
                           f"{n_merged} touching"
                           + (f", {n_samenet} same-net pair(s) not judged"
                              if n_samenet else "") + "), " + margin)

    for layer in sorted(excluded):
        if layer_class(layer) not in ("silk", "mask", "copper", "buried"):
            continue
        why = excluded[layer]
        level = worst(level, SKIP)
        problems.append(f"NOT COMPARED: {layer} has {len(why)} item(s) the gap "
                        f"check cannot represent, so any gap involving them is "
                        f"UNCHECKED rather than clean: " + "; ".join(why[:3])
                        + (f" (+{len(why)-3} more)" if len(why) > 3 else ""))
        gaps.append(Gap(
            "clearance", layer, GAP_NOT_RUN,
            f"{len(why)} item(s) on this layer cannot be represented as gap "
            f"features: " + "; ".join(why[:3])
            + (f" (+{len(why)-3} more)" if len(why) > 3 else ""),
            "model the construct, or remove it from the artwork",
            f"{layer}: every gap involving those {len(why)} item(s) is "
            f"uncompared"))

    counter_problems, n_counters = _counter_problems(fp, cfg, details)
    problems += counter_problems
    if counter_problems:
        level = worst(level, _severity("copper", cfg.palette))

    if n_tested_layers == 0 and n_counters == 0 and level == PASS:
        level = SKIP
        head = ("NOTHING TESTED -- no layer here has two features to form a "
                "gap between")
        if not gaps:
            gaps.append(Gap(
                "clearance", "whole check", GAP_VACUOUS,
                "no layer in this file has two features to form a gap "
                "between, so no spacing limit was applied to anything",
                "",
                "every spacing floor: this check compared 0 pair(s)"))
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
    if n_exempt_total:
        head += f" ({n_exempt_total} exempt by declaration)"
    c = Check("clearance", level, head, details + problems)
    c.gaps = gaps
    return c


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
        floor, cls, _ = _floor_for(layer, cfg.palette, fp.is_board)
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
# 8. ink-floor: the region measurement, boards only
# --------------------------------------------------------------------------

def _ink_parts(fp: Footprint, cfg):
    """Every item turned into ink, per layer, plus everything that could not be.

    Returns (parts_by_layer, unrepresented_by_layer). Nothing is dropped in
    silence: an item that cannot be turned into a region lands in the second
    dict with a sentence saying why, and its layer is then reported as NOT
    MEASURED rather than as clean -- missing ink can widen a gap and narrow a
    neck, so it can hide a violation AND invent one, and neither belongs in a
    verdict.
    """
    from collections import defaultdict
    parts = defaultdict(list)
    missing = defaultdict(list)

    for i, it in enumerate(fp.items):
        lab = item_label(i, it)
        # Which Parts this item produces, so each can be stamped with the
        # footprint it came from. The ink measurement returns a coordinate and
        # no item identity, so ownership has to be carried in rather than
        # recovered afterwards.
        # .get(), never parts[l]: `parts` is a defaultdict, and touching a key
        # here would create an empty entry for every layer an item names --
        # including Edge.Cuts, which must never appear in it at all, and any
        # layer whose items ALL failed to become ink, which is how a layer that
        # measured nothing would start reading as a layer that measured fine.
        before = {l: len(parts.get(l, ())) for l in it.layers}
        for l in it.layers:
            if _floor_for(l, cfg.palette, fp.is_board)[0] is None:
                continue
            if layer_class(l) == "edge":
                # Edge.Cuts is not ink. It is a path a router follows, and the
                # feature that can fail there is the width of the LOOP, not the
                # width of the pen that drew it -- measuring the 0.05 mm
                # outline stroke against a 1.0 mm bit diameter would fail every
                # board ever drawn. check_min_feature judges the loops.
                continue
            if it.kind in ("fp_poly", "fp_rect"):
                if it.filled:
                    if len(it.pts) >= 3:
                        parts[l].append(ink_measure.Part(lab, list(it.pts),
                                                         area=True,
                                                         holes=list(it.holes),
                                                         net=it.net))
                elif it.width > 0:
                    parts[l].append(ink_measure.Part(lab, list(it.pts),
                                                     width=it.width, area=False,
                                                     closed=True, net=it.net))
                else:
                    missing[l].append(
                        f"{lab}: an unfilled outline with stroke width 0, which "
                        f"means 'use the board default line width' -- a number "
                        f"this harness does not resolve, so its ink is UNKNOWN")
            elif it.kind in ("fp_line", "fp_arc"):
                if it.width > 0:
                    parts[l].append(ink_measure.Part(lab, list(it.pts),
                                                     width=it.width, area=False,
                                                     closed=False, net=it.net))
                else:
                    missing[l].append(
                        f"{lab}: stroke width 0 means 'use the board default "
                        f"line width'; that default is not resolved here, so "
                        f"this line's ink is UNKNOWN")
            elif it.kind == "fp_circle":
                cx = (it.pts[0][0] + it.pts[2][0]) / 2.0
                cy = (it.pts[0][1] + it.pts[2][1]) / 2.0
                ring = _poly_circle(cx, cy, it.char_h)
                if it.filled:
                    holes = ([_poly_circle(cx, cy, it.hole_r)]
                             if it.hole_r > 0 else [])
                    parts[l].append(ink_measure.Part(lab, ring, area=True,
                                                     holes=holes, net=it.net))
                elif it.width > 0:
                    parts[l].append(ink_measure.Part(lab, ring, width=it.width,
                                                     area=False, closed=True,
                                                     net=it.net))
                else:
                    missing[l].append(f"{lab}: unfilled circle with stroke "
                                      f"width 0; its ink is UNKNOWN")
            elif it.kind == "pad":
                if it.stale:
                    missing[l].append(f"{lab}: {it.stale}")
                    continue
                cu = layer_class(l) in ("copper", "buried")
                if it.stale_hole and cu:
                    continue        # an unplated hole contributes no copper
                holes = []
                if it.hole_r > 0 and cu:
                    cx = sum(p[0] for p in it.pts) / len(it.pts)
                    cy = sum(p[1] for p in it.pts) / len(it.pts)
                    holes = [_poly_circle(cx, cy, it.hole_r)]
                parts[l].append(ink_measure.Part(lab, list(it.pts), area=True,
                                                 holes=holes, net=it.net))
            elif it.kind in ("fp_text", "fp_text_box", "property"):
                if it.hidden:
                    continue
                ink = expand_text(it)
                if not ink.ok:
                    missing[l].append(f"{lab} {it.text[:18]!r}: {ink.why}")
                    continue
                for ch in ink.chains:
                    parts[l].append(ink_measure.Part(lab, list(ch),
                                                     width=ink.width,
                                                     area=False, closed=False))
            else:
                missing[l].append(f"{lab}: item kind {it.kind!r} is not turned "
                                  f"into ink by this check")
        for l, n0 in before.items():
            for p in parts.get(l, ())[n0:]:
                p.owner = it.owner
    return parts, missing


def _ink_fix_hint() -> str:
    alts = _venv_interpreters()
    if alts:
        return (f"run under {alts[0]} (this repo's .venv, which has shapely) "
                f"-- not under KiCad's bundled python, which does not")
    return "pip install shapely into the venv you run this harness from"


_INK_FIX_HINT = _ink_fix_hint()


def _ink_extent(fp: Footprint, pal: Palette) -> str:
    """What the ink check WOULD have covered, for a gap that says how much of
    the board went unmeasured. Counted from the items themselves, so it is
    available on the early-return paths where nothing has been measured yet."""
    per: dict[str, int] = {}
    for it in fp.items:
        for l in it.layers:
            floor, cls, _p = _floor_for(l, pal, fp.is_board)
            if floor is None or cls == "edge":
                continue
            per[l] = per.get(l, 0) + 1
    if not per:
        return "no layer in this file carries ink with a fabrication floor"
    tot = sum(per.values())
    named = ", ".join(f"{l} ({n:,} item(s))" for l, n in sorted(per.items()))
    return (f"the inscribed width and the region gaps on ALL {len(per)} "
            f"floor-bearing layer(s), {tot:,} item(s): {named}")


def check_ink(fp: Footprint, cfg) -> Check:
    """The narrowest INK and the narrowest GAP on each layer, measured on the
    region rather than item by item.

    This is the check the coupon defect needed and no per-item check could
    give. Two things make it different from check_min_feature and
    check_clearance:

      * it measures the INSCRIBED width of the ink, so a traced letterform
        reports its 0.117 mm stem and not the 1.2 mm hull of the glyph; and
      * it measures gaps between BOUNDARY POINTS, not between items, so the
        void inside a keyhole-bridged 'o' -- which is the same ring as its
        outer contour and therefore invisible to any pairwise test -- is a gap
        like any other. Every one of the six sub-floor gaps on the alpha
        coupon's front face is of exactly that kind.

    On a MASK layer the meanings invert and are reported inverted: the drawn
    shape is an opening, so the narrowest "feature" is an aperture (no
    fabricator publishes a minimum, so it is reported and NOT judged) and the
    narrowest "gap" is the dam, which is what the mask floor is about.
    """
    extent = _ink_extent(fp, cfg.palette)
    if not getattr(cfg, "ink", True):
        return Check("ink-floor", SKIP, "skipped (--no-ink)",
                     ["nothing measured the ink region; this is not a pass"]
                     ).gap("whole check", GAP_NOT_RUN, "--no-ink",
                           "drop --no-ink", extent)
    if ink_measure is None:
        return Check("ink-floor", SKIP,
                     "NOT MEASURED -- tools/ink_measure.py could not be imported",
                     [_INK_IMPORT_ERR,
                      "no width or gap on any layer was measured on the region; "
                      "this is not a pass"]
                     ).gap("whole check", GAP_NOT_RUN,
                           f"tools/ink_measure.py could not be imported: "
                           f"{_INK_IMPORT_ERR}",
                           _INK_FIX_HINT, extent)
    ok, why = ink_measure.available()
    if not ok:
        # THE ONE. This is the branch that reported SKIP under KiCad's bundled
        # python, where shapely is not installed, and let the harness summarise
        # a FAILING board as "0 pass, 1 warn, 0 fail ... No hard failures" and
        # exit 0. The text here was already honest. What it lacked was any way
        # to bind the run, which is what the Gap does.
        return Check("ink-floor", SKIP, "NOT MEASURED -- " + why.split(",")[0],
                     [why, "no width or gap on any layer was measured on the "
                           "region; this is not a pass"]
                     ).gap("whole check", GAP_NOT_RUN, why, _INK_FIX_HINT,
                           extent)

    pal = cfg.palette
    parts, missing = _ink_parts(fp, cfg)
    only = getattr(cfg, "ink_layers", None)
    sweeps = getattr(cfg, "sweeps", None)
    details, problems = [], []
    level = PASS
    judged = 0
    n_exempt_total = 0
    measured_layers: set[str] = set()
    gaps: list[Gap] = []
    # Ink area, mm2, split into what was really measured and what was not.
    # This is the run's answer to "how much of the board went unmeasured",
    # in the only unit that means anything on a board: area of art.
    area_ok = area_gone = 0.0

    for note in fp.notes:
        details.append("  ! " + note)

    # Every layer that carries an item, not only the ones that produced ink:
    # a layer whose items all turned out to be unplated holes, or which is
    # Edge.Cuts, has to appear and say what happened to it.
    layers = sorted(set(parts) | set(missing)
                    | {l for it in fp.items for l in it.layers})
    for layer in layers:
        floor, cls, prov = _floor_for(layer, pal, fp.is_board)
        if floor is None:
            continue
        if cls == "edge":
            details.append(f"  {layer:<10} not ink -- a routing path, whose "
                           f"feature is the loop width; judged by min-feature")
            continue
        if only and layer not in only:
            details.append(f"  {layer:<10} NOT MEASURED: excluded by "
                           f"--ink-layers")
            level = worst(level, SKIP)
            gaps.append(Gap(
                "ink-floor", layer, GAP_NOT_RUN,
                "excluded by --ink-layers",
                f"add {layer} to --ink-layers, or drop the flag",
                f"{layer}: {len(parts.get(layer, ()))} ink part(s), inscribed "
                f"width and region gaps both unmeasured"))
            continue
        mask = (cls == "mask")
        exempt_fn = None
        if sweeps is not None and sweeps.decls:
            sweeps.set_ink_parts(layer, parts.get(layer, []))

            def exempt_fn(quantity, w, _layer=layer, _floor=floor):
                # `_floor` is the anti-collision radius: any foreign ink within
                # a floor of the witness voids the match, because then the neck
                # or gap being measured is between the ladder and something
                # else and that is a real spacing question.
                _d, verdict = sweeps.judge_point(
                    _layer, quantity, w.value, w.x, w.y, _floor,
                    f"{_layer} ink {quantity} witness {w}")
                return verdict

        r = ink_measure.measure_layer(
            layer, parts.get(layer, []), floor,
            max_segments=getattr(cfg, "ink_max_segments", 250_000),
            max_candidates=getattr(cfg, "ink_budget", 4_000_000),
            max_report=cfg.max_report,
            exempt=exempt_fn)
        if not r.ok:
            level = worst(level, SKIP)
            problems.append(f"NOT MEASURED: {layer} -- {r.why}")
            gaps.append(Gap(
                "ink-floor", layer, GAP_NOT_RUN, r.why, _INK_FIX_HINT,
                f"{layer}: {len(parts.get(layer, ()))} ink part(s); no region "
                f"was built, so neither the inscribed width nor the gaps on "
                f"this layer exist"))
            continue
        if r.n_components == 0:
            details.append(f"  {layer:<10} no ink")
            continue

        head = (f"  {layer:<10} {r.n_components} component(s), {r.area:.3f} mm2 "
                f"of ink, floor {floor:.4f} mm"
                f"{' PROVISIONAL' if prov else ''} ({cls})")
        if layer_class(layer) == "buried" and fp.is_board:
            head += " [inner copper judged as COPPER etch, not as buried tone]"
        details.append(head)

        if missing.get(layer):
            level = worst(level, SKIP)
            problems.append(
                f"NOT MEASURED: {layer} has {len(missing[layer])} item(s) this "
                f"check could not turn into ink, so the region it measured is "
                f"NOT the whole layer and neither the width nor the gap below "
                f"is the whole answer: "
                + "; ".join(missing[layer][:3])
                + (f" (+{len(missing[layer])-3} more)"
                   if len(missing[layer]) > 3 else ""))
            gaps.append(Gap(
                "ink-floor", layer, GAP_NOT_RUN,
                f"{len(missing[layer])} item(s) on this layer could not be "
                f"turned into ink: " + "; ".join(missing[layer][:3])
                + (f" (+{len(missing[layer])-3} more)"
                   if len(missing[layer]) > 3 else ""),
                "model the construct, or remove it from the artwork",
                f"{layer}: the region measured covers only {r.n_components} "
                f"component(s) / {r.area:.3f} mm2 and is NOT the whole layer, "
                f"so the width and gap numbers reported for it are not the "
                f"whole answer"))

        if r.incomplete:
            # NOT A SKIP -- AN INCOMPLETE MEASUREMENT. The region was built and
            # the erosion numbers hold; what ran out was the boundary scan, so
            # the report says which quantities survive and which do not, and
            # how big the layer it gave up on was.
            level = worst(level, SKIP)
            problems.append(f"NOT MEASURED: {layer} -- {r.incomplete_why}")
            area_gone += r.area
            gaps.append(Gap(
                "ink-floor", layer, GAP_INCOMPLETE, r.incomplete_why,
                "raise --ink-max-segments / --ink-budget",
                f"{layer}: the narrowest ink and the narrowest gap on "
                f"{r.n_components:,} component(s) covering {r.area:.3f} mm2 "
                f"-- 100% of this layer's ink -- were never computed "
                f"({r.n_segments:,} boundary segments, "
                f"{r.n_candidates:,} candidate pair(s))"))
        else:
            judged += 1
            area_ok += r.area
            measured_layers.add(layer)
            if sweeps is not None:
                sweeps.mark_exercised(layer, ("width", "gap", "vanish"))

        if r.n_exempt:
            n_exempt_total += sum(r.n_exempt.values())
            by_block: dict = {}
            for q, w in r.exempt_witnesses:
                d = next((z for z in (sweeps.decls if sweeps else ())
                          if z.quantity == q and z.layer == layer
                          and z.active_box.contains_point((w.x, w.y))), None)
                by_block.setdefault((d.block if d else "?", q),
                                    []).append(w)
            for (block, q), ws in sorted(by_block.items()):
                lo_v = min(x.value for x in ws)
                hi_v = max(x.value for x in ws)
                details.append(
                    f"  {layer:<10} {len(ws)} {q} witness(es) EXEMPT by "
                    f"declaration [{block}], observed {lo_v:.6f}..{hi_v:.6f} mm "
                    f"against the {floor:.4f} mm floor -- removed from the "
                    f"numbers below, which are therefore the narrowest "
                    f"NON-EXEMPT ones")
                for w in ws[:cfg.max_report]:
                    details.append(f"               {w}")
                if len(ws) > cfg.max_report:
                    details.append(f"               (+{len(ws)-cfg.max_report} "
                                   f"more)")

        # --- whole components finer than the process --------------------
        if r.vanished:
            level = worst(level, _severity(cls, pal))
            problems.append(
                f"{'OPENINGS' if mask else 'INK'} FINER THAN THE PROCESS: "
                f"{layer} {r.vanished} of {r.n_components} component(s) "
                f"({r.vanished_area:.4f} mm2) have NO point at least "
                f"{floor:.4f} mm from their own edge -- the thickest ink in "
                f"each is under the floor, so an opening at the floor deletes "
                f"them outright. Widest of them: "
                + "; ".join(str(w) for w in r.vanished_examples[:3]))

        # --- narrowest neck ----------------------------------------------
        if r.min_feature is not None and not mask:
            if r.min_feature.value < floor - 1e-9:
                level = worst(level, _severity(cls, pal))
                problems.append(
                    f"{'WIDTH' if cls != 'silk' else 'SILK WIDTH'} BELOW FLOOR: "
                    f"{layer} narrowest ink {r.min_feature} < {floor:.4f} mm "
                    f"({cls}); {len(r.features_below)} distinct place(s), "
                    "measured as the inscribed width of the region and not as "
                    "the hull of any one item. A neck can be a feature drawn "
                    "too thin, or the join where two features overlap by a "
                    "hair -- the second predicts that they MERGE rather than "
                    "that ink drops out, and the coordinates say which"
                    + ("".join(f"\n               also {w}"
                               for w in r.features_below[1:cfg.max_report])))
        elif r.min_feature is not None and mask:
            details.append(
                f"  {layer:<10} narrowest OPENING {r.min_feature} -- reported, "
                f"NOT JUDGED: no profile in tools/fab_profiles.py publishes a "
                f"minimum mask opening, so there is no floor to compare with")
        elif not r.incomplete:
            details.append(
                f"  {layer:<10} narrowest ink NOT MEASURED here: no two "
                f"boundary points on this layer came within {floor:.4f} mm of "
                f"each other across the ink, so every feature is wider than "
                f"the floor by more than the scan looked")

        # --- narrowest gap -------------------------------------------------
        if r.min_gap is not None:
            if r.min_gap.value < floor - 1e-9:
                level = worst(level, _severity(cls, pal))
                problems.append(
                    f"{'MASK DAM' if mask else 'GAP'} BELOW FLOOR: {layer} "
                    f"narrowest gap {r.min_gap} < {floor:.4f} mm ({cls}); "
                    f"{len(r.gaps_below)} distinct place(s). These are gaps "
                    f"IN THE REGION, so a void enclosed by a single polygon "
                    f"counts -- which is what a pairwise item check cannot see"
                    + ("".join(f"\n               also {w}"
                               for w in r.gaps_below[1:cfg.max_report])))
            else:
                details.append(f"  {layer:<10} narrowest gap {r.min_gap} "
                               f"(floor {floor:.4f} mm)")
        elif not r.incomplete:
            details.append(
                f"  {layer:<10} narrowest gap NOT MEASURED here: nothing came "
                f"within {floor:.4f} mm of anything else, so the tightest gap "
                f"is further out than this check looked")

        if r.n_samenet_gaps:
            details.append(
                f"  {layer:<10} {r.n_samenet_gaps} sub-floor gap witness(es) "
                f"NOT judged: all the ink bounding each one belongs to a "
                f"single net, so it is a gap inside one conductor and not a "
                f"spacing limit (witnesses, not places -- one narrow run of "
                f"track produces one per boundary segment)")
        if r.open_area_lost > 1e-6:
            details.append(
                f"  {layer:<10} an opening at {floor:.4f} mm removes "
                f"{r.open_area_lost:.4f} mm2 ({r.open_pct:.2f}%) of this "
                f"layer's ink. MAGNITUDE, NOT A VERDICT: a disc-shaped "
                f"structuring element also rounds every convex corner, and "
                f"that rounding is counted in this number")
        for n in r.notes:
            details.append(f"  {layer:<10} {n}")

    for layer in sorted(missing):
        if layer in parts:
            continue
        if _floor_for(layer, pal, fp.is_board)[0] is None:
            continue
        level = worst(level, SKIP)
        problems.append(
            f"NOT MEASURED: {layer} has {len(missing[layer])} item(s) and NOT "
            f"ONE of them could be turned into ink, so this layer was not "
            f"measured at all: " + "; ".join(missing[layer][:3]))
        gaps.append(Gap(
            "ink-floor", layer, GAP_NOT_RUN,
            f"not one of the {len(missing[layer])} item(s) on this layer "
            f"could be turned into ink: " + "; ".join(missing[layer][:3]),
            "model the construct, or remove it from the artwork",
            f"{layer}: the whole layer. Nothing on it was measured"))

    cfg.ink_measured_layers = measured_layers
    if area_gone > 0 and gaps:
        # The run-level answer to "how much of the board went unmeasured",
        # in mm2 of art rather than in layer names.
        tot = area_ok + area_gone
        gaps.append(Gap(
            "ink-floor", "this file", GAP_INCOMPLETE,
            "the region measurement did not cover the whole file",
            "",
            f"{area_gone:.3f} mm2 of {tot:.3f} mm2 of floor-bearing ink "
            f"({100.0 * area_gone / tot:.1f}%) was never measured for "
            f"inscribed width or region gaps"))
    if level == PASS and judged == 0:
        return Check("ink-floor", SKIP,
                     "NO LAYER WAS MEASURED -- nothing here has ink on a layer "
                     "with a fabrication floor", details
                     ).gap("whole check", GAP_VACUOUS,
                           "no layer in this file has ink on a layer with a "
                           "fabrication floor, so no floor was applied to "
                           "anything",
                           "check that the artwork is on the layers you think "
                           "it is",
                           "every fabrication floor: this check measured 0 "
                           "layer(s)")
    if level == PASS:
        head = f"ink and gaps above floor on {judged} layer(s)"
    else:
        head = f"{len(problems)} finding(s) over {judged} measured layer(s)"
    if n_exempt_total:
        head += f" ({n_exempt_total} exempt by declaration)"
    c = Check("ink-floor", level, head, details + problems)
    c.gaps = gaps
    return c


# --------------------------------------------------------------------------
# 9. inventory: what is in this board, and what of it went unmeasured
# --------------------------------------------------------------------------

def check_inventory(fp: Footprint, cfg) -> Check:
    """Every node in the file, classified into measured / not measured.

    THIS IS THE ANTI-BLIND-SPOT CHECK. The defect that prompted board support
    was not a wrong number, it was a whole class of object -- board-level
    gr_poly -- that no check could see, and the harness said nothing because
    it did not know the class existed. So the inventory refuses to be silent
    about anything: a head this file uses that this harness does not model
    lands here by name, at SKIP, whether or not anyone has thought about it.
    """
    if not fp.is_board:
        # NOT APPLICABLE, not a hole. No Gap: see check_project_rules.
        return Check("inventory", SKIP, "not a board (not applicable)")
    from collections import Counter
    top = {k: v for k, v in fp.head_counts.items() if "/" not in k}
    inner = {k.split("/", 1)[1]: v for k, v in fp.head_counts.items()
             if k.startswith("footprint/")}
    kinds = Counter(it.kind for it in fp.items)
    details = [
        "board nodes: " + ", ".join(f"{k}={v}" for k, v in sorted(top.items())),
    ]
    if inner:
        details.append("footprint child nodes: "
                       + ", ".join(f"{k}={v}" for k, v in sorted(inner.items())))
    details.append(f"{len(fp.items)} item(s) built and measured as: "
                   + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    n_placed = sum(1 for it in fp.items if it.src.startswith("FP "))
    details.append(f"{n_placed} of them come from PLACED FOOTPRINTS, expanded "
                   f"into board coordinates -- the board's own embedded copy, "
                   f"which is what the fab images, not what the .pretty holds")

    if not fp.unmeasured:
        return Check("inventory", PASS,
                     f"{len(top)} board node kind(s), every geometry-bearing "
                     f"one modelled", details)

    from collections import defaultdict
    by_reason = defaultdict(list)
    for label, lay, why in fp.unmeasured:
        by_reason[why].append((label, lay))
    problems = []
    c = Check("inventory", SKIP,
              f"{len(fp.unmeasured)} construct(s) NOT MEASURED", details)
    for why, rows in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        ex = ", ".join(f"{l} on {y}" for l, y in rows[:3])
        problems.append(f"NOT MEASURED ({len(rows)}): {why} -- e.g. {ex}"
                        + (f" (+{len(rows)-3} more)" if len(rows) > 3 else ""))
        c.gap("board constructs", GAP_NOT_RUN, why,
              "model the construct in this harness, or remove it from the "
              "board",
              f"{len(rows)} object(s) carrying geometry that NO check in this "
              f"run measured: {ex}"
              + (f" (+{len(rows)-3} more)" if len(rows) > 3 else ""))
    c.details = details + problems[:cfg.max_report]
    return c


# --------------------------------------------------------------------------
# 10. project-rules: is the DRC that guards this board even armed?
# --------------------------------------------------------------------------

# Which .kicad_pro rule must be at least which floor. The mapping is the point:
# a rule set to 0.0 does not "default to something sensible", it switches the
# corresponding DRC test off, and a board whose DRC is off reports "0
# violations" no matter what is on it.
PRO_RULE_FLOORS = {
    "min_clearance": ("copper", "copper-to-copper spacing"),
    "min_track_width": ("copper", "minimum track width"),
    "min_silk_clearance": ("silk", "silk-to-silk spacing"),
    "min_text_thickness": ("silk", "minimum text stroke"),
}


def check_project_rules(fp: Footprint, cfg) -> Check:
    """The design rules the board's own project file arms DRC with.

    THE SEVENTH INSTANCE. This project keeps shipping checks that cannot fail
    what they exist to catch, and "DRC: 0 violations" on these boards is one:
    the .kicad_pro sets min_clearance 0.0, min_silk_clearance 0.0 and
    min_text_thickness 0.08, so the tests those numbers drive are switched off
    or set under the floor, and a green DRC is decoration.

    A verifier that does not verify the OTHER verifier's trigger conditions is
    just a longer green line. So this reads the sibling .kicad_pro and fails
    when a rule that guards a floor is below it.

    What this check can NOT do, said plainly because it changes what a fix
    means: even fully armed, KiCad 10 DRC has no silk-graphic-to-silk-graphic
    spacing test and no minimum-width test for filled polygons. Arming these
    rules makes the package honest; it does not gate polygonised silk. That is
    what check_ink() is for.
    """
    if not fp.is_board or fp.path is None:
        # NOT APPLICABLE, not a hole: a footprint has no project file and no
        # DRC to arm, so nothing went unmeasured. This site carries NO Gap,
        # which is the distinction the old single axis could not make.
        return Check("project-rules", SKIP, "not a board (not applicable)")
    _armed = ("whether the DRC guarding this board is armed at all: "
              + ", ".join(sorted(PRO_RULE_FLOORS))
              + " -- and a 'DRC: 0 violations' on a board whose rules are 0.0 "
                "tested nothing")
    pro = fp.path.with_suffix(".kicad_pro")
    if not pro.is_file():
        return Check("project-rules", SKIP,
                     "NOT MEASURED -- no sibling .kicad_pro",
                     [f"looked for {pro.name}",
                      "without it nothing here knows what DRC on this board is "
                      "armed with, so a green DRC elsewhere means nothing"]
                     ).gap("whole check", GAP_NOT_RUN,
                           f"no sibling {pro.name}",
                           f"put the project file next to the board, or check "
                           f"the DRC rules by hand", _armed)
    try:
        doc = json.loads(pro.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        return Check("project-rules", SKIP,
                     f"NOT MEASURED -- {pro.name} could not be read: {e}"
                     ).gap("whole check", GAP_NOT_RUN,
                           f"{pro.name} could not be read: {e}",
                           "repair the project file", _armed)
    rules = (((doc.get("board") or {}).get("design_settings") or {})
             .get("rules") or {})
    classes = (((doc.get("net_settings") or {}).get("classes")) or [])
    if not rules:
        return Check("project-rules", SKIP,
                     f"NOT MEASURED -- {pro.name} declares no "
                     f"board.design_settings.rules"
                     ).gap("whole check", GAP_NOT_RUN,
                           f"{pro.name} declares no "
                           f"board.design_settings.rules",
                           "set the design rules in the project", _armed)

    pal = cfg.palette
    details, problems = [], []
    level = PASS
    for key, (cls, what) in sorted(PRO_RULE_FLOORS.items()):
        floor = pal.floors.get(cls)
        if key not in rules:
            details.append(f"  {key:<34} not set (KiCad default applies)")
            continue
        val = rules[key]
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        hard = cls in pal.hard
        if val <= 0.0:
            level = worst(level, FAIL if hard else WARN)
            problems.append(
                f"DRC DISARMED: {key} = {val} in {pro.name}. Zero does not "
                f"mean 'default', it means the {what} test does not run. Any "
                f"'DRC: 0 violations' on this board tested nothing about "
                f"{cls}. Set it to at least {floor:.4f} mm")
        elif val < floor - 1e-9:
            level = worst(level, FAIL if hard else WARN)
            problems.append(
                f"DRC UNDER THE FLOOR: {key} = {val:.4f} mm in {pro.name}, "
                f"below the {floor:.4f} mm {cls} floor ({what}). DRC will pass "
                f"geometry this harness fails, which is the wrong way round")
        else:
            details.append(f"  {key:<34} {val:.4f} mm  (>= {floor:.4f} mm {cls})")

    # The .gbrjob's DesignRules block is the DEFAULT NETCLASS, not the rules
    # block -- proven by editing one and replotting. A CAM operator reads the
    # gbrjob, so a netclass looser than the board's real geometry tells the fab
    # the wrong thing about what it has to hold.
    for nc in classes:
        if not isinstance(nc, dict) or nc.get("name") != "Default":
            continue
        for key in ("clearance", "track_width"):
            if key not in nc:
                continue
            try:
                val = float(nc[key])
            except (TypeError, ValueError):
                continue
            floor = pal.floors["copper"]
            if val > floor + 1e-9:
                details.append(
                    f"  netclass Default {key:<18} {val:.4f} mm -- this, not "
                    f"the rules block, is what the .gbrjob declares to the CAM "
                    f"operator. The active copper floor is {floor:.4f} mm, so "
                    f"the package would overstate what the fab must hold")
            elif val <= 0:
                level = worst(level, WARN)
                problems.append(
                    f"netclass Default {key} = {val}: the .gbrjob will declare "
                    f"zero {key} to the fab")
            else:
                details.append(f"  netclass Default {key:<18} {val:.4f} mm")

    details.append("scope: KiCad 10 DRC has NO silk-graphic-to-silk-graphic "
                   "spacing test and NO minimum-width test for filled "
                   "polygons (verified on this install with the rules armed). "
                   "Arming these makes the plotted package honest; it does "
                   "not gate polygonised silk -- see the ink-floor check")
    if level == PASS:
        return Check("project-rules", PASS,
                     f"{pro.name}: every floor-bearing rule is armed", details)
    return Check("project-rules", level,
                 f"{len(problems)} rule(s) that cannot fail what they guard",
                 details + problems)


# --------------------------------------------------------------------------
# board load check
# --------------------------------------------------------------------------

def check_kicad_load_board(path: Path, fp: Footprint, cfg) -> Check:
    """KiCad itself parses the board, and says how much copper it sees.

    `pcb export stats` is the cheapest thing that makes KiCad build the whole
    board object, and it hands back an independent copper area per side. That
    number is compared with the one this harness computed from the same file:
    two different programs reading the same geometry and agreeing is the only
    evidence that the transform stack above -- footprint placement, rotation,
    wildcard layers, via annuli -- is being applied the way KiCad applies it.
    """
    cli = cfg.cli
    _board_extent = ("whether KiCad parses this board at all, and the "
                     "independent copper-area cross-check that is the only "
                     "evidence the footprint-placement transform in this "
                     "harness matches the one KiCad applies")
    if not cli:
        return Check("kicad-load", SKIP,
                     "kicad-cli NOT FOUND -- this board is UNVERIFIED against "
                     "KiCad",
                     ["pass --kicad-cli /path/to/kicad-cli to fix",
                      "this is NOT a pass: nothing confirmed the file loads"]
                     ).gap("whole check", GAP_NOT_RUN,
                           "no kicad-cli was found",
                           "pass --kicad-cli /path/to/kicad-cli",
                           _board_extent)
    if cfg.cli_major < MIN_KICAD_MAJOR:
        return Check("kicad-load", SKIP,
                     f"kicad-cli is version {cfg.kicad_version}, need "
                     f"{MIN_KICAD_MAJOR}+ -- this board is UNVERIFIED"
                     ).gap("whole check", GAP_NOT_RUN,
                           f"kicad-cli {cfg.kicad_version} is older than "
                           f"{MIN_KICAD_MAJOR}",
                           "pass --kicad-cli /path/to/kicad-10/kicad-cli",
                           _board_extent)
    details = []
    with tempfile.TemporaryDirectory(prefix="verify_art_") as td:
        out = Path(td) / "stats.txt"
        try:
            r = run_cli(cli, ["pcb", "export", "stats",
                              "-o", host_path(out, cli), host_path(path, cli)])
        except subprocess.TimeoutExpired:
            return Check("kicad-load", FAIL, "pcb export stats timed out")
        except OSError as e:
            return Check("kicad-load", FAIL, f"could not run kicad-cli: {e}")
        se = (r.stderr or "").replace("\r", "").strip()
        if r.returncode != 0:
            return Check("kicad-load", FAIL, "KiCad REJECTED this board",
                         [f"exit={r.returncode}"] + ([f"stderr: {se}"] if se else []))
        if not out.is_file():
            return Check("kicad-load", FAIL,
                         "pcb export stats exited 0 but wrote nothing")
        txt = out.read_text(encoding="utf-8", errors="replace")
    details.append(f"pcb export stats: KiCad built the board "
                   f"({len(txt.splitlines())} line report)")
    if se:
        details.append(f"stderr: {se}")

    got = {}
    for side in ("Front", "Back"):
        m = re.search(rf"^- {side} copper area:\s*([0-9.]+)\s*mm", txt, re.M)
        if m:
            got[side] = float(m.group(1))
    mine = {}
    if ink_measure is not None and ink_measure.HAVE_SHAPELY:
        parts, _ = _ink_parts(fp, cfg)
        for side, layer in (("Front", "F.Cu"), ("Back", "B.Cu")):
            if layer in parts:
                try:
                    g = ink_measure.build_geometry(parts[layer])
                except Exception:
                    g = None
                if g is not None:
                    mine[side] = g.area
    # WHAT KiCad's NUMBER IS, measured rather than assumed. `pcb export stats`
    # reports the SUM of the copper items' areas, not the area of their union:
    # a board carrying two 10 x 10 mm rectangles overlapping by half reports
    # 200 mm2, not 150 (verified on this install). So KiCad's figure is an
    # UPPER BOUND on the union this harness computes, and the two are equal
    # exactly when nothing on the layer overlaps anything else.
    #
    # That makes the comparison one-sided, and one-sided is still worth having:
    # equality on a non-overlapping layer is strong evidence that the placement
    # transform, the layer wildcards and the via annuli are being applied the
    # way KiCad applies them, and a union LARGER than KiCad's sum would mean
    # this harness has invented copper, which is the failure worth catching.
    level = PASS
    for side in ("Front", "Back"):
        if side in got and side in mine:
            a, b = got[side], mine[side]
            if b > a * 1.01 + 1e-6:
                level = worst(level, WARN)
                details.append(
                    f"{side.lower()} copper area: this harness computes "
                    f"{b:.3f} mm2, MORE than the {a:.3f} mm2 KiCad's own "
                    f"statistics report as the sum of item areas. A union "
                    f"cannot exceed the sum it is taken over, so this harness "
                    f"is reading copper KiCad does not have")
            elif abs(a - b) <= max(1e-3, a * 1e-5):
                details.append(
                    f"{side.lower()} copper area: {b:.3f} mm2, equal to "
                    f"KiCad's own figure -- nothing on this layer overlaps, so "
                    f"the two programs read the same geometry")
            else:
                details.append(
                    f"{side.lower()} copper area: union {b:.3f} mm2 vs KiCad's "
                    f"{a:.3f} mm2 SUM-with-overlaps. Consistent (a union is "
                    f"never larger), but NOT a corroboration: overlap accounts "
                    f"for any difference and this cannot tell overlap from a "
                    f"reading error")
        elif side in got:
            details.append(f"{side.lower()} copper area: KiCad {got[side]:.3f} "
                           f"mm2; not cross-checked (no region measurement)")
    c = Check("kicad-load", level, f"loads in KiCad {cfg.kicad_version}",
              details)
    if not mine:
        details.append("copper area NOT cross-checked against KiCad's own "
                       "number, so the placement transform in this harness is "
                       "modelled but not corroborated")
        # NOT APPLICABLE vs NOT DONE. A board with no copper on it has nothing
        # to corroborate, and charging it a coverage gap would make every
        # silk-only art board permanently INCOMPLETE for a check that was
        # never going to say anything. The cross-check is applicable only where
        # KiCad itself reports copper, and only then is its absence a hole.
        if any(v > 0 for v in got.values()):
            c.gap("copper-area cross-check", GAP_NOT_RUN,
                  "KiCad reports copper on this board but this harness "
                  "produced no copper region to compare it with (the ink "
                  "region could not be built)",
                  _INK_FIX_HINT,
                  "the only independent evidence that footprint placement, "
                  "rotation, wildcard layers and via annuli are being applied "
                  "the way KiCad applies them")
        else:
            details.append("  -- not applicable: KiCad reports no copper on "
                           "this board, so there is nothing to corroborate")
    return c


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def unpublished_floors(key: str) -> list[tuple[str, str]]:
    """(class, what) for every floor this named process does NOT publish.

    OSH Park publishes no silkscreen minimum, for instance. apply_fab keeps the
    palette doc's house number for those and says so -- but the number being
    used is then guidance wearing a fabricator's name, and a comparison against
    it is not a comparison against anything that fab has committed to. That is
    "a profile with no published floor", and it is a coverage hole in exactly
    the same sense as a check that did not run: nothing measured the artwork
    against the process it will be built on.
    """
    prof = fab_profiles.PROFILES[key]
    return [(cls, what) for cls, val, what in (
        ("copper", prof.min_copper_mm, "trace width/spacing"),
        ("silk", prof.min_silk_mm, "silkscreen stroke"),
        ("mask", prof.min_mask_dam_mm, "mask dam")) if val is None]


def _fab_gaps(check: Check, key: str, palette: Palette) -> Check:
    for cls, what in unpublished_floors(key):
        check.gap(f"{cls} floor", GAP_UNJUDGED,
                  f"{fab_profiles.PROFILES[key].name} publishes no {what}, so "
                  f"the {palette.floors[cls]:.4f} mm used for {cls} is the "
                  f"palette doc's house guidance and not this fab's number",
                  "ask the fabricator for their number before ordering",
                  f"every {cls} comparison in this file was made against a "
                  f"limit this process has not stated; a finding under it is "
                  f"a WARN and not the FAIL a published limit would make it")
    return check


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


PALETTE_TAG_PREFIX = "palette:"
TONEMAP_TAG_PREFIX = "tonemap:"


def check_colourway(fp, cfg) -> Check:
    """The colourway the part says it was assigned under, and whether it holds.

    THE PART CARRIES THE STATEMENT. Same reason the fab profile does
    (fab_profiles.py lines 203-217): an emitter that assigns ink against one
    tone table and a verifier that checks it against another will pass a part
    that is wrong, and the failure surfaces long after the command line that
    caused it is gone. So the emitter writes `palette:<mask>-<silk>-<finish>`
    and `tonemap:<digest12>` into the tags and this reads them back.

    An UNTAGGED part is verified as black-mask. That is not a guess: it is what
    every part built before colourways existed was actually assigned against,
    and it is stated here rather than assumed silently.
    """
    import palette as pal_mod
    tags = getattr(fp, "tags", "") or ""
    try:
        pal = pal_mod.from_tag(tags, allow_provisional=True)
    except pal_mod.PaletteError as e:
        return Check("colourway", FAIL, f"unusable palette tag: {e}")

    lines = []
    if pal is None:
        pal = pal_mod.palette_for("black", allow_provisional=True)
        lines.append("this footprint carries no palette tag, so it is checked "
                     "as black mask / white silk / ENIG -- what everything "
                     "built before colourways existed was assigned against")
    else:
        lines.append(f"tagged {pal.tag()}; tone table digest {pal.digest()}")
    lines.append("T5 (the board) L* %.2f; drawn tones and their separation "
                 "from it: %s" % (
                     pal.lstar("T5"),
                     ", ".join(f"{t} {pal.dl_to_board(t):+.1f}"
                               for t in pal_mod.TONE_IDS
                               if pal[t].emits)))

    struct = [v for v in pal.validate() if v.kind == "structural"]
    if struct:
        return Check("colourway", FAIL, "the tone table this part names is "
                     "not usable", lines + [str(v) for v in struct])

    found = [t[len(TONEMAP_TAG_PREFIX):] for t in tags.split()
             if t.startswith(TONEMAP_TAG_PREFIX)]
    want = getattr(cfg, "tone_map", None)
    if len(set(found)) > 1:
        return Check("colourway", FAIL,
                     "the part claims two tone maps",
                     lines + [f"tonemap tags: {', '.join(sorted(set(found)))}"])
    if found:
        lines.append(f"assigned by a DECLARED tone map, digest {found[0]}")
    if want is not None:
        have = found[0] if found else None
        if have != want.digest():
            return Check(
                "colourway", FAIL,
                "the part was built from a DIFFERENT tone map than the one it "
                "is being checked against",
                lines + [
                    f"footprint says {have or '(none)'}, the sidecar given on "
                    f"the command line hashes to {want.digest()}.",
                    "Every colour decision in this part -- which ink became "
                    "which tone, which merges were accepted, which "
                    "substitutions were declared -- came from the other table. "
                    "Checking it against this one answers a question about a "
                    "part that was never built.",
                    "Re-emit from the current sidecar, or verify against the "
                    "one it was built from."])
        lines.append("tone map digest matches the sidecar given")
    elif found:
        lines.append("no --tone-map was given, so nothing corroborates that "
                     "digest; it is recorded, not checked")
    return Check("colourway", INFO, f"colourway {pal.tag()}", lines)


def _fresh_cfg(cfg):
    """A per-file copy of cfg whose palette nothing else shares.

    A directory can hold parts built for different processes, and the second
    file must not inherit the first one's floors.
    """
    cfg = copy.copy(cfg)
    cfg.palette = replace(cfg.palette, floors=dict(cfg.palette.floors),
                          notes=list(cfg.palette.notes),
                          hard=set(cfg.palette.hard))
    cfg.render_svg = None
    cfg.ink_measured_layers = set()
    cfg.sweeps = None
    return cfg


def verify_board(path: Path, cfg) -> tuple[str, list[Check]]:
    """The whole-board run.

    Ordering matters in one place: check_ink() runs BEFORE check_min_feature()
    so that min-feature knows which layers were really measured. Where the ink
    check did not run, min-feature reports the concave filled areas it refused
    to judge as NOT MEASURED instead of quietly leaving them out -- which is
    the difference between this harness and the one that passed the coupons.
    """
    checks: list[Check] = []
    try:
        fp = load_board(path)
    except (ParseError, OSError) as e:
        return FAIL, [Check("parse", FAIL, f"cannot read as a board: {e}")]

    checks.append(Check("info", INFO,
                        f'BOARD "{fp.name}"  version={fp.version}  '
                        f'generator={fp.generator}  items={len(fp.items)}  '
                        f'layers={len(fp.board_layers)}'))
    cfg = _fresh_cfg(cfg)
    key = getattr(cfg, "fab", None)
    if key:
        checks.append(_fab_gaps(
            Check("fab", INFO, f"floors from {key} (--fab)",
                  apply_fab(cfg.palette, key)), key, cfg.palette))
    else:
        checks.append(Check("fab", SKIP,
                            "NO FAB PROFILE -- floors are the palette doc's "
                            "house guidance, not a vendor's published limit",
                            ["a board carries no fab tag the way a microtext "
                             "footprint does, so nothing in the file says which "
                             "process it was drawn for",
                             "pass --fab <profile> to check it against the "
                             "process it will actually be built on; without it "
                             "a feature under the floor is a WARN, not a FAIL, "
                             "because the number it is under is guidance"]
                            ).gap("floors", GAP_UNJUDGED,
                                  "no --fab profile: nothing in this file says "
                                  "which process it was drawn for, so the "
                                  "floors applied are the palette doc's house "
                                  "guidance and not any fabricator's published "
                                  "limit",
                                  "pass --fab <profile>",
                                  "every floor comparison in this run was made "
                                  "against guidance, so a finding under it is "
                                  "a WARN and not the FAIL it would be against "
                                  "a real process"))
    try:
        cfg.sweeps = SweepTable(
            fp, cfg, enabled=not getattr(cfg, "no_sweep", False))
    except sweep_decls.SweepError as e:
        return FAIL, checks + [Check(
            "exempt", FAIL, f"unusable sweep declaration: {e}",
            ["A declaration that cannot be parsed is not ignored. It is the "
             "artefact making a claim this harness cannot check, and running "
             "the rest of the checks around it would report on a part nobody "
             "has described."])]
    checks.append(check_project_rules(fp, cfg))
    checks.append(check_kicad_load_board(path, fp, cfg))
    n = path.stat().st_size
    checks.append(Check("size", INFO, f"{n:,} B ({n/1000:.1f} kB)",
                        ["the byte budget is scoped to an art asset under "
                         f"{ASSET_MM:.0f} mm and is not applied to a board"]))
    checks.append(check_inventory(fp, cfg))
    checks.append(check_geometry(fp, cfg))
    checks.append(check_layers(fp, cfg))
    checks.append(check_self_intersection(fp, cfg))
    at = len(checks)
    checks.append(check_ink(fp, cfg))
    checks.append(check_min_feature(fp, cfg))
    checks.append(check_clearance(fp, cfg))
    if cfg.sweeps:
        # Inserted BEFORE the three checks that consulted it, so the reader
        # meets every suspended judgement before the findings that cite it.
        checks.insert(at, cfg.sweeps.render(cfg, fp))

    return _verdict(checks, cfg), checks


def gaps_of(checks: list[Check]) -> list[Gap]:
    """Every hole in one file's run, in check order."""
    return [g for c in checks for g in c.gaps]


def _verdict(checks: list[Check], cfg) -> str:
    """One file's verdict, over BOTH axes.

    The old line was

        verdict = FAIL if lv == FAIL else (WARN if lv in (WARN, SKIP) else PASS)

    and that single `else PASS` is where a run that measured nothing turned
    into a run that found nothing. A skipped check collapsed into WARN, WARN
    did not set the exit code, and the summary read "No hard failures".

    Now: a FAIL is still a FAIL, because a defect that WAS found outranks one
    that could not be looked for. Below that, ANY hole in coverage makes the
    file INCOMPLETE, which is not a pass and never becomes one -- there is no
    flag that turns INCOMPLETE into PASS, only --accept-gaps, which
    acknowledges the hole at the exit code without renaming it.
    """
    lv = PASS
    for c in checks:
        eff = c.level
        if cfg.strict and eff in (WARN, SKIP):
            eff = FAIL
        lv = worst(lv, eff)
    if lv == FAIL:
        return FAIL
    if gaps_of(checks):
        return INCOMPLETE
    return WARN if lv in (WARN, SKIP) else PASS


def verify_file(path: Path, cfg) -> tuple[str, list[Check]]:
    root = sniff_root(path)
    if root == "board":
        return verify_board(path, cfg)
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
    cfg = _fresh_cfg(cfg)
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
        checks.append(_fab_gaps(
            Check("fab", INFO, f"floors from {key} ({why})", lines),
            key, cfg.palette))
    try:
        cfg.sweeps = SweepTable(
            fp, cfg, enabled=not getattr(cfg, "no_sweep", False))
    except sweep_decls.SweepError as e:
        return FAIL, checks + [Check(
            "exempt", FAIL, f"unusable sweep declaration: {e}")]
    checks.append(check_colourway(fp, cfg))
    checks.append(check_kicad_load(path, cfg))
    checks.append(check_size(path, fp, cfg))
    checks.append(check_geometry(fp, cfg))
    checks.append(check_layers(fp, cfg))
    checks.append(check_self_intersection(fp, cfg))
    at = len(checks)
    checks.append(check_min_feature(fp, cfg))
    checks.append(check_clearance(fp, cfg))
    if cfg.sweeps:
        checks.insert(at, cfg.sweeps.render(cfg, fp))

    return _verdict(checks, cfg), checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Acceptance harness for generated KiCad art footprints.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+",
                    help=".kicad_mod or .kicad_pcb files (or directories)")
    ap.add_argument("--palette", default=None,
                    help="path to pcb-palette.md (default: ../docs/pcb-palette.md)")
    ap.add_argument("--kicad-cli", default=None, help="path to kicad-cli")
    ap.add_argument("--side", choices=("front", "back", "both"), default="front",
                    help="which side the art lives on (default front)")
    ap.add_argument("--allow-layer", action="append", default=[],
                    metavar="LAYER", help="treat LAYER as on-palette (repeatable)")
    ap.add_argument("--strict", action="store_true",
                    help="treat WARN and SKIP as failures. NOTE this is not a "
                         "substitute for the coverage rules: several holes sit "
                         "on checks whose LEVEL is PASS -- a layer with one "
                         "feature and therefore no pair to compare, a plot "
                         "cross-check skipped by --no-render -- so --strict "
                         "never saw them. They are caught by the gap axis, "
                         "which is always on")
    ap.add_argument("--accept-gaps", action="store_true",
                    help="acknowledge that some checks did not run, and exit 0 "
                         "anyway if nothing FAILED. Without it a run in which "
                         "any check was skipped, ran out of budget or had "
                         "nothing to test exits 3, because a check that did "
                         "not run must never contribute to a pass. The gaps "
                         "are LISTED either way -- this flag accepts them, it "
                         "does not hide them, and it never turns an INCOMPLETE "
                         "file into a passing one. --strict overrides it: a "
                         "SKIP is a FAIL there, and exit 1 wins over exit 0")
    ap.add_argument("--no-render", action="store_true",
                    help="skip the fp export svg plot check (faster)")
    ap.add_argument("--no-clearance", action="store_true",
                    help="skip the gap / mask-dam check")
    ap.add_argument("--no-ink", action="store_true",
                    help="skip the board ink-floor region measurement. It is "
                         "the only check that measures the INSCRIBED width of "
                         "a filled area and the only one that can see a gap "
                         "inside a single polygon, so turning it off leaves "
                         "traced letterforms unmeasured -- it reports SKIP, "
                         "not a pass")
    ap.add_argument("--no-sweep", action="store_true",
                    help="do not honour sweep: declarations. Every one is "
                         "still LISTED at INFO with NOT HONOURED, and the "
                         "findings it would have moved are judged normally. "
                         "Refusing to honour a declaration is available; "
                         "hiding that one exists is not")
    ap.add_argument("--ink-layers", default=None, metavar="L1,L2",
                    help="restrict the ink-floor check to these layers; every "
                         "other layer is reported NOT MEASURED")
    ap.add_argument("--ink-max-segments", type=int, default=250_000,
                    help="boundary segments per layer above which the ink "
                         "width/gap scan reports itself NOT MEASURED")
    ap.add_argument("--ink-budget", type=int, default=4_000_000,
                    help="boundary pairs per layer above which the ink "
                         "width/gap scan reports itself NOT MEASURED")
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
    ap.add_argument("--tone-map", default=None, metavar="FILE",
                    help="the declared tone map (tools/tone_map.py JSON) these "
                         "parts are supposed to have been built from. A part "
                         "whose tonemap: tag does not hash to this one FAILS: "
                         "every colour decision in it came from a different "
                         "table, so checking it against this one answers a "
                         "question about a part that was never built. Without "
                         "this flag the digest is recorded and not checked")
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
    cfg.tone_map = None
    if getattr(a, "tone_map", None):
        import tone_map as _tone_map
        try:
            cfg.tone_map = _tone_map.ToneMap.load(a.tone_map)
        except (OSError, ValueError) as e:
            print(f"verify_art: --tone-map {a.tone_map}: {e}", file=sys.stderr)
            return 2
    cfg.allow_layers = set(a.allow_layer)
    cfg.strict = a.strict
    cfg.render = not a.no_render
    cfg.clearance = not a.no_clearance
    cfg.ink = not a.no_ink
    cfg.no_sweep = a.no_sweep
    cfg.sweeps = None
    cfg.ink_layers = (set(x.strip() for x in a.ink_layers.split(",") if x.strip())
                      if a.ink_layers else None)
    cfg.ink_max_segments = a.ink_max_segments
    cfg.ink_budget = a.ink_budget
    cfg.ink_measured_layers = set()
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
            targets += sorted(p.glob("*.kicad_pcb"))
        else:
            targets.append(p)
    targets = [t for t in targets
               if t.suffix in (".kicad_mod", ".kicad_pcb") or t.is_file()]
    if not targets:
        print("verify_art: no .kicad_mod or .kicad_pcb files given",
              file=sys.stderr)
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

    # A MISSING HARD DEPENDENCY IS LOUD AT STARTUP, NOT SILENT AT THE CHECK.
    # Printed before any file so the operator sees it while still watching the
    # screen, rather than three hundred lines down inside one check's details.
    # stderr as well as stdout: a caller that pipes stdout to a log and reads
    # only the exit code still gets told to its face.
    # The gaps preflight() returns are NOT attached here: check_ink() raises a
    # per-file one that names the actual layers, which is strictly better, and
    # a footprint-only run needs no ink measurement and must not be charged a
    # gap for the absence of one.
    pre_lines, _pre_gaps = preflight()
    for ln in pre_lines:
        print(ln, file=sys.stderr)
    if pre_lines and not a.as_json:
        for ln in pre_lines:
            print(ln)

    def _exempt_of(cs):
        return (sum(c.exempt for c in cs), sum(c.stale for c in cs))

    results = []
    for t in targets:
        verdict, checks = verify_file(t, cfg)
        results.append((t, verdict, checks))
        if a.as_json:
            continue
        n_ex, n_st = _exempt_of(checks)
        tail = f"  ({n_ex} exempt{f', {n_st} stale' if n_st else ''})" \
            if (n_ex or n_st) else ""
        print(f"=== {t.name}  ->  {verdict}{tail}")
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
    n_incomplete = sum(1 for _, v, _ in results if v == INCOMPLETE)
    n_exempt = sum(sum(c.exempt for c in cs) for _, _, cs in results)
    n_stale = sum(sum(c.stale for c in cs) for _, _, cs in results)
    all_gaps = [(t, g) for t, _v, cs in results for g in gaps_of(cs)]

    if a.as_json:
        print(json.dumps({
            "palette": palette.source,
            "kicad_cli": cli,
            "kicad_version": kver,
            "floors": palette.floors,
            "buried_floor_provisional": palette.buried_provisional,
            "sweep_declarations_honoured": not a.no_sweep,
            "gaps_accepted": bool(a.accept_gaps),
            "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail,
                        "incomplete": n_incomplete,
                        "total": len(results),
                        "checks_did_not_run": len(all_gaps),
                        "exempt": n_exempt, "stale": n_stale},
            "files": [{
                "path": str(t), "verdict": v,
                "exempt": sum(c.exempt for c in cs),
                "stale": sum(c.stale for c in cs),
                "exemptions": [e for c in cs for e in c.exemptions],
                # The worst LEVEL any check reached, kept beside the verdict:
                # an INCOMPLETE file can still carry findings, and a consumer
                # that only reads `verdict` would not see them.
                "worst_level": worst(*[c.level for c in cs]) if cs else PASS,
                "gaps": [g.as_dict() for g in gaps_of(cs)],
                "checks": [{"key": c.key, "level": c.level,
                            "headline": c.headline, "details": c.details,
                            "gaps": [g.as_dict() for g in c.gaps]}
                           for c in cs],
            } for t, v, cs in results],
        }, indent=2))
    else:
        print("-" * 72)
        # The exemption count is printed even at zero, deliberately. A run
        # where judgement was suspended must not be byte-similar to one where
        # it was not, and a CI diff on this line catches a new exemption
        # appearing without anybody having to read the report.
        print(f"SUMMARY: {n_pass} pass, {n_warn} warn, {n_fail} fail, "
              f"{n_incomplete} incomplete of {len(results)}   "
              f"({n_exempt} exempt, {n_stale} stale"
              f"{'; NOT HONOURED --no-sweep' if a.no_sweep else ''})")
        for t, v, cs in results:
            if v == PASS:
                continue
            # A file can be INCOMPLETE *and* carry findings, and then the
            # "0 warn" in the line above is about the VERDICT column, not about
            # the report. Say so on the file's own line rather than letting a
            # reader take "0 warn" for "no warnings".
            lv = worst(*[c.level for c in cs]) if cs else PASS
            extra = (f"   (findings: {lv})"
                     if v == INCOMPLETE and lv in (WARN, FAIL) else "")
            print(f"  {v:<10} {t.name}{extra}")

        # WHAT DID NOT RUN, AND HOW MUCH OF THE BOARD THAT WAS. Printed even
        # under --quiet: this block is the one thing a caller must not be able
        # to miss, because missing it is the defect.
        if all_gaps:
            print()
            print(f"{len(all_gaps)} CHECK(S) DID NOT RUN OR DID NOT FINISH. A "
                  f"check that did not run cannot")
            print("contribute to a pass, and none of the files below has been "
                  "cleared of what")
            print("the missing check exists to catch:")
            cur = None
            for t, g in all_gaps:
                if t != cur:
                    print(f"  {t.name}")
                    cur = t
                print("      " + g.line().replace("\n", "\n      "))

        if n_fail:
            print("\nFAIL -- do not ship these.")
            if all_gaps:
                # And do not read the FAIL as the whole story: fixing what
                # failed leaves the unmeasured part still unmeasured, and the
                # next run will say so with exit 3.
                print(f"Note also the {len(all_gaps)} check(s) above that did "
                      f"not run. Fixing what FAILED does not")
                print("measure what was never measured; expect exit 3 on the "
                      "next run until those close.")
        elif n_incomplete and not a.accept_gaps:
            print("\nINCOMPLETE -- NOT A PASS. This run did not measure "
                  "everything it exists to")
            print("measure, so nothing here says these files are shippable. "
                  "Close the gaps")
            print("listed above and run again, or pass --accept-gaps to "
                  "acknowledge them")
            print("deliberately (which changes the exit code, not the verdict).")
        elif n_incomplete:
            print("\nINCOMPLETE, ACCEPTED (--accept-gaps). Nothing FAILED, but "
                  "the checks listed")
            print("above did not run. This is still not a clean pass.")
        elif n_warn:
            print("\nNo hard failures. Warnings above are fabrication risks, not "
                  "KiCad errors; review before shipping (--strict to enforce).")

    # EXIT STATUS.
    #   0  every file passed and every check ran
    #   1  at least one FAIL
    #   2  harness error (bad arguments, unreadable palette)
    #   3  no FAIL, but at least one check did not run -- the case that used to
    #      exit 0 with "No hard failures" over a board the harness had not
    #      looked at. --accept-gaps downgrades this to 0; nothing downgrades it
    #      silently.
    if n_fail:
        return 1
    if n_incomplete and not a.accept_gaps:
        return 3
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
