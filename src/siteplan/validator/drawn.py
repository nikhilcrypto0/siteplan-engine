"""What the candidate drew, as shapely geometry, read once for every check.

Nothing here is judged: roads, gates, bays, ramps, open space and the rest are only gathered,
each as the geometry the candidate gives, so the checks can measure them against the site and
the rules. The generator's own claims about them (its partition, its metrics) are not read here.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.contracts.candidate import CandidateLayout, RoadKind
from siteplan.contracts.common import Shape
from siteplan.contracts.design_brief import AmenitySetting
from siteplan.validator.shapes import polygons_of, union_of_all

BUILT_WORDS = ("CABIN", "ROOM", "SUBSTATION")


def geometry_of(shapes: list[Shape]) -> BaseGeometry:
    return union_of_all([s.to_shapely() for s in shapes])


@dataclass(frozen=True)
class DrawnRoad:
    id: str
    kind: RoadKind
    declared_width_m: float
    shape: BaseGeometry
    tags: tuple[str, ...]


@dataclass(frozen=True)
class DrawnAmenity:
    name: str
    shape: BaseGeometry
    setting: AmenitySetting

    @property
    def roofed(self) -> bool:
        """A small structure with a roof (a cabin, a substation) rather than ground laid out for
        play or sport: judged by its name, the only thing a placed amenity carries."""
        return any(word in self.name.upper() for word in BUILT_WORDS)


@dataclass(frozen=True)
class Gate:
    shape: BaseGeometry
    declared_width_m: float


@dataclass(frozen=True)
class Drawn:
    roads: tuple[DrawnRoad, ...]
    gates: tuple[Gate, ...]
    fire_hardstanding: BaseGeometry
    club: BaseGeometry
    club_floors: int
    amenities: tuple[DrawnAmenity, ...]
    ramps: tuple[Polygon, ...]
    bays: tuple[Polygon, ...]
    open_space: tuple[Polygon, ...]
    green_strip: BaseGeometry
    cellar_drawn: bool  # False when the candidate carries no cellar plan at all
    cellar_levels: int
    cellar_outline: BaseGeometry
    cellar_setback_claimed_m: float | None

    @property
    def buildings_only(self) -> bool:
        """Nothing but buildings is drawn (a firm's drawing traced into a case, say): the ground
        between them is unknown, not empty, so what is missing there is UNVERIFIED, not a FAIL."""
        return not (self.roads or self.gates or self.ramps or self.bays or self.open_space
                    or self.amenities or self.cellar_drawn or not self.club.is_empty
                    or not self.fire_hardstanding.is_empty or not self.green_strip.is_empty)

    @property
    def road_land(self) -> BaseGeometry:
        return union_of_all([r.shape for r in self.roads])

    @property
    def motorable(self) -> BaseGeometry:
        """Ground a fire tender may drive on: every road and the clear hardstanding."""
        return union_of_all([self.road_land, self.fire_hardstanding])

    @property
    def has_circulation(self) -> bool:
        return bool(self.roads) or not self.fire_hardstanding.is_empty

    def roads_of(self, *kinds: RoadKind) -> list[DrawnRoad]:
        return [r for r in self.roads if not kinds or r.kind in kinds]

    @property
    def gate_land(self) -> BaseGeometry:
        return union_of_all([g.shape for g in self.gates])


def read(candidate: CandidateLayout) -> Drawn:
    program, circulation = candidate.program, candidate.circulation
    cellars = program.cellars
    return Drawn(
        roads=tuple(DrawnRoad(r.id, r.kind, r.declared_width_m, geometry_of(r.shapes),
                              tuple(r.tags)) for r in circulation.roads),
        gates=tuple(Gate(g.shape.to_shapely(), g.width_m) for g in circulation.gates),
        fire_hardstanding=geometry_of(circulation.fire_hardstanding),
        club=program.club_house.shape.to_shapely() if program.club_house else Polygon(),
        club_floors=program.club_house.floors if program.club_house else 0,
        amenities=tuple(DrawnAmenity(a.name, a.shape.to_shapely(), a.setting)
                        for a in program.amenities),
        ramps=tuple(p for r in program.ramps for p in polygons_of(r.to_shapely())),
        bays=tuple(p for b in program.bays for p in polygons_of(b.to_shapely())),
        open_space=tuple(p for s in program.open_space for p in polygons_of(s.to_shapely())),
        green_strip=geometry_of(program.green_strip),
        cellar_drawn=cellars is not None,
        cellar_levels=cellars.levels if cellars else 0,
        cellar_outline=geometry_of(cellars.outline) if cellars else Polygon(),
        cellar_setback_claimed_m=cellars.setback_m if cellars else None)
