"""The independent verdict, made again whenever a stored candidate is used.

The service never relies on a report it stored. `judge_again` parses the stored contracts, holds
every reference against the files, and calls the independent validator itself
(`siteplan.validator.validate`, looked up when called so that a test can watch every call).
What blocks an export whatever the architect acknowledges (`refusals`): a reference that does
not hold, a legal FAIL, a discrepancy that blocks a pass, or a report that could not measure the
candidate. What an export needs acknowledged and approved (`unresolved_items`): every legal check
the fresh report leaves UNVERIFIED. The program verdict (unit mix, units, the club house asked)
is reported and never blocks or grants anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from siteplan import validator
from siteplan.contracts import CandidateLayout, ValidationReport
from siteplan.contracts.common import Status
from siteplan.contracts.validation import Check, LegalVerdict
from siteplan.service import store
from siteplan.service.models import UnresolvedItem
from siteplan.service.store import Inputs, RunRecord

# How the validator words what it could not measure or compare (validator/refusals.py
# library_check, validator/validate.py _discrepancies): such a report is never exported.
NOT_MEASURED = ": could not be measured"
NOT_COMPARED = "could not be compared"
NOT_RECOMPUTED = "could not be recomputed"
PASSING = (Status.PASS, Status.INFO, Status.NOT_CHECKED)


@dataclass(frozen=True)
class Judged:
    record: RunRecord
    inputs: Inputs
    candidate: CandidateLayout
    report: ValidationReport  # made now, from the stored contracts
    references: tuple[str, ...]  # references that do not hold


def judge_again(out: Path, record: RunRecord, candidate_id: str) -> Judged:
    inputs = store.load_inputs(out, record)
    candidate = store.load_candidate(out, record, candidate_id)
    references = store.reference_problems(record, inputs, candidate)
    report = validator.validate(inputs.site, inputs.rules, inputs.brief, candidate,
                                inputs.envelope)
    return Judged(record, inputs, candidate, report, tuple(references))


def item_name(check: Check) -> str:
    """The name an UNVERIFIED item is acknowledged by: the rule, and its subject when the rule's
    own words do not already name it (a pair of towers 'T1/T2' is named by 'T1 / T2')."""
    rule, subject = check.finding.rule, check.subject
    named = not subject or all(part.strip() in rule for part in subject.split("/"))
    return rule if named else f"{rule} ({subject})"


def holds_under(check: Check) -> dict[str, list[str]]:
    """For each open reading the check's result turns on, the readings under which it passes."""
    return {interpretation: sorted(r for r, s in results.items() if s in PASSING)
            for interpretation, results in check.by_reading.items()
            if len(set(results.values())) > 1}


def unresolved_items(report: ValidationReport) -> list[UnresolvedItem]:
    found: dict[str, UnresolvedItem] = {}
    for check in report.legal:
        if check.finding.status is not Status.UNVERIFIED:
            continue
        name = item_name(check)
        found.setdefault(name, UnresolvedItem(
            item=name, family=check.family, measured=check.finding.measured,
            required=check.finding.required, holds_under=holds_under(check)))
    return list(found.values())


def unmeasured(report: ValidationReport, candidate: CandidateLayout) -> list[str]:
    """Why the validator could not measure the candidate, if it could not: no tower measured
    (no usable net plot, a number that is not a number, a shape the geometry library refused), a
    group of checks it could not finish, or a claim it could not compare."""
    found = []
    if not candidate.towers or len(report.recomputed.towers) != len(candidate.towers):
        found.append("the validator could not measure the candidate's towers")
    found += [f"{c.finding.rule}: {c.finding.measured}" for c in report.legal
              if c.finding.rule.endswith(NOT_MEASURED)]
    found += [f"{d.item}: {d.ours}" for d in report.cross_checks
              if d.item.endswith(NOT_COMPARED) or d.ours.startswith(NOT_RECOMPUTED)]
    return found


def refusals(judged: Judged) -> list[str]:
    """Everything that keeps the candidate from being exported, whatever is acknowledged."""
    report = judged.report
    out = list(judged.references)
    out += unmeasured(report, judged.candidate)
    out += [f"FAIL {c.finding.rule}: {c.finding.measured} (needs {c.finding.required})"
            for c in report.legal if c.finding.status is Status.FAIL]
    out += [f"cross-check {d.item}: the {d.source} says {d.theirs}, the validator found "
            f"{d.ours}" for d in report.cross_checks if d.blocks_pass]
    if report.verdict.legal is LegalVerdict.FAIL and not out:
        out.append("the legal verdict is FAIL")
    return list(dict.fromkeys(out))
