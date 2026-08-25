#!/usr/bin/env python3
"""Generate the calibration ladders for the art test coupon (issue #6).

These are the parts of the coupon that are PARAMETRIC GEOMETRY, not image
conversion — so they depend on nothing that is still being calibrated, and can
be built before the quantiser is finished. The real-asset comparisons are placed
separately.

Every block is self-labelling. A measurement that needs a drawing to interpret
does not get made.

This module also owns the footprint writer (`Fp`) shared with coupon_blocks.py
and emit_art.py, and with it the fabrication-floor guard — see below.

Usage:  python coupon_ladders.py -o RecklessArt.pretty
"""

import argparse
import math
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import stroke_font as SF                                   # noqa: E402
import sweep_decls                                         # noqa: E402

MM = 1.0

# --- Fabrication floors ----------------------------------------------------
# AUTHORITY: docs/pcb-palette.md — table "Practical limits", plus "Mask dams"
# in the shading section. The values below are only the fallback for when that
# file cannot be read; _load_floors() prefers the doc and records a note if the
# two ever disagree, so this writer and tools/verify_art.py cannot drift apart
# on what the floor is.
#
# None of these is a style preference. Silk narrower than the silk floor is ink
# the screen may not carry; copper or mask narrower than theirs is metal or an
# opening the fab may not hold. A coupon may cross these lines ON PURPOSE —
# that is exactly what cal_minfeature_*, cal_text and the duty ramps are for —
# but it has to SAY so, by passing allow_below_floor=True, so that an accident
# can never be mistaken for an experiment.
FLOOR_SILK = 0.15         # silkscreen minimum feature
FLOOR_MASK = 0.10         # mask-opening minimum feature
FLOOR_COPPER = 0.10       # copper minimum feature
FLOOR_MASK_DAM = 0.10     # mask REMAINING between two adjacent openings

# Layers the doc gives no floor for, left unchecked rather than guessed at:
#   In*.Cu     "considerably larger — see below", no number. cal_buried exists
#              to measure it; verify_art.py carries a PROVISIONAL 0.50 mm.
#   Edge.Cuts  the feature is the routed slot width, not the stroke.
#   Dwgs.User and friends — annotation, never fabricated.
STROKE_ABS_MIN = 0.05     # KiCad sanity value for unfloored layers, NOT a fab number

# Stroke-to-height for KiCad's built-in stroke font. The doc puts legible text
# at 1:6 to 1:8; 0.15 is 1:6.7 and sits inside that.
TEXT_STROKE_RATIO = 0.15

# Label geometry. The doc's legibility floor for silk text is 0.9 mm, and a
# label must never be the thing that fails, so nothing annotates below it.
# These are MINIMA, not the caps that get drawn: solved_cap() raises each label
# to the height its own letterforms need -- see below.
# 1.0, not the doc's 0.9: JLCPCB's capabilities page publishes 1.0 mm as the
# minimum silk TEXT height, tools/fix_projects.py arms it as a KiCad design
# rule, and 0.9 mm labels produced 7 text_height violations on the beta coupon.
# A label that the fab's own DRC rejects is a label that is the thing failing,
# which is the one thing these are not allowed to be. The doc's 0.9 is a
# legibility floor; this is a process floor, and the coarser of the two wins.
LABEL_H = 1.0
BLOCK_LABEL_H = 1.2

# THE LABEL PEN IS FIXED, AND THAT IS THE WHOLE FIX.
#
# text() used to size the stroke as a RATIO of the cap and raise it to the
# floor. That clamps the stroke and leaves the cap unsolved, so a label's
# inter-glyph, intra-glyph and counter gaps -- every one of which is
# `em * cap - stroke` -- went under the floor and nothing noticed. On the beta
# coupon that produced 0.041715 mm gaps in the tone names against a 0.150 mm
# floor, and 38 places where a closing at the floor genuinely bridges.
#
# A proportional pen also makes the solve diverge: with stroke = 0.15*cap the
# clear width is cap*(em - 0.15), so an inter-glyph pair at em 0.19048 needs a
# 3.7 mm cap. Holding the pen FIXED makes it cap = (floor + pen)/em, which is
# 1.386 mm for the same pair -- a label, not a headline. This is the same
# model art-coupon/tools/gen_marking.py has always used, and the marking is
# the one thing on both cards that has always been clean.
#
# 0.18 mm is that pen: 20% over the 0.15 mm silk floor, so the stroke itself
# has margin instead of sitting exactly on the limit.
LABEL_PEN = 0.18

# Labels are solved 5% CLEAR of the floor, not onto it. Solving to equality
# lands a label's tightest gap at exactly the floor, which every margin line in
# tools/verify_art.py then reports as "ON THE FLOOR ... a pass with no
# headroom, not a clean pass" -- and it is right to. A label must never be the
# marginal thing on a card whose whole purpose is to measure margins.
LABEL_MARGIN = 0.05

# The deliberate bottom of a sweep: below every fabrication floor, on purpose.
SWEEP_MIN = 0.05

# --- sweep declarations ----------------------------------------------------
# A ladder that goes under the floor says so IN THE ARTEFACT, in the same tags
# field the fab: tag lives in, so tools/verify_art.py can tell a deliberate
# sub-floor rung from an accidental one. See tools/sweep_decls.py.
#
# EVERY NUMBER IN A DECLARATION COMES FROM A DESIGN CONSTANT. Not one of them
# is read back off self.items after drawing: a band derived from the geometry
# it describes always matches that geometry, which is the verifier echoing the
# emitter's own attribute one level up, and it would make the whole mechanism
# vacuous.
SWEEP_REF = "kicad_art_generator#6"

# Measurement allowance, mm. The region measurement builds strokes by buffering
# with a 16-segment quadrant approximation, so a 0.075 mm square reads back as
# 0.074996 mm. 1 um covers that with three orders of magnitude to spare and is
# far below any defect worth the name -- it is not slack in the band.
SWEEP_BAND_SLACK = 0.001

# The converging wedge's smallest INTENDED separated gap is start_gap/steps.
# Measured it comes back a little under nominal, because the two inflated
# capsule boundaries meet at an angle. 10% covers that. It is for measurement
# geometry, not for slack: a defect at 0.001 mm is still 15x under the bound.
GAP_MEASURE_SLACK = 0.9

FLOOR_SOURCE = "built-in defaults"
FLOOR_NOTES: list[str] = []


def _load_floors(doc: pathlib.Path | None = None) -> None:
    """Read the floors out of docs/pcb-palette.md, which is the authority.

    Deliberately the same table and the same regexes as verify_art.py's
    load_palette(): if the doc changes, the emitter and the acceptance harness
    move together instead of one of them silently lagging.
    """
    global FLOOR_SILK, FLOOR_MASK, FLOOR_COPPER, FLOOR_MASK_DAM, FLOOR_SOURCE
    doc = doc or (pathlib.Path(__file__).resolve().parent.parent
                  / "docs" / "pcb-palette.md")
    if not doc.is_file():
        FLOOR_NOTES.append(f"palette doc not found at {doc} -- using built-in "
                           f"floors. FIX THIS: the doc is the authority.")
        return

    text = doc.read_text(encoding="utf-8", errors="replace")
    cur = {"silk": FLOOR_SILK, "mask": FLOOR_MASK,
           "copper": FLOOR_COPPER, "dam": FLOOR_MASK_DAM}
    for key, pat in (
        ("silk",   r"\|\s*silkscreen\s*\|\s*~?([\d.]+)\s*mm"),
        ("mask",   r"\|\s*mask opening\s*\|\s*~?([\d.]+)\s*mm"),
        ("copper", r"\|\s*copper\s*\|\s*~?([\d.]+)\s*mm"),
        ("dam",    r"must stay above\s+roughly\s*([\d.]+)\s*mm"),
    ):
        m = re.search(pat, text, re.I)
        if not m:
            FLOOR_NOTES.append(f"could not read the {key} floor from {doc.name}; "
                               f"keeping built-in {cur[key]} mm")
            continue
        v = float(m.group(1))
        if abs(v - cur[key]) > 1e-9:
            FLOOR_NOTES.append(f"{key} floor: doc says {v} mm, built-in default "
                               f"was {cur[key]} mm -- using the doc")
        cur[key] = v

    FLOOR_SILK, FLOOR_MASK, FLOOR_COPPER, FLOOR_MASK_DAM = (
        cur["silk"], cur["mask"], cur["copper"], cur["dam"])
    FLOOR_SOURCE = str(doc)


_load_floors()


class CapTooSmall(RuntimeError):
    """A label whose own letterforms close up at the size it was asked for."""


def solved_cap(s: str, layer: str, pen: float, minimum: float = 0.0,
               margin: float = LABEL_MARGIN) -> tuple[float, str]:
    """Smallest cap at which every gap in `s` clears `layer`'s floor at `pen`.

    -> (cap_mm, what binds). The constraints come from
    stroke_font.gap_constraints(): the stroke itself, the inter-glyph
    sidebearings, a glyph's own detached pieces, and closed counters. Sizing
    on a subset of those is the defect this exists to close -- the tone names
    were sized on none of them.

    `margin` is solved for as extra floor, so the answer clears the real floor
    by that fraction rather than landing exactly on it. Pass margin=0.0 to ask
    the bare question, which is what _cap_check() does: the emitter aims 5%
    high, and refuses only at the floor itself.
    """
    floor, _cls = floor_for(layer)
    if floor is None or not s.strip():
        return max(minimum, 0.0), "no floor on this layer"
    target = floor * (1.0 + margin)
    m = SF.measure_string(s)
    if m.unmeasured:
        raise CapTooSmall(
            f"{s!r} contains characters with no measured letterform "
            f"({''.join(sorted(set(m.unmeasured)))!r}), so its gaps cannot be "
            f"solved against the {floor:.3f} mm floor")
    need, binds = 0.0, "nothing"
    for c in SF.gap_constraints(m):
        if c.em is None:
            continue
        cap = (target + pen) / c.em
        if cap > need:
            need, binds = cap, f"{c.name} ({c.detail})"
    return max(need, minimum), binds


def floor_for(layer: str) -> tuple[float | None, str]:
    """(floor_mm, class) for a layer. floor is None where the doc gives none."""
    if layer.endswith(".SilkS"):
        return FLOOR_SILK, "silk"
    if layer.endswith(".Mask"):
        return FLOOR_MASK, "mask"
    if layer in ("F.Cu", "B.Cu"):
        return FLOOR_COPPER, "copper"
    if re.fullmatch(r"In\d+\.Cu", layer or ""):
        return None, "buried"
    if layer == "Edge.Cuts":
        return None, "edge"
    return None, "other"


# --- what gets swept -------------------------------------------------------
# Discrete rungs answer "does 0.1 mm work?" -- a value you can quote to a fab.
# The converging wedges answer "where exactly does it stop?" Both are wanted;
# they are different questions.
FEATURE_STEPS = [0.05, 0.075, 0.10, 0.125, 0.15, 0.20, 0.30]
HATCH_PITCHES = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
TEXT_CU = [0.4, 0.5, 0.6, 0.8, 1.0, 1.5]
TEXT_SILK = [0.6, 0.8, 1.0, 1.2, 1.5, 2.0]

# Closed counters fail before straight strokes do, so the string has to contain
# some. A row of capitals would flatter the result.
SPECIMEN = "Reckless 0123 mkgB8@"

LAYERS = {"silk": "F.SilkS", "copper": "F.Cu", "mask": "F.Mask"}


class Fp:
    """Minimal KiCad footprint writer. Modern (footprint ...) form, 20241229.

    Guards the fabrication floor: every drawn feature is measured against the
    floor for its layer, and anything under it warns to stderr naming the call
    site that asked for it. Deliberate sub-floor geometry passes
    allow_below_floor=True and is silent.

    The guard's scope is FEATURE SIZE, not gaps. A mask dam is the space
    *between* two features and cannot be seen from inside a single write call;
    that is verify_art.py's clearance check, which reasons over the whole
    footprint at once. The two together cover both halves.
    """

    def __init__(self, name):
        self.name = name
        self.items = []
        self._n = 0
        # (call site, layer, width, what) -> count, for the end-of-run tally
        self.floor_hits: dict[tuple, int] = {}
        # Sweep declaration tokens, in tag order. Written into `tags` by
        # dumps() and read back by tools/verify_art.py.
        self.sweeps: list[str] = []
        # Every DELIBERATE sub-floor draw: (layer, bbox, what, site, width).
        # write_footprint() refuses to write a footprint that has one of these
        # outside every box it declared, which is what stops the emitter
        # drawing deliberate sub-floor geometry it never told anyone about.
        self.deliberate: list[tuple] = []

    def _uuid(self):
        self._n += 1
        return f"c0up0n00-0000-0000-0000-{self._n:012d}"

    # --- fabrication-floor guard -------------------------------------------

    def _caller(self) -> str:
        """The nearest frame that is not a method call on this writer.

        Walks by object identity rather than by filename, because the block
        functions below live in the same module as Fp — a filename test would
        skip straight past them and blame main().
        """
        f = sys._getframe(1)
        while f is not None and f.f_locals.get("self", None) is self:
            f = f.f_back
        if f is None:
            return "<unknown caller>"
        return (f"{pathlib.Path(f.f_code.co_filename).name}:{f.f_lineno} "
                f"in {f.f_code.co_name}()")

    def _floor_check(self, w, layer, what, allow_below_floor, bbox=None):
        if w is None or w <= 0:
            return
        floor, cls = floor_for(layer)
        if floor is None or w >= floor - 1e-9:
            return
        if allow_below_floor:
            # Declared deliberate in CODE. That is half a declaration: the
            # other half has to reach the verifier, and write_footprint()
            # checks that it did.
            self.deliberate.append((layer, bbox, what, self._caller(), w))
            return
        site = self._caller()
        key = (site, layer, round(float(w), 4), what)
        seen = self.floor_hits.get(key, 0)
        self.floor_hits[key] = seen + 1
        if seen == 0:   # first of its kind: say it once, loudly
            print(f"FLOOR: {self.name}: {what} {w:.4f} mm on {layer} is under "
                  f"the {floor:.3f} mm {cls} floor -- {site}  "
                  f"[pass allow_below_floor=True if this is deliberate]",
                  file=sys.stderr)

    # --- extents, computed FORWARD from the parameters ---------------------
    # Never read back off self.items. A block that wants to declare the region
    # it is about to sweep asks these the same question it asks when deciding
    # where to draw, so the declaration and the geometry come from one set of
    # numbers rather than one describing the other.

    @staticmethod
    def line_box(x0, y0, x1, y1, width):
        h = width / 2.0
        return (min(x0, x1) - h, min(y0, y1) - h,
                max(x0, x1) + h, max(y0, y1) + h)

    @staticmethod
    def rect_box(x, y, w, h):
        return (min(x, x + w), min(y, y + h), max(x, x + w), max(y, y + h))

    @staticmethod
    def text_box(s, x, y, height, thickness):
        """Ink box of a `justify left` fp_text, mm.

        Deliberately the SAME computation tools/verify_art.py's _text_box()
        makes, out of the same stroke_font metrics: the emitter and the
        verifier have to agree on where the ink is, or a declaration written
        against one is checked against the other.
        """
        m = SF.measure_string(s, stroke_ratio=(thickness / height)
                              if height > 0 else None)
        if m.ink_em is None:
            return None
        x0, y0, x1, y1 = (v * height for v in m.ink_em)
        pen = thickness / 2.0
        return (x + x0 - pen, y + y0 - pen, x + x1 + pen, y + y1 + pen)

    # --- geometry ----------------------------------------------------------

    def line(self, x0, y0, x1, y1, width, layer, *, allow_below_floor=False):
        self._floor_check(width, layer, "line stroke", allow_below_floor,
                          self.line_box(x0, y0, x1, y1, width))
        self.items.append(
            f'\t(fp_line (start {x0:.4f} {y0:.4f}) (end {x1:.4f} {y1:.4f})\n'
            f'\t\t(stroke (width {width:.4f}) (type solid)) (layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}"))'
        )

    def rect(self, x, y, w, h, layer, *, allow_below_floor=False):
        self._floor_check(min(abs(w), abs(h)), layer, "rect min dimension",
                          allow_below_floor, self.rect_box(x, y, w, h))
        self.items.append(
            f'\t(fp_poly (pts (xy {x:.4f} {y:.4f}) (xy {x+w:.4f} {y:.4f}) '
            f'(xy {x+w:.4f} {y+h:.4f}) (xy {x:.4f} {y+h:.4f}))\n'
            f'\t\t(stroke (width 0) (type solid)) (fill solid) (layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}"))'
        )

    def text(self, s, x, y, height, layer, thickness=None, *,
             allow_below_floor=False):
        """Draw text. The DEFAULT thickness can never breach the floor.

        thickness=None gives the 1:6.7 stroke ratio raised to the layer's floor,
        so an ordinary label is safe by construction and needs no vigilance from
        the caller. Passing an explicit thickness is how a sweep goes below the
        floor deliberately; that path is checked, and wants allow_below_floor.

        `(unlocked yes)` is KiCad's spelling of keep_upright FALSE -- the token
        is inverted, and a fp_text WITHOUT it loads with "Keep upright" ON.
        Keep-upright text refuses to follow a 180 or 270 degree footprint
        rotation (positions rotate, glyph orientation does not), which
        scrambles any text and shreds per-glyph microtext outright. Every
        fp_text this writer emits therefore carries the token; the regression
        test is tests/test_keep_upright.py.
        """
        floor, _ = floor_for(layer)
        if thickness is None:
            t = max(height * TEXT_STROKE_RATIO,
                    floor if floor is not None else STROKE_ABS_MIN)
        else:
            t = thickness
            self._floor_check(t, layer, "text stroke", allow_below_floor,
                              self.text_box(s, x, y, height, t))
        self._cap_check(s, x, y, height, t, layer, allow_below_floor)
        self.items.append(
            f'\t(fp_text user "{s}" (at {x:.4f} {y:.4f}) (unlocked yes) '
            f'(layer "{layer}")\n'
            f'\t\t(uuid "{self._uuid()}")\n'
            f'\t\t(effects (font (size {height:.4f} {height:.4f}) '
            f'(thickness {t:.4f})) (justify left)))'
        )

    def _cap_check(self, s, x, y, height, t, layer, allow_below_floor):
        """A label whose own gaps close at the floor is a defect, and REFUSED.

        Not a warning. A warning is what the old stroke-only clamp effectively
        was, and five findings on the beta coupon went out under it. The one
        legitimate escape is a ladder that sweeps text under the floor on
        purpose -- text_ladder() -- which says so with allow_below_floor.
        """
        if allow_below_floor or not s.strip():
            return
        floor, _cls = floor_for(layer)
        if floor is None:
            return
        try:
            need, binds = solved_cap(s, layer, t, margin=0.0)
        except CapTooSmall as e:
            print(f"CAP: {self.name}: {e}", file=sys.stderr)
            return
        if height < need - 1e-9:
            raise CapTooSmall(
                f"{self.name}: {s[:40]!r} at cap {height:.4f} mm with a "
                f"{t:.4f} mm pen: the {binds} gap clears "
                f"{(need - height):.4f} mm too little against the "
                f"{floor:.3f} mm {layer} floor. Raise the cap to "
                f"{need:.4f} mm, or hold a lighter pen. "
                f"[{self._caller()}]")

    # --- sweep declarations ------------------------------------------------

    def declare_sweep(self, quantity, layer, lo, hi, box, block,
                      ref=SWEEP_REF):
        """State, in the artefact, that `block` sweeps under the floor here.

        `lo`/`hi` must be derived from the module's design constants and `box`
        from the block's own layout parameters. The token is round-tripped
        through the parser here, so a malformed declaration cannot be written
        at all.
        """
        x0, y0, x1, y1 = _round_out(*box)
        self.sweeps.append(sweep_decls.token_for(
            quantity, layer, lo, hi, x0, y0, x1, y1, block, ref))

    def tag_string(self):
        return " ".join(["recklessart", "calibration"] + self.sweeps)

    def dumps(self):
        body = "\n".join(self.items)
        return (
            f'(footprint "{self.name}"\n\t(version 20241229)\n\t(generator "coupon_ladders")\n'
            f'\t(layer "F.Cu")\n'
            f'\t(attr board_only exclude_from_pos_files exclude_from_bom)\n'
            f'\t(descr "Art calibration ladder - see kicad_art_generator#6")\n'
            f'\t(tags "{self.tag_string()}")\n{body}\n)\n'
        )

    # --- labels ------------------------------------------------------------

    def label(self, s, x, y, layer="F.SilkS", minimum=LABEL_H, pen=LABEL_PEN):
        """A label, at the smallest cap its own letterforms survive.

        Returns the cap used. Labels are the one thing on a calibration coupon
        that must never be the thing that fails, so the size is solved rather
        than chosen and the caller's `minimum` is a floor on the answer, not
        the answer.
        """
        cap, _binds = solved_cap(s, layer, pen, minimum=minimum)
        self.text(s, x, y, cap, layer, thickness=pen)
        return cap


def _round_out(x0, y0, x1, y1, dp=3):
    """Round a box OUTWARD to `dp` decimals.

    The token is formatted with %g, which can round a coordinate inward by a
    hair and leave an item that was inside the box a nanometre outside it.
    Rounding out first costs a micron of box and makes the written token mean
    what the caller computed.
    """
    q = 10.0 ** dp
    return (math.floor(x0 * q) / q, math.floor(y0 * q) / q,
            math.ceil(x1 * q) / q, math.ceil(y1 * q) / q)


class UndeclaredSweep(RuntimeError):
    """Deliberate sub-floor geometry that never told the verifier."""


def check_declarations(fp: Fp) -> list[str]:
    """Every deliberate sub-floor draw must fall inside a declared box.

    THIS IS THE LOOP CLOSURE. allow_below_floor=True is the emitter saying
    "this one is on purpose"; a sweep: token is that same statement made
    durable enough to reach tools/verify_art.py. Without this check the two
    can drift, and the drift is silent in exactly the direction that matters:
    geometry that is deliberate in the code and an unexplained FAIL in the
    report.

    -> a list of unverifiable draws (no recorded extent). Raises on any draw
    that IS locatable and is outside every box declared for its layer.
    """
    decls = sweep_decls.from_tags(fp.tag_string())
    bad, unverifiable = [], []
    for layer, bb, what, site, w in fp.deliberate:
        if bb is None:
            unverifiable.append(f"{what} {w:.4f} mm on {layer} at {site}")
            continue
        if any(d.layer == layer and d.quantity in ("width", "vanish")
               and d.box.contains_bbox(bb) for d in decls):
            continue
        bad.append(f"{what} {w:.4f} mm on {layer}, extent "
                   f"({bb[0]:.3f},{bb[1]:.3f})..({bb[2]:.3f},{bb[3]:.3f}), "
                   f"drawn at {site}")
    if bad:
        raise UndeclaredSweep(
            f"{fp.name}: {len(bad)} deliberate sub-floor draw(s) fall outside "
            f"every sweep declaration this footprint carries, so "
            f"tools/verify_art.py will report them as defects and be right to:"
            + "".join(f"\n    {b}" for b in bad)
            + f"\n  declared: "
            + ("; ".join(d.token for d in decls) or "(nothing)"))
    return unverifiable


def write_footprint(fp: Fp, outdir) -> pathlib.Path:
    """Write, then report size and any declared-deliberate floor breaches.

    Each breach already went to stderr as it happened; this is the tally, so a
    long run cannot end with the evidence scrolled off the top. Refuses
    outright when a deliberate breach was never declared to the verifier.
    """
    unverifiable = check_declarations(fp)
    p = pathlib.Path(outdir) / f"{fp.name}.kicad_mod"
    p.write_text(fp.dumps(), encoding="utf-8")
    n = sum(fp.floor_hits.values())
    flag = (f"   ** {n} sub-floor feature(s) at {len(fp.floor_hits)} site(s)"
            if n else "")
    print(f"  {p}  {p.stat().st_size:,} B{flag}")
    if fp.sweeps:
        print(f"      {len(fp.sweeps)} sweep declaration(s) covering "
              f"{len(fp.deliberate)} deliberate sub-floor draw(s)")
        for t in fp.sweeps:
            print(f"        {t}")
    for u in unverifiable:
        print(f"      ! declared deliberate but NO extent was recorded, so "
              f"the declaration could not be checked against it: {u}",
              file=sys.stderr)
    return p


def report_floors():
    print(f"floors: silk {FLOOR_SILK:.3f}  mask {FLOOR_MASK:.3f}  "
          f"copper {FLOOR_COPPER:.3f}  mask-dam {FLOOR_MASK_DAM:.3f} mm "
          f"({FLOOR_SOURCE})")
    for n in FLOOR_NOTES:
        print(f"  ! {n}")


def block_label(fp, s, x, y):
    """Labels are deliberately large: they must never be the thing that fails."""
    return fp.label(s, x, y, minimum=BLOCK_LABEL_H)


# How far a declaration box is opened out past the geometry it fences, mm.
# Small on purpose: the verifier refuses a box more than 1.25x the bounding
# box of what it fences, and a generous margin is a land-grab by another name.
BOX_MARGIN = 0.05


def isolated_features(fp, x0, y0, layer_key):
    """Discrete dots and lines. Finds dropout, which is the failure that matters."""
    layer = LAYERS[layer_key]
    floor = floor_for(layer)[0] or STROKE_ABS_MIN
    # TWO LINES, because the solved cap made one line 83 mm long. At the 1.2 mm
    # cap this caption used to be set at, its 'AT' sidebearing gap measured
    # 0.0486 mm against a 0.150 mm floor and genuinely bridged; solving that
    # away costs a 1.77 mm cap, and 53 characters at 1.77 mm ran clear across
    # the beta coupon's spectre patch -- KiCad DRC: "Silkscreen clipped by
    # solder mask", which means the fab would strip the tail of the sentence
    # that says the sub-floor rungs are deliberate. Two lines keep it inside
    # the block's own column.
    head = f"MIN FEATURE / {layer_key.upper()}"
    cap1, _b = solved_cap(head, "F.SilkS", LABEL_PEN, minimum=BLOCK_LABEL_H)
    block_label(fp, head, x0,
                y0 - 1.6 - (cap1 + LABEL_PEN + FLOOR_SILK + 0.1))
    block_label(fp, f"sweeps under {floor:.2f}mm on purpose", x0, y0 - 1.6)

    # THE DECLARATION, FROM THE DESIGN CONSTANTS. FEATURE_STEPS decides the
    # band; the row pitch, the two column offsets and the widest rung decide
    # the box. Both are known before a single item is drawn, and neither is
    # read back afterwards -- see the note on SWEEP_REF.
    dmin, dmax = min(FEATURE_STEPS), max(FEATURE_STEPS)
    pitch, n = 1.6, len(FEATURE_STEPS)
    box = (x0 + 5.0 - BOX_MARGIN,
           y0 - BOX_MARGIN,
           x0 + 11.0 + dmax / 2.0 + BOX_MARGIN,
           y0 + pitch * (n - 1) + dmax + BOX_MARGIN)
    lo, hi = dmin - SWEEP_BAND_SLACK, dmax + SWEEP_BAND_SLACK
    # `width` and `vanish` are declared SEPARATELY and neither implies the
    # other. "This feature is thin" and "this feature is meant to disappear at
    # the floor" are different claims, and artwork silently deleted at the
    # floor has already cost this project three characters' limbs.
    fp.declare_sweep("width", layer, lo, hi, box, "rungs")
    fp.declare_sweep("vanish", layer, lo, hi, box, "rungs")

    y = y0
    for d in FEATURE_STEPS:
        # The rung label sits LEFT of the box, so a declaration written for
        # copper rungs can never reach the silk that annotates them.
        fp.label(f"{d:.3f}", x0, y + 0.4)
        # A dot and a 4 mm line at the same dimension. The bottom rungs are
        # under the floor and are meant to be: the rung that disappears IS the
        # measurement. Declared, so the guard stays quiet about it.
        fp.rect(x0 + 5.0, y, d, d, layer, allow_below_floor=True)
        fp.line(x0 + 7.0, y + d / 2, x0 + 11.0, y + d / 2, d, layer,
                allow_below_floor=True)
        y += pitch
    return y


def converging_pair(fp, x0, y0, layer_key, length=14.0, start_gap=1.0,
                    steps=60):
    """Continuous wedge: read the merge point directly instead of interpolating."""
    layer = LAYERS[layer_key]
    block_label(fp, f"CONVERGE / {layer_key.upper()} 1.0-0mm", x0, y0 - 1.6)
    # The GAP is what is being swept here, so the stroke is held at the silk
    # floor — at or above every layer's floor — to keep the stroke from being
    # the thing that fails first.
    w = FLOOR_SILK

    # THE BAND. The wedge sweeps the gap continuously to ZERO, so the naive
    # band would be 0..start_gap -- a bound that bounds nothing, and rejected
    # by sweep_decls' hard 0.010 mm floor. It is not needed: a touching pair is
    # one component and never was a finding, so the only gaps that ever reach
    # judgement are the SEPARATED ones, whose smallest intended value is
    # start_gap/steps.
    lo = (start_gap / steps) * GAP_MEASURE_SLACK
    box = (x0 - w / 2.0 - BOX_MARGIN, y0 - start_gap / 2.0 - w / 2.0 - BOX_MARGIN,
           x0 + length + w / 2.0 + BOX_MARGIN,
           y0 + start_gap / 2.0 + w / 2.0 + BOX_MARGIN)
    fp.declare_sweep("gap", layer, lo, start_gap + SWEEP_BAND_SLACK, box,
                     "converge")

    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        g0, g1 = start_gap * (1 - t0), start_gap * (1 - t1)
        xa, xb = x0 + length * t0, x0 + length * t1
        fp.line(xa, y0 - g0 / 2, xb, y0 - g1 / 2, w, layer)
        fp.line(xa, y0 + g0 / 2, xb, y0 + g1 / 2, w, layer)
    return y0 + 2.0


def hatch_ladder(fp, x0, y0, layer_key="silk", block=8.0):
    """Pitch sweep, each block ramping duty 20->80% by line width."""
    layer = LAYERS[layer_key]
    floor = floor_for(layer)[0] or STROKE_ABS_MIN

    def duty_of(i, n):
        return 0.2 + 0.6 * (i / max(n - 1, 1))

    # Design constants first, geometry second. The widest stroke sets how far
    # the field's ink reaches past its nominal box; the pitch that packs the
    # most rows sets how tall it is.
    wmax = max(max(p * duty_of(n - 1, n), SWEEP_MIN)
               for p in HATCH_PITCHES for n in (int(block / p),))
    wmin = max(min(min(p * duty_of(i, int(block / p)), 1.0)
                   for p in HATCH_PITCHES
                   for i in range(int(block / p))), SWEEP_MIN)
    span_y = max((int(block / p) - 1) * p for p in HATCH_PITCHES)
    x_end = x0 + (len(HATCH_PITCHES) - 1) * (block + 2.0) + block
    box = (x0 - wmax / 2.0 - BOX_MARGIN, y0 - wmax / 2.0 - BOX_MARGIN,
           x_end + wmax / 2.0 + BOX_MARGIN,
           y0 + span_y + wmax / 2.0 + BOX_MARGIN)
    lo, hi = wmin - SWEEP_BAND_SLACK, wmax + SWEEP_BAND_SLACK
    fp.declare_sweep("width", layer, lo, hi, box, "hatch")
    fp.declare_sweep("vanish", layer, lo, hi, box, "hatch")

    # The captions are kept CLEAR of the declaration box, not merely on a
    # different layer -- on cal_hatch_silk the ramp and its labels share
    # F.SilkS, and a label that strays inside the box is a label a copper
    # declaration could not protect but a silk one could.
    block_label(fp, f"HATCH PITCH / {layer_key.upper()} duty 20-80% - ramp "
                    f"runs under {floor:.2f}mm", x0, box[1] - 2.4)
    x = x0
    for pitch in HATCH_PITCHES:
        fp.label(f"{pitch:.1f}", x, box[1] - 0.9)
        n = int(block / pitch)
        for i in range(n):
            yy = y0 + i * pitch
            # At the tight pitches the low-duty end lands under the floor. That
            # is the question the ladder exists to answer — at what pitch and
            # duty does hatch stop rendering as tone — so it is declared here
            # rather than clamped, and the block label says so on silk.
            w = max(pitch * duty_of(i, n), SWEEP_MIN)
            fp.line(x, yy, x + block, yy, w, layer, allow_below_floor=True)
        x += block + 2.0
    return y0 + block + 2.0


def text_ladder(fp, x0, y0, layer_key, sizes):
    layer = LAYERS[layer_key]
    floor = floor_for(layer)[0] or STROKE_ABS_MIN
    block_label(fp, f"MICROTEXT / {layer_key.upper()} - stroke sweeps under "
                    f"{floor:.2f}mm", x0, y0 - 1.6)

    # The specimen's extent at each size, computed forward from the size list
    # and the string -- the same stroke_font metrics the verifier will measure
    # it with. Unioned into one box before anything is drawn.
    bx0 = by0 = bx1 = by1 = None
    y = y0
    for h in sizes:
        b = Fp.text_box(SPECIMEN, x0 + 4.0, y, h, h * TEXT_STROKE_RATIO)
        if b is not None:
            bx0 = b[0] if bx0 is None else min(bx0, b[0])
            by0 = b[1] if by0 is None else min(by0, b[1])
            bx1 = b[2] if bx1 is None else max(bx1, b[2])
            by1 = b[3] if by1 is None else max(by1, b[3])
        y += h + 1.2
    pens = [h * TEXT_STROKE_RATIO for h in sizes]
    fp.declare_sweep("width", layer, min(pens) - SWEEP_BAND_SLACK,
                     max(pens) + SWEEP_BAND_SLACK,
                     (bx0 - BOX_MARGIN, by0 - BOX_MARGIN,
                      bx1 + BOX_MARGIN, by1 + BOX_MARGIN),
                     "microtext")
    fp.declare_sweep("vanish", layer, min(pens) - SWEEP_BAND_SLACK,
                     max(pens) + SWEEP_BAND_SLACK,
                     (bx0 - BOX_MARGIN, by0 - BOX_MARGIN,
                      bx1 + BOX_MARGIN, by1 + BOX_MARGIN),
                     "microtext")

    y = y0
    for h in sizes:
        fp.label(f"{h:.1f}", x0, y)
        # The specimen IS the sweep. Hold the 1:6.7 stroke ratio all the way
        # down, through the floor, and let the coupon report where the glyphs
        # stop resolving. Passed explicitly rather than taking the floor-raised
        # default, which would flatten the bottom of the ladder into a row of
        # identical strokes and destroy the measurement.
        fp.text(SPECIMEN, x0 + 4.0, y, h, layer,
                thickness=h * TEXT_STROKE_RATIO, allow_below_floor=True)
        y += h + 1.2
    return y


def scale_bar(fp, x0, y0, length=20.0):
    """Self-calibrating: features can be measured off a photograph."""
    # The major ticks rise 1.2 mm from the baseline, so the standard -1.6 mm
    # label position puts the caption straight through them (visible in a
    # render, invisible in the numbers). Cleared to -2.6.
    block_label(fp, "SCALE 20mm / 1mm ticks", x0, y0 - 2.6)
    # The ruler must survive whatever else on the coupon does not, so it is
    # drawn at the floor, never below it.
    fp.line(x0, y0, x0 + length, y0, FLOOR_SILK, "F.SilkS")
    for i in range(int(length) + 1):
        h = 1.2 if i % 5 == 0 else 0.6
        fp.line(x0 + i, y0, x0 + i, y0 - h, FLOOR_SILK, "F.SilkS")
    return y0 + 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--outdir", default="RecklessArt.pretty")
    args = ap.parse_args()
    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    report_floors()

    built = []
    for key in ("silk", "copper", "mask"):
        fp = Fp(f"cal_minfeature_{key}")
        y = isolated_features(fp, 0, 0, key)
        converging_pair(fp, 0, y + 3.0, key)
        built.append(fp)

    fp = Fp("cal_hatch_silk")
    hatch_ladder(fp, 0, 0, "silk")
    built.append(fp)

    fp = Fp("cal_hatch_copper")
    hatch_ladder(fp, 0, 0, "copper")
    built.append(fp)

    fp = Fp("cal_text")
    y = text_ladder(fp, 0, 0, "copper", TEXT_CU)
    y = text_ladder(fp, 0, y + 3.0, "silk", TEXT_SILK)
    scale_bar(fp, 0, y + 3.0)
    built.append(fp)

    for fp in built:
        write_footprint(fp, out)


if __name__ == "__main__":
    main()
