"""The validator on what the prototype generator really produces for the firm's Dhulapally site
(the pinned debug run, both readings of the stilt; client data, so it skips on a clean clone).

The generator checks itself with today's checker and calls its options passing. The validator,
which recomputes everything from the site model, must find no FAIL in them and must agree with
today's checker rule by rule, except where it sees an open reading the generator did not.
Characterization: it pins today's agreement on a real site."""

from pathlib import Path

import pytest
from client_baseline import ANSWERS, SURVEY, profile_path
from contract_fixtures.rules_and_envelope import resolved_rules

from siteplan.contracts import digest
from siteplan.contracts.common import Status

TEST_CLASS = "characterization"
FIXTURES = Path(__file__).parent.parent / "fixtures"
WORKSPACE = FIXTURES / "workspace"

pytestmark = pytest.mark.skipif(
    not (ANSWERS.exists() and profile_path("counted").exists() and SURVEY.exists()),
    reason="client fixtures not present")

# Where the validator is stricter than today's checker on these options, and why.
STRICTER = {
    ("not_counted", "Peripheral green strip"):
        "planned as if the stilt is not counted, the options draw no strip; if it counts the "
        "setback reaches 9 m and a strip is asked for, so the validator says UNVERIFIED naming "
        "the reading where the checker, which knows only the one it planned for, says INFO",
}


@pytest.fixture(scope="module", params=["counted", "not_counted"])
def real_run(request, tmp_path_factory):
    from client_baseline import run

    from siteplan.adapters import Readings, brief, candidate_from_option, site_model
    from siteplan.intake import load_defaults
    from siteplan.project import Project
    from siteplan.runner import read_survey

    generated = run(request.param, tmp_path_factory.mktemp(request.param))
    project = Project.model_validate(generated.project)
    site = site_model(project, site_id="dhulapally", boundary=read_survey(SURVEY).boundary,
                      draft=generated.draft)
    design = brief(project, load_defaults(WORKSPACE))
    rules = resolved_rules(site)
    readings = Readings.of(project.layout)
    refs = {"site_ref": digest(site), "rules_ref": digest(rules), "brief_ref": digest(design)}
    candidates = [candidate_from_option(
        option, generated.plot, candidate_id=f"real-{n}", readings=readings.selections,
        access_side=project.site.access_side, **refs)
        for n, option in enumerate(generated.found.options, 1)]
    return request.param, site, rules, design, candidates


def test_the_real_options_have_nothing_the_validator_fails(real_run):
    from siteplan.validator import validate

    _, site, rules, design, candidates = real_run
    assert len(candidates) >= 3
    for candidate in candidates:
        report = validate(site, rules, design, candidate)
        failed = [c.finding.rule for c in report.legal if c.finding.status is Status.FAIL]
        assert failed == [], (candidate.candidate_id, failed)
        assert [d.item for d in report.cross_checks if d.blocks_pass] == []
        assert report.verdict.legal.value == "UNVERIFIED"  # the 45 t loading alone sees to that


def test_the_validator_agrees_with_todays_checker_on_the_real_options(real_run):
    from siteplan.validator import validate

    reading, site, rules, design, candidates = real_run
    for candidate in candidates:
        ours = {c.finding.rule: c.finding.status for c in validate(
            site, rules, design, candidate).legal}
        for claim in candidate.generator_claims:
            if (reading, claim.rule) in STRICTER or claim.status is Status.INFO:
                continue
            assert ours.get(claim.rule) is claim.status, (reading, claim.rule)


def test_each_listed_stricter_verdict_is_real(real_run):
    from siteplan.validator import validate

    reading, site, rules, design, candidates = real_run
    for rule_reading, rule in STRICTER:
        if rule_reading != reading:
            continue
        seen = [c.finding.status for cand in candidates for c in validate(
            site, rules, design, cand).legal if c.finding.rule == rule]
        assert Status.UNVERIFIED in seen  # at least one real option shows the difference
