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

import math
import textwrap
from dataclasses import dataclass
from html import escape
from pathlib import Path

import ezdxf
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from siteplan import rules as law
from siteplan.contracts import CandidateLayout, CanonicalSiteModel, DesignBrief, ResolvedRules
from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Shape
from siteplan.contracts.resolved_rules import ALL, CIRCULATION_IN_SETBACK, STILT_IN_RULE_HEIGHT
from siteplan.geometry import straight_runs
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
from siteplan.validator import context as judging
from siteplan.validator import zones
from siteplan.validator.routes import Way, ways

NOTE_LAYERS = {"SOLVER-NOTES": 1, "SHEET-NOTES": 1}  # AutoCAD colour index: red
# 2026-10-19: each tower's way in from the gate (validator.routes: its entrance, its driveway
# and the route), and a north arrow on the plain DXF too, on the sheet's own layer
ROUTE_LAYERS = {"SOLVER-TOWER-ENTRANCE": 1, "SOLVER-DRIVEWAYS": 4, "SOLVER-ROUTES": 6,
                "SHEET-NORTH": 7}
ENTRANCE_MARK_M = 1.2  # an entrance's mark, its radius on the ground
PLAIN_ARROW_M_PER_MM = 1.0  # the plain DXF's north arrow, drawn as the sheet's at 1:1000
SVG_ARROW_PX = 26  # the SVG's north arrow
DXF_TEXT_M = 2.5  # label height in the plain DXF, metres on the ground
NOTE_PITCH = 1.8  # line pitch of the DXF's notes, in text heights
NOTE_TEXT_MM = 2.2  # printed height of the sheet's notes
NOTE_ABOVE_BLOCK_MM = 6.0  # gap between the sheet's notes and the title block
SVG_WIDTH_PX = 900
SVG_PAD_M = 12.0
SVG_HEAD_PX = 70
SVG_LINE_PX = 16
SVG_NOTE_CHARS = 120  # a note's line, wrapped to the drawing's width
# 2026-10-21 (the user: why the green border shows in one layout and not another, and why the
# loop road stands at different distances from the boundary): the setback band and the green
# strip carry their widths, side by side, and the strip the rule that asks it
LABEL_RUN_M = 15.0  # a stretch of plot line shorter than this carries no label of its own
STRIP_SEEN_SQM = 1.0  # less drawn strip than this along a stretch is none
STRIP_ROUND_M = 0.5  # a strip's width as drawn, read to this
STRIP_SAME_M = 0.01  # two strip widths this close are the same strip
LABEL_SPACING_M = 30.0  # the same words this near an earlier label are not said again
SETBACK_LAYER = "SOLVER-SETBACK"
MARGIN_LAYERS = {SETBACK_LAYER: 8, "SOLVER-MARGIN-LABELS": 8}  # AutoCAD grey
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
    floors_above_stilt: int = 0  # 0 where a caller does not say


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
    ways: tuple[Way, ...] = ()  # each tower's entrance, driveway and route from the gate
    driveway_m: float = law.DRIVEWAY_MIN_WIDTH_M  # rule 13(c)(viii), the width drawn
    setback: tuple[Polygon, ...] = ()  # the mandatory setback, as the validator holds it
    edge_labels: tuple[EdgeLabel, ...] = ()  # each stretch's setback and green strip, in words
    margin_notes: tuple[str, ...] = ()  # why the setback is that deep and the strip there or not


@dataclass(frozen=True)
class EdgeLabel:
    """Words laid along a stretch of the plot line, inside it."""

    at: tuple[float, float]
    text: str
    angle_deg: float  # the stretch's direction, turned to read from the left


def _shapes(shapes: list[Shape]) -> tuple[Polygon, ...]:
    return tuple(s.to_shapely() for s in shapes)


def _road_label(kind: RoadKind, width_m: float) -> str:
    legacy = LEGACY_KIND.get(kind)
    words = ROAD_LABELS[legacy] if legacy else kind.value.replace("_", " ")
    return f"{words} {width_m:g} M"


def plan_of(site: CanonicalSiteModel, candidate: CandidateLayout,
            rules: ResolvedRules | None = None, brief: DesignBrief | None = None) -> Plan:
    """The candidate's shapes; with the rules and the brief also its setback band and green
    strip in words (`margins`)."""
    setback, labels, notes = margins(site, rules, brief, candidate) \
        if rules is not None and brief is not None else ((), (), ())
    towers = []
    for tower in candidate.towers:
        prototype = candidate.prototype(tower.prototype_id)
        towers.append(TowerShape(
            name=tower.name, footprint=candidate.placed_footprint(tower),
            flats=tuple(tower.world(m.shape.to_shapely()) for m in prototype.modules),
            cores=tuple(tower.world(z.shape.to_shapely()) for z in prototype.core_zones),
            flats_per_floor=prototype.per_floor.flats,
            floors_above_stilt=tower.floors_above_stilt))
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
        bays=_shapes(p.bays), ways=tuple(ways(candidate, law.DRIVEWAY_MIN_WIDTH_M)),
        setback=setback, edge_labels=labels, margin_notes=notes)


def margins(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
            candidate: CandidateLayout
            ) -> tuple[tuple[Polygon, ...], tuple[EdgeLabel, ...], tuple[str, ...]]:
    """The mandatory setback as the independent validator holds it (validator.zones: as deep as
    the deepest any block here asks, the front apart where a band gives one) and the green strip
    the candidate draws, each stretch of the plot line labelled with how deep or wide it is, the
    strip with the rule that asks it, and two notes saying why. The stilt read as the study
    selects it, else as asks the deeper setback: never the more lenient."""
    ctx = judging.build(site, rules, brief, candidate)
    if ctx is None or not ctx.classes:
        return (), (), ()
    reading = _reading(rules, ctx)
    depths = zones.setback_depths(ctx, reading)
    if depths is None:
        return (), (), ()
    front, side = depths
    zone = zones.setback_zone(ctx, reading)
    groups = zones.edge_groups(ctx) if abs(front - side) > zones.DEPTH_EPS_M else None
    strip = unary_union(_shapes(candidate.program.green_strip)) \
        if candidate.program.green_strip else Polygon()
    asks = zones.strips_asked(ctx, reading)
    labels = []
    for run in straight_runs(ctx.net):
        if run.length < LABEL_RUN_M:
            continue
        (x0, y0), (x1, y1) = run.line.coords[0][:2], run.line.coords[-1][:2]
        ux, uy = (x1 - x0) / run.length, (y1 - y0) / run.length
        mid = run.line.interpolate(0.5, normalized=True)
        nx, ny = -uy, ux
        if not ctx.net.contains(Point(mid.x + nx * 0.5, mid.y + ny * 0.5)):
            nx, ny = -nx, -ny
        is_front = groups is not None and run.line.intersection(
            groups[0].buffer(0.01)).length > run.length / 2
        deep = front if is_front else side if groups is not None else max(front, side)
        turn = math.degrees(math.atan2(uy, ux))
        turn = turn - 180 if turn > 90 else turn + 180 if turn <= -90 else turn
        ahead = run.length * 0.18
        _say(labels, EdgeLabel((mid.x + ux * ahead + nx * deep / 2,
                                mid.y + uy * ahead + ny * deep / 2), f"setback {deep:g} m", turn))
        drawn = strip.intersection(run.line.buffer(max(deep, 0.5), cap_style="flat"))
        if drawn.area < STRIP_SEEN_SQM:
            continue
        wide = max(STRIP_ROUND_M, round(drawn.area / run.length / STRIP_ROUND_M) * STRIP_ROUND_M)
        _say(labels, EdgeLabel((mid.x - ux * ahead + nx * wide / 2,
                                mid.y - uy * ahead + ny * wide / 2),
                               _strip_words(rules, asks, wide), turn))
    notes = (_setback_note(ctx, reading, front, side, groups is not None),
             _strip_note(rules, asks))
    return (tuple(_parts_of(zone)), tuple(labels), notes)


def _say(labels: list[EdgeLabel], label: EdgeLabel) -> None:
    """Add a label unless the same words already stand within LABEL_SPACING_M (the short
    stretches of a bent side would print them over each other)."""
    if not any(o.text == label.text and math.dist(o.at, label.at) < LABEL_SPACING_M
               for o in labels):
        labels.append(label)


def _reading(rules: ResolvedRules, ctx) -> str:
    chosen = next((i.selected for i in rules.interpretations if i.id == STILT_IN_RULE_HEIGHT),
                  ALL)
    if chosen in ctx.classes:
        return chosen
    return max(ctx.classes, key=lambda r: max(zones.setback_depths(ctx, r) or (0.0, 0.0)))


def _parts_of(shape) -> list[Polygon]:
    if shape is None or shape.is_empty:
        return []
    return [g for g in getattr(shape, "geoms", [shape]) if isinstance(g, Polygon)]


def _strip_words(rules: ResolvedRules, asks, wide: float) -> str:
    ask = min(asks, key=lambda a: abs(a.width_m - wide)) if asks else None
    if ask is not None and abs(ask.width_m - wide) <= STRIP_ROUND_M:
        wide = ask.width_m  # the strip the rule asks, not the drawing's rounding at a corner
    if ask is not None and _low_strip(rules, ask):
        return f"green strip {wide:g} m, rule 5(f), low block"
    where = rules.green_strip.where_setback_from_m.value
    return (f"green strip {wide:g} m, G.O.7 2016, setback {where:g} m+" if where > 0
            else f"green strip {wide:g} m, rule 7(a)(viii)")


def _low_strip(rules: ResolvedRules, ask) -> bool:
    """Whether a strip is Table III's (rule 5(f), a block below 21 m) rather than the high-rise
    strip of rule 7(a)(viii): a high-rise band states its strip too (`StripAsk.given`), so the
    width tells them apart, the high-rise strip's being the rules' `green_strip.width_m`."""
    return abs(ask.width_m - rules.green_strip.width_m.value) > STRIP_SAME_M


def _setback_note(ctx, reading: str, front: float, side: float, apart: bool) -> str:
    classes = ctx.classes[reading]
    deepest = max(front, side)
    setting = sorted(n for n, c in classes.items()
                     if c.setback_m is not None and max(c.front_m, c.setback_m) >= deepest - 0.01)
    heights = sorted({t.floors for t in ctx.towers if t.name in setting})
    figures = (f"{front:g} m at the front (the stretches facing the access road), {side:g} m on "
               "the other sides" if apart else f"{deepest:g} m all round")
    roads_in = next((i.alternatives.get(i.selected, "") for i in ctx.rules.interpretations
                     if i.id == CIRCULATION_IN_SETBACK and i.selected != ALL), "")
    inside = (" Roads and fire lanes may run inside it (the study's selection: "
              f"{roads_in}), which is why the loop road stands in the shaded band."
              if roads_in and "may run" in roads_in else "")
    return (f"Setback (shaded): {figures}, the deepest any block here asks: "
            f"{', '.join(setting)} at Stilt + {'/'.join(str(h) for h in heights)}. "
            "A layout of lower blocks asks less, so its roads can stand nearer the boundary."
            + inside)


def _strip_note(rules: ResolvedRules, asks) -> str:
    where = rules.green_strip.where_setback_from_m.value
    if not asks:
        return ("No green strip: no block here asks one. A high-rise asks "
                f"{rules.green_strip.width_m.value:g} m only along the sides whose setback is "
                f"{where:g} m or more (G.O.Ms.No.7 of 2016); a block below 21 m asks 1 m round "
                "the plot (G.O.168 rule 5(f)).")
    said = []
    for ask in asks:
        sides = ("all round" if ask.front and ask.others else
                 "along the front" if ask.front else "along the other sides")
        rule = ("G.O.168 rule 5(f), for a block below 21 m" if _low_strip(rules, ask) else
                f"G.O.Ms.No.7 of 2016, where the setback is {where:g} m or more")
        said.append(f"{ask.width_m:g} m {sides} ({rule})")
    return "Green strip: " + "; ".join(dict.fromkeys(said)) + ", inside the setback."


def driveway_shape(way: Way, width_m: float) -> Polygon | None:
    """A tower's driveway as drawn: the rules' driveway width, from the road to its entrance."""
    line = way.driveway
    return line.buffer(width_m / 2, cap_style="flat") if line is not None else None


def _tower_point(plan: Plan, name: str):
    """Where a tower's way-in words go when it has no entrance: on the tower."""
    return next((t.footprint.representative_point() for t in plan.towers if t.name == name),
                None)


def route_words(way: Way) -> str:
    """A tower's way in, in words for a drawing (the DXF writes them in capitals)."""
    if not way.found:
        return f"{way.tower}: no drivable route ({way.why})"
    return f"{way.tower}: {way.total_m:,.0f} m from the gate"


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
    for part in plan.setback:
        poly(part, SETBACK_LAYER)
    for part in plan.green_strip:
        poly(part, "SOLVER-GREEN-STRIP")
    for words in plan.edge_labels:
        msp.add_text(words.text.upper(), height=text_h * 0.6, rotation=words.angle_deg,
                     dxfattribs={"layer": "SOLVER-MARGIN-LABELS"}
                     ).set_placement(words.at, align=TextEntityAlignment.MIDDLE_CENTER)
    for words, pieces in plan.roads:  # every piece of every road says its width (2026-10-19)
        for piece in pieces:
            poly(piece, "SOLVER-ROADS")
            for part in _parts(piece):
                label(words, part, 0.8)
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
    _draw_ways(msp, plan, text_h)


def _draw_ways(msp, plan: Plan, text_h: float) -> None:
    """Each tower's way in: its entrance (a ring), its driveway from the road (rule 13(c)(viii)'s
    width) and its route from the gate along the roads, with the route's length."""
    for way in plan.ways:
        at = way.entrance or _tower_point(plan, way.tower)
        if at is None:
            continue
        if way.found:
            msp.add_circle((at.x, at.y), ENTRANCE_MARK_M,
                           dxfattribs={"layer": "SOLVER-TOWER-ENTRANCE"})
            drive = driveway_shape(way, plan.driveway_m)
            if drive is not None:
                for part in _parts(drive):
                    msp.add_lwpolyline(_ring(part), close=True,
                                       dxfattribs={"layer": "SOLVER-DRIVEWAYS"})
            if way.route is not None:
                msp.add_lwpolyline([*way.route.coords, (way.road_point.x, way.road_point.y)],
                                   dxfattribs={"layer": "SOLVER-ROUTES"})
        msp.add_text(route_words(way).upper(), height=text_h * 0.7,
                     dxfattribs={"layer": "SOLVER-TOWER-ENTRANCE"}).set_placement(
            (at.x + ENTRANCE_MARK_M * 1.5, at.y), align=TextEntityAlignment.MIDDLE_LEFT)


def write_dxf(plan: Plan, path: Path, notes: list[str]) -> Path:
    notes = [*notes, *plan.margin_notes]
    doc = _new_drawing(LAYERS | NOTE_LAYERS | ROUTE_LAYERS | MARGIN_LAYERS)
    msp = doc.modelspace()
    _draw(msp, plan, DXF_TEXT_M, "SOLVER-LABELS")
    _north_arrow(msp, plan.plot, PLAIN_ARROW_M_PER_MM)
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
    notes = [*notes, *plan.margin_notes]
    doc = _new_drawing(LAYERS | SHEET_LAYERS | NOTE_LAYERS | ROUTE_LAYERS | MARGIN_LAYERS)
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
    said = [part for line in plan.margin_notes
            for part in textwrap.wrap(line, SVG_NOTE_CHARS, subsequent_indent="  ")]
    minx, miny, maxx, maxy = plan.plot.bounds
    scale = SVG_WIDTH_PX / max(maxx - minx + 2 * SVG_PAD_M, maxy - miny + 2 * SVG_PAD_M)
    width = (maxx - minx + 2 * SVG_PAD_M) * scale
    drawing_h = (maxy - miny + 2 * SVG_PAD_M) * scale
    height = SVG_HEAD_PX + drawing_h + SVG_LINE_PX * (len(notes) + len(said) + 1)

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
    layers = ((plan.setback, 'fill="#efe9dc" stroke="#b9ab8c" stroke-width="0.8" '
                             'stroke-dasharray="3 2"'),
              (plan.green_strip, 'fill="#cfe5c2" stroke="#6b9b55" stroke-width="0.6"'),
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
    # 2026-10-19: every road with its width, each tower's way in, and north
    for words, pieces in plan.roads:
        out += [text(part.representative_point(), words.title(), "#4a463d")
                for piece in pieces for part in _parts(piece)]
    for way in plan.ways:
        drive = driveway_shape(way, plan.driveway_m)
        if drive is not None:
            out += [shape(part, 'fill="#f8bbd0" stroke="#c2185b" stroke-width="0.8"')
                    for part in _parts(drive)]
        if way.route is not None:
            points = " ".join(xy(x, y) for x, y in [*way.route.coords,
                                                    (way.road_point.x, way.road_point.y)])
            out.append(f'<polyline points="{points}" fill="none" stroke="#c2185b" '
                       'stroke-width="1.2" stroke-dasharray="5 3"/>')
        at = way.entrance or _tower_point(plan, way.tower)
        if at is None:
            continue
        x, y = xy(at.x, at.y).split(",")
        if way.entrance is not None:
            out.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#c2185b" stroke="#fff"/>')
        out.append(f'<text x="{float(x) + 6:.1f}" y="{float(y) - 6:.1f}" font-size="9" '
                   f'fill="#880e4f">{escape(route_words(way))}</text>')
    for words in plan.edge_labels:
        x, y = xy(*words.at).split(",")
        colour = "#3f6b2b" if words.text.startswith("green") else "#7a6a48"
        out.append(f'<text x="{x}" y="{y}" font-size="8.5" text-anchor="middle" '
                   f'dominant-baseline="middle" fill="{colour}" '
                   f'transform="rotate({-words.angle_deg:.1f} {x} {y})">{escape(words.text)}'
                   '</text>')
    ax, ay = width - SVG_ARROW_PX - 10, SVG_HEAD_PX + 10
    out.append(f'<path d="M {ax:.0f},{ay:.0f} l {-SVG_ARROW_PX / 3:.1f},{SVG_ARROW_PX} '
               f'l {SVG_ARROW_PX / 3:.1f},{-SVG_ARROW_PX * 0.3:.1f} '
               f'l {SVG_ARROW_PX / 3:.1f},{SVG_ARROW_PX * 0.3:.1f} Z" fill="#111"/>'
               f'<text x="{ax:.0f}" y="{ay - 4:.0f}" font-size="13" font-weight="700" '
               'text-anchor="middle">N</text>')
    top = SVG_HEAD_PX + drawing_h
    out += [f'<text x="14" y="{top + SVG_LINE_PX * i:.0f}" font-size="12" fill="#a3200b">'
            f'{escape(line)}</text>' for i, line in enumerate(notes, 1)]
    out += [f'<text x="14" y="{top + SVG_LINE_PX * i:.0f}" font-size="12" fill="#5a5345">'
            f'{escape(line)}</text>' for i, line in enumerate(said, len(notes) + 1)]
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))
    return path
