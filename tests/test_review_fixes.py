"""The review of 2026-10-01: rule 8 only on a Group Development Scheme, no parking share picked
when whose rules apply is open, and the classifications that follow."""

import pytest
from shapely.geometry import box

from siteplan import rules
from siteplan.checks import Building, Site, Status, check_site
from siteplan.constraints import REGISTRY, Basis, by_basis
from siteplan.heights import search_heights
from siteplan.layout import LayoutRequest, SiteFacts, search
from siteplan.library import FlatLibrary

LIBRARY = FlatLibrary(
    flats=[{"name": "2A", "bhk": "2BHK", "width_m": 7.7, "depth_m": 11.0, "saleable_sqft": 1112}],
    core_width_m=7.5,
)
REQUEST = LayoutRequest(floors=8, unit_mix={"2BHK": 1.0})
SETTLED = {"abutting_road_m": 18.0, "authority": "HMDA", "inside_cure": False}


def _road_findings(gross_sqm: float):
    tower = Building("A", height_m=27.0, footprint=box(20, 20, 40, 40))
    site = Site(gross_area_sqm=gross_sqm, net_plot=box(0, 0, 60, 60), buildings=(tower,))
    return [f for f in check_site(site) if f.rule.startswith("Internal roads")]


def test_rule_8_is_not_applied_below_the_group_development_threshold():
    small = _road_findings(3_600)
    assert [(f.rule, f.status) for f in small] == [("Internal roads (rule 8)", Status.INFO)]
    assert "not a Group Development Scheme" in small[0].measured
    assert "2(c)" in small[0].clause
    large = _road_findings(4_000)  # at the threshold rule 8 applies; no roads drawn here
    assert large[0].status is Status.NOT_CHECKED


def test_a_site_under_4000_m2_is_not_laid_out_with_8m_roads():
    result = search(box(0, 0, 60, 60), LIBRARY, REQUEST, SiteFacts(**SETTLED))
    assert result.stopped and result.options == []
    assert "rule 2(c)" in result.problem and "not supported yet" in result.problem


def test_an_open_jurisdiction_is_not_tried_at_any_height_and_says_what_to_ask():
    plot = box(0, 0, 150, 120)
    found = search_heights(plot, LIBRARY, REQUEST,
                           SiteFacts(abutting_road_m=18.0, authority="HMDA", inside_cure=None))
    assert found.options == []
    assert {r.verdict for r in found.results} == {"NOT TRIED"}
    assert "confirm the authority" in found.results[0].reasons()[0]


def test_a_checked_project_with_no_jurisdiction_passes_parking_only_at_the_stricter_share():
    tower = Building("A", height_m=27.0, footprint=box(20, 20, 60, 40))  # 800 m² of stilt
    base = {"gross_area_sqm": 10_000, "net_plot": box(0, 0, 100, 100), "buildings": (tower,)}

    def parking(built_up: float) -> Status:
        found = check_site(Site(built_up_sqm=built_up, **base))
        return next(f for f in found if f.rule == "Parking (Table V)").status

    assert parking(2_500) is Status.PASS  # 800 m² >= 30% of 2,500
    assert parking(3_500) is Status.UNVERIFIED  # enough at 20%, short at 30%


def test_what_the_review_said_is_settled_is_no_longer_called_an_interpretation():
    unresolved = {c.what for c in by_basis(Basis.UNRESOLVED_INTERPRETATION)}
    for settled in ("front included", "net plot line", "4,000", "least of the 9 to 18 m",
                    "takes its access from an internal road", "What counts as parking"):
        assert not any(settled in what for what in unresolved), settled
    for still_open in ("counts the stilt", "The site area the 10% is taken of",
                       "different heights", "amenities (club house) area",
                       "9 m turning radius", "extra cellar setback",
                       "road or a fire lane may run inside a water buffer"):
        assert any(still_open in what for what in unresolved), still_open


def test_the_approach_road_law_and_the_optimisers_choice_are_kept_apart():
    law = next(c for c in REGISTRY if c.symbols and "rules.MAIN_APPROACH_ROAD_M" in c.symbols)
    choice = next(c for c in REGISTRY if c.symbols == ("access.APPROACH_M",))
    assert law.basis is Basis.LEGAL_RULE and "9-18 m" in law.value
    assert choice.basis is Basis.ENGINE_DESIGN_ASSUMPTION


@pytest.mark.parametrize("what", ["How each part is measured", "physically fit cars",
                                  "size of a parking bay", "Conservative test mode"])
def test_parking_method_is_engine_or_firm_never_law_or_reading(what):
    entry = next(c for c in REGISTRY if what in c.what)
    assert entry.basis in (Basis.ENGINE_DESIGN_ASSUMPTION, Basis.FIRM_STANDARD)


def test_the_group_development_threshold_is_the_rule_as_written():
    assert rules.is_group_development(4_000) and not rules.is_group_development(3_999)
    entry = next(c for c in REGISTRY if "rules.GROUP_DEVELOPMENT_MIN_SITE_SQM" in c.symbols)
    assert entry.basis is Basis.LEGAL_RULE
