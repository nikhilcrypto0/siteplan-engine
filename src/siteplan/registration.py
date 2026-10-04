"""Fit one drawing's outline onto another's frame by a rigid motion (turn and shift, no scale).

Made for one job: the firm's site-plan DXF draws the net plot (the boundary less the road strip)
in its own frame, and a debug run needs that outline in the survey's frame, where the roads and
any water are. The fit samples the moving outline every few metres, pairs each sample with the
nearest point of the fixed outline, and solves the best rigid motion for the pairs that agree
(iterative closest point, Kabsch). Where the two outlines differ (the strip side) the samples
stand off and are left out. The result says how well it fits, so a caller can refuse a bad one.

The fitted outline is FIRM_FINISHED_PLAN data: fit for a debug run, never for blind acceptance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon

SAMPLE_STEP_M = 2.0
ITERATIONS = 40
START_INLIER_M = 15.0  # pairs are trusted within this at first, tightening to FINAL_INLIER_M
FINAL_INLIER_M = 0.5
REFINE_ITERATIONS = 15  # then refine on pairs within REFINE_FACTOR x the median residual
REFINE_FACTOR = 3.0
REFINE_FLOOR_M = 0.005
CANDIDATE_EDGES = 4  # the longest runs of each outline tried against each other for the turn


@dataclass(frozen=True)
class Registration:
    polygon: Polygon  # the moving outline in the fixed outline's frame
    rotation_deg: float  # applied about the origin, then the shift
    shift: tuple[float, float]
    rms_m: float  # of the samples that agree
    agreeing_share: float  # of the moving outline's length within FINAL_INLIER_M of the fixed
    outside_sqm: float  # of the fitted outline lying outside the fixed outline
    gap_sqm: float  # of the fixed outline the fitted one does not cover

    def describe(self) -> str:
        return (f"turned {self.rotation_deg:.3f}°, shifted ({self.shift[0]:.3f}, "
                f"{self.shift[1]:.3f}) m; {self.agreeing_share:.0%} of the outline within "
                f"{FINAL_INLIER_M:g} m (RMS {self.rms_m:.3f} m); {self.outside_sqm:,.1f} m² "
                f"outside, {self.gap_sqm:,.1f} m² of the fixed outline not covered")


def register(moving: Polygon, fixed: Polygon) -> Registration:
    """The rigid motion that lays `moving` best onto `fixed`."""
    best = None
    for turn in _turns(moving, fixed):
        start = affinity.rotate(moving, turn, origin=(0, 0))
        shift = (fixed.centroid.x - start.centroid.x, fixed.centroid.y - start.centroid.y)
        start = affinity.translate(start, *shift)
        fitted, rms, share = _icp(start, fixed)
        if best is None or share > best[2] or (share == best[2] and rms < best[1]):
            best = (fitted, rms, share)
    fitted, rms, share = best
    rotation, shift = _motion(moving, fitted)
    return Registration(fitted, rotation, shift, rms, share,
                        fitted.difference(fixed).area, fixed.difference(fitted).area)


def _turns(moving: Polygon, fixed: Polygon) -> list[float]:
    """Candidate turns: each of the longest edges of one laid on each of the other's."""
    def longest(polygon):
        c = list(polygon.exterior.coords)
        edges = [(math.dist(a, b), math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))
                 for a, b in zip(c, c[1:], strict=False)]
        return [d for _, d in sorted(edges, reverse=True)[:CANDIDATE_EDGES]]

    turns = {round((f - m) % 360, 1) for f in longest(fixed) for m in longest(moving)}
    return sorted(turns)


def _samples(polygon: Polygon) -> np.ndarray:
    ring = polygon.exterior
    count = max(int(ring.length / SAMPLE_STEP_M), 8)
    return np.array([ring.interpolate(i * ring.length / count).coords[0] for i in range(count)])


def _icp(moving: Polygon, fixed: Polygon) -> tuple[Polygon, float, float]:
    current = moving
    ring = fixed.exterior
    for step in range(ITERATIONS + REFINE_ITERATIONS):
        source = _samples(current)
        target = np.array([ring.interpolate(ring.project(Point(p))).coords[0] for p in source])
        distance = np.linalg.norm(source - target, axis=1)
        if step < ITERATIONS:
            fraction = step / (ITERATIONS - 1)
            limit = START_INLIER_M * (FINAL_INLIER_M / START_INLIER_M) ** fraction
        else:  # refine on the pairs that truly agree, so stray pairs near a corner cannot pull
            agreeing = distance[distance <= FINAL_INLIER_M]
            limit = max(REFINE_FACTOR * float(np.median(agreeing)), REFINE_FLOOR_M) if len(
                agreeing) else FINAL_INLIER_M
        near = distance <= limit
        if near.sum() < 3:
            break
        rotation, shift = _kabsch(source[near], target[near])
        angle = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
        current = affinity.translate(affinity.rotate(current, angle, origin=(0, 0)), *shift)
    source = _samples(current)
    target = np.array([ring.interpolate(ring.project(Point(p))).coords[0] for p in source])
    distance = np.linalg.norm(source - target, axis=1)
    near = distance <= FINAL_INLIER_M
    rms = float(np.sqrt(np.mean(distance[near] ** 2))) if near.any() else math.inf
    return current, rms, float(near.mean())


def _kabsch(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The rotation (about the origin) and shift that best carry source onto target."""
    cs, ct = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source - cs).T @ (target - ct))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rotation = vt.T @ np.diag([1.0, d]) @ u.T
    return rotation, ct - rotation @ cs


def _motion(original: Polygon, fitted: Polygon) -> tuple[float, tuple[float, float]]:
    """The single turn about the origin and shift that carry the original onto the fitted."""
    a = np.array(original.exterior.coords[:-1])
    b = np.array(fitted.exterior.coords[:-1])
    rotation, shift = _kabsch(a, b)
    return math.degrees(math.atan2(rotation[1, 0], rotation[0, 0])), (float(shift[0]),
                                                                      float(shift[1]))
