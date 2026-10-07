"""The ground every road of the full search takes on made-up land: pinned on C4-01a, before the
roads were drawn from a centre-line graph (C4-01), so that drawing them from their centre lines is
shown to lay the same ground: the same candidates, the same roads of the same kinds, each the same
number of pieces and the same area to 0.01 m². (On 1c4fd2e the slim L-plot's fringe chose between
equally near places by the last digits of the geometry; C4-01a chooses by place, which moves two of
its eight proposals; C4-05's fringe search lays the L-plots' layouts with blocks below 21 m anew,
8-17% larger; C4-06 builds the layouts meant for every reading with no block NBC's own 15 m line
would hold, docs/behaviour-changes.md.)

The values pin exact output on the locked dependencies (uv.lock). They move only with a normative
replacement and an entry in docs/behaviour-changes.md.
"""

from __future__ import annotations

import pytest
from search_support import proposal_on_the_l_plot, proposal_on_the_rectangle
from shapely.ops import unary_union

TEST_CLASS = "characterization"

AREA_TOL_SQM = 0.01

RING = "ring", "LOOP", 1
APPROACH = "approach", "APPROACH", 1


def _street(i: int, area: float) -> tuple:
    return f"street-{i}", "INTERNAL", 1, area


def _pathway(i: int, area: float) -> tuple:
    return f"pathway-{i}", "PATHWAY", 1, area


def _streets(*areas: float) -> list[tuple]:
    return [_street(i, a) for i, a in enumerate(areas, 1)]


RECTANGLE_A = [(*RING, 4023.36), *_streets(738.0, 738.0, 738.0), (*APPROACH, 99.43)]
RECTANGLE_B = [(*RING, 4183.02), *_streets(1220.0, 1220.0), (*APPROACH, 86.46)]
RECTANGLE_C = [(*RING, 3427.02), *_streets(738.0, 738.0), (*APPROACH, 99.43)]
L_THREE = [(*RING, 3339.36), *_streets(410.0, 410.0, 410.0), (*APPROACH, 36.25)]
L_RING = [(*RING, 2711.34), (*APPROACH, 253.44)]
L_ONE_PATH = [(*RING, 2425.68), *_streets(585.0), (*APPROACH, 108.43), _pathway(1, 36.3)]
L_TWO_PATHS = [(*RING, 2729.34), (*APPROACH, 347.0), _pathway(1, 36.3), _pathway(2, 36.3)]
SLIM_ONE = [(*RING, 2830.68), *_streets(738.0), (*APPROACH, 222.97)]
SLIM_TWO_PATHS = [(*RING, 2425.68), *_streets(585.0), (*APPROACH, 141.79), _pathway(1, 36.3),
                  _pathway(2, 36.3)]

PINNED = {
    "rectangle": {
        "full-not_counted-ALL-13": RECTANGLE_A,
        "full-not_counted-allowed-19": RECTANGLE_B,
        "full-not_counted-allowed-20": RECTANGLE_B,
        "full-ALL-ALL-1": RECTANGLE_A,
        "full-not_counted-ALL-14": RECTANGLE_C,
        "full-ALL-allowed-7": RECTANGLE_B,
        "full-ALL-allowed-8": RECTANGLE_B,
        "full-ALL-ALL-4": RECTANGLE_C,
    },
    "l_plot": {
        "full-not_counted-allowed-18": L_THREE,
        "full-ALL-allowed-7": L_THREE,
        "full-not_counted-ALL-12": L_RING,
        "full-not_counted-ALL-13": L_ONE_PATH,
        "full-ALL-ALL-1": L_ONE_PATH,
        "full-ALL-ALL-2": L_TWO_PATHS,
    },
    "l_plot_slim": {
        "full-not_counted-allowed-18": L_THREE,
        "full-not_counted-allowed-19": SLIM_ONE,
        "full-ALL-allowed-7": L_THREE,
        "full-ALL-allowed-8": SLIM_ONE,
        "full-not_counted-ALL-12": L_RING,
        "full-not_counted-ALL-13": L_ONE_PATH,
        "full-ALL-ALL-1": L_ONE_PATH,
        "full-ALL-ALL-2": SLIM_TWO_PATHS,
    },
}


def _proposal(name: str):
    if name == "rectangle":
        return proposal_on_the_rectangle()
    return proposal_on_the_l_plot(slim=name == "l_plot_slim")


def _roads(candidate) -> list[tuple]:
    out = []
    for road in candidate.circulation.roads:
        shape = unary_union([s.to_shapely() for s in road.shapes])
        out.append((road.id, road.kind.value, len(road.shapes), shape.area))
    return out


@pytest.mark.parametrize("name", list(PINNED))
def test_every_road_takes_the_ground_it_took_before_the_graph(name):
    proposal = _proposal(name)
    assert [c.candidate_id for c in proposal.candidates] == list(PINNED[name])
    for candidate in proposal.candidates:
        found, pinned = _roads(candidate), PINNED[name][candidate.candidate_id]
        assert [r[:3] for r in found] == [p[:3] for p in pinned], candidate.candidate_id
        for (road_id, *_, area), (*_, wanted) in zip(found, pinned, strict=True):
            assert abs(area - wanted) <= AREA_TOL_SQM, (candidate.candidate_id, road_id, area)
