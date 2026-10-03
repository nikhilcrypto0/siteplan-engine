"""Legal layouts the validator once failed, found by a review that drew what an architect or an
optimizer would plausibly draw: a gate at a corner of the plot, a second entrance on a second
road, a plot turned a hair, a ramp or a cul-de-sac that bends, a loop drawn as chords of an arc,
a shape that only touches itself, rules that name a different Table V column than the site does.
Each of these failed (or was UNVERIFIED) when every input was known and the rules settle it."""

import pytest
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from validator_helpers import check, fixture, rectangle, shape, shapes, status

from siteplan.contracts.candidate import RoadKind, RoadPiece, SiteProgram
from siteplan.contracts.common import Status
from siteplan.validator import zones
from siteplan.validator.readings import TABLE_V_COLUMN
from siteplan.validator.shapes import mended, snapped

TEST_CLASS = "normative"
Z = Status
ENTRANCE = "Fire access: entrance"
LOOP = "Internal roads: loop and other roads"


def _gate(candidate, x0, y0, x1, y1, declared):
    candidate.circulation.gates[0].shape = rectangle(x0, y0, x1, y1)
    candidate.circulation.gates[0].width_m = declared


# --- gates -------------------------------------------------------------------------------------


def test_a_gate_at_the_corner_of_the_plot_lies_along_the_edge_nearer_its_middle():
    """Drawn 9.01 m along the south edge and touching the west edge at its end, it was measured
    along the west edge and found 2 m wide: 50 of 207 plots a generator laid out failed on it."""
    def corner(candidate):
        _gate(candidate, 0.0, 0.0, 9.01, 2.0, 9.0)
    c = check(fixture("rectangle").edited(corner).report(), ENTRANCE)
    assert c.finding.status is Z.PASS and "9.01 m wide" in c.finding.measured


def test_a_deep_narrow_gate_near_a_corner_is_still_as_narrow_as_it_is():
    def deep(candidate):
        _gate(candidate, 3.0, 0.0, 4.0, 12.0, 1.0)  # the west edge is 3 m off: not one it stands in
    c = check(fixture("rectangle").edited(deep).report(), ENTRANCE)
    assert c.finding.status is Z.FAIL and "1.00 m wide" in c.finding.measured


def test_a_second_entrance_on_another_road_the_survey_measures_is_doubtful_not_failed():
    def west_road(site):
        site.roads.append(site.roads[0].model_copy(update={"id": 2, "side": "W"}))

    def west_gate(candidate):
        candidate.circulation.gates.append(candidate.circulation.gates[0].model_copy(
            update={"shape": rectangle(0.0, 40.0, 2.0, 49.0)}))
    c = check(fixture("rectangle").with_site(west_road).edited(west_gate).report(), ENTRANCE)
    assert c.finding.status is Z.UNVERIFIED and "not the access road" in c.finding.measured
    # with no road known on the west a gate there leads nowhere
    assert status(fixture("rectangle").edited(west_gate).report(), ENTRANCE) is Z.FAIL


@pytest.mark.parametrize("bearing, side, expected", [
    (179.95, "SW", True), (270.05, "SW", True), (100.0, "SW", False),  # a diagonal reaches both
    (135.0, "S", True), (134.0, "S", False), (225.0, "S", True), (226.0, "S", False)])
def test_a_road_side_is_the_edges_within_45_degrees_and_a_diagonal_one_reaches_both_sides(
        bearing, side, expected):
    assert zones.faces(bearing, side) is expected


def test_a_plot_turned_a_hair_keeps_both_edges_a_diagonal_side_faces():
    for turn in (-0.05, 0.0, 0.05):
        plot = affinity.rotate(box(0, 0, 100, 50), turn, origin=(0, 0))
        assert len(zones.front_edges(plot, "SW")) == 2, turn


# --- ramps and cul-de-sacs that bend ------------------------------------------------------------


def _ramp(geometry):
    def edit(candidate):
        candidate.program.ramps = [shape(geometry)]
    return edit


def test_a_ramp_that_bends_or_folds_is_unverified_where_a_straight_short_one_fails():
    straight_short = box(127.7, 62.87, 133.1, 80.0)  # 17.1 m: short of the 24 m a 3 m drop needs
    c = check(fixture("rectangle").edited(_ramp(straight_short)).report(), "Cellar ramp")
    assert c.finding.status is Z.FAIL and "too short" in c.finding.measured
    l_shaped = unary_union([box(127.7, 62.87, 133.1, 79.87), box(118.0, 74.47, 133.1, 79.87)])
    folded = unary_union([box(120, 63, 134, 68.4), box(120, 69.0, 134, 74.4),
                          box(128.6, 63, 134, 74.4)])  # two legs side by side, 0.6 m apart
    for ramp in (l_shaped, folded):  # about 27 m and 29 m along their own middles
        c = check(fixture("rectangle").edited(_ramp(ramp)).report(), "Cellar ramp")
        assert c.finding.status is Z.UNVERIFIED, c.finding.measured
        assert "round a bend" in c.finding.measured


def test_a_cul_de_sac_that_bends_is_unverified_not_failed_on_the_length_of_its_box():
    def bent(candidate):
        candidate.towers, candidate.program = [], SiteProgram()
        candidate.circulation.fire_hardstanding = []
        body = unary_union([box(109.0, 16.0, 139.0, 24.0), box(109.0, 16.0, 117.0, 44.0),
                            Point(113.0, 44.0).buffer(9.0, quad_segs=32)])
        candidate.circulation.roads.append(RoadPiece(
            id="road-9", kind=RoadKind.CUL_DE_SAC, shapes=shapes(body), declared_width_m=8.0))
    c = check(fixture("rectangle").edited(bent).report(), "Internal roads: cul-de-sac road-9")
    assert c.finding.status is Z.UNVERIFIED and "bend" in c.finding.note


# --- shapes ---------------------------------------------------------------------------------------


def test_a_loop_road_exactly_9_m_wide_drawn_as_chords_of_arcs_is_9_m_wide():
    """Concentric arcs drawn as 16 chords a quarter are 8.989 m apart at the middle of a chord."""
    def rounded(rect, radius):
        return rect.buffer(-radius).buffer(radius, quad_segs=16)
    ring = rounded(box(2, 2, 148, 98), 18.0).difference(rounded(box(11, 11, 139, 89), 9.0))

    def redraw(candidate):
        next(r for r in candidate.circulation.roads if r.id == "road-1").shapes = shapes(ring)
    assert status(fixture("rectangle").edited(redraw).report(), LOOP) is Z.PASS


def test_a_shape_that_only_touches_itself_is_no_defect_but_one_that_crosses_itself_is():
    spike = Polygon([(0, 0), (10, 0), (10, 10), (5, 10), (5, 12), (5, 10), (0, 10)])
    fixed, flaw = mended(spike)
    assert not spike.is_valid and fixed.is_valid and flaw == ""
    assert fixed.area == pytest.approx(100.0)
    bowtie, flaw = mended(Polygon([(0, 0), (10, 10), (10, 0), (0, 10)]))
    assert flaw and bowtie.area == pytest.approx(50.0)


def test_shapes_drawn_to_share_an_edge_share_it_exactly_on_the_micrometre_grid():
    left, right = box(0, 0, 10, 10), box(10 + 3e-10, 0, 20, 10)
    assert not left.touches(right)  # a hair apart as drawn
    assert snapped(left).touches(snapped(right))  # one edge once snapped


# --- Table V -------------------------------------------------------------------------------------


def test_rules_that_name_one_table_v_column_and_a_site_inside_cure_are_held_to_both():
    def inside_cure(site):
        site.jurisdiction.inside_cure.value = True
    report = fixture("rectangle").with_site(inside_cure).report()
    assert status(report, "Table V column: rules and site agree") is Z.UNVERIFIED
    columns = check(report, "Parking (Table V)").by_reading[TABLE_V_COLUMN]
    assert set(columns) == {"ELSEWHERE", "GHMC_OR_CURE"}
    agreeing = {c.finding.rule for c in fixture("rectangle").report().legal}
    assert "Table V column: rules and site agree" not in agreeing
