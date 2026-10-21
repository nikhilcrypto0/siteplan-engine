"""The gross-to-net deduction: land given up for road widening comes off where the drawing or the
architect puts it, never where the engine guesses.

Found on the firm's own Dhulapally numbers: their statement gives a gross of 20,131 m² and a net of
18,969 m². Planning on the gross invented flats; cutting the difference off the east side at an
even width invented a 6.6 m strip where the firm draws a 40 ft road along part of that side.
"""

import json

import pytest
from shapely.geometry import Point, Polygon, box

from siteplan.adapters.legacy_site import _site_fields, site_model
from siteplan.contracts.accounting import LocationHow
from siteplan.geometry import strip_from_corner
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


CORNER = {"net_area_sqm": 5_200, "road_strip_side": "E", "road_strip_width_m": 10,
          "road_strip_from": "NE", "road_strip_toward": "S"}  # 800 m² off, from the north-east


def test_a_strip_from_a_corner_runs_along_the_boundary_and_round_a_corner_as_far_as_its_area(
        tmp_path):
    """Dhulapally, 2026-10-18: 'on the east side ... at the right-hand corner, about 1,113 m²'.
    10 m off the 60 m east side is 600 m²; the rest of the 800 m² comes off the south side from
    the corner on, 30 m of it (the corner square is counted once), so the strip ends at x = 70."""
    plot, basis = load_plot(_project(tmp_path, **CORNER), "survey.pdf")
    assert plot.area == pytest.approx(5_200, abs=0.5)
    assert not plot.contains(Point(95, 30)) and not plot.contains(Point(75, 5))
    assert plot.contains(Point(65, 5)) and plot.contains(Point(85, 15))
    assert "10 m strip along 90.0 m of the boundary from its NE corner toward S" in basis


def test_the_way_a_corner_strip_runs_is_the_architects(tmp_path):
    plot, _ = load_plot(_project(tmp_path, **{**CORNER, "road_strip_toward": "W"}), "survey.pdf")
    assert not plot.contains(Point(95, 55)) and not plot.contains(Point(50, 55))  # the north side
    assert plot.contains(Point(95, 30))


def test_a_strip_from_a_wide_corner_takes_the_whole_tip():
    """2026-10-21, Dhulapally's east tip: the plot's other side leaves the corner back behind
    the strip's start (a corner of about 107 degrees), and a strip cut square at the tip left a
    sliver the firm's plan gives up with the road. Here the corner is 117 degrees: the strip's
    inner edge runs on to the north-east side, the tip goes with it, the area is still the
    stated deduction, and it ends that much sooner along the south."""
    plot = Polygon([(0, 0), (100, 0), (100, 60), (60, 80), (0, 80)])
    cut = strip_from_corner(plot, "NE", "S", 10, 800)
    assert cut.corner == (100, 60)
    assert cut.strip.area == pytest.approx(800, abs=1)
    assert not cut.plot.contains(Point(97, 61))  # beside the tip, behind a square start
    assert cut.plot.intersection(Point(100, 60).buffer(3)).area < 0.01
    assert cut.plot.contains(Point(85, 66))  # beyond 10 m of the east side: the plot's


def test_a_corner_strip_that_cannot_hold_the_deduction_is_refused():
    with pytest.raises(ValueError, match="all round the plot comes to less"):
        strip_from_corner(PLOT, "NE", "S", 1, 6_000)
    with pytest.raises(ValueError, match="say which way the strip runs"):
        strip_from_corner(box(0, 0, 100, 100), "NE", "SW", 10, 500)  # both ways as far off SW


def test_a_corner_strip_reaches_the_site_model_as_the_stretch_it_runs_along(tmp_path):
    """The contract carries it as EXTENT (the stretch of boundary and the width); taken back to a
    project it is the strip's outline, which gives the same net plot."""
    project = _project(tmp_path, gross_area_sqm=6_000, **CORNER)
    site = site_model(project, boundary=PLOT)
    where = site.ownership.deductions[0].location
    assert where.how is LocationHow.EXTENT and where.width_m == 10
    line = where.extent.to_shapely()
    assert line.coords[0] == (100, 60) and line.length == pytest.approx(90, abs=0.05)
    back, *_ = _site_fields(site)
    again, _ = load_plot(_project(tmp_path, net_area_sqm=5_200, road_strip_m=back["road_strip_m"]),
                         "survey.pdf")
    plot, _ = load_plot(project, "survey.pdf")
    assert again.symmetric_difference(plot).area < 0.5


def test_a_corner_strip_is_never_laid_on_an_outline_that_is_already_net(tmp_path):
    """The firm's site plan given as the survey draws the net plot itself: no strip is left to
    place on it, so none is laid (it would take a negative area), and nothing is cut twice."""
    project = _project(tmp_path, gross_area_sqm=6_800, **CORNER)  # 5,200 stated net
    net_outline = box(0, 0, 100, 52)  # 5,200 m²: already the net plot
    where = site_model(project, boundary=net_outline).ownership.deductions[0].location
    assert where.how is LocationHow.UNKNOWN
    with pytest.raises(ValueError, match="takes nothing off"):
        strip_from_corner(PLOT, "NE", "S", 10, 0)


def test_a_site_plan_whose_outline_is_already_net_is_taken_as_it_is(tmp_path):
    """The firm's site-plan DXF: its outline has the road strip cut already, where they drew it."""
    plot, basis = load_plot(_project(tmp_path, net_area_sqm=6_010, authority="HMDA"), "plan.dxf")
    assert plot is PLOT
    assert "taken as the net plot" in basis and "NOT deducted" not in basis
