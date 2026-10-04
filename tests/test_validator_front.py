"""The front of the plot held apart from its other sides (contracts 1.2: `Band.front_setback_m`).

A band gives its setback for every side but the front and a front figure for the stretches of the
plot line that face the side the access road runs on (rule 5 Table III's Building Line; rule
7(a)(xi) for a high-rise). The validator holds each to its own figure, in the setback check, the
club house, the zones the other checks use, the design targets and the envelope cross-check.

Every band is MADE UP (tests/validator_low_helpers.py); no figure is a value of the order.
"""

import pytest
from shapely import affinity
from validator_helpers import check, fixture, move_tower, select, shape, status
from validator_low_helpers import (
    all_low,
    low_band,
    spacing_open,
    with_bands_below,
    with_low_bands,
)

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT, BandKind
from siteplan.validator import context, zones

TEST_CLASS = "normative"
Z = Status
COUNTED, NOT_COUNTED = "counted", "not_counted"
SETBACK = "All-round setback: T2"
# 15 m is band B: 5.3 m at the front, 3.7 m on the other sides. Made up, as every figure here.
FRONT_BANDS = (low_band(0, 12, setback=2.3, front=4.1, gap=3.1, road=0.0),
               low_band(12, 18, setback=3.7, front=5.3, gap=4.3, road=8.4),
               low_band(18, 21, setback=4.9, front=6.7, gap=5.7, road=11.6,
                        up_to_inclusive=False))


def _with_fronts(inputs=None):
    return with_bands_below(all_low(inputs or fixture("rectangle")), FRONT_BANDS)


def _access_side(side):
    return lambda site: setattr(site.access.side, "value", side)


def _t2_from_the_south(metres):
    """T2 stood 29.71 m from the south boundary, the side the fixture's access road runs on."""
    return lambda candidate: move_tower(candidate, "T2", 0.0, metres - 29.71)


def _t2_from_the_west(metres):
    return lambda candidate: move_tower(candidate, "T2", metres - 11.01, 0.0)


# --- the check ---------------------------------------------------------------------------------


def test_the_stretches_facing_the_access_road_are_held_to_the_front_figure():
    """T2 is 15 m: 5.3 m at the front, 3.7 m elsewhere. 4.5 m from the south boundary, where the
    access road runs, is short of the front figure; 6.0 m is not."""
    short = check(_with_fronts().edited(_t2_from_the_south(4.5)).report(), SETBACK)
    assert short.finding.status is Z.FAIL
    assert short.finding.measured.startswith("4.50 m at the front, 11.01 m on the other sides")
    assert ">= 5.30 m at the front (the S side), >= 3.70 m on the other sides" in (
        short.finding.required)
    assert "stretch of the plot line facing the side the access road runs on" in (
        short.finding.note)
    assert status(_with_fronts().edited(_t2_from_the_south(6.0)).report(), SETBACK) is Z.PASS


def test_the_same_distance_from_a_side_that_is_not_the_front_is_held_to_the_setback():
    """The front is where the access road runs: the same 4.5 m from the south boundary clears the
    other sides' 3.7 m when the road is on the north."""
    inputs = _with_fronts().edited(_t2_from_the_south(4.5))
    assert status(inputs.with_site(_access_side("S")).report(), SETBACK) is Z.FAIL
    assert status(inputs.with_site(_access_side("N")).report(), SETBACK) is Z.PASS


def test_every_side_but_the_front_is_held_to_the_setback():
    inputs = _with_fronts().edited(_t2_from_the_west(3.0))  # 3.0 m from the west boundary
    c = check(inputs.report(), SETBACK)
    assert c.finding.status is Z.FAIL and "3.00 m on the other sides" in c.finding.measured
    assert status(_with_fronts().edited(_t2_from_the_west(3.8)).report(), SETBACK) is Z.PASS


def test_a_front_that_cannot_be_placed_leaves_a_block_between_the_two_figures_unverified():
    """With the access road's side not known the block passes only if it clears the larger figure
    everywhere and fails only if it misses the smaller one somewhere."""
    def short_of_the_front(metres):
        return (_with_fronts().edited(_t2_from_the_south(metres))
                .with_site(_access_side(None)).report())
    between = check(short_of_the_front(4.5), SETBACK)  # over 3.7 m, under 5.3 m
    assert between.finding.status is Z.UNVERIFIED
    assert "which side is the front is not known" in between.finding.measured
    assert "access road's side is not known" in between.finding.note
    assert status(short_of_the_front(3.0), SETBACK) is Z.FAIL  # under both
    assert status(short_of_the_front(6.0), SETBACK) is Z.PASS  # over both


def test_a_band_with_no_front_figure_is_held_all_round_and_says_so():
    c = check(with_low_bands(all_low(fixture("rectangle"))).report(), SETBACK)
    assert c.finding.required == ">= 3.70 m to the net plot line"
    assert "gives no separate front figure" in c.finding.note


def test_a_front_figure_equal_to_the_setback_is_one_figure():
    bands = (low_band(0, 12, setback=2.3, front=2.3, road=0.0),
             low_band(12, 18, setback=3.7, front=3.7, road=8.4),
             low_band(18, 21, setback=4.9, front=4.9, road=11.6, up_to_inclusive=False))
    c = check(with_bands_below(all_low(fixture("rectangle")), bands).report(), SETBACK)
    assert c.finding.required == ">= 3.70 m to the net plot line"


def test_a_high_rise_band_with_a_higher_front_holds_the_front_to_it():
    """Rule 7(a)(xi): a high-rise's front is the higher of Table IV's figure and the Building
    Line, which the resolver puts on the band. Here the 24-27 m band asks 11 m at the front and
    keeps its 9 m on the other sides; T2 is 27 m with the stilt counted."""
    def higher_front(rules):
        next(b for b in rules.height.bands if b.kind is BandKind.HIGH_RISE
             and b.above_m == 24.0).front_setback_m = 11.0
    base = fixture("rectangle").with_rules(higher_front).with_rules(
        lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))
    assert status(base.report(), SETBACK) is Z.PASS  # 29.71 m from the south boundary
    c = check(base.edited(_t2_from_the_south(10.0)).report(), SETBACK)
    assert c.finding.status is Z.FAIL and ">= 11.00 m at the front" in c.finding.required
    assert "Table IV" in c.finding.clause  # the band's own table, as before


def test_the_club_house_keeps_its_bands_front_apart_from_its_sides():
    """The 6 m club house is band A: 4.1 m at the front, 2.3 m on the other sides."""
    def club_south_edge_at(metres):
        def edit(candidate):
            club = candidate.program.club_house
            bounds = club.shape.to_shapely().bounds
            club.shape = shape(affinity.translate(club.shape.to_shapely(), 0.0,
                                                  metres - bounds[1]))
        return edit
    inputs = _with_fronts().edited(club_south_edge_at(3.0))
    assert status(inputs.with_site(_access_side("S")).report(), "Club house: setback") is Z.FAIL
    assert status(inputs.with_site(_access_side("N")).report(), "Club house: setback") is Z.PASS


def test_where_a_band_gives_no_gap_of_its_own_two_low_blocks_keep_the_sides_figure():
    """Rule 5(f)(xiii): between two low blocks, the taller block's side setback, never its front."""
    bands = (low_band(0, 12, setback=2.3, front=4.1, road=0.0),
             low_band(12, 18, setback=3.7, front=5.3, road=8.4),
             low_band(18, 21, setback=4.9, front=6.7, road=11.6, up_to_inclusive=False))
    inputs = with_bands_below(all_low(fixture("rectangle")), bands).edited(
        lambda c: move_tower(c, "T3", -5.02, 0.0))  # T2/T3 gap 4.00 m
    c = check(spacing_open(inputs).report(), "Gap between blocks: T2 / T3")
    assert c.finding.status is Z.PASS and ">= 3.70 m" in c.finding.required


# --- what the other checks build on it ---------------------------------------------------------


def _ctx(inputs):
    return context.build(inputs.site, inputs.rules, inputs.brief, inputs.candidate)


def test_the_setback_zone_is_deeper_along_the_front_than_along_the_other_sides():
    """On the 150 x 100 m plot, 5.3 m along the south boundary and 3.7 m along the other three
    leave an inner 142.6 x 91 m: the zone is the rest."""
    inputs = _with_fronts()
    ctx = _ctx(inputs)
    assert zones.setback_depths(ctx, COUNTED) == (5.3, 3.7)
    assert zones.setback_zone(ctx, COUNTED).area == pytest.approx(15000 - 142.6 * 91.0)
    assert zones.deepest_setback_m(ctx, COUNTED) == 5.3
    unknown = _ctx(inputs.with_site(_access_side(None)))  # no front to place: the larger all round
    assert zones.setback_zone(unknown, COUNTED).area == pytest.approx(
        15000 - (150 - 10.6) * (100 - 10.6))


def test_a_ramp_may_not_stand_in_the_deeper_front_setback():
    """The front setback is wholly forbidden to a ramp, down to the front figure's depth."""
    ctx = _ctx(_with_fronts())
    forbidden, only_if_front = zones.ramp_zones(ctx, COUNTED)
    assert only_if_front.is_empty
    inside_front = zones.front_zone(ctx, 5.0)
    assert forbidden.intersection(inside_front).area == pytest.approx(inside_front.area)


def test_the_design_targets_hold_the_tightest_side_not_the_larger_figure_all_round():
    """T2 is 6.0 m from the front and 11.01 m from the other sides: what it keeps in hand is
    0.7 m at the front, not a shortfall against 5.3 m measured from its nearest side."""
    report = _with_fronts().edited(_t2_from_the_south(6.0)).report()
    rows = [r for r in report.design_targets if r.item.value == "setback" and "T2" in r.subject]
    assert rows
    for row in rows:
        assert row.subject == "T2 front"
        assert (row.legal_minimum, row.provided) == (pytest.approx(5.3), pytest.approx(6.0))
        assert row.meets_target
    t2 = next(t for t in report.recomputed.towers if t.name == "T2")
    assert t2.required_setback_m_by_reading == {COUNTED: 5.3, NOT_COUNTED: 5.3}  # the larger
    assert t2.setback_m == pytest.approx(6.0)  # the nearest side
