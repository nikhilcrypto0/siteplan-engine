"""The roads are drawn from the blocks that stand, never laid down before them (stream C2).

A street lies in the corridor between two neighbouring columns, the ring road runs round the cluster
the blocks and streets make, the approach runs in from the gate, and the fire lanes are what of the
6 m round each block no road covers. These tests hold the drawing to what rule 8(m) and NBC ask, and
to the claim that none of it is fixed before the blocks: change the blocks and the roads change.
"""

import ast
from functools import cache
from pathlib import Path

from search_support import made_up, rectangle
from shapely.geometry import Polygon
from shapely.ops import unary_union

from siteplan.optimizer.search import network
from siteplan.optimizer.search.land import erode, grow, polygons
from siteplan.optimizer.search.layout import Config, Failure, evaluate, lay_out, make_run
from siteplan.optimizer.search.readings import profiles

TEST_CLASS = "normative"
SRC = Path(__file__).parent.parent / "src" / "siteplan" / "optimizer" / "search"


@cache
def _run():
    made = rectangle()
    found = profiles(made.rules, made.brief, list(made.kit))
    return made, found, make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)


@cache
def _laid(profile_key="ALL-ALL", angle=0.0, offset=0.0, floors=8, reserve=None):
    made, found, run = _run()
    profile = next(p for p in found if p.key == profile_key)
    ev = evaluate(run, Config(profile, angle, offset, floors, reserve))
    assert not isinstance(ev, Failure), getattr(ev, "reason", "")
    laid, why = lay_out(run, ev)
    assert laid is not None, why
    return run, ev, laid


def _roads(laid):
    return unary_union([laid.ring, *laid.streets, laid.entrance.approach])


def test_every_block_opens_onto_a_road():
    _, _, laid = _laid()
    assert len(laid.placements) >= 4
    roads = _roads(laid)
    for p in laid.placements:
        assert p.footprint.distance(roads) <= 0.5, p.name


def test_the_ring_road_closes_round_the_blocks_and_every_street_ends_on_it():
    _, ev, laid = _laid()
    rings = [p for p in polygons(laid.ring) if p.interiors]
    assert len(rings) == 1  # a closed road: ground in the middle
    inside = Polygon(rings[0].interiors[0])
    for p in laid.placements:
        assert inside.buffer(0.01).contains(p.footprint)
    assert laid.streets
    for street in laid.streets:
        touching = polygons(street.buffer(0.5).intersection(laid.ring), 1.0)
        assert len(touching) >= 2, "a street that meets the ring at one end is a dead end"


def test_the_ring_road_is_the_band_of_a_road_round_the_blocks_and_the_streets():
    run, _, laid = _laid()
    hull = unary_union([*(p.footprint for p in laid.placements), *laid.streets]).convex_hull
    wanted = grow(hull, run.q.road_m).difference(hull)
    assert abs(laid.ring.area - wanted.area) < 1.0
    assert laid.ring.symmetric_difference(wanted).area < 5.0


def test_change_the_blocks_and_the_roads_change_with_them():
    """Nothing is fixed first: with the second column taken away, the cluster, the ring and the
    streets are drawn again from the blocks that are left: no street, a smaller ring, and every
    block that is left still on a road."""
    run, ev, laid = _laid()
    assert ev.streets and {s.column for s in ev.standing} == {0, 1}
    fewer = [s for s in ev.standing if s.column == 0]
    standing, streets, cluster, why = network.fit_cluster(
        fewer, ev.frame, ev.street_m, ev.land, run.q.road_m, run.q.legal_road_m,
        [s.choice.value for s in fewer])
    assert cluster is not None, why
    assert len(standing) == len(fewer) < len(ev.standing)
    assert streets == []  # a street lies between two columns of blocks
    assert cluster.hull.area < ev.cluster.hull.area
    assert cluster.ring.symmetric_difference(ev.cluster.ring).area > 50.0
    roads = cluster.ring
    for s in standing:
        footprint = ev.frame.to_survey(Polygon([(s.x0, s.y0), (s.x1, s.y0), (s.x1, s.y1),
                                                (s.x0, s.y1)]))
        assert footprint.distance(roads) <= 0.5


def test_the_approach_runs_from_a_gate_on_the_access_side_to_the_ring_road():
    run, _, laid = _laid()
    gate, approach = laid.entrance.gate, laid.entrance.approach
    assert gate.distance(run.plot.net.boundary) <= 0.5  # the opening is in the boundary
    assert gate.centroid.y < 3.0  # on the south side, where the access road runs
    assert run.rules.fire.entrance_width_m.value <= laid.entrance.width_m <= (
        run.rules.circulation.approach_m.value[1])
    assert approach.is_empty or approach.distance(gate) <= 0.5
    assert approach.is_empty or approach.distance(laid.ring) <= 0.5
    assert gate.buffer(0.5).intersection(_roads(laid)).area > 1.0  # a road meets the gate


def test_circulation_stays_out_of_the_setback_in_the_profile_that_holds_under_every_reading():
    run, ev, laid = _laid("ALL-ALL")
    deepest = max(p.standing.choice.cls.setback_m for p in laid.placements)
    zone = run.plot.net.difference(erode(run.plot.net, deepest))
    circulation = unary_union([laid.ring, *laid.streets, laid.lanes])
    assert circulation.intersection(zone).area < 0.5


def test_the_other_profile_runs_the_ring_road_inside_the_setback():
    run, _, laid = _laid("ALL-allowed", floors=9, reserve="N")
    deepest = max(p.standing.choice.cls.setback_m for p in laid.placements)
    zone = run.plot.net.difference(erode(run.plot.net, deepest))
    assert laid.ring.intersection(zone).area > 100.0


def test_the_planted_strip_is_drawn_where_the_setback_reaches_9_m_and_broken_only_at_the_gate():
    run, _, laid = _laid("ALL-allowed", floors=9, reserve="N")
    assert max(p.standing.choice.cls.setback_m for p in laid.placements) >= 9.0
    assert not laid.strip.is_empty
    assert laid.strip.intersection(_roads(laid)).area < 0.5
    along_boundary = run.plot.net.difference(erode(run.plot.net, run.q.strip_width_m))
    missing = along_boundary.difference(unary_union([laid.strip, laid.entrance.gate]))
    assert missing.area < 0.01 * along_boundary.area


def test_the_ground_round_every_block_is_a_road_or_a_fire_lane():
    run, _, laid = _laid()
    motorable = unary_union([_roads(laid), laid.lanes])
    for p in laid.placements:
        band = grow(p.footprint, run.q.lane_m).difference(p.footprint)
        assert band.difference(motorable).area < 0.5, p.name


def test_the_blocks_keep_the_setback_of_their_own_height_and_the_gap_of_the_taller():
    run, _, laid = _laid()
    net = run.plot.net
    for p in laid.placements:
        assert net.boundary.distance(p.footprint) >= p.standing.choice.cls.setback_m
    for i, a in enumerate(laid.placements):
        for b in laid.placements[i + 1:]:
            need = max(a.standing.choice.cls.gap_m, b.standing.choice.cls.gap_m)
            assert a.footprint.distance(b.footprint) >= need - 1e-6


def test_the_open_space_the_club_house_and_the_ramp_stand_on_what_the_blocks_and_roads_leave():
    run, _, laid = _laid()
    reach = run.q.reach_m
    blocks = unary_union([p.footprint for p in laid.placements])
    clear = unary_union([grow(p.footprint, reach) for p in laid.placements])
    taken = unary_union([clear, _roads(laid), laid.lanes])
    assert sum(p.area for p in laid.pockets) >= run.q.open_space_sqm
    for pocket in laid.pockets:
        assert pocket.intersection(taken).area < 0.5
        assert pocket.area >= run.q.pocket_sqm
    assert laid.club is not None and laid.club.intersection(taken).area < 0.5
    for p in laid.placements:  # a club house keeps a Table IV gap from every block
        assert laid.club.distance(p.footprint) >= p.standing.choice.cls.gap_m - 1e-6
    assert laid.ramps
    for ramp in laid.ramps:
        assert ramp.distance(_roads(laid)) <= 0.5 and ramp.intersection(taken).area < 0.5
        assert ramp.intersection(blocks).is_empty


def test_a_plot_with_an_arm_has_its_blocks_trimmed_to_ground_the_ring_can_surround():
    arm = made_up(Polygon([(0, 0), (150, 0), (150, 100), (24, 100), (24, 160), (0, 160)]))
    found = profiles(arm.rules, arm.brief, list(arm.kit))
    run = make_run(arm.site, arm.rules, arm.brief, arm.envelope, arm.kit, found)
    trimmed = 0
    for angle in (0.0, 90.0):
        for offset in (0.0, 8.0, 16.0):
            ev = evaluate(run, Config(found[1], angle, offset, 9, None))
            if isinstance(ev, Failure):
                continue
            off = ev.cluster.hull.difference(ev.land.cluster_land.buffer(0.01)).area
            assert off <= network.RING_CLIP_SQM  # the hull stands wholly where the ring can go
            trimmed += 1
    assert trimmed >= 1


def test_the_search_never_imports_the_legacy_loop_road_or_frame():
    """Not boundary, then setback, then a fixed loop, then towers: nothing in the search calls the
    generator that does it (grounds.frame, access.loop_road, access.entrance)."""
    banned = {"siteplan.grounds", "siteplan.access", "siteplan.layout"}
    files = sorted(SRC.glob("*.py"))
    assert len(files) >= 8
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in banned, f"{path.name} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in banned, f"{path.name} imports {alias.name}"
