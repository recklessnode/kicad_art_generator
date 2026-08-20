"""verify_art.py reading a whole .kicad_pcb.

WHAT THESE PIN, AND WHY EACH ONE EXISTS
---------------------------------------
The harness could read .kicad_mod and nothing else, by three independent gates:
main() globbed *.kicad_mod, load_footprint() demanded a (footprint ...) root,
and GRAPHIC_HEADS listed only fp_* items. Everything a board can carry --
board-level gr_poly above all -- was therefore invisible to every check, and
the coupon boards shipped 981 of them without one being compared to a floor.

Three defects made that survivable-looking, and each has a test here:

  1. NOTHING READ A BOARD AT ALL.               test_board_loads_*
  2. min_width() is a convex-hull caliper.      test_concave_*
     On a traced letterform it answers with the glyph's overall width, not the
     0.117 mm stem the glyph is drawn with, so parsing boards WITHOUT fixing
     this would have produced a green min-feature check over the exact defect.
  3. The gap check compares ITEMS.              test_gap_inside_one_polygon_*
     A keyhole-bridged glyph is one polygon: its counter is bounded by the same
     ring as its outline, so the void inside it is intra-item and structurally
     unreachable. Every one of the six sub-floor gaps on the alpha coupon's
     front face is of that kind.

The synthetic boards below are all built here from constants. Nothing in this
file reads, embeds or reproduces any board or artwork from the product repo.
"""
import json
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ink_measure as IM                                      # noqa: E402
import verify_art as V                                        # noqa: E402


# --------------------------------------------------------------------------
# rigging
# --------------------------------------------------------------------------

LAYER_TABLE = """\t(layers
\t\t(0 "F.Cu" signal)
\t\t(4 "In1.Cu" signal)
\t\t(6 "In2.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(13 "F.Paste" user)
\t\t(15 "B.Paste" user)
\t\t(31 "F.CrtYd" user "F.Courtyard")
\t\t(35 "F.Fab" user)
\t\t(25 "Edge.Cuts" user)
\t)
"""

EDGE = """\t(gr_line (start -1 -1) (end 41 -1) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))
\t(gr_line (start 41 -1) (end 41 31) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))
\t(gr_line (start 41 31) (end -1 31) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))
\t(gr_line (start -1 31) (end -1 -1) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))
"""


def write_board(tmp_path, body, name="b", edge=True, setup="", pro=None):
    p = tmp_path / f"{name}.kicad_pcb"
    p.write_text(
        '(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n'
        '\t(generator_version "10.0")\n\t(general (thickness 1.6))\n'
        '\t(paper "A4")\n' + LAYER_TABLE
        + f"\t(setup (pad_to_mask_clearance 0){setup})\n"
        + (EDGE if edge else "") + body + "\n)\n", encoding="utf-8")
    if pro is not None:
        (tmp_path / f"{name}.kicad_pro").write_text(json.dumps(pro),
                                                    encoding="utf-8")
    return p


def poly(pts, layer="F.SilkS", fill="yes", width=0.0):
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return (f"\t(gr_poly (pts {xy}) (stroke (width {width}) (type default)) "
            f'(fill {fill}) (layer "{layer}"))')


def cfg(silk=0.15, copper=0.10, mask=0.10, hard=("silk", "copper", "mask")):
    pal = V.Palette(recipe_layers={"F.Cu", "F.SilkS", "F.Mask", "B.Cu",
                                   "B.SilkS", "B.Mask", "In1.Cu", "Edge.Cuts"},
                    floors={"silk": silk, "mask": mask, "copper": copper,
                            "buried": 0.5, "edge": 1.0},
                    buried_provisional=False, source="test", notes=[],
                    hard=set(hard))
    c = type("C", (), {})()
    c.palette = pal
    c.side = "front"
    c.allow_layers = set()
    c.strict = False
    c.clearance = True
    c.max_clearance_items = 50_000
    c.clearance_budget = 40_000_000
    c.max_report = 20
    c.render_svg = None
    c.outlier_mm = 1.0
    c.max_poly_pts = 2000
    c.ink = True
    c.ink_layers = None
    c.ink_max_segments = 250_000
    c.ink_budget = 4_000_000
    c.ink_measured_layers = set()
    c.fab = None
    c.tone_map = None
    c.cli = None
    c.kicad_version = "none"
    c.cli_major = 0
    return c


def text_of(check):
    return "\n".join([check.headline] + [d for d in check.details if d])


needs_shapely = pytest.mark.skipif(not IM.HAVE_SHAPELY,
                                   reason="shapely not installed")


# The shapes. A DUMBBELL is two blocks joined by a bridge whose width is the
# thing under test; a SLOTTED BLOCK is one polygon with a narrow slot cut into
# it, so the two sides of the slot are the SAME RING and no pairwise item check
# can ever compare them.

def dumbbell(neck):
    h = neck / 2.0
    return [(0, 0), (2, 0), (2, 2 - h), (1.05 + h - 0.05, 2 - h),
            (1.05 + h - 0.05, 3 + h), (2, 3 + h), (2, 5), (0, 5),
            (0, 3 + h), (0.95 - h + 0.05, 3 + h),
            (0.95 - h + 0.05, 2 - h), (0, 2 - h)]


def bridged_blocks(neck):
    """Two 2x2 blocks joined by a bridge exactly `neck` wide and 1 mm long."""
    a = 1.0 - neck / 2.0
    b = 1.0 + neck / 2.0
    return [(0, 0), (2, 0), (2, 2), (b, 2), (b, 3), (2, 3), (2, 5), (0, 5),
            (0, 3), (a, 3), (a, 2), (0, 2)]


def slotted_block(slot):
    """One polygon with a slot exactly `slot` wide cut 3 mm into it, flaring at
    the mouth so the closest approach is inside the slot and not at a corner."""
    lo = 2.0 - slot / 2.0
    hi = 2.0 + slot / 2.0
    return [(0, 0), (5, 0), (5, 1.5), (4, lo), (1, lo), (1, hi), (4, hi),
            (5, 2.5), (5, 4), (0, 4)]


# --------------------------------------------------------------------------
# 1. a board is read at all, into the same Item model a footprint is
# --------------------------------------------------------------------------

def test_sniff_root_tells_a_board_from_a_footprint(tmp_path):
    b = write_board(tmp_path, poly([(0, 0), (1, 0), (1, 1)]))
    f = tmp_path / "f.kicad_mod"
    f.write_text('(footprint "x" (version 20241229) (generator "t")'
                 ' (layer "F.Cu"))\n', encoding="utf-8")
    assert V.sniff_root(b) == "board"
    assert V.sniff_root(f) == "footprint"


def test_board_graphics_become_the_same_items_a_footprint_uses(tmp_path):
    """gr_poly IS fp_poly here. That is the whole design: every check the
    harness already had then applies to a board without being rewritten."""
    body = "\n".join([
        poly([(0, 0), (2, 0), (2, 2), (0, 2)], "F.Cu"),
        '\t(gr_line (start 0 5) (end 4 5) (stroke (width 0.2) (type default)) (layer "F.SilkS"))',
        '\t(gr_rect (start 6 0) (end 8 2) (stroke (width 0.15) (type default)) (fill no) (layer "F.SilkS"))',
        '\t(gr_circle (center 12 4) (end 13 4) (stroke (width 0.2) (type default)) (fill no) (layer "F.SilkS"))',
        '\t(gr_arc (start 16 0) (mid 17 1) (end 18 0) (stroke (width 0.2) (type default)) (layer "F.SilkS"))',
        '\t(segment (start 20 0) (end 24 0) (width 0.25) (layer "F.Cu") (net 1))',
        '\t(via (at 26 4) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))',
        '\t(gr_text "AB" (at 30 10) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.2)) (justify left)))',
    ])
    fp = V.load_board(write_board(tmp_path, body))
    kinds = sorted({it.kind for it in fp.items})
    assert kinds == ["fp_arc", "fp_circle", "fp_line", "fp_poly", "fp_rect",
                     "fp_text"], kinds
    assert fp.is_board
    assert not fp.unmeasured, fp.unmeasured
    # the via spans every copper layer between F and B, not just the two named
    via = [it for it in fp.items if it.src.startswith("via")][0]
    assert via.layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], via.layers
    assert math.isclose(via.char_h - via.hole_r, 0.15)


def test_every_item_says_where_it_came_from(tmp_path):
    fp = V.load_board(write_board(tmp_path, poly([(0, 0), (2, 0), (2, 2)])))
    labels = [V.item_label(i, it) for i, it in enumerate(fp.items)]
    assert any(l.startswith("gr_poly #") for l in labels), labels


# --------------------------------------------------------------------------
# 2. placed footprints, in board coordinates
# --------------------------------------------------------------------------

FP_ROT = """\t(footprint "lib:part"
\t\t(layer "F.Cu")
\t\t(at 10 20 90)
\t\t(property "Reference" "R7" (at 0 0 90) (layer "F.SilkS")
\t\t\t(effects (font (size 1 1) (thickness 0.15))))
\t\t(fp_poly (pts (xy 1 0) (xy 2 0) (xy 2 1) (xy 1 1))
\t\t\t(stroke (width 0) (type default)) (fill yes) (layer "F.Cu"))
\t\t(pad "1" smd rect (at 1 0 90) (size 2 0.5) (layers "F.Cu") (net 3))
\t)"""


def test_placed_footprint_geometry_is_rotated_into_board_coordinates(tmp_path):
    fp = V.load_board(write_board(tmp_path, FP_ROT))
    p = [it for it in fp.items if it.kind == "fp_poly"][0]
    assert p.src.startswith("FP R7 [lib:part] ")
    # (1,0) through a 90 degree footprint at (10,20) lands at (10,19)
    assert min(p.pts, key=lambda q: (round(q[0], 6), round(q[1], 6))) == \
        pytest.approx((10.0, 18.0))
    xs = [q[0] for q in p.pts]
    ys = [q[1] for q in p.pts]
    assert (round(min(xs), 6), round(max(xs), 6)) == (10.0, 11.0)
    assert (round(min(ys), 6), round(max(ys), 6)) == (18.0, 19.0)


def test_pad_angle_is_absolute_not_local(tmp_path):
    """KiCad writes a pad's angle as its orientation ON THE BOARD. Applying it
    in the footprint frame AND then rotating by the footprint turns every pad
    twice: on a 90-degree-placed USB-C receptacle that overlapped VBUS with
    GND and merged 44 separate pads into one blob."""
    fp = V.load_board(write_board(tmp_path, FP_ROT))
    pad = [it for it in fp.items if it.kind == "pad"][0]
    b = V.bbox_of(pad.pts)
    # 2.0 x 0.5 pad, absolute angle 90 -> 0.5 wide in x, 2.0 tall in y,
    # centred on the transformed pad origin (10, 19).
    assert (round(b[2] - b[0], 6), round(b[3] - b[1], 6)) == (0.5, 2.0)
    assert (round((b[0] + b[2]) / 2, 6), round((b[1] + b[3]) / 2, 6)) == (10.0, 19.0)


def test_pad_layer_wildcards_resolve_against_the_board(tmp_path):
    body = ('\t(footprint "lib:th" (layer "F.Cu") (at 5 5)\n'
            '\t\t(pad "1" thru_hole circle (at 0 0) (size 1.2) (drill 0.6)\n'
            '\t\t\t(layers "*.Cu" "*.Mask") (net 2))\n\t)')
    fp = V.load_board(write_board(tmp_path, body))
    pad = [it for it in fp.items if it.kind == "pad"][0]
    assert pad.layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu",
                          "F.Mask", "B.Mask"], pad.layers


# --------------------------------------------------------------------------
# 3. THE DEFECT: a sub-floor filled polygon FAILS, at the right number
# --------------------------------------------------------------------------

@needs_shapely
def test_subfloor_filled_polygon_fails_at_the_right_number(tmp_path):
    fp = V.load_board(write_board(tmp_path, poly(bridged_blocks(0.10))))
    c = V.check_ink(fp, cfg(silk=0.15))
    body = text_of(c)
    assert c.level == V.FAIL, body
    assert "0.100000" in body, body
    assert "F.SilkS" in body


@needs_shapely
def test_the_number_tracks_the_geometry_not_a_constant(tmp_path):
    """Three different necks, three different measurements. A check that
    reports the same number whatever it is given is not measuring."""
    got = []
    for neck in (0.06, 0.09, 0.12):
        fp = V.load_board(write_board(tmp_path, poly(bridged_blocks(neck)),
                                      name=f"n{int(neck*100)}"))
        r = IM.measure_layer("F.SilkS",
                             V._ink_parts(fp, cfg())[0]["F.SilkS"], 0.15)
        got.append(r.min_feature.value)
    assert got == pytest.approx([0.06, 0.09, 0.12], abs=1e-9)


@needs_shapely
def test_a_witness_coordinate_comes_back_with_the_number(tmp_path):
    fp = V.load_board(write_board(tmp_path, poly(bridged_blocks(0.10))))
    r = IM.measure_layer("F.SilkS", V._ink_parts(fp, cfg())[0]["F.SilkS"], 0.15)
    assert r.min_feature.value == pytest.approx(0.10, abs=1e-9)
    assert (r.min_feature.x, r.min_feature.y) == pytest.approx((1.0, 2.0),
                                                               abs=1e-6)


@needs_shapely
def test_a_whole_component_finer_than_the_floor_is_reported_as_vanishing(tmp_path):
    """A 0.10 x 5 mm bar has no point 0.15 mm from its own edge: an opening at
    the floor deletes it. That is a different failure from a neck and it is
    reported as one."""
    fp = V.load_board(write_board(tmp_path,
                                  poly([(0, 0), (0.1, 0), (0.1, 5), (0, 5)])))
    r = IM.measure_layer("F.SilkS", V._ink_parts(fp, cfg())[0]["F.SilkS"], 0.15)
    assert r.vanished == 1
    # bisection on a buffered erosion: good to a few nanometres, not exact
    assert r.vanished_examples[0].value == pytest.approx(0.10, abs=1e-4)
    c = V.check_ink(fp, cfg())
    assert c.level == V.FAIL
    assert "FINER THAN THE PROCESS" in text_of(c)


# --------------------------------------------------------------------------
# 4. THE OTHER HALF OF THE DEFECT: a gap inside ONE polygon
# --------------------------------------------------------------------------

@needs_shapely
def test_gap_inside_one_polygon_is_found_and_a_pairwise_check_cannot(tmp_path):
    """The alpha coupon's six sub-floor front-face gaps are all of this shape:
    both sides of the gap belong to the same ring, so there is no PAIR of
    items to compare and check_clearance is structurally blind to it."""
    fp = V.load_board(write_board(tmp_path, poly(slotted_block(0.12))))
    conf = cfg(silk=0.15)

    pairwise = V.check_clearance(fp, conf)
    assert "GAP BELOW FLOOR" not in text_of(pairwise), (
        "if the pairwise check has learned to see intra-ring gaps, this test "
        "is measuring the wrong thing")

    region = V.check_ink(fp, conf)
    body = text_of(region)
    assert region.level == V.FAIL, body
    assert "GAP BELOW FLOOR" in body, body
    assert "0.120000" in body, body


@needs_shapely
def test_a_slot_wider_than_the_floor_is_not_a_finding(tmp_path):
    fp = V.load_board(write_board(tmp_path, poly(slotted_block(0.30))))
    c = V.check_ink(fp, cfg(silk=0.15))
    assert c.level == V.PASS, text_of(c)


# --------------------------------------------------------------------------
# 5. a clean board passes
# --------------------------------------------------------------------------

CLEAN = "\n".join([
    poly([(0, 0), (5, 0), (5, 5), (0, 5)], "F.SilkS"),
    poly([(6, 0), (11, 0), (11, 5), (6, 5)], "F.SilkS"),
    poly([(0, 10), (5, 10), (5, 15), (0, 15)], "F.Cu"),
    '\t(segment (start 10 20) (end 30 20) (width 0.3) (layer "F.Cu") (net 1))',
    '\t(via (at 32 20) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 1))',
])


@needs_shapely
def test_a_clean_board_passes_every_measurement(tmp_path):
    fp = V.load_board(write_board(tmp_path, CLEAN))
    conf = cfg()
    ink = V.check_ink(fp, conf)
    assert ink.level == V.PASS, text_of(ink)
    assert V.check_geometry(fp, conf).level == V.PASS
    assert V.check_self_intersection(fp, conf).level == V.PASS
    mf = V.check_min_feature(fp, conf)
    assert mf.level == V.PASS, text_of(mf)
    cl = V.check_clearance(fp, conf)
    assert cl.level in (V.PASS, V.SKIP), text_of(cl)


@needs_shapely
def test_a_clean_board_still_states_what_it_did_not_measure(tmp_path):
    """A pass that does not say which layers had nothing within reach reads
    the same as a pass over a part with no margin at all."""
    fp = V.load_board(write_board(tmp_path, CLEAN))
    body = text_of(V.check_ink(fp, cfg()))
    assert "NOT MEASURED here" in body, body


# --------------------------------------------------------------------------
# 6. anything unmeasurable SKIPs, with a reason, and never passes
# --------------------------------------------------------------------------

def test_an_unknown_node_head_is_reported_by_name(tmp_path):
    """The blind spot was a CLASS of object nothing knew about. A head this
    harness has never seen must land in the report rather than be skipped in
    silence -- that is the only defence against the next construct KiCad adds."""
    body = poly([(0, 0), (2, 0), (2, 2)]) + '\n\t(quantum_widget (at 3 3))'
    fp = V.load_board(write_board(tmp_path, body))
    c = V.check_inventory(fp, cfg())
    assert c.level == V.SKIP
    txt = text_of(c)
    assert "quantum_widget" in txt, txt
    assert "NOT MEASURED" in txt


@pytest.mark.parametrize("node,word", [
    ('\t(dimension (type aligned) (layer "F.SilkS") (pts (xy 0 0) (xy 5 0))'
     ' (style (thickness 0.2)))', "dimension"),
    ('\t(table (column_count 2) (layer "F.SilkS"))', "table"),
    ('\t(target (at 3 3) (size 5) (width 0.15) (layer "F.SilkS"))', "target"),
    ('\t(image (at 3 3) (scale 1) (data "AAAA"))', "bitmap"),
])
def test_geometry_bearing_constructs_that_are_not_modelled_skip(tmp_path, node,
                                                                word):
    fp = V.load_board(write_board(tmp_path, poly([(0, 0), (2, 0), (2, 2)])
                                  + "\n" + node, name=word))
    c = V.check_inventory(fp, cfg())
    assert c.level == V.SKIP
    assert word in text_of(c).lower(), text_of(c)


@needs_shapely
def test_text_the_font_table_cannot_place_is_not_measured(tmp_path):
    body = ('\t(gr_text "Hi" (at 5 5) (layer "F.SilkS") (effects (font '
            '(size 1 1) (thickness 0.2) (bold yes)) (justify left)))')
    fp = V.load_board(write_board(tmp_path, body))
    c = V.check_ink(fp, cfg())
    txt = text_of(c)
    assert c.level == V.SKIP, txt
    assert "NOT MEASURED" in txt and "bold" in txt, txt


@needs_shapely
def test_a_zone_with_no_stored_fill_is_not_measured(tmp_path):
    body = ('\t(zone (net 1) (net_name "GND") (layers "F.Cu") (hatch edge 0.5)'
            ' (polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10))))')
    fp = V.load_board(write_board(tmp_path, body))
    c = V.check_inventory(fp, cfg())
    assert c.level == V.SKIP
    assert "NO STORED FILL" in text_of(c)


@needs_shapely
def test_a_stored_zone_fill_is_measured_and_labelled_as_a_cache(tmp_path):
    body = ('\t(zone (net 1) (net_name "GND") (layers "F.Cu") (hatch edge 0.5)'
            ' (polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10)))'
            ' (filled_polygon (layer "F.Cu")'
            ' (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10))))')
    fp = V.load_board(write_board(tmp_path, body))
    z = [it for it in fp.items if "zone" in it.src][0]
    assert z.filled and z.layers == ["F.Cu"]
    assert "stored zone fill" in z.stale


@needs_shapely
def test_the_ink_check_skips_loudly_when_it_cannot_run(tmp_path, monkeypatch):
    """No shapely, no measurement -- and no estimate either. An estimated
    floor comparison is not a floor."""
    fp = V.load_board(write_board(tmp_path, poly(bridged_blocks(0.05))))
    monkeypatch.setattr(IM, "HAVE_SHAPELY", False)
    c = V.check_ink(fp, cfg())
    assert c.level == V.SKIP
    assert "NOT MEASURED" in c.headline
    assert "not a pass" in text_of(c)


@needs_shapely
def test_an_item_the_region_cannot_represent_stops_the_layer_passing(tmp_path):
    body = (poly(bridged_blocks(1.0))
            + '\n\t(gr_poly (pts (xy 20 0) (xy 25 0) (xy 25 5) (xy 20 5)) '
              '(stroke (width 0) (type default)) (fill no) (layer "F.SilkS"))')
    fp = V.load_board(write_board(tmp_path, body))
    c = V.check_ink(fp, cfg())
    txt = text_of(c)
    assert c.level == V.SKIP, txt
    assert "board default line width" in txt, txt


# --------------------------------------------------------------------------
# 7. min-feature must not claim a concave area it cannot measure
# --------------------------------------------------------------------------

def test_concave_filled_area_is_never_reported_as_measured_on_a_board(tmp_path):
    """min_width() is a rotating caliper on the CONVEX HULL: for the dumbbell
    below it answers 2.0 mm, the hull's short side, while the bridge holding
    the two blocks together is 0.05 mm. Reporting the hull number as 'narrowest
    feature, above floor' is a green check written over the defect."""
    fp = V.load_board(write_board(tmp_path, poly(bridged_blocks(0.05))))
    conf = cfg()
    conf.ink_measured_layers = set()          # the ink check did not run
    c = V.check_min_feature(fp, conf)
    txt = text_of(c)
    assert c.level == V.SKIP, txt
    assert "NOT MEASURED" in txt and "concave" in txt, txt
    assert "0.0500" not in txt          # it did not measure it, and says so
    # and the hull really does answer 2.0 here, which is why it is refused
    p = [it for it in fp.items if it.kind == "fp_poly"][0]
    assert V.min_width(p.pts) == pytest.approx(2.0)
    assert not V._is_convex(p.pts)


@needs_shapely
def test_min_feature_defers_to_the_ink_check_when_it_has_run(tmp_path):
    fp = V.load_board(write_board(tmp_path, poly(bridged_blocks(0.05))))
    conf = cfg()
    V.check_ink(fp, conf)                     # populates ink_measured_layers
    c = V.check_min_feature(fp, conf)
    assert "Measured for real by the ink-floor check" in text_of(c)


def test_a_convex_filled_area_is_still_judged_by_min_feature(tmp_path):
    """The deferral is scoped to shapes the caliper gets wrong. A rectangle is
    not one of them, and deferring it would throw away a working check."""
    fp = V.load_board(write_board(tmp_path,
                                  poly([(0, 0), (0.1, 0), (0.1, 5), (0, 5)])))
    c = V.check_min_feature(fp, cfg())
    txt = text_of(c)
    assert c.level == V.FAIL, txt
    assert "BELOW FLOOR" in txt and "0.1000" in txt


# --------------------------------------------------------------------------
# 8. things that are NOT defects and must not be reported as any
# --------------------------------------------------------------------------

@needs_shapely
def test_same_net_copper_is_not_a_spacing_violation(tmp_path):
    """A track, the via it lands on and the pour it feeds are one conductor.
    Judging the space between two pieces of it produced 81 findings on the
    product board about copper that is deliberately continuous."""
    def two_tracks(net_a, net_b):
        return (f'\t(segment (start 0 0) (end 10 0) (width 0.25) '
                f'(layer "F.Cu") (net {net_a}))\n'
                f'\t(segment (start 0 0.3) (end 10 0.3) (width 0.25) '
                f'(layer "F.Cu") (net {net_b}))')
    # centres 0.3 apart, 0.25 wide each -> a 0.05 mm gap
    diff = V.load_board(write_board(tmp_path, two_tracks(1, 2), name="diff"))
    same = V.load_board(write_board(tmp_path, two_tracks(1, 1), name="same"))
    conf = cfg(copper=0.10)
    d = V.check_ink(diff, conf)
    assert d.level == V.FAIL, text_of(d)
    assert "0.050000" in text_of(d)
    s = V.check_ink(same, cfg(copper=0.10))
    assert s.level == V.PASS, text_of(s)
    assert "single net" in text_of(s)


def test_an_unplated_hole_has_no_annular_ring_to_be_too_thin(tmp_path):
    """np_thru_hole pads in KiCad's own libraries carry a drill at least as
    large as the pad. Subtracting one from the other leaves nothing, and
    measuring that nothing produced 45 'components of 0.0000 mm2' on the
    product board."""
    body = ('\t(footprint "lib:m" (layer "F.Cu") (at 5 5)\n'
            '\t\t(pad "" np_thru_hole circle (at 0 0) (size 0.66) '
            '(drill 0.66) (layers "*.Cu" "*.Mask"))\n\t)')
    fp = V.load_board(write_board(tmp_path, body))
    pad = [it for it in fp.items if it.kind == "pad"][0]
    assert pad.stale_hole
    parts, _ = V._ink_parts(fp, cfg())
    assert not parts.get("F.Cu"), "an unplated hole is not copper"
    assert parts.get("F.Mask"), "but it is still a mask opening"


def test_edge_cuts_is_a_routing_path_and_not_ink(tmp_path):
    """Holding a 0.05 mm outline stroke against a 1.0 mm router-bit diameter
    fails every board ever drawn. The feature there is the LOOP width."""
    fp = V.load_board(write_board(tmp_path, poly([(0, 0), (5, 0), (5, 5)])))
    parts, _ = V._ink_parts(fp, cfg())
    assert "Edge.Cuts" not in parts
    if IM.HAVE_SHAPELY:
        assert "not ink" in text_of(V.check_ink(fp, cfg()))


def test_a_courtyard_hanging_off_the_board_edge_is_not_an_escape(tmp_path):
    """An edge-mounted part's body is meant to overhang. What is a defect is
    FABRICATED geometry past the routed outline."""
    body = (poly([(38, 28), (48, 28), (48, 38), (38, 38)], "F.CrtYd", fill="no",
                 width=0.05))
    fp = V.load_board(write_board(tmp_path, body))
    c = V.check_geometry(fp, cfg())
    assert "ESCAPES EXTENT" not in text_of(c), text_of(c)
    fab = V.load_board(write_board(tmp_path,
                                   poly([(38, 28), (48, 28), (48, 38), (38, 38)],
                                        "F.Cu"), name="cu"))
    assert "ESCAPES EXTENT" in text_of(V.check_geometry(fab, cfg()))


def test_a_hexagon_is_not_two_unroutable_corners(tmp_path):
    """A regular hexagon written with 27.135462 and 54.270925 has 120.0000 deg
    corners that evaluate to 119.9999996. A bare `< 120` called two of them
    unroutable on a shape a router cuts without noticing."""
    r, h = 54.270925, 47.0
    hexa = [(-r, 0), (-r / 2 - 0.000001, -h), (r / 2, -h), (r, 0),
            (r / 2, h), (-r / 2, h)]
    assert V._sharp_corners(hexa) == 0


# --------------------------------------------------------------------------
# 9. the check that verifies the other verifier's trigger conditions
# --------------------------------------------------------------------------

DISARMED = {"board": {"design_settings": {"rules": {
    "min_clearance": 0.0, "min_track_width": 0.2,
    "min_silk_clearance": 0.0, "min_text_thickness": 0.08}}},
    "net_settings": {"classes": [{"name": "Default", "clearance": 0.2,
                                  "track_width": 0.2}]}}

ARMED = {"board": {"design_settings": {"rules": {
    "min_clearance": 0.1, "min_track_width": 0.15,
    "min_silk_clearance": 0.15, "min_text_thickness": 0.15}}},
    "net_settings": {"classes": [{"name": "Default", "clearance": 0.1,
                                  "track_width": 0.1}]}}


def test_a_rule_set_to_zero_is_a_disarmed_check_not_a_default(tmp_path):
    p = write_board(tmp_path, poly([(0, 0), (2, 0), (2, 2)]), pro=DISARMED)
    c = V.check_project_rules(V.load_board(p), cfg())
    txt = text_of(c)
    assert c.level == V.FAIL, txt
    assert "DRC DISARMED" in txt and "min_clearance" in txt
    assert "min_silk_clearance" in txt
    assert "DRC UNDER THE FLOOR" in txt and "min_text_thickness" in txt


def test_armed_rules_pass_and_the_scope_is_stated(tmp_path):
    p = write_board(tmp_path, poly([(0, 0), (2, 0), (2, 2)]), name="ok",
                    pro=ARMED)
    c = V.check_project_rules(V.load_board(p), cfg())
    assert c.level == V.PASS, text_of(c)
    # and it must not pretend arming DRC would have caught the coupon defect
    assert "does not gate polygonised silk" in text_of(c)


def test_no_project_file_is_a_skip_not_a_pass(tmp_path):
    p = write_board(tmp_path, poly([(0, 0), (2, 0), (2, 2)]), name="lone")
    c = V.check_project_rules(V.load_board(p), cfg())
    assert c.level == V.SKIP
    assert "NOT MEASURED" in c.headline


# --------------------------------------------------------------------------
# 10. end to end
# --------------------------------------------------------------------------

@needs_shapely
def test_verify_board_fails_a_board_with_subfloor_silk(tmp_path):
    p = write_board(tmp_path, poly(bridged_blocks(0.08)), pro=ARMED)
    verdict, checks = V.verify_board(p, cfg())
    assert verdict == V.FAIL
    keys = {c.key for c in checks}
    assert {"inventory", "ink-floor", "min-feature", "clearance",
            "project-rules"} <= keys, keys
    ink = [c for c in checks if c.key == "ink-floor"][0]
    assert "0.080000" in text_of(ink)


@needs_shapely
def test_verify_file_dispatches_a_board_to_the_board_run(tmp_path):
    p = write_board(tmp_path, poly(bridged_blocks(0.08)), pro=ARMED)
    verdict, checks = V.verify_file(p, cfg())
    assert verdict == V.FAIL
    assert any(c.key == "inventory" for c in checks)


@needs_shapely
def test_a_clean_board_end_to_end_has_no_failing_check(tmp_path):
    p = write_board(tmp_path, CLEAN, name="clean", pro=ARMED)
    _, checks = V.verify_board(p, cfg())
    bad = [(c.key, c.headline) for c in checks if c.level == V.FAIL]
    assert not bad, bad
