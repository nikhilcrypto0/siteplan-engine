"""The club house (rule 15(a)(x)), the water buffer, the planted strip and the exits."""

from shapely.affinity import scale, translate
from shapely.geometry import box
from validator_helpers import (
    check,
    fixture,
    footprint,
    move_tower,
    select,
    set_floors,
    shape,
    status,
    tower,
)

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import ALL, AMENITY_SHARE, STILT_IN_RULE_HEIGHT

TEST_CLASS = "normative"
Z = Status
CLUB = "Amenities (club house)"
STRIP = "Peripheral green strip"


def _club_scaled(factor):
    def edit(candidate):
        club = candidate.program.club_house
        centre = club.shape.to_shapely().centroid
        club.shape = shape(scale(club.shape.to_shapely(), factor, factor, origin=centre))
    return edit


def _share_open(inputs):
    return inputs.with_rules(lambda r: setattr(r.interpretation(AMENITY_SHARE), "selected", ALL))


# --- club house ------------------------------------------------------------------------------


def test_the_club_house_meets_three_percent_of_the_built_up_area_it_helps_make():
    c = check(fixture("rectangle").report(), CLUB)
    assert c.finding.status is Z.PASS and "3.00% of built-up" in c.finding.measured


def test_a_club_house_under_the_planning_minimum_fails_where_that_reading_is_selected():
    assert status(fixture("rectangle").edited(_club_scaled(0.8)).report(), CLUB) is Z.FAIL


def test_a_club_house_of_exactly_3_percent_meets_both_wordings_of_the_clause():
    c = check(_share_open(fixture("rectangle")).report(), CLUB)
    assert c.finding.status is Z.PASS
    assert c.by_reading[AMENITY_SHARE] == {"minimum_3_percent": Z.PASS,
                                           "up_to_3_percent_or_cap": Z.PASS}


def test_a_larger_club_house_meets_the_minimum_but_may_break_the_2016_ceiling():
    inputs = _share_open(fixture("rectangle")).edited(_club_scaled(1.3))
    c = check(inputs.report(), CLUB)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[AMENITY_SHARE] == {"minimum_3_percent": Z.PASS,
                                           "up_to_3_percent_or_cap": Z.FAIL}


def test_a_smaller_club_house_meets_the_ceiling_but_not_the_minimum():
    inputs = _share_open(fixture("rectangle")).edited(_club_scaled(0.8))
    c = check(inputs.report(), CLUB)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[AMENITY_SHARE] == {"minimum_3_percent": Z.FAIL,
                                           "up_to_3_percent_or_cap": Z.PASS}


def test_the_2016_cap_of_50000_sft_lowers_the_ceiling_where_it_is_the_lower():
    def small_cap(rules):
        rules.amenities.cap_sqft_2016.value = 5_000.0  # 465 m²: under 3% of this scheme
    inputs = _share_open(fixture("rectangle")).with_rules(small_cap)
    c = check(inputs.report(), CLUB)
    assert c.by_reading[AMENITY_SHARE]["up_to_3_percent_or_cap"] is Z.FAIL


def test_the_clause_applies_only_from_100_units_and_the_units_are_counted_from_the_towers():
    c = check(fixture("nala_plot").report(), CLUB)
    assert c.finding.status is Z.INFO and c.finding.measured == "64 units"
    assert fixture("rectangle").report().recomputed.units_by_type == {"2BHK": 128, "3BHK": 80}


def test_a_club_house_inside_a_residential_block_is_not_a_block_of_its_own():
    def overlap(candidate):
        t1 = footprint(candidate, "T1")
        candidate.program.club_house.shape = shape(translate(
            candidate.program.club_house.shape.to_shapely(),
            t1.centroid.x - candidate.program.club_house.shape.to_shapely().centroid.x,
            t1.centroid.y - candidate.program.club_house.shape.to_shapely().centroid.y))
    c = check(fixture("rectangle").edited(overlap).report(), CLUB)
    assert c.finding.status is Z.FAIL and "inside a residential block" in c.finding.measured


def test_a_scheme_of_100_units_or_more_with_no_club_house_fails():
    def none(candidate):
        candidate.program.club_house = None
    assert status(fixture("rectangle").edited(none).report(), CLUB) is Z.FAIL


# --- water -----------------------------------------------------------------------------------


def test_the_water_buffer_is_rebuilt_from_the_lines_and_the_class():
    report = fixture("nala_plot").report()
    assert report.recomputed.quantities["water_buffer_on_site_sqm"] == 2160.0  # 18 m x 120 m
    assert status(report, "Water-body buffer") is Z.PASS


def test_a_block_inside_the_buffer_fails_and_one_on_its_edge_does_not():
    def overlap(candidate):
        move_tower(candidate, "T1", 50.0, 0.0)

    inside = fixture("nala_plot").edited(overlap).report()
    c = check(inside, "Water-body buffer")
    assert c.finding.status is Z.FAIL and "T1" in c.finding.measured

    def on_the_edge(candidate):
        reach = footprint(candidate, "T1").bounds[2]
        move_tower(candidate, "T1", 66.0 - reach, 0.0)  # the buffer starts 9 m short of x = 75
    assert status(fixture("nala_plot").edited(on_the_edge).report(), "Water-body buffer") is Z.PASS


def test_a_cellar_may_not_run_under_the_buffer_either():
    from siteplan.contracts.candidate import Cellars

    inputs = fixture("nala_plot").edited(lambda c: setattr(
        c.program, "cellars", Cellars(levels=1, outline=[shape(box(3, 3, 147, 117))])))
    assert status(inputs.report(), "Water-body buffer") is Z.FAIL


def test_a_water_body_with_no_geometry_has_no_buffer_to_keep_clear_so_it_is_unverified():
    def erase(site):
        site.water[0].lines = []
    report = fixture("nala_plot").with_site(erase).report()
    assert status(report, "Water-body buffer") is Z.UNVERIFIED


# --- the green strip -------------------------------------------------------------------------


def test_the_strip_is_required_where_the_setback_reaches_9_m_and_the_fixture_has_it():
    inputs = fixture("rectangle").with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, "counted"))
    c = check(inputs.report(), STRIP)
    assert c.finding.status is Z.PASS and "broken only at the entrance" in c.finding.measured


def test_with_the_stilt_open_the_strip_is_asked_for_under_one_reading_only():
    c = check(fixture("rectangle").report(), STRIP)
    assert c.finding.status is Z.PASS
    assert "not required under this reading" in c.finding.measured


def test_a_layout_without_the_strip_fails_where_the_setback_asks_for_one():
    inputs = fixture("rectangle").edited(lambda c: setattr(c.program, "green_strip", []))
    assert status(inputs.report(), STRIP) is Z.UNVERIFIED  # asked for only if the stilt counts
    settled = inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, "counted"))
    assert status(settled.report(), STRIP) is Z.FAIL


def test_a_strip_narrower_than_2_m_fails():
    def thin(candidate):
        net = box(0, 0, 150, 100)
        candidate.program.green_strip = [shape(net.difference(net.buffer(-1.0)))]
    inputs = fixture("rectangle").with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, "counted"))
    c = check(inputs.edited(thin).report(), STRIP)
    assert c.finding.status is Z.FAIL and "narrower than 2 m" in c.finding.measured


def test_a_setback_under_9_m_asks_for_no_strip():
    def lower(candidate):
        for t in candidate.towers:
            set_floors(candidate, t.name, 7)  # 24 m with the stilt, 21 m without
    c = check(fixture("rectangle").edited(lower).report(), STRIP)
    assert c.finding.status is Z.INFO and "8.00 m" in c.finding.measured


def test_with_no_setback_known_the_strip_is_not_checked():
    assert status(fixture("small_plot").report(), STRIP) is Z.NOT_CHECKED


# --- exits ---------------------------------------------------------------------------------


def test_internal_egress_is_not_checked_on_any_high_rise_layout():
    report = fixture("rectangle").report()
    assert status(report, "INTERNAL_EGRESS") is Z.NOT_CHECKED
    assert "INTERNAL_EGRESS" in report.not_checked
    assert "72 m" in check(report, "INTERNAL_EGRESS").finding.measured  # the longest block
    assert "INTERNAL_EGRESS" not in {c.finding.rule for c in fixture("small_plot").report().legal}
    assert tower(fixture("rectangle").candidate, "T1")
