"""What the optimizer core makes of the generator's layouts today (C1).

These pin labels that follow from the generator's own choices (its three massings, which layouts
it finds on made-up land), so they are kept to catch unintended change and move only with a
normative replacement (tests/MANIFEST.md). The rules they rest on are in the other optimizer
tests.
"""

from optimizer_support import LIBRARY, fixture, generators_layouts, legacy_run

from siteplan.contracts.design_brief import ParetoPoint
from siteplan.optimizer import LegacyStrategy, optimize
from siteplan.optimizer.objective import measure
from siteplan.optimizer.pareto import Scored, select

TEST_CLASS = "characterization"

SITE, RULES, BRIEF = fixture()


def _scored(candidates, brief):
    return [Scored(c, measure(c, brief)) for c in candidates]


def test_on_the_generators_own_three_massings_the_points_land_on_the_same_three():
    """The generator's A (maximum yield), B (balanced) and C (conventional smaller towers) at
    one height: the optimizer's three points choose the same three layouts."""
    _, candidates = generators_layouts()
    eight = [c for c in candidates if c.towers[0].floors_above_stilt == 8]  # stilt + 9: 30.15 m
    assert len(eight) == 3
    by_point = {p.point: p.scored.candidate.pareto_tag
                for p in select(_scored(eight, BRIEF), BRIEF).picks}
    assert by_point == {ParetoPoint.MAX_YIELD: "Option A: Maximum yield",
                        ParetoPoint.BALANCED: "Option B: Balanced development",
                        ParetoPoint.CONVENTIONAL_OPEN_SPACE:
                            "Option C: Conventional smaller towers"}


def test_the_rectangle_through_the_core_gives_the_generators_three_massings_in_order():
    result = optimize(SITE, RULES, BRIEF, [LegacyStrategy(LIBRARY)])
    assert [(a.point, a.candidate.candidate_id) for a in result.alternatives] == [
        (ParetoPoint.MAX_YIELD, "legacy-counted-not_allowed-1"),
        (ParetoPoint.BALANCED, "legacy-counted-not_allowed-2"),
        (ParetoPoint.CONVENTIONAL_OPEN_SPACE, "legacy-counted-not_allowed-3")]


def test_two_layouts_the_generator_ties_on_yield_are_labelled_by_what_each_is_for():
    """On the nala plot the generator's A and C are one single-core tower each, with the same
    flats and so the same yield; C keeps 241 m² more open space and leaves less ground to no use,
    but its tower only grazes the loop road's rounded corner (3 m of frontage, short of a
    pathway's 6 m) where A's faces it along a long side. Before C4-11 the maximum-yield label went
    to A and the open-space one to C; now the equal yields go to the layout that uses its ground
    (C), and the open-space label to the plainer scheme (A, whose quality outweighs the open
    space)."""
    site, rules, brief = fixture("nala_plot")
    run = legacy_run("nala_plot", maximise=False)
    a, c = run.proposal.candidates
    assert (a.pareto_tag, c.pareto_tag) == ("Option A: Maximum yield",
                                            "Option C: Conventional smaller towers")
    assert measure(a, brief).yield_score == measure(c, brief).yield_score
    assert measure(c, brief).open_space_sqm > measure(a, brief).open_space_sqm
    picks = select(_scored(run.proposal.candidates, brief), brief)
    assert {p.point: p.scored.candidate.pareto_tag for p in picks.picks} == {
        ParetoPoint.MAX_YIELD: "Option C: Conventional smaller towers",
        ParetoPoint.CONVENTIONAL_OPEN_SPACE: "Option A: Maximum yield"}
    assert [point for point, _ in picks.unfilled] == [ParetoPoint.BALANCED]
