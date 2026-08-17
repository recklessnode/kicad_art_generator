#!/usr/bin/env python3
"""Render the whole RecklessArt footprint library, then verify every piece.

One command so the library is reproducible rather than a pile of remembered
shell invocations::

    python3 tools/render_library.py                  # render + verify + sheet
    python3 tools/render_library.py --only bitcoin_b
    python3 tools/render_library.py --no-verify

Inputs are the NORMALISED assets written by tools/prep_assets.py, never the raw
sources: normalisation is where the white matte behind Little Satoshi and the
soft drop shadows under all three Satoshi characters are keyed out. Rendering
from the raw file silently reintroduces both.

Two entries carry --ink-tone T1. They are pure black line art, and black is the
colour of the board itself (T5 black mask), so quantised on their own merits
they land entirely on the background tone and emit nothing at all. On a
black-mask board you fabricate black line art in silk white. See
tools/emit_art.py --ink-tone.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets" / "normalised"

# name -> (normalised asset, [sizes mm], extra emit_art flags)
#
# Sizes are the LONG EDGE of the finished art. bitcoin_b is smaller because it
# is a compact mark; btc_emission is larger because it is a wide formula whose
# strokes fall under the 0.15 mm silk floor below ~25 mm (prep_assets flags it
# UNSUITABLE at 12 mm).
LIBRARY = [
    ("satoshi_miner",  "satoshi_miner.png",            [12, 20], []),
    ("satoshi_little", "little_satoshi.png",           [12, 20], []),
    ("satoshi_points", "satoshi_points.png",           [12, 20], []),
    ("mfb_node_full",  "mfb_node_full.svg",            [12, 20], []),
    ("mfb_node_light", "mfb_node_light.svg",           [12, 20], []),
    ("reckless_color", "reckless_color.svg",           [12, 20], []),
    ("reckless_mono",  "reckless_black.svg",           [12, 20], ["--ink-tone", "T1"]),
    ("mfb_lockup",     "mfb_lockup_white.svg",         [20, 30], ["--min-area-mm2", "auto"]),
    ("bitcoin_b",      "bitcoin_b.svg",                [10, 16], []),
    ("btc_emission",   "bitcoin_emission_formula.svg", [25, 35], ["--ink-tone", "T1"]),
]


def render(name, asset, size, extra, outdir, previewdir, quiet):
    src = ASSETS / asset
    if not src.exists():
        return {"name": f"{name}_{size:g}mm", "error": f"missing asset {src}"}
    stem = f"{name}_{size:g}mm"
    out = outdir / f"{stem}.kicad_mod"
    rep = previewdir / f"{stem}.json"
    cmd = [sys.executable, str(REPO / "tools" / "emit_art.py"),
           "--labels", str(src), "--width-mm", str(size), "--name", stem,
           "-o", str(out), "--report-json", str(rep),
           "--preview", str(previewdir / f"{stem}.png")] + list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if not quiet:
        sys.stdout.write(p.stdout)
    if p.returncode != 0:
        sys.stderr.write(p.stderr)
        return {"name": stem, "error": f"emit_art exit {p.returncode}",
                "stderr": p.stderr.strip()}
    r = json.loads(rep.read_text())
    r["file"] = str(out)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "output" / "RecklessArt.pretty"))
    ap.add_argument("--work", default=str(REPO / "output" / "library_work"),
                    help="per-piece previews and emit reports")
    ap.add_argument("--only", nargs="+", default=None)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    outdir = pathlib.Path(a.out)
    workdir = pathlib.Path(a.work)
    outdir.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    reports, failed = [], []
    for name, asset, sizes, extra in LIBRARY:
        if a.only and name not in a.only:
            continue
        for size in sizes:
            r = render(name, asset, size, extra, outdir, workdir, a.quiet)
            reports.append(r)
            if "error" in r:
                failed.append(r)

    summary = workdir / "library.json"
    summary.write_text(json.dumps(reports, indent=2), encoding="utf-8")

    print(f"\n{'=' * 74}\n  RENDERED {len(reports) - len(failed)} / {len(reports)} "
          f"-> {outdir}\n{'=' * 74}")
    for r in reports:
        if "error" in r:
            print(f"  !! {r['name']}: {r['error']}")
            continue
        polys = sum(t["polys"] for t in r["tones"])
        print(f"  {r['name']:24s} {r['bytes']:8,d} B  {polys:5d} polys  "
              f"{r['width_mm']:.1f} x {r['height_mm']:.1f} mm")
    total = sum(r.get("bytes", 0) for r in reports)
    print(f"  {'':24s} {total:8,d} B  total")

    if failed:
        print(f"\n!! {len(failed)} piece(s) failed to render.")
        return 1
    if a.no_verify:
        return 0

    print("\nverifying ...")
    v = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_art.py"), str(outdir)],
        stdin=subprocess.DEVNULL)
    return v.returncode


if __name__ == "__main__":
    raise SystemExit(main())
