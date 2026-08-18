#!/usr/bin/env python3
"""W1b: microprinting as a real output mode.

docs/pcb-palette.md assesses microprinting and coupon_ladders.text_ladder()
sweeps cap heights on a calibration coupon, but neither lets you PLACE microtext
in a design. This does: a string, a cap height, a palette tone, and either a path
to run along or a region to fill.

The four things this module exists to get right
-----------------------------------------------

1. THE FLOOR IS ENFORCED, NOT SUGGESTED. The palette gives copper as the only
   viable microprint medium -- etching is photolithographic, silkscreen is a
   mesh print, and the doc puts silk's implied minimum character height at
   0.9-1.2 mm, which it calls "not microprinting, just small text". A silk
   request below its floor is REFUSED with the number that refuses it, not
   quietly promoted to something that will not image.

2. STROKE SCALES WITH CAP HEIGHT AND STAYS ABOVE THE FLOOR. That is the bug
   coupon_ladders.Fp.text() already fixed once and this must not reintroduce.
   Here the stroke is always cap*ratio -- and if that lands under the floor the
   CAP HEIGHT is refused, rather than the stroke being clamped up to the floor.
   Clamping would be the worse failure: at 0.4 mm cap a 0.10 mm stroke is 1:4,
   which fills every counter in the string solid. The output would pass a naive
   min-feature check and be unreadable. So: refuse, and say which cap height
   would work.

3. THE COUNTERS ARE CHECKED, NOT JUST THE STROKES. Closed letterforms fail
   first. stroke_font.py measures the inscribed radius of every glyph's
   narrowest enclosed void off a real KiCad render, so "narrowest counter" is a
   number here, not an adjective: clear = 2*D*cap - stroke. For
   coupon_ladders.SPECIMEN the binding glyph is 'e' (D = 0.147 em), and it binds
   BEFORE the stroke does -- which is precisely why that specimen was chosen.

4. THE MASK OPENS OVER THE BLOCK, NEVER PER GLYPH. Mask registration is
   +/-0.05 mm against a ~0.10 mm stroke. A per-glyph opening cannot survive
   that; a block opening only has to place its own edge. So for any tone whose
   recipe contains a mask layer, the letterforms go on the COPPER layer and the
   mask layer gets one filled rectangle over the whole run. Two runs whose
   openings would leave a sub-floor mask dam between them are merged into one
   opening rather than left to wash away.

Tones
-----
Read from coupon_blocks.TONE_RECIPE, then split by layer class:

  T2  F.Cu + F.Mask   copper letterforms in one block opening -- gold on bare
                      laminate, the doc's option 1, the high-contrast route.
  T6  F.Cu            copper under mask, no opening -- the doc's option 2.
                      Covert, and immune to registration entirely.
  T1  F.SilkS         allowed only at or above the cap height its own floor
                      implies. Not microprinting; the doc says so.
  T3  F.Mask          refused: the letterforms would BE the opening, and the
                      doc is explicit that microprinting works in copper only.
  T5  (nothing)       refused: draws nothing by definition.
  T4/T7 buried        refused unless --allow-buried: the doc says buried tones
                      are "fields and broad shapes, not linework", and their
                      floor is PROVISIONAL (docs/pcb-palette.md gives no number).

Usage
    python tools/microtext.py --text "Reckless" --height 0.7 --tone T2 \
        --name mt_demo -o out.kicad_mod --region 0,0,20,6
    python tools/emit_art.py ... --microtext "Reckless" --microtext-height 0.7
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from dataclasses import dataclass, field

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import fab_profiles                                      # noqa: E402
import stroke_font                                       # noqa: E402
from fab_profiles import FAB_TAG_PREFIX                  # noqa: E402
from coupon_ladders import (FLOOR_MASK_DAM, FLOOR_SOURCE,  # noqa: E402
                            TEXT_STROKE_RATIO, floor_for)
from coupon_blocks import TONE_RECIPE                    # noqa: E402

TONE_LAYERS = {k.split("_", 1)[0]: tuple(v) for k, v in TONE_RECIPE.items()}

# Minimum legible character height, mm. docs/pcb-palette.md: silk 0.9-1.2 ("not
# microprinting, just small text"), copper reliable zone 0.6-0.8 with 0.5 as
# best case. These are the same numbers tools/verify_art.py checks against, on
# purpose -- the emitter must not pass something the harness will then flag.
LEGIBLE_MM = {"silk": 0.9, "copper": 0.6, "mask": 0.9, "buried": 1.2}

# docs/pcb-palette.md, "legible stroke-to-height runs about 1:6 to 1:8".
RATIO_BAND = (1.0 / 8.0, 1.0 / 6.0)

# docs/pcb-palette.md: "Vendor capability varies sharply ... Microprinting is a
# per-vendor decision, not a design constant." The doc is right, and this file
# used to answer it with three ABSTRACT tiers -- 0.127 / 0.090 / 0.075 mm,
# labelled "standard", "advanced, at extra cost" and "needs a capable fab".
#
# That table is gone. Two of its three numbers are not sold by any process in
# tools/fab_profiles.py, and the middle one is what made the palette's 0.100 mm
# copper floor look like a buildable target: 0.100 sits just inside "advanced",
# so a part sized to it read as merely expensive, when in fact it is finer than
# JLCPCB's standard 4-layer (0.1016) and coarser than their fine option
# (0.0889) -- orderable from nobody, at any price.
#
# The report now iterates fab_profiles.PROFILES: named processes, each with a
# source URL and a surcharge, so the question "who builds this" has an answer
# with a company in it.

# The mask opening is grown past the letterforms by this much. Mask registration
# is +/-0.05 mm; at 3x that, a worst-case misregistration still leaves the
# opening clear of every glyph, which is the whole point of opening over the
# block instead of over the glyphs.
DEFAULT_MASK_BLEED_MM = 0.15
MASK_REGISTRATION_MM = 0.05

# Two runs whose openings sit closer than one glyph apart read as one block, so
# they are merged rather than left as a hairline dam. Below FLOOR_MASK_DAM the
# dam washes away in processing and they merge anyway -- badly.
DEFAULT_RUN_TOL_DEG = 0.5

# Shape flow rasterises its mask this many pixels across by default. The row
# pitch at a 0.68 mm cap is about 1 mm, so at a 30 mm wide shape one pixel is
# ~0.02 mm and a span edge is located to a fortieth of a row. Raising it costs
# only load time.
DEFAULT_SHAPE_RASTER_PX = 2048


class MicrotextRefused(RuntimeError):
    """A request that cannot be honoured as asked. Never downgraded silently."""


# --- tone -> layers ---------------------------------------------------------

def _classify(layers):
    cu, mask, silk, buried = [], [], [], []
    for l in layers:
        cls = floor_for(l)[1]
        (cu if cls == "copper" else mask if cls == "mask" else
         silk if cls == "silk" else buried if cls == "buried" else []).append(l)
    return cu, mask, silk, buried


def resolve_fab(spec) -> "fab_profiles.FabProfile | None":
    """The named process for this spec, or None if it names none.

    Kept separate from check() so the CLI, the emitter and anything that
    reconstructs a spec all get the same refusals from the same code.
    """
    if getattr(spec, "fab", None) is None:
        return None
    if spec.floor_mm is not None:
        raise MicrotextRefused(
            f"--{spec.flag_prefix}fab {spec.fab} and "
            f"--{spec.flag_prefix}floor {spec.floor_mm:g} are the same decision "
            f"said two ways. Pick one: the profile carries a sourced number and "
            f"a name the verifier can be handed, the bare floor carries neither.")
    try:
        return fab_profiles.PROFILES[spec.fab]
    except KeyError:
        raise MicrotextRefused(
            f"{spec.fab!r} is not a fabrication profile. tools/fab_profiles.py "
            f"knows: {' '.join(sorted(fab_profiles.PROFILES))}") from None


def plan_tone(tone: str, *, allow_buried: bool = False):
    """-> (text_layers, mask_layers, floor_class, notes). Raises on refusal."""
    if tone not in TONE_LAYERS:
        raise MicrotextRefused(
            f"{tone!r} is not a palette tone; known: {' '.join(sorted(TONE_LAYERS))}")
    layers = TONE_LAYERS[tone]
    cu, mask, silk, buried = _classify(layers)
    notes = []

    if not layers:
        raise MicrotextRefused(
            f"{tone} draws nothing at all -- it IS the bare board (see "
            f"docs/pcb-palette.md). There is no layer to put letterforms on. "
            f"Use T2 (copper in a block mask opening) or T6 (copper under mask).")

    if cu:
        text_layers = cu
        if mask:
            notes.append(f"{tone}: letterforms on {'/'.join(cu)}, ONE block "
                         f"opening on {'/'.join(mask)} -- gold on bare laminate")
        else:
            notes.append(f"{tone}: copper under mask, no opening -- covert, and "
                         f"immune to mask registration entirely")
        return text_layers, mask, "copper", notes

    if buried:
        if not allow_buried:
            raise MicrotextRefused(
                f"{tone} puts the letterforms on {'/'.join(buried)}. "
                f"docs/pcb-palette.md: buried tones are shadows cast through "
                f"0.1 mm of dielectric, \"fine detail will not read\", and are "
                f"to be treated as fields and broad shapes, NOT linework. "
                f"Microtext is the finest linework there is. The doc also gives "
                f"no minimum-feature number for buried layers at all, so there "
                f"is nothing to check against. Use T2 or T6, or pass "
                f"--allow-buried if you are deliberately making a coupon.")
        notes.append(f"{tone}: BURIED microtext on {'/'.join(buried)} -- the "
                     f"palette gives no floor for this layer and says fine "
                     f"detail will not read. Everything below is PROVISIONAL.")
        return buried, mask, "buried", notes

    if silk:
        notes.append(f"{tone}: silkscreen. docs/pcb-palette.md puts silk's "
                     f"implied minimum character height at 0.9-1.2 mm and calls "
                     f"that \"not microprinting, just small text\" -- copper is "
                     f"about twice as fine and is the only microprint medium.")
        return silk, [], "silk", notes

    # mask-only, i.e. T3
    raise MicrotextRefused(
        f"{tone}'s only layer is {'/'.join(mask)}, so the letterforms would BE "
        f"the mask opening -- one opening per glyph, which is exactly what "
        f"docs/pcb-palette.md rules out: mask registration is "
        f"+/-{MASK_REGISTRATION_MM} mm and per-glyph openings will not survive "
        f"it. The doc is also explicit that microprinting is achievable \"only "
        f"in copper\". Use T2 (copper inside one block opening, gold on bare "
        f"laminate) or T6 (copper under mask, covert).")


# --- geometry ---------------------------------------------------------------

def rotate(dx, dy, angle_deg):
    """Rotate an offset from a KiCad text anchor by the fp_text `at` angle.

    KiCad angles are counter-clockwise as DISPLAYED, and file y grows downward,
    so the file-space rotation is the transpose of the usual one. Verified
    against a kicad-cli render, not assumed.
    """
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return dx * c + dy * s, -dx * s + dy * c


def box_quad(x, y, box, angle_deg):
    """Ink box (x0,y0,x1,y1) around an anchor -> 4 corners in footprint mm."""
    x0, y0, x1, y1 = box
    out = []
    for dx, dy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        rx, ry = rotate(dx, dy, angle_deg)
        out.append((x + rx, y + ry))
    return out


def inflate_quad(q, d):
    """Grow a convex quad outward by d, by pushing each vertex along the
    bisector of its two edges. Exact for a rectangle, which is all we make."""
    n = len(q)
    out = []
    for i in range(n):
        p = q[i]
        a, b = q[(i - 1) % n], q[(i + 1) % n]
        v1 = (p[0] - a[0], p[1] - a[1])
        v2 = (p[0] - b[0], p[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-12 or l2 < 1e-12:
            out.append(p)
            continue
        u = (v1[0] / l1 + v2[0] / l2, v1[1] / l1 + v2[1] / l2)
        lu = math.hypot(*u)
        if lu < 1e-12:
            out.append(p)
            continue
        # for a right angle the bisector reaches d*sqrt(2); scale generally
        cos_half = max(0.2, math.sqrt(max(0.0, (1 + (v1[0]*v2[0] + v1[1]*v2[1])
                                                / (l1 * l2)) / 2)))
        k = d / cos_half
        out.append((p[0] + u[0] / lu * k, p[1] + u[1] / lu * k))
    return out


def convex_hull(pts):
    p = sorted(set((round(x, 6), round(y, 6)) for x, y in pts))
    if len(p) < 3:
        return list(p)

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lo = []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    hi = []
    for q in reversed(p):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], q) <= 0:
            hi.pop()
        hi.append(q)
    return lo[:-1] + hi[:-1]


def _seg_dist(p, q, r, s):
    def pt_seg(p, a, b):
        vx, vy = b[0]-a[0], b[1]-a[1]
        L2 = vx*vx + vy*vy
        if L2 <= 0:
            return math.hypot(p[0]-a[0], p[1]-a[1])
        t = max(0.0, min(1.0, ((p[0]-a[0])*vx + (p[1]-a[1])*vy) / L2))
        return math.hypot(p[0]-(a[0]+t*vx), p[1]-(a[1]+t*vy))
    d1 = (q[0]-p[0], q[1]-p[1])
    d2 = (s[0]-r[0], s[1]-r[1])
    den = d1[0]*d2[1] - d1[1]*d2[0]
    if abs(den) > 1e-15:
        t = ((r[0]-p[0])*d2[1] - (r[1]-p[1])*d2[0]) / den
        u = ((r[0]-p[0])*d1[1] - (r[1]-p[1])*d1[0]) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            return 0.0
    return min(pt_seg(p, r, s), pt_seg(q, r, s), pt_seg(r, p, q), pt_seg(s, p, q))


def poly_gap(a, b):
    best = math.inf
    for i in range(len(a)):
        for j in range(len(b)):
            best = min(best, _seg_dist(a[i], a[(i+1) % len(a)],
                                       b[j], b[(j+1) % len(b)]))
            if best <= 0.0:
                return 0.0
    return best


# --- shape masks ------------------------------------------------------------

@dataclass
class ShapeMask:
    """A binary fill mask in millimetres. True = the letterforms may go here.

    Row 0 of `grid` is the TOP of the shape and y grows downward, which is
    KiCad's convention and the raster's, so nothing is flipped anywhere.
    """
    grid: object                      # numpy bool array [rows, cols]
    mm_per_px: float
    origin: tuple[float, float]       # mm at the top-left corner of grid[0,0]
    source: str = ""
    raster_tool: str = ""

    @property
    def height_mm(self):
        return self.grid.shape[0] * self.mm_per_px

    @property
    def width_mm(self):
        return self.grid.shape[1] * self.mm_per_px

    def band_spans(self, y_top, y_bot, *, whole_band=True):
        """Runs of x where the mask is set, for the row band y_top..y_bot mm.

        With whole_band=True a column counts only if EVERY scanline in the band
        is inside the shape. That is the conservative reading of "fill this
        shape with text": a row of letterforms is as tall as its band, so a
        column that is only inside for part of the band would put ink outside
        the silhouette. The alternative -- testing the band's centre line --
        lets ascenders and descenders hang over the edge, which reads as a
        ragged shape rather than a drawn one.
        """
        import numpy as np
        r0 = int(math.floor((y_top - self.origin[1]) / self.mm_per_px))
        r1 = int(math.ceil((y_bot - self.origin[1]) / self.mm_per_px))
        r0 = max(0, min(self.grid.shape[0], r0))
        r1 = max(0, min(self.grid.shape[0], r1))
        if r1 <= r0:
            return []
        band = self.grid[r0:r1]
        cols = band.all(axis=0) if whole_band else band.any(axis=0)
        spans = []
        idx = np.flatnonzero(np.diff(np.concatenate(
            ([False], cols, [False])).astype(np.int8)))
        for a, b in zip(idx[0::2], idx[1::2]):
            spans.append((self.origin[0] + a * self.mm_per_px,
                          self.origin[0] + b * self.mm_per_px))
        return spans

    def area_mm2(self):
        return float(self.grid.sum()) * self.mm_per_px ** 2


def _prune_svg(path, element):
    """Keep only the `element`-th drawable child of the SVG root, painted solid.

    examples/bitcoin_b.svg is three stacked shapes -- a rounded square, a disc,
    and the currency mark. Rasterising the file whole gives a filled square,
    which is not the shape anyone means by "the B". Selecting the child by
    index is explicit and reported, rather than guessing from fill colours
    (the square and the mark share one).
    """
    import xml.etree.ElementTree as ET
    NS = "http://www.w3.org/2000/svg"
    ET.register_namespace("", NS)
    tree = ET.parse(path)
    root = tree.getroot()
    kids = [k for k in list(root) if not k.tag.endswith("}defs")]
    if not (0 <= element < len(kids)):
        raise MicrotextRefused(
            f"--shape-element {element} is out of range: {pathlib.Path(path).name} "
            f"has {len(kids)} drawable children "
            f"({', '.join(k.tag.split('}')[-1] for k in kids)})")
    keep = kids[element]
    for k in kids:
        root.remove(k)
    # Paint it solid black on a transparent ground: the loader thresholds on
    # ALPHA, so the fill colour is irrelevant and any stroke would fatten the
    # silhouette past the artwork.
    keep.set("fill", "#000000")
    keep.set("stroke", "none")
    keep.set("opacity", "1")
    root.append(keep)
    return ET.tostring(root, encoding="unicode"), \
        keep.tag.split('}')[-1], len(kids)


def load_shape(path, *, element=None, width_mm=None, height_mm=None,
               origin=(0.0, 0.0), raster_px=DEFAULT_SHAPE_RASTER_PX,
               alpha_thresh=128, trim=True):
    """File -> ShapeMask, scaled so the INK bbox is width_mm / height_mm.

    Rasterising goes through emit_art.rasterise_svg so the shape mask and every
    other raster in this tree come off the same rasteriser -- that function
    documents which one it found and why the choice matters.
    """
    import numpy as np
    from PIL import Image
    p = pathlib.Path(path)
    if not p.exists():
        raise MicrotextRefused(f"--shape {path}: no such file")

    tool = "PIL"
    if p.suffix.lower() == ".svg":
        import tempfile
        import emit_art
        src, kind, nkids = (None, None, None)
        if element is not None:
            src, kind, nkids = _prune_svg(p, element)
        with tempfile.TemporaryDirectory() as td:
            use = p
            if src is not None:
                use = pathlib.Path(td) / "shape.svg"
                use.write_text(src, encoding="utf-8")
            img, tool = emit_art.rasterise_svg(use, raster_px)
        note = (f"{p.name} element[{element}] <{kind}> of {nkids}"
                if element is not None else p.name)
    else:
        img = Image.open(p).convert("RGBA")
        note = p.name

    a = np.asarray(img)
    grid = a[:, :, 3] >= alpha_thresh
    if not grid.any():
        raise MicrotextRefused(
            f"--shape {p.name} rasterised to nothing: no pixel reached alpha "
            f"{alpha_thresh}. If the artwork is opaque on an opaque ground, "
            f"select the shape with --shape-element.")
    if trim:
        ys, xs = np.nonzero(grid)
        grid = grid[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

    rows, cols = grid.shape
    if width_mm is None and height_mm is None:
        raise MicrotextRefused("load_shape needs --shape-width or --shape-height")
    if width_mm is not None and height_mm is not None:
        raise MicrotextRefused(
            "--shape-width and --shape-height both given; the mask has one "
            "aspect ratio and cannot honour both. Pick one.")
    mm_per_px = (width_mm / cols) if width_mm is not None else (height_mm / rows)
    return ShapeMask(grid=grid, mm_per_px=mm_per_px, origin=tuple(origin),
                     source=note, raster_tool=tool)


def merge_openings(quads, dam):
    """Merge any openings closer than `dam` into their convex hull, to fixpoint.

    A mask dam thinner than the floor washes away in processing (the doc's
    words), at which point the two openings merge ANYWAY -- with a ragged edge
    nobody designed. Merging them deliberately gets the same topology with an
    edge that was drawn on purpose.
    """
    cur = [list(q) for q in quads]
    merged = 0
    changed = True
    while changed and len(cur) > 1:
        changed = False
        for i in range(len(cur)):
            for j in range(i + 1, len(cur)):
                if poly_gap(cur[i], cur[j]) < dam - 1e-9:
                    hull = convex_hull(cur[i] + cur[j])
                    cur = [c for k, c in enumerate(cur) if k not in (i, j)] + [hull]
                    merged += 1
                    changed = True
                    break
            if changed:
                break
    return cur, merged


# --- the spec ---------------------------------------------------------------

@dataclass
class MicrotextSpec:
    text: str
    cap_mm: float
    tone: str = "T2"
    at: tuple[float, float] = (0.0, 0.0)
    angle_deg: float = 0.0
    path: list[tuple[float, float]] | None = None
    region: tuple[float, float, float, float] | None = None
    shape: ShapeMask | None = None
    # Shape flow only. `text` is then a continuous body of prose, not a unit to
    # be repeated: it is broken at word boundaries to fit each span the shape
    # offers on each row, and whatever is left over carries to the next span.
    hyphenate: bool = False
    hyphen_min: int = 3          # letters that must stay on each side of a break
    shape_whole_band: bool = True
    separator: str = "   "
    row_gap_mm: float | None = None
    stroke_ratio: float = TEXT_STROKE_RATIO
    # Letter-spacing in em, inserted BETWEEN glyphs. The only lever that widens
    # the inter-glyph gap, which for ordinary prose is the TIGHTEST gap in the
    # artwork -- 4/21 em, tighter than the 'i' stem-to-tittle 5/21 and much
    # tighter than the 'e' counter at 2D = 0.29488. Default 0.0: existing
    # callers get exactly the geometry they got before.
    #
    # KiCad's fp_text has no letter-spacing attribute, so non-zero tracking is
    # realised by emitting ONE fp_text PER GLYPH at the pen offsets. That is
    # exact rather than approximate -- `justify left`'s stroke-dependent slide
    # is a constant translation, so a glyph placed at its own pen offset lands
    # where the same glyph in a whole-string fp_text lands, measured identical
    # to 6.1e-6 em against kicad-cli 10.0.0 -- but it costs one fp_text per
    # character, which for a long body is a much larger file.
    tracking_em: float = 0.0
    mask_bleed_mm: float = DEFAULT_MASK_BLEED_MM
    floor_mm: float | None = None          # vendor override, a bare number
    # A named process from tools/fab_profiles.py. Says the same thing as
    # floor_mm but says WHICH FAB, so the number is sourced and the part can
    # record what it was sized for. Giving both is refused: they are one
    # decision spelled two ways, and nothing here should have to guess which
    # of two disagreeing floors the caller meant.
    fab: str | None = None
    allow_buried: bool = False
    allow_unmeasured: bool = False
    run_tol_deg: float = DEFAULT_RUN_TOL_DEG
    # How this spec's flags are spelled on the command line that built it.
    # emit_art.py prefixes them, so a message that hard-codes "--text" sends the
    # reader looking for a flag that tool does not have.
    flag_prefix: str = ""
    text_flag: str = "--text"

    @property
    def mode(self):
        if self.shape is not None:
            return "shape"
        if self.region is not None:
            return "region"
        if self.path is not None:
            return "path"
        return "line"


@dataclass
class Run:
    text: str
    x: float
    y: float
    angle: float
    quad: list = field(default_factory=list)


# --- the check --------------------------------------------------------------

def measure(spec: MicrotextSpec, s: str) -> stroke_font.StringMetrics:
    """The one place this module measures a string.

    Always at the spec's stroke ratio AND its tracking, so every ink box in
    here is where the letterforms will actually be rather than where a hairline
    pen with default spacing would have put them.
    """
    return stroke_font.measure_string(s, allow_unmeasured=spec.allow_unmeasured,
                                      stroke_ratio=spec.stroke_ratio,
                                      tracking=spec.tracking_em)


def check(spec: MicrotextSpec) -> dict:
    """Everything that can be decided before any geometry is placed.

    Raises MicrotextRefused for anything that cannot be honoured as asked.
    Returns the report skeleton; placement fills in the rest.
    """
    if not spec.text:
        raise MicrotextRefused("--microtext was given an empty string")
    haz = stroke_font.markup_hazards(spec.text)
    if haz:
        raise MicrotextRefused(
            "the string would not be fabricated as written:\n  - " +
            "\n  - ".join(haz) +
            "\n  Microprinting is unreadable without a loupe, so a silent "
            "substitution here is a defect nobody would ever catch.")

    text_layers, mask_layers, cls, notes = plan_tone(
        spec.tone, allow_buried=spec.allow_buried)

    # The ratio and the cap height are needed before the string can be measured:
    # `justify left` justifies the text BOX, so where the letterforms land
    # depends on how heavy the pen is (stroke_font, "Where the anchor actually
    # is"). Measuring first and correcting later would be measuring the wrong
    # thing.
    r = float(spec.stroke_ratio)
    if not (0 < r < 1):
        raise MicrotextRefused(f"--stroke-ratio {r} is not a ratio in (0,1)")
    cap = float(spec.cap_mm)
    if cap <= 0:
        raise MicrotextRefused(f"cap height {cap} mm is not positive")
    stroke = cap * r

    try:
        m = measure(spec, spec.text)
    except stroke_font.UnmeasuredGlyph as e:
        raise MicrotextRefused(
            f"character {e.args[0]!r} (U+{ord(e.args[0]):04X}) has no measured "
            f"metrics. tools/stroke_font.py covers printable ASCII; KiCad's "
            f"stroke font covers far more, but nothing here can state its "
            f"advance or its counters, so neither the layout nor the counter "
            f"check would be true. Re-measure with "
            f"'python tools/stroke_font.py --calibrate', or pass "
            f"--{spec.flag_prefix}allow-unmeasured to place it with the widest "
            f"measured advance and NO counter check.") from None

    if m.ink_em is None:
        raise MicrotextRefused(
            f"{spec.text!r} has no ink at all (only spaces) -- nothing to place")

    # the floor
    doc_floor = floor_for(text_layers[0])[0]
    if doc_floor is None:                       # buried: the doc gives no number
        doc_floor = 0.50
        floor_note = ("PROVISIONAL 0.50 mm -- docs/pcb-palette.md gives no "
                      "buried floor; this matches tools/verify_art.py's "
                      "provisional value and cal_buried exists to measure it")
    else:
        floor_note = f"docs/pcb-palette.md via {pathlib.Path(FLOOR_SOURCE).name}"

    # Three sources, in order of authority: a named fab profile, a bare
    # --floor number, then the palette doc. The doc clause is last and
    # untouched, so a run that names neither behaves exactly as it always did.
    prof = resolve_fab(spec)
    fab_notes: list[str] = []
    if prof is not None:
        if cls == "buried":
            # fab_profiles.FabProfile.floor_for() would hand back min_copper_mm
            # here, which is the OUTER-layer etch limit -- finer than the
            # provisional buried floor, so taking it would loosen the check on
            # the one layer the palette already says will not hold fine detail.
            # No profile in the file publishes a buried number, and
            # fab_profiles' own doctrine is that an unpublished limit is one
            # you have to ask for rather than infer.
            fab_notes.append(
                f"{prof.name} publishes no buried-layer minimum, so the "
                f"PROVISIONAL {doc_floor:g} mm still governs -- the profile's "
                f"{prof.min_copper_mm:.4f} mm is an OUTER-layer etch limit and "
                f"using it here would loosen the check, not tighten it")
            floor = doc_floor
            floor_note += f" (--{spec.flag_prefix}fab {spec.fab} does not reach this layer)"
        else:
            try:
                floor = prof.floor_for(text_layers[0])
            except ValueError as e:
                raise MicrotextRefused(
                    f"--{spec.flag_prefix}fab {spec.fab}: {e}. "
                    f"tools/fab_profiles.py does not fill unpublished limits in "
                    f"with a plausible-looking value, and neither will this: ask "
                    f"the fab, or name a profile that publishes the number.") from None
            floor_note = f"--{spec.flag_prefix}fab {spec.fab}: {prof.name} -- {prof.source}"
            if abs(floor - doc_floor) > 1e-9:
                fab_notes.append(
                    f"{prof.name} {cls} floor is {floor:.4f} mm; "
                    f"docs/pcb-palette.md says {doc_floor:g} mm. The profile "
                    f"wins, and tools/verify_art.py must be run with the same "
                    f"--fab or it will check this part against {doc_floor:g}.")
            if prof.surcharge:
                fab_notes.append(f"{prof.name} COSTS EXTRA: {prof.surcharge}")
    elif spec.floor_mm is not None:
        floor = float(spec.floor_mm)
        floor_note = (f"caller override --{spec.flag_prefix}floor "
                      f"{spec.floor_mm:g} mm (palette says {doc_floor:g} mm)")
    else:
        floor = doc_floor

    rep = {
        "text": spec.text, "tone": spec.tone, "mode": spec.mode,
        "text_layers": list(text_layers), "mask_layers": list(mask_layers),
        "floor_class": cls, "floor_mm": floor, "floor_note": floor_note,
        "fab": (None if prof is None else {
            "key": spec.fab, "name": prof.name, "source": prof.source,
            "surcharge": prof.surcharge,
            "min_copper_mm": prof.min_copper_mm,
            "min_silk_mm": prof.min_silk_mm,
            "min_mask_dam_mm": prof.min_mask_dam_mm}),
        "cap_mm": cap, "stroke_mm": stroke, "stroke_ratio": r,
        "advance_mm": m.advance_em * cap,
        "ink_mm": [v * cap for v in m.ink_em],
        "x_height_mm": stroke_font.X_HEIGHT_EM * cap,
        "glyphs": len(spec.text),
        "notes": list(notes) + fab_notes, "warnings": [], "checks": [],
        "unmeasured": list(m.unmeasured),
    }

    def add(name, value, floor_v, unit="mm", extra=""):
        ok = value >= floor_v - 1e-9
        rep["checks"].append({"name": name, "value": value, "floor": floor_v,
                              "ok": ok, "unit": unit, "note": extra})
        return ok

    # THE CONSTRAINT SET.
    #
    # min_copper_mm is minimum trace width AND SPACING. This block used to check
    # the width and one kind of spacing -- the enclosed counter -- and nothing
    # else, which is how a part shipped with 0.026 mm between the crossbars of
    # 'r' and 't' against a 0.0889 mm floor. stroke_font.gap_constraints() now
    # returns every gap in the string, and all of them are checked here by the
    # same arithmetic, so a new kind of gap cannot be added there and forgotten
    # here.
    cons = stroke_font.gap_constraints(m)
    rep["tracking_em"] = float(spec.tracking_em)
    rep["tracking_mm"] = float(spec.tracking_em) * cap
    rep["gaps"] = []
    ok_stroke = ok_counter = True
    for c in cons:
        clear = c.clear_mm(cap, stroke)
        rep["gaps"].append({
            "name": c.name, "em": c.em, "detail": c.detail,
            "trackable": c.trackable, "clear_mm": clear,
            "ok": clear >= floor - 1e-9,
            "min_cap_mm": c.min_cap_mm(floor, r)})
        if c.name == "stroke":
            ok_stroke = add("stroke width", clear, floor,
                            extra=f"1:{1/r:.1f} of the cap height")
        else:
            ok = add(f"{c.name} gap", clear, floor, extra=c.detail)
            if c.name == "counter":
                ok_counter = ok

    # Every counter in the string, not only the tightest -- the tightest is what
    # binds, the rest are what a reader sees close up first.
    rep["counters"] = []
    for ch, em in sorted(m.counter_chars.items(), key=lambda kv: kv[1]):
        clear = stroke_font.counter_clear_mm(em, cap, stroke)
        rep["counters"].append({"char": ch, "em": em, "clear_mm": clear,
                                "ok": clear >= floor - 1e-9})
    if m.counter_em is not None:
        rep["counter"] = {"char": m.counter_char, "em": m.counter_em,
                          "clear_mm": stroke_font.counter_clear_mm(
                              m.counter_em, cap, stroke)}
    else:
        rep["counter"] = None
        rep["checks"].append({
            "name": "counter gap", "value": None, "floor": floor,
            "ok": True, "unit": "mm",
            "note": "no closed letterforms in this string -- but the "
                    "inter-glyph and intra-glyph gaps above still bind"})

    # The dot classification, tested rather than assumed. stroke_font drops
    # dot-sized voids from the counter table on the grounds that they are solid
    # ink; that is true only while the pen is at least as wide as the dot, and a
    # half-open tittle is a sub-floor void that nothing else here would see.
    if not stroke_font.dots_are_solid(r):
        gapmm = (stroke_font.DOT_VOID_MAX_EM - r) * cap
        rep["warnings"].append(
            f"at 1:{1/r:.1f} the stroke font's dots are NOT solid: the widest "
            f"is {stroke_font.DOT_VOID_MAX_EM:.6f} em against a {r:.6f} em pen, "
            f"leaving a {gapmm:.4f} mm void inside a tittle. stroke_font's "
            f"counter table EXCLUDES dots on the assumption that they fill in, "
            f"so that void is checked by nothing. Use a heavier pen.")

    legible = LEGIBLE_MM.get(cls, 0.9)
    rep["legible_mm"] = legible
    ok_legible = add("cap height", cap, legible, extra="legibility, not fab")

    # smallest cap height that works, for this string on this layer
    h_fab, binding = stroke_font.min_cap_for_floor(floor, r, m)
    h_min = max(h_fab, legible)
    rep["min_cap"] = {
        "fab_mm": h_fab, "binding": binding, "legible_mm": legible,
        "recommended_mm": (math.inf if math.isinf(h_min)
                           else math.ceil(h_min * 200 - 1e-9) / 200),
        "limited_by": "legibility" if legible > h_fab else binding,
    }
    # The ratio that would make this string as small as it can be, and the cap
    # it would reach. A caller who is refused wants to know not only "raise the
    # cap" but "or change the pen": at the default 1:6.7 the counter is loose
    # and the SPACING binds, and no cap height fixes a ratio problem.
    try:
        r_opt, _ = stroke_font.optimum_ratio(m)
        h_opt, b_opt = stroke_font.min_cap_for_floor(floor, r_opt, m)
        rep["optimum"] = {"stroke_ratio": r_opt, "cap_mm": h_opt,
                          "binding": b_opt, "stroke_mm": r_opt * h_opt}
    except ValueError:
        rep["optimum"] = None
    # Which real processes can build this, as opposed to which abstract tiers
    # it clears. The tier table this replaced listed "0.090 mm advanced, at
    # extra cost", which no profile in tools/fab_profiles.py actually sells --
    # and a part sized against a number nobody quotes is a part with no fab.
    # Every row here is a named process with a source URL, and the minimum cap
    # is computed by the SAME stroke_font.min_cap_for_floor the refusal above
    # uses, not by fab_profiles.min_cap_height_mm, whose 6.7 / 0.147 constants
    # disagree with this run's ratio and this string's measured counter.
    rep["vendor"] = []
    if cls in ("copper", "silk"):
        for key in sorted(fab_profiles.PROFILES,
                          key=lambda k: fab_profiles.PROFILES[k].min_copper_mm):
            p = fab_profiles.PROFILES[key]
            try:
                f = p.floor_for(text_layers[0])
            except ValueError:
                rep["vendor"].append({"key": key, "floor_mm": None,
                                      "label": p.name, "min_cap_mm": None,
                                      "binding": "unpublished", "ok": None,
                                      "surcharge": p.surcharge})
                continue
            hv, bind = stroke_font.min_cap_for_floor(f, r, m)
            rep["vendor"].append({"key": key, "floor_mm": f, "label": p.name,
                                  "min_cap_mm": max(hv, legible),
                                  "binding": ("legibility" if legible > hv
                                              else bind),
                                  "ok": cap >= max(hv, legible) - 1e-9,
                                  "surcharge": p.surcharge})

    if not (RATIO_BAND[0] - 1e-9 <= r <= RATIO_BAND[1] + 1e-9):
        rep["warnings"].append(
            f"stroke ratio 1:{1/r:.1f} is outside the 1:6 to 1:8 legible band "
            f"docs/pcb-palette.md gives; the strokes will read as "
            f"{'too heavy -- counters close' if r > RATIO_BAND[1] else 'too light'}")
    if m.unmeasured:
        rep["warnings"].append(
            f"{len(m.unmeasured)} character(s) have no measured metrics "
            f"({''.join(m.unmeasured)!r}): placed at the widest measured advance "
            f"({stroke_font.MAX_ADVANCE_EM:.3f} em) and EXCLUDED from the counter "
            f"check. The narrowest counter reported below is therefore a lower "
            f"bound on the risk, not a verdict on the whole string.")

    fails = [c for c in rep["checks"] if not c["ok"]]
    if fails:
        rec = rep["min_cap"]["recommended_mm"]
        # 5 dp, not 4: at the boundary a counter of 0.09996 mm rounds to
        # "0.1000 mm is under the 0.100 mm floor", which reads like a bug in the
        # tool rather than a 40 nm shortfall in the design.
        detail = "\n  - ".join(
            f"{c['name']} {c['value']:.5f} mm is under the "
            f"{c['floor']:.3f} mm {'legibility floor' if c['name'] == 'cap height' else cls + ' floor'}"
            + (f" ({c['note']})" if c['note'] else "")
            for c in fails)
        extra = ""
        if cls == "silk":
            extra = ("\n  Silk is a mesh screen print; copper is etched and about "
                     "twice as fine. docs/pcb-palette.md: silk microtext is "
                     "\"not microprinting, just small text\". If you want "
                     "microprinting, use T2 or T6 on copper.")
        # The "nothing was clamped" line only means anything when clamping was
        # the temptation -- i.e. when the STROKE is what fell under the floor.
        # At a large cap height with a silly ratio the stroke is already fat and
        # raising it to the floor would make it thinner, so saying it would fill
        # the counters solid is simply false.
        clamp = ""
        if not ok_stroke:
            clamp = (f"\n  Nothing was clamped: a stroke raised to the floor at "
                     f"this cap height would be 1:{cap/floor:.1f}, which fills "
                     f"the counters solid.")
        raise MicrotextRefused(
            f"cap height {cap:.3f} mm will not image on "
            f"{'/'.join(text_layers)} ({cls}):\n  - {detail}\n"
            f"  Smallest cap height that clears every check for {spec.text!r} "
            f"on this layer: {rec:.3f} mm "
            f"(limited by {rep['min_cap']['limited_by']}).{extra}{clamp}")

    assert ok_stroke and ok_counter and ok_legible
    return rep


# --- placement --------------------------------------------------------------

def _row_text(spec, per_mm, width_mm):
    """Repeat the string with its separator until one more would overflow."""
    unit = spec.text + spec.separator
    one = per_mm(spec.text)
    if one > width_mm + 1e-9:
        raise MicrotextRefused(
            f"{spec.text!r} is {one:.3f} mm wide at a {spec.cap_mm:g} mm cap "
            f"height and the region is only {width_mm:.3f} mm wide. Refusing to "
            f"truncate the string: widen the region, or drop the cap height to "
            f"{spec.cap_mm * width_mm / one:.3f} mm (check it against the floor "
            f"first -- it may not be legal).")
    s, w = spec.text, one
    while True:
        cand = s + spec.separator + spec.text
        cw = per_mm(cand)
        if cw > width_mm + 1e-9:
            return s, w
        s, w = cand, cw


def _runs_line(spec, m, cap):
    return [Run(spec.text, spec.at[0], spec.at[1], spec.angle_deg)]


def _runs_region(spec, m, cap, rep):
    x0, y0, x1, y1 = spec.region
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0

    # "Fill this rectangle" has to mean the LETTERFORMS stay inside it, so the
    # pen is paid for on every edge. Fitting to the centreline box instead puts
    # half a stroke of ink outside the region on all four sides -- 0.05 mm at a
    # 0.7 mm cap, which is the whole mask registration budget.
    pen = rep["stroke_mm"] / 2.0

    def inkw(s):
        b = measure(spec, s).ink_em
        return 0.0 if b is None else (b[2] - b[0]) * cap + 2 * pen

    row, row_w = _row_text(spec, inkw, x1 - x0)
    rm = measure(spec, row)
    ix0, iy0, ix1, iy1 = [v * cap for v in rm.ink_em]
    ix0, iy0, ix1, iy1 = ix0 - pen, iy0 - pen, ix1 + pen, iy1 + pen
    ink_h = iy1 - iy0

    floor = rep["floor_mm"]
    gap = spec.row_gap_mm if spec.row_gap_mm is not None else max(floor, 0.25 * cap)
    if gap < floor - 1e-9:
        rep["warnings"].append(
            f"--row-gap {gap:.4f} mm leaves less than the {floor:.3f} mm "
            f"{rep['floor_class']} floor between the ink of adjacent rows; "
            f"descenders and ascenders will touch and the rows will read as one "
            f"block. Not clamped -- this is what you asked for.")
    pitch = ink_h + gap
    rep["row_pitch_mm"] = pitch
    rep["row_gap_mm"] = gap
    rep["row_text"] = row
    rep["repeats_per_row"] = row.count(spec.text)

    nrows = int(math.floor((y1 - y0 - ink_h) / pitch + 1e-9)) + 1
    if nrows < 1:
        raise MicrotextRefused(
            f"one row of {spec.text!r} is {ink_h:.3f} mm tall at a "
            f"{cap:g} mm cap height and the region is only {y1-y0:.3f} mm tall. "
            f"Refusing to place a row that would spill out of the region.")
    runs = []
    for i in range(nrows):
        ay = y0 - iy0 + i * pitch
        runs.append(Run(row, x0 - ix0, ay, 0.0))
    rep["rows"] = nrows
    used = ink_h + (nrows - 1) * pitch
    if y1 - y0 - used > pitch:
        rep["warnings"].append(
            f"{y1-y0-used:.3f} mm of the region is left empty below the last "
            f"row -- the pitch does not divide the region height")
    return runs


def _runs_shape(spec, m, cap, rep):
    """Flow one continuous body of prose into a shape mask.

    This is not the region mode with a stencil over it. Region mode repeats a
    string; here the string is a TEXT, and the shape is drawn by where its
    lines have to stop. Each row asks the mask for the x spans it may write in,
    each span is filled greedily on word boundaries, and whatever did not fit
    carries to the next span -- so the line lengths are the silhouette and the
    prose stays continuous and in order.

    Vertical metrics are taken ONCE, from the whole body, and every run in
    every row is anchored against them. Measuring each chunk's own ink box
    instead would sit a chunk with no descender lower than its neighbour and
    the rows would visibly stagger.
    """
    shape = spec.shape
    pen = rep["stroke_mm"] / 2.0

    def inkw(s):
        b = measure(spec, s).ink_em
        return 0.0 if b is None else (b[2] - b[0]) * cap + 2 * pen

    def ink_left(s):
        b = measure(spec, s).ink_em
        return 0.0 if b is None else b[0] * cap - pen

    # one vertical box for every row, from the whole body
    if m.ink_em is None:
        raise MicrotextRefused("the body has no ink at all")
    ry0 = m.ink_em[1] * cap - pen
    ry1 = m.ink_em[3] * cap + pen
    ink_h = ry1 - ry0

    floor = rep["floor_mm"]
    gap = spec.row_gap_mm if spec.row_gap_mm is not None else floor
    if gap < floor - 1e-9:
        rep["warnings"].append(
            f"--row-gap {gap:.4f} mm leaves less than the {floor:.3f} mm "
            f"{rep['floor_class']} floor between the ink of adjacent rows; "
            f"ascenders and descenders will touch and the rows will read as "
            f"one block. Not clamped -- this is what you asked for.")
    pitch = ink_h + gap

    words = spec.text.split()
    if not words:
        raise MicrotextRefused("the body is entirely whitespace")

    wi = 0                       # index of the next whole word
    tail = ""                    # remainder of a hyphenated word, if any
    runs = []
    rows_used = 0
    spans_total = 0
    spans_filled = 0
    narrow = []                  # spans that could not take even one word
    y = shape.origin[1]
    nrows = 0

    while y + ink_h <= shape.origin[1] + shape.height_mm + 1e-9:
        nrows += 1
        spans = shape.band_spans(y, y + ink_h,
                                 whole_band=spec.shape_whole_band)
        placed_this_row = False
        for sx0, sx1 in spans:
            spans_total += 1
            avail = sx1 - sx0
            if wi >= len(words) and not tail:
                break
            chunk = tail
            tail = ""
            if chunk and inkw(chunk) > avail + 1e-9:
                # the carried fragment does not even fit; put it back whole
                tail = chunk
                chunk = ""
            while wi < len(words):
                cand = (chunk + " " + words[wi]) if chunk else words[wi]
                if inkw(cand) > avail + 1e-9:
                    break
                chunk = cand
                wi += 1
            if not chunk and spec.hyphenate and wi < len(words):
                w = words[wi]
                for k in range(len(w) - spec.hyphen_min,
                               spec.hyphen_min - 1, -1):
                    if inkw(w[:k] + "-") <= avail + 1e-9:
                        chunk = w[:k] + "-"
                        tail = w[k:]
                        wi += 1
                        break
            if not chunk:
                narrow.append((y, sx0, sx1, avail))
                continue
            runs.append(Run(chunk, sx0 - ink_left(chunk), y - ry0, 0.0))
            spans_filled += 1
            placed_this_row = True
        if placed_this_row:
            rows_used += 1
        y += pitch

    left_words = len(words) - wi
    rep["row_pitch_mm"] = pitch
    rep["row_gap_mm"] = gap
    rep["row_ink_mm"] = ink_h
    rep["rows"] = nrows
    rep["rows_with_text"] = rows_used
    rep["spans_total"] = spans_total
    rep["spans_filled"] = spans_filled
    rep["spans_empty"] = len(narrow)
    rep["words_total"] = len(words)
    rep["words_placed"] = wi
    rep["chars_placed"] = sum(len(r.text) for r in runs)
    rep["chars_total"] = len(spec.text)
    rep["shape_source"] = shape.source
    rep["shape_raster_tool"] = shape.raster_tool
    rep["shape_mm"] = [shape.width_mm, shape.height_mm]
    rep["shape_area_mm2"] = shape.area_mm2()
    rep["hyphenated"] = bool(spec.hyphenate)

    if narrow:
        w_min = min(n[3] for n in narrow)
        w_max = max(n[3] for n in narrow)
        rep["warnings"].append(
            f"{len(narrow)} of {spans_total} mask spans were left empty: they "
            f"are {w_min:.3f}-{w_max:.3f} mm wide and the next word in the "
            f"text did not fit"
            + ("" if spec.hyphenate else
               " (no hyphenation -- pass --shape-hyphenate to break words)")
            + ". No text was dropped; it flowed on to the next span. Those "
              "parts of the shape are simply blank.")
    if left_words:
        rest = " ".join(words[wi:])
        raise MicrotextRefused(
            f"the shape filled up with {left_words} word(s) "
            f"({len(rest)} characters) of the body still unplaced, starting "
            f"{rest[:60]!r}. Refusing to truncate the text silently. Either "
            f"enlarge the shape, drop the cap height, or pass a shorter body. "
            f"{wi}/{len(words)} words fit at a {cap:.4f} mm cap in a "
            f"{shape.width_mm:.2f} x {shape.height_mm:.2f} mm shape.")
    if not runs:
        raise MicrotextRefused(
            f"no span in the shape was wide enough for a single word at a "
            f"{cap:.4f} mm cap height")
    return runs


def _polyline(path):
    segs, total = [], 0.0
    for a, b in zip(path, path[1:]):
        L = math.hypot(b[0]-a[0], b[1]-a[1])
        if L <= 1e-12:
            continue
        segs.append((a, b, L, total))
        total += L
    if not segs:
        raise MicrotextRefused("--path has no length: every point is the same")
    return segs, total


def _at_arc(segs, total, s):
    """Point and heading at arc length s, extended past the ends rather than
    clamped -- text that overruns must stay readable and be REPORTED, not be
    silently piled up on the final vertex."""
    for a, b, L, s0 in segs:
        if s <= s0 + L or (a, b, L, s0) is segs[-1]:
            t = (s - s0) / L
            ux, uy = (b[0]-a[0]) / L, (b[1]-a[1]) / L
            return (a[0] + ux * t * L, a[1] + uy * t * L), (ux, uy)
    a, b, L, s0 = segs[0]
    return a, ((b[0]-a[0]) / L, (b[1]-a[1]) / L)


def _runs_path(spec, m, cap, rep):
    segs, total = _polyline(spec.path)
    rep["path_length_mm"] = total
    # Tracking is inserted BETWEEN glyphs, so the first glyph does not carry it
    # -- same convention as stroke_font.measure_string, or the path arithmetic
    # and the ink box would disagree by one tracking step.
    t = float(spec.tracking_em)
    adv = [(stroke_font.GLYPHS.get(ch, (stroke_font.MAX_ADVANCE_EM, None,
                                        None))[0] + (t if i else 0.0)) * cap
           for i, ch in enumerate(spec.text)]
    text_len = sum(adv)
    rep["advance_mm"] = text_len
    if text_len > total + 1e-9:
        rep["warnings"].append(
            f"the string is {text_len:.3f} mm long at this cap height and the "
            f"path is only {total:.3f} mm; the last "
            f"{text_len-total:.3f} mm runs on past the end of the path along "
            f"the final segment's direction. Nothing was dropped -- shorten the "
            f"string, lengthen the path, or drop the cap height.")

    runs, cur, pen = [], None, 0.0
    for ch, w in zip(spec.text, adv):
        p, u = _at_arc(segs, total, pen + w / 2.0)
        ang = math.degrees(math.atan2(-u[1], u[0]))
        if cur is not None and abs(_angdiff(ang, cur[3])) <= spec.run_tol_deg:
            cur[0] += ch
        else:
            if cur is not None:
                runs.append(Run(*cur))
            sp, su = _at_arc(segs, total, pen)
            sang = math.degrees(math.atan2(-su[1], su[0]))
            cur = [ch, sp[0], sp[1], sang]
        pen += w
    if cur is not None:
        runs.append(Run(*cur))
    return runs


def _angdiff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def place(spec: MicrotextSpec, rep: dict) -> tuple[list[Run], list[list], dict]:
    """-> (runs, mask openings, rep). rep is updated in place."""
    cap = rep["cap_mm"]
    m = measure(spec, spec.text)
    if spec.mode == "shape":
        runs = _runs_shape(spec, m, cap, rep)
    elif spec.mode == "region":
        runs = _runs_region(spec, m, cap, rep)
    elif spec.mode == "path":
        runs = _runs_path(spec, m, cap, rep)
    else:
        runs = _runs_line(spec, m, cap)

    # A run can come out with no ink at all -- along a path, the tangent can
    # change exactly at a space, leaving a run that is nothing but spaces. It
    # has no letterforms to open the mask over and nothing to draw, so it is
    # dropped and counted. This is not image content going missing; a space is
    # advance, and the advance was already spent positioning the runs on either
    # side of it.
    blank = [r for r in runs if measure(spec, r.text).ink_em is None]
    if blank:
        runs = [r for r in runs if r not in blank]
        rep["blank_runs"] = len(blank)
        rep["notes"].append(
            f"{len(blank)} run(s) contained only spaces and were not emitted "
            f"(no ink, so nothing to draw and nothing to open the mask over)")
    if not runs:
        raise MicrotextRefused("every run came out blank -- nothing to place")
    for r in runs:
        box = tuple(v * cap for v in measure(spec, r.text).ink_em)
        r.quad = box_quad(r.x, r.y, box, r.angle)

    rep["runs"] = len(runs)
    rep["glyphs"] = sum(len(r.text) for r in runs)

    openings: list[list] = []
    rep["mask_bleed_mm"] = float(spec.mask_bleed_mm)
    if rep["mask_layers"]:
        # The run quads are CENTRELINE boxes, and half the pen sticks out past
        # every one of their edges. The bleed the caller asked for is clearance
        # from the LETTERFORMS, so the pen has to be paid for here -- otherwise
        # a 0.15 mm bleed silently becomes 0.0975 mm of real clearance at a
        # 0.105 mm stroke, and the number in the report would be a fiction.
        bleed = float(spec.mask_bleed_mm) + rep["stroke_mm"] / 2.0
        if spec.mask_bleed_mm < MASK_REGISTRATION_MM - 1e-9:
            rep["warnings"].append(
                f"--mask-bleed {spec.mask_bleed_mm:.4f} mm is under the "
                f"{MASK_REGISTRATION_MM} mm mask registration tolerance, so a "
                f"worst-case misregistration puts the opening edge INSIDE the "
                f"letterforms and the block stops being a block. Not clamped.")
        if spec.mode in ("region", "shape"):
            # One opening over the whole block: the doc's form 1, exactly.
            # Shape flow gets the same treatment and for the same reason --
            # mask registration is +/-0.05 mm against a ~0.10 mm stroke, so an
            # opening that tried to follow the silhouette would need its edge
            # placed to a tolerance the process does not have. The block
            # opening only has to place its own four edges, and the shape is
            # still drawn: it is drawn by the COPPER, which is what the reader
            # sees as gold against bare laminate.
            xs = [p[0] for r in runs for p in r.quad]
            ys = [p[1] for r in runs for p in r.quad]
            openings = [[(min(xs) - bleed, min(ys) - bleed),
                         (max(xs) + bleed, min(ys) - bleed),
                         (max(xs) + bleed, max(ys) + bleed),
                         (min(xs) - bleed, max(ys) + bleed)]]
            rep["openings_merged"] = 0
        else:
            # The dam decides which openings MERGE, so it is a sizing number,
            # not a warning: get it wrong and the emitted geometry is wrong.
            dam, dam_src = FLOOR_MASK_DAM, "docs/pcb-palette.md"
            fabrep = rep.get("fab")
            if fabrep is not None:
                if fabrep["min_mask_dam_mm"] is None:
                    raise MicrotextRefused(
                        f"{fabrep['name']} publishes no minimum mask dam, and "
                        f"{spec.mode} placement decides which of {len(runs)} run "
                        f"openings merge by comparing their gaps against it. "
                        f"Assuming the palette's {FLOOR_MASK_DAM:.2f} mm would "
                        f"bake a guessed vendor limit into the geometry, which "
                        f"is exactly what tools/fab_profiles.py refuses to do. "
                        f"Ask the fab, or use --{spec.flag_prefix}region / "
                        f"--{spec.flag_prefix}shape, which cut ONE block "
                        f"opening and never need a dam at all.")
                dam, dam_src = fabrep["min_mask_dam_mm"], fabrep["name"]
            rep["mask_dam_mm"] = dam
            quads = [inflate_quad(r.quad, bleed) for r in runs]
            openings, merged = merge_openings(quads, dam)
            rep["openings_merged"] = merged
            if merged:
                rep["notes"].append(
                    f"{merged} pair(s) of run openings sat closer than the "
                    f"{dam:.2f} mm mask dam ({dam_src}) and were merged into one "
                    f"opening -- a thinner dam washes away in processing")
    rep["openings"] = len(openings)

    xs = [p[0] for r in runs for p in r.quad] + [p[0] for o in openings for p in o]
    ys = [p[1] for r in runs for p in r.quad] + [p[1] for o in openings for p in o]
    rep["bbox_mm"] = [min(xs), min(ys), max(xs), max(ys)]
    rep["block_mm"] = [max(xs) - min(xs), max(ys) - min(ys)]
    return runs, openings, rep


# --- emission ---------------------------------------------------------------

def _placements(spec: MicrotextSpec, run: Run, cap: float):
    """One run -> the (text, x, y, angle) items that draw it.

    With no tracking this is the run itself, one fp_text, byte-for-byte what
    this module has always emitted. KiCad's fp_text carries no letter-spacing
    attribute, so tracking is realised the only exact way there is: one fp_text
    per glyph, anchored at its own pen offset.

    That is exact, not an approximation, and the reason is the one thing
    stroke_font already had to measure about `justify left` -- the slide it
    applies as the pen gets heavier is a CONSTANT TRANSLATION, independent of
    the string. So a glyph placed alone at pen offset p lands exactly where the
    same glyph sits inside a whole-string fp_text at the same offset. Checked
    against kicad-cli 10.0.0 on 'rtiffe' at a 1:8.4 pen: the two renders agree
    to 6.1e-6 em, which is the SVG writer's own rounding and 19,000x under the
    0.0889 mm floor at the cap heights this is used at.

    Spaces are advanced over, never emitted: an fp_text holding one space draws
    no ink, and a footprint full of them is noise in every downstream audit.
    """
    t = float(spec.tracking_em)
    if not t:
        return [(run.text, run.x, run.y, run.angle)]
    out = []
    pen = 0.0
    for i, ch in enumerate(run.text):
        if i:
            pen += t
        adv = stroke_font.GLYPHS.get(ch, (stroke_font.MAX_ADVANCE_EM,
                                          None, None))[0]
        if ch != " ":
            dx, dy = rotate(pen * cap, 0.0, run.angle)
            out.append((ch, run.x + dx, run.y + dy, run.angle))
        pen += adv
    return out


def emit(fp, spec: MicrotextSpec) -> dict:
    """Place `spec` into an emit_art.ArtFp. -> report dict.

    The stroke is passed to the writer EXPLICITLY rather than letting
    Fp.text()'s thickness=None default raise it to the floor. Both produce the
    same number here, because check() has already refused any cap height whose
    ratio-derived stroke lands under the floor -- but passing it explicitly
    leaves coupon_ladders.Fp's own floor guard live and armed underneath this
    module, so if the arithmetic above were ever wrong the writer would say so
    on stderr instead of quietly rescuing it.
    """
    rep = check(spec)
    runs, openings, rep = place(spec, rep)

    # Stamp the process into the footprint's tags.
    #
    # This is the whole fix for "a part cannot emit and then fail its own
    # verifier". A --fab flag on both tools is not enough on its own: it only
    # means the same number CAN be used twice, and it is used twice only if a
    # human remembers to type it twice. Six months from now the part is a file
    # in a library and the command line that made it is gone.
    #
    # So the floor travels WITH the artwork. tools/verify_art.py reads this tag
    # back and checks the part against the process it was sized for, whether or
    # not anyone passes it a flag. `tags` rather than `descr` because tags are
    # a keyword list by KiCad's own convention, they survive a round trip
    # through the footprint editor, and the descr belongs to the caller's prose.
    if rep.get("fab"):
        tag = f"{FAB_TAG_PREFIX}{rep['fab']['key']}"
        cur = (getattr(fp, "tags", "") or "").split()
        stale = [t for t in cur if t.startswith(FAB_TAG_PREFIX) and t != tag]
        if stale:
            raise MicrotextRefused(
                f"this footprint is already tagged {' '.join(stale)} but is "
                f"being emitted for {tag}. Two processes cannot both be the one "
                f"this part was sized for, and the tag is what the verifier "
                f"believes -- emit it under its own name instead.")
        if tag not in cur:
            fp.tags = " ".join(cur + [tag])

    for layer in rep["mask_layers"]:
        for o in openings:
            fp.poly(o, layer)
    placements = [p for r in runs for p in _placements(spec, r, rep["cap_mm"])]
    for layer in rep["text_layers"]:
        for text, x, y, ang in placements:
            fp.text_rot(text, x, y, rep["cap_mm"], layer,
                        thickness=rep["stroke_mm"], angle=ang)
    rep["fp_items"] = len(openings) * len(rep["mask_layers"]) + \
        len(placements) * len(rep["text_layers"])
    rep["fp_poly"] = len(openings) * len(rep["mask_layers"])
    rep["fp_text"] = len(placements) * len(rep["text_layers"])
    rep["fp_text_per_run"] = len(placements) / max(len(runs), 1)

    # The geometry, handed back so a CALLER can audit it. microtext draws its
    # letterforms as fp_text -- a stroke-font instruction, not an outline -- so
    # nothing downstream can recover where the ink lands by parsing the
    # footprint. emit_art.py's copper-to-cut and window-intrusion audits work on
    # polygons, and without this they see microtext copper as ABSENT and report
    # "no copper near the cut" about a footprint with copper text sitting in the
    # middle of the slug. That is worse than not auditing at all, so the ink
    # envelope goes back up the call: each run's centreline quad grown by half
    # the pen, which is the outer bound of the letterforms, and the mask
    # openings as drawn.
    #
    # It is an ENVELOPE, not the glyph outlines: a run of text is audited as the
    # box it occupies. Conservative in the safe direction -- it can report a
    # clearance breach for a letter whose nearest actual stroke is a fraction of
    # a cap height further in, and it cannot miss one.
    rep["_geometry"] = {
        "ink": [[tuple(p) for p in inflate_quad(r.quad, rep["stroke_mm"] / 2.0)]
                for r in runs],
        "openings": [[tuple(p) for p in o] for o in openings],
        "text_layers": list(rep["text_layers"]),
        "mask_layers": list(rep["mask_layers"]),
        "envelope": True,
    }
    return rep


# --- report -----------------------------------------------------------------

def print_report(rep, out=None):
    w = (out or sys.stdout).write
    w("\n  " + "-" * 74 + "\n")
    t = rep["text"]
    w(f"  MICROTEXT  {t!r}\n" if len(t) <= 58 else
      f"  MICROTEXT  {len(t)} characters, {t[:28]!r} ... {t[-24:]!r}\n")
    w("  " + "-" * 74 + "\n")
    for n in rep["notes"]:
        w(f"  note    : {n}\n")
    w(f"  tone    : {rep['tone']}  letterforms on "
      f"{'+'.join(rep['text_layers'])}"
      + (f", block opening on {'+'.join(rep['mask_layers'])}"
         if rep["mask_layers"] else ", no mask opening") + "\n")
    w(f"  floor   : {rep['floor_mm']:.3f} mm ({rep['floor_class']}) "
      f"[{rep['floor_note']}]\n")
    w(f"  mode    : {rep['mode']}  {rep['runs']} run(s), {rep['glyphs']} glyph(s), "
      f"{rep['openings']} opening(s)\n")

    w("\n  check                     value      floor    margin\n")
    w("  " + "-" * 60 + "\n")
    for c in rep["checks"]:
        if c["value"] is None:
            w(f"  {c['name']:<22}         -          -         -   {c['note']}\n")
            continue
        w(f"  {c['name']:<22} {c['value']:8.4f}   {c['floor']:7.3f}  "
          f"{c['value']-c['floor']:+8.4f}  {'OK ' if c['ok'] else 'FAIL'}"
          f"  {c['note']}\n")
    w("  " + "-" * 60 + "\n")

    if rep.get("gaps"):
        w(f"\n  every gap the {rep['floor_mm']:.4f} mm floor governs "
          f"(it is minimum WIDTH and SPACING):\n")
        w(f"    {'constraint':<13}{'em':>10}{'x/21':>9}{'clear mm':>11}"
          f"{'margin':>10}  {'min cap':>8}  track?\n")
        for g in rep["gaps"]:
            em = "  -" if g["em"] is None else f"{g['em']:.6f}"
            t21 = "  -" if g["em"] is None else f"{g['em']*21:.4f}"
            w(f"    {g['name']:<13}{em:>10}{t21:>9}{g['clear_mm']:11.4f}"
              f"{g['clear_mm']-rep['floor_mm']:+10.4f}  "
              f"{g['min_cap_mm']:8.4f}  {'yes' if g['trackable'] else 'no'}"
              f"   {'OK' if g['ok'] else 'FAIL'}\n")
        if rep.get("tracking_em"):
            w(f"    tracking {rep['tracking_em']:.6f} em = "
              f"{rep['tracking_em']*21:.4f}/21 = {rep['tracking_mm']:.4f} mm, "
              f"added between glyphs. It widens the inter-glyph row and "
              f"NOTHING else.\n")
        else:
            w("    tracking 0 -- the inter-glyph row is the font's own "
              "sidebearings. --tracking widens it; nothing widens the rest.\n")
    if rep["counters"]:
        w("\n  counters in this string (clear width = 2*D*cap - stroke):\n")
        for c in rep["counters"]:
            w(f"    {c['char']!r:4} D={c['em']:.5f} em   clear "
              f"{c['clear_mm']:7.4f} mm   {'OK' if c['ok'] else 'FAIL'}\n")
    else:
        w("\n  counters: none -- this string has no closed letterforms. That "
          "does NOT\n            make it safe: the inter-glyph and intra-glyph "
          "gaps above are\n            tighter than most counters and bind "
          "regardless.\n")
    if rep.get("optimum"):
        o = rep["optimum"]
        w(f"\n  smallest this string can be made, over every stroke ratio:\n"
          f"    cap {o['cap_mm']:.4f} mm at 1:{1/o['stroke_ratio']:.4f} "
          f"(stroke {o['stroke_mm']:.4f} mm), binding on {o['binding']}\n")

    mc = rep["min_cap"]
    w(f"\n  smallest cap height that clears every check for this string on "
      f"{'/'.join(rep['text_layers'])}:\n"
      f"    {mc['recommended_mm']:.3f} mm   (limited by {mc['limited_by']}; "
      f"fab needs {mc['fab_mm']:.4f}, legibility needs {mc['legible_mm']:.2f})\n")

    if rep["vendor"]:
        w("\n  who can build this -- tools/fab_profiles.py, named processes "
          "with published limits\n")
        for v in rep["vendor"]:
            here = "  <-- THIS RUN" if (rep.get("fab") or {}).get("key") == v["key"] else ""
            if v["floor_mm"] is None:
                w(f"    {'unpub.':>8} {v['label']:<28} floor UNPUBLISHED -- ask "
                  f"the fab{here}\n")
                continue
            cost = f"  [{v['surcharge']}]" if v["surcharge"] else ""
            w(f"    {v['floor_mm']:8.4f} {v['label']:<28} needs cap >= "
              f"{v['min_cap_mm']:.4f} mm  {'OK' if v['ok'] else 'TOO SMALL'}"
              f"  ({v['binding']}-limited){cost}{here}\n")

    if rep.get("fab"):
        f = rep["fab"]
        w(f"\n  fab     : {f['name']}  [{f['key']}]\n"
          f"            source {f['source']}\n")
        if f["surcharge"]:
            w(f"            SURCHARGE: {f['surcharge']}\n")
        w(f"            run tools/verify_art.py --fab {f['key']} on the output, "
          f"or it checks\n            this part against the palette doc instead "
          f"of against this process\n")

    b = rep["block_mm"]
    w(f"\n  block   : {b[0]:.3f} x {b[1]:.3f} mm at "
      f"({rep['bbox_mm'][0]:.3f}, {rep['bbox_mm'][1]:.3f})\n")
    if rep["mask_layers"]:
        w(f"  opening : {rep['openings']} block opening(s), "
          f"{rep.get('mask_bleed_mm', DEFAULT_MASK_BLEED_MM):.3f} mm clear of "
          f"the letterforms on every side (mask registration is "
          f"+/-{MASK_REGISTRATION_MM} mm) -- over the block, never per glyph\n")
    if rep["mode"] == "shape":
        w(f"  shape   : {rep['shape_source']} via {rep['shape_raster_tool']}, "
          f"{rep['shape_mm'][0]:.3f} x {rep['shape_mm'][1]:.3f} mm, "
          f"{rep['shape_area_mm2']:.2f} mm2 of fillable area\n")
        w(f"  rows    : {rep['rows']} band(s) across the shape, "
          f"{rep['rows_with_text']} carrying text; pitch "
          f"{rep['row_pitch_mm']:.4f} mm = {rep['row_ink_mm']:.4f} mm ink + "
          f"{rep['row_gap_mm']:.4f} mm gap\n")
        w(f"  spans   : {rep['spans_filled']}/{rep['spans_total']} mask spans "
          f"filled, {rep['spans_empty']} too narrow for the next word\n")
        w(f"  flowed  : {rep['words_placed']}/{rep['words_total']} words, "
          f"{rep['chars_placed']} of {rep['chars_total']} characters "
          f"({rep['chars_placed'] / max(rep['chars_total'], 1):.1%}); "
          f"{'hyphenated' if rep['hyphenated'] else 'NOT hyphenated'}\n")
        w(f"            (the difference is the inter-word spaces the flow "
          f"consumed at span ends -- no text was dropped)\n")
    elif "rows" in rep:
        w(f"  rows    : {rep['rows']} x {rep['repeats_per_row']} repeat(s), "
          f"pitch {rep['row_pitch_mm']:.3f} mm, gap {rep['row_gap_mm']:.3f} mm\n")
    if rep["warnings"]:
        w("\n")
        for x in rep["warnings"]:
            w(f"  !! {x}\n")
    w("\n")


# --- CLI plumbing shared with emit_art.py -----------------------------------

_TEXT_FLAG: dict[str, str] = {}


def add_cli_args(ap, prefix="", text_flag=None, group_title=None):
    """Add the microtext flags to a parser.

    emit_art.py calls this with prefix='microtext-' so the two tools cannot
    drift apart in what a flag means or what its default is.
    """
    d = prefix.replace("-", "_")
    _TEXT_FLAG[prefix] = text_flag or f"--{prefix}text"
    g = ap.add_argument_group(group_title or "microtext")
    g.add_argument(text_flag or f"--{prefix}text", dest=f"{d}text", default=None,
                   metavar="STRING",
                   help="the string to microprint. Refused if it contains "
                        "KiCad markup that would change what is fabricated")
    g.add_argument(f"--{prefix}height", dest=f"{d}height", type=float,
                   default=None, metavar="MM",
                   help="cap height in mm (KiCad's font size IS the cap height "
                        "for the stroke font -- measured, see stroke_font.py)")
    g.add_argument(f"--{prefix}tone", dest=f"{d}tone", default="T2",
                   metavar="TONE",
                   help="palette tone (default T2: copper letterforms in one "
                        "block mask opening). T6 = copper under mask, covert")
    g.add_argument(f"--{prefix}at", dest=f"{d}at", default="0,0", metavar="X,Y",
                   help="anchor for a single run, mm (default 0,0)")
    g.add_argument(f"--{prefix}angle", dest=f"{d}angle", type=float, default=0.0,
                   metavar="DEG", help="rotation of a single run")
    g.add_argument(f"--{prefix}path", dest=f"{d}path", default=None,
                   metavar='"X,Y X,Y ..."',
                   help="run the string along this polyline, one fp_text per "
                        "straight stretch")
    g.add_argument(f"--{prefix}region", dest=f"{d}region", default=None,
                   metavar="X0,Y0,X1,Y1",
                   help="fill this rectangle with repeated rows of the string")
    g.add_argument(f"--{prefix}shape", dest=f"{d}shape", default=None,
                   metavar="FILE",
                   help="flow the text into this shape (SVG or raster). Unlike "
                        "--region, the string is treated as a continuous body "
                        "of prose: it is broken at word boundaries to fit the "
                        "mask spans on each row and carried on to the next")
    g.add_argument(f"--{prefix}shape-element", dest=f"{d}shape_element",
                   type=int, default=None, metavar="N",
                   help="rasterise only the Nth drawable child of the SVG "
                        "root (0-based), painted solid. Needed when the file "
                        "stacks a shape on a background")
    g.add_argument(f"--{prefix}shape-width", dest=f"{d}shape_width", type=float,
                   default=None, metavar="MM",
                   help="width of the shape's ink bounding box in mm")
    g.add_argument(f"--{prefix}shape-height", dest=f"{d}shape_height",
                   type=float, default=None, metavar="MM",
                   help="height of the shape's ink bounding box in mm "
                        "(give width or height, not both)")
    g.add_argument(f"--{prefix}shape-raster-px", dest=f"{d}shape_raster",
                   type=int, default=DEFAULT_SHAPE_RASTER_PX, metavar="PX",
                   help=f"raster width for the shape mask "
                        f"(default {DEFAULT_SHAPE_RASTER_PX})")
    g.add_argument(f"--{prefix}shape-hyphenate", dest=f"{d}hyphenate",
                   action="store_true",
                   help="break words with a hyphen to fill a span that no "
                        "whole word fits. Off by default: an unhyphenated "
                        "flow leaves narrow spans blank but never invents a "
                        "break the author did not write")
    g.add_argument(f"--{prefix}shape-hyphen-min", dest=f"{d}hyphen_min",
                   type=int, default=3, metavar="N",
                   help="letters that must remain on each side of a hyphen "
                        "break (default 3)")
    g.add_argument(f"--{prefix}shape-center-band", dest=f"{d}center_band",
                   action="store_true",
                   help="test only the centre line of each row band against "
                        "the mask instead of the whole band. Fills more of the "
                        "silhouette and lets ascenders and descenders hang "
                        "over its edge")
    g.add_argument(f"--{prefix}separator", dest=f"{d}separator", default="   ",
                   help="between repeats in a filled region (default 3 spaces)")
    g.add_argument(f"--{prefix}row-gap", dest=f"{d}row_gap", type=float,
                   default=None, metavar="MM",
                   help="clear space between the ink of adjacent rows "
                        "(default: the layer floor, or 0.25 x cap, whichever "
                        "is larger)")
    g.add_argument(f"--{prefix}stroke-ratio", dest=f"{d}stroke_ratio", type=float,
                   default=TEXT_STROKE_RATIO, metavar="R",
                   help=f"stroke as a fraction of cap height (default "
                        f"{TEXT_STROKE_RATIO} = 1:6.7; the palette's legible "
                        f"band is 1:6 to 1:8)")
    g.add_argument(f"--{prefix}tracking", dest=f"{d}tracking", type=float,
                   default=0.0, metavar="EM",
                   help="letter-spacing in em, added BETWEEN glyphs. The "
                        "inter-glyph gap is the tightest gap in ordinary prose "
                        "(4/21 em, tighter than the 'i' stem-to-tittle 5/21 and "
                        "the 'e' counter at 0.295), and this is the only thing "
                        "that widens it. Past the point where a glyph's own "
                        "pieces take over -- 1/21 em for English prose -- it "
                        "buys nothing. Costs one fp_text PER GLYPH, because "
                        "KiCad text has no letter-spacing attribute. Default 0")
    g.add_argument(f"--{prefix}mask-bleed", dest=f"{d}mask_bleed", type=float,
                   default=DEFAULT_MASK_BLEED_MM, metavar="MM",
                   help=f"how far the block opening grows past the letterforms "
                        f"(default {DEFAULT_MASK_BLEED_MM} = 3x mask "
                        f"registration)")
    g.add_argument(f"--{prefix}floor", dest=f"{d}floor", type=float, default=None,
                   metavar="MM",
                   help="override the palette's minimum feature with your "
                        "vendor's real number, e.g. 0.127 for a standard fab")
    g.add_argument(f"--{prefix}fab", dest=f"{d}fab", default=None,
                   choices=sorted(fab_profiles.PROFILES), metavar="PROFILE",
                   help="size and check against a named process from "
                        "tools/fab_profiles.py instead of the palette doc's "
                        "generic floor: " +
                        ", ".join(sorted(fab_profiles.PROFILES)) +
                        ". Unlike --" + prefix + "floor this carries a source "
                        "and a name, and the name is written into the "
                        "footprint so tools/verify_art.py checks the part "
                        "against the process it was sized for")
    g.add_argument(f"--{prefix}run-tol-deg", dest=f"{d}run_tol", type=float,
                   default=DEFAULT_RUN_TOL_DEG, metavar="DEG",
                   help="glyphs whose path tangents differ by less than this "
                        "share one fp_text")
    g.add_argument(f"--{prefix}allow-buried", dest=f"{d}allow_buried",
                   action="store_true",
                   help="permit microtext on a buried copper layer, which the "
                        "palette says will not read and gives no floor for")
    g.add_argument(f"--{prefix}allow-unmeasured", dest=f"{d}allow_unmeasured",
                   action="store_true",
                   help="place characters with no measured metrics, excluded "
                        "from the counter check and flagged")
    return g


def _pairs(s, what):
    out = []
    for tok in s.replace(",", " ").split():
        out.append(float(tok))
    if len(out) % 2:
        raise MicrotextRefused(f"{what} needs an even number of coordinates, "
                               f"got {len(out)}: {s!r}")
    return [(out[i], out[i + 1]) for i in range(0, len(out), 2)]


def spec_from_args(args, prefix="") -> MicrotextSpec | None:
    d = prefix.replace("-", "_")
    text = getattr(args, f"{d}text")
    if text is None:
        return None
    tflag = _TEXT_FLAG.get(prefix, f"--{prefix}text")
    h = getattr(args, f"{d}height")
    if h is None:
        raise MicrotextRefused(
            f"{tflag} was given without --{prefix}height. There is no safe "
            f"default cap height: the whole question is whether the one you "
            f"want clears the floor.")
    region = getattr(args, f"{d}region")
    path = getattr(args, f"{d}path")
    shape_file = getattr(args, f"{d}shape", None)
    chosen = [n for n, v in (("region", region), ("path", path),
                             ("shape", shape_file)) if v]
    if len(chosen) > 1:
        raise MicrotextRefused(
            f"{' and '.join('--' + prefix + c for c in chosen)} are different "
            f"placements; pick one")
    shape = None
    if shape_file:
        at = _pairs(getattr(args, f"{d}at"), f"--{prefix}at")
        shape = load_shape(
            shape_file,
            element=getattr(args, f"{d}shape_element"),
            width_mm=getattr(args, f"{d}shape_width"),
            height_mm=getattr(args, f"{d}shape_height"),
            origin=at[0] if at else (0.0, 0.0),
            raster_px=getattr(args, f"{d}shape_raster"))
    reg = None
    if region:
        pts = _pairs(region, f"--{prefix}region")
        if len(pts) != 2:
            raise MicrotextRefused(f"--{prefix}region needs X0,Y0,X1,Y1")
        reg = (pts[0][0], pts[0][1], pts[1][0], pts[1][1])
    pl = None
    if path:
        pl = _pairs(path, f"--{prefix}path")
        if len(pl) < 2:
            raise MicrotextRefused(f"--{prefix}path needs at least two points")
    at = _pairs(getattr(args, f"{d}at"), f"--{prefix}at")
    return MicrotextSpec(
        text=text, cap_mm=h, tone=getattr(args, f"{d}tone"),
        at=at[0] if at else (0.0, 0.0),
        angle_deg=getattr(args, f"{d}angle"),
        path=pl, region=reg, shape=shape,
        hyphenate=getattr(args, f"{d}hyphenate", False),
        hyphen_min=getattr(args, f"{d}hyphen_min", 3),
        shape_whole_band=not getattr(args, f"{d}center_band", False),
        separator=getattr(args, f"{d}separator"),
        row_gap_mm=getattr(args, f"{d}row_gap"),
        stroke_ratio=getattr(args, f"{d}stroke_ratio"),
        tracking_em=getattr(args, f"{d}tracking", 0.0),
        mask_bleed_mm=getattr(args, f"{d}mask_bleed"),
        floor_mm=getattr(args, f"{d}floor"),
        fab=getattr(args, f"{d}fab", None),
        allow_buried=getattr(args, f"{d}allow_buried"),
        allow_unmeasured=getattr(args, f"{d}allow_unmeasured"),
        run_tol_deg=getattr(args, f"{d}run_tol"),
        flag_prefix=prefix, text_flag=tflag,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Place microprinted text in a KiCad footprint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The palette's authority on all of this is docs/pcb-palette.md; "
               "the letterform metrics are measured by tools/stroke_font.py.")
    ap.add_argument("--name", default="microtext", help="footprint name")
    ap.add_argument("-o", "--output", default=None, help="output .kicad_mod")
    ap.add_argument("--report-json", default=None)
    ap.add_argument("--specimen", action="store_true",
                    help="use coupon_ladders.SPECIMEN, chosen because its "
                         "closed counters fail first")
    ap.add_argument("--text-file", default=None, metavar="FILE",
                    help="read the body from FILE instead of --text. Newlines "
                         "collapse to single spaces, because fp_text is one "
                         "line and shape flow re-breaks the text anyway")
    ap.add_argument("--descr", default=None,
                    help="footprint descr (default: derived from the text)")
    add_cli_args(ap, prefix="", text_flag="--text")
    a = ap.parse_args(argv)

    if a.text_file:
        if a.text:
            ap.error("--text and --text-file both given; pick one")
        a.text = " ".join(
            pathlib.Path(a.text_file).read_text(encoding="utf-8").split())
    if a.specimen and not a.text:
        from coupon_ladders import SPECIMEN
        a.text = SPECIMEN
    if not a.text:
        ap.error("--text, --text-file or --specimen is required")

    from emit_art import ArtFp
    try:
        spec = spec_from_args(a)
        short = (repr(spec.text) if len(spec.text) <= 40
                 else f"{len(spec.text)} chars starting {spec.text[:32]!r}")
        fp = ArtFp(a.name, descr=a.descr or f"microtext {short} at "
                                 f"{spec.cap_mm:g} mm cap - tools/microtext.py",
                   tags="recklessart microtext")
        rep = emit(fp, spec)
    except MicrotextRefused as e:
        sys.stderr.write(f"\n!! REFUSED: {e}\n\n")
        return 2
    print_report(rep)

    if a.output:
        out = pathlib.Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(fp.dumps(), encoding="utf-8")
        rep["output"] = str(out)
        rep["bytes"] = out.stat().st_size
        print(f"  output  : {out}  {rep['bytes']:,} B "
              f"({rep['bytes']/max(rep['glyphs'],1):.0f} B/glyph)\n")
    if a.report_json:
        pathlib.Path(a.report_json).write_text(json.dumps(rep, indent=2),
                                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
