"""The machinery that runs a check under every reading and combines the results, and the zones
and the site's own geometry the checks are built on."""

import pytest
from shapely.geometry import Point, box
from validator_helpers import fixture, rectangle, select

from siteplan.contracts.common import Finding, Status
from siteplan.contracts.resolved_rules import (
    ALL,
    CIRCULATION_IN_SETBACK,
    MIXED_HEIGHT_SPACING,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.contracts.validation import Check, Family
from siteplan.validator import context, drawn, site_geometry, zones
from siteplan.validator.readings import (
    Cell,
    check_from,
    combine_statuses,
    plain,
    run,
    unknown_reading,
    verdict,
)

TEST_CLASS = "normative"
Z = Status
SPACING = MIXED_HEIGHT_SPACING


def _ctx(name="rectangle", **edits):
    inputs = fixture(name)
    return context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate), inputs


# --- running a check under every reading -------------------------------------------------------


def test_a_check_runs_once_per_reading_and_the_status_combines_as_the_contract_says():
    rules = fixture("rectangle").rules
    seen = []

    def cell(a):
        seen.append(dict(a))
        return Cell(verdict(a[STILT_IN_RULE_HEIGHT] == "not_counted"), f"under {a}", "x")
    ev = run(rules, [STILT_IN_RULE_HEIGHT], cell)
    assert [a[STILT_IN_RULE_HEIGHT] for a in seen] == ["counted", "not_counted"]
    assert ev.status is Z.UNVERIFIED
    assert ev.by_reading == {STILT_IN_RULE_HEIGHT: {"counted": Z.FAIL, "not_counted": Z.PASS}}
    assert "stilt_in_rule_height: counted FAIL, not_counted PASS" in ev.readings_note


def test_a_settled_reading_is_evaluated_alone():
    rules = fixture("rectangle").rules  # the fixtures settle the fire radius on 'outer_edge'
    ev = run(rules, ["fire_turning_radius"], lambda a: Cell(Z.PASS, "ok"))
    assert [a["fire_turning_radius"] for a, _ in ev.cells] == ["outer_edge"]
    assert ev.varying == ()


def test_every_combination_of_the_readings_is_evaluated():
    rules = fixture("rectangle").rules.model_copy(deep=True)
    select(rules, STILT_IN_RULE_HEIGHT, "counted")
    rules.interpretation(SPACING).selected = ALL
    rules.interpretation(CIRCULATION_IN_SETBACK).selected = ALL
    ev = run(rules, [STILT_IN_RULE_HEIGHT, SPACING, CIRCULATION_IN_SETBACK],
             lambda a: Cell(Z.PASS, "ok"))
    assert len(ev.cells) == 4 and ev.varying == (SPACING, CIRCULATION_IN_SETBACK)


def test_a_question_that_is_not_an_interpretation_takes_its_readings_from_the_caller():
    rules = fixture("rectangle").rules
    ev = run(rules, ["jurisdiction.table_v_column"], lambda a: Cell(Z.PASS, "ok"),
             extra={"jurisdiction.table_v_column": ["GHMC_OR_CURE", "ELSEWHERE"]})
    assert len(ev.cells) == 2


def test_the_text_names_the_readings_a_result_holds_under_and_leaves_out_irrelevant_ones():
    rules = fixture("rectangle").rules.model_copy(deep=True)
    rules.interpretation(CIRCULATION_IN_SETBACK).selected = ALL

    def cell(a):  # depends on the stilt only; the circulation reading makes no difference
        return Cell(Z.PASS, "27 m" if a[STILT_IN_RULE_HEIGHT] == "counted" else "24 m")
    ev = run(rules, [STILT_IN_RULE_HEIGHT, CIRCULATION_IN_SETBACK], cell)
    assert ev.measured == "counted: 27 m; not_counted: 24 m"


def test_statuses_that_agree_stay_as_they_are_including_info_and_not_checked():
    assert combine_statuses([Z.INFO, Z.INFO]) is Z.INFO
    assert combine_statuses([Z.NOT_CHECKED, Z.NOT_CHECKED]) is Z.NOT_CHECKED
    assert combine_statuses([Z.PASS, Z.PASS]) is Z.PASS and combine_statuses([Z.FAIL]) is Z.FAIL
    assert combine_statuses([Z.PASS, Z.NOT_CHECKED]) is Z.UNVERIFIED
    assert combine_statuses([Z.PASS, Z.FAIL]) is Z.UNVERIFIED


def test_a_reading_the_validator_cannot_evaluate_is_a_cell_that_says_so():
    cell = unknown_reading("stilt_in_rule_height", "half_counted")
    assert cell.status is Z.UNVERIFIED and "half_counted" in cell.measured


def test_a_check_built_from_readings_carries_them_and_a_plain_one_carries_none():
    rules = fixture("rectangle").rules
    ev = run(rules, [STILT_IN_RULE_HEIGHT], lambda a: Cell(Z.PASS, "ok", "needs ok", "a note"))
    c = check_from(ev, family=Family.SETBACK, rule="r", clause="c", subject="T1", note="n")
    assert isinstance(c, Check) and c.subject == "T1" and c.by_reading
    assert c.finding == Finding("r", Z.PASS, "ok", "needs ok", "c", "n a note")
    assert plain(Family.OTHER, "r", Z.INFO, "m", "q", "c").by_reading == {}


# --- zones -----------------------------------------------------------------------------------


def test_the_setback_zone_is_the_plots_own_edge_as_deep_as_the_deepest_setback():
    ctx, inputs = _ctx()
    net = ctx.net
    assert zones.deepest_setback_m(ctx, "counted") == 9.0
    assert zones.deepest_setback_m(ctx, "not_counted") == 8.0
    zone = zones.setback_zone(ctx, "counted")
    assert zone.area == pytest.approx(net.area - box(9, 9, 141, 91).area)
    assert zones.setback_zone(ctx, "no such reading") is None
    # The small plot's 15 m block is Table III's (A2: row 11, 6 m), with the 3 m Building Line on
    # its 12 m road in front (the south side).
    small = _ctx("small_plot")[0]
    assert zones.deepest_setback_m(small, "counted") == 6.0
    assert zones.setback_zone(small, "counted").area == pytest.approx(
        small.net.area - box(6, 3, 54, 44).area)


@pytest.mark.parametrize("side, edge", [("S", (0, 0, 150, 0)), ("N", (0, 100, 150, 100)),
                                        ("W", (0, 0, 0, 100)), ("E", (150, 0, 150, 100))])
def test_the_front_of_the_plot_is_the_boundary_that_faces_the_access_side(side, edge):
    net = box(0, 0, 150, 100)
    front = zones.front_edges(net, side)
    assert len(front) == 1
    assert list(front[0].coords) in ([edge[:2], edge[2:]], [edge[2:], edge[:2]])


def test_a_corner_plot_faces_the_access_side_on_every_edge_within_45_degrees():
    from shapely.geometry import Polygon, box

    diamond = Polygon([(0, 50), (50, 0), (100, 50), (50, 100)])
    assert len(zones.front_edges(diamond, "SW")) == 1
    assert len(zones.front_edges(diamond, "S")) == 2  # exactly 45 degrees either side is front
    # a diagonal side is both of the sides it lies between (found by review: it used to be none,
    # so a ramp in the front setback of a plot reached from the north-east passed)
    for side, faces in {"NE": {"N", "E"}, "SE": {"S", "E"}, "SW": {"S", "W"},
                        "NW": {"N", "W"}}.items():
        edges = zones.front_edges(box(0, 0, 100, 50), side)
        assert {zones.compass_name(b) for e, b in zones.boundary_edges(box(0, 0, 100, 50))
                if any(e.equals(f) for f in edges)} == faces


def test_the_front_zone_is_the_land_within_the_setback_of_the_front():
    ctx, _ = _ctx()
    front = zones.front_zone(ctx, 9.0)
    assert front.bounds[1] == pytest.approx(0.0) and front.bounds[3] <= 9.0 + 1e-6
    assert front.area >= 150 * 9.0 - 1.0


def test_where_a_ramp_may_not_be():
    """A 9 m setback leaves the outer 2 m of a side or rear one to a ramp (7 m clear), and none
    of the front one."""
    ctx, _ = _ctx()
    forbidden, front_only = zones.ramp_zones(ctx, "counted")
    assert front_only.is_empty  # the access side is known
    assert not forbidden.contains(Point(1.0, 50.0))  # 1 m in from the west side: allowed
    assert not forbidden.contains(Point(75.0, 99.0))  # and from the rear
    assert forbidden.contains(Point(5.0, 50.0))  # 5 m in leaves under 7 m clear
    assert forbidden.contains(Point(75.0, 1.0))  # the front is never allowed
    assert not forbidden.contains(Point(75.0, 50.0))  # the middle of the plot is outside it


def test_with_the_access_side_unknown_the_rest_of_the_setback_is_forbidden_only_if_it_is_front():
    inputs = fixture("rectangle").with_site(lambda s: setattr(s.access.side, "value", None))
    ctx = context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)
    forbidden, if_front = zones.ramp_zones(ctx, "counted")
    assert not forbidden.contains(Point(1.0, 1.0)) and if_front.contains(Point(1.0, 1.0))
    assert forbidden.contains(Point(5.0, 50.0))


def test_the_gap_between_two_blocks_is_the_ground_between_them_within_their_gap_of_both():
    ctx, _ = _ctx()
    (pair, zone), *_ = zones.gap_zones(ctx, "counted", "taller_governs")
    assert pair == "T1/T2"
    t1, t2 = (next(t.footprint for t in ctx.towers if t.name == n) for n in ("T1", "T2"))
    assert zone.intersection(t1).area == 0 and zone.intersection(t2).area < 1e-6
    assert zone.area > 100
    assert all(t1.distance(Point(p)) <= 9.0 + 1e-6 for p in zone.representative_point().coords)


def test_the_green_strip_runs_along_the_boundary_where_the_setback_reaches_9_m():
    ctx, _ = _ctx()
    strip = zones.green_strip_zone(ctx, "counted")
    assert strip.area == pytest.approx(150 * 100 - 146 * 96, abs=1e-6)
    assert zones.green_strip_zone(ctx, "not_counted") is None


# --- the site's own geometry ---------------------------------------------------------------------


def test_the_water_buffer_is_the_class_width_round_the_lines_and_what_they_close():
    ctx, inputs = _ctx("nala_plot")
    (zone,) = ctx.land.water
    assert zone.buffer_m == 9.0 and zone.drawn
    assert ctx.land.keep_out_on_site.area == pytest.approx(18 * 120, abs=0.5)

    def close_it(site):  # a lake outline: a closed ring of lines closes a channel
        site.water[0].lines = [site.water[0].lines[0].model_copy(update={"points": [
            (60, 20), (90, 20), (90, 60), (60, 60), (60, 20)]})]
        site.water[0].water_class.value = "lake_under_10ha"
    closed = inputs.with_site(close_it)
    ctx2 = context.build(closed.site, closed.rules, closed.brief, closed.candidate)
    assert ctx2.land.keep_out.contains(box(65, 25, 85, 55))  # the water itself, inside the ring


def test_a_water_body_with_no_lines_or_with_a_class_the_rules_lack_has_no_buffer():
    ctx, inputs = _ctx("nala_plot")

    def erase(site):
        site.water[0].lines = []
    bare = inputs.with_site(erase)
    ctx = context.build(bare.site, bare.rules, bare.brief, bare.candidate)
    assert ctx.land.undrawn_water and ctx.land.keep_out.is_empty


def test_no_net_plot_gives_no_geometry():
    inputs = fixture("rectangle").with_site(lambda s: setattr(s, "net_plot", None))
    assert site_geometry.build(inputs.site, inputs.rules) is None
    assert context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate) is None


# --- what was drawn ----------------------------------------------------------------------------


def test_a_candidate_with_nothing_but_buildings_is_buildings_only():
    from siteplan.contracts.candidate import SiteProgram

    inputs = fixture("rectangle").edited(lambda c: (
        setattr(c, "circulation", type(c.circulation)()), setattr(c, "program", SiteProgram())))
    assert drawn.read(inputs.candidate, inputs.brief).buildings_only
    rectangle_ = fixture("rectangle")
    assert not drawn.read(rectangle_.candidate, rectangle_.brief).buildings_only


def test_an_amenitys_surface_is_what_the_brief_says_of_the_request_with_its_name():
    from siteplan.contracts.candidate import PlacedAmenity
    from siteplan.contracts.design_brief import AmenityRequest

    def add(candidate):
        candidate.program.amenities += [
            PlacedAmenity(name="Security cabin", shape=rectangle(150.0, 0.0, 154.0, 4.0)),
            PlacedAmenity(name="Play area", shape=rectangle(20.0, 13.0, 40.0, 20.0)),
            PlacedAmenity(name="PUMP HOUSE", shape=rectangle(60.0, 13.0, 64.0, 17.0))]

    def ask(brief):
        brief.program.amenities = [AmenityRequest(name="SECURITY CABIN", surface="HARD"),
                                   AmenityRequest(name="play area", surface="SOFT")]
    inputs = fixture("rectangle").edited(add).with_brief(ask)
    cabin, play, pump = drawn.read(inputs.candidate, inputs.brief).amenities
    assert cabin.hard and not cabin.unknown  # names match without regard to case
    assert play.surface == "SOFT" and not play.hard
    assert pump.unknown and not pump.hard  # a name says nothing: it was not asked for
