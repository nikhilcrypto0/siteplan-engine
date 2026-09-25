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

from siteplan.library import FlatLibrary, FlatType

MM_M = 0.001
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
WALL_ALLOWANCE = 1.12  # room labels give clear internal sizes; walls take about 12% more
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

    def saleable_sqft(self, common_area_pct: float) -> float:
        return self.carpet_sqm * SQM_SQFT * (1 + common_area_pct / 100)

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
        return self.carpet_sqm * WALL_ALLOWANCE / depth_m


def read_rooms(path: Path, text_layer: str = "A-TEXT") -> list[Room]:
    """Every labelled room in a floor-plan DXF, with the size the architect wrote on it."""
    doc = ezdxf.readfile(path)
    rooms = []
    for entity in doc.modelspace().query("TEXT MTEXT"):
        if entity.dxf.layer != text_layer:
            continue
        raw = entity.plain_text() if hasattr(entity, "plain_text") else entity.dxf.text
        name = " ".join(str(raw).split())
        size = ROOM_SIZE.search(name)
        point = entity.dxf.get("insert", None) or entity.dxf.get("align_point", None)
        if not size or point is None or NOT_A_ROOM.search(name):
            continue
        rooms.append(Room(name, point[0] * MM_M, point[1] * MM_M,
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
