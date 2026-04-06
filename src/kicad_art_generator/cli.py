from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image


RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
DEFAULT_DPI = 96
PREVIEW_BOARD_GREEN = (24, 110, 62, 255)
PREVIEW_WHITE = (245, 245, 245, 255)
PREVIEW_GOLD = (230, 183, 45, 255)
PREVIEW_DARK_GREEN = (15, 72, 43, 255)
PREVIEW_BROWN = (139, 103, 63, 255)


@dataclass
class ArtworkSize:
    width_px: float
    height_px: float


@dataclass
class ColorMatch:
    name: str
    rgb: tuple[int, int, int]
    layer: str


@dataclass
class RasterSelection:
    rows: list[list[tuple[int, int]]]
    width: int
    height: int


@dataclass(frozen=True)
class ArtPreset:
    name: str
    layers: tuple[str, ...]
    preview_color: tuple[int, int, int, int]


ART_PRESETS = {
    "silkscreen": ArtPreset("silkscreen", ("F.SilkS",), PREVIEW_WHITE),
    "back-silkscreen": ArtPreset("back-silkscreen", ("B.SilkS",), (220, 220, 220, 255)),
    "copper-exposed": ArtPreset("copper-exposed", ("F.Cu", "F.Mask"), PREVIEW_GOLD),
    "back-copper-exposed": ArtPreset("back-copper-exposed", ("B.Cu", "B.Mask"), (190, 145, 35, 255)),
    "copper-covered": ArtPreset("copper-covered", ("F.Cu",), PREVIEW_DARK_GREEN),
    "back-copper-covered": ArtPreset("back-copper-covered", ("B.Cu",), (12, 60, 38, 255)),
    "substrate-exposed": ArtPreset("substrate-exposed", ("F.Mask",), PREVIEW_BROWN),
    "back-substrate-exposed": ArtPreset("back-substrate-exposed", ("B.Mask",), (120, 88, 54, 255)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate KiCad art footprints from SVG or two-color raster artwork."
    )
    parser.add_argument("input", help="Input SVG or raster image path")
    parser.add_argument(
        "--output",
        required=True,
        help="Output .kicad_mod path, or an output directory when using --preset-sizes-in",
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
        help="KiCad layer to force artwork onto in single-layer mode",
    )
    parser.add_argument(
        "--art-preset",
        choices=sorted(ART_PRESETS),
        help="Named PCB art preset for single-layer mode, for example silkscreen or copper-exposed",
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
        "--size-in",
        type=float,
        help="Target output width in inches",
    )
    parser.add_argument(
        "--sizes-in",
        help="Comma-separated custom output widths in inches, for example 0.75,1.5,3",
    )
    parser.add_argument(
        "--preset-sizes-in",
        help="Comma-separated width presets in inches, for example 1,2,4",
    )
    parser.add_argument(
        "--sizes-mm",
        help="Comma-separated custom output widths in millimeters, for example 12.5,25,37.5",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=180,
        help="Threshold for single-layer raster inputs from 0 to 255. Darker pixels are kept by default.",
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
        help="Invert single-layer raster thresholding and keep lighter pixels instead.",
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
    parser.add_argument(
        "--mode",
        choices=["single", "dual-color"],
        default="single",
        help="Use single-layer conversion or split a two-color raster into one combined footprint",
    )
    parser.add_argument(
        "--yellow-rgb",
        default="247,147,26",
        help="RGB triple for the copper art color in dual-color mode",
    )
    parser.add_argument(
        "--white-rgb",
        default="255,255,255",
        help="RGB triple for the silkscreen art color in dual-color mode",
    )
    parser.add_argument(
        "--color-tolerance",
        type=int,
        default=24,
        help="Per-pixel RGB distance tolerance for dual-color matching",
    )
    parser.add_argument(
        "--copper-layer",
        default="F.Cu",
        help="KiCad layer for the yellow art in dual-color mode",
    )
    parser.add_argument(
        "--silkscreen-layer",
        default="F.SilkS",
        help="KiCad layer for the white art in dual-color mode",
    )
    parser.add_argument(
        "--yellow-preset",
        choices=sorted(ART_PRESETS),
        help="Named PCB art preset for the yellow-matched artwork in dual-color mode",
    )
    parser.add_argument(
        "--white-preset",
        choices=sorted(ART_PRESETS),
        help="Named PCB art preset for the second matched artwork in dual-color mode",
    )
    parser.add_argument(
        "--foreground-rgb",
        help="RGB triple to retain in single-layer raster mode, for example 0,0,0",
    )
    parser.add_argument(
        "--background-rgb",
        help="RGB triple to explicitly ignore in single-layer raster mode, for example 255,255,255",
    )
    parser.add_argument(
        "--preview-output",
        help="Optional PNG preview showing the selected art using the target layer color on a green board background",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_target = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    threshold = validate_byte("threshold", args.threshold)
    alpha_threshold = validate_byte("alpha-threshold", args.alpha_threshold)
    validate_byte("color-tolerance", args.color_tolerance)
    preview_output = (
        Path(args.preview_output).expanduser().resolve() if args.preview_output else None
    )
    if preview_output is not None:
        preview_output.parent.mkdir(parents=True, exist_ok=True)

    target_widths_mm = collect_target_widths_mm(args)
    if not target_widths_mm:
        target_widths_mm = [None]

    if uses_directory_output(args):
        output_target.mkdir(parents=True, exist_ok=True)
    else:
        output_target.parent.mkdir(parents=True, exist_ok=True)

    for target_width_mm in target_widths_mm:
        output_path = resolve_output_path(output_target, target_width_mm, args)
        footprint_name = resolve_footprint_name(output_path, target_width_mm, args)

        with tempfile.TemporaryDirectory(prefix="kicad-art-") as tmpdir_name:
            tmpdir = Path(tmpdir_name)

            if args.mode == "dual-color":
                if input_path.suffix.lower() not in RASTER_SUFFIXES:
                    raise SystemExit("Dual-color mode currently expects a raster image input.")
                generate_dual_color_module(
                    input_path=input_path,
                    output_path=output_path,
                    footprint_name=footprint_name,
                    value=args.value,
                    target_width_mm=target_width_mm,
                    height_mm=args.height_mm,
                    args=args,
                    tmpdir=tmpdir,
                    alpha_threshold=alpha_threshold,
                    preview_output=preview_output_for_target(
                        preview_output, output_path, target_width_mm, args
                    ),
                )
            else:
                generate_single_layer_module(
                    input_path=input_path,
                    output_path=output_path,
                    footprint_name=footprint_name,
                    value=args.value,
                    target_width_mm=target_width_mm,
                    height_mm=args.height_mm,
                    preset=resolve_single_art_preset(args),
                    precision=args.precision,
                    dpi=args.dpi,
                    center=args.center,
                    threshold=threshold,
                    alpha_threshold=alpha_threshold,
                    invert=args.invert,
                    max_dimension=max(1, args.max_dimension),
                    verbose=args.verbose,
                    tmpdir=tmpdir,
                    foreground_rgb=parse_optional_rgb_triplet(args.foreground_rgb),
                    background_rgb=parse_optional_rgb_triplet(args.background_rgb),
                    color_tolerance=args.color_tolerance,
                    preview_output=preview_output_for_target(
                        preview_output, output_path, target_width_mm, args
                    ),
                )


def collect_target_widths_mm(args: argparse.Namespace) -> list[float | None]:
    widths_mm: list[float | None] = []

    if args.sizes_mm:
        widths_mm.extend(parse_number_list(args.sizes_mm))
    elif args.sizes_in:
        widths_mm.extend(value * 25.4 for value in parse_number_list(args.sizes_in))
    elif args.preset_sizes_in:
        widths_mm.extend(value * 25.4 for value in parse_number_list(args.preset_sizes_in))
    elif args.size_in is not None:
        widths_mm.append(args.size_in * 25.4)
    elif args.width_mm is not None:
        widths_mm.append(args.width_mm)

    return widths_mm


def resolve_output_path(
    output_target: Path,
    target_width_mm: float | None,
    args: argparse.Namespace,
) -> Path:
    if not uses_directory_output(args):
        return output_target

    width_in = target_width_mm / 25.4 if target_width_mm is not None else 0.0
    width_label = format_size_label(width_in)
    base_name = args.footprint_name or Path(args.input).stem
    return output_target / f"{base_name}_{width_label}.kicad_mod"


def resolve_footprint_name(
    output_path: Path,
    target_width_mm: float | None,
    args: argparse.Namespace,
) -> str:
    if not uses_directory_output(args):
        return args.footprint_name or output_path.stem

    width_in = target_width_mm / 25.4 if target_width_mm is not None else 0.0
    width_label = format_size_label(width_in)
    base_name = args.footprint_name or Path(args.input).stem
    return f"{base_name}_{width_label}"


def uses_directory_output(args: argparse.Namespace) -> bool:
    return bool(args.preset_sizes_in or args.sizes_in or args.sizes_mm)


def get_art_preset(name: str) -> ArtPreset:
    try:
        return ART_PRESETS[name]
    except KeyError as exc:
        raise SystemExit(f"Unknown art preset: {name}") from exc


def resolve_single_art_preset(args: argparse.Namespace) -> ArtPreset:
    if args.art_preset:
        return get_art_preset(args.art_preset)
    return ArtPreset(args.layer, (args.layer,), preview_color_for_layer(args.layer))


def resolve_dual_art_preset(preset_name: str | None, fallback_layer: str) -> ArtPreset:
    if preset_name:
        return get_art_preset(preset_name)
    return ArtPreset(fallback_layer, (fallback_layer,), preview_color_for_layer(fallback_layer))


def preview_color_for_layer(layer: str) -> tuple[int, int, int, int]:
    if layer in ("F.SilkS", "B.SilkS"):
        return PREVIEW_WHITE
    if layer in ("F.Cu", "B.Cu"):
        return PREVIEW_DARK_GREEN
    if layer in ("F.Mask", "B.Mask"):
        return PREVIEW_BROWN
    return PREVIEW_WHITE


def preview_output_for_target(
    preview_output: Path | None,
    output_path: Path,
    target_width_mm: float | None,
    args: argparse.Namespace,
) -> Path | None:
    del target_width_mm
    if preview_output is None:
        return None
    if not uses_directory_output(args):
        return preview_output
    return preview_output.parent / f"{output_path.stem}_preview.png"


def format_size_label(size_in: float) -> str:
    if math.isclose(size_in, round(size_in), abs_tol=1e-6):
        return f"{int(round(size_in))}in"
    return f"{size_in:.2f}in".replace(".", "p")


def parse_number_list(value: str) -> list[float]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise SystemExit("Expected at least one size value.")
    return [float(part) for part in parts]


def validate_byte(name: str, value: int) -> int:
    if not 0 <= value <= 255:
        raise SystemExit(f"{name} must be between 0 and 255")
    return value


def generate_single_layer_module(
    input_path: Path,
    output_path: Path,
    footprint_name: str,
    value: str,
    target_width_mm: float | None,
    height_mm: float | None,
    preset: ArtPreset,
    precision: float,
    dpi: int,
    center: bool,
    threshold: int,
    alpha_threshold: int,
    invert: bool,
    max_dimension: int,
    verbose: bool,
    tmpdir: Path,
    foreground_rgb: tuple[int, int, int] | None,
    background_rgb: tuple[int, int, int] | None,
    color_tolerance: int,
    preview_output: Path | None,
) -> None:
    if input_path.suffix.lower() in RASTER_SUFFIXES:
        svg_input = tmpdir / f"{input_path.stem}.svg"
        selection = raster_to_selection(
            input_path=input_path,
            threshold=threshold,
            alpha_threshold=alpha_threshold,
            invert=invert,
            max_dimension=max_dimension,
            foreground_rgb=foreground_rgb,
            background_rgb=background_rgb,
            color_tolerance=color_tolerance,
        )
        rectangles = merge_row_runs(selection.rows)
        if not rectangles:
            raise SystemExit("No visible art remained after raster processing.")
        write_svg_rects(svg_input, selection.width, selection.height, rectangles)
        if preview_output is not None:
            write_preview_png(
                rows=selection.rows,
                width=selection.width,
                height=selection.height,
                color=preset.preview_color,
                output_path=preview_output,
            )
        size = ArtworkSize(width_px=float(selection.width), height_px=float(selection.height))
    else:
        svg_input = input_path
        size = load_svg_size(svg_input)

    scale_factor = compute_scale_factor(
        size=size,
        dpi=dpi,
        width_mm=target_width_mm,
        height_mm=height_mm,
    )

    temp_sections: list[str] = []
    for layer in preset.layers:
        temp_output = tmpdir / f"{footprint_name}_{layer.replace('.', '_')}.kicad_mod"
        run_svg2mod(
            svg_input=svg_input,
            output_path=temp_output,
            footprint_name=footprint_name,
            value=value,
            layer=layer,
            center=center,
            precision=precision,
            dpi=dpi,
            scale_factor=scale_factor,
            verbose=verbose,
        )
        temp_sections.extend(extract_module_sections(temp_output))

    write_combined_module(output_path, footprint_name, value, temp_sections)


def generate_dual_color_module(
    input_path: Path,
    output_path: Path,
    footprint_name: str,
    value: str,
    target_width_mm: float | None,
    height_mm: float | None,
    args: argparse.Namespace,
    tmpdir: Path,
    alpha_threshold: int,
    preview_output: Path | None,
) -> None:
    yellow_rgb = parse_rgb_triplet(args.yellow_rgb)
    white_rgb = parse_rgb_triplet(args.white_rgb)
    image, size = open_and_scale_image(input_path, max(1, args.max_dimension))

    color_matches = [
        ColorMatch("yellow", yellow_rgb, args.copper_layer),
        ColorMatch("white", white_rgb, args.silkscreen_layer),
    ]

    module_sections: list[str] = []
    preview_layers: list[tuple[list[list[tuple[int, int]]], tuple[int, int, int, int]]] = []
    for match in color_matches:
        preset_name = args.yellow_preset if match.name == "yellow" else args.white_preset
        preset = resolve_dual_art_preset(preset_name, match.layer)
        color_svg = tmpdir / f"{match.name}.svg"
        rows = extract_color_rows(
            image=image,
            target_rgb=match.rgb,
            tolerance=args.color_tolerance,
            alpha_threshold=alpha_threshold,
        )
        rectangles = merge_row_runs(rows)
        if not rectangles:
            continue
        write_svg_rects(color_svg, int(size.width_px), int(size.height_px), rectangles)
        preview_layers.append((rows, preset.preview_color))

        scale_factor = compute_scale_factor(
            size=size,
            dpi=args.dpi,
            width_mm=target_width_mm,
            height_mm=height_mm,
        )
        for layer in preset.layers:
            temp_module = tmpdir / f"{match.name}_{layer.replace('.', '_')}.kicad_mod"
            run_svg2mod(
                svg_input=color_svg,
                output_path=temp_module,
                footprint_name=footprint_name,
                value=value,
                layer=layer,
                center=args.center,
                precision=args.precision,
                dpi=args.dpi,
                scale_factor=scale_factor,
                verbose=args.verbose,
            )
            module_sections.extend(extract_module_sections(temp_module))

    if not module_sections:
        raise SystemExit("No matching yellow or white pixels were found in the input image.")

    if preview_output is not None:
        write_multi_preview_png(
            preview_layers=preview_layers,
            width=int(size.width_px),
            height=int(size.height_px),
            output_path=preview_output,
        )

    write_combined_module(
        output_path=output_path,
        footprint_name=footprint_name,
        value=value,
        sections=module_sections,
    )


def parse_rgb_triplet(value: str) -> tuple[int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise SystemExit(f"RGB value must have exactly 3 comma-separated parts: {value}")
    channels = tuple(validate_byte("rgb channel", int(part)) for part in parts)
    return channels


def parse_optional_rgb_triplet(value: str | None) -> tuple[int, int, int] | None:
    if value is None:
        return None
    return parse_rgb_triplet(value)


def open_and_scale_image(input_path: Path, max_dimension: int) -> tuple[Image.Image, ArtworkSize]:
    image = Image.open(input_path).convert("RGBA")
    width, height = image.size
    longest_edge = max(width, height)
    if longest_edge > max_dimension:
        scale = max_dimension / float(longest_edge)
        image = image.resize(
            (
                max(1, int(round(width * scale))),
                max(1, int(round(height * scale))),
            ),
            Image.Resampling.LANCZOS,
        )
        width, height = image.size
    return image, ArtworkSize(width_px=float(width), height_px=float(height))


def extract_color_rows(
    image: Image.Image,
    target_rgb: tuple[int, int, int],
    tolerance: int,
    alpha_threshold: int,
) -> list[list[tuple[int, int]]]:
    pixels = image.load()
    width, height = image.size
    rows: list[list[tuple[int, int]]] = []

    for y in range(height):
        runs: list[tuple[int, int]] = []
        run_start: int | None = None
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            channel_delta = max(
                abs(red - target_rgb[0]),
                abs(green - target_rgb[1]),
                abs(blue - target_rgb[2]),
            )
            filled = alpha >= alpha_threshold and channel_delta <= tolerance
            if filled and run_start is None:
                run_start = x
            elif not filled and run_start is not None:
                runs.append((run_start, x))
                run_start = None
        if run_start is not None:
            runs.append((run_start, width))
        rows.append(runs)
    return rows


def raster_to_selection(
    input_path: Path,
    threshold: int,
    alpha_threshold: int,
    invert: bool,
    max_dimension: int,
    foreground_rgb: tuple[int, int, int] | None,
    background_rgb: tuple[int, int, int] | None,
    color_tolerance: int,
) -> RasterSelection:
    image, size = open_and_scale_image(input_path, max_dimension)

    pixels = image.load()
    width, height = image.size
    rows: list[list[tuple[int, int]]] = []

    for y in range(height):
        runs: list[tuple[int, int]] = []
        run_start: int | None = None
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            filled = pixel_is_selected(
                red=red,
                green=green,
                blue=blue,
                alpha=alpha,
                alpha_threshold=alpha_threshold,
                threshold=threshold,
                invert=invert,
                foreground_rgb=foreground_rgb,
                background_rgb=background_rgb,
                color_tolerance=color_tolerance,
            )
            if filled and run_start is None:
                run_start = x
            elif not filled and run_start is not None:
                runs.append((run_start, x))
                run_start = None
        if run_start is not None:
            runs.append((run_start, width))
        rows.append(runs)

    return RasterSelection(rows=rows, width=int(size.width_px), height=int(size.height_px))


def write_svg_rects(
    output_svg: Path,
    width: int,
    height: int,
    rectangles: list[tuple[int, int, int, int]],
) -> None:
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


def pixel_is_selected(
    red: int,
    green: int,
    blue: int,
    alpha: int,
    alpha_threshold: int,
    threshold: int,
    invert: bool,
    foreground_rgb: tuple[int, int, int] | None,
    background_rgb: tuple[int, int, int] | None,
    color_tolerance: int,
) -> bool:
    if alpha < alpha_threshold:
        return False

    pixel_rgb = (red, green, blue)
    if background_rgb is not None and color_distance_max(pixel_rgb, background_rgb) <= color_tolerance:
        return False

    if foreground_rgb is not None:
        return color_distance_max(pixel_rgb, foreground_rgb) <= color_tolerance

    luminance = int(round(0.299 * red + 0.587 * green + 0.114 * blue))
    return luminance > threshold if invert else luminance <= threshold


def color_distance_max(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> int:
    return max(abs(rgb_a[0] - rgb_b[0]), abs(rgb_a[1] - rgb_b[1]), abs(rgb_a[2] - rgb_b[2]))


def write_preview_png(
    rows: list[list[tuple[int, int]]],
    width: int,
    height: int,
    color: tuple[int, int, int, int],
    output_path: Path,
) -> None:
    preview = Image.new("RGBA", (width, height), PREVIEW_BOARD_GREEN)
    pixels = preview.load()

    for y, runs in enumerate(rows):
        for x0, x1 in runs:
            for x in range(x0, x1):
                pixels[x, y] = color

    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path, format="PNG")


def write_multi_preview_png(
    preview_layers: list[tuple[list[list[tuple[int, int]]], tuple[int, int, int, int]]],
    width: int,
    height: int,
    output_path: Path,
) -> None:
    preview = Image.new("RGBA", (width, height), PREVIEW_BOARD_GREEN)
    pixels = preview.load()

    for rows, color in preview_layers:
        for y, runs in enumerate(rows):
            for x0, x1 in runs:
                for x in range(x0, x1):
                    pixels[x, y] = color

    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path, format="PNG")


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
    dpi: int,
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
        str(dpi),
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


def normalize_module_file(output_path: Path, footprint_name: str, value: str) -> None:
    sections = extract_module_sections(output_path)
    write_combined_module(output_path, footprint_name, value, sections)


def extract_module_sections(module_path: Path) -> list[str]:
    text = module_path.read_text(encoding="utf-8")
    sections: list[str] = []
    for token in ("(fp_poly", "(pad "):
        start_index = 0
        while True:
            index = text.find(token, start_index)
            if index == -1:
                break
            sections.append(extract_balanced_block(text, index))
            start_index = index + 1
    return sections


def extract_balanced_block(text: str, start_index: int) -> str:
    depth = 0
    in_string = False
    escaped = False

    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]

    raise SystemExit("Failed to parse generated KiCad module content.")


def write_combined_module(
    output_path: Path,
    footprint_name: str,
    value: str,
    sections: list[str],
) -> None:
    normalized_sections = [indent_kicad_block(section, 2) for section in sections]
    module_text = "\n".join(
        [
            f'(module {footprint_name} (layer F.Cu) (tedit {format_tedit()})',
            "  (attr board_only exclude_from_pos_files exclude_from_bom)",
            f'  (descr "Generated by kicad_art_generator as reusable board art")',
            "  (tags kicad_art_generator)",
            f"  {make_fp_text('reference', footprint_name, -2.0)}",
            f"  {make_fp_text('value', value, 2.0)}",
            *normalized_sections,
            ")",
            "",
        ]
    )
    output_path.write_text(module_text, encoding="utf-8")


def format_tedit() -> str:
    return uuid.uuid4().hex[:8].upper()


def make_fp_text(kind: str, text: str, y_pos: float) -> str:
    return (
        f"(fp_text {kind} {text} (at 0 {y_pos}) (layer F.SilkS) hide "
        f"(effects (font (size 1.524 1.524) (thickness 0.3048))))"
    )


def indent_kicad_block(block: str, spaces: int) -> str:
    indent = " " * spaces
    return "\n".join(f"{indent}{line}" if line else line for line in block.splitlines())


if __name__ == "__main__":
    main()
