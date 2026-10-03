"""The edges of rule 8(m) and NBC 4.6: a cul-de-sac a little long, a head a little small, a block
of exactly 12 m, a road 2 m from a block, a lane a few metres narrow, a path that reaches a tower
only if it counts as a lane. Each pins a survivor of a mutation test of the first road tests."""

import pytest
from shapely.geometry import Point, box
from shapely.ops import unary_union
from validator_helpers import check, fixture, move_tower, rectangle, set_floors, shapes, status

from siteplan.contracts.candidate import PlacedAmenity, RoadKind, RoadPiece, SiteProgram
from siteplan.contracts.common import Status
from siteplan.validator.fire import clear_band

TEST_CLASS = "normative"
Z = Status
SERVED = "Internal roads: every block served"
REACHED = "Fire access: reached from the entrance"
ENTRANCE = "Fire access: entrance"
LANE = "Fire lane: perimeter lane inside the setback"


def _road(candidate, road_id):
    return next(r for r in candidate.circulation.roads if r.id == road_id)


def _without_internal_road(candidate):
    candidate.circulation.roads = [r for r in candidate.circulation.roads
                                   if r.kind is not RoadKind.INTERNAL]


# --- the main approach, the cul-de-sac ---------------------------------------------------------


def test_a_main_approach_declared_narrower_than_drawn_is_held_to_the_declaration():
    def declare(candidate):
        _road(candidate, "road-2").declared_width_m = 8.0
    assert status(fixture("rectangle").edited(declare).report(),
                  "Internal roads: main approach") is Z.FAIL


def _cul(candidate, *, length=69.0, head=9.0, width=8.0):
    """A cul-de-sac off the loop's east side on land cleared of everything else."""
    candidate.towers, candidate.program = [], SiteProgram()
    candidate.circulation.fire_hardstanding = []
    x_end = 139.0 - length
    stem = box(x_end, 34.0 - width / 2, 139.0, 34.0 + width / 2)
    body = unary_union([stem, Point(x_end, 34.0).buffer(head, quad_segs=32)]) if head else stem
    candidate.circulation.roads.append(RoadPiece(
        id="road-9", kind=RoadKind.CUL_DE_SAC, shapes=shapes(body), declared_width_m=width))


@pytest.mark.parametrize("trouble", [{"length": 110.0}, {"head": 7.5}])
def test_a_cul_de_sac_over_100_m_long_or_with_a_head_under_9_m_radius_fails(trouble):
    report = fixture("rectangle").edited(lambda c: _cul(c, **trouble)).report()
    assert status(report, "Internal roads: cul-de-sac road-9") is Z.FAIL, trouble


# --- every block above 12 m opens onto a road ---------------------------------------------------


def test_a_block_of_exactly_12_m_is_not_above_12_m_and_needs_no_road():
    def low(candidate):
        _without_internal_road(candidate)
        set_floors(candidate, "T3", 3)  # 3 m stilt + 9 m = 12 m exactly
    assert check(fixture("rectangle").edited(low).report(), SERVED).finding.measured == (
        "all 2 blocks")

    def higher(candidate):
        low(candidate)
        set_floors(candidate, "T3", 4)  # 15 m
    assert check(fixture("rectangle").edited(higher).report(), SERVED).finding.measured == (
        "not on a road: T3")


def test_a_block_2_m_from_a_road_is_not_on_it():
    def nearly(candidate):
        _without_internal_road(candidate)
        move_tower(candidate, "T3", 4.0, 0.0)  # 2 m from the loop's east arm
    c = check(fixture("rectangle").edited(nearly).report(), SERVED)
    assert "T3" in c.finding.measured


def test_blocks_served_only_by_the_perimeter_lane_are_unverified():
    def lane_only(candidate):
        _without_internal_road(candidate)
        _road(candidate, "road-1").kind = RoadKind.PERIMETER_LANE
        move_tower(candidate, "T3", 5.6, 0.0)  # 0.4 m from the lane
        move_tower(candidate, "T1", 0.0, 1.7)
    c = check(fixture("rectangle").edited(lane_only).report(), SERVED)
    assert c.finding.status is Z.UNVERIFIED and "perimeter lane only" in c.finding.measured


def test_a_perimeter_lane_narrower_than_a_fire_lane_fails():
    def thin(candidate):
        lane = _road(candidate, "road-1")
        lane.kind = RoadKind.PERIMETER_LANE
        lane.shapes = shapes(box(2.0, 2.0, 148.0, 98.0).difference(box(6.0, 6.0, 144.0, 94.0)))
    assert status(fixture("rectangle").edited(thin).report(), LANE) is Z.FAIL


# --- reaching the blocks from the gate ---------------------------------------------------------


def _one_tower_and_one_road(candidate, road):
    candidate.towers = [t for t in candidate.towers if t.name == "T3"]
    candidate.circulation.fire_hardstanding = []
    candidate.circulation.roads = [RoadPiece(id="road-1", kind=RoadKind.INTERNAL,
                                             shapes=shapes(road), declared_width_m=3.0)]


def test_a_path_narrower_than_a_fire_lane_does_not_reach_a_block_it_touches():
    thin = unary_union([box(6.0, 0.0, 9.0, 26.0), box(6.0, 23.0, 110.0, 26.0)])  # 3 m wide
    wide = unary_union([box(5.5, 0.0, 12.0, 28.5), box(5.5, 22.0, 110.0, 28.5)])  # 6.5 m wide
    assert status(fixture("rectangle").edited(lambda c: _one_tower_and_one_road(c, thin)).report(),
                  REACHED) is Z.FAIL
    assert status(fixture("rectangle").edited(lambda c: _one_tower_and_one_road(c, wide)).report(),
                  REACHED) is Z.PASS


def test_a_lane_from_the_gate_that_never_touches_a_block_does_not_reach_it():
    away = box(5.5, 0.0, 12.0, 10.0)  # 6.5 m wide, going nowhere near T3
    c = check(fixture("rectangle").edited(lambda c: _one_tower_and_one_road(c, away)).report(),
              REACHED)
    assert c.finding.status is Z.FAIL and "cut off: T3" in c.finding.measured


def test_a_water_buffer_blocks_the_ground_a_fire_tender_needs():
    """The nala's buffer stops a vehicle as a building does: a tower whose 6 m of clear ground
    runs into it has no way round."""
    def beside_the_buffer(candidate):
        move_tower(candidate, "T1", 27.9, 0.0)  # 3 m from the buffer
    c = check(fixture("nala_plot").edited(beside_the_buffer).report(), "Fire access: T1")
    assert c.finding.status is Z.FAIL and "a water buffer" in c.finding.measured


def test_the_bends_of_a_perimeter_lane_are_swept_by_the_turning_tender_like_a_loop_roads():
    def narrow_lane(candidate):
        lane = _road(candidate, "road-1")
        lane.kind = RoadKind.PERIMETER_LANE
        lane.shapes = shapes(box(2.0, 2.0, 148.0, 98.0).difference(box(8.0, 8.0, 142.0, 92.0)))
    c = check(fixture("rectangle").edited(narrow_lane).report(),
              "Fire access: turns along the loop road")
    assert c.finding.status is Z.FAIL


def test_a_site_under_4000_m2_with_no_driveway_drawn_has_no_driveway_check():
    def none(candidate):
        candidate.circulation.roads = [r for r in candidate.circulation.roads
                                       if r.kind is not RoadKind.DRIVEWAY]
    names = {c.finding.rule for c in fixture("small_plot").edited(none).report().legal}
    assert "Driveways" not in names


def test_the_clear_ground_round_a_block_is_square_at_the_corners():
    assert clear_band(box(0.0, 0.0, 10.0, 10.0), 6.0).area == pytest.approx(22 * 22 - 100)


def test_the_6_m_round_a_block_must_all_be_road_or_fire_lane():
    def no_lanes(candidate):
        candidate.circulation.fire_hardstanding = []
    c = check(fixture("rectangle").edited(no_lanes).report(), "Fire access: T3")
    assert c.finding.status is Z.FAIL and "6 m" in c.finding.measured


# --- the entrance ------------------------------------------------------------------------------


def test_something_built_over_the_entrance_fails_it():
    def cabin(candidate):
        candidate.program.amenities.append(
            PlacedAmenity(name="SECURITY CABIN", shape=rectangle(5.0, 0.5, 8.0, 3.0)))
    c = check(fixture("rectangle").edited(cabin).report(), ENTRANCE)
    assert c.finding.status is Z.FAIL and "something is built over it" in c.finding.measured


@pytest.mark.parametrize("width, expected", [(5.1, Z.FAIL), (5.99, Z.FAIL), (6.0, Z.PASS)])
def test_the_entrance_is_6_m_wide_to_the_centimetre(width, expected):
    def gate(candidate):
        candidate.circulation.gates[0].shape = rectangle(3.0, 0.0, 3.0 + width, 2.0)
        candidate.circulation.gates[0].width_m = width
    assert status(fixture("rectangle").edited(gate).report(), ENTRANCE) is expected


def test_a_ramp_built_on_a_road_is_an_obstruction_to_the_fire_tender():
    def ramp_on_the_road(candidate):
        candidate.program.ramps = [rectangle(60.0, 55.0, 65.4, 60.0)]
    c = check(fixture("rectangle").edited(ramp_on_the_road).report(),
              "Fire access: nothing parked or built on it")
    assert c.finding.status is Z.FAIL and "ramp" in c.finding.measured

