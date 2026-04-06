# kicad_art_generator

Linux-first KiCad art footprint generation for Ubuntu and WSL.

This project wraps `svg2mod` with a simpler CLI so you can turn:

- `SVG` artwork directly into KiCad footprints
- `PNG`, `JPG`, `BMP`, and other raster images into KiCad footprints by first converting the raster into a rectangle-based SVG mask
- two-color raster art into a single reusable footprint with yellow mapped to copper and white mapped to silkscreen

The output is a standard `.kicad_mod` footprint that can be dropped into a `.pretty` library and used in KiCad.

## Ubuntu / WSL prerequisites

These are the Ubuntu packages currently expected by the setup flow, including the ones you installed manually in WSL:

```bash
sudo apt-get update
sudo apt-get install -y \
  python3-venv \
  python3-pip \
  python3-dev \
  build-essential \
  pkg-config \
  libcairo2-dev \
  libgirepository1.0-dev \
  gir1.2-rsvg-2.0
```

Additional graphics tools currently available in your WSL environment and useful for preparing source artwork:

```bash
gimp
inkscape
rsvg-convert
```

Then bootstrap the project:

```bash
./scripts/setup_ubuntu.sh
```

## Quick start

Clone into WSL and install:

```bash
git clone https://github.com/recklessnode/kicad_art_generator.git
cd kicad_art_generator
./scripts/setup_ubuntu.sh
```

Generate a footprint from SVG:

```bash
. .venv/bin/activate
kicad-art examples/bitcoin_b.svg --output output/bitcoin_b.kicad_mod --layer F.Cu --width-mm 20
```

Generate a footprint from a bitmap:

```bash
. .venv/bin/activate
kicad-art logo.png --output output/logo.kicad_mod --layer F.SilkS --width-mm 25 --threshold 180
```

Generate your original two-color asset style as one combined footprint at 1 inch, 2 inches, and 4 inches:

```bash
. .venv/bin/activate
kicad-art art.png \
  --mode dual-color \
  --output output/ \
  --footprint-name energy_path \
  --preset-sizes-in 1,2,4 \
  --center
```

Generate a dual-color ENIG-style logo preview, with yellow exposed copper and green silkscreen:

```bash
. .venv/bin/activate
kicad-art "Cholla Energy.png" \
  --mode dual-color \
  --output output/cholla_energy_enig.kicad_mod \
  --footprint-name cholla_energy_enig \
  --width-mm 50 \
  --yellow-rgb 246,226,0 \
  --white-rgb 1,105,56 \
  --yellow-preset copper-exposed \
  --white-preset silkscreen \
  --color-tolerance 32 \
  --alpha-threshold 32 \
  --preview-output output/cholla_energy_enig_preview.png \
  --center
```

Generate the same style at fully custom parametric sizes:

```bash
. .venv/bin/activate
kicad-art art.png \
  --mode dual-color \
  --output output/ \
  --footprint-name energy_path \
  --sizes-in 0.75,1.25,2.5 \
  --center
```

Or in millimeters:

```bash
. .venv/bin/activate
kicad-art art.png \
  --mode dual-color \
  --output output/ \
  --footprint-name energy_path \
  --sizes-mm 18,32,48 \
  --center
```

Generate single-layer black-on-white art, ignore the white background, and emit a preview:

```bash
. .venv/bin/activate
kicad-art cholla_cactus.png \
  --output output/cholla_cactus_silks.kicad_mod \
  --layer F.SilkS \
  --width-mm 50 \
  --foreground-rgb 0,0,0 \
  --background-rgb 255,255,255 \
  --color-tolerance 16 \
  --preview-output output/cholla_cactus_silks_preview.png
```

Export directly into a KiCad footprint library:

```bash
. .venv/bin/activate
kicad-art cholla_cactus.png \
  --output output/cholla_cactus_silks.kicad_mod \
  --layer F.SilkS \
  --width-mm 50 \
  --foreground-rgb 0,0,0 \
  --background-rgb 255,255,255 \
  --pretty-dir ./ArtAssets.pretty
```

## What the tool does

- Uses `svg2mod` for KiCad module generation
- Accepts SVG input directly
- Accepts raster input by converting dark pixels into SVG rectangles before export
- Supports two-color PNG-style assets with yellow sent to `F.Cu` and white sent to `F.SilkS`
- Emits a single combined footprint so the art stays together as one reusable module
- Supports single-layer raster extraction by retaining a chosen foreground color and explicitly ignoring a background color
- Can generate a preview PNG on a green board-like background using the target layer color
- Supports named art presets that emit the PCB layers needed for visible art finishes
- Lets you target a specific KiCad layer such as `F.Cu`, `B.Cu`, `F.SilkS`, or `B.Mask`
- Lets you size the output by width or height in millimeters
- Supports preset width generation in inches for reusable art families

## CLI

```bash
kicad-art INPUT \
  --output OUTPUT \
  --layer F.Cu \
  --width-mm 20 \
  --footprint-name my_logo
```

Main options:

- `--output`: output `.kicad_mod` path
- `--mode dual-color`: split yellow and white into a single combined footprint
- `--layer`: KiCad layer to force the artwork onto
- `--art-preset`: named single-layer art behavior such as `silkscreen`, `copper-exposed`, `copper-covered`, or `substrate-exposed`
- `--width-mm`: target width in millimeters
- `--height-mm`: target height in millimeters
- `--size-in`: target width in inches
- `--preset-sizes-in`: comma-separated inch presets, for example `1,2,4`
- `--sizes-in`: comma-separated custom inch sizes
- `--sizes-mm`: comma-separated custom millimeter sizes
- `--footprint-name`: footprint name inside the KiCad module
- `--value`: footprint value field
- `--threshold`: grayscale threshold for raster inputs
- `--invert`: invert raster thresholding
- `--center`: center the footprint around its bounding box
- `--precision`: line approximation precision passed through to `svg2mod`
- `--yellow-rgb`: RGB triple for copper art in dual-color mode
- `--white-rgb`: RGB triple for silkscreen art in dual-color mode
- `--color-tolerance`: matching tolerance for the dual-color split
- `--copper-layer`: target copper layer, default `F.Cu`
- `--silkscreen-layer`: target silkscreen layer, default `F.SilkS`
- `--yellow-preset`: named preset for the first matched color in dual-color mode
- `--white-preset`: named preset for the second matched color in dual-color mode
- `--foreground-rgb`: retain this color in single-layer raster mode
- `--background-rgb`: explicitly ignore this color in single-layer raster mode
- `--preview-output`: write a PNG preview of the retained artwork in the chosen layer color
- `--pretty-dir`: copy generated `.kicad_mod` files directly into a target `.pretty` library directory

Run `kicad-art --help` to see the full current option set.

## Named Art Presets

- `silkscreen`: places art on `F.SilkS`
- `back-silkscreen`: places art on `B.SilkS`
- `copper-exposed`: places art on copper and opens mask above it, yielding visible ENIG-style gold
- `back-copper-exposed`: the back-side version of exposed copper art
- `copper-covered`: places art on copper only, leaving solder mask over it for a darker green tone
- `back-copper-covered`: the back-side version of covered copper art
- `substrate-exposed`: opens solder mask without copper for a brown substrate tone
- `back-substrate-exposed`: the back-side version of exposed substrate art

## Recommended workflow

1. Prepare a clean two-color source image in GIMP or Inkscape, using one yellow tone and one white tone with transparency elsewhere.
2. Run `kicad-art` in `dual-color` mode with either `--preset-sizes-in 1,2,4` or your own `--sizes-in` / `--sizes-mm` list.
3. Either copy the generated `.kicad_mod` files into a `.pretty` library, or pass `--pretty-dir` so the tool exports them there automatically.
4. Place the resulting art footprint like any other footprint in PCB Editor.

The copper and silkscreen geometry is embedded into the footprint itself, which keeps the art durable and reusable across board designs.

When using copper for visible art, prefer `copper-exposed` so the tool emits both the copper feature and the matching solder-mask opening. If you want a darker green tone instead, use `copper-covered` so the copper remains under solder mask.

For black-on-white line art, a simpler workflow works well:

1. Point `--foreground-rgb` at the ink color you want to keep, such as `0,0,0`.
2. Point `--background-rgb` at the paper color you want to discard, such as `255,255,255`.
3. Use `--preview-output` to quickly confirm the retained geometry before importing the footprint into KiCad.

If an image is very large or detailed, reduce `--max-dimension` to keep the generated footprint smaller and easier to manage.

## Conversation Log

Commit-time history is tracked in [docs/conversation_log.md](/Users/prael/Documents/GitHub/kicad_art_generator/docs/conversation_log.md).

## Development

Run the checks from WSL:

```bash
. .venv/bin/activate
pytest
```

## Notes

- SVG input generally gives the cleanest output and should be preferred when you have vector art available.
- Raster input works best with high-contrast source images.
- Very detailed bitmaps can still create large footprints, so start with simpler art or lower source resolution when possible.
