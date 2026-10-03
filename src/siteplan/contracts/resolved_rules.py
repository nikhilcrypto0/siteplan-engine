"""ResolvedRules: what the law asks of one site, in metres and square metres.

Every value carries its clause, its basis (law, firm, engine, open reading, site) and its status.
Heights are limits in metres on a named measure (the Table IV height, the physical height NBC
measures, height above sea level); turning a height into floors needs the brief's floor heights,
so no floor count appears here (tests/test_contracts.py enforces it). Where the text leaves a
question open, the question is an Interpretation with its readings; `selected` is one reading,
or ALL when every consumer must evaluate every reading and a result that holds under only some
of them is UNVERIFIED.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import Field, model_validator

from siteplan.contracts.common import Basis, Contract, Part, Provenance

T = TypeVar("T")
ALL = "ALL"  # evaluate every reading of an interpretation

# The open readings every ResolvedRules must carry; consumers look them up by these ids.
STILT_IN_RULE_HEIGHT = "stilt_in_rule_height"
OPEN_SPACE_BASIS = "open_space_basis"
CIRCULATION_IN_SETBACK = "circulation_in_setback"
FIRE_TURNING_RADIUS = "fire_turning_radius"
APPROACH_WIDTH = "approach_width"
MIXED_HEIGHT_SPACING = "mixed_height_spacing"
VISITOR_PARKING = "visitor_parking"
AMENITY_SHARE = "amenity_share"
REQUIRED_INTERPRETATIONS = (STILT_IN_RULE_HEIGHT, OPEN_SPACE_BASIS, CIRCULATION_IN_SETBACK,
                            FIRE_TURNING_RADIUS, APPROACH_WIDTH, MIXED_HEIGHT_SPACING,
                            VISITOR_PARKING, AMENITY_SHARE)


class RuleValue(Part, Generic[T]):
    value: T
    unit: str = ""
    clause: str
    basis: Basis = Basis.LEGAL_RULE
    status: Provenance = Provenance.VERIFIED  # VERIFIED: read from the order's own text
    note: str = ""


class OrderRead(StrEnum):
    TEXT = "TEXT"  # read from its text layer
    SCAN = "SCAN"  # read from rendered page images
    UNREAD = "UNREAD"


class OrderRef(Part):
    id: str  # e.g. 'G.O.Ms.No.168 of 2012'
    read: OrderRead
    note: str = ""


class Interpretation(Part):
    id: str
    question: str
    alternatives: dict[str, str] = Field(min_length=2)  # reading -> what it means
    selected: str  # one reading, or ALL
    basis: Basis = Basis.UNRESOLVED_INTERPRETATION
    status: Provenance = Provenance.UNVERIFIED
    sources: list[str] = []
    settles: str = ""  # the evidence that would settle it

    @model_validator(mode="after")
    def _selected_is_a_reading(self) -> Interpretation:
        if self.selected != ALL and self.selected not in self.alternatives:
            raise ValueError(f"{self.id}: selected '{self.selected}' is not one of its readings")
        return self

    def readings(self) -> list[str]:
        return list(self.alternatives) if self.selected == ALL else [self.selected]


class Category(Part):
    group_development: RuleValue[bool]  # rule 2(c): 4,000 m² and over
    amenities_from_units: RuleValue[int]
    above_5_acres: RuleValue[bool]


class TableVColumn(StrEnum):
    GHMC_OR_CURE = "GHMC_OR_CURE"
    ELSEWHERE = "ELSEWHERE"
    OPEN = "OPEN"  # whose rules apply is not established


class WhenOpen(StrEnum):
    STOP = "STOP"  # stop and ask
    CONSERVATIVE = "CONSERVATIVE"  # a labelled test mode: plan the stricter column


class JurisdictionRules(Part):
    table_v_column: TableVColumn
    when_open: WhenOpen = WhenOpen.STOP
    note: str = ""


class HeightMeasure(StrEnum):
    RULE_HEIGHT = "RULE_HEIGHT"  # the height that picks the Table IV row and the high-rise class
    PHYSICAL_HEIGHT = "PHYSICAL_HEIGHT"  # ground to the top, stilt included (NBC Part 3 2.10)
    AMSL = "AMSL"  # above mean sea level (airport and Air Force limits)


class BandKind(StrEnum):
    HIGH_RISE = "HIGH_RISE"
    NON_HIGH_RISE = "NON_HIGH_RISE"


class Band(Part):
    above_m: float = Field(ge=0)
    up_to_m: float = Field(gt=0)
    kind: BandKind
    modelled: bool = True  # False: the engine does not encode this band yet (Table III)
    min_road_m: float | None = None
    setback_m: float | None = None  # all round
    gap_m: float | None = None  # between two blocks
    clause: str
    status: Provenance = Provenance.VERIFIED


class HeightLimit(Part):
    measure: HeightMeasure
    max_m: float | None  # None: this limit cannot be evaluated yet (see status and reason)
    reason: str
    clause: str
    status: Provenance
    applies_if: str | None = None  # a condition on a site fact, e.g. the road ending at the plot


class HeightRules(Part):
    measures: dict[HeightMeasure, str]  # what each measure includes
    rule_height_interpretation: str = STILT_IN_RULE_HEIGHT
    high_rise_from_m: RuleValue[float]
    tdr_band_m: RuleValue[tuple[float, float]]
    tdr_plot_sqm: RuleValue[tuple[float, float]]
    bands: list[Band]
    limits: list[HeightLimit]


class SetbackRules(Part):
    measured_on: RuleValue[str]  # the net plot
    front: RuleValue[str]
    concessions: list[RuleValue[str]] = []  # each note says when it applies


class SpacingRules(Part):
    clause: str
    mixed_heights_interpretation: str = MIXED_HEIGHT_SPACING


class OpenSpaceRules(Part):
    share: RuleValue[float]
    basis_interpretation: str = OPEN_SPACE_BASIS
    requirement_sqm_by_reading: dict[str, float]  # the area asked under each denominator
    min_width_m: RuleValue[float]
    min_pocket_sqm: RuleValue[float]
    over_and_above_setbacks: RuleValue[bool]
    block_gaps_excluded: RuleValue[bool]
    buffer_may_count: RuleValue[bool]


class GreenStripRules(Part):
    width_m: RuleValue[float]
    where_setback_from_m: RuleValue[float]


class CirculationRules(Part):
    applies: RuleValue[bool]  # rule 8 governs a group development scheme
    approach_m: RuleValue[tuple[float, float]]
    approach_interpretation: str = APPROACH_WIDTH
    internal_road_m: RuleValue[float]
    cul_de_sac_width_m: RuleValue[float]
    cul_de_sac_length_m: RuleValue[tuple[float, float]]
    cul_de_sac_head_radius_m: RuleValue[float]
    pathway_max_block_height_m: RuleValue[float]
    driveway_min_m: RuleValue[float]
    driveway_is_road: RuleValue[bool]
    block_over_12m_on_road: RuleValue[bool]
    in_setback_interpretation: str = CIRCULATION_IN_SETBACK


class FireRules(Part):
    applies_from_m: RuleValue[float]  # the high-rise threshold, on the rule height
    clear_width_m: RuleValue[float]
    turning_radius_m: RuleValue[float]
    turning_interpretation: str = FIRE_TURNING_RADIUS
    entrance_width_m: RuleValue[float]
    entrance_clear_height_m: RuleValue[float]
    load_t: RuleValue[float]
    street_join_m: RuleValue[float]
    dead_end_max_physical_m: RuleValue[float]


class ParkingMeasurement(Part):
    """How parking is measured where no order says: the engine's own standard."""

    bay_m: tuple[float, float]
    aisle_m: float
    sqm_per_car: float
    basis: Basis = Basis.ENGINE_DESIGN_ASSUMPTION
    note: str = ""


class ParkingRules(Part):
    share_pct_by_column: dict[TableVColumn, float]
    share_pct: RuleValue[float] | None  # None while the column is OPEN and the run stops
    visitors_fraction: RuleValue[float]
    visitors_interpretation: str = VISITOR_PARKING
    cellar_setback_by_site_sqm: RuleValue[list[tuple[float | None, float]]]  # None: and above
    cellar_extra_setback_per_level_m: RuleValue[float]
    ramp_single_min_m: RuleValue[float]
    ramp_pair_min_m: RuleValue[float]
    ramp_gradient: RuleValue[float]
    ramp_in_setbacks: RuleValue[str]
    utilities_max_fraction: RuleValue[float]
    measurement: ParkingMeasurement


class AmenityRules(Part):
    share_of_built_up: RuleValue[float]
    share_interpretation: str = AMENITY_SHARE
    cap_sqft_2016: RuleValue[float]
    from_units: RuleValue[int]
    separate_block: RuleValue[str]
    large_project_share_of_site: RuleValue[float]
    large_project_from_acres: RuleValue[float]


class WaterRules(Part):
    buffer_m_by_class: RuleValue[dict[str, float]]


class ResolvedRules(Contract):
    site_ref: str
    rules_digest: str
    orders: list[OrderRef]
    category: Category
    jurisdiction: JurisdictionRules
    height: HeightRules
    setbacks: SetbackRules
    spacing: SpacingRules
    open_space: OpenSpaceRules
    green_strip: GreenStripRules
    circulation: CirculationRules
    fire: FireRules
    parking: ParkingRules
    amenities: AmenityRules
    water: WaterRules
    interpretations: list[Interpretation]

    @model_validator(mode="after")
    def _interpretations_complete(self) -> ResolvedRules:
        ids = [i.id for i in self.interpretations]
        if len(ids) != len(set(ids)):
            raise ValueError("interpretation ids must be unique")
        missing = [i for i in REQUIRED_INTERPRETATIONS if i not in ids]
        if missing:
            raise ValueError(f"missing interpretation(s): {missing}")
        basis = self.interpretation(OPEN_SPACE_BASIS)
        if set(self.open_space.requirement_sqm_by_reading) != set(basis.alternatives):
            raise ValueError("open_space.requirement_sqm_by_reading needs one area per reading "
                             f"of {OPEN_SPACE_BASIS}")
        return self

    def interpretation(self, interpretation_id: str) -> Interpretation:
        return next(i for i in self.interpretations if i.id == interpretation_id)

    def readings(self, interpretation_id: str) -> list[str]:
        return self.interpretation(interpretation_id).readings()
