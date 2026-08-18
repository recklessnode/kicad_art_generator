# Source and image attribution

`btc_whitepaper_b_board.png`, `btc_whitepaper_b_head.png`,
`btc_whitepaper_b_zoom.png`, and the text they render —
`examples/bitcoin_whitepaper_s1.txt`, which
`library/RecklessArt.pretty/art_btc_whitepaper_b.kicad_mod` sets

Section 1, *Introduction*, of **"Bitcoin: A Peer-to-Peer Electronic Cash
System"** by Satoshi Nakamoto (2008), extracted from the canonical
`bitcoin.pdf`. The whitepaper is published under the **MIT License**.

> Attribution: Satoshi Nakamoto, <https://bitcoin.org/bitcoin.pdf>

1799 characters, unmodified except that the line-end hyphenation of the original
typesetting is rejoined (`non-` + `reversible` is a real compound word and keeps
its hyphen) and newlines collapse to single spaces, because `fp_text` is one line
and the shape flow re-breaks the text anyway. The figures are renders of the
resulting KiCad footprint geometry, not of the PDF.

`examples/bitcoin_b.svg` is a 614-byte, three-shape (rounded square, disc, path)
rendition of the Bitcoin currency mark. **Its origin is not recorded**: it has
been in the tree since the initial commit `ff41777` and no commit body names a
source. The mark itself is in common public use, but if that file is a copy of
someone's artwork rather than a redraw, this note is the place to say so.

---

`tux_A_unfiltered.png`, `tux_B_filtered.png`

Rendered from `tux.svg` as distributed with Inkscape (`/usr/share/inkscape/branding/tux.svg`).
Tux the penguin was created by Larry Ewing using The GIMP.

> Attribution: lewing@isc.tamu.edu and The GIMP

These are conversions of that artwork into KiCad footprint geometry, produced to
document the behaviour of `--min-area-mm2`. See
[#7](https://github.com/recklessnode/kicad_art_generator/issues/7).

`minarea_A..D.png` are renders of the Bitcoin emission formula, a mathematical
figure, and carry no third-party rights.
