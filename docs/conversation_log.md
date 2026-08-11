# Conversation Log

Running record of work on this repo: what was done, **why**, the evidence
behind it, and what turned out to be wrong.

All timestamps are **UTC**. Note that git author dates render in local time
(PDT, UTC−7), so a commit may show the previous calendar day.

## Model provenance

Which model produced which functionality, so that when a new frontier model
lands it is obvious which parts of this codebase are most likely to benefit
from a fresh pass. Older code is not automatically worse — but code written
against an older model's ceiling, and against an older KiCad, is where the
easy wins concentrate.

| area | commits | date | model |
|---|---|---|---|
| core scaffolding, CLI, single/dual-colour modes | `ff41777`, `21fb87e`, `648c7a3` | 2026-04-05 | *unrecorded* — believed GPT-5.4-class |
| parametric sizing, presets, library export | `ffaad28`, `6bc20b4`, `e621e91` | 2026-04-05 | *unrecorded* — believed GPT-5.4-class |
| colour matching, palette analysis, library bundles | `dba0ae3`, `08bd232`, `06218be` | 2026-04-05/06 | *unrecorded* — believed GPT-5.4-class |
| **SVG colour mapping** ← complaint 1 | `9c03675`, `6fad3b4` | 2026-04-06 | *unrecorded* — believed GPT-5.4-class |
| quality presets, SVG previews | `2980f3f`, `e22b979` | 2026-04-06/09 | *unrecorded* — believed GPT-5.4-class |
| **potrace vectorisation, compact vector mode** ← complaint 2 | `9a57b52`, `cc7b2d8` | 2026-04-09/12 | *unrecorded* — believed GPT-5.4-class |
| audit + redesign: orchestration, judgement | `2f01cb1`, `ba81f22`, this entry | 2026-08-11 | **Claude Opus 5** |
| audit + redesign: survey probes, design proposals | (pending) | 2026-08-11 | **Claude Fable 5** |

The April attribution is **not recorded in the repository**. What the history
actually contains, checked rather than assumed:

- All 16 April commits are authored by the owner's own account. None carries a
  trailer, and no commit body anywhere in the April range mentions a model.
- The only `Claude` strings in the entire history are the `Co-Authored-By`
  lines on the August audit commits. Seeing those and inferring that Claude
  wrote the tool is a trap — they post-date the code by four months.

One weak forensic signal does survive. The April commits use the GitHub
noreply address `125509978+recklessnode@users.noreply.github.com`, whereas the
August ones use the local git identity `ronald@bynoe.us`. That means the April
work was committed **through GitHub's API** rather than by local git — a
web/API-driven agent rather than a CLI one. It does not name the model, but it
narrows the class, and it is the only evidence the repository itself holds.

So the attribution rests on the owner's recollection ("I think by like GPT-5.4
or something") and should be treated as approximate. This is precisely the gap
the convention below exists to close.

**Convention going forward.** Every commit carries a `Models:` trailer naming
each model and what it did, so provenance survives without depending on anyone
remembering. Greppable with `git log --grep='Models:'`.

```
Models: Opus 5 (orchestration, judgement); Fable 5 (survey, design proposals)
```

---

## 2026-04-05 to 2026-04-12 — Initial build

Model: *unrecorded*, believed GPT-5.4-class. KiCad version of the day, not 10.x.

- Bootstrapped the repository and built out the core KiCad art generation workflows.
- Added single-color, dual-color, multi-color, preview, analysis, and library export modes.
- Added named PCB art presets for silkscreen, exposed copper, covered copper, exposed substrate, and user drawings.
- Added parametric sizing, richer help examples, and public release packaging.
- Improved SVG handling, including better source-color preservation and preview generation.
- Added `potrace`-based bitmap vectorization and a compact all-vector option.

---

## 2026-08-11 06:31 UTC — Audit and redesign kicked off

**Models:** Opus 5 (orchestration); Fable 5 (survey, design).

### Why now

This tool was written in April 2026 (16 commits, `2cc2880` latest) against a
much older KiCad and by a much older model. It is about to matter: the Satoshi
Starter board is nearing the end of its electrical work and art integration is
tracked there as `Blockscale-Solutions/SatoshiStarter#27` (floorplan + art-zone
contract) and `#30` (art integration + art-copper DRC). Before art assets get
made, the tool that makes them needs to be trustworthy.

### The complaints, as stated by the owner

1. **Colour conversion to the PCB palette is poor** — worse than converting by
   hand. The achievable "colours" on a board are a small discrete set
   (silkscreen, copper trace, bare substrate, mask-removed copper, and buried
   inner-layer copper), and the mapping onto them is not good.
2. **PNG conversion produces very large footprint files.**
3. **Output size is fixed**, believed at the time to be a KiCad limitation.

Complaint 3 is the interesting one, because it is a claim about KiCad rather
than about this code, and KiCad has moved from whatever version was current in
April to 10.0.5. That assumption is now worth testing rather than inheriting.

### Verified before starting

- `src/kicad_art_generator/cli.py` is **1,875 lines**; `tests/test_cli.py` is
  18.5 KB.
- `potrace` vectorisation exists (`9a57b52`) and a "compact vector mode"
  (`cc7b2d8`) — so some of the file-size problem may already be partly
  addressed, and the audit has to establish what is actually in use.
- **There is no art library.** The repo carries exactly one asset,
  `examples/bitcoin_b.svg`, 614 bytes. The owner thought test art footprints
  might be in the repo; they are not, on any branch. Nothing art-related exists
  on the SatoshiStarter `draft` branch either — checked the full tree.

### Approach

An eight-agent workflow, audit and design **only**. Implementation is
deliberately held back to a second pass so the direction is agreed before
anything lands in a public repo.

**Survey — 4 parallel (Fable 5), each required to run things rather than read them:**

| probe | question |
|---|---|
| code | how colour mapping actually works, and measured byte/primitive counts from a real generation run |
| kicad10 | which `fp_*` primitives KiCad 10.0.0 supports, whether `fp_poly` takes curves, whether `kicad-cli` gained image import, whether "fixed size" is still a real constraint |
| palette | the achievable tone set and the right quantisation approach |
| geometry | contour-trace + simplify vs potrace vs rectangles, with a prototype run for real vertex counts and file sizes |

**Design — 3 parallel (Fable 5), deliberately opposed angles** (minimal-change,
clean rebuild, fabrication-first) so they do not converge prematurely.

**Judge — 1 (Opus 5, high effort).** Required to name where the surveys and
proposals *contradicted each other* rather than smoothing it over.

### Two constraints written into every agent brief

**Do not assert a KiCad capability without verifying it against the installed
10.0.5.** Guessing at file-format support is the cheapest way to be confidently
wrong and would waste an entire implementation cycle. This is the direct lesson
from the same day's SatoshiStarter audit, where a `connect_pads thru_hole_only`
misreading produced a published finding that had to be retracted — the syntax
was verified, the semantics were not.

**Fabrication limits drive the tolerances, not aesthetics.** Silkscreen minimum
feature is around 0.15 mm and mask/copper around 0.1 mm. Geometry finer than
the board house can produce is wasted vertices, which is plausibly a large part
of complaint 2.

### Known downstream constraint

The SatoshiStarter repo now gates pushes on `tools/pcb_rules.py`
(`.github/workflows/pcb-checks.yml`). Art placed on `F.Cu` is real copper and
will trip DRC clearance and unconnected-island checks, and rule `R3` would read
an art-only layer as carrying zero track segments.

The fix belongs here, not there: **art footprints should be designed to be
excludable by construction** — a naming convention or a dedicated group the
rules can skip — rather than the board repo accumulating exclusions after the
fact. Folded into the implementation brief as a design input.

---

## 2026-08-11 06:45 UTC — Correction: buried inner-layer copper is a real tone

**Models:** Opus 5 (correction, orchestration).

The brief written for the palette survey said of buried traces: *"Assess
whether inner-layer copper is actually visible through FR4 ... Be honest if
this is marginal."* That framing was wrong, and the owner corrected it with a
physical sample.

**Evidence.** A photograph of a finished board: black soldermask, ENIG gold
exposed copper, white silkscreen — and a dark field carrying clearly legible
art rendered *entirely as tonal shifts within the black*. Concentric rings,
chevron bands and grid hatching are all readable. Multiple distinct dark tones
are present; it is not one flat black with gold on top.

**Why it works, and it is not marginal.** The governing variable is prepreg
thickness, not FR4 translucency in general. The Satoshi Starter stackup is
`0.035 Cu / 0.1 prepreg / 1.24 core / 0.1 prepreg / 0.035 Cu`, so **In1.Cu sits
roughly 0.1 mm beneath the surface copper** — thin enough to shadow through a
dark mask. On a board with a thick outer prepreg the effect would be much
weaker. So this is a stackup-dependent capability we happen to have, rather
than a universal property.

That also means three mechanisms produce "dark", and they are different tones
that a quantiser should treat separately:

- outer-layer copper under mask
- inner-layer copper shadowing through prepreg + mask
- bare substrate under mask

**Consequence for the redesign.** The achievable palette is materially larger
than the eight front-side copper/mask/silk combinations originally assumed.
Inner layers participate, which means the tool is not choosing among ~5 tones
but something closer to a two-dimensional space of surface state × buried
state.

The practical limit is edge sharpness rather than availability: a buried tone
is a diffuse shadow through 0.1 mm of dielectric, so its edges blur relative to
a silkscreen or copper edge. Minimum feature size for a buried tone is
therefore larger than for the surface layers, and that constraint — not
whether the tone exists — is what should bound its use.

**Process note.** Caught while the workflow was still in its survey phase,
before any design proposal or the Opus 5 judgement had started. Stopped the
run, rewrote the palette brief to treat buried tones as settled and to
characterise rather than assess them, and resumed — the three unaffected survey
agents cache on their unchanged prompts, so only the palette probe re-ran.

Had it landed later, a wrong "buried traces are marginal" premise would have
propagated through three design proposals and the synthesis. Worth recording as
the general point: **an assumption embedded in a brief is more expensive than
an assumption embedded in code**, because every downstream agent inherits it
without re-deriving it.

---

## 2026-08-11 07:10 UTC — Real output samples: both complaints diagnosed precisely

**Models:** Opus 5 (analysis).

The owner supplied a directory of local test output — ten `.kicad_mod` files and
four preview PNGs, outside the repo and deliberately not committed. This is far
better evidence than anything synthesised, and it turns both complaints from
impressions into measurements.

### Complaint 2 (huge files): every raster polygon is one source pixel

| file | bytes | fp_poly | vertices | verts/poly |
|---|---|---|---|---|
| `bitcoin_b` | 8,443 | 3 | 171 | **57.0** |
| `two_color_demo_1in` | 868 | 2 | 10 | 5.0 |
| `cholla_energy_enig_v2` | 425,442 | 1,356 | 6,780 | 5.0 |
| `reckless_svg_multicolor` | 645,610 | 2,610 | 13,050 | 5.0 |
| `cholla_cactus_bundle` | 833,845 | 2,565 | 12,825 | 5.0 |
| `reckless_svg_multicolor_hq` | **2,522,310** | 9,455 | 47,275 | 5.0 |

**Exactly 5.0 vertices per polygon** across every raster-derived file — four
corners plus the closing repeat, i.e. an axis-aligned rectangle. The first
polygon in the 2.5 MB file is:

```
(xy -0.029296875 -27.5390625) (xy -0.029296875 -27.509765625)
(xy  0.029296875 -27.509765625) (xy  0.029296875 -27.5390625)
```

That is **0.0586 × 0.0293 mm** — a single source pixel. Silkscreen minimum
feature is around 0.15 mm, so this geometry is roughly **2.5× finer than any
board house can print**. The tool is spending 2.5 MB storing detail that
physically cannot be fabricated.

The `hq` preset makes this worse rather than better: 9,455 rectangles against
2,610 for the same logo. Quality presets scale *rectangle count*, not trace
fidelity.

### The good path already exists in this codebase

`bitcoin_b.kicad_mod` is **3 polygons, 57 vertices each, 8.4 KB** — genuine
traced contours. So single/dual-colour SVG handling vectorises correctly.

The bug is narrower than "the tool is bad": **multi-colour mode rasterises even
vector input.** `reckless_svg_multicolor` came from an SVG and still produced
2,610 rectangles. The vector information is discarded on the way in.

### Complaint 1 (bad colour conversion): source-dependent, not uniform

Comparing the two previews:

- `cholla_energy_enig_v2` renders **well** — the flower keeps its petal detail,
  the wordmark is clean. Flat, high-contrast, few colours.
- `reckless_svg_multicolor_hq` loses **most of the artwork**. Only the white
  hexagon outline and a handful of disconnected gold fragments survive; the
  interior is empty.

So the classifier copes with simple flat art and collapses on anything with
gradients, thin strokes or close shades — dropping content wholesale rather
than mis-assigning it. That is exactly the shape of "worse than we could do by
hand": a human has no trouble with the harder case.

Note this is *not* a layer-model problem. The multi-colour output does use all
three layers — `F.SilkS` 4,725, `F.Cu` 2,367, `F.Mask` 2,366. The tone model is
sound; the per-pixel classification feeding it is not.

### Output is in pre-KiCad-6 format

```
generated:  (module reckless_svg_multicolor_hq (layer F.Cu) (tedit 0FC7F88C)
KiCad 10:   (footprint "PG-TSDSON-8"
```

`(module ...)` was replaced by `(footprint ...)` in **KiCad 6, released 2021**.
KiCad 10 still reads the legacy form, so this has never failed loudly — but it
means the tool's model of KiCad predates the current format by five years.
Direct support for complaint 3 being an inherited assumption rather than a
present-day constraint.

### Target assets for the Satoshi Starter

Named by the owner: the **Reckless Systems logo**, the **emission rate**, the
**"Bitcoin B" logo**, and the **"Satoshi" character** from My First Bitcoin.
These become the acceptance set — a redesign has to render all four
convincingly, and the Reckless logo specifically is the one that currently
fails, so it is the regression test that matters.

Note the supplied directory contains outputs and previews only; the **source
art is not in it**, and will be needed before the acceptance set can be run.

---

## 2026-08-11 07:25 UTC — Requirement: one growing `RecklessArt` library, not loose files

**Models:** Opus 5 (analysis).

### The deliverable shape

The tool currently emits standalone `.kicad_mod` files. The owner's actual
requirement is **a single `RecklessArt` library that accumulates parts over
time**, registered once, so placing art on any board is *Add Footprint →
RecklessArt → pick*. Minimum effort at placement time is the design goal, not
minimum effort at generation time.

Concretely that means:

- Output target is `RecklessArt.pretty/`, one `.kicad_mod` per art element —
  not a directory of one-off files per invocation.
- **Registered globally**, not per project, so every board gets it without
  per-project setup. That is what makes it one-time rather than per-board work.
- **Idempotent regeneration**: re-running a part replaces it in place rather
  than accumulating `_v2`, `_hq`, `_final` variants. The existing local output
  directory — which contains `cholla_cactus_bundle`, `cholla_cactus_silks` and
  `cholla_cactus_library_test`, all near-identical at 822-834 KB — is what
  happens without this.
- Art parts already carry `(attr board_only exclude_from_pos_files
  exclude_from_bom)` and `(tags kicad_art_generator)`. Both are correct and
  should be kept.

### This also solves the DRC-exclusion problem cleanly

Earlier entry noted that art on `F.Cu` is real copper and will trip the
SatoshiStarter CI rules. With a library, **membership is the exclusion
mechanism** — `tools/pcb_rules.py` skips footprints whose library is
`RecklessArt`, and the board's DRC gets a rule area or exclusion keyed the same
way. No naming-convention hack, no per-part maintenance, and it cannot drift
because a part is either in the art library or it is not.

### Source assets located

`.../1-ASIC Satoshi Starter/Art Assets/`:

| asset | formats | note |
|---|---|---|
| Bitcoin Emission Formula | **`.svg`** (18 KB), `.mml`, `.odf`, 3× `.png` | authored as a LibreOffice Math formula — crisp line art, and the **only asset with a vector source** |
| Little Satoshi | `.png` | |
| Satoshi Miner (+ transparent) | `.png` | |
| Satoshi Points | `.png` | |

**Missing from both directories: the Reckless Systems logo source and the
Bitcoin B source.** The Reckless logo exists only as generated output
(`reckless_svg_multicolor*`), and `examples/bitcoin_b.svg` in this repo is a
614-byte placeholder rather than the real mark. Both are needed before the
acceptance set can run.

### Difficulty assessment of the assets

The Satoshi character is a **far better PCB candidate than the Reckless logo**:
flat-shaded cartoon with heavy consistent black outlines and roughly five
tones — black line, dark gold body, light yellow helmet, white eyes, orange
shading. That is structurally the Cholla case, which the current tool already
handles well, not the Reckless case which it fails.

Worth noting for the palette work: the character's body is *literally a gold
coin*, which maps directly onto ENIG exposed copper, and the black outlines map
onto bare black soldermask. On the black-mask/ENIG stackup the owner is already
using, this asset is close to purpose-built. The mapping should be
*controllable* rather than inferred — the tool should let a human assign source
tone → PCB layer when the automatic choice is wrong, which is the practical
answer to "we could do better by hand".

The emission formula, being line art with an SVG source, should go through the
vector path that already works (`bitcoin_b`: 3 polygons, 57 vertices each,
8.4 KB) and should never touch the rasteriser.

---

## 2026-08-11 07:40 UTC — Root cause of the Reckless logo failure: it is a parsing bug

**Models:** Opus 5 (analysis).

Located the real source: `.../Business Docs/Logo-Library/Logo-Library/Color/`,
which holds Black / Color / White variants as `.svg`, `.eps` and Affinity
`.afdesign` originals. `RecklessSystemsLogoColor.svg` is 19 KB.

The SVG is **ideal input**: 28 paths, 9 groups, viewBox `0 0 720 720`, **zero
gradients, zero embedded images**. Clean flat vector line art. There is no
excuse for it converting badly, which makes the failure diagnostic rather than
inherent.

### What the source actually contains

```
28 paths total
17 with an explicit fill  (of which 1 is fill:none)
11 with NO fill           <- inherit; SVG default is black
```

Explicit fills, in full:

| colour | uses |
|---|---|
| `rgb(1,190,219)` cyan | 8 |
| `rgb(20,191,219)` cyan | 2 |
| `rgb(240,81,54)` orange-red | 1 |
| `none` | 1 |

### Three defects, compounding

**1. The preset asks the wrong question.** Dual-colour mode maps *yellow →
copper, white → silkscreen*. **This logo contains no yellow and no white** — it
is cyan, orange-red, and black. So the matcher finds almost nothing and
discards the rest. That is precisely the observed preview: an empty hexagon
with a few disconnected fragments.

The tool asks *"which pixels are yellow or white?"* when the right question is
*"what are the N dominant tones here, and where should each map?"*

**2. Inherited fills are invisible.** Eleven of 28 paths declare no fill and
inherit SVG's default black. Any extractor scanning for explicit `fill:`
declarations misses **39% of the artwork** before classification even starts.

**3. Near-duplicate colours are treated as distinct.** `rgb(1,190,219)` and
`rgb(20,191,219)` differ by (19,1,0) — visually identical cyan, numerically two
colours. The repo already carries a `--adjacent-color-tolerance` flag, which
reads as a workaround bolted on after hitting exactly this, rather than a fix
for the underlying model. Perceptual clustering in CIELAB makes the flag
unnecessary.

### The full chain, for the record

```
SVG (28 clean paths)
  -> preset looks for yellow/white   .. logo has neither
  -> extractor sees explicit fills only .. 11 paths invisible
  -> two identical cyans counted separately
  -> multi-colour mode RASTERISES the vector source anyway
  -> survivors emitted one rectangle per pixel  -> 2.5 MB
```

Every stage is lossy, and the last two are wholly unnecessary for vector input.
**Complaints 1 and 2 are the same bug seen from two ends.**

The fix is correspondingly narrower than a rewrite: resolve inherited fills,
cluster tones perceptually rather than matching named colours, let the operator
assign tone → layer, and keep vector input on the vector path.

### Licensing note for the public release

The Bitcoin "B" came from Wikipedia. The Bitcoin logo is public domain, so it
carries cleanly into a CERN-OHL-S release (`SatoshiStarter#13`). The Reckless
Systems mark is the owner's own. The MFB Satoshi character is third-party and
its usage terms should be confirmed before it ships on a public board.

---

## 2026-08-11 07:55 UTC — Correction, and the variant set is a controlled experiment

**Models:** Opus 5 (analysis).

### Correcting the previous entry

The previous entry claimed `RecklessSystemsLogoColor.svg` had "17 with fill, 11
without → 39% invisible". **Wrong.** The check tested whether the substring
`fill` appeared in the path element, which also matches `fill-rule` — inflating
the count.

Measured properly, distinguishing `style="fill:…"` from `fill="…"`:

```
28 paths | 12 CSS fill | 0 attribute fill | 16 with neither
```

So **16 of 28 paths (57%) inherit**, not 39%. The defect is worse than
reported. Also worth noting: the logos use the CSS `style="fill:…"` form
exclusively and never the `fill="…"` attribute form — an extractor handling
only one syntax would fail differently on other artwork.

That error is the same class as the tool's own: matching a colour by pattern
without resolving what the SVG actually means. Recorded rather than quietly
fixed, because the point of this log is the mistakes.

### The variant set is a near-perfect test matrix

The owner has single-colour logos parallel to the colour one. Both should go
into `RecklessArt` — but the pair is more valuable than two deliverables,
because it isolates the inheritance defect exactly:

| variant | paths | explicit fill | inherited | what it tests |
|---|---|---|---|---|
| `Black` | 17 | **0** | **17 (100%)** | pure inheritance — renders nothing if resolution is broken |
| `White` | 17 | 17 | 0 | same 17 paths, all explicit — the control |
| `Color` | 28 | 12 | 16 (57%) | mixed, multi-tone — the reported failure |
| `WhiteColor` | 28 | **28** | 0 | same 28 paths, all explicit — the multi-tone control |

Two clean A/B pairs on identical artwork:

- **Black vs White** — 17 paths each, 100% inherited vs 0%. Single tone, so
  classification is not a factor. Any difference in output is *purely*
  inheritance resolution.
- **Color vs WhiteColor** — 28 paths each, 57% inherited vs 0%. Same test at
  multi-tone.

If a redesign renders all four faithfully, both the inheritance bug and the
classifier are demonstrably fixed. If `WhiteColor` works and `Color` does not,
the fault is isolated to inheritance alone. This is a better acceptance test
than anything that could have been constructed deliberately, and it exists
because the brand library happens to ship the same mark four ways.

### Practical note for the library

The single-colour variants are also the **easy win**: one tone, one layer, and
they should go through the vector path that already works — the `bitcoin_b`
result (3 polygons, 57 vertices each, 8.4 KB) is the benchmark. A single-colour
Reckless mark on silkscreen ought to land in that size class. If it does not,
the geometry path is broken independently of the classifier, which is worth
knowing before any colour work starts.

So the sequence is: single-colour first as a geometry check, then colour.

---

## 2026-08-11 08:10 UTC — Palette specified: `docs/pcb-palette.md`

**Models:** Opus 5 (analysis, spec).

Wrote the palette up as a standalone reference rather than a log entry, since
it is the target the quantiser maps onto and will be consulted repeatedly.

**Seven tones**, from four binary controls per side (`F.SilkS`, `F.Mask`
negative, `F.Cu`, `In1.Cu`). Not sixteen combinations — two constraints collapse
the space:

- **Silk requires mask beneath it.** Fabs strip ink off a mask opening; KiCad
  names the rule *"Silkscreen clipped by solder mask"* and this board trips it
  121 times. So silk and mask-opening are mutually exclusive.
- **Outer copper occludes buried copper**, so `In1.Cu` only matters where there
  is no `F.Cu`.

That turns the mapping into a decision tree rather than a lookup, which is a
simpler thing to implement correctly:

```
silk? -> T1. mask open? -> copper ? T2 : buried ? T4 : T3
                        -> copper ? T6 : buried ? T7 : T5
```

Two findings from writing it that matter for implementation:

**`In2.Cu` contributes nothing to the front.** It sits ~1.375 mm back through
the core. `In1` shades the front, `In2` shades the back — the sides are
symmetric and independent. Earlier entries loosely said "inner layers
participate"; it is specifically `In1` for front-side art.

**T5 is the absence of all geometry.** The background tone requires drawing
nothing. So the quantiser should pick the most common source tone as background
and emit no polygons for it — correct behaviour *and* the largest single
file-size saving available, on top of the vector fix.

Also recorded: buried tones blur (shadows through 0.1 mm of dielectric, so
fields not linework), and any tone boundary defined by mask-over-copper stacks
two tolerances at ±0.05 mm registration — so oversize copper relative to the
mask opening and let registration error move the edge *within* copper.

The sRGB values are deliberately left unpopulated. They are vendor- and
finish-dependent and no theoretical table should be trusted for matching. We
have a physical reference board; the right way to fill them in is to photograph
it under diffuse light against a colour card and sample. Until then the
appearance column is ordinal, not colorimetric.

---

## 2026-08-11 08:50 UTC — Audit complete. Decision: rebuild, fabrication-first

**Models:** Fable 5 (4 survey probes, 3 design proposals); Opus 5 (orchestration,
judgement). 8 agents, 0 errors, ~741 k subagent tokens.

### Correction first: KiCad here is 10.0.0, not 10.0.5

`kicad-cli version` → **10.0.0** (format `20260206`). I briefed every agent with
10.0.5 and wrote it into earlier entries; both surveys and the judge caught it
independently. Corrected throughout above.

Note the CI gate in `SatoshiStarter` pins the container `kicad/kicad:10.0.5-full`,
so **CI runs a newer KiCad than this workstation**. Their ERC/DRC counts agreed
exactly (3 / 209 / 5) so they are behaviourally equivalent today, but that is an
observation, not a guarantee. The format version `20260206` is the invariant that
actually matters.

### Verdict: fabrication-first rebuild

The three proposals converged ~85% — all invert the data model to
tone → layer-mask → **one trace per physical layer**, all lift a validated
crack-trace/Douglas-Peucker prototype, all emit modern s-expressions, all delete
potrace / svg2mod / rsvg-convert. The fabrication-first proposal won on the
remainder: it organises around **per-tone absolute minimum feature in mm**, which
forces morphological legalisation as a first-class stage, registration
compensation as set operations between layers, and **size-aware tone collapse** —
the honest answer to complaint 3, since a 12 mm badge and a 50 mm badge are
different fabrication problems and should get different tone sets rather than the
same geometry scaled.

### New defects the audit found that we had not

- **Dimensional bug.** A requested 20 mm width emits **26.67 mm** and **13.35 mm**
  in different modes. 26.67 = 20 × 96/72 — a pt/px unit confusion. Part of
  complaint 3 is not "KiCad forces fixed sizes"; it is that the sizes are simply
  wrong.
- **65.4% of pixels dropped** on a gradient fixture (74,504 of 113,953); 2,695
  boundary pixels dropped even on the clean bitcoin logo.
- **Tonal inversion.** Navy `(16,24,64)` renders as white silkscreen, L\* ≈ 97,
  across 63,772 pixels. Not merely mismapped — inverted.
- **Dual-colour emits every shape twice** — 1,339 `fp_poly` on `F.Cu` plus 1,338
  on `F.Mask` for the same art. A 2× on top of the trace problem.
- **Non-deterministic output**: random `tedit`, so golden tests are impossible.

### Two hard tooling constraints, both verified here

**`kicad-cli` exits 0 on failure.** Reproduced directly: with a non-existent
output directory, `fp export svg` prints `Failed to create file` *and* `Done.`
and returns **0**. Any tooling that checks `$?` gets a false green.

**`--layers` silently breaks on inner layers.** Measured:

| `--layers` | exit | bytes |
|---|---|---|
| `In1.Cu` | 0 | **0** |
| `F.SilkS` | 0 | 930 |
| `In1.Cu,F.SilkS` | 0 | **0** |
| *(omitted)* | 0 | 1106 — renders **both** |

So one bad layer name poisons the whole list, and the failure is silent. But
In1 art renders fine with no filter. The smoke-test rule is therefore: **never
pass `--layers`, and assert the output file exists rather than trusting the exit
code.**

### Deliberately not shipping in v1

- **In1 "void"/keepout mode.** `pcbnew.ZONE_FILLER.Fill()` **segfaults (exit 139,
  2/2)** with a keepout-bearing footprint on the board, and fills cleanly without
  it. So there is no automated way to verify a knockout in a filled pour, and it
  cannot carry a CI gate. Ship **island mode only** (`fp_poly` on `In1.Cu`,
  verified to reach the gerber as a real region), behind `--enable-buried`.
  Unblocked by a five-minute manual GUI check, not by more automation.
- **Dithering.** Correctness depends on physical dot-pitch legibility we have no
  measurement for.

### Environment facts that shape the build

KiCad's bundled Python 3.11.5 has **PIL 12.1.1 and numpy 2.4.2**; **scipy,
skimage, cv2, svgelements and cairosvg are all absent.** Morphology must
therefore be hand-rolled and separable — measured `MaxFilter(21)` on an 1800²
mask is **8.18 s**, so naive open+close across 7 tones × 3 sizes is minutes.

### Next step is a go/no-go, not code

W0 is a half-day spike: quantiser + compositor only, no emitter, run on the real
sources, producing side-by-side renders against the current previews with ring
count, coverage and mean ΔE. **Ronald looks at it and says yes or no before
anything else is written.** That is the right gate — every downstream estimate
depends on the quantiser actually being better, and that is a judgement only he
can make.

---

## 2026-08-11 09:15 UTC — Hatching / stippling assessed and specified

**Models:** Opus 5 (analysis, verification).

Question raised: can line-width variation or stippling produce shading between
the seven discrete tones? **Yes**, and the spec is now in `docs/pcb-palette.md`.

Verified locally that variable-width `fp_line` renders correctly — a generated
hatch exported to SVG with distinct `stroke-width` values from 0.105 to 0.175 mm.

Two findings worth recording:

**The texture is always visible.** The eye resolves ~1 arcmin ≈ 0.087 mm at
300 mm. The smallest halftone cell carrying eight levels off a 0.15 mm minimum
silk feature is ~0.5 mm, which subtends ~5.7 arcmin — about 6× the resolving
limit. PCB halftone is coarser than newsprint and will never blend. That makes
it a *style* (engraving, banknote) rather than a way to fake continuous tone,
which suits this board.

**It is not automatically cheap.** `fp_line` carries its own stroke width so no
filled geometry is needed, but one line holds one width — tonal variation along
a line needs segmentation. Measured: **153 bytes/segment**, and a naive 25 mm
square at 0.4 mm pitch with 1 mm segments produced **1,550 segments / 238 KB**,
i.e. no better than the solid-fill problem being fixed. Quantising the ramp to
~8 levels before segmenting takes it to roughly 500 segments / 76 KB. The rule
is *quantise then segment*, never the reverse.

Ranked by fabrication reliability: line-width modulation first (connected
geometry, no dropout), then pitch modulation, then true stipple last (isolated
silk dots near minimum size print inconsistently). And mask-opening hatching is
capped around 60–70 % duty by the ~0.1 mm dam minimum, beyond which the mask
between openings washes away and the hatch collapses to solid.

Scheduled as v2. It sits naturally inside the rebuild's `legalize.py`, which
already reasons about per-tone minimum feature — a hatch is a legal rendering of
a value *between* two palette entries under the same constraints. v1 must not
preclude it, and the chosen architecture does not.

---

## 2026-08-11 09:35 UTC — Microprinting assessed

**Models:** Opus 5 (analysis, verification).

Achievable in **copper only**, at ~2–3× coarser than banknote microprinting.
Spec added to `docs/pcb-palette.md`.

Etching is photolithographic and silkscreen is a mesh print, so copper is about
twice as fine — that difference decides it. Silk bottoms out at ~0.9–1.2 mm
character height (small text, not microprinting); copper at a capable fab
reaches **0.5–0.7 mm**. Banknote reference is 0.15–0.25 mm.

At 0.5 mm and 300 mm viewing, text subtends ~5.7 arcmin against a ~5 arcmin
recognition threshold — a hairline to the eye, legible under a loupe. The effect
holds even though the scale does not match currency.

Verified `fp_text` on `F.Cu` renders correctly at 0.5 mm/0.075 mm and
0.3 mm/0.05 mm, and costs **468 bytes for two whole strings** because KiCad's
stroke font is built in. Text must stay text — glyph outlines as `fp_poly` would
be orders of magnitude worse. Useful contrast with hatching at 153 bytes/segment.

Two findings that shape how it gets used:

**Never open the mask per glyph.** ±0.05 mm registration against a 0.075 mm
stroke is two-thirds of the feature. Either open one rectangle over the whole
text block with copper letterforms inside (gold on tan, T2 on T3, registration
only places the block edge), or leave the mask closed entirely (T6) for a covert
dark-on-dark sheen that is immune to registration.

**The board's own rules reject it.** The Satoshi Starter sets
`min_text_height 0.8 mm` / `min_text_thickness 0.08 mm` and routes nothing under
0.2 mm, so 0.5 mm microtext violates its own DRC. Art must be excluded from
those constraints — which the planned `RecklessArt` library-membership exclusion
already handles, so no new machinery.

Reliable zone is 0.6–0.8 mm; 0.5 mm is best-case and depends on the fab. At a
0.075 mm stroke, ±0.025 mm etch tolerance is a third of the feature and glyphs
degrade.

---

## 2026-08-11 09:55 UTC — T8: the translucent window

**Models:** Opus 5 (analysis, verification).

Question: on a 4-layer board, does hollowing a cell through every layer and
stripping mask from both faces give a translucent window? **Yes.** Added to
`docs/pcb-palette.md` as an eighth tone.

Light path with no copper anywhere is **1.44 mm of FR4** (0.1 prepreg + 1.24
core + 0.1 prepreg). That is translucent but **diffuse** — woven glass in epoxy
scatters heavily and tints yellow-green. Frosted glass, not a window: light
passes, shapes do not.

**Inner copper can absolutely be excluded** — copper only exists where drawn, so
this is keepouts on all four copper layers rather than "removal". That matters
because the standing recommendation for `SatoshiStarter#3` is to make In1.Cu a
full ground plane; once it is a pour it floods any window unless a keepout
excludes it. Verified the mechanism is already working on this board: three
keepouts inside the inductor footprint with `copperpour not_allowed`,
`tracks not_allowed`, `vias not_allowed`.

Three things make T8 unlike the other tones:

- **Six aligned layer operations** (4 copper exclusions + 2 mask openings), so
  registration stacks across the full stackup. Bold shapes only, no detail.
- **It only exists when lit.** Unlit it is bare laminate, effectively T3. Needs
  a reverse-side LED — all five existing LEDs are front-side THT — or edge
  injection, where FR4 works as a mediocre but usable light guide.
- **Warpage is not a risk**, counterintuitively: asymmetric copper warps boards,
  and a void absent on *all* layers is symmetric.

Product note worth carrying to the kit issues: this is a miner. An activity LED
behind a translucent Satoshi window would glow while the board hashes — literal
visible proof of work on a board built to teach it.

Verification has the same gap as buried void mode: `ZONE_FILLER.Fill()`
segfaults with a keepout-bearing footprint, so no automated confirmation that
the keepout knocks its hole in a filled pour. The GUI plainly works — this board
fills with three keepouts — so the mechanism is sound and only automation is
blocked. Ship behind a flag; verify once by hand in the GUI and export gerbers.
