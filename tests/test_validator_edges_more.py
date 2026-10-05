"""More edges, from an automatic mutation run over the code the review round added or changed:
how near a gate must be to the boundary, how wide an entrance may be, the compass a boundary
faces, a ramp a hair short of its width or length, a pocket partly off the plot, what the ledger
claims, and what a claim the library cannot compare costs. Each pins a mutation the first tests
let through."""

from dataclasses import replace

import pytest
from shapely import affinity
from shapely.geometry import Polygon, box
from validator_helpers import check, fixture, rectangle, select, set_floors, shape, status

from siteplan import geometry
from siteplan.contracts.accounting import PhysicalUse
from siteplan.contracts.candidate import SiteProgram
from siteplan.contracts.common import Shape, Status
from siteplan.contracts.resolved_rules import MIXED_HEIGHT_SPACING, STILT_IN_RULE_HEIGHT
from siteplan.validator import accounting, context, drawn, zones
from siteplan.validator.open_space import qualifying
from siteplan.validator.readings import COUNTED
from siteplan.validator.shapes import edge_segments, polygon_of, width_along_edge

TEST_CLASS = "normative"
Z = Status
ENTRANCE = "Fire access: entrance"
SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _counted(inputs):
    return inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))


# --- the gate -----------------------------------------------------------------------------------


@pytest.mark.parametrize("inset, expected", [(0.4, Z.PASS), (0.6, Z.FAIL)])
def test_a_gate_within_half_a_metre_of_the_boundary_stands_in_it(inset, expected):
    def gate(candidate):
        candidate.circulation.gates[0].shape = rectangle(3.0, inset, 12.0, inset + 2.0)
    assert status(fixture("rectangle").edited(gate).report(), ENTRANCE) is expected


@pytest.mark.parametrize("width, expected", [(18.0, Z.PASS), (18.1, Z.UNVERIFIED)])
def test_an_entrance_may_be_as_wide_as_the_widest_main_approach_road_and_no_wider(width, expected):
    def gate(candidate):
        candidate.circulation.gates[0].shape = rectangle(3.0, 0.0, 3.0 + width, 2.0)
        candidate.circulation.gates[0].width_m = width
    assert status(fixture("rectangle").edited(gate).report(), ENTRANCE) is expected


# --- the compass a boundary faces ---------------------------------------------------------------


@pytest.mark.parametrize("bearing, name", [(0, "N"), (22, "N"), (23, "NE"), (45, "NE"), (90, "E"),
                                           (135, "SE"), (180, "S"), (225, "SW"), (270, "W"),
                                           (315, "NW"), (337, "NW"), (338, "N"), (359, "N")])
def test_a_bearing_is_the_nearest_of_the_eight_compass_points(bearing, name):
    assert zones.compass_name(bearing) == name


def test_the_angle_between_two_bearings_goes_the_short_way_round():
    assert geometry.angle_between(350.0, 10.0) == pytest.approx(20.0)
    assert geometry.angle_between(10.0, 350.0) == pytest.approx(20.0)
    assert geometry.angle_between(0.0, 180.0) == pytest.approx(180.0)


def test_every_stretch_of_a_boundary_faces_away_from_the_plot():
    faces = {zones.compass_name(bearing) for _, bearing in zones.boundary_edges(box(0, 0, 100, 50))}
    assert faces == {"N", "E", "S", "W"}
    by_side = {zones.compass_name(b): e.length for e, b in zones.boundary_edges(box(0, 0, 100, 50))}
    assert by_side == pytest.approx({"S": 100.0, "N": 100.0, "E": 50.0, "W": 50.0})


def test_a_gate_in_a_corner_stands_in_both_the_sides_that_meet_there():
    plot = box(0.0, 0.0, 100.0, 50.0)
    corner = box(-1.0, -1.0, 3.0, 3.0)
    assert sorted(zones.compass_name(b) for b in zones.bearings_near(plot, corner, 0.5)) == [
        "S", "W"]
    middle = box(40.0, -1.0, 49.0, 1.0)
    assert [zones.compass_name(b) for b in zones.bearings_near(plot, middle, 0.5)] == ["S"]


# --- shapes -------------------------------------------------------------------------------------


def test_a_triangular_hole_is_a_ring_and_stays():
    holed, flaw = polygon_of(Shape(outer=SQUARE, holes=[[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0)]]))
    assert flaw == "" and holed.area == pytest.approx(100.0 - 2.0)


def test_a_ring_too_short_is_dropped_and_a_triangle_beside_it_stays():
    # The contract refuses a hole of two points since 1.1; the validator still copes with one
    # put together without that check.
    holed, flaw = polygon_of(Shape.model_construct(
        outer=SQUARE, holes=[[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0)], [(5.0, 5.0), (6.0, 6.0)]]))
    assert "a hole too short to be a ring was dropped" in flaw
    assert holed.area == pytest.approx(100.0 - 2.0)


def test_a_zero_length_edge_of_a_boundary_is_not_an_edge():
    plot = Polygon([(0, 0), (10, 0), (10, 0), (10, 10), (0, 10)])  # the corner given twice
    assert len(edge_segments(plot)) == 4


def test_the_width_of_nothing_along_a_boundary_is_nothing():
    assert width_along_edge(Polygon(), box(0, 0, 10, 10)) == 0.0
    assert width_along_edge(box(2, -1, 7, 1), box(0, 0, 10, 10)) == pytest.approx(5.0)


# --- the club house against a tower at the Table IV seam ----------------------------------------


def test_a_club_house_too_close_to_a_block_exactly_21_m_high_fails():
    """1.1: exactly 21 m is Table IV's first row, which asks 7 m; 5 m is short of it."""
    def close(candidate):
        set_floors(candidate, "T1", 6)  # 21 m with the stilt
        club = candidate.program.club_house
        club.shape = shape(affinity.translate(club.shape.to_shapely(), -4.0, 0.0))  # 5 m off T1
    inputs = _counted(fixture("rectangle")).with_rules(
        lambda r: select(r, MIXED_HEIGHT_SPACING, "taller_governs")).edited(close)
    assert status(inputs.report(), "Club house gap to T1") is Z.FAIL


def test_where_each_block_keeps_its_own_gap_a_club_house_the_towers_gap_away_passes():
    inputs = _counted(fixture("rectangle")).with_rules(
        lambda r: select(r, MIXED_HEIGHT_SPACING, "each_own"))
    assert status(inputs.report(), "Club house gap to T1") is Z.PASS  # 9.02 m: the tower's 9 m


# --- the open space -----------------------------------------------------------------------------


def _ground(inputs):
    return context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)


def _alone(*pockets):
    def edit(candidate):
        candidate.towers = []
        candidate.circulation.roads = []
        candidate.circulation.fire_hardstanding = []
        candidate.program = SiteProgram(open_space=[rectangle(*p) for p in pockets])
    return edit


def test_a_pocket_partly_off_the_plot_counts_only_the_part_on_it_and_says_so():
    ctx = _ground(fixture("rectangle").edited(_alone((-10.0, 40.0, 30.0, 60.0))))
    q = qualifying(ctx, "counted", "taller_governs")
    assert q.area_sqm == pytest.approx(30.0 * 20.0)
    assert q.removed["outside the net plot"] == pytest.approx(10.0 * 20.0)


def test_what_is_taken_out_for_being_narrow_or_small_is_said_only_when_something_was():
    wide = qualifying(_ground(fixture("rectangle").edited(_alone((60.0, 40.0, 70.0, 50.0)))),
                      "counted", "taller_governs")
    assert not [why for why in wide.removed if "narrower" in why]
    thin = qualifying(_ground(fixture("rectangle").edited(_alone((60.0, 40.0, 62.0, 80.0)))),
                      "counted", "taller_governs")
    assert [why for why in thin.removed if "narrower" in why]


# --- the cellar's ramp, a hair either side of its size ------------------------------------------


def _ramp(x1=133.1, y0=62.87, y1=86.86):
    def edit(candidate):
        candidate.program.ramps = [rectangle(127.7, y0, x1, y1)]
    return edit


@pytest.mark.parametrize("edit, ok", [
    (_ramp(x1=133.05), True),  # 5.35 m: within the few centimetres a drawing may fall short by
    (_ramp(x1=133.0), False),  # 5.30 m
    (_ramp(y1=86.83), True),  # 23.96 m long
    (_ramp(y1=86.81), False),  # 23.94 m
    (_ramp(y0=63.3, y1=87.25), True),  # 0.4 m from the road below it
    (_ramp(y0=63.5, y1=87.45), False)])  # 0.6 m from it, and 0.95 m from the loop above
def test_a_ramp_a_hair_inside_or_outside_its_size_and_its_distance_from_a_road(edit, ok):
    report = fixture("rectangle").edited(edit).report()
    assert (status(report, "Cellar ramp") is Z.PASS) is ok, check(report, "Cellar ramp").finding


def test_a_bay_partly_off_the_plot_is_off_it():
    def half_off(candidate):
        candidate.circulation.roads = []
        candidate.circulation.fire_hardstanding = []
        candidate.program = SiteProgram(bays=[rectangle(-1.0, 40.0, 1.5, 45.0)])
    c = check(fixture("rectangle").edited(half_off).report(), "Surface parking bays")
    assert "off the plot" in c.finding.measured


# --- the ledger and what was drawn --------------------------------------------------------------


def _claims(inputs):
    return accounting.claims_of(_ground(inputs))


def test_the_ledger_claims_every_drawn_thing_once_numbered_from_one():
    claims = _claims(fixture("rectangle"))
    refs = {c.use: {x.ref for x in claims if x.use is c.use} for c in claims}
    assert refs[PhysicalUse.RAMP] == {"ramp 1"}
    assert "bay 1" in refs[PhysicalUse.SURFACE_PARKING] and "bay 10" in refs[
        PhysicalUse.SURFACE_PARKING]
    assert refs[PhysicalUse.SOFT_OPEN_SPACE] == {"open space 1", "open space 2"}
    assert {PhysicalUse.FIRE_HARDSTANDING, PhysicalUse.GREEN_STRIP} <= set(refs)


def test_a_candidate_with_no_club_house_or_cellars_says_so_in_what_it_drew():
    inputs = fixture("rectangle").edited(lambda c: (
        setattr(c.program, "club_house", None), setattr(c.program, "cellars", None)))
    d = drawn.read(inputs.candidate, inputs.brief)
    assert d.club_floors == 0 and d.cellar_levels == 0 and not d.cellar_drawn


def test_a_flaw_in_one_of_a_roads_shapes_names_which():
    crossing = shape(Polygon([(0, 0), (10, 10), (10, 0), (0, 10)]))

    def two_shapes(candidate):
        road = candidate.circulation.roads[0]
        road.shapes = [road.shapes[0], crossing]
    flaws = drawn.read(fixture("rectangle").edited(two_shapes).candidate,
                       fixture("rectangle").brief).flaws
    assert len(flaws) == 1 and flaws[0].startswith("road road-1, shape 2: ")

    def one_shape(candidate):
        candidate.circulation.roads[0].shapes = [crossing]
    only = drawn.read(fixture("rectangle").edited(one_shape).candidate,
                      fixture("rectangle").brief).flaws
    assert only[0].startswith("road road-1: ")


# --- what a claim the library cannot compare costs ----------------------------------------------


def test_a_claimed_ledger_the_contract_cannot_even_read_blocks_a_pass():
    def malformed(candidate):
        candidate.partition.entries[0].shapes = [Shape.model_construct(
            outer=SQUARE, holes=[[(1.0, 1.0), (2.0, 2.0)]])]
    report = fixture("rectangle").edited(malformed).report()
    found = [d for d in report.cross_checks if d.item == "partition could not be compared"]
    assert found and found[0].blocks_pass


def test_an_envelope_the_library_cannot_compare_is_recorded_as_the_envelopes_and_never_blocks(
        monkeypatch):
    from shapely.errors import GEOSException

    def give_up(*args, **kwargs):
        raise GEOSException("made up")
    monkeypatch.setattr("siteplan.validator.cross_checks.envelope_checks", give_up)
    inputs = fixture("rectangle")
    report = replace(inputs).report(envelope=True)
    found = [d for d in report.cross_checks if d.item == "envelope could not be compared"]
    assert len(found) == 1 and found[0].source == "envelope" and not found[0].blocks_pass

