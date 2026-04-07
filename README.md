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

Analyze an image first and get a suggested mapping:

```bash
. .venv/bin/activate
kicad-art "Cholla Energy.png" --mode analyze
```

Analyze a multi-color SVG and get a best-effort mapping suggestion:

```bash
. .venv/bin/activate
kicad-art "RecklessSystemsLogoWhiteColor.svg" \
  --mode analyze \
  --svg-render-width 1024
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

If a logo uses close shades of the same color, widen the adjacent-shade match so text and outlines are retained:

```bash
. .venv/bin/activate
kicad-art "Cholla Energy.png" \
  --mode dual-color \
  --output output/cholla_energy_enig_v2.kicad_mod \
  --footprint-name cholla_energy_enig_v2 \
  --width-mm 50 \
  --yellow-rgb 246,226,0 \
  --white-rgb 1,105,56 \
  --yellow-preset copper-exposed \
  --white-preset silkscreen \
  --color-tolerance 24 \
  --adjacent-color-tolerance 64 \
  --adjacent-shade-limit 16 \
  --alpha-threshold 32 \
  --preview-output output/cholla_energy_enig_v2_preview.png \
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

Create a fuller KiCad library bundle that can be imported into a project wholesale:

```bash
. .venv/bin/activate
kicad-art cholla_cactus.png \
  --output output/cholla_cactus_bundle.kicad_mod \
  --footprint-name cholla_cactus_bundle \
  --width-mm 50 \
  --foreground-rgb 0,0,0 \
  --background-rgb 255,255,255 \
  --library-root ./libraries \
  --library-name PromoArt
```

Generate a best-effort multi-color footprint from an SVG by consuming the dominant visible color families:

```bash
. .venv/bin/activate
kicad-art "RecklessSystemsLogoWhiteColor.svg" \
  --mode multi-color \
  --output output/reckless_svg_multicolor.kicad_mod \
  --footprint-name reckless_svg_multicolor \
  --width-mm 60 \
  --multi-color-presets silkscreen,copper-exposed,copper-covered,substrate-exposed \
  --preview-output output/reckless_svg_multicolor_preview.png \
  --svg-render-width 1024 \
  --center
```

If the result looks too grainy, increase detail retention:

```bash
. .venv/bin/activate
kicad-art "RecklessSystemsLogoWhiteColor.svg" \
  --mode multi-color \
  --output output/reckless_svg_multicolor_hq.kicad_mod \
  --footprint-name reckless_svg_multicolor_hq \
  --width-mm 60 \
  --multi-color-presets silkscreen,copper-exposed,copper-covered,substrate-exposed \
  --preview-output output/reckless_svg_multicolor_hq_preview.png \
  --quality high \
  --center
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
- Can analyze an image palette and suggest likely single-layer or dual-color mappings
- Can perform best-effort multi-color mapping, including on SVG input by rasterizing it for palette analysis
- Supports quality presets so you can trade output sharpness against footprint size and generation cost
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
- `--mode analyze`: inspect the image palette and print suggested mappings without generating a footprint
- `--mode multi-color`: map the strongest visible color families to a preset list in order
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
- `--quality`: detail preset for working resolution and curve sharpness
- `--yellow-rgb`: RGB triple for copper art in dual-color mode
- `--white-rgb`: RGB triple for silkscreen art in dual-color mode
- `--color-tolerance`: matching tolerance for the dual-color split
- `--adjacent-color-tolerance`: broader tolerance for absorbing nearby shades around each matched dual-color family
- `--adjacent-shade-limit`: maximum number of nearby palette shades to absorb for each dual-color family
- `--copper-layer`: target copper layer, default `F.Cu`
- `--silkscreen-layer`: target silkscreen layer, default `F.SilkS`
- `--yellow-preset`: named preset for the first matched color in dual-color mode
- `--white-preset`: named preset for the second matched color in dual-color mode
- `--foreground-rgb`: retain this color in single-layer raster mode
- `--background-rgb`: explicitly ignore this color in single-layer raster mode
- `--preview-output`: write a PNG preview of the retained artwork in the chosen layer color
- `--pretty-dir`: copy generated `.kicad_mod` files directly into a target `.pretty` library directory
- `--library-root`: create a KiCad library bundle directory containing a named `.pretty` library and import metadata
- `--library-name`: library name used with `--library-root`
- `--analysis-cluster-tolerance`: merge nearby opaque colors into shared palette clusters during analysis
- `--analysis-min-fraction`: minimum opaque coverage required for a cluster to count as a strong analysis candidate
- `--multi-color-presets`: preset sequence used by multi-color mapping
- `--max-color-count`: maximum number of dominant color families to consume in multi-color mode
- `--svg-render-width`: raster width used when analyzing or multi-color-mapping SVG input

Run `kicad-art --help` to see the full current option set.

## Analysis Mode

Use `--mode analyze` when you want the tool to inspect an image before generation.

It reports:

- image size and transparency
- dominant opaque color clusters
- a suggested background color to ignore when one is obvious
- a suggested `single-layer` or `dual-color` workflow when confidence is high
- a suggested `multi-color` workflow when several dominant visible color families are present

If the palette is too ambiguous, the tool exits with a warning instead of pretending it found a clean mapping.

## Library Bundles

If you use `--library-root` together with `--library-name`, the tool creates:

- `<LibraryName>.pretty/`: the generated footprint library directory
- `fp-lib-table`: a KiCad footprint-library table snippet you can merge into a project
- `library_manifest.md`: a small description of the generated bundle

This makes it easier to move a full art library into KiCad instead of importing footprints one at a time.

## SVG Best-Effort Mapping

For multi-color SVG assets, the tool rasterizes the SVG for color-family analysis, then maps the dominant visible color families to the presets you provide in `--multi-color-presets`.

This is intentionally best-effort:

- it works well when the SVG has a small number of strong visible color families
- tiny anti-alias colors are usually ignored or absorbed
- if the palette is too fragmented, use `--mode analyze` first and then tune the presets or explicit RGB options

## Quality Presets

- `draft`: smallest and fastest, but the most blocky
- `standard`: balanced default
- `high`: better detail retention for logos and denser artwork
- `ultra`: maximum fidelity, but can produce very large footprints

The quality preset adjusts:

- raster working resolution
- SVG render width for color-family extraction
- curve approximation precision

You can still override `--max-dimension`, `--svg-render-width`, or `--precision` directly when needed.

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

For logos that use multiple close shades of green, yellow, or another brand color, tune `--adjacent-color-tolerance` upward so the tool keeps adjacent shades that belong to the same visual family while still dropping unrelated colors.

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
