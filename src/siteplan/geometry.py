"""Small geometry helpers shared by the survey readers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union


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


def largest_polygon(segments: list[LineString]) -> Polygon | None:
    """Close a soup of line segments into polygons and return the biggest one."""
    if len(segments) < 3:
        return None
    polygons = list(polygonize(unary_union(segments)))
    return max(polygons, key=lambda p: p.area) if polygons else None
