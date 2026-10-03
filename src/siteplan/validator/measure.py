"""The towers as the candidate's own geometry makes them: footprint, cores, heights, Table IV row.

A tower's footprint is its prototype's, placed as `PlacedTower.world` says; the footprint the
generator states is only compared with it. Heights come from the floors, the stilt and the floor
heights (the prototype's, else the brief's firm standards). Whether the stilt counts toward the
height that picks the Table IV row is an open reading, so a tower has one rule height per
reading and one physical height, the one NBC measures.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon

from siteplan.contracts.candidate import CandidateLayout, PlacedTower
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.prototype import TowerPrototype
from siteplan.contracts.resolved_rules import Band, BandKind, ResolvedRules
from siteplan.validator.readings import COUNTED, EACH_OWN, NOT_COUNTED, TALLER_GOVERNS

TOL_M = 1e-6  # a length this close to the rule's is the rule's


@dataclass(frozen=True)
class TowerGeometry:
    name: str
    footprint: Polygon  # recomputed from the prototype and the placement
    stated: Polygon  # what the generator says it is
    cores: tuple[Polygon, ...]  # the prototype's lift and stair zones, placed
    floors: int  # above the stilt
    has_stilt: bool
    stilt_height_m: float
    floor_height_m: float
    prototype: TowerPrototype
    placed: PlacedTower

    @property
    def physical_height_m(self) -> float:
        """Ground to the top, the stilt included: what NBC's fire rules measure."""
        return (self.stilt_height_m if self.has_stilt else 0.0) + self.floors * self.floor_height_m

    def rule_height_m(self, reading: str) -> float | None:
        """The height that picks the Table IV row and the high-rise class, under a reading of
        whether the stilt counts; None for a reading this validator cannot evaluate."""
        if reading == COUNTED:
            return self.physical_height_m
        if reading == NOT_COUNTED:
            return self.floors * self.floor_height_m
        return None

    @property
    def built_up_sqm(self) -> float:
        """Every floor above the stilt, wall to wall (what Table V and rule 15 measure)."""
        return self.footprint.area * self.floors

    @property
    def units(self) -> dict[str, int]:
        """Flats by category, counted from the prototype's modules, a floor at a time."""
        out: dict[str, int] = {}
        for module in self.prototype.modules:
            out[module.category] = out.get(module.category, 0) + self.floors
        return out


def tower_geometries(candidate: CandidateLayout, brief: DesignBrief) -> tuple[TowerGeometry, ...]:
    standards = brief.firm_standards
    towers = []
    for placed in candidate.towers:
        prototype = candidate.prototype(placed.prototype_id)
        towers.append(TowerGeometry(
            name=placed.name, footprint=candidate.placed_footprint(placed),
            stated=placed.footprint.to_shapely(),
            cores=tuple(placed.world(z.shape.to_shapely()) for z in prototype.core_zones),
            floors=placed.floors_above_stilt, has_stilt=placed.has_stilt,
            stilt_height_m=prototype.heights.stilt_height_m or standards.stilt_height_m.value,
            floor_height_m=prototype.heights.floor_to_floor_m or standards.floor_to_floor_m.value,
            prototype=prototype, placed=placed))
    return tuple(towers)


@dataclass(frozen=True)
class HeightClass:
    """Where a rule height falls in the resolved bands."""

    height_m: float
    high_rise: bool
    band: Band | None  # the band whose values apply; None when none can be used
    state: str  # 'ok', 'unmodelled' (Table III or beyond the bands) or 'seam'

    @property
    def label(self) -> str:
        if self.state == "seam":
            return f"exactly {self.height_m:g} m, the high-rise threshold"
        if self.band is None:
            return "beyond the bands in the rules"
        kind = "" if self.band.kind is BandKind.HIGH_RISE else "non-high-rise "
        return f"{kind}{self.band.above_m:g}-{self.band.up_to_m:g} m"

    @property
    def setback_m(self) -> float | None:
        return self.band.setback_m if self.state == "ok" and self.band else None

    @property
    def gap_m(self) -> float | None:
        if self.state != "ok" or self.band is None:
            return None
        return self.band.gap_m if self.band.gap_m is not None else self.band.setback_m

    @property
    def min_road_m(self) -> float | None:
        return self.band.min_road_m if self.state == "ok" and self.band else None


def classify(rules: ResolvedRules, height_m: float) -> HeightClass:
    """The band a rule height falls in. A building is high-rise from `high_rise_from_m` up;
    exactly at that height the resolved bands have no Table IV row for it (the row below ends
    there and the row above starts there), which is a seam, never a guess."""
    high_rise = height_m >= rules.height.high_rise_from_m.value - TOL_M
    band = next((b for b in rules.height.bands
                 if b.above_m + TOL_M < height_m <= b.up_to_m + TOL_M), None)
    if band is None:
        return HeightClass(height_m, high_rise, None, "unmodelled")
    if high_rise and band.kind is not BandKind.HIGH_RISE:
        return HeightClass(height_m, high_rise, None, "seam")
    if not band.modelled or band.setback_m is None:
        return HeightClass(height_m, high_rise, band, "unmodelled")
    return HeightClass(height_m, high_rise, band, "ok")


def setback_of(net: Polygon, footprint: Polygon) -> float:
    """How far a footprint stands from the net plot's boundary; nothing when any of it lies
    outside the plot."""
    if not net.contains(footprint):
        return 0.0
    return float(net.boundary.distance(footprint))


def required_gap(a: HeightClass, b: HeightClass, a_height_m: float, b_height_m: float,
                 spacing: str) -> tuple[float | None, str]:
    """The gap two blocks need under a reading of mixed-height spacing, and 'ok'; or None and
    why there is none: 'seam', 'unmodelled' (a block's own gap is not in the rules) or 'unknown'
    (a reading this validator cannot evaluate).

    taller_governs: the taller block's Table IV gap. each_own: each block keeps its own gap on
    its own half of the space between them, so the mean of the two. Blocks of the same height
    need the same gap either way."""
    if "seam" in (a.state, b.state):
        return None, "seam"
    if spacing == TALLER_GOVERNS:
        taller = a if a_height_m >= b_height_m else b
        return (taller.gap_m, "ok") if taller.gap_m is not None else (None, "unmodelled")
    if spacing == EACH_OWN:
        if a.gap_m is None or b.gap_m is None:
            return None, "unmodelled"
        return (a.gap_m + b.gap_m) / 2, "ok"
    return None, "unknown"
