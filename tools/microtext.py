#!/usr/bin/env python3
"""W1b: microprinting as a real output mode.

docs/pcb-palette.md assesses microprinting and coupon_ladders.text_ladder()
sweeps cap heights on a calibration coupon, but neither lets you PLACE microtext
in a design. This does: a string, a cap height, a palette tone, and either a path
to run along or a region to fill.

The eight things this module exists to get right
------------------------------------------------

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

4. THE MASK NEVER OPENS PER GLYPH. Mask registration is +/-0.05 mm against a
   ~0.10 mm stroke. A per-glyph opening cannot survive that; an opening whose
   edge stays a full bleed clear of every letterform only has to place its
   own edge. So for any tone whose recipe contains a mask layer, the
   letterforms go on the COPPER layer and the mask layer gets one filled
   region: a rectangle over a line, path or region run, and for shape flow
   the ART SILHOUETTE itself -- the union of the row spans the flow ran
   against, grown by the bleed, with the counters kept masked (issue #15).
   Two runs whose openings would leave a sub-floor mask dam between them are
   merged into one opening rather than left to wash away, and a silhouette
   whose lobes close to under the dam is refused for the same reason.

5. WHETHER THE TEXT FILLS THE SHAPE IS A VERDICT, NOT A STATISTIC. Shape flow
   used to print "M/N mask spans filled" and stop, which reads identically
   whether the body fitted the silhouette or ran out with eleven bands still
   blank. Both directions now end in a named conclusion with the arithmetic to
   act on it:

     UNDERFILL  the text ran out before the shape did and whole row bands are
                blank. WARNS: nothing was lost -- every character supplied is
                on the board, in order -- and the gap is visible to the naked
                eye, which is the opposite of the sub-floor stroke this module
                refuses over. Says how many characters short, MEASURED by
                re-running the flow with the body extended, and offers the
                larger cap height that would fill the shape with the text on
                hand, verified by running the flow there.
                --shape-require-fill makes it fatal for an unattended build.

     OVERFILL   the shape ran out before the text did, so text is TRUNCATED.
                REFUSES: a reader cannot see a word that is not on the board,
                so unlike underfill there is no blank to notice, and at these
                cap heights nobody proof-reads the result. Says how many
                characters did not fit and offers the smaller (finer) cap that
                would hold them -- or, when the floor bounds how fine the
                process can go, says outright that the text cannot be made to
                fit at this process and by how much it misses.
                --shape-allow-truncation makes truncation a deliberate choice
                and records the dropped characters in the report.

   Announced truncation is a choice; silent truncation is a defect.

6. THE VERDICT COMES BEFORE THE FLOW, NOT AFTER IT. The process floor fixes the
   smallest cap height that can be built; the cap height and the art size fix
   how many characters the art holds; that and the text length fix the verdict.
   None of it needs a glyph placed first, so none of it waits for one. check()
   measures the CHARACTER CAPACITY of the shape and reports the verdict at the
   top of the report, and a body that will not fit is refused there rather than
   after the work.

   Capacity is EXACT for the prose it is measured with, not an estimate: the
   flow is causal, so running it over the body repeated until the art overflows
   gives the longest prefix of that prose the art takes, character for
   character. It is NOT a property of the shape alone -- two bodies of the same
   length pack differently -- so it is always measured with the prose in hand.

   solve() exposes the same arithmetic without emitting anything. Three
   quantities -- art size S, cap height h, text length L -- and fixing any two
   determines the third:

       art + cap        -> the characters it holds, and the shortest text that
                           still fills it
       cap + characters -> how big the art has to be
       art + characters -> the largest cap the text survives

   Every answer comes back with the flow that was run at it. `--solve` on the
   command line; the unknown is whichever of --shape-height / --height /
   --text you leave out.

7. A BREAK AT THE AUTHOR'S OWN HYPHEN ALTERS NOTHING, AND IS ALWAYS TAKEN. A
   word that already contains a hyphen is split there -- "peer-to-peer" is
   "peer-" + "to-" + "peer" -- independent of --shape-hyphenate and independent
   of --shape-hyphen-min, because nothing is inserted, nothing is removed, and
   no word is divided that the author had not already divided. Joining the
   pieces returns the word character for character.

   INSERTING a hyphen is the other thing entirely, it stays behind
   --shape-hyphenate, and it is the only operation here that puts a character
   on the board the author did not write. Every one is recorded by word,
   warned about, and counted; and place() walks the strings that will be
   fabricated back against the source, allowing an inter-word space the flow
   consumed and an inserted hyphen that was DECLARED, and nothing else. An
   undeclared hyphen, a dropped word or a scrambled order fails that walk and
   refuses the part.

8. THE TEXT TRAVELS IN THE PART (issue #20). A placed body used to exist only
   as geometry -- 1,638 of the whitepaper part's 1,644 characters were
   recoverable from nothing but glyph coordinates. Every emit now stores
   three footprint properties, in the serialisation KiCad 10's own writer
   uses: Microtext (the author's text, verbatim, selectable in the editor),
   MicrotextPlaced (the text as the board carries it, one line per run --
   the only form that matches the geometry once a hyphen was inserted), and
   MicrotextRecipe (JSON: text file, shape and element, cap, tracking,
   stroke ratio, fab, hyphenation -- enough to regenerate). And the
   integrity walk of point 7 is exposed from the artefact side: --recover
   reads the glyphs back off any .kicad_mod in reading order, prints the
   text, and proves it against the stored source when there is one.

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

    # how many characters does a 2.5 in Bitcoin mark hold at the fab floor?
    python tools/microtext.py --solve --shape examples/bitcoin_b.svg \
        --shape-element 2 --shape-height 63.5 --height 0.79 \
        --text-file examples/bitcoin_whitepaper_s1.txt \
        --stroke-ratio 0.125 --tracking 0.047619 --fab jlcpcb-4l-fine

    # ... and how big would it have to be to hold all of that text?
    # (same command with --shape-height left off)

    # read the text back off an emitted part, and prove it
    python tools/microtext.py --recover out.kicad_mod
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
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
            notes.append(f"{tone}: letterforms on {'/'.join(cu)}, one mask "
                         f"opening on {'/'.join(mask)} over the whole block "
                         f"(shape flow: over the art silhouette) -- gold on "
                         f"bare laminate")
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

    def scaled(self, k):
        """The same silhouette at k times the size, about the same origin.

        The grid is untouched -- only the millimetres a pixel stands for change
        -- so this is EXACTLY the shape the caller loaded, not a redrawn
        approximation, and the raster quantisation scales with it. That is what
        makes an art-size remedy checkable: the flow can be re-run at the size
        this module recommends, on the same silhouette, and the number handed
        back is one that was measured there.
        """
        if k <= 0:
            raise MicrotextRefused(f"art scale {k} is not positive")
        return ShapeMask(grid=self.grid, mm_per_px=self.mm_per_px * float(k),
                         origin=self.origin, source=self.source,
                         raster_tool=self.raster_tool)

    def size_mm(self, axis):
        return self.height_mm if axis == "height" else self.width_mm


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


# --- the silhouette opening (issue #15) -------------------------------------
#
# The shape-mode mask opening follows the ART SILHOUETTE: the union of the row
# band spans the flow ran against, each grown by the mask bleed. The helpers
# here compute that union EXACTLY -- every vertex of the opening is a
# coordinate the arithmetic produced, not a pixel a raster put near it -- and
# then measure the one thing a polygon opening can get wrong that a rectangle
# cannot: a strip of mask left narrower than the process dam.

def _rect_union(rects):
    """Exact union of axis-aligned rectangles. -> (loops, covered).

    `loops` are the closed boundary loops in mm, collinear runs collapsed,
    wound to emit_art's convention: signed_area < 0 is an outer boundary,
    > 0 is a hole (a counter that stays masked). `covered((x, y))` answers
    point-in-union, which is how the corridor check below tells a strip of
    MASK between two opening edges from the inside of the opening itself.

    Coordinate compression + boundary tracing rather than a raster union, on
    purpose: the spans are already quantised once by the shape mask's own
    raster, and a second quantisation here would put the opening edge up to a
    pixel away from where the bleed arithmetic promised it.
    """
    import numpy as np
    xs = sorted({v for r in rects for v in (r[0], r[2])})
    ys = sorted({v for r in rects for v in (r[1], r[3])})
    xi = {v: i for i, v in enumerate(xs)}
    yi = {v: i for i, v in enumerate(ys)}
    # cell (cj, ci) spans ys[cj-1]..ys[cj] x xs[ci-1]..xs[ci]; cj=0 / ci=0 and
    # the top row/column past the last coordinate are the empty outside ring.
    cov = np.zeros((len(ys) + 1, len(xs) + 1), dtype=bool)
    for x0, y0, x1, y1 in rects:
        if x1 <= x0 or y1 <= y0:
            continue
        cov[yi[y0] + 1: yi[y1] + 1, xi[x0] + 1: xi[x1] + 1] = True

    # Directed boundary edges, covered region kept on the (dy, -dx) side --
    # the winding that makes a plain rectangle come out with negative signed
    # area, matching emit_art's outer/hole convention.
    out_e: dict = {}

    def add(v, d):
        out_e.setdefault(v, []).append(d)

    for i in range(len(xs)):
        for j in range(len(ys) - 1):
            left, right = cov[j + 1, i], cov[j + 1, i + 1]
            if right and not left:
                add((i, j), (0, 1))
            elif left and not right:
                add((i, j + 1), (0, -1))
    for j in range(len(ys)):
        for i in range(len(xs) - 1):
            above, below = cov[j, i + 1], cov[j + 1, i + 1]
            if above and not below:
                add((i, j), (1, 0))
            elif below and not above:
                add((i + 1, j), (-1, 0))

    loops = []
    seen = set()
    for start, dirs in list(out_e.items()):
        for d0 in list(dirs):
            if (start, d0) in seen:
                continue
            v, d = start, d0
            pts = []
            while True:
                seen.add((v, d))
                pts.append(v)
                v = (v[0] + d[0], v[1] + d[1])
                cand = out_e.get(v, ())
                # Turn toward the covered side first. At an ordinary vertex
                # exactly one continuation exists and the priority is inert;
                # at a corner-touching crossing it keeps each covered lobe on
                # its own simple loop. The successor rule is a bijection on
                # directed edges, so the walk always returns to its start
                # edge -- that, not the start vertex, is what closes a loop.
                n = (d[1], -d[0])
                for nd in (n, d, (-n[0], -n[1])):
                    if nd in cand:
                        d = nd
                        break
                else:
                    raise AssertionError(
                        "open boundary while tracing a rectangle union -- "
                        "this is a bug in _rect_union, not in the shape")
                if v == start and d == d0:
                    break
            out = []
            m = len(pts)
            for k in range(m):
                p0, p1, p2 = pts[k - 1], pts[k], pts[(k + 1) % m]
                if (p1[0] - p0[0], p1[1] - p0[1]) != (p2[0] - p1[0],
                                                      p2[1] - p1[1]):
                    out.append((xs[p1[0]], ys[p1[1]]))
            if len(out) >= 3:
                loops.append(out)

    import bisect

    def covered(p):
        ci = bisect.bisect_left(xs, p[0])
        cj = bisect.bisect_left(ys, p[1])
        if ci <= 0 or cj <= 0 or ci >= len(xs) + 1 or cj >= len(ys) + 1:
            return False
        return bool(cov[cj, ci])

    return loops, covered


def _seg_closest(p, q, r, s):
    """Closest points between non-crossing segments pq, rs. -> (d, on_pq, on_rs).

    Ties are AVERAGED: two parallel overlapping edges achieve their distance
    everywhere along the overlap, and the endpoint pair a naive argmin returns
    sits exactly on whatever third edge joins them -- which is the one point
    where "is the midpoint mask or opening" cannot be answered. The average
    lands mid-overlap, where it can.
    """
    def pt_seg(pt, a, b):
        vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 <= 0 else max(0.0, min(1.0, ((pt[0] - a[0]) * vx +
                                                   (pt[1] - a[1]) * vy) / L2))
        cp = (a[0] + t * vx, a[1] + t * vy)
        return math.hypot(pt[0] - cp[0], pt[1] - cp[1]), cp
    cands = []
    for pt, (a, b), flip in ((p, (r, s), False), (q, (r, s), False),
                             (r, (p, q), True), (s, (p, q), True)):
        d, cp = pt_seg(pt, a, b)
        cands.append((d, cp, pt) if flip else (d, pt, cp))
    dmin = min(c[0] for c in cands)
    tied = [c for c in cands if c[0] <= dmin + 1e-12]
    pa = (sum(c[1][0] for c in tied) / len(tied),
          sum(c[1][1] for c in tied) / len(tied))
    pb = (sum(c[2][0] for c in tied) / len(tied),
          sum(c[2][1] for c in tied) / len(tied))
    return dmin, pa, pb


def _mask_corridors(loops, covered, radius):
    """The narrowest strip of MASK between two opening edges. -> (mm, (x, y)).

    (None, None) when no two edges face each other across mask within
    `radius`. Two edges of the OPENING closer than the process dam, with mask
    between them, is a web the fab cannot hold: it washes away and the two
    lobes merge with an edge nobody drew. A rectangle opening could never do
    this; a silhouette opening can, anywhere the silhouette pinches, so it is
    measured here on the exact loops that will be emitted.

    Two tests keep this honest, and each catches what the other cannot:

      FACING. Every loop edge knows which side of it is mask (the loops are
      wound with the opening on a fixed side). A pair of edges is a dam
      candidate only if each one's mask side points at the other -- which is
      what "two lobes closing" means. Without this, every staircase step the
      band quantisation puts on the boundary reports its own corner pocket
      as a corridor, because the pocket is mask and it is narrow; but that
      pocket opens into the wide outside mask and no web is formed there.

      COVERED. The midpoint of the closest approach must itself be mask.
      Without this, two facing edges with a sliver of OPENING between them
      -- the opening's own geometry, no mask involved -- would be reported.
    """
    edges = []
    for li, lp in enumerate(loops):
        n = len(lp)
        for k in range(n):
            a, b = lp[k], lp[(k + 1) % n]
            ex, ey = b[0] - a[0], b[1] - a[1]
            el = math.hypot(ex, ey)
            if el <= 1e-12:
                continue
            mask_n = (ey / el, -ex / el)    # -(covered-side normal): the mask side
            mask_n = (-mask_n[0], -mask_n[1])
            edges.append((min(a[0], b[0]), li, k, n, a, b, mask_n,
                          min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
    edges.sort(key=lambda e: e[0])
    best, where = None, None
    for u in range(len(edges)):
        xu0, lu, ku, nu, a1, b1, m1, yu0, xu1, yu1 = edges[u]
        for w in range(u + 1, len(edges)):
            xw0, lw, kw, nw, a2, b2, m2, yw0, xw1, yw1 = edges[w]
            lim = best if best is not None else radius
            if xw0 - xu1 >= lim:
                break                       # sorted by min-x: nothing closer follows
            if lu == lw:
                dk = abs(ku - kw)
                if dk == 1 or dk == nu - 1:
                    continue                # adjacent edges share a vertex
            if yw0 - yu1 >= lim or yu0 - yw1 >= lim:
                continue
            d, pa, pb = _seg_closest(a1, b1, a2, b2)
            if d <= 1e-9 or d >= lim:
                continue
            v = (pb[0] - pa[0], pb[1] - pa[1])
            if v[0] * m1[0] + v[1] * m1[1] <= 1e-12:
                continue                    # edge 1's mask side looks away
            if v[0] * m2[0] + v[1] * m2[1] >= -1e-12:
                continue                    # edge 2's mask side looks away
            mid = ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0)
            if covered(mid):
                continue                    # opening between them, not mask
            best, where = d, mid
    return best, where


def _silhouette_openings(loops):
    """Union loops -> fp_poly-ready outlines. -> (outlines, holes, unbridged).

    A hole loop is a COUNTER -- the enclosed hole in a letter B -- and it
    stays masked: it is joined to its outer by emit_art.bridge_holes' zero-
    width fracture slit, the same keyhole form every tone fill in this tree
    uses, rather than being filled over or emitted as a second polygon KiCad
    would union away.
    """
    import numpy as np
    import emit_art
    outers, holes = [], []
    for lp in loops:
        a = np.asarray(lp, dtype=np.float64)
        (outers if emit_art.signed_area(a) < 0 else holes).append(a)
    buckets: list[list] = [[] for _ in outers]
    unbridged = 0
    for hp in holes:
        best, best_a = -1, math.inf
        for i, op in enumerate(outers):
            oa = -emit_art.signed_area(op)
            if oa >= best_a:
                continue
            if emit_art.point_in_poly(hp[0], op):
                best, best_a = i, oa
        if best >= 0:
            buckets[best].append(hp)
        else:
            unbridged += 1
    outs = []
    for op, hs in zip(outers, buckets):
        if hs:
            merged, ub = emit_art.bridge_holes(op, hs)
            unbridged += ub
        else:
            merged = op
        # round to the writer's grid and drop the consecutive duplicates the
        # rounding can mint -- two union vertices under 0.1 um apart are one
        # point in the file, and verify_art counts the pair as a defect
        merged = emit_art._round_dedupe(np.asarray(merged, dtype=np.float64))
        outs.append([(float(x), float(y)) for x, y in merged])
    return outs, len(holes), unbridged


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
    # The two halves of "does the text fit the shape", and their defaults are
    # not symmetric because the two failures are not symmetric.
    #
    # OVERFILL drops characters. A reader cannot see a word that is not there,
    # and at these cap heights nobody is proof-reading the board under a loupe,
    # so it REFUSES by default and this flag is how truncation becomes a
    # deliberate choice rather than an accident.
    #
    # UNDERFILL drops nothing: every character supplied is on the board, in
    # order, and the shortfall is a blank you can see from across the room. So
    # it WARNS by default, and this flag is how a caller who needs the
    # silhouette actually finished -- a library build, a CI gate -- makes it
    # fatal.
    allow_truncation: bool = False
    require_fill: bool = False
    # Measure the shape's character capacity in check(), before anything is
    # placed, and report the verdict there. On by default: knowing whether the
    # text fits BEFORE the flow runs is the whole point, and it costs one
    # oversupplied flow -- tens of milliseconds against the flow that follows.
    # Turned off only by callers that are themselves inside the solve.
    forecast: bool = True
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
    # Where `text` came from, when it came from a file (--text-file). Recorded
    # in the emitted part's provenance property so the part can say which file
    # to regenerate from; None means the text arrived inline and the property
    # says so.
    source_path: str | None = None
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


def resolve_floor(spec, text_layers, cls):
    """The minimum feature this run is sized against. -> (mm, note, prof, notes)

    Lifted out of check() so the sizing solve can ask what the floor is without
    first having to name a cap height that clears it -- which is the whole
    chicken-and-egg the solve exists to break. The logic is unchanged: three
    sources, in order of authority -- a named fab profile, a bare --floor
    number, then the palette doc, whose clause is last and untouched.
    """
    doc_floor = floor_for(text_layers[0])[0]
    if doc_floor is None:                       # buried: the doc gives no number
        doc_floor = 0.50
        floor_note = ("PROVISIONAL 0.50 mm -- docs/pcb-palette.md gives no "
                      "buried floor; this matches tools/verify_art.py's "
                      "provisional value and cal_buried exists to measure it")
    else:
        floor_note = f"docs/pcb-palette.md via {pathlib.Path(FLOOR_SOURCE).name}"

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
    return floor, floor_note, prof, fab_notes


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

    floor, floor_note, prof, fab_notes = resolve_floor(spec, text_layers, cls)

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
        "flag_prefix": spec.flag_prefix,
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

    # ---- THE VERDICT, UP FRONT ---------------------------------------------
    #
    # Everything above is about whether the letterforms can be BUILT. This is
    # about whether the text and the art are the same size, and it belongs
    # here, in the function whose whole job is "everything that can be decided
    # before any geometry is placed", because it CAN be decided here. The
    # process floor fixes the smallest cap; the cap and the art size fix the
    # capacity; the capacity and the text length fix the verdict. Nothing about
    # that needs a glyph placed first, and the caller who is about to be
    # refused should be told before the work rather than after it.
    if spec.mode == "shape" and spec.forecast:
        rep["capacity"] = forecast(spec, cap, floor)
        fc = rep["capacity"] or {}
        if ((fc.get("verdict") == "overfill" and not spec.allow_truncation)
                or (fc.get("verdict") == "underfill" and spec.require_fill)):
            # It is going to refuse. Build the verdict here so the refusal
            # arrives before the flow rather than after it -- and if the
            # forecast were somehow wrong, roll the report back and let the
            # normal path speak, rather than leaving a warning behind twice.
            marker = len(rep["warnings"])
            _fill_verdict(spec, rep, _flow(spec, cap, floor), cap)
            del rep["warnings"][marker:]
            rep.pop("fill", None)

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


# --- shape flow -------------------------------------------------------------
#
# A ROW BAND CAN BE EMPTY FOR TWO DIFFERENT REASONS AND THEY WANT DIFFERENT
# FIXES. Either the band was too NARROW for the next word -- a letterform's
# extremities always are, and that is reported on its own -- or the WORDS RAN
# OUT before the flow got there. The second one is underfill: the reader sees a
# bite taken out of the silhouette, and no amount of hyphenation or rerunning
# fixes it, because there is nothing left to place.
#
# This module used to print both as one neutral statistic ("M/N mask spans
# filled") and draw no conclusion. It now separates them, because the fix for
# one is not the fix for the other, and it names the fix.
#
# The mirror case is worse. When the shape fills up first the text is
# TRUNCATED, and a reader cannot see the words that are missing -- there is no
# blank to notice. Microprinting is unreadable without a loupe, so a truncation
# nobody announced is a defect nobody would ever catch. That one refuses.

@dataclass
class FlowSpan:
    """One x span of one row band, and what became of it."""
    band: int
    y: float
    x0: float
    x1: float
    state: str              # "filled" | "narrow" | "abandoned"
    text: str = ""
    # abandoned only: was this span wide enough to have held the narrowest
    # piece of the body? A 0.4 mm sliver at the tip of a letterform is not
    # capacity anybody lost, and counting it would make every shape look
    # underfilled.
    usable: bool = True
    # Source characters consumed through the END of this span, separators
    # included -- so a span's `consumed` is the length of the prefix of the
    # body that this span finishes. That is what makes capacity EXACT rather
    # than estimated: the flow is causal, so a body cut to this length places
    # everything up to here and nothing after it.
    consumed: int = 0

    @property
    def width(self):
        return self.x1 - self.x0


@dataclass
class Flow:
    """The result of walking a shape's row bands with a body of prose.

    Produced by _flow(), which is the ONE implementation of the walk. The
    remedy search re-runs it at other cap heights, so every cap height this
    module recommends is one the flow was actually run at rather than one a
    capacity formula predicted -- the flow re-breaks at every span, and a
    closed form in cap would be a guess dressed up as a number.
    """
    spans: list
    runs: list
    bands: int
    ink_h: float
    pitch: float
    words_total: int
    words_placed: int
    unplaced: str
    # Every hyphen this tool ADDED, with the word it divided. Breaking at a
    # hyphen the author already wrote alters nothing and is not in here;
    # inserting one alters the text, and every single one is.
    inserted: list = field(default_factory=list)
    # Breaks taken at a hyphen the author already wrote. Recorded because it
    # is worth knowing how much of the fill came from ordinary typesetting --
    # NOT because it needs disclosing. It changes no character.
    soft_breaks: int = 0
    pieces_total: int = 0
    consumed_chars: int = 0

    def _st(self, s):
        return [x for x in self.spans if x.state == s]

    @property
    def filled(self):
        return self._st("filled")

    @property
    def narrow(self):
        return self._st("narrow")

    @property
    def abandoned(self):
        return self._st("abandoned")

    @property
    def abandoned_usable(self):
        return [s for s in self.spans if s.state == "abandoned" and s.usable]

    @property
    def bands_with_text(self):
        return {s.band for s in self.spans if s.state == "filled"}

    @property
    def bands_abandoned(self):
        """Bands that got NOTHING, had room for a word, and were reached after
        the body ran out. This is the underfill count."""
        return sorted({s.band for s in self.abandoned_usable}
                      - self.bands_with_text)

    @property
    def chars_placed(self):
        return sum(len(s.text) for s in self.spans if s.state == "filled")

    @property
    def words_left(self):
        return self.words_total - self.words_placed

    @property
    def source_chars_placed(self):
        """Characters of the AUTHOR'S text on the board.

        chars_placed counts what is drawn, which includes any hyphen this tool
        inserted. Those are not the author's characters and are not counted as
        them here.
        """
        return self.chars_placed - len(self.inserted)


# --- breaking a word ---------------------------------------------------------
#
# A HYPHEN THE AUTHOR ALREADY WROTE IS A BREAK POINT, AND BREAKING THERE ALTERS
# NOTHING.
#
# The flow used to split the body on whitespace only, so "peer-to-peer" was one
# atomic 12-character unit -- the widest thing in the whitepaper's opening
# sentence -- and the word with the MOST built-in break points was the hardest
# word in the text to place. When it fitted no span it jammed every span after
# it, because the flow never skips a word: prose order is the whole point of
# shape flow. Measured, that is not a rounding error. On a 40 mm B at a 2.0 mm
# cap the Abstract contributed NINE glyphs before deadlocking on
# "peer-to-peer" at band 2 of 13.
#
# The escape hatch was wrong three ways. --shape-hyphenate searched for an
# algorithmic break position k and emitted w[:k] + "-", which for
# "peer-to-peer" at hyphen_min 3 runs k = 9..3 and produces:
#
#   k=8  ->  "peer-to-"  +  "-"      =  "peer-to--"      a doubled hyphen
#   k=7  ->  "peer-to-"  tail "-peer"                    a hyphen INSERTED at a
#                                                        break the author had
#                                                        already made
#   k=5  ->  "peer-"     +  "-"      =  "peer--"         doubled again
#
# so the three defects are (a) existing hyphens were not break points at all,
# (b) a doubled hyphen whenever the algorithmic position landed on a real one,
# and (c) the whole path was gated on a flag that was OFF for the part that
# shipped. hyphen_min compounded it: the natural segment "to" is two letters, so
# even a correct implementation of "break at the author's hyphen" would have
# refused that break for being too short -- a rule about how much of a word to
# leave on a line, applied to a break where NOTHING is inserted and no word is
# divided.
#
# So the body is now split at its existing hyphens ALWAYS -- independent of
# --shape-hyphenate, independent of hyphen_min -- into PIECES that each carry
# the hyphen that ends them. "peer-to-peer" is ["peer-", "to-", "peer"], and
# "".join() of the pieces is the word, character for character. Breaking between
# pieces is ordinary typesetting: it puts a line break where the author already
# put a hyphen, and it adds nothing, removes nothing and discloses nothing.
#
# Algorithmic hyphenation is what is left over: it applies only to a piece that
# is still too wide for the span on its own, it stays behind --shape-hyphenate,
# and it is the ONE operation in this module that puts a character on the board
# the author did not write -- which is why every one of them is recorded,
# reported, and provable from the emitted footprint by recover_text().

def _hyphen_segments(word):
    """Split `word` at its existing hyphens. "".join(result) == word, always.

    A segment keeps the hyphen that ends it, so a break between segments needs
    no character added and none removed. Runs of hyphens that would leave a
    segment with no letters in front of them -- a bare "-", the "--" the
    whitepaper uses as a dash -- are folded into a neighbour rather than
    becoming a break point: there would be nothing to leave on the line.
    """
    segs, start = [], 0
    for i, ch in enumerate(word):
        if ch == "-":
            segs.append(word[start:i + 1])
            start = i + 1
    if start < len(word):
        segs.append(word[start:])
    if not segs:
        return [word]
    out: list[str] = []
    for s in segs:
        if out and not s.strip("-"):
            out[-1] += s                 # a bare "-" glues back onto its left
        else:
            out.append(s)
    while len(out) > 1 and not out[0].strip("-"):
        out[0] += out[1]                 # ... unless there is nothing on its left
        del out[1]
    return out


def _algo_split(seg, hyphen_min, avail, inkw):
    """Break `seg` by INSERTING a hyphen -> (head, tail), or None.

    This is the operation that alters the text, so it is the narrow one. It is
    reached only for a piece that does not fit whole, only behind
    --shape-hyphenate, and it never lands next to a hyphen the author wrote --
    which is what produced "peer-to--". hyphen_min applies HERE and only here,
    because here a word really is being divided; a trailing authorial hyphen is
    not one of the letters it is counting.
    """
    n = len(seg)
    hi = n - hyphen_min - (1 if seg.endswith("-") else 0)
    for k in range(hi, hyphen_min - 1, -1):
        if seg[k - 1] == "-" or seg[k] == "-":
            continue
        cand = seg[:k] + "-"
        if inkw(cand) <= avail + 1e-9:
            return cand, seg[k:]
    return None


def _flow(spec, cap, floor, *, gap=None):
    """Walk the shape's row bands and place the body into their spans.

    Every span is recorded, including the ones visited after the body ran out:
    an older loop broke out of the span list at that point, so "spans_total"
    was a count of spans VISITED and the capacity the text failed to reach was
    never in the report at all.

    The unit of placement is a PIECE, not a whitespace word -- see the block
    above. For a body with no hyphen in it the two are the same thing and this
    walk places exactly what it always placed, glyph for glyph.
    """
    shape = spec.shape
    if shape is None:
        raise MicrotextRefused("_flow needs a shape")
    stroke = cap * float(spec.stroke_ratio)
    pen = stroke / 2.0

    _w = {}

    def inkw(s):
        v = _w.get(s)
        if v is None:
            b = measure(spec, s).ink_em
            v = 0.0 if b is None else (b[2] - b[0]) * cap + 2 * pen
            _w[s] = v
        return v

    def ink_left(s):
        b = measure(spec, s).ink_em
        return 0.0 if b is None else b[0] * cap - pen

    # one vertical box for every row, from the whole body
    m = measure(spec, spec.text)
    if m.ink_em is None:
        raise MicrotextRefused("the body has no ink at all")
    ry0 = m.ink_em[1] * cap - pen
    ry1 = m.ink_em[3] * cap + pen
    ink_h = ry1 - ry0
    if gap is None:
        gap = spec.row_gap_mm if spec.row_gap_mm is not None else floor
    pitch = ink_h + gap

    words = spec.text.split()
    if not words:
        raise MicrotextRefused("the body is entirely whitespace")

    pieces: list[str] = []       # what actually gets placed, in reading order
    glue: list[bool] = []        # True: the NEXT piece follows with no space
    owner: list[int] = []        # which whitespace word this piece came from
    for k, wd in enumerate(words):
        segs = _hyphen_segments(wd)
        for si, s in enumerate(segs):
            pieces.append(s)
            glue.append(si < len(segs) - 1)
            owner.append(k)

    # The narrowest PIECE in the body: the test for whether an abandoned span
    # was capacity or a sliver. "Some part of this text would have gone there"
    # is the weakest true claim available, which is the right one to make when
    # the point is to accuse the caller of supplying too little text.
    narrowest = min(inkw(p) for p in set(pieces))

    pi = 0                       # index of the next piece
    used = 0                     # source characters consumed, separators included
    inserted: list = []          # every hyphen this tool ADDED
    soft_breaks = 0              # breaks taken at a hyphen the author wrote
    spans_rec: list = []
    runs: list = []
    band = 0
    y = shape.origin[1]

    while y + ink_h <= shape.origin[1] + shape.height_mm + 1e-9:
        for sx0, sx1 in shape.band_spans(y, y + ink_h,
                                         whole_band=spec.shape_whole_band):
            avail = sx1 - sx0
            if pi >= len(pieces):
                spans_rec.append(FlowSpan(
                    band, y, sx0, sx1, "abandoned",
                    usable=avail >= narrowest - 1e-9, consumed=used))
                continue
            chunk = ""
            sep = ""
            took = 0
            while pi < len(pieces):
                cand = chunk + sep + pieces[pi]
                if inkw(cand) > avail + 1e-9:
                    break
                chunk = cand
                sep = "" if glue[pi] else " "
                used += len(pieces[pi]) + (
                    1 if (not glue[pi] and pi + 1 < len(pieces)) else 0)
                pi += 1
                took += 1
            if took and sep == "":
                # this span ends INSIDE a word, at a hyphen its author wrote
                soft_breaks += 1
            if not chunk and spec.hyphenate:
                hd = _algo_split(pieces[pi], spec.hyphen_min, avail, inkw)
                if hd is not None:
                    head, rest_seg = hd
                    inserted.append({"word": words[owner[pi]], "head": head,
                                     "tail": rest_seg, "band": band})
                    chunk = head
                    used += len(head) - 1      # the hyphen is not source text
                    pieces[pi] = rest_seg
            if not chunk:
                spans_rec.append(FlowSpan(band, y, sx0, sx1, "narrow",
                                          consumed=used))
                continue
            spans_rec.append(FlowSpan(band, y, sx0, sx1, "filled", text=chunk,
                                      consumed=used))
            runs.append(Run(chunk, sx0 - ink_left(chunk), y - ry0, 0.0))
        band += 1
        y += pitch

    parts: list[str] = []
    for k in range(pi, len(pieces)):
        if parts and not glue[k - 1]:
            parts.append(" ")
        parts.append(pieces[k])
    rest = "".join(parts)
    # THE INVARIANT CAPACITY RESTS ON. `used` is a running count of source
    # characters and `rest` is the text left over, and they have to add up to
    # the body -- otherwise a span's `consumed` is not the prefix boundary it
    # is documented to be and every capacity number off this flow is wrong by
    # however much they disagree. Asserted rather than trusted, because the two
    # are computed by completely different routes.
    assert used + len(rest) == sum(len(w) for w in words) + len(words) - 1, (
        f"the flow consumed {used} characters and has {len(rest)} left, which "
        f"is not the {sum(len(w) for w in words) + len(words) - 1}-character "
        f"body it was given")
    # A word is PLACED when its last piece is. One broken across two spans is
    # not counted until its tail lands, so words_placed and `unplaced` can
    # never disagree about the same word.
    placed_words = owner[pi] if pi < len(pieces) else len(words)
    return Flow(spans=spans_rec, runs=runs, bands=band, ink_h=ink_h,
                pitch=pitch, words_total=len(words), words_placed=placed_words,
                unplaced=rest, inserted=inserted, soft_breaks=soft_breaks,
                pieces_total=len(pieces), consumed_chars=used)


def _flow_at(spec, cap, floor):
    """The flow at a trial cap height, or None if it cannot be run there."""
    if cap <= 0:
        return None
    try:
        return _flow(spec, cap, floor)
    except MicrotextRefused:
        return None


# Cap heights are recommended on this grid, the same 0.005 mm the min_cap
# recommendation already rounds to. Finer than that is false precision against
# a +/-0.05 mm registration budget.
CAP_GRID_MM = 0.005


def _bisect_cap(spec, floor, a, b, ok, *, iters=22, grid=CAP_GRID_MM):
    """The cap nearest `a` on the segment a -> b at which ok(flow) holds.

    ok() is assumed monotone along the segment -- false at `a`, true at `b`.
    Returns (cap, flow) or None. The returned cap is QUANTISED to the grid and
    then the flow is RUN AGAIN there, so the number handed to the caller is one
    that was measured at exactly the value printed. A rounded number that was
    never run is the kind of claim this module refuses to make.
    """
    fb = _flow_at(spec, b, floor)
    if fb is None or not ok(fb):
        return None
    fa = _flow_at(spec, a, floor)
    if fa is not None and ok(fa):
        return a, fa
    lo, hi = 0.0, 1.0                     # lo fails, hi holds
    best = (b, fb)
    for _ in range(iters):
        if abs(hi - lo) * abs(b - a) < grid / 4.0:
            break
        mid = (lo + hi) / 2.0
        c = a + mid * (b - a)
        f = _flow_at(spec, c, floor)
        if f is not None and ok(f):
            hi, best = mid, (c, f)
        else:
            lo = mid
    c, f = best
    q = ((math.ceil(c / grid - 1e-9) if b > a else math.floor(c / grid + 1e-9))
         * grid)
    if (q - b) * (1 if b > a else -1) <= 1e-12 and q > 0:
        fq = _flow_at(spec, q, floor)
        if fq is not None and ok(fq):
            return q, fq
    return c, f


def _row_chars(fl):
    """min / max / mean / stdev of characters per row band that carries text.

    Reported unconditionally, because the shipped part measures 4 / 67 / 33.0
    with a stdev of half the mean and nothing in the report said so. A row of 4
    characters against a mean of 33 is the waist of the letterform, and a
    reader deciding whether the artwork reads wants that number.
    """
    per = {}
    for s in fl.spans:
        if s.state == "filled":
            per[s.band] = per.get(s.band, 0) + len(s.text)
    v = sorted(per.values())
    if not v:
        return None
    mean = sum(v) / len(v)
    if len(v) > 1:
        var = sum((x - mean) ** 2 for x in v) / (len(v) - 1)
        sd = math.sqrt(var)
    else:
        sd = 0.0
    return {"n": len(v), "min": v[0], "max": v[-1], "mean": mean,
            "stdev": sd, "cv": (sd / mean if mean else 0.0)}


def _chars_to_fill(spec, cap, floor, *, guess=None, cap_n=None):
    """How many MORE characters would fill every band, MEASURED.

    The obvious estimate is the abandoned span width times the characters per
    mm the run achieved where it did fill. That was tried and it reads 2x high
    on the shipped art_btc_whitepaper_b -- it says 117 characters short where
    58 already clears it -- because the abandoned spans are the narrow stem
    legs at the foot of the mark, and a greedy flow wastes far more of a 7 mm
    span than of a 40 mm one. A density figure cannot know that.

    So the body is extended with its OWN prose repeated and the flow is run
    again, bisecting on the length of the extension. That gets the added text's
    word lengths right, which is the one property that decides how greedy
    wrapping packs a narrow span. It is still an estimate -- the prose the
    caller actually adds will pack differently -- but it is an estimate made by
    running the thing rather than by modelling it.
    """
    body = spec.text
    if not body:
        return None
    from dataclasses import replace as _replace

    def ok(n):
        if n <= 0:
            f = _flow_at(spec, cap, floor)
        else:
            pad = (" " + body) * (n // (len(body) + 1) + 1)
            f = _flow_at(_replace(spec, text=body + pad[:n]), cap, floor)
        return f is not None and not f.bands_abandoned

    # Bounded by the density estimate rather than by a round number, so a huge
    # shape does not turn this into a flow run over a megabyte of filler. If
    # the bound is reached the caller falls back to the density figure and says
    # which one it is quoting.
    if cap_n is None:
        cap_n = 4 * int(guess or len(body)) + 1024
    hi = max(16, 2 * int(guess or 16))
    while hi < cap_n and not ok(hi):
        hi *= 2
    if hi >= cap_n and not ok(hi):
        return None
    lo = 0
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    return hi


# --- the sizing solve --------------------------------------------------------
#
# THE OWNER'S FORMULATION, AND WHY IT IS THE RIGHT ONE.
#
# The process floor fixes the smallest cap height that can be built. So for a
# given shape at a given art size, the CHARACTER CAPACITY is determined in
# advance -- before any text is supplied, and before a single glyph is flowed.
# Three quantities:
#
#     S   art size, the shape's ink box in mm
#     h   cap height in mm, at or above the floor's minimum for this string
#     L   text length in characters
#
# Fix any two and the third is determined. solve() is that, exposed directly so
# it can be asked without emitting anything, and the answer always comes back
# with the flow that proves it.
#
# CAPACITY IS EXACT FOR A GIVEN BODY. It is not an estimate and it is not a
# model. The flow is CAUSAL: it reads the body once, in order, never looks
# ahead, and each span's outcome depends only on the text before it. So running
# it over this body REPEATED until the shape overflows produces exactly the
# placement it would produce for ANY prefix of that repetition -- and the
# consumed prefix is therefore the longest text of this prose that fits,
# character for character. A body one character longer loses exactly one
# character off the end; a body one character shorter leaves exactly one
# character of slack. FlowSpan.consumed is what records the prefix boundary at
# every span, and _flow() asserts the totals agree with the leftover string.
#
# WHAT CAPACITY IS NOT is a property of the shape alone. It is "characters that
# THIS word-length distribution packs into this silhouette", because greedy
# wrapping against a ragged right edge turns on where the word boundaries fall.
# Two bodies of the same length do not have the same capacity. So the number is
# always measured with the prose the caller intends to set, and the report says
# which prose it was measured with.

CAPACITY_MAX_CHARS = 1 << 18

# Art sizes are recommended on this grid. Finer than 0.05 mm is false precision
# against a raster mask whose own pixel is 0.03-0.05 mm at the sizes in use.
ART_GRID_MM = 0.05


def _normalise(text):
    """The body as the flow sees it: runs of whitespace collapsed to one space.

    Every character count in this section is against THIS string, because it is
    the one the flow indexes. Quoting a length that includes a newline the flow
    never saw would make the arithmetic wrong by however much the caller's file
    was wrapped.
    """
    return " ".join(text.split())


def _oversupply(spec, cap, floor, *, max_chars=CAPACITY_MAX_CHARS):
    """Run the flow on this body repeated until the shape overflows.

    -> (trial_text, flow), or None if the flow cannot run at this cap height or
    the shape swallows more than max_chars of it.
    """
    from dataclasses import replace as _replace
    body = _normalise(spec.text)
    if not body:
        raise MicrotextRefused("the body is entirely whitespace")
    mult = 1
    while True:
        trial = " ".join([body] * mult)
        f = _flow_at(_replace(spec, text=trial), cap, floor)
        if f is None:
            return None
        if f.unplaced:
            return trial, f
        mult *= 2
        if (len(body) + 1) * mult > max_chars:
            return None


def capacity(spec, *, cap_mm=None, floor=None, art_mm=None, axis="height"):
    """How much of THIS prose this shape holds, MEASURED. -> dict.

    Everything in the returned dict was produced by running the flow once over
    an oversupplied body; nothing is extrapolated.

      chars          the longest prefix of this prose, ending at a word or at
                     a hyphen the author wrote, that the shape places IN FULL.
                     Exact: a body of this length loses nothing, and every
                     shorter one loses nothing either.
      fill_chars     the shortest prefix that leaves no row band blank, or None
                     when no length of this prose does. The other end of the
                     useful range: between fill_chars and chars the art is full
                     and the text is whole.
      bands          row bands the shape offers at this cap height
      bands_fillable bands that carry text when the shape is oversupplied; the
                     rest are slivers no piece of this body ever fits and no
                     amount of text would fill

    ONE CAVEAT, stated because it is the only place the word EXACT needs one: a
    body cut mid-word can be LONGER than `chars` and still fit, because cutting
    a word makes a narrower word, and a narrower word fits a span the whole one
    did not. That is a property of truncated text, not of this art. Every body
    that ends where its author ended a word obeys the number.
    """
    if spec.shape is None:
        raise MicrotextRefused("capacity() needs a shape")
    sp = spec
    if art_mm is not None:
        sp = _at_art(spec, art_mm, axis)
    cap = float(cap_mm if cap_mm is not None else sp.cap_mm)
    if floor is None:
        layers, _mask, cls, _n = plan_tone(sp.tone, allow_buried=sp.allow_buried)
        floor = resolve_floor(sp, layers, cls)[0]
    got = _oversupply(sp, cap, floor)
    if got is None:
        return None
    trial, f = got
    chars = len(trial[:f.consumed_chars].rstrip())

    # THE FILL LINE, in one pass over the oversupplied flow rather than by
    # bisecting on flows.
    #
    # The flow is causal and the spans are visited in a fixed order, so a body
    # cut to end at filled span p produces EXACTLY this flow up to p and then
    # nothing: every span after p is reached with the words gone, so every one
    # of them is "abandoned" -- including the ones that read as merely "narrow"
    # here only because more text existed to not fit them. A band is therefore
    # blank FOR WANT OF WORDS at p exactly when it has no filled span at or
    # before p and does have a span after p that was wide enough to have held
    # the narrowest piece of the body. Both conditions relax as p grows, so the
    # first p that clears them is the answer, and one scan finds it.
    #
    # It can come back None, and that is a real answer rather than a failure.
    # If a band beyond the last one this prose ever reaches is still wide
    # enough to have held a word, then no length of THIS prose both fills the
    # art and fits inside it: more text is truncated, less leaves the band
    # blank. The remedy is then a different art size or a different cap height,
    # which is exactly what the solve is for.
    thresh = _narrowest_piece(sp, cap)
    big = 1 << 62
    first_fill = {}
    last_usable = {}
    for idx, s in enumerate(f.spans):
        if s.state == "filled" and s.band not in first_fill:
            first_fill[s.band] = idx
        if (s.x1 - s.x0) >= thresh - 1e-9:
            last_usable[s.band] = idx
    fill_chars = None
    for p, s in enumerate(f.spans):
        if s.state != "filled":
            continue
        if any(first_fill.get(b, big) > p and last_usable.get(b, -1) > p
               for b in range(f.bands)):
            continue
        fill_chars = len(trial[:s.consumed].rstrip())
        break
    return {
        "chars": chars,
        "fill_chars": fill_chars,
        "cap_mm": cap,
        "art_mm": [sp.shape.width_mm, sp.shape.height_mm],
        "art_axis": axis,
        "art_size_mm": sp.shape.size_mm(axis),
        "bands": f.bands,
        "bands_fillable": len(f.bands_with_text),
        "spans": len(f.spans),
        "spans_filled": len(f.filled),
        "spans_narrow": len(f.narrow),
        "soft_breaks": f.soft_breaks,
        "inserted_hyphens": len(f.inserted),
        "hyphenate": bool(sp.hyphenate),
        "sample_chars": len(trial),
        "sample_source": "the body itself, repeated",
        "exact": True,
    }


def _narrowest_piece(spec, cap):
    """Ink width of the narrowest placeable piece of this body, mm.

    The same threshold _flow() uses to decide whether an abandoned span was
    capacity or a sliver, computed here so the fill line can be worked out from
    the span inventory without re-running anything.
    """
    stroke = cap * float(spec.stroke_ratio)
    best = None
    seen = set()
    for wd in spec.text.split():
        for p in _hyphen_segments(wd):
            if p in seen:
                continue
            seen.add(p)
            b = measure(spec, p).ink_em
            v = 0.0 if b is None else (b[2] - b[0]) * cap + stroke
            best = v if best is None else min(best, v)
    return 0.0 if best is None else best


def forecast(spec, cap, floor):
    """Capacity against the text on hand -- the verdict, up front. -> dict

    This is the number the owner asked for: "we know the dimensions of the art
    footprint ahead of time, and whether or not a specific art piece exceeds
    the size of our coupon, and exactly how many characters it will take to
    present it in full."

    Two measurements, both by flow, neither modelled. capacity() says what this
    art holds of this prose. Then the body ITSELF is flowed once, and that is
    what the verdict and `excess_chars` come from -- so the count of characters
    that will not fit is the exact count, for this exact body, and not the
    capacity arithmetic's opinion of it. The two agree on every well-formed
    body; where they can differ is a body that ends mid-word, and then the flow
    is right and the arithmetic is the approximation.
    """
    c = capacity(spec, cap_mm=cap, floor=floor)
    if c is None:
        return None
    fl = _flow_at(spec, cap, floor)
    L = len(_normalise(spec.text))
    c["text_chars"] = L
    c["spare_chars"] = c["chars"] - L
    c["excess_chars"] = len(fl.unplaced) if fl is not None else max(0, L - c["chars"])
    c["excess_words"] = fl.words_left if fl is not None else None
    c["placed_chars"] = fl.source_chars_placed if fl is not None else None
    c["bands_blank"] = len(fl.bands_abandoned) if fl is not None else None
    c["flowed"] = fl is not None
    if fl is None:
        c["verdict"] = "unknown"
    elif fl.unplaced:
        c["verdict"] = "overfill"
    elif fl.bands_abandoned:
        c["verdict"] = "underfill"
    else:
        c["verdict"] = "fits"
    return c


def _at_art(spec, art_mm, axis="height"):
    """The same spec with its shape resized to `art_mm` along `axis`."""
    from dataclasses import replace as _replace
    if spec.shape is None:
        raise MicrotextRefused("an art size needs a shape")
    cur = spec.shape.size_mm(axis)
    if cur <= 0:
        raise MicrotextRefused("the shape has no size along " + axis)
    return _replace(spec, shape=spec.shape.scaled(float(art_mm) / cur))


def min_cap_mm(spec, floor):
    """Smallest cap height that clears every check for this string. -> (mm, why)

    The same arithmetic check() refuses with, so the solve can never recommend
    a cap height check() would then reject.
    """
    layers, _mask, cls, _n = plan_tone(spec.tone, allow_buried=spec.allow_buried)
    m = measure(spec, spec.text)
    h_fab, binding = stroke_font.min_cap_for_floor(floor, float(spec.stroke_ratio), m)
    legible = LEGIBLE_MM.get(cls, 0.9)
    h = max(h_fab, legible)
    return ((math.inf if math.isinf(h) else math.ceil(h * 200 - 1e-9) / 200),
            ("legibility" if legible > h_fab else binding))


def _cap_for(spec, floor, target, lo, hi, *, grid=CAP_GRID_MM, iters=40):
    """Largest cap in [lo, hi] whose capacity still reaches `target`.

    Capacity falls as the cap rises -- fewer rows, each wider -- so the
    predicate is monotone the same way _bisect_cap's is. Bisected on the grid
    and then MEASURED at the quantised answer, so the number printed is one the
    flow was run at.
    """
    def cap_at(h):
        c = capacity(spec, cap_mm=h, floor=floor)
        return -1 if c is None else c["chars"]
    if cap_at(lo) < target:
        return None
    if cap_at(hi) >= target:
        return hi, cap_at(hi)
    for _ in range(iters):
        if hi - lo <= grid:
            break
        mid = (lo + hi) / 2.0
        if cap_at(mid) >= target:
            lo = mid
        else:
            hi = mid
    # Canonicalise on the grid. A bisection lands wherever its bracket started,
    # so without this the same question asked from two different seeds comes
    # back one grid step apart -- and a tool that prints two answers to one
    # question in the same session is worse than a tool that prints none.
    q = math.floor(lo / grid + 1e-9) * grid
    while q > grid and cap_at(q) < target:
        q -= grid
    for _ in range(8):
        if cap_at(q + grid) < target:
            break
        q += grid
    n = cap_at(q)
    if q > 0 and n >= target:
        return q, n
    return lo, cap_at(lo)


def _art_for(spec, floor, cap, target, axis, *, grid=ART_GRID_MM, iters=40):
    """Smallest art size whose capacity reaches `target`, at this cap height.

    Seeded analytically -- capacity goes as (S/h)^2 to first order, so one
    measured point gives a starting size -- then bracketed and bisected with
    measured flows, then MEASURED at the quantised answer. The seed only
    decides how many flows this costs; it never decides the answer.
    """
    def cap_at(s):
        c = capacity(spec, cap_mm=cap, floor=floor, art_mm=s, axis=axis)
        return -1 if c is None else c["chars"]

    s0 = spec.shape.size_mm(axis)
    c0 = cap_at(s0)
    if c0 <= 0:
        lo, hi = s0, s0 * 2.0
    else:
        seed = s0 * math.sqrt(max(target, 1) / c0)
        lo, hi = seed * 0.8, seed * 1.25
    grow = 0
    while cap_at(hi) < target:
        lo, hi = hi, hi * 1.5
        grow += 1
        if grow > 24:
            return None
    while lo > grid and cap_at(lo) >= target:
        hi, lo = lo, lo / 1.5
    for _ in range(iters):
        if hi - lo <= grid:
            break
        mid = (lo + hi) / 2.0
        if cap_at(mid) >= target:
            hi = mid
        else:
            lo = mid
    # Canonicalise on the grid -- see _cap_for. Here the answer is the SMALLEST
    # grid size that still holds the target, walked down from the bisection.
    q = math.ceil(hi / grid - 1e-9) * grid
    for _ in range(64):
        if cap_at(q) >= target:
            break
        q += grid
    for _ in range(64):
        if q - grid < grid or cap_at(q - grid) < target:
            break
        q -= grid
    n = cap_at(q)
    if n >= target:
        return q, n
    return hi, cap_at(hi)


def _band_step(c):
    """How many characters one row band is worth at this size, roughly.

    The quantum that makes capacity a step function: a shape offers whole row
    bands, so capacity moves in jumps of about chars/bands as the art grows or
    the raster shifts a band across the usability line. Any slack smaller than
    this is inside one step -- real at the raster it was measured on, not a
    margin the answer can be trusted to keep at another.
    """
    return max(1, round(c["chars"] / max(c["bands_fillable"], 1)))


def solve(spec, *, art_mm=None, cap_mm=None, chars=None, floor=None,
          axis="height", want=None):
    """Given any two of {art size, cap height, text length}, return the third.

    The tool the owner asked for, callable without emitting anything:

        art + cap        -> how many characters the art holds (and the shortest
                            text that still fills it)
        cap + characters -> how big the art has to be
        art + characters -> the largest cap height the text will survive

    Whichever of art_mm / cap_mm / chars is left None is the unknown; give all
    three and it answers "does this fit, and by how much" instead. `spec` always
    supplies the silhouette, the tone, the fab, the stroke ratio, the tracking,
    and -- because capacity is prose-dependent -- the prose to measure with.

    THE THREE-GIVEN MODE IS A VERDICT, NOT A STATISTIC. When art, cap and text
    length are all fixed there is nothing left to solve for, so the answer is
    a comparison: `verdict` is "fits" / "underfill" / "overflow", and every
    failing verdict carries the arithmetic to act on it -- how many characters
    short or over, and a remedy MEASURED by running the flow at it (a coarser
    cap that the text on hand fills, a finer cap that holds it, or the art
    size that does). "It does not fit" with no number is treated here as a
    bug, not an answer.

    Every answer is verified: the flow is re-run at the value being reported and
    the capacity that comes back is what the answer carries. Nothing here is
    extrapolated from a fitted law.

    CAPACITY IS QUANTISED BY ROW BANDS, and the report says so. The shape
    offers whole rows of type; growing the art does nothing until the next
    band fits, at which point capacity jumps by roughly one band's worth of
    characters (`band_step_chars`). An answer whose slack is inside one step
    is exact for the raster it was measured on but can lose a band at another
    --shape-raster-px, so any such answer also carries a `robust_*` value that
    holds the target with at least one full band to spare.
    """
    from dataclasses import replace as _replace
    if spec.shape is None:
        raise MicrotextRefused(
            "the sizing solve needs a shape: it solves over the art SIZE, and "
            "a line, a path and a region have no silhouette to resize")
    layers, _mask, cls, _n = plan_tone(spec.tone, allow_buried=spec.allow_buried)
    floor_given = floor is not None
    if floor is None:
        floor, floor_note, _p, _fn = resolve_floor(spec, layers, cls)
    else:
        floor_note = f"caller-supplied {floor:g} mm"
    hmin, hmin_why = min_cap_mm(spec, floor)

    body = _normalise(spec.text)
    if chars is None:
        # The target is len(body) unless the caller named one. It is kept in
        # EVERY mode -- discarding it in the three-given mode is how this tool
        # once answered "1319 characters" to a 2923-character body and stopped.
        chars = len(body)
    if want is None:
        want = ("art" if art_mm is None else
                "cap" if cap_mm is None else "chars")
    if art_mm is None and want != "art":
        art_mm = spec.shape.size_mm(axis)
    if cap_mm is None and want != "cap":
        cap_mm = float(spec.cap_mm)

    res = {
        "want": want, "axis": axis, "floor_mm": floor, "floor_note": floor_note,
        "min_cap_mm": hmin, "min_cap_limited_by": hmin_why,
        "text_layers": list(layers), "sample_chars": len(body),
        "target_chars": chars,
        "hyphenate": bool(spec.hyphenate), "notes": [], "ok": True,
        "shape_source": spec.shape.source,
        "aspect": spec.shape.width_mm / spec.shape.height_mm,
        "raster_px": max(spec.shape.grid.shape),
    }

    # WHAT THE DEFAULTS COST, said before any verdict. A cold first attempt --
    # no --fab, the default stroke, no tracking -- lands on a minimum cap about
    # three times the one the same request earns with a named process and
    # palette-legal type settings, and capacity falls with the square of that.
    # An honest first run must not look impossible for want of two flags nobody
    # told the caller about, so when tighter-but-legal settings materially
    # lower the floor cap, the report says so WITH THE NUMBER.
    if not math.isinf(hmin):
        loosen, tight = [], spec
        if float(spec.tracking_em) < 1.0 / 21 - 1e-12:
            tight = _replace(tight, tracking_em=1.0 / 21)
            loosen.append("--tracking 0.047619 (1/21 em, past which it buys "
                          "nothing)")
        if float(spec.stroke_ratio) > 0.125 + 1e-12:
            tight = _replace(tight, stroke_ratio=0.125)
            loosen.append("--stroke-ratio 0.125 (1:8, the light end of the "
                          "palette's legible band)")
        if loosen:
            h_t, _why_t = min_cap_mm(tight, floor)
            if h_t < hmin - CAP_GRID_MM / 2:
                res["min_cap_tight_mm"] = h_t
                res["notes"].append(
                    f"the {hmin:.4f} mm minimum cap reflects conservative "
                    f"DEFAULTS, not the process: {' and '.join(loosen)} "
                    f"lower{'s' if len(loosen) == 1 else ''} it to {h_t:.4f} "
                    f"mm at this same floor, roughly "
                    f"{(hmin / h_t) ** 2:.1f}x the capacity")
    if spec.fab is None and spec.floor_mm is None and not floor_given:
        res["notes"].append(
            f"no --fab named, so the floor is docs/pcb-palette.md's "
            f"conservative {floor:.4f} mm; a named profile is measured, not "
            f"assumed -- e.g. --fab jlcpcb-4l-fine is a 0.0889 mm floor")

    if want == "chars":
        cap = float(cap_mm)
        if cap < hmin - 1e-9:
            res["ok"] = False
            res["notes"].append(
                f"a {cap:.4f} mm cap height cannot be built on "
                f"{'/'.join(layers)} at a {floor:.4f} mm floor -- the smallest "
                f"that clears every check for this string is {hmin:.4f} mm "
                f"(limited by {hmin_why}). Capacity below is what the geometry "
                f"would hold, not what the process will make.")
        sp = _at_art(spec, art_mm, axis)
        c = capacity(spec, cap_mm=cap, floor=floor, art_mm=art_mm, axis=axis)
        if c is None:
            # Even a dead end hands back a number: the art size that is NOT a
            # dead end, measured, so the refusal is a step and not a wall.
            growth = (None if math.isinf(hmin) else
                      _art_for(sp, floor, max(cap, hmin), chars, axis))
            hint = (f" GROW THE ART to {growth[0]:.2f} mm {axis}: at a "
                    f"{max(cap, hmin):.4f} mm cap it holds {growth[1]} "
                    f"characters, measured by running the flow there."
                    if growth else "")
            raise MicrotextRefused(
                f"no flow is possible at a {cap:.4f} mm cap in a "
                f"{art_mm:.3f} mm {axis} art: either no span is wide enough for "
                f"any piece of this body, or the shape swallows more than "
                f"{CAPACITY_MAX_CHARS} characters of it.{hint}")
        res["capacity"] = c
        res["answer"] = c["chars"]
        res["answer_unit"] = "characters"
        res["art_mm"] = c["art_mm"]
        res["cap_mm"] = cap
        res["band_step_chars"] = _band_step(c)

        # THE VERDICT. All three quantities are fixed, so the answer the
        # caller actually asked for is the comparison, with a measured remedy
        # on every failing branch.
        fill = c["fill_chars"]
        hi_cap = max(sp.shape.height_mm, sp.shape.width_mm) / 2.0
        if chars > c["chars"]:
            over = chars - c["chars"]
            res["verdict"] = "overflow"
            res["overflow_chars"] = over
            res["ok"] = False
            finer = None
            if not math.isinf(hmin) and cap - CAP_GRID_MM > hmin + 1e-9:
                finer = _cap_for(sp, floor, chars, hmin, cap - CAP_GRID_MM)
            if finer is not None:
                res["remedy_cap_mm"], res["remedy_cap_chars"] = finer
                res["verdict_text"] = (
                    f"{chars} characters against a capacity of {c['chars']}: "
                    f"{over} would be truncated at this cap height. LOWER THE "
                    f"CAP to {finer[0]:.4f} mm -- it holds {finer[1]} "
                    f"characters there, measured by re-running the flow -- or "
                    f"cut {over} characters from the end.")
            else:
                growth = (None if math.isinf(hmin) else
                          _art_for(sp, floor, cap, chars, axis))
                if growth is not None:
                    res["remedy_art_mm"], res["remedy_art_chars"] = growth
                res["verdict_text"] = (
                    f"extra text provided: your output will be truncated even "
                    f"at the highest resolution output. {chars} characters "
                    f"against a capacity of {c['chars']} at the "
                    f"{cap:.4f} mm cap"
                    + (" (the finest this process builds for this string)"
                       if abs(cap - hmin) < CAP_GRID_MM else "")
                    + f", so {over} character(s) would be cut."
                    + (f" GROW THE ART to {growth[0]:.2f} mm {axis} -- it "
                       f"holds {growth[1]} characters there, measured by "
                       f"re-running the flow -- or cut exactly {over} "
                       f"character(s) from the end." if growth else
                       f" No art size up to 24 doublings holds them; cut "
                       f"{over} character(s) from the end."))
        elif fill is not None and chars < fill:
            short = fill - chars
            res["verdict"] = "underfill"
            res["short_chars"] = short
            res["spare_chars"] = c["chars"] - chars
            coarser = (None if math.isinf(hmin) else
                       _cap_for(sp, floor, chars, hmin, hi_cap))
            remedy = ""
            if coarser is not None and coarser[0] > cap + CAP_GRID_MM / 2:
                cc = capacity(spec, cap_mm=coarser[0], floor=floor,
                              art_mm=art_mm, axis=axis)
                fills = (cc is not None and cc["fill_chars"] is not None
                         and cc["fill_chars"] <= chars)
                res["remedy_cap_mm"] = coarser[0]
                res["remedy_cap_chars"] = coarser[1]
                res["remedy_cap_fills"] = fills
                remedy = (
                    f" -- at a {coarser[0]:.4f} mm cap the {chars} characters "
                    f"on hand "
                    + (f"fill the art (capacity {coarser[1]}, fills from "
                       f"{cc['fill_chars']}, measured)" if fills else
                       f"come closest (capacity {coarser[1]}, measured)"))
            res["verdict_text"] = (
                f"text length must be at least {fill} characters ({short} "
                f"characters short) to reproduce this image at "
                + ("finest resolution" if abs(cap - hmin) < CAP_GRID_MM else
                   f"this resolution ({cap:.4f} mm cap)")
                + f". Provide more text, or lower the microprinting "
                  f"resolution{remedy}. Nothing is lost either way: every "
                  f"character supplied lands on the board, in order -- the "
                  f"shortfall is row bands left blank.")
        else:
            res["verdict"] = "fits"
            res["spare_chars"] = c["chars"] - chars
            res["verdict_text"] = (
                f"{chars} characters fit with {c['chars'] - chars} to spare "
                f"(capacity {c['chars']}"
                + (f", full from {fill} characters up" if fill is not None
                   else ", though no length of this prose fills every band")
                + f"), measured at the {cap:.4f} mm cap.")
        return res

    if want == "cap":
        # An upper bound that is generous but finite: at a cap this large the
        # art holds one row of a couple of words, so the bracket always closes.
        hi = max(spec.shape.height_mm, spec.shape.width_mm) / 2.0
        sp = _at_art(spec, art_mm, axis)
        got = _cap_for(sp, floor, chars, hmin, hi)
        if got is None:
            c = capacity(spec, cap_mm=hmin, floor=floor, art_mm=art_mm, axis=axis)
            res["ok"] = False
            res["capacity"] = c
            res["cap_mm"] = hmin
            res["art_mm"] = c["art_mm"] if c else None
            res["short_chars"] = chars - (c["chars"] if c else 0)
            # The remedy this branch refuses with is one the art branch can
            # already compute in seconds. Withholding a number the module
            # ALREADY KNOWS is the failure mode this tool exists to not have.
            growth = (None if math.isinf(hmin) else
                      _art_for(sp, floor, hmin, chars, axis))
            if growth is not None:
                res["remedy_art_mm"], res["remedy_art_chars"] = growth
            res["notes"].append(
                f"NO cap height works. At the smallest one this process can "
                f"build -- {hmin:.4f} mm, limited by {hmin_why} against the "
                f"{floor:.4f} mm floor -- a {art_mm:.3f} mm {axis} art holds "
                f"{c['chars'] if c else 0} characters, {res['short_chars']} "
                f"short of {chars}."
                + (f" GROW THE ART to {growth[0]:.2f} mm {axis}: at the "
                   f"{hmin:.4f} mm floor cap it holds {growth[1]} characters, "
                   f"measured by re-running the flow there." if growth else "")
                + f" Or cut {res['short_chars']} characters, or move to a "
                  f"process with a finer floor.")
            return res
        cap, got_chars = got
        c = capacity(spec, cap_mm=cap, floor=floor, art_mm=art_mm, axis=axis)
        res["answer"] = cap
        res["answer_unit"] = "mm cap height"
        res["cap_mm"] = cap
        res["art_mm"] = c["art_mm"]
        res["capacity"] = c
        res["verified"] = c["chars"] >= chars
        res["spare_chars"] = c["chars"] - chars
        res["band_step_chars"] = _band_step(c)
        if abs(cap - hmin) < CAP_GRID_MM:
            res["notes"].append(
                f"this is the process floor itself ({hmin:.4f} mm, limited by "
                f"{hmin_why}) -- there is no margin left in cap height")
        elif res["spare_chars"] < res["band_step_chars"]:
            robust = _cap_for(sp, floor, chars + res["band_step_chars"],
                              hmin, cap)
            if robust is not None and robust[0] < cap - CAP_GRID_MM / 2:
                res["robust_cap_mm"], res["robust_cap_chars"] = robust
                res["notes"].append(
                    f"the {cap:.4f} mm answer has {res['spare_chars']} "
                    f"characters of slack against a ~{res['band_step_chars']}"
                    f"-character row-band step: exact for this raster "
                    f"({res['raster_px']} px) but a band can cross the line "
                    f"at another --shape-raster-px. ROBUST: {robust[0]:.4f} "
                    f"mm holds {robust[1]} characters, at least one full "
                    f"band of slack, measured.")
        return res

    # want == "art"
    got = _art_for(spec, floor, float(cap_mm), chars, axis)
    if got is None:
        res["ok"] = False
        res["notes"].append(
            f"no art size up to 24 doublings holds {chars} characters at a "
            f"{cap_mm:.4f} mm cap. Something else is wrong -- most likely the "
            f"cap is so large that no span in the silhouette fits a word.")
        return res
    art, got_chars = got
    c = capacity(spec, cap_mm=float(cap_mm), floor=floor, art_mm=art, axis=axis)
    res["answer"] = art
    res["answer_unit"] = f"mm {axis}"
    res["art_mm"] = c["art_mm"]
    res["cap_mm"] = float(cap_mm)
    res["capacity"] = c
    res["verified"] = c["chars"] >= chars
    res["spare_chars"] = c["chars"] - chars
    res["band_step_chars"] = _band_step(c)
    if res["spare_chars"] < res["band_step_chars"]:
        # THE KNIFE EDGE, named. Capacity is a step function of art size --
        # nothing happens until the next row band fits, then ~one band's worth
        # of characters arrives at once -- and the raster decides exactly where
        # a band crosses the line. A minimal answer with sub-band slack is
        # therefore exact for the raster it was measured on and only for it.
        # The robust answer buys one full band of margin, which is the
        # smallest unit the geometry deals in.
        robust = _art_for(spec, floor, float(cap_mm),
                          chars + res["band_step_chars"], axis)
        if robust is not None and robust[0] > art + ART_GRID_MM / 2:
            res["robust_art_mm"], res["robust_art_chars"] = robust
            res["notes"].append(
                f"the {art:.2f} mm answer has {res['spare_chars']} "
                f"character(s) of slack against a ~{res['band_step_chars']}"
                f"-character row-band step: exact for this raster "
                f"({res['raster_px']} px) but a band can cross the line at "
                f"another --shape-raster-px. ROBUST: {robust[0]:.2f} mm "
                f"{axis} holds {robust[1]} characters, at least one full "
                f"band of slack, measured.")
    if float(cap_mm) < hmin - 1e-9:
        res["ok"] = False
        res["notes"].append(
            f"the art size is right but the CAP is not buildable: {cap_mm:.4f} "
            f"mm against a {hmin:.4f} mm minimum ({hmin_why}, {floor:.4f} mm "
            f"floor). Solve again at {hmin:.4f} mm to get an art size that can "
            f"actually be made.")
    return res


def print_solve(res, out=None):
    """The solve, on its own, with the arithmetic that produced it."""
    w = (out or sys.stdout).write
    c = res.get("capacity") or {}
    w("\n  " + "-" * 74 + "\n")
    w(f"  SIZING SOLVE -- for {res['want']}, measured on {res['shape_source']}\n")
    w("  " + "-" * 74 + "\n")
    w(f"  floor   : {res['floor_mm']:.4f} mm [{res['floor_note']}]\n")
    w(f"  min cap : {res['min_cap_mm']:.4f} mm on "
      f"{'/'.join(res['text_layers'])} (limited by {res['min_cap_limited_by']})"
      f" -- the process floor, which is what makes capacity knowable in advance\n")
    if res.get("art_mm"):
        w(f"  art     : {res['art_mm'][0]:.3f} x {res['art_mm'][1]:.3f} mm "
          f"({res['art_mm'][0]/25.4:.3f} x {res['art_mm'][1]/25.4:.3f} in)\n")
    if res.get("cap_mm"):
        w(f"  cap     : {res['cap_mm']:.4f} mm\n")
    if c:
        w(f"  bands   : {c['bands_fillable']}/{c['bands']} row bands can carry "
          f"text; {c['spans_filled']}/{c['spans']} spans fill when oversupplied\n")
        w(f"  capacity: {c['chars']} characters -- EXACT for this prose, "
          f"measured by flowing it repeated until the shape overflowed "
          f"({c['sample_chars']} characters supplied)\n")
        if c.get("fill_chars") is not None:
            w(f"  fill at : {c['fill_chars']} characters leave no row band "
              f"blank; between {c['fill_chars']} and {c['chars']} the art is "
              f"full and nothing is cut\n")
        w(f"  breaks  : {c['soft_breaks']} at hyphens the author wrote "
          f"(alters nothing), {c['inserted_hyphens']} inserted"
          f"{' -- --shape-hyphenate is OFF' if not c['hyphenate'] else ''}\n")
    if res.get("answer") is not None:
        w(f"\n  ANSWER  : {res['answer']:.4f} {res['answer_unit']}\n"
          if isinstance(res["answer"], float) else
          f"\n  ANSWER  : {res['answer']} {res['answer_unit']}\n")
        if res.get("spare_chars") is not None and res.get("verdict") is None:
            q = res.get("band_step_chars")
            edge = (q is not None and res["spare_chars"] < q)
            w(f"            {res['spare_chars']:+d} characters of slack "
              f"against the {res.get('target_chars')} asked for, VERIFIED by "
              f"re-running the flow at that value"
              + (f" -- inside one ~{q}-character row-band step, see the "
                 f"ROBUST note" if edge else "") + "\n")
    if res.get("verdict"):
        w(f"\n  VERDICT : {res['verdict'].upper()}\n")
        import textwrap
        for line in textwrap.wrap(res.get("verdict_text", ""), width=66,
                                  break_on_hyphens=False):
            w(f"            {line}\n")
    if res.get("target_chars") and res.get("target_chars") != res["sample_chars"]:
        w(f"            (target {res['target_chars']} characters; packing "
          f"measured with the {res['sample_chars']}-character body supplied, "
          f"because capacity depends on word lengths)\n")
    for n in res["notes"]:
        w(f"  !! {n}\n")
    w("\n")


def recover_text(source, placed, *, inserted=0):
    """Walk the board's text against the source. -> dict, and it has teeth.

    This is the proof that nothing was altered without saying so. `placed` is
    the strings as they will be fabricated, in reading order. The walk allows
    exactly two differences and nothing else:

      - an inter-word SPACE in the source that the board does not carry. The
        flow consumes those at span ends; a space draws no ink, so there is
        nothing to lose.
      - a hyphen on the board that the source does not have -- but only as many
        as were DECLARED. That is the whole point: breaking at a hyphen the
        author already wrote round-trips to the source exactly and needs no
        allowance at all, while inserting one must be declared or this fails.

    A single other character out of place, or in the wrong order, fails. That
    is how a scrambled flow gets caught rather than reported as "98.6% of
    characters placed", which is also what silent truncation looks like.

    `ok` is about ALTERATION and only that. Text the board simply ran out of
    room for is counted in `truncated` and left for the fill verdict to
    adjudicate, because whether a truncation is allowed is a decision the
    caller makes with --shape-allow-truncation and not one this walk should
    pre-empt. A caller reading this dict for "did all of it land" wants
    ok AND truncated == 0. Fed the report's own example -- board
    'for'/'non-rever-' against source 'for non-reversible payments' -- it
    returns ok False with nothing declared, and with one hyphen declared it
    returns ok True and truncated 14. Neither of those is a pass.
    """
    src = _normalise(source)
    joined = "".join(placed)
    i = j = 0
    dropped = found = 0
    while i < len(src) and j < len(joined):
        if src[i] == joined[j]:
            i += 1
            j += 1
        elif src[i] == " ":
            dropped += 1
            i += 1
        elif joined[j] == "-":
            found += 1
            j += 1
        else:
            return {"ok": False, "reason": "diverged", "at": i,
                    "source": src[max(0, i - 28):i + 28],
                    "board": joined[max(0, j - 28):j + 28],
                    "dropped_spaces": dropped, "inserted_found": found,
                    "inserted_declared": inserted, "truncated": None}
    while i < len(src) and src[i] == " ":
        dropped += 1
        i += 1
    trunc = len(src) - i
    left = len(joined) - j
    ok = (left == 0 and found == inserted)
    reason = ("" if ok else
              "the board carries characters the source does not" if left else
              f"{found} inserted hyphen(s) on the board, {inserted} declared")
    return {"ok": ok, "reason": reason, "at": None,
            "dropped_spaces": dropped, "inserted_found": found,
            "inserted_declared": inserted, "truncated": trunc,
            "source_chars": len(src), "board_chars": len(joined)}


def _sexpr_parse(text):
    """A .kicad_mod file -> nested lists; quoted strings arrive unescaped.

    Enough parser for recovery and no more: atoms, quoted strings, KiCad's
    backslash escapes. Local rather than pcbnew because recovery has to run
    wherever the part is, and pcbnew's Python only exists inside a KiCad
    install.
    """
    toks = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', text)
    def unesc(t):
        return re.sub(r"\\(.)",
                      lambda m: {"n": "\n", "t": "\t",
                                 "r": "\r"}.get(m.group(1), m.group(1)), t)
    stack: list[list] = [[]]
    for t in toks:
        if t == "(":
            new: list = []
            stack[-1].append(new)
            stack.append(new)
        elif t == ")":
            if len(stack) == 1:
                raise MicrotextRefused("unbalanced ')' in the file")
            stack.pop()
        elif t.startswith('"'):
            stack[-1].append(unesc(t[1:-1]))
        else:
            stack[-1].append(t)
    if len(stack) != 1 or not stack[0]:
        raise MicrotextRefused("unbalanced '(' in the file")
    return stack[0][0]


def recover_from_part(path):
    """Read the text back OFF an emitted .kicad_mod, in reading order. -> dict

    emit() proves the placed strings against the source with recover_text()
    before a part ships -- and then the proof went down with the process while
    the part lived on. This is the same walk run from the ARTEFACT: the
    fp_text glyphs are read back in reading order, reassembled into runs, and
    -- when the part carries its Microtext property -- walked against that
    stored source with exactly the tolerance the emitter declared (the
    inserted-hyphen count in MicrotextRecipe). A part that has lost its
    inputs can still be read; a part whose geometry was edited since emit
    fails the walk and says where.

    Reads axis-aligned parts. A rotated path run is refused rather than
    mis-ordered: reading order along a polyline is not derivable from anchor
    coordinates alone.
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise MicrotextRefused(f"{path}: no such file")
    node = _sexpr_parse(p.read_text(encoding="utf-8"))
    if not node or node[0] != "footprint":
        raise MicrotextRefused(f"{p.name}: not a footprint (.kicad_mod)")

    props: dict = {}
    glyphs = []
    for it in node[1:]:
        if not isinstance(it, list) or not it:
            continue
        if it[0] == "property" and len(it) >= 3 \
                and isinstance(it[1], str) and isinstance(it[2], str):
            props[it[1]] = it[2]
        elif it[0] == "fp_text" and len(it) >= 3 and isinstance(it[2], str):
            sub = {c[0]: c for c in it if isinstance(c, list) and c}
            at, layer = sub.get("at"), sub.get("layer")
            if at is None or layer is None:
                continue
            x, y = float(at[1]), float(at[2])
            ang = float(at[3]) if len(at) > 3 else 0.0
            cap = None
            for c in sub.get("effects", []):
                if isinstance(c, list) and c and c[0] == "font":
                    for cc in c:
                        if isinstance(cc, list) and cc and cc[0] == "size":
                            cap = float(cc[1])
            glyphs.append((layer[1], x, y, ang, cap, it[2]))
    if not glyphs:
        raise MicrotextRefused(
            f"{p.name}: no fp_text on the part -- nothing to read back")

    from collections import Counter
    lay = Counter(g[0] for g in glyphs).most_common(1)[0][0]
    glyphs = [g for g in glyphs if g[0] == lay]
    if any(abs(g[3]) > 0.01 for g in glyphs):
        raise MicrotextRefused(
            f"{p.name}: rotated fp_text on {lay} -- recovery reads "
            f"axis-aligned parts (line, region and shape placements)")
    caps = sorted(g[4] for g in glyphs if g[4])
    if not caps:
        raise MicrotextRefused(f"{p.name}: fp_text carries no font size")
    cap = caps[len(caps) // 2]

    recipe: dict = {}
    if PROP_RECIPE in props:
        try:
            recipe = json.loads(props[PROP_RECIPE])
        except ValueError:
            recipe = {}

    # Rows: cluster on y. Runs in one band share their anchor to the writer's
    # four decimals and adjacent bands sit at least an ink height apart, so a
    # quarter cap splits bands and never splits a band.
    rows: list[list] = []
    for g in sorted(glyphs, key=lambda g: (g[2], g[1])):
        if rows and abs(g[2] - rows[-1][-1][2]) <= 0.25 * cap:
            rows[-1].append(g)
        else:
            rows.append([g])
    for r in rows:
        r.sort(key=lambda g: g[1])

    # One fp_text per glyph (tracking) or one per run? The recipe answers
    # exactly; without one, a part that is >90% single-character strings is
    # per-glyph -- no prose is.
    per_glyph = sum(1 for g in glyphs if len(g[5]) == 1) > 0.9 * len(glyphs)
    if "tracking_em" in recipe:
        per_glyph = float(recipe["tracking_em"] or 0.0) != 0.0
    space_adv = stroke_font.GLYPHS.get(" ", (0.4, None, None))[0]

    def adv(ch):
        return stroke_font.GLYPHS.get(ch, (stroke_font.MAX_ADVANCE_EM,
                                           None, None))[0]

    placed: list[str] = []
    if not per_glyph:
        for r in rows:
            parts: list[str] = []
            for g in r:
                if parts and not parts[-1].endswith("-"):
                    parts.append(" ")
                parts.append(g[5])
            placed.append("".join(parts))
    else:
        # Spaces are never emitted (they draw no ink), so they are read back
        # from the pen: a step past advance+tracking by half a space is a
        # space. After a hyphen no space is inferred -- a span that ends
        # mid-word at a hyphen glues to the next span, and inventing a space
        # there would turn 'non-'+'reversible' into a divergence.
        t = float(recipe.get("tracking_em", 0.0) or 0.0)
        if "tracking_em" not in recipe:
            gaps = [(g1[1] - g0[1]) / cap - adv(g0[5])
                    for r in rows for g0, g1 in zip(r, r[1:])]
            t = max(0.0, min(gaps)) if gaps else 0.0
        for r in rows:
            buf = [r[0][5]]
            for g0, g1 in zip(r, r[1:]):
                extra = (g1[1] - g0[1]) / cap - adv(g0[5]) - t
                if extra > 0.5 * (space_adv + t) and not buf[-1].endswith("-"):
                    buf.append(" ")
                buf.append(g1[5])
            placed.append("".join(buf))

    text = ""
    for s in placed:
        if text and not text.endswith("-"):
            text += " "
        text += s

    out = {"file": str(p), "layer": lay, "cap_mm": cap, "rows": len(rows),
           "glyphs": len(glyphs), "per_glyph": per_glyph, "placed": placed,
           "text": text, "properties": sorted(props),
           "recipe": recipe or None,
           "source_property": PROP_TEXT in props, "integrity": None}
    # The walk's tolerance model (consumed span-end spaces, declared hyphens)
    # is the SHAPE flow's. A line run is the degenerate case of it; a region
    # or path part REPEATS its string, so walking the repetitions against one
    # copy of the source would report a divergence that is not one. Read
    # those, don't judge them.
    if PROP_TEXT in props and recipe.get("mode", "shape") in ("shape", "line"):
        ins = len(recipe.get("inserted_hyphens") or [])
        out["integrity"] = recover_text(props[PROP_TEXT], placed,
                                        inserted=ins)
    return out


def _art_remedy(spec, floor, cap, target, axis, *, want, verify):
    """The art size that fixes this, MEASURED, with the flow that proves it.

    want="hold"  the SMALLEST art that holds the whole body -- the overfill
                 remedy, and the only one of the three that neither approaches
                 the process floor nor removes a word.
    want="fill"  the LARGEST art that the body on hand still fills without
                 overflowing -- the underfill remedy that leaves the cap height
                 where the caller put it.

    The predicate IS `verify`, run on the real body at every size tried, not a
    capacity number standing in for it. Capacity is used for the opening guess
    and for nothing else: it decides how many flows this costs, never what the
    answer is. The answer is then snapped to ART_GRID_MM and walked to the
    extreme grid point that still passes, so the same question asked from two
    different starting sizes comes back with the same millimetres.

    -> (art_mm, [w_mm, h_mm], flow at that size) or None.
    """
    def ok(s):
        if s <= ART_GRID_MM * 2:
            return False
        f = _flow_at(_at_art(spec, s, axis), cap, floor)
        return f is not None and verify(f)

    cur = spec.shape.size_mm(axis)
    if want == "hold":
        c = capacity(spec, cap_mm=cap, floor=floor, art_mm=cur, axis=axis)
        hi = cur
        if c and c["chars"] > 0 and target > c["chars"]:
            hi = cur * math.sqrt(target / c["chars"])
        lo = cur
        for _ in range(30):
            if ok(hi):
                break
            lo, hi = hi, hi * 1.25
        else:
            return None
        for _ in range(48):
            if hi - lo <= ART_GRID_MM:
                break
            mid = (lo + hi) / 2.0
            if ok(mid):
                hi = mid
            else:
                lo = mid
        art = math.ceil(hi / ART_GRID_MM - 1e-9) * ART_GRID_MM
        for _ in range(64):
            if ok(art):
                break
            art += ART_GRID_MM
        else:
            return None
        for _ in range(64):
            if not ok(art - ART_GRID_MM):
                break
            art -= ART_GRID_MM
    else:
        # THE WINDOW, and why the search is not run on `ok` directly.
        #
        # Two things move in opposite directions as the art shrinks: the blank
        # bands close (monotone) and the text starts to overflow (monotone the
        # other way). So the sizes that work are a WINDOW, [smallest that holds
        # the whole body, largest that leaves no band blank], and a bisection
        # driven by their conjunction steps straight over it -- measured, a
        # 40 mm rectangle at half capacity has a window 0.8 mm wide and a
        # geometric probe misses it entirely.
        #
        # So the search runs on the monotone half -- "no band is blank" -- and
        # takes its largest grid point, which is the top of the window. The
        # full predicate is then checked there once: if the whole body does not
        # fit at the top of the window, the window is empty and there is no art
        # size that both fills this shape and holds this text.
        def closes(s):
            if s <= ART_GRID_MM * 2:
                return False
            f = _flow_at(_at_art(spec, s, axis), cap, floor)
            return f is not None and bool(f.runs) and not f.bands_abandoned
        hi, lo = cur, cur
        for _ in range(40):
            lo *= 0.85
            if lo <= ART_GRID_MM * 4:
                return None
            if closes(lo):
                break
        else:
            return None
        for _ in range(48):
            if hi - lo <= ART_GRID_MM / 4.0:
                break
            mid = (lo + hi) / 2.0
            if closes(mid):
                lo = mid
            else:
                hi = mid
        art = math.floor(lo / ART_GRID_MM + 1e-9) * ART_GRID_MM
        for _ in range(64):
            if closes(art):
                break
            art -= ART_GRID_MM
            if art <= ART_GRID_MM * 2:
                return None
        for _ in range(64):
            if not closes(art + ART_GRID_MM):
                break
            art += ART_GRID_MM
    sp2 = _at_art(spec, art, axis)
    f2 = _flow_at(sp2, cap, floor)
    if f2 is None or not verify(f2):
        return None
    return art, [sp2.shape.width_mm, sp2.shape.height_mm], f2


def _fill_verdict(spec, rep, fl, cap):
    """Underfill and overfill, both loud, both actionable. Can raise.

    Also fills rep["fill"] with the row-fill distribution whatever the verdict,
    because "M of N spans filled" was never the number that tells a reader
    whether the artwork reads.
    """
    w_filled = sum(s.width for s in fl.filled)
    w_lost = sum(s.width for s in fl.abandoned_usable)
    empty = fl.bands_abandoned
    # What check() already worked out before any of this ran. It is the same
    # arithmetic, measured the same way; this verdict is where it is CONFIRMED
    # against the flow of the real body rather than where it is discovered.
    cap_rep = rep.get("capacity")

    # Characters of INPUT per mm of span, as this run actually achieved it on
    # this text at this cap in this shape. Calibrating on the run itself is the
    # only estimator this module can stand behind: it already contains the
    # greedy flow's ragged right edge, this body's word lengths and this font's
    # advances, none of which a closed form knows.
    cpm = (len(spec.text) / w_filled) if w_filled > 1e-9 else None
    if cpm is None and rep.get("advance_mm"):
        cpm = len(spec.text) / rep["advance_mm"]

    fill = {
        "bands": fl.bands,
        "bands_with_text": len(fl.bands_with_text),
        "bands_empty": fl.bands - len(fl.bands_with_text),
        "bands_underfilled": len(empty),
        "spans_total": len(fl.spans),
        "spans_filled": len(fl.filled),
        "spans_narrow": len(fl.narrow),
        "spans_abandoned": len(fl.abandoned),
        "spans_abandoned_usable": len(fl.abandoned_usable),
        "width_filled_mm": w_filled,
        "width_narrow_mm": sum(s.width for s in fl.narrow),
        "width_abandoned_usable_mm": w_lost,
        "chars_per_mm": cpm,
        "row_chars": _row_chars(fl),
        "verdict": "fits",
        "shortfall_chars": None,
        "need_chars": None,
        "surplus_chars": None,
        "remedy_cap_mm": None,
        "remedy_cap_verified": False,
        "remedy_art_mm": None,
        "remedy_art_wh_mm": None,
        "remedy_art_scale": None,
        "remedy_art_verified": False,
        "finest_cap_mm": None,
        "estimate": None,
        "capacity_chars": (cap_rep or {}).get("chars"),
        "fill_chars": (cap_rep or {}).get("fill_chars"),
    }
    rep["fill"] = fill

    # ---- OVERFILL: the shape ran out before the text did ------------------
    if fl.words_left or fl.unplaced:
        rest = fl.unplaced
        fill["verdict"] = "overfill"
        fill["surplus_chars"] = len(rest)

        # A SMALLER cap is a FINER resolution: more rows, each narrower, so more
        # capacity. It cannot go below the smallest cap that clears every fab
        # and legibility check for this string on this layer -- that number is
        # already computed, from the same stroke_font arithmetic the refusal
        # above uses, and it is what "the fabricable range" means here.
        finest = rep["min_cap"]["recommended_mm"]
        fill["finest_cap_mm"] = finest
        found = None
        if finest and not math.isinf(finest) and finest < cap - 1e-9:
            found = _bisect_cap(
                spec, rep["floor_mm"], cap, finest,
                lambda f: bool(f.runs) and not (f.words_left or f.unplaced))
        # THE ART-SIZE REMEDY. It is computed first because it is the one this
        # module recommends: growing the art is the only fix here that neither
        # walks the letterforms toward the process floor nor deletes a word the
        # author wrote.
        axis = "height"
        L = len(_normalise(spec.text))
        art = _art_remedy(spec, rep["floor_mm"], cap, L, axis,
                          want="hold",
                          verify=lambda f: bool(f.runs) and not f.unplaced)
        if art is not None:
            fill["remedy_art_mm"] = art[0]
            fill["remedy_art_wh_mm"] = art[1]
            fill["remedy_art_verified"] = True
            fill["remedy_art_scale"] = art[0] / spec.shape.size_mm(axis)
        head = (f"OVERFILL -- the shape ran out before the text did. "
                f"{len(rest)} character(s) in {fl.words_left} word(s) DID NOT "
                f"FIT and would be TRUNCATED, starting {rest[:56]!r}. Extra "
                f"text provided: {fl.words_placed}/{fl.words_total} words and "
                f"{fl.chars_placed} of {len(spec.text)} characters fit at a "
                f"{cap:.4f} mm cap in a {spec.shape.width_mm:.2f} x "
                f"{spec.shape.height_mm:.2f} mm shape."
                + (f" This was known BEFORE the flow ran: this art holds "
                   f"{cap_rep['chars']} characters of this prose and "
                   f"{cap_rep['text_chars']} were supplied."
                   if cap_rep else ""))
        grow = ""
        if art is not None:
            grow = (f"\n  GROW THE ART to {art[0]:.2f} mm "
                    f"{axis} ({art[1][0]:.2f} x {art[1][1]:.2f} mm, "
                    f"{art[1][0]/25.4:.2f} x {art[1][1]/25.4:.2f} in, "
                    f"{fill['remedy_art_scale']:.3f}x what was asked for). "
                    f"MEASURED: the flow was re-run on this exact body at that "
                    f"size and all {fl.words_total} words fit."
                    f"\n  THAT IS THE ONE TO TAKE if the board has the room. A "
                    f"finer cap height walks the letterforms TOWARD the "
                    f"{rep['floor_mm']:.4f} mm {rep['floor_class']} floor, "
                    f"which is the direction that stops being manufacturable; "
                    f"cutting text deletes the author's words. Growing the art "
                    f"does neither.")
        if found is not None:
            fill["remedy_cap_mm"], fill["remedy_cap_verified"] = found[0], True
            fix = (grow +
                   f"\n  Or CUT exactly {len(rest)} characters "
                   f"({fl.words_left} words) from the end, or RAISE "
                   f"the microprinting resolution to a {found[0]:.4f} mm cap "
                   f"height -- finer, so more and narrower rows. That cap is "
                   f"MEASURED, not modelled: the flow was re-run at exactly "
                   f"{found[0]:.4f} mm and all {fl.words_total} words fit.")
        else:
            still = 0
            if finest and not math.isinf(finest) and finest < cap - 1e-9:
                ff = _flow_at(spec, finest, rep["floor_mm"])
                still = len(ff.unplaced) if ff is not None else len(rest)
            else:
                still = len(rest)
            fill["chars_over_at_finest"] = still
            fix = (grow + f"\n  There is NO finer resolution to raise to. The "
                   f"smallest cap height this string can be set at on "
                   f"{'/'.join(rep['text_layers'])} is "
                   f"{finest:.4f} mm (limited by "
                   f"{rep['min_cap']['limited_by']} against the "
                   f"{rep['floor_mm']:.4f} mm {rep['floor_class']} floor), and "
                   f"at {finest:.4f} mm this body is STILL about {still} "
                   f"characters too long. This text cannot be made to fit this "
                   f"shape at this process: cut exactly {len(rest)} characters "
                   f"({fl.words_left} words) from the end of the body, "
                   + (f"grow the art to {art[0]:.2f} mm {axis} (measured "
                      f"above), " if art is not None else "enlarge the shape, ")
                   + f"or move to a process with a finer floor.")
        why = ("\n  Refusing to truncate the text silently. Microprinting is "
               "unreadable without a loupe, so a truncation nobody announced "
               "is a defect nobody would ever catch -- unlike an empty band, "
               "there is no blank for a reader to notice. Pass "
               f"--{spec.flag_prefix}shape-allow-truncation to drop the tail "
               "on purpose; it becomes a warning and the dropped text is "
               "recorded in the report.")
        if spec.allow_truncation:
            fill["truncated"] = rest
            rep["warnings"].append(
                head + fix + f"\n  TRUNCATED ON PURPOSE "
                f"(--{spec.flag_prefix}shape-allow-truncation): the "
                f"{len(rest)} characters above are NOT on the board.")
        else:
            raise MicrotextRefused(head + fix + why)
        return

    # ---- UNDERFILL: the text ran out before the shape did ------------------
    #
    # THE THRESHOLD, and why it is this and not a percentage.
    #
    # "Fraction of bands carrying text" is not the measure. Measured over 19
    # runs on 9 shapes in this tree it ranges from 0% to 100% and does not
    # separate the cases: reckless_black at a 0.8 mm cap carries text in 15 of
    # 43 bands (34.9%) and is NOT underfilled -- 180 of its 197 spans are
    # slivers between strokes that no word ever fits -- while the shipped
    # art_btc_whitepaper_b carries text in 52 of 58 (89.7%) and IS underfilled:
    # the bottom stems of the mark are blank because section 1 ran out.
    #
    # So the measure is capacity ABANDONED: span width that the flow reached,
    # that was wide enough to hold the narrowest word in the body, and that got
    # nothing because there were no words left. That number is exactly 0 for
    # all 15 runs where the text did not run out, and 84.9 / 126.8 / 119.1 /
    # 508.9 mm for the 4 where it did. There is no measured case in between.
    #
    # The bar is ONE WHOLE BAND. A band is the unit the eye sees: an empty one
    # is a stripe across the silhouette. Anything smaller is the ragged right
    # edge of the last span, which every flowed text has by construction and
    # which no amount of extra text removes. On the four underfilled runs the
    # smallest shortfall is 5 bands, so the bar is not what decides them; it is
    # there so the tool does not cry about half an empty span.
    if not empty:
        return

    fill["verdict"] = "underfill"
    # The density figure is kept, because it is the cheap sanity check on the
    # measured one and because it is the number a reader can recompute from the
    # rest of the report. It is NOT what is quoted.
    dens = int(round(w_lost * cpm)) if cpm else None
    fill["shortfall_by_density_chars"] = dens
    # The exact fill line, when one exists: capacity() reads it straight off the
    # span inventory of one oversupplied flow. It is used as the SEED here
    # rather than as the answer, because "the smallest addition that clears the
    # last band" is asked of arbitrary text and a body cut mid-word ends in a
    # narrower word that can clear a band the whole one could not. The
    # bisection below is what answers the question as asked; the exact number
    # is what makes it cheap and is reported beside it.
    exact = None
    if cap_rep and cap_rep.get("fill_chars") is not None:
        exact = max(1, cap_rep["fill_chars"] - len(_normalise(spec.text)))
    fill["shortfall_exact_chars"] = exact
    short = _chars_to_fill(spec, cap, rep["floor_mm"], guess=(exact or dens))
    fill["shortfall_measured"] = short is not None
    if short is None:
        short = dens
    fill["shortfall_chars"] = short
    fill["need_chars"] = (len(spec.text) + short) if short is not None else None
    fill["estimate"] = (
        (f"the flow was re-run with this body extended by its own prose, and "
         f"{short} more characters is the smallest addition that leaves no "
         f"band blank -- measured, not modelled"
         + (f" (a width-times-density figure off the {w_lost:.2f} mm of "
            f"abandoned span says {dens} instead"
            + (", which reads high because a greedy flow wastes more of a "
               "narrow span than of a wide one, and the abandoned spans are "
               "the narrow ones" if dens > short else "")
            + ")" if dens is not None and dens != short else ""))
        if fill["shortfall_measured"] else
        (f"{w_lost:.2f} mm of abandoned span width at the {cpm:.4f} input "
         f"characters per mm this run achieved over the {w_filled:.2f} mm it "
         f"did fill" if cpm else
         "no span was filled, so nothing calibrates it"))

    # LOWERING the microprinting resolution means a LARGER cap: fewer rows,
    # each wider, so less capacity -- which is what makes the text on hand
    # enough. Searched on "no band is abandoned", which is monotone in cap;
    # whether the whole body still fits there is then checked separately,
    # because the two can fail in opposite directions.
    found = _bisect_cap(spec, rep["floor_mm"], cap, cap * 3.0,
                        lambda f: bool(f.runs) and not f.bands_abandoned)
    # THE OTHER REMEDY, in art size rather than cap height. Same standard of
    # proof: the size is bisected on measured capacity and then the REAL body
    # is flowed into the shape at that size, and it only gets reported if that
    # flow both fills every band and loses nothing.
    axis = "height"
    L = len(_normalise(spec.text))
    art = _art_remedy(
        spec, rep["floor_mm"], cap, L, axis, want="fill",
        verify=lambda f: bool(f.runs) and not f.bands_abandoned and not f.unplaced)
    smaller = ""
    if art is not None:
        fill["remedy_art_mm"] = art[0]
        fill["remedy_art_wh_mm"] = art[1]
        fill["remedy_art_verified"] = True
        fill["remedy_art_scale"] = art[0] / spec.shape.size_mm(axis)
        smaller = (f", or SHRINK THE ART to {art[0]:.2f} mm {axis} "
                   f"({art[1][0]:.2f} x {art[1][1]:.2f} mm, "
                   f"{fill['remedy_art_scale']:.3f}x what was asked for), which "
                   f"the text on hand fills exactly -- MEASURED, the flow was "
                   f"re-run on this body at that size and no band is blank")
    coarser = ""
    if found is not None and not (found[1].words_left or found[1].unplaced):
        fill["remedy_cap_mm"], fill["remedy_cap_verified"] = found[0], True
        coarser = (f", or lower the microprinting resolution to a "
                   f"{found[0]:.4f} mm cap height -- coarser, so fewer and "
                   f"wider rows. MEASURED: the flow was re-run at exactly "
                   f"{found[0]:.4f} mm and every band carries text")
    elif found is not None:
        fill["remedy_cap_mm"] = found[0]
        coarser = (f". Lowering the resolution does not work here: at "
                   f"{found[0]:.4f} mm the shape is full but "
                   f"{len(found[1].unplaced)} characters of this same body no "
                   f"longer fit, so there is no cap on the "
                   f"{CAP_GRID_MM:g} mm grid that both fills the shape and "
                   f"holds the whole text. More text is the only remedy")
    else:
        coarser = (f". Lowering the resolution does not work here: no cap "
                   f"height up to {cap * 3.0:.3f} mm fills every band. More "
                   f"text is the only remedy")

    # WHICH ONE TO TAKE. Both are free of the failure that matters -- neither
    # loses a character -- so the tie is broken on the two things that are not
    # symmetric: a LARGER cap height moves every stroke and every counter
    # further from the process floor, so the part gets easier to build rather
    # than harder; and the art size is usually the thing the board already
    # committed to, while the cap height is not. Shrinking the art is the right
    # answer only when the coarser cap has stopped being microprinting.
    pick = ""
    if found is not None and not (found[1].words_left or found[1].unplaced):
        pick = (f"\n     TAKE THE CAP HEIGHT. {found[0]:.4f} mm is "
                f"{found[0]/cap:.2f}x the stroke and counter clearances this "
                f"run has, so it moves AWAY from the "
                f"{rep['floor_mm']:.4f} mm {rep['floor_class']} floor and the "
                f"part gets easier to build, and it leaves the art footprint "
                f"the board already committed to alone."
                + (f" Shrink the art to {art[0]:.2f} mm instead only if a "
                   f"{found[0]:.4f} mm cap has stopped being microprinting for "
                   f"this design." if art is not None else ""))
    elif art is not None:
        pick = (f"\n     TAKE THE ART SIZE: {art[0]:.2f} mm {axis}. No cap "
                f"height on the {CAP_GRID_MM:g} mm grid both fills this shape "
                f"and holds this whole text, and that one does.")
    need = ("more text" if short is None
            else f"at least about {len(spec.text) + short} characters "
                 f"(about {short} characters short)")
    rep["warnings"].append(
        f"UNDERFILL -- the text ran out before the shape did. "
        f"{len(empty)} of {fl.bands} row bands are blank because there were no "
        f"words left to put in them, NOT because they were too narrow: "
        f"{len(fl.abandoned_usable)} mask span(s), {w_lost:.2f} mm of usable "
        f"width, got nothing. Text length must be {need} to reproduce this "
        f"image at a {cap:.4f} mm cap height. Provide more text{coarser}"
        f"{smaller}."
        + (f"\n     The character count is an ESTIMATE and this is where it "
           f"comes from: {fill['estimate']}. "
           f"It is LUMPY: whether the last band fills turns on one word "
           f"landing in it, so prose with different word lengths can clear the "
           f"same shape with a fraction of this, or need more. It is the size "
           f"of the gap, not a target." if short is not None else "")
        + pick)
    if spec.require_fill:
        raise MicrotextRefused(rep["warnings"][-1] + (
            f"\n  Refused because --{spec.flag_prefix}shape-require-fill was "
            f"given. Without it this is a warning: every character supplied is "
            f"on the board, in order, and the shortfall is VISIBLE -- unlike a "
            f"sub-floor stroke, a reader can see the blank."))


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
    floor = rep["floor_mm"]
    gap = spec.row_gap_mm if spec.row_gap_mm is not None else floor
    if gap < floor - 1e-9:
        rep["warnings"].append(
            f"--{spec.flag_prefix}row-gap {gap:.4f} mm leaves less than the "
            f"{floor:.3f} mm {rep['floor_class']} floor between the ink of "
            f"adjacent rows; ascenders and descenders will touch and the rows "
            f"will read as one block. Not clamped -- this is what you asked for.")

    fl = _flow(spec, cap, floor)
    shape = spec.shape

    rep["row_pitch_mm"] = fl.pitch
    rep["row_gap_mm"] = gap
    rep["row_ink_mm"] = fl.ink_h
    rep["rows"] = fl.bands
    rep["rows_with_text"] = len(fl.bands_with_text)
    rep["spans_total"] = len(fl.spans)
    rep["spans_filled"] = len(fl.filled)
    rep["spans_empty"] = len(fl.narrow)
    rep["spans_abandoned"] = len(fl.abandoned)
    rep["words_total"] = fl.words_total
    rep["words_placed"] = fl.words_placed
    rep["chars_placed"] = fl.chars_placed
    rep["chars_total"] = len(spec.text)
    rep["shape_source"] = shape.source
    rep["shape_raster_tool"] = shape.raster_tool
    rep["shape_mm"] = [shape.width_mm, shape.height_mm]
    rep["shape_area_mm2"] = shape.area_mm2()
    rep["hyphenated"] = bool(spec.hyphenate)

    # WHAT WAS DONE TO THE TEXT, split by whether it changed the text.
    #
    # A break at a hyphen the author already wrote changes nothing: the line
    # ends where the author put a hyphen, and joining the pieces back up
    # returns the word character for character. It is counted here because it
    # is worth knowing how much of the fill came from ordinary typesetting, and
    # for no other reason -- it needs no disclosure and gets none.
    #
    # An INSERTED hyphen is a character on the board the author did not write.
    # Every one of them is listed, by word, and the list is what
    # rep["integrity"] is checked against below.
    rep["soft_breaks"] = fl.soft_breaks
    rep["inserted_hyphens"] = [
        {"word": h["word"], "as_set": h["head"] + h["tail"], "band": h["band"]}
        for h in fl.inserted]
    if fl.inserted:
        rep["warnings"].append(
            f"{len(fl.inserted)} hyphen(s) were INSERTED into words that are "
            f"not hyphenated in the source, because "
            f"--{spec.flag_prefix}shape-hyphenate was given: "
            + "; ".join(f"{h['word']!r} set as {h['head']!r}+{h['tail']!r}"
                        for h in fl.inserted[:8])
            + (f" and {len(fl.inserted)-8} more" if len(fl.inserted) > 8 else "")
            + ". That is a change to the author's text and this is the notice "
              "of it. Breaks taken at hyphens the author already wrote are NOT "
              f"in this list and need none -- there were {fl.soft_breaks} of "
              f"those, and they add and remove nothing.")

    if fl.narrow:
        w_min = min(s.width for s in fl.narrow)
        w_max = max(s.width for s in fl.narrow)
        rep["warnings"].append(
            f"{len(fl.narrow)} of {len(fl.spans)} mask spans were left empty: "
            f"they are {w_min:.3f}-{w_max:.3f} mm wide and the next word in the "
            f"text did not fit"
            + ("" if spec.hyphenate else
               f" (no hyphenation -- pass --{spec.flag_prefix}shape-hyphenate "
               f"to break words)")
            + ". Nothing was dropped AT THESE SPANS -- the text flowed on to "
              "the next one. Those parts of the shape are simply blank. "
              "Whether anything was dropped at the END of the body is the "
              "fill verdict's business, not this warning's.")

    # The whole point of this round. Both directions, same code path, matching
    # messages -- and it can raise, so it runs before the emptier refusal below.
    _fill_verdict(spec, rep, fl, cap)

    if not fl.runs:
        raise MicrotextRefused(
            f"no span in the shape was wide enough for a single word at a "
            f"{cap:.4f} mm cap height")
    # Every span the flow ran against -- filled, narrow and abandoned alike.
    # Their union IS the art silhouette as this flow saw it, and place() cuts
    # the mask opening from exactly this list, so the opening and the text
    # can never disagree about what the shape was. Private key: place() pops
    # it before the report is serialised.
    rep["_flow_spans"] = [(s.y, s.x0, s.x1) for s in fl.spans]
    return fl.runs


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

    # THE PROOF THAT NOTHING WAS ALTERED WITHOUT SAYING SO.
    #
    # "98.6% of characters placed" is also what silent truncation looks like,
    # so the claim is not made from a percentage. The strings that will be
    # fabricated are walked against the source in reading order, and the walk
    # allows exactly two differences: an inter-word space the flow consumed at
    # a span end, and an inserted hyphen -- but only as many as this run
    # DECLARED. A break at an existing hyphen therefore has to round-trip to
    # the source exactly, because nothing in the walk would forgive it.
    if spec.mode == "shape":
        ins = len(rep.get("inserted_hyphens") or [])
        rep["integrity"] = recover_text(spec.text, [r.text for r in runs],
                                        inserted=ins)
        if not rep["integrity"]["ok"]:
            raise MicrotextRefused(
                f"the text on the board does not walk back to the source: "
                f"{rep['integrity']['reason']}"
                + (f" at source character {rep['integrity']['at']}\n"
                   f"    source: {rep['integrity'].get('source')!r}\n"
                   f"    board : {rep['integrity'].get('board')!r}"
                   if rep["integrity"].get("at") is not None else "")
                + f"\n  {rep['integrity']['inserted_found']} hyphen(s) on the "
                  f"board are not in the source and {ins} were declared. This "
                  f"is the check that stops an altered text shipping as an "
                  f"unaltered one, and it has just fired.")

    openings: list[list] = []
    rep["mask_bleed_mm"] = float(spec.mask_bleed_mm)
    flow_spans = rep.pop("_flow_spans", None)
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
        if spec.mode == "region":
            # One opening over the whole block: the doc's form 1, exactly.
            # A region IS a rectangle, so its silhouette and its bounding box
            # are the same shape and there is nothing to follow.
            xs = [p[0] for r in runs for p in r.quad]
            ys = [p[1] for r in runs for p in r.quad]
            openings = [[(min(xs) - bleed, min(ys) - bleed),
                         (max(xs) + bleed, min(ys) - bleed),
                         (max(xs) + bleed, max(ys) + bleed),
                         (min(xs) - bleed, max(ys) + bleed)]]
            rep["openings_merged"] = 0
            rep["opening_form"] = "block"
        elif spec.mode == "shape":
            # The opening follows the ART SILHOUETTE (issue #15): the union of
            # the row band spans the flow ran against, each grown by the bleed.
            #
            # This code used to cut one bounding-box rectangle here and argue
            # registration for it. The registration argument was real but it
            # was about the LETTERFORMS: an opening that hugged each glyph
            # would need its edge placed against a ~0.10 mm stroke to a
            # tolerance (+/-0.05 mm) the process does not have. The silhouette
            # edge is not that edge. It lands in empty laminate between the
            # outermost glyphs and the shape boundary, cleared from every
            # glyph by the same bleed the block enjoyed, and there is still
            # exactly one edge to register -- it just isn't a rectangle. What
            # the rectangle actually cost was the artwork: the emitted part
            # carried the whole shape as one bare-laminate block and left the
            # silhouette to be inferred from the copper alone, when T3 (mask
            # opening over bare laminate) is a tone this palette owns and the
            # opening itself can draw the art.
            #
            # The spans already bound the INK -- flow reserves the half-pen on
            # every side inside each span -- so the growth here is the asked-
            # for bleed alone; adding the half-stroke again would overstate
            # the clearance the report claims. A glyph that exactly fills its
            # span touches the span edge, so the measured worst-case clearance
            # IS spec.mask_bleed_mm, the same number the block delivered.
            ink_h = rep["row_ink_mm"]
            g = float(spec.mask_bleed_mm)
            rects = [(x0 - g, y - g, x1 + g, y + ink_h + g)
                     for (y, x0, x1) in flow_spans]
            loops, covered_fn = _rect_union(rects)

            # A polygon opening can do one thing a rectangle cannot: leave a
            # web of mask thinner than the process dam wherever the silhouette
            # pinches. Measured on the exact loops to be emitted, and refused
            # -- a sub-dam web washes away and the lobes merge with an edge
            # nobody drew.
            dam, dam_src = FLOOR_MASK_DAM, "docs/pcb-palette.md"
            fabrep = rep.get("fab")
            if fabrep is not None and fabrep["min_mask_dam_mm"] is not None:
                dam, dam_src = fabrep["min_mask_dam_mm"], fabrep["name"]
            elif fabrep is not None:
                rep["warnings"].append(
                    f"{fabrep['name']} publishes no minimum mask dam; the "
                    f"silhouette opening's narrowest mask web was checked "
                    f"against the palette's {FLOOR_MASK_DAM:.2f} mm instead. "
                    f"Ask the fab before ordering.")
            rep["mask_dam_mm"] = dam
            narrow, at_pt = _mask_corridors(loops, covered_fn, 2.0 * dam)
            rep["mask_corridor_mm"] = narrow
            if narrow is not None and narrow < dam - 1e-9:
                raise MicrotextRefused(
                    f"the silhouette opening leaves a {narrow:.3f} mm web of "
                    f"mask near ({at_pt[0]:.2f}, {at_pt[1]:.2f}) mm, under "
                    f"the {dam:.2f} mm mask dam ({dam_src}). Two lobes of "
                    f"the opening close to less than the dam there, and a "
                    f"web that thin washes away in processing -- the lobes "
                    f"merge with an edge nobody designed. Widen the art "
                    f"where it pinches, or reduce --{spec.flag_prefix}"
                    f"mask-bleed (currently {g:.3f} mm) so the openings "
                    f"stand further apart.")

            openings, holes_kept, unbridged = _silhouette_openings(loops)
            if unbridged:
                raise MicrotextRefused(
                    f"{unbridged} counter(s) in the silhouette opening could "
                    f"not be joined to an outer boundary -- emitting them "
                    f"would fill an enclosed hole with bare laminate that "
                    f"the artwork keeps masked. This is a bug in the union, "
                    f"not in the shape; do not ship the part.")
            rep["openings_merged"] = 0
            rep["opening_form"] = "silhouette"
            rep["opening_holes"] = holes_kept
            rep["opening_vertices"] = sum(len(o) for o in openings)
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
                        f"Ask the fab, or use --{spec.flag_prefix}region, "
                        f"which cuts ONE block opening and never needs a dam "
                        f"at all.")
                dam, dam_src = fabrep["min_mask_dam_mm"], fabrep["name"]
            rep["mask_dam_mm"] = dam
            quads = [inflate_quad(r.quad, bleed) for r in runs]
            openings, merged = merge_openings(quads, dam)
            rep["openings_merged"] = merged
            rep["opening_form"] = "runs"
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


# --- footprint properties (issue #20) ---------------------------------------
#
# 1,638 of the whitepaper part's 1,644 placed characters existed only as
# geometry; the descr named the first six words and everything else needed a
# loupe. The text now travels IN the part, as footprint properties -- the one
# KiCad container whose value survives a round trip through the editor and can
# be selected and copied out of the properties panel.
#
# The serialisation was read back from KiCad 10's own writer, not invented:
# a file carrying this exact token parses in pcbnew 10.0, GetFieldText()
# returns the value -- including a newline stored as the two-character escape
# \n -- and FootprintSave() re-emits the same form:
#
#   (property "Name" "Value" (at 0 0 0) (layer "F.Fab") (hide yes)
#     (effects (font (size 1 1) (thickness 0.15))))
#
# (_property_item substitutes the part's own cap and stroke for KiCad's
# 1 / 0.15 defaults -- see its docstring for why that is not cosmetic.)

PROP_TEXT = "Microtext"          # the author's text, verbatim
PROP_PLACED = "MicrotextPlaced"  # what the board carries: one line per run
PROP_RECIPE = "MicrotextRecipe"  # JSON: everything needed to regenerate


def _prop_escape(s):
    """Escape a property value for a KiCad quoted string.

    Unlike emit_art._sexpr_str this KEEPS newlines, as the \\n escape KiCad
    itself writes -- PROP_PLACED is one line per run and flattening it would
    destroy exactly the structure the property exists to preserve.
    """
    return (str(s).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\n").replace("\t", " "))


def _property_item(name, value, cap_mm, stroke_mm):
    """One footprint property as an ArtFp body item.

    The font mirrors the part's own cap and stroke rather than KiCad's 1 mm /
    0.15 mm default, and not for looks -- the field is hidden and never
    plots. verify_art cross-checks every (thickness ...) token in the file
    against what kicad-cli actually draws, and a hidden 0.15 mm pen the plot
    can never show reads as PEN WIDTH DISAGREES on an otherwise clean part.
    Mirroring keeps the file's set of stroke widths exactly the set the
    board gets.
    """
    return ('\t(property "%s" "%s" (at 0 0 0) (layer "F.Fab") (hide yes) '
            '(effects (font (size %.4f %.4f) (thickness %.4f))))'
            % (_prop_escape(name), _prop_escape(value),
               cap_mm, cap_mm, stroke_mm))


def _recipe(spec: MicrotextSpec, rep: dict) -> dict:
    """The provenance a part needs to be regenerated, or at least re-argued.

    Everything here is a value the emit actually used, read from the spec and
    the report -- not from the command line, which is gone six months later.
    """
    r = {
        "tool": "kicad_art_generator tools/microtext.py",
        "mode": spec.mode,
        "tone": spec.tone,
        "cap_mm": rep["cap_mm"],
        "stroke_ratio": float(spec.stroke_ratio),
        "stroke_mm": rep["stroke_mm"],
        "tracking_em": float(spec.tracking_em),
        "mask_bleed_mm": float(spec.mask_bleed_mm),
        "fab": rep["fab"]["key"] if rep.get("fab") else None,
        "floor_mm": rep["floor_mm"],
        "text_file": spec.source_path,
        "text_chars": len(spec.text),
    }
    if spec.mode == "shape":
        r.update({
            "shape": spec.shape.source,
            "shape_mm": [spec.shape.width_mm, spec.shape.height_mm],
            "shape_origin_mm": [float(v) for v in spec.shape.origin],
            "shape_raster_px": [int(v) for v in spec.shape.grid.shape],
            "shape_whole_band": bool(spec.shape_whole_band),
            "hyphenate": bool(spec.hyphenate),
            "hyphen_min": int(spec.hyphen_min),
            "row_gap_mm": rep.get("row_gap_mm"),
            # BOTH forms of every word this tool hyphenated: what the author
            # wrote ("word") and what the board carries ("as_set"). Only the
            # latter matches the geometry, and recovery needs the count.
            "inserted_hyphens": rep.get("inserted_hyphens", []),
        })
    else:
        r.update({"at": [float(v) for v in spec.at],
                  "angle_deg": float(spec.angle_deg),
                  "separator": spec.separator})
        if spec.region is not None:
            r["region"] = [float(v) for v in spec.region]
        if spec.path is not None:
            r["path"] = [[float(x), float(y)] for x, y in spec.path]
    return r


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

    # The text, IN the part (issue #20). The author's body verbatim, the body
    # as placed (one line per run -- the only form that matches the geometry
    # once a hyphen was inserted or a span-end space consumed), and the recipe
    # to regenerate it. A second microtext block on the same footprint gets
    # numbered names; KiCad treats duplicate property names as one field.
    n_prev = sum(1 for it in fp.items
                 if re.match(rf'\s*\(property "{PROP_TEXT}\d*" ', it))
    sfx = "" if n_prev == 0 else str(n_prev + 1)
    props = [(PROP_TEXT + sfx, spec.text),
             (PROP_PLACED + sfx, "\n".join(r.text for r in runs)),
             (PROP_RECIPE + sfx, json.dumps(_recipe(spec, rep),
                                            sort_keys=True))]
    for off, (nm, val) in enumerate(props):
        fp.items.insert(off, _property_item(nm, val,
                                            rep["cap_mm"], rep["stroke_mm"]))
    rep["properties"] = [nm for nm, _ in props]

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
      + (f", mask opening on {'+'.join(rep['mask_layers'])}"
         if rep["mask_layers"] else ", no mask opening") + "\n")
    w(f"  floor   : {rep['floor_mm']:.3f} mm ({rep['floor_class']}) "
      f"[{rep['floor_note']}]\n")
    w(f"  mode    : {rep['mode']}  {rep['runs']} run(s), {rep['glyphs']} glyph(s), "
      f"{rep['openings']} opening(s)\n")

    # THE VERDICT FIRST. It was decided in check(), before a glyph was placed,
    # and it is printed before the fab arithmetic for the same reason: it is
    # what the caller came to find out, and burying it under sixty lines of
    # clearances is how "M/N spans filled" got read as a pass for a run that
    # dropped a third of its text.
    c = rep.get("capacity")
    if c:
        vb = {"fits": "FITS", "underfill": "*** UNDERFILL ***",
              "overfill": "*** OVERFILL ***"}.get(c.get("verdict"), "?")
        w(f"\n  capacity: {vb}   this art holds {c['chars']} characters of "
          f"this prose at a {c['cap_mm']:.4f} mm cap; "
          f"{c['text_chars']} were supplied\n")
        if c["verdict"] == "overfill":
            w(f"            {c['excess_chars']} characters "
              f"({c['excess_words']} words) DO NOT FIT -- cut exactly that "
              f"many, or resize; see the fill verdict below\n")
        elif c["verdict"] == "underfill":
            w(f"            {c['spare_chars']} characters of unused capacity"
              + (f"; {c['fill_chars']} characters of this prose, ending where "
                 f"a word ends, leaves no band blank" if
                 c.get("fill_chars") is not None
                 else "; NO length of this prose fills every band -- the art "
                      "wants a different size or cap") + "\n")
        else:
            w(f"            {c['spare_chars']} characters of slack"
              + (f"; full anywhere from {c['fill_chars']} to {c['chars']}"
                 if c.get("fill_chars") is not None else "") + "\n")
        w(f"            KNOWN BEFORE THE FLOW RAN, and exact for this prose: "
          f"capacity is measured by flowing this\n            body repeated "
          f"until the art overflowed, and the flow is causal, so the consumed "
          f"prefix is\n            the longest text of this prose the art "
          f"takes. Another body of the same length packs\n            "
          f"differently -- capacity is a property of the art AND the word "
          f"lengths.\n")

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
        if rep.get("opening_form") == "silhouette":
            w(f"  opening : the ART SILHOUETTE -- {rep['openings']} "
              f"opening(s), {rep['opening_vertices']} vertices, "
              f"{rep['opening_holes']} counter(s) kept masked, "
              f"{rep.get('mask_bleed_mm', DEFAULT_MASK_BLEED_MM):.3f} mm "
              f"clear of the letterforms (mask registration is "
              f"+/-{MASK_REGISTRATION_MM} mm)\n")
            if rep.get("mask_corridor_mm") is not None:
                w(f"            narrowest mask web between opening lobes "
                  f"{rep['mask_corridor_mm']:.3f} mm, above the "
                  f"{rep['mask_dam_mm']:.2f} mm dam\n")
        else:
            w(f"  opening : {rep['openings']} block opening(s), "
              f"{rep.get('mask_bleed_mm', DEFAULT_MASK_BLEED_MM):.3f} mm "
              f"clear of the letterforms on every side (mask registration "
              f"is +/-{MASK_REGISTRATION_MM} mm) -- over the block, never "
              f"per glyph\n")
    if rep["mode"] == "shape":
        w(f"  shape   : {rep['shape_source']} via {rep['shape_raster_tool']}, "
          f"{rep['shape_mm'][0]:.3f} x {rep['shape_mm'][1]:.3f} mm, "
          f"{rep['shape_area_mm2']:.2f} mm2 of fillable area\n")
        w(f"  rows    : {rep['rows']} band(s) across the shape, "
          f"{rep['rows_with_text']} carrying text; pitch "
          f"{rep['row_pitch_mm']:.4f} mm = {rep['row_ink_mm']:.4f} mm ink + "
          f"{rep['row_gap_mm']:.4f} mm gap\n")
        f = rep.get("fill") or {}
        ig = rep.get("integrity") or {}
        if ig:
            w(f"  text    : {ig['source_chars']} source characters walked back "
              f"off the board in reading order -- "
              f"{'INTACT' if ig['ok'] else 'MISMATCH: ' + ig['reason']}, "
              f"{ig['dropped_spaces']} inter-word space(s) consumed at span "
              f"ends,\n            {ig['inserted_found']} hyphen(s) inserted "
              f"(declared {ig['inserted_declared']}), "
              f"{rep.get('soft_breaks', 0)} break(s) taken at hyphens the "
              f"author already wrote -- those alter nothing"
              + (f",\n            {ig['truncated']} source character(s) never "
                 f"reached the board -- see the fill verdict"
                 if ig.get("truncated") else "") + "\n")
        w(f"  spans   : {rep['spans_filled']}/{rep['spans_total']} mask spans "
          f"filled, {rep['spans_empty']} too narrow for the next word, "
          f"{rep.get('spans_abandoned', 0)} reached after the text ran out\n")
        w(f"  flowed  : {rep['words_placed']}/{rep['words_total']} words, "
          f"{rep['chars_placed']} of {rep['chars_total']} characters "
          f"({rep['chars_placed'] / max(rep['chars_total'], 1):.1%}); "
          f"{'hyphenated' if rep['hyphenated'] else 'NOT hyphenated'}\n")
        w(f"            (the difference is the inter-word spaces the flow "
          f"consumed at span ends -- no text\n            was dropped, and the "
          f"fill verdict below is what says so rather than this "
          f"percentage)\n")
        rc = f.get("row_chars")
        if rc:
            w(f"  per row : {rc['min']} to {rc['max']} characters, mean "
              f"{rc['mean']:.1f}, stdev {rc['stdev']:.2f} "
              f"(stdev/mean {rc['cv']:.2f}) over {rc['n']} row(s) with text\n")
            w(f"            Characters AS FLOWED, inter-word spaces included; "
              f"count the glyphs in the\n            emitted footprint instead "
              f"and every number here comes out lower.\n")
            w(f"            The short rows ARE the silhouette; the spread is "
              f"how strongly the shape\n            pinches. A row far under "
              f"the mean is a waist, not a fault.\n")
        # THE VERDICT, on its own line, in the same place every run.
        v = f.get("verdict")
        if v == "fits":
            w(f"  fill    : FITS -- {f['bands_with_text']}/{f['bands']} row "
              f"bands carry text and no band was left blank for want of words"
              + (f"; {f['bands_empty'] - f['bands_underfilled']} band(s) are "
                 f"blank because every span in them is too narrow for a word"
                 if f.get("bands_empty") else "") + "\n")
        elif v == "underfill":
            w(f"  fill    : *** UNDERFILL *** {f['bands_underfilled']} of "
              f"{f['bands']} row bands blank for want of words; "
              f"{f['width_abandoned_usable_mm']:.2f} mm of usable span width "
              f"got nothing\n")
            if f.get("need_chars"):
                w(f"            text length must be at least about "
                  f"{f['need_chars']} characters (about "
                  f"{f['shortfall_chars']} short) to reproduce this image at "
                  f"this cap height\n")
            if f.get("remedy_cap_mm") and f.get("remedy_cap_verified"):
                w(f"            cap remedy: lower the resolution to a "
                  f"{f['remedy_cap_mm']:.4f} mm cap (measured, not modelled) "
                  f"-- PREFERRED, it moves away from the floor\n")
            if f.get("remedy_art_mm") and f.get("remedy_art_verified"):
                w(f"            art remedy: shrink the art to "
                  f"{f['remedy_art_wh_mm'][0]:.2f} x "
                  f"{f['remedy_art_wh_mm'][1]:.2f} mm "
                  f"({f['remedy_art_scale']:.3f}x), measured\n")
            w("            text remedy: provide more text -- nothing is lost "
              "either way, the blank is simply visible\n")
        elif v == "overfill":
            w(f"  fill    : *** OVERFILL *** {f['surplus_chars']} characters "
              f"did not fit and were TRUNCATED ON PURPOSE "
              f"(--{rep.get('flag_prefix', '')}shape-allow-truncation)\n")
            if f.get("remedy_art_mm") and f.get("remedy_art_verified"):
                w(f"            art remedy: grow the art to "
                  f"{f['remedy_art_wh_mm'][0]:.2f} x "
                  f"{f['remedy_art_wh_mm'][1]:.2f} mm "
                  f"({f['remedy_art_scale']:.3f}x), measured -- PREFERRED, it "
                  f"neither approaches the floor nor deletes a word\n")
            if f.get("remedy_cap_mm") and f.get("remedy_cap_verified"):
                w(f"            cap remedy: raise the resolution to a "
                  f"{f['remedy_cap_mm']:.4f} mm cap (measured)\n")
            w(f"            text remedy: cut exactly {f['surplus_chars']} "
              f"characters from the end of the body\n")
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
                   help="INSERT a hyphen to break a word that fits no span "
                        "whole. Off by default, and it stays off: this breaks "
                        "on WIDTH, not on syllables, so it will set 'Internet' "
                        "as 'Int-' + 'ernet', which is not a hyphenation any "
                        "reader would accept -- it is a misspelling in two "
                        "pieces. Breaking at hyphens the author ALREADY wrote "
                        "is not this flag and never was: that happens always, "
                        "it needs no permission because it inserts nothing, "
                        "and on the whitepaper prose it is worth most of what "
                        "this flag used to be credited with")
    g.add_argument(f"--{prefix}shape-hyphen-min", dest=f"{d}hyphen_min",
                   type=int, default=3, metavar="N",
                   help="letters that must remain on each side of an INSERTED "
                        "hyphen (default 3). It does not apply to a hyphen the "
                        "author wrote: nothing is being inserted there and no "
                        "word is being divided, which is why 'peer-to-peer' "
                        "breaks after 'to-' even though 'to' is two letters")
    g.add_argument(f"--{prefix}shape-allow-truncation",
                   dest=f"{d}allow_truncation", action="store_true",
                   help="let the flow DROP the text that did not fit instead "
                        "of refusing. Off by default: a reader cannot see a "
                        "word that is not on the board, so silent truncation "
                        "is the one failure here nobody would ever catch. With "
                        "this flag the refusal becomes a warning and the "
                        "dropped characters are recorded in the report")
    g.add_argument(f"--{prefix}shape-require-fill", dest=f"{d}require_fill",
                   action="store_true",
                   help="REFUSE when the text runs out before the shape does "
                        "and whole row bands are left blank. Off by default: "
                        "nothing is lost, and the shortfall is visible to the "
                        "naked eye. Turn it on for an unattended build, where "
                        "a warning on stdout is a warning nobody reads")
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
        allow_truncation=getattr(args, f"{d}allow_truncation", False),
        require_fill=getattr(args, f"{d}require_fill", False),
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


def solve_from_args(a, ap) -> dict:
    """--solve, from the parsed command line. -> the solve dict.

    The shape has to be loaded at SOME size before it can be resized, so when
    the art size is the unknown it is loaded at a nominal 100 mm and the solve
    scales from there -- the silhouette and its aspect ratio are what matter,
    and both are untouched by the scale it was loaded at.
    """
    if not a.shape:
        ap.error("--solve needs --shape: it solves over the art SIZE, and a "
                 "line, a path and a region have no silhouette to resize")
    axis = "width" if a.shape_width is not None else "height"
    known_art = (a.shape_width if axis == "width" else a.shape_height)
    if a.solve_art_mm is not None:
        known_art = a.solve_art_mm
    want = ("art" if known_art is None else
            "cap" if a.height is None else "chars")
    load_kw = ({"width_mm": 100.0} if axis == "width"
               else {"height_mm": 100.0}) if known_art is None else (
        {"width_mm": known_art} if axis == "width" else {"height_mm": known_art})
    shape = load_shape(a.shape, element=a.shape_element,
                       raster_px=a.shape_raster, **load_kw)
    spec = MicrotextSpec(
        text=a.text, cap_mm=(a.height if a.height else 1.0), tone=a.tone,
        shape=shape, hyphenate=a.hyphenate, hyphen_min=a.hyphen_min,
        shape_whole_band=not a.center_band, row_gap_mm=a.row_gap,
        stroke_ratio=a.stroke_ratio, tracking_em=a.tracking,
        floor_mm=a.floor, fab=a.fab, allow_buried=a.allow_buried,
        allow_unmeasured=a.allow_unmeasured, forecast=False)
    return solve(spec, art_mm=(None if want == "art" else known_art),
                 cap_mm=(None if want == "cap" else a.height),
                 chars=a.solve_chars, axis=axis, want=want)


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
    ap.add_argument("--recover", default=None, metavar="KICAD_MOD",
                    help="read the text back OFF an emitted part: walk its "
                         "fp_text glyphs in reading order, print the "
                         "recovered text on stdout, and -- when the part "
                         "stores its Microtext property -- prove the "
                         "geometry against it. Emits nothing; every other "
                         "flag is ignored. Exit 0 intact, 1 diverged.")
    g = ap.add_argument_group(
        "sizing solve",
        "Given any two of {art size, cap height, text length}, return the "
        "third. Emits nothing. The unknown is whichever you leave out: no "
        "--shape-width/--shape-height solves for the art size, no --height "
        "solves for the cap height, and giving all three answers 'does this "
        "fit, and by how much'. --text is always required, because capacity "
        "depends on the word lengths of the prose being set and not only on "
        "the shape.")
    g.add_argument("--solve", action="store_true",
                   help="run the sizing solve and stop")
    g.add_argument("--solve-chars", type=int, default=None, metavar="N",
                   help="solve for N characters instead of len(--text). The "
                        "text is still needed: it is what the packing is "
                        "measured with")
    g.add_argument("--solve-art-mm", type=float, default=None, metavar="MM",
                   help="the art size to solve at, along whichever axis "
                        "--shape-width / --shape-height names (height if "
                        "neither). Same thing as giving that flag; here so a "
                        "caller can sweep sizes without restating the load")
    add_cli_args(ap, prefix="", text_flag="--text")
    a = ap.parse_args(argv)

    if a.recover:
        try:
            rec = recover_from_part(a.recover)
        except MicrotextRefused as e:
            sys.stderr.write(f"\n!! REFUSED: {e}\n\n")
            return 2
        print(rec["text"])
        it = rec["integrity"]
        if it is None:
            sys.stderr.write(
                f"  {rec['glyphs']} glyph(s) in {rec['rows']} row(s) read "
                f"back off {pathlib.Path(a.recover).name}. No Microtext "
                f"property on the part -- the text above is geometry alone, "
                f"unverified. Parts emitted before issue #20 carry none.\n")
            rc = 0
        elif it["ok"]:
            sys.stderr.write(
                f"  INTACT: {it['source_chars']} source characters walked "
                f"back off the part in reading order against the stored "
                f"Microtext property ({it['dropped_spaces']} span-end "
                f"space(s) consumed, {it['inserted_found']} declared "
                f"hyphen(s) found)"
                + (f"; {it['truncated']} character(s) of source were never "
                   f"placed (the part declares its truncation)"
                   if it.get("truncated") else "") + ".\n")
            rc = 0
        else:
            sys.stderr.write(
                f"  DIVERGED: the geometry does not walk back to the stored "
                f"source: {it['reason']}"
                + (f" at source character {it['at']}\n"
                   f"    source: {it.get('source')!r}\n"
                   f"    board : {it.get('board')!r}"
                   if it.get("at") is not None else "") +
                "\n  Either the fp_text was edited since emit, or the "
                "property was. The part no longer carries the text it "
                "claims.\n")
            rc = 1
        if a.report_json:
            pathlib.Path(a.report_json).write_text(
                json.dumps(rec, indent=2), encoding="utf-8")
        return rc

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

    if a.solve:
        try:
            res = solve_from_args(a, ap)
        except MicrotextRefused as e:
            sys.stderr.write(f"\n!! REFUSED: {e}\n\n")
            return 2
        print_solve(res)
        if a.report_json:
            pathlib.Path(a.report_json).write_text(json.dumps(res, indent=2),
                                                   encoding="utf-8")
        return 0 if res.get("ok", True) else 1

    from emit_art import ArtFp
    try:
        spec = spec_from_args(a)
        spec.source_path = a.text_file
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
