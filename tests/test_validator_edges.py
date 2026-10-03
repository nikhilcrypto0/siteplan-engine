"""The edges of the rules: a value exactly at a threshold, a shortfall just past it, a figure that
differs by a little. A mutation tester changed the validator's logic 146 ways and the first set of
tests caught 65: they planted large violations on one fixture, so a threshold nudged by a few
percent, a comparison flipped at its boundary or a term dropped went unnoticed. Each test here
pins one of the survivors to the behaviour the rules ask for."""

from dataclasses import replace

import pytest
from shapely.geometry import Polygon, box
from validator_helpers import (
    check,
    fixture,
    move_tower,
    rectangle,
    select,
    set_floors,
    shape,
    shapes,
    status,
)

from siteplan import rules as law
from siteplan.contracts.accounting import DeductionKind, LayerKind, PhysicalUse
from siteplan.contracts.candidate import Cellars, SiteProgram
from siteplan.contracts.common import Basis, Provenance, Status
from siteplan.contracts.resolved_rules import (
    ALL,
    MIXED_HEIGHT_SPACING,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.validator import accounting, context, drawn
from siteplan.validator.readings import COUNTED, basis_note
from siteplan.validator.shapes import mended, sides_of

TEST_CLASS = "normative"
Z = Status


def _plot(sqm):
    """A plot of exactly that area (50 m deep), as the site and its ownership both say."""
    def edit(site):
        site.net_plot.value = shape(box(0.0, 0.0, sqm / 50.0, 50.0))
        site.ownership.net_sqm.value = site.ownership.gross_sqm.value = sqm
        site.ownership.deductions = []
    return edit


def _counted(inputs):
    return inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))


# --- plot size, TDR ----------------------------------------------------------------------------


def test_a_plot_of_exactly_the_minimum_takes_a_high_rise_and_one_just_under_does_not():
    need = law.MIN_HIGH_RISE_PLOT_SQM
    assert status(fixture("rectangle").with_site(_plot(need)).report(),
                  "Plot size for high-rise") is Z.PASS
    assert status(fixture("rectangle").with_site(_plot(need - 1.0)).report(),
                  "Plot size for high-rise") is Z.FAIL


@pytest.mark.parametrize("sqm, asked", [(750.0, True), (749.0, False), (2000.0, True),
                                        (2001.0, False)])
def test_the_tdr_question_covers_plots_from_750_to_2000_m2_inclusive(sqm, asked):
    inputs = _counted(fixture("rectangle")).with_site(_plot(sqm)).edited(
        lambda c: set_floors(c, "T1", 5))  # 18 m with the stilt
    names = {c.finding.rule for c in inputs.report().legal}
    assert ("TDR for a building of 18 to 21 m" in names) is asked


# --- the Table IV seam and the mean of two gaps ----------------------------------------------


def _all_at_the_seam(candidate):
    for t in candidate.towers:
        set_floors(candidate, t.name, 6)  # exactly 21 m with the stilt counted


def _legal_road(inputs, metres):
    def edit(site):
        site.access_road().legal_row_m.value = metres
    return inputs.with_site(edit)


def test_a_road_short_only_of_the_row_above_a_seam_is_unverified_not_failed():
    inputs = _legal_road(_counted(fixture("rectangle")).edited(_all_at_the_seam), 10.0)
    assert status(inputs.report(), "Abutting road width (for T1)") is Z.UNVERIFIED


def test_a_gap_short_only_of_the_row_above_a_seam_is_unverified_not_failed():
    def close(candidate):
        _all_at_the_seam(candidate)
        move_tower(candidate, "T1", 0.0, -4.0)  # 5 m from T2: short of the row above's gap
    c = check(_counted(fixture("rectangle")).edited(close).report(), "Gap between blocks: T1 / T2")
    assert c.finding.status is Z.UNVERIFIED


def test_where_each_block_keeps_its_own_gap_the_gap_asked_is_their_mean_not_the_smaller():
    """A 30 m block and a 27 m block ask 10 m and 9 m: 9.5 m between them, so 9.2 m is short."""
    def tall_and_short(candidate):
        set_floors(candidate, "T1", 9)  # 30 m with the stilt
        move_tower(candidate, "T1", 0.0, 0.1)  # 9.2 m from T2
    inputs = _counted(fixture("rectangle")).with_rules(
        lambda r: select(r, MIXED_HEIGHT_SPACING, "each_own")).edited(tall_and_short)
    c = check(inputs.report(), "Gap between blocks: T1 / T2")
    assert c.finding.status is Z.FAIL and "9.50 m" in c.finding.required


def test_the_status_of_the_road_width_is_said_beside_it():
    c = check(fixture("rectangle").report(), "Abutting road width (for T1)")
    assert "Width status: DECLARED_ON_SITE_PLAN" in c.finding.note


def test_what_a_rule_value_rests_on_is_said_unless_it_is_a_verified_legal_rule():
    value = fixture("rectangle").rules.circulation.internal_road_m
    assert basis_note(value) == ""
    unverified = value.model_copy(update={"status": Provenance.UNVERIFIED})
    assert "UNVERIFIED" in basis_note(unverified)
    interpreted = value.model_copy(update={"basis": Basis.UNRESOLVED_INTERPRETATION})
    assert "UNRESOLVED_INTERPRETATION" in basis_note(interpreted)


def test_what_stands_between_a_layout_and_a_pass_is_listed_in_the_verdict():
    report = fixture("rectangle").report()
    assert "Height above sea level (airport and Air Force): UNVERIFIED" in report.verdict.reasons


# --- shapes ------------------------------------------------------------------------------------


def test_a_shape_that_crosses_itself_is_mended_to_the_ground_of_both_lobes():
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
    mended_shape, flaw = mended(bowtie)
    assert mended_shape.area == pytest.approx(50.0) and "Self-intersection" in flaw
    assert mended(box(0, 0, 1, 1)) == (box(0, 0, 1, 1), "")


def test_the_rectangle_round_a_polygon_is_the_smallest_not_the_largest():
    long, short = sides_of(Polygon([(0, 0), (10, 0), (2, 3)]))
    assert (long, short) == pytest.approx((10.0, 3.0))


# --- ramps in the setback ----------------------------------------------------------------------


def test_a_single_ramp_in_a_12_m_setback_may_not_reach_past_the_5_m_that_leaves_7_m_clear():
    def tall(inputs):
        return _counted(inputs).edited(lambda c: set_floors(c, "T1", 11)).edited(
            lambda c: setattr(c.program, "ramps", [rectangle(0.1, 40.0, 5.5, 63.99)]))
    c = check(tall(fixture("rectangle")).report(), "Cellar ramp")
    assert c.finding.status is Z.FAIL and "setback" in c.finding.measured


# --- what was drawn ---------------------------------------------------------------------------


def test_a_candidate_with_buildings_and_a_cellar_plan_is_more_than_buildings():
    inputs = fixture("rectangle").edited(lambda c: (
        setattr(c, "circulation", type(c.circulation)()), setattr(c, "program", SiteProgram(
            cellars=Cellars(levels=1, outline=[rectangle(20.0, 20.0, 80.0, 50.0)])))))
    assert not drawn.read(inputs.candidate, inputs.brief).buildings_only


def test_clear_hardstanding_alone_is_a_circulation_layout():
    inputs = fixture("rectangle").edited(lambda c: setattr(
        c.circulation, "roads", []) or setattr(c.circulation, "gates", []))
    assert drawn.read(inputs.candidate, inputs.brief).has_circulation  # the hardstanding stays
    bare = inputs.edited(lambda c: setattr(c.circulation, "fire_hardstanding", []))
    assert not drawn.read(bare.candidate, bare.brief).has_circulation


# --- the ledger ---------------------------------------------------------------------------------


def _ledger(inputs):
    ctx = context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)
    return accounting.recompute(ctx)


def test_a_bay_laid_over_a_road_keeps_only_the_ground_the_road_does_not_take():
    """Road before bay: a bay 2.5 m wide with 2 m of it on the west arm of the loop road keeps
    2.5 m²."""
    def over_the_road(candidate):
        candidate.towers, candidate.program = [], SiteProgram(
            bays=[rectangle(9.0, 40.0, 11.5, 45.0)])
        candidate.circulation.fire_hardstanding = []
    by_use = _ledger(fixture("rectangle").edited(over_the_road)).ledger.by_use()
    assert by_use[PhysicalUse.SURFACE_PARKING] == pytest.approx(2.5, abs=0.1)


def test_two_bays_overlapping_by_3_m2_are_a_conflict_in_the_ledger():
    def overlapping(candidate):
        candidate.towers, candidate.program = [], SiteProgram(
            bays=[rectangle(20.0, 20.0, 22.5, 25.0), rectangle(21.9, 20.0, 24.4, 25.0)])
        candidate.circulation.fire_hardstanding = []
    assert status(fixture("rectangle").edited(overlapping).report(), "Every square metre once"
                  ) is Z.FAIL


# --- the rule layers ---------------------------------------------------------------------------


def test_the_cellar_setback_layer_is_the_ring_along_the_boundary_not_the_land_inside_it():
    layers = fixture("rectangle").report().accounting.rule_layers.of(LayerKind.CELLAR_SETBACK)
    assert len(layers) == 1
    net = box(0.0, 0.0, 150.0, 100.0)
    assert layers[0].area_sqm == pytest.approx(net.area - net.buffer(-3.0).area, abs=0.01)


def test_a_block_gap_that_differs_between_the_readings_names_the_open_spacing_reading():
    def two_heights(candidate):
        set_floors(candidate, "T1", 9)  # 30 m beside 27 m blocks: the gap asked depends on it
    inputs = _counted(fixture("rectangle")).with_rules(
        lambda r: setattr(r.interpretation(MIXED_HEIGHT_SPACING), "selected", ALL)
    ).edited(two_heights)
    gaps = inputs.report().accounting.rule_layers.of(LayerKind.BLOCK_GAP)
    named = {g.applies_to: g.interpretation_ref for g in gaps}
    assert named["T1/T2"] == MIXED_HEIGHT_SPACING
    assert named["T2/T3"] is None  # two 27 m blocks ask the same whichever reading


# --- what an envelope or a generator claims ----------------------------------------------------


def _discrepancies(report):
    return {d.item: d for d in report.cross_checks}


def test_a_candidate_made_for_another_brief_is_not_judged_as_if_it_were_this_ones():
    report = fixture("rectangle").edited(lambda c: setattr(c, "brief_ref", "0123456789abcdef")
                                         ).report()
    assert _discrepancies(report)["candidate.brief_ref"].blocks_pass


def test_a_partition_made_for_another_net_area_blocks_a_pass():
    report = fixture("rectangle").edited(
        lambda c: setattr(c.partition, "net_area_sqm", c.partition.net_area_sqm * 1.2)).report()
    assert _discrepancies(report)["partition: net area"].blocks_pass


def test_a_generator_claiming_pass_where_the_validator_cannot_tell_is_recorded_not_blocking():
    def boast(candidate):
        candidate.generator_claims = [
            replace(c, status=Z.PASS) if c.rule == "Fire access: 45 t hard surface" else c
            for c in candidate.generator_claims]
    inputs = fixture("rectangle").edited(boast)
    assert "Fire access: 45 t hard surface" in {c.rule for c in inputs.candidate.generator_claims}
    d = _discrepancies(inputs.report()).get("Fire access: 45 t hard surface")
    assert d is not None and not d.blocks_pass


def test_a_stated_footprint_a_little_off_the_drawn_one_is_still_flagged():
    def shift(candidate):
        t = candidate.towers[0]
        t.footprint = shape(candidate.placed_footprint(t).buffer(0.4, join_style="mitre"))
    assert _discrepancies(fixture("rectangle").edited(shift).report())["footprint T1"].blocks_pass


def test_a_claimed_built_up_area_a_few_percent_under_the_true_one_is_flagged():
    def understate(candidate):
        candidate.metrics.built_up_sqft *= 0.97
    d = _discrepancies(fixture("rectangle").edited(understate).report())["built-up area"]
    assert d.blocks_pass
    close = fixture("rectangle").edited(lambda c: setattr(
        c.metrics, "built_up_sqft", c.metrics.built_up_sqft * 0.998)).report()
    assert "built-up area" not in _discrepancies(close)


def test_an_envelope_made_for_other_rules_is_not_compared_even_for_the_same_site():
    """A wrong envelope (a 3 m setback all through) made for other rules says nothing about these:
    it is noted, and nothing in it is held against the layout."""
    inputs = fixture("rectangle")
    envelope = inputs.envelope.model_copy(deep=True)
    for band in envelope.bands:
        band.setback_m = 3.0
    other = replace(inputs, envelope=envelope.model_copy(update={"rules_ref": "0123456789abcdef"}))
    report = other.report(envelope=True)
    assert not [d for d in report.cross_checks if d.item.startswith("envelope setback")]
    assert [d for d in replace(inputs, envelope=envelope).report(envelope=True).cross_checks
            if d.item.startswith("envelope setback")]  # made for these rules, it is compared


def test_the_envelopes_buildable_land_is_compared_with_the_water_taken_out():
    inputs = fixture("nala_plot")
    envelope = inputs.envelope.model_copy(deep=True)
    band = envelope.bands[-1]
    net = inputs.site.net_plot.value.to_shapely()
    band.buildable = shapes(net.buffer(-band.setback_m))  # the water buffer not taken out of it
    found = [d for d in replace(inputs, envelope=envelope).report(envelope=True).cross_checks
             if d.item.startswith("envelope buildable land")]
    assert found and found[0].blocks_pass


# --- the site's own land -----------------------------------------------------------------------


def test_a_net_outline_far_from_the_net_ownership_is_not_trusted():
    def off(site):
        site.ownership.net_sqm.value *= 1.15  # 15% over what the outline encloses
        site.ownership.gross_sqm.value *= 1.15
        site.ownership.deductions = []
    c = check(fixture("rectangle").with_site(off).report(), "Net plot")
    assert c.finding.status is Z.UNVERIFIED and "disagree" in c.finding.note


def test_a_planted_strip_missing_along_half_the_boundary_fails():
    def half(candidate):
        strip = candidate.program.green_strip[0].to_shapely()
        candidate.program.green_strip = shapes(strip.intersection(box(0.0, -10.0, 75.0, 110.0)))
    c = check(_counted(fixture("rectangle")).edited(half).report(), "Peripheral green strip")
    assert c.finding.status is Z.FAIL and "of the strip is missing" in c.finding.measured


def test_a_drawing_of_buildings_only_cannot_pass_the_planted_strip():
    inputs = fixture("rectangle").edited(lambda c: (
        setattr(c, "circulation", type(c.circulation)()), setattr(c, "program", SiteProgram())))
    assert status(inputs.report(), "Peripheral green strip") is Z.UNVERIFIED


# --- the club house ---------------------------------------------------------------------------


def _club_of(candidate, sqm):
    """A one-floor club house of that area, well clear of everything, replacing the fixture's."""
    candidate.program.club_house.floors = 1
    candidate.program.club_house.shape = rectangle(40.0, 5.0, 40.0 + sqm / 20.0, 25.0)


def _tower_built_up(inputs):
    return inputs.report().recomputed.quantities["tower_floor_sqm"]


def test_the_clause_applies_to_a_scheme_of_exactly_the_units_it_names():
    units = int(fixture("rectangle").report().recomputed.quantities["units"])

    def from_units(n):
        return lambda r: setattr(r.amenities.from_units, "value", n)

    def no_club(candidate):
        candidate.program.club_house = None
    missing = fixture("rectangle").edited(no_club)
    named = "Amenities (club house)"
    assert status(missing.with_rules(from_units(units)).report(), named) is Z.FAIL
    assert status(missing.with_rules(from_units(units + 1)).report(), named) is Z.INFO


def test_the_club_house_is_3_percent_of_the_built_up_area_it_is_part_of():
    """The built-up area the 3% is of includes the club house: a club house of 3.05% of the towers
    alone is 2.96% of the whole and short."""
    inputs = fixture("rectangle").with_rules(lambda r: select(r, "amenity_share",
                                                              "minimum_3_percent"))
    towers = _tower_built_up(inputs)
    short = inputs.edited(lambda c: _club_of(c, 0.0305 * towers))
    assert status(short.report(), "Amenities (club house)") is Z.FAIL
    enough = inputs.edited(lambda c: _club_of(c, 0.0312 * towers))
    assert status(enough.report(), "Amenities (club house)") is Z.PASS


def test_a_club_house_20_m2_under_the_minimum_fails():
    inputs = fixture("rectangle").with_rules(lambda r: select(r, "amenity_share",
                                                              "minimum_3_percent"))
    towers = _tower_built_up(inputs)
    need = 0.03 * towers / 0.97  # the club house is 3% of towers plus itself
    assert status(inputs.edited(lambda c: _club_of(c, need - 20.0)).report(),
                  "Amenities (club house)") is Z.FAIL
    assert status(inputs.edited(lambda c: _club_of(c, need + 0.1)).report(),
                  "Amenities (club house)") is Z.PASS


def test_the_deduction_kinds_are_what_the_master_plan_rule_reads():
    assert {k.value for k in DeductionKind} >= {"SURRENDER", "ACQUISITION", "TRANSFER"}
