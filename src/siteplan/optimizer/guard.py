"""The hard-constraint guard: nothing whose legal verdict is FAIL is ever returned, whatever its
score.

Every candidate goes to the validator before it is scored or ranked, so a layout that breaks a
rule cannot win on yield. The guard does not trust the report it is given: it checks that the
report is about this candidate and these inputs, and that its verdict follows from its own
checks. UNVERIFIED is not FAIL: a layout resting on an open question is kept and says so.

Judging is not part of the search budget. Nothing is returned unjudged, so a candidate the
search found is always judged, however much of the budget the search used; a strategy that
proposes many candidates should propose its best, not everything it looked at.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    ValidationReport,
    digest,
)
from siteplan.contracts.common import Status
from siteplan.contracts.validation import LegalVerdict, legal_verdict
from siteplan.optimizer.interfaces import Validator

Inputs = tuple[str, str, str]  # digests of the site model, the rules and the brief judged


@dataclass(frozen=True)
class Validated:
    candidate: CandidateLayout
    report: ValidationReport


@dataclass(frozen=True)
class Rejection:
    candidate_id: str
    strategy: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GuardResult:
    passed: tuple[Validated, ...]
    rejected: tuple[Rejection, ...]


def inputs_of(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief) -> Inputs:
    return digest(site), digest(rules), digest(brief)


# The one check a study does not lay for (Objectives.study): rule 7(a)(vii)'s tot-lot, laid later
# from the land the study leaves. Its FAIL stays in the report; only the refusal skips it.
STUDY_NOT_LAID = "Organized open space (tot-lot)"


def held_to(report: ValidationReport, study: bool) -> LegalVerdict:
    """The legal verdict a layout is refused on: the report's own, or in a study the verdict of
    every check but the tot-lot's (and every blocking cross-check)."""
    if not study:
        return legal_verdict(report.legal, report.cross_checks)
    return legal_verdict([c for c in report.legal if c.finding.rule != STUDY_NOT_LAID],
                         report.cross_checks)


def why_refused(candidate: CandidateLayout, report: ValidationReport, inputs: Inputs,
                *, study: bool = False) -> list[str]:
    """Why a candidate may not be returned on this report; empty when it may. `study` is the
    optimizer's alone to pass, for a study brief (Objectives.study): the missing tot-lot is then
    not a reason, every other one is; the service's export never passes it."""
    reasons = []
    if report.candidate_ref != digest(candidate):
        reasons.append("the report judged another candidate")
    if (report.site_ref, report.rules_ref, report.brief_ref) != inputs:
        reasons.append("the report judged other inputs than the ones asked about")
    expected = legal_verdict(report.legal, report.cross_checks)
    if report.verdict.legal is not expected:
        reasons.append(f"the report's verdict {report.verdict.legal} does not follow from its "
                       f"checks ({expected})")
    if held_to(report, study) is LegalVerdict.FAIL:
        reasons += [f"{c.finding.rule}: {c.finding.measured} (needs {c.finding.required})"
                    for c in report.legal if c.finding.status is Status.FAIL
                    and not (study and c.finding.rule == STUDY_NOT_LAID)]
        reasons += [f"{d.item}: the {d.source} says {d.theirs}, the validator found {d.ours}"
                    for d in report.cross_checks if d.blocks_pass]
    return reasons


def guard(candidates: Sequence[CandidateLayout], validator: Validator,
          site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
          envelope: BuildableEnvelope | None) -> GuardResult:
    """Judge each candidate and keep those that may be returned."""
    inputs = inputs_of(site, rules, brief)
    passed: list[Validated] = []
    rejected: list[Rejection] = []
    for candidate in candidates:
        report = validator.validate(site, rules, brief, candidate, envelope)
        reasons = why_refused(candidate, report, inputs, study=brief.objectives.study)
        if reasons:
            rejected.append(Rejection(candidate.candidate_id, candidate.strategy, tuple(reasons)))
        else:
            passed.append(Validated(candidate, report))
    return GuardResult(tuple(passed), tuple(rejected))
