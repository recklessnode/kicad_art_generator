"""T8 windows and T9 cuts -- the parts that cannot be checked by looking at a
rendered footprint.

Three things here are worth a test rather than an eyeball:

  * WHICH corners get filleted. A router bit cannot cut into a corner the VOID
    is convex at, and can cut around one the MATERIAL is convex at. The rule is
    the same in both cases -- "fillet the corners convex to the void" -- but it
    reverses between an outer loop (which encloses the void) and a hole loop
    (which encloses an island of board standing inside it), so an off-by-one on
    the sense would fillet exactly the wrong half and look plausible.

  * WHICH SIDE of a cut copper lands on. This is the trap the whole feature
    exists to close: KiCad's copper_edge_clearance is a distance rule and is
    indifferent to side, so copper printed on the slug passes DRC and then gets
    routed away. Two of the four ways it goes wrong -- copper strictly inside
    the void, and copper covering a cut entirely -- cannot be produced from a
    label raster at all, because tones are exclusive per pixel and a mark
    inside a cut region traces as a hole in it. They are reachable through the
    library API, so they are tested through the library API.

  * That a T8 window opens BOTH faces. Mask left on either side kills it, and
    a footprint that opens only F.Mask looks completely fine in the editor.
"""

import math
import pathlib
import sys

import numpy as np

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))

import emit_art as E  # noqa: E402


# --- helpers ---------------------------------------------------------------

def _rect(px0, py0, px1, py1, shape=(80, 80)):
    m = np.zeros(shape, dtype=bool)
    m[py0:py1, px0:px1] = True
    return m


def _loops(mask, mmpp=0.25):
    return E._tone_loops(mask, mmpp, 0.0, 0.0, 0.02, 0.0)


def _square(x0, y0, x1, y1):
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)


def _sharp_corner_count(loop, limit_deg=120.0):
    """The same measure verify_art.check_min_feature applies to Edge.Cuts."""
    n, out = len(loop), 0
    for i in range(n):
        a, b, c = loop[(i - 1) % n], loop[i], loop[(i + 1) % n]
        v1, v2 = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cos)) < limit_deg:
            out += 1
    return out


# --- fillet sense ----------------------------------------------------------

def test_square_void_rounds_all_four_corners_and_loses_area():
    """A square hole: every corner is convex to the void, so the bit rounds all
    four and the void gets SMALLER by four corner-minus-quadrant slivers."""
    o, b, _ = _loops(_rect(20, 20, 60, 60))
    regions, st = E.build_cut_regions(o, b, 0.8, 0.0, 0.02, simplify_mm=0.1875)
    assert st["filleted"] == 4, st
    assert st["islands"] == 0
    before, after = abs(E.signed_area(o[0][0])), abs(E.signed_area(regions[0][0]))
    assert after < before
    # 4 x (r^2 - pi r^2 / 4), plus whatever the pre-fillet simplification took.
    assert (before - after) >= 4 * (0.64 - math.pi * 0.64 / 4) - 1e-6
    assert _sharp_corner_count(regions[0][0]) == 0


def test_material_convex_corners_are_left_sharp_by_default():
    """A plus-shaped void has 8 corners convex to the void and 4 reflex ones at
    the tips of the material poking into it. Only the first 8 are uncuttable;
    the doc is explicit that the bit cuts around the others, so they stay."""
    m = np.zeros((80, 80), dtype=bool)
    m[32:48, 16:64] = True
    m[16:64, 32:48] = True
    o, b, _ = _loops(m)
    _, st = E.build_cut_regions(o, b, 0.8, 0.0, 0.02, simplify_mm=0.1875)
    assert st["filleted"] == 8, st
    assert st["outer_filleted"] == 0
    # ...and --cut-outer-fillet-mm is what rounds the other four.
    _, st2 = E.build_cut_regions(o, b, 0.8, 0.8, 0.02, simplify_mm=0.1875)
    assert (st2["filleted"], st2["outer_filleted"]) == (8, 4), st2


def test_island_fillet_reverses_sense_and_adds_material():
    """A plus-shaped island of board standing inside a void. Its four CONCAVE
    corners are the ones the void is convex at, so those are the ones the bit
    cannot reach -- and rounding them takes the void's point off, which ADDS
    material to the island. Its eight convex corners are cut around and stay.

    Measured on the loop alone so the pre-fillet simplification, which shrinks
    every loop slightly, cannot be mistaken for the fillet's own effect.
    """
    plus = np.array([[-1, -3], [1, -3], [1, -1], [3, -1], [3, 1], [1, 1],
                     [1, 3], [-1, 3], [-1, 1], [-3, 1], [-3, -1], [-1, -1]],
                    dtype=float)
    rounded, n, reduced = E.fillet_loop(plus, 0.8, False, sagitta_tol=0.01)
    assert n == 4, n                       # only the four concave corners
    assert not reduced
    assert abs(E.signed_area(rounded)) > abs(E.signed_area(plus))
    assert _sharp_corner_count(rounded) == 8     # the eight points survive

    # ...and the same sense comes out of the raster path: 4 corners on the
    # square outer plus 4 on the plus-shaped island it contains.
    m = np.zeros((100, 100), dtype=bool)
    m[15:85, 15:85] = True
    m[45:55, 25:75] = False
    m[25:75, 45:55] = False
    o, b, _ = _loops(m)
    assert len(o) == 1 and len(b[0]) == 1
    regions, st = E.build_cut_regions(o, b, 0.8, 0.0, 0.02, simplify_mm=0.1875)
    assert st["islands"] == 1
    assert st["filleted"] == 8, st
    assert _sharp_corner_count(regions[0][1][0]) == 8


def test_fillet_radius_is_reduced_not_overrun_and_says_so():
    """An edge too short to carry the arc gets a smaller radius -- the only
    alternative is an arc that overshoots its neighbour and self-intersects --
    and every reduction is reported so nothing is clamped in silence."""
    loop = _square(0.0, 0.0, 1.0, 1.0)
    _, n, reduced = E.fillet_loop(loop, 0.8, True, sagitta_tol=0.01)
    assert n == 4
    assert len(reduced) == 4
    assert max(reduced) < 0.8


def test_flat_corners_are_not_filleted():
    """A corner whose arc would depart from it by less than the coordinate
    tolerance does not earn eight vertices."""
    loop = np.array([[0, 0], [10, 0], [20, 0.05], [20, 10], [0, 10]], float)
    _, n, _ = E.fillet_loop(loop, 0.8, True, sagitta_tol=0.05)
    assert n < 5


# --- which side of the cut -------------------------------------------------

def _region_square(x0, y0, x1, y1, islands=()):
    return [(_square(x0, y0, x1, y1), [_square(*i) for i in islands])]


def test_copper_strictly_inside_the_void_is_waste():
    regions = _region_square(-10, -10, 10, 10)
    cu = [("T2", "F.Cu", _square(-2, -2, 2, 2))]
    rep = E.audit_copper_vs_cut(cu, regions, 0.5)
    assert len(rep["waste"]) == 1
    assert "INSIDE the cut" in rep["waste"][0]["why"]
    assert not rep["close"]


def test_copper_covering_the_whole_cut_is_waste():
    """Every copper vertex is outside the cut and the gap is large, so both a
    vertex test and a distance test would pass it. The pour still covers the
    slug."""
    regions = _region_square(-2, -2, 2, 2)
    cu = [("T2", "F.Cu", _square(-20, -20, 20, 20))]
    rep = E.audit_copper_vs_cut(cu, regions, 0.5)
    assert len(rep["waste"]) == 1
    assert "COVERS" in rep["waste"][0]["why"]


def test_copper_straddling_the_cut_line_is_waste():
    regions = _region_square(-10, -10, 10, 10)
    cu = [("T2", "F.Cu", _square(8, -2, 14, 2))]
    rep = E.audit_copper_vs_cut(cu, regions, 0.5)
    assert len(rep["waste"]) == 1
    assert "STRADDLES" in rep["waste"][0]["why"]


def test_copper_on_an_enclosed_island_is_waste():
    """Not the slug, but nothing holds the island either."""
    regions = _region_square(-10, -10, 10, 10, islands=[(-3, -3, 3, 3)])
    cu = [("T2", "F.Cu", _square(-1, -1, 1, 1))]
    rep = E.audit_copper_vs_cut(cu, regions, 0.5)
    assert len(rep["waste"]) == 1
    assert "ISLAND" in rep["waste"][0]["why"]


def test_copper_on_the_keep_side_inside_the_board_rule_is_close_not_waste():
    regions = _region_square(-10, -10, 10, 10)
    cu = [("T2", "F.Cu", _square(10.2, -2, 14, 2))]
    rep = E.audit_copper_vs_cut(cu, regions, 0.5)
    assert not rep["waste"]
    assert len(rep["close"]) == 1
    assert abs(rep["close"][0]["gap_mm"] - 0.2) < 1e-6


def test_copper_clear_of_the_cut_is_clean():
    regions = _region_square(-10, -10, 10, 10)
    cu = [("T2", "F.Cu", _square(12, -2, 16, 2))]
    rep = E.audit_copper_vs_cut(cu, regions, 0.5)
    assert not rep["waste"] and not rep["close"]
    assert rep["skipped_far"] == 1        # bbox prune, never even measured


def test_buried_copper_counts_too():
    """The board's copper-to-edge rule is not front-only, and an In1 mark on a
    routed-away slug is lost just as surely as a front one."""
    regions = _region_square(-10, -10, 10, 10)
    cu = [("T7", "In1.Cu", _square(-2, -2, 2, 2))]
    rep = E.audit_copper_vs_cut(cu, regions, 0.5)
    assert len(rep["waste"]) == 1
    assert rep["waste"][0]["layer"] == "In1.Cu"


# --- end to end ------------------------------------------------------------

def _demo_labels():
    """T5 ground, a T1 silk bar, T2 copper well clear, a T3 window, a T4 cut."""
    names = [t[0] for t in E.TONES]
    idx = {n: i for i, n in enumerate(names)}
    L = np.full((80, 80), idx["T5"], dtype=np.int64)
    L[4:10, 8:72] = idx["T1"]
    L[60:70, 12:22] = idx["T2"]
    L[12:32, 8:22] = idx["T3"]
    L[24:56, 28:52] = idx["T4"]
    return L, names


def test_window_opens_both_faces_and_marks_a_keepout():
    L, names = _demo_labels()
    text, rep = E.emit_detailed(L, names, 40.0, "t_win", window_tone="T3")
    assert rep["t8"]["mask_layers"] == ["F.Mask", "B.Mask"]
    assert text.count('(layer "F.Mask")') >= 1
    assert text.count('(layer "B.Mask")') >= 1
    # One aperture per face, same shape.
    row = next(r for r in rep["tones"] if r["tone"] == "T3")
    assert row["mode"] == "T8 window"
    assert '(layer "Dwgs.User")' in text
    assert rep["t8"]["keepout_segs"] > 0
    assert any("BOARD-LEVEL rule area" in w for w in rep["warnings"])
    assert any("BOTH faces" in w for w in rep["warnings"])


def test_cut_emits_edge_cuts_line_loops_and_warns_it_is_unconditional():
    L, names = _demo_labels()
    text, rep = E.emit_detailed(L, names, 40.0, "t_cut", cut_tone="T4")
    assert '(layer "Edge.Cuts")' in text
    # Strokes, not fills: a board outline is a path the router follows.
    assert '(fill solid) (layer "Edge.Cuts")' not in text
    assert rep["t9"]["polys"] == 1
    assert rep["t9"]["filleted"] == 4
    assert any("UNCONDITIONAL" in w for w in rep["warnings"])
    # ...and an extent, so a lone cut loop is not mistaken for a board outline.
    assert '(layer "F.CrtYd")' in text
    assert rep["courtyard_mm"]


def test_cut_and_window_cannot_be_the_same_tone():
    L, names = _demo_labels()
    try:
        E.emit_detailed(L, names, 40.0, "t_x", window_tone="T3", cut_tone="T3")
    except ValueError as e:
        assert "cannot be both" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_copper_inside_a_cut_is_a_hard_failure_by_default():
    L, names = _demo_labels()
    idx = {n: i for i, n in enumerate(names)}
    L[34:44, 34:44] = idx["T2"]           # ENIG on the slug
    try:
        E.emit_detailed(L, names, 40.0, "t_trap", cut_tone="T4")
    except E.CopperInWaste as e:
        assert "WASTE SIDE" in str(e)
    else:
        raise AssertionError("copper on the waste side was not caught")
    # ...and the override downgrades it rather than hiding it.
    _, rep = E.emit_detailed(L, names, 40.0, "t_trap", cut_tone="T4",
                             allow_copper_in_cut=True)
    assert any("WASTE SIDE" in w for w in rep["warnings"])


def test_no_cut_or_window_flags_changes_nothing():
    """The structural modes are opt-in; without them the emitter draws exactly
    what it drew before, on palette layers only."""
    L, names = _demo_labels()
    text, rep = E.emit_detailed(L, names, 40.0, "t_plain")
    for layer in ("Edge.Cuts", "Dwgs.User", "F.CrtYd", "B.Mask"):
        assert f'(layer "{layer}")' not in text
    assert rep["t8"] is None and rep["t9"] is None
    assert rep["total_fp_line"] == 0
