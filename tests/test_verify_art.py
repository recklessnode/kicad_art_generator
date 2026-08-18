"""The acceptance harness's own acceptance tests.

These pin the three things that let an unbuildable part pass verify_art.py 7/7:

  1. fp_text geometry was REPORTED, not measured. check_min_feature called
     note(layer, it.thickness, ...) -- it handed back the attribute the emitter
     had written into the file it was checking, so a text item could not
     possibly disagree with its own emitter.
  2. fp_text could not participate in the gap check at all. check_clearance
     collected fp_line, fp_poly and fp_rect, so copper-to-copper SPACING
     between letterforms was structurally unreachable -- and
     FabProfile.min_copper_mm is minimum trace width AND SPACING.
  3. A check that formed ZERO pairs printed PASS. 'clearance F.Mask gaps >=
     0.200 mm' over a single polygon is a sentence about nothing.

The part that prompted this -- 1712 characters at a 0.6030 mm cap against
JLCPCB's 0.0889 mm floor -- had a narrowest copper gap of 0.0260 mm, 29% of the
floor, in 156 pairs. Every check passed.
"""
import math
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import stroke_font as SF                                       # noqa: E402
import verify_art as V                                         # noqa: E402


# --------------------------------------------------------------------------
# rigging
# --------------------------------------------------------------------------

def cfg(copper=0.1, mask=0.1, silk=0.15, hard=(), render_svg=None):
    pal = V.Palette(recipe_layers=set(),
                    floors={"silk": silk, "mask": mask, "copper": copper,
                            "buried": 0.5, "edge": 1.0},
                    buried_provisional=False, source="test", notes=[],
                    hard=set(hard))
    c = type("C", (), {})()
    c.palette = pal
    c.clearance = True
    c.max_clearance_items = 50000
    c.clearance_budget = 40_000_000
    c.max_report = 20
    c.render_svg = render_svg
    c.outlier_mm = 1.0
    return c


def write_fp(tmp_path, body, name="t"):
    p = tmp_path / f"{name}.kicad_mod"
    p.write_text(f'(footprint "{name}"\n\t(version 20241229)\n'
                 f'\t(generator "test")\n\t(layer "F.Cu")\n'
                 f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
                 + body + "\n)\n", encoding="utf-8")
    return p


def text_node(s, at=(0.0, 0.0), cap=1.0, thick=0.1, layer="F.Cu",
              justify="left", extra=""):
    j = f"(justify {justify})" if justify else ""
    return (f'\t(fp_text user "{s}" (at {at[0]} {at[1]}) (layer "{layer}")\n'
            f'\t\t(effects (font (size {cap} {cap}) (thickness {thick}) {extra})'
            f' {j}))')


def detail_text(check):
    return "\n".join([check.headline] + list(check.details))


# --------------------------------------------------------------------------
# 1. fp_text is MEASURED, not echoed
# --------------------------------------------------------------------------

def test_text_is_expanded_into_real_geometry(tmp_path):
    """The width comes off expanded letterforms, and the report says so."""
    fp = V.load_footprint(write_fp(tmp_path, text_node("Hello", thick=0.12)))
    c = V.check_min_feature(fp, cfg(copper=0.1))
    body = detail_text(c)
    assert "EXPANDED" in body, body
    assert "expanded letterforms" in body, body
    # The old code path said "glyph stroke" and quoted it.thickness.
    assert "glyph stroke" not in body, body
    ink = V.expand_text(fp.items[0])
    assert ink.ok and ink.n_seg > 0
    assert f"{ink.n_seg} segments" in body


def test_expansion_places_a_known_letterform(tmp_path):
    """An 'H' at a 1 mm cap really is a 1 mm stem, where KiCad puts it.

    Checked against the font's own cap-height statement rather than against the
    table this is testing: GLYPHS says the capital ink box spans exactly 1 em.
    """
    fp = V.load_footprint(write_fp(tmp_path, text_node("H", cap=1.0, thick=0.01)))
    ink = V.expand_text(fp.items[0])
    ys = [y for ch in ink.chains for (_, y) in ch]
    assert math.isclose(max(ys) - min(ys), SF.CAP_HEIGHT_EM * 1.0, abs_tol=1e-6)
    assert len(ink.chains) == 3          # two stems and a crossbar


def test_unexpandable_text_is_not_measured_and_never_passes(tmp_path):
    """Italic letterforms are not the ones in the table, so say so.

    This is the shape of the original bug in miniature: the honest answer is
    "unknown", and the tempting answer is the thickness attribute, which would
    read as a clean measurement of geometry nobody looked at.
    """
    fp = V.load_footprint(write_fp(
        tmp_path, text_node("Hello", thick=0.02, extra="(italic yes)")))
    c = V.check_min_feature(fp, cfg(copper=0.1))
    body = detail_text(c) + "\n".join(c.details)
    assert "NOT MEASURED" in body, body
    assert c.level != V.PASS
    # and it must not have quietly reported 0.02 mm as if it had measured it
    assert "0.0200 mm  [" not in body, body


def test_whitespace_only_text_says_so_without_inventing_a_finding(tmp_path):
    """Measured, and the answer is 'none'. Distinct from NOT MEASURED, and not
    a fabrication risk -- a string of spaces cannot be too fine."""
    fp = V.load_footprint(write_fp(tmp_path, text_node("   ", thick=0.02)))
    c = V.check_min_feature(fp, cfg(copper=0.1))
    assert "draws no ink at all" in detail_text(c)
    assert "NOT MEASURED" not in detail_text(c)


def test_hidden_text_is_not_on_the_board(tmp_path):
    """KiCad does not plot hidden text, so it cannot be too fine or too close.
    Both spellings of hide, and the property NAME is not the drawn string."""
    body = ('\t(property "Reference" "REF**" (at 0 0) (layer "F.SilkS")\n'
            '\t\t(effects (font (size 1 1) (thickness 0.01))) (hide yes))\n'
            + text_node("x", thick=0.001, layer="F.SilkS") .replace(
                '(at 0.0 0.0)', '(at 0 4) hide'))
    fp = V.load_footprint(write_fp(tmp_path, body))
    assert all(it.hidden for it in fp.items), [it.hidden for it in fp.items]
    assert fp.items[0].text == "REF**"     # not "Reference"
    mf = V.check_min_feature(fp, cfg(silk=0.15))
    assert "NOT MEASURED" not in detail_text(mf)
    assert "BELOW FLOOR" not in detail_text(mf)
    cl = V.check_clearance(fp, cfg(silk=0.15))
    assert "NOT COMPARED" not in detail_text(cl)


def test_draw_angle_matches_kicads_upside_down_rule():
    """Measured against kicad-cli: the flip is between 90 and 91, and again
    between 270 and 271."""
    assert V._draw_angle(0) == 0
    assert V._draw_angle(90) == 90
    assert V._draw_angle(91) == 271
    assert V._draw_angle(180) == 360
    assert V._draw_angle(270) == 450
    assert V._draw_angle(271) == 271
    assert V._draw_angle(-90) == 90        # normalises to 270, so it flips
    assert V._draw_angle(-30) == -30


# --------------------------------------------------------------------------
# 2. fp_text participates in the clearance check
# --------------------------------------------------------------------------

INTER_GLYPH_EM = 4.0 / 21.0     # newstroke is on a 21-unit em grid


def test_text_gap_is_measured_between_glyphs(tmp_path):
    """'rt' -- the arm of the r and the crossbar of the t.

    Both are horizontal strokes on the same line, 4/21 em apart centre to
    centre, which makes this the tightest inter-glyph gap in ordinary prose and
    the one that sank the whitepaper part. Expected value derived from the em
    grid, not from the geometry under test.
    """
    cap, thick = 1.0, 0.1
    want = INTER_GLYPH_EM * cap - thick
    fp = V.load_footprint(write_fp(tmp_path, text_node("rt", cap=cap,
                                                       thick=thick)))
    c = V.check_clearance(fp, cfg(copper=want + 0.01))
    hit = [d for d in c.details if "GAP BELOW FLOOR" in d]
    assert hit, detail_text(c)
    got = float(hit[0].split("narrowest gap ")[1].split(" mm")[0])
    assert math.isclose(got, want, abs_tol=1e-4), (got, want)
    assert c.level in (V.WARN, V.FAIL)


def test_text_gap_passes_when_the_floor_allows_it(tmp_path):
    cap, thick = 1.0, 0.1
    want = INTER_GLYPH_EM * cap - thick
    fp = V.load_footprint(write_fp(tmp_path, text_node("rt", cap=cap,
                                                       thick=thick)))
    c = V.check_clearance(fp, cfg(copper=want - 0.01))
    assert c.level == V.PASS, detail_text(c)
    assert "pair(s) compared" in detail_text(c)


def test_a_passing_layer_still_names_its_narrowest_gap(tmp_path):
    """A verdict is not a margin.

    'all gaps >= 0.0889 mm' is equally true of a part with 40% of headroom and
    of a part sitting on the floor with nothing, and the whitepaper part was
    the second kind. The judging pass cannot supply the number -- it only looks
    out as far as the floor, so on a passing layer it finds nothing -- hence the
    separate margin pass. Here the floor is set well under the real gap, so the
    judging pass sees nothing and the reported number can only have come from
    the margin pass.
    """
    cap, thick = 1.0, 0.1
    want = INTER_GLYPH_EM * cap - thick
    floor = want - 0.02
    fp = V.load_footprint(write_fp(tmp_path, text_node("rt", cap=cap,
                                                       thick=thick)))
    c = V.check_clearance(fp, cfg(copper=floor))
    body = detail_text(c)
    assert c.level == V.PASS, body
    assert "narrowest gap" in body, body
    got = float(body.split("narrowest gap ")[1].split(" mm")[0])
    assert math.isclose(got, want, abs_tol=1e-4), (got, want)
    assert "+%.6f mm" % (got - floor) in body, body
    assert "ON THE FLOOR" not in body, body


def test_a_gap_sitting_on_the_floor_is_called_out_as_such(tmp_path):
    """Passing by less than the model can resolve is not a clean pass."""
    cap, thick = 1.0, 0.1
    want = INTER_GLYPH_EM * cap - thick
    fp = V.load_footprint(write_fp(tmp_path, text_node("rt", cap=cap,
                                                       thick=thick)))
    c = V.check_clearance(fp, cfg(copper=want - V.TEXT_MODEL_EPS_MM / 2.0))
    body = detail_text(c)
    assert c.level == V.PASS, body
    assert "ON THE FLOOR" in body, body


def test_the_margin_pass_cannot_change_a_verdict(tmp_path):
    """Same geometry, margin pass budgeted out of existence -> same level.

    The margin pass exists only to put a number on the report. If it could ever
    move a verdict it would be a second, unreviewed judging pass with a wider
    radius, so this pins that it cannot.
    """
    cap, thick = 1.0, 0.1
    want = INTER_GLYPH_EM * cap - thick
    fp = V.load_footprint(write_fp(tmp_path, text_node("rt", cap=cap,
                                                       thick=thick)))
    saved = V.GAP_MARGIN_BUDGET
    try:
        for floor in (want - 0.02, want + 0.01):
            V.GAP_MARGIN_BUDGET = saved
            on = V.check_clearance(fp, cfg(copper=floor))
            V.GAP_MARGIN_BUDGET = 0
            off = V.check_clearance(fp, cfg(copper=floor))
            assert on.level == off.level, (floor, on.level, off.level)
        # ...and with the budget gone the report says NOT MEASURED rather than
        # quoting the floor back as if it were the gap
        V.GAP_MARGIN_BUDGET = 0
        body = detail_text(V.check_clearance(fp, cfg(copper=want - 0.02)))
        assert "NOT MEASURED" in body, body
    finally:
        V.GAP_MARGIN_BUDGET = saved


TITTLE_EM = 5.0 / 21.0


def test_gap_inside_one_glyph_is_measured(tmp_path):
    """The stem of an 'i' and its own tittle are separate copper.

    Splitting a string per character would miss this, and the part that
    prompted the fix had 109 sub-floor pairs of exactly this kind. Features are
    per stroke PATH for that reason.
    """
    cap, thick = 1.0, 0.1
    want = TITTLE_EM * cap - thick
    fp = V.load_footprint(write_fp(tmp_path, text_node("i", cap=cap,
                                                       thick=thick)))
    c = V.check_clearance(fp, cfg(copper=want + 0.01))
    hit = [d for d in c.details if "GAP BELOW FLOOR" in d]
    assert hit, detail_text(c)
    got = float(hit[0].split("narrowest gap ")[1].split(" mm")[0])
    assert math.isclose(got, want, abs_tol=1e-4), (got, want)


def test_touching_strokes_are_one_feature(tmp_path):
    """An 'H' is three stroke paths and three pairs of them.

    Two of those pairs are a stem meeting the crossbar -- continuous ink, gap
    zero, one feature. Only the stem-to-stem pair is a real gap, and it is the
    0.5714 em advance minus the pen. Reporting the crossbar joints as 0 mm
    gaps would bury every real finding under one per letter.
    """
    fp = V.load_footprint(write_fp(tmp_path, text_node("H", cap=1.0, thick=0.1)))
    c = V.check_clearance(fp, cfg(copper=0.4))
    body = detail_text(c)
    assert c.level == V.PASS, body
    assert "3 pair(s) compared" in body and "2 touching" in body, body


def test_counter_of_an_e_is_checked(tmp_path):
    """An enclosed void is bounded by ONE stroke, so no pair of features spans
    it and the pairwise test cannot see it. clear = 2*D*cap - stroke."""
    cap, thick = 1.0, 0.1
    want = 2 * SF.GLYPHS["e"][2] * cap - thick
    fp = V.load_footprint(write_fp(tmp_path, text_node("e", cap=cap,
                                                       thick=thick)))
    c = V.check_clearance(fp, cfg(copper=want + 0.01))
    hit = [d for d in c.details if "COUNTER TOO TIGHT" in d]
    assert hit, detail_text(c)
    assert f"{want:.6f}" in hit[0]
    ok = V.check_clearance(fp, cfg(copper=want - 0.01))
    assert ok.level == V.PASS, detail_text(ok)


def test_unexpandable_text_is_not_silently_dropped_from_clearance(tmp_path):
    fp = V.load_footprint(write_fp(
        tmp_path, text_node("Hello", thick=0.02, extra="(bold yes)")))
    c = V.check_clearance(fp, cfg(copper=0.1))
    assert "NOT COMPARED" in detail_text(c) + "".join(c.details)
    assert c.level != V.PASS


# --------------------------------------------------------------------------
# 3. a check that formed zero pairs must not print PASS
# --------------------------------------------------------------------------

MASK_POLY = ('\t(fp_poly (pts (xy -5 -5) (xy 5 -5) (xy 5 5) (xy -5 5)) '
             '(stroke (width 0) (type solid)) (fill solid) (layer "F.Mask"))')


def test_single_polygon_layer_reports_untested_not_pass(tmp_path):
    fp = V.load_footprint(write_fp(tmp_path, MASK_POLY))
    c = V.check_clearance(fp, cfg(mask=0.2))
    body = detail_text(c)
    assert "NOT TESTED" in body, body
    assert "0 pairs" in body, body
    assert "all gaps >= " not in body, body
    # nothing on any layer could be compared, so the CHECK tested nothing
    assert c.level == V.SKIP, body
    assert "NOTHING TESTED" in c.headline


def test_a_layer_with_pairs_still_passes_alongside_an_untested_one(tmp_path):
    body = MASK_POLY + "\n" + text_node("rt", cap=1.0, thick=0.1)
    fp = V.load_footprint(write_fp(tmp_path, body))
    c = V.check_clearance(fp, cfg(copper=0.05, mask=0.2))
    assert c.level == V.PASS, detail_text(c)
    assert "had nothing to compare" in c.headline, c.headline
    assert "NOT TESTED" in detail_text(c)


def test_min_feature_with_nothing_to_judge_is_not_a_pass(tmp_path):
    """A part whose only geometry is a mask opening exercises no floor."""
    fp = V.load_footprint(write_fp(tmp_path, MASK_POLY))
    c = V.check_min_feature(fp, cfg(mask=0.2))
    assert c.level == V.SKIP, detail_text(c)
    assert "NO FLOOR WAS EXERCISED" in c.headline


# --------------------------------------------------------------------------
# 4. a mask OPENING is not a mask DAM
# --------------------------------------------------------------------------

def test_mask_opening_is_not_judged_against_the_dam_limit(tmp_path):
    """The old report read 'F.Mask narrowest 33.797 mm ... floor 0.200 mm',
    which compares an aperture against the web between two apertures."""
    fp = V.load_footprint(write_fp(tmp_path, MASK_POLY))
    c = V.check_min_feature(fp, cfg(mask=0.2))
    body = detail_text(c)
    assert "narrowest OPENING" in body, body
    assert "NOT JUDGED" in body, body
    assert "BELOW FLOOR" not in body, body


def test_a_narrow_mask_opening_is_flagged_as_unknown_not_as_below_floor(tmp_path):
    """Separating the two quantities must not lose the alarm on a 50 um
    aperture -- it must stop mislabelling it as a floor violation."""
    thin = ('\t(fp_poly (pts (xy 0 0) (xy 10 0) (xy 10 0.05) (xy 0 0.05)) '
            '(stroke (width 0) (type solid)) (fill solid) (layer "F.Mask"))')
    fp = V.load_footprint(write_fp(tmp_path, thin))
    c = V.check_min_feature(fp, cfg(mask=0.2))
    body = detail_text(c) + " ".join(c.details)
    assert "narrowest OPENING 0.0500 mm" in body
    assert "BELOW FLOOR" not in body
    assert "OUTSIDE THE PUBLISHED ENVELOPE" in body
    assert c.level == V.SKIP        # unverified, not approved and not condemned


def test_mask_dam_is_still_enforced_between_two_openings(tmp_path):
    two = ('\t(fp_poly (pts (xy 0 0) (xy 1 0) (xy 1 1) (xy 0 1)) '
           '(stroke (width 0) (type solid)) (fill solid) (layer "F.Mask"))\n'
           '\t(fp_poly (pts (xy 1.05 0) (xy 2 0) (xy 2 1) (xy 1.05 1)) '
           '(stroke (width 0) (type solid)) (fill solid) (layer "F.Mask"))')
    fp = V.load_footprint(write_fp(tmp_path, two))
    c = V.check_clearance(fp, cfg(mask=0.2))
    hit = [d for d in c.details if "GAP BELOW FLOOR" in d]
    assert hit, detail_text(c)
    assert "0.050000 mm" in hit[0], hit[0]
    assert "wash away" in hit[0]


# --------------------------------------------------------------------------
# severity: a vendor's published limit is not a suggestion
# --------------------------------------------------------------------------

def test_fab_sourced_floor_fails_and_doc_sourced_floor_warns(tmp_path):
    cap, thick = 1.0, 0.1
    tight = INTER_GLYPH_EM * cap - thick + 0.01
    fp = V.load_footprint(write_fp(tmp_path, text_node("rt", cap=cap,
                                                       thick=thick)))
    assert V.check_clearance(fp, cfg(copper=tight)).level == V.WARN
    assert V.check_clearance(fp, cfg(copper=tight,
                                     hard=("copper",))).level == V.FAIL


# --------------------------------------------------------------------------
# the spatial index must not lose pairs to go faster
# --------------------------------------------------------------------------

def test_a_gap_that_misses_by_less_than_the_model_knows_is_not_a_finding(tmp_path):
    """A coupon whose silk gap is 0.150000 mm BY CONSTRUCTION came back as
    0.149999 mm -- a violation of 1.2 nanometres, invented by the 1e-6 em
    rounding in GLYPH_PATHS. Real findings must not have to compete with that.
    """
    cap, thick = 1.0, 0.1
    exact = INTER_GLYPH_EM * cap - thick
    fp = V.load_footprint(write_fp(tmp_path, text_node("rt", cap=cap,
                                                       thick=thick)))
    # a floor a nanometre above the true gap: inside the model's own precision
    assert V.check_clearance(fp, cfg(copper=exact + 1e-9)).level == V.PASS
    # a floor comfortably above it: a real finding
    assert V.check_clearance(fp, cfg(copper=exact + 0.01)).level == V.WARN
    assert V.TEXT_MODEL_EPS_MM == 1e-4


def test_candidate_pairs_finds_everything_brute_force_finds():
    import random
    rng = random.Random(20260817)
    feats = []
    for _ in range(400):
        x, y = rng.uniform(-20, 20), rng.uniform(-20, 20)
        w, h = rng.choice([0.05, 0.4, 3.0]), rng.choice([0.05, 0.4, 3.0])
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        feats.append(V.Feat("f", V.edges_bb_of(pts, True), 0.0,
                            (x, y, x + w, y + h)))
    reach = 0.2

    def close(a, b):
        dx = max(0.0, a.bb[0] - b.bb[2], b.bb[0] - a.bb[2])
        dy = max(0.0, a.bb[1] - b.bb[3], b.bb[1] - a.bb[3])
        return dx * dx + dy * dy < reach * reach

    brute = {(i, j) for i in range(len(feats)) for j in range(i + 1, len(feats))
             if close(feats[i], feats[j])}
    emitted = list(V._candidate_pairs(feats, reach))
    got = {p for p in emitted if close(feats[p[0]], feats[p[1]])}
    assert len(emitted) == len(set(emitted)), "pairs must be emitted once"
    assert brute == got, sorted(brute ^ got)[:8]


# --------------------------------------------------------------------------
# end to end, against the part this was all about
# --------------------------------------------------------------------------

PART = ROOT / "library" / "RecklessArt.pretty" / "art_btc_whitepaper_b.kicad_mod"

# The defect specimen, kept as a fixture rather than as the live library part.
#
# This test used to load the library part directly, on the reasoning that the
# broken part was sitting right there. That made the alarm self-disarming: the
# moment the part was re-emitted correctly the test could only be "fixed" by
# weakening it, and the one piece of real geometry proving the verifier can see
# a 0.026 mm copper gap would have been deleted along with the defect. So the
# 0.6030 mm / 1:6.783 / untracked emission is frozen here as a specimen. It is
# not a part anyone should fabricate, and it is not in the library for exactly
# that reason.
UNBUILDABLE = ROOT / "tests" / "fixtures" / \
    "art_btc_whitepaper_b_0603_unbuildable.kicad_mod"


@pytest.mark.skipif(not UNBUILDABLE.is_file(), reason="specimen not present")
def test_the_known_unbuildable_part_fails_on_copper_spacing():
    fp = V.load_footprint(UNBUILDABLE)
    c = V.check_clearance(fp, cfg(copper=0.0889, mask=0.2, hard=("copper",)))
    hit = [d for d in c.details if "GAP BELOW FLOOR" in d and "F.Cu" in d]
    assert hit, detail_text(c)
    got = float(hit[0].split("narrowest gap ")[1].split(" mm")[0])
    assert math.isclose(got, 0.025958, abs_tol=2e-6), got
    assert " in 156 of " in hit[0], hit[0]
    assert c.level == V.FAIL


@pytest.mark.skipif(not PART.is_file(), reason="whitepaper part not present")
def test_the_reemitted_whitepaper_clears_the_floor_it_is_tagged_for():
    """The fix, pinned by measurement rather than by a verdict.

    A bare `level == PASS` would have passed on the old part too, for every
    check except the two that could not see letterforms. So this asserts the
    MARGIN: the narrowest copper-to-copper spacing in the part, found by
    widening the search radius past the floor so that legal gaps are measured
    as well as illegal ones.

    Expected values come from the em grid and the emission parameters, not from
    the part: at cap 0.8 mm, 1:8 and 1/21 em of tracking the inter-glyph gap is
    (4/21 + 1/21)*cap - stroke and the 'i' stem-to-tittle is (5/21)*cap - stroke,
    both 0.090476 mm, and the anchors are written to 4 decimal places so an
    inter-glyph pair can lose up to 1e-4 mm of that to rounding.
    """
    fp = V.load_footprint(PART)
    c = V.check_clearance(fp, cfg(copper=0.0889, mask=0.2, hard=("copper",)))
    assert c.level == V.PASS, detail_text(c)

    want = (5.0 / 21.0) * 0.8 - 0.1
    by_layer, _, _ = V.clearance_features(fp, cfg(copper=0.0889))
    feats = by_layer["F.Cu"]
    reach = 0.13
    tight = None
    for a, b in V._candidate_pairs(feats, reach):
        fa, fb = feats[a], feats[b]
        g = V._feature_gap(fa.edges, fb.edges, fa.width, fb.width,
                           reach + (fa.width + fb.width) / 2.0)
        if g is None or g <= 1e-9:
            continue
        if tight is None or g < tight:
            tight = g
    assert tight is not None, "no separated pair found at all"
    assert tight >= 0.0889, tight
    assert math.isclose(tight, want, abs_tol=1.0e-4), (tight, want)
    # and it is not sitting ON the floor -- that framing is what hid the defect
    assert tight - 0.0889 > 10 * V.TEXT_MODEL_EPS_MM, tight


# --------------------------------------------------------------------------
# the model against the renderer
# --------------------------------------------------------------------------

def _kicad_cli():
    c = V.find_kicad_cli(None)
    return c.path if c.path and c.major >= V.MIN_KICAD_MAJOR else None


@pytest.mark.skipif(_kicad_cli() is None, reason="needs kicad-cli 10+")
@pytest.mark.parametrize("just,ang", [("left", 0.0), ("right", 37.5),
                                      ("", 90.0), ("left mirror", 0.0),
                                      ("left top", 180.0)])
def test_expansion_matches_what_kicad_plots(tmp_path, just, ang):
    """The whole measurement rests on the letterforms being KiCad's. Render the
    footprint and compare, rather than believing the table."""
    cli = _kicad_cli()
    s = "Hxy8e j!%@Wg"
    at = (1.5, -2.25)
    body = text_node(s, at=at, cap=0.603, thick=0.0889,
                     justify=just).replace(
        f"(at {at[0]} {at[1]})", f"(at {at[0]} {at[1]} {ang})" if ang else
        f"(at {at[0]} {at[1]})")
    lib = tmp_path / "in.pretty"
    lib.mkdir()
    src = write_fp(tmp_path, body, name="x")
    shutil.copy2(src, lib / src.name)
    out = tmp_path / "svg"
    out.mkdir()
    r = subprocess.run([cli, "fp", "export", "svg", "-o",
                        V.host_path(out, cli), V.host_path(lib, cli)],
                       capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    svg = next(out.glob("*.svg")).read_text(encoding="utf-8", errors="replace")
    fp = V.load_footprint(src)
    note = V.cross_check_expansion(fp, svg)
    assert note.startswith("expansion cross-checked"), note
    dev = float(note.split("worst deviation ")[1].split(" mm")[0])
    assert dev < 1e-3, note


@pytest.mark.skipif(_kicad_cli() is None, reason="needs kicad-cli 10+")
def test_every_baked_glyph_still_matches_this_kicad():
    """The whole printable-ASCII table, re-measured against the live renderer.

    This is what keeps GLYPH_PATHS from rotting: a KiCad that changed the
    letterforms, or a table edited by hand, shows up here as a segment-count or
    a coordinate difference rather than as a quietly wrong spacing number on a
    board that has already been ordered.
    """
    import tempfile
    cli = _kicad_cli()
    chars = [c for c in map(chr, range(0x20, 0x7F))]
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        lib = tmp / "in.pretty"
        lib.mkdir()
        for i, ch in enumerate(chars):
            esc = ch.replace("\\", "\\\\").replace('"', '\\"')
            (lib / f"g{i:03d}.kicad_mod").write_text(
                f'(footprint "g{i:03d}" (version 20241229) (generator "test") '
                f'(layer "F.Cu")\n'
                f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
                f'\t(fp_text user "{esc}" (at 0 0) (layer "F.Cu")\n'
                f'\t\t(effects (font (size 10 10) (thickness 0.05)) '
                f'(justify left)))\n)\n', encoding="utf-8")
        out = tmp / "svg"
        out.mkdir()
        r = subprocess.run([cli, "fp", "export", "svg", "-o",
                            V.host_path(out, cli), "--layers", "F.Cu",
                            V.host_path(lib, cli)],
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        assert r.returncode == 0, r.stderr
        bad = []
        for i, ch in enumerate(chars):
            svg = (out / f"g{i:03d}.svg").read_text(encoding="utf-8",
                                                    errors="replace")
            got = len(V.svg_text_segments(svg))
            want = sum(len(c) - 1 for c in SF.GLYPH_PATHS[ch])
            if got != want:
                bad.append(f"{ch!r}: kicad plots {got} segments, "
                           f"GLYPH_PATHS has {want}")
        assert not bad, bad
    total = sum(len(c) - 1 for v in SF.GLYPH_PATHS.values() for c in v)
    assert total == 788, total      # the table as measured on 2026-08-17
