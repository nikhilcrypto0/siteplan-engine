"""Floors from metres (C1): the law's heights in metres, the firm's floor heights, and every floor
count a tower may take, never only the most. Made-up land and the contract fixtures only."""

import pytest
from optimizer_support import fixture, intent, max_legal, module_prototype, rules_with_dead_end

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.design_brief import HeightMode
from siteplan.contracts.prototype import PrototypeHeights
from siteplan.contracts.resolved_rules import (
    STILT_IN_RULE_HEIGHT,
    Applicability,
    Eligibility,
    HeightMeasure,
    HighRiseEligibility,
)
from siteplan.optimizer.floors import (
    CEILING_M,
    STILT_COUNTED,
    STILT_NOT_COUNTED,
    assess_floor_count,
    assess_floors,
    feasible_floors,
    floors_by_reading,
)

TEST_CLASS = "normative"

# The made-up site: a 3.0 m stilt and 3.0 m floors (the brief's), a road that serves buildings up
# to 30 m of rule height, and NBC's 30 m physical-height limit for a road that ends at the plot.


def _counts(options) -> list[int]:
    return [option.floors for option in options]


def _physical(option):
    (check,) = option.checks_on(HeightMeasure.PHYSICAL_HEIGHT)
    return check


def test_a_30_m_limit_gives_nine_floors_when_the_stilt_counts_and_ten_when_it_does_not():
    site, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    counted = feasible_floors(rules, brief, None, STILT_COUNTED)
    not_counted = feasible_floors(rules, brief, None, STILT_NOT_COUNTED)
    assert max(_counts(counted)) == 9  # 3 m stilt + 9 x 3 m = 30 m
    assert max(_counts(not_counted)) == 10  # 10 x 3 m = 30 m
    assert counted[-1].rule_height_m == 30.0 and not_counted[-1].rule_height_m == 30.0
    assert counted[-1].physical_height_m == 30.0 and not_counted[-1].physical_height_m == 33.0


def test_every_feasible_count_is_returned_not_only_the_most():
    site, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    # Below 21 m the band's setback is not encoded (Table III), so those counts are not offered;
    # exactly 21 m (6 floors on the stilt, or 7 with the stilt left out) is a high-rise.
    assert _counts(feasible_floors(rules, brief, None, STILT_COUNTED)) == [6, 7, 8, 9]
    assert _counts(feasible_floors(rules, brief, None, STILT_NOT_COUNTED)) == [7, 8, 9, 10]
    by_reading = floors_by_reading(rules, brief, None)
    assert set(by_reading) == {STILT_COUNTED, STILT_NOT_COUNTED}
    assert _counts(by_reading[STILT_COUNTED]) == [6, 7, 8, 9]


def test_the_33_m_physical_height_is_unverified_while_the_dead_end_is_unknown():
    site, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    ten = next(o for o in assess_floors(rules, brief, None, STILT_NOT_COUNTED) if o.floors == 10)
    assert ten.physical_height_m == 33.0
    assert _physical(ten).status is Status.UNVERIFIED
    assert "not known" in _physical(ten).reason
    assert ten.feasible and ten in feasible_floors(rules, brief, None, STILT_NOT_COUNTED)
    assert ten.open_items  # said, not hidden


def test_the_33_m_physical_height_fails_when_the_road_ends_at_the_plot():
    site, rules = rules_with_dead_end(True)
    brief = max_legal(fixture()[2])
    ten = next(o for o in assess_floors(rules, brief, None, STILT_NOT_COUNTED) if o.floors == 10)
    assert _physical(ten).status is Status.FAIL
    assert not ten.feasible
    assert max(_counts(feasible_floors(rules, brief, None, STILT_NOT_COUNTED))) == 9


def test_a_road_that_runs_on_past_the_plot_does_not_bring_the_limit_in():
    site, rules = rules_with_dead_end(False)
    brief = max_legal(fixture()[2])
    ten = next(o for o in assess_floors(rules, brief, None, STILT_NOT_COUNTED)
               if o.floors == 10)
    assert _physical(ten).status is Status.INFO and "does not apply" in _physical(ten).reason
    assert max(_counts(feasible_floors(rules, brief, None, STILT_NOT_COUNTED))) == 10


@pytest.mark.parametrize(("ends", "applicability", "status", "offered"), [
    (None, Applicability.UNKNOWN, Status.UNVERIFIED, True),
    (True, Applicability.APPLIES, Status.FAIL, False),
    (False, Applicability.DOES_NOT_APPLY, Status.INFO, True)])
def test_the_site_answer_reaches_the_floors_through_the_rules_alone(
        ends, applicability, status, offered):
    """Whether the road ends at the plot is in the limit (its applicability): the optimizer reads
    the rules, never the site model, and the verdict is the contract's HeightLimit.evaluate."""
    _, rules = rules_with_dead_end(ends)
    (limit,) = [lim for lim in rules.height.limits if lim.measure is HeightMeasure.PHYSICAL_HEIGHT]
    assert limit.applicability is applicability
    ten = assess_floor_count(rules, max_legal(fixture()[2]), None, STILT_NOT_COUNTED, 10)
    assert _physical(ten).status is status is limit.evaluate(33.0)
    assert ten.feasible is offered


def test_the_first_count_a_limit_rules_out_is_kept_so_a_report_can_say_why():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    options = assess_floors(rules, brief, None, STILT_COUNTED)
    assert _counts(options) == list(range(1, 11))  # 10 floors: 33 m, over the road's 30 m
    last = options[-1]
    assert not last.feasible and last.status is Status.FAIL
    (road,) = last.checks_on(HeightMeasure.RULE_HEIGHT)
    assert road.status is Status.FAIL and "30 m" in road.reason
    assert all(o.feasible for o in options[:-1])


def test_each_option_names_its_band_its_setback_and_its_gap():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    by_floors = {o.floors: o for o in feasible_floors(rules, brief, None, STILT_COUNTED)}
    assert (by_floors[6].rule_height_m, by_floors[6].setback_m, by_floors[6].gap_m) == (21, 7, 7)
    assert (by_floors[6].band.above_m, by_floors[6].band.up_to_m) == (21, 21)  # its own band
    assert (by_floors[7].rule_height_m, by_floors[7].setback_m, by_floors[7].gap_m) == (24, 8, 8)
    assert (by_floors[8].setback_m, by_floors[9].setback_m) == (9, 10)
    assert (by_floors[9].band.above_m, by_floors[9].band.up_to_m) == (27, 30)
    # The stilt left out of the rule height moves the same tower into a lower band.
    other = {o.floors: o for o in feasible_floors(rules, brief, None, STILT_NOT_COUNTED)}
    assert other[9].rule_height_m == 27 and other[9].setback_m == 9


def test_a_count_below_the_high_rise_height_is_assessed_but_not_offered_yet():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    three = assess_floor_count(rules, brief, None, STILT_COUNTED, 3)  # 12 m: Table III
    assert three.feasible and not three.modelled and three.status is Status.UNVERIFIED
    assert three.setback_m is None
    assert 3 not in _counts(feasible_floors(rules, brief, None, STILT_COUNTED))


def test_a_limit_with_no_value_is_reported_and_never_passed():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    option = feasible_floors(rules, brief, None, STILT_COUNTED)[0]
    (airport,) = option.checks_on(HeightMeasure.AMSL)
    assert airport.limit_m is None and airport.status is Status.UNVERIFIED
    assert option.feasible  # an open item does not rule a height out


def test_a_prototypes_own_floor_height_replaces_the_firms():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    block = module_prototype(1)
    tall = block.model_copy(update={"heights": PrototypeHeights(floor_to_floor_m=3.3)})
    both = block.model_copy(update={"heights": PrototypeHeights(
        stilt_height_m=4.5, floor_to_floor_m=3.3)})
    assert max(_counts(feasible_floors(rules, brief, None, STILT_COUNTED))) == 9
    assert max(_counts(feasible_floors(rules, brief, tall, STILT_COUNTED))) == 8  # 3 + 8 x 3.3
    assert max(_counts(feasible_floors(rules, brief, both, STILT_COUNTED))) == 7  # 4.5 + 7 x 3.3
    top = feasible_floors(rules, brief, tall, STILT_COUNTED)[-1]
    assert (top.stilt_m, top.floor_to_floor_m) == (3.0, 3.3)  # the stilt still the brief's


def test_a_height_exactly_at_its_limit_meets_it():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    nine = assess_floor_count(rules, brief, None, STILT_COUNTED, 9)
    assert nine.rule_height_m == 30.0 and nine.feasible
    (road,) = nine.checks_on(HeightMeasure.RULE_HEIGHT)
    assert road.status is Status.PASS


def test_without_a_stilt_the_stilt_reading_cannot_matter():
    _, rules = rules_with_dead_end(None)
    brief = intent(max_legal(fixture()[2]), mode=HeightMode.MAX_LEGAL, has_stilt=False)
    counted = feasible_floors(rules, brief, None, STILT_COUNTED)
    not_counted = feasible_floors(rules, brief, None, STILT_NOT_COUNTED)
    assert _counts(counted) == _counts(not_counted) == [7, 8, 9, 10]  # 7 floors = 21 m
    assert counted[-1].physical_height_m == counted[-1].rule_height_m == 30.0


def test_the_briefs_intent_chooses_within_what_the_law_leaves_open():
    _, rules = rules_with_dead_end(None)
    base = fixture()[2]
    fixed = intent(base, mode=HeightMode.FIXED, floors_above_stilt=8)
    assert _counts(feasible_floors(rules, fixed, None, STILT_COUNTED)) == [8]
    too_tall = intent(base, mode=HeightMode.FIXED, floors_above_stilt=10)
    assert feasible_floors(rules, too_tall, None, STILT_COUNTED) == []  # the law says no
    ranged = intent(base, mode=HeightMode.RANGE, floors_range=(8, 12))
    assert _counts(feasible_floors(rules, ranged, None, STILT_COUNTED)) == [8, 9]
    at_least = intent(base, mode=HeightMode.MAX_LEGAL, min_floors_above_stilt=8)
    assert _counts(feasible_floors(rules, at_least, None, STILT_COUNTED)) == [8, 9]


def test_the_most_the_law_allows_is_a_set_of_counts_not_one():
    _, rules = rules_with_dead_end(None)
    options = feasible_floors(rules, max_legal(fixture()[2]), None, STILT_NOT_COUNTED)
    assert len(options) > 1


def test_a_limit_whose_own_status_is_unverified_still_holds_a_breach_back():
    """The road's width is a drawing value: the limit is the best we have. A count above it is
    not offered, and is labelled UNVERIFIED (the validator's word), not FAIL: the road the
    drawing shows settles nothing either way."""
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    limits = [limit.model_copy(update={"status": Provenance.UNVERIFIED})
              if limit.measure is HeightMeasure.RULE_HEIGHT else limit
              for limit in rules.height.limits]
    rules = rules.model_copy(update={"height": rules.height.model_copy(update={"limits": limits})})
    assert max(_counts(feasible_floors(rules, brief, None, STILT_COUNTED))) == 9
    over = assess_floor_count(rules, brief, None, STILT_COUNTED, 10)
    assert over.limits_status is Status.UNVERIFIED and not over.feasible
    within = assess_floor_count(rules, brief, None, STILT_COUNTED, 9)
    assert within.feasible and within.status is Status.UNVERIFIED  # never a PASS on it


def _eligibility(rules, road_met: bool | None):
    """The rules with the high-rise road ground met, not met or unsettled."""
    grounds = [g.model_copy(update={"met": road_met}) if g.id == "road_width" else g
               for g in rules.height.high_rise.grounds]
    high_rise = HighRiseEligibility(eligibility=HighRiseEligibility.of_grounds(grounds),
                                    grounds=grounds, note="made up")
    return rules.model_copy(update={"height": rules.height.model_copy(
        update={"high_rise": high_rise})})


def test_where_a_high_rise_is_prohibited_no_count_is_offered_and_nothing_lower_either():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    prohibited = _eligibility(rules, False)
    assert prohibited.height.high_rise.eligibility is Eligibility.PROHIBITED
    assert feasible_floors(prohibited, brief, None, STILT_COUNTED) == []
    six = assess_floor_count(prohibited, brief, None, STILT_COUNTED, 6)  # 21 m
    assert six.high_rise.status is Status.FAIL and not six.feasible
    assert "road_width" in six.high_rise.reason
    five = assess_floor_count(prohibited, brief, None, STILT_COUNTED, 5)  # 18 m: Table III
    assert five.high_rise is None and not five.modelled
    assert five.status is not Status.PASS  # a prohibited high-rise passes nothing lower


def test_an_unsettled_eligibility_offers_high_rise_counts_labelled_unverified():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    unsettled = _eligibility(rules, None)
    assert unsettled.height.high_rise.eligibility is Eligibility.UNVERIFIED
    offered = feasible_floors(unsettled, brief, None, STILT_COUNTED)
    assert _counts(offered) == [6, 7, 8, 9]
    assert all(o.high_rise.status is Status.UNVERIFIED and o.status is Status.UNVERIFIED
               for o in offered)


def test_where_no_limit_stops_the_count_a_search_ceiling_does():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    limits = [limit for limit in rules.height.limits
              if limit.measure is not HeightMeasure.RULE_HEIGHT]
    rules = rules.model_copy(update={"height": rules.height.model_copy(update={"limits": limits})})
    options = assess_floors(rules, brief, None, STILT_COUNTED)
    assert options[-1].physical_height_m >= CEILING_M > options[-2].physical_height_m


def test_a_small_plots_road_gives_a_lower_limit():
    site, rules = rules_with_dead_end(None, "small_plot")  # 12.19 m road: up to 24 m
    brief = max_legal(fixture("small_plot")[2])
    assert _counts(feasible_floors(rules, brief, None, STILT_COUNTED)) == [6, 7]


def test_a_reading_the_rules_do_not_have_is_refused():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    with pytest.raises(ValueError, match="unknown reading"):
        feasible_floors(rules, brief, None, "half_counted")
    assert rules.readings(STILT_IN_RULE_HEIGHT) == [STILT_COUNTED, STILT_NOT_COUNTED]


def test_heights_that_cannot_make_a_building_are_refused():
    _, rules = rules_with_dead_end(None)
    brief = max_legal(fixture()[2])
    flat = brief.firm_standards.floor_to_floor_m.model_copy(update={"value": 0.0})
    bad = brief.model_copy(update={"firm_standards": brief.firm_standards.model_copy(
        update={"floor_to_floor_m": flat})})
    with pytest.raises(ValueError, match="positive"):
        feasible_floors(rules, bad, None, STILT_COUNTED)
    with pytest.raises(ValueError, match="at least one floor"):
        assess_floor_count(rules, brief, None, STILT_COUNTED, 0)
