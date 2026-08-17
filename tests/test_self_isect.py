"""Self-intersection check: must catch real fill hazards, must not cry wolf.

Context. A polygon-with-holes is serialised to KiCad as a single *fractured*
outline: each hole is joined to the boundary by a zero-width slit that is
traversed once inward and once outward. KiCad's own zone filler does exactly
this (SHAPE_POLY_SET::Fracture) and plots the result with fill-rule:evenodd.

The slit is a collinear overlap of positive length, so a naive overlap test
calls it a self-intersection. It is not a fill hazard: an edge traversed once
in each direction changes the winding number of no point off the segment, so
even-odd and nonzero agree. tests/test_keyhole_fill.py proves that by
rasterisation. This file guards the *classifier*: the check must still fail on
everything that genuinely makes a fill ambiguous.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import verify_art as V


def _poly_check(pts, layer="F.SilkS"):
    """Run the real check over one polygon and return (level, head, details)."""
    it = V.Item(kind="fp_poly", layers=[layer], pts=[tuple(p) for p in pts],
                filled=True, width=0.0)
    fp = V.Footprint(name="t", version="20241229", generator="test", items=[it])
    cfg = type("C", (), {"max_poly_pts": 100000, "max_report": 50})()
    c = V.check_self_intersection(fp, cfg)
    return c.level, c.headline, c.details


# --- must FAIL: genuine fill hazards ---------------------------------------

def test_bowtie_proper_crossing_fails():
    lvl, head, _ = _poly_check([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert lvl == V.FAIL, f"bowtie must fail, got {lvl} {head}"


def test_figure_eight_fails():
    lvl, _, _ = _poly_check([(0, 0), (4, 4), (8, 0), (8, 4), (4, 0), (0, 4)])
    assert lvl == V.FAIL


def test_collinear_overlap_same_direction_fails():
    """Traversing a stretch of line twice in the SAME direction is not a slit:
    there is no compensating reverse traversal, so nonzero and even-odd
    disagree about the region beyond it. test_keyhole_fill.py proves the
    disagreement; this asserts the checker calls it out."""
    pts = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 0),
           (10, 0), (10, -5), (0, -5)]
    lvl, _, _ = _poly_check(pts)
    assert lvl == V.FAIL


def test_partial_reverse_overlap_fails():
    """Reverse traversal of only PART of an earlier edge: extents differ, so it
    is not a balanced slit and the swept region is ambiguous."""
    pts = [(0, 0), (10, 0), (10, 5), (6, 5), (6, 0), (2, 0), (2, 8), (0, 8)]
    lvl, _, _ = _poly_check(pts)
    assert lvl == V.FAIL


def test_spiral_self_crossing_fails():
    pts = [(0, 0), (10, 0), (10, 10), (2, 10), (2, 2), (6, 2), (6, 6), (-1, 6)]
    lvl, _, _ = _poly_check(pts)
    assert lvl == V.FAIL


# --- must PASS: not hazards -------------------------------------------------

def test_simple_square_passes():
    lvl, _, _ = _poly_check([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert lvl == V.PASS


def test_collinear_vertex_split_passes():
    """A vertex inserted in the middle of a straight edge splits it into two
    collinear halves that touch at one point and overlap over zero length.
    Bridging inserts exactly this. It is not an intersection."""
    pts = [(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)]
    lvl, head, det = _poly_check(pts)
    assert lvl == V.PASS, f"collinear split vertex must not flag: {head} {det}"


def test_collinear_split_far_apart_in_index_passes():
    """Same touch, but the two collinear halves are far apart in vertex order,
    which is how a keyhole bridge point actually appears."""
    pts = [(-8, -6), (-8, 0), (-6, 0), (-6, -4), (-4, -4), (-4, 4),
           (-6, 4), (-6, 0), (-8, 0), (-8, 6), (8, 6), (8, -6)]
    lvl, head, det = _poly_check(pts)
    assert lvl == V.PASS, f"{head} {det}"


def test_keyhole_slit_passes_and_is_reported():
    """The real construction: square with one square hole, bridged."""
    import numpy as np
    import emit_art as E
    outer = np.array([(-10., -10.), (10., -10.), (10., 10.), (-10., 10.)])
    hole = np.array([(-4., -4.), (-4., 4.), (4., 4.), (4., -4.)])
    bridged, unb = E.bridge_holes(outer, [hole])
    assert unb == 0
    lvl, head, det = _poly_check(bridged.tolist())
    assert lvl == V.PASS, f"keyhole must pass: {head} {det}"
    blob = " ".join(det).lower()
    assert "slit" in blob or "fracture" in blob, \
        f"the slit must be REPORTED, not silently ignored: {det}"


def test_two_holes_keyhole_passes():
    import numpy as np
    import emit_art as E
    outer = np.array([(-10., -10.), (10., -10.), (10., 10.), (-10., 10.)])
    h1 = np.array([(-6., -2.), (-6., 2.), (-2., 2.), (-2., -2.)])
    h2 = np.array([(2., -2.), (2., 2.), (6., 2.), (6., -2.)])
    bridged, unb = E.bridge_holes(outer, [h1, h2])
    assert unb == 0
    lvl, head, det = _poly_check(bridged.tolist())
    assert lvl == V.PASS, f"{head} {det}"


def test_slit_plus_real_crossing_still_fails():
    """A polygon that has BOTH a legitimate slit and a genuine crossing must
    still fail -- the slit exemption must not mask a real defect."""
    import numpy as np
    import emit_art as E
    outer = np.array([(-10., -10.), (10., -10.), (10., 10.), (-10., 10.)])
    hole = np.array([(-4., -4.), (-4., 4.), (4., 4.), (4., -4.)])
    bridged, _ = E.bridge_holes(outer, [hole])
    pts = bridged.tolist()
    pts += [(-20., 0.), (20., 1.)]          # a bar that slices the outline
    lvl, head, det = _poly_check(pts)
    assert lvl == V.FAIL, f"crossing hidden behind a slit: {head} {det}"
