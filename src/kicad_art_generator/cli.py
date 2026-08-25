from __future__ import annotations

import argparse
import shutil
import math
import re
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
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
PREVIEW_USER = (130, 180, 220, 255)
QUALITY_DEFAULTS = {
    "draft": {"max_dimension": 512, "svg_render_width": 1024, "precision": 5.0},
    "standard": {"max_dimension": 1024, "svg_render_width": 2048, "precision": 3.0},
    "high": {"max_dimension": 2048, "svg_render_width": 4096, "precision": 1.5},
    "ultra": {"max_dimension": 4096, "svg_render_width": 8192, "precision": 1.0},
}


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


@dataclass(frozen=True)
class PaletteCluster:
    rgb: tuple[int, int, int]
    count: int


ART_PRESETS = {
    "silkscreen": ArtPreset("silkscreen", ("F.SilkS",), PREVIEW_WHITE),
    "back-silkscreen": ArtPreset("back-silkscreen", ("B.SilkS",), (220, 220, 220, 255)),
    "copper-exposed": ArtPreset("copper-exposed", ("F.Cu", "F.Mask"), PREVIEW_GOLD),
    "back-copper-exposed": ArtPreset("back-copper-exposed", ("B.Cu", "B.Mask"), (190, 145, 35, 255)),
    "copper-covered": ArtPreset("copper-covered", ("F.Cu",), PREVIEW_DARK_GREEN),
    "back-copper-covered": ArtPreset("back-copper-covered", ("B.Cu",), (12, 60, 38, 255)),
    "substrate-exposed": ArtPreset("substrate-exposed", ("F.Mask",), PREVIEW_BROWN),
    "back-substrate-exposed": ArtPreset("back-substrate-exposed", ("B.Mask",), (120, 88, 54, 255)),
    "user-drawings": ArtPreset("user-drawings", ("Dwgs.User",), PREVIEW_USER),
}


HELP_EXAMPLES = """Examples:
  Analyze an image first:
    kicad-art "logo.png" --mode analyze

  Generate a detailed dual-color ENIG-style logo:
    kicad-art "brand_mark.png" \\
      --mode dual-color \\
      --output output/brand_mark_enig.kicad_mod \\
      --footprint-name brand_mark_enig \\
      --width-mm 50 \\
      --yellow-rgb 246,226,0 \\
      --white-rgb 1,105,56 \\
      --yellow-preset copper-exposed \\
      --white-preset silkscreen \\
      --color-tolerance 24 \\
      --adjacent-color-tolerance 64 \\
      --adjacent-shade-limit 16 \\
      --alpha-threshold 32 \\
      --preview-output output/brand_mark_enig_preview.png \\
      --quality high \\
      --center

  Export directly into a KiCad library bundle:
    kicad-art line_art.png \\
      --output output/line_art_silks.kicad_mod \\
      --footprint-name line_art_silks \\
      --width-mm 50 \\
      --foreground-rgb 0,0,0 \\
      --background-rgb 255,255,255 \\
      --library-root ./libraries \\
      --library-name PromoArt

  Push SVG detail higher when needed:
    kicad-art "logo_color.svg" \\
      --mode multi-color \\
      --output output/logo_color_hq.kicad_mod \\
      --footprint-name logo_color_hq \\
      --width-mm 60 \\
      --multi-color-presets silkscreen,copper-exposed,copper-covered,substrate-exposed \\
      --preview-output output/logo_color_hq_preview.png \\
      --quality high \\
      --center

  Produce a smaller all-vector bitmap result:
    kicad-art "formula.png" \\
      --output output/formula_vectorized_compact.kicad_mod \\
      --footprint-name formula_vectorized_compact \\
      --art-preset silkscreen \\
      --width-mm 90 \\
      --foreground-rgb 0,0,0 \\
      --background-rgb 255,255,255 \\
      --bitmap-processing vectorize-compact \\
      --center
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate KiCad art footprints from SVG or raster artwork.",
        epilog=HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Input SVG or raster image path")
    parser.add_argument(
        "--output",
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
        "--quality",
        choices=list(QUALITY_DEFAULTS),
        default="standard",
        help="Detail preset that tunes working resolution and curve sharpness",
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
        choices=["single", "dual-color", "multi-color", "analyze"],
        default="single",
        help="Use single-layer conversion, split a two-color image into one combined footprint, map multiple dominant colors, or analyze an image palette",
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
        "--adjacent-color-tolerance",
        type=int,
        default=64,
        help="Wider tolerance for absorbing nearby shades around each primary dual-color match",
    )
    parser.add_argument(
        "--adjacent-shade-limit",
        type=int,
        default=16,
        help="Maximum number of extra nearby palette shades to absorb for each dual-color target",
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
        "--bitmap-processing",
        choices=["raster", "vectorize", "vectorize-compact"],
        default="raster",
        help="How to process single-layer bitmap inputs: keep a raster-style mask, vectorize with potrace, or create a smaller compact vectorized output",
    )
    parser.add_argument(
        "--background-rgb",
        help="RGB triple to explicitly ignore in single-layer raster mode, for example 255,255,255",
    )
    parser.add_argument(
        "--preview-output",
        help="Optional PNG preview showing the selected art using the target layer color on a green board background",
    )
    parser.add_argument(
        "--pretty-dir",
        help="Optional target .pretty directory to receive the generated .kicad_mod files",
    )
    parser.add_argument(
        "--library-root",
        help="Optional root directory for a KiCad library bundle that will contain a named .pretty library and import metadata",
    )
    parser.add_argument(
        "--library-name",
        help="Library name to use with --library-root, for example PromoArt",
    )
    parser.add_argument(
        "--analysis-cluster-tolerance",
        type=int,
        default=24,
        help="Color distance used to merge nearby opaque colors into palette clusters during analysis",
    )
    parser.add_argument(
        "--analysis-min-fraction",
        type=float,
        default=0.02,
        help="Minimum opaque coverage fraction for a cluster to be treated as a strong candidate during analysis",
    )
    parser.add_argument(
        "--multi-color-presets",
        default="silkscreen,copper-exposed,copper-covered,substrate-exposed",
        help="Comma-separated preset list used by --mode multi-color, in assignment order",
    )
    parser.add_argument(
        "--max-color-count",
        type=int,
        default=4,
        help="Maximum dominant color families to map in multi-color mode",
    )
    parser.add_argument(
        "--svg-render-width",
        type=int,
        help="Raster render width used when color-analyzing SVG artwork",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    apply_quality_defaults(args)

    input_path = Path(args.input).expanduser().resolve()

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    threshold = validate_byte("threshold", args.threshold)
    alpha_threshold = validate_byte("alpha-threshold", args.alpha_threshold)
    validate_byte("color-tolerance", args.color_tolerance)
    validate_byte("adjacent-color-tolerance", args.adjacent_color_tolerance)

    if not args.output:
        if args.mode != "analyze":
            raise SystemExit("--output is required unless --mode analyze is used.")

    preview_output = (
        Path(args.preview_output).expanduser().resolve() if args.preview_output else None
    )
    pretty_dir = Path(args.pretty_dir).expanduser().resolve() if args.pretty_dir else None
    library_root = Path(args.library_root).expanduser().resolve() if args.library_root else None
    if preview_output is not None:
        preview_output.parent.mkdir(parents=True, exist_ok=True)
    if (library_root is None) != (args.library_name is None):
        raise SystemExit("--library-root and --library-name must be provided together.")
    if library_root is not None:
        pretty_dir = initialize_library_bundle(library_root, args.library_name)
    if pretty_dir is not None:
        ensure_pretty_dir(pretty_dir)

    if args.mode == "analyze":
        with tempfile.TemporaryDirectory(prefix="kicad-art-analyze-") as tmpdir_name:
            analyze_image(
                input_path=input_path,
                alpha_threshold=alpha_threshold,
                cluster_tolerance=args.analysis_cluster_tolerance,
                min_fraction=args.analysis_min_fraction,
                svg_render_width=args.svg_render_width,
                tmpdir=Path(tmpdir_name),
            )
        return

    output_target = Path(args.output).expanduser().resolve()

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
            elif args.mode == "multi-color":
                generate_multi_color_module(
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
                    svg_render_width=args.svg_render_width,
                    verbose=args.verbose,
                    tmpdir=tmpdir,
                    foreground_rgb=parse_optional_rgb_triplet(args.foreground_rgb),
                    background_rgb=parse_optional_rgb_triplet(args.background_rgb),
                    bitmap_processing=args.bitmap_processing,
                    color_tolerance=args.color_tolerance,
                    preview_output=preview_output_for_target(
                        preview_output, output_path, target_width_mm, args
                    ),
                )

        if pretty_dir is not None:
            export_to_pretty_dir(output_path, pretty_dir)


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


def apply_quality_defaults(args: argparse.Namespace) -> None:
    quality = QUALITY_DEFAULTS[args.quality]
    if args.max_dimension is None:
        args.max_dimension = quality["max_dimension"]
    if args.svg_render_width is None:
        args.svg_render_width = quality["svg_render_width"]
    if args.precision is None:
        args.precision = quality["precision"]


def preview_color_for_layer(layer: str) -> tuple[int, int, int, int]:
    if layer in ("F.SilkS", "B.SilkS"):
        return PREVIEW_WHITE
    if layer in ("F.Cu", "B.Cu"):
        return PREVIEW_DARK_GREEN
    if layer in ("F.Mask", "B.Mask"):
        return PREVIEW_BROWN
    if layer == "Dwgs.User":
        return PREVIEW_USER
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


def ensure_pretty_dir(pretty_dir: Path) -> None:
    if pretty_dir.suffix != ".pretty":
        raise SystemExit(f"--pretty-dir must point to a .pretty directory: {pretty_dir}")
    pretty_dir.mkdir(parents=True, exist_ok=True)


def initialize_library_bundle(library_root: Path, library_name: str) -> Path:
    library_root.mkdir(parents=True, exist_ok=True)
    pretty_dir = library_root / f"{library_name}.pretty"
    pretty_dir.mkdir(parents=True, exist_ok=True)

    fp_lib_table = library_root / "fp-lib-table"
    fp_lib_table.write_text(
        "\n".join(
            [
                "(fp_lib_table",
                f'  (lib (name "{library_name}")(type "KiCad")(uri "${{KIPRJMOD}}/{library_name}.pretty")(options "")(descr "Generated art library"))',
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )

    manifest = library_root / "library_manifest.md"
    manifest.write_text(
        "\n".join(
            [
                f"# {library_name}",
                "",
                "Generated by kicad_art_generator.",
                "",
                "Contents:",
                f"- `{library_name}.pretty/`: footprint library directory",
                "- `fp-lib-table`: KiCad footprint library table snippet for project import",
                "",
                "To use in KiCad:",
                "1. Copy this bundle into your project or shared library area.",
                "2. Add the `fp-lib-table` entry to your project footprint libraries, or merge the entry into an existing `fp-lib-table`.",
                "3. Use the footprints from the generated `.pretty` library.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return pretty_dir


def export_to_pretty_dir(output_path: Path, pretty_dir: Path) -> Path:
    destination = pretty_dir / output_path.name
    shutil.copy2(output_path, destination)
    return destination


def analyze_image(
    input_path: Path,
    alpha_threshold: int,
    cluster_tolerance: int,
    min_fraction: float,
    svg_render_width: int,
    tmpdir: Path,
) -> None:
    image, _ = load_work_image(
        input_path=input_path,
        max_dimension=max(svg_render_width, 1),
        svg_render_width=svg_render_width,
        tmpdir=tmpdir,
    )
    width, height = image.size
    total_pixels = width * height
    transparent_pixels = sum(1 for *_rgb, alpha in image.getdata() if alpha < alpha_threshold)
    opaque_pixels = total_pixels - transparent_pixels

    print(f"Image: {input_path}")
    print(f"Size: {width}x{height}")
    print(f"Transparent pixels: {transparent_pixels} ({transparent_pixels / total_pixels:.1%})")
    print(f"Opaque pixels: {opaque_pixels} ({opaque_pixels / total_pixels:.1%})")

    if opaque_pixels <= 0:
        raise SystemExit("Analysis failed: no opaque pixels above the alpha threshold were found.")

    clusters = cluster_opaque_palette(image, alpha_threshold, cluster_tolerance)
    print("Dominant opaque color clusters:")
    for index, cluster in enumerate(clusters[:6], start=1):
        print(f"  {index}. rgb={format_rgb(cluster.rgb)} pixels={cluster.count} coverage={cluster.count / opaque_pixels:.1%}")

    suggestions = suggest_mappings(clusters, opaque_pixels, transparent_pixels, total_pixels, min_fraction)
    if suggestions["background"] is not None:
        print(f"Suggested background/ignore color: {format_rgb(suggestions['background'])}")
    elif transparent_pixels > 0:
        print("Suggested background/ignore color: transparent")
    else:
        print("Suggested background/ignore color: none confidently identified")

    mode = suggestions["mode"]
    if mode == "single":
        foreground = suggestions["foreground"]
        print("Suggested mapping:")
        print("  single-layer art")
        print(f"  retain {format_rgb(foreground)}")
        print("  suggested preset: silkscreen")
        if suggestions["background"] is not None:
            print(f"  ignore {format_rgb(suggestions['background'])}")
    elif mode == "dual":
        primary = suggestions["primary"]
        secondary = suggestions["secondary"]
        print("Suggested mapping:")
        print("  dual-color art")
        print(f"  color 1: {format_rgb(primary)} -> copper-exposed")
        print(f"  color 2: {format_rgb(secondary)} -> silkscreen")
        print(f"  suggested adjacent-color-tolerance: {max(cluster_tolerance, 48)}")
    elif mode == "multi":
        print("Suggested mapping:")
        print("  multi-color art")
        for index, (rgb, preset_name) in enumerate(suggestions["mappings"], start=1):
            print(f"  color {index}: {format_rgb(rgb)} -> {preset_name}")
    else:
        print("Could not find a confident dominant-color mapping.")
        print("Try lowering the background complexity, increasing transparency, or use explicit RGB arguments.")
        raise SystemExit(2)


def cluster_opaque_palette(
    image: Image.Image,
    alpha_threshold: int,
    cluster_tolerance: int,
) -> list[PaletteCluster]:
    palette = Counter(
        (red, green, blue)
        for red, green, blue, alpha in image.getdata()
        if alpha >= alpha_threshold
    )
    clusters: list[PaletteCluster] = []

    for rgb, count in palette.most_common():
        for index, cluster in enumerate(clusters):
            if color_distance_max(rgb, cluster.rgb) <= cluster_tolerance:
                if count > cluster.count:
                    clusters[index] = PaletteCluster(rgb=rgb, count=cluster.count + count)
                else:
                    clusters[index] = PaletteCluster(rgb=cluster.rgb, count=cluster.count + count)
                break
        else:
            clusters.append(PaletteCluster(rgb=rgb, count=count))

    return sorted(clusters, key=lambda cluster: cluster.count, reverse=True)


def suggest_mappings(
    clusters: list[PaletteCluster],
    opaque_pixels: int,
    transparent_pixels: int,
    total_pixels: int,
    min_fraction: float,
) -> dict[str, object]:
    background = infer_background_color(clusters, opaque_pixels, transparent_pixels, total_pixels)
    candidates = [cluster for cluster in clusters if cluster.rgb != background]
    strong = [cluster for cluster in candidates if cluster.count / opaque_pixels >= min_fraction]
    top = strong[:4]
    adjacent_tolerance = 64

    if len(top) >= 2:
        first, second = top[0], top[1]
        third_party_clusters = [
            cluster
            for cluster in top[2:]
            if min(
                color_distance_max(cluster.rgb, first.rgb),
                color_distance_max(cluster.rgb, second.rgb),
            )
            > adjacent_tolerance
        ]
        if (
            first.count / opaque_pixels >= 0.08
            and second.count / opaque_pixels >= 0.08
            and not third_party_clusters
        ):
            return {
                "mode": "dual",
                "primary": first.rgb,
                "secondary": second.rgb,
                "background": background,
            }

    if len(strong) > 4:
        return {"mode": "ambiguous", "background": background}

    if len(top) >= 3:
        preset_names = ["silkscreen", "copper-exposed", "copper-covered", "substrate-exposed"]
        return {
            "mode": "multi",
            "mappings": [
                (cluster.rgb, preset_names[index])
                for index, cluster in enumerate(top[: len(preset_names)])
            ],
            "background": background,
        }

    if len(top) >= 1:
        first = top[0]
        second_fraction = top[1].count / opaque_pixels if len(top) > 1 else 0.0
        min_single_fraction = 0.05 if background is not None else 0.12
        if first.count / opaque_pixels >= min_single_fraction and second_fraction < 0.25:
            return {
                "mode": "single",
                "foreground": first.rgb,
                "background": background,
            }

    return {"mode": "ambiguous", "background": background}


def infer_background_color(
    clusters: list[PaletteCluster],
    opaque_pixels: int,
    transparent_pixels: int,
    total_pixels: int,
) -> tuple[int, int, int] | None:
    if transparent_pixels / total_pixels >= 0.2:
        return None
    if not clusters:
        return None
    top = clusters[0]
    if top.count / opaque_pixels < 0.45:
        return None
    luminance = 0.299 * top.rgb[0] + 0.587 * top.rgb[1] + 0.114 * top.rgb[2]
    if luminance >= 220:
        return top.rgb
    return None


def format_rgb(rgb: tuple[int, int, int]) -> str:
    return ",".join(str(channel) for channel in rgb)


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
    svg_render_width: int,
    verbose: bool,
    tmpdir: Path,
    foreground_rgb: tuple[int, int, int] | None,
    background_rgb: tuple[int, int, int] | None,
    bitmap_processing: str,
    color_tolerance: int,
    preview_output: Path | None,
) -> None:
    if input_path.suffix.lower() in RASTER_SUFFIXES:
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
        if preview_output is not None:
            write_preview_png(
                rows=selection.rows,
                width=selection.width,
                height=selection.height,
                color=preset.preview_color,
                output_path=preview_output,
            )
        size = ArtworkSize(width_px=float(selection.width), height_px=float(selection.height))
        if bitmap_processing in {"vectorize", "vectorize-compact"}:
            svg_input = tmpdir / f"{input_path.stem}_trace.svg"
            vectorize_selection_to_svg(
                selection,
                svg_input,
                tmpdir,
                compact=(bitmap_processing == "vectorize-compact"),
            )
        else:
            svg_input = tmpdir / f"{input_path.stem}.svg"
            rectangles = merge_row_runs(selection.rows)
            if not rectangles:
                raise SystemExit("No visible art remained after raster processing.")
            write_svg_rects(svg_input, selection.width, selection.height, rectangles)
    else:
        svg_input = input_path
        size = load_svg_size(svg_input)
        if preview_output is not None:
            preview_selection = preview_selection_from_svg(
                input_path=input_path,
                tmpdir=tmpdir,
                alpha_threshold=alpha_threshold,
                max_dimension=max_dimension,
                svg_render_width=svg_render_width,
                threshold=threshold,
                invert=invert,
                foreground_rgb=foreground_rgb,
                background_rgb=background_rgb,
                color_tolerance=color_tolerance,
            )
            write_preview_png(
                rows=preview_selection.rows,
                width=preview_selection.width,
                height=preview_selection.height,
                color=preset.preview_color,
                output_path=preview_output,
            )
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
    image, size = load_work_image(
        input_path=input_path,
        max_dimension=max(1, args.max_dimension),
        svg_render_width=args.svg_render_width,
        tmpdir=tmpdir,
    )

    color_matches = [
        ColorMatch("yellow", yellow_rgb, args.copper_layer),
        ColorMatch("white", white_rgb, args.silkscreen_layer),
    ]
    palette_color_sets = select_dual_color_palette_sets(
        image=image,
        matches=color_matches,
        alpha_threshold=alpha_threshold,
        base_tolerance=args.color_tolerance,
        adjacent_tolerance=args.adjacent_color_tolerance,
        adjacent_shade_limit=args.adjacent_shade_limit,
    )

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
            accepted_colors=palette_color_sets.get(match.name),
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


def generate_multi_color_module(
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
    image, size = load_work_image(
        input_path=input_path,
        max_dimension=max(1, args.max_dimension),
        svg_render_width=args.svg_render_width,
        tmpdir=tmpdir,
    )
    preset_names = [part.strip() for part in args.multi_color_presets.split(",") if part.strip()]
    if not preset_names:
        raise SystemExit("--multi-color-presets must contain at least one preset name.")
    presets = [get_art_preset(name) for name in preset_names[: max(1, args.max_color_count)]]

    svg_seed_masks: dict[tuple[int, int, int], RasterSelection] = {}
    if input_path.suffix.lower() == ".svg":
        svg_seed_masks = render_svg_seed_masks(
            input_path=input_path,
            tmpdir=tmpdir,
            svg_render_width=args.svg_render_width,
            alpha_threshold=alpha_threshold,
            max_dimension=max(1, args.max_dimension),
        )
        seed_colors = list(svg_seed_masks)[: min(args.max_color_count, len(presets))]
    else:
        seed_colors = choose_multi_color_seed_colors(
            input_path=input_path,
            image=image,
            alpha_threshold=alpha_threshold,
            cluster_tolerance=args.analysis_cluster_tolerance,
            min_fraction=args.analysis_min_fraction,
            max_color_count=min(args.max_color_count, len(presets)),
        )
    if not seed_colors:
        raise SystemExit("Could not find enough dominant visible colors for multi-color mapping.")

    if input_path.suffix.lower() == ".svg":
        pass
    else:
        palette_sets = select_palette_sets_for_seeds(
            image=image,
            seeds=seed_colors,
            alpha_threshold=alpha_threshold,
            base_tolerance=args.color_tolerance,
            adjacent_tolerance=args.adjacent_color_tolerance,
            adjacent_shade_limit=args.adjacent_shade_limit,
        )

    module_sections: list[str] = []
    preview_layers: list[tuple[list[list[tuple[int, int]]], tuple[int, int, int, int]]] = []
    scale_factor = compute_scale_factor(
        size=size,
        dpi=args.dpi,
        width_mm=target_width_mm,
        height_mm=height_mm,
    )

    for index, seed_rgb in enumerate(seed_colors):
        preset = presets[index]
        if input_path.suffix.lower() == ".svg":
            selection = svg_seed_masks[seed_rgb]
            rows = selection.rows
            rect_width = selection.width
            rect_height = selection.height
        else:
            rows = extract_color_rows(
                image=image,
                target_rgb=seed_rgb,
                tolerance=args.color_tolerance,
                alpha_threshold=alpha_threshold,
                accepted_colors=palette_sets.get(seed_rgb),
            )
            rect_width = int(size.width_px)
            rect_height = int(size.height_px)
        rectangles = merge_row_runs(rows)
        if not rectangles:
            continue
        svg_path = tmpdir / f"multi_{index}.svg"
        write_svg_rects(svg_path, rect_width, rect_height, rectangles)
        preview_layers.append((rows, preset.preview_color))

        for layer in preset.layers:
            temp_module = tmpdir / f"multi_{index}_{layer.replace('.', '_')}.kicad_mod"
            run_svg2mod(
                svg_input=svg_path,
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
        raise SystemExit("Multi-color mapping did not produce any geometry.")
    if preview_output is not None:
        write_multi_preview_png(
            preview_layers=preview_layers,
            width=int(size.width_px),
            height=int(size.height_px),
            output_path=preview_output,
        )
    write_combined_module(output_path, footprint_name, value, module_sections)


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


def load_work_image(
    input_path: Path,
    max_dimension: int,
    svg_render_width: int,
    tmpdir: Path,
) -> tuple[Image.Image, ArtworkSize]:
    if input_path.suffix.lower() in RASTER_SUFFIXES:
        return open_and_scale_image(input_path, max_dimension)
    if input_path.suffix.lower() == ".svg":
        raster_path = tmpdir / f"{input_path.stem}_render.png"
        render_svg_to_png(input_path, raster_path, svg_render_width)
        return open_and_scale_image(raster_path, max_dimension)
    raise SystemExit(f"Unsupported input type for image-based processing: {input_path.suffix}")


def preview_selection_from_svg(
    input_path: Path,
    tmpdir: Path,
    alpha_threshold: int,
    max_dimension: int,
    svg_render_width: int,
    threshold: int,
    invert: bool,
    foreground_rgb: tuple[int, int, int] | None,
    background_rgb: tuple[int, int, int] | None,
    color_tolerance: int,
) -> RasterSelection:
    raster_path = tmpdir / f"{input_path.stem}_preview.png"
    render_svg_to_png(input_path, raster_path, svg_render_width)
    return raster_to_selection(
        input_path=raster_path,
        threshold=threshold,
        alpha_threshold=alpha_threshold,
        invert=invert,
        max_dimension=max_dimension,
        foreground_rgb=foreground_rgb,
        background_rgb=background_rgb,
        color_tolerance=color_tolerance,
    )


def vectorize_selection_to_svg(
    selection: RasterSelection,
    output_svg: Path,
    tmpdir: Path,
    compact: bool = False,
) -> None:
    pbm_path = tmpdir / "trace_input.pbm"
    scale_divisor = 2 if compact else 1
    target_width = max(1, selection.width // scale_divisor)
    target_height = max(1, selection.height // scale_divisor)
    bitmap = Image.new("1", (target_width, target_height), 1)
    pixels = bitmap.load()
    for y, runs in enumerate(selection.rows):
        for x0, x1 in runs:
            if compact:
                y_scaled = min(target_height - 1, y // scale_divisor)
                for x in range(x0, x1):
                    x_scaled = min(target_width - 1, x // scale_divisor)
                    pixels[x_scaled, y_scaled] = 0
            else:
                for x in range(x0, x1):
                    pixels[x, y] = 0
    bitmap.save(pbm_path)
    command = [
        "potrace",
        "-s",
        "--turdsize",
        "6" if compact else "2",
        "--opttolerance",
        "0.5" if compact else "0.2",
        "-o",
        str(output_svg),
        str(pbm_path),
    ]
    command.insert(2, "--flat" if compact else "--longcurve")
    if compact:
        command.extend(["--unit", "2"])
    subprocess.run(command, check=True)


def render_svg_to_png(input_path: Path, output_path: Path, render_width: int) -> None:
    command = [
        "rsvg-convert",
        "--keep-aspect-ratio",
        "--width",
        str(render_width),
        "-o",
        str(output_path),
        str(input_path),
    ]
    subprocess.run(command, check=True)


def render_svg_seed_masks(
    input_path: Path,
    tmpdir: Path,
    svg_render_width: int,
    alpha_threshold: int,
    max_dimension: int,
) -> dict[tuple[int, int, int], RasterSelection]:
    rendered: list[tuple[tuple[int, int, int], RasterSelection, int]] = []
    for index, seed_rgb in enumerate(parse_svg_declared_colors(input_path)):
        mask_svg = tmpdir / f"multi_mask_{index}.svg"
        mask_png = tmpdir / f"multi_mask_{index}.png"
        write_svg_color_mask(input_path, seed_rgb, mask_svg)
        render_svg_to_png(mask_svg, mask_png, svg_render_width)
        selection = raster_to_selection(
            input_path=mask_png,
            threshold=200,
            alpha_threshold=alpha_threshold,
            invert=False,
            max_dimension=max_dimension,
            foreground_rgb=(0, 0, 0),
            background_rgb=(255, 255, 255),
            color_tolerance=24,
        )
        coverage = sum(x1 - x0 for runs in selection.rows for x0, x1 in runs)
        if coverage > 0:
            rendered.append((seed_rgb, selection, coverage))
    rendered.sort(key=lambda item: item[2], reverse=True)
    return {seed_rgb: selection for seed_rgb, selection, _coverage in rendered}


def parse_svg_declared_colors(input_path: Path) -> list[tuple[int, int, int]]:
    text = input_path.read_text(encoding="utf-8")
    matches = re.findall(r"(?i)(?:fill|stroke)\s*:\s*rgb\((\d+),(\d+),(\d+)\)|(?:fill|stroke)\s*=\s*\"#([0-9a-f]{6})\"", text)
    colors: list[tuple[int, int, int]] = []
    for r1, g1, b1, hex_value in matches:
        if hex_value:
            colors.append(tuple(int(hex_value[i : i + 2], 16) for i in (0, 2, 4)))
        else:
            colors.append((int(r1), int(g1), int(b1)))
    seen: set[tuple[int, int, int]] = set()
    ordered: list[tuple[int, int, int]] = []
    for color in colors:
        if color not in seen:
            seen.add(color)
            ordered.append(color)
    return ordered


def write_svg_color_mask(input_path: Path, target_rgb: tuple[int, int, int], output_path: Path) -> None:
    text = input_path.read_text(encoding="utf-8")
    target = f"rgb({target_rgb[0]},{target_rgb[1]},{target_rgb[2]})"
    target_hex = "#{:02x}{:02x}{:02x}".format(*target_rgb)

    def replace_style(match: re.Match[str]) -> str:
        prop = match.group(1)
        value = match.group(2)
        normalized = value.replace(" ", "").lower()
        if normalized in {target.lower(), target_hex.lower()}:
            return f"{prop}:rgb(0,0,0)"
        return f"{prop}:none"

    text = re.sub(
        r"(fill|stroke)\s*:\s*(rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)|#[0-9A-Fa-f]{6})",
        replace_style,
        text,
    )

    def replace_attr(match: re.Match[str]) -> str:
        prop = match.group(1)
        value = match.group(2)
        normalized = value.replace(" ", "").lower()
        if normalized in {target.lower(), target_hex.lower()}:
            return f'{prop}="rgb(0,0,0)"'
        return f'{prop}="none"'

    text = re.sub(
        r'(fill|stroke)\s*=\s*"(rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)|#[0-9A-Fa-f]{6})"',
        replace_attr,
        text,
    )
    output_path.write_text(text, encoding="utf-8")


def select_dual_color_palette_sets(
    image: Image.Image,
    matches: list[ColorMatch],
    alpha_threshold: int,
    base_tolerance: int,
    adjacent_tolerance: int,
    adjacent_shade_limit: int,
) -> dict[str, set[tuple[int, int, int]]]:
    accepted_by_rgb = select_palette_sets_for_seeds(
        image=image,
        seeds=[match.rgb for match in matches],
        alpha_threshold=alpha_threshold,
        base_tolerance=base_tolerance,
        adjacent_tolerance=adjacent_tolerance,
        adjacent_shade_limit=adjacent_shade_limit,
    )
    return {match.name: accepted_by_rgb.get(match.rgb, set()) for match in matches}


def select_palette_sets_for_seeds(
    image: Image.Image,
    seeds: list[tuple[int, int, int]],
    alpha_threshold: int,
    base_tolerance: int,
    adjacent_tolerance: int,
    adjacent_shade_limit: int,
) -> dict[tuple[int, int, int], set[tuple[int, int, int]]]:
    palette = Counter(
        (red, green, blue)
        for red, green, blue, alpha in image.getdata()
        if alpha >= alpha_threshold
    )
    ranked_colors = [rgb for rgb, _count in palette.most_common()]

    accepted: dict[tuple[int, int, int], set[tuple[int, int, int]]] = {seed: set() for seed in seeds}
    extra_counts: dict[tuple[int, int, int], int] = {seed: 0 for seed in seeds}

    for rgb in ranked_colors:
        distances = sorted(
            ((color_distance_max(rgb, seed), seed) for seed in seeds),
            key=lambda item: item[0],
        )
        nearest_distance, nearest_seed = distances[0]
        second_distance = distances[1][0] if len(distances) > 1 else 255

        if nearest_distance <= base_tolerance:
            accepted[nearest_seed].add(rgb)
            continue

        if (
            nearest_distance <= adjacent_tolerance
            and extra_counts[nearest_seed] < adjacent_shade_limit
            and second_distance - nearest_distance >= 8
        ):
            accepted[nearest_seed].add(rgb)
            extra_counts[nearest_seed] += 1

    return accepted


def assign_pixels_to_svg_seed_colors(
    image: Image.Image,
    seeds: list[tuple[int, int, int]],
    alpha_threshold: int,
) -> dict[tuple[int, int, int], set[tuple[int, int, int]]]:
    palette = Counter(
        (red, green, blue)
        for red, green, blue, alpha in image.getdata()
        if alpha >= alpha_threshold
    )
    assignments: dict[tuple[int, int, int], set[tuple[int, int, int]]] = {seed: set() for seed in seeds}
    for rgb, _count in palette.items():
        nearest_seed = min(seeds, key=lambda seed: color_distance_max(rgb, seed))
        assignments[nearest_seed].add(rgb)
    return assignments


def choose_multi_color_seed_colors(
    input_path: Path,
    image: Image.Image,
    alpha_threshold: int,
    cluster_tolerance: int,
    min_fraction: float,
    max_color_count: int,
) -> list[tuple[int, int, int]]:
    if input_path.suffix.lower() == ".svg":
        declared = parse_svg_declared_colors(input_path)
        if declared:
            return rank_seed_colors_by_coverage(image, declared, alpha_threshold)[:max_color_count]

    clusters = choose_multi_color_clusters(
        image=image,
        alpha_threshold=alpha_threshold,
        cluster_tolerance=cluster_tolerance,
        min_fraction=min_fraction,
        max_color_count=max_color_count,
    )
    return [cluster.rgb for cluster in clusters]


def rank_seed_colors_by_coverage(
    image: Image.Image,
    seeds: list[tuple[int, int, int]],
    alpha_threshold: int,
) -> list[tuple[int, int, int]]:
    coverage = {seed: 0 for seed in seeds}
    for red, green, blue, alpha in image.getdata():
        if alpha < alpha_threshold:
            continue
        rgb = (red, green, blue)
        nearest_seed = min(seeds, key=lambda seed: color_distance_max(rgb, seed))
        coverage[nearest_seed] += 1
    return [seed for seed, _count in sorted(coverage.items(), key=lambda item: item[1], reverse=True) if _count > 0]


def choose_multi_color_clusters(
    image: Image.Image,
    alpha_threshold: int,
    cluster_tolerance: int,
    min_fraction: float,
    max_color_count: int,
) -> list[PaletteCluster]:
    clusters = cluster_opaque_palette(image, alpha_threshold, cluster_tolerance)
    opaque_pixels = sum(cluster.count for cluster in clusters)
    background = infer_background_color(clusters, opaque_pixels, 0, opaque_pixels)
    candidates = [cluster for cluster in clusters if cluster.rgb != background]
    strong = [cluster for cluster in candidates if cluster.count / opaque_pixels >= min_fraction]
    return strong[:max_color_count]


def extract_color_rows(
    image: Image.Image,
    target_rgb: tuple[int, int, int],
    tolerance: int,
    alpha_threshold: int,
    accepted_colors: set[tuple[int, int, int]] | None = None,
) -> list[list[tuple[int, int]]]:
    pixels = image.load()
    width, height = image.size
    rows: list[list[tuple[int, int]]] = []

    for y in range(height):
        runs: list[tuple[int, int]] = []
        run_start: int | None = None
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            pixel_rgb = (red, green, blue)
            channel_delta = color_distance_max(pixel_rgb, target_rgb)
            if accepted_colors is not None:
                filled = alpha >= alpha_threshold and pixel_rgb in accepted_colors
            else:
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
    # `unlocked` inside (at ...) is this legacy (module ...) format's spelling
    # of keep_upright FALSE -- without it KiCad loads the text with "Keep
    # upright" ON and the glyphs refuse to follow a 180/270 degree footprint
    # rotation. Verified round-trip against pcbnew 10.0: bare `unlocked` in
    # `at` reads back IsKeepUpright() == False.
    return (
        f"(fp_text {kind} {text} (at 0 {y_pos} unlocked) (layer F.SilkS) hide "
        f"(effects (font (size 1.524 1.524) (thickness 0.3048))))"
    )


def indent_kicad_block(block: str, spaces: int) -> str:
    indent = " " * spaces
    return "\n".join(f"{indent}{line}" if line else line for line in block.splitlines())


if __name__ == "__main__":
    main()
