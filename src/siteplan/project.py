"""The project file: what the architect (or, later, the LLM) fills in, validated at the boundary.

Units follow the firm's drawings: roads in feet, site in sq yd, open space in sq ft.
Metric fields are accepted too. The JSON schema of this model is what the LLM will be
asked to produce from a plain-English brief.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator
from shapely.geometry import Polygon

from siteplan.area_statement import AreaStatement
from siteplan.checks import Building, Site
from siteplan.units import ft_to_m, parse_acre_gunta, sqft_to_sqm, sqyd_to_sqm

Ring = list[tuple[float, float]]


class BuildingIn(BaseModel):
    name: str
    height_m: PositiveFloat | None = None
    stilt_height_m: PositiveFloat | None = None
    floors: PositiveInt | None = None
    floor_height_m: PositiveFloat | None = None
    footprint_m: Ring | None = Field(None, description="Outline in metres, site coordinates.")

    def to_building(self) -> Building:
        return Building(
            name=self.name,
            height_m=self.height_m,
            stilt_height_m=self.stilt_height_m,
            floors=self.floors,
            floor_height_m=self.floor_height_m,
            footprint=Polygon(self.footprint_m) if self.footprint_m else None,
        )


class SiteIn(BaseModel):
    gross_area_text: str | None = Field(None, description="As written, e.g. '3 AC 12.50 GTS'.")
    gross_area_sqm: PositiveFloat | None = None
    net_area_sqyd: PositiveFloat | None = None
    net_area_sqm: PositiveFloat | None = None
    abutting_road_ft: PositiveFloat | None = None
    abutting_road_m: PositiveFloat | None = None
    master_plan_road_ft: PositiveFloat | None = None
    master_plan_road_m: PositiveFloat | None = None
    open_space_sqft: PositiveFloat | None = None
    net_plot_m: Ring | None = None
    open_space_pockets_m: list[Ring] = []

    @model_validator(mode="after")
    def _area_text_parses(self) -> SiteIn:
        if self.gross_area_text and parse_acre_gunta(self.gross_area_text) is None:
            raise ValueError(f"gross_area_text not understood: {self.gross_area_text!r}")
        return self

    def gross_sqm(self) -> float | None:
        if self.gross_area_sqm:
            return self.gross_area_sqm
        return parse_acre_gunta(self.gross_area_text) if self.gross_area_text else None

    def net_sqm(self) -> float | None:
        if self.net_area_sqm:
            return self.net_area_sqm
        return sqyd_to_sqm(self.net_area_sqyd) if self.net_area_sqyd else None


def _metres(m: float | None, ft: float | None) -> float | None:
    return m if m is not None else (ft_to_m(ft) if ft is not None else None)


class Project(BaseModel):
    name: str
    site: SiteIn
    buildings: list[BuildingIn] = []
    area_statement: AreaStatement | None = None

    def to_site(self) -> Site:
        s = self.site
        return Site(
            gross_area_sqm=s.gross_sqm(),
            net_area_sqm=s.net_sqm(),
            abutting_road_m=_metres(s.abutting_road_m, s.abutting_road_ft),
            master_plan_road_m=_metres(s.master_plan_road_m, s.master_plan_road_ft),
            open_space_sqm=sqft_to_sqm(s.open_space_sqft) if s.open_space_sqft else None,
            net_plot=Polygon(s.net_plot_m) if s.net_plot_m else None,
            open_space_pockets=tuple(Polygon(p) for p in s.open_space_pockets_m),
            buildings=tuple(b.to_building() for b in self.buildings),
        )
