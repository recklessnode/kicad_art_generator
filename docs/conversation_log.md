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
| kicad10 | which `fp_*` primitives KiCad 10.0.5 supports, whether `fp_poly` takes curves, whether `kicad-cli` gained image import, whether "fixed size" is still a real constraint |
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
