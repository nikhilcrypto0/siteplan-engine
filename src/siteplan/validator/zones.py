"""The regulatory zones on the net plot, rebuilt from the rules and the towers' own heights.

A setback zone is the net plot's own edge, as deep as the deepest Table IV setback any tower needs
under a reading of the stilt; a block gap is the ground between two blocks closer to both than
the gap they need; the green strip runs along the boundary where the setback reaches 9 m. None of
them is taken from an envelope or from the generator's rule layers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

from siteplan.contracts.common import Side
from siteplan.geometry import COMPASS_DEG, faces
from siteplan.validator.context import Context
from siteplan.validator.measure import required_gap
from siteplan.validator.shapes import mitred, union_of_all

DEPTH_EPS_M = 1e-9  # two setbacks this close are one figure


def setback_depths(ctx: Context, reading: str) -> tuple[float, float] | None:
    """The deepest setbacks any block needs when the stilt is read as `reading`, as (at the front,
    on every other side): a band's front figure is its setback where it gives none. None when no
    block's row is usable."""
    classes = [c for c in ctx.classes.get(reading, {}).values() if c.setback_m is not None]
    if not classes:
        return None
    return max(c.front_m for c in classes), max(c.setback_m for c in classes)


def deepest_setback_m(ctx: Context, reading: str) -> float | None:
    """The deepest setback any block needs, on any side, when the stilt is read as `reading`;
    None when no block's row is usable."""
    depths = setback_depths(ctx, reading)
    return None if depths is None else max(depths)


def edge_groups(ctx: Context) -> tuple[BaseGeometry, BaseGeometry] | None:
    """The stretches of the plot line that face the side the access road runs on, and the rest;
    None when that side is not known or no stretch faces it."""
    side = ctx.site.access.side.value
    if side is None:
        return None
    edges = boundary_edges(ctx.net)
    front = [e for e, bearing in edges if faces(bearing, side)]
    if not front:
        return None
    return (union_of_all(front),
            union_of_all([e for e, bearing in edges if not faces(bearing, side)]))


def setback_zone(ctx: Context, reading: str) -> BaseGeometry | None:
    """The mandatory setback as ground: the plot's own edge as deep as the deepest setback needs.
    Where the bands give a front figure of their own, the front stretches are as deep as it and
    the rest as deep as the setback; where the front cannot be told, all round as deep as the
    larger, never more lenient."""
    depths = setback_depths(ctx, reading)
    if depths is None:
        return None
    front, side = depths
    groups = edge_groups(ctx) if abs(front - side) > DEPTH_EPS_M else None
    if groups is not None:
        return union_of_all([groups[0].buffer(front), groups[1].buffer(side)]
                            ).intersection(ctx.net)
    return ctx.net.difference(ctx.net.buffer(-max(front, side)))


def gap_zones(ctx: Context, reading: str, spacing: str) -> list[tuple[str, BaseGeometry]]:
    """For each pair of blocks, the ground between them that is within the gap they need of
    both: inside their joint outline, so not the ground beyond the ends of the facing walls, and
    never the blocks themselves."""
    classes = ctx.classes.get(reading, {})
    out = []
    for a, b in combinations(ctx.towers, 2):
        if a.name not in classes or b.name not in classes:
            continue
        need, why = required_gap(classes[a.name], classes[b.name], spacing)
        if need is None:
            continue
        blocks = union_of_all([a.footprint, b.footprint])
        zone = a.footprint.buffer(need).intersection(b.footprint.buffer(need))
        out.append((f"{a.name}/{b.name}", zone.intersection(blocks.convex_hull).difference(blocks)))
    return out


@dataclass(frozen=True)
class StripAsk:
    """A planting strip the blocks' bands ask: how wide, and along which stretches of the plot
    line (the front, the other sides, or both). It lies within the setbacks and is never added to
    them."""

    width_m: float
    front: bool
    others: bool
    given: bool  # the band says so (`Band.green_strip_m`), rather than the high-rise rule below


def strips_asked(ctx: Context, reading: str) -> list[StripAsk]:
    """The planting each block's band asks under a reading of the stilt. A band that carries a
    strip (`green_strip_m`, along all sides or the frontage) says it itself; a high-rise band that
    carries none is held to the high-rise strip, rule 7(a)(viii): `width_m` where its setback
    reaches `where_setback_from_m`, on the stretches where it does. A band below the high-rise
    height that carries none asks none."""
    green = ctx.rules.green_strip
    found: list[StripAsk] = []
    for cls in ctx.classes.get(reading, {}).values():
        if not cls.settled:
            continue
        band = cls.band
        if band.green_strip_m is not None:
            if band.green_strip_m > 0:
                found.append(StripAsk(band.green_strip_m, True, band.green_strip_sides == "ALL",
                                      True))
        elif cls.high_rise:
            where = green.where_setback_from_m.value
            front, others = cls.front_m >= where, cls.setback_m >= where
            if front or others:
                found.append(StripAsk(green.width_m.value, front, others, False))
    return list(dict.fromkeys(found))


def green_strip_zones(ctx: Context, reading: str) -> tuple[BaseGeometry, BaseGeometry] | None:
    """The ground that must be planted under a reading, as (certainly, possibly); None when no
    band asks a strip. A strip along the whole plot line, or along the front or the other sides
    where the access road's side is known, is certain. Where that side is not known a strip along
    only part of the plot line cannot be placed: the whole periphery of its width is possible."""
    asked = strips_asked(ctx, reading)
    if not asked:
        return None
    groups = edge_groups(ctx)
    certain: list[BaseGeometry] = []
    possible: list[BaseGeometry] = []
    for ask in asked:
        around = ctx.net.difference(mitred(ctx.net, -ask.width_m))
        if ask.front and ask.others:
            certain.append(around)
        elif groups is None:
            possible.append(around)
        else:
            edges = groups[0] if ask.front else groups[1]
            certain.append(edges.buffer(ask.width_m).intersection(ctx.net))
    return union_of_all(certain), union_of_all(possible)


def green_strip_zone(ctx: Context, reading: str) -> BaseGeometry | None:
    """The ground a strip may be asked of, certainly or possibly (for the rule layers and the
    ledger); None when no band asks one."""
    zones = green_strip_zones(ctx, reading)
    return None if zones is None else union_of_all(list(zones))


def compass_name(bearing_deg: float) -> str:
    """The nearest of the eight compass points to a bearing (degrees clockwise from north)."""
    return list(COMPASS_DEG)[round((bearing_deg % 360) / 45) % 8]


def boundary_edges(net: Polygon) -> list[tuple[LineString, float]]:
    """Every stretch of the plot's boundary with the bearing its outward normal faces."""
    edges = []
    oriented = orient(net, 1.0)
    for ring in [oriented.exterior, *oriented.interiors]:
        coords = list(ring.coords)
        for a, b in zip(coords, coords[1:], strict=False):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            bearing = math.degrees(math.atan2(dy / length, -dx / length)) % 360  # outward normal
            edges.append((LineString([a, b]), bearing))
    return edges


def bearings_near(net: Polygon, shape: BaseGeometry, within_m: float) -> list[float]:
    """The bearings the plot's boundary faces where a shape stands: the nearest stretch and any
    other within `within_m` of it (a gate at a corner stands in two sides)."""
    edges = boundary_edges(net)
    if shape.is_empty or not edges:
        return []
    nearest = min(shape.distance(e) for e, _ in edges)
    return [bearing for e, bearing in edges if shape.distance(e) <= nearest + within_m]


def front_edges(net, side: Side) -> list[LineString]:
    """The stretches of the plot's boundary that face the side the access road runs along, as
    `geometry.faces` reads a side (the envelope and the search read it the same way): within 45
    degrees either way, a diagonal side half a compass step more, so a diagonal side (north-east)
    takes in both the sides it lies between: a ramp barred from the front is barred from
    either."""
    return [edge for edge, bearing in boundary_edges(net) if faces(bearing, side)]


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
    depths = setback_depths(ctx, reading)
    if depths is None:
        return Polygon(), Polygon()
    front_depth, side_depth = depths
    split = abs(front_depth - side_depth) > DEPTH_EPS_M and edge_groups(ctx) is not None
    depth = side_depth if split else max(front_depth, side_depth)
    zone = setback_zone(ctx, reading)
    # Rule 13(c)(vii): a ramp in a side or rear setback leaves this much for fire vehicles.
    leave = ctx.rules.parking.ramp_fire_clearance_m.value
    keep_clear = zone if depth <= leave else zone.intersection(
        ctx.net.buffer(-(depth - leave)))
    front = front_zone(ctx, front_depth if split else depth)
    if front is None:
        return keep_clear, zone.difference(keep_clear)
    return union_of_all([keep_clear, front.intersection(zone)]), Polygon()
