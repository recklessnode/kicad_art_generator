"""Tests for the pure-geometry half of tools/texture_board.py.

texture_board.py needs pcbnew, which only exists inside KiCad's bundled Python,
and that interpreter has no pytest. So the module is written to IMPORT cleanly
without pcbnew (HAVE_PCBNEW goes False and only BoardIngest is unusable), and
everything that can be tested without a board lives in free functions. This file
tests those. The board-dependent behaviour is verified by measurement against
SatoshiStarter instead -- see the sweep tables in the module docstring.

The one thing worth stating plainly: `parse_rect` and `corridor_quad` are the
only places where an operator's numbers turn into geometry, so a silent sign or
ordering error there would move an exclusion zone somewhere else on the board
without any error message. That is what these tests are for.
"""

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import texture_board as tb


# --- parse_rect ---------------------------------------------------------------

def test_parse_rect_normalises_corner_order():
    """Either diagonal must give the same rectangle; operators type both."""
    a = tb.parse_rect("10,20,30,40")
    b = tb.parse_rect("30,40,10,20")
    c = tb.parse_rect("30,20,10,40")
    assert a == (10.0, 20.0, 30.0, 40.0)
    assert a == b == c


def test_parse_rect_tolerates_spaces_and_negatives():
    assert tb.parse_rect(" -5 , -2 , 5 , 2 ") == (-5.0, -2.0, 5.0, 2.0)


@pytest.mark.parametrize("bad", [
    "1,2,3",              # too few
    "1,2,3,4,5",          # too many
    "1,2,x,4",            # not a number
    "",                   # empty
])
def test_parse_rect_rejects_malformed(bad):
    with pytest.raises(ValueError):
        tb.parse_rect(bad)


@pytest.mark.parametrize("degenerate", ["10,20,10,40", "10,20,30,20"])
def test_parse_rect_rejects_zero_area(degenerate):
    """A zero-width rect subtracts nothing, so it must not pass silently."""
    with pytest.raises(ValueError):
        tb.parse_rect(degenerate)


# --- corridor_quad -----------------------------------------------------------

def test_corridor_quad_area_is_length_times_width():
    p0, p1, hw = (0.0, 0.0), (10.0, 0.0), 2.0
    quad = tb.corridor_quad(p0, p1, hw)
    assert len(quad) == 4
    assert tb.polygon_area_mm2(quad) == pytest.approx(10.0 * 2 * hw)


def test_corridor_quad_is_symmetric_about_the_segment():
    quad = tb.corridor_quad((0.0, 0.0), (10.0, 0.0), 3.0)
    ys = sorted({round(y, 9) for _, y in quad})
    assert ys == [-3.0, 3.0]


def test_corridor_quad_area_is_orientation_independent():
    """The 51.6 mm VRM->ASIC run is not axis-aligned; area must not care."""
    hw = 4.0
    for angle in (0, 17, 45, 90, 133, 180, 271):
        r = math.radians(angle)
        p1 = (20.0 * math.cos(r), 20.0 * math.sin(r))
        quad = tb.corridor_quad((0.0, 0.0), p1, hw)
        assert tb.polygon_area_mm2(quad) == pytest.approx(20.0 * 2 * hw, rel=1e-9)


def test_corridor_quad_reversing_the_segment_gives_the_same_region():
    a = tb.corridor_quad(tb.CORRIDOR_L1, tb.CORRIDOR_U9, 6.0)
    b = tb.corridor_quad(tb.CORRIDOR_U9, tb.CORRIDOR_L1, 6.0)
    assert sorted(round(v, 9) for pt in a for v in pt) == \
           sorted(round(v, 9) for pt in b for v in pt)


def test_corridor_quad_rejects_coincident_endpoints():
    with pytest.raises(ValueError):
        tb.corridor_quad((1.0, 1.0), (1.0, 1.0), 5.0)


def test_measured_corridor_length():
    """L1 (151.5, 75.5) -> U9 (100.0, 72.5) was measured at 51.6 mm."""
    assert tb.corridor_length_mm() == pytest.approx(51.6, abs=0.05)


# --- the board-specific constants -------------------------------------------

def test_hs1_true_envelope_matches_the_measurement():
    """47.56 x 47.55 mm, against the footprint's 176.2 mm2 of standoff bosses.

    If this drifts, the front centre of the board silently becomes texturable
    underneath a heatsink. See defect #55.
    """
    x0, y0, x1, y1 = tb.HS1_TRUE_ENVELOPE
    assert (x1 - x0) == pytest.approx(47.56, abs=0.005)
    assert (y1 - y0) == pytest.approx(47.55, abs=0.005)
    assert tb.polygon_area_mm2(tb.rect_corners(tb.HS1_TRUE_ENVELOPE)) \
        == pytest.approx(2261.5, abs=1.0)


def test_hs1_spurious_back_silk_is_not_the_true_envelope():
    """The footprint's 40 mm back-silk rectangle is recorded only to be ignored."""
    assert tb.HS1_SPURIOUS_BACK_SILK != tb.HS1_TRUE_ENVELOPE
    sx0, sy0, sx1, sy1 = tb.HS1_SPURIOUS_BACK_SILK
    tx0, ty0, tx1, ty1 = tb.HS1_TRUE_ENVELOPE
    # it is strictly inside the true envelope, i.e. trusting it under-protects
    assert tx0 < sx0 and ty0 < sy0 and sx1 < tx1 and sy1 < ty1
    assert (sx1 - sx0) == pytest.approx(40.16, abs=0.005)


def test_corridor_default_half_width_actually_reaches_ground_copper():
    """Measured: below ~8 mm the band lies wholly inside the VCORE pour and
    removes 0.0 mm2 from GNDREF on F.Cu, In1.Cu and B.Cu alike. A default that
    protects nothing is worse than no default, so it must stay above that."""
    assert tb.IngestOptions().corridor_half_width_mm >= 8.0


def test_side_layer_map_covers_all_four_copper_layers():
    flat = [l for ls in tb.SIDE_LAYERS.values() for l in ls]
    assert sorted(flat) == ["B.Cu", "F.Cu", "In1.Cu", "In2.Cu"]
    assert len(flat) == len(set(flat)), "a layer must belong to exactly one side"


# --- unit conversion ---------------------------------------------------------

def test_mm_to_nm_rounds_rather_than_truncates():
    """0.15 mm must not become 149999 nm; a truncating converter loses a nm per
    call and the error accumulates across an inflate chain."""
    assert tb.mm_to_nm(0.15) == 150000
    assert tb.mm_to_nm(-0.15) == -150000
    assert tb.mm_to_nm(0.0000004) == 0
    assert tb.mm_to_nm(0.0000006) == 1


def test_nm_mm_round_trip():
    for v in (0.0, 0.1, 1.0, 47.56, 152.45, -12.75):
        assert tb.nm_to_mm(tb.mm_to_nm(v)) == pytest.approx(v, abs=1e-6)


# --- shoelace ----------------------------------------------------------------

def test_polygon_area_ignores_winding_direction():
    cw = [(0, 0), (0, 10), (10, 10), (10, 0)]
    ccw = list(reversed(cw))
    assert tb.polygon_area_mm2(cw) == pytest.approx(100.0)
    assert tb.polygon_area_mm2(ccw) == pytest.approx(100.0)


def test_polygon_area_of_degenerate_input_is_zero():
    assert tb.polygon_area_mm2([]) == 0.0
    assert tb.polygon_area_mm2([(0, 0)]) == 0.0
    assert tb.polygon_area_mm2([(0, 0), (1, 1)]) == 0.0


# --- option surface ----------------------------------------------------------

def test_default_options_are_all_non_negative_clearances():
    o = tb.IngestOptions()
    for name in ("clr_courtyard_mm", "clr_pad_mm", "clr_track_mm", "clr_via_mm",
                 "clr_hole_mm", "clr_zone_mm", "clr_hs_mm", "clr_extra_mm",
                 "edge_inset_mm", "corridor_half_width_mm", "min_region_mm2"):
        assert getattr(o, name) >= 0, name


def test_cli_maps_every_clearance_flag_onto_the_options():
    argv = ["--board", "x.kicad_pcb", "--clr-pad", "0.75", "--clr-track", "0.31",
            "--clr-courtyard", "1.25", "--clr-zone", "0.9", "--clr-via", "0.44",
            "--clr-hole", "0.22", "--clr-hs", "2.5", "--clr-extra", "0.6",
            "--edge-inset", "3.0", "--corridor-half-width", "15.0",
            "--min-region-mm2", "4.0", "--pour-net", "GNDREF",
            "--hs1-sides", "both", "--corridor-front-only",
            "--exclude", "1,2,3,4", "--exclude", "10,10,20,20"]
    o = tb.opts_from_args(tb.build_parser().parse_args(argv))
    assert o.clr_pad_mm == 0.75
    assert o.clr_track_mm == 0.31
    assert o.clr_courtyard_mm == 1.25
    assert o.clr_zone_mm == 0.9
    assert o.clr_via_mm == 0.44
    assert o.clr_hole_mm == 0.22
    assert o.clr_hs_mm == 2.5
    assert o.clr_extra_mm == 0.6
    assert o.edge_inset_mm == 3.0
    assert o.corridor_half_width_mm == 15.0
    assert o.min_region_mm2 == 4.0
    assert o.pour_net == "GNDREF"
    assert o.hs1_sides == "both"
    assert o.corridor_all_layers is False
    assert o.excludes == [(1.0, 2.0, 3.0, 4.0), (10.0, 10.0, 20.0, 20.0)]


def test_cli_defaults_keep_the_hs1_guard_on_and_the_corridor_everywhere():
    o = tb.opts_from_args(tb.build_parser().parse_args(["--board", "x.kicad_pcb"]))
    assert o.hs1_sides == "front"
    assert o.corridor_all_layers is True
    assert o.refill is True


def test_no_refill_flag_turns_the_in_process_refill_off():
    """Refilling is the default because NeedRefill() is not persisted and so
    cannot detect a stale file -- measured False on 15/15 zones of both a stale
    and a freshly refilled copy of this board."""
    o = tb.opts_from_args(
        tb.build_parser().parse_args(["--board", "x.kicad_pcb", "--no-refill"]))
    assert o.refill is False


def test_board_ingest_without_pcbnew_says_so_instead_of_crashing_obscurely():
    if tb.HAVE_PCBNEW:
        pytest.skip("pcbnew present; the no-pcbnew message cannot be provoked")
    with pytest.raises(RuntimeError, match="pcbnew"):
        tb.BoardIngest("nonexistent.kicad_pcb", tb.IngestOptions())
