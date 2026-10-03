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
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.basis import Basis
from siteplan.findings import Finding, Status
from siteplan.provenance import Provenance

__all__ = ["CONTRACTS_VERSION", "Basis", "Contract", "Finding", "Line", "Part", "Point",
           "Provenance", "Ring", "Shape", "Side", "SourceKind", "Sourced", "Status", "digest",
           "shapes_from", "union_of"]

CONTRACTS_VERSION = "1.0"

Point = tuple[float, float]
Ring = list[Point]
Side = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
T = TypeVar("T")


class Part(BaseModel):
    """A piece of a contract: unknown fields are refused, so a misspelt key is an error."""

    model_config = ConfigDict(extra="forbid")


class Contract(Part):
    """A permanent contract between pipeline stages, versioned."""

    schema_version: Literal["1.0"] = CONTRACTS_VERSION


class SourceKind(StrEnum):
    SURVEY = "SURVEY"  # read off the surveyor's drawing
    ARCHITECT = "ARCHITECT"  # the architect's answer
    DOCUMENT = "DOCUMENT"  # a certificate, an approval, a title deed
    FIRM_STANDARD = "FIRM_STANDARD"  # the firm's workspace or library files
    FIRM_FINISHED_PLAN = "FIRM_FINISHED_PLAN"  # the firm's own finished drawing: never blind input
    ENGINE_DEFAULT = "ENGINE_DEFAULT"  # the engine's default, standing in until someone sets it
    TEST_PROFILE = "TEST_PROFILE"  # a site's temporary test assumption


class Sourced(Part, Generic[T]):
    """A value with how far it can be trusted and where it came from."""

    value: T
    status: Provenance
    source_kind: SourceKind
    source: str = ""


class Shape(Part):
    """A polygon: its outer ring and any holes, metres, survey frame, not closed (the first
    point is not repeated)."""

    outer: Ring = Field(min_length=3)
    holes: list[Ring] = []

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
