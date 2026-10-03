"""Planted violations: each one is made by editing a copy of a contract fixture's candidate, and
the validator must FAIL it. The untouched fixture is the control: it has nothing to FAIL.

Where a violation is a shortfall of the law, it is short of what every reading allows: a setback
0.3 m short of the stilt-not-counted setback is short under both readings of the stilt (one 0.3 m
short of the stilt-counted setback only is UNVERIFIED, see test_validator_blocks.py).
"""

import pytest
from validator_helpers import (
    check,
    fixture,
    footprint,
    move_tower,
    rectangle,
    select,
    set_floors,
    shape,
    status,
)

from siteplan.contracts.candidate import Cellars
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import LegalVerdict

TEST_CLASS = "normative"
Z = Status
WEAKEST_SETBACK_M = 8.0  # Table IV, 21-24 m: the stilt does not count in a 27 m tower
WEAKEST_GAP_M = 8.0


def _net(inputs):
    return inputs.site.net_plot.value.to_shapely()


def _north_setback_to(inputs, name: str, metres: float):
    """Move a tower north so that it stands `metres` from the net plot's boundary."""
    def plant(candidate):
        distance = _net(inputs).boundary.distance(footprint(candidate, name))
        move_tower(candidate, name, 0.0, distance - metres)
    return plant


def _gap_between(inputs, a: str, b: str, metres: float):
    def plant(candidate):
        now = footprint(candidate, a).distance(footprint(candidate, b))
        move_tower(candidate, a, 0.0, -(now - metres))
    return plant


def _narrow_road(candidate):
    road = next(r for r in candidate.circulation.roads if r.kind.value == "INTERNAL")
    road.shapes = [shape(r.to_shapely().buffer(-0.055, join_style="mitre")) for r in road.shapes]


def _bay_in_a_fire_band(candidate):
    candidate.program.bays.append(rectangle(134.0, 38.0, 136.5, 43.0))  # beside T3's east face


def _open_space_at_9_9_percent(candidate):
    others = sum(s.area_sqm for s in candidate.program.open_space[1:])
    target = 0.099 * 15_000.0  # of the net plot: below the share asked under every denominator
    width = (target - others) / (22.83 - 11.01)
    candidate.program.open_space[0] = rectangle(11.01, 11.01, 11.01 + width, 22.83)


def _no_cellars(candidate):
    candidate.program.cellars = Cellars(levels=0)


def _ramp_in_the_front_setback(candidate):
    candidate.program.ramps = [rectangle(20.0, 2.0, 25.4, 25.99)]  # the front is the south side


def _too_tall(candidate):
    set_floors(candidate, "T1", 12)  # 39 m with the stilt, 36 m without: over the road's band


PLANTS = {
    "setback 0.3 m short": (
        lambda i: i.edited(_north_setback_to(i, "T1", WEAKEST_SETBACK_M - 0.3)),
        ["All-round setback: T1"]),
    "gap between towers too short": (
        lambda i: i.edited(_gap_between(i, "T1", "T2", WEAKEST_GAP_M - 0.3)),
        ["Gap between blocks: T1 / T2"]),
    "an 8.9 m internal road": (
        lambda i: i.edited(_narrow_road), ["Internal roads: loop and other roads"]),
    "a parking bay inside a fire band": (
        lambda i: i.edited(_bay_in_a_fire_band),
        ["Fire access: T3", "Fire access: nothing parked or built on it",
         "Surface parking bays"]),
    "a tower above its band under both readings": (
        lambda i: i.edited(_too_tall),
        ["Abutting road width (for T1)", "Rule-height limit: the 18.29 m road serves buildings "
         "up to 30 m"]),
    "open space at 9.9%": (
        lambda i: i.edited(_open_space_at_9_9_percent), ["Organized open space (tot-lot)"]),
    "parking short": (lambda i: i.edited(_no_cellars), ["Parking (Table V)"]),
    "a ramp in the front setback": (
        lambda i: i.edited(_ramp_in_the_front_setback), ["Cellar ramp"]),
}


def test_the_untouched_fixture_has_nothing_to_fail():
    report = fixture("rectangle").report()
    assert report.verdict.legal is LegalVerdict.UNVERIFIED
    assert [c.finding.rule for c in report.legal if c.finding.status is Z.FAIL] == []


@pytest.mark.parametrize("name", list(PLANTS))
def test_each_planted_violation_fails(name):
    plant, expected = PLANTS[name]
    report = plant(fixture("rectangle")).report()
    for rule in expected:
        assert status(report, rule) is Z.FAIL, (name, rule)
    assert report.verdict.legal is LegalVerdict.FAIL


@pytest.mark.parametrize("name", ["setback 0.3 m short", "gap between towers too short",
                                  "a tower above its band under both readings"])
def test_the_height_dependent_plants_fail_under_every_reading_of_the_stilt(name):
    plant, expected = PLANTS[name]
    report = plant(fixture("rectangle")).report()
    for rule in expected:
        by_stilt = check(report, rule).by_reading[STILT_IN_RULE_HEIGHT]
        assert set(by_stilt.values()) == {Z.FAIL}, (rule, by_stilt)


def test_a_setback_short_of_the_stilt_counted_figure_only_is_not_a_fail():
    """0.3 m short of 9 m is 8.7 m: enough if the stilt does not count (8 m). Not settled."""
    inputs = fixture("rectangle")
    report = inputs.edited(_north_setback_to(inputs, "T1", 8.7)).report()
    assert status(report, "All-round setback: T1") is Z.UNVERIFIED


def test_the_same_setback_fails_when_the_rules_settle_on_the_stilt_counting():
    inputs = fixture("rectangle").with_rules(
        lambda r: select(r, STILT_IN_RULE_HEIGHT, "counted"))
    report = inputs.edited(_north_setback_to(inputs, "T1", 8.7)).report()
    assert status(report, "All-round setback: T1") is Z.FAIL
