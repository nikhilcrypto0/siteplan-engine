"""Checks against the firm's real drawings.

The drawings, the project file and the expected values all live in fixtures/
(gitignored), so no client data is committed. The tests skip on a clean clone.
"""

import json
from pathlib import Path

import pytest
from client_baseline import ANSWERS, FIRM_CASE, PINNED, READINGS, SURVEY, profile_path

from siteplan import rules
from siteplan.area_statement import render
from siteplan.checks import check_site
from siteplan.max_floors import max_floors
from siteplan.pdf_survey import read_pdf_survey
from siteplan.project import Project
from siteplan.units import ft_to_m, sqyd_to_sqm

FIXTURES = Path(__file__).parent.parent / "fixtures"
EXPECTATIONS = FIXTURES / "expectations.json"

pytestmark = pytest.mark.skipif(not EXPECTATIONS.exists(), reason="client fixtures not present")


@pytest.fixture(scope="module")
def expect() -> dict:
    return json.loads(EXPECTATIONS.read_text())


def test_survey_matches_the_surveyors_area(expect):
    survey = read_pdf_survey(FIXTURES / expect["survey_pdf"])
    assert survey.stated_area_sqm == pytest.approx(expect["stated_area_sqm"], abs=0.1)
    assert abs(survey.area_difference_pct) < expect["max_area_difference_pct"]
    assert survey.calibration.snapped_scale == expect["snapped_scale"]
    assert [e.written_m for e in survey.calibration.rejected] == expect["rejected_labels"]
    assert sum(lv.on_site for lv in survey.levels) >= expect["min_on_site_levels"]
    assert survey.terrain().falls_towards == expect["falls_towards"]


def test_every_other_survey_lands_on_its_printed_area(expect):
    """Suchitra's survey has no dimension labels and levels on a local benchmark; the reader
    once returned its sheet frame, 7,239 m², for a plot printed as 8,063.799 m²."""
    for sheet in expect.get("surveys", []):
        survey = read_pdf_survey(FIXTURES / "workspace" / sheet["file"])
        name = sheet["file"]
        assert abs(survey.area_sqm / sheet["printed_sqm"] - 1) * 100 < sheet[
            "max_area_difference_pct"], name
        assert len(survey.boundary.exterior.coords) - 1 >= sheet["min_corners"], name
        assert sum(lv.on_site for lv in survey.levels) >= sheet["min_on_site_levels"], name
        assert survey.terrain().falls_towards == sheet["falls_towards"], name
        assert any(sheet["warning"] in w.lower() for w in survey.warnings), name


def test_area_statement_reproduces_the_drawing(expect):
    project = Project.model_validate_json((FIXTURES / expect["project"]).read_text())
    statement = project.area_statement
    assert [g.with_common_area_sqft for g in statement.groups] == expect["loaded_group_totals_sqft"]
    assert statement.total_sqft == expect["total_sqft"]
    assert expect["rendered_total_line"] in render(statement)


def test_rule_check_statuses(expect):
    project = Project.model_validate_json((FIXTURES / expect["project"]).read_text())
    found = {f.rule: f.status.value for f in check_site(project.to_site())}
    for rule, status in expect["statuses"].items():
        assert found[rule] == status, rule


# The test values set on 30 Sept 2026: unsanctioned fixtures, never evidence for a rule.
DHULAPALLY = FIXTURES / "workspace" / "dhula-assumed.project.json"
SUCHITRA = FIXTURES / "workspace" / "suchitra.project.json"


def _project(path: Path) -> Project:
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    return Project.model_validate_json(path.read_text())


def test_dhulapally_keeps_its_declared_road_apart_from_the_measured_one():
    project = _project(DHULAPALLY)
    site = project.to_site()
    assert site.abutting_road_m == pytest.approx(18.288)
    assert site.measured_carriageway_m == pytest.approx(14.08)
    assert site.abutting_road_status == "DECLARED_ON_SITE_PLAN"
    assert (site.authority, site.inside_cure) == ("CMC", True)
    assert rules.parking_percent(site.authority, site.inside_cure) == rules.PARKING_PERCENT_GHMC
    assert project.site.road_dead_end is None and project.site.site_coordinates is None


@pytest.mark.parametrize("dead_end", [True, False])
def test_dhulapally_is_run_both_ways_on_the_dead_end_nobody_knows(dead_end):
    project = _project(DHULAPALLY)
    limit = max_floors(project.site.net_sqm(), project.to_site().abutting_road_m,
                       dead_end=dead_end)
    nbc_note = any("4.6(b)" in note for note in limit.notes)
    assert nbc_note is dead_end  # the residential 30 m rule speaks only on a dead end
    assert limit.floors_stilt_not_counted == (8 if dead_end else 10)  # 30.15 m on a dead end


def test_suchitra_road_is_a_drawing_value_and_its_floors_only_proposed():
    project = _project(SUCHITRA)
    assert project.site.abutting_road_status == "UNVERIFIED_DRAWING_VALUE"
    assert project.site.abutting_road_m == pytest.approx(12.4)
    assert (project.site.proposed_floors, project.site.sanctioned_floors) == (10, None)
    # the drawings propose stilt + 10 where a 12.4 m road allows stilt + 7 or 8
    limit = max_floors(project.site.net_sqm(), project.site.abutting_road_m)
    assert max(limit.floors_stilt_counted, limit.floors_stilt_not_counted) < 10


# Dhulapally, two runs never mixed (client_baseline.py). BLIND: the raw survey, the architect's
# answers and the firm's standard libraries; it stops and asks until the architect says where the
# 1,160 m² road strip lies. DEBUG: the firm's net outline, fitted onto the survey and tagged
# FIRM_FINISHED_PLAN, stands in for the strip; it carries the regression load, pinned under both
# readings of whether the stilt counts toward the Table IV height.


def _answers() -> dict:
    if not (SURVEY.exists() and ANSWERS.exists()):
        pytest.skip("the Dhulapally survey or its answers are not present")
    return json.loads(ANSWERS.read_text())


def test_dhulapally_blind_run_stops_and_asks_where_the_strip_lies(tmp_path):
    """The engine once cut 1,160 m² off the whole east side at an even 6.6 m, where the firm
    draws a 40 ft road along part of it. It no longer guesses."""
    from siteplan.acceptance import generate

    with pytest.raises(ValueError, match="does not guess a strip's location"):
        generate(SURVEY, _answers(), tmp_path, FIXTURES / "workspace", conservative_parking=True)


def test_dhulapally_blind_run_refuses_the_firms_finished_plan(tmp_path):
    from siteplan.acceptance import generate
    from siteplan.blind import BlindLeak
    from siteplan.profiles import load_profile

    path = profile_path("counted")
    if not path.exists():
        pytest.skip("the debug profile is not present")
    with pytest.raises(BlindLeak):
        generate(SURVEY, _answers(), tmp_path, FIXTURES / "workspace", conservative_parking=True,
                 profile=load_profile(path))
    with pytest.raises(BlindLeak, match="finished plans"):
        generate(FIXTURES / "workspace" / "DULAPALLY_SITE_PLANS.dxf", _answers(), tmp_path,
                 FIXTURES / "workspace", conservative_parking=True)


def test_dhulapally_60_ft_road_allows_30_m_of_rule_height_under_either_reading():
    """The architect confirmed the 60 ft road (2026-10-02). The law gives a height in metres;
    floors follow from the floor heights, and both readings of the stilt are kept open."""
    answers = _answers()
    assert answers["road_row"] == "60 ft"
    assert answers["_status"]["road_row"] == "USER_CONFIRMED"
    assert answers["_source_kind"]["road_row"] == "ARCHITECT"
    limit = max_floors(sqyd_to_sqm(22686), ft_to_m(60), floor_height_m=3.0, stilt_height_m=3.0)
    assert limit.max_height_m == 30
    assert (limit.floors_stilt_counted, limit.floors_stilt_not_counted) == (8, 10)  # 0.15 m raise


def test_the_fitted_net_outline_matches_the_stated_net_and_strip():
    from shapely.geometry import Polygon

    from siteplan.profiles import load_profile
    from siteplan.runner import read_survey

    path = profile_path("counted")
    if not path.exists():
        pytest.skip("the debug profile is not present")
    outline = Polygon(load_profile(path).site["net_plot_m"].value)
    boundary = read_survey(SURVEY).boundary
    assert outline.area == pytest.approx(18968.4, rel=0.001)  # 22,686 sq yd
    assert outline.difference(boundary).area < 0.005 * outline.area
    assert boundary.area - outline.area == pytest.approx(1160, rel=0.03)


@pytest.fixture(scope="module", params=list(READINGS))
def debug_run(request, tmp_path_factory):
    from client_baseline import run

    _answers()
    if not profile_path(request.param).exists():
        pytest.skip("the debug profiles are not present (run tests/client_baseline.py)")
    return request.param, run(request.param, tmp_path_factory.mktemp(request.param))


def test_the_debug_baseline_is_reproduced(debug_run):
    from client_baseline import summarise

    if not PINNED.exists():
        pytest.skip("the debug baseline is not pinned (run tests/client_baseline.py)")
    reading, generated = debug_run
    assert summarise(generated) == json.loads(PINNED.read_text())["readings"][reading]


def test_every_debug_option_passes_and_each_is_a_different_idea(debug_run):
    from siteplan.layout import same_idea

    _, generated = debug_run
    options = generated.found.options
    assert len(options) >= 3
    assert all(not option.fails for option in options)
    assert not any(same_idea(a, b) for i, a in enumerate(options) for b in options[i + 1:])
    for option in options:
        assert option.parking.laid_out_sqm >= option.parking.required_sqm - 0.5
        assert option.open_space_sqm >= 0.10 * generated.plot.area


def test_the_debug_run_says_so_and_never_uses_dhulapallys_own_flats(debug_run):
    from siteplan.acceptance import compare, report
    from siteplan.cases import Case

    _, generated = debug_run
    # A library sized from Dhulapally's own statement would leak the answer into the layout.
    assert "calibrated" not in generated.standards["flat_library"]
    if not FIRM_CASE.exists():
        pytest.skip("the firm's case is not present")
    text = report(generated, compare(generated, Case.model_validate_json(FIRM_CASE.read_text())))
    assert text.startswith("DEBUG RUN")
    for heading in ("0. TEST PROFILE", "1. EXTRACTED FROM THE SURVEY", "Maximum legally allowed",
                    "5. LAYOUTS THAT PASS", "6. REJECTED CANDIDATES",
                    "7. COMPARED WITH THE FIRM'S PLAN", "FROM THE FIRM'S FINISHED PLAN"):
        assert heading in text, heading
    assert "BHADURPALLE" in text  # the place as the survey writes it, not the ward assumed
