"""Step 5: where buildings can stand, the club house, and the tot-lot, the architect's way
(2026-10-11) for any site.

1. A height map. Where the tallest building step 2 allows does not fit, one floor lower is
   tried, then the next, down to the lowest block worth building (Stilt + 6 unless the firm
   says otherwise), each height keeping its own setbacks; the blocks are the firm's own, the
   double-loaded kit and a slim one (one row of flats beside the corridor), turned either way.
   Each part of the land is marked with the tallest building that fits there.
2. Land no building fits on keeps no building's setback, but the plot's edge always keeps one:
   beside a building, its own height's; elsewhere, the lowest block's (the architect's word,
   2026-10-11: the outside boundary is never touched). The club house is tried there first
   (one; its footprint the architect's share of the land left after the setbacks), and the
   rest of it is tot-lot.
3. The tot-lot: 10% of the whole plot for a high-rise site or a Group Development Scheme (rules
   7(a)(vii), 8(g)), 5% for any other plot above 750 m² (5(f)(vi)), in pockets at least 3 m
   wide; on the free land first, then in the plot's corners that cost the fewest floors, each
   pocket no further along than its corner's shorter side, never grown out of one place. A
   water body's buffer may count (3(a)(iii)(3)); the gaps between blocks never do
   (7(a)(xii))."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from pathlib import Path

from shapely import set_precision
from shapely.affinity import rotate, translate
from shapely.errors import GEOSException
from shapely.geometry import Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan import rules
from siteplan.intake import load_defaults
from siteplan.library import FlatLibrary
from siteplan.prototypes.compose import compose_library
from siteplan.steps.inputs import Inputs, bearing, compass
from siteplan.steps.setbacks import Setbacks, land_left_at
from siteplan.steps.survey_copy import SHORT_RUN_M, SurveyCopy

CUT_TOLERANCE_M = 0.01  # how finely a cut or a pocket's size is placed; pieces this close are
# one pocket; a width this short of the least still counts (a 3.000 m strip is 3 m wide)
GRID_M = 0.001  # two outlines GEOS cannot overlay are snapped to this grid and tried again
LOWEST_FLOORS = 6  # the lowest block worth building: the architect's word (2026-10-11)
CLUB_HOUSE_LAND_SHARE = 0.01  # the club house's footprint, of the land left after the setbacks:
# the architect's figure (2026-10-11), not a rule
CORNER_DEG = 170.0  # two sides meeting at less than this inside the plot make a corner
SHARP_DEG = 60.0  # a corner sharper than this is cut straight across, not spanned along its sides
CLUB_TURN_DEG = 5  # the club house is tried at every turn this many degrees apart
CLUB_STEP_SHARE = 0.25  # and with its middle at points this share of its side apart
FREE, WATER = "land no building fits on", "the water's buffer"
SETBACK = "setback land no building is left beside"
FROM_LINE, FROM_EDGE = "the buffer from the line drawn", "the buffer from the plot's edge"
MEET, DIFF = "intersection", "difference"


@dataclass(frozen=True)
class Share:
    """What the rules ask of this site: the share of the site, and the pockets' least size."""

    fraction: float
    min_width_m: float
    min_pocket_sqm: float
    why: str  # 'a high-rise site and a Group Development Scheme'
    clauses: tuple[tuple[str, str], ...]  # (whom the rule holds, its clause)


def share_for(high_rise: bool, group_scheme: bool, plot_sqm: float) -> Share | None:
    """Rule 7(a)(vii) for a high-rise site and 8(g) for a Group Development Scheme (the same 10%,
    not added); rule 5(f)(vi) for any other plot above 750 m²; None below it."""
    if high_rise or group_scheme:
        why = " and ".join(name for name, holds in (("a high-rise site", high_rise),
                                                    ("a Group Development Scheme", group_scheme))
                           if holds)
        clauses = tuple((whom, clause) for whom, clause, holds in (
            ("a high-rise site", rules.OPEN_SPACE_2012_CLAUSE, high_rise),
            ("a Group Development Scheme", rules.GROUP_SCHEME_OPEN_SPACE_CLAUSE, group_scheme))
            if holds)
        return Share(rules.OPEN_SPACE_MIN_FRACTION, rules.OPEN_SPACE_MIN_WIDTH_M,
                     rules.OPEN_SPACE_MIN_POCKET_SQM, why, clauses)
    if plot_sqm > rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:
        return Share(rules.NON_HIGH_RISE_OPEN_SPACE_FRACTION,
                     rules.NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M,
                     rules.NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM,
                     f"a plot above {rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:,.0f} m²",
                     (("a plot below high-rise", rules.NON_HIGH_RISE_OPEN_SPACE_CLAUSE),))
    return None


@dataclass(frozen=True)
class Blocks:
    """The firm's blocks: the kit its flat library composes and a slim one made from the same
    flats, one row beside the corridor. A block fits where the land is as wide as its short side
    and a piece holds its footprint."""

    footprints: tuple[tuple[str, float, float], ...]  # (what it is, length, depth)
    source: str  # the file and how far it is confirmed

    @property
    def narrowest_m(self) -> float:
        return min(min(length, depth) for _, length, depth in self.footprints)


class NoBlocks(Exception):
    """The workspace names a flat library that cannot be read or composed."""


def firm_blocks(workspace: Path | None) -> Blocks | None:
    """The firm's blocks (the kit, the flats in equal shares, and the slim one), or None when
    the workspace names no library."""
    if workspace is None:
        return None
    defaults = load_defaults(workspace)
    if not defaults.flat_library:
        return None
    try:
        library = FlatLibrary.model_validate_json(
            (workspace / defaults.flat_library).read_text())
        kit = compose_library(library)
    except (OSError, ValueError) as problem:
        first = str(problem).splitlines()[0]
        raise NoBlocks(f"{defaults.flat_library} cannot be used: {first}") from problem
    shortest = min(kit, key=lambda block: block.length_m)
    slim = ("a slim block: one row of the firm's flats beside the corridor", shortest.length_m,
            library.flats[0].depth_m + library.corridor_width_m)
    return Blocks((*((f"the kit's {block.id}", block.length_m, block.depth_m) for block in kit),
                   slim),
                  f"{defaults.flat_library}, the firm's flat library in the workspace "
                  f"({defaults.standard_status('flat_library')})")


@dataclass(frozen=True)
class Tier:
    """One height of the height map."""

    floors: int
    setback_m: float  # the widest of its sides' setbacks
    fits: BaseGeometry  # where one of the firm's blocks this tall fits, its setbacks kept
    tallest: BaseGeometry  # the part where this is the tallest building that fits
    band: BaseGeometry  # the setback land those blocks keep from the plot's edge


@dataclass(frozen=True)
class Club:
    footprint: Polygon | None  # None when it does not fit on the free land
    area_sqm: float
    setback_m: float  # what it keeps from the plot's edge


@dataclass(frozen=True)
class Pocket:
    polygon: BaseGeometry  # one piece, or pieces that touch
    lies: str  # where in the plot: 'north'
    on_sqm: tuple[tuple[str, float], ...]  # (FREE, WATER or 'Stilt + N land', m²)

    @property
    def area_sqm(self) -> float:
        return self.polygon.area


@dataclass(frozen=True)
class Placing:
    """The height map, the club house and the tot-lot on one reading of the water's buffer."""

    reading: str  # FROM_LINE, FROM_EDGE, or '' when there is no water
    tiers: tuple[Tier, ...]  # tallest first
    free: BaseGeometry  # land no building fits on, inside the edge's own setback
    club: Club
    tot_lot: BaseGeometry
    pockets: tuple[Pocket, ...]
    corners: int  # the corners of the plot the tot-lot takes
    need_sqm: float
    edge: BaseGeometry  # the setback the plot's edge always keeps (ring)
    standing: tuple[BaseGeometry, ...]  # each height's land where a block still fits once the
    # tot-lot and the club house are out, measured again

    @property
    def buildable(self) -> BaseGeometry:
        return unary_union([tier.fits for tier in self.tiers])

    @property
    def short_sqm(self) -> float:
        return max(0.0, self.need_sqm - self.tot_lot.area)

    def on(self, kind: str) -> float:
        return sum(area for pocket in self.pockets for k, area in pocket.on_sqm if k == kind)

    @property
    def building_land_after(self) -> BaseGeometry:
        """Where a building fits once the tot-lot and the club house are out: a strip they
        leave too thin for a block no longer counts."""
        return unary_union(self.standing)

    @property
    def free_after(self) -> BaseGeometry:
        """Free land the tot-lot and the club house leave: roads, parking, landscaping."""
        taken = unary_union([self.tot_lot, *([self.club.footprint] if self.club.footprint
                                             else [])])
        return _overlay(self.free, taken, DIFF)

    @property
    def kept_setbacks(self) -> BaseGeometry:
        """The setback land kept: beside where a building can still stand, each height's own,
        and the edge's own everywhere."""
        return unary_union([*(_overlay(tier.band, land.buffer(
            tier.setback_m + CUT_TOLERANCE_M, join_style="mitre"), MEET)
            for tier, land in zip(self.tiers, self.standing, strict=True)), self.edge])

    def floors_lost_sqm(self) -> float:
        """The tot-lot's area on building land, each square metre counted by the floors that
        would stand there (Stilt + 10 land costs ten floors a square metre)."""
        return sum(_overlay(self.tot_lot, tier.tallest, MEET).area * tier.floors
                   for tier in self.tiers)


@dataclass
class TotLot:
    inputs: Inputs
    copy: SurveyCopy
    setbacks: Setbacks
    stopped: str | None = None
    ask: str | None = None
    share: Share | None = None
    plot_sqm: float = 0.0  # the whole plot, as the sheet writes it (or as drawn)
    plot_from: str = ""
    blocks: Blocks | None = None
    lowest: int = LOWEST_FLOORS
    lowest_from: str = ""
    club_share: float = CLUB_HOUSE_LAND_SHARE
    club_share_from: str = ""
    placings: tuple[Placing, ...] = ()  # the first is the one drawn
    waiting: tuple[str, ...] = ()  # water whose buffer waits on an answer (step 3)

    @property
    def need_sqm(self) -> float:
        return self.share.fraction * self.plot_sqm if self.share else 0.0

    @property
    def net_need_sqm(self) -> float:
        net = self.setbacks.widening.net
        return self.share.fraction * net.area if self.share and net is not None else 0.0


def lay_out(inputs: Inputs, copy: SurveyCopy, setbacks: Setbacks) -> TotLot:
    t = TotLot(inputs, copy, setbacks)
    if setbacks.stopped:
        return _stop(t, "step 4 has no land left for buildings yet, and the tot-lot is taken "
                        "from it", setbacks.ask)
    t.plot_sqm = copy.written_sqm or copy.drawn_sqm
    t.plot_from = "written on the sheet" if copy.written_sqm else "as drawn (none is written)"
    t.share = share_for(setbacks.high_rise, setbacks.widening.group_scheme, t.plot_sqm)
    if t.share is None:
        return t
    ask = ("Which flat library does the firm build with? Name it as flat_library in the "
           "workspace's siteplan.workspace.json.")
    try:
        t.blocks = firm_blocks(inputs.workspace)
    except NoBlocks as problem:
        return _stop(t, f"the firm's flat library cannot be used ({problem})", ask)
    if t.blocks is None:
        return _stop(t, "the firm's blocks are not known, and the land no building fits on "
                        "is found with them", ask)
    _firm_figures(t)
    water = [w for w in setbacks.widening.water if w.buffer_m is not None]
    t.waiting = tuple(w.kind for w in setbacks.widening.water if w.buffer_m is None)
    readings = [("", None)] if not water else [
        (FROM_LINE, unary_union([w.kept_free for w in water])),
        (FROM_EDGE, unary_union([w.edge_kept_free for w in water]))]
    road = setbacks.height.road
    start = next((g for g in (road.frontage, road.ground, road.area)
                  if g is not None and not g.is_empty), None)
    club_area = t.club_share * setbacks.left.area
    club_setback = _club_setback(t)
    corners = plot_corners(setbacks.widening.net, setbacks.sides)
    turns = _side_turns(setbacks.sides)
    for reading, buffer in readings:
        tiers = height_map(setbacks, t.blocks, t.lowest, buffer)
        free = _free(setbacks.widening.net, tiers)
        club = place_club(free, setbacks.widening.net, club_area, club_setback, start, turns)
        t.placings += (place(tiers, free, club, buffer, t.need_sqm, t.share, start,
                             setbacks.widening.net, corners, reading,
                             (club_area, club_setback, turns), t.blocks),)
    return t


def _stop(t: TotLot, why: str, ask: str | None) -> TotLot:
    t.stopped, t.ask = why, ask
    return t


def _firm_figures(t: TotLot) -> None:
    """The architect's two working figures, from the workspace when the firm sets them."""
    defaults = load_defaults(t.inputs.workspace) if t.inputs.workspace else None
    set_lowest = defaults is not None and defaults.lowest_block_floors is not None
    t.lowest = defaults.lowest_block_floors if set_lowest else LOWEST_FLOORS
    t.lowest_from = ("the firm's workspace" if set_lowest else
                     "the architect's word (2026-10-11), the engine's default until the firm "
                     "sets lowest_block_floors")
    set_share = defaults is not None and defaults.club_house_land_share is not None
    t.club_share = defaults.club_house_land_share if set_share else CLUB_HOUSE_LAND_SHARE
    t.club_share_from = ("the firm's workspace" if set_share else
                         "the architect's figure (2026-10-11), not a rule; the engine's default "
                         "until the firm sets club_house_land_share")


def _side_turns(sides) -> tuple[float, ...]:
    """The directions of the plot's sides (jogs left out), in degrees within a quarter turn: a
    square set square to a side."""
    out = set()
    for side in sides:
        if side.length_m >= SHORT_RUN_M:
            (x0, y0), (x1, y1) = side.line.coords[0], side.line.coords[-1]
            out.add(round(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 90, 1))
    return tuple(sorted(out))


def _club_setback(t: TotLot) -> float:
    """The club house is taken as the lowest building Table III lists for the plot (up to its
    first line's height): its side setback, or the Building Line for the main road if higher."""
    line = rules.table_iii_lines(t.setbacks.widening.net.area)[0]
    front = rules.building_line_m(line, t.setbacks.height.reckoned_m or 0.0)
    return max(line.side_m or 0.0, front)


def height_map(s: Setbacks, blocks: Blocks, lowest: int,
               buffer: BaseGeometry | None) -> tuple[Tier, ...]:
    """From the tallest building step 2 allows down one floor at a time to the lowest worth
    building: where a block of the firm's fits at each height, its own setbacks kept and no
    building in a water body's buffer."""
    net = s.widening.net
    out, claimed = [], Polygon()
    for floors in range(s.floors, min(s.floors, lowest) - 1, -1):
        land, setback = land_left_at(s, floors)
        band = _overlay(net, land, DIFF)
        if buffer is not None:
            land = _overlay(land, buffer, DIFF)
        fits = block_land_in(land, blocks)
        out.append(Tier(floors, setback, fits, _overlay(fits, claimed, DIFF), band))
        claimed = unary_union([claimed, fits])
    return tuple(out)


def ring(net: Polygon, tiers: tuple[Tier, ...]) -> BaseGeometry:
    """The setback the plot's edge always keeps, a building beside it or not: the lowest block's
    (the architect's word, 2026-10-11: the outside boundary is never touched; the green strip and
    the fire lane run in it)."""
    return _overlay(net, net.buffer(-tiers[-1].setback_m, join_style="mitre"), DIFF)


def _free(net: Polygon, tiers: tuple[Tier, ...]) -> BaseGeometry:
    """The net plot less every place a block fits, the setback land each keeps beside it and
    the edge's own setback: no building can stand here."""
    kept = [_overlay(tier.band, tier.fits.buffer(tier.setback_m + CUT_TOLERANCE_M,
                                                 join_style="mitre"), MEET)
            for tier in tiers]
    used = unary_union([*(tier.fits for tier in tiers), *kept, ring(net, tiers)])
    return _overlay(net, used, DIFF)


def place_club(free: BaseGeometry, net: Polygon, area: float, setback: float,
               road: BaseGeometry | None, turns: tuple[float, ...] = ()) -> Club:
    """One club house, a square of `area` m², on the free land and its setback from the plot's
    edge kept, square to the land it stands on (else to one of the plot's sides, `turns`, in
    degrees), as near the main road as it fits; None when it does not fit."""
    if free.is_empty or area <= 0:
        return Club(None, area, setback)
    side = math.sqrt(area)
    room = _overlay(free, net.buffer(-setback, join_style="mitre"), MEET)
    centres = room.buffer(-side / 2, join_style="mitre")  # a middle at least half a side in
    if centres.is_empty:
        return Club(None, area, setback)
    square = box(-side / 2, -side / 2, side / 2, side / 2)
    step = side * CLUB_STEP_SHARE
    minx, miny, maxx, maxy = centres.bounds
    xs = _steps_from_middle(minx, maxx, step)  # the middle first: a tight room has one line
    ys = _steps_from_middle(miny, maxy, step)
    best = None
    along = _lengthwise(room, None)  # the land it stands on: square to its length first
    own = (round(math.degrees(math.atan2(along[1], along[0])) % 90, 1),) if along else ()
    for turn in own + tuple(turns or range(0, 90, CLUB_TURN_DEG)):
        if best is not None and turn not in own:
            break  # square to the land it stands on whenever it fits so
        turned = rotate(square, turn, origin=(0, 0))
        for y in ys:
            for x in xs:
                placed = translate(turned, x, y)
                if room.contains(placed):
                    near = placed.distance(road) if road is not None else 0.0
                    if best is None or near < best[0]:
                        best = (near, placed)
    return Club(best[1] if best else None, area, setback)


def _steps_from_middle(low: float, high: float, step: float) -> list[float]:
    """Points `step` apart across [low, high], one at its middle."""
    middle, out, k = (low + high) / 2, [], 0
    while middle - k * step >= low - CUT_TOLERANCE_M or middle + k * step <= high + CUT_TOLERANCE_M:
        out += sorted({middle - k * step, middle + k * step})
        k += 1
    return [v for v in out if low - CUT_TOLERANCE_M <= v <= high + CUT_TOLERANCE_M]


def place(tiers: tuple[Tier, ...], free: BaseGeometry, club: Club, buffer: BaseGeometry | None,
          need_sqm: float, share: Share, road: BaseGeometry | None, plot: Polygon,
          corners: list[Corner], reading: str = "",
          club_try: tuple[float, float, tuple[float, ...]] | None = None,
          blocks: Blocks | None = None) -> Placing:
    """The tot-lot: the free land first (largest piece first, the last cut square to its length
    at its end away from the main road); then, when it does not hold the need, pockets in the
    plot's corners, the ones that cost the fewest floors, as many as cost the least. A pocket
    keeps out of every setback: the edge's own, and each building's beside it."""
    def keep(geometry: BaseGeometry) -> BaseGeometry:
        return pockets_in(geometry, share)

    held_out = club.footprint if club.footprint is not None else Polygon()
    taken, held = [], 0.0
    for part in sorted(_parts(keep(_overlay(free, held_out, DIFF))), key=lambda p: -p.area):
        if held >= need_sqm:
            break
        if held + part.area > need_sqm:
            part = straight_cut(part, _lengthwise(part, road), need_sqm - held, keep)
        taken.append(part)
        held += part.area
    used = 0
    if held < need_sqm and corners:
        out = unary_union([held_out, *taken])
        pockets, used = corner_pockets(corners, plot, tiers, out, need_sqm - held, keep)
        if club.footprint is None and club_try is not None:
            # the corner land the tot-lot frees has no building: the club house is tried there
            # first, and the tot-lot grows to make up what it takes
            area, setback, turns = club_try
            club = place_club(pockets, plot, area, setback, road, turns)
            if club.footprint is not None:
                out = unary_union([club.footprint, *taken])
                pockets, used = corner_pockets(corners, plot, tiers, out, need_sqm - held, keep)
        taken.append(pockets)
    tot_lot = unary_union(taken) if taken else Polygon()
    pockets = tuple(Pocket(part, compass(bearing((plot.centroid.x, plot.centroid.y),
                                                 (part.centroid.x, part.centroid.y))),
                           _stands_on(part, free, buffer, tiers))
                    for part in _touching(_parts(tot_lot)))
    taken = unary_union([tot_lot, *([club.footprint] if club.footprint else [])])
    standing = tuple(_overlay(tier.fits, taken, DIFF) if blocks is None
                     else block_land_in(_overlay(tier.fits, taken, DIFF), blocks)
                     for tier in tiers)
    return Placing(reading, tiers, free, club, tot_lot, pockets, used, need_sqm,
                   ring(plot, tiers), standing)


def _stands_on(part: BaseGeometry, free: BaseGeometry, buffer: BaseGeometry | None,
               tiers: tuple[Tier, ...]) -> tuple[tuple[str, float], ...]:
    wet = _overlay(part, buffer, MEET).area if buffer is not None else 0.0
    building = [(f"Stilt + {tier.floors} land", _overlay(part, tier.tallest, MEET).area)
                for tier in tiers]
    setback = part.area - wet - _overlay(part, free, MEET).area - sum(a for _, a in building)
    out = [(WATER, wet), (FREE, _overlay(part, free, MEET).area - wet),
           (SETBACK, setback), *building]
    return tuple((kind, area) for kind, area in out if area > CUT_TOLERANCE_M)


@dataclass(frozen=True)
class Corner:
    point: tuple[float, float]
    a: tuple[float, float]  # a unit vector along one side, away from the corner
    b: tuple[float, float]  # and along the other
    angle_deg: float  # between the two sides, inside the plot
    reach_m: float  # the shorter of its two sides: no pocket runs further


def plot_corners(plot: Polygon, sides) -> list[Corner]:
    """The plot's corners: where one of step 4's sides (a jog under the jog length skipped) meets
    the next and the plot turns inward by more than a bend."""
    long = [side for side in sides if side.length_m >= SHORT_RUN_M]
    out = []
    for i, side in enumerate(long):
        after = long[(i + 1) % len(long)]
        ends, starts = side.line.coords[-1], after.line.coords[0]
        point = ((ends[0] + starts[0]) / 2, (ends[1] + starts[1]) / 2)
        a = _unit(side.line.coords[0], point)
        b = _unit(after.line.coords[-1], point)
        if a is None or b is None:
            continue
        angle = math.degrees(math.acos(max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))))
        inward = _unit((point[0] + a[0] + b[0], point[1] + a[1] + b[1]), point)
        if angle >= CORNER_DEG or inward is None:
            continue
        step = SHORT_RUN_M / 2  # a little way into the corner: inside the plot when it is convex
        if plot.contains(Point(point[0] + inward[0] * step, point[1] + inward[1] * step)):
            out.append(Corner(point, a, b, angle, min(side.length_m, after.length_m)))
    return out


def _unit(to: tuple[float, float], start: tuple[float, float]) -> tuple[float, float] | None:
    dx, dy = to[0] - start[0], to[1] - start[1]
    length = math.hypot(dx, dy)
    return None if length <= CUT_TOLERANCE_M else (dx / length, dy / length)


def corner_region(corner: Corner, size: float, plot: Polygon) -> BaseGeometry:
    """The plot's land at a corner: the parallelogram its two sides span, `size` metres along
    each; at a sharp corner, everything within `size` of it along its middle, one straight cut
    across. Never further along than the corner's shorter side, so a pocket stays in its
    corner (a sharp one's arm) instead of running on into the plot."""
    (cx, cy), (ax, ay), (bx, by) = corner.point, corner.a, corner.b
    sharp = corner.angle_deg < SHARP_DEG
    size = min(size, corner.reach_m * (math.cos(math.radians(corner.angle_deg / 2)) if sharp
                                       else 1.0))
    if not sharp:
        shape = Polygon([(cx, cy), (cx + ax * size, cy + ay * size),
                         (cx + (ax + bx) * size, cy + (ay + by) * size),
                         (cx + bx * size, cy + by * size)])
    else:
        mx, my = _unit((cx + ax + bx, cy + ay + by), (cx, cy))
        reach = sum(abs(c) for c in plot.bounds) + size  # beyond the plot
        cone = Polygon([(cx, cy), (cx + ax * reach, cy + ay * reach),
                        (cx + bx * reach, cy + by * reach)])
        across = Polygon([(cx - my * reach, cy + mx * reach), (cx + my * reach, cy - mx * reach),
                          (cx + my * reach + mx * size, cy - mx * reach + my * size),
                          (cx - my * reach + mx * size, cy + mx * reach + my * size)])
        shape = _overlay(cone, across, MEET)
    return _overlay(plot, shape, MEET)


def _pockets_at(chosen: list[Corner], size: float, plot: Polygon, tiers: tuple[Tier, ...],
                out: BaseGeometry, keep) -> BaseGeometry:
    """The pockets at the chosen corners at one size: the corner land less the setback land a
    building left beside it keeps and the edge's own, less what is taken already."""
    region = unary_union([corner_region(c, size, plot) for c in chosen])
    kept = unary_union([*(_overlay(tier.band, _overlay(tier.fits, region, DIFF).buffer(
        tier.setback_m + CUT_TOLERANCE_M, join_style="mitre"), MEET) for tier in tiers),
                        ring(plot, tiers)])
    return keep(_overlay(_overlay(region, kept, DIFF), out, DIFF))


def corner_pockets(corners: list[Corner], plot: Polygon, tiers: tuple[Tier, ...],
                   out: BaseGeometry, area: float, keep) -> tuple[BaseGeometry, int]:
    """`area` m² of pockets in the plot's corners, one size at each; the corners taken are the
    cheapest in floors a square metre, as many as cost the least in all (on even land, every
    corner). Returns the pockets and how many corners hold them."""
    reference = math.sqrt(area / len(corners))

    def rate(corner: Corner) -> float:
        pocket = _pockets_at([corner], reference, plot, tiers, out, keep)
        return _cost(pocket, tiers) / max(pocket.area, CUT_TOLERANCE_M)

    ranked = sorted(corners, key=rate)
    best = None
    for count in range(1, len(ranked) + 1):
        pockets = _grow(ranked[:count], plot, tiers, out, area, keep)
        cost = _cost(pockets, tiers)
        if pockets.area >= area - CUT_TOLERANCE_M and (best is None
                                                       or round(cost) <= round(best[0])):
            best = (cost, pockets, count)  # a tie keeps the more corners
    if best is None:
        return _grow(ranked, plot, tiers, out, area, keep), len(ranked)
    return best[1], best[2]


def _grow(chosen: list[Corner], plot: Polygon, tiers: tuple[Tier, ...], out: BaseGeometry,
          area: float, keep) -> BaseGeometry:
    """Pockets of one size at every chosen corner, the size found so they hold `area` m²."""
    low, high = 0.0, sum(abs(c) for c in plot.bounds)
    if _pockets_at(chosen, high, plot, tiers, out, keep).area < area:
        return _pockets_at(chosen, high, plot, tiers, out, keep)
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if _pockets_at(chosen, middle, plot, tiers, out, keep).area >= area:
            high = middle
        else:
            low = middle
    return _pockets_at(chosen, high, plot, tiers, out, keep)


def _cost(geometry: BaseGeometry, tiers: tuple[Tier, ...]) -> float:
    """Floors a square metre summed: what the geometry takes from the building land."""
    return sum(_overlay(geometry, tier.tallest, MEET).area * tier.floors for tier in tiers)


def pockets_in(geometry: BaseGeometry, share: Share) -> BaseGeometry:
    """The parts of `geometry` that count as tot-lot: at least the least width everywhere (a
    circle that wide rolls through them; corners keep their shape) and each piece at least the
    least pocket."""
    if geometry is None or geometry.is_empty:
        return Polygon()
    half = share.min_width_m / 2 - CUT_TOLERANCE_M
    wide = geometry.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")
    wide = _overlay(wide, geometry, MEET)
    return unary_union([p for p in _parts(wide) if p.area >= share.min_pocket_sqm])


def block_land_in(land: BaseGeometry, blocks: Blocks) -> BaseGeometry:
    """Where one of the firm's blocks fits: land as wide as its short side, in pieces that hold
    its footprint; the union over the firm's blocks."""
    if land.is_empty:
        return Polygon()
    out = []
    for _, length, depth in blocks.footprints:
        half = min(length, depth) / 2 - CUT_TOLERANCE_M
        wide = land.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")
        wide = _overlay(wide, land, MEET)
        out += [p for p in _parts(wide) if p.area >= length * depth]
    return unary_union(out) if out else Polygon()


def _overlay(a: BaseGeometry, b: BaseGeometry, how: str) -> BaseGeometry:
    """a's intersection with b, or a less b. GEOS refuses some outlines that meet at a hair's
    breadth ('non-noded intersection'); those are snapped to a millimetre grid and tried again."""
    try:
        return getattr(a, how)(b)
    except GEOSException:
        return getattr(set_precision(a, GRID_M), how)(set_precision(b, GRID_M))


def _parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    return [g for g in getattr(geometry, "geoms", [geometry])
            if isinstance(g, Polygon) and not g.is_empty]


def _touching(parts: list[Polygon]) -> list[BaseGeometry]:
    """The pieces that touch (within the cut's tolerance) as one pocket each, largest first; the
    shapes are kept exactly."""
    groups: list[BaseGeometry] = []
    for part in sorted(parts, key=lambda p: -p.area):
        near = [g for g in groups if g.distance(part) <= CUT_TOLERANCE_M]
        groups = [g for g in groups if all(g is not n for n in near)]
        groups.append(unary_union([part, *near]))
    return sorted(groups, key=lambda g: -g.area)


def _toward(start: BaseGeometry | None, end: BaseGeometry) -> tuple[float, float] | None:
    """The unit direction from one shape's middle to another's; None when they share it."""
    if start is None:
        return None
    a, b = start.centroid, end.centroid
    length = math.hypot(b.x - a.x, b.y - a.y)
    return None if length <= CUT_TOLERANCE_M else ((b.x - a.x) / length, (b.y - a.y) / length)


def _lengthwise(part: BaseGeometry, road: BaseGeometry | None) -> tuple[float, float] | None:
    """The direction along a pocket's length (its smallest enclosing rectangle's long side),
    pointing away from the main road."""
    with warnings.catch_warnings():  # GEOS divides by zero on a rectangle square to the axes
        warnings.simplefilter("ignore", RuntimeWarning)
        rectangle = part.minimum_rotated_rectangle
    if not isinstance(rectangle, Polygon):  # a line or a point: no length to cut along
        return None
    (ax, ay), (bx, by), (cx, cy) = list(rectangle.exterior.coords)[:3]
    dx, dy = max(((bx - ax, by - ay), (cx - bx, cy - by)), key=lambda d: math.hypot(*d))
    length = math.hypot(dx, dy)
    if length <= CUT_TOLERANCE_M:
        return None
    ux, uy = dx / length, dy / length
    away = _toward(road, part)
    return (-ux, -uy) if away is not None and ux * away[0] + uy * away[1] < 0 else (ux, uy)


def straight_cut(region: BaseGeometry, toward: tuple[float, float] | None, area: float,
                  keep) -> BaseGeometry:
    """The part of `region` furthest along `toward` that holds `area` m² of pockets that count,
    cut off by one straight line square to it. All of it when it holds no more."""
    whole = keep(region)
    toward = toward or _lengthwise(region, None)
    if whole.area <= area or toward is None:
        return whole
    ux, uy = toward
    along = [x * ux + y * uy for part in _parts(region) for x, y in part.exterior.coords]
    reach = sum(abs(c) for c in region.bounds)  # covers every point of the region

    def beyond(at: float) -> BaseGeometry:
        side = reach + abs(at)
        x, y = at * ux, at * uy  # on the line
        half = Polygon([(x - side * uy, y + side * ux),
                        (x - side * uy + side * ux, y + side * ux + side * uy),
                        (x + side * uy + side * ux, y - side * ux + side * uy),
                        (x + side * uy, y - side * ux)])
        return keep(_overlay(region, half, MEET))

    low, high = min(along), max(along)
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if beyond(middle).area >= area:
            low = middle
        else:
            high = middle
    return beyond(low)
