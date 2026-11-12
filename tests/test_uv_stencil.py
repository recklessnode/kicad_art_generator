#!/usr/bin/env python3
"""The UV stencil: geometry, gutters, bands, raster, mirror, art fitting. Synthetic boards, no KiCad, no assets.

What the tests pin, and why each one matters:

  * No printable area lies closer than the gutter to a pad, silk piece or hole. A gutter that is wrong by a few hundredths of a millimetre is
    invisible in a preview and is exactly what the experiment this tool exists for would then measure instead of the printer.
  * The raster is transparent over every pad at every DPI tried, and a pixel is a known size. The file is meant to be printed at 100%.
  * Bands cut each part of the board with its own gutter, left to right as seen; the back side is mirrored, so "left" is what the person
    looking at that face sees.
  * Transparent pixels are white, edges are hard, and the DPI survives a round trip through the PNG.

The pcbnew reading (tools/uv_extract.py) cannot be tested without KiCad; it is verified by measurement on a real board.

Run:  python3 tests/test_uv_stencil.py       (or under pytest)
"""
from __future__ import annotations

import io
import pathlib
import sys

import numpy as np
from PIL import Image
from shapely.geometry import Point, box

_TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import uv_stencil as uv                                    # noqa: E402


def ring(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def board_dict(side="F"):
    """A 40 x 30 mm board: a pad at (10..12, 14..16), silk at (22..28, 4..6), a 2 mm hole at (30, 22), a courtyard round the pad."""
    return dict(format="uv-geometry/1", side=side, board=dict(file="synthetic.kicad_pcb"),
                outline=[dict(ring=ring(0, 0, 40, 30), holes=[])],
                openings=[dict(ring=ring(10, 14, 12, 16), holes=[])],
                silk=[dict(ring=ring(22, 4, 28, 6), holes=[])],
                holes=[], via_holes=[dict(x=30, y=22, d=2.0)],
                courtyards=[dict(ring=ring(8, 12, 14, 18), holes=[])],
                counts=dict(openings=1, silk=1, courtyards=1, vias=1, vias_untented=0))


def geometry(side="F"):
    return uv.load_geometry(board_dict(side))


NO_OPEN = dict(min_feature=0.0)


# ------------------------------------------------------------------------ the stencil region
def test_nothing_printable_within_the_gutter_of_a_keepout():
    g = geometry()
    for gutter in (0.05, 0.2, 0.5):
        region = uv.printable_region(g, uv.Params(gutter=gutter, **NO_OPEN))
        for name, kept in (("pad", g.openings), ("silk", g.silk), ("hole", g.holes)):
            assert region.distance(kept) >= gutter - 1e-9, (name, gutter, region.distance(kept))


def test_the_gutter_is_tight_not_generous():
    """The region must come right up to the gutter, not stop well short of it."""
    g = geometry()
    region = uv.printable_region(g, uv.Params(gutter=0.2, **NO_OPEN))
    assert 0.2 - 1e-9 <= region.distance(g.openings) <= 0.2 * 1.005 + 1e-9       # a circumscribed offset: never near, and under 0.5% far


def test_edge_margin_keeps_ink_off_the_board_edge():
    g = geometry()
    region = uv.printable_region(g, uv.Params(gutter=0.1, edge_margin=0.5, **NO_OPEN))
    assert region.bounds[0] >= 0.5 - 1e-6 and region.bounds[1] >= 0.5 - 1e-6
    assert region.bounds[2] <= 40 - 0.5 + 1e-6 and region.bounds[3] <= 30 - 0.5 + 1e-6


def test_courtyards_mode_keeps_art_from_under_the_parts():
    g = geometry()
    pads = uv.printable_region(g, uv.Params(keepout="pads", gutter=0.2, **NO_OPEN))
    courts = uv.printable_region(g, uv.Params(keepout="courtyards", gutter=0.2, **NO_OPEN))
    spot = Point(8.5, 13)                                  # inside the courtyard, away from the pad
    assert pads.contains(spot) and not courts.contains(spot)
    assert courts.distance(g.courtyards) >= 0.2 - 1e-9


def test_a_per_kind_gutter_overrides_the_general_one():
    g = geometry()
    region = uv.printable_region(g, uv.Params(gutter=0.1, silk_gutter=0.6, **NO_OPEN))
    assert region.distance(g.silk) >= 0.6 - 1e-9
    assert region.distance(g.openings) < 0.2


def test_a_strip_narrower_than_min_feature_is_dropped_and_a_wide_one_kept():
    d = board_dict()
    d["openings"] = [dict(ring=ring(10, 14, 12, 16), holes=[]), dict(ring=ring(12.5, 14, 14.5, 16), holes=[])]     # 0.5 mm apart
    g = uv.load_geometry(d)
    strip = Point(12.25, 15)                                  # between the pads: 0.5 - 2 x 0.2 = 0.1 mm wide once the gutters are cut
    assert uv.printable_region(g, uv.Params(gutter=0.2, min_feature=0.0)).contains(strip)
    assert not uv.printable_region(g, uv.Params(gutter=0.2, min_feature=0.3)).contains(strip)
    assert uv.printable_region(g, uv.Params(gutter=0.2, min_feature=0.3)).contains(Point(5, 5))


# ------------------------------------------------------------------------ bands
def test_bands_split_the_board_left_to_right_with_their_own_gutter():
    g = geometry()
    p = uv.Params(bands=(0.1, 0.5), **NO_OPEN)
    region, bands = uv.banded_region(g, p)
    assert [b["gutter"] for b in bands] == [0.1, 0.5]
    assert bands[0]["x1"] == bands[1]["x0"] == 20.0
    left = region.intersection(box(0, 0, 20, 30))
    right = region.intersection(box(20, 0, 40, 30))
    assert left.distance(g.openings) >= 0.1 - 1e-9 and left.distance(g.openings) < 0.2             # the pad is in the left band
    assert right.distance(g.silk) >= 0.5 - 1e-9 and right.distance(g.holes) >= 0.5 - 1e-9          # the silk and the hole are in the right band


def test_back_side_mirrors_so_bands_read_as_seen():
    f = uv.print_frame(geometry("F"), "F")
    b = uv.print_frame(geometry("B"), "B")
    assert f.openings.bounds == (10.0, 14.0, 12.0, 16.0)
    assert b.openings.bounds == (28.0, 14.0, 30.0, 16.0)                                            # 40 - x
    assert uv.print_frame(geometry("B"), "B", mirror_back=False).openings.bounds == f.openings.bounds


def test_rotate_turns_the_board_clockwise_as_seen():
    g = uv.print_frame(geometry("F"), "F", rotate=90)
    x0, y0, x1, y1 = g.bbox
    assert abs((x1 - x0) - 30) < 1e-9 and abs((y1 - y0) - 40) < 1e-9                  # a 40 x 30 board is now 30 x 40
    c = g.openings.centroid
    assert abs(c.x - 20) < 1e-9 and abs(c.y - 24) < 1e-9, (c.x, c.y)                  # the pad was left of centre; clockwise puts it above
    assert uv.print_frame(geometry("F"), "F", rotate=360).bbox == geometry("F").bbox
    try:
        uv.print_frame(geometry("F"), "F", rotate=45)
    except ValueError:
        return
    raise AssertionError("accepted a rotation that is not a multiple of 90")


def test_a_rotated_print_has_swapped_pixel_size_and_still_clears_the_pad():
    g = geometry()
    _, mask, rep, _, _ = uv.build(g, "F", uv.Params(gutter=0.2, **NO_OPEN), 300, rotate=90)
    w, h, _ = uv.pixel_size((0, 0, 30, 40), 300)
    assert mask.shape == (h, w) and rep["rotated_clockwise"] == 90
    assert rep["checks"]["pad_samples_printed"] == 0 and rep["checks"]["keepout_samples_printed"] == 0


# ------------------------------------------------------------------------ raster
def test_a_pixel_is_a_known_size():
    w, h, ppm = uv.pixel_size((0, 0, 40, 30), 600)
    assert abs(ppm - 600 / 25.4) < 1e-9
    assert (w, h) == (int(np.ceil(40 * ppm)), int(np.ceil(30 * ppm)))


def test_raster_is_transparent_over_the_pad_and_printable_elsewhere():
    g = geometry()
    for dpi in (150, 600):
        img, mask, rep, region, _ = uv.build(g, "F", uv.Params(gutter=0.2, **NO_OPEN), dpi)
        ppm = dpi / 25.4
        at = lambda x, y: mask[int((30 - y) * ppm), int(x * ppm)]
        assert at(11, 15) == 0                                  # the pad
        assert at(10 - 0.1, 15) == 0                            # inside the gutter beside it
        assert at(5, 5) == 255                                  # open board
        assert at(30, 22) == 0                                  # the hole
        assert rep["checks"]["pad_samples_printed"] == 0 and rep["checks"]["keepout_samples_printed"] == 0


def test_the_gutter_edge_lands_where_the_geometry_says():
    """Walk along a row from the pad outwards: the first printed pixel is the gutter, to within a pixel."""
    g = geometry()
    dpi = 1200
    _, mask, _, _, _ = uv.build(g, "F", uv.Params(gutter=0.30, **NO_OPEN), dpi)
    ppm = dpi / 25.4
    row = int((30 - 15) * ppm)
    first = next(c for c in range(int(12 * ppm), mask.shape[1]) if mask[row, c] > 0)
    assert abs(first / ppm - 12.30) <= 1.5 / ppm


def test_hard_edges_only():
    _, mask, *_ = uv.build(geometry(), "F", uv.Params(gutter=0.2, **NO_OPEN), 300)
    assert set(np.unique(mask)) <= {0, 255}


# ------------------------------------------------------------------------ the art
def test_cover_fills_and_contain_leaves_a_margin():
    art = Image.new("RGBA", (100, 50), (200, 30, 30, 255))
    cover = uv.fit_art(art, (80, 80), "cover")
    contain = uv.fit_art(art, (80, 80), "contain")
    assert cover.size == contain.size == (80, 80)
    assert np.asarray(cover)[..., 3].min() == 255                                  # no transparent pixel: it filled the frame
    assert np.asarray(contain)[0, 40, 3] == 0 and np.asarray(contain)[40, 40, 3] == 255   # bars above and below, art in the middle


def test_anchor_chooses_which_part_of_the_art_survives_a_crop():
    art = Image.new("RGBA", (100, 50), (0, 0, 255, 255))
    art.paste((255, 0, 0, 255), (0, 0, 20, 50))                                    # a red strip at the left end
    assert tuple(np.asarray(uv.fit_art(art, (50, 50), "cover", "left"))[25, 2][:3]) == (255, 0, 0)
    assert tuple(np.asarray(uv.fit_art(art, (50, 50), "cover", "right"))[25, 2][:3]) == (0, 0, 255)


def test_white_to_alpha_removes_white_and_light_neutral_grey_only():
    a = np.zeros((1, 4, 4), np.uint8)
    a[0, 0] = (255, 255, 255, 255)           # white
    a[0, 1] = (225, 225, 225, 255)           # the light grey of a baked-in transparency checkerboard
    a[0, 2] = (255, 200, 200, 255)           # pale pink: not neutral
    a[0, 3] = (30, 30, 30, 255)              # dark
    out = np.asarray(uv.white_to_alpha(Image.fromarray(a), 0.85))
    assert list(out[0, :, 3]) == [0, 0, 255, 255]


def _checker(cells=8, size=40, tones=(120, 190)):
    a = np.zeros((cells * size, cells * size, 4), np.uint8)
    for r in range(cells):
        for c in range(cells):
            a[r * size:(r + 1) * size, c * size:(c + 1) * size, :3] = tones[(r + c) % 2]
    a[..., 3] = 255
    return a


def test_a_baked_in_checkerboard_is_cleared_and_the_art_inside_it_is_not():
    a = _checker()
    a[100:220, 100:220] = (200, 30, 30, 255)                       # a red square of art
    out, info = uv.remove_checkerboard(Image.fromarray(a))
    o = np.asarray(out)
    assert info is not None and info["tones"] == [120, 190]
    assert o[10, 10, 3] == 0 and o[10, 50, 3] == 0                  # both greys of the checkerboard
    assert (o[120:200, 120:200, 3] == 255).all()                     # the art survives


def test_an_image_without_a_checkerboard_is_left_alone():
    a = np.zeros((300, 300, 4), np.uint8)
    a[..., :3] = (10, 20, 80)                                        # dark blue all over: not neutral
    a[..., 3] = 255
    out, info = uv.remove_checkerboard(Image.fromarray(a))
    assert info is None and (np.asarray(out) == a).all()
    g = np.zeros((300, 300, 4), np.uint8)
    g[..., :3] = 60
    g[..., 3] = 255                                                  # one flat grey: neutral but a single tone
    assert uv.remove_checkerboard(Image.fromarray(g))[1] is None


def test_transparent_pixels_are_white_and_the_stencil_cuts_the_art():
    g = geometry()
    art = Image.new("RGBA", (400, 300), (10, 20, 30, 255))
    img, mask, *_ = uv.build(g, "F", uv.Params(gutter=0.2, **NO_OPEN), 300, art=art)
    a = np.asarray(img)
    assert (a[..., 3][mask == 0] == 0).all() and (a[..., 3][mask > 0] == 255).all()
    assert (a[..., :3][a[..., 3] == 0] == 255).all()
    assert tuple(a[(a[..., 3] == 255).nonzero()[0][0], (a[..., 3] == 255).nonzero()[1][0]][:3]) == (10, 20, 30)


def test_dpi_survives_a_png_round_trip():
    img, *_ = uv.build(geometry(), "F", uv.Params(gutter=0.2), 600, art=Image.new("RGBA", (50, 40), (1, 2, 3, 255)))
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(600, 600))
    back = Image.open(io.BytesIO(buf.getvalue()))
    assert abs(back.info["dpi"][0] - 600) < 0.05 and back.mode == "RGBA"


def test_report_is_deterministic_and_complete():
    r1 = uv.build(geometry(), "F", uv.Params(gutter=0.2), 300)[2]
    r2 = uv.build(geometry(), "F", uv.Params(gutter=0.2), 300)[2]
    assert r1 == r2
    for k in ("side", "dpi", "size_px", "mm_per_px", "board_mm", "bands", "params", "printable_share", "ink_share", "checks"):
        assert k in r1
    assert 0 < r1["printable_share"] < 1


def test_bad_parameters_are_refused():
    for bad in (uv.Params(keepout="nope"), uv.Params(gutter=-1), uv.Params(bands=(0.1, -0.2))):
        try:
            bad.check()
        except ValueError:
            continue
        raise AssertionError("accepted %r" % (bad,))


def test_the_geometry_loader_rejects_other_files():
    try:
        uv.load_geometry(dict(format="something-else"))
    except ValueError:
        return
    raise AssertionError("accepted a file that is not uv-geometry/1")


if __name__ == "__main__":
    fails = 0
    for nm, fn in sorted(globals().items()):
        if nm.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {nm}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {nm}: {e}")
    print(f"\n  {fails} failure(s)")
    sys.exit(1 if fails else 0)
