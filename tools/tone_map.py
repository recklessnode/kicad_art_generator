#!/usr/bin/env python3
"""Which tone does this ink go in? Answered by DECLARATION, never by distance.

THE PROBLEM THIS REPLACES. ``w0_spike.quantise`` assigns every pixel to its
nearest palette anchor in weighted Lab. That is a sound way to pick between
tones the process can make, and it is a catastrophic way to handle ink the
process CANNOT make. On a dark-mask board T5 -- bare mask -- is the darkest
tone that exists. The corpus blacks sit at L* 0.0-0.3; purple's T5 sits at
L* 28.2. The ink is 28 L* below the darkest achievable tone, so no anchor
represents it, and nearest-anchor resolves that impossibility by choosing the
extremum. The extremum is T5. T5 draws nothing. Measured consequence, from the
source-overlay metric in tools/fidelity.py against the shipped library:

    satoshi_points_20mm   29.55 % of source ink undrawn -- legs, arms, the
                          pointing arm and the eyebrows are simply absent
    satoshi_little_20mm   24.59 %      satoshi_miner_20mm  20.24 %
    mfb_node_full_38mm    11.96 %      mfb_node_light_38mm 14.48 %

and a second failure with a different mechanism but the same root: a light grey
at L* 89 has no anchor between L* 89 and L* 100, so it quantises to T1
alongside the white disc it is drawn on and the laurel wreath merges into the
background of its own badge.

WHY DECLARATION FIXES WHAT A BETTER ANCHOR SET CANNOT. Nearest-anchor is
distance-bound: it can only ever choose the tone closest to the ink. Declaration
is not. The mfb_node_light grey CAN be sent to T3 (bare FR4, L* 72.4 on purple)
-- 22 L* below T1 and 44 L* above the board, legible and distinct -- even though
T3 is 17 L* further from the source grey than T1 is. That assignment is
unreachable by any anchor table and trivial to declare. Same for the Reckless
cyan, which merges into the white shield under every anchor set the repo can
express and separates cleanly the moment somebody says "cyan is T3".

WHAT THIS MODULE REFUSES TO DO. It never invents a substitution. An ink that is
not declared is UNMAPPED and counted, and past a budget the emit refuses and
prints a paste-ready block naming the orphan colours. An ink bound to a tone it
is nowhere near must say ``off_palette = true``. An ink sharing a tone with
another declared ink must name it in ``merge_ok``. Every lossy step is a
sentence somebody wrote, not a number a metric chose.

THE MIXTURE PATH IS KEPT, THE MIXTURE CONSTANTS ARE NOT. Coverage-antialiased
boundary pixels still have to be resolved, and w0_spike's photometric rule is
the right one: a boundary pixel is literally ``c = (1-t)*A + t*B`` and reading
``t`` back in sRGB is what makes a >= 1 px feature survive at every sub-pixel
offset. But ``MIX_SUPPORT_FRAC``, ``MIX_PAIR_PENALTY``, ``MIX_MIN_DE`` and
``MIX_EDGE`` (w0_spike.py lines 154-163) exist only to break ties inside the
palette's self-degenerate dark cluster -- T7 sits 0.5 weighted-Lab units off the
T5~T6 segment. Declared inks in one asset are tens of units apart; the closest
pair in the whole corpus is two shades of one gold, 10.4 apart. There
is no tie to break, so those four constants are not used here, and the
blow-up they were mitigating cannot recur.

    ENDPOINTS ARE THE DECLARED sRGB VALUES, NOT PALETTE ANCHORS. That is the
    substantive difference from w0_spike._coverage's caller. The renderer
    blended the SOURCE colours; recovering the fraction against the source
    colours is reading back the number that was actually written.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np

from w0_spike import (MIX_MAX_RES, MIX_SPLIT, L_WEIGHT, _coverage,
                      _squared_distances, srgb_to_lab)

# An ink at or beyond this weighted-Lab distance from the tone it is bound to
# is not being approximated, it is being replaced, and it has to say so.
# MEASURED over the corpus: the two off-palette inks in it -- a saturated red
# and a saturated cyan -- sit 58 and 61 weighted-Lab units from every anchor of
# every palette this file can build, while the largest distance any OTHER
# declared ink has to the tone it is bound to is 43. 55 sits in that gap.
#
# The corpus colours themselves are third-party brand property and are NOT
# reproduced here. This repo is public: the measurements are ours, the values
# are not. They live in the private sidecar that sits beside the art.
OFF_PALETTE_DE = 55.0

# Default matching tolerance, weighted Lab. 10.0 is the same dE the repo's own
# ingest clusterer uses to decide two colours are the same ink
# (prep_assets.colour_census, called with 10.0 throughout).
DEFAULT_TOL_DE = 10.0

# Unmapped ink is a REFUSAL, not a rounding. 0.25 % of opaque pixels is roughly
# the antialias residue a clean two-tone vector leaves behind; anything above
# it is a colour nobody declared.
DEFAULT_UNMAPPED_BUDGET_PCT = 0.25

# A declared merge that ERASES a feature is refused past this much of the ink
# (issue #17: satoshi_points' chest S, drawn only in the shading gold, merged
# into the body gold and was not drawn at any size -- while every check
# passed, because every check measured ink that was DRAWN, and merged ink is
# drawn, just in its neighbour's colour). MEASURED across the three Satoshi
# characters, sidecar mappings as declared (points as declared before the
# 2026-08-24 S repair): the erased chest-S glyphs total 0.553 % of ink on
# satoshi_points, 0.343 % on little_satoshi, 0.326 % on satoshi_miner, while
# the worst enclosed antialias speckle that survives the enclosure test is a
# single pixel, 0.0006 %. 0.05 sits in that three-decade gap: 6.5x under the
# smallest real erasure, 80x over the measured speckle.
MERGE_ERASED_FAIL_PCT = 0.05

# A component counts as ENCLOSED when at least this fraction of its drawn
# border (border against opaque ink; the silhouette against background is
# excluded, because that edge is the merge partner's silhouette too and
# survives the merge unchanged) is the very ink it merged into. MEASURED on
# the three Satoshi characters: every genuinely erased feature -- the chest-S
# strokes, drawn only in shading gold and surrounded by body gold -- reads
# exactly 1.000, and everything that keeps a visible edge reads 0.969 or
# less (satoshi_points' rim crescent 0.000: it lies between two runs of the
# drawn black outline; satoshi_miner's helmet dome 0.921 and hatband 0.969:
# both meet the black outline). 0.98 is the middle of that measured gap.
MERGE_ENCLOSED_MIN_FRAC = 0.98


class ToneMapError(ValueError):
    pass


class UnmappedInk(ToneMapError):
    """Source ink that no declared entry claims, over budget."""

    def __init__(self, msg, orphans=None, block=None):
        super().__init__(msg)
        self.orphans = orphans or []
        self.block = block or ""


def _hex_to_rgb(s) -> tuple[int, int, int]:
    if isinstance(s, (tuple, list)):
        if len(s) != 3:
            raise ToneMapError(f"colour {s!r} is not 3 channels")
        return tuple(int(c) for c in s)
    t = str(s).strip().lstrip("#")
    if len(t) != 6:
        raise ToneMapError(f"colour {s!r} is not a 6-digit hex like #rrggbb")
    try:
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ToneMapError(f"colour {s!r} is not hex") from None


def rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


@dataclass(frozen=True)
class Ink:
    """One source colour and the tone somebody decided it becomes."""
    rgb: tuple[int, int, int]
    tone: str
    merge_ok: tuple[str, ...] = ()     # hexes of other declared inks it may share with
    off_palette: bool = False          # acknowledges d_weighted >= OFF_PALETTE_DE
    legibility: str = ""               # "declared" acknowledges |dL| < LEGIBLE_MIN_DL
    erase_ok: bool = False             # acknowledges the merge ERASES this ink's
                                       # enclosed features (issue #17). merge_ok
                                       # says "share a tone"; it does not say
                                       # "and the feature disappears" -- that is
                                       # a second, bigger loss and needs its own
                                       # sentence.
    note: str = ""

    @property
    def hex(self) -> str:
        return rgb_to_hex(self.rgb)


@dataclass(frozen=True)
class ToneMap:
    mask: str
    inks: tuple[Ink, ...]
    tol_de: float = DEFAULT_TOL_DE
    unmapped_budget_pct: float = DEFAULT_UNMAPPED_BUDGET_PCT
    inner_ok: bool = False
    source: str = ""                   # filename this map speaks for, for messages

    def __post_init__(self):
        if not self.inks:
            raise ToneMapError(f"{self.source or 'tone map'}: no inks declared")
        seen = {}
        for ink in self.inks:
            if ink.hex in seen:
                raise ToneMapError(
                    f"{self.source or 'tone map'}: colour {ink.hex} declared "
                    f"twice. Two rows for one colour cannot both apply and "
                    f"which one wins would be an accident of ordering")
            seen[ink.hex] = ink
        for ink in self.inks:
            for other in ink.merge_ok:
                h = rgb_to_hex(_hex_to_rgb(other))
                if h not in seen:
                    raise ToneMapError(
                        f"{self.source or 'tone map'}: {ink.hex} lists "
                        f"merge_ok = {h}, which is not a declared ink here. "
                        f"A merge can only be permitted between two colours "
                        f"this table actually names")

    def by_hex(self, h: str) -> Ink | None:
        h = rgb_to_hex(_hex_to_rgb(h))
        return next((i for i in self.inks if i.hex == h), None)

    def merge_groups(self) -> list[tuple[str, ...]]:
        """Declared merges, closed transitively. -> groups of hexes, sorted.

        TRANSITIVE ON PURPOSE, and this is a judgement rather than a detail.
        satoshi_miner has three golds; a strictly pairwise reading needs three
        declarations to say the one thing that is true of them ("one surface
        finish, one metal tone"), and a five-colour piece would need ten. The
        cost of that is not typing, it is that nobody reads the tenth line.

        Transitivity cannot merge anything nobody named: an edge only exists
        where somebody wrote a hex, both ends have to be declared inks of this
        same table, and merges are only ever CHECKED within a single tone -- so
        every member of a closed group was already declared into that tone by
        hand. What the closure adds is that a chain counts as the group it
        obviously is.
        """
        parent = {i.hex: i.hex for i in self.inks}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for ink in self.inks:
            for other in ink.merge_ok:
                h = rgb_to_hex(_hex_to_rgb(other))
                if h in parent:
                    ra, rb = find(ink.hex), find(h)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
        groups: dict[str, list[str]] = {}
        for ink in self.inks:
            groups.setdefault(find(ink.hex), []).append(ink.hex)
        return sorted(tuple(sorted(v)) for v in groups.values() if len(v) > 1)

    def merge_declared(self, ha: str, hb: str) -> bool:
        """May these two declared colours share a tone without complaint?"""
        ha = rgb_to_hex(_hex_to_rgb(ha))
        hb = rgb_to_hex(_hex_to_rgb(hb))
        return any(ha in g and hb in g for g in self.merge_groups())

    def canonical(self) -> str:
        rows = []
        for ink in sorted(self.inks, key=lambda i: i.hex):
            merges = ",".join(sorted(rgb_to_hex(_hex_to_rgb(m))
                                     for m in ink.merge_ok))
            # erase_ok is appended only when set, so every map written before
            # the key existed keeps the digest its shipped footprints carry.
            rows.append(f"{ink.hex}>{ink.tone}|m={merges}|"
                        f"o={int(ink.off_palette)}|l={ink.legibility}"
                        + ("|e=1" if ink.erase_ok else ""))
        return (f"{self.mask}#tol={self.tol_de:g}#"
                f"budget={self.unmapped_budget_pct:g}#"
                f"inner={int(self.inner_ok)}#" + ";".join(rows))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()[:12]

    # --- serialisation, so build_library can hand one to emit_art ----------
    def to_dict(self) -> dict:
        rows = []
        for ink in self.inks:
            row = {"rgb": ink.hex, "tone": ink.tone}
            if ink.merge_ok:
                row["merge_ok"] = [rgb_to_hex(_hex_to_rgb(m))
                                   for m in ink.merge_ok]
            if ink.off_palette:
                row["off_palette"] = True
            if ink.erase_ok:
                row["erase_ok"] = True
            if ink.legibility:
                row["legibility"] = ink.legibility
            if ink.note:
                row["note"] = ink.note
            rows.append(row)
        return {
            "mask": self.mask, "tol_de": self.tol_de,
            "unmapped_budget_pct": self.unmapped_budget_pct,
            "inner_ok": self.inner_ok, "source": self.source,
            "tones": rows,
        }

    @staticmethod
    def from_dict(d: dict) -> "ToneMap":
        rows = d.get("tones")
        if not isinstance(rows, list):
            raise ToneMapError("tone map has no 'tones' list")
        inks = []
        for r in rows:
            if not isinstance(r, dict) or "rgb" not in r or "tone" not in r:
                raise ToneMapError(f"tone map row {r!r} needs 'rgb' and 'tone'")
            inks.append(Ink(
                rgb=_hex_to_rgb(r["rgb"]), tone=str(r["tone"]),
                merge_ok=tuple(str(m) for m in (r.get("merge_ok") or ())),
                off_palette=bool(r.get("off_palette", False)),
                erase_ok=bool(r.get("erase_ok", False)),
                legibility=str(r.get("legibility") or ""),
                note=str(r.get("note") or "")))
        return ToneMap(
            mask=str(d.get("mask", "black")), inks=tuple(inks),
            tol_de=float(d.get("tol_de", DEFAULT_TOL_DE)),
            unmapped_budget_pct=float(d.get("unmapped_budget_pct",
                                            DEFAULT_UNMAPPED_BUDGET_PCT)),
            inner_ok=bool(d.get("inner_ok", False)),
            source=str(d.get("source") or ""))

    @staticmethod
    def load(path) -> "ToneMap":
        import pathlib
        return ToneMap.from_dict(json.loads(
            pathlib.Path(path).read_text(encoding="utf-8")))


def _weighted(rgb) -> np.ndarray:
    w = np.array([L_WEIGHT, 1.0, 1.0])
    return srgb_to_lab(np.asarray(rgb, dtype=np.uint8)) * w


def paste_block(orphans, palette=None) -> str:
    """A TOML fragment the operator can paste into the sidecar, verbatim."""
    lines = ["tones = ["]
    for o in orphans:
        near = f'  # nearest legible tone {o["nearest_legible"]}' \
            if o.get("nearest_legible") else ""
        lines.append(f'  {{ rgb = "{o["hex"]}", tone = "?" }},'
                     f'{near}   # {o["share"]:.2f}% of ink, L* {o["lstar"]:.1f}')
    lines.append("]")
    return "\n".join(lines)


def map_labels(img, tmap: ToneMap, palette, *, min_alpha: int = 128):
    """-> (labels, opaque, stats). Same shape as w0_spike.quantise.

    ``labels`` indexes palette.tones (i.e. palette.TONE_IDS order); -1 is
    "nothing here", which covers both non-opaque pixels and UNMAPPED ink. The
    unmapped count is in ``stats`` and is budget-gated by the caller, so -1
    cannot quietly become a way to lose artwork.
    """
    from palette import TONE_IDS

    img = img.convert("RGBA")
    arr = np.asarray(img, dtype=np.uint8)
    rgb, alpha = arr[..., :3], arr[..., 3]
    # Denominator pinned to quantise's own min_alpha. The choice is
    # load-bearing and was measured: btc_emission reads 1.556 % undrawn at
    # alpha >= 128 and 16.111 % at alpha >= 1, because the soft edge of a
    # stroke is not the stroke.
    opaque = alpha >= min_alpha

    tone_index = {tid: i for i, tid in enumerate(TONE_IDS)}
    for ink in tmap.inks:
        if ink.tone not in tone_index:
            raise ToneMapError(
                f"{tmap.source or 'tone map'}: {ink.hex} is bound to "
                f"{ink.tone!r}, which is not a tone; known: "
                f"{' '.join(TONE_IDS)}")

    ink_rgb = np.array([i.rgb for i in tmap.inks], dtype=np.float64)
    A = _weighted(np.array([i.rgb for i in tmap.inks], dtype=np.uint8))
    P = _weighted(rgb)

    dsq = _squared_distances(P, A)
    order = np.argsort(dsq, axis=-1, kind="stable")
    i1 = order[..., 0]
    d1 = np.sqrt(np.take_along_axis(dsq, i1[..., None], -1)[..., 0])
    if len(tmap.inks) > 1:
        i2 = order[..., 1]
        d2 = np.sqrt(np.take_along_axis(dsq, i2[..., None], -1)[..., 0])
    else:
        i2 = i1
        d2 = np.full(d1.shape, np.inf)

    tol = float(tmap.tol_de)
    # (2) unique match: inside tol of exactly one declared ink.
    unique = (d1 <= tol) & (d2 > tol)
    ink_of = np.where(unique, i1, -1)

    # (3) everything else opaque is tested as a convex blend of a PAIR of
    # declared inks, swept over every pair rather than only over the two
    # nearest. The two-nearest shortcut is wrong exactly where it matters:
    # MEASURED on satoshi_points, a mid grey #797877 is a blend of the white
    # #fefefe and the black #010101, but in weighted Lab its two NEAREST
    # declared inks are the two golds (57.5 and 79.8 units) because the black
    # and the white are both ~100 units away at opposite ends of the same
    # segment. Restricted to the golds it fits nothing and falls out as
    # unmapped: 2.996 % of the ink against a 0.25 % budget, i.e. a refusal for
    # a picture that is perfectly well declared. With the full sweep the
    # correct pair is available and the same piece lands at 0.114 %.
    #
    # Residual is to the SEGMENT, not to the infinite line: a pixel beyond an
    # endpoint is exactly as far away as it is from that endpoint, and
    # pretending otherwise is how a flat off-palette field gets reinterpreted
    # as a boundary. w0_spike used an interiority margin (MIX_EDGE) for the
    # same purpose; clamping t is the same statement without the constant.
    todo = opaque & ~unique
    blend_ok = np.zeros(opaque.shape, dtype=bool)
    n_ink = len(tmap.inks)
    if todo.any() and n_ink > 1:
        best_res = np.full(P.shape[:2], np.inf)
        pa = np.zeros(P.shape[:2], dtype=np.int64)
        pb = np.zeros(P.shape[:2], dtype=np.int64)
        for a in range(n_ink):
            for b in range(a + 1, n_ink):
                u = A[b] - A[a]
                uu = float((u * u).sum())
                if uu <= 0:
                    continue
                t = np.clip(((P - A[a]) @ u) / uu, 0.0, 1.0)
                foot = A[a] + t[..., None] * u
                r = np.linalg.norm(P - foot, axis=-1)
                upd = r < best_res            # strict: ties keep the lower pair
                best_res = np.where(upd, r, best_res)
                pa = np.where(upd, a, pa)
                pb = np.where(upd, b, pb)
        blend_ok = todo & (best_res < MIX_MAX_RES)

        cov, eps = _coverage(rgb.astype(np.float64), ink_rgb, pa, pb)
        # Split toward the MINORITY ink of the pair, by confident support, so
        # a half-covered cell goes to the thin feature rather than to whichever
        # colour sorts first. `eps` is w0_spike's exact 8-bit rounding bound:
        # a 1 px stroke centred on a pixel boundary puts both cells at exactly
        # 0.5, and without it the 8-bit encoding casts the deciding vote.
        support = np.bincount(i1[opaque & unique].ravel(), minlength=n_ink)
        sa, sb = support[pa], support[pb]
        take_b = np.where(sb <= sa, cov >= MIX_SPLIT - eps,
                          cov > 1.0 - MIX_SPLIT + eps)
        ink_of = np.where(blend_ok, np.where(take_b, pb, pa), ink_of)

    ink_of = np.where(opaque, ink_of, -1)

    tone_of_ink = np.array([tone_index[i.tone] for i in tmap.inks],
                           dtype=np.int64)
    labels = np.where(ink_of >= 0, tone_of_ink[np.clip(ink_of, 0, None)], -1)
    labels = np.where(opaque & (ink_of < 0), -1, labels).astype(np.int64)

    unmapped = opaque & (ink_of < 0)
    total = int(opaque.sum())
    n_unmapped = int(unmapped.sum())

    per_ink = {}
    for k, ink in enumerate(tmap.inks):
        n = int((ink_of == k).sum())
        if n:
            per_ink[ink.hex] = {"tone": ink.tone, "px": n,
                                "share_pct": round(100.0 * n / max(total, 1), 4)}

    per_tone = {}
    for tid, idx in tone_index.items():
        n = int(((labels == idx) & opaque).sum())
        if n:
            per_tone[tid] = n

    orphans = []
    if n_unmapped:
        orphans = _orphan_census(rgb, unmapped, total, palette)

    stats = {
        "opaque_px": total,
        "assigned_px": total - n_unmapped,
        "dropped_px": n_unmapped,
        "per_tone": per_tone,
        "per_tone_naive": dict(per_tone),   # no naive pass here: nothing guessed
        "resolver": "tone_map",
        "tonemap_digest": tmap.digest(),
        "tol_de": tol,
        "per_ink": per_ink,
        "unmapped_px": n_unmapped,
        "unmapped_pct": round(100.0 * n_unmapped / max(total, 1), 4),
        "unmapped_budget_pct": float(tmap.unmapped_budget_pct),
        "unmapped_orphans": orphans,
        "blend_px": int((blend_ok & opaque).sum()),
        "unique_px": int((unique & opaque).sum()),
        "mixture": {"enabled": True, "mixture_px": int((blend_ok & opaque).sum()),
                    "reassigned_px": 0, "pairs": {}, "moves": {},
                    "tones_eliminated": [], "established": [],
                    "params": {"mix_split": MIX_SPLIT,
                               "mix_max_res": MIX_MAX_RES, "tol_de": tol}},
    }

    # (6) DISTINGUISHABILITY of declared merges (issue #17). Every other
    # check in this file measures ink that is drawn; a merged ink is drawn,
    # just in its neighbour's colour, so a feature drawn ONLY in it can
    # vanish while every drawn-ness number stays perfect. This census is the
    # check that measures the vanishing, and the caller gates it.
    stats["merge_erasure"] = _merge_erasure(ink_of, opaque, tmap)

    # (5) POST-ASSERTION, on the OUTPUT rather than on the domain. Every label
    # that exists is a tone that draws, unless a declared ink named the
    # background on purpose. This is an internal error, not a warning: if it
    # ever fires, the resolver has silently lost artwork and no downstream
    # number would show it.
    from palette import BACKGROUND_TONE
    declared_bg = {tone_index[i.tone] for i in tmap.inks
                   if i.tone == BACKGROUND_TONE}
    drawn = {int(v) for v in np.unique(labels) if v >= 0}
    bad = {TONE_IDS[v] for v in drawn - declared_bg
           if not palette[TONE_IDS[v]].emits}
    if bad:
        raise AssertionError(
            f"tone_map produced non-drawing tone(s) {sorted(bad)} that no "
            f"declared ink asked for -- artwork would be lost silently")

    return labels, opaque, stats


def _shift(m: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """`m` moved by (dy, dx), padding with False: off-image is background."""
    out = np.zeros_like(m)
    h, w = m.shape
    ys = slice(max(dy, 0), h + min(dy, 0))
    xs = slice(max(dx, 0), w + min(dx, 0))
    yd = slice(max(-dy, 0), h + min(-dy, 0))
    xd = slice(max(-dx, 0), w + min(-dx, 0))
    out[ys, xs] = m[yd, xd]
    return out


def enclosed_components(member_of, opaque, k: int, group: set[int]) -> list[dict]:
    """The connected regions of ink ``k`` and who owns each region's border.

    ``member_of`` maps each pixel to an ink index (-1 = nothing). For every
    8-connected component of ``member_of == k``, its border pixels-adjacencies
    are classified three ways: against another member of ``group`` (the inks
    this one declared merge_ok with), against any OTHER opaque ink, and
    against background. ``enclosure`` is group / (group + other) -- the share
    of the component's DRAWN border that is the very ink it merges into.

    Background border is excluded from the denominator on purpose: where a
    merged region runs to the silhouette, that edge is the merge partner's
    silhouette too, and it survives the merge unchanged. What makes a feature
    visible after a merge is a border against a tone that renders differently
    -- and only the "other" bucket has one. A component with NO drawn border
    at all (a free-standing island) is not enclosed by anything and reads
    enclosure 0.0.
    """
    import prep_assets

    m = (member_of == k)
    lbl, n = prep_assets._label8(m)
    if n == 0:
        return []
    partner = np.isin(member_of, [i for i in group if i != k]) & opaque
    other = opaque & (member_of != k) & ~partner
    grp_b = np.zeros(n + 1, dtype=np.int64)
    oth_b = np.zeros(n + 1, dtype=np.int64)
    bg_b = np.zeros(n + 1, dtype=np.int64)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            nb_partner = _shift(partner, dy, dx)
            nb_other = _shift(other, dy, dx)
            nb_same = _shift(m, dy, dx)
            nb_bg = ~(nb_partner | nb_other | nb_same)
            grp_b += np.bincount(lbl[nb_partner & m], minlength=n + 1)
            oth_b += np.bincount(lbl[nb_other & m], minlength=n + 1)
            bg_b += np.bincount(lbl[nb_bg & m], minlength=n + 1)
    px = np.bincount(lbl[m], minlength=n + 1)
    out = []
    for c in range(1, n + 1):
        drawn = int(grp_b[c] + oth_b[c])
        enc = (grp_b[c] / drawn) if drawn else 0.0
        out.append({
            "px": int(px[c]),
            "border_partner": int(grp_b[c]),
            "border_other": int(oth_b[c]),
            "border_background": int(bg_b[c]),
            "enclosure": round(float(enc), 4),
            "erased": bool(drawn and enc >= MERGE_ENCLOSED_MIN_FRAC),
        })
    out.sort(key=lambda r: -r["px"])
    return out


def _merge_erasure(ink_of, opaque, tmap: "ToneMap") -> list[dict]:
    """Per declared-merge ink: how much of it forms enclosed, erased regions.

    Only non-dominant members of each merge group are examined: the group's
    largest ink is the field the others disappear into, and a field is not a
    feature. Antialias fringe between two inks is immune twice over -- blend
    pixels resolve to one endpoint of the pair they actually blend, and
    whatever slips through totals far under MERGE_ERASED_FAIL_PCT, which is
    the caller's gate.
    """
    groups = tmap.merge_groups()
    if not groups:
        return []
    idx_of = {ink.hex: i for i, ink in enumerate(tmap.inks)}
    counts = np.bincount(ink_of[ink_of >= 0].ravel(), minlength=len(tmap.inks))
    total = max(int(opaque.sum()), 1)
    out = []
    for g in groups:
        idxs = [idx_of[h] for h in g]
        field = max(idxs, key=lambda i: int(counts[i]))
        gset = set(idxs)
        for k in idxs:
            if k == field or counts[k] == 0:
                continue
            comps = enclosed_components(ink_of, opaque, k, gset)
            erased_px = sum(c["px"] for c in comps if c["erased"])
            out.append({
                "hex": tmap.inks[k].hex,
                "tone": tmap.inks[k].tone,
                "merged_into": [tmap.inks[i].hex for i in sorted(gset - {k})],
                "ink_px": int(counts[k]),
                "ink_pct": round(100.0 * int(counts[k]) / total, 4),
                "erased_px": int(erased_px),
                "erased_pct": round(100.0 * erased_px / total, 4),
                "erase_ok": tmap.inks[k].erase_ok,
                "components": comps[:12],
                "n_components": len(comps),
                "n_erased": sum(1 for c in comps if c["erased"]),
            })
    return out


def _orphan_census(rgb, unmapped, total, palette):
    """The undeclared colours, biggest first, so the refusal can name them."""
    px = rgb[unmapped]
    if px.size == 0:
        return []
    # Bucket to 8 levels per channel: enough to name a colour, coarse enough
    # that antialias noise does not produce ten thousand "orphans".
    q = (px.astype(np.int64) >> 5)
    key = (q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2]
    uk, counts = np.unique(key, return_counts=True)
    out = []
    for k, n in sorted(zip(uk.tolist(), counts.tolist()),
                       key=lambda kv: (-kv[1], kv[0]))[:12]:
        sel = key == k
        mean = px[sel].mean(axis=0)
        row = {"hex": rgb_to_hex(np.round(mean).astype(int)),
               "px": int(n), "share": round(100.0 * n / max(total, 1), 3)}
        if palette is not None:
            row["lstar"] = round(palette.lstar_of_rgb(np.round(mean)), 1)
            # Front-side legible tones only: an orphan is being suggested a
            # home, and suggesting an inner-layer one would be suggesting a
            # criterion-3 violation.
            leg = palette.legible(allow_inner=False)
            if leg:
                d = {t: float(np.linalg.norm(
                    _weighted(np.array(palette[t].rgb, dtype=np.uint8))
                    - _weighted(np.round(mean).astype(np.uint8)))) for t in leg}
                row["nearest_legible"] = min(d, key=d.get)
        out.append(row)
    return out
