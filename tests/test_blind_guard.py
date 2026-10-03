"""Blind acceptance never sees the firm's finished plan (blind.py), and stops and asks rather
than guess where a road strip lies. Made-up survey and workspace; the Dhulapally checks are in
test_client_fixtures.py."""

import json
from pathlib import Path

import ezdxf
import pytest

from siteplan.acceptance import generate
from siteplan.blind import BlindLeak, blind_leaks, check
from siteplan.profiles import AssumptionProfile

EXAMPLES = Path(__file__).parent.parent / "examples"
ANSWERS = {"main_road": "W", "road_row": "60 ft", "road_row_source": "2", "surrender": "no",
           "authority": "HMDA", "inside_cure": "no", "name": "Blind test",
           "mix": "70% 2BHK, 30% 3BHK", "floors": "8"}
OUTLINE = [(0, 0), (150, 0), (150, 120), (0, 120)]


def _workspace(tmp_path, finished_plans=()) -> Path:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_lwpolyline(OUTLINE, close=True, dxfattribs={"layer": "SITE-BOUNDARY"})
    doc.modelspace().add_text("AREA: 18000 SQ.MTS", height=2).set_placement((10, -10))
    doc.saveas(tmp_path / "survey.dxf")
    (tmp_path / "siteplan.workspace.json").write_text(json.dumps(
        {"flat_library": str(EXAMPLES / "flat_library.example.json"),
         "finished_plans": list(finished_plans)}))
    return tmp_path


def _profile(debug: bool = False, kind: str = "TEST_PROFILE") -> AssumptionProfile:
    return AssumptionProfile.model_validate({
        "name": "made-up", "purpose": "leak test", "debug_fixture": debug,
        "site": {"net_plot_m": {"value": OUTLINE, "source": "the firm's site plan",
                                "source_kind": kind}}})


def test_a_blind_run_refuses_a_debug_profile(tmp_path):
    ws = _workspace(tmp_path)
    with pytest.raises(BlindLeak, match="debug fixture"):
        generate(ws / "survey.dxf", ANSWERS, ws / "out", profile=_profile(debug=True))
    assert not (ws / "out" / "project.json").exists(), "nothing may be written"


def test_a_blind_run_refuses_a_profile_value_from_the_finished_plan(tmp_path):
    ws = _workspace(tmp_path)
    with pytest.raises(BlindLeak, match="site.net_plot_m"):
        generate(ws / "survey.dxf", ANSWERS, ws / "out",
                 profile=_profile(kind="FIRM_FINISHED_PLAN"))


def test_a_blind_run_refuses_an_answer_from_the_finished_plan(tmp_path):
    ws = _workspace(tmp_path)
    answers = ANSWERS | {"_source_kind": {"road_row": "FIRM_FINISHED_PLAN"}}
    with pytest.raises(BlindLeak, match="road_row"):
        generate(ws / "survey.dxf", answers, ws / "out")


def test_a_blind_run_refuses_the_finished_plan_as_its_survey(tmp_path):
    ws = _workspace(tmp_path, finished_plans=["survey.dxf"])
    with pytest.raises(BlindLeak, match="finished plans"):
        generate(ws / "survey.dxf", ANSWERS, ws / "out")


def test_a_debug_run_may_use_the_finished_plan_but_must_say_so():
    leaks = blind_leaks(Path("plan.dxf"), {}, _profile(debug=True, kind="FIRM_FINISHED_PLAN"),
                        ["plan.dxf"])
    assert len(leaks) == 3
    check("debug", Path("plan.dxf"), {}, _profile(debug=True), ["plan.dxf"])  # no error
    with pytest.raises(ValueError, match="mode"):
        check("acceptance", Path("plan.dxf"), {})


def test_an_ordinary_test_profile_is_not_a_leak(tmp_path):
    assert blind_leaks(Path("survey.dxf"), ANSWERS, _profile()) == []


def test_a_blind_run_stops_and_asks_when_the_strip_cannot_be_placed(tmp_path):
    """The net area is less than the survey's, and nobody has said where the strip lies."""
    ws = _workspace(tmp_path)
    with pytest.raises(ValueError, match="does not guess"):
        generate(ws / "survey.dxf", ANSWERS | {"surrender": "net 17000 m2"}, ws / "out")
