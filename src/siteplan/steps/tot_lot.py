"""Step 5: where buildings can stand, and the tot-lot, the architect's way (2026-10-12), for any
site.

1. A height map. Where the tallest building step 2 allows does not fit, one floor lower is
   tried, then the next, down to the lowest block worth building (Stilt + 7: his word), each
   height keeping its own setbacks; the blocks are the firm's own, the double-loaded kit and a
   slim one (one row of flats beside the corridor), turned either way. Each part of the land is
   marked with the tallest building that fits there. The plot's edge always keeps a setback.
2. The gate, where the main road meets the plot. Nothing stands in front of it: the way the
   approach road comes straight in, as wide as the gate, and a fire engine's turn there.
3. The tot-lot: 10% of the whole plot for a high-rise site or a Group Development Scheme (rules
   7(a)(vii), 8(g)), 5% for any other plot above 750 m² (5(f)(vi)), in pockets at least 3 m
   wide, out of every setback. First the land no building fits on; then pockets at the plot's
   major corners, the patch the corner's two sides make. Beside the gate a corner's pocket is a
   right-angled triangle, its small side along the gate's side and the long slant away from it
   (his word). Twenty different ways of choosing the corners and shaping the pockets are laid
   out for the architect to choose one. A water body's buffer may count (3(a)(iii)(3)); the gaps
   between blocks never do (7(a)(xii))."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path

from shapely import set_precision
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from siteplan import rules
from siteplan.geometry import Run, facing_deg, straight_runs
from siteplan.intake import load_defaults
from siteplan.library import FlatLibrary
from siteplan.prototypes.compose import compose_library
from siteplan.steps.gate import on_net
from siteplan.steps.inputs import Inputs, bearing, compass
from siteplan.steps.setbacks import Setbacks, land_left_at
from siteplan.steps.survey_copy import SHORT_RUN_M, SurveyCopy

CUT_TOLERANCE_M = 0.01  # how finely a pocket's size is placed; pieces this close are one pocket;
# a width this short of the least still counts (a 3.000 m strip is 3 m wide)
GRID_M = 0.001  # two outlines GEOS cannot overlay are snapped to this grid and tried again
LOWEST_FLOORS = 7  # the lowest block worth building: the architect's word (2026-10-12)
CORNER_TURN_DEG = 30.0  # the edge of the land turns at least this much at a major corner
SHARP_DEG = 60.0  # a corner sharper than this is cut straight across, not spanned by its sides
STEEP, SHALLOW = 3.0, 2.0  # a triangle's long side, in times its small side
OPTIONS = 20  # how many tot-lots the architect is shown, to choose one (his word, 2026-10-12)
SAME_SQM = 1.0  # two options whose tot-lots differ by less than this are the same
FREE, WATER = "land no building fits on", "the water's buffer"
FROM_LINE, FROM_EDGE = "the buffer from the line drawn", "the buffer from the plot's edge"
MEET, DIFF = "intersection", "difference"
CHEAPEST, ALL, FAR, NEAR, COUNT, SET = "cheapest", "all", "far", "near", "count", "set"
SETS = (2, 3)  # after the named ideas, every two and then every three of a site's corners
AT_GATE, EVERY = "at the gate", "every"


@dataclass(frozen=True)
class Idea:
    """One way of laying the tot-lot. Every idea keeps the same rules: the whole share, out of
    every setback, never in front of the gate, triangles beside it."""

    words: str
    free_first: bool = True  # the land no building fits on goes first
    pick: str = CHEAPEST  # CHEAPEST: as many of the cheapest corners as cost the least in all;
    # ALL; FAR (from the gate); NEAR (the two beside it); COUNT: the `count` cheapest; SET: the
    # corners numbered in `members`
    count: int = 0
    members: tuple[int, ...] = ()
    triangles: str = AT_GATE  # AT_GATE: the corners beside the gate; EVERY: every corner
    ratio: float = STEEP  # a triangle's long side, in times its small side


FIRST = "no-building land first, then "
LATER = ", nothing taken first"
IDEAS = (  # in the order the architect sees them; the first is the way of 2026-10-11
    Idea(FIRST + "the corners that cost the fewest floors"),
    Idea(FIRST + "every major corner equally", pick=ALL),
    Idea(FIRST + "only the corners farthest from the gate", pick=FAR),
    Idea(FIRST + "only the two corners beside the gate, as triangles", pick=NEAR),
    Idea(FIRST + "the two cheapest corners", pick=COUNT, count=2),
    Idea(FIRST + "the three cheapest corners", pick=COUNT, count=3),
    Idea(FIRST + "the corners that cost the fewest floors, every one a triangle",
         triangles=EVERY),
    Idea(FIRST + "every major corner equally, every one a triangle", pick=ALL, triangles=EVERY),
    Idea(FIRST + "the corners farthest from the gate, as triangles", pick=FAR, triangles=EVERY),
    Idea(FIRST + "the two corners beside the gate, wider triangles", pick=NEAR, ratio=SHALLOW),
    Idea(FIRST + "every major corner equally, wider triangles", pick=ALL, triangles=EVERY,
         ratio=SHALLOW),
    Idea(FIRST + "the two cheapest corners, as triangles", pick=COUNT, count=2,
         triangles=EVERY),
    Idea(FIRST + "the three cheapest corners, as triangles", pick=COUNT, count=3,
         triangles=EVERY),
    Idea("the corners that cost the fewest floors" + LATER, free_first=False),
    Idea("every major corner equally" + LATER, free_first=False, pick=ALL),
    Idea("the corners farthest from the gate" + LATER, free_first=False, pick=FAR),
    Idea("the two corners beside the gate, as triangles" + LATER, free_first=False, pick=NEAR),
    Idea("every major corner equally, every one a triangle" + LATER, free_first=False,
         pick=ALL, triangles=EVERY),
    Idea("the two cheapest corners" + LATER, free_first=False, pick=COUNT, count=2),
    Idea("the three cheapest corners" + LATER, free_first=False, pick=COUNT, count=3),
    Idea(FIRST + "the corners farthest from the gate, wider triangles", pick=FAR,
         triangles=EVERY, ratio=SHALLOW),
    Idea(FIRST + "the corners that cost the fewest floors, wider triangles", triangles=EVERY,
         ratio=SHALLOW),
    Idea("the two corners beside the gate, wider triangles" + LATER, free_first=False,
         pick=NEAR, ratio=SHALLOW),
    Idea("the corners farthest from the gate, as triangles" + LATER, free_first=False,
         pick=FAR, triangles=EVERY),
)


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

    @property
    def shortest_m(self) -> float:
        return min(length for _, length, _ in self.footprints)


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
class Pocket:
    polygon: BaseGeometry  # one piece, or pieces that touch
    lies: str  # where: 'on the land no building fits on', 'at the north corner'
    on_sqm: tuple[tuple[str, float], ...]  # (FREE, WATER or 'Stilt + N land', m²)

    @property
    def area_sqm(self) -> float:
        return self.polygon.area


@dataclass(frozen=True)
class Corner:
    """A major corner and the tot-lot it takes."""

    number: int
    lies: str  # 'south-west', from the plot's middle
    point: BaseGeometry
    share_sqm: float  # what it was given
    tot_lot: BaseGeometry
    triangle: bool  # a right-angled triangle, its small side toward the gate


@dataclass(frozen=True)
class Placing:
    """The height map and the tot-lot on one reading of the water's buffer."""

    reading: str  # FROM_LINE, FROM_EDGE, or '' when there is no water
    tiers: tuple[Tier, ...]  # tallest first
    room: BaseGeometry  # the plot less its edge's setback: where a pocket may go
    free: BaseGeometry  # land no building fits on, inside the edge's own setback
    tot_lot: BaseGeometry
    free_taken: BaseGeometry  # the tot-lot laid on the land no building fits on
    pockets: tuple[Pocket, ...]
    need_sqm: float
    gate: BaseGeometry  # where the approach road comes in from the main road
    gate_zone: BaseGeometry  # kept clear in front of it: no tot-lot
    corners: tuple[Corner, ...]  # the corners that took the rest, and what each took
    standing: tuple[BaseGeometry, ...]  # each height's land where a block still fits once the
    # tot-lot is out, measured again

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
        """Where a building fits once the tot-lot is out: land it leaves too thin for a block
        no longer counts."""
        return unary_union(self.standing)

    @property
    def kept_setbacks(self) -> BaseGeometry:
        """The setback land kept beside where a building can still stand, each height's own."""
        return unary_union([_overlay(tier.band, land.buffer(
            tier.setback_m + CUT_TOLERANCE_M, join_style="mitre"), MEET)
            for tier, land in zip(self.tiers, self.standing, strict=True)])

    def floors_lost_sqm(self) -> float:
        """The tot-lot's area on building land, each square metre counted by the floors that
        would stand there (Stilt + 10 land costs ten floors a square metre)."""
        return _cost(self.tot_lot, self.tiers)


@dataclass(frozen=True)
class Option:
    """One tot-lot the architect may choose: an idea, laid on every reading of the water."""

    number: int
    idea: Idea
    placings: tuple[Placing, ...]
    same: tuple[str, ...] = ()  # further ideas that came out the same

    @property
    def placing(self) -> Placing:
        return self.placings[0]


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
    options: tuple[Option, ...] = ()  # the tot-lots the architect chooses from
    waiting: tuple[str, ...] = ()  # water whose buffer waits on an answer (step 3)

    @property
    def need_sqm(self) -> float:
        return self.share.fraction * self.plot_sqm if self.share else 0.0

    @property
    def net_need_sqm(self) -> float:
        net = self.setbacks.widening.net
        return self.share.fraction * net.area if self.share and net is not None else 0.0


def lay_out(inputs: Inputs, copy: SurveyCopy, setbacks: Setbacks,
            ideas: tuple[Idea, ...] | None = None) -> TotLot:
    """The height map and the tot-lot options: `ideas`, or the named ideas and then the sets of
    the site's own corners, until OPTIONS different tot-lots."""
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
    water = [w for w in setbacks.widening.water if w.buffer_m is not None]
    t.waiting = tuple(w.kind for w in setbacks.widening.water if w.buffer_m is None)
    readings = [("", None)] if not water else [
        (FROM_LINE, unary_union([w.kept_free for w in water])),
        (FROM_EDGE, unary_union([w.edge_kept_free for w in water]))]
    net = setbacks.widening.net
    gate = gate_of(setbacks)
    zone = in_front_of(gate, net, setbacks.front_m + rules.FIRE_TURNING_RADIUS_M)
    maps = [(reading, buffer, height_map(setbacks, t.blocks, t.lowest, buffer))
            for reading, buffer in readings]
    if ideas is None:
        ideas = IDEAS + corner_sets(net, maps[0][2], t.blocks)
    options: list[Option] = []
    for idea in ideas:
        placings = tuple(place(tiers, buffer, t.need_sqm, t.share, net, gate, zone, t.blocks,
                               reading, idea)
                         for reading, buffer, tiers in maps)
        twin = next((i for i, o in enumerate(options)
                     if _overlay(o.placing.tot_lot, placings[0].tot_lot, "symmetric_difference")
                     .area < SAME_SQM), None)
        if twin is not None:
            options[twin] = replace(options[twin], same=(*options[twin].same, idea.words))
            continue
        options.append(Option(len(options) + 1, idea, placings))
        if len(options) == OPTIONS:
            break
    t.options = tuple(options)
    t.placings = options[0].placings
    return t


def corner_sets(net: Polygon, tiers: tuple[Tier, ...], blocks: Blocks) -> tuple[Idea, ...]:
    """Every two, then every three, of the site's major corners, named by where they lie: first
    with the no-building land taken first, then each set as triangles."""
    seats = corners_of_land(room_of(net, tiers), net, major_edges(net, blocks.shortest_m))
    middle = (net.centroid.x, net.centroid.y)
    words = [compass(bearing(middle, (s.point.x, s.point.y))) for s in seats]
    names = [f"{w} ({i + 1})" if words.count(w) > 1 else w for i, w in enumerate(words)]
    out = []
    for size in SETS:
        for members in combinations(range(len(seats)), size):
            where = " and ".join(names[i] for i in members)
            out.append(Idea(f"{FIRST}the {where} corners", pick=SET, members=members))
    for size in SETS:
        for members in combinations(range(len(seats)), size):
            where = " and ".join(names[i] for i in members)
            out.append(Idea(f"{FIRST}the {where} corners, as triangles", pick=SET,
                            members=members, triangles=EVERY))
    return tuple(out)


def _stop(t: TotLot, why: str, ask: str | None) -> TotLot:
    t.stopped, t.ask = why, ask
    return t


def gate_of(s: Setbacks) -> BaseGeometry:
    """Where the approach road comes in on the net plot: the main road's stretch of its edge, or
    the land given up to widen the main road (steps/gate.py)."""
    return on_net(s.widening.net, s.height.road, s.widening.pieces)


def in_front_of(gate: BaseGeometry, net: Polygon, turn_m: float) -> BaseGeometry:
    """The land in front of the gate, never tot-lot (the architect, 2026-10-12): the way the
    approach road comes straight in, as wide as the gate, across the plot; and the turn a fire
    engine makes coming in, `turn_m` round the gate. Beside the gate, along the edge, is not in
    front of it."""
    if gate.is_empty:
        return Polygon()
    (ax, ay), (bx, by) = gate.coords[0], gate.coords[-1]
    length = math.hypot(bx - ax, by - ay)
    if length <= CUT_TOLERANCE_M:
        return _overlay(gate.buffer(turn_m), net, MEET)
    nx, ny = -(by - ay) / length, (bx - ax) / length
    middle = gate.interpolate(0.5, normalized=True)
    if not net.contains(Point(middle.x + nx, middle.y + ny)):
        nx, ny = -nx, -ny
    x0, y0, x1, y1 = net.bounds
    far = 2 * math.hypot(x1 - x0, y1 - y0)
    way_in = Polygon([(ax, ay), (bx, by), (bx + nx * far, by + ny * far),
                      (ax + nx * far, ay + ny * far)])
    return _overlay(unary_union([way_in, gate.buffer(turn_m)]), net, MEET)


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


def room_of(net: Polygon, tiers: tuple[Tier, ...]) -> BaseGeometry:
    """The plot less the setback its edge always keeps, a building beside it or not: the lowest
    block's (the outside boundary is never touched; the green strip and the fire lane run in
    it)."""
    return net.buffer(-tiers[-1].setback_m, join_style="mitre")


def _free(tiers: tuple[Tier, ...], room: BaseGeometry) -> BaseGeometry:
    """The room less every place a block fits and the setback land each keeps beside it: no
    building can stand here."""
    kept = [_overlay(tier.band, tier.fits.buffer(tier.setback_m + CUT_TOLERANCE_M,
                                                 join_style="mitre"), MEET)
            for tier in tiers]
    used = unary_union([*(tier.fits for tier in tiers), *kept])
    return _overlay(room, used, DIFF)


def place(tiers: tuple[Tier, ...], buffer: BaseGeometry | None, need_sqm: float, share: Share,
          plot: Polygon, gate: BaseGeometry, zone: BaseGeometry, blocks: Blocks | None = None,
          reading: str = "", idea: Idea = IDEAS[0]) -> Placing:
    """The tot-lot as the idea lays it: first (when it says so) the land no building fits on,
    the part farthest from the buildings first; then pockets at the major corners it picks, an
    equal share each, never in front of the gate and out of every setback."""
    def keep(geometry: BaseGeometry) -> BaseGeometry:
        return pockets_in(geometry, share)

    room = room_of(plot, tiers)
    free = _free(tiers, room)
    buildable = unary_union([tier.fits for tier in tiers])
    first = (_far_first(keep(_overlay(free, zone, DIFF)),
                        buildable if not buildable.is_empty else plot.centroid, need_sqm, keep)
             if idea.free_first else Polygon())
    rest = need_sqm - first.area
    corners: tuple[Corner, ...] = ()
    if rest > CUT_TOLERANCE_M:
        shortest = blocks.shortest_m if blocks is not None else 0.0
        seats = corners_of_land(room, plot, major_edges(plot, shortest))
        out = unary_union([zone, first]) if not first.is_empty else zone
        corners = _at_corners(idea, seats, gate, room, tiers, out, rest, plot, keep)
    tot_lot = unary_union([first, *(c.tot_lot for c in corners)])
    pockets = ((Pocket(first, "on the land no building fits on",
                       _stands_on(first, free, buffer, tiers)),) if not first.is_empty else ())
    pockets += tuple(Pocket(c.tot_lot, f"at the {c.lies} corner"
                            + (" (a triangle)" if c.triangle else ""),
                            _stands_on(c.tot_lot, free, buffer, tiers))
                     for c in corners if not c.tot_lot.is_empty)
    standing = tuple(_overlay(tier.fits, tot_lot, DIFF) if blocks is None
                     else block_land_in(_overlay(tier.fits, tot_lot, DIFF), blocks)
                     for tier in tiers)
    return Placing(reading, tiers, room, free, tot_lot, first, pockets, need_sqm, gate, zone,
                   corners, standing)


def _far_first(free: BaseGeometry, buildings: BaseGeometry, need: float, keep) -> BaseGeometry:
    """`need` of the land no building fits on, the part farthest from the buildings first (all
    of it when it holds less)."""
    if free.is_empty or need <= CUT_TOLERANCE_M:
        return Polygon()
    if free.area <= need:
        return free
    low, high = 0.0, free.hausdorff_distance(buildings)
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if keep(_overlay(free, buildings.buffer(middle), DIFF)).area >= need:
            low = middle
        else:
            high = middle
    return keep(_overlay(free, buildings.buffer(low), DIFF))


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
    """A major corner of the land a pocket may take: on its edge (`ring`, anticlockwise) at `at`,
    its sides running back and ahead as far as halfway to the next corners (`back`, `ahead`)."""

    ring: LineString
    at: float
    back: float
    ahead: float

    @property
    def point(self) -> BaseGeometry:
        return self.ring.interpolate(self.at)

    def side(self, ahead: bool) -> tuple[tuple[float, float], float]:
        """The unit way along one side from the corner, and how far the pocket may run on it."""
        reach = self.ahead if ahead else self.back
        end = self.ring.interpolate((self.at + (reach if ahead else -reach)) % self.ring.length)
        here = self.point
        length = math.hypot(end.x - here.x, end.y - here.y) or 1.0
        return ((end.x - here.x) / length, (end.y - here.y) / length), reach


def corners_of_land(land: BaseGeometry, net: Polygon,
                    edges: tuple[tuple[str, tuple[Run, ...]], ...]) -> list[Seat]:
    """The major corners: where the land's edge facing one major edge of the plot turns, by at
    least CORNER_TURN_DEG and outward (a corner, not a notch), into the edge facing the next.
    Each piece of the land's outline faces the plot's stretch nearest it; a stretch facing a
    minor one lies between the two edges and the corner is in its middle."""
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
    """The corners on either side of the gate along the land's edge: the one below it and the
    one above it."""
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


def _shape(seat: Seat, size: float, triangle: bool, ratio: float,
           gate: BaseGeometry) -> BaseGeometry:
    """The land a corner's pocket takes at one size: the patch its two sides make, `size` along
    each (no further than halfway to the next corner); a right-angled triangle, its small side
    along the side toward the gate and its long slant away; at a corner sharper than SHARP_DEG,
    everything within `size` of it, cut straight across."""
    (ax, ay), back = seat.side(False)
    (bx, by), ahead = seat.side(True)
    p = seat.point
    cx, cy = p.x, p.y
    angle = math.degrees(math.acos(max(-1.0, min(1.0, ax * bx + ay * by))))
    if angle < SHARP_DEG:
        mx, my = ax + bx, ay + by
        norm = math.hypot(mx, my) or 1.0
        mx, my = mx / norm, my / norm
        far = size + back + ahead
        cone = Polygon([(cx, cy), (cx + ax * far, cy + ay * far), (cx + bx * far, cy + by * far)])
        across = Polygon([(cx - my * far, cy + mx * far), (cx + my * far, cy - mx * far),
                          (cx + my * far + mx * size, cy - mx * far + my * size),
                          (cx - my * far + mx * size, cy + mx * far + my * size)])
        return _overlay(cone, across, MEET)
    if not triangle:
        a, b = min(size, back), min(size, ahead)
        return Polygon([(cx, cy), (cx + ax * a, cy + ay * a),
                        (cx + ax * a + bx * b, cy + ay * a + by * b), (cx + bx * b, cy + by * b)])
    toward_back = gate.is_empty or Point(cx + ax, cy + ay).distance(gate) <= Point(
        cx + bx, cy + by).distance(gate)
    (sx, sy), small_reach, (lx, ly), long_reach = (
        ((ax, ay), back, (bx, by), ahead) if toward_back else ((bx, by), ahead, (ax, ay), back))
    small, long = min(size / ratio, small_reach), min(size, long_reach)
    return Polygon([(cx, cy), (cx + sx * small, cy + sy * small), (cx + lx * long, cy + ly * long)])


def _pocket(seat: Seat, size: float, triangle: bool, ratio: float, gate: BaseGeometry,
            room: BaseGeometry, tiers: tuple[Tier, ...], out: BaseGeometry, keep) -> BaseGeometry:
    """A corner's pocket at one size: its shape on the room, less the setback each building
    left beside it keeps, less what is out (the land before the gate, what is taken)."""
    region = _overlay(_shape(seat, size, triangle, ratio, gate), room, MEET)
    if region.is_empty:
        return Polygon()
    kept = []
    for tier in tiers:  # only the buildings within a setback of the pocket can need one in it
        reach = tier.setback_m + CUT_TOLERANCE_M
        near = _overlay(tier.fits, region.buffer(reach, join_style="mitre"), MEET)
        if not near.is_empty:
            kept.append(_overlay(tier.band, _overlay(near, region, DIFF).buffer(
                reach, join_style="mitre"), MEET))
    region = _overlay(region, unary_union(kept), DIFF) if kept else region
    return keep(_overlay(region, out, DIFF))


def _sized(seat: Seat, area: float, triangle: bool, ratio: float, gate: BaseGeometry,
           room: BaseGeometry, tiers: tuple[Tier, ...], out: BaseGeometry, keep) -> BaseGeometry:
    """The smallest pocket at the corner that holds `area` (the largest it can be when none
    does)."""
    if area <= CUT_TOLERANCE_M:
        return Polygon()
    top = (seat.back + seat.ahead) * max(ratio, 1.0)
    biggest = _pocket(seat, top, triangle, ratio, gate, room, tiers, out, keep)
    if biggest.area <= area:
        return biggest
    low, high = 0.0, top
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if _pocket(seat, middle, triangle, ratio, gate, room, tiers, out, keep).area >= area:
            high = middle
        else:
            low = middle
    return _pocket(seat, high, triangle, ratio, gate, room, tiers, out, keep)


def _at_corners(idea: Idea, seats: list[Seat], gate: BaseGeometry, room: BaseGeometry,
                tiers: tuple[Tier, ...], out: BaseGeometry, need: float, plot: Polygon,
                keep) -> tuple[Corner, ...]:
    """`need` in pockets at the corners the idea picks, an equal share each; a corner that cannot
    hold its share passes the rest to the others, and when the picked corners together cannot
    hold it the cheapest of the rest join them."""
    if not seats:
        return ()
    near = {id(s) for s in beside_gate(seats, gate)}

    def triangle(seat: Seat) -> bool:
        return idea.triangles == EVERY or id(seat) in near

    def rate(seat: Seat) -> float:
        pocket = _sized(seat, need / len(seats), triangle(seat), idea.ratio, gate, room, tiers,
                        out, keep)
        return _cost(pocket, tiers) / max(pocket.area, CUT_TOLERANCE_M)

    ranked = sorted(seats, key=rate)
    if idea.pick == ALL:
        chosen = list(seats)
    elif idea.pick == FAR:
        far = sorted(seats, key=lambda s: -s.point.distance(gate)) if not gate.is_empty else seats
        chosen = far[:math.ceil(len(seats) / 2)]
    elif idea.pick == NEAR:
        chosen = [s for s in seats if id(s) in near] or ranked[:1]
    elif idea.pick == COUNT:
        chosen = ranked[:idea.count]
    elif idea.pick == SET:
        chosen = [seats[i] for i in idea.members if i < len(seats)]
    else:  # CHEAPEST: as many of the cheapest as cost the least in all (a tie keeps more)
        best = None
        for k in range(1, len(ranked) + 1):
            laid = _lay(ranked[:k], need, triangle, idea.ratio, gate, room, tiers, out, keep)
            if sum(g.area for _, _, g in laid) < need - CUT_TOLERANCE_M:
                continue
            cost = round(sum(_cost(g, tiers) for _, _, g in laid))
            if best is None or cost <= best[0]:
                best = (cost, ranked[:k])
        chosen = list(best[1]) if best else list(ranked)
    laid = _lay(chosen, need, triangle, idea.ratio, gate, room, tiers, out, keep)
    for extra in [s for s in ranked if s not in chosen]:  # the picked ones cannot hold it all
        if sum(g.area for _, _, g in laid) >= need - CUT_TOLERANCE_M:
            break
        chosen.append(extra)
        laid = _lay(chosen, need, triangle, idea.ratio, gate, room, tiers, out, keep)
    middle = (plot.centroid.x, plot.centroid.y)
    return tuple(Corner(number, compass(bearing(middle, (s.point.x, s.point.y))), s.point, give,
                        piece, triangle(s))
                 for number, (s, give, piece) in enumerate(laid, 1))


def _lay(chosen: list[Seat], need: float, triangle, ratio: float, gate: BaseGeometry,
         room: BaseGeometry, tiers: tuple[Tier, ...], out: BaseGeometry,
         keep) -> list[tuple[Seat, float, BaseGeometry]]:
    """An equal share at each chosen corner, the ones with the least room first so land two
    corners share goes to the one that needs it; a corner that cannot hold its share passes the
    rest to the others equally."""
    room_at = [_sized(s, need, triangle(s), ratio, gate, room, tiers, out, keep).area
               for s in chosen]
    order = sorted(range(len(chosen)), key=lambda i: room_at[i])
    gives = _water_fill(need, [room_at[i] for i in order])
    placed: dict[int, tuple[float, BaseGeometry]] = {}
    taken = [out]
    for i, give in zip(order, gives, strict=True):
        piece = _sized(chosen[i], give, triangle(chosen[i]), ratio, gate, room, tiers,
                       unary_union(taken), keep)
        placed[i] = (give, piece)
        taken.append(piece)
    return [(chosen[i], *placed[i]) for i in range(len(chosen))]


def _water_fill(need: float, room: list[float]) -> list[float]:
    """The need split equally; a corner with less room than its share keeps what it has room
    for and the rest is split equally over the others, until it is all given or no room is
    left."""
    given = [0.0] * len(room)
    left = need
    open_ = [i for i, r in enumerate(room) if r > CUT_TOLERANCE_M]
    while left > CUT_TOLERANCE_M and open_:
        each = left / len(open_)
        for i in list(open_):
            give = min(each, room[i] - given[i])
            given[i] += give
            left -= give
            if room[i] - given[i] <= CUT_TOLERANCE_M:
                open_.remove(i)
    return given


def _cost(geometry: BaseGeometry, tiers: tuple[Tier, ...]) -> float:
    """Floors a square metre summed: what the geometry takes from the building land."""
    return sum(_overlay(geometry, tier.tallest, MEET).area * tier.floors for tier in tiers)


def _stands_on(part: BaseGeometry, free: BaseGeometry, buffer: BaseGeometry | None,
               tiers: tuple[Tier, ...]) -> tuple[tuple[str, float], ...]:
    wet = _overlay(part, buffer, MEET).area if buffer is not None else 0.0
    building = [(f"Stilt + {tier.floors} land", _overlay(part, tier.tallest, MEET).area)
                for tier in tiers]
    out = [(WATER, wet), (FREE, _overlay(part, free, MEET).area - wet), *building]
    return tuple((kind, area) for kind, area in out if area > CUT_TOLERANCE_M)


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
