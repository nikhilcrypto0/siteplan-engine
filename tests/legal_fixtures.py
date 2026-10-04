"""Made-up sites for the legal-envelope tests: a CanonicalSiteModel built from a polygon and the
few facts a test is about, so each test states only what it needs. Nothing here is client data.
"""

from __future__ import annotations

from shapely.geometry import Polygon

from siteplan.contracts.common import Shape
from siteplan.contracts.site_model import CanonicalSiteModel

SOURCE = "made-up test input"


def sourced(value, status: str = "USER_CONFIRMED", kind: str = "ARCHITECT") -> dict:
    return {"value": value, "status": status, "source_kind": kind, "source": SOURCE}


def _tri(value, status: str) -> dict:
    """A yes/no/unknown answer: unknown is UNVERIFIED whatever status was asked for."""
    return sourced(value, "UNVERIFIED" if value is None else status)


def make_site(net: Polygon, *, boundary: Polygon | None = None, surrendered: float | None = None,
              strip_known: bool = True, road_m: float | None = 18.288,
              road_status: str = "USER_CONFIRMED", row_status: str = "DECLARED_ON_SITE_PLAN",
              master_plan_m: float | None = None, side: str | None = "S",
              dead_end: bool | None = False, joins: bool | None = True,
              authority: str | None = "HMDA", inside_cure: bool | None = False,
              jurisdiction_status: str = "USER_CONFIRMED", water: list | None = None,
              features: list | None = None, coordinates: tuple | None = None,
              net_plot: bool = True) -> CanonicalSiteModel:
    """A site on `net`. `surrendered` is the area given up for a road, added to the gross;
    `strip_known` says whether its location is known (else the net plot may be left out with
    `net_plot=False`, as the pipeline does while it waits for the architect)."""
    gross = net.area + (surrendered or 0.0)
    where = ({"how": "SIDE_AND_WIDTH", "side": "E", "width_m": 5.0} if strip_known
             else {"how": "UNKNOWN", "side": "E"})
    deductions = ([{"kind": "SURRENDER", "purpose": "road widening (made-up)",
                    "area_sqm": sourced(surrendered), "location": where}] if surrendered else [])
    road = {"id": 1, "side": side, "drawn_width_m": 7.0, "row_status": row_status,
            "legal_row_m": sourced(road_m, road_status) if road_m is not None else None,
            "master_plan_row_m": sourced(master_plan_m) if master_plan_m else None}
    return CanonicalSiteModel.model_validate({
        "site_id": "made-up", "name": "Made-up site",
        "boundary": Shape.from_shapely(boundary or net).model_dump(),
        "ownership": {"gross_sqm": sourced(gross, "EXTRACTED", "SURVEY"),
                      "deductions": deductions, "net_sqm": sourced(net.area)},
        "net_plot": sourced(Shape.from_shapely(net).model_dump(), "USER_CONFIRMED") if net_plot
        else None,
        "roads": [road],
        "access": {"road_id": sourced(1, "EXTRACTED", "SURVEY"), "side": sourced(
            side, "EXTRACTED", "SURVEY"), "dead_end": _tri(dead_end, "USER_CONFIRMED"),
            "joins_12m_street": _tri(joins, "USER_CONFIRMED")},
        "water": water or [], "features": features or [],
        "jurisdiction": {"authority": _tri(authority, jurisdiction_status),
                         "inside_cure": _tri(inside_cure, jurisdiction_status)},
        "coordinates": sourced(coordinates) if coordinates else None})


def nala(lines: list[list[tuple[float, float]]], *, water_class: str = "nala_over_10m",
         water_id: str = "water-1") -> dict:
    """A water body as drawn: the lines, and its class as the architect gave it."""
    return {"id": water_id, "water_class": sourced(water_class), "drawn_as": "layer NALA",
            "lines": [{"points": line} for line in lines]}
