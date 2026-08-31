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

The library also STAGES the hand-authored parts in library/RecklessArt.pretty/
alongside the emitted ones, so that this one command produces the complete
shippable library rather than most of it. Those two are checked-in geometry,
not renders -- see CURATED below.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets" / "normalised"

# The one piece in this library whose tone assignment is a DESIGN DECISION
# rather than a consequence of the artwork, so it is written into the
# footprint's own (descr) where a reader in the KiCad library browser will meet
# it, instead of living only here.
MFB_3TONE_DESCR = (
    "THREE-TONE MFB lockup for the PURPLE product baseline. "
    "T5 bare purple mask = the field, and draws nothing because T5 IS the "
    "board; T2 ENIG gold = the orange band, on F.Cu+F.Mask; T1 silk white = "
    "the Bitcoin B and the wordmark, on F.SilkS. "
    "DESIGN DECISION: the source is MFB's own white-wordmark colourway "
    "(Logo MPB Assets-10), not the near-black one (Assets-2). MFB put a WHITE "
    "mark on purple themselves, so recolouring the wordmark for a purple "
    "board follows their usage rather than inventing a colourway; and "
    "measured, the near-black #231F20 quantises to T5, which would make the "
    "wordmark the same tone as the background it sits on and erase it. "
    "FIDELITY: orange #F7941F -> T2 ENIG is a dE 32 hue shift. No tone in the "
    "palette is closer -- the next is T3 bare FR4 at dE 51."
)

# --- the manifest -----------------------------------------------------------
#
# name -> (normalised asset, [sizes mm], extra emit_art flags)
#
# Sizes are the LONG EDGE of the finished art, and NEITHER the sizes NOR the
# flags here are taste. Every (piece, size, flags) row below is one that
# tools/verify_art.py returns PASS for under kicad-cli 10.0.0 with the render
# and clearance checks live. A size that used to be in this list and is gone
# was removed because the artwork is not fabricable that small, and the
# measured number that says so is in the comment on the entry.
#
# The two knobs that do the work, and why they are not interchangeable:
#
#   --min-area-mm2 drops a region by AREA. It is the right tool for the
#   shattered antialias contour that quantising a photographic source leaves
#   along every tone boundary -- hundreds of loops of a few thousandths of a
#   mm2 that can never image as a line. It cannot touch a GAP between two real
#   features, and it cannot see a sliver: a 0.045 x 0.5 mm hair has twice the
#   copper auto-threshold's area while being 2.2x under the width floor. Where
#   the residual defect is a gap, the only lever is SIZE, and that is why four
#   pieces below got bigger instead of getting a flag.
#
#   'auto' means each tone's own minimum fabricable feature squared
#   (emit_art.py:2217). It is principled but weak, because of the sliver case
#   above. Where a measured explicit value clears the part and 'auto' does
#   not, the explicit value is used and the plateau it sits on is recorded --
#   a threshold is only trustworthy if neighbouring values give the same
#   answer, otherwise it is a knife-edge fit to one input.
#
# --allow-dropped-tones appears ONLY on the entries that actually drop a tone
# to zero polygons. On the others the guard stays armed, so that a future
# change to an asset or a threshold that starts deleting a whole tone fails
# loudly instead of passing quietly.
LIBRARY = [
    # 0.10 mm2, not 'auto'. auto WARNs at both sizes (12 mm: F.Cu narrowest
    # 0.0272, F.SilkS 0.0506 -- slivers with legal area). 0.05 / 0.10 / 0.15
    # all emit the byte-identical 9,585 B / 10-polygon part at 12 mm, so 0.10
    # sits in the middle of a measured plateau rather than on an edge. What it
    # removes over auto is 1 extra T1 loop, 2 T2 loops totalling 0.0104 mm2,
    # and T4 -- which in this image is literally ONE pixel (0.00074 mm2).
    ("satoshi_miner",  "satoshi_miner.png",            [12, 20],
     ["--min-area-mm2", "0.10", "--allow-dropped-tones"]),
    # 0.02 mm2 clears both sizes. auto clears 12 mm (identically -- 7,975 B)
    # but leaves 20 mm at F.Cu narrowest 0.0422, so one threshold for both
    # sizes beats a per-size split.
    ("satoshi_little", "little_satoshi.png",           [12, 20],
     ["--min-area-mm2", "0.02", "--allow-dropped-tones"]),
    # 20 mm ONLY, and it is the sole size that works. The residual at 12 mm is
    # two GAPS, which no min-area can reach: F.Cu 0.0845 and F.Mask 0.0580
    # against a 0.10 floor, plus a 0.1177 mm silk feature. Bisected upward at
    # 0.02: 16 mm still leaves an F.Mask gap of 0.0633, 18 mm 0.0871, 20 mm is
    # clean. It does not scale back up either -- at 30 mm the T6/T7 specks
    # regrow past 0.02 mm2 and it WARNs again, so this piece is one size.
    ("satoshi_points", "satoshi_points.png",           [20],
     ["--min-area-mm2", "0.02", "--allow-dropped-tones"]),
    # 38/50 mm, up from 12/20. Nothing is wrong with the artwork; it is a
    # dense badge and its silk-to-silk gaps scale with the piece. At 12 mm the
    # worst F.SilkS gap is 0.0242 mm and at 20 mm 0.0616 mm, against a 0.15 mm
    # floor -- a factor of 2.5 under, at which silk bleeds inward and the
    # features merge into a blob. First clean size is 37 mm; 38 is used for a
    # little headroom. Same story for mfb_node_light (0.0166 at 12 mm).
    ("mfb_node_full",  "mfb_node_full.svg",            [38, 50],
     ["--min-area-mm2", "auto", "--allow-dropped-tones"]),
    ("mfb_node_light", "mfb_node_light.svg",           [38, 50],
     ["--min-area-mm2", "auto", "--allow-dropped-tones"]),
    # The Reckless mark in colour, and the source is the WHITE-on-colour
    # colourway, NOT reckless_color.svg. This is the same trap that produced
    # the mfb_logo orphan, and it is measured, not suspected: quantise
    # reckless_color.svg and 292,508 of its 459,417 opaque pixels -- 63.7% --
    # land on T5, which draws nothing. Every one of those pixels is INTERIOR
    # (flood-filling the background in from the image border reaches none of
    # them), so it is not a transparent margin being discounted, it is the
    # body of the logo being erased. reckless_white_color.svg is pixel-for-
    # pixel the same mark with the dark body white: T5 = 0, nothing is lost.
    # On a BLACK-mask board reckless_color.svg is the correct file, because
    # there the erased body IS the board; on the purple product baseline it is
    # not, and this library targets purple.
    ("reckless_3tone",  "reckless_white_color.svg",    [35, 50],
     ["--min-area-mm2", "auto", "--allow-dropped-tones"]),
    # 35/50 mm, up from 12/20, and for the same reason as the node badges:
    # F.SilkS gap 0.0515 mm at 12 mm, 0.0858 at 20 mm. Bisected: 34 mm still
    # WARNs at 0.1459 mm, 35 mm is clean. reckless_3tone above is the same
    # artwork and reports the same two gaps to the micron, so both Reckless
    # entries carry the same pair of sizes. No min-area flag -- measured, this
    # asset drops no tone and 'auto' is a byte-for-byte no-op on it, so adding
    # it would only be cargo.
    ("reckless_mono",  "reckless_black.svg",           [35, 50], ["--ink-tone", "T1"]),
    ("mfb_lockup",     "mfb_lockup_white.svg",         [20, 30], ["--min-area-mm2", "auto"]),
    # The same horizontal lockup in MFB's orange/white colourway, which on the
    # purple product baseline is the THREE-tone mark: T5 bare purple mask for
    # the field, T2 ENIG for the band, T1 silk for the Bitcoin B and the
    # wordmark. Two of the three are drawn; T5 draws nothing because T5 IS the
    # board. No --allow-dropped-tones: measured, the quantiser lands on exactly
    # {T1, T2} with zero pixels dropped, so there is nothing to allow and the
    # guard stays armed. See tools/prep_assets.py for why the source is
    # Assets-10 and not Assets-2.
    ("mfb_lockup_3tone", "mfb_lockup_3tone.png",       [20, 30],
     ["--min-area-mm2", "auto", "--descr", MFB_3TONE_DESCR]),
    ("bitcoin_b",      "bitcoin_b.svg",                [10, 16], []),
    # THE 72 mm FIGURE BELOW WAS WRONG, AND WRONG IN THE DANGEROUS DIRECTION.
    #
    # It read "the narrowest F.SilkS feature scales dead linearly at 0.002105
    # mm per mm of width, so it reaches the 0.15 mm silk floor only at 72 mm.
    # Bisected: 70 mm gives 0.1475, 71 mm 0.1496, 72 mm clears." Every number
    # in that sentence came from the FOOTPRINT-level min-feature check, which
    # is a rotating caliper on the CONVEX HULL -- exact for a convex outline
    # and an over-estimate for a concave one. Glyphs are concave. Placed on a
    # board and measured by the ink-floor check, which takes the inscribed
    # width of the region and is the exact one, the same art at 72 mm is
    # 0.078192 mm at 8 sites: less than HALF the floor. The true rate is
    # 0.001086 mm/mm, so this art needs 138 mm to clear in silk.
    #
    # So btc_emission_72mm and _90mm SHIP SUB-FLOOR SILK. They are kept only
    # so the defect stays reproducible; nothing should place them.
    ("btc_emission",   "bitcoin_emission_formula.svg", [72, 90], ["--ink-tone", "T1"]),

    # The replacement, and the reason tools/render_math.py exists. Same maths,
    # re-rendered from the expression in STIX Sans: a uniform-stroke face has
    # no hairline to lose, so the narrowest ink is 0.137 mm at 72 mm against
    # the serif's 0.078, and the whole graphic clears at 79 mm rather than 138.
    # 80 mm is that minimum with a little air. Verified on a board: no sub-floor
    # ink, and the narrowest gap is 0.300 mm against the 0.150 mm floor.
    #
    # Silk-only is deliberate. JLCPCB publishes the same 0.15 mm silk floor on
    # all three of their profiles, so this one size is correct on the cheap
    # process as well as the fine one. The ENIG alternative clears copper at
    # ~47 mm but binds against a minimum mask OPENING, which JLCPCB does not
    # publish -- fab_profiles.py carries a mask DAM figure, which is a
    # different quantity. Unpublished is not the same as met.
    ("btc_emission_sans", "bitcoin_emission_formula_sans.svg", [80],
     ["--ink-tone", "T1"]),
]

# --- hand-authored parts ----------------------------------------------------
#
# Not renders. These are checked-in geometry under library/RecklessArt.pretty/
# that no quantiser can produce -- art_hex_asic_window is a board cutout with
# ENIG registration marks placed around it, and art_btc_whitepaper_b is 1,712
# stroke-font glyphs flowed into a mask shape by tools/microtext.py. They are
# staged into the output library so that ONE command yields the whole shippable
# set; their source of truth is the .kicad_mod in git, and verify_art runs over
# them exactly as it does over the emitted pieces.
CURATED = REPO / "library" / "RecklessArt.pretty"


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
    ap.add_argument("--no-curated", action="store_true",
                    help="skip staging the hand-authored parts in "
                         "library/RecklessArt.pretty (see CURATED)")
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

    staged = []
    if not a.no_curated:
        for src in sorted(CURATED.glob("*.kicad_mod")):
            if a.only and src.stem not in a.only:
                continue
            dst = outdir / src.name
            shutil.copyfile(src, dst)
            staged.append(dst)

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
    for d in staged:
        n = d.stat().st_size
        total += n
        print(f"  {d.stem:24s} {n:8,d} B  (hand-authored, staged from "
              f"{CURATED.relative_to(REPO)})")
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
