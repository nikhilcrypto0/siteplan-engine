"""The flat library: the firm's standard flats that towers are assembled from.

A tower is a double-loaded slab: flats on both sides of a corridor, with lift/stair cores across
it. A flat's width x depth is its share of the typical floor, cores and corridor included
(AreaBasis.PLATE_SHARE, since 2026-10-12), unless the library says it is the flat alone; a core
is compact (`core_depth_m`) unless the library sets none, when it spans the whole depth. v0
assumes every flat in a library has the same depth, which is how the studied site plan is drawn
(flats line up along straight corridors). The legacy towers (towers.py) read neither switch.

Until the firm's own DWG blocks arrive, only examples/flat_library.example.json exists,
and its sizes are illustrative, not the firm's.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator

# The core's depth across the block when a library does not say: a compact core across the
# corridor (2026-10-12; a core spanning the whole 25.79 m depth took 193 m² for two lifts and a
# stair). 7.5 x 8 m leaves 44 m² beside a 2.13 m corridor, within the 36-56 m² built of the six
# cores measured on the firm's Suchitra typical floor (two lifts and a stair in 41 m²).
COMPACT_CORE_DEPTH_M = 8.0


class FlatType(BaseModel):
    name: str
    bhk: str = Field(description="Unit-mix category, e.g. '2BHK'")
    width_m: PositiveFloat = Field(description="Frontage along the corridor")
    depth_m: PositiveFloat
    saleable_sqft: PositiveFloat
    # Where the library knows them (a firm's own floor plan does; example sizes do not), so a
    # tower prototype's flat can carry all three areas, which are not interchangeable.
    carpet_sqft: PositiveFloat | None = None
    built_up_sqft: PositiveFloat | None = None


class AreaBasis(StrEnum):
    """What a flat's width x depth stands for in a library (2026-10-12)."""

    # The flat and its share of the corridors, lifts and stairs: the saleable area less the
    # loading, which in the firm's statement sits on the whole floor (474,912 sft of floor x 1.22
    # = its 579,392 saleable). Cores and corridor are laid out of the flats, not added to them.
    PLATE_SHARE = "PLATE_SHARE"
    # The flat alone: cores and corridor are added to the flats (the composer before 2026-10-12).
    FLAT_ONLY = "FLAT_ONLY"


class FlatLibrary(BaseModel):
    note: str = ""
    flats: list[FlatType] = Field(min_length=1)
    core_width_m: PositiveFloat = Field(description="Lift + stair core, along the corridor")
    corridor_width_m: PositiveFloat = 2.13  # 7 ft, as on the studied plan
    flats_per_core_per_side: PositiveInt = 4
    area_basis: AreaBasis = AreaBasis.PLATE_SHARE
    core_depth_m: PositiveFloat | None = Field(
        COMPACT_CORE_DEPTH_M, description="The core across the block, the corridor included; "
        "None spans the whole depth, outer wall to outer wall")

    @model_validator(mode="after")
    def _one_depth(self) -> FlatLibrary:
        depths = {round(f.depth_m, 2) for f in self.flats}
        if len(depths) > 1:
            raise ValueError(f"v0 needs all flats the same depth; got {sorted(depths)} m")
        if self.core_depth_m is not None and self.core_depth_m <= self.corridor_width_m:
            raise ValueError(f"a core {self.core_depth_m:g} m deep does not reach across the "
                             f"{self.corridor_width_m:g} m corridor")
        return self

    @property
    def tower_depth_m(self) -> float:
        return 2 * self.flats[0].depth_m + self.corridor_width_m

    @property
    def categories(self) -> set[str]:
        return {f.bhk for f in self.flats}
