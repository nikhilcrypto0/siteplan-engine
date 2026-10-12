"""The engine's geometry as CAD items, one per object, each on its layer, in millimetres.

Nothing here computes a rule: every shape is one the engine already made (step 1's survey
boundary, step 3's net plot and the land given up, step 4's setback band, green strip, fire
lane, the land left for buildings, each side's setback), copied vertex for vertex. A shape in
several pieces becomes several items (`id`, `id#2`, ...), so each is one object in FreeCAD."""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.cad.bridge import to_cad
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
NOTES = "Notes"
LAYERS = (SURVEY, NET, GIVEN, SETBACK, BUILDABLE, DIMENSIONS, GREEN, FIRE, WATER, GATE,
          OUTSIDE_ROADS, ROADS, FOOTPRINTS, TOWERS, PARKING, AMENITIES, NOTES)
DIMENSION_SIDE_M = 5.0  # rendering: sides shorter than this get no dimension (jogs)
DIMENSION_SHIFT_M = 1.5  # rendering: a dimension line sits this far along its side
TEXT_SIZE_M = 2.0  # rendering: a label's height in the drawing, readable at site scale


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
            AMENITIES: style("#b15928", "#ffd8a8", 30), NOTES: style("#222222")}


def ring(coords) -> list[list[float]]:
    pts = list(coords)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]  # FreeCAD closes a ring itself
    return [to_cad(p) for p in pts]


def parts(geometry: BaseGeometry | None) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    return [g for g in getattr(geometry, "geoms", [geometry])
            if isinstance(g, Polygon) and not g.is_empty]


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


def step4_items(s: Setbacks) -> list[dict]:
    return [*survey_items(s), *net_items(s), *setback_items(s)]
