#!/usr/bin/env python3
"""Render a footprint as it will LOOK ON A BOARD, not as KiCad's editor draws it.

    python3 tools/board_render.py --lib output/RecklessArt.pretty \
        --fp tux_hatch -o out.png --px 900

WHY THIS EXISTS
---------------
`kicad-cli fp export svg` plots one layer per invocation in the editor's palette:
pale yellow silk, pink mask, red copper, on whatever background the theme
carries. Three colours, none of which is what the board looks like, and the two
tones that carry most of the shading in this palette -- F.Cu under mask, and the
buried layers -- barely register at all. A figure whose whole purpose is to show
a tone difference is useless in those colours.

So the layers are exported as MASKS and recombined through the palette's own
decision tree, from docs/pcb-palette.md:

    mask open?  -> copper? T2 : (buried? T4 : T3)
    mask closed -> copper? T6 : (buried? T7 : T5)

with silk painted last because it sits on top of everything, and the tone
colours taken from w0_spike.TONES so this file cannot drift from the quantiser
the art was assigned with.

WHAT IT CANNOT SHOW, AND WHY THAT IS SAID ON THE FIGURE
-------------------------------------------------------
`fp export svg` emits NOTHING WHATSOEVER for In1.Cu -- measured, and written up
in docs/pcb-palette.md, "Buried tones cannot be previewed from a footprint". The
buried half of the decision tree is therefore unreachable through this path: T4
renders as T3 and T7 renders as T5. That is not a rounding error, it is two of
the seven tones missing, so --annotate stamps it on the image rather than
leaving a reader to assume the render is complete.

READING KICAD'S PLOT
--------------------
Two traps, both hit while building this:

1. In `--black-and-white` mode KiCad does not plot every item black. Silk comes
   out WHITE, because silk IS white. "Ink = dark pixels" therefore finds no silk
   at all, and "ink = any non-white pixel" finds none either. So every fill and
   stroke colour in the exported SVG is forced to black before rasterising, and
   ink is "anything drawn".

2. The plot carries a background <rect> larger than the viewBox. Forcing colours
   to black without removing it paints the whole frame. It is dropped by
   geometry -- a rect that covers the entire viewBox is a background, not art.

The two together are why this is a mask pipeline and not a screenshot.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from w0_spike import TONES                                    # noqa: E402

TONE_RGB = {t[0]: t[2] for t in TONES}

# Layers pulled out of the plot. Order is irrelevant here -- the compositing
# order is fixed in compose() -- but every one of these has to be asked for
# separately because kicad-cli takes one layer set per run.
LAYERS = ("F.Cu", "F.Mask", "B.Mask", "F.SilkS", "Edge.Cuts", "Dwgs.User")

# A window is bare laminate with 1.44 mm of board and no copper in the way, lit
# from behind. It is not a palette tone -- it is what you see THROUGH the board
# -- so it gets a colour of its own rather than being forced into the table.
# Warm because FR4 with no copper transmits amber, which is the observation
# docs/pcb-palette.md makes about it.
WINDOW_RGB = (232, 196, 120)
# Where the router has been. Not a colour on the board: the absence of board.
CUT_RGB = (16, 16, 18)
CUT_EDGE_RGB = (196, 72, 72)
KEEPOUT_RGB = (120, 150, 200)


# Which kicad-cli this module drives. Resolved once, through verify_art's
# picker so the renderer and the acceptance harness cannot end up on different
# binaries -- a distro kicad-cli 7 earlier on PATH cannot parse a
# version-20241229 footprint, and when a PLOT is what silently comes out wrong
# the result is a figure drawn with the wrong stroke metrics rather than an
# error anybody notices.
MIN_MAJOR = 10
_CLI: str | None = None


def set_kicad_cli(explicit: str | None = None, min_major: int = MIN_MAJOR):
    """Resolve, version-gate and remember the kicad-cli to plot with."""
    global _CLI
    import verify_art
    choice = verify_art.find_kicad_cli(explicit)
    if not choice.path:
        raise SystemExit(
            "no kicad-cli found" +
            (" (rejected: " + ", ".join(choice.rejected) + ")"
             if choice.rejected else "") +
            "\n  pass --kicad-cli /path/to/kicad-cli")
    if choice.major < min_major:
        raise SystemExit(
            f"kicad-cli {choice.version} at {choice.path} is below the "
            f"required major version {min_major}.\n"
            f"  KiCad {choice.major} cannot parse a version-20241229 footprint "
            f"and plots with different stroke metrics, so a figure it renders "
            f"is not the artwork. Pass --kicad-cli with a {min_major}.x binary.")
    _CLI = choice.path
    return choice


def _cli() -> str:
    if _CLI is None:
        set_kicad_cli(None)
    return _CLI


def export_layer(lib: pathlib.Path, fp: str, layer: str,
                 tmp: pathlib.Path) -> pathlib.Path | None:
    """kicad-cli fp export svg for ONE layer. -> svg path, or None if empty."""
    import verify_art
    cli = _cli()
    out = tmp / layer.replace(".", "_")
    out.mkdir(parents=True, exist_ok=True)
    r = verify_art.run_cli(cli, [
        "fp", "export", "svg", verify_art.host_path(pathlib.Path(lib), cli),
        "--fp", fp, "--layers", layer, "--black-and-white",
        "-o", verify_art.host_path(out, cli)])
    svg = out / f"{fp}.svg"
    if r.returncode != 0 or not svg.is_file():
        return None
    return svg


_RECT_RE = re.compile(
    r'<rect\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"\s+'
    r'width="([\d.]+)"\s+height="([\d.]+)"[^>]*/?>')
_VIEWBOX_RE = re.compile(r'viewBox="([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+)"')


def _normalise(svg_text: str) -> tuple[str, tuple[float, float, float, float]]:
    """Force every drawn item black and drop the background rect. -> (svg, vbox).

    See the module docstring, "READING KICAD'S PLOT" -- this is trap 1 and trap 2.
    """
    m = _VIEWBOX_RE.search(svg_text)
    if not m:
        raise RuntimeError("exported SVG has no viewBox; cannot align layers")
    vx, vy, vw, vh = (float(g) for g in m.groups())

    def _drop(mo):
        x, y, w, h = (float(g) for g in mo.groups())
        # Covers the whole viewBox -> background. Anything smaller is art.
        if x <= vx + 1e-9 and y <= vy + 1e-9 and \
           x + w >= vx + vw - 1e-9 and y + h >= vy + vh - 1e-9:
            return ""
        return mo.group(0)

    svg_text = _RECT_RE.sub(_drop, svg_text)
    svg_text = re.sub(r'(fill|stroke):#[0-9A-Fa-f]{6}', r'\1:#000000', svg_text)
    svg_text = re.sub(r'(fill|stroke)-opacity:[\d.]+', r'\1-opacity:1', svg_text)
    return svg_text, (vx, vy, vw, vh)


def layer_mask(svg: pathlib.Path, px: int) -> tuple[np.ndarray, tuple]:
    """Normalised layer plot -> boolean ink mask at `px` wide."""
    import cairosvg
    text, vbox = _normalise(svg.read_text(encoding="utf-8", errors="replace"))
    png = cairosvg.svg2png(bytestring=text.encode("utf-8"), output_width=px,
                           background_color="white")
    import io
    im = Image.open(io.BytesIO(png)).convert("L")
    a = np.asarray(im)
    # Anything not left as the white ground was drawn. The 250 rather than 255
    # is antialias slack; a mark whose coverage is under ~2% is not a mark.
    return a < 250, vbox


def enclosed_by(cut: np.ndarray) -> np.ndarray:
    """Which pixels a closed Edge.Cuts loop encloses. -> boolean mask.

    Flood from the frame across everything the cut does not occupy; what the
    flood cannot reach is inside a loop, and a loop in Edge.Cuts means the
    router separates it from the board. This is the same claim emit_art's
    copper-vs-cut audit makes about the waste side, arrived at differently, so
    the figure and the audit can be checked against each other.

    A loop nested INSIDE a routed loop would be called removed along with its
    parent. Correct for a slug (nothing holds it), wrong for a bridge that is
    not drawn -- there is no bridge in any of these figures.
    """
    H, W = cut.shape
    reach = np.zeros_like(cut)
    stack = []
    for x in range(W):
        for y in (0, H - 1):
            if not cut[y, x]:
                stack.append((y, x))
    for y in range(H):
        for x in (0, W - 1):
            if not cut[y, x]:
                stack.append((y, x))
    while stack:
        y, x = stack.pop()
        if reach[y, x] or cut[y, x]:
            continue
        reach[y, x] = True
        if y:
            stack.append((y - 1, x))
        if y + 1 < H:
            stack.append((y + 1, x))
        if x:
            stack.append((y, x - 1))
        if x + 1 < W:
            stack.append((y, x + 1))
    return ~(reach | cut)


def compose(masks: dict, px_per_mm: float, *, show_keepout=True):
    """The palette decision tree, in physical order. -> PIL RGB image."""
    ref = next(m for m in masks.values() if m is not None)
    H, W = ref.shape
    img = np.zeros((H, W, 3), dtype=np.uint8)

    def g(name):
        m = masks.get(name)
        return np.zeros((H, W), dtype=bool) if m is None else m

    f_cu, f_mask, b_mask = g("F.Cu"), g("F.Mask"), g("B.Mask")
    silk, edge, dwgs = g("F.SilkS"), g("Edge.Cuts"), g("Dwgs.User")

    # T5 is not painted, it IS the ground: mask closed, no copper, no buried.
    img[:] = TONE_RGB["T5"]

    # mask closed -> copper? T6 : T5. (buried? T7 -- unreachable, see docstring)
    img[f_cu & ~f_mask] = TONE_RGB["T6"]
    # mask open -> copper? T2 : T3. (buried? T4 -- likewise unreachable)
    img[f_mask & ~f_cu] = TONE_RGB["T3"]
    img[f_mask & f_cu] = TONE_RGB["T2"]

    # T8: both faces open and no copper in the way -- light gets through. Tested
    # after the surface tones because a window is not a surface.
    window = f_mask & b_mask & ~f_cu
    img[window] = WINDOW_RGB

    # Silk sits on top of every one of them. Last, and unconditional.
    img[silk] = TONE_RGB["T1"]

    # T9: the board is gone. After silk, because ink plotted onto a slug goes
    # with the slug -- which is the entire point of the copper-vs-cut audit.
    if edge.any():
        removed = enclosed_by(edge)
        # BLENDED, not painted over. Filling the removed area solid is the
        # literal truth -- there is no board there -- and it produces a figure
        # that hides the very thing the reader has to see, which is WHAT LEAVES
        # with the slug. Marks printed on routed-away laminate are the failure
        # emit_art raises CopperInWaste for, and a figure of that failure has to
        # show the marks. So the art stays visible at 40% and the region reads
        # as gone.
        img[removed] = (0.40 * img[removed].astype(np.float32)
                        + 0.60 * np.array(CUT_RGB, dtype=np.float32)
                        ).astype(np.uint8)
        img[edge] = CUT_EDGE_RGB

    if show_keepout and dwgs.any():
        img[dwgs] = KEEPOUT_RGB
    return Image.fromarray(img)


def render(lib, fp, px=900, keepout=True, crop_mm=None):
    """-> (image, notes). notes says what could not be shown.

    `px` is the width of the PLOT, not of the saved image: with crop_mm the
    plot is rasterised whole at `px` and then a window is cut out of it, so the
    zoom's resolution is set by px and its extent by crop_mm. Rasterising only
    the crop region would re-plot at a different scale and the detail would no
    longer be the same pixels as the overview.
    """
    lib = pathlib.Path(lib)
    notes = []
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        masks, vbox, present = {}, None, []
        for layer in LAYERS:
            svg = export_layer(lib, fp, layer, tmp)
            if svg is None:
                masks[layer] = None
                continue
            m, vb = layer_mask(svg, px)
            vbox = vb if vbox is None else vbox
            if vb != vbox:
                raise RuntimeError(
                    f"{layer} plotted at viewBox {vb}, others at {vbox} -- the "
                    f"layers do not align and the composite would be a lie")
            masks[layer] = m
            if m.any():
                present.append(layer)
    if vbox is None:
        raise RuntimeError(f"no layer of {fp} could be plotted")
    px_per_mm = px / vbox[2]
    print(f"plotted extent: {vbox[2]:.3f} x {vbox[3]:.3f} mm "
          f"at {px_per_mm:.2f} px/mm "
          f"(--crop-mm is measured from this extent's top-left corner)")
    notes.append(f"layers with ink: {', '.join(present) or 'none'}")
    notes.append("In1.Cu/In2.Cu NOT SHOWN: kicad-cli fp export svg emits "
                 "nothing for buried copper, so T4 renders as T3 and T7 as T5")
    img = compose(masks, px_per_mm, show_keepout=keepout)
    if crop_mm is not None:
        x0, y0, x1, y1 = crop_mm
        box = (int(round((x0 - vbox[0]) * px_per_mm)),
               int(round((y0 - vbox[1]) * px_per_mm)),
               int(round((x1 - vbox[0]) * px_per_mm)),
               int(round((y1 - vbox[1]) * px_per_mm)))
        box = (max(0, box[0]), max(0, box[1]),
               min(img.width, box[2]), min(img.height, box[3]))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise RuntimeError(
                f"--crop-mm {crop_mm} lies outside the plotted extent "
                f"x {vbox[0]:.3f}..{vbox[0]+vbox[2]:.3f}, "
                f"y {vbox[1]:.3f}..{vbox[1]+vbox[3]:.3f} mm")
        notes.append(f"plotted at {px_per_mm:.1f} px/mm")
        img = img.crop(box)
    return img, notes


def annotate(img, title, sub, notes):
    """Caption strip under the render. A figure that does not say what it is and
    what it is missing gets quoted as evidence for something it never showed."""
    pad, lh = 14, 17
    lines = [t for t in (sub, *notes) if t]
    strip = pad * 2 + 22 + lh * len(lines)
    out = Image.new("RGB", (img.width, img.height + strip), (247, 246, 243))
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    y = img.height + pad
    d.text((pad, y), title, fill=(18, 18, 20))
    y += 22
    for t in lines:
        d.text((pad, y), t, fill=(70, 70, 76))
        y += lh
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", required=True, help=".pretty directory")
    ap.add_argument("--fp", required=True, help="footprint name in it")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--px", type=int, default=900, help="output width in pixels")
    ap.add_argument("--title", default=None)
    ap.add_argument("--sub", default=None)
    ap.add_argument("--no-annotate", dest="annotate", action="store_false",
                    default=True)
    ap.add_argument("--no-keepout", dest="keepout", action="store_false",
                    default=True)
    ap.add_argument("--kicad-cli", default=None,
                    help=f"path to kicad-cli. Must be {MIN_MAJOR}.x or newer: "
                         f"an older one plots with different stroke metrics "
                         f"and the figure would not be the artwork")
    ap.add_argument("--crop-mm", default=None, metavar="X0,Y0,X1,Y1",
                    help="crop to this window before saving -- for a zoom "
                         "close enough to read microtext. Millimetres from the "
                         "TOP-LEFT OF THE PLOTTED EXTENT, not footprint "
                         "coordinates: kicad-cli plots a footprint into a "
                         "viewBox of its own that starts at 0,0 whatever the "
                         "footprint's origin is. The extent is printed on "
                         "every run so a window can be picked from it")
    a = ap.parse_args(argv)

    choice = set_kicad_cli(a.kicad_cli)
    print(f"kicad-cli: {choice.path}  ({choice.version})")

    crop = None
    if a.crop_mm:
        v = [float(t) for t in a.crop_mm.replace(",", " ").split()]
        if len(v) != 4:
            ap.error("--crop-mm needs X0,Y0,X1,Y1")
        crop = (min(v[0], v[2]), min(v[1], v[3]),
                max(v[0], v[2]), max(v[1], v[3]))

    img, notes = render(a.lib, a.fp, px=a.px, keepout=a.keepout, crop_mm=crop)
    if crop:
        notes.append(f"CROP {crop[0]:g},{crop[1]:g} to {crop[2]:g},{crop[3]:g} mm "
                     f"of the footprint -- a detail, not the whole part")
    if a.annotate:
        img = annotate(img, a.title or a.fp, a.sub, notes)
    out = pathlib.Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"{out}  {img.width}x{img.height}")
    for n in notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
