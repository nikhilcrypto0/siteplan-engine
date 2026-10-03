"""What stops a vehicle, a block or a bay: the obstacles on the site, gathered once.

Used wherever a check asks whether ground is free: the lanes round a tower, the turns of the loop
road, the width left to a road, a surface bay, a tot-lot.
"""

from __future__ import annotations

from shapely.geometry.base import BaseGeometry

from siteplan.validator.context import Context
from siteplan.validator.shapes import union_of_all


class Ground:
    """Ground outside the plot, the planted strip, the water buffer, and everything built,
    parked or laid out on the site. A tower is not an obstacle to itself."""

    def __init__(self, ctx: Context):
        d = ctx.drawn
        self.net = ctx.net
        self.barred = union_of_all([d.green_strip, ctx.land.keep_out])
        self.solids: list[tuple[str, BaseGeometry]] = [(t.name, t.footprint) for t in ctx.towers]
        self.solids += [("club house", d.club),
                        ("amenities", union_of_all([a.shape for a in d.amenities])),
                        ("bays", union_of_all(list(d.bays))),
                        ("open space", union_of_all(list(d.open_space))),
                        ("ramps", union_of_all(list(d.ramps)))]
        self._others: dict[str | None, BaseGeometry] = {}
        self.solid_land: BaseGeometry = union_of_all([g for _, g in self.solids])

    def _in_the_way(self, owner: str | None) -> BaseGeometry:
        if owner not in self._others:
            self._others[owner] = union_of_all(
                [self.barred, *(g for o, g in self.solids if o != owner)])
        return self._others[owner]

    def blocked_area(self, shape: BaseGeometry, owner: str | None = None) -> float:
        """How much of a shape is off the plot, planted, in a water buffer or under something
        built, parked or laid out (not counting the owner's own footprint)."""
        return shape.difference(self.net).area + shape.intersection(
            self._in_the_way(owner)).area

    def solid_area(self, shape: BaseGeometry) -> float:
        """How much of a shape has something built, parked or laid out on it."""
        return shape.intersection(self.solid_land).area
