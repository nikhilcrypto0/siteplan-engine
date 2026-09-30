"""The project file: what the architect (or, later, the LLM) fills in, validated at the boundary.

Units follow the firm's drawings: roads in feet, site in sq yd, open space in sq ft.
Metric fields are accepted too. The JSON schema of this model is what the LLM will be
asked to produce from a plain-English brief.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator
from shapely.geometry import Polygon

from siteplan import rules
from siteplan.area_statement import AreaStatement
from siteplan.checks import Building, Site
from siteplan.layout import LayoutRequest
from siteplan.units import ft_to_m, parse_acre_gunta, sqft_to_sqm, sqyd_to_sqm

Ring = list[tuple[float, float]]
WaterKind = Literal[tuple(rules.WATER_BUFFER_M)]  # the classes rule 3(a)(ii) gives buffers for
RoadWidthStatus = Literal["CERTIFIED_ROW", "DECLARED_ON_SITE_PLAN", "UNVERIFIED_DRAWING_VALUE"]


def _ft(value: float | None) -> float | None:
    return ft_to_m(value) if value is not None else None


def _sqyd(value: float | None) -> float | None:
    return sqyd_to_sqm(value) if value is not None else None


def _text_area(value: str | None) -> float | None:
    return parse_acre_gunta(value) if value else None


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


class SheetIn(BaseModel):
    """What the drawing sheet's title block says, beyond the project name."""

    client: str = ""
    architect: str = ""
    drawing: str = "SITE PLAN"
    number: str = ""
    revision: str = ""
    drawn_by: str = ""


class WaterIn(BaseModel):
    """A lake, nala or river the survey draws, and the class that sets its buffer (rule 3(a)(ii)).
    The class is the architect's to say: a drawn channel does not show a nala's defined width."""

    kind: WaterKind
    survey_colour: str | None = Field(
        None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Its line colour on a PDF survey")
    survey_layer: str | None = Field(None, description="Its layer on a DXF survey")

    @model_validator(mode="after")
    def _one_way_to_find_it(self) -> WaterIn:
        if (self.survey_colour is None) == (self.survey_layer is None):
            raise ValueError("Give the water body's survey_colour (PDF) or survey_layer (DXF).")
        return self


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
    water: list[WaterIn] = []
    authority: str | None = Field(
        None, description="The body whose rules apply (GHMC, CMC, HMDA, DTCP...); the Table V "
        "parking percentage differs by one"
    )
    inside_cure: bool | None = Field(
        None, description="Inside the Core Urban Region, where GHMC's building rules apply "
        "(G.O.Ms.No.45 of 2026). Leave out when not known.")
    abutting_road_status: RoadWidthStatus | None = Field(
        None, description="How the abutting road width is known: a certified right of way, "
        "declared on the site plan, or a value read off a drawing")
    measured_carriageway_m: PositiveFloat | None = Field(
        None, description="The road as the survey measures it; reported beside the declared "
        "width, never used by the rules")
    road_dead_end: bool | None = Field(
        None, description="Does the access road end at the plot? Leave out when not known: a "
        "survey line stopping at the boundary does not prove it")
    proposed_floors: PositiveInt | None = Field(
        None, description="Floors above the stilt the firm's drawings propose")
    sanctioned_floors: PositiveInt | None = Field(
        None, description="Floors above the stilt on the sanction; from an approval, never a "
        "drawing")
    site_coordinates: tuple[float, float] | None = Field(
        None, description="Latitude and longitude. Without them airport and Air Force height "
        "limits stay unverified.")

    @model_validator(mode="after")
    def _area_text_parses(self) -> SiteIn:
        if self.gross_area_text and parse_acre_gunta(self.gross_area_text) is None:
            raise ValueError(f"gross_area_text not understood: {self.gross_area_text!r}")
        return self

    @model_validator(mode="after")
    def _paired_units_agree(self) -> SiteIn:
        """The same quantity given twice (e.g. feet and metres) must agree, not be silently
        overridden. This catches a bad unit conversion by a person or by the LLM."""
        pairs = [
            ("abutting_road_m", self.abutting_road_m, _ft(self.abutting_road_ft)),
            ("master_plan_road_m", self.master_plan_road_m, _ft(self.master_plan_road_ft)),
            ("net_area_sqm", self.net_area_sqm, _sqyd(self.net_area_sqyd)),
            ("gross_area_sqm", self.gross_area_sqm, _text_area(self.gross_area_text)),
        ]
        for name, given, derived in pairs:
            if given is not None and derived is not None and abs(given / derived - 1) > 0.01:
                raise ValueError(
                    f"{name}={given:g} disagrees with the other unit given for it "
                    f"({derived:.2f} after conversion). Give one, or make them match."
                )
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
    layout: LayoutRequest | None = None
    sheet: SheetIn = Field(default_factory=lambda: SheetIn())

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
            authority=s.authority,
            inside_cure=s.inside_cure,
            abutting_road_status=s.abutting_road_status,
            measured_carriageway_m=s.measured_carriageway_m,
        )
