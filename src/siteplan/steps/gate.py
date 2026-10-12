"""The gate: where the approach road comes in from the main road. Every step's picture marks it,
so no step works without knowing where the entrance is (the architect, 2026-10-11), and step 5
keeps the land in front of it clear."""

from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring, unary_union

from siteplan import rules
from siteplan.steps.drawing import Layer, Picture
from siteplan.steps.survey_copy import ROAD_TOUCH_M, RoadSeen

LAYER = Layer("GATE", "#d62828", 1, "The gate: where the approach road comes in", width=7.0)


def gate_line(plot: Polygon, road: RoadSeen | None,
              given: tuple[BaseGeometry, ...] = ()) -> BaseGeometry:
    """The stretch of the plot's edge where the main road meets it (or `given`, land given up to
    widen it), as wide as rule 8(m)'s main approach road may be: no narrower than the narrowest
    (a road that only touches the plot still lets the approach road in, the edge either side of
    the touch taken) and no wider than the widest (its middle; step 6 may move it). Empty when
    the main road does not reach the plot."""
    if road is None or road.frontage is None or road.frontage.is_empty:
        return LineString()
    # flat ends: the reach catches an edge beside the road, never one past its ends
    reach = unary_union([road.frontage.buffer(ROAD_TOUCH_M, cap_style="flat"), *given])
    met = plot.exterior.intersection(reach)
    lines = [g for g in getattr(met, "geoms", [met])
             if g.geom_type == "LineString" and g.length > 0]
    if not lines:
        return LineString()
    merged = linemerge(lines)
    line = max(getattr(merged, "geoms", [merged]), key=lambda g: g.length)
    narrowest, widest = rules.MAIN_APPROACH_ROAD_M
    edge = LineString(plot.exterior.coords)
    middle = edge.project(line.interpolate(0.5, normalized=True))
    return linemerge(around(edge, middle, min(max(line.length, narrowest), widest) / 2))


def around(edge: LineString, middle: float, length: float) -> list[LineString]:
    """The stretch of a closed edge within `length` of the point `middle` along it, both ways
    (round the edge's start when it reaches it)."""
    total = edge.length
    if 2 * length >= total:
        return [edge]
    start, end = middle - length, middle + length
    spans = ([(start, end)] if start >= 0 and end <= total else
             [(0.0, end), (total + start, total)] if start < 0 else
             [(start, total), (0.0, end - total)])
    return [substring(edge, a, b) for a, b in spans if b > a]


def on_net(net: Polygon, road: RoadSeen | None, pieces: tuple = ()) -> BaseGeometry:
    """The gate on the net plot (step 3 on): the main road's stretch of its edge, or the land
    given up to widen the main road."""
    given = tuple(p.polygon for p in pieces
                  if road is not None and p.counted and road.name in p.widens)
    return gate_line(net, road, given)


def draw(picture: Picture, gate: BaseGeometry) -> None:
    """Mark the gate on a picture that has the LAYER and a NOTES layer."""
    if gate.is_empty:
        return
    picture.add("GATE", gate)
    middle = gate.interpolate(0.5, normalized=True)
    picture.label("NOTES", (middle.x, middle.y), "GATE")
