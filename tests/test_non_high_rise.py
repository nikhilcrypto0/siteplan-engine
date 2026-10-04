"""What Table III gives a site below the high-rise height (stream A2): the permissible heights of
its row, the setback, the road and the permission of each stretch, and the high-rise front.

Made-up sites only. The figures are the order's (tests/test_rules.py pins them against the page);
what these tests hold is how a site's plot, road and category pick among them.
"""

import pytest

from siteplan import rules
from siteplan.contracts.common import Provenance
from siteplan.contracts.resolved_rules import Eligibility
from siteplan.legal.non_high_rise import high_rise_front, stretches

TEST_CLASS = "normative"
CONFIRMED, GUESS = Provenance.USER_CONFIRMED, Provenance.UNVERIFIED
ROAD_60_FT = ((18.288, CONFIRMED),)
ALLOWED, PROHIBITED, UNKNOWN = Eligibility.ALLOWED, Eligibility.PROHIBITED, Eligibility.UNVERIFIED


def _run(plot_sqm=18_000.0, widths=ROAD_60_FT, *, gross_sqm=None, plot_status=CONFIRMED,
         gross_status=CONFIRMED):
    return stretches(plot_sqm=plot_sqm, plot_status=plot_status,
                     gross_sqm=plot_sqm if gross_sqm is None else gross_sqm,
                     gross_status=gross_status, widths=widths, high_rise_from_m=21.0)


def _shape(stretch):
    return (stretch.above_m, stretch.up_to_m, stretch.above_inclusive, stretch.up_to_inclusive)


# --- Every height once ------------------------------------------------------------------------


@pytest.mark.parametrize("plot", [30, 75, 150, 250, 350, 450, 600, 800, 1200, 1800, 2000, 2400,
                                  3000, 18_000])
def test_the_stretches_tile_every_height_below_21_m_once(plot):
    """Each stretch starts where the last ended, one of the two edges is the one that holds the
    height, and the last stops short of 21 m, which is a high-rise's."""
    found = _run(plot)
    assert (found[0].above_m, found[0].above_inclusive) == (0.0, False)
    for before, after in zip(found, found[1:], strict=False):
        assert after.above_m == before.up_to_m
        assert after.above_inclusive != before.up_to_inclusive
    assert (found[-1].up_to_m, found[-1].up_to_inclusive) == (21.0, False)


def test_a_group_scheme_on_a_60_ft_road_takes_row_11_and_keeps_every_figure_the_order_gives():
    """Above 2,500 m²: 7, 15 and 'below 18' m with sides of 5, 6 and 7 m; the front is 4 m,
    because 60 ft is reckoned as 18 m; the road asked is a group scheme's 12 m, met."""
    first, second, third, open_ = _run()
    assert [(s.above_m, s.up_to_m, s.up_to_inclusive) for s in (first, second, third)] == [
        (0.0, 7, True), (7, 15, True), (15, 18, False)]
    assert [s.side_m for s in (first, second, third)] == [5.0, 6.0, 7.0]
    assert {s.front_m for s in (first, second, third)} == {4.0}
    assert {s.min_road_m for s in (first, second, third)} == {12.0}
    assert {s.permission for s in (first, second, third)} == {ALLOWED}
    assert {s.status for s in (first, second, third)} == {CONFIRMED}
    assert {s.row for s in (first, second, third)} == {11}
    assert rules.GROUP_DEVELOPMENT_ROAD_CLAUSE in first.note
    assert (open_.above_m, open_.up_to_m, open_.above_inclusive) == (18, 21, True)


def test_a_road_given_in_metres_just_over_18_m_has_the_next_front():
    assert {s.front_m for s in _run(widths=((18.3, CONFIRMED),))[:3]} == {5.0}
    assert {s.front_m for s in _run(widths=((18.0, CONFIRMED),))[:3]} == {4.0}


# --- The road ---------------------------------------------------------------------------------


def test_a_group_scheme_needs_12_m_for_every_height_a_plot_without_one_needs_9_m_up_to_15_m():
    scheme = _run(4500.0, ((10.0, CONFIRMED),))
    assert {s.min_road_m for s in scheme[:3]} == {12.0}
    plain = _run(3000.0, ((10.0, CONFIRMED),))  # under 4,000 m²: not a group development scheme
    assert [s.min_road_m for s in plain[:3]] == [9.0, 9.0, 12.0]
    assert plain[0].clause.endswith("up to 7 m") and rules.TABLE_II_CLAUSE in plain[0].note
    assert rules.TABLE_III_TOP_TIER_CLAUSE in plain[2].note


def test_a_confirmed_road_that_is_too_narrow_prohibits_and_an_unconfirmed_one_settles_nothing():
    short = _run(3000.0, ((10.0, CONFIRMED),))
    assert [s.permission for s in short[:3]] == [ALLOWED, ALLOWED, PROHIBITED]
    assert "falls short of it" in short[2].note
    drawn = _run(3000.0, ((10.0, GUESS),))
    assert [s.permission for s in drawn[:3]] == [ALLOWED, ALLOWED, UNKNOWN]
    assert {s.status for s in drawn[:3]} == {GUESS}
    scheme = _run(4500.0, ((10.0, CONFIRMED),))
    assert {s.permission for s in scheme[:3]} == {PROHIBITED}


def test_with_no_road_given_no_front_is_guessed_and_nothing_is_allowed():
    found = _run(widths=())
    assert {s.front_m for s in found[:3]} == {None}
    assert {s.permission for s in found[:3]} == {UNKNOWN} and {s.status for s in found} == {GUESS}
    assert "not given" in found[0].note
    assert {s.side_m for s in found[:3]} == {5.0, 6.0, 7.0}  # the sides do not depend on the road


def test_a_master_plan_width_beside_the_road_leaves_the_front_and_the_road_open_where_they_differ():
    """12.0 m as it stands, 18.288 m once the strip is surrendered: the front is 3 m on one and
    4 m on the other; the larger stands and the band is not settled. A width under the road asked
    on only one of them leaves permission open."""
    both = _run(widths=((12.0, CONFIRMED), (18.288, CONFIRMED)))
    assert {s.front_m for s in both[:3]} == {4.0} and {s.status for s in both[:3]} == {GUESS}
    assert {s.permission for s in both[:3]} == {ALLOWED}  # both meet a scheme's 12 m
    narrow = _run(widths=((10.0, CONFIRMED), (18.288, CONFIRMED)))
    assert {s.permission for s in narrow[:3]} == {UNKNOWN}


# --- The plot ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("plot", "row", "heights", "sides"), [
    (30, 1, [7], [0.0]),
    (75, 2, [7, 10], [0.0, 0.5]),
    (150, 3, [10], [1.0]),
    (250, 4, [7, 10], [1.0, 1.5]),
    (350, 5, [7, 12], [1.5, 2.0]),
    (450, 6, [7, 12], [2.0, 2.5]),
    (600, 7, [7, 12, 15], [2.5, 3.0, 3.5]),
    (800, 8, [7, 12, 15], [3.0, 3.5, 4.0]),
    (1200, 9, [7, 12, 15, 18], [3.5, 4.0, 5.0, 6.0]),
    (2000, 10, [7, 15, 18], [4.0, 5.0, 6.0]),
])
def test_a_plot_takes_its_rows_lines_and_a_dash_in_column_10_is_no_setback(plot, row, heights,
                                                                          sides):
    found = [s for s in _run(plot, ((30.0, CONFIRMED),)) if s.row == row and s.side_m is not None]
    assert [s.up_to_m for s in found] == heights and [s.side_m for s in found] == sides


def test_the_gap_a_block_needs_is_its_side_setback_so_the_stretch_carries_no_other_figure():
    """Rule 5(f)(xiii): the space between two blocks is the side setback of the taller one. The
    resolver gives each band that figure as its gap; nothing here has a second number."""
    assert all(not hasattr(s, "gap_m") for s in _run())


def test_a_plot_just_over_a_row_edge_is_in_the_next_row():
    assert {s.row for s in _run(1000.0) if s.row} == {8}
    assert {s.row for s in _run(1000.5) if s.row} == {9}


def test_the_status_is_the_weakest_of_the_plot_the_road_and_for_a_scheme_the_gross_area():
    """The gross area counts only where it decides something: it decides whether a site is a
    group development scheme, which asks 12 m of road for every height."""
    scheme = _run(18_000.0, gross_status=Provenance.EXTRACTED)
    assert {s.status for s in scheme[:3]} == {Provenance.EXTRACTED}
    plain = _run(3000.0, gross_status=Provenance.EXTRACTED)  # under 4,000 m²: not a scheme
    assert {s.status for s in plain[:3]} == {CONFIRMED}
    assert {s.status for s in _run(plot_status=Provenance.EXTRACTED)[:3]} == {Provenance.EXTRACTED}


# --- What Table III leaves open below 21 m ----------------------------------------------------


@pytest.mark.parametrize("plot", [30, 75, 150, 250, 350, 450, 600])
def test_above_a_rows_last_height_nothing_is_permitted_on_a_plot_under_750_m2(plot):
    """Rows 1 to 7 stop at 7 to 15 m, and no order read permits more: one stretch, PROHIBITED,
    with no setback to plan a block on."""
    *_, last = _run(plot)
    assert (last.up_to_m, last.permission) == (21.0, PROHIBITED)
    assert (last.side_m, last.front_m, last.min_road_m) == (None, None, None)
    assert "no order read permits" in last.note and last.clause == rules.TABLE_III_CLAUSE


def test_a_plot_of_750_to_1000_m2_stops_at_15_m_and_may_reach_18_to_21_m_only_through_tdr():
    *_, open_a, open_b = _run(800)
    assert (_shape(open_a), open_a.permission) == ((15, 18, False, False), PROHIBITED)
    assert (_shape(open_b), open_b.permission) == ((18, 21, True, False), UNKNOWN)
    assert "only through TDR" in open_b.note and open_b.clause == rules.TDR_BAND_CLAUSE
    assert open_b.status is GUESS and open_b.side_m is None


@pytest.mark.parametrize("plot", [1200, 1800, 2000])
def test_a_plot_of_1000_to_2000_m2_has_its_18_to_21_m_through_tdr_after_the_18_line(plot):
    *_, open_ = _run(plot)
    assert (_shape(open_), open_.permission) == ((18, 21, True, False), UNKNOWN)
    assert "only through TDR" in open_.note


@pytest.mark.parametrize("plot", [2400, 3000, 18_000])
def test_a_plot_above_2000_m2_has_no_line_between_18_and_21_m_and_the_order_says_nothing(plot):
    *_, open_ = _run(plot)
    assert (_shape(open_), open_.permission) == ((18, 21, True, False), UNKNOWN)
    assert "no order read gives a setback" in open_.note and "TDR" not in open_.note.split(";")[0]


def test_a_road_known_to_be_too_narrow_prohibits_even_what_might_be_open_through_tdr():
    """Above 15 m a road of 12 m is asked (rule 5(e), Table II B2, rule 8(b)): a confirmed road
    short of it settles the stretch that was only open, and an unconfirmed one does not."""
    short = _run(1200.0, ((10.0, CONFIRMED),))
    assert short[-1].permission is PROHIBITED and "falls short" in short[-1].note
    assert short[-1].clause == rules.TDR_BAND_CLAUSE
    drawn = _run(1200.0, ((10.0, GUESS),))
    assert drawn[-1].permission is UNKNOWN
    scheme = _run(18_000.0, ((11.9, CONFIRMED),))  # a group scheme on 11.9 m: nothing at all
    assert {s.permission for s in scheme} == {PROHIBITED}
    assert _run(1200.0, ((12.0, CONFIRMED),))[-1].permission is UNKNOWN


def test_exactly_750_m2_is_in_row_7_and_still_through_tdr_above_18_m():
    """The order's 'from 750 sq.m to 2000 sq.m' includes 750; row 7's last line is 15 m."""
    *_, no_line, tdr = _run(750.0)
    assert (no_line.permission, tdr.permission) == (PROHIBITED, UNKNOWN)
    assert "only through TDR" in tdr.note


# --- The high-rise front ----------------------------------------------------------------------


@pytest.mark.parametrize(("all_round", "road", "front"), [
    (7.0, 30.5, 7.5), (7.0, 30.0, None), (7.0, 24.0, None), (7.0, 12.0, None),
    (8.0, 60.0, None), (9.0, 60.0, None), (20.0, 60.0, None)])
def test_a_high_rises_front_is_the_higher_of_column_4_and_the_building_line(all_round, road, front):
    """Rule 7(a)(xi): only the 21 m band (7 m) can be lower than the widest Building Line, 7.5 m."""
    got, settled = high_rise_front(all_round, 18_000.0, ((road, CONFIRMED),))
    assert (got, settled) == (front, True)


def test_a_high_rises_front_on_an_unknown_road_is_the_widest_line_only_where_that_could_matter():
    assert high_rise_front(7.0, 18_000.0, ()) == (7.5, False)
    assert high_rise_front(8.0, 18_000.0, ()) == (None, True)  # no road can make 7.5 beat 8


def test_two_road_widths_that_give_different_lines_leave_the_high_rise_front_open():
    assert high_rise_front(7.0, 18_000.0, ((24.0, CONFIRMED), (40.0, CONFIRMED))) == (7.5, False)
    assert high_rise_front(7.0, 18_000.0, ((12.0, CONFIRMED), (24.0, CONFIRMED))) == (None, True)
