from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_svg_example_generates_kicad_module(tmp_path: Path) -> None:
    output = tmp_path / "bitcoin_b.kicad_mod"
    example = REPO_ROOT / "examples" / "bitcoin_b.svg"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "kicad_art_generator.cli",
            str(example),
            "--output",
            str(output),
            "--layer",
            "F.Cu",
            "--width-mm",
            "20",
            "--center",
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    text = output.read_text(encoding="utf-8")
    assert "(module bitcoin_b" in text
    assert "(attr board_only exclude_from_pos_files exclude_from_bom)" in text
    assert "(layer F.Cu)" in text
    assert "(fp_poly" in text


def test_dual_color_generates_combined_layers_and_presets(tmp_path: Path) -> None:
    image_path = tmp_path / "test.png"
    output_dir = tmp_path / "out"

    image = Image.new("RGBA", (32, 24), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 13, 21), fill=(247, 147, 26, 255))
    draw.rectangle((16, 2, 29, 21), fill=(255, 255, 255, 255))
    image.save(image_path)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "kicad_art_generator.cli",
            str(image_path),
            "--mode",
            "dual-color",
            "--output",
            str(output_dir),
            "--preset-sizes-in",
            "1,2,4",
            "--footprint-name",
            "badge_art",
            "--center",
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    generated = sorted(path.name for path in output_dir.glob("*.kicad_mod"))
    assert generated == [
        "badge_art_1in.kicad_mod",
        "badge_art_2in.kicad_mod",
        "badge_art_4in.kicad_mod",
    ]

    text = (output_dir / "badge_art_2in.kicad_mod").read_text(encoding="utf-8")
    assert "(module badge_art_2in" in text
    assert "(attr board_only exclude_from_pos_files exclude_from_bom)" in text
    assert text.count("(fp_poly") >= 2
    assert "(layer F.Cu)" in text
    assert "(layer F.SilkS)" in text


def test_single_layer_color_match_and_preview(tmp_path: Path) -> None:
    image_path = tmp_path / "cactus_like.png"
    output = tmp_path / "cactus.kicad_mod"
    preview = tmp_path / "cactus_preview.png"

    image = Image.new("RGBA", (24, 24), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 3, 19, 20), fill=(0, 0, 0, 255))
    draw.rectangle((9, 9, 14, 14), fill=(255, 255, 255, 255))
    image.save(image_path)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "kicad_art_generator.cli",
            str(image_path),
            "--output",
            str(output),
            "--layer",
            "F.SilkS",
            "--width-mm",
            "12",
            "--foreground-rgb",
            "0,0,0",
            "--background-rgb",
            "255,255,255",
            "--color-tolerance",
            "8",
            "--preview-output",
            str(preview),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    text = output.read_text(encoding="utf-8")
    assert "(module cactus" in text
    assert "(layer F.SilkS)" in text
    assert preview.exists()
