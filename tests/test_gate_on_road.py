"""An entrance not pinned opens where the access road meets the plot (2026-10-21: Suchitra's blind
runs opened theirs 80 m from where R2 meets the plot, on an edge no road touches, because any
edge facing the road's side was taken): the site model carries where the survey draws the road
reaching the plot, the envelope's access zones are that stretch alone, the search lays its gate
there or says why it cannot, and the validator fails a gate that opens onto no road. Made-up
land."""

import ezdxf
import pytest
from search_support import made_up, strategy
from shapely.geometry import LineString, box
from validator_helpers import fixture

from siteplan.contracts import digest
from siteplan.contracts.common import Line, Provenance, Sourced, SourceKind, Status
from siteplan.legal.envelope import envelope
from siteplan.legal.resolve import resolve
from siteplan.legal.site import site_from_project
from siteplan.optimizer.search import network
from siteplan.optimizer.search.land import plot_of
from siteplan.project import Project
from siteplan.validator import validate

TEST_CLASS = "normative"
ENTRANCE = "Fire access: entrance"
SOURCE = "the survey: where road 1 reaches the plot (made up)"


def _meets(points_list):
    return Sourced[list[Line]](value=[Line(points=p) for p in points_list],
                               status=Provenance.EXTRACTED, source_kind=SourceKind.SURVEY,
                               source=SOURCE)


def _entrance(report):
    return next(c for c in report.legal if c.finding.rule == ENTRANCE)


def _road_meets(points_list):
    def edit(site):
        site.access.frontage = _meets(points_list)
    return fixture("rectangle").with_site(edit)


def _zones_length(site) -> float:
    return sum(z.length_m for z in envelope(site, resolve(site)).circulation.access_zones)


# --- The survey says where the road meets the plot -------------------------------------------


def _survey(tmp_path):
    """A 150 x 100 m plot whose 12 m road comes up from the south and ends at it, 60 to 72 m
    along its south edge: the rest of that edge faces the road's side and meets no road."""
    doc = ezdxf.new("R2018")
    doc.units = ezdxf.units.M
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (150, 0), (150, 100), (0, 100)], close=True,
                       dxfattribs={"layer": "SITE-BOUNDARY"})
    for x in (60, 72):
        msp.add_line((x, -40), (x, 0), dxfattribs={"layer": "ROAD"})
    doc.saveas(tmp_path / "survey.dxf")
    return tmp_path / "survey.dxf"


def _project():
    return Project.model_validate({
        "name": "Made-up survey",
        "site": {"abutting_road_ft": 40, "abutting_road_status": "DECLARED_ON_SITE_PLAN",
                 "access_side": "S", "road_dead_end": False, "authority": "HMDA",
                 "inside_cure": False, "gross_area_sqm": 15_000, "net_area_sqm": 15_000},
        "sources": {"abutting_road": "architect: 40 ft", "access_side": "survey: road 1"},
        "status": {"abutting_road": "USER_CONFIRMED", "authority": "USER_CONFIRMED",
                   "inside_cure": "USER_CONFIRMED", "road_dead_end": "USER_CONFIRMED"},
        "layout": {"floors": 8, "unit_mix": {"2BHK": 1.0}}})


def test_the_survey_says_where_the_access_road_meets_the_plot(tmp_path):
    site = site_from_project(_project(), _survey(tmp_path))
    met = site.access.frontage
    assert met is not None and met.status is Provenance.EXTRACTED
    assert met.source_kind is SourceKind.SURVEY and "road 1" in met.source
    assert sum(LineString(line.points).length for line in met.value) == pytest.approx(12, abs=1)
    # the access zones are the road's 12 m, not the whole 150 m south edge facing its side
    assert 10 < _zones_length(site) < 16


def test_a_site_whose_survey_draws_no_road_keeps_the_side_reading():
    site = made_up(box(0, 0, 200, 120)).site
    assert site.access.frontage is None
    assert _zones_length(site) == pytest.approx(200, abs=1)  # the south edge facing the road


# --- The validator: a gate onto no road is no entrance ----------------------------------------


def test_a_gate_where_the_road_meets_the_plot_is_an_entrance():
    # the made-up rectangle opens its gate on the south edge, 3 to 12 m along
    check = _entrance(_road_meets([[(0.0, 0.0), (15.0, 0.0)]]).report())
    assert "opens onto no road" not in check.finding.measured


def test_a_gate_away_from_where_the_road_meets_the_plot_fails():
    """The rectangle's gate faces the road's side (south), all the old reading asked; the road is
    drawn meeting the plot on its east edge, 40 to 60 m up, where nothing is given up, so a gate
    on the south edge opens onto the land beside the plot."""
    check = _entrance(_road_meets([[(150.0, 40.0), (150.0, 60.0)]]).report())
    assert check.finding.status is Status.FAIL
    assert "from where the access road meets the plot: it opens onto no road" in (
        check.finding.measured)
    assert "where the access road meets it" in check.finding.required


def test_land_given_up_to_widen_the_road_is_the_road_s():
    """The rectangle gives up a 3 m strip all along its south edge; the road reaches the surveyed
    boundary 100 to 130 m along, and the strip beside it becomes road, so a gate on the strip's
    inner edge, 3 to 12 m along, opens onto the widened road (as the steps' gate reads it)."""
    check = _entrance(_road_meets([[(100.0, -3.0), (130.0, -3.0)]]).report())
    assert "opens onto no road" not in check.finding.measured


def test_a_road_drawn_short_of_the_plot_leaves_no_entrance():
    check = _entrance(_road_meets([]).report())
    assert check.finding.status is Status.FAIL
    assert "the survey draws the access road short of the plot" in check.finding.measured


# --- The search lays its gate on the road, or says why it cannot ------------------------------


def _with_road(made, points_list):
    site = made.site.model_copy(deep=True)
    site.access.frontage = _meets(points_list)
    rules = made.rules.model_copy(update={"site_ref": digest(site)})
    return made.__class__(site, rules, made.brief, envelope(site, rules), made.kit)


def test_the_search_opens_its_gate_where_the_road_meets_the_plot():
    stretch = [(60.0, 0.0), (75.0, 0.0)]
    met = _with_road(made_up(box(0, 0, 200, 120)), [stretch])
    proposal = strategy().propose(met.context())
    assert proposal.candidates
    road = LineString(stretch).buffer(1.5)
    for c in proposal.candidates:
        for gate in c.circulation.gates:
            assert gate.shape.to_shapely().intersects(road), c.candidate_id
        report = validate(met.site, met.rules, met.brief, c, met.envelope)
        assert "opens onto no road" not in _entrance(report).finding.measured


def test_a_road_meeting_the_plot_along_less_than_the_approach_lays_no_gate_and_says_so():
    """Suchitra's R2 meets its plot along a notch of a few metres: no 9 m entrance fits there, and
    none is invented on another edge; the architect pins it."""
    met = _with_road(made_up(box(0, 0, 200, 120)), [[(60.0, 0.0), (64.0, 0.0)]])
    entrance, why = network.find_entrance(plot_of(met.site, met.envelope), [], box(0, 0, 0, 0),
                                          9.0, 2.0)
    assert entrance is None
    assert "meets the plot along 4.0 m" in why and "the architect's to say" in why
