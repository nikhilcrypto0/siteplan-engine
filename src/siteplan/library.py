"""The flat library: the firm's standard flats that towers are assembled from.

A tower is a double-loaded slab: flats on both sides of a corridor, with lift/stair cores
spanning the full depth. v0 assumes every flat in a library has the same depth, which is
how the studied site plan is drawn (flats line up along straight corridors).

Until the firm's own DWG blocks arrive, only examples/flat_library.example.json exists,
and its sizes are illustrative, not the firm's.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator


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


class FlatLibrary(BaseModel):
    note: str = ""
    flats: list[FlatType] = Field(min_length=1)
    core_width_m: PositiveFloat = Field(description="Lift + stair core, spans the full depth")
    corridor_width_m: PositiveFloat = 2.13  # 7 ft, as on the studied plan
    flats_per_core_per_side: PositiveInt = 4

    @model_validator(mode="after")
    def _one_depth(self) -> FlatLibrary:
        depths = {round(f.depth_m, 2) for f in self.flats}
        if len(depths) > 1:
            raise ValueError(f"v0 needs all flats the same depth; got {sorted(depths)} m")
        return self

    @property
    def tower_depth_m(self) -> float:
        return 2 * self.flats[0].depth_m + self.corridor_width_m

    @property
    def categories(self) -> set[str]:
        return {f.bhk for f in self.flats}
