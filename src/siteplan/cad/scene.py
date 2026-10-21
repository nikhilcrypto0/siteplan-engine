"""The engine's geometry as CAD items, one per object, each on its layer, in millimetres.

Nothing here computes a rule: every shape is one the engine already made (step 1's survey
boundary, step 3's net plot and the land given up, step 4's setback band, green strip, fire
lane, the land left for buildings, each side's setback), copied vertex for vertex. A shape in
several pieces becomes several items (`id`, `id#2`, ...), so each is one object in FreeCAD."""

from __future__ import annotations

import math
import textwrap

from shapely import set_precision
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from siteplan.cad.bridge import to_cad
from siteplan.service.render import driveway_shape, route_words
from siteplan.steps import carried
from siteplan.steps.gate import on_net
from siteplan.steps.setbacks import Setbacks

SURVEY = "Survey boundary"
NET = "Net plot"
GIVEN = "Land given up"
SETBACK = "Setback zone"
BUILDABLE = "Buildable area"
DIMENSIONS = "Setback dimensions"
GREEN = "Green strip"
FIRE = "Fire-access lane"
WATER = "Water buffer"
GATE = "Gate"
OUTSIDE_ROADS = "Roads outside the plot"
ROADS = "Internal roads and driveways"
FOOTPRINTS = "Building footprints"
TOWERS = "Towers"
PARKING = "Parking zones"
AMENITIES = "Clubhouse and amenities"
OPEN_SPACE = "Open space and tot-lot"
FLATS = "Flats"
CORES = "Lift and stair cores"
NOTES = "Notes"
DETAIL = "Notes: verdict in full"  # the long note under a layout, hidden for a screenshot
ROUTES = "Entrances, driveways and routes from the gate"
NORTH = "North arrow"
LAYERS = (SURVEY, NET, GIVEN, SETBACK, BUILDABLE, DIMENSIONS, GREEN, FIRE, WATER, GATE,
          OUTSIDE_ROADS, ROADS, FOOTPRINTS, TOWERS, FLATS, CORES, PARKING, OPEN_SPACE,
          AMENITIES, ROUTES, NORTH, NOTES, DETAIL)
DIMENSION_SIDE_M = 5.0  # rendering: sides shorter than this get no dimension (jogs)
DIMENSION_SHIFT_M = 1.5  # rendering: a dimension line sits this far along its side
TEXT_SIZE_M = 2.0  # rendering: a label's height in the drawing, readable at site scale
SHEET_TEXT_M = 5.0  # rendering: the sheet label's height, readable when a whole site is shown
CHAR_WIDTH = 0.6  # rendering: a character's width as a share of the text's height
LINE_PITCH = 1.5  # rendering: a text line's height, baseline to baseline, in text heights
SNAP_M = 1e-6  # a hole nearer its outer edge than this is snapped to a grid this fine
NORTH_SIZE_M = 12.0  # rendering: the north arrow's length on the ground
NORTH_GAP_M = 10.0  # rendering: the north arrow stands this far right of the plot


def _rgb(hex_colour: str) -> list[float]:
    return [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def styles() -> dict[str, dict]:
    """Each layer's line and fill colour (the steps' pictures' colours), its transparency in
    percent and its line width in pixels."""
    def style(line: str, fill: str | None = None, transparency: int = 0,
              width: float = 2.0) -> dict:
        out = {"line": _rgb(line), "transparency": transparency, "width": width}
        if fill:
            out["fill"] = _rgb(fill)
        return out

    return {SURVEY: style("#000000", width=3.0), NET: style("#2e8b3d", width=3.0),
            GIVEN: style("#b07aa1", "#b07aa1", 60), SETBACK: style("#f08c00", "#f9c27d", 70),
            BUILDABLE: style("#3b6fb6", "#dfe8f5", 60, 2.5),
            DIMENSIONS: style("#7a3e00", width=1.0), GREEN: style("#2e8b3d", "#8fc79a", 40),
            FIRE: style("#8b0000", "#b33a3a", 55), WATER: style("#00a6c8", "#9edcea", 50),
            GATE: style("#d62828", width=6.0), OUTSIDE_ROADS: style("#d62828", "#f6dada", 75),
            ROADS: style("#5a5a5a", "#9a9a9a", 40), FOOTPRINTS: style("#111111", "#7ea6dc", 15),
            TOWERS: style("#111111", "#1f3f7a", 15, 2.5), PARKING: style("#6a3d9a", "#cab2d6", 40),
            AMENITIES: style("#b15928", "#ffd8a8", 30), NOTES: style("#222222"),
            DETAIL: style("#444444"), ROUTES: style("#c2185b", "#f8bbd0", 30, 2.5),
            NORTH: style("#111111", "#111111", 0, 2.0),
            OPEN_SPACE: style("#4d9221", "#b8e186", 35), FLATS: style("#1f3f7a", "#7ea6dc", 20,
                                                                         0.8),
            CORES: style("#333333", "#8c8c8c", 10, 0.8)}


def ring(coords) -> list[list[float]]:
    pts = list(coords)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]  # FreeCAD closes a ring itself
    return [to_cad(p) for p in pts]


def parts(geometry: BaseGeometry | None) -> list[Polygon]:
    """The polygons of a shape, each valid: a 'hole' that shares a stretch of its outer edge (a
    fire lane broken at one place) is a C, not a hole, and FreeCAD would cut it into faces its
    read-back does not see as one; it is made valid first, its area unchanged."""
    if geometry is None or geometry.is_empty:
        return []
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    out = []
    for piece in _flat(geometry):
        if not isinstance(piece, Polygon) or piece.is_empty:
            continue
        if any(piece.exterior.distance(hole) < SNAP_M for hole in piece.interiors):
            # a hole a hair inside the outer edge, closer than CAD can tell apart: on a
            # micrometre grid it is the C it is
            out += [g for g in _flat(set_precision(piece, SNAP_M))
                    if isinstance(g, Polygon) and not g.is_empty]
        else:
            out.append(piece)
    return out


def _flat(geometry: BaseGeometry) -> list[BaseGeometry]:
    if hasattr(geometry, "geoms"):
        return [part for g in geometry.geoms for part in _flat(g)]
    return [geometry]


def polygon_items(ident: str, label: str, layer: str, geometry: BaseGeometry | None,
                  kind: str) -> list[dict]:
    """A polygon (or each piece of one) as an `outline` (its outer edge, a Draft wire whose
    points can be dragged) or an `area` (with its holes, a Part face)."""
    out = []
    for n, piece in enumerate(sorted(parts(geometry), key=lambda p: -p.area), 1):
        rings = [ring(piece.exterior.coords)]
        if kind == "area":
            rings += [ring(hole.coords) for hole in piece.interiors]
        out.append({"id": ident if n == 1 else f"{ident}#{n}",
                    "label": label if n == 1 else f"{label} ({n})", "layer": layer,
                    "kind": kind, "rings": rings})
    return out


def tower_label(tower, sep: str) -> str:
    """A tower's name, its height and its flats a floor, e.g. 'T1 · Stilt + 9 · 12 flats a
    floor': the flats alone read like a floor count (2026-10-12)."""
    height = [f"Stilt + {tower.floors_above_stilt}"] if tower.floors_above_stilt else []
    return sep.join([tower.name, *height, f"{tower.flats_per_floor} flats a floor"])


def _inward(net: Polygon, line: LineString) -> tuple[Point, tuple[float, float]] | None:
    (ax, ay), (bx, by) = line.coords[0], line.coords[-1]
    length = math.hypot(bx - ax, by - ay)
    if length == 0:
        return None
    middle = line.interpolate(0.5, normalized=True)
    for nx, ny in ((-(by - ay) / length, (bx - ax) / length),
                   ((by - ay) / length, -(bx - ax) / length)):
        if net.contains(Point(middle.x + nx * 0.01, middle.y + ny * 0.01)):
            return middle, (nx, ny)
    return None


def setback_dimensions(s: Setbacks) -> list[dict]:
    """Each side's setback as a CAD dimension: from the middle of the side, square to it, as far
    in as the side keeps open (step 4's figure for that side)."""
    out = []
    for side in s.sides:
        if side.length_m < DIMENSION_SIDE_M or side.metres <= 0:
            continue
        found = _inward(s.widening.net, side.line)
        if found is None:
            continue
        middle, (nx, ny) = found
        (ax, ay), (bx, by) = side.line.coords[0], side.line.coords[-1]
        along = (bx - ax) / side.length_m, (by - ay) / side.length_m
        end = (middle.x + nx * side.metres, middle.y + ny * side.metres)
        line = ((middle.x + end[0]) / 2 + along[0] * DIMENSION_SHIFT_M,
                (middle.y + end[1]) / 2 + along[1] * DIMENSION_SHIFT_M)
        out.append({"id": f"setback-side-{side.number}",
                    "label": f"Setback, side {side.number} ({side.faces}): {side.metres:g} m",
                    "layer": DIMENSIONS, "kind": "dimension", "start": to_cad(middle.coords[0]),
                    "end": to_cad(end), "line": to_cad(line)})
    return out


def survey_items(s: Setbacks) -> list[dict]:
    """Step 1: the survey's property boundary, and the roads drawn round it."""
    out = polygon_items("survey-boundary", "Survey boundary (step 1)", SURVEY, s.copy.plot,
                        "outline")
    for item in carried.found_in(s.copy):
        if item.kind != carried.ROAD or item.shape is None:
            continue
        out += polygon_items(f"road-{item.key}", f"Road {item.key} (as drawn)", OUTSIDE_ROADS,
                             item.shape, "area")
    return out


def net_items(s: Setbacks) -> list[dict]:
    """Step 3: the net plot, the land given up to widen a road, and the gate."""
    w = s.widening
    out = polygon_items("net-plot", "Net plot (step 3)", NET, w.net, "outline")
    for k, piece in enumerate((p for p in w.pieces if p.counted), 1):
        out += polygon_items(f"given-{k}", f"Land given up {k}", GIVEN, piece.polygon, "area")
    gate = on_net(w.net, s.height.road, w.pieces)
    if not gate.is_empty:
        lines = list(getattr(gate, "geoms", [gate]))
        for k, line in enumerate(lines, 1):
            out.append({"id": "gate" if k == 1 else f"gate#{k}",
                        "label": "Gate: the way in from the main road", "layer": GATE,
                        "kind": "line", "points": [to_cad(p) for p in line.coords]})
    return out


def setback_items(s: Setbacks) -> list[dict]:
    """Step 4: the setback zone, the land left for buildings, the green strip, where the fire
    lane can run, every water body's buffer and each side's setback as a dimension."""
    out = polygon_items("setback-zone", f"Setback zone (Stilt + {s.floors})", SETBACK, s.band,
                        "area")
    out += polygon_items("buildable", f"Buildable area (Stilt + {s.floors})", BUILDABLE, s.left,
                         "outline")
    out += polygon_items("green-strip", "Green strip (2 m)", GREEN, s.green, "area")
    out += polygon_items("fire-lane", "Where the fire lane can run", FIRE, s.fire_lane, "area")
    for water in s.widening.water:
        if water.buffer_m is not None:
            out += polygon_items(f"water-{water.kind}", f"Buffer of the {water.kind}", WATER,
                                 water.kept_free, "area")
    out += setback_dimensions(s)
    return out


def picture_layers(picture, step: str) -> tuple[list[tuple[str, list[dict]]], dict[str, dict]]:
    """A step's own picture (steps/drawing.Picture: the engine's shapes in metres, its layers,
    colours and labels) as CAD items, one group per layer in the picture's own drawing order, and
    each layer's style. Nothing is measured again: every vertex is the picture's. A polygon with
    no hole is an outline (draggable points), one with holes an area; a line stays a line, a
    point a point, a label a text."""
    styles: dict[str, dict] = {}
    groups: list[tuple[str, list[dict]]] = []
    for layer in picture.layers:
        name = f"{step} · {layer.name}"
        prefix = f"{step.lower().replace(' ', '')}-{layer.name.lower()}"
        items: list[dict] = []
        for geometry in (g for n, g in picture.shapes if n == layer.name):
            items += _shape_items(f"{prefix}-{len(items) + 1}", layer.legend or layer.name,
                                  name, geometry)
        for k, (_, at, text) in enumerate((x for x in picture.labels if x[0] == layer.name), 1):
            items.append({"id": f"{prefix}-text-{k}", "label": text.split("\n")[0],
                          "layer": name, "kind": "text", "at": to_cad(at), "text": text,
                          "size": TEXT_SIZE_M * 1000})
        if not items:
            continue
        fill = _rgb(layer.colour)
        styles[name] = {"line": fill, "fill": fill, "width": layer.width,
                        "transparency": round((1 - layer.fill) * 100) if layer.fill else 100,
                        "dash": bool(layer.dash)}
        groups.append((name, items))
    return groups, styles


def _shape_items(ident: str, label: str, layer: str, geometry: BaseGeometry) -> list[dict]:
    out: list[dict] = []
    for g in getattr(geometry, "geoms", [geometry]):
        if g.is_empty:
            continue
        key = ident if not out else f"{ident}.{len(out) + 1}"
        if isinstance(g, Polygon):
            out += polygon_items(key, label, layer, g, "area" if g.interiors else "outline")
        elif g.geom_type in ("LineString", "LinearRing"):
            out.append({"id": key, "label": label, "layer": layer, "kind": "line",
                        "points": [to_cad(p) for p in g.coords]})
        elif g.geom_type == "Point":
            out.append({"id": key, "label": label, "layer": layer, "kind": "point",
                        "at": to_cad((g.x, g.y))})
        elif hasattr(g, "geoms"):
            out += _shape_items(key, label, layer, g)
    return out


def candidate_layers(plan, setback_zone: BaseGeometry | None, setback_words: str
                     ) -> list[tuple[str, list[dict]]]:
    """A candidate layout (service.render.plan_of: the engine's shapes for it, every tower with
    its flats and cores placed) as CAD groups in the order to draw them: the ground first, then
    each tower on its own, so the towers can be watched going down one by one."""
    groups: list[tuple[str, list[dict]]] = []

    def add(layer: str, ident: str, label: str, shapes) -> None:
        items: list[dict] = []
        for k, shape in enumerate(shapes, 1):
            items += polygon_items(f"{ident}-{k}", label, layer, shape,
                                   "area" if any(p.interiors for p in parts(shape))
                                   else "outline")
        if items:
            groups.append((layer, items))

    add(NET, "layout-net", "Net plot", [plan.plot])
    if setback_zone is None and plan.setback:  # the validator's band (render.margins)
        setback_zone, setback_words = unary_union(plan.setback), "Setback"
    add(SETBACK, "layout-setback", setback_words, [setback_zone] if setback_zone else [])
    add(GREEN, "layout-green", "Green strip", plan.green_strip)
    for n, (words, pieces) in enumerate(plan.roads, 1):  # two roads may share a name
        add(ROADS, f"layout-road-{n}", f"{words.title()} ({n})", pieces)
    add(FIRE, "layout-fire", "Fire hardstanding", plan.fire)
    add(GATE, "layout-gate", "Main entrance", plan.gates)
    add(PARKING, "layout-cellar", "Cellar", plan.cellars)
    add(PARKING, "layout-ramp", "Ramp 1:8", plan.ramps)
    add(PARKING, "layout-bay", "Parking bay", plan.bays)
    add(OPEN_SPACE, "layout-open", "Tot-lot / open space", plan.open_space)
    for n, (name, shape) in enumerate(plan.amenities, 1):  # two amenities may share a name
        add(AMENITIES, f"layout-amenity-{n}", name, [shape])
    if plan.club is not None:
        add(AMENITIES, "layout-club", f"Club house, {plan.club_floors} floors", [plan.club])
    for tower in plan.towers:
        key = f"layout-{tower.name.lower().replace(' ', '-')}"
        items = polygon_items(key, tower_label(tower, " · "),
                              TOWERS, tower.footprint, "outline")
        items += [i for k, flat in enumerate(tower.flats, 1)
                  for i in polygon_items(f"{key}-flat-{k}", f"{tower.name} flat {k}",
                                         FLATS, flat, "outline")]
        items += [i for k, core in enumerate(tower.cores, 1)
                  for i in polygon_items(f"{key}-core-{k}", f"{tower.name} core {k}", CORES,
                                         core, "outline")]
        c = tower.footprint.centroid
        items.append({"id": f"{key}-text", "label": f"{tower.name} label", "layer": NOTES,
                      "kind": "text", "at": to_cad((c.x, c.y)), "size": TEXT_SIZE_M * 1500,
                      "text": tower_label(tower, "\n")})
        groups.append((f"{TOWERS}: {tower.name}", items))
    groups += [g for g in (_road_labels(plan), _margin_labels(plan), _ways(plan),
                           _north(plan.plot)) if g[1]]
    return groups


def _margin_labels(plan) -> tuple[str, list[dict]]:
    """Each stretch's setback and green strip, how deep or wide and which rule asks the strip
    (2026-10-21), at the points render.margins gives; FreeCAD's text stands level."""
    items = [{"id": f"layout-margin-{k}", "label": words.text, "layer": NOTES, "kind": "text",
              "at": to_cad(words.at), "size": TEXT_SIZE_M * 700, "text": words.text}
             for k, words in enumerate(getattr(plan, "edge_labels", ()), 1)]
    return NOTES, items


def _road_labels(plan) -> tuple[str, list[dict]]:
    """Every piece of every road says its width (2026-10-19)."""
    items = []
    for n, (words, pieces) in enumerate(plan.roads, 1):
        for k, part in enumerate((p for piece in pieces for p in parts(piece)), 1):
            at = part.representative_point()
            items.append({"id": f"layout-road-{n}-label-{k}", "label": f"{words.title()} label",
                          "layer": NOTES, "kind": "text", "at": to_cad((at.x, at.y)),
                          "size": TEXT_SIZE_M * 1000, "text": words.title()})
    return NOTES, items


def _ways(plan) -> tuple[str, list[dict]]:
    """Each tower's way in from the gate (validator.routes): its entrance, its driveway from the
    road and its route along the roads, with the route's length."""
    items: list[dict] = []
    for way in plan.ways:
        key = f"layout-way-{way.tower.lower().replace(' ', '-')}"
        drive = driveway_shape(way, plan.driveway_m)
        if drive is not None:
            items += polygon_items(f"{key}-driveway", f"{way.tower} driveway", ROUTES, drive,
                                   "outline")
        if way.route is not None:
            points = [*way.route.coords, (way.road_point.x, way.road_point.y)]
            items.append({"id": f"{key}-route", "label": f"{way.tower} route from the gate",
                          "layer": ROUTES, "kind": "line", "points": [to_cad(p) for p in points]})
        if way.entrance is not None:
            items.append({"id": f"{key}-entrance", "label": f"{way.tower} entrance",
                          "layer": ROUTES, "kind": "point",
                          "at": to_cad((way.entrance.x, way.entrance.y))})
        at = way.entrance or next((t.footprint.representative_point() for t in plan.towers
                                   if t.name == way.tower), None)
        if at is not None:
            items.append({"id": f"{key}-text", "label": f"{way.tower} route length",
                          "layer": ROUTES, "kind": "text", "at": to_cad((at.x, at.y)),
                          "size": TEXT_SIZE_M * 1000, "text": route_words(way)})
    return ROUTES, items


def _north(plot: Polygon) -> tuple[str, list[dict]]:
    """A north arrow beside the plot's top right corner: the survey's +y, as both surveys'
    arrows draw north."""
    _, _, maxx, maxy = plot.bounds
    x, y, size = maxx + NORTH_GAP_M, maxy, NORTH_SIZE_M
    head = [(x - size / 3, y - size), (x, y), (x + size / 3, y - size), (x, y - size * 0.7),
            (x - size / 3, y - size)]
    return NORTH, [{"id": "layout-north-arrow", "label": "North", "layer": NORTH,
                    "kind": "line", "points": [to_cad(p) for p in head]},
                   {"id": "layout-north-text", "label": "North label", "layer": NORTH,
                    "kind": "text", "at": to_cad((x, y + TEXT_SIZE_M)),
                    "size": TEXT_SIZE_M * 1500, "text": "N"}]


LAYOUT = "layout-"  # every object of a layout drawn from a run starts so (candidate_layers)


def wrapped(lines: list[str], width_m: float, size_m: float = TEXT_SIZE_M) -> list[str]:
    """The lines broken at words so that none, drawn `size_m` high, is wider than `width_m`
    (2026-10-17: in FreeCAD one long line made the view zoom out until nothing was readable)."""
    chars = max(1, int(width_m / (size_m * CHAR_WIDTH)))
    out: list[str] = []
    for line in lines:
        out += textwrap.wrap(line, chars, break_long_words=True) or [""]
    return out


def sheet_label(plot: BaseGeometry, lines: list[str]) -> dict:
    """What the sheet says of the layout drawn (2026-10-16, the architect): DEBUG or STUDY where
    they apply, its verdict in a few words, PRELIMINARY for floor plates; above the plot's
    north-west corner, no wider than the plot."""
    x0, _, x1, y1 = plot.bounds
    text = wrapped(lines, x1 - x0, SHEET_TEXT_M)
    return {"id": f"{LAYOUT}sheet-label", "label": "What this layout is", "layer": NOTES,
            "kind": "text", "at": to_cad((x0, y1 + LINE_PITCH * SHEET_TEXT_M * len(text))),
            "size": SHEET_TEXT_M * 1000, "text": "\n".join(text)}


def sheet_note(plot: BaseGeometry, lines: list[str]) -> dict:
    """The verdict in full (every reading, fact and rule it rests on, and why it could not be
    exported), below the plot, no wider than it, on a layer of its own (DETAIL) that a
    screenshot hides so the view is framed on the plot."""
    x0, y0, x1, _ = plot.bounds
    return {"id": f"{LAYOUT}sheet-note", "label": "The verdict in full", "layer": DETAIL,
            "kind": "text", "at": to_cad((x0, y0 - LINE_PITCH * TEXT_SIZE_M)),
            "size": TEXT_SIZE_M * 1000, "text": "\n".join(wrapped(lines, x1 - x0))}


def step4_items(s: Setbacks) -> list[dict]:
    return [*survey_items(s), *net_items(s), *setback_items(s)]
