"""Ground truth for the self-intersection check: WHICH constructs are defects?

check_self_intersection exists because a self-intersecting polygon has no
well-defined area or orientation, so every downstream consumer -- the plotter,
DRC, boolean ops, the fab's rasteriser -- is free to disagree about it. The
measurable symptom is that the shoelace (signed) area stops matching the area
actually filled. A simple polygon never shows that; a bowtie does.

Note it is NOT enough to ask "do even-odd and nonzero disagree?". They agree on
a bowtie (two lobes of opposite orientation, parity 1 and winding +-1 both fill)
yet a bowtie is still malformed. So the tests below use the area criterion.

Against that yardstick:

  * a FRACTURED (keyhole) outline -- what a polygon-with-holes is serialised to,
    and what KiCad's own zone filler emits (SHAPE_POLY_SET::Fracture) -- fills
    exactly the intended region, under both rules, with shoelace area matching.
    The slit is traversed once each way, so it sweeps zero area. Not a defect.
  * a bowtie and a same-direction double traversal both break the area
    identity. Defects.

verify_art.classify_edge_pair must agree with that split.
"""
import sys, pathlib
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import emit_art as E
import verify_art as V


def _fill(poly, X, Y):
    """Even-odd parity and nonzero winding for every sample point."""
    par = np.zeros(X.shape, dtype=np.int64)
    wind = np.zeros(X.shape, dtype=np.int64)
    n = len(poly)
    for k in range(n):
        x0, y0 = poly[k]
        x1, y1 = poly[(k + 1) % n]
        if y0 == y1:
            continue
        straddle = ((y0 <= Y) & (Y < y1)) | ((y1 <= Y) & (Y < y0))
        xin = x0 + (Y - y0) / (y1 - y0) * (x1 - x0)
        hit = straddle & (xin > X)
        par += hit
        wind += np.where(hit & (y1 > y0), 1, 0) - np.where(hit & (y1 < y0), 1, 0)
    return (par % 2).astype(bool), (wind != 0)


def _truth(outer, holes, X, Y):
    inside, _ = _fill(outer, X, Y)
    for h in holes:
        hin, _ = _fill(h, X, Y)
        inside &= ~hin
    return inside


def _shoelace(poly):
    p = np.asarray(poly, dtype=float)
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _grid(half=13.0, n=601):
    g = np.linspace(-half, half, n)
    X, Y = np.meshgrid(g, g)
    cell = (g[1] - g[0]) ** 2
    return X, Y, cell


def _ring(cx, cy, r, n, ccw=True):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    if not ccw:
        a = a[::-1]
    return np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], 1)


CASES = {
    "one centred hole":  (_ring(0, 0, 10, 64), [_ring(0, 0, 4, 32, False)]),
    "two holes":         (_ring(0, 0, 10, 64), [_ring(-4, 0, 2.5, 24, False),
                                                _ring(4, 0, 2.5, 24, False)]),
    "three in a column": (_ring(0, 0, 10, 80), [_ring(0, -5, 2, 20, False),
                                                _ring(0, 0, 2, 20, False),
                                                _ring(0, 5, 2, 20, False)]),
    "three on one row":  (_ring(0, 0, 10, 64), [_ring(-5, 2, 1.5, 16, False),
                                                _ring(0, 2, 1.5, 16, False),
                                                _ring(5, 2, 1.5, 16, False)]),
    "mixed rows":        (_ring(0, 0, 12, 90), [_ring(-6, 3, 2, 18, False),
                                                _ring(0, 3, 2, 18, False),
                                                _ring(6, 3, 2, 18, False),
                                                _ring(0, -5, 3, 20, False)]),
}

BOWTIE = np.array([(0., 0.), (10., 10.), (10., 0.), (0., 10.)])
DOUBLE_TRAVERSAL = np.array([(0., 0.), (10., 0.), (10., 5.), (5., 5.), (5., 0.),
                             (10., 0.), (10., -5.), (0., -5.)])


def test_keyhole_fills_exactly_the_intended_region():
    """Both fill rules, and the true polygon-with-holes, all agree."""
    X, Y, _ = _grid()
    for name, (outer, holes) in CASES.items():
        bridged, unbridged = E.bridge_holes(outer, holes)
        assert unbridged == 0, f"{name}: {unbridged} holes left unbridged"
        eo, nz = _fill(bridged, X, Y)
        tr = _truth(outer, holes, X, Y)
        assert (eo == nz).all(), f"{name}: even-odd and nonzero disagree"
        assert (eo == tr).all(), f"{name}: fill does not match polygon-with-holes"


def test_keyhole_preserves_the_area_identity():
    """The slit sweeps zero area, so shoelace still equals the filled area --
    the property a genuine self-intersection destroys."""
    X, Y, cell = _grid()
    for name, (outer, holes) in CASES.items():
        bridged, _ = E.bridge_holes(outer, holes)
        eo, _ = _fill(bridged, X, Y)
        rast = eo.sum() * cell
        sign = abs(_shoelace(bridged))
        assert abs(sign - rast) / rast < 0.02, \
            f"{name}: shoelace {sign:.3f} vs rasterised {rast:.3f}"


def test_keyhole_is_not_flagged_as_a_hazard():
    """Every edge pair in a bridged outline is either clean or a slit."""
    for name, (outer, holes) in CASES.items():
        bridged, _ = E.bridge_holes(outer, holes)
        pts = [tuple(p) for p in bridged]
        e = V.edges_of(pts, closed=True)
        m = len(e)
        bad = []
        for a in range(m):
            for b in range(a + 2, m):
                if a == 0 and b == m - 1:
                    continue
                k = V.classify_edge_pair(e[a][0], e[a][1], e[b][0], e[b][1])
                if k is not None and k is not V._SLIT:
                    bad.append((a, b, k))
        assert not bad, f"{name}: classifier calls a keyhole a hazard: {bad[:5]}"


def test_bowtie_breaks_the_area_identity():
    """Signed area collapses to ~0 while real filled area is ~50 mm2."""
    X, Y, cell = _grid()
    eo, _ = _fill(BOWTIE, X, Y)
    rast = eo.sum() * cell
    assert rast > 40, "sanity: the bowtie does enclose area"
    assert abs(_shoelace(BOWTIE)) < 0.01 * rast, \
        "bowtie signed area should cancel to nothing"


def test_double_traversal_breaks_the_area_identity():
    """The re-traversed span is counted twice by shoelace."""
    X, Y, cell = _grid()
    eo, _ = _fill(DOUBLE_TRAVERSAL, X, Y)
    rast = eo.sum() * cell
    assert abs(abs(_shoelace(DOUBLE_TRAVERSAL)) - rast) / rast > 0.1, \
        "double traversal should not preserve the area identity"


def test_classifier_flags_both_hazards():
    for name, poly in (("bowtie", BOWTIE), ("double traversal", DOUBLE_TRAVERSAL)):
        pts = [tuple(p) for p in poly]
        e = V.edges_of(pts, closed=True)
        m = len(e)
        kinds = set()
        for a in range(m):
            for b in range(a + 2, m):
                if a == 0 and b == m - 1:
                    continue
                k = V.classify_edge_pair(e[a][0], e[a][1], e[b][0], e[b][1])
                if k is not None:
                    kinds.add(k)
        assert kinds - {V._SLIT}, f"{name}: classifier saw no hazard, only {kinds}"


# --- holes sharing an exact y (text art) ------------------------------------
#
# The bridge vertex is the topmost of a hole's leftmost vertices, so it is
# always a local extremum in y. A half-open straddle test cannot see an edge
# that merely touches the ray there, which made an already-merged hole
# invisible to any later hole on the same row -- and the later slit was laid
# straight over the earlier one. Letter counters on one line of text share a
# row constantly, so this was the common case, not a corner case.

def _rect(x0, y0, x1, y1, ccw=True):
    p = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return np.array(p if ccw else p[::-1], dtype=float)


ROW_OF_HOLES = (
    _rect(-10, -10, 10, 10),
    [_rect(-8, -2, -6, 2, False),      # all three share y == -2 exactly,
     _rect(-3, -2, -1, 2, False),      # which is where the bridge vertex sits
     _rect(2, -2, 4, 2, False)],
)


def test_holes_sharing_a_row_do_not_produce_overlapping_slits():
    outer, holes = ROW_OF_HOLES
    bridged, unbridged = E.bridge_holes(outer, holes)
    assert unbridged == 0
    pts = [tuple(p) for p in bridged]
    e = V.edges_of(pts, closed=True)
    m = len(e)
    bad = []
    for a in range(m):
        for b in range(a + 2, m):
            if a == 0 and b == m - 1:
                continue
            k = V.classify_edge_pair(e[a][0], e[a][1], e[b][0], e[b][1])
            if k is not None and k is not V._SLIT:
                bad.append((a, b, k))
    assert not bad, f"slits overlap for holes on a shared row: {bad[:5]}"


def test_holes_sharing_a_row_still_fill_correctly():
    outer, holes = ROW_OF_HOLES
    X, Y, cell = _grid()
    bridged, _ = E.bridge_holes(outer, holes)
    eo, nz = _fill(bridged, X, Y)
    tr = _truth(outer, holes, X, Y)
    assert (eo == nz).all()
    assert (eo == tr).all(), "fixing the slits must not change the filled region"
    assert abs(abs(_shoelace(bridged)) - eo.sum() * cell) / (eo.sum() * cell) < 0.02


def test_many_rows_of_holes_stay_clean():
    """A grid of holes: every row shares a y, every column shares an x."""
    outer = _rect(-20, -20, 20, 20)
    holes = [_rect(x, y, x + 2, y + 2, False)
             for y in (-12, -6, 0, 6) for x in (-14, -8, -2, 4, 10)]
    bridged, unbridged = E.bridge_holes(outer, holes)
    assert unbridged == 0
    pts = [tuple(p) for p in bridged]
    e = V.edges_of(pts, closed=True)
    m = len(e)
    bad = 0
    for a in range(m):
        for b in range(a + 2, m):
            if a == 0 and b == m - 1:
                continue
            k = V.classify_edge_pair(e[a][0], e[a][1], e[b][0], e[b][1])
            if k is not None and k is not V._SLIT:
                bad += 1
    assert bad == 0, f"{bad} overlapping/crossing pairs in a 4x5 hole grid"
