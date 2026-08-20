#!/usr/bin/env python3
"""Build and maintain a KiCad .pretty art library from image files.

Point it at an image or a directory of images and an output library::

    python3 tools/build_library.py assets/normalised -o output/RecklessArt.pretty

It UPDATES AND APPENDS, and that is the whole of what it does. Footprints
this run produces are written; footprints already in the library that this run
did not produce are left exactly alone -- not read, not rewritten, and never
deleted. THIS TOOL HAS NO DELETE PATH AT ALL. A full rebuild is `rm -r
LIB.pretty` followed by a normal run.

Every piece is emitted to a temporary file in the SYSTEM temporary directory,
guarded, verified with tools/verify_art.py, and only then installed into the
library. A piece whose verdict is FAIL is not installed, and a failed update
leaves the previous good footprint in place.

A piece whose verdict is WARN **is** installed. That is a deliberate choice,
not an oversight: every real piece in this corpus warns about something -- a
gap under one fab's floor, a feature under another's -- and a tool that
refused every WARN could not build the library it exists to maintain. So the
promise is narrower and true: nothing reaches the library unexamined. Every
WARN and every line of its DETAIL is printed to stdout, counted in the footer
and named again at the end, and --strict turns a WARN into a failure for
anyone who wants the stricter contract. A warning whose content lives only in
a JSON file is not a warning.

WHAT THIS TOOL MAY OVERWRITE
----------------------------
Only footprints it produced itself. A footprint is ITS OWN when the journal
beside the library names it, or when its (descr) carries emit_art's own stamp
("kicad_art_generator/emit_art.py"). Anything else is FOREIGN, and a name
collision with a foreign footprint is refused before anything is built.

This is the real library's shape, not a hypothetical: RecklessArt.pretty mixes
image-derived footprints with art_hex_asic_window (tools/texture_board.py,
carries Edge.Cuts) and art_btc_whitepaper_b (tools/microtext.py, 1534
fp_text). Neither is reproducible by this tool and both have exactly the kind
of name an image could collide with. --overwrite-foreign is the explicit way
through, and it permits an OVERWRITE -- there is nothing here that deletes.

THE LIBRARY IS WHERE THE ARTWORK LANDS, SO -o IS THE PATH THAT IS GUARDED
-------------------------------------------------------------------------
Every footprint installed here is derived from a source image, the corpus
includes third-party and brand material, and a git working tree is a thing
that gets pushed. So an output library inside a working tree that does not
ignore it is refused, and --allow-tracked-library is the way through.

That guard used to exist only for previews: _git_toplevel and _git_ignores
were written, tested, and then called from nowhere except the preview check,
while -o -- the directory this tool actually fills with derived art -- had no
containment check of any kind. Reproduced in the real public repo with real
MFB art: exit 0, no warning.

SatoshiStarter/RecklessArt.pretty is the legitimate opposite case. It is
TRACKED on purpose, in a PRIVATE repo, and it has to keep working, which is
why the answer is an override flag rather than a rule with an exception
carved into it.

EVERYTHING THIS TOOL WRITES, ENUMERATED -- and every one of them is checked
---------------------------------------------------------------------------
"The guard covers -o" is only worth saying if -o is the whole list. It is now,
and this is the list, exhaustively:

  1. LIB.pretty/                        the directory itself (mkdir)
  2. LIB.pretty/NAME.kicad_mod          each installed footprint
  3. LIB.pretty/.NAME.kicad_mod.XXXX    the cross-device install temporary,
                                        unlinked on failure, replaced away on
                                        success -- see _install()
  4. LIB.pretty.build.json              the journal, or wherever --journal
                                        points
  5. $TMPDIR/build_library_XXXX/...     the emit staging file and emit_art's
                                        --report-json, in the SYSTEM temp area

1-3 are inside the library, which is checked. 5 is OS-owned temp, on nobody's
working tree. 4 is NOT inside the library -- it is a SIBLING of it by design,
because `kicad-cli fp upgrade -o` copies only .kicad_mod files and anything
kept inside a .pretty is silently lost the first time somebody upgrades it. A
sibling of a checked path is not a checked path, so THE JOURNAL IS CHECKED
TOO, on its own, by the same rule. Round 4 asserted "the -o guard covers what
this tool writes" while the stage, the undo directory AND the journal were all
landing in lib.parent unchecked; two of those three no longer exist, and the
third is now checked rather than asserted about.

verify_art is imported, not spawned, and it shells out to kicad-cli against
its own tempfile.TemporaryDirectory -- system temp, category 5.

PREVIEWS AND --regenerate WERE REMOVED (ROUND 4)
------------------------------------------------
Neither was ever asked for. Between them they were the sole cause of every
defect three hardening rounds could not close, so they are gone rather than
patched again.

PREVIEW RENDERING is gone entirely: --preview-dir, the render staged for every
piece, the .build_library_previews marker, the art-tree rules, and the
journal's "source_dirs" memory that existed only to feed those rules. A
preview is a clean, recognisable COLOUR RENDER OF THE SOURCE ARTWORK -- a
verifier opened one and identified the MFB character from it -- so it needed
containment the tool never got right: a render was planted in a TRACKED
location of a public repo; and because the stage sat INSIDE the library and a
render was made for every piece on every run, the tool could discover its own
output and build alpha_20mm_20mm with no --preview-dir given at all. The
art-tree rule grew until it refused the ordinary art/ + out/ sibling layout,
and "source_dirs" made that refusal permanent for that library.

THIS TOOL NOW WRITES NO IMAGE ANYWHERE. That is what actually closes the
self-ingestion loop -- not a marker file and not a path rule, but having no
render to ingest. Anyone who wants one runs `emit_art.py --preview` and aims
it themselves.

--regenerate is gone: it deleted every footprint it believed this tool had
produced and this run had not. The owner asked for update-and-append and said
a full regenerate would be an acceptable FALLBACK; that is not a request for a
journal-driven garbage collector, and append -- the thing actually asked for
-- works. It produced unrecoverable deletions in two successive rounds, and it
rested on is_ours(), which cannot tell this tool's work from ANY emit_art
output: emit_art stamps "kicad_art_generator/emit_art.py" into every descr it
writes (emit_art.py:3582), so a footprint somebody produced by running
emit_art by hand reads as this tool's own and was in scope to be deleted. A
rebuild is now `rm -r LIB.pretty` and a normal run: aimed by the user, at a
path the user named, by a tool that does not have to guess whose art it is.

THE PERSISTENT STAGING SUBSYSTEM WAS REMOVED (ROUND 5)
------------------------------------------------------
Four rounds of evidence said the same thing: the defect always landed wherever
the staging directory lived. Inside the library, a TemporaryDirectory unwind
on Ctrl-C destroyed the backups it held, and the library ingested its own
preview output. Moved beside the library, the stale-stage sweep began globbing
`.build_library_*` in the PARENT of the library -- a directory the tool does
not own -- and the -o guard covered only the .pretty while the stage, the undo
directory and the journal all landed in that parent, unchecked.

So there is no staging directory any more, no undo directory, no sweep, no
glob over any directory, and no `.build_library_*` convention in either repo.
The shape that replaces it has no failure mode to harden:

  * each piece is emitted to a UNIQUE TEMPORARY FILE in the system temporary
    area, which the OS owns and cleans up and which is on nobody's git tree;
  * it is guarded and verified THERE;
  * it is installed with a single os.replace onto the target.

THE INCUMBENT IS NEVER MOVED, COPIED ASIDE, OR TOUCHED AT ALL until the
os.replace lands on top of it, and os.replace is atomic. So an interrupt at
any instant leaves every footprint either OLD or NEW -- never missing, and
never needing restoration. Nothing is moved aside, so there is nothing to
restore, nothing to sweep, and no rollback that could misreport itself. The
~330 lines of preserve / restore / undo / audit / unwind / second-interrupt
machinery that existed to make a mid-install interrupt survivable are gone,
because the thing they defended against can no longer happen.

os.replace refuses to cross filesystems (EXDEV), and the system temp area very
often IS on another filesystem from the library -- under WSL it always is. So
the cross-device case is the NORMAL path here, not an exotic one, and it is
explicit: copy into the TARGET DIRECTORY under a unique dot-name, then
os.replace from there, which is same-directory and therefore same-filesystem
and therefore still atomic. The temporary is unlinked on any failure. That
copy is the ONLY thing this tool writes into the library besides the
footprints themselves; it is per-piece, self-cleaning, and inside the
directory the -o guard checks.

A run either installed a piece or it did not, and which of the two is READ OFF
THE DISK -- the target's bytes are compared against the bytes that were meant
to land -- never taken from what the run intended.

WHAT THIS FILE OWNS AND WHAT IT BORROWS
---------------------------------------
emit_art.py is invoked as a SUBPROCESS and its --report-json is parsed. Its
refusals are exit codes plus stderr (2 ToneDropped / RegionOpError / microtext
/ --ink-tone misuse, 3 EMPTY OUTPUT, 4 CopperInWaste -- emit_art.py:3924-3980),
not exceptions that survive an import boundary, and a subprocess also isolates
a segfault or an OOM on one piece from the rest of the run.

verify_art.py is IMPORTED: verify_file(path, cfg) -> (verdict, [Check]) is a
clean API returning structured results. cfg is built once per run, which is
what makes per-file cost ~1.7 s instead of re-parsing the palette and
re-probing kicad-cli for every piece. verify_file copies cfg internally per
file (verify_art.py:2653), so parts built for different fab profiles do not
contaminate each other.

render_library.py is neither imported nor modified. Its LIBRARY list is a
curated manifest; the sidecar (--help-options) is the general form of it.

HOW "UNCHANGED" IS KNOWN
------------------------
By re-emitting and comparing bytes. Nothing else. Not mtime -- prep_assets.py
rewrites assets/normalised wholesale and re-stamps every file. Not a
source-hash cache -- a cache key that omits the emitter reports UNCHANGED for a
footprint whose geometry today's emitter would build differently, and a key
that includes the emitter's hash invalidates on every commit of emit_art.py and
buys nothing. Re-emitting costs 2.5-7.4 s per piece; there is deliberately no
--assume-unchanged.

This is only safe because emit_art is deterministic: --uuids is off by default
(KiCad mints them on load) and even with it on, ArtFp._uuid is a uuid5 of
"name:index" (emit_art.py:1218-1233). Byte-identical re-runs are therefore
achievable, and an unchanged piece is not written at all, so mtime does not
churn and re-running does not produce a spurious git diff.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import errno
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import verify_art                                     # noqa: E402
import fab_profiles                                   # noqa: E402
import palette                                        # noqa: E402
import tone_map                                       # noqa: E402
import fidelity                                       # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:                            # pragma: no cover
    tomllib = None

TOOLS = HERE
EMIT_ART = HERE / "emit_art.py"

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".svg")
SIDECAR_NAME = "artlib.toml"
SIDECAR_SCHEMA = 1
DEFAULT_SIZE_MM = 20.0
DEFAULT_MAX_DROPPED_PCT = 1.0
# A tone that emitted no polygons at all fails only once it was a REGION of the
# design. MEASURED need for the threshold: the purple rebuild refused
# mfb_lockup_3tone over "T3 (181 px) -> 0 polygons", which is 0.03% of its ink
# -- the antialias residue between the white and the orange. 0.5% is an order
# of magnitude above that and two below the smallest deliberate region in the
# corpus (satoshi_points' red accent at 0.42%... which is why it is DECLARED
# rather than left to be dropped).
DROPPED_TONE_FAIL_PCT = 0.5
MIN_KICAD_MAJOR = verify_art.MIN_KICAD_MAJOR

# emit_art stamps this into every (descr) it writes (emit_art.py:3581-3583).
# It is the DURABLE half of provenance: the journal can be deleted, moved or
# restored from a backup, but the stamp travels inside the footprint.
EMIT_STAMP = "kicad_art_generator/emit_art.py"

# The descr is the 6th line of an emit_art footprint. Reading a prefix keeps
# the provenance probe cheap next to art_btc_whitepaper_b, which is 1534
# fp_text elements and megabytes of file.
PROVENANCE_PROBE_BYTES = 64 * 1024

# THE STAGE IS IN THE SYSTEM TEMPORARY DIRECTORY, and it has no name this tool
# is required to recognise later. Rounds 2, 3 and 4 each moved a NAMED,
# PERSISTENT staging directory somewhere new and each new home came with its
# own destruction path -- inside the library it was ingested and its backups
# were rmtree'd by a TemporaryDirectory unwind; beside the library the
# stale-stage sweep started globbing a directory the tool does not own. The
# subsystem is gone rather than relocated a fourth time. tempfile picks the
# location, the OS owns it, nothing globs for it, and no .gitignore anywhere
# needs a rule for it.
STAGE_PREFIX = "build_library_"

# Win32 MAX_PATH. MEASURED, not remembered: in C:\Users\prael\AppData\Local\
# Temp\np a 180-char footprint name (241-char host path) loads; a 200-char name
# (261-char host path) fails with "Unable to load library". The budget is a
# property of where the LIBRARY lives, not of the name, so it is computed from
# the library's host path at run time.
MAX_PATH = 260

# Reserved DOS device names. CON.kicad_mod cannot be created on Windows at all;
# refusing by name beats a bare OSError from deep inside an install.
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", "CLOCK$"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}

# emit_art flags this tool owns. argparse takes the LAST occurrence, so a
# user-supplied duplicate would silently redirect the output or rename the
# footprint -- the exact silent-wrong-build this tool exists to prevent.
#
# MATCHING THESE BY EXACT STRING DOES NOT WORK, and that is not a subtlety:
# emit_art's argparse abbreviates long options, so --nam, --na and --n all
# reach --name. REPRODUCED: --emit-arg=--nam --emit-arg=EVIL installed a file
# whose first line was (footprint "EVIL") and reported it as
# "ADDED plain_mark_20mm ... verify PASS", exit 0 -- success reported on a
# footprint that is not what it says it is. -o also takes its value attached
# (-o/tmp/evil), which contains no '=' for a split-on-equals guard to find.
# _reserved_hit() below resolves a token the way argparse would, against
# emit_art's ACTUAL option list.
RESERVED_EMIT_ARGS = {
    "--labels": "the source is the SOURCE argument",
    "--width-mm": "the size is --size, or 'sizes' in the sidecar",
    "--name": "the name is derived from the source; use 'name' in the sidecar",
    "-o": "the output is -o LIB.pretty",
    "--output": "the output is -o LIB.pretty",
    "--report-json": "build_library parses this itself",
    "--preview": ("a preview is a colour render of the SOURCE artwork; this "
                  "tool writes no images at all and will not aim emit_art's "
                  "renderer at an unguarded path on your behalf -- run "
                  "emit_art.py --preview yourself and choose where it lands"),
    "--min-area-mm2": "use --min-area, or 'min_area' in the sidecar",
    "--descr": "use 'descr' in the sidecar",
    "--allow-empty": "build_library refuses a footprint with no geometry",
    "--tone-map": "the map is 'tones' in the sidecar; this tool serialises it",
    "--palette-mask": "the colourway is 'mask' in the sidecar",
    "--ink-tone": ("declare the colour instead: 'tones' in the sidecar says "
                   "which ink becomes which tone, and says it per colour. "
                   "--ink-tone re-points whatever single tone the quantiser "
                   "happened to choose, which is a different statement every "
                   "time the palette moves -- and the palette moved"),
}

ADDED, UPDATED, UNCHANGED, FAILED = "ADDED", "UPDATED", "UNCHANGED", "FAILED"
UNTOUCHED = "UNTOUCHED"

INVERT_NOTE = (
    "INVERTED BY build_library. Quantised on its own merits this piece lands "
    "entirely on T5 -- the colour of the board itself -- so emit_art refused "
    "it as EMPTY OUTPUT and it was re-emitted with --ink-tone T1, i.e. drawn "
    "in silk white, the way black line art is actually fabricated on a "
    "black-mask board.")


# ---------------------------------------------------------------------------
# host paths
# ---------------------------------------------------------------------------

_WSLPATH = shutil.which("wslpath") if sys.platform != "win32" else None
_HOSTCACHE: dict[str, str] = {}


def _wslpath(s: str) -> str | None:
    try:
        r = subprocess.run([_WSLPATH, "-w", s], capture_output=True, text=True,
                           timeout=20, stdin=subprocess.DEVNULL)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def host_path(p: Path | str) -> str:
    """The path as the Windows side of the world sees it.

    A Windows kicad-cli.exe driven from a WSL Python gets its arguments
    verbatim, and MAX_PATH is measured against the Windows path, not the
    /mnt/c one. The library may not exist yet -- the budget has to be knowable
    BEFORE anything is created -- so a path wslpath will not translate falls
    back to its nearest existing ancestor plus the remainder.
    """
    s = str(p)
    if sys.platform == "win32" or not _WSLPATH:
        return s
    if s in _HOSTCACHE:
        return _HOSTCACHE[s]
    out = _wslpath(s)
    if out is None:
        q = Path(s).resolve()
        tail: list[str] = []
        while not q.exists() and q.parent != q:
            tail.append(q.name)
            q = q.parent
        base = _wslpath(str(q))
        out = "\\".join([base] + list(reversed(tail))) if base else s
    _HOSTCACHE[s] = out
    return out


def is_windows_host(s: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", s)) or s.startswith("\\\\")


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------

def size_suffix(mm: float) -> str:
    """12 -> '12mm', 12.5 -> '12p5mm'.

    Dots are LEGAL in a KiCad 10 footprint name -- 'logo.v2_20mm' was verified
    to load, re-serialise and plot -- so 'p' is a readability choice, made so a
    name never looks like it carries a file extension. It also reproduces the
    existing corpus (bitcoin_b_10mm, mfb_lockup_30mm, ...) exactly.
    """
    return f"{mm:g}".replace(".", "p").replace("-", "m") + "mm"


class NameError_(ValueError):
    pass


def slug(raw: str, allow_unicode: bool = False) -> str:
    """NFC-normalise, keep [A-Za-z0-9_-], collapse everything else to one '_'.

    The author's case is preserved: 'Logo' stays 'Logo'. KiCad accepts spaces,
    dots, '#', CJK and a great deal more (all verified against kicad-cli 10.0.0
    with fp upgrade + fp export svg), so this is not a KiCad constraint -- it
    is so that the bare string that ends up inside every .kicad_pcb placing the
    footprint is one nobody has to quote or transliterate.
    """
    s = unicodedata.normalize("NFC", raw)
    if not allow_unicode:
        bad = sorted({ch for ch in s if ord(ch) > 127})
        if bad:
            shown = ", ".join(f"{ch!r} (U+{ord(ch):04X})" for ch in bad)
            raise NameError_(
                f"non-ASCII character(s) in the name: {shown}. KiCad 10 accepts "
                f"them (verified), but the name is a bare string inside every "
                f".kicad_pcb that places the footprint. Pass "
                f"--allow-unicode-names to keep them, or set 'name' for this "
                f"piece in the sidecar")
    if allow_unicode:
        kept = "".join(ch if (ch.isalnum() or ch in "_-") else "\x00" for ch in s)
    else:
        kept = re.sub(r"[^A-Za-z0-9_-]", "\x00", s)
    out = re.sub(r"\x00+", "_", kept)
    out = re.sub(r"_+", "_", out).strip("_")
    if not out:
        raise NameError_(f"{raw!r} contains nothing usable as a name")
    return out


def check_reserved(name: str) -> None:
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise NameError_(
            f"{name!r} is a reserved DOS device name; Windows cannot create "
            f"{name}.kicad_mod at all. Rename the source or set 'name' in the "
            f"sidecar")


# ---------------------------------------------------------------------------
# provenance: what this tool is allowed to overwrite
# ---------------------------------------------------------------------------

def journal_path_for(lib: Path, explicit: str | None = None) -> Path:
    return Path(explicit) if explicit else lib.with_name(lib.name + ".build.json")


def load_produced(journal: Path) -> set[str]:
    """Footprint names this tool has recorded producing into this library.

    Accumulated across runs, not just the last one: a run narrowed to two
    pieces must not turn the other nineteen into strangers.
    """
    try:
        rec = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return set()
    if not isinstance(rec, dict):
        return set()
    names: set[str] = set()
    got = rec.get("produced")
    if isinstance(got, list):
        names |= {str(x) for x in got}
    for p in rec.get("pieces") or []:
        if isinstance(p, dict) and p.get("name"):
            names.add(str(p["name"]))
    return names


def has_emit_stamp(path: Path) -> bool:
    """Does this footprint carry emit_art's own provenance stamp?"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(PROVENANCE_PROBE_BYTES)
    except OSError:
        return False                      # unreadable is FOREIGN, by default
    return EMIT_STAMP.encode("utf-8") in head


def is_ours(path: Path, produced: set[str]) -> bool:
    return path.stem in produced or has_emit_stamp(path)


_CASE_CACHE: dict[str, bool | None] = {}


def case_insensitive_fs(where: Path) -> bool | None:
    """True/False for the filesystem at `where`, None if it cannot be probed.

    The collision message used to assert case-insensitivity without looking.
    On the ext4 the tests run on that sentence is simply false, and a refusal
    that explains itself with a false fact teaches the reader to distrust the
    next one.
    """
    d = where
    while not d.is_dir() and d.parent != d:
        d = d.parent
    key = str(d)
    if key in _CASE_CACHE:
        return _CASE_CACHE[key]
    verdict: bool | None = None
    # Read-only probe first: an existing entry whose name has a letter in it
    # answers the question without writing anything. The library may be inside
    # a source tree, and "nothing is ever written into a source directory" is
    # a promise this tool makes in its own --help.
    try:
        for entry in sorted(d.iterdir())[:64]:
            flipped = entry.with_name(entry.name.swapcase())
            if flipped.name == entry.name:
                continue                       # no cased character in it
            # samefile, not exists: on a case-SENSITIVE filesystem the flipped
            # name could be a second, different file.
            verdict = flipped.exists() and os.path.samefile(entry, flipped)
            break
    except OSError:
        verdict = None
    if verdict is None:
        try:
            with tempfile.NamedTemporaryFile(dir=d, prefix="CaseProbe",
                                             suffix=".tmp", delete=False) as fh:
                probe = Path(fh.name)
            try:
                flipped = probe.with_name(probe.name.replace("CaseProbe",
                                                             "caseprobe"))
                verdict = flipped.exists()
            finally:
                probe.unlink(missing_ok=True)
        except OSError:
            verdict = None
    _CASE_CACHE[key] = verdict
    return verdict


# ---------------------------------------------------------------------------
# sidecar
# ---------------------------------------------------------------------------

SECTION_KEYS = {"name", "sizes", "min_area", "emit", "descr",
                "mask", "tones", "tol_de", "unmapped_budget_pct", "inner_ok",
                "skip"}
DEFAULTS_KEYS = {"sizes", "min_area", "emit", "descr",
                 "mask", "tol_de", "unmapped_budget_pct", "inner_ok"}

HELP_OPTIONS = """\
build_library sidecar -- per-piece settings, TOML
=================================================

Art is not uniform, and the proof is the library that already exists. Measured
against tools/render_library.py's manifest -- 11 entries, 21 footprints -- 4
need a footprint name that is not their filename, 2 need --ink-tone T1, the
sizes span 10 mm to 90 mm, and the min-area setting takes FOUR different
values across the eleven ("none", 0.02, 0.10 and "auto", each with the
measurement that chose it written next to it). One flag set for a whole
directory cannot say any of that, and a tool that cannot express the library
it already has is not a replacement for it. So per-piece settings live in a
file BESIDE THE ART.

Beside the art, and not inside the library, for a measured reason: KiCad
tolerates foreign files in a .pretty (fp upgrade and fp export svg both ignore
them), but `kicad-cli fp upgrade -o` copies only *.kicad_mod into its output,
so anything kept inside a .pretty evaporates the first time somebody upgrades
the library into a new directory. The journal is written beside the library for
the same reason.

Default location: artlib.toml in each SOURCE directory. Override with
--options FILE, disable with --no-options.

    schema = 1                      # required; the only supported value is 1

    [defaults]                      # applies to every source under this file
    sizes    = [12, 20]             # finished LONG-EDGE sizes in mm
    min_area = "auto"               # "auto" | "none" | a number in mm2
    emit     = ["--smooth", "0.5"]  # extra emit_art.py arguments
    descr    = "..."                # footprint (descr); provenance is appended

    ["reckless_black.svg"]          # section key = source FILENAME
    name = "reckless_mono"          # footprint name; default is the file stem
    emit = ["--ink-tone", "T1"]     # black ink on a black-mask board

    ["satoshi_miner.png"]
    sizes    = [12, 20]
    min_area = 0.10                 # not "auto": auto leaves legal-AREA
                                    # slivers 0.027 mm wide. 0.05/0.10/0.15
                                    # all emit the same bytes, so 0.10 is the
                                    # middle of a measured plateau

    ["mfb_node_full.svg"]
    sizes = [38, 50]                # not 12/20: at 20 mm the worst F.SilkS
                                    # gap is 0.0616 against a 0.15 floor

    ["*.jpg"]                       # glob sections allowed
    emit = ["--smooth", "1.0"]      # JPEG is what emit_art's --smooth is for

WHICH TONE EACH INK BECOMES -- 'mask' AND 'tones'
    Not a colour preference. On a dark-mask board T5 (bare mask) is the DARKEST
    tone the process can make, so source ink darker than the board cannot be
    represented at all, and nearest-anchor assignment answers that impossibility
    by choosing T5 -- which draws nothing. Measured on the library this tool
    built before the change: satoshi_points lost 29.6% of its ink that way,
    satoshi_little 24.6%, mfb_node_full 12.0%, mfb_node_light 14.5%. The legs,
    the arms and the laurel wreath were simply absent.

    A 'tones' table says what each source colour becomes. Anything not named is
    UNMAPPED and the emit REFUSES past 'unmapped_budget_pct', printing the
    orphan colours as a block you can paste back in. --propose-tones writes the
    first draft of the table for you.

        mask   = "purple"            # black | purple | green | white
        tol_de = 10.0                # a pixel this close to a declared colour
                                     # IS that colour (weighted Lab)
        unmapped_budget_pct = 0.25   # refuse past this much undeclared ink
        inner_ok = false             # allow T4/T7, which need In1.Cu

        ["character.png"]
        tones = [
          { rgb = "#e0a040", tone = "T2" },                          # body
          { rgb = "#c08830", tone = "T2", merge_ok = ["#e0a040"] },  # shading
          { rgb = "#fefefe", tone = "T1" },                          # highlight
          { rgb = "#010101", tone = "T6", off_palette = true },      # outline
        ]

    Per-ink keys, each of them an acknowledgement the tool will not make for you
        tone         the tone id this colour becomes. Required.
        merge_ok     other declared colours it may share that tone with. One
                     finish means exactly ONE metal tone, so three golds really
                     do become one T2 -- but that loses a distinction the
                     artwork has, so it has to be named.
        off_palette  the colour is 55+ weighted-Lab units from the tone. That
                     is a substitution, not an approximation: the Reckless red
                     renders as gold under every assignment there is.
        legibility   "declared" -- the tone is under 8 L* from the board, i.e.
                     drawn and invisible. tools/texture_board.py calls that
                     separation "a sheen and not a graphic".
        note         free text; it ends up in the report.

    skip = true      exclude a source entirely, with the reason in a comment.

KEYS
    [defaults]  sizes, min_area, emit, descr, mask, tol_de,
                unmapped_budget_pct, inner_ok
    section     name, sizes, min_area, emit, descr, mask, tones, tol_de,
                unmapped_budget_pct, inner_ok, skip
                ('name' only in an EXACT-filename section: a glob 'name' would
                 hand the same footprint name to several sources)

PRECEDENCE
    CLI flag > exact-filename section > glob section (longest pattern wins)
             > [defaults] > built-in

    'emit' lists CONCATENATE rather than replace, in that order, so a per-piece
    flag overrides a run-wide one the way argparse does:
        --emit-arg ... , [defaults].emit , glob.emit , exact.emit

TWO HARD ERRORS, both because the alternative is a silent wrong build
    * an UNKNOWN KEY -- a typo'd `size = 20` (singular) that quietly does
      nothing is exactly the unattended failure this tool exists to prevent;
    * a SECTION MATCHING NO SOURCE -- it means art was renamed or moved, and
      the flags that art needed are now not being applied to anything.
      Enforced when the sidecar's own directory was given as a SOURCE, i.e.
      when every file it could speak for was in play. When the run was narrowed
      to individual files the unmatched sections are reported as a note
      instead, because narrowing the run is not the same as losing the art.

RESERVED emit ARGUMENTS
    These are owned by build_library and refused inside 'emit' or --emit-arg,
    because argparse takes the LAST occurrence and a duplicate would silently
    rename the footprint or redirect the output:
""" + "".join(f"        {k:<18} {v}\n" for k, v in sorted(RESERVED_EMIT_ARGS.items()))


class SidecarError(ValueError):
    pass


@dataclass
class Section:
    pattern: str
    exact: bool
    data: dict
    used: bool = False


@dataclass
class Sidecar:
    path: Path
    # The directory whose sources this sidecar speaks for. None means "every
    # source in the run": that is what an explicit --options FILE means, and
    # scoping it to the file's own directory would make --options silently do
    # nothing whenever the settings file does not sit with the art.
    root: Path | None
    defaults: dict
    sections: list[Section]
    enforce_unmatched: bool = False


def _check_keys(where: str, data: dict, allowed: set[str], path: Path) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise SidecarError(
            f"{path}: unknown key(s) in {where}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}. A key that is silently "
            f"ignored is a setting you believe is applied and is not")


def _norm_settings(where: str, data: dict, path: Path) -> dict:
    out = {}
    if "sizes" in data:
        v = data["sizes"]
        if not isinstance(v, list) or not v or not all(
                isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0
                for x in v):
            raise SidecarError(f"{path}: {where}: 'sizes' must be a non-empty "
                               f"list of positive numbers, got {v!r}")
        out["sizes"] = [float(x) for x in v]
    if "min_area" in data:
        out["min_area"] = _norm_min_area(data["min_area"],
                                         f"{path}: {where}: 'min_area'")
    if "emit" in data:
        v = data["emit"]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise SidecarError(f"{path}: {where}: 'emit' must be a list of "
                               f"strings, got {v!r}")
        _check_emit_args(v, f"{path}: {where}: 'emit'")
        out["emit"] = list(v)
    if "descr" in data:
        if not isinstance(data["descr"], str):
            raise SidecarError(f"{path}: {where}: 'descr' must be a string")
        out["descr"] = data["descr"]
    if "name" in data:
        if not isinstance(data["name"], str) or not data["name"].strip():
            raise SidecarError(f"{path}: {where}: 'name' must be a non-empty "
                               f"string")
        out["name"] = data["name"]
    if "mask" in data:
        if not isinstance(data["mask"], str):
            raise SidecarError(f"{path}: {where}: 'mask' must be a string")
        try:
            palette.palette_for(data["mask"])
        except palette.PaletteError as e:
            raise SidecarError(f"{path}: {where}: {e}") from None
        out["mask"] = data["mask"].lower()
    if "skip" in data:
        if not isinstance(data["skip"], bool):
            raise SidecarError(f"{path}: {where}: 'skip' must be true or false")
        out["skip"] = data["skip"]
    if "inner_ok" in data:
        if not isinstance(data["inner_ok"], bool):
            raise SidecarError(f"{path}: {where}: 'inner_ok' must be true or "
                               f"false")
        out["inner_ok"] = data["inner_ok"]
    for k in ("tol_de", "unmapped_budget_pct"):
        if k in data:
            v = data[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise SidecarError(f"{path}: {where}: '{k}' must be a "
                                   f"non-negative number, got {v!r}")
            out[k] = float(v)
    if "tones" in data:
        out["tones"] = _norm_tones(data["tones"], f"{path}: {where}: 'tones'")
    return out


_INK_KEYS = {"rgb", "tone", "merge_ok", "off_palette", "legibility", "note"}


def _norm_tones(v, where: str) -> list[dict]:
    """Validate a declared ink table before anything is emitted.

    Everything here is checkable without loading the image, so it is checked
    here: a typo in a tone id should be one line of output at parse time, not a
    footprint that is missing an arm.
    """
    if not isinstance(v, list) or not v:
        raise SidecarError(f"{where}: must be a non-empty list of "
                           f"{{ rgb = \"#rrggbb\", tone = \"Tn\" }} tables")
    rows, seen = [], {}
    for i, r in enumerate(v):
        at = f"{where}[{i}]"
        if not isinstance(r, dict):
            raise SidecarError(f"{at}: must be a table")
        unknown = sorted(set(r) - _INK_KEYS)
        if unknown:
            raise SidecarError(
                f"{at}: unknown key(s) {', '.join(unknown)}. Allowed: "
                f"{', '.join(sorted(_INK_KEYS))}")
        for req in ("rgb", "tone"):
            if req not in r:
                raise SidecarError(f"{at}: needs '{req}'")
        try:
            rgb = tone_map._hex_to_rgb(r["rgb"])
        except tone_map.ToneMapError as e:
            raise SidecarError(f"{at}: {e}") from None
        h = tone_map.rgb_to_hex(rgb)
        if h in seen:
            raise SidecarError(
                f"{at}: colour {h} is declared twice. Two rows for one colour "
                f"cannot both apply, and which one wins would be an accident "
                f"of ordering")
        seen[h] = True
        tid = str(r["tone"])
        if tid not in palette.TONE_IDS:
            raise SidecarError(f"{at}: tone {tid!r} is not a tone; known: "
                               f"{' '.join(palette.TONE_IDS)}")
        row = {"rgb": h, "tone": tid}
        if "merge_ok" in r:
            m = r["merge_ok"]
            if not isinstance(m, list) or not all(isinstance(x, str) for x in m):
                raise SidecarError(f"{at}: 'merge_ok' must be a list of hex "
                                   f"colours")
            row["merge_ok"] = [tone_map.rgb_to_hex(tone_map._hex_to_rgb(x))
                               for x in m]
        for k, ty in (("off_palette", bool), ("legibility", str),
                      ("note", str)):
            if k in r:
                if not isinstance(r[k], ty):
                    raise SidecarError(f"{at}: '{k}' must be "
                                       f"{'true/false' if ty is bool else 'a string'}")
                row[k] = r[k]
        if row.get("legibility", "") not in ("", "declared"):
            raise SidecarError(
                f"{at}: 'legibility' is either absent or the exact word "
                f"\"declared\"; got {row['legibility']!r}")
        rows.append(row)
    named = set(seen)
    for row in rows:
        for m in row.get("merge_ok", []):
            if m not in named:
                raise SidecarError(
                    f"{where}: {row['rgb']} lists merge_ok = {m}, which is not "
                    f"a declared colour in the same table. A merge can only be "
                    f"permitted between two colours this table actually names")
    # T4/T7 need In1.Cu and are refused per piece rather than here, because the
    # 'inner_ok' that permits them is resolved with the rest of the settings and
    # a message naming the flag has to be able to see the flag.
    return rows


def _norm_min_area(v, where: str) -> str:
    if isinstance(v, bool):
        raise SidecarError(f"{where}: must be 'auto', 'none' or a number in mm2")
    if isinstance(v, (int, float)):
        if v < 0:
            raise SidecarError(f"{where}: must not be negative")
        return "none" if float(v) == 0.0 else repr(float(v))
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("auto", "none"):
            return s
        try:
            f = float(s)
        except ValueError:
            raise SidecarError(f"{where}: must be 'auto', 'none' or a number "
                               f"in mm2, got {v!r}") from None
        if f < 0:
            raise SidecarError(f"{where}: must not be negative")
        return "none" if f == 0.0 else repr(f)
    raise SidecarError(f"{where}: must be 'auto', 'none' or a number in mm2")


_EMIT_OPTS: set[str] | None = None
_ADD_ARG_RE = re.compile(
    r"""add_argument\(\s*((?:["'][^"']*["']\s*,\s*)*["'][^"']*["'])""")
_LITERAL_RE = re.compile(r"""["']([^"']*)["']""")


def _emit_option_strings() -> set[str]:
    """Every option string emit_art's parser defines.

    Read out of the SOURCE rather than by importing emit_art: emit_art is a
    subprocess here on purpose (a segfault or an OOM on one piece must not
    take the run with it), and it builds its parser inside main(), so there is
    nothing importable to introspect. A static scan of the add_argument()
    literals is exact for the way that file is written and costs one read.
    """
    global _EMIT_OPTS
    if _EMIT_OPTS is not None:
        return _EMIT_OPTS
    opts: set[str] = set()
    try:
        src = EMIT_ART.read_text(encoding="utf-8", errors="replace")
    except OSError:                                    # pragma: no cover
        src = ""
    for m in _ADD_ARG_RE.finditer(src):
        for lit in _LITERAL_RE.findall(m.group(1)):
            if not lit.startswith("-"):
                break                                  # a positional argument
            opts.add(lit)
    # Never depend on the scan alone: if emit_art is unreadable or its style
    # changes, the flags this tool owns must still be known.
    opts |= set(RESERVED_EMIT_ARGS) | {"-h", "--help"}
    _EMIT_OPTS = opts
    return opts


def _reserved_hit(token: str) -> str | None:
    """The reserved emit_art option `token` would actually reach, or None.

    Mirrors argparse: an exact match wins outright, otherwise a long option is
    resolved by prefix. A prefix that is ambiguous is refused too when any of
    its candidates is reserved -- argparse would reject it, and guessing on
    the user's behalf is how the abbreviation hole opened in the first place.
    """
    if not token.startswith("-") or token in ("-", "--"):
        return None
    head = token.split("=", 1)[0]
    opts = _emit_option_strings()
    if head.startswith("--"):
        if head in opts:                               # exact match wins
            return head if head in RESERVED_EMIT_ARGS else None
        hits = sorted(o for o in opts
                      if o.startswith("--") and o.startswith(head)
                      and o in RESERVED_EMIT_ARGS)
        return hits[0] if hits else None
    # Short options do not abbreviate, but -oVALUE is a single token.
    for o in sorted(RESERVED_EMIT_ARGS):
        if len(o) == 2 and not o.startswith("--") and token.startswith(o):
            return o
    return None


def _check_emit_args(args: list[str], where: str) -> None:
    for a in args:
        hit = _reserved_hit(a)
        if hit is None:
            continue
        head = a.split("=", 1)[0]
        if head == hit:
            raise SidecarError(
                f"{where}: {head} is owned by build_library -- "
                f"{RESERVED_EMIT_ARGS[head]}. argparse takes the last "
                f"occurrence, so passing it here would silently override the "
                f"tool's own value")
        raise SidecarError(
            f"{where}: {a} reaches emit_art's {hit}, which is owned by "
            f"build_library -- {RESERVED_EMIT_ARGS[hit]}. argparse "
            f"abbreviates long options and attaches short-option values, so "
            f"{head} IS {hit} by the time emit_art parses it, and argparse "
            f"takes the last occurrence. This was reproduced: "
            f"--emit-arg=--nam --emit-arg=EVIL installed a footprint named "
            f"EVIL and reported it as a PASS")


_GLOB_META = re.compile(r"[*?\[]")


def load_sidecar(path: Path, root: Path, enforce: bool) -> Sidecar:
    if tomllib is None:                                # pragma: no cover
        raise SidecarError("this Python has no tomllib; need 3.11+ to read a "
                           "sidecar, or pass --no-options")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise SidecarError(f"{path}: cannot read: {e}") from None
    except tomllib.TOMLDecodeError as e:
        raise SidecarError(f"{path}: not valid TOML: {e}") from None

    schema = data.pop("schema", None)
    if schema is None:
        raise SidecarError(f"{path}: missing `schema = {SIDECAR_SCHEMA}` at the "
                           f"top of the file")
    if schema != SIDECAR_SCHEMA:
        raise SidecarError(f"{path}: schema {schema!r} is not supported "
                           f"(this build_library reads schema "
                           f"{SIDECAR_SCHEMA})")

    defaults, sections = {}, []
    for key, val in data.items():
        if not isinstance(val, dict):
            raise SidecarError(
                f"{path}: top-level key {key!r} is not a table. The only "
                f"top-level scalar is `schema`; everything else must be "
                f"[defaults] or a [\"filename\"] section")
        if key == "defaults":
            if "name" in val:
                raise SidecarError(
                    f"{path}: 'name' is not allowed in [defaults] -- it would "
                    f"give every source the same footprint name")
            _check_keys("[defaults]", val, DEFAULTS_KEYS, path)
            defaults = _norm_settings("[defaults]", val, path)
            continue
        _check_keys(f'["{key}"]', val, SECTION_KEYS, path)
        exact = not _GLOB_META.search(key)
        if "name" in val and not exact:
            raise SidecarError(
                f'{path}: \'name\' is not allowed in the glob section '
                f'["{key}"] -- it would give every matching source the same '
                f'footprint name')
        sections.append(Section(key, exact, _norm_settings(f'["{key}"]', val, path)))
    return Sidecar(path, root, defaults, sections, enforce)


def resolve_settings(src: Path, sidecars: list[Sidecar]) -> tuple[dict, list[str]]:
    """Merge every sidecar that covers `src`, innermost directory last."""
    merged: dict = {}
    emit: list[str] = []
    used: list[str] = []
    for sc in sidecars:
        if sc.root is not None:
            try:
                src.resolve().relative_to(sc.root)
            except ValueError:
                continue
        base = src.name
        hits: list[Section] = []
        exact = [s for s in sc.sections if s.exact and s.pattern == base]
        globs = sorted((s for s in sc.sections
                        if not s.exact and fnmatch.fnmatch(base, s.pattern)),
                       key=lambda s: len(s.pattern))
        hits = globs + exact
        if sc.defaults or hits:
            used.append(str(sc.path))
        for layer in [sc.defaults] + [h.data for h in hits]:
            for k, v in layer.items():
                if k == "emit":
                    emit += v
                else:
                    merged[k] = v
        for h in hits:
            h.used = True
    if emit:
        merged["emit"] = emit
    return merged, used


# ---------------------------------------------------------------------------
# pieces
# ---------------------------------------------------------------------------

@dataclass
class Piece:
    source: Path
    size: float
    name: str
    min_area: str                     # "auto" | "none" | "<float>"
    emit_args: list[str]
    descr: str | None
    sidecars: list[str]
    mask: str = "black"
    tone_map: dict | None = None      # tone_map.ToneMap.to_dict() shape
    allow_inner: bool = False
    allow_provisional: bool = False

    @property
    def raster_width(self) -> int:
        """The raster width emit_art will actually use for this piece."""
        args = list(self.emit_args)
        for i, t in enumerate(args):
            if t == "--raster-width" and i + 1 < len(args):
                try:
                    return int(args[i + 1])
                except ValueError:
                    break
            if t.startswith("--raster-width="):
                try:
                    return int(t.split("=", 1)[1])
                except ValueError:
                    break
        return 1200

    @property
    def crop(self) -> bool:
        return "--no-crop" not in self.emit_args


@dataclass
class Result:
    piece: Piece
    state: str = FAILED
    inverted: bool = False
    bytes: int | None = None
    polys: int | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    t5_px: int = 0
    opaque_px: int = 0
    dropped_tones: list[dict] = field(default_factory=list)
    dropped_regions: int = 0
    dropped_mm2: float = 0.0
    ink_mm2: float = 0.0
    dropped_pct: float = 0.0
    verdict: str | None = None
    checks: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    # WARN/SKIP lines and their DETAIL. Separate from notes because notes are
    # dropped by --quiet and a verify warning must never be: the whole point
    # of this tool is maintenance without an agent reading the JSON.
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    foreign_overwritten: bool = False
    prev_bytes: int | None = None
    prev_mtime: str | None = None
    emit_warnings: list[str] = field(default_factory=list)
    staged: Path | None = None
    fidelity: dict | None = None

    @property
    def t5_pct(self) -> float:
        return 100.0 * self.t5_px / self.opaque_px if self.opaque_px else 0.0

    @property
    def accepted(self) -> bool:
        """Did the piece pass every guard and verify_art? The EXIT CODE keys
        off this, not off whether it reached the disk: --on-fail write installs
        a piece that failed, and a run that installed known-bad art must not
        report success."""
        return not self.problems

    @property
    def ok(self) -> bool:
        return self.state in (ADDED, UPDATED, UNCHANGED)

    @property
    def label(self) -> str:
        if self.problems:
            return "WRITTEN" if self.ok else FAILED
        return "INVERTED" if self.inverted else self.state


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

@dataclass
class EmitOut:
    rc: int
    stdout: str
    stderr: str
    report: dict | None
    cmd: list[str]


def run_emit(piece: Piece, out_file: Path, report_file: Path,
             extra: list[str], descr: str | None,
             timeout: int = 900) -> EmitOut:
    """emit_art, with --preview DELIBERATELY NEVER PASSED.

    The tool used to render a colour preview of every piece into the stage on
    every run, whether or not anything asked for one, and that render is what
    the library then discovered as its own next input. Nothing here writes an
    image any more.
    """
    cmd = [sys.executable, str(EMIT_ART),
           "--labels", str(piece.source),
           "--width-mm", f"{piece.size:g}",
           "--name", piece.name,
           "-o", str(out_file),
           "--report-json", str(report_file)]
    cmd += ["--palette-mask", piece.mask]
    if piece.tone_map is not None:
        # Serialised beside the staged footprint, in the stage this run owns.
        # The DIGEST of it goes into the footprint's tags, so a part and the
        # table it was assigned under can be checked against each other later
        # without either of them being trusted to describe the other.
        tm_file = report_file.with_name(report_file.name.replace(
            ".report.json", ".tonemap.json"))
        tm_file.write_text(json.dumps(piece.tone_map, indent=1),
                           encoding="utf-8")
        cmd += ["--tone-map", str(tm_file)]
        if piece.allow_inner:
            cmd += ["--allow-inner"]
        if piece.allow_provisional:
            cmd += ["--allow-provisional"]
    if piece.min_area == "auto":
        cmd += ["--min-area-mm2", "auto", "--allow-dropped-tones"]
    elif piece.min_area == "none":
        cmd += ["--min-area-mm2", "0"]
    else:
        cmd += ["--min-area-mm2", piece.min_area, "--allow-dropped-tones"]
    if descr:
        cmd += ["--descr", descr]
    cmd += list(piece.emit_args) + list(extra)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        rc, so, se = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return EmitOut(124, "", f"emit_art timed out after {timeout} s", None, cmd)
    rep = None
    if report_file.exists():
        try:
            rep = json.loads(report_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rep = None
    return EmitOut(rc, so, se, rep, cmd)


EMIT_EXIT_MEANING = {
    2: ("emit_art REFUSED the piece (exit 2): a tone was dropped without "
        "permission, a region operation was refused, microtext was refused, or "
        "--ink-tone was applied to something that is not monochrome line art"),
    3: ("emit_art refused this as EMPTY OUTPUT (exit 3): every inked pixel "
        "landed on a tone that draws nothing -- on a black-mask board T5 IS "
        "the board. The whole artwork would be lost"),
    4: ("emit_art refused this as COPPER IN WASTE (exit 4): copper landed on "
        "the scrap side of a T9 cut, which DRC cannot see"),
    124: "emit_art timed out",
}


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

@dataclass
class Found:
    files: list[Path] = field(default_factory=list)
    dirs: list[Path] = field(default_factory=list)
    skipped_subdirs: list[Path] = field(default_factory=list)
    ignored: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def discover(sources: list[str], recursive: bool,
             exclude: list[Path] | None = None) -> Found:
    """Walk the SOURCEs.

    `exclude` is the tool's OWN output: the library. It can legitimately sit
    inside the source folder, and a stray PNG in a .pretty is not artwork.

    THE SELF-INGESTION LOOP IS CLOSED AT THE SOURCE NOW. Run 1 produced
    alpha_20mm, run 2 discovered run 1's colour render and added
    alpha_20mm_20mm, run 3 added alpha_20mm_20mm_20mm -- three identical
    commands, exit 0 each time. That needed a marker file and a set of
    art-tree rules while the tool still wrote renders. It writes no image
    anywhere any more, so there is nothing of its own left to find.

    Nor is there a working directory left to step over. The stage is in the
    system temporary directory, which is not a place a SOURCE argument points,
    so the name-prefix rule that used to skip `.build_library_*` while walking
    -- and the rule for the files rglob had already yielded from inside one --
    are both gone with it. Excluding the library is the whole list.
    """
    ex = []
    for e in (exclude or []):
        try:
            ex.append(e.resolve())
        except OSError:                                # pragma: no cover
            continue
    f = Found()
    seen = set()

    def excluded(q: Path) -> bool:
        try:
            rq = q.resolve()
        except OSError:                                # pragma: no cover
            return False
        return any(rq == e or _under(rq, e) for e in ex)

    for s in sources:
        p = Path(s)
        if not p.exists():
            f.errors.append(f"{s}: no such file or directory")
            continue
        if p.is_file():
            if p.suffix.lower() not in IMAGE_EXT:
                f.errors.append(f"{p}: not an image build_library reads "
                                f"({', '.join(IMAGE_EXT)})")
                continue
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                f.files.append(p)
            continue
        if not p.is_dir():
            f.errors.append(f"{s}: neither a file nor a directory")
            continue
        f.dirs.append(p)
        walker = sorted(p.rglob("*")) if recursive else sorted(p.iterdir())
        for q in walker:
            if q.is_dir():
                if not recursive and not excluded(q):
                    f.skipped_subdirs.append(q)
                continue
            if excluded(q):
                continue
            if q.suffix.lower() not in IMAGE_EXT:
                # Named explicitly, a .tif is an error. Dropped in a folder it
                # used to be a bare `continue`: no footprint, no message, and
                # a support call. Report it instead.
                if q.name != SIDECAR_NAME and not q.name.startswith("."):
                    f.ignored.append(q)
                continue
            rp = q.resolve()
            if rp not in seen:
                seen.add(rp)
                f.files.append(q)
    f.files.sort(key=lambda q: (str(q).lower(), str(q)))
    return f


# ---------------------------------------------------------------------------
# summary helpers
# ---------------------------------------------------------------------------

def fmt_mtime(p: Path) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
    except OSError:
        return "?"


def worst_exit(results: list[Result]) -> int:
    """1 if ANY piece failed acceptance, including one installed by
    --on-fail write. A human running this unattended reads the exit code, so it
    reports the worst RESULT, not the worst disk outcome."""
    return 1 if any(r.problems for r in results) else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="build_library.py",
        description=(
            "Build and maintain a KiCad .pretty art library from image files.\n"
            "\n"
            "Point it at an image or a directory of images and an output\n"
            "library. Default behaviour is UPDATE AND APPEND: footprints this\n"
            "run produces are written, footprints already in the library that\n"
            "this run did not produce are left exactly alone -- not read, not\n"
            "rewritten, and never deleted. THIS TOOL HAS NO DELETE PATH: a\n"
            "full rebuild is `rm -r LIB.pretty` and a normal run.\n"
            "\n"
            "Every piece is emitted to a temporary file in the system\n"
            "temporary directory, verified with tools/verify_art.py, and\n"
            "only then installed with one atomic os.replace. The incumbent\n"
            "is never moved, so an interrupt leaves every footprint either\n"
            "old or new and never missing. A piece whose verdict is FAIL is\n"
            "not installed, and a failed update leaves the previous good\n"
            "footprint in place. A piece\n"
            "whose verdict is WARN IS installed -- every real piece in this\n"
            "corpus warns about something -- so every WARN and all of its\n"
            "detail is printed here, counted in the footer and named again\n"
            "at the end. --strict turns a WARN into a failure.\n"
            "\n"
            "Only footprints this tool produced are ever overwritten. One\n"
            "it did not make (no entry in the journal, no emit_art stamp in\n"
            "the descr) is FOREIGN: a name collision with it stops the run\n"
            "before anything is built.\n"
            "\n"
            "-o is refused inside a git working tree that does not ignore it\n"
            "-- that is where derived artwork lands -- unless you pass\n"
            "--allow-tracked-library and mean it."),
        epilog=(
            "exit codes:\n"
            "  0  every piece succeeded (or was unchanged)\n"
            "  1  one or more pieces failed\n"
            "  2  usage, sidecar or environment error -- nothing was built\n"
            "  3  no sources matched\n"
            "\n"
            "--help-options prints the sidecar schema.\n"),
        formatter_class=argparse.RawDescriptionHelpFormatter)

    ap.add_argument("sources", nargs="+", metavar="SOURCE",
                    help="image file, or directory of images "
                         "(png/jpg/jpeg/svg). Repeatable. Sources are read "
                         "only: nothing is ever copied, moved or written into "
                         "a source directory")
    ap.add_argument("-o", "--output", required=True, metavar="LIB.pretty",
                    help="output footprint library directory. Created if "
                         "absent. Refused inside a git working tree that does "
                         "not ignore it, because this is where derived "
                         "artwork lands and third-party art must not reach a "
                         "public tree -- see --allow-tracked-library")
    ap.add_argument("--size", type=float, action="append", metavar="MM",
                    help="finished LONG-EDGE size in mm. Repeat for several "
                         "sizes of the same piece: --size 12 --size 20. "
                         f"Default {DEFAULT_SIZE_MM:g}")
    ap.add_argument("--recursive", action="store_true",
                    help="walk sub-directories of a SOURCE directory. Off by "
                         "default: recursion multiplies name collisions across "
                         "folders, and a flat drop-folder is the normal shape. "
                         "Sub-directories skipped this way are counted and "
                         "named in the summary, never passed over in silence")

    g = ap.add_argument_group(
        "per-piece options",
        "Art is not uniform: across the 11 entries of tools/render_library.py "
        "4 need a footprint name that is not their filename, 2 need --ink-tone "
        "T1, the sizes span 10 to 90 mm, and min-area takes four different "
        "values. One flag set for a whole directory cannot say that, so "
        "per-piece settings live in a sidecar file beside the art. "
        "--help-options prints its schema.")
    m = g.add_mutually_exclusive_group()
    m.add_argument("--options", metavar="FILE",
                   help=f"sidecar of per-source settings (TOML). Default: "
                        f"{SIDECAR_NAME} in each SOURCE directory, if present. "
                        f"Keys are source FILENAMES; see --help-options")
    m.add_argument("--no-options", action="store_true",
                   help="ignore any sidecar and use only the flags given here")
    g.add_argument("--emit-arg", action="append", default=[], metavar="ARG",
                   help="extra argument passed to emit_art.py for EVERY piece. "
                        "Repeatable; use --emit-arg=--foo=bar for values. "
                        "Per-piece 'emit' in the sidecar appends after these")

    c = ap.add_argument_group("conversion defaults")
    c.add_argument("--min-area", default=None, metavar="SPEC",
                   help="'auto' (default), 'none', or a number in mm2, passed "
                        "to emit_art --min-area-mm2. auto drops regions below "
                        "each tone's own minimum fabricable feature squared. "
                        "MEASURED: on reckless_color at 20 mm this is 460 "
                        "polys / 108,504 B / verify WARN -> 13 polys / 4,356 B "
                        "/ verify PASS, because 447 of 460 regions were "
                        "antialias specks; on the clean vector "
                        "examples/bitcoin_b.svg it changes nothing at all "
                        "(byte-identical). auto implies emit_art "
                        "--allow-dropped-tones, and every dropped tone is "
                        "listed in the summary")
    c.add_argument("--max-dropped-pct", type=float,
                   default=DEFAULT_MAX_DROPPED_PCT, metavar="PCT",
                   help=f"fail a piece if --min-area drops more than PCT of "
                        f"its total inked area (default "
                        f"{DEFAULT_MAX_DROPPED_PCT:g}). This is the guard that "
                        f"makes auto safe to leave on: MEASURED, speck removal "
                        f"costs 0.000-0.44%% of ink across this corpus, while "
                        f"bitcoin_emission_formula.svg loses 3.6%% at 12 mm "
                        f"and 13.9%% at 8 mm -- real strokes, not noise. Raise "
                        f"the size or set min_area for that piece instead of "
                        f"raising this")
    c.add_argument("--no-ink-fallback", action="store_true",
                   help="do not retry a piece with --ink-tone T1 when emit_art "
                        "refuses it as EMPTY OUTPUT. The retry is on by "
                        "default and is safe by construction: emit_art itself "
                        "refuses --ink-tone on anything that is not "
                        "monochrome-on-background (verified: exit 2, nothing "
                        "written). It is always reported as INVERTED and "
                        "recorded in the footprint's descr")
    c.add_argument("--palette-mask", default=None, metavar="COLOUR",
                   help="mask colour every piece in this run is assigned "
                        "against, overriding 'mask' in the sidecar. black "
                        "(default), purple, green, white. The colourway is "
                        "written into each footprint's tags, so verify_art "
                        "checks the part against the same one it was built for")
    c.add_argument("--propose-tones", action="store_true",
                   help="DO NOT BUILD. For each source, census its colours "
                        "against the target palette and print a paste-ready "
                        "[section] with a 'tones' table, the share of ink each "
                        "colour carries, its L*, and how far the tone it would "
                        "land on sits from the board. EXITS 3 if any cluster's "
                        "nearest tone is T5 -- which draws nothing, so that "
                        "colour would be erased -- if two colours 10 dE apart "
                        "would share a tone, or if any binding lands under the "
                        "20 L* worth-doing line. Writes no image and no "
                        "footprint")

    n = ap.add_argument_group("naming")
    n.add_argument("--prefix", default="", metavar="STR",
                   help="prepend STR to every footprint name this run produces")
    n.add_argument("--allow-unicode-names", action="store_true",
                   help="permit non-ASCII in footprint names. KiCad 10 accepts "
                        "them (verified: 'cafe' with an acute and CJK both "
                        "load and plot), but the name is a bare string inside "
                        "every .kicad_pcb that places it, so the default is to "
                        "refuse rather than to transliterate")

    lm = ap.add_argument_group("library maintenance")
    lm.add_argument("--allow-tracked-library", action="store_true",
                    help="permit an output library -- and this run's journal "
                         "-- inside a git working tree that does not ignore "
                         "them. Refused by default: the library is where "
                         "derived artwork lands, this corpus includes "
                         "third-party and brand art, and a working tree gets "
                         "pushed. The legitimate case is real and is why this "
                         "flag exists -- SatoshiStarter tracks "
                         "RecklessArt.pretty on purpose, in a private repo")
    lm.add_argument("--overwrite-foreign", action="store_true",
                    help="permit this run to OVERWRITE footprints this tool "
                         "did not produce. Off by default: the library does "
                         "hold art_hex_asic_window and art_btc_whitepaper_b, "
                         "which come from texture_board.py and microtext.py, "
                         "are irreplaceable by this tool, and have exactly "
                         "the kind of name an image could collide with")
    lm.add_argument("--dry-run", action="store_true",
                    help="do everything -- emit, guard, verify, compare -- but "
                         "install nothing. Reports the exact "
                         "added/updated/unchanged/failed/untouched state the "
                         "real run would produce. It is not faster than a real "
                         "run: the only honest way to know a footprint is "
                         "unchanged is to build it and compare the bytes")

    f = ap.add_argument_group("failure policy")
    f.add_argument("--on-fail", choices=("skip", "abort", "write"),
                   default="skip",
                   help="skip (default): a failing piece is not installed, the "
                        "rest of the run continues, and any previous good "
                        "version of that footprint stays in the library. "
                        "abort: stop at the first failure and install nothing "
                        "at all, leaving the library byte-identical to how it "
                        "started. write: install it anyway and stamp the "
                        "failure into the footprint's descr so it cannot be "
                        "shipped unknowingly (only possible when emit_art "
                        "itself produced a file)")
    f.add_argument("--no-verify", action="store_true",
                   help="do not run tools/verify_art.py. Without this flag the "
                        "run REFUSES TO START if kicad-cli is missing or older "
                        f"than major {MIN_KICAD_MAJOR}, because unattended "
                        "maintenance whose acceptance harness is not running "
                        "is the exact situation that produced 21 layers of "
                        "vacuous PASS")
    f.add_argument("--strict", action="store_true",
                   help="treat verify WARN and SKIP as failures (verify_art "
                        "--strict)")
    f.add_argument("--fab", default=None, metavar="PROFILE",
                   choices=sorted(fab_profiles.PROFILES),
                   help="verify against a named process from "
                        "tools/fab_profiles.py instead of the palette doc: "
                        + ", ".join(sorted(fab_profiles.PROFILES)))
    f.add_argument("--kicad-cli", default=None, metavar="PATH",
                   help="path to kicad-cli. Probed for --version; a cli below "
                        f"major {MIN_KICAD_MAJOR} is refused, not silently used")

    o = ap.add_argument_group("output")
    o.add_argument("--journal", default=None, metavar="FILE",
                   help="write the full machine-readable run record here "
                        "(JSON). Default: <output>.build.json, BESIDE the "
                        "library, not inside it -- kicad-cli fp upgrade -o "
                        "copies only .kicad_mod files, so anything kept inside "
                        "a .pretty is silently lost the first time somebody "
                        "upgrades it. Being a sibling of the library does not "
                        "make it covered by the library's .gitignore rule, so "
                        "this path is checked against the working tree in its "
                        "own right -- see --allow-tracked-library")
    o.add_argument("--json", dest="as_json", action="store_true",
                   help="print the run record to stdout instead of the table")
    o.add_argument("--jobs", type=int, default=None, metavar="N",
                   help="emit N pieces in parallel (default: cpu_count/2, "
                        "capped at 4). Verification is serialised: it shells "
                        "out to kicad-cli per file")
    o.add_argument("--quiet", action="store_true",
                   help="one line per piece, plus the summary")
    o.add_argument("--help-options", action="store_true",
                   help="print the sidecar schema and exit")
    return ap


def default_jobs() -> int:
    return max(1, min(4, (os.cpu_count() or 2) // 2))


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

class Usage(Exception):
    """Exit 2: usage, sidecar or environment. Nothing was built."""


PROPOSE_MIN_SHARE_PCT = 0.1


def _propose_tones(a, sources: list[Path], mask: str) -> int:
    """Census each source against the target palette; print a paste-ready table.

    WRITES NOTHING. Not the sidecar, not an image, not a footprint -- the tool
    writes no images at all and this is not the place to start.

    EXITS 3 on any of three findings, because each of them means the table it
    just printed would lose part of the picture if pasted unedited, and a
    proposal that exits 0 while containing a hole is the same defect as a check
    that cannot fail.
    """
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(TOOLS))
    import prep_assets
    from emit_art import crop_to_content, rasterise_svg

    pal = palette.palette_for(mask, allow_provisional=True)
    front = [t for t in pal.drawable(allow_inner=False, allow_provisional=True)]
    legible = [t for t in front
               if abs(pal.dl_to_board(t)) >= palette.LEGIBLE_MIN_DL]
    w = sys.stdout.write
    w(f"# --propose-tones against {pal.tag()}\n")
    w(f"# board (T5) L* {pal.lstar('T5'):.2f}.  front-side tones, dL from board:\n")
    for t in front:
        w(f"#   {t} {pal[t].name:<18} L* {pal.lstar(t):6.2f}  "
          f"dL {pal.dl_to_board(t):+6.2f}"
          f"{'  PROVISIONAL' if pal[t].provenance == 'PROVISIONAL' else ''}"
          f"{'' if t in legible else '   <- UNDER the ' + format(palette.LEGIBLE_MIN_DL, 'g') + ' L* legibility line'}\n")
    w("\n")

    findings = 0
    for src in sources:
        if src.suffix.lower() == ".svg":
            img, _tool = rasterise_svg(src, 1200)
        else:
            img = Image.open(src).convert("RGBA")
        img, _box = crop_to_content(img)
        arr = np.asarray(img.convert("RGBA"))
        rgb, ink = arr[..., :3], arr[..., 3] >= 128
        cen = prep_assets.colour_census(rgb, ink, tone_map.DEFAULT_TOL_DE)
        w(f'["{src.name}"]\n')
        w(f"# soft-edge pixels {cen['soft_pixel_fraction']:.3f} of ink; "
          f"{int(ink.sum()):,} opaque px\n")
        w("tones = [\n")
        seen_tone: dict[str, list] = {}
        for c in cen["clusters"]:
            share = 100.0 * c["area_fraction"]
            if share < PROPOSE_MIN_SHARE_PCT:
                continue
            crgb = tuple(int(v) for v in c["rgb"])
            d = {t: float(np.linalg.norm(
                tone_map._weighted(np.array(pal[t].rgb, dtype=np.uint8))
                - tone_map._weighted(np.array(crgb, dtype=np.uint8))))
                for t in palette.TONE_IDS}
            near_any = min(d, key=d.get)
            pick = min(legible, key=d.get) if legible else near_any
            extra = []
            if not pal[near_any].emits:
                findings += 1
                w(f"  # !! {c['hex']} is NEAREST {near_any}, WHICH DRAWS "
                  f"NOTHING -- {near_any} IS THE BOARD. Under nearest-anchor "
                  f"assignment this\n"
                  f"  #    colour is erased outright ({share:.2f}% of the ink, "
                  f"L* {pal.lstar_of_rgb(crgb):.1f}, {abs(pal.lstar_of_rgb(crgb) - pal.lstar('T5')):.1f} L* "
                  f"from the board).\n"
                  f"  #    Every tone this process can make is lighter than "
                  f"this ink. Choose a substitute and say so.\n")
            if d[pick] >= tone_map.OFF_PALETTE_DE:
                extra.append("off_palette = true")
            if abs(pal.dl_to_board(pick)) < palette.LEGIBLE_WARN_DL:
                findings += 1
                w(f"  # !! {c['hex']} -> {pick} is only "
                  f"{abs(pal.dl_to_board(pick)):.1f} L* from the board, under "
                  f"the {palette.LEGIBLE_WARN_DL:g} L* worth-doing line "
                  f"(emit_art.HALFTONE_MIN_DELTA_L).\n")
                if abs(pal.dl_to_board(pick)) < palette.LEGIBLE_MIN_DL:
                    extra.append('legibility = "declared"')
            prev = seen_tone.setdefault(pick, [])
            merge = ""
            if prev:
                sep = min(float(np.linalg.norm(
                    tone_map._weighted(np.array(crgb, dtype=np.uint8))
                    - tone_map._weighted(np.array(
                        tone_map._hex_to_rgb(p), dtype=np.uint8))))
                    for p in prev)
                if sep >= tone_map.DEFAULT_TOL_DE:
                    findings += 1
                    w(f"  # !! {c['hex']} and {prev[0]} are {sep:.1f} units "
                      f"apart and would BOTH be {pick}. One finish means "
                      f"exactly one metal\n"
                      f"  #    tone (docs/pcb-palette.md line 145), so this may "
                      f"be right -- but the board loses a distinction the art "
                      f"has.\n")
                merge = ", merge_ok = [" + ", ".join(
                    f'"{p}"' for p in prev) + "]"
            prev.append(c["hex"])
            tail = (", " + ", ".join(extra)) if extra else ""
            w(f'  {{ rgb = "{c["hex"]}", tone = "{pick}"{merge}{tail} }},'
              f'   # {share:.2f}% of ink, L* {pal.lstar_of_rgb(crgb):.1f}, '
              f'{d[pick]:.0f} units from {pick}\n')
        w("]\n\n")
    if findings:
        w(f"# {findings} finding(s) above. Exit 3: this table would lose part "
          f"of the picture if pasted unedited.\n")
    return 3 if findings else 0


def _resolve_tone_map(src: Path, settings: dict, mask: str
                      ) -> tuple[dict | None, bool, bool]:
    """-> (serialisable tone map or None, allow_inner, allow_provisional).

    A source with no 'tones' table gets None and emit_art falls back to
    nearest-anchor assignment, which is what every piece built before this
    change used. That fallback is only correct for art drawn in the colours the
    board can make; --propose-tones exists to find out whether it is.
    """
    rows = settings.get("tones")
    if not rows:
        return None, False, False
    inner_ok = bool(settings.get("inner_ok", False))
    pal = palette.palette_for(mask, allow_provisional=True)
    need_inner = sorted({r["tone"] for r in rows if pal[r["tone"]].inner})
    if need_inner and not inner_ok:
        raise Usage(
            f"{src.name}: tones bind ink to {', '.join(need_inner)}, whose "
            f"recipe reaches In1.Cu. The piece stops being renderable on a "
            f"2-layer board and costs a layer to show a colour. Set "
            f"inner_ok = true for this source if that is the intent.")
    need_prov = sorted({r["tone"] for r in rows
                        if pal[r["tone"]].provenance == "PROVISIONAL"})
    d = {
        "mask": mask,
        "tol_de": float(settings.get("tol_de", tone_map.DEFAULT_TOL_DE)),
        "unmapped_budget_pct": float(settings.get(
            "unmapped_budget_pct", tone_map.DEFAULT_UNMAPPED_BUDGET_PCT)),
        "inner_ok": inner_ok,
        "source": src.name,
        "tones": rows,
    }
    # Round-trip it now so a malformed table is a parse error here rather than
    # a subprocess failure per size.
    tone_map.ToneMap.from_dict(d)
    return d, inner_ok, bool(need_prov)


def _plan(a, out: dict, exclude: list[Path]
          ) -> tuple[list[Piece], list[Sidecar], list[str], Found]:
    found = discover(a.sources, a.recursive, exclude)
    files, dirs = found.files, found.dirs
    out["skipped_subdirs"] = [str(p) for p in found.skipped_subdirs]
    out["ignored_files"] = [str(p) for p in found.ignored]
    if found.errors:
        raise Usage("\n".join(found.errors))
    if not files:
        return [], [], [], found

    # ---- sidecars ---------------------------------------------------------
    sidecars: list[Sidecar] = []
    if not a.no_options:
        if a.options:
            p = Path(a.options)
            if not p.is_file():
                raise Usage(f"--options {a.options}: no such file")
            sidecars.append(load_sidecar(p, None, enforce=bool(dirs)))
        else:
            seen = set()
            for d in dirs:
                sc = d / SIDECAR_NAME
                rp = sc.resolve()
                if sc.is_file() and rp not in seen:
                    seen.add(rp)
                    sidecars.append(load_sidecar(sc, d.resolve(), enforce=True))
            for fpath in files:
                sc = fpath.parent / SIDECAR_NAME
                rp = sc.resolve()
                if sc.is_file() and rp not in seen:
                    seen.add(rp)
                    sidecars.append(load_sidecar(sc, fpath.resolve().parent,
                                                 enforce=False))
    # Innermost directory last, so a nested sidecar overrides an outer one; an
    # explicit --options (root None) is the outermost layer of all.
    sidecars.sort(key=lambda s: -1 if s.root is None else len(str(s.root)))

    # ---- pieces -----------------------------------------------------------
    pieces: list[Piece] = []
    notes: list[str] = []
    for src in files:
        settings, used = resolve_settings(src, sidecars)
        if settings.get("skip"):
            notes.append(f"{src.name}: skip = true in the sidecar -- excluded")
            for sc in sidecars:
                for s in sc.sections:
                    if s.exact and s.pattern == src.name:
                        s.used = True
            continue
        sizes = [float(x) for x in a.size] if a.size else \
            settings.get("sizes", [DEFAULT_SIZE_MM])
        min_area = a.min_area if a.min_area is not None else \
            settings.get("min_area", "auto")
        emit = list(a.emit_arg) + list(settings.get("emit", []))
        base = settings.get("name") or src.stem
        mask = (a.palette_mask or settings.get("mask") or "black").lower()
        tmap, inner, prov = _resolve_tone_map(src, settings, mask)
        try:
            nm = slug(a.prefix + base, a.allow_unicode_names)
            for size in sizes:
                full = f"{nm}_{size_suffix(size)}"
                check_reserved(full)
                pieces.append(Piece(src, float(size), full, min_area, emit,
                                    settings.get("descr"), used,
                                    mask=mask, tone_map=tmap,
                                    allow_inner=inner, allow_provisional=prov))
        except NameError_ as e:
            raise Usage(f"{src}: {e}") from None

    # ---- unmatched sidecar sections --------------------------------------
    for sc in sidecars:
        dead = [s.pattern for s in sc.sections if not s.used]
        if not dead:
            continue
        msg = (f"{sc.path}: section(s) matching no source: "
               + ", ".join(f'["{d}"]' for d in dead))
        if sc.enforce_unmatched:
            raise Usage(
                msg + ".\nThat means art was renamed or moved, and the flags "
                      "that art needed are now not being applied to anything. "
                      "Fix the section, delete it, or narrow the run.")
        notes.append(msg + " (run was narrowed to individual files, so this is "
                           "a note, not an error)")
    return pieces, sidecars, notes, found


def _case_note(lib: Path) -> str:
    """Say what this filesystem actually does, or say nothing."""
    verdict = case_insensitive_fs(lib)
    if verdict is True:
        return (" (the filesystem here is case-insensitive and would keep "
                "only one of them, without an error)")
    if verdict is False:
        return (" (the filesystem here is case-sensitive, so both would exist "
                "side by side -- but they are one name to every "
                "case-insensitive filesystem this library is also opened on, "
                "and to KiCad's own library lookup on Windows)")
    return " (this filesystem's case behaviour could not be probed)"


def _validate_names(pieces: list[Piece], lib: Path, a) -> None:
    lib_host = host_path(lib)
    budget_applies = is_windows_host(lib_host)
    reg: dict[str, Piece] = {}
    for p in pieces:
        key = p.name.casefold()
        if key in reg:
            other = reg[key]
            raise Usage(
                f"COLLISION: {other.source} and {p.source} both resolve to the "
                f"footprint name {p.name!r}"
                + (_case_note(lib) if other.name != p.name else "")
                + ".\nNeither was written. This is not auto-suffixed: an "
                  "auto-suffix makes a footprint's identity a function of "
                  "directory-walk order, so the same two files could swap "
                  "names on the next run and every board that placed them "
                  "would silently get the other picture.\nFix it one of three "
                  "ways: rename a source, use --prefix, or set `name = ...` "
                  "for one of them in the sidecar.")
        reg[key] = p
        if budget_applies:
            total = len(lib_host) + 1 + len(p.name) + len(".kicad_mod")
            if total > MAX_PATH:
                raise Usage(
                    f"PATH TOO LONG: {lib_host}\\{p.name}.kicad_mod is "
                    f"{total} characters; the Win32 limit is {MAX_PATH} and "
                    f"KiCad reports 'Unable to load library' past it "
                    f"(measured). Remove {total - MAX_PATH} character(s) from "
                    f"the name, or put the library in a shorter path. The name "
                    f"is never truncated: truncation invents collisions.")
    if lib.is_dir():
        for f in sorted(lib.glob("*.kicad_mod")):
            key = f.stem.casefold()
            p = reg.get(key)
            if p is not None and f.stem != p.name:
                raise Usage(
                    f"COLLISION with the existing library: this run produces "
                    f"{p.name!r} (from {p.source}) but {f} is already there. "
                    f"They differ only in case, so on this filesystem one "
                    f"would silently overwrite the other, while on a "
                    f"case-sensitive filesystem they are two different "
                    f"footprints. Rename one of them deliberately.")


def _make_cfg(a) -> tuple[object, verify_art.CliChoice]:
    if a.no_verify and not a.kicad_cli:
        # Do not go hunting for a cli we have been told not to use: the search
        # shells out to every candidate on the machine for its version.
        choice = verify_art.CliChoice(None, "not probed (--no-verify)", -1)
    else:
        choice = verify_art.find_kicad_cli(a.kicad_cli)
    if not a.no_verify:
        if not choice.path:
            raise Usage(
                "no kicad-cli found, and verification is not optional by "
                "accident.\nUnattended library maintenance whose acceptance "
                "harness is silently skipping is the exact situation that "
                "produced 21 layers of vacuous PASS.\nPass --kicad-cli "
                "/path/to/kicad-cli, or --no-verify if you have decided to "
                "build unverified art.")
        if choice.major < MIN_KICAD_MAJOR:
            raise Usage(
                f"kicad-cli at {choice.path} reports version "
                f"{choice.version}; build_library needs major "
                f"{MIN_KICAD_MAJOR}+.\nKiCad {choice.major} cannot parse a "
                f"modern (version 20241229) footprint, so the load check would "
                f"SKIP and every piece would be installed unverified.\nPass a "
                f"newer --kicad-cli, or --no-verify if you have decided to "
                f"build unverified art.")

    doc = REPO / "docs" / "pcb-palette.md"
    palette = verify_art.load_palette(doc if doc.is_file() else None, "front")

    class Cfg:
        pass
    cfg = Cfg()
    cfg.cli, cfg.kicad_version, cfg.cli_major = \
        choice.path, choice.version, choice.major
    cfg.palette, cfg.side = palette, "front"
    cfg.fab = a.fab
    cfg.allow_layers = set()
    cfg.strict = a.strict
    cfg.render = True
    cfg.clearance = True
    cfg.warn_bytes, cfg.fail_bytes = verify_art.WARN_BYTES, verify_art.FAIL_BYTES
    cfg.outlier_mm = verify_art.OUTLIER_MM
    cfg.max_poly_pts = 2000
    cfg.max_clearance_items = 100_000
    cfg.clearance_budget = 4_000_000
    cfg.max_report = 8
    cfg.render_svg = None
    return cfg, choice


def _analyse(rep: dict, res: Result, max_dropped_pct: float) -> None:
    tones = rep.get("tones", [])
    res.bytes = rep.get("bytes")
    res.polys = rep.get("total_polys")
    res.width_mm, res.height_mm = rep.get("width_mm"), rep.get("height_mm")
    res.emit_warnings = list(rep.get("warnings", []))

    # emit_art's own definition of "inked": every OPAQUE pixel, background tone
    # included (emit_art.py:3963). T5 counts because T5 is part of the picture
    # -- it is the board showing through.
    mm2_px = float(rep.get("mm_per_px", 0.0)) ** 2
    res.opaque_px = sum(int(t.get("px", 0)) for t in tones)
    res.ink_mm2 = res.opaque_px * mm2_px
    res.t5_px = sum(int(t.get("px", 0)) for t in tones if t.get("tone") == "T5")

    fully = set(rep.get("dropped") or [])
    for t in tones:
        n = int(t.get("area_dropped") or 0)
        mm2 = float(t.get("area_dropped_mm2") or 0.0)
        if n or mm2 or t.get("tone") in fully:
            res.dropped_regions += n
            res.dropped_mm2 += mm2
            # 'px' is emit_art's census of the whole TONE, not of what was
            # dropped -- the old summary line printed it right next to the
            # dropped region count as though the two agreed. Carry the tone's
            # area alongside it so the printed line can say which is which.
            res.dropped_tones.append({
                "tone": t.get("tone"), "px": int(t.get("px", 0)),
                "tone_total_px": int(t.get("px", 0)),
                "tone_total_mm2": round(int(t.get("px", 0)) * mm2_px, 6),
                "regions_dropped": n, "mm2": round(mm2, 6),
                "tone_lost_entirely": t.get("tone") in fully})
    res.dropped_pct = (100.0 * res.dropped_mm2 / res.ink_mm2) if res.ink_mm2 else 0.0


def _guard(res: Result, a) -> None:
    """Post-emit guards. Appends to res.problems; empty means the piece passed."""
    if not res.polys:
        res.problems.append(
            "BLANK FOOTPRINT: emit produced 0 polygons. build_library refuses "
            "to install art with no geometry -- a silently blank footprint is "
            "the worst failure mode here")
    if res.dropped_pct > a.max_dropped_pct:
        res.problems.append(
            f"SPECK-REMOVAL BUDGET (emitter-reported): --min-area removed "
            f"{res.dropped_pct:.3f}% of the inked area ({res.dropped_mm2:.6f} "
            f"of {res.ink_mm2:.4f} mm2, {res.dropped_regions} region(s)), over "
            f"the {a.max_dropped_pct:g}% budget. THIS READS `area_dropped` OUT "
            f"OF THE EMITTER'S OWN REPORT and is therefore not a fidelity "
            f"measurement -- it says what the emitter believes it discarded, "
            f"not what is missing from the picture; tools/fidelity.py measures "
            f"that independently and is checked separately. Across this corpus "
            f"speck removal costs 0.000-0.44%; a loss this size is real "
            f"artwork. Raise --size for this piece, or set min_area for it in "
            f"the sidecar -- do not raise --max-dropped-pct")
    # A FULLY dropped tone, judged by AREA rather than by the fact of it. The
    # old guard failed on the fact alone, which refused mfb_lockup_3tone over
    # "T3 (181 px) -> 0 polygons" -- 0.03% of the ink, i.e. antialias residue.
    # A tone that WAS a region of the design is a different event from a tone
    # that was a rounding error, and one number tells them apart.
    for t in res.dropped_tones:
        if not t.get("tone_lost_entirely"):
            continue
        share = (100.0 * t["tone_total_px"] / res.opaque_px) if res.opaque_px else 0.0
        t["share_pct"] = round(share, 4)
        if share >= DROPPED_TONE_FAIL_PCT:
            res.problems.append(
                f"TONE LOST ENTIRELY: {t['tone']} carried {t['tone_total_px']:,} "
                f"px ({share:.3f}% of the ink) and emitted 0 polygons, over the "
                f"{DROPPED_TONE_FAIL_PCT:g}% line. That is a region of the "
                f"design, not a speck")
        elif share > 0:
            res.warnings.append(
                f"tone lost entirely: {t['tone']} ({t['tone_total_px']:,} px, "
                f"{share:.3f}% of the ink) emitted 0 polygons -- under the "
                f"{DROPPED_TONE_FAIL_PCT:g}% line, so it is speck removal "
                f"rather than lost artwork")
    # T5 is REPORTED, never guessed at. Measured: reckless_color legitimately
    # puts 63.7% of its opaque pixels on T5 (the black field of the logo, and
    # it verifies PASS), mfb_node_full sits at 11.9%, satoshi_miner at 19.2%.
    # Any threshold that fires on a real trap also fires on correct art.
    if res.t5_px:
        flags = " ".join(res.piece.emit_args)
        if "--silhouette-tone" not in flags and "--ink-tone" not in flags \
                and not res.inverted:
            res.notes.append(
                f"T5 {res.t5_px:,} px ({res.t5_pct:.1f}% of opaque) draws "
                f"NOTHING -- T5 IS the board. If any of that is subject "
                f"rather than background it has silently vanished; render it "
                f"with `emit_art.py --preview` and look, then reach for "
                f"--silhouette-tone or --ink-tone")


def _fidelity(res: Result, staged: Path, rep: dict) -> None:
    """The acceptance metric: does the picture survive?

    This is the only check in the tool that does not read the emitter's opinion
    of its own output. It rasterises the staged footprint from its OWN polygons
    and overlays it, pixel-aligned, on the source file. verify_art passing is
    not fidelity: every one of the four mutilated pieces in the shipped library
    verified PASS or WARN while missing its limbs.
    """
    p = res.piece
    try:
        u = fidelity.undrawn_ink(p.source, staged, rep,
                                 raster_width=p.raster_width, crop=p.crop)
    except Exception as e:                                  # noqa: BLE001
        res.problems.append(
            f"FIDELITY NOT MEASURED: {type(e).__name__}: {e}. A piece whose "
            f"acceptance metric could not be computed is not a piece that "
            f"passed it")
        return
    res.fidelity = u
    line = (f"undrawn source ink {u['undrawn_pct']:.3f}% "
            f"({u['undrawn_px']:,} of {u['opaque_px']:,} opaque px), "
            f"overdrawn {u['overdrawn_pct_of_ink']:.3f}% of ink")
    if u["verdict"] == "FAIL":
        res.problems.append(
            f"FIDELITY: {line} -- at or over the "
            f"{u['fail_at_pct']:g}% line. MEASURED BAND: every good footprint "
            f"in this corpus lands in 0.185-2.310% and every mutilated one in "
            f"11.964-29.551%; nothing has ever landed between. Ink this far "
            f"undrawn is a part of the picture that is not on the board")
    elif u["verdict"] == "WARN":
        res.warnings.append(f"FIDELITY WARN: {line} (warn line "
                            f"{u['warn_at_pct']:g}%)")
    else:
        res.notes.append(f"fidelity: {line}")
    if u["inner_layers"]:
        res.warnings.append(
            f"NOT 2-LAYER RENDERABLE: geometry on {', '.join(u['inner_layers'])}. "
            f"Only T4 and T7 need an inner layer, and both are opt-in")


NOT_VERIFIED = "NOT VERIFIED"


def _verify(res: Result, path: Path, cfg, no_verify: bool) -> None:
    if no_verify:
        res.verdict = NOT_VERIFIED
        res.warnings.append("NOT VERIFIED: --no-verify was given, so nothing "
                            "confirmed this footprint loads or is fabricable")
        return
    verdict, checks = verify_art.verify_file(path, cfg)
    res.verdict = verdict
    res.checks = [{"key": c.key, "level": c.level, "headline": c.headline,
                   "details": list(c.details)} for c in checks]
    # --strict is enforced HERE as well as inside verify_art. verify_art
    # promotes WARN/SKIP to FAIL when it computes the verdict
    # (verify_art.py:2698), but a promise this tool makes in its own --help is
    # a promise it should keep itself rather than inherit.
    strict = bool(getattr(cfg, "strict", False))
    for c in checks:
        if c.level == verify_art.FAIL or (
                strict and c.level in (verify_art.WARN, verify_art.SKIP)):
            promoted = ("" if c.level == verify_art.FAIL
                        else f" ({c.level} refused by --strict)")
            res.problems.append(f"verify {c.key}: {c.headline}{promoted}")
            res.problems += [f"  {d}" for d in c.details]
        elif c.level in (verify_art.WARN, verify_art.SKIP):
            # The DETAIL, not just the headline. "[WARN] clearance: 1
            # clearance problem(s)" on stdout while "GAP BELOW FLOOR: F.Cu
            # narrowest gap 0.016434 mm < 0.1000 mm" sat in the journal is how
            # every satoshi piece shipped without anyone reading the number.
            res.warnings.append(f"[{c.level}] {c.key}: {c.headline}")
            res.warnings += [f"  {d}" for d in c.details]
    if verdict == verify_art.FAIL and not any(
            p.startswith("verify ") for p in res.problems):
        res.problems.append("verify FAIL")


# ---------------------------------------------------------------------------
# containment, provenance and the install
# ---------------------------------------------------------------------------

def _nearest_existing(p: Path) -> Path:
    """The closest ancestor of `p` that exists. `git` has to be run somewhere."""
    q = p
    while not q.is_dir():
        if q.parent == q:
            return q
        q = q.parent
    return q


def _git_toplevel(p: Path) -> Path | None:
    """The root of the git working tree `p` lives in, or None.

    rev-parse, not a scan for a .git directory: a submodule and a linked
    worktree both carry a .git FILE, and both are still working trees whose
    contents get committed and pushed.
    """
    if not shutil.which("git"):
        return None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=_nearest_existing(p), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):       # pragma: no cover
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return Path(r.stdout.strip()).resolve()
    except OSError:                                     # pragma: no cover
        return None


# `<source>:<linenum>:<pattern>` -- the head of a `check-ignore -v` line, up to
# the tab before the pathname. `src` is greedy so a source filename containing
# a colon still parses: the line number anchors the split.
_IGNORE_RULE = re.compile(r"^(?P<src>.*):(?P<line>\d+):(?P<pat>.*)$")


def _ignore_rule(top: Path, rel: str) -> str | None:
    """The .gitignore PATTERN that ignores `rel`, or None. One invocation.

    -v, and the pattern field is READ, not just the exit code. `check-ignore
    -q` answers with an exit status alone, and an exit status alone cannot
    distinguish "a rule you wrote matches this" from any other route to 0 --
    which is how a rule that was not there was 'verified' three rounds
    running. A match is only believed here when git names a NON-EMPTY pattern
    for it, so the evidence is the rule itself and not the absence of an
    error.
    """
    try:
        r = subprocess.run(
            ["git", "check-ignore", "-v", "--", rel],
            cwd=top, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):       # pragma: no cover
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        m = _IGNORE_RULE.match(line.split("\t", 1)[0])
        if not m:
            continue
        pat = m.group("pat").strip()
        if not pat:
            continue
        # A NEGATION IS NOT A MATCH. check-ignore -v reports the DECIDING
        # rule, and for a re-included path that rule is the negation
        # itself, e.g. ".gitignore:2:!Lib.pretty/". Exit status 0 plus a
        # non-empty pattern is therefore not enough: git is saying the
        # path is explicitly NOT ignored, which is the opposite of what
        # the caller asked. Believing it inverts the guard in the
        # DANGEROUS direction -- a library git would happily stage reads
        # as safely ignored, and third-party artwork lands in a tracked
        # tree. The shape that triggers it is the common one: "*.pretty/"
        # to ignore built libraries, plus a negation to keep one tracked.
        if pat.startswith("!"):
            return None
        return pat
    return None


def _git_ignores(top: Path, target: Path, is_dir: bool) -> bool:
    """Does the working tree at `top` ignore `target`?

    THE FIRST-RUN FALSE REFUSAL. check-ignore decides whether a
    DIRECTORY-ONLY pattern (`Lib.pretty/`) can match a path by asking whether
    that path IS a directory -- it stats it. -o is checked before the library
    is created, so while the directory is still absent the rule reports NO
    MATCH, the run is refused, and then a bare `mkdir Lib.pretty` makes the
    identical command succeed. Same command, opposite answers, against a
    --help that promises the library is "Created if absent".

    MEASURED, all four combinations, git 2.43.0, one repo per row:

        .gitignore    directory   query          check-ignore
        Lib.pretty/   absent      Lib.pretty     NO MATCH  <-- the false refusal
        Lib.pretty/   absent      Lib.pretty/    match
        Lib.pretty/   present     Lib.pretty     match
        Lib.pretty/   present     Lib.pretty/    match
        Lib.pretty    absent      Lib.pretty     match
        Lib.pretty    absent      Lib.pretty/    match
        Lib.pretty    present     Lib.pretty     match
        Lib.pretty    present     Lib.pretty/    match

    So for a DIRECTORY the slash form is the one that is right in all four,
    and both forms are asked anyway: a single check-ignore invocation is not
    trusted to settle this, and either form finding a real named rule is
    enough.

    is_dir IS NOT OPTIONAL AND IS NOT GUESSED. The slash form asserts to git
    "this path is a directory", so asking it about a FILE would let a
    directory-only pattern match something it does not actually ignore -- a
    false ALLOW, the dangerous direction. The library is a directory by
    contract (-o must end in .pretty); the journal is a file. Each is asked
    about as what it is, whether or not it exists yet.
    """
    try:
        rel = target.relative_to(top).as_posix()
    except ValueError:                                  # pragma: no cover
        return False
    forms = (rel + "/", rel) if is_dir else (rel,)
    return any(_ignore_rule(top, f) for f in forms)


def _check_output_lib(lib: Path, journal: Path, allow_tracked: bool) -> None:
    """EVERY DURABLE PATH THIS TOOL WRITES, CHECKED -- not just -o.

    _git_toplevel and _git_ignores were written for --preview-dir and called
    from nowhere else, so the one directory this tool definitely fills with
    derived artwork was the one directory with NO containment check of any
    kind. Reproduced in the real public repo with real MFB art: a run straight
    into a tracked path, exit 0, not a word.

    Round 4 fixed that for the .pretty and then claimed the guard covered
    everything the tool wrote, while the staging directory, the undo directory
    AND the journal were all landing in lib.parent -- outside the checked
    path. The first two no longer exist. The journal still does, deliberately:
    it must stay OUTSIDE the .pretty because `kicad-cli fp upgrade -o` copies
    only .kicad_mod files and silently drops anything else. So it gets its own
    check rather than an assurance.

    A footprint is not a preview -- it is line art on tone layers, not a
    recognisable colour render -- but it is still DERIVED FROM the source art,
    this corpus includes third-party and brand material, and a working tree is
    a thing that gets committed and pushed. The journal is not art, but it
    quotes every source path and every footprint name the run touched.

    SatoshiStarter/RecklessArt.pretty is the legitimate case, and it is not
    exotic: a private board repo that tracks its own art library on purpose.
    That is why the way through is a flag the user types, and not a heuristic
    that tries to guess which checkouts are private.
    """
    if allow_tracked:
        return
    # (path, it-is-a-directory, what-it-is). The install temporary of
    # _install() is inside the library, so checking the library covers it; the
    # emit stage is in the system temporary directory and is on no working
    # tree at all.
    for target, is_dir, what in ((lib.resolve(), True, "-o"),
                                 (journal.resolve(), False, "--journal")):
        top = _git_toplevel(target)
        if top is None or _git_ignores(top, target, is_dir):
            continue
        if what == "-o":
            why = (f"THIS IS WHERE THE ARTWORK LANDS. Every footprint "
                   f"installed here is derived from a source image, this "
                   f"corpus includes third-party and brand art, and a working "
                   f"tree is a thing that gets committed and pushed.")
            fix = (f"  * add the library to {top / '.gitignore'}, if these "
                   f"footprints are build output;\n"
                   f"  * point -o outside the checkout;\n")
        else:
            why = (f"THAT IS THIS RUN'S JOURNAL, and it is a file this tool "
                   f"writes. It lives beside the library rather than inside "
                   f"it because `kicad-cli fp upgrade -o` copies only "
                   f".kicad_mod files and would silently drop it -- so being "
                   f"a sibling of an ignored library does not make it "
                   f"ignored, and it names every source path and every "
                   f"footprint this run touched.")
            fix = (f"  * add it to {top / '.gitignore'} -- ignoring the "
                   f"library's whole parent directory covers both;\n"
                   f"  * point --journal somewhere outside the checkout;\n")
        raise Usage(
            f"{what} {target}: that is inside the git working tree {top}, and "
            f"git does not ignore it.\n{why}\nThree ways on:\n{fix}"
            f"  * pass --allow-tracked-library, if these paths are MEANT to "
            f"be tracked -- the real case for a private board repo that ships "
            f"its own art library.\n"
            f"With no git on the machine this rule cannot fire at all, so it "
            f"is a guard and not a guarantee.")


def _foreign_collisions(pieces: list[Piece], lib: Path, produced: set[str]
                        ) -> list[tuple[Path, Piece]]:
    if not lib.is_dir():
        return []
    hits = []
    for p in pieces:
        tgt = lib / f"{p.name}.kicad_mod"
        if tgt.is_file() and not is_ours(tgt, produced):
            hits.append((tgt, p))
    return hits


def _foreign_message(lib: Path, foreign: list[tuple[Path, Piece]]) -> str:
    rows = "\n".join(f"  {t.name}   <- would be overwritten by {p.source}"
                     for t, p in foreign)
    return (
        f"FOREIGN FOOTPRINT(S) in {lib}: this run would overwrite "
        f"{len(foreign)} footprint(s) it did not produce.\n{rows}\n"
        f"Neither the journal beside the library nor an emit_art provenance "
        f"stamp inside the (descr) says build_library made them, so as far as "
        f"this tool can tell they are somebody else's work and a name "
        f"collision with them is destruction, not an update. This is the real "
        f"library's shape: art_hex_asic_window comes from "
        f"tools/texture_board.py and carries Edge.Cuts, art_btc_whitepaper_b "
        f"comes from tools/microtext.py and is 1534 fp_text elements. This "
        f"tool cannot rebuild either one.\nNothing was written. Rename the "
        f"source, set `name = ...` for it in the sidecar, point -o at a "
        f"different library, or pass --overwrite-foreign if you have decided "
        f"that these really are yours to replace.")


def _install(src: Path, dst: Path) -> None:
    """Put `src` at `dst` atomically, and touch nothing else.

    THE INCUMBENT IS NEVER MOVED, copied aside, or opened. os.replace lands
    the new footprint on top of the old one in a single step, so no instant
    exists in which `dst` is absent, and an interrupt anywhere in a run leaves
    every footprint either OLD or NEW. That is the whole reason there is no
    undo directory, no rollback and no audit in this file any more: nothing is
    set aside, so there is nothing to put back and no restoration to
    misreport.

    EXDEV IS THE NORMAL PATH HERE, NOT AN EXOTIC ONE. `src` is in the system
    temporary directory, which is often a different filesystem from the
    library and under WSL always is (/tmp is ext4, /mnt/c is DrvFs), and
    os.replace refuses to cross filesystems. So the fallback copies into THE
    TARGET'S OWN DIRECTORY under a unique dot-name and replaces from there:
    same directory means same filesystem, so the step that actually lands the
    footprint is still one atomic os.replace. The temporary is unlinked on any
    failure, including an interrupt.

    That temporary is the only thing this tool writes into the library besides
    the footprints, and it cannot be mistaken for one: mkstemp gives it a
    leading dot and a `.tmp` suffix, and everything that reads a .pretty --
    KiCad, and this file -- globs `*.kicad_mod`. It is inside the library,
    which is the directory the -o guard checks.

    A SIGKILL cannot be caught, so it can strand exactly one such file. That
    is the honest residue, and it is the whole of it: one invisible file the
    user can delete, where the previous design stranded whole directories of
    derived art as a matter of course and needed a sweep -- which then became
    a destruction path of its own. mkstemp and not a fixed name, so two runs
    against one library cannot collide on it.
    """
    try:
        os.replace(src, dst)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    fd, name = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.",
                                suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except BaseException:                               # noqa: BLE001
        # The cleanup may not replace the failure that caused it: an
        # unwritable library fails the copy AND the unlink, and reporting the
        # unlink would hide the real reason.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:                                 # pragma: no cover
            pass
        raise


def _digest(p: Path) -> str | None:
    """sha256 of a file, or None if it cannot be read."""
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _landed(want: dict[str, str | None], lib: Path) -> list[str]:
    """Which pieces actually reached the library. READ THE DISK.

    Not "did the loop get this far" and not "did os.replace return": the
    content that was meant to land, compared against the content that is
    there. Every claim the summary and the journal make about what a run
    installed comes from here.

    `want` is the staged digest taken BEFORE the install, because os.replace
    MOVES on a same-filesystem install and the staged file is gone afterwards
    -- comparing against it then reads a missing file and reports that nothing
    was installed at all. (It survives the cross-device path, so a check that
    used it directly would have been right in WSL and silently wrong on
    Windows, which is the worse way round.)

    There is nothing else left to ask. The old code had to reason about
    restored / absent / new / gone / LOST / UNKNOWN because it moved
    incumbents aside and might fail to put them back. Nothing is moved now, so
    a target holds either this run's content or the content it already held,
    and those are the only two answers there are.
    """
    return [n for n, d in want.items()
            if d is not None and _digest(lib / f"{n}.kicad_mod") == d]


def _say_interrupted(exc: BaseException, installed: list[str], lib: Path,
                     journal_path: Path) -> None:
    """What landed before the interrupt, said on the way out.

    run() is abandoned from here, so nothing below it gets to print. There is
    no rollback to report and no restoration that could have half-succeeded --
    every footprint in the library is either this run's or the one that was
    there before it started -- so all this has to be right about is which.

    It is guarded because it is the last thing that runs, and a traceback
    printed on top of an interrupted install is strictly worse than one line.
    """
    try:
        what = ("interrupted (Ctrl-C)" if isinstance(exc, KeyboardInterrupt)
                else f"{type(exc).__name__}: {exc}")
        e = sys.stderr.write
        e(f"\nbuild_library: {what.upper()} PART WAY THROUGH THE INSTALL "
          f"INTO {lib}\n")
        if installed:
            e(f"  {len(installed)} footprint(s) were already installed and "
              f"hold THIS RUN'S content: {', '.join(installed)}\n")
        e("  Every other footprint is exactly as it was. Nothing is missing: "
          "no incumbent was moved aside, so none needed restoring.\n"
          f"  The journal at {journal_path} was NOT written and does not "
          f"describe the run above.\n\n")
    except BaseException:                               # noqa: BLE001
        pass


VERDICT_ORDER = (verify_art.PASS, verify_art.WARN, verify_art.FAIL,
                 verify_art.SKIP, "NOT VERIFIED", "NOT REACHED")


def _verdict_counts(results: list[Result]) -> dict:
    counts = {k: 0 for k in VERDICT_ORDER}
    for r in results:
        v = r.verdict or "NOT REACHED"
        counts[v] = counts.get(v, 0) + 1
    return counts


def run(a) -> tuple[int, dict]:
    lib = Path(a.output)
    if lib.suffix.lower() != ".pretty":
        raise Usage(f"-o {a.output}: a KiCad footprint library directory must "
                    f"end in .pretty; KiCad will not load anything else as one")
    if lib.exists() and not lib.is_dir():
        raise Usage(f"-o {a.output}: exists and is not a directory")
    journal_path = journal_path_for(lib, a.journal)
    # BEFORE anything is probed, created or built. A refusal here must leave
    # the disk exactly as it was, including not creating the library. Both
    # durable paths this tool writes are checked, not just -o: the journal is
    # a SIBLING of the library, and a sibling of an ignored path is not an
    # ignored path.
    _check_output_lib(lib, journal_path, a.allow_tracked_library)

    if a.min_area is not None:
        a.min_area = _norm_min_area(a.min_area, "--min-area")
    if a.max_dropped_pct < 0:
        raise Usage("--max-dropped-pct must not be negative")
    _check_emit_args(a.emit_arg, "--emit-arg")

    record: dict = {
        "tool": "build_library.py",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "library": str(lib),
        "sources": list(a.sources),
        "recursive": bool(a.recursive),
        "min_area": a.min_area or "auto",
        "max_dropped_pct": a.max_dropped_pct,
        "on_fail": a.on_fail,
        "dry_run": bool(a.dry_run),
        "strict": bool(a.strict),
        "overwrite_foreign": bool(a.overwrite_foreign),
        "allow_tracked_library": bool(a.allow_tracked_library),
    }

    # The tool's own output is never a source. The LIBRARY can legitimately
    # sit inside the source folder, and a .pretty is not a place art comes
    # from. That is the whole list now: the tool writes no image anywhere, so
    # there is nothing else of its own that discovery could pick up.
    pieces, sidecars, notes, found = _plan(a, record, [lib])
    record["notes"] = notes
    record["sidecars"] = [str(s.path) for s in sidecars]
    if not pieces:
        record["pieces"] = []
        record["summary"] = {"added": 0, "updated": 0, "unchanged": 0,
                             "failed": 0, "untouched": 0}
        return 3, record

    # Name validation runs FIRST: before the environment is probed and before
    # anything is created. A collision or a too-long path must leave the disk
    # exactly as it was, including not leaving an empty library directory
    # behind, and must not depend on whether a kicad-cli was found.
    _validate_names(pieces, lib, a)

    # ...and provenance runs right behind it, for the same reason. A footprint
    # this tool did not produce is not its property to overwrite.
    produced_before = load_produced(journal_path)
    foreign = _foreign_collisions(pieces, lib, produced_before)
    if foreign and not a.overwrite_foreign:
        raise Usage(_foreign_message(lib, foreign))
    record["foreign_overwritten"] = sorted(p.stem for p, _ in foreign)

    cfg, choice = _make_cfg(a)
    record["kicad_cli"] = choice.path
    record["kicad_version"] = choice.version
    record["verified"] = not a.no_verify
    record["palette"] = cfg.palette.source

    if not a.dry_run:
        lib.mkdir(parents=True, exist_ok=True)

    produced = {p.name for p in pieces}
    existing = {f.stem: f for f in sorted(lib.glob("*.kicad_mod"))}
    untouched = sorted(set(existing) - produced)

    jobs = a.jobs if a.jobs and a.jobs > 0 else default_jobs()
    results: list[Result] = []
    not_reached: list[str] = []
    aborted = False

    # THE STAGE IS THE SYSTEM TEMPORARY DIRECTORY, and that is the whole of
    # it: no `dir=`, no name anything else has to recognise, no sweep of
    # anybody's directory, nothing left behind for a later run to reason
    # about. tempfile chooses the location and the OS owns it. A dry run and a
    # real run are identical here, because neither one needs the stage to be
    # on the library's volume -- _install() carries the cross-device case
    # explicitly, and it is the usual case rather than the rare one.
    with tempfile.TemporaryDirectory(prefix=STAGE_PREFIX) as td:
        stage = Path(td)

        def emit_job(p: Piece) -> tuple[Piece, EmitOut, bool]:
            outf = stage / f"{p.name}.kicad_mod"
            repf = stage / f"{p.name}.report.json"
            e = run_emit(p, outf, repf, [], p.descr)
            inverted = False
            if e.rc == 3 and not a.no_ink_fallback \
                    and "--ink-tone" not in " ".join(p.emit_args):
                d = f"{p.descr.strip()} {INVERT_NOTE}" if p.descr else INVERT_NOTE
                e2 = run_emit(p, outf, repf, ["--ink-tone", "T1"], d)
                if e2.rc == 0:
                    return p, e2, True
                e.stderr += ("\n-- retry with --ink-tone T1 also failed "
                             f"(exit {e2.rc}) --\n" + e2.stderr)
            return p, e, inverted

        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(emit_job, p) for p in pieces]
            for fut, piece in zip(futures, pieces):
                if aborted:
                    fut.cancel()
                    not_reached.append(piece.name)
                    continue
                p, e, inverted = fut.result()
                res = Result(piece=p, inverted=inverted)
                target = lib / f"{p.name}.kicad_mod"
                if target.exists():
                    res.prev_bytes = target.stat().st_size
                    res.prev_mtime = fmt_mtime(target)

                if e.rc != 0 or e.report is None:
                    why = EMIT_EXIT_MEANING.get(
                        e.rc, f"emit_art exited {e.rc}")
                    res.problems.append(why)
                    tail = [ln for ln in e.stderr.splitlines() if ln.strip()][-6:]
                    res.notes += [f"emit_art: {ln.strip()}" for ln in tail]
                    if e.rc == 3 and a.no_ink_fallback:
                        res.notes.append(
                            "the --ink-tone T1 retry was disabled with "
                            "--no-ink-fallback")
                    res.state = FAILED
                    if res.prev_bytes is not None:
                        res.notes.append(
                            f"kept the previous footprint "
                            f"({res.prev_bytes:,} B, {res.prev_mtime})")
                    results.append(res)
                    if a.on_fail == "abort":
                        aborted = True
                    continue

                if inverted:
                    res.notes.append(
                        "EMPTY OUTPUT on the first pass -- every inked pixel "
                        "landed on T5, the board's own colour; re-emitted with "
                        "--ink-tone T1 (silk white) and stamped into the descr")
                _analyse(e.report, res, a.max_dropped_pct)
                staged = stage / f"{p.name}.kicad_mod"
                res.staged = staged
                _guard(res, a)
                _fidelity(res, staged, e.report)
                if not res.problems:
                    _verify(res, staged, cfg, a.no_verify)

                if res.problems:
                    res.state = FAILED
                    if a.on_fail == "write" and staged.exists():
                        stamp = ("FAILED ACCEPTANCE, INSTALLED ANYWAY WITH "
                                 "--on-fail write: "
                                 + "; ".join(res.problems)
                                 + ". Do not ship this without re-checking it.")
                        d = f"{p.descr.strip()} {stamp}" if p.descr else stamp
                        e3 = run_emit(p, staged,
                                      stage / f"{p.name}.report.json",
                                      (["--ink-tone", "T1"] if res.inverted else []),
                                      d)
                        if e3.rc == 0 and e3.report is not None:
                            res.bytes = e3.report.get("bytes")
                            res.notes.append(
                                "installed anyway (--on-fail write); the "
                                "failure is stamped into the footprint's descr")
                            res.state = _install_state(staged, lib, p.name)
                        else:
                            res.notes.append(
                                "--on-fail write could not re-emit with the "
                                "failure stamp; nothing was installed")
                    elif a.on_fail == "abort":
                        aborted = True
                    if res.state == FAILED and res.prev_bytes is not None:
                        res.notes.append(
                            f"kept the previous footprint "
                            f"({res.prev_bytes:,} B, {res.prev_mtime})")
                else:
                    res.state = _install_state(staged, lib, p.name)
                results.append(res)

        # ---- install ------------------------------------------------------
        # One os.replace per piece, and that is the entire install. Nothing is
        # preserved, because nothing is displaced: a piece that has not been
        # reached yet still has whatever it had before, and a piece that has
        # been reached has this run's bytes. A failure part way through is
        # therefore not a state needing repair, it is just a shorter run.
        installed: list[str] = []
        install_error: str | None = None
        n_failed = sum(1 for r in results if not r.accepted)
        do_install = not a.dry_run and not (a.on_fail == "abort" and n_failed)
        pending = [r for r in results if r.state in (ADDED, UPDATED)
                   and r.staged and r.staged.exists()]
        if do_install:
            # Taken BEFORE the loop: a same-filesystem install MOVES the
            # staged file, so afterwards there is nothing left to compare the
            # library against. See _landed().
            want = {r.piece.name: _digest(r.staged) for r in pending}
            try:
                for r in pending:
                    _install(r.staged, lib / f"{r.piece.name}.kicad_mod")
            except OSError as e:
                install_error = f"{type(e).__name__}: {e}"
            except BaseException as e:                  # noqa: BLE001
                # Ctrl-C, SystemExit, MemoryError. run() is abandoned from
                # here so nothing below will print, and the library needs
                # nothing done to it -- but the user should still be told what
                # landed and that the journal did not get written.
                _say_interrupted(e, _landed(want, lib), lib, journal_path)
                raise
            # OFF THE DISK, not off the loop. Identical answer whether the
            # loop ran to the end or stopped on an OSError half way, which is
            # exactly what makes it worth reading it back instead of counting
            # iterations.
            installed = _landed(want, lib)

    if do_install:
        # EVERY ADDED/UPDATED ROW IS RECONCILED AGAINST THE DISK. A row that
        # says ADDED is a claim that a file is in the library, so it is only
        # allowed to stand when the file is there with this run's content.
        #
        # The loop stops at the first OSError, so pieces before it ARE
        # installed and only the ones that are not on disk are failures.
        # Marking every ADDED/UPDATED row failed -- which is what this did
        # while it also promised each of them a rollback -- was wrong in both
        # directions at once.
        landed = set(installed)
        why = (f"the install stopped here ({install_error})"
               if install_error else
               "the emitted footprint was not there to install")
        for r in results:
            if r.state in (ADDED, UPDATED) and r.piece.name not in landed:
                r.state = FAILED
                r.problems.append(
                    f"NOT INSTALLED: {why}. "
                    + (f"The footprint already in the library is untouched "
                       f"({r.prev_bytes:,} B, {r.prev_mtime})."
                       if r.prev_bytes is not None
                       else "Nothing was added under this name."))
        n_failed = sum(1 for r in results if not r.accepted)
    record["install_error"] = install_error

    if a.on_fail == "abort" and n_failed:
        record["aborted"] = True

    # ---- journal, written from the POST-INSTALL state ----------------------
    # Read back off the disk after the moves, not from intent, so the summary
    # and the library cannot disagree.
    for r in results:
        f = lib / f"{r.piece.name}.kicad_mod"
        r.__dict__["on_disk_bytes"] = f.stat().st_size if f.exists() else None

    record["pieces"] = [{
        "name": r.piece.name,
        "source": str(r.piece.source),
        "source_basename": r.piece.source.name,
        "size_mm": r.piece.size,
        "state": r.state,
        "label": r.label,
        "inverted": r.inverted,
        "min_area": r.piece.min_area,
        "emit_args": r.piece.emit_args,
        "bytes": r.bytes,
        "on_disk_bytes": r.__dict__.get("on_disk_bytes"),
        "polys": r.polys,
        "width_mm": r.width_mm,
        "height_mm": r.height_mm,
        "t5_px": r.t5_px,
        "opaque_px": r.opaque_px,
        "t5_pct_of_opaque": round(r.t5_pct, 4),
        "dropped": r.dropped_tones,
        "dropped_regions": r.dropped_regions,
        "dropped_mm2": round(r.dropped_mm2, 6),
        "ink_mm2": round(r.ink_mm2, 6),
        "dropped_pct_of_ink": round(r.dropped_pct, 5),
        "mask": r.piece.mask,
        "tone_map": r.piece.tone_map,
        "fidelity": r.fidelity,
        "verify": r.verdict,
        "checks": r.checks,
        "problems": r.problems,
        "warnings": r.warnings,
        "notes": r.notes,
        "emit_warnings": r.emit_warnings,
        "previous_bytes": r.prev_bytes,
        "previous_mtime": r.prev_mtime,
    } for r in results]
    # "untouched" means "still in the library, left alone". A name that is not
    # on disk is not untouched: the journal used to list bravo_20mm as
    # untouched, and keep it in `produced`, for a file the tool had deleted --
    # the provenance record the whole safety system rests on asserting that a
    # destroyed footprint was present and was this tool's own work. Nothing
    # here deletes any more, but the disk is still the source of the claim.
    record["untouched"] = [u for u in untouched
                           if existing[u].is_symlink() or existing[u].exists()]
    record["installed"] = installed
    record["not_reached"] = not_reached
    # Every footprint name this tool has produced into this library, carried
    # across runs. A run narrowed to two pieces must not turn the other
    # nineteen into strangers: `produced` is half of the provenance test that
    # decides what --overwrite-foreign is needed for.
    record["produced"] = sorted(
        produced_before | {r.piece.name for r in results if r.ok})
    # NO "source_dirs". It existed only to feed the preview-dir art-tree
    # guard, and it outlived its usefulness badly: once a directory was in
    # there it stayed in there, so the refusal it powered became PERMANENT for
    # that library and no later command line could clear it. That is what made
    # the standard art/ + out/ sibling layout unbuildable for a checkout that
    # had once been built the other way.
    record["summary"] = {
        "added": sum(1 for r in results if r.state == ADDED),
        "updated": sum(1 for r in results if r.state == UPDATED),
        "unchanged": sum(1 for r in results if r.state == UNCHANGED),
        "failed": sum(1 for r in results if not r.accepted),
        "failed_but_written": sum(1 for r in results if not r.accepted and r.ok),
        "inverted": sum(1 for r in results if r.inverted and r.accepted),
        "untouched": len(untouched),
        "not_reached": len(not_reached),
        "total": len(results),
        "verify": _verdict_counts(results),
    }
    record["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    record["journal"] = str(journal_path)

    journal_error = None
    if not a.dry_run:
        try:
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            journal_path.write_text(json.dumps(record, indent=2),
                                    encoding="utf-8")
        except OSError as e:
            journal_error = f"{type(e).__name__}: {e}"
            record["journal_error"] = journal_error

    if not a.as_json:
        _print_summary(a, record, results, lib, choice, untouched,
                       journal_path, sidecars, notes, not_reached)
    code = worst_exit(results)
    if install_error or journal_error:
        code = max(code, 1)
    return code, record


def _install_state(staged: Path, lib: Path, name: str) -> str:
    target = lib / f"{name}.kicad_mod"
    if not target.exists():
        return ADDED
    try:
        if target.read_bytes() == staged.read_bytes():
            return UNCHANGED
    except OSError:
        return UPDATED
    return UPDATED


def _print_summary(a, record, results, lib, choice, untouched,
                   journal_path, sidecars, notes, not_reached=()) -> None:
    w = sys.stdout.write
    sizes = sorted({r.piece.size for r in results})
    srcs = len({r.piece.source for r in results})
    w(f"\nbuild_library -- {srcs} source(s), {len(sizes)} size(s) -> {lib}\n")
    if a.no_verify:
        w("  kicad-cli : NOT USED (--no-verify) -- nothing here is verified\n")
    else:
        w(f"  kicad-cli : {choice.path} ({choice.version})\n")
    w(f"  options   : {', '.join(str(s.path) for s in sidecars) or 'none'}\n")
    w(f"  min-area  : {record['min_area']} (dropped-area budget "
      f"{a.max_dropped_pct:g}% of ink)\n")
    if a.dry_run:
        w("  DRY RUN   : nothing will be installed\n")
    for n in notes:
        w(f"  ! {n}\n")
    for d in record.get("skipped_subdirs", []):
        w(f"  - skipped sub-directory (no --recursive): {d}\n")
    ign = record.get("ignored_files") or []
    if ign:
        # A bare `continue` here meant "I put the file in and got no footprint
        # and no message", which is a support call. Naming a .tif explicitly
        # is an error, so dropping one in a folder must at least be visible.
        w(f"  - {len(ign)} file(s) ignored, not an image build_library reads "
          f"({', '.join(IMAGE_EXT)}):\n")
        for f in ign[:20]:
            w(f"                 {f}\n")
        if len(ign) > 20:
            w(f"                 ... and {len(ign) - 20} more\n")
    if record.get("foreign_overwritten"):
        w(f"  ! OVERWROTE FOREIGN: --overwrite-foreign was given, so "
          f"{len(record['foreign_overwritten'])} footprint(s) this tool did "
          f"not produce were replaced: "
          f"{', '.join(record['foreign_overwritten'])}\n")
    w("\n")

    nw = max([26] + [len(r.piece.name) for r in results])
    for r in sorted(results, key=lambda x: x.piece.name):
        head = (f"  {r.label:<10} {r.piece.name:<{nw}}")
        if r.bytes is not None:
            head += (f" {r.bytes:>9,} B {r.polys:>5,} polys "
                     f"{r.width_mm:6.2f} x {r.height_mm:5.2f} mm")
        else:
            head += " " * 45
        if r.verdict:
            head += f"  verify {r.verdict}"
        if r.state == UPDATED and r.prev_bytes is not None:
            head += f"  (was {r.prev_bytes:,} B)"
        w(head.rstrip() + "\n")
        # --quiet drops the notes, never the PROBLEMS and never the verify
        # WARNINGS. A FAILED row with no reason on it is a row nobody can act
        # on, and a WARN whose detail only exists in a JSON file is not a
        # warning: the whole point of this tool is maintenance without an
        # agent, so the number that decides fabricability has to be here.
        for p in r.problems:
            w(f"                 {p}\n")
        for x in r.warnings:
            w(f"                 {x}\n")
        if a.quiet:
            continue
        for n in r.notes:
            w(f"                 {n}\n")
        for d in r.dropped_tones:
            # 'px' is the tone's whole census, 'mm2' is what was actually
            # dropped. Printing them side by side unlabelled made a 0.00089
            # mm2 loss read as 104,502 px.
            w(f"                 DROPPED {d['tone']}: "
              f"{d['regions_dropped']} region(s), {d['mm2']:.6f} mm2 "
              f"(tone total {d['tone_total_px']:,} px = "
              f"{d['tone_total_mm2']:.4f} mm2)"
              + (" -- TONE LOST ENTIRELY" if d["tone_lost_entirely"] else "")
              + "\n")
        if r.dropped_tones:
            w(f"                 DROPPED TOTAL {r.dropped_regions} region(s), "
              f"{r.dropped_mm2:.6f} mm2 of {r.ink_mm2:.4f} mm2 of ink = "
              f"{r.dropped_pct:.3f}%\n")
    w("\n")

    if untouched:
        w(f"  {UNTOUCHED}  {len(untouched)} footprint(s) this run did not "
          f"produce, left alone:\n")
        for u in untouched:
            w(f"                 {u}\n")
    if not_reached:
        w(f"  NOT REACHED  {len(not_reached)} piece(s) after the abort: "
          f"{', '.join(not_reached)}\n")
    s = record["summary"]
    w(f"\n  {s['added']} added, {s['updated']} updated, {s['unchanged']} "
      f"unchanged, {s['failed']} failed, {s['untouched']} untouched"
      + (f".  ({s['inverted']} inverted)" if s["inverted"] else ".") + "\n")

    # The verdict tally. On a 21-footprint run nobody should have to read 21
    # rows to learn whether anything is fabricable.
    v = s.get("verify") or {}
    shown = [f"{n} {k}" for k in VERDICT_ORDER for n in [v.get(k, 0)] if n]
    if shown:
        w(f"  verify:  {', '.join(shown)}.\n")
    warned = sorted(r.piece.name for r in results
                    if r.verdict == verify_art.WARN and r.ok)
    if warned:
        w(f"  {len(warned)} piece(s) verified WARN and were INSTALLED: "
          f"{', '.join(warned)}.\n"
          f"  A WARN is verify_art measuring a feature or a gap against a "
          f"fabrication floor and finding it short; the numbers are on the "
          f"rows above. This tool installs them on purpose -- every real "
          f"piece in this corpus warns about something -- so read them, or "
          f"re-run with --strict to refuse them.\n")
    skipped = sorted(r.piece.name for r in results
                     if r.verdict == verify_art.SKIP and r.ok)
    if skipped:
        w(f"  {len(skipped)} piece(s) verified SKIP and were INSTALLED: "
          f"{', '.join(skipped)}. A SKIP is not a pass -- a check did not "
          f"run.\n")
    if s["failed_but_written"]:
        w(f"  {s['failed_but_written']} of those failures were INSTALLED "
          f"ANYWAY by --on-fail write. The exit code is still 1.\n")
    if a.on_fail == "abort" and s["failed"]:
        w("  --on-fail abort: NOTHING was installed; the library is "
          "byte-identical to how it started.\n")
    if record.get("install_error"):
        w(f"\n  INSTALL FAILED: {record['install_error']}\n")
        # READ OFF THE DISK, and there are only two things it can say now.
        # This used to be a six-branch account of a rollback -- restored /
        # gone / LOST / UNKNOWN, preserved originals kept, "byte-identical to
        # how it started" -- and the two most reassuring of those sentences
        # were both printed over a footprint the tool had destroyed. Nothing
        # is displaced any more, so there is no rollback to describe and no
        # way for the description to be wrong.
        done = record.get("installed") or []
        if done:
            w(f"  {len(done)} footprint(s) had already been installed and "
              f"hold this run's content: {', '.join(done)}\n")
        else:
            w("  Nothing had been installed yet.\n")
        w("  Every other footprint is exactly as it was before this run. No "
          "incumbent is ever moved aside, so none is missing and none needed "
          "restoring.\n")
    if record.get("journal_error"):
        w(f"\n  JOURNAL NOT WRITTEN: {record['journal_error']}\n"
          f"  The library on disk is correct, but the next run cannot use the "
          f"journal to tell its own footprints from anybody else's and will "
          f"fall back to the emit_art stamp alone.\n")
    if a.dry_run:
        w("  DRY RUN: nothing was installed, no journal written.\n")
    elif not record.get("journal_error"):
        w(f"  journal: {journal_path}\n")
    w("\n")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help-options" in argv:
        sys.stdout.write(HELP_OPTIONS)
        return 0
    if "--propose-tones" in argv:
        # Intercepted before the main parser for the same reason
        # --help-options is: this mode BUILDS NOTHING, so it must not require
        # -o, must not probe a kicad-cli, and must not create a library
        # directory as a side effect of being asked a question.
        pp = argparse.ArgumentParser(add_help=False)
        pp.add_argument("sources", nargs="*")
        pp.add_argument("--propose-tones", action="store_true")
        pp.add_argument("--palette-mask", default="black")
        pp.add_argument("--recursive", action="store_true")
        pp.add_argument("-o", "--output", default=None)
        pa, unknown = pp.parse_known_args(argv)
        if unknown:
            sys.stderr.write(
                f"\nbuild_library --propose-tones: it censuses sources and "
                f"prints a table; it does not build, so it takes only SOURCE, "
                f"--palette-mask and --recursive.\nUnrecognised here: "
                f"{' '.join(unknown)}\n\n")
            return 2
        if not pa.sources:
            sys.stderr.write("\nbuild_library --propose-tones: name at least "
                             "one SOURCE image or directory\n\n")
            return 2
        found = discover(pa.sources, pa.recursive, [])
        if found.errors:
            sys.stderr.write("\nbuild_library: " + "\n".join(found.errors) + "\n\n")
            return 2
        if not found.files:
            sys.stderr.write(f"\nbuild_library: no sources matched "
                             f"({', '.join(IMAGE_EXT)})\n\n")
            return 3
        try:
            return _propose_tones(pa, found.files, pa.palette_mask or "black")
        except palette.PaletteError as e:
            sys.stderr.write(f"\nbuild_library: {e}\n\n")
            return 2
    ap = build_parser()
    a = ap.parse_args(argv)
    try:
        code, record = run(a)
    except Usage as e:
        sys.stderr.write(f"\nbuild_library: {e}\n\n")
        return 2
    except SidecarError as e:
        sys.stderr.write(f"\nbuild_library: {e}\n\n")
        return 2
    except KeyboardInterrupt:
        # A Ctrl-C during the INSTALL has already been described by
        # _say_interrupted, which named what landed. This covers the EMIT
        # phase, where the library has not been touched at all and the system
        # temporary directory is the only thing discarded.
        sys.stderr.write("\nbuild_library: interrupted.\n\n")
        return 130
    if a.as_json:
        sys.stdout.write(json.dumps(record, indent=2) + "\n")
    if code == 3:
        # discover() collected these; run() used to throw them away, so
        # pointing one level too high printed four words and exited.
        e = sys.stderr.write
        e(f"build_library: no sources matched ({', '.join(IMAGE_EXT)})\n")
        subs = record.get("skipped_subdirs") or []
        if subs:
            e(f"  {len(subs)} sub-directory(ies) were NOT walked, because "
              f"--recursive was not given:\n")
            for d in subs[:20]:
                e(f"    {d}\n")
            if len(subs) > 20:
                e(f"    ... and {len(subs) - 20} more\n")
            e("  Point at one of them, or add --recursive.\n")
        ign = record.get("ignored_files") or []
        if ign:
            e(f"  {len(ign)} file(s) were not images build_library reads:\n")
            for f in ign[:20]:
                e(f"    {f}\n")
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:                          # pragma: no cover
        raise SystemExit(130)
