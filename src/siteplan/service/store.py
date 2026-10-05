"""A run on disk: the contracts it was made from, its candidates, and the record that ties them.

    out/<run_id>/run.json               the record: mode, inputs, digests, candidates, approvals
    out/<run_id>/site.json              CanonicalSiteModel
    out/<run_id>/rules.json             ResolvedRules
    out/<run_id>/brief.json             DesignBrief
    out/<run_id>/envelope.json          BuildableEnvelope
    out/<run_id>/candidates/<id>.json   CandidateLayout
    out/<run_id>/reports/<id>.json      ValidationReport made when the run was (never trusted later)

Nothing read back is trusted: `load` parses every contract again and `reference_problems` holds
each candidate's references (site, rules, brief, envelope) against the digests of the files as
they are now, and against the digests recorded when the run was made. The record's approvals are
the audit (audit.py): the proposal's entry is written with the run, and an export's is appended
(`append_approval`); no entry is ever changed or removed.
"""

from __future__ import annotations

import logging
import os
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
from siteplan.service.models import ApprovalRecord, Mode

log = logging.getLogger("siteplan.service")

RECORD = "run.json"
INPUTS = {"site": ("site.json", CanonicalSiteModel), "rules": ("rules.json", ResolvedRules),
          "brief": ("brief.json", DesignBrief), "envelope": ("envelope.json", BuildableEnvelope)}


class StoreError(ValueError):
    """A run or candidate that is not there, or a file that no longer parses."""


class StoredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    digest: str
    point: str | None = None


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
    candidates: list[StoredCandidate] = []
    notes: list[str] = []
    unfilled: list[str] = []
    rejected: list[str] = []

    def entry(self, candidate_id: str) -> StoredCandidate:
        found = next((c for c in self.candidates if c.candidate_id == candidate_id), None)
        if found is None:
            raise StoreError(f"Run {self.run_id} has no candidate '{candidate_id}'.")
        return found


@dataclass(frozen=True)
class Inputs:
    site: CanonicalSiteModel
    rules: ResolvedRules
    brief: DesignBrief
    envelope: BuildableEnvelope


def write_run(folder: Path, record: RunRecord, inputs: Inputs,
              judged: list[tuple[CandidateLayout, ValidationReport]]) -> RunRecord:
    """Write the contracts, each candidate with the report the service made of it, and the record
    holding every digest."""
    (folder / "candidates").mkdir(parents=True)
    (folder / "reports").mkdir()
    digests = {}
    for key, (name, _) in INPUTS.items():
        model = getattr(inputs, key)
        (folder / name).write_text(model.model_dump_json(indent=1))
        digests[key] = digest(model)
    for candidate, report in judged:
        (folder / "candidates" / f"{candidate.candidate_id}.json").write_text(
            candidate.model_dump_json(indent=1))
        (folder / "reports" / f"{candidate.candidate_id}.json").write_text(
            report.model_dump_json(indent=1))
    record = record.model_copy(update={"digests": digests})
    (folder / RECORD).write_text(record.model_dump_json(indent=1))
    return record


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


def reference_problems(record: RunRecord, inputs: Inputs, candidate: CandidateLayout
                       ) -> list[str]:
    """Every reference that does not hold: a contract changed since the run was made, or a
    candidate (or the rules, or the envelope) made for other inputs than the ones stored."""
    now = {key: digest(getattr(inputs, key)) for key in INPUTS}
    found = [f"the stored {INPUTS[key][0]} changed since the run was made (digest {now[key]}, "
             f"recorded {record.digests.get(key)})" for key in INPUTS
             if now[key] != record.digests.get(key)]
    recorded = record.entry(candidate.candidate_id).digest
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
