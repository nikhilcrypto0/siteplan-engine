"""Step 5: the buildings, and the tot-lot in what they leave, the architect's way (2026-10-12),
for any site; each option a whole one, so he never chooses buildings blind.

1. A height map: from the tallest building step 2 allows down one floor at a time to the lowest
   worth building (Stilt + 7: his word), each height keeping its own setbacks.
2. The buildings (buildings.py): the firm's blocks in straight rows, each arm of the plot along its
   own longest straight edge, the tallest first and lower ones into the narrow parts, round one
   road idea (a loop round the blocks, or a spine from the gate with rows facing it).
3. The tot-lot in what the blocks leave: 10% of the whole plot for a high-rise site or a Group
   Development Scheme (rules 7(a)(vii), 8(g)), 5% for any other plot above 750 m² (5(f)(vi)), in
   pockets at least 3 m wide and 50 m², inside the land left for buildings, never in a setback,
   in the gap between two blocks (7(a)(xii)), in a high-rise's fire lane (NBC Part 3 4.6), on a
   road or in front of the gate; several medium pieces rather than one big one; a right-angled
   triangle at the corners beside the gate. When the leftovers hold less than the share, the
   block that frees the most tot-lot for the fewest flats is shortened or dropped, and the flats
   lost are counted.
The club house comes in the next stage."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from shapely import affinity, set_precision
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from siteplan import rules
from siteplan.geometry import Run, facing_deg, straight_runs
from siteplan.intake import load_defaults
from siteplan.library import FlatLibrary
from siteplan.prototypes.compose import compose_library
from siteplan.steps import buildings
from siteplan.steps.buildings import (
    HIGH,
    LOOP,
    LOW,
    SPINE,
    SPINE_LOOP,
    Block,
    Kind,
    Layout,
    Plan,
)
from siteplan.steps.gate import on_net
from siteplan.steps.inputs import Inputs, compass
from siteplan.steps.setbacks import Setbacks, below_high_rise, land_left_at
from siteplan.steps.survey_copy import SHORT_RUN_M, SurveyCopy
from siteplan.units import SQM_PER_ACRE

CUT_TOLERANCE_M = 0.01  # how finely a piece's size is placed; pieces this close are one piece; a
# width this short of the least still counts (a 3.000 m strip is 3 m wide)
GRID_M = 0.001  # two outlines GEOS cannot overlay are snapped to this grid and tried again
LOWEST_FLOORS = 7  # the lowest block worth building: the architect's word (2026-10-12)
CORNER_TURN_DEG = 30.0  # the edge of the land turns at least this much at a major corner
STEEP = 3.0  # a gate corner's triangle: its long side, in times its small side
MEDIUM_SQM = 900.0  # a tot-lot piece is taken up to this first, so several medium pieces come
# before one big one (the reference plans' pockets run about 100 to 900 m²)
SAME_SQM = 1.0  # two layouts whose blocks differ by less than this are the same
EDGES_TRIED = 3  # the main part's rows are tried along this many of its longest straight edges
NARSINGI_FLATS_PER_ACRE = 367 / 3.95  # the approved Narsingi scheme: 367 flats on 3.95 acres
SECOND_LOOK = 0.5  # a layout under this share of Narsingi's density, or over its inverse, is
# worth a second look
FREE, WATER = "land no building stands on", "the water's buffer"
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
    flats, one row beside the corridor."""

    kinds: tuple[Kind, ...]
    source: str  # the file and how far it is confirmed

    @property
    def footprints(self) -> tuple[tuple[str, float, float], ...]:
        return tuple((k.what, k.length_m, k.depth_m) for k in self.kinds)

    @property
    def narrowest_m(self) -> float:
        return min(min(k.length_m, k.depth_m) for k in self.kinds)

    @property
    def shortest_m(self) -> float:
        return min(k.length_m for k in self.kinds)


class NoBlocks(Exception):
    """The workspace names a flat library that cannot be read or composed."""


def firm_blocks(workspace: Path | None) -> Blocks | None:
    """The firm's blocks (the kit, the flats in equal shares, and the slim one: one row of the
    shortest block's flats beside its corridor), or None when the workspace names no library."""
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
    slim = Kind("a slim block: one row of the firm's flats beside the corridor",
                shortest.length_m, library.flats[0].depth_m + library.corridor_width_m,
                max(1, shortest.per_floor.flats // 2))
    return Blocks((*(Kind(f"the kit's {block.id}", block.length_m, block.depth_m,
                          block.per_floor.flats) for block in kit), slim),
                  f"{defaults.flat_library}, the firm's flat library in the workspace "
                  f"({defaults.standard_status('flat_library')})")


@dataclass(frozen=True)
class Tier:
    """One height of the height map."""

    floors: int
    setback_m: float  # the widest of its sides' setbacks
    land: BaseGeometry  # the land a building this tall may stand on
    fits: BaseGeometry  # where one of the firm's blocks this tall fits, its setbacks kept
    tallest: BaseGeometry  # the part where this is the tallest building that fits
    band: BaseGeometry  # the setback land those blocks keep from the plot's edge
    high_rise: bool  # 21 m or more, counted (G.O.Ms.No.95): a fire lane all round
    # Below 21 m, the band the resolver reads (setbacks.below_high_rise): ALLOWED with Table
    # III's setback, or UNVERIFIED (no order read gives one: the setback drawn is Table IV's first
    # row, a stand-in) or PROHIBITED, and why (2026-10-13).
    permission: str = "ALLOWED"
    why: str = ""


@dataclass(frozen=True)
class Pocket:
    polygon: BaseGeometry
    lies: str  # where in the plot: 'north'
    on_sqm: tuple[tuple[str, float], ...]  # (FREE, WATER, ...), m²

    @property
    def area_sqm(self) -> float:
        return self.polygon.area


@dataclass(frozen=True)
class Placing:
    """One option on one reading of the water's buffer: its blocks and the tot-lot they leave."""

    reading: str  # FROM_LINE, FROM_EDGE, or '' when there is no water
    tiers: tuple[Tier, ...]  # tallest first
    layout: Layout  # the blocks as kept, after any the tot-lot asked back
    room: BaseGeometry  # the land left for buildings: no tot-lot outside it
    kept_out: BaseGeometry  # the blocks, the gaps between them, their setbacks and fire lanes
    leftover: BaseGeometry  # what the blocks leave, in pieces the tot-lot can use
    tot_lot: BaseGeometry
    pockets: tuple[Pocket, ...]
    need_sqm: float
    gate: BaseGeometry  # where the approach road comes in from the main road
    gate_zone: BaseGeometry  # kept clear in front of it: no tot-lot
    flats_first: int  # the flats before the tot-lot asked any back
    changes: tuple[str, ...]  # the blocks shortened or dropped for the tot-lot, said

    @property
    def flats(self) -> int:
        return self.layout.flats

    @property
    def flats_lost(self) -> int:
        return self.flats_first - self.flats

    @property
    def short_sqm(self) -> float:
        return max(0.0, self.need_sqm - self.tot_lot.area)

    def on(self, kind: str) -> float:
        return sum(area for pocket in self.pockets for k, area in pocket.on_sqm if k == kind)


@dataclass(frozen=True)
class Option:
    """One whole option the architect may choose: the buildings and their tot-lot, laid on every
    reading of the water."""

    number: int
    plan: Plan
    placings: tuple[Placing, ...]

    @property
    def placing(self) -> Placing:
        return self.placings[0]

    @property
    def holds(self) -> bool:
        return all(p.short_sqm <= CUT_TOLERANCE_M for p in self.placings)


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
    placings: tuple[Placing, ...] = ()  # option 1's, the first the one drawn
    options: tuple[Option, ...] = ()  # the whole options the architect chooses from
    failed: tuple[Option, ...] = ()  # layouts whose leftovers could not be made to hold it
    waiting: tuple[str, ...] = ()  # water whose buffer waits on an answer (step 3)

    @property
    def need_sqm(self) -> float:
        return self.share.fraction * self.plot_sqm if self.share else 0.0

    @property
    def net_need_sqm(self) -> float:
        net = self.setbacks.widening.net
        return self.share.fraction * net.area if self.share and net is not None else 0.0

    @property
    def acres(self) -> float:
        return self.plot_sqm / SQM_PER_ACRE


def lay_out(inputs: Inputs, copy: SurveyCopy, setbacks: Setbacks) -> TotLot:
    """The whole options: every plan's buildings, each with the tot-lot its leftovers hold."""
    t = TotLot(inputs, copy, setbacks)
    if setbacks.stopped:
        return _stop(t, "step 4 has no land left for buildings yet, and the buildings stand on "
                        "it", setbacks.ask)
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
        return _stop(t, "the firm's blocks are not known, and the buildings are laid with them",
                     ask)
    water = [w for w in setbacks.widening.water if w.buffer_m is not None]
    t.waiting = tuple(w.kind for w in setbacks.widening.water if w.buffer_m is None)
    readings = [("", None)] if not water else [
        (FROM_LINE, unary_union([w.kept_free for w in water])),
        (FROM_EDGE, unary_union([w.edge_kept_free for w in water]))]
    net = setbacks.widening.net
    gate = gate_of(setbacks)
    turn = setbacks.front_m + rules.FIRE_TURNING_RADIUS_M
    zone = in_front_of(gate, net, turn)
    maps = [(reading, buffer, height_map(setbacks, t.blocks, t.lowest, buffer))
            for reading, buffer in readings]
    tiers0 = maps[0][2]
    kinds = list(t.blocks.kinds)
    smallest = 2 * min(k.length_m * k.depth_m for k in kinds)
    arms = tuple(buildings.arms_of(tiers0[-1].land, smallest))
    reach = max(tier.setback_m for tier in tiers0) + rules.INTERNAL_ROAD_M
    ways = [buildings.directions(arm, net, reach) for arm in arms]
    turned = _gate_turn(gate, net, turn)
    loop = buildings.loop_band(net, setbacks.high_rise, arms[0], reach) if arms else Polygon()
    spine = _way_in(gate, net)
    options: list[Option] = []
    failed: list[Option] = []
    for plan in plans(arms, ways, gate, net):
        reserved = {LOOP: unary_union([loop, turned]), SPINE: zone,
                    SPINE_LOOP: unary_union([loop, zone])}[plan.road]
        spine_here = spine if plan.road != LOOP else None
        sides = (LOW, HIGH) if plan.road == LOOP else (LOW,)
        best = None
        for side in sides:  # the sweep from either side: the better is the plan's, not another
            blocks = buildings.lay(plan, arms, _lands(tiers0), kinds, reserved, spine_here, side)
            if best is None or sum(b.flats for b in blocks) > best[0]:
                best = (sum(b.flats for b in blocks), side)
        placings = []
        for reading, _buffer, tiers in maps:
            blocks = buildings.lay(plan, arms, _lands(tiers), kinds, reserved, spine_here,
                                   best[1])
            roads = {LOOP: loop, SPINE: spine or Polygon(),
                     SPINE_LOOP: unary_union([loop, spine or Polygon()])}[plan.road]
            layout = Layout(plan, blocks, roads, arms)
            placings.append(place(layout, tiers, t.need_sqm, t.share, net, gate, zone, kinds,
                                  t.blocks.shortest_m, reading))
        option = Option(0, plan, tuple(placings))
        same = next((o for o in options + failed if _same(o.placing.layout, option.placing.layout)),
                    None)
        if same is not None:
            continue
        (options if option.holds else failed).append(option)
    options.sort(key=lambda o: (-o.placing.flats, o.placing.flats_lost))
    t.options = tuple(replace(o, number=n) for n, o in enumerate(options, 1))
    t.failed = tuple(failed)
    shown = t.options or t.failed
    t.placings = shown[0].placings if shown else ()
    return t


def _stop(t: TotLot, why: str, ask: str | None) -> TotLot:
    t.stopped, t.ask = why, ask
    return t


def _lands(tiers: tuple[Tier, ...]) -> list[tuple[int, float, BaseGeometry]]:
    return [(tier.floors, tier.setback_m, tier.land) for tier in tiers]


def _same(a: Layout, b: Layout) -> bool:
    return _overlay(a.footprint, b.footprint, "symmetric_difference").area < SAME_SQM


def plans(arms: tuple[Polygon, ...], ways: list[list[tuple[float, str, float]]],
          gate: BaseGeometry, net: Polygon) -> list[Plan]:
    """The road and row ideas to lay: a loop with the main part's rows along its longest straight
    edge, and along each of its next two; a spine from the gate with rows facing it, with and
    without a loop round them. Every other arm's rows run along its own longest edge."""
    if not arms or not ways or not ways[0]:
        return []
    others = tuple(w[0][0] if w else ways[0][0][0] for w in ways[1:])
    arm_words = "".join(f"; the {where} arm's rows along its own {w[0][1]} edge"
                        for where, w in zip(_where(arms[1:], net), ways[1:], strict=True) if w)
    out = [Plan(LOOP, (angle, *others), f"Rows along the {faces} edge, a loop road round the "
                                        f"blocks{arm_words}")
           for angle, faces, _ in ways[0][:EDGES_TRIED]]
    if not gate.is_empty:
        (ax, ay), (bx, by) = gate.coords[0], gate.coords[-1]
        angle = (math.degrees(math.atan2(by - ay, bx - ax)) + 90) % 180
        out.append(Plan(SPINE, (angle, *others), "Two rows facing a spine road straight in from "
                                                 f"the gate{arm_words}"))
        out.append(Plan(SPINE_LOOP, (angle, *others), "Two rows facing a spine road from the "
                                                      f"gate, a loop road round them{arm_words}"))
    return out


def _where(arms: tuple[Polygon, ...], net: Polygon) -> list[str]:
    middle = net.centroid
    out = []
    for arm in arms:
        c = arm.centroid
        out.append(compass(math.degrees(math.atan2(c.x - middle.x, c.y - middle.y)) % 360))
    return out


def gate_of(s: Setbacks) -> BaseGeometry:
    """Where the approach road comes in on the net plot: the main road's stretch of its edge, or
    the land given up to widen the main road (steps/gate.py)."""
    return on_net(s.widening.net, s.height.road, s.widening.pieces)


def _way_in(gate: BaseGeometry, net: Polygon) -> BaseGeometry | None:
    """The way the approach road comes straight in from the gate, as wide as the gate, across
    the plot."""
    if gate.is_empty:
        return None
    (ax, ay), (bx, by) = gate.coords[0], gate.coords[-1]
    length = math.hypot(bx - ax, by - ay)
    if length <= CUT_TOLERANCE_M:
        return None
    nx, ny = -(by - ay) / length, (bx - ax) / length
    middle = gate.interpolate(0.5, normalized=True)
    if not net.contains(Point(middle.x + nx, middle.y + ny)):
        nx, ny = -nx, -ny
    x0, y0, x1, y1 = net.bounds
    far = 2 * math.hypot(x1 - x0, y1 - y0)
    return _overlay(Polygon([(ax, ay), (bx, by), (bx + nx * far, by + ny * far),
                             (ax + nx * far, ay + ny * far)]), net, MEET)


def _gate_turn(gate: BaseGeometry, net: Polygon, turn_m: float) -> BaseGeometry:
    return _overlay(gate.buffer(turn_m), net, MEET) if not gate.is_empty else Polygon()


def in_front_of(gate: BaseGeometry, net: Polygon, turn_m: float) -> BaseGeometry:
    """The land in front of the gate, never tot-lot (the architect, 2026-10-12): the way the
    approach road comes straight in, as wide as the gate, across the plot; and the turn a fire
    engine makes coming in, `turn_m` round the gate. Beside the gate, along the edge, is not in
    front of it."""
    way = _way_in(gate, net)
    return unary_union([g for g in (way, _gate_turn(gate, net, turn_m)) if g is not None])


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
        high = s.height.storeys.counted_m(floors) >= rules.HIGH_RISE_THRESHOLD_M - CUT_TOLERANCE_M
        stretch = None if high else below_high_rise(s, floors)
        settled = stretch is None or stretch.side_m is not None
        out.append(Tier(floors, setback, land, fits, _overlay(fits, claimed, DIFF), band, high,
                        "ALLOWED" if settled else stretch.permission.value,
                        "" if settled else stretch.note))
        claimed = unary_union([claimed, fits])
    return tuple(out)


def place(layout: Layout, tiers: tuple[Tier, ...], need_sqm: float, share: Share, plot: Polygon,
          gate: BaseGeometry, zone: BaseGeometry, kinds: list[Kind], shortest_m: float,
          reading: str = "") -> Placing:
    """The tot-lot in what a layout's blocks leave; when that holds less than the share, the block
    that frees the most of it for the fewest flats is shortened or dropped, until it holds."""
    def keep(geometry: BaseGeometry) -> BaseGeometry:
        return pockets_in(geometry, share)

    room = tiers[-1].land  # the land left for buildings: the lowest height's, the widest
    corners = beside_gate(corners_of_land(room, plot, major_edges(plot, shortest_m)), gate)
    first = layout.flats
    layout, changes = _repair(layout, need_sqm, kinds, lambda trial: _leftover(
        trial, tiers, room, zone, corners, gate, keep)[0])
    leftover, kept_out = _leftover(layout, tiers, room, zone, corners, gate, keep)
    tot_lot = _medium_first(leftover, need_sqm, layout.footprint, keep)
    middle = (plot.centroid.x, plot.centroid.y)
    pockets = tuple(Pocket(part, compass(math.degrees(math.atan2(
        part.centroid.x - middle[0], part.centroid.y - middle[1])) % 360),
        _stands_on(part, tiers, layout))
        for part in sorted(_parts(tot_lot), key=lambda g: -g.area))
    return Placing(reading, tiers, layout, room, kept_out, leftover, tot_lot, pockets, need_sqm,
                   gate, zone, first, tuple(changes))


def _repair(layout: Layout, need: float, kinds: list[Kind],
            leftover_of) -> tuple[Layout, list[str]]:
    """Blocks shortened or dropped until the leftovers hold `need`, losing the fewest flats: step
    by step the change that frees the most tot-lot for each flat lost, and at every step the
    cheapest change that would hold it at once; the cheapest whole path is kept."""
    current, changes = layout, []
    best: tuple[int, Layout, list[str]] | None = None
    while True:
        left = leftover_of(current).area
        if left >= need - CUT_TOLERANCE_M:
            if best is None or layout.flats - current.flats < best[0]:
                best = (layout.flats - current.flats, current, changes)
            break
        finish, rate = None, None
        for i in range(len(current.blocks)):
            for blocks, said in _smaller(current.blocks, i, kinds):
                trial = replace(current, blocks=blocks)
                more = leftover_of(trial).area
                gain, lost = more - left, current.flats - trial.flats
                if gain <= CUT_TOLERANCE_M:
                    continue
                if more >= need - CUT_TOLERANCE_M and (finish is None or lost < finish[0]):
                    finish = (lost, trial, said)
                if rate is None or gain / max(lost, 1) > rate[0]:
                    rate = (gain / max(lost, 1), trial, said)
        if finish is not None:
            total = layout.flats - finish[1].flats
            if best is None or total < best[0]:
                best = (total, finish[1], [*changes, finish[2]])
        if rate is None or (best is not None and layout.flats - rate[1].flats >= best[0]):
            break
        current, changes = rate[1], [*changes, rate[2]]
    return (best[1], best[2]) if best else (current, changes)


def _leftover(layout: Layout, tiers: tuple[Tier, ...], room: BaseGeometry, zone: BaseGeometry,
              corners: list[Seat], gate: BaseGeometry,
              keep) -> tuple[BaseGeometry, BaseGeometry]:
    """What a layout's blocks leave for the tot-lot, and what they keep out of it: the blocks, the
    gap between any two (the taller one's setback, 7(a)(xii)), each block's setback from the
    plot's edge, a high-rise's fire lane all round (NBC Part 3 4.6), the roads and the land in
    front of the gate; the corners beside the gate cut to right-angled triangles."""
    by_floors = {tier.floors: tier for tier in tiers}
    blocks = layout.blocks
    out: list[BaseGeometry] = [b.polygon for b in blocks]
    for i, a in enumerate(blocks):
        tier = by_floors[a.floors]
        out.append(_overlay(tier.band, a.polygon.buffer(tier.setback_m + CUT_TOLERANCE_M,
                                                        join_style="mitre"), MEET))
        if tier.high_rise:
            out.append(a.polygon.buffer(rules.FIRE_TENDER_MIN_WIDTH_M, join_style="mitre"))
        for b in blocks[i + 1:]:
            gap = by_floors[max(a.floors, b.floors)].setback_m
            if a.polygon.distance(b.polygon) <= gap + CUT_TOLERANCE_M:
                between = _overlay(a.polygon.buffer(gap, join_style="mitre"),
                                   b.polygon.buffer(gap, join_style="mitre"), MEET)
                out.append(between)
    kept_out = unary_union(out)
    free = _overlay(_overlay(_overlay(room, kept_out, DIFF), zone, DIFF), layout.roads, DIFF)
    for seat in corners:
        patch, triangle = _gate_corner(seat, gate)
        free = _overlay(free, _overlay(patch, triangle, DIFF), DIFF)
    return keep(free.buffer(0)), kept_out


def _smaller(blocks: tuple[Block, ...], i: int,
             kinds: list[Kind]) -> list[tuple[tuple[Block, ...], str]]:
    """Block `i` dropped, or shortened to each shorter block of the firm's of the same depth,
    kept at either end of where it stood."""
    block = blocks[i]
    rest = blocks[:i] + blocks[i + 1:]
    out = [(rest, f"dropped a Stilt + {block.floors} block ({block.kind.what}, "
                  f"{block.flats} flats)")]
    turned = affinity.rotate(block.polygon, -block.angle_deg, origin=(0, 0))
    x0, y0, x1, y1 = turned.bounds
    for kind in kinds:
        if kind.depth_m != block.kind.depth_m or kind.length_m >= block.kind.length_m:
            continue
        for start in (x0, x1 - kind.length_m):
            shorter = affinity.rotate(box(start, y0, start + kind.length_m, y1), block.angle_deg,
                                      origin=(0, 0))
            out.append((rest[:i] + (replace(block, polygon=shorter, kind=kind),) + rest[i:],
                        f"shortened a Stilt + {block.floors} block to {kind.what} "
                        f"({block.flats - kind.flats_per_floor * block.floors} flats fewer)"))
    return out


def _medium_first(leftover: BaseGeometry, need: float, buildings_: BaseGeometry,
                  keep) -> BaseGeometry:
    """`need` of the leftovers in several medium pieces: each piece first up to MEDIUM_SQM, the
    part farthest from the blocks, the largest pieces first; only then larger."""
    pieces = sorted(_parts(leftover), key=lambda g: -g.area)
    taken: list[BaseGeometry] = [Polygon() for _ in pieces]
    for cap in (MEDIUM_SQM, math.inf):
        for k, piece in enumerate(pieces):
            left = need - sum(g.area for g in taken)
            if left <= CUT_TOLERANCE_M:
                break
            target = min(cap, piece.area, taken[k].area + left)
            if target > taken[k].area + CUT_TOLERANCE_M:
                taken[k] = _far_first(piece, buildings_, target, keep)
    return unary_union([g for g in taken if not g.is_empty]) if any(
        not g.is_empty for g in taken) else Polygon()


def _far_first(free: BaseGeometry, buildings_: BaseGeometry, need: float,
               keep) -> BaseGeometry:
    """`need` of the land, the part farthest from the blocks first (all of it when it holds
    less)."""
    if free.is_empty or need <= CUT_TOLERANCE_M:
        return Polygon()
    if free.area <= need:
        return free
    if buildings_.is_empty:
        buildings_ = free.centroid
    low, high = 0.0, free.hausdorff_distance(buildings_)
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if keep(_overlay(free, buildings_.buffer(middle), DIFF)).area >= need:
            low = middle
        else:
            high = middle
    return keep(_overlay(free, buildings_.buffer(low), DIFF))


def major_edges(net: Polygon, shortest_m: float) -> tuple[tuple[str, tuple[Run, ...]], ...]:
    """The plot's major edges: neighbouring straight stretches facing the same way are one edge
    (a jog shorter than SHORT_RUN_M between them does not part them), and an edge is major when
    it is as long as the firm's shortest block. Each with the way it faces and its stretches."""
    groups: list[tuple[str, list[Run]]] = []
    for part in _parts(net):
        runs = straight_runs(part)
        start = len(groups)
        for run in runs:
            if run.length < SHORT_RUN_M:
                continue
            faces = compass(facing_deg(part, run))
            if len(groups) > start and groups[-1][0] == faces:
                groups[-1][1].append(run)
            else:
                groups.append((faces, [run]))
        if len(groups) - start > 1 and groups[-1][0] == groups[start][0]:  # round the start
            faces, last = groups.pop()
            groups[start] = (faces, last + groups[start][1])
    return tuple((faces, tuple(runs)) for faces, runs in groups
                 if sum(r.length for r in runs) >= shortest_m)


@dataclass(frozen=True)
class Seat:
    """A major corner of the land: on its edge (`ring`, anticlockwise) at `at`, its sides running
    back and ahead as far as halfway to the next corners (`back`, `ahead`)."""

    ring: LineString
    at: float
    back: float
    ahead: float

    @property
    def point(self) -> BaseGeometry:
        return self.ring.interpolate(self.at)

    def side(self, ahead: bool) -> tuple[tuple[float, float], float]:
        """The unit way along one side from the corner, and how far it runs."""
        reach = self.ahead if ahead else self.back
        end = self.ring.interpolate((self.at + (reach if ahead else -reach)) % self.ring.length)
        here = self.point
        length = math.hypot(end.x - here.x, end.y - here.y) or 1.0
        return ((end.x - here.x) / length, (end.y - here.y) / length), reach


def corners_of_land(land: BaseGeometry, net: Polygon,
                    edges: tuple[tuple[str, tuple[Run, ...]], ...]) -> list[Seat]:
    """The major corners: where the land's edge facing one major edge of the plot turns, by at
    least CORNER_TURN_DEG and outward (a corner, not a notch), into the edge facing the next."""
    runs = [run for part in _parts(net) for run in straight_runs(part)]
    owner = {tuple(run.line.coords): i for i, (_, own) in enumerate(edges) for run in own}
    seats: list[Seat] = []
    for part in _parts(land):
        ring = LineString(orient(part, 1.0).exterior.coords)  # anticlockwise: land on the left
        coords = list(ring.coords)
        pieces = []  # (start, end, the major edge it faces or None, its direction)
        start = 0.0
        for a, b in zip(coords, coords[1:], strict=False):
            length = math.dist(a, b)
            if length == 0:
                continue
            middle = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            nearest = min(runs, key=lambda run: run.line.distance(middle))
            pieces.append((start, start + length, owner.get(tuple(nearest.line.coords)),
                           math.atan2(b[1] - a[1], b[0] - a[0])))
            start += length
        found = _turns(pieces, ring.length)
        for k, at in enumerate(found):
            before = (at - found[k - 1]) % ring.length or ring.length
            after = (found[(k + 1) % len(found)] - at) % ring.length or ring.length
            seats.append(Seat(ring, at, before / 2, after / 2))
    return seats


def _turns(pieces: list[tuple], total: float) -> list[float]:
    """The places along the ring where the edge facing one major edge gives way to the edge
    facing the next, turning left (outward) by at least CORNER_TURN_DEG on the way."""
    count = len(pieces)
    marked = [i for i in range(count) if pieces[i][2] is not None]
    out = []
    for n, i in enumerate(marked):
        j = marked[(n + 1) % len(marked)]
        if pieces[j][2] == pieces[i][2]:
            continue
        turn, k = 0.0, i
        while k != j:
            nxt = (k + 1) % count
            turn += (pieces[nxt][3] - pieces[k][3] + math.pi) % (2 * math.pi) - math.pi
            k = nxt
        if math.degrees(turn) < CORNER_TURN_DEG:
            continue
        gap = (pieces[j][0] - pieces[i][1]) % total
        out.append((pieces[i][1] + gap / 2) % total)
    return sorted(out)


def beside_gate(seats: list[Seat], gate: BaseGeometry) -> list[Seat]:
    """The corners on either side of the gate along the land's edge."""
    if gate.is_empty or not seats:
        return []
    middle = gate.interpolate(0.5, normalized=True)
    out: list[Seat] = []
    for ring in {id(s.ring): s.ring for s in seats}.values():
        own = sorted((s for s in seats if s.ring is ring), key=lambda s: s.at)
        here = ring.project(middle)
        ahead = next((s for s in own if s.at >= here), own[0])
        back = next((s for s in reversed(own) if s.at < here), own[-1])
        out += [ahead] if ahead is back else [back, ahead]
    return sorted(out, key=lambda s: s.point.distance(middle))[:2]


def _gate_corner(seat: Seat, gate: BaseGeometry) -> tuple[Polygon, Polygon]:
    """A corner beside the gate: the patch its two sides make, and the right-angled triangle in
    it the tot-lot keeps (the architect, 2026-10-12): its small side along the side toward the
    gate, its long side STEEP times that along the other, the slant between."""
    (ax, ay), back = seat.side(False)
    (bx, by), ahead = seat.side(True)
    p = seat.point
    cx, cy = p.x, p.y
    patch = Polygon([(cx, cy), (cx + ax * back, cy + ay * back),
                     (cx + ax * back + bx * ahead, cy + ay * back + by * ahead),
                     (cx + bx * ahead, cy + by * ahead)])
    toward_back = Point(cx + ax, cy + ay).distance(gate) <= Point(cx + bx, cy + by).distance(gate)
    (sx, sy), small_reach, (lx, ly), long_reach = (
        ((ax, ay), back, (bx, by), ahead) if toward_back else ((bx, by), ahead, (ax, ay), back))
    small = min(long_reach / STEEP, small_reach)
    triangle = Polygon([(cx, cy), (cx + sx * small, cy + sy * small),
                        (cx + lx * long_reach, cy + ly * long_reach)])
    return patch, triangle


def _stands_on(part: BaseGeometry, tiers: tuple[Tier, ...],
               layout: Layout) -> tuple[tuple[str, float], ...]:
    """What a tot-lot piece takes: land a block of each height could have stood on, or none."""
    out = [(f"Stilt + {tier.floors} land", _overlay(part, tier.tallest, MEET).area)
           for tier in tiers]
    free = part.area - sum(a for _, a in out)
    return tuple((kind, area) for kind, area in [*out, (FREE, free)]
                 if area > CUT_TOLERANCE_M)


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
