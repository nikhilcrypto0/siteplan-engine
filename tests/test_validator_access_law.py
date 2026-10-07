"""Access below the high-rise line (contracts 1.3), read on 2026-10-06 from the NBC 2016 page
images and brought in by G.O.168 rule 15(a)(i):

- NBC Part 3 4.6 is for "high rise buildings and special buildings"; Part 4 1.2(b)(6) makes a
  special building of one with two basements or more, or one of more than 500 m² (read as law);
- NBC's own high-rise line is 15 m (Part 4 2.38, the stilt included): open, nbc_fire_height;
- how much of a block must face a road for it to open onto one (rule 8(l), (m)): open,
  opens_onto_road;
- the pathway from a road to a building is no longer than 30 m (Part 3 4.3.2.2);
- a stilt counts as parking only where a car can drive in (the engine's reading).

Every limit changed here is MADE UP and says so; the cellars and pathways are drawn on the
made-up rectangle.
"""

from shapely.geometry import box
from shapely.ops import unary_union
from validator_helpers import (
    check,
    fixture,
    move_tower,
    rectangle,
    select,
    shape,
    shapes,
    status,
)
from validator_low_helpers import all_low, flat_block, with_low_bands

from siteplan.contracts.candidate import Cellars, PlacedAmenity, RoadKind, RoadPiece
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import NBC_FIRE_HEIGHT, OPENS_ONTO_ROAD
from siteplan.contracts.validation import Family
from siteplan.validator.context import build
from siteplan.validator.fire import MAYBE_SPECIAL_NOTE
from siteplan.validator.parking import measure_floors

TEST_CLASS = "normative"
Z = Status
SERVED = "Internal roads: every block served"
PATH_LENGTH = "Internal roads: pathway length (NBC 4.3.2.2)"
OBSTRUCTION = "Fire access: nothing parked or built on it"
UNDER_T1_600 = (20.0, 65.0, 50.0, 85.0)  # 600 m², under T1 only (T1 is 14.4-86.4 x 62.9-87)
UNDER_T1_400 = (20.0, 65.0, 40.0, 85.0)  # 400 m²
STRAIGHT = box(109.0, 43.84, 115.0, 53.85)  # from T3 (moved down 10 m) to the internal road
DOG_LEG = unary_union([box(100.0, 43.84, 106.0, 48.0), box(100.0, 45.0, 120.0, 51.0),
                       box(114.0, 45.0, 120.0, 53.85)])


def _low():
    """Every block 12 m, no stilt: below the state's 21 m and below NBC's own 15 m."""
    return with_low_bands(all_low(fixture("rectangle"), 4))


def _cellar(levels, *boxes):
    def edit(candidate):
        candidate.program.cellars = Cellars(levels=levels,
                                            outline=[rectangle(*b) for b in boxes])
    return edit


def _no_cellar(candidate):
    candidate.program.cellars = None


def _cabin_beside_t3(candidate):
    candidate.program.amenities.append(
        PlacedAmenity(name="SECURITY CABIN", shape=rectangle(134.5, 40.0, 137.0, 42.5)))


def _held(report):
    return {c.finding.rule for c in report.legal
            if c.family is Family.FIRE and c.finding.rule.startswith("Fire access: T")}


# --- NBC 4.6 for special buildings (law) --------------------------------------------------------


def test_a_block_over_a_cellar_of_more_than_500_m2_is_a_special_building_held_to_4_6():
    report = _low().edited(_cellar(1, UNDER_T1_600)).report()
    assert _held(report) == {"Fire access: T1"}  # T2 and T3 stand over no cellar
    c = check(report, "Fire access: T1")
    assert c.finding.status is Z.PASS
    assert "a cellar of 1 level, 600 m² a level: a special building" in c.finding.note


def test_a_block_over_one_cellar_level_of_500_m2_or_less_is_not_a_special_building():
    report = _low().edited(_cellar(1, UNDER_T1_400)).report()
    assert _held(report) == set()
    assert status(report, "Fire access") is Z.INFO


def test_a_block_over_two_cellar_levels_is_a_special_building_whatever_their_area():
    report = _low().edited(_cellar(2, UNDER_T1_400)).report()
    assert _held(report) == {"Fire access: T1"}
    assert "a cellar of 2 levels, 400 m² a level" in check(report, "Fire access: T1").finding.note


def test_a_cellar_drawn_without_its_outline_leaves_each_block_perhaps_special():
    """Which blocks stand over cellar levels drawn without an outline is not known: each block
    is judged as if held, and what fails only on that is UNVERIFIED, never FAIL."""
    report = _low().edited(lambda c: (_cellar(1)(c), _cabin_beside_t3(c))).report()
    assert _held(report) == {"Fire access: T1", "Fire access: T2", "Fire access: T3"}
    t3 = check(report, "Fire access: T3")
    assert t3.finding.status is Z.UNVERIFIED and MAYBE_SPECIAL_NOTE in t3.finding.note
    assert check(report, "Fire access: T1").finding.status is Z.PASS


# --- NBC's own 15 m line (an open reading) ------------------------------------------------------


def test_nbcs_own_15_m_line_holds_a_block_under_one_reading_only():
    at = flat_block(_low(), "T3", 5, 3.0).edited(_no_cellar).report()  # 15.0 m
    c = check(at, "Fire access: T3")
    assert c.by_reading[NBC_FIRE_HEIGHT] == {"state_line": Z.PASS, "nbc_line": Z.PASS}
    assert "at or above NBC's own 15 m line" in c.finding.note
    assert "2.38" in c.finding.clause
    under = flat_block(_low(), "T3", 5, 2.98).edited(_no_cellar).report()  # 14.9 m
    assert "Fire access: T3" not in _held(under)


def test_a_site_wide_fire_check_that_fails_only_where_a_reading_holds_a_block_is_unverified():
    """Something on a fire lane. Over the cellar the 15 m blocks are special buildings and it
    fails; over no cellar 4.6 holds them only under the nbc_line reading, so it is UNVERIFIED,
    with nothing asked under the state's line."""
    def obstruct(candidate):
        p = candidate.circulation.fire_hardstanding[-1].to_shapely().representative_point()
        candidate.program.amenities.append(PlacedAmenity(
            name="KIOSK", shape=rectangle(p.x - 1.0, p.y - 1.0, p.x + 1.0, p.y + 1.0)))
    fifteen = with_low_bands(all_low(fixture("rectangle")))
    assert status(fifteen.edited(obstruct).report(), OBSTRUCTION) is Z.FAIL
    bare = check(fifteen.edited(lambda c: (_no_cellar(c), obstruct(c))).report(), OBSTRUCTION)
    assert bare.finding.status is Z.UNVERIFIED
    assert bare.by_reading[NBC_FIRE_HEIGHT] == {"state_line": Z.PASS, "nbc_line": Z.FAIL}


# --- "Opens onto a road" (an open reading) ------------------------------------------------------


def _road_short_of_t3(candidate):
    """The internal road cut back so that it only meets T3's corner."""
    road = next(r for r in candidate.circulation.roads if r.kind is RoadKind.INTERNAL)
    road.shapes = [shape(road.shapes[0].to_shapely().intersection(box(0, 0, 92.5, 200)))]


def test_a_block_that_only_touches_a_road_at_a_corner_opens_onto_it_under_one_reading_only():
    c = check(fixture("rectangle").edited(_road_short_of_t3).report(), SERVED)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[OPENS_ONTO_ROAD] == {"touch": Z.PASS, "frontage": Z.FAIL}
    assert "frontage: not on a road: T3 (faces a road for 1.5 m)" in c.finding.measured
    assert OPENS_ONTO_ROAD in c.finding.note


def test_a_block_with_a_pathways_width_facing_a_road_opens_onto_it_under_both_readings():
    c = check(fixture("rectangle").report(), SERVED)
    assert c.finding.status is Z.PASS
    assert c.by_reading[OPENS_ONTO_ROAD] == {"touch": Z.PASS, "frontage": Z.PASS}


def test_with_the_frontage_reading_chosen_a_corner_touch_fails():
    inputs = fixture("rectangle").with_rules(lambda r: select(r, OPENS_ONTO_ROAD, "frontage"))
    assert status(inputs.edited(_road_short_of_t3).report(), SERVED) is Z.FAIL


# --- The pathway's length (NBC 4.3.2.2) ---------------------------------------------------------


def _pathway_served(path):
    """T3 at 12 m, 10 m below the internal road, reached by the pathway drawn."""
    def edit(candidate):
        move_tower(candidate, "T3", 0.0, -10.0)
        candidate.circulation.roads.append(RoadPiece(
            id="pathway-1", kind=RoadKind.PATHWAY, declared_width_m=6.0, shapes=shapes(path)))
    return _low().edited(edit)


def _max_length(metres):
    def edit(rules):
        circ = rules.circulation
        circ.pathway_max_length_m = circ.pathway_max_length_m.model_copy(update={
            "value": metres, "clause": "MADE-UP (test): not NBC 4.3.2.2's figure"})
    return edit


def test_a_straight_pathway_is_measured_along_itself():
    c = check(_pathway_served(STRAIGHT).report(), PATH_LENGTH)
    assert c.finding.status is Z.PASS and c.finding.measured == "T3 10.0 m"
    assert "4.3.2.2" in c.finding.clause and "15(a)(i)" in c.finding.clause


def test_a_pathway_longer_than_the_rules_allow_fails():
    c = check(_pathway_served(STRAIGHT).with_rules(_max_length(8.0)).report(), PATH_LENGTH)
    assert c.finding.status is Z.FAIL and c.finding.measured == "T3 at least 10.0 m"


def test_a_pathway_that_is_not_one_straight_run_is_bounded_and_unverified_in_between():
    inputs = _pathway_served(DOG_LEG)
    assert status(inputs.with_rules(_max_length(8.0)).report(), PATH_LENGTH) is Z.FAIL
    c = check(inputs.with_rules(_max_length(12.0)).report(), PATH_LENGTH)
    assert c.finding.status is Z.UNVERIFIED
    assert c.finding.measured.startswith("T3 between 10.0 and ")
    assert status(inputs.with_rules(_max_length(100.0)).report(), PATH_LENGTH) is Z.PASS


def test_a_layout_with_no_pathway_says_nothing_of_a_pathways_length():
    assert PATH_LENGTH not in {c.finding.rule for c in fixture("rectangle").report().legal}


# --- A stilt no car can drive into (the engine's reading) ---------------------------------------


def _strip_access(candidate):
    """No internal road and no fire lanes: T1 faces the loop road for 1.5 m, T3 nothing."""
    candidate.circulation.roads = [r for r in candidate.circulation.roads
                                   if r.kind is not RoadKind.INTERNAL]
    candidate.circulation.fire_hardstanding = []


def test_a_stilt_no_car_can_drive_into_is_not_counted_as_parking():
    base = fixture("rectangle")
    every = measure_floors(build(base.site, base.rules, base.brief, base.candidate))
    assert every.stilts_unreached == ()
    cut = base.edited(_strip_access)
    some = measure_floors(build(cut.site, cut.rules, cut.brief, cut.candidate))
    assert some.stilts_unreached == ("T1", "T3")
    assert 0 < some.stilt_sqm < every.stilt_sqm  # T2's stilt alone
    measured = check(cut.report(), "Parking (Table V)").finding.measured
    assert ("not counted, the stilt of T1, T3: no 4.5 m of it faces a road, fire lane or "
            "pathway") in measured
