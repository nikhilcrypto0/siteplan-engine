"""The towers recomputed from the site model, the rules and the candidate's own geometry:
footprints, heights under every reading of the stilt, the Table IV row, setbacks and gaps."""

import pytest
from shapely.affinity import translate
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

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.resolved_rules import ALL, MIXED_HEIGHT_SPACING, STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import LegalVerdict

TEST_CLASS = "normative"
Z = Status
COUNTED, NOT_COUNTED = "counted", "not_counted"


def _measure(report, name):
    return next(t for t in report.recomputed.towers if t.name == name)


def _counted_only(inputs):
    return inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))


def _spacing_open(inputs):
    """The fixtures settle on the taller block's gap; leave it open, as the contract may."""
    return inputs.with_rules(lambda r: setattr(r.interpretation(MIXED_HEIGHT_SPACING),
                                               "selected", ALL))


# --- heights ------------------------------------------------------------------------------


def test_each_tower_has_a_physical_height_and_a_rule_height_under_every_reading_of_the_stilt():
    t1 = _measure(fixture("rectangle").report(), "T1")
    assert t1.physical_height_m == pytest.approx(27.0)  # 3 m stilt and 8 floors of 3 m
    assert t1.rule_height_m_by_reading == {COUNTED: 27.0, NOT_COUNTED: 24.0}
    assert t1.band_by_reading == {COUNTED: "24-27 m", NOT_COUNTED: "21-24 m"}
    assert t1.required_setback_m_by_reading == {COUNTED: 9.0, NOT_COUNTED: 8.0}


def test_a_prototypes_own_floor_height_beats_the_briefs():
    inputs = fixture("rectangle").edited(
        lambda c: setattr(c.prototype(tower(c, "T1").prototype_id).heights, "floor_to_floor_m",
                          3.2))
    t1 = _measure(inputs.report(), "T1")
    assert t1.physical_height_m == pytest.approx(3.0 + 8 * 3.2)
    assert t1.band_by_reading[COUNTED] == "27-30 m"
    assert _measure(inputs.report(), "T2").physical_height_m == pytest.approx(27.0)


def test_the_firms_standard_heights_apply_where_the_prototype_sets_none():
    inputs = fixture("rectangle").with_brief(
        lambda b: setattr(b.firm_standards.stilt_height_m, "value", 4.5))
    t1 = _measure(inputs.report(), "T1")
    assert t1.physical_height_m == pytest.approx(28.5)
    assert t1.rule_height_m_by_reading == {COUNTED: 28.5, NOT_COUNTED: 24.0}


def test_a_tower_without_a_stilt_is_the_same_height_under_either_reading():
    inputs = fixture("rectangle").edited(lambda c: setattr(tower(c, "T1"), "has_stilt", False))
    t1 = _measure(inputs.report(), "T1")
    assert t1.physical_height_m == pytest.approx(24.0)
    assert t1.rule_height_m_by_reading == {COUNTED: 24.0, NOT_COUNTED: 24.0}


def test_the_height_comes_from_the_floors_not_from_what_the_generator_says():
    inputs = fixture("rectangle").edited(lambda c: set_floors(c, "T3", 10))
    assert _measure(inputs.report(), "T3").physical_height_m == pytest.approx(33.0)
    assert inputs.candidate.metrics.extra["physical_height_m"] == 27.0  # the claim is not used


# --- the footprint ------------------------------------------------------------------------


def test_the_footprint_is_the_prototypes_placed_and_a_mismatch_with_the_stated_one_blocks():
    inputs = fixture("rectangle")
    assert [d for d in inputs.report().cross_checks if "footprint" in d.item] == []

    def lie(candidate):  # the generator says T1 is 20 m to the east of where it stands
        tower(candidate, "T1").footprint = shape(translate(footprint(candidate, "T1"), 20.0))

    report = inputs.edited(lie).report()
    blocking = [d for d in report.cross_checks if d.item == "footprint T1"]
    assert len(blocking) == 1 and blocking[0].blocks_pass and blocking[0].source == "generator"
    assert report.verdict.legal is LegalVerdict.FAIL


def test_measurements_are_taken_on_the_recomputed_footprint_not_the_stated_one():
    """A generator that states a footprint inside the setback line while the prototype stands
    outside it does not get the benefit: the setback is measured on where the tower is."""
    inputs = fixture("rectangle")

    def lie(candidate):
        tower(candidate, "T1").y += 8.0  # moved, footprint left as it was stated
    report = inputs.edited(lie).report()
    assert status(report, "All-round setback: T1") is Z.FAIL
    assert report.verdict.legal is LegalVerdict.FAIL


# --- setbacks, gaps: the readings -----------------------------------------------------------


def _north_to(inputs, name, metres):
    net = inputs.site.net_plot.value.to_shapely()

    def plant(candidate):
        move_tower(candidate, name, 0.0, net.boundary.distance(footprint(candidate, name))
                   - metres)
    return inputs.edited(plant)


def test_legal_under_both_readings_is_pass_and_the_result_names_both():
    c = check(fixture("rectangle").report(), "All-round setback: T1")
    assert c.finding.status is Z.PASS
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.PASS, NOT_COUNTED: Z.PASS}


def test_legal_only_if_the_stilt_does_not_count_is_unverified_and_names_the_reading():
    c = check(_north_to(fixture("rectangle"), "T1", 8.5).report(), "All-round setback: T1")
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.FAIL, NOT_COUNTED: Z.PASS}
    assert NOT_COUNTED in c.finding.note and STILT_IN_RULE_HEIGHT in c.finding.note
    assert "9.00" in c.finding.required and "8.00" in c.finding.required


def test_a_tower_under_both_requirements_fails_under_both():
    c = check(_north_to(fixture("rectangle"), "T1", 7.0).report(), "All-round setback: T1")
    assert c.finding.status is Z.FAIL
    assert set(c.by_reading[STILT_IN_RULE_HEIGHT].values()) == {Z.FAIL}


def test_the_setback_is_measured_to_the_net_plot_not_to_the_surveyed_boundary():
    """The rectangle's surveyed boundary reaches 3 m past the net plot on the south, land that
    is being surrendered: a tower 8.5 m from the net plot is 11.5 m from the boundary, and only
    the first is its setback."""
    inputs = fixture("rectangle")
    assert inputs.site.boundary.to_shapely().bounds[1] == pytest.approx(-3.0)
    assert inputs.site.net_plot.value.to_shapely().bounds[1] == pytest.approx(0.0)

    def south(candidate):
        move_tower(candidate, "T2", 0.0, -(footprint(candidate, "T2").bounds[1] - 8.5))
    t2 = _measure(inputs.edited(south).report(), "T2")
    assert t2.setback_m == pytest.approx(8.5, abs=1e-6)


def test_a_tower_outside_the_net_plot_has_no_setback_at_all():
    def push(candidate):
        move_tower(candidate, "T3", 40.0, 0.0)  # over the east boundary
    report = fixture("rectangle").edited(push).report()
    assert _measure(report, "T3").setback_m == 0.0
    assert status(report, "All-round setback: T3") is Z.FAIL


def test_the_gap_between_two_towers_is_the_distance_between_their_footprints():
    report = fixture("rectangle").report()
    pair = next(p for p in report.recomputed.pairs if (p.a, p.b) == ("T1", "T2"))
    inputs = fixture("rectangle")
    assert pair.gap_m == pytest.approx(
        footprint(inputs.candidate, "T1").distance(footprint(inputs.candidate, "T2")))
    assert pair.required_m == 9.0  # the strictest reading: the taller block's 24-27 m gap
    assert status(report, "Gap between blocks: T1 / T2") is Z.PASS


def _mixed(inputs, gap_m):
    """T2 nine floors (30 m: gap 10 m) beside T1's eight (27 m: gap 9 m), `gap_m` apart."""
    def plant(candidate):
        set_floors(candidate, "T2", 9)
        now = footprint(candidate, "T1").distance(footprint(candidate, "T2"))
        move_tower(candidate, "T1", 0.0, gap_m - now)
    return inputs.edited(plant)


def test_between_blocks_of_different_heights_the_taller_blocks_gap_governs():
    inputs = _counted_only(fixture("rectangle"))
    inputs = inputs.with_rules(lambda r: select(r, MIXED_HEIGHT_SPACING, "taller_governs"))
    report = _mixed(inputs, 9.4).report()  # 9 m would do for T1, but T2 is taller: 10 m
    assert status(report, "Gap between blocks: T1 / T2") is Z.FAIL
    assert "10.00" in check(report, "Gap between blocks: T1 / T2").finding.required


def test_whether_the_taller_governs_is_an_open_reading_and_the_result_names_it():
    inputs = _spacing_open(_counted_only(fixture("rectangle")))  # the stilt settled, spacing open
    c = check(_mixed(inputs, 9.7).report(), "Gap between blocks: T1 / T2")
    # 10 m if the taller governs, 9.5 m if each keeps its own half
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[MIXED_HEIGHT_SPACING] == {"taller_governs": Z.FAIL, "each_own": Z.PASS}
    assert MIXED_HEIGHT_SPACING in c.finding.note


def test_blocks_of_one_height_need_the_same_gap_whichever_reading():
    c = check(_spacing_open(fixture("rectangle")).report(), "Gap between blocks: T1 / T3")
    assert c.finding.status is Z.PASS
    assert c.by_reading[MIXED_HEIGHT_SPACING] == {"taller_governs": Z.PASS, "each_own": Z.PASS}


# --- the band, the road, the plot ------------------------------------------------------------


def _road(inputs, legal=None, master=None, status_=None):
    def edit(site):
        road = site.access_road()
        if legal is not None:
            road.legal_row_m.value = legal
        if master is not None:
            road.master_plan_row_m = type(road.legal_row_m)(
                value=master, status=Provenance.USER_CONFIRMED, source_kind="ARCHITECT",
                source="made up")
        if status_ is not None:
            road.legal_row_m.status = status_
    return inputs.with_site(edit)


def test_a_road_too_narrow_for_the_tallest_towers_band_fails_where_every_reading_agrees():
    report = _road(fixture("rectangle"), legal=10.0).report()  # both bands need 12 m or more
    c = check(report, "Abutting road width (for T1)")
    assert c.finding.status is Z.FAIL
    assert set(c.by_reading[STILT_IN_RULE_HEIGHT].values()) == {Z.FAIL}


def test_a_road_that_serves_the_lower_band_only_is_unverified_with_the_stilt_open():
    report = _road(fixture("rectangle"), legal=12.5).report()
    c = check(report, "Abutting road width (for T1)")  # 27 m needs 18 m, 24 m needs 12 m
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.FAIL, NOT_COUNTED: Z.PASS}


def test_the_master_plan_width_counts_where_there_is_one_and_says_so():
    report = _road(fixture("rectangle"), legal=10.0, master=18.29).report()
    c = check(report, "Abutting road width (for T1)")
    assert c.finding.status is Z.PASS and "master plan" in c.finding.measured
    assert "surrendered" in c.finding.note


def test_an_unknown_road_width_is_unverified_not_assumed():
    report = _road(fixture("rectangle"), status_=Provenance.UNVERIFIED).report()
    assert status(report, "Abutting road width (for T1)") is Z.UNVERIFIED


def test_the_drawn_carriageway_is_reported_beside_the_declared_width_never_used():
    inputs = fixture("rectangle").with_site(
        lambda s: setattr(s.access_road(), "drawn_width_m", 7.0))
    c = check(inputs.report(), "Abutting road width (for T1)")
    assert c.finding.status is Z.PASS  # the declared 18.29 m, not the 7 m drawn
    assert "7.00 m of carriageway" in c.finding.note


def test_plot_size_for_a_high_rise_is_measured_on_the_net_plot():
    assert status(fixture("rectangle").report(), "Plot size for high-rise") is Z.PASS

    def shrink(site):
        site.net_plot.value = shape(box(0, 0, 40, 40))
        site.ownership.net_sqm.value = site.ownership.gross_sqm.value = 1600.0
    assert status(fixture("rectangle").with_site(shrink).report(),
                  "Plot size for high-rise") is Z.FAIL


def test_the_rule_height_limit_in_the_rules_is_held_against_every_tower():
    def lower(rules):
        rules.height.limits[0].max_m = 25.0
    report = fixture("rectangle").with_rules(lower).report()
    c = next(x for x in report.legal if x.finding.rule.startswith("Rule-height limit"))
    assert c.finding.status is Z.UNVERIFIED  # 27 m is over 25 m, 24 m is not
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.FAIL, NOT_COUNTED: Z.PASS}


def test_the_height_above_sea_level_is_unverified_without_coordinates():
    c = check(fixture("rectangle").report(), "Height above sea level (airport and Air Force)")
    assert c.finding.status is Z.UNVERIFIED and "coordinates" in c.finding.measured


# --- heights the table does not settle ---------------------------------------------------------


def test_a_block_below_the_high_rise_threshold_is_not_judged_by_table_iv():
    report = fixture("small_plot").report()  # 18 m with the stilt, 15 m without
    assert status(report, "All-round setback: T1") is Z.NOT_CHECKED
    assert "All-round setback: T1" in report.not_checked


def test_a_block_that_is_high_rise_only_if_the_stilt_counts_is_unverified_not_passed():
    inputs = fixture("rectangle").edited(lambda c: set_floors(c, "T1", 6))  # 21 m exactly / 18 m
    c = check(inputs.report(), "All-round setback: T1")
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[STILT_IN_RULE_HEIGHT][NOT_COUNTED] is Z.NOT_CHECKED


def test_a_block_exactly_at_the_threshold_is_held_to_the_stricter_row_above_it():
    inputs = _counted_only(fixture("rectangle")).edited(lambda c: set_floors(c, "T1", 6))
    # T1 is 21.0 m: the resolved bands have no Table IV row for exactly 21 m
    assert status(inputs.report(), "All-round setback: T1") is Z.PASS  # 13 m meets the row above
    short = _north_to(inputs, "T1", 7.5).report()
    c = check(short, "All-round setback: T1")
    assert c.finding.status is Z.UNVERIFIED and "threshold" in c.finding.note


def test_an_unknown_reading_is_unverified_never_guessed():
    def invent(rules):
        interpretation = rules.interpretation(STILT_IN_RULE_HEIGHT)
        interpretation.alternatives["half_counted"] = "half the stilt counts"
        interpretation.selected = "half_counted"
    c = check(fixture("rectangle").with_rules(invent).report(), "All-round setback: T1")
    assert c.finding.status is Z.UNVERIFIED and "half_counted" in c.finding.measured


def test_the_verdict_follows_the_contracts_rule_and_a_report_survives_json():
    from siteplan.contracts import ValidationReport
    from siteplan.contracts.validation import legal_verdict

    report = fixture("rectangle").report()
    assert report.verdict.legal is legal_verdict(report.legal, report.cross_checks)
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report
    assert all(c.family.value != "PROGRAM" for c in report.legal)
