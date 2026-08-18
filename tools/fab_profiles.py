#!/usr/bin/env python3
"""Fabrication profiles: the constraints that decide what art can exist.

Every floor in this repo used to be a single number lifted from
docs/pcb-palette.md. That was fine while one board went to one fab. It stops
being fine the moment the same artwork has to survive two processes, because
the binding constraint is whichever fab is COARSER -- and the coarser one is
not always the cheaper one. OSH Park's 4-layer service is 5 mil where JLCPCB's
fine option is 3.5 mil, so the boutique prototype house is the limiting case,
not the budget one.

A profile carries three kinds of fact, and they are not interchangeable:

  GEOMETRY   what the process can image. Hard limits; violate them and the
             feature is absent from the board.
  APPEARANCE mask colour and surface finish. These do not gate fabrication at
             all, but they decide what the palette's tones LOOK like -- T5 is
             literally the bare mask, so a purple-mask fab has a different T5
             than a black-mask one, and every tone relationship shifts with it.
  COST       whether a floor costs extra. A number you can reach for +20% is
             not the same as one you get for free, and the caller should be
             told which they are asking for.

Numbers marked UNPUBLISHED are exactly that. They are not guesses and must not
be filled in with a plausible-looking value: a fabricator who does not publish
a limit is a fabricator you have to ask. Anything that depends on an
unpublished number should refuse rather than assume.

Sources are recorded per profile. Re-check them before an order -- fabrication
capability changes, and a stale floor is the kind of error that only shows up
on the delivered board.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIL = 0.0254  # mm


@dataclass(frozen=True)
class FabProfile:
    """One fabrication process, as far as it is publicly specified."""

    name: str
    layers: int

    # --- geometry: hard limits -------------------------------------------
    min_copper_mm: float          # minimum trace width AND spacing
    min_silk_mm: float | None     # minimum silkscreen stroke
    min_mask_dam_mm: float | None # minimum web of mask between two openings
    mask_expansion_mm: float | None
    min_drill_mm: float | None
    min_annular_mm: float | None

    # --- appearance: drives the palette, not fabricability ---------------
    mask_colour: str
    finish: str
    substrate: str

    # --- cost -------------------------------------------------------------
    surcharge: str | None = None
    source: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def floor_for(self, layer: str) -> float:
        """Minimum feature on a given KiCad layer name."""
        if layer.endswith(".SilkS"):
            if self.min_silk_mm is None:
                raise ValueError(f"{self.name}: silk floor unpublished")
            return self.min_silk_mm
        return self.min_copper_mm


# Counter model measured in tools/stroke_font.py against the KiCad newstroke
# font: ink is centred on the stroke centreline, so the clear width of an
# enclosed void is 2*D*cap - stroke, where D is that glyph's inscribed-void
# radius in em. Lowercase 'e' is the tightest counter in ordinary prose at
# D = 0.147, which is why it closes before '@', '8', 'B' or 'R'.
CAP_TO_STROKE = 6.7
D_TIGHTEST_PROSE = 0.147


def min_cap_height_mm(profile: FabProfile, d_em: float = D_TIGHTEST_PROSE) -> float:
    """Smallest legible cap height for prose on copper under this profile.

    Two constraints, and the counter binds over the stroke for every profile
    measured so far -- which is the whole reason the specimen string in
    coupon_ladders.py was chosen to contain closed letterforms.
    """
    floor = profile.min_copper_mm
    stroke_bound = CAP_TO_STROKE * floor
    counter_bound = floor / (2 * d_em - 1 / CAP_TO_STROKE)
    return max(stroke_bound, counter_bound)


PROFILES: dict[str, FabProfile] = {
    "jlcpcb-4l-fine": FabProfile(
        name="JLCPCB 4-layer, fine",
        layers=4,
        min_copper_mm=3.5 * MIL,   # 0.0889
        min_silk_mm=0.15,
        min_mask_dam_mm=0.20,
        mask_expansion_mm=None,
        min_drill_mm=0.20,
        min_annular_mm=None,
        mask_colour="green (black available)",
        finish="HASL default; ENIG is an upcharge",
        substrate="FR4",
        surcharge="+20% on 4-8 layer boards",
        source="https://jlcpcb.com/capabilities/pcb-capabilities",
        notes=(
            "3.5 mil is reachable but billed; 4 mil is the no-cost floor.",
            "ENIG is NOT the default. Palette tone T2 assumes exposed gold, so "
            "ordering HASL changes what T2 looks like on the delivered board.",
        ),
    ),
    "jlcpcb-4l": FabProfile(
        name="JLCPCB 4-layer, standard",
        layers=4,
        min_copper_mm=4.0 * MIL,   # 0.1016
        min_silk_mm=0.15,
        min_mask_dam_mm=0.20,
        mask_expansion_mm=None,
        min_drill_mm=0.20,
        min_annular_mm=None,
        mask_colour="green (black available)",
        finish="HASL default; ENIG is an upcharge",
        substrate="FR4",
        surcharge=None,
        source="https://jlcpcb.com/capabilities/pcb-capabilities",
        notes=("The no-extra-cost floor for 4-layer work.",),
    ),
    "jlcpcb-2l": FabProfile(
        name="JLCPCB 2-layer, standard",
        layers=2,
        min_copper_mm=5.0 * MIL,   # 0.1270
        min_silk_mm=0.15,
        min_mask_dam_mm=0.20,
        mask_expansion_mm=None,
        min_drill_mm=0.30,
        min_annular_mm=None,
        mask_colour="green (black available)",
        finish="HASL default; ENIG is an upcharge",
        substrate="FR4",
        surcharge=None,
        source="https://jlcpcb.com/capabilities/pcb-capabilities",
    ),
    "oshpark-4l": FabProfile(
        name="OSH Park 4-layer prototype",
        layers=4,
        min_copper_mm=5.0 * MIL,   # 0.1270
        min_silk_mm=None,          # UNPUBLISHED
        min_mask_dam_mm=None,      # UNPUBLISHED -- see notes
        mask_expansion_mm=2.0 * MIL,
        min_drill_mm=10.0 * MIL,
        min_annular_mm=4.0 * MIL,
        mask_colour="purple",
        finish="ENIG, always",
        substrate="FR408",
        surcharge=None,
        source="https://docs.oshpark.com/services/four-layer/",
        notes=(
            "COARSER than JLCPCB's fine option, so this is the binding profile "
            "whenever one artwork must serve both.",
            "Purple mask means T5 -- which IS the board -- is purple here. The "
            "palette anchors in docs/pcb-palette.md are measured for BLACK mask "
            "only; purple and green are both uncalibrated.",
            "ENIG on every board, so T2 gold is guaranteed rather than an option.",
            "No minimum mask dam is published. Techniques gated on dam width "
            "(stipple, fine hatch on T2/T3) cannot be sized for this profile "
            "without asking OSH Park directly.",
        ),
    ),
    "oshpark-2l": FabProfile(
        name="OSH Park 2-layer prototype",
        layers=2,
        min_copper_mm=6.0 * MIL,   # 0.1524
        min_silk_mm=None,          # UNPUBLISHED
        min_mask_dam_mm=None,      # UNPUBLISHED
        mask_expansion_mm=2.0 * MIL,
        min_drill_mm=13.0 * MIL,
        min_annular_mm=7.0 * MIL,
        mask_colour="purple",
        finish="ENIG, always",
        substrate="FR4",
        surcharge=None,
        source="https://docs.oshpark.com/services/two-layer/",
        notes=("The coarsest profile here; art that survives this survives anywhere.",),
    ),
}


# ---------------------------------------------------------------------------
# THE PROCESS TRAVELS WITH THE ARTWORK
# ---------------------------------------------------------------------------
# An emitter that sizes to a floor and a verifier that checks against a
# different one will happily ship a part that fails its own acceptance test --
# and the failure surfaces long after the command line that caused it is gone.
# Passing the same --fab to both tools fixes it only for as long as somebody
# remembers to type it twice.
#
# So the emitter writes this token into the footprint's `tags`, and the
# verifier reads it back. The part then states which process it was sized for,
# and that statement is the single source both sides resolve through. A part
# with no token is a part sized to the palette doc's generic floor, which is
# the old behaviour and stays the default.
FAB_TAG_PREFIX = "fab:"


def tag_for(key: str) -> str:
    """The footprint tag that records `key` as the process a part was built for."""
    if key not in PROFILES:
        raise KeyError(f"{key!r} is not a fabrication profile; "
                       f"known: {' '.join(sorted(PROFILES))}")
    return f"{FAB_TAG_PREFIX}{key}"


def from_tags(tags: str) -> tuple[str, FabProfile] | None:
    """-> (key, profile) recorded in a footprint's tag string, or None.

    Raises on a tag naming a process this file does not know, and on a part
    claiming two: both mean the part is not describing a process that can be
    checked, and guessing which one was meant is how the emit/verify split
    reopens.
    """
    found = [t[len(FAB_TAG_PREFIX):] for t in (tags or "").split()
             if t.startswith(FAB_TAG_PREFIX)]
    if not found:
        return None
    if len(set(found)) > 1:
        raise ValueError(
            f"footprint is tagged for {len(set(found))} processes at once "
            f"({', '.join(sorted(set(found)))}); it can only have been sized "
            f"for one")
    key = found[0]
    if key not in PROFILES:
        raise ValueError(
            f"footprint is tagged {FAB_TAG_PREFIX}{key} but tools/fab_profiles.py "
            f"knows no such process; known: {' '.join(sorted(PROFILES))}")
    return key, PROFILES[key]


def binding(*names: str) -> FabProfile:
    """The profile that constrains a set -- coarsest copper floor wins.

    Use when one artwork must be fabricable by several processes. Returns the
    profile whose limits govern, so the caller sizes against reality rather
    than against whichever fab they happened to think of first.
    """
    chosen = max((PROFILES[n] for n in names), key=lambda p: p.min_copper_mm)
    return chosen


# ---------------------------------------------------------------------------
# PRODUCT BASELINE
# ---------------------------------------------------------------------------
# SatoshiStarter debuts on PURPLE soldermask with ENIG, whichever fab builds it
# (decision 2026-08-17). That is a palette fact before it is a purchasing one.
#
# T5 is not a colour choice in this system -- it IS the bare board, the tone
# produced by drawing nothing. So the mask colour sets the ground against which
# every other tone is read, and docs/pcb-palette.md's anchors are measured
# against BLACK. They do not describe the product being built.
#
# What changes on purple:
#   T1 silk        white on purple -- still the brightest tone
#   T2 ENIG        gold on purple. Gold and purple sit near-opposite on the
#                  wheel, so this pairing is higher-contrast than gold on black.
#   T3 bare FR4    substrate against purple. NOTE the substrate differs by fab:
#                  OSH Park 4-layer is FR408, JLCPCB is FR4, and they are not
#                  the same shade. T3 is therefore fab-dependent in a way the
#                  other tones are not.
#   T6 copper/mask purple over copper vs purple over substrate. This is the
#                  subtlest distinction in the palette and the one most likely
#                  to collapse; it needs measuring, not predicting.
#
# Consequence: recklessnode/kicad_art_generator#1 must be run on a PURPLE ENIG
# coupon. A black-mask calibration would characterise a board we are not making.
BASELINE_MASK = "purple"
BASELINE_FINISH = "ENIG"


def deviates_from_baseline(profile: FabProfile) -> list[str]:
    """How a profile departs from the purple/ENIG product baseline.

    JLCPCB can hit the baseline but does not by default: HASL is standard there
    and purple is an extended colour, so both must be ordered explicitly. An
    order that silently ships HASL turns T2 from gold into bright tin, which
    changes the artwork rather than merely its tolerance.
    """
    out = []
    if BASELINE_MASK not in profile.mask_colour.lower():
        out.append(f"mask: {profile.mask_colour} -- purple must be ordered explicitly")
    if BASELINE_FINISH.lower() not in profile.finish.lower().split(";")[0]:
        out.append(f"finish: {profile.finish} -- T2 assumes exposed gold")
    return out


def _report() -> None:
    print(f"{'profile':<28} {'copper':>8} {'mask dam':>9} {'min cap':>9}  {'mask':<10} finish")
    for key, p in PROFILES.items():
        dam = f"{p.min_mask_dam_mm:.3f}" if p.min_mask_dam_mm else "unpub."
        print(
            f"{key:<28} {p.min_copper_mm:8.4f} {dam:>9} "
            f"{min_cap_height_mm(p):8.3f}  {p.mask_colour[:10]:<10} {p.finish}"
        )
    print()
    both = binding("jlcpcb-4l-fine", "oshpark-4l")
    fine = PROFILES["jlcpcb-4l-fine"]
    ratio = (min_cap_height_mm(fine) / min_cap_height_mm(both)) ** 2
    print(f"Serving jlcpcb-4l-fine AND oshpark-4l is bound by: {both.name}")
    print(
        f"  cap {min_cap_height_mm(both):.3f} mm vs {min_cap_height_mm(fine):.3f} mm alone; "
        f"character density falls to {ratio * 100:.0f}%"
    )


if __name__ == "__main__":
    _report()


# ---------------------------------------------------------------------------
# MASK AND SILK
# ---------------------------------------------------------------------------
# Silk colour is not an independent choice. Fabs pair it with the mask, and the
# pairing exists because white-on-white is not a legible board: white mask
# defaults to BLACK silk everywhere, and every other mask colour defaults to
# white silk.
#
# This matters far more than a colour swap, because T1 (silk) and T5 (bare
# mask) are the two extremes the rest of the palette is read between. Get the
# pair wrong and tones collapse into each other:
#
#   white mask + white silk   T1 vs T5 = dE 2.2   -- SIX collapsed pairs.
#                             Silkscreen is invisible. This is the same failure
#                             as art whose subject maps to T5: the mark and the
#                             ground are one tone.
#   white mask + black silk   three collapsed pairs, in line with black/purple.
#
# And the ordering INVERTS, which is the part that breaks code rather than eyes:
#
#   black  + white silk   T1 > T3 > T2 > T6 > T7 > T5
#   purple + white silk   T1 > T3 > T2 > T5 > T7 > T6
#   white  + BLACK silk   T5 > T7 > T6 > T3 > T2 > T1
#
# On a white board T1 goes from brightest tone to darkest, and T5 from darkest
# to brightest. Anything that assumes "T1 is the light one" or "T5 is the dark
# ground" -- including the halftone ramp's L* gate, which declines tones below
# 20 L* -- makes the opposite decision there. Ask is_inverted() rather than
# assuming.
#
# All values below except black are ESTIMATES. Black is the only set actually
# measured (docs/pcb-palette.md). recklessnode/kicad_art_generator#1 exists to
# replace these, and it now needs a coupon per mask colour, not one coupon.
MASK_DEFAULT_SILK = {
    "black": "white",
    "purple": "white",
    "green": "white",
    "red": "white",
    "blue": "white",
    "yellow": "black",
    "white": "black",
}

_MASK_RGB = {
    "black": (24, 24, 27),
    "purple": (86, 48, 124),
    "green": (19, 94, 60),
    "white": (240, 240, 238),
}
_SILK_RGB = {"white": (238, 238, 232), "black": (30, 30, 32)}

# Tones that do not depend on the mask: exposed metal and exposed substrate.
_FIXED = {"T2": (198, 158, 72), "T3": (196, 176, 126)}


def _luma(rgb: tuple[int, int, int]) -> float:
    """Rough perceptual lightness, enough to order tones."""
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def tone_anchors(mask: str, silk: str | None = None) -> dict[str, tuple[int, int, int]]:
    """Palette anchors for a mask/silk pair.

    Mask-derived tones are shaded from the mask itself: copper under mask (T6)
    reads darker than bare mask, buried copper (T7) less so. Those shading
    factors are guesses and are exactly what the calibration coupon replaces.
    """
    mask = mask.lower()
    if mask not in _MASK_RGB:
        raise ValueError(f"no anchors for mask colour {mask!r}")
    silk = (silk or MASK_DEFAULT_SILK.get(mask, "white")).lower()
    m = _MASK_RGB[mask]
    dark = 0.72 if _luma(m) > 0.25 else 1.35   # copper darkens a light mask, lifts a dark one
    mid = (1 + dark) / 2
    clamp = lambda v: max(0, min(255, int(round(v))))
    out = dict(_FIXED)
    out["T1"] = _SILK_RGB[silk]
    out["T5"] = m
    out["T6"] = tuple(clamp(c * dark) for c in m)
    out["T7"] = tuple(clamp(c * mid) for c in m)
    out["T4"] = tuple(clamp((a + b) / 2) for a, b in zip(_FIXED["T3"], out["T7"]))
    return out


def is_inverted(mask: str, silk: str | None = None) -> bool:
    """True when T1 is darker than T5 -- the white-board case.

    Callers with lightness-dependent logic must branch on this. The halftone
    ramp is the known one: it ramps from T5 as background toward the tone, and
    on an inverted board that direction is backwards.
    """
    t = tone_anchors(mask, silk)
    return _luma(t["T1"]) < _luma(t["T5"])
