"""The ground a fire tender sweeps when it turns, worked out from its own dimensions.

NBC asks a 6 m lane and a turning radius of 9 m and does not say where the 9 m is measured, so the
rules keep two readings: the lane's outer edge turns on 9 m (its inner edge on 3 m), or its
centreline does (inner edge 6 m, outer edge 12 m). A lane going round a block's corner keeps its
inner edge on the corner and sweeps an annular sector about a centre on the corner's bisector. A
lane at a convex bend of a road's outer wall keeps its outer edge on both walls; at a reflex bend
the lane goes round the step as it would round a block.

The sector is ground that must stay clear: nothing built, parked or laid out on it, and it must lie
on the plot. The ring road's bends are worked out here so that nothing is placed on them; the
validator measures the same sectors again from the drawing, and a layout that leaves them clear
meets the rule.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from siteplan.optimizer.search.land import EMPTY, polygons

ARC_STEPS = 24
MIN_TURN_DEG = 5.0  # a bend shallower than this is a straight road


@dataclass(frozen=True)
class Turning:
    r_in: float
    r_out: float


def sector(centre: tuple[float, float], r_in: float, r_out: float, start: float,
           sweep: float) -> Polygon:
    angles = [start + sweep * i / ARC_STEPS for i in range(ARC_STEPS + 1)]
    cx, cy = centre
    outer = [(cx + r_out * math.cos(a), cy + r_out * math.sin(a)) for a in angles]
    inner = [(cx + r_in * math.cos(a), cy + r_in * math.sin(a)) for a in reversed(angles)]
    return Polygon(outer + inner)


@dataclass(frozen=True)
class _Corner:
    at: tuple[float, float]
    out1: tuple[float, float]
    out2: tuple[float, float]
    turn: float  # radians, positive turning left: convex on an anticlockwise outline
    sides: tuple[float, float]  # the lengths of the edges coming in and going out


def _unit(a, b) -> tuple[float, float]:
    length = math.dist(a, b) or 1.0
    return (b[0] - a[0]) / length, (b[1] - a[1]) / length


def _corners(polygon: Polygon) -> Iterator[_Corner]:
    ring = list(orient(polygon, 1.0).exterior.coords)[:-1]
    ring = [p for i, p in enumerate(ring) if math.dist(p, ring[i - 1]) > 1e-6]
    for i, here in enumerate(ring):
        before, after = ring[i - 1], ring[(i + 1) % len(ring)]
        d1, d2 = _unit(before, here), _unit(here, after)
        turn = math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])
        if abs(math.degrees(turn)) >= MIN_TURN_DEG:
            yield _Corner(here, (d1[1], -d1[0]), (d2[1], -d2[0]), turn,
                          (math.dist(before, here), math.dist(here, after)))


def _bisector(u: tuple[float, float], v: tuple[float, float]) -> tuple[float, float]:
    x, y = u[0] + v[0], u[1] + v[1]
    size = math.hypot(x, y) or 1.0
    return x / size, y / size


def _angle(v: tuple[float, float]) -> float:
    return math.atan2(v[1], v[0])


def _round_corner(c: _Corner, turning: Turning) -> Polygon:
    bx, by = _bisector(c.out1, c.out2)
    centre = (c.at[0] - turning.r_in * bx, c.at[1] - turning.r_in * by)
    return sector(centre, turning.r_in, turning.r_out, _angle(c.out1), c.turn)


def _wall_corner(c: _Corner, turning: Turning) -> Polygon:
    if c.turn > 0:  # convex: the lane keeps its outer edge on both walls
        bx, by = _bisector(c.out1, c.out2)
        reach = turning.r_out / math.cos(c.turn / 2)
        centre = (c.at[0] - reach * bx, c.at[1] - reach * by)
        return sector(centre, turning.r_in, turning.r_out, _angle(c.out1), c.turn)
    # reflex: the wall steps into the road and the lane goes round it like a block
    m1, m2 = (-c.out1[0], -c.out1[1]), (-c.out2[0], -c.out2[1])
    bx, by = _bisector(m1, m2)
    centre = (c.at[0] - turning.r_in * bx, c.at[1] - turning.r_in * by)
    return sector(centre, turning.r_in, turning.r_out, _angle(m1), c.turn)


def around_block(block: Polygon, turning: Turning) -> list[Polygon]:
    """The swept sector at each convex corner of a block, for a lane going round it on the
    outside with its inner edge on the corner (a notch in the block: the lane does not go in)."""
    return [_round_corner(c, turning) for c in _corners(block) if c.turn > 0]


def along_wall(outline: Polygon, turning: Turning) -> list[Polygon]:
    """The swept sector at each bend of the outer wall of a road."""
    return [_wall_corner(c, turning) for c in _corners(outline)]


def junction_turns(network: BaseGeometry, loop: BaseGeometry, boundary: BaseGeometry,
                   turnings: Sequence[Turning], same_m: float, touch_m: float,
                   lane_m: float) -> list[list[Polygon]]:
    """For each reading of the turning radius, the swept sector at every corner of a road network
    where one road joins another (C4-15): the corners of its outer wall and of the land it
    encloses that are no bend of the loop road (within `same_m` of one; loop_turns sweeps those)
    and not where it opens onto the street outside (within `touch_m` of the plot's boundary). A
    corner either side of which is shorter than the lane is wide is a jog, not a wall a tender
    drives along, and one that doubles back is the tip of a slit the union of the pieces left:
    neither is swept."""
    bends = [c.at for part in polygons(loop) for ring in (part.exterior, *part.interiors)
             for c in _corners(Polygon(ring))]

    def joins(c: _Corner) -> bool:
        return abs(math.degrees(c.turn)) < 180 - MIN_TURN_DEG and min(c.sides) >= lane_m \
            and all(math.dist(c.at, b) > same_m for b in bends) \
            and boundary.distance(Point(c.at)) > touch_m

    walls = [c for part in polygons(network) for c in _corners(Polygon(part.exterior))
             if joins(c)]
    holes = [c for part in polygons(network) for hole in part.interiors
             for c in _corners(Polygon(hole)) if c.turn > 0 and joins(c)]
    return [[*(_wall_corner(c, t) for c in walls), *(_round_corner(c, t) for c in holes)]
            for t in turnings]


def loop_turns(road: BaseGeometry, turnings: Sequence[Turning]) -> BaseGeometry:
    """Every swept sector along a road that rings land: along its outer wall, and round the
    corners of any land it encloses, under every reading of the turning radius."""
    pieces: list[BaseGeometry] = []
    for part in polygons(road):
        for turning in turnings:
            pieces += along_wall(Polygon(part.exterior), turning)
            for hole in part.interiors:
                pieces += around_block(Polygon(hole), turning)
    return unary_union(pieces) if pieces else EMPTY
