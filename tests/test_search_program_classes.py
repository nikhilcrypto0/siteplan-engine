"""The program's classes in the search (C4-08). What the law asks is never traded; what the brief
requires is the program, laid before what it prefers or leaves optional, a preference that takes
what the program leaves. A firm's library that says nothing of a facility leaves it preferred.
Made-up land and made-up facilities.
"""

from __future__ import annotations

from search_support import rectangle
from shapely.geometry import Point, box

from siteplan.adapters.legacy_site import amenity_request
from siteplan.contracts.design_brief import AmenityPriority, AmenityRequest, AmenitySetting
from siteplan.optimizer.search import ground
from siteplan.site_amenities import AmenityItem

TEST_CLASS = "normative"


def _asked(name: str, priority: AmenityPriority, size=(20.0, 30.0),
           setting=AmenitySetting.OUTDOOR) -> AmenityRequest:
    return AmenityRequest(name=name, priority=priority, setting=setting, footprint_m=size)


def test_with_room_for_one_the_required_facility_stands_before_a_preferred_one():
    """The firm lists the tennis court first; there is room for one of the two: the required
    play area takes it, and the court is named as without room."""
    made = rectangle()
    court = _asked("TENNIS COURT", AmenityPriority.PREFERRED, size=(18.0, 36.0))
    play = _asked("CHILDRENS PLAY", AmenityPriority.REQUIRED, size=(18.0, 36.0))
    room = box(0, 0, 20, 40)
    placed, missed = ground.place_facilities([court, play], made.rules, [], room, None, [0.0],
                                             Point(0, 0))
    assert [f.request.name for f in placed] == ["CHILDRENS PLAY"] and missed == ["TENNIS COURT"]


def test_a_library_that_says_nothing_leaves_a_facility_preferred_one_that_says_is_heard():
    item = AmenityItem(name="SWIMMING POOL", width_m=12.0, depth_m=25.0)
    assert AmenityRequest(**amenity_request(item)).priority is AmenityPriority.PREFERRED
    stated = AmenityItem(name="SWIMMING POOL", width_m=12.0, depth_m=25.0,
                         priority=AmenityPriority.REQUIRED)
    assert AmenityRequest(**amenity_request(stated)).priority is AmenityPriority.REQUIRED


def test_the_order_that_places_the_most_is_kept_not_the_first_fit_of_the_firms():
    """C4-10: room 34 x 21 m; the firm lists a 33 x 10 m deck first and two 15 m square courts after
    it. Laid first, the deck leaves no room for either court; the courts first, side by side, both
    stand: two facilities where the firm's order placed one."""
    made = rectangle()
    deck = _asked("DECK", AmenityPriority.PREFERRED, size=(33.0, 10.0))
    courts = [_asked(f"COURT {i}", AmenityPriority.PREFERRED, size=(15.0, 15.0)) for i in (1, 2)]
    room = box(0, 0, 34, 21)
    first_fit, _ = ground._place_in_order([deck, *courts], made.rules, [], room, None, [0.0],
                                         Point(0, 0))
    assert [f.request.name for f in first_fit] == ["DECK"]
    placed, missed = ground.place_facilities([deck, *courts], made.rules, [], room, None, [0.0],
                                             Point(0, 0))
    assert sorted(f.request.name for f in placed) == ["COURT 1", "COURT 2"]
    assert missed == ["DECK"]


def test_no_order_lays_a_preferred_facility_before_a_required_one():
    """Whatever order is searched, a required facility is laid before the preferred ones: with
    room for one, the required stands even where a preferred one would leave room for more."""
    made = rectangle()
    small = [_asked(f"SEAT {i}", AmenityPriority.PREFERRED, size=(5.0, 5.0)) for i in (1, 2, 3)]
    big = _asked("GYM YARD", AmenityPriority.REQUIRED, size=(18.0, 18.0))
    placed, missed = ground.place_facilities([*small, big], made.rules, [], box(0, 0, 19, 19),
                                             None, [0.0], Point(0, 0))
    assert [f.request.name for f in placed] == ["GYM YARD"]
    assert missed == ["SEAT 1", "SEAT 2", "SEAT 3"]
