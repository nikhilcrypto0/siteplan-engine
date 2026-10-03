"""The prototype's types convert to the contracts and back without changing a number the engine
uses, and a legacy layout option becomes a candidate that gives the chat tool the same reply."""

import dataclasses
import json
from pathlib import Path

import pytest
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
from siteplan.contracts import CandidateLayout
from siteplan.contracts.accounting import LayerKind, Permit, PhysicalUse
from siteplan.contracts.common import Provenance, Shape, SourceKind
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.mcp_server import OPTION_KEYS
from siteplan.project import Project

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
