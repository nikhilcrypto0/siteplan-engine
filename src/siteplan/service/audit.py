"""The approval audit: every approval the service asks of the person, written down as it is asked.

    out/approvals.jsonl     every approval asked, one JSON line each, refused ones included
    out/<run_id>/run.json   the run's own (`RunRecord.approvals`): the proposal that made it, and
                            every export approval asked on it

An entry (models.ApprovalRecord) is the service's own account: the title and lines it showed the
person and their digest, the answer (APPROVED, REJECTED, UNANSWERED or CHANNEL_FAILURE), the class
of the approver the host chose, the time in UTC, and for an export the fresh report's UNVERIFIED
items as it names them and that report's digest. Nothing in it is taken from the caller of an
operation. Entries are only appended, and each is written before anything the approval allows
runs: if it cannot be written, the operation fails and nothing runs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from siteplan.service.models import ApprovalRecord, Asked, Decision

LOG = "approvals.jsonl"


def asked_digest(title: str, lines: Sequence[str]) -> str:
    """The sha256 of exactly what the person was shown."""
    text = json.dumps({"title": title, "lines": list(lines)}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def entry(asked: Asked, title: str, lines: Sequence[str], decision: Decision, channel: str, *,
          run_id: str | None = None, candidate_id: str | None = None,
          acknowledged: Sequence[str] = (), report_digest: str | None = None) -> ApprovalRecord:
    return ApprovalRecord(
        asked=asked, title=title, lines=tuple(lines), asked_digest=asked_digest(title, lines),
        decision=decision, channel=channel,
        at=datetime.now(UTC).isoformat(timespec="milliseconds"), run_id=run_id,
        candidate_id=candidate_id, acknowledged=tuple(acknowledged), report_digest=report_digest)


def append(out: Path, record: ApprovalRecord) -> None:
    """Add an entry to the service's approvals log."""
    out.mkdir(parents=True, exist_ok=True)
    with (out / LOG).open("a", encoding="utf-8") as log_file:
        log_file.write(record.model_dump_json() + "\n")


def read(out: Path) -> list[ApprovalRecord]:
    """The service's approvals log, oldest first (for a reviewer; the service decides nothing
    from it)."""
    path = out / LOG
    if not path.is_file():
        return []
    return [ApprovalRecord.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
