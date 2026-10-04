"""Blocks below the high-rise height (21 m), judged on the band the rules give them: their
setback, the gap between blocks, the road their band asks, and what a prohibited high-rise does
and does not say of them.

Every band here is MADE UP (tests/validator_low_helpers.py): the validator's logic is tested
before A2 encodes the real Table III, and no figure below is a value of the order. A band the
rules do not model stays NOT_CHECKED, never PASS, and a band they mark UNVERIFIED settles nothing.

A low block here usually has no stilt (`flat`), so every reading of the stilt gives it one height;
test_table_iii_is_read_on_the_height_above_the_stilt_whatever_the_reading holds the stilt itself.
"""

import pytest
from validator_helpers import (
    check,
    fixture,
    move_tower,
    select,
    status,
)
from validator_low_helpers import (
    LOW_A,
    LOW_B,
    LOW_C,
    MADE_UP,
    access_road_of,
    all_low,
    changed_rules,
    flat,
    flat_block,
    floors_of,
    low_band,
    spacing_open,
    with_bands_below,
    with_low_bands,
)

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.resolved_rules import (
    MIXED_HEIGHT_SPACING,
    STILT_IN_RULE_HEIGHT,
    Eligibility,
)
from siteplan.contracts.validation import Family

TEST_CLASS = "normative"
Z = Status
COUNTED, NOT_COUNTED = "counted", "not_counted"
TALLER, EACH_OWN = "taller_governs", "each_own"
RULE_5_XIII = ('"The space between 2 blocks shall not be less than the side setback of the '
               'tallest block as mentioned in Table - III"')


def _counted(inputs):
    """Only the reading in which the stilt counts, for the high-rise blocks of a mixed layout."""
    return inputs.with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))


def _prohibited(inputs):
    def edit(rules):
        high_rise = rules.height.high_rise
        next(g for g in high_rise.grounds if g.id == "road_width").met = False
        high_rise.eligibility = type(high_rise).of_grounds(high_rise.grounds)
    return inputs.with_rules(edit)


def _t2_to_the_west(metres):
    """T2 moved west: it stood 11.01 m from the boundary."""
    return lambda candidate: move_tower(candidate, "T2", -metres, 0.0)


# --- a band that is not modelled stays NOT_CHECKED ---------------------------------------------


def test_a_block_in_a_band_the_rules_do_not_model_is_never_passed():
    report = all_low(fixture("rectangle")).report()  # the fixtures' band below 21 m: not modelled
    for rule in ("All-round setback: T1", "Gap between blocks: T1 / T2",
                 "Abutting road width (for T1)", "Club house: setback", "Club house gap to T1"):
        assert status(report, rule) is Z.NOT_CHECKED, rule
        assert rule in report.not_checked
    assert "Table III" in check(report, "All-round setback: T1").finding.note
    assert "Table III" in check(report, "All-round setback: T1").finding.required


def test_a_modelled_band_that_gives_no_setback_is_not_modelled_either():
    nothing = low_band(0, 12, setback=None, road=None)
    bands = (nothing, low_band(12, 18, setback=3.7, gap=4.3, road=8.4),
             low_band(18, 21, setback=4.9, gap=5.7, road=11.6, up_to_inclusive=False))
    report = with_bands_below(all_low(fixture("rectangle"), 3), bands).report()  # 9 m
    assert status(report, "All-round setback: T1") is Z.NOT_CHECKED


def test_each_block_is_judged_on_its_own_band_and_a_band_not_modelled_is_said_apart():
    """T2 (15 m) is in a band the rules model, T3 (9 m) in one they do not: T2 is judged, T3 is
    NOT_CHECKED, and their gap is the taller block's, which is the modelled one."""
    unmodelled = low_band(0, 12, setback=None, road=None, modelled=False)
    bands = (unmodelled, low_band(12, 18, setback=3.7, gap=4.3, road=8.4),
             low_band(18, 21, setback=4.9, gap=5.7, road=11.6, up_to_inclusive=False))
    report = with_bands_below(flat(fixture("rectangle"), T2=5, T3=3), bands).report()
    assert status(report, "All-round setback: T2") is Z.PASS
    assert status(report, "All-round setback: T3") is Z.NOT_CHECKED
    assert status(report, "Gap between blocks: T2 / T3") is Z.PASS  # the taller block's gap
    nine = with_bands_below(flat(fixture("rectangle"), T2=3, T3=3), bands).report()
    assert status(nine, "Gap between blocks: T2 / T3") is Z.NOT_CHECKED


def test_a_band_the_rules_mark_unverified_settles_nothing_either_way():
    """The same 1.51 m setback is a FAIL on a band the rules confirm and UNVERIFIED on one they
    mark UNVERIFIED, as a height limit on unconfirmed inputs is (`HeightLimit.evaluate`)."""
    unsure = tuple(low_band(b.above_m, b.up_to_m, setback=b.setback_m, gap=b.gap_m,
                            road=b.min_road_m, up_to_inclusive=b.up_to_inclusive,
                            status=Provenance.UNVERIFIED) for b in (LOW_A, LOW_B, LOW_C))
    base = all_low(fixture("rectangle"))
    assert status(with_low_bands(base).edited(_t2_to_the_west(9.5)).report(),
                  "All-round setback: T2") is Z.FAIL
    report = with_bands_below(base, unsure).edited(_t2_to_the_west(9.5)).report()
    assert status(report, "All-round setback: T2") is Z.UNVERIFIED
    assert "UNVERIFIED" in check(report, "All-round setback: T2").finding.note
    for rule in ("Gap between blocks: T1 / T2", "Abutting road width (for T1)",
                 "Club house: setback"):
        assert status(report, rule) is Z.UNVERIFIED, rule


# --- setback -----------------------------------------------------------------------------------


def test_a_low_block_keeps_the_setback_its_own_band_asks_and_cites_the_bands_own_table():
    """15 m is band B, 3.7 m. The check cites the band's table, not Table IV's front clause."""
    c = check(with_low_bands(all_low(fixture("rectangle"))).report(), "All-round setback: T2")
    assert c.finding.status is Z.PASS and c.finding.measured == "11.01 m"
    assert c.finding.required == ">= 3.70 m to the net plot line"
    assert MADE_UP in c.finding.clause
    assert "front setback of a high-rise" not in c.finding.clause  # that clause is Table IV's
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.PASS, NOT_COUNTED: Z.PASS}


@pytest.mark.parametrize("west_m, expected", [
    (7.30, Z.PASS),  # 3.71 m: just over band B's 3.7 m
    (7.32, Z.FAIL),  # 3.69 m: just under it
])
def test_a_low_block_is_held_to_its_bands_setback_to_the_centimetre(west_m, expected):
    inputs = with_low_bands(all_low(fixture("rectangle"))).edited(_t2_to_the_west(west_m))
    assert status(inputs.report(), "All-round setback: T2") is expected


def test_a_low_block_that_is_not_wholly_on_the_plot_fails_whatever_its_band():
    inputs = with_low_bands(all_low(fixture("rectangle"))).edited(_t2_to_the_west(20.0))
    c = check(inputs.report(), "All-round setback: T2")
    assert c.finding.status is Z.FAIL and "not wholly inside" in c.finding.measured


def test_a_block_that_is_high_rise_only_if_the_stilt_counts_is_judged_on_both_tables():
    """6 floors on a 3 m stilt: 21 m if the stilt counts (Table IV's first row, 7 m), 18 m if not
    (band B, 3.7 m). With a band modelled for the second reading the block can be passed, or
    failed, on both: 5.0 m keeps band B's figure and not Table IV's."""
    base = with_low_bands(floors_of(fixture("rectangle"), T3=6))
    c = check(base.report(), "All-round setback: T3")
    assert c.finding.status is Z.PASS
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.PASS, NOT_COUNTED: Z.PASS}
    near = check(base.edited(lambda c: move_tower(c, "T3", 12.0, 0.0)).report(),
                 "All-round setback: T3")  # 150 - 145.03 = 4.97 m
    assert near.finding.status is Z.UNVERIFIED
    assert near.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.FAIL, NOT_COUNTED: Z.PASS}


def test_table_iii_is_read_on_the_height_above_the_stilt_whatever_the_reading():
    """Rule 5(c) leaves the stilt out of Table III's heights. 4 floors on a 3 m stilt are 15 m of
    rule height if the stilt counts and 12 m if not, and either way 12 m above the stilt: band A,
    2.3 m, which no road need serve. The class (high-rise or not) still follows the reading, and
    the report says which height the band was read on."""
    stilted = with_low_bands(floors_of(fixture("rectangle"), T1=4, T2=4, T3=4))
    report = stilted.report()
    t1 = next(t for t in report.recomputed.towers if t.name == "T1")
    assert t1.rule_height_m_by_reading == {COUNTED: 15.0, NOT_COUNTED: 12.0}
    assert set(t1.band_by_reading.values()) == {"non-high-rise 0-12 m"}
    assert t1.required_setback_m_by_reading == {COUNTED: 2.3, NOT_COUNTED: 2.3}
    height_class = check(report, "Height class: T1")
    assert "15.00 m, read as 12.00 m above the stilt" in height_class.finding.measured
    near = check(stilted.edited(_t2_to_the_west(7.5)).report(), "All-round setback: T2")
    assert near.finding.status is Z.PASS  # 3.51 m keeps band A's 2.3 m under both readings
    assert near.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.PASS, NOT_COUNTED: Z.PASS}
    too_near = check(stilted.edited(_t2_to_the_west(9.5)).report(), "All-round setback: T2")
    assert too_near.finding.status is Z.FAIL  # 1.51 m, under both
    narrow = check(access_road_of(stilted, 5.0).report(), "Abutting road width (for T1)")
    assert narrow.finding.status is Z.PASS and narrow.finding.required == ">= 0 m"


def test_a_block_below_21_m_with_the_stilt_counted_is_not_shifted_a_row_by_it():
    """5 floors on a 3 m stilt: 18 m of rule height when the stilt counts, which would be band B,
    and 15 m above the stilt, which is band B too; 6 floors are 21 m (a high-rise) when it counts
    and band B (18 m above the stilt) when it does not. The row follows the height above the
    stilt, so a block 3 m taller on its stilt is not held to a row 3 m higher."""
    five = with_low_bands(floors_of(fixture("rectangle"), T2=5))
    t2 = next(t for t in five.report().recomputed.towers if t.name == "T2")
    assert set(t2.band_by_reading.values()) == {"non-high-rise 12-18 m"}
    four = with_low_bands(floors_of(fixture("rectangle"), T2=4))  # 12 m above the stilt
    t2 = next(t for t in four.report().recomputed.towers if t.name == "T2")
    assert set(t2.band_by_reading.values()) == {"non-high-rise 0-12 m"}


# --- gaps between blocks -----------------------------------------------------------------------


def test_two_low_blocks_keep_the_tallest_blocks_gap_whatever_the_open_reading_says():
    """Rule 5(f)(xiii) says whose figure it is, so mixed-height spacing (a Table IV question) does
    not reach two blocks below the high-rise height: T2 is 12 m (3.1 m), T3 15 m (4.3 m), and a
    4.0 m gap is under the taller block's under every reading, though it would clear the mean of
    the two (3.7 m). The check quotes the rule, page and words."""
    inputs = spacing_open(with_low_bands(flat(fixture("rectangle"), T2=4, T3=5)))
    inputs = inputs.edited(lambda c: move_tower(c, "T3", -5.02, 0.0))  # T2/T3 gap 4.00 m
    c = check(inputs.report(), "Gap between blocks: T2 / T3")
    assert c.finding.status is Z.FAIL
    assert c.by_reading[MIXED_HEIGHT_SPACING] == {TALLER: Z.FAIL, EACH_OWN: Z.FAIL}
    assert ">= 4.30 m (the tallest block's side setback)" in c.finding.required
    assert "rule 5(f)(xiii), p.11" in c.finding.note and RULE_5_XIII in c.finding.note
    assert "rule 5(f)(xiii)" in c.finding.clause and MADE_UP in c.finding.clause


def test_a_reading_of_spacing_the_validator_does_not_know_never_reaches_two_low_blocks():
    """Two low blocks are decided by the rule's own words, so there is no reading to be unsure
    of; a low block beside a high-rise has one, and it is UNVERIFIED, never guessed."""
    def invent(rules):
        spacing = rules.interpretation(MIXED_HEIGHT_SPACING)
        spacing.alternatives["half_each"] = "half of each"
        spacing.selected = "half_each"
    low_low = with_low_bands(all_low(fixture("rectangle"))).with_rules(invent)
    assert status(low_low.report(), "Gap between blocks: T2 / T3") is Z.PASS
    mixed = _counted(with_low_bands(flat(fixture("rectangle"), T2=5))).with_rules(invent)
    c = check(mixed.report(), "Gap between blocks: T2 / T3")
    assert c.finding.status is Z.UNVERIFIED and "half_each" in c.finding.measured


def test_a_low_block_beside_a_high_rise_is_judged_under_every_reading_of_spacing():
    """T2 is 15 m (band B, 4.3 m), T3 27 m (Table IV, 9 m). The taller block's gap is 9 m; if each
    keeps its own it is their mean, 6.65 m. 8.02 m passes one reading and not the other."""
    base = _counted(spacing_open(with_low_bands(flat(fixture("rectangle"), T2=5))))
    near = base.edited(lambda c: move_tower(c, "T3", -1.0, 0.0))  # gap 8.02 m
    c = check(near.report(), "Gap between blocks: T2 / T3")
    assert c.finding.status is Z.UNVERIFIED
    assert c.by_reading[MIXED_HEIGHT_SPACING] == {TALLER: Z.FAIL, EACH_OWN: Z.PASS}
    assert "6.65 m" in c.finding.required and ">= 9.00 m" in c.finding.required
    nearer = base.edited(lambda c: move_tower(c, "T3", -3.5, 0.0))  # gap 5.52 m
    assert status(nearer.report(), "Gap between blocks: T2 / T3") is Z.FAIL
    assert status(base.report(), "Gap between blocks: T2 / T3") is Z.PASS  # 9.02 m


def test_where_a_band_gives_no_gap_of_its_own_the_setback_is_the_gap():
    """The contract reads an unset gap as the band's setback (as for Table IV, where the two are
    one figure). State the gap where they differ."""
    bands = (low_band(0, 12, setback=2.3, road=0.0), low_band(12, 18, setback=6.5, road=8.4),
             low_band(18, 21, setback=4.9, road=11.6, up_to_inclusive=False))
    inputs = with_bands_below(all_low(fixture("rectangle")), bands).edited(
        lambda c: move_tower(c, "T3", -3.0, 0.0))  # T2/T3 gap 6.02 m
    c = check(inputs.report(), "Gap between blocks: T2 / T3")
    assert c.finding.status is Z.FAIL and ">= 6.50 m" in c.finding.required


def test_blocks_of_the_high_rise_height_keep_the_gaps_they_always_did():
    """Installing modelled bands below 21 m moves no gap between two high-rise blocks."""
    for name in ("rectangle", "l_plot_with_arm"):
        inputs = spacing_open(fixture(name))
        moved = changed_rules(inputs.report(), with_low_bands(inputs).report())
        assert not [r for r in moved if r.startswith("Gap between blocks")], name


# --- the road the band asks --------------------------------------------------------------------


def test_the_road_a_low_band_asks_is_held_to_the_access_road():
    """15 m is band B, which asks 8.4 m of the abutting road."""
    low = with_low_bands(all_low(fixture("rectangle")))
    assert status(access_road_of(low, 8.4).report(), "Abutting road width (for T1)") is Z.PASS
    short = check(access_road_of(low, 8.0).report(), "Abutting road width (for T1)")
    assert short.finding.status is Z.FAIL and short.finding.required == ">= 8.4 m"
    assert MADE_UP in short.finding.clause


def test_a_band_that_asks_no_road_passes_the_narrowest():
    inputs = access_road_of(with_low_bands(all_low(fixture("rectangle"), 4)), 5.0)  # 12 m: band A
    c = check(inputs.report(), "Abutting road width (for T1)")
    assert c.finding.status is Z.PASS and c.finding.required == ">= 0 m"


def test_a_band_that_states_no_road_is_named_and_not_judged_never_read_as_asking_none():
    """`min_road_m` None is 'not stated', and 0.0 is 'asks none': a missing figure is not a pass."""
    bands = (low_band(0, 12, setback=2.3, gap=3.1, road=None), LOW_B,
             low_band(18, 21, setback=4.9, gap=5.7, road=11.6, up_to_inclusive=False))
    alone = with_bands_below(all_low(fixture("rectangle"), 4), bands)  # 12 m: the band with none
    assert status(alone.report(), "Abutting road width (for T1)") is Z.NOT_CHECKED
    with_a_high_rise = with_bands_below(flat(fixture("rectangle"), T2=4), bands)
    c = check(with_a_high_rise.report(), "Abutting road width (for T1)")
    assert c.finding.status is Z.PASS  # the high-rise blocks are judged, as they always were
    assert "T2" in c.finding.note and "not judged here" in c.finding.note


def test_a_roads_unconfirmed_width_leaves_a_low_blocks_road_unverified():
    def drawn(site):
        site.access_road().row_status = "UNVERIFIED_DRAWING_VALUE"
    c = check(with_low_bands(all_low(fixture("rectangle"))).with_site(drawn).report(),
              "Abutting road width (for T1)")
    assert c.finding.status is Z.UNVERIFIED and "never confirmed" in c.finding.note


def test_the_road_check_names_the_tallest_high_rise_as_it_always_did():
    report = with_low_bands(flat(fixture("rectangle"), T2=5)).report()  # T1, T3: 27 m; T2: 15 m
    c = check(report, "Abutting road width (for T1)")
    assert c.subject == "T1"
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.PASS, NOT_COUNTED: Z.PASS}
    assert ">= 18 m" in c.finding.required  # the high-rise rows still decide


# --- a prohibited high-rise says nothing of a lower block --------------------------------------


def test_a_prohibition_fails_a_block_of_exactly_the_high_rise_height_and_not_one_just_under():
    """7 floors of 3 m, no stilt: 21.0 m, a high-rise (rule 2(f)). 5 floors of 4.18 m: 20.9 m."""
    inputs = _prohibited(with_low_bands(fixture("rectangle")))
    assert inputs.rules.height.high_rise.eligibility is Eligibility.PROHIBITED
    names = [t.name for t in inputs.candidate.towers]
    exactly, under = inputs, inputs
    for n in names:
        exactly = flat_block(exactly, n, 7, 3.0)
        under = flat_block(under, n, 5, 4.18)
    assert status(exactly.report(), "High-rise eligibility") is Z.FAIL
    report = under.report()
    assert "High-rise eligibility" not in {x.finding.rule for x in report.legal}
    assert check(report, "Height class: T1").finding.measured.startswith("20.90 m physical")


def test_a_prohibition_permits_nothing_lower_and_a_low_block_is_judged_on_its_band_alone():
    """On a site that may take no high-rise, a block below 21 m neither passes nor fails on the
    prohibition. In a band the rules do not model it is NOT_CHECKED; in one they model, its band
    decides, PASS or FAIL, exactly as on a site that may take a high-rise."""
    shut = _prohibited(all_low(fixture("rectangle")))
    assert status(shut.report(), "All-round setback: T1") is Z.NOT_CHECKED
    modelled = _prohibited(with_low_bands(all_low(fixture("rectangle"))))
    open_site = with_low_bands(all_low(fixture("rectangle")))
    for inputs in (modelled, open_site):
        report = inputs.report()
        assert "High-rise eligibility" not in {c.finding.rule for c in report.legal}
        assert status(report, "All-round setback: T1") is Z.PASS
    shut_fail = check(modelled.edited(_t2_to_the_west(9.5)).report(), "All-round setback: T2")
    open_fail = check(open_site.edited(_t2_to_the_west(9.5)).report(), "All-round setback: T2")
    assert shut_fail.finding.status is Z.FAIL and shut_fail.finding == open_fail.finding


def test_a_prohibition_fails_the_high_rise_in_a_mixed_layout_and_leaves_the_low_block_alone():
    layout = with_low_bands(flat(fixture("rectangle"), T2=5))
    report = _prohibited(layout).report()
    assert status(report, "High-rise eligibility") is Z.FAIL  # T1 and T3 are 27 m
    assert status(report, "All-round setback: T2") is Z.PASS
    assert (check(report, "All-round setback: T2").finding
            == check(layout.report(), "All-round setback: T2").finding)


# --- nothing moves for the blocks that were already judged --------------------------------------


@pytest.mark.parametrize("site", ["rectangle", "l_plot_with_arm", "nala_plot"])
def test_installing_modelled_bands_below_21_m_moves_no_check_of_a_high_rise_layout(site):
    """The fixtures' towers are all high-rise. Only the club house, which is the one low block
    there, changes: it is judged on its band instead of NOT_CHECKED."""
    before = fixture(site).report()
    after = with_low_bands(fixture(site)).report()
    moved = changed_rules(before, after)
    assert set(moved) <= {"Club house: setback", "Club house gap to T1", "Club house gap to T2",
                          "Club house gap to T3"}
    assert after.verdict.legal is before.verdict.legal


def test_the_high_rise_blocks_of_a_mixed_layout_are_judged_as_before_the_low_one_is_modelled():
    """T3 is 15 m. Whether its band is modelled changes T3's own checks and nothing about T1 or
    T2's: their setback, fire access and eligibility read the same."""
    shut = flat(fixture("rectangle"), T3=5)
    open_ = with_low_bands(shut)
    for rule in ("All-round setback: T1", "All-round setback: T2", "Fire access: T1",
                 "Fire access: T2", "High-rise eligibility", "Plot size for high-rise",
                 "Gap between blocks: T1 / T2"):
        assert check(shut.report(), rule) == check(open_.report(), rule), rule


def test_an_unmodelled_low_block_beside_a_high_rise_does_not_hide_the_high_rise_road_verdict():
    """The road check judges the high-rise blocks as before; the block it cannot judge is named."""
    report = flat(fixture("rectangle"), T3=5).report()  # T3 15 m, band not modelled
    c = check(report, "Abutting road width (for T1)")
    assert c.finding.status is Z.PASS and "T3" in c.finding.note
    assert c.by_reading[STILT_IN_RULE_HEIGHT] == {COUNTED: Z.PASS, NOT_COUNTED: Z.PASS}
    assert status(report, "All-round setback: T3") is Z.NOT_CHECKED


def test_the_report_carries_the_low_bands_figures_and_survives_json():
    from siteplan.contracts import ValidationReport
    report = with_low_bands(all_low(fixture("rectangle"))).report()
    assert {c.family for c in report.legal if c.finding.rule == "All-round setback: T1"} == {
        Family.SETBACK}
    again = ValidationReport.model_validate_json(report.model_dump_json())
    assert again.verdict == report.verdict
    measure = next(t for t in report.recomputed.towers if t.name == "T1")
    assert measure.required_setback_m_by_reading == {COUNTED: 3.7, NOT_COUNTED: 3.7}
    assert measure.band_by_reading == {COUNTED: "non-high-rise 12-18 m",
                                       NOT_COUNTED: "non-high-rise 12-18 m"}
    pair = next(p for p in report.recomputed.pairs if (p.a, p.b) == ("T1", "T2"))
    assert pair.required_m == 4.3
    assert {row.item.value for row in report.design_targets} >= {"setback", "tower_gap"}
