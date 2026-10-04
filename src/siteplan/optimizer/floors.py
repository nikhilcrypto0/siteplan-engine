"""Floors from metres: which floor counts the law leaves open to a tower, and what each asks.

ResolvedRules speaks in metres on named measures and holds no floor count. A tower's floors come
from the stilt and floor-to-floor heights (the prototype's when it sets them, else the firm's
standards in the DesignBrief). Whether the stilt counts toward the height that picks the Table IV
row is an open reading (`stilt_in_rule_height`, selected ALL), so every function here takes one
reading and `floors_by_reading` runs them all. NBC's physical height always includes the stilt.

Nothing here picks a height for the design. `feasible_floors` returns every count the law leaves
open, so a tower's height stays a choice for the search: "the most the law allows" never means
every tower at the maximum.

What a limit says of a height is the contract's, never worked out again here: the verdict is
`HeightLimit.evaluate` and whether the height may be offered is `HeightLimit.beyond`, so the
optimizer and the validator read every limit the same way. A limit that applies holds a height
back whether or not its inputs are confirmed (it is UNVERIFIED, not FAIL, when they are not);
one whose condition is unsettled (the dead end nobody has answered) lets the height through,
labelled UNVERIFIED. The band of a height is `HeightRules.band_for`. Where a high-rise is
prohibited no count of the high-rise height or more is offered, and that permits nothing lower:
below it the band is Table III's, not modelled, so no count there is offered or passed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.design_brief import DesignBrief, HeightIntent, HeightMode
from siteplan.contracts.prototype import TowerPrototype
from siteplan.contracts.resolved_rules import (
    HEIGHT_TOL_M,
    STILT_IN_RULE_HEIGHT,
    Applicability,
    Band,
    Eligibility,
    HeightLimit,
    HeightMeasure,
    LimitBound,
    ResolvedRules,
)

STILT_COUNTED = "counted"  # the readings of stilt_in_rule_height the adapters also use
STILT_NOT_COUNTED = "not_counted"
READINGS = (STILT_COUNTED, STILT_NOT_COUNTED)
EPS_M = HEIGHT_TOL_M  # a height that meets its limit to a millionth of a metre meets it
# A search bound, not a rule: where no limit stops the count (a road of 30 m or more), counts are
# assessed up to the top of Table IV's last bounded row.
CEILING_M = 120.0
CONDITION = {Applicability.APPLIES: True, Applicability.DOES_NOT_APPLY: False,
             Applicability.UNKNOWN: None}
HIGH_RISE_CHECK = "High-rise eligibility"


@dataclass(frozen=True)
class LimitCheck:
    """One height limit (or the site's high-rise eligibility) held against one floor count."""

    measure: HeightMeasure
    limit_m: float | None  # None: there is no number to hold the height to
    height_m: float | None  # the building's height on that measure; None if floors cannot give it
    status: Status
    reason: str
    clause: str
    limit_status: Provenance  # how far the limit itself can be trusted
    condition: bool | None = True  # is the limit in force; None: it rests on an unsettled fact
    holds_back: bool = False  # the count may not be offered


def worst(checks: Iterable[LimitCheck]) -> Status:
    """FAIL if any check fails, else UNVERIFIED if any is open, else PASS."""
    statuses = {check.status for check in checks}
    if Status.FAIL in statuses:
        return Status.FAIL
    return Status.UNVERIFIED if Status.UNVERIFIED in statuses else Status.PASS


@dataclass(frozen=True)
class FloorOption:
    """A floor count above the stilt, the heights it makes, its band and every check on it."""

    floors: int
    reading: str
    stilt_m: float
    floor_to_floor_m: float
    rule_height_m: float  # the height that picks the Table IV row and the high-rise class
    physical_height_m: float  # ground to the top, stilt included (NBC)
    band: Band | None
    limits: tuple[LimitCheck, ...]
    high_rise: LimitCheck | None = None  # the site's eligibility, for a high-rise count only

    @property
    def checks(self) -> tuple[LimitCheck, ...]:
        return (*self.limits, *((self.high_rise,) if self.high_rise else ()))

    @property
    def setback_m(self) -> float | None:
        return self.band.setback_m if self.band else None

    @property
    def gap_m(self) -> float | None:
        return self.band.gap_m if self.band else None

    @property
    def modelled(self) -> bool:
        """Whether the engine knows this band's setback and gap (Table III is not encoded)."""
        return bool(self.band and self.band.modelled and self.band.setback_m is not None)

    @property
    def limits_status(self) -> Status:
        return worst(self.checks)

    @property
    def feasible(self) -> bool:
        """Nothing holds this count back. A limit that only may apply does not: it is reported
        UNVERIFIED."""
        return not any(check.holds_back for check in self.checks)

    @property
    def status(self) -> Status:
        if self.limits_status is not Status.PASS:
            return self.limits_status
        return Status.PASS if self.modelled else Status.NOT_CHECKED

    @property
    def open_items(self) -> tuple[str, ...]:
        return tuple(check.reason for check in self.checks if check.status is Status.UNVERIFIED)

    def checks_on(self, measure: HeightMeasure) -> tuple[LimitCheck, ...]:
        return tuple(check for check in self.limits if check.measure is measure)


def standard_heights(brief: DesignBrief, prototype: TowerPrototype | None,
                     has_stilt: bool | None = None) -> tuple[float, float]:
    """(stilt, floor-to-floor) in metres: the prototype's own when it sets them, else the
    firm's standards. No stilt means a stilt height of 0."""
    own = prototype.heights if prototype is not None else None
    standards = brief.firm_standards
    stilt = own.stilt_height_m if own and own.stilt_height_m is not None \
        else standards.stilt_height_m.value
    floor = own.floor_to_floor_m if own and own.floor_to_floor_m is not None \
        else standards.floor_to_floor_m.value
    if floor <= 0 or stilt < 0:
        raise ValueError(f"heights must be positive: floor {floor:g} m, stilt {stilt:g} m")
    if has_stilt is None:
        has_stilt = brief.height_intent.has_stilt
    return (stilt if has_stilt else 0.0), floor


def _reason(limit: HeightLimit, height: float | None, status: Status) -> str:
    if height is None or limit.bound is not LimitBound.BOUNDED:
        return limit.reason
    if limit.within(height):
        return f"{height:g} m is within {limit.max_m:g} m: {limit.reason}"
    over = f"{height:g} m is above the {limit.max_m:g} m limit: {limit.reason}"
    if limit.applicability is Applicability.DOES_NOT_APPLY:
        return f"{over}; it does not apply here ({limit.condition.text})"
    if limit.applicability is Applicability.UNKNOWN:
        return f"{over}; it applies only if {limit.condition.text}, which is not known"
    if status is Status.UNVERIFIED:
        return f"{over}; the limit rests on inputs not yet confirmed ({limit.status})"
    return over


def _check(limit: HeightLimit, rule_m: float, physical_m: float) -> LimitCheck:
    height = {HeightMeasure.RULE_HEIGHT: rule_m,
              HeightMeasure.PHYSICAL_HEIGHT: physical_m}.get(limit.measure)
    if height is not None:
        status, held = limit.evaluate(height), limit.beyond(height)
    else:  # no height on this measure (above sea level): only a limit that is not there passes
        status = {Applicability.DOES_NOT_APPLY: Status.INFO}.get(limit.applicability) or (
            Status.PASS if limit.bound is LimitBound.UNBOUNDED else Status.UNVERIFIED)
        held = False
    return LimitCheck(limit.measure, limit.max_m, height, status, _reason(limit, height, status),
                      limit.clause, limit.status, CONDITION[limit.applicability], held)


def _high_rise(rules: ResolvedRules, rule_m: float) -> LimitCheck | None:
    """The site's eligibility, held against a count of the high-rise height or more."""
    start = rules.height.high_rise_from_m.value
    if rule_m < start - EPS_M:
        return None
    high_rise = rules.height.high_rise
    failing = [g for g in high_rise.grounds if g.settled and g.met is False]
    open_ = [g for g in high_rise.grounds if not g.settled]
    status = {Eligibility.ALLOWED: Status.PASS, Eligibility.PROHIBITED: Status.FAIL,
              Eligibility.UNVERIFIED: Status.UNVERIFIED}[high_rise.eligibility]
    named = failing if failing else open_
    reason = (f"a high-rise is {high_rise.eligibility.value.lower()} here"
              + "".join(f"; {g.id}: {g.measured}, {g.required}" for g in named)
              + (f" ({high_rise.note})" if high_rise.note else ""))
    clause = "; ".join(sorted({g.clause for g in named})) or rules.height.high_rise_from_m.clause
    return LimitCheck(HeightMeasure.RULE_HEIGHT, start, rule_m, status, reason, clause,
                      Provenance.UNVERIFIED if open_ else Provenance.VERIFIED,
                      holds_back=high_rise.eligibility is Eligibility.PROHIBITED)


def assess_floor_count(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                       reading: str, floors: int, *, has_stilt: bool | None = None
                       ) -> FloorOption:
    """One floor count held against every height limit under one reading of the stilt."""
    if reading not in READINGS or reading not in rules.interpretation(
            STILT_IN_RULE_HEIGHT).alternatives:
        raise ValueError(f"unknown reading '{reading}' of {STILT_IN_RULE_HEIGHT}: "
                         f"{', '.join(READINGS)}")
    if floors < 1:
        raise ValueError("a tower has at least one floor above the stilt")
    stilt, floor = standard_heights(brief, prototype, has_stilt)
    physical = stilt + floors * floor
    rule_height = physical if reading == STILT_COUNTED else floors * floor
    checks = tuple(_check(limit, rule_height, physical) for limit in rules.height.limits)
    return FloorOption(floors, reading, stilt, floor, rule_height, physical,
                       rules.height.band_for(rule_height), checks,
                       _high_rise(rules, rule_height))


def assess_floors(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                  reading: str) -> list[FloorOption]:
    """Every floor count from one up to the first one held back (or the ceiling), each with its
    verdicts. Heights only grow, so a count held back is followed by none that is offered; the
    first is kept so a report can say what stops the next floor."""
    options: list[FloorOption] = []
    while True:
        option = assess_floor_count(rules, brief, prototype, reading, len(options) + 1)
        options.append(option)
        if not option.feasible or option.physical_height_m >= CEILING_M:
            return options


def feasible_floors(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                    reading: str) -> list[FloorOption]:
    """The floor counts a tower may take, lowest first: nothing holds them back, the band's
    setback and gap are modelled (below the high-rise height they are not yet), and the brief's
    height intent allows them. It is the whole set, never only the most."""
    return [option for option in assess_floors(rules, brief, prototype, reading)
            if option.feasible and option.modelled
            and _wanted(option.floors, brief.height_intent)]


def floors_by_reading(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None
                      ) -> dict[str, list[FloorOption]]:
    """The feasible counts under every reading of the stilt the rules leave open."""
    return {reading: feasible_floors(rules, brief, prototype, reading)
            for reading in rules.readings(STILT_IN_RULE_HEIGHT)}


def _wanted(floors: int, intent: HeightIntent) -> bool:
    if intent.min_floors_above_stilt and floors < intent.min_floors_above_stilt:
        return False
    if intent.mode is HeightMode.FIXED:
        return floors == intent.floors_above_stilt
    if intent.mode is HeightMode.RANGE:
        low, high = intent.floors_range
        return low <= floors <= high
    return True
