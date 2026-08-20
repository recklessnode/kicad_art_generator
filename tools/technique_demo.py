#!/usr/bin/env python3
"""Visual study: the five art techniques, Bitcoin-themed, as they would appear
on a black-mask / ENIG board.

This is a DESIGN STUDY, not an emitter. It renders board appearance so the
techniques can be judged by eye before geometry is committed. Feature sizes are
held to the fabrication limits in docs/pcb-palette.md so nothing here flatters
itself with detail a board could not hold.

Usage:  python technique_demo.py -o technique_demo.png
"""

import argparse
import math
import pathlib

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PX_PER_MM = 24
PANEL_MM = 34
P = PANEL_MM * PX_PER_MM

# Palette anchors from docs/pcb-palette.md (estimates until issue #1 lands).
T5_MASK = (25, 25, 28)
T2_GOLD = (205, 165, 75)
T1_SILK = (235, 235, 230)
T3_FR4 = (200, 180, 130)
DESK = (92, 68, 44)          # what a cut-through shows
GLOW = (196, 214, 150)       # backlit FR4: yellow-green, diffuse

MIN_SILK = 0.15 * PX_PER_MM
MIN_CU = 0.10 * PX_PER_MM


def font(px):
    for p in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(p, px)
        except OSError:
            continue
    return ImageFont.load_default()


def bitcoin_mask(size, stroke_scale=1.0):
    """The Bitcoin mark as a 1-bit mask: a bold B with two vertical bars."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    f = font(int(size * 0.72))
    t = "B"
    bb = d.textbbox((0, 0), t, font=f)
    d.text(((size - (bb[2] - bb[0])) / 2 - bb[0],
            (size - (bb[3] - bb[1])) / 2 - bb[1]), t, fill=255, font=f)
    bw = max(int(size * 0.055 * stroke_scale), 2)
    for dx in (-0.10, 0.10):
        x = size / 2 + size * dx
        d.rectangle([x - bw / 2, size * 0.10, x + bw / 2, size * 0.90], fill=255)
    return m


def panel(label, note):
    img = Image.new("RGB", (P, P), T5_MASK)
    return img, ImageDraw.Draw(img), label, note


def finish(img, label, note):
    d = ImageDraw.Draw(img)
    d.rectangle([0, P - 46, P, P], fill=(0, 0, 0))
    d.text((12, P - 40), label, fill=T1_SILK, font=font(21))
    d.text((12, P - 19), note, fill=(150, 150, 150), font=font(13))
    return img


# --- 1. Translucent window -------------------------------------------------
def demo_window():
    img, d, lab, note = panel("T8  BACKLIT WINDOW",
                              "B-shaped copper-free window, lit from behind")
    m = bitcoin_mask(int(P * 0.62))
    off = (P - m.width) // 2
    # The glow spreads well beyond the opening: FR4 scatters. That bleed is the
    # real design constraint -- it sets minimum spacing between windows.
    halo = Image.new("L", (P, P), 0)
    halo.paste(m, (off, off - 20))
    halo = halo.filter(ImageFilter.GaussianBlur(26))
    img = Image.composite(Image.new("RGB", (P, P), GLOW), img, halo)
    core = Image.new("L", (P, P), 0)
    core.paste(m, (off, off - 20))
    core = core.filter(ImageFilter.GaussianBlur(5))
    img = Image.composite(Image.new("RGB", (P, P), (228, 238, 190)), img, core)
    return finish(img, lab, note)


# --- 2. Cut-through --------------------------------------------------------
def demo_cut():
    img, d, lab, note = panel("T9  CUTOUT",
                              "routed through; inside corners filleted to bit radius")
    m = bitcoin_mask(int(P * 0.62))
    off = (P - m.width) // 2
    # A router cannot make a sharp inside corner. Blur-then-threshold rounds the
    # geometry the way a 0.8 mm bit actually would.
    r = m.filter(ImageFilter.GaussianBlur(int(0.8 * PX_PER_MM * 0.5)))
    r = r.point(lambda v: 255 if v > 128 else 0)
    hole = Image.new("L", (P, P), 0)
    hole.paste(r, (off, off - 20))
    img = Image.composite(Image.new("RGB", (P, P), DESK), img, hole)
    edge = hole.filter(ImageFilter.GaussianBlur(3))
    img = Image.composite(Image.new("RGB", (P, P), (60, 48, 34)),
                          img, ImageChopsDiff(edge, hole))
    return finish(img, lab, note)


def ImageChopsDiff(a, b):
    from PIL import ImageChops
    return ImageChops.subtract(a, b)


# --- 3. Stippling ----------------------------------------------------------
def demo_stipple():
    img, d, lab, note = panel("STIPPLE",
                              "gold dots, 0.5 mm pitch - reads as texture, not tone")
    m = bitcoin_mask(int(P * 0.62)).resize((P, P))
    px = m.load()
    pitch = int(0.5 * PX_PER_MM)
    for gy in range(pitch, P - 60, pitch):
        for gx in range(pitch, P - pitch, pitch):
            v = px[min(gx, P - 1), min(gy, P - 1)] / 255.0
            # ramp density with a horizontal gradient so the sweep is visible
            v *= 0.25 + 0.75 * (gx / P)
            if v <= 0.05:
                continue
            r = max(MIN_CU / 2, (pitch * 0.48) * math.sqrt(v))
            d.ellipse([gx - r, gy - r, gx + r, gy + r], fill=T2_GOLD)
    return finish(img, lab, note)


# --- 4. Line-width shading -------------------------------------------------
def demo_hatch():
    img, d, lab, note = panel("LINE-WIDTH SHADING",
                              "silk hatch, 0.4 mm pitch, width ramped 0.10-0.30 mm")
    m = bitcoin_mask(int(P * 0.62)).resize((P, P))
    px = m.load()
    pitch = 0.4 * PX_PER_MM
    y = pitch
    while y < P - 60:
        x = 0
        seg = 3.0
        while x < P:
            v = px[min(int(x), P - 1), min(int(y), P - 1)] / 255.0
            if v > 0.5:
                w = 0.10 + 0.20 * (x / P)          # ramp across the panel
                d.line([x, y, x + seg, y], fill=T1_SILK,
                       width=max(int(w * PX_PER_MM), 2))
            x += seg
        y += pitch
    return finish(img, lab, note)


# --- 5. Microprinting ------------------------------------------------------
def demo_microprint():
    img, d, lab, note = panel("MICROPRINT",
                              "copper text 0.5 mm cap height inside one mask opening")
    # One mask opening over the whole block: never per-glyph, since registration
    # is +/-0.05 mm against a 0.075 mm stroke.
    pad = 26
    d.rectangle([pad, pad, P - pad, P - 76], fill=T3_FR4)
    msg = ("The Times 03/Jan/2009 Chancellor on brink of second bailout for banks  ")
    f = font(max(int(0.5 * PX_PER_MM), 8))
    y = pad + 12
    while y < P - 92:
        d.text((pad + 8, y), msg * 2, fill=(150, 120, 55), font=f)
        y += int(0.5 * PX_PER_MM * 1.45)
    big = bitcoin_mask(int(P * 0.34))
    img.paste(Image.new("RGB", big.size, T2_GOLD), (P // 2 - big.width // 2, P // 2 - 40), big)
    return finish(img, lab, note)


# --- 6. Everything together ------------------------------------------------
def demo_combined():
    img, d, lab, note = panel("COMBINED",
                              "solid + hatch shading + microtext caption")
    m = bitcoin_mask(int(P * 0.5))
    off = (P - m.width) // 2
    img.paste(Image.new("RGB", m.size, T2_GOLD), (off, 28), m)
    pitch = 0.4 * PX_PER_MM
    y = 28 + m.height + 10
    i = 0
    while y < P - 96:
        w = 0.10 + 0.18 * (1 - i / 14.0)
        d.line([off, y, off + m.width, y], fill=T1_SILK,
               width=max(int(w * PX_PER_MM), 2))
        y += pitch
        i += 1
    f = font(max(int(0.6 * PX_PER_MM), 9))
    d.text((off, P - 92), "21,000,000  \u2022  PROOF OF WORK", fill=(150, 120, 55), font=f)
    return finish(img, lab, note)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="technique_demo.png")
    a = ap.parse_args()
    panels = [demo_window(), demo_cut(), demo_stipple(),
              demo_hatch(), demo_microprint(), demo_combined()]
    cols, rows, gap = 3, 2, 14
    sheet = Image.new("RGB", (cols * P + (cols + 1) * gap,
                              rows * P + (rows + 1) * gap), (18, 18, 20))
    for i, pn in enumerate(panels):
        c, r = i % cols, i // cols
        sheet.paste(pn, (gap + c * (P + gap), gap + r * (P + gap)))
    out = pathlib.Path(a.out)
    sheet.save(out)
    print(f"  {out}  {sheet.width}x{sheet.height}  {out.stat().st_size:,} B")


if __name__ == "__main__":
    main()
