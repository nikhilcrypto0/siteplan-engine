"""The gross-to-net deduction: land given up for road widening comes off where the drawing or the
architect puts it, never where the engine guesses.

Found on the firm's own Dhulapally numbers: their statement gives a gross of 20,131 m² and a net of
18,969 m². Planning on the gross invented flats; cutting the difference off the east side at an
even width invented a 6.6 m strip where the firm draws a 40 ft road along part of that side.
"""

import json

import pytest
from shapely.geometry import box

from siteplan.project import Project
from siteplan.runner import load_plot

PLOT = box(0, 0, 100, 60)  # 6,000 m²


def _project(tmp_path, **site):
    path = tmp_path / "p.project.json"
    path.write_text(json.dumps({"name": "T", "site": site,
                                "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}}}))
    return Project.model_validate_json(path.read_text())


@pytest.fixture(autouse=True)
def _survey(monkeypatch):
    monkeypatch.setattr("siteplan.runner.read_survey",
                        lambda path: type("S", (), {"boundary": PLOT})())


def test_a_deduction_with_nothing_to_say_where_it_lies_stops_and_asks(tmp_path):
    for site in ({"net_area_sqm": 5_000}, {"net_area_sqm": 5_000, "road_strip_side": "E"}):
        with pytest.raises(ValueError, match="does not guess a strip's location"):
            load_plot(_project(tmp_path, **site), "survey.pdf")


def test_a_strip_given_by_side_and_width_comes_off_that_side(tmp_path):
    project = _project(tmp_path, net_area_sqm=5_400, road_strip_side="E", road_strip_width_m=10)
    plot, basis = load_plot(project, "survey.pdf")
    assert plot.bounds[2] == pytest.approx(90) and plot.area == pytest.approx(5_400)
    assert "10 m strip along the E side" in basis and "7(a)(iii)" in basis


def test_a_strip_that_does_not_come_to_the_stated_deduction_is_refused(tmp_path):
    """Dhulapally: a 40 ft road along part of the east side is not 40 ft off the whole side."""
    project = _project(tmp_path, net_area_sqm=5_000, road_strip_side="E", road_strip_width_m=10)
    with pytest.raises(ValueError, match="does not lie as described"):
        load_plot(project, "survey.pdf")


def test_a_strip_outline_is_taken_as_drawn(tmp_path):
    strip = [[60, 0], [100, 0], [100, 10], [60, 10]]  # 400 m² off part of the south side
    project = _project(tmp_path, net_area_sqm=5_600, road_strip_m=strip)
    plot, basis = load_plot(project, "survey.pdf")
    assert plot.area == pytest.approx(5_600) and "strip outline" in basis


def test_load_plot_leaves_the_boundary_alone_when_no_net_area_is_stated(tmp_path):
    plot, basis = load_plot(_project(tmp_path, authority="HMDA"), "survey.pdf")
    assert plot.area == pytest.approx(6_000)
    assert "NOT deducted" in basis


def test_a_site_plan_whose_outline_is_already_net_is_taken_as_it_is(tmp_path):
    """The firm's site-plan DXF: its outline has the road strip cut already, where they drew it."""
    plot, basis = load_plot(_project(tmp_path, net_area_sqm=6_010, authority="HMDA"), "plan.dxf")
    assert plot is PLOT
    assert "taken as the net plot" in basis and "NOT deducted" not in basis
