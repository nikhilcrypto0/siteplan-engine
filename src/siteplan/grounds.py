"""The ground round the towers, laid while the towers are chosen, not after.

For one height, `frame` fixes what does not depend on the towers: their land (the plot less the
setback, or less the green strip and the loop road where those need more), the loop road, the
entrance and the green strip. `lay` then takes a placement of towers and gives every other
requirement its land in the order an architect would, on what the roads and the fire bands
leave: the club house (rule 15(a)(x)), the cellars and their ramp (Table V, rule 13(c)), the
tot-lot (rule 7(a)(vii) and 8(g)). When one of them cannot be met, the smallest tower is dropped
and the ground is laid again, so every layout that comes out meets them all; the reasons each
tower was dropped are kept.

`quick=True` checks the club house and the ramp by area only, for ranking hundreds of
placements; the few worth drawing are then laid exactly.

LEGACY, not for production generation by a language model: kept only for regression comparison.
Production generation is `siteplan.service` (the full search lays the ground from the blocks).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.affinity import rotate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from siteplan import rules
from siteplan.access import (
    FIRE_BAND_M,
    R_OUT,
    ROAD_M,
    Entrance,
    RoadPiece,
    entrance,
    fire_bands,
    green_strip,
    green_strip_width,
    inner_plot,
    loop_road,
    loop_turns,
    tower_inset,
)
from siteplan.geometry import opening
from siteplan.parking import (
    ParkingPlan,
    ParkingStandards,
    bay_area_sqm,
    cellar_floor,
    cellar_outline,
    cellars_needed,
    count_bays,
    place_ramp,
    ramp_size,
    stilt_area,
)
from siteplan.site_amenities import AmenityItem, _fit
from siteplan.towers import Placement, Tower, corridor_roads

EPS_M = 0.01
# Every number here is classified in constraints.py; none of these three is law.
CLEARANCE_M = 1.5  # walking room between the club house, the ramp and the tot-lot
CLUB_ASPECT = 1.6  # the club house footprint's proportion, when the firm gives none
# The planning target for the club house: the 2012 minimum, UNRESOLVED_INTERPRETATION of the 2016
# wording ('upto 3% ... or 50,000 Sft. whichever is lower'), ASSUMED_FOR_TEST (see rules.py).
AMENITY_SHARE = rules.AMENITY_MIN_BUILT_UP_FRACTION
# The share of a parking floor that bays and aisles are expected to take once laid out, for
# sizing the cellars; the cars are then counted and a level added if they fall short.
LAYOUT_SHARE = 0.75
# A water body beside the towers' land is three separate things, never added to each other:
# 1. the statutory buffer (rules.WATER_BUFFER_M, rule 3(a)(ii)), which is the keep-out itself;
# 2. the Table IV setback, measured from the plot line: towers keep the larger of the two where
#    they overlap, because the land is the plot under the setback LESS the buffer zone (a union);
# 3. room to drive beside the tower. NBC 4.6(c) asks a motorable band on every side
#    (FIRE_BAND_M on our reading of the 9 m); the buffer is treated as not motorable, which is an
#    UNRESOLVED_INTERPRETATION of rule 3(a). Beyond that band the loop road needs the rest of its
#    9 m to run along the water rather than end at it (a dead end rule 8(m) does not allow): that
#    remainder is the engine's road pattern, an ENGINE_DESIGN_ASSUMPTION.
WATER_FIRE_CLEARANCE_M = FIRE_BAND_M
WATER_LOOP_ROAD_EXTRA_M = max(0.0, ROAD_M - FIRE_BAND_M)


@dataclass(frozen=True)
class Frame:
    """What one height fixes before any tower is placed."""

    plot: Polygon
    tot_lot_target_sqm: float
    setback_m: float
    corridor_m: float
    green_m: float
    envelope: Polygon  # the towers' land, the loop road running round it
    land: Polygon  # all the ground beyond the setbacks and the loop: towers and everything else
    inner: Polygon  # motorable ground: the plot less the green strip and any water buffer
    loop: Polygon
    entrance: Entrance
    green: Polygon | None
    keep_out: Polygon | None
    turns: tuple[Polygon, ...]  # swept sectors at the loop road's bends
    # With circulation inside the setback (a test assumption), the ring round the towers is a
    # perimeter driveway and fire lane as wide as the setback leaves, not a 9 m loop road.
    perimeter_m: float = 0.0

    @property
    def base_roads(self) -> list[RoadPiece]:
        ring = (RoadPiece("perimeter", self.loop, self.perimeter_m) if self.perimeter_m
                else RoadPiece("loop", self.loop, ROAD_M))
        return [ring,
                RoadPiece("main approach", self.entrance.approach, self.entrance.width_m)]


def frame(plot: Polygon, setback_m: float, gross_area_sqm: float | None = None,
          keep_out=None, access_side: str | None = None,
          circulation_in_setback: bool = False) -> Frame | None:
    """None when the towers' land is empty. The plot is the net plot and the setback is kept on
    every side, the front included (rules.SETBACK_ON_NET_PLOT_CLAUSE, rules.FRONT_SETBACK_CLAUSE).
    """
    green_m = green_strip_width(setback_m)
    # Without the test assumption the 9 m loop road runs outside the setback, so towers stand
    # the larger of the setback and the green strip plus the road; with it, at the setback, the
    # perimeter lane inside it (boundary -> setback with circulation in it -> building).
    inset = setback_m if circulation_in_setback else tower_inset(setback_m)
    inner = inner_plot(plot, green_m, keep_out)
    land = plot.buffer(-(inset + EPS_M))
    # Towers keep the fire clearance off a water buffer, and the rest of a road's width so the
    # loop can run along the water (see WATER_FIRE_CLEARANCE_M). The setback is not added to it.
    if keep_out is not None:
        clear = WATER_FIRE_CLEARANCE_M + (0.0 if circulation_in_setback
                                          else WATER_LOOP_ROAD_EXTRA_M)
        land = land.difference(keep_out.buffer(clear + EPS_M, join_style="mitre"))
    # Only ground a fire tender can reach from the entrance side is used: no crossing over a
    # nala or lake is drawn, so land beyond one is left unbuilt.
    parts = list(getattr(inner, "geoms", [inner]))
    if len(parts) > 1:
        side = entrance(plot, access_side, inset + EPS_M, keep_out)
        reachable = [part for part in parts if part.intersects(side.approach)]
        if reachable:
            land = land.intersection(unary_union(reachable))
    # The loop runs round the towers' land, so that land keeps no part a tender could not turn
    # round: nothing narrower than two turning radii, every corner rounded to one. A narrow arm
    # of the plot is left to the tot-lot, the facilities and the parking.
    envelope = land.buffer(-R_OUT).buffer(R_OUT)
    if envelope.is_empty:
        return None
    loop = loop_road(envelope, inner)
    # The entrance goes where the shortest approach from the access side joins the loop; it
    # stops at the towers' land, which the loop already rings. With the perimeter lane inside
    # a setback narrower than the road, the approach is carried in at least its own width, and
    # the towers keep off it.
    least = max(inset, ROAD_M) + 5 * EPS_M if circulation_in_setback else inset + EPS_M
    gate = entrance(plot, access_side, least, keep_out, loop)
    if circulation_in_setback:
        envelope = _largest(envelope.difference(gate.approach.buffer(EPS_M, join_style="mitre")))
    else:
        gate = Entrance(gate.gate, _largest(gate.approach.difference(envelope)), gate.width_m,
                        gate.note)
    land = land.difference(gate.approach)
    target = rules.OPEN_SPACE_MIN_FRACTION * max(plot.area, gross_area_sqm or 0.0)
    corridor = max(setback_m, ROAD_M) + EPS_M
    return Frame(plot, target, setback_m, corridor, green_m, envelope, land, inner, loop, gate,
                 green_strip(plot, green_m, gate.gate), keep_out, tuple(loop_turns(loop)),
                 setback_m - green_m if circulation_in_setback else 0.0)


@dataclass(frozen=True)
class Context:
    """The site facts and standards the ground depends on, beyond the geometry."""

    floors: int
    club_house: bool
    club_house_sqm: float | None
    club_house_floors: int
    parking_percent: float
    parking_basis: str
    standards: ParkingStandards = field(default_factory=ParkingStandards)


@dataclass(frozen=True)
class Ground:
    towers: tuple[Tower, ...]
    roads: tuple[RoadPiece, ...]
    fire_lanes: Polygon | None
    club: Polygon | None
    club_sqm: float
    ramp: Polygon | None
    tot_lot: tuple[Polygon, ...]
    parking: ParkingPlan
    free: Polygon | None  # what is left for the facilities and surface parking
    dropped: tuple[str, ...] = ()  # why towers were dropped, in order


def lay(fr: Frame, placement: Placement, ctx: Context, quick: bool = False
        ) -> tuple[Ground | None, list[str]]:
    """The ground for this placement, dropping the smallest tower until every requirement
    fits. Returns the ground (None when no tower survives) and the reasons towers went."""
    reasons: list[str] = []
    current = placement
    while current.towers:
        ground, reason = _attempt(fr, current, ctx, quick)
        if ground is not None:
            return Ground(**{**ground.__dict__, "dropped": tuple(reasons)}), reasons
        reasons.append(reason)
        smallest = min(current.towers, key=lambda t: t.saleable_sqft_per_floor())
        current = current.without(smallest)
    return None, reasons


def _attempt(fr: Frame, placement: Placement, ctx: Context, quick: bool
             ) -> tuple[Ground | None, str]:
    towers = placement.towers
    corridors = corridor_roads(placement, fr.envelope, fr.loop)
    roads = (*fr.base_roads, *corridors)
    road_land = unary_union([r.shape for r in roads])
    bands = fire_bands([t.footprint for t in towers])
    circulation = unary_union([road_land, bands]) if bands is not None else road_land
    blocks = unary_union([t.footprint for t in towers])
    room = fr.land.difference(unary_union([blocks, circulation]))
    fire_lanes = bands.difference(road_land).intersection(fr.inner) if bands else None

    tower_sqm = sum(t.footprint.area for t in towers) * ctx.floors
    units = sum(sum(t.flats_per_floor().values()) for t in towers) * ctx.floors
    club_sqm = _club_size(ctx, tower_sqm, units)
    footprint = club_sqm / ctx.club_house_floors if club_sqm else 0.0
    club_room = room.difference(blocks.buffer(fr.setback_m + EPS_M, join_style="mitre"))
    if club_sqm and not _wide_enough(club_room, footprint):
        return None, _no_club(club_sqm)

    need = ctx.parking_percent / 100 * (tower_sqm + club_sqm)
    stilt = stilt_area(towers)
    width, length = ramp_size(ctx.standards)
    cores = [c for t in towers for c in t.cores]
    per_level = [_level_area(fr, n, cores, width * length, ctx.standards)
                 for n in range(1, ctx.standards.max_cellars + 1)]
    # Sized so the cars that fit in bays and aisles, not only the floor, meet the need.
    levels = cellars_needed(need, stilt * LAYOUT_SHARE, [a * LAYOUT_SHARE for a in per_level])
    if levels is None:
        best = (stilt + (ctx.standards.max_cellars * per_level[-1] if per_level else 0.0))
        return None, (f"parking: {need:,.0f} m² needed ({ctx.parking_percent:g}% of built-up), "
                      f"about {best * LAYOUT_SHARE:,.0f} m² of bays and aisles fit in the "
                      f"stilt and {ctx.standards.max_cellars} cellars")

    if quick:  # the area book: club, ramp and tot-lot must all fit in the pockets together
        spare = sum(p.area for p in _pockets(room))
        wanted = (fr.tot_lot_target_sqm + footprint * 1.15
                  + (width * length * 1.3 if levels else 0.0))
        if spare + EPS_M < wanted:
            return None, (f"open ground: {spare:,.0f} m² of pockets for {wanted:,.0f} m² of "
                          "tot-lot, club house and ramp")
        club = ramp = None
        chosen: list[Polygon] = []
        free = room
    else:
        club = None
        if club_sqm:
            club = _fit(club_room, _club_item(footprint), placement.angle_deg,
                        fr.entrance.gate.centroid)
            if club is None:
                return None, _no_club(club_sqm)
            room = room.difference(club.buffer(CLEARANCE_M, join_style="mitre"))
        ramp = None
        if levels:
            ramp = place_ramp(room, road_land, width, length, fr.entrance.gate.centroid)
            if ramp is None:
                return None, ("no room beside a road for the cellar ramp "
                              f"({width:g} x {length:g} m, rule 13(c)(vii)) outside the "
                              "setbacks and the fire lanes")
            room = room.difference(ramp.buffer(CLEARANCE_M, join_style="mitre"))
        chosen, total = _choose_tot_lot(room, fr.tot_lot_target_sqm, placement.angle_deg)
        if total + EPS_M < fr.tot_lot_target_sqm:
            return None, (f"tot-lot: {total:,.0f} m² of pockets at least 3 m wide, "
                          f"{fr.tot_lot_target_sqm:,.0f} m² needed (rule 7(a)(vii))")
        free = room.difference(unary_union(chosen)) if chosen else room

    plan = parking_plan(fr, towers, club_sqm, ctx, levels, (ramp,) if ramp is not None else ())
    return Ground(towers, tuple(roads), fire_lanes, club, club_sqm, ramp, tuple(chosen), plan,
                  free), ""


def parking_plan(fr: Frame, towers, club_sqm: float, ctx: Context, levels: int,
                 ramps: tuple[Polygon, ...], surface_sqm: float = 0.0,
                 cars: dict[str, int] | None = None) -> ParkingPlan:
    """The parking a set of towers is given with `levels` cellars (rule 13 and Table V)."""
    width, length = ramp_size(ctx.standards)
    cores = [c for t in towers for c in t.cores]
    tower_sqm = sum(t.footprint.area for t in towers) * ctx.floors
    return ParkingPlan(
        percent=ctx.parking_percent, basis=ctx.parking_basis, built_up_sqm=tower_sqm + club_sqm,
        stilt_sqm=stilt_area(towers), surface_sqm=surface_sqm, cellar_levels=levels,
        cellar_setback_m=rules.cellar_setback_m(fr.plot.area, max(levels, 1)),
        cellar_sqm_per_level=(_level_area(fr, levels, cores, width * length, ctx.standards)
                              if levels else 0.0),
        cellar_outline=(cellar_outline(fr.plot, fr.plot.area, levels, fr.keep_out)
                        if levels else None),
        ramps=ramps if levels else (), ramp_width_m=width if levels else 0.0,
        ramp_length_m=length if levels else 0.0,
        utilities_fraction=ctx.standards.utilities_fraction if levels else 0.0,
        cars=cars or {},
    )


def firm_up(fr: Frame, ground: Ground, towers, ctx: Context, angle: float, bays: int,
            spare=None, roads=None) -> ParkingPlan:
    """Count the cars that fit on every floor and add cellar levels (and, with none yet, a ramp
    on the spare ground) until the bays and aisles laid out meet Table V, or the deepest the
    standards allow is reached; the checker says so if even that is short."""
    levels, ramps = ground.parking.cellar_levels, ground.parking.ramps
    surface = bay_area_sqm(bays)

    def counted(n: int) -> ParkingPlan:
        plan = parking_plan(fr, towers, ground.club_sqm, ctx, n, ramps, surface)
        return ParkingPlan(**{**plan.__dict__, "cars": _cars(fr, plan, towers, angle, bays)})

    def enough(plan: ParkingPlan) -> bool:
        need = plan.required_sqm - EPS_M
        return plan.provided_sqm >= need and plan.laid_out_sqm >= need

    plan = counted(levels)
    while not enough(plan) and levels < ctx.standards.max_cellars:  # dig deeper
        if not ramps:
            width, length = ramp_size(ctx.standards)
            ramp = (place_ramp(spare, roads, width, length, fr.entrance.gate.centroid)
                    if spare is not None and roads is not None else None)
            if ramp is None:
                return plan
            ramps = (ramp,)
        levels += 1
        plan = counted(levels)
    while enough(plan) and levels > 0:  # but no deeper than the cars counted need
        shallower = counted(levels - 1)
        if not enough(shallower):
            break
        levels, plan = levels - 1, shallower
    return plan


def _cars(fr: Frame, plan: ParkingPlan, towers, angle: float, bays: int) -> dict[str, int]:
    cars = {"stilt": sum(count_bays(t.footprint.difference(unary_union(t.cores)), angle)
                         for t in towers)}
    if plan.cellar_levels and plan.cellar_outline is not None:
        cores = [c for t in towers for c in t.cores]
        floor = cellar_floor(plan.cellar_outline, cores, plan.ramps)
        per_level = int(count_bays(floor, angle) * (1 - plan.utilities_fraction))
        for level in range(1, plan.cellar_levels + 1):
            cars[f"cellar {level}"] = per_level
    if bays:
        cars["surface"] = bays
    return cars


def _largest(shape) -> Polygon:
    parts = [p for p in getattr(shape, "geoms", [shape]) if isinstance(p, Polygon)]
    return max(parts, key=lambda p: p.area) if parts else shape


def _no_club(club_sqm: float) -> str:
    return (f"no room for a {club_sqm:,.0f} m² club house (rule 15(a)(x)) clear of the "
            "roads, the fire lanes and the block gaps")


def _club_item(footprint: float) -> AmenityItem:
    depth = math.sqrt(footprint / CLUB_ASPECT)
    return AmenityItem(name="CLUB HOUSE", width_m=footprint / depth, depth_m=depth)


def _wide_enough(room, footprint: float) -> bool:
    """Whether some part of the room is as wide as the club house is deep, over its area."""
    if room.is_empty:
        return False
    depth = math.sqrt(footprint / CLUB_ASPECT)
    return opening(room, depth).area >= footprint


def _choose_tot_lot(room, target: float, angle_deg: float = 0.0) -> tuple[list[Polygon], float]:
    """The biggest pockets first, until the target is met; the last one is cut down to what is
    still needed, so the rest of it stays free for the facilities and the surface bays."""
    chosen, total = [], 0.0
    for pocket in sorted(_pockets(room), key=lambda p: -p.area):
        if total >= target:
            break
        still = target - total
        if pocket.area > still * TRIM_ABOVE:
            pocket = _trim(pocket, still * TRIM_MARGIN, angle_deg) or pocket
        chosen.append(pocket)
        total += pocket.area
    return chosen, total


TRIM_ABOVE = 1.2  # a pocket this much bigger than what is still needed is cut down
TRIM_MARGIN = 1.02  # and cut a little over, so rounding never leaves the tot-lot short


def _trim(pocket: Polygon, area: float, angle_deg: float) -> Polygon | None:
    """The end of a pocket holding `area`, cut square to the towers, when that piece is still a
    pocket the rule accepts (3 m wide, 50 m²); None when it would not be."""
    if area < rules.OPEN_SPACE_MIN_POCKET_SQM + EPS_M:
        return None
    turned = rotate(pocket, -angle_deg, origin=(0, 0))
    minx, miny, maxx, maxy = turned.bounds
    along_x = maxx - minx >= maxy - miny  # cut across the long side, never along it

    def keep(at: float) -> Polygon:
        cut = (box(minx - 1, miny - 1, at, maxy + 1) if along_x
               else box(minx - 1, miny - 1, maxx + 1, at))
        return turned.intersection(cut)

    lo, hi = (minx, maxx) if along_x else (miny, maxy)
    for _ in range(40):  # the cut that leaves the area wanted
        mid = (lo + hi) / 2
        if keep(mid).area < area:
            lo = mid
        else:
            hi = mid
    piece = keep(hi)
    parts = [p for p in getattr(piece, "geoms", [piece]) if isinstance(p, Polygon)]
    if not parts:
        return None
    piece = max(parts, key=lambda p: p.area)
    if piece.area < area / TRIM_MARGIN or piece.area < rules.OPEN_SPACE_MIN_POCKET_SQM:
        return None
    if opening(piece, rules.OPEN_SPACE_MIN_WIDTH_M + 2 * EPS_M).area < piece.area * 0.98:
        return None
    return rotate(piece, angle_deg, origin=(0, 0))


def _club_size(ctx: Context, tower_sqm: float, units: int) -> float:
    """Rule 15(a)(x): 3% of the built-up area from 100 units, the block itself included. The 3%
    as a minimum is the engine's planning assumption for the test, not settled law."""
    if not ctx.club_house:
        return 0.0
    if ctx.club_house_sqm:
        return ctx.club_house_sqm
    if units < rules.AMENITY_MIN_UNITS:
        return 0.0
    return AMENITY_SHARE * tower_sqm / (1 - AMENITY_SHARE) + EPS_M


def _level_area(fr: Frame, levels: int, cores, ramp_sqm: float,
                standards: ParkingStandards) -> float:
    """One cellar level's Table V area when there are `levels`: the outline under the rule
    13(c)(x) setback, less the cores, the ramp and the utilities share."""
    outline = cellar_outline(fr.plot, fr.plot.area, levels, fr.keep_out)
    floor = outline.area - sum(c.area for c in cores) - ramp_sqm
    return max(0.0, floor * (1 - standards.utilities_fraction))


def _pockets(room) -> list[Polygon]:
    """Tot-lot pockets: at least 3 m wide and 50 m² each (rule 7(a)(vii))."""
    if room.is_empty:
        return []
    # Growing back after the shrink can push a square corner past the room's own edge.
    usable = opening(room, rules.OPEN_SPACE_MIN_WIDTH_M + 2 * EPS_M).intersection(room)
    parts = getattr(usable, "geoms", [usable])
    return [p for p in parts if isinstance(p, Polygon)
            and p.area >= rules.OPEN_SPACE_MIN_POCKET_SQM + EPS_M]
