"""The roads, generated from the blocks that stand and never laid down before them.

Rule 8(m) of a group development asks for 9 m roads, a main approach from the entrance, every road
meeting another road or a gate at both ends, and every block above 12 m on a road. NBC asks 6 m of
motorable ground on every side of a high-rise, turns at every corner, a way in from the gate. What
is drawn here follows from where the blocks stand:

- a *street* in the corridor between two neighbouring columns, over the stretch where both have
  blocks, so every block with a neighbour opens onto one;
- the *ring road*: the 9 m band round the whole cluster of blocks and streets (the cluster is the
  blocks and streets with the notches narrower than a road closed, and the ground they enclose
  filled), so every street ends on it and no road is a dead end, and every block on the outside
  opens onto it;
- the *main approach*, straight in from the gate to the ring, where the gate is the place on the
  access side that gives the shortest approach clear of everything;
- the *fire lanes*: whatever of the 6 m round each block no road covers, which is the ground between
  two blocks of a column.

A configuration whose ring does not close, whose cluster falls in two, or whose approach cannot
reach the ring is not offered: the reason is returned, never worked round.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.geometry import opening
from siteplan.optimizer.search.columns import Standing
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.land import EMPTY, Land, Plot, grow, polygons

MIN_STREET_LENGTH_M = 9.0  # a street shorter than its own width is no street
STREET_REACH_M = 100_000.0  # far enough that a street meets the hull's edge at both ends
FILL_SLIVER_SQM = 0.05
RING_CLIP_SQM = 0.5  # drawing noise: ground this small off a shape is nothing
RING_TIP_SQM = 40.0  # the ring may lose the tip of a corner to a slanted boundary, no more
APPROACH_REACH_SQM = 18.0  # the approach runs this much into the ring, so the two join
MIN_APPROACH_SQM = 27.0  # an approach shorter than this beyond the ring is the ring itself
TOUCH_M = 0.5
ENTRANCES_TRIED = 12  # of the positions that reach the ring, the shortest this many are checked
APPROACH_OUTSIDE_SQM = 0.02  # the approach lies wholly on the plot: a road that is cut is not 9 m
APPROACH_LONGEST_M = 150.0
GATE_STEP_M = 3.0
GATE_DEPTH_M = 2.0  # the mouth of the entrance: as deep as the planted strip
EPS_M = 0.01


def street_slots(standing: Sequence[Standing], street_width_m: float
                 ) -> list[tuple[float, float, float, float]]:
    """The corridor between each two neighbouring columns that hold blocks: its x range in the
    turned frame, and the stretch of y the two columns cover between them (so a block with a
    neighbour column opens onto the street along its full length)."""
    by_column: dict[int, list[Standing]] = {}
    for s in standing:
        by_column.setdefault(s.column, []).append(s)
    slots = []
    for column in sorted(by_column):
        right = by_column.get(column + 1)
        if right is None:
            continue
        left = by_column[column]
        low = min(min(s.y0 for s in left), min(s.y0 for s in right))
        high = max(max(s.y1 for s in left), max(s.y1 for s in right))
        x0 = max(s.x1 for s in left)
        x1 = min(s.x0 for s in right)
        if high - low >= MIN_STREET_LENGTH_M and x1 - x0 >= street_width_m - EPS_M:
            slots.append((x0, x1, low, high))
    return slots


def street_pieces(standing: Sequence[Standing], frame: Frame, street_width_m: float,
                  hull: Polygon | None = None) -> list[Polygon]:
    """The streets, in the survey's frame. Before the cluster is known a street runs the length of
    the two columns it lies between; given the hull it runs on to the hull's edge at both ends,
    where the ring road is, so no street stops short of everything."""
    out: list[Polygon] = []
    for x0, x1, low, high in street_slots(standing, street_width_m):
        if hull is None:
            out.append(frame.to_survey(box(x0, low, x1, high)))
        else:
            piece = frame.to_survey(box(x0, -STREET_REACH_M, x1, STREET_REACH_M))
            out += polygons(piece.intersection(hull), FILL_SLIVER_SQM)
    return out


@dataclass(frozen=True)
class Cluster:
    """The blocks and streets as one convex piece of ground, and the ring road round it."""

    hull: Polygon  # the convex hull of the blocks and the streets
    ring: BaseGeometry  # the road round the hull, on the roadable ground
    clipped: bool = False  # the ground cut the tip of a corner off the ring: it is still a road
    # wide, but not as wide as the band that was asked for


def _hull_of(pieces: Sequence[BaseGeometry]) -> Polygon:
    return unary_union(list(pieces)).convex_hull


def cluster_of(footprints: Sequence[Polygon], streets: Sequence[Polygon], land: Land,
               ring_width_m: float, road_width_m: float) -> tuple[Cluster | None, str]:
    """The cluster of these blocks and streets and the ring road round it, or why there is none:
    the ground does not hold the cluster with the ring round it, or the ring is not a closed road.

    The cluster is the convex hull of the blocks and the streets. A convex outline gives a ring
    with no reflex corner, so the tender never has to turn round a step in the road's outer wall
    (which would need ground beyond it), and every gap and notch inside the outline is a fire lane
    between two blocks, never a road of its own."""
    hull = _hull_of([*footprints, *streets])
    if hull.geom_type != "Polygon":
        return None, "the blocks have no area to build a road round"
    outside = hull.difference(land.cluster_land.buffer(EPS_M))
    if outside.area > RING_CLIP_SQM:
        return None, ("the cluster does not stand wholly where the ring road can run round it "
                      f"({outside.area:,.0f} m² off)")
    wanted = grow(hull, ring_width_m).difference(hull)
    ring = wanted.intersection(land.roadable)
    lost = wanted.area - ring.area
    if lost > RING_TIP_SQM:
        return None, f"the ring road is cut short by the ground that bounds it ({lost:,.0f} m²)"
    parts = polygons(ring, FILL_SLIVER_SQM)
    if not [p for p in parts if p.interiors]:
        return None, "the ring road does not close round the cluster"
    whole = unary_union(parts)
    if lost > RING_CLIP_SQM and whole.difference(opening(whole, road_width_m)).area > RING_CLIP_SQM:
        return None, "the ring road is narrower than a road in places, where the ground cuts it"
    return Cluster(hull, whole, lost > RING_CLIP_SQM), ""


def _violation(hull: Polygon, land: Land, ring_width_m: float) -> float:
    """How much of the hull, and of the ring road round it, falls off the ground that may hold
    them."""
    off = hull.difference(land.cluster_land.buffer(EPS_M)).area
    ring = grow(hull, ring_width_m).difference(hull)
    return off + max(0.0, ring.difference(land.roadable).area - RING_TIP_SQM)


def fit_cluster(standing: Sequence[Standing], frame: Frame, street_m: float, land: Land,
                ring_width_m: float, road_width_m: float, values: Sequence[float]
                ) -> tuple[list[Standing], list[Polygon], Cluster | None, str]:
    """The blocks, with the fewest taken away, whose cluster the ground holds with the ring road
    round it. The columns are laid on ground where each block fits; the convex hull of them all
    may not (a plot with an arm, a notch). Of the blocks that make the hull stand off the ground,
    the one whose removal leaves least of it off, and then the least valuable, goes first."""
    value = {id(s): v for s, v in zip(standing, values, strict=True)}
    current = list(standing)
    why = "no block stands"
    while current:
        footprints = [frame.to_survey(box(s.x0, s.y0, s.x1, s.y1)) for s in current]
        cluster, why = cluster_of(footprints, street_pieces(current, frame, street_m), land,
                                  ring_width_m, road_width_m)
        if cluster is not None:
            return current, street_pieces(current, frame, street_m, cluster.hull), cluster, ""
        if len(current) == 1:
            break
        cost = partial(_cost_of_dropping, current, frame, street_m, land, ring_width_m, value)
        drop = min(range(len(current)), key=cost)
        current = current[:drop] + current[drop + 1:]
    return [], [], None, why


def _cost_of_dropping(current: Sequence[Standing], frame: Frame, street_m: float, land: Land,
                      ring_width_m: float, value: dict[int, float], i: int
                      ) -> tuple[float, float]:
    """What is still off the ground with block `i` gone, and then what the block was worth."""
    rest = [*current[:i], *current[i + 1:]]
    kept = [frame.to_survey(box(s.x0, s.y0, s.x1, s.y1)) for s in rest]
    hull = _hull_of([*kept, *street_pieces(rest, frame, street_m)])
    return (_violation(hull, land, ring_width_m), value[id(current[i])])


@dataclass(frozen=True)
class Entrance:
    gate: Polygon  # the opening in the boundary
    approach: BaseGeometry  # the main approach road, from the gate to the ring; empty when the
    # ring road itself meets the gate
    width_m: float
    side: str | None


def find_entrance(plot: Plot, cluster: Cluster, blocked: BaseGeometry, width_m: float,
                  strip_width_m: float) -> tuple[Entrance | None, str]:
    """The gate and the straight approach that give the shortest road from the access side to the
    ring, clear of everything in `blocked` (the blocks, and ground kept for something else). The
    approach is a road 9 m wide everywhere, which a straight strip meeting the ring at a slant is
    not (a sliver of its corner is narrower), so a position is kept only if the strip and the ring
    together are as wide as a road all along it."""
    if not plot.gate_runs:
        return None, "the access side gives no stretch of boundary a gate may open in"
    half = width_m / 2 + EPS_M
    found: list[tuple[float, float, Polygon, Polygon]] = []
    for line in plot.gate_runs:
        for at, along, inward in _gate_points(plot.net, line, half):
            depth = _depth_to_ring(plot.net, at, along, inward, half, cluster.ring)
            if depth is None:
                continue
            rectangle = _rectangle(at, along, inward, half, depth)
            approach = rectangle.intersection(plot.net)
            if (rectangle.difference(plot.net.buffer(EPS_M)).area > APPROACH_OUTSIDE_SQM
                    or approach.intersection(blocked).area > RING_CLIP_SQM
                    or approach.intersection(plot.excluded).area > RING_CLIP_SQM
                    or approach.intersection(cluster.hull).area > RING_CLIP_SQM):
                continue
            gate = _rectangle(at, along, inward, half, max(GATE_DEPTH_M, strip_width_m, 1.0)
                              ).intersection(plot.net)
            found.append((depth, abs(line.project(Point(at)) - line.length / 2), gate, approach))
    if not found:
        return None, "no approach from the access side reaches the ring road clear of everything"
    for _, _, gate, approach in sorted(found, key=lambda f: f[:2])[:ENTRANCES_TRIED]:
        if approach.difference(cluster.ring).area < MIN_APPROACH_SQM \
                and gate.buffer(TOUCH_M).intersection(cluster.ring).area >= APPROACH_REACH_SQM / 2:
            approach = EMPTY  # the ring road itself meets the gate: no road is left to call one
        elif _sliver(approach, cluster.ring, width_m):
            continue
        return Entrance(gate, approach, width_m, plot.access_side), ""
    return None, "no approach meets the ring road as a road 9 m wide all along it"


def _sliver(approach: BaseGeometry, ring: BaseGeometry, width_m: float) -> bool:
    """Whether some of the approach, as a stretch of the road network, is narrower than a road."""
    network = unary_union([approach, ring])
    return approach.difference(opening(network, width_m - 2 * EPS_M)).area > RING_CLIP_SQM


def _gate_points(net: Polygon, line: LineString, half: float
                 ) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]:
    """Places along a stretch of boundary a gate of this half-width may open at: the point, the
    direction along the boundary and the direction into the plot."""
    coords = list(line.coords)
    out = []
    for (x0, y0), (x1, y1) in zip(coords, coords[1:], strict=False):
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 2 * half:
            continue
        along = ((x1 - x0) / length, (y1 - y0) / length)
        normal = (-along[1], along[0])
        middle = ((x0 + x1) / 2, (y0 + y1) / 2)
        inward = normal if net.contains(Point(middle[0] + normal[0] * 0.5,
                                              middle[1] + normal[1] * 0.5)) else (
            -normal[0], -normal[1])
        steps = int((length - 2 * half) // GATE_STEP_M)
        for i in range(steps + 1):
            t = half + i * GATE_STEP_M
            out.append(((x0 + along[0] * t, y0 + along[1] * t), along, inward))
    return out


def _rectangle(at, along, inward, half: float, depth: float) -> Polygon:
    a = (at[0] - along[0] * half, at[1] - along[1] * half)
    b = (at[0] + along[0] * half, at[1] + along[1] * half)
    return Polygon([a, b, (b[0] + inward[0] * depth, b[1] + inward[1] * depth),
                    (a[0] + inward[0] * depth, a[1] + inward[1] * depth)])


def _depth_to_ring(net: Polygon, at, along, inward, half: float, ring: BaseGeometry
                   ) -> float | None:
    """How deep a straight approach from `at` must go to run APPROACH_REACH_SQM into the ring; the
    overlap only grows with depth, so it is bisected."""
    def overlap(depth: float) -> float:
        return _rectangle(at, along, inward, half, depth).intersection(ring).area

    if overlap(APPROACH_LONGEST_M) < APPROACH_REACH_SQM:
        return None
    low, high = 0.0, APPROACH_LONGEST_M
    for _ in range(14):
        middle = (low + high) / 2
        low, high = (low, middle) if overlap(middle) >= APPROACH_REACH_SQM else (middle, high)
    return high


def fire_lanes(footprints: Sequence[Polygon], roads: BaseGeometry, net: Polygon,
               lane_width_m: float, blocks: BaseGeometry | None = None) -> BaseGeometry:
    """The ground within a lane's width of a block that no road covers: it is motorable and kept
    clear, whatever else the plot holds. `footprints` are the blocks that ask for it (the
    high-rises: below 21 m rule 15(a)(i) asks no lane); `blocks`, every block, which no lane
    covers (the footprints themselves when not given)."""
    if not footprints:
        return EMPTY
    blocks = unary_union(list(footprints)) if blocks is None else blocks
    bands = unary_union([grow(f, lane_width_m) for f in footprints]).difference(blocks)
    lanes = bands.difference(roads).intersection(net)
    return unary_union(polygons(lanes, FILL_SLIVER_SQM)) if not lanes.is_empty else EMPTY
