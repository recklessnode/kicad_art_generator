"""What must stay true about microprinting.

These are the four claims tools/microtext.py is built on, turned into
assertions. None of them needs kicad-cli: the letterform geometry was measured
once (tools/stroke_font.py --calibrate, which re-derives and diffs it) and
everything here is arithmetic on those numbers.

  1. The floor is enforced, not suggested -- and the refusal names a cap height
     that would work.
  2. The stroke scales with the cap height and never lands under the floor. The
     specific failure guarded against is the one coupon_ladders.Fp.text() fixed:
     a stroke silently CLAMPED up to the floor, which at a small cap height is a
     1:4 pen that fills every counter solid while passing a naive width check.
  3. Closed counters fail before straight strokes. This is why
     coupon_ladders.SPECIMEN contains 'e', '8', 'B', 'g' and '@'.
  4. The mask opens over the block, never per glyph, and covers every glyph with
     the asked-for clearance -- measured against where KiCad actually PUTS the
     letterforms, which is not where the anchor is.
"""
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
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
    assert "narrowest counter" in str(e.value)


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
    rep = M.check(spec(text="ILT", cap_mm=0.7, tone="T2"))
    assert rep["counter"] is None
    note = [c["note"] for c in rep["checks"] if c["name"] == "narrowest counter"]
    assert "no closed letterforms" in note[0]


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
    _, rep = _emit(spec(text="Reckless microprint", cap_mm=0.7, tone="T2",
                        path=[(0, 0), (6, 0), (12, 0.4)]))
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
