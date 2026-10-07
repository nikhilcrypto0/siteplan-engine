"""The program: what the architect and the firm asked for, held against what was drawn.

These checks are design intent, not law. A missed unit mix, a club house that was not wanted or
an amenity with no room is a shortfall of the brief, never an illegality, so none of them is ever
among the legal checks and none of them changes the legal verdict.
"""

from __future__ import annotations

from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import (
    AmenityPriority,
    ClubSize,
    DesignBrief,
    HeightMode,
    UnitsMode,
)
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.validation import Check, Family
from siteplan.validator.measure import TOL_M, TowerGeometry
from siteplan.validator.readings import plain, verdict
from siteplan.validator.shapes import polygon_of, sides_of

BRIEF = "the brief"
UNITS_TARGET_TOLERANCE = 0.05  # a units target is met within this share
SIZE_SLACK_SQM = 0.5


def units_by_type(towers: tuple[TowerGeometry, ...]) -> dict[str, int]:
    """Flats by category, counted from every tower's modules, a floor at a time."""
    out: dict[str, int] = {}
    for t in towers:
        for category, n in t.units.items():
            out[category] = out.get(category, 0) + n
    return out


def mix_error(counts: dict[str, int], target: dict[str, float]) -> float:
    """Half the summed gap between achieved and requested shares: 0 is exact, 1 is disjoint."""
    total = sum(counts.values()) or 1
    keys = set(counts) | set(target)
    return sum(abs(counts.get(k, 0) / total - target.get(k, 0.0)) for k in keys) / 2


def _mix_check(brief: DesignBrief, counts: dict[str, int]) -> Check:
    target = brief.program.unit_mix.value
    error, tolerance = mix_error(counts, target), brief.program.mix_tolerance
    total = sum(counts.values()) or 1
    achieved = {k: round(v / total, 3) for k, v in sorted(counts.items())}
    return plain(Family.PROGRAM, "Unit mix", verdict(error <= tolerance + 1e-9),
                 f"mix error {error:.3f}; achieved {achieved}",
                 f"within {tolerance:g} of {dict(sorted(target.items()))}", BRIEF)


def _units_check(brief: DesignBrief, counts: dict[str, int]) -> Check:
    units, n = brief.program.units, sum(counts.values())
    if units.mode is UnitsMode.MAXIMISE:
        return plain(Family.PROGRAM, "Units", Status.INFO, f"{n} flats", "as many as the land "
                     "takes", BRIEF)
    if units.mode is UnitsMode.TARGET:
        ok = abs(n - units.target) <= UNITS_TARGET_TOLERANCE * units.target
        return plain(Family.PROGRAM, "Units", verdict(ok), f"{n} flats",
                     f"{units.target} flats, within {UNITS_TARGET_TOLERANCE:.0%}", BRIEF)
    ok = units.minimum <= n <= units.maximum
    return plain(Family.PROGRAM, "Units", verdict(ok), f"{n} flats",
                 f"{units.minimum} to {units.maximum} flats", BRIEF)


def _club_check(brief: DesignBrief, candidate: CandidateLayout, units: int,
                rules: ResolvedRules) -> Check:
    asked, club = brief.program.club_house, candidate.program.club_house
    wanted = asked.wanted.value
    provided = polygon_of(club.shape)[0].area * club.floors if club else 0.0
    below = units < rules.amenities.from_units.value
    if wanted and club is None and asked.size is ClubSize.LEGAL_MINIMUM and below:
        return plain(Family.PROGRAM, "Club house", Status.PASS,
                     f"none drawn: {units} units, and the legal minimum is none below "
                     f"{rules.amenities.from_units.value}", "a club house of the legal minimum",
                     BRIEF)
    if not wanted:
        return plain(Family.PROGRAM, "Club house", Status.PASS if club is None else Status.INFO,
                     "none drawn" if club is None else f"{provided:,.0f} m² drawn although not "
                     "asked for (the law may ask for it)", "not wanted", BRIEF)
    problems = []
    if club is None:
        problems.append("none drawn")
    elif asked.size is ClubSize.STATED and provided + SIZE_SLACK_SQM < asked.sqm:
        problems.append(f"{provided:,.0f} m² of the {asked.sqm:,.0f} m² asked")
    elif asked.floors and club.floors != asked.floors:
        problems.append(f"{club.floors} floors, not {asked.floors}")
    return plain(Family.PROGRAM, "Club house", verdict(not problems),
                 "; ".join(problems) if problems else f"{provided:,.0f} m²",
                 "a club house", BRIEF)


def _amenity_checks(brief: DesignBrief, candidate: CandidateLayout) -> list[Check]:
    """Each facility the brief asks for (C4-08: two classes). One it REQUIRES is part of the
    program, and a layout without it fails the program. One it PREFERS (what a firm's library
    gives when it says nothing) or leaves OPTIONAL is a preference: said when it is not placed,
    never a failure of the program, so no layout is held to the whole of a firm's library."""
    placed = {a.name.casefold() for a in candidate.program.amenities}
    out = []
    for asked in brief.program.amenities:
        there = asked.name.casefold() in placed
        missed = asked.name in candidate.program.amenities_missed
        if there:
            status, measured = Status.PASS, "placed"
        elif asked.priority is not AmenityPriority.REQUIRED:
            status = Status.INFO
            measured = (f"not placed ({asked.priority.value.lower()})"
                        + (": no room found for it" if missed else ""))
        else:
            status = Status.FAIL
            measured = "no room found for it" if missed else "not placed"
        out.append(plain(Family.PROGRAM, f"Amenity: {asked.name}", status, measured,
                         f"{asked.priority.value.lower()}", BRIEF))
    return out


def _height_check(brief: DesignBrief, towers: tuple[TowerGeometry, ...]) -> Check | None:
    if not towers:
        return None
    h, floors = brief.height_intent, [t.floors for t in towers]
    problems = []
    if h.mode is HeightMode.FIXED and any(f != h.floors_above_stilt for f in floors):
        problems.append(f"floors {sorted(set(floors))}, not {h.floors_above_stilt}")
    if h.mode is HeightMode.RANGE and not all(h.floors_range[0] <= f <= h.floors_range[1]
                                              for f in floors):
        problems.append(f"floors {sorted(set(floors))} outside {h.floors_range}")
    if h.min_floors_above_stilt and min(floors) < h.min_floors_above_stilt:
        problems.append(f"a tower under {h.min_floors_above_stilt} floors")
    if any(t.has_stilt != h.has_stilt for t in towers):
        problems.append("stilt differs from the brief")
    if not h.mixed_heights_allowed and len(set(floors)) > 1:
        problems.append("heights are mixed")
    return plain(Family.PROGRAM, "Height intent", verdict(not problems),
                 "; ".join(problems) if problems else f"floors above the stilt: {sorted(floors)}",
                 f"{h.mode.value.lower().replace('_', ' ')}, as asked in the brief", BRIEF)


def _standards_check(brief: DesignBrief, candidate: CandidateLayout,
                     towers: tuple[TowerGeometry, ...]) -> Check | None:
    f = brief.firm_standards
    problems = []
    if f.max_tower_length_m and towers:
        longest = max(sides_of(t.footprint)[0] for t in towers)
        if longest > f.max_tower_length_m.value + TOL_M:
            problems.append(f"longest block {longest:.1f} m over the firm's "
                            f"{f.max_tower_length_m.value:g} m")
    if f.max_cores_per_tower:
        most = max((t.prototype.cores for t in towers), default=0)
        if most > f.max_cores_per_tower.value:
            problems.append(f"{most} cores in a block, the firm allows "
                            f"{f.max_cores_per_tower.value}")
    allowed = brief.program.allowed_types
    if allowed:
        used = {m.type_id for t in towers for m in t.prototype.modules}
        if used - set(allowed):
            problems.append("flat types outside the firm's library: "
                            + ", ".join(sorted(used - set(allowed))))
    if not brief.program.parking.surface_bays_allowed and candidate.program.bays:
        problems.append("surface bays drawn, which the brief does not allow")
    cellars = candidate.program.cellars
    if cellars and cellars.levels > brief.program.parking.max_cellars.value:
        problems.append(f"{cellars.levels} cellar levels, the brief allows "
                        f"{brief.program.parking.max_cellars.value}")
    return plain(Family.PROGRAM, "Firm standards and parking preferences", verdict(not problems),
                 "; ".join(problems) if problems else "within them", "the firm's standards",
                 BRIEF)


def program_checks(brief: DesignBrief, candidate: CandidateLayout,
                   towers: tuple[TowerGeometry, ...], rules: ResolvedRules) -> list[Check]:
    counts = units_by_type(towers)
    out = [_mix_check(brief, counts), _units_check(brief, counts),
           _club_check(brief, candidate, sum(counts.values()), rules)]
    out += _amenity_checks(brief, candidate)
    height = _height_check(brief, towers)
    out += [height] if height else []
    out.append(_standards_check(brief, candidate, towers))
    return out
