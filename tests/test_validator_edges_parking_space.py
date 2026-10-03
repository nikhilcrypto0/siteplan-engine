"""The edges of parking and the open space: a bay a little too narrow, one on a road no lane
shadows, a pocket a few square metres short, ground that counts only where nothing else already
takes it. Each pins a survivor of a mutation test of the first tests, which hid these rules behind
the fire bands that happen to stand beside every pocket and bay on the fixtures."""

import pytest
from shapely.ops import unary_union
from validator_helpers import check, fixture, move_tower, rectangle, select, status

from siteplan.contracts.candidate import SiteProgram
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    OPEN_SPACE_BASIS,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.validator import context
from siteplan.validator.parking import bay_standard, cellar_setback_m
from siteplan.validator.readings import COUNTED

TEST_CLASS = "normative"
Z = Status
BAYS = "Surface parking bays"
OPEN_SPACE = "Organized open space (tot-lot)"
COUNTING = f"open_space_counting_sqm[{STILT_IN_RULE_HEIGHT}=counted]"


def _clear(candidate):
    """Nothing on the plot but what a test draws next."""
    candidate.towers = []
    candidate.circulation.fire_hardstanding = []
    candidate.circulation.gates = []


def _counted(inputs):
    return inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))


# --- bays ------------------------------------------------------------------------------------


def _bay(*boxes, roads=False):
    def edit(candidate):
        _clear(candidate)
        if not roads:
            candidate.circulation.roads = []
        candidate.program = SiteProgram(bays=[rectangle(*b) for b in boxes])
    return edit


@pytest.mark.parametrize("bay", [(70.0, 12.0, 72.5, 16.0), (70.0, 12.0, 72.0, 17.0)])
def test_a_bay_too_short_or_too_narrow_for_a_car_is_no_bay(bay):
    c = check(fixture("rectangle").edited(_bay(bay)).report(), BAYS)
    assert c.finding.status is Z.FAIL and "too small for a car" in c.finding.measured


def test_a_bay_on_a_road_is_no_bay_even_where_no_fire_lane_shadows_the_road():
    c = check(fixture("rectangle").edited(_bay((5.0, 40.0, 7.5, 45.0), roads=True)).report(), BAYS)
    assert c.finding.status is Z.FAIL and "on a road or fire lane" in c.finding.measured


def test_a_bay_in_the_clear_ground_round_a_high_rise_is_no_bay_even_with_no_lane_there():
    def beside_t2(candidate):
        candidate.circulation.roads = []
        candidate.circulation.fire_hardstanding = []
        candidate.program = SiteProgram(bays=[rectangle(60.0, 24.0, 62.5, 29.0)])  # 5 m from T2
    c = check(fixture("rectangle").edited(beside_t2).report(), BAYS)
    assert c.finding.status is Z.FAIL and "in a fire lane's clear ground" in c.finding.measured


# --- the cellar's floor and cars ----------------------------------------------------------------


def test_the_cellar_setback_steps_at_the_tables_own_upper_size():
    rules = fixture("rectangle").rules
    table = rules.parking.cellar_setback_by_site_sqm.value
    up_to = table[0][0]
    assert cellar_setback_m(rules, up_to, 1) == table[0][1]
    assert cellar_setback_m(rules, up_to + 0.01, 1) == table[1][1]


def test_a_cellar_level_has_the_outline_less_cores_ramp_and_the_utilities_share():
    inputs = fixture("rectangle")
    c = inputs.candidate
    outline = unary_union([s.to_shapely() for s in c.program.cellars.outline])
    cores = unary_union([t.world(z.shape.to_shapely()) for t in c.towers
                         for z in c.prototype(t.prototype_id).core_zones])
    ramps = unary_union([r.to_shapely() for r in c.program.ramps])
    utilities = inputs.brief.firm_standards.cellar_utilities_share.value
    expected = outline.difference(unary_union([cores, ramps])).area * (1 - utilities)
    got = inputs.report().recomputed.quantities["parking_cellar_sqm_per_level"]
    assert got == pytest.approx(expected, abs=0.5)


def test_the_cars_that_fit_count_the_stilt_the_cellars_and_the_surface_bays():
    q = fixture("rectangle").report().recomputed.quantities
    assert q["parking_cars"] == q["parking_stilt_cars"] + q["parking_cellar_cars"] + 10


def test_the_visitors_share_is_taken_of_what_table_v_asks():
    inputs = fixture("rectangle")
    report = inputs.report()
    asked = report.recomputed.quantities["parking_required_sqm[ELSEWHERE]"]
    need = inputs.rules.parking.visitors_fraction.value * asked
    assert f"{need:,.0f} m²" in check(report, "Visitors' parking").finding.required


# --- ramps ---------------------------------------------------------------------------------


def _ramps(*boxes):
    def edit(candidate):
        candidate.program.ramps = [rectangle(*b) for b in boxes]
    return edit


def test_parking_a_few_cars_short_fails_where_a_rounding_does_not():
    """Table V asked 20 m² short of what is provided is short; 0.4 m² short is rounding."""
    inputs = fixture("rectangle")
    ctx = context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)
    q = inputs.report().recomputed.quantities
    _, _, sqm_per_car = bay_standard(ctx)
    floor = (q["parking_stilt_sqm"] + 10 * 12.5
             + q["parking_cellar_levels"] * q["parking_cellar_sqm_per_level"])
    provided = min(floor, q["parking_cars"] * sqm_per_car)

    def needing(sqm):
        def edit(rules):
            rules.parking.share_pct.value = 100.0 * sqm / q["built_up_sqm"]
        return edit
    assert status(inputs.with_rules(needing(provided + 20.0)).report(), "Parking (Table V)"
                  ) is Z.FAIL
    assert status(inputs.with_rules(needing(provided + 0.4)).report(), "Parking (Table V)"
                  ) is Z.PASS


def test_two_ramps_must_each_be_3_6_m_wide():
    report = fixture("rectangle").edited(
        _ramps((127.7, 62.87, 131.3, 86.86), (134.0, 62.87, 136.0, 86.86))).report()
    c = check(report, "Cellar ramp")
    assert c.finding.status is Z.FAIL and "width" in c.finding.measured


def test_every_ramp_must_be_long_enough_for_the_slope_not_only_one_of_them():
    report = fixture("rectangle").edited(
        _ramps((127.7, 62.87, 131.3, 86.86), (134.0, 62.87, 137.6, 72.0))).report()
    c = check(report, "Cellar ramp")
    assert c.finding.status is Z.FAIL and "too short for a 1 in 8 slope" in c.finding.measured


def test_a_ramp_2_m_from_a_road_has_its_top_off_it():
    c = check(fixture("rectangle").edited(_ramps((127.7, 64.9, 133.1, 87.0))).report(),
              "Cellar ramp")
    assert c.finding.status is Z.FAIL and "top not on a road" in c.finding.measured


# --- the open space ------------------------------------------------------------------------


def _pockets(*boxes, club=None):
    def edit(candidate):
        _clear(candidate)
        candidate.circulation.roads = []
        candidate.program = SiteProgram(open_space=[rectangle(*b) for b in boxes])
        if club is not None:
            candidate.program.club_house = club
    return edit


def _counted_sqm(inputs):
    return inputs.report().recomputed.quantities[COUNTING]


@pytest.mark.parametrize("pocket, counts", [
    ((60.0, 40.0, 70.0, 44.0), 0.0),  # 40 m²: under the 50 m² of a pocket
    ((60.0, 40.0, 70.0, 45.0), 50.0),  # 50 m² exactly
    ((60.0, 40.0, 62.5, 70.0), 0.0),  # 75 m² but 2.5 m wide: under the 3 m
    ((60.0, 40.0, 63.0, 70.0), 90.0)])  # 3 m wide exactly
def test_a_pocket_counts_from_50_m2_and_3_m_wide(pocket, counts):
    assert _counted_sqm(fixture("rectangle").edited(_pockets(pocket))) == pytest.approx(counts)


def test_open_space_drawn_over_the_club_house_is_the_club_houses_ground_not_open_space():
    inputs = fixture("rectangle")
    club = inputs.candidate.program.club_house.model_copy(
        update={"shape": rectangle(40.0, 40.0, 70.0, 60.0)})
    assert _counted_sqm(inputs.edited(_pockets((45.0, 45.0, 65.0, 55.0), club=club))) == 0.0


def test_ground_between_two_blocks_kept_apart_by_the_table_is_not_open_space():
    """T2 and T3 16 m apart: the 4 m between 6 m of clear ground each side holds a 2 m strip
    within the 9 m of both, which is the gap between the blocks and no pocket: what is left on
    either side is under 3 m wide."""
    def apart(candidate):
        candidate.towers = [t for t in candidate.towers if t.name in ("T2", "T3")]
        move_tower(candidate, "T3", 7.0, 0.0)
        candidate.circulation.roads, candidate.circulation.fire_hardstanding = [], []
        candidate.program = SiteProgram(open_space=[rectangle(89.0, 33.0, 93.0, 51.0)])
    assert _counted_sqm(_counted(fixture("rectangle")).edited(apart)) == 0.0

    def gap_not_excluded(rules):
        rules.open_space.block_gaps_excluded.value = False
    open_gap = _counted(fixture("rectangle")).with_rules(gap_not_excluded).edited(apart)
    assert _counted_sqm(open_gap) == pytest.approx(72.0, abs=0.5)  # the 4 m strip, if gaps counted


def test_the_open_space_a_generator_claims_is_held_to_the_least_any_reading_gives():
    """A pocket along the south: 9 m of setback takes 0.8 m of it if the stilt counts, 8 m none.
    The generator claims all of it."""
    def along_the_south(candidate):
        candidate.circulation.roads, candidate.circulation.fire_hardstanding = [], []
        candidate.program = SiteProgram(open_space=[rectangle(20.0, 8.2, 130.0, 12.0)])
        candidate.metrics.open_space_sqm = 110.0 * 3.8
    report = fixture("rectangle").edited(along_the_south).report()
    claim = next(d for d in report.cross_checks if d.item == "open space")
    assert claim.blocks_pass


def test_open_space_a_few_m2_short_of_the_share_fails():
    """1,600 m² of ground that counts, against a share the rules put at 1,603 m²."""
    def pocket(candidate):
        candidate.circulation.roads, candidate.circulation.fire_hardstanding = [], []
        candidate.program = SiteProgram(
            open_space=[rectangle(10.0, 10.0, 140.0, 10.0 + 1600 / 130)])

    def asking(sqm):
        def edit(rules):
            select(rules, OPEN_SPACE_BASIS, "net_after_surrender")
            rules.open_space.requirement_sqm_by_reading["net_after_surrender"] = sqm
        return edit
    base = _counted(fixture("rectangle")).edited(pocket)
    c = check(base.with_rules(asking(1603.0)).report(), OPEN_SPACE)
    assert c.finding.status is Z.FAIL and "1,600.0 m² counts" in c.finding.measured
    assert status(base.with_rules(asking(1599.9)).report(), OPEN_SPACE) is Z.PASS


def test_where_the_setback_is_not_known_the_share_cannot_be_passed():
    def low(candidate):
        for t in candidate.towers:
            t.floors_above_stilt = 4  # 15 m
    assert status(fixture("rectangle").edited(low).report(), OPEN_SPACE) is Z.UNVERIFIED
