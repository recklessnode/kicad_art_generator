#!/usr/bin/env python3
"""Sweep declarations: how a calibration ladder says it goes under the floor.

    sweep:<quantity>:<layer>:<lo>..<hi>:<x0>,<y0>,<x1>,<y1>:<block>:<ref>

WHY THIS EXISTS
---------------
A calibration ladder EXISTS to sweep below the fabrication floor and find where
the process actually breaks. `cal_minfeature_copper` draws copper at 0.050 mm
against a 0.0889 mm floor on purpose; the rung that disappears IS the
measurement. tools/verify_art.py measures that correctly and then reaches the
wrong conclusion, and a coupon that can only ever FAIL teaches its reader to
stop reading. A real defect then hides among the expected ones.

WHY IT IS DANGEROUS, AND WHAT IS DONE ABOUT IT
----------------------------------------------
An exemption mechanism is LITERALLY A WAY TO MAKE CHECKS STOP FAILING. This
project has already found eight checks that could not fail what they existed to
catch. So every field below is load-bearing against a specific abuse:

  quantity  a CLOSED ENUM. `vanish` is separate from `width` because "this is
            meant to disappear at the floor" is a much stronger claim than
            "this is thin", and artwork silently deleted at the floor is a
            defect this project has already shipped once.
  layer     exactly ONE layer, no wildcards. On the beta coupon the same
            footprints carry deliberate sub-floor COPPER and accidental
            sub-floor SILK; a footprint-granularity exemption would have
            swallowed five real defects.
  lo..hi    a BOUNDED band. Out-of-band is a FAIL even inside the box: a part
            that promised a range and broke its own promise is worse than one
            that never promised. `lo` has a hard 0.010 mm floor -- zero is not
            a sweep bottom, a feature at zero does not exist and a gap at zero
            is a short.
  box       sub-footprint granularity, because no per-item field survives a
            KiCad round-trip (three separate mechanisms renumber uuids) and
            because the ink measurement has no item identity at all -- it
            returns a coordinate. Coordinates are the only key that works.
  block     named in every report line, so the reader knows what claimed the
            suppression.
  ref       a pointer a reviewer can check. A token without one does not parse.

Malformed is FAIL, never "ignored" -- the same discipline as
tools/fab_profiles.py's from_tags(), which this module is modelled on, and
which lives in the same `tags` field. A fourth token beside `fab:`, `palette:`
and `tonemap:` is not a new dialect.

The verifier owns the rest of the guard rails: only three checks are ever
handed the table, boxes are clipped to the declaring footprint, tightness is
enforced against the geometry actually fenced, and every declaration is printed
verbatim on every run whether it matched anything or not.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

SWEEP_TAG_PREFIX = "sweep:"

# The closed enum. Adding to it is a deliberate act, not a parse accident.
QUANTITIES = ("width", "gap", "vanish")

QUANTITY_MEANS = {
    "width": "ink narrower than the floor, on purpose",
    "gap": "a separation narrower than the floor, on purpose",
    "vanish": "a whole feature the floor deletes, on purpose -- the rung that "
              "disappears IS the measurement",
}

# ABSOLUTE, NON-NEGOTIABLE. A declaration with lo = 0 bounds nothing: it says
# "any value at all down to nothing is expected", which is not a sweep bottom,
# it is a blanket. Rejected the way fab_profiles.from_tags() rejects an unknown
# process key -- refusing to parse, rather than clamping and carrying on.
MIN_LO_MM = 0.010

_LAYER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_BLOCK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class SweepError(ValueError):
    """A declaration that cannot be trusted. Never downgraded to a warning."""


def _cut(a, b, axis: int, v: float):
    """Where segment a-b crosses the line `axis == v`."""
    da, db = a[axis] - v, b[axis] - v
    t = 0.0 if abs(da - db) < 1e-18 else da / (da - db)
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


@dataclass
class Box:
    """A rectangle, in whatever frame its owner is in.

    Kept as four corners rather than as (x0, y0, x1, y1) because a footprint
    placed at an angle turns an axis-aligned local box into a rotated
    quadrilateral on the board, and rounding that back out to an axis-aligned
    bbox would silently enlarge the declaration.
    """
    corners: list                       # [(x, y)] x4, in order

    @staticmethod
    def from_extents(x0, y0, x1, y1) -> "Box":
        return Box([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    @property
    def extents(self):
        xs = [p[0] for p in self.corners]
        ys = [p[1] for p in self.corners]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def area(self) -> float:
        s = 0.0
        n = len(self.corners)
        for i in range(n):
            x1, y1 = self.corners[i]
            x2, y2 = self.corners[(i + 1) % n]
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    def transformed(self, fn) -> "Box":
        return Box([fn(p) for p in self.corners])

    def clipped_to_bbox(self, bb) -> "Box | None":
        """Sutherland-Hodgman against an axis-aligned box. None if nothing left.

        A FOOTPRINT CAN NEVER REACH OUTSIDE ITSELF. Clipping rather than
        rejecting is deliberate: a box drawn a hair past the outermost rung is
        a rounding artefact and should just be trimmed, while a box drawn round
        the whole board is trimmed to the footprint and then fails the
        tightness rule -- which is the check that was going to catch it anyway.
        Rejecting on containment would have made the first case fatal and the
        second no easier to see.
        """
        if bb is None:
            return None
        x0, y0, x1, y1 = bb
        poly = list(self.corners)
        for inside, isect in (
            (lambda p: p[0] >= x0, lambda a, b: _cut(a, b, 0, x0)),
            (lambda p: p[0] <= x1, lambda a, b: _cut(a, b, 0, x1)),
            (lambda p: p[1] >= y0, lambda a, b: _cut(a, b, 1, y0)),
            (lambda p: p[1] <= y1, lambda a, b: _cut(a, b, 1, y1)),
        ):
            out = []
            n = len(poly)
            for i in range(n):
                a, b = poly[i], poly[(i + 1) % n]
                ia, ib = inside(a), inside(b)
                if ia:
                    out.append(a)
                    if not ib:
                        out.append(isect(a, b))
                elif ib:
                    out.append(isect(a, b))
            poly = out
            if not poly:
                return None
        if len(poly) < 3:
            return None
        return Box(poly)

    def contains_point(self, p, eps: float = 1e-9) -> bool:
        """Point in the (convex) quadrilateral, boundary counting as inside."""
        n = len(self.corners)
        sign = 0
        for i in range(n):
            ax, ay = self.corners[i]
            bx, by = self.corners[(i + 1) % n]
            cr = (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)
            if abs(cr) <= eps:
                continue
            s = 1 if cr > 0 else -1
            if sign == 0:
                sign = s
            elif s != sign:
                return False
        return True

    def contains_bbox(self, bb, eps: float = 1e-9) -> bool:
        """Every corner of an axis-aligned bbox inside.

        The bbox of an item is never smaller than the item, so requiring the
        BBOX inside is strictly stronger than requiring the geometry inside.
        The error direction is refusing to exempt something that was in fact
        wholly inside, which is the safe way round.
        """
        if bb is None:
            return False
        x0, y0, x1, y1 = bb
        return all(self.contains_point(p, eps)
                   for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))

    def overlaps(self, other: "Box") -> bool:
        """Separating-axis test on two convex quads."""
        for quad in (self.corners, other.corners):
            n = len(quad)
            for i in range(n):
                ax, ay = quad[i]
                bx, by = quad[(i + 1) % n]
                nx, ny = -(by - ay), (bx - ax)
                l = math.hypot(nx, ny)
                if l < 1e-12:
                    continue
                nx, ny = nx / l, ny / l
                a0 = min(nx * p[0] + ny * p[1] for p in self.corners)
                a1 = max(nx * p[0] + ny * p[1] for p in self.corners)
                b0 = min(nx * p[0] + ny * p[1] for p in other.corners)
                b1 = max(nx * p[0] + ny * p[1] for p in other.corners)
                if a1 < b0 - 1e-9 or b1 < a0 - 1e-9:
                    return False
        return True

    def __str__(self) -> str:
        x0, y0, x1, y1 = self.extents
        return f"box({x0:.3f},{y0:.3f} .. {x1:.3f},{y1:.3f})"


@dataclass
class SweepDecl:
    """One parsed declaration. Immutable as far as the verifier is concerned."""
    quantity: str
    layer: str
    lo: float
    hi: float
    box: Box                    # footprint-local mm, as written
    block: str
    ref: str
    token: str                  # VERBATIM, printed on every run
    owner: int = -1             # footprint instance index, set at ingest
    owner_name: str = ""        # library id of the declaring footprint
    source: str = ""            # "library file" or "board-embedded copy"
    board_box: "Box | None" = None       # box after Placement, board mm

    # --- run state, filled by the checks -------------------------------
    n_matched: int = 0
    obs_lo: "float | None" = None
    obs_hi: "float | None" = None
    n_fenced: int = 0           # items of the owner on `layer` inside the box
    fenced_area: float = 0.0    # bbox area of that fenced geometry
    out_of_band: list = field(default_factory=list)   # (value, where)
    exercised: bool = False     # did the check that would judge it run at all
    notes: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.block}/{self.quantity}/{self.layer}"

    @property
    def active_box(self) -> Box:
        return self.board_box if self.board_box is not None else self.box

    def observe(self, value: float):
        self.n_matched += 1
        if self.obs_lo is None or value < self.obs_lo:
            self.obs_lo = value
        if self.obs_hi is None or value > self.obs_hi:
            self.obs_hi = value

    def in_band(self, value: float) -> bool:
        return self.lo - 1e-12 <= value <= self.hi + 1e-12

    def band_str(self) -> str:
        return f"{self.lo:.3f}..{self.hi:.3f}"


def parse_token(tok: str, known_layers=None) -> SweepDecl:
    """One `sweep:` token -> SweepDecl. Raises SweepError on anything else."""
    if not tok.startswith(SWEEP_TAG_PREFIX):
        raise SweepError(f"{tok!r} is not a sweep declaration")
    parts = tok.split(":", 6)
    if len(parts) != 7:
        raise SweepError(
            f"{tok!r} has {len(parts)} colon-separated field(s), expected 7: "
            f"sweep:<quantity>:<layer>:<lo>..<hi>:<x0>,<y0>,<x1>,<y1>:"
            f"<block>:<ref>")
    _, quantity, layer, band, box, block, ref = parts

    if quantity not in QUANTITIES:
        raise SweepError(
            f"{tok!r} declares quantity {quantity!r}; the enum is "
            f"{', '.join(QUANTITIES)}. A quantity outside it is not a sweep "
            f"this harness can bound")

    if not _LAYER_RE.match(layer) or "*" in layer or "," in layer:
        raise SweepError(
            f"{tok!r} names layer {layer!r}. Exactly one KiCad layer name, no "
            f"wildcards and no lists: a declaration that spans layers is how a "
            f"deliberate copper sweep swallows an accidental silk defect")
    if known_layers is not None and layer not in known_layers:
        raise SweepError(
            f"{tok!r} names layer {layer!r}, which KiCad does not know")

    if ".." not in band:
        raise SweepError(f"{tok!r}: band {band!r} is not <lo>..<hi>")
    lo_s, _, hi_s = band.partition("..")
    try:
        lo, hi = float(lo_s), float(hi_s)
    except ValueError:
        raise SweepError(f"{tok!r}: band {band!r} is not two numbers") from None
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise SweepError(f"{tok!r}: band {band!r} is not finite")
    if hi <= lo:
        raise SweepError(
            f"{tok!r}: band {lo}..{hi} does not increase; a band must bound "
            f"something")
    if lo < MIN_LO_MM - 1e-12:
        raise SweepError(
            f"{tok!r}: lo = {lo} mm is under the {MIN_LO_MM} mm hard floor "
            f"this mechanism will accept. Zero is not a sweep bottom -- a "
            f"feature at zero does not exist and a gap at zero is a short -- "
            f"and a band that starts near it bounds nothing")

    nums = box.split(",")
    if len(nums) != 4:
        raise SweepError(f"{tok!r}: box {box!r} is not x0,y0,x1,y1")
    try:
        x0, y0, x1, y1 = (float(v) for v in nums)
    except ValueError:
        raise SweepError(f"{tok!r}: box {box!r} is not four numbers") from None
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        raise SweepError(f"{tok!r}: box {box!r} is not finite")
    if x1 <= x0 or y1 <= y0:
        raise SweepError(
            f"{tok!r}: box {box!r} has no area (needs x1 > x0 and y1 > y0)")

    if not _BLOCK_RE.match(block):
        raise SweepError(
            f"{tok!r}: block name {block!r} must be a bare identifier -- it is "
            f"printed in every report line that cites this declaration")
    if not ref.strip():
        raise SweepError(
            f"{tok!r}: the ref is empty. A declaration is a claim, and a claim "
            f"with no pointer a reviewer can check is not reviewable")

    return SweepDecl(quantity=quantity, layer=layer, lo=lo, hi=hi,
                     box=Box.from_extents(x0, y0, x1, y1),
                     block=block, ref=ref.strip(), token=tok)


def from_tags(tags: str, known_layers=None) -> list[SweepDecl]:
    """Every sweep declaration in a footprint's tag string.

    Raises on any malformed token and on two declarations of the same
    (quantity, layer) whose boxes overlap -- exactly one declaration may ever
    match a finding, and guessing which of two contradictory bands was meant is
    how the emit/verify split reopens.
    """
    out = [parse_token(t, known_layers) for t in (tags or "").split()
           if t.startswith(SWEEP_TAG_PREFIX)]
    for i, a in enumerate(out):
        for b in out[i + 1:]:
            if a.quantity == b.quantity and a.layer == b.layer \
                    and a.box.overlaps(b.box):
                raise SweepError(
                    f"two {a.quantity} declarations on {a.layer} overlap "
                    f"({a.block} {a.box} and {b.block} {b.box}). A finding may "
                    f"match exactly one declaration; two bands over one place "
                    f"is a contradiction, not a refinement")
    return out


def token_for(quantity: str, layer: str, lo: float, hi: float,
              x0: float, y0: float, x1: float, y1: float,
              block: str, ref: str) -> str:
    """Format a declaration. Used by the EMITTER.

    The emitter must pass numbers derived from its own DESIGN CONSTANTS, never
    from a scan of the geometry it has just drawn. A band computed from what
    was emitted always matches what was emitted, which is the verifier echoing
    the emitter's own attribute -- the exact defect this project found first,
    rebuilt one layer up, and the whole mechanism would be vacuous. The token
    is round-tripped through parse_token() here so a malformed one cannot be
    written in the first place.
    """
    tok = (f"{SWEEP_TAG_PREFIX}{quantity}:{layer}:{lo:g}..{hi:g}:"
           f"{x0:g},{y0:g},{x1:g},{y1:g}:{block}:{ref}")
    parse_token(tok)
    return tok
