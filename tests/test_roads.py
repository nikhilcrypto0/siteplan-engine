"""Roads next to the plot, measured across themselves. Made-up geometry, in metres."""

import pytest
from shapely.geometry import LineString, Polygon

from siteplan.roads import roads_near
from siteplan.survey import Survey

PLOT = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])


def _survey(*roads: LineString) -> Survey:
    return Survey(source="made up", boundary=PLOT, stated_area_sqm=None, calibration=None,
                  levels=(), roads=roads)


def _dashed(y: float, x0: float, x1: float, dash: float = 0.6, gap: float = 0.6):
    pieces, x = [], x0
    while x < x1:
        pieces.append(LineString([(x, y), (min(x + dash, x1), y)]))
        x += dash + gap
    return pieces


def test_a_road_along_a_side_is_measured_edge_to_edge():
    survey = _survey(LineString([(-20, -2), (120, -2)]), LineString([(-20, -14), (120, -14)]))
    [road] = roads_near(survey)
    assert road.width_m == pytest.approx(12.0, abs=0.05)
    assert road.distance_m == pytest.approx(2.0, abs=0.1)
    assert road.lines_m == pytest.approx((0.0, 12.0), abs=0.05)
    assert road.side == "S"


def test_a_divided_road_meeting_the_plot_keeps_its_divider():
    """Dhulapally's entry road ends at the plot: a ray outward runs between its edges."""
    lines = [LineString([(-60, y), (0, y)]) for y in (30.0, 36.0, 38.0, 44.0)]
    [road] = roads_near(_survey(*lines))
    assert road.width_m == pytest.approx(14.0, abs=0.05)
    assert road.lines_m == pytest.approx((0.0, 6.0, 8.0, 14.0), abs=0.05)
    assert road.divided and road.distance_m == pytest.approx(0.0, abs=0.1)
    assert road.side == "W"


def test_dashed_footpath_edges_count_in_the_width():
    """Suchitra draws its footpaths in short dashes; without them its 40 ft road read 9 m."""
    solid = [LineString([(-20, 86.7), (120, 86.7)]), LineString([(-20, 95.7), (120, 95.7)])]
    lines = [*solid, *_dashed(85.0, -20, 120), *_dashed(97.6, -20, 120)]
    [road] = roads_near(_survey(*lines))
    assert road.width_m == pytest.approx(12.6, abs=0.05)
    assert road.lines_m == pytest.approx((0.0, 1.7, 10.7, 12.6), abs=0.05)
    assert road.side == "N" and not road.divided


def test_dotted_footpath_edges_count_too():
    """Suchitra's are dots under 0.2 m long, which a crossing line almost always misses."""
    solid = [LineString([(-20, 86.7), (120, 86.7)]), LineString([(-20, 95.7), (120, 95.7)])]
    dots = [*_dashed(85.0, -20, 120, dash=0.08, gap=0.3),
            *_dashed(97.6, -20, 120, dash=0.08, gap=0.3)]
    [road] = roads_near(_survey(*solid, *dots))
    assert road.lines_m == pytest.approx((0.0, 1.7, 10.7, 12.6), abs=0.05)


def test_roads_are_listed_nearest_first_and_far_ones_are_left_out():
    near = [LineString([(-20, -1), (120, -1)]), LineString([(-20, -8), (120, -8)])]
    away = [LineString([(130, -20), (130, 100)]), LineString([(140, -20), (140, 100)])]
    beyond = [LineString([(-20, 200), (120, 200)]), LineString([(-20, 212), (120, 212)])]
    found = roads_near(_survey(*near, *away, *beyond))
    assert [round(r.width_m) for r in found] == [7, 10]
    assert [round(r.distance_m) for r in found] == [1, 30]


def test_a_lone_line_is_not_a_road():
    assert roads_near(_survey(LineString([(-20, -3), (120, -3)]))) == ()
