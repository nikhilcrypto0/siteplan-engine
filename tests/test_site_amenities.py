"""The master-plan layer: facilities placed in the ground the buildings leave."""

import pytest
from shapely.geometry import Point, box

from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.site_amenities import AmenityLibrary, place_amenities

PLOT = box(0, 0, 160, 130)
FLATS = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3})
AMENITIES = AmenityLibrary(items=[
    # 12 x 6 m: with the true Table IV setbacks this made-up site packs six towers, and a
    # 20 x 10 m pool no longer finds ground; the placement rule is what is under test.
    {"name": "SWIMMING POOL", "width_m": 12.0, "depth_m": 6.0, "near": "club"},
    {"name": "CHILDRENS PLAY", "width_m": 10.0, "depth_m": 8.0, "near": "open space"},
    {"name": "SECURITY CABIN", "width_m": 3.5, "depth_m": 3.0, "near": "gate"},
])


@pytest.fixture(scope="module")
def option():
    return solve(PLOT, FLATS, REQUEST, abutting_road_m=18.0, amenities=AMENITIES)[0]


def test_facilities_are_placed_in_the_free_ground(option):
    assert option.amenities
    envelope = PLOT.buffer(-9)
    for amenity in option.amenities:
        assert envelope.contains(amenity.shape.buffer(-0.01))
        assert not any(t.footprint.intersects(amenity.shape.buffer(-0.01)) for t in option.towers)


def test_nothing_is_placed_on_the_open_space_the_rules_require(option):
    for amenity in option.amenities:
        assert not any(p.intersects(amenity.shape.buffer(-0.01)) for p in option.open_space)


def test_facilities_do_not_sit_on_each_other_or_on_the_parking(option):
    shapes = [a.shape for a in option.amenities]
    for i, shape in enumerate(shapes):
        assert not any(other.intersects(shape.buffer(-0.01)) for other in shapes[i + 1:])
        assert not any(bay.intersects(shape.buffer(-0.01)) for bay in option.parking_bays)


def test_each_facility_keeps_its_size(option):
    wanted = {item.name: item.area_sqm for item in AMENITIES.items}
    for amenity in option.amenities:
        assert amenity.shape.area == pytest.approx(wanted[amenity.name], rel=0.01)


def test_the_pool_lands_nearer_the_club_house_than_the_gate(option):
    pool = next((a for a in option.amenities if a.name == "SWIMMING POOL"), None)
    if pool is None or option.club_house is None or not option.gates:
        pytest.skip("this site did not hold a pool, a club house and a gate")
    gate = option.gates[0][1].centroid
    assert pool.shape.centroid.distance(option.club_house.centroid) < pool.shape.centroid.distance(
        gate
    )


def test_an_item_with_no_room_is_named_not_squeezed_in():
    room = box(0, 0, 12, 12)
    library = AmenityLibrary(items=[
        {"name": "SMALL", "width_m": 5.0, "depth_m": 5.0},
        {"name": "ENORMOUS", "width_m": 90.0, "depth_m": 40.0},
    ])
    placed, missed = place_amenities(room, library, 0.0, {"edge": Point(0, 0)})
    assert [p.name for p in placed] == ["SMALL"]
    assert missed == ["ENORMOUS"]


def test_the_summary_lists_the_facilities_and_what_did_not_fit(option):
    summary = option.summary()
    assert [a["name"] for a in summary["amenities"]] == [a.name for a in option.amenities]
    assert summary["amenities_with_no_room"] == list(option.amenities_missed)
