from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
DEFAULT_DPI = 96


@dataclass
class ArtworkSize:
    width_px: float
    height_px: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate KiCad art footprints from SVG or raster artwork."
    )
    parser.add_argument("input", help="Input SVG or raster image path")
    parser.add_argument(
        "--output",
        required=True,
        help="Output .kicad_mod path",
    )
    parser.add_argument(
        "--footprint-name",
        help="Footprint name inside the KiCad module. Defaults to the output stem.",
    )
    parser.add_argument(
        "--value",
        default="LOGO",
        help="KiCad value field for the footprint",
    )
    parser.add_argument(
        "--layer",
        default="F.SilkS",
        help="KiCad layer to force the artwork onto, for example F.Cu or F.SilkS",
    )
    parser.add_argument(
        "--width-mm",
        type=float,
        help="Target output width in millimeters",
    )
    parser.add_argument(
        "--height-mm",
        type=float,
        help="Target output height in millimeters",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=180,
        help="Threshold for raster inputs from 0 to 255. Darker pixels are kept by default.",
    )
    parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=1,
        help="Minimum alpha value for raster pixels to be considered visible.",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Invert raster thresholding and keep lighter pixels instead.",
    )
    parser.add_argument(
        "--max-dimension",
        type=int,
        default=512,
        help="Maximum raster dimension before downscaling for footprint generation.",
    )
    parser.add_argument(
        "--center",
        action="store_true",
        help="Center the footprint around its bounding box.",
    )
    parser.add_argument(
        "--precision",
        type=float,
        default=5.0,
        help="Curve approximation precision passed to svg2mod.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help="DPI used by svg2mod for SVG pixel units.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the generated svg2mod command before execution.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    footprint_name = args.footprint_name or output_path.stem

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    threshold = validate_byte("threshold", args.threshold)
    alpha_threshold = validate_byte("alpha-threshold", args.alpha_threshold)

    with tempfile.TemporaryDirectory(prefix="kicad-art-") as tmpdir_name:
        tmpdir = Path(tmpdir_name)

        if input_path.suffix.lower() in RASTER_SUFFIXES:
            svg_input = tmpdir / f"{input_path.stem}.svg"
            size = raster_to_svg(
                input_path=input_path,
                output_svg=svg_input,
                threshold=threshold,
                alpha_threshold=alpha_threshold,
                invert=args.invert,
                max_dimension=max(1, args.max_dimension),
            )
        else:
            svg_input = input_path
            size = load_svg_size(svg_input)

        scale_factor = compute_scale_factor(
            size=size,
            dpi=args.dpi,
            width_mm=args.width_mm,
            height_mm=args.height_mm,
        )

        run_svg2mod(
            svg_input=svg_input,
            output_path=output_path,
            footprint_name=footprint_name,
            value=args.value,
            layer=args.layer,
            center=args.center,
            precision=args.precision,
            dpi=args.dpi,
            scale_factor=scale_factor,
            verbose=args.verbose,
        )


def validate_byte(name: str, value: int) -> int:
    if not 0 <= value <= 255:
        raise SystemExit(f"{name} must be between 0 and 255")
    return value


def raster_to_svg(
    input_path: Path,
    output_svg: Path,
    threshold: int,
    alpha_threshold: int,
    invert: bool,
    max_dimension: int,
) -> ArtworkSize:
    image = Image.open(input_path).convert("RGBA")

    width, height = image.size
    longest_edge = max(width, height)
    if longest_edge > max_dimension:
        scale = max_dimension / float(longest_edge)
        new_size = (
            max(1, int(round(width * scale))),
            max(1, int(round(height * scale))),
        )
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        width, height = image.size

    pixels = image.load()
    rows: list[list[tuple[int, int]]] = []

    for y in range(height):
        runs: list[tuple[int, int]] = []
        run_start: int | None = None
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            luminance = int(round(0.299 * red + 0.587 * green + 0.114 * blue))
            filled = alpha >= alpha_threshold and (
                luminance > threshold if invert else luminance <= threshold
            )
            if filled and run_start is None:
                run_start = x
            elif not filled and run_start is not None:
                runs.append((run_start, x))
                run_start = None
        if run_start is not None:
            runs.append((run_start, width))
        rows.append(runs)

    rectangles = merge_row_runs(rows)
    if not rectangles:
        raise SystemExit("No visible art remained after raster thresholding.")

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '  <g fill="#000000" stroke="none">',
    ]
    for x, y, rect_width, rect_height in rectangles:
        svg_lines.append(
            f'    <rect x="{x}" y="{y}" width="{rect_width}" height="{rect_height}" />'
        )
    svg_lines.extend(["  </g>", "</svg>"])
    output_svg.write_text("\n".join(svg_lines) + "\n", encoding="utf-8")

    return ArtworkSize(width_px=float(width), height_px=float(height))


def merge_row_runs(rows: Iterable[list[tuple[int, int]]]) -> list[tuple[int, int, int, int]]:
    active: dict[tuple[int, int], list[int]] = {}
    rectangles: list[tuple[int, int, int, int]] = []

    for y, runs in enumerate(rows):
        current = set(runs)

        for run in list(active):
            if run not in current:
                x0, y0, x1, height = active.pop(run)
                rectangles.append((x0, y0, x1 - x0, height))

        for run in runs:
            x0, x1 = run
            if run in active:
                active[run][3] += 1
            else:
                active[run] = [x0, y, x1, 1]

    for x0, y0, x1, height in active.values():
        rectangles.append((x0, y0, x1 - x0, height))

    return rectangles


def load_svg_size(svg_path: Path) -> ArtworkSize:
    root = ET.fromstring(svg_path.read_text(encoding="utf-8"))

    view_box = root.attrib.get("viewBox")
    if view_box:
        _, _, width, height = [float(part) for part in view_box.replace(",", " ").split()]
        return ArtworkSize(width_px=width, height_px=height)

    width_attr = root.attrib.get("width")
    height_attr = root.attrib.get("height")
    if width_attr and height_attr:
        return ArtworkSize(
            width_px=parse_svg_length(width_attr),
            height_px=parse_svg_length(height_attr),
        )

    raise SystemExit(
        "Could not determine SVG dimensions. Add width and height or a viewBox."
    )


def parse_svg_length(value: str) -> float:
    filtered = "".join(ch for ch in value if ch.isdigit() or ch in ".-")
    if not filtered:
        raise SystemExit(f"Could not parse SVG dimension: {value}")
    return float(filtered)


def compute_scale_factor(
    size: ArtworkSize,
    dpi: int,
    width_mm: float | None,
    height_mm: float | None,
) -> float:
    base_width_mm = size.width_px * 25.4 / dpi
    base_height_mm = size.height_px * 25.4 / dpi

    factors: list[float] = []
    if width_mm is not None:
        factors.append(width_mm / base_width_mm)
    if height_mm is not None:
        factors.append(height_mm / base_height_mm)

    if not factors:
        return 1.0
    if len(factors) == 1:
        return factors[0]

    if not math.isclose(factors[0], factors[1], rel_tol=0.02, abs_tol=0.02):
        raise SystemExit(
            "Width and height imply different scale factors. Specify only one target dimension or use matching aspect ratio."
        )
    return factors[0]


def run_svg2mod(
    svg_input: Path,
    output_path: Path,
    footprint_name: str,
    value: str,
    layer: str,
    center: bool,
    precision: float,
    dpi: float,
    scale_factor: float,
    verbose: bool,
) -> None:
    command = [
        sys.executable,
        "-m",
        "svg2mod.cli",
        "--input-file",
        str(svg_input),
        "--output-file",
        str(output_path),
        "--format",
        "latest",
        "--module-name",
        footprint_name,
        "--module-value",
        value,
        "--force-layer",
        layer,
        "--dpi",
        str(int(dpi)),
        "--factor",
        str(scale_factor),
        "--precision",
        str(precision),
    ]

    if center:
        command.append("--center")

    if verbose:
        print("Running:", " ".join(command))

    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
