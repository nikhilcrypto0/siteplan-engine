import pytest
from pydantic import ValidationError

from siteplan.project import SiteIn


def test_matching_paired_units_are_accepted():
    site = SiteIn(
        abutting_road_ft=40, abutting_road_m=12.19, net_area_sqyd=1000, net_area_sqm=836.1
    )
    assert site.abutting_road_m == 12.19


@pytest.mark.parametrize(
    "fields",
    [
        {"abutting_road_ft": 40, "abutting_road_m": 40},  # feet typed into the metres field
        {"master_plan_road_ft": 60, "master_plan_road_m": 12.19},
        {"net_area_sqyd": 1000, "net_area_sqm": 1000},
        {"gross_area_text": "3 AC 12.50 GTS", "gross_area_sqm": 10000},
    ],
)
def test_disagreeing_paired_units_are_rejected(fields):
    with pytest.raises(ValidationError, match="disagrees"):
        SiteIn(**fields)


def test_unreadable_area_text_is_rejected():
    with pytest.raises(ValidationError, match="not understood"):
        SiteIn(gross_area_text="about five acres")
