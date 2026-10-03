"""ValidationReport: an independent verdict on one candidate.

The validator judges a CandidateLayout from the site model, the resolved rules and the brief,
recomputing what it measures; the generator's claims and the envelope are compared, never
trusted. The legal verdict and the program verdict are separate: a missed unit mix is not
illegal. Where an interpretation is open (selected ALL), a check is run under every reading,
and a result that holds under only some of them is UNVERIFIED, naming the reading.

The verdict rule is here, not in the validator, so every report is held to the same one:
FAIL if any legal check fails or a discrepancy blocks a pass; otherwise UNVERIFIED if any legal
check is unverified; otherwise PASS. NOT_CHECKED is listed beside the verdict, never folded
into it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import model_validator

from siteplan.contracts.accounting import PartitionLedger, RuleLayers
from siteplan.contracts.common import Contract, Finding, Part, Status


class Family(StrEnum):
    SETBACK = "SETBACK"
    SPACING = "SPACING"
    ROADS = "ROADS"
    DEAD_END = "DEAD_END"
    FIRE = "FIRE"
    HEIGHT = "HEIGHT"
    OPEN_SPACE = "OPEN_SPACE"
    PARKING = "PARKING"
    AMENITIES = "AMENITIES"
    WATER = "WATER"
    GREEN_STRIP = "GREEN_STRIP"
    EGRESS = "EGRESS"
    ACCOUNTING = "ACCOUNTING"
    CONSISTENCY = "CONSISTENCY"
    PROGRAM = "PROGRAM"
    OTHER = "OTHER"


class LegalVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class ProgramVerdict(StrEnum):
    MET = "MET"
    PARTLY_MET = "PARTLY_MET"
    NOT_MET = "NOT_MET"


def combine_readings(results: dict[str, Status]) -> Status:
    """One status from a check's result under each reading: PASS or FAIL only when every
    reading agrees; otherwise UNVERIFIED."""
    values = set(results.values())
    if values == {Status.PASS}:
        return Status.PASS
    if values == {Status.FAIL}:
        return Status.FAIL
    return Status.UNVERIFIED


class Check(Part):
    family: Family
    subject: str | None = None  # a tower, a pair of towers, a road
    finding: Finding
    by_reading: dict[str, dict[str, Status]] = {}  # interpretation id -> reading -> result

    @model_validator(mode="after")
    def _status_follows_the_readings(self) -> Check:
        for interpretation, results in self.by_reading.items():
            combined = combine_readings(results)
            if combined is not Status.PASS and self.finding.status is Status.PASS:
                raise ValueError(f"{self.finding.rule}: PASS overall but {combined} under the "
                                 f"readings of {interpretation}")
        return self


class TowerMeasure(Part):
    name: str
    physical_height_m: float
    rule_height_m_by_reading: dict[str, float] = {}
    band_by_reading: dict[str, str] = {}
    setback_m: float  # measured from the net plot
    required_setback_m_by_reading: dict[str, float] = {}


class PairMeasure(Part):
    a: str
    b: str
    gap_m: float
    required_m: float | None = None


class Recomputed(Part):
    towers: list[TowerMeasure] = []
    pairs: list[PairMeasure] = []
    quantities: dict[str, float] = {}  # built-up, parking need, open space by reading, ...
    units_by_type: dict[str, int] = {}


class Discrepancy(Part):
    item: str
    source: Literal["generator", "envelope"]
    theirs: str
    ours: str
    blocks_pass: bool


class Accounting(Part):
    partition: PartitionLedger | None = None
    partition_problems: list[str] = []
    rule_layers: RuleLayers | None = None


class Verdict(Part):
    legal: LegalVerdict
    program: ProgramVerdict
    reasons: list[str] = []


def legal_verdict(checks: list[Check], cross_checks: list[Discrepancy]) -> LegalVerdict:
    statuses = {c.finding.status for c in checks}
    if Status.FAIL in statuses or any(d.blocks_pass for d in cross_checks):
        return LegalVerdict.FAIL
    if Status.UNVERIFIED in statuses:
        return LegalVerdict.UNVERIFIED
    return LegalVerdict.PASS


def program_verdict(checks: list[Check]) -> ProgramVerdict:
    statuses = {c.finding.status for c in checks} - {Status.INFO, Status.NOT_CHECKED}
    if not statuses or statuses == {Status.PASS}:
        return ProgramVerdict.MET
    if Status.PASS not in statuses and statuses <= {Status.FAIL}:
        return ProgramVerdict.NOT_MET
    return ProgramVerdict.PARTLY_MET


class ValidationReport(Contract):
    candidate_ref: str
    site_ref: str
    rules_ref: str
    brief_ref: str
    envelope_ref: str | None = None  # given only for cross-checking
    validator_version: str
    recomputed: Recomputed = Recomputed()
    legal: list[Check] = []
    program: list[Check] = []
    accounting: Accounting = Accounting()
    cross_checks: list[Discrepancy] = []
    not_checked: list[str] = []
    verdict: Verdict

    @model_validator(mode="after")
    def _verdict_follows_the_checks(self) -> ValidationReport:
        expected = legal_verdict(self.legal, self.cross_checks)
        if self.verdict.legal is not expected:
            raise ValueError(f"legal verdict {self.verdict.legal} does not follow from the checks "
                             f"({expected})")
        if any(c.family is Family.PROGRAM for c in self.legal):
            raise ValueError("a program check sits among the legal checks")
        return self
