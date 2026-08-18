"""Tests for the slot/tie-neck half of tools/texture_board.py.

Everything here is pure geometry and graph theory, so it runs in the project's
own environment without pcbnew. The pcbnew half is verified against the real
board instead, because a mock zone filler would not have found any of the four
things that actually went wrong.

Each test below that pins a trap names the measurement that motivated it.
"""
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import texture_board as tb          # noqa: E402
import tilings                      # noqa: E402


# --- fixtures -----------------------------------------------------------------

def hex_patch(w=20.0, tile=2.0):
    return tilings.generate("hex", (0, 0, w, w), tile, 0)


# --- edge de-duplication ------------------------------------------------------

def test_shared_walls_are_welded_once():
    rings = hex_patch()
    edges, st = tb.tile_edges(rings)
    assert st["directed_edges"] == 6 * len(rings)
    assert st["unique_edges"] == len(edges)
    assert st["shared_edges"] > 0
    # no wall appears twice, in either direction
    keys = [tuple(sorted((tb._wkey(a), tb._wkey(b)))) for a, b in edges]
    assert len(set(keys)) == len(keys)


def test_euler_characteristic_of_the_welded_graph():
    """V - E + F == 1 for a disc-like patch. This is the de-dup's real test.

    If a shared wall were counted twice, E would be too large and this would
    fail. Nothing else in the suite notices a doubled wall, because a doubled
    slot unions to the same geometry -- it only corrupts the wall GRAPH, and a
    doubled wall is a 2-cycle that would make the forest test reject good input.
    """
    rings = hex_patch()
    edges, _ = tb.tile_edges(rings)
    V = len({tb._wkey(p) for e in edges for p in e})
    assert V - len(edges) + len(rings) == 1


def test_degenerate_walls_are_dropped_not_cut():
    edges, st = tb.tile_edges([[(0, 0), (1, 0), (1, 0), (0, 1), (0, 0)]])
    assert st["degenerate_edges"] == 1
    assert st["unique_edges"] == 3


# --- the connectivity theorem -------------------------------------------------

def test_uncut_tiles_are_cyclic_and_are_caught():
    """--neck-style none must be rejected by the graph, before any board."""
    rings = hex_patch()
    edges, _ = tb.tile_edges(rings)
    joining, st = tb.wall_cut_audit(edges, 0.5, "none", 0.15)
    assert len(joining) == len(edges)
    ok, _, _ = tb.wall_graph_is_forest(joining)
    assert ok is False
    assert st["joining"] == len(edges)


@pytest.mark.parametrize("style", ["midedge", "vertex", "both"])
def test_necked_styles_leave_no_wall_joining_its_endpoints(style):
    """The property that makes a necked style safe on ANY region shape.

    Not "the wall graph is acyclic" -- that is the weaker claim that let
    --neck-style forest through. If no wall joins its endpoints then no
    continuous slot path exists at all, so no path can touch the pour boundary
    twice either, and that is what makes the guarantee shape-independent.
    """
    rings = hex_patch(tile=4.0)
    edges, _ = tb.tile_edges(rings)
    cx = tb.cap_extend_mm(0.25, "round")
    joining, st = tb.wall_cut_audit(edges, 0.4, style, 0.05, cx)
    assert joining == []
    assert st["cut"] > 0
    ok, _, _ = tb.wall_graph_is_forest(joining)
    assert ok is True


def test_spanning_forest_is_a_tree_but_that_is_not_enough():
    """Acyclic, exactly V-1 walls -- and still not a safety guarantee.

    The measured failure on SatoshiStarter is recorded in the module banner: this
    wall set is a genuine spanning tree and it still isolated 12.922 and 8.456
    mm2 against the pour's eastern edge. The test asserts what the function
    promises (a tree) and asserts that every wall in it still joins its
    endpoints, which is the property that makes it shape-dependent.
    """
    rings = hex_patch()
    edges, _ = tb.tile_edges(rings)
    V = len({tb._wkey(p) for e in edges for p in e})
    forest = tb.spanning_forest(edges, seed=0)
    ok, nv, ncomp = tb.wall_graph_is_forest(forest)
    assert ok is True
    assert nv == V
    assert ncomp == 1
    assert len(forest) == V - 1
    joining, _ = tb.wall_cut_audit(forest, 0.4, "forest", 0.05)
    assert len(joining) == len(forest)      # every wall runs end to end


def test_spanning_forest_is_deterministic_per_seed():
    rings = hex_patch()
    edges, _ = tb.tile_edges(rings)
    assert tb.spanning_forest(edges, 7) == tb.spanning_forest(edges, 7)
    assert tb.spanning_forest(edges, 7) != tb.spanning_forest(edges, 8)


def test_forest_test_rejects_a_doubled_wall():
    e = ((0.0, 0.0), (1.0, 0.0))
    assert tb.wall_graph_is_forest([e])[0] is True
    assert tb.wall_graph_is_forest([e, e])[0] is False


# --- the cap-overhang trap ----------------------------------------------------

def test_round_caps_overhang_and_neck_mm_compensates():
    """THE bug that shipped a broken board once. neck_mm is COPPER, not a gap.

    Measured consequence of getting this wrong: --slot-mm 0.25 --neck-mm 0.40
    with round caps left 0.40 - 2*0.125 = 0.15 mm of copper, under the pour's
    0.25 mm min_thickness, so the filler deleted every neck and then every cell
    -- 355.7 mm2 of copper gone and hexagonal bites in the pour edge.
    """
    cx = tb.cap_extend_mm(0.25, "round")
    assert cx == 0.125
    assert tb.cap_extend_mm(0.25, "square") == 0.0

    a, b = (0.0, 0.0), (2.4, 0.0)
    cuts = tb.neck_cuts(a, b, 0.40, "midedge", 0.05, cx)
    gaps = tb.cut_gaps_mm(a, b, cuts)
    assert len(gaps) == 1
    assert gaps[0] == pytest.approx(0.40 + 2 * cx)          # centreline gap
    assert gaps[0] - 2 * cx == pytest.approx(0.40)          # surviving copper

    sq = tb.neck_cuts(a, b, 0.40, "midedge", 0.05, 0.0)
    assert tb.cut_gaps_mm(a, b, sq)[0] == pytest.approx(0.40)


def test_audit_reports_copper_bridge_not_centreline_gap():
    rings = hex_patch(tile=4.0)
    edges, _ = tb.tile_edges(rings)
    cx = tb.cap_extend_mm(0.3, "round")
    _, st = tb.wall_cut_audit(edges, 0.45, "midedge", 0.05, cx)
    assert st["bridge_mm"] == pytest.approx(0.45)
    assert st["min_gap_mm"] == pytest.approx(0.45 + 2 * cx)


def test_vertex_style_reports_the_narrowest_single_bridge():
    """Two end necks of 0.4 must not be reported as one 0.8 gap."""
    a, b = (0.0, 0.0), (3.0, 0.0)
    cuts = tb.neck_cuts(a, b, 0.4, "vertex", 0.05, 0.0)
    gaps = tb.cut_gaps_mm(a, b, cuts)
    assert gaps == pytest.approx([0.4, 0.4])


# --- dropping slots is always safe -------------------------------------------

def test_a_wall_too_short_to_neck_yields_no_slot():
    """Dropping a slot only ADDS copper, so it can never break connectivity."""
    a, b = (0.0, 0.0), (0.5, 0.0)
    assert tb.neck_cuts(a, b, 0.4, "midedge", 0.15, 0.125) == []
    assert tb.neck_cuts(a, b, 0.4, "vertex", 0.15, 0.125) == []


def test_min_cut_drops_short_segments_only():
    a, b = (0.0, 0.0), (4.0, 0.0)
    assert len(tb.neck_cuts(a, b, 0.4, "midedge", 0.15, 0.0)) == 2
    assert tb.neck_cuts(a, b, 0.4, "midedge", 2.0, 0.0) == []


def test_unknown_style_raises():
    with pytest.raises(ValueError):
        tb.neck_cuts((0, 0), (1, 0), 0.4, "spirals", 0.1)


# --- slot bodies --------------------------------------------------------------

def test_square_cap_area_is_exact():
    r = tb.stadium_ring((0, 0), (10, 0), 0.25, "square")
    assert abs(tb.polygon_area_mm2(r)) == pytest.approx(2.5, rel=1e-12)


def test_round_cap_area_approaches_the_stadium():
    for seg in (8, 32, 128):
        r = tb.stadium_ring((0, 0), (10, 0), 0.25, "round", seg)
        want = 2.5 + math.pi * 0.125 ** 2
        assert abs(tb.polygon_area_mm2(r)) == pytest.approx(want, rel=3.0 / seg ** 2)


def test_slot_width_is_measured_perpendicular_at_any_angle():
    for ang in (0.0, 0.3, 1.0, 2.2):
        a = (0.0, 0.0)
        b = (5.0 * math.cos(ang), 5.0 * math.sin(ang))
        r = tb.stadium_ring(a, b, 0.4, "square")
        assert abs(tb.polygon_area_mm2(r)) == pytest.approx(5.0 * 0.4, rel=1e-12)


def test_zero_length_wall_makes_no_body():
    assert tb.stadium_ring((1, 1), (1, 1), 0.25, "round") == []


def test_slot_length_and_gaps_are_consistent():
    rings = hex_patch(tile=4.0)
    edges, _ = tb.tile_edges(rings)
    cx = tb.cap_extend_mm(0.25, "round")
    for a, b in edges[:40]:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        cuts = tb.neck_cuts(a, b, 0.4, "midedge", 0.05, cx)
        assert tb.slot_length_mm(cuts) + sum(tb.cut_gaps_mm(a, b, cuts)) == \
            pytest.approx(L)


# --- board-first framing ------------------------------------------------------
# Everything here is pure: the frame decision, the tile ledger arithmetic and the
# refusal path all run without pcbnew, which is what lets them be tested at all.

FRAME = (51.80, 26.40, 202.20, 126.00)      # SatoshiStarter, inset 1.0 mm
SPAN_TILE = 11.6743


def test_the_board_first_kinds_are_named_and_gated():
    """Handing a board-first kind a per-layer permitted bbox would destroy the
    only property it has, so the choice is made by kind and not by the caller."""
    assert tilings.kinds().count("spectre-fingerprint") == 1
    assert "spectre-fingerprint" in tb.BOARD_FIRST_KINDS
    assert tb.uses_board_frame("spectre-fingerprint") is True
    assert tb.uses_board_frame("hex") is False
    # and the override is explicit in both directions
    assert tb.uses_board_frame("hex", "board") is True
    assert tb.uses_board_frame("spectre-fingerprint", "permitted") is False


def test_default_options_leave_every_lattice_run_unchanged():
    """The documented hex run must not move because a new kind was added."""
    t = tb.TextureOptions()
    assert t.tile_frame == "auto"
    assert tb.uses_board_frame(t.tiling, t.tile_frame) is False


class _FakeBBox:
    def __init__(self, l, t, r, b):
        self._v = (l, t, r, b)

    def GetLeft(self):
        return self._v[0]

    def GetTop(self):
        return self._v[1]

    def GetRight(self):
        return self._v[2]

    def GetBottom(self):
        return self._v[3]


class _FakePoly:
    def __init__(self, bb):
        self._bb = bb

    def BBox(self):
        return self._bb


def test_board_frame_is_the_deflated_outline_bbox_in_mm():
    poly = _FakePoly(_FakeBBox(51800000, 26400000, 202200000, 126000000))
    assert tb.board_frame_mm(poly) == pytest.approx(FRAME)


def test_tile_ledger_counts_the_stage_that_used_to_be_invisible():
    """offered -> outside the frame -> masked -> placed.

    The old report counted tiles only AFTER tilings.generate()'s frame filter, so
    under a board-anchored frame every tile hanging over the board outline
    vanished between two numbers that both looked right. On this board's frame at
    the smallest spanning tile, that is 27 of the 71.
    """
    opts = tb.TextureOptions(tiling="spectre-fingerprint", tile_mm=SPAN_TILE,
                             seed=0)
    offered = tb.tiles_offered(tilings, opts, FRAME)
    inframe = tilings.generate("spectre-fingerprint", FRAME, SPAN_TILE, 0)
    assert offered == 71
    assert len(inframe) == 44
    assert offered - len(inframe) == 27


def test_the_refusal_stops_the_run_with_its_own_exit_code(monkeypatch, tmp_path):
    """THE LOUD-FAILURE PATH, end to end through the CLI wiring.

    No board may be written, nothing may be rescaled, and the exit code must be
    distinguishable from a connectivity failure (3) or a DRC failure (4).
    """
    parser = tb.build_parser()
    out = tmp_path / "never_written.kicad_pcb"
    a = parser.parse_args(["--board", "b.kicad_pcb", "--texture-mode", "add",
                           "--tiling", "spectre-fingerprint", "--tile-mm", "3",
                           "--out", str(out)])
    assert a.tile_frame == "auto"

    def boom(*args, **kw):
        raise tilings.SpectreCoverageError(
            "refused", frame_mm=(150.4, 99.6), patch_mm=(38.649, 38.060),
            tile_mm=3.0, min_tile_mm=SPAN_TILE, needed_level=4, levels=2)

    monkeypatch.setattr(tb, "run_texture", boom)
    rc = tb.main_texture(a, parser, object())
    assert rc == 5
    assert not out.exists()


def test_the_cli_offers_the_frame_override():
    a = tb.build_parser().parse_args(["--board", "b.kicad_pcb", "--tiling",
                                      "hex", "--tile-frame", "board",
                                      "--out", "o.kicad_pcb"])
    assert tb.tex_opts_from_args(a).tile_frame == "board"
    assert tb.uses_board_frame("hex", "board") is True


# --- the cell grid, through the texture tool ---------------------------------

CELL_FRAME = (51.30, 25.90, 202.70, 126.50)     # SatoshiStarter, inset 0.5 mm


def test_every_registered_tiling_is_reachable_from_the_command_line():
    """THE DEFECT THIS TEST EXISTS FOR, and it cost the whole cell-grid mode.

    --tiling's choices were a list retyped by hand next to argparse. spectre-
    cells was registered in tilings.py, named in BOARD_FIRST_KINDS, covered by
    uses_board_frame() and exercised by unit tests -- and argparse still
    rejected it, so the mode could not be run at all. Every test passed while
    the feature was unreachable, because no test crossed the CLI boundary.

    A hand-maintained mirror of an extension point is a defect waiting for the
    next extension, so the choices now come from the registry and this asserts
    the two can never diverge again.
    """
    action = [x for x in tb.build_parser()._actions if x.dest == "tiling"][0]
    assert sorted(action.choices) == sorted(tilings.kinds())
    for kind in tilings.kinds():
        a = tb.build_parser().parse_args(
            ["--board", "b.kicad_pcb", "--tiling", kind, "--out", "o.kicad_pcb"])
        assert tb.tex_opts_from_args(a).tiling == kind


def test_the_cell_grid_is_board_first_like_the_one_patch_mode():
    """It fills a window, so nothing about it raises -- and that is the trap.

    spectre-fingerprint announces its contract by refusing a frame it cannot
    span. spectre-cells never refuses, so the only thing keeping it anchored to
    the board is its membership of BOARD_FIRST_KINDS. Handed a per-layer
    permitted bbox instead, its field would move whenever the copper moved and
    two runs could not be compared -- the exact defect the board-first framing
    was built to remove.
    """
    assert tilings.kinds().count("spectre-cells") == 1
    assert "spectre-cells" in tb.BOARD_FIRST_KINDS
    assert tb.uses_board_frame("spectre-cells") is True
    assert tb.uses_board_frame("spectre-cells", "permitted") is False
    assert "BOARD-FIRST" in tilings.KINDS["spectre-cells"].note.upper()


def test_the_cell_grid_ledger_accounts_for_every_offered_tile():
    """offered -> outside the frame -> (masked) -> placed, with nothing clipped.

    852 = 71 tiles x 12 cells, and the 176 that hang over the board outline are
    DROPPED whole. The ledger has to reconcile exactly, because the stage that
    used to be invisible is precisely where a clipped tile would hide.
    """
    opts = tb.TextureOptions(tiling="spectre-cells", tile_mm=3.0, seed=0)
    offered = tb.tiles_offered(tilings, opts, CELL_FRAME)
    inframe = tilings.generate("spectre-cells", CELL_FRAME, 3.0, 0)
    assert offered == 71 * 12 == 852
    assert len(inframe) == 676
    assert offered - len(inframe) == 176
    # the ledger's arithmetic, not just its inputs
    assert max(0, offered - len(inframe)) == 176


@pytest.mark.skipif(not tb.HAVE_PCBNEW,
                    reason="place_tiles_by_fragment needs pcbnew's "
                           "SHAPE_POLY_SET; run under KiCad's bundled Python")
def test_the_tool_never_emits_a_partial_tile():
    """Requirement (a): complete spectres or nothing.

    place_tiles_by_fragment is the only gate between the generated field and the
    board, so this asserts on ITS output rather than on the generator's: a tile
    is kept whole or dropped, and every kept ring is still exactly tile_mm^2.

    Skipped without pcbnew rather than faked. A mock SHAPE_POLY_SET would test
    the mock's containment rule, not KiCad's, and containment is the entire
    question here. The same property is measured on the real board by the run
    ledger, where offered = outside + masked + placed must reconcile exactly.
    """
    rings = tilings.generate("spectre-cells", CELL_FRAME, 3.0, 0)
    poly = tb._sps()
    # one permitted fragment: a rectangle slicing through the middle of the grid
    tb._add_ring(poly, [(60.0, 40.0), (140.0, 40.0), (140.0, 90.0), (60.0, 90.0)])
    kept, dropped, worst, _, _ = tb.place_tiles_by_fragment(poly, rings)
    assert kept and dropped
    assert len(kept) + dropped == len(rings)
    assert worst <= 1e-6
    for r in kept:
        assert r in rings, "a kept tile is not one of the offered tiles"
        assert abs(tilings.signed_area(r[:-1])) == pytest.approx(9.0, rel=1e-9)
        x0, y0, x1, y1 = tilings.bbox_of(r[:-1])
        assert x0 >= 60.0 - 1e-9 and x1 <= 140.0 + 1e-9
        assert y0 >= 40.0 - 1e-9 and y1 <= 90.0 + 1e-9


def test_the_geometry_digest_is_what_a_reproducibility_check_compares():
    """Not the file. The emitted .kicad_pcb carries KiCad-assigned random UUIDs
    and will never hash equal between two runs; the tile geometry will.

    Also pins the quantum: a difference KiCad's 1 nm file resolution cannot
    represent must not be reported as one, and a difference of a single internal
    unit must be.

    The quantum half is measured on a SYNTHETIC ring at known coordinates, not
    on the spectre field. Nudging the real field sub-nanometre is not a valid
    probe: quantisation rounds half to even, so any vertex that happens to land
    on an exact half-nanometre flips bucket under an arbitrarily small nudge and
    the test fails for a reason that has nothing to do with the property.
    """
    rings = tilings.generate("spectre-cells", CELL_FRAME, 3.0, 0)
    d = tb.geometry_digest(rings)
    assert d == tb.geometry_digest(tilings.generate("spectre-cells",
                                                    CELL_FRAME, 3.0, 0))
    assert d != tb.geometry_digest(tilings.generate("spectre-cells",
                                                    CELL_FRAME, 3.0, 1))
    # 1.0 mm = 1000000 nm exactly, so the rounding is nowhere near a tie
    box = [[(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]]
    b = tb.geometry_digest(box)
    sub = [[(x + 4e-8, y) for x, y in r] for r in box]         # 0.04 nm
    assert tb.geometry_digest(sub) == b, "sub-quantum noise changed the digest"
    one_nm = [[(x + 1e-6, y) for x, y in r] for r in box]      # 1 nm
    assert tb.geometry_digest(one_nm) != b, "a 1 nm move went unnoticed"


def test_the_fingerprint_stamp_names_the_board_state():
    """An unlabelled fingerprint is indistinguishable from any other one.

    The stamp must carry enough to trace an image back to a board state, and it
    must not label the tile area simply "area": the tiles are inset by half a
    gutter before emission, so tile area and copper area differ by about 20% on
    this board and a bare label invites quoting the wrong one.
    """
    src = pathlib.Path(tb.__file__).read_text(encoding="utf-8")
    i = src.index("if a.fingerprint_png:")
    block = src[i:src.index("if a.texture_json:", i)]
    for key in ("tiling", "tile_mm", "level", "tiles", "tile-area",
                "edge-inset", "frame-inset", "seed", "layer", "board", "geom"):
        assert '("%s"' % key in block, key
    assert '("area"' not in block, "the ambiguous label is back"
    assert "NOT_QUITE_SUPERTILE" in block
    assert "supertile" in tb.NOT_QUITE_SUPERTILE
    assert "97" in tb.NOT_QUITE_SUPERTILE      # level 3 self-overlaps
    assert "0.6405" in tb.NOT_QUITE_SUPERTILE  # and it fails compactness


def test_a_wall_that_cuts_to_nothing_is_a_loud_failure_not_a_pass():
    """THE SILENT NO-OP, pinned at the arithmetic that produces it.

    Measured on SatoshiStarter with spectre-cells at --tile-mm 3.0 and the
    DEFAULTS: 233 walls on F.Cu, 0 cut, 0 keepout zones, 0.000 mm2 removed --
    and the run printed PASS on every connectivity check and exited 0. Every
    check was true, and every one was true because nothing had happened.

    A spectre edge is tile_mm/sqrt(3+3*sqrt3) long, so 1.0479 mm at tile 3.0.
    midedge cuts the two ends, and a round cap eats slot_mm/2 at each end of
    each cut, leaving (1.0479 - 0.5)/2 - 0.25 = 0.0239 mm -- under --min-cut-mm.
    """
    edge = 3.0 / math.sqrt(tilings.SPECTRE_UNIT_AREA)
    assert edge == pytest.approx(1.047891, abs=1e-6)
    cx = tb.cap_extend_mm(0.25, "round")
    assert cx == 0.125
    dead = tb.neck_cuts((0.0, 0.0), (edge, 0.0), 0.5, "midedge", 0.15, cx)
    assert dead == [], "the configuration that produced the no-op now cuts"
    span = (edge - 0.5) / 2.0 - 2.0 * cx
    assert span == pytest.approx(0.0239, abs=1e-4)

    # square caps, or a shorter neck, and the same wall cuts fine -- so the
    # guard must fire on the no-op, not on the tiling
    assert len(tb.neck_cuts((0.0, 0.0), (edge, 0.0), 0.4, "midedge", 0.15,
                            tb.cap_extend_mm(0.25, "square"))) == 2
    # and the lattice kind the documented runs use is nowhere near the edge
    hex_edge = math.sqrt(2.0 * 9.0 / (3.0 * math.sqrt(3.0)))
    assert hex_edge == pytest.approx(1.8612, abs=1e-4)
    assert len(tb.neck_cuts((0.0, 0.0), (hex_edge, 0.0), 0.4, "midedge",
                            0.15, cx)) == 2

    exc = tb.NoCutError("boom", layer="F.Cu", walls=233, wall_mm=edge,
                        neck_mm=0.5, slot_mm=0.25, cap="round",
                        min_cut_mm=0.15, span_mm=span)
    assert isinstance(exc, RuntimeError)          # old handlers keep working
    assert exc.walls == 233 and exc.layer == "F.Cu"


def test_the_no_cut_refusal_has_its_own_exit_code(monkeypatch, tmp_path):
    """Distinguishable from connectivity (3), DRC (4) and the spectre
    refusal (5), and it must not write a board."""
    parser = tb.build_parser()
    out = tmp_path / "never_written.kicad_pcb"
    a = parser.parse_args(["--board", "b.kicad_pcb", "--texture-mode",
                           "subtract", "--tiling", "spectre-cells",
                           "--tile-mm", "3", "--out", str(out)])

    def boom(*args, **kw):
        raise tb.NoCutError("F.Cu: 233 walls, 0 cut.", layer="F.Cu", walls=233,
                            wall_mm=1.047891, neck_mm=0.5, slot_mm=0.25,
                            cap="round", min_cut_mm=0.15, span_mm=0.0239)

    monkeypatch.setattr(tb, "run_texture", boom)
    rc = tb.main_texture(a, parser, object())
    assert rc == 6
    assert not out.exists()


def test_the_frame_inset_is_separable_from_the_copper_clearance():
    """A DRC clearance must not silently rewrite the art.

    edge_inset_mm is a copper-to-edge clearance AND, until it was split, the
    anchor for every board-first field -- so changing a design rule moved every
    tile. frame_inset_mm defaults to following it, which keeps documented runs
    reproducible, and can be pinned to hold the pattern still while the
    clearance moves. That separation is how the two effects get measured apart.
    """
    assert tb.IngestOptions().edge_inset_mm == 0.5     # the board's own rule
    assert tb.IngestOptions().frame_inset_mm is None   # = follow it
    a = tb.build_parser().parse_args(["--board", "b.kicad_pcb"])
    assert a.edge_inset == 0.5 and a.frame_inset is None
    b = tb.build_parser().parse_args(["--board", "b.kicad_pcb",
                                      "--edge-inset", "0.5",
                                      "--frame-inset", "1.0"])
    assert b.edge_inset == 0.5 and b.frame_inset == 1.0


# --- raster connected components ---------------------------------------------

def test_component_stats_counts_and_measures():
    np = pytest.importorskip("numpy")
    m = np.zeros((40, 40), dtype=bool)
    m[2:12, 2:12] = True                  # 10x10 px
    m[20:25, 20:30] = True                # 5x10 px
    n, areas, _ = tb.component_stats(m, px_per_mm=10.0, connectivity=4)
    assert n == 2
    assert areas == pytest.approx([1.0, 0.5])


def test_four_connectivity_splits_what_eight_joins():
    np = pytest.importorskip("numpy")
    m = np.zeros((10, 10), dtype=bool)
    m[2:4, 2:4] = True
    m[4:6, 4:6] = True                    # touches the first only diagonally
    assert tb.component_stats(m, 1.0, 4)[0] == 2
    assert tb.component_stats(m, 1.0, 8)[0] == 1


def test_a_ring_of_slot_isolates_and_a_necked_ring_does_not():
    """The whole design, at raster scale, with no board involved."""
    np = pytest.importorskip("numpy")
    for necked, want in ((False, 2), (True, 1)):
        m = np.ones((60, 60), dtype=bool)
        m[20:40, 20:22] = False           # four walls of a box
        m[20:40, 38:40] = False
        m[20:22, 20:40] = False
        m[38:40, 20:40] = False
        if necked:
            m[28:32, 20:22] = True        # one tie-neck in one wall
        assert tb.component_stats(m, 1.0, 4)[0] == want


def test_empty_mask_has_no_components():
    np = pytest.importorskip("numpy")
    assert tb.component_stats(np.zeros((8, 8), dtype=bool), 1.0)[0] == 0
