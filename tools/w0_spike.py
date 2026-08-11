#!/usr/bin/env python3
"""W0 go/no-go spike: quantiser + compositor only. No emitter, no tracing.

Answers one question: does mapping source art onto the PCB tone palette in a
perceptual space, with the background tone emitted as nothing, produce something
better than the current tool? Everything downstream depends on that being true,
and it is a judgement made by looking, not by a metric.

Deliberately NOT here: contour tracing, geometry simplification, s-expression
emission. Those are W1/W2 and they are pointless if this stage is wrong.

Usage:  python w0_spike.py <image> [<image> ...] -o <outdir>
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


def quantise(img, min_alpha=128, smooth=1):
    """Map every opaque pixel to its nearest tone. Returns (labels, mask, stats).

    Nearest in Lab, not RGB. The current tool asks 'is this pixel yellow or
    white?' and drops everything that is neither; this asks 'which of the seven
    reachable tones is closest?', which cannot drop anything by construction.
    """
    img = img.convert("RGBA")
    if smooth:
        # Kill JPEG/antialiasing confetti before classifying, or a faithful
        # tracer turns every stray pixel into a sub-fabricable ring.
        img = img.filter(ImageFilter.GaussianBlur(smooth))
    arr = np.asarray(img, dtype=np.uint8)
    rgb, alpha = arr[..., :3], arr[..., 3]
    opaque = alpha >= min_alpha

    lab = srgb_to_lab(rgb)
    anchors = srgb_to_lab(np.array([t[2] for t in TONES], dtype=np.uint8))

    w = np.array([L_WEIGHT, 1.0, 1.0])
    d = (((lab[:, :, None, :] - anchors[None, None, :, :]) * w) ** 2).sum(-1)
    labels = np.argmin(d, axis=-1)
    labels[~opaque] = -1

    counts = Counter(labels[opaque].ravel().tolist())
    total = int(opaque.sum())
    stats = {
        "opaque_px": total,
        "assigned_px": sum(counts.values()),
        "dropped_px": total - sum(counts.values()),
        "per_tone": {TONES[i][0]: n for i, n in sorted(counts.items())},
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
    p.add_argument("--smooth", type=float, default=1.0)
    args = p.parse_args()

    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    for src in args.images:
        path = pathlib.Path(src)
        if not path.exists():
            print(f"  !! missing: {src}", file=sys.stderr)
            continue
        img = Image.open(path)
        labels, opaque, st = quantise(img, smooth=args.smooth)
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
            print(f"    {tid} {name:<18} {n:>9,}  {100*n/max(st['opaque_px'],1):5.1f}%")
        print(f"  -> {dest}")


if __name__ == "__main__":
    main()
