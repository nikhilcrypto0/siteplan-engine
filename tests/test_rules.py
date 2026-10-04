import math
import re
from pathlib import Path

import pytest

from siteplan import rules
from siteplan.rules import TABLE_IV, band_for_height

ORDER = Path(__file__).parent.parent / "fixtures" / "rules" / "go168-2012.pdf"


@pytest.mark.parametrize(
    ("height", "road", "open_space"),
    [(18, 12, 7), (21, 12, 7), (21.01, 12, 8), (24, 12, 8), (26.5, 18, 9), (27, 18, 9),
     (27.1, 18, 10), (30, 18, 10), (30.5, 24, 11), (45.5, 30, 14), (55, 30, 16)],
)
def test_table_iv_bands_are_above_lower_up_to_upper(height, road, open_space):
    band = band_for_height(height)
    assert band is not None
    assert (band.min_road_m, band.min_open_space_m) == (road, open_space)


@pytest.mark.parametrize(("height", "road", "setback"), [
    (57.0, 30, 17),     # the three bands G.O.Ms.No.50 of 2019 added above 55 m
    (70.0, 30, 17),
    (100.0, 30, 18),
    (150.0, 30, 20),
])
def test_the_2019_bands_above_55_m_are_encoded(height, road, setback):
    band = band_for_height(height)
    assert (band.min_road_m, band.min_open_space_m) == (road, setback)


def test_table_iv_has_no_gaps_or_overlaps():
    for lower, upper in zip(TABLE_IV, TABLE_IV[1:], strict=False):
        assert lower.up_to_m == upper.above_m


def test_the_five_percent_amenity_share_is_rule_9_o_and_10_i_and_is_not_rule_8():
    """Read on p.16 of the 2012 text: the clause stands under row housing and cluster housing.
    A brief once called it rule 8(o); rule 8 (group development) has no such clause."""
    assert rules.LARGE_PROJECT_FROM_ACRES == 5.0
    assert rules.LARGE_PROJECT_AMENITY_SHARE_OF_SITE == 0.05
    clause = rules.LARGE_PROJECT_AMENITY_CLAUSE
    assert "rule 9(o)" in clause and "rule 10(i)" in clause and "p.16" in clause
    assert "8(o)" not in clause


def test_the_fire_tender_loading_is_pinned():
    """NBC 2016 Part 3 4.6(c), as recorded in AGENTS.md; a paving specification the engine
    carries but never checks."""
    assert rules.FIRE_TENDER_LOAD_T == 45.0


def test_the_distance_from_an_electricity_line_is_as_rule_3c_gives_it():
    """Rule 3(c)(i), pp.4-5 of the 2012 order: 3 m from a high-tension line, 1.5 m from a
    low-tension line, 'both vertical and horizontal'."""
    assert rules.ELECTRICAL_HT_CLEARANCE_M == 3.0
    assert rules.ELECTRICAL_LT_CLEARANCE_M == 1.5
    assert "3(c)(i)" in rules.ELECTRICAL_CLAUSE


def test_a_ramp_in_a_side_or_rear_setback_leaves_7_m_for_fire_vehicles():
    """Rule 13(c)(vii): 'after leaving minimum 7m of setback for movement of fire-fighting
    vehicles'."""
    assert rules.RAMP_FIRE_CLEARANCE_M == 7.0
    assert "13(c)(vii)" in rules.RAMP_CLAUSE


# --- Table III (rule 5), read from the 2012 order's pp.9-10 --------------------------------------

BL = (3, 4, 5, 6, 7.5)  # columns 5-9 of every line from 300 m² up
# The table as typed again from the page image, one line per permissible height:
# (Sl.No., above, up to, parking provision, height up to, '18**', Building Line by road, side)
THE_ORDER_PRINTS = [
    (1, 0, 50, "Stilt floor", 7, False, (1.5, 1.5, 3, 3, 3), None),
    (2, 50, 100, "Stilt floor", 7, False, (1.5, 1.5, 3, 3, 3), None),
    (2, 50, 100, "Stilt floor", 10, False, (1.5, 1.5, 3, 3, 3), 0.5),
    (3, 100, 200, "Stilt floor", 10, False, (1.5, 1.5, 3, 3, 3), 1.0),
    (4, 200, 300, "Stilt floor", 7, False, (2, 3, 3, 4, 5), 1.0),
    (4, 200, 300, "Stilt floor", 10, False, (2, 3, 3, 5, 6), 1.5),
    (5, 300, 400, "Stilt floor", 7, False, BL, 1.5),
    (5, 300, 400, "Stilt floor", 12, False, BL, 2.0),
    (6, 400, 500, "Stilt floor", 7, False, BL, 2.0),
    (6, 400, 500, "Stilt floor", 12, False, BL, 2.5),
    (7, 500, 750, "Stilt floor", 7, False, BL, 2.5),
    (7, 500, 750, "Stilt floor", 12, False, BL, 3.0),
    (7, 500, 750, "Stilt floor", 15, False, BL, 3.5),
    (8, 750, 1000, "Stilt + One Cellar floor", 7, False, BL, 3.0),
    (8, 750, 1000, "Stilt + One Cellar floor", 12, False, BL, 3.5),
    (8, 750, 1000, "Stilt + One Cellar floor", 15, False, BL, 4.0),
    (9, 1000, 1500, "Stilt + 2 Cellar floors", 7, False, BL, 3.5),
    (9, 1000, 1500, "Stilt + 2 Cellar floors", 12, False, BL, 4.0),
    (9, 1000, 1500, "Stilt + 2 Cellar floors", 15, False, BL, 5.0),
    (9, 1000, 1500, "Stilt + 2 Cellar floors", 18, True, BL, 6.0),
    (10, 1500, 2500, "Stilt + 2 Cellar floors", 7, False, BL, 4.0),
    (10, 1500, 2500, "Stilt + 2 Cellar floors", 15, False, BL, 5.0),
    (10, 1500, 2500, "Stilt + 2 Cellar floors", 18, True, BL, 6.0),
    (11, 2500, math.inf, "Stilt + 2 or more Cellar floors", 7, False, BL, 5.0),
    (11, 2500, math.inf, "Stilt + 2 or more Cellar floors", 15, False, BL, 6.0),
    (11, 2500, math.inf, "Stilt + 2 or more Cellar floors", 18, True, BL, 7.0),
]


def test_table_iii_is_the_order_line_for_line():
    ours = [(t.row, t.above_sqm, t.up_to_sqm, t.parking, t.up_to_m, t.below, t.front_m, t.side_m)
            for t in rules.TABLE_III]
    assert ours == THE_ORDER_PRINTS


def test_table_iii_is_built_the_way_the_order_builds_it():
    """Eleven rows; a row's lines rise in height; the setback on the other sides never falls as
    the building rises; the Building Line never falls as the road widens; the rows meet."""
    assert sorted({t.row for t in rules.TABLE_III}) == list(range(1, 12))
    for row in range(1, 12):
        lines = [t for t in rules.TABLE_III if t.row == row]
        assert [t.up_to_m for t in lines] == sorted(t.up_to_m for t in lines)
        sides = [t.side_m or 0.0 for t in lines]
        assert sides == sorted(sides)
        assert {(t.above_sqm, t.up_to_sqm) for t in lines} == {(lines[0].above_sqm,
                                                                lines[0].up_to_sqm)}
        assert all(list(t.front_m) == sorted(t.front_m) for t in lines)
    first_of = {t.row: t for t in reversed(rules.TABLE_III)}
    assert [first_of[r].up_to_sqm for r in range(1, 11)] == [
        first_of[r].above_sqm for r in range(2, 12)]
    assert first_of[11].up_to_sqm == math.inf
    assert {t.below for t in rules.TABLE_III if t.up_to_m == 18} == {True}
    assert {t.row for t in rules.TABLE_III if t.below} == {9, 10, 11}  # rule 5(e)'s rows


def test_the_parking_column_of_rows_1_to_3_carries_the_stilt_floor_g_o_7_of_2016_added():
    """G.O.Ms.No.7 of 2016, Amendment 6 (p.3): 'Stilt floor' added in column 3 against rows 1, 2
    and 3, which the 2012 order left blank or '-'."""
    assert {t.parking for t in rules.TABLE_III if t.row <= 3} == {"Stilt floor"}
    assert "Amendment 6" in rules.TABLE_III_CLAUSE


@pytest.mark.parametrize(("plot", "row"), [
    (10, 1), (49.99, 1), (50, 2), (50.01, 2), (100, 2), (100.01, 3), (200, 3), (200.01, 4),
    (300, 4), (300.01, 5), (400, 5), (500, 6), (500.01, 7), (750, 7), (750.01, 8), (1000, 8),
    (1000.01, 9), (1500, 9), (1500.01, 10), (2500, 10), (2500.01, 11), (18_969, 11)])
def test_a_plot_is_in_the_row_it_is_above_the_lower_edge_of_and_up_to_the_upper(plot, row):
    """Column 2 reads 'Above - Up to'. Exactly 50 m² is between 'Less than 50' and '50-100' by the
    labels and is taken in row 2; every other edge is unambiguous."""
    assert {t.row for t in rules.table_iii_lines(plot)} == {row}


@pytest.mark.parametrize(("height", "up_to", "side"), [
    (3.0, 7, 5.0), (7.0, 7, 5.0), (7.0000001, 7, 5.0), (7.01, 15, 6.0), (12.0, 15, 6.0),
    (15.0, 15, 6.0), (15.01, 18, 7.0), (17.99, 18, 7.0)])
def test_a_height_takes_the_line_of_the_lowest_permissible_height_that_reaches_it(
        height, up_to, side):
    """A plot over 2,500 m² has lines at 7, 15 and 18 m (no 12 m line: rows 10 and 11 have none)."""
    line = rules.table_iii_line(3000, height)
    assert (line.up_to_m, line.side_m) == (up_to, side)


def test_18_m_itself_is_not_reached_by_the_18_line_and_nothing_above_is_permitted():
    """'18**' is 'above 15m and below 18m' (rule 5(e)): 18 m is no line of Table III. Between 18
    and 21 m the order read gives no line either; G.O.Ms.No.95 of 2026 lets 750-2000 m² plots build
    there through TDR and says nothing of the setback."""
    assert rules.table_iii_line(3000, 18.0) is None and rules.table_iii_line(3000, 20.9) is None
    assert rules.table_iii_line(3000, 17.999).below
    assert rules.table_iii_line(600, 15.01) is None  # a 500-750 m² plot stops at 15 m
    assert rules.table_iii_line(30, 7.5) is None
    assert rules.TABLE_III_TOP_TIER_MIN_ROAD_M == 12.0 and "5(e)" in rules.TABLE_III_TOP_TIER_CLAUSE


@pytest.mark.parametrize(("road", "front"), [
    (5.0, 3.0), (12.0, 3.0), (12.01, 4.0), (18.0, 4.0), (18.01, 5.0), (24.0, 5.0), (24.01, 6.0),
    (30.0, 6.0), (30.01, 7.5), (60.0, 7.5)])
def test_the_building_line_is_by_the_abutting_roads_width(road, front):
    line = rules.table_iii_line(3000, 10.0)
    assert rules.building_line_m(line, road) == front
    assert rules.TABLE_III_ROAD_UP_TO_M == (12.0, 18.0, 24.0, 30.0)


def test_a_small_plots_building_line_has_its_own_figures():
    """Rows 1 to 3: 1.5 m up to 18 m of road, 3 m above; row 4 asks 2 to 6 m."""
    small = [rules.building_line_m(rules.table_iii_line(40, 7), r) for r in (10, 15, 20, 28, 40)]
    assert small == [1.5, 1.5, 3.0, 3.0, 3.0]
    row_4 = [rules.building_line_m(rules.table_iii_line(250, 10), r) for r in (10, 15, 20, 28, 40)]
    assert row_4 == [2.0, 3.0, 3.0, 5.0, 6.0]


@pytest.mark.parametrize(("feet", "metres"), [
    (10, 3.0), (20, 6.0), (25, 7.5), (30, 9.0), (40, 12.0), (50, 15.0), (60, 18.0), (80, 24.0),
    (100, 30.0), (150, 45.0), (200, 60.0)])
def test_a_road_in_feet_is_reckoned_as_the_orders_metres(feet, metres):
    """Rule 5(f)(xvii), p.11: the conversion 'shall be reckoned for the road widths only'. The
    engine turns 60 ft into 18.288 m, which Table III's 'above 18 m' would put a column too far."""
    assert (metres, feet) in rules.ROAD_WIDTH_FEET
    assert rules.reckoned_road_width_m(feet * 0.3048) == metres
    line = rules.table_iii_line(3000, 10.0)
    assert rules.building_line_m(line, feet * 0.3048) == rules.building_line_m(line, metres)


def test_a_width_that_is_not_a_listed_number_of_feet_is_taken_as_it_stands():
    assert rules.reckoned_road_width_m(18.3) == 18.3  # 18.3 m is above 18 m: the front is 5 m
    assert rules.reckoned_road_width_m(14.0) == 14.0 and rules.reckoned_road_width_m(7.0) == 7.0
    line = rules.table_iii_line(3000, 10.0)
    assert (rules.building_line_m(line, 18.288), rules.building_line_m(line, 18.3)) == (4.0, 5.0)


def test_the_stilt_is_left_out_of_table_iii_and_has_a_least_height():
    """Rule 5(c), p.10."""
    assert rules.STILT_MIN_HEIGHT_M == 2.5 and rules.MECHANICAL_PARKING_FLOOR_MIN_HEIGHT_M == 4.5
    assert "5(c)" in rules.TABLE_III_STILT_CLAUSE and "p.10" in rules.TABLE_III_STILT_CLAUSE


def test_the_roads_the_non_high_rise_heights_need_are_table_ii_and_rule_8_b():
    """Table II (pp.7-8), category B: B1 9 m up to 5 floors, B2 12 m (six floors, more than 100
    units, a Group Development Scheme, other non-high-rise up to 18 m); rule 8(b), p.14: 12 m."""
    assert (rules.TABLE_II_B1_ROAD_M, rules.TABLE_II_B1_MAX_FLOORS) == (9.0, 5)
    assert (rules.TABLE_II_B2_ROAD_M, rules.TABLE_II_B2_UNITS_OVER) == (12.0, 100)
    assert rules.GROUP_DEVELOPMENT_MIN_ROAD_M == 12.0
    assert rules.GROUP_DEVELOPMENT_MIN_ROAD_M == rules.TABLE_II_B2_ROAD_M
    assert rules.TABLE_II_B2_ROAD_M == rules.TABLE_III_TOP_TIER_MIN_ROAD_M
    assert "pp.7-8" in rules.TABLE_II_CLAUSE and "p.14" in rules.GROUP_DEVELOPMENT_ROAD_CLAUSE


def test_a_pathway_is_6_m_wide_for_blocks_up_to_12_m_and_a_subdivided_plots_access_is_3_6_or_6():
    """Rule 8(l), p.15; rule 4(f), p.8."""
    assert (rules.PATHWAY_WIDTH_M, rules.PATHWAY_MAX_BLOCK_HEIGHT_M) == (6.0, 12.0)
    assert rules.SUBDIVISION_PATHWAY_M == (3.6, 6.0)
    assert "4(f)" in rules.SUBDIVISION_PATHWAY_CLAUSE


def test_below_21_m_the_order_gives_one_fire_figure_and_it_is_the_clearance_above_18_m():
    """Rule 5(f)(xvi), p.11. Rule 15(a)(i) gives none: it holds a non-high-rise building to the
    NBC's requirements 'other than heights and setbacks'; no number stands behind it here."""
    assert rules.FIRE_CLEARANCE_RESIDENTIAL_ABOVE_M == 18.0
    assert "5(f)(xvi)" in rules.FIRE_CLEARANCE_CLAUSE
    assert "National Building Code 2016" in rules.NON_HIGH_RISE_NBC_CLAUSE
    assert "other than heights and setbacks" in rules.NON_HIGH_RISE_NBC_CLAUSE


def test_the_high_rise_front_is_rule_7_a_xi_and_not_the_commercial_courtyard_rule_it_was_cited_to():
    """The engine first cited p.17(b) for the front. That is rule 12(b), 'U' type commercial
    buildings with a central courtyard (the order's rule 12 heading is on p.17, above it). The
    high-rise front is rule 7(a)(xi), p.14: the higher of Table IV column 4 and the Building Line
    of Table III."""
    clause = rules.FRONT_SETBACK_CLAUSE
    assert "7(a)(xi)" in clause and "p.14" in clause and "higher" in clause
    assert "p.17" not in clause and "12(b)" not in clause
    assert clause == rules.BUILDING_LINE_HIGH_RISE_CLAUSE


def test_height_rules_answers_table_iii_when_it_is_given_the_plot_and_the_road():
    answer = rules.height_rules(15.0, plot_sqm=3000, road_m=18.288)
    assert answer["table_iii_row"] == 11 and answer["min_side_setback_m"] == 6.0
    assert answer["min_gap_between_blocks_m"] == 6.0 and answer["building_line_m"] == 4.0
    assert answer["clause"] == rules.TABLE_III_CLAUSE
    taller = rules.height_rules(16.0, plot_sqm=3000, road_m=18.288)
    assert taller["min_side_setback_m"] == 7.0 and taller["min_abutting_road_m"] == 12.0
    none = rules.height_rules(19.0, plot_sqm=3000)
    assert "table_iii_row" not in none and "permits no building of 19 m" in none["answer"]
    assert "not encoded" in rules.height_rules(15.0)["answer"]  # no plot, no row


# --- Every clause says which page of the order it was read on ---------------------------------

NEW_CLAUSES = [
    "TABLE_III_CLAUSE", "TABLE_III_STILT_CLAUSE", "TABLE_III_TOP_TIER_CLAUSE",
    "TABLE_III_BIGGER_ROAD_CLAUSE", "NON_HIGH_RISE_SPACING_CLAUSE", "GROUP_SCHEME_SPACING_CLAUSE",
    "BUILDING_LINE_HIGH_RISE_CLAUSE", "ROAD_WIDTH_CONVERSION_CLAUSE", "TABLE_II_CLAUSE",
    "GROUP_DEVELOPMENT_ROAD_CLAUSE", "SUBDIVISION_PATHWAY_CLAUSE", "FIRE_CLEARANCE_CLAUSE",
    "NON_HIGH_RISE_GREEN_STRIP_CLAUSE", "NON_HIGH_RISE_OPEN_SPACE_CLAUSE",
    "PUBLIC_UTILITY_AREA_CLAUSE", "SETBACK_TRANSFER_CLAUSE", "NARROW_PLOT_CLAUSE",
    "ROAD_WIDENING_NON_HIGH_RISE_CLAUSE", "TDR_NON_HIGH_RISE_SETBACK_CLAUSE"]


@pytest.mark.parametrize("name", NEW_CLAUSES)
def test_a_clause_names_the_order_the_rule_and_the_page(name):
    clause = getattr(rules, name)
    assert clause.startswith("G.O.") and re.search(r"\bpp?\.\d", clause), clause
    assert "rule" in clause.split("(")[0], clause


# What each clause quotes, on the page the clause names. The order has a text layer (the tables
# come out scrambled, the sentences do not); the test skips where the order is not kept.
QUOTED = [
    (9, "PERMISSIBLE SETBACKS & HEIGHT STIPULATIONS FOR ALL TYPES"),
    (9, "(Buildings below 18m in height inclusive of Stilt / Parking Floor)"),
    (10, "Stilt Floor meant for parking is excluded from the permissible height in"),
    (10, "Height of stilt floor shall not be less than 2.5m"),
    (10, "such parking floor shall not be less than 4.5m"),
    (10, "Buildings of height above 15m and below 18m in Sl.Nos.9, 10 and 11"),
    (10, "abut minimum 12m wide roads only"),
    (10, "front setback should be insisted towards the bigger road width"),
    (11, "The space between 2 blocks shall not be less than the side setback"),
    (11, "of the tallest block as mentioned in Table - III"),
    (11, "Residential buildings of height more than 18 m"),
    (11, "conversion from M.K.S. and F.P.S. system shall be reckoned for the road widths"),
    (11, "(7) 18m = 60ft"),
    (14, "Building Line given in Table - III of rule-5 whichever is higher"),
    (14, "The minimum abutting existing road width shall be 12m and black topped"),
    (15, "access through pathways of 6m width"),
    (15, "Column -10 of Table-"),
    (7, "The setbacks shall be followed as per Table-III of rule-5"),
    (8, "Group Housing with more than 100 units"),
    (8, "a means of independent access of minimum 3.6m pathway"),
    (17, "12. BUILDINGS WITH CENTRAL COURTYARD FOR COMMERCIAL USE"),
    (17, "The Front setback shall be as per Table-III of rule-5 & Table-IV of rule-7 for Non High"),
    (20, "Non High Rise Buildings"),
    (20, "other than heights and setbacks specified in the National Building Code - 2005"),
    (10, "A strip of at least 1m greenery / lawn along the frontage of the site"),
    (10, "within the front setback shall be developed and maintained with greenery"),
    (10, "a minimum 1m wide continuous green planting strip in the periphery on remaining"),
    (10, "For Plots above 300sq.m in addition to (iii) above"),
    (10, "5% of the site area to be developed as organized open space"),
    (10, "minimum width of 3m with a minimum area of 15sq.m at each location"),
    (10, "For all residential / institutional / industrial plots above 750sq.m"),
    (10, "provision shall be made for earmarking an area of 3m X 3m"),
    (10, "In all plots 750sq.m and above"),
    (10, "it is permitted to transfer up to 1m of setback from any one side to any other side"),
    (10, "In case of plots 300 - 750sq.m"),
    (10, "it is permitted to transfer up to 2m"),
    (10, "subject to maintaining of a minimum 2.5m setback on other side and a minimum building "
         "line"),
    (10, "The transfer of setback from front setback is not allowed"),
    (10, "For narrow plots having extent not more than 400sq.m and where the length is 4 times of "
         "the width of the plot"),
    (11, "subject to maintaining a minimum of side setback of 1m in case of buildings of height up "
         "to 10m"),
    (11, "minimum of 2m in case of buildings of height above 10m and up to 15m"),
    (10, "The setbacks are to be left after leaving the affected area of the plot"),
]


def test_the_planting_strips_of_rule_5_f_are_1_m_and_the_periphery_one_is_for_plots_above_300_m2():
    """Rule 5(f)(iiii) and (ivi), p.10. G.O.Ms.No.7 of 2016 does not touch them; its Amendment 8
    is rule 7(viii), the high-rise strip (2 m where the setback is 9 m or more), which stays."""
    assert rules.NON_HIGH_RISE_FRONTAGE_STRIP_M == 1.0
    assert rules.NON_HIGH_RISE_PERIPHERY_STRIP_M == 1.0
    assert rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM == 300.0
    assert rules.PERIPHERAL_GREEN_STRIP_M == 2.0
    assert rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M == 9.0


def test_the_five_percent_open_space_of_rule_5_f_vi_is_not_the_ten_percent_of_a_group_scheme():
    """Rule 5(f)(vi), p.10: plots above 750 m², 3 m wide and 15 m² a pocket; rule 8(g) and rule
    7(a)(vii) keep 10% and 50 m²."""
    assert rules.NON_HIGH_RISE_OPEN_SPACE_FRACTION == 0.05
    assert rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM == 750.0
    assert (rules.NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M,
            rules.NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM) == (3.0, 15.0)
    assert (rules.OPEN_SPACE_MIN_FRACTION, rules.OPEN_SPACE_MIN_POCKET_SQM) == (0.10, 50.0)


def test_a_plot_of_750_m2_and_above_earmarks_3_m_by_3_m_for_utilities():
    assert rules.PUBLIC_UTILITY_AREA_M == (3.0, 3.0)
    assert rules.PUBLIC_UTILITY_AREA_FROM_SQM == 750.0


def test_setback_may_move_between_sides_by_1_m_or_2_m_and_never_from_the_front():
    """Rule 5(f)(viiii) and (ixi), p.10, and (xi), pp.10-11 for narrow plots: design options,
    carried as read and applied nowhere."""
    assert (rules.SETBACK_TRANSFER_300_TO_750_M, rules.SETBACK_TRANSFER_ABOVE_750_M) == (1.0, 2.0)
    assert rules.SETBACK_TRANSFER_MIN_OTHER_SIDE_M == 2.5
    assert "never from the front" in rules.SETBACK_TRANSFER_CLAUSE
    assert (rules.NARROW_PLOT_MAX_SQM, rules.NARROW_PLOT_LENGTH_TO_WIDTH) == (400.0, 4.0)
    assert rules.NARROW_PLOT_MIN_SIDE_M == ((10.0, 1.0), (15.0, 2.0))


def test_the_concessions_of_a_surrendering_owner_are_the_minimums_tdr_relaxation_keeps():
    """G.O.Ms.No.7 of 2016, Amendment 16 (p.5): building line 6 m for roads of 30 m and above,
    3 m for 18 m and below 30 m, 2 m under 18 m; side and rear 2 m up to 12 m of height, 2.5 m
    above 12 and up to 15 m, 3 m above 15 and up to 18 m. G.O.Ms.No.95 of 2026, rule 17(d)(ix),
    keeps 'minimum setbacks as prescribed in cases of road widening'."""
    line = rules.ROAD_WIDENING_NON_HIGH_RISE_BUILDING_LINE_M
    assert line == ((30.0, 6.0), (18.0, 3.0), (0.0, 2.0))
    side = rules.ROAD_WIDENING_NON_HIGH_RISE_SIDE_REAR_M
    assert side == ((12.0, 2.0), (15.0, 2.5), (18.0, 3.0))
    assert "Amendment 16" in rules.ROAD_WIDENING_NON_HIGH_RISE_CLAUSE
    assert "17(d)(ix)" in rules.TDR_NON_HIGH_RISE_SETBACK_CLAUSE


def test_what_the_clauses_quote_is_on_the_page_they_name():
    pdfplumber = pytest.importorskip("pdfplumber")
    if not ORDER.exists():
        pytest.skip("the 2012 order is not kept in fixtures/rules")
    with pdfplumber.open(ORDER) as pdf:
        text = {n: " ".join((pdf.pages[n - 1].extract_text() or "").split()) for n in
                {page for page, _ in QUOTED}}
    missing = [(page, quote) for page, quote in QUOTED
               if " ".join(quote.split()) not in text[page]]
    assert missing == []
