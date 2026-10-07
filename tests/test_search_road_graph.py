"""The full search's roads as a graph of centre lines (C4-01): nodes where roads begin, meet and
end, edges along each road's centre line, and every road's pavement drawn from its centre line.

On made-up land, every layout the quick search lays out is held to the network it should be: one
piece, no road that stops with nowhere to go, the ring road a loop cut at every junction, each
street an edge between two junctions on the ring, the approach from an entrance at the gate, and
each rule 8(l) pathway from the block it serves. The ground a road takes is its centre line
widened, so moving the line moves the road; and a layout whose roads are not one network is
refused, with the reason.
"""

from __future__ import annotations

from functools import cache
from unittest.mock import patch

import pytest
from search_support import l_plot, rectangle, strategy
from shapely import affinity
from shapely.geometry import LineString, Point, box
from shapely.ops import linemerge, unary_union

from siteplan.contracts.candidate import RoadKind
from siteplan.optimizer.search import layout, network
from siteplan.optimizer.search import strategy as strategy_module
from siteplan.optimizer.search.land import polygons
from siteplan.optimizer.search.layout import Config, evaluate, lay_out, make_run
from siteplan.optimizer.search.readings import profiles
from siteplan.optimizer.search.road_graph import (
    Builder,
    NodeKind,
    Road,
    RoadGraph,
    pavement,
)

TEST_CLASS = "normative"

ON_LINE_M = 1e-6  # a point this close to a centre line is on it
SITES = ("rectangle", "l_plot")


@cache
def _search(name: str) -> tuple:
    """Every layout the quick search lays out on this made-up land, with the evaluation it was laid
    out from: the strategy's own lay_out calls are watched."""
    made = rectangle() if name == "rectangle" else l_plot()
    found = []
    real = strategy_module.lay_out

    def watched(run, ev):
        laid, why = real(run, ev)
        if laid is not None:
            found.append((ev, laid))
        return laid, why

    with patch.object(strategy_module, "lay_out", watched):
        strategy().propose(made.context())
    assert len(found) >= 5, f"the quick search laid out only {len(found)} layouts on {name}"
    return tuple(found)


def _every(*names: str):
    return [(ev, laid) for name in names for ev, laid in _search(name)]


def _ends(graph: RoadGraph, road_id: str) -> tuple[str, str]:
    (edge,) = [e for e in graph.edges if e.road == road_id]
    return edge.a, edge.b


def _on_ring(graph: RoadGraph, node_id: str) -> bool:
    return Point(graph.node(node_id).at).distance(graph.road("ring").line) <= ON_LINE_M


# --- Every layout's roads are one network -------------------------------------------------------


@pytest.mark.parametrize("name", SITES)
def test_every_layout_the_search_lays_out_is_one_road_network(name):
    for _, laid in _search(name):
        graph = laid.graph
        assert graph.problems() == []
        assert len(graph.components()) == 1
        assert graph.dead_ends() == []
        assert sum(n.kind is NodeKind.ENTRANCE for n in graph.nodes) == 1


@pytest.mark.parametrize("name", SITES)
def test_the_ring_road_is_a_loop_cut_at_every_junction(name):
    for ev, laid in _search(name):
        graph = laid.graph
        ring = graph.road("ring")
        assert ring is ev.cluster.road  # the cluster's ring, the same centre line and pavement
        pieces = [e for e in graph.edges if e.road == "ring"]
        assert abs(sum(e.line.length for e in pieces) - ring.line.length) <= ON_LINE_M
        merged = linemerge([e.line for e in pieces])
        assert merged.geom_type == "LineString" and merged.is_closed  # one closed loop
        for edge in pieces:
            for end in (edge.a, edge.b):
                node = graph.node(end)
                assert graph.degree(end) >= 3 or node.kind is NodeKind.ENTRANCE, end
        streets = graph.of_kind(RoadKind.INTERNAL)
        assert graph.loops() == 1 + len(streets)  # each street closes one loop more


@pytest.mark.parametrize("name", SITES)
def test_each_street_runs_between_two_junctions_on_the_ring_and_paves_its_corridor(name):
    seen = 0
    for ev, laid in _search(name):
        graph, ring = laid.graph, laid.ring
        for street in graph.of_kind(RoadKind.INTERNAL):
            a, b = _ends(graph, street.id)
            assert a != b
            for end in (a, b):
                assert graph.node(end).kind is NodeKind.JUNCTION and graph.degree(end) >= 3
                assert _on_ring(graph, end)
            assert street.ground.difference(ev.cluster.hull).area < ON_LINE_M
            touching = polygons(street.ground.buffer(0.5).intersection(ring), 1.0)
            assert len(touching) >= 2, "a street that meets the ring at one end is a dead end"
            seen += 1
    assert seen


@pytest.mark.parametrize("name", SITES)
def test_the_approach_runs_from_an_entrance_at_the_gate_to_a_junction_on_the_ring(name):
    for _, laid in _search(name):
        graph, entrance = laid.graph, laid.entrance
        (gate,) = [n for n in graph.nodes if n.kind is NodeKind.ENTRANCE]
        if entrance.road is None:  # the ring road itself meets the gate
            assert _on_ring(graph, gate.id)
            continue
        assert graph.road("approach") is entrance.road
        a, b = _ends(graph, "approach")
        assert a == gate.id and graph.degree(a) == 1
        assert Point(gate.at).distance(entrance.gate) <= ON_LINE_M
        assert graph.node(b).kind is NodeKind.JUNCTION and _on_ring(graph, b)
        assert graph.degree(b) >= 3
        assert entrance.approach is entrance.road.ground


def test_a_pathway_runs_from_the_block_it_serves_to_a_junction_on_the_ring():
    seen = 0
    for _, laid in _search("l_plot"):
        graph = laid.graph
        for path in graph.of_kind(RoadKind.PATHWAY):
            a, b = _ends(graph, path.id)
            assert graph.node(a).kind is NodeKind.SERVICE and graph.degree(a) == 1
            served = [p for p in laid.placements
                      if p.footprint.distance(Point(graph.node(a).at)) <= network.TOUCH_M]
            assert len(served) == 1  # the block the pathway reaches
            assert graph.node(b).kind is NodeKind.JUNCTION and _on_ring(graph, b)
            assert path.ground.distance(laid.ring) == 0.0  # it runs into the ring
            assert path.ground.distance(served[0].footprint) <= network.TOUCH_M
            assert abs(path.ground.area - path.width_m * path.paved.length) < 1e-6
            seen += 1
    assert seen, "no layout on the L-plot used a pathway"


# --- The ground is the centre line widened -----------------------------------------------------


def test_every_road_is_its_centre_line_widened_and_moves_with_it():
    for _, laid in _every(*SITES):
        for road in laid.graph.roads:
            line = road.paved if road.paved is not None else road.line
            again = pavement(line, road.width_m, road.domain)
            assert again.symmetric_difference(road.ground).area < 1e-9, road.id
            loose = Road(road.id, road.kind, road.line, road.width_m, None, road.paved)
            moved = Road(road.id, road.kind, affinity.translate(road.line, 1.0, 0.0),
                         road.width_m, None, affinity.translate(road.paved, 1.0, 0.0)
                         if road.paved is not None else None)
            shifted = affinity.translate(loose.ground, 1.0, 0.0)
            assert moved.ground.symmetric_difference(shifted).area < 1e-6, road.id
            assert moved.ground.symmetric_difference(loose.ground).area > 1.0, road.id


def test_the_layout_roads_are_the_graphs():
    for _, laid in _every(*SITES):
        graph = laid.graph
        assert laid.ring is graph.road("ring").ground
        assert laid.streets == [r.ground for r in graph.of_kind(RoadKind.INTERNAL)]
        assert laid.pathways == [r.ground for r in graph.of_kind(RoadKind.PATHWAY)]
        assert laid.entrance.approach.equals(graph.ground([RoadKind.APPROACH])) \
            or laid.entrance.approach.is_empty


# --- A graph that is not one network is said so, and refused -----------------------------------


def _square_ring() -> Road:
    return Road("ring", RoadKind.LOOP, LineString([(0, 0), (60, 0), (60, 40), (0, 40), (0, 0)]),
                9.0)


def test_a_sound_network_has_no_problems_and_one_loop():
    builder = Builder()
    builder.loop(_square_ring(), [(30, 0)])
    builder.road(Road("approach", RoadKind.APPROACH, LineString([(30, -20), (30, 0)]), 9.0),
                 start=NodeKind.ENTRANCE)
    graph = builder.graph()
    assert graph.problems() == []
    assert graph.loops() == 1 and len(graph.components()) == 1


def test_a_road_that_stops_with_nowhere_to_go_is_a_dead_end():
    builder = Builder()
    builder.loop(_square_ring(), [(30, 0), (20, 40)])
    builder.road(Road("approach", RoadKind.APPROACH, LineString([(30, -20), (30, 0)]), 9.0),
                 start=NodeKind.ENTRANCE)
    builder.road(Road("street-1", RoadKind.INTERNAL, LineString([(20, 40), (20, 15)]), 9.0))
    graph = builder.graph()
    assert graph.problems() == ["a road stops with nowhere to go at 1 point(s)"]
    assert [n.at for n in graph.dead_ends()] == [(20.0, 15.0)]


def test_a_pathway_ends_at_the_block_it_serves_and_is_no_dead_end():
    builder = Builder()
    builder.loop(_square_ring(), [(30, 0), (60, 20)])
    builder.road(Road("approach", RoadKind.APPROACH, LineString([(30, -20), (30, 0)]), 9.0),
                 start=NodeKind.ENTRANCE)
    builder.road(Road("pathway-1", RoadKind.PATHWAY, LineString([(75, 20), (60, 20)]), 6.0),
                 start=NodeKind.SERVICE)
    assert builder.graph().problems() == []


def test_roads_in_two_pieces_and_no_entrance_are_said():
    builder = Builder()
    builder.loop(_square_ring(), [])
    builder.road(Road("street-1", RoadKind.INTERNAL, LineString([(200, 0), (200, 50)]), 9.0))
    assert builder.graph().problems() == [
        "the roads fall in 2 pieces", "a road stops with nowhere to go at 2 point(s)",
        "no road starts from an entrance"]


def test_the_entrance_is_a_node_of_the_ring_when_the_ring_itself_meets_the_gate():
    hull = box(0, 0, 60, 40)
    ring = Road("ring", RoadKind.LOOP, network.ring_centre(hull, 9.0), 9.0)
    entrance = network.Entrance(box(20, -11, 29, -9), None, 9.0, "S", (24.5, -9.0))
    graph = network.road_graph(network.Cluster(hull, ring), [], entrance, [])
    (gate,) = [n for n in graph.nodes if n.kind is NodeKind.ENTRANCE]
    assert Point(gate.at).distance(ring.line) <= ON_LINE_M
    assert graph.degree(gate.id) == 2 and graph.problems() == [] and graph.loops() == 1


def test_lay_out_refuses_a_layout_whose_roads_are_not_one_network():
    made = rectangle()
    found = profiles(made.rules, made.brief, list(made.kit))
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)
    ev = evaluate(run, Config(next(p for p in found if p.key == "ALL-ALL"), 0.0, 0.0, 8))
    laid, why = lay_out(run, ev)
    assert laid is not None, why
    real = network.road_graph

    def with_a_stray_road(*args):
        graph = real(*args)
        stray = Road("street-9", RoadKind.INTERNAL, LineString([(500, 500), (500, 560)]), 9.0)
        builder = Builder()
        builder.nodes, builder.roads, builder.edges = (list(graph.nodes), list(graph.roads),
                                                       list(graph.edges))
        builder.road(stray)
        return builder.graph()

    with patch.object(layout.network, "road_graph", with_a_stray_road):
        laid, why = lay_out(run, ev)
    assert laid is None
    assert why == ("the roads are not one network: the roads fall in 2 pieces; a road stops "
                   "with nowhere to go at 2 point(s)")


def test_the_motor_roads_leave_the_pathways_out():
    for _, laid in _search("l_plot"):
        if not laid.pathways:
            continue
        motor = laid.graph.ground(layout.MOTOR_ROADS)
        for pathway in laid.pathways:
            assert pathway.difference(motor).area > 1.0  # its own pavement is not a motor road
        assert unary_union([motor, *laid.pathways]).area > motor.area
        return
    pytest.fail("no layout on the L-plot used a pathway")
