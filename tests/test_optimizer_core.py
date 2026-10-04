"""The optimizer core end to end (C1): deterministic for a seed, within a time budget, every
alternative judged in the form it is returned. Made-up land and candidates only."""

import random
from itertools import combinations

import pytest
from optimizer_support import (
    LIBRARY,
    Clock,
    Fixed,
    Scripted,
    candidate,
    fixture,
    module_prototype,
    refs_of,
    tower,
)

from siteplan.contracts import digest
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import (
    HeightMode,
    Objectives,
    ParetoPoint,
    UnitsMode,
    UnitTarget,
)
from siteplan.contracts.validation import LegalVerdict
from siteplan.optimizer import (
    InterimValidator,
    LegacyStrategy,
    Proposal,
    SearchContext,
    optimize,
)
from siteplan.optimizer.pareto import same_idea

TEST_CLASS = "normative"

P1, P2 = module_prototype(1), module_prototype(2)
SITE, RULES, BRIEF = fixture()


def _brief(**objectives):
    return BRIEF.model_copy(update={"objectives": Objectives(**objectives)})


def _made(candidate_id, floors, open_space, *, towers=2, proto=P2, brief=BRIEF, **kwargs):
    """A candidate made for the brief it will be judged against: one made for another is
    refused as stale."""
    return candidate(
        candidate_id, [tower(f"T{n}", proto, 30 + 40 * n, 20 + 25 * n, floors)
                       for n in range(towers)], [proto], open_space_sqm=open_space,
        refs=refs_of(SITE, RULES, brief), **kwargs)


class Scatter:
    """A strategy that draws its candidates at random, the way a search would, from the seed."""

    name = "SCATTER"

    def propose(self, context):
        rng = context.rng("scatter")
        made = []
        for i in range(8):
            proto = rng.choice([P1, P2])
            towers = [tower(f"T{n}", proto, rng.uniform(20, 130), rng.uniform(15, 85),
                            rng.randint(5, 9), rng.choice([0.0, 90.0]))
                      for n in range(rng.randint(1, 4))]
            made.append(candidate(f"scatter-{i}", towers, [proto], open_space_sqm=rng.uniform(
                100, 3000), refs=refs_of(context.site, context.rules, context.brief),
                strategy=self.name))
        return Proposal(self.name, tuple(made))


# --- deterministic for a seed -----------------------------------------------------------------


def test_the_same_seed_gives_the_same_result_whatever_the_global_random_state():
    random.seed(1)
    first = optimize(SITE, RULES, BRIEF, [Scatter()], seed=7)
    random.seed(2)
    again = optimize(SITE, RULES, BRIEF, [Scatter()], seed=7)
    assert first == again and first.alternatives and first.seed == 7


def test_another_seed_gives_other_candidates():
    a = optimize(SITE, RULES, BRIEF, [Scatter()], seed=7)
    b = optimize(SITE, RULES, BRIEF, [Scatter()], seed=8)
    assert [alt.candidate for alt in a.alternatives] != [alt.candidate for alt in b.alternatives]


def test_a_strategys_streams_are_its_own_and_follow_the_seed():
    context = SearchContext(SITE, RULES, BRIEF, seed=3)
    assert context.rng("a").random() == context.rng("a").random()
    assert context.rng("a").random() != context.rng("b").random()
    assert context.rng().random() != SearchContext(SITE, RULES, BRIEF, seed=4).rng().random()


def test_the_generator_run_through_the_core_is_the_same_every_time():
    brief = _brief()
    strategies = [LegacyStrategy(LIBRARY)]
    first = optimize(SITE, RULES, brief, strategies, seed=0)
    assert first == optimize(SITE, RULES, brief, strategies, seed=0)
    assert first.alternatives


# --- the time budget ---------------------------------------------------------------------------


def test_a_strategy_the_budget_has_no_time_for_is_not_started_and_the_rest_is_still_judged():
    clock = Clock(step=0.0)
    brief = _brief(search_budget_s=15)
    slow = [Fixed([_made(f"s{i}", 9 - i, 300 * (i + 1), towers=i + 1, brief=brief)],
                  name=f"S{i}", clock=clock, takes=10.0) for i in range(3)]
    result = optimize(SITE, RULES, brief, slow, clock=clock)
    assert result.budget_exhausted
    assert "S2: not run, the time budget was spent" in result.notes
    assert result.considered == 2  # the first two ran; the third was never started
    assert {a.candidate.candidate_id for a in result.alternatives} == {"s0", "s1"}
    assert not result.rejected  # what was found so far is returned, judged


def test_a_strategy_that_stopped_early_says_so_and_the_core_passes_it_on():
    stopped = Fixed([_made("a", 9, 300)], name="HALF", notes=("stopped on the budget",),
                    exhausted=True)
    result = optimize(SITE, RULES, BRIEF, [stopped])
    assert result.budget_exhausted and "HALF: stopped on the budget" in result.notes
    assert [a.candidate.candidate_id for a in result.alternatives] == ["a"]


def test_the_budget_bounds_the_search_not_the_judging_so_nothing_found_goes_unjudged():
    """The search spent the whole budget; every candidate it found is still judged, because
    nothing is returned unjudged (and so judging cannot be cut short)."""
    clock = Clock(step=0.0)
    validator = Scripted(clock=clock, takes=100.0)  # judging is slow, and the budget is gone
    brief = _brief(search_budget_s=5)
    pool = [_made(f"c{i}", floors=9 - i, open_space=300, towers=i + 1, brief=brief)
            for i in range(4)]
    greedy = Fixed(pool, clock=clock, takes=50.0)  # one unit of work overruns the budget
    result = optimize(SITE, RULES, brief, [greedy], validator=validator, clock=clock)
    assert result.budget_exhausted is False  # the search was not cut short: it was one unit
    assert sorted(set(validator.calls)) == ["c0", "c1", "c2", "c3"]
    assert result.alternatives and not result.rejected


def test_the_budget_is_the_briefs_and_no_budget_means_no_limit():
    clock = Clock(step=0.0)
    slow = [Fixed([_made(f"s{i}", 9 - i, 300 * (i + 1), towers=i + 1)], name=f"S{i}",
                  clock=clock, takes=1000.0) for i in range(3)]
    result = optimize(SITE, RULES, BRIEF, slow, clock=clock)  # the brief sets none
    assert not result.budget_exhausted and result.considered == 3


def test_a_real_clock_budget_stops_a_real_search_early_and_says_so():
    brief = _brief(search_budget_s=1e-6)
    brief = brief.model_copy(update={"height_intent": brief.height_intent.model_copy(
        update={"mode": HeightMode.MAX_LEGAL})})
    result = optimize(SITE, RULES, brief, [LegacyStrategy(LIBRARY)])
    assert result.budget_exhausted and result.alternatives == ()
    assert any("time budget" in note for note in result.notes)


# --- every alternative is judged as returned -----------------------------------------------------


def test_each_alternative_carries_its_scores_its_tag_and_a_report_of_exactly_that_candidate():
    pool = [_made("slabs", 9, 300), _made("mid", 9, 1200, towers=3, proto=P1),
            _made("singles", 5, 2400, towers=5, proto=P1)]
    result = optimize(SITE, RULES, BRIEF, [Fixed(pool)])
    assert [a.point for a in result.alternatives] == [
        ParetoPoint.MAX_YIELD, ParetoPoint.BALANCED, ParetoPoint.CONVENTIONAL_OPEN_SPACE]
    for a in result.alternatives:
        assert a.candidate.pareto_tag == a.point.value
        assert {"saleable_sqft", "units", "open_space_sqm", "mix_fit", "conventionality",
                "towers", "yield_score"} <= set(a.candidate.scores)
        assert a.report.candidate_ref == digest(a.candidate)  # the final form, tagged and scored
        assert a.report.verdict.legal is not LegalVerdict.FAIL
    for a, b in combinations([alt.candidate for alt in result.alternatives], 2):
        assert not same_idea(a, b)
    assert set(result.front) == {"slabs", "mid", "singles"}


def test_the_generators_own_scores_are_kept_beside_ours():
    made = _made("a", 9, 300)
    made = made.model_copy(update={"scores": {"score": 123.0}})
    (alternative,) = optimize(SITE, RULES, BRIEF, [Fixed([made])]).alternatives
    assert alternative.candidate.scores["score"] == 123.0
    assert alternative.candidate.scores["yield_score"] > 0


def test_a_validator_that_contradicts_itself_gets_nothing_returned():
    """Judged PASS when the pool is guarded and FAIL when the returned form is judged."""
    validator = Scripted({"flaky": (Status.PASS, Status.FAIL)})
    pool = [_made("flaky", 9, 300), _made("steady", 8, 1200, towers=3, proto=P1)]
    result = optimize(SITE, RULES, BRIEF, [Fixed(pool)], validator=validator)
    assert "flaky" not in {a.candidate.candidate_id for a in result.alternatives}
    assert [r.candidate_id for r in result.rejected] == ["flaky"]


def test_the_interim_validator_is_the_default_and_a_validator_can_be_given():
    pool = [_made("a", 9, 300)]
    default = optimize(SITE, RULES, BRIEF, [Fixed(pool)])
    explicit = optimize(SITE, RULES, BRIEF, [Fixed(pool)], validator=InterimValidator())
    assert default == explicit
    scripted = optimize(SITE, RULES, BRIEF, [Fixed(pool)], validator=Scripted())
    assert scripted.alternatives[0].report.validator_version == "scripted test validator"


def test_two_strategies_may_not_use_one_candidate_id():
    with pytest.raises(ValueError, match="repeated: \\['same'\\]"):
        optimize(SITE, RULES, BRIEF, [Fixed([_made("same", 9, 300)], name="A"),
                                      Fixed([_made("same", 8, 300)], name="B")])


def test_no_strategy_and_no_candidate_give_an_empty_answer_not_an_error():
    nothing = optimize(SITE, RULES, BRIEF, [])
    assert nothing.alternatives == () and nothing.considered == 0 and not nothing.budget_exhausted
    assert {why for _, why in nothing.unfilled} == {"no candidate passed"}


def test_what_a_strategy_says_about_its_run_comes_back_with_its_name():
    result = optimize(SITE, RULES, BRIEF, [Fixed([], name="QUIET", notes=("nothing fits",))])
    assert result.notes == ("QUIET: nothing fits",)


def test_a_unit_target_the_objective_does_not_use_yet_is_said():
    target = BRIEF.program.model_copy(update={"units": UnitTarget(
        mode=UnitsMode.TARGET, target=300)})
    brief = BRIEF.model_copy(update={"program": target})
    result = optimize(SITE, RULES, brief, [])
    assert any("unit target" in note for note in result.notes)
    assert not any("unit target" in note for note in optimize(SITE, RULES, BRIEF, []).notes)


# --- the generator through the core ------------------------------------------------------


def test_every_reading_of_the_stilt_is_run_and_the_pool_keeps_them_apart():
    strategies = LegacyStrategy.for_readings(RULES, LIBRARY)
    result = optimize(SITE, RULES, BRIEF, strategies)
    assert result.considered >= 4 and result.alternatives
    basis = {(a.candidate.interpretation_basis["stilt_in_rule_height"],
              a.candidate.interpretation_basis["circulation_in_setback"])
             for a in result.alternatives}
    assert basis <= {("counted", "allowed"), ("counted", "not_allowed"),
                     ("not_counted", "allowed"), ("not_counted", "not_allowed")}
    for a in result.alternatives:
        assert a.candidate.candidate_id.startswith("legacy-")
        assert a.report.verdict.legal is LegalVerdict.UNVERIFIED  # interim: never a PASS
