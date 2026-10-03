"""Roads (rule 8(m), 8(l)) and fire access (NBC 4.6), measured from the drawn shapes."""

import pytest
from shapely.geometry import Point, box
from shapely.ops import unary_union
from validator_helpers import (
    check,
    fixture,
    move_tower,
    rectangle,
    select,
    set_floors,
    shape,
    shapes,
    status,
)

from siteplan.contracts.candidate import PlacedAmenity, RoadKind, RoadPiece, SiteProgram
from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.resolved_rules import (
    ALL,
    APPROACH_WIDTH,
    CIRCULATION_IN_SETBACK,
    FIRE_TURNING_RADIUS,
    STILT_IN_RULE_HEIGHT,
)

TEST_CLASS = "normative"
Z = Status
LOOP_ROADS = "Internal roads: loop and other roads"


def _road(candidate, kind):
    return next(r for r in candidate.circulation.roads if r.kind.value == kind)


def _shrink(road, metres):
    road.shapes = [shape(s.to_shapely().buffer(-metres, join_style="mitre")) for s in road.shapes]


# --- internal roads --------------------------------------------------------------------------


def test_a_road_is_measured_from_its_drawn_shape_not_from_the_width_it_declares():
    inputs = fixture("rectangle").edited(lambda c: _shrink(_road(c, "INTERNAL"), 0.055))
    report = inputs.report()
    assert _road(inputs.candidate, "INTERNAL").declared_width_m == 9.0  # still says 9 m
    c = check(report, LOOP_ROADS)
    assert c.finding.status is Z.FAIL and "8.9" in c.finding.measured
    lie = [d for d in report.cross_checks if d.item.startswith("road width")]
    assert len(lie) == 1 and lie[0].blocks_pass and "8.9" in lie[0].ours


def test_a_road_that_declares_itself_narrower_than_9_m_fails_though_it_is_drawn_wider():
    def declare(candidate):
        _road(candidate, "INTERNAL").declared_width_m = 8.9
    assert status(fixture("rectangle").edited(declare).report(), LOOP_ROADS) is Z.FAIL


def test_something_standing_on_a_road_takes_its_width_from_it():
    def park(candidate):  # a tot-lot pocket laid across the middle of the internal road
        candidate.program.open_space.append(rectangle(60.0, 55.0, 90.0, 61.5))
    c = check(fixture("rectangle").edited(park).report(), LOOP_ROADS)
    assert c.finding.status is Z.FAIL and "road-3" in c.finding.measured


def test_a_main_approach_road_narrower_than_9_m_fails():
    inputs = fixture("rectangle").edited(lambda c: _shrink(_road(c, "APPROACH"), 0.06))
    assert status(inputs.report(), "Internal roads: main approach") is Z.FAIL


def test_how_wide_the_authority_wants_the_approach_is_an_open_reading():
    inputs = fixture("rectangle").with_rules(
        lambda r: setattr(r.interpretation(APPROACH_WIDTH), "selected", ALL))
    c = check(inputs.report(), "Internal roads: main approach")
    assert c.finding.status is Z.UNVERIFIED  # 9 m is the least; the authority may ask 18 m
    assert c.by_reading[APPROACH_WIDTH] == {"minimum": Z.PASS, "authority_choice": Z.UNVERIFIED}
    assert status(fixture("rectangle").report(), "Internal roads: main approach") is Z.PASS


def test_a_driveway_is_never_counted_as_an_internal_road():
    def demote(candidate):
        _road(candidate, "INTERNAL").kind = RoadKind.DRIVEWAY
    report = fixture("rectangle").edited(demote).report()
    served = check(report, "Internal roads: every block served")
    assert served.finding.status is Z.FAIL  # T3 reaches only the driveway; T1 and T2 the loop
    assert served.finding.measured == "not on a road: T3"
    assert status(report, "Driveways") is Z.PASS


def test_a_driveway_narrower_than_4_5_m_fails():
    def thin(candidate):
        road = _road(candidate, "INTERNAL")
        road.kind, road.declared_width_m = RoadKind.DRIVEWAY, 4.0
        road.shapes = [rectangle(11.01, 56.0, 138.99, 60.0)]
    assert status(fixture("rectangle").edited(thin).report(), "Driveways") is Z.FAIL


def test_every_block_above_12_m_must_open_onto_a_road():
    def cut_off(candidate):
        candidate.circulation.roads = [r for r in candidate.circulation.roads
                                       if r.kind.value != "INTERNAL"]
    served = check(fixture("rectangle").edited(cut_off).report(),
                   "Internal roads: every block served")
    assert served.finding.status is Z.FAIL and served.finding.measured == "not on a road: T3"
    assert status(fixture("rectangle").report(), "Internal roads: every block served") is Z.PASS


def test_a_road_that_ends_short_of_the_loop_is_a_dead_end():
    def shorten(candidate):
        road = _road(candidate, "INTERNAL")
        road.shapes = [shape(road.shapes[0].to_shapely().intersection(box(16, 0, 200, 200)))]
    c = check(fixture("rectangle").edited(shorten).report(), "Internal roads: dead ends")
    assert c.finding.status is Z.FAIL and "road-3" in c.finding.measured


def _cul_de_sac(candidate, *, width=8.0, length=69.0, head=9.0, joined=True):
    """A cul-de-sac off the loop's east side, on land cleared of everything else so that only
    its own form is judged."""
    candidate.towers, candidate.program = [], SiteProgram()
    candidate.circulation.fire_hardstanding = []
    x_end = 139.0 - length
    stem = box(x_end, 34.0 - width / 2, 139.0 if joined else 120.0, 34.0 + width / 2)
    body = unary_union([stem, Point(x_end, 34.0).buffer(head, quad_segs=32)]) if head else stem
    candidate.circulation.roads.append(RoadPiece(
        id="road-9", kind=RoadKind.CUL_DE_SAC, shapes=shapes(body), declared_width_m=width))


@pytest.mark.parametrize("trouble", [{}, {"length": 40.0}, {"width": 6.0}, {"head": 0},
                                     {"joined": False}])
def test_a_cul_de_sac_must_be_8_m_wide_50_to_100_m_long_with_a_9_m_head(trouble):
    report = fixture("rectangle").edited(lambda c: _cul_de_sac(c, **trouble)).report()
    got = check(report, "Internal roads: cul-de-sac road-9")
    assert got.finding.status is (Z.PASS if not trouble else Z.FAIL), (trouble,
                                                                       got.finding.measured)


def test_below_4000_m2_rule_8_does_not_apply_and_a_driveway_serves():
    report = fixture("small_plot").report()
    assert status(report, "Internal roads (rule 8)") is Z.INFO
    assert status(report, "Driveways") is Z.PASS


# --- circulation inside the setback ------------------------------------------------------------


def test_roads_and_fire_lanes_in_the_setback_are_judged_under_both_readings():
    c = check(fixture("rectangle").report(), "Circulation inside the setback")
    assert c.finding.status is Z.UNVERIFIED
    by = c.by_reading[CIRCULATION_IN_SETBACK]
    assert by == {"allowed": Z.PASS, "not_allowed": Z.FAIL}
    assert c.finding.note.count("13(c)(vii)") == 1


@pytest.mark.parametrize("reading, expected", [("allowed", Z.PASS), ("not_allowed", Z.FAIL)])
def test_a_profile_that_settles_the_reading_gets_a_settled_answer(reading, expected):
    inputs = fixture("rectangle").with_rules(lambda r: select(r, CIRCULATION_IN_SETBACK, reading))
    assert status(inputs.report(), "Circulation inside the setback") is expected


def test_the_road_that_crosses_the_setback_to_the_gate_is_not_circulation_in_it():
    def only_the_entrance(candidate):
        candidate.circulation.roads = [r for r in candidate.circulation.roads
                                       if r.kind.value == "APPROACH"]
        candidate.circulation.fire_hardstanding = []
    inputs = fixture("rectangle").with_rules(lambda r: select(r, CIRCULATION_IN_SETBACK,
                                                              "not_allowed"))
    assert status(inputs.edited(only_the_entrance).report(),
                  "Circulation inside the setback") is Z.PASS


# --- fire access -------------------------------------------------------------------------------


def test_something_built_within_6_m_of_a_high_rise_fails_its_fire_access():
    def build(candidate):
        candidate.program.amenities.append(
            PlacedAmenity(name="SECURITY CABIN", shape=rectangle(134.5, 40.0, 137.0, 42.5)))
    report = fixture("rectangle").edited(build).report()
    assert status(report, "Fire access: T3") is Z.FAIL
    assert "within 6 m" in check(report, "Fire access: T3").finding.measured


def test_no_gate_means_no_way_in_for_a_fire_tender():
    inputs = fixture("rectangle").edited(lambda c: setattr(c.circulation, "gates", []))
    report = inputs.report()
    assert status(report, "Fire access: entrance") is Z.FAIL
    assert status(report, "Fire access: reached from the entrance") is Z.FAIL


def test_a_gate_narrower_than_6_m_fails():
    def narrow(candidate):
        candidate.circulation.gates[0].shape = rectangle(5.0, 0.0, 9.0, 2.0)
    assert status(fixture("rectangle").edited(narrow).report(), "Fire access: entrance") is Z.FAIL


def test_a_gate_that_meets_no_lane_does_not_reach_the_blocks():
    def float_free(candidate):
        candidate.circulation.gates[0].shape = rectangle(20.0, 0.0, 29.0, 1.0)
    report = fixture("rectangle").edited(float_free).report()
    assert status(report, "Fire access: reached from the entrance") is Z.FAIL


def test_a_layout_with_no_roads_cannot_be_passed_on_its_fire_access():
    def strip(candidate):
        candidate.circulation.roads, candidate.circulation.gates = [], []
        candidate.circulation.fire_hardstanding = []
    report = fixture("rectangle").edited(strip).report()
    assert status(report, "Fire access: around each block") is Z.UNVERIFIED
    assert status(report, "Internal roads") is Z.UNVERIFIED


def test_the_turn_at_a_corner_needs_more_room_under_the_centreline_reading():
    def obstruct(candidate):  # 7.3 m off T3's east face at its corner: past 6.88, short of 7.76
        candidate.program.amenities.append(
            PlacedAmenity(name="TRANSFORMER YARD", shape=rectangle(140.3, 49.0, 142.3, 51.0)))
    inputs = fixture("rectangle").with_rules(
        lambda r: setattr(r.interpretation(FIRE_TURNING_RADIUS), "selected", ALL))
    c = check(inputs.edited(obstruct).report(), "Fire access: T3")
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[FIRE_TURNING_RADIUS] == {"outer_edge": Z.PASS, "centreline": Z.FAIL}
    assert FIRE_TURNING_RADIUS in c.finding.note


def test_a_bend_of_the_loop_road_with_something_in_the_way_fails():
    def block_the_corner(candidate):
        candidate.program.amenities.append(
            PlacedAmenity(name="SUBSTATION", shape=rectangle(141.0, 4.0, 145.0, 8.0)))
    c = check(fixture("rectangle").edited(block_the_corner).report(),
              "Fire access: turns along the loop road")
    assert c.finding.status is Z.FAIL and "blocked" in c.finding.measured


def test_nothing_may_be_parked_or_built_on_a_road_or_a_fire_lane():
    def park(candidate):
        candidate.program.bays.append(rectangle(60.0, 56.0, 62.5, 61.0))  # on the internal road
    c = check(fixture("rectangle").edited(park).report(),
              "Fire access: nothing parked or built on it")
    assert c.finding.status is Z.FAIL and "parking bay" in c.finding.measured


def _facts(inputs, **values):
    def edit(site):
        for name, value in values.items():
            sourced = getattr(site.access, name)
            sourced.value = value
            sourced.status = Provenance.USER_CONFIRMED if value is not None else (
                Provenance.UNVERIFIED)
    return inputs.with_site(edit)


def test_where_the_street_leads_comes_from_the_site_and_is_unverified_when_unknown():
    inputs = fixture("rectangle")
    assert status(_facts(inputs, joins_12m_street=None).report(),
                  "Fire access: the street joins a 12 m street") is Z.UNVERIFIED
    assert status(_facts(inputs, joins_12m_street=False).report(),
                  "Fire access: the street joins a 12 m street") is Z.FAIL
    assert status(_facts(inputs, joins_12m_street=True).report(),
                  "Fire access: the street joins a 12 m street") is Z.PASS


def test_a_dead_end_road_bars_a_building_above_30_m_only():
    low = _facts(fixture("rectangle"), dead_end=True)
    assert status(low.report(), "Fire access: dead-end road") is Z.PASS  # 27 m

    def taller(candidate):
        set_floors(candidate, "T1", 10)  # 33 m
    tall = low.edited(taller)
    assert status(tall.report(), "Fire access: dead-end road") is Z.FAIL
    rule = "Fire access: dead-end road"
    assert status(_facts(tall, dead_end=None).report(), rule) is Z.UNVERIFIED
    assert status(_facts(tall, dead_end=False).report(), rule) is Z.PASS


def test_the_45_tonne_loading_is_always_unverified():
    assert status(fixture("rectangle").report(), "Fire access: 45 t hard surface") is Z.UNVERIFIED


def test_a_block_that_is_high_rise_only_if_the_stilt_counts_has_its_fire_access_unverified():
    def lower(candidate):
        set_floors(candidate, "T3", 6)  # exactly 21 m with the stilt, 18 m without
        move_tower(candidate, "T3", 0.0, 0.0)
    inputs = fixture("rectangle").edited(lower)
    c = check(inputs.report(), "Fire access: T3")
    assert c.by_reading[STILT_IN_RULE_HEIGHT]["not_counted"] is Z.NOT_CHECKED
    assert c.finding.status is Z.UNVERIFIED
