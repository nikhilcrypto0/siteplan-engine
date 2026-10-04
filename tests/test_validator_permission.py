"""Whether the heights of a block's band may stand on this site at all (contracts 1.2:
`Band.permission` and `HeightRules.band_permission`).

A band the tables do not permit here is a band of its own, so a block in it fails on that alone,
naming the reason; one in a band whose permission is not settled is UNVERIFIED. A prohibited
high-rise (eligibility) fails only blocks of 21 m or more and permits nothing below: a block below
it is judged on its own band's permission.

Every band is MADE UP (tests/validator_low_helpers.py); no figure is a value of the order.
"""

from validator_helpers import check, fixture, move_tower, status
from validator_low_helpers import (
    LOW_A,
    LOW_B,
    all_low,
    flat_block,
    floors_of,
    low_band,
    with_bands_below,
    with_low_bands,
)

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.resolved_rules import BandKind, Eligibility

TEST_CLASS = "normative"
Z = Status
NOTE = "made up: a plot this size may take nothing above 18 m"
PERMITTED = "Height permitted: T2"


def _bands(permission, *, status=Provenance.ASSUMED_FOR_TEST):
    """A made-up band above 18 m the site may not take (no figures to hold a block to, as a
    stretch the tables leave out has none), or may take only once something is confirmed."""
    above_18 = low_band(18, 21, setback=None, road=None, up_to_inclusive=False,
                        permission=permission, note=NOTE, status=status)
    return (LOW_A, LOW_B, above_18)


def _t2_at(metres, floors=5):
    """T2 with no stilt and floors of the height that gives `metres` above the stilt."""
    return lambda inputs: flat_block(inputs, "T2", floors, metres / floors)


def _prohibited(inputs):
    def edit(rules):
        high_rise = rules.height.high_rise
        next(g for g in high_rise.grounds if g.id == "road_width").met = False
        high_rise.eligibility = type(high_rise).of_grounds(high_rise.grounds)
    return inputs.with_rules(edit)


def test_a_block_in_a_band_the_site_may_not_take_fails_and_names_why():
    inputs = _t2_at(19.0)(with_bands_below(all_low(fixture("rectangle")),
                                           _bands(Eligibility.PROHIBITED)))
    c = check(inputs.report(), PERMITTED)
    assert c.finding.status is Z.FAIL
    assert NOTE in c.finding.measured and "prohibited" in c.finding.measured
    assert "MADE-UP" in c.finding.clause


def test_a_band_with_no_figures_leaves_its_other_checks_not_checked_and_says_why():
    """A stretch the site may not take has no setback or road to hold a block to: those checks
    are NOT_CHECKED, saying the band gives none (and why), not that Table III is unmodelled."""
    inputs = _t2_at(19.0)(with_bands_below(all_low(fixture("rectangle")),
                                           _bands(Eligibility.PROHIBITED)))
    report = inputs.report()
    setback = check(report, "All-round setback: T2")
    assert setback.finding.status is Z.NOT_CHECKED
    assert "gives no setback to hold the block to" in setback.finding.note
    assert NOTE in setback.finding.note
    assert "not modelled yet" not in setback.finding.note
    assert status(report, "All-round setback: T1") is Z.PASS  # the other blocks are judged


def test_a_block_in_a_band_whose_permission_is_not_settled_is_unverified():
    inputs = _t2_at(19.0)(with_bands_below(all_low(fixture("rectangle")),
                                           _bands(Eligibility.UNVERIFIED)))
    c = check(inputs.report(), PERMITTED)
    assert c.finding.status is Z.UNVERIFIED and NOTE in c.finding.measured


def test_a_block_in_a_band_the_site_may_take_passes_its_permission():
    c = check(with_low_bands(all_low(fixture("rectangle"))).report(), "Height permitted: T1")
    assert c.finding.status is Z.PASS and "allowed" in c.finding.measured


def test_a_band_the_rules_mark_unverified_settles_nothing_even_when_it_allows_the_height():
    unsure = (low_band(0, 12, setback=2.3, road=0.0, status=Provenance.UNVERIFIED),
              low_band(12, 18, setback=3.7, road=8.4, status=Provenance.UNVERIFIED),
              low_band(18, 21, setback=4.9, road=11.6, up_to_inclusive=False,
                       status=Provenance.UNVERIFIED))
    report = with_bands_below(all_low(fixture("rectangle")), unsure).report()
    assert status(report, "Height permitted: T1") is Z.UNVERIFIED


def test_a_band_the_rules_do_not_model_asks_nothing_of_the_site():
    names = {c.finding.rule for c in all_low(fixture("rectangle")).report().legal}
    assert not [n for n in names if n.startswith("Height permitted")]  # as shipped: said elsewhere


def test_a_layout_of_high_rise_blocks_makes_no_permission_check():
    names = {c.finding.rule for c in with_low_bands(fixture("rectangle")).report().legal}
    assert not [n for n in names if n.startswith("Height permitted")]


def test_a_prohibited_high_rise_permits_nothing_lower_and_fails_nothing_lower():
    """On a site that may take no high-rise a block below 21 m is held to its own band's
    permission alone: allowed, it passes; in a band the tables do not permit, it fails on that."""
    base = _prohibited(with_low_bands(all_low(fixture("rectangle"))))
    assert status(base.report(), "Height permitted: T1") is Z.PASS
    barred = _prohibited(_t2_at(19.0)(with_bands_below(all_low(fixture("rectangle")),
                                                       _bands(Eligibility.PROHIBITED))))
    report = barred.report()
    assert status(report, PERMITTED) is Z.FAIL  # its own band, not the prohibition
    assert status(report, "Height permitted: T1") is Z.PASS
    assert "High-rise eligibility" not in {c.finding.rule for c in report.legal}


def test_a_high_rise_band_that_is_itself_not_permitted_fails_a_block_in_it():
    """A band of Table IV may carry its own permission too; the site's eligibility, with its
    grounds, stays the high-rise eligibility check's."""
    def bar_24_to_27(rules):
        band = next(b for b in rules.height.bands
                    if b.kind is BandKind.HIGH_RISE and b.above_m == 24.0)
        band.permission, band.permission_note = Eligibility.PROHIBITED, "made up: no 24-27 m here"
    report = fixture("rectangle").with_rules(bar_24_to_27).report()
    c = check(report, "Height permitted: T1")  # 27 m with the stilt counted, 24 m without
    assert c.by_reading["stilt_in_rule_height"]["counted"] is Z.FAIL
    assert c.by_reading["stilt_in_rule_height"]["not_counted"] is Z.PASS
    assert status(report, "High-rise eligibility") is Z.PASS


def test_a_block_that_is_high_rise_only_if_the_stilt_counts_takes_the_sites_eligibility_too():
    """6 floors on a 3 m stilt: a high-rise (21 m) if the stilt counts, band B if not. On a site
    that may take no high-rise, `band_permission` fails the first reading and passes the second."""
    inputs = _prohibited(with_low_bands(floors_of(fixture("rectangle"), T2=6)))
    c = check(inputs.report(), PERMITTED)
    assert c.by_reading["stilt_in_rule_height"] == {"counted": Z.FAIL, "not_counted": Z.PASS}
    assert c.finding.status is Z.UNVERIFIED
    assert "high-rise eligibility is PROHIBITED" in c.finding.measured


def test_the_permission_does_not_change_where_the_block_stands():
    """A block in a prohibited band fails on that alone: moving it changes no permission."""
    barred = _t2_at(19.0)(with_bands_below(all_low(fixture("rectangle")),
                                           _bands(Eligibility.PROHIBITED)))
    moved = barred.edited(lambda c: move_tower(c, "T2", 0.0, 1.0))
    assert check(barred.report(), PERMITTED).finding == check(moved.report(), PERMITTED).finding
