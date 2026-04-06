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
    assert "(layer F.Cu)" in text
    assert "(fp_poly" in text


def test_raster_input_generates_kicad_module(tmp_path: Path) -> None:
    image_path = tmp_path / "test.png"
    output = tmp_path / "test_logo.kicad_mod"

    image = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 27, 27), fill=(0, 0, 0, 255))
    draw.rectangle((11, 11, 20, 20), fill=(255, 255, 255, 0))
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
            "10",
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    text = output.read_text(encoding="utf-8")
    assert "(module test_logo" in text
    assert "(layer F.SilkS)" in text
    assert "(fp_poly" in text
