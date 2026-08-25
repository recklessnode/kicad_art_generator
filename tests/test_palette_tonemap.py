"""Tests for the tone table, the declared resolver, and the fidelity metric.

EVERY TEST HERE IS LISTED WITH THE THING IT CATCHES AND THE INPUT THAT MAKES IT
FAIL. That is the whole point: this repo has shipped four checks that could not
fail what they existed to catch, and the fix for that is not more checks, it is
checks with a committed failing input beside them.

None of these reads the emitter's own report as evidence of the emitter's
output. `test_helper_is_not_a_reimplementation` enforces that structurally for
tools/fidelity.py, because the fourth bitten instance was a helper that
documented itself as "the independent second opinion" while being a
line-for-line reimplementation of the tool it was checking.
"""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import fidelity                                    # noqa: E402
import palette as pal_mod                          # noqa: E402
import tone_map as tm                              # noqa: E402
from fixtures.palettes import (BLACK_AGAINST_DARK_INK,  # noqa: E402
                               PURPLE_CODED, TWO_NON_DRAWING_TONES)

EMIT = TOOLS / "emit_art.py"
BUILD = TOOLS / "build_library.py"
VERIFY = TOOLS / "verify_art.py"
ASSETS = REPO / "assets" / "normalised"
PRETTY = REPO / "output" / "RecklessArt.pretty"
WORK = REPO / "output" / "library_work"

_has_corpus = ASSETS.is_dir() and (ASSETS / "bitcoin_b.svg").is_file()
_has_built = (PRETTY / "bitcoin_b_16mm.kicad_mod").is_file() and \
             (WORK / "bitcoin_b_16mm.json").is_file()
needs_corpus = pytest.mark.skipif(not _has_corpus,
                                  reason="normalised assets not present")
needs_built = pytest.mark.skipif(not _has_built,
                                 reason="output/RecklessArt.pretty not built")


def tone_map_for(src, mask="purple", overrides=None):
    """Build a tone map by CENSUSING the source, not by naming its colours.

    The corpus is third-party brand art and this repo is public, so no test
    here writes one of its colours down. Reading them off the file at run time
    is also the stronger test: a hard-coded hex silently stops matching the day
    the asset is re-exported, and the run then measures a tone map that is not
    the one under test.
    """
    import prep_assets
    from emit_art import crop_to_content, rasterise_svg
    src = Path(src)
    if src.suffix.lower() == ".svg":
        img, _ = rasterise_svg(src, 1200)
    else:
        img = Image.open(src).convert("RGBA")
    img, _ = crop_to_content(img)
    arr = np.asarray(img.convert("RGBA"))
    cen = prep_assets.colour_census(arr[..., :3], arr[..., 3] >= 128, 10.0,
                                    mask=mask)
    pal = pal_mod.palette_for(mask, allow_provisional=True)
    legible = list(pal.legible(allow_inner=False, allow_provisional=True))
    rows, first_of = [], {}
    for c in cen["clusters"]:
        if c["area_fraction"] < 0.004:
            continue
        rgb = tuple(int(v) for v in c["rgb"])
        w = tm._weighted(np.array(rgb, dtype=np.uint8))
        tone = min(legible, key=lambda t: float(np.linalg.norm(
            w - tm._weighted(np.array(pal[t].rgb, dtype=np.uint8)))))
        tone = (overrides or {}).get(c["hex"], tone)
        row = {"rgb": c["hex"], "tone": tone}
        d = float(np.linalg.norm(
            w - tm._weighted(np.array(pal[tone].rgb, dtype=np.uint8))))
        if d >= tm.OFF_PALETTE_DE:
            row["off_palette"] = True
        if abs(pal.dl_to_board(tone)) < pal_mod.LEGIBLE_MIN_DL:
            row["legibility"] = "declared"
        if tone in first_of:
            row["merge_ok"] = [first_of[tone]]
            # This helper is a census draft, not a curated map: on
            # little_satoshi the nearest-legible merge paints the chest S
            # gold-on-gold, and the emitter now refuses exactly that (issue
            # #17, test_merge_erasure.py). The tests using this helper are
            # about emission mechanics, so the erasure is declared, the way
            # a person shipping the merge on purpose would.
            row["erase_ok"] = True
        else:
            first_of[tone] = c["hex"]
        rows.append(row)
    return {"mask": mask, "tol_de": 10.0, "unmapped_budget_pct": 1.0,
            "tones": rows}


def run(args, **kw):
    return subprocess.run([sys.executable, *[str(a) for a in args]],
                          capture_output=True, text=True, **kw)


# ---------------------------------------------------------------------------
# 1. the palette invariant
# ---------------------------------------------------------------------------

def test_palette_validate_rejects_purple_coded():
    """CATCHES: a tone table with no drawable tone for the ink it serves.

    FAILING INPUT: tests/fixtures/palettes.PURPLE_CODED -- the table
    fab_profiles.tone_anchors("purple") produced. T5 draws nothing and is the
    darkest entry, so black ink resolves to it by proximity and is erased.
    """
    v = PURPLE_CODED.validate()
    assert v, "PURPLE_CODED must not validate clean -- it erases black ink"
    kinds = {x.kind for x in v}
    assert "nearest_anchor" in kinds, [str(x) for x in v]
    assert any("(0, 0, 0)" in x.msg for x in v), [str(x) for x in v]


def test_palette_validate_rejects_black_against_dark_ink():
    v = BLACK_AGAINST_DARK_INK.validate()
    assert any(x.kind == "nearest_anchor" for x in v), [str(x) for x in v]


def test_palette_validate_catches_two_non_drawing_tones():
    """CATCHES rule 1, which no input this repo generates would ever exercise."""
    v = TWO_NON_DRAWING_TONES.validate()
    assert any(x.kind == "structural" and "draw nothing" in x.msg for x in v), \
        [str(x) for x in v]


def test_shipped_palettes_have_no_structural_defect():
    for mask in ("black", "purple", "green", "white"):
        p = pal_mod.palette_for(mask, allow_provisional=True)
        assert [x for x in p.validate() if x.kind == "structural"] == []


def test_provisional_tones_are_not_drawable_by_default():
    p = pal_mod.palette_for("purple")
    assert "T6" not in p.drawable()
    assert "T6" in p.drawable(allow_provisional=True)
    assert p["T6"].provenance == "PROVISIONAL"
    # ...and black's are not provisional, so a black run is unaffected.
    assert all(t.provenance != "PROVISIONAL"
               for t in pal_mod.palette_for("black").tones)


def test_green_t6_is_brighter_than_t5():
    """The refutation, as a test. docs/pcb-palette.md line 152 says T6 is
    visibly brighter than T5 on green; the deleted tone_anchors() returned it
    9.985 L* DARKER because green's mask luma (0.2965) crossed a guessed 0.25
    threshold."""
    g = pal_mod.palette_for("green", allow_provisional=True)
    assert g.dl_to_board("T6") > 0, g.dl_to_board("T6")
    assert g.dl_to_board("T7") > 0


def test_inner_tones_agree_with_the_recipe_table():
    from coupon_blocks import TONE_RECIPE
    recipe = {k.split("_", 1)[0]: v for k, v in TONE_RECIPE.items()}
    p = pal_mod.palette_for("black")
    for t in p.tones:
        assert t.inner == any(l.startswith("In") for l in recipe[t.id]), t.id


def test_palette_tag_round_trips():
    p = pal_mod.palette_for("purple")
    back = pal_mod.from_tag(f"recklessart art {p.tag()}")
    assert back.tag() == p.tag()
    assert back.digest() == p.digest()
    assert pal_mod.from_tag("recklessart art") is None
    with pytest.raises(pal_mod.PaletteError):
        pal_mod.from_tag("palette:purple-white-enig palette:black-white-enig")


# ---------------------------------------------------------------------------
# 2. ink the colour of the board still emits
# ---------------------------------------------------------------------------

def _swatch(path, rgb, size=200):
    a = np.zeros((size, size, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[40:160, 40:160, :3] = rgb                    # a square of the test ink
    Image.fromarray(a, "RGBA").save(path)


def test_t5_coloured_ink_still_emits(tmp_path):
    """CATCHES: the whole failure this change exists for, at its extreme.

    The ink is EXACTLY the board's own colour. Under nearest-anchor assignment
    it is T5 by definition and draws nothing. Declared to a drawable tone it
    must produce polygons. Strictly stronger than probing quantise(rgb(0,0,0)):
    this one cannot be passed by moving an anchor.
    """
    p = pal_mod.palette_for("purple", allow_provisional=True)
    board = p["T5"].rgb
    src = tmp_path / "swatch.png"
    _swatch(src, board)
    tmap = tmp_path / "tm.json"
    tmap.write_text(json.dumps({
        "mask": "purple", "tol_de": 10.0,
        "tones": [{"rgb": "#ffffff", "tone": "T1"},
                  {"rgb": tm.rgb_to_hex(board), "tone": "T2",
                   "off_palette": True}]}))
    out = tmp_path / "sw.kicad_mod"
    rep = tmp_path / "sw.json"
    r = run([EMIT, "--labels", src, "--width-mm", 10, "--name", "sw",
             "-o", out, "--report-json", rep, "--tone-map", tmap,
             "--palette-mask", "purple"])
    assert r.returncode == 0, r.stderr
    text = out.read_text()
    assert "F.Cu" in text and "F.Mask" in text, "the T5-coloured square is absent"
    rows = {t["tone"]: t for t in json.loads(rep.read_text())["tones"]}
    assert rows["T2"]["polys"] >= 1, rows


def test_ink_tone_no_longer_demands_the_background(tmp_path):
    """The guard at emit_art.py:3869 used to require the single present tone to
    be T5 exactly. That is a statement about one palette; four of the library's
    21 pieces exited 2 under any colourway where black does not land on T5."""
    src = tmp_path / "mono.png"
    a = np.zeros((120, 120, 4), dtype=np.uint8)
    a[20:100, 20:100] = (10, 10, 12, 255)
    Image.fromarray(a, "RGBA").save(src)
    out = tmp_path / "m.kicad_mod"
    r = run([EMIT, "--labels", src, "--width-mm", 10, "--name", "m", "-o", out,
             "--ink-tone", "T1", "--palette-mask", "purple"])
    assert r.returncode == 0, r.stderr
    assert "F.SilkS" in out.read_text()


# ---------------------------------------------------------------------------
# 3. the fidelity metric can fail
# ---------------------------------------------------------------------------

@needs_built
def test_undrawn_can_fail(tmp_path):
    """CATCHES: a fidelity metric that reports a good number for a mutilated
    part. FAILING INPUT: bitcoin_b_16mm with every F.SilkS polygon deleted --
    the white of the mark, gone. 0.197 % must become ~29 %."""
    rep = json.loads((WORK / "bitcoin_b_16mm.json").read_text())
    good = fidelity.undrawn_ink(ASSETS / "bitcoin_b.svg",
                                PRETTY / "bitcoin_b_16mm.kicad_mod", rep)
    assert good["undrawn_pct"] < 1.0, good
    assert good["verdict"] == "PASS"

    txt = (PRETTY / "bitcoin_b_16mm.kicad_mod").read_text()
    kept = [b for b in fidelity._blocks(txt, "fp_poly") if "F.SilkS" not in b]
    dropped = [b for b in fidelity._blocks(txt, "fp_poly") if "F.SilkS" in b]
    assert dropped, "no F.SilkS polygons to remove -- the control is inert"
    for b in dropped:
        txt = txt.replace(b, "")
    bad = tmp_path / "bitcoin_b_16mm.kicad_mod"
    bad.write_text(txt)
    got = fidelity.undrawn_ink(ASSETS / "bitcoin_b.svg", bad, rep)
    assert got["undrawn_pct"] > 25.0, got
    assert got["verdict"] == "FAIL"
    assert len(kept) == len(fidelity.polys_of(bad))


@needs_built
def test_undrawn_minimum_is_at_zero_shift(tmp_path):
    """The alignment control. If the frame equations were wrong the metric
    would still return a number, and it would still look plausible. Shifting
    every polygon by one pixel must make it WORSE in both directions."""
    rep = json.loads((WORK / "bitcoin_b_16mm.json").read_text())
    src = ASSETS / "bitcoin_b.svg"
    mod = PRETTY / "bitcoin_b_16mm.kicad_mod"
    base = fidelity.undrawn_ink(src, mod, rep)["undrawn_pct"]
    mmpx = rep["mm_per_px"]
    txt = mod.read_text()
    for axis, sign in ((0, +1), (0, -1), (1, +1), (1, -1)):
        def shift(m, axis=axis, sign=sign):
            x, y = float(m.group(1)), float(m.group(2))
            if axis == 0:
                x += sign * mmpx
            else:
                y += sign * mmpx
            return f"(xy {x:.6f} {y:.6f})"
        moved = tmp_path / f"s{axis}{sign}.kicad_mod"
        moved.write_text(re.sub(r"\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)", shift, txt))
        got = fidelity.undrawn_ink(src, moved, rep)["undrawn_pct"]
        assert got > base, (axis, sign, got, base)


@needs_built
def test_fidelity_reproduces_the_shipped_measurements():
    """The mutilated four, as numbers. If a future change quietly improves
    these it is because the metric moved, not because the art did."""
    want = {"satoshi_points_20mm": (29.5, 29.6),
            "satoshi_little_20mm": (24.5, 24.7),
            "satoshi_miner_20mm": (20.2, 20.3),
            "mfb_node_full_38mm": (11.9, 12.0),
            "bitcoin_b_16mm": (0.19, 0.21)}
    srcs = {"satoshi_points_20mm": "satoshi_points.png",
            "satoshi_little_20mm": "little_satoshi.png",
            "satoshi_miner_20mm": "satoshi_miner.png",
            "mfb_node_full_38mm": "mfb_node_full.svg",
            "bitcoin_b_16mm": "bitcoin_b.svg"}
    for fp, (lo, hi) in want.items():
        if not (PRETTY / f"{fp}.kicad_mod").is_file():
            pytest.skip(f"{fp} not built")
        rep = json.loads((WORK / f"{fp}.json").read_text())
        got = fidelity.undrawn_ink(ASSETS / srcs[fp], PRETTY / f"{fp}.kicad_mod",
                                   rep)["undrawn_pct"]
        assert lo <= got <= hi, (fp, got)


def test_helper_is_not_a_reimplementation():
    """CATCHES the fourth bitten instance directly: an acceptance metric that
    is really the tool it is checking, wearing a different name. STATIC, so it
    cannot be satisfied by a passing run."""
    tree = ast.parse((TOOLS / "fidelity.py").read_text())
    allowed = {"rasterise_svg", "crop_to_content", "relative_luminance"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "emit_art":
            names = {a.name for a in node.names}
            assert names <= allowed, f"fidelity.py imports {names - allowed}"
        if isinstance(node, ast.Import):
            assert not any(a.name == "emit_art" for a in node.names), \
                "fidelity.py must not import emit_art wholesale"


# ---------------------------------------------------------------------------
# 4-6. the declaration gates
# ---------------------------------------------------------------------------

def _three_ink_png(path):
    a = np.zeros((150, 150, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[10:60, 10:140, :3] = (247, 147, 26)          # orange
    a[70:120, 10:140, :3] = (11, 191, 219)         # cyan
    Image.fromarray(a, "RGBA").save(path)


def test_merge_gate_fails_undeclared(tmp_path):
    """CATCHES: two visibly different inks quietly becoming one tone."""
    src = tmp_path / "three.png"
    _three_ink_png(src)
    tmap = tmp_path / "tm.json"
    tmap.write_text(json.dumps({"mask": "black", "tones": [
        {"rgb": "#ffffff", "tone": "T1"},
        {"rgb": "#e08a1e", "tone": "T2"},
        {"rgb": "#10c0e0", "tone": "T2", "off_palette": True}]}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "t",
             "-o", tmp_path / "t.kicad_mod", "--tone-map", tmap])
    assert r.returncode == 2, r.stdout
    assert "both bound to T2" in r.stderr, r.stderr

    # ...and it passes once the merge is named.
    tmap.write_text(json.dumps({"mask": "black", "tones": [
        {"rgb": "#ffffff", "tone": "T1"},
        {"rgb": "#e08a1e", "tone": "T2"},
        {"rgb": "#10c0e0", "tone": "T2", "off_palette": True,
         "merge_ok": ["#e08a1e"]}]}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "t",
             "-o", tmp_path / "t.kicad_mod", "--tone-map", tmap])
    assert r.returncode == 0, r.stderr


def test_merge_ok_is_transitive():
    """Three golds and one metal tone: a chain of declarations is the group it
    obviously is. Without this a five-colour piece needs ten declarations and
    nobody reads the tenth."""
    t = tm.ToneMap.from_dict({"mask": "purple", "tones": [
        {"rgb": "#e0a040", "tone": "T2"},
        {"rgb": "#f0d050", "tone": "T2", "merge_ok": ["#e0a040"]},
        {"rgb": "#c08830", "tone": "T2", "merge_ok": ["#e0a040"]}]})
    assert t.merge_declared("#f0d050", "#c08830")
    assert t.merge_groups() == [("#c08830", "#e0a040", "#f0d050")]
    # ...but an undeclared colour is never dragged in.
    t2 = tm.ToneMap.from_dict({"mask": "purple", "tones": [
        {"rgb": "#e0a040", "tone": "T2"},
        {"rgb": "#f0d050", "tone": "T2", "merge_ok": ["#e0a040"]},
        {"rgb": "#c08830", "tone": "T2"}]})
    assert not t2.merge_declared("#f0d050", "#c08830")


def test_legibility_gate_fails_on_black_T6(tmp_path):
    """CATCHES THE FIFTH INSTANCE OF THE BITTEN PATTERN, and it arrives inside
    the fix. Once T5 is ineligible and inner tones are excluded, black ink is
    STRUCTURALLY forced onto T6. Undrawn ink then reads 1-2 % while the limbs
    are drawn 7.87 L* from the board -- which tools/texture_board.py calls
    "a sheen and not a graphic". The part is not missing. It is invisible."""
    p = pal_mod.palette_for("black")
    assert abs(p.dl_to_board("T6")) < pal_mod.LEGIBLE_MIN_DL, p.dl_to_board("T6")
    src = tmp_path / "dark.png"
    a = np.zeros((150, 150, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[20:130, 20:130, :3] = (1, 1, 1)
    Image.fromarray(a, "RGBA").save(src)
    tmap = tmp_path / "tm.json"
    body = [{"rgb": "#ffffff", "tone": "T1"},
            {"rgb": "#010101", "tone": "T6", "off_palette": True}]
    tmap.write_text(json.dumps({"mask": "black", "tones": body}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "d",
             "-o", tmp_path / "d.kicad_mod", "--tone-map", tmap])
    assert r.returncode == 2, r.stdout
    assert "L* from the board" in r.stderr, r.stderr

    body[1]["legibility"] = "declared"
    tmap.write_text(json.dumps({"mask": "black", "tones": body}))
    out = tmp_path / "d.kicad_mod"
    rep = tmp_path / "d.json"
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "d",
             "-o", out, "--report-json", rep, "--tone-map", tmap])
    assert r.returncode == 0, r.stderr

    # ...and the acceptance metric still SAYS so, declared or not.
    g = fidelity.illegible_ink(out, json.loads(rep.read_text()), p,
                               tm.ToneMap.load(tmap))
    t6 = next(r for r in g["tones"] if r["tone"] == "T6")
    assert t6["share_pct"] > 1.0 and t6["status"].startswith("ILLEGIBLE"), t6


def test_offpalette_gate(tmp_path):
    """CATCHES: an ink silently approximated by a tone it is nowhere near.
    FAILING INPUT: the Reckless red, 58 weighted-Lab units from every tone on
    every palette in the repo. It renders as gold whatever anyone does."""
    src = tmp_path / "red.png"
    a = np.zeros((120, 120, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[20:100, 20:100, :3] = (240, 81, 54)
    Image.fromarray(a, "RGBA").save(src)
    tmap = tmp_path / "tm.json"
    body = [{"rgb": "#ffffff", "tone": "T1"}, {"rgb": "#f04a30", "tone": "T2"}]
    tmap.write_text(json.dumps({"mask": "purple", "tones": body}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "r",
             "-o", tmp_path / "r.kicad_mod", "--tone-map", tmap,
             "--palette-mask", "purple"])
    assert r.returncode == 2, r.stdout
    assert "off_palette" in r.stderr, r.stderr
    body[1]["off_palette"] = True
    tmap.write_text(json.dumps({"mask": "purple", "tones": body}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "r",
             "-o", tmp_path / "r.kicad_mod", "--tone-map", tmap,
             "--palette-mask", "purple"])
    assert r.returncode == 0, r.stderr


def test_unmapped_ink_is_refused_with_a_paste_ready_block(tmp_path):
    src = tmp_path / "orphan.png"
    a = np.zeros((120, 120, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[20:100, 20:100, :3] = (60, 140, 30)          # nobody declares green
    Image.fromarray(a, "RGBA").save(src)
    tmap = tmp_path / "tm.json"
    tmap.write_text(json.dumps({"mask": "black", "tones": [
        {"rgb": "#ffffff", "tone": "T1"}]}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "o",
             "-o", tmp_path / "o.kicad_mod", "--tone-map", tmap])
    assert r.returncode == 2, r.stdout
    assert "UNMAPPED INK" in r.stderr and 'tone = "?"' in r.stderr, r.stderr


def test_inner_tone_needs_permission(tmp_path):
    src = tmp_path / "two.png"
    a = np.zeros((120, 120, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[20:100, 20:100, :3] = (1, 1, 1)
    Image.fromarray(a, "RGBA").save(src)
    tmap = tmp_path / "tm.json"
    tmap.write_text(json.dumps({"mask": "black", "tones": [
        {"rgb": "#ffffff", "tone": "T1"},
        {"rgb": "#010101", "tone": "T7", "off_palette": True,
         "legibility": "declared"}]}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "i",
             "-o", tmp_path / "i.kicad_mod", "--tone-map", tmap])
    assert r.returncode == 2 and "INNER" in r.stderr, r.stderr


def test_provisional_tone_needs_permission(tmp_path):
    src = tmp_path / "two.png"
    a = np.zeros((120, 120, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[20:100, 20:100, :3] = (1, 1, 1)
    Image.fromarray(a, "RGBA").save(src)
    tmap = tmp_path / "tm.json"
    tmap.write_text(json.dumps({"mask": "purple", "tones": [
        {"rgb": "#ffffff", "tone": "T1"},
        {"rgb": "#010101", "tone": "T6", "off_palette": True,
         "legibility": "declared"}]}))
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "p",
             "-o", tmp_path / "p.kicad_mod", "--tone-map", tmap,
             "--palette-mask", "purple"])
    assert r.returncode == 2 and "PROVISIONAL" in r.stderr, r.stderr
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "p",
             "-o", tmp_path / "p.kicad_mod", "--tone-map", tmap,
             "--palette-mask", "purple", "--allow-provisional"])
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# 7. the dropped-tone guard is area-relative
# ---------------------------------------------------------------------------

def test_dropped_tone_guard_is_area_relative():
    """CATCHES: a build refused over antialias residue, and a build that ships
    with a whole region missing. The 181-px / 0.03 % T3 speck that refused
    mfb_lockup_3tone must WARN; a 0.6 % tone must FAIL."""
    import build_library as bl

    class A:
        max_dropped_pct = 1.0

    def result(share_pct):
        piece = bl.Piece(Path("x.png"), 20.0, "x", "auto", [], None, [])
        r = bl.Result(piece=piece)
        r.polys = 5
        r.opaque_px = 1_000_000
        r.ink_mm2 = 100.0
        r.dropped_tones = [{"tone": "T3", "px": int(share_pct * 10_000),
                            "tone_total_px": int(share_pct * 10_000),
                            "tone_lost_entirely": True, "regions_dropped": 1,
                            "mm2": 0.0}]
        bl._guard(r, A())
        return r

    speck = result(0.0181)          # 181 px of 1,000,000
    assert not speck.problems, speck.problems
    assert any("tone lost entirely" in w for w in speck.warnings), speck.warnings

    region = result(0.6)
    assert any("TONE LOST ENTIRELY" in p for p in region.problems), region.problems


def test_speck_budget_says_it_reads_the_emitter():
    """The rename is not cosmetic. A check that reads `area_dropped` out of the
    emitter's own report is the emitter's opinion of itself, and the message has
    to say so or somebody will read it as a fidelity number."""
    import build_library as bl

    class A:
        max_dropped_pct = 0.001
    piece = bl.Piece(Path("x.png"), 20.0, "x", "auto", [], None, [])
    r = bl.Result(piece=piece)
    r.polys = 5
    r.ink_mm2 = 100.0
    r.dropped_mm2 = 50.0
    r.dropped_pct = 50.0
    bl._guard(r, A())
    msg = " ".join(r.problems)
    assert "SPECK-REMOVAL BUDGET (emitter-reported)" in msg
    assert "not a fidelity measurement" in msg


# ---------------------------------------------------------------------------
# 8. the tone-map digest travels with the part
# ---------------------------------------------------------------------------

def test_digest_mismatch_verify_fails(tmp_path):
    """CATCHES: a part checked against a table it was not built from. Every
    colour decision in it came from the other one."""
    src = tmp_path / "two.png"
    a = np.zeros((150, 150, 4), dtype=np.uint8)
    a[..., 3] = 255
    a[..., :3] = (255, 255, 255)
    a[20:130, 20:130, :3] = (247, 147, 26)
    Image.fromarray(a, "RGBA").save(src)
    tmap = tmp_path / "tm.json"
    body = {"mask": "black", "tones": [{"rgb": "#ffffff", "tone": "T1"},
                                       {"rgb": "#e08a1e", "tone": "T2"}]}
    tmap.write_text(json.dumps(body))
    out = tmp_path / "d.kicad_mod"
    r = run([EMIT, "--labels", src, "--width-mm", 20, "--name", "d", "-o", out,
             "--tone-map", tmap])
    assert r.returncode == 0, r.stderr
    digest = tm.ToneMap.from_dict(body).digest()
    assert f"tonemap:{digest}" in out.read_text()

    r = run([VERIFY, out, "--no-render", "--tone-map", tmap])
    assert "colourway" in r.stdout
    assert "FAIL" not in r.stdout.split("colourway")[1][:400], r.stdout

    body["tones"][1]["tone"] = "T3"                # edit the sidecar after emit
    tmap.write_text(json.dumps(body))
    r = run([VERIFY, out, "--no-render", "--tone-map", tmap])
    assert "DIFFERENT tone map" in r.stdout, r.stdout
    assert r.returncode != 0


# ---------------------------------------------------------------------------
# 9-10. bytes and determinism
# ---------------------------------------------------------------------------

@needs_corpus
def test_bytes_stable(tmp_path):
    """CATCHES the mixture-constant transfer failure: bitcoin_b_16mm went from
    7,088 B to 54,693 B when the dark-cluster tie-break constants were carried
    to a palette they were not fitted on. Declared inks are tens of units
    apart, so there is no tie to break and no blow-up to have."""
    tmap = tmp_path / "tm.json"
    tmap.write_text(json.dumps(tone_map_for(ASSETS / "bitcoin_b.svg")))
    out = tmp_path / "b.kicad_mod"
    # --no-copper-normalise: this test pins the QUANTISER's output size, and
    # the copper width normalisation legitimately adds filler polys for the
    # sub-floor antialias dither an unfiltered raw emit leaves between T1 and
    # T2 (30,687 B with it on). Off, the 7,088 B baseline still measures
    # exactly the mixture-constant behaviour it was written to catch.
    r = run([EMIT, "--labels", ASSETS / "bitcoin_b.svg", "--width-mm", 16,
             "--name", "bitcoin_b_16mm", "-o", out, "--tone-map", tmap,
             "--palette-mask", "purple", "--no-copper-normalise"])
    assert r.returncode == 0, r.stderr
    n = out.stat().st_size
    assert 7088 * 0.95 <= n <= 7088 * 1.05, n


@needs_corpus
def test_determinism(tmp_path):
    """No RNG, no clock, no set iteration anywhere in the path."""
    tmap = tmp_path / "tm.json"
    tmap.write_text(json.dumps(tone_map_for(ASSETS / "little_satoshi.png")))
    digests = []
    for i in range(2):
        out = tmp_path / f"run{i}.kicad_mod"
        r = run([EMIT, "--labels", ASSETS / "little_satoshi.png",
                 "--width-mm", 20, "--name", "satoshi_little_20mm", "-o", out,
                 "--tone-map", tmap, "--palette-mask", "purple",
                 "--allow-provisional", "--min-area-mm2", "0.02",
                 "--allow-dropped-tones"])
        assert r.returncode == 0, r.stderr
        digests.append(out.read_bytes())
    assert digests[0] == digests[1]


def test_tonemap_digest_is_order_independent():
    a = tm.ToneMap.from_dict({"mask": "p", "tones": [
        {"rgb": "#ffffff", "tone": "T1"}, {"rgb": "#000000", "tone": "T6"}]})
    b = tm.ToneMap.from_dict({"mask": "p", "tones": [
        {"rgb": "#000000", "tone": "T6"}, {"rgb": "#ffffff", "tone": "T1"}]})
    assert a.digest() == b.digest()
    c = tm.ToneMap.from_dict({"mask": "p", "tones": [
        {"rgb": "#ffffff", "tone": "T1"}, {"rgb": "#000000", "tone": "T7"}]})
    assert a.digest() != c.digest()


# ---------------------------------------------------------------------------
# 11. --propose-tones
# ---------------------------------------------------------------------------

@needs_corpus
def test_propose_tones_exit3():
    """CATCHES: a proposal that prints a table with a hole in it and exits 0."""
    r = run([BUILD, "--propose-tones", "--palette-mask", "purple",
             ASSETS / "satoshi_points.png"])
    assert r.returncode == 3, r.stdout
    assert "WHICH DRAWS NOTHING" in r.stdout
    assert 'tone = "T6"' in r.stdout
    # ...and a source with nothing wrong exits 0.
    r = run([BUILD, "--propose-tones", "--palette-mask", "purple",
             ASSETS / "bitcoin_b.svg"])
    assert r.returncode == 0, r.stdout


@needs_corpus
def test_propose_tones_writes_nothing(tmp_path):
    before = sorted(p.name for p in ASSETS.iterdir())
    run([BUILD, "--propose-tones", "--palette-mask", "purple",
         ASSETS / "bitcoin_b.svg"])
    assert sorted(p.name for p in ASSETS.iterdir()) == before


# ---------------------------------------------------------------------------
# sidecar schema
# ---------------------------------------------------------------------------

def test_sidecar_rejects_unknown_ink_key(tmp_path):
    import build_library as bl
    sc = tmp_path / "artlib.toml"
    sc.write_text('schema = 1\n["a.png"]\n'
                  'tones = [ { rgb = "#ffffff", tone = "T1", colour = "x" } ]\n')
    with pytest.raises(bl.SidecarError, match="unknown key"):
        bl.load_sidecar(sc, tmp_path, enforce=False)


def test_sidecar_rejects_unknown_tone(tmp_path):
    import build_library as bl
    sc = tmp_path / "artlib.toml"
    sc.write_text('schema = 1\n["a.png"]\n'
                  'tones = [ { rgb = "#ffffff", tone = "T9" } ]\n')
    with pytest.raises(bl.SidecarError, match="not a tone"):
        bl.load_sidecar(sc, tmp_path, enforce=False)


def test_sidecar_rejects_merge_ok_to_a_stranger(tmp_path):
    import build_library as bl
    sc = tmp_path / "artlib.toml"
    sc.write_text('schema = 1\n["a.png"]\ntones = [\n'
                  '  { rgb = "#ffffff", tone = "T1", merge_ok = ["#123456"] } ]\n')
    with pytest.raises(bl.SidecarError, match="not a declared colour"):
        bl.load_sidecar(sc, tmp_path, enforce=False)


def test_old_build_library_would_reject_a_new_sidecar():
    """The forward-compatibility statement, as a test. _check_keys hard-errors
    on an unknown key, so a build_library that predates 'tones' fails loudly
    instead of silently dropping every colour decision in the file."""
    import build_library as bl
    with pytest.raises(bl.SidecarError, match="unknown key"):
        bl._check_keys("[x]", {"tones": []}, {"name", "sizes", "min_area",
                                              "emit", "descr"}, Path("x"))


def test_ink_tone_is_reserved_in_the_sidecar():
    import build_library as bl
    with pytest.raises(bl.SidecarError, match="--ink-tone"):
        bl._check_emit_args(["--ink-tone", "T1"], "test")
