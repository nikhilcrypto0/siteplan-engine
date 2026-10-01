"""Starting a project from a raw survey: take what the drawing shows, ask only what it cannot.

All geometry here is made up; the firm's surveys are checked in test_client_fixtures.py.
"""

import json

import ezdxf
import pytest
from shapely.geometry import box

from siteplan.cli import main
from siteplan.geometry import strip_along_side
from siteplan.intake import (
    Draft,
    Mark,
    WorkspaceDefaults,
    _surrender,
    _water,
    build_project,
    extract,
    load_defaults,
    missing,
    questions,
)
from siteplan.provenance import Provenance
from siteplan.roads import Road

ROAD = Road(width_m=14.08, lines_m=(0.0, 7.0, 8.0, 14.08), distance_m=10.5, side="W",
            direction_deg=90.0, sections=20)
ANSWERS = {"main_road": "1", "road_row": "60 ft", "road_row_source": "2", "dead_end": "unknown",
           "surrender": "net 9000 m2, E", "water": "no", "authority": "CMC",
           "inside_cure": "yes", "name": "Test site", "mix": "70% 2BHK, 30% 3BHK",
           "floors": "max", "club_house": "yes"}


def _draft(**changes) -> Draft:
    base = dict(survey="test_survey.pdf", gross_area_sqm=10000.0, written_area_sqm=None,
                on_site_levels=12, roads=(ROAD,), marks=(), line_work=(), place="",
                warnings=())
    return Draft(**base | changes)


@pytest.mark.parametrize(("text", "expected"), [
    ("no", None),
    ("net 22686 sq yd, E", ("net", 18968.4, "E")),
    ("1163 m2 east", ("given", 1163.0, "E")),
    ("given 500 sq m on the north-west", ("given", 500.0, "NW")),
])
def test_land_given_up_is_read_in_the_ways_architects_say_it(text, expected):
    kind, area, side, _ = _surrender(text) or (None, None, None, None)
    if expected is None:
        assert kind is None
    else:
        assert (kind, side) == (expected[0], expected[2])
        assert area == pytest.approx(expected[1], abs=0.1)


def test_land_given_up_needs_an_area():
    with pytest.raises(ValueError, match="net 22686 sq yd"):
        _surrender("the east side")


def test_water_is_named_by_colour_or_layer_and_class():
    assert _water("no") == []
    assert _water("#00ffff nala over 10 m") == [
        {"kind": "nala_over_10m", "survey_colour": "#00FFFF"}]
    assert _water("layer NALA LINE, nala up to 10 m; #0000FF lake under 10 ha") == [
        {"kind": "nala_up_to_10m", "survey_layer": "NALA LINE"},
        {"kind": "lake_under_10ha", "survey_colour": "#0000FF"}]
    with pytest.raises(ValueError, match="class"):
        _water("#00FFFF pond")


def test_only_one_road_is_offered_as_the_default_and_a_width_source_only_for_a_given_width():
    asked = {q.key: q for q in questions(_draft())}
    assert asked["main_road"].default == "1"
    source = asked["road_row_source"]
    assert source.when({"road_row": "60 ft"}) and not source.when({"road_row": "as drawn"})
    two = {q.key: q for q in questions(_draft(roads=(ROAD, ROAD)))}
    assert two["main_road"].default == ""  # the survey cannot say which is the access


def test_a_marked_nala_must_be_answered_and_its_nearest_lines_are_shown_not_chosen():
    nala = Mark("water", "Nala", 5.7, (("#808080", 2.9), ("#00FFFF", 6.9)))
    water = {q.key: q for q in questions(_draft(marks=(nala,)))}["water"]
    assert water.default == ""
    assert "#808080 2.9 m" in water.prompt and "#00FFFF 6.9 m" in water.prompt
    unmarked = {q.key: q for q in questions(_draft())}["water"]
    assert unmarked.default == "no"


def test_the_project_keeps_declared_and_measured_apart_and_says_where_each_came_from():
    project = build_project(_draft(), ANSWERS)
    site = project["site"]
    assert site["abutting_road_ft"] == 60
    assert site["abutting_road_status"] == "DECLARED_ON_SITE_PLAN"
    assert site["measured_carriageway_m"] == pytest.approx(14.08)
    assert (site["net_area_sqm"], site["road_strip_side"]) == (9000.0, "E")
    assert (site["authority"], site["inside_cure"], site["road_dead_end"]) == ("CMC", True, None)
    assert project["sources"]["measured_carriageway_m"].startswith("survey")
    assert project["sources"]["abutting_road"] == "architect: 60 ft"


def test_max_floors_are_worked_out_by_the_engine_not_typed():
    layout = build_project(_draft(), ANSWERS)["layout"]
    assert (layout["floors"], layout["maximise"]) == (9, True)  # a 60 ft road: 30 m
    fixed = build_project(_draft(), ANSWERS | {"floors": "8"})["layout"]
    assert fixed["floors"] == 8 and "maximise" not in fixed


def test_as_drawn_uses_the_survey_width_and_marks_it_unverified():
    site = build_project(_draft(), ANSWERS | {"road_row": "as drawn"})["site"]
    assert site["abutting_road_m"] == pytest.approx(14.08)
    assert site["abutting_road_status"] == "UNVERIFIED_DRAWING_VALUE"


def test_unanswered_questions_are_named_before_anything_is_built():
    answers = {k: v for k, v in ANSWERS.items() if k not in ("road_row", "surrender")}
    problems = missing(_draft(), answers)
    assert {p.split(":")[0] for p in problems} == {"road_row", "surrender"}
    with pytest.raises(ValueError, match="road_row"):
        build_project(_draft(), answers)


def test_the_firms_longest_block_is_a_workspace_default():
    layout = build_project(_draft(), ANSWERS, WorkspaceDefaults(max_tower_length_m=56))["layout"]
    assert layout["max_tower_length_m"] == 56
    assert "max_tower_length_m" not in build_project(_draft(), ANSWERS)["layout"]


def test_workspace_defaults_are_the_firms_libraries_and_heights(tmp_path):
    assert load_defaults(tmp_path) == WorkspaceDefaults()
    (tmp_path / "siteplan.workspace.json").write_text(json.dumps(
        {"flat_library": "flats.json", "amenities": "amenities.json", "floor_height_m": 3.1}))
    defaults = load_defaults(tmp_path)
    assert (defaults.flat_library, defaults.floor_height_m) == ("flats.json", 3.1)


def test_a_strip_named_for_a_side_comes_off_that_side_at_the_width_given():
    plot = box(0, 0, 100, 60)
    east = strip_along_side(plot, "E", 12.0)
    assert east.bounds[2] == pytest.approx(88) and east.area == pytest.approx(88 * 60)
    north = strip_along_side(plot, "N", 10.0)
    assert north.bounds[3] == pytest.approx(50)


@pytest.mark.parametrize(("answer", "side", "width"), [
    ("net 22686 sq yd, E, 40 ft", "E", 12.192),
    ("1163 m2 east 12.2 m", "E", 12.2),
    ("net 22686 sq yd, E", "E", None),  # no width: where the strip lies stays open
])
def test_the_surrender_answer_carries_the_strips_side_and_width(answer, side, width):
    from siteplan.intake import _surrender

    _, _, got_side, got_width = _surrender(answer)
    assert got_side == side
    assert got_width == (pytest.approx(width) if width else None)


def test_a_strip_with_no_width_is_recorded_as_unverified():
    unknown = build_project(_draft(), ANSWERS | {"surrender": "net 5000 m2, E"})
    assert unknown["status"]["road_strip"] == Provenance.UNVERIFIED
    given = build_project(_draft(), ANSWERS | {"surrender": "net 5000 m2, E, 10 m"})
    assert given["status"]["road_strip"] == Provenance.USER_CONFIRMED
    assert given["site"]["road_strip_width_m"] == 10


def test_every_value_says_how_far_it_can_be_trusted():
    status = build_project(_draft(), ANSWERS)["status"]
    assert status["gross_area_sqm"] == Provenance.EXTRACTED
    assert status["measured_carriageway_m"] == Provenance.EXTRACTED
    assert status["access_side"] == Provenance.EXTRACTED  # the chosen road's side, off the survey
    assert status["abutting_road"] == Provenance.USER_CONFIRMED  # declared on the site plan
    assert status["road_dead_end"] == Provenance.UNVERIFIED  # answered 'unknown'
    assert status["street_joins_12m"] == Provenance.UNVERIFIED  # left at its default
    assert status["authority"] == Provenance.USER_CONFIRMED
    assert status["site_coordinates"] == Provenance.UNVERIFIED
    assert status["flat_library"] == Provenance.ASSUMED_FOR_TEST  # the engine's, not the firm's
    certified = build_project(_draft(), ANSWERS | {"road_row_source": "1"})["status"]
    assert certified["abutting_road"] == Provenance.VERIFIED


def test_an_answers_file_can_mark_a_value_unverified_or_assumed_for_a_test():
    marked = ANSWERS | {"_status": {"authority": "UNVERIFIED", "road_row": "ASSUMED_FOR_TEST"}}
    status = build_project(_draft(), marked)["status"]
    assert status["authority"] == Provenance.UNVERIFIED
    assert status["abutting_road"] == Provenance.ASSUMED_FOR_TEST


def test_the_access_side_and_the_street_it_joins_go_into_the_project():
    site = build_project(_draft(), ANSWERS | {"street_join": "yes"})["site"]
    assert site["access_side"] == "W" and site["street_joins_12m"] is True


def test_workspace_standards_set_by_the_firm_are_confirmed_and_the_rest_assumed():
    defaults = WorkspaceDefaults(flat_library="flats.json", max_cellars=2,
                                 status={"floor_height_m": "ASSUMED_FOR_TEST"})
    project = build_project(_draft(), ANSWERS, defaults)
    assert project["layout"]["max_cellars"] == 2
    assert project["status"]["flat_library"] == Provenance.USER_CONFIRMED
    assert project["status"]["floor_height_m"] == Provenance.ASSUMED_FOR_TEST
    assert project["status"]["cellar_floor_height_m"] == Provenance.ASSUMED_FOR_TEST


def _dxf_survey(path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (120, 0), (120, 90), (0, 90)], close=True,
                       dxfattribs={"layer": "SITE-BOUNDARY"})
    msp.add_text("AREA: 10800 SQ.MTS", height=2).set_placement((10, -10))
    msp.add_text("ROAD WIDENING", height=2, dxfattribs={"layer": "RW"}).set_placement((50, 95))
    msp.add_line((60, -5), (60, 95), dxfattribs={"layer": "NALA"})
    msp.add_text("NALA", height=2, dxfattribs={"layer": "NALA"}).set_placement((61, 45))
    msp.add_text("KOMPALLY (V), QUTHBULLAPUR (M)", height=2).set_placement((10, -20))
    doc.saveas(path)
    return path


def test_extract_finds_marks_the_place_and_line_work_that_may_be_water(tmp_path):
    draft = extract(_dxf_survey(tmp_path / "survey.dxf"))
    assert draft.written_area_sqm == pytest.approx(10800)
    kinds = {m.kind: m for m in draft.marks}
    assert set(kinds) == {"road widening", "water"}
    assert kinds["water"].nearby == (("NALA", 0.0),)  # a DXF label's own layer
    assert "QUTHBULLAPUR (M)" in draft.place
    assert [(g.key, g.crosses_plot) for g in draft.line_work] == [("NALA", True)]


def test_start_turns_a_survey_and_answers_into_a_project_file(tmp_path, capsys):
    survey = _dxf_survey(tmp_path / "survey.dxf")
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(ANSWERS | {"main_road": "E", "surrender": "no",
                                             "water": "layer NALA, nala up to 10 m"}))
    out = tmp_path / "test.project.json"
    assert main(["start", str(survey), "--answers", str(answers), "--out", str(out)]) == 0
    project = json.loads(out.read_text())
    assert project["site"]["water"] == [{"kind": "nala_up_to_10m", "survey_layer": "NALA"}]
    assert project["layout"]["maximise"] is True
    assert "Wrote" in capsys.readouterr().out
    assert main(["start", str(survey), "--answers", str(answers), "--out", str(out)]) == 1
