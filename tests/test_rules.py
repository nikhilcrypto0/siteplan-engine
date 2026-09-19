import pytest

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


def test_above_55_m_is_not_encoded():
    assert band_for_height(55.5) is None


def test_table_iv_has_no_gaps_or_overlaps():
    for lower, upper in zip(TABLE_IV, TABLE_IV[1:], strict=False):
        assert lower.up_to_m == upper.above_m
