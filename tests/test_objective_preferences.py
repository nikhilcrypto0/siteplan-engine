"""The architect's soft preferences, scored (C4-16): each kind the engine knows scores how well a
layout meets the wish, 0 to 1, and the objective's preference axis is their weighted mean, 1 for
every layout when the brief gives none. A preference is never a rule, and one the engine does not
understand is named, never weighed unsaid. Made-up land only."""

from __future__ import annotations

import pytest
from optimizer_support import candidate, fixture, module_prototype, tower
from shapely.geometry import box

from siteplan.contracts.candidate import ClubHouse, Gate
from siteplan.contracts.common import Shape
from siteplan.contracts.design_brief import Objectives, ParetoPoint, SoftPreference
from siteplan.optimizer.objective import AXES, measure
from siteplan.optimizer.pareto import Scored, select
from siteplan.optimizer.preferences import not_weighed, preference_score

TEST_CLASS = "normative"

_, _, BRIEF = fixture()
P1 = module_prototype(1)  # 31 m long, 24 m deep: its long side runs along its rotation
GATE = box(0, 0, 9, 2)  # an entrance on the south line, by the west corner


def _blocks(candidate_id, rotations=(0.0, 0.0)):
    """Blocks of one prototype in a row, and no open space (turning a block moves it nearer the
    open space the helper draws, which would tell the layouts apart on another axis)."""
    return candidate(candidate_id, [tower(f"T{i}", P1, 20 + 40 * i, 50, 8, r)
                                    for i, r in enumerate(rotations)], [P1])


def _entered(made, club=None):
    """The candidate with an entrance at GATE, and a club house when given."""
    circulation = made.circulation.model_copy(update={"gates": [
        Gate(shape=Shape.from_shapely(GATE), width_m=9.0)]})
    program = made.program.model_copy(update={"club_house": None if club is None else ClubHouse(
        shape=Shape.from_shapely(club), floors=2)})
    return made.model_copy(update={"circulation": circulation, "program": program})


def _wish(kind, weight=1.0, **params):
    return SoftPreference(kind=kind, params=params, weight=weight)


def test_with_no_preference_every_layout_scores_one_and_the_axis_moves_nothing():
    axis = AXES.index("preference")
    for made in (_blocks("upright"), _blocks("turned", (90.0, 90.0))):
        scores = measure(made, BRIEF)
        assert scores.preference == scores.vector[axis] == 1.0


def test_orientation_scores_how_far_the_long_sides_run_along_the_axis():
    along = [_wish("orientation", axis_deg=0.0)]
    assert preference_score(_blocks("along"), along) == pytest.approx(1.0)
    assert preference_score(_blocks("across", (90.0, 90.0)), along) == pytest.approx(0.0, abs=1e-9)
    assert preference_score(_blocks("both", (0.0, 90.0)), along) == pytest.approx(0.5)


def test_max_towers_scores_the_share_of_the_blocks_asked():
    three = _blocks("three", (0.0, 0.0, 0.0))
    assert preference_score(three, [_wish("max_towers", towers=3)]) == 1.0
    assert preference_score(three, [_wish("max_towers", towers=2)]) == pytest.approx(2 / 3)


def test_keep_away_from_road_scores_the_share_of_blocks_far_enough_from_the_entrance():
    """The west block stands 36 m from the entrance, the east one 50 m."""
    made = _entered(_blocks("two"))
    assert preference_score(made, [_wish("keep_away_from_road", m=30.0)]) == 1.0
    assert preference_score(made, [_wish("keep_away_from_road", m=40.0)]) == pytest.approx(0.5)


def test_club_near_entrance_scores_the_distance_asked_over_the_distance_found():
    """The club house stands 3.16 m from the entrance (one across, three up)."""
    made = _entered(_blocks("two"), club=box(10, 5, 30, 20))
    assert preference_score(made, [_wish("club_near_entrance", m=5.0)]) == 1.0
    assert preference_score(made, [_wish("club_near_entrance", m=1.0)]) == pytest.approx(
        1 / 10 ** 0.5)
    assert preference_score(_entered(_blocks("none")), [_wish("club_near_entrance", m=5.0)]) == 0


def test_a_preference_the_engine_does_not_understand_is_named_and_not_weighed():
    """An unknown kind, and a known one with its parameter missing: neither counts for or against
    a layout, and both are named."""
    wishes = [_wish("feng_shui", element="water"), _wish("orientation")]
    assert not_weighed(wishes) == ["feng_shui", "orientation"]
    assert preference_score(_blocks("any"), wishes) == 1.0
    weighed = [*wishes, _wish("max_towers", towers=1)]
    assert preference_score(_blocks("two"), weighed) == pytest.approx(0.5)  # the one understood


def test_the_balanced_option_follows_the_preference_between_otherwise_equal_layouts():
    """The same two blocks upright and turned a quarter: equal on every other axis, so the tie
    went by name (`a-` first); asked for long sides running north-south (90 degrees), the turned
    one is taken."""
    upright, turned = _blocks("a-upright"), _blocks("b-turned", (90.0, 90.0))

    def balanced(preferences):
        brief = BRIEF.model_copy(update={"objectives": Objectives(
            pareto=[ParetoPoint.BALANCED], options=1, soft_preferences=preferences)})
        pool = [Scored(c, measure(c, brief)) for c in (upright, turned)]
        return [p.scored.candidate.candidate_id for p in select(pool, brief).picks]

    assert balanced([]) == ["a-upright"]
    assert balanced([_wish("orientation", axis_deg=90.0)]) == ["b-turned"]


def test_the_search_says_which_preferences_it_weighed_and_which_it_could_not():
    from search_support import rectangle

    from siteplan.optimizer.search.layout import make_run
    from siteplan.optimizer.search.readings import profiles
    from siteplan.optimizer.search.strategy import Tally, _notes

    made = rectangle()
    brief = made.brief.model_copy(update={"objectives": made.brief.objectives.model_copy(
        update={"soft_preferences": [_wish("orientation", axis_deg=0.0),
                                     _wish("feng_shui", element="water")]})})
    run = make_run(made.site, made.rules, brief, made.envelope, made.kit,
                   profiles(made.rules, brief, list(made.kit)))
    notes = _notes(run, Tally(), [], [])
    assert "soft preferences weighed (a score, never a rule): orientation" in notes
    assert any(n.startswith("soft preferences not weighed") and n.endswith("feng_shui")
               for n in notes)
