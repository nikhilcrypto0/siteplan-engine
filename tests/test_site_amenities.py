"""The master-plan layer: facilities placed in the ground the buildings leave."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from shapely.geometry import Point, box

from siteplan.contracts.common import FacilityUse, Surface
from siteplan.layout import LayoutRequest, solve
from siteplan.library import FlatLibrary
from siteplan.site_amenities import AmenityLibrary, place_amenities

EXAMPLES = Path(__file__).parent.parent / "examples"
PLOT = box(0, 0, 180, 140)  # room left for the facilities once the rules have their land
FLATS = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 0.7, "3BHK": 0.3},
                        conservative_parking=True)  # no jurisdiction given: test mode
AMENITIES = AmenityLibrary(items=[
    # 12 x 6 m: with the true Table IV setbacks this made-up site packs six towers, and a
    # 20 x 10 m pool no longer finds ground; the placement rule is what is under test.
    {"name": "SWIMMING POOL", "width_m": 12.0, "depth_m": 6.0, "near": "club"},
    {"name": "CHILDRENS PLAY", "width_m": 10.0, "depth_m": 8.0, "near": "open space"},
    {"name": "SECURITY CABIN", "width_m": 3.5, "depth_m": 3.0, "near": "gate"},
])


@pytest.fixture(scope="module")
def option():
    # The placement rule is under test, so take an option that had ground for facilities: the
    # maximum-yield option may fill the ground with towers and name every facility as missed.
    options = solve(PLOT, FLATS, REQUEST, abutting_road_m=18.0, amenities=AMENITIES)
    return next(o for o in options if o.amenities)


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


def test_each_facility_lands_by_its_own_anchor():
    """The pool goes by the club house and the cabin by the gate, wherever those two are."""
    strip = box(0, 0, 120, 20)
    anchors = {"club": Point(5, 10), "gate": Point(115, 10)}
    placed, missed = place_amenities(strip, AMENITIES, 0.0, anchors)
    where = {a.name: a.shape.centroid for a in placed}
    assert where["SWIMMING POOL"].distance(anchors["club"]) < 15
    assert where["SECURITY CABIN"].distance(anchors["gate"]) < 5


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


def test_a_facilitys_use_and_surface_are_stated_or_unknown_never_guessed():
    """Where the placer may stand an item says nothing of what its ground is made of."""
    play = AMENITIES.items[1]
    assert play.name == "CHILDRENS PLAY" and (play.use, play.surface) == (None, None)
    seat = AmenityLibrary(items=[{"name": "SEATING", "width_m": 8.0, "depth_m": 6.0,
                                  "counts_as_open_space": True}]).items[0]
    assert seat.surface is None
    stated = AmenityLibrary(items=[{"name": "SEATING", "width_m": 8.0, "depth_m": 6.0,
                                    "use": "SOFT_LANDSCAPE", "surface": "SOFT"}]).items[0]
    assert (stated.use, stated.surface) == (FacilityUse.SOFT_LANDSCAPE, Surface.SOFT)
    with pytest.raises(ValidationError):
        AmenityLibrary(items=[{"name": "SEATING", "width_m": 8.0, "depth_m": 6.0,
                               "surface": "GRASS"}])


@pytest.mark.parametrize("name", ["amenities.example.json", "amenities.hyderabad.json"])
def test_the_example_libraries_state_every_items_use_and_surface(name):
    library = AmenityLibrary.model_validate_json((EXAMPLES / name).read_text())
    assert all(item.use is not None and item.surface is not None for item in library.items)
    by_name = {item.name: item for item in library.items}
    assert by_name["SECURITY CABIN"].surface is Surface.BUILT
    assert by_name["CHILDRENS PLAY"].use is FacilityUse.TOT_LOT
    # an item the placer may stand on the open space is one this list states as soft
    assert all(item.surface is Surface.SOFT for item in library.items
               if item.counts_as_open_space)
