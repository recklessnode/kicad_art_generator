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

## What of this document you can actually run

This file is both the specification and the status board. Some of what follows
is a **conversion mode** — feed it an image and the technique comes out the other
end — and some is still only **calibration geometry**, drawn parametrically for a
test coupon and not driven by any picture. Every implemented technique below
carries an **In the emitter** heading naming its flags; this table is the index.

| technique | status | how you run it |
|---|---|---|
| T1–T7 flat tones | **conversion mode** | the default: `tools/emit_art.py --labels IMG --width-mm N --name NAME -o OUT` |
| line-width modulation *(technique 1)* | **conversion mode** | `--fill-mode hatch`, with `--hatch-pitch` / `--hatch-angle` / `--halftone-levels` |
| line-pitch modulation *(technique 2)* | **not implemented** | pitch is a constant, not a per-cell variable |
| stipple, by dot size *(technique 3)* | **conversion mode** | `--fill-mode stipple`, with `--stipple-pitch` / `--halftone-levels` |
| microprinting | **conversion mode** | `tools/microtext.py`, or `--microtext STRING --microtext-height MM --microtext-tone TONE` on an art footprint |
| knockout | **conversion mode** | `--knockout MARK[:HOST]`, with `--knockout-floor-mult` |
| silhouette keyline | **conversion mode** | `--silhouette-tone TONE --silhouette-mm WIDTH` |
| **T8** translucent window | **conversion mode, but half a part** | `--window-tone TONE` emits the two mask openings only; the four copper keepouts *cannot* be footprint-borne and have to be drawn on the board |
| **T9** cuts | **conversion mode** | `--cut-tone TONE`, with `--cut-fillet-mm` / `--cut-outer-fillet-mm` |
| tone patches, buried wedges, ladders, registration marks | **calibration geometry only** | `tools/coupon_ladders.py`, `tools/coupon_blocks.py` — parametric, no image goes in |
| the five-technique visual study | **not footprints at all** | `tools/technique_demo.py` writes a PNG |
| arcs inside `fp_poly` | **measured, not emitted** | KiCad round-trips them and they are smaller; the emitter still writes straight RDP polylines |

Every mode's output is expected to pass `tools/verify_art.py`. It has one known
blind spot, named under **Knockout** below. What the implemented modes are
allowed to promise rests on the measurements collected under **Measured, not
assumed** at the end of this file.

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

**And T5 has no silhouette.** A source region that quantises to T5 draws
nothing, so it is indistinguishable from the board around it. On Tux that is
**34.7 % of the figure** — his entire body — which dissolves into the board with
no edge at all. Colour data cannot recover the boundary, because body and
background are then the same tone and contiguous; the alpha channel still can.
`tools/emit_art.py --silhouette-tone TONE --silhouette-mm WIDTH` reassigns a ring
of the alpha edge to a contrasting tone. Measured under **Measured, not assumed**
below.

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

**And buried tones cannot be previewed from a footprint at all.** `kicad-cli fp
export svg` emits nothing whatsoever for `In1.Cu` — measured, see the end of this
file — so T4 and T7 are invisible in every footprint-level SVG render. Confirming
one means plotting from a board or opening the part in the GUI.

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

**And this is a black-mask set.** Every tone above, including the estimated sRGB
anchors the quantiser actually uses in `tools/w0_spike.py`, describes the
black-mask / ENIG stackup. A green board is not this palette re-lit — it needs
its own sampled anchors. The green-mask figures in `docs/images/` are a
**render-time colour choice, not a calibration**, so a coverage percentage read
off them describes geometry rather than appearance. Both gaps close under the
same issue, **#1 — sample real tones from a reference board**.

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

## In the emitter

`tools/emit_art.py --fill-mode hatch|stipple` makes this a conversion mode. A
source *gradient* becomes a duty-cycle field between the T5 background (duty 0,
which draws nothing) and the tone solid (duty 1), so a picture is no longer
limited to seven flat tones. `--hatch-pitch` (0.40 mm), `--hatch-angle` (45°, off
both raster axes so the mark grid cannot beat against the pixel grid),
`--stipple-pitch` (0.50 mm) and `--halftone-levels` (8) drive it. It needs the
source *image*: a `.npy` of labels has already thrown the shading away.

Which of the three techniques above that is, precisely:

- `hatch` is **technique 1, line-width modulation** — the pitch is constant and
  the mark width tracks duty.
- `stipple` is **technique 3**, dot size on a fixed grid.
- **Technique 2, pitch modulation, is not implemented.** Pitch is a constant, not
  a per-cell variable.

Marks are emitted as **filled quads, not `fp_line` strokes**, which revises the
cost argument above: a stroke has round caps that bulge half a width past the
clip, and one line can hold only one width anyway. So the unit of cost is a
polygon, and the prediction above is worth checking against it.

**It holds.** `output/w1_halftone/grad_hatch` is the same case that section
projects — a 25 mm square, 0.4 mm pitch, quantised to 8 levels — and comes out at
**677 filled marks / 105.5 kB** against the projected ~500 segments / 76 KB. Same
order, about a third above the estimate, and two tones deep rather than one. The
rule the estimate rests on is the one that matters and it survives: quantise the
ramp *before* segmenting.

On real art the ratio is milder, because most of a picture is flat. The 25 mm
Satoshi asset: solid 85,458 B / 454 polygons, stipple 94,865 B, hatch 138,013 B /
818 polygons. A smooth ramp is the opposite extreme — `grad_solid` is 2,113 B
because a gradient quantises to almost nothing at all, and `grad_hatch` is
108,061 B because the hatch is the only thing rendering it.

### The floor sets the duty range, and it is narrow

The layer's minimum feature applies to the mark **and** to the dam between marks,
so duty is confined to `floor/pitch … 1 − floor/pitch`, with 0 and 1 exact at
either end. Measured from `output/w1_halftone/satoshi_hatch.json` at the default
0.4 mm pitch:

| tone | layers | floor | achievable duty |
|---|---|---|---|
| T1 | `F.SilkS` | 0.15 mm | 0.377 – 0.623 |
| T2 | `F.Cu` + `F.Mask` | 0.10 mm | 0.253 – 0.748 |
| T3 | `F.Mask` | 0.10 mm | 0.253 – 0.748 |

That 0.748 **is** this document's "roughly 60–70 % duty" cap on mask hatch,
measured: the cap is pitch-dependent, and at 0.4 mm pitch it is 75 %. Silk, with
the coarser floor, gets only the middle quarter of its ramp. A pitch below twice
the floor can hold no duty at all — the emitter says so and reports every
clamped pixel rather than clamping quietly. Stipple is worse, exactly as the
ranking above predicts: dots on a square grid put duty at the *square* of the
linear ratio, measured 0.091 – 0.487 for T1 and 0.041 – 0.637 for T2 at the
0.5 mm default pitch.

### It declines the ramps this document calls worthless

The ramp table above rates T5 → T6 "too subtle on black mask to be worth it".
The emitter enforces that with a 20 L\* threshold and names what it skipped:
measured against the black-mask anchors, **T6 is 7.9 L\* from the T5 background
and T7 is 3.4 L\***, so both are drawn **solid** and the geometry a halftone
would have cost is never spent. T1 (84.1 L\*), T2 (60.9) and T3 (65.0) are
patterned.

All layers of a tone's recipe carry the **same** marks, so T2 stays copper and
mask coincident — hatching only the mask would turn the space between marks into
T6 rather than into background.

## Sequencing — superseded

Written as a v2 feature, to sit in the rebuild's `legalize.py`. It arrived
earlier than that, in `tools/emit_art.py`, for the reason the original note
gives: the duty ladder needs precisely what `legalize.py` was going to provide —
per-tone minimum feature — and the emitter already had it. The framing survives
the schedule slipping forward, and whatever replaces `emit_art.py` must keep it:
a hatch is a legal way to render a value *between* two palette entries, under the
same constraints as either end.

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

## In the emitter

`tools/microtext.py --text STRING --height MM --tone TONE` places microtext, as
a single run, along a `--path`, or filling a `--region` with repeated rows.
`tools/emit_art.py` carries the same flags prefixed `--microtext-*`, so a
microprint can go onto an art footprint in one pass.

It enforces the two rules above rather than restating them. Silk below the cap
height its own floor implies is **refused**, not quietly promoted; so are `T3`
(the letterforms would *be* the mask opening) and the buried tones, which this
document says are fields and broad shapes, not linework. `T2` puts copper
letterforms inside **one** block opening and `T6` puts copper under mask with no
opening at all — the two forms named above, and the only two offered.

### The counters are measurable, so they are measured

`tools/stroke_font.py` reads KiCad's newstroke font off a `kicad-cli fp export
svg` render, which writes the stroke centrelines as plain polylines. For every
printable ASCII glyph it records the advance, the ink box, and the inscribed
radius *D* of the narrowest enclosed void, all in em. Because the ink is centred
on the centreline, a counter's clear width is then exactly

    clear = 2·D·cap − stroke

which turns "closed letterforms fail before straight strokes" into a number. At
the 1:6.7 stroke ratio the crossover is at **D = 0.15 em**: a glyph with a
tighter counter than that fails before its own strokes do. Measured, `'e'` is
0.147, `'@'` 0.214, `'8'` 0.214, `'B'` 0.238 — so `e` is the first thing in
`coupon_ladders.SPECIMEN` to close, which is why that specimen was chosen.

For the full specimen on copper, against this document's 0.1 mm floor:

| limit | smallest cap height |
|---|---|
| stroke ≥ 0.1 mm | 0.667 mm |
| **counter ≥ 0.1 mm** | **0.690 mm** ← binds |
| legibility (0.6 mm) | 0.600 mm |

**0.695 mm**, rounded up to a 5 µm step, passes every check in
`tools/verify_art.py`. That lands inside the 0.6–0.8 mm reliable zone above
without having been aimed at it. At a standard fab's 0.127 mm the same string
needs 0.88 mm — the per-vendor point above, in millimetres.

### KiCad slides the text as the pen gets heavier

Measured against KiCad 10.0.0: `justify left` justifies the text *box*, which
includes the pen, so the letterforms sit **0.658 × stroke to the right and
0.052 × stroke above** the anchor. Pure translation — the string's own extent
does not change — and linear to 6e-9 em over a 90× range of stroke ratio.

At a 0.105 mm stroke that x shift is 0.069 mm, **larger than the ±0.05 mm mask
registration tolerance the block opening exists to absorb**. A block opening
placed from the anchor rather than from the letterforms therefore spends the
entire registration budget before the fab has done anything. `stroke_font.py`
corrects for it and `verify_art.py` now uses the same measured extents instead
of its old 0.75 em-per-character estimate.

## Cost

Negligible, and worth contrasting with hatching. `fp_text` uses KiCad's built-in
stroke font, so a whole string is one object: **468 bytes for two complete
strings**, measured. Glyph outlines as `fp_poly` would be orders of magnitude
worse. Text stays text.

---

# T8 — the translucent window

Yes: strip mask from **both** faces and keep copper off **all four** layers, and
the remaining laminate passes light. This is a real eighth tone, but it behaves
unlike the other seven and deserves its own rules.

## The light path

```
F.Mask   removed
F.Cu     absent
prepreg  0.10 mm
In1.Cu   absent
core     1.24 mm      <- 1.44 mm of FR4 total
In2.Cu   absent
prepreg  0.10 mm
B.Cu     absent
B.Mask   removed
```

**Diffuse, not clear.** FR4 is woven glass in epoxy: it scatters heavily and
carries a yellow-green tint. At 1.44 mm expect frosted glass — a glow, not a
view. You will see light *through* it, never shapes.

**Mask must come off both faces.** Soldermask is largely opaque and black mask
especially so. Mask remaining on either side kills the effect.

## Yes, inner copper can be excluded

Copper exists only where it is drawn, so "removing" it is really "never putting
it there". The mechanism is a **keepout / rule area on every copper layer**.

This matters more than it sounds, because the recommendation for
`SatoshiStarter#3` is to make **In1.Cu a full ground plane**. Once In1 is a
pour, it floods any window unless a keepout excludes it. So a translucent window
is not the absence of drawing — it is four deliberate keepouts plus two mask
openings.

**The mechanism is already proven on this board.** Satoshi Starter carries three
working keepouts inside the inductor footprint, with `copperpour not_allowed`,
`tracks not_allowed`, `vias not_allowed`. Nothing new is required.

### The keepout has to be on the BOARD, not in the footprint

Measured against KiCad 10.0.0: a copper keepout **carried by a footprint is
silently ignored by the zone filler**. Not an error, not a warning — the plotted
copper gerber comes back byte-identical to the same board with no keepout at
all. Board-level rule areas work as documented; footprint-level ones do not.

This is the constraint that shapes the whole tone. A T8 window **cannot be a
self-contained part**. A footprint can carry its own two mask openings, and
that is all; the four copper exclusions have to be drawn on the board that
places it, or the In1 pour floods the window and it never lights.

`tools/emit_art.py --window-tone` therefore emits the mask apertures on F.Mask
and B.Mask, marks the outline to trace on `Dwgs.User`, and says so on every run.
The `Dwgs.User` outline is documentation, not fabrication: nothing on it becomes
copper, mask or a keepout by itself.

## Why this tone is different

**It needs six aligned layer operations** — four copper exclusions and two mask
openings — so registration tolerance stacks across the whole stackup. **Bold
shapes only.** No linework, no detail, no small features.

**It only reads when lit.** Unlit, a T8 window is simply bare laminate — tan,
close to T3. The tone exists only with a light source behind or at the edge.

- **Backlit:** needs an LED on the reverse. The five existing LEDs are all
  front-side through-hole, so this means adding one.
- **Edge-lit:** FR4 is a mediocre light guide but works over short spans. Inject
  at the board edge, scatter at the window.

There is an obvious product idea here: this is a **miner**. An activity LED
behind a translucent Satoshi window would glow as the board hashes — literal
visible proof of work, on a board built to teach exactly that.

## Mechanical notes

- A copper-free window costs some stiffness. Fine at art scale; think twice at
  structural scale or near mounting holes.
- **Warpage is not a concern here.** Asymmetric copper warps boards; a void that
  is absent on *all* layers is symmetric and behaves well.
- Large bare-laminate exposure is unusual enough that some fabs query it or
  surcharge. Confirm before committing a design to it.

## Verification gap

`pcbnew.ZONE_FILLER.Fill()` **segfaults (exit 139)** with a keepout-bearing
footprint on the board, so there is no automated way to confirm a keepout
actually knocks its hole in a filled pour. The GUI plainly works — this board
fills with three keepouts present — so the mechanism is sound and only the
*automated* check is unavailable.

> Read that alongside the finding above: the case that segfaults the scripted
> filler is the *footprint*-borne keepout, which is also the case that produces
> no hole even when the filler survives. The keepout that matters — the
> board-level rule area — fills and plots normally, and the emitter never asks
> for the other kind.

Same disposition as buried-copper void mode: **ship it, gate it behind a flag,
and verify by opening the board once in the GUI and exporting the gerbers.**
Five minutes, and it cannot be replaced by more automation.

---

# T9 — cuts

Board outline and internal cutouts are art. Unlike T8, a cut is the **absence of
board**, so it shows whatever is behind it — desk, enclosure, a backlight, or
another board in a stack.

## Two forms

**Outline.** `Edge.Cuts` need not be rectangular. A pendant, a badge, a
silhouette — the whole board becomes the shape.

**Internal cutouts.** Windows and slots routed clean through. Combine with T8 in
an adjacent region and you get a lit window beside an open one.

## Router constraints — the ones that bite

Cuts are made with a rotating bit, not a beam, and that governs everything:

| constraint | typical value | consequence |
|---|---|---|
| standard bit diameter | 1.6–2.0 mm | |
| **minimum internal radius** | **= bit radius, 0.8–1.0 mm** | **sharp internal corners are impossible** |
| smaller bit available | 1.0 mm dia → 0.5 mm radius | at extra cost, ask first |
| minimum slot width | ≈ bit diameter | a 0.5 mm slot cannot be routed |
| external corners | sharp is fine | the bit cuts *around* them |

**Internal corners are always filleted to the bit radius.** Design them that way
or the fab will do it for you, badly. This is the most common surprise: art that
looks crisp in KiCad comes back with 1 mm rounded inside corners.

**Fine detail is not cuttable.** The interlocking pattern on the reference
pendant is entirely ENIG-on-black, not cuts — the only cuts are the triangular
outline and three mounting holes. That is the right division of labour: **cuts
for silhouette, copper and mask for detail.**

**Webs need width.** Material left between two cuts must not snap in
depanelisation or handling. Treat ~1.5 mm as a floor for anything handled, more
for a kit a student will flex.

## Cost and process notes

Complex outlines increase routing time and cost; internal cutouts more so.
V-scoring is cheaper but only cuts straight lines edge to edge, so it is
unusable for art. Panelisation tabs and mouse-bites leave witness marks on the
outline — place them where the art can absorb them.

## In the emitter

`tools/emit_art.py --cut-tone TONE` turns that tone's regions into `Edge.Cuts`
loops, and fillets the inside corners to `--cut-fillet-mm` (default 0.8) rather
than leaving them for the fab to round without telling anyone. Outside corners
are left sharp, because the bit cuts around those.

Two things it will refuse or shout about, both of which have already bitten a
hand-built part in `library/`:

- **A footprint cutout is unconditional.** Footprint `Edge.Cuts` merges into the
  same gerber layer as the board outline, so every board that places the
  footprint gets the hole. There is no per-instance switch.
- **Copper must be on the KEEP side.** `copper_edge_clearance` is a distance
  rule and is indifferent to side, so copper printed on the slug clears the
  rule, passes DRC, and is routed away with the waste. The emitter decides the
  side explicitly and fails rather than warns.

---

# Knockout: silk as background rather than foreground

Worth naming because it inverts the usual assumption, and the reference boards
use it constantly.

The SparkFun carrier's pin labels are **white silk rectangles with the text
knocked out** — the dark letters are bare mask showing through gaps in the ink,
not dark ink.

Two consequences:

**It is another way to get "dark on light"** without a second ink colour. Any
tone can host any other as a knockout, subject only to minimum feature on the
*gap* rather than on the mark.

**Minimum feature applies to the hole, not the shape.** A 0.15 mm silk gap is at
least as hard to hold as a 0.15 mm silk line — ink bleeds inward and can close a
fine gap. Knockout text needs *more* margin than positive text, not less.

For the tracer this means polygon-with-holes must be first-class, which the
chosen architecture already requires for letterforms like O and 8.

## In the emitter

`tools/emit_art.py --knockout MARK[:HOST]` (repeatable) stops drawing tone MARK
in its own layers; the gap it leaves in HOST *is* the mark. HOST defaults to
whichever drawing tone the mark mostly borders. Verified on a synthetic silk
field, `output/regionops/knockfield_*`: `--knockout T2:T1` takes 9 `fp_poly` down
to 1, suppresses T2's `F.Cu` + `F.Mask` entirely, and measures host adjacency at
100 %.

### "More margin than positive text" is now a number: 2×

`--knockout-floor-mult`, default **2.0**. This document states the direction and
gives no number, so it was derived rather than picked. Ink bleed *b* runs outward
from every inked edge. A positive mark of width *w* has ink inside both of its
edges and so images at *w* + 2*b* — fatter, but present. A gap has ink outside
both edges, images at *w* − 2*b*, and is **gone at w = 2b**. The positive floor
*F* is where a mark stops being reliable, which puts *b* ≈ *F*/2 — and for mask
*F*/2 = 0.05 mm is exactly the ±0.05 mm registration tolerance quoted above. So a
gap must be drawn at *F* + 2(*F*/2) = **2F**. Demonstrated on the same synthetic
field: a 0.200 mm silk gap passes the 0.15 mm positive floor and fails the
0.30 mm knockout floor.

Gap width is measured as the **largest inscribed circle** — not minimum width,
which condemns every acute corner, and not area, which waves through a long thin
slot. It is accurate to roughly ±4 % of the floor being tested and the direction
of the error is not guaranteed, so a gap within a few percent of the floor may be
called either way. The audit runs on **every hole in every tone**, flag or no
flag, because a hole *is* a knockout; `--no-gap-audit` and `--gap-audit-max`
bound it.

### The acceptance harness cannot see knockouts

`tools/verify_art.py` measures clearance *between* separate features. After
keyhole bridging, a knockout is a hole *inside* a single polygon, so there are no
pairs left to compare.

Measured, and it is the uncomfortable case: of the nine footprints in
`output/regionops/`, `knockfield_knockout.kicad_mod` is the **one that PASSES**
everything — min-feature and clearance both clean — and it is also the one
carrying **two silk gaps below the 0.30 mm knockout floor, the narrowest
0.094 mm across**. The emitter's own gap audit is currently the only thing that
catches those. Do not read a harness PASS as clearance on a knockout.

---

# Measured, not assumed

Findings from running the tools rather than reasoning about them, against the
installed **KiCad 10.0.0** (file format `20260206`) and the stackup at the top of
this file. Each one is a limit on what the emitter is allowed to promise, and
each is stated with the evidence that produced it. Dates and sessions are in
`docs/conversation_log.md`.

## A footprint cannot carry a copper keepout

A copper keepout carried by a **footprint is silently ignored by the KiCad 10
zone filler** — not an error, not a warning. The plotted copper gerber comes back
**byte-identical to the same board with no keepout at all**. Board-level rule
areas work as documented.

Stated in full under T8 above, because it is what stops a translucent window
being a self-contained part. It is also why `tools/texture_board.py` is
board-in / board-out and reasons in board coordinates throughout, rather than
generating a footprint.

## Buried tones cannot be previewed from a footprint

`kicad-cli fp export svg` **emits nothing at all for `In1.Cu`**. Found while
rendering the Tux comparison figures: the front layers plot, the buried layer
produces no output whatsoever, and the failure is silent. So **T4 and T7 cannot
be shown in any footprint-level SVG preview** — the composites in `docs/images/`
render T1/T2/T3/T5/T6 honestly and the two buried tones not at all. Noted rather
than worked around; confirming a buried tone means plotting it from a board, or
opening the footprint in the GUI.

## Arcs survive the round trip, and are 2.2–4× smaller

Arcs inside `fp_poly` round-trip to gerber as real **G02/G03** arc commands, and
for curved geometry they come out **2.2–4× smaller** than the RDP-simplified
polyline approximating the same curve.

This answers a question the April audit asked and could not settle — whether
`fp_poly` takes curves — in the affirmative, and all the way through to the film
rather than only into the file.

The emitter does **not** use them yet: `tools/emit_art.py` traces marching-squares
contours, simplifies with RDP, and writes straight segments only. So this is the
largest known unclaimed file-size win for curved art, recorded here rather than
left to be re-derived.

## KiCad does not snap, merge or heal abutting polygons

Two polygons on the same layer that share a boundary are left exactly as
written — **no snapping, no merging, no healing**. Exact coincidence gives a
**true zero gap**, and whatever the emitter writes is what reaches the film.

Two consequences the emitter now depends on. Adjacent tone regions can be made to
abut with neither seam nor overlap: `tools/verify_art.py` measures 19 `F.Cu` pairs
at a **0.000 mm** gap in `output/regionops/baseline.kicad_mod`, features touching
exactly rather than nearly. And symmetrically, a 0.01 mm sliver written by
accident is fabricated as a 0.01 mm sliver — nothing upstream will tidy it away.
It is why the halftone clip contours are deliberately **not** RDP-simplified:
adjacent duty levels share a marching-squares boundary exactly, and simplifying
each independently would open a 0 – 0.05 mm slot on every level boundary in the
picture.

## A region that maps to T5 loses its silhouette entirely

**T5 is the board.** It draws nothing, so a source region quantising to T5 cannot
be told from the background. Measured on Tux at default settings: **34.7 % of the
figure** — his whole body — has no edge at all. Colour data cannot recover the
boundary, since body and background are one contiguous tone; alpha can, which is
what `--silhouette-tone` uses.

Which tone the keyline goes in matters, and was measured on the green-mask renders
in `docs/images/`:

| render | tones | note |
|---|---|---|
| `tux_green_plain` | 3 — mask 59.9, silk 22.8, gold 17.2 | no keyline: the body has no edge |
| `tux_green_keyline_fr4` | 4 — mask 59.7, silk 21.3, gold 15.3, FR4 3.5 | **works** — a genuine fourth tone, tan against green |
| `tux_green_keyline_gold` | 3 — mask 59.6, silk 21.3, gold 18.8 | only grows the gold already there; beak and feet are T2 |

The first version of that keyline was specified in **pixels**, which was wrong:
it shrank as the art scaled up. It is millimetres now, so the keyline is the same
physical width at every output size, and the emitter warns rather than clamps when
the requested width is under the tone's own floor.

## The tone anchors are a BLACK-mask set

Every tone in this document, and every sRGB anchor the quantiser uses in
`tools/w0_spike.py`, describes the **black-mask / ENIG** stackup. A green set is
**uncalibrated**: the green-mask figures are a render-time colour choice, not a
measurement, so coverage percentages read off them describe geometry rather than
appearance. Tracked as issue **#1 — calibrate the palette: sample real tones from
a reference board**, which is also the issue that turns the black-mask anchors
themselves from estimates into measurements.

---

# Reference boards observed

| board | demonstrates |
|---|---|
| SparkFun MicroMod carrier | black mask + white silk; constellation linework; **silk knockout** labels; faint T6 traces under mask |
| Bolt Industries rulers | **same art, two finishes** — ENIG gold on black vs bare/OSP brown on white. Copper used as *linework*, not fill |
| Bitcoin pyramid pendant | **custom outline as art**; dense ENIG-on-black pattern; detail in copper, silhouette in cuts |
| Peer-to-Peer card *(not a PCB)* | target aesthetic: metallic on dark, embossed dark-on-dark background — the print analogue of T5/T6/T7 |
| Bitcoin sticker sheet *(not a PCB)* | **visible halftone** on the two photographic images — what dithering looks like at legible scale |

The Bolt pair is the most useful single reference: identical artwork, two
finishes, showing directly that the metal tone is **brown on bare/OSP and gold
on ENIG**. That is the T2 finish-dependence documented above, in physical form,
and it argues for the palette file carrying a finish parameter rather than
hard-coding gold.
