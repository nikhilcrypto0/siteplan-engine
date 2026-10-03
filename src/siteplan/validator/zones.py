"""The regulatory zones on the net plot, rebuilt from the rules and the towers' own heights.

A setback zone is the net plot's own edge, as deep as the deepest Table IV setback any tower needs
under a reading of the stilt; a block gap is the ground between two blocks closer to both than
the gap they need; the green strip runs along the boundary where the setback reaches 9 m. None of
them is taken from an envelope or from the generator's rule layers.
"""

from __future__ import annotations

import math
from itertools import combinations

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

from siteplan.contracts.common import Side
from siteplan.validator.context import Context
from siteplan.validator.measure import required_gap
from siteplan.validator.shapes import union_of_all

COMPASS_DEG = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
FRONT_SECTOR_DEG = 45  # a boundary edge faces a side when its outward normal is within this
# Rule 13(c)(vii) lets a ramp use a side or rear setback "after leaving minimum 7m of setback for
# movement of fire-fighting vehicles". The 7 m is in the clause's text only; ResolvedRules carries
# the sentence (parking.ramp_in_setbacks), not the number.
RAMP_FIRE_LEAVE_M = 7.0


def deepest_setback_m(ctx: Context, reading: str) -> float | None:
    """The deepest Table IV setback any tower needs when the stilt is read as `reading`; None
    when no tower's row is usable."""
    values = [c.setback_m for c in ctx.classes.get(reading, {}).values()
              if c.setback_m is not None]
    return max(values) if values else None


def setback_zone(ctx: Context, reading: str) -> BaseGeometry | None:
    depth = deepest_setback_m(ctx, reading)
    return None if depth is None else ctx.net.difference(ctx.net.buffer(-depth))


def gap_zones(ctx: Context, reading: str, spacing: str) -> list[tuple[str, BaseGeometry]]:
    """For each pair of blocks, the ground between them that is within the gap they need of
    both: inside their joint outline, so not the ground beyond the ends of the facing walls, and
    never the blocks themselves."""
    classes = ctx.classes.get(reading, {})
    out = []
    for a, b in combinations(ctx.towers, 2):
        if a.name not in classes or b.name not in classes:
            continue
        need, why = required_gap(classes[a.name], classes[b.name], a.rule_height_m(reading),
                                 b.rule_height_m(reading), spacing)
        if need is None:
            continue
        blocks = union_of_all([a.footprint, b.footprint])
        zone = a.footprint.buffer(need).intersection(b.footprint.buffer(need))
        out.append((f"{a.name}/{b.name}", zone.intersection(blocks.convex_hull).difference(blocks)))
    return out


def green_strip_zone(ctx: Context, reading: str) -> BaseGeometry | None:
    """The peripheral strip the rules ask for where the setback reaches 9 m; None when the
    setback is shallower under this reading (or unknown), and so asks for none."""
    depth = deepest_setback_m(ctx, reading)
    green = ctx.rules.green_strip
    if depth is None or depth < green.where_setback_from_m.value:
        return None
    width = green.width_m.value
    return ctx.net.difference(ctx.net.buffer(-width, join_style="mitre"))


def front_edges(net, side: Side) -> list[LineString]:
    """The stretches of the plot's boundary that face the side the access road runs along."""
    centre = COMPASS_DEG[side]
    ring = list(orient(net, 1.0).exterior.coords)
    edges = []
    for a, b in zip(ring, ring[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        bearing = math.degrees(math.atan2(dy / length, -dx / length)) % 360  # outward normal
        if abs((bearing - centre + 180) % 360 - 180) < FRONT_SECTOR_DEG:
            edges.append(LineString([a, b]))
    return edges


def front_zone(ctx: Context, depth_m: float) -> BaseGeometry | None:
    """The land within `depth_m` of the front of the plot; None when the access side is not
    known."""
    side = ctx.site.access.side.value
    if side is None:
        return None
    edges = front_edges(ctx.net, side)
    return union_of_all([e.buffer(depth_m) for e in edges]).intersection(ctx.net)


def ramp_zones(ctx: Context, reading: str) -> tuple[BaseGeometry, BaseGeometry]:
    """Where a ramp may not be under a reading of the stilt, as (forbidden, forbidden only if it
    is the front). Forbidden: the front setback when the access side is known, and the part of
    any setback that would leave less than 7 m clear. When the access side is not known, the
    rest of the setback is the second shape: a ramp there is allowed in a side or rear setback
    and not in the front."""
    depth = deepest_setback_m(ctx, reading)
    if depth is None:
        return Polygon(), Polygon()
    zone = ctx.net.difference(ctx.net.buffer(-depth))
    keep_clear = zone if depth <= RAMP_FIRE_LEAVE_M else zone.intersection(
        ctx.net.buffer(-(depth - RAMP_FIRE_LEAVE_M)))
    front = front_zone(ctx, depth)
    if front is None:
        return keep_clear, zone.difference(keep_clear)
    return union_of_all([keep_clear, front.intersection(zone)]), Polygon()
