"""The envelope cross-check on contracts 1.2: a band's front setback and its permission.

An envelope more lenient than the law (a smaller front setback, more buildable land, a band it
calls allowed that the law prohibits) would let a layout pass that the law forbids, so it blocks;
a stricter one only costs room. Until an edge-wise inset exists the envelope's buildable land is
inset all round by the larger of the band's two figures, and the validator recomputes it that way.

The front figure here is MADE UP (11 m on the 24-27 m band); it is not a value of the order.
"""

from dataclasses import replace

from shapely.geometry import box
from validator_helpers import fixture, shapes

from siteplan.contracts import digest
from siteplan.contracts.resolved_rules import BandKind, Eligibility

TEST_CLASS = "normative"
NET = box(0, 0, 150, 100)
FRONT_M = 11.0  # made up: the 24-27 m band keeps 9 m on the other sides


def _envelope_band(envelope, above_m=24.0, up_to_m=27.0):
    return next(b for b in envelope.bands if (b.above_m, b.up_to_m) == (above_m, up_to_m))


def _with_front(inputs=None, *, permission=None, note="made up: no 24-27 m on this site"):
    """The rectangle with a front figure (and, if asked, a permission) on the 24-27 m band, the
    envelope re-pointed at the new rules so it is compared."""
    inputs = inputs or fixture("rectangle")

    def edit(rules):
        band = next(b for b in rules.height.bands
                    if b.kind is BandKind.HIGH_RISE and b.above_m == 24.0)
        band.front_setback_m = FRONT_M
        if permission is not None:
            band.permission, band.permission_note = permission, note
    inputs = inputs.with_rules(edit)
    envelope = inputs.envelope.model_copy(deep=True)
    envelope.rules_ref = digest(inputs.rules)
    return replace(inputs, envelope=envelope)


def _consistent(inputs):
    """An envelope that carries the band's front figure and insets by the larger of the two."""
    band = _envelope_band(inputs.envelope)
    band.front_setback_m = FRONT_M
    land = NET.buffer(-FRONT_M)
    band.setback_envelope, band.buildable, band.area_sqm = shapes(land), shapes(land), land.area
    return inputs


def _envelope_items(report):
    return {d.item: d for d in report.cross_checks if d.source == "envelope"}


def test_an_envelope_that_carries_the_front_and_insets_by_the_larger_figure_agrees():
    report = _consistent(_with_front()).report(envelope=True)
    assert [d.item for d in report.cross_checks if d.item.startswith("envelope ")] == []


def test_an_envelope_that_leaves_out_the_front_figure_is_more_lenient_and_blocks():
    """The band's land was inset by its 9 m on every side: short of the front's 11 m, and the
    envelope states no front at all, so it would let a block stand 2 m too near the road."""
    report = _with_front().report(envelope=True)  # the fixture envelope: 9 m, no front
    items = _envelope_items(report)
    front = items["envelope front setback, band 24-27 m"]
    assert front.blocks_pass and (front.theirs, front.ours) == ("9 m", "11 m")
    land = items["envelope buildable land, band 24-27 m"]
    assert land.blocks_pass  # more land than the law leaves


def test_an_envelope_with_a_larger_front_than_the_law_is_recorded_without_blocking():
    inputs = _consistent(_with_front())
    _envelope_band(inputs.envelope).front_setback_m = 13.0
    item = _envelope_items(inputs.report(envelope=True))["envelope front setback, band 24-27 m"]
    assert not item.blocks_pass and (item.theirs, item.ours) == ("13 m", "11 m")


def test_a_band_the_envelope_calls_allowed_that_the_law_prohibits_blocks():
    inputs = _consistent(_with_front(permission=Eligibility.PROHIBITED))
    assert _envelope_band(inputs.envelope).permission is Eligibility.ALLOWED
    item = _envelope_items(inputs.report(envelope=True))["envelope permission, band 24-27 m"]
    assert item.blocks_pass and (item.theirs, item.ours) == ("ALLOWED", "PROHIBITED")


def test_a_band_the_envelope_calls_unverified_that_the_law_prohibits_blocks_too():
    inputs = _consistent(_with_front(permission=Eligibility.PROHIBITED))
    _envelope_band(inputs.envelope).permission = Eligibility.UNVERIFIED
    item = _envelope_items(inputs.report(envelope=True))["envelope permission, band 24-27 m"]
    assert item.blocks_pass and (item.theirs, item.ours) == ("UNVERIFIED", "PROHIBITED")


def test_a_band_the_envelope_prohibits_that_the_law_allows_is_recorded_without_blocking():
    inputs = _consistent(_with_front())
    _envelope_band(inputs.envelope).permission = Eligibility.PROHIBITED
    item = _envelope_items(inputs.report(envelope=True))["envelope permission, band 24-27 m"]
    assert not item.blocks_pass and (item.theirs, item.ours) == ("PROHIBITED", "ALLOWED")


def test_a_high_rise_band_follows_the_sites_eligibility_in_the_permission_it_is_compared_on():
    """`HeightRules.band_permission` adds the site's high-rise eligibility to a high-rise band: an
    envelope that calls such a band allowed on a site that may take no high-rise blocks."""
    def no_high_rise(rules):
        high_rise = rules.height.high_rise
        next(g for g in high_rise.grounds if g.id == "road_width").met = False
        high_rise.eligibility = type(high_rise).of_grounds(high_rise.grounds)
    inputs = _consistent(_with_front())
    shut = inputs.with_rules(no_high_rise)
    envelope = shut.envelope.model_copy(deep=True)
    envelope.rules_ref = digest(shut.rules)
    item = _envelope_items(replace(shut, envelope=envelope).report(envelope=True))[
        "envelope permission, band 24-27 m"]
    assert item.blocks_pass and item.ours == "PROHIBITED"
