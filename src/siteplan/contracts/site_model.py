"""CanonicalSiteModel: what the land is, and how each fact about it is known.

It holds no rule value and no design choice. Buffer widths, setbacks and heights are law
(ResolvedRules); flats, floors and floor heights are the brief's. Where a fact is not known it
is None with an UNVERIFIED status, never a guess: a net plot whose road strip cannot be placed
is None, and the pipeline stops and asks.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_serializer, model_validator

from siteplan import rules
from siteplan.contracts.accounting import OwnershipReconciliation
from siteplan.contracts.common import Contract, Line, Part, Shape, Side, Sourced

RowStatus = Literal["CERTIFIED_ROW", "DECLARED_ON_SITE_PLAN", "UNVERIFIED_DRAWING_VALUE"]
WaterClass = Literal[tuple(rules.WATER_BUFFER_M)]  # the classes rule 3(a)(ii) names
NET_PLOT_TOLERANCE = 0.02  # a net outline may differ from the stated net area by this share


class Road(Part):
    id: int
    side: Side | None = None
    drawn_width_m: float | None = Field(None, gt=0)  # measured across itself on the survey
    divided: bool = False
    distance_m: float | None = Field(None, ge=0)  # from the plot
    legal_row_m: Sourced[float] | None = None  # its legal right of way, when someone says
    row_status: RowStatus | None = None  # how that width is documented
    master_plan_row_m: Sourced[float] | None = None  # the width the master plan proposes


class Access(Part):
    road_id: Sourced[int | None]
    side: Sourced[Side | None]
    dead_end: Sourced[bool | None]  # does the access road end at the plot
    joins_12m_street: Sourced[bool | None]  # does it join a street 12 m wide or more
    # Where the entrance is, when the survey or the architect fixes it (2026-10-12): the stretch
    # of the net plot's edge the main approach comes in on, and the only place it may. Absent
    # from site models stored before it, and left out of the dump when absent, so a stored site
    # model keeps its digest.
    gate: Sourced[Line] | None = None

    @model_serializer(mode="wrap")
    def _as_stored_when_absent(self, handler):
        dumped = handler(self)
        if dumped.get("gate") is None:
            dumped.pop("gate", None)
        return dumped


class Water(Part):
    id: str
    water_class: Sourced[WaterClass]
    drawn_as: str  # '#00FFFF' on a PDF survey, 'layer NALA' on a DXF one
    lines: list[Line] = []  # as drawn; the buffer round them is law, not a site fact
    channel: list[Shape] = []  # what those lines close, if anything


class Feature(Part):
    kind: str  # 'HT_LINE', 'MARK', ...
    text: str = ""
    lines: list[Line] = []
    shapes: list[Shape] = []
    source: str = ""


class PlaceName(Part):
    village: str | None = None
    mandal: str | None = None
    district: str | None = None


class ApplicationStatus(StrEnum):
    """Where the building permission application stands (2026-10-13), which decides which
    orders bind it where an order names no commencement date (G.O.Ms.No.95 of 2026)."""

    NOT_FILED = "NOT_FILED"  # a new scheme: the rules in force when it is filed apply
    FILED = "FILED"  # received by the authority, on application_date
    SANCTIONED = "SANCTIONED"  # permission granted on an application received on that date


class Jurisdiction(Part):
    authority: Sourced[str | None]  # whose building rules apply: GHMC, CMC, HMDA, DTCP, ...
    inside_cure: Sourced[bool | None]
    # Since 2026-10-13: the application's status and the date it was received, each with how it
    # is known. Absent from site models stored before, and left out of the dump when absent, so a
    # stored site model keeps its digest; absent means not known.
    application_status: Sourced[ApplicationStatus | None] | None = None
    application_date: Sourced[date | None] | None = None

    @model_serializer(mode="wrap")
    def _as_stored_when_absent(self, handler):
        dumped = handler(self)
        for key in ("application_status", "application_date"):
            if dumped.get(key) is None:
                dumped.pop(key, None)
        return dumped


class CanonicalSiteModel(Contract):
    site_id: str
    name: str
    survey_file: str | None = None
    frame: str = "survey metres, as drawn"
    boundary: Shape | None = None  # the surveyed outline, as drawn
    written_area_sqm: float | None = Field(None, gt=0)  # the largest area written on the sheet
    ownership: OwnershipReconciliation
    net_plot: Sourced[Shape] | None = None  # None while a deduction cannot be placed: stop, ask
    roads: list[Road] = []
    access: Access
    water: list[Water] = []
    features: list[Feature] = []
    spot_levels: int = Field(0, ge=0)
    place: Sourced[PlaceName] | None = None
    jurisdiction: Jurisdiction
    coordinates: Sourced[tuple[float, float]] | None = None  # latitude, longitude
    proposed_floors: Sourced[int] | None = None  # what a drawing proposes; informational
    sanctioned_floors: Sourced[int] | None = None  # from an approval only, never a drawing

    @model_validator(mode="after")
    def _consistent(self) -> CanonicalSiteModel:
        ids = [road.id for road in self.roads]
        if len(ids) != len(set(ids)):
            raise ValueError("road ids must be unique")
        chosen = self.access.road_id.value
        if chosen is not None and self.roads and chosen not in ids:
            raise ValueError(f"the access road {chosen} is not one of the roads {ids}")
        if self.net_plot is not None:
            drawn, stated = self.net_plot.value.area_sqm, self.ownership.net_sqm.value
            if abs(drawn - stated) > NET_PLOT_TOLERANCE * stated:
                raise ValueError(f"the net plot outline is {drawn:,.1f} m², not the "
                                 f"{stated:,.1f} m² of net ownership")
        return self

    def access_road(self) -> Road | None:
        chosen = self.access.road_id.value
        return next((road for road in self.roads if road.id == chosen), None)
