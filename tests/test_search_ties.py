"""The full search's choices never turn on the last digits of its geometry (C4-01a).

Where two of its answers are equal, the search chooses between them by a rule, never by
floating-point noise. The ring road's narrowness is tested a hair under a road: a ring drawn at
exactly the road's width and opened at exactly that width shrinks to a line whose last digits decide
what comes back. The fringe ranks the blocks it may place by their distance from the ring and their
place to the millimetre, and counts a block whose edge lies on its ground's edge as standing on it.
The generator's ledger takes its claims into one union at a time: GEOS 3.13's cascaded union of the
claims so far and a ring road whose hole a block lines dropped the block on Dhulapally. All three
were found when the roads were first drawn from centre lines (C4-01), which moves their last digits.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from search_support import proposal_on_the_l_plot, proposal_on_the_rectangle
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from siteplan.optimizer.search import fringe, network
from siteplan.optimizer.search.land import EMPTY, Land, grow

TEST_CLASS = "normative"

ROAD_M = 9.0


BLOCK = box(0, 0, 30, 60)
TIP = Polygon([(39, 69), (37, 69), (39, 67)])  # 2 m along each outer edge of the band's corner
SIDE = box(38, 20, 40, 40)  # 1 m into the band's east side, over 20 m


def _cluster(cut: Polygon, turn_deg: float):
    """One block, turned, with the ground a ring road exactly a road wide may take round it less
    `cut` (drawn in the block's own frame, then turned with it)."""
    hull = affinity.rotate(BLOCK, turn_deg, origin=(0, 0))
    roadable = affinity.rotate(grow(BLOCK, ROAD_M).difference(cut), turn_deg, origin=(0, 0))
    land = Land(zone=EMPTY, strip=EMPTY, roadable=roadable, cluster_land=hull, interior=hull)
    return network.cluster_of([hull], [], land, ROAD_M, ROAD_M)


@pytest.mark.parametrize("turn_deg", [14.4, 25.8, 27.3])
def test_a_ring_drawn_at_exactly_the_road_width_with_its_corner_tip_cut_is_still_a_road(turn_deg):
    """The cut takes 2 m² off the tip of the band's mitred corner, beyond a road's width, so every
    stretch of the ring is still a road wide: the cluster stands. Opened at exactly the width, at
    these turns the ring was called narrower than a road."""
    cluster, why = _cluster(TIP, turn_deg)
    assert cluster is not None, why
    assert cluster.clipped  # still a road wide, but less than the band asked for


@pytest.mark.parametrize("turn_deg", [0.0, 14.4, 72.3])
def test_a_ring_the_ground_cuts_into_is_still_narrower_than_a_road(turn_deg):
    """1 m into the band's side over 20 m leaves 8 m of road there: refused, as before."""
    cluster, why = _cluster(SIDE, turn_deg)
    assert cluster is None
    assert why == "the ring road is narrower than a road in places, where the ground cuts it"


@pytest.mark.parametrize("distances", [[1e-13, 0.0], [0.0, 1e-13]])
def test_between_blocks_equally_near_the_ring_the_last_digits_never_choose(distances):
    """Two blocks the ring touches, one 1e-13 m away by noise: the western one is taken either
    way, by its place, not by which of them the noise put nearer."""
    q = SimpleNamespace(pathway_m=6.0, pathway_any_block=False, pathway_max_height_m=12.0)
    choice = SimpleNamespace(value=100.0, cls=SimpleNamespace(gap_m=5.0, physical_m=30.0))
    west, east = box(10, 0, 30, 40), box(50, 0, 70, 40)
    fits = SimpleNamespace(of=lambda _: (np.array([west, east]), np.array(distances)))
    pick = fringe._best([choice], fits, EMPTY, EMPTY, q, box(-100, -100, 200, 200), 0.0)
    assert pick is not None and pick[0].equals(west)


def test_a_block_whose_edge_lies_on_its_grounds_edge_stands_on_it():
    """Ground a block's depth wide less 1e-9 m of noise holds the block."""
    ground = box(0, 0, 10 - 1e-9, 40)
    boxes = fringe._grid(ground, [ground], 10.0, 40.0)
    assert len(boxes) == 1 and boxes[0].equals(box(0, 0, 10, 40))


@pytest.mark.parametrize("proposal", [proposal_on_the_rectangle, proposal_on_the_l_plot])
def test_the_ledger_counts_every_square_metre_of_the_plot_once(proposal):
    for candidate in proposal().candidates:
        ledger = candidate.partition
        pieces = [unary_union([s.to_shapely() for s in e.shapes]) for e in ledger.entries]
        assert abs(sum(p.area for p in pieces) - ledger.net_area_sqm) < 0.01, \
            candidate.candidate_id
        assert abs(unary_union(pieces).area - ledger.net_area_sqm) < 0.01, \
            candidate.candidate_id
