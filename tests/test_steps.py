"""The architect's steps for any project (`siteplan steps`): step 1 copies the survey, step 2
reads the height the main road allows, step 3 takes off the land given up for road widening,
step 4 keeps the setbacks from every side, step 5 places the tot-lot, and every step's
report answers the same five questions. Made-up land only."""

import itertools
import json
from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import LineString, Polygon, box

from siteplan import rules
from siteplan.blind import BlindLeak
from siteplan.cli import main
from siteplan.steps import (
    carried,
    main_road_height_report,
    road_widening_report,
    setbacks_report,
    survey_copy_report,
    tot_lot_report,
)
from siteplan.steps.drawing import frame
from siteplan.steps.inputs import from_answers, from_project
from siteplan.steps.main_road_height import DRAWN, TABLE_III_WAY, TABLE_IV_WAY, height_for
from siteplan.steps.road_widening import take_off
from siteplan.steps.run import run_steps
from siteplan.steps.setbacks import set_back
from siteplan.steps.survey_copy import ALONG, APART, CARRIED, ENDS, copy_survey
from siteplan.steps.tot_lot import (
    SAME_SQM,
    firm_blocks,
    lay_out,
    pockets_in,
    share_for,
)

TEST_CLASS = "normative"

# A 120 x 90 m plot (10,800 m², as written on the sheet); the reader keeps its corner at (0, 0).
PLOT = [(0, 0), (120, 0), (120, 90), (0, 90)]
# The made-up flat library in examples/: blocks 24.13 m deep, the smallest 31 m long.
LIBRARY = Path(__file__).resolve().parents[1] / "examples" / "flat_library.example.json"


def _workspace(folder, **settings):
    """A workspace that names the example flat library, as a firm's names its own."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / LIBRARY.name).write_text(LIBRARY.read_text())
    (folder / "siteplan.workspace.json").write_text(json.dumps({"flat_library": LIBRARY.name,
                                                                **settings}))
    return folder


def _survey(path, *, south=True, east=True, far=True, short_road=False, west_road=False,
            south_along=False, sump=False, detour=False, nala_x=-12.0, extras=False, plot=PLOT):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_lwpolyline(plot, close=True, dxfattribs={"layer": "SITE-BOUNDARY"})
    area = Polygon(plot).area
    msp.add_text(f"AREA: {area:.0f} SQ.MTS", height=2).set_placement((10, -60))
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
    return from_project(survey, _project(tmp_path / "made-up.project.json", **site),
                        _workspace(tmp_path))


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
    assert [r.number for r in reports] == [1, 2, 3, 4, 5]
    for n in (1, 2, 3, 4, 5):
        text = (tmp_path / "out" / f"step{n}" / "REPORT.md").read_text()
        assert all(heading in text for heading in FIVE), n
        assert "Not rules: what the engine decided by itself" in text
        for name in (f"step{n}.svg", f"step{n}.dxf", f"step{n}.json"):
            assert (tmp_path / "out" / f"step{n}" / name).exists()
    index = (tmp_path / "out" / "README.md").read_text()
    assert all(f"| {n} |" in index for n in range(1, 8)) and "a later stage" in index
    assert json.loads((tmp_path / "out" / "step3" / "step3.json").read_text())["net_plot"]
    assert (tmp_path / "out" / "step2" / "step2-section.svg").exists()


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
    _workspace(tmp_path)  # the firm's flat library, which step 5 needs
    assert main(["steps", str(survey), "--project", str(done), "--out",
                 str(tmp_path / "a")]) == 0
    facts = json.loads((tmp_path / "a" / "step5" / "step5.json").read_text())
    for n in range(1, len(facts["options"]) + 1):  # every whole option drawn, to choose from
        assert (tmp_path / "a" / "step5" / f"step5-option-{n:02d}.svg").exists()
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
    for n, text, facts, picture, around in _later_steps(inputs, copy):
        assert all(i.what in text for i in items), n
        assert [c["key"] for c in facts["carried"]] == [i.key for i in items], n
        drawn = [g for layer, g in picture.shapes if layer in ("ROADS", "WATER")]
        view = frame(copy.plot, around)
        for i in items:
            if i.shape is not None and not i.shape.intersection(view).is_empty:
                assert any(g.intersects(i.shape) for g in drawn), (n, i.key)


def _later_steps(inputs, copy):
    """Every step after step 1: its number, report, facts, picture and how far round the plot
    the picture reaches. A new step joins this list, so the guard holds it too."""
    height = height_for(inputs, copy)
    widening = take_off(inputs, copy)
    setbacks = set_back(inputs, copy, height, widening)
    tot_lot = lay_out(inputs, copy, setbacks)
    return [(2, main_road_height_report.report(height).markdown(),
             main_road_height_report.facts(height), main_road_height_report.picture(height),
             main_road_height_report.DRAWN_AROUND_M),
            (3, road_widening_report.report(widening).markdown(),
             road_widening_report.facts(widening), road_widening_report.picture(widening),
             road_widening_report.DRAWN_AROUND_M),
            (4, setbacks_report.report(setbacks).markdown(), setbacks_report.facts(setbacks),
             setbacks_report.picture(setbacks), setbacks_report.DRAWN_AROUND_M),
            (5, tot_lot_report.report(tot_lot).markdown(), tot_lot_report.facts(tot_lot),
             tot_lot_report.picture(tot_lot), tot_lot_report.DRAWN_AROUND_M)]


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
# Beyond them, what the architect said to use: G.O.Ms.No.7 of 2016's planting strip (2026-10-13)
ARCHITECT_ADDED = {"7"}


def test_every_steps_report_cites_only_the_architects_seven_files(tmp_path):
    """The architect's rule (2026-10-10): rules come from his seven files only; anything else is
    put to him first. NBC 2016 is among them; a government order outside them fails this."""
    import re

    survey = _survey(tmp_path / "survey.dxf", nala_x=0.0, extras=True)
    inputs = _inputs(tmp_path, survey, gross_area_sqm=10_800, net_area_sqm=10_350,
                     road_strip_side="E", road_strip_width_m=5.0,
                     water=[{"kind": "nala_over_10m", "survey_layer": "NALA"}])
    run_steps(inputs, tmp_path / "out")
    for n in (1, 2, 3, 4, 5):
        text = (tmp_path / "out" / f"step{n}" / "REPORT.md").read_text()
        cited = set(re.findall(r"G\.O\.(?:M\.?S\.? ?)?(?:No\.)? ?(\d+)", text, re.I))
        assert cited <= SEVEN_FILES | ARCHITECT_ADDED, (n, cited - SEVEN_FILES)


def test_the_biggest_road_is_the_main_road_when_the_answers_name_none(tmp_path):
    """The architect's rule (2026-10-11): when the main road is not named, the biggest road that
    meets the plot is the main road. A legal width given without a road is asked, not pinned on
    it."""
    survey = _survey(tmp_path / "survey.dxf")
    inputs = _inputs(tmp_path, survey, access_side=None, measured_carriageway_m=None)
    copy = copy_survey(inputs)
    east = next(r for r in copy.roads if r.lies == "east")  # 12 m, the biggest that meets it
    assert copy.access is not None and copy.access.name == east.name
    assert copy.access.legal_width_m is None  # the 9 m given is not pinned on it
    report = survey_copy_report.report(copy)
    assert any("Your rule" in c.why for c in report.choices)
    assert any("without saying which road" in q for q in report.questions)

# --- Step 2: the main road and the height it allows ----------------------------------------------


def test_step_two_reads_the_height_from_the_main_roads_legal_width(tmp_path):
    """A 60 ft road is 18 m (rule 5(f)(xvii)); Table IV lets it serve 30 m; floors of 2.9 m (the
    2.75 m room and a slab), the stilt separate and not counted (the architect's rule): stilt +
    10, 29 m counted, 31.8 m from the ground. TDR's extra floors are shown, never taken."""
    inputs = _inputs(tmp_path, access_side="E", measured_carriageway_m=12.0,
                     abutting_road_m=None, abutting_road_ft=60)
    h = height_for(inputs, copy_survey(inputs))
    assert h.road.lies == "east" and h.reckoned_m == 18 and h.way == TABLE_IV_WAY
    assert h.limit_m == 30 and h.floors == 10 and h.allowed_floors == 10 and h.high_rise
    assert h.storeys.counted_m(10) == pytest.approx(29.0)
    assert h.storeys.physical_m(10) == pytest.approx(0.15 + 2.65 + 29.0)
    assert h.tdr_floors == 4
    report = main_road_height_report.report(h)
    assert any("Stilt + 10" in line for line in report.output)
    assert any("NOT taken" in line for line in report.output)
    assert [b.served for b in h.bands][-1] is False  # the next row is shown, and needs 24 m


def test_a_road_is_a_dead_end_only_when_the_project_says_so(tmp_path):
    """The architect's rule (2026-10-11): a road is a dead end only when he names it one; until
    then it is a through road and nothing is asked. Named, NBC's 30 m from the ground holds."""
    site = {"access_side": "E", "measured_carriageway_m": 12.0, "abutting_road_m": 18.288}
    through = _inputs(tmp_path, road_dead_end=None, **site)
    h = height_for(through, copy_survey(through))
    report = main_road_height_report.report(h)
    assert h.dead_end is False and h.allowed_floors == 10
    assert not any("dead end" in q for q in report.questions)
    assert any("through road" in c.what for c in report.choices)
    named = _inputs(tmp_path, road_dead_end=True, **site)
    h = height_for(named, copy_survey(named))
    assert h.floors == 10 and h.allowed_floors == 9
    assert h.storeys.physical_m(9) <= rules.DEAD_END_MAX_HEIGHT_M < h.storeys.physical_m(10)


def test_below_table_iv_the_height_comes_from_table_iii_the_stilt_left_out(tmp_path):
    """A 9 m road serves no Table IV row, so Table III gives the height for the plot's size;
    its '18**' line needs a 12 m road (rule 5(e)), so the most is 15 m: five floors."""
    inputs = _inputs(tmp_path)
    h = height_for(inputs, copy_survey(inputs))
    assert h.way == TABLE_III_WAY and h.limit_m == 15 and h.floors == 5 and not h.high_rise
    assert h.tdr_floors == 0
    assert any(b.served is False for b in h.bands)  # the 18** line, on a road under 12 m


def test_a_drawn_width_stands_in_for_a_legal_one_and_is_asked(tmp_path):
    inputs = _inputs(tmp_path, access_side="E", measured_carriageway_m=12.0,
                     abutting_road_m=None)
    h = height_for(inputs, copy_survey(inputs))
    assert h.width_from == DRAWN and h.width_m == pytest.approx(12.0, abs=0.05)
    assert h.limit_m == 24 and h.floors == 8
    assert any("legal width" in q for q in main_road_height_report.report(h).questions)


def test_a_legal_width_nobody_checked_is_asked(tmp_path):
    path = _project(tmp_path / "p.json", access_side="E", measured_carriageway_m=12.0,
                    abutting_road_m=12.4, abutting_road_status="UNVERIFIED_DRAWING_VALUE")
    project = json.loads(path.read_text())
    project["status"] = {}
    path.write_text(json.dumps(project))
    inputs = from_project(_survey(tmp_path / "survey.dxf"), path, tmp_path)
    questions = main_road_height_report.report(height_for(inputs, copy_survey(inputs))).questions
    assert any("really" in q and "legal width" in q for q in questions)


def test_step_two_stops_and_asks_when_there_is_no_main_road(tmp_path):
    inputs = _inputs(tmp_path, _survey(tmp_path / "survey.dxf", extras=True), access_side="N")
    copy = copy_survey(inputs)
    h = height_for(inputs, copy)
    report = main_road_height_report.report(h)
    assert h.stopped and report.stopped and report.questions
    text = report.markdown()
    assert all(i.what in text for i in carried.found_in(copy))
    assert "carried unchanged (this step stopped)" in text


def test_the_side_view_shows_the_stilt_the_floors_and_the_limits(tmp_path):
    inputs = _inputs(tmp_path, access_side="E", measured_carriageway_m=12.0,
                     abutting_road_m=18.288, road_dead_end=True)
    h = height_for(inputs, copy_survey(inputs))
    side = main_road_height_report.section(h)
    layers = [layer for layer, _ in side.shapes]
    assert layers.count("FLOORS") == 9 and layers.count("STILT") == 1  # the dead end's cap
    assert layers.count("TDR") == 0 and "LIMIT" in layers and "DEAD-END" in layers
    through = _inputs(tmp_path, access_side="E", measured_carriageway_m=12.0,
                      abutting_road_m=18.288)
    layers = [layer for layer, _ in main_road_height_report.section(
        height_for(through, copy_survey(through))).shapes]
    assert layers.count("FLOORS") == 10 and layers.count("TDR") == 4
    assert not side.plan and "<polygon" not in side.svg()  # a side view has no north arrow

# --- Step 4: setbacks from every side ----------------------------------------------------------

HIGH_RISE = {"access_side": "E", "measured_carriageway_m": 12.0, "abutting_road_m": None,
             "abutting_road_ft": 60}


def _setbacks(inputs):
    copy = copy_survey(inputs)
    widening = take_off(inputs, copy)
    return set_back(inputs, copy, height_for(inputs, copy), widening)


def test_a_high_rise_keeps_table_iv_on_every_side_with_the_green_strip_inside(tmp_path):
    """Stilt + 10 (29 m counted) keeps Table IV's 10 m all round; towards the 60 ft road the
    higher of that and the Building Line (4 m); the 2 m green strip lies inside; beside it 8 m
    is left for the 6 m fire lane. 120 x 90 m less 10 m all round leaves 100 x 70 m."""
    s = _setbacks(_inputs(tmp_path, **HIGH_RISE))
    assert s.high_rise and s.floors == 10 and s.open_space_m == 10
    assert {side.metres for side in s.sides} == {10}
    assert any(side.roads and "legal width is 4 m" in side.why for side in s.sides)
    assert s.left.area == pytest.approx(100 * 70)
    assert s.green.area == pytest.approx(120 * 90 - 116 * 86)
    assert s.fire_room_m == pytest.approx(8.0)
    assert [o.open_space_m for o in s.options] == [7, 8, 9, 10]
    assert s.options[0].left_sqm == pytest.approx(106 * 76)
    assert dict(s.long_blocks)[60.0] == pytest.approx(12.0)  # 10 + 6 - 4
    assert dict(s.long_blocks)[40.0] == 10 and max(dict(s.long_blocks).values()) <= 20
    text = setbacks_report.report(s).markdown()
    assert "LAND LEFT FOR BUILDINGS: 7,000.0 m²" in text and "it fits" in text


def test_the_fire_lane_is_drawn_in_dark_red_just_inside_the_green_strip(tmp_path):
    """The lane runs 2 m to 8 m in from the edge all round: 116 x 86 less 104 x 74. It lies
    inside the 10 m setback, and the picture draws it on its own dark red layer."""
    s = _setbacks(_inputs(tmp_path, **HIGH_RISE))
    assert s.fire_lane.area == pytest.approx(116 * 86 - 104 * 74)
    assert s.fire_lane.difference(s.band).area == pytest.approx(0, abs=1e-6)
    assert s.fire_lane.intersection(s.green).area == pytest.approx(0, abs=1e-6)
    assert not s.lane_in_water
    p = setbacks_report.picture(s)
    assert next(layer for layer in p.layers if layer.name == "FIRE-LANE").colour == "#8b0000"
    assert any(name == "FIRE-LANE" for name, _ in p.shapes)
    assert "Drawn in dark red: 2,280.0 m²" in setbacks_report.report(s).markdown()
    assert setbacks_report.facts(s)["fire_lane_sqm"] == pytest.approx(2280)


def test_below_high_rise_table_iii_gives_the_front_to_the_bigger_road_and_column_10_elsewhere(
        tmp_path):
    """The 9 m main road allows 15 m (step 2): Table III row 11's 15 m line keeps 6 m (column
    10) on every side but the one towards the bigger road, the 12 m road along the east, which
    keeps the Building Line for a road up to 12 m, 3 m (rule 5(f)(iii))."""
    s = _setbacks(_inputs(tmp_path))
    assert not s.high_rise and s.green is None and not s.options and s.fire_lane is None
    assert not any(name == "FIRE-LANE" for name, _ in setbacks_report.picture(s).shapes)
    east = next(side for side in s.sides if side.faces == "east")
    assert s.front_road == east.roads[0] and east.metres == 3 and "bigger road" in east.why
    assert {side.metres for side in s.sides if side is not east} == {6}
    assert s.left.area == pytest.approx((120 - 6 - 3) * (90 - 12))
    text = setbacks_report.report(s).markdown()
    assert "The sides keep 6 m; the front" in text


def test_a_water_buffer_is_laid_over_the_setbacks_never_added(tmp_path):
    """A nala on the west edge keeps 9 m free; the high-rise setback there is 10 m, so the
    land left is the same either way."""
    survey = _survey(tmp_path / "survey.dxf", nala_x=0.0)
    s = _setbacks(_inputs(tmp_path, survey, water=[{"kind": "nala_over_10m",
                                                    "survey_layer": "NALA"}], **HIGH_RISE))
    (kind, from_line, from_edge), = s.left_by_water
    assert kind == "nala_over_10m"
    assert from_line.area == pytest.approx(s.left.area) == pytest.approx(from_edge.area)
    # the fire lane, 2 m to 8 m in, lies in the 9 m buffer along the west: 6 x 86 and the two
    # 1 x 6 ends of the north and south lanes; the architect's rule (2026-10-11) allows it, so it
    # is said, never asked
    (kind, on_line, on_edge), = s.lane_in_water
    assert on_line == pytest.approx(6 * 86 + 2 * 6) == pytest.approx(on_edge)
    report = setbacks_report.report(s)
    assert not any("fire lane" in q for q in report.questions)
    assert any(c.what == "The fire lane may run in a water body's buffer." and "Your rule" in c.why
               for c in report.choices)
    assert any("Your rule (2026-10-11): the buffer and the setbacks overlap" in c.why
               for c in report.choices)
    assert any("allowed (your rule, 2026-10-11)" in line for line in report.output)
    assert setbacks_report.facts(s)["fire_lane_in_water_buffer_sqm"][0]["from_line_drawn"] == (
        pytest.approx(528))


def test_the_road_widening_concession_is_shown_never_taken(tmp_path):
    """Land given up on the east (5 m): the net plot is 115 x 90. The front towards the main
    road keeps 10 m; with rule 16(e)'s concession the other sides keep 7 m: shown, not taken."""
    s = _setbacks(_inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_350,
                          road_strip_side="E", road_strip_width_m=5.0, **HIGH_RISE))
    assert s.left.area == pytest.approx(95 * 70)
    c = s.concession
    assert c is not None and c.open_space_m == 7 and c.front_m == 10
    # the east (main road) and the south (a road meets it) keep 10 m; west and north come to 7
    assert c.left_sqm == pytest.approx((115 - 7 - 10) * (90 - 10 - 7))
    text = setbacks_report.report(s).markdown()
    assert "shown, NOT taken" in text


def test_step_four_stops_when_step_three_has_no_net_plot(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", extras=True)
    inputs = _inputs(tmp_path, survey, gross_area_sqm=10_800, net_area_sqm=10_200,
                     road_strip_side="S")
    copy = copy_survey(inputs)
    s = _setbacks(inputs)
    report = setbacks_report.report(s)
    assert s.stopped and report.stopped and report.questions
    assert all(i.what in report.markdown() for i in carried.found_in(copy))


def test_a_power_line_written_near_the_plot_is_asked_in_step_four(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", extras=True)
    s = _setbacks(_inputs(tmp_path, survey, **HIGH_RISE))
    assert any("power line" in q for q in setbacks_report.report(s).questions)


# --- What the review of steps 2 and 4 found ---------------------------------------------------


def test_a_named_dead_end_caps_a_road_that_sets_no_limit(tmp_path):
    """A 30 m road sets no Table IV limit; named a dead end, NBC's 30 m from the ground still
    holds, so step 2 allows stilt + 9 and step 4 draws for it instead of asking."""
    site = {"access_side": "E", "measured_carriageway_m": 12.0, "abutting_road_m": 30.0}
    inputs = _inputs(tmp_path, road_dead_end=True, **site)
    h = height_for(inputs, copy_survey(inputs))
    assert h.floors is None and h.allowed_floors == 9 and h.tdr_shown == 0
    s = _setbacks(inputs)
    assert not s.stopped and s.floors == 9
    report = main_road_height_report.report(h)
    assert any("THE MOST: Stilt + 9" in line for line in report.output)
    assert not any("None" in q for q in report.questions)


def test_a_named_dead_end_is_the_headline_and_takes_no_tdr_floor_above_its_cap(tmp_path):
    inputs = _inputs(tmp_path, access_side="E", measured_carriageway_m=12.0,
                     abutting_road_m=18.288, road_dead_end=True)
    h = height_for(inputs, copy_survey(inputs))
    report = main_road_height_report.report(h)
    text = report.markdown()
    assert "THE MOST: Stilt + 9 floors, because" in text and "THE MOST: Stilt + 10" not in text
    assert "The road alone would allow Stilt + 10" in text
    assert h.tdr_floors == 4 and h.tdr_shown == 0 and "TDR: no extra floor" in text
    assert "STILT + 9 FLOORS" in main_road_height_report._headline(h)
    assert main_road_height_report.facts(h)["tdr_extra_floors_shown_not_taken"] == 0


def test_a_width_given_without_naming_the_road_is_said_and_what_it_would_allow_shown(tmp_path):
    """No road named: the biggest is the main road and the answers' 60 ft is not pinned on it
    (step 1 asks). Step 2 reads the drawn 12 m but never says no legal width was given."""
    inputs = _inputs(tmp_path, access_side=None, measured_carriageway_m=None,
                     abutting_road_m=None, abutting_road_ft=60)
    h = height_for(inputs, copy_survey(inputs))
    assert h.width_from == DRAWN and h.floors == 8
    assert h.unpinned_m == pytest.approx(18.288) and h.unpinned_floors == 10
    report = main_road_height_report.report(h)
    text = report.markdown()
    assert "no legal width is given" not in text and "no legal width given" not in text
    assert any("without naming the road" in q for q in report.questions)
    assert any("Stilt + 10 (asked)" in line for line in report.output)


def test_a_net_plot_whose_table_iii_row_does_not_allow_the_floors_stops_and_asks(tmp_path):
    """Step 2 reads Table III from the written area; when the net plot's row stops lower, step
    4 asks instead of failing."""
    from dataclasses import replace

    inputs = _inputs(tmp_path)
    copy = copy_survey(inputs)
    h = replace(height_for(inputs, copy), floors=7)  # 20.3 m: above row 11's last line
    s = set_back(inputs, copy, h, take_off(inputs, copy))
    assert s.stopped and "Table III row" in s.stopped and "How many floors" in s.ask
    assert setbacks_report.report(s).stopped


def test_a_river_whose_buffer_waits_on_an_answer_is_never_said_to_be_laid_over(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", nala_x=0.0)
    s = _setbacks(_inputs(tmp_path, survey, water=[{"kind": "river", "survey_layer": "NALA"}],
                          **HIGH_RISE))
    report = setbacks_report.report(s)
    assert not s.left_by_water
    assert not any("buffer over the setbacks" in line for line in report.did)
    assert not any("laid over the setbacks: land in both" in c.what for c in report.choices)
    assert any("waits on one answer" in line for line in report.output)


# --- Step 5: the buildings and the tot-lot ---------------------------------------------------

# A 120 x 90 m plot with a 24 m wide arm 60 m long on its north-west: 12,240 m².
ARMED = [(0, 0), (120, 0), (120, 90), (24, 90), (24, 150), (0, 150)]
# The same with a 30 m wide arm 70 m long: too narrow for Stilt + 10 (10 m a side leaves 10 m),
# wide enough for a slim block at Stilt + 8 (8 m a side leaves 14 m).
BENT = [(0, 0), (120, 0), (120, 90), (30, 90), (30, 160), (0, 160)]
TEN = share_for(True, False, 10_000)
IN_FRONT = box(0, 36, 120, 54)  # the east gate's way straight in, across the plot (18 m wide)


def _tot_lot_inputs(inputs):
    copy = copy_survey(inputs)
    return inputs, copy, set_back(inputs, copy, height_for(inputs, copy), take_off(inputs, copy))


def _step5(inputs):
    return lay_out(*_tot_lot_inputs(inputs))


def _firm_step5(tmp_path, plot=PLOT, **settings):
    survey = _survey(tmp_path / "survey.dxf", plot=plot)
    folder = _workspace(tmp_path / "firm", **settings)
    return _step5(from_project(survey, _project(tmp_path / "p.json", **HIGH_RISE), folder))


def test_the_tot_lot_is_ten_percent_of_a_high_rise_or_group_scheme_and_five_below():
    assert share_for(True, False, 3_000).fraction == pytest.approx(0.10)
    assert share_for(False, True, 10_800).min_pocket_sqm == pytest.approx(50)
    five = share_for(False, False, 3_000)
    assert five.fraction == pytest.approx(0.05) and five.min_pocket_sqm == pytest.approx(15)
    assert share_for(False, False, 700) is None
    both = share_for(True, True, 10_800)
    assert both.fraction == pytest.approx(0.10) and len(both.clauses) == 2  # one 10%, not two


def test_table_iv_keeps_what_the_approved_kondapur_tower_keeps():
    """The architect's check (2026-10-12): the approved Kondapur tower, 49.98 m, keeps 14 m all
    round, Table IV's row for 45 to 50 m."""
    assert rules.band_for_height(49.98).min_open_space_m == 14


def test_the_height_map_steps_down_one_floor_at_a_time_to_stilt_plus_seven(tmp_path):
    t = _step5(_inputs(tmp_path, **HIGH_RISE))
    p = t.placings[0]
    assert [tier.floors for tier in p.tiers] == [10, 9, 8, 7] and t.lowest == 7
    assert [tier.setback_m for tier in p.tiers] == [10, 9, 8, 7]
    assert p.tiers[0].tallest.area == pytest.approx(100 * 70)
    assert p.room.bounds == pytest.approx((7, 7, 113, 83))  # the land left at the lowest's 7 m


def test_the_slim_block_is_one_row_of_the_firms_flats_beside_the_corridor(tmp_path):
    from siteplan.library import FlatLibrary

    library = FlatLibrary.model_validate_json(LIBRARY.read_text())
    blocks = firm_blocks(_workspace(tmp_path / "firm"))
    slim = blocks.kinds[-1]
    kit = blocks.kinds[:-1]
    shortest = min(kit, key=lambda k: k.length_m)
    assert "slim" in slim.what
    assert slim.depth_m == pytest.approx(library.flats[0].depth_m + library.corridor_width_m)
    assert slim.length_m == pytest.approx(shortest.length_m)
    assert slim.flats_per_floor == shortest.flats_per_floor // 2


def test_a_bent_plot_is_cut_into_its_arms_and_each_takes_its_own_edge(tmp_path):
    """The bent plot's arm is cut off at its neck; its rows run along its own long edge (north),
    the main part's along the plot's long south edge."""
    from siteplan.steps import buildings

    t = _firm_step5(tmp_path, plot=BENT)
    p = t.placings[0]
    assert len(p.layout.arms) == 2
    assert p.layout.arms[1].bounds[1] >= 83 - 0.5  # the arm, beyond the main part
    plain = buildings.arms_of(box(7, 7, 113, 83), 500)
    assert len(plain) == 1


def test_lower_blocks_go_into_a_narrow_arm(tmp_path):
    """The architect (2026-10-12): lower blocks, down to Stilt + 7, into narrow parts like the
    arm before any land is called unbuildable. The 30 m arm is too narrow for Stilt + 10 (and
    + 9); the buildings stage lays a Stilt + 8 slim block there. (The tot-lot may ask it back
    later: it frees the most tot-lot for the fewest flats.)"""
    from shapely.geometry import Polygon as Shape

    from siteplan.steps import buildings

    t = _firm_step5(tmp_path, plot=BENT)
    p = t.placings[0]
    lands = [(tier.floors, tier.setback_m, tier.land) for tier in p.tiers]
    plan = buildings.Plan(buildings.SPINE, p.layout.plan.angles, "")
    blocks = buildings.lay(plan, p.layout.arms, lands, list(t.blocks.kinds), Shape(), None,
                           buildings.LOW)
    in_arm = [b for b in blocks if b.arm == 1]
    assert in_arm and {b.floors for b in in_arm} <= {8, 7}
    assert all("slim" in b.kind.what for b in in_arm)


def test_the_blocks_stand_in_straight_rows_on_their_heights_land_and_keep_their_gaps(tmp_path):
    """Every option's blocks: on the land their height may stand on, never on a road or in the
    gate's turn, the taller one's setback between any two (7(a)(xii)); a loop option's rows run
    along one direction in the plot."""
    from siteplan.steps.buildings import LOOP

    t = _step5(_inputs(tmp_path, **HIGH_RISE))
    for option in t.options:
        p = option.placing
        tiers = {tier.floors: tier for tier in p.tiers}
        blocks = p.layout.blocks
        assert blocks, option.number
        for b in blocks:
            assert b.polygon.difference(tiers[b.floors].land).area == pytest.approx(0, abs=0.5)
            assert b.polygon.intersection(p.layout.roads).area == pytest.approx(0, abs=0.5)
            assert b.polygon.distance(p.gate) >= 19 - 0.1
        for a, b in itertools.combinations(blocks, 2):
            gap = tiers[max(a.floors, b.floors)].setback_m
            assert a.polygon.distance(b.polygon) >= gap - 0.05, option.number
        if option.plan.road == LOOP:
            assert len({round(b.angle_deg) for b in blocks}) == 1


def test_each_option_is_whole_its_buildings_with_their_tot_lot(tmp_path):
    """The architect (2026-10-12): each option shows its buildings with its tot-lot already
    laid, so he never chooses buildings blind. Every option holds the share in the leftovers,
    inside the land left, never in a block, the gap between two, a setback, a fire lane, a road
    or in front of the gate; options are different ideas, not copies."""
    t = _step5(_inputs(tmp_path, **HIGH_RISE))
    assert len(t.options) >= 3 and t.placings == t.options[0].placings
    for option in t.options:
        p = option.placing
        assert option.holds and p.tot_lot.area >= t.need_sqm - 1, option.number
        assert p.tot_lot.difference(p.room).area == pytest.approx(0, abs=0.01)
        assert p.tot_lot.intersection(p.kept_out).area == pytest.approx(0, abs=0.5)
        assert p.tot_lot.intersection(p.layout.roads).area == pytest.approx(0, abs=0.5)
        assert p.tot_lot.intersection(IN_FRONT).area == pytest.approx(0, abs=0.5)
        assert p.tot_lot.distance(p.gate) >= 19 - 0.1
        assert all(q.area_sqm >= 50 for q in p.pockets)
        assert p.flats_lost == p.flats_first - p.flats and (p.changes or p.flats_lost == 0)
    for a, b in itertools.combinations(t.options, 2):
        assert a.placing.layout.footprint.symmetric_difference(
            b.placing.layout.footprint).area >= SAME_SQM
    assert len({o.plan.words for o in t.options}) == len(t.options)
    assert [o.placing.flats for o in t.options] == sorted(
        (o.placing.flats for o in t.options), reverse=True)
    text = tot_lot_report.report(t).markdown()
    assert "WHOLE OPTIONS for you to choose from" in text and "The options: choose one" in text
    assert f"Which option do you choose (1 to {len(t.options)})?" in text
    assert "of Narsingi's" in text
    assert len(tot_lot_report.facts(t)["options"]) == len(t.options)
    assert len(tot_lot_report.option_pictures(t)) == len(t.options)


def test_the_tot_lot_asks_back_the_block_that_frees_most_for_fewest_flats(tmp_path):
    """The rectangular plot's rows leave little over, so blocks are shortened or dropped until
    the leftovers hold the share; the flats lost are counted and said."""
    t = _step5(_inputs(tmp_path, **HIGH_RISE))
    asked = [o for o in t.options if o.placing.flats_lost > 0]
    assert asked
    for option in asked:
        p = option.placing
        assert p.changes and p.tot_lot.area >= t.need_sqm - 1
    text = tot_lot_report.report(t).markdown()
    if t.options[0].placing.changes:
        assert "For the tot-lot:" in text


def test_the_tot_lot_takes_several_medium_pieces_before_one_big_one():
    from siteplan.steps.tot_lot import MEDIUM_SQM, _medium_first

    big, small = box(0, 0, 100, 20), box(200, 0, 215, 20)  # 2,000 and 300 m²
    taken = _medium_first(big.union(small), 1_000, box(-50, 0, -40, 20),
                          lambda g: pockets_in(g, TEN))
    parts = list(getattr(taken, "geoms", [taken]))
    assert taken.area == pytest.approx(1_000, abs=2)
    assert len(parts) == 2 and max(g.area for g in parts) <= MEDIUM_SQM + 2


def test_a_corner_beside_the_gate_keeps_a_triangle_small_at_the_gate():
    """The architect (2026-10-12): at a corner beside the gate the tot-lot is a right-angled
    triangle, its small side along the side toward the gate, the long slant away."""
    from siteplan.steps.tot_lot import STEEP, Seat, _gate_corner

    ring = LineString([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])  # anticlockwise
    seat = Seat(ring, 100, 50, 50)  # the south-east corner, its sides 50 m each way
    gate_here = LineString([(100, 60), (100, 70)])  # on the east side
    patch, triangle = _gate_corner(seat, gate_here)
    assert patch.area == pytest.approx(50 * 50)
    x0, y0, x1, y1 = triangle.bounds
    assert (x1 - x0, y1 - y0) == pytest.approx((50, 50 / STEEP))  # long west, small north
    assert triangle.area == pytest.approx(0.5 * 50 * 50 / STEEP)


def test_no_block_stands_in_a_water_buffer_and_the_options_still_hold(tmp_path):
    survey = _survey(tmp_path / "survey.dxf", nala_x=0.0)
    t = _step5(_inputs(tmp_path, survey, water=[{"kind": "lake_10ha_or_more",
                                                 "survey_layer": "NALA"}], **HIGH_RISE))
    buffer = t.setbacks.widening.water[0].kept_free
    assert t.options
    for option in t.options:
        assert len(option.placings) == 2  # the buffer from the line drawn and from the edge
        for p in option.placings:
            for b in p.layout.blocks:
                assert b.polygon.intersection(buffer).area == pytest.approx(0, abs=0.5)
            assert p.tot_lot.area >= t.need_sqm - 1


def test_a_pocket_exactly_the_least_width_counts():
    """An 88 x 3.0 m strip is 3 m wide: it counts, where the rounding of the width test once
    threw it out."""
    assert pockets_in(box(6, 6, 94, 9), TEN).area == pytest.approx(88 * 3, abs=0.5)
    assert pockets_in(box(6, 6, 94, 8.9), TEN).is_empty


def test_five_percent_takes_pockets_of_fifteen_square_metres():
    five = share_for(False, False, 3_000)
    assert pockets_in(box(0, 0, 4, 5), five).area == pytest.approx(20)  # 20 m², 4 m wide
    assert pockets_in(box(0, 0, 3.5, 4), five).is_empty  # 14 m², under 15
    assert pockets_in(box(0, 0, 4, 5), TEN).is_empty  # under the 10% rule's 50 m²


def test_outlines_geos_cannot_overlay_are_snapped_and_tried_again(monkeypatch):
    """GEOS once raised 'non-noded intersection' on a made-up plot and stopped the whole run:
    an overlay that fails is snapped to a millimetre grid and tried again."""
    import shapely
    from shapely.errors import GEOSException

    from siteplan.steps import tot_lot

    class Fussy:  # an outline GEOS refuses until it is snapped
        def intersection(self, other):
            raise GEOSException("TopologyException: found non-noded intersection")

    snapped = []

    def snap(geometry, grid):
        snapped.append(grid)
        return box(0, 0, 10, 10) if isinstance(geometry, Fussy) else shapely.set_precision(
            geometry, grid)

    monkeypatch.setattr(tot_lot, "set_precision", snap)
    out = tot_lot._overlay(Fussy(), box(5, 5, 20, 20), tot_lot.MEET)
    assert snapped == [tot_lot.GRID_M] * 2 and out.area == pytest.approx(25)


def test_land_that_cannot_hold_the_tot_lot_is_said_and_asked(tmp_path):
    from dataclasses import replace

    t = _step5(_inputs(tmp_path, **HIGH_RISE))
    short = replace(t.placings[0], need_sqm=t.placings[0].tot_lot.area + 500)
    report = tot_lot_report.report(replace(t, placings=(short,)))
    assert any("THE LAND CANNOT HOLD THE TOT-LOT" in line for line in report.output)
    assert any("cannot hold the tot-lot" in q and "lower" in q for q in report.questions)


def test_a_plot_the_rules_ask_no_tot_lot_of_says_so(tmp_path):
    from dataclasses import replace

    t = _step5(_inputs(tmp_path, **HIGH_RISE))
    none = replace(t, share=None, placings=())
    report = tot_lot_report.report(none)
    assert report.output == ["No tot-lot is needed on this plot."] and report.picture is None
    assert tot_lot_report.facts(none)["needed"] is False


def test_step_five_stops_and_asks_without_the_firms_blocks(tmp_path):
    survey = _survey(tmp_path / "survey.dxf")
    t = _step5(from_project(survey, _project(tmp_path / "p.json", **HIGH_RISE),
                            tmp_path / "bare"))
    assert t.stopped and "flat_library" in t.ask
    assert "1,080.0 m²" in tot_lot_report.report(t).markdown()  # the size is still said


def test_a_flat_library_that_cannot_be_read_stops_and_asks(tmp_path):
    survey = _survey(tmp_path / "survey.dxf")
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "siteplan.workspace.json").write_text(json.dumps({"flat_library": "gone.json"}))
    t = _step5(from_project(survey, _project(tmp_path / "p.json", **HIGH_RISE), folder))
    assert t.stopped and "gone.json cannot be used" in t.stopped and "flat_library" in t.ask


def test_step_five_stops_when_step_four_has_no_land(tmp_path):
    t = _step5(_inputs(tmp_path, gross_area_sqm=10_800, net_area_sqm=10_200,
                       road_strip_side="S"))
    assert t.stopped and "step 4" in t.stopped
    assert "carried unchanged (this step stopped)" in tot_lot_report.report(t).markdown()
    facts = tot_lot_report.facts(t)
    assert facts["needed"] is None and facts["need_sqm"] is None  # not known, never "no"


def test_step_five_draws_each_option_whole(tmp_path):
    t = _step5(_inputs(tmp_path, **HIGH_RISE))
    pic = tot_lot_report.picture(t)
    layers = {name for name, _ in pic.shapes}
    assert {"STILT-10", "SETBACK", "ROAD", "TOT-LOT", "NET-PLOT", "GATE", "GATE-ZONE"} <= layers
    assert any(text.startswith("TOT-LOT") for _, _, text in pic.labels)
    assert any(text.startswith("S+10") for _, _, text in pic.labels)
    text = tot_lot_report.report(t).markdown()
    assert "OPTION 1's BLOCKS" in text and "The club house comes in the next stage." in text
    facts = tot_lot_report.facts(t)
    assert facts["lowest_floors"] == 7 and facts["options"][0]["readings"][0]["blocks"]


def test_every_steps_picture_marks_the_gate(tmp_path):
    """The architect (2026-10-11): there is no gate marking on any of the plans. The south road
    is the main road here (9 m wide, ending at the plot), so every picture marks its 9 m."""
    inputs = _inputs(tmp_path)
    copy = copy_survey(inputs)
    pictures = [survey_copy_report.picture(copy)] + [pic for *_, pic, _ in
                                                     _later_steps(inputs, copy)]
    assert len(pictures) == 5
    for n, pic in enumerate(pictures, 1):
        gates = [shape for name, shape in pic.shapes if name == "GATE"]
        assert len(gates) == 1, n
        assert gates[0].length == pytest.approx(9, abs=1.0), n
        assert gates[0].distance(LineString([(50, 0), (59, 0)])) < 0.5, n
        assert any(text == "GATE" for _, _, text in pic.labels), n


def test_a_road_that_only_touches_the_plot_still_gets_a_gate_the_approach_road_fits():
    """Rule 8(m): a main approach road is 9 to 18 m wide. A road meeting the plot over 3 m gets
    a 9 m gate centred on the meeting; one meeting it over 40 m, its middle 18 m."""
    from types import SimpleNamespace

    from siteplan.steps.gate import gate_line

    plot = Polygon(PLOT)
    short = gate_line(plot, SimpleNamespace(frontage=LineString([(50, 0), (53, 0)])))
    assert short.length == pytest.approx(9) and short.bounds == pytest.approx((47, 0, 56, 0))
    corner = gate_line(plot, SimpleNamespace(frontage=LineString([(118, 0), (120, 0)])))
    assert corner.length == pytest.approx(9)  # round the corner: 5.5 m south, 3.5 m east
    assert corner.distance(Polygon([(119, 0), (120, 0), (120, 1)]).centroid) < 1
    long = gate_line(plot, SimpleNamespace(frontage=LineString([(10, 0), (50, 0)])))
    assert long.length == pytest.approx(18) and long.bounds == pytest.approx((21, 0, 39, 0))


def test_the_land_left_never_comes_nearer_a_side_than_its_setback_even_at_a_corner():
    """Found in CAD (2026-10-12): a buffer's round ends are chords inside the circle, which left
    land up to 12 mm inside a 10 m setback at an inside corner. The band now covers every corner
    from outside, so the land left keeps the whole setback; a straight side keeps exactly it."""
    from shapely.geometry import LineString, box

    from siteplan.steps import setbacks

    corner = LineString([(0, 0), (60, 0), (60, 60)])  # two sides meeting at an inside corner
    land = box(-40, -40, 100, 100)
    old = land.difference(corner.buffer(10.0))
    new = land.difference(setbacks._reach(corner, 10.0))
    assert old.distance(corner) < 10.0 - 1e-3  # the old band undercut the corner
    assert new.distance(corner) >= 10.0 - 1e-9
    straight = land.difference(setbacks._reach(LineString([(0, 0), (60, 0)]), 10.0))
    assert straight.distance(LineString([(30, 0), (30, 0.0)])) == pytest.approx(10.0, abs=1e-9)
