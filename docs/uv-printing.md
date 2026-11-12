# UV printing art onto a finished board

`tools/uv_stencil.py` cuts an image to a KiCad board so that UV-printer ink never lands on exposed pads, silk, holes or the board edge. The output is
one RGBA PNG per board side, at the board's size, ready to print. The reasoning and the open questions are in
[issue 29](https://github.com/recklessnode/kicad_art_generator/issues/29).

## Use

```bash
# 1. KiCad's Python reads the board (it needs pcbnew); the rest runs in this project's environment.
python3 tools/uv_stencil.py BOARD.kicad_pcb --side F --art art.png --out front.png --dpi 600 --gutter 0.20

# a gutter sweep on one print: four vertical bands, left to right as seen, each cut with its own gutter
python3 tools/uv_stencil.py BOARD.kicad_pcb --side F --art art.png --out front_sweep.png --bands 0.05,0.10,0.20,0.40

# keep the geometry and work without KiCad afterwards
python3 tools/uv_stencil.py BOARD.kicad_pcb --side B --save-geometry back.json --art art.png --out back.png
python3 tools/uv_stencil.py --geometry back.json --art art.png --out back_g010.png --gutter 0.10
```

Without `--art` the output is the stencil alone (black where ink may print). `--preview-out` writes the art with the pads (orange), silk (blue),
courtyards (green) and holes (red) outlined over it, for looking at a clearance. `--report-out` writes the parameters, the size in pixels, the
printable share and the checks as JSON.

`uv_stencil.py` finds a Python that can import pcbnew (`--kicad-python`, `KICAD_PYTHON`, KiCad's `bin/python.exe`, or the system Python). To
run the reading step yourself: `"C:/Program Files/KiCad/10.0/bin/python.exe" tools/uv_extract.py BOARD.kicad_pcb --side F --out geometry.json`.

## What ink is kept off

| Keepout | Source in the board | Always, or by `--keepout` |
|---|---|---|
| Mask openings (exposed copper, and any untented via) | the mask layer of that side | always |
| Silk, graphics and text | the silkscreen layer of that side, before the fabricator clips it at the mask openings | always |
| Drilled holes | every pad hole and every via drill | always |
| Outside the board, and an edge margin inside it | Edge.Cuts, inset by `--edge-margin` | always |
| Component courtyards | the filled courtyard of every footprint on that side | `--keepout courtyards` |

Each is grown by the gutter. With `--keepout pads` art may sit where a part will go; with `--keepout courtyards` it stays out from under the parts.

## The gutter

`--gutter` is the clear distance in millimetres between the art and a keepout; the printable region comes no closer than that, and at most 0.5%
farther. `--silk-gutter`, `--hole-gutter` and `--courtyard-gutter` set one kind apart. `--min-feature` (default 0.10 mm) drops printable regions narrower
than that: the slivers left between two close keepouts. Use `--min-feature 0` to keep everything.

The printer's own tolerance is what the gutter has to cover (positioning, ink spread), and it is not known in advance. That is what `--bands` is for:
one print carries a sweep, and the same artwork is compared across it. [E: start somewhere between 0.05 mm (tight) and 0.5 mm (relaxed); the
real values are what the experiment finds.]

## Size, orientation and ink

* The PNG covers the board's bounding box exactly. One pixel is 25.4 / dpi mm (0.042 mm at 600 dpi) and the file carries the DPI, so printed at 100% it
  is board size.
* The image is the face as seen looking at it. The back side is mirrored left to right relative to the top view, so text on its silk reads correctly;
  `--no-mirror-back` turns that off.
* Edges are hard: alpha is 0 or the art's own, never a blend, so a gutter is a gutter.
* Where alpha is 0 the colour is white, not black. If a print workflow ignores alpha, white is the safe colour on a white board.
* `--fit` is `cover` (fill the board and crop), `contain` (the whole image, the rest transparent) or `stretch`; `--anchor` picks which part survives a crop.

## Cleaning the art

* `--white-to-alpha [THRESHOLD]` turns near-white (every channel at or above the threshold, nearly neutral; default 0.85) into transparency. On a white
  board white needs no ink. Do not use it for a coloured board.
* `--remove-checkerboard` clears the grey-and-white "transparency" checkerboard that some exports flatten into a JPEG. A JPEG has no alpha, so the squares
  are ink otherwise. The two greys are read from the four corners and must agree; if they do not, nothing is changed and it says so. It also clears
  any neutral grey of the art itself that falls between the two tones, so look at the result.

## What is checked

After rasterising, the tool checks that every mask opening's representative point is transparent in the PNG, and that a few thousand sample points
inside the tightest keepout are too. The exit status is 1 if either fails. The checks look at pixels, so they would catch a wrong scale, a wrong
mirror or a drawing error; they do not know the printer.

The geometry (stencil, gutters, bands, mirror, raster, fitting, checkerboard) is covered by `tests/test_uv_stencil.py`, which needs no KiCad; run it with
`python3 tests/test_uv_stencil.py` or under pytest. Reading the board with pcbnew is verified by measurement on a real board, as `texture_board.py` is.

## What it does not know

The printer's resolution, how accurately a board can be positioned on it, and whether its software reads alpha as ink density or as a hard mask.
Whether KiCad's mask polygons already include untented vias is not relied on: untented vias are added to the openings explicitly. Registration marks
are not drawn; if the printer needs them they are a further step.
