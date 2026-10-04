"""Candidates a review drew to stop the validator or to hide a FAIL: a hole of two points that the
contract admits, a stated footprint with no area, metrics that are not what they should be, a
count too large to be a count, and a layout drawn in millimetres on a site in metres. Each gets a
report, and none costs a verdict the layout had earned."""

import time

import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon, box
from validator_helpers import check, fixture, move_tower, shape, status

from siteplan.contracts import ValidationReport
from siteplan.contracts.candidate import Cellars
from siteplan.contracts.common import Shape, Status
from siteplan.contracts.validation import LegalVerdict

TEST_CLASS = "normative"
Z = Status
SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _a_hole_of_two_points():
    """Since contracts 1.1 a hole needs three points and the contract refuses one of two
    (test_the_contract_refuses_a_hole_of_two_points). The validator still defends itself against
    such a shape put together without the contract's check, which is what this builds."""
    return Shape.model_construct(outer=SQUARE, holes=[[(1.0, 1.0), (2.0, 2.0)]])


def test_the_contract_refuses_a_hole_of_two_points():
    with pytest.raises(ValidationError, match="three points"):
        Shape(outer=SQUARE, holes=[[(1.0, 1.0), (2.0, 2.0)]])


def test_a_hole_too_short_to_be_a_ring_is_dropped_named_and_blocks_a_pass():
    holed = _a_hole_of_two_points()
    places = {
        "a road": lambda c: setattr(c.circulation.roads[0], "shapes", [holed]),
        "a gate": lambda c: setattr(c.circulation.gates[0], "shape", holed),
        "a ramp": lambda c: setattr(c.program, "ramps", [holed]),
        "a parking bay": lambda c: setattr(c.program, "bays", [holed]),
        "the club house": lambda c: setattr(c.program.club_house, "shape", holed),
        "the footprint it states": lambda c: setattr(c.towers[0], "footprint", holed),
        "its prototype's footprint": lambda c: setattr(c.prototypes_used[0], "footprint", holed),
    }
    for where, edit in places.items():
        report = fixture("rectangle").edited(edit).report()
        found = [d for d in report.cross_checks if d.item == "malformed shape"]
        assert found and found[0].blocks_pass, where
        assert "a hole too short to be a ring was dropped" in found[0].theirs, where
        assert ValidationReport.model_validate_json(report.model_dump_json()) == report, where


def test_a_net_plot_with_a_hole_too_short_to_be_a_ring_is_refused():
    def spoil(site):
        site.net_plot.value = _a_hole_of_two_points()
    report = fixture("rectangle").with_site(spoil).report()
    assert [c.finding.status for c in report.legal] == [Z.UNVERIFIED]
    assert report.verdict.legal is LegalVerdict.UNVERIFIED


def test_a_stated_footprint_with_no_area_does_not_hide_the_fail_it_was_stated_for():
    """Asked for the centre of a footprint with no area the geometry library raised, and the one
    UNVERIFIED line that replaced the report had lost the tower's setback FAIL."""
    def tower_at_the_boundary(candidate):
        move_tower(candidate, "T1", 0.0, 60.0)
        candidate.towers[0].footprint = shape(Polygon([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]))
    report = fixture("rectangle").edited(tower_at_the_boundary).report()
    assert status(report, "All-round setback: T1") is Z.FAIL
    assert report.verdict.legal is LegalVerdict.FAIL
    assert any(d.item == "footprint T1" and d.blocks_pass for d in report.cross_checks)


def test_metrics_that_are_not_numbers_are_not_read_as_cars():
    for extra in ({"parking": 3}, {"parking": {"cars": "many"}}, {"parking": {"cars": {"a": "x"}}},
                  {"parking": {"cars": [1, 2]}}, {"parking": None}):
        def spoil(candidate, extra=extra):
            candidate.metrics.extra = extra
        report = fixture("rectangle").edited(spoil).report()
        assert not [d for d in report.cross_checks if d.item == "cars that fit"], extra


def test_a_whole_number_too_large_to_count_anything_is_not_a_candidate():
    def absurd(candidate):
        candidate.towers[0].floors_above_stilt = 10**400
    report = fixture("rectangle").edited(absurd).report()
    assert [c.finding.status for c in report.legal] == [Z.FAIL]
    assert "towers[0].floors_above_stilt = a whole number of" in report.legal[0].finding.measured


def test_a_layout_drawn_in_millimetres_on_a_site_in_metres_is_refused_quickly():
    """A cellar a thousand times too big used to be laid out with cars, and never finished."""
    def millimetres(candidate):
        candidate.program.cellars = Cellars(
            levels=1, outline=[shape(box(0.0, 0.0, 145_000.0, 95_000.0))])
    start = time.monotonic()
    report = fixture("rectangle").edited(millimetres).report()
    assert time.monotonic() - start < 10.0
    c = check(report, "Scale of the drawing")
    assert c.finding.status is Z.FAIL and "reaches 145,000 m" in c.finding.measured
    assert report.verdict.legal is LegalVerdict.FAIL
    assert status(fixture("rectangle").report(), "All-round setback: T1") is Z.PASS  # the control
