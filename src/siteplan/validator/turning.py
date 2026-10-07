"""The ground a fire tender sweeps when it turns, built from the tender's own dimensions.

NBC 2016 Part 3 4.6(c) asks a 6 m lane and a turning radius of 9 m, and does not say where the
9 m is measured, so there are two readings of it:

- outer_edge: the lane's outer edge turns on 9 m (its inner edge on 3 m);
- centreline: the lane's centreline turns on 9 m (inner edge 6 m, outer edge 12 m).

A lane going round a block's corner keeps its inner edge on the corner and sweeps an annular
sector about a centre on the corner's bisector; a lane at a convex bend of a road's outer edge
keeps its outer edge on both walls; at a reflex bend it goes round the step as it would round a
block. Where one road joins another (the approach, a street or a link meeting the loop) the
corners the junction makes are swept the same way (C4-15). The sector is the ground the tender
needs. All of it is derived here from the radii, not taken from the generator's own turning
code.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.validator.readings import CENTRELINE, OUTER_EDGE
from siteplan.validator.shapes import polygons_of

ARC_STEPS = 24  # an arc is drawn as this many chords
MIN_TURN_DEG = 5.0  # a bend shallower than this is a straight road


@dataclass(frozen=True)
class Turning:
    """The lane and the radii of its inner and outer edge, under one reading of the 9 m."""

    reading: str
    lane_m: float
    r_in: float
    r_out: float

    @property
    def reach_m(self) -> float:
        """How far from each face of a square block the sector reaches at its corner: the clear
        ground a lane needs beside a block to turn round it."""
        return self.r_out - self.r_in * math.sin(math.pi / 4)


def turning_for(rules: ResolvedRules, reading: str) -> Turning | None:
    lane = rules.fire.clear_width_m.value
    radius = rules.fire.turning_radius_m.value
    if reading == OUTER_EDGE:
        return Turning(reading, lane, radius - lane, radius)
    if reading == CENTRELINE:
        return Turning(reading, lane, radius - lane / 2, radius + lane / 2)
    return None


def sector(centre: tuple[float, float], r_in: float, r_out: float, start: float,
           sweep: float) -> Polygon:
    """The annulus between two radii about a centre, from angle `start` through `sweep` radians
    (negative sweeps clockwise)."""
    angles = [start + sweep * i / ARC_STEPS for i in range(ARC_STEPS + 1)]
    cx, cy = centre
    outer = [(cx + r_out * math.cos(a), cy + r_out * math.sin(a)) for a in angles]
    inner = [(cx + r_in * math.cos(a), cy + r_in * math.sin(a)) for a in reversed(angles)]
    return Polygon(outer + inner)


@dataclass(frozen=True)
class Corner:
    at: tuple[float, float]
    out1: tuple[float, float]  # outward normal of the edge coming in
    out2: tuple[float, float]  # outward normal of the edge going out
    turn: float  # radians, positive turning left (convex on an anticlockwise outline)
    sides: tuple[float, float]  # the lengths of the edges coming in and going out


def corners(polygon: Polygon) -> Iterator[Corner]:
    """The corners of a polygon's outer ring, walked anticlockwise, bends under MIN_TURN_DEG
    left out."""
    ring = list(orient(polygon, 1.0).exterior.coords)[:-1]
    ring = [p for i, p in enumerate(ring) if math.dist(p, ring[i - 1]) > 1e-6]
    for i, here in enumerate(ring):
        before, after = ring[i - 1], ring[(i + 1) % len(ring)]
        d1, d2 = _unit(before, here), _unit(here, after)
        turn = math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])
        if abs(math.degrees(turn)) >= MIN_TURN_DEG:
            yield Corner(here, (d1[1], -d1[0]), (d2[1], -d2[0]), turn,
                         (math.dist(before, here), math.dist(here, after)))


def _unit(a, b) -> tuple[float, float]:
    length = math.dist(a, b) or 1.0
    return (b[0] - a[0]) / length, (b[1] - a[1]) / length


def _bisector(u: tuple[float, float], v: tuple[float, float]) -> tuple[float, float]:
    x, y = u[0] + v[0], u[1] + v[1]
    size = math.hypot(x, y) or 1.0
    return x / size, y / size


def _angle(v: tuple[float, float]) -> float:
    return math.atan2(v[1], v[0])


def _round_corner(c: Corner, turning: Turning) -> Polygon:
    """The sector a lane sweeps going round a convex corner with its inner edge on it."""
    bx, by = _bisector(c.out1, c.out2)
    centre = (c.at[0] - turning.r_in * bx, c.at[1] - turning.r_in * by)
    return sector(centre, turning.r_in, turning.r_out, _angle(c.out1), c.turn)


def _wall_corner(c: Corner, turning: Turning) -> Polygon:
    """The sector a lane sweeps at a bend of a road's outer edge."""
    if c.turn > 0:  # convex: the lane keeps its outer edge on both walls
        bx, by = _bisector(c.out1, c.out2)
        reach = turning.r_out / math.cos(c.turn / 2)  # R_out / sin(half the interior angle)
        centre = (c.at[0] - reach * bx, c.at[1] - reach * by)
        return sector(centre, turning.r_in, turning.r_out, _angle(c.out1), c.turn)
    # reflex: the wall steps into the site and the lane goes round it like a block
    m1, m2 = (-c.out1[0], -c.out1[1]), (-c.out2[0], -c.out2[1])
    bx, by = _bisector(m1, m2)
    centre = (c.at[0] - turning.r_in * bx, c.at[1] - turning.r_in * by)
    return sector(centre, turning.r_in, turning.r_out, _angle(m1), c.turn)


def round_block(block: Polygon, turning: Turning) -> list[Polygon]:
    """The swept sector at each convex corner of a block, for a lane going round it on the
    outside with its inner edge on the corner (a notch in the block: the lane does not go in)."""
    return [_round_corner(c, turning) for c in corners(block) if c.turn > 0]


def along_wall(outline: Polygon, turning: Turning) -> list[Polygon]:
    """The swept sector at each bend of the outer edge of a road network."""
    return [_wall_corner(c, turning) for c in corners(outline)]


def junction_turns(network: BaseGeometry, loop: BaseGeometry, boundary: BaseGeometry,
                   turning: Turning, same_m: float, touch_m: float) -> list[Polygon]:
    """The swept sector at every corner of a road network where one road joins another (C4-15):
    the corners of its outer edge and of the land it encloses that are no bend of its loop road
    (within `same_m` of one: road_bends sweeps those) and not where it opens onto the street
    outside (within `touch_m` of the plot's boundary: the tender turns on the street there). A
    corner either side of which is shorter than the lane is wide is a jog in the drawing, not a
    wall a tender drives along, and one that doubles back is the tip of a slit: neither is
    swept."""
    bends = [c.at for part in polygons_of(loop) for ring in (part.exterior, *part.interiors)
             for c in corners(Polygon(ring))]

    def joins(c: Corner) -> bool:
        return abs(math.degrees(c.turn)) < 180 - MIN_TURN_DEG \
            and min(c.sides) >= turning.lane_m \
            and all(math.dist(c.at, b) > same_m for b in bends) \
            and boundary.distance(Point(c.at)) > touch_m

    out: list[Polygon] = []
    for part in polygons_of(network):
        out += [_wall_corner(c, turning) for c in corners(Polygon(part.exterior)) if joins(c)]
        for hole in part.interiors:
            out += [_round_corner(c, turning) for c in corners(Polygon(hole))
                    if c.turn > 0 and joins(c)]
    return out


def road_bends(road_land: BaseGeometry, turning: Turning) -> list[Polygon]:
    """Every bend of a road network that rings land: along its outer edge, and round the corners
    of any land it encloses."""
    out: list[Polygon] = []
    for part in polygons_of(road_land):
        out += along_wall(Polygon(part.exterior), turning)
        for hole in part.interiors:
            out += round_block(Polygon(hole), turning)
    return out
