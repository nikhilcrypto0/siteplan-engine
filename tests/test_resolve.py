"""ResolvedRules for a site (stream A1): the law in metres, every value with its clause, basis and
status, every open question an Interpretation, nothing about floors."""

import json

import pytest
from contract_fixtures import SITES, load
from legal_fixtures import make_site, nala
from pydantic import BaseModel
from shapely.geometry import box

from siteplan import heights
from siteplan import rules as rules_py
from siteplan.constraints import REGISTRY
from siteplan.constraints import Basis as ConstraintBasis
from siteplan.contracts import ResolvedRules
from siteplan.contracts.common import Basis, FacilityUse, Provenance, Status, digest
from siteplan.contracts.resolved_rules import (
    ALL,
    AMENITY_SHARE,
    CIRCULATION_IN_SETBACK,
    FIRE_TURNING_RADIUS,
    MIXED_HEIGHT_SPACING,
    OPEN_SPACE_BASIS,
    OPEN_SPACE_OTHER_USES,
    REQUIRED_INTERPRETATIONS,
    STILT_IN_RULE_HEIGHT,
    TOT_LOT_SURFACE,
    Applicability,
    BandKind,
    Eligibility,
    HeightMeasure,
    LimitBound,
    OrderRead,
    RuleValue,
    SiteFact,
    TableVColumn,
    WhenOpen,
)
from siteplan.legal.readings import (
    CELLAR_EXTRA_SETBACK,
    ROAD_IN_WATER_BUFFER,
    TABLE_IV_ROAD_WIDTH,
)
from siteplan.legal.resolve import AIRPORT_CLAUSE, resolve, rules_digest

TEST_CLASS = "normative"
PLOT = box(0, 0, 150, 120)  # 18,000 m²: a group development scheme, a high-rise plot
OPEN_EVERY_WAY = {STILT_IN_RULE_HEIGHT, OPEN_SPACE_BASIS, CIRCULATION_IN_SETBACK, TOT_LOT_SURFACE,
                  OPEN_SPACE_OTHER_USES}


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def _values(node, path=""):
    """Every RuleValue in a model, with its dotted path."""
    if isinstance(node, RuleValue):
        yield path, node
    elif isinstance(node, BaseModel):
        for name in type(node).model_fields:
            yield from _values(getattr(node, name), f"{path}.{name}" if path else name)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _values(item, f"{path}[{i}]")
    elif isinstance(node, dict):
        for key, item in node.items():
            yield from _values(item, f"{path}[{key}]")


def _limits(rules: ResolvedRules, measure: HeightMeasure):
    return [limit for limit in rules.height.limits if limit.measure is measure]


# --- Criterion 2: heights are metres, never floors --------------------------------------------


@pytest.mark.parametrize("name", SITES)
def test_the_rules_carry_no_floor_count_anywhere(name):
    rules = resolve(load(name, "CanonicalSiteModel"))
    assert not [k for k in _keys(json.loads(rules.model_dump_json())) if "floor" in k.lower()]
    assert {limit.measure for limit in rules.height.limits} <= set(HeightMeasure)
    assert all(limit.max_m is None or isinstance(limit.max_m, float)
               for limit in rules.height.limits)


# --- Criterion 3: every value says where it comes from; every open question is a reading ------


@pytest.mark.parametrize("name", SITES)
def test_every_rule_value_has_its_clause_basis_and_status(name):
    rules = resolve(load(name, "CanonicalSiteModel"))
    values = list(_values(rules))
    assert len(values) > 40
    for path, value in values:
        assert value.clause.strip(), path
        assert isinstance(value.basis, Basis) and isinstance(value.status, Provenance), path
        if value.basis is Basis.LEGAL_RULE:
            assert "G.O." in value.clause or "NBC" in value.clause, f"{path}: {value.clause}"
    for item in (*rules.height.bands, *rules.height.limits):
        assert item.clause.strip() and isinstance(item.status, Provenance)


@pytest.mark.parametrize("name", SITES)
def test_the_required_readings_are_carried_and_the_five_open_ones_are_all(name):
    rules = resolve(load(name, "CanonicalSiteModel"))
    ids = [i.id for i in rules.interpretations]
    assert set(REQUIRED_INTERPRETATIONS) <= set(ids) and len(ids) == len(set(ids))
    for open_reading in OPEN_EVERY_WAY:
        reading = rules.interpretation(open_reading)
        assert reading.selected == ALL and reading.status is Provenance.UNVERIFIED
        assert rules.readings(open_reading) == list(reading.alternatives)
    for reading in rules.interpretations:
        assert len(reading.alternatives) >= 2 and reading.sources and reading.settles
        if reading.selected != ALL:
            assert reading.status is Provenance.ASSUMED_FOR_TEST, reading.id
    # the rest carry a reading
    assert {i.id for i in rules.interpretations if i.selected == ALL} == OPEN_EVERY_WAY


# What constraints.py calls UNRESOLVED_INTERPRETATION, by the start of its sentence, and the
# reading that carries it. A new open reading in the audit fails here until it is carried.
AUDITED_READINGS = {
    "The building's height, which picks the Table IV row": STILT_IN_RULE_HEIGHT,
    "Whether internal roads, driveways and fire lanes may run inside": CIRCULATION_IN_SETBACK,
    "The gap between two blocks of different heights": MIXED_HEIGHT_SPACING,
    "The site area the 10% is taken of": OPEN_SPACE_BASIS,
    "Whether a road or a fire lane may run inside a water buffer": ROAD_IN_WATER_BUFFER,
    "Where the 9 m turning radius is measured": FIRE_TURNING_RADIUS,
    "The amenities (club house) area as a share of the built-up area": AMENITY_SHARE,
    "The extra cellar setback is applied to every level": CELLAR_EXTRA_SETBACK,
}


def test_every_reading_the_audit_leaves_open_is_carried_as_an_interpretation():
    rules = resolve(load("rectangle", "CanonicalSiteModel"))
    carried = {i.id for i in rules.interpretations}
    open_ones = [c.what for c in REGISTRY if c.basis is ConstraintBasis.UNRESOLVED_INTERPRETATION]
    for what in open_ones:
        reading = next((r for start, r in AUDITED_READINGS.items() if what.startswith(start)), None)
        assert reading in carried, f"carry this open reading in legal/readings.py: {what}"


def test_a_rule_value_resting_on_an_open_reading_points_at_one():
    """A value whose basis is an unresolved reading is one the rules explain with an
    Interpretation (the open Table V column is the jurisdiction's, not a reading)."""
    rules = resolve(load("rectangle", "CanonicalSiteModel"))
    resting = {path for path, value in _values(rules)
               if value.basis is Basis.UNRESOLVED_INTERPRETATION}
    explained_by = {"amenities.share_of_built_up": AMENITY_SHARE}
    assert resting == set(explained_by)
    assert set(explained_by.values()) <= {i.id for i in rules.interpretations}
    assert rules.amenities.share_interpretation == AMENITY_SHARE


# --- Criterion 4, as unit tests: the road sets the height by Table IV -------------------------


@pytest.mark.parametrize(("road_m", "top"), [
    (12.0, 24.0), (17.99, 24.0), (18.0, 30.0), (18.288, 30.0), (23.99, 30.0), (24.0, 45.0),
    (29.99, 45.0)])
def test_table_iv_by_the_roads_legal_width(road_m, top):
    limit, = _limits(resolve(make_site(PLOT, road_m=road_m)), HeightMeasure.RULE_HEIGHT)
    assert (limit.id, limit.bound, limit.max_m) == ("table_iv_road", LimitBound.BOUNDED, top)
    assert limit.inclusive and limit.clause == rules_py.TABLE_IV_CLAUSE
    assert limit.status is Provenance.USER_CONFIRMED and limit.condition is None
    assert limit.applicability is Applicability.APPLIES
    assert limit.evaluate(top) is Status.PASS and limit.evaluate(top + 0.01) is Status.FAIL


def test_a_60_ft_road_serves_30_m_and_the_next_band_needs_24_m_of_road():
    limit, = _limits(resolve(make_site(PLOT, road_m=18.288)), HeightMeasure.RULE_HEIGHT)
    assert limit.max_m == 30.0
    assert "serves buildings up to 30 m" in limit.reason and "needs 24 m of road" in limit.reason


@pytest.mark.parametrize(("status", "row", "expected"), [
    ("VERIFIED", "CERTIFIED_ROW", Provenance.VERIFIED),
    ("USER_CONFIRMED", "DECLARED_ON_SITE_PLAN", Provenance.USER_CONFIRMED),
    ("UNVERIFIED", "UNVERIFIED_DRAWING_VALUE", Provenance.UNVERIFIED)])
def test_the_limit_is_as_trusted_as_the_roads_width(status, row, expected):
    limit, = _limits(resolve(make_site(PLOT, road_m=12.38, road_status=status, row_status=row)),
                     HeightMeasure.RULE_HEIGHT)
    assert limit.max_m == 24.0 and limit.status is expected
    assert row in limit.reason  # the road says how its width is known


def test_a_drawing_value_road_settles_no_height_and_still_holds_heights_back():
    """Suchitra's case: a limit on an unconfirmed width settles nothing either way, and no
    generator offers a height beyond it."""
    limit, = _limits(resolve(make_site(PLOT, road_m=12.38, road_status="UNVERIFIED",
                                       row_status="UNVERIFIED_DRAWING_VALUE")),
                     HeightMeasure.RULE_HEIGHT)
    assert limit.evaluate(24.0) is Status.UNVERIFIED and limit.evaluate(27.0) is Status.UNVERIFIED
    assert limit.beyond(27.0) and not limit.beyond(24.0)


def test_a_road_under_the_first_row_prohibits_a_high_rise_and_permits_nothing_lower():
    """PLOT is a group development scheme, which rule 8(b) asks 12 m of road for at every height:
    on 11.9 m no band below 21 m is permitted either, which is what the Table III bands say."""
    rules = resolve(make_site(PLOT, road_m=11.9))
    limit, = _limits(rules, HeightMeasure.RULE_HEIGHT)
    assert (limit.bound, limit.max_m, limit.inclusive) == (LimitBound.BOUNDED, 21.0, False)
    assert "Table III" in limit.reason and limit.status is Provenance.USER_CONFIRMED
    assert limit.evaluate(15.0) is Status.PASS and limit.evaluate(21.0) is Status.FAIL
    high_rise = rules.height.high_rise
    assert high_rise.eligibility is Eligibility.PROHIBITED
    assert [g.id for g in high_rise.grounds if g.met is False] == ["road_width"]
    assert "permits nothing below it" in high_rise.note
    low = [b for b in rules.height.bands if b.kind is BandKind.NON_HIGH_RISE]
    assert low and {b.permission for b in low} == {Eligibility.PROHIBITED}  # the 12 m is not met
    assert rules.height.permissible_non_high_rise(include_unverified=True) is None
    assert {rules.height.band_permission(b) for b in rules.height.bands} == {
        Eligibility.PROHIBITED}
    assert rules.height.band_for(15.0).modelled is True


def test_a_road_that_meets_every_row_sets_no_limit_and_says_so():
    limit, = _limits(resolve(make_site(PLOT, road_m=30.0)), HeightMeasure.RULE_HEIGHT)
    assert limit.bound is LimitBound.UNBOUNDED and limit.max_m is None
    assert "no height limit" in limit.reason and limit.status is Provenance.USER_CONFIRMED
    assert limit.evaluate(90.0) is Status.PASS


def test_an_unknown_road_width_is_reported_not_guessed():
    rules = resolve(make_site(PLOT, road_m=None))
    limit, = _limits(rules, HeightMeasure.RULE_HEIGHT)
    assert limit.bound is LimitBound.NOT_EVALUATED and limit.status is Provenance.UNVERIFIED
    assert "not given" in limit.reason
    assert rules.height.high_rise.eligibility is Eligibility.UNVERIFIED


def test_a_master_plan_width_is_a_second_limit_and_an_open_reading():
    rules = resolve(make_site(PLOT, road_m=12.0, master_plan_m=18.0))
    existing, planned = _limits(rules, HeightMeasure.RULE_HEIGHT)
    assert (existing.max_m, planned.max_m) == (24.0, 30.0)
    assert existing.condition.fact is planned.condition.fact is (
        SiteFact.MASTER_PLAN_LAND_SURRENDERED)
    assert (existing.condition.holds_when, planned.condition.holds_when) == (False, True)
    assert existing.applicability is planned.applicability is Applicability.UNKNOWN
    assert existing.evaluate(27.0) is Status.UNVERIFIED  # within one reading, beyond the other
    assert rules.interpretation(TABLE_IV_ROAD_WIDTH).selected == ALL
    plain = resolve(make_site(PLOT, road_m=12.0))
    assert TABLE_IV_ROAD_WIDTH not in {i.id for i in plain.interpretations}


# --- The other height limits and the high-rise minimum ----------------------------------------


@pytest.mark.parametrize(("dead_end", "applicability", "at_33_m"), [
    (None, Applicability.UNKNOWN, Status.UNVERIFIED),
    (True, Applicability.APPLIES, Status.FAIL),
    (False, Applicability.DOES_NOT_APPLY, Status.INFO)])
def test_nbc_30_m_on_the_physical_height_applies_only_if_the_road_ends_at_the_plot(
        dead_end, applicability, at_33_m):
    limit, = _limits(resolve(make_site(PLOT, dead_end=dead_end)), HeightMeasure.PHYSICAL_HEIGHT)
    assert (limit.id, limit.max_m) == ("dead_end", rules_py.DEAD_END_MAX_HEIGHT_M)
    assert limit.condition.fact is SiteFact.ROAD_ENDS_AT_PLOT and limit.condition.holds_when
    assert limit.applicability is applicability and limit.clause == rules_py.DEAD_END_CLAUSE
    assert limit.evaluate(33.0) is at_33_m
    assert limit.evaluate(30.0) is (Status.INFO if dead_end is False else Status.PASS)
    assert limit.beyond(33.0) is (dead_end is True)  # an unsettled end is offered, labelled


def test_the_airport_height_is_unverified_without_coordinates_and_still_not_computed_with():
    for coordinates in (None, (17.5, 78.4)):
        limit, = _limits(resolve(make_site(PLOT, coordinates=coordinates)), HeightMeasure.AMSL)
        assert limit.bound is LimitBound.NOT_EVALUATED and limit.status is Provenance.UNVERIFIED
        assert limit.evaluate(30.0) is Status.UNVERIFIED
    assert AIRPORT_CLAUSE == heights.AIRPORT_CLAUSE


def test_a_plot_under_2000_m2_cannot_take_a_high_rise():
    rules = resolve(make_site(box(0, 0, 40, 40)))  # 1,600 m²
    high_rise = rules.height.high_rise
    assert high_rise.eligibility is Eligibility.PROHIBITED
    plot = next(g for g in high_rise.grounds if g.id == "plot_size")
    assert plot.met is False and plot.clause == rules_py.MIN_HIGH_RISE_PLOT_CLAUSE
    assert plot.status is Provenance.USER_CONFIRMED
    assert all(lim.clause != rules_py.MIN_HIGH_RISE_PLOT_CLAUSE for lim in rules.height.limits)
    enough = resolve(make_site(box(0, 0, 50, 40)))  # 2,000 m² exactly
    assert enough.height.high_rise.eligibility is Eligibility.ALLOWED


def test_a_site_just_short_by_road_widening_is_unverified_not_failed():
    """Rule 7(a)(iii) lets a site left short by road widening count when the shortfall is
    small; the engine does not model it, so near the minimum with land given up it says so."""
    rules = resolve(make_site(box(0, 0, 45, 42), surrendered=300.0))  # net 1,890, gross 2,190
    plot = next(g for g in rules.height.high_rise.grounds if g.id == "plot_size")
    assert plot.met is False and plot.status is Provenance.UNVERIFIED
    assert "7(a)(iii)" in plot.required
    assert rules.height.high_rise.eligibility is Eligibility.UNVERIFIED


def test_every_height_has_one_band_and_exactly_21_m_is_a_high_rise():
    rules = resolve(make_site(PLOT))
    assert rules.height.high_rise_from_m.value == 21.0
    bands = rules.height.bands
    low, at, high = bands[:4], bands[4], bands[5:]
    assert [b.kind for b in low] == [BandKind.NON_HIGH_RISE] * 4  # Table III's lines, then open
    assert all(b.modelled for b in low)
    assert (low[-1].above_m, low[-1].up_to_m) == (18.0, 21.0)
    assert low[-1].above_inclusive is True and low[-1].up_to_inclusive is False
    assert (at.kind, at.above_m, at.up_to_m, at.min_road_m, at.setback_m, at.gap_m) == (
        BandKind.HIGH_RISE, 21.0, 21.0, 12.0, 7.0, 7.0)
    assert all(b.kind is BandKind.HIGH_RISE and b.modelled for b in high)
    table = [b for b in rules_py.TABLE_IV if b.above_m >= 21.0]
    assert [(b.above_m, b.up_to_m, b.min_road_m, b.setback_m, b.gap_m) for b in high] == [
        (t.above_m, t.up_to_m, t.min_road_m, t.min_open_space_m, t.min_open_space_m)
        for t in table]
    assert rules.height.band_for(3.0 + 6 * 3.0) is at  # stilt + 6 floors is 21 m


def test_the_open_space_rule_names_its_uses_and_keeps_the_rest_open():
    space = resolve(make_site(PLOT)).open_space
    assert space.qualifying_uses.value == [FacilityUse.GREENERY, FacilityUse.TOT_LOT,
                                           FacilityUse.SOFT_LANDSCAPE]
    assert space.qualifying_uses.clause == rules_py.OPEN_SPACE_CLAUSE


def test_the_line_clearances_and_the_ramp_fire_clearance_are_carried_as_read():
    rules = resolve(make_site(PLOT))
    assert (rules.electrical.ht_clearance_m.value, rules.electrical.lt_clearance_m.value) == (
        rules_py.ELECTRICAL_HT_CLEARANCE_M, rules_py.ELECTRICAL_LT_CLEARANCE_M)
    assert rules.parking.ramp_fire_clearance_m.value == rules_py.RAMP_FIRE_CLEARANCE_M
    assert rules.parking.ramp_fire_clearance_m.clause == rules_py.RAMP_CLAUSE


# --- Criterion 9 (the quantity): open space under every reading of the area -------------------


def test_the_open_space_asked_is_given_under_each_reading_of_the_area():
    rules = resolve(make_site(box(0, 0, 150, 100), surrendered=450.0))  # gross 15,450, net 15,000
    asked = rules.open_space.requirement_sqm_by_reading
    share = rules.open_space.share.value
    assert share == 0.10
    assert asked == pytest.approx({"gross_before_surrender": share * 15_450,
                                   "gross_after_surrender": share * 15_000,
                                   "net_after_surrender": share * 15_000})
    assert set(asked) == set(rules.interpretation(OPEN_SPACE_BASIS).alternatives)
    assert rules.open_space.over_and_above_setbacks.clause == rules_py.OPEN_SPACE_CLAUSE
    assert rules.open_space.buffer_may_count.clause == rules_py.WATER_BUFFER_CLAUSE


def test_a_deduction_that_is_not_a_surrender_does_not_move_the_after_surrender_area():
    site = make_site(box(0, 0, 150, 100), surrendered=450.0)
    data = site.model_dump(mode="json")
    data["ownership"]["deductions"][0]["kind"] = "ACQUISITION"
    rules = resolve(type(site).model_validate(data))
    asked = rules.open_space.requirement_sqm_by_reading
    assert asked["gross_after_surrender"] == pytest.approx(asked["gross_before_surrender"])
    assert asked["net_after_surrender"] < asked["gross_after_surrender"]


# --- Jurisdiction and Table V -----------------------------------------------------------------


@pytest.mark.parametrize(("authority", "cure", "status", "column", "share"), [
    ("HMDA", False, "USER_CONFIRMED", TableVColumn.ELSEWHERE, 20.0),
    ("CMC", True, "USER_CONFIRMED", TableVColumn.GHMC_OR_CURE, 30.0),
    ("GHMC", None, "USER_CONFIRMED", TableVColumn.GHMC_OR_CURE, 30.0)])
def test_a_settled_jurisdiction_takes_its_table_v_column(authority, cure, status, column, share):
    rules = resolve(make_site(PLOT, authority=authority, inside_cure=cure,
                              jurisdiction_status=status))
    assert rules.jurisdiction.table_v_column is column
    assert rules.parking.share_pct.value == share
    assert rules.parking.share_pct_by_column == {TableVColumn.GHMC_OR_CURE: 30.0,
                                                 TableVColumn.ELSEWHERE: 20.0}


@pytest.mark.parametrize("site", [
    make_site(PLOT, authority="CMC", inside_cure=True, jurisdiction_status="UNVERIFIED"),
    make_site(PLOT, authority=None, inside_cure=False),
    make_site(PLOT, authority="HMDA", inside_cure=None)], ids=["unconfirmed", "no authority",
                                                               "cure unknown"])
def test_an_open_jurisdiction_leaves_the_parking_share_open_unless_told_to_be_conservative(site):
    rules = resolve(site)
    assert rules.jurisdiction.table_v_column is TableVColumn.OPEN
    assert rules.parking.share_pct is None
    assert rules.jurisdiction.when_open is WhenOpen.STOP
    cautious = resolve(site, when_open=WhenOpen.CONSERVATIVE)
    share = cautious.parking.share_pct
    assert share.value == 30.0 and share.status is Provenance.ASSUMED_FOR_TEST
    assert share.basis is Basis.UNRESOLVED_INTERPRETATION and "CONSERVATIVE" in share.note
    assert cautious.jurisdiction.table_v_column is TableVColumn.OPEN  # still open, and labelled


# --- Readings a test profile may pick ---------------------------------------------------------


def test_a_test_profile_picks_a_reading_and_it_is_recorded_as_assumed_for_the_test():
    rules = resolve(make_site(PLOT), selections={STILT_IN_RULE_HEIGHT: "not_counted",
                                                 OPEN_SPACE_BASIS: "net_after_surrender"})
    stilt = rules.interpretation(STILT_IN_RULE_HEIGHT)
    assert stilt.selected == "not_counted" and stilt.status is Provenance.ASSUMED_FOR_TEST
    assert rules.readings(STILT_IN_RULE_HEIGHT) == ["not_counted"]
    assert "test profile" in stilt.sources[-1]
    assert rules.readings(OPEN_SPACE_BASIS) == ["net_after_surrender"]
    assert rules.interpretation(CIRCULATION_IN_SETBACK).selected == ALL  # untouched


def test_a_selection_must_name_a_reading_the_site_carries():
    site = make_site(PLOT)
    with pytest.raises(ValueError, match="no open reading 'stilt'"):
        resolve(site, selections={"stilt": "counted"})
    with pytest.raises(ValueError, match="'sometimes' is not a reading of stilt_in_rule_height"):
        resolve(site, selections={STILT_IN_RULE_HEIGHT: "sometimes"})
    with pytest.raises(ValueError, match=TABLE_IV_ROAD_WIDTH):  # no master-plan width here
        resolve(site, selections={TABLE_IV_ROAD_WIDTH: "existing"})
    again = resolve(site, selections={STILT_IN_RULE_HEIGHT: ALL})
    assert again.interpretation(STILT_IN_RULE_HEIGHT).status is Provenance.UNVERIFIED


# --- The rest of what the contract asks -------------------------------------------------------


def test_a_group_development_scheme_and_no_five_acre_amenity_share():
    """The 5% of site area for amenities above 5 acres is rule 9(o) and 10(i), row and cluster
    housing: recorded in rules.py, never carried in a group scheme's rules."""
    big = resolve(make_site(box(0, 0, 200, 110)))  # 22,000 m², above 5 acres
    small = resolve(make_site(box(0, 0, 60, 50)))  # 3,000 m²
    assert big.category.group_development.value and not small.category.group_development.value
    assert big.circulation.applies.value and not small.circulation.applies.value
    assert big.category.group_development.status is Provenance.EXTRACTED  # as trusted as the area
    text = big.model_dump_json()
    assert "above_5_acres" not in text and "large_project" not in text
    assert "rule 9(o)" in rules_py.LARGE_PROJECT_AMENITY_CLAUSE


def test_the_orders_are_listed_with_how_each_was_read_and_the_unread_ones_named():
    orders = {o.id: o.read for o in resolve(make_site(PLOT)).orders}
    assert orders["G.O.Ms.No.168 of 2012"] is OrderRead.TEXT
    assert orders["G.O.Ms.No.7 of 2016"] is OrderRead.TEXT
    for scanned in ("G.O.Ms.No.50 of 2019", "G.O.Ms.No.65 of 2019", "G.O.Ms.No.95 of 2026",
                    "G.O.Ms.No.264 of 2019", "G.O.Ms.No.14 of 2022", "G.O.Ms.No.103 of 2021"):
        assert orders[scanned] is OrderRead.SCAN
    assert orders["G.O.Ms.No.49 of 2023"] is OrderRead.TEXT
    unread = {name for name, read in orders.items() if read is OrderRead.UNREAD}
    # G.O.245 of 2012 may have changed rule 5: Table III stands on the order as first issued
    assert {"G.O.Ms.No.245 of 2012", "G.O.Ms.No.16 of 2026", "TS-bPASS G.O.201"} <= unread


def test_the_45_t_loading_is_carried_unverified_and_the_water_widths_are_the_rules():
    rules = resolve(make_site(PLOT))
    assert rules.fire.load_t.value == 45.0 and rules.fire.load_t.status is Provenance.UNVERIFIED
    assert rules.water.buffer_m_by_class.value == rules_py.WATER_BUFFER_M
    assert rules.fire.dead_end_max_physical_m.value == rules_py.DEAD_END_MAX_HEIGHT_M


def test_the_rules_survive_json_name_their_site_and_change_with_a_rule_value(monkeypatch):
    site = make_site(PLOT, water=[nala([[(75, -5), (75, 125)]])])
    rules = resolve(site)
    assert ResolvedRules.model_validate_json(rules.model_dump_json()) == rules
    assert rules.site_ref == digest(site)
    assert resolve(site) == rules  # deterministic
    before = rules_digest()
    monkeypatch.setattr(rules_py, "HIGH_RISE_THRESHOLD_M", 22.0)
    assert rules_digest() != before


@pytest.mark.parametrize("name", SITES)
def test_the_real_producer_agrees_with_the_p0_fixtures_on_what_consumers_read(name):
    """Streams C and D started from tests/contract_fixtures, built by a stand-in. The ids of the
    readings, the bands, the quantities and the height limits they read must be the same here;
    clauses and statuses are where this producer is more exact, and are not compared."""
    site = load(name, "CanonicalSiteModel")
    ours, theirs = resolve(site), load(name, "ResolvedRules")
    for reading in REQUIRED_INTERPRETATIONS:
        mine, fixture = ours.interpretation(reading), theirs.interpretation(reading)
        assert (mine.selected, set(mine.alternatives)) == (fixture.selected,
                                                           set(fixture.alternatives)), reading
    keys = ("above_m", "up_to_m", "above_inclusive", "up_to_inclusive", "kind", "modelled",
            "min_road_m", "setback_m", "gap_m", "measure", "front_setback_m", "permission",
            "green_strip_m", "green_strip_sides")
    assert [b.model_dump(include=set(keys)) for b in ours.height.bands] == [
        b.model_dump(include=set(keys)) for b in theirs.height.bands]
    assert ours.open_space.requirement_sqm_by_reading == pytest.approx(
        theirs.open_space.requirement_sqm_by_reading)
    limit_keys = ("id", "measure", "bound", "max_m", "inclusive", "applicability")
    assert [lim.model_dump(include=set(limit_keys)) for lim in ours.height.limits] == [
        lim.model_dump(include=set(limit_keys)) for lim in theirs.height.limits]
    assert ours.height.high_rise.eligibility is theirs.height.high_rise.eligibility
    assert ours.open_space.qualifying_uses.value == theirs.open_space.qualifying_uses.value
    assert ours.jurisdiction.table_v_column == theirs.jurisdiction.table_v_column
    assert ours.parking.share_pct.value == theirs.parking.share_pct.value
    assert ours.category.group_development.value == theirs.category.group_development.value
    assert ours.fire.dead_end_max_physical_m.value == theirs.fire.dead_end_max_physical_m.value
