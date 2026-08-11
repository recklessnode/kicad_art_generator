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
