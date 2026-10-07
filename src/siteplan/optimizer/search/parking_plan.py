"""Parking that physically fits: the stilt, the cellars and what Table V asks.

Table V asks a share of the built-up area as parking floor; rule 13(b) lets it be met in the stilt,
the open space beyond the setbacks and the cellars. A cellar may take the plot less the cellar
setback of rule 13(c)(x), which grows with every level, less the cores, the ramp and the share
rule 13(c)(xi) allows for utilities, and runs under no block the search lays no fire band for: a
block over a cellar of more than 500 m², or of two levels, is an NBC special building (Part 4
1.2(b)(6)), held to 4.6's fire access whatever its height. It takes only what the need asks
(C4-13): once the fewest levels are known, its outline is a rectangle square to the configuration's
turn grown round the ramp, the piece of the plot under the setback inside it that the ramp reaches
and that holds the need, the same on every level; a level of the whole plot dug for a few cars was
the rule before. The area is not
enough: the cars laid out in bays and aisles on every floor have to meet it too, and that count is
made here the way a floor is really laid out.

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
CUT_STEPS = 12  # halvings that size a cellar round its ramp: to 1/4096 of the plot (C4-13)
FIT_ROUNDS = 4  # car counts a cellar is grown by at most, before the whole is kept
FIT_MARGIN = 0.02  # each growth asks this much more floor than the cars counted suggest


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
                 ramps: Sequence[Polygon], built_up_sqm: float, turn_deg: float,
                 clear_of: BaseGeometry = EMPTY) -> tuple[ParkingPlan | None, str]:
    """The fewest cellar levels that meet Table V by floor area and by cars laid out, or why none
    do within the deepest the brief allows. The cellars run under nothing in `clear_of`: the
    blocks with no fire band, which a cellar under them would make special buildings."""
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
        if not clear_of.is_empty:
            outline = outline.difference(clear_of)
        if outline.is_empty:
            return None, "no ground is left for a cellar inside its setback"
        level = _Level(unary_union([core_land, *ramps]) if ramps else core_land, levels,
                       stilt_sqm, stilt_cars, tuple(turns), q, need + SAFETY_SQM)
        per_level, cars_per_level, provided = level.counted(outline)
        if provided >= level.target:
            if ramps:
                density = cars_per_level / max(level.floor_of(outline), 1.0)
                sized = _sized(outline, unary_union(ramps), turn_deg, level, density)
                if sized is not None:
                    outline, (per_level, cars_per_level, provided) = sized
            return ParkingPlan(need, stilt_sqm, stilt_cars,
                               Cellars(levels, outline, setback, per_level, cars_per_level),
                               stilt_cars + levels * cars_per_level, provided), ""
    return None, (f"Table V asks {need:,.0f} m² of parking; the stilt and {q.max_cellars} "
                  "cellar level(s) hold fewer cars than that")


@dataclass(frozen=True)
class _Level:
    """What the cellars of so many levels must give, and how a part of their outline counts."""

    taken: BaseGeometry  # the cores and the ramps, which take floor on every level
    levels: int
    stilt_sqm: float
    stilt_cars: int
    turns: tuple[float, ...]
    q: Quantities
    target: float  # the need and the safety kept above it

    def counted(self, part: BaseGeometry) -> tuple[float, int, float]:
        """A level's floor and cars on this part of the outline, and what the plan provides."""
        q = self.q
        floor = part.difference(self.taken)
        per_level = floor.area * (1 - q.utilities_share)
        cars = int(cars_on_floor(floor, self.turns, q.bay_m, q.aisle_m) * (1 - q.utilities_share))
        return per_level, cars, min(self.stilt_sqm + self.levels * per_level,
                                    (self.stilt_cars + self.levels * cars) * q.sqm_per_car)

    def floor_of(self, part: BaseGeometry) -> float:
        """A level's parking floor on this part of the outline: cheap, no car counted."""
        return part.difference(self.taken).area * (1 - self.q.utilities_share)

    @property
    def floor_needed(self) -> float:
        """The floor a level must give for the area the need asks."""
        return (self.target - self.stilt_sqm) / self.levels

    @property
    def cars_needed(self) -> float:
        """The cars a level must hold for the need, at so much floor a car."""
        return (self.target / self.q.sqm_per_car - self.stilt_cars) / self.levels


def _sized(outline: BaseGeometry, ramps: BaseGeometry, turn_deg: float, level: _Level,
           density: float) -> tuple[BaseGeometry, tuple[float, int, float]] | None:
    """The part of a cellar's outline the need takes (C4-13): a rectangle square to the turn grown
    round the ramps, the piece of the outline inside it the ramps reach. The growth is placed for
    the floor the need asks, by area and by its cars at the `density` the whole level was counted
    at, and a little more (FIT_MARGIN); then, while the cars counted leave it short, for the floor
    that many cars ask at the density counted on the piece, at most FIT_ROUNDS counts. The piece
    and its count (`_Level.counted`); None, for the whole outline, when no smaller piece holds the
    need."""
    turned = rotate(outline, -turn_deg, origin=(0, 0))
    down = rotate(ramps, -turn_deg, origin=(0, 0))
    rx0, ry0, rx1, ry1 = down.bounds
    x0, y0, x1, y1 = turned.bounds
    whole = max(rx0 - x0, x1 - rx1, ry0 - y0, y1 - ry1, 0.0)  # the growth that takes it all

    def piece(grown: float) -> BaseGeometry:
        parts = polygons(turned.intersection(
            shapely.box(rx0 - grown, ry0 - grown, rx1 + grown, ry1 + grown)))
        if not parts:
            return EMPTY
        near = min(parts, key=lambda p: p.distance(down))
        return rotate(near, turn_deg, origin=(0, 0))

    most = level.floor_of(piece(whole))

    def grown_for(floor_sqm: float) -> float:
        """The least growth whose piece gives this much floor a level (all of it if none does)."""
        if most < floor_sqm:
            return whole
        short, enough = 0.0, whole
        for _ in range(CUT_STEPS):
            middle = (short + enough) / 2
            short, enough = (short, middle) if level.floor_of(piece(middle)) >= floor_sqm \
                else (middle, enough)
        return enough

    grown = grown_for(max(level.floor_needed,
                          level.cars_needed / max(density, 1e-9) * (1 + FIT_MARGIN)))
    for _ in range(FIT_ROUNDS):
        part = piece(grown)
        counted = level.counted(part)
        if counted[2] >= level.target:
            return part, counted
        if grown >= whole:
            break
        floor = level.floor_of(part)
        grown = grown_for(floor * max(level.cars_needed / max(counted[1], 1), 1.0)
                          * (1 + FIT_MARGIN))
    return None


def ramp_length_m(q: Quantities) -> float:
    """The length of a ramp down one cellar storey at the gradient the rules give."""
    return q.ramp_rise_m / q.ramp_gradient


__all__ = ["Cellars", "ParkingPlan", "cars_on_floor", "cellar_setback", "plan_parking",
           "ramp_length_m", "math"]
