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
from siteplan.contracts.common import Provenance
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.prototype import TowerPrototype
from siteplan.contracts.resolved_rules import Band, BandKind, ResolvedRules
from siteplan.validator.readings import COUNTED, EACH_OWN, NOT_COUNTED, TALLER_GOVERNS
from siteplan.validator.shapes import polygon_of, snapped

TOL_M = 1e-6  # a length this close to the rule's is the rule's

# Rule 5(xiii), read on page 11 of fixtures/rules/go168-2012.pdf (the 2012 text): between two
# blocks below the high-rise height the order itself says whose figure it is, so the open reading
# of mixed-height spacing (a Table IV question, rule 7(a)(xii)) does not reach them.
LOW_GAP_RULE = ("G.O.168 rule 5(xiii), p.11: \"The space between 2 blocks shall not be less than "
                "the side setback of the tallest block as mentioned in Table - III\"")
LOW_GAP_CLAUSE = ("G.O.168 rule 5(xiii) (the space between 2 blocks: the tallest block's side "
                  "setback)")

HIGH_RISE_FRONT_NOTE = ("The front of a high-rise keeps the Table IV figure too, measured on the "
                        "net plot.")
# INTERIM (contracts 1.2): a band carries one setback, all round. Table III gives the Building Line
# at the front apart from the setback on the other sides, which ResolvedRules cannot say yet.
ALL_ROUND_NOTE = ("Held to the band's all-round figure, measured on the net plot. Table III's "
                  "Building Line at the front is a separate figure that ResolvedRules does not "
                  "carry apart from it, so the front is not judged on its own.")
UNCONFIRMED_NOTE = ("The rules mark this band UNVERIFIED: its values settle nothing either way.")


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
    flaws: tuple[str, ...] = ()  # shapes that crossed themselves and were mended to be measured

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
        flaws: list[str] = []

        def sound(shape, label: str, flaws=flaws, name=placed.name):
            geometry, flaw = polygon_of(shape)
            if flaw:
                flaws.append(f"{label} of {name}: {flaw}")
            return geometry

        def block(shape, label: str, sound=sound):
            """A building as one polygon: a mended outline that falls in two is judged on the
            ground round both (a building held to more ground can only be held to more)."""
            geometry = sound(shape, label)
            if isinstance(geometry, Polygon):
                return geometry
            hull = geometry.convex_hull
            return hull if isinstance(hull, Polygon) else Polygon()

        towers.append(TowerGeometry(
            name=placed.name,
            footprint=snapped(placed.world(
                block(prototype.footprint, "its prototype's footprint"))),
            stated=sound(placed.footprint, "the footprint it states"),
            cores=tuple(snapped(placed.world(block(z.shape, "a core zone")))
                        for z in prototype.core_zones),
            floors=placed.floors_above_stilt, has_stilt=placed.has_stilt,
            stilt_height_m=prototype.heights.stilt_height_m or standards.stilt_height_m.value,
            floor_height_m=prototype.heights.floor_to_floor_m or standards.floor_to_floor_m.value,
            prototype=prototype, placed=placed, flaws=tuple(flaws)))
    return tuple(towers)


@dataclass(frozen=True)
class HeightClass:
    """Where a rule height falls in the resolved bands: the one band the rules give it
    (`HeightRules.band_for`, the same lookup the optimizer makes). A building is high-rise from
    `high_rise_from_m` up; a block of exactly that height has its own band (Table IV's first
    row). A band the rules do not model (Table III, below it) leaves the height unjudged.
    """

    height_m: float
    high_rise: bool
    band: Band | None  # the band whose values apply; None above the last band
    state: str  # 'ok', or 'unmodelled' (Table III, or beyond the bands)

    @property
    def settled(self) -> bool:
        return self.state == "ok"

    @property
    def confirmed(self) -> bool:
        """Whether the rules stand behind the band's values. A band they mark UNVERIFIED settles
        nothing either way, as a height limit on unconfirmed inputs does
        (`HeightLimit.evaluate`): a result on it is UNVERIFIED, never PASS or FAIL."""
        return self.band is None or self.band.status is not Provenance.UNVERIFIED

    @property
    def table(self) -> str:
        """The clause of the band's own table: Table IV above the high-rise height, Table III
        (rule 5) below it; empty beyond the bands."""
        return self.band.clause if self.band is not None else ""

    @property
    def setback_note(self) -> str:
        """What a check of this band's setback says about the front.

        INTERIM (contracts 1.2): a band carries one setback, all round, so the front of a block
        below the high-rise height is not judged apart from its other sides. This note and
        `setback_m` are the one place that changes when a band carries the Building Line."""
        return HIGH_RISE_FRONT_NOTE if self.high_rise else ALL_ROUND_NOTE

    @property
    def label(self) -> str:
        if self.band is None:
            return "beyond the bands in the rules"
        kind = "" if self.band.kind is BandKind.HIGH_RISE else "non-high-rise "
        if self.band.above_m == self.band.up_to_m:
            return f"{kind}exactly {self.band.above_m:g} m"
        return f"{kind}{self.band.above_m:g}-{self.band.up_to_m:g} m"

    @property
    def _usable(self) -> Band | None:
        return self.band if self.state == "ok" else None

    @property
    def setback_m(self) -> float | None:
        return self._usable.setback_m if self._usable else None

    @property
    def gap_m(self) -> float | None:
        band = self._usable
        if band is None:
            return None
        return band.gap_m if band.gap_m is not None else band.setback_m

    @property
    def min_road_m(self) -> float | None:
        return self._usable.min_road_m if self._usable else None


def classify(rules: ResolvedRules, height_m: float) -> HeightClass:
    high_rise = height_m >= rules.height.high_rise_from_m.value - TOL_M
    band = rules.height.band_for(height_m)
    if band is None or not band.modelled or band.setback_m is None:
        return HeightClass(height_m, high_rise, band, "unmodelled")
    return HeightClass(height_m, high_rise, band, "ok")


def setback_of(net: Polygon, footprint: Polygon) -> float:
    """How far a footprint stands from the net plot's boundary; nothing when any of it lies
    outside the plot."""
    if not net.contains(footprint):
        return 0.0
    return float(net.boundary.distance(footprint))


def gap_sources(a: HeightClass, b: HeightClass, a_height_m: float, b_height_m: float,
                spacing: str) -> tuple[HeightClass, ...] | None:
    """The blocks whose own gap figure decides what two blocks need between them under a reading
    of mixed-height spacing; None for a reading this validator cannot evaluate.

    taller_governs: the taller block's, whatever the shorter block is. each_own: each block keeps
    its own gap on its own half of the space between them, so both. Blocks of the same height
    need the same gap either way. Two blocks below the high-rise height are not an open question:
    rule 5(xiii) gives the tallest block's (LOW_GAP_RULE), whatever the reading."""
    taller = a if a_height_m >= b_height_m else b
    if not (a.high_rise or b.high_rise) or spacing == TALLER_GOVERNS:
        return (taller,)
    if spacing == EACH_OWN:
        return (a, b)
    return None


def required_gap(a: HeightClass, b: HeightClass, a_height_m: float, b_height_m: float,
                 spacing: str) -> tuple[float | None, str]:
    """The gap two blocks need under a reading of mixed-height spacing: 'ok', or None and why
    there is none: 'unmodelled' (a block's own gap is not in the rules) or 'unknown' (a reading
    this validator cannot evaluate). It is the mean of the figures `gap_sources` names."""
    sources = gap_sources(a, b, a_height_m, b_height_m, spacing)
    if sources is None:
        return None, "unknown"
    gaps = [c.gap_m for c in sources]
    if any(g is None for g in gaps):
        return None, "unmodelled"
    return sum(gaps) / len(gaps), "ok"
