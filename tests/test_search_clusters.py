"""More than one cluster of blocks, each round its own ring road, joined into one network (C4-02).

The first cluster is the convex outline of the blocks the ground holds with a ring road round it;
a plot of two wings that one convex outline cannot take in (two squares joined by a narrow neck)
leaves the second wing empty, or, where the first cluster's ramp then has no road to stand beside,
lays nothing at all. A configuration that lets further clusters stand lays columns on the ground
the first leaves, fits them round a ring road of their own, and joins that ring to one already
laid by a link road. Everything is held to the one network of the road graph (C4-01), and the
independent validator judges every layout as before.

Everything runs on made-up land.
"""

from __future__ import annotations

from functools import cache
from unittest.mock import patch

from search_support import made_up, rectangle, strategy
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from siteplan.contracts.candidate import RoadKind
from siteplan.optimizer.search import network
from siteplan.optimizer.search import strategy as strategy_module
from siteplan.optimizer.search.layout import Config, Failure, evaluate, make_run
from siteplan.optimizer.search.readings import profiles
from siteplan.optimizer.search.road_graph import NodeKind, Road

TEST_CLASS = "normative"

WEST, EAST = box(0, 0, 120, 120), box(170, 0, 290, 120)
NECK = box(120, 30, 170, 90)
DOG_BONE = unary_union([WEST, NECK, EAST])  # two 120 m squares and a 50 m neck between them
ON_LINE_M = 1e-6


@cache
def _dog_bone():
    return made_up(DOG_BONE)


@cache
def _search() -> tuple:
    """The quick search on the dog-bone: what it proposes, and every layout it laid out with more
    than one cluster, with the evaluation it came from."""
    found = []
    real = strategy_module.lay_out

    def watched(run, ev):
        laid, why = real(run, ev)
        if laid is not None and len(ev.clusters) > 1:
            found.append((ev, laid))
        return laid, why

    with patch.object(strategy_module, "lay_out", watched):
        proposal = strategy().propose(_dog_bone().context())
    return proposal, tuple(found)


def _mostly_in(footprint, region) -> bool:
    return footprint.intersection(region).area > footprint.area / 2


def test_the_second_wing_takes_a_cluster_of_its_own_joined_by_a_link():
    _, laid_out = _search()
    assert laid_out, "no layout with a second cluster was laid out on the dog-bone"
    for ev, laid in laid_out:
        graph = laid.graph
        assert graph.problems() == []
        rings = graph.of_kind(RoadKind.LOOP)
        assert [r.id for r in rings] == ["ring", *(f"ring-{i}" for i in range(2, len(rings) + 1))]
        assert {_mostly_in(c.hull, WEST) for c in ev.clusters} == {True, False}
        for link in ev.links:
            (edge,) = [e for e in graph.edges if e.road == link.id]
            ends = [graph.node(edge.a), graph.node(edge.b)]
            on = [{r.id for r in rings if Point(n.at).distance(r.line) <= ON_LINE_M}
                  for n in ends]
            assert all(len(o) == 1 for o in on) and on[0] != on[1]  # two different rings
            assert all(n.kind is NodeKind.JUNCTION for n in ends)
            assert link.ground.difference(ev.land.roadable).area < 0.5
            assert link.ground.intersection(ev.hulls).area < 0.5
        blocks = [p.footprint for p in laid.placements]
        assert any(_mostly_in(f, WEST) for f in blocks) and any(_mostly_in(f, EAST) for f in blocks)


def test_the_strictest_profile_lays_out_two_wings_only_with_two_clusters():
    """Under ALL-ALL no road may run in the setback, the neck holds no cluster, and one cluster's
    ramp had no road beside it: nothing was proposed. With a cluster in each wing there is."""
    proposal, _ = _search()
    strict = [c for c in proposal.candidates if "-ALL-ALL-" in c.candidate_id]
    assert strict
    for candidate in strict:
        loops = [r for r in candidate.circulation.roads if r.kind is RoadKind.LOOP]
        links = [r for r in candidate.circulation.roads if r.id.startswith("link-")]
        assert len(loops) == 2 and len(links) == 1, candidate.candidate_id


def test_further_clusters_keep_clear_of_those_laid():
    _, laid_out = _search()
    for ev, laid in laid_out:
        for i, a in enumerate(ev.clusters):
            for b in ev.clusters[i + 1:]:
                assert a.hull.distance(b.hull) >= ev.street_m - 1e-6
                assert a.ring.intersection(b.hull).area < 0.5
                assert b.ring.intersection(a.hull).area < 0.5
        for i, p in enumerate(laid.placements):
            for q in laid.placements[i + 1:]:
                need = max(p.standing.choice.cls.gap_m, q.standing.choice.cls.gap_m)
                assert p.footprint.distance(q.footprint) >= need - 1e-6


def test_the_link_runs_through_the_neck_where_the_nearest_points_would_leave_the_ground():
    """Two rings face each other along their whole sides; the nearest pair of their centre lines
    may lie anywhere along them, but only the neck has ground between them."""
    west, east = box(20, 20, 90, 100), box(200, 20, 270, 100)
    laid = network.Cluster(west, Road("ring", RoadKind.LOOP, network.ring_centre(west, 9.0), 9.0))
    further = network.Cluster(east, Road("ring-2", RoadKind.LOOP,
                                         network.ring_centre(east, 9.0), 9.0))
    road = network.link(further, [laid], DOG_BONE, 9.0, 1)
    assert road is not None
    assert road.ground.difference(DOG_BONE).area < 0.5
    assert all(30 + 4.5 - 1e-6 <= y <= 90 - 4.5 + 1e-6 for _, y in road.line.coords)
    assert road.line.length == 200 - 9.0 / 2 - (90 + 9.0 / 2)  # straight across, side to side


def test_no_link_is_laid_across_ground_a_road_may_not_take():
    west, east = box(20, 20, 90, 100), box(200, 20, 270, 100)
    laid = network.Cluster(west, Road("ring", RoadKind.LOOP, network.ring_centre(west, 9.0), 9.0))
    further = network.Cluster(east, Road("ring-2", RoadKind.LOOP,
                                         network.ring_centre(east, 9.0), 9.0))
    assert network.link(further, [laid], unary_union([WEST, EAST]), 9.0, 1) is None


def test_a_plot_whose_first_cluster_takes_all_the_ground_says_no_further_cluster_stands():
    made = rectangle()
    found = profiles(made.rules, made.brief, list(made.kit))
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)
    profile = next(p for p in found if p.key == "ALL-ALL")
    ev = evaluate(run, Config(profile, 0.0, 0.0, 8, more_clusters=True))
    assert isinstance(ev, Failure)
    assert ev.reason == "no further cluster stands on the ground the first leaves"
    single = evaluate(run, Config(profile, 0.0, 0.0, 8))
    assert not isinstance(single, Failure) and len(single.clusters) == 1 and not single.links


def test_a_link_never_crosses_a_cluster():
    """From the far side of the further ring the line to the laid ring would cross the further
    cluster: the link found is the short one between the facing sides, clear of both."""
    west, east = box(20, 20, 90, 100), box(200, 20, 270, 100)
    laid = network.Cluster(west, Road("ring", RoadKind.LOOP, network.ring_centre(west, 9.0), 9.0))
    further = network.Cluster(east, Road("ring-2", RoadKind.LOOP,
                                         network.ring_centre(east, 9.0), 9.0))
    road = network.link(further, [laid], box(-50, -50, 350, 170), 9.0, 1)
    assert road is not None
    assert road.ground.intersection(unary_union([west, east])).area < 0.5
    assert LineString(road.line).length <= 200 - 9.0 - 90 + 1e-6
