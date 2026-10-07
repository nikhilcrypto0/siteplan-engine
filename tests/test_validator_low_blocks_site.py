"""The rest of what a block below 21 m is held to: the club house's own band, rule 8(l)'s roads and
pathways, and fire access, where NBC 4.6 holds a low block only as a special building (over a
large or deep cellar) or, under one reading, from NBC's own 15 m, and the report says which.

Every band is MADE UP (tests/validator_low_helpers.py); no figure is a value of the order. The
pathways, drawn, are in test_validator_pathways.py and the planting in test_validator_planting.py.
"""

from shapely import affinity
from validator_helpers import (
    check,
    fixture,
    move_tower,
    rectangle,
    select,
    set_floors,
    shape,
    status,
)
from validator_low_helpers import (
    MADE_UP,
    all_low,
    flat,
    floors_of,
    low_band,
    spacing_open,
    unmodelled_below,
    with_bands_below,
    with_low_bands,
)

from siteplan.contracts.candidate import PlacedAmenity
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import NBC_FIRE_HEIGHT, STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import Family

TEST_CLASS = "normative"
Z = Status
COUNTED, NOT_COUNTED = "counted", "not_counted"
CLUB_SETBACK = "Club house: setback"
SERVED = "Internal roads: every block served"
PATHWAYS = "Internal roads: blocks up to 12 m (pathways)"
BELOW = "Fire access below 21 m (rule 15(a)(i))"
RULE_15_A_I = ('"The building requirements and standards other than heights and setbacks '
               'specified in the National Building Code - 2005 shall be complied with."')


def _counted(inputs):
    """Only the reading in which the stilt counts, for the high-rise blocks of a mixed layout."""
    return inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))


def _club_edge_at(candidate, x):
    """The club house moved so that its east edge is at `x` (the plot's east boundary is 150)."""
    club = candidate.program.club_house
    bounds = club.shape.to_shapely().bounds
    club.shape = shape(affinity.translate(club.shape.to_shapely(), x - bounds[2], 0.0))


def _club_west_by(candidate, metres):
    club = candidate.program.club_house
    club.shape = shape(affinity.translate(club.shape.to_shapely(), -metres, 0.0))


def _off_the_roads(candidate, name="T3"):
    move_tower(candidate, name, 0.0, -10.0)  # 34 m from the nearest road


def _no_cellar(candidate):
    candidate.program.cellars = None


def _cabin_beside_t3(candidate):
    candidate.program.amenities.append(
        PlacedAmenity(name="SECURITY CABIN", shape=rectangle(134.5, 40.0, 137.0, 42.5)))


def _names(report, family):
    return {c.finding.rule for c in report.legal if c.family is family}


# --- the club house, through its own band ------------------------------------------------------


def test_the_club_houses_setback_is_its_own_bands_where_the_rules_model_it():
    """A 2-floor club house is 6 m: band A, 2.3 m. 3.0 m from the boundary passes, 2.0 m fails;
    it is no longer NOT_CHECKED, and a low club house that passes is a PASS (only one as tall as
    a high-rise cannot, which test_validator_club_spacing keeps)."""
    inputs = with_low_bands(fixture("rectangle"))
    assert status(inputs.report(), CLUB_SETBACK) is Z.PASS
    near = inputs.edited(lambda c: _club_edge_at(c, 147.0))
    assert status(near.report(), CLUB_SETBACK) is Z.PASS
    too_near = check(inputs.edited(lambda c: _club_edge_at(c, 148.0)).report(), CLUB_SETBACK)
    assert too_near.finding.status is Z.FAIL
    assert too_near.finding.required == ">= 2.30 m to the net plot line"
    assert MADE_UP in too_near.finding.clause
    assert status(unmodelled_below(fixture("rectangle")).report(), CLUB_SETBACK) is Z.NOT_CHECKED
    shipped = check(fixture("rectangle").report(), CLUB_SETBACK)  # Table III's own band (A2)
    assert shipped.finding.status is Z.PASS and "Table III" in shipped.finding.clause


def test_a_club_house_in_a_band_the_rules_do_not_model_is_not_checked():
    bands = (low_band(0, 9, setback=None, road=None, modelled=False),
             low_band(9, 18, setback=3.7, gap=4.3, road=8.4),
             low_band(18, 21, setback=4.9, gap=5.7, road=11.6, up_to_inclusive=False))
    report = with_bands_below(all_low(fixture("rectangle")), bands).report()
    c = check(report, CLUB_SETBACK)  # 6 m: the band that is not modelled
    assert c.finding.status is Z.NOT_CHECKED and "Table III" in c.finding.note
    assert status(report, "All-round setback: T1") is Z.PASS  # the towers' band is modelled
    # the club house is lower than the towers, so the towers' gap is the one asked, as before
    assert status(report, "Club house gap to T1") is Z.PASS


def test_a_club_house_keeps_the_gap_its_band_and_the_towers_ask():
    """A 6 m club house (band A, 3.1 m) beside 15 m towers (band B, 4.3 m): two blocks below the
    high-rise height, so the tallest block's gap, 4.3 m, whatever mixed-height spacing says."""
    base = spacing_open(with_low_bands(all_low(fixture("rectangle"))))
    assert status(base.report(), "Club house gap to T1") is Z.PASS  # 9.02 m
    near = check(base.edited(lambda c: _club_west_by(c, 5.0)).report(),
                 "Club house gap to T1")  # 4.02 m
    assert near.finding.status is Z.FAIL
    assert ">= 4.30 m (the tallest block's side setback)" in near.finding.required
    assert "rule 5(f)(xiii)" in near.finding.note
    just = base.edited(lambda c: _club_west_by(c, 4.7))  # 4.32 m
    assert status(just.report(), "Club house gap to T1") is Z.PASS


def test_a_club_house_beside_a_high_rise_is_judged_under_every_reading_of_spacing():
    """T1 is 27 m (Table IV, 9 m); the 6 m club house is band A (3.1 m): 7.02 m clears the mean of
    the two (6.05 m) and not the taller block's gap."""
    inputs = _counted(spacing_open(with_low_bands(flat(fixture("rectangle"), T2=5)))
                      ).edited(lambda c: _club_west_by(c, 2.0))
    c = check(inputs.report(), "Club house gap to T1")
    assert c.finding.status is Z.UNVERIFIED
    assert sorted(c.by_reading["mixed_height_spacing"].values(), key=str) == [Z.FAIL, Z.PASS]
    assert "6.05 m" in c.finding.required


# --- rule 8(l): the blocks up to 12 m and the blocks above ----------------------------------------


def test_a_block_up_to_12_m_on_an_internal_road_is_served():
    report = with_low_bands(all_low(fixture("rectangle"), 3)).report()  # 9 m
    c = check(report, PATHWAYS)
    assert c.finding.status is Z.PASS and c.finding.measured == "all 3 on an internal road"
    assert "8(l)" in c.finding.clause


def test_every_block_is_in_exactly_one_of_the_two_rule_8l_checks():
    """Above 12 m a block opens onto a road (FAIL if not); up to 12 m, exactly 12 included, it may
    take a pathway. A block moves from one check to the other at 12 m and is in only one."""
    def with_t3(floors):
        return fixture("rectangle").edited(lambda c: (set_floors(c, "T3", floors),
                                                      _off_the_roads(c)))
    twelve = with_t3(3).report()  # 3 m stilt + 9 m: exactly 12 m
    assert check(twelve, SERVED).finding.measured == "all 2 blocks"
    assert "T3" in check(twelve, PATHWAYS).finding.measured
    fifteen = with_t3(4).report()
    assert check(fifteen, SERVED).finding.status is Z.FAIL
    assert "T3" in check(fifteen, SERVED).finding.measured
    assert PATHWAYS not in {c.finding.rule for c in fifteen.legal}  # no block up to 12 m


def test_a_layout_of_blocks_all_up_to_12_m_has_no_vacuous_every_block_served():
    report = with_low_bands(all_low(fixture("rectangle"), 3)).report()
    names = {c.finding.rule for c in report.legal}
    assert SERVED not in names and PATHWAYS in names


def test_when_the_rules_read_a_pathway_as_open_to_any_block_neither_check_is_made():
    def read_otherwise(rules):
        rules.circulation.block_over_12m_on_road.value = False
    names = {c.finding.rule
             for c in fixture("rectangle").with_rules(read_otherwise).report().legal}
    assert SERVED not in names and PATHWAYS not in names


def test_a_low_block_above_12_m_off_every_road_fails_as_a_high_rise_would():
    """Rule 8(l) holds every block above 12 m, whatever its table: 15 m is below 21 m and still
    must open onto an internal road."""
    inputs = with_low_bands(all_low(fixture("rectangle"))).edited(_off_the_roads)
    c = check(inputs.report(), SERVED)
    assert c.finding.status is Z.FAIL and c.finding.measured == "not on a road: T3"


# --- fire access below 21 m ----------------------------------------------------------------------


def test_a_low_block_over_no_cellar_and_below_15_m_is_not_held_to_nbc_4_6():
    """12 m blocks over no cellar are neither high-rise (not at the state's 21 m, nor at NBC's own
    15 m) nor special buildings, so NBC 4.6 asks nothing of them under any reading: no lanes are
    judged for them, and the report says so block by block."""
    assert "Fire access: T2" in _names(fixture("rectangle").report(), Family.FIRE)
    low = with_low_bands(all_low(fixture("rectangle"), floors=4)).edited(_no_cellar).report()
    assert not [n for n in _names(low, Family.FIRE) if n.startswith("Fire access: T")]
    assert status(low, "Fire access") is Z.INFO
    c = check(low, BELOW)
    assert c.family is Family.FIRE and BELOW in low.not_checked
    assert c.finding.measured == "T1: not held to 4.6; T2: not held to 4.6; T3: not held to 4.6"


def test_a_low_block_over_the_cellar_is_a_special_building_held_to_nbc_4_6():
    """NBC 2016 Part 3 4.6 is for 'high rise buildings and special buildings'; Part 4 1.2(b)(6)
    makes a special building of one with a basement of more than 500 m², at any height; rule
    15(a)(i) brings it to a block below 21 m (read as law). The fixture's one cellar level runs
    under every block, so each 12 m block is held to the lanes and the corner turns."""
    low = with_low_bands(all_low(fixture("rectangle"), floors=4)).report()
    for name in ("T1", "T2", "T3"):
        c = check(low, f"Fire access: {name}")
        assert c.finding.status is Z.PASS  # the fixture gives every block its lanes
        assert "a special building (NBC Part 4 1.2(b)(6))" in c.finding.note
        assert "1.2(b)(6)" in c.finding.clause and "15(a)(i)" in c.finding.clause
    measured = check(low, BELOW).finding.measured
    assert "T2: a special building over the cellar, held to 4.6" in measured


def test_what_the_rest_of_the_code_asks_below_21_m_is_not_checked_and_says_why():
    """Rule 15(a)(i) keeps the National Building Code's requirements other than heights and
    setbacks. 4.6's access is judged block by block and 4.3.2.2's pathway with the roads; the rest
    of the Code (exits, the fire protection inside a block) is not on a site plan: NOT_CHECKED,
    listed beside the verdict, naming the rule."""
    report = with_low_bands(all_low(fixture("rectangle"))).report()
    c = check(report, BELOW)
    assert c.finding.status is Z.NOT_CHECKED and BELOW in report.not_checked
    assert "rule 15(a)(i), p.20" in c.finding.note and RULE_15_A_I in c.finding.note
    assert "1.2(b)(6)" in c.finding.note and "4.3.2.2" in c.finding.note
    assert "not shown on a site plan" in c.finding.note
    assert "other than heights and setbacks" in c.finding.required


def test_a_low_blocks_fire_access_never_fails_a_block_for_a_lane_it_is_not_held_to():
    """A 15 m block over no cellar is held to 4.6 only under the nbc_line reading: something
    standing in its lane fails it there and under no other reading, so it is UNVERIFIED, never
    FAIL, and so is every site-wide fire check that holds only where it is held."""
    report = with_low_bands(all_low(fixture("rectangle"))).edited(
        lambda c: (_no_cellar(c), _cabin_beside_t3(c))).report()
    fire = {c.finding.rule: c.finding.status for c in report.legal if c.family is Family.FIRE}
    assert Z.FAIL not in fire.values()
    t3 = check(report, "Fire access: T3")
    assert t3.finding.status is Z.UNVERIFIED
    assert t3.by_reading[NBC_FIRE_HEIGHT] == {"state_line": Z.PASS, "nbc_line": Z.FAIL}
    assert "NBC's own 15 m line" in t3.finding.note


def test_in_a_mixed_layout_the_high_rise_fire_checks_are_unchanged_and_the_low_block_is_named():
    shut = flat(fixture("rectangle"), T3=5)
    for inputs in (shut, with_low_bands(shut)):
        report = inputs.report()
        assert "T3: a special building over the cellar" in check(report, BELOW).finding.measured
        assert check(report, "Fire access: T3").finding.status is Z.PASS
        for rule in ("Fire access: T1", "Fire access: T2"):
            assert check(report, rule) == check(fixture("rectangle").report(), rule), rule
    report = with_low_bands(shut).edited(_no_cellar).report()  # 15 m: NBC's own line only
    assert "T3: 15 m, held to 4.6 under the nbc_line reading only" in (
        check(report, BELOW).finding.measured)


def test_a_block_that_is_low_only_under_one_reading_of_the_stilt_says_which():
    """6 floors on a 3 m stilt: 21 m if the stilt counts (a high-rise), 18 m if not (below), over
    the cellar either way: held to the lanes under every reading."""
    report = with_low_bands(floors_of(fixture("rectangle"), T3=6)).report()
    c = check(report, BELOW)
    assert "T3 (only if the stilt is not_counted)" in c.finding.measured
    t3 = check(report, "Fire access: T3")
    assert t3.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.PASS, NOT_COUNTED: Z.PASS}
    assert "special building" in t3.finding.note and "15(b)(iv)" in t3.finding.clause


def test_a_low_block_standing_on_a_road_still_takes_the_road_from_its_width():
    """Not being held to the fire lanes does not let a block stand on an internal road: the road
    is measured on the ground left to it, so rule 8(m) fails it, as for any block."""
    inputs = with_low_bands(all_low(fixture("rectangle"))).edited(
        lambda c: move_tower(c, "T2", -3.0, 0.0))  # onto the loop road's west arm
    report = inputs.report()
    c = check(report, "Internal roads: loop and other roads")
    assert c.finding.status is Z.FAIL and "narrower than 9 m" in c.finding.measured
    assert status(report, "Every square metre once") is Z.FAIL


def test_the_fire_statement_is_absent_where_no_block_is_below_21_m():
    names = {c.finding.rule for c in fixture("rectangle").report().legal}
    assert BELOW not in names and "Fire access: T1" in names
