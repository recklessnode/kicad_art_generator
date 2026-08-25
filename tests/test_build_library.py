"""Acceptance tests for tools/build_library.py.

The properties that matter here are not "does it produce a footprint" -- that
is emit_art's job and emit_art has its own tests. They are the ones an
unattended maintenance run depends on:

  * IDEMPOTENCE -- a second run over unchanged input writes nothing at all,
    not even an identical byte, so the library does not churn its mtimes and
    re-running does not produce a git diff.
  * APPEND DOES NOT DESTROY -- a footprint this run did not produce survives
    byte for byte and is never even opened. Round 4 removed --regenerate, so
    this is now a property of the tool rather than of one default: there is
    no code path here that deletes a footprint at all.
  * THE ARTWORK STAYS OUT OF A PUBLIC TREE -- -o is where derived art lands,
    and it is refused inside a git working tree that does not ignore it.
  * NOTHING THIS TOOL WRITES CAN BECOME ITS OWN INPUT -- round 4 removed
    preview rendering, so it writes no image anywhere, and round 5 removed the
    persistent staging subsystem, so it creates no working directory in
    anybody's tree either.
  * AN INTERRUPT LEAVES EVERY FOOTPRINT OLD OR NEW -- never missing. The
    incumbent is never moved aside, so there is nothing to restore and no
    rollback that could misreport itself.
  * THE EXIT CODE IS TRUSTWORTHY -- including when --on-fail write installs a
    piece that failed, which must still be exit 1.
  * THE T5 TRAP IS CAUGHT -- black line art on a black-mask board draws
    nothing, and a silently blank footprint is the worst failure mode here.
  * NAMES COLLIDE LOUDLY -- the filesystem on the development machine is
    case-insensitive and loses one of Logo.svg / logo.png WITHOUT AN ERROR.

Source images are generated at test time from the palette's own tone anchors
(tools/w0_spike.TONES), so the suite carries no binary fixtures and no
third-party artwork.
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_library as bl                              # noqa: E402
import verify_art                                       # noqa: E402

PIL = pytest.importorskip("PIL.Image", reason="build_library needs Pillow")
from PIL import Image, ImageDraw                        # noqa: E402

# Tone anchors, straight out of tools/w0_spike.TONES so a change there breaks
# these tests rather than silently repainting the fixtures.
SILK = (235, 235, 230, 255)     # T1, draws on F.SilkS
GOLD = (205, 165, 75, 255)      # T2, draws on F.Cu + F.Mask
BOARD = (25, 25, 28, 255)       # T5, the black mask -- DRAWS NOTHING
CLEAR = (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _png(path: Path, boxes, size=(64, 40)) -> Path:
    im = Image.new("RGBA", size, CLEAR)
    d = ImageDraw.Draw(im)
    for box, colour in boxes:
        d.rectangle(box, fill=colour)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


@pytest.fixture
def art(tmp_path: Path) -> Path:
    """A drop-folder of synthetic art with known tone content."""
    d = tmp_path / "art"
    _png(d / "silk_bar.png", [((8, 8, 55, 31), SILK)])
    _png(d / "gold_bar.png", [((6, 6, 57, 33), GOLD)])
    # Pure T5: quantises entirely onto the colour of the board, so emit_art
    # refuses it as EMPTY OUTPUT (exit 3) unless it is inverted.
    _png(d / "board_bar.png", [((8, 8, 55, 31), BOARD)])
    # One solid bar plus 90 one-pixel specks. MEASURED at --size 6: the content
    # bbox is 60 x 27 px, so mm_per_px = 0.1 and each speck is under T1's own
    # auto floor of 0.15^2 = 0.0225 mm2. emit_art drops all 90 -- 0.3 of the
    # 8.7 mm2 of ink, 3.448% -- which is over the 1% default budget and in the
    # same range as the real counter-example, bitcoin_emission_formula.svg
    # losing 3.632% of its strokes at 12 mm.
    _png(d / "specks.png",
         [((2, 2, 61, 14), SILK)]
         + [((2 + 2 * i, y, 2 + 2 * i, y), SILK)
            for y in (20, 24, 28) for i in range(30)])
    return d


def lib_of(tmp_path: Path, name="Test.pretty") -> Path:
    return tmp_path / name


def run(*argv) -> int:
    return bl.main([str(a) for a in argv])


def snapshot(lib: Path) -> dict[str, tuple[bytes, int, int]]:
    """content + mtime_ns + size for every footprint, so a test can prove a
    file was not merely rewritten identically but not written at all."""
    out = {}
    for f in sorted(lib.glob("*.kicad_mod")):
        st = f.stat()
        out[f.name] = (f.read_bytes(), st.st_mtime_ns, st.st_size)
    return out


def journal(lib: Path) -> dict:
    return json.loads(lib.with_name(lib.name + ".build.json")
                      .read_text(encoding="utf-8"))


def git_tree(tmp_path: Path, ignore: str = "output/\n") -> Path:
    """A real git working tree, because the -o guard shells out to real git."""
    import subprocess                                   # noqa: PLC0415
    if not shutil.which("git"):
        pytest.skip("needs git")
    wt = tmp_path / "checkout"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True,
                   stdin=subprocess.DEVNULL, capture_output=True)
    (wt / ".gitignore").write_text(ignore, encoding="utf-8")
    return wt


def ignores(repo: Path, rel: str) -> bool:
    """git check-ignore, ASKING GIT DIRECTLY and reading the pattern it names.

    Deliberately NOT bl._git_ignores: a test that verifies the tool's rule
    with the tool's own helper verifies nothing. This is the independent
    second opinion, so it runs the raw command and requires git to name a
    NON-EMPTY pattern for the match -- an exit code alone does not say a rule
    exists, and "the exit code was 0" is how SatoshiStarter went three rounds
    believing in a `.build_library_*/` rule it did not have.
    """
    import re as _re                                    # noqa: PLC0415
    import subprocess                                   # noqa: PLC0415
    r = subprocess.run(["git", "check-ignore", "-v", "--", rel], cwd=repo,
                       stdin=subprocess.DEVNULL, capture_output=True,
                       text=True)
    assert r.returncode in (0, 1), r.stderr
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        m = _re.match(r"^(?P<src>.*):(?P<n>\d+):(?P<pat>.*)$",
                      line.split("\t", 1)[0])
        if m and m.group("pat").strip():
            return True
    return False


SATOSHI = Path("/mnt/c/Users/prael/Documents/GitHub/SatoshiStarter")
if not SATOSHI.is_dir():                                # non-WSL checkouts
    SATOSHI = REPO.parent / "SatoshiStarter"


HAVE_KICAD = verify_art.find_kicad_cli(None)
kicad10 = pytest.mark.skipif(
    not HAVE_KICAD.path or HAVE_KICAD.major < verify_art.MIN_KICAD_MAJOR,
    reason=f"needs kicad-cli >= {verify_art.MIN_KICAD_MAJOR}")


# ===========================================================================
# 1. naming
# ===========================================================================

class TestNaming:
    def test_size_suffix_matches_the_existing_corpus(self):
        # output/RecklessArt.pretty holds bitcoin_b_10mm, mfb_lockup_30mm, ...
        assert bl.size_suffix(10) == "10mm"
        assert bl.size_suffix(20.0) == "20mm"
        assert bl.size_suffix(12.5) == "12p5mm"
        assert bl.size_suffix(7.25) == "7p25mm"

    def test_slug_preserves_the_authors_case(self):
        assert bl.slug("Logo") == "Logo"
        assert bl.slug("RecklessSystemsLogoBlack") == "RecklessSystemsLogoBlack"

    def test_slug_collapses_runs_and_strips(self):
        assert bl.slug("Logo MPB Assets-10") == "Logo_MPB_Assets-10"
        assert bl.slug("  a &&& b  ") == "a_b"
        assert bl.slug("logo.v2") == "logo_v2"
        assert bl.slug("__x__") == "x"

    def test_slug_refuses_non_ascii_by_default_and_names_the_character(self):
        with pytest.raises(bl.NameError_) as e:
            bl.slug("café")
        assert "U+00E9" in str(e.value)
        assert "--allow-unicode-names" in str(e.value)

    def test_slug_keeps_non_ascii_when_asked(self):
        assert bl.slug("café", allow_unicode=True) == "café"
        assert bl.slug("商標", allow_unicode=True) == "商標"

    def test_slug_refuses_a_name_with_nothing_in_it(self):
        for empty in ("###", "   ", "_", "..."):
            with pytest.raises(bl.NameError_):
                bl.slug(empty)
        # '-' is in the keep set, so a name made of hyphens is legal, if odd.
        assert bl.slug("---") == "---"

    def test_reserved_dos_device_names_are_refused(self):
        bl.check_reserved("console_20mm")            # not reserved
        for bad in ("CON", "nul", "COM1", "LPT9"):
            with pytest.raises(bl.NameError_):
                bl.check_reserved(bad)

    def test_collision_exits_2_and_writes_nothing(self, tmp_path):
        # THE case the brief asks about. Verified on this machine: writing
        # Logo_20mm.kicad_mod then logo_20mm.kicad_mod leaves ONE file, named
        # Logo_20mm.kicad_mod, containing the second file's bytes -- silent
        # data loss, no error from the OS. The check is case-FOLDED in the
        # tool, so it fires on a case-sensitive filesystem too.
        d = tmp_path / "src"
        _png(d / "Logo.png", [((8, 8, 55, 31), SILK)])
        _png(d / "logo.png", [((6, 6, 57, 33), GOLD)])
        lib = lib_of(tmp_path)
        rc = run(d, "-o", lib, "--size", 10, "--no-verify")
        assert rc == 2
        assert not lib.exists(), "a refused run must not even create the library"

    def test_collision_message_offers_the_three_deterministic_fixes(
            self, tmp_path, capsys):
        d = tmp_path / "src"
        _png(d / "Logo.png", [((8, 8, 55, 31), SILK)])
        _png(d / "logo.png", [((6, 6, 57, 33), GOLD)])
        run(d, "-o", lib_of(tmp_path), "--size", 10, "--no-verify")
        err = capsys.readouterr().err
        assert "COLLISION" in err
        assert "rename a source" in err and "--prefix" in err and "sidecar" in err
        assert "not auto-suffixed" in err
        assert "directory-walk order" in err, \
            "the message must say WHY an auto-suffix is refused"

    def test_prefix_resolves_a_collision(self, tmp_path):
        d1, d2 = tmp_path / "a", tmp_path / "b"
        _png(d1 / "x.png", [((8, 8, 55, 31), SILK)])
        _png(d2 / "x.png", [((6, 6, 57, 33), GOLD)])
        assert run(d1, d2, "-o", lib_of(tmp_path), "--size", 10,
                   "--no-verify") == 2
        lib = lib_of(tmp_path, "P.pretty")
        assert run(d1, "-o", lib, "--size", 10, "--no-verify") == 0
        assert run(d2, "-o", lib, "--size", 10, "--prefix", "b_",
                   "--no-verify") == 0
        assert {f.stem for f in lib.glob("*.kicad_mod")} == {"x_10mm", "b_x_10mm"}

    def test_collision_with_an_existing_library_file_of_different_case(
            self, tmp_path, capsys):
        lib = lib_of(tmp_path)
        lib.mkdir()
        (lib / "Silk_bar_10mm.kicad_mod").write_text(
            '(footprint "Silk_bar_10mm")', encoding="utf-8")
        d = tmp_path / "src"
        _png(d / "silk_bar.png", [((8, 8, 55, 31), SILK)])
        rc = run(d, "-o", lib, "--size", 10, "--no-verify")
        assert rc == 2
        assert "COLLISION with the existing library" in capsys.readouterr().err

    def test_path_budget_fails_with_the_character_count(self, tmp_path, capsys):
        host = bl.host_path(lib_of(tmp_path))
        if not bl.is_windows_host(host):
            pytest.skip("MAX_PATH is a Win32 property; this path is POSIX")
        room = bl.MAX_PATH - len(host) - 1 - len(".kicad_mod") - len("_10mm")
        d = tmp_path / "src"
        _png(d / ("z" * (room + 5) + ".png"), [((8, 8, 55, 31), SILK)])
        lib = lib_of(tmp_path)
        assert run(d, "-o", lib, "--size", 10, "--no-verify") == 2
        err = capsys.readouterr().err
        assert "PATH TOO LONG" in err
        assert "Remove 5 character(s)" in err
        assert "never truncated" in err
        assert not lib.exists()


# ===========================================================================
# 2. sidecar
# ===========================================================================

class TestSidecar:
    def _write(self, tmp_path, body) -> Path:
        p = tmp_path / bl.SIDECAR_NAME
        p.write_text(body, encoding="utf-8")
        return p

    def test_unknown_key_is_a_hard_error(self, tmp_path):
        p = self._write(tmp_path, 'schema = 1\n["a.png"]\nsize = 20\n')
        with pytest.raises(bl.SidecarError) as e:
            bl.load_sidecar(p, tmp_path, True)
        assert "unknown key(s)" in str(e.value) and "size" in str(e.value)

    def test_missing_or_wrong_schema_is_refused(self, tmp_path):
        with pytest.raises(bl.SidecarError, match="missing"):
            bl.load_sidecar(self._write(tmp_path, '[defaults]\nsizes=[20]\n'),
                            tmp_path, True)
        with pytest.raises(bl.SidecarError, match="not supported"):
            bl.load_sidecar(self._write(tmp_path, 'schema = 2\n'), tmp_path, True)

    def test_a_reserved_emit_argument_is_refused(self, tmp_path):
        p = self._write(tmp_path,
                        'schema = 1\n["a.png"]\nemit = ["--name", "sneaky"]\n')
        with pytest.raises(bl.SidecarError) as e:
            bl.load_sidecar(p, tmp_path, True)
        assert "--name is owned by build_library" in str(e.value)

    def test_name_is_refused_where_it_would_collide(self, tmp_path):
        with pytest.raises(bl.SidecarError, match="not allowed in \\[defaults\\]"):
            bl.load_sidecar(self._write(tmp_path, 'schema=1\n[defaults]\nname="x"\n'),
                            tmp_path, True)
        with pytest.raises(bl.SidecarError, match="glob section"):
            bl.load_sidecar(self._write(tmp_path, 'schema=1\n["*.png"]\nname="x"\n'),
                            tmp_path, True)

    def test_precedence_exact_beats_longest_glob_beats_defaults(self, tmp_path):
        # The flags here are real emit_art flags this tool does not own.
        # Placeholders like "--d" are no longer usable: --d abbreviates to
        # --descr, which build_library owns, and the guard now catches that.
        p = self._write(tmp_path, """
schema = 1
[defaults]
sizes = [8]
emit  = ["--uuids"]
["*.png"]
sizes = [9]
emit  = ["--crop"]
["silk*.png"]
sizes = [10]
emit  = ["--no-crop"]
["silk_bar.png"]
name  = "chosen"
sizes = [11]
emit  = ["--smooth"]
""")
        sc = bl.load_sidecar(p, tmp_path, True)
        got, _ = bl.resolve_settings(tmp_path / "silk_bar.png", [sc])
        assert got["sizes"] == [11.0]
        assert got["name"] == "chosen"
        # emit CONCATENATES, weakest first, so the last flag wins the way
        # argparse resolves a duplicate.
        assert got["emit"] == ["--uuids", "--crop", "--no-crop", "--smooth"]
        other, _ = bl.resolve_settings(tmp_path / "gold_bar.png", [sc])
        assert other["sizes"] == [9.0]
        assert other["emit"] == ["--uuids", "--crop"]

    def test_min_area_forms(self, tmp_path):
        n = bl._norm_min_area
        assert n("auto", "w") == "auto"
        assert n("NONE", "w") == "none"
        assert n(0, "w") == "none"
        assert n(0.09, "w") == repr(0.09)
        assert n("0.09", "w") == repr(0.09)
        for bad in (-1, "banana", True, [1]):
            with pytest.raises(bl.SidecarError):
                n(bad, "w")

    def test_a_section_matching_no_source_is_a_hard_error(self, art, tmp_path):
        (art / bl.SIDECAR_NAME).write_text(
            'schema = 1\n["renamed_away.png"]\nsizes = [10]\n', encoding="utf-8")
        lib = lib_of(tmp_path)
        assert run(art, "-o", lib, "--no-verify") == 2
        assert not lib.exists()

    def test_that_error_is_only_a_note_when_the_run_was_narrowed(
            self, art, tmp_path, capsys):
        (art / bl.SIDECAR_NAME).write_text(
            'schema = 1\n["silk_bar.png"]\nsizes = [10]\n'
            '["gold_bar.png"]\nsizes = [10]\n', encoding="utf-8")
        lib = lib_of(tmp_path)
        rc = run(art / "silk_bar.png", "-o", lib, "--no-verify")
        assert rc == 0
        out = capsys.readouterr().out
        assert "matching no source" in out and "note, not an error" in out

    def test_no_options_ignores_the_sidecar(self, art, tmp_path):
        (art / bl.SIDECAR_NAME).write_text(
            'schema = 1\n["nope.png"]\nsizes=[10]\n', encoding="utf-8")
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--no-options",
                   "--size", 10, "--no-verify") == 0

    def test_a_reserved_emit_arg_on_the_command_line_is_refused(
            self, art, tmp_path, capsys):
        assert run(art / "silk_bar.png", "-o", lib_of(tmp_path), "--size", 10,
                   "--no-verify", "--emit-arg=--output=/tmp/x") == 2
        assert "owned by build_library" in capsys.readouterr().err


# ===========================================================================
# 3. discovery and usage
# ===========================================================================

class TestDiscovery:
    def test_no_sources_exits_3(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert run(tmp_path / "empty", "-o", lib_of(tmp_path),
                   "--no-verify") == 3

    def test_a_missing_source_exits_2(self, tmp_path):
        assert run(tmp_path / "nope.png", "-o", lib_of(tmp_path),
                   "--no-verify") == 2

    def test_output_must_be_a_pretty_directory(self, art, tmp_path, capsys):
        assert run(art / "silk_bar.png", "-o", tmp_path / "Lib",
                   "--no-verify") == 2
        assert ".pretty" in capsys.readouterr().err

    def test_subdirectories_are_named_not_silently_skipped(
            self, art, tmp_path, capsys):
        (art / "deeper").mkdir()
        _png(art / "deeper" / "inner.png", [((8, 8, 55, 31), SILK)])
        run(art / "silk_bar.png", art, "-o", lib_of(tmp_path), "--size", 10,
            "--no-verify")
        assert "skipped sub-directory (no --recursive)" in capsys.readouterr().out

    def test_recursive_finds_the_inner_file(self, art, tmp_path):
        (art / "deeper").mkdir()
        _png(art / "deeper" / "inner.png", [((8, 8, 55, 31), SILK)])
        lib = lib_of(tmp_path)
        assert run(art / "deeper", "-o", lib, "--size", 10, "--recursive",
                   "--no-verify") == 0
        assert (lib / "inner_10mm.kicad_mod").exists()


# ===========================================================================
# 4. idempotence and append -- the two hard requirements
# ===========================================================================

class TestIdempotenceAndAppend:
    def test_second_run_writes_nothing_at_all(self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", art / "gold_bar.png", "-o", lib,
                   "--size", 10, "--size", 16, "--no-verify") == 0
        first = snapshot(lib)
        assert len(first) == 4
        assert all(p["state"] == "ADDED" for p in journal(lib)["pieces"])

        assert run(art / "silk_bar.png", art / "gold_bar.png", "-o", lib,
                   "--size", 10, "--size", 16, "--no-verify") == 0
        second = snapshot(lib)
        assert second == first, "bytes, size AND mtime must all be unchanged"
        j = journal(lib)
        assert [p["state"] for p in j["pieces"]] == ["UNCHANGED"] * 4
        assert j["installed"] == [], "an unchanged piece is not written at all"

    def test_a_changed_source_reports_updated(self, art, tmp_path):
        lib = lib_of(tmp_path)
        run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify")
        before = snapshot(lib)
        _png(art / "silk_bar.png", [((2, 2, 61, 37), SILK)])   # bigger bar
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert journal(lib)["pieces"][0]["state"] == "UPDATED"
        assert snapshot(lib) != before

    def test_append_leaves_a_foreign_footprint_byte_identical(self, art, tmp_path):
        # SatoshiStarter/RecklessArt.pretty really does hold
        # art_hex_asic_window.kicad_mod and mfb_logo_20mm/30mm, which no
        # image-driven run produces. A tool that "regenerates" by default
        # deletes them.
        lib = lib_of(tmp_path)
        lib.mkdir()
        foreign = lib / "art_hex_asic_window.kicad_mod"
        foreign.write_text('(footprint "art_hex_asic_window" (version 20241229))',
                           encoding="utf-8")
        before = (foreign.read_bytes(), foreign.stat().st_mtime_ns)

        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert (foreign.read_bytes(), foreign.stat().st_mtime_ns) == before
        j = journal(lib)
        assert j["untouched"] == ["art_hex_asic_window"]
        assert "removed" not in j, \
            "there is no delete path left, so there is no deletion to record"

    def test_there_is_no_flag_that_deletes_a_footprint(self, art, tmp_path):
        """--regenerate was removed in round 4. The owner asked for
        update-and-append and said a full regenerate would be an acceptable
        FALLBACK; that is not a request for a journal-driven garbage
        collector, and append is what the tool does. It produced unrecoverable
        deletions in two successive rounds, and it decided what to delete with
        is_ours(), which cannot tell this tool's output from ANY emit_art
        output -- so a footprint somebody made by running emit_art by hand was
        in scope to be deleted."""
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10, "--size", 16,
                   "--no-verify") == 0
        mine = lib / "silk_bar_16mm.kicad_mod"
        before = (mine.read_bytes(), mine.stat().st_mtime_ns)

        # No option string anywhere in the parser deletes anything.
        strings = []
        for act in bl.build_parser()._actions:
            strings += list(act.option_strings)
        assert not [s for s in strings if "regenerate" in s], strings

        # ...and the flag is genuinely gone, not merely undocumented.
        with pytest.raises(SystemExit):
            run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify",
                "--regenerate")

        # A narrower run over one size still leaves the other exactly alone.
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert (mine.read_bytes(), mine.stat().st_mtime_ns) == before

    def test_a_rebuild_is_the_user_deleting_the_directory(self, art, tmp_path):
        """The documented replacement, exercised: remove the .pretty and run
        again. It is a full regenerate, aimed by the user at a path the user
        named, by a tool that does not have to guess whose art it is."""
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10, "--size", 16,
                   "--no-verify") == 0
        assert len(list(lib.glob("*.kicad_mod"))) == 2
        shutil.rmtree(lib)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert {f.stem for f in lib.glob("*.kicad_mod")} == {"silk_bar_10mm"}

    def test_dry_run_installs_nothing(self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   "--dry-run") == 0
        assert not lib.exists()
        assert not lib.with_name(lib.name + ".build.json").exists()


# ===========================================================================
# 5. the T5 trap
# ===========================================================================

class TestT5:
    def test_pure_board_colour_fails_and_writes_nothing(
            self, art, tmp_path, capsys):
        lib = lib_of(tmp_path)
        rc = run(art / "board_bar.png", "-o", lib, "--size", 10, "--no-verify",
                 "--no-ink-fallback")
        assert rc == 1
        assert list(lib.glob("*.kicad_mod")) == []
        out = capsys.readouterr().out
        assert "EMPTY OUTPUT" in out
        assert "--no-ink-fallback" in out

    def test_the_fallback_inverts_it_and_says_so(self, art, tmp_path, capsys):
        lib = lib_of(tmp_path)
        assert run(art / "board_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        f = lib / "board_bar_10mm.kicad_mod"
        assert f.exists()
        p = journal(lib)["pieces"][0]
        assert p["inverted"] is True and p["label"] == "INVERTED"
        assert p["polys"] > 0
        # The inversion must be discoverable in the KiCad library browser, not
        # only in the journal.
        assert "INVERTED BY build_library" in f.read_text(encoding="utf-8")
        assert "F.SilkS" in f.read_text(encoding="utf-8")
        assert "INVERTED" in capsys.readouterr().out

    def test_a_partial_t5_field_is_reported_and_now_also_measured(
            self, tmp_path):
        # THIS TEST CHANGED, and the reason is the whole point of the fidelity
        # metric. It used to assert exit 0, on the argument that no threshold
        # separates a real trap from correct art -- reckless_color legitimately
        # puts 63.7% of its opaque pixels on T5 and verifies PASS, while
        # mfb_node_full sat at 11.9% and was mutilated. That argument was
        # right about the T5 CENSUS and wrong about the question: the census
        # counts pixels that landed on a tone, and what matters is whether the
        # picture survived. tools/fidelity.py measures that directly by
        # overlaying the emitted polygons on the source, and here it says half
        # the artwork is not on the board. So the number is still reported, the
        # two flags are still named -- and the piece no longer installs.
        d = tmp_path / "src"
        _png(d / "mixed.png", [((2, 2, 61, 20), BOARD), ((2, 22, 61, 37), SILK)])
        lib = lib_of(tmp_path)
        assert run(d, "-o", lib, "--size", 10, "--no-verify") == 1
        p = journal(lib)["pieces"][0]
        assert p["t5_px"] > 0
        assert 0 < p["t5_pct_of_opaque"] < 100
        assert any("T5 IS the board" in n for n in p["notes"])
        assert any("--silhouette-tone" in n for n in p["notes"])
        assert any("FIDELITY" in x for x in p["problems"]), p["problems"]
        assert p["fidelity"]["undrawn_pct"] > 40.0, p["fidelity"]
        assert list(lib.glob("*.kicad_mod")) == []

    def test_allow_empty_cannot_be_smuggled_in_through_emit_arg(
            self, art, tmp_path, capsys):
        lib = lib_of(tmp_path)
        rc = run(art / "board_bar.png", "-o", lib, "--size", 10, "--no-verify",
                 "--no-ink-fallback", "--emit-arg=--allow-empty")
        assert rc == 2, "the one flag that produces a blank footprint is refused"
        assert "refuses a footprint with no geometry" in capsys.readouterr().err
        assert not lib.exists()

    def test_the_blank_guard_fires_on_zero_polygons(self, art):
        # Defence in depth behind that refusal: whatever route a report with no
        # geometry arrives by, the piece does not reach the library.
        res = bl.Result(piece=bl.Piece(art / "x.png", 10.0, "x_10mm", "auto",
                                       [], None, []))
        res.polys = 0
        bl._guard(res, bl.build_parser().parse_args(
            ["x.png", "-o", "L.pretty"]))
        assert any("BLANK FOOTPRINT" in p for p in res.problems)


# ===========================================================================
# 6. the dropped-area budget
# ===========================================================================

class TestDroppedArea:
    def test_over_the_default_budget_fails_with_the_numbers(
            self, art, tmp_path, capsys):
        lib = lib_of(tmp_path)
        rc = run(art / "specks.png", "-o", lib, "--size", 6, "--no-verify")
        assert rc == 1
        assert list(lib.glob("*.kicad_mod")) == []
        out = capsys.readouterr().out
        assert "SPECK-REMOVAL BUDGET (emitter-reported)" in out
        # The rename is load-bearing: this budget reads `area_dropped` out of
        # emit_art's own report, so it is the emitter's opinion of itself and
        # must not be read as a fidelity number. tools/fidelity.py is what
        # measures the picture, and it is a separate gate.
        assert "not a fidelity measurement" in out
        assert "do not raise --max-dropped-pct" in out
        assert "Raise --size" in out

    def test_raising_the_speck_budget_does_not_buy_a_pass(self, art, tmp_path):
        # The speck budget and the acceptance metric are INDEPENDENT gates, and
        # this fixture proves they have to be. --max-dropped-pct 90 satisfies
        # the emitter-reported budget outright; the overlay then measures 90 of
        # 870 opaque source pixels with no polygon over them -- 10.3% of the
        # picture missing -- and refuses it anyway. A budget flag cannot talk
        # the fidelity metric out of what it measured.
        lib = lib_of(tmp_path)
        assert run(art / "specks.png", "-o", lib, "--size", 6, "--no-verify",
                   "--max-dropped-pct", 90) == 1
        p = journal(lib)["pieces"][0]
        assert p["dropped_regions"] > 0
        assert p["dropped_pct_of_ink"] > 0
        assert p["dropped"], "every dropped tone is listed, never merely allowed"
        assert not any("SPECK-REMOVAL BUDGET" in x for x in p["problems"]), \
            "the budget itself passed at 90%"
        assert any("FIDELITY" in x for x in p["problems"]), p["problems"]
        assert p["fidelity"]["undrawn_pct"] > 5.0, p["fidelity"]

    def test_min_area_none_drops_nothing(self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "specks.png", "-o", lib, "--size", 6, "--no-verify",
                   "--min-area", "none") == 0
        p = journal(lib)["pieces"][0]
        assert p["dropped_regions"] == 0 and p["dropped_pct_of_ink"] == 0


# ===========================================================================
# 7. failure policy and exit codes
# ===========================================================================

class TestFailurePolicy:
    def _mixed(self, art, tmp_path):
        d = tmp_path / "mixed"
        for i in range(4):
            _png(d / f"good{i}.png", [((2 + i, 2, 55, 31), SILK)])
        shutil.copy2(art / "board_bar.png", d / "bad.png")
        return d

    def test_skip_isolates_the_failure_and_keeps_the_previous_version(
            self, art, tmp_path):
        d = self._mixed(art, tmp_path)
        lib = lib_of(tmp_path)
        # Seed a good previous version of the piece that is about to fail.
        _png(d / "bad.png", [((8, 8, 55, 31), SILK)])
        assert run(d, "-o", lib, "--size", 10, "--no-verify") == 0
        prev = (lib / "bad_10mm.kicad_mod").read_bytes()
        shutil.copy2(art / "board_bar.png", d / "bad.png")   # now unbuildable

        rc = run(d, "-o", lib, "--size", 10, "--no-verify", "--no-ink-fallback")
        assert rc == 1
        assert len(list(lib.glob("*.kicad_mod"))) == 5
        assert (lib / "bad_10mm.kicad_mod").read_bytes() == prev, \
            "a failed update must leave the previous good footprint in place"
        j = journal(lib)
        assert j["summary"]["failed"] == 1
        bad = [p for p in j["pieces"] if p["name"] == "bad_10mm"][0]
        assert any("kept the previous footprint" in n for n in bad["notes"])

    def test_abort_leaves_the_library_byte_identical(self, art, tmp_path):
        d = self._mixed(art, tmp_path)
        lib = lib_of(tmp_path)
        lib.mkdir()
        (lib / "pre_existing.kicad_mod").write_text('(footprint "pre_existing")',
                                                    encoding="utf-8")
        before = snapshot(lib)
        rc = run(d, "-o", lib, "--size", 10, "--no-verify", "--no-ink-fallback",
                 "--on-fail", "abort", "--jobs", 1)
        assert rc == 1
        assert snapshot(lib) == before, \
            "--on-fail abort must install nothing at all"

    def test_write_installs_the_failure_and_still_exits_1(self, art, tmp_path):
        lib = lib_of(tmp_path)
        rc = run(art / "specks.png", "-o", lib, "--size", 6, "--no-verify",
                 "--on-fail", "write")
        assert rc == 1, "the exit code reports the worst RESULT, not the disk"
        f = lib / "specks_6mm.kicad_mod"
        assert f.exists()
        assert "FAILED ACCEPTANCE" in f.read_text(encoding="utf-8"), \
            "the failure must be stamped where a reader in KiCad meets it"
        j = journal(lib)
        assert j["summary"]["failed_but_written"] == 1

    def test_exit_0_only_when_everything_passed(self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0


# ===========================================================================
# 8. the verification gate
# ===========================================================================

class TestVerificationGate:
    def _stub(self, tmp_path, version) -> Path:
        p = tmp_path / ("kicad-cli-stub" + (".py" if os.name == "nt" else ""))
        p.write_text(f'#!{sys.executable}\nprint("{version}")\n', encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return p

    @pytest.mark.skipif(os.name == "nt", reason="needs an executable bit")
    def test_a_version_9_cli_refuses_to_start(self, art, tmp_path, capsys):
        stub = self._stub(tmp_path, "9.0.0")
        lib = lib_of(tmp_path)
        rc = run(art / "silk_bar.png", "-o", lib, "--size", 10,
                 "--kicad-cli", stub)
        assert rc == 2
        assert not lib.exists()
        err = capsys.readouterr().err
        assert "9.0.0" in err and "vacuous PASS" not in err.split("\n")[0]
        assert "--no-verify" in err

    def test_a_missing_cli_refuses_to_start(self, art, tmp_path, capsys):
        lib = lib_of(tmp_path)
        rc = run(art / "silk_bar.png", "-o", lib, "--size", 10,
                 "--kicad-cli", tmp_path / "does-not-exist")
        assert rc == 2
        assert "vacuous PASS" in capsys.readouterr().err

    def test_no_verify_marks_every_row_not_verified(self, art, tmp_path, capsys):
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert journal(lib)["pieces"][0]["verify"] == "NOT VERIFIED"
        assert journal(lib)["verified"] is False
        assert "NOT VERIFIED" in capsys.readouterr().out

    @kicad10
    def test_a_verified_piece_carries_its_checks_and_loads_in_kicad(
            self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10) == 0
        p = journal(lib)["pieces"][0]
        # INCOMPLETE joined this set when verify_art stopped folding "a check
        # did not run" into WARN. A single silk bar forms no pairs on any
        # layer, so the spacing floor is genuinely never applied to it -- which
        # is a coverage hole, not a finding, and not a FAIL either.
        assert p["verify"] in ("PASS", "WARN", "INCOMPLETE"), p["verify"]
        keys = {c["key"] for c in p["checks"]}
        assert "kicad-load" in keys
        load = [c for c in p["checks"] if c["key"] == "kicad-load"][0]
        assert load["level"] == "PASS", \
            "a SKIP here is NOT a pass and must never be counted as one"

        out = tmp_path / "upg.pretty"
        r = verify_art.run_cli(
            HAVE_KICAD.path,
            ["fp", "upgrade", "--force",
             "-o", verify_art.host_path(out, HAVE_KICAD.path),
             verify_art.host_path(lib, HAVE_KICAD.path)])
        assert r.returncode == 0, r.stderr
        assert (out / "silk_bar_10mm.kicad_mod").exists()


# ===========================================================================
# 9. provenance and the don't-leak rule
# ===========================================================================

class TestProvenance:
    def test_the_footprint_records_the_basename_never_the_path(
            self, art, tmp_path):
        lib = lib_of(tmp_path)
        run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify")
        text = (lib / "silk_bar_10mm.kicad_mod").read_text(encoding="utf-8")
        assert "silk_bar.png" in text
        assert str(art) not in text, \
            "third-party art must not leak its local path into a public tree"

    def test_the_internal_name_equals_the_file_stem(self, art, tmp_path):
        # A file FILESTEM.kicad_mod containing (footprint "OTHER") loads without
        # complaint and `fp upgrade` silently rewrites it to FILESTEM, at which
        # point the descr's provenance line is a lie and `fp export svg
        # --footprint OTHER` cannot find it.
        lib = lib_of(tmp_path)
        run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify")
        f = lib / "silk_bar_10mm.kicad_mod"
        assert f.read_text(encoding="utf-8").startswith('(footprint "silk_bar_10mm"')

    def test_nothing_is_written_into_the_source_directory(self, art, tmp_path):
        before = sorted(p.name for p in art.iterdir())
        run(art, "-o", lib_of(tmp_path), "--size", 10, "--no-verify")
        assert sorted(p.name for p in art.iterdir()) == before

    def test_the_journal_lives_beside_the_library_not_inside_it(
            self, art, tmp_path):
        # `kicad-cli fp upgrade -o` copies only *.kicad_mod, so anything kept
        # inside a .pretty evaporates the first time somebody upgrades it.
        lib = lib_of(tmp_path)
        run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify")
        assert lib.with_name(lib.name + ".build.json").is_file()
        assert [f.suffix for f in lib.iterdir()] == [".kicad_mod"]


# ===========================================================================
# 10. reproduction of the curated library (slow, opt-in)
# ===========================================================================

REFERENCE = REPO / "output" / "RecklessArt.pretty"
ASSETS = REPO / "assets" / "normalised"


@pytest.mark.skipif(
    os.environ.get("BUILD_LIBRARY_SLOW") != "1",
    reason="~3 min of real emits; set BUILD_LIBRARY_SLOW=1 to run")
@pytest.mark.skipif(not REFERENCE.is_dir() or not ASSETS.is_dir(),
                    reason="needs output/RecklessArt.pretty and the assets")
def test_a_sidecar_transcribing_render_library_reproduces_it_byte_for_byte(
        tmp_path):
    """tools/render_library.py's LIBRARY is a curated manifest; the sidecar is
    the general form of it. If the sidecar cannot express the library that
    already exists, build_library is not a replacement for it."""
    import render_library                                # noqa: PLC0415

    lines = ["schema = 1", "", "[defaults]", 'min_area = "none"', ""]
    for name, asset, sizes, extra in render_library.LIBRARY:
        emit, min_area, descr = [], None, None
        i = 0
        while i < len(extra):
            if extra[i] == "--min-area-mm2":
                min_area, i = extra[i + 1], i + 2
            elif extra[i] == "--descr":
                descr, i = extra[i + 1], i + 2
            else:
                emit.append(extra[i]); i += 1
        lines.append(f'["{asset}"]')
        lines.append(f'name  = "{name}"')
        lines.append(f'sizes = [{", ".join(f"{s:g}" for s in sizes)}]')
        if min_area:
            lines.append(f'min_area = "{min_area}"')
        if emit:
            lines.append("emit  = [" + ", ".join(json.dumps(e) for e in emit) + "]")
        if descr:
            lines.append("descr = " + json.dumps(descr))
        lines.append("")
    sidecar = tmp_path / "artlib.toml"
    sidecar.write_text("\n".join(lines), encoding="utf-8")

    wanted = {a for _, a, _, _ in render_library.LIBRARY}
    srcs = [ASSETS / a for a in sorted(wanted)]
    missing = [s for s in srcs if not s.is_file()]
    if missing:
        pytest.skip(f"missing normalised assets: {[m.name for m in missing]}")

    lib = tmp_path / "RecklessArt.pretty"
    rc = bl.main([str(s) for s in srcs] + ["-o", str(lib),
                                           "--options", str(sidecar),
                                           "--no-verify", "--jobs", "4"])
    assert rc == 0
    ref = {f.name: f.read_bytes() for f in REFERENCE.glob("*.kicad_mod")}
    got = {f.name: f.read_bytes() for f in lib.glob("*.kicad_mod")}

    # Every footprint the manifest describes must come out byte for byte.
    missing = sorted(set(got) - set(ref))
    assert not missing, f"produced but not in the reference: {missing}"
    differing = [n for n in sorted(got) if ref[n] != got[n]]
    assert not differing, f"{len(differing)} of {len(got)} differ: {differing[:5]}"

    # The reference also holds footprints no image-driven run produces --
    # art_hex_asic_window from texture_board, art_btc_whitepaper_b from
    # microtext. Those are precisely the UNTOUCHED case, and the reason this
    # tool has no delete path: a tool that rebuilt this library by default
    # would destroy them.
    extra = sorted(set(ref) - set(got))
    assert all(not e[0].isdigit() for e in extra)
    print(f"\nreproduced {len(got)} footprint(s) byte for byte; "
          f"{len(extra)} in the reference are not image-driven: {extra}")


# ===========================================================================
# 11. PROVENANCE -- a footprint this tool did not produce is not its property
# ===========================================================================

HAND_MADE = (
    '(footprint "art_hex_asic_window_20mm"\n'
    '\t(version 20241229)\n'
    '\t(descr "HAND MADE - IRREPLACEABLE")\n'
    ')\n')


class TestForeignFootprints:
    """RecklessArt.pretty mixes image-derived footprints with art produced by
    tools/texture_board.py and tools/microtext.py. Neither of those carries
    emit_art's stamp and neither is reproducible by build_library, so a name
    collision with one of them is DESTRUCTION, not an update. Name collision
    alone cannot tell the two apart; provenance can."""

    def _victim(self, tmp_path):
        lib = lib_of(tmp_path)
        lib.mkdir()
        v = lib / "art_hex_asic_window_20mm.kicad_mod"
        v.write_text(HAND_MADE, encoding="utf-8")
        d = tmp_path / "src"
        _png(d / "art_hex_asic_window.png", [((8, 8, 55, 31), SILK)])
        return lib, v, d

    def test_a_foreign_footprint_is_never_silently_overwritten(
            self, tmp_path, capsys):
        lib, victim, d = self._victim(tmp_path)
        before = (victim.read_bytes(), victim.stat().st_mtime_ns)
        rc = run(d, "-o", lib, "--size", 20, "--no-verify")
        assert rc == 2, "a run that would clobber hand-made art must refuse"
        assert (victim.read_bytes(), victim.stat().st_mtime_ns) == before, \
            "the hand-made footprint must not even be opened for writing"
        err = capsys.readouterr().err
        assert "FOREIGN" in err
        assert "art_hex_asic_window_20mm" in err
        assert "--overwrite-foreign" in err, \
            "the refusal must name the one flag that gets through it"

    def test_nothing_else_is_installed_either(self, tmp_path):
        lib, victim, d = self._victim(tmp_path)
        _png(d / "innocent.png", [((6, 6, 57, 33), GOLD)])
        assert run(d, "-o", lib, "--size", 20, "--no-verify") == 2
        assert not (lib / "innocent_20mm.kicad_mod").exists(), \
            "the check runs before anything is built, like every other refusal"

    def test_the_override_flag_is_the_only_way_through(self, tmp_path, capsys):
        lib, victim, d = self._victim(tmp_path)
        assert run(d, "-o", lib, "--size", 20, "--no-verify",
                   "--overwrite-foreign") == 0
        assert "HAND MADE" not in victim.read_text(encoding="utf-8")
        assert "OVERWROTE FOREIGN" in capsys.readouterr().out

    def test_a_footprint_this_tool_made_is_still_updated(self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        _png(art / "silk_bar.png", [((2, 2, 61, 37), SILK)])
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert journal(lib)["pieces"][0]["state"] == "UPDATED"

    def test_the_emit_art_stamp_alone_is_enough_when_the_journal_is_gone(
            self, art, tmp_path):
        # The journal is the fast path; the stamp in the descr is the durable
        # one. A library restored from a backup, or maintained from another
        # checkout, must not suddenly become foreign to its own tool.
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        lib.with_name(lib.name + ".build.json").unlink()
        _png(art / "silk_bar.png", [((2, 2, 61, 37), SILK)])
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert journal(lib)["pieces"][0]["state"] == "UPDATED"

    def test_the_real_library_shape_survives_a_normal_run(self, art, tmp_path):
        # art_hex_asic_window (texture_board.py, Edge.Cuts) and
        # art_btc_whitepaper_b (microtext.py, 1534 fp_text) live in the same
        # .pretty this tool maintains and neither is reproducible by it.
        lib = lib_of(tmp_path)
        lib.mkdir()
        keep = {}
        for n, descr in (
                ("art_hex_asic_window", "Hex ASIC display cutout"),
                ("art_btc_whitepaper_b", "microprinted - tools/microtext.py")):
            f = lib / f"{n}.kicad_mod"
            f.write_text(f'(footprint "{n}" (descr "{descr}"))',
                         encoding="utf-8")
            keep[n] = (f.read_bytes(), f.stat().st_mtime_ns)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        for n, before in keep.items():
            f = lib / f"{n}.kicad_mod"
            assert (f.read_bytes(), f.stat().st_mtime_ns) == before

# ===========================================================================
# 12. ARTWORK CONTAINMENT -- -o is where the derived artwork actually lands
# ===========================================================================

class TestArtworkContainment:
    def test_this_tool_writes_no_image_anywhere(self, art, tmp_path):
        """Round 4 deleted preview rendering outright. It is not off by
        default and it is not behind a flag: there is no code path here that
        writes an image, which is what actually closes the self-ingestion loop
        -- there is no render left to ingest."""
        lib = lib_of(tmp_path)
        before = sorted(p.resolve() for p in tmp_path.rglob("*.png"))
        assert run(art / "silk_bar.png", art / "gold_bar.png", "-o", lib,
                   "--size", 10, "--no-verify") == 0
        assert sorted(p.resolve() for p in tmp_path.rglob("*.png")) == before, \
            "a recognisable colour render of the source art is not a default"
        for pat in ("*.png", "*.jpg", "*.jpeg", "*.svg"):
            assert not list(lib.rglob(pat)), pat

    def test_no_flag_can_ask_for_one(self, art, tmp_path):
        strings = []
        for act in bl.build_parser()._actions:
            strings += list(act.option_strings)
        assert not [s for s in strings if "preview" in s], strings
        with pytest.raises(SystemExit):
            run(art / "silk_bar.png", "-o", lib_of(tmp_path), "--size", 10,
                "--no-verify", "--preview-dir", tmp_path / "pv")

    def test_emit_art_is_never_asked_for_a_preview(self, art, tmp_path,
                                                   monkeypatch):
        """The render used to be made on EVERY run for EVERY piece, into the
        stage, whatever the flags said -- and the stage was inside the
        library. Both halves of that are gone; this is the first half."""
        seen = []
        real = bl.subprocess.run

        def spy(cmd, *a, **k):
            seen.append(list(cmd))
            return real(cmd, *a, **k)

        monkeypatch.setattr(bl.subprocess, "run", spy)
        assert run(art / "silk_bar.png", "-o", lib_of(tmp_path), "--size", 10,
                   "--no-verify") == 0
        emits = [c for c in seen if any("emit_art" in str(x) for x in c)]
        assert emits, "no emit_art call was observed"
        for c in emits:
            assert "--preview" not in c, c

    def test_the_reserved_argument_guard_still_closes_the_back_door(
            self, art, tmp_path, capsys):
        """--preview stays RESERVED even though this tool no longer passes it.
        It is the one emit_art flag that writes a colour render of the source
        art to an arbitrary path, and there is no destination guard left to
        catch where that lands."""
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   f"--emit-arg=--preview={tmp_path / 'leak.png'}") == 2
        assert "owned by build_library" in capsys.readouterr().err
        assert not (tmp_path / "leak.png").exists()


class TestOutputLibraryContainment:
    """-o HAD NO CONTAINMENT CHECK AT ALL.

    _git_toplevel and _git_ignores were written, tested and then called from
    exactly one place: the preview guard. The library -- the directory this
    tool actually fills with derived artwork -- was never checked, and a run
    into a tracked path of the real public repo with real MFB art exited 0
    without a word.
    """

    def test_a_library_in_a_working_tree_that_does_not_ignore_it_is_refused(
            self, art, tmp_path, capsys):
        wt = git_tree(tmp_path)
        lib = wt / "boards" / "Art.pretty"
        rc = run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify")
        assert rc == 2
        err = capsys.readouterr().err
        assert "git working tree" in err and "does not ignore it" in err
        assert not lib.exists(), "and the library was not even created"

    def test_the_refusal_names_all_three_ways_on(self, art, tmp_path, capsys):
        wt = git_tree(tmp_path)
        run(art / "silk_bar.png", "-o", wt / "Art.pretty", "--size", 10,
            "--no-verify")
        err = capsys.readouterr().err
        assert ".gitignore" in err
        assert "outside the checkout" in err
        assert "--allow-tracked-library" in err

    def test_a_gitignored_library_inside_a_working_tree_is_allowed(
            self, art, tmp_path):
        """The rule is 'not ignored', not 'not in a repo'. An in-repo library
        is the documented workflow; it just has to be ignored."""
        wt = git_tree(tmp_path)
        lib = wt / "output" / "Art.pretty"
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert (lib / "silk_bar_10mm.kicad_mod").is_file()

    def test_the_override_flag_lets_a_deliberately_tracked_library_through(
            self, art, tmp_path):
        """SatoshiStarter tracks RecklessArt.pretty on purpose, in a private
        repo, and it has to keep working. That is why the way through is a
        flag and not a heuristic guessing which checkouts are private."""
        wt = git_tree(tmp_path)
        lib = wt / "Art.pretty"
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   "--allow-tracked-library") == 0
        assert (lib / "silk_bar_10mm.kicad_mod").is_file()

    def test_a_dry_run_is_refused_too(self, art, tmp_path):
        """--dry-run is the command you would run to check yourself. Telling
        you the destination is wrong is the most useful thing it can do."""
        wt = git_tree(tmp_path)
        assert run(art / "silk_bar.png", "-o", wt / "Art.pretty", "--size", 10,
                   "--no-verify", "--dry-run") == 2

    def test_a_library_outside_any_working_tree_is_untouched_by_the_rule(
            self, art, tmp_path):
        assert run(art / "silk_bar.png", "-o", lib_of(tmp_path), "--size", 10,
                   "--no-verify") == 0

    @pytest.mark.skipif(not SATOSHI.is_dir(), reason="needs the board repo")
    def test_the_real_private_board_library_still_works(self):
        """THE EXACT PATH, checked without writing a byte into it.
        SatoshiStarter/RecklessArt.pretty is TRACKED and PRIVATE: the guard
        must refuse it bare and accept it with the flag, or round 4 has broken
        the one library this tool exists to maintain."""
        if not shutil.which("git"):
            pytest.skip("needs git")
        lib = SATOSHI / "RecklessArt.pretty"
        jrn = lib.with_name(lib.name + ".build.json")
        top = bl._git_toplevel(lib.resolve())
        assert top == SATOSHI.resolve(), top
        assert not bl._git_ignores(top, lib.resolve(), True), \
            "this test is meaningless unless the library really is tracked"
        with pytest.raises(bl.Usage):
            bl._check_output_lib(lib, jrn, False)
        assert bl._check_output_lib(lib, jrn, True) is None

    def test_neither_repo_needs_a_rule_for_this_tools_working_directories(
            self):
        """ROUND 4 PUT `.build_library_*/` IN BOTH REPOS. It was a rule two
        working trees had to carry because the tool insisted on creating named
        directories in them -- and the same round's sweep then globbed that
        pattern in the library's PARENT and rmtree'd what it found.

        There is nothing left to ignore. The stage is in the system temporary
        directory, so a run that is SIGKILLed leaves nothing in either repo,
        and neither .gitignore needs to know this tool exists.
        """
        if not shutil.which("git"):
            pytest.skip("needs git")
        checked = 0
        for repo in (REPO, SATOSHI):
            if not (repo / ".git").exists():
                continue
            checked += 1
            body = (repo / ".gitignore").read_text(encoding="utf-8")
            assert ".build_library_" not in body, \
                f"{repo.name}/.gitignore still carries a rule for a " \
                f"convention this tool no longer has:\n{body}"
            for rel in (".build_library_1234_x/alpha.kicad_mod",
                        "sub/dir/.build_library_undo_9/bravo.kicad_mod"):
                assert not ignores(repo, rel), \
                    f"{repo.name}: {rel} is still ignored by something"
        assert checked, "neither repo was a git checkout"

    def test_this_repos_own_documented_targets_stay_ignored(self):
        if not (REPO / ".git").exists() or not shutil.which("git"):
            pytest.skip("needs a git checkout")
        assert ignores(REPO, "library/RecklessArt.pretty/satoshi_20mm.kicad_mod")
        assert ignores(REPO, "library/RecklessArt.pretty.build.json")
        assert ignores(REPO, "output/RecklessArt.pretty/x.kicad_mod")
        # ...and the two hand-made footprints the repo really does track must
        # stay tracked, or this rule has broken the library it protects.
        assert not ignores(
            REPO, "library/RecklessArt.pretty/art_hex_asic_window.kicad_mod")
        assert not ignores(
            REPO, "library/RecklessArt.pretty/art_btc_whitepaper_b.kicad_mod")

    def test_removing_the_rule_did_not_start_ignoring_a_tracked_file(self):
        """Round 4 added `.build_library_*/` to both repos and round 5 removes
        it. Either edit could silently start ignoring a TRACKED file, which is
        a quiet way to lose one, so both .gitignore files are checked against
        every tracked path in their own repo.

        The `build_library` scoping is gone with the rule, so this now asserts
        a blanket zero -- with one documented exception. kicad_art_generator's
        .gitignore carries a pre-existing broken negation: `assets/` excludes
        the directory and `!assets/normalised/bitcoin_emission_formula.svg`
        cannot re-include a file whose parent directory is excluded, which is
        documented git behaviour and predates all five rounds.

        `check-ignore -v --stdin` also reports NEGATION patterns -- a `!` line
        is git saying the path is explicitly NOT ignored -- so those rows are
        the opposite of a finding and are dropped.
        """
        import re as _re                                # noqa: PLC0415
        import subprocess                               # noqa: PLC0415
        if not shutil.which("git"):
            pytest.skip("needs git")
        known = {"assets/normalised/bitcoin_emission_formula.svg"}
        checked = 0
        for repo in (REPO, SATOSHI):
            if not (repo / ".git").exists():
                continue
            checked += 1
            tracked = subprocess.run(
                ["git", "ls-files"], cwd=repo, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, check=True).stdout.split("\n")
            tracked = [t for t in tracked if t]
            assert tracked, repo
            hits = subprocess.run(
                ["git", "check-ignore", "-v", "--no-index", "--stdin"],
                cwd=repo, input="\n".join(tracked),
                capture_output=True, text=True).stdout.splitlines()
            bad = []
            for h in hits:
                head, _, path = h.partition("\t")
                m = _re.match(r"^(?P<src>.*):(?P<n>\d+):(?P<pat>.*)$", head)
                pat = m.group("pat") if m else ""
                if not pat.strip() or pat.startswith("!"):
                    continue                    # no rule, or an un-ignore
                if path.strip() in known:
                    continue
                bad.append(h)
            assert not bad, \
                f"{repo.name}: .gitignore ignores tracked file(s): {bad}"
        assert checked, "neither repo was a git checkout"

    # -- the first-run false refusal, and the journal -----------------------

    def _repo(self, tmp_path, ignore, name="checkout"):
        import subprocess                               # noqa: PLC0415
        if not shutil.which("git"):
            pytest.skip("needs git")
        wt = tmp_path / name
        wt.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=wt, check=True,
                       stdin=subprocess.DEVNULL, capture_output=True)
        (wt / ".gitignore").write_text(ignore, encoding="utf-8")
        return wt

    @pytest.mark.parametrize("pattern", ["Art.pretty/", "Art.pretty"])
    @pytest.mark.parametrize("present", [False, True])
    def test_a_directory_only_rule_answers_the_same_before_and_after_mkdir(
            self, art, tmp_path, pattern, present):
        """THE FIRST-RUN FALSE REFUSAL, all four combinations.

        check-ignore decides whether `Art.pretty/` can match `Art.pretty` by
        STATTING the path, and -o is checked before the library exists. So
        with the directory-only rule and no directory, round 4's single
        no-slash invocation reported NO MATCH and refused -- and then a bare
        `mkdir Art.pretty` made the identical command succeed. Same command,
        opposite answers, against a --help that says "Created if absent".
        """
        wt = self._repo(tmp_path, pattern + "\n")
        lib = wt / "Art.pretty"
        if present:
            lib.mkdir()
        # git itself, so the fixture is honest about which combination this is
        raw_no_slash = ignores(wt, "Art.pretty")
        if pattern.endswith("/") and not present:
            assert not raw_no_slash, \
                "this combination no longer reproduces the false refusal"
        assert bl._git_ignores(wt.resolve(), lib.resolve(), True), \
            f"pattern={pattern} present={present}: git ignores this library"
        # --journal outside the tree, so this test is about the LIBRARY alone;
        # the journal's own guard has its own tests below.
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify", "--journal", tmp_path / "j.json") == 0
        assert (lib / "silk_bar_10mm.kicad_mod").is_file()

    def test_a_directory_only_rule_does_not_ignore_a_file_of_that_name(
            self, tmp_path):
        """The other direction, and the dangerous one. Asserting to git that a
        path is a directory is how the slash form works, so asking it about a
        FILE would let `X/` be read as ignoring the file `X` -- a false ALLOW.
        The journal is a file; is_dir is passed, never guessed."""
        wt = self._repo(tmp_path, "Art.pretty.build.json/\n")
        f = wt / "Art.pretty.build.json"
        assert not ignores(wt, "Art.pretty.build.json"), "git does not ignore it"
        assert not bl._git_ignores(wt.resolve(), f.resolve(), False)
        assert bl._git_ignores(wt.resolve(), f.resolve(), True), \
            "and the slash form really would have said yes"

    def test_a_match_is_only_believed_when_git_names_a_pattern(
            self, tmp_path):
        """An exit code cannot distinguish 'a rule you wrote matches' from any
        other route to 0. The pattern field can."""
        for body in ("\n\n\n", "build/\n\n*.log\n"):
            wt = self._repo(tmp_path, body, name=f"r{len(body)}{body.count('*')}")
            assert not bl._git_ignores(wt.resolve(),
                                       (wt / "Art.pretty").resolve(), True)
            assert bl._ignore_rule(wt.resolve(), "Art.pretty/") is None

    def test_the_journal_is_guarded_as_well_as_the_library(
            self, art, tmp_path, capsys):
        """ROUND 4 CLAIMED THE -o GUARD COVERED EVERYTHING THIS TOOL WROTE
        while the stage, the undo directory AND the journal were all landing
        in lib.parent, unchecked. Two of those three are gone. The journal
        still lives beside the library on purpose -- `kicad-cli fp upgrade -o`
        copies only .kicad_mod files -- so a rule that ignores the LIBRARY
        does not ignore it, and it is checked in its own right."""
        wt = self._repo(tmp_path, "Art.pretty/\n")      # the library only
        lib = wt / "Art.pretty"
        rc = run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify")
        assert rc == 2, "the journal would have landed in a tracked path"
        err = capsys.readouterr().err
        assert "--journal" in err and "Art.pretty.build.json" in err
        assert not lib.exists(), "and nothing was created"

    def test_ignoring_the_parent_directory_covers_both(
            self, art, tmp_path):
        """...and the fix the message suggests actually works."""
        wt = self._repo(tmp_path, "out/\n")
        lib = wt / "out" / "Art.pretty"
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert lib.with_name(lib.name + ".build.json").is_file()

    def test_pointing_the_journal_out_of_the_tree_is_the_other_way_on(
            self, art, tmp_path):
        wt = self._repo(tmp_path, "Art.pretty/\n")
        lib = wt / "Art.pretty"
        jrn = tmp_path / "elsewhere.json"
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify", "--journal", jrn) == 0
        assert jrn.is_file()
        assert not lib.with_name(lib.name + ".build.json").exists()

    def test_every_durable_path_the_run_wrote_was_a_checked_one(
            self, art, tmp_path):
        """THE ENUMERATION, CHECKED RATHER THAN ASSERTED.

        Round 4's claim that the -o guard covered everything this tool wrote
        was false, and it was false because nobody enumerated. So: walk the
        WHOLE working tree and the whole source tree before and after a real
        run, and require the delta to be exactly the library, its footprints
        and the journal. Anything else -- a stage, an undo directory, a
        stranded install temporary, a marker file -- shows up here by
        construction, whatever it is called.
        """
        wt = self._repo(tmp_path, "out/\n")
        lib = wt / "out" / "Art.pretty"

        def tree(d):
            return {p.relative_to(d) for p in d.rglob("*")
                    if ".git" not in p.parts}

        src_before = tree(art)
        wt_before = tree(wt)
        assert run(art / "silk_bar.png", art / "gold_bar.png", "-o", lib,
                   "--size", 10, "--no-verify") == 0
        assert tree(art) == src_before, "a SOURCE directory was written into"
        assert tree(wt) - wt_before == {
            Path("out"),
            Path("out/Art.pretty"),
            Path("out/Art.pretty/silk_bar_10mm.kicad_mod"),
            Path("out/Art.pretty/gold_bar_10mm.kicad_mod"),
            Path("out/Art.pretty.build.json"),
        }, sorted(str(p) for p in tree(wt) - wt_before)

    @pytest.mark.skipif(not SATOSHI.is_dir(), reason="needs the board repo")
    def test_the_real_tracked_footprints_stay_tracked(self):
        """The private board repo tracks its art library deliberately. A rule
        added for working directories must not touch it."""
        if not (SATOSHI / ".git").exists() or not shutil.which("git"):
            pytest.skip("needs a git checkout")
        for n in ("art_hex_asic_window", "art_btc_whitepaper_b",
                  "mfb_lockup_20mm"):
            assert not ignores(SATOSHI, f"RecklessArt.pretty/{n}.kicad_mod"), n


class TestTheStageIsInTheSystemTemp:
    """FOUR ROUNDS, ONE DEFECT: it always landed wherever the staging
    directory lived.

    Round 2, stage inside the library: a Ctrl-C unwound the staging
    TemporaryDirectory and took the preserved originals with it. Round 3,
    stage inside the library: the library discovered its own preview output
    and built alpha_20mm_20mm. Round 4, stage beside the library: the
    stale-stage sweep began globbing `.build_library_*` in the library's
    PARENT -- a directory the tool does not own -- and the -o guard covered
    only the .pretty while the stage, the undo directory and the journal all
    landed in that parent unchecked.

    So the stage is not somewhere else now; the SUBSYSTEM is gone. tempfile
    picks the location, the OS owns it, nothing globs for it, and no
    .gitignore anywhere needs a rule for it.
    """

    def _spy_dirs(self, monkeypatch):
        made = []
        real_td = bl.tempfile.TemporaryDirectory
        real_mk = bl.tempfile.mkdtemp

        def spy_td(*a, **k):
            t = real_td(*a, **k)
            made.append(Path(t.name).resolve())
            return t

        def spy_mk(*a, **k):
            p = real_mk(*a, **k)
            made.append(Path(p).resolve())
            return p

        monkeypatch.setattr(bl.tempfile, "TemporaryDirectory", spy_td)
        monkeypatch.setattr(bl.tempfile, "mkdtemp", spy_mk)
        return made

    def test_no_working_directory_is_made_in_the_library_or_beside_it(
            self, art, tmp_path, monkeypatch):
        """BOTH, which is the round-5 half. Round 4 got 'not inside the
        library' and put the problem one directory up instead."""
        lib = lib_of(tmp_path)
        made = self._spy_dirs(monkeypatch)
        assert run(art / "silk_bar.png", art / "gold_bar.png", "-o", lib,
                   "--size", 10, "--no-verify") == 0
        assert made, "no working directory was created at all"
        rlib = lib.resolve()
        tmproot = Path(tempfile.gettempdir()).resolve()
        for d in made:
            assert not bl._under(d, rlib) and d != rlib, \
                f"{d} is inside the library it is maintaining"
            assert d.parent != rlib.parent, \
                f"{d} is in the library's PARENT, which is somebody's repo"
            assert bl._under(d, tmproot), \
                f"{d} is not in the system temporary directory ({tmproot})"

    def test_nothing_is_left_behind_anywhere_to_be_swept_later(
            self, art, tmp_path):
        """The sweep existed because the stage outlived the run. A directory
        the OS owns and removes does not need one, and a tool with no sweep
        cannot rmtree the wrong thing."""
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert sorted(p.name for p in lib.iterdir()) == \
            ["silk_bar_10mm.kicad_mod"]
        assert sorted(p.name for p in tmp_path.iterdir()) == \
            ["Test.pretty", "Test.pretty.build.json", "art"]

    def test_no_build_library_convention_survives_anywhere(self):
        """`.build_library_*` was a name two repos' .gitignore files had to
        know, a glob that swept directories by it, and a discovery rule that
        skipped them. All three are gone, so the name is nobody's contract.

        Scanned as CODE, not as text: the prose in this file still describes
        the convention at length, because how it went wrong four times is the
        reason it is not here any more. What must not survive is a string the
        tool can act on.
        """
        import ast                                      # noqa: PLC0415
        tree = ast.parse((REPO / "tools" / "build_library.py")
                         .read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                d = ast.get_docstring(node, clean=False)
                if d is not None:
                    docs.add(d)
        live = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value not in docs]
        bad = [s for s in live if ".build_library_" in s]
        assert not bad, f"the convention is back as a live string: {bad}"
        assert not hasattr(bl, "UNDO_PREFIX")
        assert not hasattr(bl, "_sweep_stale_stages")
        assert not hasattr(bl, "_make_undo_dir")
        assert not hasattr(bl, "_work_root")
        # and the stage prefix that remains is only a tempfile courtesy label
        assert not bl.STAGE_PREFIX.startswith(".")

        # NO GLOB OVER ANY DIRECTORY except for footprints. The sweep globbed
        # `.build_library_*` in the library's PARENT and rmtree'd the hits --
        # a silent destruction path in a directory the tool does not own.
        globs = [n.args[0].value for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("glob", "rglob") and n.args
                 and isinstance(n.args[0], ast.Constant)]
        assert set(globs) <= {"*.kicad_mod", "*"}, globs
        assert not [n for n in ast.walk(tree)
                    if isinstance(n, ast.Attribute) and n.attr == "rmtree"], \
            "nothing in this tool removes a directory tree any more"

    def test_the_library_holds_nothing_but_footprints_mid_install(
            self, art, tmp_path, monkeypatch):
        """Not just afterwards: DURING. The install temporary of the
        cross-device path is created in the library itself, so it has to be
        invisible to everything that reads a .pretty."""
        lib = lib_of(tmp_path)
        seen = []
        real = bl._install

        def spy(src, dst):
            r = real(src, dst)
            seen.append(sorted(p.name for p in Path(dst).parent.iterdir()))
            return r

        monkeypatch.setattr(bl, "_install", spy)
        assert run(art / "silk_bar.png", art / "gold_bar.png", "-o", lib,
                   "--size", 10, "--no-verify") == 0
        assert len(seen) >= 2, "not enough installs to observe the library"
        for names in seen:
            assert all(n.endswith(".kicad_mod") for n in names), names
            assert not any(n.startswith(".") for n in names), names

    def test_a_working_directory_is_never_discovered_as_a_source(
            self, tmp_path):
        """The old answer was a name rule in discover(). The stage is in the
        system temp now, which is not a place a SOURCE argument points, so a
        directory that merely LOOKS like the old convention is just the user's
        own art and must be walked like any other."""
        top = tmp_path / "work"
        src = top / "art"
        _png(src / "alpha.png", [((8, 8, 55, 31), SILK)])
        mine = top / ".build_library_1234_x"
        _png(mine / "beta.png", [((6, 6, 57, 33), GOLD)])
        lib = top / "Lib.pretty"
        assert run(top, "-o", lib, "--recursive", "--size", 20,
                   "--no-verify") == 0
        assert {f.stem for f in lib.glob("*.kicad_mod")} == \
            {"alpha_20mm", "beta_20mm"}, \
            "a name rule is still silently swallowing the user's own art"


class TestSourceTreeIsReadOnly:
    def test_three_identical_runs_produce_the_same_library(self, tmp_path):
        # REPRODUCED: run 1 -> alpha_20mm, run 2 -> + alpha_20mm_20mm,
        # run 3 -> + alpha_20mm_20mm_20mm. The tool was eating its own colour
        # renders -- and still could with NO --preview-dir given, because the
        # stage was inside the library and a render was made for every piece
        # on every run. It writes no image anywhere now.
        src = tmp_path / "F" / "art"
        _png(src / "alpha.png", [((8, 8, 55, 31), SILK)])
        lib = src / "Lib.pretty"
        for i in range(3):
            assert run(src, "-o", lib, "--recursive", "--size", 20,
                       "--no-verify") == 0, f"run {i + 1}"
            assert {f.stem for f in lib.glob("*.kicad_mod")} == {"alpha_20mm"}, \
                f"after run {i + 1}"

    def test_the_tool_cannot_brick_itself_against_the_users_own_art(
            self, tmp_path):
        # With a real x_20mm.png beside x.png the second run used to abort
        # with a COLLISION between the tool's own render and the user's art,
        # exit 2, nothing built -- and blamed the user's art. A filename rule
        # can never tell those apart, which is why the only name-based rule
        # left applies to DIRECTORIES this tool creates itself.
        src = tmp_path / "F" / "art"
        _png(src / "x.png", [((8, 8, 55, 31), SILK)])
        _png(src / "x_20mm.png", [((6, 6, 57, 33), GOLD)])
        lib = src / "Lib.pretty"
        assert run(src, "-o", lib, "--recursive", "--size", 20,
                   "--no-verify") == 0
        assert run(src, "-o", lib, "--recursive", "--size", 20,
                   "--no-verify") == 0
        assert {f.stem for f in lib.glob("*.kicad_mod")} == \
            {"x_20mm", "x_20mm_20mm"}

    def test_an_image_inside_the_output_library_is_not_a_source(self, tmp_path):
        src = tmp_path / "art"
        _png(src / "alpha.png", [((8, 8, 55, 31), SILK)])
        lib = src / "Lib.pretty"
        lib.mkdir(parents=True)
        _png(lib / "stray.png", [((6, 6, 57, 33), GOLD)])
        assert run(src, "-o", lib, "--recursive", "--size", 20,
                   "--no-verify") == 0
        assert {f.stem for f in lib.glob("*.kicad_mod")} == {"alpha_20mm"}


# ===========================================================================
# 13. ATOMICITY -- never a partial library plus a stale journal
# ===========================================================================

class TestInstallAtomicity:
    def _three(self, tmp_path):
        d = tmp_path / "src"
        for i, n in enumerate("abc"):
            _png(d / f"{n}.png", [((8, 8, 50 + i, 31), SILK)])
        return d

    def test_an_obstructed_target_stops_there_and_reports_it_off_the_disk(
            self, tmp_path, capsys):
        """A failure part way through is not a state needing repair, it is a
        shorter run. Pieces before the obstruction ARE installed; pieces after
        it still hold what they held. Nothing was moved aside, so the honest
        report is which of the two each piece is -- not a rollback claim."""
        d = self._three(tmp_path)
        lib = lib_of(tmp_path)
        assert run(d, "-o", lib, "--size", 10, "--no-verify") == 0
        before = snapshot(lib)
        for i, n in enumerate("abc"):                 # every piece now UPDATEs
            _png(d / f"{n}.png", [((2, 2, 55 + i, 37), SILK)])
        obstruction = lib / "b_10mm.kicad_mod"
        obstruction.unlink()
        obstruction.mkdir()

        rc = run(d, "-o", lib, "--size", 10, "--no-verify")
        assert rc != 0, "an install that could not complete is not a success"
        out = capsys.readouterr().out
        assert "INSTALL FAILED" in out
        j = journal(lib)
        assert j.get("install_error"), "the journal must record the failure"

        # EVERY piece is old-or-new, and the journal says which, from disk.
        landed = set(j["installed"])
        assert "b" not in [n[0] for n in landed], landed
        for n in ("a", "c"):
            f = lib / f"{n}_10mm.kicad_mod"
            fresh = f.read_bytes() != before[f.name][0]
            assert fresh == (f"{n}_10mm" in landed), \
                f"{n}: the journal and the disk disagree"
        # ...and nothing is missing, which is the property that matters.
        for n in ("a", "c"):
            assert (lib / f"{n}_10mm.kicad_mod").is_file()

    def test_the_rows_that_did_not_install_say_the_old_one_is_untouched(
            self, tmp_path, capsys):
        """Round 4 marked EVERY ADDED/UPDATED row failed on any install error
        and appended a rollback promise to each. Both halves were wrong: the
        pieces installed before the error really were installed, and no
        rollback had happened."""
        d = self._three(tmp_path)
        lib = lib_of(tmp_path)
        assert run(d, "-o", lib, "--size", 10, "--no-verify") == 0
        for i, n in enumerate("abc"):
            _png(d / f"{n}.png", [((2, 2, 55 + i, 37), SILK)])
        obstruction = lib / "b_10mm.kicad_mod"
        obstruction.unlink()
        obstruction.mkdir()
        run(d, "-o", lib, "--size", 10, "--no-verify")
        out = capsys.readouterr().out
        assert "rolled back" not in out.lower(), \
            "there is no rollback; claiming one is the round-3 defect"
        assert "NOT INSTALLED" in out
        assert "already in the library is untouched" in out

    def test_a_cross_device_link_error_is_handled_not_crashed(
            self, art, tmp_path, monkeypatch):
        """EXDEV IS THE NORMAL PATH NOW. The stage is in the system temp, so
        under WSL every install crosses from ext4 to DrvFs."""
        lib = lib_of(tmp_path)
        real = os.replace
        fired = []

        def fake(src, dst, *a, **k):
            if not fired and Path(dst).parent == lib and \
                    str(dst).endswith(".kicad_mod"):
                fired.append(1)
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real(src, dst, *a, **k)

        monkeypatch.setattr(bl.os, "replace", fake)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        assert fired, "the test did not exercise the EXDEV path"
        f = lib / "silk_bar_10mm.kicad_mod"
        assert f.is_file()
        assert f.read_text(encoding="utf-8").startswith(
            '(footprint "silk_bar_10mm"')
        assert sorted(p.name for p in lib.iterdir()) == [f.name], \
            "the cross-device temporary was left in the library"

    def test_the_cross_device_temporary_is_removed_when_the_copy_fails(
            self, art, tmp_path, monkeypatch):
        """It is the only thing this tool writes into the library besides
        footprints, so it has to clean up after itself on the failing path as
        well as the succeeding one."""
        lib = lib_of(tmp_path)
        lib.mkdir(parents=True)
        src = tmp_path / "staged.kicad_mod"
        src.write_text("(footprint \"x\")\n", encoding="utf-8")
        dst = lib / "x.kicad_mod"

        monkeypatch.setattr(bl.os, "replace", lambda *a, **k: (_ for _ in ())
                            .throw(OSError(errno.EXDEV, "cross-device")))
        monkeypatch.setattr(bl.shutil, "copy2", lambda *a, **k: (_ for _ in ())
                            .throw(OSError(errno.ENOSPC, "no space")))
        with pytest.raises(OSError):
            bl._install(src, dst)
        assert list(lib.iterdir()) == [], \
            f"a temporary was stranded in the library: " \
            f"{[p.name for p in lib.iterdir()]}"

    def test_the_incumbent_is_never_opened_moved_or_copied(
            self, tmp_path, monkeypatch):
        """THE PROPERTY THE WHOLE ROUND RESTS ON. If nothing displaces the
        file that is already there, no interrupt can leave a hole and no
        rollback is needed to fix one. Proved by watching every rename and
        copy the install makes: the only path a target name appears at is the
        DESTINATION of a replace."""
        d, lib = _three_installed(tmp_path)
        targets = {(lib / f"{n}_20mm.kicad_mod").resolve() for n in ABC}
        moved_from, copied_from = [], []
        real_replace, real_copy = os.replace, shutil.copy2

        def spy_replace(src, dst, *a, **k):
            if Path(src).resolve() in targets:
                moved_from.append(str(src))
            return real_replace(src, dst, *a, **k)

        def spy_copy(src, dst, *a, **k):
            if Path(src).resolve() in targets:
                copied_from.append(str(src))
            return real_copy(src, dst, *a, **k)

        monkeypatch.setattr(bl.os, "replace", spy_replace)
        monkeypatch.setattr(bl.shutil, "copy2", spy_copy)
        for i, n in enumerate(ABC):                   # make all three UPDATE
            _png(d / f"{n}.png", [((2, 2, 55 + i, 37), SILK)])
        assert run(d, "-o", lib, "--size", 20, "--no-verify") == 0
        assert moved_from == [], \
            f"an incumbent was moved aside: {moved_from}"
        assert copied_from == [], \
            f"an incumbent was copied aside: {copied_from}"
        assert _state(lib, ABC) == {n: "new" for n in ABC}

    @pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0,
                        reason="needs POSIX permissions and a non-root user")
    def test_an_unwritable_library_fails_cleanly(self, art, tmp_path, capsys):
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        before = snapshot(lib)
        _png(art / "silk_bar.png", [((2, 2, 61, 37), SILK)])
        lib.chmod(0o555)
        try:
            probe = lib / ".probe"
            try:
                probe.touch()
                probe.unlink()
                pytest.skip("this filesystem ignores the read-only bit")
            except OSError:
                pass
            rc = run(art / "silk_bar.png", "-o", lib, "--size", 10,
                     "--no-verify")
        finally:
            lib.chmod(0o755)
        assert rc != 0
        assert snapshot(lib) == before
        assert "INSTALL FAILED" in capsys.readouterr().out


# ===========================================================================
# 14. THE RESERVED-ARGUMENT GUARD vs argparse prefix abbreviation
# ===========================================================================

class TestReservedEmitArgs:
    # emit_art's argparse abbreviates: --nam, --na and --n all reach --name.
    # REPRODUCED: --emit-arg=--nam --emit-arg=EVIL installed a file whose
    # first line was (footprint "EVIL"), reported as ADDED plain_mark_20mm,
    # verify PASS, exit 0.
    @pytest.mark.parametrize("abbrev", ["--name", "--nam", "--na", "--n"])
    def test_an_abbreviated_reserved_flag_is_refused(
            self, art, tmp_path, abbrev, capsys):
        lib = lib_of(tmp_path)
        rc = run(art / "gold_bar.png", "-o", lib, "--size", 10, "--no-verify",
                 f"--emit-arg={abbrev}", "--emit-arg=EVIL")
        assert rc == 2, f"{abbrev} reaches --name through argparse abbreviation"
        assert not lib.exists()
        assert "owned by build_library" in capsys.readouterr().err

    @pytest.mark.parametrize("abbrev", ["--out", "--outp", "--report", "--prev",
                                        "--min-area-mm", "--desc", "--label",
                                        "--width", "--allow-emp"])
    def test_every_other_reserved_flag_abbreviates_too(
            self, art, tmp_path, abbrev):
        lib = lib_of(tmp_path)
        assert run(art / "gold_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   f"--emit-arg={abbrev}", "--emit-arg=x") == 2
        assert not lib.exists()

    def test_an_attached_short_option_value_is_refused(self, art, tmp_path):
        # -oVALUE is one token to argparse and never contained an '=' for the
        # old split-on-equals guard to find.
        lib = lib_of(tmp_path)
        evil = tmp_path / "evil.kicad_mod"
        assert run(art / "gold_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   f"--emit-arg=-o{evil}") == 2
        assert not evil.exists()

    def test_the_sidecar_route_is_closed_too(self, art, tmp_path, capsys):
        (art / bl.SIDECAR_NAME).write_text(
            'schema = 1\n["gold_bar.png"]\n'
            'emit = ["--nam", "SIDECAR_EVIL"]\n', encoding="utf-8")
        lib = lib_of(tmp_path)
        assert run(art / "gold_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 2
        assert "owned by build_library" in capsys.readouterr().err

    def test_the_installed_footprint_is_named_what_the_row_says(
            self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "gold_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        f = lib / "gold_bar_10mm.kicad_mod"
        assert f.read_text(encoding="utf-8").startswith(
            '(footprint "gold_bar_10mm"')

    def test_a_legitimate_emit_flag_still_gets_through(self, art, tmp_path):
        lib = lib_of(tmp_path)
        assert run(art / "gold_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   "--emit-arg=--smooth", "--emit-arg=0.5") == 0
        assert (lib / "gold_bar_10mm.kicad_mod").is_file()

    def test_an_abbreviation_of_a_flag_this_tool_does_not_own_is_allowed(
            self, art, tmp_path):
        # --smoot reaches emit_art's --smooth, which build_library does not
        # own. Refusing it would be over-blocking.
        lib = lib_of(tmp_path)
        assert run(art / "gold_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   "--emit-arg=--smoot", "--emit-arg=0.5") == 0

    def test_the_guard_knows_emit_arts_real_option_list(self):
        opts = bl._emit_option_strings()
        for must in ("--labels", "--width-mm", "--name", "--output", "-o",
                     "--report-json", "--preview", "--min-area-mm2", "--descr",
                     "--allow-empty", "--smooth", "--ink-tone"):
            assert must in opts, f"{must} missing from the scanned option list"


# ===========================================================================
# 15. HONESTY -- what stdout alone tells an unattended operator
# ===========================================================================

GAP = ("GAP BELOW FLOOR: F.Cu narrowest gap 0.016434 mm < 0.1000 mm (copper) "
       "in 2 of 8 separated pair(s)")
FLOOR = "BELOW FLOOR: F.Cu 0.0395 mm"


def _fake_warn_verify(monkeypatch):
    """A kicad-cli that exists and a verify_file that WARNs with detail."""
    monkeypatch.setattr(
        bl.verify_art, "find_kicad_cli",
        lambda explicit=None: verify_art.CliChoice("/nonexistent/kicad-cli",
                                                   "10.0.0", 10, []))

    def fake(path, cfg):
        return verify_art.WARN, [
            verify_art.Check("clearance", verify_art.WARN,
                             "1 clearance problem(s)", [GAP, FLOOR])]

    monkeypatch.setattr(bl.verify_art, "verify_file", fake)


class TestVerifyHonesty:
    def test_a_warn_detail_reaches_stdout(self, art, tmp_path, monkeypatch,
                                          capsys):
        _fake_warn_verify(monkeypatch)
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10) == 0
        out = capsys.readouterr().out
        assert "GAP BELOW FLOOR" in out, \
            "a warning whose content only exists in a JSON file is not a warning"
        assert "0.016434" in out
        assert "BELOW FLOOR: F.Cu 0.0395 mm" in out

    def test_the_warn_detail_survives_quiet(self, art, tmp_path, monkeypatch,
                                            capsys):
        _fake_warn_verify(monkeypatch)
        assert run(art / "silk_bar.png", "-o", lib_of(tmp_path), "--size", 10,
                   "--quiet") == 0
        assert "GAP BELOW FLOOR" in capsys.readouterr().out

    def test_the_footer_counts_the_verdicts(self, art, tmp_path, monkeypatch,
                                            capsys):
        _fake_warn_verify(monkeypatch)
        assert run(art / "silk_bar.png", art / "gold_bar.png", "-o",
                   lib_of(tmp_path), "--size", 10) == 0
        out = capsys.readouterr().out
        assert "2 WARN" in out, \
            "on a 21-footprint run nobody should have to eyeball 21 rows"

    def test_the_footer_names_the_pieces_that_are_not_known_fabricable(
            self, art, tmp_path, monkeypatch, capsys):
        _fake_warn_verify(monkeypatch)
        assert run(art / "silk_bar.png", "-o", lib_of(tmp_path),
                   "--size", 10) == 0
        out = capsys.readouterr().out
        assert "verified WARN and were INSTALLED" in out
        assert "silk_bar_10mm" in out
        assert "--strict" in out

    def test_the_journal_counts_them_too(self, art, tmp_path, monkeypatch):
        _fake_warn_verify(monkeypatch)
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10) == 0
        assert journal(lib)["summary"]["verify"]["WARN"] == 1

    def test_the_help_does_not_promise_what_the_tool_does_not_do(self):
        # The claim is wrapped across lines in both places, so compare on
        # collapsed whitespace or the assertion is vacuous.
        flat = " ".join(bl.build_parser().format_help().split())
        assert "never contains art that could not be fabricated" not in flat, \
            "every satoshi piece was installed on a WARN; the promise was false"
        assert "--strict" in flat
        assert "never contains art that could not be fabricated" not in \
            " ".join((bl.__doc__ or "").split())

    def test_strict_still_turns_a_warn_into_a_failure(self, art, tmp_path,
                                                      monkeypatch):
        _fake_warn_verify(monkeypatch)
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--strict") == 1
        assert not (lib / "silk_bar_10mm.kicad_mod").exists()


class TestDroppedLine:
    def test_the_dropped_line_reports_what_was_dropped(self, art, tmp_path,
                                                       capsys):
        # The old line read "DROPPED T1 (104,502 px, 1 region(s)) -- 0.092% of
        # ink", where px was the tone's TOTAL pixel count from emit_art's
        # census, not the dropped count. The guard the design leans on hardest
        # printed a figure that meant something else.
        lib = lib_of(tmp_path)
        # Exit 1, not 0: this fixture loses 10.3% of its ink and the fidelity
        # metric now refuses it. What is being tested here is the REPORTING,
        # and a piece that fails acceptance is exactly when the reporting has
        # to be right -- so the lines are asserted on a failing run.
        assert run(art / "specks.png", "-o", lib, "--size", 6, "--no-verify",
                   "--max-dropped-pct", 90) == 1
        lines = [ln for ln in capsys.readouterr().out.splitlines()
                 if "DROPPED" in ln]
        assert lines, "the dropped tones must still be listed"
        blob = "\n".join(lines)
        assert "mm2" in blob, "the dropped AMOUNT must be an area, in mm2"
        assert "tone total" in blob, \
            "the tone's own pixel census must be labelled as a total"


# ===========================================================================
# 16. --dry-run, discovery reporting, and the case claim
# ===========================================================================

class TestDryRunWritesNothing:
    def test_a_dry_run_writes_no_image_and_no_working_directory(
            self, art, tmp_path):
        lib = lib_of(tmp_path)
        before = sorted(p.resolve() for p in tmp_path.rglob("*.png"))
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10, "--no-verify",
                   "--dry-run") == 0
        assert sorted(p.resolve() for p in tmp_path.rglob("*.png")) == before
        assert not lib.exists()
        assert not list(tmp_path.glob(bl.STAGE_PREFIX + "*")), \
            "a dry run stages in the system temp and leaves nothing beside -o"


class TestDiscoveryReporting:
    def test_a_directory_one_level_too_high_names_the_subdirectories(
            self, tmp_path, capsys):
        top = tmp_path / "top"
        _png(top / "art" / "a.png", [((8, 8, 55, 31), SILK)])
        rc = run(top, "-o", lib_of(tmp_path), "--no-verify")
        assert rc == 3
        cap = capsys.readouterr()
        blob = cap.out + cap.err
        assert str(top / "art") in blob and "--recursive" in blob, \
            "discover() already collected the sub-directories; run() threw " \
            "them away"

    def test_a_non_image_file_in_a_source_directory_is_named(
            self, tmp_path, capsys):
        d = tmp_path / "src"
        _png(d / "a.png", [((8, 8, 55, 31), SILK)])
        (d / "logo.tif").write_bytes(b"II*\x00")
        assert run(d, "-o", lib_of(tmp_path), "--size", 10, "--no-verify") == 0
        assert "logo.tif" in capsys.readouterr().out, \
            "naming a .tif explicitly errors; dropping it in a folder must " \
            "not be silent"

    def test_the_sidecar_is_not_reported_as_an_ignored_file(self, tmp_path,
                                                            capsys):
        d = tmp_path / "src"
        _png(d / "a.png", [((8, 8, 55, 31), SILK)])
        (d / bl.SIDECAR_NAME).write_text("schema = 1\n", encoding="utf-8")
        assert run(d, "-o", lib_of(tmp_path), "--size", 10, "--no-verify") == 0
        assert "ignored" not in capsys.readouterr().out.lower()


def _fs_case_insensitive(d: Path) -> bool:
    p = d / "CaseProbe.tmp"
    p.write_text("x", encoding="utf-8")
    try:
        return (d / "caseprobe.tmp").exists()
    finally:
        p.unlink()


class TestCaseClaim:
    def test_the_case_insensitivity_claim_is_probed_not_asserted(
            self, tmp_path, capsys):
        d = tmp_path / "src"
        _png(d / "Logo.png", [((8, 8, 55, 31), SILK)])
        _png(d / "logo.png", [((6, 6, 57, 33), GOLD)])
        assert run(d, "-o", lib_of(tmp_path), "--size", 10, "--no-verify") == 2
        err = capsys.readouterr().err
        assert "COLLISION" in err
        if _fs_case_insensitive(tmp_path):
            assert "case-insensitive" in err
        else:
            assert "would keep only one of them" not in err, \
                "on case-sensitive ext4 that sentence is simply false"
            assert "case-sensitive" in err


# ===========================================================================
# 19. AN INTERRUPT -- a run that is stopped must never leave a hole
# ===========================================================================

MARK = "PREVIOUS GOOD CONTENT"


def _three_installed(tmp_path, names=("alpha", "bravo", "charlie")):
    """A three-piece library whose footprints each carry a recognisable
    previous content, and a source tree that would UPDATE all three."""
    d = tmp_path / "src"
    for i, n in enumerate(names):
        _png(d / f"{n}.png", [((8, 8, 50 + i, 31), SILK)])
    lib = lib_of(tmp_path)
    assert run(d, "-o", lib, "--size", 20, "--no-verify") == 0
    for f in sorted(lib.glob("*.kicad_mod")):
        f.write_text(f"{MARK} {f.stem}\n", encoding="utf-8")
    return d, lib


def _state(lib: Path, names) -> dict[str, str]:
    """old / new / GONE, per footprint, straight off the disk."""
    out = {}
    for n in names:
        f = lib / f"{n}_20mm.kicad_mod"
        if not f.exists():
            out[n] = "GONE"
        else:
            out[n] = "old" if MARK in f.read_text(encoding="utf-8") else "new"
    return out


ABC = ("alpha", "bravo", "charlie")


class TestAnInterruptLeavesEveryFootprintOldOrNew:
    """THE DEFECT AND ITS THREE ATTEMPTED FIXES.

    Round 2 reproduced it: the install stashed the incumbent into
    stage/.pre_install, INSIDE the staging TemporaryDirectory, and caught only
    OSError. A KeyboardInterrupt is not an OSError, so it walked out through
    the `with`, __exit__ rmtreed the stage, and the stashed original went with
    it -- alpha new, charlie old, bravo_20mm.kicad_mod GONE. Not old, not new:
    deleted.

    Rounds 3 and 4 answered with machinery: an undo directory outside the
    stage, a rollback behind a `committed` flag, an audit that read the disk
    rather than the intent, a guard around the audit for a SECOND Ctrl-C
    arriving during the unwind, and a guard around the report of that. Roughly
    330 lines, all of it correct, all of it existing to survive a hole that
    only existed because something had been moved aside.

    ROUND 5 REMOVED THE HOLE INSTEAD. The incumbent is never moved, so
    os.replace is the only thing that ever touches a target and it is atomic:
    at no instant is a footprint absent. There is nothing to preserve, nothing
    to restore, nothing to sweep, and no rollback that could misreport itself.
    These tests are what is left to check -- the property, not the machinery.
    """

    def _interrupt_at(self, monkeypatch, exc, nth=2):
        real = bl._install
        calls = []

        def boom(src, dst):
            calls.append(Path(dst).name)
            if len(calls) == nth:
                raise exc
            return real(src, dst)

        monkeypatch.setattr(bl, "_install", boom)
        return calls

    @pytest.mark.parametrize("exc", [KeyboardInterrupt(), SystemExit(3),
                                     MemoryError()],
                             ids=["ctrl-c", "sysexit", "oom"])
    def test_no_footprint_is_ever_missing_whatever_stops_the_run(
            self, tmp_path, monkeypatch, exc):
        """Not only KeyboardInterrupt. The old code caught OSError and let
        every other BaseException walk out through a rmtree."""
        d, lib = _three_installed(tmp_path)
        self._interrupt_at(monkeypatch, exc)
        try:
            bl.main([str(d), "-o", str(lib), "--size", "20", "--no-verify"])
        except BaseException:                           # noqa: BLE001
            pass                        # main() turns Ctrl-C into exit 130
        got = _state(lib, ABC)
        assert "GONE" not in got.values(), f"a footprint was destroyed: {got}"
        assert set(got.values()) <= {"old", "new"}, got

    def test_an_interrupt_before_anything_was_installed_changes_nothing(
            self, tmp_path, monkeypatch):
        d, lib = _three_installed(tmp_path)
        before = snapshot(lib)
        self._interrupt_at(monkeypatch, KeyboardInterrupt(), nth=1)
        assert run(d, "-o", lib, "--size", 20, "--no-verify") == 130
        assert snapshot(lib) == before, \
            "not merely identical bytes -- not written at all"

    def test_it_names_what_landed_and_admits_the_journal_is_stale(
            self, tmp_path, monkeypatch, capsys):
        """A real Ctrl-C used to produce a bare exit 130 with one footprint
        fewer than before the run. Nothing is missing now, but the run is
        still abandoned before the journal is written, and that is worth
        saying because it is the only lasting consequence left."""
        d, lib = _three_installed(tmp_path)
        self._interrupt_at(monkeypatch, KeyboardInterrupt(), nth=3)
        assert run(d, "-o", lib, "--size", 20, "--no-verify") == 130
        err = capsys.readouterr().err
        assert "PART WAY THROUGH THE INSTALL" in err
        got = _state(lib, ABC)
        landed = sorted(n for n, s in got.items() if s == "new")
        assert landed, "the test did not get far enough to install anything"
        for n in landed:
            assert f"{n}_20mm" in err, f"{n} landed but was not named:\n{err}"
        assert "was NOT written" in err
        # It may SAY nothing needed restoring; it must never CLAIM a rollback
        # or a restoration happened. Those were the sentences round 3 printed
        # over a footprint it had destroyed.
        low = err.lower()
        for claim in ("was rolled back", "rolled back:", "were restored",
                      "restored to how it was",
                      "byte-identical to how it started"):
            assert claim not in low, f"{claim!r} in:\n{err}"

    def test_the_untouched_journal_still_describes_the_library(
            self, tmp_path, monkeypatch):
        """The journal is not rewritten by an abandoned run, so it still says
        what it said. That stays TRUE here only because nothing was deleted:
        every name it lists is still on disk."""
        d, lib = _three_installed(tmp_path)
        jf = lib.with_name(lib.name + ".build.json")
        before = jf.read_bytes()
        self._interrupt_at(monkeypatch, KeyboardInterrupt())
        run(d, "-o", lib, "--size", 20, "--no-verify")
        assert jf.read_bytes() == before
        j = json.loads(before)
        assert sorted(j["produced"]) == ["alpha_20mm", "bravo_20mm",
                                         "charlie_20mm"]
        for n in j["produced"]:
            assert (lib / f"{n}.kicad_mod").is_file(), \
                "the journal names a footprint that is not on disk"

    def test_a_real_sigint_to_a_real_process_leaves_no_hole(self, tmp_path):
        """Not a raised exception: a SIGINT delivered by the operating system
        to a separate process, which is what Ctrl-C actually is. The signal
        can land on any bytecode boundary, including inside os.replace."""
        if os.name == "nt":
            pytest.skip("SIGINT here is not the POSIX arrangement")
        import signal                                   # noqa: PLC0415
        import subprocess                               # noqa: PLC0415
        import textwrap                                 # noqa: PLC0415

        d, lib = _three_installed(tmp_path)
        driver = tmp_path / "driver.py"
        driver.write_text(textwrap.dedent(f"""
            import importlib, os, signal, sys
            sys.path.insert(0, {str(TOOLS)!r})
            bl = importlib.import_module({bl.__name__!r})
            real, calls = bl._install, []
            def boom(src, dst):
                calls.append(1)
                if len(calls) == 2:
                    os.kill(os.getpid(), signal.SIGINT)   # a REAL signal
                return real(src, dst)
            bl._install = boom
            sys.exit(bl.main([{str(d)!r}, "-o", {str(lib)!r},
                              "--size", "20", "--no-verify"]))
        """), encoding="utf-8")
        p = subprocess.run([sys.executable, str(driver)],
                           capture_output=True, text=True, timeout=600)

        got = _state(lib, ABC)
        assert "GONE" not in got.values(), \
            f"SIGINT destroyed a footprint: {got}\n{p.stderr}"
        assert p.returncode in (130, -signal.SIGINT), \
            f"rc={p.returncode}\n{p.stderr}"
        assert "INTERRUPTED" in p.stderr.upper(), \
            f"a real Ctrl-C must not exit in silence:\n{p.stderr}"
        # ...and the library holds footprints and nothing else: the
        # cross-device temporary is unlinked even on this path.
        assert all(f.name.endswith(".kicad_mod") and not f.name.startswith(".")
                   for f in lib.iterdir()), sorted(p.name for p in lib.iterdir())

    def test_the_machinery_that_existed_to_repair_holes_is_gone(self):
        """Deleted, not merely unused. Every one of these was a path that
        could destroy or misdescribe a footprint, and two of them did."""
        for gone in ("_preserve", "_restore", "_undo", "_audit", "_audit_row",
                     "_safe_audit", "_unwind", "_report_unwind",
                     "_safe_report_unwind", "_state_lines", "_same_bytes",
                     "_pid_alive", "_sweep_stale_stages", "_make_stage",
                     "_make_undo_dir", "_work_root", "_atomic_install",
                     "CLEAN_STATES", "UNDO_PREFIX", "STALE_STAGE_SECONDS"):
            assert not hasattr(bl, gone), f"{gone} is still here"

    def test_no_run_record_makes_a_rollback_claim_at_all(
            self, art, tmp_path):
        """With nothing displaced there is no rollback, so a key that could
        assert one is a key that could be wrong."""
        lib = lib_of(tmp_path)
        assert run(art / "silk_bar.png", "-o", lib, "--size", 10,
                   "--no-verify") == 0
        j = journal(lib)
        for key in ("rolled_back", "rollback_errors", "disk_state",
                    "unrecoverable", "recoverable_originals",
                    "swept_stage_dirs", "held_undo_dirs"):
            assert key not in j, f"{key} survived in the run record"
        assert j["installed"] == ["silk_bar_10mm"]


# ===========================================================================
# 21. CONTAINMENT -- nothing this tool writes can become its own input
# ===========================================================================

class TestNothingItWritesIsEverASource:
    """The three-identical-runs reproduction lives in TestSourceTreeIsReadOnly
    with its siblings; this is the regression the fix for it caused."""

    def test_the_standard_art_and_out_sibling_layout_builds(self, tmp_path):
        """THE ART-TREE REGRESSION. The preview guard refused a destination
        inside a source directory OR ITS PARENT, and `source_dirs` in the
        journal made that refusal permanent for the library once it had been
        recorded -- so the ordinary

            work/art/*.png   ->   work/out/Lib.pretty

        layout became unbuildable for that checkout, forever. Both the rule
        and the memory are gone."""
        work = tmp_path / "work"
        art = work / "art"
        _png(art / "alpha.png", [((8, 8, 55, 31), SILK)])
        lib = work / "out" / "Lib.pretty"
        for i in range(3):
            assert run(art, "-o", lib, "--size", 20, "--no-verify") == 0, i
        assert {f.stem for f in lib.glob("*.kicad_mod")} == {"alpha_20mm"}
        assert "source_dirs" not in journal(lib), \
            "the memory that made the refusal permanent is gone"
