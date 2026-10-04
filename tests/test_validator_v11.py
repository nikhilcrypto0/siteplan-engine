"""Contracts 1.1 in the validator: high-rise eligibility, the open-space width test kept to the
ground it is given, design targets beside the verdict, and the distance from electricity lines.
Made-up land only."""

from shapely.geometry import Polygon, box
from validator_helpers import check, fixture, set_floors, status

from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import DesignMargins
from siteplan.contracts.resolved_rules import Eligibility
from siteplan.contracts.site_model import Feature
from siteplan.contracts.validation import TargetItem
from siteplan.validator.shapes import OPENING_SLACK_M, mitred, opening

TEST_CLASS = "normative"
Z = Status
ELIGIBILITY = "High-rise eligibility"


def _road_ground(met: bool | None):
    def edit(rules):
        high_rise = rules.height.high_rise
        road = next(g for g in high_rise.grounds if g.id == "road_width")
        road.met = met
        high_rise.eligibility = type(high_rise).of_grounds(high_rise.grounds)
    return edit


def test_a_high_rise_where_the_site_may_take_none_fails_and_nothing_lower_passes():
    inputs = fixture("rectangle").with_rules(_road_ground(False))
    assert inputs.rules.height.high_rise.eligibility is Eligibility.PROHIBITED
    c = check(inputs.report(), ELIGIBILITY)
    assert c.finding.status is Z.FAIL and "road_width" in c.finding.measured
    low = inputs.edited(lambda c: [set_floors(c, t.name, 4) for t in c.towers])  # 15 m blocks
    report = low.report()
    assert ELIGIBILITY not in {x.finding.rule for x in report.legal}  # no high-rise to judge
    for tower in low.candidate.towers:  # Table III is not encoded: never a PASS
        assert status(report, f"All-round setback: {tower.name}") is Z.NOT_CHECKED


def test_an_unsettled_eligibility_leaves_a_high_rise_unverified():
    inputs = fixture("rectangle").with_rules(_road_ground(None))
    assert inputs.rules.height.high_rise.eligibility is Eligibility.UNVERIFIED
    assert status(inputs.report(), ELIGIBILITY) is Z.UNVERIFIED
    assert status(fixture("rectangle").report(), ELIGIBILITY) is Z.PASS


# A 40 x 30 m pocket crossed by two strips, as a pocket less a setback and a fire band becomes.
CROSSED = (box(0, 0, 40, 30)
           .difference(Polygon([(37.84, 40.18), (31.80, 40.58), (30.32, 18.29), (36.35, 17.88)]))
           .difference(Polygon([(36.37, 36.20), (29.79, 37.38), (21.33, -9.77), (27.91, -10.95)])))


def test_the_width_test_never_counts_ground_outside_the_pocket_it_is_given():
    """Found on a real layout: shrunk and grown back with square corners, ground reached past a
    corner the pocket cuts and was counted as open space (13 m² there). Here, 14 m² without the
    clip; none with it."""
    half = 3.0 / 2 - OPENING_SLACK_M
    assert mitred(mitred(CROSSED, -half), half).difference(CROSSED).area > 10.0  # the defect
    kept = opening(CROSSED, 3.0)
    assert kept.difference(CROSSED).area < 1e-9
    assert kept.area <= CROSSED.area + 1e-6


def test_every_pocket_counts_no_more_than_was_drawn():
    report = fixture("rectangle").report()
    c = check(report, "Organized open space (tot-lot)")
    counted, drawn = (float(part.split(" m²")[0].replace(",", ""))
                      for part in c.finding.measured.split(" counts of "))
    assert counted <= drawn


def _margins(**values):
    firm = {"status": "USER_CONFIRMED", "source_kind": "FIRM_STANDARD", "source": "made up"}

    def edit(brief):
        brief.design_margins = DesignMargins.model_validate(
            {name: {**firm, "value": value} for name, value in values.items()})
    return edit


def test_design_targets_sit_beside_the_verdict_with_the_legal_minimum_and_what_is_provided():
    report = fixture("rectangle").report()
    items = {row.item for row in report.design_targets}
    assert {TargetItem.SETBACK, TargetItem.TOWER_GAP, TargetItem.OPEN_SPACE,
            TargetItem.PARKING} <= items
    for row in report.design_targets:  # no margin set: the target is the legal minimum
        assert row.target == row.legal_minimum and row.basis.value == "ENGINE_DESIGN_ASSUMPTION"
    setback = next(r for r in report.design_targets if r.item is TargetItem.SETBACK)
    assert setback.provided >= setback.legal_minimum  # the fixture keeps its setbacks
    assert "Design margins" not in {c.finding.rule for c in report.program}


def test_a_missed_design_target_is_a_program_finding_and_never_moves_the_legal_verdict():
    plain = fixture("rectangle")
    margined = plain.with_brief(_margins(setback_extra_m=40.0))  # more than the plot can give
    report = margined.report()
    row = next(r for r in report.design_targets if r.item is TargetItem.SETBACK)
    assert row.target == row.legal_minimum + 40.0 and row.basis.value == "FIRM_STANDARD"
    assert not row.meets_target
    margin = check_program(report, "Design margins")
    assert margin.finding.status is Z.FAIL and "setback" in margin.finding.measured
    assert report.verdict.legal is plain.report().verdict.legal  # judged on the law alone
    kept = plain.with_brief(_margins(setback_extra_m=0.5)).report()
    assert check_program(kept, "Design margins").finding.status is Z.PASS


def check_program(report, rule):
    return next(c for c in report.program if c.finding.rule == rule)


def test_a_marked_electricity_line_is_said_never_passed():
    def mark(site):
        site.features = [Feature(kind="MARK", text="HT line: HT LINE 11KV, 5.0 m from the plot")]
    c = check(fixture("rectangle").with_site(mark).report(), "Distance from electricity lines")
    assert c.finding.status is Z.UNVERIFIED and "3 m" in c.finding.required
    assert "1.5 m" in c.finding.required and "3(c)(i)" in c.finding.clause
    names = {x.finding.rule for x in fixture("rectangle").report().legal}
    assert "Distance from electricity lines" not in names  # nothing marked, nothing said
