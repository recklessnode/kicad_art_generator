#!/usr/bin/env python3
"""Outline (TrueType) faces for coupon marking and labels: resolution,
coverage, KiCad-exact geometry, and floor-solved cap heights.

WHY THIS IS BUILT AROUND A KICAD SUBPROCESS
-------------------------------------------
The stroke-font pipeline could reason about its own geometry because the pen
is a parameter.  An outline face has no pen: stem width, counter width and
inter-glyph gap are all emergent properties of letterforms this repo does not
own.  Three facts about how KiCad renders them, all measured on this rig
(2026-08-30, KiCad 10.0.0, tools/kicad_text_probe.py):

  * KERNING IS APPLIED (HarfBuzz).  'AWAVA' in Ubuntu at size 10 measures
    47.554 mm of ink; bare hmtx advances predict 49.758 mm.  Geometry built
    from advances alone overstates inter-glyph gaps -- the exact quantity the
    silk floor binds.
  * THE EM SCALE IS PER-FACE and not a published constant: measured em/size
    is 1.3985 (Ubuntu), 1.5674 (Ubuntu Mono), 1.3961 (Consolas), 1.4009
    (Segoe UI), 1.3991 (Orbitron).  Guessing a universal 1.4 mis-sizes
    Ubuntu Mono by 12%.
  * The BASELINE of a default-vertical-justify text sits 0.4150 x size below
    the anchor, for every face and every string probed.  Re-derived from the
    'H' probe on every run rather than trusted.

So the authority on what a faced string looks like is KiCad itself:
tools/kicad_text_probe.py (KiCad's python, the only interpreter here that can
import pcbnew) renders each (face, text) once at a reference size and this
module scales the returned polygons linearly -- outline text is a linear
transform of the em, so one probe per string serves every cap height.

SILENT SUBSTITUTION, AND THE TWO GATES AGAINST IT
-------------------------------------------------
KiCad resolves a face name through fontconfig and SUBSTITUTES silently when
it does not resolve -- ResolveFont() returns True even for a nonsense name.
Two independent gates make that loud instead:

  gate 1  the requested face's font FILE must exist on this machine and its
          name table must carry exactly the requested family name
          (require_face / _font).
  gate 2  the probed 'H' is fingerprinted against fontTools reading the SAME
          FILE: cap-height-normalised ink width, left sidebearing, baseline
          position, and the narrowest stem measured by two independent
          renderers (KiCad polygons vs flattened glyf outlines).  A
          substituted or wrong-style face fails the fingerprint, and
          calibration() raises.

Every helper here raises OutlineFontError rather than returning a guess; the
callers (gen_marking.py, coupon_ladders.py, coupon_blocks.py) let it
propagate, so a build with an unresolvable face DIES instead of shipping
substituted letterforms.

This module needs the venv (fontTools, shapely via ink_measure).  It must
never be imported by build_coupons.py, which runs under KiCad's python --
that script consumes the JSON manifests the venv tools write instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import ink_measure as IM                                    # noqa: E402

try:
    from fontTools.ttLib import TTFont
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    _FT_WHY = ""
except Exception as _e:                                     # pragma: no cover
    TTFont = None
    _FT_WHY = "%s: %s" % (type(_e).__name__, _e)


class OutlineFontError(RuntimeError):
    """A face that cannot be proven to render as requested. Never a warning."""


# --- the faces --------------------------------------------------------------
# One regular style per family. The FILE is named, not just the family: gate 2
# fingerprints KiCad's rendering against this exact file, so installing a
# different cut of the same family fails the build instead of changing the
# letterforms quietly.
_USER_FONTS = "Users/prael/AppData/Local/Microsoft/Windows/Fonts"
_SYS_FONTS = "Windows/Fonts"
FACES = {
    "Orbitron":    (_USER_FONTS, "Orbitron-Regular.ttf"),
    "Ubuntu":      (_USER_FONTS, "Ubuntu-R.ttf"),
    # NOT UbuntuMono-R.ttf: both are installed and carry the same family
    # name, and KiCad's fontconfig picks the VARIABLE font -- measured, the
    # rendered H stem is 0.9380 mm at size 10 (the [wght] file's default
    # instance) where the static Regular would draw 1.0971 mm. The registry
    # must name the file KiCad actually uses or gate 2 refuses the build.
    "Ubuntu Mono": (_USER_FONTS, "UbuntuMono[wght].ttf"),
    "Consolas":    (_SYS_FONTS, "consola.ttf"),
    "Segoe UI":    (_SYS_FONTS, "segoeui.ttf"),
}

REF_SIZE = 10.0          # mm; every probe renders here and is scaled linearly

# Fingerprint tolerances, mm at REF_SIZE (so /10 at a 1 mm size). 0.02 mm at
# size 10 is 0.2% -- far inside the difference between any two real faces
# (the closest pair measured, Segoe UI vs the silent fallback, differ by
# 0.19 mm in cap height alone) and far outside flattening error (0.002 mm).
_FP_TOL_MM = 0.02
# Stem agreement between the two renderers: KiCad flattens ERROR_INSIDE
# (under-reads ink) and the fontTools path flattens by subdivision, so allow
# 0.03 mm at REF_SIZE -- 0.3% of a stem, two orders under any style step.
_STEM_TOL_MM = 0.03


def _roots() -> list[str]:
    if sys.platform == "win32":
        return ["C:/"]
    return ["/mnt/c/"]


def _win(path: str) -> str:
    """A path KiCad's WINDOWS python can open, whatever OS we run under."""
    if path.startswith("/mnt/c/"):
        return "C:/" + path[len("/mnt/c/"):]
    return path


def font_path(face: str) -> pathlib.Path:
    if face not in FACES:
        raise OutlineFontError(
            "face %r is not in the registry; have %s" % (face, sorted(FACES)))
    sub, fname = FACES[face]
    for root in _roots():
        p = pathlib.Path(root) / sub / fname
        if p.is_file():
            return p
    raise OutlineFontError(
        "face %r: font file %s not found under %s -- the face cannot resolve "
        "and KiCad would SILENTLY SUBSTITUTE. Install the font or fix FACES."
        % (face, fname, " or ".join(_roots())))


def require_face(face: str) -> None:
    """Gate 1: the file exists and its name table says it IS this family."""
    _font(face)


_FONTS: dict[str, "TTFont"] = {}


def _font(face: str):
    if face in _FONTS:
        return _FONTS[face]
    if TTFont is None:
        raise OutlineFontError(
            "fontTools is not importable (%s); run from the venv" % _FT_WHY)
    p = font_path(face)
    f = TTFont(str(p), lazy=True)
    fams = set()
    for rec in f["name"].names:
        if rec.nameID in (1, 16):
            try:
                fams.add(rec.toUnicode())
            except Exception:
                pass
    if face not in fams:
        raise OutlineFontError(
            "%s carries family name(s) %s, not %r -- the registry points at "
            "the wrong file" % (p.name, sorted(fams), face))
    _FONTS[face] = f
    return f


def missing_glyphs(face: str, text: str) -> str:
    """Characters of `text` with NO glyph in `face`'s cmap, '' when covered.

    .notdef fallthrough is exactly the silent-substitution failure shape, so
    a caller must refuse any string for which this is non-empty.
    """
    cmap = _font(face).getBestCmap()
    return "".join(sorted({c for c in text
                           if c not in ("\t",) and ord(c) not in cmap}))


def assert_coverage(face: str, text: str, what: str = "") -> None:
    miss = missing_glyphs(face, text)
    if miss:
        raise OutlineFontError(
            "%s%r cannot be set in %s: no glyph for %s"
            % (("%s: " % what) if what else "", text, face,
               " ".join("U+%04X %r" % (ord(c), c) for c in miss)))


# --- the KiCad subprocess and its cache -------------------------------------

def _kicad_python() -> str:
    env = os.environ.get("KICAD_PYTHON")
    cands = ([env] if env else []) + [
        r"C:/Program Files/KiCad/10.0/bin/python.exe",
        "/mnt/c/Program Files/KiCad/10.0/bin/python.exe",
    ]
    for c in cands:
        if c and pathlib.Path(c).is_file():
            return c
    raise OutlineFontError(
        "KiCad's python was not found (tried %s); set KICAD_PYTHON" % cands)


def _tmpdir() -> pathlib.Path:
    """A directory BOTH pythons can reach: the Windows temp dir."""
    for root in _roots():
        p = pathlib.Path(root) / "Users/prael/AppData/Local/Temp"
        if p.is_dir():
            return p
    return pathlib.Path(tempfile.gettempdir())


_CACHE_NAME = "kicad_text_probe_cache.json"
_cache: dict | None = None


def _font_sig(face: str) -> str:
    p = font_path(face)
    st = p.stat()
    return "%d-%d" % (st.st_size, int(st.st_mtime))


def _cache_path() -> pathlib.Path:
    return _tmpdir() / _CACHE_NAME


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_cache_path().read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _key(face: str, text: str) -> str:
    raw = "\x00".join([face, text, "%g" % REF_SIZE, _font_sig(face)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _probe_many(entries: list[tuple[str, str]]) -> None:
    """Render every uncached (face, text) through KiCad, one subprocess."""
    cache = _load_cache()
    todo = []
    for face, text in entries:
        k = _key(face, text)
        if k not in cache:
            todo.append({"id": k, "face": face, "text": text,
                         "size_mm": REF_SIZE})
    if not todo:
        return
    here = pathlib.Path(__file__).resolve().parent
    script = _win(str(here / "kicad_text_probe.py"))
    d = _tmpdir()
    req = d / "kicad_text_probe_req.json"
    resp = d / "kicad_text_probe_resp.json"
    req.write_text(json.dumps({"entries": todo}), encoding="utf-8")
    if resp.exists():
        resp.unlink()
    r = subprocess.run([_kicad_python(), script, _win(str(req)),
                        _win(str(resp))],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not resp.is_file():
        raise OutlineFontError(
            "kicad_text_probe failed (rc %d):\n%s\n%s"
            % (r.returncode, r.stdout[-2000:], r.stderr[-2000:]))
    got = json.loads(resp.read_text(encoding="utf-8"))["entries"]
    for e in todo:
        if e["id"] not in got:
            raise OutlineFontError("probe returned nothing for %r in %s"
                                   % (e["text"], e["face"]))
        cache[e["id"]] = got[e["id"]]
    _cache_path().write_text(json.dumps(cache), encoding="utf-8")


def prefetch(runs) -> None:
    """Probe a batch of (face, text) pairs in one KiCad launch."""
    uniq = sorted({(f, t) for f, t in runs})
    for f, _t in uniq:
        require_face(f)
    _probe_many(uniq)


class RunInk:
    """KiCad's exact ink for one (face, text) at REF_SIZE.

    Coordinates: mm, y-down, anchor at (0, 0), horizontal justify LEFT,
    vertical justify default.  `outlines` is [(outer, [holes...])].
    """

    def __init__(self, face: str, text: str, raw: dict):
        self.face = face
        self.text = text
        if not raw.get("resolved"):
            raise OutlineFontError("KiCad did not resolve %r" % face)
        if not raw["outlines"]:
            raise OutlineFontError("%r in %s rendered NO ink" % (text, face))
        self.outlines = [([tuple(p) for p in o["outer"]],
                          [[tuple(p) for p in h] for h in o["holes"]])
                         for o in raw["outlines"]]
        self.bbox = tuple(raw["bbox"])

    def parts(self, size: float, dx: float = 0.0, dy: float = 0.0,
              label: str = "") -> list:
        s = size / REF_SIZE
        out = []
        for i, (outer, holes) in enumerate(self.outlines):
            out.append(IM.Part(
                label="%s#%d" % (label or self.text, i),
                pts=[(x * s + dx, y * s + dy) for x, y in outer],
                holes=[[(x * s + dx, y * s + dy) for x, y in h]
                       for h in holes]))
        return out

    def box(self, size: float, dx: float = 0.0, dy: float = 0.0):
        s = size / REF_SIZE
        x0, y0, x1, y1 = self.bbox
        return (x0 * s + dx, y0 * s + dy, x1 * s + dx, y1 * s + dy)


def run_ink(face: str, text: str) -> RunInk:
    require_face(face)
    _probe_many([(face, text)])
    return RunInk(face, text, _load_cache()[_key(face, text)])


# --- calibration and the substitution fingerprint ---------------------------

def _flatten_glyph(font, ch: str, steps: int = 24):
    """Closed contours of one glyph from the FILE, flattened, font units."""
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    pen = DecomposingRecordingPen(gs)
    gs[cmap[ord(ch)]].draw(pen)
    contours, cur = [], []

    def bez(pts):
        # de Casteljau sampling; pts includes the current point first.
        n = len(pts) - 1
        for k in range(1, steps + 1):
            t = k / steps
            q = list(pts)
            for lev in range(n):
                q = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1])
                     for a, b in zip(q, q[1:])]
            cur.append(q[0])

    for op, args in pen.value:
        if op == "moveTo":
            if cur:
                contours.append(cur)
            cur = [args[0]]
        elif op == "lineTo":
            cur.append(args[0])
        elif op == "qCurveTo":
            # TrueType: implied on-curve points between successive off-curve
            # points; the recording pen already gives fully-specified runs
            # only when the font does -- expand the general form.
            pts = list(args)
            prev = cur[-1]
            # split a run of off-curves into quadratic segments
            offs, last = pts[:-1], pts[-1]
            if last is None:            # closed all-off-curve contour
                last = ((offs[0][0] + prev[0]) / 2, (offs[0][1] + prev[1]) / 2)
            seg_start = prev
            for i, off in enumerate(offs):
                if i + 1 < len(offs):
                    nxt = offs[i + 1]
                    end = ((off[0] + nxt[0]) / 2, (off[1] + nxt[1]) / 2)
                else:
                    end = last
                cur_saved = cur
                cur = []
                bez([seg_start, off, end])
                cur_saved.extend(cur)
                cur = cur_saved
                seg_start = end
        elif op == "curveTo":
            prev = cur[-1]
            cur_saved = cur
            cur = []
            bez([prev] + list(args))
            cur_saved.extend(cur)
            cur = cur_saved
        elif op == "closePath":
            if cur:
                contours.append(cur)
                cur = []
    if cur:
        contours.append(cur)
    return contours


def _glyph_parts_mm(font, ch: str, mm_per_unit: float) -> list:
    """The glyph as IM parts in mm, y flipped to board-style y-down."""
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except Exception as e:                                  # pragma: no cover
        raise OutlineFontError("shapely unavailable: %s" % e)
    rings = []
    for c in _flatten_glyph(font, ch):
        pts = [(x * mm_per_unit, -y * mm_per_unit) for x, y in c]
        if len(pts) >= 3:
            rings.append(Polygon(pts).buffer(0))
    if not rings:
        raise OutlineFontError("glyph %r produced no contours" % ch)
    # even-odd: subtract nested rings (counters), union the rest
    rings.sort(key=lambda p: -p.area)
    geo = rings[0]
    for p in rings[1:]:
        if geo.contains(p.representative_point()):
            geo = geo.difference(p)
        else:
            geo = unary_union([geo, p])
    polys = list(geo.geoms) if geo.geom_type == "MultiPolygon" else [geo]
    return [IM.Part(label="ft", pts=list(p.exterior.coords),
                    holes=[list(i.coords) for i in p.interiors])
            for p in polys]


def _min_stem(parts, scan: float) -> float | None:
    m = IM.measure_layer("F.SilkS", parts, floor=scan)
    return m.min_feature.value if m.min_feature else None


class Cal:
    """Per-face calibration: KiCad size <-> physical mm, fingerprint-checked."""

    def __init__(self, face: str):
        self.face = face
        font = _font(face)
        upem = font["head"].unitsPerEm
        cmap = font.getBestCmap()
        glyf = font["glyf"]
        gH = glyf[cmap[ord("H")]]
        ink = run_ink(face, "H")
        x0, y0, x1, y1 = ink.bbox
        h_units = gH.yMax - gH.yMin
        scale = (y1 - y0) / h_units          # mm per font unit at REF_SIZE
        self.mm_per_unit_per_size = scale / REF_SIZE
        self.baseline_per_size = (y1 + gH.yMin * scale) / REF_SIZE
        self.cap_ratio = (gH.yMax * scale) / REF_SIZE   # cap mm per size mm
        self.em_per_size = upem * self.mm_per_unit_per_size

        # gate 2: KiCad's rendering must BE this file's letterforms.
        checks = [
            ("H ink width", x1 - x0, (gH.xMax - gH.xMin) * scale, _FP_TOL_MM),
            ("H left sidebearing", x0, gH.xMin * scale, _FP_TOL_MM),
            ("baseline offset", y1 + gH.yMin * scale, 0.4150 * REF_SIZE,
             _FP_TOL_MM),
        ]
        for name, got, want, tol in checks:
            if abs(got - want) > tol:
                raise OutlineFontError(
                    "face %r FINGERPRINT MISMATCH on %s: KiCad rendered "
                    "%.4f mm where %s predicts %.4f mm (tol %.3f). KiCad has "
                    "substituted another font, or the registry names the "
                    "wrong file." % (face, name, got, name == "baseline offset"
                                     and "the measured constant" or
                                     font_path(face).name, want, tol))
        # stems, by two independent renderers of the same glyph
        k_stem = _min_stem(ink.parts(REF_SIZE), scan=0.35 * REF_SIZE)
        f_stem = _min_stem(_glyph_parts_mm(font, "H", scale),
                           scan=0.35 * REF_SIZE)
        if k_stem is None or f_stem is None:
            raise OutlineFontError(
                "face %r: could not measure the H stem (KiCad %s, fontTools "
                "%s)" % (face, k_stem, f_stem))
        if abs(k_stem - f_stem) > _STEM_TOL_MM:
            raise OutlineFontError(
                "face %r STEM MISMATCH: KiCad renders an H stem of %.4f mm "
                "at size %g, the font file says %.4f mm -- a different style "
                "or family is being substituted."
                % (face, k_stem, REF_SIZE, f_stem))
        self.h_stem_per_size = k_stem / REF_SIZE

    def size_for_cap(self, cap: float) -> float:
        return cap / self.cap_ratio

    def baseline_offset(self, size: float) -> float:
        """Anchor-to-baseline, y-down mm, for a default-vertical text."""
        return self.baseline_per_size * size


_CALS: dict[str, Cal] = {}


def calibration(face: str) -> Cal:
    if face not in _CALS:
        _CALS[face] = Cal(face)
    return _CALS[face]


# --- floor solving ----------------------------------------------------------

def measure_string(face: str, text: str, cap: float, floor: float):
    """LayerInk of `text` at cap height `cap`, judged against `floor`.

    features_below / gaps_below / vanished non-empty means the string AS SET
    goes under the floor.  Gap witnesses are the CLASSIFIED ones: re-entrant
    corners (which no closing can bridge) are discounted by ink_measure and
    reported in rounded_gaps, exactly as verify_art discounts them.
    """
    cal = calibration(face)
    ink = run_ink(face, text)
    return IM.measure_layer("F.SilkS", ink.parts(cal.size_for_cap(cap)),
                            floor=floor)


def narrowest(face: str, text: str, cap: float, scan_ratio: float = 0.45):
    """(min_feature, min_gap) Witnesses inside a wide scan, for REPORTING."""
    cal = calibration(face)
    ink = run_ink(face, text)
    m = IM.measure_layer("F.SilkS", ink.parts(cal.size_for_cap(cap)),
                         floor=max(scan_ratio * cap, 0.31))
    return m.min_feature, m.min_gap


def solved_cap_face(face: str, text: str, floor: float, *,
                    minimum: float = 0.0, margin: float = 0.05,
                    max_iter: int = 6) -> tuple[float, str]:
    """Smallest cap at which every stem, counter and gap of `text` in `face`
    clears `floor` by `margin` -- the outline-face analogue of
    coupon_ladders.solved_cap(), measured off KiCad's own polygons instead of
    solved from stroke metrics (an outline face HAS no stroke metric).

    -> (cap_mm, what bound).  Raises OutlineFontError if it will not converge
    (a face whose letterforms TOUCH never clears any floor at any size).
    """
    assert_coverage(face, text)
    target = floor * (1.0 + margin)
    cap = max(minimum, target)      # a cap under the floor never clears it
    binds = "nothing"
    for _ in range(max_iter):
        m = measure_string(face, text, cap, target)
        bad = []
        if m.min_feature is not None:
            bad.append(("stem/feature %s" % m.min_feature, m.min_feature.value))
        if m.min_gap is not None:
            bad.append(("gap %s" % m.min_gap, m.min_gap.value))
        for w in m.vanished_witnesses:
            # A whole glyph whose THICKEST ink is under the floor (a
            # monolinear digit at a small cap is one component of uniform
            # stroke). The witness value is the max inscribed diameter, so
            # scaling by it is the same linear solve as for a neck.
            bad.append(("vanishing component %s" % w, w.value))
        if m.incomplete:
            raise OutlineFontError("%r in %s: measurement incomplete: %s"
                                   % (text, face, m.incomplete_why))
        if not bad:
            return cap, binds
        what, worst = min(bad, key=lambda b: b[1])
        if worst <= 0:
            raise OutlineFontError(
                "%r in %s has touching or zero-width ink; no cap fixes that"
                % (text, face))
        binds = what
        # linear: the whole string scales with cap. 1.001 covers re-measure
        # jitter at the new size.
        cap = cap * (target / worst) * 1.001
    m = measure_string(face, text, cap, target)
    if m.min_feature is None and m.min_gap is None and not m.vanished:
        return cap, binds
    raise OutlineFontError(
        "%r in %s did not converge on a floor-clearing cap after %d rounds "
        "(last cap %.4f)" % (text, face, max_iter, cap))
