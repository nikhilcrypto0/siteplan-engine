"""Parking: what Table V asks, and what the stilt, the surface and the cellars can really hold.

Rule 13(a), Table V row 4, asks a share of the total built-up area as parking area: 30% in GHMC
(and anywhere in CURE, G.O.Ms.No.45 of 2026), 20% elsewhere. Rule 13(b) lets it be met in cellars,
the stilt, and the open space over and above the setbacks, in any combination. The engine counts:

- the stilt: every tower's footprint less its lift and stair cores;
- the surface: the bays actually laid out inside the setback envelope, never in the setback band,
  a fire lane or a road (rule 13(b)(iii); NBC 4.6(c) keeps the open space round a high-rise free
  of parking);
- cellars: as many levels as it takes, each the plot less the rule 13(c)(x) cellar setback
  (3 m on a site over 2,000 m², 0.5 m more for every cellar beyond the first), less the cores,
  the ramp and the share rule 13(c)(xi) allows for utilities (up to 10%, taken in full).

The ramp is rule 13(c)(vii)'s single ramp of 5.4 m at 1 in 8, a real footprint: at the surface it
is a cut in the ground next to a road, and on every cellar level it takes floor. The area is what
Table V measures; the cars are the bays and 6 m aisles that physically fit on each floor, which
is the check that the area is usable and not just counted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from siteplan import rules

BAY_WIDTH_M = 2.5
BAY_DEPTH_M = 5.0
AISLE_M = 6.0
MAX_BAYS = 600  # a site plan stops being readable long before this
EPS_M = 0.01
RAMP_STEP_M = 2.0
# A bay and half the 6 m aisle it opens onto, as a double-loaded row is laid out.
LAID_OUT_SQM_PER_CAR = BAY_WIDTH_M * (BAY_DEPTH_M + AISLE_M / 2)


def bay_area_sqm(bays: int) -> float:
    return bays * BAY_WIDTH_M * BAY_DEPTH_M


def surface_bays(free, angle_deg: float, limit: int = MAX_BAYS,
                 double_loaded: bool = False) -> list[Polygon]:
    """Bays filling the free area, in rows running along the towers, an aisle beside each row.
    Double-loaded, two rows share one aisle, as a cellar is laid out."""
    bays: list[Polygon] = []
    for area, fitting in _fitting_bays(free, angle_deg, double_loaded):
        for bay in fitting[: limit - len(bays)]:
            bays.append(rotate(bay, angle_deg, origin=area.centroid))
        if len(bays) >= limit:
            break
    return bays


def _fitting_bays(free, angle_deg: float, double_loaded: bool):
    """For each part of the free area, the bays that fit, in its turned frame. Every place on
    the grid is tested at once."""
    for area in _parts(free):
        if area.area < BAY_WIDTH_M * BAY_DEPTH_M:
            continue
        turned = rotate(area, -angle_deg, origin="centroid")
        minx, miny, maxx, maxy = turned.bounds
        rows = _row_starts(miny, maxy, double_loaded)
        columns = np.arange(minx, maxx - BAY_WIDTH_M + EPS_M, BAY_WIDTH_M)
        if not rows or not len(columns):
            continue
        x0, y0 = (a.ravel() for a in np.meshgrid(columns, rows))
        grid = shapely.box(x0, y0, x0 + BAY_WIDTH_M, y0 + BAY_DEPTH_M)
        shapely.prepare(turned)
        yield area, list(grid[shapely.contains(turned, grid)])


def _row_starts(low: float, high: float, double_loaded: bool) -> list[float]:
    starts, y = [], low
    while y + BAY_DEPTH_M <= high + EPS_M:
        starts.append(y)
        if double_loaded and y + 2 * BAY_DEPTH_M + AISLE_M <= high + EPS_M:
            starts.append(y + BAY_DEPTH_M + AISLE_M)
            y += 2 * BAY_DEPTH_M + AISLE_M
        else:
            y += BAY_DEPTH_M + AISLE_M
    return starts


def count_bays(floor, angle_deg: float) -> int:
    """Cars that physically fit on a parking floor laid out double-loaded."""
    return sum(len(fitting) for _, fitting in _fitting_bays(floor, angle_deg, double_loaded=True))


def _parts(shape) -> list[Polygon]:
    if shape is None or shape.is_empty:
        return []
    if isinstance(shape, (list, tuple)):
        return [p for item in shape for p in _parts(item)]
    return [shape] if isinstance(shape, Polygon) else [p for p in shape.geoms
                                                       if isinstance(p, Polygon)]


@dataclass(frozen=True)
class ParkingStandards:
    """The firm's parking standards; the defaults are ours until the firm sets them."""

    cellar_floor_height_m: float = 3.0  # ramp rise per cellar level
    utilities_fraction: float = rules.CELLAR_UTILITIES_MAX_FRACTION
    max_cellars: int = 3  # a search bound, not a rule: no order limits the number of cellars


def parking_percent(authority: str | None, inside_cure: bool | None,
                    jurisdiction_confirmed: bool = True) -> tuple[float, str]:
    """The Table V share to plan for, and why. When whose rules apply is not settled, the
    stricter GHMC column is used, so a scheme that passes passes either way."""
    if authority is None or inside_cure is None or not jurisdiction_confirmed:
        return rules.PARKING_PERCENT_GHMC, (
            "jurisdiction not settled, so the stricter GHMC column is used and the answer holds "
            "either way")
    percent = rules.parking_percent(authority, inside_cure)
    where = "GHMC or CURE" if percent == rules.PARKING_PERCENT_GHMC else authority
    return percent, f"Table V column for {where}"


def ramp_size(standards: ParkingStandards) -> tuple[float, float]:
    """Width and length of the single 5.4 m ramp at 1 in 8 down one cellar level."""
    return rules.RAMP_SINGLE_MIN_WIDTH_M, standards.cellar_floor_height_m / rules.RAMP_MAX_GRADIENT


def cellar_outline(plot: Polygon, site_sqm: float, levels: int, keep_out=None):
    """The ground every cellar floor may cover: the plot less the rule 13(c)(x) setback."""
    setback = rules.cellar_setback_m(site_sqm, levels)
    outline = plot.buffer(-setback, join_style="mitre")
    return outline.difference(keep_out) if keep_out is not None else outline


def cellar_floor(outline, cores, ramps) -> object:
    """One cellar level's parking floor: the outline less the cores and the ramp."""
    taken = [*cores, *ramps]
    return outline.difference(unary_union(taken)) if taken else outline


@dataclass(frozen=True)
class ParkingPlan:
    percent: float
    basis: str  # why this percentage
    built_up_sqm: float
    stilt_sqm: float
    surface_sqm: float
    cellar_levels: int
    cellar_setback_m: float
    cellar_sqm_per_level: float  # Table V area of one level, after cores, ramp and utilities
    cellar_outline: Polygon | None = None
    ramps: tuple[Polygon, ...] = ()
    ramp_width_m: float = 0.0
    ramp_length_m: float = 0.0
    utilities_fraction: float = 0.0
    cars: dict[str, int] = field(default_factory=dict)  # bays that fit, by floor

    @property
    def required_sqm(self) -> float:
        return self.percent / 100 * self.built_up_sqm

    @property
    def cellar_sqm(self) -> float:
        return self.cellar_sqm_per_level * self.cellar_levels

    @property
    def provided_sqm(self) -> float:
        return self.stilt_sqm + self.surface_sqm + self.cellar_sqm

    @property
    def ground_sqm(self) -> float:
        """Parking at ground level, where visitors' parking is marked (rule 13(c)(xii))."""
        return self.stilt_sqm + self.surface_sqm

    @property
    def laid_out_sqm(self) -> float:
        """The parking the cars that physically fit account for: each a bay and its share of
        the aisle. Zero until the cars are counted."""
        return sum(self.cars.values()) * LAID_OUT_SQM_PER_CAR

    def as_dict(self) -> dict:
        return {
            "percent": self.percent, "basis": self.basis,
            "required_sqm": round(self.required_sqm), "provided_sqm": round(self.provided_sqm),
            "stilt_sqm": round(self.stilt_sqm), "surface_sqm": round(self.surface_sqm),
            "cellar_levels": self.cellar_levels,
            "cellar_sqm_per_level": round(self.cellar_sqm_per_level),
            "cellar_setback_m": self.cellar_setback_m,
            "ramp": (f"{len(self.ramps)} x {self.ramp_width_m:g} m wide, "
                     f"{self.ramp_length_m:g} m long at 1 in 8") if self.ramps else "none",
            "cars": dict(self.cars), "total_cars": sum(self.cars.values()),
            "laid_out_sqm": round(self.laid_out_sqm),
        }


def stilt_area(towers) -> float:
    """Every tower's stilt floor less its cores (lifts, stairs and their lobby)."""
    return sum(t.footprint.area - sum(c.area for c in t.cores) for t in towers)


def cellars_needed(need_sqm: float, ground_sqm: float, per_level) -> int | None:
    """The fewest cellar levels that meet the need; per_level(n) is one level's area when there
    are n. None when even the most the standards allow do not."""
    if ground_sqm + EPS_M >= need_sqm:
        return 0
    for levels in range(1, len(per_level) + 1):
        if ground_sqm + levels * per_level[levels - 1] + EPS_M >= need_sqm:
            return levels
    return None


def place_ramp(room, roads, width_m: float, length_m: float, anchor=None) -> Polygon | None:
    """A ramp rectangle inside `room` with one short end on a road, so cars drive straight off
    the road and down. Of the positions that fit, the one nearest the anchor (the entrance)."""
    if room.is_empty:
        return None
    near = room.buffer(0.2)
    edges = [LineString(ring.coords) for part in _parts(roads)
             for ring in (part.exterior, *part.interiors)]
    # Only the stretches of road that border the room can start a ramp into it.
    edges = [piece for edge in edges for piece in _lines(edge.intersection(near))
             if piece.length >= width_m]
    inside = prep(room)
    best: tuple[float, Polygon] | None = None
    for edge in edges:
        steps = int(edge.length // RAMP_STEP_M)
        for i in range(steps + 1):
            at = edge.interpolate(i * RAMP_STEP_M)
            ahead = edge.interpolate(min(edge.length, i * RAMP_STEP_M + 0.5))
            dx, dy = ahead.x - at.x, ahead.y - at.y
            size = (dx * dx + dy * dy) ** 0.5
            if size == 0:
                continue
            ux, uy = dx / size, dy / size
            half_x, half_y = ux * width_m / 2, uy * width_m / 2
            for nx, ny in ((-uy, ux), (uy, -ux)):
                near = (nx * EPS_M, ny * EPS_M)  # the top of the ramp, just off the road
                far = (nx * length_m, ny * length_m)  # its foot, one cellar storey down
                ramp = Polygon([
                    (at.x - half_x + near[0], at.y - half_y + near[1]),
                    (at.x + half_x + near[0], at.y + half_y + near[1]),
                    (at.x + half_x + far[0], at.y + half_y + far[1]),
                    (at.x - half_x + far[0], at.y - half_y + far[1]),
                ])
                if not inside.contains(ramp):
                    continue
                score = ramp.centroid.distance(anchor) if anchor is not None else 0.0
                if best is None or score < best[0]:
                    best = (score, ramp)
    return best[1] if best else None


def _lines(shape) -> list[LineString]:
    if shape.is_empty:
        return []
    if shape.geom_type == "LineString":
        return [shape]
    return [g for g in getattr(shape, "geoms", []) if g.geom_type == "LineString"]
