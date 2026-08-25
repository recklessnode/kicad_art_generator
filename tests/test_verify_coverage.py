"""A SKIPPED CHECK MUST NEVER CONTRIBUTE TO A PASS.

THE RUN THAT PROMPTED THIS FILE
-------------------------------
verify_art.py was run under "C:/Program Files/KiCad/10.0/bin/python.exe", where
shapely is not installed. The ink-floor check reported SKIP. The harness printed

    SUMMARY: 0 pass, 1 warn, 0 fail of 1   (0 exempt, 0 stale)
    No hard failures. Warnings above are fabrication risks, not KiCad errors;
    review before shipping (--strict to enforce).

and exited 0. The same board, on the same fab profile, run from the repo venv
where shapely exists, gives

    SUMMARY: 0 pass, 0 warn, 1 fail of 1
    FAIL -- do not ship these.

and exits 1. A board that FAILS was reported as shippable because the check
that fails it could not load its dependency.

That is the TWELFTH instance in this project of a check that cannot fail what
it exists to catch. verify_art had ALREADY been extended once to report NOT
TESTED rather than green for a vacuous check -- and it still did this, because
the honesty was in the per-check TEXT and the dishonesty was in the SUMMARY and
the EXIT CODE, which is the only part a caller reads.

WHAT EACH TEST HERE PINS, AND HOW IT WAS PROVED NOT TO BE VACUOUS
-----------------------------------------------------------------
A regression test that passes against the code it is supposed to condemn is
the thirteenth instance of this defect, not a defence against it. So these were
run against the pre-fix harness as well as the current one:

    git show 4411eee:tools/verify_art.py > /tmp/old/verify_art.py
    # conftest.py in /tmp/old puts that directory ahead of tools/ on sys.path,
    # so `import verify_art` resolves to the OLD file while ink_measure,
    # fab_profiles and the rest still come from the repo
    cd /tmp/old && .venv/bin/pytest -q tests/test_verify_coverage.py

Result: 29 failed, 3 passed. The three that pass are

    test_the_board_really_does_fail_when_the_check_can_run
    test_the_startup_banner_is_silent_when_the_dependency_is_there
    test_a_clean_fully_measured_board_still_passes

and they pass on purpose. They are GUARDS, not regression tests: they exist to
stop the fix from over-correcting into a harness that reports INCOMPLETE for
everything, which says exactly as much as one that reports PASS for everything.
The other twenty-nine all fail on the old file.

(test_not_applicable_is_not_a_gap is also a guard by intent -- it fences the
same over-correction from the other side -- but it happens to fail on the old
file too, with an AttributeError, because Check had no `gaps` attribute to
assert was empty. Its failure there proves nothing about old behaviour and it
is not counted as a regression test.)
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ink_measure as IM                                       # noqa: E402
import verify_art as V                                         # noqa: E402

needs_shapely = pytest.mark.skipif(not IM.available()[0],
                                   reason="shapely not installed")


# --------------------------------------------------------------------------
# rigging -- every board here is built from constants in this file
# --------------------------------------------------------------------------

LAYER_TABLE = """\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(25 "Edge.Cuts" user)
\t)
"""

EDGE = "".join(
    f'\t(gr_line (start {a} {b}) (end {c} {d}) (stroke (width 0.05) '
    f'(type default)) (layer "Edge.Cuts"))\n'
    for a, b, c, d in [(-1, -1, 41, -1), (41, -1, 41, 31),
                       (41, 31, -1, 31), (-1, 31, -1, -1)])

ARMED = {
    "board": {"design_settings": {"rules": {
        "min_clearance": 0.2, "min_track_width": 0.2,
        "min_silk_clearance": 0.2, "min_text_thickness": 0.2}}},
    "net_settings": {"classes": [
        {"name": "Default", "clearance": 0.0889, "track_width": 0.0889}]},
}


def poly(pts, layer="F.SilkS"):
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return (f'\t(gr_poly (pts {xy}) (stroke (width 0.0) (type default)) '
            f'(fill yes) (layer "{layer}"))')


def rect(x, y, w, h, layer="F.SilkS"):
    return poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], layer)


def bridged_blocks(neck, x=0.0, y=0.0):
    """Two 2x2 blocks joined by a bridge exactly `neck` wide.

    CONCAVE on purpose. min_width() is a rotating caliper on the convex hull
    and answers 2.0 mm for this shape whatever `neck` is, so a sub-floor neck
    here is invisible to every check EXCEPT the region measurement. It is the
    shape of the sub-floor stipple the ink check exists for.
    """
    a, b = 1.0 - neck / 2.0, 1.0 + neck / 2.0
    pts = [(0, 0), (2, 0), (2, 2), (b, 2), (b, 3), (2, 3), (2, 5), (0, 5),
           (0, 3), (a, 3), (a, 2), (0, 2)]
    return [(px + x, py + y) for px, py in pts]


def write_board(tmp_path, body, name="b", pro=None):
    p = tmp_path / f"{name}.kicad_pcb"
    p.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n'
                 '\t(generator_version "10.0")\n\t(general (thickness 1.6))\n'
                 '\t(paper "A4")\n' + LAYER_TABLE
                 + "\t(setup (pad_to_mask_clearance 0))\n" + EDGE + body
                 + "\n)\n", encoding="utf-8")
    if pro is not None:
        (tmp_path / f"{name}.kicad_pro").write_text(json.dumps(pro),
                                                    encoding="utf-8")
    return p


def sub_floor_board(tmp_path, name="stipple"):
    """A board that FAILS jlcpcb-4l-fine, and fails ONLY on the region
    measurement. Everything else about it is clean and fully measured, so a
    run that reports it as anything other than FAIL has stopped measuring."""
    return write_board(tmp_path,
                       poly(bridged_blocks(0.0383), layer="F.SilkS"),
                       name=name, pro=ARMED)


def clean_board(tmp_path, name="clean"):
    """Nothing wrong with it and nothing about it unmeasured."""
    body = "\n".join([
        rect(2, 2, 4, 4, "F.Cu"), rect(12, 2, 4, 4, "F.Cu"),
        rect(2, 12, 4, 4, "F.SilkS"), rect(12, 12, 4, 4, "F.SilkS"),
        rect(22, 2, 4, 4, "F.Mask"), rect(32, 2, 4, 4, "F.Mask"),
    ])
    return write_board(tmp_path, body, name=name, pro=ARMED)


def run_main(capsys, *args, no_shapely=False, monkeypatch=None):
    """-> (exit code, stdout, stderr). `no_shapely` reproduces the interpreter
    the false green came from: ink_measure never imported at all."""
    if no_shapely:
        monkeypatch.setattr(V, "ink_measure", None)
        monkeypatch.setattr(
            V, "_INK_IMPORT_ERR",
            "ModuleNotFoundError: No module named 'shapely'")
    rc = V.main([str(a) for a in args])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def gap_dicts(out_json):
    return [g for f in out_json["files"] for g in f["gaps"]]


# ==========================================================================
# 1. THE DEFECT ITSELF
# ==========================================================================

def test_a_missing_shapely_cannot_summarise_as_a_pass(tmp_path, capsys,
                                                      monkeypatch):
    """REGRESSION. This is the run that happened, reproduced exactly.

    Old behaviour: exit 0, "SUMMARY: 0 pass, 1 warn, 0 fail", "No hard
    failures. Warnings above are fabrication risks". On a board that FAILS.
    """
    b = sub_floor_board(tmp_path)
    rc, out, _err = run_main(capsys, b, "--fab", "jlcpcb-4l-fine",
                             no_shapely=True, monkeypatch=monkeypatch)

    assert rc != 0, "a run that did not measure the board exited 0\n" + out
    assert "No hard failures" not in out, out
    assert "1 warn" not in out, "a check that DID NOT RUN was folded into WARN"
    assert "INCOMPLETE" in out, out
    assert "CHECK(S) DID NOT RUN" in out, out
    # and it says WHICH check and WHY, not merely that something was skipped
    assert "ink-floor" in out and "shapely" in out, out


def test_the_run_without_shapely_is_never_greener_than_the_run_with_it(
        tmp_path, capsys, monkeypatch):
    """REGRESSION, and the property that actually matters.

    Removing a dependency must not be able to IMPROVE a verdict. Old
    behaviour: with shapely rc=1 FAIL, without shapely rc=0 "No hard
    failures" -- deleting a library turned a failing board into a shipping one.
    """
    b = sub_floor_board(tmp_path)
    rc_with, out_with, _ = run_main(capsys, b, "--fab", "jlcpcb-4l-fine")
    with monkeypatch.context() as m:
        rc_without, out_without, _ = run_main(
            capsys, b, "--fab", "jlcpcb-4l-fine",
            no_shapely=True, monkeypatch=m)

    if IM.available()[0]:
        # The measurement really does fail this board when it can run, so the
        # comparison below is between a real FAIL and its absence.
        assert rc_with == 1, out_with
        assert "FAIL -- do not ship these" in out_with
    # The property, stated as the property and not as an ordering on exit
    # codes (1 = FAIL and 3 = INCOMPLETE are not ranked against each other):
    # taking the dependency away must not make the run report as clean.
    assert rc_without != 0, out_without
    assert "No hard failures" not in out_without
    assert "0 pass," in out_without, out_without


@needs_shapely
def test_the_board_really_does_fail_when_the_check_can_run(tmp_path, capsys):
    """GUARD on the two tests above: if this fixture ever stopped failing,
    they would be comparing nothing against nothing and would still pass."""
    b = sub_floor_board(tmp_path)
    rc, out, _ = run_main(capsys, b, "--fab", "jlcpcb-4l-fine")
    assert rc == 1, out
    assert "WIDTH BELOW FLOOR" in out or "SILK WIDTH BELOW FLOOR" in out, out
    assert "0.038300" in out, out


# ==========================================================================
# 2. LOUD AT STARTUP, NOT SILENT AT THE CHECK
# ==========================================================================

def test_a_missing_hard_dependency_is_announced_before_any_file(
        tmp_path, capsys, monkeypatch):
    """REGRESSION. Old behaviour: no startup output at all. The only mention
    of shapely was inside one check's details, three hundred lines into a
    report whose last line said "No hard failures"."""
    b = clean_board(tmp_path)
    _rc, out, err = run_main(capsys, b, no_shapely=True,
                             monkeypatch=monkeypatch)

    assert "THE INK-FLOOR CHECK CANNOT RUN UNDER THIS INTERPRETER" in out, out
    # it names the interpreter that cannot, ...
    assert sys.executable in out, out
    # ... and the one in this repo that can, which is the actionable half
    assert ".venv" in out, out
    # before the first file, not after it
    assert (out.index("CANNOT RUN UNDER THIS INTERPRETER")
            < out.index("=== ")), "the warning came after the report"
    # and on stderr too, for a caller that pipes stdout to a log
    assert "CANNOT RUN UNDER THIS INTERPRETER" in err, err


def test_the_startup_banner_is_silent_when_the_dependency_is_there(
        tmp_path, capsys):
    """GUARD. A banner that always prints is a banner nobody reads."""
    if not IM.available()[0]:
        pytest.skip("shapely not installed")
    b = clean_board(tmp_path)
    _rc, out, err = run_main(capsys, b)
    assert "CANNOT RUN UNDER THIS INTERPRETER" not in out
    assert "CANNOT RUN UNDER THIS INTERPRETER" not in err


def test_preflight_reports_the_gap_it_would_charge(monkeypatch):
    """The preflight's own contract, tested directly."""
    monkeypatch.setattr(V, "ink_measure", None)
    monkeypatch.setattr(V, "_INK_IMPORT_ERR", "ModuleNotFoundError: shapely")
    lines, gaps = V.preflight()
    assert lines and gaps
    assert gaps[0].check == "ink-floor"
    assert gaps[0].kind == V.GAP_NOT_RUN
    assert gaps[0].extent, "a gap with no extent does not say how much was lost"


# ==========================================================================
# 3. BUDGET EXHAUSTION IS AN INCOMPLETE MEASUREMENT, NOT A SKIP
# ==========================================================================

def test_an_exhausted_clearance_budget_says_how_much_went_uncompared(
        tmp_path, capsys):
    """REGRESSION. Old behaviour: level WARN, one line saying "Remaining gaps
    are UNCHECKED", no quantity, and exit 0. The previous production run
    reported the default --clearance-budget exhausting on alpha's F.Cu at 912
    features and the harness still summarised without a failure."""
    # The budget only accumulates on pairs close enough to be worth measuring,
    # so the features have to be within a floor of each other for it to run out
    # at all -- 1.0 mm rectangles on a 1.1 mm pitch, i.e. 0.1 mm gaps against
    # the 0.15 mm silk floor. That the board is also SPACED TOO TIGHT is beside
    # the point here and is what makes the budget bite.
    body = "\n".join(rect(1 + 1.1 * i, 1, 1.0, 1.0, "F.SilkS")
                     for i in range(20))
    b = write_board(tmp_path, body, name="many", pro=ARMED)
    rc, out, _ = run_main(capsys, b, "--clearance-budget", "1", "--json")
    doc = json.loads(out)

    assert doc["summary"]["incomplete"] == 1, out
    assert rc == 3, rc
    inc = [g for g in gap_dicts(doc)
           if g["check"] == "clearance" and g["kind"] == V.GAP_INCOMPLETE]
    assert inc, gap_dicts(doc)
    g = inc[0]
    # an INCOMPLETE MEASUREMENT states its extent, in the unit it measures in
    assert "candidate pair" in g["extent"], g
    assert "NEVER COMPARED" in g["extent"], g
    assert "%" in g["extent"], g
    assert "stopped while examining feature" in g["extent"], g
    assert g["fix"], g


@needs_shapely
def test_an_exhausted_ink_budget_says_how_much_ink_went_unmeasured(
        tmp_path, capsys):
    """REGRESSION. Old behaviour: SKIP, folded into WARN, exit 0."""
    b = sub_floor_board(tmp_path)
    rc, out, _ = run_main(capsys, b, "--fab", "jlcpcb-4l-fine",
                          "--ink-budget", "1", "--json")
    doc = json.loads(out)
    assert rc != 0
    inc = [g for g in gap_dicts(doc)
           if g["check"] == "ink-floor" and g["kind"] == V.GAP_INCOMPLETE]
    assert inc, gap_dicts(doc)
    # mm2 of art, and the share of the file, is the honest unit here
    assert any("mm2" in g["extent"] for g in inc), inc
    assert any("%" in g["extent"] for g in inc), inc


def test_drain_count_reports_a_lower_bound_rather_than_a_wrong_total():
    """The remainder count is capped, and says so instead of lying."""
    assert V._drain_count(iter(range(10)), 100) == (10, False)
    assert V._drain_count(iter(range(1000)), 7) == (7, True)


# ==========================================================================
# 4. A CHECK WITH NOTHING TO TEST IS NOT A CHECK THAT PASSED
# ==========================================================================

@needs_shapely
def test_a_layer_with_no_pairs_cannot_be_folded_into_a_passing_run(
        tmp_path, capsys):
    """REGRESSION. A single feature forms no pairs, so the spacing floor was
    applied to nothing. Old behaviour: the detail line said NOT TESTED and the
    run exited 0 anyway -- the honest sentence had no consequence."""
    b = write_board(tmp_path, rect(2, 2, 5, 5, "F.SilkS"), name="lone",
                    pro=ARMED)
    rc, out, _ = run_main(capsys, b, "--json")
    doc = json.loads(out)
    vac = [g for g in gap_dicts(doc) if g["kind"] == V.GAP_VACUOUS]
    assert vac, gap_dicts(doc)
    assert rc == 3, out
    assert doc["files"][0]["verdict"] == V.INCOMPLETE


def test_a_vacuous_gap_says_it_does_not_mean_the_layer_is_clean(
        tmp_path, capsys):
    """The wording is load-bearing: "0 pairs" is the sentence that reads like
    a pass, so the gap has to say out loud that it is not one."""
    b = write_board(tmp_path, rect(2, 2, 5, 5, "F.SilkS"), name="lone2",
                    pro=ARMED)
    _rc, out, _ = run_main(capsys, b, "--json")
    doc = json.loads(out)
    vac = [g for g in gap_dicts(doc) if g["kind"] == V.GAP_VACUOUS]
    assert any("does NOT mean" in g["extent"] for g in vac), vac


@needs_shapely
def test_a_profile_with_no_published_floor_does_not_pass_silently(
        tmp_path, capsys):
    """REGRESSION. OSH Park publishes no silkscreen minimum and no mask dam.
    apply_fab keeps the palette doc's house number for those and prints a line
    saying so -- and the run then compared the artwork against guidance wearing
    a fabricator's name and called the result a pass. "The floors are from
    oshpark-2l" was not true of silk or mask on any such run."""
    b = clean_board(tmp_path)
    rc, out, _ = run_main(capsys, b, "--fab", "oshpark-2l", "--json")
    doc = json.loads(out)
    unjudged = [g for g in gap_dicts(doc)
                if g["check"] == "fab" and g["kind"] == V.GAP_UNJUDGED]
    scopes = {g["scope"] for g in unjudged}
    assert scopes == {"silk floor", "mask floor"}, gap_dicts(doc)
    assert rc == 3, out
    # and a profile that publishes everything charges nothing
    rc2, out2, _ = run_main(capsys, b, "--fab", "jlcpcb-4l-fine", "--json")
    doc2 = json.loads(out2)
    assert not [g for g in gap_dicts(doc2) if g["check"] == "fab"], out2
    assert rc2 == 0, out2


def test_unpublished_floors_reads_the_profile_table_not_a_second_copy():
    """The list comes from tools/fab_profiles.py itself, so a profile that
    gains or loses a published number cannot leave this out of date."""
    assert V.unpublished_floors("jlcpcb-4l-fine") == []
    assert {c for c, _w in V.unpublished_floors("oshpark-2l")} == {"silk",
                                                                  "mask"}


# ==========================================================================
# 5. EVERY WAY OF TURNING A CHECK OFF BINDS THE RUN
# ==========================================================================

@needs_shapely
@pytest.mark.parametrize("flags,who", [
    (["--no-ink"], "ink-floor"),
    (["--no-clearance"], "clearance"),
    (["--ink-layers", "B.Cu"], "ink-floor"),
    (["--ink-max-segments", "1"], "ink-floor"),
    (["--ink-budget", "1"], "ink-floor"),
    (["--clearance-budget", "1"], "clearance"),
    (["--max-clearance-items", "1"], "clearance"),
    (["--max-poly-pts", "3"], "self-isect"),
])
def test_every_switch_that_disables_a_check_makes_the_run_incomplete(
        tmp_path, capsys, flags, who):
    """REGRESSION, and the structural one.

    Old behaviour: each of these produced SKIP or WARN and exit 0. Making one
    site honest at a time is how this defect keeps coming back; the property
    has to hold for EVERY way a check can be turned off, so it is asserted
    over the whole list rather than over the one that got noticed.
    """
    body = "\n".join([
        rect(2, 2, 4, 4, "F.Cu"), rect(12, 2, 4, 4, "F.Cu"),
        rect(2, 12, 4, 4, "F.SilkS"), rect(12, 12, 4, 4, "F.SilkS"),
        # One tight pair, so --clearance-budget has something to run out ON:
        # the budget only accumulates over pairs close enough to measure.
        rect(22, 2, 4, 4, "F.Cu"), rect(26.05, 2, 4, 4, "F.Cu"),
    ])
    b = write_board(tmp_path, body, name="sw", pro=ARMED)

    rc, out, _ = run_main(capsys, b, *flags, "--json")
    doc = json.loads(out)
    who_gaps = [g for g in gap_dicts(doc) if g["check"] == who]
    assert who_gaps, f"{flags} silently turned {who} off\n" + out
    assert all(g["extent"] for g in who_gaps), who_gaps
    assert rc == 3, f"{flags} -> exit {rc}"
    assert doc["files"][0]["verdict"] == V.INCOMPLETE


@needs_shapely
def test_a_footprint_run_without_the_kicad_plot_is_incomplete(
        tmp_path, capsys):
    """REGRESSION. --no-render skips the fp export svg cross-check, which is
    the only evidence that the letterforms measured are the letterforms KiCad
    images. Old behaviour: one detail line, level PASS, exit 0."""
    p = tmp_path / "t.kicad_mod"
    p.write_text(
        '(footprint "t"\n\t(version 20241229)\n\t(generator "test")\n'
        '\t(layer "F.Cu")\n'
        '\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
        + rect(0, 0, 2, 2, "F.SilkS").replace("gr_poly", "fp_poly") + "\n"
        + rect(5, 0, 2, 2, "F.SilkS").replace("gr_poly", "fp_poly") + "\n)\n",
        encoding="utf-8")
    rc, out, _ = run_main(capsys, p, "--no-render", "--json")
    doc = json.loads(out)
    g = [x for x in gap_dicts(doc) if x["scope"] == "fp export svg"]
    if not V.find_kicad_cli(None).path:
        pytest.skip("no kicad-cli on this machine")
    assert g, gap_dicts(doc)
    assert rc == 3, out


# ==========================================================================
# 6. --accept-gaps ACCEPTS THE HOLE. IT DOES NOT RENAME IT.
# ==========================================================================

@needs_shapely
def test_accept_gaps_moves_the_exit_code_and_nothing_else(tmp_path, capsys):
    b = clean_board(tmp_path)
    rc_no, out_no, _ = run_main(capsys, b, "--no-ink", "--json")
    rc_yes, out_yes, _ = run_main(capsys, b, "--no-ink", "--accept-gaps",
                                  "--json")
    a, c = json.loads(out_no), json.loads(out_yes)

    assert rc_no == 3 and rc_yes == 0
    # the VERDICT is untouched: the file is still not a pass
    assert a["files"][0]["verdict"] == V.INCOMPLETE
    assert c["files"][0]["verdict"] == V.INCOMPLETE
    assert c["summary"]["pass"] == 0
    # and the gaps are still listed, in full
    assert gap_dicts(a) == gap_dicts(c)
    assert c["gaps_accepted"] is True


@needs_shapely
def test_accept_gaps_cannot_rescue_a_real_failure(tmp_path, capsys):
    """It acknowledges what was NOT measured. It has no opinion on what was."""
    b = sub_floor_board(tmp_path)
    rc, out, _ = run_main(capsys, b, "--fab", "jlcpcb-4l-fine",
                          "--accept-gaps")
    assert rc == 1, out
    assert "FAIL -- do not ship these" in out


@needs_shapely
def test_the_gap_list_survives_quiet(tmp_path, capsys):
    """--quiet hides check details. It must not hide what did not run."""
    b = clean_board(tmp_path)
    _rc, out, _ = run_main(capsys, b, "--no-ink", "--quiet")
    assert "CHECK(S) DID NOT RUN" in out, out
    assert "--no-ink" in out, out


# ==========================================================================
# 7. THE ANTI-OVER-CORRECTION GUARDS
# ==========================================================================
#
# A harness that reports INCOMPLETE for everything says exactly as much as one
# that reports PASS for everything. These two tests pass on the old code as
# well -- deliberately. They are not regression tests; they are the fence that
# stops the regression tests above from being satisfied by making the tool
# refuse to ever pass.

@needs_shapely
def test_a_clean_fully_measured_board_still_passes(tmp_path, capsys):
    """GUARD."""
    b = clean_board(tmp_path)
    rc, out, _ = run_main(capsys, b, "--fab", "jlcpcb-4l-fine")
    assert rc == 0, out
    assert "1 pass" in out, out
    assert "CHECK(S) DID NOT RUN" not in out, out


def test_not_applicable_is_not_a_gap(tmp_path):
    """GUARD (see the note in the module docstring). check_inventory and
    check_project_rules are board-only. On a
    footprint there is nothing there to measure, so nothing went unmeasured,
    and charging a gap would make every footprint permanently INCOMPLETE.

    This distinction is the whole reason coverage is a second axis rather than
    another level: SKIP has to be able to mean both "not applicable" and "did
    not run", and only one of them binds the run.
    """
    p = tmp_path / "f.kicad_mod"
    p.write_text('(footprint "f"\n\t(version 20241229)\n\t(generator "t")\n'
                 '\t(layer "F.Cu")\n'
                 + rect(0, 0, 2, 2, "F.SilkS").replace("gr_poly", "fp_poly")
                 + "\n)\n", encoding="utf-8")
    fp = V.load_footprint(p)
    conf = type("C", (), {})()
    conf.max_report = 8
    conf.palette = V.Palette(
        recipe_layers=set(),
        floors={"silk": 0.15, "mask": 0.1, "copper": 0.1, "buried": 0.5,
                "edge": 1.0},
        buried_provisional=False, source="test", notes=[], hard=set())

    inv = V.check_inventory(fp, conf)
    pro = V.check_project_rules(fp, conf)
    assert inv.level == V.SKIP and inv.gaps == []
    assert pro.level == V.SKIP and pro.gaps == []
    assert "not applicable" in inv.headline
    assert "not applicable" in pro.headline


# ==========================================================================
# 8. THE MACHINE-READABLE SIDE
# ==========================================================================

@needs_shapely
def test_json_carries_the_gaps_and_the_incomplete_count(tmp_path, capsys):
    """REGRESSION. The JSON summary had pass/warn/fail and no way at all to
    express "this run did not look", so a CI job consuming it could not tell
    a measured board from an unmeasured one."""
    b = clean_board(tmp_path)
    _rc, out, _ = run_main(capsys, b, "--no-ink", "--json")
    doc = json.loads(out)

    assert doc["summary"]["incomplete"] == 1
    assert doc["summary"]["checks_did_not_run"] >= 1
    assert doc["summary"]["pass"] == 0
    g = gap_dicts(doc)[0]
    assert set(g) == {"check", "scope", "kind", "why", "fix", "extent"}
    # and the gaps hang off their own check as well as off the file
    ink = [c for c in doc["files"][0]["checks"] if c["key"] == "ink-floor"][0]
    assert ink["gaps"]


@needs_shapely
def test_an_incomplete_file_does_not_hide_its_findings(tmp_path, capsys):
    """A file can be INCOMPLETE *and* carry findings. "0 warn" in the summary
    is then about the verdict column, and a reader must not take it for "no
    warnings"."""
    b = sub_floor_board(tmp_path)          # sub-floor, so it has findings
    _rc, out, _ = run_main(capsys, b, "--no-clearance", "--json")
    doc = json.loads(out)
    f = doc["files"][0]
    assert f["verdict"] == V.INCOMPLETE
    assert f["worst_level"] in (V.WARN, V.FAIL), f["worst_level"]

    _rc, txt, _ = run_main(capsys, b, "--no-clearance")
    assert "0 warn" in txt
    assert "(findings:" in txt, txt


def test_every_gap_states_an_extent(tmp_path, capsys, monkeypatch):
    """A gap that cannot say how much went unmeasured is half a report.

    Swept over a run that is deliberately full of holes rather than asserted
    at each site, so a NEW gap site added later cannot get away with omitting
    it.
    """
    b = sub_floor_board(tmp_path)
    _rc, out, _ = run_main(capsys, b, "--no-clearance", "--json",
                           no_shapely=True, monkeypatch=monkeypatch)
    doc = json.loads(out)
    gs = gap_dicts(doc)
    assert len(gs) >= 3, gs
    for g in gs:
        assert g["extent"], f"gap with no extent: {g}"
        assert g["why"], f"gap with no reason: {g}"
        assert g["kind"] in (V.GAP_NOT_RUN, V.GAP_INCOMPLETE, V.GAP_VACUOUS,
                             V.GAP_UNJUDGED), g


# ==========================================================================
# 9. THE OLD SENTENCES ARE GONE
# ==========================================================================

def test_the_summary_can_no_longer_say_no_hard_failures_over_a_hole(
        tmp_path, capsys, monkeypatch):
    """REGRESSION, on the exact string that was read and believed."""
    b = sub_floor_board(tmp_path)
    _rc, out, _ = run_main(capsys, b, "--fab", "jlcpcb-4l-fine",
                           no_shapely=True, monkeypatch=monkeypatch)
    assert "No hard failures" not in out
    assert "review before shipping" not in out
    assert "INCOMPLETE -- NOT A PASS" in out


def test_the_summary_line_counts_incomplete_separately_from_warn(
        tmp_path, capsys, monkeypatch):
    """REGRESSION. "1 warn" was the whole lie: a check that did not run was
    counted in the same column as a fabrication risk somebody had looked at."""
    b = clean_board(tmp_path)
    _rc, out, _ = run_main(capsys, b, "--no-ink",
                           no_shapely=True, monkeypatch=monkeypatch)
    assert "0 warn" in out, out
    assert "1 incomplete" in out, out
