"""Every fp_text this repo emits must have KiCad's "Keep upright" OFF.

The property is INVERTED in the file format: KiCad writes `(unlocked yes)` to
mean keep_upright FALSE, and a fp_text with NO such token loads with "Keep
upright" ON. That is exactly how every emitted part shipped with it on -- the
emitters simply never wrote the token, and nothing failed, because at rotation
0 and 90 keep-upright text draws where it should. At 180 and 270 it does not:
the glyph POSITIONS rotate with the footprint and the glyph ORIENTATIONS snap
back upright. Measured with pcbnew 10.0 on art_btc_whitepaper_b_72mm (1468
fp_text, one per glyph):

    keep_upright=True   rot=180 -> every glyph draws at 0   SCRAMBLED
    keep_upright=True   rot=270 -> every glyph draws at 90  SCRAMBLED
    keep_upright=False  rot=anything -> glyphs follow the body

For one-fp_text-per-glyph microtext that is not "slightly off", it is
overlapping soup.

These tests assert on the ACTUAL emitted artifact -- the s-expression that a
fp_text carries -- via verify_art's own parser, not on whether some writer
function was called. And because this repo has a history of checks that cannot
fail what they exist to catch, test_the_checker_itself_flags_the_old_form
feeds the checker the pre-fix output verbatim and requires it to FAIL that.

pcbnew round-trip ground truth (KiCad 10.0, Windows, not available under
pytest's WSL venv, so recorded here rather than executed here):
  - modern (footprint ...) form: `(unlocked yes)` child node between (at) and
    (layer) reads back IsKeepUpright() == False; absent reads True.
  - legacy (module ...) form (src/kicad_art_generator/cli.py): a bare
    `unlocked` token inside (at ...) reads back False; absent reads True.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import microtext as M            # noqa: E402
import stroke_font as SF         # noqa: E402
from coupon_ladders import Fp, SPECIMEN    # noqa: E402
from emit_art import ArtFp       # noqa: E402
from verify_art import parse_sexpr, kids, kid   # noqa: E402

from kicad_art_generator.cli import make_fp_text   # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]


# --- the checker ------------------------------------------------------------

def fp_text_nodes(sexpr_text):
    # parse_sexpr returns the LIST of top-level nodes; a .kicad_mod has one.
    tops = parse_sexpr(sexpr_text)
    assert len(tops) == 1 and tops[0][0] == "footprint"
    return kids(tops[0], "fp_text")


def keep_upright_off(node):
    """True iff this fp_text node will load with "Keep upright" OFF.

    Mirrors KiCad's parser: the modern spelling is an `(unlocked yes)` child
    node; the legacy (module ...) spelling is a bare `unlocked` token inside
    the (at ...) node. Either reads back IsKeepUpright() == False. NO token
    in either place means the property is ON -- the failure mode.
    """
    unl = kid(node, "unlocked")
    if unl is not None and len(unl) > 1 and unl[1] == "yes":
        return True
    at = kid(node, "at")
    if at is not None and "unlocked" in at[1:]:
        return True
    return False


def assert_all_off(sexpr_text, expect_at_least=1):
    nodes = fp_text_nodes(sexpr_text)
    assert len(nodes) >= expect_at_least, (
        f"expected at least {expect_at_least} fp_text, found {len(nodes)}: "
        f"a keep-upright check over zero texts checks nothing")
    on = [n for n in nodes if not keep_upright_off(n)]
    assert not on, (
        f"{len(on)} of {len(nodes)} fp_text will load with Keep upright ON "
        f"(no unlocked token); at 180/270 degree footprint rotation their "
        f"glyphs will not follow the body")


# --- the checker itself must be able to fail --------------------------------

def test_the_checker_itself_flags_the_old_form():
    """The pre-fix emitter output, verbatim, must FAIL the check.

    This is the twelfth-useless-check guard: if keep_upright_off() ever goes
    soft (parses wrong, matches the wrong node, defaults to True), this test
    goes red before any regression does.
    """
    old = ('(footprint "old"\n\t(version 20241229)\n\t(generator "emit_art")\n'
           '\t(layer "F.Cu")\n'
           '\t(fp_text user "A" (at 11.1280 0.4851) (layer "F.Cu")\n'
           '\t\t(effects (font (size 0.8000 0.8000) (thickness 0.1000)) '
           '(justify left)))\n)\n')
    nodes = fp_text_nodes(old)
    assert len(nodes) == 1
    assert not keep_upright_off(nodes[0])
    with pytest.raises(AssertionError):
        assert_all_off(old)


def test_the_checker_is_not_fooled_by_unlocked_no():
    """(unlocked no) is keep_upright ON and must not pass."""
    txt = ('(footprint "no"\n'
           '\t(fp_text user "A" (at 0 0) (unlocked no) (layer "F.Cu")\n'
           '\t\t(effects (font (size 1 1) (thickness 0.15))))\n)\n')
    assert not keep_upright_off(fp_text_nodes(txt)[0])


# --- every writer in the tree ----------------------------------------------

def test_coupon_ladders_fp_text_is_keep_upright_off():
    fp = Fp("t")
    fp.text("W0", 0.0, 0.0, 2.0, "F.SilkS")
    assert_all_off(fp.dumps())


def test_emit_art_text_rot_is_keep_upright_off_at_all_angles():
    fp = ArtFp("t")
    for i, ang in enumerate((0.0, 37.5, 180.0, 270.0)):
        fp.text_rot("A", float(i), 0.0, 2.0, "F.SilkS", angle=ang)
    assert_all_off(fp.dumps(), expect_at_least=4)


def test_microtext_emit_end_to_end_is_keep_upright_off():
    """The real path the shipped parts came through: microtext -> ArtFp."""
    fp = ArtFp("t", tags="recklessart microtext")
    rep = M.emit(fp, M.MicrotextSpec(text=SPECIMEN, cap_mm=0.7, tone="T2"))
    assert rep["fp_text"] > 0
    assert_all_off(fp.dumps(), expect_at_least=rep["fp_text"])


def test_stroke_font_calibration_probe_is_keep_upright_off():
    assert_all_off(SF._cal_fp("cal", "HH"))


def test_legacy_cli_fp_text_is_keep_upright_off():
    txt = f'(footprint "x"\n\t{make_fp_text("reference", "x", -2.0)}\n)\n'
    assert_all_off(txt)


# --- the shipped artifact ---------------------------------------------------

def test_committed_library_microtext_is_keep_upright_off():
    """The checked-in whitepaper part, not just the code that would remake it.

    This is the file that was measured scrambled at 180/270; once regenerated
    it must never lose the token again.
    """
    p = REPO / "library" / "RecklessArt.pretty" / "art_btc_whitepaper_b.kicad_mod"
    assert_all_off(p.read_text(encoding="utf-8"), expect_at_least=1000)
