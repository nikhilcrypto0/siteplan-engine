"""Checks against the firm's real drawings.

The drawings, the project file and the expected values all live in fixtures/
(gitignored), so no client data is committed. The tests skip on a clean clone.
"""

import json
from pathlib import Path

import pytest

from siteplan.area_statement import render
from siteplan.checks import check_site
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
