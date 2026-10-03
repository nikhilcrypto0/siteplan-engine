"""Organised open space (rule 7(a)(vii), 8(g)): how much of what the candidate calls open space
really counts, against what the law asks under every reading of the area it is a share of.

Open space counts when it lies inside the net plot, over and above the setbacks and outside the
gaps between blocks, is not a road, a lane, a bay or a building, is not the fire tender's clear
ground, and forms a pocket at least 3 m wide and 50 m². Water-buffer land counts only where the
rules say it may. The generator's own open-space figure is compared with this, never used.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    MIXED_HEIGHT_SPACING,
    OPEN_SPACE_BASIS,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.contracts.validation import Check, Family
from siteplan.validator.context import Context
from siteplan.validator.fire import clear_band
from siteplan.validator.measure import TOL_M
from siteplan.validator.readings import Assignment, Cell, check_from, plain, run, verdict
from siteplan.validator.shapes import narrower_than, opening, polygons_of, union_of_all
from siteplan.validator.zones import gap_zones, setback_zone


@dataclass(frozen=True)
class Qualifying:
    """The open space that counts under one reading of the stilt and of block spacing."""

    pockets: tuple[Polygon, ...]
    declared_sqm: float
    removed: dict[str, float]  # why ground was taken out, and how much
    setback_known: bool

    @property
    def area_sqm(self) -> float:
        return sum(p.area for p in self.pockets)


def _take_out(remaining: BaseGeometry, zone: BaseGeometry | None, why: str,
              removed: dict[str, float]) -> BaseGeometry:
    if zone is None or zone.is_empty or remaining.is_empty:
        return remaining
    gone = remaining.intersection(zone).area
    if gone > 0:
        removed[why] = removed.get(why, 0.0) + gone
    return remaining.difference(zone)


def qualifying(ctx: Context, reading: str, spacing: str) -> Qualifying:
    d, rules = ctx.drawn, ctx.rules.open_space
    declared = union_of_all(list(d.open_space))
    removed: dict[str, float] = {}
    if declared.difference(ctx.net).area > 0:
        removed["outside the net plot"] = declared.difference(ctx.net).area
    remaining = declared.intersection(ctx.net)
    zone = setback_zone(ctx, reading) if rules.over_and_above_setbacks.value else None
    remaining = _take_out(remaining, zone, "inside the setback", removed)
    if rules.block_gaps_excluded.value:
        gaps = union_of_all([z for _, z in gap_zones(ctx, reading, spacing)])
        remaining = _take_out(remaining, gaps, "in a gap between blocks", removed)
    if not rules.buffer_may_count.value:
        remaining = _take_out(remaining, ctx.land.keep_out, "in a water buffer", removed)
    lane = ctx.rules.fire.clear_width_m.value
    bands = union_of_all([clear_band(t.footprint, lane) for t in ctx.high_rise(reading)])
    remaining = _take_out(remaining, bands, "in a fire lane's clear ground", removed)
    other_uses = union_of_all([
        *(t.footprint for t in ctx.towers), d.club, d.road_land, d.fire_hardstanding,
        *d.bays, *d.ramps, *(a.shape for a in d.amenities if a.roofed)])
    remaining = _take_out(remaining, other_uses, "under a building, road, lane, bay or ramp",
                          removed)
    width, least = rules.min_width_m.value, rules.min_pocket_sqm.value
    wide = opening(remaining, width) if not remaining.is_empty else remaining
    pockets = tuple(p for p in polygons_of(wide) if p.area + TOL_M >= least)
    narrow = remaining.area - sum(p.area for p in pockets)
    if narrow > 1e-3:
        removed[f"narrower than {width:g} m or a pocket under {least:g} m²"] = narrow
    return Qualifying(pockets, declared.area, removed,
                      setback_known=zone is not None or not rules.over_and_above_setbacks.value)


def expected_requirement(ctx: Context, basis: str) -> float | None:
    """What the share of the site comes to under a reading, from the ownership figures; None for
    a reading this validator does not know the area of."""
    share, own = ctx.rules.open_space.share.value, ctx.site.ownership
    surrendered = sum(x.area_sqm.value for x in own.deductions if x.kind.value == "SURRENDER")
    areas = {"gross_before_surrender": own.gross_sqm.value,
             "gross_after_surrender": own.gross_sqm.value - surrendered,
             "net_after_surrender": own.net_sqm.value}
    return share * areas[basis] if basis in areas else None


def _requirement_agreement(ctx: Context) -> Check | None:
    """The area the rules ask under each reading, held against the ownership figures."""
    off = []
    for basis, asked in ctx.rules.open_space.requirement_sqm_by_reading.items():
        expected = expected_requirement(ctx, basis)
        if expected is not None and abs(asked - expected) > 0.005 * max(expected, 1.0):
            off.append(f"{basis}: rules {asked:,.1f} m², site {expected:,.1f} m²")
    if not off:
        return None
    return plain(Family.CONSISTENCY, "Open-space area asked: rules and site agree",
                 Status.UNVERIFIED, "; ".join(off), "the share of each area, from the ownership "
                 "figures", ctx.rules.open_space.share.clause,
                 "ResolvedRules and the site's ownership disagree on the area the open space is a "
                 "share of; the larger requirement is the one used.")


def open_space_checks(ctx: Context) -> tuple[list[Check], dict[str, float]]:
    """The open-space checks, and the quantities behind them for the report."""
    rules = ctx.rules.open_space
    share = rules.share.value
    requirements = rules.requirement_sqm_by_reading
    ground = {(r, s): qualifying(ctx, r, s) for r in ctx.stilt_readings
              for s in ctx.rules.readings(MIXED_HEIGHT_SPACING)}

    def cell(a: Assignment) -> Cell:
        basis = a[OPEN_SPACE_BASIS]
        asked = requirements[basis]
        if ctx.drawn.buildings_only and not ctx.drawn.open_space:
            return Cell(Status.UNVERIFIED, "no open space drawn",
                        f">= {share:.0%} of the {basis} area = {asked:,.1f} m²",
                        "Only the buildings are drawn: the ground between them is not known.")
        q = ground[(a[STILT_IN_RULE_HEIGHT], a[MIXED_HEIGHT_SPACING])]
        pct = 100 * q.area_sqm / (asked / share) if asked else 0.0
        measured = f"{q.area_sqm:,.1f} m² counts of {q.declared_sqm:,.1f} m² drawn"
        note = ("; ".join(f"{gone:,.1f} m² {why}" for why, gone in q.removed.items())
                if q.removed else "")
        required = (f">= {share:.0%} of the {basis} area = {asked:,.1f} m² (this is {pct:.2f}% "
                    "of it), over and above setbacks")
        if not q.setback_known:
            return Cell(Status.UNVERIFIED, measured, required,
                        "The setback is not known under this reading, so which ground is over "
                        "and above it cannot be told.")
        return Cell(verdict(q.area_sqm + TOL_M >= asked), measured, required,
                    f"Taken out: {note}." if note else "")

    main = check_from(
        run(ctx.rules, [STILT_IN_RULE_HEIGHT, MIXED_HEIGHT_SPACING, OPEN_SPACE_BASIS], cell),
        family=Family.OPEN_SPACE, rule="Organized open space (tot-lot)",
        clause=rules.share.clause,
        note="The denominator of the 10% is not settled: it is evaluated under every reading.")
    agreement = _requirement_agreement(ctx)
    quantities = {"open_space_declared_sqm": sum(p.area for p in ctx.drawn.open_space)}
    for reading in ctx.stilt_readings:
        counts = min(ground[(reading, s)].area_sqm for s in ctx.rules.readings(
            MIXED_HEIGHT_SPACING))
        quantities[f"open_space_counting_sqm[{STILT_IN_RULE_HEIGHT}={reading}]"] = counts
    for basis, asked in requirements.items():
        quantities[f"open_space_required_sqm[{OPEN_SPACE_BASIS}={basis}]"] = asked
    return [main] + ([agreement] if agreement else []), quantities


def pocket_checks(ctx: Context) -> list[Check]:
    """Each pocket the candidate draws: whether all of it counts. A pocket that does not is not
    illegal, it just does not count towards the share."""
    rules = ctx.rules.open_space
    width, least = rules.min_width_m.value, rules.min_pocket_sqm.value
    out = []
    for i, pocket in enumerate(ctx.drawn.open_space, 1):
        narrow = narrower_than(pocket, width)
        small = pocket.area + TOL_M < least
        problems = []
        if small:
            problems.append(f"under {least:g} m²")
        if narrow:
            problems.append(f"narrower than {width:g} m in places")
        out.append(plain(
            Family.OPEN_SPACE, f"Open-space pocket {i}",
            Status.INFO if problems else Status.PASS,
            f"{pocket.area:,.1f} m²" + (", " + ", ".join(problems) if problems else ""),
            f">= {least:g} m² and >= {width:g} m wide", rules.min_pocket_sqm.clause,
            "It does not count towards the share." if problems else ""))
    return out
