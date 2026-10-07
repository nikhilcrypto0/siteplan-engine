"""The fringe's search (C4-05): a kind of block whose nearest places all fail no longer ends the
search, a smaller or lower one is tried next; and the fringe is laid in the plot's own directions
as well as the configuration's, so a band turned from the columns takes blocks turned with it.
Made-up land and made-up blocks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely import affinity
from shapely.geometry import box

from siteplan.optimizer.search import fringe
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.land import EMPTY, Land, Plot

TEST_CLASS = "normative"

Q = SimpleNamespace(pathway_m=6.0, pathway_any_block=False, pathway_max_height_m=12.0,
                    gap_margin_m=0.0, lane_m=6.0, reach_m=6.88)
UPRIGHT = Frame(90.0)  # the turned frame is the survey's own: the blocks' long axis along y
LOW = SimpleNamespace(front=0.0, setback_m=0.0, gap_m=5.0, high_rise=False, physical_m=18.0)


def _block(name: str, depth: float, length: float, value: float):
    return SimpleNamespace(prototype=SimpleNamespace(id=name), cls=LOW, depth_m=depth,
                           length_m=length, value=value)


def _place(net, ring, ground, choices, frame=UPRIGHT, room_sqm=0.0):
    plot = Plot(net=net, excluded=EMPTY, gate_runs=(), access_side=None)
    land = Land(zone=EMPTY, strip=EMPTY, roadable=net, cluster_land=EMPTY, interior=net)
    return fringe.place(plot, Q, frame, land, ring, EMPTY, [], choices,
                        own={(0.0, 0.0): ground}, kept_clear=None, roads_in_setback=True,
                        eps_m=0.01, room_sqm=room_sqm)


def test_a_kind_none_of_whose_places_leaves_the_room_is_passed_over_for_a_smaller_one():
    """Along a ring road on the south, 100 m of ground 51 m deep: the 20 x 40 m block leaves less
    free ground than the rest of the layout needs wherever it stands, the 20 x 20 m one does not.
    The greedy tried the big block's nearest places and gave up; the small one stands now."""
    net, ring, ground = box(0, 0, 100, 60), box(0, 0, 100, 9), box(0, 9, 100, 60)
    big, small = _block("big", 20.0, 40.0, 100.0), _block("small", 20.0, 20.0, 50.0)
    free = ground.area
    room = free - 1000.0  # the big block's 25-30 x 45 m with its gap leaves less, the small one's
    placed = _place(net, ring, ground, [big, small], room_sqm=room)  # 25-30 x 25 m more
    assert [f.standing.choice.prototype.id for f in placed] == ["small"]


def test_where_the_most_valuable_kind_stands_the_search_is_as_before():
    net, ring, ground = box(0, 0, 100, 60), box(0, 0, 100, 9), box(0, 9, 100, 60)
    big, small = _block("big", 20.0, 40.0, 100.0), _block("small", 20.0, 20.0, 50.0)
    placed = _place(net, ring, ground, [big, small])
    assert [f.standing.choice.prototype.id for f in placed][0] == "big"
    assert all(f.standing.frame is None for f in placed)  # in the configuration's direction


@pytest.mark.parametrize("turn_deg", [30.0, 140.0])
def test_a_band_turned_from_the_columns_takes_blocks_turned_with_it(turn_deg):
    """A band 200 m long and 40 m wide, turned from the configuration's direction, a ring road
    along its long side: no upright 20 x 40 m block fits in the 31 m left, one turned to the band
    does, standing against the road, in the band's own frame."""
    def turned(shape):
        return affinity.rotate(shape, turn_deg, origin=(0, 0))
    net, ring, ground = turned(box(0, 0, 200, 40)), turned(box(0, 0, 200, 9)), \
        turned(box(0, 9, 200, 40))
    block = _block("block", 20.0, 40.0, 100.0)
    placed = _place(net, ring, ground, [block])
    assert len(placed) >= 3
    for f in placed:
        assert f.standing.frame is not None
        assert abs((f.standing.frame.angle_deg - turn_deg) % 180.0) < 1e-6 \
            or abs((f.standing.frame.angle_deg - turn_deg - 90.0) % 180.0) < 1e-6
        footprint = f.standing.frame.to_survey(
            box(f.standing.x0, f.standing.y0, f.standing.x1, f.standing.y1))
        assert ground.buffer(0.02).contains(footprint)
        assert footprint.distance(ring) <= 0.05  # against the road: no pathway is needed
        assert f.path is None


def test_a_block_may_stand_flush_against_either_edge_of_its_ground():
    """Ground 33.5 m wide and 40 m long holds a 20 m deep block every metre from its west edge
    and flush against its east edge, where a road on that side is."""
    ground = box(0, 0, 33.5, 40)
    xs = sorted(round(b.bounds[0], 6) for b in fringe._grid(ground, [ground], 20.0, 40.0))
    assert xs[0] == 0.0 and xs[-1] == 13.5
