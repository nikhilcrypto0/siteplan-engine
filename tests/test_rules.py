import pytest

from siteplan import rules
from siteplan.rules import TABLE_IV, band_for_height


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
