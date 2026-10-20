"""The entrance stays where the project pins it (2026-10-20, the architect's rule: the main road
is the main entrance, fixed, never changed; in the blind runs the gate had slid along the main
road's side): a layout whose gate opens anywhere else fails the program check, is refused by the
guard and is never offered; an answers file pins it as a project file does. Made-up land."""

from search_support import made_up, strategy
from shapely.geometry import LineString, box
from validator_helpers import fixture

from siteplan.contracts import digest
from siteplan.contracts.common import Line, Provenance, Sourced, SourceKind, Status
from siteplan.intake import build_project
from siteplan.legal.envelope import envelope
from siteplan.optimizer.guard import inputs_of, off_gate, why_refused
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


def test_an_answers_file_pins_the_gate_as_a_project_file_does():
    from test_intake import ANSWERS, _draft  # noqa: PLC0415

    project = Project.model_validate(build_project(_draft(), ANSWERS | {
        "gate_m": PIN, "_source": {"gate_m": SOURCE}}))
    assert project.site.gate_m == PIN
    assert project.status["gate_m"] is Provenance.USER_CONFIRMED
    assert project.sources["gate_m"] == SOURCE
    unpinned = Project.model_validate(build_project(_draft(), ANSWERS))
    assert unpinned.site.gate_m is None
