"""A run on disk: the contracts it was made from, its candidates, and the record that ties them.

    out/<run_id>/run.json               the record: mode, inputs, digests, candidates, approvals
    out/<run_id>/site.json              CanonicalSiteModel
    out/<run_id>/rules.json             ResolvedRules
    out/<run_id>/brief.json             DesignBrief
    out/<run_id>/envelope.json          BuildableEnvelope
    out/<run_id>/candidates/<id>.json   CandidateLayout
    out/<run_id>/reports/<id>.json      ValidationReport made when the run was (never trusted later)
    out/<run_id>/proposed/candidates/<id>.json   every layout the search proposed, as proposed
    out/<run_id>/proposed/reports/<id>.json      the report the optimizer's guard judged it by

Nothing read back is trusted: `load` parses every contract again and `reference_problems` holds
each candidate's references (site, rules, brief, envelope) against the digests of the files as
they are now, and against the digests recorded when the run was made. A layout the run did not
show is reached only through the record's own list of proposals, in a run whose record holds the
person's approval of the proposal that made it, and only while it and its report still have the
digests recorded with them (`proposal_problems`). The record's approvals are the audit
(audit.py): the proposal's entry is written with the run, and an export's is appended
(`append_approval`); no entry is ever changed or removed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    ValidationReport,
    digest,
)
from siteplan.service.models import ApprovalRecord, Asked, Decision, Mode

log = logging.getLogger("siteplan.service")

RECORD = "run.json"
PROPOSED = "proposed"
INPUTS = {"site": ("site.json", CanonicalSiteModel), "rules": ("rules.json", ResolvedRules),
          "brief": ("brief.json", DesignBrief), "envelope": ("envelope.json", BuildableEnvelope)}


class StoreError(ValueError):
    """A run or candidate that is not there, or a file that no longer parses."""


class StoredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    digest: str
    point: str | None = None


class ProposedCandidate(BaseModel):
    """A layout the search proposed and the optimizer's guard passed, shown or not, with what ties
    it to its files under proposed/."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    digest: str  # of the candidate as proposed
    report_digest: str  # of the report the guard judged it by
    basis: dict[str, str]  # the readings it was laid out for (its interpretation_basis)
    holds_under_every_reading: bool  # no UNVERIFIED legal check of the report turns on a reading
    shown: bool  # one of the alternatives in `candidates`


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: Mode
    project_name: str
    project_file: str
    survey_file: str | None = None
    sheet: dict[str, str] = {}  # the title block's client, architect ... from the project file
    approved: list[str] = []  # the lines the architect approved
    approvals: tuple[ApprovalRecord, ...] = ()  # every approval asked on the run, oldest first
    digests: dict[str, str] = {}  # of the stored inputs, written with them
    candidates: list[StoredCandidate] = []  # the alternatives shown
    # Every layout the search proposed that the guard passed, the alternatives among them; none in
    # a run made before the proposals were kept.
    proposed_candidates: list[ProposedCandidate] = []
    notes: list[str] = []
    unfilled: list[str] = []
    rejected: list[str] = []

    def entry(self, candidate_id: str) -> StoredCandidate:
        found = next((c for c in self.candidates if c.candidate_id == candidate_id), None)
        if found is None:
            raise StoreError(f"Run {self.run_id} has no candidate '{candidate_id}'.")
        return found

    def shows(self, candidate_id: str) -> bool:
        return any(c.candidate_id == candidate_id for c in self.candidates)

    def proposal(self, candidate_id: str) -> ProposedCandidate:
        """A layout this run's search proposed: only one the record lists, and only in a run whose
        record holds the person's approval of the proposal that made it."""
        found = next((c for c in self.proposed_candidates if c.candidate_id == candidate_id),
                     None)
        if found is None:
            raise StoreError(f"Run {self.run_id} has no candidate '{candidate_id}'.")
        if not any(a.asked is Asked.PROPOSAL and a.decision is Decision.APPROVED
                   and a.run_id == self.run_id for a in self.approvals):
            raise StoreError(f"Run {self.run_id} holds no approved proposal; its proposals "
                             "cannot be used.")
        return found


@dataclass(frozen=True)
class Inputs:
    site: CanonicalSiteModel
    rules: ResolvedRules
    brief: DesignBrief
    envelope: BuildableEnvelope


def write_run(folder: Path, record: RunRecord, inputs: Inputs,
              judged: list[tuple[CandidateLayout, ValidationReport]],
              proposed: Sequence[tuple[CandidateLayout, ValidationReport]] = ()) -> RunRecord:
    """Write the contracts, each candidate shown with the report the service made of it, every
    proposal with the report the guard judged it by, and the record holding every digest."""
    (folder / "candidates").mkdir(parents=True)
    (folder / "reports").mkdir()
    (folder / PROPOSED / "candidates").mkdir(parents=True)
    (folder / PROPOSED / "reports").mkdir()
    for key, (name, _) in INPUTS.items():
        (folder / name).write_text(getattr(inputs, key).model_dump_json(indent=1))
    digests = input_digests(inputs)
    for candidate, report in judged:
        (folder / "candidates" / f"{candidate.candidate_id}.json").write_text(
            candidate.model_dump_json(indent=1))
        (folder / "reports" / f"{candidate.candidate_id}.json").write_text(
            report.model_dump_json(indent=1))
    for candidate, report in proposed:
        (folder / PROPOSED / "candidates" / f"{candidate.candidate_id}.json").write_text(
            candidate.model_dump_json(indent=1))
        (folder / PROPOSED / "reports" / f"{candidate.candidate_id}.json").write_text(
            report.model_dump_json(indent=1))
    record = record.model_copy(update={"digests": digests})
    (folder / RECORD).write_text(record.model_dump_json(indent=1))
    return record


def input_digests(inputs: Inputs) -> dict[str, str]:
    """The digests a run's record keeps of the inputs it searched."""
    return {key: digest(getattr(inputs, key)) for key in INPUTS}


def approved_runs_of(out: Path, digests: dict[str, str]) -> list[tuple[str, str]]:
    """Every run in `out` approved and searched on exactly these inputs, with when it was
    approved, oldest first: a request that repeats one is said to before it is approved again,
    so a second identical search is never asked for, or reported, as if it were the first."""
    found = []
    for path in out.glob(f"*/{RECORD}"):
        try:
            record = RunRecord.model_validate_json(path.read_text())
        except (OSError, ValidationError):
            continue
        if record.digests != digests:
            continue
        approval = next((a for a in record.approvals if a.asked is Asked.PROPOSAL
                         and a.decision is Decision.APPROVED), None)
        if approval is not None:
            found.append((approval.at, record.run_id))
    return [(run_id, at) for at, run_id in sorted(found)]


def read_record(out: Path, run_id: str) -> RunRecord:
    path = out / run_id / RECORD
    if not path.is_file():
        raise StoreError(f"There is no run '{run_id}'.")
    return RunRecord.model_validate_json(path.read_text())


def append_approval(out: Path, run_id: str, entry: ApprovalRecord) -> RunRecord:
    """The run's record as it stands on disk, with one more approval at the end, written whole
    (a new file put in the old one's place, so a record is never left half written)."""
    record = read_record(out, run_id)
    record = record.model_copy(update={"approvals": (*record.approvals, entry)})
    path = out / run_id / RECORD
    partial = path.with_name(f".{RECORD}.partial")
    partial.write_text(record.model_dump_json(indent=1))
    os.replace(partial, path)
    return record


def _parse(path: Path, model: type[BaseModel]):
    try:
        return model.model_validate_json(path.read_text())
    except (OSError, ValidationError, ValueError) as error:
        log.warning("stored file refused: %s (%s)", path, error)
        raise StoreError(f"The stored {path.name} cannot be read as a {model.__name__}; the "
                         "run has to be made again.") from None


def load_inputs(out: Path, record: RunRecord) -> Inputs:
    folder = out / record.run_id
    return Inputs(**{key: _parse(folder / name, model) for key, (name, model) in INPUTS.items()})


def load_candidate(out: Path, record: RunRecord, candidate_id: str) -> CandidateLayout:
    record.entry(candidate_id)
    return _parse(out / record.run_id / "candidates" / f"{candidate_id}.json", CandidateLayout)


def load_report(out: Path, record: RunRecord, candidate_id: str) -> ValidationReport:
    record.entry(candidate_id)
    return _parse(out / record.run_id / "reports" / f"{candidate_id}.json", ValidationReport)


def load_proposed(out: Path, record: RunRecord, candidate_id: str
                  ) -> tuple[CandidateLayout, ValidationReport]:
    """A layout the search proposed, and the report the guard judged it by: only one the record
    lists (`RunRecord.proposal`)."""
    record.proposal(candidate_id)
    folder = out / record.run_id / PROPOSED
    return (_parse(folder / "candidates" / f"{candidate_id}.json", CandidateLayout),
            _parse(folder / "reports" / f"{candidate_id}.json", ValidationReport))


def reference_problems(record: RunRecord, inputs: Inputs, candidate: CandidateLayout,
                       recorded: str) -> list[str]:
    """Every reference that does not hold: a contract changed since the run was made, a
    candidate that is not the one recorded for the id asked for (`recorded`, its digest), or a
    candidate (or the rules, or the envelope) made for other inputs than the ones stored."""
    now = {key: digest(getattr(inputs, key)) for key in INPUTS}
    found = [f"the stored {INPUTS[key][0]} changed since the run was made (digest {now[key]}, "
             f"recorded {record.digests.get(key)})" for key in INPUTS
             if now[key] != record.digests.get(key)]
    if digest(candidate) != recorded:
        found.append(f"the stored candidate changed since the run was made (digest "
                     f"{digest(candidate)}, recorded {recorded})")
    refs = (("candidate.site_ref", candidate.site_ref, now["site"]),
            ("candidate.rules_ref", candidate.rules_ref, now["rules"]),
            ("candidate.brief_ref", candidate.brief_ref, now["brief"]),
            ("candidate.envelope_ref", candidate.envelope_ref, now["envelope"]),
            ("rules.site_ref", inputs.rules.site_ref, now["site"]),
            ("envelope.site_ref", inputs.envelope.site_ref, now["site"]),
            ("envelope.rules_ref", inputs.envelope.rules_ref, now["rules"]))
    found += [f"{name} is {theirs}, not the stored file's {ours}" for name, theirs, ours in refs
              if theirs != ours]
    return found


def proposal_problems(record: RunRecord, inputs: Inputs, candidate_id: str,
                      candidate: CandidateLayout, report: ValidationReport) -> list[str]:
    """`reference_problems` for a layout the run did not show, and its stored report held to the
    digest recorded with it."""
    entry = record.proposal(candidate_id)
    found = reference_problems(record, inputs, candidate, entry.digest)
    if digest(report) != entry.report_digest:
        found.append(f"the stored report of the proposal changed since the run was made (digest "
                     f"{digest(report)}, recorded {entry.report_digest})")
    return found
