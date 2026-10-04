"""Read a firm's own floor-plan DXF into a flat library.

The architect writes each room's size into its label ("MASTER BEDROOM 4315X3465"), so the
sizes come from the drawing rather than from us. Walls will not serve: they are drawn as
separate lines broken at every door, so they do not close into rooms (tried, and 90 wall
segments produced no flat-sized face). Block names will not serve either: this firm's are
draftsman shorthand, and "MAIN DOOR" is the block for every door, not the flat's own.

What does serve is the kitchen. A flat has exactly one, so counting kitchens counts flats,
and every other room belongs to the kitchen it sits nearest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from statistics import median

import ezdxf

from siteplan.dxf_entities import (
    TEXT_TYPES,
    declared_metres_per_unit,
    open_blocks,
    text_of,
    text_position,
)
from siteplan.library import FlatLibrary, FlatType

MM_M = 0.001  # room sizes are written in millimetres, whatever the drawing unit
SQM_SQFT = 10.7639
ROOM_SIZE = re.compile(r"(\d{3,5})\s*[xX]\s*(\d{3,5})")
KITCHEN = re.compile(r"\bKITCHEN\b", re.I)
BEDROOM = re.compile(r"BED\s*ROOM|BEDROOM|M\.BED", re.I)
# Shared parts of a building, and anything that is not a room inside a flat.
NOT_A_ROOM = re.compile(
    r"OPEN TO SKY|GARBAGE|STAIR|LIFT|LOBBY|CORRIDOR|DUCT|SHAFT|TERRACE|PARKING|RAMP|"
    r"CLUB|GYM|POOL|SALOON|OFFICE|SECURITY|GENERATOR|TRANSFORMER|SUMP|STP",
    re.I,
)
# Three areas, and a firm sells on the third. Room labels give the clear internal size, so
# carpet; walls and balconies make it built-up, which is the figure an area statement prints;
# the common-area loading on top of that is what the flat is sold as. Quoting carpet as if it
# were saleable understates a scheme by a third, which is what this engine did until a
# comparison with the firm's own Dhulapally statement showed 325,152 sft against their 474,912.
BUILT_UP_FROM_CARPET = 1.12
MIN_CARPET_PER_BEDROOM_SQM = 22.0  # below this the grouping has pulled in a neighbour's room
ROOM_REACH_M = 11.0  # a room further than this from any kitchen is not part of a flat
PLAUSIBLE_ROOMS = range(3, 13)
PLAUSIBLE_BEDROOMS = range(1, 5)


@dataclass(frozen=True)
class Room:
    name: str
    x: float
    y: float
    width_m: float
    depth_m: float

    @property
    def area_sqm(self) -> float:
        return self.width_m * self.depth_m

    @property
    def is_kitchen(self) -> bool:
        return bool(KITCHEN.search(self.name))

    @property
    def is_bedroom(self) -> bool:
        return bool(BEDROOM.search(self.name))


@dataclass(frozen=True)
class FlatPlan:
    """One flat as the drawing describes it: the rooms that belong to its kitchen."""

    rooms: tuple[Room, ...]

    @property
    def bedrooms(self) -> int:
        return sum(1 for r in self.rooms if r.is_bedroom)

    @property
    def carpet_sqm(self) -> float:
        return sum(r.area_sqm for r in self.rooms)

    @property
    def category(self) -> str:
        return f"{self.bedrooms}BHK"

    @property
    def plausible(self) -> bool:
        return (len(self.rooms) in PLAUSIBLE_ROOMS
                and self.bedrooms in PLAUSIBLE_BEDROOMS
                and self.carpet_per_bedroom_sqm >= MIN_CARPET_PER_BEDROOM_SQM)

    @property
    def built_up_sqm(self) -> float:
        """Carpet plus its walls and balconies: what an area statement prints."""
        return self.carpet_sqm * BUILT_UP_FROM_CARPET

    def saleable_sqft(self, common_area_pct: float) -> float:
        """Built-up with the common-area loading: what the flat is sold as."""
        return self.built_up_sqm * SQM_SQFT * (1 + common_area_pct / 100)

    @property
    def carpet_per_bedroom_sqm(self) -> float:
        return self.carpet_sqm / self.bedrooms if self.bedrooms else 0.0

    def depth_m(self) -> float:
        """How deep the flat runs, from where its rooms sit across the tower."""
        return max(r.y for r in self.rooms) - min(r.y for r in self.rooms) + max(
            r.depth_m for r in self.rooms
        )

    def width_m(self, depth_m: float) -> float:
        """Frontage along the corridor. Taken from the area rather than from the label
        positions: a label sits wherever it fits, so the spread of labels measures the
        draughtsman's hand, not the flat. Walls are not in the room sizes, so they are
        allowed for here."""
        return self.built_up_sqm / depth_m


def read_rooms(path: Path, text_layer: str = "A-TEXT",
               metres_per_unit: float | None = None) -> list[Room]:
    """Every labelled room in a floor-plan DXF, with the size the architect wrote on it.

    Where a label sits is in the drawing's own unit, which its header declares (Suchitra's
    says millimetres; the firm's Dhulapally site plan says inches). The size in the label is
    millimetres whatever the drawing unit, as architects write it. Labels inside blocks count:
    a flat drawn once and placed many times is still many flats.
    """
    doc = ezdxf.readfile(path)
    k = metres_per_unit or declared_metres_per_unit(doc)
    if k is None:
        raise ValueError(f"{path}: drawing units are not set ($INSUNITS). "
                         "Say what one drawing unit is with metres_per_unit.")
    rooms = []
    for drawn in open_blocks(doc.modelspace()).drawn:
        entity = drawn.entity
        if entity.dxftype() not in TEXT_TYPES or drawn.layer != text_layer:
            continue
        name = text_of(entity)
        size = ROOM_SIZE.search(name)
        point = text_position(entity)
        if not size or point is None or NOT_A_ROOM.search(name):
            continue
        rooms.append(Room(name, point[0] * k, point[1] * k,
                          int(size.group(1)) * MM_M, int(size.group(2)) * MM_M))
    return rooms


def to_library(
    flats: list[FlatPlan],
    common_area_pct: float = 22.0,
    core_width_m: float = 7.5,
    corridor_width_m: float = 2.13,
    per_category: int = 2,
    note: str = "",
) -> FlatLibrary:
    """The repeated flat types, as a library the solver can build towers from.

    A type has to appear at least twice: a one-off is a corner unit or a misread, not a
    standard the firm repeats. Depths are forced to one value because v0 assembles towers
    from flats of equal depth, and the note says so.
    """
    usable = [f for f in flats if f.plausible]
    if not usable:
        raise ValueError("No flat in this drawing had a plausible set of rooms.")
    depth_m = round(median(f.depth_m() for f in usable), 2)

    seen: dict[tuple[str, float], list[FlatPlan]] = {}
    for flat in usable:
        seen.setdefault((flat.category, round(flat.carpet_sqm / 5) * 5), []).append(flat)
    repeated = {key: group for key, group in seen.items() if len(group) >= 2}

    types: list[FlatType] = []
    for category in sorted({key[0] for key in repeated}):
        ranked = sorted(((key, group) for key, group in repeated.items() if key[0] == category),
                        key=lambda item: -len(item[1]))
        for letter, (_, group) in zip("ABCDEF", ranked[:per_category], strict=False):
            types.append(FlatType(
                name=f"{category}-{letter}",
                bhk=category,
                width_m=round(median(f.width_m(depth_m) for f in group), 2),
                depth_m=depth_m,
                saleable_sqft=round(median(f.saleable_sqft(common_area_pct) for f in group)),
                carpet_sqft=round(median(f.carpet_sqm for f in group) * SQM_SQFT),
                built_up_sqft=round(median(f.built_up_sqm for f in group) * SQM_SQFT),
            ))
    if not types:
        raise ValueError("No flat type repeated in this drawing; nothing to build a library on.")
    return FlatLibrary(note=note, flats=types, core_width_m=core_width_m,
                       corridor_width_m=corridor_width_m)


def group_into_flats(rooms: list[Room], reach_m: float = ROOM_REACH_M) -> list[FlatPlan]:
    """One flat per kitchen; every other room joins the kitchen it sits nearest."""
    kitchens = [r for r in rooms if r.is_kitchen]
    if not kitchens:
        return []
    grouped: list[list[Room]] = [[k] for k in kitchens]
    for room in rooms:
        if room.is_kitchen:
            continue
        nearest, closest = None, reach_m
        for index, kitchen in enumerate(kitchens):
            gap = hypot(room.x - kitchen.x, room.y - kitchen.y)
            if gap < closest:
                nearest, closest = index, gap
        if nearest is not None:
            grouped[nearest].append(room)
    return [FlatPlan(tuple(group)) for group in grouped]
