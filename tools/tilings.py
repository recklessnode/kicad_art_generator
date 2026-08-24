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

FILLING A REGION THAT IS NOT A RECTANGLE.  A card outline is a hexagon or a
rounded rectangle, and its bounding box is up to 15% bigger than the card.

    spectre_region_fill(region, tile_mm, seed=0, keepouts=(), reject=None)

takes the outline itself -- a ring, or a rect if that is what you have -- picks
the deflation depth whose BOUNDARY POLYGON contains it, keeps only whole tiles,
drops every tile a keepout meets, and returns the tiles together with the
ledger that says what happened to the rest.  Same whole-tile rule as generate(),
generalised from a rectangle to a polygon.

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

WHERE THIS STANDS.  The substitution is implemented from the published system
and runs to arbitrary depth.  Every level 0..5 has been audited tile by tile and
pair by pair with exact integer predicates and comes back clean; level 6 --
272791 tiles -- passes the cheaper exact oracles.  SPECTRE_AUDITED_LEVEL is 5
and both gates sit on it.

    lvl   tiles   pairs  proper crossings  interior verts  overlapping pairs
      0       1       0                 0               0                  0
      1       9      21                 0               0                  0
      2      71     209                 0               0                  0
      3     559    1845                 0               0                  0
      4    4401   15339                 0               0                  0
      5   34649  124201                 0               0                  0

with, at every one of those levels, exactly one boundary loop, no holes, no edge
claimed by three or more tiles, no lattice vertex carrying more than 360 degrees
of tile, no tile a mirror image of any other, and an exact area defect at the
float-noise floor.  A level-5 patch is about 680 unit edges across, which is
710 mm at tile_mm 3.0 -- bigger than any board this repo will ever texture.

WHAT WAS WRONG BEFORE, because the fix is one line and the diagnosis took three
sessions.  This module used to build the substitution out of ROTATIONS AND
TRANSLATIONS ONLY.  The published substitution composes a REFLECTION onto all
eight slot transforms at every generation -- the paper says so in one sentence,
"the rules of Figure 2.1 reverse all tile orientations" -- so successive levels
alternate handedness.  Without it:

  * the anchor quad grew by exactly 3.0 per level where SPECTRE_INFLATION =
    sqrt(4 + sqrt 15) = 2.805884 is what the tile counts force;
  * the eight children were therefore pushed 6.9% too far apart every level;
  * level 2 came out as THREE DISCONNECTED LUMPS filling 64% of their hull --
    it passed the overlap audit, which is why it shipped;
  * level 3 had 97 overlapping tile pairs, 128 proper edge crossings, 520
    strictly-interior vertices, 25 edges claimed by three or more tiles and 7
    boundary loops.

With it, the same seven chain rules and the published anchor quad give
2.805883701.  Not instantly: the quad's perimeter is not an eigenvector of the
map, so its subdominant component decays and the per-level ratio runs
2.827766, 2.808774, 2.806253, 2.805931, ... -> 2.805883701, never more than 1%
out.  (An earlier report of this measurement said "exact from the first step";
that was a six-decimal display of the later levels, and it is corrected here.)
The rotation-only 3.0, by contrast, IS exact from the second step and stays
exactly 3.0 forever, which is what makes it so clearly the wrong number rather
than a near miss.  See spectre_quad_inflation(), which still measures both.

AND WHY EVERY SEARCH FOR A BETTER CONSTANT CAME BACK EMPTY, correctly.  The
ledger this docstring used to carry recorded that sweeping all 32^4 = 1048576
super-quad rules found no eigenvalue of modulus 2.805884, that re-deriving the
rules from the verified 9-tile cluster gave 1794 chain descriptions of which the
nine with the canonical rotation sequence all failed the same eigen test, and
that the anchor quad is forced -- exactly four of 24024 ordered vertex 4-tuples
make a valid cluster and all four give the same cluster.  Every one of those
measurements was right and none of them is retracted.  They were all searches
over LINEAR quad maps.  With a reflection in the chain the one-step quad map is
ANTI-linear -- z -> A conj(z) + b -- and its growth lives in the eigenvalues of
A conj(A), which no linear eigenvalue sweep can see.  The searches were sound;
the framework they searched was the defect.

THE NINE LABELS WERE NOT THE FIX, and this is worth saying plainly because it
was the standing hypothesis.  The published system has nine metatile labels
(Gamma, Delta, Theta, Lambda, Xi, Pi, Sigma, Phi, Psi) where this module had two
clusters, and issue #8 proposed that restoring them -- each with its own quad --
was what would inflate correctly.  It is not.  The published system shares ONE
quad across all nine labels, exactly as the two-cluster code did; and every row
of the substitution table places Gamma at slot 7 and nowhere else, and only
Gamma's row drops a slot, so by induction all eight non-Gamma supertiles are the
IDENTICAL point set at every level.  Nine labels, two distinct geometries.  The
labels are implemented here because they are the published system and because
they carry the hierarchy bookkeeping the aperiodicity argument needs, but they
are geometrically redundant and the old collapse was faithful.

MEASURED, on both diagonals of the 2x2, because "it works now" is not evidence
about which change did it.  Same published quad, same super-quad rule, same
chain rules; only the labels and the reflection vary:

    labels    reflection    level 2                level 3
    nine      no            9 overlapping pairs    1908 overlapping pairs
    nine      YES           0                      0
    two       YES           0                      0

The nine labels without the reflection are WORSE than the two clusters without
it were.  The two clusters with the reflection are clean.  So the reflection is
necessary and sufficient and the nine labels are neither -- which makes issue
#8's hypothesis a second honest negative result, in the same spirit as the
first.  The labels are kept because they are the published system and cost
nothing; the ledger is what the measurement says, not what the hypothesis said.

  ESTABLISHED, by measurement, not assertion:
    * Tile(1,1) itself, derived here from its structure rather than copied from
      anyone's coordinate list -- and the derivation is checked: 14 unit edges,
      all directions multiples of 30 degrees, "1/3" and "1/4" vertex classes
      alternating, exactly one straight vertex, area 3 + 3*sqrt(3).  There are
      exactly two such 14-gons and they are mirror images; this is one of them.
    * The eight-slot substitution rule places eight children and leaves a hole
      of exactly one tile area, and that hole is congruent to the tile BY A PURE
      ROTATION.  That is the whole point: had it needed a mirrored tile this
      would be the hat, which cannot tile without both handednesses.
    * HOMOCHIRALITY, which is the claim that actually matters and is not quite
      the claim this module used to make.  Within any one patch, no tile is a
      mirror image of any other -- asserted tile by tile, exactly, at every
      level built.  Across LEVELS the handedness alternates, because the
      substitution reverses orientation; a level-3 patch is built from mirror
      images of the tile a level-2 patch is built from.  spectre_tiles() undoes
      that so its output is always in Tile(1,1)'s own handedness;
      spectre_patch() does not, because its anchor quad is only meaningful in
      the frame the chain built it in.  MEASURED: reflect a level-1 patch and
      its quad together and substitute again and you get 9 overlapping pairs and
      35 edges claimed by three or more tiles.  That is why the two entry points
      differ, and it is the one place a caller can be surprised.
    * Both cluster types, with the published counts: a non-Gamma supertile is
      7 Spectres + 1 Mystic and Gamma is 6 Spectres + 1 Mystic, giving
      1, 9, 71, 559, 4401, 34649 and 2, 8, 62, 488, 3842, 30248.  The Perron
      eigenvalue of [[7,1],[6,1]] is 4 + sqrt(15) = 7.873 -- NOT 8, which is why
      a fixed eight-fold substitution could never have been the right shape.

  A SUPERTILE IS RAGGED, and one acceptance number had to change because of it.
  The old supertile test demanded hull fill >= 0.75, calibrated on a lone tile
  (0.8146) and the 9-tile cluster (0.8040).  That was a good proxy while the
  alternative was a ring of clusters around a void -- it is what caught the old
  level 2 -- but it is not a property of the real object: the correct patches
  fill 0.8146, 0.8040, 0.7076, 0.6510, 0.6266, 0.6177 of their hulls at levels
  0..5, converging to about 0.61.  The criterion is now the thing hull fill was
  standing in for and that the old level 2 actually failed: ONE boundary loop,
  no holes, no edge shared by three or more tiles.

  WHAT THIS COSTS THE WINDOW-FILLING KIND.  A ragged patch means the bounding
  box is not a coverage test.  `kind="spectre"` now checks that the requested
  window lies inside the patch's BOUNDARY POLYGON before serving it, because a
  window that merely fits the bbox can enclose a bay of the patch's own outline
  and come back with a hole in it -- measured, on a 14 x 14 mm window at
  tile_mm 4.  See _spectre_levels_for().

  STILL NOT CLAIMED: that the tiling this module emits is aperiodic as a matter
  of proof.  What is now available is evidence rather than nothing.  The
  standing test used to be a strict xfail reading "a 9-tile cluster is far too
  small to scan"; it is now a real assertion, run on the 559-tile level-3 patch
  -- symmetry_scan() is quadratic in the tile count, so level 3 is what fits in
  a test suite, and it is two orders of magnitude more than there was.  Hundreds
  of candidate translations, none scoring above 0.5, on a scan the periodic
  kinds are calibrated to score exactly 1.0 on.  Absence of a translational
  symmetry in a finite patch is still not a proof about the infinite tiling, and
  this module does not pretend otherwise.

WHERE THIS IMPLEMENTATION CAME FROM, for the licence file.  The substitution
system -- the nine-row rule table, the seven chain rules, the anchor quad, the
super-quad recursion and the per-generation reflection -- is the published
mathematics of Smith, Myers, Kaplan and Goodman-Strauss, "A chiral aperiodic
monotile" (arXiv:2305.17743, Combinatorial Theory 4(2), 2024), and is
implemented here from that mathematics.  Kaplan's reference application was
consulted as an existence proof and as a source of test vectors -- specifically
to confirm the rule table and to establish that this module's own vertex
numbering is the published one shifted by 12 and turned 30 degrees, which is a
measurement made against its coordinate list and recorded as the constant
SPECTRE_QUAD_IDX.  No source was copied from it.

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
    """Apply a motion.  Accepts either shape, so callers written against the
    orientation-preserving (k, t) motions keep working now that the
    substitution hands out reflective (k, r, t) ones."""
    if len(m) == 3:
        return r_apply(m, p)
    k, t = m
    return z_add(z_rot(p, k), t)


def m_compose(outer, inner):
    """outer after inner."""
    ko, to = outer
    ki, ti = inner
    return ((ko + ki) % 12, z_add(z_rot(ti, ko), to))


def z_conj(p):
    """Complex conjugation -- reflect across the x-axis.  Exact, and integral.

    THE OPERATION THIS MODULE USED TO BE UNABLE TO EXPRESS, and the whole reason
    the substitution used to fall apart at level 3.  It is exact for the same
    reason rotation is: conjugation permutes the twelfth roots of unity, so it
    maps Z[d] to itself.  From d^4 = d^2 - 1 one gets d^6 = -1 and hence
    d^9 = -d^3, d^10 = 1 - d^2, d^11 = d - d^3, so

        conj(a0 + a1 d + a2 d^2 + a3 d^3)
            = a0 + a1 d^11 + a2 d^10 + a3 d^9
            = (a0 + a2) + a1 d - a2 d^2 + (-a1 - a3) d^3.

    No square roots, no floats, no tolerance -- an integer 4-tuple in and an
    integer 4-tuple out, which is what keeps every downstream audit exact.
    """
    a0, a1, a2, a3 = p
    return (a0 + a2, a1, -a2, -a1 - a3)


# A REFLECTIVE motion is (k, r, t): conjugate if r, then rotate by k*30
# degrees, then translate by t.  This is the full 24-element point group of the
# triangular lattice plus translations; (k, t) above is the orientation-
# preserving half of it and is kept because several measurements and one test
# are statements about that half specifically.
RIDENT = (0, 0, ZERO)
REFLECT = (0, 1, ZERO)


def r_apply(m, p):
    k, r, t = m
    if r:
        p = z_conj(p)
    return z_add(z_rot(p, k), t)


def r_compose(outer, inner):
    """outer after inner, for reflective motions.

    Conjugation anticommutes with rotation -- C R_k = R_-k C -- which is the
    only wrinkle: the outer reflection flips the sign of the inner rotation.
    """
    ko, ro, to = outer
    ki, ri, ti = inner
    return ((ko + (-ki if ro else ki)) % 12, ro ^ ri,
            z_add(r_apply((ko, ro, ZERO), ti), to))


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

# The four anchor ("quad") vertices the rules index into.  This is the paper's
# quad, mapped into this module's vertex numbering: this polygon's vertex i is
# the published polygon's vertex (i + 12) mod 14 turned 30 degrees -- measured,
# by matching the two edge-direction sequences, and there is NO reflection in
# that map, so the two tiles are the same handedness.  The published quad
# (3, 5, 7, 11) therefore lands on (5, 7, 9, 13) here.
#
# It is one of exactly four ordered 4-tuples out of 24024 that make the chain
# below close into a valid 9-tile cluster (see the test that sweeps them), and
# all four give the SAME cluster -- but they are NOT interchangeable above level
# 1, because SPECTRE_SUPER_QUAD indexes into the quad and the four quads are
# different point sets.  The one that goes with the published super-quad rule is
# this one.
SPECTRE_QUAD_IDX = (5, 7, 9, 13)

# What the rotation-only framework used, kept so the historical measurement
# below can still be reproduced exactly rather than merely described.
SPECTRE_LEGACY_QUAD_IDX = (3, 7, 11, 13)

# The substitution has NINE metatile labels, and collapsing them was one of the
# two things wrong with the old implementation here:
#
#   Gamma is the MYSTIC -- a two-Spectre compound.  The other eight are single
#   Spectres at level 0.  Each label inflates to eight slots; Gamma's row leaves
#   one slot empty, so
#
#     non-Gamma supertile = 7 Spectres + 1 Mystic   (9 tiles at the bottom)
#     Gamma    supertile  = 6 Spectres + 1 Mystic   (8 tiles at the bottom)
#
# and with n and g tiles in the two at one level, the next has n' = 7n + g and
# g' = 6n + g.  The Perron eigenvalue of [[7,1],[6,1]] is 4 + sqrt(15) = 7.873
# -- NOT 8.  Any fixed eight-fold rule therefore has the wrong growth rate.
#
# THE NINE LABELS ARE HERE BECAUSE THEY ARE THE PUBLISHED SYSTEM, NOT BECAUSE
# THEY FIXED ANYTHING.  Read the table: every row places Gamma at slot 7 and
# nowhere else, and only Gamma's row drops a slot.  So by induction on the level,
# all eight non-Gamma supertiles are the IDENTICAL point set at every level, and
# the nine labels have exactly two distinct geometries between them -- which is
# what the old two-cluster code already had.  The labels carry the hierarchy
# bookkeeping that the aperiodicity proof needs; they do not carry geometry.
# _spectre_build() exploits that, but by object identity rather than by
# assumption: see the comment there.
SPECTRE_LABELS = ("Gamma", "Delta", "Theta", "Lambda", "Xi",
                  "Pi", "Sigma", "Phi", "Psi")

SPECTRE_SUBSTITUTION = {
    "Gamma":  ("Pi", "Delta", None,   "Theta", "Sigma", "Xi",  "Phi",    "Gamma"),
    "Delta":  ("Xi", "Delta", "Xi",   "Phi",   "Sigma", "Pi",  "Phi",    "Gamma"),
    "Theta":  ("Psi", "Delta", "Pi",  "Phi",   "Sigma", "Pi",  "Phi",    "Gamma"),
    "Lambda": ("Psi", "Delta", "Xi",  "Phi",   "Sigma", "Pi",  "Phi",    "Gamma"),
    "Xi":     ("Psi", "Delta", "Pi",  "Phi",   "Sigma", "Psi", "Phi",    "Gamma"),
    "Pi":     ("Psi", "Delta", "Xi",  "Phi",   "Sigma", "Psi", "Phi",    "Gamma"),
    "Sigma":  ("Xi", "Delta", "Xi",   "Phi",   "Sigma", "Pi",  "Lambda", "Gamma"),
    "Phi":    ("Psi", "Delta", "Psi", "Phi",   "Sigma", "Pi",  "Phi",    "Gamma"),
    "Psi":    ("Psi", "Delta", "Psi", "Phi",   "Sigma", "Psi", "Phi",    "Gamma"),
}

# SPECTRE_GAMMA_SLOT is the slot that carries the Mystic; SPECTRE_DROP_SLOT is
# the slot Gamma's own row leaves out.  Both are now READ OFF the table above
# rather than found by search, and both are asserted against it at import so the
# table and the two shortcut constants cannot drift apart.
SPECTRE_GAMMA_SLOT = 7
SPECTRE_DROP_SLOT = 2

assert all(row.index("Gamma") == SPECTRE_GAMMA_SLOT and
           row.count("Gamma") == 1
           for row in SPECTRE_SUBSTITUTION.values()), \
    "Gamma is not at slot %d in every row" % SPECTRE_GAMMA_SLOT
assert SPECTRE_SUBSTITUTION["Gamma"].index(None) == SPECTRE_DROP_SLOT
assert all(None not in row for L, row in SPECTRE_SUBSTITUTION.items()
           if L != "Gamma"), "only Gamma's row may drop a slot"
assert all(set(row) - {None} <= set(SPECTRE_LABELS)
           for row in SPECTRE_SUBSTITUTION.values())

# The Mystic's second tile, relative to the Gamma slot: rotate 30 degrees, then
# translate.  This is the transform that was measured to fill the hole.
SPECTRE_MYSTIC = (1, (0, 1, 0, 1))


def spectre_slot_motions(quad, rules=None, reflect=False):
    """The eight child placements for one substitution step.

    `reflect` is the whole difference between a spectre substitution that works
    and the one this module shipped for months.

    The seven chain rules are the authors' and are unchanged.  What the paper
    adds, and what was missing here, is one sentence: the rules REVERSE ALL TILE
    ORIENTATIONS, so a reflection is composed onto all eight slot transforms at
    every generation and successive levels alternate handedness.  With
    reflect=False the eight motions are rotations and translations, the one-step
    quad map is LINEAR, its growth is one of four eigenvalues, and the module
    docstring's ledger of dead ends -- the 32^4 super-quad sweep, the 1794-chain
    re-derivation -- is a complete search of that space.  With reflect=True the
    map is ANTI-linear (z -> A conj(z) + b), its growth lives in the eigenvalues
    of A conj(A), and no linear eigenvalue sweep can see it.  That is why every
    one of those searches came back empty and every one of them was right.

    Measured, both ways, by spectre_quad_inflation(): 3.0 without, and
    2.805884 = sqrt(4 + sqrt 15) exactly and from the first step, with.
    """
    motions = [RIDENT]
    total = 0
    k = 0
    tquad = list(quad)
    for turn, frm, to in (rules or SPECTRE_RULES):
        if turn:
            total += turn
            k = total % 12
            tquad = [z_rot(q, k) for q in quad]
        prev = motions[-1]
        anchor = r_apply(prev, quad[frm])
        motions.append((k, 0, z_sub(anchor, tquad[to])))
    if reflect:
        motions = [r_compose(REFLECT, m) for m in motions]
    return motions


# The linear inflation the tile counts force.  A level-n metatile is a union of
# n_k congruent tiles and n_k grows by the Perron eigenvalue 4 + sqrt(15), so its
# AREA grows by that and its LINEAR size by the square root.  Everything that
# scales with the metatile -- the anchor quad above all -- has to grow by this
# and nothing else.
SPECTRE_INFLATION = math.sqrt(4.0 + math.sqrt(15.0))     # 2.805884


def spectre_quad_inflation(levels=8, super_quad=None, rules=None,
                           quad_idx=None, reflect=True):
    """How fast the anchor quad actually grows, per substitution step.

    THE ONE-LINE DIFFERENCE BETWEEN THE BROKEN SYSTEM AND THE WORKING ONE, and
    it is a measurement rather than an argument.  One substitution step maps the
    quad by

        Q'[i] = motions(Q)[a_i] applied to Q[b_i]

    With reflect=False the eight slot motions are LINEAR in Q -- the rotations
    come from the cumulative turns in `rules` and never touch the quad at all,
    and each translation is a fixed ring combination of the four quad points --
    so the quad map is a fixed 4x4 linear map and the quad grows by one of its
    four eigenvalues.  With reflect=True a conjugation is composed onto every
    slot transform and the map becomes ANTI-linear; its growth is set by the
    eigenvalues of A conj(A), which no linear eigenvalue sweep can see.

    Iterating and watching the perimeter measures the factor directly, and the
    two answers are the whole story of this module's spectre:

        reflect=False, legacy quad and super-quad    ->  exactly 3.0, forever
        reflect=True,  published quad and super-quad ->  2.805883701

    The second CONVERGES to its value rather than starting there: the quad's
    perimeter is not an eigenvector of the map, so the subdominant component
    decays and the ratio runs 2.827766, 2.808774, 2.806253, ... -- never more
    than 1% out.  The first is exactly 3.0 from the second step on, which is the
    tell: 3.0 is not a near miss to be tuned away, it is a different eigenvalue.

    SPECTRE_INFLATION = sqrt(4 + sqrt 15) = 2.805884 is what the tile counts
    force.  The old 3.0 outran the metatile by 6.9% per level, which pushed the
    eight children apart, which is why the old level-2 patch was three
    disconnected lumps around a void and the old level 3 had 97 overlapping
    pairs.  Everything in the ledger that searched for a better constant was
    searching the linear framework, and was correct that nothing there works.

    Returns (factor, perimeters).
    """
    quad = tuple(SPECTRE[i] for i in (quad_idx or SPECTRE_QUAD_IDX))
    sq = super_quad or SPECTRE_SUPER_QUAD
    per = []
    for _ in range(max(2, int(levels))):
        motions = spectre_slot_motions(quad, rules, reflect)
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


def convex_hull(points):
    """Monotone chain.  Defined here, above the spectre, because the spectre's
    extent machinery needs it at import time."""
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
# This is the published super-quad rule, and it is the one issue #8 tested and
# rejected -- correctly, in the rotation-only framework, where it inflates at
# 1.05-ish and wanders.  With the reflection in the chain it inflates at exactly
# SPECTRE_INFLATION from the first step.  The rule did not change; the group the
# motions live in did.
SPECTRE_SUPER_QUAD = ((6, 2), (5, 1), (3, 2), (0, 1))

# What the rotation-only framework used.  Kept, with the legacy quad above, so
# that spectre_quad_inflation(reflect=False, ...) still reproduces the historical
# 3.0 measurement exactly -- the evidence that the diagnosis is right is that the
# SAME code with the SAME rules gives 3.0 one way and 2.805884 the other.
SPECTRE_LEGACY_SUPER_QUAD = ((0, 1), (2, 1), (5, 1), (5, 3))

# THE DEEPEST LEVEL AUDITED TILE BY TILE AND PAIR BY PAIR.  It is 5 -- 34,649
# tiles -- and it is 5 because that is what has actually been run, not because
# anything is known to break at 6.  Every level 0..5 passes spectre_patch_audit()
# with 0 overlapping pairs, 0 proper edge crossings, 0 strictly-interior
# vertices, 0 reflected tiles, exactly one boundary loop and no holes.
#
# Level 6 (272,791 tiles) was checked too, with the three oracles that are cheap
# enough to run at that size -- the exact edge/angle census, an independent
# shapely union, and 2e6 uniform sample points -- and is clean: no edge claimed
# by three or more tiles, no lattice vertex carrying more than 360 degrees of
# tile, union area equal to the sum of tile areas to 4e-8 mm2 in one simply
# connected part with no interior rings, no sample point covered twice.  It is
# not the audited constant because the full exhaustive pair audit was not run on
# it.  Raise this the day you run it.
SPECTRE_AUDITED_LEVEL = 5

# The deepest substitution level that is a SUPERTILE -- something you may hand
# the anchor quad for and substitute again.
#
# IT WAS 1 FOR A REASON THAT WAS REAL AND IS NOW FIXED, and the honest history
# matters because the fix is not the one the ledger predicted.  The old system
# grew its anchor quad by exactly 3.0 per level where SPECTRE_INFLATION =
# 2.805884 is required; the eight children were pushed 6.9% too far apart every
# level; level 2 came out as three disconnected lumps filling 64% of its hull,
# and level 3 had 97 overlapping tile pairs.  The module then searched, hard and
# correctly, for a better anchor quad -- all 32^4 super-quad rules, 1794
# re-derived chain descriptions -- and found nothing, because every one of those
# searches was a search over LINEAR quad maps and the published map is not
# linear.  The published substitution composes a REFLECTION onto all eight slot
# transforms every generation ("the rules reverse all tile orientations"), which
# makes the one-step quad map anti-linear and its growth invisible to any
# eigenvalue sweep.  Adding z_conj() to the motion algebra is the entire fix.
#
# WHAT THIS CONSTANT GATES, unchanged in meaning:
#   * further substitution -- any use of the anchor quad spectre_patch() returns;
#   * any claim of self-similarity or supertile-hood;
#   * the CLI's level walk.
# It does NOT gate "may I place these tiles on a board and mask them".  That is
# SPECTRE_PATCH_LEVEL below.  The two questions still have separate constants,
# and the constants now happen to have the same value -- which is what it looks
# like when the geometry is right rather than when one gate has been loosened.
SPECTRE_SUPERTILE_LEVEL = SPECTRE_AUDITED_LEVEL

# The old name, kept as an alias because it is what several callers, tests and
# error messages say.  It means what it always meant: the deepest SUPERTILE
# level.
SPECTRE_VERIFIED_LEVEL = SPECTRE_SUPERTILE_LEVEL

# The deepest level that is a valid PATCH: a set of tiles with pairwise disjoint
# interiors that you place once and then mask.
#
# ITS ACCEPTANCE TEST IS STILL DELIBERATELY WEAKER THAN THE SUPERTILE'S, and the
# two constants stay separate for that reason and not for their current values.
# A patch consumer asks "do these tiles overlap" and nothing else.  A supertile
# consumer additionally needs the thing to be one connected simply-connected
# lump it can inflate again.
#
# ONE ACCEPTANCE NUMBER HAD TO CHANGE AND IT IS WORTH KNOWING WHY.  The old
# supertile test demanded hull fill >= 0.75, calibrated on a lone tile (0.8146)
# and the 9-tile cluster (0.8040).  That threshold does not survive contact with
# a real spectre supertile: the correct patches fill 0.8146, 0.8040, 0.7076,
# 0.6510, 0.6266, 0.6177 of their hulls at levels 0..5, converging to about 0.61
# because the supertile boundary is genuinely ragged and stays ragged -- look at
# a picture of level 3.  Hull fill was a good proxy for "is this a compact chunk
# of plane" when the alternative was a ring of clusters around a void; it is not
# a property of the real object.
#
# IT WAS REPLACED ONCE BY THE WRONG THING, AND THE RECORD OF THAT MATTERS MORE
# THAN THE CURRENT VALUE.  The first replacement was "one boundary loop, no
# broken chains, no edge shared by three or more tiles", justified by the claim
# that this is what the old level 2 failed.  It is not: measured, by rebuilding
# the rotation-only construction and running it through spectre_patch_audit(),
# the old level-2 patch scores boundary_loops 1, broken_chains 0 and
# edges_shared_by_3_or_more 0 -- it PASSED.  Three lumps touching at two
# vertices trace one closed boundary curve, so a loop count is not a
# connectivity test.  What replaces hull fill is the property itself, counted
# exactly: tile_components == 1 and boundary_pinch_vertices == 0.  See
# spectre_patch_audit().
SPECTRE_PATCH_LEVEL = SPECTRE_AUDITED_LEVEL


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

    Both sequences are now built and audited rather than merely predicted:
    1, 9, 71, 559, 4401, 34649 for a non-Gamma supertile and 2, 8, 62, 488,
    3842, 30248 for Gamma.  See SPECTRE_AUDITED_LEVEL.
    """
    n, g = 1, 2
    for _ in range(max(0, int(levels))):
        n, g = 7 * n + g, 6 * n + g
    return n


def spectre_mystic_size(levels):
    """Tile count of a level-`levels` GAMMA (Mystic) supertile: 2, 8, 62, ..."""
    n, g = 1, 2
    for _ in range(max(0, int(levels))):
        n, g = 7 * n + g, 6 * n + g
    return g


_PATCH_CACHE: dict[int, tuple] = {}


def spectre_patch(levels):
    """The substitution `levels` times, as (tiles, quad).  SUPERTILE gate.

    All nine metatile labels are carried along, because each is defined in terms
    of the others; this returns the ordinary (non-Gamma) supertile, which is what
    every caller means by "the patch".  spectre_mystic_tiles() is the other one.
    Tile counts come out 1, 9, 71, 559, 4401, 34649 and 2, 8, 62, 488, 3842,
    30248, which is the published recurrence and is asserted by the tests.

    Returns (tiles, quad): `tiles` is a tuple of exact 14-point polygons in the
    ring Z[d], `quad` the anchor quad of the whole patch.

    IN THE SUBSTITUTION'S OWN FRAME, NOT NORMALISED.  The published substitution
    reverses orientation every generation, so at ODD levels these tiles are
    mirror images of the module's SPECTRE constant -- one handedness throughout,
    as a spectre tiling must be, just the other one.  The quad is only meaningful
    in that frame (MEASURED: reflect a patch and its quad together and substitute
    again and you get 9 overlapping pairs), which is why this entry point does
    not normalise and spectre_tiles(), which returns no quad, does.

    THIS ENTRY POINT IS GATED AT SPECTRE_SUPERTILE_LEVEL, and the gate now means
    "nobody has run the exhaustive audit past here" rather than "this is known to
    break".  The refusal names the audit to run and the constant to raise; both
    are cheap and neither is a search for a magic constant any more.
    """
    levels = int(levels)
    if levels < 0:
        raise ValueError("levels must be >= 0")
    if levels > SPECTRE_SUPERTILE_LEVEL:
        raise RuntimeError(
            "spectre level %d is past SPECTRE_SUPERTILE_LEVEL = %d, which is "
            "the deepest level whose %d tiles have been audited pair by pair "
            "with exact integer predicates.  Nothing is known to break above "
            "it -- level 6 (272791 tiles) passes the cheaper oracles -- but "
            "'not known to break' is not what this gate hands out.  To go "
            "deeper: run spectre_patch_audit(%d), which is ungated, and if it "
            "returns supertile_ok raise SPECTRE_AUDITED_LEVEL."
            % (levels, SPECTRE_SUPERTILE_LEVEL,
               spectre_patch_size(SPECTRE_SUPERTILE_LEVEL), levels))
    tiles, quad, _gamma = _spectre_build(levels)
    return tiles, quad


def spectre_tiles(levels):
    """The substitution `levels` times, TILES ONLY.  PATCH gate.

    Same construction as spectre_patch(), same cache, and deliberately no anchor
    quad: a patch consumer places the tiles once and masks them, and has no use
    for the quad.  Serves up to SPECTRE_PATCH_LEVEL, whose disjointness is proved
    exactly by spectre_patch_audit().
    """
    levels = int(levels)
    if levels < 0:
        raise ValueError("levels must be >= 0")
    if levels > SPECTRE_PATCH_LEVEL:
        raise RuntimeError(
            "spectre level %d is past SPECTRE_PATCH_LEVEL = %d (%d tiles), "
            "which is the deepest level spectre_patch_audit() has been run on "
            "exhaustively.  Overlapping tiles mean overlapping slots, so this "
            "module does not hand out a patch nobody has measured.  "
            "spectre_patch_audit(%d) is ungated: run it, and raise "
            "SPECTRE_AUDITED_LEVEL if it passes."
            % (levels, SPECTRE_PATCH_LEVEL,
               spectre_patch_size(SPECTRE_PATCH_LEVEL), levels))
    return _spectre_handed(levels)[0]


def spectre_mystic_tiles(levels):
    """The level-`levels` GAMMA (Mystic) supertile, tiles only.

    Same gate as spectre_tiles().  Exposed because the Gamma supertile is the
    other half of the recursion and the only place the nine-label table shows
    geometrically: it is the one row that drops a slot.
    """
    levels = int(levels)
    if levels < 0:
        raise ValueError("levels must be >= 0")
    if levels > SPECTRE_PATCH_LEVEL:
        raise RuntimeError(
            "spectre level %d is past SPECTRE_PATCH_LEVEL = %d; see "
            "spectre_tiles()." % (levels, SPECTRE_PATCH_LEVEL))
    return _spectre_handed(levels)[1]


def _spectre_build(levels):
    """The substitution itself, ungated.  Private: every public caller goes
    through one of the two gates above, which is what keeps the supertile
    question and the patch question from being answered by the same constant.

    Returns (non_gamma_tiles, quad, gamma_tiles).

    THE THREE THINGS THIS DOES THAT THE OLD ONE DID NOT:

      1. all nine published metatile labels, each with its own row of the
         substitution table, rather than two hand-rolled "clusters";
      2. the anchor quad is the published one and is advanced by the published
         super-quad rule;
      3. the slot motions carry the per-generation REFLECTION, which is the
         load-bearing change.  (1) and (2) alone still produce the broken level
         3; (3) alone, with the old two-cluster code, does not have the right
         quad to reflect.  All three together give 0 overlapping pairs at every
         level anyone has measured.

    A NOTE ON THE MEMOISATION, because it looks like the exact shortcut that hid
    the old bug and is not.  Two labels whose rows resolve to the SAME EIGHT
    CHILD OBJECTS get the same eight motions applied to the same eight point
    sets, so their supertiles are the same object -- that is identity reasoning
    about this loop, not an assumption about spectre geometry.  It happens to
    collapse the nine rows to two distinct computations per level, because every
    row places Gamma at slot 7 and only Gamma's row drops a slot; if a future
    table broke that, this code would simply do the full nine.  The collapse is
    an OUTPUT of the table here, where in the old code it was an input.
    """
    levels = int(levels)
    if levels < 0:
        raise ValueError("levels must be >= 0")
    if levels in _PATCH_CACHE:
        return _PATCH_CACHE[levels]

    quad = tuple(SPECTRE[i] for i in SPECTRE_QUAD_IDX)
    spectre_only = (SPECTRE,)
    tiles = {L: spectre_only for L in SPECTRE_LABELS}
    tiles["Gamma"] = tuple(_mystic(SPECTRE))

    for _ in range(levels):
        motions = spectre_slot_motions(quad, reflect=True)
        nxt = {}
        done = {}
        for L in SPECTRE_LABELS:
            row = SPECTRE_SUBSTITUTION[L]
            key = tuple(None if c is None else id(tiles[c]) for c in row)
            hit = done.get(key)
            if hit is None:
                acc = []
                for slot, child in enumerate(row):
                    if child is None:
                        continue
                    m = motions[slot]
                    for t in tiles[child]:
                        acc.append(tuple(r_apply(m, p) for p in t))
                hit = done[key] = tuple(acc)
            nxt[L] = hit
        quad = tuple(r_apply(motions[a], quad[b]) for a, b in SPECTRE_SUPER_QUAD)
        tiles = nxt

    out = (tiles["Delta"], quad, tiles["Gamma"])
    _PATCH_CACHE[levels] = out
    return out


_NORM_CACHE: dict[int, tuple] = {}


def _spectre_handed(levels):
    """The level-`levels` patches turned back into Tile(1,1)'s own handedness.

    Returns (non_gamma_tiles, gamma_tiles), congruent to what _spectre_build()
    produced by AT MOST one global reflection -- so every overlap, gap, edge and
    angle measurement is identical, and only which of the two mirror-image
    14-gons the tiles are copies of changes.

    WHY THIS EXISTS.  The published substitution reverses orientation at every
    generation, so a level-n patch is made of mirror images of Tile(1,1) when n
    is odd.  That is the real mathematics and _spectre_build() keeps it, because
    the anchor quad is only meaningful in the frame the chain built it in --
    MEASURED: reflect a level-1 patch and its quad together and substitute again
    and you get 9 overlapping pairs, 35 edges claimed by three or more tiles.
    So the quad-bearing path never normalises.

    Everything downstream of a patch, though, places tiles and forgets the quad,
    and it wants the handedness not to flip when the level does.  Normalising
    here costs one integer negation per coordinate and makes spectre_tiles(1)
    not merely congruent to the module's original verified 9-tile cluster but
    IDENTICAL to it.

    The handedness is MEASURED, not inferred from the parity of `levels`, and
    every tile is then checked to agree with the first.  A patch that mixed
    handedness would be a hat tiling, not a spectre one, and this is where that
    would be caught.
    """
    levels = int(levels)
    if levels in _NORM_CACHE:
        return _NORM_CACHE[levels]
    tiles, _quad, gamma = _spectre_build(levels)
    flip = not _is_rotation_of_tile(tiles[0])
    if flip:
        tiles = tuple(tuple(z_conj(p) for p in t) for t in tiles)
        gamma = tuple(tuple(z_conj(p) for p in t) for t in gamma)
    bad = [i for i, t in enumerate(tiles) if not _is_rotation_of_tile(t)]
    if bad:
        raise AssertionError(
            "spectre level %d mixes handedness: %d of %d tiles are mirror "
            "images of the rest (first at index %d).  That is a hat tiling, "
            "not a spectre one, and it means the substitution is wrong."
            % (levels, len(bad), len(tiles), bad[0]))
    out = (tiles, gamma)
    _NORM_CACHE[levels] = out
    return out


def spectre_exact_fit(levels, gamma=False, tiles=None):
    """Exact fit audit of a spectre patch: no tolerance anywhere.

    Returns a dict with the edge census and the boundary loops.  `interior`
    edges are shared by exactly two tiles; `shared3` counts edges claimed by
    three or more, which is only possible if two tiles overlap; `loops` is the
    set of boundary cycles.

    TWO OF THE FIELDS ANSWER "IS THIS ONE LUMP", AND boundary_loops IS NOT ONE
    OF THEM.  That was the assumption a supertile gate was briefly built on and
    it is false.  A boundary cycle passes through a PINCH -- a vertex where two
    otherwise separate lumps touch at a point -- without noticing, so three
    lumps joined at two points trace out a single closed boundary walk with no
    hole in it.  Measured, on this module's own predecessor: the rotation-only
    level-2 patch is three edge-connected components and reports
    boundary_loops == 1, broken_chains == 0, edges_shared_by_3_or_more == 0.
    The two fields that do answer the question are

        tile_components            edge-connected components of the tile set;
                                   one lump means exactly 1
        boundary_pinch_vertices    boundary vertices with more than one
                                   outgoing boundary edge; a simply connected
                                   region has 0

    and both are exact integer counts, not proxies.  `boundary_loops` remains
    the hole test, which is what it is good for: with 0 pinches, a second loop
    is a hole and nothing else.

    UNGATED on purpose: this is a measurement, not a supplier of tiles, and
    refusing to measure a level is how level 2 sat unexamined for a session.

    `gamma` measures the Mystic (Gamma) supertile instead of the ordinary one.
    Both have to be sound: each is built out of copies of the other.

    `tiles` measures an EXPLICIT tile list instead of a level of this module's
    own substitution, so that a patch built some other way -- an older
    construction, a hand-made counterexample -- can be put through the identical
    census.  There was no way to do that when the supertile gate was rewritten,
    which is why the claim about what the old level 2 failed went unchecked.
    """
    tiles = (_spectre_handed(levels)[1 if gamma else 0] if tiles is None
             else tuple(tuple(t) for t in tiles))
    owners = defaultdict(list)
    directed = defaultdict(int)
    for ti, t in enumerate(tiles):
        n = len(t)
        for i in range(n):
            a, b = t[i], t[(i + 1) % n]
            owners[(a, b) if a <= b else (b, a)].append(ti)
            directed[(a, b)] += 1
    shared3 = sum(1 for v in owners.values() if len(v) > 2)
    interior = sum(1 for v in owners.values() if len(v) == 2)
    boundary = sum(1 for v in owners.values() if len(v) == 1)
    # Edge-connected components of the tile set, by union-find over the edges
    # two or more tiles share.  Tiles that meet only at a POINT are deliberately
    # not joined: a supertile you may substitute again has to be one lump of
    # plane, and two lumps pinched at a vertex are not.
    parent = list(range(len(tiles)))

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ids in owners.values():
        if len(ids) > 1:
            ra = _find(ids[0])
            for other in ids[1:]:
                rb = _find(other)
                if ra != rb:
                    parent[rb] = ra
    components = len({_find(i) for i in range(len(tiles))}) if tiles else 0
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
    # counted BEFORE the walk consumes adj: see the docstring
    pinch = sum(1 for v in adj.values() if len(v) > 1)
    loops = []
    broken = 0
    # Every iteration of the inner loop pops exactly one edge and never puts it
    # back, so the walk terminates in at most `boundary` steps whatever the
    # geometry.  That is a property of the multiset, not an assumption about the
    # patch -- and it is exactly the property spectre_patch_boundary() lost when
    # it collapsed the multiset to one successor per vertex.
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
        "boundary_pinch_vertices": pinch,
        "tile_components": components,
        "union_area": area,
        "sum_tile_areas": len(tiles) * SPECTRE_UNIT_AREA,
        "area_defect": area - len(tiles) * SPECTRE_UNIT_AREA,
    }


# The interior angle at each of Tile(1,1)'s fourteen vertices, in units of 30
# degrees, derived from the edge directions rather than transcribed.  Turning
# from edge direction d[i-1] onto d[i] turns by (d[i] - d[i-1]) and the interior
# angle of a counter-clockwise ring is 180 degrees minus that turn.
def _spectre_vertex_angles():
    d = SPECTRE_DIRS
    n = len(d)
    out = [((6 - (d[i] - d[i - 1])) % 12) or 12 for i in range(n)]
    if sum(out) != 6 * (n - 2):            # ring would be running clockwise
        out = [12 - a for a in out]
    assert sum(out) == 6 * (n - 2), "interior angles do not sum to (n-2)*180"
    assert sorted(set(out)) == [3, 4, 6, 8, 9], \
        "Tile(1,1) angles are not {90,120,180,240,270}: %r" % (sorted(set(out)),)
    assert out.count(6) == 1, "Tile(1,1) must have exactly one straight vertex"
    return tuple(out)


SPECTRE_VERTEX_ANGLES = _spectre_vertex_angles()


def spectre_vertex_census(levels, gamma=False):
    """Exact angle census: how much tile meets at each vertex of the patch?

    THE CHEAP STRONG ORACLE, and the one that scales.  The pairwise audit is
    O(tiles) pairs with a 14x14 edge sweep inside each; this is one pass over
    the tiles, exact integer arithmetic, and it catches the thing that actually
    goes wrong.

    Every edge of Tile(1,1) is a UNIT step in a direction that is a multiple of
    30 degrees, so every tile boundary is fourteen unit segments between points
    of Z[d] and two tiles can only meet edge-to-edge or corner-to-corner -- there
    are no T-junctions to reason about.  The interior angles are therefore whole
    multiples of 30 degrees and the total angle of tile meeting at any point is
    an integer.  Two facts follow, and neither has a tolerance in it:

        no lattice point may carry more than 360 degrees of tile
        a point carrying exactly 360 is interior; less is on the boundary

    A patch whose tiles overlap violates the first somewhere.  Run on the old
    broken level 3 this reports 55 vertices over 360 degrees and a worst vertex
    of 720 -- two full tiles stacked -- which is about as loud as a measurement
    gets.

    It is NOT a complete overlap test on its own: two unit segments can cross at
    a point that is not a lattice point, which this cannot see.  That is what
    spectre_patch_audit()'s edge-crossing sweep is for.  The two together are
    what the tests use.
    """
    return vertex_census(_spectre_handed(levels)[1 if gamma else 0], levels)


def vertex_census(tiles, levels=None):
    """spectre_vertex_census() on an explicit tile list.  See its docstring.

    Split out so the census can be pointed at a deliberately broken tile list --
    which is the only way to know it would notice.
    """
    dir_of = {z_unit(k): k for k in range(12)}
    ang = defaultdict(int)
    edge = defaultdict(int)
    want = 6 * (len(SPECTRE) - 2)          # (n-2)*180 degrees, in 30-degree units
    for t in tiles:
        n = len(t)
        d = []
        for i in range(n):
            v = z_sub(t[(i + 1) % n], t[i])
            k = dir_of.get(v)
            if k is None:
                raise AssertionError(
                    "tile edge %r is not a unit step at a multiple of 30 "
                    "degrees; the angle census does not apply" % (v,))
            d.append(k)
        a = [((6 - (d[i] - d[i - 1])) % 12) or 12 for i in range(n)]
        if sum(a) != want:                 # ring runs clockwise; flip it
            a = [12 - x for x in a]
            if sum(a) != want:
                raise AssertionError("interior angles of a tile do not close")
        for i in range(n):
            ang[t[i]] += a[i]
            p, q = t[i], t[(i + 1) % n]
            edge[(p, q) if p <= q else (q, p)] += 1
    over = [p for p, v in ang.items() if v > 12]
    return {
        "levels": levels,
        "n_tiles": len(tiles),
        "distinct_vertices": len(ang),
        "vertices_over_360": len(over),
        "worst_vertex_deg": (max(ang.values()) * 30) if ang else 0,
        "interior_vertices": sum(1 for v in ang.values() if v == 12),
        "edges_shared_by_3_or_more": sum(1 for v in edge.values() if v > 2),
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


_AUDIT_CACHE: dict[int, dict] = {}


def spectre_patch_audit(levels, tiles=None):
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

    WHAT IS NOT ASKED, and this is the point of having a separate audit:
    connectedness, a single boundary loop, and the absence of holes.  Those are
    SUPERTILE properties -- they say the patch is one chunk of plane you could
    substitute again.  A consumer that places tiles once and then discards most
    of them against a copper mask is indifferent to a void it was never going to
    fill.  They are reported either way, and `supertile_ok` is the flag that
    includes them.

    THE SUPERTILE CRITERION, AND THE HISTORY, BECAUSE ONE ROUND OF IT WAS WRONG.

    It began as hull_fill >= 0.75, calibrated on a lone tile (0.8146) and the
    9-tile cluster (0.8040).  That threshold does not survive a real spectre
    supertile, which is genuinely ragged and gets raggeder: the correct patches
    fill 0.8146, 0.8040, 0.7076, 0.6510, 0.6266, 0.6177 of their hulls at levels
    0..5, converging to about 0.61.  Kept, it would reject every correct patch
    from level 2 down.  So it had to go, and it is NOT coming back.

    It was replaced by "one boundary loop, no broken chains, no edge claimed by
    three or more tiles", with a note claiming that is what the old level 2
    actually failed.  THAT CLAIM WAS FALSE AND THE REPLACEMENT GATE PASSED THE
    KNOWN-BAD PATCH.  Measured, by rebuilding the rotation-only construction and
    putting its tiles through this very function (`tiles=`, added for exactly
    this): the old level-2 patch is 71 tiles in THREE edge-connected components
    ringing a void, and it scores overlapping_pairs 0, area_defect -6.8e-13,
    edges_shared_by_3_or_more 0, broken_chains 0 and boundary_loops 1.  It
    passed.  hull_fill 0.6405 was the only clause of the original gate that ever
    caught it, and dropping that clause dropped the gate.

    Why boundary_loops did not catch it: the three lumps TOUCH, at two vertices,
    and a boundary walk goes straight through a pinch.  One closed boundary
    curve, no hole, three lumps.  So the gate now measures the two things that
    do answer the question, both exact integer counts and neither a proxy:

        tile_components == 1            one lump, joined by shared EDGES
        boundary_pinch_vertices == 0    and not merely touching at points

    plus the loop and edge conditions it already had, which are the hole test
    and the overlap test respectively.  Against that gate the old level 2 fails
    on both new clauses (3 components, 2 pinches) and every correct level 0..5
    passes on all four (1 component, 0 pinches, 1 loop, 0 shared-by-3), for the
    Gamma supertile as well as the ordinary one.  Hull fill is still reported,
    because a sudden drop in it is still worth seeing; it is not gated on.

    Ungated deliberately: measuring a level is always allowed, and refusing to is
    how level 2 stayed unexamined.  Getting the TILES is what is gated, by
    spectre_tiles().

    `tiles` audits an EXPLICIT tile list rather than a level of this module's
    substitution, and bypasses the cache.  `levels` is then only used to say
    what the count should have been.
    """
    levels = int(levels)
    if tiles is not None:
        tiles = tuple(tuple(t) for t in tiles)
        return _spectre_patch_audit(levels, tiles)
    hit = _AUDIT_CACHE.get(levels)
    if hit is not None:
        return dict(hit)
    out = _spectre_patch_audit(levels, _spectre_handed(levels)[0])
    _AUDIT_CACHE[levels] = out
    return dict(out)


def _spectre_patch_audit(levels, tiles):
    """spectre_patch_audit() on an explicit tile list, uncached."""
    exact = [[_z_pt2(p) for p in t] for t in tiles]
    fl = [[z_xy(p) for p in t] for t in tiles]
    boxes = [bbox_of(r) for r in fl]
    n = len(tiles)
    # Candidate pairs from a uniform grid rather than the full n^2 sweep: a
    # 34649-tile patch is 600 million ordered pairs and the answer for all but a
    # few thousand of them is "their bounding boxes do not even touch".  The grid
    # cannot MISS a pair -- two overlapping bboxes share a point, that point is
    # in some cell, and both tiles are registered in every cell their bbox spans
    # -- so `pairs_tested` below is the same number the n^2 sweep would report.
    cell = 4.0
    grid = defaultdict(list)
    for i, b in enumerate(boxes):
        for gx in range(int(math.floor(b[0] / cell)),
                        int(math.floor(b[2] / cell)) + 1):
            for gy in range(int(math.floor(b[1] / cell)),
                            int(math.floor(b[3] / cell)) + 1):
                grid[(gx, gy)].append(i)
    cand = set()
    for bucket in grid.values():
        for a in range(len(bucket)):
            for b in range(a + 1, len(bucket)):
                cand.add((bucket[a], bucket[b]) if bucket[a] < bucket[b]
                         else (bucket[b], bucket[a]))
    tested = crossings = inside_hits = 0
    bad = set()
    for i, j in sorted(cand):
        bi, bj = boxes[i], boxes[j]
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
    fit = spectre_exact_fit(levels, tiles=tiles)
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
        "edges_shared_by_3_or_more": fit["edges_shared_by_3_or_more"],
        "boundary_loops": fit["boundary_loops"],
        "broken_chains": fit["broken_chains"],
        "boundary_pinch_vertices": fit["boundary_pinch_vertices"],
        "tile_components": fit["tile_components"],
        # reported, NOT gated -- see the docstring
        "hull_fill": fill_fraction(fl),
    }
    out["patch_ok"] = (n == want and not bad and not reflected
                       and abs(fit["area_defect"]) < 1e-9)
    # ONE LUMP (tile_components), NOT MERELY TOUCHING (boundary_pinch_vertices),
    # NO HOLE (boundary_loops, broken_chains), NO OVERLAP
    # (edges_shared_by_3_or_more).  The first two are the clauses that fail the
    # old rotation-only level 2, which the previous gate passed; see the
    # docstring for the measurement.
    out["supertile_ok"] = bool(out["patch_ok"]
                               and out["tile_components"] == 1
                               and out["boundary_pinch_vertices"] == 0
                               and out["boundary_loops"] == 1
                               and out["broken_chains"] == 0
                               and out["edges_shared_by_3_or_more"] == 0)
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

    `reason` says WHICH refusal this is, because the two are not the same
    failure and do not have the same fix:

      "span"   the patch's bounding box is smaller than the frame.
               `min_tile_mm` is spectre_span_tile_mm(); `needed_level` is the
               extrapolated level that would span at the requested tile_mm.
      "cover"  the bounding box is big enough but the BOUNDARY POLYGON does not
               contain the frame, so the frame takes in bays of bare board.
               `min_tile_mm` is spectre_cover_tile_mm(), which is much larger
               than the span number -- 3.086404 against 0.561439 on this repo's
               frame at level 5 -- and `needed_level` is None, because how deep
               a patch would have to be to COVER an arbitrary frame has not been
               established and this class will not invent it.

    A caller that just catches the class and reads `min_tile_mm` is correct
    either way; one that branches on the fix should branch on `reason`.
    """

    def __init__(self, message, frame_mm=None, patch_mm=None, tile_mm=None,
                 min_tile_mm=None, needed_level=None, levels=None,
                 reason="span"):
        super().__init__(message)
        self.frame_mm = frame_mm
        self.patch_mm = patch_mm
        self.tile_mm = tile_mm
        self.min_tile_mm = min_tile_mm
        self.needed_level = needed_level
        self.levels = levels
        self.reason = reason


def spectre_unit_mm(tile_mm):
    """mm per unit edge at the given equal-area tile size.  tile_mm / 2.862892."""
    return float(tile_mm) / math.sqrt(SPECTRE_UNIT_AREA)


_EXTENT_CACHE: dict[tuple, tuple] = {}
_HULL_CACHE: dict[int, tuple] = {}


def _spectre_hull(levels):
    """The patch's convex hull, as EXACT ring points.  Cached per level.

    Every extent question about a rotated patch is a question about its hull --
    the bbox of a rotated point set is the bbox of the rotated hull -- and a
    level-5 patch has 214662 distinct vertices against a hull of a few hundred.
    Rotating the hull instead of the patch is what keeps spectre_patch_extent()
    from costing six million ring multiplications per turn.

    The hull is SELECTED using floats and RETURNED as exact ring tuples, so
    every extent downstream is still computed by exact rotation.
    """
    levels = int(levels)
    hit = _HULL_CACHE.get(levels)
    if hit is not None:
        return hit
    seen = {}
    for t in spectre_tiles(levels):
        for p in t:
            if p not in seen:
                seen[p] = z_xy(p)
    back = {}
    for p, xy in seen.items():
        back.setdefault(xy, p)
    hull = convex_hull(list(back))
    _HULL_CACHE[levels] = tuple(back[xy] for xy in hull)
    return _HULL_CACHE[levels]


def spectre_patch_extent(levels=None, turn=0):
    """(w, h) of the patch's bounding box in UNIT EDGES, at turn*30 degrees.

    Multiply by spectre_unit_mm(tile_mm) for millimetres.  Measured, not
    derived: the bbox does NOT grow by SPECTRE_INFLATION, because the patch is
    not a scaled copy of itself as a SET -- level 1 -> 2 is 3.399 x 3.427 -- so
    any arithmetic that assumes a single growth factor here is wrong.
    """
    levels = SPECTRE_PATCH_LEVEL if levels is None else int(levels)
    key = (levels, int(turn) % 12)
    if key in _EXTENT_CACHE:
        return _EXTENT_CACHE[key]
    pts = [z_xy(z_rot(p, key[1])) for p in _spectre_hull(levels)]
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
    """The substitution level needed to span this frame.

    Levels 0..SPECTRE_PATCH_LEVEL are MEASURED -- the patch is built and its
    bbox taken.  Above that the extent is extrapolated at SPECTRE_INFLATION per
    level, which is now an extrapolation of a working system rather than of a
    hypothetical one, but is still an extrapolation and is still not a promise
    that the level has been audited.  Returns None if even max_level would not
    do it.
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


def _centred_frame_rect(ring, frame_w, frame_h, unit):
    """The frame, in unit edges, centred on `ring`'s bounding-box centre.

    One place, so the placement rule that spectre_fingerprint_placement() uses
    and the coverage question spectre_cover_level() answers cannot drift apart.
    They drifted once: the search loop asked about a centred rect and then, when
    no level answered yes, handed back SPECTRE_PATCH_LEVEL anyway.
    """
    cx = (min(p[0] for p in ring) + max(p[0] for p in ring)) / 2.0
    cy = (min(p[1] for p in ring) + max(p[1] for p in ring)) / 2.0
    hw = frame_w / unit / 2.0
    hh = frame_h / unit / 2.0
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def spectre_cover_level(frame_w, frame_h, tile_mm, turn=0, max_level=None):
    """Shallowest level whose BOUNDARY POLYGON contains the centred frame.

    Returns None when no level up to `max_level` (default SPECTRE_PATCH_LEVEL)
    does.  None is a real answer and callers must handle it: it is NOT the same
    thing as SPECTRE_PATCH_LEVEL, and treating it as such is the exact bug this
    function was factored out to kill.  See spectre_fingerprint_placement().

    COVERS, not spans.  A patch whose bounding box contains the frame can still
    leave bays of bare board inside it, because a spectre supertile's outer
    boundary is ragged -- about 0.62 of its convex hull by level 4.  Measured on
    this repo's 150.4 x 99.6 mm frame at tile_mm 3.0, turn 0: the level-4 patch
    spans the frame and leaves 2295.021 mm2 uncovered in two bays; the level-5
    patch spans it and still leaves 3.687 mm2 in two notches at the frame's
    edge.  So this returns None there, and spectre_fingerprint_placement()
    refuses rather than returning 5 with coverage unverified.

    The bbox test is kept as a cheap precondition only -- covering implies
    spanning, so a level that does not span cannot cover and need not have its
    boundary walked.
    """
    hi = SPECTRE_PATCH_LEVEL if max_level is None else int(max_level)
    unit = spectre_unit_mm(tile_mm)
    turn = int(turn) % 12
    for lv in range(0, hi + 1):
        ew, eh = spectre_patch_extent(lv, turn)
        if ew * unit < frame_w - 1e-9 or eh * unit < frame_h - 1e-9:
            continue
        ring = spectre_patch_boundary(lv, turn)
        if _ring_contains_rect(ring, _centred_frame_rect(ring, frame_w,
                                                         frame_h, unit)):
            return lv
    return None


def spectre_cover_tile_mm(frame_w, frame_h, levels=None, turn=0, rtol=1e-9):
    """The SMALLEST tile_mm at which `levels` COVERS the centred frame.

    The coverage counterpart of spectre_span_tile_mm(), and the number a
    coverage refusal has to carry if it is to be actionable: on this repo's
    150.4 x 99.6 mm frame at level 5, turn 0, spanning needs 3.086404 mm.  Both
    numbers are needed because they are far apart -- the same frame and level
    span at 0.561439 mm, 5.5x smaller -- and quoting the span number for a
    coverage failure would send the caller to a tile size that still fails.

    Returns None if no tile size covers, which happens when the frame's centre
    is not inside the patch at all.  Bisected, not derived: the rect shrinks
    about a fixed centre as tile_mm grows, and a concentric sub-rectangle of a
    contained rectangle is contained, so containment is monotone in tile_mm and
    bisection is exact to `rtol`.
    """
    turn = int(turn) % 12
    ring = spectre_patch_boundary(SPECTRE_PATCH_LEVEL if levels is None
                                  else int(levels), turn)
    frame_w = float(frame_w)
    frame_h = float(frame_h)

    def covered(tile):
        unit = spectre_unit_mm(tile)
        return _ring_contains_rect(
            ring, _centred_frame_rect(ring, frame_w, frame_h, unit))

    lo = spectre_span_tile_mm(frame_w, frame_h, levels, turn)
    hi = lo
    for _ in range(64):                 # a shrinking rect must eventually fit,
        if covered(hi):                 # unless the centre itself is outside
            break
        hi *= 2.0
    else:
        return None
    for _ in range(200):
        if hi - lo <= rtol * hi:
            break
        mid = (lo + hi) / 2.0
        if covered(mid):
            hi = mid
        else:
            lo = mid
    return hi


def spectre_fingerprint(frame, tile_mm, seed=0, levels=None):
    """The board-first patch, centred on `frame`, or a refusal.

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

    WITH `levels=None` IT NOW CHOOSES THE LEVEL, and that is a change worth
    stating.  It used to mean "level 2, 71 tiles, take it or leave it", because
    71 tiles was every tile the module had; a 150 x 100 mm board then forced
    tile_mm >= 11.674 and offered six surviving tiles, which is why the cell-grid
    mode had to exist.  It now means "the shallowest level that COVERS this
    frame at this tile size and rotation", measured, searched no deeper than
    SPECTRE_PATCH_LEVEL -- AND IT RAISES IF NO LEVEL COVERS.  It does not cap:
    capping is what it used to do, and returning the deepest level because the
    search fell through is indistinguishable from returning it because the
    search succeeded.  Pass an explicit `levels` to pin it.

    COVERS, not "whose bounding box is big enough".  A spectre supertile has a
    ragged outer boundary -- it fills about 0.63 of its convex hull -- so a
    patch whose bbox contains the frame can still leave bays of bare board
    inside it.  Measured on this repo's 150.4 x 99.6 mm frame at tile_mm 3.0,
    rot 0, against shapely: the level-4 patch bbox-covers it and leaves
    2295.021 mm2 outside the patch in two components of 1615.385 and
    679.636 mm2, and the level-5 patch bbox-covers it and still leaves
    3.687 mm2 in two.  The whitespace the pipeline expects is the one
    tile-width strip the whole-tile rule leaves at the perimeter, not that.  So
    the test is containment in the patch's boundary polygon; see
    spectre_patch_boundary().  At that tile size and rotation NOTHING covers,
    and this raises -- see spectre_fingerprint_placement() for what to do
    about it.

    Raises SpectreCoverageError -- loudly, with numbers -- if even
    SPECTRE_PATCH_LEVEL cannot cover the frame.  It does not scale the tile down
    and it does not repeat the patch across the board; a repeated patch is
    periodic at the patch pitch, which is the one property the spectre was
    chosen to avoid.

    The placement rule itself is spectre_fingerprint_placement(), which this
    calls; the rings it returns are cropped to the frame's neighbourhood, so the
    rule is asserted there rather than inferred from the output's bounding box.
    """
    levels, ox, oy = spectre_fingerprint_placement(frame, tile_mm, seed, levels)
    x0, y0, x1, y1 = (float(v) for v in frame)
    unit = spectre_unit_mm(tile_mm)
    turn = int(seed) % 12
    pts = _rotated_patch(levels, turn)[0]
    # Offer only the tiles that reach the frame.  Covering a 150 x 100 mm board
    # takes a level-5 patch of 34649 tiles once coverage is measured properly,
    # and all but a couple of thousand of those are metres off the board.
    # Dropping a tile whose bounding box does not touch the frame CANNOT change
    # what generate() returns -- its whole-tile filter would drop it anyway --
    # so this is the same field, minus the part of it nobody can see.  It also
    # makes the ledger's "offered" number mean something: offered minus placed
    # is now the board-edge overhang rather than the size of the patch.
    out = []
    for t in pts:
        r = [(p[0] * unit + ox, p[1] * unit + oy) for p in t]
        bx0, by0, bx1, by1 = bbox_of(r)
        if bx1 < x0 - 1e-9 or bx0 > x1 + 1e-9 or \
           by1 < y0 - 1e-9 or by0 > y1 + 1e-9:
            continue
        out.append(r)
    out.sort(key=lambda r: (round(centroid(r)[1], 6), round(centroid(r)[0], 6)))
    return [r + [r[0]] for r in out]


def spectre_fingerprint_placement(frame, tile_mm, seed=0, levels=None):
    """(levels, ox, oy) -- the whole placement rule, in one inspectable place.

    `ox, oy` are the mm offsets that take the level-`levels` patch, rotated by
    seed%12 turns and scaled by spectre_unit_mm(tile_mm), onto the board.  The
    rule is: pick the shallowest level whose boundary polygon contains the
    frame, then CENTRE that patch on the frame.  Centring is deterministic and
    is the only placement that does not privilege one corner of the board.

    IF NO LEVEL COVERS, IT RAISES.  It used to clamp: `levels` was seeded with
    SPECTRE_PATCH_LEVEL before the search, so "the search found the deepest
    level" and "the search found nothing" returned the same value and the caller
    could not tell them apart.  The only guard left standing in the second case
    was the bounding-box span test below, which is exactly the bbox-for-coverage
    substitution this rule exists to reject.  It is not a corner case: at
    tile_mm 3.0 and turn 0 NO level covers this repo's 150.4 x 99.6 mm frame --
    level 5 leaves 3.687 mm2 in two notches at the frame edge -- and the old
    code returned 5 for it.  The sibling _spectre_levels_for() has always raised
    on the same input; the two agree now.

    COVERAGE IS ROTATION-DEPENDENT, which is worth knowing before reading a
    refusal as a dead end.  Measured on that frame at tile_mm 3.0: level 5
    covers at 8 of the 12 turns and fails at turns 0, 3, 6 and 9.  So a refusal
    at seed 0 does not mean the tile size is wrong.

    Separated from spectre_fingerprint() because that function crops its output
    to the frame, so the centring is no longer visible in the returned rings'
    bounding box -- and a placement rule nothing can assert is a placement rule
    that will drift.
    """
    x0, y0, x1, y1 = (float(v) for v in frame)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("empty frame %r" % (frame,))
    if tile_mm <= 0:
        raise ValueError("tile_mm must be positive, got %r" % (tile_mm,))
    fw, fh = x1 - x0, y1 - y0
    turn = int(seed) % 12
    unit = spectre_unit_mm(tile_mm)

    if levels is None:
        found = spectre_cover_level(fw, fh, tile_mm, turn)
        if found is None:
            # NO LEVEL COVERS, AND THAT IS NOT LEVEL SPECTRE_PATCH_LEVEL.  This
            # used to seed `levels = SPECTRE_PATCH_LEVEL` before the loop, so a
            # search that found nothing was indistinguishable from a search that
            # found the deepest level, and the caller got that level with its
            # coverage never established.  The only surviving guard below is a
            # bounding-box span test -- the precise bbox-for-coverage confusion
            # this rule exists to reject.  Reproduced: a frame cut to level 5's
            # own extent returned levels=5 with _ring_contains_rect False.
            # _spectre_levels_for() raises on the same input; so does this now.
            ew, eh = spectre_patch_extent(SPECTRE_PATCH_LEVEL, turn)
            pw, ph = ew * unit, eh * unit
            if pw >= fw - 1e-9 and ph >= fh - 1e-9:
                need = spectre_cover_tile_mm(fw, fh, SPECTRE_PATCH_LEVEL, turn)
                raise SpectreCoverageError(
                    "spectre level %d SPANS the %.3f x %.3f mm frame at tile_mm "
                    "%.3f -- its bounding box is %.3f x %.3f mm -- but its "
                    "BOUNDARY POLYGON does not contain the frame, and no "
                    "shallower level does either. Coverage is the test, not the "
                    "bounding box: a supertile fills about 0.62 of its convex "
                    "hull by level 4, so a frame inside the bbox can still take "
                    "in bays of bare board, and whole-tile filtering would then "
                    "hand back a field with a hole in it. This is a REFUSAL, "
                    "not a clamp: the previous code returned level %d here with "
                    "its coverage unverified. Your options, in full: raise "
                    "--tile-mm to at least %s mm, the smallest tile at which "
                    "level %d covers this frame at rotation %d; change the seed "
                    "-- coverage is rotation-dependent and seed %% 12 picks the "
                    "rotation; audit a deeper level and raise "
                    "SPECTRE_AUDITED_LEVEL; or pass levels= explicitly and own "
                    "the bays yourself. What is NOT on offer: repeating the "
                    "patch, which would make the field periodic at a %.1f mm "
                    "pitch and throw away the only reason to use a spectre."
                    % (SPECTRE_PATCH_LEVEL, fw, fh, tile_mm, pw, ph,
                       SPECTRE_PATCH_LEVEL,
                       "?" if need is None else "%.6f" % need,
                       SPECTRE_PATCH_LEVEL, turn, max(pw, ph)),
                    frame_mm=(fw, fh), patch_mm=(pw, ph),
                    tile_mm=float(tile_mm), min_tile_mm=need,
                    needed_level=None, levels=SPECTRE_PATCH_LEVEL,
                    reason="cover")
            # it does not even span: fall through to the span refusal below,
            # which already carries the right numbers for that case.
            levels = SPECTRE_PATCH_LEVEL
        else:
            levels = found
    else:
        levels = int(levels)

    ew, eh = spectre_patch_extent(levels, turn)
    pw, ph = ew * unit, eh * unit
    if pw < fw - 1e-9 or ph < fh - 1e-9:
        need = spectre_span_tile_mm(fw, fh, levels, turn)
        lv = spectre_span_level(fw, fh, tile_mm, turn)
        raise SpectreCoverageError(
            "spectre level %d is %.3f x %.3f mm at tile_mm %.3f and cannot span "
            "the %.3f x %.3f mm board frame. The deepest AUDITED patch is level "
            "%d (%d tiles). Your options, in full: raise --tile-mm to at least "
            "%.3f mm, which is the smallest tile at which this patch spans this "
            "board at rotation %d; audit a deeper level and raise "
            "SPECTRE_AUDITED_LEVEL, which is now a matter of compute rather "
            "than of mathematics; or use a lattice kind. What is NOT on offer: "
            "repeating the patch across the board, which would make the field "
            "periodic at a %.1f mm pitch and throw away the only reason to use "
            "a spectre, and silently shrinking to fit, which would answer a "
            "question you did not ask. Spanning at tile_mm %.3f would need "
            "level %s."
            % (levels, pw, ph, tile_mm, fw, fh, SPECTRE_PATCH_LEVEL,
               spectre_patch_size(SPECTRE_PATCH_LEVEL), need, turn,
               max(pw, ph), tile_mm, "?" if lv is None else str(lv)),
            frame_mm=(fw, fh), patch_mm=(pw, ph), tile_mm=float(tile_mm),
            min_tile_mm=need, needed_level=lv, levels=levels)
    _pts, pminx, pminy, pmaxx, pmaxy = _rotated_patch(levels, turn)
    # centre the patch on the frame: deterministic, and the only placement that
    # does not privilege one corner of the board over another.
    ox = (x0 + x1) / 2.0 - (pminx + pmaxx) / 2.0 * unit
    oy = (y0 + y1) / 2.0 - (pminy + pmaxy) / 2.0 * unit
    return levels, ox, oy


@register("spectre-fingerprint",
          size="equal-area size; edge = tile_mm/2.8629", edges=14,
          note="BOARD-FIRST. ONE spectre patch centred on the board frame, at "
               "the shallowest substitution level whose BOUNDARY POLYGON "
               "covers it -- covers, not spans -- seed choosing the rotation "
               "only. Refuses loudly rather than repeating, rescaling or "
               "handing back a level whose coverage it never checked. The bbox "
               "handed to generate() must be the BOARD, not a permitted region")
def _spectre_fingerprint(bbox, tile_mm, seed):
    for ring in spectre_fingerprint(bbox, tile_mm, seed):
        yield ring


# ---------------------------------------------------------------------------
# the cell grid -- the fingerprint that is actually sensitive to the board
# ---------------------------------------------------------------------------
# WHY THIS EXISTED, and read the last paragraph before reaching for it.
#
# It was written when 71 tiles was every tile the module had.  spectre_fingerprint
# had to SPAN the board with those 71, which on a 150 x 100 mm board forced
# tile_mm >= 11.674 and a tile 16.7 mm across.  At that size only six tiles
# survived the F.Cu copper mask and four survived B.Cu, and a six-element field
# cannot distinguish two boards: measured over a full-board sweep, moving all 156
# footprints by 2.0 mm changed the surviving set in 2 cases out of 156, both of
# them NETLESS mechanical hardware, and moving J3 by 12 mm changed the permitted
# area by 98.39 mm2 with a bit-identical tile set.  The failure was arithmetic,
# not conceptual: the field was too small to resolve anything.
#
# The cell grid keeps the anchoring and spends the tile budget properly.  The
# frame is cut into square cells of a fixed pitch, each cell gets its own
# level-SPECTRE_CELL_LEVEL patch at its own rotation, and the tile size is then
# free -- at tile_mm 3.0 the same board is offered hundreds of tiles instead of
# 71.
#
# WHAT CHANGED UNDER IT.  The substitution now runs to arbitrary depth, so the
# one-patch mode can offer a 150 x 100 mm board 34649 tiles at tile_mm 3.0
# without repeating anything, which is the resolution this mode was invented to
# buy and it buys it WITHOUT giving up long-range aperiodicity.  This mode is
# kept because its contract, its constants and its tests are all still true, and
# because a per-cell field is a different (coarser, scrambled) fingerprint that
# somebody may still want -- but it is no longer the answer to "the one-patch
# field is too small".  Prefer spectre-fingerprint.
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


# The level this mode puts in a cell.  PINNED, and not to SPECTRE_PATCH_LEVEL:
# every constant and proof below is about the size of ONE cell's patch, and a
# cell that grew whenever the audited depth grew would silently rescale every
# board this mode has ever produced.  71 tiles per cell is the design.
SPECTRE_CELL_LEVEL = 2


def spectre_cell_units(levels=None):
    """Side of the smallest SQUARE cell that holds the patch at EVERY rotation.

    In UNIT EDGES.  Measured over all twelve 30-degree turns and maximised, so
    the answer does not depend on which turn a cell happens to draw -- which is
    the whole point: a per-cell rotation may only be free if the cell is big
    enough for the worst one.

    At SPECTRE_CELL_LEVEL the twelve turns give six distinct bboxes and the
    largest single dimension of any of them has a closed form in Z[sqrt 3] --
    exact because every vertex is a point of Z[d] and both coordinates therefore
    lie in (1/2)Z[sqrt 3], so there is no rounding in it.  The value is asserted
    against that closed form at import; see SPECTRE_CELL_SIDE_CLOSED_FORM.
    """
    levels = SPECTRE_CELL_LEVEL if levels is None else int(levels)
    return max(max(spectre_patch_extent(levels, k)) for k in range(12))


# The closed form of the cell side, as (A, B) meaning (A + B*sqrt 3)/2 unit
# edges.  It is (27, 27), i.e. 27*(1 + sqrt 3)/2 = 36.882685902179844.
#
# IT CHANGED WITH THE SUBSTITUTION AND THAT IS NOT A ROUNDING DRIFT.  The old
# value was 15 + 13*sqrt(3) = 37.5167, and it was an honest measurement of the
# old level-2 patch -- which was three disconnected lumps sprawling around a
# void, and so wider across than a correct 71-tile supertile is.  The correct
# level-2 patch is one compact lump, so its cell is smaller.  Any board
# previously generated with kind "spectre-cells" will NOT reproduce
# bit-for-bit; that is the price of the patch being right, and it is stated here
# rather than left to be discovered by a diff.
SPECTRE_CELL_SIDE_CLOSED_FORM = (27, 27)

# The cell in units of tile_mm: cell_mm = SPECTRE_CELL_PITCH * tile_mm.
#
# DO NOT ROUND THIS AND DO NOT COPY IT OUT OF A REPORT.  The disjointness proof
# below is TIGHT -- at four of the twelve turns the patch is exactly as tall as
# its cell -- so a pitch even a nanometre short makes the proof false rather than
# conservative.  The constant is derived at import from the measured extents and
# cross-checked against its closed form, so it cannot drift.
SPECTRE_CELL_PITCH = spectre_cell_units() / math.sqrt(SPECTRE_UNIT_AREA)

assert abs(spectre_cell_units()
           - (SPECTRE_CELL_SIDE_CLOSED_FORM[0]
              + SPECTRE_CELL_SIDE_CLOSED_FORM[1] * R3) / 2.0) < 1e-12, \
    ("level-%d cell side is not (%d + %d*sqrt 3)/2; re-derive before trusting it"
     % (SPECTRE_CELL_LEVEL, SPECTRE_CELL_SIDE_CLOSED_FORM[0],
        SPECTRE_CELL_SIDE_CLOSED_FORM[1]))


def spectre_cell_pitch_mm(tile_mm, levels=None):
    """Cell pitch in mm at this tile size.  SPECTRE_CELL_PITCH * tile_mm."""
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

      1. every tile of the level-SPECTRE_CELL_LEVEL patch has pairwise-disjoint
         interiors with every other tile of the same patch.  That is not assumed
         here, it is proved by spectre_patch_audit(2) under integer predicates in
         Z[sqrt 3]: 71 tiles, 209 candidate pairs, 0 overlapping pairs, 0 proper
         edge crossings, 0 strictly-interior vertices, area defect 1.1e-13.
      2. every tile of a rotated patch lies inside the patch's own bbox, and
         that bbox is at most spectre_cell_units() on a side at EVERY one of the
         twelve turns.  Centred in a cell of exactly that side, the whole patch
         therefore lies inside the closed cell rectangle.
      3. the cells are a square lattice, so two distinct cells meet at most in a
         shared boundary segment, which has empty interior.

    1 + 2 + 3 give pairwise-disjoint interiors for the whole field.  Note the
    bound in (2) is TIGHT, not slack: at turns 2, 5, 8 and 11 the patch is
    exactly as tall (or wide) as the cell, so its extreme vertices touch the cell
    edge and can touch the neighbouring cell's patch.  Touching is not
    overlapping -- interiors stay disjoint -- but it does mean a cell pitch even
    a nanometre smaller than spectre_cell_units() breaks the proof.

    Determinism: the only inputs are `frame`, `tile_mm`, `seed` and `levels`.
    No RNG, no clock, no set or dict iteration order, and the per-cell rotation
    comes from hashlib rather than hash().  Two processes with different
    PYTHONHASHSEED produce the identical list.
    """
    levels = SPECTRE_CELL_LEVEL if levels is None else int(levels)
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
        SPECTRE_CELL_LEVEL if levels is None else int(levels))
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
               "12.88302*tile_mm square grid anchored at the board frame, each "
               "cell rotated by a hashlib-derived turn. Disjoint by "
               "construction. Aperiodic inside a cell, NOT across cells -- "
               "prefer spectre-fingerprint, which no longer needs the trade. "
               "The bbox handed to generate() must be the BOARD, not a "
               "permitted region")
def _spectre_cells(bbox, tile_mm, seed):
    for ring in spectre_cell_grid(bbox, tile_mm, seed):
        yield ring


_BOUNDARY_CACHE: dict[tuple, tuple] = {}


def spectre_patch_boundary(levels, turn=0, tiles=None):
    """The patch's outer boundary as one closed float ring, in unit edges.

    There is exactly one -- spectre_patch_audit() proves tile_components == 1,
    boundary_pinch_vertices == 0, boundary_loops == 1 and broken_chains == 0 at
    every audited level -- so this is well defined.  It is built by cancelling
    every directed tile edge against its reverse, which is exact (the points are
    ring tuples, compared as integers) before the final conversion to floats.

    EVERY WAY IT CAN FAIL NOW RAISES, AND THE HANG IS GONE.  This used to store
    ONE successor per vertex, so at a pinch -- a vertex with two outgoing
    boundary edges, which is what two lumps touching at a point looks like --
    the second edge silently overwrote the first, and the walk could then cycle
    forever without ever reaching `start`.  The "more than one boundary loop"
    check below it was unreachable code.  Measured on the rotation-only level-2
    patch: 280 boundary edges, 2 vertices with two outgoing edges, 278 stored,
    and the walk still running after 200000 steps.

    Three things fix it and all three are needed.  The successors are kept as a
    MULTISET, so no edge is dropped.  Pinches are counted and refused up front,
    because a pinched boundary has no well-defined single ring whatever the walk
    does.  And the walk carries a hard bound of one step per boundary edge, so
    it cannot outlive the data even if some future edge set defeats both checks.

    `tiles` walks an explicit tile list instead of this module's level-`levels`
    patch; the result is not cached in that case.
    """
    key = (int(levels), int(turn) % 12)
    explicit = tiles is not None
    if not explicit:
        hit = _BOUNDARY_CACHE.get(key)
        if hit is not None:
            return hit
        tiles = spectre_tiles(key[0])
    directed = defaultdict(int)
    for t in tiles:
        n = len(t)
        for i in range(n):
            directed[(t[i], t[(i + 1) % n])] += 1
    for (a, b) in list(directed):
        m = min(directed.get((a, b), 0), directed.get((b, a), 0))
        if m:
            directed[(a, b)] -= m
            directed[(b, a)] -= m
    succ = defaultdict(list)
    for (a, b), m in directed.items():
        for _ in range(m):
            succ[a].append(b)
    n_edges = sum(len(v) for v in succ.values())
    if not n_edges:
        if not explicit:
            _BOUNDARY_CACHE[key] = ()
        return ()
    pinched = sorted(v for v, s in succ.items() if len(s) > 1)
    if pinched:
        raise AssertionError(
            "spectre level %d has %d boundary vertices with more than one "
            "outgoing boundary edge out of %d boundary edges, so its boundary "
            "is PINCHED and there is no single outer ring to return.  That is "
            "what lumps meeting at a point look like, and it is the case in "
            "which a boundary walk splices separate loops into one -- see "
            "spectre_patch_audit(), which counts it as "
            "boundary_pinch_vertices.  First pinch at %r."
            % (key[0], len(pinched), n_edges, z_xy(pinched[0])))
    adj = {a: s[0] for a, s in succ.items()}
    start = next(iter(adj))
    ring = [start]
    cur = adj[start]
    # hard bound: one step per boundary edge.  The walk consumes no edges, so
    # nothing but the bound stops it if the successor map ever cycles.
    steps = 1
    while cur != start:
        ring.append(cur)
        nxt = adj.get(cur)
        if nxt is None:
            raise AssertionError(
                "spectre level %d has a broken boundary chain: the walk reached "
                "%r, which has no outgoing boundary edge, after %d of %d edges"
                % (key[0], z_xy(cur), steps, n_edges))
        cur = nxt
        steps += 1
        if steps > n_edges:
            raise AssertionError(
                "spectre level %d: the boundary walk did not close in %d steps, "
                "one per boundary edge, so the successor map contains a cycle "
                "that does not pass through the start vertex.  The patch is not "
                "one connected simply connected region"
                % (key[0], n_edges))
    if len(ring) != n_edges:
        raise AssertionError(
            "spectre level %d has more than one boundary loop: the walk closed "
            "after %d of %d boundary edges.  The patch is not one connected "
            "simply connected region" % (key[0], len(ring), n_edges))
    out = tuple(z_xy(z_rot(p, key[1])) for p in ring)
    if not explicit:
        _BOUNDARY_CACHE[key] = out
    return out


def _ring_contains_rect(ring, rect):
    """Is the closed rectangle entirely inside the simple polygon `ring`?

    A rectangle is convex, so it lies inside a simple polygon exactly when no
    edge of the polygon meets the rectangle's interior AND one point of the
    rectangle is inside.  "No edge meets the interior" is in turn: no polygon
    vertex strictly inside, and no polygon edge properly crossing a side.
    """
    rx0, ry0, rx1, ry1 = rect
    corners = [(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)]
    for p in corners:
        if not _strictly_inside(p, list(ring)):
            return False
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if rx0 - 1e-9 <= a[0] <= rx1 + 1e-9 and ry0 - 1e-9 <= a[1] <= ry1 + 1e-9:
            return False
        for k in range(4):
            if _properly_crosses(a, b, corners[k], corners[(k + 1) % 4]):
                return False
    return True


# ---------------------------------------------------------------------------
# filling a REGION -- whole tiles, all the way to the perimeter
# ---------------------------------------------------------------------------
# WHAT THIS ADDS THAT spectre_fingerprint() DID NOT.  The fingerprint takes a
# RECTANGLE and asks "which level's boundary polygon contains it".  A card is
# not a rectangle: the alpha coupon is a hexagon whose corners stick 7.3 mm
# past its own flats, and asking the patch to contain the hexagon's BOUNDING
# BOX makes the deflation go a level deeper than the card needs -- and a level
# is a factor of 7.9 in tiles.  So the region-filling entry point takes the
# outline itself, in one piece:
#
#     fill = spectre_region_fill(region, tile_mm)      # region = ring or rect
#     fill["tiles"]                                    # closed rings, mm
#     fill["offered"], fill["dropped_partial"], fill["coverage"]
#
# The three-step pipeline the board owner set out, with step 1 being the part
# that did not exist:
#
#   1. deflate until the patch COVERS the region  -- spectre_region_placement()
#   2. keep only the tiles that lie WHOLLY inside it, never clip -- the
#      whole-tile filter below, which is the same rule generate() applies to a
#      bbox, generalised from a rectangle to a polygon
#   3. drop every tile that meets a keepout                -- `keepouts`/`reject`
#
# COVERAGE IS REPORTED, NOT ASSUMED.  Every spectre tile has area exactly
# tile_mm**2 by construction (that is what "equal-area size" means here), so
# coverage is kept * tile_mm**2 / region_area -- but the area is measured from
# the emitted rings anyway and the two are cross-checked, because a coverage
# number computed from the count alone cannot notice a malformed tile.


def _as_region(region):
    """(ring, bbox, area) from either a rect 4-tuple or a closed/open ring.

    A rect is accepted because most callers still have one, and because the
    rectangle case has to keep behaving exactly as it did.  Anything else is
    read as a polygon: a list of (x, y), closed or not, either winding.
    """
    if (len(region) == 4 and all(isinstance(v, (int, float)) for v in region)):
        x0, y0, x1, y1 = (float(v) for v in region)
        if x1 <= x0 or y1 <= y0:
            raise ValueError("empty region rect %r" % (region,))
        ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:
        ring = _open([(float(p[0]), float(p[1])) for p in region])
        if len(ring) < 3:
            raise ValueError("a region needs at least 3 points, got %d"
                             % len(ring))
    if signed_area(ring) < 0:
        ring = ring[::-1]
    return ring, bbox_of(ring), abs(signed_area(ring))


def _point_in_ring(pt, ring, tol=1e-9):
    """1 strictly inside, 0 on the boundary, -1 outside.

    Same crossing rule as _strictly_inside(), but it reports the boundary as
    its own answer instead of folding it into "outside".  The whole-tile filter
    needs that: a tile edge that lies exactly along the region edge is a tile
    that fits, and calling it a partial would throw away a legal tile.
    """
    x, y = pt
    n = len(ring)
    inside = False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if abs(_cross((x1, y1), (x2, y2), (x, y))) < tol and \
           min(x1, x2) - tol <= x <= max(x1, x2) + tol and \
           min(y1, y2) - tol <= y <= max(y1, y2) + tol:
            return 0
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return 1 if inside else -1


def _ring_contains_ring(outer, inner, ibox=None):
    """Is the simple polygon `inner` entirely inside the simple polygon `outer`?

    The rectangle version above is only sound because a rectangle is convex.
    For two general simple polygons the test is the classic one: no vertex of
    `inner` outside `outer`, no vertex of `outer` strictly inside `inner`, and
    no pair of edges properly crossing.  Touching is allowed throughout -- a
    tile that shares an edge with the card outline is inside the card.
    """
    if ibox is None:
        ibox = bbox_of(inner)
    ix0, iy0, ix1, iy1 = ibox
    for p in inner:
        if _point_in_ring(p, outer) < 0:
            return False
    n = len(outer)
    m = len(inner)
    for i in range(n):
        a, b = outer[i], outer[(i + 1) % n]
        # the overwhelming majority of a supertile boundary is nowhere near the
        # region; reject those edges on the box before touching them.
        if max(a[0], b[0]) < ix0 - 1e-9 or min(a[0], b[0]) > ix1 + 1e-9 or \
           max(a[1], b[1]) < iy0 - 1e-9 or min(a[1], b[1]) > iy1 + 1e-9:
            continue
        if ix0 - 1e-9 <= a[0] <= ix1 + 1e-9 and iy0 - 1e-9 <= a[1] <= iy1 + 1e-9 \
           and _point_in_ring(a, inner) > 0:
            return False
        for j in range(m):
            if _properly_crosses(a, b, inner[j], inner[(j + 1) % m]):
                return False
    return True


def _rings_meet(a, b, abox=None, bbox_b=None):
    """Do the two simple polygons share interior area?  Touching does not count."""
    ax0, ay0, ax1, ay1 = bbox_of(a) if abox is None else abox
    bx0, by0, bx1, by1 = bbox_of(b) if bbox_b is None else bbox_b
    if ax1 < bx0 - 1e-9 or bx1 < ax0 - 1e-9 or \
       ay1 < by0 - 1e-9 or by1 < ay0 - 1e-9:
        return False
    return not _disjoint(a, b)


def _region_kept(pts, unit, ox, oy, ring, rbox):
    """How many whole tiles this offset lands inside the region."""
    rx0, ry0, rx1, ry1 = rbox
    n = 0
    for t in pts:
        r = [(p[0] * unit + ox, p[1] * unit + oy) for p in t]
        b = bbox_of(r)
        if b[2] < rx0 - 1e-9 or b[0] > rx1 + 1e-9 or \
           b[3] < ry0 - 1e-9 or b[1] > ry1 + 1e-9:
            continue
        if _ring_contains_ring(ring, r, b):
            n += 1
    return n


def _region_best_offset(lv, turn, unit, ox, oy, bnd, ring, rbox, tile_mm,
                        search):
    """The offset near (ox, oy) that keeps the MOST whole tiles.

    WHY THIS IS OPTIONAL AND NOT THE DEFAULT.  Where the patch sits under the
    outline is a free parameter -- at 15 mm a 94 mm card is a speck inside a
    level-3 patch -- and it decides how many tiles the perimeter cuts.
    Measured on the alpha coupon over 12 rotations and a 15x15 offset grid:
    15 mm 19..21 whole tiles centred against 24 at the best offset, 9 mm 69..74
    against 75, 6 mm 171..175 against 179, 3 mm 757..765 against 770.  So it is
    worth about a fifth of the field at 15 mm and about one percent at 3 mm.

    It is NOT the default because the default has to be a rule you can restate
    in one sentence -- centre it -- so that the field is a function of (region,
    tile_mm, seed) that anyone can reproduce without running this search.  Ask
    for it explicitly, with place="most-tiles", and know that it costs a full
    whole-tile scan per candidate offset.

    Ties break toward the centred offset, so the answer is deterministic.
    """
    step = float(tile_mm) * 0.7
    pts = _rotated_patch(lv, turn)[0]
    best = None
    for i in range(-search, search + 1):
        for j in range(-search, search + 1):
            dx, dy = ox + i * step, oy + j * step
            moved = [(p[0] * unit + dx, p[1] * unit + dy) for p in bnd]
            if not _ring_contains_ring(moved, ring, rbox):
                continue
            k = _region_kept(pts, unit, dx, dy, ring, rbox)
            key = (-k, i * i + j * j, i, j)
            if best is None or key < best[0]:
                best = (key, dx, dy)
    if best is None:
        return lv, ox, oy
    return lv, best[1], best[2]


def spectre_region_placement(region, tile_mm, seed=0, levels=None,
                             place="cover", search=4):
    """(levels, ox, oy) -- the deflation depth and offset that COVER `region`.

    The rule, and it is the fingerprint's rule generalised from a rectangle to
    a polygon: take the shallowest audited level whose OUTER BOUNDARY POLYGON
    contains the region once centred on it, and hand back the mm offset that
    puts it there.  `seed` picks one of the twelve 30-degree rotations and does
    nothing else, so a face's field is a function of (region, tile_mm, seed).

    THE BOUNDARY, NOT THE BOUNDING BOX.  A supertile is ragged -- it fills
    0.71 of its hull at level 2 and 0.62 by level 4 -- so a region inside the
    patch's bbox can still contain a bay of bare plane several centimetres
    across.  Measured on this very board before the test was fixed; see
    _spectre_levels_for().

    If centring does not contain the region the patch is NUDGED before the
    depth is increased, over a deterministic ladder of offsets ordered by
    distance from centred.  A level costs a factor of 7.9 in tiles; a two
    millimetre nudge costs nothing, and the ladder is a fixed function of the
    region and the level, so the field is still reproducible.

    `place` is "cover" (the rule above) or "most-tiles", which keeps the depth
    the rule chose and then searches nearby offsets for the one that loses the
    fewest tiles to the perimeter; see _region_best_offset() for what that buys
    and what it costs.

    Raises SpectreCoverageError, with numbers, if no audited level covers it.
    """
    if place not in ("cover", "most-tiles"):
        raise ValueError("place must be 'cover' or 'most-tiles', got %r"
                         % (place,))
    ring, (rx0, ry0, rx1, ry1), _area = _as_region(region)
    if tile_mm <= 0:
        raise ValueError("tile_mm must be positive, got %r" % (tile_mm,))
    turn = int(seed) % 12
    unit = spectre_unit_mm(tile_mm)
    rw, rh = rx1 - rx0, ry1 - ry0
    rcx, rcy = (rx0 + rx1) / 2.0, (ry0 + ry1) / 2.0
    lo = 1 if levels is None else int(levels)
    hi = SPECTRE_AUDITED_LEVEL if levels is None else int(levels)
    for lv in range(lo, hi + 1):
        b = spectre_patch_boundary(lv, turn)
        bx0 = min(p[0] for p in b) * unit
        by0 = min(p[1] for p in b) * unit
        bx1 = max(p[0] for p in b) * unit
        by1 = max(p[1] for p in b) * unit
        if bx1 - bx0 < rw - 1e-9 or by1 - by0 < rh - 1e-9:
            continue                      # cannot even reach across the region
        sx = ((bx1 - bx0) - rw) / 2.0     # slack on each side, mm
        sy = ((by1 - by0) - rh) / 2.0
        cands = []
        for i in range(-2, 3):
            for j in range(-2, 3):
                dx, dy = i * sx / 2.0, j * sy / 2.0
                cands.append((dx * dx + dy * dy, i, j, dx, dy))
        cands.sort()
        for _d, _i, _j, dx, dy in cands:
            ox = rcx - (bx0 + bx1) / 2.0 + dx
            oy = rcy - (by0 + by1) / 2.0 + dy
            moved = [(p[0] * unit + ox, p[1] * unit + oy) for p in b]
            if _ring_contains_ring(moved, ring, (rx0, ry0, rx1, ry1)):
                if place == "cover":
                    return lv, ox, oy
                return _region_best_offset(lv, turn, unit, ox, oy, b, ring,
                                           (rx0, ry0, rx1, ry1), tile_mm,
                                           search)
        # THE BBOX CENTRE CAN SIT IN A BAY.  A deep patch fills only ~0.41 of
        # its own bounding box -- the hull is ragged and the bbox is set by the
        # longest fractal fingers -- so when the region is small relative to
        # the patch (alpha's 107 mm hexagon in the 536 mm level-5 patch at
        # tile_mm 2.0, measured), the bbox centre lands in a bay and the
        # slack-quarter rungs above, ~107 mm apart at that depth, step clean
        # over every valid window.  Shapely agreed with _ring_contains_ring on
        # each of those failures: the geometry test was right, the SEARCH was
        # too coarse.  So, only after the ladder above has failed: anchor on
        # the patch's area centroid, which sits in the patch's mass rather
        # than between its fingers, and walk rungs of HALF THE REGION'S size,
        # which no valid window can fall between.  Purely additive -- any
        # placement that succeeded before this fallback existed still returns
        # identically -- and still a fixed function of (region, tile_mm, seed).
        cbx, cby = centroid(list(b))
        imax = min(6, int(sx / (rw / 2.0))) if rw > 0 else 0
        jmax = min(6, int(sy / (rh / 2.0))) if rh > 0 else 0
        fcands = []
        for i in range(-imax, imax + 1):
            for j in range(-jmax, jmax + 1):
                dx, dy = i * rw / 2.0, j * rh / 2.0
                fcands.append((dx * dx + dy * dy, i, j, dx, dy))
        fcands.sort()
        for _d, _i, _j, dx, dy in fcands[:200]:
            ox = rcx - cbx * unit + dx
            oy = rcy - cby * unit + dy
            moved = [(p[0] * unit + ox, p[1] * unit + oy) for p in b]
            if _ring_contains_ring(moved, ring, (rx0, ry0, rx1, ry1)):
                if place == "cover":
                    return lv, ox, oy
                return _region_best_offset(lv, turn, unit, ox, oy, b, ring,
                                           (rx0, ry0, rx1, ry1), tile_mm,
                                           search)
    deepest = spectre_patch_boundary(hi, turn)
    dw = (max(p[0] for p in deepest) - min(p[0] for p in deepest)) * unit
    dh = (max(p[1] for p in deepest) - min(p[1] for p in deepest)) * unit
    need = spectre_span_tile_mm(rw, rh, hi, turn)
    raise SpectreCoverageError(
        "no spectre patch up to level %d covers a %.3f x %.3f mm region at "
        "tile_mm %.3f, rotation %d. The level-%d patch measures %.3f x %.3f mm "
        "across, but it fills only about 0.62 of its hull, so bounding-box room "
        "is not coverage. Options: raise tile_mm to at least %.3f mm (that is "
        "the bbox bound, and the ragged boundary will want a little more); "
        "audit level %d and raise SPECTRE_AUDITED_LEVEL, which is compute and "
        "not mathematics; or fill a smaller region. NOT on offer: repeating the "
        "patch, which is periodic at the patch pitch and throws away the only "
        "reason to use a spectre, and clipping tiles at the perimeter, which "
        "cuts open slot walls."
        % (hi, rw, rh, tile_mm, turn, hi, dw, dh, need, hi + 1),
        frame_mm=(rw, rh), patch_mm=(dw, dh), tile_mm=float(tile_mm),
        # `need` is the SPAN bound, not the cover bound, and the message says
        # so.  reason="cover" is still the right label -- this is a coverage
        # failure -- and it is what tells a caller not to act on min_tile_mm as
        # if it were sufficient.  There is no cheap cover bound here: unlike
        # spectre_cover_tile_mm(), which bisects a concentric RECTANGLE, this
        # rule searches an offset ladder against an arbitrary POLYGON, so
        # coverage is not monotone in tile_mm about a fixed centre and
        # bisection does not apply.
        min_tile_mm=need, needed_level=None, levels=hi, reason="cover")


def spectre_region_fill(region, tile_mm, seed=0, levels=None,
                        keepouts=(), reject=None, place="cover", search=4):
    """Fill `region` with WHOLE spectre tiles, and report what happened.

    `region` is a closed or open ring of (x, y) in mm, or a rect (x0, y0, x1,
    y1).  `keepouts` is an iterable of rings; every tile that shares interior
    area with one is dropped.  `reject(ring) -> bool` is the same veto in
    callable form, for the masks this module cannot see -- copper, apertures,
    courtyards, a rasterised card face -- so that a caller with a real board
    does not have to turn its mask into polygons first.

    Returns a dict.  `tiles` is the field, closed rings, ordered exactly as
    generate() orders its output.  The rest is the ledger:

        offered           tiles of the patch that reach the region at all
        kept              tiles emitted
        dropped_partial   dropped for crossing the perimeter -- the whitespace
                          the whole-tile rule leaves, and the only whitespace
                          it is allowed to leave
        dropped_keepout   dropped for meeting a keepout
        coverage          covered_mm2 / region_mm2

    NOTHING IS EVER CLIPPED.  A clipped tile has a cut wall that does not
    close, which isolates copper downstream; the perimeter gets whitespace
    instead, which is the trade the board owner asked for.

    `place="most-tiles"` spends compute to lose fewer tiles at the perimeter;
    see _region_best_offset() for the measurement of what that is worth at each
    tile size, which is a fifth of the field at 15 mm and nothing at 3 mm.
    """
    ring, rbox, area = _as_region(region)
    lv, ox, oy = spectre_region_placement(region, tile_mm, seed, levels,
                                          place, search)
    unit = spectre_unit_mm(tile_mm)
    turn = int(seed) % 12
    rx0, ry0, rx1, ry1 = rbox
    kos = []
    for k in keepouts:
        kr = _open([(float(p[0]), float(p[1])) for p in k])
        kos.append((kr, bbox_of(kr)))

    offered = kept = partial = blocked = 0
    out = []
    for t in _rotated_patch(lv, turn)[0]:
        r = [(p[0] * unit + ox, p[1] * unit + oy) for p in t]
        bx0, by0, bx1, by1 = bbox_of(r)
        if bx1 < rx0 - 1e-9 or bx0 > rx1 + 1e-9 or \
           by1 < ry0 - 1e-9 or by0 > ry1 + 1e-9:
            continue                      # not even near the region
        # OFFERED MEANS TOUCHING THE REGION, not "in the region's bounding
        # box".  On a hexagon the box is 15% bigger than the card and the
        # difference is entirely tiles that are nowhere near it -- counting
        # those as offered, and then as partials, would report a third of the
        # field being thrown away at the perimeter when it never reached the
        # perimeter at all.  So `dropped_partial` is exactly the tiles the
        # OUTLINE cuts, which is the number the whitespace at the edge is made
        # of, and offered - kept - dropped_keepout == dropped_partial.
        if not _rings_meet(r, ring, (bx0, by0, bx1, by1), rbox):
            continue
        offered += 1
        if not _ring_contains_ring(ring, r, (bx0, by0, bx1, by1)):
            partial += 1
            continue
        if any(_rings_meet(r, k, (bx0, by0, bx1, by1), kb) for k, kb in kos) or \
           (reject is not None and reject(r + [r[0]])):
            blocked += 1
            continue
        kept += 1
        out.append(r)
    out.sort(key=lambda r: (round(centroid(r)[1], 6), round(centroid(r)[0], 6)))
    covered = sum(abs(signed_area(r)) for r in out)
    return {
        "tiles": [r + [r[0]] for r in out],
        "levels": lv, "turn": turn, "tile_mm": float(tile_mm),
        "seed": int(seed), "offset_mm": (ox, oy),
        "patch_tiles": spectre_patch_size(lv),
        "offered": offered, "kept": kept,
        "dropped_partial": partial, "dropped_keepout": blocked,
        "region_mm2": area, "covered_mm2": covered,
        "coverage": covered / area if area > 0 else 0.0,
        # the count-based figure, kept beside the measured one on purpose: every
        # spectre tile is exactly tile_mm**2, so these two must agree, and a
        # disagreement is a malformed tile rather than a rounding artefact.
        "coverage_by_count": kept * float(tile_mm) ** 2 / area if area else 0.0,
    }


def spectre_region_tiles(region, tile_mm, seed=0, levels=None,
                         keepouts=(), reject=None, place="cover", search=4):
    """The tiles alone, for callers that do not want the ledger."""
    return spectre_region_fill(region, tile_mm, seed, levels,
                               keepouts, reject, place, search)["tiles"]


def _spectre_levels_for(w, h, unit, turn=0, fx=0.5, fy=0.5):
    """Smallest level that actually COVERS a w x h window, and where to put it.

    Returns (levels, (ox, oy)) with the offset in UNIT EDGES from the window's
    lower-left corner to the patch origin.

    THE BBOX IS NOT THE TEST, and that is the correction here.  This used to ask
    only whether the patch's bounding box was at least as big as the window, and
    that was safe when the deepest patch was a 9-tile cluster filling 80% of its
    hull.  A real spectre supertile is ragged and gets raggeder -- 0.71 of its
    hull at level 2, 0.62 at level 4 -- so a window inside the bbox can easily
    contain a bay of the patch's own outer boundary, and whole-tile filtering
    then hands back a tile set with an enclosed HOLE.  Measured: a 14 x 14 mm
    window at tile_mm 4 did exactly that.

    So the test is containment in the boundary polygon, not in the bbox.  The
    seed's slide is offered first and the centred placement is the fallback, so a
    seed can still sample different neighbourhoods but can never buy a hole.
    """
    for levels in range(1, SPECTRE_SUPERTILE_LEVEL + 1):
        ew, eh = spectre_patch_extent(levels, turn)
        if ew * unit < w or eh * unit < h:
            continue
        ring = spectre_patch_boundary(levels, turn)
        pminx = min(p[0] for p in ring)
        pminy = min(p[1] for p in ring)
        pmaxx = max(p[0] for p in ring)
        pmaxy = max(p[1] for p in ring)
        slack_x = (pmaxx - pminx) - w / unit
        slack_y = (pmaxy - pminy) - h / unit
        for gx, gy in ((fx, fy), (0.5, 0.5)):
            rx0 = pminx + gx * slack_x
            ry0 = pminy + gy * slack_y
            if _ring_contains_rect(ring, (rx0, ry0,
                                          rx0 + w / unit, ry0 + h / unit)):
                return levels, (rx0, ry0)
    raise RuntimeError(
        "a %.1f x %.1f mm window is not covered by any spectre patch up to "
        "level %d, the deepest audited SUPERTILE (%d tiles).  Coverage, not "
        "bounding box: a supertile's outer boundary is ragged -- it fills about "
        "0.62 of its convex hull by level 4 -- so a window has to fit inside the "
        "boundary polygon, and this one does not.  Raise tile_mm, audit a deeper "
        "level and raise SPECTRE_AUDITED_LEVEL, or use kind "
        "'spectre-fingerprint', which anchors the patch to a board and lets the "
        "mask decide, instead of fitting it to a window."
        % (w, h, SPECTRE_SUPERTILE_LEVEL,
           spectre_patch_size(SPECTRE_SUPERTILE_LEVEL)))


@register("spectre", size="equal-area size; edge = tile_mm/2.8629", edges=14,
          note="Tile(1,1), the chiral aperiodic monotile, built by its "
               "substitution system.  Straight edges -- see the module "
               "docstring for exactly what that does and does not guarantee")
def _spectre(bbox, tile_mm, seed):
    x0, y0, x1, y1 = bbox
    unit = tile_mm / math.sqrt(SPECTRE_UNIT_AREA)   # mm per unit edge
    turn = (int(seed) % 12) if seed else 0
    rng = random.Random(seed)
    # slide the requested window around inside the patch, so different seeds
    # sample different neighbourhoods of the aperiodic tiling -- but only where
    # the patch actually covers it; see _spectre_levels_for.
    fx = rng.random() if seed else 0.5
    fy = rng.random() if seed else 0.5
    levels, (px, py) = _spectre_levels_for(x1 - x0, y1 - y0, unit, turn, fx, fy)
    pts, _mnx, _mny, _mxx, _mxy = _rotated_patch(levels, turn)
    ox = x0 - px * unit
    oy = y0 - py * unit
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
    ap.add_argument("--spectre-fit-level", type=int, default=4, metavar="N",
                    help="how deep --spectre-fit walks.  The pairwise audit "
                         "costs about 30 s at level 4 and four minutes at "
                         "level 5; the default stops at 4, and going past "
                         "SPECTRE_AUDITED_LEVEL is how you earn the right to "
                         "raise it")
    ap.add_argument("--spectre-census-level", type=int, default=None,
                    metavar="N",
                    help="additionally run the O(n) exact vertex-angle census "
                         "up to level N.  Cheap enough for levels the pairwise "
                         "audit cannot reach")
    a = ap.parse_args(argv)
    if a.spectre_fit:
        print("exact fit audit of the spectre substitution (integer arithmetic,")
        print("no tolerance anywhere):")
        for lv in range(0, max(0, a.spectre_fit_level) + 1):
            r = spectre_exact_fit(lv)
            tiles = _spectre_handed(lv)[0]
            rings = [[z_xy(p) for p in t] for t in tiles]
            o = overlap_audit(rings, cell=4.0)
            au = spectre_patch_audit(lv)
            print("   level %d  %6d tiles  interior edges %7d  boundary %6d  "
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
        if a.spectre_census_level is not None:
            print("   exact vertex-angle census (no lattice point may carry "
                  "more than 360 degrees of tile):")
            for lv in range(0, max(0, a.spectre_census_level) + 1):
                for gamma in (False, True):
                    c = spectre_vertex_census(lv, gamma=gamma)
                    print("      level %d %-5s %8d tiles  %8d vertices  "
                          "interior %8d  over 360 degrees %d  worst %d deg  "
                          "edges shared by 3+ %d"
                          % (lv, "Gamma" if gamma else "", c["n_tiles"],
                             c["distinct_vertices"], c["interior_vertices"],
                             c["vertices_over_360"], c["worst_vertex_deg"],
                             c["edges_shared_by_3_or_more"]))
        print("   two gates, two questions: SPECTRE_SUPERTILE_LEVEL = %d (may I "
              "substitute again), SPECTRE_PATCH_LEVEL = %d (may I place these "
              "tiles and mask them); SPECTRE_AUDITED_LEVEL = %d is how deep the "
              "pairwise audit has been run.  See the module docstring."
              % (SPECTRE_SUPERTILE_LEVEL, SPECTRE_PATCH_LEVEL,
                 SPECTRE_AUDITED_LEVEL))
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
