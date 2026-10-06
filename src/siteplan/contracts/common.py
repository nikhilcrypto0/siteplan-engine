"""Shared types for the permanent contracts (docs/ARCHITECTURE.md).

Geometry travels as plain coordinates in metres, in the survey's own frame, so every contract
serialises to JSON; the shapely objects the engine works with are made from it and back
(`Shape.to_shapely`, `shapes_from`). A fact the engine did not compute itself carries how it is
known (`Sourced`): its status, the kind of source and the source itself, so a contract can be
asked what any answer rests on.

Separation (enforced by tests/test_contracts.py): the site model holds facts about the land,
ResolvedRules what the law asks of the site, DesignBrief what the architect and the firm want.
None of the three holds another's kind of fact.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.basis import Basis
from siteplan.findings import Finding, Status
from siteplan.provenance import Provenance

__all__ = ["CONTRACTS_VERSION", "Basis", "Contract", "FacilityUse", "Finding", "Line", "Part",
           "Point", "Provenance", "Ring", "Shape", "Side", "SourceKind", "Sourced", "Status",
           "Surface", "digest", "shapes_from", "union_of"]

# 1.1 (2026-10-03): height limits with an explicit bound and applicability, high-rise eligibility,
# inclusive band edges, facility use and surface, design margins, bounds on rule values.
# 1.2 (2026-10-04): Table III (rule 5) can be held: a band's own height measure (the stilt left
# out, 5(c)), its front setback, its permission and planting strip; rule 8(l)'s pathways.
# 1.3 (2026-10-06): NBC 4.6 for special buildings (a block over a cellar of more than 500 m² or of
# two levels), NBC's 15 m line as the nbc_fire_height reading, "opens onto a road" as the
# opens_onto_road reading, NBC 4.3.2.2's 30 m pathway.
CONTRACTS_VERSION = "1.3"

Point = tuple[float, float]
Ring = list[Point]
Side = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
T = TypeVar("T")


class Part(BaseModel):
    """A piece of a contract: unknown fields are refused, so a misspelt key is an error."""

    model_config = ConfigDict(extra="forbid")


class Contract(Part):
    """A permanent contract between pipeline stages, versioned."""

    schema_version: Literal["1.3"] = CONTRACTS_VERSION


class SourceKind(StrEnum):
    SURVEY = "SURVEY"  # read off the surveyor's drawing
    ARCHITECT = "ARCHITECT"  # the architect's answer
    DOCUMENT = "DOCUMENT"  # a certificate, an approval, a title deed
    FIRM_STANDARD = "FIRM_STANDARD"  # the firm's workspace or library files
    FIRM_FINISHED_PLAN = "FIRM_FINISHED_PLAN"  # the firm's own finished drawing: never blind input
    ENGINE_DEFAULT = "ENGINE_DEFAULT"  # the engine's default, standing in until someone sets it
    TEST_PROFILE = "TEST_PROFILE"  # a site's temporary test assumption


class Surface(StrEnum):
    """What a facility's ground is made of. Stated by whoever specifies the facility (the firm's
    amenity library); never read off its name."""

    SOFT = "SOFT"  # planted or soft-landscaped ground
    HARD = "HARD"  # paved, water or a sports surface, open to the sky
    BUILT = "BUILT"  # under a roof


class FacilityUse(StrEnum):
    """What a facility is for. The first three are the uses rule 7(a)(vii) names for organised
    open space ('greenery, tot lot or soft landscaping etc.')."""

    GREENERY = "GREENERY"
    TOT_LOT = "TOT_LOT"
    SOFT_LANDSCAPE = "SOFT_LANDSCAPE"
    SPORT_COURT = "SPORT_COURT"
    POOL = "POOL"
    PAVED_DECK = "PAVED_DECK"
    BUILT_SERVICE = "BUILT_SERVICE"  # a cabin, a substation
    OTHER = "OTHER"


class Sourced(Part, Generic[T]):
    """A value with how far it can be trusted and where it came from."""

    value: T
    status: Provenance
    source_kind: SourceKind
    source: str = ""


def _finite(points: Ring, what: str) -> None:
    if not all(math.isfinite(c) for point in points for c in point):
        raise ValueError(f"{what} has a coordinate that is not a finite number")


class Shape(Part):
    """A polygon: its outer ring and any holes, metres, survey frame, not closed (the first
    point is not repeated). Every ring has at least three points and only finite coordinates."""

    outer: Ring = Field(min_length=3)
    holes: list[Ring] = []

    @model_validator(mode="after")
    def _measurable(self) -> Shape:
        _finite(self.outer, "a shape's outline")
        for hole in self.holes:
            if len(hole) < 3:
                raise ValueError("a hole needs at least three points")
            _finite(hole, "a hole")
        return self

    @classmethod
    def from_shapely(cls, polygon: Polygon, digits: int | None = None) -> Shape:
        def ring(coords) -> Ring:
            points = [(float(x), float(y)) for x, y, *_ in list(coords)[:-1]]
            return [(round(x, digits), round(y, digits)) for x, y in points] if digits else points

        return cls(outer=ring(polygon.exterior.coords),
                   holes=[ring(hole.coords) for hole in polygon.interiors])

    def to_shapely(self) -> Polygon:
        return Polygon(self.outer, self.holes)

    @property
    def area_sqm(self) -> float:
        return self.to_shapely().area


class Line(Part):
    """An open line (a road edge, a water line, a stretch of boundary), metres, survey frame."""

    points: list[Point] = Field(min_length=2)

    @model_validator(mode="after")
    def _measurable(self) -> Line:
        _finite(self.points, "a line")
        return self

    def to_shapely(self) -> LineString:
        return LineString(self.points)

    @property
    def length_m(self) -> float:
        return self.to_shapely().length


def shapes_from(geometry: BaseGeometry | None, digits: int | None = None) -> list[Shape]:
    """Every polygon in a geometry (a polygon, a multipolygon or a collection), as Shapes;
    lines, points and empty pieces are dropped."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [Shape.from_shapely(geometry, digits)]
    return [shape for part in getattr(geometry, "geoms", ()) for shape in shapes_from(part, digits)]


def union_of(shapes: list[Shape]) -> BaseGeometry:
    """The shapes as one shapely geometry (empty when there are none)."""
    return unary_union([s.to_shapely() for s in shapes])


def digest(model: BaseModel) -> str:
    """A short, stable fingerprint of a contract's content, for the refs one contract keeps to
    another (a report names the exact site model, rules and brief it judged)."""
    text = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:16]
