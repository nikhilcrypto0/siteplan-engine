"""The stilt_raise reading (NBC 2016 Part 3 12.1): how far a parking stilt's floor stands above the
ground a height is measured from, 0.15 m as covered parking or 0.45 m as a plinth.

The rules carry one raise, the selected reading's (under ALL the larger, which holds under both).
While the law leaves the question open (2026-10-13) the validator judges the other reading too,
wherever it could change a result: when a block's height under one raise or the other lies near
a figure the height and fire rules state. A check whose result differs between the two rests on
the reading and is CONDITIONAL, with the result under each and the one the study selected."""

from __future__ import annotations

from dataclasses import replace

from siteplan import rules as law
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    ALL,
    COVERED_PARKING,
    PLINTH,
    RAISE_FIELDS,
    STILT_RAISE,
    ResolvedRules,
)
from siteplan.contracts.validation import Check, Dependency, DependsOn, combine_readings
from siteplan.validator.context import Context

RAISES = (COVERED_PARKING, PLINTH)
NEAR_M = 0.05  # a rule figure this near a height under either raise may change a result


def raise_m(reading: str) -> float:
    """The raise a reading gives (rules.py, NBC 2016 Part 3 12.1.2 and 12.1.1)."""
    return law.COVERED_PARKING_RAISE_M if reading == COVERED_PARKING else law.PLINTH_MIN_M


def other_reading(rules: ResolvedRules) -> tuple[str, str] | None:
    """(the reading the rules carry, the other one to judge too), or None when there is none to
    judge: the question settled or not carried, ALL selected (the rules then hold the larger
    raise), or no raise carried (a contract stored before 2026-10-10)."""
    found = next((i for i in rules.interpretations if i.id == STILT_RAISE), None)
    if (found is None or rules.height.stilt_raise_m is None or found.settled
            or found.selected == ALL or found.selected not in RAISES):
        return None
    others = [r for r in found.alternatives if r != found.selected and r in RAISES]
    return (found.selected, others[0]) if others else None


def with_raise(rules: ResolvedRules, reading: str) -> ResolvedRules:
    """The rules with the stilt's raise of another reading, everything else as it is."""
    out = rules.model_copy(deep=True)
    out.height.stilt_raise_m = out.height.stilt_raise_m.model_copy(
        update={"value": raise_m(reading)})
    return out


def _numbers(node) -> list[float]:
    if isinstance(node, bool):
        return []
    if isinstance(node, int | float):
        return [float(node)]
    if isinstance(node, dict):
        return [x for v in node.values() for x in _numbers(v)]
    if isinstance(node, list | tuple):
        return [x for v in node for x in _numbers(v)]
    return []


def may_differ(ctx: Context, other: str) -> bool:
    """Whether the other raise could change a result: some block with a stilt has a height (its
    physical one, or its rule height under a reading of the stilt) that, under one raise or the
    other, lies within NEAR_M of a figure the height or fire rules state. Every number in those
    rules counts as such a figure, so this errs towards judging both."""
    shift = raise_m(other) - ctx.rules.height.stilt_raise_m.value
    marks = (_numbers(ctx.rules.height.model_dump(exclude=set(RAISE_FIELDS)))
             + _numbers(ctx.rules.fire.model_dump()))
    for t in ctx.towers:
        if not t.has_stilt:
            continue
        heights = [t.physical_height_m, *(h for r in ctx.stilt_readings
                                          if (h := t.rule_height_m(r)) is not None)]
        for h in heights:
            lo, hi = sorted((h, h + shift))
            if any(lo - NEAR_M <= m <= hi + NEAR_M for m in marks):
                return True
    return False


def _key(c: Check) -> tuple:
    return (c.family, c.finding.rule, c.subject)


def _unique(found: list[Dependency]) -> list[Dependency]:
    out: dict[tuple[str, str], Dependency] = {}
    for d in found:
        out.setdefault((d.kind.value, d.id), d)
    return list(out.values())


def _differs(c: Check, other_check: Check | None, selected: str, other: str) -> Check:
    """One check under the raise the rules carry, held beside the same check under the other: as
    it is where they agree; CONDITIONAL on stilt_raise where they do not. A check the other raise
    does not raise at all counts as passing there (the rule does not arise)."""
    s1 = c.finding.status
    s2 = other_check.finding.status if other_check is not None else Status.PASS
    if s1 is s2:
        return c
    outcomes = {selected: s1, other: s2}
    there = (f" Under the {other} reading of {STILT_RAISE}: "
             + (other_check.finding.measured if other_check is not None else "the rule does not "
                "arise") + ".")
    finding = replace(c.finding, status=combine_readings(outcomes),
                      note=(c.finding.note + there).strip())
    rests = [*c.rests_on, *(other_check.rests_on if other_check is not None else []),
             Dependency(kind=DependsOn.READING, id=STILT_RAISE, selected=selected,
                        outcomes=outcomes)]
    return Check(family=c.family, subject=c.subject, finding=finding,
                 by_reading={**c.by_reading, STILT_RAISE: outcomes}, rests_on=_unique(rests),
                 selected_status=c.selected_status or s1)


def _only_there(c: Check, selected: str, other: str) -> Check | None:
    """A check only the other raise brings in (a block that is a high-rise only there): kept, as
    CONDITIONAL, when it does not pass there; the rule does not arise under the selection."""
    if c.finding.status not in (Status.FAIL, Status.CONDITIONAL):
        return None
    outcomes = {selected: Status.PASS, other: c.finding.status}
    finding = replace(c.finding, status=Status.CONDITIONAL, note=(
        c.finding.note + f" Only under the {other} reading of {STILT_RAISE}; under the "
        f"{selected} reading the rule does not arise.").strip())
    rests = [*c.rests_on, Dependency(kind=DependsOn.READING, id=STILT_RAISE, selected=selected,
                                     outcomes=outcomes)]
    return Check(family=c.family, subject=c.subject, finding=finding,
                 by_reading={**c.by_reading, STILT_RAISE: outcomes}, rests_on=_unique(rests),
                 selected_status=Status.PASS)


def merge(selected: str, other: str, given: list[Check], alt: list[Check]) -> list[Check]:
    """The legal checks under the raise the rules carry, each held beside the same check (by
    family, rule and subject) under the other raise."""
    there: dict[tuple, list[Check]] = {}
    for c in alt:
        there.setdefault(_key(c), []).append(c)
    out = []
    for c in given:  # checks of one key are matched in their order
        same = there.get(_key(c))
        out.append(_differs(c, same.pop(0) if same else None, selected, other))
    out += [m for left in there.values() for c in left
            for m in [_only_there(c, selected, other)] if m is not None]
    return out
