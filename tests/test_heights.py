"""The height search: top down, the law first, then the ground, each rejection with its reason."""

from shapely.geometry import box

from siteplan.findings import Status
from siteplan.heights import heights_to_try, legal_findings, search_heights
from siteplan.layout import LayoutRequest, SiteFacts
from siteplan.library import FlatLibrary

PLOT = box(0, 0, 150, 120)
LIBRARY = FlatLibrary(
    flats=[
        {"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112},
        {"name": "3A", "bhk": "3BHK", "width_m": 10.5, "depth_m": 11.0, "saleable_sqft": 1517},
    ],
    core_width_m=7.5,
)
MIX = {"2BHK": 0.7, "3BHK": 0.3}
FACTS = SiteFacts(abutting_road_m=18.29, access_side="S", authority="HMDA", inside_cure=False)


def test_heights_run_from_one_above_the_legal_limit_down_to_the_lowest_high_rise():
    request = LayoutRequest(floors=9, unit_mix=MIX, maximise=True)
    assert heights_to_try(request) == [10, 9, 8, 7, 6]  # 6 floors on a 3 m stilt is 21 m
    assert heights_to_try(request.model_copy(update={"maximise": False})) == [9]


def test_a_height_the_road_cannot_serve_fails_on_the_law_and_is_not_drawn():
    """Measured from the ground, the stilt floor 0.15 m up (NBC Part 3 12.1.2): stilt + 9 on
    3 m storeys is 30.15 m, past the 60 ft road's 30 m."""
    found = search_heights(PLOT, LIBRARY, LayoutRequest(floors=8, unit_mix=MIX, maximise=True),
                           FACTS)
    top = found.results[0]
    assert (top.floors, top.verdict, top.search) == (9, "FAIL (law)", None)
    assert top.reasons()[0].startswith("Abutting road width: 18.29 m; needs >= 24 m")
    assert found.max_legal_floors == 8
    assert found.max_feasible_floors == 8
    assert found.options and all(not option.fails for option in found.options)
    assert [r.floors for r in found.results] == [9, 8, 7, 6]


def test_above_30_m_an_unknown_dead_end_is_unverified_and_a_known_one_fails():
    request = LayoutRequest(floors=10, unit_mix=MIX)

    def dead_end(**facts):
        found = legal_findings(10, request, SiteFacts(abutting_road_m=24.0, **facts), PLOT)
        return next(f for f in found if f.rule == "Dead-end road").status

    assert dead_end() is Status.UNVERIFIED
    assert dead_end(road_dead_end=True) is Status.FAIL
    assert dead_end(road_dead_end=False) is Status.PASS
    ends = SiteFacts(abutting_road_m=18.3, road_dead_end=True)
    eight = legal_findings(8, LayoutRequest(floors=8, unit_mix=MIX), ends, PLOT)
    assert not any(f.rule == "Dead-end road" for f in eight)  # 27.15 m: a dead end is allowed
    nine = legal_findings(9, LayoutRequest(floors=9, unit_mix=MIX), ends, PLOT)
    # 30.15 m from the ground, the stilt floor's raise in it: over 30 m on a dead end
    assert next(f for f in nine if f.rule == "Dead-end road").status is Status.FAIL


def test_without_coordinates_the_airport_height_stays_unverified_and_blocks_nothing():
    found = legal_findings(9, LayoutRequest(floors=9, unit_mix=MIX), FACTS, PLOT)
    airport = next(f for f in found if f.rule.startswith("Airport"))
    assert airport.status is Status.UNVERIFIED


def test_a_height_the_ground_cannot_hold_says_what_stopped_it():
    """With no cellars allowed, the stilt and surface cannot carry Table V at any high-rise
    height here, so every height fails on the site, and says it is the parking."""
    request = LayoutRequest(floors=7, unit_mix=MIX, maximise=True, max_cellars=0)
    found = search_heights(PLOT, LIBRARY, request, FACTS)
    tried = [r for r in found.results if not r.legal_fails]
    assert tried and all(r.verdict == "FAIL (site)" for r in tried)
    assert all("parking" in " ".join(r.reasons()) for r in tried)
    assert found.options == [] and found.max_feasible_floors is None
