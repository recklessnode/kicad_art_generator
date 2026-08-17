"""Lone-outlier detection: catch a bad transform, do not libel a frame."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import verify_art as V


def _fp(rects, layer="F.SilkS"):
    items = []
    for (x0, y0, x1, y1) in rects:
        items.append(V.Item(kind="fp_poly", layers=[layer],
                            pts=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                            filled=True, width=0.0))
    return V.Footprint(name="t", version="20241229", generator="test", items=items)


CFG = type("C", (), {"outlier_mm": 1.0, "max_report": 20})()

ART = [(-2, -2, 2, 2), (-1, 3, 1, 4), (0, -4, 3, -3)]


def test_stray_polygon_is_flagged():
    """A polygon flung far from the art, enclosing nothing -- a bad transform."""
    fp = _fp(ART + [(40, 40, 41, 41)])
    hits = V._lone_outliers(fp, CFG)
    assert hits, "a runaway polygon must still be caught"
    assert "#3" in hits[0], hits


def test_enclosing_frame_is_not_flagged():
    """A border that contains all the other art is the art, not a stray."""
    fp = _fp([(-20, -20, 20, 20)] + ART)
    assert V._lone_outliers(fp, CFG) == []


def test_frame_present_and_stray_present_still_flags_the_stray():
    """The frame exemption must not swallow a real defect alongside it."""
    fp = _fp([(-20, -20, 20, 20)] + ART + [(200, 0, 201, 1)])
    hits = V._lone_outliers(fp, CFG)
    assert len(hits) == 1 and "#4" in hits[0], hits


def test_partial_overhang_is_still_flagged():
    """Reaching past on one side only is not enclosure."""
    fp = _fp(ART + [(-60, -1, -30, 1)])
    assert V._lone_outliers(fp, CFG), "one-sided overhang is not a frame"


def test_tiled_layout_is_quiet():
    fp = _fp([(x, 0, x + 2, 2) for x in range(0, 40, 4)])
    assert V._lone_outliers(fp, CFG) == []


def test_real_library_frames_pass_geometry():
    """The three pieces this fix was written for, if they have been rendered."""
    out = pathlib.Path(__file__).resolve().parents[1] / "output" / "RecklessArt.pretty"
    names = ["reckless_mono_20mm", "mfb_node_light_20mm", "mfb_node_full_20mm"]
    seen = 0
    for n in names:
        p = out / f"{n}.kicad_mod"
        if not p.exists():
            continue
        seen += 1
        fp = V.load_footprint(p)
        assert V._lone_outliers(fp, CFG) == [], f"{n} still reports an outlier"
    if not seen:
        import pytest
        pytest.skip("library not rendered yet")
