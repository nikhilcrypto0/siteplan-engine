"""The prototype's project file, split into the contracts' three kinds of fact and joined back.

A project file (project.py) mixes the site's facts, the readings of the law it was planned under
and the design asked for. `split_project` turns it into a CanonicalSiteModel, a DesignBrief and
the readings; `join_project` makes the project file again. A round trip changes no number the
engine uses (tests/test_adapters.py). Where a project file says nothing about where a value
came from, the value is taken as the architect's: a project file is what the architect fills in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shapely.geometry import Polygon

from siteplan.contracts.accounting import DeductionKind, LocationHow
from siteplan.contracts.common import Provenance, Shape, SourceKind
from siteplan.contracts.design_brief import ClubSize, DesignBrief, HeightMode
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    STILT_IN_RULE_HEIGHT,
    WhenOpen,
)
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.intake import Draft, WorkspaceDefaults
from siteplan.layout import LayoutRequest
from siteplan.project import Project, _metres

KIND_BY_PREFIX = (("survey", SourceKind.SURVEY), ("architect", SourceKind.ARCHITECT),
                  ("firm standard", SourceKind.FIRM_STANDARD),
                  ("engine default", SourceKind.ENGINE_DEFAULT),
                  ("test profile", SourceKind.TEST_PROFILE), ("document", SourceKind.DOCUMENT))
DERIVED_NET = "derived: no deduction stated, so net equals gross"
DEFAULT_NOTATION = "Stilt + N means one parking stilt plus N floors above it"
NET_GROSS_TOLERANCE_SQM = 1.0
ROAD_NUMBER = re.compile(r"road (\d+)")
STANDARD_KEYS = {"stilt_height_m": "stilt_height_m", "floor_to_floor_m": "floor_height_m",
                 "cellar_floor_height_m": "cellar_floor_height_m",
                 "common_area_loading_pct": "common_area_pct"}


@dataclass(frozen=True)
class Readings:
    """The readings of the law a legacy request was made under (ResolvedRules selections)."""

    selections: dict[str, str]
    when_open: WhenOpen

    @classmethod
    def of(cls, request: LayoutRequest) -> Readings:
        return cls({STILT_IN_RULE_HEIGHT: "counted" if request.stilt_in_rule_height
                    else "not_counted",
                    CIRCULATION_IN_SETBACK: "allowed" if request.circulation_in_setback
                    else "not_allowed"},
                   WhenOpen.CONSERVATIVE if request.conservative_parking else WhenOpen.STOP)


def kind_of(project: Project, key: str) -> SourceKind:
    if key in project.source_kinds:
        return project.source_kinds[key]
    text = project.sources.get(key, "").lower()
    return next((kind for prefix, kind in KIND_BY_PREFIX if text.startswith(prefix)),
                SourceKind.ARCHITECT)


def sourced(project: Project, key: str, value) -> dict:
    status = project.status.get(key) or (
        Provenance.UNVERIFIED if value is None else Provenance.USER_CONFIRMED)
    return {"value": value, "status": status, "source_kind": kind_of(project, key),
            "source": project.sources.get(key, "project file")}


def split_project(project: Project, *, site_id: str | None = None,
                  boundary: Polygon | None = None, draft: Draft | None = None,
                  defaults: WorkspaceDefaults | None = None,
                  notation: dict | None = None) -> tuple[CanonicalSiteModel, DesignBrief, Readings]:
    if project.layout is None:
        raise ValueError("The project has no layout request to split into a brief.")
    site = site_model(project, site_id=site_id, boundary=boundary, draft=draft)
    return site, brief(project, defaults, notation), Readings.of(project.layout)


def site_model(project: Project, *, site_id: str | None = None, boundary: Polygon | None = None,
               draft: Draft | None = None) -> CanonicalSiteModel:
    s = project.site
    plot = Polygon(s.net_plot_m) if s.net_plot_m else None
    gross = s.gross_sqm() or (boundary.area if boundary is not None else None) or (
        plot.area if plot is not None else s.net_sqm())
    if gross is None:
        raise ValueError("The project states no site area and has no outline.")
    net = s.net_sqm() or gross
    ownership = {"gross_sqm": sourced(project, "gross_area_sqm", gross),
                 "written_as": s.gross_area_text, "deductions": [],
                 "net_sqm": sourced(project, "net_area_sqm", net) if s.net_sqm() else {
                     "value": net, "status": Provenance.EXTRACTED,
                     "source_kind": kind_of(project, "gross_area_sqm"), "source": DERIVED_NET}}
    if net < gross - NET_GROSS_TOLERANCE_SQM:
        ownership["deductions"].append({
            "kind": DeductionKind.SURRENDER,
            "purpose": project.sources.get("road_strip") or project.sources.get(
                "net_area_sqm", "land given up"),
            "area_sqm": sourced(project, "net_area_sqm", gross - net),
            "location": _location(project)})
    roads, chosen = _roads(project, draft)
    return CanonicalSiteModel(
        site_id=site_id or re.sub(r"[^a-z0-9]+", "-", project.name.lower()).strip("-"),
        name=project.name, survey_file=draft.survey if draft else None,
        boundary=Shape.from_shapely(boundary) if boundary is not None else None,
        written_area_sqm=draft.written_area_sqm if draft else None, ownership=ownership,
        net_plot=sourced(project, "net_plot_m", Shape.from_shapely(plot)) if plot else None,
        roads=roads,
        access={"road_id": {**sourced(project, "access_side", chosen),
                            "status": project.status.get("access_side") or (
                                Provenance.UNVERIFIED if chosen is None
                                else Provenance.USER_CONFIRMED)},
                "side": sourced(project, "access_side", s.access_side),
                "dead_end": sourced(project, "road_dead_end", s.road_dead_end),
                "joins_12m_street": sourced(project, "street_joins_12m", s.street_joins_12m)},
        water=[{"id": f"water-{i}",
                "water_class": sourced(project, "water", w.kind),
                "drawn_as": w.survey_colour or f"layer {w.survey_layer}"}
               for i, w in enumerate(s.water, 1)],
        features=[{"kind": "MARK", "text": f"{m.kind}: {m.text}", "source": "survey"}
                  for m in (draft.marks if draft else ())],
        spot_levels=draft.on_site_levels if draft else 0,
        place=_place(draft),
        jurisdiction={"authority": sourced(project, "authority", s.authority),
                      "inside_cure": sourced(project, "inside_cure", s.inside_cure)},
        coordinates=sourced(project, "site_coordinates", s.site_coordinates)
        if s.site_coordinates else None,
        proposed_floors=sourced(project, "proposed_floors", s.proposed_floors)
        if s.proposed_floors else None,
        sanctioned_floors=sourced(project, "sanctioned_floors", s.sanctioned_floors)
        if s.sanctioned_floors else None)


def _location(project: Project) -> dict:
    s = project.site
    if s.road_strip_m:
        return {"how": LocationHow.OUTLINE, "shape": Shape.from_shapely(Polygon(s.road_strip_m))}
    if s.road_strip_side and s.road_strip_width_m:
        return {"how": LocationHow.SIDE_AND_WIDTH, "side": s.road_strip_side,
                "width_m": s.road_strip_width_m}
    return {"how": LocationHow.UNKNOWN, "side": s.road_strip_side}


def _roads(project: Project, draft: Draft | None) -> tuple[list[dict], int | None]:
    """The roads the survey measured, the access road carrying its legal width; a project with
    no survey has the one road it declares."""
    s = project.site
    match = ROAD_NUMBER.search(project.sources.get("access_side", ""))
    measured = list(draft.roads) if draft else []
    chosen = int(match.group(1)) if match and measured else (None if measured else 1)
    roads = [{"id": i, "side": r.side, "drawn_width_m": r.width_m, "divided": r.divided,
              "distance_m": r.distance_m} for i, r in enumerate(measured, 1)]
    if not roads:
        roads = [{"id": 1, "side": s.access_side, "drawn_width_m": s.measured_carriageway_m}]
    road = next((r for r in roads if r["id"] == chosen), None)
    if road is not None:
        legal = _metres(s.abutting_road_m, s.abutting_road_ft)
        if legal is not None:
            road["legal_row_m"] = sourced(project, "abutting_road", legal)
        road["row_status"] = s.abutting_road_status
        planned = _metres(s.master_plan_road_m, s.master_plan_road_ft)
        if planned is not None:
            road["master_plan_row_m"] = sourced(project, "master_plan_road_m", planned)
        if s.measured_carriageway_m is not None:
            road["drawn_width_m"] = s.measured_carriageway_m
    return roads, chosen


def _place(draft: Draft | None) -> dict | None:
    if draft is None or not draft.place:
        return None
    text = draft.place
    village = re.search(r"([A-Z][A-Z .]+?)\s*\(V\)", text)
    mandal = re.search(r"([A-Z][A-Z .]+?)\s*\(M\)", text)
    district = re.search(r"([A-Z][A-Z .]+?)\s*DIST", text)
    return {"value": {"village": village and village.group(1).strip(),
                      "mandal": mandal and mandal.group(1).strip(),
                      "district": district and district.group(1).strip()},
            "status": Provenance.EXTRACTED, "source_kind": SourceKind.SURVEY,
            "source": f"survey: {text}"}


def brief(project: Project, defaults: WorkspaceDefaults | None = None,
          notation: dict | None = None) -> DesignBrief:
    r = project.layout
    defaults = defaults or WorkspaceDefaults()
    standards = {name: sourced(project, key, getattr(r, key))
                 for name, key in STANDARD_KEYS.items()}
    return DesignBrief(
        brief_id=f"{re.sub(r'[^a-z0-9]+', '-', project.name.lower()).strip('-')}-brief",
        project_name=project.name,
        program={
            "unit_mix": sourced(project, "unit_mix", r.unit_mix),
            "flat_library": sourced(project, "flat_library", defaults.flat_library)
            if defaults.flat_library else None,
            "amenity_library": sourced(project, "amenities", defaults.amenities)
            if defaults.amenities else None,
            "club_house": {"wanted": sourced(project, "club_house", r.club_house),
                           "size": ClubSize.STATED if r.club_house_sqm else ClubSize.LEGAL_MINIMUM,
                           "sqm": r.club_house_sqm, "floors": r.club_house_floors},
            "parking": {"max_cellars": sourced(project, "max_cellars", r.max_cellars)}},
        height_intent={
            "notation": notation or {"value": DEFAULT_NOTATION,
                                     "status": Provenance.ASSUMED_FOR_TEST,
                                     "source_kind": SourceKind.ENGINE_DEFAULT,
                                     "source": "the engine's reading of the notation"},
            "mode": HeightMode.MAX_LEGAL if r.maximise else HeightMode.FIXED,
            "floors_above_stilt": None if r.maximise else r.floors},
        firm_standards={
            **standards,
            "cellar_utilities_share": sourced(project, "cellar_utilities_pct",
                                              r.cellar_utilities_pct / 100),
            "min_flats_per_side": {"value": r.min_flats_per_side,
                                   "status": Provenance.ASSUMED_FOR_TEST,
                                   "source_kind": SourceKind.ENGINE_DEFAULT,
                                   "source": "engine default"},
            "max_tower_length_m": sourced(project, "max_tower_length_m", r.max_tower_length_m)
            if r.max_tower_length_m else None},
        objectives={"options": r.options})


def request(brief: DesignBrief, readings: Readings, floors_for_max: int | None = None
            ) -> LayoutRequest:
    """The legacy request a brief and its readings make. A MAX_LEGAL brief names no floor
    count (the law's height is in metres); the legacy pipeline needs the height it starts its
    search from, which the caller works out (intake does it with max_floors)."""
    h, f, p = brief.height_intent, brief.firm_standards, brief.program
    floors = h.floors_above_stilt if h.mode is HeightMode.FIXED else floors_for_max
    if floors is None:
        raise ValueError("A MAX_LEGAL brief needs the starting floors from the caller.")
    return LayoutRequest(
        floors=floors, stilt_height_m=f.stilt_height_m.value,
        floor_height_m=f.floor_to_floor_m.value, unit_mix=p.unit_mix.value,
        common_area_pct=f.common_area_loading_pct.value, club_house=p.club_house.wanted.value,
        club_house_sqm=p.club_house.sqm if p.club_house.size is ClubSize.STATED else None,
        club_house_floors=p.club_house.floors or 2,
        max_tower_length_m=f.max_tower_length_m.value if f.max_tower_length_m else None,
        min_flats_per_side=f.min_flats_per_side.value,
        stilt_in_rule_height=readings.selections[STILT_IN_RULE_HEIGHT] == "counted",
        circulation_in_setback=readings.selections[CIRCULATION_IN_SETBACK] == "allowed",
        conservative_parking=readings.when_open is WhenOpen.CONSERVATIVE,
        cellar_floor_height_m=f.cellar_floor_height_m.value,
        cellar_utilities_pct=round(f.cellar_utilities_share.value * 100, 9),
        max_cellars=p.parking.max_cellars.value, options=brief.objectives.options,
        maximise=h.mode is HeightMode.MAX_LEGAL)


def join_project(site: CanonicalSiteModel, brief: DesignBrief, readings: Readings,
                 floors_for_max: int | None = None) -> Project:
    """The legacy project file again: site fields, the request, and every value's source."""
    fields, sources, status, kinds = _site_fields(site)
    return Project(name=site.name, site=fields,
                   layout=request(brief, readings, floors_for_max),
                   sources=sources, status=status, source_kinds=kinds)


def _site_fields(site: CanonicalSiteModel) -> tuple[dict, dict, dict, dict]:
    fields: dict = {}
    sources: dict = {}
    status: dict = {}
    kinds: dict = {}

    def put(key: str, value, how, field: str | None = None) -> None:
        if value is not None:
            fields[field or key] = value
        if how is not None:
            sources[key], status[key], kinds[key] = how.source, how.status, how.source_kind

    own = site.ownership
    put("gross_area_sqm", own.gross_sqm.value, own.gross_sqm)
    if own.written_as:
        fields["gross_area_text"] = own.written_as
    if own.net_sqm.source != DERIVED_NET:
        put("net_area_sqm", own.net_sqm.value, own.net_sqm)
    for deduction in own.deductions:
        if deduction.kind is not DeductionKind.SURRENDER:
            continue
        where = deduction.location
        if where.shape is not None:
            fields["road_strip_m"] = where.shape.outer
        if where.side is not None:
            fields["road_strip_side"] = where.side
        if where.width_m is not None:
            fields["road_strip_width_m"] = where.width_m
    if site.net_plot is not None:
        put("net_plot_m", site.net_plot.value.outer, site.net_plot)
    road = site.access_road()
    if road is not None:
        if road.legal_row_m is not None:
            put("abutting_road", road.legal_row_m.value, road.legal_row_m, "abutting_road_m")
        if road.master_plan_row_m is not None:
            put("master_plan_road_m", road.master_plan_row_m.value, road.master_plan_row_m)
        if road.row_status is not None:
            fields["abutting_road_status"] = road.row_status
        if road.drawn_width_m is not None:
            fields["measured_carriageway_m"] = road.drawn_width_m
    a = site.access
    put("access_side", a.side.value, a.side)
    put("road_dead_end", a.dead_end.value, a.dead_end)
    put("street_joins_12m", a.joins_12m_street.value, a.joins_12m_street)
    if site.water:
        fields["water"] = [{"kind": w.water_class.value, **(
            {"survey_layer": w.drawn_as[len("layer "):]} if w.drawn_as.startswith("layer ")
            else {"survey_colour": w.drawn_as})} for w in site.water]
        put("water", None, site.water[0].water_class)
    j = site.jurisdiction
    put("authority", j.authority.value, j.authority)
    put("inside_cure", j.inside_cure.value, j.inside_cure)
    for key, value in (("site_coordinates", site.coordinates),
                       ("proposed_floors", site.proposed_floors),
                       ("sanctioned_floors", site.sanctioned_floors)):
        if value is not None:
            put(key, value.value, value)
    return fields, sources, status, kinds
