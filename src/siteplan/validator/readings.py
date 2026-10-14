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
from dataclasses import dataclass, field

from siteplan.contracts.common import Basis, Finding, Provenance, Status
from siteplan.contracts.resolved_rules import (
    Applicability,
    HeightLimit,
    LimitBound,
    ResolvedRules,
)
from siteplan.contracts.validation import (
    Check,
    Dependency,
    DependsOn,
    Family,
    combine_readings,
)

COUNTED, NOT_COUNTED = "counted", "not_counted"  # stilt_in_rule_height
ALLOWED, NOT_ALLOWED = "allowed", "not_allowed"  # circulation_in_setback
OUTER_EDGE, CENTRELINE = "outer_edge", "centreline"  # fire_turning_radius
MINIMUM_APPROACH, AUTHORITY_CHOICE = "minimum", "authority_choice"  # approach_width
TALLER_GOVERNS, EACH_OWN = "taller_governs", "each_own"  # mixed_height_spacing
AT_GROUND, ANYWHERE = "at_ground", "anywhere"  # visitor_parking
MINIMUM_SHARE, SHARE_OR_CAP = "minimum_3_percent", "up_to_3_percent_or_cap"  # amenity_share
STATE_LINE, NBC_LINE = "state_line", "nbc_line"  # nbc_fire_height
TOUCH, FRONTAGE = "touch", "frontage"  # opens_onto_road
FIRE_BAND = "fire_band"  # opens_onto_road, offered only when a project selects it
# Whose Table V column applies is not an Interpretation: it is ResolvedRules.jurisdiction. When
# it is OPEN the validator evaluates both columns, under this key.
TABLE_V_COLUMN = "jurisdiction.table_v_column"
# Which width of the access road Table IV reads when the master plan widens it (carried by the
# rules only when a master-plan width is known): the road as it stands, or the master-plan width
# once its strip is surrendered.
TABLE_IV_ROAD_WIDTH = "table_iv_road_width"
EXISTING_WIDTH, MASTER_PLAN_WIDTH = "existing", "master_plan"

Assignment = dict[str, str]  # interpretation id -> the reading this cell is evaluated under


@dataclass(frozen=True)
class Cell:
    """One check's result under one assignment of readings; a CONDITIONAL cell names what it
    rests on beyond the readings (a site fact, a gap in the rules, a measurement)."""

    status: Status
    measured: str
    required: str = ""
    note: str = ""
    rests_on: tuple[Dependency, ...] = ()


def fact(name: str, detail: str = "") -> Dependency:
    """A fact about the site that is not known or not verified."""
    return Dependency(kind=DependsOn.SITE_FACT, id=name, detail=detail)


def rule_gap(name: str, detail: str = "") -> Dependency:
    """The law read gives no figure, or a rule value is unconfirmed."""
    return Dependency(kind=DependsOn.RULE_GAP, id=name, detail=detail)


def measurement(name: str, detail: str = "") -> Dependency:
    """The drawing does not settle what the check measures."""
    return Dependency(kind=DependsOn.MEASUREMENT, id=name, detail=detail)


JURISDICTION_FACT = "whose rules apply (Table V column)"


def unconfirmed_band(table: str) -> Dependency:
    """A height band the rules mark UNVERIFIED (no order read gives its figures)."""
    return rule_gap("height band unconfirmed", table)


def limit_rests(limit: HeightLimit) -> tuple[Dependency, ...]:
    """What a height limit's CONDITIONAL result rests on (HeightLimit.evaluate): whether it
    applies, a bound nobody could work out, or inputs nobody confirmed."""
    found = []
    if limit.condition is not None and limit.applicability is Applicability.UNKNOWN:
        found.append(fact(limit.condition.text, f"whether {limit.reason} applies"))
    if limit.bound is LimitBound.NOT_EVALUATED:
        found.append(fact(limit.reason, "the limit cannot be worked out from what is known"))
    if limit.status is Provenance.UNVERIFIED:
        found.append(fact(limit.reason, "the limit rests on inputs nobody has confirmed"))
    return tuple(found) or (rule_gap(limit.reason),)


def _unique(found: Sequence[Dependency]) -> list[Dependency]:
    out: dict[tuple[str, str], Dependency] = {}
    for d in found:
        out.setdefault((d.kind.value, d.id), d)
    return list(out.values())


def unknown_reading(interpretation_id: str, reading: str) -> Cell:
    return Cell(Status.UNVERIFIED, f"reading '{reading}' of {interpretation_id}",
                "a reading this validator can evaluate",
                "The reading is not one the validator knows how to evaluate; it is not guessed.",
                (Dependency(kind=DependsOn.READING, id=interpretation_id,
                            detail=f"'{reading}' cannot be evaluated"),))


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
    selection: Assignment = field(default_factory=dict)  # the study's selected readings

    @property
    def selected_status(self) -> Status | None:
        """The result under the readings the study selected; None when it selected none of the
        readings this check depends on."""
        chosen = {i: r for i, r in self.selection.items() if i in self.ids}
        if not chosen:
            return None
        return combine_statuses([c.status for a, c in self.cells
                                 if all(a[i] == r for i, r in chosen.items())])

    @property
    def dependencies(self) -> list[Dependency]:
        """What the result rests on: each reading under which it differs, with the result under
        each and the study's selection; and what the CONDITIONAL cells name."""
        marginals = self.by_reading
        found = [self._dependency(i, m) for i, m in marginals.items() if len(set(m.values())) > 1]
        found += [d for _, cell in self.cells if cell.status is Status.CONDITIONAL
                  for d in cell.rests_on]
        if not found and len({c.status for _, c in self.cells}) > 1:
            # the result turns on the readings together, though on none of them alone: each
            # question that varies is named, with the results under it
            found = [self._dependency(i, marginals[i]) for i in self.varying]
        return _unique(found)

    def _dependency(self, interpretation: str, marginal: dict[str, Status]) -> Dependency:
        if interpretation == TABLE_V_COLUMN:
            return Dependency(kind=DependsOn.SITE_FACT, id=JURISDICTION_FACT, outcomes=marginal)
        return Dependency(kind=DependsOn.READING, id=interpretation,
                          selected=self.selection.get(interpretation), outcomes=marginal)

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
    """Evaluate a check under every combination of the readings of the given interpretations:
    every reading of a question the law leaves open, whatever a study selected (2026-10-13), and
    only the selected one of a settled question (Interpretation.judged). The study's selections
    are kept, so the result under them is known beside the result under every reading. `extra`
    gives the readings of an open question that is not an Interpretation (whose Table V column
    applies)."""
    ids = tuple(interpretation_ids)
    options = [list(extra[i]) if extra and i in extra else rules.judged_readings(i)
               for i in ids]
    cells = []
    for combination in itertools.product(*options):
        assignment = dict(zip(ids, combination, strict=True))
        cells.append((assignment, evaluate(assignment)))
    selection = {i: r for i, r in rules.study_selections().items() if i in ids}
    return Evaluated(ids, tuple(cells), tuple(i for i, o in zip(ids, options, strict=True)
                                              if len(o) > 1), selection)


def check_from(ev: Evaluated, *, family: Family, rule: str, clause: str,
               subject: str | None = None, note: str = "") -> Check:
    notes = " ".join(part for part in (note, ev.note, ev.readings_note) if part)
    finding = Finding(rule, ev.status, ev.measured, ev.required, clause, notes)
    return Check(family=family, subject=subject, finding=finding, by_reading=ev.by_reading,
                 rests_on=ev.dependencies if ev.status is Status.CONDITIONAL else [],
                 selected_status=ev.selected_status)


def plain(family: Family, rule: str, status: Status, measured: str, required: str, clause: str,
          note: str = "", subject: str | None = None,
          rests_on: Sequence[Dependency] = ()) -> Check:
    """A check that depends on no open reading; a CONDITIONAL one names what it rests on."""
    return Check(family=family, subject=subject,
                 finding=Finding(rule, status, measured, required, clause, note),
                 rests_on=list(rests_on) if status is Status.CONDITIONAL else [])
