# Maintaining a footprint library — `tools/build_library.py`

Point it at art and a `.pretty`, and it keeps the library up to date. It is the
general form of `tools/render_library.py`: that file is a hand-curated manifest
of eleven pieces, this one walks a folder.

```
python3 tools/build_library.py <file-or-directory>... -o <SomeLib.pretty> [options]
```

Everything below was measured on this machine against **kicad-cli 10.0.0**
(`C:/Program Files/KiCad/10.0/bin/kicad-cli.exe`). Numbers are re-derivable with
the commands quoted.

> ### Round 4 removed two features. Read this if you used either.
>
> **Preview rendering is gone.** `--preview-dir`, the render made for every
> piece on every run, the `.build_library_previews` marker, the art-tree
> rules, and `journal["source_dirs"]` — all removed, not disabled. To get a
> colour render of a piece, run the renderer yourself and aim it:
>
> ```bash
> python3 tools/emit_art.py --labels art/logo.svg --width-mm 20 \
>     --name logo_20mm -o /tmp/logo_20mm.kicad_mod --preview /tmp/logo_20mm.png
> ```
>
> **`--regenerate` is gone**, along with `--allow-unverified-regenerate`.
> **This tool no longer deletes anything, under any flag.** To rebuild a
> library from scratch, delete the directory yourself and run it again:
>
> ```bash
> rm -r out/MyArt.pretty && python3 tools/build_library.py art/ -o out/MyArt.pretty
> ```
>
> Why both went, and why patching them again was the wrong move, is in
> [Why previews and `--regenerate` were removed](#why-previews-and---regenerate-were-removed).
> One guard arrived in their place: **`-o` is now refused inside a git working
> tree that does not ignore it**, unless you pass `--allow-tracked-library`.

> ### Round 5 removed the staging subsystem. Nothing you type changes.
>
> There is no staging directory, no undo directory, no stale-stage sweep and
> no `.build_library_*` convention any more — **and both repos' `.gitignore`
> rules for it are gone, because there is nothing left to ignore.** Each piece
> is emitted to a temporary file in the system temporary directory, verified
> there, and installed with one atomic `os.replace`. The incumbent is never
> displaced, so an interrupt leaves every footprint old or new and never
> missing, and no rollback is needed to make that true.
>
> Two things follow that you may notice. `journal["rolled_back"]`,
> `["disk_state"]`, `["rollback_errors"]`, `["unrecoverable"]`,
> `["recoverable_originals"]`, `["swept_stage_dirs"]` and `["held_undo_dirs"]`
> are **gone** from the run record — they described a rollback that no longer
> exists. And **`--journal` is now guarded like `-o`**: it is a file this tool
> writes, it sits *beside* the library rather than inside it, and a
> `.gitignore` rule naming only the library does not cover it. Ignore the
> library's parent directory, point `--journal` outside the checkout, or pass
> `--allow-tracked-library`.
>
> A first-run refusal is also fixed: a directory-only `.gitignore` rule
> (`MyArt.pretty/`) used to report *not ignored* while the directory did not
> exist yet, so run 1 was refused and a bare `mkdir` made run 2 succeed.

---

## The one-minute version

```bash
# a single image, two sizes, into a library that does not exist yet
python3 tools/build_library.py art/logo.svg -o out/MyArt.pretty --size 12 --size 20

# a whole drop-folder, per-piece settings from art/artlib.toml if it is there
python3 tools/build_library.py art/ -o out/MyArt.pretty

# see exactly what would happen, change nothing
python3 tools/build_library.py art/ -o out/MyArt.pretty --dry-run
```

Exit codes — a human running this unattended reads **only** this:

| code | meaning |
|---|---|
| `0` | every piece passed or warned, or was already up to date |
| `1` | at least one piece failed (not installed, unless `--on-fail write`), **or** the install failed — in which case each row says, read off the disk, whether that footprint holds this run's content or the one it already had |
| `2` | usage, sidecar, provenance or environment error. **Nothing was built** |
| `3` | no sources matched — the sub-directories that were *not* walked are named, with the `--recursive` hint |
| `130` | interrupted (`Ctrl-C`). Every footprint is old or new and none is missing; the run names what landed and says the journal was not written. Never a silent exit |

Exit `0` does **not** mean every footprint is fabricable everywhere; see
verification below. The footer's verdict tally is the line to read.

---

## What it guarantees

**It only ever overwrites its own work.** A name collision is not evidence of
ownership. A footprint is *this tool's* when the journal beside the library
names it, **or** when its `(descr)` carries emit_art's stamp
`kicad_art_generator/emit_art.py`. Anything else is **FOREIGN**, and a run that
would overwrite one stops with exit 2 before a single byte is emitted.

This is not hypothetical: `SatoshiStarter/RecklessArt.pretty` holds
`art_hex_asic_window` (from `texture_board.py`, carries `Edge.Cuts`) and
`art_btc_whitepaper_b` (from `microtext.py`, 1534 `fp_text` elements). Neither
is reproducible by this tool, and `art_hex_asic_window.png` in a drop folder
is a name an image could plausibly have. Before this check, seeding
`art_hex_asic_window_20mm.kicad_mod` with hand-made content and dropping the
matching PNG in gave `UPDATED`, exit 0, and the hand-made content gone — no
warning, no backup.

`--overwrite-foreign` is the deliberate way through, and it is reported on
stdout (`OVERWROTE FOREIGN: ...`) and in the journal when used.

**Append, never destroy — and now there is no other mode.** A `.kicad_mod` in
the library that this run did not produce is never opened for writing, never
rewritten, never deleted; it is listed as `UNTOUCHED`. Round 4 removed
`--regenerate`, so this is a property of the tool rather than of one default:
**there is no code path here that deletes a footprint.** Search the source for
`unlink` and the only hits are temp files it created itself in the same
function.

That makes the blast radius of every remaining bug strictly smaller. The worst
thing a broken run can now do to existing art is overwrite a footprint whose
name it produced *and* whose provenance says this tool made it — and that
overwrite is a single atomic `os.replace`, so the target holds either the old
footprint or the new one at every instant.

**Idempotence.** A second run over unchanged input writes *nothing at all* —
not an identical byte. Verified end to end: a seven-footprint library re-run
came back with all seven identical in `sha256` **and** in `mtime`. So the
library does not churn and re-running does not produce a git diff.

How "unchanged" is known: by **re-emitting and comparing bytes**. Not mtime —
`prep_assets.py` rewrites `assets/normalised/` wholesale and re-stamps every
file, so mtime would report the whole library as updated after every prep run.
Not a source-hash cache — a key that omits the emitter reports `UNCHANGED` for
a footprint whose geometry today's `emit_art.py` would build differently
(`emit_art.py` changed in 5 of the last 20 commits), and a key that includes
the emitter's hash invalidates on every commit and buys nothing. Re-emitting
costs 2.5–7.4 s per piece. There is deliberately no `--assume-unchanged`.

That is only safe because emit is deterministic: `--uuids` is off by default
because KiCad mints them on load, and even with it on `ArtFp._uuid` is a
`uuid5` of `name:index`, not a random one.

**Nothing reaches the library unexamined — which is not the same as
"everything in it is fabricable".** Every piece is emitted to a temporary
file in the system temporary directory, guarded, run through
`tools/verify_art.py` *there*, and only then installed. A piece whose verdict is `FAIL` is not installed and the previous
good footprint stays exactly where it was.

A piece whose verdict is **`WARN` is installed**, deliberately. Every real
piece in this corpus warns about something — for `satoshi_points_20mm`,
`GAP BELOW FLOOR: F.Cu narrowest gap 0.016434 mm < 0.1000 mm (copper) in 2 of
8 separated pair(s)` — and a tool that refused every WARN could not build the
library it exists to maintain. What changed in the hardening pass is that the
warning is now impossible to miss from stdout alone:

* every WARN and **every line of its detail** is printed under the row, and is
  **not** suppressed by `--quiet`;
* the footer carries a verdict tally (`verify:  18 PASS, 3 WARN.`);
* the footer then names them: `3 piece(s) verified WARN and were INSTALLED:
  ...`, with the reminder that `--strict` refuses them.

Before that, stdout said only `[WARN] clearance: 1 clearance problem(s)` while
the number that decides fabricability sat in a JSON file. A warning whose
content only exists in a JSON file is not a warning, and the goal here is
maintenance *without* an agent reading the journal.

Without `--no-verify` the run **refuses to start** if `kicad-cli` is missing or
below major 10 — unattended maintenance whose acceptance harness is silently
skipping is the exact situation that produced 21 layers of vacuous PASS before
commit `db5eff9`. verify's `SKIP` / `NOT TESTED` are reported as `NOT VERIFIED`
and counted separately from passes, never folded into them.

**The install cannot leave a hole, because nothing is ever displaced.** Each
piece is emitted to a unique temporary file in the **system** temporary
directory, guarded and verified *there*, and installed with a single
`os.replace` onto the target. The incumbent footprint is never moved, never
copied aside, never opened. `os.replace` is atomic, so at no instant is a
target absent: **an interrupt at any point leaves every footprint either old
or new, never missing.**

That is the whole of it. There is no staging directory, no undo directory, no
rollback, no audit, no sweep, and no `.build_library_*` convention in either
repo. If nothing is moved aside there is nothing to restore, nothing to sweep,
and no rollback claim that can be wrong.

**Why the subsystem was removed rather than moved a fourth time.** Four rounds
of evidence said the same thing: the defect always landed wherever the staging
directory lived.

| round | where the stage lived | what it cost |
|---|---|---|
| 2 | inside the library | `TemporaryDirectory.__exit__` `rmtree`d the stage on a `Ctrl-C` and took the preserved originals with it — alpha new, charlie old, `bravo_20mm.kicad_mod` **gone** |
| 3 | inside the library | the library ingested its own preview output and built `alpha_20mm_20mm` |
| 4 | beside the library | the stale-stage sweep began globbing `.build_library_*` in the library's **parent** — a directory the tool does not own — and the `-o` guard covered only the `.pretty` while the stage, the undo directory and the journal all landed in that parent, unchecked |

Rounds 3 and 4 answered with machinery: an undo directory outside the stage, a
rollback behind a `committed` flag, an audit reading the disk rather than the
intent, a guard around the audit for a *second* `Ctrl-C` arriving during the
unwind, and a guard around the report of that. Roughly 330 lines, all of it
correct, all of it existing to survive a hole that only existed because
something had been moved aside. Round 5 removed the hole instead.

**`EXDEV` is the normal path here, not an exotic one.** The stage is in the
system temp, which is frequently a different filesystem from the library and
under WSL always is (`/tmp` is ext4, `/mnt/c` is DrvFs), and `os.replace`
refuses to cross filesystems. So the fallback is explicit: copy into the
**target's own directory** under a unique dot-name, then `os.replace` from
there — same directory, therefore same filesystem, therefore the step that
actually lands the footprint is still one atomic rename. The temporary is
unlinked on any failure, including an interrupt. It cannot be mistaken for a
footprint (leading dot, `.tmp` suffix; everything that reads a `.pretty` globs
`*.kicad_mod`), and it is *inside* the library, which is the directory the
`-o` guard checks.

**A run either installed a piece or it did not, and that is read off the
disk.** The digest of the staged content is taken before the install and
compared against what is in the library afterwards — the same answer whether
the loop ran to the end, stopped on an `OSError` half way, or was abandoned by
a `Ctrl-C`. An install error stops at that piece: the pieces before it *are*
installed and say so, the pieces after it are marked `NOT INSTALLED` and say
that the footprint already in the library is untouched. Round 4 marked every
`ADDED`/`UPDATED` row failed on any install error *and* appended a rollback
promise to each; both halves were wrong at once.

A `Ctrl-C` exits `130` and still says what it did: which footprints hold this
run's content, that nothing is missing, and that the journal was **not**
written and so does not describe that run. That last point is the only lasting
consequence left of an interrupt, and it is safe by construction — provenance
falls back to the `emit_art` stamp inside the `(descr)`, so a footprint
installed but not journalled is still recognised as this tool's own.

### Everything this tool writes, enumerated

"The `-o` guard covers what this tool writes" is only worth saying if `-o` is
the whole list. Round 4 said it while the stage, the undo directory *and* the
journal were all landing in `lib.parent`, outside the checked path. Two of the
three no longer exist; the third is now checked rather than asserted about.

| # | path | checked by |
|---|---|---|
| 1 | `LIB.pretty/` | the `-o` guard |
| 2 | `LIB.pretty/NAME.kicad_mod` | inside 1 |
| 3 | `LIB.pretty/.NAME.kicad_mod.XXXX.tmp` — the cross-device install temporary, unlinked on failure | inside 1 |
| 4 | `LIB.pretty.build.json`, or `--journal` | **its own** containment check |
| 5 | `$TMPDIR/build_library_XXXX/` — the emit staging file and `emit_art --report-json` | OS-owned temp, on no working tree |

`verify_art` is imported rather than spawned and shells out to `kicad-cli`
against its own `tempfile.TemporaryDirectory` — category 5.

The journal stays a **sibling** of the library on purpose: `kicad-cli fp
upgrade -o` copies only `.kicad_mod` files, so anything kept inside a `.pretty`
is silently lost the first time somebody upgrades it. A sibling of an ignored
path is not an ignored path, so a `.gitignore` that names only the library
leaves the journal tracked, and the run is refused with the three ways on —
ignore the parent directory (which covers both), point `--journal` elsewhere,
or pass `--allow-tracked-library`.

### The `check-ignore` trap, in both directions

`git check-ignore` decides whether a **directory-only** pattern (`Lib.pretty/`)
can match a path by *statting* it. `-o` is checked before the library is
created, so round 4's single no-slash invocation reported NO MATCH while the
directory was absent, refused the run — and then a bare `mkdir Lib.pretty`
made the identical command succeed, against a `--help` that promises the
library is "Created if absent".

Measured, all four combinations, git 2.43.0:

| `.gitignore` | directory | query | `check-ignore` |
|---|---|---|---|
| `Lib.pretty/` | absent | `Lib.pretty` | **NO MATCH** ← the false refusal |
| `Lib.pretty/` | absent | `Lib.pretty/` | match |
| `Lib.pretty/` | present | `Lib.pretty` | match |
| `Lib.pretty/` | present | `Lib.pretty/` | match |
| `Lib.pretty` | absent | `Lib.pretty` | match |
| `Lib.pretty` | absent | `Lib.pretty/` | match |
| `Lib.pretty` | present | `Lib.pretty` | match |
| `Lib.pretty` | present | `Lib.pretty/` | match |

So for a **directory** the slash form is right in all four, and both forms are
asked anyway — one `check-ignore` invocation is not trusted to settle this.
The `is_dir` flag is passed, never guessed: the slash form *asserts* to git
that a path is a directory, so asking it about a **file** would let `X/` be
read as ignoring the file `X` — a false *allow*, the dangerous direction. The
library is a directory by contract; the journal is a file.

And a match is only believed when git names a **non-empty pattern** in its
`-v` output. An exit code alone cannot distinguish "a rule you wrote matches
this" from any other route to `0`, and "the exit code was 0" is how
SatoshiStarter went three rounds believing in a rule it did not have. Verify
by hand the same way:

```bash
git check-ignore -v -- output/RecklessArt.pretty/      # a directory
git check-ignore -v -- output/RecklessArt.pretty.build.json   # a file
```

Read the pattern field, not just `$?`. (And beware `$?` after a pipeline — it
is the *last* command's status, not `git`'s.)

**Names collide loudly.** On Windows and macOS the filesystem *loses* one of
`Logo.svg` / `logo.png` **without an error** — measured on this machine:
writing `Logo_20mm.kicad_mod` then `logo_20mm.kicad_mod` leaves one file, named
`Logo_20mm.kicad_mod`, holding the second file's bytes. The refusal message
**probes** the filesystem it is about to write to rather than asserting this;
on case-sensitive ext4 it says so, and explains that the pair still collides
on the filesystems the library is also opened on. The tool keeps its own
case-folded registry, refuses before emitting anything, and never auto-suffixes
(`_1`, `_2`), because an auto-suffix makes a footprint's identity a function of
directory-walk order — the same two files could swap names next run and every
board that placed them would silently get the other picture.

**Third-party art stays out of the repo.** Sources are read-only — *nothing*
is written into a source directory; and the footprint's `descr` records the
source **basename** only, never a path.

**`-o` is the path that is guarded.** Every footprint installed there is
derived from a source image, this corpus includes third-party and brand
material, and a git working tree is a thing that gets pushed. So an output
library inside a working tree that does **not** ignore it is refused, before
anything is probed or created:

```
build_library: -o docs/Guard.pretty: that is inside the git working tree
/…/kicad_art_generator, and git does not ignore it.
THIS IS WHERE THE ARTWORK LANDS. …
Three ways on:
  * add the library to /…/kicad_art_generator/.gitignore, if these footprints
    are build output;
  * point -o outside the checkout;
  * pass --allow-tracked-library, if this library is MEANT to be tracked …
```

The rule is *not ignored*, not *not in a repo*: `output/MyArt.pretty` and
`library/RecklessArt.pretty` inside this checkout are both accepted, because
`output/` and `library/` are ignored. With no `git` on the machine the rule
cannot fire at all, so it is a guard and not a guarantee.

**`--allow-tracked-library` is for the case that is genuinely legitimate.**
`SatoshiStarter/RecklessArt.pretty` is **tracked on purpose**, in a **private**
repo, and it has to keep working:

```bash
python3 tools/build_library.py art/ \
    -o ~/Documents/GitHub/SatoshiStarter/RecklessArt.pretty \
    --allow-tracked-library
```

That is why the way through is a flag the user types, and not a heuristic
trying to guess which checkouts are private.

This check existed in round 3 — for **previews only**. `_git_toplevel` and
`_git_ignores` were written, tested, and called from exactly one place: the
preview-directory guard. The library, the one directory this tool definitely
fills with derived artwork, had no containment check of any kind, and a run
straight into a tracked path of the real public repo with real MFB art exited
`0` without a word.

---

## Why previews and `--regenerate` were removed

Three hardening rounds did not converge. The defect count rotated instead of
falling: each round fixed the named bugs and the next pass found new paths
through the *same* two subsystems. Every unresolved defect traced back to
features that were never asked for. What was actually asked for was this:

> "I think we should be able to point it at a file or a directory, and then
> pass it an output filename for a library, it is okay if we just re-generate
> the whole library, but I would prefer to update & append footprints in it."
>
> "I would like footprint library maintenance to be relatively straightforward
> without an agent."

### Previews

A preview is a clean, recognisable **colour render of the source artwork** — a
verifier opened one out of `AdvLib.pretty.previews/` and identified the MFB
character from it directly. Consent to place a mark on a board is not
permission to redistribute the art. Rendering one on every run therefore
needed containment the tool never got right:

* a render of real MFB art was planted in a **tracked** location of a public
  repo;
* the stage lived **inside** the library and a render was made for **every**
  piece on **every** run, so the tool could discover its own output — run 1 →
  `alpha_20mm`, run 2 → `alpha_20mm_20mm`, run 3 → `alpha_20mm_20mm_20mm`,
  three identical commands, exit `0` each time, and still reproducible with no
  `--preview-dir` given at all;
* the art-tree rule grew to refuse a destination inside a source directory *or
  its parent*, which refuses the ordinary `work/art/` + `work/out/` sibling
  layout — and `journal["source_dirs"]` remembered it, making that refusal
  **permanent** for that library, with no command line able to clear it;
* `_place_previews` did its `mkdir` **after** `committed = True`, so an
  `OSError` there escaped `run()` and `main()` and killed the process before
  the journal write and the summary.

None of that is a preview bug. It is the cost of the tool producing a second
kind of artefact at all. **So it does not.** This tool writes no image
anywhere, which is what actually closes the self-ingestion loop: not a marker
file and not a path rule, but having no render to ingest. `emit_art.py
--preview` still exists and you aim it yourself.

`--preview` stays on the **reserved** `--emit-arg` list even so. It is the one
emit_art flag that writes a colour render of the source art to an arbitrary
path, and there is no destination guard left to catch where it lands:

```
$ build_library.py art/logo.svg -o out/L.pretty --emit-arg=--preview=/tmp/leak.png
build_library: --emit-arg: --preview is owned by build_library — a preview is
a colour render of the SOURCE artwork; this tool writes no images at all …
```

### `--regenerate`

The owner said a full regenerate would be an **acceptable fallback** and that
append was preferred. Append is what the tool does, and it works — so the
fallback was never needed. What `--regenerate` actually implemented was
something else: a journal-driven garbage collector that deleted every
footprint it believed this tool had produced and this run had not.

* it produced **unrecoverable deletions in two successive rounds** — round 2
  deleted with a bare `unlink()` and printed *"nothing was deleted"* over the
  files it had destroyed; round 3 could be killed after its deletions had
  become irreversible;
* it decided what to delete with `is_ours()`, and **`is_ours()` cannot tell
  this tool's work from any other emit_art output.** `emit_art.py` stamps
  `kicad_art_generator/emit_art.py` into every `descr` it writes, so a
  footprint somebody produced by running `emit_art.py` by hand reads as this
  tool's own and was in scope to be deleted. That is not fixable inside this
  tool: the stamp identifies the *emitter*, not the caller;
* it was the entire reason for `--allow-unverified-regenerate`, the
  `doomed`/`kept_foreign` split, `_announce_deletions`, `_remove_footprint`,
  the `deleted` audit state, and a large branch of the summary.

The replacement is a command the owner can already type, aimed at a path the
owner named, run by a tool that does not have to guess whose art it is:

```bash
rm -r out/MyArt.pretty && python3 tools/build_library.py art/ -o out/MyArt.pretty
```

That *is* "re-generate the whole library", and it is the reading of the
request that does not require this tool to hold a deletion power it cannot
aim safely.

---

## Naming---

## Naming

```
footprint_name = [--prefix] + slug(sidecar `name`, else the file stem) + "_" + size
size           = "20mm", "12p5mm"   # '.' -> 'p'
```

`slug()` NFC-normalises, keeps `[A-Za-z0-9_-]`, collapses every other run to a
single `_`, and **preserves the author's case**.

KiCad is not the constraint — `logo.v2_20mm`, `my logo 20mm`, `café_20mm`,
`商標_20mm`, `logo#1` and a trailing space all load, re-serialise and plot
cleanly under kicad-cli 10.0.0. The three real constraints, all measured:

1. **Path length, not name length.** A 180-char name (241-char host path)
   loads; a 200-char name (261-char host path) fails with `Unable to load
   library`. That is Win32 `MAX_PATH` = 260 and it is a property of where the
   *library* sits. The tool budgets `len(host path of lib) + len(name) +
   len(".kicad_mod") + 1 <= 260` and fails the piece with the exact number of
   characters to remove. It never truncates: truncation invents collisions.
2. **Case-insensitivity** (above).
3. **The file stem is authoritative.** `FILESTEM.kicad_mod` containing
   `(footprint "OTHER")` loads without complaint, and `fp upgrade` silently
   rewrites it to `FILESTEM`, at which point the descr's provenance line is a
   lie and `fp export svg --footprint OTHER` cannot find it. So `--name` always
   equals the stem.

Non-ASCII needs `--allow-unicode-names`; otherwise the piece fails with the
offending characters named. Not because KiCad minds, but because the name is a
bare string inside every `.kicad_pcb` that places the footprint.

---

## Per-piece settings: `artlib.toml`

`--help-options` prints the full schema. The short version:

```toml
schema = 1

[defaults]
sizes    = [12, 20]
min_area = "auto"

["reckless_black.svg"]           # section key is the source FILENAME
name = "reckless_mono"
emit = ["--ink-tone", "T1"]

["satoshi_miner.png"]
min_area = 0.10                  # measured; "auto" leaves 0.027 mm slivers

["*.jpg"]                        # glob sections allowed, longest wins
emit = ["--smooth", "1.0"]
```

Precedence: **CLI flag > exact filename > longest glob > `[defaults]` >
built-in**. `emit` lists concatenate weakest-first, so a per-piece flag beats a
run-wide one the way argparse resolves a duplicate.

It lives with the **art**, not in the library, because `kicad-cli fp upgrade
-o` copies only `*.kicad_mod` — anything kept inside a `.pretty` evaporates the
first time somebody upgrades it into a new directory. (The journal is written
beside the library for the same reason.) And `assets/` is gitignored, so a
sidecar next to the art cannot leak into this public repo.

Two things are **hard errors**, because the alternative is a silent wrong
build: an unknown key (a typo'd `size = 20` that quietly does nothing), and a
section matching no source (art was renamed or moved and its flags are now
being applied to nothing).

Why a sidecar and not flags, a filename convention, or auto-detection: the
existing manifest needs 4 non-default names, 2 `--ink-tone T1`, sizes from 10
to 90 mm and four different min-area values. Encoding flags in filenames would
make the footprint name a function of the flags — change a flag, orphan every
board that placed the old name. Auto-detection is used in exactly one place,
where it is safe by construction (below).

---

## The two guards worth knowing

### `--min-area auto`, budgeted at 1 % of ink

`auto` is the default: it drops regions below each tone's own minimum fabricable
feature squared. On `reckless_color.svg` at 20 mm that is 460 polys / 108,504 B
/ verify WARN → 13 polys / 4,356 B / verify PASS, because **447 of 460 regions
were antialias specks**. On clean vector art it costs nothing at all —
`examples/bitcoin_b.svg` is byte-identical with and without.

But it is not universally right, and the guard is what makes it safe to leave
on. Measured across the corpus:

| piece · size | dropped, as % of ink |
|---|---|
| `bitcoin_b.svg` 10/16 mm | 0.000 % |
| `mfb_lockup_white.svg` 20 mm | 0.0002 % |
| `reckless_color.svg` 20 mm | 0.053 % |
| `satoshi_miner.png` 20 mm | 0.409 % |
| **`bitcoin_emission_formula.svg` 12 mm** | **3.632 %** |
| **`bitcoin_emission_formula.svg` 8 mm** | **13.887 %** |

Speck removal costs under half a percent; real stroke loss costs several. The
corpus separates cleanly either side of **1 %**, which is `--max-dropped-pct`.
Over budget, the piece **fails** with the numbers and the two real remedies:
raise `--size`, or set `min_area` for that piece. Do not raise the budget.

`--allow-dropped-tones` is coupled to a nonzero min-area and on with it —
without it a raster piece cannot build at all — and every dropped tone is
listed in the summary, so "allowed" never means "unmentioned". The line reads:

```
DROPPED T2: 1 region(s), 0.000890 mm2 (tone total 104,502 px = 0.9660 mm2)
DROPPED TOTAL 1 region(s), 0.000890 mm2 of 0.9660 mm2 of ink = 0.092%
```

The two numbers on the first line mean different things and are now labelled
as such. It used to print `DROPPED T2 (104,502 px, 1 region(s)) -- 0.092% of
ink`, where the pixel count was emit_art's census of the **whole tone**, not of
what was dropped — a 0.00089 mm² loss reading as 104,502 px, on the guard this
design leans on hardest.

### The T5 trap

T5 is the black solder mask: **T5 draws nothing, because T5 *is* the board.**
Black line art quantised on its own merits lands entirely on T5 and the artwork
silently disappears.

* **Total wipeout is a hard refusal.** `emit_art` exits 3 and writes nothing.
* **One automatic retry, safe by construction.** The piece is re-emitted once
  with `--ink-tone T1` (silk white), which is how you would actually fabricate
  it. This cannot damage colour art: `emit_art` itself refuses `--ink-tone` on
  anything with more than one tone (exit 2, nothing written). The piece is
  reported as `INVERTED`, never as a plain success, and the inversion is
  written into the footprint's `descr` where a reader in the KiCad library
  browser meets it. Disable with `--no-ink-fallback`.
* **The partial case is reported, not guessed at.** A subject only *partly* on
  T5 still emits geometry and exits 0. No threshold can catch it:
  `reckless_color.svg` legitimately puts **63.7 %** of its opaque pixels on T5
  (that is the black field of the logo, and it verifies PASS) while
  `mfb_node_full.svg` sits at 11.9 % and `satoshi_miner.png` at 19.2 %. So
  every row carries `T5 <n> px (<x>% of opaque)` and names
  `--silhouette-tone` / `--ink-tone`. To see a partial wipeout in two seconds
  without opening KiCad, render that one piece yourself —
  `emit_art.py … --preview /tmp/check.png` — and put the PNG somewhere outside
  the art and outside a public tree.

---

## Failure policy

| flag | behaviour |
|---|---|
| `--on-fail skip` *(default)* | the failing piece is not installed, the run continues, the previous good footprint stays put |
| `--on-fail abort` | stop at the first failure and install nothing; the library ends byte-identical to how it started |
| `--on-fail write` | install it anyway and stamp the failure into the `descr`. **Still exits 1** |

The exit code reports the worst *result*, not the worst disk outcome — a run
that installed known-bad art under `--on-fail write` is still exit 1.

`--strict` makes verify `WARN` and `SKIP` failures, so they are refused
installation like any other failure. It is enforced here as well as inside
`verify_art`, so the guarantee does not depend on how the verdict is computed
downstream.

---

## The flags that let you do something dangerous

Each of these exists because the safe default is a refusal, and a refusal with
no way through is a tool you route around.

| flag | what it unlocks | why it is off by default |
|---|---|---|
| `--overwrite-foreign` | overwrite footprints this tool did not produce | `art_hex_asic_window` and `art_btc_whitepaper_b` are irreplaceable by this tool and collide with plausible image names |
| `--allow-tracked-library` | an output library inside a git working tree that does not ignore it | `-o` is where derived artwork lands, and a working tree gets pushed — but `SatoshiStarter/RecklessArt.pretty` is tracked on purpose, in a private repo |
| `--on-fail write` | install a piece that failed acceptance | the failure is stamped in the `descr`; exit is still 1 |
| `--no-verify` | build without `kicad-cli` | this is how 21 layers of vacuous PASS happened |

---

## Worked example

Three runs against the read-only archive in
`SatoshiStarter/art-assets/`, into a library seeded with one hand-made
footprint that no image run produces:

```
A. single file  -> fresh library : 2 ADDED, 1 UNTOUCHED, exit 0
B. directory    -> same library  : 4 ADDED, 1 FAILED, 3 UNTOUCHED, exit 1
C. re-run of A                   : 2 UNCHANGED, 5 UNTOUCHED, exit 0
```

After C, all seven footprints — the two from A, the four from B, and the
hand-made one — were identical in `sha256` **and** untouched in `mtime`.
`kicad-cli fp upgrade --force` over the finished library exits 0.

The one failure in B is worth reading: `Little Satoshi.png` straight out of the
archive fails `verify geometry: 1 lone outlier`. That is the white matte
`tools/prep_assets.py` exists to key out. The tool refused to install it and
said why, which is the whole point.

---

## Running the tests

```bash
./.venv/bin/python -m pytest tests/test_build_library.py -q
```

141 tests, ~3 m 5 s. Every defect found in the adversarial reviews carries a
regression test that fails before its fix and passes after — provenance,
output-library containment, install atomicity, the abbreviated `--emit-arg`
guard, the WARN detail on stdout, and the rest.

The data-safety ones are worth knowing by name, because they are the tests
that would catch the worst regression this tool has had:

* `TestAnInterruptLeavesEveryFootprintOldOrNew` — a `KeyboardInterrupt`, a
  `SystemExit`, a `MemoryError` and **a real `SIGINT` delivered to a real
  subprocess**, each raised mid-install, must leave every footprint old or new
  and none missing. It also asserts the *cause*: `TestInstallAtomicity`
  watches every `os.replace` and `shutil.copy2` the install makes and requires
  that no path inside the library is ever the **source** of one — the
  incumbent is never displaced, which is why no rollback is needed. And the
  machinery that used to repair holes (`_preserve`, `_undo`, `_audit`,
  `_unwind`, `_sweep_stale_stages`, …) is asserted **absent**, not merely
  unused;
* `TestInstallAtomicity` — an obstructed target stops the install there; the
  pieces before it *are* installed and the journal says so from the disk; the
  rows after it say the footprint already in the library is untouched; and no
  output anywhere claims a rollback. The cross-device path is exercised
  directly, including that its temporary is unlinked when the copy fails;
* `TestOutputLibraryContainment` — `-o` inside a working tree that does not
  ignore it is refused and the library is not even created; an ignored one is
  allowed; `--allow-tracked-library` gets through; the **journal** is guarded
  in its own right; the directory-only-rule false refusal is checked across
  **all four** pattern × directory-presence combinations; a match is only
  believed when git names a non-empty pattern; a whole-working-tree diff
  requires the only new paths to be the library, its footprints and the
  journal; and the **real** `SatoshiStarter/RecklessArt.pretty` path is
  checked both ways without writing a byte into it;
* `TestTheStageIsInTheSystemTemp` — no working directory is created inside the
  library **or beside it**; the library holds nothing but `.kicad_mod` files
  *during* the install as well as after; nothing is left behind for a later
  run to sweep; the tool contains no live `.build_library_*` string, no glob
  other than `*.kicad_mod`, and no `rmtree` at all; and a user directory that
  merely *looks* like the old convention is walked like any other art;
* `TestNothingItWritesIsEverASource` — the `art/` + `out/` sibling layout
  builds three times running, and `journal["source_dirs"]` is gone.

The reproduction test — a sidecar transcribing `render_library.LIBRARY` must
rebuild all 21 of its footprints byte for byte — takes ~35 s of real emits and
is opt-in. It is the check that this scope cut changed no geometry:

```bash
BUILD_LIBRARY_SLOW=1 ./.venv/bin/python -m pytest tests/test_build_library.py -q -k reproduces
```
