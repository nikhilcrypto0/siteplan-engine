"""Every tower's way in (2026-10-19, the architect): its entrance, the driveway from the road to
it, and the shortest route a car can drive from the plot's gate to it.

This is the client's requirement, never law: a check of the program (`program.route_checks`).
NBC 4.6's fire access and rule 8(m)/(l)'s roads are judged elsewhere, as law.

Everything is the validator's own reading of the candidate as drawn, so the drawings (the
service's DXF, sheet and SVG, and FreeCAD) show the same ways the report measures:

- the roads a car drives are every road but a rule 8(l) pathway, and the gates; a car's centre
  keeps CAR_CLEAR_M in from their edges;
- a tower's entrance is at a core, on one of its long faces (its lobby), or at the middle of a
  short face (the end of its corridor); a block with no core is entered at its middle;
- its driveway runs straight from the entrance to the nearest point of a road, as wide as the
  rules' driveway (rule 13(c)(viii)), and is refused where it crosses another block, the club
  house, a facility or the organised open space; it is nothing where the block stands on a road
  (within ON_ROAD_M of it);
- the route is the shortest path a car's centre can take inside the roads from a gate to where
  the driveway leaves the road (bends only at the roads' corners, found on a visibility graph),
  then the driveway; of the entrances a tower may have, the one with the shortest route is its
  entrance. A driver's line is a little longer than this shortest path.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from siteplan.contracts.candidate import CandidateLayout, PlacedTower, RoadKind
from siteplan.validator.shapes import oriented_box, polygon_of, polygons_of

CAR_CLEAR_M = 1.0  # a car's centre keeps this far in from a road's edge (half a car and a little)
SIMPLIFY_M = 0.25  # the drivable ground's outline is simplified this much before its corners
COVER_EPS_M = 1e-3  # a sight line along the drivable ground's edge still counts as inside it
CROSSING_SQM = 0.5  # a driveway crossing less of another use than this does not cross it
ON_ROAD_M = 0.5  # a block this near a road stands on it: no driveway (as opens_onto_road's touch)


@dataclass(frozen=True)
class Way:
    """One tower's way in. `route` runs from a gate to `road_point`, where the driveway leaves
    the road for the `entrance`; with no way, `why` says what stops it."""

    tower: str
    entrance: Point | None = None
    road_point: Point | None = None
    route: LineString | None = None
    route_m: float = math.inf
    driveway_m: float = 0.0
    why: str = ""

    @property
    def found(self) -> bool:
        return self.entrance is not None

    @property
    def total_m(self) -> float:
        return self.route_m + self.driveway_m

    @property
    def driveway(self) -> LineString | None:
        if self.entrance is None or self.driveway_m <= 0:
            return None
        return LineString([self.road_point, self.entrance])


def drivable(candidate: CandidateLayout) -> BaseGeometry:
    """The ground a car drives on: every road but a pathway, and the gates."""
    return unary_union([_shape(s) for r in candidate.circulation.roads
                        if r.kind is not RoadKind.PATHWAY for s in r.shapes]
                       + [_shape(g.shape) for g in candidate.circulation.gates])


def entrances(footprint: Polygon, cores: list[Polygon]) -> list[Point]:
    """Where a block may be entered: out from each core to both long faces, and the middle of
    each short face; from its middle when it has no core."""
    angle, long_m, _ = oriented_box(footprint)
    along = np.array([math.cos(angle), math.sin(angle)])
    across = np.array([-along[1], along[0]])
    reach = 2 * long_m + 1.0
    centre = footprint.centroid
    out = []
    for start, directions in [*((c.centroid, (across, -across)) for c in cores or [centre]),
                              (centre, (along, -along))]:
        for d in directions:
            ray = LineString([(start.x, start.y), (start.x + d[0] * reach,
                                                   start.y + d[1] * reach)])
            hit = footprint.exterior.intersection(ray)
            points = [p for p in getattr(hit, "geoms", [hit]) if isinstance(p, Point)]
            if points:
                out.append(max(points, key=start.distance))
    return out


class _Graph:
    """Shortest paths inside the drivable ground from the gates: a visibility graph on the
    corners of its outline, kept CAR_CLEAR_M in."""

    def __init__(self, ground: BaseGeometry, gates: list[Polygon]) -> None:
        self.free = ground.buffer(-CAR_CLEAR_M).simplify(SIMPLIFY_M)
        self.inside = self.free.buffer(COVER_EPS_M)
        shapely.prepare(self.inside)
        corners = [xy for p in getattr(self.free, "geoms", [self.free]) if not p.is_empty
                   for ring in [p.exterior, *p.interiors] for xy in list(ring.coords)[:-1]]
        self.nodes = np.array(corners, dtype=float).reshape(-1, 2)
        k = len(self.nodes)
        self.dist = np.full(k, math.inf)
        self.came: list[int | Point] = [-1] * k
        self.starts = [nearest_points(self.free, g.centroid)[0] for g in gates
                       if not self.free.is_empty]
        if k and self.starts:
            self._spread(k)

    def _seen_from(self, p: Point) -> np.ndarray:
        if not len(self.nodes):
            return np.zeros(0, dtype=bool)
        here = np.repeat([[p.x, p.y]], len(self.nodes), axis=0)
        return shapely.covers(self.inside, shapely.linestrings(
            np.stack([here, self.nodes], axis=1)))

    def _spread(self, k: int) -> None:
        i, j = np.triu_indices(k, 1)
        seen = shapely.covers(self.inside, shapely.linestrings(
            np.stack([self.nodes[i], self.nodes[j]], axis=1)))
        near: list[list[tuple[int, float]]] = [[] for _ in range(k)]
        for a, b in zip(i[seen], j[seen], strict=True):
            d = float(np.hypot(*(self.nodes[a] - self.nodes[b])))
            near[a].append((b, d))
            near[b].append((a, d))
        queue: list[tuple[float, int]] = []
        for start in self.starts:
            for n in np.nonzero(self._seen_from(start))[0]:
                d = start.distance(Point(self.nodes[n]))
                if d < self.dist[n]:
                    self.dist[n], self.came[n] = d, start
                    heapq.heappush(queue, (d, int(n)))
        while queue:
            d, u = heapq.heappop(queue)
            if d > self.dist[u]:
                continue
            for v, w in near[u]:
                if d + w < self.dist[v]:
                    self.dist[v], self.came[v] = d + w, u
                    heapq.heappush(queue, (d + w, v))

    def route(self, end: Point) -> tuple[float, LineString | None]:
        """The shortest path from a gate to `end` (a point of the free ground) and its length."""
        best, via = math.inf, None
        for start in self.starts:
            if self.inside.covers(LineString([start, end])) and start.distance(end) < best:
                best, via = start.distance(end), start
        seen = self._seen_from(end)
        for n in np.nonzero(seen)[0]:
            d = self.dist[n] + end.distance(Point(self.nodes[n]))
            if d < best:
                best, via = d, int(n)
        if via is None:
            return math.inf, None
        points = [end]
        while not isinstance(via, Point):
            points.append(Point(self.nodes[via]))
            via = self.came[via]
        points.append(via)
        return best, LineString(points[::-1]) if len(points) > 1 else None


def ways(candidate: CandidateLayout, driveway_m: float) -> list[Way]:
    """Every tower's way in from a gate, in the candidate's order of towers."""
    towers = candidate.towers
    ground = drivable(candidate)
    gates = [_shape(g.shape) for g in candidate.circulation.gates]
    if not gates:
        return [Way(t.name, why="no gate is drawn") for t in towers]
    if ground.is_empty:
        return [Way(t.name, why="no road is drawn") for t in towers]
    graph = _Graph(ground, gates)
    if graph.free.is_empty:
        return [Way(t.name, why="the roads are too narrow for a car") for t in towers]
    program = candidate.program
    footprints = [_footprint(candidate, t) for t in towers]
    others = [_shape(program.club_house.shape)] if program.club_house else []
    others += [_shape(a.shape) for a in program.amenities]
    others += [_shape(s) for s in program.open_space]
    return [_way(t, footprints[i], _cores(candidate, t), ground, graph,
                 unary_union([*footprints[:i], *footprints[i + 1:], *others]), driveway_m)
            for i, t in enumerate(towers)]


def _cores(candidate: CandidateLayout, tower: PlacedTower) -> list[Polygon]:
    prototype = candidate.prototype(tower.prototype_id)
    return [p for z in prototype.core_zones for p in polygons_of(tower.world(_shape(z.shape)))]


def _shape(shape) -> BaseGeometry:
    """A contract shape as the rest of the validator reads it: a hole too short to be a ring
    dropped, a shape that crosses itself mended (the report names the flaw elsewhere)."""
    return polygon_of(shape)[0]


def _footprint(candidate: CandidateLayout, tower: PlacedTower) -> Polygon:
    """The block's footprint as its prototype and placement make it, mended; its largest piece
    when mending splits it."""
    placed = polygons_of(tower.world(_shape(candidate.prototype(tower.prototype_id).footprint)))
    return max(placed, key=lambda p: p.area) if placed else Polygon()


def _way(tower: PlacedTower, footprint: Polygon, cores: list[Polygon], ground: BaseGeometry,
         graph: _Graph, blocking: BaseGeometry, driveway_m: float) -> Way:
    if footprint.is_empty:
        return Way(tower.name, why="its footprint cannot be measured")
    best: Way | None = None
    crossed = False
    for entrance in entrances(footprint, cores):
        road_point = nearest_points(ground, entrance)[0]
        drive = entrance.distance(road_point)
        if drive > ON_ROAD_M and LineString([entrance, road_point]).buffer(
                driveway_m / 2, cap_style="flat").intersection(blocking).area > CROSSING_SQM:
            crossed = True
            continue
        on_road = nearest_points(graph.free, road_point)[0]
        length, route = graph.route(on_road)
        if math.isinf(length):
            continue
        way = Way(tower.name, entrance, road_point, route, length + on_road.distance(road_point),
                  drive if drive > ON_ROAD_M else 0.0)
        if best is None or way.total_m < best.total_m:
            best = way
    if best is not None:
        return best
    if crossed:
        return Way(tower.name, why="every driveway from a road to its entrances crosses another "
                   "block, the club house, a facility or the open space")
    return Way(tower.name, why="no road a car can drive from a gate reaches it")
