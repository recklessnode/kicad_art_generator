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
| palette spec, W0 quantiser spike, calibration coupons, technique study | `ccfa35a`, `0274292`, `2d9aaba`, `a4f9ca5`, `52b344a`, `0239f86`, `cdf3033`, `90d322d`, `0c35928` | 2026-08-11 | **Claude Opus 5** |
| W1 emitter, acceptance harness, asset ingest, render driver, coupon floors | `268052e`, `2cfffc2`, `cd20664`, `5ac55d1`, `166af9a`, `fc6bc2c` | 2026-08-16 | **Claude Opus 5** |
| hex ASIC cutout part; min-area, output-size, Tux and green-mask renders | `c619f92`, `6ff633c`, `3c62c52`, `5ab25fc`, `13600b5`, `a80d190` | 2026-08-16 | **Claude Opus 5** |
| **conversion modes** — T8 windows, T9 cuts, microtext, silhouette keyline, knockout, hatch/stipple fills | `0336559` | 2026-08-16 | **Claude Opus 5** |
| microtext audit fix + reproducible SVG rasterisation | `b4666dc` | 2026-08-16 | **Claude Opus 5** |
| palette status board + measured-facts chapter; August log entries | `5c029b6` | 2026-08-16 | **Claude Opus 5** |
| tiling generators (`tools/tilings.py`) — checker, hex, spectre; exact ring arithmetic | working tree, uncommitted | 2026-08-17 | **Claude Opus 5** |
| spectre level-2 investigation and the impossibility ledger | working tree, uncommitted | 2026-08-17 | **Claude Opus 5** |
| board texture, both halves (`tools/texture_board.py`) — ingest, slots, tie-necks, acceptance | working tree, uncommitted | 2026-08-16/17 | **Claude Opus 5** |
| additive texture (`--texture-mode add`) | working tree, uncommitted | 2026-08-17 | **Claude Opus 5** |
| microtext shape flow (`--shape`) and the whitepaper ₿ part | working tree, uncommitted | 2026-08-17 | **Claude Opus 5** |
| board-appearance render driver (`tools/board_render.py`) | working tree, uncommitted | 2026-08-17 | **Claude Opus 5** |
| palette board-texture chapter, shape-flow section; this log pass | working tree, this entry | 2026-08-17 | **Claude Opus 5** |

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

**And a `Date:` trailer, for the reason in the header note.** The August 16
commits carry both. The note above warns that a local-time author date can show
the *previous* calendar day; this session is the mirror image — the last commits
are `2026-08-16 22:26–23:00 −0700`, which is **2026-08-17 05:26–06:00 UTC**, the
*next* calendar day. `Date: 2026-08-16` on each commit is the session date and
is the one to trust. The 2026-08-16 entries below carry the same date for the
same reason, and no clock time: they were written at the end of the session
rather than as it ran, so a per-entry UTC timestamp would be invented precision.

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

---

## 2026-08-11 10:20 UTC — Reference boards, plus T9 (cuts) and the knockout technique

**Models:** Opus 5 (analysis).

Five physical references supplied. Two add capability the palette did not cover.

**T9 — cuts.** `Edge.Cuts` outline and internal cutouts are art. Unlike T8
(translucent laminate) a cut is the *absence of board*, showing whatever is
behind. The governing fact is that cuts are routed with a rotating bit, so
**internal corners are always filleted to the bit radius — 0.8–1.0 mm
typically** — and sharp inside corners are impossible. Minimum slot width is
about one bit diameter, so a 0.5 mm slot cannot exist.

The pendant reference makes the right division of labour obvious: its dense
interlocking pattern is entirely ENIG-on-black, and the only cuts are the
triangular outline and three mounting holes. **Cuts for silhouette, copper and
mask for detail.**

**Knockout.** The SparkFun carrier's pin labels are white silk rectangles with
the text knocked *out* — the dark letters are bare mask through gaps in the ink,
not a second ink. This inverts the usual assumption and is worth naming, because
minimum feature then applies to the **gap** rather than the mark, and ink bleeds
inward, so knockout text needs *more* margin than positive text. It also means
polygon-with-holes must be first-class in the tracer, which the architecture
already requires for letterforms like O.

**The Bolt Industries ruler pair is the most useful single reference:** identical
artwork on two boards, showing the metal tone as **brown on bare/OSP** and
**gold on ENIG**. That is the documented T2 finish-dependence in physical form,
and it argues for the palette file carrying a finish parameter rather than
hard-coding gold.

Also noted: the sticker sheet's two photographic images are visibly halftoned,
which is a useful sanity check on the earlier conclusion that PCB dithering
reads as texture rather than blending. At legible scale, it does.

---

## 2026-08-16 — W1 lands: emitter, acceptance harness, ingest, renders

**Models:** Opus 5 (all work).

Five days after the audit concluded *rebuild, fabrication-first*, the pipeline
runs end to end: image in, quantised tones out, footprint written, footprint
**checked**.

| commit | what |
|---|---|
| `268052e` | mixture-aware tone assignment — kills the antialias halo the nearest-anchor quantiser produced at every tone boundary |
| `2cfffc2` | **W1 emitter**, `tools/emit_art.py`: marching squares → RDP → one `fp_poly` per contour per layer, holes keyhole-bridged |
| `cd20664` | **acceptance harness**, `tools/verify_art.py`: seven checks, and it reads the palette doc rather than duplicating it |
| `5ac55d1` | asset prep — crop, SVG fill inheritance, colour census |
| `166af9a` | library render driver and preview sheet |
| `fc6bc2c` | the coupon generators honour the fabrication floors, and breaching one is loud |
| `c619f92` | hex ASIC display cutout footprint, hand-built |
| `6ff633c`, `3c62c52`, `5ab25fc`, `13600b5`, `a80d190` | comparison renders, and two findings that came out of making them |

### The palette doc is now an input, not a description

`verify_art.py` parses `docs/pcb-palette.md` for the layer recipe and the
fabrication floors. Run it and it says so:

```
  palette : .../docs/pcb-palette.md
  kicad   : .../KiCad/10.0/bin/kicad-cli.exe  (10.0.0)
  floors  : silk 0.150  mask 0.100  copper 0.100  buried 0.500*PROVISIONAL  edge 1.00 mm
```

and per footprint, under the layers check,
`palette recipes (front-side): B.Mask, Edge.Cuts, F.Cu, F.Mask, F.SilkS, In1.Cu`
— read out of the doc's own recipe fence.

That is a good property — one authority, not two — and it has a consequence
nobody would guess from the filename: **editing the palette doc can change what
the harness enforces.** Every documentation pass on that file from here on has to
re-run the harness and compare, which the entry at the bottom of this log does.

### Two findings from the render work, neither of them the point of it

**`kicad-cli fp export svg` emits nothing at all for `In1.Cu`.** Silently — the
front layers plot, the buried layer produces no output. So T4 and T7 cannot be
previewed from a footprint by any route, and the composite figures in
`docs/images/` show five tones honestly and the two buried ones not at all. Noted
in the palette doc rather than worked around.

**A region that maps to T5 loses its silhouette entirely**, because T5 draws
nothing and *is* the board. On Tux that is **34.7 % of the figure** — his whole
body — dissolving into the background with no edge. Colour data cannot recover
it: body and background are the same tone and contiguous. Alpha can, and that
became `--silhouette-tone` in the same session (below).

The green-mask renders that exposed it come with their own caveat, recorded on
the commit and now in the palette doc: **the tone anchors are a black-mask set**,
so a green palette is a render-time choice and not a calibration. That is issue
**#1**, unchanged.

### And one uncomfortable measurement

Across the 18-piece `RecklessArt` render, **4,283 of 4,576 polygons (93.6 %) sit
below the fabricable minimum feature** for their layer, at a consistent 0.70× of
source-pixel size — single-pixel raster speckle that cannot print and inflates
every count downstream. `--min-area-mm2 auto` already implements the filter and
correctly *refuses* when filtering would empty a tone, which is exactly what
happens on the raster Satoshi assets. So it needs a decision rather than a
default, and it is open as **#7**.

---

## 2026-08-16 — T8 and T9 become conversion modes, and one of them cannot be a part

**Models:** Opus 5 (all work).

Both tones were specified on 2026-08-11 and neither was runnable. Now:
`tools/emit_art.py --window-tone TONE` and `--cut-tone TONE`, with
`--cut-fillet-mm` (0.8 default), `--cut-outer-fillet-mm` (0, sharp),
`--copper-edge-clearance-mm` (0.5), `--allow-copper-in-cut` and
`--no-cut-courtyard`. Outputs in `output/t8t9/`; `tests/test_t8t9.py`.

### The measurement that decides T8's shape

**A copper keepout carried by a footprint is silently ignored by the KiCad 10
zone filler.** Not an error, not a warning: the plotted copper gerber is
**byte-identical to the same board with no keepout at all**. Board-level rule
areas work as documented.

Read that against the earlier verification gap, and the two findings resolve
each other: the case that segfaults `pcbnew.ZONE_FILLER.Fill()` is the
*footprint*-borne keepout, which is also the case that produces no hole even when
the filler survives. The keepout that matters — the board-level rule area — fills
and plots normally, and the emitter never asks for the other kind.

So a T8 window **cannot be a self-contained part**. `--window-tone` emits the two
mask apertures on `F.Mask` and `B.Mask`, marks the outline to trace on
`Dwgs.User`, and says on every run that the four copper exclusions must be drawn
on the board or the In1 pour floods the window and it never lights. The
`Dwgs.User` outline is documentation, not fabrication.

The same measurement is why `tools/texture_board.py` — started this session, part
1 of 2 — is board-in / board-out and reasons in board coordinates throughout,
rather than generating a footprint.

### T9 refuses two things rather than warning about them

**A footprint cutout is unconditional**: footprint `Edge.Cuts` merges into the
same gerber layer as the board outline, so every board placing the footprint gets
the hole, with no per-instance switch. And **copper must be on the keep side** —
`copper_edge_clearance` is a distance rule and is indifferent to *which side* of
the cut the copper is on, so copper printed on the slug clears the rule, passes
DRC, and is routed away with the waste. The emitter decides the side explicitly
and fails rather than warns. Both had already bitten a hand-built part in
`library/`.

Inside corners are filleted to `--cut-fillet-mm` deliberately, because the fab
will round them to its own bit whether or not the design admits it; outside
corners are left sharp, because the bit cuts around those.

---

## 2026-08-16 — Microprinting becomes a conversion mode, and the font gets measured

**Models:** Opus 5 (all work).

`tools/microtext.py --text STRING --height MM --tone TONE` places a run, a run
along a `--path`, or repeated rows filling a `--region`; `emit_art.py` carries the
same flags as `--microtext-*` so a microprint lands on an art footprint in one
pass. Specimens in `output/microtext/`, tests in `tests/test_microtext.py`.

It enforces the two rules the palette already stated rather than restating them:
silk below the cap height its own floor implies is **refused**, and so are `T3`
(the letterforms would *be* the mask opening) and the buried tones. `T2` puts
copper letterforms inside **one** block opening; `T6` puts copper under mask with
no opening at all. Those are the only two forms offered, which is what the
±0.05 mm registration argument demands.

### The counters are measurable, so they were measured

`tools/stroke_font.py` reads KiCad's newstroke font off a `kicad-cli fp export
svg` render — which writes stroke centrelines as plain polylines — and records,
per printable ASCII glyph, the advance, the ink box, and the inscribed radius *D*
of the narrowest enclosed void, in em. Ink is centred on the centreline, so a
counter's clear width is exactly `2·D·cap − stroke`, which turns "closed
letterforms fail before straight strokes" into arithmetic. At the 1:6.7 stroke
ratio the crossover is **D = 0.15 em**; measured, `'e'` is **0.147**, `'@'` and
`'8'` 0.214, `'B'` 0.238 — so `e` is the first glyph in the specimen to close,
which is why that specimen was chosen.

For the full specimen on copper against the doc's 0.1 mm floor: stroke binds at
0.667 mm, **counter at 0.690 mm** — the counter binds — and legibility at
0.600 mm. **0.695 mm** passes every check in `verify_art.py`, landing inside the
0.6–0.8 mm reliable zone without having been aimed at it. At a standard fab's
0.127 mm the same string needs 0.88 mm, which is the "per-vendor decision" point
expressed in millimetres.

### KiCad slides the text as the pen gets heavier

`justify left` justifies the text **box**, which includes the pen, so the
letterforms sit **0.658 × stroke to the right and 0.052 × stroke above** the
anchor. Pure translation — the string's own extent does not change — and linear
to 6e-9 em across a 90× range of stroke ratio.

At a 0.105 mm stroke that x shift is 0.069 mm, **larger than the ±0.05 mm mask
registration tolerance the block opening exists to absorb**. A block opening
placed from the anchor instead of from the letterforms therefore spends the whole
registration budget before the fab does anything. `stroke_font.py` corrects for
it, and `verify_art.py` now uses the measured extents instead of its old 0.75 em
per character estimate.

Cost, for contrast with hatching: **468 bytes for two complete strings**, because
KiCad's stroke font is built in and a whole string is one object. Text stays text.

---

## 2026-08-16 — Region-boundary operations: the silhouette keyline, and knockout

**Models:** Opus 5 (all work).

Two operations on where a tone *ends* rather than on what it is.
`--silhouette-tone TONE --silhouette-mm WIDTH` and `--knockout MARK[:HOST]` with
`--knockout-floor-mult`. Outputs in `output/regionops/`.

### The keyline is in millimetres, which was the correction

The `a80d190` render note called the pixel-specified prototype wrong: a ring in
pixels shrinks as the art scales up. It is millimetres now, converted per-run
from `width_mm / W`, so it is the same physical keyline at every output size —
and it therefore lives in `emit_detailed()`, not in `load_labels()`, which has no
idea how large the art will be. Distance is an exact windowed Euclidean
transform, no scipy, since scipy is not a dependency of this tree.

It **warns rather than clamps**, on three independent conditions: below the
tone's fabrication floor, sub-pixel at the current raster scale, and empty ring.
It also reports which tones the ring ate and how many ring pixels came from the
**raster frame** rather than an alpha edge — art running off its own crop gets
keylined along the cut, 5 px on Tux.

Tux at 30 mm, a 0.30 mm T3 keyline: T3 goes from **0.02 % to 4.93 %** of the
figure and T5 from **34.75 % to 31.03 %**; the footprint goes from 29,809 B to
35,987 B. The check that matters is topological, not tonal: before the keyline,
T5's border includes `alpha=873`; after, alpha vanishes from T5's border
entirely — the ring fully separates body from transparency.

**It refuses a source with no alpha, deliberately.** The alternative — outline
the outermost non-T5 region — is a guess, because on an opaque source T5 is used
both *as* subject and *as* ground, which is the exact problem the flag exists to
solve. It would also keyline every interior T5 region, i.e. Tux's own markings.

### "Knockout needs more margin" is now 2×, and derived

`--knockout-floor-mult`, default **2.0**. The palette states the direction and
gives no number. Ink bleed *b* runs outward from every inked edge: a positive
mark of width *w* has ink inside both edges and images at *w* + 2*b* — fatter but
present — while a gap has ink outside both edges, images at *w* − 2*b*, and is
**gone at w = 2b**. The positive floor *F* is where a mark stops being reliable,
so *b* ≈ *F*/2 — and for mask *F*/2 = 0.05 mm is exactly the registration
tolerance the palette already quotes. A gap therefore wants *F* + 2(*F*/2) = 2*F*.

Reproduced this session on the synthetic silk field: `--knockout T2:T1` takes
**9 `fp_poly` to 1**, suppresses T2's `F.Cu`+`F.Mask` entirely, reports 100 % of
the mark's border against T1, and audits the host's four resulting gaps against a
`0.3 mm = 0.15 mm ×2` floor — **two of the four fail, narrowest 0.094 mm**. A
0.2 mm gap passing the positive silk floor and failing the knockout floor is the
whole point, in one artifact.

Gap width is the **largest inscribed circle**: minimum width condemns every acute
corner, area waves through a long thin slot. It is good to roughly ±4 % of the
floor under test and the error direction is not guaranteed, so a gap within a few
percent may be called either way — a warning threshold on top of a bleed
multiplier nobody here has physically measured. The audit runs on **every hole in
every tone**, flag or no flag, because a hole *is* a knockout.

### Three things that are worse than they look

**The harness cannot see knockouts at all, at any floor.** `verify_art.py`
measures clearance *between* separate features; after keyhole bridging a knockout
is a hole *inside* one polygon, so there are no pairs to compare. Of the nine
footprints in `output/regionops/`, the **one** that passes every check is
`knockfield_knockout.kicad_mod` — the one carrying the two sub-floor silk gaps.
The emitter's own gap audit is currently the only thing that catches them. A
verify-side check that walks fracture slits back into holes is wanted.

**Tux cannot demonstrate the knockout path**, honestly reported by the tool
itself: T5 there is not enclosed by anything, so both diagnostics fire correctly
("only 29.2 % of the mark's border touches T1"; "T1 has no holes at all"). The
suppression path is proved on the synthetic field instead.

**A floor inconsistency already in the tree, surfaced rather than papered over.**
`emit_art.MIN_FEATURE_BURIED_MM` is **0.30 mm** for `In1.Cu`/`In2.Cu`,
`verify_art.FLOOR_BURIED` is **0.50 mm PROVISIONAL**, and the palette gives no
number at all — `floor_for()` correctly returns `None` for a buried layer. The
0.30 was left alone because `--min-area-mm2 auto` has used it since before any of
this, and moving it would silently change what every existing asset drops; the
new region-boundary and halftone checks use the harness's 0.50 so emit and verify
agree with each other. Both numbers are kept, each doing the job it already did,
and the emitter warns whenever a run actually draws on a buried layer, naming
both.

It is **not resolvable in code**, and the code says so: `cal_buried` — the
calibration block that already exists in `tools/coupon_blocks.py` — has to be
fabricated and measured. That is the physical calibration session, **#5**, and
specifically coupon **#6**.

---

## 2026-08-16 — Halftone fills: hatch and stipple stop being a v2 feature

**Models:** Opus 5 (all work).

`--fill-mode solid|hatch|stipple`, with `--hatch-pitch` (0.40 mm),
`--hatch-angle` (45°), `--stipple-pitch` (0.50 mm) and `--halftone-levels` (8).
A source *gradient* becomes a duty-cycle field between the T5 background (duty 0,
draws nothing) and the tone solid (duty 1), so a picture is no longer limited to
seven flat tones. It needs the source image: a `.npy` of labels has already
thrown the shading away. Outputs in `output/w1_halftone/`.

Scheduled on 2026-08-11 as v2, to live in the rebuild's `legalize.py`. It arrived
early for the reason that note gave: the duty ladder needs per-tone minimum
feature, and the emitter already had it.

Which techniques these are, precisely: `hatch` is **technique 1, line-width
modulation** — constant pitch, mark width tracking duty. `stipple` is technique
3, dot size on a fixed grid. **Technique 2, pitch modulation, is not
implemented**, and the palette's status table now says so.

### The floor sets the duty range, and it is narrower than the estimate implied

The layer floor applies to the mark *and* to the dam, so duty is confined to
`floor/pitch … 1 − floor/pitch` with 0 and 1 exact. Measured at the 0.4 mm
default pitch:

| tone | layers | floor | achievable duty |
|---|---|---|---|
| T1 | `F.SilkS` | 0.15 mm | 0.377 – 0.623 |
| T2 | `F.Cu` + `F.Mask` | 0.10 mm | 0.253 – 0.748 |
| T3 | `F.Mask` | 0.10 mm | 0.253 – 0.748 |

The 2026-08-11 entry put the mask-hatch cap at "roughly 60–70 %" from the dam
minimum. Measured, it is **74.8 %** at 0.4 mm pitch — the cap is pitch-dependent,
and the estimate was in the right place. Silk gets only the middle quarter of its
ramp. Stipple is worse, as the ranking predicted: squares on a square grid put
duty at the *square* of the linear ratio, 0.091–0.487 for T1 and 0.041–0.637 for
T2 at 0.5 mm pitch. Clamped pixels are counted and reported, never silently
snapped.

### It declines the ramps the palette calls worthless

Measured against the black-mask anchors, **T6 is 7.9 L\* from the T5 background
and T7 is 3.4 L\***, both under a 20 L\* worth-doing line, so both are drawn
**solid** — the palette's "too subtle on black mask to be worth it", enforced
rather than restated. T1 (84.1), T2 (60.9) and T3 (65.0) are patterned. All
layers of a tone's recipe carry the same marks, so T2 stays copper-and-mask
coincident; hatching only the mask would turn the space between marks into T6.

### The cost projection holds

The 2026-08-11 entry projected a 25 mm square at 0.4 mm pitch, quantised to 8
levels, at roughly 500 segments / 76 KB. Measured on exactly that case,
`grad_hatch`: **677 filled marks / 105.5 kB**, two tones deep. Same order, about
a third above the estimate, and the rule it rests on survives — quantise before
segmenting.

Marks are filled quads, not `fp_line` strokes: a stroke has round caps that bulge
half a width past the clip, and one line holds one width anyway. On real art the
premium is milder because most of a picture is flat — the 25 mm Satoshi asset
goes 85,458 B solid → 138,013 B hatched. A pure ramp is the opposite extreme:
2,113 B solid, because a gradient quantises to almost nothing, against 108,061 B
hatched, because the hatch is the only thing rendering it at all.

Two decisions worth recording. Clip contours are deliberately **not**
RDP-simplified: adjacent duty levels share a marching-squares boundary exactly,
and simplifying each independently would open a 0–0.05 mm slot on every level
boundary in the picture. And `--fill-mode solid` output is byte-identical to the
pre-change emitter, so the flat path carries no cost from any of this.

---

## 2026-08-16 — Four measurements against KiCad 10.0.0, and the docs squared with reality

**Models:** Opus 5 (all work).

### The measurements

| fact | evidence | now recorded in |
|---|---|---|
| a copper keepout carried by a **footprint** is silently ignored by the zone filler | plotted copper gerber **byte-identical** to the same board with no keepout | palette: T8, and *Measured, not assumed* |
| `kicad-cli fp export svg` emits **nothing** for `In1.Cu` | front layers plot, buried layer produces no output, silently — so T4/T7 cannot be previewed from a footprint | palette: *Practical limits* and *Measured, not assumed* |
| arcs in `fp_poly` round-trip to gerber as real **G02/G03** | **2.2–4× smaller** than the RDP-simplified polyline for the same curve; the emitter does not use them yet | palette: *Measured, not assumed* |
| KiCad does **not** snap, merge or heal same-layer abutting polygons | exact coincidence gives a **true zero gap**; whatever the emitter writes reaches the film | palette: *Measured, not assumed* |

The arc result closes a question the April audit raised and could not settle —
whether `fp_poly` takes curves — and answers it all the way to the film rather
than only into the file. It is the largest known unclaimed file-size win for
curved art, and it is written down precisely because nothing consumes it yet.

The abutment result is why the halftone clip contours are left unsimplified, and
it cuts both ways: a sliver written by accident is fabricated as a sliver.
`verify_art.py` measures 19 `F.Cu` pairs at a 0.000 mm gap in
`output/regionops/baseline.kicad_mod` — features touching exactly rather than
nearly.

Two further facts from the render work are recorded with them: **a region mapping
to T5 loses its silhouette entirely** (34.7 % of Tux), and **the tone anchors are
a black-mask set**, so the green-mask figures are a render-time choice and a green
palette needs its own calibration under **#1**.

### `docs/pcb-palette.md` now says what you can run

The palette described hatching, stippling, microprinting, knockout, T8 and T9 as
*techniques*. All six are conversion modes now, and the document could not tell a
reader which of them they could actually run. What changed:

- a **status board** at the top — every technique against conversion mode,
  calibration geometry only, or not implemented, with the flags that drive it.
  Line-pitch modulation is named as the one shading technique with no
  implementation, and the coupon generators are named as calibration geometry
  rather than modes.
- **In the emitter** sections for hatching/stippling and for knockout, which had
  none, alongside the ones microprinting, T8 and T9 gained earlier in the session.
  Measured duty ranges, the 2× knockout floor derivation, and the harness's
  knockout blind spot are all in them.
- *Sequencing* under hatching said "this is a v2 feature". It is marked
  **superseded**, with why it arrived early and what survives of the v2 framing.
- a closing **Measured, not assumed** chapter holding the six facts above with
  their evidence.

### Verified, because that doc is executable

**Both** tools parse the palette — `verify_art.py` for the layer recipe and the
floors, `emit_art.py` for the floors — so an edit to that document can change
what gets enforced and what gets drawn. Prose edits to it are therefore checked like
code, and these were:

- harness output over `output/regionops`, `output/w1_halftone`, `output/t8t9` and
  `output/microtext` — **25 footprints** — is **identical to the pre-edit run,
  line for line**, including
  `floors  : silk 0.150  mask 0.100  copper 0.100  buried 0.500*PROVISIONAL  edge 1.00 mm`
  and the per-footprint recipe line, and with **no** parse warnings.
- a hatch emit re-run after the edit is **byte-identical** to the same command
  before it, and still reports `silk 0.15  mask 0.10  copper 0.10 mm from
  pcb-palette.md`.

The one thing the pass did not touch is `README.md`, which still does not mention
any of the new flags. Other work was live in that file this session and a
concurrent edit had a good chance of clobbering it; the flags are self-documenting
via `--help` until someone does it deliberately.

Nothing committed; all of it is in the working tree.

---

## 2026-08-17 — Board texture: the pour becomes the canvas, both ways

**Models:** Opus 5 (all work).

`tools/texture_board.py` is now whole. It is not a conversion mode and there is
no footprint anywhere in it: it reads a `.kicad_pcb`, decides where decoration is
allowed from the board's own geometry, lays a tiling there, and writes a board
back. It has to be board-level, because a footprint-borne copper keepout is
silently ignored by the KiCad 10 filler — the fact recorded on 2026-08-16, now
load-bearing rather than interesting.

It runs under KiCad's bundled Python on `pcbnew` rather than parsing
s-expressions, and the sharper of the two reasons is a silent-failure one: KiCad
10 writes nets as `(net "Name")` **strings**, so a regex written against the old
numeric form matches nothing, selects an empty obstacle set, and reports a huge
permitted area with no symptom at all.

### Add mode, and the number that decided it

A requirement change from the board owner: texture should be F.Cu material under
closed mask — not gold, just texture — and should appear wherever there is mask
with no copper to interfere with. So `--texture-mode add` lays **new** copper in
**empty** board: tone T6, the dark under-mask sheen, against T5 bare mask.

Only the base region inverts. Subtract starts from the pour and removes
obstacles; add starts from the whole board inside `Edge.Cuts` and removes the
same obstacles plus every copper feature of every net plus every mask opening.
Clearances, courtyards, the HS1 envelope, the return corridor, the edge inset,
whole-tile placement and fragment dropping are shared code in both directions.

The measurement that answered the owner's question, on the reference board:

| | permitted | placed | copper |
|---|---|---|---|
| subtract, `F.Cu` | 41.0 % of the 1691.5 mm² pour ≈ 693 mm² | 44 tiles, 172 dropped | −3.51 % of the pour |
| add, `F.Cu` + `B.Cu` | 8575.0 / 9125.4 mm², **55.7 % / 59.2 % of the board** | 1188 of 3094 tiles | +9098.0 mm² in 1188 islands |

Twelve times the area, because a plane covering a fifth of the board has a large
complement. That is the difference between a texture and scattered confetti.
`--add-fill outline` was built too and lays 1956.3 mm² in 21 islands; solid is
4.7× the copper for the same tiles and the *same* electrical cost, so it is the
default.

### Float it. Tying it to GNDREF is a label, not a connection

Both were built and both went through DRC on the real board. Floating: 206
warnings, 0 errors, **0 unconnected** — identical to the untextured baseline by
type and severity. `--add-net GNDREF`: 206 warnings, 0 errors, and **499
unconnected items**, every one severity *error*.

The recommendation is floating, and not because DRC dislikes the alternative.
`SetNetCode(GNDREF)` declares that the copper *ought* to be on GNDREF; the copper
is still an isolated island, so the connectivity engine is right. The board is
not more grounded for having been labelled.

Stitching vias cannot fix it either, and that was measured rather than assumed:
of the 4671.5 mm² added on `F.Cu`, GNDREF lies beneath **0.0 %** on `In1.Cu`,
`In2.Cu` and `B.Cu` alike. That is the definition of the mode — texture goes
where there is no copper, and here the inner planes follow the outer ones — so
there is nothing under it to stitch down to. Largest island 7.658 mm², none over
3.43 mm across; that is what a fab's own thieving pattern already is.

A third option was rejected before it was built: emitting tiles as **zones**.
Every pour on this board sets `island_removal_mode = ALWAYS`, so a tile-as-zone
is an island and the filler deletes it on the next refill — the texture would
vanish from the plots while the file still described it. `PCB_SHAPE` is not a
fill, so the filler never touches it.

### Three things measurement overturned, each already coded the wrong way round

1. **A round slot cap overhangs its endpoint by `slot/2`.** A 0.40 mm neck with a
   0.25 mm round-capped slot leaves 0.15 mm of copper, under the pour's 0.25 mm
   `min_thickness`. The filler deleted every neck, then every cell as an island:
   **355.7 mm² gone**, the texture replaced by hexagonal bites out of the pour
   edge, from a 0.10 mm arithmetic error. `--neck-mm` now means the copper that
   *survives*, and `cap_extend_mm()` subtracts the caps.
2. **An acyclic wall set does not guarantee connected copper.** `--neck-style
   forest` is a provable spanning tree and still isolated **21.0 mm²** at the
   pour's east edge: acyclicity guarantees connectivity in the *plane*, and the
   copper is a bounded region a slot chain can sever by reaching its boundary
   twice. A neck in every wall is what makes the guarantee shape-independent.
3. **The flood-fill raster has to cover the whole pour, not the permitted
   region.** Sized to the permitted region it cropped the pour and reported
   `F.Cu` as 3 components of 765.814 mm² instead of 4 of 1562.485.

### The proof, since `verify_art.py` reads footprints and cannot see boards

Not "the areas match" — two different regions can share an area. The check is the
**symmetric difference** of the filled polygons before and after: add mode
floating gives **0.0 mm² on `F.Cu`** and 8.2e-08 mm² on `B.Cu`.

The tolerance was measured rather than chosen. Refilling the untextured board
three times in one process gives symdiff exactly 0.000e+00 for every pair, so the
filler is deterministic and the noise floor is *zero* — which is why 8.2e-08 had
to be explained instead of waved through. It is one sliver at x 88.785,
y 71.06…71.23: a polygon vertex landing differently in Clipper's integer
arithmetic once the filler has a foreign object to clear at all. Same-net copper
needs no clearance, which is exactly why the GNDREF variant reads 0.0. It is
1.1e-08 % of the pour. The clearance that makes this hold is `--clr-copper`,
default **0.55 mm** and deliberately not the 0.5 mm the other knobs use, because
every pour here carries `local_clearance 0.5 mm`.

Connectivity is proved by component **area**, not count: subtract mode takes
`F.Cu` from 1559.188 / 126.376 / 6.134 / 3.299 mm² to 1495.246 / 126.376 / 6.134
/ 3.299 — three components unchanged to 1e-9 mm², one smaller by exactly the slot
area. 4- and 8-connectivity agree, and an independent raster flood fill agrees;
that probe is the only direct look at the topology, because with island removal
ALWAYS the filler deletes isolated cells rather than leaving them, so a component
count alone cannot fail.

Fill time is not a constraint: **1.13 s at 346 keepout zones** against 1.13 s
untextured, knee around 2000 zones (1.48 s), 14.9 s at 11500.

### Two zone-filler traps recorded in `Measured, not assumed`

`ZONE::NeedRefill()` is an in-session dirty flag and is **not persisted** — it
answers `False` for all 15 zones on a never-refilled board *and* on a freshly
refilled one, so a staleness check built on it would pass every stale board on
earth. Ingest refills in process instead. And `Unfracture()` on an
already-unfractured set **destroys its holes**: the `B.Cu` pour goes 1377.8 mm²
with 41 holes to 1422.1 mm² with 0 holes, silently filling 44.3 mm² of void, and
every area check still passes because the area it reports is the area it now has.

### What is board-specific, and named as such

HS1 is mis-modelled — only its four M3 bosses are courtyard, the 40 mm body
outline sits on `B.Silkscreen`, so the footprint under-reports the heatsink by
about 12× in area; the true front envelope is x 72.22…119.78, y 52.42…99.97 mm
(SatoshiStarter#55). The VRM-to-ASIC return corridor, L1 (151.5, 75.5) to U9
(100.0, 72.5), is excluded outright — texture across a return path is a decision
about current, not about art. And the texture is derived from board state, so any
placement or routing change invalidates it: regenerate, never maintain, never
merge a textured board back.

---

## 2026-08-17 — Tilings, and why the spectre stops at level 1

**Models:** Opus 5 (all work).

`tools/tilings.py` is pure geometry — no board, no KiCad, no file I/O — and
supplies `checker`, `hex`, `spectre` and `spectre-curved`. Two decisions in it
are worth the log.

**`tile_mm` is the equal-area size.** Every kind produces tiles of area exactly
`tile_mm²`, because that is the only definition under which two kinds are
comparable, and comparing them is the point: the number that decides what a
texture costs is slot length per unit area. Measured at `tile_mm 6` — checker
24.000 mm perimeter per tile and 0.3667 mm of slot per mm²; hex 22.335 mm and
0.3554. Hex costs **7 % less slot** for the same tile area, so 7 % less copper
removed and 7 % fewer vertices in the file.

**Construction coordinates are exact.** Vertices of Tile(1,1) live in the ring
`Z[d]`, `d = exp(iπ/6)`, so a vertex is an integer 4-tuple, every 30° rotation is
an integer operation, and two tile edges either coincide *exactly* or not at all.
There is no tolerance anywhere in the fit check.

### Level 2 was not reached, and nobody should look for it in this framework

> **Superseded 2026-08-20 — see "The spectre reaches the plane" at the end of
> this log.** Everything measured below is correct and none of it is retracted;
> the phrase doing the damage is "in this framework". The framework was missing
> the substitution's per-generation *reflection*, which makes the quad map
> anti-linear and its growth invisible to every linear eigenvalue sweep recorded
> here. `SPECTRE_AUDITED_LEVEL` is now 5, at 34 649 tiles.

`SPECTRE_VERIFIED_LEVEL` stays at **1**. A level-2 patch was built — 71 tiles,
the published count, zero overlaps, one boundary loop, no holes, no reflected
tile — and rejected on compactness at **64 % hull fill** against 80.4 % for a
true supertile. What is new is that the cause is no longer a suspicion about a
subtly wrong anchor quad. It is structural, and it was measured:

- **The quad is forced.** Sweeping all 14·13·12·11 = 24024 ordered vertex
  4-tuples, exactly **four** make a valid 9-tile cluster, and all four produce the
  identical cluster at 80.4 % fill. Level 1 is not one option among many.
- **The quad map is linear, so its growth is a fixed number.** The eight slot
  rotations come from the cumulative turns in the rules and never touch the quad;
  each slot translation is a fixed ring combination of the four quad points. One
  substitution step is therefore a fixed 4×4 complex matrix.
- **That number is 3, and it has to be 2.805884.** Measured by iterating the map:
  perimeters 29.031, 87.580, 262.740, 788.221, … a ratio of **3.000000000** from
  level 3 on, against `sqrt(4 + sqrt(15)) = 2.805883701` forced by the tile
  counts. The quad outruns the metatile by 6.9 % per level, compounding, and the
  level-2 patch comes out as a **ring of eight clusters around one connected void
  of 21.2 tile areas** — 2.36 clusters' worth, measured by rasterising the patch
  and flood-filling inside its hull. The 64 % was measuring exactly that.
- **No anchor quad fixes it.** Across all 32⁴ = 1,048,576 super-quad rules, not
  one has any eigenvalue of modulus 2.805884 (0 hits at 1e-7 and at 1e-9; nearest
  miss 2.8058798). The current constant sits at eigenvalues [3, 1, 0, 0].
- **Nor does re-deriving the rules.** Re-describing the verified cluster as a
  7-rule chain — every base tile, every Mystic partner, all 5040 slot orderings —
  yields 1794 chain descriptions; the nine with the canonical
  60/60/120/180/180/240/120 rotation sequence give five distinct rule sets, and
  all five fail the same eigen test.

So the statement is stronger than "level 2 was not found": for these rules, with
an anchor quad made of (slot, quad-index) points, a level-2 supertile does not
exist, and 64 % is a necessary consequence rather than bad luck. Changing
`SPECTRE_SUPER_QUAD` cannot help.

Two things are left open and are written into the module so the next person
starts where this stopped. 1747 of the 1794 chain descriptions were never
eigen-scanned — only the nine matching the published turn sequence were, which is
a judgement, not a proof, and the scan is mechanical. And the likeliest real fix
is not in the space searched at all: this module collapses the nine metatile
labels into two, which reproduces the tile counts exactly — which is *why* every
count-based check passes — but if the labels carry different quads then the quad
is not one vector under one linear map and the growth argument does not apply to
the real system. Restoring the nine labels, each with its own quad, is the thing
to try.

> That hypothesis was tried on 2026-08-20 and is **wrong**: the published system
> shares one quad across all nine labels, and the nine labels *without* the
> reflection give 9 overlapping pairs at level 2 and 1908 at level 3 — worse than
> the two-cluster collapse. The two-cluster collapse *with* the reflection is
> clean. See the entry at the end of this log.

A quad-free direct fit was also tried and is explicitly **not** evidence: all
three runs (1752, 2030 and 10004 complete placements) were stopped by their own
time budget rather than exhausting the space, and the overlap test capped its
pair list, so genuinely overlapping arrangements were let through. It rules
nothing out and is recorded so nobody repeats it thinking it settled something.

`spectre` therefore **refuses** any window bigger than its 9-tile cluster —
roughly 15 mm across at `--tile-mm 4`; measured, a 14 mm window yields 4 tiles
and a 15 mm window is refused — rather than emit unaudited geometry. The
aperiodicity claim is not made for it either: a 9-tile cluster cannot demonstrate
absence of translational symmetry. The scan itself is known to work, because the
periodic kinds score exactly 1.0000 on it (checker 68 exact repeats of 68, hex 54
of 54); it simply has nothing big enough to run on, so
`test_spectre_has_no_translational_symmetry` remains a strict `xfail` and did not
silently convert to a pass.

One honest caveat about the tile itself: this module emits Tile(1,1) with
**straight** edges, which is not by itself an aperiodic monotile — straight edges
let a reflected copy sit against an unreflected one. What is produced is a
specific, verified, non-periodic tiling *by* Tile(1,1), using rotations and
translations of one handedness only; no patch this module builds contains a
reflected tile, and a test asserts it tile by tile. Straight edges are a
fabrication choice: every edge becomes a slot, a curve becomes a polyline anyway,
and each extra vertex costs board file for no visible gain at a 2–6 mm tile.
`spectre_curved()` is there if the look is wanted.

---

## 2026-08-17 — Prose flowed into a shape, and the whitepaper at 0.6783 mm

**Models:** Opus 5 (all work).

`tools/microtext.py` gains a fourth placement, `--shape FILE`, alongside `--at`,
`--path` and `--region`. It is **not** `--region` with a stencil over it:
`--region` repeats a string, while `--shape` treats the string as a continuous
body of prose, fills each x span the mask offers on each row greedily on word
boundaries, and carries the remainder to the next span. The line lengths *are*
the silhouette — there is no outline in the output at all.

Vertical metrics are taken once, from the whole body, and every run is anchored
against them. Measuring each chunk's own ink box instead would sit a chunk with
no descender lower than its neighbour and the rows would visibly stagger. A row
band counts a column only if **every** scanline in the band is inside the mask;
`--shape-center-band` relaxes that, at the cost of letting ascenders and
descenders hang past the silhouette.

Three refusals, on the same principle as the rest of the tool. Text left over
when the shape fills up is refused, naming the unplaced word count and the cap at
which it did fit. A shape that rasterises to nothing is refused and names
`--shape-element` as the fix — `examples/bitcoin_b.svg` stacks a rounded square,
a disc and the currency mark, so rasterising it whole gives a filled square,
which is not the shape anyone means by "the mark". And `--shape-width` with
`--shape-height` is refused, because the mask has one aspect ratio and cannot
honour both. Spans too narrow for the next word are left blank and reported
rather than filled by inventing a hyphen the author did not write;
`--shape-hyphenate` opts in.

### The Bitcoin whitepaper Introduction, in the Bitcoin mark

`library/RecklessArt.pretty/art_btc_whitepaper_b.kicad_mod`. Section 1 of
`bitcoin.pdf`, taken from the canonical file rather than typed from memory,
extracted with a purpose-written PDF text pass (zlib + `/ToUnicode` CMaps + a
text-matrix walk) and split at the paragraph break by **measured typeset width**
summed from the fonts' own `/Widths`, not by character count — section 1 is
justified and has no extra leading between its paragraphs, so a character count
mis-splits it. 1799 characters, 267 words, pure ASCII, so no glyph substitutions.
Section 2 was not needed: the shape was sized so section 1 exactly fills it.

Measured on the emitted part: **1712 glyphs in 88 `fp_text` runs**, 55 row bands
at 1.1044 mm pitch, 88 of 93 mask spans filled, shape 39.345 × 61.000 mm, block
opening 37.981 × 60.716 mm, 13,615 B, T2. The 87-character difference is
inter-word spaces consumed at span ends — integrity was proved by reading the
`.kicad_mod` back and rejoining the 88 runs to the source string exactly and in
order, not by trusting the in-memory report. **7/7 PASS** on `verify_art.py`
under kicad-cli 10.0.0, with `F.Cu` narrowest feature 0.100 mm — dead on the
floor. The mask is **one** opening over the whole block, never per glyph; the
mark is drawn by the copper.

### The smallest cap height is `floor / D`, and it needs a matching stroke ratio

Both constraints are linear in cap, so they cross: stroke-limited at
`cap ≥ floor/r`, counter-limited at `cap ≥ floor/(2D − r)`, equal at **r = D
exactly**, giving `cap = floor/D` as the global minimum over every stroke ratio.
The binding glyph was looked up in the text actually being set (36 distinct
characters) and is lowercase **`'e'`, D = 0.14744 em**, as the palette predicted.
So `0.100 / 0.14744 = 0.6782 mm`, a 1:6.782 ratio, inside the palette's 1:8–1:6
band. Verified empirically: **0.6782 mm is refused** (stroke 0.09999 mm) and
**0.6783 mm emits**, with stroke and counter both landing on 0.1000 mm.

This does not happen at the tool's default 1:6.7 ratio, and the distinction
matters for anyone reproducing the number: at the default the same body is
**counter**-limited and refused below **0.695 mm**. The part is emitted with
`--stroke-ratio 0.14744` — D passed as the ratio.

Legibility is the honest part. x-height at that cap is **0.452 mm**, roughly 2.5–3
pt. This is loupe text, which is what microprinting means. And the 0.100 mm floor
sits between vendor tiers: at r = D each tier's minimum cap is just `floor/D`, so
a **standard 5-mil fab cannot build this part** (needs 0.8614 mm), a 0.09 mm
advanced fab can (0.6104 mm), and at 0.075 mm capability fab stops binding and
legibility takes over at 0.600 mm. A coarser fab does not scale the mark by the
cap ratio — the flow re-breaks at every span, so the shape has to be re-sized and
the run repeated.

### The render driver was plotting with whatever `kicad-cli` was on PATH

`tools/board_render.py` recombines the plotted layers through this palette's own
decision tree, so a figure shows what the board will look like rather than
KiCad's editor colours. It was found resolving a bare `"kicad-cli"` from PATH —
which on this machine finds a distro **7.0.11** that cannot parse file format
20241229, and which had already silently rendered one microprint figure with
KiCad 7 stroke metrics. It now resolves through `verify_art.find_kicad_cli` with
a hard gate at major ≥ 10 and prints the version it chose.

The three figures in `docs/images/btc_whitepaper_b_*.png` were re-derived from the
committed part under **kicad-cli 10.0.0** and all three came back
**pixel-identical** to the files on disk, so their provenance is established
rather than assumed: no KiCad 7 plot survives in them. Each carries its own caveat on the image: `fp export svg`
emits nothing for `In1.Cu`, so T4 renders as T3 and T7 as T5.

### Not landing this pass

`tools/fab_profiles.py` — vendor geometry limits and per-mask-colour tone anchors
— is **held back**, not committed. It is imported by nothing and tested by
nothing; its `tone_anchors("black")` set disagrees with `w0_spike.TONES`, the
anchors this repo's quantiser and render driver actually use, giving
T6 − T5 = 4.0 L\* where the established set gives 7.9 and T4 (112, 102, 79)
against (170, 150, 105); and its own comment's tone-ordering table does not
reproduce from the code in the same file — for purple and for white-mask /
black-silk the computed order is the reverse of what the comment states. The one
finding worth keeping from it *is* kept, in the palette under **The tone anchors
are a BLACK-mask set**: on a light mask the ordering inverts, which the halftone
ramp's L\* gate does not handle, so issue **#1** needs a coupon per mask colour
rather than one coupon.

Nothing committed this pass either; all of it is in the working tree.

## 2026-08-20 — The spectre reaches the plane: it was a missing reflection

`SPECTRE_AUDITED_LEVEL = 5`. The substitution runs to arbitrary depth and level 5
— **34 649 tiles** — is audited pair by pair with exact integer predicates in
`Z[sqrt 3]`: zero overlapping pairs, zero proper edge crossings, zero
strictly-interior vertices, one boundary loop, no holes, no edge claimed by three
or more tiles, no tile a mirror image of any other. Level 6 (272 791 tiles) was
checked with the cheaper exact oracles and is clean too.

| lvl | tiles | candidate pairs | crossings | interior verts | overlapping pairs |
|----:|------:|----------------:|----------:|---------------:|------------------:|
| 0 | 1 | 0 | 0 | 0 | 0 |
| 1 | 9 | 21 | 0 | 0 | 0 |
| 2 | 71 | 209 | 0 | 0 | 0 |
| 3 | 559 | 1845 | 0 | 0 | 0 |
| 4 | 4401 | 15 339 | 0 | 0 | 0 |
| 5 | 34 649 | 124 201 | 0 | 0 | 0 |

Level 3 is the line that matters: it used to report **97 overlapping pairs, 128
proper edge crossings, 520 strictly-interior vertices, 25 edges shared by three
or more tiles and 7 boundary loops**.

### What was wrong

One line. This module built the substitution out of **rotations and translations
only**. The published substitution composes a **reflection** onto all eight slot
transforms at every generation — the paper says so in one sentence, *"the rules of
Figure 2.1 reverse all tile orientations"* — so successive levels alternate
handedness. Without it the anchor quad grew by exactly **3.0** per level where the
tile counts force `sqrt(4 + sqrt(15)) = 2.805884`; the eight children were pushed
6.9 % too far apart every level; level 2 came out as three disconnected lumps at
64 % hull fill, and level 3 self-overlapped.

Adding `z_conj()` — complex conjugation in `Z[d]`, which is exact and integral,
because conjugation permutes the twelfth roots of unity — and one composition
step is the entire fix.

### Why every previous search came back empty, correctly

The ledger recorded that all 32⁴ = 1 048 576 super-quad rules were swept with no
eigenvalue of modulus 2.805884, that 1794 re-derived chain descriptions all
failed the same test, and that the anchor quad is forced. **None of that is
retracted.** Every one of those was a search over *linear* quad maps. With a
reflection in the chain the one-step quad map is **anti-linear** — `z -> A·conj(z)
+ b` — and its growth lives in the eigenvalues of `A·conj(A)`, which no linear
eigenvalue sweep can see. The searches were sound; the framework they searched
was the defect.

### The nine labels were not the fix — a second honest negative result

Issue #8's hypothesis was that collapsing the nine metatile labels (Γ, Δ, Θ, Λ,
Ξ, Π, Σ, Φ, Ψ) into two was the defect, and that restoring them *each with its
own quad* was what would inflate correctly. It is wrong, and it is wrong for a
reason that can be read straight off the published table: every row places Γ at
slot 7 and nowhere else, and only Γ's row drops a slot, so by induction all eight
non-Γ supertiles are the **identical point set** at every level. Nine labels, two
geometries — exactly what the two-cluster code already had. The published system
also shares **one** quad across all nine labels.

Measured on both diagonals of the 2 × 2, same quad, same super-quad rule, same
chain rules:

| labels | reflection | level 2 | level 3 |
|---|---|---|---|
| nine | no | 9 overlapping pairs | 1908 overlapping pairs |
| nine | **yes** | 0 | 0 |
| two | **yes** | 0 | 0 |

Nine labels *without* the reflection are worse than two clusters without it were.
Two clusters *with* it are clean. The reflection is necessary and sufficient; the
labels are neither. They are implemented anyway — they are the published system,
they cost nothing, and they carry the hierarchy bookkeeping the aperiodicity
argument needs — but the ledger says what the measurement says.

One number in the earlier report is also corrected: the reflected quad growth was
described as "2.805884 from the first step, exactly". It **converges** —
2.827766, 2.808774, 2.806253, 2.805931, … → 2.805883701 — never more than 1 %
out. The rotation-only 3.0, by contrast, is exactly 3.0 from the second step on,
which is the tell that it is a different eigenvalue rather than a near miss.

### Five oracles, and a negative control

The failure mode being guarded against is *"a count-based check passed a broken
implementation for months"*, so nothing rests on tile counts. Levels were checked
with: the repo's exact predicates on doubled `Z[sqrt 3]` integers; a second exact
implementation written from scratch over `Fraction`-based `Q(sqrt 3)` with a
different in-polygon algorithm; an exact combinatorial census (every unit edge
claimed by at most two tiles, every lattice vertex carrying at most 360° of tile —
integer arithmetic, since all interior angles are multiples of 30°); shapely's
`unary_union`; and dense uniform point sampling.

All five were first pointed at the **known-broken** level 3 and all five fired:
97 / 97 overlapping pairs from the two exact ones, 55 vertices over 360° with a
worst of 720°, 201.7 mm² of area lost to overlap, 7248 doubly-covered sample
points. An oracle that cannot fail is not evidence. The angle census is now in
the module as `spectre_vertex_census()` — O(n), exact, and cheap enough to run at
level 6.

### What it buys the board

`spectre-fingerprint` used to refuse a 150 × 100 mm board at `--tile-mm 3`: 71
tiles could not span it, the smallest tile that would span was 11.674 mm, and at
that size six tiles survived the copper mask. That is why `spectre-cells` had to
exist. The mode now picks the shallowest level that **covers** the frame and puts
**1564 whole 3 mm tiles** on the same board, with no repetition and no rescaling.
Re-measured 2026-08-24 through `spectre_region_fill`, which is what fills a board
today; `spectre_fingerprint` refuses this frame rather than clamping to a level
that only spans it, so the figure quoted here is no longer reachable by that call.

Covers, not spans: a real spectre supertile is ragged — it fills 0.8146, 0.8040,
0.7076, 0.6510, 0.6266, 0.6177 of its convex hull at levels 0…5, converging to
about 0.61 — so a patch whose *bounding box* contains the frame can still leave
centimetre-wide bays of bare board inside it. Both the fingerprint and the
window-filling `spectre` kind now test containment in the patch's **boundary
polygon**. Before that, a 14 × 14 mm window at `--tile-mm 4` came back with a
hole in it.

The old supertile acceptance test — hull fill ≥ 0.75 — had to go for the same
reason: it was calibrated on a lone tile and a 9-tile cluster and it *rejects
correct objects*. It is replaced by what it was standing in for and what the old
level 2 actually failed: one boundary loop, no holes, no edge shared by three
tiles. `spectre-cells` keeps working, with a smaller cell — its pitch was
`15 + 13√3` and is now `27(1 + √3)/2` unit edges, because the corrected 71-tile
patch is one compact lump instead of three sprawling ones. Boards previously
generated with that kind will not reproduce bit-for-bit.

### Aperiodicity

The strict xfail `test_spectre_has_no_translational_symmetry` said *"a 9-tile
cluster is far too small to scan; needs a correct level 2"*. It is now a real
assertion on the 559-tile level-3 patch: hundreds of candidate translations, best
score 0.13, zero exact repeats, on a scan the periodic kinds are calibrated to
score exactly 1.0. Still evidence and not a proof — a finite patch cannot rule
out a symmetry of the infinite tiling — and the module still says so.

### Provenance

The rule table, chain rules, anchor quad, super-quad recursion and the reflection
are the published mathematics of Smith, Myers, Kaplan and Goodman-Strauss, *A
chiral aperiodic monotile* (arXiv:2305.17743, Combinatorial Theory 4(2), 2024),
implemented here from that mathematics. Kaplan's reference application was
consulted as an existence proof and a source of test vectors — to confirm the
nine-row table, and to measure that this module's vertex numbering is the
published one shifted by 12 and turned 30°, which is why `SPECTRE_QUAD_IDX` moved
from `(3, 7, 11, 13)` to `(5, 7, 9, 13)`. No source was copied from it.

Nothing committed this pass; all of it is in the working tree.

## 2026-08-21 — Filling a region: whole tiles to the perimeter, and what the cards can actually hold

The plane-tiling defect was fixed last pass. This pass turns it into the thing the
board owner asked for: *give me a region and a tile size, and fill it*. Step 1 of
his three-step pipeline — tile the plane, discard partials at the perimeter,
remove what the art cuts — was the one that did not exist. Steps 2 and 3 already
worked.

### The entry point

`spectre_region_fill(region, tile_mm, seed=0, keepouts=(), reject=None)` in
`tools/tilings.py`. `region` is a ring or a rect; it returns the tiles and a
ledger — `offered`, `dropped_partial`, `dropped_keepout`, `kept`, `coverage`.

Two things in it are worth stating rather than assuming.

**The region is a polygon, not a bounding box.** `spectre_fingerprint()` asks
whether the patch contains the frame's *rectangle*. A card is not a rectangle:
the alpha coupon's hexagonal corners stick 7.3 mm past its own flats, so asking
for the bounding box makes the deflation go a level deeper than the card needs,
and a level is a factor of 7.9 in tiles. `spectre_region_placement()` tests
containment of the outline itself, in the patch's own boundary polygon — the
raggedness matters and the bounding box still is not the test.

**`offered` means touching the region.** Counting every tile whose bounding box
met the region's bounding box reported 1205 offered and 443 partials on the alpha
hexagon at 3 mm, when only 905 tiles come near the card and only 143 are cut by
its outline. The ledger now closes: `offered = kept + dropped_partial +
dropped_keepout`.

`place="most-tiles"` is an opt-in second placement rule. Where the patch sits
under the outline is a free parameter — at 15 mm a 94 mm card is a speck inside a
level-3 patch — and it is worth a fifth of the field at that size: measured over
12 rotations and a 15×15 offset grid, alpha takes 19–21 whole tiles centred
against 24 at the best offset at 15 mm, and 757–765 against 770 at 3 mm. It is
not the default because the default has to be restatable in one sentence.

### The answer to the target: 3 mm on one face, 15 mm on the other

Face area is the outline less the 0.5 mm copper-to-edge inset, less the routed
ASIC cutout: **alpha 7348.2 mm², beta 7563.2 mm²**. FIELD is the tiling alone;
ART is what survives the card's own copper, mask, silk, buried copper and cutout,
each grown by the 0.55 mm add-mode clearance.

FIELD % / ART %, tiles in brackets. The rotation is the one each face already
uses, which is why the two beta faces have different FIELD numbers.

| tile | alpha front | alpha back | beta front | beta back |
|---|---|---|---|---|
| 15 mm | 55.1 / **0.0** (18 → 0) | 55.1 / **6.1** (18 → 2) | 62.5 / **3.0** (21 → 1) | 53.6 / **0.0** (18 → 0) |
| 9 mm | 71.7 / 1.1 (65 → 1) | 71.7 / 27.6 (65 → 25) | 75.0 / 9.6 (70 → 9) | 73.9 / 16.1 (69 → 15) |
| 6 mm | 78.4 / 7.8 (160 → 16) | 78.4 / 43.6 (160 → 89) | 84.3 / 18.6 (177 → 39) | 82.4 / 29.0 (173 → 61) |
| 3 mm | 89.9 / **22.9** (734 → 187) | 89.9 / **62.0** (734 → 506) | 90.8 / **30.8** (763 → 259) | 90.8 / **50.8** (763 → 427) |

Today's cards carry one 71-tile level-2 patch per face: 3.13 % and 15.85 % on
alpha, 6.84 % and 15.40 % on beta, measured the same way. With
`place="most-tiles"` the 3 mm faces go to 24.3 % and the 15 mm backs to 9.2 %
(alpha) and 3.0 % (beta) — the placement search maximises whole tiles in the
*region*, so it can trade a tile away against the art, and beta's front loses
four (259 → 255) that way.

The sanity check the brief supplied holds, once one number in it is corrected: a
hexagon of 94 mm across flats is `√3/2 × 94²` = **7652 mm²**, not 8844 — 8844 is
94², which is the bounding box's own scale and 15.5 % too big. Perfect packing at
15 mm is therefore ~33 tiles, not 39, against 18 realised; at 3 mm, 850, against
905 offered and 734 kept; and 6 mm lands on 160–177 tiles, which is the ~200
legible tiles of the owner's reference image.

**15 mm is too bold for these cards, and the reason is not coverage.** The field
itself is fine — 55–62 % of the face, the rest being the whole-tile rim, which at
a 21.5 × 16.9 mm tile is up to 21 mm deep and cannot be otherwise. What kills it
is the *art*: the four lines of marking text on each back run the width of the
card, and a 21 mm tile cannot get between them. Alpha's back keeps 2 tiles of 18;
beta's keeps none of 18. At 6 mm the same faces keep 89 and 61.

### Verification of the emitted field

Every claim measured on the emitted millimetre rings, not on the ring algebra
that produced them. At the two target sizes, on all four faces: **0 overlapping
pairs** (of 2 524–2 683 tested), 0 duplicates, **0 reflected**, **0 not congruent
to Tile(1,1)**, 0 tiles outside the region, every tile exactly `tile_mm²`. The
congruence test is rebuilt from the reference tile's edge lengths and turn angles
in float millimetres with an independent in-polygon test, so it catches a clipped
tile, a mirrored tile and a rescaled one with one measurement.

`gap_audit` on the field with no keepouts: **one boundary loop, no holes, no
broken chains** on every face and size. That is the exact half of "reaches the
perimeter". The visible half is a raster: uncovered 629 mm² on alpha at 3 mm, none
of it more than **4.78 mm** from the outline — 1.6 tile widths — and **zero bays**
deeper than two tiles. Beta: 679 mm², 4.88 mm, zero bays. The one deep pocket
anywhere is alpha's ASIC cutout, which is a hole in the card.

The depth test needed a fix of its own: without padding the raster,
`distance_transform_edt` measures to the nearest zero pixel *inside the array*, so
a region touching the border borrows a depth from the far side of the shape — the
4 mm strip along the hexagon's bottom flat came back as a 27 mm bay.

**No periodicity.** The blind scan is exhaustive over translations, because a
symmetry must carry one chosen centre onto another: alpha 3 mm best score 0.7306
over 671 candidates, beta 0.7784 over 449, **zero exact repeats** on either. A hex
lattice filled into the same region at the same size scores **1.0000 with 384
exact repeats** on beta. On alpha the same control tops out at 0.9860, because the
scan erodes a rectangle out of the centre and a hexagon leaves that rectangle's
corners empty — the control has to be run on the card's own shape or it credits
the spectre for the shape of the card.

### Two things found on the cards

**`build_coupons.py` cannot rebuild.** Its `patch()` calls
`T.spectre_fingerprint(frame, tile_mm, seed=turn)` with the level-2 patch's own
bounding box as the frame and asserts 71 tiles. Since `SPECTRE_PATCH_LEVEL`
became 5 the level search runs, the level-2 boundary cannot contain its own
bounding box, and the call now returns **153 rings from level 5**. The fix is
`levels=2` in that one call. Not made here — the coupons were not to be rebuilt
this pass.

**An ink-derived keepout cannot see a patch defined by the absence of ink.** T5
is bare board and draws nothing, by definition. Measured: one 3 mm tile lands
inside beta's T5 tone patch. Alpha's T5 cell survives only because the T6 and T7
cells beside it and the silk frame around it are ink. Those patches need
declaring as keepouts, not deriving. Both cards' silkscreen also states "spectre
L2 · 71 tiles · tile 4.05 mm", which is a marking that would have to change.

Renders of all four faces at 3/6/9/15 mm are in the scratch bench, not the repo.
Nothing committed this pass; all of it is in the working tree.


## 2026-08-21 — The sizing solve, and the word that was hardest to break

Two changes to `tools/microtext.py`, and the first one is why the second one was
worth having. Nothing committed; nothing rebuilt.

### The hyphen was four defects, not a missing feature

The flow split the body on whitespace only, so `peer-to-peer` — the word with
the most built-in break points in the whitepaper's opening sentence — was one
atomic 12-character unit and the **hardest word in the text to place**. When it
fitted no span it jammed every span after it, because the flow never skips a
word.

`--shape-hyphenate` searched for a break position `k` and emitted `w[:k] + "-"`.
For `peer-to-peer` at `hyphen_min` 3 that runs k = 9..3:

| k | head | tail | what it does |
|---|---|---|---|
| 8 | `peer-to--` | `peer` | doubles a hyphen the author wrote |
| 7 | `peer-to-` | `-peer` | inserts one where the author already had one |
| 5 | `peer--` | `to-peer` | doubles it again |

and `hyphen_min` compounded it: the natural segment `to` is two letters, so even
a correct "break at the author's hyphen" would have refused that break — a rule
about how much of a *word* to leave on a line, applied where nothing is inserted
and no word is divided.

A **fourth** defect turned up when the recovery walk was pointed at the legacy
loop: it put an unplaceable carried fragment back into `tail` and then went on
filling the span from `words[wi]`, which is the text *after* the fragment. So
the board carried a later word first. Reproduced exactly, on a three-band mask:

    legacy  ['Int-', 'has', 'ernet', 'come to']     board reads "Int-hasernet..."
    now     ['Int-', 'ernet', 'has', 'come to']

Both flows are in `tests/test_microtext.py`: `legacy_flow()` is the pre-repair
walk spliced back in verbatim, so every "it used to do X" here is an assertion
about a runnable object. **Eight of the new tests fail against it and pass
against the repair.**

### The fix, and what existing-hyphen breaking recovers on its own

The body is now split at its existing hyphens **always** — independent of
`--shape-hyphenate`, independent of `hyphen_min` — into pieces that each carry
the hyphen that ends them. `peer-to-peer` is `["peer-", "to-", "peer"]` and
`"".join()` is the word, character for character. Breaking between them is
ordinary typesetting. Algorithmic hyphenation is what is left over: only for a
piece still too wide on its own, still behind the flag.

Measured on `examples/bitcoin_b.svg` element 2 at the `jlcpcb-4l-fine` floor cap
of 0.790 mm, 1:8 stroke, 1/21 em tracking, **with `--shape-hyphenate` OFF**:

| art | before | after | recovered |
|---|---|---|---|
| B 63.5 mm, Abstract+Intro | 1053 chars, 33/51 bands | **1319, 46/51** | +266 chars, +13 bands |
| B 76.2 mm, Abstract+Intro | 1934, 54/61 | **2023, 58/61** | +89, +4 |
| B 30.0 mm, Abstract | 68, 6/19 | **106, 11/19** | +38, +5 |
| B 40.0 mm cap 2.0, Abstract | 9, 2/13 | **22, 4/13** | +13, +2 |

The last row is the case the owner found: nine glyphs from the entire Abstract.
None of that recovery changes a character of the text.

### The flag stays OFF, and now there is a number for it

It is worth **0.0%–11.7%** of capacity after the repair (63.5 mm: 6.5%;
76.2 mm: 3.4%), against the ~25% that existing-hyphen breaking now delivers for
free. But the argument is not the percentage. The algorithm breaks on **width,
not syllables**, and this is what it does to the whitepaper:

    contro-lled   unavoidab-le.   netwo-rk,   weaknes-ses   transact-ions,
    instituti-ons   tru-sted   prop-ose   anot-her   Int-ernet

Those are not hyphenations a reader would accept; they are misspellings in two
pieces, at a size nobody proof-reads. And at the art size that actually holds
the text the owner wants — 90.4 mm, below — the flag buys **0.0%** and the mark
fills every band without it. It only matters when the art is too small for the
text, which is a sizing problem, and sizing now has its own answer.

Every inserted hyphen is recorded by word, warned about, and counted; a break at
an existing hyphen is counted too and explicitly **not** disclosed as an
alteration, because it is not one.

### Capacity is exact, and the verdict comes before the flow

`check()` now measures the shape's **character capacity** and reports the
verdict at the top of the report; an overfilling body is refused there rather
than after the work. The number is not an estimate. The flow is causal, so
running it over the body repeated until the art overflows gives the longest
prefix of that prose the art takes, character for character — verified by
cutting the body to exactly that length and re-flowing it. `FlowSpan.consumed`
records the prefix boundary at every span, and `_flow()` asserts the running
count and the leftover text add up to the body. Capacity costs 10–75 ms.

Capacity is **not** a property of the shape alone: the same 2.5 in B at the same
cap holds 1404 characters of the Abstract and 1319 of Abstract+Introduction,
because greedy wrapping turns on where the word boundaries fall.

`solve()` exposes the same arithmetic with nothing emitted — `--solve` on the
command line, the unknown being whichever of `--shape-height` / `--height` /
`--text` is left out:

    art + cap        -> characters it holds, and the shortest text that fills it
    cap + characters -> how big the art has to be
    art + characters -> the largest cap the text survives

Every answer is bisected on measured flows, snapped to a grid (0.05 mm art,
0.005 mm cap), and then **re-run at the value printed**. The three directions
close on each other: 63.5 mm + 0.79 mm gives 1319 characters; 1319 characters at
0.79 mm gives 63.25 mm, which is the smallest size that holds them.

### The owner's case: a 2.5 in B, Abstract + Introduction, at the floor

**It does not fit, and no cap height makes it fit.** The floor cap for this body
at 1:8 with 1/21 em tracking on `jlcpcb-4l-fine` is 0.790 mm, and a 63.5 mm B
holds **1319** characters of that prose. The text is 2923. Two numbers:

- **grow the art to 90.40 mm** (58.31 × 90.40 mm, 3.56 in) — capacity 2925,
  2 characters of slack, and full anywhere from 2916 characters up; verified
  by re-running the flow on the real body at that size;
- or **cut exactly 1604 characters** (237 words) from the end.

A finer cap is not on the table: 0.790 mm *is* the floor, limited by the `i`'s
own stem-to-tittle gap against 0.0889 mm. What a 2.5 in B does hold at that cap
is the **Abstract alone** (1120 chars against 1404 of capacity, 10 bands blank —
it underfills) or about 1319 characters of the two together.

So the tool now recommends, rather than only reporting. **Overfill: grow the
art.** It is the only one of the three fixes that neither walks the letterforms
toward the process floor nor deletes a word. **Underfill: raise the cap.** It
moves every stroke and counter *away* from the floor, so the part gets easier to
build, and it leaves the art footprint the board already committed to alone.
Both remedies are computed and both are verified by re-running the flow.

### Nothing is altered without saying so, and it is provable

`recover_text()` walks the strings that will be fabricated back against the
source in reading order and allows exactly two differences: an inter-word space
the flow consumed at a span end, and an inserted hyphen **that was declared**.
`place()` runs it and **refuses the part** if it does not close. So a break at an
existing hyphen has to round-trip with no allowance at all — measured on the B at
63.5 and 76.2 mm, it does — while an inserted one fails unless it is in the
report. Fed the old worked example, board `for` / `non-rever-` against source
`for non-reversible payments`, it returns ok False with nothing declared and
truncated 14 with one declared. Neither is a pass. Run against the legacy walk,
the emit path now refuses outright: *"the text on the board does not walk back to
the source: 3 inserted hyphen(s) on the board, 0 declared."*
