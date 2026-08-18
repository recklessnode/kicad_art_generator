#!/usr/bin/env python3
"""Tiling generators for the board texture tool.  Pure geometry -- no board, no
KiCad, no file I/O.  Everything here is millimetres and plain Python floats on
the way out; nothing in this module knows what a copper pour is.

WHAT THIS IS FOR
----------------
tools/texture_board.py cuts a decorative slot pattern into an existing copper
pour.  The slot centrelines are the EDGES of a tiling, so the only thing this
module has to get right is: produce tiles that fit together exactly.  If the
tiles overlap, two slots overlap and the pour loses more copper than intended;
if the tiles leave gaps, the pattern has seams that read as mistakes.

    generate(kind, bbox, tile_mm, seed=0) -> list of closed polygons

Each returned polygon is a list of (x, y) pairs in mm with the first point
REPEATED as the last, so it is a closed ring ready to hand to a polygon
emitter without further thought.

WHOLE TILES ONLY.  A tile is returned only if it lies entirely inside `bbox`.
Nothing is clipped and no partial tiles are ever produced -- that is a hard
requirement of the texture tool (a clipped tile has a cut wall that does not
close, which isolates copper), and it is enforced here rather than downstream
so that no caller can forget.

WHAT `bbox` IS FOR, and it is not the mask.  For the lattice kinds bbox is the
window being filled and the whole-tile rule is the only mask there is.  For the
board-first kind ("spectre-fingerprint") bbox is the BOARD FRAME: the real mask
is the permitted copper polygons, applied downstream by the texture tool, and
the whole-tile rule here only trims tiles overhanging the board outline.  Those
two roles are easy to confuse and the difference decides whether the pattern
moves when the copper moves -- see spectre_fingerprint().

ADDING A KIND
-------------
Write a generator and decorate it.  That is the whole procedure -- there is no
table to update, no enum, no dispatch chain:

    @register("brick", size="the long side of the brick")
    def _brick(bbox, tile_mm, seed):
        ...
        yield [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

A generator yields OPEN rings (no repeated last point) in mm, covering at
least `bbox`; `generate()` closes them, applies the whole-tile filter and sorts
the result.  It may yield tiles outside the bbox freely -- overshooting is
cheaper than getting the margin wrong.  `kinds()` lists what is registered.

WHAT tile_mm MEANS
------------------
`tile_mm` is the tile's EQUAL-AREA SIZE: every kind produces tiles of area
exactly tile_mm**2.  This is the only definition under which two kinds at the
same tile_mm are comparable, and comparing them is the point -- the number that
decides how much copper a texture costs is slot length per unit area, and that
is meaningless unless the tiles are the same size.  A "6 mm" hexagon, square
and spectre therefore all have area 36 mm**2 and differ only in shape.  Per-kind
edge lengths are reported by metrics().


THE SPECTRE
===========
`kind="spectre"` is the chiral aperiodic monotile of Smith, Myers, Kaplan and
Goodman-Strauss (2023) -- the tile that covers the plane with no translational
symmetry and, unlike the earlier "hat", WITHOUT needing reflected copies.

HOW FAR THIS ACTUALLY GOT -- read this before using the kind.  TWO different
questions, two different answers, and conflating them is what made this module
throw away a patch it was entitled to use:

  * as a SUPERTILE -- something you may substitute again -- level 1, the 9-tile
    cluster.  SPECTRE_SUPERTILE_LEVEL.  That has not changed and cannot be
    changed by picking better constants; the reason is measured below.
  * as a PATCH -- a finite set of tiles you place once and then mask against
    something else -- level 2, 71 tiles.  SPECTRE_PATCH_LEVEL.  Level 2 is
    exactly disjoint (proved by integer predicates, no tolerance, see
    spectre_patch_audit) and it is only its COMPACTNESS that fails, which is a
    supertile property and not a masking one.

The two gates are separate functions on purpose.  spectre_patch() returns the
anchor quad and therefore refuses anything above SPECTRE_SUPERTILE_LEVEL -- the
quad is the thing that produces the broken level 3, so handing it out above the
level it is verified at is how the breakage escapes.  spectre_tiles() returns
tiles ONLY and serves up to SPECTRE_PATCH_LEVEL.

A 9-tile cluster is about 15 mm across at tile_mm = 4 and a 71-tile patch about
39 mm at tile_mm = 3, so as a WINDOW FILLER the spectre is still nearly useless
and hex is still the answer.  What level 2 does buy is the board-first
FINGERPRINT mode -- see spectre_fingerprint() -- which does not fill a window at
all.

  ESTABLISHED, by measurement, not assertion:
    * Tile(1,1) itself, derived here from its structure rather than copied from
      anyone's coordinate list -- and the derivation is checked: 14 unit edges,
      all directions multiples of 30 degrees, "1/3" and "1/4" vertex classes
      alternating, exactly one straight vertex, area 3 + 3*sqrt(3).  There are
      exactly two such 14-gons and they are mirror images; this is one of them.
    * The eight-slot substitution rule places eight children and leaves a hole
      of exactly one tile area, and that hole is congruent to the tile BY A PURE
      ROTATION.  That is the whole point: had it needed a mirrored tile this
      would be the hat, which cannot tile without both handednesses.  No tile in
      any patch this module builds is ever a reflected copy, and a test asserts
      it tile by tile.
    * Both cluster types, with the published counts: Spectre cluster =
      7 Spectres + 1 Mystic, Mystic cluster = 6 Spectres + 1 Mystic, giving
      1, 9, 71 and 2, 8, 62.  Levels 0 and 1 are audited for zero overlapping
      tile pairs, a single boundary loop, no hole, and 80% hull fill.

  NOT ESTABLISHED, and this is the honest headline: a patch big enough to be a
  board texture, and with it the aperiodicity evidence such a patch would carry.
  A 9-tile cluster cannot demonstrate absence of translational symmetry -- the
  scan needs hundreds of tiles -- so the "no translational symmetry" claim is
  NOT made here for the spectre.  It is made, and verified, only in the negative
  direction: the periodic kinds score exactly 1.0 on symmetry_scan, so the test
  itself is known to work; it simply has nothing big enough to run on.

  Level 2 is where the effort went and how it failed AS A SUPERTILE, which is
  worth knowing: 71 tiles, the published count, zero overlaps, one boundary
  loop, no holes, no reflected tile -- and only 64% hull fill instead of 80%,
  i.e. a sprawl rather than a supertile.  Level 3 was then unreachable with any
  of the ten level-2 anchor quads and any drop slot.

  Re-measured since, with exact integer predicates rather than the float audit
  (spectre_patch_audit, and every number below is what it returns):

      lvl  tiles  pairs  proper crossings  interior vertices  overlapping pairs
        0      1      0                 0                  0                 0
        1      9     21                 0                  0                 0
        2     71    185                 0                  0                 0
        3    559   1664               128                520                97

  So level 2 is a legitimate patch of 71 pairwise interior-disjoint tiles, with
  hull fill 0.6405 and exact area defect -6.8e-13, and level 3 is genuinely
  broken -- 97 overlapping pairs, 25 edges claimed by three or more tiles, 7
  boundary loops.  Overlapping tiles mean overlapping slots and a pour that
  loses more copper than intended, which is the failure this module exists to
  prevent, so SPECTRE_PATCH_LEVEL is 2 by measurement, not by policy.

  WHY, exactly.  This is no longer a suspicion about "a subtly wrong anchor
  quad" -- the cause has been measured and it is structural, so nobody should
  spend another session hunting for a better quad in this framework:

    * The anchor quad is forced.  Sweeping all 14*13*12*11 = 24024 ordered
      vertex 4-tuples, exactly FOUR make a valid 9-tile cluster -- (2,7,12,13),
      (3,7,11,13), (4,7,10,13), (5,7,9,13) -- and all four produce the SAME
      cluster, at 80.4% fill.  Level 1 is not one option among many; it is the
      only one, and it is right.

    * The quad map is linear, so the quad's growth rate is a fixed number.
      The eight slot rotations come from the cumulative turns in SPECTRE_RULES
      and do not depend on the quad at all; each slot translation is a fixed
      ring combination of the four quad points.  So one substitution step maps
      the quad by a fixed 4x4 complex matrix and the quad grows by that matrix's
      eigenvalue.  See spectre_quad_inflation().

    * That number is 3, and it has to be 2.805884.  Measured by iterating the
      map: the quad perimeter grows by exactly 3.000000 per level, while
      SPECTRE_INFLATION = sqrt(4 + sqrt(15)) = 2.805884 is what the tile counts
      force.  The quad outruns the metatile by 6.9% per level, the eight
      children are pushed apart by that much, and the level-2 patch comes out as
      a RING of eight clusters around one connected void of 21.2 tile areas --
      2.36 clusters' worth, measured by rasterising the patch and flood-filling
      the empty space inside its hull.  The 64% was measuring exactly that.

    * No anchor quad fixes it.  Across all 32^4 = 1,048,576 super-quad rules --
      every ordered choice of four (slot, quad-index) anchor points -- not one
      has any eigenvalue of modulus 2.805884 (nearest miss 2.8058798, and 0 hits
      at a tolerance of 1e-7).  The current constant sits at eigenvalues
      [3, 1, 0, 0].

    * Nor does re-deriving the rules.  Describing the verified cluster as a
      7-rule chain again -- every base tile, every Mystic partner, all 5040
      slot orderings, solving exactly for the quad vertices that make the chain
      hold -- yields 1794 chain descriptions.  Nine of them have the canonical
      rotation sequence (0, 60, 60, 120, 180, 180, 240, 120 degrees), giving
      five distinct rule sets, and all five fail the same eigen test: their best
      inflations over the full 32^4 sweep are 3.62, 3.73, 4.62, 3.83, 3.83.

    * A quad-free fit was also tried, and it is the one piece of this that is
      NOT evidence -- recorded so nobody repeats it thinking it settled
      something.  Dropping the quad machinery and fitting eight copies of the
      level-1 cluster together directly -- fixed rotations, edge-to-edge, at
      most the one tile the Mystic metatile is missing allowed to collide --
      enumerated 1752, 2030 and 10004 complete placements in three runs and
      found no hole-free single loop among them.  But every run was stopped by
      its own time budget rather than exhausting the space, and the overlap test
      capped its pair list, so arrangements that do overlap were let through.
      The search space was never exhausted and nothing here rules anything out.
      The eigen results above are what carry the conclusion.

  So the honest statement is stronger than "level 2 was not found": for these
  rules, with an anchor quad made of (slot, quad-index) anchor points, a level-2
  supertile does not exist, and the 64% fill is a necessary consequence rather
  than bad luck.  Changing SPECTRE_SUPER_QUAD cannot help.

  WHAT IS STILL OPEN, so the next person starts where this stopped rather than
  where it started:

    * 1747 of the 1794 chain descriptions have not been eigen-scanned.  Only the
      nine with the canonical rotation sequence were, because the other 1747
      re-order the slots and so contradict the published 60/60/120/180/180/240/
      120 turn sequence.  That is a judgement, not a proof, and the scan is
      mechanical: build the linear model from the rules, sweep 32^4, look for
      |eigenvalue| = SPECTRE_INFLATION.  It is a few hours of compute.

    * The likeliest real fix is structural and is not in the space searched at
      all.  This module collapses the nine metatile labels (Gamma, Delta, Theta,
      Lambda, Xi, Pi, Sigma, Phi, Psi) into two -- "Spectre cluster" and "Mystic
      cluster" -- which reproduces the tile counts exactly and is why every
      count-based check passes.  But if the labels carry DIFFERENT quads, the
      quad is not one vector under one linear map and the growth argument above
      simply does not apply to the real system.  That would explain, without any
      of the constants being wrong, why nothing in this framework can inflate at
      2.805884.  Restoring the nine labels, each with its own quad, is the thing
      to try next.

THE BOARD-FIRST FINGERPRINT MODE
--------------------------------
`kind="spectre-fingerprint"` inverts who decides where the tiles go.  Every
other kind here is asked to fill a window and slides its lattice to suit; this
one is anchored to the board and refuses to move.

  * ONE frame per board, not one per layer.  The caller passes the board
    outline's bbox (deflated by the edge inset), the same rectangle for F.Cu and
    B.Cu, so the two layers' tiles register with each other in board
    coordinates.
  * The patch is level SPECTRE_PATCH_LEVEL, centred on that frame.  The seed's
    ONLY job is to choose one of the twelve 30-degree rotations.  There is no
    slide, no window-size dependence, no per-layer offset: the generated field
    is a function of (board outline, tile_mm, seed) and NOTHING else.
  * The board-specific part is therefore which tiles SURVIVE the copper mask.
    That surviving subset is the fingerprint -- move a component and a different
    subset comes back, on a field that did not itself move.  With the old
    window-fitting placement the field slid whenever the permitted region
    changed shape, so nothing could be compared to anything.
  * IT REFUSES RATHER THAN REPEATING.  If the patch is too small to span the
    frame at the requested tile_mm, spectre_fingerprint raises
    SpectreCoverageError carrying the smallest tile_mm that would span and the
    level a correct substitution would need.  Tiling copies of the patch across
    the board would make the field PERIODIC at the patch pitch, which throws
    away the only property the spectre was chosen for; scaling the tile down
    silently would answer a question nobody asked.  Both are refused.

What this mode does NOT claim: aperiodicity.  71 tiles cannot demonstrate the
absence of a translational symmetry -- see the paragraph above -- and nothing
about anchoring the patch to a board changes that.


Straight edges, and what that costs.  This module emits Tile(1,1) -- the
equilateral 14-gon -- with STRAIGHT edges.  That matters and must not be
glossed over:

  * Tile(1,1) with straight edges is NOT itself an aperiodic monotile.  It
    admits periodic tilings, because its straight edges let a reflected copy sit
    against an unreflected one.  The canonical Spectre replaces each straight
    edge with a curve (any non-mirror-symmetric edge modification will do),
    which destroys the reflection and makes the tile STRICTLY chiral.
  * What this module produces is a specific, verified, NON-periodic tiling BY
    Tile(1,1), generated by the spectre substitution and using rotations and
    translations of one handedness only -- never a reflection.  So the pattern
    on the board is aperiodic in fact.  It is not, however, *forced* to be
    aperiodic by the tile shape alone.
  * The reason to keep the edges straight is fabrication, not laziness.  Each
    edge becomes a routed or etched slot of finite width; a curve becomes a
    polyline anyway, and every extra vertex is another point in the board file
    for no visible gain at a 2-6 mm tile.  See `spectre_curved()` for the
    curved-edge variant if the look is wanted; it is the same tiling with each
    edge replaced by its S-curve, so all the fit guarantees carry over.

Coordinates during construction are EXACT.  Vertices of Tile(1,1) live in the
ring Z[d] where d = exp(i*pi/6), because every edge is a unit step in a
direction that is a multiple of 30 degrees.  So a vertex is an integer 4-tuple
(a0,a1,a2,a3) meaning a0 + a1*d + a2*d^2 + a3*d^3 with d^4 = d^2 - 1, every
30-degree rotation is an integer operation, and two tile edges either coincide
EXACTLY or not at all.  There is no tolerance anywhere in the fit check: "do
these two tiles share an edge" is a dictionary lookup on integer tuples.  Only
the final scale-and-place step touches floating point.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import sys
from collections import defaultdict

MM = 1.0

# ---------------------------------------------------------------------------
# Exact arithmetic in Z[d], d = exp(i*pi/6)
# ---------------------------------------------------------------------------
# A point is (a0, a1, a2, a3) meaning a0 + a1*d + a2*d^2 + a3*d^3.  The minimal
# polynomial of a primitive 12th root of unity is x^4 - x^2 + 1, so d^4 = d^2-1,
# which is the only reduction needed.

R3 = math.sqrt(3.0)
ZERO = (0, 0, 0, 0)


def z_mul_d(p):
    """Multiply by d, i.e. rotate 30 degrees CCW.  Exact."""
    a0, a1, a2, a3 = p
    return (-a3, a0, a1 + a3, a2)


def z_rot(p, k):
    """Rotate by k*30 degrees.  Exact for any integer k."""
    for _ in range(k % 12):
        p = z_mul_d(p)
    return p


def z_add(p, q):
    return (p[0] + q[0], p[1] + q[1], p[2] + q[2], p[3] + q[3])


def z_sub(p, q):
    return (p[0] - q[0], p[1] - q[1], p[2] - q[2], p[3] - q[3])


def z_unit(k):
    """The unit vector at k*30 degrees, as a ring element."""
    return z_rot((1, 0, 0, 0), k)


def z_xy(p):
    """Exact ring element -> float (x, y).  The only lossy step."""
    a0, a1, a2, a3 = p
    return (a0 + a1 * R3 / 2 + a2 / 2, a1 / 2 + a2 * R3 / 2 + a3)


# A rigid motion is (k, t): rotate by k*30 degrees, then translate by t.
IDENT = (0, ZERO)


def m_apply(m, p):
    k, t = m
    return z_add(z_rot(p, k), t)


def m_compose(outer, inner):
    """outer after inner."""
    ko, to = outer
    ki, ti = inner
    return ((ko + ki) % 12, z_add(z_rot(ti, ko), to))


# ---------------------------------------------------------------------------
# Tile(1,1), the spectre polygon
# ---------------------------------------------------------------------------
# The 14 unit edge directions, in units of 30 degrees.  This is not a
# transcription of anyone's coordinate list: it is the unique (up to chirality
# and starting vertex) equilateral 14-gon that
#   * closes,
#   * is simple,
#   * has vertices alternating between the "1/3" class (interior 120 or 240) and
#     the "1/4" class (interior 90, 180 or 270),
#   * has exactly one straight (180 degree) vertex -- the middle of the
#     double-length edge,
# and that additionally admits the spectre substitution below.  Both handedness
# classes satisfy the first four conditions; this is the one whose supertile
# closes up, which is checked by validate().
SPECTRE_DIRS = (0, 10, 1, 11, 2, 4, 1, 3, 6, 8, 5, 7, 7, 9)

# Unit-edge Tile(1,1) area = 3 + 3*sqrt(3).
SPECTRE_UNIT_AREA = 3.0 + 3.0 * R3


def _spectre_polygon():
    pts = [ZERO]
    for k in SPECTRE_DIRS:
        pts.append(z_add(pts[-1], z_unit(k)))
    assert pts[-1] == ZERO, "Tile(1,1) edge directions do not close"
    return tuple(pts[:-1])


SPECTRE = _spectre_polygon()

# --- the substitution ------------------------------------------------------
# Eight children are placed by chaining seven rules.  Each rule is
# (turn, from_index, to_index): turn the running rotation by turn*30 degrees,
# then translate the child so that its quad point `to_index` lands on the
# previous child's quad point `from_index`.  These seven triples are the
# authors' transformation rules, in units of 30 degrees rather than degrees.
SPECTRE_RULES = ((2, 3, 1), (0, 2, 0), (2, 3, 1), (2, 3, 1),
                 (0, 2, 0), (2, 3, 1), (-4, 3, 3))

# The four anchor ("quad") vertices the rules index into.
SPECTRE_QUAD_IDX = (3, 7, 11, 13)

# The substitution has TWO cluster types, and getting that wrong is what makes
# every plausible-looking single-rule version fall apart:
#
#   Spectre cluster = 7 Spectres + 1 Mystic   (9 tiles at the bottom)
#   Mystic  cluster = 6 Spectres + 1 Mystic   (8 tiles at the bottom)
#
# so with n and g tiles in the two at one level, the next level has
# n' = 7n + g and g' = 6n + g.  The Perron eigenvalue of [[7,1],[6,1]] is
# 4 + sqrt(15) = 7.873 -- NOT 8.  Any fixed eight-fold rule therefore has the
# wrong growth rate and is guaranteed to break; several were built and measured
# breaking at the third level before this structure was used.
#
# SPECTRE_GAMMA_SLOT is the slot that carries the Mystic; SPECTRE_DROP_SLOT is
# the slot the Mystic cluster leaves out.  Both were found by measurement.
SPECTRE_GAMMA_SLOT = 7
SPECTRE_DROP_SLOT = 5

# The Mystic's second tile, relative to the Gamma slot: rotate 30 degrees, then
# translate.  This is the transform that was measured to fill the hole.
SPECTRE_MYSTIC = (1, (0, 1, 0, 1))


def spectre_slot_motions(quad, rules=None):
    """The eight child placements for one substitution step."""
    motions = [IDENT]
    total = 0
    k = 0
    tquad = list(quad)
    for turn, frm, to in (rules or SPECTRE_RULES):
        if turn:
            total += turn
            k = total % 12
            tquad = [z_rot(q, k) for q in quad]
        prev = motions[-1]
        anchor = m_apply(prev, quad[frm])
        motions.append((k, z_sub(anchor, tquad[to])))
    return motions


# The linear inflation the tile counts force.  A level-n metatile is a union of
# n_k congruent tiles and n_k grows by the Perron eigenvalue 4 + sqrt(15), so its
# AREA grows by that and its LINEAR size by the square root.  Everything that
# scales with the metatile -- the anchor quad above all -- has to grow by this
# and nothing else.
SPECTRE_INFLATION = math.sqrt(4.0 + math.sqrt(15.0))     # 2.805884


def spectre_quad_inflation(levels=8, super_quad=None, rules=None,
                           quad_idx=None):
    """How fast the anchor quad actually grows, per substitution step.

    THE NUMBER THAT KILLS LEVEL 2, and it is a measurement rather than an
    argument.  One substitution step maps the quad by

        Q'[i] = motions(Q)[a_i] applied to Q[b_i]

    and the eight slot motions are LINEAR in Q -- the rotations come from the
    cumulative turns in `rules` and never touch the quad at all, and each
    translation is a fixed ring combination of the four quad points.  So the
    quad map is a fixed 4x4 linear map and the quad grows by a fixed factor.
    Iterating it and watching the perimeter measures that factor directly.

    With the constants in this module the answer is exactly 3.0, against the
    2.805884 that SPECTRE_INFLATION requires.  The quad therefore outruns the
    metatile by 3/2.805884 = 1.0692 every level, the eight children get pushed
    apart by that much, and the level-2 patch comes out as a ring of clusters
    around one connected void of 21.2 tile areas -- which is what the 64% hull
    fill was measuring all along.  It is not a near miss to be tuned away: it is
    the wrong number.

    Returns (factor, perimeters).
    """
    quad = tuple(SPECTRE[i] for i in (quad_idx or SPECTRE_QUAD_IDX))
    sq = super_quad or SPECTRE_SUPER_QUAD
    per = []
    for _ in range(max(2, int(levels))):
        motions = spectre_slot_motions(quad, rules)
        quad = tuple(m_apply(motions[a], quad[b]) for a, b in sq)
        pts = [z_xy(p) for p in quad]
        per.append(sum(math.hypot(pts[(i + 1) % 4][0] - pts[i][0],
                                  pts[(i + 1) % 4][1] - pts[i][1])
                       for i in range(4)))
    return (per[-1] / per[-2] if per[-2] else 0.0), per


# ---------------------------------------------------------------------------
# geometry helpers (floats, for measurement and output)
# ---------------------------------------------------------------------------

def signed_area(ring):
    s = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def perimeter(ring):
    s = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        s += math.hypot(x2 - x1, y2 - y1)
    return s


def centroid(ring):
    """Area centroid of an open ring."""
    a = signed_area(ring)
    if abs(a) < 1e-15:
        n = len(ring)
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        cr = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    return (cx / (6 * a), cy / (6 * a))


def _open(ring):
    """Drop a repeated closing point if present."""
    if len(ring) > 1 and abs(ring[0][0] - ring[-1][0]) < 1e-12 \
            and abs(ring[0][1] - ring[-1][1]) < 1e-12:
        return list(ring[:-1])
    return list(ring)


def _close(ring):
    r = _open(ring)
    return r + [r[0]]


def bbox_of(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------

class Kind:
    def __init__(self, name, fn, size, edges, note):
        self.name = name
        self.fn = fn
        self.size = size
        self.edges = edges
        self.note = note


KINDS: dict[str, Kind] = {}


def register(name, size="", edges=0, note=""):
    """Register a tiling generator.  See the module docstring."""
    def deco(fn):
        KINDS[name] = Kind(name, fn, size, edges, note or (fn.__doc__ or "").strip())
        return fn
    return deco


def kinds():
    return sorted(KINDS)


# ---------------------------------------------------------------------------
# hex
# ---------------------------------------------------------------------------

@register("hex", size="flat-to-flat width = 1.0746*tile_mm", edges=6,
          note="regular hexagons on a triangular lattice; periodic")
def _hex(bbox, tile_mm, seed):
    # area of a regular hexagon of side s is 3*sqrt(3)/2 * s^2
    s = math.sqrt(2.0 * tile_mm * tile_mm / (3.0 * R3))
    dx = R3 * s                      # centre-to-centre, same row
    dy = 1.5 * s                     # row pitch
    x0, y0, x1, y1 = bbox
    rng = random.Random(seed)
    ox = rng.random() * dx if seed else 0.0
    oy = rng.random() * dy if seed else 0.0
    j0 = int(math.floor((y0 - s - oy) / dy)) - 1
    j1 = int(math.ceil((y1 + s - oy) / dy)) + 1
    for j in range(j0, j1 + 1):
        cy = oy + j * dy
        row_shift = (dx / 2.0) if (j % 2) else 0.0
        i0 = int(math.floor((x0 - dx - ox - row_shift) / dx)) - 1
        i1 = int(math.ceil((x1 + dx - ox - row_shift) / dx)) + 1
        for i in range(i0, i1 + 1):
            cx = ox + row_shift + i * dx
            yield [(cx + s * math.cos(math.radians(60 * v + 30)),
                    cy + s * math.sin(math.radians(60 * v + 30)))
                   for v in range(6)]


# ---------------------------------------------------------------------------
# checker
# ---------------------------------------------------------------------------

@register("checker", size="square side = tile_mm", edges=4,
          note="square grid; periodic.  The checkerboard LOOK comes from the "
               "driver cutting alternate cells -- as a tiling this is every "
               "cell, which is what makes the fit and gap tests meaningful")
def _checker(bbox, tile_mm, seed):
    s = tile_mm
    x0, y0, x1, y1 = bbox
    rng = random.Random(seed)
    ox = rng.random() * s if seed else 0.0
    oy = rng.random() * s if seed else 0.0
    i0 = int(math.floor((x0 - ox) / s)) - 1
    i1 = int(math.ceil((x1 - ox) / s)) + 1
    j0 = int(math.floor((y0 - oy) / s)) - 1
    j1 = int(math.ceil((y1 - oy) / s)) + 1
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            x = ox + i * s
            y = oy + j * s
            yield [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]


def checker_parity(ring):
    """0/1 chequerboard parity of a cell, for a driver that wants alternation."""
    cx, cy = centroid(_open(ring))
    x0, y0, x1, y1 = bbox_of(_open(ring))
    s = x1 - x0
    return int(math.floor(cx / s + 0.5) + math.floor(cy / s + 0.5)) & 1


# ---------------------------------------------------------------------------
# spectre
# ---------------------------------------------------------------------------

def _mystic(unit):
    """The two-tile "Mystic": a tile plus a second copy of the same tile.

    Measured, not assumed.  Placing one tile in each of the eight slots leaves a
    hole of exactly one tile area, and that hole is congruent to the tile BY A
    PURE ROTATION -- no reflection.  That is the spectre property: had the hole
    needed a mirrored tile this would be the hat, which cannot tile without both
    handednesses.  Expressed relative to the Gamma slot the filler is the tile
    turned 30 degrees and shifted, which is the pair below.
    """
    k, tr = SPECTRE_MYSTIC
    return [unit, tuple(z_add(z_rot(p, k), tr) for p in unit)]


# Where the next level's four anchor points come from: (slot, quad index).
# Found by search over the eight-slot anchor points and kept because it is one
# of only ten that pass the real audit at level 2 -- thousands pass the cheap
# tests.  It does NOT survive level 3, and neither does any of the other nine
# with any drop slot.
#
# It is now known WHY, and the reason is not specific to this constant: it makes
# the quad grow by exactly 3 per level where SPECTRE_INFLATION = 2.805884 is
# required, and no choice among the 32^4 alternatives does any better.  See
# spectre_quad_inflation() and the module docstring.  Changing this tuple cannot
# fix level 2.
SPECTRE_SUPER_QUAD = ((0, 1), (2, 1), (5, 1), (5, 3))

# The deepest substitution level that is actually a SUPERTILE here.  It is 1:
# the 9-tile Spectre cluster.
#
# Level 2 is the interesting failure and is worth spelling out, because it
# passed every test that seemed sufficient at the time.  With the super-quad
# above it produces exactly 71 tiles -- the published count -- with zero
# overlapping tile pairs, a single boundary loop, no holes, and no reflected
# tile.  It is still wrong: it fills only 64% of its convex hull, against 80.4%
# for the 9-tile cluster and 81.5% for a lone tile.  A picture of it shows what
# the number means: eight clusters arranged in a RING around a cluster-sized
# void, not a sprawl and not a supertile.
#
# That void is now accounted for exactly.  The quad map is linear and grows the
# quad by 3.0 per level where 2.805884 is required, so the eight children are
# pushed apart by 6.9% per level; no anchor quad among the 32^4 and no
# re-derived rule set among the five with the canonical rotations does better,
# and fitting the eight clusters together directly -- no quad at all -- gives
# 2030 placements and no hole-free one.  See the module docstring for the full
# ledger and spectre_quad_inflation() for the measurement.
#
# So this stays at 1 for a reason that is now proved rather than suspected, and
# raising it requires a different framework, not a better constant.  Raising it
# without extending the audit -- fill_fraction included -- does not make a
# bigger patch correct, it only stops anyone finding out.
#
# WHAT THIS CONSTANT GATES, exactly, now that there are two of them:
#   * further substitution -- i.e. ANY use of the anchor quad spectre_patch()
#     returns, since inflating the quad again is what breaks;
#   * any claim of self-similarity or supertile-hood;
#   * the fill_fraction >= 0.75 acceptance test;
#   * the CLI's level walk.
# It does NOT gate "may I place these tiles on a board and mask them".  That is
# SPECTRE_PATCH_LEVEL below, and it is a weaker question with a different answer.
SPECTRE_SUPERTILE_LEVEL = 1

# The old name, kept as an alias for one release because it is what every
# existing caller, test and error message says.  It means what it always meant:
# the deepest SUPERTILE level.  If you are reaching for it to decide how big a
# patch you may place, you want SPECTRE_PATCH_LEVEL instead.
SPECTRE_VERIFIED_LEVEL = SPECTRE_SUPERTILE_LEVEL

# The deepest level that is a valid PATCH: a set of tiles with pairwise disjoint
# interiors that you place once and then mask.  It is 2, and it is 2 by
# measurement -- spectre_patch_audit(2) reports 71 tiles, 185 candidate pairs,
# 0 proper edge crossings, 0 strictly-interior vertices, 0 overlapping pairs,
# 0 reflected tiles and an exact area defect of -6.8e-13, all under integer
# predicates with no tolerance anywhere.
#
# ITS ACCEPTANCE TEST IS DELIBERATELY WEAKER THAN THE SUPERTILE'S, and this is
# the whole reason the two constants exist.  A patch consumer asks "do these
# tiles overlap" and nothing else; it does not iterate, so self-similarity is
# irrelevant, and it discards most of the tiles against a copper mask anyway, so
# a void in the middle costs it nothing.  Hull fill, single-loop and no-holes are
# therefore NOT criteria here -- level 2 fails all three (fill 0.6405) and is
# still perfectly placeable.
#
# LEVEL 3 IS NOT.  spectre_patch_audit(3): 559 tiles, 97 overlapping pairs, 128
# proper edge crossings, 520 strictly-interior vertices, 25 edges shared by 3+
# tiles, 7 boundary loops.  Overlapping tiles mean overlapping slots and a pour
# that loses more copper than intended.  Raising this constant without rerunning
# that audit ships exactly the defect this module was written to prevent.
SPECTRE_PATCH_LEVEL = 2


def spectre_patch_size(levels):
    """Tile count after `levels` substitution steps, from the cluster counts.

    A Spectre cluster is 7 Spectres + 1 Mystic and a Mystic cluster is
    6 Spectres + 1 Mystic, so with n Spectre-cluster tiles and g Mystic-cluster
    tiles at one level, the next has n' = 7n + g and g' = 6n + g.  Starting from
    n = 1 (a tile) and g = 2 (the mystic pair) that gives

        1, 9, 71, 559, 4401, ...

    The growth ratio tends to the Perron eigenvalue of [[7,1],[6,1]], which is
    4 + sqrt(15) = 7.873 -- NOT 8, which is why a fixed eight-fold substitution
    could never have been the right shape for this and why several that looked
    promising were measured to fall apart at the third level.

    Levels 0, 1 and 2 are constructible here; see SPECTRE_PATCH_LEVEL.  The
    rest of the sequence is stated so the next person knows what a correct level
    3 has to weigh -- 559 tiles, and nothing else.
    """
    n, g = 1, 2
    for _ in range(max(0, int(levels))):
        n, g = 7 * n + g, 6 * n + g
    return n


_PATCH_CACHE: dict[int, tuple] = {}


def spectre_patch(levels):
    """The substitution `levels` times, as (tiles, quad).  SUPERTILE gate.

    Both cluster types are carried along, because the Spectre cluster is defined
    in terms of the Mystic one and vice versa; returning only the Spectre half
    would make the next step impossible.  Tile counts come out 1, 9, 71 and
    2, 8, 62, which is the published recurrence and is asserted by the tests.

    Returns (tiles, quad): `tiles` is a tuple of exact 14-point polygons in the
    ring Z[d], `quad` the anchor quad of the whole patch.

    THIS ENTRY POINT IS GATED AT SPECTRE_SUPERTILE_LEVEL, and the reason is the
    quad rather than the tiles.  Above level 1 the quad is meaningless -- it is
    the thing that grows by 3.0 where 2.805884 is required, and substituting
    with it again is precisely what produces the 97 overlapping pairs at level
    3.  Handing it out at level 2 would let the breakage escape through a caller
    that only meant to ask for tiles.  If tiles are all you want, that is
    spectre_tiles(), which serves level 2 and returns no quad at all.
    """
    levels = int(levels)
    if levels < 0:
        raise ValueError("levels must be >= 0")
    if levels > SPECTRE_SUPERTILE_LEVEL:
        # There is no honest way to answer this WITH A QUAD.  The super-quad
        # that works at level 2 does not survive level 3; iterating anyway
        # produces a patch whose tiles overlap, and it looks entirely plausible
        # until audited.
        raise RuntimeError(
            "spectre level %d is not a supertile: no anchor quad was found "
            "that survives the third inflation, so SPECTRE_VERIFIED_LEVEL is "
            "%d.  See the module docstring.  For a PATCH of tiles with no quad, "
            "spectre_tiles() serves up to SPECTRE_PATCH_LEVEL = %d."
            % (levels, SPECTRE_SUPERTILE_LEVEL, SPECTRE_PATCH_LEVEL))
    return _spectre_build(levels)


def spectre_tiles(levels):
    """The substitution `levels` times, TILES ONLY.  PATCH gate.

    Same construction as spectre_patch(), same cache, and deliberately no anchor
    quad: a patch consumer places the tiles once and masks them, and has no use
    for the quad beyond re-entering the substitution it must not re-enter.
    Serves up to SPECTRE_PATCH_LEVEL = 2, whose disjointness is proved exactly
    by spectre_patch_audit().
    """
    levels = int(levels)
    if levels < 0:
        raise ValueError("levels must be >= 0")
    if levels > SPECTRE_PATCH_LEVEL:
        raise RuntimeError(
            "spectre level %d is not a placeable patch: spectre_patch_audit(%d) "
            "reports %d overlapping tile pairs, 128 proper edge crossings and "
            "25 edges claimed by three or more tiles at level 3, so "
            "SPECTRE_PATCH_LEVEL is %d.  Overlapping tiles mean overlapping "
            "slots.  See the module docstring."
            % (levels, levels, 97, SPECTRE_PATCH_LEVEL))
    return _spectre_build(levels)[0]


def _spectre_build(levels):
    """The substitution itself, ungated.  Private: every public caller goes
    through one of the two gates above, which is what keeps the supertile
    question and the patch question from being answered by the same constant."""
    levels = int(levels)
    if levels < 0:
        raise ValueError("levels must be >= 0")
    if levels in _PATCH_CACHE:
        return _PATCH_CACHE[levels]
    quad = tuple(SPECTRE[i] for i in SPECTRE_QUAD_IDX)
    spectres = (SPECTRE,)
    mystics = tuple(_mystic(SPECTRE))
    for _ in range(levels):
        motions = spectre_slot_motions(quad)
        nxt_s, nxt_m = [], []
        for slot, m in enumerate(motions):
            src = mystics if slot == SPECTRE_GAMMA_SLOT else spectres
            placed = [tuple(m_apply(m, p) for p in t) for t in src]
            nxt_s.extend(placed)
            if slot != SPECTRE_DROP_SLOT:
                nxt_m.extend(placed)
        quad = tuple(m_apply(motions[a], quad[b]) for a, b in SPECTRE_SUPER_QUAD)
        spectres, mystics = tuple(nxt_s), tuple(nxt_m)
    _PATCH_CACHE[levels] = (spectres, quad)
    return spectres, quad


def spectre_exact_fit(levels):
    """Exact fit audit of a spectre patch: no tolerance anywhere.

    Returns a dict with the edge census and the boundary loops.  `interior`
    edges are shared by exactly two tiles; `shared3` counts edges claimed by
    three or more, which is only possible if two tiles overlap; `loops` is the
    set of boundary cycles, of which there must be exactly one -- a second loop
    is a hole.

    UNGATED on purpose: this is a measurement, not a supplier of tiles, and
    refusing to measure a level is how level 2 sat unexamined for a session.
    """
    tiles = _spectre_build(levels)[0]
    und = defaultdict(int)
    directed = defaultdict(int)
    for t in tiles:
        n = len(t)
        for i in range(n):
            a, b = t[i], t[(i + 1) % n]
            und[(a, b) if a <= b else (b, a)] += 1
            directed[(a, b)] += 1
    shared3 = sum(1 for v in und.values() if v > 2)
    interior = sum(1 for v in und.values() if v == 2)
    boundary = sum(1 for v in und.values() if v == 1)
    # cancel each directed edge against its reverse; what is left is boundary
    for (a, b) in list(directed):
        n = min(directed.get((a, b), 0), directed.get((b, a), 0))
        if n:
            directed[(a, b)] -= n
            directed[(b, a)] -= n
    adj = defaultdict(list)
    for (a, b), n in directed.items():
        for _ in range(n):
            adj[a].append(b)
    loops = []
    broken = 0
    while adj:
        start = next(iter(adj))
        loop = [start]
        cur = start
        while True:
            nxt = adj[cur].pop()
            if not adj[cur]:
                del adj[cur]
            if nxt == start:
                loops.append(loop)
                break
            loop.append(nxt)
            cur = nxt
            if cur not in adj:
                broken += 1
                break
    area = sum(signed_area([z_xy(p) for p in lp]) for lp in loops)
    return {
        "levels": levels,
        "n_tiles": len(tiles),
        "interior_edges": interior,
        "boundary_edges": boundary,
        "edges_shared_by_3_or_more": shared3,
        "boundary_loops": len(loops),
        "broken_chains": broken,
        "union_area": area,
        "sum_tile_areas": len(tiles) * SPECTRE_UNIT_AREA,
        "area_defect": area - len(tiles) * SPECTRE_UNIT_AREA,
    }


# ---------------------------------------------------------------------------
# the PATCH audit -- exact, integer, and deliberately weaker than the supertile's
# ---------------------------------------------------------------------------
# Every vertex of every spectre tile is a0 + a1*d + a2*d^2 + a3*d^3 with
# d = exp(i*pi/6).  Since d = (sqrt3, 1)/2, d^2 = (1, sqrt3)/2 and d^3 = (0, 1),
#
#     2x = (2*a0 + a2) + a1*sqrt3          2y = (a1 + 2*a3) + a2*sqrt3
#
# so every doubled coordinate is an element of Z[sqrt3].  An orientation
# determinant is then a sign of A + B*sqrt3 with A and B integers, and that sign
# is decided by comparing A^2 with 3*B^2 -- exact, in unbounded integers, with no
# tolerance anywhere and no epsilon to tune.  overlap_audit() above answers the
# same question in floats with a 1e-9 epsilon and a bucket grid; the two agreeing
# on levels 0-2 is worth more than either on its own, which is why this exists
# rather than reusing that one.

def _sq_mul(u, v):
    return (u[0] * v[0] + 3 * u[1] * v[1], u[0] * v[1] + u[1] * v[0])


def _sq_sub(u, v):
    return (u[0] - v[0], u[1] - v[1])


def _sq_sign(u):
    """sign(A + B*sqrt3), exactly."""
    a, b = u
    if a == 0 and b == 0:
        return 0
    if a >= 0 and b >= 0:
        return 1
    if a <= 0 and b <= 0:
        return -1
    d = a * a - 3 * b * b          # mixed signs: compare A^2 with 3B^2
    if a > 0:                      # b < 0
        return 1 if d > 0 else (-1 if d < 0 else 0)
    return -1 if d > 0 else (1 if d < 0 else 0)


def _z_pt2(p):
    """Ring element -> (2x, 2y) as a pair of Z[sqrt3] elements.  Exact."""
    a0, a1, a2, a3 = p
    return ((2 * a0 + a2, a1), (a1 + 2 * a3, a2))


def _orient2(a, b, c):
    """Sign of cross(b - a, c - a).  Coordinates are doubled, which scales the
    determinant by 4 and therefore cannot change its sign."""
    return _sq_sign(_sq_sub(
        _sq_mul(_sq_sub(b[0], a[0]), _sq_sub(c[1], a[1])),
        _sq_mul(_sq_sub(c[0], a[0]), _sq_sub(b[1], a[1]))))


def _proper_cross2(p1, p2, p3, p4):
    """True iff the two closed segments cross transversally (touching is not a
    crossing -- two tiles sharing an edge or a vertex must not count)."""
    d1 = _orient2(p3, p4, p1)
    d2 = _orient2(p3, p4, p2)
    d3 = _orient2(p1, p2, p3)
    d4 = _orient2(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def _strictly_inside2(q, poly):
    """Exact winding number, strict: a point ON the boundary is NOT inside."""
    wn = 0
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        o = _orient2(a, b, q)
        if o == 0:
            vx = _sq_sub(b[0], a[0])
            vy = _sq_sub(b[1], a[1])
            wx = _sq_sub(q[0], a[0])
            wy = _sq_sub(q[1], a[1])
            t1 = (_sq_mul(vx, wx)[0] + _sq_mul(vy, wy)[0],
                  _sq_mul(vx, wx)[1] + _sq_mul(vy, wy)[1])
            t2 = (_sq_mul(vx, vx)[0] + _sq_mul(vy, vy)[0],
                  _sq_mul(vx, vx)[1] + _sq_mul(vy, vy)[1])
            if _sq_sign(t1) >= 0 and _sq_sign(_sq_sub(t1, t2)) <= 0:
                return False                      # on the boundary
        ay = _sq_sign(_sq_sub(a[1], q[1]))
        by = _sq_sign(_sq_sub(b[1], q[1]))
        if ay <= 0 < by:
            if o > 0:
                wn += 1
        elif by <= 0 < ay:
            if o < 0:
                wn -= 1
    return wn != 0


def _is_rotation_of_tile(t):
    """Is `t` a pure rotation+translation of Tile(1,1), rather than a mirror?

    Exhaustive over all twelve rotations and all fourteen starting vertices, on
    exact ring tuples, so a False here is a proof of reflection and not a
    tolerance artefact.
    """
    n = len(SPECTRE)
    if len(t) != n:
        return False
    for k in range(12):
        rb = [z_rot(p, k) for p in SPECTRE]
        for s in range(n):
            tr = z_sub(t[0], rb[s])
            if [z_add(p, tr) for p in rb[s:] + rb[:s]] == list(t):
                return True
    return False


def spectre_patch_audit(levels):
    """Is the level-`levels` patch PLACEABLE?  Exact, and ungated.

    THE FOUR QUESTIONS A MASKING CONSUMER ACTUALLY ASKS, and no others:

        count == spectre_patch_size(levels)      nothing was lost or doubled
        overlapping_pairs == 0                   no two slots would overlap
        reflected_tiles == 0                     one handedness, i.e. a spectre
        |area_defect| < 1e-9                     no gaps either

    Overlap is decided by the two conditions that are together necessary and
    sufficient for two simple polygons to have disjoint interiors: no pair of
    edges crosses transversally, and no vertex of either lies strictly inside the
    other.  (Containment without either would need one tile inside the other,
    impossible for congruent tiles unless they coincide, which a zero area defect
    rules out.)  Both predicates are integer-exact -- see the note above.

    WHAT IS NOT ASKED, and this is the point of having a separate audit: hull
    fill, a single boundary loop, and the absence of holes.  Those are SUPERTILE
    properties -- they say the patch is a compact chunk of plane you could
    substitute again -- and level 2 fails them (fill 0.6405, eight clusters round
    a void).  A consumer that places tiles once and then discards most of them
    against a copper mask is indifferent to a void it was never going to fill.
    They are reported anyway, so that nobody can read a passing audit as a claim
    that level 2 is a supertile.

    Ungated deliberately: measuring a level is always allowed, and refusing to is
    how level 2 stayed unexamined.  Getting the TILES is what is gated, by
    spectre_tiles().
    """
    levels = int(levels)
    tiles = _spectre_build(levels)[0]
    exact = [[_z_pt2(p) for p in t] for t in tiles]
    fl = [[z_xy(p) for p in t] for t in tiles]
    boxes = [bbox_of(r) for r in fl]
    n = len(tiles)
    tested = crossings = inside_hits = 0
    bad = set()
    for i in range(n):
        bi = boxes[i]
        for j in range(i + 1, n):
            bj = boxes[j]
            if bi[2] < bj[0] - 1e-9 or bj[2] < bi[0] - 1e-9 or \
               bi[3] < bj[1] - 1e-9 or bj[3] < bi[1] - 1e-9:
                continue
            tested += 1
            a, b = exact[i], exact[j]
            hit = False
            for k in range(len(a)):
                a1, a2 = a[k], a[(k + 1) % len(a)]
                for m in range(len(b)):
                    if _proper_cross2(a1, a2, b[m], b[(m + 1) % len(b)]):
                        crossings += 1
                        hit = True
            for v in a:
                if _strictly_inside2(v, b):
                    inside_hits += 1
                    hit = True
            for v in b:
                if _strictly_inside2(v, a):
                    inside_hits += 1
                    hit = True
            if hit:
                bad.add((i, j))
    fit = spectre_exact_fit(levels)
    reflected = sum(0 if _is_rotation_of_tile(t) else 1 for t in tiles)
    want = spectre_patch_size(levels)
    out = {
        "levels": levels,
        "n_tiles": n,
        "expected_tiles": want,
        "pairs_tested": tested,
        "proper_crossings": crossings,
        "strictly_interior_vertices": inside_hits,
        "overlapping_pairs": len(bad),
        "examples": sorted(bad)[:5],
        "reflected_tiles": reflected,
        "area_defect": fit["area_defect"],
        # reported, NOT gated -- see the docstring
        "edges_shared_by_3_or_more": fit["edges_shared_by_3_or_more"],
        "boundary_loops": fit["boundary_loops"],
        "hull_fill": fill_fraction(fl),
    }
    out["patch_ok"] = (n == want and not bad and not reflected
                       and abs(fit["area_defect"]) < 1e-9)
    out["supertile_ok"] = bool(out["patch_ok"] and out["boundary_loops"] == 1
                               and out["hull_fill"] >= 0.75)
    return out


# ---------------------------------------------------------------------------
# the board-first fingerprint
# ---------------------------------------------------------------------------

class SpectreCoverageError(RuntimeError):
    """The deepest usable patch cannot span the frame at the requested tile_mm.

    Carries the numbers needed to act on it: `min_tile_mm` is the smallest tile
    that WOULD span this frame at this rotation, `needed_level` the substitution
    level a CORRECT system would need at the requested tile_mm.  A RuntimeError
    subclass so that callers already catching the module's refusals keep working.
    """

    def __init__(self, message, frame_mm=None, patch_mm=None, tile_mm=None,
                 min_tile_mm=None, needed_level=None, levels=None):
        super().__init__(message)
        self.frame_mm = frame_mm
        self.patch_mm = patch_mm
        self.tile_mm = tile_mm
        self.min_tile_mm = min_tile_mm
        self.needed_level = needed_level
        self.levels = levels


def spectre_unit_mm(tile_mm):
    """mm per unit edge at the given equal-area tile size.  tile_mm / 2.862892."""
    return float(tile_mm) / math.sqrt(SPECTRE_UNIT_AREA)


_EXTENT_CACHE: dict[tuple, tuple] = {}


def spectre_patch_extent(levels=None, turn=0):
    """(w, h) of the patch's bounding box in UNIT EDGES, at turn*30 degrees.

    Multiply by spectre_unit_mm(tile_mm) for millimetres.  Measured, not
    derived: the bbox does NOT grow by the quad's eigenvalue 3.0 and does not
    grow by SPECTRE_INFLATION either -- level 1 -> 2 is 3.492 x 3.244 -- so any
    arithmetic that assumes a growth factor here is wrong.
    """
    levels = SPECTRE_PATCH_LEVEL if levels is None else int(levels)
    key = (levels, int(turn) % 12)
    if key in _EXTENT_CACHE:
        return _EXTENT_CACHE[key]
    tiles = spectre_tiles(levels)
    pts = [z_xy(z_rot(p, key[1])) for t in tiles for p in t]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    _EXTENT_CACHE[key] = (max(xs) - min(xs), max(ys) - min(ys))
    return _EXTENT_CACHE[key]


def spectre_span_tile_mm(frame_w, frame_h, levels=None, turn=0):
    """The SMALLEST tile_mm at which the patch spans a frame_w x frame_h frame.

    Smallest, not largest: the patch is a fixed number of tiles, so it can only
    be made to cover more board by making the tiles bigger.  There is no upper
    bound from coverage -- the upper bound comes from the copper mask, where a
    tile too big to fit between two obstacles simply never places.
    """
    ew, eh = spectre_patch_extent(levels, turn)
    u = math.sqrt(SPECTRE_UNIT_AREA)
    return max(float(frame_w) / ew, float(frame_h) / eh) * u


def spectre_span_level(frame_w, frame_h, tile_mm, turn=0, max_level=12):
    """The substitution level a CORRECT system would need to span this frame.

    Levels 0..SPECTRE_PATCH_LEVEL are measured.  Above that nothing is
    constructible here, so the extent is extrapolated at SPECTRE_INFLATION =
    2.805884 per level -- the linear growth the TILE COUNTS force, which is what
    a correct substitution would have.  The number is therefore a statement about
    what would be required, not a promise that it can be built; this module
    cannot build level 3 at all.  Returns None if even max_level would not do it.
    """
    unit = spectre_unit_mm(tile_mm)
    for lv in range(0, SPECTRE_PATCH_LEVEL + 1):
        ew, eh = spectre_patch_extent(lv, turn)
        if ew * unit >= frame_w - 1e-9 and eh * unit >= frame_h - 1e-9:
            return lv
    ew, eh = spectre_patch_extent(SPECTRE_PATCH_LEVEL, turn)
    for lv in range(SPECTRE_PATCH_LEVEL + 1, int(max_level) + 1):
        f = SPECTRE_INFLATION ** (lv - SPECTRE_PATCH_LEVEL)
        if ew * f * unit >= frame_w - 1e-9 and eh * f * unit >= frame_h - 1e-9:
            return lv
    return None


def spectre_fingerprint(frame, tile_mm, seed=0, levels=None):
    """The board-first patch: one level-2 patch, centred on `frame`, or a refusal.

    `frame` is (x0, y0, x1, y1) in mm -- the BOARD outline's bbox, deflated by
    the edge inset, and the SAME rectangle for every layer of the board.  That is
    the whole mechanism: the returned field depends on (frame, tile_mm, seed) and
    on nothing else, so the only board-specific thing about the final texture is
    which tiles survive the copper mask downstream.  Returns closed rings in mm.

    The seed picks one of the twelve 30-degree rotations and does nothing else.
    In particular it does NOT slide the patch, which is what the window-fitting
    kind does (see _spectre): a slide computed from the window's size makes the
    pattern move whenever the permitted region changes shape, and then no two
    runs are comparable and there is no fingerprint to speak of.

    Raises SpectreCoverageError -- loudly, with numbers -- if the patch cannot
    span the frame.  It does not scale the tile down and it does not repeat the
    patch across the board; a repeated patch is periodic at the patch pitch,
    which is the one property the spectre was chosen to avoid.
    """
    levels = SPECTRE_PATCH_LEVEL if levels is None else int(levels)
    x0, y0, x1, y1 = (float(v) for v in frame)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("empty frame %r" % (frame,))
    if tile_mm <= 0:
        raise ValueError("tile_mm must be positive, got %r" % (tile_mm,))
    fw, fh = x1 - x0, y1 - y0
    turn = int(seed) % 12
    unit = spectre_unit_mm(tile_mm)
    ew, eh = spectre_patch_extent(levels, turn)
    pw, ph = ew * unit, eh * unit
    if pw < fw - 1e-9 or ph < fh - 1e-9:
        need = spectre_span_tile_mm(fw, fh, levels, turn)
        lv = spectre_span_level(fw, fh, tile_mm, turn)
        raise SpectreCoverageError(
            "spectre level %d is %.3f x %.3f mm at tile_mm %.3f and cannot span "
            "the %.3f x %.3f mm board frame. The deepest PLACEABLE patch is "
            "level %d (%d tiles); it is not a supertile and cannot be inflated "
            "again -- level 3 has %d overlapping tile pairs. Your options, in "
            "full: raise --tile-mm to at least %.3f mm, which is the smallest "
            "tile at which this patch spans this board at rotation %d; or use a "
            "lattice kind. What is NOT on offer: repeating the patch across the "
            "board, which would make the field periodic at a %.1f mm pitch and "
            "throw away the only reason to use a spectre, and silently shrinking "
            "to fit, which would answer a question you did not ask. Spanning at "
            "tile_mm %.3f would need level %s, and this framework cannot build "
            "level 3, let alone that."
            % (levels, pw, ph, tile_mm, fw, fh, SPECTRE_PATCH_LEVEL,
               spectre_patch_size(SPECTRE_PATCH_LEVEL), 97, need, turn,
               max(pw, ph), tile_mm, "?" if lv is None else str(lv)),
            frame_mm=(fw, fh), patch_mm=(pw, ph), tile_mm=float(tile_mm),
            min_tile_mm=need, needed_level=lv, levels=levels)
    tiles = spectre_tiles(levels)
    pts = [[z_xy(z_rot(p, turn)) for p in t] for t in tiles]
    xs = [p[0] for t in pts for p in t]
    ys = [p[1] for t in pts for p in t]
    # centre the patch on the frame: deterministic, and the only placement that
    # does not privilege one corner of the board over another.
    ox = (x0 + x1) / 2.0 - (min(xs) + max(xs)) / 2.0 * unit
    oy = (y0 + y1) / 2.0 - (min(ys) + max(ys)) / 2.0 * unit
    out = [[(p[0] * unit + ox, p[1] * unit + oy) for p in t] for t in pts]
    out.sort(key=lambda r: (round(centroid(r)[1], 6), round(centroid(r)[0], 6)))
    return [r + [r[0]] for r in out]


@register("spectre-fingerprint",
          size="equal-area size; edge = tile_mm/2.8629", edges=14,
          note="BOARD-FIRST. One level-2 spectre patch (71 tiles) centred on "
               "the board frame, seed choosing the rotation only. Refuses "
               "loudly rather than repeating or rescaling. The bbox handed to "
               "generate() must be the BOARD, not a permitted region")
def _spectre_fingerprint(bbox, tile_mm, seed):
    for ring in spectre_fingerprint(bbox, tile_mm, seed):
        yield ring


# ---------------------------------------------------------------------------
# the cell grid -- the fingerprint that is actually sensitive to the board
# ---------------------------------------------------------------------------
# WHY THIS EXISTS, in one paragraph, because the one-patch mode above looks like
# it already does the job and does not.  spectre_fingerprint() must SPAN the
# board with 71 tiles, which on a 150 x 100 mm board forces tile_mm >= 11.674 and
# a tile 16.7 mm across.  At that size only six tiles survive the F.Cu copper
# mask and four survive B.Cu, and a six-element field cannot distinguish two
# boards: measured over a full-board sweep, moving all 156 footprints by 2.0 mm
# changed the surviving set in 2 cases out of 156, both of them NETLESS
# mechanical hardware, and moving J3 by 12 mm changed the permitted area by
# 98.39 mm2 with a bit-identical tile set.  The failure was arithmetic, not
# conceptual: the field was too small to resolve anything.
#
# The cell grid keeps the anchoring and spends the tile budget properly.  The
# frame is cut into square cells of a fixed pitch, each cell gets its own
# level-2 patch at its own rotation, and the tile size is then free -- at
# tile_mm 3.0 the same board is offered hundreds of tiles instead of 71.
#
# WHAT IT COSTS, stated plainly rather than buried.  spectre_fingerprint()
# refuses to repeat the patch, and the reason it gives is correct: a repeated
# patch is periodic at the patch pitch.  This mode repeats it.  The per-cell
# rotation breaks EXACT translational symmetry only when two cells draw
# different turns -- two neighbours that draw the same k out of 12 are exact
# translates of each other.  So the field is aperiodic INSIDE a cell and merely
# scrambled between cells; it is not an aperiodic tiling of the board and must
# not be described as one.  That is the trade this mode makes on purpose:
# sensitivity to the copper, which the one-patch mode did not have at any size,
# in exchange for long-range aperiodicity, which nothing downstream measures.


def spectre_cell_units(levels=None):
    """Side of the smallest SQUARE cell that holds the patch at EVERY rotation.

    In UNIT EDGES.  Measured over all twelve 30-degree turns and maximised, so
    the answer does not depend on which turn a cell happens to draw -- which is
    the whole point: a per-cell rotation may only be free if the cell is big
    enough for the worst one.

    At level 2 the twelve turns give six distinct bboxes, and the largest single
    dimension of any of them is exactly 15 + 13*sqrt(3) = 37.516660498395 unit
    edges (turns 1, 4, 7, 10, in height; the same number appears as a width at
    turns 4 and 10).  Exact because every vertex is a point of Z[d] and both
    coordinates therefore lie in (1/2)Z[sqrt 3]; there is no rounding in it.
    """
    levels = SPECTRE_PATCH_LEVEL if levels is None else int(levels)
    return max(max(spectre_patch_extent(levels, k)) for k in range(12))


# The level-2 cell in units of tile_mm: cell_mm = SPECTRE_CELL_PITCH * tile_mm.
#
# DO NOT ROUND THIS AND DO NOT COPY IT OUT OF A REPORT.  The value that has been
# quoted at 4 decimal places, 13.1042, is SHORT by 2.609e-4 per mm of tile.  At
# tile_mm 3.0 that is 7.8e-4 mm of cell, i.e. the turn-1 patch would overhang its
# cell by 783 nm -- 783 times KiCad's own 1 nm file quantum -- and the
# disjoint-by-construction argument below would be false rather than tight.  The
# constant is derived at import from the measured extents and cross-checked
# against its closed form, so it cannot drift.
SPECTRE_CELL_PITCH = spectre_cell_units() / math.sqrt(SPECTRE_UNIT_AREA)

assert abs(spectre_cell_units() - (15.0 + 13.0 * R3)) < 1e-12, \
    "level-2 cell side is not 15 + 13*sqrt(3); re-derive before trusting it"


def spectre_cell_pitch_mm(tile_mm, levels=None):
    """Cell pitch in mm at this tile size.  13.104460921054 * tile_mm at L2."""
    if tile_mm <= 0:
        raise ValueError("tile_mm must be positive, got %r" % (tile_mm,))
    return spectre_cell_units(levels) * spectre_unit_mm(tile_mm)


def spectre_cell_turn(seed, i, j):
    """Rotation index 0..11 for cell (i, j).  STABLE ACROSS PROCESSES.

    hashlib, not hash().  Python's built-in hash() on str and bytes is salted by
    PYTHONHASHSEED, so a field built on it would differ between two runs of the
    same command on the same board -- which destroys the only property this mode
    has.  SHA-256 of an ASCII key is overkill for twelve buckets and that is
    fine: it costs microseconds per cell and it is the one primitive here whose
    cross-process stability is not in question.

    The key is versioned.  Changing the key string changes every field ever
    generated, so it is a deliberate, visible act and not a refactor.
    """
    key = "spectre-cell/v1/%d/%d/%d" % (int(seed), int(i), int(j))
    digest = hashlib.sha256(key.encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") % 12


_ROT_PATCH_CACHE: dict[tuple, tuple] = {}


def _rotated_patch(levels, turn):
    """(tiles as float xy, minx, miny, maxx, maxy) in unit edges, cached."""
    key = (int(levels), int(turn) % 12)
    hit = _ROT_PATCH_CACHE.get(key)
    if hit is not None:
        return hit
    pts = [[z_xy(z_rot(p, key[1])) for p in t] for t in spectre_tiles(key[0])]
    xs = [p[0] for t in pts for p in t]
    ys = [p[1] for t in pts for p in t]
    _ROT_PATCH_CACHE[key] = (pts, min(xs), min(ys), max(xs), max(ys))
    return _ROT_PATCH_CACHE[key]


def spectre_cell_grid(frame, tile_mm, seed=0, levels=None):
    """A level-2 patch per cell over `frame`.  Closed rings in mm.

    `frame` is (x0, y0, x1, y1) -- the SAME board-anchored rectangle every layer
    of the run gets, exactly as spectre_fingerprint() takes it.  The grid is
    anchored at (x0, y0) and is ceil(w/cell) x ceil(h/cell) cells, so the last
    column and row hang over the frame; generate()'s whole-tile filter drops
    what hangs over, which is the intended and only behaviour -- nothing is ever
    clipped.

    DISJOINTNESS IS BY CONSTRUCTION, and the argument is three lines:

      1. every tile of the level-2 patch has pairwise-disjoint interiors with
         every other tile of the same patch.  That is not assumed here, it is
         proved by spectre_patch_audit(2) under integer predicates in Z[sqrt 3]:
         71 tiles, 185 candidate pairs, 0 overlapping pairs, 0 proper edge
         crossings, 0 strictly-interior vertices, area defect -6.8e-13.
      2. every tile of a rotated patch lies inside the patch's own bbox, and
         that bbox is at most spectre_cell_units() on a side at EVERY one of the
         twelve turns.  Centred in a cell of exactly that side, the whole patch
         therefore lies inside the closed cell rectangle.
      3. the cells are a square lattice, so two distinct cells meet at most in a
         shared boundary segment, which has empty interior.

    1 + 2 + 3 give pairwise-disjoint interiors for the whole field.  Note the
    bound in (2) is TIGHT, not slack: at turns 1, 4, 7 and 10 the patch is
    exactly as tall (or wide) as the cell, so its extreme vertices touch the cell
    edge and can touch the neighbouring cell's patch.  Touching is not
    overlapping -- interiors stay disjoint -- but it does mean a cell pitch even
    a nanometre smaller than spectre_cell_units() breaks the proof.

    Determinism: the only inputs are `frame`, `tile_mm`, `seed` and `levels`.
    No RNG, no clock, no set or dict iteration order, and the per-cell rotation
    comes from hashlib rather than hash().  Two processes with different
    PYTHONHASHSEED produce the identical list.
    """
    levels = SPECTRE_PATCH_LEVEL if levels is None else int(levels)
    x0, y0, x1, y1 = (float(v) for v in frame)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("empty frame %r" % (frame,))
    if tile_mm <= 0:
        raise ValueError("tile_mm must be positive, got %r" % (tile_mm,))

    cell = spectre_cell_pitch_mm(tile_mm, levels)
    unit = spectre_unit_mm(tile_mm)
    # ceil, with a 1e-9 mm slack so a frame that is an exact multiple of the
    # cell does not buy a whole extra column for a rounding artefact
    nx = max(1, int(math.ceil((x1 - x0) / cell - 1e-9)))
    ny = max(1, int(math.ceil((y1 - y0) / cell - 1e-9)))

    out = []
    for j in range(ny):
        cy = y0 + (j + 0.5) * cell
        for i in range(nx):
            cx = x0 + (i + 0.5) * cell
            turn = spectre_cell_turn(seed, i, j)
            pts, pminx, pminy, pmaxx, pmaxy = _rotated_patch(levels, turn)
            ox = cx - (pminx + pmaxx) / 2.0 * unit
            oy = cy - (pminy + pmaxy) / 2.0 * unit
            for t in pts:
                out.append([(p[0] * unit + ox, p[1] * unit + oy) for p in t])
    out.sort(key=lambda r: (round(centroid(r)[1], 6), round(centroid(r)[0], 6)))
    return [r + [r[0]] for r in out]


def spectre_cell_layout(frame, tile_mm, seed=0, levels=None):
    """The grid's shape, without building any geometry.  For reports and tests.

    Returns a dict: cell pitch, nx, ny, the per-cell turns, how many neighbour
    pairs drew the SAME turn (those pairs are exact translates of each other and
    are the honest measure of how periodic the field still is), and the tile
    count offered before any filtering.
    """
    cell = spectre_cell_pitch_mm(tile_mm, levels)
    nx = max(1, int(math.ceil((float(frame[2]) - float(frame[0])) / cell - 1e-9)))
    ny = max(1, int(math.ceil((float(frame[3]) - float(frame[1])) / cell - 1e-9)))
    turns = {(i, j): spectre_cell_turn(seed, i, j)
             for j in range(ny) for i in range(nx)}
    same = 0
    pairs = 0
    for j in range(ny):
        for i in range(nx):
            for di, dj in ((1, 0), (0, 1)):
                n = (i + di, j + dj)
                if n in turns:
                    pairs += 1
                    same += (turns[n] == turns[(i, j)])
    per_patch = spectre_patch_size(
        SPECTRE_PATCH_LEVEL if levels is None else int(levels))
    return {
        "cell_mm": cell,
        "nx": nx, "ny": ny, "cells": nx * ny,
        "turns": turns,
        "turn_histogram": {k: sum(1 for v in turns.values() if v == k)
                           for k in range(12)},
        "adjacent_pairs": pairs,
        "adjacent_same_turn": same,
        "tiles_per_cell": per_patch,
        "tiles_offered": per_patch * nx * ny,
    }


@register("spectre-cells",
          size="equal-area size; edge = tile_mm/2.8629", edges=14,
          note="BOARD-FIRST. A level-2 spectre patch (71 tiles) per cell of a "
               "13.10446*tile_mm square grid anchored at the board frame, each "
               "cell rotated by a hashlib-derived turn. Disjoint by "
               "construction. Aperiodic inside a cell, NOT across cells. The "
               "bbox handed to generate() must be the BOARD, not a permitted "
               "region")
def _spectre_cells(bbox, tile_mm, seed):
    for ring in spectre_cell_grid(bbox, tile_mm, seed):
        yield ring


def _spectre_levels_for(w, h, unit):
    """Smallest level whose patch bbox comfortably contains a w x h window.

    THE WINDOW-FITTING PATH, kept at SPECTRE_SUPERTILE_LEVEL on purpose even
    though a level-2 patch exists and would cover more.  Everything below slides
    the patch to suit the window, and a placement that depends on the window's
    size is the exact behaviour the board-first mode was written to get rid of:
    change the copper, the permitted bbox changes, and every tile moves.  Level 2
    is served by spectre_fingerprint(), which anchors instead of sliding.
    """
    for levels in range(1, SPECTRE_SUPERTILE_LEVEL + 1):
        tiles, _ = spectre_patch(levels)
        xs = []
        ys = []
        for t in tiles:
            for p in t:
                x, y = z_xy(p)
                xs.append(x)
                ys.append(y)
        pw = (max(xs) - min(xs)) * unit
        ph = (max(ys) - min(ys)) * unit
        # only coverage is required.  Whole-tile-only will still strip roughly a
        # tile's width off each side of the window, which is inherent in the
        # rule and not something a margin here can prevent.
        if pw >= w and ph >= h:
            return levels, (min(xs), min(ys), max(xs), max(ys))
    raise RuntimeError(
        "a %.1f x %.1f mm window needs a bigger spectre patch than level %d, "
        "which is the deepest level that is a verified SUPERTILE.  Level 2 "
        "exists and passes every fit test but fills only 64%% of its hull -- "
        "eight clusters ringing a void of 21 tile areas -- because the anchor quad "
        "grows by 3.0 per level where %.6f is required, and no anchor quad and "
        "no re-derived rule set fixes that.  So do not go looking for a better "
        "constant; use hex, raise tile_mm, or use kind 'spectre-fingerprint', "
        "which places the level-2 PATCH against the board instead of fitting it "
        "to a window.  SPECTRE_VERIFIED_LEVEL is what the audit earned, not a knob."
        % (w, h, SPECTRE_SUPERTILE_LEVEL, SPECTRE_INFLATION))


@register("spectre", size="equal-area size; edge = tile_mm/2.8629", edges=14,
          note="Tile(1,1), the chiral aperiodic monotile, built by its "
               "substitution system.  Straight edges -- see the module "
               "docstring for exactly what that does and does not guarantee")
def _spectre(bbox, tile_mm, seed):
    x0, y0, x1, y1 = bbox
    unit = tile_mm / math.sqrt(SPECTRE_UNIT_AREA)   # mm per unit edge
    levels, pb = _spectre_levels_for(x1 - x0, y1 - y0, unit)
    tiles, _ = spectre_patch(levels)
    turn = (int(seed) % 12) if seed else 0
    rng = random.Random(seed)
    pts = [[z_xy(z_rot(p, turn)) for p in t] for t in tiles]
    xs = [p[0] for t in pts for p in t]
    ys = [p[1] for t in pts for p in t]
    pminx, pmaxx, pminy, pmaxy = min(xs), max(xs), min(ys), max(ys)
    # slide the requested window around inside the patch, so different seeds
    # sample different neighbourhoods of the aperiodic tiling
    slack_x = (pmaxx - pminx) * unit - (x1 - x0)
    slack_y = (pmaxy - pminy) * unit - (y1 - y0)
    fx = rng.random() if seed else 0.5
    fy = rng.random() if seed else 0.5
    ox = x0 - pminx * unit - fx * slack_x
    oy = y0 - pminy * unit - fy * slack_y
    for t in pts:
        yield [(p[0] * unit + ox, p[1] * unit + oy) for p in t]


@register("spectre-curved", size="equal-area size; same tiling as 'spectre'",
          edges=14,
          note="the canonical curved-edge Spectre: every straight edge replaced "
               "by an S-curve that is odd-symmetric about the edge midpoint, so "
               "neighbouring tiles still match EXACTLY while a reflected copy "
               "cannot.  This is the strictly chiral tile")
def _spectre_curved(bbox, tile_mm, seed):
    unit = tile_mm / math.sqrt(SPECTRE_UNIT_AREA)
    for ring in _spectre(bbox, tile_mm, seed):
        yield curve_edges(ring, amplitude=0.14 * unit, steps=6)


def curve_edges(ring, amplitude, steps=6):
    """Replace each edge of `ring` by an S-curve, odd-symmetric about the edge
    midpoint.

    The symmetry is what keeps the tiling exact.  Traverse the same edge from
    the other end and the curve comes out identical, so the two tiles that share
    an edge still share it point for point; and because the offset integrates to
    zero over the edge, the tile area is unchanged.
    """
    r = _open(ring)
    out = []
    n = len(r)
    for i in range(n):
        ax, ay = r[i]
        bx, by = r[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L < 1e-12:
            continue
        nx, ny = -ey / L, ex / L
        out.append((ax, ay))
        for s in range(1, steps):
            t = s / steps
            d = amplitude * math.sin(2 * math.pi * t)
            out.append((ax + t * ex + d * nx, ay + t * ey + d * ny))
    return out


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def generate(kind, bbox, tile_mm, seed=0):
    """Tiles of `kind` filling `bbox`, whole tiles only.

    bbox is (x0, y0, x1, y1) in mm.  Returns a list of closed rings (first
    point repeated last), ordered bottom-to-top then left-to-right so output is
    reproducible.
    """
    if kind not in KINDS:
        raise ValueError("unknown tiling %r; have %s" % (kind, ", ".join(kinds())))
    if tile_mm <= 0:
        raise ValueError("tile_mm must be positive, got %r" % (tile_mm,))
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        raise ValueError("empty bbox %r" % (bbox,))
    out = []
    for ring in KINDS[kind].fn((x0, y0, x1, y1), float(tile_mm), int(seed)):
        r = _open(ring)
        bx0, by0, bx1, by1 = bbox_of(r)
        if bx0 < x0 or by0 < y0 or bx1 > x1 or by1 > y1:
            continue          # whole tiles only -- never clip
        out.append(r)
    out.sort(key=lambda r: (round(centroid(r)[1], 6), round(centroid(r)[0], 6)))
    return [r + [r[0]] for r in out]


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------
# Every claim this module makes about its output is checked by one of the four
# functions below.  None of them trusts the generator.
#
# A WARNING ABOUT ONE TEST THAT DOES NOT WORK, so nobody re-invents it: the
# signed area enclosed by the patch boundary is NOT an overlap test.  Build the
# boundary by cancelling each directed edge against its reverse and the enclosed
# signed area comes out equal to the sum of the tile areas whether the tiles
# overlap or not, because the shoelace sum is additive over the multiset of
# tiles.  It is a fine GAP test once overlap has been ruled out some other way,
# and that is all it is used for here.

NM = 1e-6           # KiCad's own file resolution; the quantum for "same point"


def _q(p):
    return (round(p[0] / NM), round(p[1] / NM))


def overlap_audit(tiles, cell=None):
    """Exact-in-spirit pairwise interior-disjointness proof.

    For two simple polygons, if no pair of edges properly crosses and no vertex
    of either lies strictly inside the other, their interiors are disjoint or
    one contains the other.  All tiles of one kind are congruent, so
    containment is impossible unless they coincide -- which the duplicate check
    catches.  A uniform grid supplies the candidate pairs so the cost is near
    linear rather than quadratic.

    Returns dict(pairs_tested, overlapping_pairs, duplicate_tiles, worst=...)
    """
    rings = [_open(t) for t in tiles]
    if not rings:
        return {"pairs_tested": 0, "overlapping_pairs": 0, "duplicate_tiles": 0,
                "examples": []}
    boxes = [bbox_of(r) for r in rings]
    if cell is None:
        cell = max(1e-9, max(b[2] - b[0] for b in boxes))
    grid = defaultdict(list)
    for i, b in enumerate(boxes):
        for gx in range(int(math.floor(b[0] / cell)), int(math.floor(b[2] / cell)) + 1):
            for gy in range(int(math.floor(b[1] / cell)), int(math.floor(b[3] / cell)) + 1):
                grid[(gx, gy)].append(i)
    pairs = set()
    for bucket in grid.values():
        for a in range(len(bucket)):
            for b in range(a + 1, len(bucket)):
                pairs.add((bucket[a], bucket[b]) if bucket[a] < bucket[b]
                          else (bucket[b], bucket[a]))
    seen = {}
    dup = 0
    for i, r in enumerate(rings):
        key = tuple(sorted(_q(p) for p in r))
        if key in seen:
            dup += 1
        else:
            seen[key] = i
    bad = []
    tested = 0
    for i, j in pairs:
        bi, bj = boxes[i], boxes[j]
        if bi[2] < bj[0] - NM or bj[2] < bi[0] - NM or \
           bi[3] < bj[1] - NM or bj[3] < bi[1] - NM:
            continue
        tested += 1
        if not _disjoint(rings[i], rings[j]):
            bad.append((i, j))
    return {"pairs_tested": tested, "overlapping_pairs": len(bad),
            "duplicate_tiles": dup, "examples": bad[:5]}


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _properly_crosses(p, q, r, s):
    e = 1e-9
    d1 = _cross(r, s, p)
    d2 = _cross(r, s, q)
    d3 = _cross(p, q, r)
    d4 = _cross(p, q, s)
    return (((d1 > e and d2 < -e) or (d1 < -e and d2 > e)) and
            ((d3 > e and d4 < -e) or (d3 < -e and d4 > e)))


def _strictly_inside(pt, ring):
    x, y = pt
    n = len(ring)
    inside = False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if abs(_cross((x1, y1), (x2, y2), (x, y))) < 1e-9 and \
           min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and \
           min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            return False              # on the boundary is not inside
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def _disjoint(ra, rb):
    for i in range(len(ra)):
        a1, a2 = ra[i], ra[(i + 1) % len(ra)]
        for j in range(len(rb)):
            if _properly_crosses(a1, a2, rb[j], rb[(j + 1) % len(rb)]):
                return False
    for v in ra:
        if _strictly_inside(v, rb):
            return False
    for v in rb:
        if _strictly_inside(v, ra):
            return False
    return True


def gap_audit(tiles):
    """Boundary-loop census.  Valid as a gap test only once overlap is ruled out.

    Cancels every directed edge against its reverse; whatever survives is the
    boundary of the union.  One loop means one simply connected patch: no holes,
    no seams.  Extra loops with negative area are gaps.  Points are compared at
    nanometre quantisation, KiCad's own file resolution.
    """
    directed = defaultdict(int)
    for t in tiles:
        r = _open(t)
        n = len(r)
        for i in range(n):
            directed[(_q(r[i]), _q(r[(i + 1) % n]))] += 1
    for (a, b) in list(directed):
        n = min(directed.get((a, b), 0), directed.get((b, a), 0))
        if n:
            directed[(a, b)] -= n
            directed[(b, a)] -= n
    adj = defaultdict(list)
    for (a, b), n in directed.items():
        for _ in range(n):
            adj[a].append(b)
    loops = []
    broken = 0
    while adj:
        start = next(iter(adj))
        loop = [start]
        cur = start
        while True:
            if cur not in adj:
                broken += 1
                break
            nxt = adj[cur].pop()
            if not adj[cur]:
                del adj[cur]
            if nxt == start:
                loops.append(loop)
                break
            loop.append(nxt)
            cur = nxt
    areas = [signed_area([(x * NM, y * NM) for x, y in lp]) for lp in loops]
    holes = [a for a in areas if a < 0]
    tile_sum = sum(abs(signed_area(_open(t))) for t in tiles)
    return {"loops": len(loops), "broken_chains": broken,
            "holes": len(holes), "hole_area": -sum(holes),
            "outer_area": sum(a for a in areas if a > 0),
            "sum_tile_areas": tile_sum,
            "gap_area": sum(a for a in areas if a > 0) - sum(-h for h in holes)
                        - tile_sum}


def convex_hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return list(pts)

    def half(seq):
        h = []
        for p in seq:
            while len(h) > 1 and \
                    (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - \
                    (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h

    return half(pts)[:-1] + half(pts[::-1])[:-1]


def fill_fraction(tiles):
    """Covered area as a fraction of the patch's convex hull.

    THE TEST THAT WAS MISSING, and it is the one that caught the level-2
    spectre.  Zero overlaps, one boundary loop and no holes are all satisfied by
    a long sprawling snake of tiles: nothing in those three checks says the
    patch has to be a compact chunk of plane.  A real supertile is as compact as
    the tile it is made of, so this number should barely move between levels --
    a single Tile(1,1) fills 81.5% of its hull and the 9-tile cluster fills
    80.4%.  Anything that drops well below that is not a supertile, whatever
    else it passes, and a rectangular window cut from it comes out full of
    holes.
    """
    rings = [_open(t) for t in tiles]
    covered = sum(abs(signed_area(r)) for r in rings)
    hull = convex_hull([p for r in rings for p in r])
    ha = abs(signed_area(hull))
    return covered / ha if ha > 0 else 0.0


def symmetry_scan(tiles, limit=None):
    """Look for a translational symmetry of the tile-centre point set.

    Rigorous, and cheap, because of one observation: if a vector v translates
    the tiling onto itself then it must in particular carry ONE chosen centre
    onto another centre.  So the only candidate vectors are the differences
    between a fixed anchor centre and every other centre -- n candidates, not
    n^2.  Testing them all therefore rules out every possible translational
    symmetry, not just the ones that occurred to the author.

    For each candidate v the score is measured only where the answer is not an
    artefact of the patch ending.  Let R be the bounding box of the centres,
    eroded on all four sides by `margin` -- one and a half tile diameters, which
    is more than the whole-tile filter can strip off an edge.  The core is then
    {p : p + v lies in R}, so a genuine lattice vector of a periodic tiling
    scores EXACTLY 1.0 (its images are all well inside the patch and therefore
    all present).  An aperiodic tiling cannot score 1.0 on any non-zero v.
    Calibration matters here: if the periodic kinds do not come out at 1.0, the
    test is measuring the patch edge rather than the tiling.

    Returns dict with the best non-zero score and the top offenders.
    """
    cs = [centroid(_open(t)) for t in tiles]
    if len(cs) < 4:
        return {"n_centres": len(cs), "best_score": 0.0, "best_offset": None,
                "exact_repeats": 0, "top": []}
    xs = [c[0] for c in cs]
    ys = [c[1] for c in cs]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    tile_d = math.sqrt(sum(abs(signed_area(_open(t))) for t in tiles) / len(tiles))
    margin = 1.5 * tile_d
    rx0, ry0, rx1, ry1 = x0 + margin, y0 + margin, x1 - margin, y1 - margin
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    anchor = min(cs, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
    pset = {_q(c) for c in cs}
    if limit is None:
        limit = 0.5 * min(x1 - x0, y1 - y0)
    scored = []
    for c in cs:
        v = (c[0] - anchor[0], c[1] - anchor[1])
        L = math.hypot(*v)
        if L < 1e-9 or L > limit:
            continue
        core = [p for p in cs
                if rx0 - 1e-9 <= p[0] + v[0] <= rx1 + 1e-9
                and ry0 - 1e-9 <= p[1] + v[1] <= ry1 + 1e-9]
        if len(core) < max(8, 0.05 * len(cs)):
            continue
        hit = sum(1 for p in core if _q((p[0] + v[0], p[1] + v[1])) in pset)
        scored.append((hit / len(core), L, len(core), hit, v))
    scored.sort(key=lambda t: (-t[0], t[1]))
    exact = sum(1 for s in scored if s[0] > 1.0 - 1e-12)
    return {
        "n_centres": len(cs),
        "candidates_tested": len(scored),
        "best_score": scored[0][0] if scored else 0.0,
        "best_offset": scored[0][4] if scored else None,
        "exact_repeats": exact,
        "top": [{"score": round(s[0], 6), "offset_mm": (round(s[4][0], 4),
                                                        round(s[4][1], 4)),
                 "length_mm": round(s[1], 4), "core": s[2], "hits": s[3]}
                for s in scored[:5]],
    }


def metrics(tiles):
    """Counts, edge census and slot length per unit area.

    slot_len_per_mm2 is the number that decides copper cost: it counts each
    shared edge ONCE, because a slot cut along a shared edge is one slot, not
    two.  Multiply it by the slot width to get the fraction of copper removed.
    """
    rings = [_open(t) for t in tiles]
    n = len(rings)
    if not n:
        return {"n_tiles": 0}
    areas = [abs(signed_area(r)) for r in rings]
    nv = [len(r) for r in rings]
    seen = {}
    for r in rings:
        m = len(r)
        for i in range(m):
            a, b = _q(r[i]), _q(r[(i + 1) % m])
            k = (a, b) if a <= b else (b, a)
            L = math.hypot(r[(i + 1) % m][0] - r[i][0], r[(i + 1) % m][1] - r[i][1])
            e = seen.get(k)
            seen[k] = (L, (e[1] if e else 0) + 1)
    slot_len = sum(L for L, _ in seen.values())
    inner = sum(L for L, c in seen.values() if c >= 2)
    outer = sum(L for L, c in seen.values() if c == 1)
    total_area = sum(areas)
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return {
        "n_tiles": n,
        "edges_per_tile_min": min(nv),
        "edges_per_tile_max": max(nv),
        "tile_area_mm2_mean": total_area / n,
        "tile_area_mm2_spread": max(areas) - min(areas),
        "covered_area_mm2": total_area,
        "unique_edges": len(seen),
        "per_tile_perimeter_mm": sum(perimeter(r) for r in rings) / n,
        "slot_len_mm": slot_len,
        "slot_len_per_mm2": slot_len / total_area,
        # the patch's own outer boundary is an artefact of where we cut the
        # window: in an unbounded tiling those edges would each be shared, so
        # halving them gives the density the pattern actually converges to.
        "slot_len_per_mm2_bulk": (inner + 0.5 * outer) / total_area,
        "fill_fraction": fill_fraction(rings),
        "patch_bbox": (min(xs), min(ys), max(xs), max(ys)),
    }


def validate(kind, bbox=(0.0, 0.0, 60.0, 40.0), tile_mm=4.0, seed=0):
    """Run every check on one kind and return the evidence as a dict."""
    tiles = generate(kind, bbox, tile_mm, seed)
    ev = {"kind": kind, "bbox": bbox, "tile_mm": tile_mm, "seed": seed,
          "metrics": metrics(tiles), "overlap": overlap_audit(tiles),
          "gaps": gap_audit(tiles), "symmetry": symmetry_scan(tiles)}
    return ev


def _fmt(ev):
    m, o, g, s = ev["metrics"], ev["overlap"], ev["gaps"], ev["symmetry"]
    L = []
    L.append("%-15s tile_mm %.3f  seed %d" % (ev["kind"], ev["tile_mm"], ev["seed"]))
    L.append("   tiles %5d   vertices/tile %d..%d   area %.4f mm2 (spread %.2e)"
             % (m["n_tiles"], m["edges_per_tile_min"], m["edges_per_tile_max"],
                m["tile_area_mm2_mean"], m["tile_area_mm2_spread"]))
    L.append("   fit      overlapping pairs %d / %d tested, duplicates %d"
             % (o["overlapping_pairs"], o["pairs_tested"], o["duplicate_tiles"]))
    L.append("   gaps     boundary loops %d (holes %d, hole area %.3e mm2), "
             "broken chains %d" % (g["loops"], g["holes"], g["hole_area"],
                                   g["broken_chains"]))
    L.append("   compact  patch covers %.1f%% of its convex hull"
             % (100.0 * m["fill_fraction"],))
    L.append("   slots    unique edges %d, length %.2f mm, %.4f mm/mm2 in this "
             "window, %.4f mm/mm2 in bulk"
             % (m["unique_edges"], m["slot_len_mm"], m["slot_len_per_mm2"],
                m["slot_len_per_mm2_bulk"]))
    L.append("            at 0.25 mm slot width that is %.1f%% of the copper"
             % (100.0 * m["slot_len_per_mm2_bulk"] * 0.25))
    L.append("   symmetry best non-zero translation scores %.4f over %d "
             "candidates; exact repeats %d"
             % (s["best_score"], s["candidates_tested"], s["exact_repeats"]))
    for t in s["top"][:3]:
        L.append("            %.4f at %s |v| %.3f mm (%d/%d core centres)"
                 % (t["score"], t["offset_mm"], t["length_mm"], t["hits"],
                    t["core"]))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kind", action="append", choices=sorted(KINDS),
                    help="repeatable; default is every kind")
    ap.add_argument("--tile-mm", type=float, default=4.0)
    ap.add_argument("--bbox", type=float, nargs=4,
                    default=[0.0, 0.0, 60.0, 40.0], metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--spectre-fit", action="store_true",
                    help="exact-arithmetic fit audit of the raw spectre patches")
    a = ap.parse_args(argv)
    if a.spectre_fit:
        print("exact fit audit of the spectre substitution (integer arithmetic,")
        print("no tolerance anywhere):")
        for lv in range(0, SPECTRE_PATCH_LEVEL + 1):
            r = spectre_exact_fit(lv)
            tiles = spectre_tiles(lv)
            rings = [[z_xy(p) for p in t] for t in tiles]
            o = overlap_audit(rings, cell=4.0)
            au = spectre_patch_audit(lv)
            print("   level %d  %6d tiles  interior edges %6d  boundary %5d  "
                  "edges shared by 3+ %d  loops %d  broken %d  "
                  "overlapping pairs %d of %d (float) / %d of %d (exact)  "
                  "reflected %d  hull fill %.1f%%   PATCH %s  SUPERTILE %s"
                  % (lv, r["n_tiles"], r["interior_edges"], r["boundary_edges"],
                     r["edges_shared_by_3_or_more"], r["boundary_loops"],
                     r["broken_chains"], o["overlapping_pairs"],
                     o["pairs_tested"], au["overlapping_pairs"],
                     au["pairs_tested"], au["reflected_tiles"],
                     100.0 * au["hull_fill"],
                     "ok" if au["patch_ok"] else "NO",
                     "ok" if au["supertile_ok"] else "NO"))
        print("   two gates, two questions: SPECTRE_SUPERTILE_LEVEL = %d (may I "
              "substitute again), SPECTRE_PATCH_LEVEL = %d (may I place these "
              "tiles and mask them).  See the module docstring."
              % (SPECTRE_SUPERTILE_LEVEL, SPECTRE_PATCH_LEVEL))
        print()
    for k in (a.kind or sorted(KINDS)):
        try:
            print(_fmt(validate(k, tuple(a.bbox), a.tile_mm, a.seed)))
        except RuntimeError as exc:
            print("%-15s UNAVAILABLE: %s" % (k, exc))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
