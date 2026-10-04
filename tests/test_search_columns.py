"""Blocks in columns: the best sequence of prototypes and heights along one column (stream C2).

The search along a column is solved exactly, so these tests hold it to an exhaustive search on
small instances, and to the three things the architecture asks of a mixed-height optimizer: a lower
block stands where only a lower height fits, a block is lowered when that lets its neighbour stand,
and the legal maximum never means every block at it.
"""

import random

from search_support import rectangle
from shapely.geometry import Polygon, box

from siteplan.optimizer.search.columns import (
    Choice,
    choices_for,
    free_stretches,
    plan_column,
)
from siteplan.optimizer.search.readings import FloorClass

TEST_CLASS = "normative"


def _gap(a: FloorClass, b: FloorClass) -> float:
    return max(a.gap_m, b.gap_m)  # the taller block's gap governs


def _class(floors: int, setback: float, gap: float) -> FloorClass:
    return FloorClass(floors, 3.0 + 3.0 * floors, setback, gap, (), ())


CLASSES = {7: _class(7, 8.0, 8.0), 8: _class(8, 9.0, 9.0), 9: _class(9, 10.0, 10.0)}


def _choices(prototypes=None, floors=(7, 8, 9)):
    kit = prototypes or rectangle().kit
    return choices_for(kit, {p.id: [CLASSES[f] for f in floors] for p in kit})


def _plan(stretches, choices=None, column=0):
    return plan_column(stretches, choices or _choices(), _gap, column, 0.0)


def _sequence(column):
    return [(s.choice.prototype.id, s.choice.cls.floors, round(s.y0, 6)) for s in column.standing]


def test_the_best_sequence_is_found_among_all_of_them():
    """On integer lengths the grid is exact, so the search must equal an exhaustive one."""
    rng = random.Random(7)
    for _ in range(40):
        lengths = sorted(rng.sample(range(4, 14), 3))
        gaps = {1: 2, 2: 3}
        classes = {f: FloorClass(f, 0.0, 1.0, float(gaps[f]), (), ()) for f in gaps}
        choices = [Choice(rectangle().kit[0], classes[f], float(n), 1.0, rng.randint(5, 40) * n * f)
                   for n in lengths for f in gaps]
        stretch = rng.randint(14, 40)
        found = plan_column({1.0: [(0.0, float(stretch))]}, choices,
                            lambda a, b: max(a.gap_m, b.gap_m), 0, 0.0)
        assert found.value == _exhaustive(choices, stretch, gaps)


def _exhaustive(choices, stretch: int, gaps: dict[int, int]) -> float:
    best = 0.0

    def go(earliest: int, last: int | None, total: float) -> None:
        nonlocal best
        best = max(best, total)
        for choice in choices:
            floors = choice.cls.floors
            need = 0 if last is None else max(gaps[last], gaps[floors])
            for start in range(earliest + need, stretch - int(choice.length_m) + 1):
                go(start + int(choice.length_m), floors, total + choice.value)

    go(0, None, 0.0)
    return best


def test_a_block_is_lowered_when_that_lets_its_neighbour_stand():
    """Two 41 m blocks need 92 m at 9 floors (a gap of 10 m) and 91 m at 8 (a gap of 9 m): in 91 m
    the one block at 9 floors is worth less than both at 8, so both are lowered."""
    one = [p for p in rectangle().kit if p.id == "single-core-6"]
    column = _plan({10.0: [(0.0, 91.0)], 9.0: [(0.0, 91.0)], 8.0: [(0.0, 91.0)]},
                   _choices(one))
    assert [(s.choice.cls.floors, s.y0) for s in column.standing] == [(8, 0.0), (8, 50.0)]
    roomier = _plan({10.0: [(0.0, 92.0)], 9.0: [(0.0, 92.0)], 8.0: [(0.0, 92.0)]},
                    _choices(one))
    assert [s.choice.cls.floors for s in roomier.standing] == [9, 9]  # 92 m is room for the lot


def test_the_legal_maximum_never_means_every_block_at_it():
    """With 9 floors the most the law allows, 141 m is better filled with three blocks of 8 floors
    (three 41 m blocks and two gaps of 9 m) than with the two that fit at 9 floors (each gap 10 m):
    the maximum is a limit on a block, never a goal for every one."""
    one = [p for p in rectangle().kit if p.id == "single-core-6"]
    stretches = {10.0: [(0.0, 141.0)], 9.0: [(0.0, 141.0)], 8.0: [(0.0, 141.0)]}
    column = _plan(stretches, _choices(one))
    assert [s.choice.cls.floors for s in column.standing] == [8, 8, 8]
    assert column.value > _plan(stretches, _choices(one, floors=(9,))).value


def test_a_lower_block_stands_where_only_a_lower_height_fits():
    """The tall blocks keep a deeper setback, so their ground ends sooner: the end of the column
    that only the lower height reaches takes a lower block."""
    stretches = {10.0: [(0.0, 125.0)], 9.0: [(0.0, 160.0)], 8.0: [(0.0, 160.0)]}
    column = _plan(stretches)
    by_height = {s.choice.cls.floors: s for s in column.standing}
    assert len(column.standing) >= 2 and len(set(by_height)) >= 2  # mixed heights
    tallest = max(s.choice.cls.floors for s in column.standing)
    for s in column.standing:
        if s.choice.cls.floors == tallest:
            assert s.y1 <= 125.0 + 1e-6  # the tall block stands on tall ground
    assert max(s.y1 for s in column.standing) > 125.0  # and the lower ones go past it


def test_the_gap_between_two_blocks_is_the_taller_ones():
    stretches = {10.0: [(0.0, 400.0)], 9.0: [(0.0, 400.0)], 8.0: [(0.0, 400.0)]}
    column = _plan(stretches)
    pairs = list(zip(column.standing, column.standing[1:], strict=False))
    assert pairs
    for a, b in pairs:
        need = max(a.choice.cls.gap_m, b.choice.cls.gap_m)
        assert b.y0 - a.y1 >= need - 1e-9


def test_blocks_never_stand_off_the_ground_their_height_allows():
    stretches = {10.0: [(0.0, 60.0), (80.0, 150.0)], 9.0: [(0.0, 150.0)], 8.0: [(0.0, 150.0)]}
    column = _plan(stretches)
    for s in column.standing:
        assert any(a - 1e-9 <= s.y0 and s.y1 <= b + 1e-9
                   for a, b in stretches[s.choice.cls.setback_m])


def test_no_ground_no_blocks():
    assert _plan({}).standing == ()
    assert _plan({10.0: [], 9.0: [], 8.0: []}).value == 0.0


def test_free_stretches_are_the_ranges_where_a_whole_strip_lies_on_the_land():
    land = Polygon([(0, 0), (30, 0), (30, 50), (60, 50), (60, 120), (0, 120)])
    # a strip 20 m wide at x = 5..25 lies on the land the whole way up; one at x = 40..60 only
    # from y = 50
    assert free_stretches(land, 5.0, 20.0) == [(0.0, 120.0)]
    assert free_stretches(land, 40.0, 20.0) == [(50.0, 120.0)]
    assert free_stretches(box(0, 0, 10, 10), 20.0, 5.0) == []
