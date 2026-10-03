"""TowerPrototype: a reusable building, one typical floor of it, in its own frame.

The footprint is centred on the origin with its long axis along x. A prototype carries no legal
value and no floor count: how many floors a placed tower has is the optimizer's choice, within
what the law allows. Floor heights are optional: None means the brief's firm standard applies,
and a prototype sets its own only when its design needs it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, PositiveInt, model_validator

from siteplan.contracts.common import Contract, Part, Shape, SourceKind

AREA_TOLERANCE = 0.01  # share by which stated per-floor areas may differ from the drawn ones
SALEABLE_TOLERANCE_SQFT = 0.5


class PrototypeFamily(StrEnum):
    SINGLE_CORE_SMALL = "SINGLE_CORE_SMALL"
    SINGLE_CORE = "SINGLE_CORE"
    TWO_CORE_MEDIUM = "TWO_CORE_MEDIUM"
    TWO_CORE_LARGE = "TWO_CORE_LARGE"
    LEGACY_RECTANGLE = "LEGACY_RECTANGLE"  # a tower as the prototype generator laid it


class FlatModule(Part):
    id: str
    type_id: str  # the flat type in the firm's library
    category: str  # unit-mix category, e.g. '2BHK'
    shape: Shape
    saleable_sqft: float = Field(gt=0)
    carpet_sqft: float | None = Field(None, gt=0)
    built_up_sqft: float | None = Field(None, gt=0)


class CoreZone(Part):
    shape: Shape
    lifts: int = Field(0, ge=0)  # placeholder counts until egress is modelled
    stairs: int = Field(0, ge=0)


class PerFloor(Part):
    flats: int = Field(ge=0)
    flats_by_type: dict[str, int]
    gross_floor_sqm: float = Field(gt=0)  # the footprint, wall to wall
    flats_own_sqm: float = Field(ge=0)
    common_core_sqm: float = Field(ge=0)  # corridors, lifts, stairs
    saleable_sqft: float = Field(ge=0)  # from the modules only


class PrototypeHeights(Part):
    stilt_height_m: float | None = Field(None, gt=0)
    floor_to_floor_m: float | None = Field(None, gt=0)


class Stretch(Part):
    """A block that can be built longer or shorter by whole modules."""

    module_pitch_m: float = Field(gt=0)
    min_modules: PositiveInt
    max_modules: PositiveInt


class TowerPrototype(Contract):
    id: str
    family: PrototypeFamily
    source_kind: SourceKind
    source: str = ""
    footprint: Shape
    length_m: float = Field(gt=0)
    depth_m: float = Field(gt=0)
    cores: int = Field(ge=0)
    modules: list[FlatModule] = Field(min_length=1)
    core_zones: list[CoreZone] = []
    corridor: list[Shape] = []
    per_floor: PerFloor
    heights: PrototypeHeights = PrototypeHeights()
    stretch: Stretch | None = None

    @model_validator(mode="after")
    def _per_floor_agrees(self) -> TowerPrototype:
        p = self.per_floor
        by_type: dict[str, int] = {}
        for module in self.modules:
            by_type[module.category] = by_type.get(module.category, 0) + 1
        problems = []
        if p.flats != len(self.modules) or p.flats_by_type != by_type:
            problems.append(f"per_floor counts {p.flats} {p.flats_by_type}, modules {by_type}")
        if self.cores != len(self.core_zones):
            problems.append(f"{self.cores} cores but {len(self.core_zones)} core zones")
        own = sum(m.shape.area_sqm for m in self.modules)
        gross = self.footprint.area_sqm
        for name, stated, drawn in (("flats_own_sqm", p.flats_own_sqm, own),
                                    ("gross_floor_sqm", p.gross_floor_sqm, gross),
                                    ("common_core_sqm", p.common_core_sqm, gross - own)):
            if abs(stated - drawn) > AREA_TOLERANCE * max(drawn, 1.0):
                problems.append(f"{name} {stated:.2f} is not the drawn {drawn:.2f}")
        saleable = sum(m.saleable_sqft for m in self.modules)
        if abs(p.saleable_sqft - saleable) > SALEABLE_TOLERANCE_SQFT * max(1, len(self.modules)):
            problems.append(f"saleable_sqft {p.saleable_sqft:.1f} is not the modules' "
                            f"{saleable:.1f}")
        if problems:
            raise ValueError(f"prototype {self.id}: " + "; ".join(problems))
        return self
