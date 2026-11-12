#!/usr/bin/env python3
"""UV-printer art: cut an image to a board so ink never lands on pads, silk, holes or the board edge.

    python3 tools/uv_stencil.py BOARD.kicad_pcb --side F --art art.png --out front.png --dpi 600 --gutter 0.20

WHY THIS EXISTS
---------------
A UV flatbed printer (Eufymake E1) can print colour straight onto a finished PCB. Ink on an exposed pad cannot be soldered through, ink
on silk hides it, and ink in a hole or over the edge is a defect. So the art is cut like a stencil first: the print file is a PNG whose alpha
is opaque where the art prints and fully transparent over every pad, over existing silk, in every hole, and outside the board.

WHAT IT DOES
------------
  1. Reads the board once with KiCad's Python (uv_extract.py) -- or takes that JSON with --geometry, which needs no KiCad.
  2. Builds the printable region: the board outline, inset by --edge-margin, minus every keepout grown by the gutter.
  3. Rasterises it at --dpi, so one pixel is a known size, and multiplies the art by it.
  4. Checks the raster against the geometry and writes a report.

THE GUTTER
----------
--gutter is the clear distance, in mm, between the art and the thing it must avoid. It is the variable to experiment with: the printer's real
tolerance is not known in advance, so a tight gutter and a relaxed one are both worth printing. --keepout says what the gutter is measured
from:

  pads         mask openings (the exposed copper), silk and holes. Art may sit under where a part will go.
  courtyards   the above, plus every footprint's courtyard. Art stays out from under the parts.

--silk-gutter, --hole-gutter and --courtyard-gutter override the gutter for one kind of keepout.

--bands takes a list of gutters, e.g. 0.05,0.10,0.20,0.40, and splits the print into that many vertical bands, left to right as seen,
each cut with its own gutter. One print then carries a sweep, and the same artwork is compared across it.

ORIENTATION, SIZE AND INK
-------------------------
* The image is the face as seen looking at it. The back side is therefore mirrored relative to the top view (--no-mirror-back turns that off).
* The image covers the board's bounding box exactly, at --dpi, and carries that DPI in the file: printed at 100%, it is board size.
* Edges are hard (alpha is 0 or the art's own), so a gutter is a gutter. A pixel is 25.4/dpi mm: at 600 dpi, 0.042 mm.
* Where alpha is 0 the colour is white, not black: if a print workflow ignores alpha, white is the safe colour on a white board.
* --white-to-alpha turns near-white into transparency. On a white board white needs no ink. Only use it for a white board.
* --remove-checkerboard clears the grey-and-white "transparency" checkerboard that is sometimes baked into a JPEG: a JPEG cannot carry
  alpha, so the squares are ink otherwise. The two greys are read from the image's corners.

WHAT IT DOES NOT KNOW
---------------------
The printer's resolution, positioning accuracy and how its software reads alpha. Those are what the gutter experiment finds out.
Untented vias are treated as keepouts; whether KiCad's mask polygons already include them is not relied on.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import random
import shutil
import subprocess
import sys
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

HERE = pathlib.Path(__file__).resolve().parent
EMPTY = Polygon()
ANCHORS = {"center": (0.5, 0.5), "left": (0.0, 0.5), "right": (1.0, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0),
           "topleft": (0.0, 0.0), "topright": (1.0, 0.0), "bottomleft": (0.0, 1.0), "bottomright": (1.0, 1.0)}


# ---------------------------------------------------------------------------------------------- geometry in, as shapely
@dataclass(frozen=True)
class Geometry:
    outline: object
    openings: object
    silk: object
    holes: object
    courtyards: object
    meta: dict

    def mapped(self, fn):
        return Geometry(fn(self.outline), fn(self.openings), fn(self.silk), fn(self.holes), fn(self.courtyards), self.meta)

    @property
    def bbox(self):
        return self.outline.bounds


def _polys(items):
    out = []
    for it in items:
        p = Polygon(it["ring"], it.get("holes", [])).buffer(0)
        if not p.is_empty:
            out.append(p)
    return unary_union(out) if out else EMPTY


def load_geometry(d: dict) -> Geometry:
    """Shapely geometry from the JSON uv_extract.py writes (or any dict with the same keys)."""
    if d.get("format") != "uv-geometry/1":
        raise ValueError("not a uv-geometry/1 file")
    holes = [_polys(d["holes"])] + [Point(v["x"], v["y"]).buffer(v["d"] / 2, quad_segs=8) for v in d.get("via_holes", [])]
    meta = dict(board=d.get("board", {}), side=d["side"], counts=d.get("counts", {}))
    return Geometry(_polys(d["outline"]), _polys(d["openings"]), _polys(d["silk"]), unary_union(holes), _polys(d["courtyards"]), meta)


def print_frame(geom: Geometry, side: str, mirror_back: bool = True) -> Geometry:
    """The geometry as seen looking at the face. The back side is mirrored left to right about the board's centre."""
    if side.upper() == "B" and mirror_back:
        x0, _, x1, _ = geom.bbox
        return geom.mapped(lambda g: affinity.scale(g, xfact=-1.0, yfact=1.0, origin=((x0 + x1) / 2, 0.0)) if not g.is_empty else g)
    return geom


# ---------------------------------------------------------------------------------------------- the stencil
@dataclass(frozen=True)
class Params:
    keepout: str = "pads"                  # "pads" or "courtyards"
    gutter: float = 0.20                   # mm clear between the art and a keepout
    silk_gutter: float | None = None
    hole_gutter: float | None = None
    courtyard_gutter: float | None = None
    edge_margin: float = 0.30              # mm kept clear inside the board outline
    min_feature: float = 0.10              # mm: printable regions narrower than this are dropped; 0 keeps everything
    bands: tuple = ()                      # gutters, one vertical band each, left to right as seen

    def check(self):
        if self.keepout not in ("pads", "courtyards"):
            raise ValueError("keepout is 'pads' or 'courtyards'")
        for name in ("gutter", "silk_gutter", "hole_gutter", "courtyard_gutter", "edge_margin", "min_feature"):
            v = getattr(self, name)
            if v is not None and v < 0:
                raise ValueError("%s cannot be negative" % name)
        if any(g < 0 for g in self.bands):
            raise ValueError("a band gutter cannot be negative")


QUAD = 8                                   # segments per quarter circle in a rounded offset


def grow(g, d: float):
    """g grown by d mm, as a polygon that circumscribes the true round offset. A buffer's polygon sits inside the circle it approximates, so a
    plain buffer(d) can leave art a hair closer than d; this one cannot (it errs far, by under 0.5%, never near)."""
    if g.is_empty or d <= 0:
        return g
    return g.buffer(d / math.cos(math.pi / (4 * QUAD)), quad_segs=QUAD)


def keepout_union(geom: Geometry, params: Params, gutter: float | None = None):
    """Everything ink must stay out of, each kind grown by its gutter."""
    g = params.gutter if gutter is None else gutter
    pick = lambda v: g if v is None else v                 # a per-kind gutter wins over the general one, in every band
    parts = [grow(geom.openings, g), grow(geom.silk, pick(params.silk_gutter)), grow(geom.holes, pick(params.hole_gutter))]
    if params.keepout == "courtyards":
        parts.append(grow(geom.courtyards, pick(params.courtyard_gutter)))
    parts = [q for q in parts if not q.is_empty]
    return unary_union(parts) if parts else EMPTY


def _open(region, m: float):
    """Drop printable regions narrower than m mm: a morphological opening."""
    if m <= 0 or region.is_empty:
        return region
    r = region.buffer(-m / 2, quad_segs=QUAD).buffer(m / 2, quad_segs=QUAD)
    return r


def printable_region(geom: Geometry, params: Params, gutter: float | None = None):
    """The part of the board the art may print on, for one gutter value."""
    params.check()
    base = geom.outline.buffer(-params.edge_margin, quad_segs=QUAD) if params.edge_margin else geom.outline
    return _open(base.difference(keepout_union(geom, params, gutter)), params.min_feature)


def banded_region(geom: Geometry, params: Params):
    """(region, bands). With params.bands the print is split into equal vertical bands, each cut with its own gutter."""
    if not params.bands:
        g = params.gutter
        return printable_region(geom, params), [dict(x0=geom.bbox[0], x1=geom.bbox[2], gutter=g)]
    x0, y0, x1, y1 = geom.bbox
    n = len(params.bands)
    parts, bands = [], []
    for k, g in enumerate(params.bands):
        bx0, bx1 = x0 + (x1 - x0) * k / n, x0 + (x1 - x0) * (k + 1) / n
        parts.append(printable_region(geom, params, g).intersection(box(bx0, y0 - 1, bx1, y1 + 1)))
        bands.append(dict(x0=round(bx0, 4), x1=round(bx1, 4), gutter=g))
    return unary_union(parts), bands


# ---------------------------------------------------------------------------------------------- raster
def geoms(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for part in getattr(g, "geoms", []) for p in geoms(part)]


def pixel_size(bbox, dpi: float):
    ppm = dpi / 25.4
    return int(math.ceil((bbox[2] - bbox[0]) * ppm)), int(math.ceil((bbox[3] - bbox[1]) * ppm)), ppm


def rasterise(region, bbox, dpi: float) -> np.ndarray:
    """A (height, width) uint8 mask, 255 where the region is, hard edges. Row 0 is the top of the board (largest y)."""
    w, h, ppm = pixel_size(bbox, dpi)
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    x0, y1 = bbox[0], bbox[3]
    pt = lambda x, y: ((x - x0) * ppm, (y1 - y) * ppm)
    for p in sorted(geoms(region), key=lambda q: -Polygon(q.exterior).area):         # a piece inside another's hole is drawn after it
        d.polygon([pt(x, y) for x, y in p.exterior.coords], fill=255)
        for r in p.interiors:
            d.polygon([pt(x, y) for x, y in r.coords], fill=0)
    return np.asarray(img)


# ---------------------------------------------------------------------------------------------- the art
def load_art(path, size_px=None) -> Image.Image:
    p = pathlib.Path(path)
    if p.suffix.lower() == ".svg":
        try:
            import cairosvg
        except ImportError:
            raise SystemExit("reading an SVG needs cairosvg (pip install cairosvg); or rasterise it first and pass the PNG")
        import io
        kw = dict(output_width=size_px[0]) if size_px else {}
        return Image.open(io.BytesIO(cairosvg.svg2png(url=str(p), **kw))).convert("RGBA")
    return Image.open(p).convert("RGBA")


def fit_art(art: Image.Image, size_px, mode: str = "cover", anchor: str = "center") -> Image.Image:
    """The art scaled to exactly size_px (w, h). cover fills and crops; contain fits whole and leaves the rest transparent; stretch ignores aspect."""
    if mode not in ("cover", "contain", "stretch"):
        raise ValueError("fit is cover, contain or stretch")
    ax, ay = ANCHORS[anchor]
    w, h = size_px
    aw, ah = art.size
    if mode == "stretch":
        return art.resize((w, h), Image.LANCZOS)
    s = max(w / aw, h / ah) if mode == "cover" else min(w / aw, h / ah)
    nw, nh = max(1, round(aw * s)), max(1, round(ah * s))
    scaled = art.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    canvas.paste(scaled, (round((w - nw) * ax), round((h - nh) * ay)))
    return canvas


def white_to_alpha(rgba: Image.Image, threshold: float = 0.85, chroma: float = 0.12) -> Image.Image:
    """Near-white pixels (every channel at or above threshold, nearly neutral) become transparent."""
    a = np.array(rgba, dtype=np.float32) / 255.0
    rgb = a[..., :3]
    white = (rgb.min(axis=-1) >= threshold) & ((rgb.max(axis=-1) - rgb.min(axis=-1)) <= chroma)
    out = np.array(rgba)
    out[..., 3] = np.where(white, 0, out[..., 3])
    return Image.fromarray(out)


def remove_checkerboard(rgba: Image.Image, corner: int = 64, tol: float = 14.0, chroma: float = 12.0):
    """Make a baked-in "transparency" checkerboard transparent. Returns (image, info), info None if there is none.

    Some exports flatten a transparent background to a grey checkerboard, and a JPEG cannot carry alpha, so the squares are pixels. The
    two greys are read from the four corners (each must be near-neutral and show two tones at least 20 levels apart, in at least two
    corners that agree); every near-neutral pixel whose grey lies between those two tones, plus a margin for JPEG noise, is cleared. That
    includes the blurred edge between squares. It also clears any neutral grey of the art itself inside that band, so look at the result."""
    a = np.array(rgba)
    rgb = a[..., :3].astype(np.float32)
    n = min(corner, a.shape[0] // 4, a.shape[1] // 4)
    found = []
    for blk in (rgb[:n, :n], rgb[:n, -n:], rgb[-n:, :n], rgb[-n:, -n:]):
        px = blk.reshape(-1, 3)
        if ((px.max(axis=1) - px.min(axis=1)) <= chroma).mean() < 0.9:
            continue
        lum = px.mean(axis=1)
        lo, hi = float(np.percentile(lum, 20)), float(np.percentile(lum, 80))
        if hi - lo >= 20:
            found.append((lo, hi))
    if len(found) < 2:
        return rgba, None
    lo, hi = min(f[0] for f in found), max(f[1] for f in found)
    if max(f[0] for f in found) - lo > 20 or hi - min(f[1] for f in found) > 20:           # the corners do not agree: not one checkerboard
        return rgba, None
    lum = rgb.mean(axis=-1)
    neutral = (rgb.max(axis=-1) - rgb.min(axis=-1)) <= chroma
    clear = neutral & (lum >= lo - tol) & (lum <= hi + tol)
    a[..., 3] = np.where(clear, 0, a[..., 3])
    return Image.fromarray(a), dict(tones=[round(lo), round(hi)], cleared_share=round(float(clear.mean()), 4))


def compose(art_rgba: Image.Image, mask: np.ndarray) -> Image.Image:
    """The art with its alpha cut by the stencil; transparent pixels are white."""
    a = np.array(art_rgba)
    alpha = np.where(mask > 0, a[..., 3], 0).astype(np.uint8)
    rgb = np.where(alpha[..., None] > 0, a[..., :3], 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]))


# ---------------------------------------------------------------------------------------------- checks
def check_raster(geom: Geometry, params: Params, alpha: np.ndarray, bbox, dpi: float, samples: int = 3000, seed: int = 1) -> dict:
    """The raster must be transparent over every pad, and inside the tightest keepout. Both are looked at in pixels."""
    _, _, ppm = pixel_size(bbox, dpi)
    x0, y1 = bbox[0], bbox[3]
    px = lambda x, y: (int((x - x0) * ppm), int((y1 - y) * ppm))
    h, w = alpha.shape
    pads = [p.representative_point() for p in geoms(geom.openings)]
    bad_pads = sum(1 for p in pads if 0 <= px(p.x, p.y)[0] < w and 0 <= px(p.x, p.y)[1] < h and alpha[px(p.x, p.y)[1], px(p.x, p.y)[0]] > 0)
    tightest = min(params.bands) if params.bands else params.gutter
    inner = keepout_union(geom, params, tightest).buffer(-1.5 / ppm)          # at least 1.5 px inside, clear of rounding at the edge
    rng = random.Random(seed)
    bad, tested = 0, 0
    if not inner.is_empty:
        bx0, by0, bx1, by1 = inner.bounds
        for _ in range(samples * 4):
            if tested >= samples:
                break
            x, y = rng.uniform(bx0, bx1), rng.uniform(by0, by1)
            if inner.contains(Point(x, y)):
                tested += 1
                c, r = px(x, y)
                if 0 <= c < w and 0 <= r < h and alpha[r, c] > 0:
                    bad += 1
    return dict(pad_samples=len(pads), pad_samples_printed=bad_pads, keepout_samples=tested, keepout_samples_printed=bad)


# ---------------------------------------------------------------------------------------------- finding KiCad's Python
def can_import_pcbnew(python) -> bool:
    try:
        return subprocess.run([python, "-c", "import pcbnew"], capture_output=True).returncode == 0
    except OSError:
        return False


def find_kicad_python(arg=None):
    cli = shutil.which("kicad-cli")
    cands = [arg, os.environ.get("KICAD_PYTHON")]
    if cli:
        d = pathlib.Path(cli).resolve().parent
        cands += [str(d / "python.exe"), str(d / "python3"), str(d / "python")]
    cands += [r"C:\Program Files\KiCad\10.0\bin\python.exe", r"C:\Program Files\KiCad\9.0\bin\python.exe", sys.executable, shutil.which("python3")]
    for c in cands:
        if c and can_import_pcbnew(c):
            return c
    raise SystemExit("Cannot find a Python that can `import pcbnew`. On Windows it is KiCad's own bin/python.exe. Pass --kicad-python PATH, "
                     "or extract once with tools/uv_extract.py and pass the JSON with --geometry.")


def read_board(board, side, kicad_python=None, save=None) -> dict:
    import tempfile
    out = pathlib.Path(save) if save else pathlib.Path(tempfile.mkdtemp(prefix="uv-")) / "geometry.json"
    r = subprocess.run([find_kicad_python(kicad_python), str(HERE / "uv_extract.py"), str(board), "--side", side, "--out", str(out)], capture_output=True, text=True)
    if not out.is_file():
        raise SystemExit("Reading the board failed:\n%s%s" % (r.stdout[-600:], r.stderr[-600:]))
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "board read")
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------- preview
def preview(geom: Geometry, region, bbox, px_per_mm: float, art_rgba: Image.Image | None) -> Image.Image:
    """The art over a white board, with the pads, silk, holes and courtyards outlined, for looking at a clearance."""
    w = int(math.ceil((bbox[2] - bbox[0]) * px_per_mm))
    h = int(math.ceil((bbox[3] - bbox[1]) * px_per_mm))
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    if art_rgba is not None:
        img.alpha_composite(art_rgba.resize((w, h), Image.NEAREST))
    d = ImageDraw.Draw(img)
    pt = lambda x, y: ((x - bbox[0]) * px_per_mm, (bbox[3] - y) * px_per_mm)

    def outline(g, colour, width=1):
        for p in geoms(g):
            d.line([pt(x, y) for x, y in p.exterior.coords], fill=colour, width=width)
            for r in p.interiors:
                d.line([pt(x, y) for x, y in r.coords], fill=colour, width=width)
    outline(geom.courtyards, (0, 160, 0, 255))
    outline(geom.silk, (0, 90, 220, 255))
    outline(geom.openings, (220, 140, 0, 255), 2)
    outline(geom.holes, (200, 0, 0, 255), 2)
    outline(geom.outline, (0, 0, 0, 255), 2)
    return img


# ---------------------------------------------------------------------------------------------- the pipeline
def build(geom: Geometry, side: str, params: Params, dpi: float, art=None, fit="cover", anchor="center", white=None, mirror_back=True):
    """(rgba image or None, stencil mask, report). `geom` is in the top-view frame; the result is in the print frame."""
    g = print_frame(geom, side, mirror_back)
    bbox = g.bbox
    region, bands = banded_region(g, params)
    mask = rasterise(region, bbox, dpi)
    w, h, ppm = pixel_size(bbox, dpi)
    img = None
    if art is not None:
        fitted = fit_art(art, (w, h), fit, anchor)
        if white is not None:
            fitted = white_to_alpha(fitted, white)
        img = compose(fitted, mask)
    alpha = np.asarray(img)[..., 3] if img is not None else mask
    board_area = g.outline.area
    report = dict(
        side=side.upper(), mirrored=side.upper() == "B" and mirror_back, dpi=dpi, size_px=[w, h], mm_per_px=round(25.4 / dpi, 5),
        board_mm=[round(bbox[2] - bbox[0], 4), round(bbox[3] - bbox[1], 4)], bands=bands,
        params=dict(keepout=params.keepout, gutter=params.gutter, silk_gutter=params.silk_gutter, hole_gutter=params.hole_gutter,
                    courtyard_gutter=params.courtyard_gutter, edge_margin=params.edge_margin, min_feature=params.min_feature, bands=list(params.bands)),
        board_area_mm2=round(board_area, 2), printable_area_mm2=round(region.area, 2), printable_share=round(region.area / board_area, 4) if board_area else 0.0,
        ink_share=round(float((alpha > 0).mean()), 4), checks=check_raster(g, params, alpha, bbox, dpi),
        board=g.meta.get("board", {}), geometry_counts=g.meta.get("counts", {}))
    return img, mask, report, region, g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", nargs="?", help="the .kicad_pcb (not needed with --geometry)")
    ap.add_argument("--side", choices=("F", "B"), help="F: front, B: back (required with a board)")
    ap.add_argument("--geometry", help="geometry JSON from uv_extract.py, instead of reading a board")
    ap.add_argument("--save-geometry", help="keep the JSON read from the board")
    ap.add_argument("--art", help="the image: PNG, JPEG or SVG; without it only the stencil is written")
    ap.add_argument("--out", required=True, help="the print file: RGBA PNG at the board's size")
    ap.add_argument("--dpi", type=float, default=600.0, help="pixels per inch of the print file (default 600)")
    ap.add_argument("--keepout", choices=("pads", "courtyards"), default="pads", help="what the gutter is measured from (default pads)")
    ap.add_argument("--gutter", type=float, default=0.20, help="mm clear between the art and a keepout (default 0.20)")
    ap.add_argument("--silk-gutter", type=float, help="mm, for silk (default: --gutter)")
    ap.add_argument("--hole-gutter", type=float, help="mm, for holes (default: --gutter)")
    ap.add_argument("--courtyard-gutter", type=float, help="mm, for courtyards (default: --gutter)")
    ap.add_argument("--edge-margin", type=float, default=0.30, help="mm kept clear inside the board outline (default 0.30)")
    ap.add_argument("--min-feature", type=float, default=0.10, help="mm: drop printable regions narrower than this; 0 keeps all (default 0.10)")
    ap.add_argument("--bands", help="comma-separated gutters: one vertical band each, left to right as seen, e.g. 0.05,0.10,0.20,0.40")
    ap.add_argument("--fit", choices=("cover", "contain", "stretch"), default="cover")
    ap.add_argument("--anchor", choices=sorted(ANCHORS), default="center")
    ap.add_argument("--white-to-alpha", type=float, nargs="?", const=0.85, default=None, metavar="THRESHOLD",
                    help="turn near-white into transparency (white board only); threshold 0-1, default 0.85 when given")
    ap.add_argument("--remove-checkerboard", action="store_true",
                    help="clear a baked-in grey transparency checkerboard (read from the image's corners); reports what it found")
    ap.add_argument("--no-mirror-back", action="store_true", help="leave the back side as in the top view")
    ap.add_argument("--stencil-out", help="also write the stencil alone (white = may print)")
    ap.add_argument("--preview-out", help="also write a preview with the keepouts outlined")
    ap.add_argument("--report-out", help="also write the report as JSON")
    ap.add_argument("--kicad-python", help="a Python that can import pcbnew (default: found)")
    a = ap.parse_args(argv)

    if a.geometry:
        raw = json.loads(pathlib.Path(a.geometry).read_text(encoding="utf-8"))
        side = a.side or raw["side"]
    else:
        if not (a.board and a.side):
            ap.error("give a board and --side, or --geometry")
        raw = read_board(a.board, a.side, a.kicad_python, a.save_geometry)
        side = a.side
    geom = load_geometry(raw)
    bands = tuple(float(v) for v in a.bands.split(",")) if a.bands else ()
    params = Params(keepout=a.keepout, gutter=a.gutter, silk_gutter=a.silk_gutter, hole_gutter=a.hole_gutter, courtyard_gutter=a.courtyard_gutter,
                    edge_margin=a.edge_margin, min_feature=a.min_feature, bands=bands)
    size = pixel_size(print_frame(geom, side, not a.no_mirror_back).bbox, a.dpi)
    art = load_art(a.art, size[:2]) if a.art else None
    checker = None
    if art is not None and a.remove_checkerboard:
        art, checker = remove_checkerboard(art)
        print("checkerboard: %s" % ("none found in the corners" if checker is None else "cleared %.1f%% of the image (tones %d and %d)" % (
            100 * checker["cleared_share"], *checker["tones"])))
    img, mask, report, region, g = build(geom, side, params, a.dpi, art, a.fit, a.anchor, a.white_to_alpha, not a.no_mirror_back)

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    (img if img is not None else compose(Image.new("RGBA", (mask.shape[1], mask.shape[0]), (0, 0, 0, 255)), mask)).save(out, dpi=(a.dpi, a.dpi))
    if a.stencil_out:
        Image.fromarray(mask).save(a.stencil_out, dpi=(a.dpi, a.dpi))
    if a.preview_out:
        preview(g, region, g.bbox, 8.0, img).convert("RGB").save(a.preview_out)
    report["art"] = dict(file=pathlib.Path(a.art).name if a.art else None, fit=a.fit, anchor=a.anchor, white_to_alpha=a.white_to_alpha, checkerboard=checker)
    c = report["checks"]
    print("%s: %d x %d px at %g dpi, %.2f x %.2f mm; printable %.1f%% of the board; keepout=%s gutter=%s%s" % (
        out, report["size_px"][0], report["size_px"][1], a.dpi, *report["board_mm"], 100 * report["printable_share"], a.keepout,
        a.gutter if not bands else "bands " + ",".join("%g" % v for v in bands), " (back, mirrored)" if report["mirrored"] else ""))
    print("checks: %d of %d pad centres printed, %d of %d keepout samples printed" % (
        c["pad_samples_printed"], c["pad_samples"], c["keepout_samples_printed"], c["keepout_samples"]))
    if a.report_out:
        pathlib.Path(a.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return 0 if (c["pad_samples_printed"] == 0 and c["keepout_samples_printed"] == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
