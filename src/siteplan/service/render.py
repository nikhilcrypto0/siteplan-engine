"""Drawings of one candidate: a DXF for ZWCAD on the BuildNow layer names the legacy writer uses,
an SVG preview, and the A1 sheet.

Everything drawn is the candidate's own geometry, as the contract carries it: each tower is its
prototype placed as the candidate places it (`PlacedTower.world`), with its flats and cores, and
the roads, gates, open space, club house, facilities, ramps, cellars and bays are the shapes the
candidate holds. No generator is called and nothing is laid out again. The layer names and
road labels are imported from layout_export (the legacy writer); the sheet's scale, north
arrow, scale bar, dimensions, border, statement column and title block are sheet.py's own
helpers. The notes (DEBUG RUN, the UNVERIFIED items the architect acknowledged) are drawn on
every output: a SOLVER-NOTES layer in the DXF, a SHEET-NOTES note on the sheet, lines under the
SVG.

The numbers here size text and margins on paper and on screen; none of them is a site or legal
dimension.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from html import escape
from pathlib import Path

import ezdxf
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from shapely.geometry import Polygon

from siteplan.contracts import CandidateLayout, CanonicalSiteModel
from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Shape
from siteplan.layout_export import LAYERS, ROAD_LABELS, _parts, _ring
from siteplan.sheet import (
    SHEET_LAYERS,
    STATEMENT_WIDTH_MM,
    TEXT_MM,
    SheetInfo,
    _border,
    _dimension,
    _north_arrow,
    _scale_bar,
    pick_scale,
)

NOTE_LAYERS = {"SOLVER-NOTES": 1, "SHEET-NOTES": 1}  # AutoCAD colour index: red
DXF_TEXT_M = 2.5  # label height in the plain DXF, metres on the ground
NOTE_PITCH = 1.8  # line pitch of the DXF's notes, in text heights
NOTE_TEXT_MM = 2.2  # printed height of the sheet's notes
NOTE_ABOVE_BLOCK_MM = 6.0  # gap between the sheet's notes and the title block
SVG_WIDTH_PX = 900
SVG_PAD_M = 12.0
SVG_HEAD_PX = 70
SVG_LINE_PX = 16
SVG_NOTE_CHARS = 120  # a note's line, wrapped to the drawing's width
# The contract's road kinds, in the legacy writer's label keys (layout_export.ROAD_LABELS).
LEGACY_KIND = {RoadKind.LOOP: "loop", RoadKind.PERIMETER_LANE: "perimeter",
               RoadKind.APPROACH: "main approach", RoadKind.INTERNAL: "internal",
               RoadKind.CUL_DE_SAC: "cul-de-sac"}


@dataclass(frozen=True)
class TowerShape:
    name: str
    footprint: Polygon
    flats: tuple[Polygon, ...]
    cores: tuple[Polygon, ...]
    flats_per_floor: int


@dataclass(frozen=True)
class Plan:
    """A candidate's ground, as shapes to draw."""

    plot: Polygon
    towers: tuple[TowerShape, ...]
    roads: tuple[tuple[str, tuple[Polygon, ...]], ...]  # label, pieces
    fire: tuple[Polygon, ...]
    gates: tuple[Polygon, ...]
    green_strip: tuple[Polygon, ...]
    open_space: tuple[Polygon, ...]
    club: Polygon | None
    club_floors: int
    amenities: tuple[tuple[str, Polygon], ...]
    ramps: tuple[Polygon, ...]
    cellars: tuple[Polygon, ...]
    bays: tuple[Polygon, ...]


def _shapes(shapes: list[Shape]) -> tuple[Polygon, ...]:
    return tuple(s.to_shapely() for s in shapes)


def _road_label(kind: RoadKind, width_m: float) -> str:
    legacy = LEGACY_KIND.get(kind)
    words = ROAD_LABELS[legacy] if legacy else kind.value.replace("_", " ")
    return f"{words} {width_m:g} M"


def plan_of(site: CanonicalSiteModel, candidate: CandidateLayout) -> Plan:
    towers = []
    for tower in candidate.towers:
        prototype = candidate.prototype(tower.prototype_id)
        towers.append(TowerShape(
            name=tower.name, footprint=candidate.placed_footprint(tower),
            flats=tuple(tower.world(m.shape.to_shapely()) for m in prototype.modules),
            cores=tuple(tower.world(z.shape.to_shapely()) for z in prototype.core_zones),
            flats_per_floor=prototype.per_floor.flats))
    c, p = candidate.circulation, candidate.program
    return Plan(
        plot=site.net_plot.value.to_shapely(), towers=tuple(towers),
        roads=tuple((_road_label(r.kind, r.declared_width_m), _shapes(r.shapes))
                    for r in c.roads),
        fire=_shapes(c.fire_hardstanding), gates=tuple(g.shape.to_shapely() for g in c.gates),
        green_strip=_shapes(p.green_strip), open_space=_shapes(p.open_space),
        club=p.club_house.shape.to_shapely() if p.club_house else None,
        club_floors=p.club_house.floors if p.club_house else 0,
        amenities=tuple((a.name, a.shape.to_shapely()) for a in p.amenities),
        ramps=_shapes(p.ramps), cellars=_shapes(p.cellars.outline) if p.cellars else (),
        bays=_shapes(p.bays))


# --- DXF -------------------------------------------------------------------------------------


def _new_drawing(layers: dict[str, int]):
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    for name, colour in layers.items():
        doc.layers.add(name, color=colour)
    return doc


def _draw(msp, plan: Plan, text_h: float, label_layer: str) -> None:
    """The plan on the BuildNow layers (and the legacy writer's SOLVER-* ones), labelled."""

    def poly(shape: Polygon, layer: str) -> None:
        for part in _parts(shape):
            msp.add_lwpolyline(_ring(part), close=True, dxfattribs={"layer": layer})
            for hole in part.interiors:
                msp.add_lwpolyline([(x, y) for x, y in list(hole.coords)[:-1]], close=True,
                                   dxfattribs={"layer": layer})

    def label(text: str, shape: Polygon, scale: float) -> None:
        at = shape.representative_point()
        msp.add_text(text, height=text_h * scale, dxfattribs={"layer": label_layer}
                     ).set_placement((at.x, at.y), align=TextEntityAlignment.MIDDLE_CENTER)

    poly(plan.plot, "Plot")
    for part in plan.green_strip:
        poly(part, "SOLVER-GREEN-STRIP")
    for words, pieces in plan.roads:
        for piece in pieces:
            poly(piece, "SOLVER-ROADS")
        if pieces:
            label(words, max(pieces, key=lambda s: s.area), 0.8)
    for part in plan.fire:
        poly(part, "SOLVER-FIRE-LANES")
    for gate in plan.gates:
        poly(gate, "SOLVER-ENTRANCE")
        label("MAIN ENTRANCE", gate, 0.9)
    for cellar in plan.cellars:
        poly(cellar, "SOLVER-CELLAR")
    for ramp in plan.ramps:
        poly(ramp, "SOLVER-RAMPS")
        label("RAMP 1:8", ramp, 0.7)
    for bay in plan.bays:
        poly(bay, "Parking")
    for name, shape in plan.amenities:
        poly(shape, "SITE-AMENITIES")
        label(name, shape, 0.75)
    for pocket in plan.open_space:
        poly(pocket, "Organized Open Space")
        label("TOT-LOT", pocket, 0.8)
    if plan.club is not None:
        poly(plan.club, "Building Plan")
        label(f"CLUB HOUSE, {plan.club_floors} FLOORS", plan.club, 0.9)
    for tower in plan.towers:
        poly(tower.footprint, "Building Plan")
        for flat in tower.flats:
            poly(flat, "Dwelling Unit")
        for core in tower.cores:
            poly(core, "SOLVER-CORES")
        label(f"{tower.name} · {tower.flats_per_floor} FLATS/FLOOR", tower.footprint, 0.9)


def write_dxf(plan: Plan, path: Path, notes: list[str]) -> Path:
    doc = _new_drawing(LAYERS | NOTE_LAYERS)
    msp = doc.modelspace()
    _draw(msp, plan, DXF_TEXT_M, "SOLVER-LABELS")
    minx, miny, _, _ = plan.plot.bounds
    pitch = NOTE_PITCH * DXF_TEXT_M
    for i, line in enumerate(notes, 2):
        msp.add_text(line, height=DXF_TEXT_M, dxfattribs={"layer": "SOLVER-NOTES"}
                     ).set_placement((minx, miny - i * pitch))
    return _save(doc, path)


def write_sheet(plan: Plan, path: Path, info: SheetInfo, statement: str,
                notes: list[str]) -> Path:
    """The A1 sheet: the plan, sheet.py's dimensions, north arrow, scale bar, border, area
    statement and title block, and the notes in the statement column above the title block."""
    scale = pick_scale(plan.plot)
    m = scale / 1000  # one printed millimetre in metres on the ground
    doc = _new_drawing(LAYERS | SHEET_LAYERS | NOTE_LAYERS)
    msp = doc.modelspace()
    _draw(msp, plan, TEXT_MM * m, "SHEET-TEXT")
    _dimension(msp, plan.plot, [t.footprint for t in plan.towers], m)
    _north_arrow(msp, plan.plot, m)
    _scale_bar(msp, plan.plot, scale, m)
    column_x, block_top = _border(msp, plan.plot, statement, info, scale, m)
    if notes:
        note = msp.add_mtext("\\P".join(notes), dxfattribs={
            "layer": "SHEET-NOTES", "char_height": NOTE_TEXT_MM * m,
            "width": STATEMENT_WIDTH_MM * m})
        note.set_location((column_x, block_top + NOTE_ABOVE_BLOCK_MM * m),
                          attachment_point=MTextEntityAlignment.BOTTOM_LEFT)
    return _save(doc, path)


def _save(doc, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


# --- SVG -------------------------------------------------------------------------------------


def write_svg(plan: Plan, path: Path, title: str, subtitle: str, notes: list[str]) -> Path:
    """A plain drawing for a browser, with the notes under it, wrapped to its width."""
    notes = [part for line in notes
             for part in textwrap.wrap(line, SVG_NOTE_CHARS, subsequent_indent="  ")]
    minx, miny, maxx, maxy = plan.plot.bounds
    scale = SVG_WIDTH_PX / max(maxx - minx + 2 * SVG_PAD_M, maxy - miny + 2 * SVG_PAD_M)
    width = (maxx - minx + 2 * SVG_PAD_M) * scale
    drawing_h = (maxy - miny + 2 * SVG_PAD_M) * scale
    height = SVG_HEAD_PX + drawing_h + SVG_LINE_PX * (len(notes) + 1)

    def xy(x: float, y: float) -> str:
        across = (x - minx + SVG_PAD_M) * scale
        down = (maxy - y + SVG_PAD_M) * scale + SVG_HEAD_PX
        return f"{across:.1f},{down:.1f}"

    def shape(polygon: Polygon, style: str) -> str:
        rings = [polygon.exterior, *polygon.interiors]
        d = " ".join("M " + " ".join(xy(x, y) for x, y in r.coords) + " Z" for r in rings)
        return f'<path d="{d}" fill-rule="evenodd" {style}/>'

    def text(at, words: str, colour: str) -> str:
        x, y = xy(at.x, at.y).split(",")
        return (f'<text x="{x}" y="{y}" font-size="10" text-anchor="middle" '
                f'fill="{colour}">{escape(words)}</text>')

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
           f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Helvetica, Arial, sans-serif">',
           '<rect width="100%" height="100%" fill="#fbfbf8"/>',
           f'<text x="14" y="26" font-size="17" font-weight="700">{escape(title)}</text>',
           f'<text x="14" y="50" font-size="13" fill="#444">{escape(subtitle)}</text>',
           shape(plan.plot, 'fill="none" stroke="#ad2677" stroke-width="2"')]
    layers = ((plan.green_strip, 'fill="#d9ead0" stroke="none"'),
              ([p for _, pieces in plan.roads for p in pieces], 'fill="#d6d2c6" stroke="#9c9587"'),
              (plan.fire, 'fill="#f3e3c7" stroke="#d0a24c" stroke-dasharray="4 3"'),
              (plan.gates, 'fill="#f6d6cc" stroke="#bd3b27"'),
              (plan.ramps, 'fill="#6d7f99" stroke="#34445c"'),
              (plan.bays, 'fill="#f0ece0" stroke="#9a9384" stroke-width="0.5"'),
              ([s for _, s in plan.amenities], 'fill="#cde7ef" stroke="#3b7f96"'),
              (plan.open_space, 'fill="#bfdcaa" stroke="#47762c"'),
              ([plan.club] if plan.club is not None else [], 'fill="#cfd8e8" stroke="#3a5a8c"'))
    for shapes, style in layers:
        out += [shape(part, style) for s in shapes for part in _parts(s)]
    for tower in plan.towers:
        out.append(shape(tower.footprint, 'fill="#e8e4d6" stroke="#333"'))
        out += [shape(f, 'fill="#f7f4ea" stroke="#5b5b5b" stroke-width="1.1"')
                for f in tower.flats]
        out += [shape(c, 'fill="#8a8a8a"') for c in tower.cores]
        out.append(text(tower.footprint.representative_point(), tower.name, "#bd3b27"))
    top = SVG_HEAD_PX + drawing_h
    out += [f'<text x="14" y="{top + SVG_LINE_PX * i:.0f}" font-size="12" fill="#a3200b">'
            f'{escape(line)}</text>' for i, line in enumerate(notes, 1)]
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))
    return path
