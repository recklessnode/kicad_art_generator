"""Palettes that are KNOWN BAD, committed so that the checks can be shown to fail.

A validator with no failing input is a validator nobody has tested. These two
are the exact tables the repair was written against, and
tests/test_palette_tonemap.py asserts that `Palette.validate()` returns a
non-empty list for both. If either one ever starts passing, the check has been
weakened and the test says so.
"""

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from palette import TONE_IDS, Palette, Tone  # noqa: E402

# The purple table exactly as tools/fab_profiles.tone_anchors("purple")
# computed it before that function was deleted. Transcribed from a run of it,
# not imported, because the function no longer exists -- the point of a
# known-bad fixture is that it survives the removal of the thing that made it.
#
# Its defect is not the numbers: it is that T5 -- the tone that DRAWS NOTHING --
# is the darkest entry, so black ink resolves to it by proximity and is erased.
# Measured: rgb(0,0,0) sits 75.14 weighted-Lab units from T5 and nearer to it
# than to anything else in the table.
_PURPLE_CODED_RGB = {
    "T1": (238, 238, 232),
    "T2": (198, 158, 72),
    "T3": (196, 176, 126),
    "T4": (148, 116, 136),
    "T5": (86, 48, 124),
    "T6": (116, 65, 167),
    "T7": (101, 56, 146),
}

# The shipped black table (w0_spike.TONES), which has the same defect for the
# same reason: T5 at L* 8.87 is the darkest tone the process makes and the
# corpus blacks sit below it.
_BLACK_RGB = {
    "T1": (235, 235, 230),
    "T2": (205, 165, 75),
    "T3": (200, 180, 130),
    "T4": (170, 150, 105),
    "T5": (25, 25, 28),
    "T6": (44, 41, 36),
    "T7": (33, 32, 31),
}

_NAMES = {"T1": "silk white", "T2": "ENIG gold", "T3": "bare FR4",
          "T4": "FR4 + buried", "T5": "black mask", "T6": "mask over copper",
          "T7": "mask + buried"}


def _make(mask, table, provenance="estimated"):
    return Palette(
        mask=mask, silk="white", finish="ENIG", substrate="FR4",
        tones=tuple(Tone(id=t, name=_NAMES[t], rgb=table[t],
                         emits=(t != "T5"), inner=(t in ("T4", "T7")),
                         provenance=provenance) for t in TONE_IDS))


PURPLE_CODED = _make("purple", _PURPLE_CODED_RGB)
BLACK_AGAINST_DARK_INK = _make("black", _BLACK_RGB)

# A THIRD fixture, and the one that catches a lazy fix: a table with TWO
# non-drawing tones. Nothing in the corpus produces it, which is exactly why a
# structural check needs it -- rule 1 of validate() would otherwise never be
# exercised by any input this repo can generate.
_TWO_BLANKS = Palette(
    mask="black", silk="white", finish="ENIG", substrate="FR4",
    tones=tuple(Tone(id=t, name=_NAMES[t], rgb=_BLACK_RGB[t],
                     emits=(t not in ("T5", "T7")),
                     inner=(t in ("T4", "T7")), provenance="estimated")
                for t in TONE_IDS))
TWO_NON_DRAWING_TONES = _TWO_BLANKS
