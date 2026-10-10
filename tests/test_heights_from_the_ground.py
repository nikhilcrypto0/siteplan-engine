"""A height starts at the ground, and the storeys start above it (2026-10-10).

Rule 2(e) and NBC Part 2 2.6 measure a height from the ground; NBC Part 3 12.1, which rule
15(a)(vi) brings to all buildings, raises the lowest floor above it: a parking stilt's floor
0.15 m (12.1.2, covered parking), any other lowest floor 0.45 m (12.1.1, the plinth). With the
stilt in a height the raise is in it; where the stilt is left out (rule 5(c), the not_counted
reading) the whole stilt floor is, its raise with it. The hand-built contract fixtures carry no
raise, as a contract stored before it does; `with_raise` gives them the one the resolver now
carries. Made-up land only.
"""

import pytest
from contract_fixtures import HERE, with_raise
from optimizer_support import fixture, intent, max_legal, module_prototype, rules_with_dead_end

from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import HeightMode
from siteplan.contracts.prototype import PrototypeHeights
from siteplan.contracts.resolved_rules import HeightMeasure
from siteplan.layout import LayoutRequest
from siteplan.optimizer.floors import (
    STILT_COUNTED,
    STILT_NOT_COUNTED,
    assess_floor_count,
    assess_floors,
    feasible_floors,
)
from siteplan.validator.measure import tower_geometries

TEST_CLASS = "normative"
MIX = {"2BHK": 0.7, "3BHK": 0.3}


def _raised(ends_at_plot=None):
    site, rules = rules_with_dead_end(ends_at_plot)
    return site, with_raise(rules)


def _counts(options) -> list[int]:
    return [option.floors for option in options]


def test_storeys_that_exactly_reach_a_limit_with_the_stilt_counted_are_over_it():
    """A 3 m stilt and nine 3 m floors are 30.15 m from the ground: over the road's 30 m."""
    _, rules = _raised()
    brief = max_legal(fixture()[2])
    nine = assess_floor_count(rules, brief, None, STILT_COUNTED, 9)
    assert nine.rule_height_m == pytest.approx(30.15) and not nine.feasible
    assert max(_counts(feasible_floors(rules, brief, None, STILT_COUNTED))) == 8


def test_left_out_the_stilt_floor_goes_with_its_raise():
    """Under not_counted ten 3 m floors are still 30 m of rule height; NBC's physical height,
    from the ground, is 33.15 m."""
    _, rules = _raised()
    brief = max_legal(fixture()[2])
    ten = assess_floor_count(rules, brief, None, STILT_NOT_COUNTED, 10)
    assert ten.rule_height_m == pytest.approx(30.0) and ten.feasible
    assert ten.physical_height_m == pytest.approx(33.15)
    assert max(_counts(feasible_floors(rules, brief, None, STILT_NOT_COUNTED))) == 10


def test_a_physical_height_over_30_m_on_a_dead_end_is_held_back_with_the_raise_in_it():
    _, rules = _raised(True)
    brief = max_legal(fixture()[2])
    nine = assess_floors(rules, brief, None, STILT_NOT_COUNTED)[-1]  # the scan stops here
    assert nine.floors == 9 and nine.physical_height_m == pytest.approx(30.15)
    (physical,) = nine.checks_on(HeightMeasure.PHYSICAL_HEIGHT)
    assert physical.status is Status.FAIL and not nine.feasible


def test_table_iii_is_read_with_the_stilt_floor_left_out_raise_and_all():
    """Rule 5(c): three floors on the stilt are 9 m for Table III, as before the raise."""
    _, rules = _raised()
    three = assess_floor_count(rules, max_legal(fixture()[2]), None, STILT_COUNTED, 3)
    assert three.below_high_rise and three.band.measure is HeightMeasure.HEIGHT_ABOVE_STILT
    assert three.band.contains(9.0) and three.rule_height_m == pytest.approx(12.15)


def test_a_stilt_a_raise_short_of_the_storey_lands_on_the_limit_again():
    """0.15 + 2.85 + 9 x 3 m = 30 m: exactly at the limit, which meets it; + 6 x 3 m = 21 m."""
    _, rules = _raised()
    brief = max_legal(fixture()[2])
    exact = module_prototype(1).model_copy(update={"heights": PrototypeHeights(
        stilt_height_m=2.85)})
    nine = assess_floor_count(rules, brief, exact, STILT_COUNTED, 9)
    assert nine.rule_height_m == pytest.approx(30.0) and nine.feasible
    six = assess_floor_count(rules, brief, exact, STILT_COUNTED, 6)
    assert (six.band.above_m, six.band.up_to_m) == (21, 21)


def test_a_block_with_no_stilt_stands_on_the_plinth_under_either_reading():
    _, rules = _raised()
    brief = intent(max_legal(fixture()[2]), mode=HeightMode.MAX_LEGAL, has_stilt=False)
    counted = feasible_floors(rules, brief, None, STILT_COUNTED)
    not_counted = feasible_floors(rules, brief, None, STILT_NOT_COUNTED)
    # 0.45 m plinth: 6 floors are 18.45 m (no setback is given 18-21 m); 10 are 30.45 m
    assert _counts(counted) == _counts(not_counted) == [1, 2, 3, 4, 5, 7, 8, 9]
    assert counted[-1].physical_height_m == counted[-1].rule_height_m == pytest.approx(27.45)


def test_rules_stored_without_a_raise_give_the_heights_they_gave():
    _, stored = rules_with_dead_end(None)
    nine = assess_floor_count(stored, max_legal(fixture()[2]), None, STILT_COUNTED, 9)
    assert nine.rule_height_m == pytest.approx(30.0) and nine.feasible


def test_the_validator_measures_the_same_heights_from_the_ground():
    """The validator's towers (validator.measure) take the raise as the optimizer does."""
    _, stored = rules_with_dead_end(None)
    rules = with_raise(stored)
    brief = fixture()[2]
    candidate = CandidateLayout.model_validate_json(
        (HERE / "rectangle" / "CandidateLayout.json").read_text())
    before = tower_geometries(candidate, brief, stored)
    after = tower_geometries(candidate, brief, rules)
    for old, new in zip(before, after, strict=True):
        assert new.physical_height_m == pytest.approx(old.physical_height_m + 0.15)
        assert new.rule_height_m("counted") == pytest.approx(old.rule_height_m("counted") + 0.15)
        assert new.rule_height_m("not_counted") == pytest.approx(old.rule_height_m("not_counted"))
        assert new.above_stilt_m == pytest.approx(old.above_stilt_m)


def test_the_legacy_request_measures_from_the_ground_too():
    counted = LayoutRequest(floors=9, unit_mix=MIX, stilt_in_rule_height=True)
    assert counted.height_m == pytest.approx(30.15) == counted.rule_height_m
    left_out = LayoutRequest(floors=10, unit_mix=MIX, stilt_in_rule_height=False)
    assert left_out.rule_height_m == pytest.approx(30.0)
    assert left_out.height_m == pytest.approx(33.15)
