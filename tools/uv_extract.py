#!/usr/bin/env python3
"""Read what a UV print has to keep ink off, from a .kicad_pcb. Runs under KiCad's own Python (it needs pcbnew).

    "C:/Program Files/KiCad/10.0/bin/python.exe" tools/uv_extract.py BOARD.kicad_pcb --side F --out geometry.json

uv_stencil.py runs this for you; call it directly to keep the JSON and work on it without KiCad. All coordinates are millimetres in the
TOP-VIEW frame with the board's lower-left corner at (0, 0), x to the right and y up (KiCad's y points down; this frame does not):

    x' = x - xmin,   y' = ymax - y        (xmin, ymax from the board outline)

The JSON holds, for the side asked for:

    outline     the board outline, with any cut-outs as holes
    openings    solder-mask openings on that side: exposed copper, plus any untented via
    silk        everything on that side's silkscreen, graphics and text, as polygons
    holes       every drilled hole (pads), as polygons
    via_holes   every via drill, as {x, y, d}
    courtyards  the filled courtyard of every footprint on that side

What is NOT in it, and why. The silk is the silk BEFORE the fabricator clips it at the mask openings, so it is a superset of what the
finished board shows: ink is kept off silk that will be cut away too, which costs a little art and never risks a pad.

Read once. Loading a board twice in one process crashes this pcbnew build (see texture_board.py), so nothing here loads it more than once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

try:
    import pcbnew
    HAVE_PCBNEW = True
except ImportError:                                   # importable without KiCad, so the rest of the tool can be tested
    pcbnew = None
    HAVE_PCBNEW = False

IU = 1e6                                              # KiCad internal units per millimetre
MAX_ERROR = 3000                                      # nm: how far a flattened arc may sit from the true one


def board_sha256(path) -> str:
    """The file with LF line endings, so a Windows and a Linux checkout of one commit agree."""
    return hashlib.sha256(pathlib.Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def extract(board_path, side: str) -> dict:
    if not HAVE_PCBNEW:
        raise RuntimeError("pcbnew is not importable. Run this under KiCad's bundled Python, e.g.\n"
                           '  "C:/Program Files/KiCad/10.0/bin/python.exe" tools/uv_extract.py BOARD.kicad_pcb --side F --out geometry.json')
    side = side.upper()
    if side not in ("F", "B"):
        raise ValueError("side is F or B")
    layers = dict(F=dict(mask=pcbnew.F_Mask, silk=pcbnew.F_SilkS, crtyd=pcbnew.F_CrtYd, cu=pcbnew.F_Cu),
                  B=dict(mask=pcbnew.B_Mask, silk=pcbnew.B_SilkS, crtyd=pcbnew.B_CrtYd, cu=pcbnew.B_Cu))[side]
    b = pcbnew.LoadBoard(str(board_path))

    outline_set = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(outline_set, False)
    if outline_set.OutlineCount() == 0:
        raise RuntimeError("the board has no closed outline on Edge.Cuts")
    pts = [(outline_set.Outline(i).CPoint(k).x / IU, outline_set.Outline(i).CPoint(k).y / IU)
           for i in range(outline_set.OutlineCount()) for k in range(outline_set.Outline(i).PointCount())]
    xmin, ymax = min(p[0] for p in pts), max(p[1] for p in pts)

    def T(x_nm, y_nm):
        return [round(x_nm / IU - xmin, 4), round(ymax - y_nm / IU, 4)]

    def polys(ps):
        out = []
        for i in range(ps.OutlineCount()):
            o = ps.Outline(i)
            holes = []
            for j in range(ps.HoleCount(i)):
                h = ps.Hole(i, j)
                holes.append([T(h.CPoint(k).x, h.CPoint(k).y) for k in range(h.PointCount())])
            out.append(dict(ring=[T(o.CPoint(k).x, o.CPoint(k).y) for k in range(o.PointCount())], holes=holes))
        return out

    def layer_polys(lid):
        ps = pcbnew.SHAPE_POLY_SET()
        b.ConvertBrdLayerToPolygonalContours(lid, ps)
        return polys(ps)

    openings = layer_polys(layers["mask"])
    n_vias, n_untented = 0, 0
    extra = pcbnew.SHAPE_POLY_SET()
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            n_vias += 1
            if not t.IsTented(layers["mask"]):
                n_untented += 1
                t.TransformShapeToPolygon(extra, layers["cu"], 0, MAX_ERROR, pcbnew.ERROR_INSIDE)
    openings += polys(extra)

    hole_set = pcbnew.SHAPE_POLY_SET()
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetDrillSize().x > 0:
                p.TransformHoleToPolygon(hole_set, 0, MAX_ERROR, pcbnew.ERROR_INSIDE)
    via_holes = [dict(zip(("x", "y"), T(t.GetPosition().x, t.GetPosition().y)), d=round(t.GetDrillValue() / IU, 4))
                 for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]

    courtyards = []
    for fp in b.GetFootprints():
        cy = fp.GetCourtyard(layers["crtyd"])
        if cy.OutlineCount():
            courtyards += polys(cy)

    silk = layer_polys(layers["silk"])
    return dict(
        format="uv-geometry/1", units="mm", frame="top view, lower-left of the board outline at (0, 0), x right, y up",
        board=dict(file=pathlib.Path(board_path).name, sha256=board_sha256(board_path), kicad=pcbnew.Version(),
                   width=round(max(p[0] for p in pts) - xmin, 4), height=round(ymax - min(p[1] for p in pts), 4)),
        side=side, outline=polys(outline_set), openings=openings, silk=silk, holes=polys(hole_set),
        via_holes=via_holes, courtyards=courtyards,
        counts=dict(openings=len(openings), silk=len(silk), courtyards=len(courtyards), vias=n_vias, vias_untented=n_untented))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("board")
    ap.add_argument("--side", choices=("F", "B"), required=True, help="F: front (top), B: back (bottom)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    geom = extract(a.board, a.side)
    pathlib.Path(a.out).write_text(json.dumps(geom), encoding="utf-8", newline="\n")
    c = geom["counts"]
    print("%s side of %s (%s): %d mask openings, %d silk pieces, %d courtyards, %d vias (%d untented) -> %s" % (
        a.side, geom["board"]["file"], geom["board"]["kicad"], c["openings"], c["silk"], c["courtyards"], c["vias"], c["vias_untented"], a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
