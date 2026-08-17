#!/usr/bin/env python3
"""W0 go/no-go spike: quantiser + compositor only. No emitter, no tracing.

Answers one question: does mapping source art onto the PCB tone palette in a
perceptual space, with the background tone emitted as nothing, produce something
better than the current tool? Everything downstream depends on that being true,
and it is a judgement made by looking, not by a metric.

Deliberately NOT here: contour tracing, geometry simplification, s-expression
emission. Those are W1/W2 and they are pointless if this stage is wrong.

Usage:  python w0_spike.py <image> [<image> ...] -o <outdir>


THE ANTIALIAS HALO, AND WHY THE FIX IS PHOTOMETRIC
--------------------------------------------------
Plain nearest-anchor assignment has one systematic failure, and it dominates
everything downstream. Where two tones meet, the renderer writes a 1-2 px band
of coverage-blended colour. That blend is not near either of its two parents in
Lab -- it is halfway between them -- and halfway between two palette anchors
frequently lands nearest a THIRD anchor. Measured on bitcoin_b at 1200 px:

    T1 silk white    414,249 px   3 polygons
    T2 ENIG gold   1,002,389 px   2 polygons
    T3 bare FR4        3,046 px  841 polygons   <-- 100% halo, 0.2% of the image
                                                    98% of the polygon count

Every one of those 841 T3 regions was measured to be nowhere three pixels
thick. They are not artwork. They are the boundary itself, promoted to a tone.

The fix asks a different question of each pixel. Not "which anchor is nearest"
but "is this colour better explained as a MIXTURE of two anchors than as any
single anchor?" For a coverage-antialiased edge the answer is yes by
construction: the renderer literally computed c = (1-t)*A + t*B. So:

  - find the anchor pair (a, b) whose connecting segment in weighted Lab passes
    closest to the pixel, with the foot of the perpendicular strictly interior;
  - accept it as a MIXTURE if that residual beats the nearest single anchor by
    `mix_ratio` AND is itself small in absolute terms (`mix_max_res`) -- both
    halves are needed, see the constants below;
  - the pixel's label is then RESTRICTED to {a, b}. A third tone becomes
    unreachable, and that restriction is the whole artefact, gone;
  - choose between a and b by the coverage recovered in sRGB, against
    `mix_split`.

Two properties follow, and they are the reason this was chosen over the
morphological alternatives (opening per tone label; dropping small connected
components; snapping near-equidistant pixels to a locally dominant neighbour):

  1. IT NEVER LOOKS AT A NEIGHBOURING PIXEL. The rule is photometric. It
     therefore cannot erode a feature on grounds of being small or thin, which
     is exactly what every morphological rule does. A 1 px stroke drawn in an
     on-palette colour is not even a candidate: its residual from every mixture
     line is large, so it passes through untouched. The palette exists to make
     0.1-0.15 mm strokes survive; a size threshold would have undone that.

  2. HALO REMOVAL AND THE THIN-FEATURE THRESHOLD ARE DECOUPLED. Restricting the
     label to {a, b} is what kills the spurious third tone, and it happens
     whatever `mix_split` and `mix_bias` are set to -- those only decide WHERE
     the a/b boundary falls. The thin-ink knob is therefore free: turning it up
     cannot resurrect T3. tests/test_halo.py sweeps it and asserts exactly that.

Thresholding recovered coverage at 0.5 is also just the correct binarisation of
an antialiased edge, and it gives a guarantee: an axis-aligned line of width
>= 1.0 px spans at most two cells whose coverages sum to its width, so its peak
cell coverage is >= 0.5 and at least one cell is always assigned to the line --
provided the exactly-0.5 tie goes to the line, which is why the split is taken
toward the minority tone of the pair. Verified over sub-pixel offsets, three
orientations and five tone polarities in tests/test_halo.py. Below 1.0 px the
guarantee genuinely does not hold and no photometric rule can restore it: at
0.5 px coverage a real stroke and a halo are the same pixel. `mix_bias` is
exposed for that case rather than guessed at.

ONE THING THIS CANNOT DO. A tone whose ONLY appearance in the image is
sub-pixel blend has no established colour to be a blend endpoint of, and the
palette's dark cluster is degenerate enough that it will be attributed to a
neighbouring black instead: T7 sits 0.5 weighted-Lab units off the T5~T6
segment, T6 sits 0.7 off T4~T7, T4 sits 3.1 off T3~T6. Which dark tone a black
edge "is a mixture of" is then decided by noise. The tie is broken by requiring
blend endpoints to be ESTABLISHED -- to carry `mix_support_frac` of the opaque
pixels confidently -- and unestablished endpoints are charged a residual
penalty. This is what stops satoshi_miner scattering hundreds of 1 px In1.Cu
islands (T7) along every black outline. It is reported, not silent: `stats
["mixture"]["established"]` lists which tones qualified.

THE PRE-BLUR IS NOW OFF BY DEFAULT. `smooth` was hired to suppress antialias
confetti; the mixture rule does that job properly. Meanwhile the blur was
manufacturing the very artefact it was meant to hide -- GaussianBlur(1.0)
inflated the ambiguous-pixel set 3.6x on bitcoin_b (725 -> 2,609 px) and 2.9x
on satoshi_miner (3,001 -> 8,765 px) by smearing 1 px boundaries into 3 px
bands -- and it erodes genuine thin features below the coverage floor: it drops
a 1 px line's peak coverage to ~0.4, so the guarantee above fails with the blur
on. It remains available for genuinely noisy (JPEG) sources.
"""

import argparse
import pathlib
import sys
from collections import Counter

import numpy as np
from PIL import Image, ImageFilter

# --- The palette. Anchors are ESTIMATES until the reference board is sampled.
# Ordering matters only for reporting. See docs/pcb-palette.md.
TONES = [
    # id   name                approx sRGB        emit?
    ("T1", "silk white",       (235, 235, 230), True),
    ("T2", "ENIG gold",        (205, 165,  75), True),
    ("T3", "bare FR4",         (200, 180, 130), True),
    ("T4", "FR4 + buried",     (170, 150, 105), True),
    ("T5", "black mask",       ( 25,  25,  28), False),  # background: draw nothing
    ("T6", "mask over copper", ( 44,  41,  36), True),
    ("T7", "mask + buried",    ( 33,  32,  31), True),
]

# Lightness is weighted above chroma: getting a dark thing dark matters more
# than getting its hue right, and the current tool's worst failure is rendering
# navy as white silk.
L_WEIGHT = 2.0

# --- mixture-pixel defaults. All four thresholds below were picked off measured
# distributions over six real assets, not guessed. See the module docstring.
#
# How much better the two-anchor mixture must explain the colour than the best
# single anchor. Measured res/d1 on bitcoin_b: the entire halo lies below 1.0,
# every genuine pixel above 1.5 -- a two-order-of-magnitude gap. The binding
# constraint at the other end is satoshi_points, whose flat gold field sits at
# 0.94 and must NOT be touched, so this cannot approach 1.0.
MIX_RATIO = 0.8
# ...and the mixture must actually FIT, in absolute weighted-Lab units. This is
# the well-conditioned half of the test: res/d1 blows up wherever d1 -> 0, and
# on off-palette artwork (satoshi's gold is 38 units from every anchor) the
# ratio alone will happily reclassify a whole flat field. Measured: halo
# residuals top out near 15, the nearest genuine flat field sits at 35.8. 16
# keeps a 2.2x margin to the first thing that would be damaged.
MIX_MAX_RES = 16.0
# A pixel this close to an anchor is already on-palette; never reinterpret it.
MIX_MIN_DE = 1.5
# Coverage at which the label flips to the MINORITY tone of the pair. 0.5 is
# the correct binarisation of an antialiased edge and is what makes a >= 1 px
# feature survive at every sub-pixel offset.
MIX_SPLIT = 0.5
# Extra coverage, in fractions of a pixel, handed to the minority tone -- i.e.
# to the thin feature, whichever polarity it has. 0.0 keeps the exact >= 1 px
# guarantee; raise it to hold on to sub-pixel strokes at the cost of fattening
# every minority region by that fraction of a pixel. It cannot bring the halo
# back: the halo dies from confining the pixel to the pair, not from the split.
MIX_BIAS = 0.0
# A tone counts as ESTABLISHED in an image once this fraction of the opaque
# pixels resolve to it confidently (floor of 32 px). Only established tones are
# allowed to be endpoints of a blend, because the palette's dark cluster is
# self-degenerate -- T7 sits 0.5 units off the T5~T6 segment and T6 sits 0.7
# off T4~T7 -- so which dark pair a black edge "is a mixture of" is decided by
# sub-tenth-of-a-unit noise unless something breaks the tie.
MIX_SUPPORT_FRAC = 0.005
# Residual penalty, in weighted-Lab units, charged per unestablished endpoint.
# Degenerate pairs separate by well under 1 unit, so 4 flips them reliably
# while leaving any genuine preference (> 4 units) alone.
MIX_PAIR_PENALTY = 4.0
# The foot of the perpendicular must be strictly inside the segment by this
# much, otherwise "mixture of a and b" degenerates into "is a" or "is b".
MIX_EDGE = 0.02


def srgb_to_lab(rgb):
    """sRGB uint8 -> CIELAB D65. Hand-rolled; skimage is not available."""
    a = np.asarray(rgb, dtype=np.float64) / 255.0
    a = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = a @ m.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    e, k = 216 / 24389, 24389 / 27
    f = np.where(xyz > e, np.cbrt(xyz), (k * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def _anchors_weighted():
    """Palette anchors in the weighted Lab space the metric actually uses."""
    w = np.array([L_WEIGHT, 1.0, 1.0])
    return srgb_to_lab(np.array([t[2] for t in TONES], dtype=np.uint8)) * w, w


def _squared_distances(P, A):
    """(H,W,NT) squared distances, built one anchor at a time.

    The obvious broadcast form allocates an (H,W,NT,3) temporary -- 242 MB for a
    1200x1200 input. This holds one (H,W) temporary instead.
    """
    out = np.empty(P.shape[:2] + (A.shape[0],), dtype=np.float64)
    for i in range(A.shape[0]):
        d = P - A[i]
        out[..., i] = (d * d).sum(-1)
    return out


def _pair_sweep(P, A, dsq, penalty, edge):
    """Best two-anchor mixture per pixel. Returns (residual, pair_a, pair_b).

    Detection is done in weighted Lab, the space the palette metric lives in.
    For every unordered anchor pair (i<j) the perpendicular distance from the
    pixel to the line through A[i], A[j] falls out of the squared distances
    already in hand:

        |P - A[i] - t*u|^2 = |P - A[i]|^2 - t^2 |u|^2,   t = (P-A[i]).u / |u|^2

    so the whole 21-pair sweep costs one dot product per pair and allocates no
    new (H,W,3) array. `penalty` adds a per-anchor cost to the residual used
    for RANKING pairs only -- the returned residual is the raw geometric one,
    so the accept/reject thresholds stay in honest units. Ties break on pair
    order (lowest i, then lowest j) via a strict `<`: nothing here depends on
    anything but the input.
    """
    nt = A.shape[0]
    best_score = np.full(P.shape[:2], np.inf)
    best_r = np.full(P.shape[:2], np.inf)
    best_a = np.zeros(P.shape[:2], dtype=np.int8)
    best_b = np.zeros(P.shape[:2], dtype=np.int8)

    for i in range(nt):
        for j in range(i + 1, nt):
            u = A[j] - A[i]
            uu = float((u * u).sum())
            if uu <= 0:
                continue
            t = ((P - A[i]) @ u) / uu
            r2 = dsq[..., i] - t * t * uu
            np.maximum(r2, 0.0, out=r2)                 # kill fp noise below 0
            r = np.sqrt(r2)
            score = r + penalty[i] + penalty[j]
            outside = (t <= edge) | (t >= 1.0 - edge)
            score[outside] = np.inf
            upd = score < best_score
            best_score = np.where(upd, score, best_score)
            best_r = np.where(upd, r, best_r)
            best_a = np.where(upd, i, best_a)
            best_b = np.where(upd, j, best_b)

    best_r[~np.isfinite(best_score)] = np.inf
    return best_r, best_a, best_b


def _coverage(rgb, srgb_anchors, pa, pb):
    """Fraction of anchor `pb` in the pixel, measured in sRGB. -> (cov, eps).

    sRGB, not Lab, and that is not a detail. Renderers composite in gamma-
    encoded sRGB, so sRGB is where the blend is linear in coverage; the same
    blend is bowed in Lab. Reading the fraction off the Lab projection biases
    it toward the lighter tone by roughly 0.05 of a pixel -- enough to erase a
    1 px DARK line on a light field. Measured on the synthetic bench: a 1 px
    black stroke on ENIG gold survived 1 of 4 sub-pixel offsets with the Lab
    fraction, 4 of 4 with this one. Recovering coverage in the compositing
    space makes the 0.5 threshold mean exactly "does the shape cover more than
    half of this cell", which is the polarity-symmetric statement.

    `eps` is the exact worst-case error the 8-bit encoding can introduce into
    `cov`: each channel is rounded to within half a level, so the projection
    onto the pair direction v moves by at most 0.5*sum(|v|)/|v|^2. It matters,
    because a 1 px stroke centred on a pixel boundary puts both its cells at
    coverage exactly 0.5, right on the threshold. The true 50% blend of ENIG
    gold and black mask is (115, 95, 51.5), which stores as (115, 95, 52) and
    reads back as 0.4996 -- so without this bound the 8-bit encoding alone
    casts the deciding vote on whether a minimum-width feature exists, and the
    stroke vanishes at that one offset.
    """
    ca, cb = srgb_anchors[pa], srgb_anchors[pb]
    v = cb - ca
    vv = (v * v).sum(-1)
    safe = np.where(vv > 0, vv, 1.0)
    cov = np.where(vv > 0, ((rgb - ca) * v).sum(-1) / safe, 0.0)
    eps = np.where(vv > 0, 0.5 * np.abs(v).sum(-1) / safe, 0.0)
    return np.clip(cov, 0.0, 1.0), eps


def quantise(img, min_alpha=128, smooth=0, *,
             mix=True, mix_ratio=MIX_RATIO, mix_max_res=MIX_MAX_RES,
             mix_split=MIX_SPLIT, mix_bias=MIX_BIAS,
             mix_support_frac=MIX_SUPPORT_FRAC,
             mix_pair_penalty=MIX_PAIR_PENALTY, mix_edge=MIX_EDGE):
    """Map every opaque pixel to its nearest tone. Returns (labels, mask, stats).

    Nearest in Lab, not RGB. The current tool asks 'is this pixel yellow or
    white?' and drops everything that is neither; this asks 'which of the seven
    reachable tones is closest?', which cannot drop anything by construction.

    On top of that, coverage-blended boundary pixels are recognised as mixtures
    of two anchors and confined to those two, so a tone boundary can no longer
    invent a third tone along itself. See the module docstring; `mix=False`
    restores the plain nearest-anchor behaviour exactly.

    `smooth` is a Gaussian pre-blur radius and now defaults to 0. It widens the
    blend band and erodes thin features; only reach for it on noisy sources.
    """
    img = img.convert("RGBA")
    if smooth:
        # Only for genuinely noisy input (JPEG ringing). This USED to run at
        # radius 1 unconditionally and was tripling the halo it meant to hide.
        img = img.filter(ImageFilter.GaussianBlur(smooth))
    arr = np.asarray(img, dtype=np.uint8)
    rgb, alpha = arr[..., :3], arr[..., 3]
    opaque = alpha >= min_alpha

    A, w = _anchors_weighted()
    P = srgb_to_lab(rgb) * w
    srgb_anchors = np.array([t[2] for t in TONES], dtype=np.float64)

    dsq = _squared_distances(P, A)
    near = np.argmin(dsq, axis=-1)                      # ties -> lowest index
    d1 = np.sqrt(np.take_along_axis(dsq, near[..., None], -1)[..., 0])

    naive = np.where(opaque, near, -1)
    mixture_stats = {"enabled": bool(mix)}

    if mix:
        nt = len(TONES)
        rgbf = rgb.astype(np.float64)

        def flag(res):
            return (np.isfinite(res) & (res < mix_ratio * d1)
                    & (res < mix_max_res) & (d1 > MIX_MIN_DE))

        # Pass 1, unpenalised: only to find out which tones are ESTABLISHED,
        # i.e. carried by pixels that are not themselves blends. Without this
        # the palette's degenerate dark cluster decides the pair by noise.
        res0, _, _ = _pair_sweep(P, A, dsq, np.zeros(nt), mix_edge)
        support = np.bincount(near[opaque & ~flag(res0)].ravel(), minlength=nt)
        floor = max(32.0, mix_support_frac * float(opaque.sum()))
        penalty = np.where(support < floor, mix_pair_penalty, 0.0)

        # Pass 2: rank pairs with unestablished endpoints charged `penalty`.
        res, pa, pb = _pair_sweep(P, A, dsq, penalty, mix_edge)
        is_mix = flag(res)
        cov, eps = _coverage(rgbf, srgb_anchors, pa, pb)

        # Split toward the MINORITY tone of the pair, so `mix_bias` means "keep
        # thin ink" whatever its polarity, and so an exactly-half-covered cell
        # goes to the thin thing rather than to whichever anchor sorts first.
        # That tie is not hypothetical: a 1 px line centred on a pixel boundary
        # puts BOTH its cells at exactly 0.5. `eps` widens the tie by the 8-bit
        # rounding bound so the encoding cannot cast the deciding vote.
        sa, sb = support[pa], support[pb]
        take_b = np.where(sb <= sa, cov >= mix_split - mix_bias - eps,
                          cov > 1.0 - mix_split + mix_bias + eps)
        labels = np.where(is_mix, np.where(take_b, pb, pa).astype(near.dtype), near)
        labels = np.where(opaque, labels, -1)

        sel = is_mix & opaque
        changed = sel & (labels != naive)
        pairs = Counter(f"{TONES[i][0]}~{TONES[j][0]}"
                        for i, j in zip(pa[sel].ravel().tolist(),
                                        pb[sel].ravel().tolist()))
        moves = Counter(f"{TONES[a][0]}->{TONES[b][0]}"
                        for a, b in zip(naive[changed].ravel().tolist(),
                                        labels[changed].ravel().tolist()))
        before = set(naive[opaque].ravel().tolist())
        after = set(labels[opaque].ravel().tolist())
        mixture_stats.update({
            "mixture_px": int(sel.sum()),
            "reassigned_px": int(changed.sum()),
            "pairs": dict(pairs.most_common()),
            "moves": dict(moves.most_common()),
            "tones_eliminated": [TONES[i][0] for i in sorted(before - after)],
            "established": [TONES[i][0] for i in range(nt) if penalty[i] == 0],
            "support": {TONES[i][0]: int(support[i]) for i in range(nt)
                        if support[i]},
            "params": {"mix_ratio": mix_ratio, "mix_max_res": mix_max_res,
                       "mix_split": mix_split, "mix_bias": mix_bias,
                       "mix_support_frac": mix_support_frac,
                       "mix_pair_penalty": mix_pair_penalty,
                       "mix_min_de": MIX_MIN_DE, "mix_edge": mix_edge,
                       "smooth": smooth},
        })
    else:
        labels = naive

    counts = Counter(labels[opaque].ravel().tolist())
    total = int(opaque.sum())
    stats = {
        "opaque_px": total,
        "assigned_px": sum(counts.values()),
        "dropped_px": total - sum(counts.values()),
        "per_tone": {TONES[i][0]: n for i, n in sorted(counts.items())},
        "per_tone_naive": {TONES[i][0]: n for i, n in
                           sorted(Counter(naive[opaque].ravel().tolist()).items())},
        "mixture": mixture_stats,
    }
    return labels, opaque, stats


def composite(labels, background="T5"):
    """Render the quantised result as the board would look."""
    bg = next(i for i, t in enumerate(TONES) if t[0] == background)
    out = np.zeros(labels.shape + (3,), dtype=np.uint8)
    out[:, :] = TONES[bg][2]
    for i, t in enumerate(TONES):
        out[labels == i] = t[2]
    return Image.fromarray(out, "RGB")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("images", nargs="+")
    p.add_argument("-o", "--outdir", default="w0_out")
    p.add_argument("--smooth", type=float, default=0.0)
    p.add_argument("--no-mix", dest="mix", action="store_false", default=True,
                   help="disable mixture-pixel handling (the pre-fix behaviour)")
    p.add_argument("--mix-ratio", type=float, default=MIX_RATIO)
    p.add_argument("--mix-max-res", type=float, default=MIX_MAX_RES)
    p.add_argument("--mix-split", type=float, default=MIX_SPLIT)
    p.add_argument("--mix-bias", type=float, default=MIX_BIAS,
                   help="extra coverage given to the minority tone of each pair")
    args = p.parse_args()

    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    for src in args.images:
        path = pathlib.Path(src)
        if not path.exists():
            print(f"  !! missing: {src}", file=sys.stderr)
            continue
        img = Image.open(path)
        labels, opaque, st = quantise(img, smooth=args.smooth, mix=args.mix,
                                      mix_ratio=args.mix_ratio,
                                      mix_max_res=args.mix_max_res,
                                      mix_split=args.mix_split,
                                      mix_bias=args.mix_bias)
        comp = composite(labels)
        dest = out / (path.stem.replace(" ", "_") + "__w0.png")
        comp.save(dest)

        bgpx = st["per_tone"].get("T5", 0)
        ink = st["assigned_px"] - bgpx
        print(f"\n{path.name}  ({img.width}x{img.height})")
        print(f"  opaque={st['opaque_px']:,}  assigned={st['assigned_px']:,}  "
              f"DROPPED={st['dropped_px']:,}")
        print(f"  background(T5)={bgpx:,}  ink={ink:,} "
              f"({100*ink/max(st['opaque_px'],1):.1f}% of opaque)")
        for tid, n in st["per_tone"].items():
            name = next(t[1] for t in TONES if t[0] == tid)
            was = st["per_tone_naive"].get(tid, 0)
            delta = f"  (was {was:,})" if was != n else ""
            print(f"    {tid} {name:<18} {n:>9,}  "
                  f"{100*n/max(st['opaque_px'],1):5.1f}%{delta}")
        m = st["mixture"]
        if m.get("enabled"):
            print(f"  mixture: {m['mixture_px']:,} boundary px, "
                  f"{m['reassigned_px']:,} relabelled")
            if m["pairs"]:
                print("    between: " + "  ".join(f"{k}={v:,}"
                                                  for k, v in list(m["pairs"].items())[:6]))
            print("    established: " + ", ".join(m["established"]))
            if m["tones_eliminated"]:
                print("    TONES ELIMINATED (were halo-only): "
                      + ", ".join(m["tones_eliminated"]))
        print(f"  -> {dest}")


if __name__ == "__main__":
    main()
