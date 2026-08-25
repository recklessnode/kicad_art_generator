"""Issue #17: a declared merge_ok must not ERASE a feature silently.

Every check before this one measured ink that was DRAWN. A merged ink is
drawn -- in its neighbour's colour -- so a feature drawn ONLY in the merged
colour and wholly enclosed by its merge partner could vanish while undrawn
ink read 0.0%: satoshi_points' chest S was painted gold on gold and did not
exist at any size.

EVERY TEST HERE IS LISTED WITH THE THING IT CATCHES AND THE INPUT THAT MAKES
IT FAIL, same as test_palette_tonemap.py.
"""

import json
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

import palette as pal_mod                          # noqa: E402
import tone_map as tm                              # noqa: E402

BUILD = TOOLS / "build_library.py"
ASSETS = REPO / "assets" / "normalised"
needs_corpus = pytest.mark.skipif(
    not (ASSETS.is_dir() and (ASSETS / "satoshi_points.png").is_file()),
    reason="normalised assets not present")

PAL = pal_mod.palette_for("purple", allow_provisional=True)

# Synthetic colours, nothing brand-owned: a "body gold", a "shading gold" one
# shade darker (23 weighted-Lab units apart -- same order as the real pair),
# plus white.
FIELD = "#e0a040"
SHADE = "#c08830"
WHITE = "#ffffff"


def picture(feature="enclosed"):
    """120x120 RGBA test picture: a FIELD square with a SHADE feature in it.

    feature = "enclosed"  20x20 SHADE blob wholly inside the FIELD -- the
                          chest-S situation.
              "outlined"  the same blob, but ringed by 3px of WHITE, the way
                          a feature with its own drawn outline is.
              "fringe"    no blob: a 1px SHADE halo around an inner WHITE
                          square (boundary fringe) plus three 1px specks.
    """
    a = np.zeros((120, 120, 4), dtype=np.uint8)

    def put(x0, y0, x1, y1, hx):
        r, g, b = tm._hex_to_rgb(hx)
        a[y0:y1, x0:x1] = [r, g, b, 255]

    put(10, 10, 110, 110, FIELD)
    if feature == "enclosed":
        put(40, 40, 60, 60, SHADE)
    elif feature == "outlined":
        put(37, 37, 63, 63, WHITE)
        put(40, 40, 60, 60, SHADE)
    elif feature == "fringe":
        put(69, 69, 92, 92, SHADE)      # 1px halo...
        put(70, 70, 91, 91, WHITE)      # ...around a white square
        for x, y in ((20, 20), (25, 90), (90, 25)):   # 3 enclosed specks
            put(x, y, x + 1, y + 1, SHADE)
    return Image.fromarray(a)


def tmap_for(rows):
    return tm.ToneMap.from_dict({"mask": "purple", "tones": rows})


def erasure_rows(img, rows):
    _labels, _opaque, st = tm.map_labels(img, tmap_for(rows), PAL)
    return st["merge_erasure"], st


def check(rows, img):
    """Run emit_art's tone-map gate and return its refusal list."""
    from emit_art import _check_tone_map
    tmap = tmap_for(rows)
    _labels, _opaque, st = tm.map_labels(img, tmap, PAL)
    return _check_tone_map(tmap, PAL, st, False, True)


MERGED = [{"rgb": FIELD, "tone": "T2"},
          {"rgb": SHADE, "tone": "T2", "merge_ok": [FIELD]},
          {"rgb": WHITE, "tone": "T1"}]


# ---------------------------------------------------------------------------
# the census
# ---------------------------------------------------------------------------

def test_enclosed_feature_is_measured_as_erased():
    """CATCHES: a merge that swallows a wholly-enclosed feature while every
    drawn-ness metric stays perfect.

    FAILING INPUT: a 400 px SHADE blob inside the FIELD, both declared T2
    with the merge named -- the synthetic chest S."""
    rows, st = erasure_rows(picture("enclosed"), MERGED)
    assert len(rows) == 1
    r = rows[0]
    assert r["hex"] == SHADE and r["merged_into"] == [FIELD]
    assert r["erased_px"] == 400
    assert r["erased_pct"] >= tm.MERGE_ERASED_FAIL_PCT
    assert r["components"][0]["enclosure"] == 1.0
    assert r["components"][0]["erased"]
    # and the drawn-ness numbers are exactly the blind spot: nothing dropped
    assert st["dropped_px"] == 0


def test_outlined_feature_is_not_erased():
    """CATCHES the check firing on a feature that keeps a visible edge: the
    blob's WHITE ring renders as T1, so the blob's whole drawn border is a
    tone boundary and the feature survives the merge."""
    rows, _st = erasure_rows(picture("outlined"), MERGED)
    assert len(rows) == 1
    assert rows[0]["erased_px"] == 0
    assert all(c["enclosure"] == 0.0 for c in rows[0]["components"])


def test_field_itself_is_never_the_feature():
    """The group's dominant ink is the field the others merge into; a field
    is not a feature and must not be censused as one."""
    rows, _st = erasure_rows(picture("enclosed"), MERGED)
    assert [r["hex"] for r in rows] == [SHADE]


# ---------------------------------------------------------------------------
# the refusal
# ---------------------------------------------------------------------------

def test_emit_refuses_an_erasing_merge():
    """CATCHES issue #17 itself: merge_ok alone must no longer be enough
    where the merge erases. The refusal names the numbers and both exits:
    a distinct tone, or erase_ok."""
    out = check(MERGED, picture("enclosed"))
    hits = [o for o in out if "erase_ok" in o]
    assert len(hits) == 1, out
    assert SHADE in hits[0] and "wholly" in hits[0]
    # T3 is free and legible on purple; the message must offer it
    assert "T3" in hits[0]


def test_erase_ok_is_the_sentence_that_permits_it():
    rows = [dict(MERGED[0]), dict(MERGED[1], erase_ok=True), dict(MERGED[2])]
    out = check(rows, picture("enclosed"))
    assert not [o for o in out if "erase_ok = true" in o], out


def test_fringe_and_speckle_do_not_fire():
    """CATCHES a threshold that cannot tell a feature from residue.

    FAILING INPUT: a 1px SHADE halo on the FIELD/WHITE boundary (enclosure
    below the line: half its border is T1) plus three 1px enclosed specks
    (0.003% of ink, 16x under MERGE_ERASED_FAIL_PCT)."""
    rows, _st = erasure_rows(picture("fringe"), MERGED)
    assert len(rows) == 1
    r = rows[0]
    assert r["erased_pct"] < tm.MERGE_ERASED_FAIL_PCT
    out = check(MERGED, picture("fringe"))
    assert not [o for o in out if "erase_ok" in o], out


@needs_corpus
def test_the_historical_satoshi_points_mapping_fires():
    """CATCHES: the exact shipped defect. The sidecar that merged the shading
    gold into the body gold (both T2, merge declared) painted the chest S
    invisibly; the census must measure it and the gate must refuse it.

    The colours are read off the corpus at run time -- they are third-party
    brand property and are not written down here (same policy as
    test_palette_tonemap.tone_map_for)."""
    import prep_assets
    from emit_art import _check_tone_map, crop_to_content
    img = Image.open(ASSETS / "satoshi_points.png").convert("RGBA")
    img, _ = crop_to_content(img)
    arr = np.asarray(img)
    cen = prep_assets.colour_census(arr[..., :3], arr[..., 3] >= 128, 10.0)
    legible = list(PAL.legible(allow_inner=False, allow_provisional=True))

    def nearest(crgb):
        w = tm._weighted(np.array(crgb, dtype=np.uint8))
        return min(legible, key=lambda t: float(np.linalg.norm(
            w - tm._weighted(np.array(PAL[t].rgb, dtype=np.uint8)))))

    rows, gold = [], []
    for c in cen["clusters"]:
        if c["area_fraction"] < 0.004:
            continue
        crgb = tuple(int(v) for v in c["rgb"])
        tone = nearest(crgb)
        row = {"rgb": c["hex"], "tone": tone}
        if tone == "T2":
            gold.append(c["hex"])
            if len(gold) > 1:
                row["merge_ok"] = [gold[0]]     # the historical declaration
        else:
            row["off_palette"] = True
            row["legibility"] = "declared"
        rows.append(row)
    assert len(gold) >= 2, "expected at least the two golds nearest T2"

    tmap = tm.ToneMap.from_dict({"mask": "purple", "tones": rows})
    _labels, _opaque, st = tm.map_labels(img, tmap, PAL)
    # exactly one merged colour erases: the shading gold that carries the S.
    hit = [r for r in st["merge_erasure"]
           if r["erased_pct"] >= tm.MERGE_ERASED_FAIL_PCT]
    assert len(hit) == 1, st["merge_erasure"]
    assert hit[0]["hex"] == gold[1]
    # the chest S: hundreds of pixels, several strokes, all at enclosure 1.0
    assert hit[0]["erased_px"] >= 100
    assert hit[0]["erased_pct"] >= tm.MERGE_ERASED_FAIL_PCT
    assert any(c["enclosure"] == 1.0 and c["erased"]
               for c in hit[0]["components"])
    out = _check_tone_map(tmap, PAL, st, False, True)
    assert [o for o in out if "erase_ok" in o], out


# ---------------------------------------------------------------------------
# the declaration plumbing
# ---------------------------------------------------------------------------

def test_erase_ok_roundtrips_and_digests():
    """erase_ok must survive to_dict/from_dict and be part of the identity of
    a map that sets it -- while every map that does not set it keeps the
    digest its shipped footprints already carry."""
    a = tmap_for(MERGED)
    rows = [dict(MERGED[0]), dict(MERGED[1], erase_ok=True), dict(MERGED[2])]
    b = tmap_for(rows)
    assert "e=" not in a.canonical()
    assert a.digest() != b.digest()
    c = tm.ToneMap.from_dict(b.to_dict())
    assert c.digest() == b.digest()
    assert c.by_hex(SHADE).erase_ok is True
    assert c.by_hex(FIELD).erase_ok is False


def test_sidecar_accepts_erase_ok_and_rejects_a_non_bool(tmp_path):
    import build_library as bl
    sc = tmp_path / "artlib.toml"
    sc.write_text('schema = 1\n["a.png"]\ntones = [\n'
                  '  { rgb = "#e0a040", tone = "T2" },\n'
                  '  { rgb = "#c08830", tone = "T2", '
                  'merge_ok = ["#e0a040"], erase_ok = true } ]\n')
    got = bl.load_sidecar(sc, tmp_path, enforce=False)
    (sec,), = ((s.data["tones"],) for s in got.sections)
    assert sec[1]["erase_ok"] is True
    sc.write_text('schema = 1\n["a.png"]\ntones = [\n'
                  '  { rgb = "#e0a040", tone = "T2", erase_ok = "yes" } ]\n')
    with pytest.raises(bl.SidecarError, match="erase_ok"):
        bl.load_sidecar(sc, tmp_path, enforce=False)


# ---------------------------------------------------------------------------
# --propose-tones
# ---------------------------------------------------------------------------

def test_propose_tones_does_not_offer_an_erasing_merge(tmp_path):
    """CATCHES: a paste-ready proposal containing the merge that kills the
    feature. Before this change the tool printed
    { rgb = SHADE, tone = "T2", merge_ok = [FIELD] } for exactly this input,
    with only a generic two-colours-one-tone comment beside it."""
    src = tmp_path / "s_on_a_disc.png"
    picture("enclosed").save(src)
    r = subprocess.run([sys.executable, str(BUILD), "--propose-tones",
                        "--palette-mask", "purple", str(src)],
                       capture_output=True, text=True)
    assert "moved OFF" in r.stdout, r.stdout
    assert "merge_ok" not in r.stdout, r.stdout
    # the two golds end on two different tones
    lines = [l for l in r.stdout.splitlines() if l.strip().startswith("{")]
    tones = {l.split('rgb = "')[1][:7]: l.split('tone = "')[1][:2]
             for l in lines}
    assert tones[FIELD] != tones[SHADE], r.stdout
    # nothing about this source loses picture any more -> exit 0
    assert r.returncode == 0, r.stdout + r.stderr
