#!/usr/bin/env python3
"""W1b: microprinting as a real output mode.

docs/pcb-palette.md assesses microprinting and coupon_ladders.text_ladder()
sweeps cap heights on a calibration coupon, but neither lets you PLACE microtext
in a design. This does: a string, a cap height, a palette tone, and either a path
to run along or a region to fill.

The four things this module exists to get right
-----------------------------------------------

1. THE FLOOR IS ENFORCED, NOT SUGGESTED. The palette gives copper as the only
   viable microprint medium -- etching is photolithographic, silkscreen is a
   mesh print, and the doc puts silk's implied minimum character height at
   0.9-1.2 mm, which it calls "not microprinting, just small text". A silk
   request below its floor is REFUSED with the number that refuses it, not
   quietly promoted to something that will not image.

2. STROKE SCALES WITH CAP HEIGHT AND STAYS ABOVE THE FLOOR. That is the bug
   coupon_ladders.Fp.text() already fixed once and this must not reintroduce.
   Here the stroke is always cap*ratio -- and if that lands under the floor the
   CAP HEIGHT is refused, rather than the stroke being clamped up to the floor.
   Clamping would be the worse failure: at 0.4 mm cap a 0.10 mm stroke is 1:4,
   which fills every counter in the string solid. The output would pass a naive
   min-feature check and be unreadable. So: refuse, and say which cap height
   would work.

3. THE COUNTERS ARE CHECKED, NOT JUST THE STROKES. Closed letterforms fail
   first. stroke_font.py measures the inscribed radius of every glyph's
   narrowest enclosed void off a real KiCad render, so "narrowest counter" is a
   number here, not an adjective: clear = 2*D*cap - stroke. For
   coupon_ladders.SPECIMEN the binding glyph is 'e' (D = 0.147 em), and it binds
   BEFORE the stroke does -- which is precisely why that specimen was chosen.

4. THE MASK OPENS OVER THE BLOCK, NEVER PER GLYPH. Mask registration is
   +/-0.05 mm against a ~0.10 mm stroke. A per-glyph opening cannot survive
   that; a block opening only has to place its own edge. So for any tone whose
   recipe contains a mask layer, the letterforms go on the COPPER layer and the
   mask layer gets one filled rectangle over the whole run. Two runs whose
   openings would leave a sub-floor mask dam between them are merged into one
   opening rather than left to wash away.

Tones
-----
Read from coupon_blocks.TONE_RECIPE, then split by layer class:

  T2  F.Cu + F.Mask   copper letterforms in one block opening -- gold on bare
                      laminate, the doc's option 1, the high-contrast route.
  T6  F.Cu            copper under mask, no opening -- the doc's option 2.
                      Covert, and immune to registration entirely.
  T1  F.SilkS         allowed only at or above the cap height its own floor
                      implies. Not microprinting; the doc says so.
  T3  F.Mask          refused: the letterforms would BE the opening, and the
                      doc is explicit that microprinting works in copper only.
  T5  (nothing)       refused: draws nothing by definition.
  T4/T7 buried        refused unless --allow-buried: the doc says buried tones
                      are "fields and broad shapes, not linework", and their
                      floor is PROVISIONAL (docs/pcb-palette.md gives no number).

Usage
    python tools/microtext.py --text "Reckless" --height 0.7 --tone T2 \
        --name mt_demo -o out.kicad_mod --region 0,0,20,6
    python tools/emit_art.py ... --microtext "Reckless" --microtext-height 0.7
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from dataclasses import dataclass, field

_TOOLS = pathlib.Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import stroke_font                                       # noqa: E402
from coupon_ladders import (FLOOR_MASK_DAM, FLOOR_SOURCE,  # noqa: E402
                            TEXT_STROKE_RATIO, floor_for)
from coupon_blocks import TONE_RECIPE                    # noqa: E402

TONE_LAYERS = {k.split("_", 1)[0]: tuple(v) for k, v in TONE_RECIPE.items()}

# Minimum legible character height, mm. docs/pcb-palette.md: silk 0.9-1.2 ("not
# microprinting, just small text"), copper reliable zone 0.6-0.8 with 0.5 as
# best case. These are the same numbers tools/verify_art.py checks against, on
# purpose -- the emitter must not pass something the harness will then flag.
LEGIBLE_MM = {"silk": 0.9, "copper": 0.6, "mask": 0.9, "buried": 1.2}

# docs/pcb-palette.md, "legible stroke-to-height runs about 1:6 to 1:8".
RATIO_BAND = (1.0 / 8.0, 1.0 / 6.0)

# docs/pcb-palette.md: "Vendor capability varies sharply. 0.127 mm (5 mil) is
# standard; 0.09 mm is an advanced option at extra cost; 0.075 mm needs a
# capable fab. Microprinting is a per-vendor decision, not a design constant."
# Reported for every run, because the palette's own 0.1 mm copper floor is
# BETWEEN the standard and advanced tiers: a design that clears the palette
# floor may still be unbuildable at the fab you actually ordered from.
VENDOR_TIERS = [
    (0.127, "standard (5 mil)"),
    (0.090, "advanced, at extra cost"),
    (0.075, "needs a capable fab"),
]

# The mask opening is grown past the letterforms by this much. Mask registration
# is +/-0.05 mm; at 3x that, a worst-case misregistration still leaves the
# opening clear of every glyph, which is the whole point of opening over the
# block instead of over the glyphs.
DEFAULT_MASK_BLEED_MM = 0.15
MASK_REGISTRATION_MM = 0.05

# Two runs whose openings sit closer than one glyph apart read as one block, so
# they are merged rather than left as a hairline dam. Below FLOOR_MASK_DAM the
# dam washes away in processing and they merge anyway -- badly.
DEFAULT_RUN_TOL_DEG = 0.5


class MicrotextRefused(RuntimeError):
    """A request that cannot be honoured as asked. Never downgraded silently."""


# --- tone -> layers ---------------------------------------------------------

def _classify(layers):
    cu, mask, silk, buried = [], [], [], []
    for l in layers:
        cls = floor_for(l)[1]
        (cu if cls == "copper" else mask if cls == "mask" else
         silk if cls == "silk" else buried if cls == "buried" else []).append(l)
    return cu, mask, silk, buried


def plan_tone(tone: str, *, allow_buried: bool = False):
    """-> (text_layers, mask_layers, floor_class, notes). Raises on refusal."""
    if tone not in TONE_LAYERS:
        raise MicrotextRefused(
            f"{tone!r} is not a palette tone; known: {' '.join(sorted(TONE_LAYERS))}")
    layers = TONE_LAYERS[tone]
    cu, mask, silk, buried = _classify(layers)
    notes = []

    if not layers:
        raise MicrotextRefused(
            f"{tone} draws nothing at all -- it IS the bare board (see "
            f"docs/pcb-palette.md). There is no layer to put letterforms on. "
            f"Use T2 (copper in a block mask opening) or T6 (copper under mask).")

    if cu:
        text_layers = cu
        if mask:
            notes.append(f"{tone}: letterforms on {'/'.join(cu)}, ONE block "
                         f"opening on {'/'.join(mask)} -- gold on bare laminate")
        else:
            notes.append(f"{tone}: copper under mask, no opening -- covert, and "
                         f"immune to mask registration entirely")
        return text_layers, mask, "copper", notes

    if buried:
        if not allow_buried:
            raise MicrotextRefused(
                f"{tone} puts the letterforms on {'/'.join(buried)}. "
                f"docs/pcb-palette.md: buried tones are shadows cast through "
                f"0.1 mm of dielectric, \"fine detail will not read\", and are "
                f"to be treated as fields and broad shapes, NOT linework. "
                f"Microtext is the finest linework there is. The doc also gives "
                f"no minimum-feature number for buried layers at all, so there "
                f"is nothing to check against. Use T2 or T6, or pass "
                f"--allow-buried if you are deliberately making a coupon.")
        notes.append(f"{tone}: BURIED microtext on {'/'.join(buried)} -- the "
                     f"palette gives no floor for this layer and says fine "
                     f"detail will not read. Everything below is PROVISIONAL.")
        return buried, mask, "buried", notes

    if silk:
        notes.append(f"{tone}: silkscreen. docs/pcb-palette.md puts silk's "
                     f"implied minimum character height at 0.9-1.2 mm and calls "
                     f"that \"not microprinting, just small text\" -- copper is "
                     f"about twice as fine and is the only microprint medium.")
        return silk, [], "silk", notes

    # mask-only, i.e. T3
    raise MicrotextRefused(
        f"{tone}'s only layer is {'/'.join(mask)}, so the letterforms would BE "
        f"the mask opening -- one opening per glyph, which is exactly what "
        f"docs/pcb-palette.md rules out: mask registration is "
        f"+/-{MASK_REGISTRATION_MM} mm and per-glyph openings will not survive "
        f"it. The doc is also explicit that microprinting is achievable \"only "
        f"in copper\". Use T2 (copper inside one block opening, gold on bare "
        f"laminate) or T6 (copper under mask, covert).")


# --- geometry ---------------------------------------------------------------

def rotate(dx, dy, angle_deg):
    """Rotate an offset from a KiCad text anchor by the fp_text `at` angle.

    KiCad angles are counter-clockwise as DISPLAYED, and file y grows downward,
    so the file-space rotation is the transpose of the usual one. Verified
    against a kicad-cli render, not assumed.
    """
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return dx * c + dy * s, -dx * s + dy * c


def box_quad(x, y, box, angle_deg):
    """Ink box (x0,y0,x1,y1) around an anchor -> 4 corners in footprint mm."""
    x0, y0, x1, y1 = box
    out = []
    for dx, dy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        rx, ry = rotate(dx, dy, angle_deg)
        out.append((x + rx, y + ry))
    return out


def inflate_quad(q, d):
    """Grow a convex quad outward by d, by pushing each vertex along the
    bisector of its two edges. Exact for a rectangle, which is all we make."""
    n = len(q)
    out = []
    for i in range(n):
        p = q[i]
        a, b = q[(i - 1) % n], q[(i + 1) % n]
        v1 = (p[0] - a[0], p[1] - a[1])
        v2 = (p[0] - b[0], p[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-12 or l2 < 1e-12:
            out.append(p)
            continue
        u = (v1[0] / l1 + v2[0] / l2, v1[1] / l1 + v2[1] / l2)
        lu = math.hypot(*u)
        if lu < 1e-12:
            out.append(p)
            continue
        # for a right angle the bisector reaches d*sqrt(2); scale generally
        cos_half = max(0.2, math.sqrt(max(0.0, (1 + (v1[0]*v2[0] + v1[1]*v2[1])
                                                / (l1 * l2)) / 2)))
        k = d / cos_half
        out.append((p[0] + u[0] / lu * k, p[1] + u[1] / lu * k))
    return out


def convex_hull(pts):
    p = sorted(set((round(x, 6), round(y, 6)) for x, y in pts))
    if len(p) < 3:
        return list(p)

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lo = []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    hi = []
    for q in reversed(p):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], q) <= 0:
            hi.pop()
        hi.append(q)
    return lo[:-1] + hi[:-1]


def _seg_dist(p, q, r, s):
    def pt_seg(p, a, b):
        vx, vy = b[0]-a[0], b[1]-a[1]
        L2 = vx*vx + vy*vy
        if L2 <= 0:
            return math.hypot(p[0]-a[0], p[1]-a[1])
        t = max(0.0, min(1.0, ((p[0]-a[0])*vx + (p[1]-a[1])*vy) / L2))
        return math.hypot(p[0]-(a[0]+t*vx), p[1]-(a[1]+t*vy))
    d1 = (q[0]-p[0], q[1]-p[1])
    d2 = (s[0]-r[0], s[1]-r[1])
    den = d1[0]*d2[1] - d1[1]*d2[0]
    if abs(den) > 1e-15:
        t = ((r[0]-p[0])*d2[1] - (r[1]-p[1])*d2[0]) / den
        u = ((r[0]-p[0])*d1[1] - (r[1]-p[1])*d1[0]) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            return 0.0
    return min(pt_seg(p, r, s), pt_seg(q, r, s), pt_seg(r, p, q), pt_seg(s, p, q))


def poly_gap(a, b):
    best = math.inf
    for i in range(len(a)):
        for j in range(len(b)):
            best = min(best, _seg_dist(a[i], a[(i+1) % len(a)],
                                       b[j], b[(j+1) % len(b)]))
            if best <= 0.0:
                return 0.0
    return best


def merge_openings(quads, dam):
    """Merge any openings closer than `dam` into their convex hull, to fixpoint.

    A mask dam thinner than the floor washes away in processing (the doc's
    words), at which point the two openings merge ANYWAY -- with a ragged edge
    nobody designed. Merging them deliberately gets the same topology with an
    edge that was drawn on purpose.
    """
    cur = [list(q) for q in quads]
    merged = 0
    changed = True
    while changed and len(cur) > 1:
        changed = False
        for i in range(len(cur)):
            for j in range(i + 1, len(cur)):
                if poly_gap(cur[i], cur[j]) < dam - 1e-9:
                    hull = convex_hull(cur[i] + cur[j])
                    cur = [c for k, c in enumerate(cur) if k not in (i, j)] + [hull]
                    merged += 1
                    changed = True
                    break
            if changed:
                break
    return cur, merged


# --- the spec ---------------------------------------------------------------

@dataclass
class MicrotextSpec:
    text: str
    cap_mm: float
    tone: str = "T2"
    at: tuple[float, float] = (0.0, 0.0)
    angle_deg: float = 0.0
    path: list[tuple[float, float]] | None = None
    region: tuple[float, float, float, float] | None = None
    separator: str = "   "
    row_gap_mm: float | None = None
    stroke_ratio: float = TEXT_STROKE_RATIO
    mask_bleed_mm: float = DEFAULT_MASK_BLEED_MM
    floor_mm: float | None = None          # vendor override
    allow_buried: bool = False
    allow_unmeasured: bool = False
    run_tol_deg: float = DEFAULT_RUN_TOL_DEG
    # How this spec's flags are spelled on the command line that built it.
    # emit_art.py prefixes them, so a message that hard-codes "--text" sends the
    # reader looking for a flag that tool does not have.
    flag_prefix: str = ""
    text_flag: str = "--text"

    @property
    def mode(self):
        if self.region is not None:
            return "region"
        if self.path is not None:
            return "path"
        return "line"


@dataclass
class Run:
    text: str
    x: float
    y: float
    angle: float
    quad: list = field(default_factory=list)


# --- the check --------------------------------------------------------------

def measure(spec: MicrotextSpec, s: str) -> stroke_font.StringMetrics:
    """The one place this module measures a string.

    Always at the spec's stroke ratio, so every ink box in here is where the
    letterforms will actually be rather than where a hairline pen would have
    put them.
    """
    return stroke_font.measure_string(s, allow_unmeasured=spec.allow_unmeasured,
                                      stroke_ratio=spec.stroke_ratio)


def check(spec: MicrotextSpec) -> dict:
    """Everything that can be decided before any geometry is placed.

    Raises MicrotextRefused for anything that cannot be honoured as asked.
    Returns the report skeleton; placement fills in the rest.
    """
    if not spec.text:
        raise MicrotextRefused("--microtext was given an empty string")
    haz = stroke_font.markup_hazards(spec.text)
    if haz:
        raise MicrotextRefused(
            "the string would not be fabricated as written:\n  - " +
            "\n  - ".join(haz) +
            "\n  Microprinting is unreadable without a loupe, so a silent "
            "substitution here is a defect nobody would ever catch.")

    text_layers, mask_layers, cls, notes = plan_tone(
        spec.tone, allow_buried=spec.allow_buried)

    # The ratio and the cap height are needed before the string can be measured:
    # `justify left` justifies the text BOX, so where the letterforms land
    # depends on how heavy the pen is (stroke_font, "Where the anchor actually
    # is"). Measuring first and correcting later would be measuring the wrong
    # thing.
    r = float(spec.stroke_ratio)
    if not (0 < r < 1):
        raise MicrotextRefused(f"--stroke-ratio {r} is not a ratio in (0,1)")
    cap = float(spec.cap_mm)
    if cap <= 0:
        raise MicrotextRefused(f"cap height {cap} mm is not positive")
    stroke = cap * r

    try:
        m = measure(spec, spec.text)
    except stroke_font.UnmeasuredGlyph as e:
        raise MicrotextRefused(
            f"character {e.args[0]!r} (U+{ord(e.args[0]):04X}) has no measured "
            f"metrics. tools/stroke_font.py covers printable ASCII; KiCad's "
            f"stroke font covers far more, but nothing here can state its "
            f"advance or its counters, so neither the layout nor the counter "
            f"check would be true. Re-measure with "
            f"'python tools/stroke_font.py --calibrate', or pass "
            f"--{spec.flag_prefix}allow-unmeasured to place it with the widest "
            f"measured advance and NO counter check.") from None

    if m.ink_em is None:
        raise MicrotextRefused(
            f"{spec.text!r} has no ink at all (only spaces) -- nothing to place")

    # the floor
    doc_floor = floor_for(text_layers[0])[0]
    if doc_floor is None:                       # buried: the doc gives no number
        doc_floor = 0.50
        floor_note = ("PROVISIONAL 0.50 mm -- docs/pcb-palette.md gives no "
                      "buried floor; this matches tools/verify_art.py's "
                      "provisional value and cal_buried exists to measure it")
    else:
        floor_note = f"docs/pcb-palette.md via {pathlib.Path(FLOOR_SOURCE).name}"
    floor = doc_floor if spec.floor_mm is None else float(spec.floor_mm)
    if spec.floor_mm is not None:
        floor_note = (f"caller override --floor {spec.floor_mm:g} mm "
                      f"(palette says {doc_floor:g} mm)")

    rep = {
        "text": spec.text, "tone": spec.tone, "mode": spec.mode,
        "text_layers": list(text_layers), "mask_layers": list(mask_layers),
        "floor_class": cls, "floor_mm": floor, "floor_note": floor_note,
        "cap_mm": cap, "stroke_mm": stroke, "stroke_ratio": r,
        "advance_mm": m.advance_em * cap,
        "ink_mm": [v * cap for v in m.ink_em],
        "x_height_mm": stroke_font.X_HEIGHT_EM * cap,
        "glyphs": len(spec.text),
        "notes": list(notes), "warnings": [], "checks": [],
        "unmeasured": list(m.unmeasured),
    }

    def add(name, value, floor_v, unit="mm", extra=""):
        ok = value >= floor_v - 1e-9
        rep["checks"].append({"name": name, "value": value, "floor": floor_v,
                              "ok": ok, "unit": unit, "note": extra})
        return ok

    ok_stroke = add("stroke width", stroke, floor,
                    extra=f"1:{1/r:.1f} of the cap height")

    # counters
    rep["counters"] = []
    for ch, em in sorted(m.counter_chars.items(), key=lambda kv: kv[1]):
        clear = stroke_font.counter_clear_mm(em, cap, stroke)
        rep["counters"].append({"char": ch, "em": em, "clear_mm": clear,
                                "ok": clear >= floor - 1e-9})
    ok_counter = True
    if m.counter_em is not None:
        clear = stroke_font.counter_clear_mm(m.counter_em, cap, stroke)
        rep["counter"] = {"char": m.counter_char, "em": m.counter_em,
                          "clear_mm": clear}
        ok_counter = add("narrowest counter", clear, floor,
                         extra=f"{m.counter_char!r}, inscribed radius "
                               f"{m.counter_em:.5f} em")
    else:
        rep["counter"] = None
        rep["checks"].append({
            "name": "narrowest counter", "value": None, "floor": floor,
            "ok": True, "unit": "mm",
            "note": "no closed letterforms in this string -- nothing here fails "
                    "before the strokes do"})

    legible = LEGIBLE_MM.get(cls, 0.9)
    rep["legible_mm"] = legible
    ok_legible = add("cap height", cap, legible, extra="legibility, not fab")

    # smallest cap height that works, for this string on this layer
    h_fab, binding = stroke_font.min_cap_for_floor(floor, r, m.counter_em)
    h_min = max(h_fab, legible)
    rep["min_cap"] = {
        "fab_mm": h_fab, "binding": binding, "legible_mm": legible,
        "recommended_mm": (math.inf if math.isinf(h_min)
                           else math.ceil(h_min * 200 - 1e-9) / 200),
        "limited_by": "legibility" if legible > h_fab else binding,
    }
    rep["vendor"] = []
    if cls == "copper":
        for f, label in VENDOR_TIERS:
            hv, bind = stroke_font.min_cap_for_floor(f, r, m.counter_em)
            rep["vendor"].append({"floor_mm": f, "label": label,
                                  "min_cap_mm": max(hv, legible),
                                  "binding": ("legibility" if legible > hv
                                              else bind),
                                  "ok": cap >= max(hv, legible) - 1e-9})

    if not (RATIO_BAND[0] - 1e-9 <= r <= RATIO_BAND[1] + 1e-9):
        rep["warnings"].append(
            f"stroke ratio 1:{1/r:.1f} is outside the 1:6 to 1:8 legible band "
            f"docs/pcb-palette.md gives; the strokes will read as "
            f"{'too heavy -- counters close' if r > RATIO_BAND[1] else 'too light'}")
    if m.unmeasured:
        rep["warnings"].append(
            f"{len(m.unmeasured)} character(s) have no measured metrics "
            f"({''.join(m.unmeasured)!r}): placed at the widest measured advance "
            f"({stroke_font.MAX_ADVANCE_EM:.3f} em) and EXCLUDED from the counter "
            f"check. The narrowest counter reported below is therefore a lower "
            f"bound on the risk, not a verdict on the whole string.")

    fails = [c for c in rep["checks"] if not c["ok"]]
    if fails:
        rec = rep["min_cap"]["recommended_mm"]
        # 5 dp, not 4: at the boundary a counter of 0.09996 mm rounds to
        # "0.1000 mm is under the 0.100 mm floor", which reads like a bug in the
        # tool rather than a 40 nm shortfall in the design.
        detail = "\n  - ".join(
            f"{c['name']} {c['value']:.5f} mm is under the "
            f"{c['floor']:.3f} mm {'legibility floor' if c['name'] == 'cap height' else cls + ' floor'}"
            + (f" ({c['note']})" if c['note'] else "")
            for c in fails)
        extra = ""
        if cls == "silk":
            extra = ("\n  Silk is a mesh screen print; copper is etched and about "
                     "twice as fine. docs/pcb-palette.md: silk microtext is "
                     "\"not microprinting, just small text\". If you want "
                     "microprinting, use T2 or T6 on copper.")
        # The "nothing was clamped" line only means anything when clamping was
        # the temptation -- i.e. when the STROKE is what fell under the floor.
        # At a large cap height with a silly ratio the stroke is already fat and
        # raising it to the floor would make it thinner, so saying it would fill
        # the counters solid is simply false.
        clamp = ""
        if not ok_stroke:
            clamp = (f"\n  Nothing was clamped: a stroke raised to the floor at "
                     f"this cap height would be 1:{cap/floor:.1f}, which fills "
                     f"the counters solid.")
        raise MicrotextRefused(
            f"cap height {cap:.3f} mm will not image on "
            f"{'/'.join(text_layers)} ({cls}):\n  - {detail}\n"
            f"  Smallest cap height that clears every check for {spec.text!r} "
            f"on this layer: {rec:.3f} mm "
            f"(limited by {rep['min_cap']['limited_by']}).{extra}{clamp}")

    assert ok_stroke and ok_counter and ok_legible
    return rep


# --- placement --------------------------------------------------------------

def _row_text(spec, per_mm, width_mm):
    """Repeat the string with its separator until one more would overflow."""
    unit = spec.text + spec.separator
    one = per_mm(spec.text)
    if one > width_mm + 1e-9:
        raise MicrotextRefused(
            f"{spec.text!r} is {one:.3f} mm wide at a {spec.cap_mm:g} mm cap "
            f"height and the region is only {width_mm:.3f} mm wide. Refusing to "
            f"truncate the string: widen the region, or drop the cap height to "
            f"{spec.cap_mm * width_mm / one:.3f} mm (check it against the floor "
            f"first -- it may not be legal).")
    s, w = spec.text, one
    while True:
        cand = s + spec.separator + spec.text
        cw = per_mm(cand)
        if cw > width_mm + 1e-9:
            return s, w
        s, w = cand, cw


def _runs_line(spec, m, cap):
    return [Run(spec.text, spec.at[0], spec.at[1], spec.angle_deg)]


def _runs_region(spec, m, cap, rep):
    x0, y0, x1, y1 = spec.region
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0

    # "Fill this rectangle" has to mean the LETTERFORMS stay inside it, so the
    # pen is paid for on every edge. Fitting to the centreline box instead puts
    # half a stroke of ink outside the region on all four sides -- 0.05 mm at a
    # 0.7 mm cap, which is the whole mask registration budget.
    pen = rep["stroke_mm"] / 2.0

    def inkw(s):
        b = measure(spec, s).ink_em
        return 0.0 if b is None else (b[2] - b[0]) * cap + 2 * pen

    row, row_w = _row_text(spec, inkw, x1 - x0)
    rm = measure(spec, row)
    ix0, iy0, ix1, iy1 = [v * cap for v in rm.ink_em]
    ix0, iy0, ix1, iy1 = ix0 - pen, iy0 - pen, ix1 + pen, iy1 + pen
    ink_h = iy1 - iy0

    floor = rep["floor_mm"]
    gap = spec.row_gap_mm if spec.row_gap_mm is not None else max(floor, 0.25 * cap)
    if gap < floor - 1e-9:
        rep["warnings"].append(
            f"--row-gap {gap:.4f} mm leaves less than the {floor:.3f} mm "
            f"{rep['floor_class']} floor between the ink of adjacent rows; "
            f"descenders and ascenders will touch and the rows will read as one "
            f"block. Not clamped -- this is what you asked for.")
    pitch = ink_h + gap
    rep["row_pitch_mm"] = pitch
    rep["row_gap_mm"] = gap
    rep["row_text"] = row
    rep["repeats_per_row"] = row.count(spec.text)

    nrows = int(math.floor((y1 - y0 - ink_h) / pitch + 1e-9)) + 1
    if nrows < 1:
        raise MicrotextRefused(
            f"one row of {spec.text!r} is {ink_h:.3f} mm tall at a "
            f"{cap:g} mm cap height and the region is only {y1-y0:.3f} mm tall. "
            f"Refusing to place a row that would spill out of the region.")
    runs = []
    for i in range(nrows):
        ay = y0 - iy0 + i * pitch
        runs.append(Run(row, x0 - ix0, ay, 0.0))
    rep["rows"] = nrows
    used = ink_h + (nrows - 1) * pitch
    if y1 - y0 - used > pitch:
        rep["warnings"].append(
            f"{y1-y0-used:.3f} mm of the region is left empty below the last "
            f"row -- the pitch does not divide the region height")
    return runs


def _polyline(path):
    segs, total = [], 0.0
    for a, b in zip(path, path[1:]):
        L = math.hypot(b[0]-a[0], b[1]-a[1])
        if L <= 1e-12:
            continue
        segs.append((a, b, L, total))
        total += L
    if not segs:
        raise MicrotextRefused("--path has no length: every point is the same")
    return segs, total


def _at_arc(segs, total, s):
    """Point and heading at arc length s, extended past the ends rather than
    clamped -- text that overruns must stay readable and be REPORTED, not be
    silently piled up on the final vertex."""
    for a, b, L, s0 in segs:
        if s <= s0 + L or (a, b, L, s0) is segs[-1]:
            t = (s - s0) / L
            ux, uy = (b[0]-a[0]) / L, (b[1]-a[1]) / L
            return (a[0] + ux * t * L, a[1] + uy * t * L), (ux, uy)
    a, b, L, s0 = segs[0]
    return a, ((b[0]-a[0]) / L, (b[1]-a[1]) / L)


def _runs_path(spec, m, cap, rep):
    segs, total = _polyline(spec.path)
    rep["path_length_mm"] = total
    adv = [stroke_font.GLYPHS.get(ch, (stroke_font.MAX_ADVANCE_EM, None, None))[0]
           * cap for ch in spec.text]
    text_len = sum(adv)
    rep["advance_mm"] = text_len
    if text_len > total + 1e-9:
        rep["warnings"].append(
            f"the string is {text_len:.3f} mm long at this cap height and the "
            f"path is only {total:.3f} mm; the last "
            f"{text_len-total:.3f} mm runs on past the end of the path along "
            f"the final segment's direction. Nothing was dropped -- shorten the "
            f"string, lengthen the path, or drop the cap height.")

    runs, cur, pen = [], None, 0.0
    for ch, w in zip(spec.text, adv):
        p, u = _at_arc(segs, total, pen + w / 2.0)
        ang = math.degrees(math.atan2(-u[1], u[0]))
        if cur is not None and abs(_angdiff(ang, cur[3])) <= spec.run_tol_deg:
            cur[0] += ch
        else:
            if cur is not None:
                runs.append(Run(*cur))
            sp, su = _at_arc(segs, total, pen)
            sang = math.degrees(math.atan2(-su[1], su[0]))
            cur = [ch, sp[0], sp[1], sang]
        pen += w
    if cur is not None:
        runs.append(Run(*cur))
    return runs


def _angdiff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def place(spec: MicrotextSpec, rep: dict) -> tuple[list[Run], list[list], dict]:
    """-> (runs, mask openings, rep). rep is updated in place."""
    cap = rep["cap_mm"]
    m = measure(spec, spec.text)
    if spec.mode == "region":
        runs = _runs_region(spec, m, cap, rep)
    elif spec.mode == "path":
        runs = _runs_path(spec, m, cap, rep)
    else:
        runs = _runs_line(spec, m, cap)

    # A run can come out with no ink at all -- along a path, the tangent can
    # change exactly at a space, leaving a run that is nothing but spaces. It
    # has no letterforms to open the mask over and nothing to draw, so it is
    # dropped and counted. This is not image content going missing; a space is
    # advance, and the advance was already spent positioning the runs on either
    # side of it.
    blank = [r for r in runs if measure(spec, r.text).ink_em is None]
    if blank:
        runs = [r for r in runs if r not in blank]
        rep["blank_runs"] = len(blank)
        rep["notes"].append(
            f"{len(blank)} run(s) contained only spaces and were not emitted "
            f"(no ink, so nothing to draw and nothing to open the mask over)")
    if not runs:
        raise MicrotextRefused("every run came out blank -- nothing to place")
    for r in runs:
        box = tuple(v * cap for v in measure(spec, r.text).ink_em)
        r.quad = box_quad(r.x, r.y, box, r.angle)

    rep["runs"] = len(runs)
    rep["glyphs"] = sum(len(r.text) for r in runs)

    openings: list[list] = []
    rep["mask_bleed_mm"] = float(spec.mask_bleed_mm)
    if rep["mask_layers"]:
        # The run quads are CENTRELINE boxes, and half the pen sticks out past
        # every one of their edges. The bleed the caller asked for is clearance
        # from the LETTERFORMS, so the pen has to be paid for here -- otherwise
        # a 0.15 mm bleed silently becomes 0.0975 mm of real clearance at a
        # 0.105 mm stroke, and the number in the report would be a fiction.
        bleed = float(spec.mask_bleed_mm) + rep["stroke_mm"] / 2.0
        if spec.mask_bleed_mm < MASK_REGISTRATION_MM - 1e-9:
            rep["warnings"].append(
                f"--mask-bleed {spec.mask_bleed_mm:.4f} mm is under the "
                f"{MASK_REGISTRATION_MM} mm mask registration tolerance, so a "
                f"worst-case misregistration puts the opening edge INSIDE the "
                f"letterforms and the block stops being a block. Not clamped.")
        if spec.mode == "region":
            # one opening over the whole block: the doc's form 1, exactly
            xs = [p[0] for r in runs for p in r.quad]
            ys = [p[1] for r in runs for p in r.quad]
            openings = [[(min(xs) - bleed, min(ys) - bleed),
                         (max(xs) + bleed, min(ys) - bleed),
                         (max(xs) + bleed, max(ys) + bleed),
                         (min(xs) - bleed, max(ys) + bleed)]]
            rep["openings_merged"] = 0
        else:
            quads = [inflate_quad(r.quad, bleed) for r in runs]
            openings, merged = merge_openings(quads, FLOOR_MASK_DAM)
            rep["openings_merged"] = merged
            if merged:
                rep["notes"].append(
                    f"{merged} pair(s) of run openings sat closer than the "
                    f"{FLOOR_MASK_DAM:.2f} mm mask dam and were merged into one "
                    f"opening -- a thinner dam washes away in processing")
    rep["openings"] = len(openings)

    xs = [p[0] for r in runs for p in r.quad] + [p[0] for o in openings for p in o]
    ys = [p[1] for r in runs for p in r.quad] + [p[1] for o in openings for p in o]
    rep["bbox_mm"] = [min(xs), min(ys), max(xs), max(ys)]
    rep["block_mm"] = [max(xs) - min(xs), max(ys) - min(ys)]
    return runs, openings, rep


# --- emission ---------------------------------------------------------------

def emit(fp, spec: MicrotextSpec) -> dict:
    """Place `spec` into an emit_art.ArtFp. -> report dict.

    The stroke is passed to the writer EXPLICITLY rather than letting
    Fp.text()'s thickness=None default raise it to the floor. Both produce the
    same number here, because check() has already refused any cap height whose
    ratio-derived stroke lands under the floor -- but passing it explicitly
    leaves coupon_ladders.Fp's own floor guard live and armed underneath this
    module, so if the arithmetic above were ever wrong the writer would say so
    on stderr instead of quietly rescuing it.
    """
    rep = check(spec)
    runs, openings, rep = place(spec, rep)

    for layer in rep["mask_layers"]:
        for o in openings:
            fp.poly(o, layer)
    for layer in rep["text_layers"]:
        for r in runs:
            fp.text_rot(r.text, r.x, r.y, rep["cap_mm"], layer,
                        thickness=rep["stroke_mm"], angle=r.angle)
    rep["fp_items"] = len(openings) * len(rep["mask_layers"]) + \
        len(runs) * len(rep["text_layers"])
    rep["fp_poly"] = len(openings) * len(rep["mask_layers"])
    rep["fp_text"] = len(runs) * len(rep["text_layers"])

    # The geometry, handed back so a CALLER can audit it. microtext draws its
    # letterforms as fp_text -- a stroke-font instruction, not an outline -- so
    # nothing downstream can recover where the ink lands by parsing the
    # footprint. emit_art.py's copper-to-cut and window-intrusion audits work on
    # polygons, and without this they see microtext copper as ABSENT and report
    # "no copper near the cut" about a footprint with copper text sitting in the
    # middle of the slug. That is worse than not auditing at all, so the ink
    # envelope goes back up the call: each run's centreline quad grown by half
    # the pen, which is the outer bound of the letterforms, and the mask
    # openings as drawn.
    #
    # It is an ENVELOPE, not the glyph outlines: a run of text is audited as the
    # box it occupies. Conservative in the safe direction -- it can report a
    # clearance breach for a letter whose nearest actual stroke is a fraction of
    # a cap height further in, and it cannot miss one.
    rep["_geometry"] = {
        "ink": [[tuple(p) for p in inflate_quad(r.quad, rep["stroke_mm"] / 2.0)]
                for r in runs],
        "openings": [[tuple(p) for p in o] for o in openings],
        "text_layers": list(rep["text_layers"]),
        "mask_layers": list(rep["mask_layers"]),
        "envelope": True,
    }
    return rep


# --- report -----------------------------------------------------------------

def print_report(rep, out=None):
    w = (out or sys.stdout).write
    w("\n  " + "-" * 74 + "\n")
    w(f"  MICROTEXT  {rep['text']!r}\n")
    w("  " + "-" * 74 + "\n")
    for n in rep["notes"]:
        w(f"  note    : {n}\n")
    w(f"  tone    : {rep['tone']}  letterforms on "
      f"{'+'.join(rep['text_layers'])}"
      + (f", block opening on {'+'.join(rep['mask_layers'])}"
         if rep["mask_layers"] else ", no mask opening") + "\n")
    w(f"  floor   : {rep['floor_mm']:.3f} mm ({rep['floor_class']}) "
      f"[{rep['floor_note']}]\n")
    w(f"  mode    : {rep['mode']}  {rep['runs']} run(s), {rep['glyphs']} glyph(s), "
      f"{rep['openings']} opening(s)\n")

    w("\n  check                     value      floor    margin\n")
    w("  " + "-" * 60 + "\n")
    for c in rep["checks"]:
        if c["value"] is None:
            w(f"  {c['name']:<22}         -          -         -   {c['note']}\n")
            continue
        w(f"  {c['name']:<22} {c['value']:8.4f}   {c['floor']:7.3f}  "
          f"{c['value']-c['floor']:+8.4f}  {'OK ' if c['ok'] else 'FAIL'}"
          f"  {c['note']}\n")
    w("  " + "-" * 60 + "\n")

    if rep["counters"]:
        w("\n  counters in this string (clear width = 2*D*cap - stroke):\n")
        for c in rep["counters"]:
            w(f"    {c['char']!r:4} D={c['em']:.5f} em   clear "
              f"{c['clear_mm']:7.4f} mm   {'OK' if c['ok'] else 'FAIL'}\n")
        w(f"    closed letterforms fail before straight strokes: at "
          f"1:{1/rep['stroke_ratio']:.1f} any counter under "
          f"{rep['stroke_ratio']:.5f} em binds first\n")
    else:
        w("\n  counters: none -- this string has no closed letterforms, so the "
          "stroke\n            width is the only thing that can fail. That is a "
          "weaker test\n            than coupon_ladders.SPECIMEN, which was "
          "chosen to include them.\n")

    mc = rep["min_cap"]
    w(f"\n  smallest cap height that clears every check for this string on "
      f"{'/'.join(rep['text_layers'])}:\n"
      f"    {mc['recommended_mm']:.3f} mm   (limited by {mc['limited_by']}; "
      f"fab needs {mc['fab_mm']:.4f}, legibility needs {mc['legible_mm']:.2f})\n")

    if rep["vendor"]:
        w("\n  vendor capability -- docs/pcb-palette.md: \"a per-vendor decision, "
          "not a design constant\"\n")
        for v in rep["vendor"]:
            w(f"    {v['floor_mm']:.3f} mm {v['label']:<24} needs cap >= "
              f"{v['min_cap_mm']:.3f} mm  {'OK' if v['ok'] else 'TOO SMALL'}"
              f"  ({v['binding']}-limited)\n")

    b = rep["block_mm"]
    w(f"\n  block   : {b[0]:.3f} x {b[1]:.3f} mm at "
      f"({rep['bbox_mm'][0]:.3f}, {rep['bbox_mm'][1]:.3f})\n")
    if rep["mask_layers"]:
        w(f"  opening : {rep['openings']} block opening(s), "
          f"{rep.get('mask_bleed_mm', DEFAULT_MASK_BLEED_MM):.3f} mm clear of "
          f"the letterforms on every side (mask registration is "
          f"+/-{MASK_REGISTRATION_MM} mm) -- over the block, never per glyph\n")
    if "rows" in rep:
        w(f"  rows    : {rep['rows']} x {rep['repeats_per_row']} repeat(s), "
          f"pitch {rep['row_pitch_mm']:.3f} mm, gap {rep['row_gap_mm']:.3f} mm\n")
    if rep["warnings"]:
        w("\n")
        for x in rep["warnings"]:
            w(f"  !! {x}\n")
    w("\n")


# --- CLI plumbing shared with emit_art.py -----------------------------------

_TEXT_FLAG: dict[str, str] = {}


def add_cli_args(ap, prefix="", text_flag=None, group_title=None):
    """Add the microtext flags to a parser.

    emit_art.py calls this with prefix='microtext-' so the two tools cannot
    drift apart in what a flag means or what its default is.
    """
    d = prefix.replace("-", "_")
    _TEXT_FLAG[prefix] = text_flag or f"--{prefix}text"
    g = ap.add_argument_group(group_title or "microtext")
    g.add_argument(text_flag or f"--{prefix}text", dest=f"{d}text", default=None,
                   metavar="STRING",
                   help="the string to microprint. Refused if it contains "
                        "KiCad markup that would change what is fabricated")
    g.add_argument(f"--{prefix}height", dest=f"{d}height", type=float,
                   default=None, metavar="MM",
                   help="cap height in mm (KiCad's font size IS the cap height "
                        "for the stroke font -- measured, see stroke_font.py)")
    g.add_argument(f"--{prefix}tone", dest=f"{d}tone", default="T2",
                   metavar="TONE",
                   help="palette tone (default T2: copper letterforms in one "
                        "block mask opening). T6 = copper under mask, covert")
    g.add_argument(f"--{prefix}at", dest=f"{d}at", default="0,0", metavar="X,Y",
                   help="anchor for a single run, mm (default 0,0)")
    g.add_argument(f"--{prefix}angle", dest=f"{d}angle", type=float, default=0.0,
                   metavar="DEG", help="rotation of a single run")
    g.add_argument(f"--{prefix}path", dest=f"{d}path", default=None,
                   metavar='"X,Y X,Y ..."',
                   help="run the string along this polyline, one fp_text per "
                        "straight stretch")
    g.add_argument(f"--{prefix}region", dest=f"{d}region", default=None,
                   metavar="X0,Y0,X1,Y1",
                   help="fill this rectangle with repeated rows of the string")
    g.add_argument(f"--{prefix}separator", dest=f"{d}separator", default="   ",
                   help="between repeats in a filled region (default 3 spaces)")
    g.add_argument(f"--{prefix}row-gap", dest=f"{d}row_gap", type=float,
                   default=None, metavar="MM",
                   help="clear space between the ink of adjacent rows "
                        "(default: the layer floor, or 0.25 x cap, whichever "
                        "is larger)")
    g.add_argument(f"--{prefix}stroke-ratio", dest=f"{d}stroke_ratio", type=float,
                   default=TEXT_STROKE_RATIO, metavar="R",
                   help=f"stroke as a fraction of cap height (default "
                        f"{TEXT_STROKE_RATIO} = 1:6.7; the palette's legible "
                        f"band is 1:6 to 1:8)")
    g.add_argument(f"--{prefix}mask-bleed", dest=f"{d}mask_bleed", type=float,
                   default=DEFAULT_MASK_BLEED_MM, metavar="MM",
                   help=f"how far the block opening grows past the letterforms "
                        f"(default {DEFAULT_MASK_BLEED_MM} = 3x mask "
                        f"registration)")
    g.add_argument(f"--{prefix}floor", dest=f"{d}floor", type=float, default=None,
                   metavar="MM",
                   help="override the palette's minimum feature with your "
                        "vendor's real number, e.g. 0.127 for a standard fab")
    g.add_argument(f"--{prefix}run-tol-deg", dest=f"{d}run_tol", type=float,
                   default=DEFAULT_RUN_TOL_DEG, metavar="DEG",
                   help="glyphs whose path tangents differ by less than this "
                        "share one fp_text")
    g.add_argument(f"--{prefix}allow-buried", dest=f"{d}allow_buried",
                   action="store_true",
                   help="permit microtext on a buried copper layer, which the "
                        "palette says will not read and gives no floor for")
    g.add_argument(f"--{prefix}allow-unmeasured", dest=f"{d}allow_unmeasured",
                   action="store_true",
                   help="place characters with no measured metrics, excluded "
                        "from the counter check and flagged")
    return g


def _pairs(s, what):
    out = []
    for tok in s.replace(",", " ").split():
        out.append(float(tok))
    if len(out) % 2:
        raise MicrotextRefused(f"{what} needs an even number of coordinates, "
                               f"got {len(out)}: {s!r}")
    return [(out[i], out[i + 1]) for i in range(0, len(out), 2)]


def spec_from_args(args, prefix="") -> MicrotextSpec | None:
    d = prefix.replace("-", "_")
    text = getattr(args, f"{d}text")
    if text is None:
        return None
    tflag = _TEXT_FLAG.get(prefix, f"--{prefix}text")
    h = getattr(args, f"{d}height")
    if h is None:
        raise MicrotextRefused(
            f"{tflag} was given without --{prefix}height. There is no safe "
            f"default cap height: the whole question is whether the one you "
            f"want clears the floor.")
    region = getattr(args, f"{d}region")
    path = getattr(args, f"{d}path")
    if region and path:
        raise MicrotextRefused(f"--{prefix}region and --{prefix}path are "
                               f"different placements; pick one")
    reg = None
    if region:
        pts = _pairs(region, f"--{prefix}region")
        if len(pts) != 2:
            raise MicrotextRefused(f"--{prefix}region needs X0,Y0,X1,Y1")
        reg = (pts[0][0], pts[0][1], pts[1][0], pts[1][1])
    pl = None
    if path:
        pl = _pairs(path, f"--{prefix}path")
        if len(pl) < 2:
            raise MicrotextRefused(f"--{prefix}path needs at least two points")
    at = _pairs(getattr(args, f"{d}at"), f"--{prefix}at")
    return MicrotextSpec(
        text=text, cap_mm=h, tone=getattr(args, f"{d}tone"),
        at=at[0] if at else (0.0, 0.0),
        angle_deg=getattr(args, f"{d}angle"),
        path=pl, region=reg,
        separator=getattr(args, f"{d}separator"),
        row_gap_mm=getattr(args, f"{d}row_gap"),
        stroke_ratio=getattr(args, f"{d}stroke_ratio"),
        mask_bleed_mm=getattr(args, f"{d}mask_bleed"),
        floor_mm=getattr(args, f"{d}floor"),
        allow_buried=getattr(args, f"{d}allow_buried"),
        allow_unmeasured=getattr(args, f"{d}allow_unmeasured"),
        run_tol_deg=getattr(args, f"{d}run_tol"),
        flag_prefix=prefix, text_flag=tflag,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Place microprinted text in a KiCad footprint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The palette's authority on all of this is docs/pcb-palette.md; "
               "the letterform metrics are measured by tools/stroke_font.py.")
    ap.add_argument("--name", default="microtext", help="footprint name")
    ap.add_argument("-o", "--output", default=None, help="output .kicad_mod")
    ap.add_argument("--report-json", default=None)
    ap.add_argument("--specimen", action="store_true",
                    help="use coupon_ladders.SPECIMEN, chosen because its "
                         "closed counters fail first")
    add_cli_args(ap, prefix="", text_flag="--text")
    a = ap.parse_args(argv)

    if a.specimen and not a.text:
        from coupon_ladders import SPECIMEN
        a.text = SPECIMEN
    if not a.text:
        ap.error("--text (or --specimen) is required")

    from emit_art import ArtFp
    try:
        spec = spec_from_args(a)
        fp = ArtFp(a.name, descr=f"microtext {spec.text!r} at "
                                 f"{spec.cap_mm:g} mm cap - tools/microtext.py",
                   tags="recklessart microtext")
        rep = emit(fp, spec)
    except MicrotextRefused as e:
        sys.stderr.write(f"\n!! REFUSED: {e}\n\n")
        return 2
    print_report(rep)

    if a.output:
        out = pathlib.Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(fp.dumps(), encoding="utf-8")
        rep["output"] = str(out)
        rep["bytes"] = out.stat().st_size
        print(f"  output  : {out}  {rep['bytes']:,} B "
              f"({rep['bytes']/max(rep['glyphs'],1):.0f} B/glyph)\n")
    if a.report_json:
        pathlib.Path(a.report_json).write_text(json.dumps(rep, indent=2),
                                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
