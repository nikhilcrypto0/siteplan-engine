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
