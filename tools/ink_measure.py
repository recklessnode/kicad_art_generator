#!/usr/bin/env python3
"""True ink measurement for one fabrication layer: inscribed feature width,
real gaps, and what a morphological opening at the floor actually deletes.

WHY THIS EXISTS, AND WHAT IT REPLACES
-------------------------------------
verify_art.py measured a filled polygon with `min_width()`, a rotating-caliper
on the CONVEX HULL. For a rectangle that is exact. For a traced letterform it
reports the glyph's overall width -- roughly 1.2 mm for a capital at a 1.6 mm
cap -- while the stem it is actually made of is 0.117 mm. The hull answer is
not merely imprecise, it is a green check written over the exact defect.

The gap check had the mirror-image hole. It compares ITEMS pairwise, and a
keyhole-bridged glyph is ONE polygon: the outer contour and its counter are the
same ring, so the void inside an 'o' is intra-item and unreachable. The gaps
that shipped on the alpha coupon's front face -- 0.116600 mm and five more --
are every one of them intra-ring.

Both holes have the same root: the measurement was per ITEM, and ink is not per
item. Ink is a REGION. This module measures the region:

  * FEATURE WIDTH  the narrowest neck of the ink, anywhere, measured between
                   two boundary points whose midpoint lies INSIDE the ink.
  * GAP            the narrowest separation, anywhere, measured between two
                   boundary points whose midpoint lies OUTSIDE the ink.
                   Intra-ring pairs count, which is what makes counters and
                   notches visible.
  * VANISHED       components whose THICKEST ink is under the floor, found by
                   eroding the whole layer once and asking which components
                   have nothing left. A component that vanishes is a piece of
                   art that does not appear on the delivered board.
  * OPENING LOSS   how much ink area an opening at the floor removes. Reported
                   as a MAGNITUDE, never as a verdict -- see the caveat on
                   `open_area_lost`.

WHAT THIS DOES NOT MEASURE, STATED SO IT IS NEVER MISTAKEN FOR A PASS
---------------------------------------------------------------------
  * Without shapely there is no measurement at all. `available()` says so and
    the caller must report SKIP. There is no fallback estimate, because a
    fallback estimate of a floor violation is how the floor stops working.
  * The neck/gap scan ignores boundary pairs closer than `arc_ratio x floor`
    ALONG THE RING, because two adjacent segments of the same contour are
    trivially close and would swamp everything. A feature whose whole boundary
    is shorter than that -- a speck the size of the floor itself -- therefore
    has no neck witness. That case is caught by VANISHED instead, which has no
    such blind spot, and the two are reported together for exactly this reason.
  * Curves are flattened by the caller before they arrive here. Flattening a
    round pad into a 64-gon makes it very slightly polygonal; the caller is
    told to circumscribe rather than inscribe so the error costs margin instead
    of hiding a violation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# shapely is optional and its absence is a SKIP, never a pass
# --------------------------------------------------------------------------

try:  # pragma: no cover - exercised by whichever branch the host provides
    import numpy as _np
    import shapely as _shp
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    from shapely.prepared import prep
    from shapely.strtree import STRtree
    _WHY = ""
except Exception as _e:  # pragma: no cover
    _np = _shp = None
    _WHY = f"{type(_e).__name__}: {_e}"

HAVE_SHAPELY = _shp is not None
SHAPELY_WHY = _WHY


def available() -> tuple[bool, str]:
    """(can we measure, why not)."""
    if HAVE_SHAPELY:
        return True, ""
    return False, ("shapely is not importable, so the ink region cannot be "
                   f"built and NOTHING on this layer was measured ({SHAPELY_WHY}). "
                   "pip install shapely")


# Buffer resolution. 16 quadrant segments puts a round join within 0.24% of the
# true circle; erosion by an INSCRIBED polygon erodes slightly less than a true
# disc, so the error direction is fewer false failures, never fewer real ones.
QUAD_SEGS = 16

# Two boundary points closer than this multiple of the floor as measured ALONG
# the contour are the same piece of boundary, not two sides of a feature.
ARC_RATIO = 2.0

# Areas below this are shapely rounding, not ink.
AREA_EPS = 1e-9

# How far a local closing test looks around a gap witness, in floors. Taken
# from art-coupon/tools/check_silk_bridging.py, which asked this question first.
LOCAL_R_FLOORS = 6.0

# Beyond this many clustered gap witnesses the bridging classification gives up
# and says so rather than spending unbounded time on buffer operations.
MAX_CLASSIFY = 400

# A feature EXACTLY at the floor is not under it. Every other floor comparison
# in this tree is `value < floor - eps`; the erosion test was the one place
# that was not, and it is unstable there -- a straight 0.150 mm bar erodes to
# nothing at floor/2 while an L-bend of the same stroke does not, because the
# rounded join leaves a spot where the disc fits. The fab publishes 0.150 mm as
# the finest silk it images, so a 0.150 mm stroke images. Eroding by
# (floor - FLOOR_EPS)/2 makes the test agree with every other floor test here
# and with the process, and a feature at 0.1499 mm still vanishes.
FLOOR_EPS = 1e-6

# Two boundary points this close are the SAME POINT. KiCad stores coordinates
# to the nanometre (1e-6 mm), so anything under that is not a gap and not a
# neck -- it is two objects touching, and a union built from a zone fill, the
# tracks that enter it and the pads it surrounds is full of exact tangencies.
# Reporting those as "gap 0.000000 mm" produced 45 findings on the product
# board, every one of them a contact point, and burying eight real ones.
CONTACT_MM = 1e-6


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

@dataclass
class Part:
    """One piece of ink on one layer, already in board coordinates.

    area=True  : `pts` is a closed outline that is FILLED (minus `holes`).
    area=False : `pts` is a centreline stroked `width` wide with round caps.
    """
    label: str
    pts: list
    width: float = 0.0
    area: bool = True
    closed: bool = True
    holes: list = field(default_factory=list)
    # KiCad net number, "" for none. Copper on one net is one conductor and
    # the space between two pieces of it is not a spacing limit; copper with
    # NO net is not exempt, because two unconnected tiles still have to etch
    # apart. Only used to classify GAPS -- a feature that is too thin is too
    # thin whatever it is connected to.
    net: str = ""
    # Which footprint instance this ink came from, -1 for board-level graphics.
    # Used ONLY to decide whether a sweep declaration may claim a witness: if
    # any foreign part contributes to the merged region there, the finding is
    # not the declaring block's to claim. See verify_art.SweepTable.
    owner: int = -1


@dataclass
class Witness:
    """A measured number and where on the board it is."""
    value: float
    x: float
    y: float
    note: str = ""

    def __str__(self) -> str:
        s = f"{self.value:.6f} mm at ({self.x:.3f}, {self.y:.3f})"
        return s + (f" -- {self.note}" if self.note else "")


@dataclass
class LayerInk:
    layer: str
    floor: float
    ok: bool = False
    why: str = ""
    n_parts: int = 0
    n_components: int = 0
    area: float = 0.0
    min_feature: Witness | None = None
    min_gap: Witness | None = None
    features_below: list = field(default_factory=list)
    gaps_below: list = field(default_factory=list)
    vanished: int = 0
    vanished_area: float = 0.0
    vanished_examples: list = field(default_factory=list)
    open_area_lost: float = 0.0
    open_pct: float = 0.0
    n_segments: int = 0
    n_candidates: int = 0
    n_samenet_gaps: int = 0
    incomplete: bool = False
    incomplete_why: str = ""
    notes: list = field(default_factory=list)
    # --- gap witnesses a closing at the floor does NOT join ---------------
    # A re-entrant corner inside one glyph narrows to zero at its vertex, so
    # the scan always finds a sub-floor pair there whatever the cap height --
    # the value is a property of the junction angle and of the scan, not of the
    # artwork. Discounted from the verdict and COUNTED here, never dropped.
    rounded_gaps: list = field(default_factory=list)
    n_rounded_gaps: int = 0
    n_bridging_gaps: int = 0
    classify_incomplete: bool = False
    # --- judgement suspended by a sweep declaration ----------------------
    # Counted per quantity so the caller can print who claimed what. Nothing
    # here is removed from the measurement; it is moved out of the verdict.
    n_exempt: dict = field(default_factory=dict)
    exempt_witnesses: list = field(default_factory=list)   # (quantity, Witness)
    # Every component the floor deletes, not just the max_report widest.
    vanished_witnesses: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return (self.ok and not self.incomplete and not self.features_below
                and not self.gaps_below and not self.vanished)


# --------------------------------------------------------------------------
# Region construction
# --------------------------------------------------------------------------

def build_geometry(parts, quad_segs: int = QUAD_SEGS):
    """Union every Part into one region. None if there is no ink."""
    if not HAVE_SHAPELY:
        raise RuntimeError("shapely unavailable")
    pieces = []
    strokes: dict[float, list] = {}
    for p in parts:
        if p.area:
            if len(p.pts) < 3:
                continue
            try:
                g = Polygon(p.pts, p.holes or None)
            except Exception:
                continue
            if not g.is_valid:
                g = g.buffer(0)
            if not g.is_empty:
                pieces.append(g)
        else:
            if len(p.pts) < 2:
                if len(p.pts) == 1 and p.width > 0:
                    pieces.append(Point(p.pts[0]).buffer(p.width / 2.0,
                                                         quad_segs=quad_segs))
                continue
            pts = list(p.pts)
            if p.closed and pts[0] != pts[-1]:
                pts.append(pts[0])
            strokes.setdefault(round(max(p.width, 1e-6), 9), []).append(
                LineString(pts))
    for w, lss in strokes.items():
        merged = unary_union(lss)
        pieces.append(merged.buffer(w / 2.0, quad_segs=quad_segs,
                                    cap_style=1, join_style=1))
    if not pieces:
        return None
    geo = unary_union(pieces)
    return None if geo.is_empty else geo


def _polys(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in geom.geoms if g.geom_type == "Polygon"]


def _rings(geom):
    out = []
    for p in _polys(geom):
        out.append(list(p.exterior.coords))
        for r in p.interiors:
            out.append(list(r.coords))
    return out


# --------------------------------------------------------------------------
# Exact segment-to-segment distance, with the closest points
# --------------------------------------------------------------------------

def seg_seg_closest(a, b, c, d):
    """(distance, point on ab, point on cd). Exact for the non-parallel case
    and iterated for the degenerate one."""
    def clamp(t):
        return 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    wx, wy = a[0] - c[0], a[1] - c[1]
    A = ux * ux + uy * uy
    B = ux * vx + uy * vy
    C = vx * vx + vy * vy
    D = ux * wx + uy * wy
    E = vx * wx + vy * wy
    den = A * C - B * B
    if den > 1e-18:
        s = clamp((B * E - C * D) / den)
        t = clamp((A * E - B * D) / den)
    else:
        s = 0.0
        t = clamp(E / C) if C > 1e-18 else 0.0
    for _ in range(3):
        t = clamp((B * s + E) / C) if C > 1e-18 else 0.0
        s = clamp((B * t - D) / A) if A > 1e-18 else 0.0
    px, py = a[0] + s * ux, a[1] + s * uy
    qx, qy = c[0] + t * vx, c[1] + t * vy
    return math.hypot(px - qx, py - qy), (px, py), (qx, qy)


def _cluster(rows, tol):
    """Collapse witnesses that describe the same spot. Keeps the smallest."""
    rows = sorted(rows, key=lambda w: w.value)
    out: list = []
    for w in rows:
        if any(math.hypot(w.x - o.x, w.y - o.y) < tol for o in out):
            continue
        out.append(w)
    return out


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------

def _topology(geom):
    ps = _polys(geom)
    return len(ps), sum(len(p.interiors) for p in ps)


def bridges_at_floor(geo, x: float, y: float, floor: float,
                     quad_segs: int = QUAD_SEGS,
                     r_floors: float = LOCAL_R_FLOORS) -> bool:
    """Does a closing at the floor JOIN anything near (x, y)?

    A gap matters when the process can close it -- when ink the design keeps
    apart ends up joined. That is a topology question and it has a topology
    answer: close the local region at the floor and compare component and hole
    counts. If they are unchanged, the sub-floor pair the scan found was a
    corner being rounded and nothing bridged.

    Run LOCALLY, in a disc around the witness, so one real bridge cannot hide
    behind fifty rounded corners in a global count.
    """
    win = Point(x, y).buffer(r_floors * floor, quad_segs=16)
    g = geo.intersection(win)
    if g.is_empty:
        return True                 # nothing to reason about: keep the finding
    c = (g.buffer(floor / 2.0, quad_segs=quad_segs, join_style=1)
          .buffer(-floor / 2.0, quad_segs=quad_segs, join_style=1)
          .intersection(win))
    return _topology(g) != _topology(c)


def measure_layer(layer: str, parts, floor: float, *,
                  quad_segs: int = QUAD_SEGS,
                  arc_ratio: float = ARC_RATIO,
                  max_segments: int = 250_000,
                  max_candidates: int = 4_000_000,
                  max_report: int = 8,
                  exempt=None,
                  classify_gaps: bool = True) -> LayerInk:
    """Measure one layer's ink against one floor.

    Every number that comes back is measured off the region. Where a number
    could not be produced the field stays None and `incomplete`/`why` says
    which, so the caller can report NOT MEASURED rather than a pass.

    `exempt(quantity, witness) -> 'exempt' | 'out-of-band' | None` is the sweep
    declaration hook. The POLICY lives entirely in the caller; this function
    only partitions and counts, and everything it suspends judgement on is
    returned in `n_exempt` / `exempt_witnesses` so the caller can print it. An
    'out-of-band' verdict still leaves the witness in the findings, because a
    part that broke its own declared bound is a failure of the declaration, not
    an exemption from it.
    """
    r = LayerInk(layer=layer, floor=floor, n_parts=len(parts))
    ok, why = available()
    if not ok:
        r.why = why
        return r
    try:
        geo = build_geometry(parts, quad_segs=quad_segs)
    except Exception as e:                       # pragma: no cover
        r.why = f"the ink region could not be built: {type(e).__name__}: {e}"
        return r
    if geo is None:
        r.ok = True
        r.why = "no ink on this layer"
        return r

    r.ok = True
    # Slivers of zero area are what a union leaves behind where two objects
    # touch exactly. They are not components of the ink and counting them as
    # ones that "vanish at the floor" is a finding about arithmetic.
    all_comps = _polys(geo)
    comps = [p for p in all_comps if p.area > AREA_EPS]
    n_sliver = len(all_comps) - len(comps)
    if n_sliver:
        r.notes.append(f"{n_sliver} zero-area sliver(s) dropped: a union leaves "
                       f"one wherever two objects touch exactly, and they are "
                       f"not ink")
    r.n_components = len(comps)
    r.area = geo.area

    # ---- erosion: which whole components are finer than the floor ---------
    # Eroded by (floor - FLOOR_EPS)/2, not floor/2: see FLOOR_EPS. A feature
    # exactly AT the floor is at the process limit, not under it, and the strict
    # form made that verdict depend on whether the stroke happened to have a
    # corner in it.
    rad = max(floor - FLOOR_EPS, 0.0) / 2.0
    er = geo.buffer(-rad, quad_segs=quad_segs, join_style=1)
    if er.is_empty:
        gone = comps
    else:
        gone = [p for p in comps if not p.intersects(er)]
    op = er.buffer(rad, quad_segs=quad_segs, join_style=1) if not er.is_empty else er
    lost = geo.area - (op.area if not op.is_empty else 0.0)
    r.open_area_lost = max(0.0, lost)
    r.open_pct = (100.0 * r.open_area_lost / geo.area) if geo.area > 0 else 0.0

    # Every deleted component gets a witness, not just the widest few: a sweep
    # declaration is matched on coordinates, so a component with no witness
    # could never be attributed to the block that drew it on purpose.
    kept_gone = []
    for p in sorted(gone, key=lambda q: -q.area):
        c = p.representative_point()
        w = Witness(_max_inscribed_diameter(p, floor, quad_segs), c.x, c.y,
                    f"whole component, {p.area:.5f} mm^2")
        r.vanished_witnesses.append(w)
        if exempt is not None and exempt("vanish", w) == "exempt":
            r.n_exempt["vanish"] = r.n_exempt.get("vanish", 0) + 1
            r.exempt_witnesses.append(("vanish", w))
            continue
        kept_gone.append((p, w))
    r.vanished = len(kept_gone)
    r.vanished_area = sum(p.area for p, _w in kept_gone)
    r.vanished_examples = [w for _p, w in kept_gone[:max_report]]

    # ---- boundary scan: exact necks and gaps, with witnesses --------------
    segs = []                    # (p, q, ring, cum_at_start)
    ringlen = {}
    for ri, ring in enumerate(_rings(geo)):
        cum = 0.0
        for k in range(len(ring) - 1):
            p, q = ring[k], ring[k + 1]
            segs.append((p, q, ri, cum))
            cum += math.hypot(q[0] - p[0], q[1] - p[1])
        ringlen[ri] = cum
    r.n_segments = len(segs)
    if not segs:
        return r
    if len(segs) > max_segments:
        r.incomplete = True
        r.incomplete_why = (
            f"{len(segs):,} boundary segments is over the {max_segments:,} "
            f"scan limit, so the narrowest feature and the narrowest gap on "
            f"this layer are NOT MEASURED (raise --ink-max-segments). The "
            f"erosion numbers above still hold; the exact widths do not exist")
        return r

    geoms = [LineString([s[0], s[1]]) for s in segs]
    arr = _np.array(geoms, dtype=object)
    tree = STRtree(geoms)
    try:
        pairs = tree.query(arr, predicate="dwithin", distance=floor)
    except Exception:                            # GEOS < 3.10
        pairs = tree.query(_np.array([g.buffer(floor, quad_segs=1)
                                      for g in geoms], dtype=object))
    ii, jj = pairs[0], pairs[1]
    mask = jj > ii
    ii, jj = ii[mask], jj[mask]
    r.n_candidates = int(len(ii))
    if r.n_candidates > max_candidates:
        r.incomplete = True
        r.incomplete_why = (
            f"{r.n_candidates:,} boundary pairs is over the "
            f"{max_candidates:,} budget, so the narrowest feature and gap are "
            f"NOT MEASURED (raise --ink-budget)")
        return r

    arc_skip = arc_ratio * floor
    hits = []
    n_contact = 0
    for i, j in zip(ii.tolist(), jj.tolist()):
        pi, qi, ri_, ci = segs[i]
        pj, qj, rj_, cj = segs[j]
        d, A, B = seg_seg_closest(pi, qi, pj, qj)
        if d <= CONTACT_MM:
            n_contact += 1
            continue
        if d >= floor:
            continue
        if ri_ == rj_:
            # ARC DISTANCE IS MEASURED TO THE CLOSEST POINTS, not between the
            # segments' endpoints. Between endpoints it under-states: a notch
            # 0.12 mm wide and 3 mm deep is bounded by two long parallel
            # segments joined at the base, so the endpoint arc is 0.12 mm, the
            # whole pair is thrown away as contour-adjacent, and a 3 mm slot
            # narrower than the floor is never reported. Measured to the
            # closest points the same pair reports 6 mm of contour at the
            # notch MOUTH and is kept. This can only ADD pairs -- the closest
            # point never lies outside its own segment -- so it never loses a
            # finding that the endpoint form would have made.
            L = ringlen[ri_]
            cumA = ci + math.hypot(A[0] - pi[0], A[1] - pi[1])
            cumB = cj + math.hypot(B[0] - pj[0], B[1] - pj[1])
            delta = abs(cumA - cumB)
            if min(delta, max(L - delta, 0.0)) < arc_skip:
                continue
        hits.append((d, (A[0] + B[0]) / 2.0, (A[1] + B[1]) / 2.0))

    inside = prep(geo)
    necks, gaps = [], []
    for d, mx, my in hits:
        w = Witness(d, mx, my)
        (necks if inside.contains(Point(mx, my)) else gaps).append(w)

    # SAME-NET GAPS ARE NOT SPACING. Build a region per named net and drop any
    # gap whose two sides are both inside one of them: a track, the via it
    # lands on and the pour it feeds are one conductor. Only the gap witnesses
    # are tested, so this costs nothing on a layer with no nets at all -- which
    # is every silk and mask layer, and every art coupon.
    nets = sorted({p.net for p in parts if p.net})
    if nets and gaps:
        regions = {}
        for nm in nets:
            g = build_geometry([p for p in parts if p.net == nm],
                               quad_segs=quad_segs)
            if g is not None:
                regions[nm] = g
        keep = []
        for w in gaps:
            probe = Point(w.x, w.y).buffer(w.value * 1.5 + 1e-9, quad_segs=8)
            local = geo.intersection(probe)
            same = False
            if not local.is_empty:
                for g in regions.values():
                    if not g.intersects(probe):
                        continue
                    # ALL the ink bounding this gap belongs to one net, so the
                    # gap is internal to a single conductor.
                    if local.difference(g).area <= max(1e-12, local.area * 1e-6):
                        same = True
                        break
            if same:
                r.n_samenet_gaps += 1
                continue
            keep.append(w)
        gaps = keep
    tol = max(floor, 1e-6)
    # CLUSTER FIRST, then judge. _cluster() sorts by value and keeps the
    # smallest of each neighbourhood, so the global minimum is always a
    # representative and the two passes below cannot disagree about it.
    neck_reps = _cluster(necks, tol)
    gap_reps = _cluster(gaps, tol)

    kept_necks = []
    for w in neck_reps:
        if exempt is not None and exempt("width", w) == "exempt":
            r.n_exempt["width"] = r.n_exempt.get("width", 0) + 1
            r.exempt_witnesses.append(("width", w))
            continue
        kept_necks.append(w)

    kept_gaps = []
    if classify_gaps and gap_reps:
        todo = gap_reps[:MAX_CLASSIFY]
        if len(gap_reps) > MAX_CLASSIFY:
            r.classify_incomplete = True
        for w in todo:
            if exempt is not None and exempt("gap", w) == "exempt":
                r.n_exempt["gap"] = r.n_exempt.get("gap", 0) + 1
                r.exempt_witnesses.append(("gap", w))
                continue
            if bridges_at_floor(geo, w.x, w.y, floor, quad_segs):
                r.n_bridging_gaps += 1
                kept_gaps.append(w)
            else:
                r.n_rounded_gaps += 1
                r.rounded_gaps.append(w)
        # Anything past the classification cap is KEPT as a finding: the
        # unexamined case must never be the quiet one.
        kept_gaps += gap_reps[MAX_CLASSIFY:]
    else:
        for w in gap_reps:
            if exempt is not None and exempt("gap", w) == "exempt":
                r.n_exempt["gap"] = r.n_exempt.get("gap", 0) + 1
                r.exempt_witnesses.append(("gap", w))
                continue
            kept_gaps.append(w)

    r.features_below = kept_necks[:max_report]
    r.gaps_below = kept_gaps[:max_report]
    if kept_necks:
        r.min_feature = min(kept_necks, key=lambda w: w.value)
    if kept_gaps:
        r.min_gap = min(kept_gaps, key=lambda w: w.value)
    if r.n_rounded_gaps:
        worst_r = min(r.rounded_gaps, key=lambda w: w.value)
        r.notes.append(
            f"{r.n_rounded_gaps} sub-floor gap witness(es) are RE-ENTRANT "
            f"CORNERS, not gaps: a closing at {floor:.4f} mm rounds each one "
            f"and joins nothing, so the process cannot bridge there. Narrowest "
            f"of them {worst_r}. {r.n_bridging_gaps} witness(es) DO bridge and "
            f"are judged above")
    if r.classify_incomplete:
        r.notes.append(
            f"more than {MAX_CLASSIFY} clustered gap witnesses: the closing "
            f"test was applied to the first {MAX_CLASSIFY} and the rest are "
            f"KEPT as findings unexamined")
    r.notes.append(
        f"boundary scan: {len(segs):,} segments, {r.n_candidates:,} pairs "
        f"within {floor:.4f} mm, contour-adjacent pairs closer than "
        f"{arc_skip:.4f} mm along the ring excluded as the same piece of "
        f"boundary"
        + (f", {n_contact:,} pair(s) at or under {CONTACT_MM:g} mm treated as "
           f"objects TOUCHING rather than as a gap or a neck" if n_contact
           else ""))
    return r


def _max_inscribed_diameter(poly, floor: float, quad_segs: int,
                            iters: int = 24) -> float:
    """Largest circle that fits in `poly`, by bisection on erosion.

    Only ever called on components that already failed the erosion test, so
    the answer is known to be under `floor` and the bracket starts there.
    """
    lo, hi = 0.0, max(floor, 1e-6)
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if poly.buffer(-mid / 2.0, quad_segs=quad_segs).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def measure_gap_closure(parts, floor: float, quad_segs: int = QUAD_SEGS):
    """Area a closing at the floor adds: > 0 means some void is narrower than
    the floor. Complete where the boundary scan is not, and unused for the
    verdict for the same reason `open_area_lost` is -- a disc structuring
    element rounds concave corners just as it rounds convex ones."""
    geo = build_geometry(parts, quad_segs=quad_segs)
    if geo is None:
        return 0.0
    cl = geo.buffer(floor / 2.0, quad_segs=quad_segs, join_style=1)
    cl = cl.buffer(-floor / 2.0, quad_segs=quad_segs, join_style=1)
    return max(0.0, cl.area - geo.area)
