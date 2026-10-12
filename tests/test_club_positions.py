"""The club house tried in more than one place (2026-10-12, the architect: let it try other places,
an arm of the plot among them): the program is laid with the club house nearest the gate and again
nearest the far end of the open ground, and the furnishing that leaves the more usable open space
is kept, then the fewer cellar levels, the gate's between equals. Made-up shapes; `_furnish` is
stood in for, so only the choosing is tested here (the full search runs it in
test_search_road_ground.py)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from shapely.geometry import Point, Polygon, box

from siteplan.optimizer.search import layout as layout_module
from siteplan.optimizer.search.layout import _far_point, _furnish_where_best, _Program

TEST_CLASS = "normative"

GATE = Point(0, 0)
OPEN = box(0, 0, 100, 40)
BLOCK = box(40, 10, 60, 30)
NARROW = box(0, 0, 10, 10)  # under 12 m across: no usable open space
WIDE = box(62, 0, 100, 40)  # 38 m across, within 30 m of the block


def _program() -> _Program:
    return _Program(land=None, open_land=OPEN, buildable=None, zones=None,
                    placements=[SimpleNamespace(footprint=BLOCK)], stilts=[], roads=None,
                    tower_sqm=0.0, units=0, angles=[], angle_deg=0.0, anchor=GATE, cores=[],
                    low=None)


def _furnished(pocket, levels: int = 1):
    return SimpleNamespace(pockets=[pocket], plan=SimpleNamespace(levels=levels), tag=pocket)


def _choose(by_place):
    """`_furnish_where_best` with `_furnish` answering by where the club house was looked for."""
    tried = []

    def furnish(run, program, repair=None):
        place = "far" if program.club_anchor is not None else "gate"
        tried.append((place, program.club_anchor))
        return by_place[place]

    with patch.object(layout_module, "_furnish", furnish):
        return _furnish_where_best(None, _program()), tried


def test_the_far_point_is_the_corner_of_the_open_ground_farthest_from_the_gate():
    assert _far_point(OPEN, GATE).equals(Point(100, 40))
    assert _far_point(Polygon(), GATE) is None


def test_both_places_are_tried_and_the_more_usable_open_space_is_kept():
    (kept, why), tried = _choose({"gate": (_furnished(NARROW), ""),
                                  "far": (_furnished(WIDE), "")})
    assert [place for place, _ in tried] == ["gate", "far"]
    assert tried[1][1].equals(Point(100, 40))
    assert kept.tag is WIDE and why == ""


def test_between_equals_the_fewer_cellar_levels_then_the_gates_place_is_kept():
    (kept, _), _ = _choose({"gate": (_furnished(WIDE, 2), ""), "far": (_furnished(WIDE, 1), "")})
    assert kept.plan.levels == 1
    gate = _furnished(WIDE, 1)
    (kept, _), _ = _choose({"gate": (gate, ""), "far": (_furnished(WIDE, 1), "")})
    assert kept is gate


def test_a_place_that_finds_no_room_gives_way_and_none_gives_the_gates_reason():
    (kept, _), _ = _choose({"gate": (None, "no room for the club house"),
                            "far": (_furnished(NARROW), "")})
    assert kept.tag is NARROW
    (kept, why), _ = _choose({"gate": (None, "no room for the club house"),
                              "far": (None, "something else")})
    assert kept is None and why == "no room for the club house"
