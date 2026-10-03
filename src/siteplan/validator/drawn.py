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
from siteplan.validator.shapes import mended, polygons_of, union_of_all

BUILT_WORDS = ("CABIN", "ROOM", "SUBSTATION")


def taken(shapes: list[Shape], label: str, flaws: list[str]) -> list[BaseGeometry]:
    """Each shape as geometry that can be measured. One that had to be mended (it crosses
    itself) is written down in `flaws`, named by `label`."""
    out = []
    for n, shape in enumerate(shapes, 1):
        geometry, flaw = mended(shape.to_shapely())
        if flaw:
            flaws.append(f"{label}{f', shape {n}' if len(shapes) > 1 else ''}: {flaw}")
        out.append(geometry)
    return out


def geometry_of(shapes: list[Shape], label: str, flaws: list[str]) -> BaseGeometry:
    return union_of_all(taken(shapes, label, flaws))


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
    flaws: tuple[str, ...]  # shapes that crossed themselves and were mended to be measured

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
    flaws: list[str] = []

    def one(shape: Shape, label: str) -> BaseGeometry:
        return union_of_all(taken([shape], label, flaws))

    def pieces(shapes: list[Shape], label: str) -> tuple[Polygon, ...]:
        return tuple(p for g in taken(shapes, label, flaws) for p in polygons_of(g))

    return Drawn(
        roads=tuple(DrawnRoad(r.id, r.kind, r.declared_width_m,
                              geometry_of(r.shapes, f"road {r.id}", flaws), tuple(r.tags))
                    for r in circulation.roads),
        gates=tuple(Gate(one(g.shape, "a gate"), g.width_m) for g in circulation.gates),
        fire_hardstanding=geometry_of(circulation.fire_hardstanding, "fire hardstanding", flaws),
        club=one(program.club_house.shape, "the club house") if program.club_house else Polygon(),
        club_floors=program.club_house.floors if program.club_house else 0,
        amenities=tuple(DrawnAmenity(a.name, one(a.shape, f"amenity {a.name}"), a.setting)
                        for a in program.amenities),
        ramps=pieces(program.ramps, "a ramp"),
        bays=pieces(program.bays, "a parking bay"),
        open_space=pieces(program.open_space, "open space"),
        green_strip=geometry_of(program.green_strip, "the green strip", flaws),
        cellar_drawn=cellars is not None,
        cellar_levels=cellars.levels if cellars else 0,
        cellar_outline=geometry_of(cellars.outline, "the cellar outline", flaws) if cellars
        else Polygon(),
        cellar_setback_claimed_m=cellars.setback_m if cellars else None,
        flaws=tuple(flaws))
