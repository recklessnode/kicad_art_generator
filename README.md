# kicad_art_generator

Linux-first KiCad art footprint generation for Ubuntu and WSL.

This project wraps `svg2mod` with a simpler CLI so you can turn:

- `SVG` artwork directly into KiCad footprints
- `PNG`, `JPG`, `BMP`, and other raster images into KiCad footprints by first converting the raster into a rectangle-based SVG mask

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

## What the tool does

- Uses `svg2mod` for KiCad module generation
- Accepts SVG input directly
- Accepts raster input by converting dark pixels into SVG rectangles before export
- Lets you target a specific KiCad layer such as `F.Cu`, `B.Cu`, `F.SilkS`, or `B.Mask`
- Lets you size the output by width or height in millimeters

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
- `--layer`: KiCad layer to force the artwork onto
- `--width-mm`: target width in millimeters
- `--height-mm`: target height in millimeters
- `--footprint-name`: footprint name inside the KiCad module
- `--value`: footprint value field
- `--threshold`: grayscale threshold for raster inputs
- `--invert`: invert raster thresholding
- `--center`: center the footprint around its bounding box
- `--precision`: line approximation precision passed through to `svg2mod`

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
