"""The ground every road of the full search takes on made-up land: pinned on C4-01a, before the
roads were drawn from a centre-line graph (C4-01), so that drawing them from their centre lines is
shown to lay the same ground: the same candidates, the same roads of the same kinds, each the same
number of pieces and the same area to 0.01 m². (On 1c4fd2e the slim L-plot's fringe chose between
equally near places by the last digits of the geometry; C4-01a chooses by place, which moves two of
its eight proposals; C4-05's fringe search lays the L-plots' layouts with blocks below 21 m anew,
8-17% larger; C4-06 builds the layouts meant for every reading with no block NBC's own 15 m line
would hold; C4-07 stands the club house on its own band's ground and repairs the layouts it lays
out, the larger ones laid after all the others; C4-09 judges each profile's front and different
ideas first; C4-11 scores site use and the quality of a scheme and judges each point's best of
the front first, so four, three and four of the three plots' eight proposals are other layouts, five
of their road sets pinned here for the first time (RECTANGLE_F and _G, L_ONE, SLIM_THREE and
SLIM_ONE_STREET), docs/behaviour-changes.md.)

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
RECTANGLE_D = [(*RING, 4504.68), *_streets(1740.0), (*APPROACH, 82.58)]
RECTANGLE_F = [(*RING, 3568.68), *_streets(1220.0), (*APPROACH, 292.09)]
RECTANGLE_G = [(*RING, 4270.68), *_streets(1458.0), (*APPROACH, 340.23)]
L_THREE = [(*RING, 3339.36), *_streets(410.0, 410.0, 410.0), (*APPROACH, 36.25)]
L_RING = [(*RING, 2711.34), (*APPROACH, 253.44)]
L_RING_WIDE = [(*RING, 2954.34), (*APPROACH, 260.13)]
L_ONE_PATH = [(*RING, 2425.68), *_streets(585.0), (*APPROACH, 108.43), _pathway(1, 36.3)]
L_ONE = [(*RING, 2425.68), *_streets(585.0), (*APPROACH, 108.43)]
SLIM_THREE = [(*RING, 3014.19), *_streets(369.0, 369.0, 369.0), (*APPROACH, 36.25)]
SLIM_ONE_STREET = [(*RING, 2355.59), *_streets(710.0), (*APPROACH, 138.41)]

PINNED = {
    "rectangle": {
        "full-not_counted-allowed-19": RECTANGLE_D,
        "full-ALL-allowed-7": RECTANGLE_D,
        "full-not_counted-ALL-13": RECTANGLE_A,
        "full-ALL-ALL-1": RECTANGLE_A,
        "full-not_counted-allowed-24": RECTANGLE_F,
        "full-not_counted-ALL-18": RECTANGLE_G,
        "full-ALL-allowed-12": RECTANGLE_F,
        "full-ALL-ALL-3": RECTANGLE_G,
    },
    "l_plot": {
        "full-not_counted-allowed-18": L_THREE,
        "full-not_counted-allowed-29": L_RING_WIDE,
        "full-not_counted-ALL-27": L_RING,
        "full-ALL-allowed-7": L_THREE,
        "full-ALL-allowed-25": L_RING_WIDE,
        "full-ALL-ALL-23": L_ONE_PATH,
        "full-not_counted-ALL-15": L_ONE,
        "full-ALL-ALL-4": L_ONE,
    },
    "l_plot_slim": {
        "full-not_counted-allowed-18": L_THREE,
        "full-not_counted-ALL-47": L_RING,
        "full-ALL-allowed-7": L_THREE,
        "full-not_counted-allowed-41": SLIM_THREE,
        "full-ALL-ALL-45": L_ONE_PATH,
        "full-ALL-allowed-31": SLIM_THREE,
        "full-not_counted-ALL-38": SLIM_ONE_STREET,
        "full-ALL-ALL-27": SLIM_ONE_STREET,
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
