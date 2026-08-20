#!/usr/bin/env python3
"""W1: the emitter. Quantised tone-label raster -> KiCad footprint.

w0_spike.py answers "which tone is this pixel?" and stops there. This is the
stage that turns that answer into geometry a fab can make.

The one thing that matters here is that regions are emitted as POLYGONS, not as
per-pixel rectangles. The April pipeline emitted rectangles and produced a
2.5 MB footprint for a single 25 mm asset; a traced outline of the same art is
two orders of magnitude smaller and is also the only form a fab CAM tool can
reason about.

Pipeline, per tone:

    binary mask
      -> marching squares            closed loops on the half-pixel grid
      -> scale to mm                 (width_mm sets the scale; height follows)
      -> Ramer-Douglas-Peucker       tolerance in MILLIMETRES, not pixels
      -> outer/hole classification   by signed area, then containment
      -> hole bridging ("fracture")  polygon-with-holes -> one simple outline
      -> fp_poly on every layer the tone's recipe names

Design decisions worth arguing with:

HOLES. KiCad's `fp_poly` carries a single `(pts ...)` list, so a polygon with a
hole cannot be written directly. The two offered options were (a) split into
several simple polygons or (b) paint the hole with the background tone on top.
(b) is impossible here: the background tone T5 is *the absence of everything*,
and silk is the topmost physical layer, so there is nothing you can draw on top
of a silk region to un-draw it. So: (a), by keyhole bridging (a.k.a. fracture) —
each hole is joined to its containing outline by a zero-width slit, producing
one self-touching but non-self-crossing outline that fills correctly under both
even-odd and non-zero winding.

That is also exactly what KiCad itself does internally: `SHAPE_POLY_SET::
Fracture()`. Verified empirically — a bridged square-with-square-hole round-
trips through `kicad-cli fp upgrade` unchanged and plots as
`fill-rule:evenodd` with the hole open, KiCad having re-derived the hole and
re-cut its own bridge in a different place.

TOLERANCE is in millimetres and defaults to 0.05 mm, because every reason to
pick a number is physical, not pixel-based:
  - it is half the 0.1 mm minimum fabricable mask/copper feature,
  - it equals the +/-0.05 mm mask registration tolerance, so geometry finer
    than this cannot be *placed* reliably even if it can be imaged, and
  - the eye resolves ~0.087 mm at 300 mm, so it is below visibility.
Because the tolerance is fixed in mm, the same artwork emitted at 12 mm keeps
far fewer vertices than at 50 mm — the small badge automatically gets the
coarser polygons, and the vertex count tracks the output size rather than the
input resolution.

HALFTONE FILLS break the seven-tone ceiling. `--fill-mode hatch|stipple` renders
a tone as a duty-cycle field between the background and that tone rather than as
a flat fill, with the duty read off the SOURCE luminance inside the tone's own
region — so a gradient in the source becomes a duty ramp on the board, and
shading that the palette has no tone for gets a representation instead of being
banded onto its nearest neighbour. What a given pitch can and cannot represent
is bounded by the fabrication floors from both sides and is reported every run:
see the halftone section further down for the reasoning, the constraints and the
residual it does not fix.

Usage
    python tools/emit_art.py --labels art.png --width-mm 25 --name foo -o foo.kicad_mod
    python tools/emit_art.py --labels labels.npy --width-mm 25 --name foo -o foo.kicad_mod
    python tools/emit_art.py --labels art.png --width-mm 25 --name foo -o foo.kicad_mod \
        --fill-mode hatch --hatch-pitch 0.4 --hatch-angle 45
    python tools/emit_art.py --labels art.png --width-mm 25 --name foo -o foo.kicad_mod \
        --microtext "Reckless Systems" --microtext-height 0.7 --microtext-tone T2

`--microtext` is the one mode here whose geometry this file does not own:
tools/microtext.py places it and tools/stroke_font.py supplies the measured
letterform metrics it is checked against. It is applied last, after every tone,
so its mask opening frames letterforms and nothing else. It refuses rather than
degrades -- see its module docstring for why a clamped stroke is the worse
failure -- so a request it cannot honour stops the whole run before anything is
written.

`--labels` accepts a .npy of the array `w0_spike.quantise()` returns, or any
image (PNG/JPG/SVG), in which case it is quantised here with that same
function. Nothing about the quantiser is reimplemented. A .npy is labels only,
so it carries no luminance and cannot drive a halftone; that is refused rather
than downgraded.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys
import uuid

import numpy as np
from PIL import Image

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from w0_spike import (TONES, MIX_RATIO, MIX_SPLIT,   # noqa: E402
                      composite, quantise)
from coupon_ladders import (Fp, FLOOR_NOTES, FLOOR_SOURCE,  # noqa: E402
                            STROKE_ABS_MIN, TEXT_STROKE_RATIO, floor_for)
from coupon_blocks import TONE_RECIPE                # noqa: E402
import palette as _pal                               # noqa: E402
import tone_map as _tm                               # noqa: E402

# --- palette wiring --------------------------------------------------------
# Single source of truth for the layer recipes is coupon_blocks.TONE_RECIPE,
# which is itself a transcription of the table in docs/pcb-palette.md. Its keys
# are "T1_silk" style; strip to the tone id.
TONE_LAYERS = {k.split("_", 1)[0]: tuple(v) for k, v in TONE_RECIPE.items()}

BACKGROUND = "T5"          # draws nothing, by definition. See docs/pcb-palette.md.
DEFAULT_TOLERANCE_MM = 0.05
COORD_DP = 4

# Minimum fabricable feature per layer. Used only to flag polygons that are too
# small to make -- never to silently delete them.
#
# The SURFACE floors are not written here. They are read out of the doc by
# coupon_ladders._load_floors() and fetched through floor_for(), which is the
# same table and the same regexes verify_art.load_palette() uses -- so the
# emitter, the coupon generators and the acceptance harness all move together
# when docs/pcb-palette.md changes, instead of one of them silently lagging.
# They were previously transcribed by hand into this dict; the numbers agreed
# with the doc, which is exactly why nobody would have noticed when they stopped.
# emit_art already used floor_for() for text strokes, so the module was carrying
# two floor tables for two jobs. Now it carries one.
MIN_FEATURE_MM = {layer: floor_for(layer)[0] for layer in
                  ("F.SilkS", "B.SilkS", "F.Mask", "B.Mask", "F.Cu", "B.Cu")}

# Buried is the exception, and it is a real disagreement rather than an
# oversight -- see BURIED_FLOOR_MM further down for the whole story. In short:
# docs/pcb-palette.md gives no number ("considerably larger -- see below"), so
# floor_for() correctly returns None; --min-area-mm2 auto has used 0.30 mm here
# since before any of this and moving it would silently change what every
# existing asset drops; and the region-boundary and halftone checks use the
# harness's PROVISIONAL 0.50 mm so that emit and verify agree with each other.
# Both numbers are therefore kept, each doing the job it has always done, and
# emit_detailed() WARNS whenever a run actually draws on a buried layer, naming
# both. It is not resolvable in code: somebody has to build cal_buried and
# measure it.
MIN_FEATURE_BURIED_MM = 0.30      # legacy --min-area-mm2 auto value. See above.
MIN_FEATURE_MM.update({"In1.Cu": MIN_FEATURE_BURIED_MM,
                       "In2.Cu": MIN_FEATURE_BURIED_MM})

APRIL_BASELINE_BYTES = 2_500_000     # the 2.5 MB file this rebuild exists to beat

# --- halftone constants -----------------------------------------------------
# The reasoning for all of these is in the halftone section further down; they
# live up here only because emit_detailed()'s defaults are bound at def time.
HALFTONE_MODES = ("solid", "hatch", "stipple")

# Defaults, all from docs/pcb-palette.md rather than taste:
#   0.4 mm hatch pitch  -- the pitch coupon_blocks.shading_fields() sweeps, and
#                          the one the doc's own cost worked example uses.
#   45 deg              -- off both raster axes, so the line grid cannot beat
#                          against the pixel grid, and off the board's own
#                          orthogonal features.
#   0.5 mm stipple      -- the doc's worked cell size for eight levels off a
#                          0.15 mm minimum dot, and shading_fields()' pitch.
#   8 levels            -- "Quantise the ramp before segmenting, not after."
#                          The doc measures 25 levels at 1,550 segments/238 kB
#                          against 8 levels at ~500 segments/76 kB.
DEFAULT_HATCH_PITCH_MM = 0.40
DEFAULT_HATCH_ANGLE_DEG = 45.0
DEFAULT_STIPPLE_PITCH_MM = 0.50
DEFAULT_HALFTONE_LEVELS = 8

# Percentile of the source luminance inside a tone's own region that is taken to
# mean "full duty". Not the maximum: one specular pixel would then set the scale
# for the whole region and push everything else down a step.
HALFTONE_HI_PCT = 98.0

# How far apart, in L*, the tone and the background have to be before a duty
# ramp between them is worth building. docs/pcb-palette.md, "Where it earns its
# place": T5->T1 (83 L*) and T5->T2 (61 L*) are the ramps it names; T5->T6 is
# "too subtle on black mask to be worth it" and measures 7.6 L*. 20 sits in that
# gap with room on both sides. Below it a halftone costs geometry to render a
# difference nobody can see, so the tone is drawn solid and the reason is said.
HALFTONE_MIN_DELTA_L = 20.0

# Two scan-line spans are the same point at this distance (mm). Adjacent duty
# levels share a marching-squares boundary EXACTLY, so this is a float-noise
# tolerance and nothing more -- four orders below KiCad's 1e-5 mm resolution.
_SPAN_TOUCH = 1e-6

# How far above the floor the ladder's extreme rungs are actually built (mm).
# A mark computed to be exactly `floor` wide is written out through a rotation
# and a round to COORD_DP, and comes back a fraction of a micron under -- at
# which point verify_art.py reports "0.150 mm < 0.150 mm", which is true and
# useless. 1 um is ten times the worst-case rounding error at four decimal
# places and 0.7% of the silk floor, so it buys the margin without moving the
# tone. It is a WRITE-OUT allowance, not a fabrication opinion.
_FLOOR_MARGIN_MM = 0.001

# Overlap forced between two marks that abut on the same scan line (mm).
# Adjacent duty levels meet at exactly one x -- their clip contours are the same
# unsimplified marching-squares boundary -- but the two marks have different
# half-widths, so after the rotation and the 4-dp round their shared edges can
# land 0.1 um apart instead of on top of each other. That reads as a 0.0001 mm
# dam, which is not a dam, it is arithmetic. 2 um of deliberate overlap makes
# them one feature and says so, rather than leaving a gap nobody can measure and
# no fab could hold.
_SPAN_OVERLAP = 0.002

# --- T8 windows and T9 cuts -------------------------------------------------
#
# Neither tone is in TONE_RECIPE, and that is not an oversight. T1..T7 are
# SURFACE tones: a recipe of layers you draw on, one dict lookup per tone. T8
# and T9 are STRUCTURAL -- they change what the board *is* at that spot rather
# than what colour it is -- and each carries constraints that no layer list can
# express (both faces at once; keepouts on every copper layer; a router bit
# radius; a copper-to-edge clearance that is a BOARD rule, not a palette
# number). So they are not rows in the recipe table, they are modes you POINT
# at a tone with --window-tone / --cut-tone. docs/pcb-palette.md carries them
# the same way: as prose, after the recipe fence, not inside it.

WINDOW_LAYERS = ("F.Mask", "B.Mask")   # mask off BOTH faces or the window is dead
WINDOW_KEEPOUT_LAYER = "Dwgs.User"     # annotation. Never fabricated.
WINDOW_KEEPOUT_STROKE_MM = 0.12        # a drawing weight, not a feature size
# The copper layers a board-level rule area has to exclude for the window to
# pass light. docs/pcb-palette.md: "four deliberate keepouts plus two mask
# openings". In1/In2 are named because SatoshiStarter#3 makes In1 a ground
# plane, and a pour floods any window that has no keepout.
WINDOW_KEEPOUT_COPPER = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")

CUT_LAYER = "Edge.Cuts"
CUT_STROKE_MM = 0.05      # drawing weight; the FEATURE is the routed slot width

# docs/pcb-palette.md, "Router constraints -- the ones that bite":
#   standard bit 1.6-2.0 mm dia  ->  minimum internal radius = 0.8-1.0 mm
#   smaller bit  1.0 mm dia      ->  0.5 mm radius, "at extra cost, ask first"
#   minimum slot width           ~=  bit diameter
#   webs: "treat ~1.5 mm as a floor for anything handled"
DEFAULT_CUT_FILLET_MM = 0.8      # bottom of the standard-bit radius range
CUT_FILLET_FLOOR_MM = 0.5        # smallest radius any bit in the doc can cut
CUT_SLOT_MIN_MM = 1.0            # 1.0 mm dia bit; the standard bit needs 1.6-2.0
CUT_WEB_MIN_MM = 1.5             # material left between two cuts
CUT_FILLET_SEGMENTS = 8

# SatoshiStarter's copper-to-edge rule. This is a BOARD number, not a palette
# floor -- docs/pcb-palette.md gives none -- so it is a default to be overridden
# per board with --copper-edge-clearance-mm, and it is labelled as such wherever
# it is reported.
DEFAULT_COPPER_EDGE_MM = 0.5

COPPER_LAYER_RE = re.compile(r"^(?:F|B|In\d+)\.Cu$")

# Cap on point/edge pair comparisons in the copper-vs-cut audit. Blowing it
# reports the audit INCOMPLETE; it never silently stops checking.
AUDIT_PAIR_BUDGET = 60_000_000
_AUDIT_CHUNK = 4096


class ToneDropped(RuntimeError):
    """A tone present in the input produced no geometry. Never acceptable."""


class CopperInWaste(RuntimeError):
    """Copper landed on the slug a T9 cut routes away, or inside the board rule.

    The direction-agnostic trap: KiCad's copper_edge_clearance measures the
    DISTANCE from copper to an Edge.Cuts line and does not care which side of it
    the copper is on. Marks placed inside a cutout are 1.5 mm from the edge and
    pass DRC -- and then get routed away with the slug.
    """


# --- marching squares ------------------------------------------------------
# Cell corners TL=8 TR=4 BR=2 BL=1. Midpoints indexed T=0 R=1 B=2 L=3.
# Directed so the FILLED side is always on the left of travel (image coords,
# y down). That makes outer loops negative-area and hole loops positive, which
# is how they are told apart below, and it makes every midpoint appear exactly
# once as a segment start -- so the loops stitch with a plain dict.
#
# Cases 5 and 10 are the saddles. Resolved as 8-connected FOREGROUND (the two
# diagonal filled corners join), which is right for artwork: a diagonal run of
# pixels is one stroke, not a string of islands. Background is therefore
# 4-connected, so holes never leak out through a diagonal.
_MS = {
    1:  ((2, 3),),
    2:  ((1, 2),),
    3:  ((1, 3),),
    4:  ((0, 1),),
    5:  ((0, 3), (2, 1)),
    6:  ((0, 2),),
    7:  ((0, 3),),
    8:  ((3, 0),),
    9:  ((2, 0),),
    10: ((1, 0), (3, 2)),
    11: ((1, 0),),
    12: ((3, 1),),
    13: ((2, 1),),
    14: ((3, 2),),
}


def trace_contours(mask):
    """Marching squares -> list of closed loops, (N,2) float arrays.

    Coordinates are pixel-centre space: pixel (row r, col c) sits at (x=c, y=r),
    and contour vertices land on half-pixel edge midpoints.
    """
    m = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), dtype=np.uint8)
    m[1:-1, 1:-1] = np.asarray(mask, dtype=bool).astype(np.uint8)

    tl, tr = m[:-1, :-1], m[:-1, 1:]
    br, bl = m[1:, 1:], m[1:, :-1]
    case = (tl << 3) | (tr << 2) | (br << 1) | bl

    stride = 2 * m.shape[1] + 4          # doubled-coordinate row stride
    succ: dict[int, int] = {}

    for cv, segs in _MS.items():
        rr, cc = np.nonzero(case == cv)
        if rr.size == 0:
            continue
        r2 = rr.astype(np.int64) << 1
        c2 = cc.astype(np.int64) << 1
        mid = (
            (c2 + 1, r2),        # T
            (c2 + 2, r2 + 1),    # R
            (c2 + 1, r2 + 2),    # B
            (c2, r2 + 1),        # L
        )
        for a, b in segs:
            ax, ay = mid[a]
            bx, by = mid[b]
            succ.update(zip((ay * stride + ax).tolist(),
                            (by * stride + bx).tolist()))

    loops = []
    while succ:
        start = next(iter(succ))
        k, keys = start, []
        while True:
            nk = succ.pop(k, None)
            if nk is None:
                break
            keys.append(k)
            k = nk
            if k == start:
                break
        if len(keys) < 3:
            continue
        ka = np.asarray(keys, dtype=np.int64)
        y2, x2 = np.divmod(ka, stride)
        loops.append(np.stack([x2 * 0.5 - 1.0, y2 * 0.5 - 1.0], axis=1))
    return loops


# --- geometry helpers ------------------------------------------------------
def signed_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def point_in_poly(pt, poly):
    x, y = float(pt[0]), float(pt[1])
    ax, ay = poly[:, 0], poly[:, 1]
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    straddle = (ay > y) != (by > y)
    if not straddle.any():
        return False
    dy = np.where(straddle, by - ay, 1.0)
    xi = ax + (y - ay) * (bx - ax) / dy
    return bool(np.count_nonzero(straddle & (xi > x)) & 1)


def _rdp_open(pts, eps):
    """Ramer-Douglas-Peucker on an open polyline. Iterative; keeps ends."""
    n = len(pts)
    if n < 3:
        return np.ones(n, dtype=bool)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        seg = pts[i + 1:j]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0.0:
            d = np.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1])
        else:
            d = np.abs(dx * (a[1] - seg[:, 1]) - (a[0] - seg[:, 0]) * dy) / length
        k = int(np.argmax(d))
        if d[k] > eps:
            mid = i + 1 + k
            keep[mid] = True
            stack.append((i, mid))
            stack.append((mid, j))
    return keep


def rdp_closed(pts, eps):
    """RDP on a closed loop. Anchored on the two mutually most distant-ish
    points so the result does not depend on where the tracer happened to start.
    Falls back to the original loop rather than collapsing it -- a tiny loop is
    still image content and must not vanish here."""
    n = len(pts)
    if n < 4 or eps <= 0:
        return pts
    d0 = np.hypot(pts[:, 0] - pts[0, 0], pts[:, 1] - pts[0, 1])
    i1 = int(np.argmax(d0))
    if i1 == 0:
        return pts
    a = pts[:i1 + 1]
    b = np.vstack([pts[i1:], pts[:1]])
    out = np.vstack([a[_rdp_open(a, eps)][:-1], b[_rdp_open(b, eps)][:-1]])
    return out if len(out) >= 3 else pts


def bridge_holes(outer, holes):
    """Polygon-with-holes -> one self-touching outline (keyhole / fracture).

    Each hole is joined by a zero-width horizontal slit running left from the
    hole's leftmost vertex to the first boundary it meets. Holes are processed
    left to right and merged into the working outline as they go, so a hole can
    bridge to an earlier hole's boundary; a hole still unprocessed lies entirely
    to the right and cannot be in the way.

    The leftward ray uses a CLOSED span test -- an edge counts if py lies
    anywhere between its endpoints, endpoints included -- rather than the
    half-open "strictly straddles" rule used for point-in-polygon. That
    distinction is the whole ballgame here, and it is not a style preference:

      The bridge vertex is chosen as the topmost of the hole's leftmost
      vertices, so it is by construction a local extremum in y. Under the
      half-open rule an edge that merely TOUCHES the ray at such a vertex does
      not count, which makes an already-merged hole invisible to any later hole
      sharing its exact y. Text art produces those constantly -- the counters of
      letters on one line share a pixel row -- and the later hole's slit then
      ran straight through the earlier one, laying two slits on top of each
      other. The MFB node badges did this 16 times each.

      Overlapping slits still FILL correctly (each is traversed once in each
      direction, so the winding cancels) which is why it went unnoticed, but the
      outline is no longer a clean fracture and no downstream boolean or offset
      operation can be trusted on it.

    With the closed test the nearest boundary to the left is found whether it
    crosses the ray or merely touches it, so a later hole bridges ONTO the
    earlier hole's vertex instead of over it.
    """
    out = np.asarray(outer, dtype=np.float64)
    order = sorted(range(len(holes)), key=lambda i: float(holes[i][:, 0].min()))
    unbridged = 0
    for hi in order:
        hole = np.asarray(holes[hi], dtype=np.float64)
        xmin = hole[:, 0].min()
        cand = np.nonzero(hole[:, 0] <= xmin + 1e-12)[0]
        i0 = int(cand[np.argmin(hole[cand, 1])])
        px, py = float(hole[i0, 0]), float(hole[i0, 1])

        ax, ay = out[:, 0], out[:, 1]
        bx, by = np.roll(ax, -1), np.roll(ay, -1)
        # Horizontal edges are excluded: they meet the ray in a segment, not a
        # point, and their endpoints are already carried by the adjoining edges.
        sloped = ay != by
        span = (np.minimum(ay, by) <= py) & (py <= np.maximum(ay, by)) & sloped
        dy = np.where(sloped, by - ay, 1.0)
        xi = np.where(span, ax + (py - ay) * (bx - ax) / dy, -np.inf)
        xi = np.where(xi <= px + 1e-9, xi, -np.inf)
        i = int(np.argmax(xi))
        if not np.isfinite(xi[i]):
            unbridged += 1          # geometrically impossible; reported, never hidden
            continue
        q = np.array([[float(xi[i]), py]])
        rot = np.roll(hole, -i0, axis=0)
        out = np.concatenate([out[:i + 1], q, rot, rot[:1], q, out[i + 1:]])
    return out, unbridged


def fillet_loop(loop, radius, want_convex, *, sagitta_tol=DEFAULT_TOLERANCE_MM,
                seg=CUT_FILLET_SEGMENTS):
    """Round selected corners of one closed loop to `radius`.

    WHICH corners is the whole question, and it is decided in terms of the
    region the loop ENCLOSES (its winding interior, independent of traversal
    direction):

        want_convex=True   corners where that region's interior angle is < 180
        want_convex=False  the reflex ones

    For a T9 cut the enclosed region of an OUTER loop is the void, and of a hole
    loop is an island of board left standing inside the void. A router bit of
    radius r cannot cut a corner the void is convex at -- it sweeps an arc and
    leaves a quarter-round of material behind -- so those are the corners that
    MUST be filleted. Corners the void is reflex at are corners the MATERIAL is
    convex at; the bit cuts around the outside of those and they stay sharp,
    which is what docs/pcb-palette.md means by "external corners: sharp is
    fine". Outer loop and island loop therefore want opposite senses, and the
    caller passes them.

    The arc always removes area on the NARROW side of the corner, which is the
    right thing in both senses: rounding a corner cuts it off.

    Corners flatter than `sagitta_tol` are left alone -- there the arc departs
    from the sharp corner by less than the emitter's own coordinate tolerance,
    so it would spend eight vertices to move the outline by less than its
    precision.

    Returns (pts, n_filleted, reduced). `reduced` lists every radius that had to
    be cut down because the adjoining edges were too short to carry the one that
    was asked for. Reduction is unavoidable -- the alternative is an arc that
    overshoots its neighbour and self-intersects -- so it is REPORTED rather
    than done quietly, and the caller warns on it.
    """
    P = np.asarray(loop, dtype=np.float64)
    n = len(P)
    if n < 3 or radius <= 0:
        return P, 0, []
    orient = 1.0 if signed_area(P) > 0 else -1.0
    out: list = []
    n_fil = 0
    reduced: list[float] = []
    for i in range(n):
        A, B, C = P[i - 1], P[i], P[(i + 1) % n]
        u, v = A - B, C - B
        lu = math.hypot(float(u[0]), float(u[1]))
        lv = math.hypot(float(v[0]), float(v[1]))
        if lu < 1e-12 or lv < 1e-12:
            out.append(B)
            continue
        u, v = u / lu, v / lv
        cosang = max(-1.0, min(1.0, float(u[0] * v[0] + u[1] * v[1])))
        theta = math.acos(cosang)          # 0..pi, measured on the NARROW side
        # Convexity w.r.t. the enclosed region: for a loop whose signed area is
        # positive, convex vertices have a positive turn cross-product; the sign
        # flips with traversal direction, which `orient` cancels.
        cross = float((B[0] - A[0]) * (C[1] - B[1]) - (B[1] - A[1]) * (C[0] - B[0]))
        convex = (cross * orient) > 0
        if convex != want_convex or theta <= 1e-9 or theta >= math.pi - 1e-9:
            out.append(B)
            continue
        half = theta / 2.0
        sagitta = radius * (1.0 / math.sin(half) - 1.0)
        if sagitta < sagitta_tol:
            out.append(B)
            continue
        t = radius / math.tan(half)
        tmax = 0.5 * min(lu, lv)           # half of each edge, so two adjacent
        r = radius                          # fillets can never overrun each other
        if t > tmax:
            t = tmax
            r = t * math.tan(half)
            reduced.append(r)
        w = u + v
        lw = math.hypot(float(w[0]), float(w[1]))
        if lw < 1e-12:
            out.append(B)
            continue
        w = w / lw
        centre = B + w * (r / math.sin(half))
        p0, p1 = B + u * t, B + v * t
        a0 = math.atan2(float(p0[1] - centre[1]), float(p0[0] - centre[0]))
        a1 = math.atan2(float(p1[1] - centre[1]), float(p1[0] - centre[0]))
        da = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi   # short way round
        for k in range(seg + 1):
            ang = a0 + da * k / seg
            out.append(np.array([centre[0] + r * math.cos(ang),
                                 centre[1] + r * math.sin(ang)]))
        n_fil += 1
    return np.asarray(out, dtype=np.float64), n_fil, reduced


# --- vectorised point / segment predicates ---------------------------------
# point_in_poly() above answers for ONE point. The copper-vs-cut audit asks for
# thousands at a time, so these are the array forms. Same even-odd rule, so a
# keyhole-bridged outline (which is self-touching by construction) is read
# correctly -- that is the whole reason the fracture is made that way.

def _pip_many(P, poly, chunk=_AUDIT_CHUNK):
    """(N,) bool: which of P (N,2) lie inside the closed polygon `poly`."""
    P = np.asarray(P, dtype=np.float64).reshape(-1, 2)
    poly = np.asarray(poly, dtype=np.float64)
    if len(poly) < 3 or len(P) == 0:
        return np.zeros(len(P), dtype=bool)
    ax, ay = poly[:, 0], poly[:, 1]
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    dy = np.where(ay != by, by - ay, 1.0)
    out = np.zeros(len(P), dtype=bool)
    for s in range(0, len(P), chunk):
        px = P[s:s + chunk, 0][:, None]
        py = P[s:s + chunk, 1][:, None]
        straddle = (ay[None, :] > py) != (by[None, :] > py)
        xi = ax[None, :] + (py - ay[None, :]) * (bx - ax)[None, :] / dy[None, :]
        out[s:s + chunk] = (np.count_nonzero(straddle & (xi > px), axis=1) & 1) != 0
    return out


def _seg_pts(pts, closed=True):
    """Closed polyline -> (S1, S2) segment endpoint arrays."""
    a = np.asarray(pts, dtype=np.float64)
    if len(a) < 2:
        return a[:0], a[:0]
    b = np.roll(a, -1, axis=0)
    return (a, b) if closed else (a[:-1], a[1:])


def _pt_seg_d2(P, S1, S2):
    """(N,M) squared distance from each point in P to each segment S1->S2."""
    d = S2 - S1
    ll = (d * d).sum(1)
    llz = np.where(ll > 0, ll, 1.0)
    wx = P[:, 0][:, None] - S1[:, 0][None, :]
    wy = P[:, 1][:, None] - S1[:, 1][None, :]
    t = np.clip((wx * d[:, 0][None, :] + wy * d[:, 1][None, :]) / llz[None, :],
                0.0, 1.0)
    ex = wx - t * d[:, 0][None, :]
    ey = wy - t * d[:, 1][None, :]
    return ex * ex + ey * ey


def _segs_cross(A1, A2, B1, B2):
    """(N,M) bool: do segments A properly cross segments B?

    Needed because two polylines can cross with every vertex far from the other
    line -- an X of two long segments. A vertex-to-segment minimum alone would
    report them metres apart when the true gap is zero.
    """
    dax = (A2[:, 0] - A1[:, 0])[:, None]
    day = (A2[:, 1] - A1[:, 1])[:, None]
    dbx = (B2[:, 0] - B1[:, 0])[None, :]
    dby = (B2[:, 1] - B1[:, 1])[None, :]
    d1 = dax * (B1[:, 1][None, :] - A1[:, 1][:, None]) - \
        day * (B1[:, 0][None, :] - A1[:, 0][:, None])
    d2 = dax * (B2[:, 1][None, :] - A1[:, 1][:, None]) - \
        day * (B2[:, 0][None, :] - A1[:, 0][:, None])
    d3 = dbx * (A1[:, 1][:, None] - B1[:, 1][None, :]) - \
        dby * (A1[:, 0][:, None] - B1[:, 0][None, :])
    d4 = dbx * (A2[:, 1][:, None] - B1[:, 1][None, :]) - \
        dby * (A2[:, 0][:, None] - B1[:, 0][None, :])
    return ((d1 > 0) != (d2 > 0)) & ((d3 > 0) != (d4 > 0))


def _polyline_gap(a_pts, b_pts, budget=None):
    """Minimum distance between two closed polylines. 0 if they cross.

    -> (gap, pairs_examined) or (None, pairs) if the budget ran out.
    """
    A1, A2 = _seg_pts(a_pts)
    B1, B2 = _seg_pts(b_pts)
    if len(A1) == 0 or len(B1) == 0:
        return math.inf, 0
    pairs = len(A1) * len(B1)
    if budget is not None and pairs > budget:
        return None, pairs
    best = math.inf
    for s in range(0, len(A1), _AUDIT_CHUNK):
        a1, a2 = A1[s:s + _AUDIT_CHUNK], A2[s:s + _AUDIT_CHUNK]
        if _segs_cross(a1, a2, B1, B2).any():
            return 0.0, pairs
        d2 = np.minimum(_pt_seg_d2(a1, B1, B2), _pt_seg_d2(a2, B1, B2))
        e2 = np.minimum(_pt_seg_d2(B1, a1, a2), _pt_seg_d2(B2, a1, a2))
        best = min(best, float(d2.min()), float(e2.min()))
    return math.sqrt(best), pairs


def _bbox(pts):
    a = np.asarray(pts, dtype=np.float64)
    return (float(a[:, 0].min()), float(a[:, 1].min()),
            float(a[:, 0].max()), float(a[:, 1].max()))


def _bbox_gap(a, b):
    return math.hypot(max(0.0, a[0] - b[2], b[0] - a[2]),
                      max(0.0, a[1] - b[3], b[1] - a[3]))


def _round_dedupe(pts, dp=COORD_DP):
    r = np.round(np.asarray(pts, dtype=np.float64), dp)
    if len(r) > 1:
        keep = np.ones(len(r), dtype=bool)
        keep[1:] = np.any(r[1:] != r[:-1], axis=1)
        r = r[keep]
    if len(r) > 2 and np.all(r[0] == r[-1]):
        r = r[:-1]
    return r


# --- region-boundary operations ---------------------------------------------
# Two facts about a picture that the tone map on its own cannot express.
#
# SILHOUETTE. T5 draws nothing and IS the board, so any part of the subject that
# quantises to T5 is indistinguishable from the ground it sits on. On Tux that
# is 34.7% of the figure -- his entire body -- contiguous with the background
# and the same tone as it. No colour operation can recover the outline, because
# there is no colour difference left to recover: body and background are one
# region. The alpha channel, where the source has one, holds exactly the missing
# fact -- which pixels are subject at all -- so the silhouette is derived from
# alpha as the ring of opaque pixels within a given distance of the transparent
# edge, reassigned to a tone that does draw.
#
# The width of that ring is specified in MILLIMETRES and converted here using
# the output's own mm/px. A ring specified in pixels would be a different
# physical keyline at every output size -- 3 px is 0.27 mm on a 30 mm badge and
# 0.11 mm on a 12 mm one, i.e. the same command would sail over the silk floor
# at one size and fall under it at the other.
#
# KNOCKOUT. A mark removed FROM a tone field rather than drawn in it. The hole
# is already there -- a field's mask is `labels == host`, so anything that is
# not the host is by construction a gap in it. What is missing is (a) being able
# to say "and do not draw the mark either; let the gap BE the mark", which is
# how the SparkFun carrier's labels work (dark letters are bare mask showing
# through gaps in the silk, not dark ink), and (b) the fabrication check, which
# is NOT the check a positive mark gets.

BURIED_LAYERS = ("In1.Cu", "In2.Cu")

# docs/pcb-palette.md gives no number for buried tones -- "considerably larger
# -- see below", and the section below it is prose about blur. tools/verify_art.py
# assumes 0.50 mm and prints it as PROVISIONAL (--floor-buried). MIN_FEATURE_MM
# above carries 0.30 mm and is deliberately NOT changed here, because
# --min-area-mm2 auto has always used it and moving it would silently change
# what every existing asset drops. The region-boundary checks below use the
# harness's 0.50 mm so emit and verify agree with each other, and say
# PROVISIONAL every time they print it. The two numbers disagreeing is a real
# inconsistency in the tree; it is surfaced, not papered over -- see
# _buried_floor_warning(), which fires on any run that draws on a buried layer.
BURIED_FLOOR_MM = 0.50


def _buried_floor_warning(layers_used):
    """The one warning for the buried-floor split. -> str or None.

    `layers_used` is every layer the run actually drew on. Silent unless a
    buried one is among them: a picture with no buried tone is not affected by
    which number is right, and a warning nobody can act on is noise.
    """
    hit = sorted(l for l in set(layers_used) if l in BURIED_LAYERS)
    if not hit or abs(MIN_FEATURE_BURIED_MM - BURIED_FLOOR_MM) < 1e-9:
        return None
    return (
        f"BURIED FLOOR IS UNDECIDED and this run draws on {'/'.join(hit)}. "
        f"docs/pcb-palette.md gives no number for buried tones "
        f"(\"considerably larger -- see below\"), so this tree carries two: "
        f"{MIN_FEATURE_BURIED_MM:g} mm governs --min-area-mm2 auto and the "
        f"per-tone min-feature count, and {BURIED_FLOOR_MM:g} mm PROVISIONAL "
        f"governs the keyline width, the knockout/gap floor and the halftone "
        f"duty ladder (it is verify_art.py's --floor-buried, so emit and the "
        f"harness agree). Both appear in this report and they are not the same "
        f"number. Anything between them passes one check and fails the other. "
        f"Build cal_buried, measure it, and set both.")

# How much larger a floor a KNOCKOUT has to clear than the same feature drawn
# positive. docs/pcb-palette.md states the direction and declines to give a
# number: "A 0.15 mm silk gap is at least as hard to hold as a 0.15 mm silk
# line -- ink bleeds inward and can close a fine gap. Knockout text needs *more*
# margin than positive text, not less."
#
# 2.0, derived rather than picked: bleed b runs outward from every inked edge.
# A positive mark of width w carries ink on the INSIDE of both its edges, so it
# images at w + 2b -- fatter than drawn, but still there. A gap of width w has
# ink on the OUTSIDE of both its edges, so it images at w - 2b and is gone
# entirely at w = 2b. The positive floor F is the width at which a mark stops
# being reliable, which puts b at roughly F/2 -- and for mask that is
# F/2 = 0.05 mm, exactly the +-0.05 mm registration tolerance the doc does
# quote. A gap therefore has to be DRAWN at F + 2(F/2) = 2F to survive as F.
# On silk that is 0.30 mm, which is also the right order for the "more margin
# than positive text" the doc asks for. Exposed as --knockout-floor-mult
# because it is a process constant nobody in this tree has measured.
KNOCKOUT_FLOOR_MULT = 2.0

# Gap measurement is the most expensive thing here; stop after this many and
# say so rather than either hanging or pretending the audit was complete.
GAP_AUDIT_MAX = 400


class RegionOpError(ValueError):
    """A --silhouette-* / --knockout request that cannot be honoured as asked."""


def tone_floor_mm(layers):
    """(floor_mm, provisional) for a tone, from the layers its recipe names.

    The WIDEST floor wins: a tone drawn on both silk and copper is limited by
    silk, because the feature has to survive on every layer it is written to.
    """
    floor, prov = 0.0, False
    for layer in layers:
        if layer in BURIED_LAYERS:
            f, p = BURIED_FLOOR_MM, True
        else:
            f, p = MIN_FEATURE_MM.get(layer, 0.1), False
        if f > floor:
            floor, prov = f, p
        elif f == floor and p:
            prov = True
    return floor, prov


def edt_px(seed, radius_px, outside_is_seed=False):
    """Euclidean distance in PIXELS from every cell to the nearest True in
    `seed`, computed out to `radius_px` only; farther cells come back inf.

    Separable and windowed, in O(radius) numpy passes: the vertical sweep finds
    the nearest seed within +-r in each column, the horizontal sweep combines
    columns within +-r. That is exact for every cell whose true distance is
    <= r, which is the only range any caller here cares about -- both callers
    are asking "is this within a fabrication-scale distance of an edge", and a
    cell 400 px away is as good as infinitely far.

    Windowed rather than a full Felzenszwalb lower-envelope transform because
    that one is a sequential scan per row and would have to be a Python loop;
    this is a handful of whole-array shifts. scipy.ndimage would give both, but
    scipy is not a dependency of this tree and adding one for a distance
    transform is not a trade worth making.

    `outside_is_seed` treats everything beyond the raster as seed, which is what
    the silhouette wants: art that runs off the edge of its own frame ends
    there, and the frame edge is an edge of the artwork.
    """
    seed = np.asarray(seed, dtype=bool)
    H, W = seed.shape
    r = max(0, int(math.ceil(float(radius_px))))
    fill_v = bool(outside_is_seed)
    fill_h = 0.0 if outside_is_seed else np.inf

    g = np.where(seed, 0.0, np.inf)          # nearest seed in this column
    for k in range(1, r + 1):
        if k < H:
            up = np.full((H, W), fill_v)
            up[:H - k] = seed[k:]
            dn = np.full((H, W), fill_v)
            dn[k:] = seed[:H - k]
            hit = up | dn
        else:
            hit = np.full((H, W), fill_v)
        hit &= ~np.isfinite(g)
        if hit.any():
            g[hit] = float(k)

    g2 = g * g
    d2 = g2.copy()
    for k in range(1, r + 1):
        left = np.full((H, W), fill_h)
        right = np.full((H, W), fill_h)
        if k < W:
            left[:, k:] = g2[:, :W - k]
            right[:, :W - k] = g2[:, k:]
        np.minimum(d2, float(k * k) + np.minimum(left, right), out=d2)
    return np.sqrt(d2)


def _dilate1(mask):
    """4-connected dilation by one pixel. Reads only `mask`, so the four ORs do
    not cascade into a two-pixel dilation."""
    m = np.asarray(mask, dtype=bool)
    d = m.copy()
    d[1:] |= m[:-1]
    d[:-1] |= m[1:]
    d[:, 1:] |= m[:, :-1]
    d[:, :-1] |= m[:, 1:]
    return d


def silhouette_ring(labels, width_px, frame_is_edge=True):
    """Opaque pixels within `width_px` of a transparent one -> boolean mask.

    Distance is to the nearest transparent pixel CENTRE, so the outermost layer
    of opaque pixels sits at 1.0 and a ring of `n` px of physical width comes
    out n px thick -- which lines up with the tracer, whose contours run on the
    half-pixel grid, i.e. half a pixel outside that outermost centre.
    """
    transparent = np.asarray(labels) < 0
    d = edt_px(transparent, width_px, outside_is_seed=frame_is_edge)
    return (~transparent) & (d <= float(width_px) + 1e-9)


def _poly_inside_grid(poly, xs, ys):
    """Which points of the grid xs X ys lie inside `poly`. -> (len(ys), len(xs)).

    Scanline crossing-number, a row at a time: the edges straddling a row give
    that row's crossing abscissae, and one searchsorted turns them into the
    parity of every sample in the row at once. Half-open straddle (`>` on one
    end, not the other) so a vertex is counted exactly once.
    """
    p = np.asarray(poly, dtype=np.float64)
    ax, ay = p[:, 0], p[:, 1]
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    sloped = ay != by
    ax, ay, bx, by = ax[sloped], ay[sloped], bx[sloped], by[sloped]
    out = np.zeros((len(ys), len(xs)), dtype=bool)
    if ax.size == 0:
        return out
    for j, y in enumerate(ys):
        hit = (ay > y) != (by > y)
        if not hit.any():
            continue
        xi = np.sort(ax[hit] + (y - ay[hit]) * (bx[hit] - ax[hit])
                     / (by[hit] - ay[hit]))
        out[j] = (np.searchsorted(xi, xs, side="right") & 1).astype(bool)
    return out


def _inscribed_width(p, step, radius_mm, max_cells):
    """Inscribed-circle diameter of `p` on a grid of pitch `step`.
    -> (width_mm, step_used). Searches out to `radius_mm` only."""
    x0, y0 = float(p[:, 0].min()), float(p[:, 1].min())
    x1, y1 = float(p[:, 0].max()), float(p[:, 1].max())
    w, h = x1 - x0, y1 - y0
    nx, ny = int(w / step) + 3, int(h / step) + 3
    if nx * ny > max_cells:
        step *= math.sqrt(nx * ny / float(max_cells))
        nx, ny = int(w / step) + 3, int(h / step) + 3
    xs = x0 - step + np.arange(nx) * step
    ys = y0 - step + np.arange(ny) * step

    inside = _poly_inside_grid(p, xs, ys)
    if not inside.any():
        return 0.0, step                      # thinner than one sample step
    d = edt_px(~inside, radius_mm / step + 2.0, outside_is_seed=True)
    d[~inside] = 0.0
    # Cells deeper than the window come back inf and are floored to 0 here,
    # which is safe rather than lossy: every finite cell up to the window edge
    # is still there, so the maximum saturates AT the window instead of being
    # lost, and the window is set well above the floor being tested.
    dmax = float(np.max(np.where(np.isfinite(d), d, 0.0)))
    # The distance is to the nearest OUTSIDE sample CENTRE; the boundary itself
    # is about half a step nearer than that, so the radius is dmax - 0.5 cells.
    return 2.0 * max(0.0, dmax - 0.5) * step, step


def gap_width_mm(poly, cap_mm, samples_per_cap=48, max_cells=400_000):
    """Diameter of the largest circle that fits inside `poly`, in mm.
    -> (width_mm, exact).

    This is the right measure of "how wide is this gap". A knockout fails when
    ink closes it, and it closes last where the gap is widest, so what has to
    clear the floor is the largest inscribed circle. The two obvious
    alternatives are both wrong for this: polygon MINIMUM width condemns every
    acute corner of an otherwise generous gap, and AREA passes a long thin slot
    that will close along its whole length. Same reasoning as an inscribed-
    circle DRC rule.

    Two passes, because the only question ever asked is "does this clear
    `cap_mm`" and the common answer is "easily":

      coarse, at cap/4 -- the sampling error is about 1.5 cells on the diameter,
      so a coarse reading of 2*cap means a true width of at least 1.6*cap and
      the gap is waved through as (cap, exact=False);

      fine, at cap/samples_per_cap, only for the gaps that came back anywhere
      near the floor. Those are thin by definition, so their bounding box is
      thin too and the fine grid over it is small. The cell budget still exists
      for the pathological case -- a long thin diagonal snake, whose bbox is
      large in both axes -- and coarsening it sets exact=False.

    Measured against shapes with a known inradius (slab, disc, L-notch), the
    fine pass lands within about +-2 cells on the diameter -- +-4% of the floor
    at the default sampling -- and the disc, whose boundary is the one the grid
    fits worst, errs low. So a gap within a few percent of the floor may be
    called either way. This is a fabrication warning, not a DRC engine, and it
    is a warning about a number (the bleed multiplier) that nobody here has
    measured either.
    """
    p = np.asarray(poly, dtype=np.float64)
    x0, y0 = float(p[:, 0].min()), float(p[:, 1].min())
    x1, y1 = float(p[:, 0].max()), float(p[:, 1].max())
    if x1 <= x0 or y1 <= y0 or cap_mm <= 0.0:
        return 0.0, True
    cap_mm = float(cap_mm)

    coarse, _ = _inscribed_width(p, cap_mm / 4.0, 2.5 * cap_mm, max_cells)
    if coarse >= 2.0 * cap_mm:
        return cap_mm, False                  # "at least the floor" is all we asked

    step = cap_mm / max(1, int(samples_per_cap))
    width, used = _inscribed_width(p, step, 1.5 * cap_mm, max_cells)
    exact = used <= step * 1.000001
    if width >= cap_mm:
        return cap_mm, False
    return float(width), exact


def border_tones(mask, labels, tone_names):
    """What a region sits AGAINST: tone -> pixel count around its outer edge.

    A one-pixel adjacency count, not a topological enclosure test, and it is
    used as one: it answers "does this mark border the field it claims to be
    knocked out of", which is the failure that actually happens (a mark that
    runs out of its host reads as bare board, not as a gap). A mark sealed
    inside a third tone inside the host would fool it, so it is reported as a
    percentage rather than asserted.
    """
    m = np.asarray(mask, dtype=bool)
    ring = _dilate1(m) & ~m
    counts: dict[str, int] = {}
    vals, ns = np.unique(np.asarray(labels)[ring], return_counts=True)
    for v, n in zip(vals.tolist(), ns.tolist()):
        key = "alpha" if v < 0 else tone_names[v]
        counts[key] = counts.get(key, 0) + int(n)
    edge = int(m[0].sum() + m[-1].sum()) + int(m[1:-1, 0].sum() + m[1:-1, -1].sum())
    if edge:
        counts["frame"] = counts.get("frame", 0) + edge
    return counts


NO_ALPHA_REFUSAL = (
    "--silhouette-tone needs an alpha channel and this source has none: every "
    "pixel is opaque, so there is no figure/ground information in the file at "
    "all.\nThe documented alternative -- deriving the outline from the "
    "outermost non-{bg} boundary -- is NOT implemented, deliberately. On an "
    "opaque source {bg} is used both AS the subject and AS the ground (that is "
    "the whole problem this flag exists to solve) and the two are the same "
    "pixels; any outline derived from them would be a guess dressed up as a "
    "measurement, and it would also lay a keyline around every interior {bg} "
    "region -- Tux's own body markings -- rather than around the figure.\n"
    "Supply a source with alpha, or matte the subject out first. To outline a "
    "field from the inside instead, that is --knockout."
)


def apply_silhouette(labels, tone_names, tone_layers, tone, width_mm, mm_per_px):
    """Reassign the alpha-derived edge ring to `tone`. -> (labels, info)."""
    if tone not in tone_names:
        raise RegionOpError(
            f"--silhouette-tone {tone!r} is not one of the tones in play; "
            f"known: {' '.join(dict.fromkeys(tone_names))}")
    idx = tone_names.index(tone)
    layers = tuple(tone_layers.get(tone) or ())
    if tone == BACKGROUND or not layers:
        raise RegionOpError(
            f"--silhouette-tone {tone} draws nothing -- it IS the board (see "
            f"docs/pcb-palette.md). A silhouette in it would be exactly as "
            f"invisible as the problem it is meant to fix. Pick a tone with a "
            f"layer recipe, e.g. T3 (bare FR4, tan) or T1 (silk white).")

    labels = np.asarray(labels)
    transparent = labels < 0
    if not transparent.any():
        raise RegionOpError(NO_ALPHA_REFUSAL.format(bg=BACKGROUND))

    floor, prov = tone_floor_mm(layers)
    warnings: list[str] = []
    defaulted = width_mm is None
    if defaulted:
        width_mm = floor
    width_mm = float(width_mm)
    if width_mm <= 0.0:
        raise RegionOpError(f"--silhouette-mm must be positive, got {width_mm:g}")

    if width_mm < floor - 1e-9:
        warnings.append(
            f"silhouette: --silhouette-mm {width_mm:g} is BELOW the "
            f"{floor:g} mm{' PROVISIONAL' if prov else ''} minimum feature for "
            f"{tone} on {'/'.join(layers)}. Emitting it as asked -- it will "
            f"print unreliably or not at all. Raise it to at least {floor:g}.")

    width_px = width_mm / mm_per_px
    if width_px < 1.0:
        warnings.append(
            f"silhouette: {width_mm:g} mm is {width_px:.2f} px at this raster "
            f"scale ({mm_per_px*1000:.1f} um/px) -- under one pixel, so the "
            f"ring cannot be resolved from the source. Re-raster larger "
            f"(--raster-width) or widen --silhouette-mm.")

    before = dict(zip(*[a.tolist() for a in np.unique(labels[~transparent],
                                                      return_counts=True)]))
    ring = silhouette_ring(labels, width_px, frame_is_edge=True)
    ring_px = int(ring.sum())

    # Which of those came from the frame rather than from alpha: art that runs
    # off its own raster gets a keyline along the cut, and that is a real thing
    # to know about rather than a surprise at fab.
    d_alpha = edt_px(transparent, width_px, outside_is_seed=False)
    frame_px = int((ring & ~(d_alpha <= width_px + 1e-9)).sum())

    if ring_px == 0:
        warnings.append(
            f"silhouette: the {width_mm:g} mm ring is EMPTY -- no opaque pixel "
            f"lies within {width_px:.2f} px of a transparent one. Nothing was "
            f"drawn and the silhouette is still missing.")

    eaten_v, eaten_n = np.unique(labels[ring], return_counts=True)
    eaten = {tone_names[int(v)]: int(n) for v, n in zip(eaten_v, eaten_n)
             if int(v) >= 0}

    out = labels.copy()
    out[ring] = idx
    after = dict(zip(*[a.tolist() for a in np.unique(out[~transparent],
                                                     return_counts=True)]))
    consumed = [(tone_names[v], n) for v, n in sorted(before.items())
                if v != idx and after.get(v, 0) == 0]

    opaque_px = int((~transparent).sum())
    info = {
        "tone": tone, "layers": list(layers),
        "width_mm": width_mm, "width_px": width_px,
        "width_defaulted": defaulted,
        "floor_mm": floor, "floor_provisional": prov,
        "ring_px": ring_px,
        "ring_pct_of_opaque": round(100.0 * ring_px / max(opaque_px, 1), 2),
        "frame_derived_px": frame_px,
        "reassigned_from": dict(sorted(eaten.items(),
                                       key=lambda kv: -kv[1])),
        "consumed": consumed,
        "warnings": warnings,
    }
    return out, info


def _fmt_counts(d):
    return "  ".join(f"{k}={v:,}" for k, v in
                     sorted(d.items(), key=lambda kv: -kv[1])) or "-"


def parse_knockout(spec):
    """'MARK' or 'MARK:HOST' -> (mark, host_or_None)."""
    s = str(spec).strip()
    if not s:
        raise RegionOpError("--knockout needs a tone, e.g. --knockout T5:T1")
    mark, sep, host = s.partition(":")
    mark, host = mark.strip(), host.strip()
    if sep and not host:
        raise RegionOpError(f"--knockout {spec!r}: nothing after the colon; "
                            f"write MARK:HOST or just MARK to auto-detect")
    return mark, (host or None)


def _resolve_knockouts(specs, labels, tone_names, tone_layers, mult):
    """[(mark, host|None)] -> validated knockout records, in order.

    A knockout is a claim about two regions -- this mark is a gap in that field
    -- and both halves have to be true for the result to be a knockout rather
    than a deletion, so both are checked here and reported as measurements
    rather than assumed.
    """
    labels = np.asarray(labels)
    known = list(dict.fromkeys(tone_names))
    out = []
    for mark, host in specs:
        if mark not in tone_names:
            raise RegionOpError(f"--knockout: {mark!r} is not one of the tones "
                                f"in play; known: {' '.join(known)}")
        m_idx = tone_names.index(mark)
        mask = labels == m_idx
        px = int(mask.sum())
        if px == 0:
            raise RegionOpError(
                f"--knockout {mark}: that tone does not appear in this image, "
                f"so there is nothing to knock out. Present: "
                f"{' '.join(sorted({tone_names[int(v)] for v in np.unique(labels) if v >= 0}))}")

        border = border_tones(mask, labels, tone_names)
        auto = host is None
        if auto:
            cand = [(n, t) for t, n in border.items()
                    if t not in (mark, "alpha", "frame") and tone_layers.get(t)]
            if not cand:
                raise RegionOpError(
                    f"--knockout {mark}: nothing that draws borders this tone, "
                    f"so there is no field for it to be a knockout OF. It "
                    f"borders {_fmt_counts(border)}. Name the host explicitly "
                    f"as {mark}:HOST if you meant something else.")
            host = max(cand)[1]
        if host == mark:
            raise RegionOpError(f"--knockout {mark}:{host} -- a tone cannot be "
                                f"a knockout of itself")
        if host not in tone_names:
            raise RegionOpError(f"--knockout {mark}:{host} -- {host!r} is not "
                                f"one of the tones in play; known: {' '.join(known)}")
        h_layers = tuple(tone_layers.get(host) or ())
        if host == BACKGROUND or not h_layers:
            raise RegionOpError(
                f"--knockout {mark}:{host} -- {host} draws nothing; it IS the "
                f"board. There is no field there to cut a hole in, so the mark "
                f"would just be deleted. Host it in a tone with a layer "
                f"recipe, e.g. T1 (silk) or T2 (ENIG).")

        total = max(1, sum(border.values()))
        floor, prov = tone_floor_mm(h_layers)
        m_layers = tuple(tone_layers.get(mark) or ())
        out.append({
            "mark": mark, "mark_idx": m_idx, "host": host,
            "host_auto": auto, "px": px,
            "suppressed_layers": list(m_layers),
            "host_layers": list(h_layers),
            "host_floor_mm": floor, "host_floor_provisional": prov,
            "knockout_floor_mm": round(floor * float(mult), 4),
            "floor_mult": float(mult),
            "hosted_pct": round(100.0 * border.get(host, 0) / total, 2),
            "border": dict(sorted(border.items(), key=lambda kv: -kv[1])),
            "border_other": {k: v for k, v in border.items() if k != host},
        })
    return out


# --- footprint writer ------------------------------------------------------
def _sexpr_str(s):
    """Escape a Python string for a KiCad quoted s-expression atom.

    `descr` is now caller-supplied (--descr), so it can contain a double quote.
    Interpolating one unescaped ends the atom early and the rest of the string
    is parsed as s-expression source: the file still LOOKS fine in a diff and
    then fails to load, or worse, loads as something else. Newlines are folded
    to spaces for the same reason -- KiCad accepts them, but a one-line descr
    is what every reader of this tree expects.
    """
    return (str(s).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", " ").replace("\r", " "))


class ArtFp(Fp):
    """coupon_ladders.Fp plus arbitrary filled polygons and an art header.

    Subclassed rather than copied: Fp is the working minimal KiCad footprint
    writer already in the tree and there must not be a second one.
    """

    _NS = uuid.UUID("6f1f2e2c-6a4f-5f2a-9b7e-4d6c1a2b3c4d")

    def __init__(self, name, descr=None, tags="recklessart art", with_uuids=False):
        super().__init__(name)
        self.descr = descr or "Art footprint - kicad_art_generator tools/emit_art.py"
        self.tags = tags
        # `uuid` is optional on fp_poly and KiCad mints one on load (verified with
        # kicad-cli fp upgrade). At ~48 bytes a line and thousands of polygons it
        # is the single largest avoidable cost in the file, so it is off by
        # default. `stroke` is kept: relying on the parser's default width would
        # make an outline appear if that default ever changes.
        self.with_uuids = with_uuids

    def _uuid(self):
        self._n += 1
        return str(uuid.uuid5(self._NS, f"{self.name}:{self._n}"))

    @staticmethod
    def _num(v):
        s = f"{v:.{COORD_DP}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s

    def poly(self, pts, layer):
        body = " ".join(f"(xy {self._num(x)} {self._num(y)})" for x, y in pts)
        tail = f'\n\t\t(uuid "{self._uuid()}")' if self.with_uuids else ""
        self.items.append(
            f'\t(fp_poly (pts {body}) (stroke (width 0) (type solid)) '
            f'(fill solid) (layer "{layer}"){tail})'
        )

    def stroke(self, x0, y0, x1, y1, width, layer):
        """fp_line, uuid optional. Fp.line always writes one; a T9 outline is
        thousands of segments, so it gets the same treatment as poly(). The
        inherited Fp.line is untouched -- coupon_blocks.py depends on it."""
        tail = f'\n\t\t(uuid "{self._uuid()}")' if self.with_uuids else ""
        self.items.append(
            f'\t(fp_line (start {self._num(x0)} {self._num(y0)}) '
            f'(end {self._num(x1)} {self._num(y1)}) '
            f'(stroke (width {width:g}) (type solid)) (layer "{layer}"){tail})'
        )

    def stroke_loop(self, pts, width, layer):
        """A closed polyline as fp_line segments.

        fp_line, not fp_poly, on purpose for Edge.Cuts: the board outline is a
        set of strokes the router follows, and fp_line chains are the form the
        proven part (library/RecklessArt.pretty/art_hex_asic_window.kicad_mod)
        uses and that verify_art's closed_loops() reassembles.
        """
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            self.stroke(float(a[0]), float(a[1]), float(b[0]), float(b[1]),
                        width, layer)
        return n

    def text_rot(self, s, x, y, height, layer, thickness=None, *, angle=0.0,
                 allow_below_floor=False):
        """fp_text with a rotation, and with the string escaped.

        Fp.text() has no angle parameter and coupon_blocks.py depends on its
        signature, so this is added here rather than changing it. Two
        differences from the inherited version, both of which matter only once
        text is being placed programmatically rather than as a hand-written
        label:

        - `angle`, so microtext can follow a path.
        - the string is escaped for the s-expression. Fp.text() interpolates it
          raw, which is fine for the fixed labels coupon_ladders writes and is
          not fine for a caller-supplied string: one quote character in it
          produces a .kicad_mod that will not parse.

        The floor guard is deliberately identical, including the thickness=None
        default that raises the stroke to the layer's floor -- that default is
        the fix from coupon_ladders.Fp.text() and it is not being re-opened
        here. tools/microtext.py passes an explicit thickness it has already
        proved legal, which leaves this check live underneath it as a backstop.
        """
        floor, _ = floor_for(layer)
        if thickness is None:
            t = max(height * TEXT_STROKE_RATIO,
                    floor if floor is not None else STROKE_ABS_MIN)
        else:
            t = thickness
            self._floor_check(t, layer, "text stroke", allow_below_floor)
        esc = str(s).replace("\\", "\\\\").replace('"', '\\"')
        at = (f"{x:.4f} {y:.4f}" if abs(angle) < 1e-9
              else f"{x:.4f} {y:.4f} {angle:.4f}")
        tail = f'\n\t\t(uuid "{self._uuid()}")' if self.with_uuids else ""
        self.items.append(
            f'\t(fp_text user "{esc}" (at {at}) (layer "{layer}"){tail}\n'
            f'\t\t(effects (font (size {height:.4f} {height:.4f}) '
            f'(thickness {t:.4f})) (justify left)))'
        )
        return t

    def dumps(self):
        body = "\n".join(self.items)
        return (
            f'(footprint "{self.name}"\n\t(version 20241229)\n\t(generator "emit_art")\n'
            f'\t(layer "F.Cu")\n'
            f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
            f'\t(descr "{_sexpr_str(self.descr)}")\n'
            f'\t(tags "{_sexpr_str(self.tags)}")\n{body}\n)\n'
        )


# --- the emitter ------------------------------------------------------------
def _tone_loops(mask, mm_per_px, ox, oy, tolerance_mm, min_area_mm2):
    """One tone's binary mask -> (outers, buckets, info) in mm.

    `outers` is [(pts, area)]; `buckets[i]` is the list of hole loops belonging
    to outers[i]. Split out of _tone_polygons() because T8 and T9 need the loops
    BEFORE they are keyhole-bridged: a zero-width fracture slit is exactly right
    for a filled mask aperture and exactly wrong for a routed boundary or a
    keepout outline, neither of which is a fill.
    """
    info = {"outers": 0, "holes": 0, "unbridged": 0,
            "area_dropped": 0, "area_dropped_mm2": 0.0}

    loops = trace_contours(mask)
    if not loops:
        return [], [], info

    simplified = []
    for lp in loops:
        mm = np.empty_like(lp)
        mm[:, 0] = (lp[:, 0] + 0.5) * mm_per_px + ox
        mm[:, 1] = (lp[:, 1] + 0.5) * mm_per_px + oy
        simplified.append(rdp_closed(mm, tolerance_mm))

    areas = [signed_area(p) for p in simplified]
    outers = [(p, -a) for p, a in zip(simplified, areas) if a < 0]
    holes = [(p, a) for p, a in zip(simplified, areas) if a > 0]

    if min_area_mm2 > 0:
        kept = []
        for p, a in outers:
            if a < min_area_mm2:
                info["area_dropped"] += 1
                info["area_dropped_mm2"] += a
            else:
                kept.append((p, a))
        outers = kept
        kept = []
        for p, a in holes:
            if a < min_area_mm2:
                info["area_dropped"] += 1
                info["area_dropped_mm2"] += a
            else:
                kept.append((p, a))
        holes = kept

    info["outers"] = len(outers)
    info["holes"] = len(holes)

    # Attach each hole to the SMALLEST outer that contains it. Smallest, not
    # any: with an island inside a hole inside a region, the hole is contained
    # by exactly one outer (its own), while the island is a separate outer that
    # the hole surrounds rather than the reverse.
    boxes = [(p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max())
             for p, _ in outers]
    buckets: list[list] = [[] for _ in outers]
    for hp, _ha in holes:
        hx, hy = float(hp[0, 0]), float(hp[0, 1])
        best, best_a = -1, math.inf
        for i, (op, oa) in enumerate(outers):
            x0, y0, x1, y1 = boxes[i]
            if oa >= best_a or not (x0 <= hx <= x1 and y0 <= hy <= y1):
                continue                      # cheap bbox reject before the ray cast
            if point_in_poly(hp[0], op):
                best, best_a = i, oa
        if best >= 0:
            buckets[best].append(hp)
        else:
            info["unbridged"] += 1

    return outers, buckets, info


def _bridge_loops(outers, buckets, info):
    """(outers, buckets) -> keyhole-bridged simple outlines, ready for fp_poly."""
    polys = []
    for (op, _oa), hs in zip(outers, buckets):
        if hs:
            merged, ub = bridge_holes(op, hs)
            info["unbridged"] += ub
        else:
            merged = op
        pts = _round_dedupe(merged)
        if len(pts) >= 3:
            polys.append(pts)
        else:
            info["area_dropped"] += 1
    return polys


def _tone_polygons(mask, mm_per_px, ox, oy, tolerance_mm, min_area_mm2):
    """One tone's binary mask -> list of outlines in mm, plus bookkeeping."""
    outers, buckets, info = _tone_loops(mask, mm_per_px, ox, oy,
                                        tolerance_mm, min_area_mm2)
    # The hole loops as they stand BEFORE bridging. Every one of them is a gap
    # in this tone's field -- a knockout, whether or not anyone asked for one --
    # and a gap is floored differently from a mark. Kept for the gap audit in
    # emit_detailed(); after bridging they are no longer separable from the
    # outline that swallowed them.
    info["hole_polys"] = [hp for hs in buckets for hp in hs]
    return _bridge_loops(outers, buckets, info), info


# --- T8 / T9 region construction -------------------------------------------

def build_regions(outers, buckets):
    """(outers, buckets) -> [(outer_pts, [island_pts, ...])], unbridged.

    A "region" keeps the outer boundary and its holes SEPARATE, which is what
    both structural tones need: for T9 each is its own routed loop, and for T8
    the keepout outline is drawn the same way a rule area is.
    """
    regions = []
    for (op, _oa), hs in zip(outers, buckets):
        o = _round_dedupe(op)
        if len(o) < 3:
            continue
        islands = [h for h in (_round_dedupe(x) for x in hs) if len(h) >= 3]
        regions.append((o, islands))
    return regions


def build_cut_regions(outers, buckets, fillet_mm, outer_fillet_mm, sagitta_tol,
                      simplify_mm=0.0):
    """Fillet the corners a router bit cannot cut, then close the loops.

    `simplify_mm` is an RDP pass applied BEFORE filleting, and it is not
    optional in practice. Marching squares puts its vertices on half-pixel edge
    midpoints, so a 90-degree raster corner comes out of the tracer as a
    CHAMFER: two 135-degree turns joined by an edge 0.71 px long. Filleting
    that corner vertex by vertex gives two arcs, each with only 0.35 px of edge
    to sit on, so the radius collapses to a third of a pixel and the corner the
    router actually has to negotiate is left untouched. Collapsing the chamfer
    back to a corner first is what makes the requested radius land where it was
    meant to. Nothing real is lost doing it: the routed boundary is followed by
    a 1.6-2.0 mm bit, and a sub-pixel wiggle on it is not a feature any bit can
    resolve. The amount removed is measured and reported.

    Pass 1 is mandatory: corners the VOID is convex at cannot be cut sharp and
    the fab will round them to its own bit radius whether or not we asked. Doing
    it here means the drawing and the board agree.

    Pass 2 is optional (outer_fillet_mm, default 0) and rounds the corners the
    MATERIAL is convex at -- corners the bit cuts around the outside of, where
    the doc says sharp is fine. It exists because verify_art's sharp-corner
    check measures the angle between the two edges and so cannot tell the two
    kinds apart; a caller who wants a clean bill rather than a faithful outline
    can round them too.
    """
    st = {"filleted": 0, "outer_filleted": 0, "reduced": [], "islands": 0,
          "loops": 0, "simplify_mm": float(simplify_mm),
          "verts_in": 0, "verts_simplified": 0}

    def prep(loop):
        a = np.asarray(loop, dtype=np.float64)
        st["verts_in"] += len(a)
        if simplify_mm > 0:
            a = rdp_closed(a, simplify_mm)
        st["verts_simplified"] += len(a)
        return a

    regions = []
    for (op, _oa), hs in zip(outers, buckets):
        # Outer loop: it encloses the VOID, so the void-convex corners are the
        # ones convex w.r.t. what the loop encloses.
        pts, nf, red = fillet_loop(prep(op), fillet_mm, True,
                                   sagitta_tol=sagitta_tol)
        st["filleted"] += nf
        st["reduced"] += red
        if outer_fillet_mm > 0:
            pts, nf2, red2 = fillet_loop(pts, outer_fillet_mm, False,
                                         sagitta_tol=sagitta_tol)
            st["outer_filleted"] += nf2
            st["reduced"] += red2
        pts = _round_dedupe(pts)
        if len(pts) < 3:
            continue
        islands = []
        for h in hs:
            # Hole loop: it encloses an ISLAND OF BOARD standing inside the
            # void, so the void-convex corners are the island's CONCAVE ones.
            hp, nf, red = fillet_loop(prep(h), fillet_mm, False,
                                      sagitta_tol=sagitta_tol)
            st["filleted"] += nf
            st["reduced"] += red
            if outer_fillet_mm > 0:
                hp, nf2, red2 = fillet_loop(hp, outer_fillet_mm, True,
                                            sagitta_tol=sagitta_tol)
                st["outer_filleted"] += nf2
                st["reduced"] += red2
            hp = _round_dedupe(hp)
            if len(hp) >= 3:
                islands.append(hp)
        regions.append((pts, islands))
        st["islands"] += len(islands)
    st["loops"] = sum(1 + len(i) for _, i in regions)
    return regions, st


def region_loops(regions):
    """Every boundary in a region list, outers and islands alike."""
    out = []
    for outer, islands in regions:
        out.append(outer)
        out.extend(islands)
    return out


def points_in_regions(P, regions):
    """(N,) bool -- which points lie in the region interior (outer minus islands)."""
    P = np.asarray(P, dtype=np.float64).reshape(-1, 2)
    hit = np.zeros(len(P), dtype=bool)
    for outer, islands in regions:
        inside = _pip_many(P, outer)
        for isl in islands:
            inside &= ~_pip_many(P, isl)
        hit |= inside
    return hit


def audit_copper_vs_cut(copper, regions, clearance_mm, budget=AUDIT_PAIR_BUDGET):
    """THE TRAP. Which side of the cut does each copper polygon land on?

    KiCad's copper_edge_clearance is a DISTANCE rule and is direction-agnostic:
    a mark sitting comfortably inside a cutout is comfortably far from the cut
    line, so DRC passes it, and then the router removes the slug it is printed
    on. A hand-built hex part in this library did exactly that. Distance alone
    cannot catch it; the side has to be decided explicitly.

    Four things go wrong and all four are checked:
      1. copper on an ISLAND -- board fully enclosed by the cut. It is not the
         slug, but nothing holds it either: it drops out on the router, taking
         the copper with it. A mark placed inside a cutout usually lands here
         rather than in the void proper, because the mark is a different tone
         and so traces as a hole in the cut region.
      2. copper VERTICES inside the void          -- copper on the slug
      3. cut vertices inside a copper polygon     -- copper covering the slug,
         with every copper vertex outside it (a big pour over a small cutout)
      4. copper closer to the boundary than the board rule, on the keep side

    `copper` is [(tone, layer, pts)]. -> report dict; nothing is raised here.
    """
    rep = {"clearance_mm": float(clearance_mm), "checked": 0, "skipped_far": 0,
           "waste": [], "close": [], "pairs": 0, "incomplete": False,
           "min_gap_mm": None}
    loops = region_loops(regions)
    if not loops or not copper:
        return rep

    islands = [isl for _, isls in regions for isl in isls]
    loop_bb = [_bbox(l) for l in loops]
    all_bb = (min(b[0] for b in loop_bb), min(b[1] for b in loop_bb),
              max(b[2] for b in loop_bb), max(b[3] for b in loop_bb))
    loop_pts = np.concatenate(loops, axis=0)

    for tone, layer, pts in copper:
        cb = _bbox(pts)
        if _bbox_gap(cb, all_bb) > clearance_mm:
            rep["skipped_far"] += 1
            continue
        rep["checked"] += 1

        # Distance FIRST, then the side. Order matters: while a polygon still
        # straddles the boundary, "which side is it on" has no answer and a
        # vertex count is only a tally of which way each corner happened to
        # round. Once the gap is known to be non-zero the polygon lies wholly on
        # one side and a single containment test settles it.
        gap = math.inf
        for l, lb in zip(loops, loop_bb):
            if _bbox_gap(cb, lb) > clearance_mm:
                continue
            g, pairs = _polyline_gap(pts, l, budget=budget - rep["pairs"])
            rep["pairs"] += pairs
            if g is None:
                rep["incomplete"] = True
                break
            gap = min(gap, g)
        if math.isfinite(gap) and (rep["min_gap_mm"] is None
                                   or gap < rep["min_gap_mm"]):
            rep["min_gap_mm"] = gap

        why = None
        if gap <= 1e-9:
            why = ("the copper polygon STRADDLES the cut line -- part of it is "
                   "on the slug whichever way the boundary is read")
        else:
            n_isl = sum(int(np.count_nonzero(_pip_many(pts, isl)))
                        for isl in islands)
            if n_isl:
                why = ("it sits on an ISLAND of board fully enclosed by the cut "
                       "-- nothing holds the island, so it drops out on the "
                       "router and takes the copper with it")
            elif points_in_regions(pts[:1], regions)[0]:
                why = "it lies INSIDE the cut, on the slug that gets routed away"
            else:
                near = loop_pts[(loop_pts[:, 0] >= cb[0]) & (loop_pts[:, 0] <= cb[2]) &
                                (loop_pts[:, 1] >= cb[1]) & (loop_pts[:, 1] <= cb[3])]
                if len(near) and _pip_many(near, pts).any():
                    why = "the copper polygon COVERS the cut outline"
        if why:
            rep["waste"].append({"tone": tone, "layer": layer, "why": why,
                                 "gap_mm": (round(gap, 4)
                                            if math.isfinite(gap) else None),
                                 "bbox": [round(v, 4) for v in cb]})
        elif math.isfinite(gap) and gap < clearance_mm - 1e-9:
            rep["close"].append({"tone": tone, "layer": layer,
                                 "gap_mm": round(gap, 4),
                                 "bbox": [round(v, 4) for v in cb]})
    return rep


def audit_copper_vs_window(copper, regions, budget=AUDIT_PAIR_BUDGET):
    """Copper overlapping a T8 window kills it: the light path needs all four
    copper layers absent. Reported, not fatal -- the mask still opens and the
    rest of the art still fabricates; the window just never lights."""
    rep = {"checked": 0, "intrudes": [], "incomplete": False}
    loops = region_loops(regions)
    if not loops or not copper:
        return rep
    loop_bb = [_bbox(l) for l in loops]
    all_bb = (min(b[0] for b in loop_bb), min(b[1] for b in loop_bb),
              max(b[2] for b in loop_bb), max(b[3] for b in loop_bb))
    loop_pts = np.concatenate(loops, axis=0)
    for tone, layer, pts in copper:
        cb = _bbox(pts)
        if _bbox_gap(cb, all_bb) > 0.0:
            continue
        rep["checked"] += 1
        n_in = int(np.count_nonzero(points_in_regions(pts, regions)))
        covers = _pip_many(loop_pts, pts).any()
        if n_in or covers:
            rep["intrudes"].append({
                "tone": tone, "layer": layer,
                "why": (f"{n_in} vertices inside the window" if n_in
                        else "copper covers the window"),
                "bbox": [round(v, 4) for v in cb]})
    return rep


def cut_self_checks(regions, fillet_mm):
    """Slot width and web width, from docs/pcb-palette.md's router table."""
    out = {"narrow_slots": [], "thin_webs": [], "min_slot_mm": None,
           "min_web_mm": None}
    loops = region_loops(regions)
    for k, l in enumerate(loops):
        # min_width over the convex hull is the same measure verify_art uses;
        # it under-reports concave loops and never over-reports.
        w = _hull_min_width(l)
        if w is None:
            continue
        if out["min_slot_mm"] is None or w < out["min_slot_mm"]:
            out["min_slot_mm"] = w
        if w < CUT_SLOT_MIN_MM - 1e-9:
            out["narrow_slots"].append((k, round(w, 4)))
    bbs = [_bbox(l) for l in loops]
    for i in range(len(loops)):
        for j in range(i + 1, len(loops)):
            if _bbox_gap(bbs[i], bbs[j]) > CUT_WEB_MIN_MM:
                continue
            g, _ = _polyline_gap(loops[i], loops[j])
            if g is None or g <= 1e-9:
                continue
            if out["min_web_mm"] is None or g < out["min_web_mm"]:
                out["min_web_mm"] = g
            if g < CUT_WEB_MIN_MM - 1e-9:
                out["thin_webs"].append((i, j, round(g, 4)))
    return out


def _hull_min_width(pts):
    """Minimum width of the convex hull of a loop -- its narrowest span."""
    P = np.asarray(pts, dtype=np.float64)
    if len(P) < 3:
        return None
    # Andrew monotone chain.
    order = np.lexsort((P[:, 1], P[:, 0]))
    S = P[order]
    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) -
                                   (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0])) <= 0:
                h.pop()
            h.append(p)
        return h
    hull = half(S)[:-1] + half(S[::-1])[:-1]
    if len(hull) < 3:
        return 0.0
    H = np.asarray(hull, dtype=np.float64)
    n = len(H)
    best = math.inf
    for i in range(n):
        a, b = H[i], H[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ex, ey)
        if L < 1e-12:
            continue
        d = np.abs(ex * (H[:, 1] - a[1]) - ey * (H[:, 0] - a[0])) / L
        best = min(best, float(d.max()))
    return None if not math.isfinite(best) else best


def _caller_site(levels=1):
    """Where a breaching parameter came from, for the warning text.

    Same intent as coupon_ladders.Fp._caller(): a fabrication warning that does
    not say who asked for the value is a warning nobody can act on. levels=1
    names the caller of the function that calls this.
    """
    try:
        f = sys._getframe(levels + 1)
    except ValueError:
        return "<unknown caller>"
    return (f"{pathlib.Path(f.f_code.co_filename).name}:{f.f_lineno} "
            f"in {f.f_code.co_name}()")


def plan_window_tone(mask, mm_per_px, ox, oy, tolerance_mm, area_floor):
    """T8. -> (apertures, regions, row, warnings, info).

    `apertures` are keyhole-bridged fills for F.Mask and B.Mask. `regions` keep
    the outer/hole split, which is what the Dwgs.User keepout outline wants: a
    rule area is a boundary, not a fill, so it must not be fractured.
    """
    outers, buckets, info = _tone_loops(mask, mm_per_px, ox, oy,
                                        tolerance_mm, area_floor)
    regions = build_regions(outers, buckets)
    apertures = _bridge_loops(outers, buckets, info)
    narrow = [round(w, 4) for w in
              (_hull_min_width(o) for o, _ in regions) if w is not None]
    row = {
        "mode": "T8 window", "layers": list(WINDOW_LAYERS) + [WINDOW_KEEPOUT_LAYER],
        "polys": len(apertures), "verts": int(sum(len(p) for p in apertures)),
        "holes": info["holes"],
        "area_dropped": info["area_dropped"],
        "area_dropped_mm2": round(info["area_dropped_mm2"], 6),
        "min_feature_mm": MIN_FEATURE_MM["F.Mask"],
        "min_area_mm2": area_floor,
        "sub_min_feature": sum(1 for w in narrow if w < MIN_FEATURE_MM["F.Mask"]),
        "note": f"{len(apertures)} aperture(s) on F.Mask+B.Mask, keepout outline "
                f"on {WINDOW_KEEPOUT_LAYER}",
        "min_window_mm": min(narrow) if narrow else None,
    }
    warn = [
        "T8 KEEPOUT IS NOT SELF-CONTAINED: a copper keepout carried by a "
        "FOOTPRINT is silently ignored by the KiCad 10 zone filler -- verified "
        "this session, the plotted gerber is byte-identical to no keepout at "
        "all. Board-level rule areas do work. So a BOARD-LEVEL rule area "
        f"excluding copper on {'/'.join(WINDOW_KEEPOUT_COPPER)} is REQUIRED "
        f"over every window, or the In1 ground pour floods it and the window "
        f"never lights. The outline to trace is on {WINDOW_KEEPOUT_LAYER}.",
        "T8 needs BOTH faces: F.Mask and B.Mask are both opened here. Mask "
        "left on either side kills the effect (docs/pcb-palette.md).",
    ]
    if row["min_window_mm"] is not None and row["min_window_mm"] < 1.0:
        warn.append(
            f"T8: narrowest window is {row['min_window_mm']:.3f} mm across. "
            f"docs/pcb-palette.md gives NO number for this -- it says only "
            f"'bold shapes only, no linework, no detail, no small features', "
            f"because six aligned layer operations stack their registration "
            f"tolerance. Treat anything at this scale as unproven.")
    return apertures, regions, row, warn, info


def plan_cut_tone(mask, mm_per_px, ox, oy, tolerance_mm, area_floor,
                  fillet_mm, outer_fillet_mm, site="<caller>"):
    """T9. -> (regions, row, warnings, info)."""
    outers, buckets, info = _tone_loops(mask, mm_per_px, ox, oy,
                                        tolerance_mm, area_floor)
    # 0.75 px: above the 0.71/2 px a marching-squares corner chamfer departs
    # from the true corner, below the 1 px that would start merging genuinely
    # separate pixel features. See build_cut_regions().
    simplify_mm = max(float(tolerance_mm), 0.75 * mm_per_px)
    regions, st = build_cut_regions(outers, buckets, fillet_mm,
                                    outer_fillet_mm, tolerance_mm,
                                    simplify_mm=simplify_mm)
    checks = cut_self_checks(regions, fillet_mm)
    loops = region_loops(regions)
    row = {
        "mode": "T9 cut", "layers": [CUT_LAYER],
        "polys": len(loops), "verts": int(sum(len(l) for l in loops)),
        "holes": st["islands"],
        "area_dropped": info["area_dropped"],
        "area_dropped_mm2": round(info["area_dropped_mm2"], 6),
        "min_feature_mm": CUT_SLOT_MIN_MM,
        "min_area_mm2": area_floor,
        "sub_min_feature": len(checks["narrow_slots"]),
        "filleted": st["filleted"], "outer_filleted": st["outer_filleted"],
        "simplify_mm": round(simplify_mm, 4),
        "verts_in": st["verts_in"], "verts_simplified": st["verts_simplified"],
        "min_slot_mm": (round(checks["min_slot_mm"], 4)
                        if checks["min_slot_mm"] is not None else None),
        "min_web_mm": (round(checks["min_web_mm"], 4)
                       if checks["min_web_mm"] is not None else None),
        "note": f"{len(loops)} routed loop(s), {st['filleted']} inside corner(s) "
                f"filleted r{fillet_mm:g}",
    }

    warn = []
    if simplify_mm > tolerance_mm + 1e-9 and st["verts_in"]:
        warn.append(
            f"T9: the cut outline was simplified at {simplify_mm:.4g} mm "
            f"(0.75 px) before filleting, {st['verts_in']:,} -> "
            f"{st['verts_simplified']:,} vertices. The tracer leaves a "
            f"half-pixel chamfer at every raster corner and a fillet placed on "
            f"the chamfer collapses to the chamfer's length instead of the "
            f"radius asked for. This coarsens the CUT only -- no other tone is "
            f"touched -- and stays far under the {2*DEFAULT_CUT_FILLET_MM:g} mm "
            f"bit that has to follow it.")
    warn.append(
        f"T9 CUTOUT IS UNCONDITIONAL: footprint-level Edge.Cuts merges into the "
        f"same gerber layer as the board outline, so EVERY board that places "
        f"this footprint gets {len(loops)} loop(s) routed clean through it. "
        f"There is no per-instance switch and no DNP that suppresses it. If "
        f"some boards must not have the hole, this has to be two footprints.")
    if fillet_mm <= 0:
        warn.append(
            f"T9: --cut-fillet-mm is 0, so inside corners are being emitted "
            f"sharp. They cannot be CUT sharp: the fab will fillet every one of "
            f"them to its own bit radius (0.8-1.0 mm) without telling you, and "
            f"the board will not match the drawing -- {site}")
    elif fillet_mm < CUT_FILLET_FLOOR_MM - 1e-9:
        warn.append(
            f"T9: --cut-fillet-mm {fillet_mm:g} is under the {CUT_FILLET_FLOOR_MM} mm "
            f"radius of the smallest bit docs/pcb-palette.md names (1.0 mm dia, "
            f"'at extra cost, ask first'). No standard bit can cut it and the "
            f"fab will open it out to 0.8-1.0 mm -- {site}")
    elif fillet_mm < DEFAULT_CUT_FILLET_MM - 1e-9:
        warn.append(
            f"T9: --cut-fillet-mm {fillet_mm:g} needs a small bit (radius "
            f"{fillet_mm:g} mm => {2*fillet_mm:g} mm dia). The standard 1.6-2.0 mm "
            f"bit cannot reach it; confirm with the fab before committing -- {site}")

    if st["reduced"]:
        worst_r = min(st["reduced"])
        under = sum(1 for r in st["reduced"] if r < CUT_FILLET_FLOOR_MM - 1e-9)
        warn.append(
            f"T9: {len(st['reduced'])} corner(s) could not carry the full "
            f"r{fillet_mm:g} fillet -- the adjoining edges are shorter than the "
            f"arc needs, so the radius was REDUCED there, smallest "
            f"r{worst_r:.3f} mm"
            + (f", and {under} of those fell below the {CUT_FILLET_FLOOR_MM} mm "
               f"bit floor and will be opened out by the fab" if under else "")
            + ". Raise --tolerance-mm or scale the art up to fix it at source.")
    if st["islands"]:
        warn.append(
            f"T9: {st['islands']} island(s) of board are fully enclosed by the "
            f"cut. Nothing holds them: they drop out on the router and leave "
            f"open holes. Either they belong to a different tone or the cut "
            f"needs a bridge.")
    if checks["narrow_slots"]:
        w = min(v for _, v in checks["narrow_slots"])
        warn.append(
            f"T9: {len(checks['narrow_slots'])} loop(s) are narrower than the "
            f"{CUT_SLOT_MIN_MM} mm minimum slot width (= smallest bit diameter), "
            f"narrowest {w:.3f} mm. A slot cannot be routed narrower than the "
            f"bit; these will not be cut.")
    if checks["thin_webs"]:
        g = min(v for _, _, v in checks["thin_webs"])
        warn.append(
            f"T9: {len(checks['thin_webs'])} web(s) of board between two cuts "
            f"are under the {CUT_WEB_MIN_MM} mm the doc calls a floor for "
            f"anything handled, narrowest {g:.3f} mm -- these snap in "
            f"depanelisation.")
    if info["area_dropped"]:
        warn.append(
            f"T9: DROPPED {info['area_dropped']} cut region(s) below "
            f"{area_floor:g} mm2 -- too small to route. Those parts of the "
            f"image are now solid board, not holes.")
    return regions, row, warn, info


def emit_detailed(labels, tone_names, width_mm, name, *,
                  tolerance_mm=DEFAULT_TOLERANCE_MM, min_area_mm2=0.0,
                  tone_layers=None, descr=None, strict=True, with_uuids=False,
                  window_tone=None, cut_tone=None,
                  cut_fillet_mm=DEFAULT_CUT_FILLET_MM, cut_outer_fillet_mm=0.0,
                  copper_edge_mm=DEFAULT_COPPER_EDGE_MM,
                  allow_copper_in_cut=False, courtyard=True,
                  silhouette_tone=None, silhouette_mm=None,
                  knockouts=(), knockout_floor_mult=KNOCKOUT_FLOOR_MULT,
                  gap_audit=True, gap_audit_max=GAP_AUDIT_MAX,
                  fill_mode="solid", luma=None,
                  hatch_pitch_mm=DEFAULT_HATCH_PITCH_MM,
                  hatch_angle_deg=DEFAULT_HATCH_ANGLE_DEG,
                  stipple_pitch_mm=DEFAULT_STIPPLE_PITCH_MM,
                  halftone_levels=DEFAULT_HALFTONE_LEVELS,
                  microtext=None, pal=None, tags=None):
    """Core. Returns (footprint_text, report_dict).

    `pal` is a palette.Palette -- the colourway this part is being assigned
    against. It decides what every tone LOOKS like and therefore every
    lightness-dependent judgement the emitter makes; the geometry does not
    depend on it. None means the black table, which is what everything built
    before colourways existed used. `tags` is written into the footprint so a
    part states its own colourway and the verifier can read it back instead of
    being told again on a command line.

    min_area_mm2 may be a number, or the string "auto" to use each tone's own
    minimum fabricable feature squared (see MIN_FEATURE_MM). Anything it removes
    is reported per tone and as a run-level warning; nothing is dropped quietly.

    `silhouette_tone` reassigns the alpha-derived edge ring to that tone;
    `silhouette_mm` is its width in MILLIMETRES (default: that tone's own
    minimum feature). See the region-boundary section above.

    `knockouts` is a sequence of (mark_tone, host_tone_or_None). Each named mark
    stops being drawn in its own layers and is left as a gap in the host field.
    Independently of that, every hole in every tone is measured against
    `knockout_floor_mult` x the tone's positive floor, because a hole IS a
    knockout and ink bleeds into it from both sides.

    `fill_mode` "hatch" or "stipple" renders each eligible tone as a duty-cycle
    field between the background and that tone instead of as a solid fill, with
    the duty read off `luma` -- the SOURCE relative luminance, same shape as
    `labels`. Without `luma` there is no shading to read and the request is
    refused rather than silently downgraded. See the halftone section above for
    what "eligible" means and what the pitch can and cannot represent.
    """
    labels = np.asarray(labels)
    if labels.ndim != 2:
        raise ValueError(f"labels must be a 2-D array, got shape {labels.shape}")
    tone_layers = TONE_LAYERS if tone_layers is None else tone_layers
    auto_area = isinstance(min_area_mm2, str) and min_area_mm2.lower() == "auto"
    if not auto_area:
        min_area_mm2 = float(min_area_mm2)

    if float(width_mm) <= 0:
        raise ValueError(f"width_mm must be positive, got {width_mm}")
    # Captured here, while our caller's frame is still one hop away, so a
    # fabrication warning about a parameter can name whoever passed it.
    _call_site = _caller_site()
    H, W = labels.shape
    mm_per_px = float(width_mm) / W
    height_mm = H * mm_per_px
    ox, oy = -width_mm / 2.0, -height_mm / 2.0     # centre the art on the origin

    # Silhouette first: it rewrites labels, so everything downstream -- the
    # tone census, the per-tone geometry, the drop checks -- has to see the
    # rewritten array, not the original. mm_per_px is what makes the width
    # physical, which is why this cannot live in load_labels().
    sil_info = None
    if silhouette_tone is not None:
        labels, sil_info = apply_silhouette(labels, tone_names, tone_layers,
                                            silhouette_tone, silhouette_mm,
                                            mm_per_px)
    elif silhouette_mm is not None:
        raise RegionOpError(
            "--silhouette-mm was given without --silhouette-tone; there is no "
            "tone to draw the ring in, so the width would do nothing.")

    present = {int(v): int(n) for v, n in zip(*np.unique(labels, return_counts=True))
               if int(v) >= 0}
    unknown = [v for v in present if v >= len(tone_names)]
    if unknown:
        raise ValueError(f"labels contain indices {unknown} with no entry in tone_names "
                         f"(len={len(tone_names)})")

    if pal is None:
        pal = _pal.palette_for("black", allow_provisional=True)
    # A palette with a STRUCTURAL defect cannot be built against at all: the
    # tone table would be describing something that is not a board. The
    # nearest_anchor kind is deliberately not fatal here -- see
    # palette.Palette.validate() -- because it is a statement about ink the
    # process cannot make, which every dark-mask board has and which a declared
    # tone map is precisely the answer to.
    _bad = [v for v in pal.validate() if v.kind == "structural"]
    if _bad:
        raise ValueError("palette is not usable: "
                         + "; ".join(str(v) for v in _bad))

    fp = ArtFp(name, descr=descr, with_uuids=with_uuids,
               **({"tags": tags} if tags else {}))
    report = {
        "name": name,
        "palette": {"tag": pal.tag(), "digest": pal.digest(),
                    "mask": pal.mask, "silk": pal.silk, "finish": pal.finish,
                    "provisional": sorted(t.id for t in pal.tones
                                          if t.provenance == "PROVISIONAL")},
        "input_px": [W, H],
        "width_mm": float(width_mm),
        "height_mm": round(height_mm, 4),
        "mm_per_px": mm_per_px,
        "tolerance_mm": float(tolerance_mm),
        "tolerance_px": tolerance_mm / mm_per_px,
        "min_area_mm2": "auto" if auto_area else min_area_mm2,
        "tones": [],
        "dropped": [],
        "warnings": [],
        "transparent_px": int((labels < 0).sum()),
        # Where the surface floors in this run came from. One line in the report
        # answers "was the emitter using the doc or its own opinion?", which
        # until now took reading the source to find out.
        "floors": {
            "source": FLOOR_SOURCE,
            "surface_mm": {k: v for k, v in sorted(MIN_FEATURE_MM.items())
                           if k not in BURIED_LAYERS},
            "buried_min_area_mm": MIN_FEATURE_BURIED_MM,
            "buried_checks_mm": BURIED_FLOOR_MM,
            "buried_provisional": True,
        },
    }
    # If the doc could not be read, or disagreed with the built-ins, say so on
    # every run rather than only when coupon_ladders is run as a program.
    for _n in FLOOR_NOTES:
        report["warnings"].append(f"palette floors: {_n}")

    # --- halftone set-up ---------------------------------------------------
    fill_mode = (fill_mode or "solid").lower()
    if fill_mode not in HALFTONE_MODES:
        raise ValueError(f"--fill-mode {fill_mode!r} is not one of "
                         f"{', '.join(HALFTONE_MODES)}")
    ht_pitch = (float(hatch_pitch_mm) if fill_mode == "hatch"
                else float(stipple_pitch_mm))
    report["halftone"] = None
    ht_luma = None
    if fill_mode != "solid":
        if luma is None:
            raise ValueError(
                f"--fill-mode {fill_mode} needs the SOURCE image: duty comes "
                f"from source luminance, and a .npy of labels has already "
                f"thrown that away. Pass the image to --labels instead, or use "
                f"--fill-mode solid.")
        ht_luma = np.asarray(luma, dtype=np.float64)
        if ht_luma.shape != labels.shape:
            raise ValueError(
                f"luma {ht_luma.shape} does not match labels {labels.shape}; "
                f"the duty field has to be sampled on the same raster the "
                f"tones were assigned on")
        _aY = anchor_luma(pal)
        report["halftone"] = {
            "mode": fill_mode, "pitch_mm": ht_pitch,
            "angle_deg": float(hatch_angle_deg) if fill_mode == "hatch" else 0.0,
            "levels": int(halftone_levels),
            "hi_pct": HALFTONE_HI_PCT,
            "min_delta_L": HALFTONE_MIN_DELTA_L,
            "background": BACKGROUND,
            "tones": [], "quads": 0,
            "exempt": [t for t in (window_tone, cut_tone, silhouette_tone) if t],
        }
        # A structural tone is not a surface tone and has no duty cycle: T9 is
        # board that is not there and T8 is board you light through, and neither
        # is "some coverage of an ink over the background". Both are handled
        # before the halftone branch is reached; said here so the exemption is
        # in the report rather than only in the control flow.
        for t in (window_tone, cut_tone):
            if t:
                report["warnings"].append(
                    f"--fill-mode {fill_mode} does not apply to {t}: it is a "
                    f"structural tone (T8 window / T9 cut), not a coverage of "
                    f"ink over the background, so there is no duty to modulate.")
        # The keyline tone is exempt for the same class of reason, and this one
        # had to be decided rather than inherited: --silhouette-tone and
        # --fill-mode were built independently, and combining them halftoned the
        # keyline along with everything else. Measured on Tux at 0.3 mm in T1,
        # the ring came out at duty 0.38-0.62 -- i.e. the outline whose entire
        # purpose is to CLOSE around the figure was rendered as a row of dashes
        # with up to 62% of its length missing. A keyline is a boundary, not a
        # shade; a boundary at 62% duty is a different mark. So the whole tone
        # the ring is drawn in stays solid.
        #
        # The whole tone, not just the ring: splitting one tone into a solid
        # ring plus a halftoned interior would put a seam between them on every
        # boundary they share, and the tone chosen for a keyline is normally one
        # the picture barely uses (T3 is 14 px of Tux before the ring, 0.02%),
        # so there is no shading of consequence being given up.
        if silhouette_tone:
            report["warnings"].append(
                f"--fill-mode {fill_mode} does NOT apply to {silhouette_tone}: "
                f"it carries the --silhouette-tone keyline, and a duty cycle "
                f"turns a closed outline into a dashed one. {silhouette_tone} "
                f"is drawn SOLID. Point --silhouette-tone at a tone you do not "
                f"also want shaded, or drop --fill-mode.")

    if sil_info is not None:
        report["silhouette"] = sil_info
        report["warnings"].extend(sil_info["warnings"])

    # A knockout of a STRUCTURAL tone is refused rather than obeyed. The tone
    # loop tests `idx in ko_by_idx` before it tests --cut-tone / --window-tone,
    # so --knockout T3 --cut-tone T3 used to win the race silently: no
    # Edge.Cuts, report["t9"] is None, no warning, exit 0. The two flags mean
    # incompatible things -- a knockout is "leave this tone out of its host's
    # field", a cut is "remove the board here" and a window is "light through
    # here" -- and neither is the obvious loser, so the ambiguity goes back to
    # whoever wrote the command line instead of being resolved by source order.
    _structural = {t: f for f, t in (("--cut-tone", cut_tone),
                                     ("--window-tone", window_tone)) if t}
    for _m, _h in knockouts:
        if _m in _structural:
            raise RegionOpError(
                f"--knockout {_m}{':' + _h if _h else ''} names the same tone as "
                f"{_structural[_m]} {_m}. A knockout leaves a tone OUT of its "
                f"host's field; a cut removes the board and a window lights "
                f"through it. {_m} cannot be both absent ink and altered "
                f"laminate. Drop one of the two flags, or point them at "
                f"different tones.")

    # Knockouts are resolved against the POST-silhouette labels: a keyline can
    # take the outermost pixels of a mark, and the host it borders is whatever
    # borders it after that.
    ko = _resolve_knockouts(knockouts, labels, tone_names, tone_layers,
                            knockout_floor_mult)
    ko_by_idx = {e["mark_idx"]: e for e in ko}
    if ko:
        report["knockouts"] = ko
    hole_polys: dict[str, list] = {}

    # --- T8 / T9 set-up ----------------------------------------------------
    # Structural tones are resolved by NAME against tone_names, so they land
    # after any --ink-tone remap rather than before it.
    if window_tone is not None and window_tone == cut_tone:
        raise ValueError(
            f"--window-tone and --cut-tone are both {window_tone!r}. A region is "
            f"either laminate you light through or laminate you remove; it "
            f"cannot be both.")
    ids_present = {tone_names[i] for i in present}
    for flag, t in (("--window-tone", window_tone), ("--cut-tone", cut_tone)):
        if t is None:
            continue
        if t not in tone_names:
            raise ValueError(f"{flag} {t!r} is not one of the tone names "
                             f"({', '.join(tone_names)})")
        if t not in ids_present:
            report["warnings"].append(
                f"{flag} {t}: no pixel in this image carries that tone, so no "
                f"geometry was emitted for it. Nothing was lost -- but check "
                f"you named the tone you meant.")
    copper_polys: list[tuple] = []      # (tone, layer, pts), for the cut audit
    cut_regions: list = []
    window_regions: list = []
    report["t8"] = None
    report["t9"] = None
    report["cut_audit"] = None

    for idx in sorted(present):
        tone = tone_names[idx]
        px = present[idx]
        layers = tone_layers.get(tone)
        if layers is None:
            raise ValueError(f"tone {tone!r} has no layer recipe; known: "
                             f"{sorted(tone_layers)}")
        row = {"tone": tone, "px": px, "layers": list(layers),
               "polys": 0, "verts": 0, "holes": 0, "sub_min_feature": 0,
               "background": tone == BACKGROUND}

        if idx in ko_by_idx:
            # Not drawn, on purpose: the gap in the host field IS the mark.
            # Checked BEFORE the background branch, because T5 knocked out of
            # T1 silk is the canonical knockout (SparkFun's labels) and it
            # would otherwise be filed as "background" and never mentioned.
            e = ko_by_idx[idx]
            what = "already drew nothing" if not layers \
                else "suppressed " + "+".join(layers)
            row["knockout_of"] = e["host"]
            row["note"] = f"KNOCKOUT of {e['host']} - not drawn; {what}"
            report["tones"].append(row)
            continue

        # --- structural tones. Checked BEFORE the background branch: --cut-tone
        # T5 (route the background away, leaving the art as the board's own
        # silhouette) is a headline use of T9, and the background branch would
        # otherwise swallow it and emit nothing.
        if tone == cut_tone:
            area_floor = (CUT_SLOT_MIN_MM * CUT_SLOT_MIN_MM if auto_area
                          else float(min_area_mm2))
            cut_regions, bits, warn, info = plan_cut_tone(
                (labels == idx), mm_per_px, ox, oy, tolerance_mm, area_floor,
                cut_fillet_mm, cut_outer_fillet_mm, site=_call_site)
            row.update(bits)
            report["warnings"].extend(warn)
            report["t9"] = {k: bits[k] for k in
                            ("polys", "verts", "holes", "filleted",
                             "outer_filleted", "min_slot_mm", "min_web_mm",
                             "simplify_mm", "verts_in", "verts_simplified")}
            report["t9"]["tone"] = tone
            report["t9"]["fillet_mm"] = float(cut_fillet_mm)
            report["t9"]["outer_fillet_mm"] = float(cut_outer_fillet_mm)
            for loop in region_loops(cut_regions):
                fp.stroke_loop(loop, CUT_STROKE_MM, CUT_LAYER)
            if row["polys"] == 0:
                report["dropped"].append(tone)
            report["tones"].append(row)
            continue

        if tone == window_tone:
            area_floor = (MIN_FEATURE_MM["F.Mask"] ** 2 if auto_area
                          else float(min_area_mm2))
            apertures, window_regions, bits, warn, info = plan_window_tone(
                (labels == idx), mm_per_px, ox, oy, tolerance_mm, area_floor)
            row.update(bits)
            report["warnings"].extend(warn)
            report["t8"] = {k: bits[k] for k in
                            ("polys", "verts", "holes", "min_window_mm")}
            report["t8"]["tone"] = tone
            report["t8"]["mask_layers"] = list(WINDOW_LAYERS)
            report["t8"]["keepout_layer"] = WINDOW_KEEPOUT_LAYER
            report["t8"]["board_rule_area_required_on"] = list(WINDOW_KEEPOUT_COPPER)
            for layer in WINDOW_LAYERS:
                for p in apertures:
                    fp.poly(p, layer)
            # The keepout goes down as an OUTLINE, not a fill: it is the shape
            # a board-level rule area has to be traced over, and a rule area is
            # a boundary. Holes stay separate for the same reason.
            segs = 0
            for outer, islands in window_regions:
                segs += fp.stroke_loop(outer, WINDOW_KEEPOUT_STROKE_MM,
                                       WINDOW_KEEPOUT_LAYER)
                for isl in islands:
                    segs += fp.stroke_loop(isl, WINDOW_KEEPOUT_STROKE_MM,
                                           WINDOW_KEEPOUT_LAYER)
            row["keepout_segs"] = segs
            report["t8"]["keepout_segs"] = segs
            if info["area_dropped"]:
                report["warnings"].append(
                    f"{tone}: DROPPED {info['area_dropped']} window region(s) "
                    f"below {area_floor:g} mm2 -- those parts of the image are "
                    f"now ordinary masked board, not windows.")
            if row["polys"] == 0:
                report["dropped"].append(tone)
            report["tones"].append(row)
            continue

        if tone == BACKGROUND or not layers:
            row["note"] = "background - draws nothing, by design"
            report["tones"].append(row)
            continue

        floor = max(MIN_FEATURE_MM.get(l, 0.1) for l in layers)
        row["min_feature_mm"] = floor
        area_floor = floor * floor if auto_area else float(min_area_mm2)
        row["min_area_mm2"] = area_floor

        tone_mask = (labels == idx)
        ht_quads = []
        if ht_luma is not None and tone == silhouette_tone:
            # Exempt: see the keyline note in the halftone set-up above. Said in
            # this tone's own row too, so the reason travels with the geometry
            # and not only with the run.
            row["fill_mode"] = "solid"
            row["halftone"] = False
            row["note"] = "solid - carries the silhouette keyline"
        elif ht_luma is not None:
            # Halftone. The solid part of the tone still goes through the normal
            # trace/bridge path -- duty 1 IS a solid fill and there is no reason
            # to render it any other way -- and only the intermediate duties
            # become marks.
            solid_polys, ht_quads, plan = halftone_tone(
                tone_mask, ht_luma, tone=tone, layers=layers,
                mm_per_px=mm_per_px, ox=ox, oy=oy, tolerance_mm=tolerance_mm,
                min_area_mm2=area_floor, mode=fill_mode, pitch_mm=ht_pitch,
                angle_deg=hatch_angle_deg, levels=halftone_levels,
                bg_luma=_aY[BACKGROUND], tone_luma=_aY.get(tone, 0.0))
            report["halftone"]["tones"].append(plan)
            report["warnings"].extend(plan["warnings"])
            row["fill_mode"] = fill_mode if plan["on"] else "solid"
            row["halftone"] = plan["on"]
            if plan["on"]:
                row["note"] = (
                    f"{fill_mode} {ht_pitch:g}mm duty "
                    f"{plan['ladder']['duty_min']:.2f}-"
                    f"{plan['ladder']['duty_max']:.2f}")
            else:
                row["note"] = f"solid - {plan['why'].split('.')[0][:52]}"
        # Gated on the ROW, not on `plan`. `plan` is bound inside the halftone
        # branch above, so a tone that skips that branch -- the keyline tone --
        # would either raise NameError or, worse, be tested against the PREVIOUS
        # tone's plan, which is a function-scope local that outlives the
        # iteration. row["halftone"] is set on every path that has an opinion
        # and absent on the ones that do not.
        if row.get("halftone"):
            polys = solid_polys
            info = {"holes": plan["solid_info"]["holes"],
                    "unbridged": plan["solid_info"]["unbridged"],
                    "area_dropped": plan["solid_info"]["area_dropped"],
                    "area_dropped_mm2": 0.0, "hole_polys": []}
        else:
            polys, info = _tone_polygons(mask=tone_mask, mm_per_px=mm_per_px,
                                         ox=ox, oy=oy, tolerance_mm=tolerance_mm,
                                         min_area_mm2=area_floor)
        row["polys"] = len(polys)
        row["verts"] = int(sum(len(p) for p in polys))
        row["holes"] = info["holes"]
        hole_polys[tone] = info.get("hole_polys", [])
        row["area_dropped"] = info["area_dropped"]
        row["area_dropped_mm2"] = round(info["area_dropped_mm2"], 6)
        row["sub_min_feature"] = sum(1 for p in polys if abs(signed_area(p)) < floor * floor)

        if info["unbridged"]:
            report["warnings"].append(
                f"{tone}: {info['unbridged']} hole(s) could not be bridged and are "
                f"filled solid -- geometry is WRONG, inspect the source")
        if info["area_dropped"]:
            report["warnings"].append(
                f"{tone}: DROPPED {info['area_dropped']} region(s) below "
                f"{area_floor:g} mm2 ({row['area_dropped_mm2']:g} mm2, "
                f"{100.0*row['area_dropped_mm2']/max(px*mm_per_px*mm_per_px, 1e-12):.1f}% "
                f"of this tone's area) -- unfabricable at {floor} mm min feature")
        if row["sub_min_feature"]:
            report["warnings"].append(
                f"{tone}: {row['sub_min_feature']} polygon(s) below the {floor} mm "
                f"minimum feature for {'/'.join(layers)} -- will print unreliably")

        if ht_quads:
            # Every layer the recipe names carries the SAME marks. Hatching only
            # one layer of a two-layer recipe would change the tone between the
            # marks, not just its coverage.
            qpts = [q for q, _lv in ht_quads]
            row["quads"] = len(qpts)
            row["polys"] += len(qpts)
            row["verts"] += int(sum(len(p) for p in qpts))
            report["halftone"]["quads"] += len(qpts)
            for layer in layers:
                if COPPER_LAYER_RE.match(layer):
                    copper_polys.extend((tone, layer, p) for p in qpts)
                for p in qpts:
                    fp.poly(p, layer)

        for layer in layers:
            if COPPER_LAYER_RE.match(layer):
                # Stashed for the copper-vs-cut audit below. Every copper layer
                # counts: the board's copper-to-edge rule is not front-only, and
                # a buried In1 mark on a routed-away slug is lost just as surely
                # as a front one.
                copper_polys.extend((tone, layer, p) for p in polys)
            for p in polys:
                fp.poly(p, layer)

        if row["polys"] == 0:
            report["dropped"].append(tone)
        report["tones"].append(row)

    # One warning for the buried-floor split, fired on the layers this run
    # actually drew on rather than on the ones the palette could reach.
    _bw = _buried_floor_warning(
        [l for r in report["tones"] if r["polys"] for l in r["layers"]])
    if _bw:
        report["warnings"].append(_bw)

    # --- gap audit. Every hole in every drawn tone is a knockout whether or not
    # anyone asked for one, and a knockout is not floored like a mark: ink
    # bleeds INWARD across both edges of a gap, so it closes at a width where
    # the same feature drawn positive would merely be fat. See
    # KNOCKOUT_FLOOR_MULT for where the multiplier comes from.
    if gap_audit:
        budget = int(gap_audit_max)
        for row in report["tones"]:
            gaps = hole_polys.get(row["tone"], [])
            if not gaps:
                continue
            floor, prov = tone_floor_mm(row["layers"])
            ko_floor = floor * float(knockout_floor_mult)
            row["gaps"] = len(gaps)
            row["gap_floor_mm"] = round(ko_floor, 4)
            # Narrowest first, so a truncated audit truncates the safe end.
            order = sorted(gaps, key=lambda q: abs(signed_area(q)))
            take = order[:max(0, budget)]
            budget -= len(take)
            widths = [gap_width_mm(p, ko_floor)[0] for p in take]
            bad = [w for w in widths if w < ko_floor - 1e-9]
            row["gaps_measured"] = len(take)
            row["gaps_below_floor"] = len(bad)
            if len(take) < len(gaps):
                row["gap_audit_incomplete"] = True
            if bad:
                report["warnings"].append(
                    f"{row['tone']}: {len(bad)} of {len(gaps)} gap(s) narrower "
                    f"than the {ko_floor:g} mm knockout floor "
                    f"({floor:g} mm{' PROVISIONAL' if prov else ''} positive "
                    f"x{knockout_floor_mult:g}) -- ink bleeds inward and will "
                    f"close them; narrowest {min(bad):.3f} mm across")
            if row.get("gap_audit_incomplete"):
                report["warnings"].append(
                    f"{row['tone']}: gap audit INCOMPLETE -- measured "
                    f"{len(take)} of {len(gaps)} gaps (--gap-audit-max). The "
                    f"unmeasured ones are the largest and least likely to "
                    f"close, but they were not checked")

    # A knockout mark that does not actually border its host is not a gap in
    # that field at all -- it reads as bare board through a hole in nothing.
    for e in ko:
        host_row = next((r for r in report["tones"] if r["tone"] == e["host"]),
                        None)
        e["host_gaps"] = (host_row or {}).get("gaps", 0)
        e["host_gaps_below_floor"] = (host_row or {}).get("gaps_below_floor", 0)
        if e["hosted_pct"] < 99.5:
            report["warnings"].append(
                f"knockout {e['mark']} of {e['host']}: only "
                f"{e['hosted_pct']:.1f}% of the mark's border touches "
                f"{e['host']} (rest: {_fmt_counts(e['border_other'])}). Those "
                f"parts are not gaps in a {e['host']} field and will read as "
                f"bare board, not as {e['host']}-hosted knockout")
        if e["host_gaps"] == 0 and host_row is not None:
            report["warnings"].append(
                f"knockout {e['mark']} of {e['host']}: {e['host']} has no "
                f"holes at all, so nothing was knocked out of it -- the "
                f"{e['px']:,} px of {e['mark']} are simply not drawn")

    # --- microtext ---------------------------------------------------------
    # After the tone loop, so the block mask opening is placed over letterforms
    # and not over anything the tone loop happens to draw afterwards -- and
    # BEFORE the two structural audits below, which is the whole reason it sits
    # here rather than at the end. Microtext draws copper as fp_text, so its ink
    # is invisible to any check that reads polygons; run last, it slipped past
    # the copper-to-cut audit entirely and the audit then reported "no copper
    # within the clearance" about a footprint with copper text in the middle of
    # the slug. tools/microtext.py owns every decision about the text itself --
    # the floors, the counter arithmetic, the rule that the mask opens over the
    # block and never per glyph -- and it raises rather than degrading, so an
    # unbuildable request never reaches the file.
    mt_geom = None
    if microtext is not None:
        import microtext as _mt
        mrep = _mt.emit(fp, microtext)
        mt_geom = mrep.pop("_geometry", None)
        report["microtext"] = mrep
        for x in mrep["warnings"]:
            report["warnings"].append(f"microtext: {x}")
        if mt_geom:
            # Copper letterforms join the audit pool as their ink envelopes. The
            # mask openings are not copper and are not added: a mask opening
            # inside a T9 slug is lost with the slug and costs nothing, whereas
            # copper is the failure that ships.
            mt_tone = mrep["tone"]
            for layer in mt_geom["text_layers"]:
                if COPPER_LAYER_RE.match(layer):
                    copper_polys.extend((f"{mt_tone} microtext", layer, q)
                                        for q in mt_geom["ink"])
            if (cut_regions or window_regions) and not any(
                    COPPER_LAYER_RE.match(l) for l in mt_geom["text_layers"]):
                report["warnings"].append(
                    f"microtext: {mt_tone} puts no copper down "
                    f"({'+'.join(mt_geom['text_layers']) or 'no layers'}), so "
                    f"the copper audits have nothing of it to check. Its mask "
                    f"openings are NOT checked against the cut or the window.")

    # --- copper vs the cut. THE TRAP. -------------------------------------
    # KiCad's copper_edge_clearance is a distance rule and is direction-blind:
    # copper sitting inside a cutout is a comfortable distance from the cut
    # line, so DRC passes it, and then the router takes the slug and the copper
    # with it. A hand-built hex part in this library did exactly that. Distance
    # alone cannot catch it, so the side is decided explicitly here, and it is
    # a hard failure rather than a warning because there is no board on which
    # copper printed onto removed laminate is what someone meant.
    if cut_regions:
        aud = audit_copper_vs_cut(copper_polys, cut_regions, copper_edge_mm)
        report["cut_audit"] = aud
        if aud["incomplete"]:
            report["warnings"].append(
                f"T9: the copper-to-edge audit ran out of its "
                f"{AUDIT_PAIR_BUDGET:,}-pair budget and is INCOMPLETE. The "
                f"unchecked copper is UNVERIFIED, not clean.")
        if aud["close"]:
            worst = min(c["gap_mm"] for c in aud["close"])
            report["warnings"].append(
                f"T9: {len(aud['close'])} copper polygon(s) come within "
                f"{worst:.3f} mm of the cut, under the {copper_edge_mm:g} mm "
                f"copper-to-edge rule (a BOARD rule -- docs/pcb-palette.md "
                f"gives none; {DEFAULT_COPPER_EDGE_MM} mm is SatoshiStarter's. "
                f"Override with --copper-edge-clearance-mm) -- "
                f"{', '.join(sorted({c['tone'] + ' on ' + c['layer'] for c in aud['close']}))}")
        if aud["waste"]:
            hits = "; ".join(
                f"{c['tone']} on {c['layer']} at bbox {c['bbox']}: {c['why']}"
                for c in aud["waste"][:6])
            msg = (f"COPPER ON THE WASTE SIDE: {len(aud['waste'])} polygon(s) "
                   f"are printed on laminate the T9 cut routes away. DRC will "
                   f"NOT catch this -- copper_edge_clearance measures distance "
                   f"to the cut, not which side of it you are on -- and the "
                   f"marks leave with the slug. {hits}")
            if allow_copper_in_cut:
                report["warnings"].append(msg)
            else:
                raise CopperInWaste(msg)

    if window_regions:
        wa = audit_copper_vs_window(copper_polys, window_regions)
        report["window_audit"] = wa
        if wa["intrudes"]:
            report["warnings"].append(
                f"T8: {len(wa['intrudes'])} copper polygon(s) overlap a window "
                f"-- " + ", ".join(sorted({f"{c['tone']} on {c['layer']}"
                                           for c in wa["intrudes"]}))
                + ". The light path needs all four copper layers absent; drawn "
                  "copper inside the aperture blocks it as surely as a pour.")

    # --- courtyard over the art, when there are cuts -----------------------
    # Not decoration. An Edge.Cuts loop inside a footprint is ambiguous on its
    # face: it may be the board's own outline or a hole punched in someone
    # else's board. verify_art.reference_extent() resolves a LONE loop as a
    # board outline and then reports every mark outside it as escaping the
    # board -- which is why art_hex_asic_window.kicad_mod, whose cut is plainly
    # an internal window, currently FAILs the harness. Declaring the extent the
    # footprint actually occupies removes the ambiguity at the source instead
    # of arguing with the reader.
    if cut_regions and courtyard:
        cx0, cy0, cx1, cy1 = ox, oy, ox + width_mm, oy + height_mm
        for a, b in (((cx0, cy0), (cx1, cy0)), ((cx1, cy0), (cx1, cy1)),
                     ((cx1, cy1), (cx0, cy1)), ((cx0, cy1), (cx0, cy0))):
            fp.stroke(a[0], a[1], b[0], b[1], 0.05, "F.CrtYd")
        report["courtyard_mm"] = [round(v, 4) for v in (cx0, cy0, cx1, cy1)]
    elif cut_regions:
        report["warnings"].append(
            "T9: --no-cut-courtyard means this footprint declares no extent. A "
            "reader that finds a single Edge.Cuts loop and nothing else has no "
            "way to tell an internal cutout from a board outline; verify_art "
            "will read it as the board and report the art as escaping it.")

    report["total_polys"] = sum(t["polys"] for t in report["tones"])
    report["total_verts"] = sum(t["verts"] for t in report["tones"])
    # a polygon is written once per layer in the recipe -- except the two
    # structural tones, whose "layers" list includes stroke layers (T8's
    # Dwgs.User keepout, T9's Edge.Cuts) that carry no fills at all.
    def _fp_poly_of(t):
        if t.get("mode") == "T9 cut":
            return 0
        if t.get("mode") == "T8 window":
            return t["polys"] * len(WINDOW_LAYERS)
        return t["polys"] * len(t["layers"])

    # Microtext's own items are counted here rather than left out: the totals
    # are the census of the FILE, and a census that disagrees with the file it
    # describes is not a census. Its block openings are fp_poly like any other
    # fill; its letterforms are fp_text, which is neither a poly nor a line and
    # so gets its own total instead of being folded into one of theirs.
    _mt_rep = report.get("microtext") or {}
    report["total_fp_poly"] = (sum(_fp_poly_of(t) for t in report["tones"])
                               + _mt_rep.get("fp_poly", 0))
    report["total_fp_line"] = (
        sum(t["verts"] for t in report["tones"] if t.get("mode") == "T9 cut")
        + sum(t.get("keepout_segs", 0) for t in report["tones"])
        + (4 if report.get("courtyard_mm") else 0))
    report["total_fp_text"] = _mt_rep.get("fp_text", 0)

    text = fp.dumps()
    report["bytes"] = len(text.encode("utf-8"))

    if not report["tones"]:
        report["warnings"].append("input has no opaque pixels - nothing to emit")

    # A tone that existed only in the edge ring is gone from `present` before
    # the loop ever runs, so the dropped-tone check below cannot see it. That
    # is image content removed by a flag, and it gets the same treatment.
    consumed = (sil_info or {}).get("consumed", [])
    if consumed:
        msg = ("SILHOUETTE CONSUMED TONE(S): "
               + ", ".join(f"{t} ({n:,} px)" for t, n in consumed)
               + f" -- entirely overwritten by the {sil_info['width_mm']:g} mm "
                 f"{sil_info['tone']} keyline")
        if strict:
            raise ToneDropped(msg)
        report["warnings"].append(msg)

    if report["dropped"]:
        px_of = {r["tone"]: r["px"] for r in report["tones"]}
        # The AREA SHARE, not just the pixel count. A dropped tone is only a
        # fidelity problem in proportion to how much of the picture it was:
        # the purple rebuild refused mfb_lockup_3tone over "T3 (181 px) -> 0
        # polygons", which is 0.03 % of the ink. The count alone cannot tell
        # a lost limb from a speck, and the caller's guard needs to.
        _ink = max(sum(px_of.values()), 1)
        report["dropped_share_pct"] = {
            t: round(100.0 * px_of.get(t, 0) / _ink, 4) for t in report["dropped"]}
        msg = ("DROPPED TONE(S): " + ", ".join(
            f"{t} ({px_of[t]:,} px, "
            f"{100.0 * px_of.get(t, 0) / _ink:.3f}% of ink) -> 0 polygons"
            for t in report["dropped"]))
        if strict:
            raise ToneDropped(msg)
        report["warnings"].append(msg)

    # The labels as actually emitted -- the silhouette rewrote them. Callers
    # that render what was built (the CLI's --preview) need this array and not
    # the one they passed in. Underscored and popped before the report is
    # serialised: it is a numpy array, not JSON.
    report["_labels"] = labels
    return text, report


def emit(labels, tone_names, width_mm, name, **kwargs):
    """Interface required by the task: -> footprint text."""
    return emit_detailed(labels, tone_names, width_mm, name, **kwargs)[0]


# --- halftone fills ---------------------------------------------------------
#
# WHY THIS EXISTS. The palette is seven tones and there is no eighth. Everything
# between them has to be made spatially: a periodic field of ink covering a
# fraction d of its cell, over a background that draws nothing, reflects (1-d)
# of the background plus d of the ink, and the eye integrates that into an
# APPARENT tone lying between the two. Duty cycle is the only mechanism this
# palette has for a gradient, and it is the thing that breaks the seven-tone
# ceiling. coupon_ladders.hatch_ladder() and coupon_blocks.shading_fields()
# already emit it as calibration sweeps; this is the conversion mode.
#
# WHICH DIRECTION THE RAMP RUNS. Duty 1 is the tone solid. Duty 0 is the tone
# absent, which on this board means T5 -- bare black mask, the background, the
# one tone that draws nothing. So every ramp here is T5 -> tone, which is
# exactly the pair table in docs/pcb-palette.md ("T5 -> T1 ... highest contrast
# -- the primary ramp", "T5 -> T2 ... second ramp; watch dams"). The doc also
# writes off T5 -> T6 as "too subtle on black mask to be worth it", and that is
# enforced here as a perceptual-separation test, not left to the operator.
#
# ALL LAYERS OF THE RECIPE CARRY THE SAME GEOMETRY. A T2 mark is copper AND a
# coincident mask opening; hatching only the mask would leave copper under
# closed mask between the lines, which is T6 -- a different tone from the one
# that was asked for. So the hatch is written to every layer the recipe names,
# unchanged. What varies is only how much of the region is inked.
#
# WHERE THE DUTY COMES FROM. The SOURCE, not the label. The label already threw
# the shading away -- that is the whole complaint prep_assets.py records against
# little_satoshi ("25% of ink is not flat colour ... Expect banding"). Duty is
# read back off the source luminance inside each tone's own region, normalised
# so the region's own bright end (a high percentile, not the max, which is
# noise) means solid. A gradient in the source is then a duty ramp on the board,
# and a flat field stays flat and solid and costs nothing extra.
#
# WHAT IT CANNOT DO, ONE. Dot gain is not modelled: real ink and real etch both
# spread, so a measured board will read darker in silk and lighter in mask than
# the apparent tones reported here. The coupon exists to measure that; until it
# comes back the numbers below are geometry, not colorimetry.
#
# WHAT IT CANNOT DO, TWO -- and this one is a real residual, stated rather than
# hidden. The dams INSIDE the pattern are guaranteed: across rows the gap is
# pitch minus the mean of two mark widths, which the ladder bounds below by the
# floor; along a row, marks on adjacent duty levels are made to overlap. The dam
# between a mark and the SOLID part of the same tone is not guaranteed, and
# cannot be by construction: the solid region's boundary lies wherever the
# picture puts it, the marks lie on a fixed pitch, and for any pitch there is an
# offset that lands a mark's edge a fraction of the floor away from that
# boundary. Marks that END on the boundary are joined into the solid (they are
# extended a floor's width past it, so the two are one feature and there is no
# dam to wash out); what survives is the corner case, where a run leaves the
# region through a different edge and passes near the solid's corner without
# meeting it. On the synthetic gradient that is 1 pair in 677 items, at 0.086 mm
# against a 0.150 mm silk floor. The consequence of losing it is that one line's
# tip merges into the solid -- not a dropout, not a tone collapse. The two ways
# to remove it outright are worse than it is: suppress every mark within a floor
# of the solid, which cuts a visible dark keyline round every highlight, or
# grow the solid to swallow them, which fattens every highlight by a floor.
# verify_art.py's clearance check measures this class exactly; run it and read
# the count rather than assuming either way.

def relative_luminance(rgb):
    """sRGB -> CIE relative luminance Y (linear light), 0..1.

    Linear light and NOT L*, because a halftone averages by AREA and area
    averaging is linear in Y. Mixing duty in L* instead puts the half-duty point
    about six L* too light, which is a visible error on the T5->T1 ramp.
    """
    a = np.asarray(rgb, dtype=np.float64) / 255.0
    a = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return (0.2126729 * a[..., 0] + 0.7151522 * a[..., 1]
            + 0.0721750 * a[..., 2])


def lstar(Y):
    """Relative luminance -> CIE L*. Reporting only: L* is the space in which
    'how different do these two tones look' is a meaningful question."""
    Y = np.asarray(Y, dtype=np.float64)
    e, k = 216.0 / 24389.0, 24389.0 / 27.0
    f = np.where(Y > e, np.cbrt(np.maximum(Y, 0.0)), (k * Y + 16.0) / 116.0)
    return 116.0 * f - 16.0


def anchor_luma(pal=None):
    """Tone id -> relative luminance of its anchor in THIS colourway.

    Takes a palette.Palette. With none it falls back to the black table, which
    is what every part built before colourways existed was assigned against, so
    an untagged legacy part keeps measuring the same.

    The anchors are estimates until the reference board is photographed -- see
    docs/pcb-palette.md lines 194-198 -- so everything derived from them here
    is ordinal.
    """
    if pal is None:
        pal = _pal.palette_for("black", allow_provisional=True)
    return {t.id: float(relative_luminance(np.array(t.rgb, dtype=np.float64)))
            for t in pal.tones}


def duty_ladder(mode, pitch_mm, floor_mm, levels, *, dam_mm=None):
    """What duty cycles a pitch can ACTUALLY image on a layer with this floor.

    A halftone is bounded from both sides and both bounds are in
    docs/pcb-palette.md:

      * the MARK must be at least the layer's minimum feature. Below it the line
        or dot images as nothing, the field reads as flat background, and the
        halftone has lied about the tone it claims to render.
      * the DAM between marks must be at least the minimum gap, "or it washes
        away in processing -- at which point the hatch merges into one solid
        opening and the tone jumps to flat T2". Same arithmetic caps silk, where
        the doc's knockout note says ink bleeds inward and closes a fine gap.

    verify_art.py's clearance check applies each layer's own floor to gaps as
    well as to features, so mark floor and dam floor are the same number unless
    a caller separates them.

    So the representable duties are {0} u [d_min, d_max] u {1}: zero is bare
    background and one is solid, both perfectly fabricable, and the interval
    between them is everything the pitch can hold. Returned as an explicit
    ladder because the doc is emphatic that the ramp has to be quantised BEFORE
    it is segmented -- 25 levels cost 238 kB where 8 cost 76.

    ["ok"] False means this pitch cannot hold any duty at all; the caller must
    fall back to solid rather than emit a pattern that images as nothing.
    """
    p = float(pitch_mm)
    # The ladder is built a micron INSIDE both floors; see _FLOOR_MARGIN_MM.
    f = float(floor_mm) + _FLOOR_MARGIN_MM
    g = (float(floor_mm) if dam_mm is None else float(dam_mm)) + _FLOOR_MARGIN_MM
    # feature_floor_mm / dam_floor_mm are the values the ladder was BUILT to,
    # i.e. the fabrication floor plus the write-out margin. floor_mm is the
    # fabrication number itself, so a reader is never handed 0.151 as though
    # the fab had said it.
    out = {"mode": mode, "pitch_mm": p, "floor_mm": float(floor_mm),
           "feature_floor_mm": f,
           "dam_floor_mm": g, "levels": int(levels), "ok": False, "why": None,
           "duty_min": 0.0, "duty_max": 0.0,
           "duties": [], "feature_mm": [], "dam_mm": []}
    if p <= 0:
        out["why"] = f"pitch {p:g} mm is not positive"
        return out

    if mode == "hatch":
        # width w over pitch p; duty = w/p, dam = p - w.
        def feat(d):
            return d * p
        d_min, d_max = f / p, 1.0 - g / p
    elif mode == "stipple":
        # square dot of side s on a square grid of pitch p; duty = (s/p)^2, and
        # the orthogonal dam p - s is the binding one (the diagonal gap between
        # two dots is sqrt(2)(p - s), always larger).
        def feat(d):
            return math.sqrt(max(d, 0.0)) * p
        d_min, d_max = (f / p) ** 2, ((p - g) / p) ** 2
    else:
        raise ValueError(f"unknown halftone mode {mode!r}; "
                         f"known: {' '.join(HALFTONE_MODES)}")

    if d_max <= d_min:
        out["duty_min"], out["duty_max"] = d_min, d_max
        out["why"] = (f"a {p:.3f} mm {mode} pitch cannot hold a {f:.3f} mm mark "
                      f"AND a {g:.3f} mm dam -- it needs more than "
                      f"{f + g:.3f} mm of pitch")
        return out

    n = max(int(levels), 2)
    duties = ([0.0]
              + [d_min + (d_max - d_min) * i / (n - 1) for i in range(n)]
              + [1.0])
    out.update(ok=True, duty_min=d_min, duty_max=d_max, duties=duties,
               feature_mm=[feat(d) for d in duties],
               dam_mm=[p - feat(d) for d in duties])
    return out


def _rot_xy(x, y, ang_deg):
    c, s = math.cos(math.radians(ang_deg)), math.sin(math.radians(ang_deg))
    return x * c - y * s, x * s + y * c


def _clip_loops(mask, mm_per_px, ox, oy):
    """Region contours in mm, DELIBERATELY UNSIMPLIFIED.

    RDP is right for a polygon that gets filled and wrong for one that is only a
    clip boundary. Two adjacent duty levels share their boundary exactly --
    marching squares puts both contours on the same half-pixel edge -- and
    simplifying each independently moves them apart by up to the tolerance,
    leaving a 0-0.05 mm slot between the two levels' marks on every scan line
    that crosses the boundary. That is a sub-floor gap on every level boundary in
    the picture, which is precisely the failure the dam floor exists to prevent.
    Unsimplified, the two spans meet at the same x, the marks abut, and abutting
    marks are one feature with no dam to wash away.

    The cost is vertices in the clip, not in the output: what gets written is the
    quads, and their corners are computed, not traced.
    """
    out = []
    for lp in trace_contours(mask):
        mm = np.empty_like(lp)
        mm[:, 0] = (lp[:, 0] + 0.5) * mm_per_px + ox
        mm[:, 1] = (lp[:, 1] + 0.5) * mm_per_px + oy
        out.append(mm)
    return out


def _clip_edges(loops, angle_deg):
    """Loops -> flat rotated edge arrays (ax, ay, bx, by) for the scan line.

    Every loop of the region goes in, outer and hole alike: the span test below
    is even-odd over ALL of them, which is what makes a hole a hole without
    anyone having to classify it first. Requirement 4 -- hatching clips cleanly
    through holes -- therefore falls out of crossing parity rather than out of a
    special case, and it cannot be got wrong for a hole inside a hole either.

    Rotating by -angle puts the hatch lines on the horizontal, so the whole
    clip is one scan line problem whatever angle was asked for.
    """
    if not loops:
        return None
    A, B = [], []
    for lp in loops:
        rx, ry = _rot_xy(lp[:, 0], lp[:, 1], -angle_deg)
        p = np.stack([rx, ry], axis=1)
        A.append(p)
        B.append(np.roll(p, -1, axis=0))
    a = np.concatenate(A)
    b = np.concatenate(B)
    return (a[:, 0].copy(), a[:, 1].copy(), b[:, 0].copy(), b[:, 1].copy())


def _edges_y_range(edges):
    if edges is None:
        return None
    _ax, ay, _bx, by = edges
    return float(min(ay.min(), by.min())), float(max(ay.max(), by.max()))


def _row_spans(edges, y):
    """x-intervals in which the horizontal line `y` is inside the region.

    Half-open straddle test ((ay > y) != (by > y)), so a vertex sitting exactly
    on the line is counted once rather than twice or not at all -- the same rule
    point_in_poly() uses, and the reason the parity never goes odd.
    """
    if edges is None:
        return []
    ax, ay, bx, by = edges
    st = (ay > y) != (by > y)
    if not st.any():
        return []
    i = np.nonzero(st)[0]
    t = (y - ay[i]) / (by[i] - ay[i])
    x = np.sort(ax[i] + t * (bx[i] - ax[i]))
    n = len(x) - (len(x) & 1)
    return [(float(x[k]), float(x[k + 1])) for k in range(0, n, 2)]


def _covers(spans, a, b):
    for (x0, x1) in spans:
        if x0 <= a + 1e-9 and x1 >= b - 1e-9:
            return True
    return False


def _absorb_stubs(spans, floor_mm):
    """Runs shorter than the mark floor merged into a touching neighbour.

    A 0.04 mm long piece of a 0.15 mm wide silk line is not a feature, it is a
    speck, and emitting it would be exactly the vanishing mark this whole module
    refuses to emit. Dropping it outright is worse though: it used to touch the
    runs on either side, so removing it opens a sub-floor slot where there was
    none. So a stub is absorbed into whichever neighbour it touches -- the tone
    error is bounded by the floor and the geometry stays legal. A stub touching
    nothing has no neighbour to join, and is dropped and COUNTED.
    """
    out, absorbed, dropped, drop_mm = [], 0, 0, 0.0
    work = [list(s) for s in spans]
    n = len(work)
    for i in range(n):
        x0, x1, lv = work[i]
        if x1 - x0 >= floor_mm - 1e-9:
            out.append([x0, x1, lv])
            continue
        if out and x0 - out[-1][1] <= _SPAN_TOUCH:
            out[-1][1] = max(out[-1][1], x1)
            absorbed += 1
        elif i + 1 < n and work[i + 1][0] - x1 <= _SPAN_TOUCH:
            work[i + 1][0] = min(work[i + 1][0], x0)
            absorbed += 1
        else:
            dropped += 1
            drop_mm += x1 - x0
    return out, absorbed, dropped, drop_mm


def _hatch_quads(level_edges, level_w, solid_edges, pitch_mm, angle_deg,
                 floor_mm, y_lo, y_hi):
    """Parallel-line halftone. -> (quads, info); quads are [(pts, level)].

    Emitted as filled quads and not as fp_line strokes, for two reasons that are
    not style. A stroked line carries round caps, so a line clipped at the
    region contour bulges half a stroke width past it and the clip is not clean.
    And a line holds exactly one width, so tonal variation along it needs the
    line split anyway -- at which point the quad is the cheaper object, because
    it also states its own ends exactly.

    Rows sit at absolute multiples of the pitch, NOT at multiples measured from
    each region's own bounding box. Every duty level of every tone therefore
    lands on one shared grid, which is what makes marks on adjacent levels abut
    instead of interleaving, and what keeps the dam between two rows equal to
    pitch minus the mean of their two widths -- bounded by the ladder, and so
    bounded everywhere the picture goes.
    """
    info = {"rows": 0, "runs": 0, "stubs_absorbed": 0, "stubs_dropped": 0,
            "stub_mm": 0.0, "solid_joins": 0}
    ink = {}
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    quads = []
    k0 = int(math.floor(y_lo / pitch_mm)) - 1
    k1 = int(math.ceil(y_hi / pitch_mm)) + 1
    for k in range(k0, k1 + 1):
        y = k * pitch_mm
        spans = []
        for lv, ed in level_edges.items():
            for (a, b) in _row_spans(ed, y):
                spans.append([a, b, lv])
        if not spans:
            continue
        spans.sort(key=lambda t: (t[0], t[1]))
        merged = []
        for sp in spans:
            if (merged and merged[-1][2] == sp[2]
                    and sp[0] - merged[-1][1] <= _SPAN_TOUCH):
                merged[-1][1] = max(merged[-1][1], sp[1])
            else:
                merged.append(list(sp))
        merged, ab, dr, dmm = _absorb_stubs(merged, floor_mm)
        info["stubs_absorbed"] += ab
        info["stubs_dropped"] += dr
        info["stub_mm"] += dmm
        if not merged:
            continue
        # Force two abutting marks to actually overlap. See _SPAN_OVERLAP: they
        # meet at exactly one x before the rotation and the round, and a hair
        # either side of it afterwards.
        for a, b in zip(merged, merged[1:]):
            if abs(b[0] - a[1]) <= _SPAN_TOUCH:
                a[1] += _SPAN_OVERLAP
                b[0] -= _SPAN_OVERLAP
        info["rows"] += 1
        sol = _row_spans(solid_edges, y)
        for (x0, x1, lv) in merged:
            # Join to a solid neighbour on the same row rather than stopping a
            # hair short of it. The solid region is emitted as an RDP-simplified
            # polygon and this clip is not, so the two boundaries agree only to
            # the tolerance; overlapping by a whole floor makes them one feature
            # instead of two with an unmeasurably thin dam between them.
            for (sa, sb) in sol:
                if x0 - floor_mm <= sb <= x0:
                    x0 = sb - floor_mm
                    info["solid_joins"] += 1
                if x1 <= sa <= x1 + floor_mm:
                    x1 = sa + floor_mm
                    info["solid_joins"] += 1
            h = level_w[lv] / 2.0
            xs = np.array([x0, x1, x1, x0])
            ys = np.array([y - h, y - h, y + h, y + h])
            qx, qy = xs * c - ys * s, xs * s + ys * c
            pts = _round_dedupe(np.stack([qx, qy], axis=1))
            if len(pts) >= 3:
                quads.append((pts, lv))
                info["runs"] += 1
                ink[lv] = ink.get(lv, 0.0) + (x1 - x0) * level_w[lv]
    return quads, info, ink


def _stipple_quads(level_edges, level_s, pitch_mm, y_lo, y_hi):
    """Isolated-dot halftone, square dots on a square grid. -> (quads, info).

    docs/pcb-palette.md ranks this technique LAST -- "silk dots near the minimum
    size print inconsistently and drop out" -- and it is offered because the
    coupon sweeps it and somebody will want to compare, not because it is the
    right default. Squares rather than circles: a circle costs a dozen vertices
    to say what four say, its min width under verify_art's rotating calipers is
    the same, and coupon_blocks.shading_fields() already stipples in squares.

    A dot is emitted only if the WHOLE dot is inside the region -- centre inside
    is not enough, because a dot half over the contour spills its own width past
    the edge of the shape it is shading. Dots dropped for that reason are
    counted, never silently skipped.
    """
    info = {"rows": 0, "dots": 0, "edge_dropped": 0, "spans_too_narrow": 0,
            "narrow_mm": 0.0}
    ink = {}
    quads = []
    k0 = int(math.floor(y_lo / pitch_mm)) - 1
    k1 = int(math.ceil(y_hi / pitch_mm)) + 1
    for k in range(k0, k1 + 1):
        y = k * pitch_mm
        row_used = False
        for lv, ed in level_edges.items():
            s = level_s[lv]
            h = s / 2.0
            mid = _row_spans(ed, y)
            if not mid:
                continue
            lo = _row_spans(ed, y - h)
            hi = _row_spans(ed, y + h)
            for (a, b) in mid:
                i0 = int(math.ceil((a + h) / pitch_mm))
                i1 = int(math.floor((b - h) / pitch_mm))
                if i1 < i0:
                    # No grid position in this run can hold a whole dot. Counted:
                    # a run narrower than the dot it would carry is region the
                    # stipple grid simply cannot reach, and that is content
                    # going missing, not a rounding detail.
                    info["spans_too_narrow"] += 1
                    info["narrow_mm"] += b - a
                for i in range(i0, i1 + 1):
                    cx = i * pitch_mm
                    if not (_covers(lo, cx - h, cx + h)
                            and _covers(hi, cx - h, cx + h)):
                        info["edge_dropped"] += 1
                        continue
                    pts = _round_dedupe(np.array(
                        [[cx - h, y - h], [cx + h, y - h],
                         [cx + h, y + h], [cx - h, y + h]]))
                    if len(pts) >= 3:
                        quads.append((pts, lv))
                        info["dots"] += 1
                        ink[lv] = ink.get(lv, 0.0) + s * s
                        row_used = True
        if row_used:
            info["rows"] += 1
    return quads, info, ink


def halftone_tone(mask, luma, *, tone, layers, mm_per_px, ox, oy,
                  tolerance_mm, min_area_mm2, mode, pitch_mm, angle_deg,
                  levels, bg_luma, tone_luma):
    """One tone as a duty-modulated field. -> (solid_polys, quads, plan).

    plan["on"] False means the tone could not or should not be halftoned and the
    caller must draw it solid; plan["why"] says which, in words, every time.
    Nothing here ever quietly falls back.
    """
    floor, prov = tone_floor_mm(layers)
    plan = {"tone": tone, "mode": mode, "on": False, "why": None,
            "layers": list(layers), "pitch_mm": float(pitch_mm),
            # Stipple is axis-aligned on purpose -- a rotated dot grid buys
            # nothing (a dot has no direction to beat against the raster) and
            # would only make the reported angle a fiction.
            "angle_deg": float(angle_deg) if mode == "hatch" else 0.0,
            "floor_mm": floor,
            "floor_provisional": bool(prov), "warnings": [],
            "px": int(mask.sum())}

    l_tone, l_bg = float(lstar(tone_luma)), float(lstar(bg_luma))
    plan["delta_L"] = round(l_tone - l_bg, 2)
    if abs(l_tone - l_bg) < HALFTONE_MIN_DELTA_L:
        plan["why"] = (
            f"{tone} and the {BACKGROUND} background are only "
            f"{abs(l_tone - l_bg):.1f} L* apart, under the "
            f"{HALFTONE_MIN_DELTA_L:g} L* worth-doing line -- "
            f"docs/pcb-palette.md calls this ramp 'too subtle on black mask to "
            f"be worth it'. Drawn SOLID; the halftone would have cost geometry "
            f"to render a difference nobody can see.")
        return [], [], plan

    lad = duty_ladder(mode, pitch_mm, floor, levels)
    plan["ladder"] = lad
    if not lad["ok"]:
        site = _caller_site(2)
        msg = (f"FLOOR: {tone} on {'/'.join(layers)}: {lad['why']}; the floor is "
               f"{floor:g} mm{' PROVISIONAL' if prov else ''}. Drawn SOLID -- "
               f"the pattern is NOT thinned to fit, because a mark under the "
               f"floor images as nothing and a hatch that images as nothing is "
               f"worse than a flat tone. Asked for at {site}")
        plan["why"] = msg
        plan["warnings"].append(msg)
        sys.stderr.write("!! " + msg + "\n")
        return [], [], plan

    vals = luma[mask]
    if vals.size == 0:
        plan["why"] = f"{tone}: no pixels"
        return [], [], plan
    y_hi = float(np.percentile(vals, HALFTONE_HI_PCT))
    span = y_hi - bg_luma
    plan["source"] = {
        "y_background": bg_luma, "y_tone_anchor": tone_luma,
        "y_hi": y_hi, "hi_pct": HALFTONE_HI_PCT,
        "y_p02": float(np.percentile(vals, 2.0)),
        "y_median": float(np.median(vals)),
        "L_hi": round(float(lstar(y_hi)), 2),
        "L_p02": round(float(lstar(np.percentile(vals, 2.0))), 2),
    }
    if span <= 1e-6:
        plan["why"] = (
            f"{tone}: the source inside this region is no brighter than the "
            f"{BACKGROUND} background it would be modulated against, so there "
            f"is no ramp to build. Drawn SOLID.")
        return [], [], plan

    # Duty from the source, normalised over the region's own range: background
    # luminance means duty 0, the region's own 98th percentile means duty 1. Not
    # the palette anchor: real art is off-palette (satoshi's gold sits 38
    # weighted-Lab units from every anchor, per w0_spike), and normalising to
    # the anchor would put a flat off-palette field at some fractional duty and
    # texture the whole thing for no tonal information at all.
    duty = np.clip((luma - bg_luma) / span, 0.0, 1.0)

    duties = np.asarray(lad["duties"], dtype=np.float64)
    dm = duty[mask]
    lv_of = np.abs(dm[:, None] - duties[None, :]).argmin(1).astype(np.int16)
    err = duties[lv_of] - dm
    lvl = np.full(mask.shape, -1, dtype=np.int16)
    lvl[mask] = lv_of

    counts = np.bincount(lv_of, minlength=len(duties))
    top = len(duties) - 1
    n_px = int(mask.sum())
    # Apparent tone of each rung, the number requirement 3 asks for: coverage
    # duty of the tone anchor over the background anchor, averaged in linear
    # light, reported in L* because that is where "how light does it look" is a
    # question with an answer.
    app_Y = [bg_luma + d * (tone_luma - bg_luma) for d in lad["duties"]]
    plan["levels_detail"] = [
        {"i": i, "duty": round(float(d), 4),
         "feature_mm": round(float(lad["feature_mm"][i]), 4),
         "dam_mm": round(float(lad["dam_mm"][i]), 4),
         "apparent_L": round(float(lstar(app_Y[i])), 2),
         "px": int(counts[i])}
        for i, d in enumerate(lad["duties"])]
    plan["apparent_L_range"] = [round(float(lstar(app_Y[0])), 2),
                                round(float(lstar(app_Y[-1])), 2)]
    plan["apparent_L_hatched"] = [round(float(lstar(app_Y[1])), 2),
                                  round(float(lstar(app_Y[top - 1])), 2)]
    plan["snap_rms_duty"] = round(float(np.sqrt(np.mean(err ** 2))), 4)
    plan["snap_max_duty"] = round(float(np.max(np.abs(err))), 4)
    plan["px_blank"] = int(counts[0])
    plan["px_solid"] = int(counts[top])
    plan["px_hatched"] = int(n_px - counts[0] - counts[top])
    plan["px_wanted_below_min"] = int(np.count_nonzero(
        (dm > 0.0) & (dm < lad["duty_min"])))
    plan["px_wanted_above_max"] = int(np.count_nonzero(
        (dm > lad["duty_max"]) & (dm < 1.0)))

    if counts[0]:
        plan["warnings"].append(
            f"{tone}: {int(counts[0]):,} px ({100.0 * counts[0] / max(n_px, 1):.1f}% "
            f"of the tone) wanted a duty under {lad['duty_min']:.3f}, which is "
            f"the thinnest mark a {pitch_mm:g} mm pitch can carry at the "
            f"{floor:g} mm{' PROVISIONAL' if prov else ''} floor. They are drawn "
            f"as NOTHING -- the next duty step down, bare {BACKGROUND} board -- "
            f"rather than as a mark too fine to image.")
    if plan["px_wanted_above_max"]:
        plan["warnings"].append(
            f"{tone}: {plan['px_wanted_above_max']:,} px wanted a duty above "
            f"{lad['duty_max']:.3f}, the densest pattern that still leaves a "
            f"{floor:g} mm dam at {pitch_mm:g} mm pitch. Each snapped to the "
            f"nearer of {lad['duty_max']:.3f} and solid; that band of apparent "
            f"tone (L* {lstar(app_Y[top - 1]):.0f} to {lstar(app_Y[top]):.0f}) "
            f"is not renderable at this pitch and no pitch makes it so without "
            f"the dams washing out.")

    solid_mask = mask & (lvl == top)
    solid_polys, sinfo = _tone_polygons(
        mask=solid_mask, mm_per_px=mm_per_px, ox=ox, oy=oy,
        tolerance_mm=tolerance_mm, min_area_mm2=min_area_mm2)
    plan["solid_info"] = {k: sinfo[k] for k in
                          ("outers", "holes", "unbridged", "area_dropped")}

    # SHATTERING. A duty step that lands inside a field the source made almost
    # uniform does not draw a band across it -- it dices it. The pixels either
    # side of the step interleave at the noise scale, so the solid part comes
    # out as thousands of specks, each of them under the floor, in place of the
    # handful of polygons the flat fill would have written. On mfb_node_full
    # that turns 14 T2 polygons into 1,926 and the file from 58 kB to 912 kB,
    # for a tone difference of one duty step. It is worth naming as its own
    # failure rather than leaving it to be inferred from a sub-min-feature
    # count, because the remedy is different and is not obvious: changing the
    # pitch barely moves it (0.4 -> 1.2 mm takes mfb_node_full from 912 to 724
    # kB) and neither does changing the level count, because the step that dices
    # the field is the one between the densest pattern and solid, which the
    # ladder always carries. --min-area-mm2 auto does fix it -- 912 kB back to
    # 104 kB -- because every speck it removes is under the floor and was never
    # going to image. That is the advice given below.
    tiny = sum(1 for p in solid_polys if abs(signed_area(p)) < floor * floor)
    plan["solid_tiny"] = tiny
    if len(solid_polys) >= 20 and tiny >= 0.5 * len(solid_polys):
        plan["warnings"].append(
            f"{tone}: SHATTERED -- the duty partition split the solid part of "
            f"this tone into {len(solid_polys):,} polygons, {tiny:,} of them "
            f"under the {floor:g} mm{' PROVISIONAL' if prov else ''} floor. "
            f"That is a duty step falling inside a field the source left almost "
            f"uniform ({plan['px_solid']:,} px solid against "
            f"{plan['px_hatched']:,} px patterned), so it dices the field "
            f"instead of banding it. Every one of those specks is under the "
            f"floor and none of them will image, so re-run with --min-area-mm2 "
            f"auto to drop them (reported, not silent) -- or with --fill-mode "
            f"solid if this asset has no shading worth the geometry. A coarser "
            f"pitch or fewer levels will NOT help: the step doing the dicing is "
            f"the one between the densest pattern and solid, and the ladder "
            f"always carries it.")

    hatch_angle = float(angle_deg) if mode == "hatch" else 0.0
    level_edges, level_w = {}, {}
    for li in range(1, top):
        if counts[li] == 0:
            continue
        loops = _clip_loops(mask & (lvl == li), mm_per_px, ox, oy)
        ed = _clip_edges(loops, hatch_angle)
        if ed is None:
            continue
        level_edges[li] = ed
        level_w[li] = float(lad["feature_mm"][li])
    solid_edges = _clip_edges(_clip_loops(solid_mask, mm_per_px, ox, oy),
                              hatch_angle) if solid_mask.any() else None

    quads, ginfo, ink = [], {}, {}
    if level_edges:
        rng = [_edges_y_range(e) for e in level_edges.values()]
        y_lo = min(r[0] for r in rng)
        y_hi_r = max(r[1] for r in rng)
        if mode == "hatch":
            # floor + margin, not the bare floor: a run exactly `floor` long
            # would make a mark whose SHORT side is the floor and whose long
            # side is the floor, and it would come back from the 4-dp round a
            # fraction under, for the same reason the ladder is built inside the
            # floor. The same value sets how far a run reaches into the solid.
            quads, ginfo, ink = _hatch_quads(
                level_edges, level_w, solid_edges, float(pitch_mm), hatch_angle,
                floor + _FLOOR_MARGIN_MM, y_lo, y_hi_r)
        else:
            quads, ginfo, ink = _stipple_quads(level_edges, level_w,
                                               float(pitch_mm), y_lo, y_hi_r)
    plan["geometry"] = ginfo

    # INK DELIVERED. The duty a level asked for is a promise about how much of
    # that level's area ends up inked; whether the pattern can keep it depends
    # on whether the marks FIT, which the level's own shape decides. A duty band
    # narrower than the pitch can be missed by every scan line, and a run
    # narrower than a dot cannot host one at all -- both of which lose picture
    # without any single step reporting a loss. So the two are compared
    # directly, per level, and a level that comes up short says so by name.
    px_area = mm_per_px * mm_per_px
    short = []
    for d in plan["levels_detail"]:
        i = d["i"]
        if i == 0 or i == top or d["px"] == 0:
            continue
        want = d["px"] * px_area * d["duty"]
        got = float(ink.get(i, 0.0))
        d["ink_mm2"] = round(got, 4)
        d["ink_wanted_mm2"] = round(want, 4)
        d["ink_ratio"] = round(got / want, 3) if want > 0 else 0.0
        if want > 0 and got < 0.75 * want:
            short.append((d["duty"], d["ink_ratio"], d["px"], want - got))
    if short:
        plan["warnings"].append(
            f"{tone}: {len(short)} duty level(s) received less ink than the duty "
            f"they were assigned, because the marks do not fit the shape of the "
            f"band: "
            + "; ".join(f"duty {du:.3f} got {r * 100:.0f}% ({n:,} px, "
                        f"{miss:.2f} mm2 short)" for du, r, n, miss in short[:4])
            + f". At {pitch_mm:g} mm pitch a band narrower than the pitch can be "
              f"missed by every scan line. Those areas render LIGHTER than the "
              f"source asks for -- that is real picture, and it is short.")
    plan["quads"] = len(quads)
    plan["solid_polys"] = len(solid_polys)
    plan["on"] = True

    if ginfo.get("stubs_dropped"):
        plan["warnings"].append(
            f"{tone}: {ginfo['stubs_dropped']:,} hatch run(s) totalling "
            f"{ginfo['stub_mm']:.2f} mm were shorter than the {floor:g} mm floor "
            f"and touched no neighbour to be absorbed into -- dropped, because a "
            f"run that short is a speck, not a mark. That is source detail "
            f"finer than the pitch; a coarser --{mode}-pitch will not help, a "
            f"finer one is under the floor.")
    if ginfo.get("spans_too_narrow"):
        plan["warnings"].append(
            f"{tone}: {ginfo['spans_too_narrow']:,} run(s) totalling "
            f"{ginfo['narrow_mm']:.2f} mm were narrower than the dot they would "
            f"have carried, so the stipple grid could not reach them at all. "
            f"Those parts of the region are BARE. Hatch reaches them; stipple "
            f"cannot, because a dot has two dimensions and a line has one.")
    if ginfo.get("edge_dropped"):
        plan["warnings"].append(
            f"{tone}: {ginfo['edge_dropped']:,} stipple dot(s) sat on the region "
            f"contour and were dropped rather than allowed to spill past it. "
            f"Stipple thins toward every edge by up to half a dot -- "
            f"docs/pcb-palette.md ranks isolated dots last for exactly this "
            f"sort of reason; hatch clips flush.")
    if plan["quads"] == 0 and plan["solid_polys"] == 0 and n_px:
        plan["warnings"].append(
            f"{tone}: {n_px:,} px produced NO geometry at all under "
            f"--fill-mode {mode}. The whole tone would be lost.")
    return solid_polys, quads, plan


# --- input handling ---------------------------------------------------------
def rasterise_svg(path, width_px):
    """SVG -> RGBA PIL image on a transparent ground. cairosvg, else rsvg-convert,
    else inkscape. Kept here rather than in w0_spike: the quantiser takes an
    image and should not learn about vector formats.

    THE THREE DO NOT AGREE, and the fallback chain is silent about it. Measured
    on assets/normalised/mfb_node_full.svg at --raster-width 1200: cairosvg 2.9
    rasterises 1200x1191 and rsvg-convert 2.58 rasterises 1200x1192. One pixel
    of height, and different antialiasing along every edge, which moves the
    quantiser's tone boundaries and so the polygons: 47,128 B against 49,361 B
    for the same asset at the same size from the same emitter -- a 4.7%
    difference from nothing but which rasteriser happened to be installed. The
    whole library was rebuilt once by accident that way.

    So the tool that was actually used is returned, logged, and recorded in the
    report. cairosvg is a declared dependency for that reason: the committed
    library is reproducible with it and only approximately reproducible without.
    PNG sources are unaffected -- they are byte-identical either way."""
    import io
    import shutil
    import subprocess
    import tempfile
    from svg_entities import read_svg_bytes
    # Illustrator exports declare their private namespaces as internal DTD
    # entities, which defusedxml (under cairosvg) refuses outright. Resolve them
    # first; files without an internal subset come back byte-identical.
    data, ent = read_svg_bytes(path)
    try:
        import cairosvg
        png = cairosvg.svg2png(bytestring=data, output_width=int(width_px),
                               url=str(path))
        return Image.open(io.BytesIO(png)).convert("RGBA"), "cairosvg"
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as td:
        dst = pathlib.Path(td) / "r.png"
        src = pathlib.Path(path)
        if ent["removed_subset"]:
            src = pathlib.Path(td) / "expanded.svg"
            src.write_bytes(data)
        path = src
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-w", str(int(width_px)),
                            "-o", str(dst), str(path)], check=True)
            tool = "rsvg-convert"
        elif shutil.which("inkscape"):
            subprocess.run(["inkscape", str(path), "--export-type=png",
                            f"--export-width={int(width_px)}",
                            f"--export-filename={dst}"], check=True)
            tool = "inkscape"
        else:
            raise RuntimeError("no SVG rasteriser found (cairosvg / rsvg-convert / inkscape)")
        return Image.open(dst).convert("RGBA"), tool


def crop_to_content(img, min_alpha=8):
    """Trim a fully-transparent border. The Bitcoin emission formula SVG is a
    US-Letter artboard around a small drawing; without this it renders as a
    mostly-empty page at whatever --width-mm was asked for."""
    a = np.asarray(img.convert("RGBA"))[..., 3]
    ys, xs = np.nonzero(a >= min_alpha)
    if ys.size == 0:
        return img, None
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    if box == (0, 0, img.width, img.height):
        return img, None
    return img.crop(box), box


def _check_tone_map(tmap, pal, stats, allow_inner, allow_provisional):
    """Every reason this map may not be built, named with its own numbers.

    Each of these is a decision somebody has to make out loud. None of them is
    a threshold on quality: they are all "you are about to do X and you have
    not said you meant to".
    """
    out = []
    shares = {h: row["share_pct"] for h, row in (stats.get("per_ink") or {}).items()}
    for ink in tmap.inks:
        tone = pal[ink.tone]
        share = shares.get(ink.hex, 0.0)

        if tone.inner and not allow_inner:
            out.append(
                f"{ink.hex} is bound to {ink.tone}, whose recipe is "
                f"{'+'.join(TONE_LAYERS.get(ink.tone, ())) or 'nothing'} -- an "
                f"INNER layer. The piece stops being renderable on a 2-layer "
                f"board. Pass --allow-inner, or set inner_ok in the sidecar")

        if tone.provenance == "PROVISIONAL" and not allow_provisional:
            out.append(
                f"{ink.hex} is bound to {ink.tone}, whose sRGB value on a "
                f"{pal.mask} board is PROVISIONAL -- computed from a shading "
                f"factor nobody has measured. Pass --allow-provisional if you "
                f"mean to ship a colour you have not seen")

        d = pal.nearest(ink.rgb)
        dist = float(_np_norm(_tm._weighted(np.array(ink.rgb, dtype=np.uint8)),
                              _tm._weighted(np.array(tone.rgb, dtype=np.uint8))))
        if dist >= _tm.OFF_PALETTE_DE and not ink.off_palette:
            out.append(
                f"{ink.hex} is {dist:.1f} weighted-Lab units from {ink.tone} "
                f"(off-palette line {_tm.OFF_PALETTE_DE:g}; nearest tone of any "
                f"kind is {d[0]} at {d[1]:.1f}). This is not an approximation, "
                f"it is a substitution: set off_palette = true and say so")

        dl = pal.dl_to_board(ink.tone)
        if (share >= 1.0 and abs(dl) < _pal.LEGIBLE_MIN_DL
                and ink.legibility != "declared"):
            out.append(
                f"{ink.hex} carries {share:.2f}% of the ink and is bound to "
                f"{ink.tone}, {abs(dl):.2f} L* from the board -- under the "
                f"{_pal.LEGIBLE_MIN_DL:g} L* line at which "
                f"tools/texture_board.py calls a tone 'a sheen and not a "
                f"graphic'. It would be drawn and invisible. Set "
                f"legibility = \"declared\" if that is the intent")

    # A tone shared by two declared inks loses a distinction the artwork had.
    by_tone = {}
    for ink in tmap.inks:
        by_tone.setdefault(ink.tone, []).append(ink)
    for tid, group in sorted(by_tone.items()):
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if tmap.merge_declared(a.hex, b.hex):
                    continue
                out.append(
                    f"{a.hex} and {b.hex} are both bound to {tid}, so the "
                    f"board cannot tell them apart. One finish means exactly "
                    f"one metal tone (docs/pcb-palette.md line 145), so this "
                    f"may well be right -- but it loses a distinction the "
                    f"artwork has, and it has to be named: add "
                    f"merge_ok = [\"{b.hex}\"] to {a.hex}")
    return out


def _np_norm(a, b):
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))


def _tags_for(pal, tmap):
    """The footprint's `tags` string: what this part was assigned against.

    Same reasoning as fab_profiles.FAB_TAG_PREFIX (fab_profiles.py lines
    203-217): an emitter that assigns against one colourway and a verifier that
    checks against another will happily pass a part that is wrong, and the
    failure surfaces long after the command line that caused it is gone. So the
    part carries the statement and both sides resolve through it.
    """
    parts = ["recklessart", "art", pal.tag()]
    if tmap is not None:
        parts.append(f"tonemap:{tmap.digest()}")
    return " ".join(parts)


def load_labels(path, args, log, pal=None, tmap=None):
    """-> (labels, tone_names, source_note). Accepts .npy or any image.

    With `tmap` the pixel->tone decision is the DECLARED one from
    tools/tone_map.py and w0_spike.quantise is not called at all. Without it,
    the old nearest-anchor quantiser runs and behaves exactly as before -- that
    path is still correct for a picture drawn in the colours of the board, and
    it is what every part built before this change used.
    """
    path = pathlib.Path(path)
    tone_ids = list(_pal.TONE_IDS)
    if path.suffix.lower() == ".npy":
        labels = np.load(path)
        names = (args.tone_names.split(",") if args.tone_names
                 else list(tone_ids))
        log.append(f"labels  : {path.name} (.npy) {labels.shape[1]}x{labels.shape[0]}")
        return labels.astype(np.int64), names, None

    if path.suffix.lower() == ".svg":
        img, tool = rasterise_svg(path, args.raster_width)
        log.append(f"raster  : {path.name} via {tool} at {img.width}x{img.height} px")
        # Stashed on the args so main() can put it in the report. Which
        # rasteriser ran is part of what produced the geometry -- see
        # rasterise_svg() -- and a report that cannot say which one is not
        # enough to reproduce the file it describes.
        args._rasteriser = f"{tool} at {img.width}x{img.height} px"
    else:
        img = Image.open(path).convert("RGBA")
        log.append(f"raster  : {path.name} {img.width}x{img.height} px")

    if args.crop:
        img, box = crop_to_content(img)
        if box:
            log.append(f"crop    : content bbox {box} -> {img.width}x{img.height} px")

    if args.max_dim and max(img.size) > args.max_dim:
        s = args.max_dim / max(img.size)
        new = (max(1, round(img.width * s)), max(1, round(img.height * s)))
        img = img.resize(new, Image.LANCZOS)
        log.append(f"resize  : -> {img.width}x{img.height} px (--max-dim {args.max_dim})")

    if tmap is not None:
        labels, _opaque, st = _tm.map_labels(img, tmap, pal)
        args._tonemap_stats = st
        log.append(f"tone-map: DECLARED, {len(tmap.inks)} inks, "
                   f"digest={st['tonemap_digest']}, tol={st['tol_de']:g} dE")
        log.append(f"        : opaque={st['opaque_px']:,} "
                   f"unique={st['unique_px']:,} blend={st['blend_px']:,} "
                   f"UNMAPPED={st['unmapped_px']:,} ({st['unmapped_pct']:.3f}%)")
        for h, row in sorted(st["per_ink"].items(),
                             key=lambda kv: -kv[1]["share_pct"]):
            log.append(f"        : {h} -> {row['tone']}  {row['px']:,} px "
                       f"({row['share_pct']:.2f}%)")
        names = (args.tone_names.split(",") if args.tone_names
                 else list(tone_ids))
        return labels.astype(np.int64), names, img

    labels, _opaque, st = quantise(img, smooth=args.smooth, mix=args.mix,
                                   mix_ratio=args.mix_ratio,
                                   mix_split=args.mix_split,
                                   tones=(pal.as_w0_tones() if pal is not None
                                          else TONES))
    log.append(f"quantise: opaque={st['opaque_px']:,} dropped={st['dropped_px']:,} "
               f"tones={' '.join(st['per_tone'])}")
    m = st.get("mixture", {})
    if m.get("enabled"):
        log.append(f"mixture : {m['mixture_px']:,} coverage-blend px "
                   f"({100.0*m['mixture_px']/max(st['opaque_px'],1):.2f}%), "
                   f"{m['reassigned_px']:,} relabelled  "
                   f"[ratio={m['params']['mix_ratio']} split={m['params']['mix_split']}]")
        if m["pairs"]:
            log.append("        : between " + "  ".join(
                f"{k}={v:,}" for k, v in list(m["pairs"].items())[:6]))
        if m["tones_eliminated"]:
            naive = st.get("per_tone_naive", {})
            log.append("        : TONES REMOVED as halo-only -- " + ", ".join(
                f"{t} ({naive.get(t, 0):,} px)" for t in m["tones_eliminated"]))
    else:
        log.append("mixture : DISABLED (--no-mix) -- tone boundaries will "
                   "generate a spurious third tone")
    names = (args.tone_names.split(",") if args.tone_names
             else list(tone_ids))
    return labels.astype(np.int64), names, img


def print_report(rep, out_path, log):
    w = sys.stdout.write
    w("\n" + "=" * 74 + "\n")
    w(f"  {rep['name']}\n")
    w("=" * 74 + "\n")
    for line in log:
        w(f"  {line}\n")
    w(f"  size    : {rep['input_px'][0]}x{rep['input_px'][1]} px -> "
      f"{rep['width_mm']:.3f} x {rep['height_mm']:.3f} mm  "
      f"({rep['mm_per_px']*1000:.1f} um/px)\n")
    w(f"  simplify: {rep['tolerance_mm']} mm tolerance "
      f"(= {rep['tolerance_px']:.2f} px at this scale)\n")
    w(f"  min area: {rep['min_area_mm2']}"
      f"{' (per-tone min feature squared)' if rep['min_area_mm2'] == 'auto' else ' mm2'}\n")
    if rep["transparent_px"]:
        w(f"  alpha   : {rep['transparent_px']:,} transparent px, no geometry\n")
    s = rep.get("silhouette")
    if s:
        w(f"  silhoue.: {s['width_mm']:g} mm ring in {s['tone']} "
          f"({'+'.join(s['layers'])}) = {s['width_px']:.2f} px"
          f"{' [default: the tone min feature]' if s['width_defaulted'] else ''}"
          f"  floor {s['floor_mm']:g} mm"
          f"{' PROVISIONAL' if s['floor_provisional'] else ''}\n")
        w(f"          : {s['ring_px']:,} px reassigned "
          f"({s['ring_pct_of_opaque']:g}% of the figure) from "
          f"{_fmt_counts(s['reassigned_from'])}\n")
        if s["frame_derived_px"]:
            w(f"          : {s['frame_derived_px']:,} of them lie on the raster "
              f"edge, not on an alpha edge -- the art runs off its own frame "
              f"and is keylined along the cut\n")
    for e in rep.get("knockouts", []):
        w(f"  knockout: {e['mark']} out of {e['host']}"
          f"{' (host auto-detected)' if e['host_auto'] else ''} -- "
          f"{e['px']:,} px, "
          f"{'+'.join(e['suppressed_layers']) or 'nothing'} suppressed\n")
        w(f"          : {e['hosted_pct']:g}% of its border sits against "
          f"{e['host']}; gap floor {e['knockout_floor_mm']:g} mm "
          f"= {e['host_floor_mm']:g} mm"
          f"{' PROVISIONAL' if e['host_floor_provisional'] else ''}"
          f" x{e['floor_mult']:g} (knockout)\n")
    t8 = rep.get("t8")
    if t8:
        w(f"  T8      : {t8['tone']} -> translucent window. "
          f"{t8['polys']} aperture(s) on {'+'.join(t8['mask_layers'])}, "
          f"{t8.get('keepout_segs', 0)} keepout segment(s) on "
          f"{t8['keepout_layer']}\n")
        if t8.get("min_window_mm") is not None:
            w(f"          : narrowest window {t8['min_window_mm']:.3f} mm across "
              f"(the doc gives no floor -- 'bold shapes only')\n")
        w(f"          : BOARD-LEVEL rule area REQUIRED on "
          f"{'/'.join(t8['board_rule_area_required_on'])}; a footprint-borne "
          f"keepout is ignored by the KiCad 10 zone filler\n")
    t9 = rep.get("t9")
    if t9:
        w(f"  T9      : {t9['tone']} -> cut. {t9['polys']} routed loop(s), "
          f"{t9['verts']:,} segment(s) on Edge.Cuts, {t9['holes']} island(s)\n")
        w(f"          : fillet r{t9['fillet_mm']:g} mm on {t9['filleted']} "
          f"inside corner(s)"
          + (f", r{t9['outer_fillet_mm']:g} mm on {t9['outer_filleted']} outside"
             if t9["outer_fillet_mm"] else
             "; outside corners left sharp (the bit cuts around those)")
          + "\n")
        if t9.get("min_slot_mm") is not None:
            w(f"          : narrowest loop {t9['min_slot_mm']:.3f} mm "
              f"(slot floor {CUT_SLOT_MIN_MM:g} mm)"
              + (f", narrowest web {t9['min_web_mm']:.3f} mm "
                 f"(floor {CUT_WEB_MIN_MM:g} mm)"
                 if t9.get("min_web_mm") is not None else "") + "\n")
        a = rep.get("cut_audit") or {}
        if a.get("checked"):
            gap = a.get("min_gap_mm")
            w(f"  cu->cut : {a['checked']} copper polygon(s) near the cut, "
              f"{len(a['waste'])} on the WASTE side, {len(a['close'])} inside "
              f"the {a['clearance_mm']:g} mm board rule"
              + (f"; closest {gap:.3f} mm" if gap is not None else "")
              + ("  [INCOMPLETE]" if a.get("incomplete") else "") + "\n")
        elif a:
            w(f"  cu->cut : no copper within {a['clearance_mm']:g} mm of the cut\n")
    if rep.get("courtyard_mm"):
        c = rep["courtyard_mm"]
        w(f"  crtyd   : F.CrtYd {c[0]:g},{c[1]:g} .. {c[2]:g},{c[3]:g} mm -- "
          f"declares the extent so the cut is not read as a board outline\n")

    w("\n  tone  layers                 pixels    polys   verts  holes  dropped  note\n")
    w("  " + "-" * 78 + "\n")
    for t in rep["tones"]:
        note = t.get("note", "")
        if not note and t.get("sub_min_feature"):
            note = f"{t['sub_min_feature']} poly < {t['min_feature_mm']}mm feature"
        if t.get("gaps_below_floor"):
            g = (f"{t['gaps_below_floor']}/{t['gaps']} gap < "
                 f"{t['gap_floor_mm']:g}mm knockout floor")
            note = f"{note}; {g}" if note else g
        w(f"  {t['tone']:<4}  {'+'.join(t['layers']) or '-':<20} "
          f"{t['px']:>9,} {t['polys']:>7,} {t['verts']:>7,} {t['holes']:>6,} "
          f"{t.get('area_dropped', 0):>8,}  {note}\n")
    w("  " + "-" * 78 + "\n")
    w(f"  {'TOTAL':<4}  {'':<20} {'':>9} {rep['total_polys']:>7,} "
      f"{rep['total_verts']:>7,} {'':>6} "
      f"{sum(t.get('area_dropped', 0) for t in rep['tones']):>8,}  "
      f"{rep['total_fp_poly']:,} fp_poly"
      + (f" + {rep['total_fp_line']:,} fp_line" if rep.get("total_fp_line")
         else "")
      + (f" + {rep['total_fp_text']:,} fp_text" if rep.get("total_fp_text")
         else "") + " written\n")

    fl = rep.get("floors")
    if fl:
        w(f"  floors  : silk {fl['surface_mm']['F.SilkS']:.2f}  mask "
          f"{fl['surface_mm']['F.Mask']:.2f}  copper {fl['surface_mm']['F.Cu']:.2f} mm "
          f"from {pathlib.Path(fl['source']).name}; buried "
          f"{fl['buried_min_area_mm']:g} mm (min-area) / "
          f"{fl['buried_checks_mm']:g} mm PROVISIONAL (checks)\n")

    h = rep.get("halftone")
    if h:
        ang = f"  angle {h['angle_deg']:g} deg" if h["mode"] == "hatch" else ""
        w(f"\n  HALFTONE {h['mode'].upper()}  pitch {h['pitch_mm']:g} mm{ang}"
          f"  {h['levels']} levels  duty from source luminance "
          f"(p{h['hi_pct']:g} of each tone's own region = solid)\n")
        w(f"  ramp runs {h['background']} (nothing drawn) -> the tone; a tone "
          f"under {h['min_delta_L']:g} L* from {h['background']} is drawn solid "
          f"instead\n")
        for p in h["tones"]:
            if not p["on"]:
                w(f"    {p['tone']:<4} SOLID -- {p['why']}\n")
                continue
            lad = p["ladder"]
            w(f"\n    {p['tone']}  {'+'.join(p['layers'])}  floor "
              f"{p['floor_mm']:g} mm"
              f"{' PROVISIONAL' if p['floor_provisional'] else ''}  "
              f"dL* {p['delta_L']:g}\n")
            w(f"      achievable duty {lad['duty_min']:.3f}..{lad['duty_max']:.3f} "
              f"(+ 0 = bare board and 1 = solid, both exact); apparent L* "
              f"{p['apparent_L_range'][0]:.0f}..{p['apparent_L_range'][1]:.0f} "
              f"end to end, {p['apparent_L_hatched'][0]:.0f}.."
              f"{p['apparent_L_hatched'][1]:.0f} through the pattern\n")
            w(f"      {p['px_solid']:,} px solid  {p['px_hatched']:,} px "
              f"patterned  {p['px_blank']:,} px bare  |  "
              f"{p['solid_polys']:,} poly + {p['quads']:,} marks  |  duty snap "
              f"rms {p['snap_rms_duty']:.3f} max {p['snap_max_duty']:.3f}\n")
            w("      duty   mark    dam   L*      px\n")
            for d in p["levels_detail"]:
                tag = ("  bare" if d["i"] == 0 else
                       " solid" if d["i"] == len(p["levels_detail"]) - 1 else "")
                w(f"      {d['duty']:.3f}  {d['feature_mm']:.3f}  "
                  f"{d['dam_mm']:.3f}  {d['apparent_L']:5.1f}  "
                  f"{d['px']:>8,}{tag}\n")
            g = p.get("geometry") or {}
            if g:
                w("      " + "  ".join(f"{k}={v:,}" if isinstance(v, int)
                                       else f"{k}={v:.2f}"
                                       for k, v in g.items()) + "\n")

    if rep.get("microtext"):
        # microtext.py owns this section: the floors, the counter arithmetic
        # and the vendor tiers are its subject, and printing them from here
        # would be a second place for them to go stale.
        import microtext as _mt
        _mt.print_report(rep["microtext"], sys.stdout)

    n = rep["bytes"]
    w(f"\n  output  : {out_path}\n")
    w(f"  bytes   : {n:,} B ({n/1024:.1f} kB)  "
      f"= {100.0*n/APRIL_BASELINE_BYTES:.2f}% of the 2.5 MB April baseline "
      f"({APRIL_BASELINE_BYTES/max(n,1):.0f}x smaller)\n")
    if rep["warnings"]:
        w("\n  !! WARNINGS\n")
        for x in rep["warnings"]:
            w(f"  !! {x}\n")
    w("\n")


def _descr(args):
    """Build the footprint (descr): design intent first, provenance always.

    The provenance half -- name, source file, size -- is what makes a footprint
    traceable back to the pipeline that made it, so --descr APPENDS to it
    rather than replacing it. A piece whose descr explains the design decision
    but no longer says which file it came from is a worse artefact, not a
    better one.
    """
    prov = (f"{args.name} - {pathlib.Path(args.labels).name} at "
            f"{args.width_mm:g} mm - kicad_art_generator/emit_art.py")
    return f"{args.descr.strip()} [{prov}]" if args.descr else prov


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Quantised tone-label raster -> KiCad footprint.")
    ap.add_argument("--labels", required=True,
                    help=".npy label array from w0_spike.quantise(), or an image "
                         "(png/jpg/svg) to quantise on the way through")
    ap.add_argument("--width-mm", type=float, required=True,
                    help="output width; height follows the source aspect ratio")
    ap.add_argument("--name", required=True, help="footprint name")
    ap.add_argument("-o", "--output", required=True, help="output .kicad_mod")
    ap.add_argument("--tolerance-mm", type=float, default=DEFAULT_TOLERANCE_MM,
                    help=f"RDP tolerance in MILLIMETRES (default {DEFAULT_TOLERANCE_MM}: "
                         "half the 0.1 mm min feature, equal to mask registration, "
                         "below the eye's 0.087 mm at 300 mm)")
    ap.add_argument("--min-area-mm2", default="0",
                    help="drop regions smaller than this many mm2, or 'auto' for each "
                         "tone's own minimum fabricable feature squared. Default 0 = "
                         "drop nothing; anything dropped is reported loudly")
    ap.add_argument("--uuids", action="store_true",
                    help="write a uuid on every fp_poly (KiCad mints them on load; "
                         "off by default because it is ~48 B x thousands of polygons)")

    gq = ap.add_argument_group("quantiser (how colours become tones)")
    gq.add_argument("--smooth", type=float, default=0.0,
                    help="Gaussian pre-blur passed to w0_spike.quantise. Was 1.0; "
                         "now 0.0 because the blur widens the antialias blend band "
                         "and pushes a 1 px feature below the 50%% coverage floor. "
                         "Only for noisy (JPEG) sources")
    gq.add_argument("--no-mix", dest="mix", action="store_false", default=True,
                    help="disable mixture-pixel handling in the quantiser -- "
                         "restores the pre-fix behaviour where every tone boundary "
                         "emits a 1-2 px band of a spurious third tone")
    gq.add_argument("--mix-ratio", type=float, default=None,
                    help="how much better a two-anchor mixture must explain a pixel "
                         "than the nearest single anchor (default 0.5 = twice as well)")
    gq.add_argument("--mix-split", type=float, default=None,
                    help="recovered-coverage threshold for a blend pixel (default 0.5, "
                         "which is what makes a >=1 px feature survive). Lower it to "
                         "bias toward keeping thin ink; it cannot resurrect the halo")

    gi = ap.add_argument_group("input handling")
    gi.add_argument("--raster-width", type=int, default=1200,
                    help="raster width used for SVG input")
    gi.add_argument("--max-dim", type=int, default=0,
                    help="downscale raster input to this longest edge (0 = never)")
    gi.add_argument("--crop", dest="crop", action="store_true", default=True,
                    help="trim a fully transparent border (default on)")
    gi.add_argument("--no-crop", dest="crop", action="store_false")
    gi.add_argument("--tone-names", default=None,
                    help="comma-separated tone ids indexed by label value; "
                         "default is w0_spike.TONES order")

    go = ap.add_argument_group("output and refusals")
    go.add_argument("--preview", default=None, help="also write a composite PNG here")
    go.add_argument("--report-json", default=None, help="also write the report as JSON")
    go.add_argument("--allow-dropped-tones", action="store_true",
                    help="downgrade a dropped tone from a hard failure to a warning")
    go.add_argument("--ink-tone", default=None, metavar="TONE",
                    help="DEPRECATED sugar for a one-ink --tone-map. MONOCHROME "
                         "ART ONLY: re-points the single tone the image "
                         "quantised to at TONE, e.g. T1 for silk white. Black "
                         "ink is the same colour as a black-mask board, so "
                         "black line art quantises to the board itself and "
                         "draws nothing; this renders it inverted, the way you "
                         "would actually fabricate it. Refused alongside "
                         "--tone-map, and refused on anything with more than "
                         "one tone -- a general recolour is a tone map, and a "
                         "tone map says which colour became which tone")

    gp = ap.add_argument_group(
        "colourway and declared tone mapping",
        "WHICH TONE AN INK BECOMES IS A DECISION, NOT A DISTANCE. On a dark-mask board T5 -- bare mask -- is the darkest tone the process can make, so source ink darker than the board is unrepresentable and nearest-anchor assignment resolves that by choosing T5, which draws nothing. Measured on the shipped library: satoshi_points lost 29.6% of its ink that way, satoshi_little 24.6%, mfb_node_full 12.0%. A declared map says what each colour becomes and refuses anything it was not told about.")
    gp.add_argument("--tone-map", default=None, metavar="FILE",
                    help="JSON tone map (tools/tone_map.py). Every source "
                         "colour it names is assigned to the tone it names, "
                         "boundary pixels are resolved as blends of the two "
                         "nearest DECLARED colours, and anything else is "
                         "UNMAPPED, counted, and refused past its budget with "
                         "a paste-ready block naming the orphan colours")
    gp.add_argument("--palette-mask", default=None, metavar="COLOUR",
                    help="mask colour this part is being assigned against "
                         "(black, purple, green, white). Default black -- what "
                         "everything built before colourways existed used. The "
                         "colourway is written into the footprint's tags so "
                         "verify_art checks it against the same one")
    gp.add_argument("--palette-silk", default=None, metavar="COLOUR",
                    help="silk colour (white, black). Default follows the mask")
    gp.add_argument("--palette-finish", default="ENIG", metavar="FINISH",
                    help="surface finish; sets T2 outright. ENIG only -- HASL "
                         "and OSP have not been sampled and are refused rather "
                         "than guessed")
    gp.add_argument("--allow-inner", action="store_true",
                    help="permit a tone whose recipe reaches In1.Cu (T4, T7). "
                         "Off by default: an inner-layer tone makes the piece "
                         "un-renderable on a 2-layer board and costs a layer to "
                         "show a colour")
    gp.add_argument("--allow-provisional", action="store_true",
                    help="permit a tone whose sRGB value is PROVISIONAL. On "
                         "every mask but black, T4/T6/T7 are computed from a "
                         "shading factor nobody has measured -- the sign is "
                         "supported, the magnitude is not. Drawing in one is a "
                         "decision to ship a colour you have not seen")
    go.add_argument("--allow-empty", action="store_true",
                    help="write the footprint even if it contains no geometry at "
                         "all (the whole image landed on non-drawing tones)")
    go.add_argument("--descr", default=None, metavar="TEXT",
                    help="footprint (descr) field. The default records name, "
                         "source file and size, which is provenance. Pass this "
                         "when a piece embodies a DESIGN DECISION a reader "
                         "would otherwise have to reverse-engineer from the "
                         "geometry -- e.g. which colourway of a mark was "
                         "chosen for a given mask colour, and why. The "
                         "provenance line is appended to whatever you pass, "
                         "never replaced")

    gs = ap.add_argument_group(
        "structural tones -- T8 windows and T9 cuts",
        "Not rows in the palette recipe: they change what the board IS at that spot, not what colour it is. Pointed at a tone with the two flags below.")
    gs.add_argument("--window-tone", default=None, metavar="TONE",
                    help="T8. Regions of TONE become translucent windows: mask "
                         "opened on BOTH faces (F.Mask and B.Mask) so 1.44 mm "
                         "of bare laminate can pass light. The copper keepout "
                         "the window also needs CANNOT be carried by a "
                         "footprint -- the KiCad 10 zone filler ignores one "
                         "silently -- so the outline is marked on Dwgs.User and "
                         "a board-level rule area is required. Bold shapes only")
    gs.add_argument("--cut-tone", default=None, metavar="TONE",
                    help="T9. Regions of TONE become Edge.Cuts outlines routed "
                         "clean through. UNCONDITIONAL: footprint Edge.Cuts "
                         "merges with the board outline layer, so every board "
                         "that places this footprint gets the hole")
    gs.add_argument("--cut-fillet-mm", type=float, default=DEFAULT_CUT_FILLET_MM,
                    metavar="R",
                    help=f"radius applied to the inside corners of a T9 cut "
                         f"(default {DEFAULT_CUT_FILLET_MM:g} = the bottom of the "
                         f"standard router bit's 0.8-1.0 mm radius). A corner "
                         f"the void is convex at cannot be cut sharp; the fab "
                         f"will round it to its own bit whether or not you drew "
                         f"it, so it is drawn deliberately. 0 emits sharp "
                         f"corners and warns; anything under "
                         f"{CUT_FILLET_FLOOR_MM:g} mm is below the smallest bit "
                         f"docs/pcb-palette.md names and warns too")
    gs.add_argument("--cut-outer-fillet-mm", type=float, default=0.0,
                    metavar="R",
                    help="radius for the OUTSIDE corners of a T9 cut -- the "
                         "ones the bit cuts around, where the doc says sharp is "
                         "fine. Default 0 (sharp), which is what the fab "
                         "delivers. Raise it if you want a soft silhouette, or "
                         "to quiet verify_art's sharp-corner check, which "
                         "measures the angle between the edges and so cannot "
                         "tell an uncuttable corner from a legitimate point")
    gs.add_argument("--copper-edge-clearance-mm", type=float,
                    default=DEFAULT_COPPER_EDGE_MM, metavar="MM",
                    help=f"minimum copper-to-cut clearance (default "
                         f"{DEFAULT_COPPER_EDGE_MM:g} mm, SatoshiStarter's board "
                         f"rule -- docs/pcb-palette.md gives no number, so this "
                         f"is a board value and not a palette floor). Copper is "
                         f"also checked for WHICH SIDE of the cut it lands on, "
                         f"which DRC cannot do")
    gs.add_argument("--allow-copper-in-cut", action="store_true",
                    help="downgrade copper-on-the-waste-side from a hard "
                         "failure to a warning. There is no board on which this "
                         "is correct; the flag exists so an experiment can say "
                         "so out loud")
    gs.add_argument("--no-cut-courtyard", dest="courtyard", action="store_false",
                    default=True,
                    help="do not declare an F.CrtYd extent alongside a T9 cut. "
                         "Without it a lone Edge.Cuts loop is indistinguishable "
                         "from a board outline, and readers (verify_art among "
                         "them) will treat the art as escaping the board")

    gr = ap.add_argument_group(
        "region-boundary operations -- keylines and knockouts",
        "Two facts about a picture the tone map cannot express: where the subject ends (alpha, not colour) and which marks are gaps in a field rather than ink.")
    gr.add_argument("--silhouette-tone", default=None, metavar="TONE",
                    help="draw a keyline around the ALPHA silhouette in TONE. "
                         "A region whose colour maps to T5 is invisible -- T5 "
                         "draws nothing and IS the board -- so on a subject "
                         "that is largely T5 the outline is lost and no colour "
                         "operation can recover it, body and background being "
                         "one contiguous tone. Alpha still knows where the "
                         "subject is. Requires a source with transparency; "
                         "refused on an opaque one")
    gr.add_argument("--silhouette-mm", type=float, default=None, metavar="WIDTH",
                    help="width of that ring in MILLIMETRES (default: the "
                         "chosen tone's own minimum feature). In mm, not px, so "
                         "it stays the same physical keyline at every output "
                         "size; warns rather than clamps if it is under the "
                         "fabrication floor")
    gr.add_argument("--knockout", action="append", default=[],
                    metavar="MARK[:HOST]",
                    help="emit tone MARK as a GAP in the HOST tone's field "
                         "rather than as its own geometry -- SparkFun's silk "
                         "labels, where the dark letters are bare mask showing "
                         "through the ink, not dark ink. HOST defaults to "
                         "whichever drawing tone the mark mostly borders. "
                         "Repeatable")
    gr.add_argument("--knockout-floor-mult", type=float,
                    default=KNOCKOUT_FLOOR_MULT, metavar="M",
                    help=f"how much larger a floor a gap must clear than the "
                         f"same feature drawn positive (default "
                         f"{KNOCKOUT_FLOOR_MULT:g}: ink bleeds inward from both "
                         f"edges of a gap, so it closes where a positive mark "
                         f"would merely fatten). Applied to every hole in every "
                         f"tone, not only to --knockout ones")

    gh = ap.add_argument_group(
        "halftone fills -- continuous tone from seven tones",
        "A duty cycle between the T5 background and the tone, read off the source luminance the quantiser discarded. Needs the image, not a .npy.")
    gh.add_argument("--fill-mode", choices=HALFTONE_MODES, default="solid",
                    help="how a tone's region is filled. 'solid' (default) is "
                         "the flat fill; 'hatch' and 'stipple' render it as a "
                         "DUTY-CYCLE field between the T5 background and the "
                         "tone, so a gradient in the source becomes a duty ramp "
                         "on the board and the picture is no longer limited to "
                         "seven flat tones. Needs the source image, not a .npy "
                         "of labels -- the labels have already thrown the "
                         "shading away")
    gh.add_argument("--hatch-pitch", type=float, default=DEFAULT_HATCH_PITCH_MM,
                    metavar="MM",
                    help=f"line-to-line pitch for --fill-mode hatch (default "
                         f"{DEFAULT_HATCH_PITCH_MM:g} mm). The pitch fixes the "
                         f"achievable duty range: a mark under the layer floor "
                         f"images as nothing and a dam under it washes away, so "
                         f"duty is confined to floor/pitch .. 1-floor/pitch and "
                         f"a pitch below twice the floor can hold no duty at "
                         f"all. Both the range and any clamping are reported")
    gh.add_argument("--hatch-angle", type=float,
                    default=DEFAULT_HATCH_ANGLE_DEG, metavar="DEG",
                    help=f"hatch direction (default "
                         f"{DEFAULT_HATCH_ANGLE_DEG:g}, off both raster axes so "
                         f"the line grid cannot beat against the pixel grid)")
    gh.add_argument("--stipple-pitch", type=float,
                    default=DEFAULT_STIPPLE_PITCH_MM, metavar="MM",
                    help=f"dot-to-dot pitch for --fill-mode stipple (default "
                         f"{DEFAULT_STIPPLE_PITCH_MM:g} mm). Isolated dots are "
                         f"the LEAST reliable of the shading techniques in "
                         f"docs/pcb-palette.md -- they print inconsistently and "
                         f"drop out near minimum size. Hatch unless you are "
                         f"comparing against the coupon")
    gh.add_argument("--halftone-levels", type=int,
                    default=DEFAULT_HALFTONE_LEVELS, metavar="N",
                    help=f"how many duty steps the ramp is quantised to "
                         f"(default {DEFAULT_HALFTONE_LEVELS}). Quantise before "
                         f"segmenting, not after: docs/pcb-palette.md measures "
                         f"25 levels at 238 kB against 8 at 76 kB for the same "
                         f"square")
    gr.add_argument("--no-gap-audit", dest="gap_audit", action="store_false",
                    default=True,
                    help="skip measuring every hole against the knockout floor")
    gr.add_argument("--gap-audit-max", type=int, default=GAP_AUDIT_MAX,
                    metavar="N",
                    help=f"stop the gap audit after N holes and say so "
                         f"(default {GAP_AUDIT_MAX}); narrowest are measured first")
    # Microtext. The flags are defined by tools/microtext.py itself, with a
    # prefix, so this tool and the standalone one cannot drift apart on what a
    # flag means or what it defaults to. --microtext is the string; everything
    # else is --microtext-*.
    try:
        import microtext as _mt
        _mt.add_cli_args(ap, prefix="microtext-", text_flag="--microtext",
                         group_title="microtext (see docs/pcb-palette.md, "
                                     "\"Microprinting\")")
    except ImportError:
        _mt = None
    args = ap.parse_args(argv)
    if args.mix_ratio is None:
        args.mix_ratio = MIX_RATIO
    if args.mix_split is None:
        args.mix_split = MIX_SPLIT

    log: list[str] = []

    # --- the colourway, and the declared map, before anything is assigned ---
    try:
        pal = _pal.palette_for(args.palette_mask or "black", args.palette_silk,
                               args.palette_finish,
                               allow_provisional=args.allow_provisional)
    except _pal.PaletteError as e:
        sys.stderr.write(f"\n!! {e}\n\n")
        return 2
    _struct = [v for v in pal.validate() if v.kind == "structural"]
    if _struct:
        sys.stderr.write("\n!! palette is not usable:\n"
                         + "".join(f"!!   {v}\n" for v in _struct) + "\n")
        return 2
    log.append(f"palette : {pal.tag()} digest={pal.digest()} "
               f"drawable={' '.join(pal.drawable(allow_inner=args.allow_inner))}")

    tmap = None
    if args.tone_map:
        try:
            tmap = _tm.ToneMap.load(args.tone_map)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            sys.stderr.write(f"\n!! --tone-map {args.tone_map}: {e}\n\n")
            return 2
        if args.ink_tone:
            sys.stderr.write(
                "\n!! --tone-map and --ink-tone are both given. --ink-tone is "
                "sugar for a one-ink map;\n!! having both means two different "
                "answers to 'what tone is this ink', and which one wins\n"
                "!! would be an accident of ordering.\n\n")
            return 2
        if tmap.mask and args.palette_mask and tmap.mask != pal.mask:
            sys.stderr.write(
                f"\n!! the tone map was written for a {tmap.mask!r} board and "
                f"--palette-mask says {pal.mask!r}.\n!! Every tone in it means "
                f"something different on the other board.\n\n")
            return 2

    labels, tone_names, _img = load_labels(args.labels, args, log, pal, tmap)

    if tmap is not None:
        st = getattr(args, "_tonemap_stats", {})
        refusals = _check_tone_map(tmap, pal, st, args.allow_inner,
                                   args.allow_provisional)
        if st.get("unmapped_pct", 0.0) > st.get("unmapped_budget_pct", 0.25):
            block = _tm.paste_block(st.get("unmapped_orphans", []), pal)
            refusals.append(
                f"UNMAPPED INK {st['unmapped_pct']:.3f}% of opaque pixels, over "
                f"the {st['unmapped_budget_pct']:g}% budget. Colours nobody "
                f"declared:\n" + "\n".join(
                    f"      {o['hex']}  {o['share']:.3f}%  L* {o.get('lstar','?')}"
                    f"  nearest legible {o.get('nearest_legible','?')}"
                    for o in st.get("unmapped_orphans", [])[:8])
                + "\n   paste-ready:\n" + "\n".join(
                    "      " + l for l in block.splitlines()))
        if refusals:
            sys.stderr.write("\n!! TONE MAP REFUSED:\n"
                             + "".join(f"!!  - {r}\n" for r in refusals) + "\n")
            return 2

    # The source luminance, on the SAME raster the tones were assigned on --
    # after the crop and the downscale, which is why it is taken from the image
    # load_labels() hands back rather than re-read from disk here. It is the only
    # place the shading the quantiser discarded still exists.
    src_luma = None
    if args.fill_mode != "solid":
        if _img is None:
            sys.stderr.write(
                f"\n!! --fill-mode {args.fill_mode} needs the source image. "
                f"--labels was given a .npy of label indices, and a label is "
                f"the shading already thrown away;\n!! there is no luminance "
                f"left in it to set a duty cycle from. Pass the image itself, "
                f"or use --fill-mode solid.\n\n")
            return 2
        src_luma = relative_luminance(
            np.asarray(_img.convert("RGB"), dtype=np.float64))
        log.append(f"duty    : source luminance, {args.fill_mode} at "
                   f"{args.hatch_pitch if args.fill_mode == 'hatch' else args.stipple_pitch:g}"
                   f" mm pitch, {args.halftone_levels} levels")

    # Structural tones, validated here for the same reason --ink-tone is: a
    # typo on the command line should be a one-line message, not a traceback.
    # emit_detailed() keeps its own guard for callers that are not this CLI.
    for _flag, _t in (("--window-tone", args.window_tone),
                      ("--cut-tone", args.cut_tone)):
        if _t is not None and _t not in tone_names:
            sys.stderr.write(f"\n!! {_flag} {_t!r} is not a palette tone; "
                             f"known: {' '.join(tone_names)}\n\n")
            return 2
    if args.window_tone is not None and args.window_tone == args.cut_tone:
        sys.stderr.write(
            f"\n!! --window-tone and --cut-tone are both {args.window_tone!r}. "
            f"A region is either laminate you\n!! light through or laminate you "
            f"remove; it cannot be both.\n\n")
        return 2

    if args.ink_tone:
        known = set(_pal.TONE_IDS)
        if args.ink_tone not in known:
            sys.stderr.write(f"\n!! --ink-tone {args.ink_tone!r} is not a palette "
                             f"tone; known: {' '.join(sorted(known))}\n\n")
            return 2
        present = sorted({int(v) for v in np.unique(labels) if v >= 0})
        names_present = [tone_names[i] for i in present]
        # The old guard here demanded names_present == [T5]. That was written
        # for one palette, where black ink happened to quantise to the
        # background; on any colourway where it does not -- and the sign that
        # decides it is a 3.4% margin in a guessed constant, see
        # tools/palette.py -- the same monochrome file exits 2 instead, and 4
        # of the library's 21 pieces went with it. What actually makes the
        # operation meaningful is that there is exactly ONE ink to re-point,
        # so that is what is checked.
        if len(present) != 1:
            sys.stderr.write(
                f"\n!! --ink-tone re-points ONE ink and this image has "
                f"{len(present)}: {', '.join(names_present)}.\n"
                f"!! Which of them was meant to become {args.ink_tone} is not "
                f"in the flag. Use --tone-map and say so per colour.\n\n")
            return 2
        idx = present[0]
        was = tone_names[idx]
        tone_names = list(tone_names)
        tone_names[idx] = args.ink_tone
        log.append(f"ink-tone: monochrome art, one ink -- {was} re-pointed to "
                   f"{args.ink_tone}"
                   + (f" ({was} IS the board and would draw nothing)"
                      if was == BACKGROUND else ""))

    min_area = args.min_area_mm2 if str(args.min_area_mm2).lower() == "auto" \
        else float(args.min_area_mm2)

    try:
        knockouts = [parse_knockout(s) for s in args.knockout]
    except RegionOpError as e:
        sys.stderr.write(f"\n!! {e}\n\n")
        return 2

    mt_spec = None
    if _mt is not None:
        try:
            mt_spec = _mt.spec_from_args(args, prefix="microtext-")
        except _mt.MicrotextRefused as e:
            sys.stderr.write(f"\n!! MICROTEXT REFUSED: {e}\n\n")
            return 2

    try:
        text, rep = emit_detailed(
            labels, tone_names, args.width_mm, args.name,
            tolerance_mm=args.tolerance_mm, min_area_mm2=min_area,
            with_uuids=args.uuids,
            descr=_descr(args),
            strict=not args.allow_dropped_tones,
            silhouette_tone=args.silhouette_tone,
            silhouette_mm=args.silhouette_mm,
            knockouts=knockouts,
            knockout_floor_mult=args.knockout_floor_mult,
            gap_audit=args.gap_audit, gap_audit_max=args.gap_audit_max,
            window_tone=args.window_tone, cut_tone=args.cut_tone,
            cut_fillet_mm=args.cut_fillet_mm,
            cut_outer_fillet_mm=args.cut_outer_fillet_mm,
            copper_edge_mm=args.copper_edge_clearance_mm,
            allow_copper_in_cut=args.allow_copper_in_cut,
            courtyard=args.courtyard,
            fill_mode=args.fill_mode, luma=src_luma,
            hatch_pitch_mm=args.hatch_pitch,
            hatch_angle_deg=args.hatch_angle,
            stipple_pitch_mm=args.stipple_pitch,
            halftone_levels=args.halftone_levels,
            microtext=mt_spec,
            pal=pal, tags=_tags_for(pal, tmap))
    except RegionOpError as e:
        sys.stderr.write(f"\n!! {e}\n\n")
        return 2
    except (_mt.MicrotextRefused if _mt else ()) as e:
        sys.stderr.write(
            f"\n!! MICROTEXT REFUSED: {e}\n"
            f"!! Nothing was written. Microprinting that will not image is "
            f"worse than none:\n!! it is invisible to the naked eye either "
            f"way, so a bad one is never noticed.\n\n")
        return 2
    except CopperInWaste as e:
        sys.stderr.write(
            f"\n!! {e}\n"
            f"!! Refusing to write it. This is the failure DRC cannot see: "
            f"copper_edge_clearance\n!! measures the distance from copper to "
            f"the Edge.Cuts line and is indifferent to which\n!! side of the "
            f"line the copper is on, so marks on the slug pass and then get "
            f"routed\n!! away with it. Move the copper to the keep side, or "
            f"re-run with --allow-copper-in-cut\n!! if you have decided you "
            f"want copper printed on scrap.\n\n")
        return 4
    except ToneDropped as e:
        sys.stderr.write(f"\n!! {e}\n!! A tone in the input produced no geometry. "
                         "Refusing to write a footprint that silently loses image "
                         "content. Re-run with --allow-dropped-tones only if you have "
                         "decided the tone genuinely does not matter.\n\n")
        return 2

    labels = rep.pop("_labels", labels)      # what was emitted, keyline included

    # Total loss check. A tone whose recipe draws nothing (T5, the black mask --
    # i.e. the bare board) is legitimate as PART of a picture: it is the
    # background showing through. But if EVERY inked pixel landed there, the
    # footprint is empty and the whole artwork has been thrown away. Reporting
    # "background - draws nothing, by design" and exiting 0 made that look like
    # a success. Pure black line art on a black-mask board is exactly this case:
    # the ink is the same colour as the board, so it must be rendered inverted,
    # in silk white -- see --ink-tone.
    drawn = sum(t["polys"] for t in rep["tones"])
    inked = sum(t["px"] for t in rep["tones"])
    if inked and not drawn and not args.allow_empty:
        dead = ", ".join(f"{t['tone']} ({t['px']:,} px)" for t in rep["tones"])
        sys.stderr.write(
            f"\n!! EMPTY OUTPUT: {inked:,} inked pixels, 0 polygons.\n"
            f"!! Every pixel landed on a tone that draws nothing: {dead}.\n"
            f"!! The entire image would be lost. Refusing to write it.\n"
            f"!! If this is monochrome line art, its ink is the same colour as "
            f"the board itself;\n!! render it inverted with --ink-tone T1 "
            f"(silk white). Use --allow-empty to override.\n\n")
        return 3

    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    rep["bytes"] = out.stat().st_size
    rep["output"] = str(out)
    rep["source"] = str(args.labels)
    if getattr(args, "_rasteriser", None):
        rep["rasteriser"] = args._rasteriser
    rep["tags"] = _tags_for(pal, tmap)
    if tmap is not None:
        st = getattr(args, "_tonemap_stats", {})
        rep["tone_map"] = {
            "digest": tmap.digest(), "file": str(args.tone_map),
            "mask": tmap.mask, "tol_de": tmap.tol_de,
            "inks": tmap.to_dict()["tones"],
            "per_ink": st.get("per_ink", {}),
            "unmapped_px": st.get("unmapped_px", 0),
            "unmapped_pct": st.get("unmapped_pct", 0.0),
            "unmapped_budget_pct": st.get("unmapped_budget_pct"),
            "unmapped_orphans": st.get("unmapped_orphans", []),
            "allow_inner": bool(args.allow_inner),
            "allow_provisional": bool(args.allow_provisional),
        }
    if args.preview:
        composite(labels, tones=pal.as_w0_tones()).save(args.preview)
        log.append(f"preview : {args.preview}")

    print_report(rep, out, log)
    if args.report_json:
        pathlib.Path(args.report_json).write_text(json.dumps(rep, indent=2),
                                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
