"""What a validation report says a candidate rests on, in the words the architect reads.

Every option states its UNVERIFIED items and the readings they rest on. A check the validator ran
under every reading of an open question and got different answers for is reading-dependent: the
candidate holds only under the readings that pass it. Everything else UNVERIFIED rests on an input
nobody has confirmed (the street's width, the loading of the paving) and is said as it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from siteplan.contracts import ValidationReport
from siteplan.contracts.common import Status
from siteplan.contracts.validation import Check, Family

# UNVERIFIED on every layout, whatever the plan: said once in the notes, not on each option.
UNIVERSAL = ("Height above sea level", "Fire access: 45 t hard surface")


@dataclass(frozen=True)
class RestsOn:
    """The readings a candidate's verdict depends on: interpretation id -> the readings under which
    the checks that depend on it pass."""

    readings: dict[str, tuple[str, ...]]
    checks: tuple[str, ...]  # the reading-dependent checks, by rule

    @property
    def holds_under_every_reading(self) -> bool:
        return not self.checks


def _passing(check: Check, interpretation: str) -> list[str]:
    results = check.by_reading.get(interpretation, {})
    return [reading for reading, status in results.items() if status in (Status.PASS, Status.INFO,
                                                                       Status.NOT_CHECKED)]


def rests_on(report: ValidationReport) -> RestsOn:
    readings: dict[str, set[str]] = {}
    checks = []
    for check in report.legal:
        if check.finding.status is not Status.UNVERIFIED:
            continue
        dependent = False
        for interpretation, results in check.by_reading.items():
            if len(set(results.values())) > 1:
                dependent = True
                readings.setdefault(interpretation, set()).update(_passing(check, interpretation))
        if dependent:
            checks.append(check.finding.rule)
    return RestsOn({k: tuple(sorted(v)) for k, v in readings.items()}, tuple(checks))


def caveats(report: ValidationReport) -> list[str]:
    """Every UNVERIFIED legal item and what it rests on, then every design target the layout
    misses. The two items every layout leaves open are left out: the notes say them once."""
    out: list[str] = []
    for check in report.legal:
        finding = check.finding
        if finding.status is not Status.UNVERIFIED or finding.rule.startswith(UNIVERSAL):
            continue
        varying = {i: r for i, r in check.by_reading.items() if len(set(r.values())) > 1}
        if varying:
            says = "; ".join(
                f"holds only if {interpretation} is read as "
                + " or ".join(f"'{reading}'" for reading in _passing(check, interpretation))
                for interpretation in varying)
            out.append(f"UNVERIFIED {finding.rule}: {says}")
        else:
            out.append(f"UNVERIFIED {finding.rule}: {finding.measured}"[:240])
    for target in report.design_targets:
        if target.margin > 0 and not target.meets_target:
            subject = f" {target.subject}" if target.subject else ""
            out.append(f"design target missed ({target.item.value}{subject}): "
                       f"{target.provided:,.2f} {target.unit} provided against a target of "
                       f"{target.target:,.2f} (the legal minimum is {target.legal_minimum:,.2f}); "
                       "a margin is the firm's, never law")
    return list(dict.fromkeys(out))


def failed(report: ValidationReport) -> list[str]:
    """Why a report may not be offered: the legal checks that FAIL."""
    return [f"{c.finding.rule}: {c.finding.measured}" for c in report.legal
            if c.finding.status is Status.FAIL and c.family is not Family.PROGRAM]
