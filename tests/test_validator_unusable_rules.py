"""Rule values the contract admits that nothing can be measured with (a share of zero, a ramp of no
slope, a bay of no width, a cellar table with no row for large sites): the report says which, and
is not a pass. A review made each of them stop the validator with a division by zero."""

import pytest
from validator_helpers import fixture

from siteplan.contracts import ValidationReport
from siteplan.contracts.accounting import LayerKind
from siteplan.contracts.common import Status
from siteplan.contracts.validation import LegalVerdict

TEST_CLASS = "normative"
Z = Status


def _zero_share(rules):
    rules.open_space.share.value = 0.0


def _flat_ramp(rules):
    rules.parking.ramp_gradient.value = 0.0


def _bay_of_no_width(rules):
    rules.parking.measurement.bay_m = (0.0, 5.0)


def _bay_a_hair_wide(rules):
    rules.parking.measurement.bay_m = (1e-9, 5.0)


def _aisle_backwards(rules):
    rules.parking.measurement.aisle_m = -10.0


def _empty_cellar_table(rules):
    rules.parking.cellar_setback_by_site_sqm.value = []


@pytest.mark.parametrize("spoil, named", [
    (_zero_share, "open_space.share"), (_flat_ramp, "parking.ramp_gradient"),
    (_bay_of_no_width, "parking.measurement"), (_bay_a_hair_wide, "parking.measurement"),
    (_aisle_backwards, "parking.measurement"),
    (_empty_cellar_table, "cellar_setback_by_site_sqm")])
def test_a_rule_value_nothing_can_be_measured_with_is_named_and_never_a_pass(spoil, named):
    report = fixture("rectangle").with_rules(spoil).report()
    assert [c.finding.status for c in report.legal] == [Z.UNVERIFIED]
    assert report.legal[0].finding.rule == "Rules the validator can use"
    assert named in report.legal[0].finding.measured
    assert report.verdict.legal is LegalVerdict.UNVERIFIED
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


def test_usable_rules_are_not_questioned():
    names = {c.finding.rule for c in fixture("rectangle").report().legal}
    assert "Rules the validator can use" not in names


def _table_with_no_row_above(rules):
    rules.parking.cellar_setback_by_site_sqm.value = [(2000.0, 2.0)]  # 'and above' is missing


def test_a_cellar_table_with_no_row_for_a_large_site_is_unverified_for_that_site_only():
    """The table should end 'and above'. Without that row a site above its last size has no
    setback to hold the cellar to, which is said; the rest of the report keeps its verdicts."""
    from validator_helpers import check

    report = fixture("rectangle").with_rules(_table_with_no_row_above).report()  # 15,000 m²
    c = check(report, "Cellar setback")
    assert c.finding.status is Z.UNVERIFIED and "no row for a site of 15,000 m²" in (
        c.finding.measured)
    assert len(report.legal) > 5
    assert not [d for d in report.cross_checks if d.item == "cellar setback"]
    assert not report.accounting.rule_layers.of(LayerKind.CELLAR_SETBACK)

    def table_that_covers_the_site(rules):
        rules.parking.cellar_setback_by_site_sqm.value = [(20000.0, 2.0)]
    covered = fixture("rectangle").with_rules(table_that_covers_the_site).report()
    assert check(covered, "Cellar setback").finding.status is Z.PASS  # judged as ever
