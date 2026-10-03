"""The prototype's types convert to the contracts and back without changing a number the engine
uses, and a legacy layout option becomes a candidate that gives the chat tool the same reply."""

import dataclasses
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from shapely.geometry import box

from siteplan.adapters import (
    Readings,
    brief,
    candidate_from_option,
    join_project,
    option_keys,
    request,
    split_project,
)
from siteplan.adapters.legacy_layout import SURFACE_UNSTATED
from siteplan.contracts import CandidateLayout
from siteplan.contracts.accounting import LayerKind, Permit, PhysicalUse
from siteplan.contracts.common import Basis, FacilityUse, Provenance, Shape, SourceKind, Surface
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK
from siteplan.intake import WorkspaceDefaults
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.mcp_server import OPTION_KEYS
from siteplan.project import Project
from siteplan.site_amenities import AmenityLibrary

EXAMPLE = Path(__file__).parent.parent / "examples" / "example.project.json"
SITE_NUMBERS = ("gross_area_sqm", "net_area_sqm", "abutting_road_m", "master_plan_road_m",
                "authority", "inside_cure", "abutting_road_status", "measured_carriageway_m",
                "road_dead_end", "street_joins_12m")
LIBRARY = FlatLibrary(
    flats=[{"name": "2A", "bhk": "2BHK", "width_m": 10.0, "depth_m": 11.0, "saleable_sqft": 1190},
           {"name": "3A", "bhk": "3BHK", "width_m": 13.5, "depth_m": 11.0,
            "saleable_sqft": 1690}],
    core_width_m=7.5)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3}, conservative_parking=True)
PLOT = box(0, 0, 150, 100)
# A made-up firm's facilities. Two say nothing of their use or surface, one of them built by its
# name alone.
AMENITIES = AmenityLibrary(items=[
    {"name": "PLAY", "width_m": 8.0, "depth_m": 6.0, "near": "open space",
     "counts_as_open_space": True, "use": "TOT_LOT", "surface": "SOFT"},
    {"name": "SEATING", "width_m": 6.0, "depth_m": 4.0, "near": "open space",
     "counts_as_open_space": True},
    {"name": "DECK", "width_m": 5.0, "depth_m": 4.0, "near": "edge", "use": "PAVED_DECK",
     "surface": "HARD"},
    {"name": "GUARD ROOM", "width_m": 3.0, "depth_m": 3.0, "near": "gate",
     "use": "BUILT_SERVICE", "surface": "BUILT"},
    {"name": "SECURITY CABIN", "width_m": 3.0, "depth_m": 3.0, "near": "gate"}])


def _intake_style_project() -> Project:
    """What build_project writes for an answered survey, made up."""
    return Project.model_validate({
        "name": "Made-up intake site",
        "site": {"gross_area_sqm": 20131.1, "net_area_sqm": 18968.4, "road_strip_side": "E",
                 "abutting_road_ft": 60.0, "abutting_road_status": "DECLARED_ON_SITE_PLAN",
                 "measured_carriageway_m": 14.08, "access_side": "W", "road_dead_end": None,
                 "street_joins_12m": None, "authority": "CMC", "inside_cure": True,
                 "water": [{"kind": "nala_over_10m", "survey_colour": "#00FFFF"}]},
        "layout": {"floors": 9, "maximise": True, "unit_mix": {"2BHK": 0.7, "3BHK": 0.3},
                   "conservative_parking": True},
        "sources": {"gross_area_sqm": "survey: written area", "net_area_sqm": "architect: net",
                    "road_strip": "architect: net 22686 sq yd, E",
                    "abutting_road": "architect: 60 ft", "access_side": "survey: road 6, to the W",
                    "road_dead_end": "architect: unknown", "authority": "architect: CMC",
                    "water": "architect: #00FFFF nala over 10 m"},
        "status": {"gross_area_sqm": "EXTRACTED", "net_area_sqm": "USER_CONFIRMED",
                   "road_strip": "UNVERIFIED", "abutting_road": "USER_CONFIRMED",
                   "access_side": "EXTRACTED", "road_dead_end": "UNVERIFIED",
                   "authority": "UNVERIFIED", "water": "USER_CONFIRMED"}})


def _numbers(project: Project) -> dict:
    site = dataclasses.asdict(project.to_site())
    out = {key: site[key] for key in SITE_NUMBERS}
    out["net_plot"] = project.to_site().net_plot.wkt if project.site.net_plot_m else None
    return out


@pytest.mark.parametrize("project", [
    Project.model_validate_json(EXAMPLE.read_text()), _intake_style_project()],
    ids=["example project", "intake-style project"])
def test_a_project_splits_and_joins_back_without_changing_a_number(project):
    site, design, readings = split_project(project)
    back = join_project(site, design, readings, floors_for_max=project.layout.floors)
    assert _numbers(back) == _numbers(project)
    assert back.layout == project.layout
    assert back.site.water == project.site.water
    assert back.site.road_strip_side == project.site.road_strip_side


def test_every_value_keeps_how_it_is_known():
    site, _, _ = split_project(_intake_style_project())
    road = site.access_road()
    assert road.legal_row_m.status is Provenance.USER_CONFIRMED
    assert road.legal_row_m.source_kind is SourceKind.ARCHITECT
    assert road.drawn_width_m == 14.08  # the measured carriageway, kept apart from the legal width
    assert site.access.dead_end.value is None
    assert site.access.dead_end.status is Provenance.UNVERIFIED
    assert site.jurisdiction.authority.status is Provenance.UNVERIFIED
    deduction = site.ownership.deductions[0]
    assert deduction.location.how == "UNKNOWN" and deduction.location.side == "E"
    assert site.net_plot is None  # the strip cannot be placed, so there is no net outline


def test_a_finished_plan_value_keeps_its_kind_through_the_round_trip():
    project = Project.model_validate_json(EXAMPLE.read_text())
    project.sources["net_plot_m"] = "the firm's site plan, registered"
    project.source_kinds["net_plot_m"] = SourceKind.FIRM_FINISHED_PLAN
    site, design, readings = split_project(project)
    assert site.net_plot.source_kind is SourceKind.FIRM_FINISHED_PLAN
    back = join_project(site, design, readings)
    assert back.source_kinds["net_plot_m"] is SourceKind.FIRM_FINISHED_PLAN


def test_the_most_the_law_allows_names_no_floor_count_in_the_brief():
    project = _intake_style_project()
    design = brief(project)
    assert design.height_intent.mode == "MAX_LEGAL"
    assert design.height_intent.floors_above_stilt is None
    with pytest.raises(ValueError, match="starting floors"):
        request(design, Readings.of(project.layout))


@pytest.fixture(scope="module")
def candidates() -> list[tuple[object, CandidateLayout]]:
    readings = Readings.of(REQUEST).selections
    return [(option, candidate_from_option(
        option, PLOT, candidate_id=f"made-up-{i}", site_ref="site", rules_ref="rules",
        brief_ref="brief", readings=readings, access_side="S"))
        for i, option in enumerate(solve(PLOT, LIBRARY, REQUEST), 1)]


def test_a_legacy_option_gives_the_chat_tool_the_same_reply(candidates):
    assert candidates, "the made-up plot must give at least one option"
    for i, (option, candidate) in enumerate(candidates, 1):
        legacy = {"option": i, "floors_above_stilt": option.floors} | option.summary()
        assert option_keys(candidate, i, REQUEST.unit_mix) == {k: legacy[k] for k in OPTION_KEYS}


def test_every_tower_stands_where_its_prototype_and_placement_put_it(candidates):
    for option, candidate in candidates:
        for tower, placed in zip(option.towers, candidate.towers, strict=True):
            drawn = candidate.placed_footprint(placed)
            assert drawn.symmetric_difference(tower.footprint).area < 1e-6


def test_the_ground_is_counted_once_and_adds_up_to_the_net_plot(candidates):
    for _, candidate in candidates:
        assert candidate.partition.problems(Shape.from_shapely(PLOT)) == []
        assert abs(candidate.partition.total_sqm() - PLOT.area) < 0.005 * PLOT.area
        uses = candidate.partition.by_use()
        assert uses[PhysicalUse.TOWER] > 0 and uses[PhysicalUse.ROAD] > 0


def test_a_road_in_the_setback_is_conditional_on_the_open_reading(candidates):
    for _, candidate in candidates:
        setback = candidate.rule_layers.of(LayerKind.SETBACK)[0]
        roads = [p for p in setback.permits if p.use is PhysicalUse.ROAD]
        assert [p.permit for p in roads] == [Permit.CONDITIONAL]
        assert roads[0].interpretation_ref == CIRCULATION_IN_SETBACK


def test_a_candidate_survives_json(candidates):
    for _, candidate in candidates:
        again = CandidateLayout.model_validate_json(candidate.model_dump_json())
        assert json.loads(again.model_dump_json()) == json.loads(candidate.model_dump_json())


def _road_status(site: dict, status: dict | None = None) -> Provenance:
    project = Project.model_validate({
        "name": "Made-up road", "site": {"gross_area_sqm": 15000.0, "abutting_road_ft": 40.0,
                                         **site},
        "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}}, "status": status or {}})
    return split_project(project)[0].access_road().legal_row_m.status


def test_a_road_width_is_never_confirmed_merely_because_nobody_said_how_it_is_known():
    assert _road_status({}) is Provenance.UNVERIFIED
    assert _road_status({"abutting_road_status": "UNVERIFIED_DRAWING_VALUE"}) is (
        Provenance.UNVERIFIED)
    assert _road_status({"abutting_road_status": "DECLARED_ON_SITE_PLAN"}) is (
        Provenance.USER_CONFIRMED)
    assert _road_status({"abutting_road_status": "CERTIFIED_ROW"}) is Provenance.VERIFIED
    # what the project itself records about the width wins over the declared source
    assert _road_status({"abutting_road_status": "UNVERIFIED_DRAWING_VALUE"},
                        {"abutting_road": "USER_CONFIRMED"}) is Provenance.USER_CONFIRMED
    assert _road_status({"abutting_road_status": "CERTIFIED_ROW"},
                        {"abutting_road": "UNVERIFIED"}) is Provenance.UNVERIFIED


def test_the_brief_asks_for_the_firms_facilities_as_its_library_states_them():
    asked = {a.name: a for a in brief(_intake_style_project(), amenities=AMENITIES)
             .program.amenities}
    assert list(asked) == [item.name for item in AMENITIES.items]
    assert (asked["PLAY"].use, asked["PLAY"].surface) == (FacilityUse.TOT_LOT, Surface.SOFT)
    assert asked["DECK"].footprint_m == (5.0, 4.0)
    # it may stand on the tot-lot, and its surface was never stated: neither is assumed
    assert (asked["SEATING"].use, asked["SEATING"].surface) == (None, None)
    assert asked["SECURITY CABIN"].surface is None  # a cabin by name only
    assert brief(_intake_style_project()).program.amenities == []


@pytest.fixture(scope="module")
def furnished() -> CandidateLayout:
    option = solve(PLOT, LIBRARY, REQUEST, amenities=AMENITIES)[0]
    return candidate_from_option(
        option, PLOT, candidate_id="made-up-furnished", site_ref="site", rules_ref="rules",
        brief_ref="brief", readings=Readings.of(REQUEST).selections, access_side="S",
        amenities=AMENITIES)


def test_a_placed_facility_carries_what_its_library_states_and_nothing_its_name_suggests(
        furnished):
    stated = {item.name: item for item in AMENITIES.items}
    placed = {a.name: a for a in furnished.program.amenities}
    assert {"PLAY", "DECK", "GUARD ROOM", "SECURITY CABIN"} <= set(placed)
    for name, facility in placed.items():
        assert (facility.use, facility.surface) == (stated[name].use, stated[name].surface)
    assert placed["SECURITY CABIN"].surface is None


def test_a_facilitys_ground_follows_its_stated_surface(furnished):
    ledger = furnished.partition
    assert ledger.problems(Shape.from_shapely(PLOT)) == []
    own = {e.ref: e for e in ledger.entries}
    assert own["GUARD ROOM"].use is PhysicalUse.OTHER_BUILT
    assert own["DECK"].use is PhysicalUse.HARD_AMENITY and own["DECK"].tags == []
    # built by its name, but nobody stated it: an amenity whose surface is not stated
    assert own["SECURITY CABIN"].use is PhysicalUse.HARD_AMENITY
    assert own["SECURITY CABIN"].tags == [SURFACE_UNSTATED]
    # a soft facility is soft ground, on the tot-lot or off it, and is never counted twice
    soft = [e for e in ledger.entries if "AMENITY:PLAY" in e.tags]
    assert len(soft) == 1 and soft[0].use is PhysicalUse.SOFT_OPEN_SPACE


def test_the_firms_margins_reach_the_brief_as_its_standards_and_the_prototype_ignores_them():
    project = Project.model_validate_json(EXAMPLE.read_text())
    defaults = WorkspaceDefaults(design_margins={"setback_extra_m": 0.5,
                                                 "open_space_extra_fraction": 0.005})
    design = brief(project, defaults)
    margins = design.design_margins
    assert margins.setback_extra_m.value == 0.5
    assert margins.setback_extra_m.source_kind is SourceKind.FIRM_STANDARD
    assert margins.setback_extra_m.status is Provenance.USER_CONFIRMED
    assert margins.basis("setback_extra_m") is Basis.FIRM_STANDARD
    assert margins.open_space_target_sqm(1500.0, 0.10) == pytest.approx(1575.0)
    assert margins.tower_gap_extra_m.value == 0.0
    assert margins.basis("tower_gap_extra_m") is Basis.ENGINE_DESIGN_ASSUMPTION
    plain = brief(project)
    assert plain.design_margins.any_set is False
    # the prototype generator plans on the legal minimum: a margin does not change its request
    readings = Readings.of(project.layout)
    assert request(design, readings, project.layout.floors) == request(
        plain, readings, project.layout.floors)
    with pytest.raises(ValidationError):
        WorkspaceDefaults(design_margins={"setbak_extra_m": 1.0})
    with pytest.raises(ValidationError):
        WorkspaceDefaults(design_margins={"setback_extra_m": -1.0})
