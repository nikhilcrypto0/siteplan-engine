"""Floors from metres: which floor counts the law leaves open to a tower, and what each asks.

ResolvedRules speaks in metres on named measures and holds no floor count. A tower's floors come
from the stilt and floor-to-floor heights (the prototype's when it sets them, else the firm's
standards in the DesignBrief), standing on the lowest floor's raise above the ground every height
is measured from (`HeightRules.lowest_floor_raise_m`, NBC Part 3 12.1): storeys that exactly
reach a limit with the stilt in it are over it. Where the stilt is left out, its raise goes with
it. Whether the stilt counts toward the height that picks the Table IV
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
labelled UNVERIFIED. The band of a block is `HeightRules.band_for_block`: for a high-rise count
the band of its rule height, for a count below 21 m Table III's row on the height above the
stilt (rule 5(c)). Where a high-rise is prohibited no count of the high-rise height or more is
offered, and that permits nothing lower.

A count below the high-rise height stands on its own band's permission
(`HeightRules.band_permission`), as a high-rise count stands on the site's eligibility: offered
where the band is ALLOWED, offered and labelled UNVERIFIED where the band's permission is not
settled, never offered where it is PROHIBITED. A band the rules give no setback for (18-21 m on
most plots) is never offered either: nothing would hold a block there to anything.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from siteplan import rules as law
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
# assessed up to the top of Table IV's last bounded row, where its open-ended row starts (120 m),
# read from rules.py so the bound follows the table.
CEILING_M = float(law.TABLE_IV[-1].above_m)
CONDITION = {Applicability.APPLIES: True, Applicability.DOES_NOT_APPLY: False,
             Applicability.UNKNOWN: None}
HIGH_RISE_CHECK = "High-rise eligibility"
PERMISSION_STATUS = {Eligibility.ALLOWED: Status.PASS, Eligibility.PROHIBITED: Status.FAIL,
                     Eligibility.UNVERIFIED: Status.UNVERIFIED}


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
    permission: LimitCheck | None = None  # its band's permission, for a count below the high-rise

    @property
    def checks(self) -> tuple[LimitCheck, ...]:
        return (*self.limits, *((self.high_rise,) if self.high_rise else ()),
                *((self.permission,) if self.permission else ()))

    @property
    def setback_m(self) -> float | None:
        return self.band.setback_m if self.band else None

    @property
    def gap_m(self) -> float | None:
        return self.band.gap_m if self.band else None

    @property
    def modelled(self) -> bool:
        """Whether the engine knows this band's setback and gap."""
        return bool(self.band and self.band.modelled and self.band.setback_m is not None)

    @property
    def below_high_rise(self) -> bool:
        """A count under the high-rise height: Table III's (rule 5), not Table IV's."""
        return self.high_rise is None

    @property
    def limits_status(self) -> Status:
        return worst(self.checks)

    @property
    def feasible(self) -> bool:
        """Nothing holds this count back. A limit that only may apply does not: it is reported
        UNVERIFIED."""
        return not any(check.holds_back for check in self.checks)

    @property
    def stops_the_scan(self) -> bool:
        """Something that only grows with the height holds this count back (a height limit, the
        site's high-rise eligibility), so no taller count is offered either. A band below the
        high-rise height that is not permitted says nothing of a taller one."""
        return any(check.holds_back for check in (*self.limits, *((self.high_rise,)
                                                                  if self.high_rise else ())))

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


def _band_permission(rules: ResolvedRules, band: Band | None, band_height_m: float
                     ) -> LimitCheck | None:
    """Whether a count below the high-rise height may stand here: its band's own permission
    (plot size, road), as the rules give it. None where no band covers the height."""
    if band is None:
        return None
    permission = rules.height.band_permission(band)
    span = (f"{band.above_m:g} m" if band.above_m == band.up_to_m
            else f"{band.above_m:g}-{band.up_to_m:g} m")
    reason = f"the band {span} is {permission.value.lower()} here" + (
        f": {band.permission_note}" if permission is not Eligibility.ALLOWED
        and band.permission_note else "")
    return LimitCheck(band.measure, None, band_height_m, PERMISSION_STATUS[permission], reason,
                      band.clause, band.status,
                      holds_back=permission is Eligibility.PROHIBITED)


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
    on_stilt = brief.height_intent.has_stilt if has_stilt is None else has_stilt
    raise_m = rules.height.lowest_floor_raise_m(on_stilt)
    # The stilt floor from the ground (its raise and its storey), and the rest: left out with the
    # stilt where it is not counted; a block with no stilt stands on its plinth in every measure.
    stilt_floor = raise_m + stilt if on_stilt else 0.0
    above_stilt = floors * floor + (0.0 if on_stilt else raise_m)
    physical = stilt_floor + above_stilt
    rule_height = physical if reading == STILT_COUNTED else above_stilt
    checks = tuple(_check(limit, rule_height, physical) for limit in rules.height.limits)
    band = rules.height.band_for_block(above_stilt, stilt_floor,
                                       stilt_counted=reading == STILT_COUNTED)
    high_rise = _high_rise(rules, rule_height)
    permission = None
    if high_rise is None:  # below the high-rise height: the band's own permission decides
        on_stilt = band is not None and band.measure is HeightMeasure.HEIGHT_ABOVE_STILT
        permission = _band_permission(rules, band, above_stilt if on_stilt else rule_height)
    return FloorOption(floors, reading, stilt, floor, rule_height, physical, band, checks,
                       high_rise, permission)


def assess_floors(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                  reading: str) -> list[FloorOption]:
    """Every floor count from one up to the first one a height limit or the site's high-rise
    eligibility holds back (or the ceiling), each with its verdicts. Heights only grow, so such a
    count is followed by none that is offered; the first is kept so a report can say what stops
    the next floor. A count whose own band below the high-rise height is not permitted is passed
    over, not stopped at: a taller band may be."""
    options: list[FloorOption] = []
    while True:
        option = assess_floor_count(rules, brief, prototype, reading, len(options) + 1)
        options.append(option)
        if option.stops_the_scan or option.physical_height_m >= CEILING_M:
            return options


def feasible_floors(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                    reading: str) -> list[FloorOption]:
    """The floor counts a tower may take, lowest first: nothing holds them back (a count below
    the high-rise height stands on its band's permission), the band's setback and gap are
    modelled, and the brief's height intent allows them. It is the whole set, never only the
    most."""
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
