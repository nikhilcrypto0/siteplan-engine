"""What the generator and an envelope claim, against what the validator recomputes: nothing the
validator judges is taken from them, and where they disagree with it the report says so, and
blocks a pass when the claim flatters the layout."""

from dataclasses import replace

from shapely.geometry import box
from validator_helpers import (
    check,
    fixture,
    footprint,
    move_tower,
    shape,
    shapes,
    status,
)

from siteplan.contracts import digest
from siteplan.contracts.common import Finding, Status
from siteplan.contracts.validation import LegalVerdict

TEST_CLASS = "normative"
Z = Status
NET = box(0, 0, 150, 100)


def _discrepancy(report, item):
    found = [d for d in report.cross_checks if d.item == item]
    assert len(found) == 1, (item, [d.item for d in report.cross_checks])
    return found[0]


def _north_to(inputs, name, metres):
    def plant(candidate):
        move_tower(candidate, name, 0.0,
                   NET.boundary.distance(footprint(candidate, name)) - metres)
    return inputs.edited(plant)


# --- the report names what it judged ---------------------------------------------------------


def test_the_report_names_the_exact_inputs_it_judged_and_the_envelope_only_if_given():
    inputs = fixture("rectangle")
    report = inputs.report()
    assert (report.site_ref, report.rules_ref, report.brief_ref) == (
        digest(inputs.site), digest(inputs.rules), digest(inputs.brief))
    assert report.candidate_ref == digest(inputs.candidate) and report.envelope_ref is None
    assert inputs.report(envelope=True).envelope_ref == digest(inputs.envelope)
    assert "independent" in report.validator_version


def test_a_candidate_made_for_other_inputs_proves_nothing_and_blocks_a_pass():
    inputs = fixture("rectangle")
    report = replace(inputs, candidate=inputs.candidate.model_copy(
        update={"site_ref": "0123456789abcdef"})).report()
    d = _discrepancy(report, "candidate.site_ref")
    assert d.blocks_pass and d.theirs == "0123456789abcdef" and d.ours == digest(inputs.site)
    assert report.verdict.legal is LegalVerdict.FAIL


def test_rules_resolved_for_another_site_block_a_pass():
    inputs = fixture("rectangle")
    other = inputs.rules.model_copy(update={"site_ref": "ffffffffffffffff"})
    report = replace(inputs, rules=other).report()
    assert _discrepancy(report, "rules.site_ref").blocks_pass


# --- the footprint and the generator's own findings ----------------------------------------------


def test_the_generators_own_pass_where_the_validator_fails_is_recorded_and_blocks():
    inputs = _north_to(fixture("rectangle"), "T1", 7.0)  # its claims were made before the move
    report = inputs.report()
    d = _discrepancy(report, "All-round setback: T1")
    assert d.source == "generator" and d.blocks_pass
    assert d.theirs.startswith("PASS") and d.ours.startswith("FAIL")


def test_a_claim_the_validator_cannot_confirm_is_recorded_but_does_not_block():
    inputs = fixture("rectangle")
    report = inputs.report()
    d = _discrepancy(report, "Fire access: the street joins a 12 m street")
    assert not d.blocks_pass and d.theirs.startswith("UNVERIFIED") and d.ours.startswith("PASS")
    assert report.verdict.legal is LegalVerdict.UNVERIFIED  # not made a FAIL by it


def test_a_generator_that_is_more_cautious_than_the_validator_is_recorded_not_blocked():
    def cautious(candidate):
        candidate.generator_claims = [
            Finding(c.rule, Z.FAIL if c.rule == "Gap between blocks: T1 / T2" else c.status,
                    c.measured, c.required, c.clause, c.note) for c in candidate.generator_claims]
    d = _discrepancy(fixture("rectangle").edited(cautious).report(), "Gap between blocks: T1 / T2")
    assert not d.blocks_pass and d.theirs.startswith("FAIL") and d.ours.startswith("PASS")


def test_the_untouched_fixtures_have_no_blocking_discrepancy():
    for site in ("rectangle", "l_plot_with_arm", "nala_plot", "small_plot"):
        report = fixture(site).report(envelope=True)
        assert [d.item for d in report.cross_checks if d.blocks_pass] == [], site


# --- the totals the generator reports -------------------------------------------------------------


def test_a_built_up_area_claimed_smaller_than_it_is_blocks_and_one_claimed_larger_does_not():
    def shrink(candidate):
        candidate.metrics.built_up_sqft *= 0.9

    def grow(candidate):
        candidate.metrics.built_up_sqft *= 1.1
    assert _discrepancy(fixture("rectangle").edited(shrink).report(), "built-up area").blocks_pass
    assert not _discrepancy(fixture("rectangle").edited(grow).report(), "built-up area").blocks_pass


def test_open_space_claimed_larger_than_counts_blocks():
    def inflate(candidate):
        candidate.metrics.open_space_sqm *= 1.2
    assert _discrepancy(fixture("rectangle").edited(inflate).report(), "open space").blocks_pass


def test_a_wrong_flat_count_is_recorded_without_blocking():
    def miscount(candidate):
        candidate.metrics.total_flats += 8
        candidate.metrics.flats_by_type = {"2BHK": 130, "3BHK": 86}
    report = fixture("rectangle").edited(miscount).report()
    assert not _discrepancy(report, "flats").blocks_pass
    assert not _discrepancy(report, "flats by type").blocks_pass
    assert report.recomputed.units_by_type == {"2BHK": 128, "3BHK": 80}


def test_more_cars_claimed_than_fit_is_recorded_without_blocking():
    def boast(candidate):
        candidate.metrics.extra["parking"]["cars"] = {"stilt": 900, "cellar 1": 900}
    d = _discrepancy(fixture("rectangle").edited(boast).report(), "cars that fit")
    assert not d.blocks_pass and d.theirs == "1,800"


# --- an envelope is only ever compared --------------------------------------------------------


def _envelope_with_setback(inputs, metres, bands=("24-27",)):
    """The envelope as a buggy producer would make it: a smaller setback all through, and the
    buildable land worked out from it."""
    envelope = inputs.envelope.model_copy(deep=True)
    for band in envelope.bands:
        if f"{band.above_m:g}-{band.up_to_m:g}" in bands:
            band.setback_m = metres
            land = NET.buffer(-metres)
            band.setback_envelope = shapes(land)
            band.buildable = shapes(land)
            band.area_sqm = land.area
    return replace(inputs, envelope=envelope)


def test_an_envelope_with_too_small_a_setback_does_not_pass_a_tower_that_breaches_the_true_one():
    inputs = _north_to(fixture("rectangle"), "T1", 7.7)  # short of the law under every reading
    wrong = _envelope_with_setback(inputs, 3.0, bands=("21-24", "24-27"))
    report = wrong.report(envelope=True)
    assert status(report, "All-round setback: T1") is Z.FAIL
    blocking = [d for d in report.cross_checks if d.source == "envelope" and d.blocks_pass]
    assert {d.item for d in blocking} >= {"envelope setback, band 24-27 m"}
    d = next(d for d in blocking if d.item == "envelope setback, band 24-27 m")
    assert d.theirs == "3 m" and d.ours == "9 m"
    assert report.verdict.legal is LegalVerdict.FAIL


def test_the_same_wrong_envelope_blocks_a_pass_even_where_the_layout_happens_to_be_legal():
    wrong = _envelope_with_setback(fixture("rectangle"), 3.0)
    report = wrong.report(envelope=True)
    assert status(report, "All-round setback: T1") is Z.PASS  # the layout itself is fine
    assert any(d.source == "envelope" and d.blocks_pass for d in report.cross_checks)
    assert report.verdict.legal is LegalVerdict.FAIL


def test_the_envelope_changes_no_legal_check_it_is_never_authority():
    inputs = fixture("rectangle")
    with_it = _envelope_with_setback(inputs, 3.0).report(envelope=True)
    without = inputs.report()
    assert with_it.legal == without.legal and with_it.recomputed == without.recomputed


def test_an_envelope_stricter_than_the_law_is_recorded_without_blocking():
    stricter = _envelope_with_setback(fixture("rectangle"), 12.0)
    report = stricter.report(envelope=True)
    d = _discrepancy(report, "envelope setback, band 24-27 m")
    assert not d.blocks_pass and d.theirs == "12 m"
    assert report.verdict.legal is LegalVerdict.UNVERIFIED


def test_an_envelope_with_more_buildable_land_than_there_is_blocks():
    inputs = fixture("rectangle")
    envelope = inputs.envelope.model_copy(deep=True)
    envelope.bands[1].buildable = shapes(NET.buffer(-3.0))
    d = _discrepancy(replace(inputs, envelope=envelope).report(envelope=True),
                     "envelope buildable land, band 21-24 m")
    assert d.blocks_pass and d.source == "envelope"


def test_an_envelope_that_leaves_out_the_water_buffer_blocks():
    inputs = fixture("nala_plot")
    envelope = inputs.envelope.model_copy(deep=True)
    envelope.exclusions = []
    d = _discrepancy(replace(inputs, envelope=envelope).report(envelope=True),
                     "envelope exclusions")
    assert d.blocks_pass and "2,160" in d.ours


def test_an_envelope_for_other_inputs_is_noted_and_not_compared():
    inputs = fixture("rectangle")
    envelope = inputs.envelope.model_copy(update={"site_ref": "0123456789abcdef"})
    report = replace(inputs, envelope=envelope).report(envelope=True)
    assert not _discrepancy(report, "envelope.site_ref").blocks_pass
    assert not [d for d in report.cross_checks if d.item.startswith("envelope setback")]


# --- no net plot: the validator refuses ---------------------------------------------------------


def test_a_site_with_no_net_plot_is_refused_and_can_never_pass():
    inputs = fixture("rectangle").with_site(lambda s: setattr(s, "net_plot", None))
    report = inputs.report()
    assert report.verdict.legal is LegalVerdict.UNVERIFIED
    assert [c.finding.rule for c in report.legal] == ["Net plot"]
    c = check(report, "Net plot")
    assert c.finding.status is Z.UNVERIFIED and "refuses to certify" in c.finding.note
    assert report.accounting.partition is None and report.recomputed.towers == []
    assert report.recomputed.units_by_type  # what needs no plot is still recomputed
    assert report.program  # and the program is still judged


def test_a_net_plot_that_is_not_the_net_ownership_is_not_trusted():
    def skew(site):
        site.ownership.net_sqm.value *= 1.3
    inputs = fixture("rectangle").with_site(skew)
    assert status(inputs.report(), "Net plot") is Z.UNVERIFIED


def test_a_footprint_outside_what_the_generator_stated_is_a_blocking_discrepancy_with_both_places():
    def lie(candidate):
        t = next(t for t in candidate.towers if t.name == "T2")
        t.footprint = shape(box(0, 0, 10, 10))
    d = _discrepancy(fixture("rectangle").edited(lie).report(), "footprint T2")
    assert d.blocks_pass and "m² at (" in d.theirs and "differ" in d.ours
