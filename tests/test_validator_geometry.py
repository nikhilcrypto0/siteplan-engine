"""The geometry the validator measures with, tested against shapes whose answers are known: the
validator rebuilds what today's checker borrows from access.py, so these are its own tests."""

import math

import pytest
from shapely import wkt
from shapely.affinity import rotate
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.validator.cars import cars_on_floor
from siteplan.validator.shapes import (
    end_caps,
    healed,
    inscribed_radius,
    mitred,
    narrower_than,
    opening,
    oriented_box,
    polygons_of,
    sides_of,
    width_in,
    width_of,
)
from siteplan.validator.turning import (
    along_wall,
    corners,
    road_bends,
    round_block,
    sector,
    turning_for,
)

TEST_CLASS = "normative"
BAY, AISLE = (2.5, 5.0), 6.0


def _rules() -> ResolvedRules:
    from validator_helpers import fixture

    return fixture("rectangle").rules


# --- opening, widths, boxes ---------------------------------------------------------------


def test_opening_removes_a_part_narrower_than_the_width_and_keeps_the_rest():
    strip = box(0, 0, 10, 2)
    assert opening(strip, 3).is_empty
    assert opening(strip, 2).area == pytest.approx(strip.area, rel=1e-6)  # exactly as wide: kept
    dumbbell = box(0, 0, 10, 10).union(box(10, 4.5, 14, 5.5)).union(box(14, 0, 24, 10))
    kept = opening(dumbbell, 3)
    assert kept.area == pytest.approx(200, abs=0.01) and len(polygons_of(kept)) == 2


@pytest.mark.parametrize("angle", [0, 17, 33, 90])
def test_a_part_exactly_as_wide_as_asked_is_kept_not_swollen_or_dropped(angle):
    """Shrinking a strip by exactly half its width leaves a hairline the geometry library drops
    or swells (a 3 m strip once came back as 78 m² from 60): the opening is stable instead."""
    for width, length in ((3.0, 20.0), (9.0, 80.0), (2.0, 10.0)):
        strip = rotate(box(0, 0, length, width), angle, origin=(0, 0))
        assert opening(strip, width).area == pytest.approx(strip.area, rel=1e-6)
    assert opening(rotate(box(0, 0, 80, 8.9), angle, origin=(0, 0)), 9.0).is_empty


def test_opening_keeps_a_square_corner():
    corner = box(0, 0, 10, 10).union(box(0, 0, 40, 4))  # an L: a wide arm and a narrow one
    assert opening(corner, 4).area == pytest.approx(corner.area, rel=1e-6)


# Made-up land: turned rectangles joined (a road network of the kind the generators draw). The
# geometry library's mitre buffer gets it wrong: shrunk and grown by 4.495 m it returns parts
# lying inside one another, which is not a valid shape and breaks the next set operation.
AWKWARD = wkt.loads(
    "MULTIPOLYGON (((45.02752127777172 27.904477565410517, 66.92438620239963 83.68548635054344, "
    "106.49471057250643 68.15213428992463, 84.59784564787851 12.371125504791706, "
    "45.02752127777172 27.904477565410517)), ((24.68104515214088 53.81952647623693, "
    "26.30663108112101 53.81952647623693, 13.95937698196122 66.16678057539673, "
    "15.594389874001262 67.80179346743678, -4.858265036103589 71.9539930196818, "
    "0.1683465981885064 96.71377439090901, 45.747339020192975 87.46054674108817, "
    "40.72072738590088 62.700765369860946, 22.1552139387086 66.46984654594557, "
    "34.805534008417226 53.81952647623693, 49.37771821148314 53.81952647623693, "
    "49.37771821148314 45.14079342363482, 42.437338272044805 45.14079342363482, "
    "38.71135120288396 41.414806354473974, 34.98536413372312 45.14079342363482, "
    "24.68104515214088 45.14079342363482, 24.68104515214088 53.81952647623693)))")


def test_a_mitre_buffer_the_geometry_library_gets_wrong_is_mended_before_it_is_used():
    half = 4.495  # the shape is wrong for this distance exactly, not for its neighbours
    raw = AWKWARD.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")
    if raw.is_valid:
        pytest.skip("this geometry library no longer gets the shape wrong")
    mended = mitred(mitred(AWKWARD, -half), half)
    assert mended.is_valid
    # nothing is lost in the mending: it is the ground the parts cover together (their areas
    # added up, as the invalid shape reports, would count the nested part twice)
    assert mended.area == pytest.approx(unary_union(list(raw.geoms)).area)
    assert mended.area < raw.area
    assert AWKWARD.difference(mended).area >= 0  # the next set operation runs
    assert mitred(box(0, 0, 10, 10), 2).equals(box(-2, -2, 12, 12))  # and a plain shape is as ever


def test_a_road_drawn_8_9_m_wide_measures_8_9_whatever_it_declares():
    road = box(0, 0, 80, 8.9)
    assert width_of(road, 9.0) == pytest.approx(8.9, abs=0.03)  # reads up to 2 cm high
    assert width_of(box(0, 0, 80, 9.0), 9.0) == 9.0
    assert narrower_than(road, 8.98) and not narrower_than(box(0, 0, 80, 9.0), 8.98)


def test_a_road_is_measured_inside_its_network_so_a_junction_is_not_a_narrowing():
    plaza = box(0, 0, 40, 40)
    road = box(40, 15, 120, 24)  # 9 m, meeting a plaza
    network = plaza.union(road)
    assert width_in(network, road, 18.0) == pytest.approx(9.0, abs=0.03)
    assert width_in(network, plaza, 18.0) == 18.0
    assert width_in(network, Polygon(), 18.0) == 0.0


def test_the_smallest_rectangle_round_a_polygon_is_found_at_any_angle():
    block = rotate(box(0, 0, 40, 12), 33, origin=(0, 0))
    assert sides_of(block) == pytest.approx((40, 12), abs=1e-6)
    angle = oriented_box(block)[0] % math.pi
    assert angle == pytest.approx(math.radians(33), abs=1e-6)
    assert sides_of(Polygon()) == (0.0, 0.0)


def test_the_ends_of_a_long_shape_are_cut_across_its_axis():
    road = rotate(box(0, 0, 60, 9), 20, origin=(0, 0))
    ends = end_caps(road, 1.0)
    assert len(ends) == 2 and all(e.area == pytest.approx(9.0, abs=1e-6) for e in ends)
    assert ends[0].distance(ends[1]) == pytest.approx(58.0, abs=1e-6)


def test_the_largest_circle_in_a_shape_is_found():
    head = Point(0, 0).buffer(9.0, quad_segs=32)
    assert inscribed_radius(head.union(box(-4, -80, 4, 0))) == pytest.approx(9.0, abs=0.1)
    assert inscribed_radius(box(0, 0, 8, 50)) == pytest.approx(4.0, abs=0.1)


def test_hairline_cracks_between_roads_drawn_to_meet_are_closed():
    joined = healed(box(0, 0, 10, 9).union(box(10.04, 0, 20, 9)))
    assert len(polygons_of(joined)) == 1


# --- cars -------------------------------------------------------------------------------


def test_cars_are_counted_in_bays_that_fit_along_an_aisle():
    two_rows = box(0, 0, 40, 16)  # a bay row, a 6 m aisle, a bay row: 16 bays each
    assert cars_on_floor(two_rows, [0.0], BAY, AISLE) == 32
    one_row = box(0, 0, 40, 11)  # a bay row and the aisle in front of it: 16 along it...
    assert cars_on_floor(one_row, [0.0], BAY, AISLE) == 20  # ...or 5 short rows across it
    assert cars_on_floor(box(0, 0, 40, 2), [0.0], BAY, AISLE) == 0  # too narrow for any bay


def test_a_core_in_the_floor_takes_the_bays_it_stands_on():
    floor = box(0, 0, 40, 16).difference(box(10, 0, 20, 16))
    assert cars_on_floor(floor, [0.0], BAY, AISLE) == 24  # 10 m + 20 m of bays, two rows
    assert cars_on_floor(box(0, 0, 40, 16), [0.0], BAY, AISLE) == 32


def test_a_turned_floor_is_laid_out_along_its_own_axis():
    floor = rotate(box(0, 0, 40, 16), 25, origin=(0, 0))
    assert cars_on_floor(floor, [25.0], BAY, AISLE) == 32
    assert cars_on_floor(floor, [0.0], BAY, AISLE) < 32  # the wrong way round loses bays


# --- fire tender turns ----------------------------------------------------------------------


def test_the_two_readings_of_the_9_m_turning_radius():
    rules = _rules()
    outer, centre = turning_for(rules, "outer_edge"), turning_for(rules, "centreline")
    assert (outer.r_in, outer.r_out) == (3.0, 9.0) and outer.lane_m == 6.0
    assert (centre.r_in, centre.r_out) == (6.0, 12.0)
    assert outer.reach_m == pytest.approx(9 - 3 * math.sin(math.pi / 4)) == pytest.approx(6.879,
                                                                                           abs=1e-3)
    assert centre.reach_m == pytest.approx(7.757, abs=1e-3)
    assert turning_for(rules, "some other reading") is None


def test_a_sector_is_the_ground_between_two_radii():
    quarter = sector((0, 0), 3.0, 9.0, 0.0, math.pi / 2)
    assert quarter.area == pytest.approx(math.pi / 4 * (81 - 9), rel=0.01)
    assert quarter.bounds[2] == pytest.approx(9.0) and quarter.bounds[3] == pytest.approx(9.0)
    clockwise = sector((0, 0), 3.0, 9.0, 0.0, -math.pi / 2)
    assert clockwise.bounds[1] == pytest.approx(-9.0)


def test_round_a_block_the_lane_needs_the_reach_beside_each_face_at_each_corner():
    rules, block = _rules(), box(0, 0, 40, 24)
    for reading in ("outer_edge", "centreline"):
        turning = turning_for(rules, reading)
        sectors = round_block(block, turning)
        assert len(sectors) == 4
        beyond = max(max(s.bounds[2] - 40, s.bounds[3] - 24, -s.bounds[0], -s.bounds[1])
                     for s in sectors)
        assert beyond == pytest.approx(turning.reach_m, abs=1e-6)
        assert all(s.intersection(block).area < 1e-6 for s in sectors)  # never into the block


def test_a_notch_in_a_block_is_not_gone_into():
    notched = Polygon([(0, 0), (30, 0), (30, 10), (20, 10), (20, 20), (0, 20)])  # an L
    assert len(list(corners(notched))) == 6
    assert len(round_block(notched, turning_for(_rules(), "outer_edge"))) == 5  # not the reflex


def test_a_bend_shallower_than_5_degrees_is_a_straight_road():
    nearly = Polygon([(0, 0), (30, 0), (60, 1.5), (60, 20), (0, 20)])  # a 2.9 degree bend
    kinds = [round(math.degrees(c.turn)) for c in corners(nearly)]
    assert 3 not in kinds and len(kinds) == 4


def test_a_lane_at_a_convex_bend_keeps_its_outer_edge_on_both_walls():
    turning = turning_for(_rules(), "outer_edge")
    yard = box(0, 0, 100, 100)
    sectors = along_wall(yard, turning)
    assert len(sectors) == 4
    for s in sectors:  # the outer arc touches both walls, 9 m from the corner each way
        assert yard.buffer(1e-6).contains(s)
    corner = min(sectors, key=lambda s: s.centroid.distance(Point(0, 0)))
    assert corner.bounds[0] == pytest.approx(0.0, abs=1e-6) or corner.bounds[1] == pytest.approx(
        0.0, abs=1e-6)


def test_a_lane_at_a_reflex_bend_goes_round_the_step_like_a_block():
    step = Polygon([(0, 0), (60, 0), (60, 30), (30, 30), (30, 60), (0, 60)])
    sectors = along_wall(step, turning_for(_rules(), "outer_edge"))
    assert len(sectors) == 6  # five convex corners and one reflex
    round_the_step = min(sectors, key=lambda s: s.distance(Point(30, 30)))
    assert round_the_step.distance(Point(30, 30)) < 1e-6  # its inner edge touches the corner
    assert step.buffer(1e-6).contains(round_the_step)  # and it sweeps the site, not the notch


def test_a_road_ringing_land_is_checked_round_its_outer_edge_and_round_the_land():
    ring = box(0, 0, 100, 80).difference(box(10, 10, 90, 70))
    assert len(road_bends(ring, turning_for(_rules(), "outer_edge"))) == 8
    assert road_bends(Polygon(), turning_for(_rules(), "outer_edge")) == []
