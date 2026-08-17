#!/usr/bin/env python3
"""Does the halo fix erode genuine thin features? Synthetic, exact, no assets.

Two things have to be true at once and they pull in opposite directions:

  A. A coverage-antialiased boundary between two palette tones must produce
     ONLY those two tones. No third tone anywhere along it.
  B. A genuine line one pixel wide -- the fabrication floor, 0.15 mm silk on a
     raster scaled so 1 px == 0.15 mm -- must survive, at every sub-pixel
     offset and in every orientation.

Both are checked here against analytically antialiased test images, so the
coverage values are exact and the result does not depend on a renderer.

Run:  python3 tests/test_halo.py       (or under pytest)
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image

_TOOLS = pathlib.Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from w0_spike import TONES, quantise                       # noqa: E402

T = {t[0]: i for i, t in enumerate(TONES)}
RGB = {t[0]: np.array(t[2], dtype=np.float64) for t in TONES}

# 1 px == the 0.15 mm silkscreen minimum feature. Every width below is in px and
# therefore also in units of the fabrication floor.
FLOOR_MM = 0.15


# --------------------------------------------------------------- image makers
def _compose(cov, fg, bg):
    """Coverage -> sRGB, blended the way every 2-D renderer blends: in sRGB."""
    img = bg[None, None, :] + cov[..., None] * (fg - bg)[None, None, :]
    a = np.full(cov.shape + (1,), 255.0)
    return Image.fromarray(np.concatenate([img, a], -1).round().astype(np.uint8),
                           "RGBA")


def edge_image(h, w, x_edge, left="T1", right="T2"):
    """Vertical antialiased boundary at sub-pixel position x_edge."""
    x = np.arange(w)
    cov = np.clip(x_edge - x, 0.0, 1.0)          # fraction of the cell left of edge
    cov = np.broadcast_to(cov, (h, w)).copy()
    return _compose(cov, RGB[left], RGB[right])


def _anchor_patch(cov, tone, side=8):
    """Stamp a solid block of `tone` into a corner.

    Real artwork never contains a tone ONLY as a sub-pixel sliver -- a stroke is
    drawn in an ink that is also used somewhere with area. The quantiser relies
    on that: a blend endpoint has to be an established tone, because the dark
    end of the palette is too degenerate to attribute a black edge otherwise.
    Testing a thin line with no solid ink of the same tone anywhere would be
    testing a case the fix openly says it cannot resolve.
    """
    cov[:, :side] = 1.0                    # left gutter; never measured
    return cov


def line_image(h, w, centre, width, bg="T5", fg="T1", axis="v", patch=True):
    """A line of exact `width` px centred at `centre`, exact box coverage."""
    n = w if axis == "v" else h
    lo, hi = centre - width / 2.0, centre + width / 2.0
    k = np.arange(n)
    cov = np.clip(np.minimum(hi, k + 1) - np.maximum(lo, k), 0.0, 1.0)
    cov = (np.broadcast_to(cov, (h, w)).copy() if axis == "v"
           else np.broadcast_to(cov[:, None], (h, w)).copy())
    if patch:
        _anchor_patch(cov, fg)
    return _compose(cov, RGB[fg], RGB[bg])


def diag_line_image(n, width, offset=0.0, bg="T5", fg="T1", ss=16, patch=True):
    """A 45-degree line of `width` px, coverage by 16x16 supersampling."""
    o = (np.arange(ss) + 0.5) / ss
    yy, xx = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    cov = np.zeros((n, n))
    for dy in o:
        for dx in o:
            py, px = yy + dy, xx + dx
            d = np.abs(px - py + offset) / np.sqrt(2.0)
            cov += (d <= width / 2.0)
    cov /= (ss * ss)
    if patch:
        _anchor_patch(cov, fg)
    return _compose(cov, RGB[fg], RGB[bg])


# --------------------------------------------------------------- helpers
def tones_present(labels, opaque):
    v, c = np.unique(labels[opaque], return_counts=True)
    return {TONES[int(i)][0]: int(n) for i, n in zip(v, c) if i >= 0}


N = 48
GUTTER = 8          # solid-ink strip that establishes the tone
MEASURE = 12        # everything left of this column is ignored


def run_widths(axis, widths, offsets, fg="T1", bg="T5", **kw):
    """-> [(width_px, offset, surviving_px, peak_width_px, tones)] per offset.

    Survival is counted only right of the gutter, so the solid patch that makes
    the tone established cannot be mistaken for the line surviving.
    """
    rows = []
    for wpx in widths:
        for off in offsets:
            centre = N / 2.0 + off
            img = (line_image(N, N, centre, wpx, axis=axis, fg=fg, bg=bg)
                   if axis in "vh" else
                   diag_line_image(N, wpx, offset=off, fg=fg, bg=bg))
            lab, op, _ = quantise(img, **kw)
            hit = (lab == T[fg])
            hit[:, :MEASURE] = False
            got = int(hit.sum())
            if axis == "v":
                per = hit.sum(1)
            elif axis == "h":
                per = hit.sum(0)
            else:
                per = np.array([got / max(N - MEASURE, 1)])
            rows.append((wpx, off, got, float(per.max()) if per.size else 0.0,
                         tones_present(lab, op)))
    return rows


# Every polarity that matters: light ink on dark, dark ink on light, and two
# mid-palette pairs. The gamma bias only bites on the dark-on-light cases, so a
# test that only ever draws white silk on black mask proves nothing.
POLARITIES = [("T1", "T5", "silk white on black mask"),
              ("T5", "T1", "black mask on silk white"),
              ("T5", "T2", "black mask on ENIG gold"),
              ("T2", "T1", "ENIG gold on silk white"),
              ("T6", "T2", "mask-over-copper on gold")]


# --------------------------------------------------------------- the tests
def test_boundary_emits_no_third_tone():
    """A. Antialiased T1|T2 edge -> exactly {T1, T2}, at every sub-pixel offset."""
    bad = []
    for off in np.arange(0.0, 1.0, 0.1):
        img = edge_image(64, 64, 32.0 + off)
        lab, op, st = quantise(img)
        got = tones_present(lab, op)
        extra = set(got) - {"T1", "T2"}
        if extra:
            bad.append((round(float(off), 2), got))
    assert not bad, f"boundary invented a third tone at offsets {bad}"


def test_boundary_third_tone_exists_without_the_fix():
    """The artefact this exists to kill is real: mix=False reproduces it."""
    img = edge_image(64, 64, 32.5)
    lab, op, _ = quantise(img, mix=False)
    got = tones_present(lab, op)
    assert set(got) - {"T1", "T2"}, ("expected the unfixed quantiser to emit a "
                                     f"spurious tone, got only {got}")


def test_one_pixel_line_survives_every_offset_orientation_and_polarity():
    """B. A 1.0 px line at the fabrication floor is never erased."""
    offs = [0.0, 0.1, 0.25, 0.33, 0.5, 0.67, 0.75, 0.9]
    dead = []
    for fg, bg, nm in POLARITIES:
        for axis in ("v", "h", "d"):
            for wpx, off, got, mx, _ in run_widths(axis, [1.0], offs, fg=fg, bg=bg):
                if got == 0:
                    dead.append((nm, axis, round(off, 2)))
    assert not dead, f"1.0 px line ERASED at {dead}"


def test_coverage_is_read_in_srgb_not_lab():
    """The dark-on-light case is the one a Lab-space split gets wrong.

    Measured before the correction: a 1 px black stroke on ENIG gold survived
    1 of 4 sub-pixel offsets. Guard it directly so a future refactor that moves
    the split back into Lab fails here instead of on a fabricated board.
    """
    offs = [0.0, 0.25, 0.5, 0.75]
    live = sum(1 for r in run_widths("v", [1.0], offs, fg="T5", bg="T2") if r[2] > 0)
    assert live == len(offs), f"dark 1 px stroke on gold survived only {live}/{len(offs)}"


def test_mix_bias_points_at_the_minority_tone_both_polarities():
    """The thin-ink knob must widen the thin thing, not the low-index tone."""
    offs = [0.0, 0.25, 0.5, 0.75]
    for fg, bg, nm in (("T1", "T5", "light on dark"), ("T5", "T1", "dark on light")):
        base = sum(1 for r in run_widths("v", [0.6], offs, fg=fg, bg=bg) if r[2] > 0)
        more = sum(1 for r in run_widths("v", [0.6], offs, fg=fg, bg=bg, mix_bias=0.25)
                   if r[2] > 0)
        assert more >= base, f"{nm}: mix_bias made thin ink WORSE ({base} -> {more})"


def test_mix_bias_never_resurrects_the_halo():
    """Halo removal is decoupled from the split. Sweep the knob and prove it."""
    for bias in (0.0, 0.1, 0.2, 0.3, 0.4):
        for off in (0.0, 0.25, 0.5, 0.75):
            lab, op, _ = quantise(edge_image(64, 64, 32.0 + off), mix_bias=bias)
            extra = set(tones_present(lab, op)) - {"T1", "T2"}
            assert not extra, f"mix_bias={bias} offset={off} brought back {extra}"


def test_sub_pixel_lines_are_a_documented_threshold_not_a_surprise():
    """Below 1 px the guarantee stops. Record exactly where, do not pretend."""
    offs = [0.0, 0.25, 0.5, 0.75]
    surv = {}
    for wpx in (0.4, 0.5, 0.6, 0.75, 0.9, 1.0, 1.5, 2.0):
        rows = run_widths("v", [wpx], offs)
        surv[wpx] = sum(1 for r in rows if r[2] > 0) / len(rows)
    assert surv[1.0] == 1.0 and surv[1.5] == 1.0 and surv[2.0] == 1.0
    assert surv[0.4] < 1.0, "a 0.4 px line should NOT survive a 0.5 split"


def test_pre_blur_is_what_erodes_thin_features():
    """smooth=1.0 (the old default) destroys the 1 px guarantee. Proof."""
    offs = [0.0, 0.25, 0.5, 0.75]
    live_sharp = sum(1 for r in run_widths("v", [1.0], offs, smooth=0.0) if r[2] > 0)
    live_blur = sum(1 for r in run_widths("v", [1.0], offs, smooth=1.0) if r[2] > 0)
    assert live_sharp == len(offs)
    assert live_blur < live_sharp, ("expected the old smooth=1.0 default to erase "
                                    "1 px lines; it did not, revisit the default")


def test_deterministic():
    img = line_image(40, 40, 20.3, 1.0)
    a, _, _ = quantise(img)
    for _ in range(3):
        b, _, _ = quantise(img)
        assert np.array_equal(a, b)


def test_signature_and_return_shape_unchanged():
    img = line_image(8, 8, 4.0, 2.0)
    out = quantise(img, 128, 0)                      # positional, as before
    assert isinstance(out, tuple) and len(out) == 3
    labels, mask, stats = out
    assert labels.shape == (8, 8) and mask.shape == (8, 8)
    for k in ("opaque_px", "assigned_px", "dropped_px", "per_tone"):
        assert k in stats


# --------------------------------------------------------------- report
def _report():
    print("=" * 78)
    print("A. ANTIALIASED TONE BOUNDARY  (T1 silk white | T2 ENIG gold, 64x64)")
    print("=" * 78)
    print(f"  {'edge x':>8}  {'without fix (mix=False)':<34}  with fix")
    for off in (0.0, 0.25, 0.5, 0.75):
        i = edge_image(64, 64, 32.0 + off)
        lb, op, _ = quantise(i, mix=False)
        la, oa, _ = quantise(i)
        f = lambda d: " ".join(f"{k}={v}" for k, v in d.items())
        print(f"  {32.0+off:>8.2f}  {f(tones_present(lb, op)):<34}  "
              f"{f(tones_present(la, oa))}")

    offs = [0.0, 0.25, 0.5, 0.75]
    print()
    print("=" * 78)
    print("B. GENUINE THIN LINE, EVERY ORIENTATION AND POLARITY")
    print(f"   1 px == {FLOOR_MM} mm == the silkscreen minimum feature")
    print("   'survived' counts sub-pixel offsets where the line still exists")
    print("=" * 78)
    print(f"  {'polarity':<28} {'width px':>8} {'= mm':>6} "
          f"{'v':>5} {'h':>5} {'d':>5}   verdict")
    for fg, bg, nm in POLARITIES:
        for wpx in (0.5, 0.75, 1.0, 1.5, 2.0):
            live = {}
            for axis in ("v", "h", "d"):
                rows = run_widths(axis, [wpx], offs, fg=fg, bg=bg)
                live[axis] = sum(1 for r in rows if r[2] > 0)
            ok = all(v == len(offs) for v in live.values())
            verdict = ("PRESERVED" if ok else
                       ("below floor - expected" if wpx < 1.0 else "*** ERODED ***"))
            print(f"  {nm:<28} {wpx:>8.2f} {wpx*FLOOR_MM:>6.3f} "
                  f"{live['v']:>3}/4 {live['h']:>3}/4 {live['d']:>3}/4   {verdict}")

    print()
    print("=" * 78)
    print("C. THE PRE-BLUR IS THE ERODER  (1.0 px silk line on black mask)")
    print("=" * 78)
    for sm in (0.0, 0.5, 1.0):
        rows = run_widths("v", [1.0], offs, smooth=sm)
        live = sum(1 for r in rows if r[2] > 0)
        note = "  <-- the OLD default" if sm == 1.0 else ""
        print(f"  smooth={sm:<4} survived {live}/{len(rows)}   "
              f"px kept per offset: {[r[2] for r in rows]}{note}")

    print()
    print("=" * 78)
    print("D. mix_bias TRADES SUB-PIXEL INK FOR EDGE POSITION, NEVER FOR HALO")
    print("=" * 78)
    print(f"  {'bias':>6}  {'light 0.6px':>12} {'dark 0.6px':>11} "
          f"{'light 1.0px':>12} {'dark 1.0px':>11}   third tone on a T1|T2 edge?")
    for bias in (0.0, 0.1, 0.2, 0.3):
        def liv(w, fg, bg):
            return sum(1 for r in run_widths("v", [w], offs, fg=fg, bg=bg,
                                             mix_bias=bias) if r[2] > 0)
        extra = set()
        for off in offs:
            lab, op, _ = quantise(edge_image(64, 64, 32.0 + off), mix_bias=bias)
            extra |= set(tones_present(lab, op)) - {"T1", "T2"}
        print(f"  {bias:>6.2f}  {liv(0.6,'T1','T5'):>9}/4 {liv(0.6,'T5','T1'):>8}/4 "
              f"{liv(1.0,'T1','T5'):>9}/4 {liv(1.0,'T5','T1'):>8}/4   "
              f"{sorted(extra) if extra else 'none'}")


if __name__ == "__main__":
    _report()
    print()
    fails = 0
    for nm, fn in sorted(globals().items()):
        if nm.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {nm}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {nm}: {e}")
    print(f"\n  {fails} failure(s)")
    sys.exit(1 if fails else 0)
