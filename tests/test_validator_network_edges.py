"""The edges of the road topology and of the refusals: roads that only kiss at a corner, a loop that
runs from one gate to another, a count exactly at the limit, how many offending numbers a report
names. Survivors of an automatic mutation run over the two modules added in the review round."""

import pytest
from shapely.geometry import box
from shapely.ops import unary_union
from validator_helpers import fixture, rectangle, shapes, status

from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Status
from siteplan.validator.network import junctions
from siteplan.validator.refusals import MAX_COUNT, SHOWN, non_finite

TEST_CLASS = "normative"
Z = Status
REACH = 4.5


def test_roads_that_meet_along_a_side_have_a_junction_and_roads_that_kiss_at_a_corner_do_not():
    road = box(0.0, 0.0, 10.0, 10.0)
    beside = box(10.2, 0.0, 20.0, 10.0)  # 3 m² inside the touch distance: they meet
    corner = box(10.4, 10.4, 20.0, 20.0)  # 0.01 m² inside it: they touch at a corner
    assert len(junctions(road, beside, REACH)) == 1
    assert junctions(road, corner, REACH) == []


def test_two_contacts_nearer_together_than_a_road_is_wide_are_one_junction():
    road = box(0.0, 0.0, 10.0, 30.0)
    partners = box(10.2, 0.0, 20.0, 4.0).union(box(10.2, 8.0, 20.0, 12.0))  # 4 m apart
    assert len(junctions(road, partners, REACH)) == 1
    far = box(10.2, 0.0, 20.0, 4.0).union(box(10.2, 20.0, 20.0, 24.0))  # 16 m apart
    assert len(junctions(road, far, REACH)) == 2


def test_a_loop_that_runs_from_one_gate_to_another_need_not_close():
    """A U of road from a gate on the south side round the north and back to a second gate."""
    def through_route(candidate):
        loop = next(r for r in candidate.circulation.roads if r.id == "road-1")
        loop.shapes = shapes(unary_union([
            box(2.0, 2.0, 11.0, 98.0), box(2.0, 89.0, 148.0, 98.0), box(139.0, 2.0, 148.0, 98.0),
            box(2.0, 2.0, 12.0, 11.0), box(136.0, 2.0, 148.0, 11.0)]))
        second = candidate.circulation.gates[0].model_copy(
            update={"shape": rectangle(136.0, 0.0, 145.0, 2.0)})
        candidate.circulation.gates = [*candidate.circulation.gates, second]
    inputs = fixture("rectangle").edited(through_route)
    assert status(inputs.report(), "Internal roads: dead ends") is Z.PASS


def test_with_no_road_to_join_nothing_is_said_of_a_road_joined_to_the_entrance():
    def only_driveways(candidate):
        road = next(r for r in candidate.circulation.roads if r.id == "road-2")
        road.kind = RoadKind.DRIVEWAY
        candidate.circulation.roads = [road]
    names = {c.finding.rule for c in fixture("rectangle").edited(only_driveways).report().legal}
    assert "Internal roads: joined to the entrance" not in names


# --- the refusals --------------------------------------------------------------------------------


def test_a_whole_number_is_a_count_up_to_a_quadrillion_and_no_more():
    assert non_finite({"floors": MAX_COUNT}) == []
    assert non_finite({"floors": MAX_COUNT + 1})
    assert non_finite({"floors": -MAX_COUNT - 1})


def test_a_report_names_a_few_offending_numbers_and_says_how_many_more():
    bad = {f"x{i}": float("nan") for i in range(SHOWN + 2)}
    found = non_finite(bad)
    assert len(found) == SHOWN + 2

    def spoil(candidate):
        for i, tower in enumerate(candidate.towers):
            tower.x = float("nan")
            tower.y = float("inf") if i else tower.y
        candidate.metrics.saleable_sqft = float("-inf")
        candidate.metrics.mix_error = float("nan")
        candidate.metrics.open_space_sqm = float("nan")
        candidate.metrics.built_up_sqft = float("nan")
    report = fixture("rectangle").edited(spoil).report()
    assert "more" in report.legal[0].finding.measured
    assert report.legal[0].finding.measured.count(";") == SHOWN - 1


@pytest.mark.parametrize("sqm_per_car", [0.0, -20.0])
def test_a_car_that_takes_no_floor_is_a_rule_nothing_can_be_measured_with(sqm_per_car):
    def spoil(rules):
        rules.parking.measurement.sqm_per_car = sqm_per_car
    report = fixture("rectangle").with_rules(spoil).report()
    assert status(report, "Rules the validator can use") is Z.UNVERIFIED
