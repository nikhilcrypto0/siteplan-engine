import pytest

from siteplan.units import (
    SQM_PER_ACRE,
    acres_guntas_to_sqm,
    format_acre_gunta,
    format_indian,
    parse_acre_gunta,
    sqm_to_sqyd,
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
