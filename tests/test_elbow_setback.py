"""The setback zone is soft along the plot: where the plot bends at an elbow into two parts, each
part is as deep as the blocks that stand in it ask, not one depth round the whole plot for the
tallest of them (docs/behaviour-changes.md, 2026-10-13).

Made-up land only. What holds: a plot with no elbow is unchanged (one part, one depth); a part
with no block keeps the deepest depth of all (never more lenient than before); a tall block keeps
its own setback along the plot line near it whatever part it stands in; the search lays the same
depths the validator measures.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Polygon, box

from siteplan.geometry import ELBOW_MIN_PART_SQM, elbow_regions
from siteplan.optimizer.search.land import zone_ground
from siteplan.validator.zones import ramp_zones, setback_zone, zone_pieces

TEST_CLASS = "normative"

L_PLOT = Polygon([(0, 0), (200, 0), (200, 100), (40, 100), (40, 260), (0, 260)])  # body + arm
SQUARE = box(0, 0, 100, 100)
TALL_M, LOW_M = 10.0, 7.0


def test_a_plot_with_no_elbow_is_one_part():
    assert elbow_regions(SQUARE) == [SQUARE]


def test_an_l_plot_is_cut_across_its_neck_into_the_body_and_the_arm():
    parts = elbow_regions(L_PLOT)
    assert sorted(round(p.area) for p in parts) == [6400, 20000]
    assert sum(p.area for p in parts) == pytest.approx(L_PLOT.area)
    assert parts[0].intersection(parts[1]).area == pytest.approx(0)


def test_a_notch_or_a_gentle_bend_is_not_an_elbow():
    notch = Polygon([(0, 0), (100, 0), (100, 100), (52, 100), (52, 96), (48, 96), (48, 100),
                     (0, 100)])
    assert len(elbow_regions(notch)) == 1
    bend = Polygon([(0, 0), (100, 0), (100, 100), (60, 100), (50, 105), (40, 100), (0, 100)])
    assert len(elbow_regions(bend)) == 1  # the corners turn less than ELBOW_MIN_TURN_DEG
    assert ELBOW_MIN_PART_SQM > 0


def test_a_u_plot_is_three_parts():
    u_plot = Polygon([(0, 0), (150, 0), (150, 100), (100, 100), (100, 40), (50, 40), (50, 100),
                      (0, 100)])
    parts = elbow_regions(u_plot)
    assert len(parts) == 3 and sum(p.area for p in parts) == pytest.approx(u_plot.area)


# --- the validator's zone ----------------------------------------------------------------------


def _ctx(net: Polygon, blocks: dict[str, tuple[Polygon, float]]):
    """What the zone reads of a validation context: the plot, its parts, each block's footprint and
    the setback its band asks (the same on every side)."""
    classes = {name: SimpleNamespace(setback_m=m, front_m=m) for name, (_, m) in blocks.items()}
    towers = [SimpleNamespace(name=name, footprint=fp) for name, (fp, _) in blocks.items()]
    return SimpleNamespace(
        net=net, parts=elbow_regions(net), towers=towers, classes={"counted": classes},
        site=SimpleNamespace(access=SimpleNamespace(side=SimpleNamespace(value=None))),
        rules=SimpleNamespace(parking=SimpleNamespace(
            ramp_fire_clearance_m=SimpleNamespace(value=7.0))))


def _zone_depth_at(zone, x: float, y: float) -> float:
    """How deep the zone is from the plot's west edge (x = 0) at height y, looking east as far as
    `x`."""
    return zone.intersection(LineString([(0, y), (x, y)])).length


def test_a_plot_with_no_elbow_keeps_one_depth_for_the_tallest_block():
    ctx = _ctx(SQUARE, {"tall": (box(40, 40, 60, 60), TALL_M), "low": (box(10, 10, 20, 20), LOW_M)})
    zone = setback_zone(ctx, "counted")
    assert zone.symmetric_difference(SQUARE.difference(SQUARE.buffer(-TALL_M))).area < 1e-6


def test_the_arm_is_as_deep_as_its_own_block_and_the_body_as_deep_as_its_own():
    ctx = _ctx(L_PLOT, {"tall": (box(60, 20, 100, 60), TALL_M),
                        "low": (box(10, 150, 30, 190), LOW_M)})
    zone = setback_zone(ctx, "counted")
    assert _zone_depth_at(zone, 20, 200) == pytest.approx(LOW_M)  # the arm's west edge
    assert _zone_depth_at(zone, 50, 50) == pytest.approx(TALL_M)  # the body's west edge
    # the arm no longer keeps the body's depth; before this it did
    assert zone.area < L_PLOT.difference(L_PLOT.buffer(-TALL_M)).area


def test_a_part_with_no_block_keeps_the_deepest_depth_of_all():
    ctx = _ctx(L_PLOT, {"tall": (box(60, 20, 100, 60), TALL_M)})
    zone = setback_zone(ctx, "counted")
    assert _zone_depth_at(zone, 20, 200) == pytest.approx(TALL_M)


def test_every_block_keeps_its_own_setback_where_it_stands():
    # a block's own setback is a piece of the zone of its own, beside the part's: the tall block's
    # ten metres hold on the plot line within ten metres of it wherever that line lies
    ctx = _ctx(L_PLOT, {"tall": (box(50, 50, 90, 90), TALL_M),
                        "low": (box(10, 150, 30, 190), LOW_M)})
    pieces = zone_pieces(ctx, "counted")
    assert sorted(depth for _, depth, _ in pieces) == [LOW_M, LOW_M, TALL_M, TALL_M]


def test_the_ramp_zones_follow_the_pieces():
    ctx = _ctx(L_PLOT, {"tall": (box(60, 20, 100, 60), TALL_M),
                        "low": (box(10, 150, 30, 190), LOW_M)})
    forbidden, _ = ramp_zones(ctx, "counted")
    # a ramp leaves 7 m of a setback for fire vehicles: the inner 7 m of the body's 10 m, and the
    # whole of the arm's 7 m, as a 7 m setback is asked everywhere
    assert forbidden.intersection(LineString([(0, 50), (50, 50)])).length == pytest.approx(7)
    assert forbidden.intersection(LineString([(0, 200), (20, 200)])).length == pytest.approx(7)


# --- the search's zone -------------------------------------------------------------------------


def test_the_search_lays_each_part_with_its_own_depth_and_one_depth_without_parts():
    parts = elbow_regions(L_PLOT)
    arm = min(parts, key=lambda p: p.area)
    body = max(parts, key=lambda p: p.area)
    zone, interior = zone_ground(L_PLOT, TALL_M, [(body, TALL_M), (arm, LOW_M)])
    assert zone.union(interior).symmetric_difference(L_PLOT).area < 1e-6
    assert _zone_depth_at(zone, 20, 200) == pytest.approx(LOW_M)
    assert _zone_depth_at(zone, 50, 50) == pytest.approx(TALL_M)
    one, inside = zone_ground(L_PLOT, TALL_M)
    assert one.symmetric_difference(L_PLOT.difference(L_PLOT.buffer(-TALL_M, join_style="mitre"))
                                    ).area < 1e-6
    assert inside.area == pytest.approx(L_PLOT.buffer(-TALL_M, join_style="mitre").area)
