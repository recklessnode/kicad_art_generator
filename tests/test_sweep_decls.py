"""Sweep declarations: what may be exempted, and everything that may not.

WHY THIS FILE IS MOSTLY ATTACKS
-------------------------------
An exemption mechanism is literally a way to make checks stop failing, and this
project has already found eight checks that could not fail what they existed to
catch. So the tests that matter here are not the ones showing a declared rung
passing -- that is one test -- but the ones showing that everything else still
fails. Each attack test names the thing it is defending against.

The one test that is NOT an attack and still earns its place is
test_an_exempt_feature_is_removed_from_the_narrowest_slot: the mechanism makes
check_min_feature SEE MORE than it did, because that check keeps one value per
layer and the ladder's 0.0500 mm rung was sitting in the slot, hiding every
other sub-floor F.Cu feature on the board behind it.

Every board below is built here from constants. Nothing reads, embeds or
reproduces any board or artwork from the product repo.
"""
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ink_measure as IM                                      # noqa: E402
import sweep_decls as SD                                      # noqa: E402
import verify_art as V                                        # noqa: E402

from test_board_verify import (                               # noqa: E402
    LAYER_TABLE, EDGE, cfg, poly, text_of, needs_shapely,
)

REF = "kicad_art_generator#6"


# --------------------------------------------------------------------------
# rigging: a board carrying ONE footprint, because a declaration is attributed
# to the footprint that made it and there is no other way to exercise that.
# --------------------------------------------------------------------------

# A wide silk caption, so the footprint's own bounding box is set by its
# annotation rather than by the ladder -- which is the real shape of
# cal_minfeature_copper, whose 82 mm caption dwarfs its 6 mm of copper, and the
# reason a box clipped to the footprint can still be a land-grab.
CAPTION = ('\t\t(fp_line (start 0 -3) (end 38 -3) '
           '(stroke (width 0.2) (type solid)) (layer "F.SilkS"))')


def fp_board(tmp_path, tags, body, name="b", at=(0, 0), extra=""):
    body = CAPTION + "\n" + body
    p = tmp_path / f"{name}.kicad_pcb"
    p.write_text(
        '(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n'
        '\t(generator_version "10.0")\n\t(general (thickness 1.6))\n'
        '\t(paper "A4")\n' + LAYER_TABLE
        + "\t(setup (pad_to_mask_clearance 0))\n" + EDGE
        + f'\t(footprint "CouponCal:cal_test"\n'
        f'\t\t(layer "F.Cu")\n\t\t(at {at[0]} {at[1]})\n'
        f'\t\t(descr "Art calibration ladder")\n'
        f'\t\t(tags "{tags}")\n'
        + body + "\n\t)\n" + extra + "\n)\n", encoding="utf-8")
    return p


def rung(x0, x1, y, w, layer="F.Cu"):
    return (f'\t\t(fp_line (start {x0} {y}) (end {x1} {y}) '
            f'(stroke (width {w}) (type solid)) (layer "{layer}"))')


def tok(quantity="width", layer="F.Cu", lo=0.049, hi=0.301,
        box=(4.9, -0.2, 11.1, 2.2), block="rungs", ref=REF):
    return SD.token_for(quantity, layer, lo, hi, *box, block, ref)


def both_tok(**kw):
    """A ladder claims `width` and `vanish` separately, because they are
    separate claims. Most tests here need both to reach a clean run."""
    return f"{tok(**kw)} {tok(quantity='vanish', **kw)}"


def run(path, c=None, no_sweep=False):
    c = c or cfg()
    c.no_sweep = no_sweep
    c.sweeps = None
    verdict, checks = V.verify_board(path, c)
    return verdict, {ck.key: ck for ck in checks}


# A ladder of two sub-floor rungs inside the declared box, drawn against a
# 0.10 mm copper floor. 0.050 and 0.075 are the bottom two of FEATURE_STEPS.
# 2 mm apart, so the ladder does not accidentally create a sub-floor GAP and
# test something other than what each test says it tests.
LADDER = "\n".join([rung(5, 11, 0.0, 0.050), rung(5, 11, 2.0, 0.075)])


# ==========================================================================
# 1. What the mechanism is FOR
# ==========================================================================

def test_a_declared_subfloor_rung_passes_and_the_report_says_so(tmp_path):
    b = fp_board(tmp_path, f"recklessart calibration {both_tok()}", LADDER)
    _verdict, ck = run(b)
    # Nothing that MEASURED anything fails. (The file's overall verdict is WARN
    # here only because the rig has no sibling .kicad_pro and no kicad-cli, and
    # this harness reports both as SKIP rather than as a pass.)
    assert [c.level for c in (ck["min-feature"], ck["clearance"],
                              ck["ink-floor"])] == [V.PASS] * 3
    mf = text_of(ck["min-feature"])
    assert "BELOW FLOOR" not in mf
    # Visible, attributed and counted -- not silent.
    assert "2 exempt by declaration" in ck["min-feature"].headline
    assert "EXEMPT by declaration [rungs]" in mf
    assert "0.0500..0.0750 mm" in mf
    ex = text_of(ck["exempt"])
    assert "[USED]" in ex
    assert "2 exempt, observed 0.050000..0.075000" in ex
    assert REF in ex
    # The VERBATIM token prints, so a hand-widened band shows up in a report
    # diff and not only in a file diff.
    assert tok() in ex


def test_the_exempt_check_is_present_and_counted_on_the_check(tmp_path):
    b = fp_board(tmp_path, f"recklessart calibration {both_tok()}", LADDER)
    _v, ck = run(b)
    assert ck["exempt"].stale == 0
    assert len(ck["exempt"].exemptions) == 2
    e = [x for x in ck["exempt"].exemptions if x["quantity"] == "width"][0]
    assert (e["block"], e["quantity"], e["layer"], e["state"]) == (
        "rungs", "width", "F.Cu", "USED")
    assert e["matched"] == 2 and e["observed_min"] == pytest.approx(0.05)


# ==========================================================================
# 2. What it must never do
# ==========================================================================

def test_an_undeclared_subfloor_feature_still_fails(tmp_path):
    """The rung ladder is declared; a second one 20 mm away is not."""
    body = LADDER + "\n" + rung(25, 31, 0.0, 0.060)
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", body)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert "BELOW FLOOR: F.Cu 0.0600" in text_of(ck["min-feature"])


def test_an_exempt_feature_is_removed_from_the_narrowest_slot(tmp_path):
    """THE MASKING FIX, and the strongest argument for building this at all.

    check_min_feature keeps ONE value per layer. With the 0.0500 mm rung in
    that slot, a 0.0600 mm defect elsewhere on F.Cu is invisible -- it is not
    the narrowest, so it is never reported. Exempt measurements come out of the
    slot, which makes this case fail only because the mechanism exists.
    """
    body = LADDER + "\n" + rung(25, 31, 0.0, 0.060)

    # Without the declaration the ladder owns the slot and hides the defect.
    b0 = fp_board(tmp_path, "recklessart calibration", body, name="no_decl")
    _v0, ck0 = run(b0)
    t0 = text_of(ck0["min-feature"])
    assert "BELOW FLOOR: F.Cu 0.0500" in t0
    assert "0.0600" not in t0          # hidden behind the ladder

    # With it, the reported minimum is the narrowest NON-EXEMPT feature.
    b1 = fp_board(tmp_path, f"recklessart calibration {tok()}", body,
                  name="decl")
    _v1, ck1 = run(b1)
    t1 = text_of(ck1["min-feature"])
    assert "BELOW FLOOR: F.Cu 0.0600" in t1
    assert "BELOW FLOOR: F.Cu 0.0500" not in t1


def test_out_of_band_is_a_failure_attributed_to_the_declaration(tmp_path):
    """T5. A rung finer than the declaration's own lo.

    Reported as OUT OF DECLARED BAND and blamed on the block, not as an
    ordinary floor failure: the part promised a range and broke its own
    promise, which is worse than never promising.
    """
    body = LADDER + "\n" + rung(5, 11, 0.15, 0.001)
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", body)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    ex = text_of(ck["exempt"])
    assert "OUT OF DECLARED BAND" in ex
    assert "rungs" in ex and "0.001000 mm" in ex
    assert ck["exempt"].level == V.FAIL


def test_a_declaration_cannot_reach_another_layer(tmp_path):
    """The beta coupon in one test: the SAME footprint carries a deliberate
    sub-floor copper sweep and an accidental sub-floor silk feature."""
    body = LADDER + "\n" + rung(5, 11, 0.05, 0.100, layer="F.SilkS")
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", body)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert "BELOW FLOOR: F.SilkS 0.1000" in text_of(ck["min-feature"])


def test_a_declaration_cannot_reach_another_quantity(tmp_path):
    """A width declaration does not exempt a gap, and vice versa."""
    two = "\n".join([rung(5, 11, 0.0, 0.05), rung(5, 11, 0.06, 0.05)])
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", two)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert "GAP BELOW FLOOR" in text_of(ck["clearance"])


def test_a_declaration_cannot_silence_a_different_check(tmp_path):
    """T4. Only min-feature, clearance and ink-floor are handed the table."""
    bow = poly([(20, 20), (24, 20), (20, 24), (24, 24)], layer="F.Cu")
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER,
                 extra=bow)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert ck["self-isect"].level == V.FAIL


# ==========================================================================
# 3. Attacks on the declaration itself
# ==========================================================================

@pytest.mark.parametrize("bad", [
    "sweep:width:F.Cu:0.000..99:4.9,-0.2,11.1,0.2:rungs:x",   # T1 blanket
    "sweep:width:F.Cu:0.005..0.3:4.9,-0.2,11.1,0.2:rungs:x",  # under the hard lo
    "sweep:area:F.Cu:0.05..0.3:4.9,-0.2,11.1,0.2:rungs:x",    # not in the enum
    "sweep:width:*.Cu:0.05..0.3:4.9,-0.2,11.1,0.2:rungs:x",   # wildcard layer
    "sweep:width:F.Cu:0.3..0.05:4.9,-0.2,11.1,0.2:rungs:x",   # band inverted
    "sweep:width:F.Cu:0.05..0.3:11.1,-0.2,4.9,0.2:rungs:x",   # box inverted
    "sweep:width:F.Cu:0.05..0.3:4.9,-0.2,11.1,0.2:rungs:",    # no ref
    "sweep:width:F.Cu:0.05..0.3:4.9,-0.2,11.1:rungs:x",       # short box
    "sweep:width:F.Cu:0.05..0.3:4.9,-0.2,11.1,0.2:rungs",     # too few fields
])
def test_a_malformed_declaration_is_refused_not_ignored(bad):
    with pytest.raises(SD.SweepError):
        SD.parse_token(bad, V.KNOWN_LAYERS)


def test_a_malformed_declaration_fails_the_whole_file(tmp_path):
    b = fp_board(tmp_path, "recklessart calibration "
                           "sweep:width:F.Cu:0.000..99:4.9,-0.2,11.1,0.2:r:x",
                 LADDER)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert "unusable sweep declaration" in ck["exempt"].headline


def test_a_box_drawn_round_the_whole_footprint_fails_tightness(tmp_path):
    """T2. The land-grab. The box is clipped to the footprint first, so what
    is left to catch is a box far larger than the geometry it names."""
    big = both_tok(box=(-1.0, -20.0, 40.0, 20.0))
    b = fp_board(tmp_path, f"recklessart calibration {big}", LADDER)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    ex = text_of(ck["exempt"])
    assert "[UNUSABLE]" in ex and "tightness" in ex
    # and the findings it tried to claim are still findings
    assert "BELOW FLOOR: F.Cu 0.0500" in text_of(ck["min-feature"])


def test_a_box_over_nothing_is_void(tmp_path):
    """An empty box is a typo or a land-grab, and in either case it decays."""
    empty = tok(box=(20.0, -0.2, 26.2, 2.2))
    b = fp_board(tmp_path, f"recklessart calibration {empty}", LADDER)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert "[VOID]" in text_of(ck["exempt"])
    assert "BELOW FLOOR: F.Cu 0.0500" in text_of(ck["min-feature"])


def test_two_declarations_over_one_place_are_a_contradiction(tmp_path):
    """T9. Exactly one declaration may match a finding."""
    a = tok(box=(4.9, -0.2, 11.1, 2.2))
    c = tok(box=(4.5, -0.3, 11.5, 2.3), block="other")
    b = fp_board(tmp_path, f"recklessart calibration {a} {c}", LADDER)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert "unusable sweep declaration" in ck["exempt"].headline


def test_a_declaration_that_exempts_nothing_goes_stale(tmp_path):
    """An unnecessary suppression is a false statement about the part.

    WARN rather than a note, so --strict reaps it in CI without a new flag.
    """
    clean = "\n".join([rung(5, 11, 0.0, 0.5), rung(5, 11, 2.0, 0.5)])
    d = tok(box=(4.7, -0.3, 11.3, 2.3))
    b = fp_board(tmp_path, f"recklessart calibration {d}", clean)
    _v, ck = run(b)
    ex = text_of(ck["exempt"])
    assert "[STALE]" in ex and "exempted nothing" in ex
    assert ck["exempt"].level == V.WARN
    assert ck["exempt"].stale == 1


def test_a_footprint_cannot_exempt_anything_outside_itself(tmp_path):
    """The box is CLIPPED to the declaring footprint's own geometry."""
    reach = tok(box=(4.9, -0.2, 60.0, 2.2))
    b = fp_board(tmp_path, f"recklessart calibration {reach}", LADDER)
    _v, ck = run(b)
    assert "clipped to the declaring footprint's own geometry" in \
        text_of(ck["exempt"])


# ==========================================================================
# 4. Ink witnesses, which have coordinates and no item identity
# ==========================================================================

@needs_shapely
def test_a_declared_vanishing_component_is_exempt_and_a_stray_one_is_not(tmp_path):
    """`vanish` is a SEPARATE claim from `width` on purpose: artwork silently
    deleted at the floor has cost this project three characters' limbs."""
    body = LADDER + "\n" + rung(25, 31, 0.0, 0.060)
    both = f"{tok()} {tok(quantity='vanish')}"
    b = fp_board(tmp_path, f"recklessart calibration {both}", body)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    ink = text_of(ck["ink-floor"])
    assert "vanish witness(es) EXEMPT by declaration [rungs]" in ink
    # the undeclared 0.060 mm rung still vanishes, and still says so
    assert "FINER THAN THE PROCESS" in ink


@needs_shapely
def test_declaring_width_does_not_exempt_vanishing(tmp_path):
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER)
    verdict, ck = run(b)
    assert verdict == V.FAIL
    assert "FINER THAN THE PROCESS" in text_of(ck["ink-floor"])


@needs_shapely
def test_foreign_ink_in_the_box_voids_the_match(tmp_path):
    """T10. One foreign contributor at the witness and the finding stands.

    A neck between the ladder and something else is a real spacing question,
    and it is not the ladder's to claim.
    """
    intruder = poly([(5, -0.02), (11, -0.02), (11, 0.02), (5, 0.02)],
                    layer="F.Cu")
    both = f"{tok()} {tok(quantity='vanish')}"
    b = fp_board(tmp_path, f"recklessart calibration {both}", LADDER,
                 extra=intruder)
    _v, ck = run(b)
    ex = text_of(ck["exempt"])
    assert "was NOT exempted" in ex and "gr_poly" in ex


# ==========================================================================
# 5. Refusing to honour, and the summary
# ==========================================================================

def test_no_sweep_lists_every_declaration_and_honours_none(tmp_path):
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER)
    verdict, ck = run(b, no_sweep=True)
    assert verdict == V.FAIL
    ex = text_of(ck["exempt"])
    assert "NOT HONOURED" in ex
    assert tok() in ex               # hiding is not available
    assert "BELOW FLOOR: F.Cu 0.0500" in text_of(ck["min-feature"])


def _main(capsys, *args):
    rc = V.main([*args, "--no-render"])
    return rc, capsys.readouterr().out


def test_the_summary_line_carries_the_count_even_at_zero(tmp_path, capsys):
    """A run where judgement was suspended must not be byte-similar to one
    where it was not, so the count prints at zero too and a CI diff on this
    line catches a new exemption appearing."""
    clean = fp_board(tmp_path, "recklessart calibration",
                     rung(5, 11, 0.0, 0.5), name="clean")
    _rc, out = _main(capsys, str(clean))
    assert "(0 exempt, 0 stale)" in out

    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER)
    _rc, out = _main(capsys, str(b))
    assert "(2 exempt, 0 stale)" in out
    assert "(2 exempt)" in out          # and on the per-file verdict line too


def test_the_summary_says_when_declarations_were_not_honoured(tmp_path, capsys):
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER)
    _rc, out = _main(capsys, str(b), "--no-sweep")
    assert "NOT HONOURED --no-sweep" in out


def test_json_carries_the_exemptions(tmp_path, capsys):
    import json
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER)
    _rc, out = _main(capsys, str(b), "--json")
    d = json.loads(out)
    assert d["summary"]["exempt"] == 2 and d["summary"]["stale"] == 0
    assert d["files"][0]["exemptions"][0]["token"] == tok()


# ==========================================================================
# 6. The marker has to survive the tools that touch the file
# ==========================================================================

def test_a_declaration_written_in_a_library_reaches_a_placed_footprint(tmp_path):
    """Placement is the path the declaration actually travels: the emitter
    writes it into the .kicad_mod, build_coupons places the footprint, and the
    board copy carries the tags node. This pins the BOARD-side read, which did
    not exist -- tags and descr were in FP_INERT_HEADS and load_board() built
    its Footprint with tags="", so no footprint metadata reached any check on a
    .kicad_pcb at all."""
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER,
                 at=(30, 12))
    fp = V.load_board(b)
    assert len(fp.instances) == 1
    inst = fp.instances[0]
    assert tok() in inst.tags
    assert inst.descr == "Art calibration ladder"
    # and the box travelled with the footprint into board coordinates
    t = V.SweepTable(fp)
    d = t.decls[0]
    assert d.box.extents == pytest.approx((4.9, -0.2, 11.1, 2.2), abs=1e-9)
    x0, y0, x1, _y1 = d.active_box.extents
    assert (x0, y0, x1) == pytest.approx((34.9, 11.8, 41.1), abs=1e-6)
    # and the rungs it names are inside it in BOARD coordinates
    rungs = [it for it in fp.items
             if it.kind == "fp_line" and "F.Cu" in it.layers]
    assert len(rungs) == 2
    assert all(d.active_box.contains_bbox(it.bbox()) for it in rungs)


def test_every_item_knows_which_footprint_it_came_from(tmp_path):
    b = fp_board(tmp_path, f"recklessart calibration {tok()}", LADDER,
                 extra=poly([(20, 20), (24, 20), (24, 24)], layer="F.Cu"))
    fp = V.load_board(b)
    owners = {it.owner for it in fp.items if "F.Cu" in it.layers}
    assert owners == {0, -1}          # 0 = the footprint, -1 = board graphics


def _kicad_cli():
    try:
        c = V.find_kicad_cli(None)
    except Exception:                                   # pragma: no cover
        return None
    return c.path if c.path and c.major >= V.MIN_KICAD_MAJOR else None


@pytest.mark.skipif(_kicad_cli() is None, reason="no usable kicad-cli")
def test_the_declaration_survives_a_kicad_round_trip(tmp_path):
    """`fp upgrade` rewrites the file and renumbers every uuid. The token has
    to come back byte-identical, because it is the only durable place to put
    this -- three separate mechanisms renumber uuids and no per-item field
    survives at all."""
    cli = _kicad_cli()
    lib = tmp_path / "T.pretty"
    lib.mkdir()
    src = (f'(footprint "cal_test"\n\t(version 20241229)\n'
           f'\t(generator "coupon_ladders")\n\t(layer "F.Cu")\n'
           f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
           f'\t(descr "Art calibration ladder - see {REF}")\n'
           f'\t(tags "recklessart calibration {tok()}")\n'
           f'\t(fp_line (start 5 0) (end 11 0) (stroke (width 0.05) '
           f'(type solid)) (layer "F.Cu") (uuid "c0up0n00-0000-0000-0000-'
           f'000000000001"))\n)\n')
    (lib / "cal_test.kicad_mod").write_text(src, encoding="utf-8")
    r = subprocess.run([cli, "fp", "upgrade", V.host_path(lib, cli)],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    after = (lib / "cal_test.kicad_mod").read_text(encoding="utf-8")
    assert tok() in after
    fp = V.load_footprint(lib / "cal_test.kicad_mod")
    d = SD.from_tags(fp.tags, V.KNOWN_LAYERS)
    assert len(d) == 1 and d[0].block == "rungs" and d[0].ref == REF


# ==========================================================================
# 7. The emitter cannot draw deliberate sub-floor geometry it never declared
# ==========================================================================

def test_the_emitter_refuses_an_undeclared_deliberate_breach(tmp_path):
    """T7, the loop closure. allow_below_floor=True is the emitter saying
    'on purpose'; without a matching declaration that statement never reaches
    the verifier, and the two halves are allowed to drift."""
    import coupon_ladders as CL
    fp = CL.Fp("cal_stray")
    fp.line(0, 0, 4, 0, 0.05, "F.Cu", allow_below_floor=True)
    with pytest.raises(CL.UndeclaredSweep):
        CL.check_declarations(fp)
    fp.declare_sweep("width", "F.Cu", 0.049, 0.301,
                     (-0.1, -0.1, 4.1, 0.1), "stray")
    assert CL.check_declarations(fp) == []


def test_the_emitter_band_comes_from_the_design_constants(tmp_path):
    """The band tracks FEATURE_STEPS, so it cannot be a description of
    whatever happened to be drawn -- move the bottom rung and the declaration
    moves with it, and a rung at 0.001 mm takes the band under the mechanism's
    hard 0.010 mm floor and is refused outright."""
    import coupon_ladders as CL
    fp = CL.Fp("cal_x")
    CL.isolated_features(fp, 0, 0, "copper")
    d = {x.quantity: x for x in SD.from_tags(fp.tag_string())}
    assert d["width"].lo == pytest.approx(min(CL.FEATURE_STEPS)
                                          - CL.SWEEP_BAND_SLACK)
    assert d["width"].hi == pytest.approx(max(CL.FEATURE_STEPS)
                                          + CL.SWEEP_BAND_SLACK)
    old = CL.FEATURE_STEPS[:]
    try:
        CL.FEATURE_STEPS[0] = 0.001
        with pytest.raises(SD.SweepError):
            CL.isolated_features(CL.Fp("cal_y"), 0, 0, "copper")
    finally:
        CL.FEATURE_STEPS[:] = old


def test_the_emitter_refuses_a_label_whose_own_gaps_close(tmp_path):
    """The y = -24.1 defect, as a unit test. 'T1_silk' at a 0.9 mm cap has a
    0.021 mm inter-glyph gap against a 0.150 mm floor; the underscore pairs in
    'T3_fr4' overlap outright."""
    import coupon_ladders as CL
    fp = CL.Fp("cal_label")
    with pytest.raises(CL.CapTooSmall):
        fp.text("T1_silk", 0, 0, 0.9, "F.SilkS", thickness=0.15)
    # the shipped form clears it
    cap, _b = CL.solved_cap("T1 silk", "F.SilkS", CL.LABEL_PEN,
                            minimum=CL.LABEL_H)
    fp.text("T1 silk", 0, 0, cap, "F.SilkS", thickness=CL.LABEL_PEN)


# ==========================================================================
# 8. The two measurement fixes this work depended on
# ==========================================================================

@needs_shapely
def test_a_stroke_exactly_at_the_floor_does_not_vanish(tmp_path):
    """A feature AT the floor is at the process limit, not under it.

    The erosion test used to delete it -- and inconsistently, since an L-bend
    of the same stroke survived on the rounding of its own corner. All 13
    F.SilkS components the beta coupon reported as deleted measured
    0.149999991 mm against a 0.150 mm floor.
    """
    at = IM.Part("at", [(0, 0), (5, 0)], width=0.15, area=False, closed=False)
    under = IM.Part("u", [(0, 2), (5, 2)], width=0.1499, area=False,
                    closed=False)
    assert IM.measure_layer("F.SilkS", [at], 0.15).vanished == 0
    assert IM.measure_layer("F.SilkS", [under], 0.15).vanished == 1


@needs_shapely
def test_a_reentrant_corner_is_not_a_gap_but_a_real_bridge_is(tmp_path):
    """A gap matters when the process can CLOSE it, which is a topology
    question. Two strokes meeting at an acute angle always produce a sub-floor
    witness at the vertex whatever the cap height, because the number is a
    property of the junction angle and the scan cutoff, not of the artwork."""
    raw = {}
    for cap in (1.5, 3.0):
        parts = _glyph_parts("1", cap, 0.18)
        r0 = IM.measure_layer("F.SilkS", parts, 0.15, classify_gaps=False)
        r1 = IM.measure_layer("F.SilkS", parts, 0.15)
        raw[cap] = r0.min_gap.value
        # The scan finds it either way. The closing test says it joins nothing.
        assert r0.min_gap.value < 0.15
        assert r1.n_rounded_gaps == 1 and r1.n_bridging_gaps == 0
        assert r1.min_gap is None
    # THE TELL: the number barely moves when the artwork DOUBLES in size, and
    # it moves the wrong way. A defect scales with the drawing; this does not,
    # because it is arc_ratio * floor * sin(theta/2) -- the scan's own cutoff
    # and the junction angle. These are the numbers the alpha coupon reported.
    assert raw[1.5] == pytest.approx(0.132074, abs=5e-6)
    assert raw[3.0] == pytest.approx(0.120829, abs=5e-6)

    # A real bridge is still a real bridge: two strokes 0.05 mm apart.
    near = [IM.Part("a", [(0, 0), (3, 0)], width=0.18, area=False,
                    closed=False),
            IM.Part("b", [(0, 0.23), (3, 0.23)], width=0.18, area=False,
                    closed=False)]
    r2 = IM.measure_layer("F.SilkS", near, 0.15)
    assert r2.n_bridging_gaps >= 1 and r2.n_rounded_gaps == 0
    assert r2.min_gap.value == pytest.approx(0.05, abs=1e-6)


def _glyph_parts(s, cap, pen):
    """One string, expanded through the same letterform model the verifier
    measures with, as ink Parts."""
    it = V.Item("fp_text", ["F.SilkS"], [], 0.0, False, s, cap, pen,
                at=(0.0, 0.0), justify=frozenset({"left"}))
    ink = V.expand_text(it)
    assert ink.ok, ink.why
    return [IM.Part("t", list(ch), width=ink.width, area=False, closed=False)
            for ch in ink.chains]


def test_a_flattened_arc_keeps_the_endpoints_kicad_stored(tmp_path):
    """The beta coupon's outline is four gr_line and four gr_arc. Inflating
    the arc ENDPOINTS along with the interior vertices moved each end 1.9 um
    off the stored point, no arc end ever met a line end, and the board outline
    of every rounded-rectangle card went unmeasured behind 'Edge.Cuts present
    but no closed loop found'."""
    a, m, e = (0.0, 2.0), (1.41421356, 1.41421356), (2.0, 0.0)
    pts = V.flatten_arc(a, m, e)
    assert pts[0] == pytest.approx(a) and pts[-1] == pytest.approx(e)
    # interior vertices still circumscribe the true arc
    assert max(abs(complex(*p)) for p in pts[1:-1]) > 2.0


def test_a_rounded_rectangle_outline_is_measured(tmp_path):
    from test_board_verify import write_board
    r, hx, hy = 2.0, 10.0, 6.0
    k = r / 2 ** 0.5
    seg = ('\t(gr_line (start {} {}) (end {} {}) (stroke (width 0.05) '
           '(type default)) (layer "Edge.Cuts"))')
    arc = ('\t(gr_arc (start {} {}) (mid {} {}) (end {} {}) (stroke '
           '(width 0.05) (type default)) (layer "Edge.Cuts"))')
    body = "\n".join([
        seg.format(-hx + r, -hy, hx - r, -hy), seg.format(hx, -hy + r, hx, hy - r),
        seg.format(hx - r, hy, -hx + r, hy), seg.format(-hx, hy - r, -hx, -hy + r),
        arc.format(hx - r, -hy, hx - r + k, -hy + r - k, hx, -hy + r),
        arc.format(hx, hy - r, hx - r + k, hy - r + k, hx - r, hy),
        arc.format(-hx + r, hy, -hx + r - k, hy - r + k, -hx, hy - r),
        arc.format(-hx, -hy + r, -hx + r - k, -hy + r - k, -hx + r, -hy),
    ])
    b = write_board(tmp_path, body, edge=False)
    _v, checks = V.verify_board(b, cfg())
    t = text_of({c.key: c for c in checks}["min-feature"])
    assert "no closed loop found" not in t
    assert "is the OUTLINE" in t and "12.000 mm across" in t
