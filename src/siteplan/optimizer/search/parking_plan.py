"""Parking that physically fits: the stilt, the cellars and what Table V asks.

Table V asks a share of the built-up area as parking floor; rule 13(b) lets it be met in the stilt,
the open space beyond the setbacks and the cellars. The cellars take the whole plot less the cellar
setback of rule 13(c)(x), which grows with every level, less the cores, the ramp and the share
rule 13(c)(xi) allows for utilities. The area is not enough: the cars laid out in bays and aisles on
every floor have to meet it too, and that count is made here the way a floor is really laid out.

The count is deliberately a little shy of the validator's (fewer offsets are tried), so a plan
that meets the need here meets it there.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts import ResolvedRules
from siteplan.optimizer.search.land import EMPTY, erode, polygons
from siteplan.optimizer.search.quantities import Quantities

EPS_M = 0.01
EDGE_M = 1e-4
OFFSETS_ALONG = (0.0, 1.25)
OFFSETS_ACROSS = (0.0, 2.7, 5.3, 8.0, 10.7, 13.3)
SAFETY_SQM = 1.0  # what the plan keeps above the need, so rounding never leaves it short


def cars_on_floor(floor: BaseGeometry, turns_deg: Sequence[float], bay: tuple[float, float],
                  aisle_m: float) -> int:
    """The most cars that fit on a floor in any of the turns (and a quarter turn from each), part
    by part, in double-loaded rows: a row of bays, an aisle, a row of bays."""
    turns = sorted({round(t % 180, 3) for angle in turns_deg for t in (angle, angle + 90)})
    total = 0
    for part in polygons(floor):
        if part.area < bay[0] * bay[1]:
            continue
        total += max(_count(part, turn, bay, aisle_m, along, across)
                     for turn in turns for along in OFFSETS_ALONG for across in OFFSETS_ACROSS)
    return total


def _rows(low: float, high: float, depth: float, aisle: float) -> list[float]:
    starts, y = [], low
    while y + depth <= high + EPS_M:
        starts.append(y)
        if y + 2 * depth + aisle <= high + EPS_M:
            starts.append(y + depth + aisle)
            y += 2 * depth + aisle
        else:
            y += depth + aisle
    return starts


def _count(part: Polygon, turn: float, bay: tuple[float, float], aisle: float, along: float,
           across: float) -> int:
    width, depth = bay
    turned = rotate(part, -turn, origin="centroid").buffer(EDGE_M, join_style="mitre")
    minx, miny, maxx, maxy = turned.bounds
    minx, miny, maxx, maxy = minx + EDGE_M, miny + EDGE_M, maxx - EDGE_M, maxy - EDGE_M
    rows = _rows(miny + across, maxy, depth, aisle)
    columns = np.arange(minx + along, maxx - width + EPS_M, width)
    if not rows or not len(columns):
        return 0
    x, y = (a.ravel() for a in np.meshgrid(columns, rows))
    shapely.prepare(turned)
    return int(shapely.contains(turned, shapely.box(x, y, x + width, y + depth)).sum())


def cellar_setback(rules: ResolvedRules, site_sqm: float, levels: int, extra_per_level_m: float
                   ) -> float | None:
    """Rule 13(c)(x): the setback by site size, and more for every cellar beyond the first, applied
    to all of them (the stricter reading). None when the rules' table has no row for the site."""
    table = rules.parking.cellar_setback_by_site_sqm.value
    base = next((m for up_to, m in table if up_to is None or site_sqm <= up_to), None)
    if base is None:
        return None
    return base + extra_per_level_m * max(0, levels - 1)


@dataclass(frozen=True)
class Cellars:
    levels: int
    outline: BaseGeometry
    setback_m: float
    per_level_sqm: float
    per_level_cars: int


@dataclass(frozen=True)
class ParkingPlan:
    need_sqm: float
    stilt_sqm: float
    stilt_cars: int
    cellars: Cellars | None
    cars: int
    provided_sqm: float  # the least of the floor area and the area the cars laid out account for

    @property
    def levels(self) -> int:
        return self.cellars.levels if self.cellars else 0


def plan_parking(net: Polygon, excluded: BaseGeometry, rules: ResolvedRules, q: Quantities,
                 towers: Sequence[Polygon], cores: Sequence[BaseGeometry],
                 ramps: Sequence[Polygon], built_up_sqm: float, turn_deg: float
                 ) -> tuple[ParkingPlan | None, str]:
    """The fewest cellar levels that meet Table V by floor area and by cars laid out, or why none
    do within the deepest the brief allows."""
    need = max(q.parking_shares, default=0.0) / 100 * built_up_sqm * (1 + q.parking_margin)
    turns = sorted({turn_deg % 180, 0.0})
    core_land = unary_union([c for c in cores if not c.is_empty]) if cores else EMPTY
    stilts = [t.difference(core_land) for t in towers] if q.has_stilt else []
    stilt_sqm = sum(f.area for f in stilts)
    stilt_cars = sum(cars_on_floor(f, [turn_deg], q.bay_m, q.aisle_m) for f in stilts)
    best = ParkingPlan(need, stilt_sqm, stilt_cars, None, stilt_cars,
                       min(stilt_sqm, stilt_cars * q.sqm_per_car))
    if best.provided_sqm >= need + SAFETY_SQM:
        return best, ""
    site_sqm = net.area
    for levels in range(1, q.max_cellars + 1):
        setback = cellar_setback(rules, site_sqm, levels, q.cellar_extra_per_level_m)
        if setback is None:
            return None, "the rules give no cellar setback for a site this large"
        outline = erode(net, setback).difference(excluded) if not excluded.is_empty \
            else erode(net, setback)
        if outline.is_empty:
            return None, "no ground is left for a cellar inside its setback"
        floor = outline.difference(unary_union([core_land, *ramps]) if ramps else core_land)
        per_level = floor.area * (1 - q.utilities_share)
        cars_per_level = int(cars_on_floor(floor, turns, q.bay_m, q.aisle_m)
                             * (1 - q.utilities_share))
        area = stilt_sqm + levels * per_level
        laid_out = (stilt_cars + levels * cars_per_level) * q.sqm_per_car
        provided = min(area, laid_out)
        if provided >= need + SAFETY_SQM:
            return ParkingPlan(need, stilt_sqm, stilt_cars,
                               Cellars(levels, outline, setback, per_level, cars_per_level),
                               stilt_cars + levels * cars_per_level, provided), ""
    return None, (f"Table V asks {need:,.0f} m² of parking; the stilt and {q.max_cellars} "
                  "cellar level(s) hold fewer cars than that")


def ramp_length_m(q: Quantities) -> float:
    """The length of a ramp down one cellar storey at the gradient the rules give."""
    return q.ramp_rise_m / q.ramp_gradient


__all__ = ["Cellars", "ParkingPlan", "cars_on_floor", "cellar_setback", "plan_parking",
           "ramp_length_m", "math"]
