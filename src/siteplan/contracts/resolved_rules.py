"""ResolvedRules: what the law asks of one site, in metres and square metres.

Every value carries its clause, its basis (law, firm, engine, open reading, site) and its status.
Heights are limits in metres on a named measure (the Table IV height, the physical height NBC
measures, height above sea level); turning a height into floors needs the brief's floor heights,
so no floor count appears here (tests/test_contracts.py enforces it). Where the text leaves a
question open, the question is an Interpretation with its readings; `selected` is one reading,
or ALL when every consumer must evaluate every reading and a result that holds under only some
of them is UNVERIFIED.

The pieces of meaning live here, as methods, so the optimizer and the validator cannot read
them differently: how a height limit judges a height (`HeightLimit.evaluate`), which Table IV or
Table III row a block falls in (`HeightRules.band_for_block`, the stilt left out of Table III's
heights by rule 5(c)), whether a band's heights may stand here at all
(`HeightRules.band_permission`, and `permissible_non_high_rise` for the highest that may), and
whether a facility's ground is of a kind that counts as organised open space
(`OpenSpaceRules.qualifies`).
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import Field, model_validator

from siteplan.contracts.common import (
    Basis,
    Contract,
    FacilityUse,
    Part,
    Provenance,
    Status,
    Surface,
)

T = TypeVar("T")
ALL = "ALL"  # evaluate every reading of an interpretation
HEIGHT_TOL_M = 1e-6  # heights are sums of floor heights: 21.000000000000004 is 21 m

# The open readings every ResolvedRules must carry, and the names of their readings.
STILT_IN_RULE_HEIGHT = "stilt_in_rule_height"
OPEN_SPACE_BASIS = "open_space_basis"
CIRCULATION_IN_SETBACK = "circulation_in_setback"
FIRE_TURNING_RADIUS = "fire_turning_radius"
APPROACH_WIDTH = "approach_width"
MIXED_HEIGHT_SPACING = "mixed_height_spacing"
VISITOR_PARKING = "visitor_parking"
AMENITY_SHARE = "amenity_share"
TOT_LOT_SURFACE = "tot_lot_surface"
OPEN_SPACE_OTHER_USES = "open_space_other_uses"

COUNTED, NOT_COUNTED = "counted", "not_counted"
ALLOWED, NOT_ALLOWED = "allowed", "not_allowed"
TALLER_GOVERNS, EACH_OWN = "taller_governs", "each_own"
ANY_SURFACE, SOFT_ONLY = "any_surface", "soft_only"
SAME_KIND_ONLY, ANY_OPEN_RECREATION = "same_kind_only", "any_open_recreation"
GROSS_BEFORE_SURRENDER = "gross_before_surrender"
GROSS_AFTER_SURRENDER = "gross_after_surrender"
NET_AFTER_SURRENDER = "net_after_surrender"

READINGS: dict[str, tuple[str, ...]] = {
    STILT_IN_RULE_HEIGHT: (COUNTED, NOT_COUNTED),
    OPEN_SPACE_BASIS: (GROSS_BEFORE_SURRENDER, GROSS_AFTER_SURRENDER, NET_AFTER_SURRENDER),
    CIRCULATION_IN_SETBACK: (ALLOWED, NOT_ALLOWED),
    FIRE_TURNING_RADIUS: ("outer_edge", "centreline"),
    APPROACH_WIDTH: ("minimum", "authority_choice"),
    MIXED_HEIGHT_SPACING: (TALLER_GOVERNS, EACH_OWN),
    VISITOR_PARKING: ("at_ground", "anywhere"),
    AMENITY_SHARE: ("minimum_3_percent", "up_to_3_percent_or_cap"),
    TOT_LOT_SURFACE: (ANY_SURFACE, SOFT_ONLY),
    OPEN_SPACE_OTHER_USES: (SAME_KIND_ONLY, ANY_OPEN_RECREATION),
}
REQUIRED_INTERPRETATIONS = tuple(READINGS)


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


# --- Height ----------------------------------------------------------------------------------


class HeightMeasure(StrEnum):
    RULE_HEIGHT = "RULE_HEIGHT"  # the height that picks the Table IV row and the high-rise class
    PHYSICAL_HEIGHT = "PHYSICAL_HEIGHT"  # ground to the top, stilt included (NBC Part 3 2.10)
    AMSL = "AMSL"  # above mean sea level (airport and Air Force limits)
    # Ground to the top with the parking stilt left out: the height Table III is read on (rule
    # 5(c), "Stilt Floor meant for parking is excluded from the permissible height").
    HEIGHT_ABOVE_STILT = "HEIGHT_ABOVE_STILT"


class BandKind(StrEnum):
    HIGH_RISE = "HIGH_RISE"
    NON_HIGH_RISE = "NON_HIGH_RISE"


class Eligibility(StrEnum):
    ALLOWED = "ALLOWED"
    PROHIBITED = "PROHIBITED"
    UNVERIFIED = "UNVERIFIED"


ELIGIBILITY_RANK = {Eligibility.PROHIBITED: 0, Eligibility.UNVERIFIED: 1, Eligibility.ALLOWED: 2}
BAND_MEASURES = (HeightMeasure.RULE_HEIGHT, HeightMeasure.HEIGHT_ABOVE_STILT)


class Band(Part):
    """One row of the height tables: the heights it covers and what it asks of them. Each edge
    says whether it belongs to the band, so every height falls in exactly one band: a building of
    exactly 21 m is a high-rise (rule 2(f)) and has its own row.

    A band's edges are read on its own `measure`: the rule height for Table IV's rows, the height
    above the stilt for Table III's (rule 5(c)); `HeightRules.band_for_block` finds a block's band
    either way. `setback_m` is the setback on every side but the front when `front_setback_m` is
    given, all round when it is not. `permission` says whether a building of these heights may
    stand on this site at all (plot size, road), with the reason when it may not; a height the
    tables do not permit is a band of its own, so the bands still cover every height once."""

    above_m: float = Field(ge=0)
    up_to_m: float = Field(gt=0)
    above_inclusive: bool = False  # True: a height of exactly above_m is in this band
    up_to_inclusive: bool = True  # False: a height of exactly up_to_m is in the next band
    kind: BandKind
    measure: HeightMeasure = HeightMeasure.RULE_HEIGHT  # what the edges are read on
    modelled: bool = True  # False: the engine does not encode this band yet
    min_road_m: float | None = None
    setback_m: float | None = None  # every side but the front when front_setback_m is given
    front_setback_m: float | None = Field(None, ge=0)  # on the access road's frontage
    gap_m: float | None = None  # between two blocks
    permission: Eligibility = Eligibility.ALLOWED
    permission_note: str = ""  # why, whenever permission is not ALLOWED
    green_strip_m: float | None = Field(None, ge=0)  # the planting strip this band asks, if any
    green_strip_sides: Literal["ALL", "FRONTAGE"] = "ALL"
    clause: str
    status: Provenance = Provenance.VERIFIED

    @model_validator(mode="after")
    def _edges(self) -> Band:
        if self.up_to_m < self.above_m:
            raise ValueError("a band's upper edge is below its lower edge")
        if self.up_to_m == self.above_m and not (self.above_inclusive and self.up_to_inclusive):
            raise ValueError("a band for one exact height includes both its edges")
        if self.measure not in BAND_MEASURES:
            raise ValueError(f"a band is read on the rule height or the height above the stilt, "
                             f"not {self.measure}")
        if (self.measure is HeightMeasure.HEIGHT_ABOVE_STILT
                and self.kind is not BandKind.NON_HIGH_RISE):
            raise ValueError("only a non-high-rise band is read on the height above the stilt")
        if self.permission is not Eligibility.ALLOWED and not self.permission_note:
            raise ValueError("a band that is not ALLOWED says why (permission_note)")
        return self

    @property
    def front_m(self) -> float | None:
        """The setback at the front: the front figure when the band gives one, else setback_m."""
        return self.front_setback_m if self.front_setback_m is not None else self.setback_m

    def contains(self, height_m: float, tol_m: float = HEIGHT_TOL_M) -> bool:
        low = (height_m >= self.above_m - tol_m if self.above_inclusive
               else height_m > self.above_m + tol_m)
        high = (height_m <= self.up_to_m + tol_m if self.up_to_inclusive
                else height_m < self.up_to_m - tol_m)
        return low and high


class LimitBound(StrEnum):
    BOUNDED = "BOUNDED"  # max_m is the limit
    UNBOUNDED = "UNBOUNDED"  # the law sets no limit on this measure here
    NOT_EVALUATED = "NOT_EVALUATED"  # there is a limit, and it cannot be worked out yet


class Applicability(StrEnum):
    APPLIES = "APPLIES"  # unconditional, or its condition is known to hold
    DOES_NOT_APPLY = "DOES_NOT_APPLY"  # its condition is known not to hold
    UNKNOWN = "UNKNOWN"  # its condition rests on a site fact nobody has settled


class SiteFact(StrEnum):
    """The site facts a height limit may depend on."""

    ROAD_ENDS_AT_PLOT = "access.dead_end"
    MASTER_PLAN_LAND_SURRENDERED = "master_plan_land_surrendered"


class LimitCondition(Part):
    fact: SiteFact
    holds_when: bool  # the fact's value that brings the limit in
    text: str  # in plain words, e.g. 'the access road ends at the plot'


class HeightLimit(Part):
    """One limit on a height. `bound` says whether there is a number; `applicability` whether
    the limit is in force; `status` how far the inputs behind the number are confirmed. A limit
    that does not apply stays in the list, so a report can say it was considered."""

    id: str
    measure: HeightMeasure
    bound: LimitBound
    max_m: float | None = None  # present exactly when BOUNDED
    inclusive: bool = True  # True: up to and including max_m; False: must stay under it
    condition: LimitCondition | None = None
    applicability: Applicability = Applicability.APPLIES
    status: Provenance
    reason: str
    clause: str

    @model_validator(mode="after")
    def _consistent(self) -> HeightLimit:
        if (self.bound is LimitBound.BOUNDED) != (self.max_m is not None):
            raise ValueError(f"{self.id}: max_m is given exactly when the limit is BOUNDED")
        if self.max_m is not None and not (math.isfinite(self.max_m) and self.max_m > 0):
            raise ValueError(f"{self.id}: max_m must be a positive, finite number of metres")
        if self.condition is None and self.applicability is not Applicability.APPLIES:
            raise ValueError(f"{self.id}: a limit with no condition applies")
        return self

    def within(self, height_m: float, tol_m: float = HEIGHT_TOL_M) -> bool | None:
        """Whether the height keeps to the bound; None when there is no number to hold it to."""
        if self.bound is not LimitBound.BOUNDED:
            return None
        return (height_m <= self.max_m + tol_m if self.inclusive
                else height_m < self.max_m - tol_m)

    def evaluate(self, height_m: float, tol_m: float = HEIGHT_TOL_M) -> Status:
        """The one table every consumer uses:

        - a limit that does not apply is not applied (INFO);
        - no limit: PASS; a limit that cannot be worked out: UNVERIFIED;
        - a limit whose inputs nobody confirmed settles nothing either way: UNVERIFIED;
        - within the bound: PASS (it holds whether or not the limit applies);
        - beyond it: FAIL when the limit applies, UNVERIFIED when that is not known.
        """
        if self.applicability is Applicability.DOES_NOT_APPLY:
            return Status.INFO
        if self.bound is LimitBound.UNBOUNDED:
            return Status.PASS
        if self.bound is LimitBound.NOT_EVALUATED or self.status is Provenance.UNVERIFIED:
            return Status.UNVERIFIED
        if self.within(height_m, tol_m):
            return Status.PASS
        return Status.FAIL if self.applicability is Applicability.APPLIES else Status.UNVERIFIED

    def beyond(self, height_m: float, tol_m: float = HEIGHT_TOL_M) -> bool:
        """Whether the height passes a bound that applies: a generator does not offer such a
        height, whether or not the inputs behind the bound are confirmed. Beyond a bound that
        only may apply (its condition rests on an unsettled site fact) the height may be
        offered, and `evaluate` labels it UNVERIFIED."""
        return (self.applicability is Applicability.APPLIES
                and self.within(height_m, tol_m) is False)


class EligibilityGround(Part):
    """One thing a high-rise needs of the site (its road, its plot), and whether the site has
    it. `met` is None when it cannot be told."""

    id: str  # 'road_width', 'plot_size'
    met: bool | None
    measured: str
    required: str
    clause: str
    status: Provenance  # how far the input behind `met` is confirmed

    @property
    def settled(self) -> bool:
        return self.met is not None and self.status is not Provenance.UNVERIFIED


class HighRiseEligibility(Part):
    """Whether the site may take a high-rise at all. PROHIBITED says only that no building of
    the high-rise height or more may stand here. It says nothing about what may be built below
    that height: the non-high-rise band, its permissible height, Table III setbacks, road
    conditions and spacing are their own rules, and a height in a band that is not modelled is
    not validated by anyone until it is."""

    eligibility: Eligibility
    grounds: list[EligibilityGround] = Field(min_length=1)
    note: str = ""

    @staticmethod
    def of_grounds(grounds: list[EligibilityGround]) -> Eligibility:
        if any(g.settled and g.met is False for g in grounds):
            return Eligibility.PROHIBITED
        if any(not g.settled for g in grounds):
            return Eligibility.UNVERIFIED
        return Eligibility.ALLOWED

    @model_validator(mode="after")
    def _follows_the_grounds(self) -> HighRiseEligibility:
        expected = self.of_grounds(self.grounds)
        if self.eligibility is not expected:
            raise ValueError(f"high-rise eligibility {self.eligibility} does not follow from its "
                             f"grounds ({expected})")
        return self


class HeightRules(Part):
    measures: dict[HeightMeasure, str]  # what each measure includes
    rule_height_interpretation: str = STILT_IN_RULE_HEIGHT
    high_rise_from_m: RuleValue[float]
    high_rise: HighRiseEligibility
    tdr_band_m: RuleValue[tuple[float, float]]
    tdr_plot_sqm: RuleValue[tuple[float, float]]
    bands: list[Band] = Field(min_length=1)
    limits: list[HeightLimit]

    @model_validator(mode="after")
    def _bands_cover_every_height_once(self) -> HeightRules:
        bands = sorted(self.bands, key=lambda b: (b.above_m, b.up_to_m))
        if bands[0].above_m != 0 or bands[0].above_inclusive:
            raise ValueError("the first band starts just above 0 m")
        for a, b in zip(bands, bands[1:], strict=False):
            if b.above_m != a.up_to_m or a.up_to_inclusive == b.above_inclusive:
                raise ValueError(f"the bands at {a.up_to_m:g} m leave a gap or overlap: each "
                                 "height must fall in exactly one band")
        start = self.high_rise_from_m.value
        if any(b.measure is HeightMeasure.HEIGHT_ABOVE_STILT
               and (b.up_to_m > start or (b.up_to_m == start and b.up_to_inclusive))
               for b in self.bands):
            raise ValueError("a band read on the height above the stilt ends at the high-rise "
                             "height, which it leaves out (a building of exactly that height is "
                             "a high-rise)")
        ids = [limit.id for limit in self.limits]
        if len(ids) != len(set(ids)):
            raise ValueError("height limit ids must be unique")
        return self

    def band_for(self, height_m: float, tol_m: float = HEIGHT_TOL_M) -> Band | None:
        """The band a bare height falls in, read on that band's own measure; None above the last
        band or at 0 m. For a building, use band_for_block."""
        return next((b for b in self.bands if b.contains(height_m, tol_m)), None)

    def band_for_block(self, above_stilt_m: float, stilt_m: float, *, stilt_counted: bool,
                       tol_m: float = HEIGHT_TOL_M) -> Band | None:
        """The band a block falls in: its class (high-rise or not) from its rule height under
        the reading of the stilt, then, for a block below the high-rise height, its row on the
        height above the stilt where the band is read on that (rule 5(c)). Under 'counted' a
        block below 21 m is never found on its rule height, which would shift its Table III row
        by the stilt."""
        rule = above_stilt_m + (stilt_m if stilt_counted else 0.0)
        band = self.band_for(rule, tol_m)
        if band is None or band.measure is not HeightMeasure.HEIGHT_ABOVE_STILT:
            return band
        return next((b for b in self.bands if b.measure is HeightMeasure.HEIGHT_ABOVE_STILT
                     and b.contains(above_stilt_m, tol_m)), None)

    def band_permission(self, band: Band) -> Eligibility:
        """Whether a building of a band's heights may stand here: the band's own permission, and
        for a high-rise band the site's high-rise eligibility too, whichever is weaker."""
        if band.kind is BandKind.HIGH_RISE:
            return min(band.permission, self.high_rise.eligibility, key=ELIGIBILITY_RANK.get)
        return band.permission

    def permissible_non_high_rise(self, *, include_unverified: bool = False) -> Band | None:
        """The highest band below the high-rise height a building may take here (ALLOWED, or
        also UNVERIFIED when asked): the actual permissible non-high-rise height is its upper
        edge. None while the non-high-rise bands are not modelled."""
        allowed = {Eligibility.ALLOWED} | ({Eligibility.UNVERIFIED} if include_unverified
                                          else set())
        bands = [b for b in self.bands if b.kind is BandKind.NON_HIGH_RISE and b.modelled
                 and self.band_permission(b) in allowed]
        return max(bands, key=lambda b: (b.up_to_m, b.up_to_inclusive), default=None)


# --- The rest of the law ---------------------------------------------------------------------


class SetbackRules(Part):
    measured_on: RuleValue[str]  # the net plot
    front: RuleValue[str]
    concessions: list[RuleValue[str]] = []  # each note says when it applies


class SpacingRules(Part):
    clause: str
    mixed_heights_interpretation: str = MIXED_HEIGHT_SPACING


class Qualification(StrEnum):
    QUALIFIES = "QUALIFIES"
    DOES_NOT_QUALIFY = "DOES_NOT_QUALIFY"
    UNKNOWN = "UNKNOWN"  # the facility's use or surface is not stated: nothing is assumed


class OpenSpaceRules(Part):
    share: RuleValue[float]
    basis_interpretation: str = OPEN_SPACE_BASIS
    requirement_sqm_by_reading: dict[str, float]  # the area asked under each denominator
    min_width_m: RuleValue[float]
    min_pocket_sqm: RuleValue[float]
    over_and_above_setbacks: RuleValue[bool]
    block_gaps_excluded: RuleValue[bool]
    buffer_may_count: RuleValue[bool]
    qualifying_uses: RuleValue[list[FacilityUse]]  # the uses the rule names
    tot_lot_surface_interpretation: str = TOT_LOT_SURFACE
    other_uses_interpretation: str = OPEN_SPACE_OTHER_USES

    @model_validator(mode="after")
    def _usable(self) -> OpenSpaceRules:
        if not 0 < self.share.value <= 1:
            raise ValueError("the open-space share is a fraction above 0 and up to 1")
        if self.min_width_m.value <= 0 or self.min_pocket_sqm.value < 0:
            raise ValueError("the open-space pocket width and area must be positive")
        if any(not (math.isfinite(v) and v >= 0)
               for v in self.requirement_sqm_by_reading.values()):
            raise ValueError("each open-space requirement is a finite area")
        return self

    def qualifies(self, use: FacilityUse | None, surface: Surface | None, *,
                  tot_lot_surface: str, other_uses: str) -> Qualification:
        """Whether a facility's ground is of a kind that counts as organised open space, from
        its stated use and surface and the rule's words, under one reading of each open question.
        Never from its name. Where the ground lies (setbacks, block gaps, pocket sizes) is a
        separate test.

        - a use or surface nobody stated: UNKNOWN;
        - anything under a roof: it does not qualify;
        - a use the rule names, on a soft surface: qualifies;
        - a tot-lot on a hard surface: the rule names the tot-lot and does not say its surface,
          so it qualifies under `any_surface`;
        - whatever else is open to the sky (a court, a pool, a paved deck, greenery or
          landscaping stated as paved, a hard tot-lot under `soft_only`): it qualifies under
          `any_open_recreation` and not under `same_kind_only`.
        """
        if use is None or surface is None:
            return Qualification.UNKNOWN
        if surface is Surface.BUILT:
            return Qualification.DOES_NOT_QUALIFY
        named = use in self.qualifying_uses.value
        if named and surface is Surface.SOFT:
            return Qualification.QUALIFIES
        if use is FacilityUse.TOT_LOT and named and tot_lot_surface == ANY_SURFACE:
            return Qualification.QUALIFIES
        return (Qualification.QUALIFIES if other_uses == ANY_OPEN_RECREATION
                else Qualification.DOES_NOT_QUALIFY)


class GreenStripRules(Part):
    """The planting strips. The high-rise strip: width_m where the setback is where_setback_from_m
    or more (rule 7(a)(viii)). Table III's (rule 5(f)): frontage_m along the frontage within the
    front setback, and periphery_m on the remaining sides on plots above periphery_above_sqm.
    What each band asks is on the band (Band.green_strip_m), so no consumer works it out again."""

    width_m: RuleValue[float]
    where_setback_from_m: RuleValue[float]
    frontage_m: RuleValue[float] | None = None
    periphery_m: RuleValue[float] | None = None
    periphery_above_sqm: RuleValue[float] | None = None


class CirculationRules(Part):
    applies: RuleValue[bool]  # rule 8 governs a group development scheme
    approach_m: RuleValue[tuple[float, float]]
    approach_interpretation: str = APPROACH_WIDTH
    internal_road_m: RuleValue[float]
    cul_de_sac_width_m: RuleValue[float]
    cul_de_sac_length_m: RuleValue[tuple[float, float]]
    cul_de_sac_head_radius_m: RuleValue[float]
    pathway_max_block_height_m: RuleValue[float]
    pathway_width_m: RuleValue[float] | None = None  # rule 8(l)'s pathway, for such a block
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


class ElectricalRules(Part):
    """Rule 3(c)(i): the distance, vertical and horizontal, a building keeps from a line."""

    ht_clearance_m: RuleValue[float]
    lt_clearance_m: RuleValue[float]


class ParkingMeasurement(Part):
    """How parking is measured where no order says: the engine's own standard."""

    bay_m: tuple[float, float]
    aisle_m: float = Field(gt=0)
    sqm_per_car: float = Field(gt=0)
    basis: Basis = Basis.ENGINE_DESIGN_ASSUMPTION
    note: str = ""

    @model_validator(mode="after")
    def _a_car_fits(self) -> ParkingMeasurement:
        if min(self.bay_m) < 1.0:
            raise ValueError("a parking bay is at least a metre each way")
        if self.basis is Basis.LEGAL_RULE:
            raise ValueError("no order gives a bay size: this is never a legal rule")
        return self


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
    ramp_fire_clearance_m: RuleValue[float]  # what a ramp in a side or rear setback leaves clear
    utilities_max_fraction: RuleValue[float]
    measurement: ParkingMeasurement

    @model_validator(mode="after")
    def _usable(self) -> ParkingRules:
        table = self.cellar_setback_by_site_sqm.value
        if not table or table[-1][0] is not None:
            raise ValueError("the cellar setback table ends with a row for every larger site")
        if self.ramp_gradient.value <= 0:
            raise ValueError("a ramp's gradient is above zero")
        for name in ("visitors_fraction", "utilities_max_fraction"):
            if not 0 <= getattr(self, name).value <= 1:
                raise ValueError(f"{name} is a fraction between 0 and 1")
        if any(not 0 < share <= 100 for share in self.share_pct_by_column.values()):
            raise ValueError("a Table V share is a percentage above 0 and up to 100")
        return self


class AmenityRules(Part):
    share_of_built_up: RuleValue[float]
    share_interpretation: str = AMENITY_SHARE
    cap_sqft_2016: RuleValue[float]
    from_units: RuleValue[int]
    separate_block: RuleValue[str]


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
    electrical: ElectricalRules
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
        for name, readings in READINGS.items():
            given = set(self.interpretation(name).alternatives)
            if given != set(readings):
                raise ValueError(f"{name}: its readings are {sorted(readings)}, not "
                                 f"{sorted(given)}")
        if set(self.open_space.requirement_sqm_by_reading) != set(READINGS[OPEN_SPACE_BASIS]):
            raise ValueError("open_space.requirement_sqm_by_reading needs one area per reading "
                             f"of {OPEN_SPACE_BASIS}")
        return self

    def interpretation(self, interpretation_id: str) -> Interpretation:
        return next(i for i in self.interpretations if i.id == interpretation_id)

    def readings(self, interpretation_id: str) -> list[str]:
        return self.interpretation(interpretation_id).readings()
