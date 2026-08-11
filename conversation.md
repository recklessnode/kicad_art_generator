# Engineering log

Running record of work on this repo: what was done, **why**, the evidence
behind it, and what turned out to be wrong. `docs/conversation_log.md` is the
terse release-note history; this is the reasoning.

> **This file is committed.** The sibling convention in `mujina` keeps its
> `conversation.md` local-only because that repo's origin is public and the work
> touches NDA material. Nothing here is NDA — it is image processing and KiCad
> file formats — and this repo is already public, so the log lives in it.

---

## 2026-08-11 06:31 UTC — Audit and redesign kicked off

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
   (silkscreen, copper trace, bare substrate, mask-removed copper, and possibly
   buried inner-layer copper), and the mapping onto them is not good.
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

**Survey — 4 parallel, each required to run things rather than read them:**

| probe | question |
|---|---|
| code | how colour mapping actually works, and measured byte/primitive counts from a real generation run |
| kicad10 | which `fp_*` primitives KiCad 10.0.5 supports, whether `fp_poly` takes curves, whether `kicad-cli` gained image import, whether "fixed size" is still a real constraint |
| palette | the 8 copper/mask/silk combinations, which are visually distinct, sRGB per finish, and the right quantisation approach |
| geometry | contour-trace + simplify vs potrace vs rectangles, with a prototype run for real vertex counts and file sizes |

**Design — 3 parallel, deliberately opposed angles** (minimal-change, clean
rebuild, fabrication-first) so they do not converge prematurely.

**Judge — 1, Opus, high effort.** Required to name where the surveys and
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
(`Blockscale-Solutions/SatoshiStarter`, `.github/workflows/pcb-checks.yml`). Art
placed on `F.Cu` is real copper and will trip DRC clearance and
unconnected-island checks, and rule `R3` would read an art-only layer as
carrying zero track segments.

The fix belongs here, not there: **art footprints should be designed to be
excludable by construction** — a naming convention or a dedicated group the
rules can skip — rather than the board repo accumulating exclusions after the
fact. Folded into the implementation brief as a design input.

### Status

Workflow `wf_ad1b3e5c-79d` running. Results and the decision to follow in the
next entry.

## 2026-08-11 07:0x UTC — Correction: buried inner-layer copper is a real tone

The brief I wrote for the palette survey said of buried traces: *"Assess whether
inner-layer copper is actually visible through FR4 ... Be honest if this is
marginal."* That framing was wrong, and the owner corrected it with a physical
sample.

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
than the eight front-side copper/mask/silk combinations I had assumed. Inner
layers participate, which means the tool is not choosing among ~5 tones but
something closer to a two-dimensional space of surface state x buried state.

The practical limit is edge sharpness rather than availability: a buried tone
is a diffuse shadow through 0.1 mm of dielectric, so its edges blur relative to
a silkscreen or copper edge. Minimum feature size for a buried tone is
therefore larger than for the surface layers, and that constraint — not
whether the tone exists — is what should bound its use.

**Process note.** Caught this while the workflow was still in its survey phase,
before any design proposal or the Opus judgement had started. Stopped the run,
rewrote the palette brief to treat buried tones as settled and to characterise
rather than assess them, and resumed — the three unaffected survey agents cache
on their unchanged prompts, so only the palette probe re-ran.

Had it landed later, a wrong "buried traces are marginal" premise would have
propagated through three design proposals and the synthesis. Worth recording as
the general point: an assumption embedded in a brief is more expensive than an
assumption embedded in code, because every downstream agent inherits it without
re-deriving it.
