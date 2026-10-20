"""Every tower's way in (2026-10-19, the architect): its entrance, the driveway from the road to
it, and the shortest route a car can drive from the plot's gate to it.

This is the client's requirement, never law: a check of the program (`program.route_checks`).
NBC 4.6's fire access and rule 8(m)/(l)'s roads are judged elsewhere, as law.

Everything is the validator's own reading of the candidate as drawn, so the drawings (the
service's DXF, sheet and SVG, and FreeCAD) show the same ways the report measures:

- the ways in are every road, a rule 8(l) pathway among them (the access the rule gives a
  block up to 12 m; 2026-10-19, the user: a block's road or 6 m pathway), and the gates; a car's
  centre keeps CAR_CLEAR_M in from their edges;
- a tower's entrance is at the middle of the stretch of its outline that faces its road or
  pathway, at a core on one of its long faces (its lobby), or at the middle of a short face (the
  end of its corridor); a block with no core is entered at its middle;
- its driveway runs straight from the entrance to the nearest point of a road, as wide as the
  rules' driveway (rule 13(c)(viii)), and is refused where it crosses another block, the club
  house, a facility or the organised open space; it is nothing where the block stands on a road
  (within ON_ROAD_M of it);
- the route runs along the roads' centre lines (2026-10-19, the user: never a straight line
  that looks as if it crosses a park or a block), from the gate to the point of a centre line
  nearest where the driveway leaves the road, then across to it, then the driveway, when every
  road carries the line it was drawn from and each lies on the pavement drawn (within
  CENTRE_LINE_SLACK_M); otherwise (a layout drawn by hand, or by another generator) it is the
  shortest path a car's centre can take inside the roads, bending only at their corners (a
  visibility graph). Of the entrances a tower may have, the one with the shortest route is its
  entrance.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, substring, unary_union

from siteplan.contracts.candidate import CandidateLayout, PlacedTower
from siteplan.validator.shapes import oriented_box, polygon_of, polygons_of

CAR_CLEAR_M = 1.0  # a car's centre keeps this far in from a road's edge (half a car and a little)
SIMPLIFY_M = 0.25  # the drivable ground's outline is simplified this much before its corners
COVER_EPS_M = 1e-3  # a sight line along the drivable ground's edge still counts as inside it
CROSSING_SQM = 0.5  # a driveway crossing less of another use than this does not cross it
ON_ROAD_M = 0.5  # a block this near a road stands on it: no driveway (as opens_onto_road's touch)
CENTRE_LINE_SLACK_M = 0.5  # a centre line this far off its pavement is not trusted
JOIN_M = 0.1  # centre lines whose ends come this near one another meet
NODE_DECIMALS = 3  # a junction is one point to the millimetre


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
    """The ground a block is reached on: every road, its pathways included, and the gates."""
    return unary_union([_shape(s) for r in candidate.circulation.roads for s in r.shapes]
                       + [_shape(g.shape) for g in candidate.circulation.gates])


def entrances(footprint: Polygon, cores: list[Polygon], ground: BaseGeometry | None = None
              ) -> list[Point]:
    """Where a block may be entered: the middle of the stretch of its outline that faces the
    ground given (its road or pathway), out from each core to both long faces, and the middle of
    each short face; from its middle when it has no core."""
    angle, long_m, _ = oriented_box(footprint)
    along = np.array([math.cos(angle), math.sin(angle)])
    across = np.array([-along[1], along[0]])
    reach = 2 * long_m + 1.0
    centre = footprint.centroid
    out = [_facing(footprint, ground)] if ground is not None else []
    out = [p for p in out if p is not None]
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


def _facing(footprint: Polygon, ground: BaseGeometry) -> Point | None:
    """The middle of the longest stretch of the outline within ON_ROAD_M of the ground."""
    close = footprint.exterior.intersection(ground.buffer(ON_ROAD_M))
    runs = [g for g in getattr(close, "geoms", [close]) if isinstance(g, LineString) and g.length]
    if not runs:
        return None
    merged = linemerge(runs)
    longest = max(getattr(merged, "geoms", [merged]), key=lambda g: g.length)
    return longest.interpolate(0.5, normalized=True)


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

    @property
    def empty(self) -> bool:
        return self.free.is_empty

    def snap(self, p: Point) -> Point:
        """The point of the free ground nearest `p`."""
        return nearest_points(self.free, p)[0]

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


def centre_lines(candidate: CandidateLayout) -> list[LineString]:
    """Every road's centre line, when every road carries one lying on the pavement drawn (within
    CENTRE_LINE_SLACK_M: a street's line runs on to the ring's, the approach's from the gate);
    none otherwise, so a route never follows a line the drawing does not bear out."""
    paved = drivable(candidate).buffer(CENTRE_LINE_SLACK_M)
    out = []
    for road in candidate.circulation.roads:
        if road.centre_line is None:
            return []
        line = LineString(road.centre_line.points)
        if line.length == 0 or not paved.covers(line):
            return []
        out.append(line)
    return out


class _Lines:
    """Shortest paths along the roads' centre lines from the gates: the lines joined where they
    meet (ends within JOIN_M snapped together) and cut at every crossing, a graph on the points
    where they meet, and Dijkstra from the point of the lines nearest each gate."""

    def __init__(self, lines: list[LineString], gates: list[Polygon]) -> None:
        joined = [shapely.snap(line, unary_union([o for o in lines if o is not line]), JOIN_M)
                  for line in lines]
        net = unary_union(joined)
        self.net = net
        self.segments = [s for s in getattr(net, "geoms", [net])
                         if isinstance(s, LineString) and s.length > 0]
        self.ends = [(_node(s.coords[0]), _node(s.coords[-1])) for s in self.segments]
        self.near: dict[tuple, list[tuple[tuple, int]]] = {}
        for i, (a, b) in enumerate(self.ends):
            self.near.setdefault(a, []).append((b, i))
            self.near.setdefault(b, []).append((a, i))
        self.dist: dict[tuple, float] = {}
        self.came: dict[tuple, tuple[tuple | None, int]] = {}  # node: (previous, segment)
        self.start_of: dict[tuple, Point] = {}  # a node the first stretch reaches: its gate
        self.starts = [self.snap(g.centroid) for g in gates] if self.segments else []
        queue: list[tuple[float, tuple]] = []
        for start in self.starts:
            index, along = self._on(start)
            a, b = self.ends[index]
            for node, d in ((a, along), (b, self.segments[index].length - along)):
                if d < self.dist.get(node, math.inf):
                    self.dist[node], self.came[node] = d, (None, index)
                    self.start_of[node] = start
                    heapq.heappush(queue, (d, node))
        while queue:
            d, u = heapq.heappop(queue)
            if d > self.dist[u]:
                continue
            for v, index in self.near[u]:
                w = d + self.segments[index].length
                if w < self.dist.get(v, math.inf):
                    self.dist[v], self.came[v] = w, (u, index)
                    heapq.heappush(queue, (w, v))

    @property
    def empty(self) -> bool:
        return not self.segments

    def snap(self, p: Point) -> Point:
        """The point of the centre lines nearest `p`."""
        return nearest_points(self.net, p)[0]

    def _on(self, p: Point) -> tuple[int, float]:
        """The segment a point of the lines lies on, and how far along it."""
        index = min(range(len(self.segments)), key=lambda i: self.segments[i].distance(p))
        return index, self.segments[index].project(p)

    def route(self, end: Point) -> tuple[float, LineString | None]:
        """The shortest way along the lines from a gate to `end` (a point of the lines)."""
        index, along = self._on(end)
        segment = self.segments[index]
        best, via = math.inf, None
        for start in self.starts:  # a gate on the same stretch: straight along it
            s_index, s_along = self._on(start)
            if s_index == index and abs(s_along - along) < best:
                best, via = abs(s_along - along), ("same", s_along)
        a, b = self.ends[index]
        for node, d in ((a, along), (b, segment.length - along)):
            total = self.dist.get(node, math.inf) + d
            if total < best:
                best, via = total, ("node", node)
        if via is None:
            return math.inf, None
        if via[0] == "same":
            return best, substring(segment, via[1], along)
        node = via[1]
        tail = substring(segment, 0.0 if node == a else segment.length, along)
        pieces = [list(tail.coords)]
        while True:
            previous, seg = self.came[node]
            line = self.segments[seg]
            if previous is None:  # the first stretch, from the gate's point to this node
                start = self.start_of[node]
                head = substring(line, line.project(start),
                                 0.0 if _node(line.coords[0]) == node else line.length)
                pieces.append(list(head.coords))
                break
            forward = _node(line.coords[0]) == previous
            pieces.append(list(line.coords) if forward else list(line.coords)[::-1])
            node = previous
        coords = [xy for piece in reversed(pieces) for xy in piece]
        return best, LineString(coords) if len(coords) > 1 else None


def _node(xy) -> tuple:
    return round(xy[0], NODE_DECIMALS), round(xy[1], NODE_DECIMALS)


def ways(candidate: CandidateLayout, driveway_m: float) -> list[Way]:
    """Every tower's way in from a gate, in the candidate's order of towers."""
    towers = candidate.towers
    ground = drivable(candidate)
    gates = [_shape(g.shape) for g in candidate.circulation.gates]
    if not gates:
        return [Way(t.name, why="no gate is drawn") for t in towers]
    if ground.is_empty:
        return [Way(t.name, why="no road is drawn") for t in towers]
    lines = centre_lines(candidate)
    graph: _Graph | _Lines = _Lines(lines, gates) if lines else _Graph(ground, gates)
    if graph.empty:
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
         graph: _Graph | _Lines, blocking: BaseGeometry, driveway_m: float) -> Way:
    if footprint.is_empty:
        return Way(tower.name, why="its footprint cannot be measured")
    best: Way | None = None
    crossed = False
    for entrance in entrances(footprint, cores, ground):
        road_point = nearest_points(ground, entrance)[0]
        drive = entrance.distance(road_point)
        if drive > ON_ROAD_M and LineString([entrance, road_point]).buffer(
                driveway_m / 2, cap_style="flat").intersection(blocking).area > CROSSING_SQM:
            crossed = True
            continue
        on_road = graph.snap(road_point)
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
