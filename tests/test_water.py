"""A water body's buffer (rule 3(a)(ii)): no tower, facility or parking bay stands on it.

Found on the firm's Suchitra site, where a nala crosses the plot and the engine had been
placing towers beside it as if it were not there.
"""

import json

import pytest
from pydantic import ValidationError
from shapely.geometry import LineString, Point, box

from siteplan.checks import Building, Site, Status, check_site
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.project import Project, WaterIn
from siteplan.runner import load_water, read_survey

PLOT = box(0, 0, 150, 120)
NALA = LineString([(75, -5), (75, 125)])  # crosses the plot north to south
LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3}, options=3)


def _project(tmp_path, water):
    path = tmp_path / "p.project.json"
    path.write_text(json.dumps({"name": "T", "site": {"authority": "HMDA", "water": water},
                                "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}}}))
    return Project.model_validate_json(path.read_text())


def _survey_with(lines):
    return lambda path, water=None: type("S", (), {"boundary": PLOT, "water": lines})()


@pytest.mark.parametrize(("kind", "buffer_m"), [("nala_over_10m", 9.0), ("nala_up_to_10m", 2.0)])
def test_the_buffer_is_as_wide_as_the_class_the_architect_gives(tmp_path, monkeypatch, kind,
                                                              buffer_m):
    monkeypatch.setattr("siteplan.runner.read_survey", _survey_with((NALA,)))
    zone, note = load_water(_project(tmp_path, [{"kind": kind, "survey_colour": "#00FFFF"}]),
                            "survey.pdf")
    assert zone.contains(Point(75 + buffer_m - 0.1, 60))
    assert not zone.contains(Point(75 + buffer_m + 0.1, 60))
    assert f"{buffer_m:g} m kept clear" in note and "3(a)(ii)" in note


def test_no_water_named_means_no_keep_out(tmp_path):
    assert load_water(_project(tmp_path, []), None) == (None, "")


def test_a_water_body_needs_the_survey_that_draws_it(tmp_path, monkeypatch):
    project = _project(tmp_path, [{"kind": "nala_over_10m", "survey_layer": "NALA"}])
    with pytest.raises(ValueError, match="give the survey"):
        load_water(project, None)
    monkeypatch.setattr("siteplan.runner.read_survey", _survey_with(()))
    with pytest.raises(ValueError, match="no lines in NALA"):
        load_water(project, "survey.dxf")


@pytest.mark.parametrize("water", [
    {"kind": "nala_over_10m"},                                              # nowhere to find it
    {"kind": "nala_over_10m", "survey_colour": "#00FFFF", "survey_layer": "NALA"},  # two ways
    {"kind": "nala_over_10m", "survey_colour": "cyan"},                     # not a colour code
    {"kind": "pond", "survey_layer": "NALA"},                               # no such class
])
def test_a_water_body_is_named_one_way_with_a_known_class(water):
    with pytest.raises(ValidationError):
        WaterIn.model_validate(water)


def test_a_pdf_colour_code_reaches_the_reader_as_its_rgb(monkeypatch):
    seen = {}
    monkeypatch.setattr("siteplan.runner.read_pdf_survey",
                        lambda path, profile=None: seen.setdefault("profile", profile))
    read_survey(__import__("pathlib").Path("s.pdf"),
                WaterIn(kind="nala_over_10m", survey_colour="#00FFFF"))
    assert seen["profile"].water_colour == (0.0, 1.0, 1.0)


def test_the_layout_keeps_every_tower_off_the_buffer():
    zone = NALA.buffer(9.0)
    options = solve(PLOT, LIBRARY, REQUEST, abutting_road_m=18.0, keep_out=zone)
    assert options
    for option in options:
        assert all(t.footprint.intersection(zone).area < 0.01 for t in option.towers)
        assert all(bay.intersection(zone).area < 0.01 for bay in option.parking_bays)
        # A road's width off the buffer, so the loop road can run along it.
        assert all(t.footprint.distance(zone) >= 9.0 - 0.02 for t in option.towers)
        finding = {f.rule: f for f in option.findings}["Water-body buffer"]
        assert finding.status is Status.PASS


def test_land_across_the_water_from_the_entrance_is_left_unbuilt():
    """No crossing over the nala is drawn, so a fire tender could not reach a tower beyond it;
    the towers all stand on the entrance's side."""
    zone = NALA.buffer(9.0)
    for option in solve(PLOT, LIBRARY, REQUEST, abutting_road_m=18.0, keep_out=zone,
                        access_side="W"):
        assert option.entrance.gate.centroid.x < 75
        assert all(t.footprint.centroid.x < 75 for t in option.towers)
        assert {f.rule: f for f in option.findings}[
            "Fire access: reached from the entrance"].status is Status.PASS


def test_a_tower_standing_in_the_buffer_fails():
    site = Site(buildings=(Building("A", height_m=27, footprint=box(70, 10, 90, 30)),),
                water_buffer=NALA.buffer(9.0))
    finding = {f.rule: f for f in check_site(site)}["Water-body buffer"]
    assert finding.status is Status.FAIL and "A" in finding.measured
    assert "never as the setback" in finding.note
