"""Open readings of the law, and how one check is run under every one of them.

ResolvedRules marks each open question an Interpretation with its readings; `selected` is one
reading, or ALL. A check that depends on a question runs once per reading it must evaluate, and
the results combine as the contract says (`combine_readings`): PASS or FAIL only when every
reading agrees, otherwise UNVERIFIED, with the readings named so nobody has to guess which.

The reading names below are a convention shared with the adapters and the contract fixtures
(the contract fixes the interpretation ids, not the names of their readings). A name this
validator does not know how to evaluate is UNVERIFIED, never guessed.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from siteplan.contracts.common import Basis, Finding, Provenance, Status
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.validation import Check, Family, combine_readings

COUNTED, NOT_COUNTED = "counted", "not_counted"  # stilt_in_rule_height
ALLOWED, NOT_ALLOWED = "allowed", "not_allowed"  # circulation_in_setback
OUTER_EDGE, CENTRELINE = "outer_edge", "centreline"  # fire_turning_radius
MINIMUM_APPROACH, AUTHORITY_CHOICE = "minimum", "authority_choice"  # approach_width
TALLER_GOVERNS, EACH_OWN = "taller_governs", "each_own"  # mixed_height_spacing
AT_GROUND, ANYWHERE = "at_ground", "anywhere"  # visitor_parking
MINIMUM_SHARE, SHARE_OR_CAP = "minimum_3_percent", "up_to_3_percent_or_cap"  # amenity_share
# Whose Table V column applies is not an Interpretation: it is ResolvedRules.jurisdiction. When
# it is OPEN the validator evaluates both columns, under this key.
TABLE_V_COLUMN = "jurisdiction.table_v_column"

Assignment = dict[str, str]  # interpretation id -> the reading this cell is evaluated under


@dataclass(frozen=True)
class Cell:
    """One check's result under one assignment of readings."""

    status: Status
    measured: str
    required: str = ""
    note: str = ""


def unknown_reading(interpretation_id: str, reading: str) -> Cell:
    return Cell(Status.UNVERIFIED, f"reading '{reading}' of {interpretation_id}",
                "a reading this validator can evaluate",
                "The reading is not one the validator knows how to evaluate; it is not guessed.")


def basis_note(rule_value) -> str:
    """What a rule value rests on, when that is not an order's own text: an unresolved reading, a
    planning assumption, something nobody has confirmed. Empty for a settled, verified value."""
    if rule_value.status is Provenance.VERIFIED and rule_value.basis is Basis.LEGAL_RULE:
        return ""
    return (f"Rests on {rule_value.basis.value}, {rule_value.status.value}"
            + (f": {rule_value.note}" if rule_value.note else "."))


def verdict(ok: bool) -> Status:
    return Status.PASS if ok else Status.FAIL


def combine_statuses(statuses: Sequence[Status]) -> Status:
    """One status for several: the same when they all agree (INFO and NOT_CHECKED included),
    otherwise the contract's rule, which is UNVERIFIED."""
    distinct = set(statuses)
    if len(distinct) == 1:
        return distinct.pop()
    return combine_readings(dict(enumerate(statuses)))


@dataclass(frozen=True)
class Evaluated:
    """A check's cells over every combination of the readings it depends on."""

    ids: tuple[str, ...]
    cells: tuple[tuple[Assignment, Cell], ...]
    varying: tuple[str, ...]  # the interpretations with more than one reading to evaluate

    @property
    def status(self) -> Status:
        return combine_statuses([cell.status for _, cell in self.cells])

    @property
    def by_reading(self) -> dict[str, dict[str, Status]]:
        out: dict[str, dict[str, Status]] = {}
        for interpretation in self.ids:
            readings = dict.fromkeys(a[interpretation] for a, _ in self.cells)
            out[interpretation] = {
                reading: combine_statuses([c.status for a, c in self.cells
                                           if a[interpretation] == reading])
                for reading in readings}
        return out

    def _joined(self, pick: Callable[[Cell], str]) -> str:
        """One text for the cells: the text itself when they agree, otherwise each distinct text
        with the readings it holds under (leaving out an open question that makes no
        difference to it)."""
        grouped: dict[str, list[Assignment]] = {}
        for assignment, cell in self.cells:
            text = pick(cell)
            if text:
                grouped.setdefault(text, []).append(assignment)
        if len(grouped) <= 1:
            return next(iter(grouped), "")
        every = {i: set(a[i] for a, _ in self.cells) for i in self.varying}
        parts = []
        for text, members in grouped.items():
            labels = []
            for i in self.varying:
                held = list(dict.fromkeys(a[i] for a in members))
                if set(held) != every[i]:
                    labels.append("/".join(held))
            parts.append(f"{'+'.join(labels)}: {text}" if labels else text)
        return "; ".join(parts)

    @property
    def measured(self) -> str:
        return self._joined(lambda c: c.measured)

    @property
    def required(self) -> str:
        return self._joined(lambda c: c.required)

    @property
    def note(self) -> str:
        notes = dict.fromkeys(c.note for _, c in self.cells if c.note)
        return " ".join(notes)

    @property
    def readings_note(self) -> str:
        parts = [f"{interpretation}: " + ", ".join(f"{r} {s.value}" for r, s in marginal.items())
                 for interpretation, marginal in self.by_reading.items()
                 if len(set(marginal.values())) > 1]
        return ("The result depends on how an open question is read, so it is not settled ("
                + "; ".join(parts) + ").") if parts else ""


def run(rules: ResolvedRules, interpretation_ids: Sequence[str],
        evaluate: Callable[[Assignment], Cell],
        extra: Mapping[str, Sequence[str]] | None = None) -> Evaluated:
    """Evaluate a check under every combination of the readings of the given interpretations
    (the one selected reading of each, or every reading when it is ALL). `extra` gives the
    readings of an open question that is not an Interpretation (whose Table V column applies)."""
    ids = tuple(interpretation_ids)
    options = [list(extra[i]) if extra and i in extra else rules.readings(i) for i in ids]
    cells = []
    for combination in itertools.product(*options):
        assignment = dict(zip(ids, combination, strict=True))
        cells.append((assignment, evaluate(assignment)))
    return Evaluated(ids, tuple(cells), tuple(i for i, o in zip(ids, options, strict=True)
                                              if len(o) > 1))


def check_from(ev: Evaluated, *, family: Family, rule: str, clause: str,
               subject: str | None = None, note: str = "") -> Check:
    notes = " ".join(part for part in (note, ev.note, ev.readings_note) if part)
    finding = Finding(rule, ev.status, ev.measured, ev.required, clause, notes)
    return Check(family=family, subject=subject, finding=finding, by_reading=ev.by_reading)


def plain(family: Family, rule: str, status: Status, measured: str, required: str, clause: str,
          note: str = "", subject: str | None = None) -> Check:
    """A check that depends on no open reading."""
    return Check(family=family, subject=subject,
                 finding=Finding(rule, status, measured, required, clause, note))
