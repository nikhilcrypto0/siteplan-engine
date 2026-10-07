"""Where one road joins another the fire tender turns too (C4-15): the validator sweeps every
junction of the fire roads (the approach, a street or a link meeting the loop) as it sweeps the
loop road's bends, and the generator keeps its program and its approach clear of them. A corner on
the plot's boundary (the gate, where the tender turns on the street outside) and the tip of a slit
the drawing leaves are no junction. Made-up land only."""

from __future__ import annotations

import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from validator_helpers import check, fixture, rectangle

from siteplan.contracts.candidate import PlacedAmenity, RoadKind
from siteplan.contracts.common import Status
from siteplan.optimizer.search import network, turns
from siteplan.validator import context
from siteplan.validator import turning as validator_turning
from siteplan.validator.fire import GATE_TOUCH_M, JUNCTION_ROADS
from siteplan.validator.readings import OUTER_EDGE
from siteplan.validator.shapes import EPS_M, union_of_all

TEST_CLASS = "normative"
RULE = "Fire access: turns at the road junctions"


def _junctions(inputs):
    ctx = context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)
    loop = union_of_all([r.shape for r in ctx.drawn.roads_of(RoadKind.LOOP,
                                                              RoadKind.PERIMETER_LANE)])
    roads = union_of_all([r.shape for r in ctx.drawn.roads_of(*JUNCTION_ROADS)])
    return validator_turning.junction_turns(
        roads, loop, ctx.net.boundary, validator_turning.turning_for(inputs.rules, OUTER_EDGE),
        EPS_M, GATE_TOUCH_M)


def test_the_turns_where_a_street_joins_the_loop_are_swept_and_no_other():
    """The made-up rectangle: a loop road, an approach from the south gate running straight into
    its south-west corner, and one street across it. Two turns at each end of the street; none at
    the loop's own bends (the loop check's), none at the gate, and none where the approach's sides
    step a metre off the loop's (a jog no tender drives along)."""
    found = _junctions(fixture("rectangle"))
    assert len(found) == 4
    assert all(50.0 < s.centroid.y < 66.0 for s in found)  # the street runs at y 53.9 to 62.9


def test_something_standing_in_a_junction_turn_fails_and_a_clear_junction_passes():
    """A kiosk on the loop road where the street's west end joins it, far from every bend of the
    loop: the loop's own turns stay clear (that check passes as before), but the tender turning
    out of the street onto the loop sweeps it."""
    def kiosk(candidate):
        candidate.program.amenities.append(
            PlacedAmenity(name="KIOSK", shape=rectangle(8.4, 60.0, 9.9, 61.5)))
    assert check(fixture("rectangle").report(), RULE).finding.status is Status.PASS
    report = fixture("rectangle").edited(kiosk).report()
    assert check(report, "Fire access: turns along the loop road").finding.status is Status.PASS
    blocked = check(report, RULE)
    assert blocked.finding.status is Status.FAIL
    assert "an amenity" in blocked.finding.measured


@pytest.mark.parametrize("sweep", ["validator", "generator"])
def test_the_tip_of_a_slit_the_drawing_leaves_is_no_junction(sweep):
    """A road ringing land whose ring doubles back on itself (a slit 15 m into it, longer than a
    lane is wide, so no jog): the slit's tip turns 180 degrees, where no tender turns, and is
    swept by neither side."""
    hole = [(10, 10), (40, 10), (40, 40), (25, 40), (25, 25), (25, 40), (10, 40)]
    road = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)], [hole])
    loop = box(0, 0, 50, 50).difference(box(10, 10, 40, 40))
    far = box(-100, -100, 200, 200).boundary
    if sweep == "validator":
        found = validator_turning.junction_turns(
            road, loop, far, validator_turning.Turning(OUTER_EDGE, 6.0, 3.0, 9.0), 0.01, 0.5)
    else:
        found = turns.junction_turns(road, loop, far, [turns.Turning(3.0, 9.0)], 0.01, 0.5,
                                     6.0)[0]
    assert not any(s.contains(Point(25, 19)) for s in found)  # 6 m past the tip, in the land


def test_the_approach_planner_passes_over_a_gate_whose_turn_into_the_ring_a_block_stands_in():
    """The shortest approach on the rectangle, and a block standing where its tender turns into
    the ring: the planner takes the next gate, whose turn is clear."""
    from test_search_network import _run

    made, found, run = _run()
    from siteplan.optimizer.search.layout import Config, evaluate, land_strip

    profile = next(p for p in found if p.key == "ALL-ALL")
    ev = evaluate(run, Config(profile, 0.0, 0.0, 8))
    turnings = [turns.Turning(*t) for t in run.q.turnings]
    args = (run.plot, ev.clusters, unary_union([]), run.q.approach_m,
            land_strip(ev.land, run.q), turnings)
    first, _ = network.find_entrance(*args)
    corner = turns.junction_turns(unary_union([ev.clusters[0].ring, first.approach]),
                                  ev.clusters[0].ring, run.plot.net.boundary, turnings,
                                  network.EPS_M, network.TOUCH_M, run.q.lane_m)[0][0]
    block = corner.buffer(-0.5) if not corner.buffer(-0.5).is_empty else corner
    moved, why = network.find_entrance(*args, block)
    assert moved is not None, why
    assert moved.at != first.at
    again = turns.junction_turns(unary_union([ev.clusters[0].ring, moved.approach]),
                                 ev.clusters[0].ring, run.plot.net.boundary, turnings,
                                 network.EPS_M, network.TOUCH_M, run.q.lane_m)
    assert all(s.intersection(block).area <= network.RING_CLIP_SQM for s in again[0])
