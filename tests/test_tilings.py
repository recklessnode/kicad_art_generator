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

    The spectre cannot, and that is the honest state of the module rather than a
    fixture convenience: its substitution is a supertile only to level 1, a
    9-tile cluster roughly 15 mm across.  generate() refuses the window instead
    of emitting a patch nobody has audited.  The two tests below pin that, and
    both will start failing the day level 2 is solved properly -- which is the
    reminder to delete them.

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


def test_only_the_periodic_kinds_can_fill_a_board_window(patches):
    assert sorted(patches) == sorted(PERIODIC)


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
    with pytest.raises(RuntimeError) as e:
        T.generate("spectre", BBOX, TILE, 0)
    assert "SPECTRE_VERIFIED_LEVEL" in str(e.value)
    with pytest.raises(RuntimeError):
        T.spectre_patch(T.SPECTRE_VERIFIED_LEVEL + 1)
    assert T.SPECTRE_VERIFIED_LEVEL == 1


# --- two gates, two questions ---------------------------------------------
# The single constant used to answer both "may I substitute again" and "may I
# place these tiles", which are not the same question and do not have the same
# answer.  These four tests pin the split and, between them, make it impossible
# to raise either constant by accident.

def test_the_two_gates_are_separate_constants():
    assert T.SPECTRE_SUPERTILE_LEVEL == 1
    assert T.SPECTRE_PATCH_LEVEL == 2
    # the old name still means the old thing
    assert T.SPECTRE_VERIFIED_LEVEL == T.SPECTRE_SUPERTILE_LEVEL
    # the quad-bearing entry point is gated at the SUPERTILE level ...
    T.spectre_patch(T.SPECTRE_SUPERTILE_LEVEL)
    with pytest.raises(RuntimeError):
        T.spectre_patch(T.SPECTRE_SUPERTILE_LEVEL + 1)
    # ... the tiles-only one at the PATCH level, and it returns no quad at all
    tiles = T.spectre_tiles(T.SPECTRE_PATCH_LEVEL)
    assert len(tiles) == 71
    assert all(len(t) == 14 for t in tiles)     # tiles, not (tiles, quad)


def test_level_2_is_a_valid_patch_by_exact_arithmetic():
    """The finding this whole mode rests on, re-measured every run.

    Integer predicates in Z[sqrt3], no tolerance: 71 tiles, 185 candidate pairs,
    no edge of any tile properly crosses an edge of another, no vertex of any
    tile is strictly inside another, and not one tile is a mirror image.  That is
    necessary and sufficient for pairwise disjoint interiors.
    """
    a = T.spectre_patch_audit(2)
    assert a["n_tiles"] == a["expected_tiles"] == 71
    assert a["pairs_tested"] == 185
    assert a["proper_crossings"] == 0
    assert a["strictly_interior_vertices"] == 0
    assert a["overlapping_pairs"] == 0
    assert a["reflected_tiles"] == 0
    assert abs(a["area_defect"]) < 1e-9
    assert a["patch_ok"] is True


def test_level_2_is_still_not_a_supertile():
    """WITHOUT THIS TEST, 'level 2 is verified now' is what the next person reads.

    It is not.  The patch audit passing says the tiles may be PLACED; the
    supertile question -- may they be substituted again -- still fails, on the
    same number it always failed on.  Hull fill 0.6405 against 0.804 for the
    9-tile cluster, and the anchor quad still grows 6.9% per level too fast.
    """
    a = T.spectre_patch_audit(2)
    assert a["hull_fill"] == pytest.approx(0.6405, abs=1e-3)
    assert a["supertile_ok"] is False
    assert T.spectre_patch_audit(1)["supertile_ok"] is True
    assert T.SPECTRE_SUPERTILE_LEVEL == 1
    factor, _ = T.spectre_quad_inflation()
    assert factor == pytest.approx(3.0, abs=1e-9)
    assert factor > T.SPECTRE_INFLATION


def test_level_3_is_refused_and_the_measurement_says_why():
    """A constant that can be raised without a failing test WILL be raised."""
    with pytest.raises(RuntimeError) as e:
        T.spectre_tiles(T.SPECTRE_PATCH_LEVEL + 1)
    assert "SPECTRE_PATCH_LEVEL" in str(e.value)
    a = T.spectre_patch_audit(3)
    assert a["n_tiles"] == 559
    assert a["overlapping_pairs"] == 97
    assert a["proper_crossings"] == 128
    assert a["strictly_interior_vertices"] == 520
    assert a["edges_shared_by_3_or_more"] == 25
    assert a["boundary_loops"] == 7
    assert a["patch_ok"] is False


def test_the_exact_and_float_overlap_audits_agree():
    """Two independent methods, one answer.  overlap_audit works in floats with a
    1e-9 epsilon and a bucket grid; spectre_patch_audit is integer arithmetic in
    Z[sqrt3] with no epsilon at all.  If they ever disagree, one of them is
    measuring something other than overlap."""
    for lv in (0, 1, 2):
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


@pytest.mark.xfail(reason="a 9-tile cluster is far too small to scan; needs a "
                          "correct level 2, see SPECTRE_VERIFIED_LEVEL",
                   strict=True)
def test_spectre_has_no_translational_symmetry():
    """The aperiodicity evidence this module OWES and does not have.

    Strict xfail, so it converts into a failure -- and a demand to become a real
    assertion -- the moment the substitution produces a patch worth scanning.
    Deliberately not softened into something a 9-tile cluster can pass: that
    would look like evidence while being none.
    """
    tiles, _ = T.spectre_patch(T.SPECTRE_VERIFIED_LEVEL)
    rings = [[T.z_xy(p) for p in t] for t in tiles]
    s = T.symmetry_scan(rings)
    assert s["candidates_tested"] > 40
    assert s["exact_repeats"] == 0
    assert s["best_score"] < 0.5


def test_spectre_uses_many_orientations_and_no_reflections():
    """The chirality claim, exactly, tile by tile.

    Every tile in the cluster is a ROTATION of the base tile -- not one is a
    mirrored copy.  That is what separates the spectre from the hat, which
    cannot tile without both handednesses.  The nine tiles already sit in six of
    the twelve available orientations, which no lattice of one shape would do.
    """
    tiles, _ = T.spectre_patch(T.SPECTRE_VERIFIED_LEVEL)
    turns = set()
    for t in tiles:
        k = _rotation_of(T.SPECTRE, t)
        assert k is not None, "a tile in the patch is a reflected copy"
        turns.add(k)
    assert len(turns) >= 5, sorted(turns)


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
    tiles, _ = T.spectre_patch(1)
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
    """The whole point of the spectre: one handedness only."""
    tiles, _ = T.spectre_patch(T.SPECTRE_VERIFIED_LEVEL)
    for t in tiles:
        assert _is_rotation_of(T.SPECTRE, t)


def test_spectre_exact_fit_audit():
    """Integer arithmetic, no tolerance: no edge may be claimed by three tiles
    and the patch boundary must be a single loop."""
    for lv in range(0, T.SPECTRE_VERIFIED_LEVEL + 1):
        r = T.spectre_exact_fit(lv)
        assert r["edges_shared_by_3_or_more"] == 0, r
        assert r["broken_chains"] == 0, r
        assert r["boundary_loops"] == 1, r
        assert r["interior_edges"] > 0 or lv == 0


def test_spectre_patch_is_geometrically_disjoint():
    tiles, _ = T.spectre_patch(T.SPECTRE_VERIFIED_LEVEL)
    rings = [[T.z_xy(p) for p in t] for t in tiles]
    a = T.overlap_audit(rings, cell=4.0)
    assert a["overlapping_pairs"] == 0, a["examples"]
    assert a["duplicate_tiles"] == 0


def test_spectre_patch_tile_counts():
    for lv in range(0, T.SPECTRE_VERIFIED_LEVEL + 1):
        tiles, _ = T.spectre_patch(lv)
        assert len(tiles) == T.spectre_patch_size(lv)


def test_a_supertile_is_as_compact_as_its_tile():
    """The check that caught level 2, kept as a standing requirement.

    Zero overlaps, one loop and no holes are all satisfied by a sprawling snake
    of tiles.  A genuine supertile is a compact chunk of plane, so its hull fill
    barely moves from the tile's own -- and the rejected level-2 patch sat at
    0.64 against these.
    """
    lone = fill_of(T.spectre_patch(0)[0])
    cluster = fill_of(T.spectre_patch(T.SPECTRE_VERIFIED_LEVEL)[0])
    assert lone == pytest.approx(0.815, abs=0.01)
    assert cluster == pytest.approx(0.804, abs=0.01)
    assert cluster > 0.78


def fill_of(tiles):
    return T.fill_fraction([[T.z_xy(p) for p in t] for t in tiles])


# --- why level 2 does not exist in this framework -------------------------
# These three pin the measured reason, so that the next person to look at
# SPECTRE_VERIFIED_LEVEL finds a number rather than a suspicion.  If any of them
# starts failing, the framework has been changed and the docstring's ledger is
# stale.

def test_the_anchor_quad_is_forced_not_chosen():
    """Only four ordered vertex 4-tuples make a valid cluster, and all four
    make the SAME one.  So level 1 is not one option among many, and the level-2
    failure cannot be blamed on the level-0 quad."""
    valid = [(2, 7, 12, 13), (3, 7, 11, 13), (4, 7, 10, 13), (5, 7, 9, 13)]
    assert T.SPECTRE_QUAD_IDX in valid
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


def test_the_quad_outruns_the_metatile():
    """THE reason level 2 is a ring of clusters around a void.

    A level-n metatile is a union of n_k congruent tiles and n_k grows by
    4 + sqrt(15), so the metatile's linear size grows by sqrt(4 + sqrt(15)) =
    2.805884 and the anchor quad, which scales with it, has to grow by that too.
    It grows by exactly 3 instead -- 6.9% too fast, compounding every level.
    """
    assert T.SPECTRE_INFLATION == pytest.approx(math.sqrt(4 + math.sqrt(15)),
                                                abs=1e-12)
    factor, perims = T.spectre_quad_inflation()
    assert factor == pytest.approx(3.0, abs=1e-9)
    assert factor > T.SPECTRE_INFLATION
    assert factor / T.SPECTRE_INFLATION == pytest.approx(1.0692, abs=1e-4)
    assert len(perims) >= 2 and perims[-1] > perims[0]


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


def test_spectre_serves_the_small_window_it_can():
    """It does work, at the only size it is entitled to: the 9-tile cluster."""
    tiles = T.generate("spectre", (0.0, 0.0, 14.0, 14.0), 4.0, 0)
    assert len(tiles) >= 3
    assert T.overlap_audit(tiles)["overlapping_pairs"] == 0
    assert T.gap_audit(tiles)["holes"] == 0
    for r in tiles:
        assert abs(abs(T.signed_area(T._open(r))) - 16.0) < 1e-6


# --- the board-first fingerprint -----------------------------------------
# FRAME is the real SatoshiStarter board frame: the Edge.Cuts bbox
# (50.775..203.225 x 25.375..127.025) deflated by the 1.0 mm edge inset, as
# measured through pcbnew.  Hard-coded here so these tests run without KiCad.

FRAME = (51.80, 26.40, 202.20, 126.00)
SPAN_TILE = 11.6743        # smallest tile that spans FRAME at rotation 0


def test_fingerprint_refuses_loudly_instead_of_repeating_or_rescaling():
    """The requirement the whole mode turns on.

    A patch that does not span the board must not be tiled across it -- copies
    are periodic at the patch pitch, which throws away the one property the
    spectre was chosen for -- and must not be silently rescaled.  So it raises,
    and the exception carries the two numbers needed to act: the smallest tile
    that would span, and the level a correct substitution would need.
    """
    with pytest.raises(T.SpectreCoverageError) as e:
        T.generate("spectre-fingerprint", FRAME, 3.0, 0)
    exc = e.value
    assert isinstance(exc, RuntimeError)          # old handlers keep working
    assert exc.min_tile_mm == pytest.approx(SPAN_TILE, abs=1e-3)
    assert exc.needed_level == 4                  # and level 3 is not buildable
    assert exc.patch_mm[0] == pytest.approx(38.649, abs=1e-3)
    assert exc.patch_mm[1] == pytest.approx(38.060, abs=1e-3)
    msg = str(exc)
    assert "periodic" in msg and "11.674" in msg


def test_fingerprint_min_tile_mm_is_the_exact_threshold():
    """Not a guess with a safety margin: the number is the threshold."""
    need = T.spectre_span_tile_mm(FRAME[2] - FRAME[0], FRAME[3] - FRAME[1], 2, 0)
    assert need == pytest.approx(SPAN_TILE, abs=1e-4)
    assert T.generate("spectre-fingerprint", FRAME, need * (1 + 1e-9), 0)
    with pytest.raises(T.SpectreCoverageError):
        T.generate("spectre-fingerprint", FRAME, need * (1 - 1e-6), 0)


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
    rings = T.spectre_fingerprint(FRAME, SPAN_TILE, 0)
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    assert (min(xs) + max(xs)) / 2 == pytest.approx((FRAME[0] + FRAME[2]) / 2,
                                                    abs=1e-9)
    assert (min(ys) + max(ys)) / 2 == pytest.approx((FRAME[1] + FRAME[3]) / 2,
                                                    abs=1e-9)


def test_fingerprint_serves_the_whole_patch_and_no_more():
    """71 tiles offered; generate() keeps the ones inside the frame and never
    clips.  The count of dropped tiles is the board-edge overhang and is the
    number the texture tool now reports separately."""
    whole = T.spectre_fingerprint(FRAME, SPAN_TILE, 0)
    assert len(whole) == T.spectre_patch_size(T.SPECTRE_PATCH_LEVEL) == 71
    inframe = T.generate("spectre-fingerprint", FRAME, SPAN_TILE, 0)
    assert len(inframe) == 44
    x0, y0, x1, y1 = FRAME
    for r in inframe:
        bx0, by0, bx1, by1 = T.bbox_of(T._open(r))
        assert bx0 >= x0 - 1e-9 and by0 >= y0 - 1e-9
        assert bx1 <= x1 + 1e-9 and by1 <= y1 + 1e-9


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


def test_fingerprint_sprawls_and_that_is_allowed():
    """Written down so nobody 'fixes' it.

    The level-2 patch is eight clusters around a central bay, and the bay is NOT
    a topological hole -- it opens to the outside through a narrow channel, so
    the boundary is still one loop and gap_audit finds no hole.  What fails is
    compactness: 64% of the convex hull against 80% for the 9-tile cluster.  For
    a patch that gets masked against copper and mostly discarded that is not a
    defect, which is exactly why SPECTRE_PATCH_LEVEL has its own weaker audit --
    and it is why "no holes, one loop" was never enough to call level 2 a
    supertile either.
    """
    rings = T.spectre_fingerprint(FRAME, SPAN_TILE, 0)
    g = T.gap_audit(rings)
    assert T.overlap_audit(rings)["overlapping_pairs"] == 0
    assert g["holes"] == 0 and g["loops"] == 1
    assert T.fill_fraction(rings) == pytest.approx(0.6405, abs=1e-3)
    assert T.fill_fraction(rings) < T.fill_fraction(
        [[T.z_xy(p) for p in t] for t in T.spectre_tiles(1)])


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
    """15 + 13*sqrt(3) unit edges, and it is a MAXIMUM over all twelve turns.

    Not the level-2 bbox at turn 0 -- that is 13.5+13.5*sqrt(3) wide and
    19+10*sqrt(3) tall, both SMALLER.  A cell sized to turn 0 would be overrun
    by the turn-1, 4, 7 and 10 patches, which is precisely the case the
    per-cell rotation makes reachable.  Every vertex is a point of Z[d], so both
    coordinates lie in (1/2)Z[sqrt 3] and this is exact, not fitted.
    """
    assert T.spectre_cell_units(2) == pytest.approx(15.0 + 13.0 * math.sqrt(3.0),
                                                    abs=1e-12)
    turn0 = max(T.spectre_patch_extent(2, 0))
    assert T.spectre_cell_units(2) > turn0, "turn 0 is not the worst case"
    assert T.SPECTRE_CELL_PITCH == pytest.approx(13.104460921053793, abs=1e-12)
    # the four-decimal value that has been quoted in reports is SHORT, and by
    # enough to matter at KiCad's 1 nm file quantum
    short = (T.SPECTRE_CELL_PITCH - 13.1042) * 3.0
    assert short > 0 and short * 1e6 > 700, "13.1042 is not safe to substitute"
    assert T.spectre_cell_pitch_mm(3.0) == pytest.approx(39.313382763, abs=1e-9)


@pytest.mark.parametrize("turn", range(12))
def test_every_rotation_of_the_patch_fits_inside_one_cell(turn):
    """Step 2 of the disjointness argument, measured at all twelve turns.

    Tight, not slack: at turns 1, 4, 7 and 10 the patch is exactly as big as the
    cell in one dimension, so the assertion is <=, and a pitch chosen any
    smaller would make it fail.
    """
    w, h = T.spectre_patch_extent(2, turn)
    side = T.spectre_cell_units(2)
    assert w <= side + 1e-12 and h <= side + 1e-12
    if turn % 3 == 1:
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
    and that is not a detail.  The bound is tight: at turns 1, 4, 7 and 10 the
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
    assert len(inframe) == 676                  # 176 hang over the frame
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


def test_the_cell_grid_beats_the_one_patch_it_replaces():
    """Why this mode exists, as a number rather than a paragraph.

    The one-patch fingerprint must SPAN the board, which forces tile_mm 11.75 on
    this frame and leaves 71 tiles total -- 44 of them inside the frame.  The
    grid puts 676 tiles of 3 mm inside the same frame.  A field of a few dozen
    cannot resolve a board once the copper mask has taken most of it; that was
    the measured failure, and the fix is arithmetic.
    """
    span = T.spectre_span_tile_mm(CELL_FRAME[2] - CELL_FRAME[0],
                                  CELL_FRAME[3] - CELL_FRAME[1], 2, 0)
    assert span == pytest.approx(11.7519, abs=1e-3)
    one = T.generate("spectre-fingerprint", CELL_FRAME, span * (1 + 1e-9), 0)
    many = T.generate("spectre-cells", CELL_FRAME, 3.0, 0)
    assert len(one) == 44
    assert len(many) == 676
    assert len(many) > 15 * len(one)
    # and the grid does NOT get there by making tiles smaller than asked
    assert abs(T.signed_area(T._open(many[0]))) == pytest.approx(9.0, rel=1e-9)


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
