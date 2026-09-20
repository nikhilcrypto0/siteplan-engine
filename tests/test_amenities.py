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
    without = plan(club_house=False)[0]
    with_club = plan(club_house_sqm=1200)[0]
    assert without.club_house is None
    assert with_club.club_house is not None
    assert with_club.saleable_sqft < without.saleable_sqft
    assert not any(t.footprint.intersects(with_club.club_house) for t in with_club.towers)


def test_the_club_house_is_not_counted_as_open_space():
    option = plan(club_house_sqm=1200)[0]
    assert not any(p.intersects(option.club_house.buffer(-0.01)) for p in option.open_space)


def test_by_default_the_amenities_block_is_sized_from_the_rule():
    option = plan()[0]
    assert option.total_flats >= 100  # the clause applies from 100 units
    assert option.club_house is not None
    # Rule 15(a)(x): 3% of built-up area, measured on the pass before the block takes its land,
    # so the block is a little larger than 3% of what is finally built. Erring high is safe.
    unbuilt = plan(club_house=False)[0]
    assert option.club_house_sqm == pytest.approx(0.03 * unbuilt.built_up_sqm, rel=0.05)
    assert option.club_house_sqm > 0.03 * option.built_up_sqm
    # Two storeys by default, so it only takes half that much land.
    assert option.club_house.area == pytest.approx(option.club_house_sqm / 2, rel=0.01)


def test_a_small_scheme_gets_no_automatic_club_house():
    small = box(0, 0, 70, 60)
    option = solve(small, LIBRARY, LayoutRequest(**BASE), abutting_road_m=18.0)[0]
    assert option.total_flats < 100 and option.club_house is None


def test_a_club_house_that_cannot_fit_is_refused_rather_than_ignored():
    with pytest.raises(ValueError, match="does not fit"):
        plan(club_house_sqm=200_000)


@pytest.mark.parametrize(("rule", "status"), [
    ("Driveway", Status.PASS),
    ("Amenities (club house)", Status.PASS),   # the default block satisfies the 3%
    ("Parking", Status.NEEDS_INPUT),           # a stilt alone cannot reach 20% of built-up
])
def test_the_new_rules_are_reported_on_every_option(rule, status):
    findings = {f.rule: f for f in plan()[0].findings}
    assert findings[rule].status is status
    assert findings[rule].clause.startswith("G.O.168")


def test_leaving_the_amenities_out_of_a_big_scheme_fails_the_rule():
    finding = {f.rule: f for f in plan(club_house=False)[0].findings}["Amenities (club house)"]
    assert finding.status is Status.FAIL
    assert "3%" in finding.required


def test_parking_uses_the_ghmc_column_only_inside_ghmc():
    def required(option):
        return next(f.required for f in option.findings if f.rule == "Parking")

    inside = solve(PLOT, LIBRARY, LayoutRequest(**BASE), abutting_road_m=18.0, authority="GHMC")[0]
    assert "30%" in required(inside)
    assert "20%" in required(plan()[0])
