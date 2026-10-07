"""Usable open space (C4-12): the part of the open space at least 12 m across, where a lawn, a
court or a play area fits, within 30 m of a block, where residents see and reach it. The generator
takes the most usable pockets first and cuts the last from its more usable end; the objective
scores the usable part. A search score, never a rule: the law's open space is the validator's.
Made-up land only."""

from __future__ import annotations

import pytest
from optimizer_support import candidate, fixture, module_prototype, tower
from shapely.geometry import box
from shapely.ops import unary_union

from siteplan.optimizer.objective import AXES, measure, reach_of, usable_open_sqm
from siteplan.optimizer.search.fit import choose_pockets

TEST_CLASS = "normative"

_, _, BRIEF = fixture()
P1 = module_prototype(1)
WIDTH_M, POCKET_SQM = 3.0, 50.0  # the rule's pocket, as the generator is given it


def _usable(block):
    return lambda pocket: usable_open_sqm(pocket, reach_of(block))


def test_usable_open_space_is_wide_enough_and_near_a_block():
    reach = reach_of(box(-50, 0, 100, 20))
    assert usable_open_sqm(box(0, 30, 20, 50), reach) == pytest.approx(400.0)  # 10 m off
    assert usable_open_sqm(box(0, 25, 60, 33), reach) == 0.0  # 8 m across: no lawn fits
    assert usable_open_sqm(box(200, 200, 230, 230), reach) == 0.0  # 180 m away
    assert usable_open_sqm(box(0, 25, 40, 65), reach) == pytest.approx(40 * 25)  # to 30 m off


def test_the_generator_takes_the_most_usable_pocket_before_a_bigger_far_one():
    """A 3,600 m² pocket 160 m from the blocks and a 1,200 m² one beside them, 1,000 m² asked:
    the biggest came first; the one residents can reach does now."""
    block = box(0, 0, 40, 20)
    room = unary_union([box(200, 0, 260, 60), box(0, 30, 40, 60)])
    far, _ = choose_pockets(room, 1000.0, WIDTH_M, POCKET_SQM)
    near, total = choose_pockets(room, 1000.0, WIDTH_M, POCKET_SQM, value=_usable(block))
    assert unary_union(far).within(box(200, 0, 260, 60))
    assert unary_union(near).within(box(0, 30, 40, 60)) and total >= 1000.0


def test_the_last_pocket_is_cut_from_its_more_usable_end():
    """A 40 x 100 m pocket, the blocks beyond its north end: the 800 m² kept is the north end,
    where the south end was kept whatever lay beyond it."""
    block = box(0, 130, 40, 150)
    room = box(0, 25, 40, 125)
    south, _ = choose_pockets(room, 800.0, WIDTH_M, POCKET_SQM)
    north, _ = choose_pockets(room, 800.0, WIDTH_M, POCKET_SQM, value=_usable(block))
    assert unary_union(south).centroid.y < 50 < 100 < unary_union(north).centroid.y
    assert usable_open_sqm(unary_union(north), reach_of(block)) == pytest.approx(
        unary_union(north).area)


def test_the_open_space_axis_scores_the_usable_part_and_keeps_the_whole():
    """The helper draws 400 m² of open space at the origin: beside one block it is all usable;
    80 m from the other it is open space no one is near."""
    near = candidate("near", [tower("T1", P1, 40, 20, 8)], [P1], open_space_sqm=400)
    far = candidate("far", [tower("T1", P1, 120, 100, 8)], [P1], open_space_sqm=400)
    axis = AXES.index("open_space")
    for made, usable in ((near, 400.0), (far, 0.0)):
        scores = measure(made, BRIEF)
        assert scores.open_space_sqm == pytest.approx(400.0)
        assert scores.vector[axis] == scores.open_space_usable_sqm == pytest.approx(usable)
        assert scores.as_dict()["open_space_usable_sqm"] == scores.open_space_usable_sqm
