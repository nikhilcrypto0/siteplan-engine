"""The full search on the firm's two real sites, held to the independent validator (client data).

Dhulapally is the pinned debug run (the firm's net outline fitted onto its survey, so a DEBUG run
and never evidence for a rule); Suchitra is its survey with the nala's buffer kept clear. Both
skip on a clean clone, because the survey, the answers and the firm's libraries live in the
gitignored fixtures/. What is asserted is what the strategy promises, never a number: that it
finds layouts, that nothing the validator fails or blocks is offered, that the alternatives it
hands back are different ideas, that a block is never taller than the law lets it be under the
readings it states, and that the strategy says which readings each layout rests on. The yields
side by side with LEGACY are printed by `tests/search_compare.py`, by hand: a yield is not a thing
to pin here.
"""

from __future__ import annotations

from itertools import combinations

import pytest
from client_baseline import ANSWERS, SURVEY, WORKSPACE
from search_compare import dhulapally, suchitra

from siteplan.contracts.common import SourceKind, Status
from siteplan.contracts.validation import LegalVerdict
from siteplan.optimizer import optimize
from siteplan.optimizer.guard import inputs_of, why_refused
from siteplan.optimizer.pareto import same_idea
from siteplan.optimizer.search import FullSearchStrategy
from siteplan.optimizer.search.verdicts import rests_on
from siteplan.prototypes import compose_library

TEST_CLASS = "normative"

SITES = {
    "dhulapally": (dhulapally, (SURVEY, ANSWERS)),
    "suchitra": (suchitra, (WORKSPACE / "suchitra_survey.pdf",
                            WORKSPACE / "suchitra.project.json")),
}


def _present(name: str) -> bool:
    return all(path.exists() for path in SITES[name][1])


@pytest.fixture(scope="module", params=sorted(SITES))
def run(request):
    """The full search on one real site through `optimize`, the independent validator judging."""
    name = request.param
    if not _present(name):
        pytest.skip(f"the {name} fixtures are not present")
    site, rules, design, envelope, library, _ = SITES[name][0]()
    kit = compose_library(library, design.program.unit_mix.value,
                          source_kind=SourceKind.FIRM_STANDARD)
    result = optimize(site, rules, design, [FullSearchStrategy()], envelope=envelope,
                      prototypes=kit)
    return name, (site, rules, design, envelope), result


def test_the_search_finds_layouts_on_the_real_site(run):
    name, _, result = run
    assert 1 <= len(result.alternatives) <= 3, name
    assert all(a.candidate.strategy == "FULL" for a in result.alternatives)


def test_nothing_the_validator_fails_is_offered_and_nothing_proposed_was_refused(run):
    name, (site, rules, design, _), result = run
    assert not result.rejected, (name, [r.reasons for r in result.rejected])
    inputs = inputs_of(site, rules, design)
    for alternative in result.alternatives:
        report = alternative.report
        assert why_refused(alternative.candidate, report, inputs) == [], name
        assert report.verdict.legal is not LegalVerdict.FAIL, name
        assert not [c for c in report.legal if c.finding.status is Status.FAIL], name
        assert not [d for d in report.cross_checks if d.blocks_pass], name


def test_the_alternatives_are_different_ideas(run):
    name, _, result = run
    for a, b in combinations(result.alternatives, 2):
        assert not same_idea(a.candidate, b.candidate), (name, a.candidate.candidate_id,
                                                         b.candidate.candidate_id)


def test_every_alternative_states_what_it_rests_on(run):
    """A layout is offered with its open items named; one that rests on a reading says which."""
    name, _, result = run
    for alternative in result.alternatives:
        rests = rests_on(alternative.report)
        candidate = alternative.candidate
        assert candidate.interpretation_basis, name
        if not rests.holds_under_every_reading:
            assert rests.readings, (name, candidate.candidate_id)
        assert candidate.caveats, (name, candidate.candidate_id)


def test_the_search_stays_inside_the_ground_it_was_given(run):
    """Every tower and the club house stand on the plot's net outline."""
    name, (site, *_), result = run
    net = site.net_plot.value.to_shapely().buffer(0.01)
    for alternative in result.alternatives:
        candidate = alternative.candidate
        stands = [(tower.name, tower.footprint) for tower in candidate.towers]
        if candidate.program.club_house:
            stands.append(("club house", candidate.program.club_house.shape))
        for what, shape in stands:
            assert shape.to_shapely().difference(net).area < 0.5, (name, candidate.candidate_id,
                                                                     what)
