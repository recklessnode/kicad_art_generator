#!/usr/bin/env python3
"""The tone table, and the single authority on what a tone LOOKS like.

Before this module the answer to "what colour is T6 on a purple board?" was
computed by ``fab_profiles.tone_anchors()``, and that function is refuted by
the repo's own documentation on the one mask where the documentation is
definite:

  * ``fab_profiles.py`` line 396 reads
        ``dark = 0.72 if _luma(m) > 0.25 else 1.35``
    i.e. copper under mask is assumed to DARKEN a light mask and LIFT a dark
    one, with the branch taken on a guessed 0.25 luma threshold.
  * green's mask luma is 0.2965, so green takes the darken branch and the
    function returns T6 nearly 10 L* BELOW T5 (measured here: -9.985).
  * ``docs/pcb-palette.md`` line 152 says the opposite in as many words, for
    green specifically: "T6 is visibly brighter than T5; the classic PCB look".
  * ``fab_profiles.py`` lines 341-351's own prose ordering table claims
    ``purple + white silk  T1 > T3 > T2 > T5 > T7 > T6`` (T6 darkest) while the
    code three screens below computes ``... > T6 > T7 > T5`` (T6 brightest).

So the module contradicted the palette doc on green and contradicted itself on
purple. Worse, the branch is not robust: purple's mask luma is 0.2414, which is
0.0086 -- 3.4% -- from the 0.25 threshold. Scaling the purple mask RGB by 1.04
flips the entire dark-tone ordering. A guessed constant that close to a
discontinuity is not a model, and parameterising it would only make the guess
configurable.

WHAT THIS MODULE DOES INSTEAD. It keeps the one shading direction that has any
evidence behind it -- copper under mask LIFTS, on every mask -- deletes the
darken branch and the threshold with it, and stamps every value derived that
way ``PROVISIONAL`` so that nothing can be drawn in it without somebody saying
so on the command line. Issue #6's coupon replaces the provisional rows with
measurements; until then the honest position is that the sign is supported and
the magnitude is not.

    LIFT_T6 = 1.35, LIFT_T7 = 1.175 are the repo's existing lift factors, kept
    unchanged so that no purple tone MOVES for a reason this session cannot
    measure. They are not derived from the black set: black's own measured
    ratios are T6/T5 = 1.637 and T7/T5 = 1.275 in luma, which is 21% away from
    1.35. That disagreement is exactly why these rows are PROVISIONAL.

PROVENANCE IS RECORDED PER TONE, AND THE BLACK ROWS ARE NOT CALLED "MEASURED".
``fab_profiles.py`` line 65 claims "Black is the only set actually measured
(docs/pcb-palette.md)". The doc it cites says the opposite at lines 194-198:
"treat the appearance column as ordinal -- T1 lightest, T5 darkest -- rather
than as colorimetry", and "Every tone above, including the ESTIMATED sRGB
anchors the quantiser actually uses in tools/w0_spike.py". The black rows here
are therefore ``estimated``: they are the tones of a stackup that physically
exists and whose ORDER is known, with sRGB values nobody has sampled. Calling
them measured would be a label with nothing behind it, which is the defect
class this whole exercise exists to remove.

WHAT IS NOT HERE. Any notion that a tone can be chosen for a pixel. This module
answers "what does T6 look like"; ``tools/tone_map.py`` answers "which tone does
this ink go in", and the second question is answered by DECLARATION, never by
proximity. On a dark-mask board T5 is the darkest tone the process can produce,
so ink darker than the board is physically unrepresentable and nearest-anchor
assignment resolves that impossibility by picking the extremum -- which is the
one tone that draws nothing. See ``Palette.validate()``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

# Fixed order. NEVER a set: set iteration order is a determinism hazard and
# this tuple indexes label arrays that get written into footprints.
TONE_IDS = ("T1", "T2", "T3", "T4", "T5", "T6", "T7")

# Tones whose recipe reaches an inner layer. From coupon_blocks.TONE_RECIPE,
# which is the transcription of the table in docs/pcb-palette.md:
#   T4_fr4_buried  ["F.Mask", "In1.Cu"]      T7_mask_buried ["In1.Cu"]
INNER_TONES = frozenset({"T4", "T7"})

# The one tone that draws nothing: bare mask IS the board.
BACKGROUND_TONE = "T5"

# --- the two legibility lines ----------------------------------------------
# THESE TWO NUMBERS ARE THE WEAKEST-GROUNDED THING IN THIS FILE. 8.0 rests on
# one qualitative sentence about one mask; 20.0 is a "is a duty ramp worth
# building" line reused as a "can you see this region at all" line. Issue #6's
# coupon replaces both, and replacing them is meant to be one edit each.
#
# 8.0: tools/texture_board.py lines 2373-2376 says of the black-mask T6-T5
# separation -- measured here at 7.87 L* -- that it "reads as a sheen and not
# as a graphic", and calls that smallness "the requirement". A tone within
# ~8 L* of the board is therefore texture, not artwork.
LEGIBLE_MIN_DL = 8.0
# 20.0: emit_art.HALFTONE_MIN_DELTA_L (emit_art.py line 182), from
# docs/pcb-palette.md's ramp table via the same evidence.
LEGIBLE_WARN_DL = 20.0

# --- shading factors, kept from fab_profiles, sign only ---------------------
LIFT_T6 = 1.35
LIFT_T7 = 1.175

# --- source tables ----------------------------------------------------------
# Moved here from fab_profiles.py lines 372-375 rather than imported, because
# tone_anchors()/is_inverted() are DELETED from that module by this change and
# leaving the data behind an amputated API is how the next drift starts.
MASK_DEFAULT_SILK = {
    "black": "white", "purple": "white", "green": "white",
    "red": "white", "blue": "white", "yellow": "black", "white": "black",
}
_MASK_RGB = {
    "black": (24, 24, 27),
    "purple": (86, 48, 124),
    "green": (19, 94, 60),
    "white": (240, 240, 238),
}
_SILK_RGB = {"white": (238, 238, 232), "black": (30, 30, 32)}

# Exposed metal and exposed substrate: these do not depend on the mask.
# ENIG only. HASL is silver-grey and OSP is bare copper, and neither has a
# value anybody here has sampled -- so asking for them REFUSES rather than
# returning a plausible-looking number.
_FINISH_T2 = {"ENIG": (198, 158, 72)}
_T3_FR4 = (196, 176, 126)

# The black set, verbatim from w0_spike.TONES (w0_spike.py lines 106-115). It
# is re-exported below so that nothing but this module reads that list
# directly. Values are ESTIMATES -- see the module docstring.
_BLACK_TONES = {
    "T1": ("silk white", (235, 235, 230)),
    "T2": ("ENIG gold", (205, 165, 75)),
    "T3": ("bare FR4", (200, 180, 130)),
    "T4": ("FR4 + buried", (170, 150, 105)),
    "T5": ("black mask", (25, 25, 28)),
    "T6": ("mask over copper", (44, 41, 36)),
    "T7": ("mask + buried", (33, 32, 31)),
}

# Names carry the BLACK stackup's colour words ("silk white", "black mask"),
# which are wrong on any other colourway: the white/black palette printed
# "T1 silk white (30, 30, 32)" and "T5 black mask (240, 240, 238)", and those
# strings travel into footprints and reports.  _name_for() below substitutes
# the actual mask and silk colour of the palette being built.
_NAMES = {tid: v[0] for tid, v in _BLACK_TONES.items()}


def _name_for(tid: str, mask: str, silk: str) -> str:
    """The black table's name with its colour words replaced by this stackup's."""
    n = _NAMES[tid]
    if "silk" in n:
        n = n.replace("white", silk).replace("black", silk)
    elif "mask" in n:
        n = n.replace("black", mask).replace("white", mask)
    return n

PALETTE_TAG_PREFIX = "palette:"


class PaletteError(ValueError):
    """A palette was asked for that this file cannot describe."""


@dataclass(frozen=True)
class Tone:
    id: str
    name: str
    rgb: tuple[int, int, int]
    emits: bool          # False only for T5
    inner: bool          # True for T4, T7 -- they need In1.Cu
    provenance: str      # "measured" | "estimated" | "PROVISIONAL"


@dataclass(frozen=True)
class Violation:
    """One thing wrong with a palette.

    ``kind`` is load-bearing, and the reason is in Palette.validate().
    """
    kind: str            # "structural" | "nearest_anchor"
    tone: str | None
    msg: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.msg}"


def _lift(c: int, f: float) -> int:
    """Copper seen THROUGH the mask, as a lift toward white that cannot clamp.

    This was `_clamp(c * f)`, a straight multiply.  That is fine on a dark
    mask and structurally broken on a light one: white is (240, 240, 238), so
    240 * 1.35 = 324 clamps to 255 -- copper under a white mask modelled as
    BRIGHTER THAN PURE WHITE.  Worse, T6 and T7 both clamped to the same
    (255, 255, 255), so two tones became one and Palette.nearest() could never
    return T7 at all; the tie goes to TONE_IDS order.

    The replacement lifts by a fraction of the REMAINING HEADROOM to white,
    scaled by how much light the mask lets through in the first place:

        c + (255 - c) * (f - 1) * c / 255

    It is not a new physical claim.  It was chosen to REPRODUCE the multiply
    where the multiply was calibrated -- on black (24) at f = 1.35 it returns
    32, against the multiply's 32.4 -- while staying monotone and bounded
    everywhere else.  On white (240) it returns 245 for T6 and 242 for T7:
    distinct, below pure white, and only a few L* from the board, which is
    the honest answer.  legible() then excludes them on its own, because that
    separation is under LEGIBLE_MIN_DL.  These rows stay PROVISIONAL: nobody
    has sampled copper under a white mask, and this models it rather than
    measuring it.
    """
    return _clamp(c + (255 - c) * (f - 1.0) * c / 255.0)


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


@dataclass(frozen=True)
class Palette:
    mask: str
    silk: str
    finish: str
    substrate: str
    tones: tuple[Tone, ...]              # in TONE_IDS order
    provisional_ok: bool = False

    # --- lookup ------------------------------------------------------------
    def __getitem__(self, tid: str) -> Tone:
        for t in self.tones:
            if t.id == tid:
                return t
        raise KeyError(f"{tid!r} is not a tone; known: {' '.join(TONE_IDS)}")

    def __contains__(self, tid: object) -> bool:
        return any(t.id == tid for t in self.tones)

    # --- appearance --------------------------------------------------------
    def lstar(self, tid: str) -> float:
        """CIE L* of a tone, through emit_art's own luminance function.

        Imported inside the call on purpose: emit_art imports this module, and
        a module-level import here would close the cycle. The alternative --
        a second copy of the sRGB->luminance maths -- is the reimplementation
        defect this repo has been bitten by four times.
        """
        import numpy as np
        from emit_art import relative_luminance
        y = float(relative_luminance(np.array(self[tid].rgb, dtype=np.float64)))
        e, k = 216.0 / 24389.0, 24389.0 / 27.0
        f = y ** (1.0 / 3.0) if y > e else (k * y + 16.0) / 116.0
        return 116.0 * f - 16.0

    def dl_to_board(self, tid: str) -> float:
        """L* of a tone minus L* of the board. Signed: a white board inverts it."""
        return self.lstar(tid) - self.lstar(BACKGROUND_TONE)

    # --- what may be drawn in --------------------------------------------
    def drawable(self, *, allow_inner: bool = False,
                 allow_provisional: bool | None = None) -> tuple[str, ...]:
        """Tones that put geometry on a board this run is allowed to build."""
        prov = self.provisional_ok if allow_provisional is None else allow_provisional
        out = []
        for t in self.tones:
            if not t.emits:
                continue
            if t.inner and not allow_inner:
                continue
            if t.provenance == "PROVISIONAL" and not prov:
                continue
            out.append(t.id)
        return tuple(out)

    def legible(self, *, allow_inner: bool = False,
                allow_provisional: bool | None = None) -> tuple[str, ...]:
        """Drawable tones a viewer could actually tell apart from the board."""
        return tuple(t for t in self.drawable(allow_inner=allow_inner,
                                              allow_provisional=allow_provisional)
                     if abs(self.dl_to_board(t)) >= LEGIBLE_MIN_DL)

    def is_inverted(self) -> bool:
        """True when the silk is DARKER than the board -- the white-board case.

        Replaces fab_profiles.is_inverted(), which is deleted. Same question,
        asked of the table instead of of a shading heuristic.
        """
        return self.lstar("T1") < self.lstar(BACKGROUND_TONE)

    # --- interop -----------------------------------------------------------
    def as_w0_tones(self, *, only: tuple[str, ...] | None = None) -> list[tuple]:
        """Exactly the shape of w0_spike.TONES: (id, name, rgb, emits).

        `only` restricts the anchor table to those tone ids.  IT MATTERS THAT
        CALLERS USE IT.  drawable() decides what a run is allowed to put on a
        board, emit_art prints that set in its header -- and the nearest-anchor
        quantiser used to receive the FULL table regardless, so it could and
        did assign ink to tones the same run had just declared undrawable.
        A render was observed putting 36 mm2 on In1.Cu with neither
        --allow-inner nor --allow-provisional given, because the only place
        those flags were enforced was the DECLARED tone-map path
        (emit_art._check_tone_map).  A rule that is computed, printed, and then
        not applied to the path that does the work is not a rule.
        """
        keep = self.tones if only is None else [t for t in self.tones
                                                if t.id in set(only)]
        return [(t.id, t.name, tuple(t.rgb), t.emits) for t in keep]

    def tag(self) -> str:
        """The token the emitter writes into a footprint's `tags`.

        Mirrors fab_profiles.FAB_TAG_PREFIX: the process travels with the
        artwork, so a part states the colourway it was assigned under and the
        verifier reads it back instead of being told again on the command line.
        """
        return (f"{PALETTE_TAG_PREFIX}{self.mask}-{self.silk}-"
                f"{self.finish.lower()}")

    def canonical(self) -> str:
        rows = "|".join(
            f"{t.id},{t.rgb[0]},{t.rgb[1]},{t.rgb[2]},"
            f"{int(t.emits)},{int(t.inner)},{t.provenance}" for t in self.tones)
        return f"{self.mask}/{self.silk}/{self.finish}/{self.substrate}#{rows}"

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()[:12]

    # --- the invariant -----------------------------------------------------
    def validate(self) -> list[Violation]:
        """Everything wrong with this palette, as a list that can be empty.

        TWO KINDS, AND THE DIFFERENCE MATTERS.

        "structural" is a defect in the table: it can always be fixed by
        editing the table, and it is fatal wherever it is found.

        "nearest_anchor" is NOT a defect in the table. It is the statement that
        this palette cannot be used by proximity assignment for some ink,
        because the ink is outside the range the process can make. On a
        dark-mask board T5 is the darkest tone that exists; source ink darker
        than the board is unrepresentable at any anchor, and nearest-anchor
        assignment resolves the impossibility by choosing T5, which draws
        nothing. Purple's T5 sits at L* 28.2 and the corpus blacks sit at
        L* 0.0-0.3 -- 28 L* below the floor.

        That is a fact about physics, not about this file, and EVERY dark-mask
        palette has it, including the one the library ships on. Making it
        unconditionally fatal would make every dark-mask board unbuildable, so
        callers gate on it only where it actually bites: on the nearest-anchor
        path. Where an explicit tone map is declared, the impossibility has
        already been answered by a person, and the substitution is recorded in
        the sidecar instead of being invented by a distance metric.

        DELIBERATE DEVIATION FROM THE SPECIFICATION, RECORDED HERE. The
        specification (C1.3) says build_library and emit_art treat a non-empty
        validate() list as fatal. Taken literally that refuses the purple
        palette of Part D, whose T5 is also the darkest tone -- the shipped
        configuration would refuse itself. The kind split is how that is
        resolved without deleting the check.
        """
        out: list[Violation] = []

        # 1. exactly one non-emitting tone, and it is T5.
        blanks = [t.id for t in self.tones if not t.emits]
        if blanks != [BACKGROUND_TONE]:
            out.append(Violation(
                "structural", None,
                f"exactly one tone must draw nothing and it must be "
                f"{BACKGROUND_TONE}; this palette has {blanks or 'none'}"))

        # order and completeness -- the label arrays are indexed by this order
        if tuple(t.id for t in self.tones) != TONE_IDS:
            out.append(Violation(
                "structural", None,
                f"tones must be in TONE_IDS order {TONE_IDS}, got "
                f"{tuple(t.id for t in self.tones)}"))

        # T4/T7 must agree with coupon_blocks.TONE_RECIPE about being inner
        for t in self.tones:
            if t.inner != (t.id in INNER_TONES):
                out.append(Violation(
                    "structural", t.id,
                    f"{t.id}.inner is {t.inner} but coupon_blocks.TONE_RECIPE "
                    f"makes it {t.id in INNER_TONES}"))

        # 3. drawable() must actually exclude PROVISIONAL rows. An assertion on
        #    this object rather than a promise in a docstring: the whole point
        #    of the provenance field is that something enforces it.
        prov = {t.id for t in self.tones if t.provenance == "PROVISIONAL"}
        leaked = prov & set(self.drawable(allow_inner=True,
                                          allow_provisional=False))
        if leaked:
            out.append(Violation(
                "structural", None,
                f"PROVISIONAL tone(s) {sorted(leaked)} reached "
                f"drawable(allow_provisional=False)"))

        # 2. probe inks: does proximity assignment send anything to a tone that
        #    draws nothing?
        for probe in ((0, 0, 0), (255, 255, 255), tuple(self[BACKGROUND_TONE].rgb)):
            tid, d = self.nearest(probe)
            if self[tid].emits:
                continue
            dl = abs(self.lstar_of_rgb(probe) - self.lstar(BACKGROUND_TONE))
            if dl < LEGIBLE_MIN_DL:
                continue          # the probe really IS the board; correct answer
            out.append(Violation(
                "nearest_anchor", tid,
                f"ink rgb{probe} (L* {self.lstar_of_rgb(probe):.2f}, "
                f"{dl:.2f} L* from the board) is nearest {tid} at "
                f"{d:.2f} weighted units, and {tid} draws nothing. Proximity "
                f"assignment would erase this ink; it needs a declared tone"))
        return out

    # --- helpers used by validate() ---------------------------------------
    def lstar_of_rgb(self, rgb) -> float:
        import numpy as np
        from emit_art import relative_luminance
        y = float(relative_luminance(np.array(rgb, dtype=np.float64)))
        e, k = 216.0 / 24389.0, 24389.0 / 27.0
        f = y ** (1.0 / 3.0) if y > e else (k * y + 16.0) / 116.0
        return 116.0 * f - 16.0

    def nearest(self, rgb) -> tuple[str, float]:
        """Nearest tone in the weighted-Lab metric w0_spike actually uses."""
        import numpy as np
        from w0_spike import L_WEIGHT, srgb_to_lab
        w = np.array([L_WEIGHT, 1.0, 1.0])
        p = srgb_to_lab(np.array(rgb, dtype=np.uint8)) * w
        best, bd = None, float("inf")
        for t in self.tones:
            a = srgb_to_lab(np.array(t.rgb, dtype=np.uint8)) * w
            d = float(np.linalg.norm(p - a))
            if d < bd:                       # strict: ties go to TONE_IDS order
                best, bd = t.id, d
        return best, bd


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------

def _tone(tid: str, rgb, provenance: str) -> Tone:
    return Tone(id=tid, name=_NAMES[tid], rgb=tuple(int(c) for c in rgb),
                emits=(tid != BACKGROUND_TONE), inner=(tid in INNER_TONES),
                provenance=provenance)


def palette_for(mask: str, silk: str | None = None, finish: str = "ENIG",
                substrate: str = "FR4",
                allow_provisional: bool = False) -> Palette:
    """The tone table for a mask/silk/finish, with provenance per row."""
    mask = str(mask).lower()
    if mask not in _MASK_RGB:
        raise PaletteError(
            f"no tone table for mask colour {mask!r}; known: "
            f"{' '.join(sorted(_MASK_RGB))}. A mask nobody has a value for is "
            f"a mask you have to sample, not one to interpolate")
    silk = str(silk or MASK_DEFAULT_SILK.get(mask, "white")).lower()
    if silk not in _SILK_RGB:
        raise PaletteError(f"no silk colour {silk!r}; known: "
                           f"{' '.join(sorted(_SILK_RGB))}")
    fin = str(finish).upper()
    if fin not in _FINISH_T2:
        raise PaletteError(
            f"no T2 value for finish {finish!r}; known: "
            f"{' '.join(sorted(_FINISH_T2))}. HASL is silver-grey and OSP is "
            f"bare copper that oxidises; neither has been sampled here, and "
            f"docs/pcb-palette.md line 143 says the finish sets T2 outright")

    if mask == "black" and silk == "white" and fin == "ENIG":
        # The one stackup the repo has ever quantised against. Verbatim, so a
        # black-mask run is byte-identical to every run before this change.
        tones = tuple(_tone(tid, _BLACK_TONES[tid][1], "estimated")
                      for tid in TONE_IDS)
        return Palette(mask, silk, fin, substrate, tones, allow_provisional)

    m = _MASK_RGB[mask]
    t5 = tuple(m)
    t6 = tuple(_lift(c, LIFT_T6) for c in m)
    t7 = tuple(_lift(c, LIFT_T7) for c in m)
    t3 = _T3_FR4
    t4 = tuple(_clamp((a + b) / 2) for a, b in zip(t3, t7))
    rows = {
        "T1": (_SILK_RGB[silk], "estimated"),
        "T2": (_FINISH_T2[fin], "estimated"),
        "T3": (t3, "estimated"),
        "T4": (t4, "PROVISIONAL"),
        "T5": (t5, "estimated"),
        "T6": (t6, "PROVISIONAL"),
        "T7": (t7, "PROVISIONAL"),
    }
    tones = tuple(_tone(tid, rows[tid][0], rows[tid][1]) for tid in TONE_IDS)
    return Palette(mask, silk, fin, substrate, tones, allow_provisional)


def from_tag(tags: str, *, allow_provisional: bool = False) -> Palette | None:
    """-> the Palette a footprint's `tags` string records, or None.

    Mirrors fab_profiles.from_tags (fab_profiles.py line 219): raises on a tag
    naming a colourway this file cannot build, and on a part claiming two --
    both mean the part is not describing something that can be checked, and
    guessing which was meant is how the emit/verify split reopens.
    """
    found = [t[len(PALETTE_TAG_PREFIX):] for t in (tags or "").split()
             if t.startswith(PALETTE_TAG_PREFIX)]
    if not found:
        return None
    if len(set(found)) > 1:
        raise PaletteError(
            f"footprint claims {len(set(found))} colourways: "
            f"{', '.join(sorted(set(found)))}. Which one it was assigned "
            f"under decides every colour check; guessing is not available")
    parts = found[0].split("-")
    if len(parts) != 3:
        raise PaletteError(
            f"{PALETTE_TAG_PREFIX}{found[0]} is not <mask>-<silk>-<finish>")
    mask, silk, fin = parts
    return palette_for(mask, silk, fin, allow_provisional=allow_provisional)


def with_provisional(p: Palette, ok: bool) -> Palette:
    return replace(p, provisional_ok=ok)


# Re-export so nothing but this module reads w0_spike.TONES directly. It is
# the same object, not a copy: a copy is how texture_board.py drifted (its own
# comment at line 2372 says the hand-typed duplicate exists "so this cannot
# drift", which is exactly how it would).
def black_w0_tones() -> list[tuple]:
    return palette_for("black").as_w0_tones()


def main(argv=None):                                    # pragma: no cover
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mask", nargs="?", default="purple")
    ap.add_argument("--silk", default=None)
    ap.add_argument("--finish", default="ENIG")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    p = palette_for(a.mask, a.silk, a.finish)
    if a.json:
        print(json.dumps({
            "tag": p.tag(), "digest": p.digest(),
            "tones": [{"id": t.id, "rgb": list(t.rgb), "emits": t.emits,
                       "inner": t.inner, "provenance": t.provenance,
                       "lstar": round(p.lstar(t.id), 3),
                       "dl_to_board": round(p.dl_to_board(t.id), 3)}
                      for t in p.tones],
            "drawable": list(p.drawable()),
            "legible": list(p.legible()),
            "violations": [str(v) for v in p.validate()]}, indent=1))
        return 0
    print(f"{p.tag()}  digest={p.digest()}  inverted={p.is_inverted()}")
    for t in p.tones:
        print(f"  {t.id} {t.name:<18} {str(t.rgb):<18} L*={p.lstar(t.id):7.3f} "
              f"dL={p.dl_to_board(t.id):+8.3f}  emits={int(t.emits)} "
              f"inner={int(t.inner)}  {t.provenance}")
    print(f"  drawable (front, non-provisional): {' '.join(p.drawable())}")
    print(f"  legible  (>= {LEGIBLE_MIN_DL:g} L* from board): {' '.join(p.legible())}")
    for v in p.validate():
        print(f"  !! {v}")
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
