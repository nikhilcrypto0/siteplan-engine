"""A study (2026-10-12, the architect): the buildings and the club house only, so the land they
leave shows where the tot-lot can go. The search lays no open space and no facility and keeps no
room for them; the validator is unchanged and still fails the missing tot-lot (G.O.168 rule
7(a)(vii)); only the optimizer, asked for a study, does not refuse a layout for that one check,
and every result says STUDY, NOT A LEGAL LAYOUT. Every other rule refuses a layout as before.
Made-up land."""

TEST_CLASS = "normative"

from functools import cache  # noqa: E402

from search_support import rectangle, strategy  # noqa: E402

from siteplan.contracts.common import Status  # noqa: E402
from siteplan.contracts.design_brief import Objectives  # noqa: E402
from siteplan.contracts.validation import LegalVerdict  # noqa: E402
from siteplan.optimizer.guard import (  # noqa: E402
    STUDY_NOT_LAID,
    held_to,
    inputs_of,  # noqa: E402
    why_refused,
)
from siteplan.optimizer.search.strategy import STUDY_CAVEAT  # noqa: E402
from siteplan.validator import validate  # noqa: E402


@cache
def _studied():
    made = rectangle()
    brief = made.brief.model_copy(update={"objectives": made.brief.objectives.model_copy(
        update={"study": True})})
    study = made.__class__(made.site, made.rules, brief, made.envelope, made.kit)
    return study, strategy().propose(study.context())


def test_a_study_lays_buildings_and_the_club_house_and_no_open_space():
    _, proposal = _studied()
    assert proposal.candidates
    for c in proposal.candidates:
        assert c.towers and c.program.club_house is not None
        assert c.program.open_space == [] and c.program.amenities == []
        assert STUDY_CAVEAT in c.caveats


def test_the_validator_still_fails_the_missing_tot_lot_and_nothing_else_fails():
    made, proposal = _studied()
    for c in proposal.candidates:
        report = validate(made.site, made.rules, made.brief, c, made.envelope)
        fails = {i.finding.rule for i in report.legal if i.finding.status is Status.FAIL}
        assert STUDY_NOT_LAID in fails  # the validator is unchanged
        assert fails == {STUDY_NOT_LAID}, fails  # every other rule holds
        assert report.verdict.legal is LegalVerdict.FAIL
        assert held_to(report, study=True) is not LegalVerdict.FAIL
        inputs = inputs_of(made.site, made.rules, made.brief)
        assert why_refused(c, report, inputs, study=True) == []
        assert why_refused(c, report, inputs)  # outside a study it is refused, as ever


def test_a_study_still_refuses_any_other_fail():
    made, proposal = _studied()
    c = proposal.candidates[0]
    report = validate(made.site, made.rules, made.brief, c, made.envelope)
    other = next(i for i in report.legal if i.finding.rule != STUDY_NOT_LAID)
    broken = report.model_copy(update={"legal": [
        i.model_copy(update={"finding": i.finding.__class__(
            i.finding.rule, Status.FAIL, i.finding.measured, i.finding.required,
            i.finding.clause, i.finding.note)}) if i is other else i for i in report.legal]})
    assert held_to(broken, study=True) is LegalVerdict.FAIL


def test_the_study_flag_is_left_out_of_a_stored_brief_when_off():
    assert "study" not in Objectives().model_dump()
    assert Objectives(study=True).model_dump()["study"] is True
