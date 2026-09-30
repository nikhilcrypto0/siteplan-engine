"""A rule check's result: what was measured, what the rule asks, and which clause says so."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"  # an input the answer depends on is not known or not confirmed
    NOT_CHECKED = "NOT_CHECKED"  # the engine does not model this rule
    INFO = "INFO"  # a classification that drives other checks, not a verdict


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
