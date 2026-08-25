"""Copper width normalisation (emit_art._normalise_copper_voids).

CATCHES the sub-floor stipple failure measured 2026-08-24 on
satoshi_points_50mm: a one-pixel non-copper dither fringe along the boundary
BETWEEN two copper tones is a hole of neither tone's trace, so no min-area
value can remove it, and below the copper floor it cannot etch -- the union
of the emitted copper carries enclosed bare voids the fabricated panel will
not have. The emitter now fills those at emit time; these tests pin both the
filling and the opt-out.
"""

import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import emit_art  # noqa: E402

shapely = pytest.importorskip("shapely")
from shapely.geometry import Polygon, box          # noqa: E402
from shapely.ops import unary_union               # noqa: E402

POLY_RE = re.compile(
    r"\(fp_poly \(pts (.*?)\) \(stroke \(width 0\) \(type solid\)\)"
    r" \(fill solid\) \(layer \"F\.Cu\"\)")


def _cu_union(text):
    polys = []
    for m in POLY_RE.finditer(text):
        pts = [(float(a), float(b)) for a, b in
               re.findall(r"\(xy (-?[\d.]+) (-?[\d.]+)\)", m.group(1))]
        polys.append(Polygon(pts).buffer(0))
    return unary_union(polys)


def _sub_floor_voids(u, floor=0.0889):
    """Enclosed bare voids of the copper union that vanish when the bare is
    opened at the floor -- the features the etch cannot produce."""
    minx, miny, maxx, maxy = u.bounds
    bare = box(minx - 1, miny - 1, maxx + 1, maxy + 1).difference(u)
    kept = bare.buffer(-floor / 2, quad_segs=32).buffer(floor / 2,
                                                        quad_segs=32)
    lost = bare.difference(kept).buffer(0)
    parts = list(lost.geoms) if lost.geom_type.startswith("Multi") else [lost]
    return [c for c in parts
            if c.area > 1e-9 and c.distance(kept) >= 1e-9]


def _dithered_labels():
    """Two copper tones (T2 | T6) with a one-pixel bare seam channel.

    120 px at 6 mm is 0.05 mm/px: the seam channel is bare 0.05 mm across,
    well under the 0.0889 mm copper floor, enclosed between the two copper
    fields and reaching the outside only past its caps -- the
    satoshi_points hair-channel defect, minus the artwork. Emitted with
    tolerance_mm small enough that RDP cannot flatten a 0.05 mm notch.
    """
    n = 120
    labels = np.full((n, n), 0, dtype=np.int64)          # T2 everywhere
    labels[:, n // 2:] = 1                               # right half T6
    labels[2:-2, n // 2] = -1                            # bare seam channel
    # Capped top and bottom: an uncapped seam channel runs off the edge of
    # the art and is (correctly) treated as silhouette bare, not filled.
    return labels, ["T2", "T6"]


def test_seam_dither_is_filled():
    labels, tones = _dithered_labels()
    text, rep = emit_art.emit_detailed(labels, tones, 6.0, "seam_test",
                                       min_area_mm2=0.15, gap_audit=False,
                                       tolerance_mm=0.005)
    cn = rep["copper_normalise"]["layers"]["F.Cu"]
    assert cn["fillers"] > 0, rep["copper_normalise"]
    assert cn["voids"] + cn["pinches"] > 0
    voids = _sub_floor_voids(_cu_union(text))
    assert not voids, ("%d enclosed sub-floor void(s) survived, widest "
                       "component %.4f mm2" %
                       (len(voids), max(v.area for v in voids)))


def test_opt_out_leaves_the_defect():
    labels, tones = _dithered_labels()
    text, rep = emit_art.emit_detailed(labels, tones, 6.0, "seam_test",
                                       min_area_mm2=0.15, gap_audit=False,
                                       tolerance_mm=0.005,
                                       copper_normalise=False)
    assert rep["copper_normalise"] is None
    assert _sub_floor_voids(_cu_union(text)), \
        "the un-normalised emit was expected to carry the seam voids"


def test_no_op_on_clean_geometry():
    """A clean two-tone piece with no sub-floor bare gains no fillers."""
    n = 60
    labels = np.full((n, n), 0, dtype=np.int64)
    labels[:, n // 2:] = 1                               # clean T2 | T6 seam
    text, rep = emit_art.emit_detailed(labels, ["T2", "T6"], 6.0,
                                       "clean_test", min_area_mm2=0.15,
                                       gap_audit=False)
    cn = rep["copper_normalise"]["layers"]["F.Cu"]
    assert cn["fillers"] == 0, cn
