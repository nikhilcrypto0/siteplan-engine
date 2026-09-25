"""The gross-to-net deduction: land lost to road widening comes off the frontage.

Found on the firm's own Dhulapally numbers: their statement gives a gross of 20,131 m² and
a net of 18,969 m², and we had been laying towers out on the gross.
"""

import json

import pytest
from shapely.geometry import Polygon, box

from siteplan.geometry import less_road_strip
from siteplan.project import Project
from siteplan.runner import load_plot

PLOT = box(0, 0, 100, 60)  # 6,000 m², the 100 m sides are the longest runs


def test_the_strip_comes_off_the_longest_boundary():
    net = less_road_strip(PLOT, 5_000)
    assert net.area == pytest.approx(5_000, rel=1e-3)
    x0, y0, x1, y1 = net.bounds
    assert (x1 - x0) == pytest.approx(100)   # the long sides are untouched
    assert (y1 - y0) == pytest.approx(50)    # 10 m came off one of them


def test_a_net_area_that_is_not_smaller_changes_nothing():
    assert less_road_strip(PLOT, 6_000) is PLOT
    assert less_road_strip(PLOT, 9_999) is PLOT


def test_an_odd_shape_still_lands_on_the_stated_area():
    odd = Polygon([(0, 0), (120, 0), (120, 40), (70, 70), (0, 55)])
    net = less_road_strip(odd, odd.area * 0.9)
    assert net.area == pytest.approx(odd.area * 0.9, rel=1e-3)
    assert net.within(odd)


def _project(tmp_path, **site):
    path = tmp_path / "p.project.json"
    path.write_text(json.dumps({"name": "T", "site": site,
                                "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}}}))
    return Project.model_validate_json(path.read_text())


def test_load_plot_deducts_what_the_project_says_is_deducted(tmp_path, monkeypatch):
    monkeypatch.setattr("siteplan.runner.read_survey",
                        lambda path: type("S", (), {"boundary": PLOT})())
    project = _project(tmp_path, net_area_sqm=5_000, authority="HMDA")
    plot, basis = load_plot(project, "survey.pdf")
    assert plot.area == pytest.approx(5_000, rel=1e-3)
    assert "1,000 m² the project states is deducted" in basis
    assert "ASSUMED" in basis


def test_load_plot_leaves_the_boundary_alone_when_no_net_area_is_stated(tmp_path, monkeypatch):
    monkeypatch.setattr("siteplan.runner.read_survey",
                        lambda path: type("S", (), {"boundary": PLOT})())
    plot, basis = load_plot(_project(tmp_path, authority="HMDA"), "survey.pdf")
    assert plot.area == pytest.approx(6_000)
    assert "NOT deducted" in basis
