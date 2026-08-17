#!/usr/bin/env python3
"""W1: the emitter. Quantised tone-label raster -> KiCad footprint.

w0_spike.py answers "which tone is this pixel?" and stops there. This is the
stage that turns that answer into geometry a fab can make.

The one thing that matters here is that regions are emitted as POLYGONS, not as
per-pixel rectangles. The April pipeline emitted rectangles and produced a
2.5 MB footprint for a single 25 mm asset; a traced outline of the same art is
two orders of magnitude smaller and is also the only form a fab CAM tool can
reason about.

Pipeline, per tone:

    binary mask
      -> marching squares            closed loops on the half-pixel grid
      -> scale to mm                 (width_mm sets the scale; height follows)
      -> Ramer-Douglas-Peucker       tolerance in MILLIMETRES, not pixels
      -> outer/hole classification   by signed area, then containment
      -> hole bridging ("fracture")  polygon-with-holes -> one simple outline
      -> fp_poly on every layer the tone's recipe names

Design decisions worth arguing with:

HOLES. KiCad's `fp_poly` carries a single `(pts ...)` list, so a polygon with a
hole cannot be written directly. The two offered options were (a) split into
several simple polygons or (b) paint the hole with the background tone on top.
(b) is impossible here: the background tone T5 is *the absence of everything*,
and silk is the topmost physical layer, so there is nothing you can draw on top
of a silk region to un-draw it. So: (a), by keyhole bridging (a.k.a. fracture) —
each hole is joined to its containing outline by a zero-width slit, producing
one self-touching but non-self-crossing outline that fills correctly under both
even-odd and non-zero winding.

That is also exactly what KiCad itself does internally: `SHAPE_POLY_SET::
Fracture()`. Verified empirically — a bridged square-with-square-hole round-
trips through `kicad-cli fp upgrade` unchanged and plots as
`fill-rule:evenodd` with the hole open, KiCad having re-derived the hole and
re-cut its own bridge in a different place.

TOLERANCE is in millimetres and defaults to 0.05 mm, because every reason to
pick a number is physical, not pixel-based:
  - it is half the 0.1 mm minimum fabricable mask/copper feature,
  - it equals the +/-0.05 mm mask registration tolerance, so geometry finer
    than this cannot be *placed* reliably even if it can be imaged, and
  - the eye resolves ~0.087 mm at 300 mm, so it is below visibility.
Because the tolerance is fixed in mm, the same artwork emitted at 12 mm keeps
far fewer vertices than at 50 mm — the small badge automatically gets the
coarser polygons, and the vertex count tracks the output size rather than the
input resolution.

Usage
    python tools/emit_art.py --labels art.png --width-mm 25 --name foo -o foo.kicad_mod
    python tools/emit_art.py --labels labels.npy --width-mm 25 --name foo -o foo.kicad_mod

`--labels` accepts a .npy of the array `w0_spike.quantise()` returns, or any
image (PNG/JPG/SVG), in which case it is quantised here with that same
function. Nothing about the quantiser is reimplemented.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import uuid

import numpy as np
from PIL import Image

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from w0_spike import (TONES, MIX_RATIO, MIX_SPLIT,   # noqa: E402
                      composite, quantise)
from coupon_ladders import Fp                        # noqa: E402
from coupon_blocks import TONE_RECIPE                # noqa: E402

# --- palette wiring --------------------------------------------------------
# Single source of truth for the layer recipes is coupon_blocks.TONE_RECIPE,
# which is itself a transcription of the table in docs/pcb-palette.md. Its keys
# are "T1_silk" style; strip to the tone id.
TONE_LAYERS = {k.split("_", 1)[0]: tuple(v) for k, v in TONE_RECIPE.items()}

BACKGROUND = "T5"          # draws nothing, by definition. See docs/pcb-palette.md.
DEFAULT_TOLERANCE_MM = 0.05
COORD_DP = 4

# Minimum fabricable feature per layer, from docs/pcb-palette.md. Used only to
# flag polygons that are too small to make -- never to silently delete them.
MIN_FEATURE_MM = {
    "F.SilkS": 0.15,
    "B.SilkS": 0.15,
    "F.Mask": 0.10,
    "B.Mask": 0.10,
    "F.Cu": 0.10,
    "B.Cu": 0.10,
    "In1.Cu": 0.30,        # buried tones blur through 0.1 mm prepreg
    "In2.Cu": 0.30,
}

APRIL_BASELINE_BYTES = 2_500_000     # the 2.5 MB file this rebuild exists to beat


class ToneDropped(RuntimeError):
    """A tone present in the input produced no geometry. Never acceptable."""


# --- marching squares ------------------------------------------------------
# Cell corners TL=8 TR=4 BR=2 BL=1. Midpoints indexed T=0 R=1 B=2 L=3.
# Directed so the FILLED side is always on the left of travel (image coords,
# y down). That makes outer loops negative-area and hole loops positive, which
# is how they are told apart below, and it makes every midpoint appear exactly
# once as a segment start -- so the loops stitch with a plain dict.
#
# Cases 5 and 10 are the saddles. Resolved as 8-connected FOREGROUND (the two
# diagonal filled corners join), which is right for artwork: a diagonal run of
# pixels is one stroke, not a string of islands. Background is therefore
# 4-connected, so holes never leak out through a diagonal.
_MS = {
    1:  ((2, 3),),
    2:  ((1, 2),),
    3:  ((1, 3),),
    4:  ((0, 1),),
    5:  ((0, 3), (2, 1)),
    6:  ((0, 2),),
    7:  ((0, 3),),
    8:  ((3, 0),),
    9:  ((2, 0),),
    10: ((1, 0), (3, 2)),
    11: ((1, 0),),
    12: ((3, 1),),
    13: ((2, 1),),
    14: ((3, 2),),
}


def trace_contours(mask):
    """Marching squares -> list of closed loops, (N,2) float arrays.

    Coordinates are pixel-centre space: pixel (row r, col c) sits at (x=c, y=r),
    and contour vertices land on half-pixel edge midpoints.
    """
    m = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), dtype=np.uint8)
    m[1:-1, 1:-1] = np.asarray(mask, dtype=bool).astype(np.uint8)

    tl, tr = m[:-1, :-1], m[:-1, 1:]
    br, bl = m[1:, 1:], m[1:, :-1]
    case = (tl << 3) | (tr << 2) | (br << 1) | bl

    stride = 2 * m.shape[1] + 4          # doubled-coordinate row stride
    succ: dict[int, int] = {}

    for cv, segs in _MS.items():
        rr, cc = np.nonzero(case == cv)
        if rr.size == 0:
            continue
        r2 = rr.astype(np.int64) << 1
        c2 = cc.astype(np.int64) << 1
        mid = (
            (c2 + 1, r2),        # T
            (c2 + 2, r2 + 1),    # R
            (c2 + 1, r2 + 2),    # B
            (c2, r2 + 1),        # L
        )
        for a, b in segs:
            ax, ay = mid[a]
            bx, by = mid[b]
            succ.update(zip((ay * stride + ax).tolist(),
                            (by * stride + bx).tolist()))

    loops = []
    while succ:
        start = next(iter(succ))
        k, keys = start, []
        while True:
            nk = succ.pop(k, None)
            if nk is None:
                break
            keys.append(k)
            k = nk
            if k == start:
                break
        if len(keys) < 3:
            continue
        ka = np.asarray(keys, dtype=np.int64)
        y2, x2 = np.divmod(ka, stride)
        loops.append(np.stack([x2 * 0.5 - 1.0, y2 * 0.5 - 1.0], axis=1))
    return loops


# --- geometry helpers ------------------------------------------------------
def signed_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def point_in_poly(pt, poly):
    x, y = float(pt[0]), float(pt[1])
    ax, ay = poly[:, 0], poly[:, 1]
    bx, by = np.roll(ax, -1), np.roll(ay, -1)
    straddle = (ay > y) != (by > y)
    if not straddle.any():
        return False
    dy = np.where(straddle, by - ay, 1.0)
    xi = ax + (y - ay) * (bx - ax) / dy
    return bool(np.count_nonzero(straddle & (xi > x)) & 1)


def _rdp_open(pts, eps):
    """Ramer-Douglas-Peucker on an open polyline. Iterative; keeps ends."""
    n = len(pts)
    if n < 3:
        return np.ones(n, dtype=bool)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        seg = pts[i + 1:j]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0.0:
            d = np.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1])
        else:
            d = np.abs(dx * (a[1] - seg[:, 1]) - (a[0] - seg[:, 0]) * dy) / length
        k = int(np.argmax(d))
        if d[k] > eps:
            mid = i + 1 + k
            keep[mid] = True
            stack.append((i, mid))
            stack.append((mid, j))
    return keep


def rdp_closed(pts, eps):
    """RDP on a closed loop. Anchored on the two mutually most distant-ish
    points so the result does not depend on where the tracer happened to start.
    Falls back to the original loop rather than collapsing it -- a tiny loop is
    still image content and must not vanish here."""
    n = len(pts)
    if n < 4 or eps <= 0:
        return pts
    d0 = np.hypot(pts[:, 0] - pts[0, 0], pts[:, 1] - pts[0, 1])
    i1 = int(np.argmax(d0))
    if i1 == 0:
        return pts
    a = pts[:i1 + 1]
    b = np.vstack([pts[i1:], pts[:1]])
    out = np.vstack([a[_rdp_open(a, eps)][:-1], b[_rdp_open(b, eps)][:-1]])
    return out if len(out) >= 3 else pts


def bridge_holes(outer, holes):
    """Polygon-with-holes -> one self-touching outline (keyhole / fracture).

    Each hole is joined by a zero-width horizontal slit running left from the
    hole's leftmost vertex to the first boundary it meets. Holes are processed
    left to right and merged into the working outline as they go, so a hole can
    bridge to an earlier hole's boundary; a hole still unprocessed lies entirely
    to the right and cannot be in the way.

    The leftward ray uses a CLOSED span test -- an edge counts if py lies
    anywhere between its endpoints, endpoints included -- rather than the
    half-open "strictly straddles" rule used for point-in-polygon. That
    distinction is the whole ballgame here, and it is not a style preference:

      The bridge vertex is chosen as the topmost of the hole's leftmost
      vertices, so it is by construction a local extremum in y. Under the
      half-open rule an edge that merely TOUCHES the ray at such a vertex does
      not count, which makes an already-merged hole invisible to any later hole
      sharing its exact y. Text art produces those constantly -- the counters of
      letters on one line share a pixel row -- and the later hole's slit then
      ran straight through the earlier one, laying two slits on top of each
      other. The MFB node badges did this 16 times each.

      Overlapping slits still FILL correctly (each is traversed once in each
      direction, so the winding cancels) which is why it went unnoticed, but the
      outline is no longer a clean fracture and no downstream boolean or offset
      operation can be trusted on it.

    With the closed test the nearest boundary to the left is found whether it
    crosses the ray or merely touches it, so a later hole bridges ONTO the
    earlier hole's vertex instead of over it.
    """
    out = np.asarray(outer, dtype=np.float64)
    order = sorted(range(len(holes)), key=lambda i: float(holes[i][:, 0].min()))
    unbridged = 0
    for hi in order:
        hole = np.asarray(holes[hi], dtype=np.float64)
        xmin = hole[:, 0].min()
        cand = np.nonzero(hole[:, 0] <= xmin + 1e-12)[0]
        i0 = int(cand[np.argmin(hole[cand, 1])])
        px, py = float(hole[i0, 0]), float(hole[i0, 1])

        ax, ay = out[:, 0], out[:, 1]
        bx, by = np.roll(ax, -1), np.roll(ay, -1)
        # Horizontal edges are excluded: they meet the ray in a segment, not a
        # point, and their endpoints are already carried by the adjoining edges.
        sloped = ay != by
        span = (np.minimum(ay, by) <= py) & (py <= np.maximum(ay, by)) & sloped
        dy = np.where(sloped, by - ay, 1.0)
        xi = np.where(span, ax + (py - ay) * (bx - ax) / dy, -np.inf)
        xi = np.where(xi <= px + 1e-9, xi, -np.inf)
        i = int(np.argmax(xi))
        if not np.isfinite(xi[i]):
            unbridged += 1          # geometrically impossible; reported, never hidden
            continue
        q = np.array([[float(xi[i]), py]])
        rot = np.roll(hole, -i0, axis=0)
        out = np.concatenate([out[:i + 1], q, rot, rot[:1], q, out[i + 1:]])
    return out, unbridged


def _round_dedupe(pts, dp=COORD_DP):
    r = np.round(np.asarray(pts, dtype=np.float64), dp)
    if len(r) > 1:
        keep = np.ones(len(r), dtype=bool)
        keep[1:] = np.any(r[1:] != r[:-1], axis=1)
        r = r[keep]
    if len(r) > 2 and np.all(r[0] == r[-1]):
        r = r[:-1]
    return r


# --- footprint writer ------------------------------------------------------
class ArtFp(Fp):
    """coupon_ladders.Fp plus arbitrary filled polygons and an art header.

    Subclassed rather than copied: Fp is the working minimal KiCad footprint
    writer already in the tree and there must not be a second one.
    """

    _NS = uuid.UUID("6f1f2e2c-6a4f-5f2a-9b7e-4d6c1a2b3c4d")

    def __init__(self, name, descr=None, tags="recklessart art", with_uuids=False):
        super().__init__(name)
        self.descr = descr or "Art footprint - kicad_art_generator tools/emit_art.py"
        self.tags = tags
        # `uuid` is optional on fp_poly and KiCad mints one on load (verified with
        # kicad-cli fp upgrade). At ~48 bytes a line and thousands of polygons it
        # is the single largest avoidable cost in the file, so it is off by
        # default. `stroke` is kept: relying on the parser's default width would
        # make an outline appear if that default ever changes.
        self.with_uuids = with_uuids

    def _uuid(self):
        self._n += 1
        return str(uuid.uuid5(self._NS, f"{self.name}:{self._n}"))

    @staticmethod
    def _num(v):
        s = f"{v:.{COORD_DP}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s

    def poly(self, pts, layer):
        body = " ".join(f"(xy {self._num(x)} {self._num(y)})" for x, y in pts)
        tail = f'\n\t\t(uuid "{self._uuid()}")' if self.with_uuids else ""
        self.items.append(
            f'\t(fp_poly (pts {body}) (stroke (width 0) (type solid)) '
            f'(fill solid) (layer "{layer}"){tail})'
        )

    def dumps(self):
        body = "\n".join(self.items)
        return (
            f'(footprint "{self.name}"\n\t(version 20241229)\n\t(generator "emit_art")\n'
            f'\t(layer "F.Cu")\n'
            f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
            f'\t(descr "{self.descr}")\n'
            f'\t(tags "{self.tags}")\n{body}\n)\n'
        )


# --- the emitter ------------------------------------------------------------
def _tone_polygons(mask, mm_per_px, ox, oy, tolerance_mm, min_area_mm2):
    """One tone's binary mask -> list of outlines in mm, plus bookkeeping."""
    info = {"outers": 0, "holes": 0, "unbridged": 0,
            "area_dropped": 0, "area_dropped_mm2": 0.0}

    loops = trace_contours(mask)
    if not loops:
        return [], info

    simplified = []
    for lp in loops:
        mm = np.empty_like(lp)
        mm[:, 0] = (lp[:, 0] + 0.5) * mm_per_px + ox
        mm[:, 1] = (lp[:, 1] + 0.5) * mm_per_px + oy
        simplified.append(rdp_closed(mm, tolerance_mm))

    areas = [signed_area(p) for p in simplified]
    outers = [(p, -a) for p, a in zip(simplified, areas) if a < 0]
    holes = [(p, a) for p, a in zip(simplified, areas) if a > 0]

    if min_area_mm2 > 0:
        kept = []
        for p, a in outers:
            if a < min_area_mm2:
                info["area_dropped"] += 1
                info["area_dropped_mm2"] += a
            else:
                kept.append((p, a))
        outers = kept
        kept = []
        for p, a in holes:
            if a < min_area_mm2:
                info["area_dropped"] += 1
                info["area_dropped_mm2"] += a
            else:
                kept.append((p, a))
        holes = kept

    info["outers"] = len(outers)
    info["holes"] = len(holes)

    # Attach each hole to the SMALLEST outer that contains it. Smallest, not
    # any: with an island inside a hole inside a region, the hole is contained
    # by exactly one outer (its own), while the island is a separate outer that
    # the hole surrounds rather than the reverse.
    boxes = [(p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max())
             for p, _ in outers]
    buckets: list[list] = [[] for _ in outers]
    for hp, _ha in holes:
        hx, hy = float(hp[0, 0]), float(hp[0, 1])
        best, best_a = -1, math.inf
        for i, (op, oa) in enumerate(outers):
            x0, y0, x1, y1 = boxes[i]
            if oa >= best_a or not (x0 <= hx <= x1 and y0 <= hy <= y1):
                continue                      # cheap bbox reject before the ray cast
            if point_in_poly(hp[0], op):
                best, best_a = i, oa
        if best >= 0:
            buckets[best].append(hp)
        else:
            info["unbridged"] += 1

    polys = []
    for (op, _oa), hs in zip(outers, buckets):
        if hs:
            merged, ub = bridge_holes(op, hs)
            info["unbridged"] += ub
        else:
            merged = op
        pts = _round_dedupe(merged)
        if len(pts) >= 3:
            polys.append(pts)
        else:
            info["area_dropped"] += 1
    return polys, info


def emit_detailed(labels, tone_names, width_mm, name, *,
                  tolerance_mm=DEFAULT_TOLERANCE_MM, min_area_mm2=0.0,
                  tone_layers=None, descr=None, strict=True, with_uuids=False):
    """Core. Returns (footprint_text, report_dict).

    min_area_mm2 may be a number, or the string "auto" to use each tone's own
    minimum fabricable feature squared (see MIN_FEATURE_MM). Anything it removes
    is reported per tone and as a run-level warning; nothing is dropped quietly.
    """
    labels = np.asarray(labels)
    if labels.ndim != 2:
        raise ValueError(f"labels must be a 2-D array, got shape {labels.shape}")
    tone_layers = TONE_LAYERS if tone_layers is None else tone_layers
    auto_area = isinstance(min_area_mm2, str) and min_area_mm2.lower() == "auto"
    if not auto_area:
        min_area_mm2 = float(min_area_mm2)

    if float(width_mm) <= 0:
        raise ValueError(f"width_mm must be positive, got {width_mm}")
    H, W = labels.shape
    mm_per_px = float(width_mm) / W
    height_mm = H * mm_per_px
    ox, oy = -width_mm / 2.0, -height_mm / 2.0     # centre the art on the origin

    present = {int(v): int(n) for v, n in zip(*np.unique(labels, return_counts=True))
               if int(v) >= 0}
    unknown = [v for v in present if v >= len(tone_names)]
    if unknown:
        raise ValueError(f"labels contain indices {unknown} with no entry in tone_names "
                         f"(len={len(tone_names)})")

    fp = ArtFp(name, descr=descr, with_uuids=with_uuids)
    report = {
        "name": name,
        "input_px": [W, H],
        "width_mm": float(width_mm),
        "height_mm": round(height_mm, 4),
        "mm_per_px": mm_per_px,
        "tolerance_mm": float(tolerance_mm),
        "tolerance_px": tolerance_mm / mm_per_px,
        "min_area_mm2": "auto" if auto_area else min_area_mm2,
        "tones": [],
        "dropped": [],
        "warnings": [],
        "transparent_px": int((labels < 0).sum()),
    }

    for idx in sorted(present):
        tone = tone_names[idx]
        px = present[idx]
        layers = tone_layers.get(tone)
        if layers is None:
            raise ValueError(f"tone {tone!r} has no layer recipe; known: "
                             f"{sorted(tone_layers)}")
        row = {"tone": tone, "px": px, "layers": list(layers),
               "polys": 0, "verts": 0, "holes": 0, "sub_min_feature": 0,
               "background": tone == BACKGROUND}

        if tone == BACKGROUND or not layers:
            row["note"] = "background - draws nothing, by design"
            report["tones"].append(row)
            continue

        floor = max(MIN_FEATURE_MM.get(l, 0.1) for l in layers)
        row["min_feature_mm"] = floor
        area_floor = floor * floor if auto_area else float(min_area_mm2)
        row["min_area_mm2"] = area_floor

        polys, info = _tone_polygons(mask=(labels == idx), mm_per_px=mm_per_px,
                                     ox=ox, oy=oy, tolerance_mm=tolerance_mm,
                                     min_area_mm2=area_floor)
        row["polys"] = len(polys)
        row["verts"] = int(sum(len(p) for p in polys))
        row["holes"] = info["holes"]
        row["area_dropped"] = info["area_dropped"]
        row["area_dropped_mm2"] = round(info["area_dropped_mm2"], 6)
        row["sub_min_feature"] = sum(1 for p in polys if abs(signed_area(p)) < floor * floor)

        if info["unbridged"]:
            report["warnings"].append(
                f"{tone}: {info['unbridged']} hole(s) could not be bridged and are "
                f"filled solid -- geometry is WRONG, inspect the source")
        if info["area_dropped"]:
            report["warnings"].append(
                f"{tone}: DROPPED {info['area_dropped']} region(s) below "
                f"{area_floor:g} mm2 ({row['area_dropped_mm2']:g} mm2, "
                f"{100.0*row['area_dropped_mm2']/max(px*mm_per_px*mm_per_px, 1e-12):.1f}% "
                f"of this tone's area) -- unfabricable at {floor} mm min feature")
        if row["sub_min_feature"]:
            report["warnings"].append(
                f"{tone}: {row['sub_min_feature']} polygon(s) below the {floor} mm "
                f"minimum feature for {'/'.join(layers)} -- will print unreliably")

        for layer in layers:
            for p in polys:
                fp.poly(p, layer)

        if row["polys"] == 0:
            report["dropped"].append(tone)
        report["tones"].append(row)

    report["total_polys"] = sum(t["polys"] for t in report["tones"])
    report["total_verts"] = sum(t["verts"] for t in report["tones"])
    # a polygon is written once per layer in the recipe
    report["total_fp_poly"] = sum(t["polys"] * len(t["layers"]) for t in report["tones"])

    text = fp.dumps()
    report["bytes"] = len(text.encode("utf-8"))

    if not report["tones"]:
        report["warnings"].append("input has no opaque pixels - nothing to emit")

    if report["dropped"]:
        px_of = {r["tone"]: r["px"] for r in report["tones"]}
        msg = ("DROPPED TONE(S): " + ", ".join(
            f"{t} ({px_of[t]:,} px) -> 0 polygons" for t in report["dropped"]))
        if strict:
            raise ToneDropped(msg)
        report["warnings"].append(msg)

    return text, report


def emit(labels, tone_names, width_mm, name, **kwargs):
    """Interface required by the task: -> footprint text."""
    return emit_detailed(labels, tone_names, width_mm, name, **kwargs)[0]


# --- input handling ---------------------------------------------------------
def rasterise_svg(path, width_px):
    """SVG -> RGBA PIL image on a transparent ground. cairosvg, else rsvg-convert,
    else inkscape. Kept here rather than in w0_spike: the quantiser takes an
    image and should not learn about vector formats."""
    import io
    import shutil
    import subprocess
    import tempfile
    from svg_entities import read_svg_bytes
    # Illustrator exports declare their private namespaces as internal DTD
    # entities, which defusedxml (under cairosvg) refuses outright. Resolve them
    # first; files without an internal subset come back byte-identical.
    data, ent = read_svg_bytes(path)
    try:
        import cairosvg
        png = cairosvg.svg2png(bytestring=data, output_width=int(width_px),
                               url=str(path))
        return Image.open(io.BytesIO(png)).convert("RGBA"), "cairosvg"
    except ImportError:
        pass
    with tempfile.TemporaryDirectory() as td:
        dst = pathlib.Path(td) / "r.png"
        src = pathlib.Path(path)
        if ent["removed_subset"]:
            src = pathlib.Path(td) / "expanded.svg"
            src.write_bytes(data)
        path = src
        if shutil.which("rsvg-convert"):
            subprocess.run(["rsvg-convert", "-w", str(int(width_px)),
                            "-o", str(dst), str(path)], check=True)
            tool = "rsvg-convert"
        elif shutil.which("inkscape"):
            subprocess.run(["inkscape", str(path), "--export-type=png",
                            f"--export-width={int(width_px)}",
                            f"--export-filename={dst}"], check=True)
            tool = "inkscape"
        else:
            raise RuntimeError("no SVG rasteriser found (cairosvg / rsvg-convert / inkscape)")
        return Image.open(dst).convert("RGBA"), tool


def crop_to_content(img, min_alpha=8):
    """Trim a fully-transparent border. The Bitcoin emission formula SVG is a
    US-Letter artboard around a small drawing; without this it renders as a
    mostly-empty page at whatever --width-mm was asked for."""
    a = np.asarray(img.convert("RGBA"))[..., 3]
    ys, xs = np.nonzero(a >= min_alpha)
    if ys.size == 0:
        return img, None
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    if box == (0, 0, img.width, img.height):
        return img, None
    return img.crop(box), box


def load_labels(path, args, log):
    """-> (labels, tone_names, source_note). Accepts .npy or any image."""
    path = pathlib.Path(path)
    if path.suffix.lower() == ".npy":
        labels = np.load(path)
        names = (args.tone_names.split(",") if args.tone_names
                 else [t[0] for t in TONES])
        log.append(f"labels  : {path.name} (.npy) {labels.shape[1]}x{labels.shape[0]}")
        return labels.astype(np.int64), names, None

    if path.suffix.lower() == ".svg":
        img, tool = rasterise_svg(path, args.raster_width)
        log.append(f"raster  : {path.name} via {tool} at {img.width}x{img.height} px")
    else:
        img = Image.open(path).convert("RGBA")
        log.append(f"raster  : {path.name} {img.width}x{img.height} px")

    if args.crop:
        img, box = crop_to_content(img)
        if box:
            log.append(f"crop    : content bbox {box} -> {img.width}x{img.height} px")

    if args.max_dim and max(img.size) > args.max_dim:
        s = args.max_dim / max(img.size)
        new = (max(1, round(img.width * s)), max(1, round(img.height * s)))
        img = img.resize(new, Image.LANCZOS)
        log.append(f"resize  : -> {img.width}x{img.height} px (--max-dim {args.max_dim})")

    labels, _opaque, st = quantise(img, smooth=args.smooth, mix=args.mix,
                                   mix_ratio=args.mix_ratio,
                                   mix_split=args.mix_split)
    log.append(f"quantise: opaque={st['opaque_px']:,} dropped={st['dropped_px']:,} "
               f"tones={' '.join(st['per_tone'])}")
    m = st.get("mixture", {})
    if m.get("enabled"):
        log.append(f"mixture : {m['mixture_px']:,} coverage-blend px "
                   f"({100.0*m['mixture_px']/max(st['opaque_px'],1):.2f}%), "
                   f"{m['reassigned_px']:,} relabelled  "
                   f"[ratio={m['params']['mix_ratio']} split={m['params']['mix_split']}]")
        if m["pairs"]:
            log.append("        : between " + "  ".join(
                f"{k}={v:,}" for k, v in list(m["pairs"].items())[:6]))
        if m["tones_eliminated"]:
            naive = st.get("per_tone_naive", {})
            log.append("        : TONES REMOVED as halo-only -- " + ", ".join(
                f"{t} ({naive.get(t, 0):,} px)" for t in m["tones_eliminated"]))
    else:
        log.append("mixture : DISABLED (--no-mix) -- tone boundaries will "
                   "generate a spurious third tone")
    names = (args.tone_names.split(",") if args.tone_names
             else [t[0] for t in TONES])
    return labels.astype(np.int64), names, img


def print_report(rep, out_path, log):
    w = sys.stdout.write
    w("\n" + "=" * 74 + "\n")
    w(f"  {rep['name']}\n")
    w("=" * 74 + "\n")
    for line in log:
        w(f"  {line}\n")
    w(f"  size    : {rep['input_px'][0]}x{rep['input_px'][1]} px -> "
      f"{rep['width_mm']:.3f} x {rep['height_mm']:.3f} mm  "
      f"({rep['mm_per_px']*1000:.1f} um/px)\n")
    w(f"  simplify: {rep['tolerance_mm']} mm tolerance "
      f"(= {rep['tolerance_px']:.2f} px at this scale)\n")
    w(f"  min area: {rep['min_area_mm2']}"
      f"{' (per-tone min feature squared)' if rep['min_area_mm2'] == 'auto' else ' mm2'}\n")
    if rep["transparent_px"]:
        w(f"  alpha   : {rep['transparent_px']:,} transparent px, no geometry\n")
    w("\n  tone  layers                 pixels    polys   verts  holes  dropped  note\n")
    w("  " + "-" * 78 + "\n")
    for t in rep["tones"]:
        note = t.get("note", "")
        if not note and t.get("sub_min_feature"):
            note = f"{t['sub_min_feature']} poly < {t['min_feature_mm']}mm feature"
        w(f"  {t['tone']:<4}  {'+'.join(t['layers']) or '-':<20} "
          f"{t['px']:>9,} {t['polys']:>7,} {t['verts']:>7,} {t['holes']:>6,} "
          f"{t.get('area_dropped', 0):>8,}  {note}\n")
    w("  " + "-" * 78 + "\n")
    w(f"  {'TOTAL':<4}  {'':<20} {'':>9} {rep['total_polys']:>7,} "
      f"{rep['total_verts']:>7,} {'':>6} "
      f"{sum(t.get('area_dropped', 0) for t in rep['tones']):>8,}  "
      f"{rep['total_fp_poly']:,} fp_poly written\n")

    n = rep["bytes"]
    w(f"\n  output  : {out_path}\n")
    w(f"  bytes   : {n:,} B ({n/1024:.1f} kB)  "
      f"= {100.0*n/APRIL_BASELINE_BYTES:.2f}% of the 2.5 MB April baseline "
      f"({APRIL_BASELINE_BYTES/max(n,1):.0f}x smaller)\n")
    if rep["warnings"]:
        w("\n  !! WARNINGS\n")
        for x in rep["warnings"]:
            w(f"  !! {x}\n")
    w("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Quantised tone-label raster -> KiCad footprint.")
    ap.add_argument("--labels", required=True,
                    help=".npy label array from w0_spike.quantise(), or an image "
                         "(png/jpg/svg) to quantise on the way through")
    ap.add_argument("--width-mm", type=float, required=True,
                    help="output width; height follows the source aspect ratio")
    ap.add_argument("--name", required=True, help="footprint name")
    ap.add_argument("-o", "--output", required=True, help="output .kicad_mod")
    ap.add_argument("--tolerance-mm", type=float, default=DEFAULT_TOLERANCE_MM,
                    help=f"RDP tolerance in MILLIMETRES (default {DEFAULT_TOLERANCE_MM}: "
                         "half the 0.1 mm min feature, equal to mask registration, "
                         "below the eye's 0.087 mm at 300 mm)")
    ap.add_argument("--min-area-mm2", default="0",
                    help="drop regions smaller than this many mm2, or 'auto' for each "
                         "tone's own minimum fabricable feature squared. Default 0 = "
                         "drop nothing; anything dropped is reported loudly")
    ap.add_argument("--uuids", action="store_true",
                    help="write a uuid on every fp_poly (KiCad mints them on load; "
                         "off by default because it is ~48 B x thousands of polygons)")
    ap.add_argument("--smooth", type=float, default=0.0,
                    help="Gaussian pre-blur passed to w0_spike.quantise. Was 1.0; "
                         "now 0.0 because the blur widens the antialias blend band "
                         "and pushes a 1 px feature below the 50%% coverage floor. "
                         "Only for noisy (JPEG) sources")
    ap.add_argument("--no-mix", dest="mix", action="store_false", default=True,
                    help="disable mixture-pixel handling in the quantiser -- "
                         "restores the pre-fix behaviour where every tone boundary "
                         "emits a 1-2 px band of a spurious third tone")
    ap.add_argument("--mix-ratio", type=float, default=None,
                    help="how much better a two-anchor mixture must explain a pixel "
                         "than the nearest single anchor (default 0.5 = twice as well)")
    ap.add_argument("--mix-split", type=float, default=None,
                    help="recovered-coverage threshold for a blend pixel (default 0.5, "
                         "which is what makes a >=1 px feature survive). Lower it to "
                         "bias toward keeping thin ink; it cannot resurrect the halo")
    ap.add_argument("--raster-width", type=int, default=1200,
                    help="raster width used for SVG input")
    ap.add_argument("--max-dim", type=int, default=0,
                    help="downscale raster input to this longest edge (0 = never)")
    ap.add_argument("--crop", dest="crop", action="store_true", default=True,
                    help="trim a fully transparent border (default on)")
    ap.add_argument("--no-crop", dest="crop", action="store_false")
    ap.add_argument("--tone-names", default=None,
                    help="comma-separated tone ids indexed by label value; "
                         "default is w0_spike.TONES order")
    ap.add_argument("--preview", default=None, help="also write a composite PNG here")
    ap.add_argument("--report-json", default=None, help="also write the report as JSON")
    ap.add_argument("--allow-dropped-tones", action="store_true",
                    help="downgrade a dropped tone from a hard failure to a warning")
    ap.add_argument("--ink-tone", default=None, metavar="TONE",
                    help="MONOCHROME LINE ART ONLY. Re-point the background tone "
                         "(T5 black mask) at TONE, e.g. T1 for silk white. Black "
                         "ink is the same colour as a black-mask board, so black "
                         "line art quantises to the board itself and draws "
                         "nothing; this renders it inverted, the way you would "
                         "actually fabricate it. Refused if the image has more "
                         "than one tone, because then T5 really is background")
    ap.add_argument("--allow-empty", action="store_true",
                    help="write the footprint even if it contains no geometry at "
                         "all (the whole image landed on non-drawing tones)")
    args = ap.parse_args(argv)
    if args.mix_ratio is None:
        args.mix_ratio = MIX_RATIO
    if args.mix_split is None:
        args.mix_split = MIX_SPLIT

    log: list[str] = []
    labels, tone_names, _img = load_labels(args.labels, args, log)

    if args.ink_tone:
        known = {t[0] for t in TONES}
        if args.ink_tone not in known:
            sys.stderr.write(f"\n!! --ink-tone {args.ink_tone!r} is not a palette "
                             f"tone; known: {' '.join(sorted(known))}\n\n")
            return 2
        present = sorted({int(v) for v in np.unique(labels) if v >= 0})
        names_present = [tone_names[i] for i in present]
        # Guard against using this as a general recolour. It is only meaningful
        # when the picture is one flat ink whose tone happens to be the board.
        if names_present != [BACKGROUND]:
            sys.stderr.write(
                f"\n!! --ink-tone only applies to monochrome line art whose only "
                f"tone is the background {BACKGROUND}.\n!! This image contains "
                f"{', '.join(names_present)}. Recolouring it would misrepresent "
                f"the artwork.\n\n")
            return 2
        idx = present[0]
        tone_names = list(tone_names)
        tone_names[idx] = args.ink_tone
        log.append(f"ink-tone: monochrome line art -- {BACKGROUND} ink is the "
                   f"board colour and would draw nothing; rendering as "
                   f"{args.ink_tone}")

    min_area = args.min_area_mm2 if str(args.min_area_mm2).lower() == "auto" \
        else float(args.min_area_mm2)

    try:
        text, rep = emit_detailed(
            labels, tone_names, args.width_mm, args.name,
            tolerance_mm=args.tolerance_mm, min_area_mm2=min_area,
            with_uuids=args.uuids,
            descr=f"{args.name} - {pathlib.Path(args.labels).name} at "
                  f"{args.width_mm:g} mm - kicad_art_generator/emit_art.py",
            strict=not args.allow_dropped_tones)
    except ToneDropped as e:
        sys.stderr.write(f"\n!! {e}\n!! A tone in the input produced no geometry. "
                         "Refusing to write a footprint that silently loses image "
                         "content. Re-run with --allow-dropped-tones only if you have "
                         "decided the tone genuinely does not matter.\n\n")
        return 2

    # Total loss check. A tone whose recipe draws nothing (T5, the black mask --
    # i.e. the bare board) is legitimate as PART of a picture: it is the
    # background showing through. But if EVERY inked pixel landed there, the
    # footprint is empty and the whole artwork has been thrown away. Reporting
    # "background - draws nothing, by design" and exiting 0 made that look like
    # a success. Pure black line art on a black-mask board is exactly this case:
    # the ink is the same colour as the board, so it must be rendered inverted,
    # in silk white -- see --ink-tone.
    drawn = sum(t["polys"] for t in rep["tones"])
    inked = sum(t["px"] for t in rep["tones"])
    if inked and not drawn and not args.allow_empty:
        dead = ", ".join(f"{t['tone']} ({t['px']:,} px)" for t in rep["tones"])
        sys.stderr.write(
            f"\n!! EMPTY OUTPUT: {inked:,} inked pixels, 0 polygons.\n"
            f"!! Every pixel landed on a tone that draws nothing: {dead}.\n"
            f"!! The entire image would be lost. Refusing to write it.\n"
            f"!! If this is monochrome line art, its ink is the same colour as "
            f"the board itself;\n!! render it inverted with --ink-tone T1 "
            f"(silk white). Use --allow-empty to override.\n\n")
        return 3

    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    rep["bytes"] = out.stat().st_size
    rep["output"] = str(out)

    if args.preview:
        composite(labels).save(args.preview)
        log.append(f"preview : {args.preview}")

    print_report(rep, out, log)
    if args.report_json:
        pathlib.Path(args.report_json).write_text(json.dumps(rep, indent=2),
                                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
