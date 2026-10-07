"""The road network as a graph (C4-01): nodes where roads begin, meet and end, edges along each
road's centre line between them, and every road's pavement drawn from its centre line, never the
other way round. The network can then be asked what it is (whether it is one piece, how many loops
it holds, where a road stops with nowhere to go) as well as where it lies.

A node is an entrance (where a road starts at a gate, or where the ring road itself meets one), a
junction (where roads meet), a service point (where a road ends at what it serves: a pathway at its
block), or the anchor of a loop no other road meets. An edge runs between two nodes along one
road's centre line: the ring road is a cycle of edges cut at every junction, a street an edge
between its two junctions on the ring, the main approach an edge from the entrance to its junction.
A road's centre line ends on the centre line of the road it joins, so a junction is a point both
centre lines pass through.

A road's pavement is its centre line widened by half the road's width each side, square at the
ends and mitred at the bends, on the ground the road may take (`domain`). Where a road's own
pavement covers less or more than the stretch between its nodes, `paved` is the line it is drawn
from: the approach and a pathway run their pavement only as far into the ring as joins them, the
ring's pavement carrying them on to the junction; a street paves its whole corridor between two
columns of blocks, which the cluster's outline cuts where the ring road begins.

The legal widths, the joins and the fire tender's turns stay the independent validator's to measure
on the pavement drawn here: the graph is how the search builds its roads and reasons about them,
not a claim the validator takes on trust.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from siteplan.contracts.candidate import RoadKind
from siteplan.optimizer.search.land import EMPTY, polygons

FILL_SLIVER_SQM = 0.05  # drawing noise: a piece of pavement this small is nothing
NODE_SNAP_M = 0.05  # two road ends this close are one node, and a stretch this short no edge


class NodeKind(StrEnum):
    ENTRANCE = "ENTRANCE"  # where a road starts at a gate in the plot's boundary
    JUNCTION = "JUNCTION"  # where roads meet
    SERVICE = "SERVICE"  # where a road ends at what it serves (a pathway at its block)
    LOOP = "LOOP"  # the one node of a loop no other road meets


@dataclass(frozen=True)
class Node:
    id: str
    at: tuple[float, float]
    kind: NodeKind


@dataclass(frozen=True)
class Road:
    """One road: its whole centre line (closed for a loop), its kind, the width its pavement is
    drawn at, the ground it may take, and the line its own pavement is drawn from when that is not
    its centre line between its nodes."""

    id: str  # e.g. "ring", "street-1", "approach", "pathway-1"
    kind: RoadKind
    line: LineString
    width_m: float
    domain: BaseGeometry | None = None
    paved: LineString | None = None

    @cached_property
    def ground(self) -> BaseGeometry:
        return pavement(self.paved if self.paved is not None else self.line, self.width_m,
                        self.domain)


@dataclass(frozen=True)
class Edge:
    """A stretch of one road's centre line from node `a` to node `b` (the same node for a loop no
    other road meets)."""

    id: str
    road: str
    a: str
    b: str
    line: LineString


@dataclass(frozen=True)
class RoadGraph:
    nodes: tuple[Node, ...]
    roads: tuple[Road, ...]
    edges: tuple[Edge, ...]

    def node(self, node_id: str) -> Node:
        return next(n for n in self.nodes if n.id == node_id)

    def road(self, road_id: str) -> Road:
        return next(r for r in self.roads if r.id == road_id)

    def of_kind(self, *kinds: RoadKind) -> list[Road]:
        return [r for r in self.roads if r.kind in kinds]

    def ground(self, kinds: Iterable[RoadKind] | None = None) -> BaseGeometry:
        """The pavement of every road, or of the roads of these kinds."""
        wanted = set(kinds) if kinds is not None else None
        parts = [r.ground for r in self.roads if wanted is None or r.kind in wanted]
        parts = [p for p in parts if not p.is_empty]
        return unary_union(parts) if parts else EMPTY

    def degree(self, node_id: str) -> int:
        """How many edge ends meet at a node (a loop on one node counts twice)."""
        return sum((e.a == node_id) + (e.b == node_id) for e in self.edges)

    def components(self) -> list[set[str]]:
        """The nodes each connected piece of the network joins."""
        links: dict[str, set[str]] = {n.id: set() for n in self.nodes}
        for edge in self.edges:
            links[edge.a].add(edge.b)
            links[edge.b].add(edge.a)
        pieces: list[set[str]] = []
        for start in links:
            if any(start in piece for piece in pieces):
                continue
            piece, todo = set(), [start]
            while todo:
                current = todo.pop()
                if current not in piece:
                    piece.add(current)
                    todo += links[current] - piece
            pieces.append(piece)
        return pieces

    def loops(self) -> int:
        """How many independent loops the network holds: edges less nodes plus pieces."""
        return len(self.edges) - len(self.nodes) + len(self.components())

    def dead_ends(self) -> list[Node]:
        """The nodes a road stops at with nowhere further to go: one edge end, and neither an
        entrance nor the block a pathway serves."""
        return [n for n in self.nodes if self.degree(n.id) == 1
                and n.kind not in (NodeKind.ENTRANCE, NodeKind.SERVICE)]

    def problems(self) -> list[str]:
        """What makes this no road network a layout can stand on, said plainly: none for a sound
        one."""
        out = []
        pieces = len(self.components())
        if pieces > 1:
            out.append(f"the roads fall in {pieces} pieces")
        ends = self.dead_ends()
        if ends:
            out.append(f"a road stops with nowhere to go at {len(ends)} point(s)")
        if not any(n.kind is NodeKind.ENTRANCE for n in self.nodes):
            out.append("no road starts from an entrance")
        return out


def pavement(line: LineString, width_m: float, domain: BaseGeometry | None = None
             ) -> BaseGeometry:
    """A centre line widened to a road: half the width each side, square at the ends, mitred at
    the bends; on the domain, less any piece of it too small to be a road, when one is given."""
    drawn = line.buffer(width_m / 2, cap_style="flat", join_style="mitre")
    if domain is None:
        return drawn
    parts = polygons(drawn.intersection(domain), FILL_SLIVER_SQM)
    return unary_union(parts) if parts else EMPTY


class Builder:
    """The graph as the roads are added: nodes snapped together, a loop cut wherever another road
    meets it."""

    def __init__(self) -> None:
        self.nodes: list[Node] = []
        self.roads: list[Road] = []
        self.edges: list[Edge] = []

    def node(self, at: tuple[float, float], kind: NodeKind) -> str:
        """The node at this point: an existing one within NODE_SNAP_M (an entrance or a service
        point keeps that kind), or a new one."""
        for i, n in enumerate(self.nodes):
            if Point(n.at).distance(Point(at)) <= NODE_SNAP_M:
                if kind is not NodeKind.JUNCTION and n.kind is NodeKind.JUNCTION:
                    self.nodes[i] = Node(n.id, n.at, kind)
                return n.id
        node_id = f"n{len(self.nodes) + 1}"
        self.nodes.append(Node(node_id, (float(at[0]), float(at[1])), kind))
        return node_id

    def road(self, road: Road, start: NodeKind = NodeKind.JUNCTION,
             end: NodeKind = NodeKind.JUNCTION) -> None:
        """An open road, one edge from its first point to its last."""
        self.roads.append(road)
        coords = list(road.line.coords)
        self.edges.append(Edge(f"{road.id}#1", road.id, self.node(coords[0], start),
                               self.node(coords[-1], end), road.line))

    def loop(self, road: Road, meets: Sequence[tuple[float, float]]) -> None:
        """A closed road, cut into an edge between each two points where another road meets it,
        or one edge on one node when none does."""
        self.roads.append(road)
        ring, length = road.line, road.line.length
        cuts: list[float] = []
        for along in sorted(ring.project(Point(p)) % length for p in meets):
            if not cuts or along - cuts[-1] >= NODE_SNAP_M:
                cuts.append(along)
        if len(cuts) > 1 and cuts[0] + length - cuts[-1] < NODE_SNAP_M:
            cuts.pop()  # the last meets the ring where the first does, across its first point
        if not cuts:
            anchor = self.node(ring.coords[0], NodeKind.LOOP)
            self.edges.append(Edge(f"{road.id}#1", road.id, anchor, anchor, ring))
            return
        for i, (start, stop) in enumerate(zip(cuts, [*cuts[1:], cuts[0]], strict=True), 1):
            piece = _arc(ring, start, stop)
            coords = list(piece.coords)
            self.edges.append(Edge(f"{road.id}#{i}", road.id,
                                   self.node(coords[0], NodeKind.JUNCTION),
                                   self.node(coords[-1], NodeKind.JUNCTION), piece))

    def graph(self) -> RoadGraph:
        return RoadGraph(tuple(self.nodes), tuple(self.roads), tuple(self.edges))


def _arc(ring: LineString, start: float, stop: float) -> LineString:
    """The stretch of a closed line from `start` on along it to `stop`, across its first point when
    `stop` is not past `start` (all the way round when they are the same). Each end is the point
    at that distance, so two stretches that share a distance share the point exactly."""
    if stop > start:
        return substring(ring, start, stop)
    first = list(substring(ring, start, ring.length).coords)
    second = list(substring(ring, 0.0, stop).coords) if stop > 0 else []
    return LineString(first + second[1:])


def nearest_on(line: LineString, at: tuple[float, float]) -> tuple[float, float]:
    """The point of a line nearest to `at`."""
    found = line.interpolate(line.project(Point(at)))
    return float(found.x), float(found.y)


def crossings(line: LineString, other: LineString) -> list[tuple[float, float]]:
    """Where `line` crosses `other`, in order along `line`."""
    met = line.intersection(other)
    points = [g for g in getattr(met, "geoms", [met]) if not g.is_empty]
    coords = {(float(c[0]), float(c[1])) for g in points for c in g.coords}
    return sorted(coords, key=lambda c: line.project(Point(c)))
