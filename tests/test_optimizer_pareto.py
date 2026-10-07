"""The objective, the Pareto front and the three alternatives (C1): each from the candidate's own
prototypes and placements, each alternative a genuinely different idea. Made-up land only."""

import random
from itertools import combinations

import pytest
from optimizer_support import candidate, fixture, generators_layouts, module_prototype, tower

from siteplan import layout
from siteplan.contracts.common import Sourced
from siteplan.contracts.design_brief import Objectives, ParetoPoint
from siteplan.optimizer import pareto as pareto_module
from siteplan.optimizer.objective import (
    AREA_DECIMALS,
    AXES,
    Scores,
    measure,
    mix_error,
    priority_weights,
)
from siteplan.optimizer.pareto import Scored, dominates, pareto_front, same_idea, select

TEST_CLASS = "normative"

P1, P2 = module_prototype(1), module_prototype(2)
SITE, RULES, BRIEF = fixture()  # unit mix 70% 2BHK, 30% 3BHK; the blocks below are 50/50
MIX_FIT = 0.8  # 1 less the half-gap between 50/50 and 70/30


def _scored(*candidates, brief=BRIEF):
    return [Scored(c, measure(c, brief)) for c in candidates]


def _brief(**objectives):
    return BRIEF.model_copy(update={"objectives": Objectives(**objectives)})


def _two_slabs(candidate_id, floors, open_space, *, at=((40, 20), (110, 75)), rotation=0.0):
    (x1, y1), (x2, y2) = at
    return candidate(candidate_id, [tower("T1", P2, x1, y1, floors, rotation),
                                    tower("T2", P2, x2, y2, floors, rotation)], [P2],
                     open_space_sqm=open_space)


def _pool():
    """Three different ideas, a near-copy of the first and the first turned a quarter."""
    yield_ = _two_slabs("yield", 9, 300)  # 2 two-core slabs, tallest, least open space
    balanced = candidate("balanced", [tower("T1", P2, 40, 20, 8), tower("T2", P1, 100, 20, 8),
                                      tower("T3", P1, 60, 75, 8)], [P1, P2], open_space_sqm=1200)
    conventional = candidate(
        "conventional", [tower(f"T{i}", P1, 25 + 25 * i, 20 + 12 * (i % 3), 5)
                         for i in range(5)], [P1], open_space_sqm=2400)  # 5 single cores
    near_copy = _two_slabs("near-copy", 8, 300, at=((42, 21), (108, 74)))
    turned = _two_slabs("turned", 8, 300, rotation=90.0)
    return [yield_, balanced, conventional, near_copy, turned]


# --- the objective: from the prototypes, never from the generator's claims --------------------


def test_saleable_area_units_and_conventionality_come_from_prototypes_and_floors():
    scores = measure(_two_slabs("a", 9, 300), BRIEF)
    assert scores.saleable_sqft == 2 * 2 * 5760 * 9  # two towers, two cores each, 9 floors
    assert scores.units == 2 * 8 * 9
    assert scores.conventionality == 0.5 and scores.towers == 2
    mixed = measure(candidate("m", [tower("T1", P2, 40, 20, 8), tower("T2", P1, 100, 20, 8)],
                              [P1, P2]), BRIEF)
    assert mixed.conventionality == pytest.approx((0.5 + 1.0) / 2)
    assert mixed.saleable_sqft == (11520 + 5760) * 8


def test_a_candidate_cannot_raise_its_own_score_through_its_metrics():
    honest = _two_slabs("a", 9, 300)
    liar = honest.model_copy(update={"metrics": {
        "total_flats": 9999, "saleable_sqft": 9e9, "tower_floor_sqft": 1, "flats_own_sqft": 1,
        "common_core_sqft": 1, "built_up_sqft": 1, "open_space_sqm": 9e9,
        "open_space_share_pct": 99, "mix_error": 0}})
    assert measure(liar, BRIEF) == measure(honest, BRIEF)


def test_the_mix_is_judged_against_the_brief_and_matches_the_generators_measure():
    assert measure(_two_slabs("a", 9, 300), BRIEF).mix_fit == pytest.approx(MIX_FIT)
    counts, target = {"2BHK": 10, "3BHK": 30, "4BHK": 10}, {"2BHK": 0.5, "3BHK": 0.5}
    assert mix_error(counts, target) == layout.mix_error(counts, target)
    assert mix_error({}, {"2BHK": 1.0}) == layout.mix_error({}, {"2BHK": 1.0})
    asked = BRIEF.program.model_copy(update={"unit_mix": Sourced[dict[str, float]](
        value={"2BHK": 0.5, "3BHK": 0.5}, status=BRIEF.program.unit_mix.status,
        source_kind=BRIEF.program.unit_mix.source_kind)})
    fifty = BRIEF.model_copy(update={"program": asked})
    assert measure(_two_slabs("a", 9, 300), fifty).mix_fit == 1.0  # 50/50 blocks, 50/50 brief


def test_the_generators_own_measures_are_the_same_numbers():
    options, candidates = generators_layouts()
    for option, made in zip(options, candidates, strict=True):
        scores = measure(made, BRIEF)
        assert scores.saleable_sqft == pytest.approx(option.saleable_sqft)
        assert scores.units == option.total_flats
        assert scores.mix_fit == pytest.approx(1 - option.mix_error)
        assert scores.yield_score == pytest.approx(option.score)
        assert scores.open_space_sqm == pytest.approx(  # the objective reads areas to 0.01 m²
            option.open_space_sqm, abs=10.0 ** -AREA_DECIMALS / 2)


def test_the_architects_priorities_are_weights_and_a_misspelt_one_is_refused():
    assert priority_weights(BRIEF) == (1.0,) * len(AXES)
    heavy = _brief(priorities={"open_space": 3.0})
    assert priority_weights(heavy)[AXES.index("open_space")] == 3.0
    with pytest.raises(ValueError, match="open_space"):  # the contract names the axes it takes
        _brief(priorities={"open-space": 3.0})
    with pytest.raises(ValueError, match="cannot be negative"):
        _brief(priorities={"units": -1.0})
    with pytest.raises(ValueError, match="not all zero"):
        priority_weights(_brief(priorities=dict.fromkeys(AXES, 0.0)))


# --- the front -------------------------------------------------------------------------------


def _scores(*vector) -> Scores:
    area, units, open_space, mix, conventionality = vector
    return Scores(area, units, open_space, mix, conventionality, towers=1)


def test_a_candidate_is_dominated_only_when_another_is_no_worse_everywhere_and_better_somewhere():
    best, worse, trade = _scores(10, 5, 5, 1, 1), _scores(9, 5, 5, 1, 1), _scores(11, 5, 1, 1, 1)
    assert dominates(best, worse) and not dominates(worse, best)
    assert not dominates(best, trade) and not dominates(trade, best)  # a trade-off, not a rank
    assert not dominates(best, best)  # equal is not better


def test_the_front_holds_the_candidates_nothing_dominates():
    pool = _scored(*_pool())
    front = pareto_front(pool)
    assert {s.candidate.candidate_id for s in front} >= {"yield", "balanced", "conventional"}
    for s in pool:
        if s not in front:  # each one left out has a better candidate on the front
            assert any(dominates(f.scores, s.scores) for f in front)
        else:
            assert not any(dominates(o.scores, s.scores) for o in pool)


# --- same idea: ported from the generator -----------------------------------------------------


def test_the_ported_thresholds_are_the_generators():
    assert pareto_module.SAME_IDEA_OVERLAP == layout.SAME_IDEA_OVERLAP == 0.5
    assert pareto_module.ANGLE_FAMILY_DEG == layout.ANGLE_FAMILY_DEG == 10.0


def test_one_idea_is_as_many_towers_running_the_same_way_on_mostly_the_same_ground():
    base = _two_slabs("base", 9, 300)
    assert same_idea(base, _two_slabs("moved a little", 8, 300, at=((42, 21), (108, 74))))
    assert not same_idea(base, _two_slabs("turned", 9, 300, rotation=90.0))
    assert not same_idea(base, _two_slabs("elsewhere", 9, 300, at=((240, 20), (310, 75))))
    one = candidate("one", [tower("T1", P2, 40, 20, 9)], [P2])
    assert not same_idea(base, one)  # a different number of towers
    assert same_idea(base, base)


def test_directions_within_ten_degrees_agree_across_the_half_turn():
    def one(angle):
        return candidate(f"a{angle}", [tower("T1", P2, 40, 20, 9, angle)], [P2])

    assert same_idea(one(5.0), one(-5.0))  # 10 degrees apart
    assert same_idea(one(175.0), one(5.0))  # 10 degrees apart through 180
    assert not same_idea(one(0.0), one(20.0))  # 20 degrees apart
    assert same_idea(one(0.0), one(180.0))  # the same line


def test_towers_are_paired_by_direction_not_by_the_order_they_are_listed():
    def mixed(first, second):
        return candidate("m", [tower("T1", P2, 40, 20, 9, first),
                               tower("T2", P2, 110, 75, 9, second)], [P2])

    assert same_idea(mixed(0.0, 90.0), mixed(0.0, 90.0))
    assert not same_idea(mixed(0.0, 90.0), mixed(0.0, 0.0))  # one runs across, the other along


def test_the_port_agrees_with_the_generators_on_its_own_layouts():
    """Every pair of the options the generator found at every height: the same answer."""
    options, candidates = generators_layouts()
    assert len(options) >= 6
    pairs = list(combinations(range(len(options)), 2))
    answers = [layout.same_idea(options[i], options[j]) for i, j in pairs]
    assert True in answers and False in answers  # both kinds of pair are in the test
    for (i, j), expected in zip(pairs, answers, strict=True):
        assert same_idea(candidates[i], candidates[j]) is expected, (i, j)


# --- the three alternatives --------------------------------------------------------------------


def test_three_alternatives_that_the_ported_same_idea_calls_different():
    selection = select(_scored(*_pool()), BRIEF)
    chosen = {pick.point: pick.scored.candidate for pick in selection.picks}
    assert set(chosen) == {ParetoPoint.MAX_YIELD, ParetoPoint.BALANCED,
                           ParetoPoint.CONVENTIONAL_OPEN_SPACE}
    assert chosen[ParetoPoint.MAX_YIELD].candidate_id == "yield"
    assert chosen[ParetoPoint.CONVENTIONAL_OPEN_SPACE].candidate_id == "conventional"
    assert chosen[ParetoPoint.BALANCED].candidate_id == "balanced"
    for a, b in combinations(chosen.values(), 2):
        assert not same_idea(a, b)
    assert not selection.unfilled
    # The near-copy of the maximum-yield layout is the next best on yield, and is passed over.
    assert "near-copy" not in {c.candidate_id for c in chosen.values()}


def test_the_alternatives_come_back_in_the_order_the_brief_lists_its_points():
    brief = _brief(pareto=[ParetoPoint.CONVENTIONAL_OPEN_SPACE, ParetoPoint.MAX_YIELD,
                           ParetoPoint.BALANCED])
    picks = select(_scored(*_pool(), brief=brief), brief).picks
    assert [p.point for p in picks] == [ParetoPoint.CONVENTIONAL_OPEN_SPACE,
                                        ParetoPoint.MAX_YIELD, ParetoPoint.BALANCED]
    assert [p.scored.candidate.candidate_id for p in picks] == ["conventional", "yield",
                                                                "balanced"]


def test_a_point_nothing_different_is_left_for_is_named_not_filled_with_a_copy():
    copies = _scored(_two_slabs("a", 9, 300), _two_slabs("b", 8, 300, at=((42, 21), (108, 74))))
    selection = select(copies, BRIEF)
    assert [(p.point, p.scored.candidate.candidate_id) for p in selection.picks] == [
        (ParetoPoint.MAX_YIELD, "a")]
    assert {point for point, _ in selection.unfilled} == {
        ParetoPoint.BALANCED, ParetoPoint.CONVENTIONAL_OPEN_SPACE}
    assert all("different idea" in why for _, why in selection.unfilled)
    empty = select([], BRIEF)
    assert not empty.picks and {why for _, why in empty.unfilled} == {"no candidate passed"}


def test_the_front_is_preferred_and_what_it_dominates_is_chosen_only_to_be_different():
    front_member = candidate("front", [tower("T1", P1, 40, 20, 9), tower("T2", P1, 110, 75, 9)],
                             [P1], open_space_sqm=3000)  # more of everything, as conventional
    dominated = candidate("dominated", [tower("T1", P1, 40, 20, 5)], [P1], open_space_sqm=100)
    selection = select(_scored(front_member, dominated), BRIEF)
    picked = {p.point: (p.scored.candidate.candidate_id, p.on_front) for p in selection.picks}
    assert picked[ParetoPoint.MAX_YIELD] == ("front", True)
    assert picked[ParetoPoint.CONVENTIONAL_OPEN_SPACE] == ("dominated", False)


def test_two_layouts_that_tie_on_yield_take_the_labels_that_suit_them():
    """Equal saleable area and units, one with more open space. That one dominates, so the fill
    reaches it first; the labels are then settled so the open-space point is on the layout with
    more open space, and the maximum-yield point (a tie) on the other."""
    tight = candidate("tight", [tower("T1", P1, 40, 20, 9)], [P1], open_space_sqm=1000)
    spacious = candidate("spacious", [tower("T1", P1, 110, 75, 9)], [P1], open_space_sqm=2000)
    picks = select(_scored(tight, spacious), BRIEF).picks
    assert {p.point: (p.scored.candidate.candidate_id, p.on_front) for p in picks} == {
        ParetoPoint.MAX_YIELD: ("tight", False),
        ParetoPoint.CONVENTIONAL_OPEN_SPACE: ("spacious", True)}


def test_a_label_never_moves_off_a_layout_that_beats_the_others_on_the_earlier_point():
    best_yield = _two_slabs("yield", 9, 300)
    spacious = candidate("spacious", [tower("T1", P1, 110, 75, 9)], [P1], open_space_sqm=2000)
    picks = select(_scored(best_yield, spacious), BRIEF).picks
    assert [(p.point, p.scored.candidate.candidate_id) for p in picks] == [
        (ParetoPoint.MAX_YIELD, "yield"), (ParetoPoint.CONVENTIONAL_OPEN_SPACE, "spacious")]


def test_more_options_than_points_are_more_different_ideas_by_yield():
    # one more than the brief's points; ROBUST (C4-09) is left unfilled here, no report read
    brief = _brief(options=len(ParetoPoint) + 1)
    picks = select(_scored(*_pool(), brief=brief), brief).picks
    assert [p.point for p in picks][:3] == [ParetoPoint.MAX_YIELD, ParetoPoint.BALANCED,
                                            ParetoPoint.CONVENTIONAL_OPEN_SPACE]
    assert len(picks) == 4 and picks[3].point is None
    assert picks[3].scored.candidate.candidate_id == "turned"  # the only idea left
    for a, b in combinations([p.scored.candidate for p in picks], 2):
        assert not same_idea(a, b)


def test_the_priorities_decide_which_compromise_is_the_balanced_one():
    """Two ideas are left for BALANCED after the extremes: one with the yield, one with the
    open space. What the architect cares about picks between them."""
    base = [_two_slabs("yield", 9, 300),
            candidate("conventional", [tower(f"T{i}", P1, 25 + 25 * i, 20, 7) for i in range(5)],
                      [P1], open_space_sqm=2400)]
    for_yield = candidate("tall-and-tight", [tower("T1", P2, 40, 20, 8),
                                             tower("T2", P1, 100, 20, 8),
                                             tower("T3", P1, 60, 75, 8)], [P1, P2],
                          open_space_sqm=400)
    for_space = candidate("short-and-open", [tower("T1", P2, 40, 60, 6),
                                             tower("T2", P1, 120, 60, 6),
                                             tower("T3", P1, 20, 20, 6)], [P1, P2],
                          open_space_sqm=2000)

    def balanced(priorities):
        brief = _brief(priorities=priorities)
        picks = select(_scored(*base, for_yield, for_space, brief=brief), brief).picks
        return next(p for p in picks if p.point is ParetoPoint.BALANCED).scored.candidate

    assert balanced({"saleable_area": 5, "units": 5}).candidate_id == "tall-and-tight"
    assert balanced({"open_space": 20}).candidate_id == "short-and-open"


def test_the_selection_does_not_depend_on_the_order_the_pool_was_made_in():
    pool = _pool()
    expected = [(p.point, p.scored.candidate.candidate_id)
                for p in select(_scored(*pool), BRIEF).picks]
    for seed in range(5):
        shuffled = pool[:]
        random.Random(seed).shuffle(shuffled)
        assert [(p.point, p.scored.candidate.candidate_id)
                for p in select(_scored(*shuffled), BRIEF).picks] == expected


# --- ROBUST: the layout that rests on the fewest open readings (C4-09) -------------------------


EVERY_POINT = _brief(pareto=list(ParetoPoint))  # a brief that asks for every point, ROBUST too


def _rested(rests: dict[str, tuple[int, int]], brief=EVERY_POINT):
    """The pool, each candidate with the readings it rests on (as the guard's report gives)."""
    return [Scored(c, measure(c, brief), rests.get(c.candidate_id, (2, 3))) for c in _pool()]


def test_robust_is_the_different_idea_resting_on_the_fewest_readings_the_most_saleable():
    """The most saleable layouts rest on readings; of those that hold under every one, the most
    saleable different idea is ROBUST: not the near-copy of the scheme shown for MAX_YIELD, which
    holds too and sells more, since every alternative is another idea."""
    picks = select(_rested({"near-copy": (0, 0), "conventional": (0, 0)}), EVERY_POINT).picks
    by_point = {p.point: p.scored.candidate.candidate_id for p in picks}
    assert by_point[ParetoPoint.MAX_YIELD] == "yield"
    assert by_point[ParetoPoint.ROBUST] == "conventional"
    for a, b in combinations([p.scored.candidate for p in picks], 2):
        assert not same_idea(a, b)


def test_robust_is_left_unfilled_when_the_layout_shown_first_holds_or_no_report_was_read():
    selection = select(_rested({"yield": (0, 0), "near-copy": (0, 0)}), EVERY_POINT)
    assert ParetoPoint.ROBUST not in {p.point for p in selection.picks}
    assert (ParetoPoint.ROBUST, "a layout already chosen holds under every reading") in \
        selection.unfilled
    unread = select(_scored(*_pool(), brief=EVERY_POINT), EVERY_POINT)
    assert (ParetoPoint.ROBUST, "no candidate's validation report was read") in unread.unfilled


def test_the_fewer_open_questions_rank_first_then_the_fewer_checks():
    picks = select(_rested({"balanced": (1, 4), "turned": (1, 1)}), EVERY_POINT).picks
    assert {p.point: p.scored.candidate.candidate_id for p in picks}[ParetoPoint.ROBUST] == \
        "turned"


def test_robust_ranks_by_its_own_measure_not_the_front_of_the_other_axes():
    """The turned slabs (8 floors) are dominated by the upright ones (9 floors) on every axis the
    front is drawn over, none of them robustness; of the two layouts that hold under every
    reading they sell more than the conventional one, which is on the front: ROBUST is them.
    (A brief asking for these two points only, so no other point takes either layout.)"""
    two = _brief(pareto=[ParetoPoint.MAX_YIELD, ParetoPoint.ROBUST])
    picks = select(_rested({"turned": (0, 0), "conventional": (0, 0)}, two), two).picks
    assert {p.point: p.scored.candidate.candidate_id for p in picks}[ParetoPoint.ROBUST] == \
        "turned"
