"""A rule check's result: what was measured, what the rule asks, and which clause says so."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    # The answer depends on an unresolved reading of the law or an unverified required site fact
    # (named in the check's rests_on). Stored before 2026-10-13 as "UNVERIFIED", which still reads
    # as this, and UNVERIFIED stays its name in code.
    CONDITIONAL = "CONDITIONAL"
    UNVERIFIED = "CONDITIONAL"
    NOT_CHECKED = "NOT_CHECKED"  # the engine does not model this rule
    INFO = "INFO"  # a classification that drives other checks, not a verdict

    @classmethod
    def _missing_(cls, value):
        return cls.CONDITIONAL if value == "UNVERIFIED" else None


@dataclass(frozen=True)
class Finding:
    rule: str
    status: Status
    measured: str
    required: str
    clause: str
    note: str = ""


def narrower_than(shape, width_m: float) -> bool:
    """True if any part of the shape is narrower than width_m (a noticeable share of its area
    disappears when every part thinner than the width is removed)."""
    from siteplan.geometry import opening

    return opening(shape, width_m).area < shape.area * 0.98
