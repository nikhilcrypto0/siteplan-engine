"""Small geometry helpers shared by the survey readers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

COMPASS_DEG = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


@dataclass(frozen=True)
class Run:
    """A straight stretch of a boundary, merged from consecutive near-collinear edges."""

    line: LineString
    angle_deg: float  # direction modulo 180, so a run and its reverse compare equal

    @property
    def length(self) -> float:
        return float(self.line.length)


def _direction(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180


def angle_gap(a_deg: float, b_deg: float) -> float:
    """Smallest difference between two undirected line angles, in degrees."""
    gap = abs(a_deg - b_deg) % 180
    return min(gap, 180 - gap)


def straight_runs(polygon: Polygon, tolerance_deg: float = 3.0) -> list[Run]:
    """The straight stretches of the outline, of every piece when a nala splits the shape."""
    if polygon.geom_type == "MultiPolygon":
        return [run for part in polygon.geoms for run in straight_runs(part, tolerance_deg)]
    coords = list(polygon.exterior.coords)[:-1]
    edges = [(coords[i], coords[(i + 1) % len(coords)]) for i in range(len(coords))]
    edges = [e for e in edges if e[0] != e[1]]
    groups: list[list[tuple]] = [[edges[0]]]
    for edge in edges[1:]:
        if angle_gap(_direction(*edge), _direction(*groups[-1][-1])) <= tolerance_deg:
            groups[-1].append(edge)
        else:
            groups.append([edge])
    wraps = angle_gap(_direction(*groups[-1][-1]), _direction(*groups[0][0])) <= tolerance_deg
    if len(groups) > 1 and wraps:
        groups[0] = groups.pop() + groups[0]
    runs = []
    for group in groups:
        points = [group[0][0]] + [edge[1] for edge in group]
        runs.append(Run(LineString(points), _direction(points[0], points[-1])))
    return runs


def opening(shape, width_m: float):
    """Remove every part of a shape narrower than width_m (shrink by half, grow back)."""
    half = width_m / 2 - 1e-6
    return shape.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")


def facing_deg(boundary: Polygon, run: Run) -> float:
    """The compass bearing a run faces out of the plot: 0 north, 90 east (y is north)."""
    (x0, y0), (x1, y1) = run.line.coords[0], run.line.coords[-1]
    nx, ny = (y1 - y0) / run.length, (x0 - x1) / run.length
    mid = run.line.interpolate(0.5, normalized=True)
    if boundary.contains(Point(mid.x + nx * 0.5, mid.y + ny * 0.5)):
        nx, ny = -nx, -ny
    return math.degrees(math.atan2(nx, ny)) % 360


def strip_along_side(boundary: Polygon, side: str, width_m: float) -> Polygon:
    """The plot left after an even strip of that width comes off every run facing that side
    (within 45 degrees), as the architect describes it. Nothing is inferred: the side and the
    width are given; the caller checks the area that comes off against the stated deduction."""
    runs = [run for run in straight_runs(boundary)
            if abs((facing_deg(boundary, run) - COMPASS_DEG[side] + 180) % 360 - 180) < 45]
    if not runs:
        raise ValueError(f"No side of the plot faces {side}.")
    edge = unary_union([run.line for run in runs])
    rest = boundary.difference(edge.buffer(width_m, cap_style="flat", join_style="mitre"))
    parts = [p for p in getattr(rest, "geoms", [rest]) if p.geom_type == "Polygon"]
    if not parts:
        raise ValueError(f"A {width_m:g} m strip off the {side} side leaves no plot.")
    return max(parts, key=lambda p: p.area)
