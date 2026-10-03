"""Three ways of accounting for land, kept apart because they answer different questions.

- OwnershipReconciliation: how much land the owner holds. Gross ownership becomes net ownership
  only through land that leaves the title (a surrender, an acquisition, a transfer). A setback,
  a water buffer, a fire band or a green strip restricts building on land the owner still
  holds: it never reduces the net site area.
- PartitionLedger: what each square metre of the net site physically is. Every square metre
  appears exactly once, under its primary physical use; a second function of the same ground
  (a road that is also the fire tender's route) is a tag, never a second area. The entries sum
  to the net site area.
- RuleLayers: the regulatory geometry (setbacks, block gaps, fire bands, buffers, qualifying
  open space). Layers may overlap and are never summed; whether buffer or green-strip land
  qualifies as open space is said here, not by counting it twice in the ledger.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator
from shapely.strtree import STRtree

from siteplan.contracts.common import (
    Basis,
    Contract,
    Line,
    Part,
    Provenance,
    Shape,
    Side,
    Sourced,
    union_of,
)

AREA_TOLERANCE_SQM = 0.01  # a shape's stated area may differ from its drawn area by this
OVERLAP_TOLERANCE_SQM = 0.01  # two ledger entries overlapping by more than this is an error


# --- Ownership -------------------------------------------------------------------------------


class DeductionKind(StrEnum):
    """Only these reduce gross ownership to net ownership: each takes land out of the title."""

    SURRENDER = "SURRENDER"  # given up, e.g. for road widening or a master-plan road
    ACQUISITION = "ACQUISITION"  # acquired by a public body
    TRANSFER = "TRANSFER"  # any other conveyance out of the title


class LocationHow(StrEnum):
    OUTLINE = "OUTLINE"  # its own outline is known
    SIDE_AND_WIDTH = "SIDE_AND_WIDTH"  # an even strip of a known width along a named side
    EXTENT = "EXTENT"  # the stretch of boundary it runs along, and its width
    UNKNOWN = "UNKNOWN"  # its area is stated, where it lies is not: the pipeline stops and asks


class DeductionLocation(Part):
    how: LocationHow
    shape: Shape | None = None
    side: Side | None = None
    width_m: float | None = Field(None, gt=0)
    extent: Line | None = None

    @model_validator(mode="after")
    def _says_enough(self) -> DeductionLocation:
        needs = {LocationHow.OUTLINE: ("shape",), LocationHow.SIDE_AND_WIDTH: ("side", "width_m"),
                 LocationHow.EXTENT: ("extent", "width_m"), LocationHow.UNKNOWN: ()}[self.how]
        missing = [name for name in needs if getattr(self, name) is None]
        if missing:
            raise ValueError(f"a {self.how} location needs {', '.join(missing)}")
        return self


class OwnershipDeduction(Part):
    kind: DeductionKind
    purpose: str  # e.g. "road widening of the east road to 40 ft"
    area_sqm: Sourced[float]
    location: DeductionLocation


class OwnershipReconciliation(Part):
    """Gross ownership less the land that left the title is net ownership: the net site area
    every rule is measured on."""

    gross_sqm: Sourced[float]
    written_as: str | None = None  # the gross area as written, e.g. '3 AC 12.50 GTS'
    deductions: list[OwnershipDeduction] = []
    net_sqm: Sourced[float]
    tolerance: float = Field(0.02, ge=0, le=0.1)  # share of gross the arithmetic may miss by

    @model_validator(mode="after")
    def _adds_up(self) -> OwnershipReconciliation:
        expected = self.gross_sqm.value - sum(d.area_sqm.value for d in self.deductions)
        if abs(expected - self.net_sqm.value) > self.tolerance * self.gross_sqm.value:
            raise ValueError(
                f"gross {self.gross_sqm.value:,.1f} m² less deductions of "
                f"{self.gross_sqm.value - expected:,.1f} m² is {expected:,.1f} m², not the "
                f"{self.net_sqm.value:,.1f} m² stated as net")
        located = [d.location.shape.to_shapely() for d in self.deductions if d.location.shape]
        for i, a in enumerate(located):
            for b in located[i + 1:]:
                if a.intersection(b).area > OVERLAP_TOLERANCE_SQM:
                    raise ValueError("two ownership deductions overlap: each square metre leaves "
                                     "the title once")
        return self


# --- The physical partition of the net site --------------------------------------------------


class PhysicalUse(StrEnum):
    TOWER = "TOWER"
    CLUB_HOUSE = "CLUB_HOUSE"
    OTHER_BUILT = "OTHER_BUILT"  # security cabin, substation, anything else with a roof
    ROAD = "ROAD"  # paved internal road, approach or driveway
    FIRE_HARDSTANDING = "FIRE_HARDSTANDING"  # motorable clear ground that is not a road
    SURFACE_PARKING = "SURFACE_PARKING"
    RAMP = "RAMP"  # the cellar ramp's opening at ground level
    SOFT_OPEN_SPACE = "SOFT_OPEN_SPACE"  # planted or soft-landscaped ground: tot-lot, garden
    GREEN_STRIP = "GREEN_STRIP"  # the planted strip along the boundary
    HARD_AMENITY = "HARD_AMENITY"  # pool, court, deck
    BUFFER_LAND = "BUFFER_LAND"  # left as it is inside a statutory buffer
    UNALLOCATED = "UNALLOCATED"  # nothing yet: must say why


class PartitionEntry(Part):
    use: PhysicalUse
    shapes: list[Shape] = Field(min_length=1)
    area_sqm: float = Field(ge=0)
    ref: str | None = None  # the tower, road or facility this is
    tags: list[str] = []  # other functions of the same ground (e.g. FIRE_ACCESS); never an area
    reason: str | None = None  # why the ground is empty: required for UNALLOCATED

    @model_validator(mode="after")
    def _consistent(self) -> PartitionEntry:
        drawn = sum(s.area_sqm for s in self.shapes)
        if abs(drawn - self.area_sqm) > max(AREA_TOLERANCE_SQM, drawn * 1e-6):
            raise ValueError(f"{self.use} {self.ref or ''}: area_sqm {self.area_sqm:.2f} is not "
                             f"its drawn {drawn:.2f} m²")
        if self.use is PhysicalUse.UNALLOCATED and not self.reason:
            raise ValueError("unallocated ground must say why it is empty")
        return self


class PartitionLedger(Contract):
    """The net site, every square metre once, by what it physically is."""

    net_area_sqm: float = Field(gt=0)
    tolerance: float = Field(0.005, ge=0, le=0.05)  # share of the net area the sum may miss by
    entries: list[PartitionEntry] = []

    def total_sqm(self) -> float:
        return sum(e.area_sqm for e in self.entries)

    def by_use(self) -> dict[PhysicalUse, float]:
        out: dict[PhysicalUse, float] = {}
        for entry in self.entries:
            out[entry.use] = out.get(entry.use, 0.0) + entry.area_sqm
        return out

    def problems(self, net_plot: Shape | None = None) -> list[str]:
        """Where the ledger breaks its invariants: entries overlapping, a sum that is not the
        net area, ground of the net plot left out or ground outside it counted."""
        found = []
        total = self.total_sqm()
        if abs(total - self.net_area_sqm) > self.tolerance * self.net_area_sqm:
            found.append(f"entries sum to {total:,.1f} m², not the net {self.net_area_sqm:,.1f} m²")
        pieces = [(i, s.to_shapely()) for i, e in enumerate(self.entries) for s in e.shapes]
        tree = STRtree([p for _, p in pieces])
        for a, (i, shape) in enumerate(pieces):
            for b in tree.query(shape):
                if b <= a:
                    continue
                overlap = shape.intersection(pieces[b][1]).area
                if overlap > OVERLAP_TOLERANCE_SQM:
                    j = pieces[b][0]
                    found.append(f"{self.entries[i].use} {self.entries[i].ref or ''} and "
                                 f"{self.entries[j].use} {self.entries[j].ref or ''} overlap by "
                                 f"{overlap:,.2f} m²")
        if net_plot is not None:
            plot = net_plot.to_shapely()
            counted = union_of([s for e in self.entries for s in e.shapes])
            left_out = plot.difference(counted).area
            outside = counted.difference(plot).area
            if left_out > self.tolerance * self.net_area_sqm:
                found.append(f"{left_out:,.1f} m² of the net plot is in no entry")
            if outside > self.tolerance * self.net_area_sqm:
                found.append(f"{outside:,.1f} m² counted lies outside the net plot")
        return found


# --- Regulatory layers -----------------------------------------------------------------------


class LayerKind(StrEnum):
    SETBACK = "SETBACK"
    BLOCK_GAP = "BLOCK_GAP"
    FIRE_CLEAR_BAND = "FIRE_CLEAR_BAND"
    FIRE_ACCESS_ROUTE = "FIRE_ACCESS_ROUTE"
    TURNING_SECTOR = "TURNING_SECTOR"
    WATER_BUFFER = "WATER_BUFFER"
    GREEN_STRIP_ZONE = "GREEN_STRIP_ZONE"
    QUALIFYING_OPEN_SPACE = "QUALIFYING_OPEN_SPACE"
    RAMP_FORBIDDEN = "RAMP_FORBIDDEN"
    BAYS_FORBIDDEN = "BAYS_FORBIDDEN"
    CELLAR_SETBACK = "CELLAR_SETBACK"


class Permit(StrEnum):
    ALLOWED = "ALLOWED"
    FORBIDDEN = "FORBIDDEN"
    CONDITIONAL = "CONDITIONAL"  # allowed only under a condition, often an open reading


class Permission(Part):
    use: PhysicalUse
    permit: Permit
    condition: str | None = None
    interpretation_ref: str | None = None  # the open reading a CONDITIONAL permission rests on

    @model_validator(mode="after")
    def _condition_stated(self) -> Permission:
        if self.permit is Permit.CONDITIONAL and not (self.condition or self.interpretation_ref):
            raise ValueError(f"a conditional permission for {self.use} must say on what")
        return self


class RuleLayer(Part):
    id: str
    kind: LayerKind
    shapes: list[Shape] = []
    clause: str
    basis: Basis
    status: Provenance
    interpretation_ref: str | None = None
    applies_to: str | None = None  # a tower, a pair of towers, a height band
    permits: list[Permission] = []
    area_sqm: float = 0.0  # information only: layers overlap and are never summed


class RuleLayers(Contract):
    layers: list[RuleLayer] = []

    def of(self, kind: LayerKind) -> list[RuleLayer]:
        return [layer for layer in self.layers if layer.kind is kind]

    @model_validator(mode="after")
    def _unique_ids(self) -> RuleLayers:
        ids = [layer.id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("rule layer ids must be unique")
        return self
