"""The open readings a layout is built to hold under, and the floor counts each one leaves open.

The rules carry some open questions as ALL (the stilt, circulation inside the setback): a result
that holds under only some of their readings is UNVERIFIED. A layout is therefore built for a
*profile*, one choice per question:

- `ALL`: built to hold under every reading the rules carry. For the stilt that means a floor count
  the law leaves open under each reading, held to the setbacks and gaps of the stricter one; for
  circulation it means roads and fire lanes outside the setback, which holds under both.
- a single reading: built for it alone. It may rest on that reading (the validator then reports
  the checks that differ as UNVERIFIED and names the reading), but it must meet every rule under
  the reading it was built for, or it is not offered.

A profile that adds nothing over `ALL` (a reading whose floor counts are no more than the ones
every reading allows) is not tried. Everything else the rules leave open (the turning radius, the
spacing of blocks of different heights, the denominators of the open space, the club house share)
is always met under every reading, which costs nothing here.
"""

from __future__ import annotations

from dataclasses import dataclass

from siteplan.contracts import DesignBrief, ResolvedRules, TowerPrototype
from siteplan.contracts.resolved_rules import (
    ALLOWED,
    CIRCULATION_IN_SETBACK,
    NOT_ALLOWED,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.optimizer.floors import feasible_floors

ALL = "ALL"


@dataclass(frozen=True)
class Profile:
    """The readings of the stilt and of circulation inside the setback a layout is built for."""

    stilt: str  # ALL, or one reading of stilt_in_rule_height
    circulation: str  # ALL (roads stay out of the setback), or ALLOWED

    @property
    def key(self) -> str:
        return f"{self.stilt}-{self.circulation}"

    @property
    def roads_may_use_setback(self) -> bool:
        return self.circulation == ALLOWED

    def stilt_readings(self, rules: ResolvedRules) -> list[str]:
        return rules.readings(STILT_IN_RULE_HEIGHT) if self.stilt == ALL else [self.stilt]

    def basis(self) -> dict[str, str]:
        """The interpretation_basis a candidate made for this profile carries."""
        return {STILT_IN_RULE_HEIGHT: self.stilt, CIRCULATION_IN_SETBACK: self.circulation}


@dataclass(frozen=True)
class FloorClass:
    """A floor count and what the law asks of a block that tall under the profile's readings: the
    setback and the gap are the greatest of those the readings ask."""

    floors: int
    physical_m: float
    setback_m: float
    gap_m: float
    rule_heights: tuple[tuple[str, float], ...]  # reading -> the height that picks the row
    open_items: tuple[str, ...]  # what rests on an input nobody has settled


def floor_classes(rules: ResolvedRules, brief: DesignBrief, prototype: TowerPrototype,
                  profile: Profile) -> list[FloorClass]:
    """The floor counts a block of this prototype may take under every reading of the profile,
    lowest first. A count the law leaves open under one reading only is not here."""
    readings = profile.stilt_readings(rules)
    per_reading = [{o.floors: o for o in feasible_floors(rules, brief, prototype, reading)}
                   for reading in readings]
    common = sorted(set.intersection(*(set(found) for found in per_reading)))
    classes = []
    for floors in common:
        options = [found[floors] for found in per_reading]
        classes.append(FloorClass(
            floors=floors, physical_m=options[0].physical_height_m,
            setback_m=max(o.setback_m for o in options), gap_m=max(o.gap_m for o in options),
            rule_heights=tuple((o.reading, o.rule_height_m) for o in options),
            open_items=tuple(sorted({item for o in options for item in o.open_items}))))
    return classes


def profiles(rules: ResolvedRules, brief: DesignBrief, prototypes: list[TowerPrototype]
             ) -> list[Profile]:
    """Every profile worth building for: ALL first, then each single reading that leaves a
    floor count open which the readings together do not."""
    stilt_readings = rules.readings(STILT_IN_RULE_HEIGHT)
    circulation_readings = rules.readings(CIRCULATION_IN_SETBACK)
    stilts = [ALL]
    if len(stilt_readings) > 1:
        tallest = max(_floors_under(rules, brief, prototypes, Profile(ALL, ALL)), default=0)
        for reading in stilt_readings:
            if max(_floors_under(rules, brief, prototypes, Profile(reading, ALL)),
                   default=0) > tallest:
                stilts.append(reading)
    elif stilt_readings:
        stilts = [stilt_readings[0]]
    if len(circulation_readings) == 1:
        circulations = [ALLOWED if circulation_readings[0] == ALLOWED else ALL]
    else:
        circulations = [ALL, ALLOWED]
    return [Profile(stilt, circulation) for stilt in stilts for circulation in circulations]


def _floors_under(rules: ResolvedRules, brief: DesignBrief, prototypes: list[TowerPrototype],
                  profile: Profile) -> set[int]:
    return {c.floors for p in prototypes for c in floor_classes(rules, brief, p, profile)}


def circulation_is_strict(profile: Profile, rules: ResolvedRules) -> bool:
    """Whether roads and fire lanes must stay out of the setback for this profile: ALL asks it,
    unless the rules themselves settle the question as allowed."""
    if profile.roads_may_use_setback:
        return False
    return NOT_ALLOWED in rules.readings(CIRCULATION_IN_SETBACK)
