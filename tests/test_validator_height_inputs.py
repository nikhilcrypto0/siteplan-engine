"""The inputs the height rules rest on: the road's width (the master plan's counts only if the
widening strip is surrendered) and the heights a prototype brings (a floor shorter than the firm's
lowers the building under every rule at once). Both found by a review that tried to pass a layout
it should not have."""

from validator_helpers import check, fixture, status

from siteplan.contracts.accounting import DeductionKind
from siteplan.contracts.common import Provenance, Status

TEST_CLASS = "normative"
Z = Status
ROAD = "Abutting road width (for T1)"
HEIGHTS = "Heights of the prototypes"


def _master_plan_road(legal, master, deduction):
    def edit(site):
        road = site.access_road()
        road.legal_row_m.value = legal
        road.master_plan_row_m = type(road.legal_row_m)(
            value=master, status=Provenance.USER_CONFIRMED, source_kind="ARCHITECT",
            source="made up")
        for d in site.ownership.deductions:
            d.kind = deduction
    return edit


def test_the_master_plans_width_counts_only_where_the_strip_is_surrendered():
    """A 10 m road with an 18.29 m master plan: the plot's height needs the wider road only if
    the owner gives up the land that widens it."""
    surrendered = fixture("rectangle").with_site(
        _master_plan_road(10.0, 18.29, DeductionKind.SURRENDER)).report()
    c = check(surrendered, ROAD)
    assert c.finding.status is Z.PASS and "18.29 m (master plan)" in c.finding.measured
    assert "is surrendered" in c.finding.note

    other = fixture("rectangle").with_site(
        _master_plan_road(10.0, 18.29, DeductionKind.TRANSFER)).report()
    c = check(other, ROAD)
    assert c.finding.status is Z.FAIL and "10.00 m (existing)" in c.finding.measured
    assert "18.29 m is not counted" in c.finding.note


def test_a_prototype_with_a_floor_shorter_than_the_firms_is_said_and_never_passed():
    """Eight floors of 0.5 m read as 4 m and dropped every high-rise rule without a word."""
    def squash(candidate):
        candidate.prototypes_used[0].heights.floor_to_floor_m = 0.5
    c = check(fixture("rectangle").edited(squash).report(), HEIGHTS)
    assert c.finding.status is Z.UNVERIFIED
    assert "floor 0.5 m against the firm's 3 m" in c.finding.measured and "T1" in c.finding.measured


def test_a_stilt_shorter_than_the_firms_is_said_too_unless_there_is_no_stilt():
    def short_stilt(candidate):
        candidate.prototypes_used[0].heights.stilt_height_m = 1.0
    assert status(fixture("rectangle").edited(short_stilt).report(), HEIGHTS) is Z.UNVERIFIED

    def no_stilt(candidate):
        short_stilt(candidate)
        candidate.towers[0].has_stilt = False
    names = {c.finding.rule for c in fixture("rectangle").edited(no_stilt).report().legal}
    assert HEIGHTS not in names


def test_heights_equal_to_or_above_the_firms_are_not_questioned():
    def taller(candidate):
        candidate.prototypes_used[0].heights.floor_to_floor_m = 3.2
        candidate.prototypes_used[0].heights.stilt_height_m = 3.0
    names = {c.finding.rule for c in fixture("rectangle").edited(taller).report().legal}
    assert HEIGHTS not in names
