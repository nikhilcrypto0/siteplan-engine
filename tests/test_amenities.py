"""Amenities: the club house takes its land before the towers, and the drive rings them."""

import pytest
from shapely.geometry import box

from siteplan.amenities import club_house, driveway_ring
from siteplan.checks import Status
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.rules import DRIVEWAY_MIN_WIDTH_M

PLOT = box(0, 0, 150, 120)  # 18,000 m², room for towers and amenities
LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
BASE = {"floors": 8, "unit_mix": {"2BHK": 0.7, "3BHK": 0.3}, "options": 3}


def plan(**extra):
    return solve(PLOT, LIBRARY, LayoutRequest(**BASE | extra), abutting_road_m=18.0)


def test_the_club_house_is_placed_inside_the_setbacks():
    envelope = PLOT.buffer(-9)
    block = club_house(envelope, 900)
    assert block is not None
    assert envelope.contains(block.buffer(-0.01))
    assert block.area == pytest.approx(900, rel=0.01)


def test_a_club_house_too_big_for_the_site_does_not_fit():
    assert club_house(PLOT.buffer(-9), 1_000_000) is None


def test_the_drive_rings_the_buildings_inside_the_setback():
    envelope = PLOT.buffer(-9)
    ring = driveway_ring(PLOT, envelope, DRIVEWAY_MIN_WIDTH_M)
    assert ring is not None
    assert PLOT.contains(ring.buffer(-0.01))          # never outside the plot
    assert not ring.intersects(envelope.buffer(-0.01))  # never under the buildings
    assert ring.area > 0


def test_reserving_a_club_house_costs_buildable_land():
    without = plan()[0]
    with_club = plan(club_house_sqm=1200)[0]
    assert with_club.club_house is not None
    assert with_club.saleable_sqft < without.saleable_sqft
    assert not any(t.footprint.intersects(with_club.club_house) for t in with_club.towers)


def test_the_club_house_is_not_counted_as_open_space():
    option = plan(club_house_sqm=1200)[0]
    assert not any(p.intersects(option.club_house.buffer(-0.01)) for p in option.open_space)


def test_a_club_house_that_cannot_fit_is_refused_rather_than_ignored():
    with pytest.raises(ValueError, match="does not fit"):
        plan(club_house_sqm=200_000)


@pytest.mark.parametrize(("extra", "rule", "status"), [
    ({}, "Driveway", Status.PASS),
    ({}, "Parking", Status.NOT_CHECKED),
    ({}, "Amenities (club house)", Status.INFO),           # 18,000 m² is under 5 acres
])
def test_the_new_rules_are_reported_on_every_option(extra, rule, status):
    findings = {f.rule: f for f in plan(**extra)[0].findings}
    assert findings[rule].status is status
    assert findings[rule].clause.startswith("G.O.168")


def test_a_big_site_asks_for_amenities_until_they_are_provided():
    big = box(0, 0, 200, 150)  # 30,000 m², over 5 acres
    request = LayoutRequest(**BASE)
    option = solve(big, LIBRARY, request, abutting_road_m=18.0)[0]
    assert {f.rule: f.status for f in option.findings}["Amenities (club house)"] is (
        Status.NEEDS_INPUT
    )

    with_club = solve(big, LIBRARY, LayoutRequest(**BASE | {"club_house_sqm": 1600}),
                      abutting_road_m=18.0)[0]
    assert {f.rule: f.status for f in with_club.findings}["Amenities (club house)"] is (
        Status.PASS
    )
