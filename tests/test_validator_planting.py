"""The planting a band asks (contracts 1.2: `Band.green_strip_m` and `green_strip_sides`).

A band carries the strip it asks: a width, along the frontage or round the whole plot line (Table
III's, rule 5(f)). A strip lies within the setbacks and is never added to them. A high-rise band
that carries none is held to the high-rise strip as before (rule 7(a)(viii)); a band below the
high-rise height that carries none asks none. Where the access road's side is not known a strip
along only the frontage cannot be placed, and what cannot be told is UNVERIFIED.

Every band is MADE UP (tests/validator_low_helpers.py); no figure is a value of the order.
"""

from shapely.geometry import box
from validator_helpers import check, fixture, move_tower, select, shapes, status
from validator_low_helpers import all_low, low_band, with_bands_below, with_low_bands

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT, BandKind

TEST_CLASS = "normative"
Z = Status
STRIP = "Peripheral green strip"
COUNTED = "counted"


def _bands(strip, sides):
    """15 m is band B: the strip it asks (made up) along `sides`."""
    return (low_band(0, 12, setback=2.3, gap=3.1, road=0.0),
            low_band(12, 18, setback=3.7, gap=4.3, road=8.4, strip=strip, strip_sides=sides),
            low_band(18, 21, setback=4.9, gap=5.7, road=11.6, up_to_inclusive=False))


def _asking(strip, sides):
    return with_bands_below(all_low(fixture("rectangle")), _bands(strip, sides))


def _strip_without(region):
    """The drawn strip (a 2 m ring round the plot) less `region`."""
    def edit(candidate):
        ring = candidate.program.green_strip[0].to_shapely()
        candidate.program.green_strip = shapes(ring.difference(region))
    return edit


def _access_side(side):
    return lambda site: setattr(site.access.side, "value", side)


def test_a_strip_along_the_frontage_is_held_to_the_stretch_facing_the_access_road():
    """Band B asks 1.3 m along the frontage; the access road runs on the south. The drawn ring
    covers it; take the south stretch out of the ring and it is missing."""
    base = _asking(1.3, "FRONTAGE")
    c = check(base.report(), STRIP)
    assert c.finding.status is Z.PASS and ">= 1.3 m along the frontage" in c.finding.required
    assert "MADE-UP" in c.finding.clause
    short = check(base.edited(_strip_without(box(-1, -1, 151, 5))).report(), STRIP)
    assert short.finding.status is Z.FAIL and "of the strip is missing" in short.finding.measured


def test_a_strip_along_the_frontage_does_not_ask_for_the_other_sides():
    """The other three sides may go bare when only the frontage is asked."""
    base = _asking(1.3, "FRONTAGE")
    bare_elsewhere = base.edited(_strip_without(box(-1, 5, 151, 101)))  # only the south remains
    assert status(bare_elsewhere.report(), STRIP) is Z.PASS


def test_a_strip_asked_on_all_sides_is_held_all_round():
    base = _asking(0.9, "ALL")
    assert status(base.report(), STRIP) is Z.PASS
    c = check(base.edited(_strip_without(box(-1, 40, 6, 60))).report(), STRIP)  # a gap on the west
    assert c.finding.status is Z.FAIL and ">= 0.9 m on all sides" in c.finding.required


def test_a_drawn_strip_narrower_than_the_band_asks_fails():
    """The drawn ring is 2 m wide: it is short of a 2.5 m strip asked on all sides."""
    c = check(_asking(2.5, "ALL").report(), STRIP)
    assert c.finding.status is Z.FAIL and "narrower than 2.5 m in places" in c.finding.measured


def test_where_the_frontage_cannot_be_placed_a_strip_along_it_is_unverified():
    """With the access road's side not known nothing says which stretch is the frontage: a ring
    that leaves the south bare may or may not have missed it."""
    base = _asking(1.3, "FRONTAGE").with_site(_access_side(None))
    assert status(base.report(), STRIP) is Z.PASS  # the whole ring is drawn: covered wherever it is
    bare_south = base.edited(_strip_without(box(-1, -1, 151, 5)))
    c = check(bare_south.report(), STRIP)
    assert c.finding.status is Z.UNVERIFIED and "access road's side is not known" in (
        c.finding.measured)


def test_a_strip_lies_within_the_setback_and_is_never_added_to_it():
    """A block standing exactly at its band's setback passes with a strip asked: the strip is
    within that distance, not beyond it."""
    inputs = _asking(1.3, "ALL").edited(lambda c: move_tower(c, "T2", 3.71 - 11.01, 0.0))
    assert status(inputs.report(), "All-round setback: T2") is Z.PASS  # 3.71 m: band B asks 3.7 m


def test_a_band_that_carries_no_strip_asks_none():
    """A band below the high-rise height with no strip of its own asks none: the high-rise strip
    is not applied to it, and the check says the bands asked nothing."""
    c = check(with_low_bands(all_low(fixture("rectangle"))).report(), STRIP)
    assert c.finding.status is Z.INFO
    assert "ask none" in c.finding.note and "T1, T2, T3" in c.finding.note
    zero = check(_asking(0.0, "ALL").report(), STRIP)
    assert zero.finding.status is Z.INFO  # a strip of nothing is none


def test_a_high_rise_band_that_carries_a_strip_is_held_to_it_not_to_the_high_rise_default():
    """The 24-27 m band asks 2.5 m here; the drawn 2 m ring, which meets the high-rise strip, is
    short of it. The stilt counted, T1 to T3 are in that band."""
    def own_strip(rules):
        next(b for b in rules.height.bands if b.kind is BandKind.HIGH_RISE
             and b.above_m == 24.0).green_strip_m = 2.5
    base = fixture("rectangle").with_rules(own_strip).with_rules(
        lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))
    c = check(base.report(), STRIP)
    assert c.finding.status is Z.FAIL and "narrower than 2.5 m" in c.finding.measured
    assert ">= 2.5 m on all sides" in c.finding.required


def test_a_high_rise_band_that_carries_none_keeps_the_high_rise_strip():
    """As before: 2 m where the setback reaches 9 m (the 24-27 m band, the stilt counted). The
    contract fixtures' high-rise bands from 9 m carry that strip themselves (A2: 2 m, all
    sides); without it the check falls back on rule 7(a)(viii), to the same verdict."""
    def none_carried(rules):
        for band in rules.height.bands:
            if band.kind is BandKind.HIGH_RISE:
                band.green_strip_m = None
    shipped = fixture("rectangle").with_rules(lambda r: select(r, STILT_IN_RULE_HEIGHT, COUNTED))
    c = check(shipped.with_rules(none_carried).report(), STRIP)
    assert c.finding.status is Z.PASS
    assert c.finding.required == ">= 2 m on sides with a setback of 9 m or more"
    carried = check(shipped.report(), STRIP)
    assert carried.finding.status is Z.PASS and carried.finding.required == ">= 2 m on all sides"
