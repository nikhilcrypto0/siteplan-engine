"""No tot-lot in front of the gate (the architect, 2026-10-11; the full search since 2026-10-12):
the stretch of the plot line the gate opens, swept straight in across the plot, is kept from the
open space's pockets. Made-up land."""

TEST_CLASS = "normative"

import pytest  # noqa: E402
from contract_fixtures.build import L_PLOT  # noqa: E402
from search_support import l_plot, proposal_on_the_l_plot, rectangle, strategy  # noqa: E402
from shapely import affinity  # noqa: E402
from shapely.geometry import box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from siteplan.contracts.candidate import RoadKind  # noqa: E402
from siteplan.optimizer.search.layout import gate_way_in  # noqa: E402
from siteplan.validator.validate import validate  # noqa: E402

TOUCH_M = 0.01  # a road this near the gate meets it


def test_the_way_in_is_the_gates_width_straight_across_the_plot():
    net = box(0, 0, 200, 120)
    gate = box(90, -0.5, 99, 2.0)  # opening 9 m of the south side
    way = gate_way_in(net, gate)
    assert way.bounds == pytest.approx((90, 0, 99, 120), abs=0.02)
    assert way.area == pytest.approx(9 * 120, rel=0.01)


def test_no_pocket_of_the_searchs_open_space_stands_in_front_of_the_gate():
    proposal = strategy().propose(rectangle().context())
    net = rectangle().site.net_plot.value.to_shapely()
    for c in proposal.candidates:
        way = unary_union([gate_way_in(net, g.shape.to_shapely()) for g in c.circulation.gates])
        pockets = unary_union([s.to_shapely() for s in c.program.open_space])
        assert pockets.intersection(way).area < 1e-6, c.candidate_id


def test_the_way_in_runs_square_to_a_slanted_side():
    net = affinity.rotate(box(0, 0, 200, 120), 30, origin=(0, 0))
    gate = affinity.rotate(box(90, -0.5, 99, 2.0), 30, origin=(0, 0))
    wanted = affinity.rotate(box(90, 0, 99, 120), 30, origin=(0, 0))
    way = gate_way_in(net, gate)
    # the gate's opening is found 0.01 m beyond its edges: 0.02 m more along the 120 m
    assert way.symmetric_difference(wanted).area < 0.03 * 120
    assert way.area == pytest.approx(9 * 120, rel=0.01)


def test_the_way_in_stops_at_the_plot_line():
    up_the_arm = gate_way_in(L_PLOT, box(5, -0.5, 14, 2.0))
    assert up_the_arm.bounds == pytest.approx((5, 0, 14, 160), abs=0.02)
    beside_the_arm = gate_way_in(L_PLOT, box(100, -0.5, 109, 2.0))
    assert beside_the_arm.bounds == pytest.approx((100, 0, 109, 100), abs=0.02)


@pytest.mark.parametrize("slim", [False, True], ids=["l_plot", "l_plot_slim"])
def test_on_the_l_plot_the_gate_is_reached_kept_clear_and_no_layout_fails_the_law(slim):
    """Both made-up L-plots (2026-10-13): one gate, the approach road starting at it, its way in
    across the plot and no pocket of the open space in it; the independent validator finds no
    legal FAIL in any proposal."""
    made = l_plot(slim)
    net = made.site.net_plot.value.to_shapely()
    proposal = proposal_on_the_l_plot(slim)
    assert proposal.candidates
    for c in proposal.candidates:
        [gate] = c.circulation.gates
        opening = gate.shape.to_shapely()
        approach = unary_union([s.to_shapely() for r in c.circulation.roads
                                if r.kind is RoadKind.APPROACH for s in r.shapes])
        assert approach.distance(opening) <= TOUCH_M, c.candidate_id
        way = gate_way_in(net, opening)
        pockets = unary_union([s.to_shapely() for s in c.program.open_space])
        assert way.area > 0 and pockets.intersection(way).area < 1e-6, c.candidate_id
        report = validate(made.site, made.rules, made.brief, c, made.envelope)
        assert not [i.finding.rule for i in report.legal
                    if i.finding.status.value == "FAIL"], c.candidate_id
