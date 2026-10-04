"""What stops a vehicle, a block or a bay: the obstacles on the site, gathered once.

Used wherever a check asks whether ground is free: the lanes round a tower, the turns of the loop
road, the width left to a road, a surface bay, a tot-lot.
"""

from __future__ import annotations

from shapely.geometry.base import BaseGeometry

from siteplan.validator.context import Context
from siteplan.validator.shapes import NOISE_SQM, union_of_all

BAYS = "a parking bay"  # the label under which the drawn bays are obstacles


class Ground:
    """Ground outside the plot, the planted strip, the water buffer, and everything built,
    parked or laid out on the site. A tower is not an obstacle to itself."""

    def __init__(self, ctx: Context):
        d = ctx.drawn
        self.net = ctx.net
        self.solids: list[tuple[str, BaseGeometry]] = [(t.name, t.footprint) for t in ctx.towers]
        self.solids += [("the club house", d.club),
                        ("an amenity", union_of_all([a.shape for a in d.amenities])),
                        (BAYS, union_of_all(list(d.bays))),
                        ("a tot-lot", union_of_all(list(d.open_space))),
                        ("a ramp", union_of_all(list(d.ramps)))]
        self.parts = [("the planted strip", d.green_strip),
                      ("a water buffer", ctx.land.keep_out), *self.solids]
        self.solid_land: BaseGeometry = union_of_all([g for _, g in self.solids])
        self._others: dict[str | None, BaseGeometry] = {}

    def _in_the_way(self, owner: str | None) -> BaseGeometry:
        if owner not in self._others:
            self._others[owner] = union_of_all([g for name, g in self.parts if name != owner])
        return self._others[owner]

    def blocked_area(self, shape: BaseGeometry, owner: str | None = None) -> float:
        """How much of a shape is off the plot, planted, in a water buffer or under something
        built, parked or laid out (not counting the owner's own footprint), each square metre
        once."""
        return shape.difference(self.net).area + shape.intersection(
            self._in_the_way(owner)).area

    def blocked_by(self, shape: BaseGeometry, owner: str | None = None) -> str:
        """In words: what is in the way of a shape, the biggest first."""
        found = {"ground off the plot": shape.difference(self.net).area}
        found.update({name: shape.intersection(g).area for name, g in self.parts
                      if name != owner and not g.is_empty})
        ranked = sorted(((a, n) for n, a in found.items() if a > NOISE_SQM), reverse=True)
        return ", ".join(f"{name} {area:,.1f} m²" for area, name in ranked[:3])

    def solid_area(self, shape: BaseGeometry) -> float:
        """How much of a shape has something built, parked or laid out on it."""
        return shape.intersection(self.solid_land).area
