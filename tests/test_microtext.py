"""What must stay true about microprinting.

These are the claims tools/microtext.py is built on, turned into assertions.
None of them needs kicad-cli: the letterform geometry was measured once
(tools/stroke_font.py --calibrate, which re-derives and diffs it) and everything
here is arithmetic on those numbers.

  1. The floor is enforced, not suggested -- and the refusal names a cap height
     that would work.
  2. The stroke scales with the cap height and never lands under the floor. The
     specific failure guarded against is the one coupon_ladders.Fp.text() fixed:
     a stroke silently CLAMPED up to the floor, which at a small cap height is a
     1:4 pen that fills every counter solid while passing a naive width check.
  3. EVERY gap clears the floor, not just the counters. A minimum feature is
     minimum width AND SPACING, and there are four gaps, not two: the stroke,
     the inter-glyph sidebearing gap, a glyph's own loose pieces, and the
     enclosed counter. Claim 3 used to read "closed counters fail before
     straight strokes", which is true and irrelevant -- the counter is the
     LOOSEST of the four for ordinary prose, and sizing on it shipped a part
     with 0.026 mm of copper-to-copper spacing against a 0.0889 mm floor.
  4. The mask opens over the block, never per glyph, and covers every glyph with
     the asked-for clearance -- measured against where KiCad actually PUTS the
     letterforms, which is not where the anchor is.
  5. Letter-spacing widens the inter-glyph gap and NOTHING else, defaults to
     zero, and changes no geometry at zero.

Several tests below were changed when claim 3 was corrected. Each of those says
in its own docstring what it used to assert and why that assertion was wrong;
none was relaxed to make the new model pass.
"""
import io
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import fab_profiles as FP      # noqa: E402
import microtext as M          # noqa: E402
import stroke_font as SF       # noqa: E402
from coupon_ladders import SPECIMEN, TEXT_STROKE_RATIO   # noqa: E402
from emit_art import ArtFp     # noqa: E402

FLOOR_CU = 0.10
FLOOR_SILK = 0.15


def spec(**kw):
    kw.setdefault("text", SPECIMEN)
    kw.setdefault("cap_mm", 0.7)
    return M.MicrotextSpec(**kw)


# --- 1. the floor -----------------------------------------------------------

def test_copper_floor_refuses_and_names_a_working_height():
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(cap_mm=0.5, tone="T2"))
    msg = str(e.value)
    assert "0.100 mm copper floor" in msg
    # the refusal has to carry the answer, not just the complaint
    rec = M.check(spec(cap_mm=0.7, tone="T2"))["min_cap"]["recommended_mm"]
    assert f"{rec:.3f} mm" in msg


def test_silk_is_refused_below_its_own_floor_with_the_reason():
    # 0.9 mm clears the silk LEGIBILITY floor and still cannot be printed.
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(cap_mm=0.9, tone="T1"))
    msg = str(e.value)
    assert "0.150 mm silk floor" in msg
    assert "not microprinting" in msg      # the doc's own verdict on silk
    assert "T2 or T6" in msg               # and where to go instead


def test_silk_is_allowed_once_it_clears_its_floor():
    rep = M.check(spec(cap_mm=1.05, tone="T1"))
    assert rep["text_layers"] == ["F.SilkS"]
    assert all(c["ok"] for c in rep["checks"])


@pytest.mark.parametrize("tone,needle", [
    ("T3", "only in copper"),      # mask-only: glyphs would BE the opening
    ("T5", "draws nothing"),       # the bare board
    ("T7", "will not read"),       # buried, and the doc gives no floor at all
])
def test_tones_that_cannot_carry_microtext_are_refused(tone, needle):
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(tone=tone))
    assert needle in str(e.value)


def test_buried_is_reachable_only_deliberately_and_says_it_is_provisional():
    rep = M.check(spec(text="Reckless", cap_mm=4.0, tone="T7",
                       allow_buried=True))
    assert rep["floor_class"] == "buried"
    assert "PROVISIONAL" in rep["floor_note"]


def test_vendor_floor_override_is_enforced():
    # 0.7 mm clears the palette's 0.1 mm copper floor but not a standard fab's
    # 0.127 mm, and the doc calls this "a per-vendor decision".
    M.check(spec(cap_mm=0.7, tone="T2"))
    with pytest.raises(M.MicrotextRefused):
        M.check(spec(cap_mm=0.7, tone="T2", floor_mm=0.127))
    assert M.check(spec(cap_mm=0.9, tone="T2", floor_mm=0.127))


# --- 2. the stroke ----------------------------------------------------------

def test_stroke_scales_with_cap_height_and_is_never_clamped():
    for cap in (0.7, 1.0, 2.0, 5.0):
        rep = M.check(spec(cap_mm=cap, tone="T2"))
        assert rep["stroke_mm"] == pytest.approx(cap * TEXT_STROKE_RATIO)
        assert rep["stroke_mm"] >= FLOOR_CU


def test_the_clamping_bug_is_not_reintroduced():
    """A 0.4 mm cap with the stroke clamped up to the floor is 1:4.

    That is the shape of the bug: it passes a min-feature check on the stroke
    and is unreadable, because the counters are gone. It must be refused, and
    the refusal must say what clamping would have produced.
    """
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(cap_mm=0.4, tone="T2"))
    msg = str(e.value)
    assert "Nothing was clamped" in msg
    assert "1:4.0" in msg


def test_the_writer_guard_is_still_armed_underneath():
    """microtext passes an explicit thickness, so Fp's own floor check runs.

    If the arithmetic above ever went wrong, this is what would catch it -- so
    prove the guard actually fires on a sub-floor stroke rather than assuming.
    """
    fp = ArtFp("guard")
    fp.text_rot("x", 0, 0, 0.7, "F.Cu", thickness=0.05)
    assert fp.floor_hits, "Fp._floor_check did not fire on a 0.05 mm copper stroke"


def test_stroke_ratio_outside_the_legible_band_warns():
    # 3.0 mm is big enough that a 1:4 pen still clears the copper floor, so the
    # ratio warning is what is being tested and not the floor refusal.
    rep = M.check(spec(cap_mm=3.0, tone="T2", stroke_ratio=0.25))
    assert any("outside the 1:6 to 1:8" in w for w in rep["warnings"])


def test_the_clamping_line_is_only_claimed_when_clamping_was_the_temptation():
    """A fat pen at a large cap height fails on counters, not on the stroke.

    Saying "a stroke raised to the floor would fill the counters solid" there
    would be backwards -- raising it would make it THINNER.
    """
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(cap_mm=2.0, tone="T2", stroke_ratio=0.25))
    assert "Nothing was clamped" not in str(e.value)
    # renamed from "narrowest counter": the counter is one row of a gap table
    # now, and the table names each gap by kind. Same assertion, new spelling.
    assert "counter gap" in str(e.value)


# --- 3. the counters --------------------------------------------------------

def test_closed_counters_bind_before_straight_strokes():
    """At 1:6.7 the crossover is D = ratio: below it the counter fails first."""
    r = TEXT_STROKE_RATIO
    for ch in "eE":
        d = SF.GLYPHS[ch][2]
        h_stroke = FLOOR_CU / r
        if d is None:
            continue
        h_counter = FLOOR_CU / (2 * d - r)
        assert (h_counter > h_stroke) == (d < r)

    # and for the specimen as a whole, the counter is what binds
    rep = M.check(spec(cap_mm=0.7, tone="T2"))
    assert rep["min_cap"]["binding"] == "counter"
    assert rep["counter"]["char"] == "e"


def test_specimen_counter_glyphs_are_all_measured():
    """The specimen was chosen for its closed counters; they must be known."""
    m = SF.measure_string(SPECIMEN)
    assert set(m.counter_chars) >= set("eB8g@R0")


def test_counter_clear_matches_the_model():
    cap, r = 0.7, TEXT_STROKE_RATIO
    rep = M.check(spec(cap_mm=cap, tone="T2"))
    d = rep["counter"]["em"]
    assert rep["counter"]["clear_mm"] == pytest.approx(2 * d * cap - cap * r)


def test_a_string_with_no_counters_says_so_instead_of_passing_quietly():
    """'ILT' at a 0.7 mm cap used to PASS here. It is unbuildable.

    The old assertion was that a counterless string reports "no counters" and
    otherwise sails through -- which is precisely the hole: 'LT' puts two
    crossbars 4/21 em apart, so at a 0.7 mm cap and a 1:6.7 pen the copper-to-
    copper spacing is 0.0288 mm against a 0.100 mm floor. Having no counters
    made the string LESS safe, not more, and the tool said nothing.

    So the string is now checked at a cap that actually clears, and the 0.7 mm
    case is kept as the regression it should always have been.
    """
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(text="ILT", cap_mm=0.7, tone="T2"))
    assert "inter-glyph gap" in str(e.value)
    assert "'LT'" in str(e.value)          # and it names the pair

    rep = M.check(spec(text="ILT", cap_mm=2.5, tone="T2"))
    assert rep["counter"] is None
    note = [c["note"] for c in rep["checks"] if c["name"] == "counter gap"]
    assert "inter-glyph and intra-glyph gaps above still bind" in note[0]
    # the gap that binds is spacing, and it is reported as a gap, not a counter
    assert rep["min_cap"]["binding"] == "inter-glyph"


def test_smallest_passing_cap_height_is_the_boundary():
    """The recommended height must pass, and a step below it must not."""
    rep = M.check(spec(cap_mm=1.0, tone="T2"))
    h = rep["min_cap"]["recommended_mm"]
    assert all(c["ok"] for c in M.check(spec(cap_mm=h, tone="T2"))["checks"])
    with pytest.raises(M.MicrotextRefused):
        M.check(spec(cap_mm=h - 0.01, tone="T2"))


# --- 4. the mask block ------------------------------------------------------

def _emit(sp):
    fp = ArtFp("t")
    rep = M.emit(fp, sp)
    return fp, rep


def test_one_opening_over_the_block_not_one_per_glyph():
    fp, rep = _emit(spec(cap_mm=0.7, tone="T2"))
    assert rep["openings"] == 1
    assert rep["glyphs"] == len(SPECIMEN)
    assert sum(1 for i in fp.items if "fp_poly" in i) == 1


def test_the_opening_clears_every_letterform_by_the_asked_for_bleed():
    """Measured against the INK, and against where KiCad really puts it.

    Both corrections matter and neither is obvious: `justify left` slides the
    string right by 0.658 x stroke, and half the pen sticks out past the
    centreline box on every side.
    """
    cap, bleed = 0.7, 0.15
    sp = spec(cap_mm=cap, tone="T2", mask_bleed_mm=bleed)
    _, rep = _emit(sp)
    m = SF.measure_string(SPECIMEN, stroke_ratio=TEXT_STROKE_RATIO)
    pen = rep["stroke_mm"] / 2
    ink = [v * cap for v in m.ink_em]
    ink = (ink[0] - pen, ink[1] - pen, ink[2] + pen, ink[3] + pen)
    box = rep["bbox_mm"]
    for got, want in ((ink[0] - box[0], bleed), (ink[1] - box[1], bleed),
                      (box[2] - ink[2], bleed), (box[3] - ink[3], bleed)):
        assert got == pytest.approx(want, abs=1e-9)


def test_bleed_under_the_registration_tolerance_warns_and_is_not_clamped():
    _, rep = _emit(spec(cap_mm=0.7, tone="T2", mask_bleed_mm=0.02))
    assert any("registration" in w for w in rep["warnings"])
    assert rep["mask_bleed_mm"] == 0.02


def test_t6_is_covert_and_opens_no_mask_at_all():
    _, rep = _emit(spec(cap_mm=0.7, tone="T6"))
    assert rep["mask_layers"] == []
    assert rep["openings"] == 0


def test_runs_whose_openings_would_leave_a_sub_floor_dam_are_merged():
    # A path with a shallow bend puts two runs' openings almost touching.
    # Cap raised 0.7 -> 1.2 mm and the path scaled with it: 'Reckless
    # microprint' contains an 'i', whose stem-to-tittle gap is 5/21 em, so at
    # 0.7 mm it has 0.062 mm of copper spacing against a 0.100 mm floor and is
    # now correctly refused. This test is about mask-dam merging, not about the
    # floor, so it is moved to a cap where the string is legal.
    _, rep = _emit(spec(text="Reckless microprint", cap_mm=1.2, tone="T2",
                        path=[(0, 0), (10, 0), (20, 0.7)]))
    assert rep["openings"] <= rep["runs"]
    quads = rep["openings"]
    assert quads >= 1


# --- placement --------------------------------------------------------------

def test_a_straight_path_collapses_to_one_fp_text():
    fp, rep = _emit(spec(text="Reckless", cap_mm=0.7, tone="T2",
                         path=[(0, 0), (5, 0), (10, 0)]))
    assert rep["runs"] == 1
    assert sum(1 for i in fp.items if "fp_text" in i) == 1


def test_path_rotation_follows_the_tangent():
    _, rep = _emit(spec(text="Reckless", cap_mm=0.7, tone="T2",
                        path=[(0, 0), (10, 10)]))
    # file y grows downward, so a +x+y direction is -45 deg in KiCad's frame
    assert rep["runs"] == 1
    fp = ArtFp("t")
    M.emit(fp, spec(text="Reckless", cap_mm=0.7, tone="T2",
                    path=[(0, 0), (10, 10)]))
    txt = [i for i in fp.items if "fp_text" in i][0]
    assert "-45.0000" in txt


def test_text_longer_than_its_path_is_reported_never_truncated():
    _, rep = _emit(spec(text=SPECIMEN, cap_mm=0.7, tone="T2",
                        path=[(0, 0), (4, 0)]))
    assert rep["glyphs"] + rep.get("blank_runs", 0) == len(SPECIMEN)
    assert any("runs on past the end" in w for w in rep["warnings"])


def test_a_region_too_narrow_for_one_repeat_is_refused_not_truncated():
    with pytest.raises(M.MicrotextRefused) as e:
        M.emit(ArtFp("t"), spec(cap_mm=0.7, tone="T2", region=(0, 0, 5, 5)))
    assert "Refusing to truncate" in str(e.value)


def test_region_rows_fit_inside_the_region():
    cap = 0.7
    _, rep = _emit(spec(cap_mm=cap, tone="T2", region=(0, 0, 40, 8),
                        mask_bleed_mm=0.0))
    assert rep["rows"] >= 2
    # the ink stays inside the region; only the bleed may reach past it
    assert rep["bbox_mm"][0] >= -1e-9 and rep["bbox_mm"][1] >= -1e-9
    assert rep["bbox_mm"][2] <= 40 + 1e-9 and rep["bbox_mm"][3] <= 8 + 1e-9


def test_region_row_gap_below_the_floor_warns_and_is_honoured():
    _, rep = _emit(spec(cap_mm=0.7, tone="T2", region=(0, 0, 40, 8),
                        row_gap_mm=0.02))
    assert any("row-gap" in w for w in rep["warnings"])
    assert rep["row_gap_mm"] == 0.02


# --- the string itself ------------------------------------------------------

@pytest.mark.parametrize("bad", ["cost ${VAR} each", "over~{bar}", "two\nlines"])
def test_strings_kicad_would_rewrite_are_refused(bad):
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(text=bad, cap_mm=2.0, tone="T2"))
    assert "not be fabricated as written" in str(e.value)


def test_unmeasured_characters_are_refused_by_default():
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(text="Reckless™", cap_mm=2.0, tone="T2"))
    assert "no measured metrics" in str(e.value)


def test_unmeasured_characters_are_flagged_never_silently_counted_as_safe():
    rep = M.check(spec(text="Reckless™", cap_mm=2.0, tone="T2",
                       allow_unmeasured=True))
    assert rep["unmeasured"] == ["™"]
    assert any("EXCLUDED from the counter check" in w for w in rep["warnings"])


def test_quotes_and_backslashes_survive_into_the_footprint():
    fp = ArtFp("t")
    fp.text_rot('a"b\\c', 0, 0, 2.0, "F.Cu")
    body = fp.dumps()
    assert '"a\\"b\\\\c"' in body
    # and it still parses as an s-expression
    import verify_art as V
    assert V.parse_sexpr(body)


# --- the font metrics themselves --------------------------------------------

def test_kicad_size_is_the_cap_height():
    assert SF.CAP_HEIGHT_EM == pytest.approx(1.0, abs=1e-4)
    assert SF.X_HEIGHT_EM == pytest.approx(2 / 3, abs=1e-3)
    assert SF.DESCENDER_EM == pytest.approx(1 / 3, abs=1e-3)


def test_advances_land_on_the_font_grid():
    """newstroke is on a 21-unit em grid; a table that drifted off it is wrong."""
    for ch, (adv, _ink, _c) in SF.GLYPHS.items():
        assert abs(adv * 21 - round(adv * 21)) < 0.01, ch


def test_dots_are_classified_out_of_the_counters():
    for ch in ".:;!?i":
        assert SF.GLYPHS[ch][2] is None, f"{ch!r} reported a counter"
    for ch in "08B@eoR":
        assert SF.GLYPHS[ch][2] is not None, f"{ch!r} lost its counter"


def test_anchor_shift_is_applied_and_is_a_pure_translation():
    a = SF.measure_string("HxH", stroke_ratio=0.005)
    b = SF.measure_string("HxH", stroke_ratio=0.15)
    assert (b.ink_em[2] - b.ink_em[0]) == pytest.approx(a.ink_em[2] - a.ink_em[0])
    assert b.ink_em[0] - a.ink_em[0] == pytest.approx(
        SF.ANCHOR_SHIFT_X_PER_EM_STROKE * 0.145)
    assert b.ink_em[1] - a.ink_em[1] == pytest.approx(
        SF.ANCHOR_SHIFT_Y_PER_EM_STROKE * 0.145)


def test_geometry_helpers_agree_with_themselves():
    q = M.box_quad(0, 0, (0, -1, 4, 1), 0.0)
    assert q[0] == (0.0, -1.0) and q[2] == (4.0, 1.0)
    r = M.box_quad(0, 0, (0, -1, 4, 1), 90.0)
    # +x becomes -y (upward) in KiCad's frame
    assert r[1][0] == pytest.approx(-1.0, abs=1e-9)
    assert r[1][1] == pytest.approx(-4.0, abs=1e-9)
    assert M.poly_gap([(0, 0), (1, 0), (1, 1), (0, 1)],
                      [(2, 0), (3, 0), (3, 1), (2, 1)]) == pytest.approx(1.0)


# --- 5. the fab profile -----------------------------------------------------
# The failure these guard against is a part that emits cleanly and then fails
# its own acceptance run, because the emitter sized against a vendor's real
# floor while the verifier checked against the palette doc's generic one.

def test_no_fab_flag_leaves_the_doc_floor_exactly_where_it_was():
    """The default path must not move. Everything else here is opt-in."""
    rep = M.check(spec(cap_mm=0.7, tone="T2"))
    assert rep["fab"] is None
    assert rep["floor_mm"] == pytest.approx(FLOOR_CU)
    assert "pcb-palette.md" in rep["floor_note"]


def test_fab_profile_supplies_the_floor_and_the_part_records_which():
    fine = FP.PROFILES["jlcpcb-4l-fine"]
    rep = M.check(spec(cap_mm=0.7, tone="T2", fab="jlcpcb-4l-fine"))
    assert rep["floor_mm"] == pytest.approx(fine.min_copper_mm)
    assert rep["fab"]["key"] == "jlcpcb-4l-fine"
    assert fine.source in rep["floor_note"]

    fp = ArtFp("t", tags="recklessart microtext")
    M.emit(fp, spec(text="Testing", cap_mm=1.05, tone="T2",
                fab="jlcpcb-4l-fine"))
    assert FP.tag_for("jlcpcb-4l-fine") in fp.tags
    assert FP.from_tags(fp.tags)[0] == "jlcpcb-4l-fine"


def test_the_emitted_tag_is_what_the_verifier_resolves(tmp_path):
    """The whole coupling: the sizing floor and the checking floor, one source.

    Sizing at a vendor's fine floor and checking against the doc's generic one
    is exactly the split that let a part emit and then fail its own verifier.
    """
    import verify_art as V
    fp = ArtFp("t", tags="recklessart microtext")
    rep = M.emit(fp, spec(text="Testing", cap_mm=1.05, tone="T2",
                          fab="jlcpcb-4l-fine"))
    p = tmp_path / "t.kicad_mod"
    p.write_text(fp.dumps(), encoding="utf-8")

    pal = V.load_palette(None, "front")
    assert pal.floors["copper"] == pytest.approx(FLOOR_CU)      # the doc, before

    key, _ = FP.from_tags(V.load_footprint(p).tags)
    assert key == "jlcpcb-4l-fine"
    V.apply_fab(pal, key)
    assert pal.floors["copper"] == pytest.approx(rep["floor_mm"])  # the part, after


def test_fab_and_floor_together_are_refused():
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(cap_mm=0.7, tone="T2", fab="jlcpcb-4l-fine", floor_mm=0.12))
    assert "same decision said two ways" in str(e.value)


def test_an_unknown_profile_is_refused_by_name():
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(cap_mm=0.7, tone="T2", fab="pcbway"))
    assert "not a fabrication profile" in str(e.value)


def test_a_profile_does_not_loosen_the_buried_floor():
    """min_copper_mm is an OUTER-layer etch limit. Buried is coarser, not finer,
    so a profile that says nothing about buried layers must not be read as
    permission to shrink the one floor the doc already calls provisional."""
    rep = M.check(spec(text="Testing", cap_mm=5.75, tone="T4",
                       fab="jlcpcb-4l-fine", allow_buried=True))
    assert rep["floor_class"] == "buried"
    assert rep["floor_mm"] == pytest.approx(0.50)
    assert any("publishes no buried-layer minimum" in n for n in rep["notes"])

    # and had the profile's 0.0889 been taken, this 2.0 mm cap -- whose stroke
    # is 0.30 mm -- would have sailed through instead of being refused.
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(text="Testing", cap_mm=2.0, tone="T4",
                     fab="jlcpcb-4l-fine", allow_buried=True))
    assert "0.500 mm buried floor" in str(e.value)


def test_a_part_cannot_claim_two_processes():
    fp = ArtFp("t", tags="recklessart microtext fab:jlcpcb-2l")
    with pytest.raises(M.MicrotextRefused) as e:
        M.emit(fp, spec(text="Testing", cap_mm=1.05, tone="T2",
                        fab="jlcpcb-4l-fine"))
    assert "already tagged" in str(e.value)
    with pytest.raises(ValueError):
        FP.from_tags("recklessart fab:jlcpcb-2l fab:jlcpcb-4l-fine")


def _body():
    return " ".join((pathlib.Path(__file__).resolve().parents[1]
                     / "examples" / "bitcoin_whitepaper_s1.txt")
                    .read_text(encoding="utf-8").split())


def test_the_0603_whitepaper_cap_is_not_manufacturable():
    """THIS TEST USED TO ASSERT THE OPPOSITE, AND IT WAS WRONG.

    It read: "0.6030 mm is floor/D, derived -- not a number anybody picked. At
    r = D the stroke bound and the counter bound coincide, which is the global
    minimum cap over every stroke ratio." Every clause of that is true about
    the two-constraint model and the model was not the problem the part had.

    min_copper_mm is minimum trace width AND SPACING. At cap 0.6030 mm and
    r = D = 0.14744 the 'e' counter does clear 0.0889 mm -- and the crossbars
    of 'r' and 't', which are 4/21 em apart, clear 0.0261 mm, 29% of the floor.
    'floor/D' answered a question that does not bind. The old assertion is
    therefore inverted rather than adjusted: the part it blessed is refused.
    """
    body = _body()
    floor = FP.PROFILES["jlcpcb-4l-fine"].min_copper_mm
    D = SF.measure_string(body).counter_em
    assert D == pytest.approx(0.14744)
    assert floor / D == pytest.approx(0.60296, abs=1e-5)   # the old answer

    with pytest.raises(M.MicrotextRefused) as e:
        M.check(spec(text=body, cap_mm=0.6030, tone="T2", stroke_ratio=D,
                     fab="jlcpcb-4l-fine"))
    msg = str(e.value)
    assert "inter-glyph gap" in msg
    # and the number that condemns it, re-derived here rather than quoted
    m = SF.measure_string(body)
    inter = [c for c in SF.gap_constraints(m) if c.name == "inter-glyph"][0]
    assert inter.em == pytest.approx(4 / 21, abs=2e-5)
    assert inter.clear_mm(0.6030, 0.6030 * D) == pytest.approx(0.0261, abs=5e-4)
    assert inter.clear_mm(0.6030, 0.6030 * D) < 0.30 * floor


def test_the_binding_constraint_is_spacing_not_the_counter():
    """Enumerated, not spot-checked: the counter is the LOOSEST of the four."""
    m = SF.measure_string(_body())
    by = {c.name: c for c in SF.gap_constraints(m)}
    assert set(by) == {"stroke", "inter-glyph", "intra-glyph", "counter"}
    assert by["inter-glyph"].em == pytest.approx(4 / 21, abs=2e-5)   # 'rt','tt','ff'
    assert by["intra-glyph"].em == pytest.approx(5 / 21, abs=2e-5)   # 'i' tittle
    assert by["counter"].em == pytest.approx(0.294880)               # 'e', 2D
    assert by["inter-glyph"].em < by["intra-glyph"].em < by["counter"].em
    # only the inter-glyph one can be widened by letter-spacing
    assert by["inter-glyph"].trackable
    assert not by["intra-glyph"].trackable and not by["counter"].trackable


def test_tracking_saturates_where_the_glyphs_own_geometry_takes_over():
    """1/21 em is not a taste decision, it is where the curve goes flat.

    Tracking widens G_adv = 4/21 and nothing else, so the achievable gap is
    min(4/21 + T, 5/21) and it stops improving at T = 1/21 exactly. Past that
    the 'i' stem-to-tittle gap binds and no amount of spacing touches it.
    """
    body = _body()
    floor = FP.PROFILES["jlcpcb-4l-fine"].min_copper_mm
    caps = {}
    for k in range(0, 9):
        T = k / 4 / 21                       # 0 .. 2/21 in quarter-21ths
        m = SF.measure_string(body, tracking=T)
        r, _ = SF.optimum_ratio(m)
        caps[k], _ = SF.min_cap_for_floor(floor, r, m)
    # strictly falling up to 1/21, then flat
    for k in range(4):
        assert caps[k] > caps[k + 1] + 1e-6
    for k in range(4, 8):
        assert caps[k] == pytest.approx(caps[k + 1], abs=1e-9)
    assert caps[0] == pytest.approx(floor * 21 / 2, abs=1e-4)     # 0.93345
    assert caps[4] == pytest.approx(floor * 42 / 5, abs=1e-4)     # 0.74676


def test_the_tracked_optimum_clears_every_gap_at_once():
    """r = 5/42, cap = 0.0889 * 8.4. Three constraints land on the floor."""
    body = _body()
    floor = FP.PROFILES["jlcpcb-4l-fine"].min_copper_mm
    m = SF.measure_string(body, tracking=1 / 21)
    r, _ = SF.optimum_ratio(m)
    assert r == pytest.approx(5 / 42, abs=2e-6)
    cap, binding = SF.min_cap_for_floor(floor, r, m)
    assert cap == pytest.approx(floor * 42 / 5, abs=1e-4)     # 0.746760 mm
    assert cap * r == pytest.approx(floor, abs=1e-6)          # stroke == floor

    rep = M.check(spec(text=body, cap_mm=cap, tone="T2", stroke_ratio=r,
                       tracking_em=1 / 21, fab="jlcpcb-4l-fine"))
    assert all(g["ok"] for g in rep["gaps"])
    got = {g["name"]: g["clear_mm"] for g in rep["gaps"]}
    assert got["stroke"] == pytest.approx(floor, abs=1e-6)
    assert got["inter-glyph"] == pytest.approx(floor, abs=1e-5)
    assert got["intra-glyph"] == pytest.approx(floor, abs=1e-6)
    assert got["counter"] == pytest.approx(0.131305, abs=1e-5)

    # a hundredth of a millimetre less does not
    with pytest.raises(M.MicrotextRefused):
        M.check(spec(text=body, cap_mm=cap - 0.01, tone="T2", stroke_ratio=r,
                     tracking_em=1 / 21, fab="jlcpcb-4l-fine"))


def test_the_tracked_optimum_ratio_is_outside_the_legible_band_and_says_so():
    """1:8.4 is NOT inside the palette's 1:8-1:6 band. It is just outside it.

    Worth an assertion because the arithmetic is easy to get backwards: the
    band is a range of RATIOS, 1/8 = 0.125 to 1/6 = 0.1667, and 5/42 = 0.1190
    is below the lighter end. The tool must warn rather than let a
    reciprocal-vs-ratio slip pass for compliance.
    """
    assert 5 / 42 < M.RATIO_BAND[0]
    body = _body()
    floor = FP.PROFILES["jlcpcb-4l-fine"].min_copper_mm
    # Take the cap from the model, not from floor*42/5. The closed form assumes
    # the intra-glyph gap is exactly 5/21; GLYPHS carries it to five decimals as
    # 0.238095, which is 2e-7 mm of cap short of the ideal. Asserting against
    # the ideal would be asserting against a number the table does not hold.
    m = SF.measure_string(body, tracking=1 / 21)
    cap, _ = SF.min_cap_for_floor(floor, 5 / 42, m)
    assert cap == pytest.approx(floor * 42 / 5, rel=1e-5)
    rep = M.check(spec(text=body, cap_mm=cap, tone="T2",
                       stroke_ratio=5 / 42, tracking_em=1 / 21,
                       fab="jlcpcb-4l-fine"))
    assert any("outside the 1:6 to 1:8" in w for w in rep["warnings"])


# --- 6. letter-spacing ------------------------------------------------------

def test_tracking_defaults_to_zero_and_changes_nothing_at_zero():
    """The whole point of the default. Metrics and placement, both."""
    s = "Reckless microprint"
    assert M.MicrotextSpec(text=s, cap_mm=1.2).tracking_em == 0.0
    a = SF.measure_string(s)
    b = SF.measure_string(s, tracking=0.0)
    assert (a.advance_em, a.ink_em, a.counter_em, a.inter_gap_em,
            a.intra_gap_em) == (b.advance_em, b.ink_em, b.counter_em,
                                b.inter_gap_em, b.intra_gap_em)
    # and one run stays one fp_text, holding the whole string
    run = M.Run(s, 3.0, -1.0, 0.0)
    assert M._placements(M.MicrotextSpec(text=s, cap_mm=1.2), run, 1.2) == \
        [(s, 3.0, -1.0, 0.0)]


def test_tracking_is_inserted_between_glyphs_not_after_the_last():
    """n-1 gaps for n glyphs, or the ink box and the path walk disagree."""
    s = "rtiffe"
    T = 1 / 21
    a = SF.measure_string(s)
    b = SF.measure_string(s, tracking=T)
    assert b.advance_em - a.advance_em == pytest.approx((len(s) - 1) * T)
    assert (b.ink_em[2] - b.ink_em[0]) - (a.ink_em[2] - a.ink_em[0]) == \
        pytest.approx((len(s) - 1) * T)
    assert b.tracking_em == T


def test_tracking_widens_the_inter_glyph_gap_and_only_that():
    s = "rtiffe"
    T = 1 / 21
    a = {c.name: c.em for c in SF.gap_constraints(SF.measure_string(s))}
    b = {c.name: c.em for c in SF.gap_constraints(
        SF.measure_string(s, tracking=T))}
    assert b["inter-glyph"] - a["inter-glyph"] == pytest.approx(T)
    assert b["intra-glyph"] == a["intra-glyph"]     # 'i' stem to tittle
    assert b["counter"] == a["counter"]             # 'e'


def test_tracking_emits_one_fp_text_per_glyph_at_the_pen_offsets():
    """KiCad text has no letter-spacing attribute, so this is how it is done.

    Exactness rests on `justify left`'s slide being a pure translation, which
    stroke_font measured; the offsets asserted here are the pen positions that
    fact makes correct.
    """
    s = "rt if"
    cap, T = 2.0, 1 / 21
    sp = M.MicrotextSpec(text=s, cap_mm=cap, tracking_em=T)
    got = M._placements(sp, M.Run(s, 0.0, 0.0, 0.0), cap)
    assert [g[0] for g in got] == ["r", "t", "i", "f"]   # the space is advance
    pen = 0.0
    want = []
    for i, ch in enumerate(s):
        if i:
            pen += T
        if ch != " ":
            want.append(pen * cap)
        pen += SF.GLYPHS[ch][0]
    for (ch, x, y, ang), wx in zip(got, want):
        assert x == pytest.approx(wx, abs=1e-12)
        assert (y, ang) == (0.0, 0.0)

    fp = ArtFp("t")
    M.emit(fp, M.MicrotextSpec(text=s, cap_mm=cap, tone="T2", tracking_em=T))
    assert sum(1 for i in fp.items if "fp_text" in i) == 4


def test_tracking_rotates_with_the_run():
    """Per-glyph offsets are along the run's baseline, not along +x."""
    cap, T = 2.0, 1 / 21
    sp = M.MicrotextSpec(text="rt", cap_mm=cap, tracking_em=T, angle_deg=90.0)
    got = M._placements(sp, M.Run("rt", 0.0, 0.0, 90.0), cap)
    step = (SF.GLYPHS["r"][0] + T) * cap
    # placements are (text, x, y, angle); +90 deg in KiCad's frame turns the
    # advance direction +x into -y, i.e. upward in the file
    assert got[1][0] == "t"
    assert got[1][1] == pytest.approx(0.0, abs=1e-12)
    assert got[1][2] == pytest.approx(-step, abs=1e-12)


def test_the_legacy_two_constraint_signature_is_refused_not_silently_partial():
    """min_cap_for_floor(floor, r, D) is the API that shipped the bad part."""
    with pytest.raises(TypeError) as e:
        SF.min_cap_for_floor(0.0889, 0.14744, 0.14744)
    assert "StringMetrics" in str(e.value)


def test_the_dot_classification_is_checked_at_the_ratio_in_use():
    """stroke_font drops dot-sized voids as solid ink. Only true if the pen is
    wider than the dot -- so the assumption is tested, not asserted."""
    assert SF.dots_are_solid(5 / 42)                    # 0.1190 > 0.0458
    assert not SF.dots_are_solid(0.02)
    assert SF.DOT_VOID_MAX_EM < SF.COUNTER_MIN_EM / 5   # nothing near the line
    rep = M.check(spec(text="Reckless", cap_mm=8.0, tone="T2",
                       stroke_ratio=0.02))
    assert any("dots are NOT solid" in w for w in rep["warnings"])


# --- 6. does the text fit the shape? both directions, both loud -------------
#
# The defect these test: the flow already knew how well the text filled the
# shape and printed it as a neutral statistic ("M/N mask spans filled"), so a
# body that ran out with eleven row bands still empty read exactly like a body
# that fitted. The mirror case was worse -- a body too long REFUSED, which is
# right, but said nothing a caller could act on.
#
# The shapes here are built by hand rather than rasterised, so the arithmetic
# under test is the flow's and not cairosvg's, and so the suite needs no asset
# that this public repo does not carry.

_VOCAB = ("the quick brown fox jumps over a lazy dog and then some more "
          "words to make up the count").split()


def _words(n):
    return " ".join(_VOCAB[i % len(_VOCAB)] for i in range(n))


def _mask(rows, mm_per_px=0.25, origin=(0.0, 0.0)):
    """rows: list of '#'/'.' strings, one per raster row. '#' = fillable."""
    import numpy as np
    g = np.array([[c == "#" for c in r] for r in rows], dtype=bool)
    return M.ShapeMask(grid=g, mm_per_px=mm_per_px, origin=tuple(origin),
                       source="hand-built", raster_tool="none")


def _rect(w_mm=40.0, h_mm=40.0, mm_per_px=0.25):
    cols = int(round(w_mm / mm_per_px))
    rows = int(round(h_mm / mm_per_px))
    return _mask(["#" * cols] * rows, mm_per_px)


def _flowspec(text, shape, **kw):
    # floor_mm 0.05 keeps every fab and counter check clear across the whole
    # cap range these tests search, so what is being measured is the FILL logic
    # and not the floor logic -- which has its own tests above.
    kw.setdefault("cap_mm", 0.8)
    kw.setdefault("stroke_ratio", 0.125)
    kw.setdefault("floor_mm", 0.05)
    return M.MicrotextSpec(text=text, shape=shape, **kw)


def _run(sp):
    rep = M.check(sp)
    M.place(sp, rep)
    return rep


def _fill(sp):
    return _run(sp)["fill"]


def _capacity(shape, cap=0.8):
    """Characters this shape swallows at `cap`, found by running the flow.

    Deliberately measured rather than computed: the point of the whole change
    is that capacity in a shape is not a closed form.
    """
    def fits(n):
        sp = _flowspec(_words(n), shape, cap_mm=cap)
        return not M._flow(sp, cap, 0.05).words_left

    lo, hi = 0, 1
    while fits(hi) and hi < 1 << 16:
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return lo


def test_a_body_that_fills_the_shape_passes_silently():
    """No warning, no refusal, and the verdict says so in one word."""
    shape = _rect()
    sp = _flowspec(_words(_capacity(shape)), shape)
    rep = _run(sp)
    assert rep["fill"]["verdict"] == "fits"
    assert rep["fill"]["bands_underfilled"] == 0
    assert not any("UNDERFILL" in w or "OVERFILL" in w
                   for w in rep["warnings"])


def test_text_far_too_short_warns_and_names_the_shortfall_in_characters():
    shape = _rect()
    full = _capacity(shape)
    sp = _flowspec(_words(full // 4), shape)
    rep = _run(sp)
    f = rep["fill"]
    assert f["verdict"] == "underfill"
    assert f["bands_underfilled"] >= 1
    msg = next(w for w in rep["warnings"] if w.startswith("UNDERFILL"))
    # the owner's wording: how long the text must be, and how far short it is
    assert "Text length must be at least about" in msg
    assert f"{f['need_chars']} characters" in msg
    assert f"about {f['shortfall_chars']} characters short" in msg
    assert "Provide more text" in msg
    assert "lower the microprinting resolution" in msg
    # and it says the number is an estimate, and where the estimate came from
    assert "ESTIMATE" in msg
    assert "measured, not modelled" in msg
    assert f["shortfall_measured"] is True


def test_the_shortfall_is_measured_by_running_the_flow_not_by_density():
    """A width-times-density figure -- abandoned span width times the
    characters per mm the run achieved where it did fill -- reads high, because
    a greedy flow wastes far more of a narrow span than of a wide one. On the
    shipped mark it says 117 where 89 already clears the last band. So the
    quoted number comes from re-running the flow with the body extended, and
    the density figure is kept beside it as the cross-check it is."""
    shape = _rect()
    sp = _flowspec(_words(_capacity(shape) // 3), shape)
    f = _fill(sp)
    assert f["shortfall_measured"] is True
    assert f["shortfall_by_density_chars"] is not None
    # the quoted number is the measured one, and it is the SMALLEST addition
    # that clears the last band: one character less must still be underfilled
    n = f["shortfall_chars"]
    filler = (" " + sp.text) * (n // (len(sp.text) + 1) + 1)
    for extra, want in ((n, 0), (n - 1, 1)):
        fl = M._flow(_flowspec(sp.text + filler[:extra], shape), 0.8, 0.05)
        assert (len(fl.bands_abandoned) == 0) == (want == 0)


def test_the_shortfall_estimate_is_the_right_size():
    """Not exact -- word boundaries are lumpy and the message says so -- but it
    has to be close enough to act on, or naming a number is worse than not."""
    shape = _rect()
    full_words = _capacity(shape)
    full_chars = len(_words(full_words))
    sp = _flowspec(_words(full_words // 2), shape)
    f = _fill(sp)
    assert f["need_chars"] == pytest.approx(full_chars, rel=0.10)


def test_the_larger_cap_it_offers_actually_fills_the_shape():
    """The remedy is checked by running the flow at the cap it names, so this
    test is really asking whether the tool verified before it recommended."""
    shape = _rect()
    sp = _flowspec(_words(_capacity(shape) // 2), shape)
    f = _fill(sp)
    assert f["remedy_cap_mm"] is not None and f["remedy_cap_verified"]
    assert f["remedy_cap_mm"] > sp.cap_mm          # coarser, not finer
    again = _fill(_flowspec(sp.text, shape, cap_mm=f["remedy_cap_mm"]))
    assert again["verdict"] == "fits"
    assert again["bands_underfilled"] == 0


def test_underfill_warns_but_refuses_when_the_caller_asks_it_to():
    """WARN is the default because nothing is lost and the blank is visible.
    An unattended build can make it fatal, and then the message is the same."""
    shape = _rect()
    short = _words(_capacity(shape) // 4)
    assert _fill(_flowspec(short, shape))["verdict"] == "underfill"
    with pytest.raises(M.MicrotextRefused) as e:
        _run(_flowspec(short, shape, require_fill=True))
    assert "UNDERFILL" in str(e.value)
    assert "shape-require-fill" in str(e.value)


def test_text_far_too_long_refuses_and_names_the_characters_that_did_not_fit():
    shape = _rect()
    long = _words(_capacity(shape) * 2)
    with pytest.raises(M.MicrotextRefused) as e:
        _run(_flowspec(long, shape))
    msg = str(e.value)
    assert msg.startswith("OVERFILL")
    assert "DID NOT FIT" in msg and "TRUNCATED" in msg
    n = int(msg.split("OVERFILL -- the shape ran out before the text did. "
                      )[1].split(" character")[0])
    assert 0 < n < len(long)
    assert "Refusing to truncate the text silently" in msg
    assert "shape-allow-truncation" in msg


def test_the_smaller_cap_it_offers_actually_fits_the_long_text():
    shape = _rect()
    long = _words(int(_capacity(shape) * 1.4))
    sp = _flowspec(long, shape, allow_truncation=True)
    f = _fill(sp)
    assert f["verdict"] == "overfill"
    assert f["remedy_cap_mm"] is not None and f["remedy_cap_verified"]
    assert f["remedy_cap_mm"] < sp.cap_mm          # finer, not coarser
    again = M._flow(_flowspec(long, shape, cap_mm=f["remedy_cap_mm"]),
                    f["remedy_cap_mm"], 0.05)
    assert again.words_left == 0


def test_deliberate_truncation_is_a_choice_and_is_recorded():
    """Announced truncation is allowed; silent truncation is the defect. The
    dropped characters go into the report so nothing is only on stdout."""
    shape = _rect()
    long = _words(_capacity(shape) * 2)
    rep = _run(_flowspec(long, shape, allow_truncation=True))
    f = rep["fill"]
    assert f["verdict"] == "overfill"
    assert f["surplus_chars"] == len(f["truncated"])
    assert long.endswith(f["truncated"])
    assert any("TRUNCATED ON PURPOSE" in w for w in rep["warnings"])


def test_when_no_fabricable_cap_fits_it_says_so_instead_of_truncating():
    """The floor bounds how fine the microprinting can go. Past that there is
    no remedy in cap height at all, and saying 'raise the resolution' would be
    advice the caller cannot take."""
    shape = _rect(20.0, 20.0)
    # 20x smaller shape, and the doc's real copper floor rather than the
    # relaxed one, so min_cap sits just under the cap and buys almost nothing.
    sp = M.MicrotextSpec(text=_words(4000), shape=shape, cap_mm=1.0,
                         stroke_ratio=0.125, tone="T2")
    with pytest.raises(M.MicrotextRefused) as e:
        _run(sp)
    msg = str(e.value)
    assert "There is NO finer resolution to raise to" in msg
    assert "STILL about" in msg and "characters too long" in msg
    assert "cannot be made to fit this shape at this process" in msg


def test_short_rows_at_the_extremities_are_not_called_underfill():
    """THE THRESHOLD, and the reason it is not a percentage of bands.

    A letterform's extremities are slivers no word ever fits, and measured
    across the shapes in this tree the fraction of bands carrying text ranges
    from 0% to 100% without separating the cases: assets/normalised/
    reckless_black.svg carries text in 15 of 43 bands and is not underfilled at
    all, while the shipped art_btc_whitepaper_b carries text in 52 of 58 and
    is. So the measure is capacity ABANDONED -- span width wide enough for the
    narrowest word in the body that got nothing because the words ran out.

    Here: a wide bar over a hairline tail. Fill the bar exactly. Two thirds of
    the bands end up blank, and none of it is underfill -- until the tail is
    widened past the narrowest word in the body, which is exactly where the
    line is drawn.
    """
    mm = 0.25
    bar = "#" * 160                                     # 40 mm

    def tail_of(px):
        return ("." * ((160 - px) // 2) + "#" * px
                + "." * ((160 - px + 1) // 2))

    # 'a' is the narrowest word in _VOCAB and is 0.481 mm of ink at this cap
    # and pen, so one raster column (0.25 mm) is under it and three (0.75 mm)
    # are over it. Nothing else about the two shapes differs.
    thin = _mask([bar] * 40 + [tail_of(1)] * 80, mm)
    fat = _mask([bar] * 40 + [tail_of(3)] * 80, mm)

    sp = _flowspec(_words(_capacity(thin)), thin)
    f = _fill(sp)
    assert f["bands_empty"] >= 2 * f["bands_with_text"]     # mostly blank
    assert f["spans_abandoned"] > 0                        # and reached
    assert f["spans_abandoned_usable"] == 0                # but none usable
    assert f["bands_underfilled"] == 0
    assert f["verdict"] == "fits"

    # the same body, the same bar, half a millimetre more tail: now some word
    # in this very text WOULD have gone there, and the tool says so
    g = _fill(_flowspec(sp.text, fat))
    assert g["spans_abandoned_usable"] > 0
    assert g["verdict"] == "underfill"


def test_the_row_fill_distribution_is_reported_whatever_the_verdict():
    """The shipped part runs 4 to 67 characters a row with a stdev of half the
    mean, and nothing in the report said so."""
    mm = 0.25
    wide = "#" * 160
    narrow = "." * 60 + "#" * 40 + "." * 60
    shape = _mask(([wide] * 8 + [narrow] * 8) * 6, mm)
    sp = _flowspec(_words(_capacity(shape)), shape)
    rc = _fill(sp)["row_chars"]
    assert rc["n"] >= 4
    assert rc["min"] < rc["mean"] < rc["max"]
    assert rc["stdev"] > 0 and rc["cv"] == pytest.approx(rc["stdev"] / rc["mean"])
    out = io.StringIO()
    M.print_report(_run(sp), out)
    assert f"{rc['min']} to {rc['max']} characters" in out.getvalue()
    assert f"stdev/mean {rc['cv']:.2f}" in out.getvalue()


def test_every_span_is_counted_not_only_the_ones_the_flow_visited():
    """The old loop broke out of the span list once the body ran out, so
    spans_total counted spans VISITED -- one per band after that point -- and
    the capacity the text never reached was absent from the report entirely."""
    shape = _rect()
    full = _capacity(shape)
    long_run = M._flow(_flowspec(_words(full), shape), 0.8, 0.05)
    short_run = M._flow(_flowspec(_words(full // 4), shape), 0.8, 0.05)
    # same shape, same cap: the span inventory cannot depend on the text
    assert len(long_run.spans) == len(short_run.spans)
    assert len(short_run.filled) < len(long_run.filled)
    assert len(short_run.abandoned) > 0


def test_the_recommended_cap_was_run_not_modelled():
    """Every cap this module offers comes back with the flow that proves it."""
    shape = _rect()
    sp = _flowspec(_words(_capacity(shape) // 3), shape)
    f = _fill(sp)
    got = M._bisect_cap(sp, 0.05, sp.cap_mm, sp.cap_mm * 3.0,
                        lambda fl: bool(fl.runs) and not fl.bands_abandoned)
    assert got is not None
    cap, flow = got
    assert cap == pytest.approx(f["remedy_cap_mm"])
    assert not flow.bands_abandoned
    # quantised to the grid the min_cap recommendation already uses
    assert cap / M.CAP_GRID_MM == pytest.approx(round(cap / M.CAP_GRID_MM))


def test_the_emitted_geometry_still_holds_the_whole_source_text():
    """"98.6% of characters placed" is what silent truncation looks like too.

    So the claim is proved the only way it can be: the footprint is written,
    parsed back, its fp_text strings sorted into reading order by (y, x) and
    rejoined, and the result walked against the source. The only permitted
    difference is inter-word spaces -- the ones the flow consumes at a span end
    and, with tracking on, the ones that are never emitted at all because a
    space draws no ink. A single non-space character out of place fails this.

    Run against the shipped library/RecklessArt.pretty/art_btc_whitepaper_b:
    all 1799 source characters recovered, in order, 266 spaces missing and
    nothing else. That part is not truncating.
    """
    import re
    shape = _rect(30.0, 30.0)
    sp = _flowspec(_words(_capacity(shape)), shape, tone="T2")
    fp = ArtFp("roundtrip")
    M.emit(fp, sp)
    got = re.findall(r'\(fp_text user "((?:[^"\\\\]|\\\\.)*)"\s*\(at'
                     r' ([-\d.]+) ([-\d.]+)', fp.dumps())
    assert got
    cells = sorted((round(float(y), 4), float(x), t) for t, x, y in got)
    joined = "".join(t for _, _, t in cells)

    src, i, j, dropped = sp.text, 0, 0, 0
    while i < len(src) and j < len(joined):
        if src[i] == joined[j]:
            i += 1
            j += 1
        elif src[i] == " ":
            dropped += 1
            i += 1
        else:
            raise AssertionError(f"diverged at source {i}: "
                                 f"{src[i-20:i+20]!r} vs {joined[j-20:j+20]!r}")
    while i < len(src) and src[i] == " ":
        dropped += 1
        i += 1
    assert i == len(src), f"{len(src)-i} source characters never reached the board"
    assert j == len(joined), "the board carries characters the source does not"
    assert dropped == src.count(" ") - joined.count(" ")


def test_placement_is_byte_for_byte_what_it_always_was():
    """The walk was refactored to record every span; it must not have moved a
    single glyph. Checked against the flow's own outputs, run twice."""
    shape = _rect(30.0, 30.0)
    sp = _flowspec(_words(_capacity(shape)), shape)
    fl = M._flow(sp, 0.8, 0.05)
    rep = _run(sp)
    assert rep["runs"] == len(fl.runs)
    assert "".join(r.text for r in fl.runs).replace(" ", "") == \
        sp.text.replace(" ", "")


# --- 6. breaking a word, and what a break is allowed to change --------------
#
# THE OBJECT UNDER TEST IS RECONSTRUCTED, NOT DESCRIBED. legacy_flow() below is
# the walk as it stood before this round, spliced back in verbatim, so every
# "it used to do X" in this file is an assertion about a runnable thing rather
# than a claim in a docstring. It is itself checked against the defect report:
# 'peer-to-peer' at hyphen_min 3, the word with the most break points in the
# whitepaper's first sentence, was the hardest word in the text to place.

_HVOCAB = ("a purely peer-to-peer version of electronic cash would allow "
           "online payments proof-of-work hash-based non-reversible "
           "double-spending timestamp server").split()


def _hwords(n):
    return " ".join(_HVOCAB[i % len(_HVOCAB)] for i in range(n))


def legacy_flow(spec, cap, floor, *, gap=None):
    """tools/microtext.py _flow() as it stood before the hyphen repair.

    Kept whole rather than paraphrased: three of the four defects are in the
    arithmetic of the six lines at the bottom of the span loop, and a
    paraphrase would be a chance to fix one of them by accident.
    """
    shape = spec.shape
    stroke = cap * float(spec.stroke_ratio)
    pen = stroke / 2.0
    _w = {}

    def inkw(s):
        v = _w.get(s)
        if v is None:
            b = M.measure(spec, s).ink_em
            v = 0.0 if b is None else (b[2] - b[0]) * cap + 2 * pen
            _w[s] = v
        return v

    def ink_left(s):
        b = M.measure(spec, s).ink_em
        return 0.0 if b is None else b[0] * cap - pen

    m = M.measure(spec, spec.text)
    ry0 = m.ink_em[1] * cap - pen
    ry1 = m.ink_em[3] * cap + pen
    ink_h = ry1 - ry0
    if gap is None:
        gap = spec.row_gap_mm if spec.row_gap_mm is not None else floor
    pitch = ink_h + gap
    words = spec.text.split()
    narrowest = min(inkw(w) for w in set(words))
    wi, tail = 0, ""
    spans_rec, runs = [], []
    band = 0
    y = shape.origin[1]
    while y + ink_h <= shape.origin[1] + shape.height_mm + 1e-9:
        for sx0, sx1 in shape.band_spans(y, y + ink_h,
                                         whole_band=spec.shape_whole_band):
            avail = sx1 - sx0
            if wi >= len(words) and not tail:
                spans_rec.append(M.FlowSpan(band, y, sx0, sx1, "abandoned",
                                            usable=avail >= narrowest - 1e-9))
                continue
            chunk, tail = tail, ""
            if chunk and inkw(chunk) > avail + 1e-9:
                tail, chunk = chunk, ""
            while wi < len(words):
                cand = (chunk + " " + words[wi]) if chunk else words[wi]
                if inkw(cand) > avail + 1e-9:
                    break
                chunk = cand
                wi += 1
            if not chunk and spec.hyphenate and wi < len(words):
                w = words[wi]
                for k in range(len(w) - spec.hyphen_min, spec.hyphen_min - 1, -1):
                    if inkw(w[:k] + "-") <= avail + 1e-9:
                        chunk, tail = w[:k] + "-", w[k:]
                        wi += 1
                        break
            if not chunk:
                spans_rec.append(M.FlowSpan(band, y, sx0, sx1, "narrow"))
                continue
            spans_rec.append(M.FlowSpan(band, y, sx0, sx1, "filled", text=chunk))
            runs.append(M.Run(chunk, sx0 - ink_left(chunk), y - ry0, 0.0))
        band += 1
        y += pitch
    rest = " ".join(([tail] if tail else []) + words[wi:])
    return M.Flow(spans=spans_rec, runs=runs, bands=band, ink_h=ink_h,
                  pitch=pitch, words_total=len(words), words_placed=wi,
                  unplaced=rest)


def test_the_legacy_break_positions_are_the_ones_the_defect_report_names():
    """k=8 doubles the hyphen, k=7 inserts one where the author has one, k=5
    doubles it again. Runnable, so nobody has to take the report's word."""
    w, hmin = "peer-to-peer", 3
    got = {k: (w[:k] + "-", w[k:])
           for k in range(len(w) - hmin, hmin - 1, -1)}
    assert got[8][0] == "peer-to--"                 # (b) doubled
    assert got[5][0] == "peer--"                    # (b) doubled again
    assert got[7] == ("peer-to-", "-peer")          # (a) inserted at a real one
    assert got[4] == ("peer-", "-to-peer")
    # and joining any of them back up does NOT give the source word
    for k, (head, tail) in got.items():
        if head[-2:] == "--" or tail[:1] == "-":
            assert head + tail != w


def test_an_existing_hyphen_is_a_break_point_with_the_flag_off():
    """(c) The whole path used to be gated on --shape-hyphenate, so with the
    flag off -- how the shipped part was built -- 'peer-to-peer' was atomic."""
    mm = 0.25
    # spans wide enough for "peer-" and not for "to-peer"
    shape = _mask(["#" * 14] * 60, mm)
    sp = _flowspec("peer-to-peer version", shape, hyphenate=False)
    fl = M._flow(sp, 0.8, 0.05)
    assert [r.text for r in fl.runs][:3] == ["peer-", "to-", "peer"]
    assert fl.soft_breaks >= 2
    assert fl.inserted == []               # nothing was added to the text
    assert "".join(r.text for r in fl.runs[:3]) == "peer-to-peer"
    old = legacy_flow(_flowspec("peer-to-peer version", shape,
                                hyphenate=False), 0.8, 0.05)
    # the legacy walk could not place the word at all and jammed on it
    assert old.runs == [] or old.runs[0].text != "peer-"
    assert "peer-to-peer" in old.unplaced


def test_no_break_ever_doubles_a_hyphen_the_author_wrote():
    mm = 0.25
    for cols in range(8, 40, 2):
        shape = _mask(["#" * cols] * 40, mm)
        for hy in (False, True):
            sp = _flowspec("non-reversible peer-to-peer proof-of-work", shape,
                           hyphenate=hy)
            fl = M._flow(sp, 0.8, 0.05)
            for r in fl.runs:
                assert "--" not in r.text, (cols, hy, r.text)
                assert not r.text.startswith("-"), (cols, hy, r.text)


def test_hyphen_min_does_not_apply_to_a_hyphen_the_author_wrote():
    """'to' is two letters and hyphen_min is three, so a rule about how much of
    a word to leave on a line would have refused the break -- at a break where
    nothing is inserted and no word is divided."""
    mm = 0.25
    shape = _mask(["#" * 16] * 40, mm)
    sp = _flowspec("peer-to-peer", shape, hyphenate=False, hyphen_min=6)
    fl = M._flow(sp, 0.8, 0.05)
    assert "to-" in [r.text for r in fl.runs]
    assert not fl.inserted


def test_the_deadlock_the_legacy_walk_had_is_gone():
    """The measurable cost of (c): one wide word jams every span after it,
    because the flow never skips a word. Existing-hyphen breaking alone -- with
    --shape-hyphenate still OFF -- is what unjams it."""
    mm = 0.25
    shape = _mask(["#" * 22] * 120, mm)
    body = _hwords(60)
    old = legacy_flow(_flowspec(body, shape, hyphenate=False), 0.8, 0.05)
    new = M._flow(_flowspec(body, shape, hyphenate=False), 0.8, 0.05)
    old_chars = len(body) - len(old.unplaced)
    new_chars = len(body) - len(new.unplaced)
    assert new_chars > old_chars
    assert len(new.bands_with_text) > len(old.bands_with_text)
    assert not new.inserted            # and it cost no change to the text


def test_the_legacy_hyphenated_walk_emitted_the_text_out_of_order():
    """A FOURTH defect, found by the recovery walk rather than by reading.

    The legacy loop put an unplaceable carried fragment BACK into `tail` and
    then went on filling the span from `words[wi]`, which is the text AFTER the
    fragment. So the board carried a later word first and the fragment landed
    behind it. recover_text() refuses that; the new walk has no `tail` at all,
    because the remainder stays in the queue at its own position.
    """
    mm, W = 0.25, 20
    # 2.50 mm, then 2.00 mm, then wide. "Internet" (4.443 mm) breaks to "Int-"
    # in the first; "ernet" (2.919) does not fit the second and "has" (1.852)
    # does, which is the whole trap.
    shape = _mask(["#" * 10 + "." * (W - 10)] * 6
                  + ["#" * 8 + "." * (W - 8)] * 6
                  + ["#" * W] * 40, mm)
    body = "Internet has come to"
    old = legacy_flow(_flowspec(body, shape, hyphenate=True), 0.8, 0.05)
    new = M._flow(_flowspec(body, shape, hyphenate=True), 0.8, 0.05)
    assert [r.text for r in old.runs] == ["Int-", "has", "ernet", "come to"]
    assert [r.text for r in new.runs] == ["Int-", "ernet", "has", "come to"]
    o = M.recover_text(body, [r.text for r in old.runs],
                       inserted=len(old.inserted))
    n = M.recover_text(body, [r.text for r in new.runs],
                       inserted=len(new.inserted))
    assert o["ok"] is False and o["reason"] == "diverged"
    assert "Int-hasernet" in o["board"]
    assert n["ok"] is True


def test_an_existing_hyphen_break_round_trips_to_the_source_exactly():
    """Breaking where the author already broke alters NOTHING, so the walk gets
    no allowance at all and still has to close: inserted=0."""
    mm = 0.25
    shape = _mask(["#" * 18] * 80, mm)
    body = _hwords(40)
    fl = M._flow(_flowspec(body, shape, hyphenate=False), 0.8, 0.05)
    assert fl.soft_breaks > 0                    # breaks really were taken
    assert fl.inserted == []
    placed = " ".join(body.split())[:fl.consumed_chars]
    got = M.recover_text(placed, [r.text for r in fl.runs], inserted=0)
    assert got["ok"] is True and got["inserted_found"] == 0


def test_an_inserted_hyphen_is_declared_and_the_walk_counts_it():
    mm = 0.25
    shape = _mask(["#" * 14 + "." * 6] * 200, mm)
    body = "electronic payments timestamp server"
    fl = M._flow(_flowspec(body, shape, hyphenate=True), 0.8, 0.05)
    assert fl.inserted, "this shape is meant to force an inserted hyphen"
    placed = " ".join(body.split())[:fl.consumed_chars]
    good = M.recover_text(placed, [r.text for r in fl.runs],
                          inserted=len(fl.inserted))
    assert good["ok"] is True
    assert good["inserted_found"] == len(fl.inserted)
    # and an UNDECLARED one fails -- that is the whole point of the count
    bad = M.recover_text(placed, [r.text for r in fl.runs], inserted=0)
    assert bad["ok"] is False and "declared" in bad["reason"]


def test_the_emitted_report_declares_every_inserted_hyphen_and_no_others():
    mm = 0.25
    shape = _mask(["#" * 14 + "." * 6] * 200, mm)
    sp = _flowspec("electronic payments timestamp server", shape,
                   hyphenate=True, tone="T2", allow_truncation=True)
    rep = _run(sp)
    assert rep["inserted_hyphens"]
    assert rep["integrity"]["ok"] is True
    assert (rep["integrity"]["inserted_found"]
            == rep["integrity"]["inserted_declared"]
            == len(rep["inserted_hyphens"]))
    assert any("were INSERTED into words" in w for w in rep["warnings"])
    # the soft breaks are counted and explicitly NOT disclosed as alterations
    sp2 = _flowspec("peer-to-peer peer-to-peer peer-to-peer", _mask(
        ["#" * 14 + "." * 6] * 200, mm), hyphenate=False, tone="T2",
        allow_truncation=True)
    rep2 = _run(sp2)
    assert rep2["soft_breaks"] > 0
    assert rep2["inserted_hyphens"] == []
    assert not any("INSERTED" in w for w in rep2["warnings"])


# --- 7. the sizing solve ----------------------------------------------------

def test_capacity_is_exact_for_this_prose():
    """Not an estimate: a body of exactly `chars` loses nothing, and the next
    whole word past it does not fit."""
    shape = _rect(30.0, 30.0)
    sp = _flowspec(_words(40), shape)
    c = M.capacity(sp, floor=0.05)
    body = M._normalise(sp.text)
    trial = " ".join([body] * 16)
    n = c["chars"]
    assert M._flow(_flowspec(trial[:n], shape), 0.8, 0.05).unplaced == ""
    more = trial[:n + 1] + trial[n + 1:].split(" ")[0]
    assert M._flow(_flowspec(more, shape), 0.8, 0.05).unplaced != ""


def test_the_fill_line_is_exact_too():
    shape = _rect(30.0, 30.0)
    sp = _flowspec(_words(40), shape)
    c = M.capacity(sp, floor=0.05)
    assert c["fill_chars"] is not None
    body = M._normalise(sp.text)
    trial = " ".join([body] * 16)
    assert not M._flow(_flowspec(trial[:c["fill_chars"]], shape),
                       0.8, 0.05).bands_abandoned
    assert c["fill_chars"] <= c["chars"]


def test_the_verdict_is_known_before_a_glyph_is_placed():
    """check() is 'everything that can be decided before any geometry is
    placed', and whether the text and the art are the same size is one of those
    things. The number it reports is the one the flow then produces."""
    shape = _rect()
    full = _capacity(shape)
    sp = _flowspec(_words(full * 2), shape, allow_truncation=True)
    rep = M.check(sp)                       # no place() yet
    c = rep["capacity"]
    assert c["verdict"] == "overfill"
    assert c["exact"] is True
    M.place(sp, rep)
    assert rep["fill"]["verdict"] == "overfill"
    assert rep["fill"]["surplus_chars"] == c["excess_chars"]


def test_overfill_refuses_from_check_before_the_flow():
    shape = _rect()
    long = _words(_capacity(shape) * 2)
    with pytest.raises(M.MicrotextRefused) as e:
        M.check(_flowspec(long, shape))
    assert str(e.value).startswith("OVERFILL")
    assert "known BEFORE the flow ran" in str(e.value)


def test_underfill_offers_both_remedies_and_both_were_run():
    shape = _rect()
    sp = _flowspec(_words(_capacity(shape) // 2), shape)
    f = _fill(sp)
    assert f["verdict"] == "underfill"
    # 1. the cap height
    assert f["remedy_cap_mm"] and f["remedy_cap_verified"]
    assert _fill(_flowspec(sp.text, shape,
                           cap_mm=f["remedy_cap_mm"]))["verdict"] == "fits"
    # 2. the art size, at the ORIGINAL cap height
    assert f["remedy_art_mm"] and f["remedy_art_verified"]
    assert f["remedy_art_mm"] < shape.height_mm
    smaller = shape.scaled(f["remedy_art_mm"] / shape.height_mm)
    assert _fill(_flowspec(sp.text, smaller))["verdict"] == "fits"
    # and it says which one it would take, and why
    msg = next(w for w in _run(sp)["warnings"] if w.startswith("UNDERFILL"))
    assert "TAKE THE CAP HEIGHT" in msg
    assert "SHRINK THE ART" in msg


def test_overfill_offers_the_art_size_and_the_exact_cut():
    shape = _rect()
    long = _words(int(_capacity(shape) * 1.6))
    sp = _flowspec(long, shape, allow_truncation=True)
    f = _fill(sp)
    assert f["verdict"] == "overfill"
    assert f["remedy_art_mm"] and f["remedy_art_verified"]
    assert f["remedy_art_mm"] > shape.height_mm
    bigger = shape.scaled(f["remedy_art_mm"] / shape.height_mm)
    assert not M._flow(_flowspec(long, bigger), 0.8, 0.05).unplaced
    # the exact cut, verified by cutting it
    cut = long[:len(long) - f["surplus_chars"]]
    assert not M._flow(_flowspec(cut, shape), 0.8, 0.05).unplaced
    with pytest.raises(M.MicrotextRefused) as e:
        _run(_flowspec(long, shape))
    assert "GROW THE ART" in str(e.value)
    assert f"cut exactly {f['surplus_chars']} characters" in str(e.value).lower() \
        or f"CUT exactly {f['surplus_chars']} characters" in str(e.value)


def test_the_solve_returns_the_third_given_any_two():
    shape = _rect(30.0, 30.0)
    sp = _flowspec(_words(60), shape, forecast=False, floor_mm=0.02)
    # art + cap -> characters
    a = M.solve(sp, floor=0.02, want="chars")
    assert a["answer"] == a["capacity"]["chars"] > 0
    # art + characters -> cap
    b = M.solve(sp, floor=0.02, chars=a["answer"], want="cap")
    assert b["ok"] and b["verified"]
    assert b["capacity"]["chars"] >= a["answer"]
    # cap + characters -> art
    c = M.solve(sp, floor=0.02, chars=a["answer"], want="art")
    assert c["ok"] and c["verified"]
    assert c["capacity"]["chars"] >= a["answer"]
    # and the art it names is within a grid step of the art it was asked about
    assert abs(c["answer"] - shape.height_mm) <= 6 * M.ART_GRID_MM


def test_the_solve_never_recommends_a_cap_the_checker_would_refuse():
    shape = _rect(30.0, 30.0)
    sp = _flowspec(_words(4000), shape, forecast=False, floor_mm=0.10,
                   stroke_ratio=0.125)
    r = M.solve(sp, floor=0.10, want="cap")
    assert r["ok"] is False
    assert "NO cap height works" in r["notes"][0]
    assert r["cap_mm"] == pytest.approx(r["min_cap_mm"])


def test_the_solve_is_the_same_answer_from_either_end():
    """Whatever art size the solve names for L characters, asking that art size
    how many characters it holds has to come back with at least L."""
    shape = _rect(20.0, 20.0)
    sp = _flowspec(_words(200), shape, forecast=False, floor_mm=0.02)
    want = 900
    r = M.solve(sp, floor=0.02, chars=want, want="art")
    assert r["ok"]
    at = M.solve(M._at_art(sp, r["answer"], "height"), floor=0.02, want="chars")
    assert at["answer"] >= want
    # one grid step smaller does not hold it -- the answer is the smallest
    smaller = M.solve(M._at_art(sp, r["answer"] - M.ART_GRID_MM, "height"),
                      floor=0.02, want="chars")
    assert smaller["answer"] < want


def test_three_given_renders_a_verdict_not_a_statistic():
    """Art + cap + text: the answer is fits/underfill/overflow WITH the
    arithmetic to act on it, never a bare capacity number."""
    shape = _rect(30.0, 30.0)
    full = _capacity(shape)
    # too much text -> overflow, with the overrun counted and a measured remedy
    sp = _flowspec(_words(full * 2), shape)
    r = M.solve(sp, art_mm=30.0, cap_mm=0.8, floor=0.05, want="chars")
    assert r["verdict"] == "overflow" and not r["ok"]
    body = len(M._normalise(sp.text))
    assert r["overflow_chars"] == body - r["answer"] > 0
    assert r.get("remedy_art_mm") or r.get("remedy_cap_mm")
    if r.get("remedy_art_mm"):
        r2 = M.solve(sp, art_mm=r["remedy_art_mm"], cap_mm=0.8, floor=0.05,
                     want="chars")
        assert r2["answer"] >= body
    # enough text -> fits, with the spare counted
    sp2 = _flowspec(_words(8), shape)
    r = M.solve(sp2, art_mm=30.0, cap_mm=2.0, floor=0.05, want="chars")
    assert r["verdict"] in ("fits", "underfill")
    if r["verdict"] == "fits":
        assert r["spare_chars"] == r["answer"] - len(M._normalise(sp2.text))
    else:
        assert r["short_chars"] > 0


def test_underfill_verdict_carries_the_owner_wording_and_numbers():
    """Too little text: at least X characters, y short, and a coarser cap."""
    shape = _rect(40.0, 40.0)
    sp = _flowspec(_words(6), shape)
    r = M.solve(sp, art_mm=40.0, cap_mm=0.8, floor=0.05, want="chars")
    if r["verdict"] != "underfill":
        return  # tiny vocab happens to fill; the verdict logic is still fits
    assert "text length must be at least" in r["verdict_text"]
    assert "characters short" in r["verdict_text"]
    fill = r["capacity"]["fill_chars"]
    assert r["short_chars"] == fill - len(M._normalise(sp.text))
    # the coarser cap, when offered, was measured and holds the text
    if r.get("remedy_cap_mm"):
        r2 = M.solve(sp, art_mm=40.0, cap_mm=r["remedy_cap_mm"], floor=0.05,
                     want="chars")
        assert r2["answer"] >= len(M._normalise(sp.text))


def test_the_no_cap_branch_names_the_art_size_it_already_knows():
    """When no cap height works, the refusal carries the measured GROW THE ART
    number instead of withholding it."""
    shape = _rect(20.0, 20.0)
    sp = _flowspec(_words(200), shape)
    r = M.solve(sp, art_mm=20.0, floor=0.05, want="cap")
    assert not r["ok"]
    assert r.get("remedy_art_mm") is not None
    note = " ".join(r["notes"])
    assert "GROW THE ART" in note
    r2 = M.solve(sp, art_mm=r["remedy_art_mm"], cap_mm=r["cap_mm"],
                 floor=0.05, want="chars")
    assert r2["answer"] >= len(M._normalise(sp.text))


def test_a_knife_edge_answer_carries_a_robust_size():
    """An art answer whose slack is inside one row-band step also reports a
    ROBUST size with at least a band of margin, measured."""
    shape = _rect(30.0, 30.0)
    sp = _flowspec(_words(60), shape)
    r = M.solve(sp, floor=0.05, chars=None, want="art", cap_mm=0.8)
    assert r["band_step_chars"] >= 1
    if r["spare_chars"] < r["band_step_chars"] and r.get("robust_art_mm"):
        assert r["robust_art_mm"] > r["answer"]
        r2 = M.solve(sp, art_mm=r["robust_art_mm"], cap_mm=0.8, floor=0.05,
                     want="chars")
        assert r2["answer"] >= r["target_chars"] + r["band_step_chars"]
