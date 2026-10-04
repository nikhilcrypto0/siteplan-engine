"""The LEGACY strategy reproduces the pinned Dhulapally debug baseline (C1).

Client data: the survey, the firm's libraries and the pinned numbers all live in the gitignored
fixtures/, so this skips on a clean clone. The inputs are the project the baseline run saved,
split into the contracts; the starting floors are worked out from the law's metres, not read from
that project; and what is compared is built by client_baseline.summarise, the function that
pinned the baseline in the first place.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from client_baseline import BASELINE, PINNED, READINGS, WORKSPACE, summarise
from contract_fixtures.rules_and_envelope import resolved_rules

from siteplan.adapters import option_keys, split_project
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT, WhenOpen
from siteplan.intake import load_defaults
from siteplan.library import FlatLibrary
from siteplan.optimizer import LegacyStrategy, SearchContext
from siteplan.project import Project
from siteplan.site_amenities import AmenityLibrary

TEST_CLASS = "characterization"

FIXTURES = Path(__file__).parent.parent / "fixtures"
pytestmark = pytest.mark.skipif(
    not (PINNED.exists() and (WORKSPACE / "siteplan.workspace.json").exists()),
    reason="client fixtures (the pinned Dhulapally baseline) not present")


@pytest.fixture(scope="module", params=list(READINGS))
def wrapped(request):
    """The wrapped strategy run on the project the baseline was pinned from."""
    reading = request.param
    saved = BASELINE / reading / "project.json"
    if not saved.exists():
        pytest.skip(f"{saved.name} of the {reading} baseline is not present")
    project = Project.model_validate_json(saved.read_text())
    site, brief, readings = split_project(project)
    rules = resolved_rules(site)
    # The baseline plans in the conservative test mode: whose rules apply is not established.
    rules = rules.model_copy(update={"jurisdiction": rules.jurisdiction.model_copy(
        update={"when_open": WhenOpen.CONSERVATIVE if readings.when_open is WhenOpen.CONSERVATIVE
                else WhenOpen.STOP})})
    defaults = load_defaults(WORKSPACE)
    library = FlatLibrary.model_validate_json((WORKSPACE / defaults.flat_library).read_text())
    amenities = AmenityLibrary.model_validate_json(
        (WORKSPACE / defaults.amenities).read_text()) if defaults.amenities else None
    strategy = LegacyStrategy(library, amenities, readings=readings.selections)
    return reading, project, brief, strategy.run(SearchContext(site, rules, brief))


def test_the_wrapped_run_is_the_pinned_baseline(wrapped):
    reading, _, brief, run = wrapped
    mix = brief.program.unit_mix.value
    options = [{**option_keys(c, i, mix), "strategy": c.pareto_tag}
               for i, c in enumerate(run.proposal.candidates, 1)]
    got = summarise(SimpleNamespace(found=run.found, options=options))
    assert got == json.loads(PINNED.read_text())["readings"][reading]


def test_the_starting_floors_come_from_the_law_and_agree_with_the_baselines_project(wrapped):
    """The baseline's project says 9 floors (the stilt counted) or 10 (not counted); the run
    here was given no number and worked out the same from 30 m of rule height."""
    reading, project, _, run = wrapped
    assert run.request.floors == project.layout.floors == (9 if reading == "counted" else 10)
    assert run.request.stilt_in_rule_height is (reading == "counted")
    assert run.found.max_legal_floors == run.request.floors


def test_every_candidate_names_the_reading_it_was_made_under(wrapped):
    reading, _, _, run = wrapped
    assert run.proposal.candidates
    for made in run.proposal.candidates:
        assert made.interpretation_basis[STILT_IN_RULE_HEIGHT] == reading
        assert made.strategy == "LEGACY"
