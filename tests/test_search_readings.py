"""The readings a layout is built for, and the floor counts each leaves open (stream C2).

On a 60 ft road Table IV allows 30 m of rule height; with a 3.0 m stilt and 3.0 m floors that is 9
floors if the stilt counts and 10 if it does not, and a block is a high-rise from 21 m, which is 6
floors if the stilt counts and 7 if it does not. A layout built to hold under every reading may
only use a floor count both readings leave open.
"""

from search_support import made_up, rectangle
from shapely.geometry import box

from siteplan.contracts.design_brief import HeightIntent, HeightMode
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK, STILT_IN_RULE_HEIGHT
from siteplan.legal.resolve import resolve
from siteplan.optimizer.search.readings import ALL, Profile, floor_classes, profiles

TEST_CLASS = "normative"


def _floors(made, profile):
    return {c.floors for c in floor_classes(made.rules, made.brief, made.kit[0], profile)}


def test_a_floor_count_is_open_to_every_reading_only_where_each_reading_leaves_it_open():
    made = rectangle()
    counted = _floors(made, Profile("counted", ALL))
    not_counted = _floors(made, Profile("not_counted", ALL))
    every = _floors(made, Profile(ALL, ALL))
    assert counted == {6, 7, 8, 9}  # 21 m to 30 m with the stilt counted
    assert not_counted == {7, 8, 9, 10}  # 21 m to 30 m without it
    assert every == counted & not_counted == {7, 8, 9}


def test_a_profile_asks_the_stricter_setback_and_gap_of_its_readings():
    made = rectangle()
    by_floors = {c.floors: c for c in floor_classes(made.rules, made.brief, made.kit[0],
                                                    Profile(ALL, ALL))}
    # 8 floors is 24 m without the stilt (row 21-24, 8 m) and 27 m with it (row 24-27, 9 m):
    # the profile that holds under both keeps the 9 m
    assert (by_floors[8].setback_m, by_floors[8].gap_m) == (9.0, 9.0)
    assert (by_floors[9].setback_m, by_floors[9].gap_m) == (10.0, 10.0)
    assert by_floors[7].setback_m == 8.0  # 24 m with the stilt, 21 m without it
    only = {c.floors: c for c in floor_classes(made.rules, made.brief, made.kit[0],
                                               Profile("not_counted", ALL))}
    assert only[8].setback_m == 8.0 and only[10].setback_m == 10.0  # its own reading's rows


def test_the_profiles_are_every_reading_first_then_each_reading_that_adds_a_floor_count():
    made = rectangle()
    found = profiles(made.rules, made.brief, list(made.kit))
    assert [p.key for p in found] == ["ALL-ALL", "ALL-allowed", "not_counted-ALL",
                                      "not_counted-allowed"]
    # 'counted' leaves nothing open that every reading does not (9 floors at most); 'not_counted'
    # leaves a tenth floor
    assert found[0].basis() == {STILT_IN_RULE_HEIGHT: ALL, CIRCULATION_IN_SETBACK: ALL}
    assert found[3].roads_may_use_setback and not found[2].roads_may_use_setback


def test_a_reading_the_rules_have_settled_is_the_only_profile():
    made = rectangle()
    settled = resolve(made.site, selections={STILT_IN_RULE_HEIGHT: "counted",
                                             CIRCULATION_IN_SETBACK: "allowed"})
    found = profiles(settled, made.brief, list(made.kit))
    assert [p.key for p in found] == ["counted-allowed"]
    strict = resolve(made.site, selections={STILT_IN_RULE_HEIGHT: "not_counted",
                                            CIRCULATION_IN_SETBACK: "not_allowed"})
    assert [p.key for p in profiles(strict, made.brief, list(made.kit))] == ["not_counted-ALL"]


def test_the_brief_may_ask_for_one_floor_count_and_only_that_one_is_open():
    made = rectangle()
    fixed = made.brief.model_copy(update={"height_intent": HeightIntent(
        notation=made.brief.height_intent.notation, mode=HeightMode.FIXED, floors_above_stilt=8)})
    assert {c.floors for c in floor_classes(made.rules, fixed, made.kit[0],
                                            Profile(ALL, ALL))} == {8}
    ranged = made.brief.model_copy(update={"height_intent": HeightIntent(
        notation=made.brief.height_intent.notation, mode=HeightMode.RANGE,
        floors_range=(8, 9))})
    assert {c.floors for c in floor_classes(made.rules, ranged, made.kit[0],
                                            Profile(ALL, ALL))} == {8, 9}


def test_where_the_road_is_too_narrow_for_a_high_rise_no_floor_count_is_open():
    """A road under Table IV's 12 m cannot serve a high-rise, and that permits nothing lower: the
    blocks below 21 m are Table III's, which this strategy does not lay out."""
    narrow = made_up(box(0, 0, 200, 120), road_ft=30)
    assert _floors(narrow, Profile(ALL, ALL)) == set()
    assert profiles(narrow.rules, narrow.brief, list(narrow.kit))[0].key == "ALL-ALL"
