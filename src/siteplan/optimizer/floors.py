"""Floors from metres: which floor counts the law leaves open to a tower, and what each asks.

ResolvedRules speaks in metres on named measures and holds no floor count. A tower's floors come
from the stilt and floor-to-floor heights (the prototype's when it sets them, else the firm's
standards in the DesignBrief). Whether the stilt counts toward the height that picks the Table IV
row is an open reading (`stilt_in_rule_height`, selected ALL), so every function here takes one
reading and `floors_by_reading` runs them all. NBC's physical height always includes the stilt.

Nothing here picks a height for the design. `feasible_floors` returns every count the law leaves
open, so a tower's height stays a choice for the search: "the most the law allows" never means
every tower at the maximum.

A limit that applies only on a condition (NBC's dead-end limit) is UNVERIFIED while the condition
is not known and FAIL once it holds. HeightLimit.applies_if is free text, so the condition is
read from the site model when the caller passes it, else from the limit's own status.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.design_brief import DesignBrief, HeightIntent, HeightMode
from siteplan.contracts.prototype import TowerPrototype
from siteplan.contracts.resolved_rules import (
    STILT_IN_RULE_HEIGHT,
    Band,
    HeightLimit,
    HeightMeasure,
    ResolvedRules,
)
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.rules import DEAD_END_CLAUSE

STILT_COUNTED = "counted"  # the readings of stilt_in_rule_height the adapters also use
STILT_NOT_COUNTED = "not_counted"
READINGS = (STILT_COUNTED, STILT_NOT_COUNTED)
EPS_M = 1e-6  # a height that meets its limit to a millionth of a metre meets it
# A search bound, not a rule: where no limit stops the count (a road of 30 m or more), counts are
# assessed up to the top of Table IV's last bounded row.
CEILING_M = 120.0

# The site fact each conditional limit rests on, by its clause. NBC 4.6(b): no dead-end road for
# a residential building above 30 m, so the limit holds when the access road ends at the plot.
SITE_CONDITIONS = {DEAD_END_CLAUSE: lambda site: site.access.dead_end.value}


@dataclass(frozen=True)
class LimitCheck:
    """One height limit held against one floor count."""

    measure: HeightMeasure
    limit_m: float | None  # None: the limit cannot be evaluated yet
    height_m: float | None  # the building's height on that measure; None if floors cannot give it
    status: Status
    reason: str
    clause: str
    limit_status: Provenance  # how far the limit itself can be trusted
    condition: bool | None = True  # does the limit's condition hold; None: not known


def worst(checks: Iterable[LimitCheck]) -> Status:
    """FAIL if any check fails, else UNVERIFIED if any is open, else PASS."""
    statuses = {check.status for check in checks}
    if Status.FAIL in statuses:
        return Status.FAIL
    return Status.UNVERIFIED if Status.UNVERIFIED in statuses else Status.PASS


@dataclass(frozen=True)
class FloorOption:
    """A floor count above the stilt, the heights it makes, its Table IV band and every limit."""

    floors: int
    reading: str
    stilt_m: float
    floor_to_floor_m: float
    rule_height_m: float  # the height that picks the Table IV row and the high-rise class
    physical_height_m: float  # ground to the top, stilt included (NBC)
    band: Band | None
    limits: tuple[LimitCheck, ...]

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
        return worst(self.limits)

    @property
    def feasible(self) -> bool:
        """No limit rules this count out. An UNVERIFIED limit does not: it is reported."""
        return self.limits_status is not Status.FAIL

    @property
    def status(self) -> Status:
        if self.limits_status is not Status.PASS:
            return self.limits_status
        return Status.PASS if self.modelled else Status.NOT_CHECKED

    @property
    def open_items(self) -> tuple[str, ...]:
        return tuple(check.reason for check in self.limits if check.status is Status.UNVERIFIED)

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


def condition_holds(limit: HeightLimit, site: CanonicalSiteModel | None) -> bool | None:
    """Whether a limit is in force: True, False, or None when that is not known. A limit with no
    condition always is."""
    if limit.applies_if is None:
        return True
    read = SITE_CONDITIONS.get(limit.clause)
    if site is not None and read is not None:
        return read(site)
    return None if limit.status is Provenance.UNVERIFIED else True


def band_for(rules: ResolvedRules, rule_height_m: float) -> Band | None:
    """The band a rule height falls in: above its lower edge, up to and including its upper."""
    return next((band for band in rules.height.bands
                 if band.above_m < rule_height_m <= band.up_to_m), None)


def _check(limit: HeightLimit, rule_m: float, physical_m: float,
           condition: bool | None) -> LimitCheck:
    height = {HeightMeasure.RULE_HEIGHT: rule_m,
              HeightMeasure.PHYSICAL_HEIGHT: physical_m}.get(limit.measure)

    def result(status: Status, reason: str) -> LimitCheck:
        return LimitCheck(limit.measure, limit.max_m, height, status, reason, limit.clause,
                          limit.status, condition)

    if limit.max_m is None or height is None:
        return result(Status.UNVERIFIED, limit.reason)  # cannot be evaluated: never passed
    if math.isinf(limit.max_m) or height <= limit.max_m + EPS_M:
        return result(Status.PASS, f"{height:g} m is within {limit.max_m:g} m: {limit.reason}")
    over = f"{height:g} m is above the {limit.max_m:g} m limit: {limit.reason}"
    if condition is True:
        return result(Status.FAIL, over)
    if condition is None:
        return result(Status.UNVERIFIED, f"{over}; it applies only if {limit.applies_if}, "
                                         "which is not known")
    return result(Status.PASS, f"{over}; it does not apply here ({limit.applies_if})")


def assess_floor_count(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                       reading: str, floors: int, *, site: CanonicalSiteModel | None = None,
                       has_stilt: bool | None = None) -> FloorOption:
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
    checks = tuple(_check(limit, rule_height, physical, condition_holds(limit, site))
                   for limit in rules.height.limits)
    return FloorOption(floors, reading, stilt, floor, rule_height, physical,
                       band_for(rules, rule_height), checks)


def assess_floors(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                  reading: str, *, site: CanonicalSiteModel | None = None) -> list[FloorOption]:
    """Every floor count from one up to the first one a limit rules out (or the ceiling), each
    with its verdicts. Heights only grow, so a count that fails is followed by none that pass;
    the first failure is kept so a report can say what stops the next floor."""
    options: list[FloorOption] = []
    while True:
        option = assess_floor_count(rules, brief, prototype, reading, len(options) + 1, site=site)
        options.append(option)
        if not option.feasible or option.physical_height_m >= CEILING_M:
            return options


def feasible_floors(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                    reading: str, *, site: CanonicalSiteModel | None = None) -> list[FloorOption]:
    """The floor counts a tower may take, lowest first: no limit rules them out, the band's
    setback and gap are modelled (below the high-rise height they are not yet), and the brief's
    height intent allows them. It is the whole set, never only the most."""
    return [option for option in assess_floors(rules, brief, prototype, reading, site=site)
            if option.feasible and option.modelled
            and _wanted(option.floors, brief.height_intent)]


def floors_by_reading(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype | None,
                      *, site: CanonicalSiteModel | None = None) -> dict[str, list[FloorOption]]:
    """The feasible counts under every reading of the stilt the rules leave open."""
    return {reading: feasible_floors(rules, brief, prototype, reading, site=site)
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
