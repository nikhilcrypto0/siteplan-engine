"""The club house: sized by rule 15(a)(x), laid on ground the roads and fire lanes leave."""

import pytest
from shapely.geometry import box

from siteplan.layout import LayoutRequest, SiteFacts, search, solve
from siteplan.library import FlatLibrary

PLOT = box(0, 0, 150, 120)  # 18,000 m², room for towers and amenities
LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
BASE = {"floors": 8, "unit_mix": {"2BHK": 0.7, "3BHK": 0.3}, "options": 3}  # 27 m
FACTS = {"abutting_road_m": 18.0, "access_side": "S", "authority": "HMDA",
         "inside_cure": False}


def plan(**extra):
    return solve(PLOT, LIBRARY, LayoutRequest(**BASE | extra), **FACTS)


def test_by_default_the_amenities_block_is_three_percent_of_the_built_up_area():
    option = plan()[0]
    assert option.total_flats >= 100  # the clause applies from 100 units
    assert option.club_house is not None
    # Rule 15(a)(x): 3% of the total built-up area, the block itself included.
    assert option.club_house_sqm >= 0.03 * option.built_up_sqm
    assert option.club_house_sqm == pytest.approx(0.03 * option.built_up_sqm, rel=0.01)
    # Two storeys by default, so it takes half that much land.
    assert option.club_house.area == pytest.approx(option.club_house_sqm / 2, rel=0.01)


def test_the_club_house_keeps_off_roads_fire_lanes_and_the_tot_lot_and_its_gap_to_towers():
    option = plan()[0]
    club = option.club_house.buffer(-0.01)
    assert not any(club.intersects(r.shape) for r in option.roads)
    assert not club.intersects(option.fire_lanes)
    assert not any(p.intersects(club) for p in option.open_space)
    # Rule 7(a)(xii): the gap between two blocks is the Table IV figure, 9 m at 27 m.
    assert min(t.footprint.distance(option.club_house) for t in option.towers) >= 9.0


def test_a_small_scheme_gets_no_automatic_club_house():
    small = box(0, 0, 90, 70)
    option = solve(small, LIBRARY, LayoutRequest(**BASE | {"floors": 6}), **FACTS)[0]
    assert option.total_flats < 100 and option.club_house is None


def test_leaving_the_amenities_out_of_a_big_scheme_is_a_rejected_candidate_not_an_option():
    result = search(PLOT, LIBRARY, LayoutRequest(**BASE | {"club_house": False}),
                    SiteFacts(**FACTS))
    assert result.options == []
    reasons = [reason for rejected in result.rejected for reason in rejected.reasons]
    assert any(reason.startswith("Amenities (club house)") for reason in reasons)


def test_a_club_house_too_big_for_the_site_leaves_no_layout_and_says_why():
    result = search(PLOT, LIBRARY, LayoutRequest(**BASE | {"club_house_sqm": 200_000}),
                    SiteFacts(**FACTS))
    assert result.options == []
    assert "club house" in result.problem


def test_parking_uses_the_ghmc_column_inside_ghmc_and_asks_when_cure_is_not_known():
    def percent(extra=None, **facts):
        request = LayoutRequest(**BASE | (extra or {}))
        return solve(PLOT, LIBRARY, request, **FACTS | facts)[0].parking.percent

    assert percent(authority="GHMC") == 30.0
    assert percent() == 20.0
    # CURE not known decides 20% or 30%: a normal run stops and asks, it does not pick one.
    open_cure = search(PLOT, LIBRARY, LayoutRequest(**BASE),
                       SiteFacts(**FACTS | {"inside_cure": None}))
    assert open_cure.options == [] and open_cure.stopped
    assert "confirm the authority" in open_cure.problem
    # Only the named test mode plans the stricter column.
    assert percent({"conservative_parking": True}, inside_cure=None) == 30.0
