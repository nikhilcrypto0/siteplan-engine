"""A further cluster turned to its own ground (C4-03).

The first cluster stands in its configuration's direction. A further cluster (C4-02) is tried in
that direction and in the directions of the ground it would stand on: its principal axis and along
and across its longest edges, no two within the turned frame's tolerance, a few at most; the most
valuable that can be joined is kept, and its blocks carry their own frame to the placement. A ring
turned to its own ground reaches further out at its mitred corners than along its sides, so a
further cluster is refused where its ring would run over a laid cluster or a laid ring over it, or
where its ring would meet a laid ring at an angle (where two rings overlap askew the corner of one
sticks out of the other in a wedge narrower than a road): a turned cluster stands apart, joined by
a link road. Everything runs on made-up land.
"""

from __future__ import annotations

import math
import warnings
from functools import cache

import pytest
from search_support import made_up, rectangle
from shapely import affinity
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from siteplan.contracts.candidate import RoadKind
from siteplan.optimizer.search import network
from siteplan.optimizer.search.build import placement_of
from siteplan.optimizer.search.columns import Standing, choices_for
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.layout import (
    ZONE_ANGLES,
    Config,
    Failure,
    _meets_askew,
    _principal_axis_deg,
    _rings_cross_clusters,
    evaluate,
    lay_out,
    make_run,
    zone_angles,
)
from siteplan.optimizer.search.readings import profiles
from siteplan.optimizer.search.road_graph import Road

TEST_CLASS = "normative"

BODY = box(0, 0, 200, 110)
ARM = affinity.rotate(box(100, 60, 200, 270), 30, origin=(150, 110))  # turned 30 degrees


@cache
def _bent_l():
    made = made_up(unary_union([BODY, ARM]).buffer(0))
    found = profiles(made.rules, made.brief, list(made.kit))
    return made, found, make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)


def _angle_gap(a: float, b: float) -> float:
    d = abs(a - b) % 180
    return min(d, 180 - d)


@pytest.mark.parametrize("turn_deg", [0.0, 23.0, 61.5, 118.0])
def test_the_principal_axis_is_the_long_side_of_the_least_rectangle(turn_deg):
    piece = affinity.rotate(box(0, 0, 100, 20), turn_deg, origin=(0, 0))
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)  # no division by a vertical edge
        assert _angle_gap(_principal_axis_deg(piece), turn_deg) < 1e-6


def test_a_zone_is_tried_in_its_configurations_direction_first_and_then_its_own():
    zone = affinity.rotate(box(0, 0, 150, 40), 30, origin=(0, 0))
    angles = zone_angles(zone, 0.0, 100.0)
    assert angles[0] == 0.0 and len(angles) <= ZONE_ANGLES
    assert any(_angle_gap(a, 30.0) < 1e-6 for a in angles)  # its principal axis
    assert all(_angle_gap(a, b) > 5 for i, a in enumerate(angles) for b in angles[i + 1:])
    assert zone_angles(zone, 0.0, zone.area * 2) == [0.0]  # too small for a block


def test_a_block_laid_in_a_frame_of_its_own_is_placed_in_it():
    made = rectangle()
    found = profiles(made.rules, made.brief, list(made.kit))
    run = make_run(made.site, made.rules, made.brief, made.envelope, made.kit, found)
    choice = choices_for(run.kit, run.classes[found[0].key])[0]
    own, given = Frame(30.0), Frame(0.0)
    placed = placement_of(Standing(choice, 0, 10.0, 20.0, own), "T1", given)
    assert placed.rotation_deg == 30.0
    upright = box(10.0, 20.0, 10.0 + choice.depth_m, 20.0 + choice.length_m)
    assert placed.footprint.symmetric_difference(own.to_survey(upright)).area < 1e-6


def test_a_further_cluster_stands_in_its_own_grounds_direction_joined_by_a_link_road():
    made, found, run = _bent_l()
    profile = next(p for p in found if p.key == "ALL-ALL")
    ev = evaluate(run, Config(profile, 0.0, 0.0, 9, more_clusters=True))
    assert not isinstance(ev, Failure), getattr(ev, "reason", "")
    turned = {round(s.frame.angle_deg, 6) for s in ev.standing if s.frame is not None}
    assert turned and all(_angle_gap(a, 0.0) > 5 for a in turned)
    assert ev.links and all(not link.ground.is_empty for link in ev.links)  # a road, not a joint
    laid, why = lay_out(run, ev)
    assert laid is not None, why
    assert len(laid.graph.of_kind(RoadKind.LOOP)) == 2 and laid.graph.problems() == []
    rotations = {round(p.rotation_deg % 180, 6) for p in laid.placements}
    assert len(rotations) == 2  # the body's blocks and the turned cluster's


def test_a_ring_that_meets_another_at_an_angle_is_refused_and_one_that_runs_the_same_way_not():
    hull = box(0, 0, 60, 30)
    laid = [network.Cluster(hull, Road("ring", RoadKind.LOOP, network.ring_centre(hull, 9.0),
                                       9.0))]
    joint = Road("link-1", RoadKind.INTERNAL, LineString([(80, 15), (64.5, 15)]), 9.0,
                 box(0, 0, 0, 0).buffer(0))
    paved = Road("link-1", RoadKind.INTERNAL, LineString([(80, 15), (64.5, 15)]), 9.0,
                 box(-100, -100, 200, 200))
    assert joint.ground.is_empty and not paved.ground.is_empty
    assert _meets_askew(joint, Frame(20.0), laid, [0.0])
    assert not _meets_askew(joint, Frame(0.0), laid, [0.0])
    assert not _meets_askew(paved, Frame(20.0), laid, [0.0])


def test_a_ring_whose_mitred_corner_reaches_a_laid_cluster_is_refused():
    first = box(0, 0, 60, 30)
    laid = [network.Cluster(first, Road("ring", RoadKind.LOOP, network.ring_centre(first, 9.0),
                                        9.0))]
    # a turned block a street's width (10 m) from the first at its nearest, corner first
    turned = affinity.rotate(box(0, 0, 40, 20), 45, origin=(0, 0))
    gap = turned.bounds[0]
    turned = affinity.translate(turned, 60 + 10 - gap, 5)
    assert math.isclose(turned.distance(first), 10.0, abs_tol=1e-6)
    further = network.Cluster(turned, Road("ring-2", RoadKind.LOOP,
                                           network.ring_centre(turned, 9.0), 9.0))
    assert _rings_cross_clusters(further, laid)
    far = affinity.translate(turned, 30, 0)
    assert not _rings_cross_clusters(network.Cluster(far, Road(
        "ring-2", RoadKind.LOOP, network.ring_centre(far, 9.0), 9.0)), laid)
