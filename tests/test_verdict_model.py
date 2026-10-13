"""The verdict model of contracts 1.4 (2026-10-13): PASS, FAIL, CONDITIONAL and NOT_CHECKED.

Every expected outcome below is written out by hand (a table of results, a lane width against
the turning reading's figure), never computed from the module under test, so a change in that
module cannot move the expectation with it. What is held:

- a violation under every reading stays FAIL, whatever a study selected;
- a result that differs between readings is CONDITIONAL, keeps each reading's own result in
  by_reading and names the reading it rests on, with the study's selection beside it;
- a required site fact that is missing or unverified is CONDITIONAL, never PASS;
- a report stored as 1.3 reads with CONDITIONAL and dumps exactly as it was stored;
- the optimizer's guard refuses on the result under the study's selections.
"""

import json
from pathlib import Path

import pytest
from validator_helpers import check, fixture, select

from siteplan.contracts.common import Finding, Provenance, Status, digest
from siteplan.contracts.resolved_rules import (
    ALL,
    COVERED_PARKING,
    FIRE_TURNING_RADIUS,
    MIXED_HEIGHT_SPACING,
    PLINTH,
    STILT_RAISE,
    WhenOpen,
)
from siteplan.contracts.validation import (
    Check,
    DependsOn,
    Family,
    LegalVerdict,
    ValidationReport,
)
from siteplan.legal.resolve import resolve
from siteplan.optimizer import guard
from siteplan.validator import raise_readings
from siteplan.validator.readings import Cell, check_from, fact, run

TEST_CLASS = "normative"
P, F, C = Status.PASS, Status.FAIL, Status.CONDITIONAL
FIXTURES = Path(__file__).parent / "contract_fixtures"
TURN, GAP = FIRE_TURNING_RADIUS, MIXED_HEIGHT_SPACING


def _table(results: dict[tuple[str, str], Status]):
    """A check whose result under (turning reading, spacing reading) is the table's."""
    return lambda a: Cell(results[(a[TURN], a[GAP])], "x", "y")


def _judged(results):
    # the made-up rules select outer_edge and taller_governs without settling either
    return check_from(run(fixture("rectangle").rules, [TURN, GAP], _table(results)),
                      family=Family.FIRE, rule="r", clause="c")


# --- combining the readings ------------------------------------------------------------------


def test_a_violation_under_every_reading_is_a_fail_with_nothing_to_rest_on():
    c = _judged({("outer_edge", "taller_governs"): F, ("outer_edge", "each_own"): F,
                 ("centreline", "taller_governs"): F, ("centreline", "each_own"): F})
    assert c.finding.status is F and c.selected_status is F and c.rests_on == []
    assert c.by_reading == {TURN: {"outer_edge": F, "centreline": F},
                            GAP: {"taller_governs": F, "each_own": F}}


def test_a_result_that_turns_on_one_reading_keeps_each_readings_result():
    c = _judged({("outer_edge", "taller_governs"): P, ("outer_edge", "each_own"): P,
                 ("centreline", "taller_governs"): F, ("centreline", "each_own"): F})
    assert c.finding.status is C
    assert c.by_reading[TURN] == {"outer_edge": P, "centreline": F}
    assert c.selected_status is P  # the study selected outer_edge
    (dep,) = c.rests_on  # the spacing makes no difference, so only the turning is named
    assert (dep.kind, dep.id, dep.selected) == (DependsOn.READING, TURN, "outer_edge")
    assert dep.outcomes == {"outer_edge": P, "centreline": F}


def test_a_result_that_turns_on_two_readings_together_names_both():
    # each reading alone shows no difference (every marginal is mixed), the pair does
    c = _judged({("outer_edge", "taller_governs"): P, ("outer_edge", "each_own"): F,
                 ("centreline", "taller_governs"): F, ("centreline", "each_own"): P})
    assert c.finding.status is C
    assert {d.id for d in c.rests_on} == {TURN, GAP}


def test_a_missing_site_fact_under_every_reading_is_conditional_and_says_which():
    def cell(a):
        return Cell(C, "unknown", "y", rests_on=(fact("the access road joins a 12 m street"),))
    c = check_from(run(fixture("rectangle").rules, [TURN], cell), family=Family.FIRE,
                   rule="r", clause="c")
    assert c.finding.status is C
    assert [(d.kind, d.id) for d in c.rests_on] == [
        (DependsOn.SITE_FACT, "the access road joins a 12 m street")]


# --- the validator on made-up land -------------------------------------------------------------


def _without(name):
    def edit(site):
        sourced = getattr(site.access, name)
        sourced.value, sourced.status = None, Provenance.UNVERIFIED
    return fixture("rectangle").with_site(edit)


def test_an_unknown_street_join_is_never_a_pass_and_the_verdict_cannot_pass():
    report = _without("joins_12m_street").report()
    c = check(report, "Fire access: the street joins a 12 m street")
    assert c.finding.status is C
    assert [(d.kind, d.id) for d in c.rests_on] == [
        (DependsOn.SITE_FACT, "the access road joins a 12 m street")]
    assert report.verdict.legal is not LegalVerdict.PASS


def test_an_unknown_access_road_width_is_never_a_pass():
    def edit(site):
        site.access_road().legal_row_m.status = Provenance.UNVERIFIED
    c = next(c for c in fixture("rectangle").with_site(edit).report().legal
             if c.finding.rule.startswith("Abutting road width"))
    assert c.finding.status is C
    assert any(d.kind is DependsOn.SITE_FACT for d in c.rests_on)


def test_the_made_up_lanes_hold_on_the_outer_edge_and_fail_on_the_centreline():
    """The made-up towers keep the 6.88 m a 6 m lane needs to turn on a 9 m outer edge; read at
    the centreline the same turn needs 7.76 m (AGENTS.md, Fire access), which they do not keep."""
    c = check(fixture("rectangle").report(), "Fire access: T1")
    assert c.finding.status is C
    assert c.by_reading[TURN] == {"outer_edge": P, "centreline": F}
    assert c.selected_status is P


def test_settled_on_the_centreline_the_same_lanes_fail():
    inputs = fixture("rectangle").with_rules(lambda r: select(r, TURN, "centreline"))
    report = inputs.report()
    assert check(report, "Fire access: T1").finding.status is F
    assert report.verdict.legal is LegalVerdict.FAIL


# --- a report stored as 1.3 ------------------------------------------------------------------


@pytest.mark.parametrize("site", ["rectangle", "nala_plot", "l_plot_with_arm"])
def test_a_stored_1_3_report_reads_as_conditional_and_dumps_as_stored(site):
    text = (FIXTURES / site / "ValidationReport.json").read_text()
    stored = json.loads(text)
    assert stored["schema_version"] == "1.3" and stored["verdict"]["legal"] == "UNVERIFIED"
    report = ValidationReport.model_validate_json(text)
    assert report.verdict.legal is LegalVerdict.CONDITIONAL
    assert json.loads(report.model_dump_json()) == stored
    assert digest(report) == digest(ValidationReport.model_validate(stored))


def test_a_1_3_report_keeps_a_layers_conditional_permit():
    stored = json.loads((FIXTURES / "rectangle" / "ValidationReport.json").read_text())
    layer = {"id": "setback", "kind": "SETBACK", "clause": "c", "basis": "LEGAL_RULE",
             "status": "VERIFIED", "permits": [{"use": "ROAD", "permit": "CONDITIONAL",
                                                "condition": "made up"}]}
    stored["accounting"]["rule_layers"] = {"layers": [layer]}
    dumped = json.loads(ValidationReport.model_validate(stored).model_dump_json())
    assert dumped["accounting"]["rule_layers"]["layers"][0]["permits"][0]["permit"] == (
        "CONDITIONAL")


def test_a_1_4_report_refuses_a_conditional_result_that_names_nothing():
    stored = json.loads((FIXTURES / "rectangle" / "ValidationReport.json").read_text())
    stored["schema_version"] = "1.4"
    with pytest.raises(ValueError, match="names nothing it rests on"):
        ValidationReport.model_validate(stored)


# --- the other stilt raise ---------------------------------------------------------------------


def _limit(status: Status, readings=None) -> Check:
    return Check(family=Family.HEIGHT, finding=Finding("limit", status, "m", "r", "c"),
                 by_reading=readings or {})


def test_a_result_that_differs_between_the_raises_rests_on_the_reading_and_keeps_both():
    given = _limit(P, {"stilt_in_rule_height": {"counted": P, "not_counted": P}})
    (merged,) = raise_readings.merge(COVERED_PARKING, PLINTH, [given], [_limit(F)])
    assert merged.finding.status is C and merged.selected_status is P
    assert merged.by_reading == {"stilt_in_rule_height": {"counted": P, "not_counted": P},
                                 STILT_RAISE: {COVERED_PARKING: P, PLINTH: F}}
    assert [(d.kind, d.id, d.selected) for d in merged.rests_on] == [
        (DependsOn.READING, STILT_RAISE, COVERED_PARKING)]


def test_a_failure_under_both_raises_stays_a_failure():
    (merged,) = raise_readings.merge(COVERED_PARKING, PLINTH, [_limit(F)], [_limit(F)])
    assert merged.finding.status is F and merged.rests_on == []


def test_the_raise_is_judged_both_ways_only_while_the_law_leaves_it_open():
    site = fixture("rectangle").site
    rules = resolve(site, when_open=WhenOpen.CONSERVATIVE)  # the default: covered parking
    assert raise_readings.other_reading(rules) == (COVERED_PARKING, PLINTH)
    every = resolve(site, when_open=WhenOpen.CONSERVATIVE, selections={STILT_RAISE: ALL})
    assert raise_readings.other_reading(every) is None  # it holds the larger raise already
    settled = rules.model_copy(deep=True)
    select(settled, STILT_RAISE, COVERED_PARKING)
    assert raise_readings.other_reading(settled) is None
    # a contract stored before the raise (the made-up fixtures) carries none to vary
    assert raise_readings.other_reading(fixture("rectangle").rules) is None


# --- the guard -------------------------------------------------------------------------------


def _report_with(c: Check):
    inputs = fixture("rectangle")
    base = inputs.report()
    legal = [c]
    report = ValidationReport(
        candidate_ref=base.candidate_ref, site_ref=base.site_ref, rules_ref=base.rules_ref,
        brief_ref=base.brief_ref, validator_version="test", legal=legal,
        verdict={"legal": LegalVerdict.CONDITIONAL, "program": "MET"})
    return inputs.candidate, report, (base.site_ref, base.rules_ref, base.brief_ref)


def _conditional(selected: Status) -> Check:
    return Check(family=Family.FIRE, finding=Finding("Fire access: T1", C, "m", "r", "c"),
                 by_reading={TURN: {"outer_edge": selected, "centreline": F if selected is P
                                    else P}},
                 rests_on=[{"kind": "READING", "id": TURN, "selected": "outer_edge"}],
                 selected_status=selected)


def test_the_guard_refuses_what_fails_under_the_studys_selection():
    candidate, report, inputs = _report_with(_conditional(F))
    assert guard.why_refused(candidate, report, inputs)


def test_the_guard_passes_what_holds_under_the_studys_selection():
    candidate, report, inputs = _report_with(_conditional(P))
    assert guard.why_refused(candidate, report, inputs) == []
