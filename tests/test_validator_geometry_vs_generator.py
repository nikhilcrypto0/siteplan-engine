"""The validator's own geometry against the generator's, shape by shape: where today's code
and the rebuilt code give the same answer they are interchangeable, and when one of them
changes, this says which. Characterization: it pins the agreement of today, not a law."""

import pytest
from shapely.affinity import rotate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from validator_helpers import fixture

from siteplan import access
from siteplan.geometry import opening as generator_opening
from siteplan.validator.shapes import healed, opening
from siteplan.validator.turning import road_bends, round_block, turning_for

TEST_CLASS = "characterization"

BLOCKS = {
    "a slab": box(0, 0, 60, 18),
    "a turned slab": rotate(box(0, 0, 60, 18), 37, origin=(0, 0)),
    "an L": Polygon([(0, 0), (40, 0), (40, 14), (16, 14), (16, 30), (0, 30)]),
}


def _same_sectors(mine, theirs, share=0.01):
    assert len(mine) == len(theirs)
    key = lambda s: (round(s.centroid.x, 3), round(s.centroid.y, 3))  # noqa: E731
    for a, b in zip(sorted(mine, key=key), sorted(theirs, key=key), strict=True):
        assert a.symmetric_difference(b).area <= share * b.area


def test_the_clear_ground_a_turn_needs_is_the_generators_fire_band():
    turning = turning_for(fixture("rectangle").rules, "outer_edge")
    assert turning.reach_m == pytest.approx(access.FIRE_BAND_M)
    assert (turning.r_in, turning.r_out) == (access.R_IN, access.R_OUT)


@pytest.mark.parametrize("name", list(BLOCKS))
def test_the_sectors_round_a_block_are_the_generators(name):
    turning = turning_for(fixture("rectangle").rules, "outer_edge")
    _same_sectors(round_block(BLOCKS[name], turning), access.around_block(BLOCKS[name]))


@pytest.mark.parametrize("site", ["rectangle", "l_plot_with_arm", "nala_plot"])
def test_the_bends_of_a_loop_road_are_the_generators(site):
    inputs = fixture(site)
    loop = unary_union([s.to_shapely() for r in inputs.candidate.circulation.roads
                        if r.kind.value == "LOOP" for s in r.shapes])
    turning = turning_for(inputs.rules, "outer_edge")
    _same_sectors(road_bends(loop, turning), access.loop_turns(loop))


def test_closing_hairline_cracks_is_the_same_operation():
    pieces = box(0, 0, 10, 9).union(box(10.04, 0, 20, 9))
    assert healed(pieces).area == pytest.approx(access.healed(pieces).area)


@pytest.mark.parametrize("width", [3.0, 6.0, 8.98])
def test_an_opening_agrees_with_the_generators_away_from_the_exact_width(width):
    shape = box(0, 0, 60, 9).union(box(0, 0, 9, 40)).union(box(30, 20, 50, 34))
    assert opening(shape, width).area == pytest.approx(generator_opening(shape, width).area,
                                                       rel=1e-6)
