"""CandidateLayout: one complete proposal for a site, as the generator made it.

A tower is a prototype placed: mirrored (x -> -x) if asked, turned by rotation_deg about the
prototype's origin (anticlockwise), then moved to (x, y). Its height is not stored: whoever needs
it derives it from its floors, the stilt and the floor heights (the prototype's, else the
brief's) under the reading of the rule height in force. The prototypes used travel with the
candidate, so a validator needs no prototype code. Everything the generator believes about its
own legality is a claim (`generator_claims`); an independent validator never relies on it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, PositiveInt, model_validator
from shapely import affinity
from shapely.geometry import Polygon

from siteplan.contracts.accounting import PartitionLedger, RuleLayers
from siteplan.contracts.common import (
    Contract,
    FacilityUse,
    Finding,
    Part,
    Shape,
    Side,
    Surface,
)
from siteplan.contracts.design_brief import AmenitySetting
from siteplan.contracts.prototype import TowerPrototype


class RoadKind(StrEnum):
    APPROACH = "APPROACH"  # the main internal approach road, from the gate
    LOOP = "LOOP"
    INTERNAL = "INTERNAL"
    CUL_DE_SAC = "CUL_DE_SAC"
    DRIVEWAY = "DRIVEWAY"  # never counted as an internal road
    PERIMETER_LANE = "PERIMETER_LANE"
    PATHWAY = "PATHWAY"  # rule 8(l): access for a block up to 12 m, branching from the roads


class RoadPiece(Part):
    id: str
    kind: RoadKind
    shapes: list[Shape] = Field(min_length=1)
    declared_width_m: float = Field(gt=0)
    tags: list[str] = []  # other functions of the same pavement, e.g. FIRE_ACCESS


class Gate(Part):
    shape: Shape
    side: Side | None = None
    width_m: float = Field(gt=0)
    note: str = ""


class Circulation(Part):
    roads: list[RoadPiece] = []
    gates: list[Gate] = []
    fire_hardstanding: list[Shape] = []  # motorable clear ground that is not a road


class ClubHouse(Part):
    shape: Shape
    floors: PositiveInt


class PlacedAmenity(Part):
    """A facility as placed. Its use and surface are what the generator says it placed (from the
    firm's library, never from the name); None when nobody stated them. A validator holds them
    against the brief's request of the same name and derives what counts as open space itself."""

    name: str
    shape: Shape
    setting: AmenitySetting = AmenitySetting.OUTDOOR
    use: FacilityUse | None = None
    surface: Surface | None = None


class Cellars(Part):
    levels: int = Field(ge=0)
    outline: list[Shape] = []
    setback_m: float | None = None


class SiteProgram(Part):
    open_space: list[Shape] = []
    green_strip: list[Shape] = []
    club_house: ClubHouse | None = None
    amenities: list[PlacedAmenity] = []
    amenities_missed: list[str] = []
    ramps: list[Shape] = []
    cellars: Cellars | None = None
    bays: list[Shape] = []


class PlacedTower(Part):
    name: str
    prototype_id: str
    x: float
    y: float
    rotation_deg: float = 0.0
    mirrored: bool = False
    floors_above_stilt: PositiveInt
    has_stilt: bool = True
    footprint: Shape  # the generator's world footprint; a validator recomputes it

    def world(self, local: Polygon) -> Polygon:
        """A shape in the prototype's frame, placed as this tower is."""
        shape = affinity.scale(local, xfact=-1, origin=(0, 0)) if self.mirrored else local
        shape = affinity.rotate(shape, self.rotation_deg, origin=(0, 0))
        return affinity.translate(shape, self.x, self.y)


class Metrics(Part):
    """The generator's own numbers, for reports; a validator recomputes what it checks."""

    total_flats: int = Field(ge=0)
    flats_by_type: dict[str, int] = {}
    saleable_sqft: float = Field(ge=0)
    tower_floor_sqft: float = Field(ge=0)
    flats_own_sqft: float = Field(ge=0)
    common_core_sqft: float = Field(ge=0)
    built_up_sqft: float = Field(ge=0)
    open_space_sqm: float = Field(ge=0)
    open_space_share_pct: float = Field(ge=0)
    mix_error: float = Field(ge=0)
    extra: dict[str, Any] = {}


class CandidateLayout(Contract):
    candidate_id: str
    site_ref: str
    rules_ref: str
    brief_ref: str
    envelope_ref: str | None = None
    strategy: str = ""
    seed: int | None = None
    interpretation_basis: dict[str, str] = {}  # interpretation id -> the reading it was made for
    prototypes_used: list[TowerPrototype] = []
    towers: list[PlacedTower] = []
    circulation: Circulation = Circulation()
    program: SiteProgram = SiteProgram()
    partition: PartitionLedger | None = None
    rule_layers: RuleLayers | None = None
    metrics: Metrics | None = None
    generator_claims: list[Finding] = []
    scores: dict[str, float] = {}
    pareto_tag: str | None = None
    caveats: list[str] = []

    @model_validator(mode="after")
    def _references_resolve(self) -> CandidateLayout:
        ids = [p.id for p in self.prototypes_used]
        if len(ids) != len(set(ids)):
            raise ValueError("prototype ids must be unique")
        missing = sorted({t.prototype_id for t in self.towers} - set(ids))
        if missing:
            raise ValueError(f"towers use prototypes not carried with the candidate: {missing}")
        names = [t.name for t in self.towers]
        if len(names) != len(set(names)):
            raise ValueError("tower names must be unique")
        return self

    def prototype(self, prototype_id: str) -> TowerPrototype:
        return next(p for p in self.prototypes_used if p.id == prototype_id)

    def placed_footprint(self, tower: PlacedTower) -> Polygon:
        """The footprint as its prototype and placement make it (not the generator's copy)."""
        return tower.world(self.prototype(tower.prototype_id).footprint.to_shapely())
