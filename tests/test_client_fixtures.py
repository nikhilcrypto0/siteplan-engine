"""Checks against the firm's real drawings.

The drawings, the project file and the expected values all live in fixtures/
(gitignored), so no client data is committed. The tests skip on a clean clone.
"""

import json
from pathlib import Path

import pytest

from siteplan import rules
from siteplan.area_statement import render
from siteplan.checks import check_site
from siteplan.max_floors import max_floors
from siteplan.pdf_survey import read_pdf_survey
from siteplan.project import Project

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
    assert limit.floors_stilt_not_counted == (9 if dead_end else 10)


def test_suchitra_road_is_a_drawing_value_and_its_floors_only_proposed():
    project = _project(SUCHITRA)
    assert project.site.abutting_road_status == "UNVERIFIED_DRAWING_VALUE"
    assert project.site.abutting_road_m == pytest.approx(12.4)
    assert (project.site.proposed_floors, project.site.sanctioned_floors) == (10, None)
    # the drawings propose stilt + 10 where a 12.4 m road allows stilt + 7 or 8
    limit = max_floors(project.site.net_sqm(), project.site.abutting_road_m)
    assert max(limit.floors_stilt_counted, limit.floors_stilt_not_counted) < 10


# The acceptance run, kept as the permanent regression test: the raw survey and the answers in,
# the firm's plan read only to compare. The same path `siteplan acceptance` runs.
SURVEY = FIXTURES / "workspace" / "dhulapally_survey.pdf"
ANSWERS = FIXTURES / "acceptance" / "dhulapally.answers.json"
FIRM_CASE = FIXTURES / "cases" / "dhulapally.case.json"


@pytest.fixture(scope="module")
def dhulapally_run(tmp_path_factory):
    from siteplan.acceptance import generate

    if not (SURVEY.exists() and ANSWERS.exists()):
        pytest.skip("the Dhulapally survey or its answers are not present")
    out = tmp_path_factory.mktemp("acceptance")
    return generate(SURVEY, json.loads(ANSWERS.read_text()), out, FIXTURES / "workspace")


def test_dhulapally_from_the_survey_alone_finds_the_height_the_law_and_the_ground_allow(
        dhulapally_run):
    found = dhulapally_run.found
    top = found.results[0]
    assert (top.floors, top.verdict) == (10, "FAIL (law)")  # a 60 ft road stops at 30 m
    assert "Abutting road width" in top.reasons()[0]
    assert found.max_legal_floors == 9
    assert found.max_feasible_floors is not None and found.max_feasible_floors <= 9


def test_dhulapally_offers_three_different_layouts_that_pass_every_rule(dhulapally_run):
    from siteplan.layout import same_idea

    options = dhulapally_run.found.options
    assert len(options) >= 3
    assert all(not option.fails for option in options)
    assert not any(same_idea(a, b) for i, a in enumerate(options) for b in options[i + 1:])
    for option in options:
        assert option.parking.laid_out_sqm >= option.parking.required_sqm - 0.5
        assert option.open_space_sqm >= 0.10 * dhulapally_run.plot.area


def test_dhulapally_is_generated_without_its_own_flats_or_plan(dhulapally_run):
    # A library sized from Dhulapally's own statement would leak the answer into the layout.
    assert "calibrated" not in dhulapally_run.standards["flat_library"]
    assert not any(path.suffix == ".dxf" and "SITE_PLAN" in path.name.upper()
                   for path in dhulapally_run.out.iterdir())


def test_dhulapally_report_carries_every_section_and_the_comparison(dhulapally_run):
    from siteplan.acceptance import compare, report
    from siteplan.cases import Case

    if not FIRM_CASE.exists():
        pytest.skip("the firm's case is not present")
    rows = compare(dhulapally_run, Case.model_validate_json(FIRM_CASE.read_text()))
    text = report(dhulapally_run, rows)
    for heading in ("1. EXTRACTED FROM THE SURVEY", "2. INPUTS AND HOW FAR EACH IS TRUSTED",
                    "3. UNRESOLVED FACTS AND ASSUMPTIONS", "Maximum legally allowed",
                    "Maximum geometrically feasible", "5. LAYOUTS THAT PASS",
                    "6. REJECTED CANDIDATES", "7. COMPARED WITH THE FIRM'S PLAN"):
        assert heading in text, heading
    assert "BHADURPALLE" in text  # the place as the survey writes it, not the ward assumed
