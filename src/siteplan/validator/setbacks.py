"""A block's setback from the plot line, the front held apart from the other sides.

A band gives one setback all round, or a front figure for the stretches of the plot line that face
the side the access road runs on and a setback for every other side (rule 5 Table III's Building
Line; for a high-rise, rule 7(a)(xi)'s higher of Table IV and that line). Which stretches are the
front is the site model's access side (`zones.edge_groups`); where that side is not known the
front cannot be placed, and a block passes only if it clears the larger figure on every side and
fails only if it misses the smaller one somewhere.

The distances are measured on the net plot (rule 7(a)(iii)); a block that is not wholly on it
meets no row of any table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.contracts.common import Status
from siteplan.validator.context import Context
from siteplan.validator.measure import (
    FRONT_NOTE,
    FRONT_UNKNOWN_NOTE,
    TOL_M,
    UNCONFIRMED_NOTE,
    HeightClass,
    setback_of,
)
from siteplan.validator.readings import Cell, verdict
from siteplan.validator.zones import edge_groups


@dataclass(frozen=True)
class Distances:
    """How far a footprint stands from the plot line."""

    nearest_m: float  # anywhere on it: nothing when the footprint is not wholly on the net plot
    front_m: float | None  # from the stretches facing the access road; None: they are not known
    other_m: float | None  # from every other stretch; infinite when there is none


def _from(footprint: Polygon, geometry: BaseGeometry) -> float:
    return math.inf if geometry.is_empty else float(footprint.distance(geometry))


def plot_line_distances(ctx: Context, footprint: Polygon) -> Distances:
    nearest = setback_of(ctx.net, footprint)
    groups = edge_groups(ctx)
    if groups is None:
        return Distances(nearest, None, None)
    return Distances(nearest, _from(footprint, groups[0]), _from(footprint, groups[1]))


def _metres(value: float | None) -> str:
    return "no other side" if value is None or math.isinf(value) else f"{value:.2f} m"


def _figures(cls: HeightClass) -> tuple[float, float, bool]:
    """(front, other sides, whether they are one figure)."""
    front, side = cls.front_m, cls.setback_m
    return front, side, abs(front - side) <= TOL_M


def setback_cell(ctx: Context, footprint: Polygon, d: Distances, cls: HeightClass) -> Cell:
    """A footprint's distances from the plot line against its band's setback; the band is one the
    rules model (`cls.settled`). One figure is held all round; two are held apart, the front on
    the stretches facing the access road. A band the rules mark UNVERIFIED settles nothing."""
    front, side, one = _figures(cls)
    outside = not ctx.net.contains(footprint)
    side_name = ctx.site.access.side.value
    if one:
        required = f">= {side:.2f} m to the net plot line"
        shown, note = f"{d.nearest_m:.2f} m", cls.all_round_note
        passes: bool | None = d.nearest_m + TOL_M >= side
    elif d.front_m is not None:
        required = (f">= {front:.2f} m at the front (the {side_name} side), >= {side:.2f} m on "
                    "the other sides")
        shown = f"{d.front_m:.2f} m at the front, {_metres(d.other_m)} on the other sides"
        note = FRONT_NOTE
        other = math.inf if d.other_m is None else d.other_m
        passes = d.front_m + TOL_M >= front and other + TOL_M >= side
    else:
        required = f">= {front:.2f} m at the front, >= {side:.2f} m on the other sides"
        shown = f"{d.nearest_m:.2f} m (which side is the front is not known)"
        note = FRONT_UNKNOWN_NOTE
        most, least = max(front, side), min(front, side)
        passes = (True if d.nearest_m + TOL_M >= most
                  else False if d.nearest_m + TOL_M < least else None)
    if outside:  # no row of any table is met by a block that is not on the plot
        return Cell(Status.FAIL, f"{d.nearest_m:.2f} m: not wholly inside the net plot", required)
    if not cls.confirmed:
        return Cell(Status.UNVERIFIED, shown, required, f"{note} {UNCONFIRMED_NOTE}")
    if passes is None:
        return Cell(Status.UNVERIFIED, shown, required, note)
    return Cell(verdict(passes), shown, required, note)


@dataclass(frozen=True)
class Margin:
    """What a block keeps beyond its setback on one side of the plot: provided against needed."""

    tower: str
    reading: str
    provided: float
    need: float
    where: str  # '' all round, else 'front' or 'other sides'


def setback_margins(ctx: Context) -> list[Margin]:
    """Every distance a block's setback is held to, under every reading of the stilt, for the
    design targets: all round where the band gives one figure, the front and the other sides apart
    where it gives two and the front is known, the larger figure all round where it is not."""
    out = []
    for t in ctx.towers:
        d = plot_line_distances(ctx, t.footprint)
        for reading, classes in ctx.classes.items():
            cls = classes[t.name]
            if not cls.settled:
                continue
            front, side, one = _figures(cls)
            if one:
                out.append(Margin(t.name, reading, d.nearest_m, side, ""))
            elif d.front_m is not None:
                out.append(Margin(t.name, reading, d.front_m, front, "front"))
                if d.other_m is not None and math.isfinite(d.other_m):
                    out.append(Margin(t.name, reading, d.other_m, side, "other sides"))
            else:
                out.append(Margin(t.name, reading, d.nearest_m, max(front, side), ""))
    return out
