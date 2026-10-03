"""The area the open space is a share of: where the rules and the site's ownership figures
disagree, the larger requirement is the one held to (the report says so), never the rules' figure
alone. Found by a review: rules asking 800 m² against a site asking 1,500 passed 953 m²."""

from validator_helpers import check, fixture, rectangle, status

from siteplan.contracts.common import Status

TEST_CLASS = "normative"
Z = Status
OPEN_SPACE = "Organized open space (tot-lot)"
AGREE = "Open-space area asked: rules and site agree"


def _understated_rules(rules):
    for reading in rules.open_space.requirement_sqm_by_reading:
        rules.open_space.requirement_sqm_by_reading[reading] = 800.0


def _small_tot_lot(candidate):
    candidate.program.open_space = [rectangle(11.0, 11.0, 86.0, 22.8)]  # 885 m²


def test_open_space_enough_for_the_rules_figure_but_not_the_sites_fails():
    inputs = fixture("rectangle").with_rules(_understated_rules).edited(_small_tot_lot)
    report = inputs.report()
    assert status(report, OPEN_SPACE) is Z.FAIL
    assert status(report, AGREE) is Z.UNVERIFIED  # and the disagreement itself is said


def test_the_requirement_shown_is_the_larger_one():
    inputs = fixture("rectangle").with_rules(_understated_rules).edited(_small_tot_lot)
    c = check(inputs.report(), OPEN_SPACE)
    assert "1,500.0 m²" in c.finding.required or "1,545.0 m²" in c.finding.required


def test_rules_and_site_that_agree_change_nothing():
    report = fixture("rectangle").report()
    assert status(report, OPEN_SPACE) is Z.PASS
    assert AGREE not in {c.finding.rule for c in report.legal}
