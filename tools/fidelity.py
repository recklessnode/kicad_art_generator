#!/usr/bin/env python3
"""Does the picture survive? Three metrics, none of which reads the emitter.

THE RULE THIS FILE EXISTS TO ENFORCE. A check that cannot fail what it exists
to catch is worse than no check, because it converts an unknown into a false
assurance. This repo has been bitten by that four times:

  1. verify_art reported a text minimum-feature by echoing back the emitter's
     own ``(thickness ...)`` attribute; a part 29 % under floor passed 7 of 7.
  2. the pre-ship T5 census counted INTERIOR T5 only, discounting anything
     flood-fill-reachable from the border as margin. The limbs touch the
     background, so the fill walked through them: satoshi_points scored 1.1 %
     against a 20 % line while being 28.7 % by an honest metric.
  3. DRC cannot see a texture tile landing on one net -- KiCad silently
     assigns the touching net to netless copper -- so 206/0/0 was never
     evidence of clearance.
  4. build_library's test helper ``ignores()`` documented itself as "the
     independent second opinion" while being a line-for-line reimplementation
     of the tool's own logic.

So: **this module is forbidden from importing anything from emit_art except
``rasterise_svg``, ``crop_to_content`` and ``relative_luminance``** -- the
loader, the crop and the luminance function, all three of which describe the
INPUT rather than the output. There is a static test asserting exactly that
import list (``test_helper_is_not_a_reimplementation``). Coverage is rasterised
from the ``.kicad_mod`` TEXT with a regex and a scan-line fill written here;
none of emit_art's geometry code runs.

ALIGNMENT is the one thing taken from the emitter's report, and it is taken as
a DECLARATION rather than as a measurement: ``mm_per_px`` and ``width_mm``.
Loop space is emit_art's own pixel-centre space (emit_art.py lines 303-304 and
1347-1348), where a contour vertex at pixel (row r, col c) maps to
``mm = (px + 0.5) * mm_per_px + o``. Inverted:

    x_px = (x_mm + width_mm/2) / mm_per_px - 0.5

Both controls that prove the metric can fail are in the test suite:
deleting every ``F.SilkS`` polygon from ``bitcoin_b_16mm`` takes UNDRAWN from
0.197 % to 29.152 %, and shifting every polygon by +-1 px raises it in both
axes with the minimum at zero shift. The rasteriser was cross-checked against
``kicad-cli 10.0.0 fp export svg`` plus cairosvg at IoU 0.9759-0.9971.

THE EMPTY BAND. Measured across the shipped library and the repaired rebuild:
every good footprint lands in 0.185-2.310 % and every mutilated one in
11.964-29.551 %. Nothing has ever landed between 2.31 and 11.96. FAIL at 5.0
and WARN at 3.0 sit inside that gap with room on both sides -- they are not a
tolerance somebody liked, they are the middle of an empty region.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import numpy as np
from PIL import Image

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from emit_art import crop_to_content, rasterise_svg   # noqa: E402

# --- thresholds -------------------------------------------------------------
UNDRAWN_FAIL_PCT = 5.0
UNDRAWN_WARN_PCT = 3.0
# A cluster smaller than this is antialias residue, not a region of the design.
CLUSTER_MIN_SHARE = 0.005
CLUSTER_DE = 10.0
INDISTINGUISHABLE_FAIL_PCT = 5.0
ILLEGIBLE_FAIL_PCT = 1.0

_XY = re.compile(r"\(xy\s+(-?[\d.eE+]+)\s+(-?[\d.eE+]+)\)")
_LAYER = re.compile(r"\(layer\s+\"([^\"]+)\"\)")


# ---------------------------------------------------------------------------
# reading a .kicad_mod as text
# ---------------------------------------------------------------------------

def _blocks(txt: str, head: str):
    """Every balanced ``(head ...)`` s-expression in `txt`, as substrings.

    Balanced parens rather than "to the end of the line": the emitter happens
    to write one fp_poly per line today, and a metric that silently measures
    less than the whole file the day that changes is the bitten pattern again.
    """
    out = []
    i = 0
    pat = "(" + head
    while True:
        s = txt.find(pat, i)
        if s < 0:
            return out
        nxt = txt[s + len(pat):s + len(pat) + 1]
        if nxt and (nxt.isalnum() or nxt == "_"):
            i = s + 1                              # (fp_poly_thing, not fp_poly
            continue
        depth, j, in_str = 0, s, False
        while j < len(txt):
            c = txt[j]
            if in_str:
                if c == "\\":
                    j += 2
                    continue
                if c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    out.append(txt[s:j + 1])
                    break
            j += 1
        i = j + 1


def polys_of(mod_path) -> list[tuple[np.ndarray, str]]:
    """-> [(pts_mm (N,2), layer)] for every fp_poly in the footprint text."""
    txt = pathlib.Path(mod_path).read_text(encoding="utf-8")
    out = []
    for seg in _blocks(txt, "fp_poly"):
        pts = [(float(a), float(b)) for a, b in _XY.findall(seg)]
        lay = _LAYER.search(seg)
        if len(pts) >= 3:
            out.append((np.array(pts, dtype=np.float64),
                        lay.group(1) if lay else "?"))
    return out


def fill(poly_px: np.ndarray, H: int, W: int) -> np.ndarray:
    """Even-odd scan-line fill of one ring, sampled at pixel centres.

    EVEN-ODD within one fp_poly and OR across fp_polys, which is what KiCad
    does: a keyhole slit cut into a polygon must leave the hole empty, and two
    separate polygons that overlap are both present.
    """
    out = np.zeros((H, W), dtype=bool)
    x, y = poly_px[:, 0], poly_px[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    r0 = max(0, int(np.floor(y.min())))
    r1 = min(H - 1, int(np.ceil(y.max())))
    cols = np.arange(W, dtype=np.float64)
    for r in range(r0, r1 + 1):
        st = (y > r) != (y2 > r)
        if not st.any():
            continue
        ya, yb = y[st], y2[st]
        xa, xb = x[st], x2[st]
        xi = np.sort(xa + (r - ya) * (xb - xa) / (yb - ya))
        k = len(xi) - np.searchsorted(xi, cols, side="right")
        out[r] = (k & 1).astype(bool)
    return out


def coverage(mod_path, report) -> tuple[np.ndarray, dict]:
    """-> (union coverage bool (H,W), {layer: bool (H,W)}), in source pixels."""
    W, H = report["input_px"]
    mmpx = float(report["mm_per_px"])
    ox = -float(report["width_mm"]) / 2.0
    oy = -float(report["height_mm"]) / 2.0
    cover = np.zeros((H, W), dtype=bool)
    per_layer: dict[str, np.ndarray] = {}
    for pts, lay in polys_of(mod_path):
        q = np.empty_like(pts)
        q[:, 0] = (pts[:, 0] - ox) / mmpx - 0.5
        q[:, 1] = (pts[:, 1] - oy) / mmpx - 0.5
        f = fill(q, H, W)
        cover |= f
        if lay not in per_layer:
            per_layer[lay] = np.zeros((H, W), dtype=bool)
        per_layer[lay] |= f
    return cover, per_layer


# ---------------------------------------------------------------------------
# the source, loaded the way the emitter loads it
# ---------------------------------------------------------------------------

def load_source(src_path, raster_width: int = 1200, crop: bool = True):
    p = pathlib.Path(src_path)
    if p.suffix.lower() == ".svg":
        img, _tool = rasterise_svg(p, raster_width)
    else:
        img = Image.open(p).convert("RGBA")
    if crop:
        img, _box = crop_to_content(img)
    return img.convert("RGBA")


# ---------------------------------------------------------------------------
# C9.1 UNDRAWN SOURCE INK
# ---------------------------------------------------------------------------

def undrawn_ink(src_path, mod_path, report, *, raster_width: int = 1200,
                crop: bool = True, min_alpha: int = 128) -> dict:
    """Source ink the emitted polygons do not cover, as a share of source ink."""
    img = load_source(src_path, raster_width, crop)
    W, H = img.width, img.height
    if [W, H] != list(report["input_px"]):
        raise ValueError(
            f"{pathlib.Path(mod_path).name}: source rasterises to {W}x{H} but "
            f"the report declares {report['input_px']}. The overlay would be "
            f"measuring two different pictures, so it refuses rather than "
            f"reporting a number for the wrong alignment")

    cover, per_layer = coverage(mod_path, report)
    alpha = np.asarray(img)[..., 3]
    opaque = alpha >= min_alpha
    tot = int(opaque.sum())
    if tot == 0:
        raise ValueError(f"{src_path}: no opaque source pixels")

    undrawn = opaque & ~cover
    # A tone on an inner layer does not appear on the finished board at all, so
    # the surface-only variant is what a person looking at the part would see.
    surf = np.zeros((H, W), dtype=bool)
    for lay, f in per_layer.items():
        if not lay.startswith("In"):
            surf |= f

    pct = 100.0 * int(undrawn.sum()) / tot
    return {
        "metric": "undrawn_ink",
        "footprint": pathlib.Path(mod_path).stem,
        "source": pathlib.Path(src_path).name,
        "px": [W, H],
        "opaque_px": tot,
        "covered_px": int((opaque & cover).sum()),
        "undrawn_px": int(undrawn.sum()),
        "undrawn_pct": round(pct, 3),
        "undrawn_pct_surface_only": round(
            100.0 * int((opaque & ~surf).sum()) / tot, 3),
        # Reported BESIDE undrawn ink and never netted against it: a "fix"
        # that just fattens every stroke would otherwise buy a better
        # fidelity number by drawing over the background.
        "overdrawn_px": int((~opaque & cover).sum()),
        "overdrawn_pct_of_ink": round(100.0 * int((~opaque & cover).sum()) / tot, 3),
        "layers": sorted(per_layer),
        "inner_layers": sorted(l for l in per_layer if l.startswith("In")),
        "verdict": ("FAIL" if pct >= UNDRAWN_FAIL_PCT else
                    "WARN" if pct >= UNDRAWN_WARN_PCT else "PASS"),
        "fail_at_pct": UNDRAWN_FAIL_PCT, "warn_at_pct": UNDRAWN_WARN_PCT,
    }


# ---------------------------------------------------------------------------
# C9.2 INDISTINGUISHABLE INK
# ---------------------------------------------------------------------------

def _clusters(img, min_alpha=128):
    """Source colour clusters, via the repo's own ingest clusterer.

    prep_assets.colour_census is what tools/prep_assets.py uses to decide two
    colours are the same ink. Reusing it is deliberate: it reads the SOURCE,
    so it is independent of the emitter, and a second clusterer here would be
    a second opinion that is really the same opinion written twice.
    """
    import prep_assets
    arr = np.asarray(img.convert("RGBA"))
    rgb = arr[..., :3]
    ink = arr[..., 3] >= min_alpha
    cen = prep_assets.colour_census(rgb, ink, CLUSTER_DE)
    return [c for c in cen["clusters"] if c["area_fraction"] >= CLUSTER_MIN_SHARE]


def _lab(rgb):
    from w0_spike import srgb_to_lab
    return srgb_to_lab(np.asarray(rgb, dtype=np.uint8))


def indistinguishable_ink(src_path, mod_path, report, tmap=None, *,
                          raster_width: int = 1200, crop: bool = True,
                          min_alpha: int = 128) -> dict:
    """Two visibly different source colours that came out on the same layers."""
    img = load_source(src_path, raster_width, crop)
    cover, per_layer = coverage(mod_path, report)
    arr = np.asarray(img)
    rgbv, alpha = arr[..., :3], arr[..., 3]
    opaque = alpha >= min_alpha

    layer_names = sorted(per_layer)
    sig = np.zeros(opaque.shape, dtype=np.int64)
    for k, lay in enumerate(layer_names):
        sig |= (per_layer[lay].astype(np.int64) << k)

    rows = []
    for c in _clusters(img, min_alpha):
        crgb = tuple(int(v) for v in c["rgb"])
        # pixels of this cluster: within CLUSTER_DE of its centroid in Lab
        d = np.linalg.norm(_lab(rgbv) - _lab(np.array(crgb)), axis=-1)
        sel = opaque & (d <= CLUSTER_DE)
        if not sel.any():
            continue
        vals, counts = np.unique(sig[sel], return_counts=True)
        modal = int(vals[int(np.argmax(counts))])
        names = tuple(layer_names[k] for k in range(len(layer_names))
                      if modal >> k & 1)
        rows.append({"hex": c["hex"], "rgb": list(crgb),
                     "share": round(100.0 * c["area_fraction"], 3),
                     "layers": list(names), "empty": not names})

    merged = []
    illegal = 0.0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            if a["empty"] or b["empty"]:
                continue           # that is C9.1's business, not this metric's
            if tuple(a["layers"]) != tuple(b["layers"]):
                continue
            de = float(np.linalg.norm(_lab(np.array(a["rgb"]))
                                      - _lab(np.array(b["rgb"]))))
            if de < CLUSTER_DE:
                continue           # the same ink, correctly one tone
            ok = _merge_declared(tmap, a["hex"], b["hex"])
            smaller = min(a["share"], b["share"])
            merged.append({"a": a["hex"], "b": b["hex"], "dE76": round(de, 1),
                           "layers": a["layers"], "share": smaller,
                           "declared": ok})
            if not ok:
                illegal += smaller

    return {
        "metric": "indistinguishable_ink",
        "footprint": pathlib.Path(mod_path).stem,
        "clusters": rows, "collisions": merged,
        "indistinguishable_pct": round(illegal, 3),
        "declared_pct": round(sum(m["share"] for m in merged if m["declared"]), 3),
        "verdict": "FAIL" if illegal >= INDISTINGUISHABLE_FAIL_PCT else "PASS",
        "fail_at_pct": INDISTINGUISHABLE_FAIL_PCT,
    }


def _merge_declared(tmap, ha, hb) -> bool:
    if tmap is None:
        return False
    if tmap.by_hex(ha) is None or tmap.by_hex(hb) is None:
        return False
    return tmap.merge_declared(ha, hb)


# ---------------------------------------------------------------------------
# C9.3 ILLEGIBLE INK
# ---------------------------------------------------------------------------

def illegible_ink(mod_path, report, palette, tmap=None) -> dict:
    """Ink drawn in a tone too close to the board for anyone to see it.

    This is the gate that stops the FIFTH instance of the bitten pattern, and
    the pattern would have arrived inside the fix. Once T5 is ineligible and
    inner tones are excluded, black ink is STRUCTURALLY forced onto T6 -- it is
    the only remaining dark tone. The undrawn-ink metric then reads 1-2 %,
    because polygons genuinely exist, while the limbs are drawn in a tone 10 L*
    from the board on purple and 7.87 L* on black. tools/texture_board.py lines
    2373-2376 says of exactly that separation that it "reads as a sheen and not
    as a graphic".

    So this metric reads the PALETTE TABLE and the EMITTED LAYER SET, and never
    the emitter's report. It fails today's black palette for any ink bound to
    T6. That it fails on a shipped configuration is the evidence that it can.
    """
    from palette import LEGIBLE_MIN_DL, LEGIBLE_WARN_DL, TONE_IDS
    from coupon_blocks import TONE_RECIPE

    recipe = {k.split("_", 1)[0]: frozenset(v) for k, v in TONE_RECIPE.items()}
    _cover, per_layer = coverage(mod_path, report)
    if not per_layer:
        return {"metric": "illegible_ink",
                "footprint": pathlib.Path(mod_path).stem,
                "tones": [], "illegible_pct": 0.0, "warn_pct": 0.0,
                "verdict": "PASS", "note": "no fp_poly geometry"}

    layer_names = sorted(per_layer)
    stack = np.stack([per_layer[l] for l in layer_names], axis=0)
    any_cov = stack.any(axis=0)
    total = int(any_cov.sum())

    # Every distinct layer-set that occurs, matched against the recipe table.
    sig = np.zeros(any_cov.shape, dtype=np.int64)
    for k in range(len(layer_names)):
        sig |= (stack[k].astype(np.int64) << k)
    vals, counts = np.unique(sig[any_cov], return_counts=True)

    rows, illegible, warn = [], 0.0, 0.0
    for v, n in zip(vals.tolist(), counts.tolist()):
        names = frozenset(layer_names[k] for k in range(len(layer_names))
                          if v >> k & 1)
        tid = next((t for t in TONE_IDS if recipe.get(t) == names), None)
        share = 100.0 * n / max(total, 1)
        row = {"layers": sorted(names), "tone": tid, "share_pct": round(share, 3)}
        if tid is not None:
            dl = palette.dl_to_board(tid)
            row["dl_to_board"] = round(dl, 2)
            declared = _legibility_declared(tmap, tid)
            row["declared"] = declared
            if share >= ILLEGIBLE_FAIL_PCT and abs(dl) < LEGIBLE_MIN_DL:
                row["status"] = "ILLEGIBLE" + (" (declared)" if declared else "")
                if not declared:
                    illegible += share
            elif share >= ILLEGIBLE_FAIL_PCT and abs(dl) < LEGIBLE_WARN_DL:
                row["status"] = "MARGINAL"
                warn += share
            else:
                row["status"] = "ok"
        else:
            row["status"] = "unrecognised layer set"
        rows.append(row)

    return {
        "metric": "illegible_ink",
        "footprint": pathlib.Path(mod_path).stem,
        "drawn_px": total, "tones": rows,
        "illegible_pct": round(illegible, 3),
        "warn_pct": round(warn, 3),
        "legible_min_dl": LEGIBLE_MIN_DL, "legible_warn_dl": LEGIBLE_WARN_DL,
        "verdict": ("FAIL" if illegible >= ILLEGIBLE_FAIL_PCT else
                    "WARN" if warn >= ILLEGIBLE_FAIL_PCT else "PASS"),
    }


def _legibility_declared(tmap, tid) -> bool:
    if tmap is None:
        return False
    bound = [i for i in tmap.inks if i.tone == tid]
    return bool(bound) and all(i.legibility == "declared" for i in bound)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):                                     # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(
        description="Acceptance metrics for an emitted footprint. Renders the "
                    "footprint from its OWN polygons and overlays it on the "
                    "source.")
    ap.add_argument("--source", required=True)
    ap.add_argument("--mod", required=True)
    ap.add_argument("--report", required=True, help="emit_art --report-json")
    ap.add_argument("--tone-map", default=None)
    ap.add_argument("--palette-mask", default=None,
                    help="override the palette: tag on the footprint wins")
    ap.add_argument("--raster-width", type=int, default=1200)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    rep = json.loads(pathlib.Path(a.report).read_text(encoding="utf-8"))
    tmap = None
    if a.tone_map:
        from tone_map import ToneMap
        tmap = ToneMap.load(a.tone_map)

    import palette as pal
    txt = pathlib.Path(a.mod).read_text(encoding="utf-8")
    m = re.search(r'\(tags\s+"([^"]*)"\)', txt)
    p = pal.from_tag(m.group(1) if m else "", allow_provisional=True)
    if p is None:
        p = pal.palette_for(a.palette_mask or (tmap.mask if tmap else "black"),
                            allow_provisional=True)

    out = {
        "undrawn": undrawn_ink(a.source, a.mod, rep, raster_width=a.raster_width),
        "indistinguishable": indistinguishable_ink(
            a.source, a.mod, rep, tmap, raster_width=a.raster_width),
        "illegible": illegible_ink(a.mod, rep, p, tmap),
        "palette": p.tag(),
    }
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        u, i, g = out["undrawn"], out["indistinguishable"], out["illegible"]
        print(f"{u['footprint']}  [{out['palette']}]")
        print(f"  UNDRAWN          {u['undrawn_pct']:>7.3f} %  {u['verdict']}"
              f"   (overdrawn {u['overdrawn_pct_of_ink']:.3f} % of ink)")
        print(f"  INDISTINGUISHABLE{i['indistinguishable_pct']:>7.3f} %  "
              f"{i['verdict']}   (declared {i['declared_pct']:.3f} %)")
        print(f"  ILLEGIBLE        {g['illegible_pct']:>7.3f} %  {g['verdict']}"
              f"   (marginal {g['warn_pct']:.3f} %)")
        print(f"  layers: {' '.join(u['layers'])}")
    worst = max(_rank(out["undrawn"]["verdict"]),
                _rank(out["indistinguishable"]["verdict"]),
                _rank(out["illegible"]["verdict"]))
    return 1 if worst >= 2 else 0


def _rank(v):                                            # pragma: no cover
    return {"PASS": 0, "WARN": 1, "FAIL": 2}.get(v, 0)


if __name__ == "__main__":                               # pragma: no cover
    raise SystemExit(main())
