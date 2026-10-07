"""Which layouts the validator judges (C4-09): of each profile, the front of the objective's axes
first, then the rest by yield, different ideas before copies of one. The six judged were the six
most saleable, which a profile could fill with copies of one scheme a step apart. Made-up land.
"""

from __future__ import annotations

from optimizer_support import candidate, fixture, module_prototype, tower

from siteplan.optimizer.objective import measure
from siteplan.optimizer.search.strategy import _to_judge

TEST_CLASS = "normative"

_, _, BRIEF = fixture()
P1, P2 = module_prototype(1), module_prototype(2)


def _two_slabs(candidate_id, floors, open_space, *, at=((40, 20), (110, 75))):
    (x1, y1), (x2, y2) = at
    return candidate(candidate_id, [tower("T1", P2, x1, y1, floors),
                                    tower("T2", P2, x2, y2, floors)], [P2],
                     open_space_sqm=open_space)


def _pool(*candidates):
    return [(measure(c, BRIEF), None, c) for c in candidates]


def _ids(chosen):
    return [c.candidate_id for _, _, c in chosen]


def test_the_quota_goes_to_different_ideas_before_copies_of_one():
    """Two slabs at 9 floors, the same two a step over at 8 and at 7, and five single cores: with
    two to judge, the slabs and the single cores are judged, not the slabs twice."""
    slabs = _two_slabs("slabs", 9, 300)
    step = _two_slabs("slabs-8", 8, 300, at=((42, 21), (108, 74)))
    lower = _two_slabs("slabs-7", 7, 300, at=((41, 20), (109, 75)))
    singles = candidate("singles", [tower(f"T{i}", P1, 25 + 25 * i, 20 + 12 * (i % 3), 5)
                                    for i in range(5)], [P1], open_space_sqm=2400)
    assert _ids(_to_judge(_pool(slabs, step, lower, singles), 2)) == ["slabs", "singles"]


def test_copies_are_judged_when_no_other_idea_is_left():
    slabs = _two_slabs("slabs", 9, 300)
    step = _two_slabs("slabs-8", 8, 300, at=((42, 21), (108, 74)))
    assert _ids(_to_judge(_pool(slabs, step), 3)) == ["slabs", "slabs-8"]


def test_a_layout_nothing_beats_on_every_axis_is_judged_before_a_more_saleable_one_beaten():
    """The front first: a layout with the most open space is judged before one more saleable
    that another beats on every axis."""
    best = _two_slabs("best", 9, 3000)
    beaten = _two_slabs("beaten", 9, 2000, at=((140, 20), (200, 75)))  # best beats it on all
    open_ = candidate("open", [tower(f"T{i}", P1, 25 + 25 * i, 20, 4) for i in range(3)], [P1],
                      open_space_sqm=5000)  # less saleable, more open space: on the front
    assert _ids(_to_judge(_pool(best, beaten, open_), 2)) == ["best", "open"]
