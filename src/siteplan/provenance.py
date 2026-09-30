"""How far each input can be trusted, from checked against a document down to not known.

Every value the engine plans on carries one of these, next to where it came from, so a report
can say which of its answers rest on a guess. The order runs strongest first: a result is only as
good as the weakest input it used.
"""

from __future__ import annotations

from enum import StrEnum


class Provenance(StrEnum):
    VERIFIED = "VERIFIED"  # checked against the document itself (a certificate, an approval)
    USER_CONFIRMED = "USER_CONFIRMED"  # the architect said so
    EXTRACTED = "EXTRACTED"  # read off the survey by the engine
    ASSUMED_FOR_TEST = "ASSUMED_FOR_TEST"  # taken as given so a test can run; not evidence
    UNVERIFIED = "UNVERIFIED"  # not known, or known not to be confirmed


ORDER = tuple(Provenance)


def weakest(*statuses: Provenance | str | None) -> Provenance:
    """The least trustworthy of the statuses given; UNVERIFIED when there are none."""
    known = [Provenance(s) for s in statuses if s]
    return max(known, key=ORDER.index) if known else Provenance.UNVERIFIED


def confirmed(status: Provenance | str | None) -> bool:
    """Whether a value may be relied on as a fact rather than a guess."""
    return status in (Provenance.VERIFIED, Provenance.USER_CONFIRMED, Provenance.EXTRACTED)
