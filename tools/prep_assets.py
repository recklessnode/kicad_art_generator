#!/usr/bin/env python3
"""Ingest stage: normalise source art into a conversion-ready asset set.

This is deliberately NOT an emitter. It answers the questions that decide what
the emitter can do, and it writes the cleaned-up inputs the emitter will read:

  1. Content bbox + crop.      The emission formula is a Letter artboard with
                               ~0.4 % of it inked. Uncropped it converts to a
                               mostly-empty page.
  2. Fill inheritance census.  Resolved through the ancestor chain with a real
                               XML parse. This is the specific defect that made
                               the April pipeline drop 16 of 28 paths in the
                               Reckless logo -- quantified per asset here so the
                               regression is measurable rather than anecdotal.
  3. Colour census.            Distinct colours and their area fractions, in
                               CIELAB clusters rather than exact RGB, because
                               rgb(1,190,219) and rgb(20,191,219) are one cyan.
  4. Tone recommendation.      Per asset per target size, from the colour census
                               and the minimum feature sizes in
                               docs/pcb-palette.md. A 12 mm badge and a 50 mm
                               badge do not want the same tone set.

Outputs land in <repo>/assets/:

    assets/manifest.json          everything below, machine-readable
    assets/normalised/<id>.svg    cropped vector, text flattened to paths
    assets/normalised/<id>.png    cropped raster, matte background -> alpha
    assets/raster/<id>.png        canonical RGBA raster for the quantiser

Nothing is dropped quietly. Every asset records the ink-mask rule that fired,
a crop round-trip check, and an explicit list of colour clusters that cannot be
fabricated at each size along with the cluster each must merge into.

Usage:
    python3 tools/prep_assets.py                    # all assets -> <repo>/assets
    python3 tools/prep_assets.py --only reckless_color bitcoin_b
    python3 tools/prep_assets.py --sizes 12 25 50 --delta-e 12
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from lxml import etree

# Reuse the perceptual machinery from the W0 spike rather than growing a second
# copy of it. TONES is only used here to report which palette entry each source
# cluster lands nearest -- assignment proper is the quantiser's job.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from w0_spike import TONES, srgb_to_lab  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

SVG_NS = "http://www.w3.org/2000/svg"

# ---------------------------------------------------------------------------
# Fabrication limits. Source: docs/pcb-palette.md, "Practical limits".
# ---------------------------------------------------------------------------
MIN_FEATURE_MM = {
    "silkscreen": 0.15,
    "mask": 0.10,
    "copper": 0.10,
    # The palette doc says buried tones (T4/T7) blur through 0.1 mm of prepreg
    # and are "fields and broad shapes, not linework". It gives no number.
    # 0.50 mm is this tool's assumption, recorded so it can be argued with.
    "buried": 0.50,
}
SILK_MIN = MIN_FEATURE_MM["silkscreen"]
ETCH_MIN = min(MIN_FEATURE_MM["mask"], MIN_FEATURE_MM["copper"])

DEFAULT_SIZES_MM = (12.0, 25.0, 50.0)

# Analysis / output raster resolution, long edge in px. Vector sources are
# rendered at this; raster sources keep their native resolution capped here,
# because upsampling a 312 px PNG invents detail that is not in the source.
RASTER_LONG_EDGE = 1600

# An SVG raster whose transparent fraction is below this is treated as having a
# painted background rather than a transparent one. bitcoin_b.svg is a full
# bleed rounded rect: 1.3 % transparent, all of it corner rounding.
TRANSPARENT_MARGIN_MIN = 0.02

# Elements whose subtrees are definitions, not rendered paint.
NON_RENDERED = {
    "defs", "clipPath", "mask", "marker", "symbol", "pattern", "filter",
    "font", "font-face", "missing-glyph", "glyph", "linearGradient",
    "radialGradient", "metadata", "title", "desc",
}
SHAPE_TAGS = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

ONEDRIVE_CANDIDATES = [
    Path("/mnt/c/Users/prael/OneDrive - blockscale.solutions/Clients/Reckless Systems"),
    Path("C:/Users/prael/OneDrive - blockscale.solutions/Clients/Reckless Systems"),
    Path.home() / "OneDrive - blockscale.solutions/Clients/Reckless Systems",
]

ART = "Hardware Designs/1-ASIC Satoshi Starter/Art Assets"
LOGO = "Business Docs/Logo-Library/Logo-Library"
MFB = ("Hardware Designs/1-ASIC Satoshi Starter/SatoshiStarter/ZIP - MFB Logos/"
       "Brand-Book-main/Badges/Nodes")
MFB_WEB = ("Hardware Designs/1-ASIC Satoshi Starter/SatoshiStarter/"
           "ZIP - MFB Logos/from-website")

# role:
#   deliverable -- art we intend to convert
#   control     -- same artwork in a variant that isolates a known defect
# licence: recorded because this repo is headed for a public GPLv3 /
#   CERN-OHL-S release and third-party art must not travel with it silently.
#
#   My First Bitcoin granted WRITTEN CONSENT (2026-08-17) to place their mark on
#   the SatoshiStarter; those boards go to MFB's educator network. That consent
#   is for the BOARD, and it does not make the source files redistributable --
#   they still must never be committed to this repository. assets/ stays
#   gitignored. The originals are archived in the private SatoshiStarter repo
#   under art-assets/, with a sha256 manifest; see its README.md.
ASSETS = [
    dict(id="little_satoshi", src=f"{ART}/Little Satoshi.png", root="onedrive",
         role="deliverable", key_shadow=True, licence="third-party (MFB Satoshi) -- consent for SatoshiStarter, NOT redistributable"),
    dict(id="satoshi_miner", src=f"{ART}/Satoshi Miner - Transparent.png", root="onedrive",
         role="deliverable", key_shadow=True, licence="third-party (MFB Satoshi) -- consent for SatoshiStarter, NOT redistributable"),
    dict(id="satoshi_miner_matte", src=f"{ART}/Satoshi Miner.png", root="onedrive",
         role="control", key_shadow=True, licence="third-party (MFB Satoshi) -- consent for SatoshiStarter, NOT redistributable",
         note="Same artwork as satoshi_miner with a baked white matte. Ground "
              "truth for the matte-detection path: its recovered alpha should "
              "match satoshi_miner's real alpha."),
    dict(id="satoshi_points", src=f"{ART}/Satoshi Points.png", root="onedrive",
         role="deliverable", key_shadow=True, licence="third-party (MFB Satoshi) -- consent for SatoshiStarter, NOT redistributable"),
    dict(id="bitcoin_emission_formula", src=f"{ART}/Bitcoin Emission Formula.svg",
         root="onedrive", role="deliverable", flatten_text=True,
         licence="own work (LibreOffice Math export)"),
    dict(id="reckless_color", src=f"{LOGO}/Color/RecklessSystemsLogoColor.svg",
         root="onedrive", role="deliverable", licence="owner's mark"),
    dict(id="reckless_black", src=f"{LOGO}/Black/RecklessSystemsLogoBlack.svg",
         root="onedrive", role="deliverable", licence="owner's mark"),
    dict(id="reckless_white", src=f"{LOGO}/White/RecklessSystemsLogoWhite.svg",
         root="onedrive", role="control", licence="owner's mark",
         note="17 paths, all explicit fill. A/B control against reckless_black "
              "(17 paths, 100 % inherited)."),
    dict(id="reckless_white_color", src=f"{LOGO}/Color/RecklessSystemsLogoWhiteColor.svg",
         root="onedrive", role="control", licence="owner's mark",
         note="28 paths, all explicit fill. A/B control against reckless_color "
              "(28 paths, 57 % inherited)."),
    dict(id="mfb_node_full", src=f"{MFB}/Node Badge_full node.svg", root="onedrive",
         role="deliverable", licence="third-party (My First Bitcoin) -- consent for SatoshiStarter, NOT redistributable",
         note="Illustrator export with an internal DTD subset; see "
              "tools/svg_entities.py for why cairosvg could not read it."),
    dict(id="mfb_node_light", src=f"{MFB}/Node Badge_light node.svg", root="onedrive",
         role="deliverable", licence="third-party (My First Bitcoin) -- consent for SatoshiStarter, NOT redistributable",
         note="Sibling of mfb_node_full."),
    dict(id="mfb_lockup_white", src=f"{MFB_WEB}/logo-mfb-white.svg", root="onedrive",
         role="deliverable", licence="third-party (My First Bitcoin) -- consent for SatoshiStarter, NOT redistributable",
         note="The official WHITE lockup from myfirstbitcoin.org, fetched "
              "2026-08-17; see PROVENANCE.txt beside it. 32 paths, one fill "
              "#F6F6F6, no strokes. MFB's identity is a white mark on a purple "
              "field, so on the purple baseline this quantises to a single tone: "
              "T1 silk for the mark, T5 bare mask for the field, and the "
              "Bitcoin B is a KNOCKOUT hole in the silk band. The Brand-Book "
              "zip has no white vector lockup -- only raster PNG and an "
              "orange/near-black .ai."),
    dict(id="bitcoin_b", src="examples/bitcoin_b.svg", root="repo",
         role="deliverable", licence="public domain (Bitcoin logo)"),
]


def find_source_root(override: str | None) -> Path:
    if override:
        p = Path(override)
        if not p.is_dir():
            sys.exit(f"--source-root does not exist: {p}")
        return p
    for c in ONEDRIVE_CANDIDATES:
        if c.is_dir():
            return c
    sys.exit("Could not locate the Reckless Systems OneDrive root; pass --source-root.")


# ---------------------------------------------------------------------------
# SVG fill inheritance
# ---------------------------------------------------------------------------

def parse_style(text: str | None) -> dict:
    """Split a CSS style attribute into declarations. Not a regex for 'fill='."""
    out = {}
    if not text:
        return out
    for decl in text.split(";"):
        if ":" not in decl:
            continue
        k, _, v = decl.partition(":")
        out[k.strip().lower()] = v.strip()
    return out


def localname(el) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return "#comment"
    return tag.rsplit("}", 1)[-1]


def own_fill(el):
    """(value, syntax) for a fill declared on this element, else (None, None).

    CSS style wins over the presentation attribute -- that is the cascade, and
    getting it backwards is how you mis-read artwork that carries both.
    """
    css = parse_style(el.get("style")).get("fill")
    if css and css.lower() != "inherit":
        return css, "css"
    attr = el.get("fill")
    if attr and attr.lower() != "inherit":
        return attr, "attribute"
    return None, None


def has_stroke(el) -> bool:
    st = parse_style(el.get("style")).get("stroke") or el.get("stroke")
    return bool(st) and st.lower() != "none"


def analyse_svg_fills(path: Path) -> dict:
    """Resolve fill for every painted leaf through its ancestor chain.

    Counts, per asset:
      explicit_css / explicit_attribute  -- declared on the element itself
      inherited_from_ancestor            -- a <g> or <svg> above it declares one
      inherited_initial                  -- nothing in the chain does, so the
                                            SVG initial value (black) applies

    The last two are both invisible to an extractor that reads the element only.
    Together they are the number that matters.
    """
    tree = etree.parse(str(path))
    root = tree.getroot()

    leaves = []
    for el in root.iter():
        name = localname(el)
        if name in NON_RENDERED or name == "#comment":
            continue
        # Skip anything living inside a definition subtree.
        if any(localname(a) in NON_RENDERED for a in el.iterancestors()):
            continue
        if name in SHAPE_TAGS:
            leaves.append(el)
        elif name in ("text", "tspan"):
            # The paint leaf is the innermost span actually carrying glyphs.
            if (el.text or "").strip() and not any(
                localname(c) == "tspan" for c in el
            ):
                leaves.append(el)

    stats = Counter()
    by_tag = Counter()
    resolved = Counter()
    inherit_sources = Counter()
    stroke_only = 0

    for el in leaves:
        by_tag[localname(el)] += 1
        val, syntax = own_fill(el)
        if val is not None:
            stats["explicit_" + ("css" if syntax == "css" else "attribute")] += 1
            origin = "self"
        else:
            for anc in el.iterancestors():
                if localname(anc) == "#comment":
                    continue
                val, syntax = own_fill(anc)
                if val is not None:
                    break
            if val is not None:
                stats["inherited_from_ancestor"] += 1
                inherit_sources[f"<{localname(anc)}> {syntax}"] += 1
                origin = "ancestor"
            else:
                # SVG 1.1: the initial value of 'fill' is black.
                val, origin = "black", "initial"
                stats["inherited_initial"] += 1

        val_n = val.strip().lower()
        resolved[val_n] += 1
        if val_n == "none":
            stats["fill_none"] += 1
            if has_stroke(el):
                stroke_only += 1

    total = len(leaves)
    inherited = stats["inherited_from_ancestor"] + stats["inherited_initial"]
    return {
        "painted_leaves": total,
        "by_tag": dict(sorted(by_tag.items())),
        "explicit_css_fill": stats["explicit_css"],
        "explicit_attribute_fill": stats["explicit_attribute"],
        "inherited_from_ancestor": stats["inherited_from_ancestor"],
        "inherited_initial_black": stats["inherited_initial"],
        "inherited_total": inherited,
        "inherited_pct": round(100.0 * inherited / total, 1) if total else 0.0,
        "inherit_sources": dict(inherit_sources),
        "fill_none": stats["fill_none"],
        "stroke_only_shapes": stroke_only,
        "resolved_fill_values": dict(resolved.most_common()),
        "use_elements": sum(1 for el in root.iter() if localname(el) == "use"),
    }


# ---------------------------------------------------------------------------
# Rasterising
# ---------------------------------------------------------------------------

SHADOW_CHROMA_MAX = 10.0   # same neutrality bar the detector uses
SHADOW_L_MIN = 55.0        # above the dark outlines
SHADOW_L_MAX = 96.0        # below paper white (the assets' whites sit at 99-100)


def key_drop_shadow(arr: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, dict]:
    """Delete a soft drop shadow from an RGBA raster. -> (new mask, info).

    All three MFB Satoshi assets are drawn standing on a soft grey ground
    ellipse. It is a light neutral -- L* 79-85, chroma ~0 -- and the palette has
    nothing between silk white and black mask, so the quantiser rounds the whole
    ellipse to T1 and fabricates it as a hard white silkscreen blob under the
    character's feet. A soft shadow cannot be printed; the honest rendering is
    to remove it, which is what the ingest notes ask for.

    The rule is photometric and matches the detector in check_census(): a
    near-neutral pixel that is neither the dark line work nor paper white. It is
    deliberately NOT a shape or position test -- nothing here assumes the shadow
    is an ellipse or that it sits at the bottom.

    Selection is by colour alone, then restricted to 8-connected components that
    contain a solidly-in-band core, so an isolated antialias pixel on a black
    outline is not mistaken for shadow. Everything removed is counted and
    returned; a caller that finds the count surprising should look at the art.
    """
    rgb = arr[..., :3]
    lab = srgb_to_lab(rgb.reshape(-1, 3)).reshape(rgb.shape)
    L = lab[..., 0]
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    band = (mask & (chroma < SHADOW_CHROMA_MAX)
            & (L > SHADOW_L_MIN) & (L < SHADOW_L_MAX))
    info = {
        "rule": (f"near-neutral (chroma < {SHADOW_CHROMA_MAX:g}) with "
                 f"{SHADOW_L_MIN:g} < L* < {SHADOW_L_MAX:g}: lighter than the "
                 f"line work, darker than paper white"),
        "candidate_px": int(band.sum()),
        "removed_px": 0,
        "components_removed": 0,
        "components_rejected_as_fringe": 0,
    }
    if not band.any():
        info["detail"] = "no drop-shadow pixels found; raster unchanged"
        return mask, info

    # A real shadow has a solid core; an antialias fringe never does. Keep only
    # components holding at least one pixel comfortably inside the band.
    core = band & (L > SHADOW_L_MIN + 5) & (L < SHADOW_L_MAX - 5)
    lbl, n = _label8(band)
    keep = np.zeros(n + 1, dtype=bool)
    if n:
        core_labels = np.unique(lbl[core])
        keep[core_labels[core_labels > 0]] = True
    remove = keep[lbl]
    info["removed_px"] = int(remove.sum())
    info["components_removed"] = int(keep.sum())
    info["components_rejected_as_fringe"] = int(n - keep.sum())
    info["detail"] = (f"{info['removed_px']:,} px in "
                      f"{info['components_removed']} component(s) deleted")
    return mask & ~remove, info


def _label8(m: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected component labelling. Hand-rolled union-find; scipy is not
    available in this environment and one flood per component is too slow on a
    1600 px raster."""
    h, w = m.shape
    lbl = np.zeros((h, w), dtype=np.int32)
    parent: list[int] = [0]

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    nxt = 1
    for y in range(h):
        row = m[y]
        if not row.any():
            continue
        for x in np.nonzero(row)[0]:
            near = []
            if x > 0 and lbl[y, x - 1]:
                near.append(lbl[y, x - 1])
            if y > 0:
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w and lbl[y - 1, xx]:
                        near.append(lbl[y - 1, xx])
            if near:
                a = min(near)
                lbl[y, x] = a
                for b in near:
                    union(a, b)
            else:
                lbl[y, x] = nxt
                parent.append(nxt)
                nxt += 1
    if nxt == 1:
        return lbl, 0
    roots = np.array([find(i) for i in range(nxt)], dtype=np.int32)
    uniq, compact = np.unique(roots[1:], return_inverse=True)
    remap = np.zeros(nxt, dtype=np.int32)
    remap[1:] = compact + 1
    return remap[lbl], len(uniq)


def render_svg(path: Path, long_edge: int) -> Image.Image:
    import cairosvg
    from svg_entities import read_svg_bytes
    # See tools/svg_entities.py: Illustrator's internal DTD subset is rejected
    # by defusedxml under cairosvg. lxml (used everywhere else in this file)
    # resolves entities itself, so only this call site needs the pre-pass.
    data, _ = read_svg_bytes(path)
    w, h = svg_viewbox_size(path)
    if w >= h:
        png = cairosvg.svg2png(bytestring=data, output_width=long_edge,
                               url=str(path))
    else:
        png = cairosvg.svg2png(bytestring=data, output_height=long_edge,
                               url=str(path))
    import io
    return Image.open(io.BytesIO(png)).convert("RGBA")


LENGTH_RE = re.compile(r"^\s*([-+0-9.eE]+)\s*([a-z%]*)\s*$")


def parse_length(text: str | None):
    if not text:
        return None, None
    m = LENGTH_RE.match(text)
    if not m:
        return None, None
    try:
        return float(m.group(1)), (m.group(2) or "").lower()
    except ValueError:
        return None, None


def svg_viewbox(path: Path):
    root = etree.parse(str(path)).getroot()
    vb = root.get("viewBox")
    if vb:
        parts = [float(v) for v in re.split(r"[\s,]+", vb.strip()) if v]
        if len(parts) == 4:
            return tuple(parts)
    w, _ = parse_length(root.get("width"))
    h, _ = parse_length(root.get("height"))
    if w and h:
        return (0.0, 0.0, w, h)
    raise ValueError(f"{path.name}: no viewBox and no absolute width/height")


def svg_viewbox_size(path: Path):
    _, _, w, h = svg_viewbox(path)
    return w, h


def svg_units_per_mm(path: Path):
    """User units per mm, if the document declares a physical size. Else None."""
    root = etree.parse(str(path)).getroot()
    _, _, vbw, _ = svg_viewbox(path)
    w, unit = parse_length(root.get("width"))
    if w is None or unit not in ("mm", "cm", "in", "pt", "px", ""):
        return None
    mm = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0}.get(unit)
    if mm is None:
        return None
    return vbw / (w * mm)


# ---------------------------------------------------------------------------
# Ink mask -- what counts as content
# ---------------------------------------------------------------------------

def _row_runs_fill(cur_row, mask_row):
    """Propagate True along contiguous runs of mask_row. One dimension of a
    4-connected flood; alternate with the column version to fixpoint."""
    if not mask_row.any():
        return cur_row
    run_id = np.cumsum(~mask_row)
    seeded = np.bincount(run_id[cur_row & mask_row],
                         minlength=int(run_id.max()) + 2) > 0
    out = np.zeros_like(cur_row)
    out[mask_row] = seeded[run_id[mask_row]]
    return out


def flood_from_border(mask: np.ndarray) -> np.ndarray:
    """Region of `mask` reachable from the image border (4-connected).

    Used to separate an exterior matte from interior pixels that merely share
    its colour. Stripping matte by colour alone would eat a character's white
    eyes along with the background; this does not.
    """
    cur = np.zeros_like(mask)
    cur[0, :] = mask[0, :]
    cur[-1, :] = mask[-1, :]
    cur[:, 0] = mask[:, 0]
    cur[:, -1] = mask[:, -1]
    while True:
        before = int(cur.sum())
        for y in range(cur.shape[0]):
            cur[y] = _row_runs_fill(cur[y] | (cur[y - 1] & mask[y] if y else False),
                                    mask[y])
        for y in range(cur.shape[0] - 2, -1, -1):
            cur[y] = _row_runs_fill(cur[y] | (cur[y + 1] & mask[y]), mask[y])
        for x in range(cur.shape[1]):
            cur[:, x] = _row_runs_fill(cur[:, x], mask[:, x])
        if int(cur.sum()) == before:
            return cur


def ink_mask(rgba: np.ndarray, force_rule: str | None = None
             ) -> tuple[np.ndarray, dict]:
    """Content mask plus a record of which rule produced it.

    Three rules, in order:
      alpha        -- the source has a real transparent margin. Trust it.
      matte        -- opaque, but the border is a near-neutral flat colour.
                      Flood it from the edge; keep interior look-alikes.
      full-canvas  -- opaque and the border is chromatic, i.e. the background
                      IS artwork (bitcoin_b.svg's orange plate). Keep it all.

    force_rule pins the choice instead of deciding it from this array. The
    caller needs that when it has already edited the raster: deleting the drop
    shadow punches ~5 % of Little Satoshi to transparent, which is over
    TRANSPARENT_MARGIN_MIN, so a fresh call would switch from `matte` to
    `alpha`, leave the white background in place, and flood the whole footprint
    with silk. The rule is decided once on the untouched source and then held.
    """
    alpha = rgba[..., 3]
    transparent_frac = float((alpha < 128).mean())
    info = {"transparent_fraction": round(transparent_frac, 4)}
    if force_rule:
        info["rule_forced_by_caller"] = force_rule

    if force_rule == "alpha" or (force_rule is None
                                 and transparent_frac > TRANSPARENT_MARGIN_MIN):
        info["rule"] = "alpha"
        info["detail"] = "source carries a transparent margin; alpha >= 16 is ink"
        return alpha >= 16, info

    h, w, _ = rgba.shape
    ring = np.concatenate([rgba[0, :, :3], rgba[-1, :, :3],
                           rgba[:, 0, :3], rgba[:, -1, :3]])
    modal, count = Counter(map(tuple, ring.tolist())).most_common(1)[0]
    coverage = count / len(ring)
    lab = srgb_to_lab(np.array(modal, dtype=np.uint8))
    chroma = float(math.hypot(lab[1], lab[2]))
    info.update(border_modal_rgb=list(modal),
                border_modal_coverage=round(coverage, 3),
                border_modal_chroma=round(chroma, 1))

    if force_rule == "matte" or (force_rule is None
                                 and chroma < 12.0 and coverage >= 0.60):
        rgb_lab = srgb_to_lab(rgba[..., :3])
        d = np.sqrt(((rgb_lab - lab) ** 2).sum(-1))
        # A fully transparent pixel is background whatever colour is stored
        # underneath it, and the flood has to be able to travel through it.
        # Without this the matte rule reads RGB only, so a region the caller has
        # already deleted (the drop shadow) still walls the flood off and the
        # pocket it was sealing -- the gap between the character's legs -- is
        # kept as though it were an eye.
        bg_like = (d < 10.0) | (rgba[..., 3] < 16)
        exterior = flood_from_border(bg_like)
        interior_lookalike = int((bg_like & ~exterior).sum())
        info["rule"] = "matte"
        info["detail"] = (f"flat near-neutral border rgb{tuple(modal)} flooded "
                          f"from the edge")
        info["matte_pixels"] = int(exterior.sum())
        info["interior_background_coloured_pixels_kept"] = interior_lookalike
        return ~exterior, info

    info["rule"] = "full-canvas"
    info["detail"] = (f"opaque, and the border colour rgb{tuple(modal)} has "
                      f"chroma {chroma:.1f} -- the background is artwork, not a "
                      f"matte. Nothing removed.")
    # Still not ink where there is no paint at all: bitcoin_b.svg's rounded
    # corners are transparent, and counting them would invent a black tone.
    return alpha >= 16, info


def bbox_of(mask: np.ndarray):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def px_to_user(box_px, frame, size_px):
    """Pixel bbox -> user-unit bbox, given the user-space frame that was drawn."""
    fx, fy, fw, fh = frame
    pw, ph = size_px
    return (fx + box_px[0] * fw / pw, fy + box_px[1] * fh / ph,
            fx + box_px[2] * fw / pw, fy + box_px[3] * fh / ph)


def clamp_box(box, frame):
    fx, fy, fw, fh = frame
    return (max(fx, box[0]), max(fy, box[1]),
            min(fx + fw, box[2]), min(fy + fh, box[3]))


def ink_area_user(mask, frame, size_px) -> float:
    """Inked area expressed in source user units squared -- resolution free."""
    _, _, fw, fh = frame
    pw, ph = size_px
    return float(mask.sum()) * (fw / pw) * (fh / ph)


# ---------------------------------------------------------------------------
# Cropping
# ---------------------------------------------------------------------------

def flatten_svg_text(src: Path, dst: Path, log) -> bool:
    """Convert <text> to outlines so downstream never needs the fonts.

    The emission formula is 20 text runs in Liberation Serif and OpenSymbol.
    Shipping it as text means every renderer in the chain -- and the tracer --
    must resolve those fonts identically. Outlines remove the question.
    """
    exe = shutil.which("inkscape")
    if not exe:
        log("  !! inkscape not found: text NOT flattened. Downstream conversion "
            "will depend on Liberation Serif and OpenSymbol being installed.")
        return False
    r = subprocess.run([exe, "--export-text-to-path", "--export-plain-svg",
                        f"--export-filename={dst}", str(src)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not dst.exists():
        log(f"  !! inkscape text-to-path failed ({r.returncode}): "
            f"{r.stderr.strip()[:200]}")
        return False
    return True


def strip_dead_fonts(root) -> int:
    """Drop embedded SVG font definitions once no text references them.

    Inkscape flattens the <text> but leaves the <font> defs behind. They are
    then unreachable bytes that still imply a font dependency the file no
    longer has. Only removed when the document genuinely has no text left.
    """
    if any(localname(el) in ("text", "tspan") for el in root.iter()):
        return 0
    dead = [el for el in root.iter()
            if localname(el) in ("font", "font-face", "missing-glyph", "glyph")]
    n = 0
    for el in dead:
        if el.getparent() is not None:
            el.getparent().remove(el)
            n += 1
    for el in list(root.iter()):
        if localname(el) == "defs" and len(el) == 0 and el.getparent() is not None:
            el.getparent().remove(el)
    return n


def crop_svg(src: Path, dst: Path, box_user, units_per_mm):
    """Rewrite the root viewBox to the content box. Nothing is deleted --
    clipped-away geometry was already outside the inked area, and any clipPath
    in the document still refers to the same user-unit coordinates."""
    x0, y0, x1, y1 = box_user
    tree = etree.parse(str(src))
    root = tree.getroot()
    strip_dead_fonts(root)
    w_u, h_u = x1 - x0, y1 - y0
    root.set("viewBox", f"{x0:.4f} {y0:.4f} {w_u:.4f} {h_u:.4f}")
    if units_per_mm:
        root.set("width", f"{w_u / units_per_mm:.4f}mm")
        root.set("height", f"{h_u / units_per_mm:.4f}mm")
    else:
        root.set("width", f"{w_u:.4f}")
        root.set("height", f"{h_u:.4f}")
    root.set("preserveAspectRatio", "xMidYMid meet")
    dst.write_bytes(etree.tostring(tree, xml_declaration=True,
                                   encoding="UTF-8", pretty_print=False))


# ---------------------------------------------------------------------------
# Colour census
# ---------------------------------------------------------------------------

def interior_mask(rgb: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Ink pixels whose 8-neighbourhood is the same colour.

    Antialiasing manufactures a continuous ramp between every pair of adjacent
    colours. Censusing raw pixels therefore reports dozens of phantom tones
    that exist only on edges. Restricting the census to colour-uniform interiors
    removes them without touching real content -- the edge pixels are still
    counted in area via their parent cluster at assignment time.
    """
    q = (rgb.astype(np.int16) >> 3)
    same = np.ones(ink.shape, dtype=bool)
    pad = np.pad(q, ((1, 1), (1, 1), (0, 0)), mode="edge")
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            if dy == 1 and dx == 1:
                continue
            nb = pad[dy:dy + q.shape[0], dx:dx + q.shape[1]]
            same &= (nb == q).all(-1)
    return ink & same


def colour_census(rgb: np.ndarray, ink: np.ndarray, delta_e: float,
                  max_seed_colours: int = 512) -> dict:
    """Cluster ink colours in CIELAB and report area fractions.

    Perceptual clustering rather than exact matching, because the Reckless logo
    carries rgb(1,190,219) and rgb(20,191,219) -- two numbers, one cyan. The
    April tool needed an --adjacent-color-tolerance flag to cope; clustering in
    Lab makes the flag unnecessary.
    """
    interior = interior_mask(rgb, ink)
    census_px = rgb[interior] if interior.any() else rgb[ink]
    used_interior = bool(interior.any())

    exact_ink = np.unique(rgb[ink].reshape(-1, 3), axis=0)
    exact_interior = np.unique(census_px.reshape(-1, 3), axis=0)

    counts = Counter(map(tuple, census_px.reshape(-1, 3).tolist()))
    seeds = counts.most_common(max_seed_colours)
    seed_rgb = np.array([s for s, _ in seeds], dtype=np.uint8)
    seed_n = np.array([n for _, n in seeds], dtype=np.float64)
    seed_lab = srgb_to_lab(seed_rgb)

    # Greedy agglomeration, most-populous first: a stable, explainable merge.
    cents, weights, sums = [], [], []
    for lab, rgbv, n in zip(seed_lab, seed_rgb, seed_n):
        placed = False
        for i, c in enumerate(cents):
            if math.dist(lab, c) < delta_e:
                weights[i] += n
                sums[i] += rgbv.astype(np.float64) * n
                cents[i] = srgb_to_lab((sums[i] / weights[i]).round()
                                       .clip(0, 255).astype(np.uint8))
                placed = True
                break
        if not placed:
            cents.append(lab)
            weights.append(n)
            sums.append(rgbv.astype(np.float64) * n)

    centroids_rgb = np.array([(s / w).round().clip(0, 255).astype(np.uint8)
                              for s, w in zip(sums, weights)])
    centroid_lab = srgb_to_lab(centroids_rgb)

    # Assign EVERY ink pixel (edges included) to its nearest centroid, so the
    # reported area fractions sum to the whole inked area and nothing is lost.
    all_ink = rgb[ink].reshape(-1, 3)
    assign = np.empty(len(all_ink), dtype=np.int32)
    for s in range(0, len(all_ink), 400_000):          # chunked: the full
        chunk = srgb_to_lab(all_ink[s:s + 400_000])    # pairwise distance
        d = ((chunk[:, None, :] - centroid_lab[None, :, :]) ** 2).sum(-1)
        assign[s:s + 400_000] = np.argmin(d, axis=1)
    area = np.bincount(assign, minlength=len(centroids_rgb)).astype(np.float64)
    area /= max(area.sum(), 1)

    order = np.argsort(-area)
    tone_lab = srgb_to_lab(np.array([t[2] for t in TONES], dtype=np.uint8))
    clusters = []
    for rank, i in enumerate(order):
        c = centroids_rgb[i]
        nearest = int(np.argmin(((centroid_lab[i] - tone_lab) ** 2).sum(-1)))
        clusters.append({
            "id": rank,
            "rgb": [int(v) for v in c],
            "hex": "#%02x%02x%02x" % tuple(int(v) for v in c),
            "lab": [round(float(v), 1) for v in centroid_lab[i]],
            "area_fraction": round(float(area[i]), 5),
            "nearest_palette_tone": TONES[nearest][0],
            "nearest_palette_tone_name": TONES[nearest][1],
            "_src_index": int(i),
        })
    return {
        "delta_e_merge_threshold": delta_e,
        "census_basis": ("colour-uniform interior pixels" if used_interior
                         else "all ink pixels (no uniform interior found)"),
        "distinct_exact_colours_ink": int(len(exact_ink)),
        "distinct_exact_colours_interior": int(len(exact_interior)),
        # Ink that is NOT flat colour: antialiasing, gradients, soft shadows.
        # A high value predicts quantisation trouble, because none of it has a
        # palette entry -- every such pixel has to be forced to a neighbour.
        "soft_pixel_fraction": round(
            float(1.0 - interior.sum() / max(ink.sum(), 1)), 4),
        "clusters": clusters,
        "_assign": assign,
        "_ink": ink,
    }


# ---------------------------------------------------------------------------
# Feature size (granulometry) and tone recommendation
# ---------------------------------------------------------------------------

def erode(mask: np.ndarray) -> np.ndarray:
    pad = np.pad(mask, 1, constant_values=False)
    out = mask.copy()
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out &= pad[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


def dilate(mask: np.ndarray) -> np.ndarray:
    pad = np.pad(mask, 1, constant_values=False)
    out = mask.copy()
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out |= pad[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


# Geometric ladder: fine where the fabrication limits bite, coarse above.
_K_LADDER = (1, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 31, 40)


def granulometry(mask: np.ndarray) -> dict:
    """Local-width distribution by morphological OPENING.

    Erosion alone measures distance-to-boundary, which is half the local width
    and therefore condemns artwork that is in fact perfectly fabricable. An
    opening by a (2k+1)-square deletes exactly those features narrower than
    2k+1 px and leaves wider ones intact, so the retained area fraction is a
    true width distribution:

        retained(k)  == fraction of this tone's area in features >= 2k+1 px
        1 - retained == fraction thinner than that

    w50 is the width half the tone's area falls below -- the headline number.
    w10 is the thin tail: the width 10 % of the area falls below, which is what
    actually drops out at the fab.
    """
    a0 = int(mask.sum())
    if a0 == 0:
        return {"w10_px": 0, "w50_px": 0, "profile": []}

    profile = []
    eroded, prev_k = mask, 0
    for k in _K_LADDER:
        for _ in range(k - prev_k):
            eroded = erode(eroded)
        prev_k = k
        if not eroded.any():
            profile.append((2 * k + 1, 0.0))
            break
        opened = eroded
        for _ in range(k):
            opened = dilate(opened)
        opened &= mask                      # opening is anti-extensive
        profile.append((2 * k + 1, int(opened.sum()) / a0))
        if profile[-1][1] == 0.0:
            break

    def width_at(frac):
        # A feature dies at the first rung whose SE exceeds it, so the true
        # width lies in (2k-1, 2k+1]. Report the low end: measured against a
        # fabrication limit, an optimistic width is the dangerous error.
        for w, r in profile:
            if r <= frac:
                return max(1, w - 2)
        return max(1, profile[-1][0] - 2) if profile else 0

    return {"w10_px": width_at(0.90), "w50_px": width_at(0.50),
            "profile": [[w, round(r, 4)] for w, r in profile]}


def recommend(clusters, census, sizes_mm, raster_long_px, min_area=0.005):
    """Per-size verdict on every cluster, and a tone count that follows from it.

    A cluster survives at size S if its median local width clears the layer
    minimum. Three bands:
      renderable   w50 >= 0.15 mm  -- safe on any layer, silkscreen included
      etch-only    0.10 <= w50 < 0.15 mm -- copper or mask only, no silk
      unrepresentable  w50 < 0.10 mm -- cannot be fabricated; must merge
    """
    assign, ink = census["_assign"], census["_ink"]
    ys, xs = np.where(ink)
    shape = ink.shape

    sig = [c for c in clusters if c["area_fraction"] >= min_area]
    for c in sig:
        m = np.zeros(shape, dtype=bool)
        sel = assign == c["_src_index"]
        m[ys[sel], xs[sel]] = True
        c["feature_px"] = granulometry(m)

    lab = np.array([c["lab"] for c in sig], dtype=np.float64)
    out = {}
    for S in sizes_mm:
        mm_per_px = S / raster_long_px
        renderable, etch_only, unrep = [], [], []
        for c in sig:
            w50 = c["feature_px"]["w50_px"] * mm_per_px
            w10 = c["feature_px"]["w10_px"] * mm_per_px
            rec = {"cluster": c["id"], "hex": c["hex"],
                   "area_fraction": c["area_fraction"],
                   "w50_mm": round(w50, 3), "w10_mm": round(w10, 3)}
            if w50 >= SILK_MIN:
                renderable.append(rec)
            elif w50 >= ETCH_MIN:
                rec["constraint"] = (f"w50 {w50:.3f} mm is under the {SILK_MIN} mm "
                                     f"silkscreen minimum -- copper/mask layers only "
                                     f"(T2/T3/T6), no T1 silk")
                etch_only.append(rec)
            else:
                rec["reason"] = (f"median local width {w50:.3f} mm is under the "
                                 f"{ETCH_MIN} mm copper/mask minimum")
                unrep.append(rec)

        # Nothing is dropped silently: every unrepresentable cluster is told
        # which surviving cluster it must fold into.
        survivors = [r["cluster"] for r in renderable + etch_only]
        for r in unrep:
            i = next(k for k, c in enumerate(sig) if c["id"] == r["cluster"])
            if survivors:
                j = min(survivors,
                        key=lambda cid: math.dist(
                            lab[i], lab[next(k for k, c in enumerate(sig)
                                             if c["id"] == cid)]))
                r["merge_into_cluster"] = j
                r["merge_into_hex"] = next(c["hex"] for c in sig if c["id"] == j)
            else:
                r["merge_into_cluster"] = None

        n = len(renderable) + len(etch_only)
        capped = min(n, len(TONES))
        short_mm = S * min(shape) / max(shape)
        # Palette tone collisions: two source clusters landing on one PCB tone
        # cannot both be shown, whatever the feature size says.
        tones_used = {next(c["nearest_palette_tone"] for c in sig
                           if c["id"] == r["cluster"])
                      for r in renderable + etch_only}
        out[f"{S:g}mm"] = {
            "rendered_size_mm": [round(S, 2), round(short_mm, 2)],
            "mm_per_raster_px": round(mm_per_px, 5),
            # Widths are quantised to the erosion ladder, so nothing finer than
            # this can be resolved. Quote it, or the mm figures look precise.
            "width_measurement_quantum_mm": round(2 * mm_per_px, 4),
            "recommended_tone_count": capped,
            "distinct_palette_tones_reachable": len(tones_used),
            "renderable": renderable,
            "etch_only_no_silk": etch_only,
            "unrepresentable": unrep,
            "verdict": _verdict(S, capped, renderable, etch_only, unrep,
                                len(tones_used)),
        }
    for c in sig:
        c.pop("_src_index", None)
    for c in clusters:
        c.pop("_src_index", None)
    return out


def build_warnings(entry, census, sizes):
    """Actionable per-asset flags. Everything here is a reason a conversion
    would come out wrong, stated before anyone spends a fab run finding out."""
    warn = []
    cl = census["clusters"]
    sig = [c for c in cl if c["area_fraction"] >= 0.005]

    soft = census["soft_pixel_fraction"]
    if soft > 0.25:
        warn.append(
            f"SOFT ART: {100*soft:.0f} % of ink is not flat colour (gradients, "
            f"antialiasing, shading). The palette has no intermediate tones, so "
            f"all of it gets forced onto a neighbour. Expect banding.")

    # A mid-grey neutral that is neither the lightest nor the darkest cluster is
    # almost always a drop shadow -- a soft ellipse with no palette entry.
    if len(sig) >= 3:
        ls = sorted(sig, key=lambda c: c["lab"][0])
        for c in ls[1:-1]:
            chroma = math.hypot(c["lab"][1], c["lab"][2])
            if chroma < 10 and c["lab"][0] > 55 and c["area_fraction"] < 0.15:
                warn.append(
                    f"PROBABLE DROP SHADOW: cluster {c['id']} {c['hex']} is a "
                    f"light neutral (L*={c['lab'][0]:.0f}, chroma {chroma:.1f}) "
                    f"at {100*c['area_fraction']:.1f} % area. Soft shadows do not "
                    f"survive quantisation -- delete it at ingest rather than "
                    f"letting it become a spurious tone.")

    tones = {c["nearest_palette_tone"] for c in sig}
    if len(tones) < len(sig):
        pairs = {}
        for c in sig:
            pairs.setdefault(c["nearest_palette_tone"], []).append(c["hex"])
        collided = {k: v for k, v in pairs.items() if len(v) > 1}
        warn.append(
            f"TONE COLLISION: {len(sig)} source colours map to only "
            f"{len(tones)} palette tones -- {collided}. Those colours cannot be "
            f"told apart on the board whatever the size; pick the mapping "
            f"deliberately rather than by nearest-anchor.")

    ar = entry.get("aspect_ratio", 1.0)
    if ar >= 2.5:
        warn.append(
            f"EXTREME ASPECT {ar:.2f}:1 -- a nominal size is the LONG edge. At "
            f"{sizes[0]:g} mm long this asset is only "
            f"{sizes[0]/ar:.1f} mm tall.")

    rec = entry.get("tone_recommendation", {})
    for S in sizes:
        blk = rec.get(f"{S:g}mm", {})
        if blk.get("recommended_tone_count", 1) == 0:
            warn.append(
                f"UNSUITABLE AT {S:g} mm: no tone clears the {ETCH_MIN} mm "
                f"copper/mask minimum. Do not convert at this size.")
        elif blk.get("unrepresentable"):
            lost = sum(u["area_fraction"] for u in blk["unrepresentable"])
            warn.append(
                f"CONTENT LOSS AT {S:g} mm: {100*lost:.1f} % of ink is in "
                f"features under {ETCH_MIN} mm and must be merged away "
                f"({', '.join(u['hex'] for u in blk['unrepresentable'])}).")
    return warn


def _verdict(S, n, renderable, etch_only, unrep, tones_used):
    if n == 0:
        return (f"UNSUITABLE at {S:g} mm -- every significant tone falls below "
                f"the {ETCH_MIN} mm fabrication minimum.")
    bits = [f"{n} tone{'s' if n != 1 else ''} carry at {S:g} mm"]
    if etch_only:
        bits.append(f"{len(etch_only)} of them copper/mask only (no silkscreen)")
    if unrep:
        bits.append(f"{len(unrep)} must be merged away")
    if tones_used < n:
        bits.append(f"only {tones_used} distinct palette tones reachable -- "
                    f"{n - tones_used} source colour(s) collide")
    return "; ".join(bits) + "."


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def process(spec, source_root, outdir, sizes, delta_e, log):
    src = (source_root if spec["root"] == "onedrive" else REPO) / spec["src"]
    log(f"\n=== {spec['id']}  ({spec['role']})")
    log(f"  source: {src}")
    if not src.exists():
        log("  !! MISSING -- skipped")
        return {"id": spec["id"], "error": "source missing", "source": str(src)}

    entry = {
        "id": spec["id"],
        "role": spec["role"],
        "licence": spec["licence"],
        "source_path": str(src),
        "source_bytes": src.stat().st_size,
        "source_kind": src.suffix.lower().lstrip("."),
    }
    if spec.get("note"):
        entry["note"] = spec["note"]

    norm_dir = outdir / "normalised"
    rast_dir = outdir / "raster"
    norm_dir.mkdir(parents=True, exist_ok=True)
    rast_dir.mkdir(parents=True, exist_ok=True)

    is_svg = src.suffix.lower() == ".svg"
    tmp = Path(tempfile.mkdtemp(prefix="prep_assets_"))

    if is_svg:
        vb = svg_viewbox(src)
        upmm = svg_units_per_mm(src)
        entry["source_viewbox"] = [round(v, 3) for v in vb]
        entry["source_units_per_mm"] = round(upmm, 4) if upmm else None
        entry["svg_fill_inheritance"] = analyse_svg_fills(src)
        fi = entry["svg_fill_inheritance"]
        log(f"  fills: {fi['painted_leaves']} painted leaves  "
            f"css={fi['explicit_css_fill']} attr={fi['explicit_attribute_fill']}  "
            f"INHERITED={fi['inherited_total']} ({fi['inherited_pct']}%)"
            f"  [ancestor={fi['inherited_from_ancestor']} "
            f"initial={fi['inherited_initial_black']}]")
        if fi["stroke_only_shapes"]:
            log(f"  !! {fi['stroke_only_shapes']} stroke-only shape(s): fill is "
                f"'none' but they paint via stroke. A fill-only extractor drops "
                f"these too.")

        work = src
        if spec.get("flatten_text"):
            flat = tmp / "flat.svg"
            if flatten_svg_text(src, flat, log):
                work = flat
                entry["text_flattened_to_paths"] = True
                log("  text -> outlines via inkscape (font dependency removed)")
            else:
                entry["text_flattened_to_paths"] = False

        probe = render_svg(work, RASTER_LONG_EDGE)
        arr = np.asarray(probe)
        mask, mi = ink_mask(arr)
        entry["ink_mask"] = mi
        log(f"  ink rule: {mi['rule']} -- {mi['detail']}")
        box_px = bbox_of(mask)
        if box_px is None:
            log("  !! NO INK FOUND -- asset renders empty")
            entry["error"] = "renders empty"
            return entry

        box_user = px_to_user(box_px, vb, probe.size)
        ref_mask, ref_frame, ref_size = mask, vb, probe.size

        # The emission formula inks 0.4 % of a Letter artboard, so a first pass
        # at 1600 px resolves its strokes at ~3 px and every measurement taken
        # from it is noise. Crop generously, re-render so the content fills the
        # frame, and take the real bbox from that.
        long_px = max(box_px[2] - box_px[0], box_px[3] - box_px[1])
        entry["bbox_refined_second_pass"] = bool(long_px < 0.5 * max(probe.size))
        if entry["bbox_refined_second_pass"]:
            pad = 0.03 * max(box_user[2] - box_user[0], box_user[3] - box_user[1])
            prov = clamp_box((box_user[0] - pad, box_user[1] - pad,
                              box_user[2] + pad, box_user[3] + pad), vb)
            prov_file = tmp / "prov.svg"
            crop_svg(work, prov_file, prov, upmm)
            probe2 = render_svg(prov_file, RASTER_LONG_EDGE)
            m2, _ = ink_mask(np.asarray(probe2))
            b2 = bbox_of(m2)
            if b2 is not None:
                prov_frame = (prov[0], prov[1], prov[2] - prov[0], prov[3] - prov[1])
                box_user = px_to_user(b2, prov_frame, probe2.size)
                ref_mask, ref_frame, ref_size = m2, prov_frame, probe2.size
                log(f"  bbox refined on a second pass "
                    f"({long_px} px -> {max(b2[2]-b2[0], b2[3]-b2[1])} px of content)")

        margin = 0.004 * max(box_user[2] - box_user[0], box_user[3] - box_user[1])
        x0, y0, x1, y1 = clamp_box((box_user[0] - margin, box_user[1] - margin,
                                    box_user[2] + margin, box_user[3] + margin), vb)

        entry["crop"] = {
            "units": "SVG user units",
            "before_bbox": [round(vb[0], 2), round(vb[1], 2),
                            round(vb[0] + vb[2], 2), round(vb[1] + vb[3], 2)],
            "before_size": [round(vb[2], 2), round(vb[3], 2)],
            "after_bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
            "after_size": [round(x1 - x0, 2), round(y1 - y0, 2)],
            "area_retained_pct": round(100.0 * ((x1 - x0) * (y1 - y0))
                                       / (vb[2] * vb[3]), 3),
            "margin_user_units": round(margin, 3),
        }
        if upmm:
            entry["crop"]["after_size_mm"] = [round((x1 - x0) / upmm, 3),
                                              round((y1 - y0) / upmm, 3)]
        log(f"  bbox: {entry['crop']['before_size']} -> "
            f"{entry['crop']['after_size']} user units "
            f"({entry['crop']['area_retained_pct']}% of the artboard)")

        norm = norm_dir / f"{spec['id']}.svg"
        crop_svg(work, norm, (x0, y0, x1, y1), upmm)

        canon = render_svg(norm, RASTER_LONG_EDGE)
        # Round-trip: compare inked AREA IN SOURCE UNITS, not pixel counts.
        # The two renders are at different scales, so a pixel comparison
        # measures resolution rather than content.
        cm, _ = ink_mask(np.asarray(canon))
        before = ink_area_user(ref_mask, ref_frame, ref_size)
        after = ink_area_user(cm, (x0, y0, x1 - x0, y1 - y0), canon.size)
        drift = abs(after - before) / max(before, 1e-9)
        entry["crop_roundtrip"] = {
            "metric": "inked area in SVG user units squared",
            "before": round(before, 1),
            "after": round(after, 1),
            "drift_pct": round(100 * drift, 2),
            "ok": bool(drift < 0.10),
        }
        if drift >= 0.10:
            log(f"  !! CROP ROUND-TRIP DRIFT {100*drift:.1f}% -- content may "
                f"have been lost by the crop")
        else:
            log(f"  crop round-trip ok (inked area drift {100*drift:.2f}%)")

    else:
        img = Image.open(src).convert("RGBA")
        arr = np.asarray(img)
        entry["source_size_px"] = list(img.size)

        # ORDER MATTERS: the shadow goes first, before the matte flood.
        #
        # ink_mask floods the background colour inward from the border and keeps
        # any enclosed pocket of that colour, so that white eyes and highlights
        # survive. The characters stand on a soft grey ground ellipse that runs
        # under their feet and SEALS the gap between the legs. Flooding first,
        # the pocket between the legs is enclosed, so it is kept as if it were a
        # highlight -- and a wedge of pure background prints as solid silk
        # between the character's legs. Every Satoshi rendered that way.
        #
        # Removing the shadow first opens the gap to the border, the flood
        # drains through it, and the eyes -- genuinely enclosed by the face --
        # are unaffected.
        # The rule is chosen from the UNTOUCHED source and then held (see
        # ink_mask's force_rule), because keying the shadow changes the
        # transparent fraction enough to change the answer.
        mask, mi = ink_mask(arr)
        if spec.get("key_shadow"):
            kept, si = key_drop_shadow(arr, mask)
            entry["drop_shadow_keyed"] = si
            log(f"  drop shadow: {si['detail']}  [{si['rule']}]")
            if si["components_rejected_as_fringe"]:
                log(f"     {si['components_rejected_as_fringe']} in-band "
                    f"component(s) had no solid core and were KEPT as "
                    f"antialiasing, not shadow")
            if si["removed_px"]:
                arr = arr.copy()
                arr[..., 3] = np.where(mask & ~kept, 0, arr[..., 3])
                img = Image.fromarray(arr, "RGBA")
                # Re-flood: the ellipse was sealing the gap between the legs,
                # so that pocket of pure background can now drain to the border
                # instead of being kept as if it were a highlight.
                before = int(mask.sum())
                mask, mi = ink_mask(arr, force_rule=mi["rule"])
                freed = before - int(mask.sum()) - si["removed_px"]
                if freed > 0:
                    log(f"     re-flood after shadow removal freed {freed:,} px "
                        f"of background that the ellipse had sealed in")
        entry["ink_mask"] = mi
        log(f"  ink rule: {mi['rule']} -- {mi['detail']}")
        if mi["rule"] == "matte":
            log(f"     matte {mi['matte_pixels']:,} px removed; "
                f"{mi['interior_background_coloured_pixels_kept']:,} interior "
                f"pixels of the same colour KEPT (eyes/highlights survive)")
        box_px = bbox_of(mask)
        if box_px is None:
            entry["error"] = "no ink"
            return entry
        w, h = img.size
        entry["crop"] = {
            "units": "pixels",
            "before_bbox": [0, 0, w, h],
            "before_size": [w, h],
            "after_bbox": list(box_px),
            "after_size": [box_px[2] - box_px[0], box_px[3] - box_px[1]],
            "area_retained_pct": round(100.0 * ((box_px[2] - box_px[0])
                                                * (box_px[3] - box_px[1]))
                                       / (w * h), 3),
            "margin_user_units": 0,
        }
        log(f"  bbox: {[w, h]} -> {entry['crop']['after_size']} px "
            f"({entry['crop']['area_retained_pct']}%)")

        out = arr.copy()
        if mi["rule"] == "matte" or spec.get("key_shadow"):
            out[..., 3] = np.where(mask, out[..., 3], 0)
        canon = Image.fromarray(out, "RGBA").crop(box_px)
        if max(canon.size) > RASTER_LONG_EDGE:
            r = RASTER_LONG_EDGE / max(canon.size)
            canon = canon.resize((max(1, round(canon.size[0] * r)),
                                  max(1, round(canon.size[1] * r))),
                                 Image.LANCZOS)
        norm = norm_dir / f"{spec['id']}.png"
        canon.save(norm, optimize=True)
        entry["crop_roundtrip"] = {"ok": True, "note": "raster crop is exact"}

    canon = canon.convert("RGBA")
    rast = rast_dir / f"{spec['id']}.png"
    canon.save(rast, optimize=True)
    entry["normalised_file"] = str(norm.relative_to(outdir.parent))
    entry["normalised_bytes"] = norm.stat().st_size
    entry["raster_file"] = str(rast.relative_to(outdir.parent))
    entry["raster_size_px"] = list(canon.size)

    carr = np.asarray(canon)
    cmask, _ = ink_mask(carr)
    cen = colour_census(carr[..., :3], cmask, delta_e)
    entry["colour_census"] = {k: v for k, v in cen.items()
                              if not k.startswith("_")}
    sig = [c for c in cen["clusters"] if c["area_fraction"] >= 0.005]
    if cen["clusters"]:
        bg = cen["clusters"][0]
        entry["colour_census"]["background_cluster"] = {
            "id": bg["id"], "hex": bg["hex"],
            "area_fraction": bg["area_fraction"],
            "note": ("Largest cluster. Per docs/pcb-palette.md the quantiser "
                     "should map this to T5 and emit no geometry for it -- it "
                     "counts toward the tone total but costs nothing."),
        }
    log(f"  colours: {cen['distinct_exact_colours_ink']:,} exact -> "
        f"{len(cen['clusters'])} Lab clusters "
        f"({len(sig)} at >=0.5% area, dE<{delta_e})")
    for c in sig:
        log(f"     {c['hex']}  {100*c['area_fraction']:5.1f}%  "
            f"-> nearest {c['nearest_palette_tone']} {c['nearest_palette_tone_name']}")

    entry["aspect_ratio"] = round(max(canon.size) / min(canon.size), 3)
    entry["tone_recommendation"] = {
        "size_basis": "long edge of the finished art, in mm",
        "min_feature_mm": MIN_FEATURE_MM,
        "significant_area_threshold": 0.005,
        **recommend(cen["clusters"], cen, sizes, max(canon.size)),
    }
    entry["warnings"] = build_warnings(entry, cen, sizes)
    for w in entry["warnings"]:
        log(f"  !! {w}")
    for S in sizes:
        r = entry["tone_recommendation"][f"{S:g}mm"]
        log(f"  {S:g} mm -> {r['recommended_tone_count']} tones. {r['verdict']}")
        for u in r["unrepresentable"]:
            log(f"     !! LOSS at {S:g} mm: {u['hex']} "
                f"({100*u['area_fraction']:.1f}% of ink) {u['reason']}; "
                f"merge into cluster {u['merge_into_cluster']} "
                f"{u.get('merge_into_hex','-')}")
    shutil.rmtree(tmp, ignore_errors=True)
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "assets"))
    ap.add_argument("--source-root", default=None)
    ap.add_argument("--sizes", type=float, nargs="+", default=list(DEFAULT_SIZES_MM))
    ap.add_argument("--delta-e", type=float, default=12.0,
                    help="CIELAB merge distance for the colour census")
    ap.add_argument("--only", nargs="+", default=None)
    args = ap.parse_args()

    root = find_source_root(args.source_root)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    lines = []

    def log(s):
        print(s)
        lines.append(s)

    log(f"source root : {root}")
    log(f"output      : {outdir}")
    log(f"sizes (mm)  : {', '.join(f'{s:g}' for s in args.sizes)}")
    log(f"raster long edge: {RASTER_LONG_EDGE} px")

    specs = [a for a in ASSETS if not args.only or a["id"] in args.only]
    entries = [process(s, root, outdir, args.sizes, args.delta_e, log)
               for s in specs]

    manifest = {
        "generator": "tools/prep_assets.py",
        "stage": "ingest -- normalisation only, no KiCad emission",
        "palette_reference": "docs/pcb-palette.md",
        "raster_long_edge_px": RASTER_LONG_EDGE,
        "target_sizes_mm": args.sizes,
        "min_feature_mm": MIN_FEATURE_MM,
        "delta_e_merge_threshold": args.delta_e,
        "assets": entries,
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (outdir / "prep_assets.log").write_text("\n".join(lines) + "\n",
                                            encoding="utf-8")
    print(f"\nwrote {outdir / 'manifest.json'}")

    bad = [e for e in entries if e.get("error")]
    if bad:
        print(f"!! {len(bad)} asset(s) failed: "
              f"{', '.join(e['id'] for e in bad)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
