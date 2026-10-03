"""The edges of the program (what the brief asks): a flat count exactly at the maximum, a block with
exactly the cores the firm allows, one tower of another height under a fixed-height brief. Program
checks never change the legal verdict; these pin the survivors of a mutation test."""

from validator_helpers import check, fixture, set_floors

from siteplan.contracts.common import Provenance, Sourced, SourceKind, Status
from siteplan.contracts.design_brief import HeightMode, UnitsMode

TEST_CLASS = "normative"
Z = Status
UNITS = 208  # the rectangle fixture's flats


def _range(minimum, maximum):
    def edit(brief):
        brief.program.units.mode = UnitsMode.RANGE
        brief.program.units.minimum, brief.program.units.maximum = minimum, maximum
    return edit


def test_a_flat_count_exactly_at_the_briefs_maximum_or_minimum_meets_it():
    inputs = fixture("rectangle")
    assert int(inputs.report().recomputed.quantities["units"]) == UNITS
    assert check(inputs.with_brief(_range(UNITS, UNITS)).report(), "Units").finding.status is Z.PASS
    assert check(inputs.with_brief(_range(UNITS, UNITS + 5)).report(), "Units"
                 ).finding.status is Z.PASS
    assert check(inputs.with_brief(_range(100, UNITS - 1)).report(), "Units"
                 ).finding.status is Z.FAIL


def _fixed(floors):
    def edit(brief):
        brief.height_intent.mode = HeightMode.FIXED
        brief.height_intent.floors_above_stilt = floors
    return edit


def test_one_tower_of_another_height_breaks_a_fixed_height_even_when_the_others_keep_it():
    inputs = fixture("rectangle").with_brief(_fixed(8))
    assert check(inputs.report(), "Height intent").finding.status is Z.PASS
    odd = inputs.edited(lambda c: set_floors(c, "T3", 7))
    c = check(odd.report(), "Height intent")
    assert c.finding.status is Z.FAIL and "[7, 8]" in c.finding.measured


def _cores(n):
    def edit(brief):
        brief.firm_standards.max_cores_per_tower = Sourced[int](
            value=n, status=Provenance.USER_CONFIRMED, source_kind=SourceKind.ARCHITECT,
            source="made up")
    return edit


def test_a_block_with_exactly_the_cores_the_firm_allows_is_within_its_standard():
    inputs = fixture("rectangle")
    most = max(p.cores for p in inputs.candidate.prototypes_used)
    assert check(inputs.with_brief(_cores(most)).report(),
                 "Firm standards and parking preferences").finding.status is Z.PASS
    c = check(inputs.with_brief(_cores(most - 1)).report(),
              "Firm standards and parking preferences")
    assert c.finding.status is Z.FAIL and "cores in a block" in c.finding.measured


def test_a_club_house_of_other_floors_than_asked_is_a_shortfall_of_the_brief():
    def ask(brief):
        brief.program.club_house.floors = 3
    c = check(fixture("rectangle").with_brief(ask).report(), "Club house")
    assert c.finding.status is Z.FAIL and "2 floors, not 3" in c.finding.measured


def test_a_flat_type_outside_the_firms_library_is_flagged():
    def only_2a(brief):
        brief.program.allowed_types = ["2A"]
    c = check(fixture("rectangle").with_brief(only_2a).report(),
              "Firm standards and parking preferences")
    assert c.finding.status is Z.FAIL and "flat types outside the firm's library" in (
        c.finding.measured)
    assert "3A" in c.finding.measured
