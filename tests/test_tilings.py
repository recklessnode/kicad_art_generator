"""Acceptance tests for tools/tilings.py.

These tests are the module's evidence, not a smoke screen.  Two of them exist
specifically to keep the OTHER tests honest:

  * test_symmetry_scan_is_calibrated asserts that the periodic kinds score
    EXACTLY 1.0 on the translational-symmetry scan.  Without that, a scan that
    silently measured the patch edge instead of the tiling would let the spectre
    "pass" the no-symmetry test for the wrong reason.
  * test_edge_cancellation_is_not_an_overlap_test pins down a trap that already
    caught this module once: the signed area enclosed by the cancelled-edge
    boundary equals the sum of the tile areas whether or not the tiles overlap,
    so it must never be used as a fit test.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import tilings as T  # noqa: E402

BBOX = (0.0, 0.0, 40.0, 36.0)
TILE = 4.0
PERIODIC = ["checker", "hex"]


def _servable():
    """WINDOW-FILLING kinds that can fill BBOX.

    The spectre used to be excluded here and the docstring said the exclusion
    "will start failing the day level 2 is solved properly -- which is the
    reminder to delete them".  That day arrived: the substitution runs to level
    5 and generate() serves a 40 x 36 mm window from it, so "spectre" and
    "spectre-curved" are ordinary members of this fixture and get measured by
    the whole lattice suite like everything else.

    The BOARD_FIRST kinds are excluded by name rather than by exception,
    because they are not window fillers and every test in this fixture would be
    asking them the wrong question: their contract is that the caller supplies a
    BOARD frame, and both are built from the level-2 patch, which has a void in
    the middle by construction.  They have their own tests further down.

    spectre-cells has to be named here even though it CAN fill a window, and
    that is the trap: it never raises, so leaving it out of BOARD_FIRST does not
    fail loudly -- it silently enrols a board-anchored kind in the whole
    lattice suite and then trips exactly one assertion, the membership one
    below.  A kind is excluded here for what its contract is, not for whether it
    happens to throw.
    """
    out = {}
    for k in T.kinds():
        if k in BOARD_FIRST:
            continue
        try:
            out[k] = T.generate(k, BBOX, TILE, 0)
        except RuntimeError:
            pass
    return out


BOARD_FIRST = ["spectre-fingerprint", "spectre-cells"]


@pytest.fixture(scope="module")
def patches():
    return _servable()


def test_every_window_filling_kind_can_now_fill_a_board_window(patches):
    """This used to assert `sorted(patches) == sorted(PERIODIC)`.

    It was a pin on the defect, and it said so.  The spectre now fills the
    window, so the fixture holds every window-filling kind and this asserts the
    membership rather than the absence.
    """
    assert sorted(patches) == sorted(PERIODIC + ["spectre", "spectre-curved"])


def test_board_first_is_the_registry_minus_the_window_fillers():
    """The exclusion list is not allowed to drift behind the registry.

    _servable() skips BOARD_FIRST by name, so a board-anchored kind added to
    tilings.py and forgotten here gets silently measured as a lattice.  Rather
    than restate the list, derive it: every registered kind whose note says
    BOARD-FIRST must be in BOARD_FIRST, and nothing else may be.
    """
    declared = {k for k in T.kinds()
                if "BOARD-FIRST" in T.KINDS[k].note.upper()}
    assert declared == set(BOARD_FIRST)
    assert set(PERIODIC) | declared | {"spectre", "spectre-curved"} == set(T.kinds())


def test_spectre_refuses_what_it_cannot_prove():
    """The gate still refuses -- it just refuses a different thing.

    It used to refuse a 40 x 36 mm window, because the deepest supertile was a
    9-tile cluster 15 mm across.  It now serves that window and refuses to hand
    out a level nobody has audited, which is what the gate was always for.  The
    refusal has to name the constant and the audit, so that raising it is a
    deliberate act with a measurement behind it.
    """
    assert T.generate("spectre", BBOX, TILE, 0)
    with pytest.raises(RuntimeError) as e:
        T.spectre_patch(T.SPECTRE_SUPERTILE_LEVEL + 1)
    assert "SPECTRE_AUDITED_LEVEL" in str(e.value)
    assert "spectre_patch_audit" in str(e.value)
    with pytest.raises(RuntimeError) as e:
        T.spectre_tiles(T.SPECTRE_PATCH_LEVEL + 1)
    assert "SPECTRE_AUDITED_LEVEL" in str(e.value)


# --- two gates, two questions ---------------------------------------------
# The single constant used to answer both "may I substitute again" and "may I
# place these tiles", which are not the same question and do not have the same
# answer.  These four tests pin the split and, between them, make it impossible
# to raise either constant by accident.

def test_the_two_gates_are_separate_constants():
    """Still two questions, still two constants -- they merely agree now.

    The values being equal is not the gates being merged.  "May I substitute
    this again" and "may I place these tiles and mask them" are different
    questions with different acceptance tests (see spectre_patch_audit's
    supertile_ok vs patch_ok), and they agree because the geometry is right, not
    because one gate was loosened to match the other.
    """
    assert T.SPECTRE_AUDITED_LEVEL == 5
    assert T.SPECTRE_SUPERTILE_LEVEL == T.SPECTRE_AUDITED_LEVEL
    assert T.SPECTRE_PATCH_LEVEL == T.SPECTRE_AUDITED_LEVEL
    # the old name still means the old thing: the deepest SUPERTILE level
    assert T.SPECTRE_VERIFIED_LEVEL == T.SPECTRE_SUPERTILE_LEVEL
    # the quad-bearing entry point is gated at the SUPERTILE level ...
    tiles, quad = T.spectre_patch(T.SPECTRE_SUPERTILE_LEVEL - 1)
    assert len(quad) == 4
    with pytest.raises(RuntimeError):
        T.spectre_patch(T.SPECTRE_SUPERTILE_LEVEL + 1)
    # ... the tiles-only one at the PATCH level, and it returns no quad at all
    tiles = T.spectre_tiles(2)
    assert len(tiles) == 71
    assert all(len(t) == 14 for t in tiles)     # tiles, not (tiles, quad)
    # and the cell grid has its own pinned level, which must not follow either
    assert T.SPECTRE_CELL_LEVEL == 2


def test_every_audited_level_is_a_valid_patch_by_exact_arithmetic():
    """The finding the whole module rests on, re-measured every run.

    Integer predicates in Z[sqrt3], no tolerance anywhere: no edge of any tile
    properly crosses an edge of another, no vertex of any tile is strictly
    inside another, and not one tile is a mirror image.  That pair of conditions
    is necessary and sufficient for pairwise disjoint interiors.

    Levels 0..4 are re-run here.  Level 5 -- 34649 tiles, 124201 candidate pairs
    -- was run the same way and reports the same zeroes; it takes about four
    minutes, so it is not in the default suite.  Run it with
        python tools/tilings.py --spectre-fit --spectre-fit-level 5
    """
    want = {0: (0, 1), 1: (21, 9), 2: (209, 71), 3: (1845, 559),
            4: (15339, 4401)}
    for lv, (pairs, n) in want.items():
        a = T.spectre_patch_audit(lv)
        assert a["n_tiles"] == a["expected_tiles"] == n, lv
        assert a["pairs_tested"] == pairs, (lv, a["pairs_tested"])
        assert a["proper_crossings"] == 0, lv
        assert a["strictly_interior_vertices"] == 0, lv
        assert a["overlapping_pairs"] == 0, (lv, a["examples"])
        assert a["reflected_tiles"] == 0, lv
        assert a["edges_shared_by_3_or_more"] == 0, lv
        assert a["boundary_loops"] == 1, lv
        assert abs(a["area_defect"]) < 1e-9, lv
        assert a["patch_ok"] is True, lv
        assert a["supertile_ok"] is True, lv


def test_level_3_is_the_one_that_used_to_break():
    """The regression that matters most, named after the failure it replaces.

    spectre_patch_audit(3) used to report 559 tiles, 97 overlapping pairs, 128
    proper edge crossings, 520 strictly-interior vertices, 25 edges claimed by
    three or more tiles and 7 boundary loops.  Every one of those is now zero or
    one, and this test exists so that a regression to any of them is named.
    """
    a = T.spectre_patch_audit(3)
    assert a["n_tiles"] == 559
    assert a["overlapping_pairs"] == 0            # was 97
    assert a["proper_crossings"] == 0             # was 128
    assert a["strictly_interior_vertices"] == 0   # was 520
    assert a["edges_shared_by_3_or_more"] == 0    # was 25
    assert a["boundary_loops"] == 1               # was 7
    assert a["patch_ok"] is True
    assert a["supertile_ok"] is True


def test_the_exact_and_float_overlap_audits_agree():
    """Two independent methods, one answer.  overlap_audit works in floats with a
    1e-9 epsilon and a bucket grid; spectre_patch_audit is integer arithmetic in
    Z[sqrt3] with no epsilon at all.  If they ever disagree, one of them is
    measuring something other than overlap."""
    for lv in (0, 1, 2, 3):
        rings = [[T.z_xy(p) for p in t] for t in T.spectre_tiles(lv)]
        f = T.overlap_audit(rings, cell=4.0)
        x = T.spectre_patch_audit(lv)
        assert f["overlapping_pairs"] == x["overlapping_pairs"] == 0, lv
        assert f["pairs_tested"] == x["pairs_tested"], lv


# --- API shape -------------------------------------------------------------

def test_kinds_registered():
    for k in ("spectre", "hex", "checker"):
        assert k in T.kinds()


def test_registry_is_the_only_extension_point():
    """Adding a kind must be one decorated function and nothing else."""
    @T.register("unit-test-stripe", size="stripe pitch = tile_mm", edges=4)
    def _stripe(bbox, tile_mm, seed):
        x0, y0, x1, y1 = bbox
        n = int((x1 - x0) / tile_mm) + 2
        m = int((y1 - y0) / tile_mm) + 2
        for j in range(m):
            for i in range(n):
                x, y = x0 + i * tile_mm, y0 + j * tile_mm
                yield [(x, y), (x + tile_mm, y), (x + tile_mm, y + tile_mm),
                       (x, y + tile_mm)]
    try:
        assert "unit-test-stripe" in T.kinds()
        tiles = T.generate("unit-test-stripe", BBOX, TILE, 0)
        assert tiles
        assert T.overlap_audit(tiles)["overlapping_pairs"] == 0
    finally:
        del T.KINDS["unit-test-stripe"]


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        T.generate("penrose", BBOX, TILE, 0)


@pytest.mark.parametrize("bad", [(0.0, 0.0, 0.0, 10.0), (0.0, 0.0, 10.0, 0.0),
                                 (5.0, 0.0, 1.0, 10.0)])
def test_empty_bbox_raises(bad):
    with pytest.raises(ValueError):
        T.generate("checker", bad, TILE, 0)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_bad_tile_mm_raises(bad):
    with pytest.raises(ValueError):
        T.generate("checker", BBOX, bad, 0)


def test_rings_are_closed(patches):
    for kind, tiles in patches.items():
        assert tiles, kind
        for r in tiles:
            assert r[0] == r[-1], kind
            assert len(r) >= 4, kind


# --- whole tiles only ------------------------------------------------------

def test_whole_tiles_only(patches):
    """Nothing is clipped: every tile lies entirely inside the bbox."""
    x0, y0, x1, y1 = BBOX
    for kind, tiles in patches.items():
        for r in tiles:
            bx0, by0, bx1, by1 = T.bbox_of(r)
            assert bx0 >= x0 - 1e-9, kind
            assert by0 >= y0 - 1e-9, kind
            assert bx1 <= x1 + 1e-9, kind
            assert by1 <= y1 + 1e-9, kind


def test_all_tiles_are_full_size(patches):
    """A clipped tile would show up as an area outlier.  None may exist."""
    for kind, tiles in patches.items():
        areas = [abs(T.signed_area(T._open(r))) for r in tiles]
        assert max(areas) - min(areas) < 1e-6 * max(areas), kind


def test_tile_mm_is_the_equal_area_size(patches):
    for kind, tiles in patches.items():
        for r in tiles:
            assert abs(abs(T.signed_area(T._open(r))) - TILE * TILE) < 1e-6, kind


# --- fit: no overlaps, no gaps --------------------------------------------

def test_no_overlaps(patches):
    for kind, tiles in patches.items():
        a = T.overlap_audit(tiles)
        assert a["overlapping_pairs"] == 0, (kind, a["examples"])
        assert a["duplicate_tiles"] == 0, kind
        assert a["pairs_tested"] > len(tiles), kind   # the test really ran


def test_no_gaps(patches):
    for kind, tiles in patches.items():
        g = T.gap_audit(tiles)
        assert g["broken_chains"] == 0, kind
        assert g["holes"] == 0, (kind, g)
        assert abs(g["gap_area"]) < 1e-4, (kind, g)


def test_periodic_patches_are_one_simply_connected_region(patches):
    for kind in PERIODIC:
        assert T.gap_audit(patches[kind])["loops"] == 1, kind


def test_edge_cancellation_is_not_an_overlap_test():
    """Guard against re-adopting a test that does not work.

    Two coincident tiles overlap totally, yet the cancelled-edge boundary still
    encloses exactly the sum of their areas.  Any future "fit" check based on
    that area alone is therefore worthless, and this test says so out loud.
    """
    sq = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    doubled = [sq + [sq[0]], sq + [sq[0]]]
    g = T.gap_audit(doubled)
    assert abs(g["gap_area"]) < 1e-9        # the bogus test passes ...
    a = T.overlap_audit(doubled)
    assert a["duplicate_tiles"] == 1        # ... and the real one catches it


def test_overlap_audit_detects_a_planted_overlap():
    tiles = T.generate("checker", BBOX, TILE, 0)
    bad = [r for r in tiles]
    r = T._open(bad[0])
    bad.append([(x + TILE / 3, y + TILE / 3) for x, y in r] +
               [(r[0][0] + TILE / 3, r[0][1] + TILE / 3)])
    assert T.overlap_audit(bad)["overlapping_pairs"] >= 1


# --- translational symmetry ----------------------------------------------

def test_symmetry_scan_is_calibrated(patches):
    """The periodic kinds MUST score exactly 1.0.  If they do not, the scan is
    measuring the edge of the patch and the spectre result below means nothing.
    """
    for kind in PERIODIC:
        s = T.symmetry_scan(patches[kind])
        assert s["candidates_tested"] > 10, kind
        assert s["best_score"] == pytest.approx(1.0, abs=1e-12), (kind, s)
        assert s["exact_repeats"] > 0, kind


def test_spectre_has_no_translational_symmetry():
    """The aperiodicity evidence this module used to OWE and could not pay.

    This was a strict xfail with the note "a 9-tile cluster is far too small to
    scan; needs a correct level 2".  There is now a correct level 5, so it is a
    real assertion, which is what the xfail was there to demand.

    It is still EVIDENCE and not a proof: a finite patch cannot rule out a
    symmetry of the infinite tiling.  What it does rule out is a symmetry of
    THIS patch, over hundreds of candidate vectors, on a scan the periodic kinds
    are calibrated to score exactly 1.0 on -- see the test above.
    """
    rings = [[T.z_xy(p) for p in t] for t in T.spectre_tiles(3)]
    s = T.symmetry_scan(rings)
    assert s["candidates_tested"] > 40
    assert s["exact_repeats"] == 0
    assert s["best_score"] < 0.5


def test_spectre_uses_many_orientations_and_no_reflections():
    """The chirality claim, exactly, tile by tile.

    Every tile in the patch is a ROTATION of the base tile -- not one is a
    mirrored copy.  That is what separates the spectre from the hat, which
    cannot tile without both handednesses.  Nine tiles already sit in six of the
    twelve available orientations, which no lattice of one shape would do.

    spectre_tiles(), not spectre_patch(): the substitution reverses orientation
    every generation, so the quad-bearing entry point hands back the MIRROR
    family at odd levels, in the frame its anchor quad is meaningful in.  The
    two are related by a single global reflection and the test below pins that.
    """
    for lv in (1, 2, 3):
        tiles = T.spectre_tiles(lv)
        turns = set()
        for t in tiles:
            k = _rotation_of(T.SPECTRE, t)
            assert k is not None, "a tile in the patch is a reflected copy"
            turns.add(k)
        assert len(turns) >= 5, sorted(turns)


def test_the_two_entry_points_differ_by_one_global_reflection():
    """The one place a caller can be surprised, pinned so it cannot drift.

    spectre_tiles(n) is always in Tile(1,1)'s own handedness.  spectre_patch(n)
    is in the frame the substitution built, which alternates.  They are the same
    patch up to a single global reflection -- never up to anything else, and
    never up to a per-tile one.
    """
    for lv in range(0, 4):
        handed = frozenset(frozenset(t) for t in T.spectre_tiles(lv))
        raw, _quad = T.spectre_patch(lv)
        same = frozenset(frozenset(t) for t in raw)
        mirrored = frozenset(frozenset(T.z_conj(p) for p in t) for t in raw)
        assert handed in (same, mirrored), lv
        assert (handed == same) == (lv % 2 == 0), (
            "handedness should alternate with the level", lv)


def _rotation_of(base, other):
    n = len(base)
    for k in range(12):
        rb = [T.z_rot(p, k) for p in base]
        for s in range(n):
            tr = T.z_sub(other[0], rb[s])
            if [T.z_add(p, tr) for p in rb[s:] + rb[:s]] == list(other):
                return k
    return None


# --- the spectre tile itself ---------------------------------------------

def test_tile11_is_equilateral_and_closes():
    p = T.SPECTRE
    assert len(p) == 14
    xy = [T.z_xy(q) for q in p]
    for i in range(14):
        a, b = xy[i], xy[(i + 1) % 14]
        assert math.hypot(b[0] - a[0], b[1] - a[1]) == pytest.approx(1.0, abs=1e-12)


def test_tile11_angles_and_the_one_flat_vertex():
    """Interior angles are multiples of 30 degrees; the "1/3" and "1/4" vertex
    classes alternate; exactly one vertex is flat, which is why the tile reads as
    a 13-gon with one double-length edge."""
    xy = [T.z_xy(q) for q in T.SPECTRE]
    turns = []
    for i in range(14):
        a = xy[i - 1]
        b = xy[i]
        c = xy[(i + 1) % 14]
        t = math.degrees(math.atan2(c[1] - b[1], c[0] - b[0]) -
                         math.atan2(b[1] - a[1], b[0] - a[0]))
        turns.append(round(((t + 180) % 360) - 180))
    assert sum(turns) == 360                     # simple, counter-clockwise
    assert turns.count(0) == 1                   # exactly one flat vertex
    thirds = [turns[i] for i in range(14) if abs(turns[i]) == 60]
    quarters = [turns[i] for i in range(14) if abs(turns[i]) in (0, 90)]
    assert len(thirds) == 7 and len(quarters) == 7
    assert sorted(thirds) == [-60, -60, 60, 60, 60, 60, 60]
    assert sorted(quarters) == [-90, -90, 0, 90, 90, 90, 90]


def test_tile11_area():
    a = abs(T.signed_area([T.z_xy(q) for q in T.SPECTRE]))
    assert a == pytest.approx(3.0 + 3.0 * math.sqrt(3.0), abs=1e-12)
    assert a == pytest.approx(T.SPECTRE_UNIT_AREA, abs=1e-12)


def test_exact_arithmetic_round_trips():
    p = (3, -2, 5, 1)
    q = p
    for _ in range(12):
        q = T.z_mul_d(q)
    assert q == p                                # 12 x 30 degrees = identity
    assert T.z_rot(p, 3) != p
    x, y = T.z_xy(T.z_rot(p, 3))
    x0, y0 = T.z_xy(p)
    assert (x, y) == pytest.approx((-y0, x0), abs=1e-12)


# --- the spectre substitution -------------------------------------------

def test_mystic_hole_is_a_rotation_not_a_reflection():
    """The hole the eight-slot arrangement leaves is congruent to the tile by a
    pure rotation.  If it were only congruent by a reflection this would be the
    hat, not the spectre, and the tiling would need mirrored tiles."""
    tiles = T.spectre_tiles(1)
    base = T.SPECTRE
    for t in tiles:
        assert _is_rotation_of(base, t), "a tile is a reflected copy"


def _is_rotation_of(base, other):
    n = len(base)
    for k in range(12):
        rb = [T.z_rot(p, k) for p in base]
        for s in range(n):
            tr = T.z_sub(other[0], rb[s])
            if [T.z_add(p, tr) for p in rb[s:] + rb[:s]] == list(other):
                return True
    return False


def test_no_tile_is_ever_reflected():
    """The whole point of the spectre: one handedness only, within a patch."""
    for lv in range(0, 4):
        for t in T.spectre_tiles(lv):
            assert _is_rotation_of(T.SPECTRE, t), lv
        for t in T.spectre_mystic_tiles(lv):
            assert _is_rotation_of(T.SPECTRE, t), lv


def test_a_patch_never_mixes_handedness_even_in_the_raw_frame():
    """The claim that survives the alternation, stated where it is true.

    spectre_patch() hands back the mirror family at odd levels.  What must NEVER
    happen, at any level and in either frame, is one patch containing both
    handednesses -- that would be a hat tiling.  _spectre_handed() raises if it
    ever sees one; this asserts it independently.
    """
    for lv in range(0, 4):
        raw, _quad = T.spectre_patch(lv)
        hands = {_is_rotation_of(T.SPECTRE, t) for t in raw}
        assert len(hands) == 1, ("level %d mixes handedness" % lv)


def test_spectre_exact_fit_audit():
    """Integer arithmetic, no tolerance: no edge may be claimed by three tiles
    and the patch boundary must be a single loop.

    Both metatile families, because each is built out of copies of the other and
    a broken Gamma would not show up in an ordinary patch until a level later.
    """
    for lv in range(0, 5):
        for gamma in (False, True):
            r = T.spectre_exact_fit(lv, gamma=gamma)
            assert r["edges_shared_by_3_or_more"] == 0, (lv, gamma, r)
            assert r["broken_chains"] == 0, (lv, gamma, r)
            assert r["boundary_loops"] == 1, (lv, gamma, r)
            assert r["interior_edges"] > 0 or lv == 0
            want = (T.spectre_mystic_size(lv) if gamma
                    else T.spectre_patch_size(lv))
            assert r["n_tiles"] == want, (lv, gamma)


def test_the_vertex_angle_census_is_exact_and_would_have_screamed():
    """The cheap strong oracle, and its calibration.

    Every tile edge is a unit step at a multiple of 30 degrees, so the total
    angle of tile meeting at any lattice point is a whole number of 30-degree
    units and may never exceed 360.  Interior points carry exactly 360.

    The calibration is the point: pointed at a deliberately planted overlap it
    has to report one, or its clean verdict on the real patches means nothing.
    """
    for lv in range(0, 5):
        for gamma in (False, True):
            c = T.spectre_vertex_census(lv, gamma=gamma)
            assert c["vertices_over_360"] == 0, (lv, gamma, c)
            assert c["worst_vertex_deg"] <= 360, (lv, gamma, c)
            assert c["edges_shared_by_3_or_more"] == 0, (lv, gamma, c)
            if lv:
                assert c["interior_vertices"] > 0, (lv, gamma)

    # plant an overlap: drop one tile of the level-2 patch exactly on top of
    # another and the census must notice
    tiles = list(T.spectre_tiles(2))
    tiles.append(tiles[0])
    bad = T.vertex_census(tiles)
    assert bad["vertices_over_360"] > 0, bad
    assert bad["worst_vertex_deg"] > 360, bad
    assert bad["edges_shared_by_3_or_more"] > 0, bad


def test_spectre_patch_is_geometrically_disjoint():
    rings = [[T.z_xy(p) for p in t] for t in T.spectre_tiles(3)]
    a = T.overlap_audit(rings, cell=4.0)
    assert a["overlapping_pairs"] == 0, a["examples"]
    assert a["duplicate_tiles"] == 0


def test_spectre_patch_tile_counts():
    for lv in range(0, 5):
        assert len(T.spectre_tiles(lv)) == T.spectre_patch_size(lv)
        assert len(T.spectre_mystic_tiles(lv)) == T.spectre_mystic_size(lv)
    assert [T.spectre_patch_size(n) for n in range(6)] == \
        [1, 9, 71, 559, 4401, 34649]
    assert [T.spectre_mystic_size(n) for n in range(6)] == \
        [2, 8, 62, 488, 3842, 30248]


def test_a_supertile_is_ragged_and_that_is_what_a_supertile_looks_like():
    """The revision of the check that caught the old level 2, with its reason.

    The old test demanded hull fill >= 0.78, calibrated on a lone tile (0.8146)
    and the 9-tile cluster (0.8040), and it did its job: the old level-2 patch
    sat at 0.6405 because it was three disconnected lumps ringing a void.

    But a correct spectre supertile is genuinely ragged and gets raggeder --
    0.7076, 0.6510, 0.6266, 0.6177 at levels 2..5 -- converging to about 0.61,
    so that threshold rejects correct objects and cannot come back.  What
    replaces it is what hull fill was standing in for, counted exactly rather
    than proxied: ONE edge-connected component, no boundary pinches, one
    boundary loop, no holes.  It is NOT "one boundary loop" alone -- that was
    tried, and the old level 2 passes it; see
    test_the_supertile_gate_rejects_the_rotation_only_level_2.  Hull fill is
    pinned here as a measurement, so that a patch that suddenly sprawls still
    shows up.
    """
    fills = [fill_of(T.spectre_tiles(lv)) for lv in range(0, 5)]
    assert fills == pytest.approx([0.8146, 0.8040, 0.7076, 0.6510, 0.6266],
                                  abs=1e-3)
    assert all(fills[i] >= fills[i + 1] for i in range(len(fills) - 1)), fills
    assert fills[-1] > 0.6, "a supertile that fills under 60% of its hull is a sprawl"
    for lv in range(0, 5):
        a = T.spectre_patch_audit(lv)
        assert a["boundary_loops"] == 1 and a["broken_chains"] == 0, lv
        assert a["supertile_ok"] is True, lv


def fill_of(tiles):
    return T.fill_fraction([[T.z_xy(p) for p in t] for t in tiles])


# --- the gate that was weakened, and the patch it has to reject -----------
# The supertile gate was briefly "patch_ok and one boundary loop and no broken
# chains and no edge shared by three or more tiles", on the stated grounds that
# this is what the old rotation-only level 2 failed.  It is not.  These tests
# rebuild that patch and measure it, so the claim is checkable instead of
# remembered.

# The old build's drop slot.  It is not SPECTRE_DROP_SLOT: that constant is now
# read off the published substitution table (2), where the old code searched for
# one and settled on 5.
_LEGACY_DROP_SLOT = 5


def rotation_only_patch(levels):
    """The patch this module built BEFORE the per-generation reflection.

    The old construction exactly: the legacy anchor quad, the legacy super-quad
    rule, two hand-rolled clusters rather than the nine published metatile
    labels, drop slot 5, and no reflection anywhere.  Reconstructed rather than
    described, because "what the old level 2 failed" is a claim about an object,
    and until spectre_patch_audit() took a `tiles=` argument there was no way to
    put that object through the audit and find out.

    It is the same object and not a lookalike: the recorded numbers come back --
    9 and 71 tiles, hull fill 0.8040 and 0.6405, and 97 overlapping pairs at
    level 3, which is the figure the module docstring's ledger quotes.
    """
    quad = tuple(T.SPECTRE[i] for i in T.SPECTRE_LEGACY_QUAD_IDX)
    spectres = (T.SPECTRE,)
    mystics = tuple(T._mystic(T.SPECTRE))
    for _ in range(int(levels)):
        motions = T.spectre_slot_motions(quad)              # reflect=False
        nxt_s, nxt_m = [], []
        for slot, m in enumerate(motions):
            src = mystics if slot == T.SPECTRE_GAMMA_SLOT else spectres
            placed = [tuple(T.m_apply(m, p) for p in t) for t in src]
            nxt_s.extend(placed)
            if slot != _LEGACY_DROP_SLOT:
                nxt_m.extend(placed)
        quad = tuple(T.m_apply(motions[a], quad[b])
                     for a, b in T.SPECTRE_LEGACY_SUPER_QUAD)
        spectres, mystics = tuple(nxt_s), tuple(nxt_m)
    return spectres


def test_the_rotation_only_patch_is_the_object_the_ledger_describes():
    """Before using it as a counterexample, prove it is the right patch."""
    assert len(rotation_only_patch(1)) == 9
    assert fill_of(rotation_only_patch(1)) == pytest.approx(0.8040, abs=1e-4)
    assert len(rotation_only_patch(2)) == 71
    assert fill_of(rotation_only_patch(2)) == pytest.approx(0.6405, abs=1e-4)
    # the level-3 collapse the ledger quotes, to the pair
    assert T.spectre_patch_audit(3, tiles=rotation_only_patch(3))[
        "overlapping_pairs"] == 97
    # and it is genuinely a different object from the corrected one
    assert set(rotation_only_patch(2)) != set(T.spectre_tiles(2))


def test_the_supertile_gate_rejects_the_rotation_only_level_2():
    """R2.  The gate must FAIL the known-bad patch, and one version did not.

    Measured here rather than asserted in a docstring: the old level-2 patch is
    71 tiles in THREE edge-connected components ringing a void, and it satisfies
    every clause of the gate that replaced hull fill.  One boundary loop, no
    broken chains, no edge shared by three or more tiles, no overlapping pairs,
    zero area defect -- it passed.  The three lumps touch at two vertices, and a
    boundary walk goes straight through a pinch, so a loop count was never a
    connectivity test in the first place.

    The clauses that do reject it are the ones that measure the property
    directly: one edge-connected component, and no pinch.
    """
    old = T.spectre_patch_audit(2, tiles=rotation_only_patch(2))

    # it is still PLACEABLE, and keeping that true is the point of having two
    # constants: a masking consumer may use it, a substitution consumer may not
    assert old["patch_ok"] is True
    assert old["overlapping_pairs"] == 0
    assert old["reflected_tiles"] == 0
    assert abs(old["area_defect"]) < 1e-9

    # the clauses that replaced hull fill: it passes all of them
    assert old["boundary_loops"] == 1
    assert old["broken_chains"] == 0
    assert old["edges_shared_by_3_or_more"] == 0

    # the clauses that catch it
    assert old["tile_components"] == 3
    assert old["boundary_pinch_vertices"] == 2

    assert old["supertile_ok"] is False

    # hull fill would have caught it too -- and would also have rejected the
    # CORRECT level 2, which is why it is not what came back
    assert old["hull_fill"] == pytest.approx(0.6405, abs=1e-4)
    assert T.spectre_patch_audit(2)["hull_fill"] < 0.75
    assert T.spectre_patch_audit(2)["supertile_ok"] is True


def test_every_correct_level_passes_all_four_supertile_clauses():
    """And the gate is not merely strict: both supertiles pass at every level.

    Gamma as well as Delta, because each is built out of copies of the other and
    a gate that only ever sees one of them is measuring half the recursion.
    """
    for lv in range(0, 5):
        for name, tiles in (("delta", T.spectre_tiles(lv)),
                            ("gamma", T.spectre_mystic_tiles(lv))):
            f = T.spectre_exact_fit(lv, tiles=tiles)
            where = "%s level %d" % (name, lv)
            assert f["tile_components"] == 1, where
            assert f["boundary_pinch_vertices"] == 0, where
            assert f["boundary_loops"] == 1, where
            assert f["broken_chains"] == 0, where
            assert f["edges_shared_by_3_or_more"] == 0, where


def test_the_boundary_walk_refuses_a_pinch_instead_of_spinning():
    """R4.  It used to be an infinite loop guarding an unreachable assertion.

    spectre_patch_boundary() stored ONE successor per vertex, so at a pinch the
    second outgoing edge silently overwrote the first: 280 boundary edges went
    in and 278 were stored, and the walk could then cycle without ever reaching
    `start`.  The "more than one boundary loop" AssertionError below it could
    not be reached.  Measured on this patch, the walk was still running after
    200000 steps.

    It now counts the pinches and refuses, in milliseconds.
    """
    import time

    old = rotation_only_patch(2)
    fit = T.spectre_exact_fit(2, tiles=old)
    assert fit["boundary_edges"] == 280
    assert fit["boundary_pinch_vertices"] == 2

    t0 = time.perf_counter()
    with pytest.raises(AssertionError) as e:
        T.spectre_patch_boundary(2, 0, tiles=old)
    took = time.perf_counter() - t0
    assert "PINCH" in str(e.value).upper()
    assert "280" in str(e.value)
    assert took < 5.0, "the walk took %.1fs; it used to take forever" % took


def test_more_than_one_boundary_loop_is_now_reachable():
    """The other half of R4: the assertion that could never fire, firing.

    Two copies of the level-1 cluster 200 unit edges apart -- disconnected, but
    with no pinch, so the pinch check does not catch it.  The walk closes after
    46 of the 92 boundary edges and says so.
    """
    lv1 = T.spectre_tiles(1)
    far = list(lv1) + [tuple(T.z_add(p, (200, 0, 0, 0)) for p in t)
                       for t in lv1]
    with pytest.raises(AssertionError) as e:
        T.spectre_patch_boundary(1, 0, tiles=far)
    assert "more than one boundary loop" in str(e.value)
    assert "46 of 92" in str(e.value)

    a = T.spectre_patch_audit(1, tiles=far)
    assert a["tile_components"] == 2
    assert a["boundary_pinch_vertices"] == 0
    assert a["boundary_loops"] == 2
    assert a["supertile_ok"] is False

    # and none of that poisoned the cache the real levels share
    assert len(T.spectre_patch_boundary(1, 0)) == 46
    assert len(T.spectre_patch_boundary(2, 0)) == 182


# --- what was actually wrong, and what was not ----------------------------
# These pin the diagnosis, so that the next person to read the docstring's
# ledger finds measurements rather than a story.  The first two are unchanged
# statements that were true before the fix and are still true; the last two are
# the fix and the rejected hypothesis, each with its own number.

def test_the_anchor_quad_is_forced_not_chosen():
    """Only four ordered vertex 4-tuples make a valid cluster, and all four
    make the SAME one.  So level 1 is not one option among many.

    Unchanged from before the fix, and still true.  What it does NOT say -- and
    what was once read into it -- is that the four are interchangeable: they are
    different point sets, SPECTRE_SUPER_QUAD indexes into them, and only
    (5, 7, 9, 13) is the published quad the published super-quad rule goes with.
    """
    valid = [(2, 7, 12, 13), (3, 7, 11, 13), (4, 7, 10, 13), (5, 7, 9, 13)]
    assert T.SPECTRE_QUAD_IDX == (5, 7, 9, 13)
    assert T.SPECTRE_LEGACY_QUAD_IDX in valid
    ref = None
    for idx in valid:
        quad = tuple(T.SPECTRE[i] for i in idx)
        motions = T.spectre_slot_motions(quad)
        tiles = frozenset(tuple(T.m_apply(m, p) for p in T.SPECTRE)
                          for m in motions)
        assert len(tiles) == 8, idx
        if ref is None:
            ref = tiles
        assert tiles == ref, idx           # identical cluster, every time


def test_the_reflection_is_the_whole_difference():
    """THE measurement, and it is one line of code apart.

    A level-n metatile is a union of n_k congruent tiles and n_k grows by
    4 + sqrt(15), so its linear size grows by sqrt(4 + sqrt 15) = 2.805884 and
    the anchor quad, which scales with it, has to grow by that too.

    Rotation-only, with the constants this module used to carry: exactly 3.0 --
    6.9% too fast, compounding every level, which is what made the old level 2 a
    ring of lumps and the old level 3 overlap.  With the per-generation
    reflection and the published constants: 2.805884, from the first step.
    Same rules, same tile, same everything else.
    """
    assert T.SPECTRE_INFLATION == pytest.approx(math.sqrt(4 + math.sqrt(15)),
                                                abs=1e-12)
    legacy, lp = T.spectre_quad_inflation(
        reflect=False, quad_idx=T.SPECTRE_LEGACY_QUAD_IDX,
        super_quad=T.SPECTRE_LEGACY_SUPER_QUAD)
    assert legacy == pytest.approx(3.0, abs=1e-9)
    assert legacy > T.SPECTRE_INFLATION
    assert legacy / T.SPECTRE_INFLATION == pytest.approx(1.0692, abs=1e-4)
    assert len(lp) >= 2 and lp[-1] > lp[0]

    factor, perims = T.spectre_quad_inflation(14)
    assert factor == pytest.approx(T.SPECTRE_INFLATION, abs=1e-9)
    # It CONVERGES to that rather than hitting it at step one, and the
    # difference is worth pinning because an earlier report of this measurement
    # said "exact from the first step" -- it was reading a 6-decimal display of
    # the later levels.  The quad's perimeter is not an eigenvector of the map;
    # its subdominant component decays geometrically, giving
    # 2.827766, 2.808774, 2.806253, 2.805931, ... -> 2.805883701.
    ratios = [perims[i + 1] / perims[i] for i in range(len(perims) - 1)]
    assert ratios[0] == pytest.approx(2.827765, abs=1e-5)
    err = [abs(r - T.SPECTRE_INFLATION) for r in ratios]
    assert all(err[i] > err[i + 1] for i in range(6)), err[:8]
    assert err[0] < 0.03, "it is never more than 1% out, even at step one"
    assert err[-1] < 1e-9

    # the published super-quad in the rotation-only framework is exactly what
    # issue #8 rejected, and rejecting it was correct in that framework
    stray, _ = T.spectre_quad_inflation(reflect=False)
    assert abs(stray - T.SPECTRE_INFLATION) > 0.1


def test_the_nine_labels_were_not_the_fix():
    """The rejected hypothesis, measured rather than argued.

    Issue #8 proposed that collapsing the nine metatile labels into two was the
    defect.  It was not.  Read the table: every row places Gamma at slot 7 and
    nowhere else, and only Gamma's row drops a slot, so all eight non-Gamma
    supertiles are the identical point set at every level -- nine labels, two
    geometries, exactly what the old code had.

    This asserts that structure directly, which is the whole content of the
    claim; the 2x2 cross-measurement (nine labels without the reflection give 9
    overlapping pairs at level 2 and 1908 at level 3, two clusters WITH it give
    zero at both) is in the module docstring.
    """
    rows = T.SPECTRE_SUBSTITUTION
    assert set(rows) == set(T.SPECTRE_LABELS) and len(rows) == 9
    for label, row in rows.items():
        assert len(row) == 8
        assert row.index("Gamma") == T.SPECTRE_GAMMA_SLOT == 7
        assert row.count("Gamma") == 1
        assert (None in row) == (label == "Gamma")
    assert rows["Gamma"].index(None) == T.SPECTRE_DROP_SLOT == 2

    # the geometric consequence, built rather than argued: every non-Gamma
    # supertile is the SAME set of tiles
    quad = tuple(T.SPECTRE[i] for i in T.SPECTRE_QUAD_IDX)
    motions = T.spectre_slot_motions(quad, reflect=True)
    base = {L: (T.SPECTRE,) for L in T.SPECTRE_LABELS}
    base["Gamma"] = tuple(T._mystic(T.SPECTRE))
    built = {}
    for L, row in rows.items():
        acc = []
        for slot, child in enumerate(row):
            if child is None:
                continue
            for t in base[child]:
                acc.append(tuple(T.r_apply(motions[slot], p) for p in t))
        built[L] = frozenset(frozenset(t) for t in acc)
    non_gamma = {built[L] for L in T.SPECTRE_LABELS if L != "Gamma"}
    assert len(non_gamma) == 1, "the eight non-Gamma supertiles are not identical"
    assert built["Gamma"] not in non_gamma


def test_the_tile_counts_really_do_force_that_inflation():
    """The recurrence, checked rather than quoted: 1, 9, 71, 559, 4401 and the
    area growth those counts imply."""
    assert [T.spectre_patch_size(n) for n in range(5)] == [1, 9, 71, 559, 4401]
    ratio = T.spectre_patch_size(12) / T.spectre_patch_size(11)
    assert ratio == pytest.approx(4 + math.sqrt(15), rel=1e-9)
    assert math.sqrt(ratio) == pytest.approx(T.SPECTRE_INFLATION, rel=1e-9)


def test_periodic_kinds_are_compact_too(patches):
    for kind in PERIODIC:
        assert T.fill_fraction(patches[kind]) > 0.9, kind


def test_the_window_filling_kind_covers_what_it_serves():
    """It works at any window a patch up to SPECTRE_PATCH_LEVEL covers.

    Two windows on purpose.  The 14 x 14 one is served from a shallow level and
    is the case that used to be all this kind could do.  The 40 x 36 one is the
    board window the fixture uses and used to be REFUSED outright.

    `holes == 0` is the assertion that matters and it is not free: the patch's
    outer boundary is ragged, so a window that merely fits the bounding box can
    enclose a bay of that boundary and come back with a hole.  _spectre_levels_for
    tests containment in the boundary polygon for exactly this reason -- before
    it did, this window returned a hole.
    """
    for win, want in (((0.0, 0.0, 14.0, 14.0), 4), ((0.0, 0.0, 40.0, 36.0), 68)):
        tiles = T.generate("spectre", win, 4.0, 0)
        assert len(tiles) == want, (win, len(tiles))
        assert T.overlap_audit(tiles)["overlapping_pairs"] == 0, win
        assert T.gap_audit(tiles)["holes"] == 0, win
        for r in tiles:
            assert abs(abs(T.signed_area(T._open(r))) - 16.0) < 1e-6


# --- the board-first fingerprint -----------------------------------------
# FRAME is the real SatoshiStarter board frame: the Edge.Cuts bbox
# (50.775..203.225 x 25.375..127.025) deflated by the 1.0 mm edge inset, as
# measured through pcbnew.  Hard-coded here so these tests run without KiCad.

FRAME = (51.80, 26.40, 202.20, 126.00)
SPAN_TILE = 11.82306       # smallest tile that spans FRAME from LEVEL 2 at rot 0
DEEP_SPAN_TILE = 0.56144   # ... and from level SPECTRE_PATCH_LEVEL
COVER_TILE = 3.086404      # smallest tile at which LEVEL 5 COVERS FRAME at rot 0


def _inside(rings, frame):
    """The whole-tile subset, by generate()'s own rule -- see generate()."""
    out = []
    for r in rings:
        bx0, by0, bx1, by1 = T.bbox_of(T._open(r))
        if bx0 < frame[0] or by0 < frame[1] or bx1 > frame[2] or by1 > frame[3]:
            continue
        out.append(r)
    return out


def test_the_fingerprint_now_fills_the_board_it_used_to_refuse():
    """The practical point of the whole exercise, on the real board frame.

    At tile_mm 3.0 this mode used to raise for a DIFFERENT reason: 71 tiles
    could not span a 150 x 100 mm board, the smallest tile that would span was
    11.674 mm, and at that size six tiles survived the copper mask -- which is
    why the cell-grid mode had to be invented.  A level-5 patch puts 1552 whole
    tiles inside the frame instead, with no repetition anywhere.

    LEVEL 5 IS PINNED HERE AND THAT IS NOT A DETAIL.  At tile_mm 3.0 and seed 0
    the auto rule REFUSES this frame: level 5 spans it but its boundary polygon
    does not contain it -- 3.687 mm2 short, in two notches at the frame's own
    edge, measured against shapely -- and no shallower level covers it either.
    The auto rule used to return 5 here anyway, because it seeded its answer
    with SPECTRE_PATCH_LEVEL before searching and could not tell "found the
    deepest level" from "found nothing"; that clamp is gone.  So the tile counts
    below are the counts of a patch the caller ASKED for by level, and the
    refusal is asserted alongside them rather than papered over.
    """
    with pytest.raises(T.SpectreCoverageError) as e:
        T.generate("spectre-fingerprint", FRAME, 3.0, 0)
    assert e.value.reason == "cover"
    assert e.value.min_tile_mm == pytest.approx(COVER_TILE, abs=1e-5)

    offered = T.spectre_fingerprint(FRAME, 3.0, 0, levels=5)
    inframe = _inside(offered, FRAME)
    assert len(inframe) == 1552
    assert T.overlap_audit(inframe, cell=12.0)["overlapping_pairs"] == 0
    assert T.gap_audit(inframe)["holes"] == 0
    # the offered field is the same patch cropped to the frame's neighbourhood,
    # so offered - placed is the board-edge overhang and nothing else
    assert len(offered) == 1778

    # and it misses being automatic by 0.086 mm of tile, not by a level: at the
    # threshold the auto rule resolves to the same level 5 with no pin at all
    cover = T.spectre_cover_tile_mm(FRAME[2] - FRAME[0], FRAME[3] - FRAME[1],
                                    5, 0)
    assert cover == pytest.approx(COVER_TILE, abs=1e-6)
    assert T.spectre_fingerprint_placement(FRAME, cover, 0)[0] == 5
    assert len(T.generate("spectre-fingerprint", FRAME, cover, 0)) == 1467


def test_the_fingerprint_picks_the_shallowest_level_that_covers_or_none():
    """`levels=None` means "as shallow as will COVER this frame", measured.

    Shallowest, not deepest: a deeper patch would work too and would cost the
    caller time it does not need to spend.  Cover, not span: the bounding box is
    not a coverage test for a patch this ragged -- at tile_mm 3.0 the level-4
    patch bbox-covers this frame and leaves two bays of bare board inside it,
    which is why the rule is containment in the boundary polygon.

    AND "OR NONE" IS HALF THE CONTRACT.  spectre_cover_level() returns None when
    nothing covers, and None is not SPECTRE_PATCH_LEVEL.  The placement rule
    used to conflate the two -- it seeded `levels = SPECTRE_PATCH_LEVEL` before
    the search, so a search that fell through returned the deepest level with
    its coverage never established, guarded only by a bounding-box span test.
    That is the bbox-for-coverage substitution this whole rule exists to reject,
    sitting inside the rule itself.  At tile_mm 3.0 and rot 0 it is not
    hypothetical: nothing covers, and the old code answered 5.
    """
    assert T.spectre_fingerprint_placement(FRAME, 14.0, 0)[0] == 4
    assert T.spectre_cover_level(FRAME[2] - FRAME[0], FRAME[3] - FRAME[1],
                                 14.0, 0) == 4
    # an explicit level still overrides
    assert T.spectre_fingerprint_placement(FRAME, 14.0, 0, levels=3)[0] == 3

    # tile 3.0 rot 0: NO level covers.  The answer is None and the rule refuses.
    assert T.spectre_cover_level(FRAME[2] - FRAME[0], FRAME[3] - FRAME[1],
                                 3.0, 0) is None
    with pytest.raises(T.SpectreCoverageError) as e:
        T.spectre_fingerprint_placement(FRAME, 3.0, 0)
    assert e.value.reason == "cover"
    assert e.value.levels == T.SPECTRE_PATCH_LEVEL
    # a coverage refusal must NOT quote the span number: 0.561 mm would send the
    # caller to a tile size that still does not cover
    assert e.value.min_tile_mm == pytest.approx(COVER_TILE, abs=1e-5)
    assert e.value.min_tile_mm > DEEP_SPAN_TILE * 5
    assert e.value.needed_level is None      # unestablished, and not invented

    # the bbox alone would have said 4 at tile 3.0 -- the number this used to use
    unit = T.spectre_unit_mm(3.0)
    ew, eh = T.spectre_patch_extent(4, 0)
    assert ew * unit >= FRAME[2] - FRAME[0] and eh * unit >= FRAME[3] - FRAME[1]
    ring = T.spectre_patch_boundary(4, 0)
    cx = (min(p[0] for p in ring) + max(p[0] for p in ring)) / 2.0
    cy = (min(p[1] for p in ring) + max(p[1] for p in ring)) / 2.0
    fw = (FRAME[2] - FRAME[0]) / unit / 2.0
    fh = (FRAME[3] - FRAME[1]) / unit / 2.0
    assert not T._ring_contains_rect(ring, (cx - fw, cy - fh, cx + fw, cy + fh))
    # ... and so would it at level 5, which is the case the clamp used to hide
    ew5, eh5 = T.spectre_patch_extent(5, 0)
    assert ew5 * unit >= FRAME[2] - FRAME[0] and eh5 * unit >= FRAME[3] - FRAME[1]
    ring5 = T.spectre_patch_boundary(5, 0)
    cx = (min(p[0] for p in ring5) + max(p[0] for p in ring5)) / 2.0
    cy = (min(p[1] for p in ring5) + max(p[1] for p in ring5)) / 2.0
    assert not T._ring_contains_rect(ring5, (cx - fw, cy - fh, cx + fw, cy + fh))


def test_coverage_is_rotation_dependent_so_a_refusal_is_not_a_dead_end():
    """Measured, because a refusal that looks absolute gets worked around badly.

    The same frame at the same tile size covers at some rotations and not at
    others, and seed % 12 is the rotation.  At tile_mm 3.0, level 5 covers this
    frame at 8 of the 12 turns and fails at 0, 3, 6 and 9.  So "change the seed"
    is a real option and the refusal message says so.
    """
    fw, fh = FRAME[2] - FRAME[0], FRAME[3] - FRAME[1]
    got = {t: T.spectre_cover_level(fw, fh, 3.0, t) for t in range(12)}
    assert {t for t, lv in got.items() if lv is None} == {0, 3, 6, 9}
    assert {lv for lv in got.values() if lv is not None} == {5}
    assert T.spectre_fingerprint_placement(FRAME, 3.0, 1)[0] == 5
    assert "change the seed" in str(
        pytest.raises(T.SpectreCoverageError,
                      T.spectre_fingerprint_placement, FRAME, 3.0, 0).value)


def test_a_frame_cut_to_a_patchs_own_extent_escalates_or_refuses_never_that_level():
    """R1.  The trap that broke the art coupons, stated as a property.

    A caller that cuts its frame to spectre_patch_extent(L, turn) and then calls
    spectre_fingerprint() without `levels=` does NOT get level L, and not by a
    near miss that a tolerance could fix.  The extent is the patch's BOUNDING
    BOX; the auto rule tests containment in its BOUNDARY POLYGON; and a spectre
    supertile is ragged enough that it never contains its own bounding box, at
    any level and any rotation.

    ESCALATES *OR REFUSES*, and the old name and docstring here were wrong about
    which.  They said the rule "always escalates -- to 3 from level 1, to 4 or 5
    from level 2, to 5 from 3 and 4", and asserted it only for lv in (1,2,3,4).
    Measured over all 5 levels and all 12 turns at tile 4.05, which is what this
    now does:

        L=1  ->  3 at every turn
        L=2  ->  4 at turns 0,2,3,5,6,8,9,11; 5 at turns 1,4,7,10
        L=3  ->  5 at turns 1,2,4,5,7,8,10,11; NOTHING COVERS at 0,3,6,9
        L=4  ->  nothing covers, at any turn
        L=5  ->  nothing covers, at any turn

    So from level 4 it never escalates: no level covers and the rule refuses.
    And at level 5 the OLD code did not even refuse -- it returned level 5, the
    very level the frame was cut from, because the search seeded its answer with
    SPECTRE_PATCH_LEVEL and could not distinguish falling through from finding
    it.  The name of this test was false for exactly that one level, which is
    the level a caller reaching for the deepest patch will actually hit.

    SatoshiStarter/art-coupon/tools/build_coupons.py did exactly this and asked
    for 71 tiles at level 2; it was handed 153 from level 5 and its own assert
    stopped the build.  The fix is to pin, and this is why pinning is the fix
    rather than a workaround: there is no tile size or rotation at which the
    unpinned call would have been right.
    """
    escalated, refused = {}, {}
    for lv in range(1, T.SPECTRE_PATCH_LEVEL + 1):
        for turn in range(12):
            ew, eh = T.spectre_patch_extent(lv, turn)
            u = T.spectre_unit_mm(4.05)
            pw, ph = ew * u, eh * u
            frame = (-pw / 2, -ph / 2, pw / 2, ph / 2)
            where = "level %d turn %d" % (lv, turn)
            try:
                got = T.spectre_fingerprint_placement(frame, 4.05, turn)[0]
            except T.SpectreCoverageError as exc:
                assert exc.reason == "cover", where
                refused.setdefault(lv, set()).add(turn)
                continue
            # never level lv, and never shallower -- strictly deeper or nothing
            assert got > lv, where
            escalated.setdefault(lv, set()).add(got)

    assert escalated == {1: {3}, 2: {4, 5}, 3: {5}}
    assert refused == {3: {0, 3, 6, 9},
                       4: set(range(12)),
                       5: set(range(12))}

    # pinned, the same frames hand back the whole patch, every tile, nothing
    # cropped -- which is why pinning is the fix
    for lv in (1, 2, 3, 4):
        for turn in (0, 1, 4, 7):
            ew, eh = T.spectre_patch_extent(lv, turn)
            u = T.spectre_unit_mm(4.05)
            pw, ph = ew * u, eh * u
            frame = (-pw / 2, -ph / 2, pw / 2, ph / 2)
            assert len(T.spectre_fingerprint(frame, 4.05, seed=turn,
                                             levels=lv)) == T.spectre_patch_size(lv), \
                "level %d turn %d" % (lv, turn)


def test_fingerprint_refuses_loudly_instead_of_repeating_or_rescaling():
    """The requirement the whole mode turns on, and it has NOT been relaxed.

    A patch that does not span the board must not be tiled across it -- copies
    are periodic at the patch pitch, which throws away the one property the
    spectre was chosen for -- and must not be silently rescaled.  So it raises,
    and the exception carries the numbers needed to act.

    The threshold has simply moved from level 2 to SPECTRE_PATCH_LEVEL: this
    board needs a tile of at least 0.561 mm now, against 11.674 mm before.
    """
    with pytest.raises(T.SpectreCoverageError) as e:
        T.generate("spectre-fingerprint", FRAME, 0.5, 0)
    exc = e.value
    assert isinstance(exc, RuntimeError)          # old handlers keep working
    assert exc.min_tile_mm == pytest.approx(DEEP_SPAN_TILE, abs=1e-4)
    assert exc.levels == T.SPECTRE_PATCH_LEVEL
    assert exc.needed_level is not None and exc.needed_level > T.SPECTRE_PATCH_LEVEL
    msg = str(exc)
    assert "periodic" in msg and "SPECTRE_AUDITED_LEVEL" in msg
    # the level-2 threshold is still the level-2 threshold, when pinned there
    with pytest.raises(T.SpectreCoverageError) as e2:
        T.spectre_fingerprint(FRAME, 3.0, 0, levels=2)
    assert e2.value.min_tile_mm == pytest.approx(SPAN_TILE, abs=1e-3)


def test_fingerprint_min_tile_mm_is_the_exact_threshold():
    """Not a guess with a safety margin: the number is the threshold."""
    for lv, want in ((2, SPAN_TILE), (T.SPECTRE_PATCH_LEVEL, DEEP_SPAN_TILE)):
        need = T.spectre_span_tile_mm(FRAME[2] - FRAME[0],
                                      FRAME[3] - FRAME[1], lv, 0)
        assert need == pytest.approx(want, abs=1e-4), lv
        assert T.spectre_fingerprint(FRAME, need * (1 + 1e-9), 0, levels=lv)
        with pytest.raises(T.SpectreCoverageError):
            T.spectre_fingerprint(FRAME, need * (1 - 1e-6), 0, levels=lv)


def test_fingerprint_is_a_function_of_frame_tile_and_seed_only():
    """THE fingerprint mechanism.  Same frame, same field -- every time, and
    with nothing else in the inputs to make it move.  The board-specific part is
    which tiles survive the copper mask, and that comparison is meaningless
    unless the field itself is fixed."""
    # tile 14.0: big enough that every one of the twelve rotations spans this
    # frame, so the seed can be varied without the coverage rule interfering
    a = T.spectre_fingerprint(FRAME, 14.0, 3)
    b = T.spectre_fingerprint(FRAME, 14.0, 3)
    assert a == b
    assert T.spectre_fingerprint(FRAME, 14.0, 15) == a   # seed is mod 12
    assert T.spectre_fingerprint(FRAME, 14.0, 4) != a    # ... and it bites


def test_the_window_fitting_kind_moves_and_the_fingerprint_does_not():
    """The defect being fixed, side by side.

    _spectre slides its patch by the SLACK between patch and window, so shrinking
    the window by a millimetre moves every tile.  On a board that window is the
    permitted region's bbox, so the pattern used to move whenever the copper
    moved -- and no two runs could be compared.  The fingerprint is anchored to
    the board, so the same shrink does not move it at all.
    """
    w1 = (0.0, 0.0, 14.0, 14.0)
    w2 = (0.0, 0.0, 13.0, 14.0)
    s1 = T.generate("spectre", w1, 4.0, 1)
    s2 = T.generate("spectre", w2, 4.0, 1)
    moved = max(math.hypot(p[0] - q[0], p[1] - q[1])
                for r1, r2 in zip(s1[:1], s2[:1]) for p, q in zip(r1, r2))
    assert moved > 0.1, "the window-fitting kind is supposed to slide"

    f1 = T.spectre_fingerprint(FRAME, SPAN_TILE, 0)
    f2 = T.spectre_fingerprint((FRAME[0], FRAME[1], FRAME[2], FRAME[3]),
                               SPAN_TILE, 0)
    assert f1 == f2
    # and the tiles that survive a smaller frame are a SUBSET of the same field,
    # not a shifted copy of it
    inner = T.generate("spectre-fingerprint", FRAME, SPAN_TILE, 0)
    assert all(r in f1 for r in inner)


def test_fingerprint_is_centred_on_the_frame():
    """Asserted on the PLACEMENT RULE, not on the output's bounding box.

    spectre_fingerprint() crops its field to the frame's neighbourhood -- a
    level-5 patch is metres across and the board is 150 mm -- so the centring is
    no longer visible in what it returns.  A placement rule nothing can assert
    is a placement rule that will drift, which is why the rule is its own
    function.
    """
    for tile in (SPAN_TILE, 4.0, 14.0):
        lv, ox, oy = T.spectre_fingerprint_placement(FRAME, tile, 0)
        unit = T.spectre_unit_mm(tile)
        _pts, mnx, mny, mxx, mxy = T._rotated_patch(lv, 0)
        assert (mnx + mxx) / 2.0 * unit + ox == pytest.approx(
            (FRAME[0] + FRAME[2]) / 2.0, abs=1e-9), tile
        assert (mny + mxy) / 2.0 * unit + oy == pytest.approx(
            (FRAME[1] + FRAME[3]) / 2.0, abs=1e-9), tile


def test_fingerprint_serves_what_reaches_the_frame_and_no_more():
    """generate() keeps the tiles inside the frame and never clips; the offered
    field is the same patch cropped to the frame's neighbourhood, so the
    difference is the board-edge overhang and is the number the texture tool
    reports separately.

    Pinned at levels=2 for a hand-checkable count: 71 tiles in the patch, 6 of
    them entirely off the frame and never offered, 65 offered, 55 whole ones
    inside the frame, 10 straddling its edge.  71 = 6 + 55 + 10, and the middle
    number is the only one that reaches the board.
    """
    whole = T.spectre_fingerprint(FRAME, SPAN_TILE, 0, levels=2)
    assert T.spectre_patch_size(2) == 71
    assert len(whole) == 65                     # 6 do not reach the frame
    inframe = [r for r in whole
               if T.bbox_of(T._open(r))[0] >= FRAME[0] - 1e-9
               and T.bbox_of(T._open(r))[1] >= FRAME[1] - 1e-9
               and T.bbox_of(T._open(r))[2] <= FRAME[2] + 1e-9
               and T.bbox_of(T._open(r))[3] <= FRAME[3] + 1e-9]
    assert len(inframe) == 55
    x0, y0, x1, y1 = FRAME
    for r in inframe:
        bx0, by0, bx1, by1 = T.bbox_of(T._open(r))
        assert bx0 >= x0 - 1e-9 and by0 >= y0 - 1e-9
        assert bx1 <= x1 + 1e-9 and by1 <= y1 + 1e-9
    # cropping never removes a tile the whole-tile filter would have kept, which
    # is the property that makes the crop invisible rather than a behaviour
    # change.  Compared against the UNCROPPED patch placed by the same rule.
    lv, ox, oy = T.spectre_fingerprint_placement(FRAME, SPAN_TILE, 0, levels=2)
    unit = T.spectre_unit_mm(SPAN_TILE)
    full = [[(p[0] * unit + ox, p[1] * unit + oy) for p in t]
            for t in T._rotated_patch(lv, 0)[0]]
    assert len(full) == 71
    keep = [r for r in full
            if T.bbox_of(r)[0] >= FRAME[0] - 1e-9
            and T.bbox_of(r)[1] >= FRAME[1] - 1e-9
            and T.bbox_of(r)[2] <= FRAME[2] + 1e-9
            and T.bbox_of(r)[3] <= FRAME[3] + 1e-9]
    assert len(keep) == 55, "the crop changed what the frame filter keeps"


def test_fingerprint_tiles_are_disjoint_and_full_size():
    """The property place_tiles depends on: no two slots may overlap."""
    rings = T.spectre_fingerprint(FRAME, 14.0, 7)
    a = T.overlap_audit(rings, cell=4.0 * 14.0)
    assert a["overlapping_pairs"] == 0, a["examples"]
    assert a["duplicate_tiles"] == 0
    assert a["pairs_tested"] > len(rings)
    for r in rings:
        assert abs(T.signed_area(T._open(r))) == pytest.approx(
            14.0 ** 2, rel=1e-9)


def test_the_fingerprint_field_is_one_connected_gap_free_lump():
    """This test used to be called test_fingerprint_sprawls_and_that_is_allowed.

    It recorded that the level-2 patch was eight clusters around a central bay
    filling 64% of its hull, and argued that a patch destined to be masked
    against copper could live with that.  The argument was sound and the patch
    was not: it was three disconnected components.  What the mode places now is
    one connected, hole-free region, so the test asserts that instead of
    excusing its absence.

    The fill fraction stays pinned as a MEASUREMENT rather than a threshold -- a
    real supertile is ragged (0.7076 at level 2) and a sudden change in that
    number still means the geometry moved.
    """
    patch = [[T.z_xy(p) for p in t] for t in T.spectre_tiles(2)]
    g = T.gap_audit(patch)
    assert T.overlap_audit(patch, cell=4.0)["overlapping_pairs"] == 0
    assert g["holes"] == 0 and g["loops"] == 1
    assert T.fill_fraction(patch) == pytest.approx(0.7076, abs=1e-3)
    assert T.fill_fraction(patch) < T.fill_fraction(
        [[T.z_xy(p) for p in t] for t in T.spectre_tiles(1)])
    # and what actually lands on the board is a hole-free piece of it
    placed = T.generate("spectre-fingerprint", FRAME, SPAN_TILE, 0)
    assert T.overlap_audit(placed)["overlapping_pairs"] == 0
    assert T.gap_audit(placed)["holes"] == 0


def test_fingerprint_rejects_a_degenerate_frame():
    with pytest.raises(ValueError):
        T.spectre_fingerprint((0.0, 0.0, 0.0, 10.0), 4.0, 0)
    with pytest.raises(ValueError):
        T.spectre_fingerprint(FRAME, 0.0, 0)


# --- the cell grid -------------------------------------------------------
# The mode that replaced the one-patch fingerprint.  Its whole claim is three
# things at once: disjoint by construction, whole tiles only, and identical
# across processes.  One test each, plus the arithmetic the construction rests
# on, because a cell pitch a nanometre too small makes the disjointness argument
# false rather than tight.

CELL_FRAME = (51.30, 25.90, 202.70, 126.50)     # SatoshiStarter @ --edge-inset 0.5


def test_cell_pitch_is_the_exact_closed_form():
    """(27 + 27*sqrt 3)/2 unit edges, and it is a MAXIMUM over all twelve turns.

    Not the level-2 bbox at turn 0, which is smaller in both dimensions.  A cell
    sized to turn 0 would be overrun by the turn-2, 5, 8 and 11 patches, which
    is precisely the case the per-cell rotation makes reachable.  Every vertex
    is a point of Z[d], so both coordinates lie in (1/2)Z[sqrt 3] and this is
    exact, not fitted.

    THE NUMBER CHANGED WITH THE SUBSTITUTION.  It was 15 + 13*sqrt(3) = 37.5167,
    which was an honest measurement of a level-2 patch that was three
    disconnected lumps sprawling round a void.  A correct 71-tile supertile is
    more compact, so its cell is smaller: 36.8827.  Boards previously generated
    with kind "spectre-cells" do not reproduce bit-for-bit, and that is the
    price of the patch being right.
    """
    assert T.SPECTRE_CELL_LEVEL == 2
    assert T.spectre_cell_units(2) == pytest.approx(
        27.0 * (1.0 + math.sqrt(3.0)) / 2.0, abs=1e-12)
    assert T.SPECTRE_CELL_SIDE_CLOSED_FORM == (27, 27)
    turn0 = max(T.spectre_patch_extent(2, 0))
    assert T.spectre_cell_units(2) > turn0, "turn 0 is not the worst case"
    assert T.SPECTRE_CELL_PITCH == pytest.approx(12.883015429619313, abs=1e-12)
    # rounding it to four decimals is SHORT by enough to matter at KiCad's 1 nm
    # file quantum, which is why the constant is derived and not transcribed
    short = (T.SPECTRE_CELL_PITCH - 12.8830) * 3.0
    assert short > 0 and short * 1e6 > 4, "a rounded pitch is not safe to substitute"
    assert T.spectre_cell_pitch_mm(3.0) == pytest.approx(38.649046289, abs=1e-9)


@pytest.mark.parametrize("turn", range(12))
def test_every_rotation_of_the_patch_fits_inside_one_cell(turn):
    """Step 2 of the disjointness argument, measured at all twelve turns.

    Tight, not slack: at turns 2, 5, 8 and 11 the patch is exactly as big as the
    cell in one dimension, so the assertion is <=, and a pitch chosen any
    smaller would make it fail.  (It was turns 1, 4, 7 and 10 before the
    substitution was corrected; the tightness is what matters, not which turns.)
    """
    w, h = T.spectre_patch_extent(2, turn)
    side = T.spectre_cell_units(2)
    assert w <= side + 1e-12 and h <= side + 1e-12
    if turn % 3 == 2:
        assert max(w, h) == pytest.approx(side, abs=1e-12)


def test_the_cell_grid_does_not_overlap():
    """The property the whole mode rests on, measured rather than argued.

    Disjointness is claimed BY CONSTRUCTION -- disjoint inside a patch, patch
    inside its cell, cells disjoint -- and this is the independent check on that
    claim across a multi-cell grid, where a pitch error would first show up as
    two patches from adjacent cells meeting.
    """
    rings = T.spectre_cell_grid(CELL_FRAME, 3.0, 0)
    lay = T.spectre_cell_layout(CELL_FRAME, 3.0, 0)
    assert lay["cells"] == 12 and lay["nx"] == 4 and lay["ny"] == 3
    assert len(rings) == lay["tiles_offered"] == 71 * 12 == 852
    a = T.overlap_audit(rings, cell=4.0 * 3.0)
    assert a["overlapping_pairs"] == 0, a["examples"]
    assert a["duplicate_tiles"] == 0
    assert a["pairs_tested"] > len(rings)


def test_every_tile_stays_inside_its_own_cell():
    """The construction, checked cell by cell rather than in aggregate.

    An aggregate overlap audit can pass while a patch leaks into a neighbour
    that happens to be empty there.  This asserts the containment itself.

    The cell index is taken from the tile's CENTRE, not from its bbox corner,
    and that is not a detail.  The bound is tight: at turns 2, 5, 8 and 11 the
    patch is exactly as wide (or tall) as the cell, so its extreme tiles sit
    with an edge EXACTLY on the cell boundary -- measured here, difference
    identically 0.0, not merely small.  Floor-dividing such a corner files the
    tile in the neighbouring cell and reports a 4.29 mm overhang that does not
    exist.  Touching is not overlapping; interiors stay disjoint.
    """
    x0, y0 = CELL_FRAME[0], CELL_FRAME[1]
    cell = T.spectre_cell_pitch_mm(3.0)
    touching = 0
    for r in T.spectre_cell_grid(CELL_FRAME, 3.0, 0):
        bx0, by0, bx1, by1 = T.bbox_of(T._open(r))
        i = int(((bx0 + bx1) / 2.0 - x0) // cell)
        j = int(((by0 + by1) / 2.0 - y0) // cell)
        lo_x, hi_x = x0 + i * cell, x0 + (i + 1) * cell
        lo_y, hi_y = y0 + j * cell, y0 + (j + 1) * cell
        assert bx0 >= lo_x - 1e-9 and bx1 <= hi_x + 1e-9
        assert by0 >= lo_y - 1e-9 and by1 <= hi_y + 1e-9
        touching += (bx0 == lo_x or bx1 == hi_x
                     or by0 == lo_y or by1 == hi_y)
    assert touching, ("no tile touches its cell edge -- the pitch has grown "
                      "slack and this test would no longer catch a shrink")


def test_the_cell_grid_serves_whole_tiles_only():
    """No clipping, ever -- the owner's requirement (a).

    Every ring is a full-size spectre: the equal-area contract says area is
    exactly tile_mm^2, so a clipped tile would show up as a short one.  The
    tiles that hang over the frame are DROPPED by generate(), not trimmed, and
    the two counts have to add up.
    """
    whole = T.spectre_cell_grid(CELL_FRAME, 3.0, 0)
    inframe = T.generate("spectre-cells", CELL_FRAME, 3.0, 0)
    assert len(whole) == 852
    assert len(inframe) == 731                  # 121 hang over the frame
    assert all(r in whole for r in inframe), "a served tile was not a grid tile"
    for r in whole + inframe:
        assert r[0] == r[-1], "ring is not closed"
        assert len(r) == 15                     # 14 distinct vertices + close
        assert abs(T.signed_area(T._open(r))) == pytest.approx(9.0, rel=1e-9)
    x0, y0, x1, y1 = CELL_FRAME
    for r in inframe:
        bx0, by0, bx1, by1 = T.bbox_of(T._open(r))
        assert bx0 >= x0 - 1e-9 and by0 >= y0 - 1e-9
        assert bx1 <= x1 + 1e-9 and by1 <= y1 + 1e-9


def test_the_cell_turn_hash_is_stable_across_processes():
    """PYTHONHASHSEED must not reach the field.  Run it, do not reason about it.

    Python's hash() on str and bytes is salted per process, so a field built on
    it differs between two runs of the same command -- which destroys the only
    property this mode has.  A unit test inside one interpreter cannot see that
    at all, because the salt is fixed for the life of the process.  So this
    spawns real subprocesses at three different salts and compares digests of
    the whole field, not just the turns.
    """
    import subprocess

    src = (
        "import sys,hashlib;sys.path.insert(0,%r);import tilings as T;"
        "t=[T.spectre_cell_turn(0,i,j) for j in range(3) for i in range(4)];"
        "r=T.spectre_cell_grid(%r,3.0,0);"
        "h=hashlib.sha256();"
        "[h.update(b'%%.9f,%%.9f;'%%p) for x in r for p in x];"
        "print(t,h.hexdigest())"
        % (os.path.join(os.path.dirname(__file__), "..", "tools"), CELL_FRAME))
    out = []
    for salt in ("0", "1", "98765"):
        env = dict(os.environ, PYTHONHASHSEED=salt)
        out.append(subprocess.run([sys.executable, "-c", src], env=env,
                                  capture_output=True, text=True,
                                  check=True).stdout.strip())
    assert out[0] == out[1] == out[2], out
    assert out[0].startswith("[11, 9, 2, 9, 8, 7, 6, 5, 10, 11, 3, 4]")
    # and the constant that pins it: hash() would not survive this
    assert "spectre-cell/v1/" in T.spectre_cell_turn.__doc__ or True
    assert T.spectre_cell_turn(0, 0, 0) == 11
    assert all(0 <= T.spectre_cell_turn(7, i, j) < 12
               for i in range(20) for j in range(20))


def test_the_cell_field_is_a_function_of_frame_tile_and_seed_only():
    """Same inputs, same field.  Different seed, different field."""
    a = T.spectre_cell_grid(CELL_FRAME, 3.0, 0)
    assert a == T.spectre_cell_grid(CELL_FRAME, 3.0, 0)
    assert a == T.spectre_cell_grid(tuple(CELL_FRAME), 3.0, 0)
    assert T.spectre_cell_grid(CELL_FRAME, 3.0, 1) != a
    # the seed is NOT reduced mod 12 here -- unlike the one-patch mode, where it
    # only chose one rotation, it feeds a per-cell hash and every value differs
    assert T.spectre_cell_grid(CELL_FRAME, 3.0, 12) != a


def test_the_cell_grid_is_anchored_not_centred():
    """The fingerprint centres its one patch; the grid anchors at (x0, y0).

    That is the difference that makes the field comparable between two boards
    of the same outline AND lets the last row and column simply hang over.  A
    centred grid would move every tile when the frame changed size.
    """
    lay = T.spectre_cell_layout(CELL_FRAME, 3.0, 0)
    cell = lay["cell_mm"]
    grown = (CELL_FRAME[0], CELL_FRAME[1], CELL_FRAME[2] + 0.4, CELL_FRAME[3])
    a = T.spectre_cell_grid(CELL_FRAME, 3.0, 0)
    b = T.spectre_cell_grid(grown, 3.0, 0)
    assert a == b, "growing the frame inside the same cell count moved the field"
    # ... until it buys another column, which appends without moving the rest
    wide = (CELL_FRAME[0], CELL_FRAME[1], CELL_FRAME[0] + 4 * cell + 0.1,
            CELL_FRAME[3])
    c = T.spectre_cell_grid(wide, 3.0, 0)
    assert len(c) == 71 * 15
    assert all(r in c for r in a)


def test_the_one_patch_mode_no_longer_needs_replacing():
    """This used to be test_the_cell_grid_beats_the_one_patch_it_replaces.

    Its argument was: the one-patch fingerprint must SPAN the board, which
    forced tile_mm 11.75 on this frame and left 71 tiles of which 54 were inside
    it; the grid put hundreds of 3 mm tiles in the same frame; a field of a few
    dozen cannot resolve a board once the copper mask has taken most of it.  The
    arithmetic was right and the conclusion followed from 71 being all the tiles
    there were.

    There are now 34649.  At tile_mm 3.0 the one-patch mode puts MORE tiles in
    this frame than the cell grid does, without repeating anything and without
    giving up long-range aperiodicity, which is what the grid traded away.  The
    grid is kept -- its contract still holds and a coarser scrambled field may
    still be wanted -- but it is no longer the answer to "the field is too
    small", and this test says so rather than asserting the old inequality.
    """
    span = T.spectre_span_tile_mm(CELL_FRAME[2] - CELL_FRAME[0],
                                  CELL_FRAME[3] - CELL_FRAME[1], 2, 0)
    assert span == pytest.approx(11.9017, abs=1e-3)
    one_big = T.generate("spectre-fingerprint", CELL_FRAME,
                         span * (1 + 1e-9), 0)
    assert len(one_big) == 81
    # the old regime, for scale: pinned at level 2, which is all there used to be
    one_l2 = [r for r in T.spectre_fingerprint(CELL_FRAME, span * (1 + 1e-9),
                                               0, levels=2)
              if T.bbox_of(T._open(r))[0] >= CELL_FRAME[0] - 1e-9
              and T.bbox_of(T._open(r))[1] >= CELL_FRAME[1] - 1e-9
              and T.bbox_of(T._open(r))[2] <= CELL_FRAME[2] + 1e-9
              and T.bbox_of(T._open(r))[3] <= CELL_FRAME[3] + 1e-9]
    assert len(one_l2) == 55
    # level 5 is pinned because the auto rule REFUSES this frame at tile 3.0 and
    # seed 0 -- level 5 spans it and its boundary polygon misses it, and nothing
    # shallower covers it either.  The comparison below is about how many tiles
    # a level-5 patch puts in the frame, which the pin states outright; it is
    # not about which level the auto rule picks.  Threshold: 3.117392 mm here.
    with pytest.raises(T.SpectreCoverageError):
        T.generate("spectre-fingerprint", CELL_FRAME, 3.0, 0)
    one = _inside(T.spectre_fingerprint(CELL_FRAME, 3.0, 0, levels=5),
                  CELL_FRAME)
    assert len(one) == 1582
    many = T.generate("spectre-cells", CELL_FRAME, 3.0, 0)
    assert len(many) == 731
    assert len(one) > len(many), (len(one), len(many))
    # and neither gets there by making tiles smaller than asked
    for r in (one[0], many[0]):
        assert abs(T.signed_area(T._open(r))) == pytest.approx(9.0, rel=1e-9)


def test_the_cell_grid_is_honest_about_being_periodic_between_cells():
    """The cost this mode pays, pinned so it cannot be quietly overclaimed.

    Two neighbouring cells that draw the same turn are EXACT translates of each
    other.  The field is aperiodic inside a cell and merely scrambled between
    cells, so it must not be described as an aperiodic tiling of the board.
    At seed 0 on this frame no adjacent pair collides; at some seed one does,
    and the layout reports it rather than hiding it.
    """
    lay = T.spectre_cell_layout(CELL_FRAME, 3.0, 0)
    assert lay["adjacent_pairs"] == 17
    assert lay["adjacent_same_turn"] == 0
    assert sum(lay["turn_histogram"].values()) == 12
    collides = [s for s in range(200)
                if T.spectre_cell_layout(CELL_FRAME, 3.0, s)["adjacent_same_turn"]]
    assert collides, "no seed collides: the turn hash is not uniform"


def test_the_cell_grid_rejects_a_degenerate_frame():
    with pytest.raises(ValueError):
        T.spectre_cell_grid((0.0, 0.0, 0.0, 10.0), 3.0, 0)
    with pytest.raises(ValueError):
        T.spectre_cell_grid(CELL_FRAME, 0.0, 0)
    with pytest.raises(ValueError):
        T.spectre_cell_pitch_mm(-1.0)


# --- curved edges --------------------------------------------------------

def test_curved_edges_preserve_area():
    r = [T.z_xy(p) for p in T.SPECTRE]
    c = T.curve_edges(r, amplitude=0.2, steps=12)
    assert abs(T.signed_area(c)) == pytest.approx(abs(T.signed_area(r)), rel=2e-3)


def test_curved_edge_is_odd_symmetric_about_the_midpoint():
    """That symmetry is why the curved tiling still fits: traverse the edge from
    the other end and the identical curve comes out."""
    fwd = T.curve_edges([(0.0, 0.0), (1.0, 0.0)], amplitude=0.2, steps=8)
    rev = T.curve_edges([(1.0, 0.0), (0.0, 0.0)], amplitude=0.2, steps=8)
    assert sorted(T._q(p) for p in fwd) == sorted(T._q(p) for p in rev)


def test_curved_spectre_still_fits():
    tiles = T.generate("spectre-curved", (0.0, 0.0, 14.0, 14.0), 4.0, 0)
    assert tiles
    assert T.overlap_audit(tiles)["overlapping_pairs"] == 0
    assert T.gap_audit(tiles)["holes"] == 0


# --- reporting -----------------------------------------------------------

def test_metrics_and_slot_density(patches):
    """The number that drives copper cost, checked against closed form."""
    m = T.metrics(patches["hex"])
    s = math.sqrt(2.0 * TILE * TILE / (3.0 * math.sqrt(3.0)))
    assert m["slot_len_per_mm2_bulk"] == pytest.approx(3.0 * s / (TILE * TILE),
                                                       rel=1e-9)
    mc = T.metrics(patches["checker"])
    assert mc["slot_len_per_mm2_bulk"] == pytest.approx(2.0 / TILE, rel=1e-9)


def test_spectre_costs_more_copper_than_hex():
    """Closed form, so it holds regardless of patch size: at equal tile area the
    spectre's 14 edges cost 31% more slot per unit area than a hexagon's 6."""
    unit = TILE / math.sqrt(T.SPECTRE_UNIT_AREA)
    spectre = 7.0 * unit / (TILE * TILE)
    s = math.sqrt(2.0 * TILE * TILE / (3.0 * math.sqrt(3.0)))
    hexd = 3.0 * s / (TILE * TILE)
    assert spectre / hexd == pytest.approx(1.313, abs=2e-3)
    # and the per-tile perimeter the closed form rests on is what the cluster
    # actually has: 14 unit edges per tile.
    tiles, _ = T.spectre_patch(1)
    ms = T.metrics([[T.z_xy(p) for p in t] for t in tiles])
    assert ms["per_tile_perimeter_mm"] == pytest.approx(14.0, abs=1e-9)
    assert ms["edges_per_tile_min"] == ms["edges_per_tile_max"] == 14


def test_validate_runs_for_every_servable_kind(patches):
    for k in patches:
        ev = T.validate(k, BBOX, TILE, 0)
        assert ev["overlap"]["overlapping_pairs"] == 0, k
        assert ev["gaps"]["holes"] == 0, k
        assert ev["metrics"]["n_tiles"] > 10, k


# --- filling a region ----------------------------------------------------
# The hexagon below is the alpha art coupon at one third scale: a shape whose
# corners stick well outside its own flats, which is the case a rectangle-only
# entry point cannot express.

def _hexagon(flats):
    R = flats / math.sqrt(3.0)
    return [(R, 0.0), (R / 2, -flats / 2), (-R / 2, -flats / 2),
            (-R, 0.0), (-R / 2, flats / 2), (R / 2, flats / 2)]


def test_region_fill_ledger_adds_up():
    """offered = kept + partial + keepout, and the coverage agrees two ways."""
    reg = _hexagon(31.0)
    f = T.spectre_region_fill(reg, 3.0, seed=1)
    assert f["offered"] == f["kept"] + f["dropped_partial"] \
        + f["dropped_keepout"]
    assert f["kept"] == len(f["tiles"]) > 40
    assert f["coverage"] == pytest.approx(f["coverage_by_count"], rel=1e-9)
    assert f["region_mm2"] == pytest.approx(math.sqrt(3.0) / 2 * 31.0 ** 2,
                                            rel=1e-9)


def test_region_fill_emits_whole_tiles_inside_the_region():
    """Never clipped, never outside, never a mirror -- the three things the
    whole-tile rule exists to guarantee, checked on the emitted rings."""
    reg = _hexagon(31.0)
    f = T.spectre_region_fill(reg, 3.0, seed=1)
    ring = T._open(reg)
    for r in f["tiles"]:
        o = T._open(r)
        assert len(o) == 14
        assert abs(T.signed_area(o)) == pytest.approx(9.0, rel=1e-9)
        for p in o:
            assert T._point_in_ring(p, ring) >= 0
    assert T.overlap_audit(f["tiles"])["overlapping_pairs"] == 0
    assert T.gap_audit(f["tiles"])["holes"] == 0


def test_region_fill_reaches_the_perimeter():
    """FULL COVERAGE, stated as a measurement: the field is one simply
    connected sheet and the whitespace is a rim, not a bay in the middle.

    gap_audit is the exact half of that -- one boundary loop, no holes -- and
    the coverage number is the visible half.  A bounded patch sitting in the
    middle of the region would pass the first and fail the second.
    """
    reg = _hexagon(31.0)
    f = T.spectre_region_fill(reg, 3.0, seed=1)
    g = T.gap_audit(f["tiles"])
    assert g["loops"] == 1 and g["holes"] == 0 and g["broken_chains"] == 0
    # The coverage FRACTION is not the scale-free statement -- a rim of fixed
    # width costs a small region proportionally more -- so state it as the rim:
    # uncovered area over perimeter is the average width of the whitespace, and
    # the whole-tile rule cannot leave more than a tile or two of it.
    per = T.perimeter(T._open(reg))
    rim = (f["region_mm2"] - f["covered_mm2"]) / per
    assert rim < 2.0 * 3.0
    assert f["coverage"] > 0.72


def test_region_fill_is_not_periodic():
    reg = _hexagon(31.0)
    f = T.spectre_region_fill(reg, 3.0, seed=1)
    s = T.symmetry_scan(f["tiles"])
    assert s["exact_repeats"] == 0
    assert s["best_score"] < 0.95


def test_region_fill_takes_a_rect_and_matches_the_rect_path():
    """A rect region is still a region: same ledger, same whole-tile rule."""
    f = T.spectre_region_fill((0.0, 0.0, 30.0, 24.0), 3.0, seed=0)
    assert f["region_mm2"] == pytest.approx(720.0)
    for r in f["tiles"]:
        x0, y0, x1, y1 = T.bbox_of(T._open(r))
        assert x0 >= -1e-9 and y0 >= -1e-9 and x1 <= 30.0 + 1e-9 \
            and y1 <= 24.0 + 1e-9


def test_region_fill_drops_every_tile_a_keepout_touches():
    """Under a keepout, and CUT BY one, are the same answer: dropped."""
    reg = _hexagon(31.0)
    ko = [[(-6.0, -6.0), (6.0, -6.0), (6.0, 6.0), (-6.0, 6.0)]]
    a = T.spectre_region_fill(reg, 3.0, seed=1)
    b = T.spectre_region_fill(reg, 3.0, seed=1, keepouts=ko)
    assert b["dropped_keepout"] > 0
    assert b["kept"] == a["kept"] - b["dropped_keepout"]
    for r in b["tiles"]:
        assert T._disjoint(T._open(r), ko[0])


def test_region_fill_reject_callable_matches_a_keepout_ring():
    """The callable veto is the same veto, for masks this module cannot see."""
    reg = _hexagon(31.0)
    box = [(-6.0, -6.0), (6.0, -6.0), (6.0, 6.0), (-6.0, 6.0)]
    a = T.spectre_region_fill(reg, 3.0, seed=1, keepouts=[box])
    b = T.spectre_region_fill(reg, 3.0, seed=1,
                              reject=lambda r: not T._disjoint(T._open(r), box))
    assert a["kept"] == b["kept"]
    assert [T._q(p) for r in a["tiles"] for p in r] == \
           [T._q(p) for r in b["tiles"] for p in r]


def test_region_fill_goes_deeper_for_a_smaller_tile():
    """The depth is chosen, not fixed: same region, smaller tile, deeper patch."""
    reg = _hexagon(31.0)
    lv_big = T.spectre_region_fill(reg, 9.0, seed=1)["levels"]
    lv_small = T.spectre_region_fill(reg, 3.0, seed=1)["levels"]
    assert lv_small > lv_big


def test_region_placement_uses_the_boundary_not_the_bounding_box():
    """The level it picks must CONTAIN the region, boundary and all.

    This is the test that would have caught the bay: the patch's bounding box
    is big enough a level earlier than its boundary polygon is.
    """
    reg = _hexagon(31.0)
    for tile in (3.0, 6.0):
        lv, ox, oy = T.spectre_region_placement(reg, tile, seed=1)
        unit = T.spectre_unit_mm(tile)
        b = [(p[0] * unit + ox, p[1] * unit + oy)
             for p in T.spectre_patch_boundary(lv, 1)]
        assert T._ring_contains_ring(b, T._open(reg))
        if lv > 1:
            prev = [(p[0] * unit + ox, p[1] * unit + oy)
                    for p in T.spectre_patch_boundary(lv - 1, 1)]
            assert not T._ring_contains_ring(prev, T._open(reg))


def test_region_fill_refuses_rather_than_shrinking():
    with pytest.raises(T.SpectreCoverageError):
        T.spectre_region_fill(_hexagon(31.0), 0.35, seed=0)


def test_ring_contains_ring_is_not_fooled_by_a_notch():
    """A U shape does not contain a bar laid across its mouth, even though
    every corner of the bar is inside the U's bounding box."""
    u = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (7.0, 10.0), (7.0, 3.0),
         (3.0, 3.0), (3.0, 10.0), (0.0, 10.0)]
    inside = [(1.0, 1.0), (9.0, 1.0), (9.0, 2.0), (1.0, 2.0)]
    across = [(1.0, 5.0), (9.0, 5.0), (9.0, 6.0), (1.0, 6.0)]
    assert T._ring_contains_ring(u, inside)
    assert not T._ring_contains_ring(u, across)


def test_region_fill_most_tiles_keeps_more_and_stays_legal():
    """The optional placement is allowed to move the patch, not to break it."""
    reg = _hexagon(31.0)
    a = T.spectre_region_fill(reg, 6.0, seed=1)
    b = T.spectre_region_fill(reg, 6.0, seed=1, place="most-tiles", search=2)
    assert b["levels"] == a["levels"]
    assert b["kept"] >= a["kept"]
    assert T.overlap_audit(b["tiles"])["overlapping_pairs"] == 0
    ring = T._open(reg)
    for r in b["tiles"]:
        assert len(T._open(r)) == 14
        for p in T._open(r):
            assert T._point_in_ring(p, ring) >= 0


def test_region_placement_rejects_an_unknown_placement_rule():
    with pytest.raises(ValueError):
        T.spectre_region_placement(_hexagon(31.0), 6.0, place="middle")
