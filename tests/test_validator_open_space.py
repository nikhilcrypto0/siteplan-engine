"""Organised open space: what counts, and the area it is a share of, under every reading."""

import pytest
from validator_cases import inputs_of, made_up_case
from validator_helpers import (
    check,
    fixture,
    rectangle,
    status,
)

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    MIXED_HEIGHT_SPACING,
    OPEN_SPACE_BASIS,
    STILT_IN_RULE_HEIGHT,
)

TEST_CLASS = "normative"
Z = Status
RULE = "Organized open space (tot-lot)"
SOUTH_STRIP = (11.01, 11.01, 138.99, 22.83)  # the rectangle fixture's big pocket


def _counting(report, stilt="counted"):
    return report.recomputed.quantities[f"open_space_counting_sqm[{STILT_IN_RULE_HEIGHT}={stilt}]"]


def _with_pockets(*boxes):
    def edit(candidate):
        candidate.program.open_space = [rectangle(*b) for b in boxes]
    return edit


def test_the_fixture_meets_the_share_under_every_denominator():
    c = check(fixture("rectangle").report(), RULE)
    assert c.finding.status is Z.PASS
    assert set(c.by_reading[OPEN_SPACE_BASIS]) == {"gross_before_surrender",
                                                    "gross_after_surrender",
                                                    "net_after_surrender"}
    assert set(c.by_reading[OPEN_SPACE_BASIS].values()) == {Z.PASS}


def test_open_space_that_meets_the_net_area_but_not_the_gross_is_unverified_naming_the_basis():
    """10.13% of the net area (15,000 m²), 9.84% of the gross before surrender (15,450 m²)."""
    inputs = fixture("rectangle").edited(_with_pockets((11.01, 11.01, 138.99, 22.83),
                                                       (93.24, 82.95, 104.56, 88.99)))
    # trim the big pocket until 1,520 m² are drawn: between 1,500 and 1,545
    def trim(candidate):
        small = candidate.program.open_space[1].area_sqm
        width = (1520.0 - small) / (22.83 - 11.01)
        candidate.program.open_space[0] = rectangle(11.01, 11.01, 11.01 + width, 22.83)
    c = check(inputs.edited(trim).report(), RULE)
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[OPEN_SPACE_BASIS] == {"gross_before_surrender": Z.FAIL,
                                              "gross_after_surrender": Z.PASS,
                                              "net_after_surrender": Z.PASS}
    assert OPEN_SPACE_BASIS in c.finding.note


def test_open_space_below_every_denominator_fails():
    inputs = fixture("rectangle").edited(_with_pockets((11.01, 11.01, 100.0, 22.83)))
    c = check(inputs.report(), RULE)
    assert c.finding.status is Z.FAIL
    assert set(c.by_reading[OPEN_SPACE_BASIS].values()) == {Z.FAIL}


def test_a_pocket_narrower_than_3_m_or_smaller_than_50_m2_does_not_count():
    base = fixture("rectangle").report()
    inputs = fixture("rectangle").edited(
        lambda c: c.program.open_space.extend([rectangle(11.5, 24.0, 52.0, 26.5),  # 2.5 m wide
                                               rectangle(120.0, 24.0, 126.0, 30.0)]))  # 36 m²
    report = inputs.report()
    assert _counting(report) == pytest.approx(_counting(base), abs=0.01)
    assert report.recomputed.quantities["open_space_declared_sqm"] > _counting(base) + 100
    assert status(report, "Open-space pocket 3") is Z.INFO
    assert "narrower than 3 m" in check(report, "Open-space pocket 3").finding.measured
    assert "under 50" in check(report, "Open-space pocket 4").finding.measured


def test_ground_in_the_setback_does_not_count_and_how_much_depends_on_the_stilt_reading():
    """One clean pocket drawn right out to the west boundary, on land cleared of roads so that
    only the setback is in question: what lies within 9 m (stilt counted) or 8 m (not counted)
    of the boundary does not count."""
    def clear(candidate):
        candidate.circulation.roads, candidate.circulation.fire_hardstanding = [], []
        candidate.program.open_space = [rectangle(0.2, 11.01, 138.99, 22.83)]
    q = fixture("rectangle").edited(clear).report().recomputed.quantities
    height = 22.83 - 11.01
    assert q[f"open_space_counting_sqm[{STILT_IN_RULE_HEIGHT}=counted]"] == pytest.approx(
        (138.99 - 9.0) * height, abs=0.1)
    assert q[f"open_space_counting_sqm[{STILT_IN_RULE_HEIGHT}=not_counted]"] == pytest.approx(
        (138.99 - 8.0) * height, abs=0.1)


def test_the_gap_between_two_blocks_does_not_count_as_open_space():
    base = fixture("rectangle").report()
    between = rectangle(84.0, 35.0, 91.0, 50.0)  # T2 ends at x 83.01 and T3 starts at 92.03
    inputs = fixture("rectangle").edited(lambda c: c.program.open_space.append(between))
    assert _counting(inputs.report()) == pytest.approx(_counting(base), abs=0.01)


def test_the_tenders_clear_ground_round_a_high_rise_does_not_count():
    base = fixture("rectangle").report()
    beside = rectangle(2.0, 40.0, 10.0, 48.0)  # within 6 m of T2's west face
    inputs = fixture("rectangle").edited(lambda c: c.program.open_space.append(beside))
    assert _counting(inputs.report()) == pytest.approx(_counting(base), abs=0.01)


def test_ground_under_a_road_does_not_count():
    base = fixture("rectangle").report()
    on_the_road = rectangle(60.0, 54.0, 90.0, 62.0)  # on the internal road
    inputs = fixture("rectangle").edited(lambda c: c.program.open_space.append(on_the_road))
    assert _counting(inputs.report()) == pytest.approx(_counting(base), abs=0.01)


def test_land_within_a_water_buffer_counts_only_where_the_rules_say_it_may():
    pocket = rectangle(68.0, 20.0, 82.0, 40.0)  # inside the nala's 9 m buffer: 280 m²

    def put_in_buffer(candidate):
        candidate.program.open_space.append(pocket)

    base = fixture("nala_plot")
    with_it = base.edited(put_in_buffer)
    assert _counting(with_it.report()) == pytest.approx(_counting(base.report()) + 280, abs=0.1)

    def forbid(rules):
        rules.open_space.buffer_may_count.value = False
    strict = with_it.with_rules(forbid).report()
    assert _counting(strict) == pytest.approx(_counting(base.report()), abs=0.1)


def test_the_area_asked_in_the_rules_is_held_against_the_ownership_figures():
    inputs = fixture("rectangle")
    assert not [c for c in inputs.report().legal if c.finding.rule.startswith(
        "Open-space area asked")]

    def skew(rules):
        rules.open_space.requirement_sqm_by_reading["net_after_surrender"] = 1000.0
    report = inputs.with_rules(skew).report()
    c = check(report, "Open-space area asked: rules and site agree")
    assert c.finding.status is Z.UNVERIFIED and "net_after_surrender" in c.finding.measured


def test_a_layout_with_no_open_space_fails_but_a_drawing_of_buildings_alone_is_unverified():
    full = fixture("rectangle").edited(lambda c: setattr(c.program, "open_space", []))
    assert status(full.report(), RULE) is Z.FAIL
    assert status(inputs_of(made_up_case()).report(), RULE) is Z.UNVERIFIED


def test_the_open_space_check_is_run_under_the_stilt_the_spacing_and_the_denominator():
    from siteplan.contracts.resolved_rules import ALL

    inputs = fixture("rectangle").with_rules(
        lambda r: setattr(r.interpretation(MIXED_HEIGHT_SPACING), "selected", ALL))
    c = check(inputs.report(), RULE)
    assert c.finding.status is Z.PASS
    assert set(c.by_reading) == {STILT_IN_RULE_HEIGHT, MIXED_HEIGHT_SPACING, OPEN_SPACE_BASIS}
