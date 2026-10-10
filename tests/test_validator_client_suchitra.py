"""The validator on a second real site: the firm's Suchitra, where a nala crosses the plot (client
data, so it skips on a clean clone).

Dhulapally has no water; Suchitra's nala takes 702 m² of the plot as the rule 3(a)(ii) buffer. The
validator rebuilds that buffer from the site model, and must find nothing to fail in what the
generator makes round it, and fail a tower that stands in it. Characterization: it pins today's
agreement on a real site, and a defect found on it (a tower off the plot at the Table IV seam)."""

from pathlib import Path

import pytest
from contract_fixtures import with_raise
from contract_fixtures.rules_and_envelope import resolved_rules
from validator_helpers import move_tower

from siteplan.contracts import digest
from siteplan.contracts.common import Line, Status
from siteplan.contracts.resolved_rules import OPENS_ONTO_ROAD, STILT_IN_RULE_HEIGHT

TEST_CLASS = "characterization"
WORKSPACE = Path(__file__).parent.parent / "fixtures" / "workspace"
SURVEY = WORKSPACE / "suchitra_survey.pdf"
PROJECT = WORKSPACE / "suchitra.project.json"
STATED = Path(__file__).parent.parent / "examples" / "amenities.hyderabad.json"

pytestmark = pytest.mark.skipif(not (SURVEY.exists() and PROJECT.exists()),
                                reason="client fixtures not present")

# The 12.4 m road serves 24 m: stilt + 7 if the stilt counts, stilt + 8 if it does not.
LAYOUTS = {"counted": {"floors": 7}, "not_counted": {"floors": 8, "stilt_in_rule_height": False}}
SILL_M2 = 0.01  # the buffer the validator builds may differ from the generator's by this much

# Where the validator says UNVERIFIED and today's checker says PASS, and why.
# Rules today's checker reads one way where the validator evaluates more than one reading:
# compared under the reading the checker takes.
AS_THE_CHECKER_READS = {
    "Internal roads: every block served": (OPENS_ONTO_ROAD, "touch"),
    "Internal roads: blocks up to 12 m (pathways)": (OPENS_ONTO_ROAD, "touch"),
}
STRICTER = {
    "Abutting road width (for T1)":
        "the 12.4 m is a value read off the drawing and never confirmed; the checker takes it as "
        "given, the validator will not settle a width nobody confirmed",
}


# Cross-checks the validator blocks on a run planned for one reading of the stilt, and why.
STRICTER_CROSS_CHECKS = {
    ("not_counted", "open space"):
        "planned with the stilt left out of the height; if it counts, stilt + 8 is 27.15 m from "
        "the ground (the stilt floor 0.15 m up, NBC Part 3 12.1.2) and asks Table IV's 10 m, so "
        "part of the open space the generator counted lies in that setback; the validator counts "
        "what holds under every reading",
}


def _planned(check, reading) -> bool:
    """Whether the validator's verdict under the reading the generator planned for is its own."""
    return check is not None and check.by_reading.get(STILT_IN_RULE_HEIGHT, {}).get(reading)


@pytest.fixture(scope="module", params=sorted(LAYOUTS))
def suchitra(request):
    from siteplan.adapters import Readings, brief, candidate_from_option, site_model
    from siteplan.intake import load_defaults
    from siteplan.library import FlatLibrary
    from siteplan.project import Project
    from siteplan.runner import load_plot, load_water, read_survey, run_search
    from siteplan.site_amenities import AmenityLibrary

    project = Project.model_validate_json(PROJECT.read_text())
    project = project.model_copy(update={"layout": project.layout.model_copy(update={
        "conservative_parking": True, "maximise": True, **LAYOUTS[request.param]})})
    plot, _ = load_plot(project, SURVEY)
    keep_out, _ = load_water(project, SURVEY)
    defaults = load_defaults(WORKSPACE)
    facilities = AmenityLibrary.model_validate_json((WORKSPACE / defaults.amenities).read_text())
    found = run_search(
        project, FlatLibrary.model_validate_json((WORKSPACE / defaults.flat_library).read_text()),
        plot, project.layout, facilities, keep_out)
    ring = [list(p) for p in list(plot.exterior.coords)[:-1]]
    project = project.model_copy(update={"site": project.site.model_copy(
        update={"net_plot_m": ring})})
    site = site_model(project, site_id="suchitra", boundary=read_survey(SURVEY).boundary)
    drawn = list(read_survey(SURVEY, project.site.water[0]).water)
    site.water[0].lines = [Line(points=[tuple(c) for c in line.coords]) for line in drawn]
    # The brief states each facility's use and surface, as a firm's library does: the firm's own
    # file does not yet, so the same items as the repo's researched list states them (its own
    # statements, assumed for the test, never read off a name).
    stated = AmenityLibrary.model_validate_json(STATED.read_text())
    design = brief(project, defaults, amenities=stated)
    rules = with_raise(resolved_rules(site))  # today's rules: heights from the ground
    readings = Readings.of(project.layout)
    refs = {"site_ref": digest(site), "rules_ref": digest(rules), "brief_ref": digest(design)}
    candidates = [candidate_from_option(
        option, plot, candidate_id=f"suchitra-{n}", readings=readings.selections,
        access_side=project.site.access_side, keep_out=keep_out, amenities=stated, **refs)
        for n, option in enumerate(found.options, 1)]
    return request.param, plot, keep_out, site, rules, design, candidates


def test_the_validators_water_buffer_is_the_one_the_generator_keeps_clear(suchitra):
    from siteplan.validator import site_geometry

    _, plot, keep_out, site, rules, *_ = suchitra
    ours = site_geometry.build(site, rules).keep_out_on_site
    assert ours.area == pytest.approx(701.6, abs=0.1)  # the nala's buffer, G.O.168 rule 3(a)(ii)
    assert ours.symmetric_difference(plot.intersection(keep_out)).area < SILL_M2


def test_the_real_options_have_nothing_the_validator_fails(suchitra):
    from siteplan.validator import validate

    reading, _, _, site, rules, design, candidates = suchitra
    assert candidates
    allowed = {item for r, item in STRICTER_CROSS_CHECKS if r == reading}
    blocked = set()
    for candidate in candidates:
        report = validate(site, rules, design, candidate)
        failed = [c.finding.rule for c in report.legal if c.finding.status is Status.FAIL]
        assert failed == [], (candidate.candidate_id, failed)
        blocks = {d.item for d in report.cross_checks if d.blocks_pass}
        blocked |= blocks
        # a blocking cross-check fails the verdict; else the unconfirmed road, the 45 t loading
        assert report.verdict.legal.value == ("FAIL" if blocks else "UNVERIFIED")
    assert blocked == allowed  # each listed one is real, and nothing else blocks


def test_the_validator_agrees_with_todays_checker_on_the_real_options(suchitra):
    from siteplan.validator import validate

    planned, _, _, site, rules, design, candidates = suchitra
    for candidate in candidates:
        ours = {c.finding.rule: c for c in validate(site, rules, design, candidate).legal}
        for claim in candidate.generator_claims:
            if claim.rule in STRICTER or claim.status is Status.INFO:
                continue
            c = ours.get(claim.rule)
            if claim.rule in AS_THE_CHECKER_READS and c is not None:
                interpretation, reading = AS_THE_CHECKER_READS[claim.rule]
                assert c.by_reading[interpretation][reading] is claim.status, claim.rule
            elif c is None or c.finding.status is not claim.status:
                # the checker knows only the reading it planned for; the validator weighs both
                assert _planned(c, planned) is claim.status, claim.rule


def test_without_the_surfaces_of_its_facilities_the_open_space_is_unverified_not_passed(suchitra):
    """The options stand a children's play area and seating on the tot-lot and count them. Whether
    they are greenery is the brief's to say; a brief that does not leaves the share unsettled."""
    from siteplan.validator import validate

    _, _, _, site, rules, design, candidates = suchitra
    bare = design.model_copy(deep=True)
    bare.program.amenities = []
    seen = []
    for candidate in candidates:
        again = candidate.model_copy(update={"brief_ref": digest(bare)})
        report = validate(site, rules, bare, again)
        space = next(c for c in report.legal if c.finding.rule == "Organized open space (tot-lot)")
        seen.append(space.finding.status)
        if space.finding.status is Status.UNVERIFIED:
            assert "CHILDRENS PLAY" in space.finding.note
    assert Status.UNVERIFIED in seen


def test_a_tower_pushed_into_the_nala_buffer_fails_the_water_check(suchitra):
    from siteplan.validator import site_geometry, validate

    _, _, _, site, rules, design, candidates = suchitra
    spot = site_geometry.build(site, rules).keep_out_on_site.representative_point()
    candidate = candidates[0].model_copy(deep=True)
    tower = candidate.towers[0]
    centre = candidate.placed_footprint(tower).centroid
    move_tower(candidate, tower.name, spot.x - centre.x, spot.y - centre.y)
    report = validate(site, rules, design, candidate)
    water = [c for c in report.legal if c.finding.rule == "Water-body buffer"]
    assert [c.finding.status for c in water] == [Status.FAIL]
    assert report.verdict.legal.value == "FAIL"


def test_a_tower_off_the_plot_fails_its_setback_even_at_the_table_seam(suchitra):
    """Found on this site: the tower is 24 m with its stilt, so exactly 21 m, the high-rise
    threshold, if the stilt is not counted. A short setback there is only UNVERIFIED (the row
    above is an upper bound), but a block that is not on the plot meets no row of any table."""
    from siteplan.validator import validate

    _, plot, _, site, rules, design, candidates = suchitra
    candidate = candidates[0].model_copy(deep=True)
    tower = candidate.towers[0]
    tower.floors_above_stilt = 7  # 24.15 m with the stilt, so exactly 21 m without: the seam
    centre = candidate.placed_footprint(tower).centroid
    move_tower(candidate, tower.name, plot.bounds[2] + 80.0 - centre.x, 0.0)
    report = validate(site, rules, design, candidate)
    setback = [c for c in report.legal if c.finding.rule == f"All-round setback: {tower.name}"]
    assert [c.finding.status for c in setback] == [Status.FAIL]
