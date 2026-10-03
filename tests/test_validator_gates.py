"""Gates, each a way a layout once got in through a gate that was not one (found by a review that
tried to break the validator): the entrance is as wide as its opening, in the plot's boundary, on
the side the street runs, and only such a gate starts a lane or relaxes a rule."""

from validator_helpers import check, fixture, rectangle, status

from siteplan.contracts.common import Provenance, Status

TEST_CLASS = "normative"
Z = Status
ENTRANCE = "Fire access: entrance"
REACHED = "Fire access: reached from the entrance"


def _gate(candidate, x0, y0, x1, y1, declared=None):
    candidate.circulation.gates[0].shape = rectangle(x0, y0, x1, y1)
    if declared is not None:
        candidate.circulation.gates[0].width_m = declared


def test_a_gate_is_as_wide_as_its_opening_not_as_long_as_it_is_deep():
    """A gate drawn 1 m across and 12 m deep was 12 m wide to a measure of its longest side."""
    def deep(candidate):
        _gate(candidate, 6.0, 0.0, 7.0, 12.0, declared=1.0)
    c = check(fixture("rectangle").edited(deep).report(), ENTRANCE)
    assert c.finding.status is Z.FAIL and "1.00 m wide" in c.finding.measured


def test_a_gate_drawn_shallow_but_wide_enough_is_an_entrance():
    def shallow(candidate):
        _gate(candidate, 3.0, 0.0, 12.0, 0.5, declared=9.0)
    assert status(fixture("rectangle").edited(shallow).report(), ENTRANCE) is Z.PASS


def test_a_gate_on_a_side_the_street_does_not_run_on_is_not_the_entrance():
    """The rectangle's road runs on its south side; a gate in the north boundary leads nowhere."""
    def north(candidate):
        _gate(candidate, 60.0, 98.0, 69.0, 100.0, declared=9.0)
    c = check(fixture("rectangle").edited(north).report(), ENTRANCE)
    assert c.finding.status is Z.FAIL and "N side" in c.finding.measured
    assert "the road runs on S" in c.finding.measured


def test_with_no_street_side_known_the_side_of_a_gate_is_not_judged():
    def north(candidate):
        _gate(candidate, 60.0, 98.0, 69.0, 100.0, declared=9.0)

    def unknown(site):
        site.access.side.value, site.access.side.status = None, Provenance.UNVERIFIED
        for road in site.roads:
            road.side = None
    inputs = fixture("rectangle").with_site(unknown).edited(north)
    assert status(inputs.report(), ENTRANCE) is Z.PASS


def test_a_gate_drawn_inside_the_plot_is_no_way_in_and_starts_no_lane():
    """A 9 m 'gate' drawn on the loop road used to reach every block from nowhere."""
    def inside(candidate):
        fake = candidate.circulation.gates[0].model_copy(
            update={"shape": rectangle(60.0, 5.0, 69.0, 8.0)})
        candidate.circulation.gates = [fake]  # the real gate goes; the fake one stays
    report = fixture("rectangle").edited(inside).report()
    assert status(report, ENTRANCE) is Z.FAIL
    assert status(report, REACHED) is Z.FAIL


def test_every_gate_is_held_to_the_entrance_width_not_only_the_widest():
    def second(candidate):
        candidate.circulation.gates.append(candidate.circulation.gates[0].model_copy(
            update={"shape": rectangle(100.0, 0.0, 101.5, 2.0), "width_m": 1.5}))
    c = check(fixture("rectangle").edited(second).report(), ENTRANCE)
    assert c.finding.status is Z.FAIL and "gate 2 is 1.50 m wide" in c.finding.measured


def test_a_gate_wider_than_any_approach_road_is_doubtful_not_an_entrance_that_clears_the_strip():
    """A 'gate' 140 m wide deleted 140 m of the planted strip and passed as an entrance."""
    def gap(candidate):
        _gate(candidate, 5.0, 0.0, 145.0, 2.0, declared=140.0)
    c = check(fixture("rectangle").edited(gap).report(), ENTRANCE)
    assert c.finding.status is Z.UNVERIFIED and "more than the 18 m" in c.finding.measured
