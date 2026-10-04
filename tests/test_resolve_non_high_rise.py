"""What the resolver gives below 21 m (stream A2): the bands of Table III's row for the site, each
with the setbacks, the road and the permission it carries, and how a block finds its band.

Made-up sites only. tests/test_non_high_rise.py holds the module the bands come from; here the
bands themselves, as the contract reads them.
"""

import pytest
from legal_fixtures import make_site
from shapely.geometry import box

from siteplan import rules as rules_py
from siteplan.contracts.common import Provenance
from siteplan.contracts.resolved_rules import (
    MIXED_HEIGHT_SPACING,
    STILT_IN_RULE_HEIGHT,
    BandKind,
    Eligibility,
    HeightMeasure,
)
from siteplan.legal.resolve import resolve

TEST_CLASS = "normative"
PLOT = box(0, 0, 150, 120)  # 18,000 m²: a group development scheme, a high-rise plot
ALLOWED, PROHIBITED, OPEN = Eligibility.ALLOWED, Eligibility.PROHIBITED, Eligibility.UNVERIFIED


def _low(rules):
    return [b for b in rules.height.bands if b.kind is BandKind.NON_HIGH_RISE]


def _high(rules):
    return [b for b in rules.height.bands if b.kind is BandKind.HIGH_RISE]


def _edges(band):
    return (band.above_m, band.up_to_m, band.above_inclusive, band.up_to_inclusive)


# --- The row, the setbacks, the front ---------------------------------------------------------


def test_a_group_scheme_on_a_60_ft_road_gets_row_11_and_a_front_reckoned_as_an_18_m_road():
    rules = resolve(make_site(PLOT, road_m=18.288))
    *lines, open_ = _low(rules)
    assert [_edges(b) for b in lines] == [(0.0, 7.0, False, True), (7.0, 15.0, False, True),
                                          (15.0, 18.0, False, False)]
    assert [(b.setback_m, b.gap_m, b.front_setback_m, b.min_road_m) for b in lines] == [
        (5.0, 5.0, 4.0, 12.0), (6.0, 6.0, 4.0, 12.0), (7.0, 7.0, 4.0, 12.0)]
    assert {b.measure for b in lines} == {HeightMeasure.HEIGHT_ABOVE_STILT}
    assert {b.permission for b in lines} == {ALLOWED} and all(b.modelled for b in lines)
    assert all("row 11" in b.clause and rules_py.TABLE_III_CLAUSE in b.clause for b in lines)
    assert {(b.green_strip_m, b.green_strip_sides) for b in lines} == {(1.0, "ALL")}
    assert (_edges(open_), open_.permission, open_.setback_m) == (
        (18.0, 21.0, True, False), OPEN, None)
    assert open_.measure is HeightMeasure.HEIGHT_ABOVE_STILT and open_.permission_note


def test_the_gap_between_two_blocks_is_the_taller_ones_side_setback():
    """Rule 5(f)(xiii): every line's gap is its own column 10, so the taller block's is the larger
    of the two, and the band's front does not enter it."""
    lines = _low(resolve(make_site(PLOT)))[:3]
    assert [b.gap_m for b in lines] == [b.setback_m for b in lines] == [5.0, 6.0, 7.0]
    assert max(lines[0].gap_m, lines[2].gap_m) == lines[2].gap_m


@pytest.mark.parametrize(("road_m", "front"), [(18.288, 4.0), (18.0, 4.0), (18.3, 5.0),
                                               (12.192, 3.0), (30.48, 6.0), (35.0, 7.5)])
def test_the_front_is_the_building_line_of_the_roads_reckoned_width(road_m, front):
    lines = _low(resolve(make_site(PLOT, road_m=road_m)))[:3]
    assert {b.front_setback_m for b in lines} == {front}


def test_a_front_larger_than_the_side_is_kept_apart_from_it():
    lines = _low(resolve(make_site(PLOT, road_m=35.0)))[:3]
    assert [(b.setback_m, b.front_setback_m, b.front_m) for b in lines] == [
        (5.0, 7.5, 7.5), (6.0, 7.5, 7.5), (7.0, 7.5, 7.5)]


@pytest.mark.parametrize(("plot", "row", "ups", "sides"), [
    (box(0, 0, 40, 30), 9, [7, 12, 15, 18], [3.5, 4.0, 5.0, 6.0]),  # 1,200 m²
    (box(0, 0, 30, 20), 7, [7, 12, 15], [2.5, 3.0, 3.5]),  # 600 m²
    (box(0, 0, 60, 50), 11, [7, 15, 18], [5.0, 6.0, 7.0]),  # 3,000 m²: not a group scheme
])
def test_a_plot_takes_the_lines_of_its_own_row(plot, row, ups, sides):
    lines = [b for b in _low(resolve(make_site(plot, road_m=18.288))) if b.setback_m is not None]
    assert [b.up_to_m for b in lines] == ups and [b.setback_m for b in lines] == sides
    assert all(f"row {row}" in b.clause for b in lines)


def test_a_plot_under_750_m2_stops_at_its_last_line_and_nothing_above_it_is_permitted():
    *lines, above = _low(resolve(make_site(box(0, 0, 30, 20), road_m=18.288)))  # 600 m²
    assert [b.up_to_m for b in lines] == [7.0, 12.0, 15.0]
    assert (_edges(above), above.permission, above.setback_m) == (
        (15.0, 21.0, False, False), PROHIBITED, None)
    assert "no order read permits" in above.permission_note


def test_a_plot_of_750_to_2000_m2_may_reach_18_to_21_m_only_through_tdr():
    *_, open_ = _low(resolve(make_site(box(0, 0, 40, 30), road_m=18.288)))  # 1,200 m²
    assert (_edges(open_), open_.permission) == ((18.0, 21.0, True, False), OPEN)
    assert "only through TDR" in open_.permission_note
    assert open_.status is Provenance.UNVERIFIED and open_.clause == rules_py.TDR_BAND_CLAUSE


# --- The road ---------------------------------------------------------------------------------


def test_the_road_a_band_asks_is_a_group_schemes_12_m_or_table_iis_9_m_below_15_m():
    scheme = _low(resolve(make_site(PLOT, road_m=18.288)))[:3]
    assert {b.min_road_m for b in scheme} == {12.0}
    plain = _low(resolve(make_site(box(0, 0, 60, 50), road_m=18.288)))[:3]  # 3,000 m²
    assert [b.min_road_m for b in plain] == [9.0, 9.0, 12.0]


def test_a_road_known_to_be_too_narrow_prohibits_and_the_note_says_which_clause_asks():
    rules = resolve(make_site(box(0, 0, 60, 50), road_m=9.5, road_status="USER_CONFIRMED"))
    low = _low(rules)
    assert [b.permission for b in low[:3]] == [ALLOWED, ALLOWED, PROHIBITED]
    assert rules_py.TABLE_III_TOP_TIER_CLAUSE in low[2].permission_note
    assert rules.height.permissible_non_high_rise().up_to_m == 15.0


def test_a_group_scheme_on_a_road_under_12_m_has_nothing_below_21_m_and_no_high_rise_either():
    rules = resolve(make_site(PLOT, road_m=11.9))
    assert {b.permission for b in _low(rules)} == {PROHIBITED}
    assert {rules.height.band_permission(b) for b in rules.height.bands} == {PROHIBITED}
    assert rules.height.permissible_non_high_rise(include_unverified=True) is None


def test_a_road_nobody_has_confirmed_leaves_the_bands_unverified_not_refused():
    rules = resolve(make_site(PLOT, road_m=18.288, road_status="UNVERIFIED",
                              row_status="UNVERIFIED_DRAWING_VALUE"))
    lines = _low(rules)[:3]
    assert {b.permission for b in lines} == {ALLOWED}  # the width meets what is asked
    assert {b.status for b in lines} == {Provenance.UNVERIFIED}  # and settles nothing
    narrow = resolve(make_site(PLOT, road_m=10.0, road_status="UNVERIFIED",
                               row_status="UNVERIFIED_DRAWING_VALUE"))
    assert {b.permission for b in _low(narrow)[:3]} == {OPEN}  # a drawing value refuses nothing


def test_with_no_road_given_no_front_is_guessed_and_nothing_is_allowed_below_21_m():
    rules = resolve(make_site(PLOT, road_m=None))
    lines = _low(rules)[:3]
    assert {b.front_setback_m for b in lines} == {None} and {b.permission for b in lines} == {OPEN}
    assert [b.setback_m for b in lines] == [5.0, 6.0, 7.0]
    assert rules.height.permissible_non_high_rise() is None
    assert rules.height.permissible_non_high_rise(include_unverified=True) is not None


def test_a_master_plan_width_beside_the_road_leaves_the_front_open_where_the_two_differ():
    rules = resolve(make_site(PLOT, road_m=12.0, master_plan_m=18.0))
    lines = _low(rules)[:3]
    assert {b.front_setback_m for b in lines} == {4.0}  # the larger: 3 m on 12 m, 4 m on 18 m
    assert {b.status for b in lines} == {Provenance.UNVERIFIED}
    assert {b.permission for b in lines} == {ALLOWED}  # both widths meet a scheme's 12 m


# --- The high-rise bands ----------------------------------------------------------------------


def test_the_high_rise_bands_are_allowed_and_the_sites_eligibility_comes_through_the_method():
    rules = resolve(make_site(box(0, 0, 40, 45)))  # 1,800 m²: a high-rise is prohibited
    assert rules.height.high_rise.eligibility is Eligibility.PROHIBITED
    assert {b.permission for b in _high(rules)} == {ALLOWED}
    assert {rules.height.band_permission(b) for b in _high(rules)} == {PROHIBITED}
    assert {rules.height.band_permission(b) for b in _low(rules)[:3]} == {ALLOWED}


def test_a_block_of_exactly_21_m_on_a_road_over_30_m_keeps_the_building_line_at_the_front():
    """Rule 7(a)(xi): the higher of Table IV column 4 (7 m) and the Building Line (7.5 m above a
    30 m road). Every row above has a column 4 over 7.5 m, so only this band says it."""
    rules = resolve(make_site(PLOT, road_m=35.0))
    exactly, next_row = _high(rules)[:2]
    assert (exactly.setback_m, exactly.front_setback_m, exactly.front_m) == (7.0, 7.5, 7.5)
    assert rules_py.BUILDING_LINE_HIGH_RISE_CLAUSE in exactly.clause
    assert exactly.status is Provenance.USER_CONFIRMED  # it rests on the road
    assert (next_row.setback_m, next_row.front_setback_m) == (8.0, None)
    assert all(b.front_setback_m is None for b in _high(resolve(make_site(PLOT, road_m=18.288))))


def test_on_an_unknown_road_the_21_m_band_is_unverified_for_its_front_and_the_rest_are_not():
    rules = resolve(make_site(PLOT, road_m=None))
    exactly, next_row = _high(rules)[:2]
    assert (exactly.front_setback_m, exactly.status) == (7.5, Provenance.UNVERIFIED)
    assert (next_row.front_setback_m, next_row.status) == (None, Provenance.VERIFIED)


def test_the_high_rise_planting_strip_is_the_2_m_one_where_the_setback_is_9_m_or_more():
    high = _high(resolve(make_site(PLOT, road_m=30.0)))
    assert [(b.setback_m, b.green_strip_m) for b in high[:5]] == [
        (7.0, None), (8.0, None), (9.0, 2.0), (10.0, 2.0), (11.0, 2.0)]


# --- How a block finds its band ---------------------------------------------------------------


@pytest.mark.parametrize(("above_stilt", "stilt", "counted", "kind", "up_to"), [
    (15.0, 3.0, True, BandKind.NON_HIGH_RISE, 15.0),  # 18 m of rule height, but Table III's row
    (15.0, 3.0, False, BandKind.NON_HIGH_RISE, 15.0),
    (15.1, 3.0, True, BandKind.NON_HIGH_RISE, 18.0),  # the '18**' line, not the open stretch
    (17.9, 3.0, False, BandKind.NON_HIGH_RISE, 18.0),
    (18.0, 3.0, False, BandKind.NON_HIGH_RISE, 21.0),  # the open stretch: no line, no setback
    (18.0, 3.0, True, BandKind.HIGH_RISE, 21.0),  # 21 m of rule height: a high-rise
    (21.0, 3.0, False, BandKind.HIGH_RISE, 21.0),
    (7.0, 0.0, True, BandKind.NON_HIGH_RISE, 7.0),
])
def test_a_block_is_found_by_its_height_above_the_stilt_and_its_class_by_its_rule_height(
        above_stilt, stilt, counted, kind, up_to):
    heights = resolve(make_site(PLOT)).height
    band = heights.band_for_block(above_stilt, stilt, stilt_counted=counted)
    assert (band.kind, band.up_to_m) == (kind, up_to)


def test_the_rule_height_alone_would_put_a_block_a_line_too_high():
    """15 m above a 3 m stilt is 18 m of rule height: found there it is the open stretch, which
    has no setback; found as the contract finds it, it is the 15 m line (6 m)."""
    heights = resolve(make_site(PLOT)).height
    assert heights.band_for(18.0).setback_m is None
    assert heights.band_for_block(15.0, 3.0, stilt_counted=True).setback_m == 6.0


def test_the_permissible_non_high_rise_height_is_the_top_of_the_highest_band_that_may_stand():
    rules = resolve(make_site(PLOT))
    top = rules.height.permissible_non_high_rise()
    assert (top.up_to_m, top.up_to_inclusive) == (18.0, False)
    open_ = rules.height.permissible_non_high_rise(include_unverified=True)
    assert (open_.up_to_m, open_.up_to_inclusive) == (21.0, False)


# --- What else is carried ---------------------------------------------------------------------


def test_the_planting_strips_the_pathway_and_the_front_rule_are_carried_with_their_clauses():
    rules = resolve(make_site(PLOT))
    strips = rules.green_strip
    assert (strips.frontage_m.value, strips.periphery_m.value) == (1.0, 1.0)
    assert strips.periphery_above_sqm.value == 300.0
    assert strips.frontage_m.clause == rules_py.NON_HIGH_RISE_GREEN_STRIP_CLAUSE
    assert strips.width_m.value == 2.0  # the high-rise strip stays
    assert rules.circulation.pathway_width_m.value == 6.0
    assert rules.circulation.pathway_width_m.clause == rules_py.PATHWAY_CLAUSE
    assert rules.setbacks.front.clause == rules_py.BUILDING_LINE_HIGH_RISE_CLAUSE
    assert "12(b)" in rules.setbacks.front.note  # the clause the legacy checker cites for it
    assert len(rules.setbacks.concessions) == 2
    assert rules.setbacks.concessions[1].clause == rules_py.ROAD_WIDENING_NON_HIGH_RISE_CLAUSE


def test_a_plot_of_300_m2_or_less_keeps_its_planting_strip_on_the_frontage_only():
    lines = [b for b in _low(resolve(make_site(box(0, 0, 15, 20), road_m=12.0)))
             if b.setback_m is not None]  # 300 m²: row 4
    assert {(b.green_strip_m, b.green_strip_sides) for b in lines} == {(1.0, "FRONTAGE")}


def test_the_open_readings_name_the_sources_that_bear_on_them():
    rules = resolve(make_site(PLOT))
    stilt = " ".join(rules.interpretation(STILT_IN_RULE_HEIGHT).sources)
    assert "5(c)" in stilt and "inclusive of Stilt / Parking Floor" in stilt
    spacing = " ".join(rules.interpretation(MIXED_HEIGHT_SPACING).sources)
    assert "5(f)(xiii)" in spacing and "8(j)" in spacing and "as the case may be" in spacing
