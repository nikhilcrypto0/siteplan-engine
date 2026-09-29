"""Small geometry helpers shared by the survey readers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Polygon


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


def opening(shape, width_m: float):
    """Remove every part of a shape narrower than width_m (shrink by half, grow back)."""
    half = width_m / 2 - 1e-6
    return shape.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")


def _keep_behind(polygon: Polygon, line: LineString, signed_width_m: float) -> Polygon:
    """The polygon less a strip of that width along the line; the sign picks the side."""
    kept = polygon.difference(line.buffer(signed_width_m, single_sided=True))
    if kept.geom_type == "Polygon":
        return kept
    parts = [p for p in kept.geoms if p.geom_type == "Polygon"]
    return max(parts, key=lambda p: p.area) if parts else polygon


def less_road_strip(boundary: Polygon, net_area_sqm: float) -> Polygon:
    """The plot that is left after the gross-to-net deduction.

    On a Telangana site that deduction is land lost to road widening, so it comes off the
    frontage rather than evenly all round: an even inset would leave buildings standing in
    the strip the road will take. Which boundary faces the road is the assumption the gates
    already make, the longest straight run.
    """
    if net_area_sqm >= boundary.area:
        return boundary
    frontage = max(straight_runs(boundary), key=lambda r: r.length).line
    probe = min(boundary.bounds[2] - boundary.bounds[0], boundary.bounds[3] - boundary.bounds[1])
    side = max((1.0, -1.0), key=lambda s: boundary.area - _keep_behind(boundary, frontage, s).area)
    lo, hi = 0.0, probe
    for _ in range(60):  # the strip width that leaves exactly the net area
        mid = (lo + hi) / 2
        if _keep_behind(boundary, frontage, mid * side).area > net_area_sqm:
            lo = mid
        else:
            hi = mid
    return _keep_behind(boundary, frontage, hi * side)
