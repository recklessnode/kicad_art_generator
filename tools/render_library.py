#!/usr/bin/env python3
"""RETIRED. Use tools/build_library.py with an artlib.toml sidecar.

This file used to hold a hand-curated LIBRARY manifest -- 12 entries, one per
source asset, each with its own flags and size list -- and render the whole
footprint library from it. `tools/build_library.py` supersedes it, and the two
ran side by side for long enough to do damage. This is a tombstone rather than
a deletion because the failure it caused is worth keeping in front of whoever
looks here next.

WHY IT IS RETIRED, AND NOT MERELY DEPRECATED
--------------------------------------------
TWO SOURCES OF TRUTH FOR THE SAME TWELVE ASSETS. build_library reads
art-assets/artlib.toml; this file read the LIBRARY list below it. They covered
the same sources with DIFFERENT flags and DIFFERENT size lists, and which one a
committed footprint came from depended only on which tool somebody last ran.
Measured on the shipped library: 8 of 27 parts carried a `tonemap:` tag (built
here from artlib) and 19 did not (built from the manifest). The same artwork,
generated two ways.

That is why repairs kept not sticking. Sizes and flags fixed in artlib had no
effect on the 19, and a run of this file would have regenerated all of them
from the stale manifest -- including the serif emission that artlib had just
retired for shipping silk ink at 52% of the fabrication floor.

CURATED STAGING WAS ACTIVELY DANGEROUS. This file copied
library/RecklessArt.pretty/*.kicad_mod into the output BY FILENAME. The
generator's own copy of art_hex_asic_window had drifted to the PRE-HOLES
version -- 0 pads, 12 fp_poly, against the board repo's 6 plated pads -- so a
full run would have silently overwritten the good part with the one JLCPCB
rejected on 2026-08-27 with "There are no drill in your file". Nothing warned;
the copy is unconditional and matches on name alone.

THE MANIFEST IS NOT LOST. Every entry, with its sizing reasoning, is in git
history (and the per-piece reasoning that survived review now lives in the
artlib.toml sections, which is where a reader will look for it). The two
hand-authored parts this file used to stage -- art_hex_asic_window and
art_btc_whitepaper_b -- are checked in at library/RecklessArt.pretty/ and are
un-ignored explicitly by .gitignore; they are placed from the board repo's own
copies and need no staging step.

WHAT TO RUN INSTEAD
-------------------
    python3 tools/build_library.py -o <LIB.pretty> \\
        --options <path>/artlib.toml \\
        --palette-mask <purple|white|black> \\
        <asset> [<asset> ...]

build_library is the better tool on the points that matter here: it reads a
declarative sidecar instead of a hard-coded list, it imports verify_art rather
than spawning it, it keeps a journal and an undo directory, and it refuses to
write inside a git working tree it does not own. See its module docstring for
why preview rendering was removed from it, which is the same class of problem
as the staging above.

ONE THING build_library DOES NOT DO, DELIBERATELY: it has no ink-floor check of
its own, because verify_art runs the ink floor on BOARDS ONLY. A footprint-level
PASS means "no defect a convex-hull caliper can see", which on glyphs and badges
is much weaker than it reads. To test a footprint honestly, wrap it in a
throwaway board and verify that.
"""
import sys

MESSAGE = __doc__.strip()


def main(argv=None):
    sys.stderr.write(MESSAGE + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
