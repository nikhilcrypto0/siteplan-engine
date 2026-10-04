"""What the facilities on the site are: paved or soft is the brief's to say of each, never a guess
from its name (a review drew the same 8 x 8 m structure as PUMP ROOM and as PUMP HOUSE and got
two verdicts), and a gym inside the club house is the club house's ground, not another use."""

from validator_helpers import check, fixture, rectangle, shape, status

from siteplan.contracts.candidate import PlacedAmenity
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import AmenityRequest, AmenitySetting

TEST_CLASS = "normative"
Z = Status
OPEN_SPACE = "Organized open space (tot-lot)"
WATER = "Water-body buffer"
LEDGER = "Every square metre once"


def _asks(*requests):
    def edit(brief):
        brief.program.amenities = list(requests)
    return edit


def _place(*amenities):
    def edit(candidate):
        candidate.program.amenities = list(amenities)
    return edit


COURT = PlacedAmenity(name="TENNIS COURT", shape=rectangle(30.0, 12.0, 50.0, 22.0))  # 200 m²
PLAY = PlacedAmenity(name="CHILDRENS PLAY", shape=rectangle(30.0, 12.0, 42.0, 22.0))  # 120 m²


# --- on the tot-lot -------------------------------------------------------------------------


ROOM = PlacedAmenity(name="PUMP ROOM", shape=rectangle(30.0, 12.0, 50.0, 22.0))  # 200 m²


def test_a_built_facility_stood_on_the_tot_lot_takes_that_ground_from_the_share():
    inputs = fixture("rectangle").with_brief(_asks(AmenityRequest(
        name="PUMP ROOM", use="BUILT_SERVICE", surface="BUILT")))
    c = check(inputs.edited(_place(ROOM)).report(), OPEN_SPACE)
    assert c.finding.status is Z.FAIL  # 1,546 m² drawn, 200 m² of it built: under 1,500 and 1,545


def test_a_paved_court_on_the_tot_lot_rests_on_what_the_rules_etc_takes_in():
    """The rule names 'greenery, tot lot or soft landscaping, etc.': whether a paved court is of
    that kind is an open reading (open_space_other_uses), so the verdict holds under one reading
    only and is UNVERIFIED, never a FAIL the text does not support."""
    inputs = fixture("rectangle").with_brief(_asks(AmenityRequest(
        name="TENNIS COURT", use="SPORT_COURT", surface="HARD")))
    c = check(inputs.edited(_place(COURT)).report(), OPEN_SPACE)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading["open_space_other_uses"] == {"same_kind_only": Z.FAIL,
                                                     "any_open_recreation": Z.PASS}


def test_a_hard_tot_lot_is_unverified_never_an_automatic_fail():
    """The rule names the tot-lot and does not say its surface (tot_lot_surface is open)."""
    play = PlacedAmenity(name="CHILDRENS PLAY", shape=rectangle(30.0, 12.0, 50.0, 22.0))
    inputs = fixture("rectangle").with_brief(_asks(AmenityRequest(
        name="CHILDRENS PLAY", use="TOT_LOT", surface="HARD")))
    c = check(inputs.edited(_place(play)).report(), OPEN_SPACE)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading["tot_lot_surface"]["any_surface"] is Z.PASS


def test_a_soft_facility_on_the_tot_lot_counts_as_open_space():
    inputs = fixture("rectangle").with_brief(_asks(AmenityRequest(
        name="CHILDRENS PLAY", use="TOT_LOT", surface="SOFT")))
    assert status(inputs.edited(_place(PLAY)).report(), OPEN_SPACE) is Z.PASS


def test_a_facility_whose_surface_the_brief_does_not_say_leaves_the_share_unsettled():
    inputs = fixture("rectangle").edited(_place(PLAY))  # the brief asks for nothing
    c = check(inputs.report(), OPEN_SPACE)
    assert c.finding.status is Z.UNVERIFIED
    assert "Counts only if CHILDRENS PLAY" in c.finding.note
    named = fixture("rectangle").with_brief(_asks(AmenityRequest(
        name="CHILDRENS PLAY", surface="SOFT"))).edited(_place(PLAY))  # a surface, no use
    assert status(named.report(), OPEN_SPACE) is Z.UNVERIFIED  # never assumed from its name


def test_a_placed_facility_that_says_another_use_than_the_brief_blocks_a_pass():
    inputs = fixture("rectangle").with_brief(_asks(AmenityRequest(
        name="CHILDRENS PLAY", use="TOT_LOT", surface="SOFT")))
    claims = PLAY.model_copy(update={"use": "TOT_LOT", "surface": "HARD"})
    report = inputs.edited(_place(claims)).report()
    found = [d for d in report.cross_checks if d.item == "facility CHILDRENS PLAY: use and surface"]
    assert found and found[0].blocks_pass and "surface HARD" in found[0].theirs
    assert "use" not in found[0].theirs  # the use agrees


def test_a_facility_off_the_tot_lot_changes_nothing_whatever_its_surface():
    spa = PlacedAmenity(name="SPA", shape=rectangle(140.0, 92.0, 146.0, 96.0))  # off the pockets
    assert status(fixture("rectangle").edited(_place(spa)).report(), OPEN_SPACE) is Z.PASS


# --- in the water buffer --------------------------------------------------------------------


def _in_the_buffer(name):
    return PlacedAmenity(name=name, shape=rectangle(70.0, 50.0, 78.0, 58.0))


def test_a_paved_or_built_facility_in_a_water_buffer_fails_however_it_is_named():
    for name in ("PUMP ROOM", "PUMP HOUSE"):
        inputs = fixture("nala_plot").with_brief(_asks(AmenityRequest(name=name, surface="HARD")))
        c = check(inputs.edited(_place(_in_the_buffer(name))).report(), WATER)
        assert c.finding.status is Z.FAIL and name in c.finding.measured


def test_a_facility_in_a_water_buffer_whose_surface_is_not_said_is_unverified():
    c = check(fixture("nala_plot").edited(_place(_in_the_buffer("PUMP HOUSE"))).report(), WATER)
    assert c.finding.status is Z.UNVERIFIED and "surface not stated" in c.finding.measured


def test_a_soft_facility_in_a_water_buffer_is_greenery_and_fine():
    inputs = fixture("nala_plot").with_brief(_asks(AmenityRequest(name="GARDEN", surface="SOFT")))
    assert status(inputs.edited(_place(_in_the_buffer("GARDEN"))).report(), WATER) is Z.PASS


# --- in the club house ----------------------------------------------------------------------


def _gym(setting):
    def edit(candidate):
        club = candidate.program.club_house.shape.to_shapely()
        candidate.program.amenities = [PlacedAmenity(
            name="GYM", shape=shape(club.buffer(-2.0)), setting=setting)]
    return edit


def test_an_amenity_placed_in_the_club_house_is_the_club_houses_ground_not_another_use():
    assert status(fixture("rectangle").edited(_gym(AmenitySetting.CLUB_HOUSE)).report(),
                  LEDGER) is Z.PASS


def test_the_same_amenity_placed_outdoors_on_the_club_house_is_a_conflict():
    assert status(fixture("rectangle").edited(_gym(AmenitySetting.OUTDOOR)).report(),
                  LEDGER) is Z.FAIL
