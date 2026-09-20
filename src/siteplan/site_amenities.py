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

from pydantic import BaseModel, Field, PositiveFloat
from shapely.affinity import rotate
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

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
    # landscaping", so a play area or seating belongs in it. A pool or a court does not.
    counts_as_open_space: bool = Field(
        False, description="May stand on the organized open space the rules require"
    )

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
    """The position nearest the anchor that holds the whole rectangle."""
    best: tuple[float, Polygon] | None = None
    for angle in (angle_deg, angle_deg + 90):
        for part in _parts(room):
            if part.area < item.area_sqm:
                continue
            turned = rotate(part, -angle, origin="centroid")
            minx, miny, maxx, maxy = turned.bounds
            for x0 in _steps(minx + EPS_M, maxx - item.width_m - EPS_M):
                for y0 in _steps(miny + EPS_M, maxy - item.depth_m - EPS_M):
                    shape = box(x0, y0, x0 + item.width_m, y0 + item.depth_m)
                    if not turned.contains(shape):
                        continue
                    upright = rotate(shape, angle, origin=part.centroid)
                    score = upright.centroid.distance(anchor) if anchor else 0.0
                    if best is None or score < best[0]:
                        best = (score, upright)
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
