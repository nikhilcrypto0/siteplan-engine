"""The architect's steps for any project (`siteplan steps`): step 1 copies the survey, step 3
takes off the land given up for road widening, and every step's report answers the same five
questions. Made-up land only."""

import json

import ezdxf
import pytest
from shapely.geometry import Polygon

from siteplan import rules
from siteplan.blind import BlindLeak
from siteplan.cli import main
from siteplan.steps import carried, road_widening_report, survey_copy_report
from siteplan.steps.drawing import frame
from siteplan.steps.inputs import from_answers, from_project
from siteplan.steps.road_widening import take_off
from siteplan.steps.run import run_steps
from siteplan.steps.survey_copy import ALONG, APART, CARRIED, ENDS, copy_survey

TEST_CLASS = "normative"

# A 120 x 90 m plot (10,800 m², as written on the sheet); the reader keeps its corner at (0, 0).
PLOT = [(0, 0), (120, 0), (120, 90), (0, 90)]


def _survey(path, *, south=True, east=True, far=True, short_road=False, west_road=False,
            south_along=False, sump=False, detour=False, nala_x=-12.0, extras=False):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_lwpolyline(PLOT, close=True, dxfattribs={"layer": "SITE-BOUNDARY"})
    msp.add_text("AREA: 10800 SQ.MTS", height=2).set_placement((10, -60))
    road = {"layer": "ROAD"}
    if south:  # 9 m wide, running south from the plot and ending at it
        msp.add_lwpolyline([(50, -40), (50, 0)], dxfattribs=road)
        msp.add_lwpolyline([(59, -40), (59, 0)], dxfattribs=road)
    if east:  # 12 m wide, running north-south along the east side, half a metre off it
        msp.add_lwpolyline([(120.5, -30), (120.5, 120)], dxfattribs=road)
        msp.add_lwpolyline([(132.5, -30), (132.5, 120)], dxfattribs=road)
    if far:  # 7 m wide, 25 m off the west side
        msp.add_lwpolyline([(-25, -30), (-25, 120)], dxfattribs=road)
        msp.add_lwpolyline([(-32, -30), (-32, 120)], dxfattribs=road)
    if short_road:  # its straight edges stop 6 m short of the north side; one bends in to it
        msp.add_lwpolyline([(30, 136), (30, 96)], dxfattribs=road)
        msp.add_lwpolyline([(39, 136), (39, 96), (37, 90)], dxfattribs=road)
    if detour:  # stops 6 m short of the north side; one edge line runs off and touches the
        # plot 70 m away from the road
        msp.add_lwpolyline([(30, 136), (30, 96)], dxfattribs=road)
        msp.add_lwpolyline([(39, 96), (39, 136), (110, 136), (110, 90)], dxfattribs=road)
    if west_road:  # 7 m wide, along the west side, half a metre off it
        msp.add_lwpolyline([(-0.5, -40), (-0.5, 120)], dxfattribs=road)
        msp.add_lwpolyline([(-7.5, -40), (-7.5, 120)], dxfattribs=road)
    if south_along:  # 12 m wide, along the south side, half a metre off it
        msp.add_lwpolyline([(-40, -0.5), (150, -0.5)], dxfattribs=road)
        msp.add_lwpolyline([(-40, -12.5), (150, -12.5)], dxfattribs=road)
    msp.add_lwpolyline([(nala_x, -20), (nala_x, 110)], dxfattribs={"layer": "NALA"})
    if sump:
        msp.add_lwpolyline([(80, 60), (84, 60), (84, 64), (80, 64)], close=True,
                           dxfattribs={"layer": "NALA"})
    for x, y, z in ((20, 20, 500.4), (100, 20, 500.0), (60, 70, 501.0), (20, 80, 501.2),
                    (54.5, -3, 499.8), (54.5, -8, 499.6)):
        msp.add_point((x, y, z))
    if extras:  # notes near the plot, and lines the engine cannot name
        msp.add_text("ROAD WIDENING", height=1.5).set_placement((70, -5))
        msp.add_text("HT LINE", height=1.5).set_placement((125, 45))
        msp.add_lwpolyline([(10, -10), (10, 100)], dxfattribs={"layer": "POWER"})
        msp.add_lwpolyline([(-20, 0), (-20, 90)], dxfattribs={"layer": "DRAIN"})
    msp.add_text("BORE", height=1.5).set_placement((30, 30))
    msp.add_text("BORE", height=1.5).set_placement((90, 30))
    msp.add_text("SHED", height=1.5).set_placement((60, -6))
    doc.saveas(path)
    return path


def _project(path, **site):
    base = {"abutting_road_m": 9.0, "abutting_road_status": "DECLARED_ON_SITE_PLAN",
            "access_side": "S", "measured_carriageway_m": 9.0, "road_dead_end": False,
            "authority": "HMDA", "inside_cure": False,
            "water": [{"kind": "nala_up_to_10m", "survey_layer": "NALA"}]}
    project = {"name": "Made-up plot", "site": {**base, **site},
               "sources": {"abutting_road": "architect: 9 m"},
               "status": {"abutting_road": "USER_CONFIRMED"},
               "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}}}
    path.write_text(json.dumps(project))
    return path


def _inputs(tmp_path, survey=None, **site):
    survey = survey or _survey(tmp_path / "survey.dxf")
    return from_project(survey, _project(tmp_path / "made-up.project.json", **site), tmp_path)


# --- Step 1: copy the survey ------------------------------------------------------------------


def test_step_one_copies_the_plot_checks_its_area_and_lists_its_sides(tmp_path):
    copy = copy_survey(_inputs(tmp_path))
    assert copy.drawn_sqm == pytest.approx(10_800) and copy.written_sqm == pytest.approx(10_800)
    assert [round(s.drawn_m) for s in copy.sides] == [120, 90, 120, 90]
    assert {s.faces for s in copy.sides} == {"north", "south", "east", "west"}
    assert all(s.written_m is None for s in copy.sides)  # a DXF writes no side lengths
    assert copy.terrain.lowest == pytest.approx(500.0) and copy.levels == (4, 2)


def test_step_one_finds_how_each_road_meets_the_plot_and_its_level_there(tmp_path):
    copy = copy_survey(_inputs(tmp_path))
    by_side = {r.lies: r for r in copy.roads}
    south, east, west = by_side["south"], by_side["east"], by_side["west"]
    assert south.meets == ENDS and south.frontage_m == pytest.approx(9.0, abs=0.1)
    assert south.level[1] == pytest.approx(499.7)  # the levels drawn on the road, not the plot
    assert east.meets == ALONG and east.frontage_m == pytest.approx(90.0, abs=0.5)
    assert west.meets == APART and west.frontage_m == 0.0


def test_a_road_whose_edges_stop_short_is_taken_on_when_one_of_its_lines_touches(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", short_road=True)
    copy = copy_survey(_inputs(tmp_path, survey))
    north = next(r for r in copy.roads if r.lies == "north")
    assert north.meets == CARRIED and north.carried_m == pytest.approx(6.0, abs=0.1)
    assert north.frontage_m == pytest.approx(9.0, abs=0.2)
    report = survey_copy_report.report(copy).markdown()
    assert "taken on in its own direction to the plot" in report  # said, never silent


def test_the_access_road_carries_the_legal_width_the_answers_give_with_its_source(tmp_path):
    copy = copy_survey(_inputs(tmp_path))
    assert copy.access.lies == "south" and copy.access.legal_width_m == pytest.approx(9.0)
    assert "architect: 9 m" in copy.access.legal_source
    other = copy_survey(_inputs(tmp_path, measured_carriageway_m=14.0))
    assert other.access is None  # no road of that width meets the plot: not guessed


def test_inside_the_plot_is_listed_and_ignored_and_the_12_m_band_is_reported(tmp_path):
    copy = copy_survey(_inputs(tmp_path, _survey(tmp_path / "survey.dxf", sump=True)))
    assert copy.inside == [("BORE", 2)] and ("SHED", 1) in copy.outside
    assert copy.water == [("nala_up_to_10m", pytest.approx(12.0))]  # the sump is not water
    text = survey_copy_report.report(copy).markdown()
    assert rules.SITE_PLAN_NEIGHBOUR_BAND_CLAUSE in text


def test_a_scale_taken_from_the_written_area_is_said_to_be_no_check(tmp_path):
    copy = copy_survey(_inputs(tmp_path))
    assert copy.scale_is_a_check  # a DXF's own unit
    copy.scale_is_a_check = False
    report = survey_copy_report.report(copy)
    assert any("no check" in line for line in report.output)
    assert any("confirm one side's length" in q for q in report.questions)


# --- Step 3: road widening --------------------------------------------------------------------


def test_step_three_stops_and_asks_when_nobody_has_said_where_the_land_given_up_lies(tmp_path):
    inputs = _inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_200, road_strip_side="S")
    widening = take_off(inputs, copy_survey(inputs))
    assert widening.stopped and widening.net is None
    report = road_widening_report.report(widening)
    assert report.stopped and "Where does the land given up lie?" in report.questions[0]


def test_step_three_takes_off_the_strip_the_architect_places_and_shows_its_rewards(tmp_path):
    inputs = _inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_200, road_strip_side="S",
                     road_strip_width_m=5.0)
    widening = take_off(inputs, copy_survey(inputs))
    assert widening.net.area == pytest.approx(10_200)
    piece, = widening.pieces
    assert piece.counted and piece.lies == "south" and piece.area_sqm == pytest.approx(600)
    assert widening.given_sqm == pytest.approx(600)
    facts = road_widening_report.facts(widening)
    rewards = facts["rewards_shown_not_taken"]
    assert rewards["tdr_built_up_sqm"] == pytest.approx(rules.TDR_ROAD_SURRENDER_SHARE * 600)
    text = road_widening_report.report(widening).markdown()
    assert rules.ROAD_SURRENDER_REWARDS_CLAUSE in text and "none is taken" in text


def test_land_between_two_outlines_is_road_land_only_where_it_is_wide_and_beside_a_road(
        tmp_path):
    """A net outline 0.2 m in from the north side (a drawing difference), 5 m in from the south
    (the strip, on the side the answers name) and 3 m in from the west (beside no road)."""
    net = [(3, 5), (120, 5), (120, 89.8), (3, 89.8)]
    inputs = _inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=Polygon(net).area,
                     road_strip_side="S", net_plot_m=net)
    widening = take_off(inputs, copy_survey(inputs))
    counted = [p for p in widening.pieces if p.counted]
    assert [p.lies for p in counted] == ["south"]
    west = next(p for p in widening.pieces if p.lies == "west")
    assert not west.counted and west.why is None
    assert widening.slivers.area == pytest.approx(117 * 0.2, rel=0.05)
    assert widening.difference_sqm == pytest.approx(west.area_sqm + widening.slivers.area)


def test_a_corner_where_two_roads_meet_is_splayed_by_the_wider_road_and_never_taken(tmp_path):
    """A 12 m road along the south side and a 7 m one along the west meet at the south-west
    corner; no other corner has two roads."""
    survey = _survey(tmp_path / "survey.dxf", south=False, east=False, far=False,
                     west_road=True, south_along=True)
    inputs = _inputs(tmp_path, survey)
    copy = copy_survey(inputs)
    names = {r.lies: r.name for r in copy.roads}
    widening = take_off(inputs, copy)
    splay, = widening.splays
    assert splay.lies == "south-west" and set(splay.roads) == {names["south"], names["west"]}
    assert splay.legs_m == (3.0, 4.5)  # the wider road is 12 m: in neither row, both legs
    assert "drawn width" in splay.width_from  # no legal width given: said so
    assert widening.net.area == pytest.approx(10_800)  # shown, never taken off


def test_the_splay_rows_and_the_12_m_road_that_falls_between_them():
    assert rules.junction_splay_legs_m(9.0) == (3.0,)
    assert rules.junction_splay_legs_m(12.0) == (3.0, 4.5)
    assert rules.junction_splay_legs_m(40 * 0.3048) == (3.0, 4.5)  # 40 ft is reckoned 12 m
    assert rules.junction_splay_legs_m(18.0) == (4.5,)
    assert rules.junction_splay_legs_m(24.0) == (4.5,)
    assert rules.junction_splay_legs_m(30.0) == (6.0,)


# --- The reports and the command --------------------------------------------------------------


FIVE = ("## 1. What I did", "## 2. What is happening", "## 3. What it looks at",
        "## 4. Rules used, and where each one comes from", "## 5. Final output")


def test_every_step_report_answers_the_five_questions_and_names_what_the_engine_chose(tmp_path):
    reports = run_steps(_inputs(tmp_path), tmp_path / "out")
    assert [r.number for r in reports] == [1, 3]
    for n in (1, 3):
        text = (tmp_path / "out" / f"step{n}" / "REPORT.md").read_text()
        assert all(heading in text for heading in FIVE), n
        assert "Not rules: what the engine decided by itself" in text
        for name in (f"step{n}.svg", f"step{n}.dxf", f"step{n}.json"):
            assert (tmp_path / "out" / f"step{n}" / name).exists()
    index = (tmp_path / "out" / "README.md").read_text()
    assert all(f"| {n} |" in index for n in range(1, 8)) and "a later stage" in index
    assert json.loads((tmp_path / "out" / "step3" / "step3.json").read_text())["net_plot"]


def test_a_blind_run_refuses_a_value_taken_from_the_firms_finished_plan(tmp_path):
    survey = _survey(tmp_path / "survey.dxf")
    project = json.loads(_project(tmp_path / "p.json").read_text())
    project["source_kinds"] = {"net_plot_m": "FIRM_FINISHED_PLAN"}
    (tmp_path / "p.json").write_text(json.dumps(project))
    with pytest.raises(BlindLeak):
        from_project(survey, tmp_path / "p.json", tmp_path)
    assert from_project(survey, tmp_path / "p.json", tmp_path, mode="debug").mode == "debug"


def test_the_command_writes_every_step_and_exits_1_when_one_stopped_to_ask(tmp_path, capsys):
    survey = _survey(tmp_path / "survey.dxf")
    done = _project(tmp_path / "done.json")
    assert main(["steps", str(survey), "--project", str(done), "--out",
                 str(tmp_path / "a")]) == 0
    asks = _project(tmp_path / "asks.json", gross_area_sqm=10_800, net_area_sqm=10_200,
                    road_strip_side="S")
    assert main(["steps", str(survey), "--project", str(asks), "--out",
                 str(tmp_path / "b")]) == 1
    assert "STOPPED" in capsys.readouterr().out


# --- What the review found ----------------------------------------------------------------------


def test_land_the_architect_outlines_is_all_given_up_even_with_no_road_beside_it(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", east=False)
    strip = [(0, 85), (120, 85), (120, 90), (0, 90)]
    inputs = _inputs(tmp_path, survey, gross_area_sqm=10_800, net_area_sqm=10_200,
                     road_strip_m=strip)
    widening = take_off(inputs, copy_survey(inputs))
    assert widening.given_sqm == pytest.approx(600) and widening.difference_sqm == 0
    assert widening.adds_up and widening.high_rise_plot is True
    text = road_widening_report.report(widening).markdown()
    assert "where the strip is placed" in text and "none is taken" in text


def test_land_left_out_on_a_side_with_no_road_and_no_name_is_not_land_given_up(tmp_path):
    """A net outline 3 m in from the north side only. The east road runs past the north-east
    corner, but along the east side, not the north."""
    net = [(0, 0), (120, 0), (120, 87), (0, 87)]
    inputs = _inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_440, net_plot_m=net)
    widening = take_off(inputs, copy_survey(inputs))
    north, = widening.pieces
    assert north.lies == "north" and not north.counted
    assert not widening.adds_up  # the answers give up 360 m²; none is counted
    report = road_widening_report.report(widening)
    assert any("Which is right?" in q for q in report.questions)
    assert "NOT counted as land given up" in report.markdown()


def test_a_strip_and_the_road_it_widens_make_no_corner_cut(tmp_path):
    inputs = _inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_350, road_strip_side="E",
                     road_strip_width_m=5.0)
    widening = take_off(inputs, copy_survey(inputs))
    piece, = widening.pieces
    east = next(r for r in widening.copy.roads if r.lies == "east")
    assert piece.widens == (east.name,) and widening.splays == ()


def test_a_stopped_step_says_only_what_it_did_and_asks_what_would_let_it_go_on(tmp_path):
    unplaced = _inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_200, road_strip_side="S")
    report = road_widening_report.report(take_off(unplaced, copy_survey(unplaced)))
    assert len(report.did) == 2 and "stopped" in report.did[1]
    assert report.questions[0].startswith("Where does the land given up lie?")
    wrong = _inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_200, road_strip_side="E",
                    road_strip_width_m=3.0)  # takes 270 m², not 600
    report = road_widening_report.report(take_off(wrong, copy_survey(wrong)))
    assert "does not come to the area" in report.questions[0]


def test_a_broken_or_misplaced_outline_stops_with_a_question(tmp_path):
    crossed = _inputs(tmp_path, net_plot_m=[(0, 0), (120, 90), (120, 0), (0, 90)])
    widening = take_off(crossed, copy_survey(crossed))
    assert widening.stopped and "crosses itself" in widening.stopped
    elsewhere = _inputs(tmp_path, net_plot_m=[(500, 500), (620, 500), (620, 590), (500, 590)])
    widening = take_off(elsewhere, copy_survey(elsewhere))
    assert widening.stopped and "does not sit on the survey" in widening.stopped


def test_named_water_the_survey_does_not_draw_is_said_and_asked(tmp_path):
    inputs = _inputs(tmp_path, water=[{"kind": "nala_over_10m", "survey_layer": "CANAL"}])
    assert inputs.water_missing == ("nala over 10m (layer CANAL)",)
    report = survey_copy_report.report(copy_survey(inputs))
    assert any("NOT drawn on the survey" in line for line in report.output)
    assert any("Where is it drawn?" in q for q in report.questions)


def test_the_water_the_project_names_is_not_among_the_lines_the_engine_cannot_name(tmp_path):
    copy = copy_survey(_inputs(tmp_path))
    assert "NALA" not in {g.key.upper() for g in (*copy.inside_lines, *copy.near_lines)}


def test_a_cad_survey_is_not_said_to_have_its_side_lengths_checked(tmp_path):
    report = survey_copy_report.report(copy_survey(_inputs(tmp_path)))
    assert "the side lengths" not in report.did[1]
    assert any("CAD drawing, so none were checked" in line for line in report.output)


def test_a_road_is_taken_on_only_when_its_own_line_touches_the_plot_near_its_end(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", detour=True)
    north = next(r for r in copy_survey(_inputs(tmp_path, survey)).roads if r.lies == "north")
    assert north.meets == APART


def test_answers_name_the_access_road_by_the_number_step_1_gives_it(tmp_path):
    survey = _survey(tmp_path / "survey.dxf")
    south = next(r for r in copy_survey(_inputs(tmp_path, survey)).roads if r.lies == "south")
    answers = {"main_road": south.name[1:], "road_row": "30 ft", "road_row_source": "2",
               "dead_end": "no", "surrender": "no", "water": "no", "authority": "HMDA",
               "inside_cure": "no", "name": "Made-up plot", "mix": "100% 2BHK",
               "floors": "4", "club_house": "no"}
    copy = copy_survey(from_answers(survey, answers, tmp_path))
    assert copy.access.name == south.name
    assert copy.access.legal_width_m == pytest.approx(30 * 0.3048)
    leaked = {**answers, "_source_kind": {"surrender": "FIRM_FINISHED_PLAN"}}
    with pytest.raises(BlindLeak):
        from_answers(survey, leaked, tmp_path)


def test_a_profile_goes_with_answers_only(tmp_path, capsys):
    survey = _survey(tmp_path / "survey.dxf")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"name": "made-up"}))
    assert main(["steps", str(survey), "--project", str(_project(tmp_path / "p.json")),
                 "--profile", str(profile), "--out", str(tmp_path / "o")]) == 2


def test_step_three_carries_the_water_and_its_buffer_on_with_the_net_plot(tmp_path):
    """A nala wider than 10 m along the west side: its 9 m buffer keeps 9 x 90 m of the net plot
    free of building from step 4 on; nothing is taken off, and the later steps get its lines."""
    survey = _survey(tmp_path / "survey.dxf", nala_x=0.0)
    inputs = _inputs(tmp_path, survey, water=[{"kind": "nala_over_10m", "survey_layer": "NALA"}])
    widening = take_off(inputs, copy_survey(inputs))
    water, = widening.water
    assert water.buffer_m == rules.WATER_BUFFER_M["nala_over_10m"]
    assert water.kept_free.area == pytest.approx(9 * 90, rel=0.01)
    assert widening.net.area == pytest.approx(10_800)  # never taken off
    facts = road_widening_report.facts(widening)
    assert facts["water"][0]["lines_m"] and facts["water"][0]["buffer_m"] == 9.0
    report = road_widening_report.report(widening)
    assert rules.WATER_BUFFER_2012_CLAUSE in report.markdown()
    assert any("Is the water really a nala over 10m?" in q for q in report.questions)
    assert any(layer.name == "WATER" for layer in road_widening_report.picture(widening).layers)


def test_water_drawn_off_the_plot_is_measured_both_ways_and_asked(tmp_path):
    """The nala's line is drawn 8 m off the west side. Measured from that line its 9 m buffer
    reaches 1 m into the plot; if the 8 m between is the nala itself, it starts at the plot's
    edge and reaches 9 m in. Both are shown and the architect is asked."""
    survey = _survey(tmp_path / "survey.dxf", nala_x=-8.0)
    inputs = _inputs(tmp_path, survey, water=[{"kind": "nala_over_10m", "survey_layer": "NALA"}])
    widening = take_off(inputs, copy_survey(inputs))
    water, = widening.water
    assert water.kept_free.area == pytest.approx(1 * 90, rel=0.02)
    assert water.edge_kept_free.area == pytest.approx(9 * 90, rel=0.02)
    questions = road_widening_report.report(widening).questions
    assert any("boundary: at the line the survey draws, or at the plot's own edge" in q
               for q in questions)


def test_everything_step_1_finds_is_carried_by_step_3_in_its_report_facts_and_picture(tmp_path):
    """The guard added after step 3 first left a nala out: every road, water body, note near
    the plot and unnamed line step 1 finds has a row in step 3's report, an entry in its facts
    and, when it has a shape, a place in its picture."""
    survey = _survey(tmp_path / "survey.dxf", nala_x=0.0, extras=True)
    inputs = _inputs(tmp_path, survey, water=[{"kind": "nala_over_10m", "survey_layer": "NALA"}])
    copy = copy_survey(inputs)
    items = carried.found_in(copy)
    assert {i.kind for i in items} == {carried.ROAD, carried.WATER, carried.MARK,
                                       carried.UNNAMED}
    assert [c["key"] for c in survey_copy_report.facts(copy)["carried"]] == [i.key for i in items]
    widening = take_off(inputs, copy)
    text = road_widening_report.report(widening).markdown()
    assert all(i.what in text for i in items)
    assert [c["key"] for c in road_widening_report.facts(widening)["carried"]] == [
        i.key for i in items]
    picture = road_widening_report.picture(widening)
    drawn = [g for layer, g in picture.shapes if layer in ("ROADS", "WATER")]
    view = frame(copy.plot, road_widening_report.DRAWN_AROUND_M)
    for i in items:
        if i.shape is not None and not i.shape.intersection(view).is_empty:
            assert any(g.intersects(i.shape) for g in drawn), i.key


def test_a_step_that_stops_still_carries_everything_step_1_found(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", extras=True)
    inputs = _inputs(tmp_path, survey, gross_area_sqm=10_800, net_area_sqm=10_200,
                     road_strip_side="S")
    copy = copy_survey(inputs)
    report = road_widening_report.report(take_off(inputs, copy))
    assert report.stopped
    text = report.markdown()
    assert all(i.what in text for i in carried.found_in(copy))
    assert "carried unchanged (this step stopped)" in text


def test_a_river_shows_both_of_its_2012_figures_and_asks_which(tmp_path):
    """G.O.168 (2012) gives a river 100 m outside municipal limits and 50 m within; the engine is
    not told which, so step 3 draws no buffer for it and asks."""
    survey = _survey(tmp_path / "survey.dxf", nala_x=-5.0)
    inputs = _inputs(tmp_path, survey, water=[{"kind": "river", "survey_layer": "NALA"}])
    widening = take_off(inputs, copy_survey(inputs))
    river, = widening.water
    assert river.buffer_m is None and river.kept_free.is_empty
    report = road_widening_report.report(widening)
    assert any("within municipal limits?" in q for q in report.questions)
    assert "100 m outside municipal limits or 50 m within" in report.markdown()


SEVEN_FILES = {"168", "50", "95", "119"}  # G.O.168/2012, G.O.50/2019, G.O.95/2026, AP G.O.119


def test_every_steps_report_cites_only_the_architects_seven_files(tmp_path):
    """The architect's rule (2026-10-10): rules come from his seven files only; anything else is
    put to him first. NBC 2016 is among them; a government order outside them fails this."""
    import re

    survey = _survey(tmp_path / "survey.dxf", nala_x=0.0, extras=True)
    inputs = _inputs(tmp_path, survey, gross_area_sqm=10_800, net_area_sqm=10_350,
                     road_strip_side="E", road_strip_width_m=5.0,
                     water=[{"kind": "nala_over_10m", "survey_layer": "NALA"}])
    run_steps(inputs, tmp_path / "out")
    for n in (1, 3):
        text = (tmp_path / "out" / f"step{n}" / "REPORT.md").read_text()
        cited = set(re.findall(r"G\.O\.(?:M\.?S\.? ?)?(?:No\.)? ?(\d+)", text, re.I))
        assert cited <= SEVEN_FILES, (n, cited - SEVEN_FILES)

