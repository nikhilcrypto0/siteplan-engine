"""DesignBrief: what the architect and the firm want built.

It holds no site fact and no legal value. A firm standard may be stricter than the law (fewer
utilities in a cellar than rule 13(c)(xi) allows) but never restates it. Floors here are intent
("Stilt + 8", or the most the law allows); what the law allows is ResolvedRules', in metres, and
the optimizer turns metres into floors with the heights given here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, PositiveInt, model_validator

from siteplan import rules
from siteplan.contracts.common import Contract, Part, Sourced

MIX_SUM_TOLERANCE = 0.01


class UnitsMode(StrEnum):
    MAXIMISE = "MAXIMISE"
    TARGET = "TARGET"
    RANGE = "RANGE"


class HeightMode(StrEnum):
    MAX_LEGAL = "MAX_LEGAL"  # whatever the law allows, tower by tower; never every tower at it
    FIXED = "FIXED"
    RANGE = "RANGE"


class ClubSize(StrEnum):
    LEGAL_MINIMUM = "LEGAL_MINIMUM"
    FIRM_STANDARD = "FIRM_STANDARD"
    STATED = "STATED"


class AmenityPriority(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    OPTIONAL = "OPTIONAL"


class AmenitySetting(StrEnum):
    CLUB_HOUSE = "CLUB_HOUSE"
    OUTDOOR = "OUTDOOR"
    EITHER = "EITHER"


class ParetoPoint(StrEnum):
    MAX_YIELD = "MAX_YIELD"
    BALANCED = "BALANCED"
    CONVENTIONAL_OPEN_SPACE = "CONVENTIONAL_OPEN_SPACE"


class UnitTarget(Part):
    mode: UnitsMode = UnitsMode.MAXIMISE
    target: PositiveInt | None = None
    minimum: PositiveInt | None = None
    maximum: PositiveInt | None = None

    @model_validator(mode="after")
    def _says_enough(self) -> UnitTarget:
        if self.mode is UnitsMode.TARGET and self.target is None:
            raise ValueError("a TARGET needs target")
        if self.mode is UnitsMode.RANGE and (self.minimum is None or self.maximum is None):
            raise ValueError("a RANGE needs minimum and maximum")
        return self


class ClubHouseRequest(Part):
    wanted: Sourced[bool]
    size: ClubSize = ClubSize.LEGAL_MINIMUM
    sqm: float | None = Field(None, gt=0)  # built-up area, when size is STATED
    floors: PositiveInt | None = None

    @model_validator(mode="after")
    def _stated_size(self) -> ClubHouseRequest:
        if self.size is ClubSize.STATED and self.sqm is None:
            raise ValueError("a STATED club house size needs sqm")
        return self


class AmenityRequest(Part):
    name: str
    priority: AmenityPriority = AmenityPriority.PREFERRED
    setting: AmenitySetting = AmenitySetting.EITHER
    footprint_m: tuple[float, float] | None = None  # width, depth
    surface: Literal["SOFT", "HARD"] | None = None  # whether it qualifies is the law's, not ours


class ParkingPreferences(Part):
    max_cellars: Sourced[int]
    surface_bays_allowed: bool = True


class Program(Part):
    unit_mix: Sourced[dict[str, float]]
    mix_tolerance: float = Field(0.05, ge=0, le=1)
    units: UnitTarget = UnitTarget()
    flat_library: Sourced[str] | None = None  # the firm's library file
    allowed_types: list[str] = []
    club_house: ClubHouseRequest
    amenity_library: Sourced[str] | None = None
    amenities: list[AmenityRequest] = []
    parking: ParkingPreferences

    @model_validator(mode="after")
    def _mix_adds_up(self) -> Program:
        shares = self.unit_mix.value
        if not shares or any(v < 0 for v in shares.values()):
            raise ValueError("unit_mix needs at least one category and no negative shares")
        if abs(sum(shares.values()) - 1) > MIX_SUM_TOLERANCE:
            raise ValueError(f"unit_mix shares must add up to 1 (got {sum(shares.values()):.3f})")
        return self


class HeightIntent(Part):
    notation: Sourced[str]  # what "Stilt + N" means for this project, and who said so
    mode: HeightMode = HeightMode.MAX_LEGAL
    floors_above_stilt: PositiveInt | None = None  # FIXED
    floors_range: tuple[PositiveInt, PositiveInt] | None = None  # RANGE, lowest and highest
    has_stilt: bool = True
    mixed_heights_allowed: bool = True
    min_floors_above_stilt: PositiveInt | None = None

    @model_validator(mode="after")
    def _says_enough(self) -> HeightIntent:
        if self.mode is HeightMode.FIXED and self.floors_above_stilt is None:
            raise ValueError("a FIXED height needs floors_above_stilt")
        if self.mode is HeightMode.RANGE and self.floors_range is None:
            raise ValueError("a RANGE of heights needs floors_range")
        return self


class FirmStandards(Part):
    stilt_height_m: Sourced[float]
    floor_to_floor_m: Sourced[float]
    cellar_floor_height_m: Sourced[float]
    common_area_loading_pct: Sourced[float]
    cellar_utilities_share: Sourced[float]
    min_flats_per_side: Sourced[int]
    max_tower_length_m: Sourced[float] | None = None
    max_cores_per_tower: Sourced[int] | None = None
    preferred_prototype_families: list[str] = []
    bay_size_m: Sourced[tuple[float, float]] | None = None  # only when the firm sets its own
    aisle_m: Sourced[float] | None = None

    @model_validator(mode="after")
    def _within_the_law(self) -> FirmStandards:
        if not 0 <= self.cellar_utilities_share.value <= rules.CELLAR_UTILITIES_MAX_FRACTION:
            raise ValueError("a firm may keep less of a cellar for utilities than rule "
                             "13(c)(xi) allows, never more")
        return self


class SoftPreference(Part):
    kind: str  # e.g. 'keep_away_from_road'
    params: dict[str, Any] = {}
    weight: float = Field(1.0, ge=0)


class Objectives(Part):
    pareto: list[ParetoPoint] = list(ParetoPoint)
    options: PositiveInt = 3
    priorities: dict[str, float] = {}  # weights over saleable area, units, open space, mix fit
    soft_preferences: list[SoftPreference] = []
    search_budget_s: float | None = Field(None, gt=0)


class DesignBrief(Contract):
    brief_id: str
    project_name: str
    words: str = ""  # the architect's own words, verbatim
    program: Program
    height_intent: HeightIntent
    firm_standards: FirmStandards
    objectives: Objectives = Objectives()
