"""The program (what the architect and the firm asked for) is judged apart from the law: a
shortfall of the brief changes the program verdict, never the legal one."""

import pytest
from validator_helpers import (
    check,
    fixture,
    rectangle,
    set_floors,
)

from siteplan.contracts.candidate import Cellars, PlacedAmenity
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import (
    AmenityPriority,
    AmenityRequest,
    ClubSize,
    HeightMode,
    UnitsMode,
)
from siteplan.contracts.validation import Family, ProgramVerdict

TEST_CLASS = "normative"
Z = Status


def _mix(shares, tolerance=None):
    def edit(brief):
        brief.program.unit_mix.value = shares
        if tolerance is not None:
            brief.program.mix_tolerance = tolerance
    return edit


def test_a_met_program_is_met_and_the_unit_mix_is_counted_from_the_prototypes():
    report = fixture("nala_plot").report()
    assert report.verdict.program is ProgramVerdict.MET
    c = check(report, "Unit mix")
    assert c.finding.status is Z.PASS and "0.75" in c.finding.measured  # 48 and 16 of 64


def test_a_missed_unit_mix_changes_the_program_verdict_and_never_the_legal_one():
    before = fixture("nala_plot")
    after = before.with_brief(_mix({"2BHK": 0.1, "3BHK": 0.9}))
    a, b = before.report(), after.report()
    assert a.verdict.program is ProgramVerdict.MET
    assert b.verdict.program is ProgramVerdict.PARTLY_MET
    assert check(b, "Unit mix").finding.status is Z.FAIL
    assert b.legal == a.legal and b.verdict.legal is a.verdict.legal  # not one legal check moved
    assert all(c.family is Family.PROGRAM for c in b.program)
    assert not [c for c in b.legal if c.family is Family.PROGRAM]


def test_a_mix_missed_by_every_check_is_not_met_and_the_law_is_still_the_laws():
    inputs = fixture("nala_plot").with_brief(_mix({"2BHK": 0.0, "3BHK": 1.0}))
    inputs = inputs.with_brief(lambda b: setattr(b.program.units, "mode", UnitsMode.TARGET))
    inputs = inputs.with_brief(lambda b: setattr(b.program.units, "target", 400))
    inputs = inputs.with_brief(lambda b: setattr(b.program.club_house.wanted, "value", True))
    report = inputs.report()
    assert report.verdict.legal is fixture("nala_plot").report().verdict.legal
    assert report.verdict.program in (ProgramVerdict.PARTLY_MET, ProgramVerdict.NOT_MET)
    assert check(report, "Unit mix").finding.status is Z.FAIL
    assert check(report, "Units").finding.status is Z.FAIL


def test_the_mix_tolerance_is_the_briefs():
    assert check(fixture("rectangle").report(), "Unit mix").finding.status is Z.FAIL  # 0.085
    loose = fixture("rectangle").with_brief(_mix({"2BHK": 0.7, "3BHK": 0.3}, tolerance=0.1))
    assert check(loose.report(), "Unit mix").finding.status is Z.PASS


@pytest.mark.parametrize("mode, kwargs, expected", [
    (UnitsMode.MAXIMISE, {}, Z.INFO),
    (UnitsMode.TARGET, {"target": 208}, Z.PASS),
    (UnitsMode.TARGET, {"target": 300}, Z.FAIL),
    (UnitsMode.RANGE, {"minimum": 200, "maximum": 220}, Z.PASS),
    (UnitsMode.RANGE, {"minimum": 220, "maximum": 260}, Z.FAIL),
])
def test_the_units_asked_for(mode, kwargs, expected):
    def ask(brief):
        for field in ("target", "minimum", "maximum"):
            setattr(brief.program.units, field, kwargs.get(field))
        brief.program.units.mode = mode
    assert check(fixture("rectangle").with_brief(ask).report(), "Units").finding.status is expected


def test_a_club_house_asked_for_but_not_drawn_is_a_shortfall_of_the_brief():
    def ask(brief):
        brief.program.club_house.wanted.value = True
        brief.program.club_house.size = ClubSize.FIRM_STANDARD
    report = fixture("nala_plot").with_brief(ask).report()
    assert check(report, "Club house").finding.status is Z.FAIL
    legal_club = check(report, "Amenities (club house)")
    assert legal_club.finding.status is Z.INFO  # under 100 units the law asks for none


def test_the_legal_minimum_club_house_of_a_small_scheme_is_none_and_that_meets_the_brief():
    assert check(fixture("nala_plot").report(), "Club house").finding.status is Z.PASS


def test_a_stated_club_house_size_is_held_to():
    def ask(brief):
        brief.program.club_house.size = ClubSize.STATED
        brief.program.club_house.sqm = 2_000.0
    c = check(fixture("rectangle").with_brief(ask).report(), "Club house")
    assert c.finding.status is Z.FAIL and "of the 2,000 m² asked" in c.finding.measured


def _amenity(name, priority):
    def ask(brief):
        brief.program.amenities = [AmenityRequest(name=name, priority=priority)]
    return ask


def test_an_amenity_asked_for_is_placed_or_it_is_not():
    absent = fixture("rectangle").with_brief(_amenity("SWIMMING POOL", AmenityPriority.REQUIRED))
    assert check(absent.report(), "Amenity: SWIMMING POOL").finding.status is Z.FAIL

    def place(candidate):
        candidate.program.amenities.append(PlacedAmenity(
            name="Swimming Pool", shape=rectangle(20.0, 13.0, 40.0, 20.0)))
    placed = absent.edited(place)
    assert check(placed.report(), "Amenity: SWIMMING POOL").finding.status is Z.PASS


def test_an_amenity_with_no_room_says_so_and_an_optional_one_is_only_noted():
    def missed(candidate):
        candidate.program.amenities_missed = ["SWIMMING POOL"]
    pool = fixture("rectangle").with_brief(_amenity("SWIMMING POOL", AmenityPriority.PREFERRED))
    c = check(pool.edited(missed).report(), "Amenity: SWIMMING POOL")
    assert c.finding.status is Z.FAIL and "no room found" in c.finding.measured
    optional = fixture("rectangle").with_brief(_amenity("JOGGING TRACK",
                                                        AmenityPriority.OPTIONAL))
    assert check(optional.report(), "Amenity: JOGGING TRACK").finding.status is Z.INFO


def test_the_height_asked_for_is_held_to():
    def fixed(brief):
        brief.height_intent.mode = HeightMode.FIXED
        brief.height_intent.floors_above_stilt = 9
    c = check(fixture("rectangle").with_brief(fixed).report(), "Height intent")
    assert c.finding.status is Z.FAIL and "not 9" in c.finding.measured

    def mixed_not_allowed(brief):
        brief.height_intent.mixed_heights_allowed = False
    inputs = fixture("rectangle").with_brief(mixed_not_allowed).edited(
        lambda c: set_floors(c, "T3", 7))
    assert "heights are mixed" in check(inputs.report(), "Height intent").finding.measured


def test_the_firms_standards_and_parking_preferences_are_held_to_and_are_not_law():
    def strict(brief):
        brief.firm_standards.max_tower_length_m = type(brief.firm_standards.stilt_height_m)(
            value=60.0, status="USER_CONFIRMED", source_kind="FIRM_STANDARD", source="made up")
        brief.program.parking.surface_bays_allowed = False
        brief.program.parking.max_cellars.value = 0
    report = fixture("rectangle").with_brief(strict).report()
    c = check(report, "Firm standards and parking preferences")
    assert c.finding.status is Z.FAIL
    for part in ("longest block 72.0 m over the firm's 60 m", "surface bays drawn",
                 "1 cellar levels, the brief allows 0"):
        assert part in c.finding.measured
    assert report.verdict.legal is fixture("rectangle").report().verdict.legal


def test_the_cellars_asked_for_are_a_preference_not_a_rule():
    def deeper(candidate):
        candidate.program.cellars = Cellars(levels=4, outline=candidate.program.cellars.outline)
    inputs = fixture("rectangle").edited(deeper)
    # the brief allows 3: a program shortfall, even if the law has no limit on cellars
    assert check(inputs.report(), "Firm standards and parking preferences").finding.status is (
        Z.FAIL)
