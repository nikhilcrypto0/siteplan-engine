"""The ground the blocks and the roads leave, and what goes on it.

Open space, the club house, the cellar ramp and the facilities are each placed in ground that the
rule layers permit it, in the order an architect would give it out: the club house, which is a
building of its own and keeps a Table IV gap from every block; the ramp, which has its top on a
road; then the open space, in the biggest pieces of what is left. Ground that none of them may use
is named: the setback zone (nothing but circulation, under the reading that allows it, and the
planted strip), the clear ground round every block (6 m of lane and the room to turn at each
corner), the ground between two blocks closer than the gap to both, the roads and the water buffer.

Everything is measured the way the validator measures it, so a layout built here meets the rule it
is built for: the open space is counted only beyond the setback zone, the gaps and the clear
ground, in pieces 3 m wide and 50 m² at least.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts import ResolvedRules
from siteplan.contracts.common import Surface
from siteplan.contracts.design_brief import AmenityPriority, AmenityRequest, AmenitySetting
from siteplan.optimizer.objective import reach_of, usable_open_sqm
from siteplan.optimizer.search.fit import choose_pockets, fit_rectangle
from siteplan.optimizer.search.land import EMPTY, Land, Plot, grow, polygons
from siteplan.optimizer.search.quantities import Quantities
from siteplan.parking import place_ramp

CLEARANCE_M = 1.5  # walking room between the club house, the ramp, the open space and a facility
PRIORITY_ORDER = (AmenityPriority.REQUIRED, AmenityPriority.PREFERRED, AmenityPriority.OPTIONAL)
CLUB_ASPECT = 1.6
CLUB_SIZE_SLACK_SQM = 0.2  # over the size the share asks, so rounding never leaves it under
MIN_PIECE_SQM = 0.05


@dataclass(frozen=True)
class Zones:
    """What stands on or is kept off the ground, for one arrangement of blocks and roads."""

    blocks: BaseGeometry
    nogo: BaseGeometry  # within the corner reach of a high-rise
    roads: BaseGeometry
    lanes: BaseGeometry  # fire hardstanding
    gap_zones: BaseGeometry
    turns: BaseGeometry = EMPTY  # the ground the tender sweeps turning along the ring road
    pathways: BaseGeometry = EMPTY  # rule 8(l)'s, to blocks below 12 m: paved, never open space


def gap_zones(footprints: Sequence[Polygon], gaps_m: Sequence[float]) -> BaseGeometry:
    """The ground between two blocks closer than the gap to both (the validator takes it out of the
    open space): inside their joint outline, never the blocks themselves."""
    zones = []
    for i, a in enumerate(footprints):
        for j in range(i + 1, len(footprints)):
            b = footprints[j]
            gap = max(gaps_m[i], gaps_m[j])
            if a.distance(b) >= 2 * gap:
                continue
            blocks = unary_union([a, b])
            zone = grow(a, gap).intersection(grow(b, gap)).intersection(blocks.convex_hull)
            zones.append(zone.difference(blocks))
    return unary_union(zones) if zones else EMPTY


def zones_of(footprints: Sequence[Polygon], gaps_m: Sequence[float], roads: BaseGeometry,
             lanes: BaseGeometry, reach_m: float, turns: BaseGeometry = EMPTY,
             high_rise: Sequence[bool] | None = None, pathways: BaseGeometry = EMPTY) -> Zones:
    """`high_rise` says which blocks are high-rises (all of them when not given): only round those
    does the tender need room to turn at the corners."""
    high = [f for i, f in enumerate(footprints) if high_rise is None or high_rise[i]]
    return Zones(unary_union(list(footprints)) if footprints else EMPTY,
                 unary_union([grow(f, reach_m) for f in high]) if high else EMPTY,
                 roads, lanes, gap_zones(footprints, gaps_m), turns, pathways)


def open_ground(plot: Plot, land: Land, zones: Zones) -> BaseGeometry:
    """Ground open space may stand on: the plot less the setback zone, the planted strip, the clear
    ground round the high-rises, the roads, pathways and lanes, and the gaps between blocks."""
    taken = [g for g in (land.zone, land.strip, zones.nogo, zones.roads, zones.lanes,
                         zones.gap_zones, zones.blocks, zones.turns, zones.pathways)
             if not g.is_empty]
    return plot.net.difference(unary_union(taken)) if taken else plot.net


def buildable_ground(plot: Plot, open_land: BaseGeometry) -> BaseGeometry:
    """Ground a building may stand on: open ground without the statutory exclusions."""
    return open_land.difference(plot.excluded) if not plot.excluded.is_empty else open_land


def club_size_sqm(q: Quantities, tower_sqm: float, units: int) -> float:
    """The built-up area of the club house rule 15(a)(x) asks, the block itself counted: a share
    of all the built-up area, which is a share of the towers' over one less the share. Where the
    rules also read the share as a ceiling (the 2016 wording) the size stays within it. Zero below
    the number of units the clause names."""
    if units < q.club_from_units:
        return 0.0
    size = q.club_share * tower_sqm / (1 - q.club_share) + CLUB_SIZE_SLACK_SQM
    if q.club_cap_sqm is not None and "up_to_3_percent_or_cap" in q.club_shares_read:
        size = min(size, q.club_cap_sqm)
    return size


def place_club(room: BaseGeometry, footprint_sqm: float, turns: Sequence[float],
               anchor: Point | None) -> Polygon | None:
    """The club house's footprint: a rectangle of the proportions architects draw, in the ground
    nearest the anchor that holds it."""
    depth = math.sqrt(footprint_sqm / CLUB_ASPECT)
    return fit_rectangle(room, footprint_sqm / depth, depth, turns, anchor)


def place_ramp_beside_road(room: BaseGeometry, roads: BaseGeometry, q: Quantities,
                           length_m: float, anchor: Point | None) -> Polygon | None:
    """The cellar ramp: one of the width the rules give, as long as the gradient makes it, with its
    top on a road and wholly in ground a building may stand on."""
    if room.is_empty or roads.is_empty:
        return None
    return place_ramp(room, roads, q.ramp_width_m, length_m, anchor)


def open_space_target(q: Quantities) -> float:
    return q.open_space_sqm


def choose_open_space(room: BaseGeometry, q: Quantities, turn_deg: float,
                      blocks: BaseGeometry = EMPTY) -> tuple[list[Polygon], float]:
    """The open space the rule asks for, the most usable pockets first (C4-12: the part a lawn or
    a play area fits in, near the blocks; objective.usable_open_sqm)."""
    reach = reach_of(blocks)

    def usable(pocket: BaseGeometry) -> float:
        return usable_open_sqm(pocket, reach)

    return choose_pockets(room, q.open_space_sqm, q.pocket_width_m, q.pocket_sqm, turn_deg,
                          usable if not blocks.is_empty else None)


@dataclass(frozen=True)
class PlacedFacility:
    request: AmenityRequest
    shape: Polygon


def place_facilities(requests: Sequence[AmenityRequest], rules: ResolvedRules,
                     open_pockets: Sequence[Polygon], room: BaseGeometry, club: Polygon | None,
                     turns: Sequence[float], anchor: Point | None
                     ) -> tuple[list[PlacedFacility], list[str]]:
    """The facilities the brief asks for, as many as have room; one with no room is named and
    never squeezed in. What the brief requires is laid before what it prefers, and that before
    what is optional (C4-08). Within each, the order is searched (C4-10): the firm's own, each of
    its rotations (each facility first in turn) and the largest first, and the one that places
    the most of what is required, then of what is preferred, then of what is optional is kept,
    the firm's between equals. One facility laid first-fit could leave no room for two others.
    Missed facilities are named in the firm's order."""
    classes = [[r for r in requests if r.priority is p] for p in PRIORITY_ORDER]
    best: tuple[tuple[int, ...], list[PlacedFacility], list[str]] | None = None
    for order in _orders(classes):
        placed, missed = _place_in_order(order, rules, open_pockets, room, club, turns, anchor)
        counts = tuple(-sum(1 for f in placed if f.request.priority is p) for p in PRIORITY_ORDER)
        if best is None or counts < best[0]:
            best = (counts, placed, missed)
        if not missed:
            break
    if best is None:
        return [], []
    wanted = [r.name for r in requests]
    return best[1], sorted(best[2], key=wanted.index)


def _orders(classes: Sequence[Sequence[AmenityRequest]]) -> list[list[AmenityRequest]]:
    """The orders the facilities are tried in, the classes always in theirs: the firm's, each
    rotation of it within every class, the largest first within every class."""
    def area(r: AmenityRequest) -> float:
        return r.footprint_m[0] * r.footprint_m[1] if r.footprint_m is not None else 0.0

    turns = max((len(c) for c in classes), default=0)
    orders = [[r for c in classes for r in (c[i % len(c):] + c[:i % len(c)] if c else [])]
              for i in range(max(turns, 1))]
    orders.append([r for c in classes for r in sorted(c, key=area, reverse=True)])
    return orders


def _place_in_order(requests: Sequence[AmenityRequest], rules: ResolvedRules,
                    open_pockets: Sequence[Polygon], room: BaseGeometry, club: Polygon | None,
                    turns: Sequence[float], anchor: Point | None
                    ) -> tuple[list[PlacedFacility], list[str]]:
    """The facilities in this order, each where the ground nearest the anchor holds it. A facility
    that is soft planting of a use the rule names counts as open space, so it may stand on the open
    space; every other stands beside it. A facility meant for the club house stands inside it."""
    named = set(rules.open_space.qualifying_uses.value)
    pockets = unary_union(list(open_pockets)) if open_pockets else EMPTY
    outside = room.difference(pockets) if not pockets.is_empty else room
    inside_club = club
    placed: list[PlacedFacility] = []
    missed: list[str] = []
    for request in requests:
        if request.footprint_m is None:
            missed.append(request.name)
            continue
        width, depth = request.footprint_m
        if request.setting is AmenitySetting.CLUB_HOUSE:
            spot = (fit_rectangle(inside_club, width, depth, turns, club.centroid)
                    if inside_club is not None and not inside_club.is_empty else None)
        else:
            on_pockets = request.surface is Surface.SOFT and request.use in named
            ground = unary_union([outside, pockets]) if on_pockets and not pockets.is_empty \
                else outside
            spot = fit_rectangle(ground, width, depth, turns, anchor)
        if spot is None:
            missed.append(request.name)
            continue
        placed.append(PlacedFacility(request, spot))
        if request.setting is AmenitySetting.CLUB_HOUSE:
            inside_club = inside_club.difference(spot.buffer(CLEARANCE_M, join_style="mitre"))
        else:
            keep_clear = spot.buffer(CLEARANCE_M, join_style="mitre")
            outside = outside.difference(keep_clear)
    return placed, missed


def pieces(geometry: BaseGeometry) -> list[Polygon]:
    return polygons(geometry, MIN_PIECE_SQM)
