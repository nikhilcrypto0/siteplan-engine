"""The same site judged the same way across the pipeline (2026-10-13, the regulatory audit's
phase 4): the steps against the resolver and the validator (D11), one reading of which road width
Table IV reads (D9), exact thresholds and one tolerance (D12), and no layout offered outside a
study without its tot-lot. Made-up land throughout; every expected figure is worked by hand.
"""

import pytest
from shapely.geometry import LineString, box
from test_steps import HIGH_RISE, _inputs, _setbacks
from test_validator_height_inputs import _master_plan_road
from validator_helpers import check, fixture

from siteplan import rules
from siteplan.contracts.accounting import DeductionKind
from siteplan.contracts.candidate import SiteProgram
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import Eligibility, Interpretation
from siteplan.contracts.validation import DependsOn
from siteplan.legal.readings import interpretations
from siteplan.optimizer import guard
from siteplan.steps.setbacks import SideSetback, _green, _keeps_strip, below_high_rise

TEST_CLASS = "normative"
Z = Status


# --- D11: the planting strip and the 18 to 21 m band, as the resolver reads them ----------------


def _side(metres: float, line: LineString) -> SideSetback:
    return SideSetback(1, "south", line.length, (), metres, "made up", line)


def test_a_side_kept_at_exactly_9_m_keeps_the_strip_and_one_below_does_not():
    """Rule 7(a)(viii) as G.O.Ms.No.7 of 2016 substituted it: 'where the setback is 9m and above',
    the threshold the resolver carries."""
    line = LineString([(0, 0), (100, 0)])
    assert rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M == 9.0
    assert _keeps_strip(_side(9.0, line)) and not _keeps_strip(_side(8.99, line))


def test_the_strip_runs_only_along_the_sides_that_keep_9_m():
    """A 100 m square kept at 9 m on its south and north sides and 8.99 m on the others: the
    strip is two 100 x 2 m bands, 400 m²."""
    net = box(0, 0, 100, 100)
    sides = [_side(9.0, LineString([(0, 0), (100, 0)])),
             _side(8.99, LineString([(100, 0), (100, 100)])),
             _side(9.0, LineString([(100, 100), (0, 100)])),
             _side(8.99, LineString([(0, 100), (0, 0)]))]
    assert _green(net, sides).area == pytest.approx(400.0)
    assert _green(net, [_side(8.99, s.line) for s in sides]) is None


def test_the_steps_read_a_height_of_18_to_21_m_as_the_resolver_does(tmp_path):
    """On the made-up 120 x 90 m plot (over 2,000 m², a 60 ft road): Stilt + 7 at 2.9 m storeys
    is 20.3 m without the stilt, between Table III's top and the 21 m high-rise line, where no
    order read gives a setback; Stilt + 6, 17.4 m, has Table III's."""
    s = _setbacks(_inputs(tmp_path, **HIGH_RISE))
    seven = below_high_rise(s, 7)
    assert seven is not None and seven.side_m is None
    assert seven.permission is Eligibility.UNVERIFIED
    assert "no order read gives a setback" in seven.note
    six = below_high_rise(s, 6)
    assert six is not None and six.side_m is not None and six.permission is Eligibility.ALLOWED
    assert below_high_rise(s, 8) is None  # 23.2 m: a high-rise, Table IV's


# --- D9: one reading of which width Table IV reads ----------------------------------------------


def _with_the_width_reading(rules_):
    reading = next(r for r in interpretations(master_plan_road=True)
                   if r["id"] == "table_iv_road_width")
    rules_.interpretations.append(Interpretation.model_validate(reading))


def test_a_master_plan_road_is_judged_both_ways_where_the_rules_carry_the_reading():
    """A 10 m road the master plan widens to 18.29 m, the strip surrendered: the made-up 27 m
    blocks need Table IV's 18 m road, which only the master-plan width gives."""
    inputs = fixture("rectangle").with_site(
        _master_plan_road(10.0, 18.29, DeductionKind.SURRENDER)).with_rules(
        _with_the_width_reading)
    c = check(inputs.report(), "Abutting road width (for T1)")
    assert c.by_reading["table_iv_road_width"] == {"existing": Z.FAIL, "master_plan": Z.PASS}
    assert c.finding.status is Z.CONDITIONAL
    assert any(d.kind is DependsOn.READING and d.id == "table_iv_road_width"
               for d in c.rests_on)


def test_without_the_reading_the_master_plans_width_counts_once_surrendered_as_before():
    inputs = fixture("rectangle").with_site(
        _master_plan_road(10.0, 18.29, DeductionKind.SURRENDER))
    assert check(inputs.report(), "Abutting road width (for T1)").finding.status is Z.PASS


# --- D12: the 18 m approach maximum -------------------------------------------------------------


def test_a_main_approach_road_wider_than_the_range_rule_8m_names_is_not_passed():
    """Rule 8(m) gives a main approach road 9 to 18 m. The made-up approach measures 9.04 m:
    within 9 to 18 m it is not over the range; held to a range of 5 to 8 m it is, and the result
    names the gap (the order does not say whether a wider road is allowed), never a PASS."""
    def approach(row):
        return lambda r: setattr(r.circulation.approach_m, "value", row)
    within = check(fixture("rectangle").report(), "Internal roads: main approach")
    assert not any(d.kind is DependsOn.RULE_GAP for d in within.rests_on)
    over = check(fixture("rectangle").with_rules(approach((5.0, 8.0))).report(),
                 "Internal roads: main approach")
    assert over.finding.status is Z.CONDITIONAL
    assert any(d.kind is DependsOn.RULE_GAP for d in over.rests_on)
    assert "5 to 8 m" in over.finding.required


# --- a layout offered outside a study lays its tot-lot ------------------------------------------


def _buildings_only(candidate):
    candidate.circulation = type(candidate.circulation)()
    candidate.program = SiteProgram()


def test_a_layout_without_its_tot_lot_is_offered_only_as_a_study():
    inputs = fixture("rectangle").edited(_buildings_only)
    report = inputs.report()
    refs = (report.site_ref, report.rules_ref, report.brief_ref)
    tot_lot = check(report, guard.STUDY_NOT_LAID)
    assert tot_lot.finding.status is not Z.PASS  # nothing is drawn where 10% is asked
    assert guard.tot_lot_missing(inputs.candidate, report)
    assert guard.TOT_LOT_MISSING in guard.why_refused(inputs.candidate, report, refs)
    assert guard.TOT_LOT_MISSING not in guard.why_refused(inputs.candidate, report, refs,
                                                          study=True)


def test_a_layout_with_its_tot_lot_is_never_refused_for_it():
    inputs = fixture("rectangle")
    report = inputs.report()
    assert not guard.tot_lot_missing(inputs.candidate, report)


# --- D12: rule 2(c)'s 4,000 m², exactly ---------------------------------------------------------


@pytest.mark.parametrize(("site_sqm", "group"), [(4_000.0, True), (3_999.9, False)])
def test_a_site_of_exactly_4000_m2_is_a_group_development_scheme(site_sqm, group):
    """Rule 2(c): residential development 'on a site of 4,000 m² and above'."""
    from legal_fixtures import make_site
    from shapely.geometry import box as square

    from siteplan.legal.resolve import resolve

    assert rules.is_group_development(site_sqm) is group
    side = site_sqm ** 0.5
    resolved = resolve(make_site(square(0, 0, side, side)))
    assert resolved.category.group_development.value is group
