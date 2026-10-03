"""Bays and ramps as shapes, not as bounding boxes, and the ground whose setback is not known:
each case is a layout a review drew that the first version of the validator counted as parking."""

from shapely.geometry import Polygon, box
from validator_helpers import check, fixture, rectangle, select, set_floors, shape, status

from siteplan.contracts.candidate import Cellars
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT

TEST_CLASS = "normative"
Z = Status
BAYS = "Surface parking bays"
RAMP = "Cellar ramp"
CELLAR_SETBACK = "Cellar setback"


def _bays_on_open_land(*bays):
    def edit(candidate):
        candidate.circulation.roads = []
        candidate.circulation.fire_hardstanding = []
        candidate.program.open_space = []
        candidate.program.bays = [shape(b) for b in bays]
    return edit


def _ramps(*boxes):
    def edit(candidate):
        candidate.program.ramps = [rectangle(*b) for b in boxes]
    return edit


# --- a bay is a rectangle a car fits in --------------------------------------------------------


def test_a_bay_drawn_as_a_hollow_frame_or_a_triangle_is_not_a_bay():
    """Frames with 0.05 m walls were counted as bays of 12.5 m²: the box round them was the size."""
    frame = box(70.0, 12.0, 72.5, 17.0).difference(box(70.05, 12.05, 72.45, 16.95))
    triangle = Polygon([(76.0, 12.0), (83.0, 12.0), (76.0, 16.0)])
    for bad in (frame, triangle):
        c = check(fixture("rectangle").edited(_bays_on_open_land(bad)).report(), BAYS)
        assert c.finding.status is Z.FAIL
        assert "not a rectangle a car fits in" in c.finding.measured


def test_a_proper_bay_is_still_a_bay():
    inputs = fixture("rectangle").edited(_bays_on_open_land(box(70.0, 12.0, 72.5, 17.0)))
    assert status(inputs.report(), BAYS) is Z.PASS


# --- ramps -------------------------------------------------------------------------------------


def test_one_ramp_drawn_twice_is_one_ramp_not_two():
    one = (127.7, 62.87, 131.3, 86.86)  # 3.6 m wide: needs a partner to count
    report = fixture("rectangle").edited(_ramps(one, one)).report()
    c = check(report, RAMP)
    assert c.finding.status is Z.FAIL and "width 3.6" in c.finding.measured


def test_a_ramp_that_narrows_to_a_point_is_not_5_4_m_wide():
    def taper(candidate):
        candidate.program.ramps = [shape(Polygon([(127.7, 62.87), (133.1, 62.87), (130.4, 86.86)]))]
    c = check(fixture("rectangle").edited(taper).report(), RAMP)
    assert c.finding.status is Z.FAIL and "width" in c.finding.measured


def test_a_ramp_that_does_not_reach_the_cellar_leads_nowhere():
    def small_cellar(candidate):
        candidate.program.cellars = Cellars(levels=1, outline=[shape(box(20.0, 20.0, 80.0, 50.0))])
    c = check(fixture("rectangle").edited(small_cellar).report(), RAMP)
    assert c.finding.status is Z.FAIL and "does not reach the cellar" in c.finding.measured


def test_a_ramp_in_the_front_setback_of_a_plot_reached_from_a_diagonal_side_fails():
    """Reached from the north-east the front is the north and the east: with no front found a
    ramp in the east setback passed."""
    def tall_with_east_and_west_ramps(inputs):
        tall = inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, "counted"))
        tall = tall.edited(lambda c: set_floors(c, "T1", 11))
        return tall.edited(_ramps((0.2, 40.0, 3.8, 63.99), (146.2, 40.0, 149.8, 63.99)))
    south = tall_with_east_and_west_ramps(fixture("rectangle"))
    assert status(south.report(), RAMP) is Z.PASS

    def north_east(site):
        site.access.side.value = "NE"
    c = check(south.with_site(north_east).report(), RAMP)
    assert c.finding.status is Z.FAIL and "setback" in c.finding.measured


# --- the setback not known ---------------------------------------------------------------------


def _low_rise(candidate):
    for t in candidate.towers:
        set_floors(candidate, t.name, 4)  # 15 m: under the high-rise threshold, Table III's


def test_where_the_setback_is_not_known_bays_and_ramps_cannot_be_passed():
    """Below 21 m Table III sets the setback and it is not modelled: a ramp 0.5 m inside the front
    boundary was 'clear of the setbacks', and the bays were counted wherever they stood."""
    report = fixture("rectangle").edited(_low_rise).report()
    assert status(report, BAYS) is Z.UNVERIFIED
    assert "setback is not known" in check(report, BAYS).finding.note
    assert status(report, RAMP) is Z.UNVERIFIED


# --- cellars -----------------------------------------------------------------------------------


def test_a_cellar_wholly_off_the_plot_has_no_setback_to_keep_and_fails():
    def off(candidate):
        candidate.program.cellars = Cellars(
            levels=1, outline=[shape(box(200.0, 200.0, 260.0, 260.0))])
    c = check(fixture("rectangle").edited(off).report(), CELLAR_SETBACK)
    assert c.finding.status is Z.FAIL and "0.00 m" in c.finding.measured
