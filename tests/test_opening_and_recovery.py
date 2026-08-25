"""Issue #15 (the mask opening is the art silhouette, not the ink bbox) and
issue #20 (the source text is recoverable from the part).

Every assertion here is on EMITTED artefacts -- the fp_poly points and
property strings in the footprint body, or a .kicad_mod read back off disk --
not on a report key having been set or a function having been called. Each
test in the #15 half fails against the old bounding-box opening; each test in
the #20 half fails against a part that stores no text.
"""
import json
import pathlib
import re
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import emit_art  # noqa: E402
import microtext as M  # noqa: E402
from emit_art import ArtFp  # noqa: E402


def _mask(grid, mm_per_px=0.25, origin=(0.0, 0.0)):
    return M.ShapeMask(grid=np.asarray(grid, dtype=bool),
                       mm_per_px=mm_per_px, origin=tuple(origin),
                       source="hand-built", raster_tool="none")


_VOCAB = ("the quick brown fox jumps over a lazy dog and then some more "
          "words to make up the count").split()


def _words(n):
    return " ".join(_VOCAB[i % len(_VOCAB)] for i in range(n))


def _spec(shape, **kw):
    kw.setdefault("cap_mm", 0.8)
    kw.setdefault("tone", "T2")
    kw.setdefault("stroke_ratio", 0.125)
    kw.setdefault("floor_mm", 0.05)
    kw.setdefault("allow_truncation", True)
    kw.setdefault("text", _words(900))
    return M.MicrotextSpec(shape=shape, **kw)


def _emit(sp):
    fp = ArtFp("t")
    rep = M.emit(fp, sp)
    return fp, rep


def _emitted_polys(fp):
    """The fp_poly point lists actually written into the footprint body."""
    out = []
    for it in fp.items:
        if "fp_poly" not in it:
            continue
        pts = re.findall(r"\(xy (-?[\d.]+) (-?[\d.]+)\)", it)
        out.append([(float(x), float(y)) for x, y in pts])
    return out


# --- #15: the opening follows the silhouette --------------------------------

def _L():
    """40 x 40 mm, the upper-right 20 x 20 mm quadrant empty."""
    g = np.ones((160, 160), dtype=bool)
    g[:80, 80:] = False
    return _mask(g)


def test_shape_opening_is_the_art_silhouette_not_its_bounding_box():
    """The emitted fp_poly excludes the empty quadrant of an L.

    The old opening was the axis-aligned bounding box of every glyph quad, so
    the point (30, 10) -- bare laminate in the middle of the L's notch, far
    from any text -- sat inside it. The silhouette opening leaves it masked.
    """
    fp, rep = _emit(_spec(_L()))
    polys = _emitted_polys(fp)
    assert len(polys) == 1
    op = np.asarray(polys[0])
    assert len(op) > 4                       # a silhouette, not a rectangle
    assert not emit_art.point_in_poly((30.0, 10.0), op)   # notch stays masked
    assert emit_art.point_in_poly((10.0, 10.0), op)       # filled arm opens
    assert emit_art.point_in_poly((30.0, 30.0), op)       # both arms open
    assert rep["opening_form"] == "silhouette"


def test_every_glyph_still_sits_inside_the_opening():
    """Silhouette or not, no letterform may poke out of the opening."""
    fp, rep = _emit(_spec(_L()))
    op = np.asarray(_emitted_polys(fp)[0])
    pen = rep["stroke_mm"] / 2.0
    for q in rep["_geometry"]["ink"]:
        for pt in q:                         # ink envelope corners, pen included
            assert emit_art.point_in_poly(pt, op), \
                f"ink corner {pt} outside the mask opening (pen {pen})"


def test_the_opening_clears_the_ink_by_exactly_the_asked_for_bleed():
    """The flow reserves the half-pen INSIDE each span, so the span union
    grown by the bleed leaves exactly the asked-for clearance where a glyph
    fills its span to the edge -- measured 0.15000 on every run, and it must
    never come out under the bleed anywhere.
    """
    bleed = 0.15
    fp, rep = _emit(_spec(_L(), mask_bleed_mm=bleed))
    op = _emitted_polys(fp)[0]
    edges = [(op[k], op[(k + 1) % len(op)]) for k in range(len(op))]
    worst = 1e9
    for q in rep["_geometry"]["ink"]:        # ink envelope: quad + half pen
        for k in range(len(q)):
            a, b = q[k], q[(k + 1) % len(q)]
            for c, d in edges:
                worst = min(worst, M._seg_dist(a, b, c, d))
    # the serialised polygon is on the writer's 1e-4 mm grid (emit_art
    # COORD_DP), so the measured clearance is the bleed to within rounding
    assert worst == pytest.approx(bleed, abs=1.5e-4)


def _B():
    """A chunky 40 x 56 mm letter B: two enclosed 20 x 12 mm counters."""
    g = np.ones((224, 160), dtype=bool)
    g[32:80, 48:128] = False                 # upper counter
    g[144:192, 48:128] = False               # lower counter
    return _mask(g)


def test_a_counter_stays_masked_on_a_real_B():
    """The enclosed holes of a B stay holes: two counters in, two holes out,
    joined by keyhole slits so KiCad's even-odd fill keeps them masked."""
    fp, rep = _emit(_spec(_B(), text=_words(2000)))
    assert rep["opening_holes"] == 2
    polys = _emitted_polys(fp)
    assert len(polys) == 1                   # one bridged outline
    op = np.asarray(polys[0])
    # counter centres: (12..32, 8..20) and (12..32, 36..48) mm
    assert not emit_art.point_in_poly((22.0, 14.0), op)   # upper counter masked
    assert not emit_art.point_in_poly((22.0, 42.0), op)   # lower counter masked
    assert emit_art.point_in_poly((6.0, 28.0), op)        # the spine opens
    assert emit_art.point_in_poly((22.0, 28.0), op)       # the middle bar opens


def _lobes(gap_px, mm_per_px):
    """Two 80-px lobes side by side, `gap_px` empty columns between."""
    cols = 80 + gap_px + 80
    g = np.zeros((100, cols), dtype=bool)
    g[:, :80] = True
    g[:, 80 + gap_px:] = True
    return _mask(g, mm_per_px=mm_per_px)


def test_two_lobes_closing_under_the_dam_refuse():
    """Lobes 0.36 mm apart, bleed 0.15: the mask web between the two opening
    edges measures 0.060 mm against the palette's 0.10 mm dam. A web that
    thin washes away and the lobes merge with an edge nobody drew, so the
    emit refuses. The old bounding-box opening papered straight over this."""
    sp = _spec(_lobes(2, 0.18))
    with pytest.raises(M.MicrotextRefused) as e:
        _emit(sp)
    msg = str(e.value)
    assert "0.060 mm web of mask" in msg
    assert "0.10 mm mask dam" in msg


def test_two_well_separated_lobes_are_two_openings():
    """6 mm apart the mask web is legal, and each lobe gets its own opening
    -- the old code emitted ONE rectangle across both and the gap."""
    fp, rep = _emit(_spec(_lobes(24, 0.25)))
    polys = _emitted_polys(fp)
    assert len(polys) == 2
    assert rep["openings"] == 2
    # the mask between them stays masked
    mid = (80 * 0.25 + 3.0, 12.5)
    for op in polys:
        assert not emit_art.point_in_poly(mid, np.asarray(op))
    assert rep["mask_corridor_mm"] is None or rep["mask_corridor_mm"] >= 0.10


def test_region_mode_still_cuts_one_block_rectangle():
    """Region mode is untouched: a region IS a rectangle."""
    sp = M.MicrotextSpec(text="reckless", cap_mm=0.8, tone="T2",
                         region=(0.0, 0.0, 30.0, 10.0),
                         stroke_ratio=0.125, floor_mm=0.05)
    fp, rep = _emit(sp)
    polys = _emitted_polys(fp)
    assert len(polys) == 1 and len(polys[0]) == 4
    assert rep["opening_form"] == "block"


# --- #20: the text travels in the part --------------------------------------

def test_the_placed_text_is_stored_as_footprint_properties():
    """The author's text, verbatim and selectable, in a KiCad property --
    parsed back out of the serialised footprint, not out of the report."""
    sp = _spec(_L(), text=_words(120), allow_truncation=False)
    fp, rep = _emit(sp)
    node = M._sexpr_parse(fp.dumps())
    props = {it[1]: it[2] for it in node[1:]
             if isinstance(it, list) and it and it[0] == "property"}
    assert props["Microtext"] == sp.text
    placed = props["MicrotextPlaced"].split("\n")
    assert placed == [r.text for r in
                      M.place(sp, M.check(sp))[0]]
    # the placed form is the walkable one
    assert M.recover_text(sp.text, placed)["ok"]


def test_the_recipe_property_carries_the_regeneration_inputs():
    sp = _spec(_L(), text=_words(120), allow_truncation=False,
               tracking_em=1 / 21, source_path="examples/x.txt")
    fp, _ = _emit(sp)
    node = M._sexpr_parse(fp.dumps())
    props = {it[1]: it[2] for it in node[1:]
             if isinstance(it, list) and it and it[0] == "property"}
    r = json.loads(props["MicrotextRecipe"])
    assert r["mode"] == "shape"
    assert r["cap_mm"] == pytest.approx(0.8)
    assert r["stroke_ratio"] == pytest.approx(0.125)
    assert r["tracking_em"] == pytest.approx(1 / 21)
    assert r["text_file"] == "examples/x.txt"
    assert r["shape"] == "hand-built"
    assert r["hyphenate"] is False
    assert r["fab"] is None and r["floor_mm"] == pytest.approx(0.05)


def test_an_inserted_hyphen_stores_both_forms():
    """The author's text and the board's text are BOTH on the part, and they
    differ by exactly the declared hyphens -- only the board form matches
    the geometry."""
    g = np.ones((320, 26), dtype=bool)       # 6.5 mm wide, 80 mm tall
    sp = _spec(_mask(g), text="an extraordinarily long consideration of it",
               hyphenate=True, hyphen_min=3, allow_truncation=True)
    fp, rep = _emit(sp)
    assert rep["inserted_hyphens"], "setup: no hyphen was inserted"
    node = M._sexpr_parse(fp.dumps())
    props = {it[1]: it[2] for it in node[1:]
             if isinstance(it, list) and it and it[0] == "property"}
    board = props["MicrotextPlaced"].replace("\n", "")
    assert props["Microtext"] == sp.text            # the author's form
    assert board != sp.text.replace(" ", "")        # the board's differs...
    r = json.loads(props["MicrotextRecipe"])
    ins = r["inserted_hyphens"]
    assert len(ins) == len(rep["inserted_hyphens"])
    # ...by exactly the declared hyphens, provable from the part alone
    walk = M.recover_text(props["Microtext"],
                          props["MicrotextPlaced"].split("\n"),
                          inserted=len(ins))
    assert walk["ok"] and walk["inserted_found"] == len(ins)
    for h in ins:
        assert h["word"] in sp.text                 # what the author wrote
        assert "-" in h["as_set"]                   # what the board carries


def _write(tmp_path, sp, name="rt"):
    fp = ArtFp(name)
    rep = M.emit(fp, sp)
    p = tmp_path / f"{name}.kicad_mod"
    p.write_text(fp.dumps(), encoding="utf-8")
    return p, rep


def test_recovery_round_trips_from_the_kicad_mod(tmp_path):
    """Emit to disk, read back with nothing but the file: the walk is INTACT
    and the recovered text is the source."""
    src = _words(140)
    for name, kw in (("plain", {}), ("tracked", {"tracking_em": 1 / 21})):
        sp = _spec(_mask(np.ones((160, 160), dtype=bool)),
                   text=src, allow_truncation=False, **kw)
        p, rep = _write(tmp_path, sp, name)
        rec = M.recover_from_part(p)
        it = rec["integrity"]
        assert it is not None and it["ok"], (name, it)
        assert it["truncated"] == 0
        assert rec["text"] == M._normalise(src)
        assert rec["glyphs"] == rep["fp_text"]


def test_recovery_catches_a_glyph_edited_after_emit(tmp_path):
    """The walk has teeth from the artefact side too: change one character of
    one fp_text on disk and the recovery says DIVERGED, not 99.9%."""
    sp = _spec(_mask(np.ones((160, 160), dtype=bool)),
               text=_words(140), allow_truncation=False, tracking_em=1 / 21)
    p, _ = _write(tmp_path, sp, "tampered")
    body = p.read_text(encoding="utf-8")
    tampered = body.replace('(fp_text user "q"', '(fp_text user "z"', 1)
    assert tampered != body, "setup: no glyph to tamper with"
    p.write_text(tampered, encoding="utf-8")
    it = M.recover_from_part(p)["integrity"]
    assert it is not None and not it["ok"]
    assert it["reason"] == "diverged"


def test_recover_cli_round_trips_and_fails_loud(tmp_path, capsys):
    sp = _spec(_mask(np.ones((160, 160), dtype=bool)),
               text=_words(140), allow_truncation=False)
    p, _ = _write(tmp_path, sp, "cli")
    assert M.main(["--recover", str(p)]) == 0
    out = capsys.readouterr()
    assert M._normalise(sp.text) in out.out
    assert "INTACT" in out.err

    body = p.read_text(encoding="utf-8")
    p.write_text(body.replace('(fp_text user "quick', '(fp_text user "quack',
                              1), encoding="utf-8")
    assert M.main(["--recover", str(p)]) == 1
    assert "DIVERGED" in capsys.readouterr().err


def test_parts_emitted_before_issue_20_still_recover_unverified(tmp_path):
    """A pre-#20 part carries no property: recovery still reads the geometry
    and says plainly that it is unverified, rather than refusing."""
    sp = _spec(_mask(np.ones((160, 160), dtype=bool)),
               text=_words(140), allow_truncation=False)
    fp = ArtFp("old")
    M.emit(fp, sp)
    fp.items = [it for it in fp.items
                if not it.lstrip().startswith("(property")]
    p = tmp_path / "old.kicad_mod"
    p.write_text(fp.dumps(), encoding="utf-8")
    rec = M.recover_from_part(p)
    assert rec["integrity"] is None and not rec["source_property"]
    assert rec["text"] == M._normalise(sp.text)
