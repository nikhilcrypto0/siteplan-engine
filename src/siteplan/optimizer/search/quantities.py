"""The numbers the search reads from the rules and the brief, in one place.

Every figure is the law's (ResolvedRules) or the firm's (DesignBrief); the search invents none.
Where the rules leave a question open, the figure is the one that holds under every reading, which
is the largest of the requirements and the strictest of the distances. A design margin raises a
target above the legal minimum and is never taken for law: `margins` is what the search aims at,
`legal` what the validator holds the layout to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from siteplan import rules as law
from siteplan.contracts import CanonicalSiteModel, DesignBrief, ResolvedRules
from siteplan.contracts.design_brief import DesignMargins
from siteplan.contracts.resolved_rules import (
    AMENITY_SHARE,
    FIRE_TURNING_RADIUS,
    OPEN_SPACE_BASIS,
    TableVColumn,
)
from siteplan.units import sqft_to_sqm

QUARTER_TURN = math.pi / 4  # a lane turning a square corner sweeps from the corner to this angle


@dataclass(frozen=True)
class Quantities:
    road_m: float  # a loop, a street: the rule's width and the margin
    legal_road_m: float
    approach_m: float
    lane_m: float  # clear, motorable ground on every side of a high-rise
    reach_m: float  # clear ground at a corner of a block, for the tender to turn round it
    turnings: tuple[tuple[float, float], ...]  # (inner, outer) radius of the lane, each reading
    pocket_width_m: float
    pocket_sqm: float
    open_space_sqm: float  # what the open space aims at: the largest legal need, plus the margin
    open_space_legal_sqm: float
    strip_width_m: float
    strip_from_setback_m: float
    club_share: float
    club_cap_sqm: float | None
    club_from_units: int
    club_shares_read: tuple[str, ...]
    gap_margin_m: float
    setback_margin_m: float
    parking_margin: float
    parking_shares: tuple[float, ...]  # the Table V shares the layout may be held to, in percent
    ramp_width_m: float
    ramp_rise_m: float
    ramp_gradient: float
    utilities_share: float
    bay_m: tuple[float, float]
    aisle_m: float
    sqm_per_car: float
    max_cellars: int
    surface_bays: bool
    cellar_extra_per_level_m: float
    stilt_m: float
    floor_m: float
    has_stilt: bool
    # Rule 8(l): a pathway this wide may reach a block up to this high (physical, the stilt
    # included); a taller block opens onto an internal road, unless the rules read the clause as
    # allowing a pathway to any block. No pathway is drawn where the rules give no width.
    pathway_m: float | None
    pathway_max_height_m: float
    pathway_any_block: bool
    pathway_max_length_m: float  # NBC 4.3.2.2 through rule 15(a)(i): from the road to the block
    driveway_m: float  # rule 13(c)(viii): the least way into a stilt, as the validator reads it


def quantities(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
               with_margins: bool = True) -> Quantities:
    """The numbers to plan with. With the margins, the targets the firm set above the legal
    minimums; without them the legal minimums themselves, which is what a layout is held to."""
    margins = brief.design_margins if with_margins else DesignMargins()
    road = rules.circulation.internal_road_m.value
    approach_low, approach_high = rules.circulation.approach_m.value
    lane = rules.fire.clear_width_m.value
    standards = brief.firm_standards
    measurement = rules.parking.measurement
    bay = standards.bay_size_m.value if standards.bay_size_m else measurement.bay_m
    aisle = standards.aisle_m.value if standards.aisle_m else measurement.aisle_m
    own = standards.bay_size_m is not None or standards.aisle_m is not None
    cap = rules.amenities.cap_sqft_2016.value
    legal_open = _open_space_need(site, rules)
    share = rules.open_space.share.value
    return Quantities(
        road_m=road + margins.road_width_extra_m.value, legal_road_m=road,
        approach_m=min(approach_high, approach_low + margins.road_width_extra_m.value),
        lane_m=lane, reach_m=_reach(rules, lane), turnings=tuple(_turnings(rules, lane)),
        pocket_width_m=rules.open_space.min_width_m.value,
        pocket_sqm=rules.open_space.min_pocket_sqm.value,
        open_space_sqm=margins.open_space_target_sqm(legal_open, share),
        open_space_legal_sqm=legal_open,
        strip_width_m=rules.green_strip.width_m.value,
        strip_from_setback_m=rules.green_strip.where_setback_from_m.value,
        club_share=rules.amenities.share_of_built_up.value,
        club_cap_sqm=sqft_to_sqm(cap) if cap else None,
        club_from_units=rules.amenities.from_units.value,
        club_shares_read=tuple(rules.readings(AMENITY_SHARE)),
        gap_margin_m=margins.tower_gap_extra_m.value,
        setback_margin_m=margins.setback_extra_m.value,
        parking_margin=margins.parking_extra_fraction.value,
        parking_shares=tuple(table_v_shares(site, rules)),
        ramp_width_m=rules.parking.ramp_single_min_m.value,
        ramp_rise_m=standards.cellar_floor_height_m.value,
        ramp_gradient=rules.parking.ramp_gradient.value,
        utilities_share=standards.cellar_utilities_share.value,
        bay_m=bay, aisle_m=aisle,
        sqm_per_car=bay[0] * (bay[1] + aisle / 2) if own else measurement.sqm_per_car,
        max_cellars=brief.program.parking.max_cellars.value,
        surface_bays=brief.program.parking.surface_bays_allowed,
        cellar_extra_per_level_m=rules.parking.cellar_extra_setback_per_level_m.value,
        stilt_m=standards.stilt_height_m.value, floor_m=standards.floor_to_floor_m.value,
        has_stilt=brief.height_intent.has_stilt,
        pathway_m=(rules.circulation.pathway_width_m.value
                   if rules.circulation.pathway_width_m is not None else None),
        pathway_max_height_m=rules.circulation.pathway_max_block_height_m.value,
        pathway_any_block=not rules.circulation.block_over_12m_on_road.value,
        pathway_max_length_m=rules.circulation.pathway_max_length_m.value,
        driveway_m=rules.circulation.driveway_min_m.value)


def _turnings(rules: ResolvedRules, lane: float) -> list[tuple[float, float]]:
    """The inner and outer radius of the lane's turn under each reading of where the tender's
    turning radius is measured (a reading nobody can evaluate is left out: the validator leaves
    it UNVERIFIED)."""
    radius = rules.fire.turning_radius_m.value
    found = []
    for reading in rules.readings(FIRE_TURNING_RADIUS):
        if reading == "outer_edge":
            found.append((radius - lane, radius))
        elif reading == "centreline":
            found.append((radius - lane / 2, radius + lane / 2))
    return found


def _reach(rules: ResolvedRules, lane: float) -> float:
    """How far from each face of a block the ground must stay clear at its corners, under the
    readings of where the tender's turning radius is measured: the greatest of them."""
    reach = max((r_out - r_in * math.sin(QUARTER_TURN) for r_in, r_out in _turnings(rules, lane)),
                default=0.0)
    return reach or lane


def _open_space_need(site: CanonicalSiteModel, rules: ResolvedRules) -> float:
    """The most open space any reading of the area it is a share of asks for (the rules' own
    figure, and the share of the area the ownership gives)."""
    share = rules.open_space.share.value
    own = site.ownership
    surrendered = sum(d.area_sqm.value for d in own.deductions if d.kind.value == "SURRENDER")
    areas = {"gross_before_surrender": own.gross_sqm.value,
             "gross_after_surrender": own.gross_sqm.value - surrendered,
             "net_after_surrender": own.net_sqm.value}
    need = 0.0
    for basis in rules.readings(OPEN_SPACE_BASIS):
        need = max(need, rules.open_space.requirement_sqm_by_reading.get(basis, 0.0),
                   share * areas.get(basis, 0.0))
    return need


def table_v_shares(site: CanonicalSiteModel, rules: ResolvedRules) -> list[float]:
    """The shares of Table V the parking may be held to: the column the rules settled on, and any
    column the site's own jurisdiction allows (both, while whose rules apply is open)."""
    p = rules.parking
    by_column = {c: pct for c, pct in p.share_pct_by_column.items() if c is not TableVColumn.OPEN}
    carried = {p.share_pct.value} if p.share_pct is not None else set(by_column.values())
    j = site.jurisdiction
    allowed = law.parking_columns(j.authority.value, j.inside_cure.value)
    return sorted(carried | {pct for pct in by_column.values() if pct in allowed})
