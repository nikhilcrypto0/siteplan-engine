"""Parking: Table V on the recomputed built-up area, what the stilt, surface bays and cellars
provide, the cars that physically fit, the cellar setback and the ramp."""

import pytest
from shapely.geometry import box
from validator_helpers import (
    check,
    fixture,
    footprint,
    rectangle,
    select,
    set_floors,
    shape,
    status,
)

from siteplan.contracts.candidate import Cellars
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    ALL,
    STILT_IN_RULE_HEIGHT,
    VISITOR_PARKING,
    TableVColumn,
)
from siteplan.validator.readings import TABLE_V_COLUMN

TEST_CLASS = "normative"
Z = Status
TABLE_V = "Parking (Table V)"
RAMP = "Cellar ramp"


def _cellar(candidate, outline, levels=1):
    candidate.program.cellars = Cellars(levels=levels, outline=[shape(outline)])


# --- what Table V asks, and what is provided ------------------------------------------------


def test_built_up_is_recomputed_from_the_towers_and_the_club_house():
    inputs = fixture("rectangle")
    q = inputs.report().recomputed.quantities
    towers = sum(footprint(inputs.candidate, t.name).area * 8 for t in inputs.candidate.towers)
    club = inputs.candidate.program.club_house
    assert q["built_up_sqm"] == pytest.approx(towers + club.shape.area_sqm * club.floors, abs=0.1)
    assert q["parking_required_sqm[ELSEWHERE]"] == pytest.approx(0.2 * q["built_up_sqm"])


def test_the_stilt_is_the_footprint_less_its_cores():
    inputs = fixture("rectangle")
    t1 = inputs.candidate.prototype(inputs.candidate.towers[0].prototype_id)
    assert t1.cores >= 1
    q = inputs.report().recomputed.quantities
    cores = sum(z.shape.area_sqm for p in inputs.candidate.prototypes_used for z in p.core_zones)
    stilt = sum(footprint(inputs.candidate, t.name).area for t in inputs.candidate.towers)
    assert q["parking_stilt_sqm"] == pytest.approx(stilt - cores, abs=0.1)


def test_the_fixture_provides_what_table_v_asks_as_floor_and_as_cars():
    c = check(fixture("rectangle").report(), TABLE_V)
    assert c.finding.status is Z.PASS
    assert "cars fit in bays and aisles" in c.finding.measured
    assert "Table V column ELSEWHERE" in c.finding.required


def test_parking_short_with_no_cellars_drawn_fails_and_with_no_plan_at_all_is_unverified():
    none = fixture("rectangle").edited(lambda c: setattr(c.program, "cellars",
                                                         Cellars(levels=0)))
    assert status(none.report(), TABLE_V) is Z.FAIL
    undrawn = fixture("rectangle").edited(lambda c: setattr(c.program, "cellars", None))
    c = check(undrawn.report(), TABLE_V)
    assert c.finding.status is Z.UNVERIFIED and "underground" in c.finding.note


def test_the_cars_that_fit_must_meet_the_need_as_well_as_the_floor():
    """Plenty of floor, but a bay and its share of aisle taken as 5 m² a car: the cars laid out
    do not add up to the need, whatever the floor area says."""
    inputs = fixture("rectangle").with_rules(
        lambda r: setattr(r.parking.measurement, "sqm_per_car", 5.0))
    c = check(inputs.report(), TABLE_V)
    assert c.finding.status is Z.FAIL and "short by" in c.finding.measured


def test_when_whose_rules_apply_is_open_both_table_v_columns_are_evaluated():
    def open_column(rules):
        rules.parking.share_pct = None
        rules.jurisdiction.table_v_column = TableVColumn.OPEN

    def smaller_cellar(candidate):  # enough for 20% of the built-up area, not for 30%
        _cellar(candidate, box(20, 20, 130, 80))
    inputs = fixture("rectangle").with_rules(open_column).edited(smaller_cellar)
    c = check(inputs.report(), TABLE_V)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[TABLE_V_COLUMN] == {"GHMC_OR_CURE": Z.FAIL, "ELSEWHERE": Z.PASS}


def test_visitors_parking_at_ground_level_is_an_open_reading():
    def no_stilt_parking(candidate):
        for t in candidate.towers:
            t.has_stilt = False
        candidate.program.bays = []
    inputs = fixture("rectangle").edited(no_stilt_parking)
    assert status(inputs.report(), "Visitors' parking") is Z.FAIL  # at_ground: nothing there
    open_reading = inputs.with_rules(
        lambda r: setattr(r.interpretation(VISITOR_PARKING), "selected", ALL))
    c = check(open_reading.report(), "Visitors' parking")
    assert c.finding.status is Z.UNVERIFIED  # the cellar would do, if parking anywhere counts
    assert c.by_reading[VISITOR_PARKING] == {"at_ground": Z.FAIL, "anywhere": Z.PASS}


# --- surface bays ----------------------------------------------------------------------------


def _bays_on_open_land(*boxes):
    def edit(candidate):
        candidate.circulation.roads = []
        candidate.circulation.fire_hardstanding = []
        candidate.program.open_space = []
        candidate.program.bays = [rectangle(*b) for b in boxes]
    return edit


@pytest.mark.parametrize("bay, reason", [
    ((3.0, 4.0, 5.5, 9.0), "in the setback"),
    ((60.0, 38.0, 62.5, 43.0), "on a building, ramp or facility"),  # on T2
    ((-4.0, 40.0, -1.5, 45.0), "off the plot"),
    ((70.0, 3.0, 71.5, 7.0), "too small for a car"),
])
def test_a_bay_that_may_not_be_a_bay_is_said_not_to_be(bay, reason):
    report = fixture("rectangle").edited(_bays_on_open_land(bay)).report()
    c = check(report, "Surface parking bays")
    assert c.finding.status is Z.FAIL and reason in c.finding.measured


def test_a_bay_between_the_two_setbacks_is_a_bay_only_if_the_stilt_does_not_count():
    inputs = fixture("rectangle").edited(_bays_on_open_land((60.0, 8.2, 65.0, 10.7)))  # 5 x 2.5 m
    c = check(inputs.report(), "Surface parking bays")
    assert c.finding.status is Z.UNVERIFIED  # 9 m of setback takes 0.8 m of it, 8 m none
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {"counted": Z.FAIL, "not_counted": Z.PASS}


def test_two_bays_on_the_same_ground_are_one_bay_at_most():
    inputs = fixture("rectangle").edited(
        _bays_on_open_land((70.0, 12.0, 72.5, 17.0), (71.0, 12.0, 73.5, 17.0)))
    c = check(inputs.report(), "Surface parking bays")
    assert c.finding.status is Z.FAIL and "on another bay" in c.finding.measured


# --- cellars, setback and ramp ---------------------------------------------------------------


def test_the_cellar_keeps_3_m_from_the_property_line_on_a_site_over_2000_m2():
    short = fixture("rectangle").edited(lambda c: _cellar(c, box(2.5, 2.5, 147.5, 97.5)))
    c = check(short.report(), "Cellar setback")
    assert c.finding.status is Z.FAIL and "2.50 m" in c.finding.measured
    assert status(fixture("rectangle").report(), "Cellar setback") is Z.PASS


def test_every_cellar_level_beyond_the_first_adds_half_a_metre_to_the_setback():
    two = fixture("rectangle").edited(lambda c: _cellar(c, box(3.2, 3.2, 146.8, 96.8), levels=2))
    c = check(two.report(), "Cellar setback")
    assert c.finding.status is Z.FAIL and ">= 3.5 m" in c.finding.required
    deeper = fixture("rectangle").edited(
        lambda c: _cellar(c, box(3.6, 3.6, 146.4, 96.4), levels=2))
    assert status(deeper.report(), "Cellar setback") is Z.PASS


def test_a_cellar_under_a_water_buffer_fails():
    inputs = fixture("nala_plot").edited(lambda c: _cellar(c, box(3, 3, 147, 117)))
    assert status(inputs.report(), "Cellar setback") is Z.FAIL


def _ramps(*boxes):
    def edit(candidate):
        candidate.program.ramps = [rectangle(*b) for b in boxes]
    return edit


@pytest.mark.parametrize("ramps, ok", [
    ([(127.7, 62.87, 133.1, 86.86)], True),  # the fixture's: 5.4 m wide, 24 m long
    ([], False),  # cellars with no way down
    ([(127.7, 62.87, 132.0, 86.86)], False),  # one ramp 4.3 m wide: under 5.4 m
    ([(127.7, 62.87, 133.1, 80.0)], False),  # 17 m long: steeper than 1 in 8
    ([(127.7, 62.87, 131.3, 86.86), (134.0, 62.87, 137.6, 86.86)], True),  # two of 3.6 m
    ([(60.0, 24.0, 65.4, 47.99)], False),  # nowhere near a road
])
def test_the_ramp_is_5_4_m_or_two_of_3_6_m_at_1_in_8_with_its_top_on_a_road(ramps, ok):
    report = fixture("rectangle").edited(_ramps(*ramps)).report()
    assert (status(report, RAMP) is Z.PASS) is ok, check(report, RAMP).finding.measured


def test_a_ramp_may_never_be_in_the_front_setback():
    report = fixture("rectangle").edited(_ramps((20.0, 2.0, 25.4, 25.99))).report()
    c = check(report, RAMP)
    assert c.finding.status is Z.FAIL and "setback" in c.finding.measured


def test_a_ramp_in_a_side_setback_must_leave_7_m_and_so_never_fits_in_a_9_m_setback():
    report = fixture("rectangle").edited(_ramps((0.4, 40.0, 5.8, 63.99))).report()  # west side
    assert status(report, RAMP) is Z.FAIL


def _tall_with_two_side_ramps(inputs):
    """T1 at 36 m: a 12 m setback leaves 5 m of it for a ramp beside the boundary, 7 m clear."""
    tall = inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, "counted"))
    tall = tall.edited(lambda c: set_floors(c, "T1", 11))
    return tall.edited(_ramps((0.2, 40.0, 3.8, 63.99), (146.2, 40.0, 149.8, 63.99)))


def test_two_narrow_ramps_may_use_the_side_setbacks_where_7_m_stays_clear():
    assert status(_tall_with_two_side_ramps(fixture("rectangle")).report(), RAMP) is Z.PASS


def test_a_ramp_in_a_setback_is_unverified_while_it_is_not_known_which_side_is_the_front():
    def unknown_side(site):
        site.access.side.value = None
    inputs = _tall_with_two_side_ramps(fixture("rectangle")).with_site(unknown_side)
    assert status(inputs.report(), RAMP) is Z.UNVERIFIED


def test_the_cellar_utilities_taken_are_reported():
    c = check(fixture("rectangle").report(), "Cellar utilities")
    assert c.finding.status is Z.INFO and "10%" in c.finding.measured
