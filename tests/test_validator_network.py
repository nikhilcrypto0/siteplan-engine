"""How the roads join: rule 8(m) wants through roads, a loop that closes, and a main approach that
runs from the entrance to the network. Each case here is a layout a review drew that the first
version of the validator passed."""

from shapely.geometry import Point, box
from shapely.ops import unary_union
from validator_helpers import check, fixture, rectangle, shapes, status

from siteplan.contracts.candidate import RoadKind, RoadPiece, SiteProgram
from siteplan.contracts.common import Status

TEST_CLASS = "normative"
Z = Status
DEAD_ENDS = "Internal roads: dead ends"
JOINED = "Internal roads: joined to the entrance"


def _road(candidate, road_id):
    return next(r for r in candidate.circulation.roads if r.id == road_id)


def test_the_fixture_roads_meet_at_both_ends_and_are_joined_to_the_entrance():
    report = fixture("rectangle").report()
    assert status(report, DEAD_ENDS) is Z.PASS
    assert status(report, JOINED) is Z.PASS


def test_a_loop_road_cut_open_does_not_close_round_the_land():
    def cut(candidate):
        loop = _road(candidate, "road-1")
        loop.shapes = shapes(loop.shapes[0].to_shapely().difference(box(138.0, 40.0, 149.0, 60.0)))
    c = check(fixture("rectangle").edited(cut).report(), DEAD_ENDS)
    assert c.finding.status is Z.FAIL
    assert "the loop road (road-1) does not close round the land" in c.finding.measured


def test_a_piece_of_road_floating_clear_of_the_rest_is_not_joined():
    def float_a_piece(candidate):
        road = _road(candidate, "road-3")
        road.shapes = [*road.shapes, rectangle(16.0, 24.0, 26.0, 29.0)]
    report = fixture("rectangle").edited(float_a_piece).report()
    assert status(report, JOINED) is Z.FAIL
    assert "road-3" in check(report, JOINED).finding.measured


def test_a_main_approach_that_does_not_start_at_the_entrance_is_a_dead_end():
    def elsewhere(candidate):
        _road(candidate, "road-2").shapes = [rectangle(60.0, 2.0, 69.0, 11.0)]
    report = fixture("rectangle").edited(elsewhere).report()
    assert "road-2 does not start at an entrance" in check(report, DEAD_ENDS).finding.measured
    assert status(report, DEAD_ENDS) is Z.FAIL
    assert status(report, JOINED) is Z.FAIL  # and the entrance now meets no road at all


def test_a_way_in_drawn_as_a_driveway_is_not_a_road_to_the_loop():
    """The entrance road drawn 6.5 m wide as a driveway, and no main approach, was never tested."""
    def driveway(candidate):
        road = _road(candidate, "road-2")
        road.kind, road.declared_width_m = RoadKind.DRIVEWAY, 6.5
        road.shapes = [rectangle(4.2, 2.0, 10.7, 11.01)]
    report = fixture("rectangle").edited(driveway).report()
    assert status(report, JOINED) is Z.FAIL
    assert "no rule 8(m) road meets the entrance" in check(report, JOINED).finding.measured


def test_a_scheme_with_only_driveways_has_no_internal_roads():
    def only_driveways(candidate):
        road = _road(candidate, "road-2")
        road.kind = RoadKind.DRIVEWAY
        candidate.circulation.roads = [road]
    report = fixture("rectangle").edited(only_driveways).report()
    assert status(report, "Internal roads") is Z.FAIL


def test_roads_that_meet_only_the_perimeter_lane_are_unverified_not_dead_ends():
    """Whether a perimeter lane in the setback is an 8(m) road is not settled (an assumption)."""
    def lane_for_loop(candidate):
        _road(candidate, "road-1").kind = RoadKind.PERIMETER_LANE
    report = fixture("rectangle").edited(lane_for_loop).report()
    assert status(report, DEAD_ENDS) is Z.UNVERIFIED
    assert "perimeter lane" in check(report, DEAD_ENDS).finding.measured
    assert status(report, JOINED) is Z.UNVERIFIED
    assert status(report, "Internal roads: 9 m loop road (rule 8(m))") is Z.UNVERIFIED


def _cul_de_sac(candidate, head_at):
    """A 69 m, 8 m wide stem off the loop's east side with a 9 m radius head at one end."""
    candidate.towers, candidate.program = [], SiteProgram()
    candidate.circulation.fire_hardstanding = []
    stem = box(70.0, 30.0, 139.0, 38.0)
    head = Point(head_at, 34.0).buffer(9.0, quad_segs=32)
    candidate.circulation.roads.append(RoadPiece(
        id="road-9", kind=RoadKind.CUL_DE_SAC, shapes=shapes(unary_union([stem, head])),
        declared_width_m=8.0))


def test_a_turning_head_belongs_at_the_free_end_not_where_the_road_joins():
    at_the_end = fixture("rectangle").edited(lambda c: _cul_de_sac(c, 70.0)).report()
    at_the_joint = fixture("rectangle").edited(lambda c: _cul_de_sac(c, 139.0)).report()
    assert status(at_the_end, "Internal roads: cul-de-sac road-9") is Z.PASS
    c = check(at_the_joint, "Internal roads: cul-de-sac road-9")
    assert c.finding.status is Z.FAIL and "head radius" in c.finding.measured
