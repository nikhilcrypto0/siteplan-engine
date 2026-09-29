import pytest

from siteplan.units import (
    SQM_PER_ACRE,
    acres_guntas_to_sqm,
    format_acre_gunta,
    format_indian,
    parse_acre_gunta,
    site_area,
    sqm_to_sqyd,
    written_areas,
)


def test_acre_is_40_guntas_and_4840_sqyd():
    assert acres_guntas_to_sqm(0, 40) == pytest.approx(SQM_PER_ACRE)
    assert sqm_to_sqyd(SQM_PER_ACRE) == pytest.approx(4840)


@pytest.mark.parametrize(
    "text",
    ["TOTAL LAND AREA: 3 AC 12.50 GTS", "3 Acres 12.50 Guntas", "3AC-12.50GTS"],
)
def test_parse_acre_gunta_variants(text):
    assert parse_acre_gunta(text) == pytest.approx(13405.2, abs=0.1)


def test_parse_acre_gunta_returns_none_without_units():
    assert parse_acre_gunta("AREA DETAILS") is None


def test_format_acre_gunta_round_trips():
    assert format_acre_gunta(acres_guntas_to_sqm(3, 12.5)) == "3 AC 12.50 GTS"
    assert format_acre_gunta(acres_guntas_to_sqm(2, 0)) == "2 AC 0.00 GTS"
    assert parse_acre_gunta(format_acre_gunta(12345.6)) == pytest.approx(12345.6, abs=1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (999, "999"), (1000, "1,000"), (45678, "45,678"), (612345, "6,12,345"),
     (12345678, "1,23,45,678"), (-390138, "-3,90,138")],
)
def test_format_indian(value, expected):
    assert format_indian(value) == expected


@pytest.mark.parametrize(("text", "sqm"), [
    ("1 ACR 39 GTS 85 Sq yds.", 9644 * 0.83612736),         # Suchitra's survey
    ("(8063.799 Sq mts.)", 8063.799),
    ("TOTAL SITE AREA: 22,686 SQYDS", 22686 * 0.83612736),  # Dhulapally's site plan
    ("Area :- 141 Sq yds.", 141 * 0.83612736),
    ("AREA : 4 AC 38.98 GTS", 20131.08),
    ("8,063.80 Sq.Mtrs", 8063.80),
    ("2000 sq.m", 2000.0),
    ("2000 SQM", 2000.0),
    ("2000 m2", 2000.0),
])
def test_written_areas_in_every_unit_a_sheet_uses(text, sqm):
    assert written_areas(text) == [pytest.approx(sqm, abs=0.05)]


@pytest.mark.parametrize(
    "text", ["TOT-LOT AREA : 21,278 SQFT", "FLAT AREA: 1,190 SFT", "SCALE 1:500"]
)
def test_square_feet_and_other_numbers_are_not_land_areas(text):
    assert written_areas(text) == []


def test_the_site_area_is_the_largest_area_written():
    runs = ["Area :-", "1 ACR 39 GTS 85 Sq yds.", "(8063.799 Sq mts.)", "Area :- 141 Sq yds.",
            "21 Sq yds.", "TOT-LOT AREA : 21,278 SQFT"]
    assert site_area(runs) == pytest.approx(8063.799)
    assert site_area(["AREA DETAILS"]) is None


def test_acres_and_guntas_keep_the_square_yards_written_after_them():
    assert parse_acre_gunta("1 ACR 39 GTS 85 Sq yds.") == pytest.approx(9644 * 0.83612736)
