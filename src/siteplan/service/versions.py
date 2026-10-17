"""Versions of a layout (2026-10-16, Stage B of the architect's roadmap): a layout the architect
keeps or changes is saved in its run's folder as a version of its own, never in place of what the
run made.

    out/<run_id>/versions/<version_id>/version.json    its parent and the parent's digest, edits
    out/<run_id>/versions/<version_id>/candidate.json  CandidateLayout, its id the version's
    out/<run_id>/versions/<version_id>/report.json     the report made when it was saved

A version is written once and never changed: saving again makes another. Its parent is a layout
the run showed, one its search proposed (only in a run whose record holds the approved proposal)
or another version, and the parent's digest is recorded; the version is used only while that
digest, its own and its report's still hold, and while it was made for exactly the run's stored
inputs (`store.reference_problems`). The independent validator judges it when it is saved and
again whenever it is used (`judge.judge_again`); nothing stored is trusted.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from siteplan import validator
from siteplan.contracts import CandidateLayout, ValidationReport, digest
from siteplan.service import store
from siteplan.service.store import Inputs, RunRecord, StoreError

VERSIONS = "versions"
FILES = ("version.json", "candidate.json", "report.json")
_SUFFIX = re.compile(r"-v\d+$")


class LayoutVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    run_id: str
    parent_id: str  # a layout the run showed or proposed, or another version
    parent_digest: str  # the parent's digest when this version was saved
    digest: str  # of candidate.json
    report_digest: str  # of report.json, the report made when it was saved
    edits: list[str] = []  # what was changed from the parent, in the engine's words
    note: str = ""
    saved_at: str  # UTC, ISO 8601


def folder(out: Path, run_id: str, version_id: str) -> Path:
    return out / run_id / VERSIONS / version_id


def exists(out: Path, record: RunRecord, ident: str) -> bool:
    return (folder(out, record.run_id, ident) / FILES[0]).is_file()


def listed(out: Path, record: RunRecord) -> list[LayoutVersion]:
    """Every version saved in the run, oldest first."""
    found = []
    for path in sorted((out / record.run_id / VERSIONS).glob(f"*/{FILES[0]}")):
        found.append(store._parse(path, LayoutVersion))
    return sorted(found, key=lambda v: (v.saved_at, v.version_id))


def load(out: Path, record: RunRecord, version_id: str
         ) -> tuple[LayoutVersion, CandidateLayout, ValidationReport]:
    path = folder(out, record.run_id, version_id)
    if not (path / FILES[0]).is_file():
        raise StoreError(f"Run {record.run_id} has no version '{version_id}'.")
    version = store._parse(path / FILES[0], LayoutVersion)
    return (version, store._parse(path / FILES[1], CandidateLayout),
            store._parse(path / FILES[2], ValidationReport))


def parent(out: Path, record: RunRecord, inputs: Inputs, parent_id: str,
           _seen: frozenset[str] = frozenset()) -> tuple[CandidateLayout, str, list[str]]:
    """A layout a version may be made from, the digest recorded for it and every reference of it
    that does not hold: one the run showed, one its search proposed, or a version."""
    if exists(out, record, parent_id):
        version, candidate, report = load(out, record, parent_id)
        return candidate, version.digest, problems(out, record, inputs, version, candidate,
                                                   report, _seen)
    if record.shows(parent_id):
        candidate = store.load_candidate(out, record, parent_id)
        recorded = record.entry(parent_id).digest
        return candidate, recorded, store.reference_problems(record, inputs, candidate, recorded)
    candidate, report = store.load_proposed(out, record, parent_id)
    recorded = record.proposal(parent_id).digest
    return candidate, recorded, store.proposal_problems(record, inputs, parent_id, candidate,
                                                        report)


def problems(out: Path, record: RunRecord, inputs: Inputs, version: LayoutVersion,
             candidate: CandidateLayout, report: ValidationReport,
             _seen: frozenset[str] = frozenset()) -> list[str]:
    """Every reference of a version that does not hold: its own files, the run's inputs, and its
    parent as it was when the version was saved, back along the line to the run's own layout."""
    found = store.reference_problems(record, inputs, candidate, version.digest)
    if candidate.candidate_id != version.version_id:
        found.append(f"the stored version is {candidate.candidate_id}, not {version.version_id}")
    if digest(report) != version.report_digest:
        found.append(f"the stored report of version {version.version_id} changed since it was "
                     f"saved (digest {digest(report)}, recorded {version.report_digest})")
    seen = _seen | {version.version_id}
    if version.parent_id in seen:
        return [*found, f"version {version.version_id}'s line of parents runs in a circle"]
    try:
        _, recorded, broken = parent(out, record, inputs, version.parent_id, seen)
    except StoreError as error:
        return [*found, f"the parent {version.parent_id} cannot be used: {error}"]
    if recorded != version.parent_digest:
        found.append(f"the parent {version.parent_id} is not the one this version was made from "
                     f"(digest {recorded}, recorded {version.parent_digest})")
    return [*found, *(f"its parent {version.parent_id}: {p}" for p in broken)]


def next_id(out: Path, record: RunRecord, parent_id: str) -> str:
    """The next version of a layout's line: '<the layout it began from>-v<n>'."""
    root = _SUFFIX.sub("", parent_id)
    taken = {v.version_id for v in listed(out, record)}
    n = 1
    while f"{root}-v{n}" in taken:
        n += 1
    return f"{root}-v{n}"


def make_version(out: Path, record: RunRecord, parent_id: str,
                 candidate: CandidateLayout | None = None, edits: list[str] | None = None,
                 note: str = "") -> tuple[LayoutVersion, CandidateLayout, ValidationReport]:
    """Save a version of `parent_id` in its run: the parent unchanged when no candidate is given,
    else the candidate given (an edit). Refused when the parent's references do not hold or the
    candidate was not made for the run's stored inputs. The validator judges it now."""
    inputs = store.load_inputs(out, record)
    base, recorded, broken = parent(out, record, inputs, parent_id)
    if broken:
        raise StoreError(f"{parent_id} cannot be used: " + "; ".join(broken))
    version_id = next_id(out, record, parent_id)
    made = (candidate or base).model_copy(update={"candidate_id": version_id})
    wrong = store.reference_problems(record, inputs, made, digest(made))
    if wrong:
        raise StoreError("the layout was not made for this run's inputs: " + "; ".join(wrong))
    report = validator.validate(inputs.site, inputs.rules, inputs.brief, made, inputs.envelope)
    version = LayoutVersion(
        version_id=version_id, run_id=record.run_id, parent_id=parent_id,
        parent_digest=recorded, digest=digest(made), report_digest=digest(report),
        edits=list(edits or []), note=note, saved_at=datetime.now(UTC).isoformat())
    _write_once(folder(out, record.run_id, version_id), version, made, report)
    return version, made, report


def _write_once(path: Path, version: LayoutVersion, candidate: CandidateLayout,
                report: ValidationReport) -> None:
    """The version's three files, the record last and put in place whole, never over another."""
    try:
        path.mkdir(parents=True)
    except FileExistsError:
        raise StoreError(f"version {version.version_id} already exists") from None
    (path / FILES[1]).write_text(candidate.model_dump_json(indent=1))
    (path / FILES[2]).write_text(report.model_dump_json(indent=1))
    partial = path / f".{FILES[0]}.partial"
    partial.write_text(version.model_dump_json(indent=1))
    os.replace(partial, path / FILES[0])
