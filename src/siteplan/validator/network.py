"""How the roads join one another and the entrance: the topology rule 8(m) is about.

A through road meets another road, or a gate, at both ends; a road that stops short of everything
has an end a fire tender cannot turn out of. Roads are drawn as areas, not as lines, so a junction
is ground where two roads (each grown by the touch distance) share more than a corner, and
junctions closer together than a road is wide are one junction. A road with fewer than two has an
end that meets nothing.

A perimeter lane inside the setback is a test assumption, not an established 8(m) road: a road
that meets only it is UNVERIFIED, not a dead end and not a through road.

Not found by this: a spur drawn into the polygon of a through road, which cannot be told from the
road's own shape without a skeleton of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Status
from siteplan.contracts.validation import Check, Family
from siteplan.validator.context import Context
from siteplan.validator.drawn import DrawnRoad
from siteplan.validator.ground import Ground
from siteplan.validator.readings import plain
from siteplan.validator.shapes import healed, polygons_of, union_of_all

TOUCH_M = 0.5  # a road or gate this close to a road opens onto it
JOIN_SQM = 1.0  # contact smaller than this is two roads touching at a corner, not meeting
THROUGH = (RoadKind.APPROACH, RoadKind.LOOP, RoadKind.INTERNAL)
NETWORK = (*THROUGH, RoadKind.CUL_DE_SAC)
LANE_NOTE = "The perimeter lane is not established as an 8(m) road."


@dataclass(frozen=True)
class Part:
    """One polygon of a road's ground (what is left once anything built on it is taken away)."""

    road: DrawnRoad
    shape: Polygon


def parts_of(ctx: Context, ground: Ground, kinds: tuple[RoadKind, ...]) -> list[Part]:
    return [Part(r, p) for r in ctx.drawn.roads_of(*kinds)
            for p in polygons_of(r.shape.difference(ground.solid_land)) if p.area > JOIN_SQM]


def lane_land(ctx: Context, ground: Ground) -> BaseGeometry:
    return union_of_all([p.shape for p in parts_of(ctx, ground, (RoadKind.PERIMETER_LANE,))])


def junctions(shape: BaseGeometry, partners: BaseGeometry, reach_m: float) -> list[BaseGeometry]:
    """Where a shape meets its partners, one patch for each junction: contacts nearer together
    than `reach_m` (half a road's width, both ways) are one."""
    if partners.is_empty:
        return []
    contact = shape.buffer(TOUCH_M).intersection(partners)
    patches = [p for p in polygons_of(contact) if p.area >= JOIN_SQM]
    return polygons_of(union_of_all([p.buffer(reach_m) for p in patches]))


def _others(parts: list[Part], part: Part) -> BaseGeometry:
    return union_of_all([p.shape for p in parts if p is not part])


def _loop_problems(ctx: Context, parts: list[Part], reach_m: float) -> list[str]:
    """The loop road closes round the land or runs from one gate to another; a loop cut open has
    two ends that meet nothing."""
    loop = [p for p in parts if p.road.kind is RoadKind.LOOP]
    problems = []
    for piece in polygons_of(healed(union_of_all([p.shape for p in loop]))):
        if piece.interiors or len(junctions(piece, ctx.entrance_land, reach_m)) >= 2:
            continue
        ids = sorted({p.road.id for p in loop if p.shape.intersects(piece)})
        problems.append(f"the loop road ({', '.join(ids)}) does not close round the land and does "
                        "not run from gate to gate")
    return problems


def _end_problems(ctx: Context, parts: list[Part], reach_m: float,
                  lane: BaseGeometry) -> list[str]:
    """The main approach and the internal roads with an end that meets nothing: no road, no gate
    (and, if `lane` is given, no perimeter lane)."""
    gates = ctx.entrance_land
    problems = []
    for part in (p for p in parts if p.road.kind in (RoadKind.APPROACH, RoadKind.INTERNAL)):
        roads = union_of_all([_others(parts, part), lane])
        if part.road.kind is RoadKind.APPROACH:
            if not junctions(part.shape, gates, reach_m):
                problems.append(f"{part.road.id} does not start at an entrance")
            if not junctions(part.shape, roads, reach_m):
                problems.append(f"{part.road.id} stops short of the loop and the other roads")
        elif len(junctions(part.shape, union_of_all([roads, gates]), reach_m)) < 2:
            problems.append(f"{part.road.id} has an end that meets no road or gate")
    return problems


def dead_end_check(ctx: Context, ground: Ground) -> Check:
    """Every through road meets something at each end, and the loop closes. An end that meets
    only the perimeter lane is UNVERIFIED: whether the lane is an 8(m) road is not settled."""
    circ = ctx.rules.circulation
    low, high = circ.cul_de_sac_length_m.value
    required = (f"through roads; a cul-de-sac only {low:g}-{high:g} m long, "
                f"{circ.cul_de_sac_width_m.value:g} m wide, with a "
                f"{circ.cul_de_sac_head_radius_m.value:g} m radius head")
    clause, rule = circ.internal_road_m.clause, "Internal roads: dead ends"
    parts, reach = parts_of(ctx, ground, THROUGH), circ.internal_road_m.value / 2
    loop = _loop_problems(ctx, parts, reach)
    problems = loop + _end_problems(ctx, parts, reach, union_of_all([]))
    if not problems:
        return plain(Family.ROADS, rule, Status.PASS,
                     "every road meets another road or the entrance at both ends", required,
                     clause)
    if not loop and not _end_problems(ctx, parts, reach, lane_land(ctx, ground)):
        return plain(Family.ROADS, rule, Status.UNVERIFIED,
                     "; ".join(problems) + ", but each meets the perimeter lane", required, clause,
                     f"{LANE_NOTE} (ASSUMED_FOR_TEST circulation in the setback).")
    return plain(Family.ROADS, rule, Status.FAIL, "; ".join(problems), required, clause,
                 "A road that is not a cul-de-sac of the form rule 8(m) allows must meet another "
                 "road or a gate at both ends, and the loop must close.")


def _reached(ctx: Context, parts: list[Part], bridge: BaseGeometry) -> tuple[bool, list[str]]:
    """Whether any road (with `bridge` counted as one) meets the entrance, and which roads are
    then joined to none that does."""
    land = healed(union_of_all([*(p.shape for p in parts), bridge]))
    joined = union_of_all([c for c in polygons_of(land)
                           if c.distance(ctx.entrance_land) <= TOUCH_M])
    if joined.is_empty:
        return False, []
    return True, sorted({p.road.id for p in parts if p.shape.distance(joined) > TOUCH_M})


def entrance_connection_check(ctx: Context, ground: Ground) -> Check | None:
    """The roads are one network that begins at an entrance: a road floating clear of it is not
    joined, and an entrance that meets no 8(m) road (a driveway or a fire lane is not one) gives
    the roads no way in. Joined only through the perimeter lane is UNVERIFIED."""
    parts = parts_of(ctx, ground, NETWORK)
    if not parts or not ctx.entrances:
        return None
    rule = "Internal roads: joined to the entrance"
    clause = ctx.rules.circulation.internal_road_m.clause
    required = "one road network, entered from a gate; a driveway or fire lane is not an 8(m) road"
    reached, floating = _reached(ctx, parts, union_of_all([]))
    if reached and not floating:
        return plain(Family.ROADS, rule, Status.PASS, "every road is joined to the way in",
                     required, clause)
    lane = lane_land(ctx, ground)
    lane_reached, lane_floating = _reached(ctx, parts, lane) if not lane.is_empty else (False, [])
    if lane_reached and not lane_floating:
        return plain(Family.ROADS, rule, Status.UNVERIFIED,
                     "joined to the entrance only through the perimeter lane", required, clause,
                     LANE_NOTE)
    if not reached and not lane_reached:
        return plain(Family.ROADS, rule, Status.FAIL, "no rule 8(m) road meets the entrance",
                     required, clause,
                     "The way in from the gate must be the main approach road, 9 to 18 m wide.")
    loose = ", ".join(lane_floating or floating)
    return plain(Family.ROADS, rule, Status.FAIL,
                 f"not joined to the road from the entrance: {loose}", required, clause)
