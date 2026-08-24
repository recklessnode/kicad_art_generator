#!/usr/bin/env python3
"""Board-in, board-out decorative texture for an existing copper pour.

    python tools/texture_board.py --board IN.kicad_pcb --side front|back|both \
           --tiling spectre|hex|checker --tile-mm N --slot-mm W --out OUT.kicad_pcb

Both halves are here. PART 1 is the board ingest: it answers "where is texture
allowed?" and nothing else, returning per copper layer a polygon set inside which
a tile may be placed. `--report` runs it alone. PART 2 places tiles from
tools/tilings.py inside that region, cuts their walls as slots with a tie-neck in
every wall, emits the slots as board-level rule areas, refills, and then proves
the copper is still one region per component by an independent raster flood fill.
Giving --tiling or --out selects part 2.

MEASURED ON SatoshiStarter @ 0694274 -- hex, tile 3.00 mm, slot 0.25 mm, neck
0.40 mm, square caps, midedge necks, F.Cu + B.Cu:

  122 tiles placed (44 F.Cu, 78 B.Cu), 490 dropped for touching an obstacle
  346 keepout zones; refill of the textured board 1.13 s (1.13 s untextured)
  copper removed 3.51% of the F.Cu pour, 7.67% of the B.Cu pour
  copper the filler dropped as an island: 0.000 mm2 on both layers
  fill components before -> after: F.Cu 4 -> 4, B.Cu 3 -> 3, and every
    component but the one the slots were cut into is unchanged to 1e-9 mm2
  DRC 206 warnings / 0 errors, identical to the untextured control by type
    and severity -- the texture added nothing

THREE THINGS MEASUREMENT OVERTURNED, each of which had already been coded the
wrong way round:

  1. A round slot cap overhangs its cut endpoint by slot_mm/2, so --neck-mm 0.40
     with a 0.25 mm round-capped slot leaves 0.15 mm of copper, below the pour's
     0.25 mm min_thickness. The filler deleted every neck, then every cell:
     355.7 mm2 gone, hexagonal bites in the pour edge. --neck-mm now means the
     copper that SURVIVES; see cap_extend_mm().
  2. An acyclic wall set does NOT guarantee connected copper. The copper is a
     bounded region, not the plane, and a slot chain reaching its boundary twice
     severs it. --neck-style forest is a provable spanning tree and still
     isolated 21.0 mm2 at the pour's east edge. A neck in EVERY wall is what
     makes the guarantee shape-independent. See the PART 2 banner.
  3. The flood-fill raster window has to cover the whole POUR, not the permitted
     region. Sizing it to the permitted region cropped the pour and reported
     F.Cu as 3 components of 765.814 mm2 instead of 4 of 1562.485.


WHY THIS IS BOARD-LEVEL GEOMETRY AND NOT A FOOTPRINT
----------------------------------------------------
A footprint-borne copper keepout is SILENTLY IGNORED by the KiCad 10 zone
filler. Measured this session: the gerber produced with the footprint keepout
present is byte-identical to the gerber produced with no keepout at all. Only
board-level keepouts bite. So the texture has to be board geometry, and this
ingest therefore reasons in board coordinates throughout -- there is no
footprint-local frame anywhere below.


ZONE FILLS ARE STALE UNTIL REFILLED, AND NeedRefill() WILL NOT TELL YOU
-----------------------------------------------------------------------
The filled polygons stored in a .kicad_pcb are whatever the last fill left
behind; editing tracks does not invalidate them on disk. Every area this module
reports comes from `zone.GetFilledPolysList(layer)`, so a stale board yields a
confidently wrong answer with no symptom.

The obvious guard does not work. `ZONE::NeedRefill()` is an in-session dirty
flag and is not persisted: measured on both a never-refilled copy of this board
and a `kicad-cli pcb drc --refill-zones --save-board` copy of it, NeedRefill()
answers False for all 15 zones in both cases. A check built on it would pass
every stale board on earth.

So ingest does not check -- it REFILLS, in process, via `pcbnew.ZONE_FILLER`,
before measuring anything. 1.2 s for this board. `--no-refill` opts out and
measures the file as-is; `--report` then prints the per-layer area delta the
refill produced, which is the only honest staleness indicator available. For
SatoshiStarter at 0694274 the deltas are -0.17 mm2 on F.Cu, -0.05 on In1.Cu,
-0.13 on B.Cu and 0.00 on In2.Cu -- i.e. Clipper rounding noise, so the board's
stored fills were already current and every figure below is refill-insensitive.


BOARD-FIRST FRAMING, AND THE FINGERPRINT
----------------------------------------
Part 2 used to hand tilings.generate() the bbox of THIS LAYER's permitted region.
That is the right window for a lattice, whose anchor depends only on the seed,
and the wrong one for anything else: the bbox moves whenever the copper moves, so
F.Cu and B.Cu get different windows, and a pattern whose placement depends on the
window size lands somewhere new every time a component is nudged. Nothing can be
compared to anything.

`--tiling spectre-fingerprint` is board-first instead. The frame is the board
outline deflated by --edge-inset -- ONE rectangle for the whole run, computed
before any layer is looked at -- and the level-2 spectre patch (71 tiles) is
centred on it, with --seed choosing one of twelve rotations and nothing else. The
generated field is therefore a function of (board outline, tile_mm, seed) alone.
What is specific to this board is which tiles SURVIVE the copper mask, and that
is the fingerprint. `--tile-frame board|permitted` overrides the choice for any
kind; `auto` (the default) keeps every documented lattice run byte-identical.

MEASURED on SatoshiStarter @ 0694274, add mode, tile 11.6743 mm, seed 10:

  frame 51.80,26.40..202.20,126.00 = 150.40 x 99.60 mm, identical on both layers
  71 tiles offered, 18 hang over the board edge, 53 in frame
  F.Cu 6 placed / 47 masked, 775.3 mm2 of copper laid (9.0% of permitted)
  B.Cu 4 placed / 49 masked, 516.9 mm2 (5.7%)
  fill symmetric difference 0.000e+00 mm2 on both layers, components 4 -> 4 and
    3 -> 3, every component area identical pixel for pixel
  DRC 206 warnings / 0 errors / 0 unconnected -- identical to the untextured
    control by type and severity

  moving H2 by 4.000 mm: F.Cu 6 -> 7 placed, B.Cu 4 -> 5, on a field whose 71
    rings are bit-identical (worst vertex displacement 0.000e+00 mm). That is
    the fingerprint property, measured rather than asserted.

THE PART THAT USED TO BE BAD NEWS, and what changed. The patch must SPAN the
board -- a repeated patch is periodic at the patch pitch and throws away the only
reason to use a spectre -- and when 71 tiles was every tile tilings.py had, that
forced tile_mm >= 11.674 on a 150 x 99 mm board, i.e. a tile 16.7 mm across. At
that size:

  * subtract mode placed NOTHING at any legal tile size (its permitted region is
    694 mm2 on F.Cu in 4 fragments; no whole 11.7 mm spectre tile fits any of
    them), measured at 11.674, 12, 12.5, 13, 13.1, 14, 16 and 20 mm;
  * add mode placed 1 to 6 tiles per layer depending on seed;
  * at tile 3.0 mm the run REFUSED, because spanning needed level 4 and level 3
    was not constructible -- it self-overlapped in 97 pairs.

The spectre substitution in tilings.py has since been corrected (it was missing
the per-generation reflection) and now runs to level 5, 34649 tiles, audited.
spectre_fingerprint asks the shallowest level whose BOUNDARY POLYGON contains
the frame -- covers, not spans: the bounding box is not a coverage test for a
patch this ragged. A LEVEL-5 PATCH AT tile_mm 3.0 PUTS THIS MANY TILES IN THIS
REPO'S TWO CANDIDATE FRAMES, at rotation 0:

  * board outline deflated 1.0 mm, 150.4 x 99.6 mm: 1778 tiles reach the frame,
    1552 are entirely inside it;
  * board outline deflated 0.5 mm, 151.4 x 100.6 mm: 1805 reach it, 1582 inside.

No repetition and no rescaling: the mode is a texture again rather than a
large-format medallion.

BUT THOSE ARE PINNED NUMBERS -- levels=5 -- AND AT tile_mm 3.0, SEED 0, THE AUTO
RULE REFUSES BOTH FRAMES. Read that before quoting the counts. An earlier draft
of this paragraph said the auto rule "picks the shallowest level that COVERS the
frame ... and at tile_mm 3.0 that is level 5 ... for both of this repo's
candidate frames". The counts were right; that sentence was not. What is
measured, at rotation 0, tile_mm 3.0, the patch centred on the frame:

  * level 4 SPANS both frames -- its bbox is 318.054 x 322.978 mm -- and its
    boundary misses 2295.021 mm2 of the 1.0 mm frame in 2 components (1615.385
    and 679.636) and 2373.657 mm2 of the 0.5 mm frame in 2 components (1664.932
    and 708.725). So "level 4 leaves two bays" is confirmed as a COUNT for both
    frames; "several hundred mm2", said of the pair, understates the larger by
    a factor of three.
  * level 5 spans both frames AND STILL DOES NOT COVER EITHER: 3.687 mm2 in 2
    components (3.414, 0.273) of the 14979.840 mm2 frame, and 6.098 mm2 in ONE
    component of the 15230.840 mm2 frame. 0.025% and 0.040%.
  * so the coverage search returns None, and it did not "pick 5". The old code
    returned 5 because spectre_fingerprint_placement() seeded its answer with
    SPECTRE_PATCH_LEVEL before searching and could not tell a search that fell
    through from a search that succeeded. That clamp is fixed: the auto rule now
    raises SpectreCoverageError with reason="cover".

Areas above are measured twice -- by tilings._ring_contains_rect for the
yes/no and by shapely 2.1.2 boolean difference on the same boundary ring for the
areas -- and the two agree on every case.

THE MECHANISM IS ESTABLISHED ONLY THIS FAR, and the rest is not asserted here.
Every uncovered component at BOTH levels touches the frame's own edge -- the
level-5 ones the bottom edge, the level-4 ones the top-and-right and top-and-
left corners. None is an enclosed interior bay. The earlier "bays of bare board
INSIDE it" is wrong in that respect too: they are edge notches, and what the
whole-tile rule does with the frame perimeter is drop it anyway. Whether the
coverage test SHOULD distinguish an edge notch from an enclosed bay is an open
question and this module does not answer it: the test is containment,
containment fails, and the rule refuses. Why the boundary notches at rotations
0, 3, 6 and 9 and not at the other eight is NOT established, and is not guessed
at here.

WHAT TO DO WHEN IT REFUSES, all measured on the 150.4 x 99.6 mm frame:

  * raise --tile-mm to 3.086404 (3.117392 for the 0.5 mm inset frame). The
    threshold is 2.9% away, not a level away, and the refusal quotes it --
    spectre_cover_tile_mm() is where it comes from. At the threshold the auto
    rule resolves to level 5 with no pin and places 1467 tiles.
  * or change the seed. Coverage is rotation-dependent: at tile_mm 3.0 level 5
    covers this frame at 8 of the 12 turns and fails at turns 0, 3, 6 and 9.
    seed % 12 is the turn, so seed 1 covers and places 1565.
  * or pass levels=5 and own the notches, which is what the counts above do.

Do NOT read a coverage refusal's min_tile_mm as a span number. They are not
close: the same frame and level SPAN at 0.561439 mm and COVER at 3.086404 mm,
5.5x apart, and acting on the span number leaves you still refused. The
exception carries reason="span" or reason="cover" to tell them apart.

(An earlier draft also said "a 4401-tile level-4 patch of which 1331 are
entirely inside the frame". That tile count and level are what the bbox test picked
before a coverage test replaced it; 1331 was measured on nothing at all.)

WHOLE TILES ONLY -- WHAT THIS HALF OWES PART 2
----------------------------------------------
A tile is either entirely inside the permitted region or it is dropped. There is
no clipping and no partial tile. That rule is what makes the permitted region
the ONLY contract between the halves: part 2 never needs to consult the board
again, it just asks "does this tile's polygon sit wholly inside permitted?".
Consequently every clearance must already be baked into the region returned
here. A region handed over with the clearance still to be applied would push
that reasoning into part 2 and the rule would leak.


REAL GEOMETRY, NOT S-EXPRESSION PARSING
---------------------------------------
This module runs under KiCad's bundled Python and uses pcbnew. That is a hard
requirement for correctness, not a convenience:

  - `zone.GetFilledPolysList()` gives the ACTUAL fill, with its thermal reliefs,
    its clearance voids and its dropped islands already resolved. Re-deriving
    that from the s-expression means reimplementing the zone filler.
  - `pad.TransformShapeToPolygon()` handles roundrect / oval / trapezoid /
    custom pads, pad rotation, and solder-mask-relative sizing.
  - `footprint.GetCourtyard()` returns the courtyard as a closed polygon with
    arcs already flattened.

There is a second, sharper reason to avoid the text form. KiCad 10 writes nets
on segments, zones and pads as `(net "Name")` STRINGS -- there is no numeric net
id any more. A regex written against the old `(net 12)` form matches nothing at
all and does so silently, so a text parser that "works" can be selecting an
empty set of obstacles and reporting a huge permitted area. pcbnew sidesteps the
whole class of bug: netnames come from `GetNetname()`.

Invoke as:  "C:/Program Files/KiCad/10.0/bin/python.exe" tools/texture_board.py
(on Linux: /usr/lib/kicad/bin/python, or the system python if pcbnew is on the
path). The pure-geometry helpers below import without pcbnew so they stay
testable in the project's own environment.


WHAT GETS SUBTRACTED, AND WHY EACH ONE
--------------------------------------
Ingest starts from the pour and removes, each with its own clearance knob:

  the pour itself is the base      no pour on a layer means no texture there.
                                   Slots are cut INTO copper; there is nothing
                                   to cut into otherwise.
  other-net zone fills             a slot must not bridge two nets, and the
                                   inter-zone gap is already thin.
  pads, tracks, vias on the layer   --clr-pad / --clr-track / --clr-via
  pad and via holes                 a drill punches every layer, so holes are
                                   subtracted on all layers regardless of which
                                   layer the pad's copper is on.
  courtyards on the side            --clr-courtyard. Side-level, not per-layer:
                                   a component body sits over both its own
                                   surface layer and the inner layer beneath.
  pad bboxes for parts with no
  courtyard (Q1-Q4 on this board)   same knob; see COURTYARD FALLBACK below.
  the HS1 true envelope             see HS1 below. --hs1-sides, front by default.
  the VRM->ASIC return corridor     see RETURN CURRENT below.
  the board edge                    --edge-inset, applied as an intersection
                                   with the deflated board outline.
  user rectangles                   --exclude X0,Y0,X1,Y1 (repeatable).


HS1 IS MIS-MODELLED AND THE FOOTPRINT CANNOT BE TRUSTED (defect #55)
--------------------------------------------------------------------
`local:HT_SoloSatoshi_40mm` draws only its four M3 standoff bosses on
F.Courtyard -- 176.2 mm2 measured, against a 40.16 x 40.16 mm heatsink body.
The body outline is drawn on B.Silkscreen, which is the WRONG SIDE. The
consequence is specific and dangerous for this tool: the front centre of the
board reads as EMPTY to every geometric query, including
`footprint.GetCourtyard(F_CrtYd)` used above, while physically being underneath
a heatsink and a fan.

So the envelope is hard-coded from measurement rather than read from the
footprint: x 72.22..119.78, y 52.42..99.97, i.e. 47.56 x 47.55 mm. The spurious
40 mm silk rectangle on the back at x 75.92..116.08, y 56.12..96.28 is NOT an
obstacle and is ignored. Both are exposed as constants so that fixing defect #55
upstream is a one-line deletion here, not an archaeology exercise.


RETURN CURRENT FOLLOWS ITS SIGNAL, NOT THE SHORTEST DC PATH
-----------------------------------------------------------
A slot that CROSSES a return path forces the return to detour around it, and the
detour adds loop area. This makes slot LENGTH and ORIENTATION matter far more
than slot width -- a long slot lying across the corridor is bad in a way that
the same area of copper removed as scattered dots is not. Ingest cannot see
orientation (it hands over a region, not tiles), so it takes the blunt and safe
option: the whole corridor is removed from the permitted region and no tile can
land there at any orientation.

The corridor that matters on this board is VRM -> ASIC: L1 at (151.5, 75.5) to
U9 at (100.0, 72.5), 51.6 mm, carrying the 28-32 A VCORE return on a net with
only 14 vias board-wide. Fourteen vias for 30 A means the return has almost no
freedom to change layers, so an obstruction cannot be routed around cheaply.

THE 6 mm BAND WOULD HAVE BEEN A NO-OP, AND MEASURING IS THE ONLY WAY TO KNOW.
The corridor centreline does not run over ground copper at all. Measured, per
layer, mm2 of the GNDREF pour that a band of the given half-width removes:

    half-w   band area     F.Cu   In1.Cu     B.Cu
      3 mm     309.6        0.0      0.0      0.0
      6 mm     619.2        0.0      0.0      0.0      <-- the obvious default
      9 mm     928.7       62.1     62.1     44.5
     12 mm    1238.2      205.5    205.5    172.8      <-- the default chosen
     15 mm    1547.8      356.4    356.4    318.9
     18 mm    1857.3      503.3    503.3    464.2
     25 mm    2579.6      803.4    803.4    762.8

Zero, twice. The reason is that /ASIC/VCORE owns the centreline on every layer
that has copper there -- the band of half-width 6 mm lands 504.9 mm2 inside the
F.Cu VCORE pour, 524.6 inside In1.Cu's and 519.7 inside B.Cu's, and 0.0 inside
any GNDREF pour. In2.Cu has no plane at all under the corridor, only a 36.5 mm2
VDDINT island. So on this board there IS no ground plane directly beneath the
VCORE run: the return has to flow LATERALLY, through the GNDREF copper flanking
the VCORE pour above (y 60.1..64.2) and below it (y 89.0..98.0).

That flanking copper is what a GNDREF texture would damage, and reaching it
needs half-width >= ~8 mm. The default is therefore 12.0 mm, which covers both
flanking bands over the run's x extent and costs 12.1% of the F.Cu pour. A
6 mm band would have looked like a working guard in every report while
protecting nothing -- the same silent-empty-set failure as a `(net 12)` regex
against KiCad 10. Ingest now WARNS whenever the corridor removes 0 mm2 from a
layer's pour and names the net that actually owns the corridor copper there.

When the textured net is VCORE itself (--pour-net /ASIC/VCORE) the centreline
band is the correct guard, because then the forward 28-32 A path is what is
being cut, and a 6 mm band does bite.

Removing a mesh costs ~12-15% of the copper for any sensible pitch/width ratio,
which is a plane-resistance argument for keeping the corridor clear as well.


COURTYARD FALLBACK
------------------
Q1-Q4 have no courtyard on either layer. `GetCourtyard()` returns an empty
polygon set for them, which is indistinguishable from "no component here". The
fallback is the union of the footprint's PAD bounding boxes, not
`GetBoundingHull()` -- the hull includes silkscreen and reference text and would
swallow far more board than the part occupies. Every footprint that falls back
is named in the report, so a silent fallback on some future part is visible.


TWO SHAPE_POLY_SET REPRESENTATION TRAPS, BOTH MEASURED HERE
-----------------------------------------------------------
A SHAPE_POLY_SET holds the same region in either of two forms, and several of its
methods answer differently depending on which. Both traps below produced a
plausible wrong number before being caught.

1. HoleCount() IS NOT A COUNT OF ENCLOSED VOIDS. After a boolean, Clipper
   frequently returns the FRACTURED form, in which every hole has been rewritten
   as a zero-width slit joining it to its parent outline. HoleCount() then
   answers 0 for a region that is full of voids. Measured on this board: the
   B.Cu GNDREF pour straight out of GetFilledPolysList()+Simplify() reports 3
   outlines and 41 holes, but `pour - obstacles` reports 6 outlines and 0 holes
   at the same 1137.9 mm2. Nothing was lost -- Contains() at the centre of all 25
   back decoupling caps inside that region answers False, correctly -- but a
   "holes: 0" column in a report is a lie. There is no such column here. The
   representation-independent question is asked instead, by tile_probe().

2. Unfracture() ON AN ALREADY-UNFRACTURED SET DESTROYS ITS HOLES. Measured: the
   B.Cu pour, 1377.8 mm2 with 41 holes, becomes 1422.1 mm2 with 0 holes after a
   single Unfracture() call -- it silently filled in 44.3 mm2 of void. So
   Unfracture() is called nowhere in this file, and Fracture() is only ever
   called on a throwaway copy (see _fractured_rings).


ADD MODE -- THE INVERSION (--texture-mode add)
==============================================
A requirement change from the board owner: "For both spectre and hexagon, I
think we want this to be F.Cu layer material, so not visibly gold, and just a
board texture. And it should appear anywhere we see soldermask where said
soldermask does not already have an F.Cu that we would interfere with."

So add mode lays NEW copper in EMPTY board, under closed solder mask. On a
black-mask board that is tone T6, (44, 41, 36), against T5 (25, 25, 28) for bare
mask: a 19-count difference in red, which is the dark under-mask sheen rather
than gold. Subtract mode is unchanged and is still the default.

The base region inverts and nothing else does. Subtract mode starts from the
pour and removes obstacles; add mode starts from the whole board inside
Edge.Cuts and removes the SAME obstacles plus every copper feature of every net,
plus every solder-mask opening. The clearances, the courtyard guard, the HS1
envelope, the return corridor, the edge inset, whole-tile placement and fragment
dropping are shared code in both directions.

MEASURED ON SatoshiStarter, hex, tile 3.00 mm, gutter 0.25 mm, F.Cu + B.Cu:

  permitted region   F.Cu 8575.0 mm2 = 55.7% of the board, 72.8% of the bare
                     board; B.Cu 9125.4 mm2 = 59.2% / 78.2%
  solid fill         1188 tiles, 9098.0 mm2 of copper in 1188 islands
                     (F.Cu 4671.5 = 30.3% of the board, B.Cu 4426.5 = 28.7%)
  outline fill       same 1188 tiles, 1956.3 mm2 in 21 islands
                     (F.Cu 996.1 = 6.5% of the board, B.Cu 960.2 = 6.2%)
  ground plane       fill before == fill after, symmetric difference 0.0 mm2
                     tied to GNDREF; <= 1.6e-07 mm2 floating (see below)
  DRC floating       206 warnings / 0 errors / 0 unconnected -- identical to the
                     untextured baseline by type and severity
  DRC tied to GNDREF 206 warnings / 0 errors / 499 UNCONNECTED ITEMS

For scale: subtract mode found 41.0% of the 1691.5 mm2 F.Cu pour permitted, i.e.
about 693 mm2. Add mode has 8575.0 mm2, twelve times as much, because it works
on the complement of a plane that covers only a fifth of the board. This is the
number that decides the whole question the owner asked, and it says texture
rather than scattered confetti.

1. ELECTRICAL: FLOAT IT. TYING IT TO GNDREF IS A LABEL, NOT A CONNECTION.
--------------------------------------------------------------------------
Added copper in empty board is either floating or carries a net. Both were built
and both were run through DRC on the real board.

  floating (no net tag)   206 warnings, 0 errors, 0 unconnected items.
                          Identical to the untextured baseline in every type and
                          every severity.
  --add-net GNDREF        206 warnings, 0 errors, and 499 unconnected items,
                          every one severity "error": "Missing connection
                          between items -- Polygon [GNDREF] on B.Cu".

The recommendation is FLOATING, and the reason is not that DRC dislikes the
alternative. It is that the alternative does not do what its name suggests.
SetNetCode(GNDREF) does not connect anything; it declares that this copper ought
to be on GNDREF, and the copper is still an isolated island, so the connectivity
engine correctly reports 499 missing connections. The board is not more grounded
for having been labelled.

Nor can that be fixed with stitching vias, and this was measured rather than
assumed: of the 4671.5 mm2 added on F.Cu, the GNDREF plane lies beneath
0.0 mm2 -- 0.0% -- on In1.Cu, In2.Cu and B.Cu alike, and on B.Cu only 3.8% has
GNDREF anywhere below it. That is not a coincidence, it is the definition of the
mode: texture goes where there is no copper, and on this board the inner planes
follow the outer ones, so "no copper on F.Cu" is very nearly "no copper on any
layer". There is nothing under the texture to stitch DOWN to. Grounding it would
mean routing new copper to every island, which is a different feature and one
that would perforate the very planes add mode exists to leave alone.

So the copper floats. What that costs is bounded by its size: the largest island
is 7.658 mm2 and no island exceeds 3.43 mm across, on a board whose fastest
edges are the ASIC clocks. Isolated metal that small has no low-frequency
consequence, and it is what every fab's own copper-balancing thieving pattern
already is.

A THIRD OPTION WAS REJECTED BEFORE IT WAS BUILT: emitting the tiles as ZONES
rather than PCB_SHAPEs. Every pour on this board sets island_removal_mode =
ALWAYS. A tile emitted as a zone is a fill with no pad on it -- an island -- so
the filler DELETES it on the next refill. The texture would disappear from the
plots while the .kicad_pcb still described it. PCB_SHAPE is not a fill, so the
filler never touches it; it is copper in the gerber and copper to DRC.

2. IT REMOVES NOTHING FROM THE GROUND PLANE, AND HERE IS THE PROOF
-------------------------------------------------------------------
Not "the areas match" -- two different regions can share an area. The check is
the SYMMETRIC DIFFERENCE of the filled polygons before and after,
(before \\ after) u (after \\ before), which is zero only if the pour is the
identical region.

  tied to GNDREF   0.0 mm2 exactly, on both F.Cu and B.Cu.
  floating         0.0 mm2 on F.Cu; 8.2e-08 mm2 on B.Cu.

The tolerance was measured, not chosen. Refilling the untextured board three
times in one process gives symdiff 0.000e+00 mm2 for every pair, so the filler
is exactly deterministic and the noise floor is zero -- which means that 8.2e-08
is real and had to be explained rather than waved through. Locating it: one
sliver at x 88.785, y 71.06..71.23, losing 1.54e-07 mm2 over 54 x 164 um and
gaining 4.02e-08 mm2 over 10 x 101 um immediately beside it. It is one polygon
vertex landing differently in Clipper's integer arithmetic once the filler has a
foreign object to clear at all -- same-net copper needs no clearance, which is
exactly why the GNDREF variant reads 0.0. It is 1.1e-08 percent of the pour and
four orders of magnitude below the pour's own 0.25 mm min_thickness.

The clearance that makes this hold is --clr-copper, default 0.55 mm and NOT the
0.5 mm the other knobs use. Every pour here carries local_clearance 0.5 mm, so
new copper at exactly 0.5 mm sits on the boundary at which the filler starts
voiding the pour around it.

3. SOLID OR OUTLINE
--------------------
Both are built; --add-fill picks. Solid lays 9098.0 mm2 in 1188 islands, outline
lays 1956.3 mm2 in 21. Solid is 4.7x the copper for the same tiles and the same
electrical cost -- nothing was removed either way -- so it is the default and it
is what a texture that has to read through black mask wants.

THE GUTTER IS WHY SOLID FILL IS NOT ONE SHEET OF COPPER. A tiling tiles the
plane: neighbouring tiles share whole edges, so appending the raw tile polygons
and calling Simplify() -- a union -- merges every connected clump into a single
polygon with no internal boundary at all, and every area check still passes
because the area is right. Each tile is therefore deflated by --slot-mm/2
individually, BEFORE the union. Outline fill has the mirror-image trap and
tile_edges() already solves it: shared walls are deduplicated, so an interior
wall is stroked once rather than twice at double weight.


TIE-NECKS ARE NOT THIS FILE'S PROBLEM
--------------------------------------
Cutting closed cell outlines into a pour isolates every cell interior and yields
hundreds of floating copper islands. Each cell wall needs a tie-neck -- a gap in
the slot -- so the remaining copper stays one connected region. That is the
primary correctness requirement of the whole tool, and it lives in part 2, where
the slot geometry exists. Ingest deals in regions, which have no walls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field

try:
    import pcbnew
    HAVE_PCBNEW = True
except ImportError:                                   # pragma: no cover
    pcbnew = None
    HAVE_PCBNEW = False


# --- board-specific measured constants ---------------------------------------

# HS1's TRUE front keep-clear envelope, measured. See the HS1 note in the module
# docstring: the footprint under-reports this by a factor of 12 in area.
HS1_TRUE_ENVELOPE = (72.22, 52.42, 119.78, 99.97)     # x0, y0, x1, y1 mm

# The 40 mm rectangle the footprint draws on B.Silkscreen. Recorded so that it is
# obviously NOT used; it is the wrong side and the wrong size.
HS1_SPURIOUS_BACK_SILK = (75.92, 56.12, 116.08, 96.28)

# VRM -> ASIC VCORE return corridor: L1 -> U9.
CORRIDOR_L1 = (151.5, 75.5)
CORRIDOR_U9 = (100.0, 72.5)

# ADD MODE pass tolerance on "the pour did not move", in mm2 of symmetric
# difference between the fill before and after.
#
# The obvious tolerance is the filler's own run-to-run noise, so that was
# measured first: refilling the untextured board three times in one process
# gives symdiff 0.000e+00 mm2 on both F.Cu and B.Cu, every pair. The filler is
# exactly deterministic, so the noise floor is zero and cannot supply a
# tolerance.
#
# What the runs then showed is a clean split. Added copper tied to GNDREF leaves
# symdiff EXACTLY 0.0 on both layers -- same-net copper imposes no clearance on
# the zone, so the filler's boolean is not re-run at all. Floating copper leaves
# 8.2e-08 mm2 on B.Cu and 0.0 on F.Cu, and locating it showed one sliver at
# x 88.785, y 71.06..71.23: 1.54e-07 mm2 lost over 54 x 164 um and 4.02e-08 mm2
# gained over 10 x 101 um immediately beside it. That is one polygon vertex
# landing differently in Clipper's integer arithmetic once the filler has a
# foreign object to clear, not the pour retreating.
#
# So the tolerance is set by manufacturability instead: 1e-6 mm2 is 1 um2,
# four orders of magnitude below this pour's own 0.25 mm min_thickness and far
# below anything a fab can image. The measured value is always printed in full,
# in scientific notation, so a number under the tolerance is still visible.
FILL_MOVE_TOL_MM2 = 1e-6

# Which copper layers belong to which side. The outer layer is the one the
# texture is seen on; the inner layer directly beneath it is included because the
# same component bodies and the same corridor sit over both, and because a slot
# in In1 under a slot in F.Cu compounds the plane-resistance cost.
SIDE_LAYERS = {
    "front": ["F.Cu", "In1.Cu"],
    "back":  ["B.Cu", "In2.Cu"],
}


# --- pure geometry: no pcbnew, so this half stays testable anywhere -----------

def parse_rect(spec: str) -> tuple[float, float, float, float]:
    """'x0,y0,x1,y1' in mm -> a normalised (x0, y0, x1, y1) with x0<x1, y0<y1."""
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise ValueError(f"exclusion rect needs 4 comma-separated mm values, got {spec!r}")
    try:
        x0, y0, x1, y1 = (float(p) for p in parts)
    except ValueError:
        raise ValueError(f"exclusion rect values must be numbers, got {spec!r}") from None
    if x0 == x1 or y0 == y1:
        raise ValueError(f"exclusion rect has zero width or height: {spec!r}")
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def corridor_quad(p0, p1, half_width_mm):
    """The rectangle of half-width `half_width_mm` about segment p0->p1.

    Returned as four (x, y) mm corners in order. Caps are square here and are
    rounded later by the Inflate that applies the clearance, which is the right
    way round: a square cap at the VRM end would clip the corner of the
    inductor's own copper, a round one does not.
    """
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0:
        raise ValueError("corridor endpoints coincide")
    # unit normal
    nx, ny = -dy / length, dx / length
    h = half_width_mm
    return [
        (x0 + nx * h, y0 + ny * h),
        (x1 + nx * h, y1 + ny * h),
        (x1 - nx * h, y1 - ny * h),
        (x0 - nx * h, y0 - ny * h),
    ]


def corridor_length_mm(p0=CORRIDOR_L1, p1=CORRIDOR_U9) -> float:
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def rect_corners(rect):
    x0, y0, x1, y1 = rect
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def polygon_area_mm2(pts) -> float:
    """Shoelace area, absolute value, for a closed ring given as (x, y) mm."""
    n = len(pts)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        acc += x0 * y1 - x1 * y0
    return abs(acc) * 0.5


def geometry_digest(rings, quantum_nm=1):
    """SHA-256 over a list of closed rings, quantised to `quantum_nm` nm.

    THE REPRODUCIBILITY CHECK, and it is deliberately not a hash of the emitted
    .kicad_pcb. Two runs of the identical command on the identical board produce
    files that differ in 63 lines: every one is a KiCad-assigned random UUID, or
    one of the two group `members` lists that cite those UUIDs and are written
    in UUID-string order. Zero geometry lines differ. So a file digest reports
    "not reproducible" on a run that is bit-identical where it matters, and the
    only honest comparison is of the geometry itself.

    Quantised to KiCad's own 1 nm file resolution rather than compared as
    floats, so a difference this cannot represent is not reported as one, and a
    difference of a single internal unit is.
    """
    h = hashlib.sha256()
    h.update(b"tile-geometry/v1/%d\n" % int(quantum_nm))
    for ring in rings:
        h.update(b"R")
        for x, y in ring:
            h.update(b"%d,%d;" % (int(round(x * 1e6 / quantum_nm)),
                                  int(round(y * 1e6 / quantum_nm))))
        h.update(b"\n")
    return h.hexdigest()


# --- unit helpers -------------------------------------------------------------

def mm_to_nm(v: float) -> int:
    """mm -> KiCad internal units (nm). Rounded, never truncated."""
    return int(round(v * 1e6))


def nm_to_mm(v: int) -> float:
    return v / 1e6


# --- results ------------------------------------------------------------------

@dataclass
class LayerResult:
    """Everything ingest knows about one copper layer."""
    layer_name: str
    side: str
    mode: str = "subtract"
    pour_net: str = ""
    pour_area_mm2: float = 0.0
    # ADD MODE denominators. The pour is not the base in add mode, so a
    # percentage of it is meaningless there; these are the honest ones.
    board_area_mm2: float = 0.0          # inside Edge.Cuts, before the inset
    bare_area_mm2: float = 0.0           # board minus ALL copper, zero clearance
    permitted_area_mm2: float = 0.0
    permitted_pct_of_pour: float = 0.0
    permitted_pct_of_board: float = 0.0
    permitted_pct_of_bare: float = 0.0
    obstacle_area_mm2: float = 0.0
    fragment_count: int = 0
    largest_fragment_mm2: float = 0.0
    dropped_fragments: int = 0
    dropped_area_mm2: float = 0.0
    # tile size mm -> (area mm2 that could hold a tile centre, fragment count).
    # See tile_probe(): the inradius test, an UPPER bound on placeable area.
    tile_probe: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    # mm2 of THIS layer's pour that each obstacle class removes, measured one
    # class at a time against the pour. The classes overlap each other, so these
    # do not sum to the total -- their purpose is to expose a guard that is
    # silently removing nothing.
    removal_mm2: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    permitted = None          # SHAPE_POLY_SET, the contract with part 2
    pour = None               # SHAPE_POLY_SET, for the visualisation
    obstacles = None          # SHAPE_POLY_SET, for the visualisation
    other_pours = None        # SHAPE_POLY_SET, other nets' copper on this layer


@dataclass
class IngestOptions:
    # subtract: cut slots into the pour. add: lay new copper where there is none.
    # The two modes invert the base region -- see ADD MODE in the module
    # docstring. Everything below applies to both unless marked.
    mode: str = "subtract"
    # ADD MODE ONLY. Clearance around EVERY existing copper feature, any net.
    # 0.55, not 0.5: every pour on this board carries local_clearance 0.5 mm, so
    # new copper closer than that makes the filler void the pour around it and
    # the "removes nothing" guarantee fails. Measured at 0.50 the F.Cu GNDREF
    # fill still moved; 0.55 leaves it bit-identical. See ADD MODE.
    clr_copper_mm: float = 0.55
    # ADD MODE ONLY. Clearance around solder-mask openings. Copper under an
    # opening is gold (T2), which is the one thing the owner asked to avoid, so
    # apertures are an obstacle in their own right and not merely a proxy for
    # the pad beneath them.
    clr_mask_mm: float = 0.25
    clr_courtyard_mm: float = 0.5
    clr_pad_mm: float = 0.5
    clr_track_mm: float = 0.4
    clr_via_mm: float = 0.4
    clr_hole_mm: float = 0.4
    clr_zone_mm: float = 0.5
    clr_hs_mm: float = 1.0
    clr_extra_mm: float = 0.0
    # THE BOARD'S OWN RULE, not a round number. SatoshiStarter.kicad_pro sets
    # design_settings.rules.min_copper_edge_clearance = 0.5, and this was 1.0 --
    # the texture stood back twice as far as the board requires, for no stated
    # reason: it was the only knob in its argument group with no help text and
    # nothing in the tree ties it to a fab constraint. It is NOT standing in for
    # V-scoring, a panel rail or the router bit radius; those are Edge.Cuts
    # constraints (see docs/pcb-palette.md "Router constraints") and this
    # pipeline emits copper shapes and keepout rule areas, never Edge.Cuts.
    edge_inset_mm: float = 0.5
    # THE SECOND JOB edge_inset_mm was quietly doing, now named. The board-first
    # tilings anchor their frame on the deflated outline, so changing a COPPER
    # CLEARANCE used to move every tile on the board -- a DRC setting silently
    # rewriting the art. None means "follow edge_inset_mm", which keeps every
    # previously documented run reproducible; set it to hold the pattern still
    # while the clearance changes, which is also how the two effects get
    # measured apart.
    frame_inset_mm: float | None = None
    # 12.0, not the obvious 6.0. See the sweep in the module docstring: below
    # ~8 mm the band lies wholly inside the VCORE pour and removes nothing at all
    # from the GNDREF pour it is supposed to be protecting.
    corridor_half_width_mm: float = 12.0
    corridor_all_layers: bool = True
    min_region_mm2: float = 1.0
    pour_net: str | None = None       # None = pick the largest pour on each layer
    excludes: list = field(default_factory=list)
    hs1_sides: str = "front"          # front | both | none
    refill: bool = True               # refill in process before measuring


# --- SHAPE_POLY_SET helpers ---------------------------------------------------

def _sps():
    return pcbnew.SHAPE_POLY_SET()


def _inflate(poly, amount_nm, max_error):
    """Inflate in place, rounding all corners. Zero and negative are honoured."""
    if amount_nm == 0:
        return poly
    poly.Inflate(int(amount_nm), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                 max_error, True)
    return poly


def _add_ring(poly, pts_mm):
    """Append one closed ring, given (x, y) in mm, as a new outline."""
    idx = poly.NewOutline()
    for x, y in pts_mm:
        poly.Append(mm_to_nm(x), mm_to_nm(y), idx)
    return poly


def _area_mm2(poly) -> float:
    return poly.Area() / 1e12


def _fractured_rings(poly):
    """Simple, hole-free rings covering `poly`, in mm.

    Fracture() rewrites every hole as a slit joining it to its parent outline,
    which turns each outline into a single simple polygon. That is exactly what a
    naive scanline filler (PIL's ImageDraw.polygon) needs, and it is why the
    visualisation does not have to implement even-odd hole handling.
    """
    work = _sps()
    work.Append(poly)
    work.Fracture()
    rings = []
    for i in range(work.OutlineCount()):
        chain = work.Outline(i)
        rings.append([(nm_to_mm(chain.CPoint(j).x), nm_to_mm(chain.CPoint(j).y))
                      for j in range(chain.PointCount())])
    return rings


def _outlines_with_holes(poly):
    """[{outline: [[x,y]...], holes: [[[x,y]...]]}] in mm, for the JSON dump."""
    out = []
    for i in range(poly.OutlineCount()):
        chain = poly.Outline(i)
        ring = [[nm_to_mm(chain.CPoint(j).x), nm_to_mm(chain.CPoint(j).y)]
                for j in range(chain.PointCount())]
        holes = []
        for h in range(poly.HoleCount(i)):
            hc = poly.Hole(i, h)
            holes.append([[nm_to_mm(hc.CPoint(j).x), nm_to_mm(hc.CPoint(j).y)]
                          for j in range(hc.PointCount())])
        out.append({"outline": ring, "holes": holes})
    return out


def _drop_small_fragments(poly, min_mm2):
    """Remove outlines below `min_mm2`. Returns (kept_poly, n_dropped, area_dropped).

    A fragment smaller than one tile can never hold a whole tile, so dropping it
    costs nothing and stops the reported permitted area being inflated by dust
    that part 2 will discard anyway.
    """
    if min_mm2 <= 0:
        return poly, 0, 0.0
    kept = _sps()
    dropped = 0
    dropped_area = 0.0
    for i in range(poly.OutlineCount()):
        one = _sps()
        one.AddOutline(poly.Outline(i))
        for h in range(poly.HoleCount(i)):
            one.AddHole(poly.Hole(i, h), 0)
        a = _area_mm2(one)
        if a < min_mm2:
            dropped += 1
            dropped_area += a
            continue
        kept.Append(one)
    return kept, dropped, dropped_area


# --- the ingest ---------------------------------------------------------------

class BoardIngest:
    """Reads a board once, then answers 'where is texture allowed?' per layer."""

    def __init__(self, board_path: str, opts: IngestOptions, board=None):
        if not HAVE_PCBNEW:
            raise RuntimeError(
                "pcbnew is not importable. Run this under KiCad's bundled "
                "Python, e.g.\n"
                '  "C:/Program Files/KiCad/10.0/bin/python.exe" '
                "tools/texture_board.py ...")
        self.path = str(board_path)
        self.opts = opts
        # `board` lets the caller hand in an already-loaded BOARD. Part 2 needs
        # that: calling pcbnew.LoadBoard() twice in one process reliably
        # segfaults this build, so the whole run shares exactly one load.
        self.board = board if board is not None else pcbnew.LoadBoard(self.path)
        self.max_error = self.board.GetDesignSettings().m_MaxError
        self.notes: list[str] = []
        self.refill_delta_mm2: dict = {}
        self.refill_seconds = 0.0
        if self.opts.refill:
            self._refill()
        else:
            self.notes.append(
                "--no-refill: measuring the fills stored in the file. These may "
                "be stale, and NeedRefill() cannot detect that -- see the module "
                "docstring.")

    # -- freshness ----------------------------------------------------------

    def _filled_area_by_layer(self):
        acc = {}
        for z in self.board.Zones():
            for lid in z.GetLayerSet().Seq():
                if z.HasFilledPolysForLayer(lid):
                    name = self.board.GetLayerName(lid)
                    acc[name] = acc.get(name, 0.0) + \
                        z.GetFilledPolysList(lid).Area() / 1e12
        return acc

    def _refill(self):
        """Refill every zone in process, then record what the refill changed.

        This is done instead of checking NeedRefill(), which is not persisted and
        answers False for a stale file. The recorded delta is the staleness
        report: near-zero means the file's stored fills were already current.
        """
        import time
        before = self._filled_area_by_layer()
        t0 = time.time()
        pcbnew.ZONE_FILLER(self.board).Fill(self.board.Zones())
        self.refill_seconds = time.time() - t0
        after = self._filled_area_by_layer()
        for name in sorted(set(before) | set(after)):
            self.refill_delta_mm2[name] = after.get(name, 0.0) - before.get(name, 0.0)

    # -- the pour -----------------------------------------------------------

    def _layer_id(self, name: str):
        lid = self.board.GetLayerID(name)
        if lid < 0:
            raise ValueError(f"no such layer on this board: {name}")
        return lid

    def _pours_on_layer(self, lid):
        """{netname: SHAPE_POLY_SET} of filled copper, per net, on one layer.

        Zero-area entries are dropped. This board carries one: an unconnected
        5.42 mm2 zone outline on B.Cu at x 185.0..187.2, y 72.8..76.0 whose fill
        is empty because it has no net to connect to. HasFilledPolysForLayer()
        answers True for it, so it would otherwise appear as a net named "" with
        no copper and inflate the other-net-zone count.
        """
        by_net = {}
        for z in self.board.Zones():
            if z.GetIsRuleArea():
                continue
            if not z.HasFilledPolysForLayer(lid):
                continue
            net = z.GetNetname()
            acc = by_net.setdefault(net, _sps())
            acc.Append(z.GetFilledPolysList(lid))
        out = {}
        for net, poly in by_net.items():
            poly.Simplify()
            if poly.Area() > 0:
                out[net] = poly
        return out

    # -- obstacle builders --------------------------------------------------

    def _courtyard_obstacles(self, side: str):
        """Courtyards of every footprint mounted on `side`, plus the fallback.

        Side-level: a component body sits over its surface layer AND the inner
        layer beneath it, so the same set is subtracted from both layers of the
        side. Pads of the OPPOSITE side's parts are not covered here -- they are
        picked up per-layer by the pad pass, which is where a through-hole pad
        belongs.
        """
        want_back = (side == "back")
        crtyd = pcbnew.B_CrtYd if want_back else pcbnew.F_CrtYd
        poly = _sps()
        n_courtyard = 0
        fallbacks = []
        for fp in self.board.GetFootprints():
            if fp.IsFlipped() != want_back:
                continue
            c = fp.GetCourtyard(crtyd)
            if c.OutlineCount() > 0 and c.Area() > 0:
                poly.Append(c)
                n_courtyard += 1
                continue
            # No courtyard. Fall back to the union of PAD bounding boxes --
            # NOT GetBoundingHull(), which includes silk and refdes text.
            pads = fp.Pads()
            if not pads:
                continue
            got = False
            for pad in pads:
                bb = pad.GetBoundingBox()
                if bb.GetWidth() <= 0 or bb.GetHeight() <= 0:
                    continue
                _add_ring(poly, rect_corners((nm_to_mm(bb.GetLeft()),
                                              nm_to_mm(bb.GetTop()),
                                              nm_to_mm(bb.GetRight()),
                                              nm_to_mm(bb.GetBottom()))))
                got = True
            if got:
                fallbacks.append(fp.GetReference())
        poly.Simplify()
        if fallbacks:
            self.notes.append(
                f"courtyard fallback to pad bboxes on {side}: "
                + ", ".join(sorted(fallbacks)))
        return poly, n_courtyard, sorted(fallbacks)

    def _copper_obstacles(self, lid):
        """Pads, tracks, vias on this layer, plus every drilled hole.

        Holes are subtracted on EVERY layer regardless of which layer the pad's
        copper lives on, because a drill goes through the whole stack. A pad on
        B.Cu only still leaves a hole in the F.Cu pour.
        """
        poly = _sps()
        counts = {"pads": 0, "pad_holes": 0, "tracks": 0, "arcs": 0, "vias": 0}
        clr_pad = mm_to_nm(self.opts.clr_pad_mm)
        clr_trk = mm_to_nm(self.opts.clr_track_mm)
        clr_via = mm_to_nm(self.opts.clr_via_mm)
        clr_hole = mm_to_nm(self.opts.clr_hole_mm)

        for pad in self.board.GetPads():
            if pad.IsOnLayer(lid):
                pad.TransformShapeToPolygon(poly, lid, clr_pad, self.max_error,
                                            pcbnew.ERROR_OUTSIDE)
                counts["pads"] += 1
            if pad.HasHole():
                pad.TransformHoleToPolygon(poly, clr_hole, self.max_error,
                                           pcbnew.ERROR_OUTSIDE)
                counts["pad_holes"] += 1

        for t in self.board.Tracks():
            if not t.IsOnLayer(lid):
                continue
            if isinstance(t, pcbnew.PCB_VIA):
                t.TransformShapeToPolygon(poly, lid, clr_via, self.max_error,
                                          pcbnew.ERROR_OUTSIDE)
                counts["vias"] += 1
            else:
                t.TransformShapeToPolygon(poly, lid, clr_trk, self.max_error,
                                          pcbnew.ERROR_OUTSIDE)
                if isinstance(t, pcbnew.PCB_ARC):
                    counts["arcs"] += 1
                else:
                    counts["tracks"] += 1
        poly.Simplify()
        return poly, counts

    def _all_zone_fills(self, pours):
        """ADD MODE. Every net's filled copper on this layer, the pour included.

        In subtract mode the textured net's own pour is the BASE. In add mode it
        is an obstacle like any other: the requirement is copper "where said
        soldermask does not already have an F.Cu that we would interfere with",
        and the ground plane is exactly such an F.Cu.
        """
        poly = _sps()
        for p in pours.values():
            poly.Append(p)
        poly.Simplify()
        _inflate(poly, mm_to_nm(self.opts.clr_copper_mm), self.max_error)
        return poly, len(pours)

    def _mask_apertures(self, side: str):
        """ADD MODE. Solder-mask openings on this side, as an obstacle.

        Two sources, and the second is the one a pad-only pass would miss:
        pads that carry the mask layer in their layer set, and graphic items
        drawn directly on F.Mask / B.Mask. Measured on SatoshiStarter: 253 pad
        apertures totalling 362.870 mm2 on F.Mask and 4 footprint graphics
        totalling 9.310 mm2 -- so the graphics are 2.5% of the aperture area and
        skipping them would be a silent, small, permanent defect.

        This matters because of what the tone table does with an opening. Copper
        under closed mask is T6, 'mask over copper', which is the dark sheen the
        owner asked for. The SAME copper under an opening is T2, ENIG gold. So an
        aperture is not a duplicate of the pad guard -- it is the guard that
        keeps the texture from turning gold.
        """
        lname = "B.Mask" if side == "back" else "F.Mask"
        lid = self.board.GetLayerID(lname)
        poly = _sps()
        n_pad = n_gfx = 0
        if lid < 0:
            return poly, 0, 0
        for pad in self.board.GetPads():
            if pad.IsOnLayer(lid):
                pad.TransformShapeToPolygon(poly, lid, 0, self.max_error,
                                            pcbnew.ERROR_OUTSIDE)
                n_pad += 1
        for d in self.board.GetDrawings():
            if d.GetLayer() == lid:
                d.TransformShapeToPolygon(poly, lid, 0, self.max_error,
                                          pcbnew.ERROR_OUTSIDE)
                n_gfx += 1
        for fp in self.board.GetFootprints():
            for d in fp.GraphicalItems():
                if d.GetLayer() == lid:
                    d.TransformShapeToPolygon(poly, lid, 0, self.max_error,
                                              pcbnew.ERROR_OUTSIDE)
                    n_gfx += 1
        poly.Simplify()
        _inflate(poly, mm_to_nm(self.opts.clr_mask_mm), self.max_error)
        return poly, n_pad, n_gfx

    def _add_mode_copper(self, lid):
        """ADD MODE. Pads, tracks and vias on this layer at clr_copper_mm.

        Same items as _copper_obstacles() but on one clearance rather than three,
        because in add mode the binding constraint is not the DRC netclass
        clearance (0.2 mm on this board) but the ZONE local clearance (0.5 mm):
        new copper nearer than that to a pour makes the filler void the pour, and
        the whole premise of add mode is that the pour does not move. A track
        knob of 0.4 mm would have been quietly too small.
        """
        poly = _sps()
        counts = {"pads": 0, "pad_holes": 0, "tracks": 0, "arcs": 0, "vias": 0}
        clr = mm_to_nm(self.opts.clr_copper_mm)
        clr_hole = mm_to_nm(self.opts.clr_hole_mm)
        for pad in self.board.GetPads():
            if pad.IsOnLayer(lid):
                pad.TransformShapeToPolygon(poly, lid, clr, self.max_error,
                                            pcbnew.ERROR_OUTSIDE)
                counts["pads"] += 1
            if pad.HasHole():
                pad.TransformHoleToPolygon(poly, clr_hole, self.max_error,
                                           pcbnew.ERROR_OUTSIDE)
                counts["pad_holes"] += 1
        for t in self.board.Tracks():
            if not t.IsOnLayer(lid):
                continue
            t.TransformShapeToPolygon(poly, lid, clr, self.max_error,
                                      pcbnew.ERROR_OUTSIDE)
            if isinstance(t, pcbnew.PCB_VIA):
                counts["vias"] += 1
            elif isinstance(t, pcbnew.PCB_ARC):
                counts["arcs"] += 1
            else:
                counts["tracks"] += 1
        poly.Simplify()
        return poly, counts

    def _bare_copper_complement(self, lid, interior):
        """ADD MODE reference figure: `interior` minus ALL copper, ZERO clearance.

        Not a region anything is placed in -- it is the denominator that says how
        much of this board is bare in the first place, so that the permitted
        percentage can be read as "of the bare board" and not just "of the
        board". Zero clearance on purpose: adding one here would make it a second
        permitted region with a different name.
        """
        cu = _sps()
        for pad in self.board.GetPads():
            if pad.IsOnLayer(lid):
                pad.TransformShapeToPolygon(cu, lid, 0, self.max_error,
                                            pcbnew.ERROR_OUTSIDE)
        for t in self.board.Tracks():
            if t.IsOnLayer(lid):
                t.TransformShapeToPolygon(cu, lid, 0, self.max_error,
                                          pcbnew.ERROR_OUTSIDE)
        for z in self.board.Zones():
            if z.GetIsRuleArea():
                continue
            if z.HasFilledPolysForLayer(lid):
                cu.Append(z.GetFilledPolysList(lid))
        cu.Simplify()
        bare = _sps()
        bare.Append(interior)
        bare.BooleanSubtract(cu)
        return _area_mm2(bare)

    def _other_net_zones(self, lid, pour_net, pours):
        poly = _sps()
        n = 0
        for net, p in pours.items():
            if net == pour_net:
                continue
            poly.Append(p)
            n += 1
        poly.Simplify()
        _inflate(poly, mm_to_nm(self.opts.clr_zone_mm), self.max_error)
        return poly, n

    def _hs1_obstacle(self):
        poly = _sps()
        _add_ring(poly, rect_corners(HS1_TRUE_ENVELOPE))
        _inflate(poly, mm_to_nm(self.opts.clr_hs_mm), self.max_error)
        return poly

    def _corridor_obstacle(self):
        poly = _sps()
        _add_ring(poly, corridor_quad(CORRIDOR_L1, CORRIDOR_U9,
                                      self.opts.corridor_half_width_mm))
        # Round the ends. The straight quad has square caps; rounding them keeps
        # the band from cutting the corner of L1's own copper.
        _inflate(poly, mm_to_nm(0.001), self.max_error)
        return poly

    def _extra_obstacles(self):
        poly = _sps()
        for rect in self.opts.excludes:
            _add_ring(poly, rect_corners(rect))
        if poly.OutlineCount():
            poly.Simplify()
            _inflate(poly, mm_to_nm(self.opts.clr_extra_mm), self.max_error)
        return poly

    def board_outline(self):
        """Edge.Cuts as a closed polygon, undeflated."""
        outline = _sps()
        ok = self.board.GetBoardPolygonOutlines(outline, True)
        if not ok or outline.OutlineCount() == 0:
            raise RuntimeError("could not build a closed board outline from Edge.Cuts")
        return outline

    def _deflated_outline(self, inset_mm):
        """Edge.Cuts deflated by `inset_mm`.

        DEPENDS ON m_MaxError, and that is worth knowing about: the deflate
        approximates the rounded corners to the board's DRC max_error setting
        (0.005 mm here), so a design-setting change that touches no copper at
        all can perturb this polygon and therefore the mask and the frame. The
        value used is recorded in the run's JSON rather than left implicit.
        """
        outline = self.board_outline()
        inset = mm_to_nm(inset_mm)
        if inset > 0:
            outline.Deflate(inset, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                            self.max_error)
        return outline

    def _board_interior(self):
        """The board outline, deflated by the COPPER edge clearance."""
        return self._deflated_outline(self.opts.edge_inset_mm)

    def frame_interior(self):
        """The board outline deflated by the FRAME inset -- the tiling anchor.

        Separate from _board_interior() so that a copper clearance and a pattern
        anchor are two decisions instead of one. Defaults to the same number, so
        nothing moves unless --frame-inset is given.
        """
        fi = self.opts.frame_inset_mm
        return self._deflated_outline(self.opts.edge_inset_mm if fi is None
                                      else fi)

    # -- the per-layer answer ------------------------------------------------

    def layer(self, layer_name: str, side: str) -> LayerResult:
        lid = self._layer_id(layer_name)
        add = (self.opts.mode == "add")
        res = LayerResult(layer_name=layer_name, side=side, mode=self.opts.mode)

        pours = self._pours_on_layer(lid)
        if not pours and not add:
            # Subtract mode has nothing to cut into. Add mode does not care: it
            # lays copper where there is none, and a layer with no pour at all is
            # the easiest case it has, not an error.
            res.counts = {"note": "no filled zone on this layer"}
            res.permitted = _sps()
            res.pour = _sps()
            res.obstacles = _sps()
            return res

        if pours and self.opts.pour_net is not None:
            if self.opts.pour_net not in pours:
                # Hard error, not an empty result. A mistyped or shell-mangled
                # net name that quietly yields "0.0 mm2, 0.0% texturable" is the
                # same silent-empty-set failure as a regex written for the old
                # numeric (net 12) form -- the report looks like an answer.
                # Note for POSIX shells: a hierarchical net name such as
                # /ASIC/VCORE gets path-translated by MSYS/Git Bash. Quote it as
                # --pour-net='/ASIC/VCORE' or set MSYS_NO_PATHCONV=1.
                raise RuntimeError(
                    f"--pour-net {self.opts.pour_net!r} has no fill on "
                    f"{layer_name}. Nets with copper there: "
                    + ", ".join(f"{n!r} ({_area_mm2(p):.1f} mm2)"
                                for n, p in sorted(pours.items(),
                                                   key=lambda kv: -kv[1].Area())))
            pour_net = self.opts.pour_net
        elif pours:
            pour_net = max(pours, key=lambda n: pours[n].Area())
        else:
            pour_net = ""

        pour = _sps()
        if pour_net:
            pour.Append(pours[pour_net])
        res.pour_net = pour_net
        res.pour_area_mm2 = _area_mm2(pour)
        res.pour = pour

        # THE INVERSION. Subtract mode starts from the pour and takes obstacles
        # out of it. Add mode starts from the whole board and takes the SAME
        # obstacles out plus all the copper, so its base is the pour's
        # complement. Everything downstream -- clearances, whole-tile placement,
        # fragment dropping -- is shared, which is why this is one branch and not
        # a second ingest.
        base = _sps()
        if add:
            raw_outline = _sps()
            if not self.board.GetBoardPolygonOutlines(raw_outline, True) or \
                    raw_outline.OutlineCount() == 0:
                raise RuntimeError(
                    "could not build a closed board outline from Edge.Cuts")
            base.Append(raw_outline)
            res.board_area_mm2 = _area_mm2(base)
        else:
            base.Append(pour)

        raw_other = _sps()
        for net, p in pours.items():
            if net != pour_net:
                raw_other.Append(p)
        raw_other.Simplify()
        res.other_pours = raw_other

        cy, n_cy, fallbacks = self._courtyard_obstacles(side)
        _inflate(cy, mm_to_nm(self.opts.clr_courtyard_mm), self.max_error)

        n_mask_pad = n_mask_gfx = 0
        if add:
            cpoly, counts = self._add_mode_copper(lid)
            zpoly, n_zones = self._all_zone_fills(pours)
            mpoly, n_mask_pad, n_mask_gfx = self._mask_apertures(side)
            classes = [("all_zone_fills", zpoly),
                       ("pads_tracks_vias", cpoly),
                       ("mask_apertures", mpoly),
                       ("courtyards", cy)]
        else:
            cpoly, counts = self._copper_obstacles(lid)
            zpoly, n_zones = self._other_net_zones(lid, pour_net, pours)
            classes = [("other_net_zones", zpoly),
                       ("pads_tracks_vias", cpoly),
                       ("courtyards", cy)]

        if self.opts.hs1_sides == "both" or (
                self.opts.hs1_sides == "front" and side == "front"):
            classes.append(("hs1_envelope", self._hs1_obstacle()))

        if self.opts.corridor_all_layers or side == "front":
            classes.append(("return_corridor", self._corridor_obstacle()))

        extra = self._extra_obstacles()
        if extra.OutlineCount():
            classes.append(("extra_rects", extra))

        # Charge each class for what it actually removes from THIS pour, before
        # they are merged. A guard that removes 0.0 is a guard that is not
        # working, and that is invisible once the classes are unioned.
        obstacles = _sps()
        for name, poly in classes:
            hit = _sps()
            hit.Append(poly)
            hit.BooleanIntersection(base)
            res.removal_mm2[name] = _area_mm2(hit)
            obstacles.Append(poly)
        obstacles.Simplify()
        res.obstacles = obstacles
        res.obstacle_area_mm2 = _area_mm2(obstacles)

        # Add mode's base is the whole board, so the corridor band always removes
        # its full area from it and this warning could never fire. It is a
        # subtract-mode guard: it exists to catch a band that lands entirely
        # inside some other net's pour and protects nothing.
        if not add and "return_corridor" in res.removal_mm2 and \
                res.removal_mm2["return_corridor"] <= 0.0:
            owners = []
            band = self._corridor_obstacle()
            for net, p in pours.items():
                probe = _sps()
                probe.Append(p)
                probe.BooleanIntersection(band)
                a = _area_mm2(probe)
                if a > 0:
                    owners.append(f"{net} {a:.1f} mm2")
            res.warnings.append(
                f"return corridor removes NOTHING from the {pour_net} pour on "
                f"{layer_name} at half-width "
                f"{self.opts.corridor_half_width_mm} mm. The corridor copper "
                f"there belongs to: {', '.join(owners) if owners else 'no net'}. "
                f"Widen --corridor-half-width or texture that net instead.")

        permitted = _sps()
        permitted.Append(base)
        permitted.BooleanSubtract(obstacles)
        interior = self._board_interior()
        before_edge = _area_mm2(permitted)
        permitted.BooleanIntersection(interior)
        res.removal_mm2["edge_inset"] = before_edge - _area_mm2(permitted)
        permitted.Simplify()

        permitted, n_drop, a_drop = _drop_small_fragments(
            permitted, self.opts.min_region_mm2)

        res.permitted = permitted
        res.permitted_area_mm2 = _area_mm2(permitted)
        res.permitted_pct_of_pour = (
            100.0 * res.permitted_area_mm2 / res.pour_area_mm2
            if res.pour_area_mm2 > 0 else 0.0)
        if add:
            res.bare_area_mm2 = self._bare_copper_complement(lid, interior)
            res.permitted_pct_of_board = (
                100.0 * res.permitted_area_mm2 / res.board_area_mm2
                if res.board_area_mm2 > 0 else 0.0)
            res.permitted_pct_of_bare = (
                100.0 * res.permitted_area_mm2 / res.bare_area_mm2
                if res.bare_area_mm2 > 0 else 0.0)
        res.fragment_count = permitted.OutlineCount()
        # HOLES COUNT. This used to shoelace the outline ring alone, which on
        # this board reported the F.Cu fragment as 8817.8 mm2 where it is 8205.9,
        # and the B.Cu one as 14917.0 where it is 8088.4 -- on a board whose
        # whole area is 15408.5. The dominant permitted fragment is a sheet with
        # 21-22 holes punched in it, so ignoring holes is not a rounding error,
        # and anyone sizing a tile off this number was reading fiction.
        res.largest_fragment_mm2 = max(
            (_area_mm2(one) for one, _ in _fragments_with_bbox(permitted)),
            default=0.0)
        res.dropped_fragments = n_drop
        res.dropped_area_mm2 = a_drop
        counts.update({"all_zone_fills" if add else "other_net_zones": n_zones,
                       "courtyards": n_cy,
                       "courtyard_fallbacks": len(fallbacks),
                       "extra_rects": len(self.opts.excludes)})
        if add:
            counts.update({"mask_apertures_pad": n_mask_pad,
                           "mask_apertures_graphic": n_mask_gfx})
        res.counts = counts
        return res

    def side(self, side: str, layers=None) -> list[LayerResult]:
        names = layers if layers else SIDE_LAYERS[side]
        return [self.layer(n, side) for n in names]


def tile_probe(res: LayerResult, tile_mm: float):
    """Where could the CENTRE of a tile of size `tile_mm` legally sit?

    Deflate the permitted region by tile_mm/2. A tile whose circumradius is
    tile_mm/2 fits wholly inside the permitted region if and only if its centre
    lies in that deflation, so this is the exact answer for a disc and an UPPER
    bound for any polygon inscribed in that disc -- which is every tiling part 2
    will generate. It is the number that says whether an answer is sane: a
    permitted region of 700 mm2 that survives a 6 mm probe at 400 mm2 is usable,
    one that collapses to 5 mm2 is a ring of slivers wearing a large area.

    Returns (area_mm2, fragment_count).
    """
    if res.permitted is None or res.permitted.OutlineCount() == 0:
        return (0.0, 0)
    work = _sps()
    work.Append(res.permitted)
    work.Deflate(mm_to_nm(tile_mm / 2.0),
                 pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, 5000)
    work.Simplify()
    return (_area_mm2(work), work.OutlineCount())


# ==============================================================================
# PART 2 -- SLOT GEOMETRY
# ==============================================================================
# Everything down to the next banner is pure Python: no pcbnew, so the topology
# that the whole design rests on is testable in the project's own environment.
#
# THE THEOREM THIS FILE RESTS ON, AND THE CORRECTION MEASUREMENT FORCED ON IT
# ---------------------------------------------------------------------------
# Slots are thin arcs cut out of a sheet of copper. A finite union of arcs fails
# to separate the PLANE if and only if it contains no cycle, which suggests:
#
#     the remaining copper is connected  <=>  the set of cut walls, viewed as a
#     subgraph of the tiling's 1-skeleton, is ACYCLIC (a forest).
#
# Cutting every tile outline closed puts a cycle around every cell, which is
# precisely why the naive version isolates every cell: measured with
# --neck-style none, 44 tiles produced 49 fill components against the untextured
# board's 4, and the filler deleted 341.1 mm2 of newly-isolated copper.
#
# BUT THE ARROW ONLY RUNS ONE WAY, and believing otherwise cost a wrong design.
# The copper is NOT the plane; it is a bounded region with holes. An arc whose
# two ends both terminate on that region's BOUNDARY separates it, cycle or no
# cycle. --neck-style forest cuts whole walls, so chains of walls run
# uninterrupted, and a chain that crosses a narrow isthmus of the pour severs it.
# Measured on this board: the forest wall set is provably acyclic (123 walls,
# 124 vertices, 1 component -- exactly a spanning tree), and it STILL created two
# isolated pieces of 12.922 and 8.456 mm2, both at x 162.90..166.25, hard against
# the pour's eastern edge at x = 166.25, where the GNDREF copper narrows to a
# 3.3 mm strip that two chained hex walls span end to end.
#
# So acyclicity is necessary and not sufficient. What IS sufficient, and what
# makes the guarantee independent of the pour's shape, is the brief's rule: a
# tie-neck in EVERY wall. Then no continuous slot path exists at any length, so
# no path can reach the boundary twice and no cycle can close. `midedge`,
# `vertex` and `both` all have this property and are safe on any region;
# `forest` is acyclic but shape-dependent, and on this board it fails.
# `wall_graph_is_forest()` is still run -- it catches `none` before any board is
# touched -- but the flood fill is the proof, not a confirmation.
#
# A COROLLARY THAT DECIDES THE FILE FORMAT
# ----------------------------------------
# Measured: the KiCad 10 zone WRITER emits exactly one `(polygon ...)` per zone.
# A rule area built in memory with five outlines comes back from save+reload with
# one. So the number of keepout ZONE objects equals the number of connected
# components of the slot union, and that count is set by the neck style:
#
#   midedge  breaks each wall at its midpoint  -> components = one star per
#            tiling VERTEX (the surviving half-edge stubs around it)
#   vertex   breaks each wall at both ends     -> components = one per EDGE,
#            i.e. ~1.5x more zones than midedge for hex
#   both     breaks at ends and midpoint       -> components = 2 per EDGE
#   forest   keeps a spanning forest of walls  -> ONE component per layer, and
#            no necks at all; acyclic by construction rather than by breaking
#
# So `midedge` is not an aesthetic preference, it is the cheapest neck style that
# still puts a tie-neck in every wall, and `forest` is the cheap-at-any-scale
# escape hatch.

# Quantum for "these two tile corners are the same corner", in nm. The tiling
# generators work in floating-point mm, so shared corners agree to ~1e-12 mm but
# not bitwise. 1 um is four orders of magnitude below the narrowest slot this
# tool will cut and four orders above the float noise.
EDGE_WELD_NM = 1000


def _wkey(pt):
    """Quantised vertex key, in EDGE_WELD_NM units."""
    return (int(round(pt[0] * 1e6 / EDGE_WELD_NM)),
            int(round(pt[1] * 1e6 / EDGE_WELD_NM)))


def tile_edges(rings):
    """Undirected edges of a tile set, each shared edge returned ONCE.

    Returns (edges, stats) where edges is a list of ((x0,y0),(x1,y1)) in mm and
    stats counts what was welded. De-duplication is not merely an optimisation:
    the wall graph below has to be the graph of the tiling, and an interior wall
    counted twice would be two parallel graph edges, which is a 2-cycle. The
    forest test would then reject a perfectly good wall set.
    """
    seen = {}
    total = 0
    degenerate = 0
    for ring in rings:
        pts = ring[:-1] if (len(ring) > 1 and _wkey(ring[0]) == _wkey(ring[-1])) \
            else list(ring)
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            ka, kb = _wkey(a), _wkey(b)
            total += 1
            if ka == kb:
                degenerate += 1
                continue
            key = (ka, kb) if ka <= kb else (kb, ka)
            if key not in seen:
                seen[key] = (a, b) if ka <= kb else (b, a)
    edges = list(seen.values())
    edges.sort(key=lambda e: (round(e[0][1], 6), round(e[0][0], 6),
                              round(e[1][1], 6), round(e[1][0], 6)))
    return edges, {"directed_edges": total, "unique_edges": len(edges),
                   "shared_edges": total - len(edges) - degenerate,
                   "degenerate_edges": degenerate}


def _uf_find(parent, x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def wall_graph_is_forest(walls):
    """Is this wall set acyclic? Returns (is_forest, n_vertices, n_components).

    The connectivity guarantee in one function. `walls` is a list of edges in the
    same form `tile_edges` returns; only the quantised endpoints matter.
    """
    parent = {}
    for a, b in walls:
        for k in (_wkey(a), _wkey(b)):
            parent.setdefault(k, k)
    n_edges = 0
    for a, b in walls:
        ra, rb = _uf_find(parent, _wkey(a)), _uf_find(parent, _wkey(b))
        if ra == rb:
            return False, len(parent), 0          # this edge closes a cycle
        parent[ra] = rb
        n_edges += 1
    comps = len({_uf_find(parent, k) for k in parent})
    return True, len(parent), comps


def spanning_forest(edges, seed=0):
    """A spanning forest of the wall graph -- Kruskal on a seeded shuffle.

    Keeping only these walls makes the wall set acyclic without breaking a single
    wall, and the slot union becomes ONE polygon per layer, so the board needs one
    keepout zone instead of hundreds.

    DO NOT REACH FOR THIS AS THE SAFE OPTION. Measured on SatoshiStarter it
    FAILS: the wall set is exactly a spanning tree (123 walls, 124 vertices, one
    component) and it still isolated 12.922 and 8.456 mm2 of copper at the pour's
    eastern edge, because uninterrupted chains of walls can run from one point of
    the pour boundary to another and sever a narrow isthmus. Acyclicity protects
    the plane, not a bounded region. See the correction in the PART 2 banner.

    There is a visual price too: a spanning forest of a hexagonal lattice keeps
    V-1 of the E = 1.5V walls, so a third of the walls are absent and the pattern
    reads as a maze rather than a honeycomb. Kept as a measured negative result
    and for regions known to have no thin isthmus.
    """
    order = list(range(len(edges)))
    rnd = random.Random(seed)
    rnd.shuffle(order)
    parent = {}
    for a, b in edges:
        for k in (_wkey(a), _wkey(b)):
            parent.setdefault(k, k)
    keep = []
    for i in order:
        a, b = edges[i]
        ra, rb = _uf_find(parent, _wkey(a)), _uf_find(parent, _wkey(b))
        if ra == rb:
            continue
        parent[ra] = rb
        keep.append(i)
    keep.sort()
    return [edges[i] for i in keep]


NECK_STYLES = ("midedge", "vertex", "both", "forest", "none")


def cap_extend_mm(slot_mm, cap):
    """How far a slot BODY reaches past its cut's centreline endpoint.

    A round cap is a half-disc of radius slot_mm/2 centred on the endpoint, so it
    overhangs by slot_mm/2. A square cap stops dead on the endpoint.

    This is not a detail. Measured on this board: asking for a 0.40 mm neck with
    a 0.25 mm round-capped slot leaves 0.40 - 2*0.125 = 0.15 mm of copper, which
    is below the pour's 0.25 mm min_thickness, so the filler deleted every neck
    and then deleted every cell as an isolated island -- 355.7 mm2 of copper gone
    and the texture replaced by hexagonal bites out of the pour edge. The neck
    accounting has to subtract the caps or the tool ships that.
    """
    return slot_mm / 2.0 if cap == "round" else 0.0


class NoCutError(RuntimeError):
    """Subtract mode had walls to cut and cut none of them.

    THE SILENT NO-OP THIS EXISTS TO STOP, measured on SatoshiStarter with
    spectre-cells at --tile-mm 3.0 and the DEFAULTS: 23 tiles placed on F.Cu,
    233 walls found, 0 walls cut, 0 keepout zones emitted, 0.000 mm2 of copper
    removed -- and the run printed PASS on every connectivity check, wrote a
    .kicad_pcb, and exited 0. Every check was honest in isolation: the ground
    plane did not move, no component was isolated, no island was dropped. They
    were all satisfied because NOTHING HAPPENED, and none of them was watching
    for that.

    The arithmetic, since it is not obvious. A spectre's edge at equal-area
    tile_mm is tile_mm/sqrt(3+3*sqrt3) = 0.34930*tile_mm, so 1.0479 mm at
    tile 3.0. midedge leaves neck_mm of copper in the middle and cuts the two
    ends, and a ROUND cap (the default) overhangs its endpoint by slot_mm/2 at
    each end of each cut. So each end span is

        (1.0479 - 0.50)/2 - 2*(0.25/2) = 0.2739 - 0.25 = 0.0239 mm

    which is below --min-cut-mm 0.15 and is dropped. Both ends, every wall.
    Dropping a short slot is correct in itself -- it only ever adds copper, so
    it cannot break connectivity -- but dropping ALL of them means the texture
    was not applied, and that has to be said out loud rather than reported as a
    pass. The hex kinds are unaffected: hex at tile 3.0 has a 1.861 mm edge and
    keeps 0.605 mm of cut per end.
    """

    def __init__(self, message, layer="", walls=0, wall_mm=0.0, neck_mm=0.0,
                 slot_mm=0.0, cap="", min_cut_mm=0.0, span_mm=0.0):
        super().__init__(message)
        self.layer = layer
        self.walls = walls
        self.wall_mm = wall_mm
        self.neck_mm = neck_mm
        self.slot_mm = slot_mm
        self.cap = cap
        self.min_cut_mm = min_cut_mm
        self.span_mm = span_mm


def neck_cuts(p0, p1, neck_mm, style, min_cut_mm, cap_extend=0.0):
    """Split one wall into the sub-segments that are actually cut.

    `neck_mm` is the width of COPPER that survives -- the tie-neck itself, after
    the slot caps have taken their bite. The centreline gap is therefore
    neck_mm + 2*cap_extend, and callers pass cap_extend=cap_extend_mm(slot, cap).

    A wall too short to carry its neck plus a worthwhile cut yields no slot at
    all. Dropping a slot only ever ADDS copper, so it can never break
    connectivity; it is always the safe failure direction.
    """
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    if L <= 0:
        return []

    def at(t):
        return (x0 + dx * t / L, y0 + dy * t / L)

    gap = neck_mm + 2.0 * cap_extend      # centreline gap for an interior neck
    end = neck_mm + cap_extend            # centreline inset for an end neck

    if style in ("none", "forest"):
        spans = [(0.0, L)]          # whole wall; acyclicity comes from selection
    elif style == "midedge":
        h = (L - gap) / 2.0
        spans = [(0.0, h), (L - h, L)]
    elif style == "vertex":
        spans = [(end, L - end)]
    elif style == "both":
        mid = L / 2.0
        spans = [(end, mid - gap / 2.0), (mid + gap / 2.0, L - end)]
    else:
        raise ValueError("unknown neck style %r; have %s"
                         % (style, ", ".join(NECK_STYLES)))
    return [(at(a), at(b)) for a, b in spans if (b - a) >= min_cut_mm]


def wall_cut_audit(edges, neck_mm, style, min_cut_mm, cap_extend=0.0):
    """Classify every wall by whether its cut joins the wall's two endpoints.

    Returns (joining_walls, stats). A wall only matters to the forest test if its
    slot runs unbroken from endpoint to endpoint, because only such a wall can be
    part of a cycle of slots. So:

      - a wall with no cut at all is not a wall (dropping a slot only adds copper)
      - a NECKED wall carries a gap, so it never joins its endpoints, and a wall
        set in which no wall joins its endpoints is trivially acyclic
      - `none` and `forest` cut whole walls, so those DO join, and they are the
        only styles whose acyclicity has to be earned -- `none` fails, `forest`
        passes by construction

    `min_gap_mm` is the narrowest strip of copper any neck leaves behind. It is
    the number that has to clear the zone's min_thickness, because the filler
    deletes copper features thinner than that and a deleted neck is an isolated
    cell.
    """
    joining = []
    stats = {"walls": len(edges), "cut": 0, "uncut": 0, "joining": 0, "necks": 0}
    min_gap = float("inf")
    for a, b in edges:
        cuts = neck_cuts(a, b, neck_mm, style, min_cut_mm, cap_extend)
        if not cuts:
            stats["uncut"] += 1
            continue
        stats["cut"] += 1
        gaps = cut_gaps_mm(a, b, cuts)
        if not gaps:
            joining.append((a, b))
            stats["joining"] += 1
        else:
            stats["necks"] += len(gaps)
            min_gap = min(min_gap, min(gaps))
    stats["min_gap_mm"] = None if min_gap == float("inf") else min_gap
    # The copper that actually survives: the centreline gap less the two slot
    # caps that bite into it. Exact for midedge (both caps belong to this wall).
    # For vertex the two caps belong to two different walls meeting at an angle,
    # so this under-reports the true bridge -- the pessimistic direction.
    stats["bridge_mm"] = (None if min_gap == float("inf")
                          else min_gap - 2.0 * cap_extend)
    return joining, stats


def stadium_ring(a, b, width_mm, cap="round", cap_seg=4):
    """A slot of `width_mm` about the segment a->b, as one closed ring in mm.

    `round` caps add a `cap_seg`-step arc at each end, so the slot ends are
    rounded rather than square -- fewer sharp interior corners for the filler to
    resolve, and the cap does not overhang the segment end the way a square cap's
    corners do.
    """
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    if L <= 0:
        return []
    ux, uy = dx / L, dy / L
    px, py = -uy, ux                       # unit normal
    h = width_mm / 2.0
    if cap == "square":
        return [(x0 + px * h, y0 + py * h), (x1 + px * h, y1 + py * h),
                (x1 - px * h, y1 - py * h), (x0 - px * h, y0 - py * h)]
    ring = [(x0 + px * h, y0 + py * h), (x1 + px * h, y1 + py * h)]
    for i in range(1, cap_seg):
        t = math.pi * i / cap_seg
        c, s = math.cos(t), math.sin(t)
        ring.append((x1 + (px * c + ux * s) * h, y1 + (py * c + uy * s) * h))
    ring.append((x1 - px * h, y1 - py * h))
    ring.append((x0 - px * h, y0 - py * h))
    for i in range(1, cap_seg):
        t = math.pi * i / cap_seg
        c, s = math.cos(t), math.sin(t)
        ring.append((x0 - (px * c + ux * s) * h, y0 - (py * c + uy * s) * h))
    return ring


def slot_length_mm(cuts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in cuts)


def cut_gaps_mm(p0, p1, cuts):
    """The individual runs of UNCUT copper along the wall p0->p1, in mm.

    Reported individually rather than summed: `vertex` style leaves neck_mm at
    each end, and a total of 2*neck_mm would flatter the narrowest bridge by a
    factor of two. What has to clear min_thickness is the narrowest single bridge.
    """
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L <= 0:
        return []
    spans = sorted((math.hypot(a[0] - p0[0], a[1] - p0[1]),
                    math.hypot(b[0] - p0[0], b[1] - p0[1])) for a, b in cuts)
    gaps = []
    cursor = 0.0
    for s, e in spans:
        if s - cursor > 1e-9:
            gaps.append(s - cursor)
        cursor = max(cursor, e)
    if L - cursor > 1e-9:
        gaps.append(L - cursor)
    return gaps


# ==============================================================================
# PART 2 -- BOARD EMISSION
# ==============================================================================

@dataclass
class TextureOptions:
    mode: str = "subtract"
    tiling: str = "hex"
    tile_mm: float = 2.0
    # In subtract mode this is the width of copper REMOVED along each wall.
    # In add mode it is the width of copper NOT ADDED there -- the gutter
    # between neighbouring tiles in solid fill, and the stroke width in outline
    # fill. Same knob, same picture, opposite sign; that is what makes the two
    # modes comparable at a glance.
    slot_mm: float = 0.25
    # ADD MODE. solid: each tile becomes one filled copper island, shrunk by
    # slot_mm/2 so neighbours do not merge. outline: only the tile walls are
    # drawn, as strokes of slot_mm.
    add_fill: str = "solid"
    # ADD MODE. Netname for the added copper, or None to leave it floating.
    add_net: str | None = None
    neck_mm: float = 0.5
    neck_style: str = "midedge"
    cap: str = "round"
    cap_seg: int = 4
    min_cut_mm: float = 0.15
    seed: int = 0
    # Which layers actually get cut. Ingest reasons about F.Cu+In1.Cu as one
    # side because the obstacles are shared, but cutting the buried plane buys
    # nothing visually and costs real plane impedance, so the default is the
    # outer layer only.
    tex_layers: list = field(default_factory=list)
    clip_slots_to_permitted: bool = True
    island_probe: bool = True
    px_per_mm: float = 40.0
    # WHICH RECTANGLE THE TILING IS GENERATED OVER, and it is not a cosmetic
    # choice. "permitted": this layer's permitted bbox -- the original
    # behaviour, and it moves whenever the copper moves, so F.Cu and B.Cu get
    # different windows and no two runs are comparable. "board": the board
    # outline deflated by the edge inset, one frame for every layer of the run,
    # which is what makes a generated field a function of (board, tile_mm, seed)
    # alone. "auto" picks board for the board-first kinds and permitted for the
    # lattice kinds, which keeps every documented lattice run byte-identical.
    tile_frame: str = "auto"


@dataclass
class LayerTexture:
    layer_name: str = ""
    side: str = ""
    net: str = ""
    # THE FULL TILE LEDGER, because tiles_generated alone hides a whole stage.
    # It is counted AFTER tilings.generate()'s own whole-tile-vs-frame filter, so
    # under the board-first frame the tiles that overhang the board outline used
    # to vanish silently between "offered" and "generated".
    tiles_offered: int = 0                # what the tiling produced, pre-filter
    tiles_outside_frame: int = 0          # dropped for overhanging the frame
    tiles_generated: int = 0              # what generate() returned
    tiles_placed: int = 0
    tiles_dropped: int = 0                # dropped by the copper mask
    # THE DENOMINATOR, carried here rather than left on the ingest result.
    # Every coverage figure this run reports is a fraction of it, and it was
    # reachable only by dividing add_area_mm2 by add_pct_of_permitted -- which
    # is 0/0 in subtract mode, so the run's own JSON could not state the area
    # the percentages were taken against. Copied at the point both objects are
    # in scope; nothing downstream has to hold the ingest results.
    permitted_mm2: float = 0.0
    # tile area = sum of the surviving tiles. NOT the copper area: each tile is
    # inset by half a gutter before emission, so on this board 274 tiles are
    # 2466.0 mm2 of tile and 1982.3 mm2 of copper.
    tile_area_mm2: float = 0.0
    tile_frame_mm: tuple = ()
    tile_frame_source: str = ""
    fragments_total: int = 0
    fragments_populated: int = 0
    fragment_hits: list = field(default_factory=list)   # [(idx, n, area_mm2)]
    worst_accepted_residual_mm2: float = 0.0
    edge_stats: dict = field(default_factory=dict)
    cut_stats: dict = field(default_factory=dict)
    forest_ok: bool = False
    forest_detail: tuple = ()
    slot_outlines: int = 0
    zones_emitted: int = 0
    slot_area_mm2: float = 0.0
    slot_area_in_pour_mm2: float = 0.0
    slot_length_mm: float = 0.0
    fill_before_mm2: float = 0.0
    fill_after_mm2: float = 0.0
    components_before: int = 0
    components_after: int = 0
    components_before_8: int = 0
    components_after_8: int = 0
    areas_before: list = field(default_factory=list)
    areas_after: list = field(default_factory=list)
    island_probe_components: int = None
    island_probe_areas: list = field(default_factory=list)
    island_probe_fill_mm2: float = 0.0
    min_thickness_mm: float = 0.0
    # --- add mode ---
    mode: str = "subtract"
    add_fill: str = ""
    add_net: str = ""
    add_area_mm2: float = 0.0             # copper laid down
    add_pieces: int = 0                   # separate copper islands created
    add_pct_of_permitted: float = 0.0
    add_pct_of_board: float = 0.0
    shapes_emitted: int = 0
    tiles_emptied_by_gutter: int = 0
    # The proof for requirement 2. Not "the areas are equal" -- an exact
    # symmetric difference of the fill polygons before and after. Two different
    # regions can share an area; they cannot share a symmetric difference of 0.
    fill_symdiff_mm2: float = None
    # SHA-256 over the surviving tile GEOMETRY, quantised to 1 pm. The
    # reproducibility check, and deliberately not a hash of the .kicad_pcb:
    # see placed_rings below for why the file can never hash equal.
    placed_digest: str = ""
    warnings: list = field(default_factory=list)
    slots = None
    added = None                          # SHAPE_POLY_SET of the added copper
    # The tiles that SURVIVED the copper mask, as closed rings in mm. This is
    # the fingerprint itself -- not the emitted copper, which has already been
    # shrunk by the gutter and clipped, and not the permitted mask. Kept on the
    # result so the render step does not have to re-run the placement and risk
    # drawing a different set from the one that was measured.
    placed_rings = None


def net_fill(board, lid, net):
    """Union of the FILLED copper of `net` on layer `lid`, skipping rule areas."""
    tot = _sps()
    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        if z.IsOnLayer(lid) and z.GetNetname() == net and z.HasFilledPolysForLayer(lid):
            tot.Append(z.GetFilledPolysList(lid))
    return tot


def zone_min_thickness_mm(board, lid, net):
    """Largest min_thickness among the pours being cut.

    The filler deletes copper features thinner than a zone's min_thickness. A
    tie-neck narrower than that is silently removed, and a removed neck is an
    isolated cell -- the exact failure the necks exist to prevent. So this is a
    hard input to validation, not a curiosity.
    """
    vals = [z.GetMinThickness() / 1e6 for z in board.Zones()
            if not z.GetIsRuleArea() and z.IsOnLayer(lid)
            and z.GetNetname() == net]
    return max(vals) if vals else 0.0


def _fragments_with_bbox(poly):
    """[(sps, (x0,y0,x1,y1))] -- one entry per connected region of `poly`.

    Each outline of a Simplify()-d set, together with its holes, is one connected
    region, and regions are disjoint. A tile is connected, so a tile that lies
    wholly inside `poly` lies wholly inside exactly one of these. That turns the
    subset test from one boolean against the whole region into a bbox reject plus
    one boolean against a small region.
    """
    out = []
    for i in range(poly.OutlineCount()):
        one = _sps()
        one.AddOutline(poly.Outline(i))
        for h in range(poly.HoleCount(i)):
            one.AddHole(poly.Hole(i, h), 0)
        bb = poly.Outline(i).BBox()
        out.append((one, (nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetTop()),
                          nm_to_mm(bb.GetRight()), nm_to_mm(bb.GetBottom()))))
    return out


def place_tiles_by_fragment(permitted, rings, tol_mm2=1e-6):
    """place_tiles, plus WHICH permitted fragment each kept tile landed in.

    Returns (kept, n_dropped, worst_residual, frag_of_kept, frag_areas).
    `frag_of_kept[i]` is the index of the fragment holding `kept[i]`, and
    `frag_areas` is every fragment's area in mm2 (holes subtracted), so a caller
    can say how much of the permitted region the texture actually reached rather
    than only how many tiles it placed. On this board that distinction matters:
    one fragment carries 95.7% of the permitted F.Cu area and the other thirteen
    are dust, so "13 of 14 fragments empty" and "the texture covers the board"
    are both true at once.
    """
    frags = _fragments_with_bbox(permitted)
    areas = [_area_mm2(one) for one, _ in frags]
    kept = []
    where = []
    dropped = 0
    worst = 0.0
    for ring in rings:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        tb = (min(xs), min(ys), max(xs), max(ys))
        hit = None
        for k, (frag, fb) in enumerate(frags):
            if tb[0] < fb[0] or tb[1] < fb[1] or tb[2] > fb[2] or tb[3] > fb[3]:
                continue
            probe = _sps()
            _add_ring(probe, ring)
            probe.BooleanSubtract(frag)
            resid = _area_mm2(probe)
            if resid <= tol_mm2:
                worst = max(worst, resid)
                hit = k
                break
        if hit is None:
            dropped += 1
        else:
            kept.append(ring)
            where.append(hit)
    return kept, dropped, worst, where, areas


def place_tiles(permitted, rings, tol_mm2=1e-6):
    """Keep only the tiles lying ENTIRELY inside `permitted`. No clipping.

    Returns (kept, n_dropped, worst_accepted_residual_mm2). The test is exact:
    subtract the permitted region from the tile and require nothing to be left.
    The residual of every ACCEPTED tile is reported so that a tolerance quietly
    admitting partly-outside tiles would be visible as a residual near the
    tolerance rather than at zero.
    """
    kept, dropped, worst, _, _ = place_tiles_by_fragment(permitted, rings,
                                                         tol_mm2)
    return kept, dropped, worst


def build_slot_poly(cuts, slot_mm, cap="round", cap_seg=4):
    """Union of all slot bodies as a SHAPE_POLY_SET.

    Simplify() is a non-zero-fill union, so overlapping slot bodies merge instead
    of cancelling. Skipping it would let two slots crossing at a tiling vertex
    even-odd their overlap back into copper -- a hole in the middle of a
    junction, which is exactly the kind of defect that survives every area check
    because the areas still add up.
    """
    poly = _sps()
    for a, b in cuts:
        ring = stadium_ring(a, b, slot_mm, cap, cap_seg)
        if ring:
            _add_ring(poly, ring)
    poly.Simplify()
    return poly


def build_add_poly(rings, fill, gutter_mm, max_error, cap="round", cap_seg=4):
    """ADD MODE. The copper to lay down for a set of tiles. -> (poly, n_emptied).

    THE GUTTER IS NOT OPTIONAL, AND THIS IS THE ONE PLACE ADD MODE CANNOT BE THE
    MIRROR OF SUBTRACT MODE. A tiling tiles the plane: neighbouring tiles share
    whole edges. Appending the raw tile polygons and calling Simplify() -- which
    is a union -- therefore merges every tile in a connected clump into ONE
    polygon with no internal boundary at all. The output is not a texture, it is
    a solid sheet of copper with a ragged edge, and every area check still
    passes because the area is right. So each tile is deflated by gutter_mm/2
    INDIVIDUALLY, before the union, and the union then has nothing to merge.

    A tile smaller than the gutter deflates to nothing. Those are counted and
    returned rather than silently vanishing, because "0 tiles placed" and "412
    tiles placed and then dissolved" look identical in the tile count.
    """
    poly = _sps()
    emptied = 0
    if fill == "solid":
        d = mm_to_nm(gutter_mm / 2.0)
        for ring in rings:
            one = _sps()
            _add_ring(one, ring)
            if d > 0:
                one.Deflate(int(d), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                            max_error)
            if one.OutlineCount() == 0 or one.Area() <= 0:
                emptied += 1
                continue
            poly.Append(one)
        poly.Simplify()
        return poly, emptied
    if fill != "outline":
        raise ValueError("--add-fill %r; have solid, outline" % fill)
    # Outline fill. tile_edges() dedups the shared walls, so a wall between two
    # tiles is stroked once and the honeycomb has uniform line weight; stroking
    # per tile would double it on every interior wall and leave the border walls
    # thin.
    edges, _ = tile_edges(rings)
    for a, b in edges:
        r = stadium_ring(a, b, gutter_mm, cap, cap_seg)
        if r:
            _add_ring(poly, r)
    poly.Simplify()
    return poly, 0


def emit_copper_shapes(board, lid, poly, net_code, name_prefix, group_name=None):
    """ADD MODE. Lay `poly` down as real copper. -> (n_shapes, n_holes_fractured).

    PCB_SHAPE polygons, not zones, and the reason is the filler. Every pour on
    this board carries island_removal_mode = ALWAYS. A tile emitted as a ZONE is
    a fill with no pad on it, i.e. an island, and the filler DELETES it -- the
    texture would vanish on the next refill and the board would look untextured
    while the file said otherwise. A PCB_SHAPE is not a fill, so the filler never
    touches it; it is copper in the gerber and copper to DRC, and it is still
    there after any number of refills.

    PCB_SHAPE is a BOARD_CONNECTED_ITEM in KiCad 10, so SetNetCode() works and
    the written s-expression carries `(net "GNDREF")`. Net code 0 writes no net
    tag at all, which is the floating case.

    Fracture() first for the same reason emit_keepouts() does: one shape holds
    one `(gr_poly (pts ...))` and cannot express a hole.
    """
    work = _sps()
    work.Append(poly)
    holes = sum(work.HoleCount(i) for i in range(work.OutlineCount()))
    if holes:
        work.Fracture()
    shapes = []
    for i in range(work.OutlineCount()):
        one = _sps()
        one.AddOutline(work.Outline(i))
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_POLY)
        s.SetPolyShape(one)
        s.SetFilled(True)
        # Width 0: a filled polygon with a stroke would be the polygon INFLATED
        # by half the stroke, which would eat into the clearance the permitted
        # region was built to guarantee.
        s.SetWidth(0)
        s.SetLayer(lid)
        if net_code:
            s.SetNetCode(net_code)
        board.Add(s)
        shapes.append(s)
    if group_name and shapes:
        try:
            g = pcbnew.PCB_GROUP(board)
            g.SetName(group_name)
            for s in shapes:
                g.AddItem(s)
            board.Add(g)
        except Exception:
            pass          # grouping is a convenience for the human, not a result
    return len(shapes), holes


def emit_keepouts(board, lid, slots, name_prefix, group_name=None):
    """One board-level rule-area ZONE per slot component. Returns the count.

    Board level, not footprint level: a footprint-borne copper keepout is
    silently ignored by the KiCad 10 filler.

    One zone per component because the KiCad 10 zone writer emits exactly one
    `(polygon ...)` per zone -- measured, a five-outline rule area returns from
    save+reload carrying one. Fracture() first so that any component with a hole
    becomes a simple ring; a zone cannot express a hole either.

    AddPolygon(), not SetOutline(): SetOutline() takes ownership of the
    SHAPE_POLY_SET and Python then frees it too, which segfaults as soon as the
    temporary goes out of scope.
    """
    work = _sps()
    work.Append(slots)
    holes = sum(work.HoleCount(i) for i in range(work.OutlineCount()))
    if holes:
        work.Fracture()
    zones = []
    for i in range(work.OutlineCount()):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetLayer(lid)
        z.AddPolygon(work.Outline(i))
        z.SetZoneName("%s_%05d" % (name_prefix, i))
        board.Add(z)
        zones.append(z)
    if group_name and zones:
        try:
            g = pcbnew.PCB_GROUP(board)
            g.SetName(group_name)
            for z in zones:
                g.AddItem(z)
            board.Add(g)
        except Exception:
            pass          # grouping is a convenience for the human, not a result
    return len(zones), holes


# --- connectivity: an independent raster flood fill ---------------------------
# The zone filler is NOT a witness here. Every pour on this board carries
# island_removal_mode = ALWAYS, so a texture that isolates a cell does not leave
# a floating island for a checker to find -- the filler DELETES it. A
# component count taken from the filled polygons alone would read 1 for a
# catastrophically broken texture. Two things therefore have to agree:
#
#   1. the component count of the rasterised fill, and
#   2. area conservation: copper removed == slot area inside the pour
#
# and for a direct look at the topology the filler is hiding, --island-probe
# refills a throwaway copy with island removal set to NEVER and counts again.

def raster_mask(poly, bbox_mm, px_per_mm):
    """Rasterise a SHAPE_POLY_SET into a bool array. Needs numpy + PIL."""
    import numpy as np
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = bbox_mm
    w = max(1, int(math.ceil((x1 - x0) * px_per_mm)))
    h = max(1, int(math.ceil((y1 - y0) * px_per_mm)))
    acc = np.zeros((h, w), dtype=bool)

    def xf(pt):
        return ((pt[0] - x0) * px_per_mm, (pt[1] - y0) * px_per_mm)

    # Region by region, outline then its holes, OR-ed together. Drawing every
    # outline and then every hole would let one region's hole punch a different
    # region that legitimately fills it.
    for i in range(poly.OutlineCount()):
        chain = poly.Outline(i)
        ring = [xf((nm_to_mm(chain.CPoint(j).x), nm_to_mm(chain.CPoint(j).y)))
                for j in range(chain.PointCount())]
        if len(ring) < 3:
            continue
        img = Image.new("1", (w, h), 0)
        d = ImageDraw.Draw(img)
        d.polygon(ring, fill=1)
        for hh in range(poly.HoleCount(i)):
            hc = poly.Hole(i, hh)
            hr = [xf((nm_to_mm(hc.CPoint(j).x), nm_to_mm(hc.CPoint(j).y)))
                  for j in range(hc.PointCount())]
            if len(hr) >= 3:
                d.polygon(hr, fill=0)
        acc |= np.array(img, dtype=bool)
    return acc


def component_stats(mask, px_per_mm, connectivity=4):
    """(count, [component areas in mm2, descending], n_runs).

    Connected components of a bool raster by run-length union-find. Runs, not
    pixels: a 4400x1500 raster is 6.6M pixels but only ~10^5 runs, so this stays
    in Python without a scipy dependency (there is no scipy in KiCad's Python).

    The AREAS matter as much as the count. A bare count says "4 before, 4 after",
    which is consistent with the texture having destroyed one component and
    created another. The area list makes the claim exact: on this board the
    untextured F.Cu GNDREF fill is four pieces of 1562.485 / 126.463 / 6.185 /
    3.365 mm2, and after texturing it is 1494.642 / 126.463 / 6.185 / 3.365 --
    three components untouched to the milli-mm2 and one smaller by exactly the
    slot area. That is a much stronger statement than any count.

    4-connectivity is the conservative choice for copper: it splits regions that
    8-connectivity would join through a single diagonal pixel, so a low count
    under 4-connectivity is the stronger claim. Both are reported and should
    agree for features many pixels wide.
    """
    import numpy as np

    h, _ = mask.shape
    parent = []
    size = []

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            size[ra] += size[rb]
            size[rb] = 0

    prev = []          # [(start, end, label)] for the row above
    pad = 0 if connectivity == 4 else 1
    for y in range(h):
        row = mask[y].astype(np.int8)
        d = np.diff(np.concatenate(([0], row, [0])))
        starts = np.flatnonzero(d == 1).tolist()
        ends = np.flatnonzero(d == -1).tolist()
        cur = []
        j = 0
        for s, e in zip(starts, ends):
            lab = len(parent)
            parent.append(lab)
            size.append(e - s)
            # Runs are half-open [s, e). Two runs on adjacent rows touch under
            # 4-connectivity iff the intervals OVERLAP (s1 < e2 and s2 < e1), and
            # under 8-connectivity iff they overlap or abut (s1 <= e2 and
            # s2 <= e1). Writing `prev[j][1] < s` here instead of `<= s` joined
            # runs that merely abut, which silently turned 4-connectivity into
            # 8-connectivity -- i.e. into the LESS conservative test, in the one
            # place where the conservative answer is the whole point.
            while j < len(prev) and prev[j][1] + pad <= s:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < e + pad:
                union(prev[k][2], lab)
                k += 1
            cur.append((s, e, lab))
        prev = cur
    roots = {find(i) for i in range(len(parent))}
    px = 1.0 / (px_per_mm * px_per_mm)
    areas = sorted((size[r] * px for r in roots), reverse=True)
    return len(roots), areas, len(parent)


def count_components(mask, px_per_mm=1.0, connectivity=4):
    n, _, runs = component_stats(mask, px_per_mm, connectivity)
    return n, runs


def texture_bbox(results, margin_mm=2.0):
    """Raster window for the flood fill: the whole POUR, not the permitted region.

    This distinction is a bug I shipped and then measured. Sizing the window to
    the permitted region crops the pour, and a cropped pour splits into more
    components than it has: on this board a front-only run put the window at
    x >= 118.78 (the permitted region starts east of the HS1 envelope) and the
    F.Cu fill then read as 3 components of 765.814 / 126.389 / 6.205 mm2 instead
    of its true 4 of 1562.485 / 126.463 / 6.185 / 3.365. Comparing before against
    after under the same crop still cancels, but a component held together by
    copper OUTSIDE the window would be reported as two, and an isolation created
    just outside it would be invisible. So the window covers every pour being
    cut, whether or not texture can reach that part of it.
    """
    xs, ys = [], []
    for r in results:
        for p in (r.pour, r.permitted):
            if p is None or p.OutlineCount() == 0:
                continue
            bb = p.BBox()
            xs += [nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetRight())]
            ys += [nm_to_mm(bb.GetTop()), nm_to_mm(bb.GetBottom())]
    if not xs:
        return None
    return (min(xs) - margin_mm, min(ys) - margin_mm,
            max(xs) + margin_mm, max(ys) + margin_mm)


# --- the picture --------------------------------------------------------------
# Rendered from the FILLED polygons the zone filler actually produced, not from
# the slot polygons that were asked for. If the filler closed a slot, ate a neck
# or dropped a cell, this picture shows it. A render of the requested geometry
# would show a perfect texture on a broken board.

SUBSTRATE = (14, 58, 40)
COPPER = (206, 172, 96)
COPPER_DIM = (150, 124, 70)
OUTSIDE = (10, 10, 12)


def all_copper_on_layer(board, lid, max_error, net=None):
    """Every piece of copper on one layer as a SHAPE_POLY_SET, zero clearance.

    GRAPHICS ON COPPER LAYERS COUNT, and leaving them out was a real defect:
    add mode emits its texture as PCB_SHAPE polygons, and the first
    board-appearance render drew a board with no texture on it whatsoever. The
    copper was in the file and would have been in the gerber -- only the picture
    was wrong, which is the worst way for this to fail, because the picture is
    what the decision gets made on. Footprint graphics on copper are included
    for the same reason; SatoshiStarter has none, so this costs nothing here and
    stops the same hole reopening on a board that does.
    """
    poly = _sps()
    for pad in board.GetPads():
        if pad.IsOnLayer(lid) and (net is None or pad.GetNetname() == net):
            pad.TransformShapeToPolygon(poly, lid, 0, max_error, pcbnew.ERROR_INSIDE)
    for t in board.Tracks():
        if t.IsOnLayer(lid) and (net is None or t.GetNetname() == net):
            t.TransformShapeToPolygon(poly, lid, 0, max_error, pcbnew.ERROR_INSIDE)
    for d in board.GetDrawings():
        if d.GetLayer() == lid and (net is None or d.GetNetname() == net):
            d.TransformShapeToPolygon(poly, lid, 0, max_error, pcbnew.ERROR_INSIDE)
    for fp in board.GetFootprints():
        for d in fp.GraphicalItems():
            if d.GetLayer() == lid:
                try:
                    d.TransformShapeToPolygon(poly, lid, 0, max_error,
                                              pcbnew.ERROR_INSIDE)
                except Exception:
                    pass
    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        if z.HasFilledPolysForLayer(lid) and (net is None or z.GetNetname() == net):
            poly.Append(z.GetFilledPolysList(lid))
    poly.Simplify()
    return poly


def render_copper_png(board, lid, out_path, px_per_mm=20.0, bbox=None,
                      max_error=5000, label="", mirror=False):
    """Copper-on-substrate view of one layer. Returns (path, w, h)."""
    import numpy as np
    from PIL import Image, ImageDraw

    if bbox is None:
        bb = board.GetBoardEdgesBoundingBox()
        bbox = (nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetTop()),
                nm_to_mm(bb.GetRight()), nm_to_mm(bb.GetBottom()))
    x0, y0, x1, y1 = bbox

    outline = _sps()
    board.GetBoardPolygonOutlines(outline, True)
    cu = all_copper_on_layer(board, lid, max_error)

    m_board = raster_mask(outline, bbox, px_per_mm)
    m_cu = raster_mask(cu, bbox, px_per_mm)
    h, w = m_board.shape

    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = OUTSIDE
    img[m_board] = SUBSTRATE
    img[m_cu & m_board] = COPPER
    img[m_cu & ~m_board] = COPPER_DIM

    pic = Image.fromarray(img, "RGB")
    if mirror:
        pic = pic.transpose(Image.FLIP_LEFT_RIGHT)
    if label:
        d = ImageDraw.Draw(pic)
        d.text((8, 8), label, fill=(235, 235, 240))
    pic.save(out_path)
    return out_path, w, h


# --- what the board LOOKS like ------------------------------------------------
# Tone table from docs/pcb-palette.md, values copied from tools/w0_spike.py
# TONES so this cannot drift from the quantiser the art is assigned with.
# SatoshiStarter is a BLACK-mask board, which is why T5 is (25, 25, 28) and why
# add-mode texture reads as a sheen and not as a graphic: T6 minus T5 is 19
# counts of red. That small number IS the requirement -- "not visibly gold, and
# just a board texture".
# Was a HAND-TYPED copy of the table, carrying a comment saying it was copied
# "so this cannot drift". Three copies of one table is how it drifts.
# Resolved from tools/palette.py now. Black by default, which is what
# SatoshiStarter is -- and that is why T5 is (25, 25, 28) and why add-mode
# texture reads as a sheen and not as a graphic: T6 minus T5 is 19 counts of
# red, 7.87 L*. That small number IS the requirement here ("not visibly
# gold, and just a board texture"), and it is the same number that makes
# tools/fidelity.py refuse to call a tone that close to the board a drawn
# graphic.
import palette as _palette_mod                     # noqa: E402
TONE = {t.id: tuple(t.rgb) for t in
        _palette_mod.palette_for("black", allow_provisional=True).tones}
OUTSIDE_RGB = (10, 10, 12)

# Which layers make up a side's appearance.
SIDE_APPEARANCE = {
    "front": {"cu": "F.Cu", "mask": "F.Mask", "buried": "In1.Cu",
              "silk": "F.SilkS"},
    "back":  {"cu": "B.Cu", "mask": "B.Mask", "buried": "In2.Cu",
              "silk": "B.SilkS"},
}


def _layer_graphics_poly(board, lid, max_error):
    """Every graphic and text item on one layer, as polygons. -> (poly, n, n_fail).

    n_fail is returned rather than swallowed. Some item classes have no
    TransformShapeToPolygon in this build, and a renderer that quietly skipped
    them would draw a board with pieces of silk missing and look correct.
    """
    poly = _sps()
    n = fail = 0
    def take(it):
        nonlocal n, fail
        try:
            it.TransformShapeToPolygon(poly, lid, 0, max_error,
                                       pcbnew.ERROR_OUTSIDE)
            n += 1
        except Exception:
            fail += 1
    for d in board.GetDrawings():
        if d.GetLayer() == lid:
            take(d)
    for fp in board.GetFootprints():
        for d in fp.GraphicalItems():
            if d.GetLayer() == lid:
                take(d)
        for t in (fp.Reference(), fp.Value()):
            if t is not None and t.GetLayer() == lid and t.IsVisible():
                take(t)
    poly.Simplify()
    return poly, n, fail


def _mask_open_poly(board, lid, max_error):
    """Solder-mask OPENINGS on one mask layer: pad apertures plus graphics."""
    poly = _sps()
    for pad in board.GetPads():
        if pad.IsOnLayer(lid):
            pad.TransformShapeToPolygon(poly, lid, 0, max_error,
                                        pcbnew.ERROR_OUTSIDE)
    g, _, _ = _layer_graphics_poly(board, lid, max_error)
    poly.Append(g)
    poly.Simplify()
    return poly


def _tone_rgb(name, gain):
    """Tone colour, with the under-mask copper contrast scaled by `gain`.

    gain 1.0 is the board. Above 1.0 only T6 and T7 move, and only away from
    T5 along the line that separates them, so the exaggeration is exactly and
    only "how much darker mask-over-copper is than bare mask" -- the one
    difference add-mode texture lives in. Nothing else in the picture changes,
    which is what makes a gained render still readable as the same board.
    """
    rgb = TONE[name]
    if gain == 1.0 or name not in ("T6", "T7"):
        return rgb
    base = TONE["T5"]
    return tuple(int(max(0, min(255, round(b + (c - b) * gain))))
                 for b, c in zip(base, rgb))


def render_board_appearance(board, side, out_path, px_per_mm=24.0, bbox=None,
                            max_error=5000, label="", mirror=False, gain=1.0):
    """The board as it will LOOK, through the palette's decision tree.

        mask open?  -> copper? T2 : (buried? T4 : T3)
        mask closed -> copper? T6 : (buried? T7 : T5)

    with silk painted last because it sits on top of everything. Built from the
    FILLED zone polygons and the real pad/track shapes, so what it shows is what
    the filler produced, not what was requested.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    if side not in SIDE_APPEARANCE:
        raise ValueError("side %r; have front, back" % side)
    L = SIDE_APPEARANCE[side]

    if bbox is None:
        bb = board.GetBoardEdgesBoundingBox()
        bbox = (nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetTop()),
                nm_to_mm(bb.GetRight()), nm_to_mm(bb.GetBottom()))

    outline = _sps()
    board.GetBoardPolygonOutlines(outline, True)
    cu_lid = board.GetLayerID(L["cu"])
    bur_lid = board.GetLayerID(L["buried"])
    mask_lid = board.GetLayerID(L["mask"])
    silk_lid = board.GetLayerID(L["silk"])

    m_board = raster_mask(outline, bbox, px_per_mm)
    m_cu = raster_mask(all_copper_on_layer(board, cu_lid, max_error),
                       bbox, px_per_mm)
    m_bur = (raster_mask(all_copper_on_layer(board, bur_lid, max_error),
                         bbox, px_per_mm)
             if bur_lid >= 0 else np.zeros_like(m_board))
    m_open = (raster_mask(_mask_open_poly(board, mask_lid, max_error),
                          bbox, px_per_mm)
              if mask_lid >= 0 else np.zeros_like(m_board))
    silk_poly, n_silk, n_silk_fail = (
        _layer_graphics_poly(board, silk_lid, max_error)
        if silk_lid >= 0 else (_sps(), 0, 0))
    m_silk = raster_mask(silk_poly, bbox, px_per_mm)

    h, w = m_board.shape
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = OUTSIDE_RGB

    inb = m_board
    closed = inb & ~m_open
    openm = inb & m_open
    img[closed & ~m_cu & ~m_bur] = _tone_rgb("T5", gain)
    img[closed & ~m_cu & m_bur] = _tone_rgb("T7", gain)
    img[closed & m_cu] = _tone_rgb("T6", gain)
    img[openm & ~m_cu & ~m_bur] = _tone_rgb("T3", gain)
    img[openm & ~m_cu & m_bur] = _tone_rgb("T4", gain)
    img[openm & m_cu] = _tone_rgb("T2", gain)
    img[inb & m_silk] = _tone_rgb("T1", gain)

    pic = Image.fromarray(img, "RGB")
    if mirror:
        pic = pic.transpose(Image.FLIP_LEFT_RIGHT)
    if label or gain != 1.0 or n_silk_fail:
        d = ImageDraw.Draw(pic)
        txt = label
        if gain != 1.0:
            txt += "   [T6/T7 contrast x%.1f for review, not the board]" % gain
        if n_silk_fail:
            txt += "   [%d silk items unrenderable]" % n_silk_fail
        d.text((8, 8), txt, fill=(235, 235, 240))
    pic.save(out_path)
    return out_path, w, h


# --- visualisation ------------------------------------------------------------

C_BG = (16, 16, 20)
C_OTHER = (46, 56, 74)         # copper on the layer belonging to a DIFFERENT net
C_OBST = (122, 52, 52)         # pour copper a guard removed
C_OK = (86, 214, 142)          # permitted: whole tiles may live here
C_EDGE = (110, 112, 124)       # Edge.Cuts
C_INSET = (68, 70, 82)         # Edge.Cuts deflated by --edge-inset
C_GUIDE = (226, 176, 74)       # HS1 envelope + corridor centreline


def render_mask_png(results, board_bbox_mm, out_path, px_per_mm=6.0, title="",
                    board_outline=None, interior=None, other_pours=None,
                    hs1_rect=None, corridor=None):
    """Draw the permitted mask per layer, stacked vertically.

    The figure is the point of this whole exercise. An area number cannot tell
    you that the permitted region has collapsed into a ring of unusable slivers,
    or that the one big green blob is somewhere the texture would be hidden under
    a connector. A picture can.

    Deliberate choices, each because the first version of this figure misled:

      - obstacles are drawn ONLY where they intersect the pour. Drawn in full
        they wash the whole board red and the eye cannot find the pour at all.
      - copper on the layer belonging to OTHER nets is drawn in dark slate.
        Without it the VCORE plane in the middle of this board reads as a void,
        and the natural conclusion -- "the tool lost the middle of the pour" --
        is wrong. It is another net's copper and was never a candidate.
      - Edge.Cuts and the --edge-inset interior are stroked, so an edge inset
        that does nothing (it does nothing on this board: the pour stops 35 mm
        short of the nearest edge) is visibly doing nothing rather than
        invisibly untested.
      - the HS1 envelope and the corridor centreline are stroked in amber over
        the top, so the two hard-coded, board-specific guards can be checked
        against the red they are supposed to be causing.
    """
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = board_bbox_mm
    pad_mm = 3.0
    W = int(((x1 - x0) + 2 * pad_mm) * px_per_mm)
    H = int(((y1 - y0) + 2 * pad_mm) * px_per_mm)
    band = 34                                  # caption strip under each panel

    n = len(results)
    img = Image.new("RGB", (W, (H + band) * n + 20), C_BG)
    draw = ImageDraw.Draw(img)

    def xf(pt, oy):
        return ((pt[0] - x0 + pad_mm) * px_per_mm,
                (pt[1] - y0 + pad_mm) * px_per_mm + oy)

    def fill(poly, colour, oy):
        if poly is None:
            return
        for ring in _fractured_rings(poly):
            if len(ring) >= 3:
                draw.polygon([xf(p, oy) for p in ring], fill=colour)

    def stroke(poly, colour, oy, width=1):
        if poly is None:
            return
        for i in range(poly.OutlineCount()):
            ch = poly.Outline(i)
            pts = [xf((nm_to_mm(ch.CPoint(j).x), nm_to_mm(ch.CPoint(j).y)), oy)
                   for j in range(ch.PointCount())]
            if len(pts) >= 2:
                draw.line(pts + [pts[0]], fill=colour, width=width)

    for k, res in enumerate(results):
        oy = 20 + k * (H + band)

        if other_pours:
            fill(other_pours.get(res.layer_name), C_OTHER, oy)

        if res.pour is not None and res.obstacles is not None:
            clipped = pcbnew.SHAPE_POLY_SET()
            clipped.Append(res.obstacles)
            clipped.BooleanIntersection(res.pour)
            fill(clipped, C_OBST, oy)

        fill(res.permitted, C_OK, oy)

        stroke(interior, C_INSET, oy)
        stroke(board_outline, C_EDGE, oy)

        if hs1_rect is not None and (
                res.removal_mm2.get("hs1_envelope") is not None):
            r = hs1_rect
            draw.line([xf(p, oy) for p in rect_corners(r)]
                      + [xf(rect_corners(r)[0], oy)], fill=C_GUIDE, width=1)
        if corridor is not None and (
                res.removal_mm2.get("return_corridor") is not None):
            draw.line([xf(corridor[0], oy), xf(corridor[1], oy)],
                      fill=C_GUIDE, width=2)

        cap = (f"{res.layer_name} ({res.side})   pour {res.pour_area_mm2:.1f} mm2 "
               f"[{res.pour_net or 'none'}]   permitted "
               f"{res.permitted_area_mm2:.1f} mm2 = "
               f"{res.permitted_pct_of_pour:.1f}% of pour   "
               f"{res.fragment_count} fragments, largest "
               f"{res.largest_fragment_mm2:.1f} mm2")
        draw.text((6, oy + H + 3), cap, fill=(224, 224, 230))
        cap2 = "  ".join(f"-{k2} {v:.0f}" for k2, v in res.removal_mm2.items() if v > 0)
        draw.text((6, oy + H + 16), "removed: " + (cap2 or "nothing"),
                  fill=(168, 132, 132))

    legend = ("green = permitted (whole tiles only)   red = pour copper a guard "
              "removed   slate = other net's copper   amber = HS1 envelope + "
              "corridor centreline")
    draw.text((6, 6), (title + "   " if title else "") + legend,
              fill=(230, 200, 120))
    img.save(out_path)
    return out_path


# --- the fingerprint image ----------------------------------------------------

C_TILE = COPPER                # the surviving tiles
C_TILE_EDGE = (120, 98, 54)    # hairline between neighbouring tiles
C_FP_BG = C_BG
C_FP_OUTLINE = (70, 72, 84)    # Edge.Cuts, for registration only


def _stamp_font(size):
    """A legible font at `size`, or the bitmap default. Never raises."""
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                     # Pillow < 10.1
        return ImageFont.load_default()


def board_commit(board_path):
    """'<short sha>' or '<short sha>-dirty' for the board's repo, or 'unknown'.

    Stamped into the fingerprint so an image traces back to a board STATE. A
    fingerprint of an unknown board is a picture, not evidence.
    """
    d = str(pathlib.Path(board_path).resolve().parent)
    try:
        sha = subprocess.run(["git", "-C", d, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=20)
        if sha.returncode != 0:
            return "unknown"
        st = subprocess.run(["git", "-C", d, "status", "--porcelain",
                             "--", str(pathlib.Path(board_path).name)],
                            capture_output=True, text=True, timeout=20)
        tag = sha.stdout.strip()
        if st.returncode == 0 and st.stdout.strip():
            tag += "-dirty"
        return tag
    except Exception:
        return "unknown"


def render_fingerprint_png(rings, board_bbox_mm, out_path, px_per_mm=12.0,
                           outline=None, mirror=False, stamp=None,
                           caption=""):
    """THE SURVIVING TILES, and nothing else. One image per side.

    Not render_copper_png (that draws every pad, track and via on the layer),
    not render_board_appearance (that draws the board as it will look), and not
    render_mask_png (that draws the permitted region). Those three answer "what
    did the run do to the board"; this one answers "what IS the fingerprint",
    which is the set of whole tiles that survived the copper mask and nothing
    else. It shares their conventions on purpose -- same bbox-to-pixel mapping
    with a 3 mm pad, same mirror rule for the back side, same caption strip --
    so the four images of one run can be laid side by side and compared.

    Edge.Cuts is stroked as a hairline when `outline` is given. That is a
    registration mark, not a board render: without it two fingerprints of the
    same board at different seeds cannot be visually aligned, and a fingerprint
    that cannot be compared is not doing its job.

    `stamp` is an ordered list of (key, value) pairs burned into the caption.
    It must carry enough to trace the image back to a board state -- tiling,
    tile_mm, level, tile count, edge inset, seed, board commit -- because an
    unlabelled fingerprint is indistinguishable from any other unlabelled
    fingerprint and is therefore worthless as evidence.
    """
    from PIL import Image, ImageDraw

    x0, y0, x1, y1 = board_bbox_mm
    pad_mm = 3.0
    W = max(1, int(((x1 - x0) + 2 * pad_mm) * px_per_mm))
    H = max(1, int(((y1 - y0) + 2 * pad_mm) * px_per_mm))
    band = 74 if (stamp or caption) else 0

    img = Image.new("RGB", (W, H), C_FP_BG)
    draw = ImageDraw.Draw(img)

    def xf(pt):
        return ((pt[0] - x0 + pad_mm) * px_per_mm,
                (pt[1] - y0 + pad_mm) * px_per_mm)

    if outline is not None:
        for i in range(outline.OutlineCount()):
            o = outline.COutline(i)
            pts = [xf((nm_to_mm(o.CPoint(k).x), nm_to_mm(o.CPoint(k).y)))
                   for k in range(o.PointCount())]
            if len(pts) >= 2:
                draw.line(pts + [pts[0]], fill=C_FP_OUTLINE, width=1)

    for r in rings:
        pts = [xf(p) for p in r]
        if len(pts) >= 3:
            draw.polygon(pts, fill=C_TILE, outline=C_TILE_EDGE)

    if mirror:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)

    if band:
        full = Image.new("RGB", (W, H + band), C_FP_BG)
        full.paste(img, (0, 0))
        d2 = ImageDraw.Draw(full)
        d2.line([(0, H), (W, H)], fill=C_FP_OUTLINE, width=1)
        f = _stamp_font(15)
        line = "   ".join("%s %s" % (k, v) for k, v in (stamp or []))
        d2.text((8, H + 8), line, fill=(226, 206, 150), font=f)
        if caption:
            d2.text((8, H + 30), caption, fill=(168, 172, 186),
                    font=_stamp_font(13))
        img = full

    img.save(out_path)
    return out_path, img.size[0], img.size[1]


# The honest label, in one place so both the caption and the report say the
# same thing. Requirement (b) asked for "the Spectre not-quite-supertile that
# represents the board", and "not-quite" used to be doing real work: the old
# level-2 patch was three disconnected lumps filling 64% of their hull, and
# inflating it a third time produced 97 overlapping tile pairs.
#
# That was a defect in the substitution, not a property of the spectre, and it
# has been fixed -- tilings.py was missing the per-generation reflection. The
# patch IS a supertile now: one boundary loop, no holes, no edge claimed by
# three tiles, and it inflates cleanly to level 5 (34649 tiles) with zero
# overlapping pairs under exact integer predicates. The name of this constant is
# kept so nothing downstream breaks; the text it carries is what is true.
NOT_QUITE_SUPERTILE = (
    "supertile: level 2 is 71 tiles with pairwise-disjoint interiors, one "
    "boundary loop and no holes, proved by exact integer predicates in "
    "Z[sqrt 3], and the same substitution runs to level 5 (34649 tiles) with "
    "0 overlapping pairs")


# --- the run ------------------------------------------------------------------

def _import_tilings():
    try:
        import tilings
    except ImportError:                                   # pragma: no cover
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import tilings
    return tilings


# Kinds whose placement is anchored to the BOARD rather than fitted to a window.
# For these the frame is not a hint about where to fill, it is the definition of
# the pattern, so handing them a per-layer permitted bbox would silently destroy
# the property they exist for.
BOARD_FIRST_KINDS = ("spectre-fingerprint", "spectre-cells")


def uses_board_frame(tiling, tile_frame="auto"):
    if tile_frame == "board":
        return True
    if tile_frame == "permitted":
        return False
    return tiling in BOARD_FIRST_KINDS


def board_frame_mm(interior):
    """The one frame per run: bbox of the board outline deflated by the inset."""
    bb = interior.BBox()
    return (nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetTop()),
            nm_to_mm(bb.GetRight()), nm_to_mm(bb.GetBottom()))


def tiles_offered(tilings, tex_opts, gbox):
    """How many tiles the generator yielded BEFORE the whole-tile frame filter.

    Run the registered generator directly and count. Note the lattice kinds
    overshoot the window on purpose -- a row and a column beyond each edge, see
    the tilings docstring -- so a nonzero outside-frame count is normal for them
    and means nothing. For the board-first kinds the generator yields exactly the
    patch, so every drop there is a tile hanging over the board outline and is
    worth reporting.
    """
    kind = tilings.KINDS.get(tex_opts.tiling)
    if kind is None:
        return 0
    return sum(1 for _ in kind.fn(tuple(gbox), float(tex_opts.tile_mm),
                                  int(tex_opts.seed)))


def _simplified(poly):
    w = _sps()
    w.Append(poly)
    w.Simplify()
    return w


def resolve_net_code(board, netname):
    """Netname -> net code. 0 for None/'' (floating). Hard error if unknown.

    Not a lookup with a fallback. A mistyped --add-net that quietly resolved to
    0 would emit floating copper while the report said GNDREF, which is the
    silent-empty-set failure this file keeps running into: the run looks like it
    answered the question it was asked.
    """
    if not netname:
        return 0
    by_name = {str(k): v.GetNetCode() for k, v in board.GetNetsByName().items()}
    if netname in by_name:
        return by_name[netname]
    raise RuntimeError(
        "--add-net %r is not a net on this board. Nets carrying zone copper: %s"
        % (netname, ", ".join(sorted(
            {z.GetNetname() for z in board.Zones()
             if not z.GetIsRuleArea() and z.GetNetname()}))))


def _set_island_mode(board, mode):
    """Set island removal on every non-rule-area zone. Returns the old modes."""
    old = []
    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        old.append((z, z.GetIslandRemovalMode()))
        z.SetIslandRemovalMode(mode)
    return old


def run_texture(board_path, ing_opts, tex_opts, sides, out_path, log=print):
    """Place tiles, cut slots, emit keepouts, refill, and measure.

    Returns (board, results, textures, timings). ONE pcbnew.LoadBoard for the
    whole run -- a second load in the same process segfaults this build.
    """
    tilings = _import_tilings()
    add = (tex_opts.mode == "add")
    if not add and tex_opts.neck_style not in NECK_STYLES:
        raise ValueError("--neck-style %r; have %s"
                         % (tex_opts.neck_style, ", ".join(NECK_STYLES)))
    if add and tex_opts.add_fill not in ("solid", "outline"):
        raise ValueError("--add-fill %r; have solid, outline" % tex_opts.add_fill)
    if ing_opts.mode != tex_opts.mode:
        raise ValueError("ingest mode %r and texture mode %r disagree"
                         % (ing_opts.mode, tex_opts.mode))

    timings = {}
    t0 = time.time()
    board = pcbnew.LoadBoard(str(board_path))
    timings["load_s"] = time.time() - t0
    ing = BoardIngest(str(board_path), ing_opts, board=board)
    timings["ingest_refill_s"] = ing.refill_seconds

    targets = []
    for s in sides:
        names = ([n for n in tex_opts.tex_layers if n in SIDE_LAYERS[s]]
                 if tex_opts.tex_layers else [SIDE_LAYERS[s][0]])
        for n in names:
            if (n, s) not in targets:
                targets.append((n, s))
    if not targets:
        raise RuntimeError("no target layer: --tex-layers %r matches nothing in "
                           "%s for side(s) %s"
                           % (tex_opts.tex_layers, SIDE_LAYERS, sides))

    t0 = time.time()
    results = [ing.layer(n, s) for n, s in targets]
    timings["ingest_s"] = time.time() - t0

    # ONE BOARD-ANCHORED FRAME FOR THE WHOLE RUN. Computed from the board
    # outline, not from any layer's copper, and shared by every layer, so the
    # generated field registers between F.Cu and B.Cu and does not move when the
    # copper does. That invariance is the entire fingerprint mechanism: the
    # board-specific part of the result is which tiles survive the mask, and
    # nothing survives being compared if the field itself slid.
    board_first = uses_board_frame(tex_opts.tiling, tex_opts.tile_frame)
    frame = board_frame_mm(ing.frame_interior())

    rbox = texture_bbox(results)
    if rbox is None:
        raise RuntimeError("every permitted region is empty; nothing to texture")

    # ---- before ----------------------------------------------------------
    t0 = time.time()
    textures = []
    net_code = resolve_net_code(board, tex_opts.add_net) if add else 0
    before_fill = {}          # layer -> SHAPE_POLY_SET, kept for the symdiff
    for res in results:
        lid = ing._layer_id(res.layer_name)
        lt = LayerTexture(layer_name=res.layer_name, side=res.side,
                          net=res.pour_net)
        lt.mode = tex_opts.mode
        if add:
            lt.add_fill = tex_opts.add_fill
            lt.add_net = tex_opts.add_net or "(floating)"
        lt.min_thickness_mm = zone_min_thickness_mm(board, lid, res.pour_net)
        f = _simplified(net_fill(board, lid, res.pour_net))
        before_fill[res.layer_name] = f
        lt.fill_before_mm2 = _area_mm2(f)
        m = raster_mask(f, rbox, tex_opts.px_per_mm)
        lt.components_before, lt.areas_before, _ = component_stats(
            m, tex_opts.px_per_mm, 4)
        lt.components_before_8, _ = count_components(m, tex_opts.px_per_mm, 8)
        if not add and tex_opts.neck_mm < lt.min_thickness_mm and \
                tex_opts.neck_style not in ("forest", "none"):
            lt.warnings.append(
                "neck %.3f mm is below this pour's min_thickness %.3f mm. The "
                "filler deletes copper thinner than min_thickness, so every "
                "tie-neck would be removed and every cell isolated. Raise "
                "--neck-mm above %.3f."
                % (tex_opts.neck_mm, lt.min_thickness_mm, lt.min_thickness_mm))
        textures.append(lt)
    timings["before_measure_s"] = time.time() - t0

    # ---- place, cut, emit -------------------------------------------------
    t0 = time.time()
    for res, lt in zip(results, textures):
        lid = ing._layer_id(res.layer_name)
        if res.permitted is None or res.permitted.OutlineCount() == 0:
            lt.warnings.append("permitted region is empty; no tiles placed")
            continue
        if board_first:
            gbox = frame
            lt.tile_frame_source = "board outline, deflated %.2f mm" % (
                ing_opts.edge_inset_mm if ing_opts.frame_inset_mm is None
                else ing_opts.frame_inset_mm)
        else:
            bb = res.permitted.BBox()
            gbox = (nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetTop()),
                    nm_to_mm(bb.GetRight()), nm_to_mm(bb.GetBottom()))
            lt.tile_frame_source = "permitted bbox of %s" % res.layer_name
        lt.tile_frame_mm = tuple(round(v, 4) for v in gbox)
        rings = tilings.generate(tex_opts.tiling, gbox, tex_opts.tile_mm,
                                 tex_opts.seed)
        lt.tiles_offered = tiles_offered(tilings, tex_opts, gbox)
        lt.tiles_generated = len(rings)
        lt.tiles_outside_frame = max(0, lt.tiles_offered - len(rings))
        kept, dropped, worst, where, fareas = place_tiles_by_fragment(
            res.permitted, rings)
        lt.tiles_placed = len(kept)
        lt.tiles_dropped = dropped
        lt.worst_accepted_residual_mm2 = worst
        lt.fragments_total = len(fareas)
        hits = {}
        for k in where:
            hits[k] = hits.get(k, 0) + 1
        lt.fragments_populated = len(hits)
        lt.fragment_hits = [(k, n, round(fareas[k], 3))
                            for k, n in sorted(hits.items(),
                                               key=lambda kv: -kv[1])]
        # The surviving tile set, kept verbatim for the fingerprint render and
        # for the geometry comparison that stands in for a file hash. The
        # emitted .kicad_pcb is NOT byte-reproducible -- two identical runs
        # differ in 63 lines, all KiCad-assigned random UUIDs plus the two group
        # `members` lists that cite them and sort by UUID string, with zero
        # geometry lines differing -- so hashing the file is an invalid
        # reproducibility check and this list is what gets compared instead.
        lt.placed_rings = [[(round(x, 9), round(y, 9)) for x, y in r]
                           for r in kept]
        lt.placed_digest = geometry_digest(lt.placed_rings)
        lt.permitted_mm2 = res.permitted_area_mm2
        lt.tile_area_mm2 = sum(polygon_area_mm2(r[:-1]) for r in lt.placed_rings)
        if not kept:
            lt.warnings.append(
                "every one of the %d generated tiles was dropped: no whole tile "
                "of %.2f mm fits any permitted fragment. Reduce --tile-mm."
                % (len(rings), tex_opts.tile_mm))
            continue

        if add:
            added, emptied = build_add_poly(
                kept, tex_opts.add_fill, tex_opts.slot_mm, ing.max_error,
                tex_opts.cap, tex_opts.cap_seg)
            lt.tiles_emptied_by_gutter = emptied
            if emptied:
                lt.warnings.append(
                    "%d of %d placed tiles deflated to nothing at gutter "
                    "%.3f mm and laid no copper. Reduce --slot-mm or raise "
                    "--tile-mm." % (emptied, len(kept), tex_opts.slot_mm))
            # Clip anyway. Whole-tile placement already guarantees the tile is
            # inside the permitted region, but outline fill strokes the tile
            # WALLS, and a stroke straddles its wall -- half of it lies outside
            # the tile and can cross the permitted boundary even though the tile
            # does not. Measured as a no-op for solid fill, which is the point:
            # it costs nothing and it removes a whole class of edge case.
            added.BooleanIntersection(res.permitted)
            lt.added = added
            lt.add_area_mm2 = _area_mm2(added)
            lt.add_pieces = added.OutlineCount()
            lt.add_pct_of_permitted = (
                100.0 * lt.add_area_mm2 / res.permitted_area_mm2
                if res.permitted_area_mm2 > 0 else 0.0)
            lt.add_pct_of_board = (
                100.0 * lt.add_area_mm2 / res.board_area_mm2
                if res.board_area_mm2 > 0 else 0.0)
            n, holes = emit_copper_shapes(
                board, lid, added, net_code,
                "TEXADD_%s" % res.layer_name.replace(".", "_"),
                group_name="texture_add_%s" % res.layer_name)
            lt.shapes_emitted = n
            lt.cut_stats["added_holes_fractured"] = holes
            continue

        edges, estats = tile_edges(kept)
        lt.edge_stats = estats
        if tex_opts.neck_style == "forest":
            edges = spanning_forest(edges, tex_opts.seed)
            lt.edge_stats["forest_walls"] = len(edges)

        cx = cap_extend_mm(tex_opts.slot_mm, tex_opts.cap)
        cuts = []
        for a, b in edges:
            cuts.extend(neck_cuts(a, b, tex_opts.neck_mm, tex_opts.neck_style,
                                  tex_opts.min_cut_mm, cx))
        joining, cstats = wall_cut_audit(edges, tex_opts.neck_mm,
                                         tex_opts.neck_style,
                                         tex_opts.min_cut_mm, cx)
        lt.cut_stats = cstats
        lt.cut_stats["cut_segments"] = len(cuts)
        # THE NO-OP GUARD. Walls but no cuts means the requested texture was not
        # applied at all, and every downstream check would pass for exactly that
        # reason. See NoCutError for the measurement and the arithmetic.
        if edges and not cuts:
            wl = sum(math.dist(a, b) for a, b in edges) / len(edges)
            span = (wl - tex_opts.neck_mm) / 2.0 - 2.0 * cx
            raise NoCutError(
                "%s: %d walls, 0 cut. Every slot came out %.4f mm long, below "
                "--min-cut-mm %.3f, so all of them were dropped and NO copper "
                "would be removed. The board would be written untextured and "
                "every connectivity check would pass, because nothing would "
                "have happened."
                % (res.layer_name, len(edges), max(span, 0.0),
                   tex_opts.min_cut_mm),
                layer=res.layer_name, walls=len(edges), wall_mm=wl,
                neck_mm=tex_opts.neck_mm, slot_mm=tex_opts.slot_mm,
                cap=tex_opts.cap, min_cut_mm=tex_opts.min_cut_mm,
                span_mm=max(span, 0.0))
        ok, nv, ncomp = wall_graph_is_forest(joining)
        lt.forest_ok = ok
        lt.forest_detail = (len(joining), nv, ncomp)
        lt.slot_length_mm = slot_length_mm(cuts)

        slots = build_slot_poly(cuts, tex_opts.slot_mm, tex_opts.cap,
                               tex_opts.cap_seg)
        if tex_opts.clip_slots_to_permitted:
            slots.BooleanIntersection(res.permitted)
        lt.slot_area_mm2 = _area_mm2(slots)
        hit = _sps()
        hit.Append(slots)
        hit.BooleanIntersection(res.pour)
        lt.slot_area_in_pour_mm2 = _area_mm2(hit)
        lt.slots = slots
        lt.slot_outlines = slots.OutlineCount()

        n, holes = emit_keepouts(board, lid, slots,
                                 "TEX_%s" % res.layer_name.replace(".", "_"),
                                 group_name="texture_%s" % res.layer_name)
        lt.zones_emitted = n
        lt.cut_stats["slot_holes_fractured"] = holes
    timings["place_emit_s"] = time.time() - t0

    # ---- island probe: what the filler is hiding --------------------------
    # Subtract mode only. The probe exists because island removal ALWAYS hides a
    # cell the texture isolated by deleting it. Add mode isolates nothing -- it
    # never touches the fill -- and its added copper is PCB_SHAPEs, which are not
    # fills and which island removal cannot see at any setting. Running it in add
    # mode would print a reassuring number that tested nothing.
    if tex_opts.island_probe and not add:
        t0 = time.time()
        old = _set_island_mode(board, pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        for res, lt in zip(results, textures):
            lid = ing._layer_id(res.layer_name)
            f = _simplified(net_fill(board, lid, res.pour_net))
            lt.island_probe_fill_mm2 = _area_mm2(f)
            m = raster_mask(f, rbox, tex_opts.px_per_mm)
            lt.island_probe_components, lt.island_probe_areas, _ = \
                component_stats(m, tex_opts.px_per_mm, 4)
        for z, mode in old:
            z.SetIslandRemovalMode(mode)
        timings["island_probe_s"] = time.time() - t0

    # ---- the fill that ships ---------------------------------------------
    t0 = time.time()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    timings["textured_fill_s"] = time.time() - t0

    t0 = time.time()
    for res, lt in zip(results, textures):
        lid = ing._layer_id(res.layer_name)
        f = _simplified(net_fill(board, lid, res.pour_net))
        lt.fill_after_mm2 = _area_mm2(f)
        m = raster_mask(f, rbox, tex_opts.px_per_mm)
        lt.components_after, lt.areas_after, _ = component_stats(
            m, tex_opts.px_per_mm, 4)
        lt.components_after_8, _ = count_components(m, tex_opts.px_per_mm, 8)
        if add:
            # REQUIREMENT 2, proved geometrically rather than by area.
            # (A \ B) u (B \ A). Equal areas are necessary but not sufficient --
            # a fill that lost 3 mm2 here and gained 3 mm2 there has the same
            # area and is not the same copper. Zero symmetric difference says
            # the pour is the identical region, polygon for polygon.
            b4 = before_fill.get(res.layer_name)
            if b4 is not None:
                d1 = _sps()
                d1.Append(b4)
                d1.BooleanSubtract(f)
                d2 = _sps()
                d2.Append(f)
                d2.BooleanSubtract(b4)
                d1.Append(d2)
                d1.Simplify()
                lt.fill_symdiff_mm2 = _area_mm2(d1)
    timings["after_measure_s"] = time.time() - t0

    if out_path:
        t0 = time.time()
        pcbnew.SaveBoard(str(out_path), board)
        timings["save_s"] = time.time() - t0

    return board, results, textures, timings, rbox


def connectivity_verdict(textures):
    """PASS/FAIL per layer, and an exact split of every mm2 the texture removed.

    Copper removed decomposes into three parts, and only one of them is a defect:

      slot        the slot area inside the pour. What was asked for.
      dropped     island_probe_fill - fill_after. Copper the filler DELETED for
                  being an island. Only the probe can see it: the probe refills
                  with island removal set to NEVER, while the board's own setting
                  is ALWAYS, so normally the isolated copper is simply gone and
                  the component count of what remains is happily low.

                  CAREFUL, this was measured the hard way: island removal is
                  PER ZONE, not per net. The F.Cu GNDREF pour here is six zones,
                  and copper belonging to zone A that reaches the net only
                  through zone B is an island OF ZONE A and gets deleted even
                  though the net is intact. So `dropped` > 0 means "the filler
                  threw copper away", which is a real defect -- unasked-for
                  copper loss and visible bites in the texture -- but it is NOT
                  by itself proof of electrical isolation. Measured on this
                  board: --neck-style forest drops 21.0 mm2 while leaving the
                  component areas bit-for-bit identical to the untextured board.
                  Electrical isolation is what the component AREAS decide.
      sliver      whatever is left. The filler deletes copper features thinner
                  than the zone's min_thickness, so slot ends and the pinch
                  between two nearby slots shed a little copper. Benign: it
                  removes copper without disconnecting anything, and the
                  component count proves it.

    The component test is not `after == 1`: the untextured F.Cu GNDREF fill on
    this board is already FOUR disjoint pieces (1562.485, 126.463, 6.185, 3.365
    mm2), so demanding one component would fail a board the texture never
    touched. The test is that every component except the one the slots were cut
    into survives with its area unchanged, and no new component appears.
    """
    rows = []
    for lt in textures:
        removed = lt.fill_before_mm2 - lt.fill_after_mm2
        expect = lt.slot_area_in_pour_mm2
        excess = removed - expect
        have_probe = lt.island_probe_components is not None
        dropped = (lt.island_probe_fill_mm2 - lt.fill_after_mm2) if have_probe else None
        sliver = (excess - dropped) if have_probe else None
        tol_dropped = max(0.2, 0.002 * expect)

        # Component-for-component: line the sorted area lists up and require
        # every component but the largest to be unchanged, and the largest to
        # have lost no more than the slots plus a sliver allowance.
        ab, aa = lt.areas_before, lt.areas_after
        comp_count_ok = len(aa) <= len(ab)
        tail_ok = True
        n = min(len(ab), len(aa))
        for i in range(1, n):
            if abs(ab[i] - aa[i]) > max(0.05, 0.01 * ab[i]):
                tail_ok = False
                break
        largest_ok = True
        if ab and aa:
            lost = ab[0] - aa[0]
            # Generous, deliberately. A rasterised area carries a quantisation
            # bias of a few tenths of a percent of the region -- measured on this
            # board, 1694.997 mm2 of raster against 1691.505 mm2 of polygon, so
            # +3.5 mm2 on the before side alone -- and the bias does not cancel
            # between before and after because the boundary length changes. The
            # EXACT area accounting is the fill decomposition above (slots /
            # dropped / slivers, all from polygon areas); this bound only has to
            # catch a component losing far more than the slots, as --neck-style
            # none does at 416.7 mm2 against 75.0 asked for.
            largest_ok = (lost <= expect + max(4.0, 0.25 * expect) + 1e-9)
        comp_ok = bool(comp_count_ok and tail_ok and largest_ok)

        probe_comp_ok = (not have_probe or
                         lt.island_probe_components <= lt.components_before)
        dropped_ok = (dropped is None) or (dropped <= tol_dropped)
        # Fallback when the probe was skipped: the undecomposed excess is all
        # there is to go on, so it carries a looser tolerance and the verdict is
        # correspondingly weaker.
        area_ok = True if have_probe else (abs(excess) <= max(1.0, 0.05 * expect))
        rows.append({
            "layer": lt.layer_name, "removed_mm2": removed,
            "expected_mm2": expect, "excess_mm2": excess,
            "dropped_mm2": dropped, "sliver_mm2": sliver,
            "tol_dropped_mm2": tol_dropped, "have_probe": have_probe,
            "comp_ok": comp_ok, "comp_count_ok": comp_count_ok,
            "tail_ok": tail_ok, "largest_ok": largest_ok,
            "probe_comp_ok": probe_comp_ok,
            "dropped_ok": dropped_ok, "area_ok": area_ok,
            # Electrical connectivity is comp_ok. `dropped` is a separate defect
            # (copper thrown away, possibly only per-zone) and is reported as its
            # own failure so the two are never conflated.
            "pass": bool(comp_ok and probe_comp_ok and dropped_ok and area_ok),
            "connectivity_pass": comp_ok,
        })
    return rows


def run_drc(board_path, out_json, kicad_cli=None):
    """kicad-cli DRC on a saved board. The project file must sit alongside it.

    Measured: with the .kicad_pro present this board reports 206 warnings and 0
    errors; with the board file alone it reports 235 violations including 8
    phantom errors, because kicad-cli then falls back to default design rules
    instead of the project's. Comparing a textured board against a baseline taken
    the other way would invent violations the texture did not cause.

    THE .kicad_pro IS NOT ENOUGH, measured this session. Copy the board and the
    project file to a scratch directory and this board reports 221 warnings, not
    206: the extra 15 are lib_footprint_issues / lib_footprint_mismatch raised
    because fp-lib-table and the ${KIPRJMOD} .pretty libraries are not there, so
    the footprints cannot be compared with their library originals. Same board,
    same rules, +15 warnings from a missing library table.

    AND COPYING THE LIBRARIES IS NOT ENOUGH EITHER, which is the correction to
    the advice this docstring used to give. Measured on the same board, same
    kicad-cli 10.0.0, three library contexts:

      scratch dir, .kicad_pro only ........................ 221 warnings
      scratch dir + fp-lib-table + the three .pretty dirs .. 213 warnings
      the project directory itself ......................... 206 warnings

    The last 7 do not come back from copying files, because ${KIPRJMOD} then
    resolves to the scratch directory and the nickname paths inside fp-lib-table
    still miss. So 206 is reproducible ONLY by running in the project directory.
    That matters for an absolute comparison and not at all for a relative one:
    the texture's claim is that it adds nothing, and that is a DELTA. Run the
    baseline and the textured board in the SAME context, whichever it is, and
    the delta is exact -- measured 213 -> 213 in scratch and 206 -> 206 in the
    project directory, identical by type and severity both times, 0 errors and
    0 unconnected throughout.
    """
    exe = kicad_cli or os.environ.get("KICAD_CLI") or "kicad-cli"
    cmd = [exe, "pcb", "drc", "--format", "json", "--refill-zones",
           "--severity-all", "--output", str(out_json), str(board_path)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    return {"seconds": time.time() - t0, "rc": p.returncode,
            "stdout": p.stdout.strip(), "stderr": p.stderr.strip(),
            "cmd": " ".join(cmd)}


def drc_summary(path):
    import collections
    d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    v = d.get("violations") or []
    return {
        "total": len(v),
        "by_severity": dict(collections.Counter(x.get("severity") for x in v)),
        "by_type": dict(collections.Counter(
            (x.get("severity"), x.get("type")) for x in v)),
        "unconnected": len(d.get("unconnected_items") or []),
        "parity": len(d.get("schematic_parity") or []),
    }


def drc_delta(base_path, new_path):
    a, b = drc_summary(base_path), drc_summary(new_path)
    keys = set(a["by_type"]) | set(b["by_type"])
    rows = []
    for k in sorted(keys, key=lambda t: (t[0], t[1])):
        na, nb = a["by_type"].get(k, 0), b["by_type"].get(k, 0)
        if na != nb:
            rows.append((k[0], k[1], na, nb, nb - na))
    return a, b, rows


# --- CLI ----------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="texture_board.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Cut a decorative slot texture into an existing copper pour. "
                    "PART 1 (board ingest) is implemented; --report is live.")
    p.add_argument("--board", required=True, help="input .kicad_pcb")
    p.add_argument("--side", choices=["front", "back", "both"], default="both")
    p.add_argument("--layers", default=None,
                   help="comma-separated layer names, overriding the side default "
                        f"({SIDE_LAYERS})")

    p.add_argument("--texture-mode", choices=["subtract", "add"],
                   default="subtract",
                   help="subtract: cut slots INTO the pour (the original "
                        "behaviour, unchanged). add: lay new copper where there "
                        "is NONE, as bare F.Cu under closed mask -- tone T6, the "
                        "dark under-mask sheen, not gold. In add mode the "
                        "permitted region inverts: it is the board minus every "
                        "copper feature of every net, minus mask openings, with "
                        "all the usual component and corridor guards still on.")
    p.add_argument("--add-fill", choices=["solid", "outline"], default="solid",
                   help="add mode only. solid: each tile is one filled copper "
                        "island, shrunk by --slot-mm/2 so neighbours stay "
                        "separate. outline: only the tile walls, stroked at "
                        "--slot-mm.")
    p.add_argument("--add-net", default=None,
                   help="add mode only. Net for the added copper. Omit to leave "
                        "it floating (no net tag). See the ELECTRICAL note in "
                        "the module docstring before choosing.")

    # CHOICES COME FROM THE REGISTRY, not from a list retyped here. They were
    # retyped here, and it cost a mode: "spectre-cells" was registered in
    # tilings.py, named in BOARD_FIRST_KINDS and covered by uses_board_frame(),
    # and argparse still rejected it, so the whole cell-grid path was
    # unreachable from the command line while every unit test passed. A hand-
    # maintained mirror of an extension point is a defect waiting for the next
    # extension; tilings.kinds() is sorted, so --help stays stable.
    p.add_argument("--tiling",
                   choices=_import_tilings().kinds(),
                   default=None,
                   help="giving this, or --out, switches from ingest-only to "
                        "texture emission. Two kinds are BOARD-FIRST -- their "
                        "field is anchored to the board outline, not fitted to "
                        "the layer's permitted region. spectre-fingerprint is "
                        "ONE spectre patch centred on the board, at the "
                        "shallowest substitution level whose BOUNDARY POLYGON "
                        "covers the frame -- covers, not spans. A level-5 "
                        "patch is 34649 tiles, of which about 1550 to 1580 "
                        "land wholly inside a 150 x 100 mm board at "
                        "--tile-mm 3; but at --tile-mm 3 and --seed 0 NO level "
                        "covers that board and the run refuses -- raise "
                        "--tile-mm to 3.087 or change --seed, both of which "
                        "the refusal spells out. It fails loudly rather than "
                        "repeating, rescaling, or returning a level whose "
                        "coverage it never checked. It is the one to use. "
                        "spectre-cells puts a level-2 patch in each cell of a "
                        "12.88302*tile_mm grid; it predates the substitution "
                        "being fixed and buys resolution by giving up "
                        "aperiodicity between cells, which is no longer a "
                        "trade anyone has to make")
    p.add_argument("--tile-frame", choices=["auto", "board", "permitted"],
                   default="auto",
                   help="rectangle the tiling is generated over. permitted: "
                        "this layer's permitted bbox (the original behaviour; "
                        "the field moves when the copper moves). board: the "
                        "board outline deflated by --edge-inset, one frame for "
                        "every layer. auto (default): board for the board-first "
                        "kinds, permitted for the lattice kinds, so every "
                        "documented lattice run is unchanged")
    p.add_argument("--tile-mm", type=float, default=2.0,
                   help="EQUAL-AREA tile size: every tiling produces tiles of "
                        "area tile_mm^2, which is the only definition under "
                        "which slot cost is comparable across tilings")
    p.add_argument("--slot-mm", type=float, default=0.25,
                   help="slot width. Measured: the filler removes exactly this, "
                        "with no clearance inflation")
    p.add_argument("--out", default=None, help="output .kicad_pcb")

    g3 = p.add_argument_group("texture")
    g3.add_argument("--neck-mm", type=float, default=0.5,
                    help="length of UNCUT copper left in each wall. Must exceed "
                         "the pour's min_thickness (0.25 mm on this board) or "
                         "the filler deletes the neck and isolates the cell")
    g3.add_argument("--neck-style", choices=list(NECK_STYLES), default="midedge",
                    help="midedge: break every wall at its midpoint (default; "
                         "cheapest style that still necks every wall). vertex: "
                         "break at both ends. both: ends and middle. forest: no "
                         "necks, keep a spanning forest of walls instead -- ONE "
                         "keepout zone per layer, but a third of the walls are "
                         "absent so it reads as a maze. none: no necks at all, "
                         "which isolates every cell and exists to be measured.")
    g3.add_argument("--cap", choices=["round", "square"], default="round")
    g3.add_argument("--cap-seg", type=int, default=4)
    g3.add_argument("--min-cut-mm", type=float, default=0.15,
                    help="drop a slot shorter than this. Dropping a slot only "
                         "adds copper, so it can never break connectivity")
    g3.add_argument("--seed", type=int, default=0)
    g3.add_argument("--tex-layers", default=None,
                    help="comma-separated layers to actually cut. Default is the "
                         "OUTER layer of each side only: cutting the buried "
                         "plane is invisible and costs plane impedance")
    g3.add_argument("--no-clip-slots", action="store_true",
                    help="do not clip slot bodies to the permitted region. A "
                         "slot straddles its wall, so a tile touching the "
                         "boundary otherwise cuts into the guard band")
    g3.add_argument("--no-island-probe", action="store_true",
                    help="skip the island-removal-NEVER refill. That probe is "
                         "the only direct look at the topology: with removal "
                         "ALWAYS the filler deletes isolated cells instead of "
                         "leaving islands, so the component count alone cannot "
                         "fail")
    g3.add_argument("--raster-px-per-mm", type=float, default=40.0,
                    help="flood-fill resolution. 40 px/mm = 25 um/px, so a "
                         "0.25 mm slot is 10 px and a 0.5 mm neck is 20 px")

    g4 = p.add_argument_group("outputs")
    g4.add_argument("--render-png", default=None,
                    help="prefix for the copper renders of the textured board")
    g4.add_argument("--render-px-per-mm", type=float, default=24.0)
    g4.add_argument("--appearance-gain", type=float, default=1.0,
                    help="if not 1.0, ALSO write board-appearance images with "
                         "the T6/T7 under-mask contrast scaled by this factor. "
                         "On a black-mask board T6-T5 is 19 counts of red, which "
                         "is the truth and is nearly invisible in a thumbnail. "
                         "The gained image is stamped as gained so it cannot be "
                         "mistaken for the board.")
    g4.add_argument("--zoom-mm", type=float, default=14.0,
                    help="side of the close-up crop, centred on the densest "
                         "textured spot")
    g4.add_argument("--zoom-px-per-mm", type=float, default=140.0)
    g4.add_argument("--fingerprint-png", default=None,
                    help="prefix for the FINGERPRINT images -- the surviving "
                         "tiles alone, one per side, stamped with tiling, "
                         "tile_mm, level, tile count, edge inset, seed, the "
                         "geometry digest and the board commit. Not the "
                         "textured-board render and not the permitted mask.")
    g4.add_argument("--fingerprint-px-per-mm", type=float, default=12.0)
    g4.add_argument("--drc", action="store_true",
                    help="run kicad-cli DRC on the output. The .kicad_pro MUST "
                         "sit beside the output or DRC silently uses default "
                         "rules: 206 warnings/0 errors with it, 235 "
                         "violations/8 phantom errors without")
    g4.add_argument("--drc-baseline", default=None,
                    help="baseline DRC json to diff against")
    g4.add_argument("--drc-json", default=None)
    g4.add_argument("--kicad-cli", default=None)
    g4.add_argument("--texture-json", default=None)

    p.add_argument("--report", action="store_true",
                   help="also print the per-guard removal breakdown, the tile-fit "
                        "probe and the per-layer item counts. Without it only the "
                        "summary table is printed.")
    p.add_argument("--mask-png", default=None, help="write the permitted-mask figure here")
    p.add_argument("--mask-json", default=None, help="write the permitted polygons here")
    p.add_argument("--px-per-mm", type=float, default=6.0)
    p.add_argument("--tile-probe", default="2,4,6,8,12",
                   help="comma-separated tile sizes in mm. For each, report the "
                        "area in which a tile centre could legally sit "
                        "(permitted deflated by size/2). Empty string disables.")

    g = p.add_argument_group("clearances (mm)")
    g.add_argument("--clr-courtyard", type=float, default=0.5)
    g.add_argument("--clr-pad", type=float, default=0.5)
    g.add_argument("--clr-track", type=float, default=0.4)
    g.add_argument("--clr-via", type=float, default=0.4)
    g.add_argument("--clr-hole", type=float, default=0.4)
    g.add_argument("--clr-zone", type=float, default=0.5,
                   help="clearance around zones of any OTHER net")
    g.add_argument("--clr-hs", type=float, default=1.0,
                   help="clearance around the HS1 true envelope")
    g.add_argument("--clr-extra", type=float, default=0.0,
                   help="clearance around --exclude rectangles")
    g.add_argument("--clr-copper", type=float, default=0.55,
                   help="ADD MODE. Clearance around EVERY existing copper "
                        "feature of every net. Default 0.55, not 0.5: each pour "
                        "on this board sets local_clearance 0.5 mm, so new "
                        "copper at exactly 0.5 mm makes the filler void the pour "
                        "and add mode stops being lossless.")
    g.add_argument("--clr-mask", type=float, default=0.25,
                   help="ADD MODE. Clearance around solder-mask openings. "
                        "Copper under an opening plates as gold (T2) instead of "
                        "reading as T6 under-mask sheen.")
    g.add_argument("--edge-inset", type=float, default=0.5,
                   help="copper-to-board-edge clearance. Default 0.5, which is "
                        "this board's own min_copper_edge_clearance rule. It "
                        "was 1.0 -- twice the rule, with no reason recorded "
                        "anywhere. It does NOT stand in for V-scoring, a panel "
                        "rail or the router bit radius: those constrain "
                        "Edge.Cuts, and nothing here emits Edge.Cuts.")
    g.add_argument("--frame-inset", type=float, default=None,
                   help="inset used for the BOARD-FIRST TILING FRAME only. "
                        "Defaults to --edge-inset, which is what it used to be "
                        "welded to; give it separately to keep the pattern "
                        "still while the copper clearance moves. Anchoring art "
                        "to a DRC clearance means a clearance change silently "
                        "rewrites the art.")
    g.add_argument("--corridor-half-width", type=float, default=12.0,
                   help="half-width of the VRM->ASIC return corridor band. "
                        "Below ~8 mm the band is entirely inside the VCORE pour "
                        "and removes nothing from GNDREF; see the sweep in the "
                        "module docstring. Default 12.0.")

    g2 = p.add_argument_group("region selection")
    g2.add_argument("--pour-net", default=None,
                    help="net whose pour is textured; default is the largest "
                         "pour on each layer")
    g2.add_argument("--exclude", action="append", default=[], metavar="X0,Y0,X1,Y1",
                    help="extra exclusion rectangle in mm; repeatable")
    g2.add_argument("--min-region-mm2", type=float, default=1.0,
                    help="drop permitted fragments smaller than this")
    g2.add_argument("--hs1-sides", choices=["front", "both", "none"], default="front",
                    help="where to apply the measured HS1 envelope. 'front' is the "
                         "physical object. 'both' also protects the back copper "
                         "under the ASIC on thermal grounds. 'none' trusts HS1's "
                         "footprint courtyard, which is wrong -- see defect #55.")
    g2.add_argument("--corridor-front-only", action="store_true",
                    help="apply the return corridor to the front side only")
    g2.add_argument("--no-refill", action="store_true",
                    help="do NOT refill the zones in process; measure the fills "
                         "stored in the file. They may be stale and nothing in "
                         "the file can tell you so.")
    return p


def opts_from_args(a) -> IngestOptions:
    return IngestOptions(
        mode=a.texture_mode,
        clr_copper_mm=a.clr_copper,
        clr_mask_mm=a.clr_mask,
        clr_courtyard_mm=a.clr_courtyard,
        clr_pad_mm=a.clr_pad,
        clr_track_mm=a.clr_track,
        clr_via_mm=a.clr_via,
        clr_hole_mm=a.clr_hole,
        clr_zone_mm=a.clr_zone,
        clr_hs_mm=a.clr_hs,
        clr_extra_mm=a.clr_extra,
        edge_inset_mm=a.edge_inset,
        frame_inset_mm=a.frame_inset,
        corridor_half_width_mm=a.corridor_half_width,
        corridor_all_layers=not a.corridor_front_only,
        min_region_mm2=a.min_region_mm2,
        pour_net=a.pour_net,
        excludes=[parse_rect(s) for s in a.exclude],
        hs1_sides=a.hs1_sides,
        refill=not a.no_refill,
    )


def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)

    if a.layers and a.side == "both":
        # Courtyards are a SIDE-level obstacle, so the same layer analysed as
        # "front" and as "back" gets different obstacles and a different answer.
        # With --side both the override would emit each named layer twice with
        # two different numbers and no way to tell which is meant.
        parser.error("--layers needs --side front or --side back; with "
                     "--side both each named layer would be analysed twice, "
                     "once against each side's courtyards.")

    opts = opts_from_args(a)

    if a.tiling or a.out:
        return main_texture(a, parser, opts)

    ing = BoardIngest(a.board, opts)

    sides = ["front", "back"] if a.side == "both" else [a.side]
    layer_override = [s.strip() for s in a.layers.split(",")] if a.layers else None

    results = []
    for s in sides:
        results.extend(ing.side(s, layer_override))

    print(f"board: {a.board}")
    print(f"kicad: {pcbnew.GetBuildVersion()}   maxError: {ing.max_error} nm")
    print(f"corridor L1{CORRIDOR_L1} -> U9{CORRIDOR_U9} "
          f"= {corridor_length_mm():.1f} mm, half-width "
          f"{opts.corridor_half_width_mm} mm")
    print(f"HS1 envelope applied to: {opts.hs1_sides}  {HS1_TRUE_ENVELOPE}")
    if ing.refill_delta_mm2:
        deltas = "  ".join(f"{k} {v:+.3f}" for k, v in ing.refill_delta_mm2.items())
        print(f"in-process refill: {ing.refill_seconds:.1f} s, filled-area delta "
              f"mm2 -> {deltas}")
        worst = max(abs(v) for v in ing.refill_delta_mm2.values())
        print(f"  worst |delta| {worst:.3f} mm2 -- "
              + ("the file's stored fills were current"
                 if worst < 1.0 else
                 "THE FILE'S STORED FILLS WERE STALE; any earlier report on it "
                 "was wrong"))
    for n in dict.fromkeys(ing.notes):
        print("note: " + n)
    print()
    add = (opts.mode == "add")
    if add:
        print("MODE: add -- the permitted region is the board MINUS all copper, "
              "not the pour.")
        hdr = (f"{'layer':<8} {'side':<6} {'pour net':<22} {'board mm2':>10} "
               f"{'bare mm2':>10} {'permit mm2':>11} {'% board':>8} "
               f"{'% bare':>7} {'frags':>6}")
        print(hdr)
        print("-" * len(hdr))
        for r in results:
            print(f"{r.layer_name:<8} {r.side:<6} {(r.pour_net or '-'):<22} "
                  f"{r.board_area_mm2:>10.1f} {r.bare_area_mm2:>10.1f} "
                  f"{r.permitted_area_mm2:>11.1f} "
                  f"{r.permitted_pct_of_board:>7.1f}% "
                  f"{r.permitted_pct_of_bare:>6.1f}% {r.fragment_count:>6}")
    else:
        hdr = (f"{'layer':<8} {'side':<6} {'pour net':<22} {'pour mm2':>9} "
               f"{'permit mm2':>11} {'% pour':>7} {'frags':>6} {'largest':>8}")
        print(hdr)
        print("-" * len(hdr))
        for r in results:
            print(f"{r.layer_name:<8} {r.side:<6} {(r.pour_net or '-'):<22} "
                  f"{r.pour_area_mm2:>9.1f} {r.permitted_area_mm2:>11.1f} "
                  f"{r.permitted_pct_of_pour:>6.1f}% {r.fragment_count:>6} "
                  f"{r.largest_fragment_mm2:>8.1f}")

    if a.report:
        classes = (["all_zone_fills", "pads_tracks_vias", "mask_apertures",
                    "courtyards", "hs1_envelope", "return_corridor",
                    "extra_rects", "edge_inset"] if add else
                   ["other_net_zones", "pads_tracks_vias", "courtyards",
                    "hs1_envelope", "return_corridor", "extra_rects",
                    "edge_inset"])
        print("\nmm2 that each guard removes from this mode's base "
              "(classes overlap, so they do not sum):")
        h2 = f"{'layer':<8}" + "".join(f"{c[:16]:>18}" for c in classes)
        print(h2)
        print("-" * len(h2))
        for r in results:
            row = f"{r.layer_name:<8}"
            for c in classes:
                v = r.removal_mm2.get(c)
                row += f"{'-':>18}" if v is None else f"{v:>18.1f}"
            print(row)

    probes = [float(s) for s in a.tile_probe.split(",") if s.strip()] \
        if (a.tile_probe and a.report) else []
    if probes:
        for r in results:
            for t in probes:
                r.tile_probe[t] = tile_probe(r, t)
        print("\nmm2 in which a tile CENTRE could sit, by tile size "
              "(permitted deflated by size/2); (n) = surviving fragments:")
        h3 = f"{'layer':<8}" + "".join(f"{str(t) + ' mm':>18}" for t in probes)
        print(h3)
        print("-" * len(h3))
        for r in results:
            row = f"{r.layer_name:<8}"
            for t in probes:
                area, frags = r.tile_probe[t]
                row += f"{f'{area:.1f} ({frags})':>18}"
            print(row)

    if a.report:
        print()
        for r in results:
            print(f"{r.layer_name}: {r.counts}")
            print(f"{'':<8}dropped {r.dropped_fragments} frags / "
                  f"{r.dropped_area_mm2:.2f} mm2 below {opts.min_region_mm2} mm2")
    warned = False
    for r in results:
        for w in r.warnings:
            warned = True
            print(f"WARNING [{r.layer_name}]: {w}", file=sys.stderr)
    if warned:
        print("(warnings above went to stderr)")

    if a.mask_png:
        bb = ing.board.GetBoardEdgesBoundingBox()
        bbox = (nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetTop()),
                nm_to_mm(bb.GetRight()), nm_to_mm(bb.GetBottom()))
        raw_outline = _sps()
        ing.board.GetBoardPolygonOutlines(raw_outline, True)
        render_mask_png(
            results, bbox, a.mask_png, a.px_per_mm,
            title=pathlib.Path(a.board).name,
            board_outline=raw_outline,
            interior=ing._board_interior(),
            other_pours={r.layer_name: r.other_pours for r in results},
            hs1_rect=HS1_TRUE_ENVELOPE,
            corridor=(CORRIDOR_L1, CORRIDOR_U9))
        print(f"\nwrote {a.mask_png}")

    if a.mask_json:
        doc = {
            "board": a.board,
            "kicad": pcbnew.GetBuildVersion(),
            "options": {k: v for k, v in vars(opts).items()},
            "hs1_true_envelope": HS1_TRUE_ENVELOPE,
            "corridor": {"p0": CORRIDOR_L1, "p1": CORRIDOR_U9,
                         "half_width_mm": opts.corridor_half_width_mm},
            "layers": [{
                "layer": r.layer_name, "side": r.side, "mode": r.mode,
                "pour_net": r.pour_net,
                "pour_area_mm2": r.pour_area_mm2,
                "board_area_mm2": r.board_area_mm2,
                "bare_area_mm2": r.bare_area_mm2,
                "permitted_area_mm2": r.permitted_area_mm2,
                "permitted_pct_of_pour": r.permitted_pct_of_pour,
                "permitted_pct_of_board": r.permitted_pct_of_board,
                "permitted_pct_of_bare": r.permitted_pct_of_bare,
                "fragment_count": r.fragment_count,
                "largest_fragment_mm2": r.largest_fragment_mm2,
                "tile_probe": {str(k): v for k, v in r.tile_probe.items()},
                "counts": r.counts,
                "removal_mm2": r.removal_mm2,
                "warnings": r.warnings,
                "permitted": _outlines_with_holes(r.permitted),
            } for r in results],
        }
        pathlib.Path(a.mask_json).write_text(json.dumps(doc), encoding="utf-8")
        print(f"wrote {a.mask_json}")

    return 0


def tex_opts_from_args(a) -> TextureOptions:
    return TextureOptions(
        mode=a.texture_mode,
        add_fill=a.add_fill,
        add_net=a.add_net,
        tiling=a.tiling or "hex",
        tile_mm=a.tile_mm,
        slot_mm=a.slot_mm,
        neck_mm=a.neck_mm,
        neck_style=a.neck_style,
        cap=a.cap,
        cap_seg=a.cap_seg,
        min_cut_mm=a.min_cut_mm,
        seed=a.seed,
        tex_layers=[s.strip() for s in a.tex_layers.split(",")] if a.tex_layers else [],
        clip_slots_to_permitted=not a.no_clip_slots,
        island_probe=not a.no_island_probe,
        px_per_mm=a.raster_px_per_mm,
        tile_frame=a.tile_frame,
    )


def main_texture(a, parser, ing_opts):
    if not a.out:
        parser.error("--tiling needs --out OUT.kicad_pcb")
    tex = tex_opts_from_args(a)
    sides = ["front", "back"] if a.side == "both" else [a.side]

    try:
        board, results, textures, timings, rbox = run_texture(
            a.board, ing_opts, tex, sides, a.out)
    except _import_tilings().SpectreCoverageError as exc:
        # THE LOUD FAILURE. Nothing is written, nothing is downscaled and no
        # patch is repeated: the run stops with the numbers needed to fix it.
        print("\nSPECTRE FINGERPRINT REFUSED -- no board was written.",
              file=sys.stderr)
        print(str(exc), file=sys.stderr)
        # LABEL THE THRESHOLD BY WHICH REFUSAL THIS IS. There are two, they are
        # far apart -- 0.561 mm to span this board from level 5, 3.086 mm to
        # cover it -- and calling a coverage threshold a span threshold sends
        # the caller to a tile size that still refuses.
        if exc.min_tile_mm:
            print("\n  smallest --tile-mm that %s this board: %.3f"
                  % ("COVERS" if getattr(exc, "reason", "span") == "cover"
                     else "spans", exc.min_tile_mm), file=sys.stderr)
        print("  requested --tile-mm: %.3f   patch %.2f x %.2f mm   frame "
              "%.2f x %.2f mm"
              % (exc.tile_mm, exc.patch_mm[0], exc.patch_mm[1],
                 exc.frame_mm[0], exc.frame_mm[1]), file=sys.stderr)
        if getattr(exc, "reason", "span") == "cover":
            print("  the patch SPANS this frame and its boundary polygon does "
                  "not contain it; how deep a patch would be needed to cover "
                  "an arbitrary frame is NOT established, so no level is "
                  "quoted here. Coverage is rotation-dependent -- try another "
                  "--seed -- or pin the level and own the uncovered rim.",
                  file=sys.stderr)
        else:
            print("  level a correct substitution would need at that tile: %s"
                  % exc.needed_level, file=sys.stderr)
        return 5
    except NoCutError as exc:
        # Same contract as the refusal above: nothing written, and the numbers
        # needed to act rather than a bare "0 zones emitted" buried in a table.
        print("\nNO SLOT WAS CUT -- no board was written.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("\n  wall length (mean)   %.4f mm" % exc.wall_mm, file=sys.stderr)
        print("  --neck-mm            %.3f mm  (copper that survives)"
              % exc.neck_mm, file=sys.stderr)
        print("  --cap %-6s         overhangs %.3f mm at each cut end"
              % (exc.cap, cap_extend_mm(exc.slot_mm, exc.cap)), file=sys.stderr)
        print("  resulting slot       %.4f mm, vs --min-cut-mm %.3f"
              % (exc.span_mm, exc.min_cut_mm), file=sys.stderr)
        need = exc.wall_mm - 2.0 * exc.min_cut_mm - 4.0 * cap_extend_mm(
            exc.slot_mm, exc.cap)
        print("\n  Your options: lower --neck-mm below %.3f mm, or use "
              "--cap square, or raise --tile-mm so the walls are longer, or "
              "lower --min-cut-mm. Note the pour's min_thickness still has to "
              "fit inside whatever neck you choose."
              % max(need, 0.0), file=sys.stderr)
        return 6

    if tex.mode == "add":
        allpass, verdicts = print_add_report(a, tex, results, textures,
                                             timings, rbox)
    else:
        allpass, verdicts = print_subtract_report(a, tex, results, textures,
                                                  timings, rbox)

    for lt in textures:
        for w in lt.warnings:
            print("WARNING [%s]: %s" % (lt.layer_name, w), file=sys.stderr)
    for r in results:
        for w in r.warnings:
            print("WARNING [%s ingest]: %s" % (r.layer_name, w), file=sys.stderr)

    print("\nwrote %s" % a.out)
    return finish_texture_run(a, tex, board, textures, verdicts, timings, rbox,
                              allpass)


def _area_delta_px(before, after, px_per_mm):
    """Worst per-component area change, in PIXELS. None if the lists differ."""
    if len(before) != len(after):
        return None
    if not before:
        return 0.0
    px = 1.0 / (px_per_mm * px_per_mm)
    return max(abs(x - y) for x, y in zip(before, after)) / px


def print_tile_ledger(tex, results, textures):
    """Every tile the generator made, and where it went.  Both modes.

    Four numbers, because three of them used to be one: `offered` is what the
    tiling yielded, `outside` is what tilings.generate() dropped for overhanging
    the frame, `masked` is what the permitted polygons rejected, `placed` is what
    survived. The old report counted tiles only after the frame filter, so under
    a board-anchored frame every tile hanging over the board edge disappeared
    without being counted anywhere.

    `frags` is the permitted-region coverage: how many separate permitted
    fragments received at least one tile, out of how many exist.
    """
    print("\nTILE LEDGER  -- tiling %s, tile %.3f mm, seed %d, frame %s"
          % (tex.tiling, tex.tile_mm, tex.seed,
             "BOARD (one frame for every layer)"
             if uses_board_frame(tex.tiling, tex.tile_frame)
             else "per-layer permitted bbox"))
    h = ("%-8s %-34s %8s %8s %8s %8s %8s" %
         ("layer", "frame x0,y0,x1,y1 mm", "offered", "outside", "masked",
          "placed", "frags"))
    print(h)
    print("-" * len(h))
    for lt in textures:
        f = lt.tile_frame_mm or (0, 0, 0, 0)
        print("%-8s %-34s %8d %8d %8d %8d %8s"
              % (lt.layer_name,
                 "%.2f,%.2f,%.2f,%.2f" % tuple(f),
                 lt.tiles_offered, lt.tiles_outside_frame, lt.tiles_dropped,
                 lt.tiles_placed,
                 "%d/%d" % (lt.fragments_populated, lt.fragments_total)))
    for lt in textures:
        if lt.tile_frame_mm:
            f = lt.tile_frame_mm
            print("  %s frame %.2f x %.2f mm, from the %s"
                  % (lt.layer_name, f[2] - f[0], f[3] - f[1],
                     lt.tile_frame_source))
        if lt.fragment_hits:
            print("     permitted fragments populated: "
                  + ", ".join("#%d %d tile(s) in %.1f mm2" % (k, n, ar)
                              for k, n, ar in lt.fragment_hits[:6])
                  + (" ... +%d more" % (len(lt.fragment_hits) - 6)
                     if len(lt.fragment_hits) > 6 else ""))
        elif lt.fragments_total:
            print("     permitted fragments populated: NONE of %d"
                  % lt.fragments_total)


def print_add_report(a, tex, results, textures, timings, rbox):
    """ADD MODE report. Returns (allpass, verdicts).

    The three questions this mode has to answer, in the order they decide
    whether it ships:

      1. did the ground plane move?   fill symmetric difference, must be 0.
      2. is there enough room?        permitted area, as a fraction of the bare
                                      board and of the whole board.
      3. what did we actually lay?    added copper area and island count.
    """
    print("board:  %s" % a.board)
    print("kicad:  %s" % pcbnew.GetBuildVersion())
    print("texture: ADD  %s  tile %.2f mm (equal-area)  fill %s  gutter/stroke "
          "%.2f mm  net %s  seed %d"
          % (tex.tiling, tex.tile_mm, tex.add_fill, tex.slot_mm,
             tex.add_net or "(floating)", tex.seed))
    print("layers: %s" % ", ".join("%s (%s)" % (t.layer_name, t.side)
                                   for t in textures))
    print()

    print("WHERE ADD MODE IS ALLOWED  -- the inverted region")
    h = ("%-8s %10s %10s %11s %7s %7s %9s" %
         ("layer", "board", "bare", "permitted", "of brd", "of bare", "frags"))
    print(h)
    print("%-8s %10s %10s %11s %7s %7s %9s"
          % ("", "mm2", "mm2", "mm2", "%", "%", ""))
    print("-" * len(h))
    for r in results:
        print("%-8s %10.1f %10.1f %11.1f %6.1f%% %6.1f%% %9d"
              % (r.layer_name, r.board_area_mm2, r.bare_area_mm2,
                 r.permitted_area_mm2, r.permitted_pct_of_board,
                 r.permitted_pct_of_bare, r.fragment_count))
    print("  bare = board inside Edge.Cuts minus ALL copper at zero clearance. "
          "permitted = bare, further cut by every clearance, every courtyard, "
          "the HS1 envelope, the return corridor and the edge inset.")
    for r in results:
        if r.removal_mm2:
            print("  %s removals mm2: %s" % (r.layer_name, "  ".join(
                "%s %.1f" % (k, v) for k, v in sorted(r.removal_mm2.items()))))

    print_tile_ledger(tex, results, textures)

    print("\nWHAT WAS LAID DOWN")
    h2 = ("%-8s %8s %8s %8s %10s %8s %8s %8s" %
          ("layer", "tiles", "dropped", "emptied", "copper", "of perm",
           "of brd", "islands"))
    print(h2)
    print("%-8s %8s %8s %8s %10s %8s %8s %8s"
          % ("", "", "", "", "mm2", "%", "%", ""))
    print("-" * len(h2))
    for lt in textures:
        print("%-8s %8d %8d %8d %10.1f %7.1f%% %7.2f%% %8d"
              % (lt.layer_name, lt.tiles_placed, lt.tiles_dropped,
                 lt.tiles_emptied_by_gutter, lt.add_area_mm2,
                 lt.add_pct_of_permitted, lt.add_pct_of_board, lt.add_pieces))
    print("  islands = separate copper polygons emitted, one PCB_SHAPE each. "
          "Net: %s." % (tex.add_net or "none -- the copper is floating"))
    # THE TOLERANCE ON THE WHOLE-TILE RULE, MADE VISIBLE. place_tiles() accepts
    # a tile whose area outside the permitted region is <= tol_mm2 (1e-6), and
    # its docstring justifies that by saying the worst accepted residual is
    # "reported so that a tolerance quietly admitting partly-outside tiles would
    # be visible as a residual near the tolerance rather than at zero". It was
    # not reported anywhere: the field was set and never read, so the tolerance
    # on the module's ONLY contract between its two halves was unmonitored. A
    # number sitting at 0.0e+00 is the evidence; a number creeping toward 1e-6
    # is the warning that justification promised.
    print("  worst residual accepted by the whole-tile rule (tolerance "
          "%.0e mm2): %s"
          % (1e-6, ", ".join("%s %.3e" % (lt.layer_name,
                                          lt.worst_accepted_residual_mm2)
                             for lt in textures)))

    print("\nREQUIREMENT 2: DOES THE GROUND PLANE MOVE?")
    h3 = ("%-8s %-16s %12s %12s %12s %10s %8s" %
          ("layer", "net", "fill before", "fill after", "symdiff", "comps",
           "PASS"))
    print(h3)
    print("%-8s %-16s %12s %12s %12s %10s %8s"
          % ("", "", "mm2", "mm2", "mm2", "b4 -> aft", ""))
    print("-" * len(h3))
    verdicts = []
    allpass = True
    # THE COARSE INSTRUMENT DOES NOT OVERRULE THE FINE ONE. Two things measure
    # "did the pour move": the symmetric difference of the fill polygons, which
    # is exact integer-nanometre geometry, and the rasterised component areas at
    # --raster-px-per-mm, whose resolution is one pixel -- 0.0025 mm2 at the
    # default 20 px/mm, i.e. five orders of magnitude coarser. Letting the raster
    # cast a vote failed a run whose exact symdiff was 6.5e-09 mm2 because two
    # boundary pixels flipped. So the VERDICT is the exact symdiff plus the
    # component COUNT, which is topology and which the raster does resolve
    # reliably; the areas are reported, with their pixel deltas, as an
    # independent witness rather than as a gate.
    for lt in textures:
        sd = lt.fill_symdiff_mm2
        dpx = _area_delta_px(lt.areas_before, lt.areas_after, tex.px_per_mm)
        comps_same = (dpx is not None and dpx == 0.0)
        ok = (sd is not None and sd <= FILL_MOVE_TOL_MM2
              and lt.components_before == lt.components_after)
        allpass = allpass and ok
        verdicts.append({
            "layer": lt.layer_name, "mode": "add",
            "fill_before_mm2": lt.fill_before_mm2,
            "fill_after_mm2": lt.fill_after_mm2,
            "fill_symdiff_mm2": sd,
            "added_mm2": lt.add_area_mm2,
            "added_pieces": lt.add_pieces,
            "components_identical": comps_same,
            "worst_component_delta_px": dpx,
            "tolerance_mm2": FILL_MOVE_TOL_MM2,
            "pass": ok,
        })
        print("%-8s %-16s %12.4f %12.4f %12s %10s %8s"
              % (lt.layer_name, lt.net, lt.fill_before_mm2, lt.fill_after_mm2,
                 "-" if sd is None else "%.3e" % sd,
                 "%d -> %d" % (lt.components_before, lt.components_after),
                 "PASS" if ok else "FAIL"))
    print("  symdiff is (before \\ after) u (after \\ before) on the FILLED "
          "polygons, not a difference of areas: two different regions can share "
          "an area, they cannot share a symmetric difference of zero. Printed in "
          "full -- the pass tolerance is %.0e mm2 and the measured refill-to-"
          "refill noise floor on this board is exactly 0." % FILL_MOVE_TOL_MM2)
    for lt in textures:
        def fmt(v):
            return " ".join("%.4f" % x for x in v[:6]) + \
                (" ... +%d" % (len(v) - 6) if len(v) > 6 else "")
        dpx = _area_delta_px(lt.areas_before, lt.areas_after, tex.px_per_mm)
        if dpx is None:
            note = "COMPONENT COUNT CHANGED"
        elif dpx == 0.0:
            note = "identical, pixel for pixel"
        else:
            note = ("worst component moved %.1f raster pixel(s) = %.4f mm2; "
                    "the exact symdiff above is the authority"
                    % (dpx, dpx / (tex.px_per_mm ** 2)))
        print("  %s fill components mm2 -- %s" % (lt.layer_name, note))
        print("     before: %s" % fmt(lt.areas_before))
        print("     after : %s" % fmt(lt.areas_after))

    print("\ntiming (s): " + "  ".join("%s %.2f" % (k, v)
                                       for k, v in timings.items()))
    print("  refill of the board carrying %d added copper shapes took %.2f s"
          % (sum(t.shapes_emitted for t in textures),
             timings.get("textured_fill_s", 0.0)))
    return allpass, verdicts


def print_subtract_report(a, tex, results, textures, timings, rbox):
    """The subtract-mode report, unchanged. Returns (allpass, verdicts)."""
    print("board:  %s" % a.board)
    print("kicad:  %s" % pcbnew.GetBuildVersion())
    print("texture: %s  tile %.2f mm (equal-area)  slot %.2f mm  neck %.2f mm "
          "style %s  seed %d"
          % (tex.tiling, tex.tile_mm, tex.slot_mm, tex.neck_mm,
             tex.neck_style, tex.seed))
    print("layers cut: %s" % ", ".join("%s (%s)" % (t.layer_name, t.side)
                                       for t in textures))
    print("raster flood fill at %.0f px/mm over %s"
          % (tex.px_per_mm, tuple(round(v, 2) for v in rbox)))
    print()

    h = ("%-8s %-20s %8s %8s %8s %9s %9s %8s" %
         ("layer", "net", "tiles", "dropped", "walls", "cuts", "zones", "slot mm"))
    print(h)
    print("-" * len(h))
    for lt in textures:
        print("%-8s %-20s %8d %8d %8d %9d %9d %8.1f"
              % (lt.layer_name, lt.net, lt.tiles_placed, lt.tiles_dropped,
                 lt.edge_stats.get("unique_edges", 0),
                 lt.cut_stats.get("cut_segments", 0), lt.zones_emitted,
                 lt.slot_length_mm))

    print_tile_ledger(tex, results, textures)

    verdicts = connectivity_verdict(textures)

    print("\nzone fill, and where every removed mm2 went:")
    h2 = ("%-8s %10s %10s %9s %7s %9s %9s %9s" %
          ("layer", "before", "after", "removed", "of pour", "slots",
           "islands", "slivers"))
    print(h2)
    print("%-8s %10s %10s %9s %7s %9s %9s %9s"
          % ("", "mm2", "mm2", "mm2", "%", "mm2", "mm2", "mm2"))
    print("-" * len(h2))
    for lt, v in zip(textures, verdicts):
        pct = 100.0 * v["removed_mm2"] / lt.fill_before_mm2 \
            if lt.fill_before_mm2 else 0.0
        print("%-8s %10.3f %10.3f %9.3f %6.2f%% %9.3f %9s %9s"
              % (lt.layer_name, lt.fill_before_mm2, lt.fill_after_mm2,
                 v["removed_mm2"], pct, v["expected_mm2"],
                 "-" if v["dropped_mm2"] is None else "%.3f" % v["dropped_mm2"],
                 "-" if v["sliver_mm2"] is None else "%.3f" % v["sliver_mm2"]))
    print("  slots   = what was asked for.")
    print("  dropped = copper the filler DELETED as an island. Must be ~0. Note "
          "island removal is PER ZONE, not per net, so this can fire without "
          "any electrical isolation (measured: --neck-style forest drops 21.0 "
          "mm2 with the component areas unchanged). Real defect either way; "
          "electrical isolation is decided by the component areas below.")
    print("  slivers = copper thinner than the pour's min_thickness that the "
          "filler trims at slot ends. Removes copper, disconnects nothing.")

    print("\nCONNECTIVITY  -- component-for-component, 4-connectivity raster")
    h3 = ("%-8s %8s %8s %8s %8s %9s %8s %7s %6s" %
          ("layer", "comp b4", "comp aft", "8c b4", "8c aft", "probe comp",
           "dropped", "conn", "PASS"))
    print(h3)
    print("-" * len(h3))
    allpass = True
    for lt, v in zip(textures, verdicts):
        allpass = allpass and v["pass"]
        print("%-8s %8d %8d %8d %8d %9s %8s %7s %6s"
              % (lt.layer_name, lt.components_before, lt.components_after,
                 lt.components_before_8, lt.components_after_8,
                 "-" if lt.island_probe_components is None
                 else str(lt.island_probe_components),
                 "yes" if v["dropped_ok"] else "NO",
                 "OK" if v["comp_ok"] else "BROKEN",
                 "PASS" if v["pass"] else "FAIL"))
    for lt in textures:
        def fmt(a):
            return " ".join("%.3f" % x for x in a[:6]) + \
                (" ... +%d" % (len(a) - 6) if len(a) > 6 else "")
        print("  %s component areas mm2" % lt.layer_name)
        print("     before: %s" % fmt(lt.areas_before))
        print("     after : %s" % fmt(lt.areas_after))
        if lt.areas_before and lt.areas_after:
            same = sum(1 for i in range(1, min(len(lt.areas_before),
                                               len(lt.areas_after)))
                       if abs(lt.areas_before[i] - lt.areas_after[i]) <= 1e-9)
            print("     -> largest lost %.3f mm2; %d of the %d smaller "
                  "components are unchanged to 1e-9 mm2"
                  % (lt.areas_before[0] - lt.areas_after[0], same,
                     max(0, min(len(lt.areas_before), len(lt.areas_after)) - 1)))
    if not all(v["have_probe"] for v in verdicts):
        print("  NOTE: --no-island-probe was given, so 'dropped' could not be "
              "separated from 'slivers' and the verdict rests on the total "
              "excess with a 5% tolerance. That is the weak form of this test.")
    print("\n  wall graph acyclic (the connectivity theorem): "
          + ", ".join("%s %s (%d joining walls, %d verts, %d comps)"
                      % (lt.layer_name, "OK" if lt.forest_ok else "CYCLIC",
                         *(lt.forest_detail or (0, 0, 0)))
                      for lt in textures))
    for lt in textures:
        if lt.cut_stats.get("bridge_mm") is not None:
            print("  %s narrowest tie-neck: centreline gap %.3f mm, less two "
                  "%.3f mm slot caps = %.3f mm of copper, vs pour min_thickness "
                  "%.3f mm -> %s"
                  % (lt.layer_name, lt.cut_stats["min_gap_mm"],
                     cap_extend_mm(tex.slot_mm, tex.cap),
                     lt.cut_stats["bridge_mm"], lt.min_thickness_mm,
                     "ok" if lt.cut_stats["bridge_mm"] > lt.min_thickness_mm
                     else "TOO NARROW -- the filler deletes copper thinner than "
                          "min_thickness, which deletes the neck and then the "
                          "cell"))

    print("\ntiming (s): " + "  ".join("%s %.2f" % (k, v)
                                       for k, v in timings.items()))
    print("  the number that decides viability: refill of the TEXTURED board "
          "with %d keepout zones took %.2f s"
          % (sum(t.zones_emitted for t in textures),
             timings.get("textured_fill_s", 0.0)))
    return allpass, verdicts


def _gain_variants(a):
    """[(filename tag, gain)] -- always the true board, plus a gained copy."""
    out = [("", 1.0)]
    g = getattr(a, "appearance_gain", 1.0)
    if g and g != 1.0:
        out.append(("_gain%g" % g, float(g)))
    return out


def finish_texture_run(a, tex, board, textures, verdicts, timings, rbox,
                       allpass):
    """Renders, JSON and DRC. Shared by both modes. Returns the exit code."""
    # ---- renders ---------------------------------------------------------
    if a.render_png:
        for lt in textures:
            lid = board.GetLayerID(lt.layer_name)
            me = board.GetDesignSettings().m_MaxError
            if tex.mode == "add":
                lbl = ("%s  %s  ADD %s %s tile %.2f gutter %.2f  net %s"
                       % (pathlib.Path(a.out).name, lt.layer_name, tex.tiling,
                          tex.add_fill, tex.tile_mm, tex.slot_mm,
                          tex.add_net or "floating"))
            else:
                lbl = ("%s  %s  %s tile %.2f slot %.2f neck %.2f"
                       % (pathlib.Path(a.out).name, lt.layer_name, tex.tiling,
                          tex.tile_mm, tex.slot_mm, tex.neck_mm))
            p1 = "%s_%s.png" % (a.render_png, lt.layer_name.replace(".", "_"))
            render_copper_png(board, lid, p1, a.render_px_per_mm,
                              max_error=me, label=lbl,
                              mirror=(lt.side == "back"))
            print("wrote %s" % p1)
            stem = "%s_%s" % (a.render_png, lt.layer_name.replace(".", "_"))
            for gtag, gval in _gain_variants(a):
                pa = "%s_appearance%s.png" % (stem, gtag)
                render_board_appearance(board, lt.side, pa, a.render_px_per_mm,
                                        max_error=me, label=lbl,
                                        mirror=(lt.side == "back"), gain=gval)
                print("wrote %s" % pa)
            cx, cy = _densest_spot(lt)
            if cx is not None:
                hz = a.zoom_mm / 2.0
                zb = (cx - hz, cy - hz, cx + hz, cy + hz)
                p2 = "%s_%s_zoom.png" % (a.render_png,
                                         lt.layer_name.replace(".", "_"))
                render_copper_png(board, lid, p2, a.zoom_px_per_mm, bbox=zb,
                                  max_error=me,
                                  label="%s  %.1f mm across" % (lt.layer_name,
                                                                a.zoom_mm),
                                  mirror=(lt.side == "back"))
                print("wrote %s" % p2)
                for gtag, gval in _gain_variants(a):
                    p3 = "%s_zoom_appearance%s.png" % (stem, gtag)
                    render_board_appearance(
                        board, lt.side, p3, a.zoom_px_per_mm, bbox=zb,
                        max_error=me,
                        label="%s  %.1f mm across" % (lt.layer_name, a.zoom_mm),
                        mirror=(lt.side == "back"), gain=gval)
                    print("wrote %s" % p3)

    # ---- the fingerprint, one image per side -----------------------------
    if a.fingerprint_png:
        tilings = _import_tilings()
        outline = _sps()
        board.GetBoardPolygonOutlines(outline, True)
        bb = board.GetBoardEdgesBoundingBox()
        obox = (nm_to_mm(bb.GetLeft()), nm_to_mm(bb.GetTop()),
                nm_to_mm(bb.GetRight()), nm_to_mm(bb.GetBottom()))
        commit = board_commit(a.board)
        level = (tilings.SPECTRE_PATCH_LEVEL
                 if tex.tiling.startswith("spectre") else None)
        for lt in textures:
            rings = lt.placed_rings or []
            # THE TILE AREA, and it is labelled as such because it is NOT the
            # copper area and the two differ by a lot. Each tile is inset by
            # half a gutter before it is emitted, so on this board 274 tiles are
            # 2466.0 mm2 of tile and 1982.3 mm2 of copper -- a 20% gap. An image
            # captioned bare "area" invites the reader to quote the wrong one.
            area = lt.tile_area_mm2
            perm = lt.permitted_mm2
            stamp = [
                ("tiling", tex.tiling),
                ("tile_mm", "%.4f" % tex.tile_mm),
                ("level", "-" if level is None else str(level)),
                ("tiles", str(len(rings))),
                ("tile-area", "%.1f mm2" % area),
                ("of-permitted", ("%.2f%%" % (100.0 * area / perm))
                                 if perm > 0 else "-"),
                ("edge-inset", "%.3f mm" % a.edge_inset),
                ("frame-inset", "%.3f mm" % (a.edge_inset
                                             if a.frame_inset is None
                                             else a.frame_inset)),
                ("seed", str(tex.seed)),
                ("layer", "%s (%s)" % (lt.layer_name, lt.side)),
                ("board", "%s@%s" % (pathlib.Path(a.board).name, commit)),
                ("geom", (lt.placed_digest or "")[:16]),
            ]
            pf = "%s_%s.png" % (a.fingerprint_png,
                                lt.layer_name.replace(".", "_"))
            render_fingerprint_png(
                rings, obox, pf, a.fingerprint_px_per_mm,
                outline=outline, mirror=(lt.side == "back"), stamp=stamp,
                caption=NOT_QUITE_SUPERTILE)
            print("wrote %s  (%d tiles, %.1f mm2)" % (pf, len(rings), area))

    if a.texture_json:
        doc = {
            "board": a.board, "out": a.out,
            "board_commit": board_commit(a.board),
            "kicad": pcbnew.GetBuildVersion(),
            # RECORDED BECAUSE IT SILENTLY PARTICIPATES. Every Deflate and every
            # TransformShapeToPolygon in this pipeline is approximated to the
            # board's DRC max_error, including the board-outline deflate that
            # produces both the permitted region and the board-first tiling
            # frame. So a design setting that changes no copper whatsoever can
            # move the mask and move the pattern. It is not a knob this tool
            # owns; the least it can do is say which value produced the numbers.
            "max_error_nm": board.GetDesignSettings().m_MaxError,
            "edge_inset_mm": a.edge_inset,
            "frame_inset_mm": (a.edge_inset if a.frame_inset is None
                               else a.frame_inset),
            "texture_options": {k: v for k, v in vars(tex).items()},
            "timings_s": timings,
            "raster_bbox_mm": rbox,
            "layers": [{
                # placed_rings is excluded by SIZE, not by secrecy: 660 tiles of
                # 15 points is a megabyte of JSON per layer. placed_digest is
                # kept, and it is the thing a reproducibility check compares.
                k: v for k, v in vars(lt).items()
                if k not in ("slots", "added", "placed_rings")
            } for lt in textures],
            "verdicts": verdicts,
        }
        pathlib.Path(a.texture_json).write_text(json.dumps(doc, indent=1,
                                                          default=str),
                                                encoding="utf-8")
        print("wrote %s" % a.texture_json)

    # ---- DRC -------------------------------------------------------------
    drc_fail = False
    if a.drc:
        out_json = a.drc_json or (str(a.out) + ".drc.json")
        info = run_drc(a.out, out_json, a.kicad_cli)
        print("\nDRC: %s" % info["cmd"])
        print("  %.1f s, rc=%d, %s" % (info["seconds"], info["rc"],
                                       info["stdout"].replace("\n", " | ")))
        if info["stderr"]:
            print("  stderr: %s" % info["stderr"])
        if pathlib.Path(out_json).exists():
            s = drc_summary(out_json)
            print("  textured board: %d violations %s, %d unconnected"
                  % (s["total"], s["by_severity"], s["unconnected"]))
            if s["by_severity"].get("error"):
                drc_fail = True
            # UNCONNECTED ITEMS ARE NOT IN `violations`, AND THEY ARE ERRORS.
            # kicad-cli writes them to a separate top-level `unconnected_items`
            # array, so a check that only reads violations[].severity sees
            # "206 warnings, 0 errors" on a board with hundreds of connectivity
            # errors. Measured: add mode with --add-net GNDREF scores exactly the
            # baseline's 206 warnings AND 499 unconnected items, every one of
            # them severity "error" -- each added polygon is a GNDREF node with
            # no path to the GNDREF net. Without this branch that board passed.
            base_unconn = 0
            if a.drc_baseline and pathlib.Path(a.drc_baseline).exists():
                base_unconn = drc_summary(a.drc_baseline)["unconnected"]
            if s["unconnected"] > base_unconn:
                drc_fail = True
                print("  UNCONNECTED ITEMS: %d, against %d in the baseline. "
                      "These carry severity 'error' but live OUTSIDE the "
                      "violations array, so they do not appear in the severity "
                      "counts above." % (s["unconnected"], base_unconn))
            if a.drc_baseline:
                base, new, rows = drc_delta(a.drc_baseline, out_json)
                print("  baseline: %d violations %s"
                      % (base["total"], base["by_severity"]))
                if rows:
                    print("  what the texture changed:")
                    for sev, typ, na, nb, d in rows:
                        print("     %-8s %-28s %5d -> %5d  (%+d)"
                              % (sev, typ, na, nb, d))
                else:
                    print("  what the texture changed: NOTHING -- violation "
                          "counts identical by type and severity")

    if not allpass:
        print("\nCONNECTIVITY FAILED -- see the table above.", file=sys.stderr)
        return 3
    if drc_fail:
        print("\nDRC reported ERRORS on the textured board.", file=sys.stderr)
        return 4
    return 0


def _densest_spot(lt):
    """A point guaranteed to be ON the texture, and near the middle of it.

    The centre of the slot set's bounding box is not usable: on this board the
    permitted region is a ring around the HS1 envelope, so that centre lands in
    the middle of the heatsink where there is no texture at all. So take the
    centroid of the slot components and then snap to the real component nearest
    it.
    """
    src = lt.added if lt.mode == "add" else lt.slots
    if src is None or src.OutlineCount() == 0:
        return (None, None)
    centres = []
    for i in range(src.OutlineCount()):
        bb = src.Outline(i).BBox()
        centres.append((nm_to_mm(bb.GetLeft() + bb.GetWidth() // 2),
                        nm_to_mm(bb.GetTop() + bb.GetHeight() // 2)))
    gx = sum(c[0] for c in centres) / len(centres)
    gy = sum(c[1] for c in centres) / len(centres)
    return min(centres, key=lambda c: (c[0] - gx) ** 2 + (c[1] - gy) ** 2)


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # os._exit, not sys.exit: the BOARD destructor at interpreter shutdown
    # segfaults this build often enough to truncate the report that a normal
    # exit is not safe. Every result is already printed and every file flushed.
    os._exit(rc if isinstance(rc, int) else 0)
