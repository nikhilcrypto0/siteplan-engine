"""The turned frame: the site rotated so that the blocks' long axis runs along y.

Towers are laid in columns across x, each column a strip as deep as a block, so the search works in
a frame where a column is a vertical strip. Everything after the towers are placed (the roads, the
fire lanes, the open space) is plain geometry in the survey's own frame: a tower is placed with its
long axis at `angle_deg`, which is the turn that takes the prototype's x axis onto the column.

A prototype's footprint lies centred on its origin with its long axis along x
(`TowerPrototype`). In the turned frame it is turned a quarter turn, so it stands along y.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Frame:
    angle_deg: float  # where the blocks' long axis points in the survey's frame, 0 to 180

    @property
    def turn_deg(self) -> float:
        """How far the survey is turned to bring the blocks' long axis onto y."""
        return 90.0 - self.angle_deg

    def to_turned(self, geometry: BaseGeometry) -> BaseGeometry:
        return affinity.rotate(geometry, self.turn_deg, origin=(0, 0))

    def to_survey(self, geometry: BaseGeometry) -> BaseGeometry:
        return affinity.rotate(geometry, -self.turn_deg, origin=(0, 0))

    def point_to_survey(self, x: float, y: float) -> tuple[float, float]:
        radians = math.radians(-self.turn_deg)
        c, s = math.cos(radians), math.sin(radians)
        return x * c - y * s, x * s + y * c


def distinct_angles(angles: list[float], tolerance_deg: float = 5.0) -> list[float]:
    """The angles worth trying, modulo 180, no two within the tolerance of each other; the order
    given is kept."""
    kept: list[float] = []
    for angle in angles:
        angle %= 180.0
        if all(min(abs(angle - other) % 180.0, 180.0 - abs(angle - other) % 180.0) > tolerance_deg
               for other in kept):
            kept.append(angle)
    return kept
