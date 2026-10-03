"""The permanent contracts: what each may hold, the invariants they enforce, and the fixtures
every stream starts from (tests/contract_fixtures)."""

import json
from pathlib import Path

import pytest
from contract_fixtures import SITES, load
from pydantic import ValidationError
from shapely.geometry import box

from siteplan.contracts import ALL_CONTRACTS, schema_text
from siteplan.contracts.accounting import (
    DeductionKind,
    LayerKind,
    OwnershipReconciliation,
    PartitionLedger,
    Permit,
    PhysicalUse,
)
from siteplan.contracts.common import Finding, Shape, Status
from siteplan.contracts.resolved_rules import (
    ALL,
    CIRCULATION_IN_SETBACK,
    OPEN_SPACE_BASIS,
    REQUIRED_INTERPRETATIONS,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.contracts.validation import (
    Check,
    Discrepancy,
    Family,
    LegalVerdict,
    ValidationReport,
    legal_verdict,
)

SCHEMAS = Path(__file__).parent.parent / "docs" / "contracts"
# What each of the three kinds of fact may not hold (property names anywhere in its schema).
FORBIDDEN = {
    "CanonicalSiteModel": {"setback_m", "gap_m", "min_road_m", "unit_mix", "floor_to_floor_m",
                           "stilt_height_m", "pareto", "objectives", "clause"},
    "ResolvedRules": {"unit_mix", "floor_to_floor_m", "stilt_height_m", "pareto", "objectives",
                      "max_tower_length_m", "boundary", "net_plot"},
    "DesignBrief": {"setback_m", "gap_m", "min_road_m", "clause", "boundary", "net_plot",
                    "legal_row_m", "authority", "inside_cure", "dead_end"},
}
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
