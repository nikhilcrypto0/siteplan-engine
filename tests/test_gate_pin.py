"""The entrance stays where the project pins it (2026-10-20, the architect's rule: the main road
is the main entrance, fixed, never changed; in the blind runs the gate had slid along the main
road's side): a layout whose gate opens anywhere else fails the program check, is refused by the
guard and is never offered; an answers file pins it as a project file does. Made-up land."""

from search_support import made_up, strategy
from shapely.geometry import LineString, Polygon, box
from validator_helpers import fixture

from siteplan.contracts import digest
from siteplan.contracts.common import Line, Provenance, Sourced, SourceKind, Status
from siteplan.geometry import line_runs
from siteplan.intake import build_project
from siteplan.legal.envelope import envelope
from siteplan.optimizer.guard import inputs_of, off_gate, why_refused
from siteplan.optimizer.search import network
from siteplan.project import Project
from siteplan.validator import validate
from siteplan.validator.program import GATE_CHECK

TEST_CLASS = "normative"
SOURCE = "the architect, 2026-10-20: the main road is the main entrance, fixed"
# the made-up rectangle (150 x 100 m) opens its gate on the south edge, 3 to 12 m along
PIN = [(2.0, 0.0), (13.0, 0.0)]
SLID = [(40.0, 0.0), (49.0, 0.0)]  # 28 m further along the same side, as the blind runs did


def _pinned(points):
    def edit(site):
        site.access.gate = Sourced[Line](value=Line(points=points),
                                         status=Provenance.USER_CONFIRMED,
                                         source_kind=SourceKind.ARCHITECT, source=SOURCE)
    return fixture("rectangle").with_site(edit)


def _gate_check(report):
    return next((c for c in report.program if c.finding.rule == GATE_CHECK), None)


def test_a_gate_on_the_pinned_stretch_meets_the_check():
    report = _pinned(PIN).report()
    check = _gate_check(report)
    assert check.finding.status is Status.PASS and SOURCE in check.finding.clause
    assert not off_gate(report)


def test_a_gate_that_slid_along_the_side_fails_and_is_never_offered():
    inputs = _pinned(SLID)
    report = inputs.report()
    check = _gate_check(report)
    assert check.finding.status is Status.FAIL
    assert "gate 1 opens at (8, 1)" in check.finding.measured
    reasons = why_refused(inputs.candidate, report, inputs_of(inputs.site, inputs.rules,
                                                              inputs.brief))
    assert off_gate(report) and set(off_gate(report)) <= set(reasons)
    assert not any(c.finding.rule == GATE_CHECK for c in report.legal)  # the architect's, not law


def test_a_site_that_pins_no_gate_is_judged_as_before():
    assert _gate_check(fixture("rectangle").report()) is None


def test_the_search_keeps_the_gate_where_it_is_pinned():
    """A made-up site pinning its gate on the south side, 60 to 75 m along: every layout the
    search offers opens its gate there."""
    made = made_up(box(0, 0, 200, 120))
    pin = [(60.0, 0.0), (75.0, 0.0)]
    site = made.site.model_copy(deep=True)
    site.access.gate = Sourced[Line](value=Line(points=pin), status=Provenance.USER_CONFIRMED,
                                     source_kind=SourceKind.ARCHITECT, source=SOURCE)
    rules = made.rules.model_copy(update={"site_ref": digest(site)})
    pinned = made.__class__(site, rules, made.brief, envelope(site, rules), made.kit)
    proposal = strategy().propose(pinned.context())
    assert proposal.candidates
    stretch = LineString(pin).buffer(0.5)
    for c in proposal.candidates:
        for gate in c.circulation.gates:
            assert gate.shape.to_shapely().centroid.distance(stretch) < 3.0, c.candidate_id
        report = validate(pinned.site, pinned.rules, pinned.brief, c, pinned.envelope)
        assert _gate_check(report).finding.status is Status.PASS


def test_a_gate_pinned_on_an_edge_drawn_with_a_slight_bend_still_opens_there():
    """Dhulapally's pinned mouth is 14 m of edge drawn as segments of 7.8, 6.1 and 0.3 m bending
    half a degree: gates were placed on single segments only, none 9 m long, so no approach was
    found and the search laid nothing. A straight run is read as the engine reads one anywhere."""
    bend = (67.5, 0.04)
    net = Polygon([(0, 0), bend, (200, 0), (200, 120), (0, 120)])
    pin = [(60.0, 0.04 * 60 / 67.5), bend, (75.0, 0.04 - 0.04 * 7.5 / 132.5)]
    assert network._gate_points(net, LineString(pin), 4.51)
    made = made_up(net)
    site = made.site.model_copy(deep=True)
    site.access.gate = Sourced[Line](value=Line(points=pin), status=Provenance.USER_CONFIRMED,
                                     source_kind=SourceKind.ARCHITECT, source=SOURCE)
    rules = made.rules.model_copy(update={"site_ref": digest(site)})
    pinned = made.__class__(site, rules, made.brief, envelope(site, rules), made.kit)
    proposal = strategy().propose(pinned.context())
    assert proposal.candidates
    for c in proposal.candidates:
        report = validate(pinned.site, pinned.rules, pinned.brief, c, pinned.envelope)
        assert _gate_check(report).finding.status is Status.PASS


def test_a_stretch_with_an_edge_a_gate_fits_keeps_its_places_on_the_edges():
    """Reading every stretch by its straight runs moved the places an unpinned search opened its
    approach at and cost Suchitra 16 flats (144 to 128, 2026-10-20): the runs are read only for
    a stretch none of whose edges takes a gate."""
    net = Polygon([(0, 0), (20, 0), (26, 0.05), (26, 30), (0, 30)])
    bent = LineString([(0, 0), (20, 0), (26, 0.05)])
    assert network._gate_points(net, bent, 4.51) == network._gate_points(
        net, LineString([(0, 0), (20, 0)]), 4.51)


def test_a_corner_is_never_read_as_one_straight_run():
    corner = LineString([(0, 0), (10, 0), (10, 10)])
    assert [round(r.length, 6) for r in line_runs(corner)] == [10.0, 10.0]
    assert network._gate_points(box(0, 0, 10, 10), corner, 4.51) == network._gate_points(
        box(0, 0, 10, 10), LineString([(0, 0), (10, 0)]), 4.51) + network._gate_points(
        box(0, 0, 10, 10), LineString([(10, 0), (10, 10)]), 4.51)


def test_an_answers_file_pins_the_gate_as_a_project_file_does():
    from test_intake import ANSWERS, _draft  # noqa: PLC0415

    project = Project.model_validate(build_project(_draft(), ANSWERS | {
        "gate_m": PIN, "_source": {"gate_m": SOURCE}}))
    assert project.site.gate_m == PIN
    assert project.status["gate_m"] is Provenance.USER_CONFIRMED
    assert project.sources["gate_m"] == SOURCE
    unpinned = Project.model_validate(build_project(_draft(), ANSWERS))
    assert unpinned.site.gate_m is None
