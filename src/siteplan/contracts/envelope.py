"""BuildableEnvelope: the legal land picture of one site before any tower exists.

It holds the statutory exclusions fixed in place (a water buffer, an HT corridor), the setback
envelope and the buildable land for every height band, the width profile of that land, the
circulation the law will ask for (as requirements, never as drawn roads), and the regulatory
layers. It does not place a tower or a road, it does not partition the ground, and it does not
judge any region too narrow to use: whether a small tower, a low block or a club house fits a
narrow arm is the optimizer's question. Quantities (the open space asked, the parking share)
live in ResolvedRules; the envelope points at them.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from siteplan.contracts.accounting import RuleLayers
from siteplan.contracts.common import Contract, Finding, Line, Part, Shape, Side
from siteplan.contracts.resolved_rules import BandKind


class ExclusionKind(StrEnum):
    WATER_BUFFER = "WATER_BUFFER"
    HT_CORRIDOR = "HT_CORRIDOR"
    OTHER_STATUTORY = "OTHER_STATUTORY"


class Exclusion(Part):
    """Statutory and fixed in place: no building, whatever the design."""

    id: str
    kind: ExclusionKind
    shapes: list[Shape] = Field(min_length=1)
    clause: str
    source_ref: str | None = None  # the site model's water body or feature


class BandEnvelope(Part):
    above_m: float = Field(ge=0)
    up_to_m: float = Field(gt=0)
    kind: BandKind
    modelled: bool = True  # False until the band's rules are encoded (Table III, A2)
    setback_m: float | None = None
    setback_envelope: list[Shape] = []  # the net plot inset by the setback
    buildable: list[Shape] = []  # the setback envelope less the exclusions
    area_sqm: float = Field(0.0, ge=0)
    green_strip_applies: bool | None = None
    note: str = ""


class WidthRegion(Part):
    shape: Shape
    area_sqm: float = Field(ge=0)
    max_inscribed_width_m: float = Field(ge=0)
    length_m: float = Field(ge=0)


class WidthProfile(Part):
    """How wide a piece of land is, region by region; reported, never classified."""

    applies_to: str  # 'net plot' or a band, e.g. '27-30 m'
    regions: list[WidthRegion] = []
    area_narrower_than: list[tuple[float, float]] = []  # (width m, area of land narrower)


class AccessZone(Part):
    """Where a gate may open: frontage on the access road, less any buffer."""

    id: str
    road_id: int | None = None
    side: Side | None = None
    frontage: Line
    length_m: float = Field(ge=0)
    note: str = ""


class Obligation(Part):
    """Something the law will ask of the layout here, and where ResolvedRules holds its value."""

    id: str
    applies: bool
    rule_ref: str  # a path into ResolvedRules, e.g. 'circulation.internal_road_m'
    note: str = ""


class CirculationRequirements(Part):
    access_zones: list[AccessZone] = []
    obligations: list[Obligation] = []


class BuildableEnvelope(Contract):
    site_ref: str
    rules_ref: str
    exclusions: list[Exclusion] = []
    bands: list[BandEnvelope] = []
    width_profiles: list[WidthProfile] = []
    circulation: CirculationRequirements = CirculationRequirements()
    requirements: list[Obligation] = []  # open space, club house, parking, ramp, cellars
    rule_layers: RuleLayers = RuleLayers()
    facts: list[Finding] = []  # category, high-rise eligibility, height limits, unknowns
