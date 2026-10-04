"""The permanent contracts: what each may hold, the invariants they enforce, and the fixtures
every stream starts from (tests/contract_fixtures)."""

import json
import math
from pathlib import Path

import pytest
from contract_fixtures import SITES, load
from contract_fixtures.build import SITES as SPECS
from contract_fixtures.build import project as fixture_project
from contract_fixtures.rules_and_envelope import envelope, resolved_rules
from pydantic import ValidationError
from shapely.geometry import box

from siteplan.adapters import site_model
from siteplan.contracts import ALL_CONTRACTS, CONTRACTS_VERSION, schema_text
from siteplan.contracts.accounting import (
    DeductionKind,
    LayerKind,
    OwnershipReconciliation,
    PartitionLedger,
    Permit,
    PhysicalUse,
)
from siteplan.contracts.common import (
    Basis,
    FacilityUse,
    Finding,
    Provenance,
    Shape,
    Status,
    Surface,
)
from siteplan.contracts.design_brief import DesignMargins
from siteplan.contracts.resolved_rules import (
    ALL,
    CIRCULATION_IN_SETBACK,
    OPEN_SPACE_BASIS,
    OPEN_SPACE_OTHER_USES,
    READINGS,
    REQUIRED_INTERPRETATIONS,
    STILT_IN_RULE_HEIGHT,
    TOT_LOT_SURFACE,
    Applicability,
    BandKind,
    Eligibility,
    HeightLimit,
    HeightRules,
    HighRiseEligibility,
    LimitBound,
    ParkingMeasurement,
    Qualification,
    ResolvedRules,
)
from siteplan.contracts.validation import (
    Check,
    Discrepancy,
    Family,
    LegalVerdict,
    TargetCheck,
    ValidationReport,
    legal_verdict,
)

SCHEMAS = Path(__file__).parent.parent / "docs" / "contracts"
# What each of the three kinds of fact may not hold (property names anywhere in its schema).
FORBIDDEN = {
    "CanonicalSiteModel": {"setback_m", "gap_m", "min_road_m", "unit_mix", "floor_to_floor_m",
                           "stilt_height_m", "pareto", "objectives", "clause", "design_margins"},
    "ResolvedRules": {"unit_mix", "floor_to_floor_m", "stilt_height_m", "pareto", "objectives",
                      "max_tower_length_m", "boundary", "net_plot", "design_margins",
                      "setback_extra_m", "tower_gap_extra_m"},
    "DesignBrief": {"setback_m", "gap_m", "min_road_m", "clause", "boundary", "net_plot",
                    "legal_row_m", "authority", "inside_cure", "dead_end"},
}
# A facility's ground is judged from its stated use and surface, never from a flag or its name.
NOT_DECLARED = {"counts_as_open_space", "qualifies", "is_soft"}
SITE_FACT_SOURCES = {"SURVEY", "ARCHITECT", "DOCUMENT", "FIRM_FINISHED_PLAN", "TEST_PROFILE",
                     "ENGINE_DEFAULT", "FIRM_STANDARD"}


def _property_names(schema: dict) -> set[str]:
    names: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return names


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


@pytest.mark.parametrize("name", list(ALL_CONTRACTS))
def test_the_committed_schema_is_the_code(name):
    """docs/contracts is generated from the code (`siteplan schema`); regenerate on change."""
    committed = (SCHEMAS / f"{name}.schema.json").read_text()
    assert committed == schema_text(ALL_CONTRACTS[name]), "run: uv run siteplan schema"


@pytest.mark.parametrize("name", list(FORBIDDEN))
def test_site_facts_law_and_intent_stay_apart(name):
    found = _property_names(ALL_CONTRACTS[name].model_json_schema()) & FORBIDDEN[name]
    assert not found, f"{name} holds another kind of fact: {sorted(found)}"


def test_the_rules_carry_no_floor_count():
    names = _property_names(ALL_CONTRACTS["ResolvedRules"].model_json_schema())
    assert not [n for n in names if "floor" in n], "heights are metres; floors are the brief's"
    for site in SITES:
        text = (Path(__file__).parent / "contract_fixtures" / site / "ResolvedRules.json")
        assert not [k for k in _keys(json.loads(text.read_text())) if "floor" in k]


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize("contract", list(ALL_CONTRACTS))
def test_every_fixture_validates_and_survives_json(site, contract):
    instance = load(site, contract)
    again = type(instance).model_validate_json(instance.model_dump_json())
    assert again == instance


@pytest.mark.parametrize("site", SITES)
def test_the_open_readings_are_carried_and_evaluated_every_way(site):
    rules = load(site, "ResolvedRules")
    assert {i.id for i in rules.interpretations} >= set(REQUIRED_INTERPRETATIONS)
    for open_reading in (STILT_IN_RULE_HEIGHT, OPEN_SPACE_BASIS, CIRCULATION_IN_SETBACK):
        assert rules.interpretation(open_reading).selected == ALL
    assert set(rules.open_space.requirement_sqm_by_reading) == set(
        rules.interpretation(OPEN_SPACE_BASIS).alternatives)


def test_the_open_space_denominator_is_not_resolved_to_one_area():
    rules = load("rectangle", "ResolvedRules")  # 450 m² surrendered
    asked = rules.open_space.requirement_sqm_by_reading
    assert asked["gross_before_surrender"] > asked["net_after_surrender"]
    assert asked["gross_after_surrender"] == pytest.approx(asked["net_after_surrender"])


@pytest.mark.parametrize("site", SITES)
def test_a_road_in_a_setback_is_conditional_never_simply_allowed(site):
    for source in (load(site, "BuildableEnvelope").rule_layers,
                   load(site, "CandidateLayout").rule_layers):
        for layer in source.of(LayerKind.SETBACK):
            for permission in layer.permits:
                if permission.use in (PhysicalUse.ROAD, PhysicalUse.FIRE_HARDSTANDING):
                    assert permission.permit is Permit.CONDITIONAL
                    assert permission.interpretation_ref == CIRCULATION_IN_SETBACK


def test_only_land_leaving_the_title_reduces_net_ownership():
    assert {k.value for k in DeductionKind} == {"SURRENDER", "ACQUISITION", "TRANSFER"}
    site = load("rectangle", "CanonicalSiteModel")
    own = site.ownership
    assert own.net_sqm.value == pytest.approx(own.gross_sqm.value - 450)
    data = own.model_dump(mode="json")
    data["deductions"][0]["kind"] = "SETBACK"
    with pytest.raises(ValidationError):
        OwnershipReconciliation.model_validate(data)


def test_a_setback_or_buffer_never_shrinks_the_net_site():
    """The nala's buffer takes no land out of the title: net is gross, and the buffer is a rule
    layer and a physical BUFFER_LAND entry, not a deduction."""
    site = load("nala_plot", "CanonicalSiteModel")
    assert site.ownership.deductions == []
    assert site.ownership.net_sqm.value == site.ownership.gross_sqm.value
    ledger = load("nala_plot", "PartitionLedger")
    assert ledger.net_area_sqm == pytest.approx(site.ownership.net_sqm.value)
    assert ledger.by_use()[PhysicalUse.BUFFER_LAND] > 0


def test_ownership_arithmetic_and_overlap_are_checked():
    own = load("rectangle", "CanonicalSiteModel").ownership.model_dump(mode="json")
    wrong = dict(own, net_sqm={**own["net_sqm"], "value": 14_000})
    with pytest.raises(ValidationError, match="not the"):
        OwnershipReconciliation.model_validate(wrong)
    twice = dict(own, deductions=own["deductions"] * 2, net_sqm={**own["net_sqm"],
                                                                 "value": 14_550})
    with pytest.raises(ValidationError, match="overlap"):
        OwnershipReconciliation.model_validate(twice)


@pytest.mark.parametrize("site", SITES)
def test_every_square_metre_is_counted_once(site):
    ledger = load(site, "PartitionLedger")
    net = load(site, "CanonicalSiteModel").net_plot.value
    assert ledger.problems(net) == []
    assert ledger.total_sqm() == pytest.approx(ledger.net_area_sqm, rel=0.005)


def test_a_road_that_is_also_fire_access_is_one_area_with_a_tag():
    ledger = load("rectangle", "PartitionLedger")
    roads = [e for e in ledger.entries if e.use is PhysicalUse.ROAD]
    assert roads and all("FIRE_ACCESS" in e.tags for e in roads)
    assert "FIRE_ACCESS" not in {e.use.value for e in ledger.entries}


def test_overlapping_or_unexplained_ground_is_refused():
    a, b = Shape.from_shapely(box(0, 0, 10, 10)), Shape.from_shapely(box(5, 0, 15, 10))
    ledger = PartitionLedger(net_area_sqm=150, entries=[
        {"use": "TOWER", "shapes": [a], "area_sqm": 100},
        {"use": "ROAD", "shapes": [b], "area_sqm": 100}])
    assert any("overlap" in p for p in ledger.problems())
    with pytest.raises(ValidationError, match="why"):
        PartitionLedger(net_area_sqm=100, entries=[
            {"use": "UNALLOCATED", "shapes": [a], "area_sqm": 100}])


def test_the_envelope_reports_a_narrow_arm_and_does_not_judge_it():
    env = load("l_plot_with_arm", "BuildableEnvelope")
    widths = [r.max_inscribed_width_m for w in env.width_profiles for r in w.regions]
    assert any(abs(width - 24.0) < 0.5 for width in widths)
    assert env.exclusions == []
    text = env.model_dump_json().lower()
    assert "unusable" not in text and "too narrow" not in text
    assert "roads" not in _property_names(ALL_CONTRACTS["BuildableEnvelope"].model_json_schema())


@pytest.mark.parametrize("site", [s for s in SITES if s != "small_plot"])
def test_a_placed_tower_is_its_prototype_where_the_placement_puts_it(site):
    candidate = load(site, "CandidateLayout")
    for tower in candidate.towers:
        drawn = candidate.placed_footprint(tower)
        assert drawn.symmetric_difference(tower.footprint.to_shapely()).area < 1e-6


def test_the_legal_verdict_follows_the_rule():
    def check(status, **readings):
        return Check(family=Family.SETBACK, finding=Finding("x", status, "", "", ""),
                     by_reading=readings)

    assert legal_verdict([check(Status.PASS), check(Status.NOT_CHECKED)], []) is LegalVerdict.PASS
    assert legal_verdict([check(Status.PASS), check(Status.UNVERIFIED)],
                         []) is LegalVerdict.UNVERIFIED
    assert legal_verdict([check(Status.PASS)], [Discrepancy(
        item="setback", source="envelope", theirs="9 m", ours="10 m", blocks_pass=True)]
    ) is LegalVerdict.FAIL
    with pytest.raises(ValidationError, match="PASS overall"):
        check(Status.PASS, stilt_in_rule_height={"counted": "FAIL", "not_counted": "PASS"})


def test_a_report_cannot_state_a_verdict_its_checks_do_not_give():
    report = load("rectangle", "ValidationReport").model_dump(mode="json")
    report["verdict"]["legal"] = "PASS" if report["verdict"]["legal"] != "PASS" else "FAIL"
    with pytest.raises(ValidationError, match="does not follow"):
        ValidationReport.model_validate(report)


def test_the_brief_may_be_stricter_than_the_law_never_looser():
    brief = load("rectangle", "DesignBrief").model_dump(mode="json")
    brief["firm_standards"]["cellar_utilities_share"]["value"] = 0.2
    with pytest.raises(ValidationError, match="13\\(c\\)\\(xi\\)"):
        type(load("rectangle", "DesignBrief")).model_validate(brief)


def test_every_fact_says_where_it_came_from():
    site = load("rectangle", "CanonicalSiteModel")
    assert site.access_road().legal_row_m.source_kind.value in SITE_FACT_SOURCES
    assert site.access.dead_end.status.value == "USER_CONFIRMED"
    assert load("l_plot_with_arm", "CanonicalSiteModel").access.dead_end.status.value == (
        "UNVERIFIED")


# --- contracts 1.1 ---------------------------------------------------------------------------


def _variant(name: str, **changes) -> tuple:
    """A made-up fixture site with some of its facts changed, and its rules."""
    spec = dict(SPECS[name], **changes)
    site = site_model(fixture_project(name, spec), site_id=f"{name}-variant",
                      boundary=spec["boundary"])
    return site, resolved_rules(site)


def _limit(**fields) -> HeightLimit:
    base = {"id": "x", "measure": "RULE_HEIGHT", "bound": "BOUNDED", "max_m": 30.0,
            "status": "USER_CONFIRMED", "reason": "made up", "clause": "made up"}
    return HeightLimit.model_validate(base | fields)


CONDITION = {"fact": "access.dead_end", "holds_when": True, "text": "the road ends at the plot"}


def test_the_contracts_are_version_1_1_and_refuse_an_older_document():
    assert CONTRACTS_VERSION == "1.1"
    brief = load("rectangle", "DesignBrief").model_dump(mode="json")
    with pytest.raises(ValidationError, match="schema_version"):
        ALL_CONTRACTS["DesignBrief"].model_validate(brief | {"schema_version": "1.0"})


@pytest.mark.parametrize(("limit", "within", "beyond", "offered_beyond"), [
    # a limit that applies, on confirmed inputs
    ({}, Status.PASS, Status.FAIL, False),
    # a limit that applies, on inputs nobody confirmed: it settles nothing either way
    ({"status": "UNVERIFIED"}, Status.UNVERIFIED, Status.UNVERIFIED, False),
    # a conditional limit whose condition is not settled: met anyway it passes; beyond it the
    # height may be offered, labelled UNVERIFIED
    ({"condition": CONDITION, "applicability": "UNKNOWN"}, Status.PASS, Status.UNVERIFIED, True),
    ({"condition": CONDITION, "applicability": "APPLIES"}, Status.PASS, Status.FAIL, False),
    ({"condition": CONDITION, "applicability": "DOES_NOT_APPLY"}, Status.INFO, Status.INFO, True),
    ({"bound": "UNBOUNDED", "max_m": None}, Status.PASS, Status.PASS, True),
    ({"bound": "NOT_EVALUATED", "max_m": None}, Status.UNVERIFIED, Status.UNVERIFIED, True),
], ids=["applies", "unconfirmed", "condition unknown", "condition holds", "does not apply",
        "unbounded", "not evaluated"])
def test_a_height_limit_is_judged_by_one_table(limit, within, beyond, offered_beyond):
    """HeightLimit.evaluate is the verdict the validator gives; HeightLimit.beyond is whether a
    generator may offer the height. Both read the same limit the same way."""
    made = _limit(**limit)
    assert made.evaluate(27.0) is within
    assert made.evaluate(33.0) is beyond
    assert made.beyond(27.0) is False
    assert made.beyond(33.0) is (not offered_beyond)


def test_a_height_limit_holds_its_edge_as_the_rule_words_it():
    upto = _limit()  # up to and including 30 m
    assert upto.evaluate(30.0) is Status.PASS
    assert upto.evaluate(3.0 + 9 * 3.0) is Status.PASS  # 30.000000000000004 is 30 m
    assert upto.evaluate(30.01) is Status.FAIL
    under = _limit(inclusive=False)  # must stay under 30 m
    assert under.evaluate(30.0) is Status.FAIL and under.evaluate(29.99) is Status.PASS


@pytest.mark.parametrize("wrong", [
    {"max_m": None},  # BOUNDED without a number
    {"bound": "UNBOUNDED"},  # a number on a limit that has none
    {"bound": "NOT_EVALUATED"},
    {"max_m": math.inf},
    {"max_m": -3.0},
    {"applicability": "UNKNOWN"},  # nothing it could be unknown about
])
def test_a_height_limit_that_contradicts_itself_is_refused(wrong):
    with pytest.raises(ValidationError):
        _limit(**wrong)


@pytest.mark.parametrize("site", SITES)
def test_every_height_falls_in_exactly_one_band(site):
    height = load(site, "ResolvedRules").height
    for metres in (0.5, 12.0, 20.999, 21.0, 3.0 + 6 * 3.0, 21.001, 24.0, 24.001, 30.0, 55.0,
                   120.0, 500.0):
        assert sum(band.contains(metres) for band in height.bands) == 1, metres
    assert height.band_for(0.0) is None


def test_a_building_of_exactly_the_high_rise_height_is_a_high_rise_with_its_own_row():
    height = load("rectangle", "ResolvedRules").height
    start = height.high_rise_from_m.value
    below, at, above = (height.band_for(h) for h in (start - 0.01, start, start + 0.01))
    assert below.kind is BandKind.NON_HIGH_RISE and below.modelled is False
    assert at.kind is BandKind.HIGH_RISE and (at.above_m, at.up_to_m) == (start, start)
    assert (at.min_road_m, at.setback_m, at.gap_m) == (12, 7, 7)
    assert above.kind is BandKind.HIGH_RISE and above.setback_m == 8
    assert height.band_for(24.0).setback_m == 8 and height.band_for(24.01).setback_m == 9


def test_bands_that_leave_a_gap_or_overlap_are_refused():
    height = load("rectangle", "ResolvedRules").height.model_dump(mode="json")
    gap = dict(height, bands=[b for b in height["bands"] if b["above_m"] != b["up_to_m"]])
    with pytest.raises(ValidationError, match="gap or overlap"):
        HeightRules.model_validate(gap)
    twice = dict(height, bands=[dict(b, up_to_inclusive=True) for b in height["bands"]])
    with pytest.raises(ValidationError, match="gap or overlap"):
        HeightRules.model_validate(twice)


def test_the_envelope_of_a_band_is_found_by_the_band_never_by_the_height():
    rules, env = load("rectangle", "ResolvedRules"), load("rectangle", "BuildableEnvelope")
    assert env.of_band(rules.height.band_for(21.0)).setback_m == 7
    assert env.of_band(rules.height.band_for(21.5)).setback_m == 8
    assert env.of_band(rules.height.band_for(40.0)) is None  # beyond what the 60 ft road serves


@pytest.mark.parametrize("site", SITES)
def test_the_made_up_sites_may_take_a_high_rise(site):
    high_rise = load(site, "ResolvedRules").height.high_rise
    assert high_rise.eligibility is Eligibility.ALLOWED
    assert {g.id for g in high_rise.grounds} == {"road_width", "plot_size"}


@pytest.mark.parametrize(("changes", "failing"), [
    ({"road_ft": 30}, "road_width"),
    ({"boundary": box(0, 0, 40, 45), "net": box(0, 0, 40, 45)}, "plot_size"),
], ids=["a 30 ft road", "a plot of 1,800 m²"])
def test_a_prohibited_high_rise_says_nothing_about_lower_heights(changes, failing):
    """Where the road or the plot rules a high-rise out, nothing here says a lower building is
    legal: its band is Table III's, not modelled, and no limit passes it."""
    site, rules = _variant("small_plot", **changes)
    height = rules.height
    assert height.high_rise.eligibility is Eligibility.PROHIBITED
    assert [g.id for g in height.high_rise.grounds if g.met is False] == [failing]
    assert "Table III" in height.high_rise.note
    low = height.band_for(15.0)
    assert low.kind is BandKind.NON_HIGH_RISE and low.modelled is False
    assert low.setback_m is None and low.status is Provenance.UNVERIFIED
    # no limit stands in for the prohibition by saying "anything under 21 m"
    assert not [lim for lim in height.limits if lim.max_m == height.high_rise_from_m.value]
    env = envelope(site, rules)
    assert [b.kind for b in env.bands] == [BandKind.NON_HIGH_RISE]
    assert env.bands[0].modelled is False and env.bands[0].buildable == []


def test_a_road_too_narrow_for_a_high_rise_passes_no_lower_height_either():
    _, rules = _variant("small_plot", road_ft=30)
    road = next(lim for lim in rules.height.limits if lim.id == "table_iv_road")
    assert road.bound is LimitBound.NOT_EVALUATED and "Table III" in road.reason
    assert road.evaluate(15.0) is Status.UNVERIFIED


def test_eligibility_is_unverified_while_a_ground_is_not_settled():
    _, rules = _variant("small_plot", road_ft=None)
    high_rise = rules.height.high_rise
    assert high_rise.eligibility is Eligibility.UNVERIFIED
    assert next(g for g in high_rise.grounds if g.id == "road_width").met is None
    road = next(lim for lim in rules.height.limits if lim.id == "table_iv_road")
    assert road.bound is LimitBound.NOT_EVALUATED and road.evaluate(24.0) is Status.UNVERIFIED


def test_eligibility_must_follow_its_grounds():
    high_rise = load("rectangle", "ResolvedRules").height.high_rise.model_dump(mode="json")
    high_rise["grounds"][0]["met"] = False
    with pytest.raises(ValidationError, match="does not follow"):
        HighRiseEligibility.model_validate(high_rise)
    assert HighRiseEligibility.model_validate(
        high_rise | {"eligibility": "PROHIBITED"}).eligibility is Eligibility.PROHIBITED


def test_a_road_wide_enough_for_every_row_sets_no_limit_and_a_dead_end_follows_the_site():
    _, rules = _variant("rectangle", road_ft=100, dead_end=True)
    limits = {lim.id: lim for lim in rules.height.limits}
    assert limits["table_iv_road"].bound is LimitBound.UNBOUNDED
    assert limits["table_iv_road"].evaluate(90.0) is Status.PASS
    assert limits["dead_end"].applicability is Applicability.APPLIES
    assert limits["dead_end"].evaluate(33.0) is Status.FAIL
    runs_on = {lim.id: lim for lim in load("rectangle", "ResolvedRules").height.limits}
    assert runs_on["dead_end"].applicability is Applicability.DOES_NOT_APPLY
    not_known = {lim.id: lim for lim in load("l_plot_with_arm", "ResolvedRules").height.limits}
    assert not_known["dead_end"].applicability is Applicability.UNKNOWN
    assert not_known["dead_end"].evaluate(27.0) is Status.PASS  # met whether it applies or not
    assert not_known["dead_end"].evaluate(33.0) is Status.UNVERIFIED
    assert not_known["airport"].bound is LimitBound.NOT_EVALUATED


SOFT, HARD, BUILT = Surface.SOFT, Surface.HARD, Surface.BUILT


@pytest.mark.parametrize(("use", "surface", "tot_lot", "other", "expected"), [
    (FacilityUse.GREENERY, SOFT, "soft_only", "same_kind_only", Qualification.QUALIFIES),
    (FacilityUse.SOFT_LANDSCAPE, SOFT, "soft_only", "same_kind_only", Qualification.QUALIFIES),
    (FacilityUse.TOT_LOT, SOFT, "soft_only", "same_kind_only", Qualification.QUALIFIES),
    # the rule names the tot-lot and does not say its surface: open, never an automatic no
    (FacilityUse.TOT_LOT, HARD, "any_surface", "same_kind_only", Qualification.QUALIFIES),
    (FacilityUse.TOT_LOT, HARD, "soft_only", "same_kind_only", Qualification.DOES_NOT_QUALIFY),
    # called landscaping, stated as paved: it is not soft landscaping, only open ground
    (FacilityUse.SOFT_LANDSCAPE, HARD, "any_surface", "same_kind_only",
     Qualification.DOES_NOT_QUALIFY),
    (FacilityUse.SOFT_LANDSCAPE, HARD, "soft_only", "any_open_recreation",
     Qualification.QUALIFIES),
    (FacilityUse.TOT_LOT, HARD, "soft_only", "any_open_recreation", Qualification.QUALIFIES),
    (FacilityUse.SPORT_COURT, HARD, "any_surface", "same_kind_only",
     Qualification.DOES_NOT_QUALIFY),
    (FacilityUse.SPORT_COURT, HARD, "any_surface", "any_open_recreation",
     Qualification.QUALIFIES),
    (FacilityUse.POOL, HARD, "any_surface", "same_kind_only", Qualification.DOES_NOT_QUALIFY),
    (FacilityUse.BUILT_SERVICE, BUILT, "any_surface", "any_open_recreation",
     Qualification.DOES_NOT_QUALIFY),
    (FacilityUse.TOT_LOT, BUILT, "any_surface", "any_open_recreation",
     Qualification.DOES_NOT_QUALIFY),
    # nobody stated it: nothing is assumed
    (None, SOFT, "any_surface", "any_open_recreation", Qualification.UNKNOWN),
    (FacilityUse.TOT_LOT, None, "any_surface", "any_open_recreation", Qualification.UNKNOWN),
])
def test_open_space_counts_by_use_surface_and_the_rule(use, surface, tot_lot, other, expected):
    space = load("rectangle", "ResolvedRules").open_space
    assert space.qualifies(use, surface, tot_lot_surface=tot_lot, other_uses=other) is expected


def test_the_open_space_rule_is_no_stricter_than_its_text():
    """The rule names greenery, tot lot and soft landscaping, 'etc.'. Whether a tot-lot must be
    soft, and what the 'etc.' takes in, are open readings evaluated every way: a result that
    holds under only one of them is UNVERIFIED, never a FAIL."""
    rules = load("rectangle", "ResolvedRules")
    assert rules.open_space.qualifying_uses.value == [
        FacilityUse.GREENERY, FacilityUse.TOT_LOT, FacilityUse.SOFT_LANDSCAPE]
    for open_reading in (TOT_LOT_SURFACE, OPEN_SPACE_OTHER_USES):
        assert rules.interpretation(open_reading).selected == ALL
        assert set(rules.readings(open_reading)) == set(READINGS[open_reading])


@pytest.mark.parametrize("name", ["DesignBrief", "CandidateLayout", "ResolvedRules"])
def test_nothing_declares_that_a_facility_counts_as_open_space(name):
    """Use and surface are stated; whether the ground counts is derived (OpenSpaceRules)."""
    names = _property_names(ALL_CONTRACTS[name].model_json_schema())
    assert not names & NOT_DECLARED
    if name != "ResolvedRules":
        assert {"use", "surface"} <= names


def test_design_margins_are_never_law_and_none_is_set_unasked():
    margins = load("rectangle", "DesignBrief").design_margins
    assert margins.any_set is False
    assert margins.setback_target_m(7.0) == 7.0 and margins.parking_target_sqm(900.0) == 900.0
    for name in type(margins).model_fields:
        assert margins.basis(name) is Basis.ENGINE_DESIGN_ASSUMPTION
    firm = {"value": 0.5, "status": "USER_CONFIRMED", "source_kind": "FIRM_STANDARD",
            "source": "made up"}
    set_by_firm = DesignMargins.model_validate({
        "setback_extra_m": firm, "tower_gap_extra_m": firm, "road_width_extra_m": firm,
        "open_space_extra_fraction": firm | {"value": 0.005},
        "parking_extra_fraction": firm | {"value": 0.05}})
    assert set_by_firm.basis("setback_extra_m") is Basis.FIRM_STANDARD
    assert set_by_firm.setback_target_m(7.0) == 7.5 and set_by_firm.gap_target_m(8.0) == 8.5
    assert set_by_firm.road_width_target_m(9.0) == 9.5
    # half a point more of the same area the legal 10% is of
    assert set_by_firm.open_space_target_sqm(1500.0, 0.10) == pytest.approx(1575.0)
    assert set_by_firm.parking_target_sqm(1000.0) == pytest.approx(1050.0)
    for source_kind in ("ARCHITECT", "DOCUMENT", "SURVEY", "FIRM_FINISHED_PLAN"):
        with pytest.raises(ValidationError, match="never"):
            DesignMargins.model_validate({"setback_extra_m": firm | {"source_kind": source_kind}})
    with pytest.raises(ValidationError, match="cannot be negative"):
        DesignMargins.model_validate({"setback_extra_m": firm | {"value": -0.5}})


def test_the_rules_carry_the_line_clearances_and_the_ramp_fire_clearance():
    rules = load("rectangle", "ResolvedRules")
    assert rules.electrical.ht_clearance_m.value == 3.0
    assert rules.electrical.lt_clearance_m.value == 1.5
    assert "3(c)(i)" in rules.electrical.ht_clearance_m.clause
    assert rules.parking.ramp_fire_clearance_m.value == 7.0
    assert "13(c)(vii)" in rules.parking.ramp_fire_clearance_m.clause
    names = _property_names(ALL_CONTRACTS["ResolvedRules"].model_json_schema())
    assert not {"above_5_acres", "large_project_share_of_site"} & names  # row housing's, not ours


def test_values_that_cannot_be_are_refused():
    with pytest.raises(ValidationError, match="finite"):
        Shape(outer=[(0, 0), (10, 0), (10, math.nan)])
    with pytest.raises(ValidationError, match="hole"):
        Shape(outer=[(0, 0), (10, 0), (10, 10)], holes=[[(1, 1), (2, 2)]])
    with pytest.raises(ValidationError, match="never a legal rule"):
        ParkingMeasurement(bay_m=(2.5, 5.0), aisle_m=6.0, sqm_per_car=20.0,
                           basis=Basis.LEGAL_RULE)
    with pytest.raises(ValidationError, match="metre each way"):
        ParkingMeasurement(bay_m=(0.25, 5.0), aisle_m=6.0, sqm_per_car=20.0)
    rules = load("rectangle", "ResolvedRules").model_dump(mode="json")
    table = rules["parking"]["cellar_setback_by_site_sqm"]
    table["value"] = table["value"][:-1]  # no row for the largest sites
    with pytest.raises(ValidationError, match="every larger site"):
        ResolvedRules.model_validate(rules)
    rules = load("rectangle", "ResolvedRules").model_dump(mode="json")
    rules["open_space"]["share"]["value"] = 0.0
    with pytest.raises(ValidationError, match="open-space share"):
        ResolvedRules.model_validate(rules)
    rules = load("rectangle", "ResolvedRules").model_dump(mode="json")
    rules["interpretations"] = [i for i in rules["interpretations"]
                                if i["id"] != TOT_LOT_SURFACE]
    with pytest.raises(ValidationError, match="missing interpretation"):
        ResolvedRules.model_validate(rules)


def test_a_design_target_sits_beside_the_verdict_and_never_in_it():
    """A report shows the legal minimum, the target above it and what is provided; a missed
    target changes no legal verdict, and a target is never law nor below it."""
    row = {"item": "setback", "subject": "T1", "unit": "m", "legal_minimum": 7.0, "target": 7.5,
           "provided": 7.2, "basis": "FIRM_STANDARD"}
    made = TargetCheck.model_validate(row)
    assert made.margin == 0.5 and made.in_hand == pytest.approx(0.2)
    assert made.meets_target is False
    assert TargetCheck.model_validate(row | {"provided": 7.5}).meets_target is True
    report = load("rectangle", "ValidationReport").model_dump(mode="json")
    with_targets = ValidationReport.model_validate(report | {"design_targets": [row]})
    assert with_targets.verdict == load("rectangle", "ValidationReport").verdict
    with pytest.raises(ValidationError, match="never below the legal minimum"):
        TargetCheck.model_validate(row | {"target": 6.5})
    for basis in ("LEGAL_RULE", "SITE_INPUT", "UNRESOLVED_INTERPRETATION"):
        with pytest.raises(ValidationError, match="never"):
            TargetCheck.model_validate(row | {"basis": basis})
