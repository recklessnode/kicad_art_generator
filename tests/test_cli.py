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
    preview = tmp_path / "out_preview.png"

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
            "--yellow-preset",
            "copper-exposed",
            "--white-preset",
            "silkscreen",
            "--preview-output",
            str(preview),
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
    assert "(layer F.Mask)" in text
    assert "(layer F.SilkS)" in text
    assert (tmp_path / "badge_art_2in_preview.png").exists()


def test_dual_color_absorbs_adjacent_shades(tmp_path: Path) -> None:
    image_path = tmp_path / "shades.png"
    output = tmp_path / "shades.kicad_mod"

    image = Image.new("RGBA", (24, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((1, 2, 6, 13), fill=(246, 226, 0, 255))
    draw.rectangle((9, 2, 14, 13), fill=(1, 105, 56, 255))
    draw.rectangle((16, 2, 22, 13), fill=(14, 58, 34, 255))
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
            str(output),
            "--width-mm",
            "16",
            "--yellow-rgb",
            "246,226,0",
            "--white-rgb",
            "1,105,56",
            "--yellow-preset",
            "copper-exposed",
            "--white-preset",
            "silkscreen",
            "--color-tolerance",
            "24",
            "--adjacent-color-tolerance",
            "64",
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    text = output.read_text(encoding="utf-8")
    assert "(layer F.Cu)" in text
    assert "(layer F.Mask)" in text
    assert text.count("(layer F.SilkS)") >= 2


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


def test_single_layer_copper_exposed_preset_adds_mask(tmp_path: Path) -> None:
    image_path = tmp_path / "blob.png"
    output = tmp_path / "blob.kicad_mod"

    image = Image.new("RGBA", (20, 20), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((3, 3, 16, 16), fill=(0, 0, 0, 255))
    image.save(image_path)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "kicad_art_generator.cli",
            str(image_path),
            "--output",
            str(output),
            "--art-preset",
            "copper-exposed",
            "--width-mm",
            "10",
            "--foreground-rgb",
            "0,0,0",
            "--background-rgb",
            "255,255,255",
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    text = output.read_text(encoding="utf-8")
    assert "(layer F.Cu)" in text
    assert "(layer F.Mask)" in text


def test_export_to_pretty_dir(tmp_path: Path) -> None:
    image_path = tmp_path / "logo.png"
    output = tmp_path / "logo.kicad_mod"
    pretty_dir = tmp_path / "ArtAssets.pretty"

    image = Image.new("RGBA", (18, 18), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 13, 13), fill=(0, 0, 0, 255))
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
            "8",
            "--foreground-rgb",
            "0,0,0",
            "--background-rgb",
            "255,255,255",
            "--pretty-dir",
            str(pretty_dir),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    exported = pretty_dir / "logo.kicad_mod"
    assert exported.exists()
    assert "(module logo" in exported.read_text(encoding="utf-8")
