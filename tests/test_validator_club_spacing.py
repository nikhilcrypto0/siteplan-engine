"""Where the club house stands (rule 15(a)(x): a block of its own): its gap to each tower, its
setback, and the rule 8(o) land a large project sets aside, which nothing models and the report
must say so. Found by a review: a club house 7 m from a tower that Table IV keeps 8 to 9 m from
drew no check at all."""

from shapely import affinity
from validator_helpers import check, fixture, rectangle, select, shape, status

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import ALL, MIXED_HEIGHT_SPACING, STILT_IN_RULE_HEIGHT

TEST_CLASS = "normative"
Z = Status
GAP = "Club house gap to T1"


def _club_west_by(candidate, metres):
    club = candidate.program.club_house
    club.shape = shape(affinity.translate(club.shape.to_shapely(), -metres, 0.0))


def _spacing(reading):
    if reading == ALL:
        return lambda rules: setattr(rules.interpretation(MIXED_HEIGHT_SPACING), "selected", ALL)
    return lambda rules: select(rules, MIXED_HEIGHT_SPACING, reading)


def test_a_club_house_the_tables_gap_from_the_tower_keeps_it():
    inputs = fixture("rectangle").with_rules(_spacing("taller_governs"))
    assert status(inputs.report(), GAP) is Z.PASS  # 9.0 m from T1, which asks 9 m or 8 m


def test_a_club_house_closer_than_the_gap_fails_where_the_taller_block_governs():
    inputs = fixture("rectangle").with_rules(_spacing("taller_governs")).edited(
        lambda c: _club_west_by(c, 1.92))  # 7.10 m from T1
    c = check(inputs.report(), GAP)
    assert c.finding.status is Z.FAIL and "7.10 m" in c.finding.measured


def test_where_each_block_keeps_its_own_gap_a_club_house_between_the_halves_is_unverified():
    """The club house's own gap is Table III's, which is not modelled: only the tower's half is
    the least that can be asked, so 7.1 m between 4.5 and 9 m is not settled either way."""
    inputs = fixture("rectangle").with_rules(_spacing("each_own")).edited(
        lambda c: _club_west_by(c, 1.92))
    assert status(inputs.report(), GAP) is Z.UNVERIFIED


def test_a_club_house_closer_than_half_the_towers_gap_fails_under_every_reading():
    inputs = fixture("rectangle").with_rules(_spacing(ALL)).edited(
        lambda c: _club_west_by(c, 6.0))  # 3 m from T1
    c = check(inputs.report(), GAP)
    assert c.finding.status is Z.FAIL
    assert set(c.by_reading[MIXED_HEIGHT_SPACING].values()) == {Z.FAIL}


def test_the_stilt_reading_changes_the_gap_a_club_house_must_keep():
    """T1 is 27 m with its stilt and 24 m without: Table IV asks 9 m or 8 m of the club house,
    so 8.5 m passes only if the stilt is not counted."""
    inputs = fixture("rectangle").with_rules(_spacing("taller_governs")).edited(
        lambda c: _club_west_by(c, 0.52))  # 8.5 m from T1
    c = check(inputs.report(), GAP)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {"counted": Z.FAIL, "not_counted": Z.PASS}


def test_no_gap_is_asked_of_a_club_house_inside_a_residential_block():
    def inside(candidate):
        candidate.program.club_house.shape = shape(
            candidate.placed_footprint(candidate.towers[0]).buffer(-3.0))
    names = {c.finding.rule for c in fixture("rectangle").edited(inside).report().legal}
    assert not [n for n in names if n.startswith("Club house gap")]


def test_a_low_rise_club_houses_setback_is_said_to_be_not_modelled():
    c = check(fixture("rectangle").report(), "Club house: setback")
    assert c.finding.status is Z.NOT_CHECKED and "Table III" in c.finding.note


def test_a_club_house_as_tall_as_a_high_rise_keeps_the_setback_its_height_asks():
    def tall(candidate):
        candidate.program.club_house.floors = 8  # 24 m with the firm's 3 m floors

    def near_the_boundary(candidate):
        tall(candidate)
        club = candidate.program.club_house
        bounds = club.shape.to_shapely().bounds
        club.shape = shape(affinity.translate(club.shape.to_shapely(), 148.0 - bounds[2], 0.0))
    far = check(fixture("rectangle").edited(tall).report(), "Club house: setback")
    near = check(fixture("rectangle").edited(near_the_boundary).report(), "Club house: setback")
    assert far.finding.status is Z.UNVERIFIED and near.finding.status is Z.FAIL  # never a pass
    assert "fire access and spacing are not modelled" in far.finding.note


def test_a_club_house_of_a_tiny_footprint_and_dozens_of_floors_cannot_pass_the_3_percent():
    """30 m² over 38 floors is 1,140 m² of club house, 3% of what is built, and a 114 m block."""
    def tower(candidate):
        club = candidate.program.club_house
        club.floors = 38
        club.shape = rectangle(40.0, 5.0, 46.0, 10.0)
    c = check(fixture("rectangle").edited(tower).report(), "Amenities (club house)")
    assert c.finding.status is Z.UNVERIFIED and "cannot pass" in c.finding.note


def test_a_project_over_5_acres_says_rule_8o_is_not_modelled():
    def large(rules):
        rules.category.above_5_acres.value = True
    names = {c.finding.rule for c in fixture("rectangle").report().legal}
    assert "Large project: land set aside (rule 8(o))" not in names
    report = fixture("rectangle").with_rules(large).report()
    c = check(report, "Large project: land set aside (rule 8(o))")
    assert c.finding.status is Z.NOT_CHECKED and "5%" in c.finding.required
    assert "Large project: land set aside (rule 8(o))" in report.not_checked
