#!/usr/bin/env python3
"""Render text through KiCad itself and report the exact ink polygons.

Runs under KICAD'S python (it imports pcbnew); everything else in this tree
runs in the venv, which cannot import pcbnew.  tools/outline_font.py invokes
this as a subprocess and treats its output as the authority on what an
outline-faced string LOOKS LIKE, because KiCad's own renderer is the only
honest source for it:

  * KiCad shapes outline text with HarfBuzz, so KERNING IS APPLIED --
    measured on this rig, 'AWAVA' in Ubuntu at size 10 is 47.554 mm of ink
    against 49.758 mm predicted from bare hmtx advances.  Geometry computed
    from advances alone is therefore wrong for every proportional face, in
    the direction that narrows inter-glyph gaps -- exactly the quantity the
    silk floor is checked against.
  * The em scale KiCad applies to an outline face is per-face and not a
    published constant (measured em/size on this rig: Ubuntu 1.3985,
    Ubuntu Mono 1.5674, Consolas 1.3961, Segoe UI 1.4009, Orbitron 1.3991).
  * The vertical anchor offset IS a constant: the baseline of every face at
    every probed string sits 0.4150 x size below the anchor of a
    default-vertical-justify text.  outline_font.py re-derives it from the
    'H' probe rather than trusting this comment.

Protocol: JSON in, JSON out.
  argv[1]  request file:  {"entries": [{"id": str, "face": str, "text": str,
                                        "size_mm": float}, ...]}
  argv[2]  response file: {"kicad": version, "entries": {id: {
               "resolved": bool,       # ResolveFont() return
               "outlines": [{"outer": [[x,y]...], "holes": [[[x,y]...]...]}],
               "bbox": [x0, y0, x1, y1]}}}

Coordinates are mm, y-down, relative to the text anchor at (0,0), horizontal
justify LEFT, vertical justify default (centre) -- the same effects the
emitters write.  Curves are flattened at 0.002 mm max error, ERROR_INSIDE, so
flattening error costs measured stem width (conservative) rather than hiding
a violation.

NOTE ON SUBSTITUTION: ResolveFont returns True even for a face that does not
exist -- KiCad substitutes silently.  Detecting substitution is therefore NOT
this tool's job; outline_font.py does it by comparing this tool's geometry
against fontTools-computed geometry for the requested face.
"""

import json
import sys

import pcbnew

MAX_ERROR_MM = 0.002


def probe(face, text, size_mm, board):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetPosition(pcbnew.VECTOR2I(0, 0))
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size_mm),
                                  pcbnew.FromMM(size_mm)))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    t.SetUnresolvedFontName(face)
    resolved = bool(t.ResolveFont(None))
    ps = pcbnew.SHAPE_POLY_SET()
    t.TransformTextToPolySet(ps, 0, pcbnew.FromMM(MAX_ERROR_MM),
                             pcbnew.ERROR_INSIDE)
    outlines = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        outer = [[pcbnew.ToMM(o.CPoint(k).x), pcbnew.ToMM(o.CPoint(k).y)]
                 for k in range(o.PointCount())]
        holes = []
        for j in range(ps.HoleCount(i)):
            h = ps.Hole(i, j)
            holes.append([[pcbnew.ToMM(h.CPoint(k).x),
                           pcbnew.ToMM(h.CPoint(k).y)]
                          for k in range(h.PointCount())])
        outlines.append({"outer": outer, "holes": holes})
    bb = ps.BBox()
    bbox = ([pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
             pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())]
            if outlines else None)
    return {"resolved": resolved, "outlines": outlines, "bbox": bbox}


def main():
    req_path, resp_path = sys.argv[1], sys.argv[2]
    with open(req_path, "r", encoding="utf-8") as f:
        req = json.load(f)
    board = pcbnew.CreateEmptyBoard()
    out = {"kicad": pcbnew.GetBuildVersion(), "entries": {}}
    for e in req["entries"]:
        out["entries"][e["id"]] = probe(e["face"], e["text"],
                                        float(e["size_mm"]), board)
    with open(resp_path, "w", encoding="utf-8") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()
