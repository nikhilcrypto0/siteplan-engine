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

Each road is drawn from its centre line (road_graph.py): the ring's runs half a road out from the
cluster's outline, a street's down the middle of its corridor from the ring's centre line to the
ring's centre line again, the approach's from the gate to the ring's; `road_graph` joins them,
with the pathways to the blocks below 21 m, into one network whose junctions and loops can be
counted. A configuration whose ring does not close, whose cluster falls in two, or whose approach
cannot reach the ring is not offered: the reason is returned, never worked round.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan import rules as law
from siteplan.contracts.candidate import RoadKind
from siteplan.geometry import opening
from siteplan.optimizer.search.columns import Standing
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.land import EMPTY, Land, Plot, grow, polygons
from siteplan.optimizer.search.road_graph import (
    FILL_SLIVER_SQM,
    Builder,
    NodeKind,
    Road,
    RoadGraph,
    crossings,
    nearest_on,
    pavement,
)

# A street shorter than its own width (rule 8(m)'s 9 m, read from rules.py) is no street.
MIN_STREET_LENGTH_M = law.INTERNAL_ROAD_M
STREET_REACH_M = 100_000.0  # far enough that a street meets the hull's edge at both ends
RING_CLIP_SQM = 0.5  # drawing noise: ground this small off a shape is nothing
RING_TIP_SQM = 40.0  # the ring may lose the tip of a corner to a slanted boundary, no more
APPROACH_REACH_SQM = 18.0  # the approach runs this much into the ring, so the two join
MIN_APPROACH_SQM = 27.0  # an approach shorter than this beyond the ring is the ring itself
TOUCH_M = 0.5
ENTRANCES_TRIED = 12  # of the positions that reach the ring, the shortest this many are checked
APPROACH_OUTSIDE_SQM = 0.02  # the approach lies wholly on the plot: a road that is cut is not 9 m
APPROACH_LONGEST_M = 150.0
GATE_STEP_M = 3.0
# The mouth of the entrance: as deep as the planted strip (rule 7(a)(viii)'s 2 m, from rules.py).
GATE_DEPTH_M = law.PERIPHERAL_GREEN_STRIP_M
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


def street_pieces(standing: Sequence[Standing], frame: Frame, street_width_m: float
                  ) -> list[Polygon]:
    """The streets before the cluster is known, in the survey's frame: each runs the length of
    the two columns it lies between. The cluster is drawn round them (`street_roads` gives the
    streets once it is)."""
    return [frame.to_survey(box(x0, low, x1, high))
            for x0, x1, low, high in street_slots(standing, street_width_m)]


def street_roads(standing: Sequence[Standing], frame: Frame, street_width_m: float,
                 cluster: Cluster) -> list[Road]:
    """The streets once the cluster is known: each the centre line of its corridor from where it
    crosses the ring road's centre line to where it crosses it again, paved across the corridor
    and on to the hull's edge at both ends, where the ring road is, so no street stops short of
    everything."""
    out: list[Road] = []
    for x0, x1, _, _ in street_slots(standing, street_width_m):
        middle = (x0 + x1) / 2
        corridor = frame.to_survey(LineString([(middle, -STREET_REACH_M),
                                               (middle, STREET_REACH_M)]))
        ends = crossings(corridor, cluster.road.line)
        if len(ends) < 2:
            ends = list(corridor.intersection(cluster.hull).coords)  # a dead end, said so
        road = Road(f"street-{len(out) + 1}", RoadKind.INTERNAL, LineString([ends[0], ends[-1]]),
                    x1 - x0, cluster.hull, paved=corridor)
        if not road.ground.is_empty:
            out.append(road)
    return out


@dataclass(frozen=True)
class Cluster:
    """The blocks and streets as one convex piece of ground, and the ring road round it."""

    hull: Polygon  # the convex hull of the blocks and the streets
    road: Road  # the ring road: its centre line round the hull, paved on the roadable ground
    clipped: bool = False  # the ground cut the tip of a corner off the ring: it is still a road
    # wide, but not as wide as the band that was asked for

    @property
    def ring(self) -> BaseGeometry:
        """The ring road's ground."""
        return self.road.ground


def _hull_of(pieces: Sequence[BaseGeometry]) -> Polygon:
    return unary_union(list(pieces)).convex_hull


def ring_centre(hull: Polygon, ring_width_m: float) -> LineString:
    """The ring road's centre line: half a road out from the hull all round, its corners square
    (the hull is convex, so the band the line paves is the hull grown by a road, less the hull)."""
    return LineString(grow(hull, ring_width_m / 2).exterior.coords)


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
    road = Road("ring", RoadKind.LOOP, ring_centre(hull, ring_width_m), ring_width_m,
                land.roadable)
    wanted = pavement(road.line, ring_width_m)
    lost = wanted.area - wanted.intersection(land.roadable).area
    if lost > RING_TIP_SQM:
        return None, f"the ring road is cut short by the ground that bounds it ({lost:,.0f} m²)"
    whole = road.ground
    if not [p for p in polygons(whole) if p.interiors]:
        return None, "the ring road does not close round the cluster"
    if lost > RING_CLIP_SQM and _narrower_than_a_road(hull, whole, road_width_m):
        return None, "the ring road is narrower than a road in places, where the ground cuts it"
    return Cluster(hull, road, lost > RING_CLIP_SQM), ""


def _narrower_than_a_road(hull: Polygon, ring: BaseGeometry, road_width_m: float) -> bool:
    """Whether the ground cuts the ring road narrower than a road anywhere: a road as wide as the
    rule asks (a hair under), laid against the cluster's outline with its turns rounded, leaves the
    ring's ground. The ground cuts the ring only from outside, so a cut within the ring's margin
    over a road leaves the road whole. (Opening the ring at the road's width instead shrinks a ring
    exactly that wide to a line, whose last digits decide what grows back.)"""
    road = ring_centre(hull, road_width_m).buffer(road_width_m / 2 - EPS_M, cap_style="flat",
                                                  join_style="round")
    return road.difference(ring).area > RING_CLIP_SQM


def _violation(hull: Polygon, land: Land, ring_width_m: float) -> float:
    """How much of the hull, and of the ring road round it, falls off the ground that may hold
    them."""
    off = hull.difference(land.cluster_land.buffer(EPS_M)).area
    ring = pavement(ring_centre(hull, ring_width_m), ring_width_m)
    return off + max(0.0, ring.difference(land.roadable).area - RING_TIP_SQM)


def fit_cluster(standing: Sequence[Standing], frame: Frame, street_m: float, land: Land,
                ring_width_m: float, road_width_m: float, values: Sequence[float]
                ) -> tuple[list[Standing], list[Road], Cluster | None, str]:
    """The blocks, with the fewest taken away, whose cluster the ground holds with the ring road
    round it, and the streets between them. The columns are laid on ground where each block fits;
    the convex hull of them all may not (a plot with an arm, a notch). Of the blocks that make the
    hull stand off the ground, the one whose removal leaves least of it off, and then the least
    valuable, goes first."""
    value = {id(s): v for s, v in zip(standing, values, strict=True)}
    current = list(standing)
    why = "no block stands"
    while current:
        footprints = [frame.to_survey(box(s.x0, s.y0, s.x1, s.y1)) for s in current]
        cluster, why = cluster_of(footprints, street_pieces(current, frame, street_m), land,
                                  ring_width_m, road_width_m)
        if cluster is not None:
            return current, street_roads(current, frame, street_m, cluster), cluster, ""
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
    road: Road | None  # the main approach, from the gate to the ring; None when the ring road
    # itself meets the gate
    width_m: float
    side: str | None
    at: tuple[float, float]  # where the entrance's centre line crosses the boundary

    @property
    def approach(self) -> BaseGeometry:
        """The main approach road's ground; empty when the ring road itself meets the gate."""
        return self.road.ground if self.road is not None else EMPTY


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
    found: list[tuple[float, float, Polygon, BaseGeometry, LineString]] = []
    for line in plot.gate_runs:
        for at, along, inward in _gate_points(plot.net, line, half):
            depth = _depth_to_ring(plot.net, at, along, inward, half, cluster.ring)
            if depth is None:
                continue
            paved = LineString([at, (at[0] + inward[0] * depth, at[1] + inward[1] * depth)])
            approach = pavement(paved, 2 * half, plot.net)
            if (pavement(paved, 2 * half).difference(plot.net.buffer(EPS_M)).area
                    > APPROACH_OUTSIDE_SQM
                    or approach.intersection(blocked).area > RING_CLIP_SQM
                    or approach.intersection(plot.excluded).area > RING_CLIP_SQM
                    or approach.intersection(cluster.hull).area > RING_CLIP_SQM):
                continue
            gate = _rectangle(at, along, inward, half, max(GATE_DEPTH_M, strip_width_m, 1.0)
                              ).intersection(plot.net)
            found.append((depth, abs(line.project(Point(at)) - line.length / 2), gate, approach,
                          paved))
    if not found:
        return None, "no approach from the access side reaches the ring road clear of everything"
    for _, _, gate, approach, paved in sorted(found, key=lambda f: f[:2])[:ENTRANCES_TRIED]:
        at = paved.coords[0]
        if approach.difference(cluster.ring).area < MIN_APPROACH_SQM \
                and gate.buffer(TOUCH_M).intersection(cluster.ring).area >= APPROACH_REACH_SQM / 2:
            # the ring road itself meets the gate: no road is left to call one
            return Entrance(gate, None, width_m, plot.access_side, at), ""
        if _sliver(approach, cluster.ring, width_m):
            continue
        road = Road("approach", RoadKind.APPROACH, joining(paved, cluster.road.line), 2 * half,
                    plot.net, paved=paved)
        return Entrance(gate, road, width_m, plot.access_side, at), ""
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


def joining(paved: LineString, ring: LineString) -> LineString:
    """The centre line of a road that branches off the ring road, from its start to the ring's
    centre line: along its paved line to where that crosses the ring's centre line, or else on
    from the end of its pavement (inside the ring's) to the nearest point of the ring's centre
    line."""
    start, end = paved.coords[0], paved.coords[-1]
    crossed = crossings(paved, ring)
    if crossed:
        return LineString([start, crossed[0]])
    return LineString([start, end, nearest_on(ring, end)])


def pathway_road(number: int, paved: LineString, width_m: float, cluster: Cluster) -> Road:
    """A rule 8(l) pathway as a road: paved from the face of the block it serves into the ring,
    its centre line on to the ring's."""
    return Road(f"pathway-{number}", RoadKind.PATHWAY, joining(paved, cluster.road.line), width_m,
                paved=paved)


def road_graph(cluster: Cluster, streets: Sequence[Road], entrance: Entrance,
               pathways: Sequence[Road]) -> RoadGraph:
    """Every road of a layout as one network: the ring cut at every point another road meets it,
    each street between its two junctions on it, the approach from the entrance, and each pathway
    from the block it serves. Where the ring road itself meets the gate, the entrance is a node of
    the ring."""
    builder = Builder()
    ring = cluster.road.line
    branches = [*streets, *([entrance.road] if entrance.road is not None else []), *pathways]
    meets = [c for road in branches for c in (road.line.coords[0], road.line.coords[-1])
             if Point(c).distance(ring) <= EPS_M]
    if entrance.road is None:
        meets.append(nearest_on(ring, entrance.at))
    builder.loop(cluster.road, meets)
    for street in streets:
        builder.road(street)
    if entrance.road is not None:
        builder.road(entrance.road, start=NodeKind.ENTRANCE)
    else:
        builder.node(nearest_on(ring, entrance.at), NodeKind.ENTRANCE)
    for pathway in pathways:
        builder.road(pathway, start=NodeKind.SERVICE)
    return builder.graph()


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
