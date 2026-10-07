"""Lay the facilities into the space the buildings leave: pool, courts, play area, cabin.

This is what turns a site plan into a master plan. Each item is a rectangle of a size the
firm decides, placed in free ground near where it belongs: the pool by the club house, the
play area in the open space, the security cabin by the gate.

Two things it will not do. It never places anything on the organized open space the rules
require, because that has to stay greenery and children's play (rule 7(a)(vii)). And it
never shrinks an item to make it fit: an item with no room is reported, not squeezed in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from pydantic import BaseModel, Field, PositiveFloat
from shapely.affinity import rotate
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from siteplan.contracts.common import FacilityUse, Surface
from siteplan.contracts.design_brief import AmenityPriority

SCAN_STEP_M = 2.0
CLEARANCE_M = 1.5  # walking room between one facility and the next
EPS_M = 0.01
ANCHORS = ("club", "gate", "open space", "edge")


class AmenityItem(BaseModel):
    name: str
    width_m: PositiveFloat
    depth_m: PositiveFloat
    near: str = Field("edge", description="club, gate, open space or edge")
    # Rule 7(a)(vii) says the organized open space is to be used as "greenery, tot lot or soft
    # landscaping", so a play area or seating belongs in it. A pool or a court does not. This is
    # only where the generator may stand the item; it is never read as the item's surface.
    counts_as_open_space: bool = Field(
        False, description="May stand on the organized open space the rules require"
    )
    # What the item is for and what its ground is made of, as the firm states them. Left out they
    # are unknown: nothing reads them off the name, and a validator then leaves the item's ground
    # out of the organized open space as UNVERIFIED rather than counting it.
    use: FacilityUse | None = Field(None, description="What the facility is for")
    surface: Surface | None = Field(None, description="SOFT, HARD or BUILT, as the firm states")
    # How much the firm wants it (C4-08): REQUIRED is part of the program, a layout without it
    # fails the program; PREFERRED (unstated) and OPTIONAL are preferences, never a failure.
    priority: AmenityPriority | None = Field(
        None, description="REQUIRED, PREFERRED or OPTIONAL, as the firm states; unstated is "
                          "PREFERRED")

    @property
    def area_sqm(self) -> float:
        return self.width_m * self.depth_m


class AmenityLibrary(BaseModel):
    """The facilities a firm puts in its projects. Sizes are theirs, not ours."""

    note: str = ""
    items: list[AmenityItem] = Field(min_length=1)


@dataclass(frozen=True)
class PlacedAmenity:
    name: str
    shape: Polygon

    def as_dict(self) -> dict:
        return {"name": self.name, "area_sqm": round(self.shape.area, 1)}


def place_amenities(
    free, library: AmenityLibrary, angle_deg: float, anchors: dict[str, Point], tot_lot=None
) -> tuple[list[PlacedAmenity], list[str]]:
    """Place what fits, in the order the firm lists them, and name what did not fit. Items the
    rules allow on the organized open space may also use it; everything else may not."""
    placed: list[PlacedAmenity] = []
    missed: list[str] = []
    room = free
    open_room = room if tot_lot is None else unary_union([room, *_parts(tot_lot)])
    for item in library.items:
        here = open_room if item.counts_as_open_space else room
        spot = _fit(here, item, angle_deg, anchors.get(item.near))
        if spot is None:
            missed.append(item.name)
            continue
        placed.append(PlacedAmenity(item.name, spot))
        keep_clear = spot.buffer(CLEARANCE_M, join_style="mitre")
        room = room.difference(keep_clear)
        open_room = open_room.difference(keep_clear)
        if room.is_empty and open_room.is_empty:
            missed += [rest.name for rest in library.items[library.items.index(item) + 1:]]
            break
    return placed, missed


def _fit(room, item: AmenityItem, angle_deg: float, anchor: Point | None) -> Polygon | None:
    """The position nearest the anchor that holds the whole rectangle. Every position on the
    grid is tried at once; only the winner is built as a shape."""
    best: tuple[float, Polygon] | None = None
    for angle in (angle_deg, angle_deg + 90):
        for part in _parts(room):
            if part.area < item.area_sqm:
                continue
            turned = rotate(part, -angle, origin="centroid")
            minx, miny, maxx, maxy = turned.bounds
            xs = _steps(minx + EPS_M, maxx - item.width_m - EPS_M)
            ys = _steps(miny + EPS_M, maxy - item.depth_m - EPS_M)
            if not xs or not ys:
                continue
            x0, y0 = (a.ravel() for a in np.meshgrid(xs, ys))
            boxes = shapely.box(x0, y0, x0 + item.width_m, y0 + item.depth_m)
            shapely.prepare(turned)
            fits = shapely.contains(turned, boxes)
            if not fits.any():
                continue
            origin = part.centroid
            cx = x0[fits] + item.width_m / 2 - origin.x
            cy = y0[fits] + item.depth_m / 2 - origin.y
            turn = np.radians(angle)
            ux = origin.x + cx * np.cos(turn) - cy * np.sin(turn)
            uy = origin.y + cx * np.sin(turn) + cy * np.cos(turn)
            scores = np.hypot(ux - anchor.x, uy - anchor.y) if anchor else np.zeros(len(ux))
            pick = int(np.argmin(scores))
            if best is None or scores[pick] < best[0]:
                shape = boxes[fits][pick]
                best = (float(scores[pick]), rotate(shape, angle, origin=origin))
    return best[1] if best else None


def _steps(low: float, high: float, step: float = SCAN_STEP_M) -> list[float]:
    if high < low:
        return []
    count = int((high - low) / step)
    return [low + i * step for i in range(count + 1)] + [high]


def _parts(shape) -> list[Polygon]:
    """The polygons in a shape, a multi-shape, or a list of either."""
    if shape is None:
        return []
    if isinstance(shape, (list, tuple)):
        return [p for item in shape for p in _parts(item)]
    if shape.is_empty:
        return []
    return [shape] if isinstance(shape, Polygon) else [p for p in shape.geoms]


def free_for_amenities(envelope: Polygon, towers, club, tot_lot, bays, drive) -> Polygon:
    """Ground that is not a building, not the required open space and not parked on."""
    taken = [t.footprint for t in towers] + list(tot_lot) + list(bays)
    if club is not None:
        taken.append(club)
    if drive is not None:
        taken.append(drive)
    return envelope.difference(unary_union(taken)) if taken else envelope
