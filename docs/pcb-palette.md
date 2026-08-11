# The PCB colour palette

What tones a board can actually produce, and the exact layer combination that
generates each. This is the target the quantiser maps onto — everything the
converter does is in service of landing source colours on this table.

Reference stackup throughout is the Satoshi Starter, read from its board file:

```
F.SilkS
F.Mask        0.01 mm
F.Cu          0.035 mm
prepreg       0.10 mm     <- governs buried-tone visibility
In1.Cu        0.035 mm
core          1.24 mm
In2.Cu        0.035 mm
prepreg       0.10 mm
B.Cu          0.035 mm
B.Mask        0.01 mm
B.SilkS
```

## The four controllable layers

Per side, art is a choice over four binary controls:

| layer | sense | note |
|---|---|---|
| `F.SilkS` | additive | opaque ink. Topmost — hides everything beneath. |
| `F.Mask` | **negative** | drawing on it *removes* mask, creating an opening. |
| `F.Cu` | additive | the metal. |
| `In1.Cu` | additive | ~0.11 mm below the surface. Modulates, never dominates. |

`In2.Cu` is ~1.375 mm from the front and contributes **nothing** to front-side
appearance. It is the *back* side's buried layer. The two sides are symmetric:
`In1` shades the front, `In2` shades the back.

## Two hard constraints

**Silkscreen requires mask beneath it.** Fabs strip silk that lands on a mask
opening — the ink will not adhere to a solderable surface. KiCad enforces this
and names it directly: `silk_over_copper` → *"Silkscreen clipped by solder
mask"*. The Satoshi Starter currently trips it 121 times. So **silk and
mask-opening are mutually exclusive**, which collapses the 16 nominal
combinations considerably.

**Exposed copper is solderable.** Art on tone T2 is a wettable surface. Keep it
clear of pads and paste, or assembly will find it.

## The palette

Front side, on the black-mask / ENIG stackup in use. `—` means the layer is not
drawn.

| tone | appearance | `F.SilkS` | `F.Mask` | `F.Cu` | `In1.Cu` | mechanism |
|---|---|---|---|---|---|---|
| **T1** | white | **ink** | closed | any | any | opaque ink over mask |
| **T2** | gold (metal) | — | **open** | **yes** | any | plating finish exposed |
| **T3** | tan | — | **open** | no | no | bare laminate exposed |
| **T4** | tan, shadowed | — | **open** | no | **yes** | laminate + buried copper beneath |
| **T5** | black | — | closed | no | no | mask over laminate — *the background* |
| **T6** | black, sheen | — | closed | **yes** | any | mask over copper |
| **T7** | black, deeper | — | closed | no | **yes** | mask over laminate + buried copper |

Seven distinct tones. Three of them (T5/T6/T7) are dark-on-dark and separate
only subtly — these are the concentric rings and chevron fields visible in the
reference board.

### How to draw each in a footprint

```
T1  fp_poly on F.SilkS
T2  fp_poly on F.Cu  +  identical fp_poly on F.Mask
T3  fp_poly on F.Mask
T4  fp_poly on F.Mask  +  fp_poly on In1.Cu
T5  draw nothing                       <- background
T6  fp_poly on F.Cu
T7  fp_poly on In1.Cu
```

**T5 is the absence of everything.** The quantiser should choose the most
common source tone as background and emit no geometry for it at all. That is
both correct and the single largest file-size saving available.

### Precedence

Not sixteen free combinations — a decision tree:

```
silk?  -> T1, done. Nothing below matters.
mask open?  -> copper? T2 : (buried? T4 : T3)
mask closed -> copper? T6 : (buried? T7 : T5)
```

## What changes the palette

**Surface finish sets T2 only.** ENIG → gold. HASL → silver-grey. OSP → bare
copper, salmon, and it oxidises over time. One finish per board, so **there is
exactly one metal tone available**.

**Mask colour sets the dark-tone spread.**

| mask | T5/T6/T7 separation | note |
|---|---|---|
| black | subtle | the reference board — high-end look, low dark contrast |
| green | **marked** | T6 is visibly brighter than T5; the classic PCB look |
| white | — | T1 and T5 nearly collapse. Avoid for art. |
| blue / red | intermediate | |

**Silk colour** is usually white; black and yellow are available. On a dark
board, white is maximum contrast.

## Practical limits

**Minimum feature**, roughly, and vendor-dependent:

| layer | min feature |
|---|---|
| silkscreen | ~0.15 mm |
| mask opening | ~0.1 mm |
| copper | ~0.1 mm |
| **buried tone (T4, T7)** | **considerably larger — see below** |

**Buried tones blur.** T4 and T7 are shadows cast through 0.1 mm of dielectric,
so their edges are diffuse rather than crisp. Fine detail will not read.
Treat them as *fields and broad shapes*, not linework — which is exactly how
the reference board uses them.

**Tone boundaries that depend on two layers stack two tolerances.** The T2/T6
edge is defined by a mask edge landing on a copper edge, and mask registration
is typically ±0.05 mm. Do not rely on that boundary for fine detail; oversize
the copper relative to the mask opening so registration error moves the edge
within copper rather than off it.

## Getting real values

The sRGB numbers for these tones are genuinely vendor- and finish-dependent,
and no table written from theory should be trusted for matching. **We have a
physical reference board.** The correct way to populate real values is to
photograph it under diffuse light alongside a colour reference card and sample
each tone.

Until that is done, treat the appearance column as ordinal — T1 lightest, T5
darkest — rather than as colorimetry.

---

# Shading between tones: hatching and stippling

The seven tones are discrete. Spatial modulation — varying line width, line
pitch, or dot size — creates *apparent* intermediate values between them. This
works on a PCB, with one governing caveat.

## The caveat: at any fabricable size, the texture is visible

The eye resolves roughly 1 arcminute. At a 300 mm viewing distance that is
**0.087 mm**; at arm's length, ~0.12 mm.

Minimum fabricable features are 0.15 mm (silk) and 0.1 mm (mask, copper). A
halftone cell needs to be several times the minimum feature to carry useful
levels — eight grey levels from a 0.15 mm minimum dot needs a cell around
0.5 mm. At 300 mm that cell subtends **~5.7 arcmin, roughly 6× the resolving
limit**.

So PCB halftone is **coarser than newsprint** and will always read as visible
texture rather than smooth tone. That is not a defect to engineer around — it
is the medium. Design for a deliberate engraved or banknote look, not for
invisible blending. Which happens to suit a Bitcoin-adjacent board rather well.

## Technique ranking, by fabrication reliability

**1. Line-width modulation (best).** Parallel or contour-following lines whose
stroke width tracks source luminance. Connected geometry, so no isolated-feature
dropout — screen printing handles lines far more reliably than small dots. This
is the classic engraving technique and the right default.

**2. Line-pitch modulation.** Constant width, varying spacing. Slightly less
dynamic range, equally reliable.

**3. Isolated dots / true stipple (riskiest).** Silk dots near the minimum size
print inconsistently and drop out. Use only well above minimum, and expect
vendor variation.

## Where it earns its place

Only between tone pairs with real contrast:

| ramp | mechanism | value |
|---|---|---|
| **T5 → T1** black ↔ white | silk line width on mask | highest contrast — the primary ramp |
| **T5 → T2** black ↔ gold | mask-opening width over copper | second ramp; watch dams |
| T3 → T2 tan ↔ gold | copper width under an opening | narrow use |
| T5 → T6 | copper width under mask | too subtle on black mask to be worth it |

## Two hard constraints

**Mask dams.** If hatching *mask openings*, the mask remaining between adjacent
openings must stay above roughly 0.1 mm or it washes away in processing — at
which point the hatch merges into one solid opening and the tone jumps to flat
T2. This caps mask-hatch duty cycle at roughly 60–70 %, well short of solid.

**Cost is not free.** `fp_line` carries its own `(stroke (width …))`, so
variable width needs no filled geometry — but a line can only hold one width,
so tonal variation *along* a line requires splitting it into segments. Measured
here: **153 bytes per segment**, and a naive 25 mm square hatched at 0.4 mm
pitch with 1 mm segments came to **1,550 segments / 238 KB** — no better than
the solid-fill problem being fixed.

The fix is adaptive segmentation: split only where the width changes by a
meaningful step. Eight tonal levels rather than 25 takes the same square to
roughly 500 segments / 76 KB. **Quantise the ramp before segmenting, not after.**

## Sequencing

This is a v2 feature. It sits naturally in the rebuild's `legalize.py`, which
already reasons about per-tone minimum feature — a hatch is simply a legal way
to render a value *between* two palette entries, subject to the same
constraints. The v1 architecture should not preclude it, and does not.

---

# Microprinting

Achievable, but **only in copper**, and at roughly 2–3× coarser than banknote
microprinting. The effect still works; the scale does not match.

## Why copper and not silkscreen

Etching is photolithographic; silkscreen is a mesh screen print. Copper is
about twice as fine, and that difference decides the whole question.

| medium | min feature | implied min character height* |
|---|---|---|
| silkscreen | ~0.15 mm | **~0.9–1.2 mm** — not microprinting, just small text |
| copper, typical fab | 0.127 mm (5 mil) | ~0.85 mm |
| copper, capable fab | 0.075–0.09 mm | **~0.5–0.7 mm** ← the usable route |
| *banknote reference* | — | *0.15–0.25 mm* |

\* legible stroke-to-height runs about 1:6 to 1:8.

At **0.5 mm** character height and 300 mm viewing distance, text subtends
~5.7 arcmin. Character recognition needs roughly 5 arcmin, so it sits right at
the threshold — **reads as a hairline to the naked eye, resolves under a loupe
or a phone macro.** That is the microprinting effect, just at a coarser pitch
than currency.

## Do not open the mask per glyph

Mask registration is ±0.05 mm. Against a 0.075 mm stroke that is two-thirds of
the feature — per-glyph mask openings will not survive it. Two forms work:

**1. One mask opening over the whole text block, copper letterforms inside.**
Gold letters on bare laminate (T2 on T3). Registration only has to place the
block edge, never a glyph edge. This is the high-contrast option.

**2. Copper under mask, no opening at all** (T6). Dark-on-dark, extremely
subtle, and immune to registration entirely. Genuinely covert — visible as a
faint sheen at the right angle. Arguably the more interesting security feature.

## Practical limits

**Etch tolerance eats the margin.** At a 0.075 mm stroke, line-width tolerance
of ±0.025 mm is a third of the feature, and glyph shapes degrade. Treat 0.5 mm
as best-case and **0.6–0.8 mm as the reliable zone**.

**Vendor capability varies sharply.** 0.127 mm (5 mil) is standard; 0.09 mm is
an advanced option at extra cost; 0.075 mm needs a capable fab. Microprinting is
a per-vendor decision, not a design constant.

**The board's own rules will reject it.** The Satoshi Starter currently sets
`min_text_height 0.8 mm` and `min_text_thickness 0.08 mm`, and routes nothing
narrower than 0.2 mm. Microtext at 0.5 mm is a DRC violation *by the board's own
configuration* — so art has to be excluded from those constraints. The
`RecklessArt` library-membership exclusion already planned covers this; it does
not need separate machinery.

## Cost

Negligible, and worth contrasting with hatching. `fp_text` uses KiCad's built-in
stroke font, so a whole string is one object: **468 bytes for two complete
strings**, measured. Glyph outlines as `fp_poly` would be orders of magnitude
worse. Text stays text.
