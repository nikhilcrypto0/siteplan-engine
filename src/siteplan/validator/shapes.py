"""Geometry the validator measures with, built here so a mistake in the generator's geometry
cannot also be a mistake in the check that is meant to catch it.

Everything is plain shapely on metres: no tower, road or fire-lane logic, only shapes.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.affinity import rotate
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel, unary_union

EPS_M = 0.01  # a centimetre: below this a drawn edge and its neighbour are the same edge
OPENING_SLACK_M = 0.005  # a part this close to the width asked is that wide
NOISE_SQM = 0.5  # less than this of overlap is drawing noise, not a car, a wall or a lane


def polygons_of(geometry: BaseGeometry | None) -> list[Polygon]:
    """Every polygon in a geometry (a polygon, a multipolygon or a collection); lines, points
    and empty parts are dropped."""
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    return [p for part in getattr(geometry, "geoms", ()) for p in polygons_of(part)]


def union_of_all(geometries) -> BaseGeometry:
    """The union of any number of geometries; empty when there are none."""
    return unary_union([g for g in geometries if g is not None and not g.is_empty])


def opening(shape: BaseGeometry, width_m: float) -> BaseGeometry:
    """The shape without any part narrower than `width_m`: shrunk by half the width and grown
    back. Square (mitre) corners, so a corner that is wide enough on both sides is kept.
    A part within a centimetre of the width is kept: shrunk by exactly half its width a part
    leaves a hairline that the geometry library drops or swells, so the shrink stops half a
    centimetre short on each side."""
    half = width_m / 2 - OPENING_SLACK_M
    with np.errstate(divide="ignore", invalid="ignore"):  # GEOS notes a collapsed shape
        return shape.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")


def narrow_part(shape: BaseGeometry, width_m: float) -> BaseGeometry:
    """The parts of a shape narrower than `width_m`."""
    return shape.difference(opening(shape, width_m))


def narrower_than(shape: BaseGeometry, width_m: float) -> bool:
    """Whether any part of the shape worth noticing (more than drawing noise) is thinner than
    `width_m`: a pinch in a long road counts however small a share of the road it is."""
    return narrow_part(shape, width_m).area > NOISE_SQM


def width_in(network: BaseGeometry, part: BaseGeometry, ceiling_m: float) -> float:
    """How wide `part` is as a stretch of `network`: the widest opening of the network that
    keeps all of the part but drawing noise, to the centimetre and never above `ceiling_m`.
    Measured in the network, so a road's end, where it meets another road, is not taken for a
    narrowing; zero for a part with no ground."""
    if part.is_empty or part.area <= 0:
        return 0.0

    def keeps(width: float) -> bool:
        return part.difference(opening(network, width)).area <= NOISE_SQM

    if keeps(ceiling_m):
        return ceiling_m
    low, high = 0.0, ceiling_m
    while high - low > EPS_M / 2:
        mid = (low + high) / 2
        low, high = (mid, high) if keeps(mid) else (low, mid)
    return low


def width_of(shape: BaseGeometry, ceiling_m: float) -> float:
    """How wide a shape is everywhere (to within drawing noise). A road drawn 8.9 m wide measures
    8.9 whatever width it declares."""
    return width_in(shape, shape, ceiling_m)


def healed(shape: BaseGeometry, gap_m: float = 0.05) -> BaseGeometry:
    """The shape with hairline cracks closed: pieces drawn to meet can miss by a hair."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return shape.buffer(gap_m, join_style="mitre").buffer(-gap_m, join_style="mitre")


def oriented_box(polygon: Polygon) -> tuple[float, float, float]:
    """(angle of the long side in radians, long side, short side) of the smallest rectangle
    round a polygon, found by trying each edge of its convex hull as a side; zeros when the
    polygon has no area."""
    if polygon.is_empty or polygon.area <= 0:
        return 0.0, 0.0, 0.0
    hull = np.array(polygon.convex_hull.exterior.coords)[:-1]
    best: tuple[float, float, float, float] | None = None
    for a, b in zip(hull, np.roll(hull, -1, axis=0), strict=True):
        along = b - a
        length = float(np.hypot(*along))
        if length < 1e-9:
            continue
        u = along / length
        v = np.array([-u[1], u[0]])
        x, y = hull @ u, hull @ v
        width, height = float(x.max() - x.min()), float(y.max() - y.min())
        if best is None or width * height < best[0]:
            angle = math.atan2(u[1], u[0])
            best = (width * height, *((angle, width, height) if width >= height
                                      else (angle + math.pi / 2, height, width)))
    return (best[1], best[2], best[3]) if best else (0.0, 0.0, 0.0)


def sides_of(polygon: Polygon) -> tuple[float, float]:
    """(long, short) side of the smallest rectangle round a polygon."""
    _, long, short = oriented_box(polygon)
    return long, short


def end_caps(polygon: Polygon, depth_m: float) -> list[BaseGeometry]:
    """The two ends of a long shape, `depth_m` deep, cut across its long axis."""
    angle, _, _ = oriented_box(polygon)
    turned = rotate(polygon, -angle, origin=(0, 0), use_radians=True)
    minx, miny, maxx, maxy = turned.bounds
    caps = [box(minx - 1, miny - 1, minx + depth_m, maxy + 1),
            box(maxx - depth_m, miny - 1, maxx + 1, maxy + 1)]
    ends = [turned.intersection(c) for c in caps]
    return [rotate(e, angle, origin=(0, 0), use_radians=True) for e in ends if not e.is_empty]


def inscribed_radius(shape: BaseGeometry) -> float:
    """The radius of the largest circle that fits inside the shape (its widest point)."""
    best = 0.0
    for polygon in polygons_of(shape):
        centre = polylabel(polygon, tolerance=0.05)
        best = max(best, polygon.boundary.distance(centre))
    return best


def clean_pieces(geometry: BaseGeometry | None, min_sqm: float = 1e-4) -> list[Polygon]:
    """Polygons of a geometry that are more than a sliver."""
    return [p for p in polygons_of(geometry) if p.area > min_sqm]
