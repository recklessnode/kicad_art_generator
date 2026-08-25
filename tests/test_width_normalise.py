"""Sub-floor ink WIDTH normalisation (the dual of the void fill).

CATCHES the class the board-level ink check found on coupon_alpha,
2026-08-24, after the void fill landed: ink whose inscribed width is below
the floor at a SHORT waist. Three real witnesses, all in
satoshi_points_50mm:

  * F.Cu 0.0207 mm -- a filled hair channel BETWEEN two kept voids: the
    void filler's collar grows into copper only, so where the lost bare ran
    between two legal voids the fill IS a sub-floor copper web;
  * F.SilkS 0.0990 and 0.1401 mm -- waists drawn in the traced silk art,
    invisible to the convex-hull min-feature caliper (it reported 0.7978 mm
    over the same poly).

Morphological opening cannot see a waist shorter than the floor (the
dilation half re-covers it from the fat funnels on either side), so the
measurement is verify_art's: boundary pairs across the ink, contour-adjacent
pairs excluded. These tests pin the scan, the repair, its guards, and the
opt-outs.
"""

import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import emit_art  # noqa: E402

shapely = pytest.importorskip("shapely")
from shapely.geometry import Polygon, box                # noqa: E402
from shapely.ops import unary_union                      # noqa: E402


def _u(*polys):
    return unary_union([Polygon(p).buffer(0) for p in polys])


# --- the scan ---------------------------------------------------------------

def test_scan_sees_a_short_waist_opening_cannot():
    # Dumbbell: two 2x2 lobes joined by a 0.05-wide, 0.2-long neck.
    # Opening at floor/2 = 0.05 re-covers the neck (it is shorter than the
    # reach of the dilation from either lobe is not -- 0.2 > 0.1 -- so make
    # the neck genuinely short: 0.08 long).
    lobes = _u([(0, 0), (2, 0), (2, 2), (0, 2)],
               [(2.08, 0), (4.08, 0), (4.08, 2), (2.08, 2)],
               [(2, 0.975), (2.08, 0.975), (2.08, 1.025), (2, 1.025)])
    sites, capped = emit_art._boundary_width_sites(lobes, 0.1)
    assert not capped
    assert sites, "the 0.05 mm neck must be found"
    assert min(d for d, _p1, _p2 in sites) == pytest.approx(0.05, abs=0.005)


def test_scan_is_silent_on_a_legal_waist():
    lobes = _u([(0, 0), (2, 0), (2, 2), (0, 2)],
               [(2.08, 0), (4.08, 0), (4.08, 2), (2.08, 2)],
               [(2, 0.9), (2.08, 0.9), (2.08, 1.1), (2, 1.1)])  # 0.2 wide
    sites, capped = emit_art._boundary_width_sites(lobes, 0.1)
    assert not capped
    assert not sites, sites


def test_scan_does_not_flag_a_feature_drawn_at_the_floor():
    """Microtext strokes are drawn at exactly the floor; float dust off a
    subtraction must not turn them into witnesses."""
    bar = _u([(0, 0), (5, 0), (5, 0.1), (0, 0.1)])       # exactly 0.1 wide
    sites, capped = emit_art._boundary_width_sites(bar, 0.1)
    assert not capped
    assert not sites, sites


# --- the repair -------------------------------------------------------------

def test_repair_pads_a_web_between_two_voids():
    """A copper sheet with two fat voids separated by a 0.04 mm web -- the
    satoshi_points filled-channel geometry, minus the artwork."""
    sheet = box(0, 0, 6, 6)
    v1 = box(2.00, 2.0, 2.98, 3.0)
    v2 = box(3.02, 2.0, 4.00, 3.0)
    u = sheet.difference(v1).difference(v2)
    r = 0.05
    frame = box(-1, -1, 7, 7)
    bare = frame.difference(u)
    kept = bare.buffer(-r, quad_segs=32).buffer(r, quad_segs=32)
    kept_voids = [k for k in
                  (kept.geoms if kept.geom_type.startswith("Multi")
                   else [kept])
                  if not k.intersects(frame.exterior)]
    assert len(kept_voids) == 2
    adds, stats = emit_art._repair_subfloor_width(u, 0.1,
                                                  kept_voids=kept_voids)
    assert stats["width_padded"] >= 1, stats
    assert not stats["width_left"], stats
    u2 = u.union(adds)
    sites, _ = emit_art._boundary_width_sites(u2, 0.1)
    assert not sites, "the web must be at or above the floor after padding"
    # and both voids must still be fabricable
    bare2 = frame.difference(u2)
    kept2 = bare2.buffer(-r, quad_segs=32).buffer(r, quad_segs=32)
    voids2 = [k for k in
              (kept2.geoms if kept2.geom_type.startswith("Multi")
               else [kept2])
              if not k.intersects(frame.exterior)]
    assert len(voids2) == 2, "padding must not fill or merge the legal voids"


def test_repair_withholds_a_pad_that_would_starve_a_void():
    """A floor-adjacent void flanked by TWO sub-floor webs: the two pad
    zones merge across it, and applying the merged pad would fill the legal
    void outright. The pad must be withheld and the site reported, not
    hidden -- physically hopeless geometry is verify_art's to fail, not the
    repair's to bury."""
    sheet = box(0, 0, 6, 6)
    v1 = box(2.00, 2.0, 2.90, 3.0)                       # big void
    v2 = box(2.94, 2.35, 3.07, 2.65)                     # 0.13 x 0.30 void
    v3 = box(3.11, 2.0, 4.00, 3.0)                       # big void
    u = sheet.difference(v1).difference(v2).difference(v3)
    r = 0.05
    frame = box(-1, -1, 7, 7)
    bare = frame.difference(u)
    kept = bare.buffer(-r, quad_segs=32).buffer(r, quad_segs=32)
    kept_voids = [k for k in
                  (kept.geoms if kept.geom_type.startswith("Multi")
                   else [kept])
                  if not k.intersects(frame.exterior)]
    assert len(kept_voids) == 3
    adds, stats = emit_art._repair_subfloor_width(u, 0.1,
                                                  kept_voids=kept_voids)
    assert stats["width_left"], "the withheld site must be reported"
    # whatever was padded elsewhere, the small void must survive fabricable
    u2 = u.union(adds)
    bare2 = frame.difference(u2)
    kept2 = bare2.buffer(-r, quad_segs=32).buffer(r, quad_segs=32)
    voids2 = [k for k in
              (kept2.geoms if kept2.geom_type.startswith("Multi")
               else [kept2])
              if not k.intersects(frame.exterior)]
    assert len(voids2) == 3, "no pad may fill or merge a legal void"


def test_near_sites_are_padded_as_one():
    """Two waists within a floor of each other must not become two pads
    with a brand-new sub-floor gap between them (measured 0.099 mm on
    satoshi_points_28mm silk, first attempt)."""
    # one bar with two 0.05-wide waists 0.09 apart
    bar = _u([(0, 0), (5, 0), (5, 1), (0, 1)])
    n1 = box(2.00, -0.5, 2.04, 0.475).union(box(2.00, 0.525, 2.04, 1.5))
    n2 = box(2.13, -0.5, 2.17, 0.475).union(box(2.13, 0.525, 2.17, 1.5))
    u = bar.difference(n1).difference(n2).buffer(0)
    adds, stats = emit_art._repair_subfloor_width(u, 0.1)
    u2 = u.union(adds)
    sites, _ = emit_art._boundary_width_sites(u2, 0.1)
    assert not sites, "no residual sub-floor width after padding"
    # the pads AS EMITTED (with the collar grown into the existing ink,
    # exactly as both emission paths apply it) must not stand a sub-floor
    # gap apart -- that gap was the measured 0.099 mm defect of the first
    # attempt
    coll = adds.union(adds.buffer(0.1, quad_segs=8)
                      .intersection(u)).buffer(0)
    parts = (list(coll.geoms) if coll.geom_type.startswith("Multi")
             else [coll])
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            assert not (1e-9 < a.distance(b) < 0.1), \
                "two emitted pads stand a sub-floor gap apart"


# --- silk, end to end through emit ------------------------------------------

def _silk_waist_labels():
    """One silk tone (T1) drawn as a bar with a sub-floor waist.

    80 px at 8 mm is 0.1 mm/px: the bar is 8 px = 0.8 mm tall with a 1-px
    = 0.1 mm waist -- under the 0.15 mm silk floor, over the tracer's
    resolution.
    """
    n = 80
    labels = np.full((n, n), -1, dtype=np.int64)
    labels[36:44, 8:72] = 0                              # T1 bar
    labels[36:40, 38:42] = -1                            # notch from above
    labels[41:44, 38:42] = -1                            # notch from below
    # leaves rows 40 only: a 0.1 mm waist at x ~ 3.8-4.2 mm
    return labels, ["T1"]


def test_silk_waist_is_padded():
    labels, tones = _silk_waist_labels()
    text, rep = emit_art.emit_detailed(labels, tones, 8.0, "silk_waist",
                                       min_area_mm2=0.0, gap_audit=False,
                                       tolerance_mm=0.005)
    sn = rep["silk_normalise"]["layers"]["F.SilkS"]
    assert sn["pads"] > 0, rep["silk_normalise"]
    silk = []
    for m in re.finditer(
            r"\(fp_poly \(pts (.*?)\) \(stroke \(width 0\) \(type solid\)\)"
            r" \(fill solid\) \(layer \"F\.SilkS\"\)", text):
        pts = [(float(a), float(b)) for a, b in
               re.findall(r"\(xy (-?[\d.]+) (-?[\d.]+)\)", m.group(1))]
        silk.append(Polygon(pts).buffer(0))
    u = unary_union(silk)
    sites, capped = emit_art._boundary_width_sites(u, 0.15)
    assert not capped
    assert not sites, ("sub-floor silk width survived the pad: %s"
                       % sorted(d for d, _a, _b in sites)[:5])


def test_silk_opt_out_leaves_the_waist():
    labels, tones = _silk_waist_labels()
    text, rep = emit_art.emit_detailed(labels, tones, 8.0, "silk_waist",
                                       min_area_mm2=0.0, gap_audit=False,
                                       tolerance_mm=0.005,
                                       silk_normalise=False)
    assert rep["silk_normalise"] is None
    silk = []
    for m in re.finditer(
            r"\(fp_poly \(pts (.*?)\) \(stroke \(width 0\) \(type solid\)\)"
            r" \(fill solid\) \(layer \"F\.SilkS\"\)", text):
        pts = [(float(a), float(b)) for a, b in
               re.findall(r"\(xy (-?[\d.]+) (-?[\d.]+)\)", m.group(1))]
        silk.append(Polygon(pts).buffer(0))
    sites, _ = emit_art._boundary_width_sites(unary_union(silk), 0.15)
    assert sites, "the un-normalised emit was expected to carry the waist"
