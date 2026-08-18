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
