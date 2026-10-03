"""The validator against today's checker. On the contract fixtures (the prototype generator's
own candidates, whose `generator_claims` are today's checker's findings) it gives the same
statuses, except where a difference is listed here with its reason. On the firm's cases it FAILs
exactly where `siteplan cases` does. Characterization: it pins today's agreement."""

from pathlib import Path

import pytest
from contract_fixtures import SITES
from validator_cases import inputs_of, made_up_case
from validator_helpers import fixture, status, statuses

from siteplan.cases import load_cases, review
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT

TEST_CLASS = "characterization"
CASES = Path(__file__).parent.parent / "fixtures" / "cases"

# Where the validator and today's checker part ways on the fixtures, and why. Every other claim
# the generator makes gets the same status from the validator.
DIFFERENT = {
    ("rectangle", "Fire access: the street joins a 12 m street"):
        "the generator was run without the architect's answer (UNVERIFIED); the site model "
        "holds it (the street joins one, USER_CONFIRMED) and the validator reads it there",
    ("small_plot", "Setbacks (Table III)"):
        "a hand-made claim, not the checker's: under 21 m Table III applies, which neither "
        "models, so the validator says NOT_CHECKED under 'All-round setback: T1'",
}
# What the checker says on every layout and the validator says only when it has something to
# say: with no driveway drawn there is nothing to judge.
NOT_CARRIED = {"Driveways"}


@pytest.mark.parametrize("site", SITES)
def test_the_validator_gives_todays_statuses_on_the_contract_fixtures(site):
    inputs = fixture(site)
    ours = statuses(inputs.report())
    for claim in inputs.candidate.generator_claims:
        if claim.rule in NOT_CARRIED or (site, claim.rule) in DIFFERENT:
            continue
        assert ours.get(claim.rule) is claim.status, (site, claim.rule, claim.status,
                                                      ours.get(claim.rule))


@pytest.mark.parametrize("key", list(DIFFERENT))
def test_each_listed_difference_is_real_and_has_a_reason(key):
    site, rule = key
    inputs = fixture(site)
    claimed = {c.rule: c.status for c in inputs.candidate.generator_claims}
    assert claimed[rule] is not statuses(inputs.report()).get(rule)
    assert len(DIFFERENT[key]) > 30


def test_what_the_validator_adds_to_todays_checks_on_a_generated_layout():
    """New: roads and fire lanes in the setback under both readings (UNVERIFIED), the height
    limit from the rules, the height above sea level (UNVERIFIED with no coordinates), the
    ledger, surface bays, and the net plot itself."""
    report = fixture("rectangle").report()
    claimed = {c.rule for c in fixture("rectangle").candidate.generator_claims}
    added = {c.finding.rule for c in report.legal} - claimed
    assert {"Circulation inside the setback", "Every square metre once", "Net plot",
            "Surface parking bays", "Height above sea level (airport and Air Force)"} <= added
    assert status(report, "Circulation inside the setback") is Status.UNVERIFIED


# --- cases: the firm's drawings as buildings and a plot ----------------------------------


def test_the_validator_fails_a_made_up_firm_drawing_where_the_checker_does():
    case = made_up_case()
    expected = {f.rule for f in review(case).failures}
    assert expected  # the drawing keeps 8 m where the stilt-counted figure is 9 m
    report = inputs_of(case).report()
    assert {c.finding.rule for c in report.legal if c.finding.status is Status.FAIL} == expected


def test_a_block_at_exactly_the_high_rise_threshold_is_not_passed_without_its_table_row():
    """Stilt + 6 at 3 m is exactly 21 m. The resolved bands have no Table IV row for exactly 21
    m, so it is held to the row above (the stricter): 7 m round it does not meet 8 m, and the
    validator says UNVERIFIED where the checker, which reads the row below, says PASS."""
    report = inputs_of(made_up_case()).report()
    assert status(report, "All-round setback: Tower 5") is Status.UNVERIFIED
    held = status(inputs_of(made_up_case(setback_of_stilt_6_block=8.5)).report(),
                  "All-round setback: Tower 5")
    assert held is Status.PASS  # meets the stricter row, so it meets either


def test_with_the_stilt_left_open_the_firms_8_m_is_unverified_not_a_fail():
    """The firm's drawing behaves as if the stilt does not count (24 m needs 8 m): a reading the
    rules have not ruled out, so the validator does not call it illegal."""
    report = inputs_of(made_up_case(), stilt_reading=None).report()
    assert status(report, "All-round setback: Tower 1") is Status.UNVERIFIED
    assert [c.finding.rule for c in report.legal if c.finding.status is Status.FAIL] == []


@pytest.mark.skipif(not CASES.is_dir(), reason="client cases not present")
def test_every_client_case_fails_only_where_we_already_know_why():
    for case in load_cases(CASES):
        report = inputs_of(case).report()
        failed = {c.finding.rule for c in report.legal if c.finding.status is Status.FAIL}
        assert failed == set(case.known_disagreements), (case.name, failed)
        assert failed == {f.rule for f in review(case).failures}


@pytest.mark.skipif(not CASES.is_dir(), reason="client cases not present")
def test_with_the_stilt_left_open_every_known_failure_still_fails_if_the_stilt_counts():
    for case in load_cases(CASES):
        report = inputs_of(case, stilt_reading=None).report()
        for rule in case.known_disagreements:
            by_stilt = next(c for c in report.legal if c.finding.rule == rule).by_reading
            assert by_stilt[STILT_IN_RULE_HEIGHT]["counted"] is Status.FAIL, (case.name, rule)
