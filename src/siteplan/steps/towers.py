"""Step 5: the towers, the architect's brief (2026-10-12), for any site.

His brief: 2BHK flats of 1,150 sft and 3BHK flats of 1,300 sft; 40% of the project's flats 3BHK
and 60% 2BHK, counted over the whole project, never inside one tower; 4, 5 and 6 towers, each
running north to south, ten different layouts of each; the driveways and the setbacks drawn and
no tot-lot yet. The rest is the engine's to draw, inside the rules (his word: "imagination is
unlimited ... make sure it falls inside the rules").

1. The flats: each as wide along the corridor as its saleable area allows once the firm's common
   area loading is taken off, at the depth of the firm's own flats.
2. A tower's floor: flats on both sides of a corridor, the same flat opposite each, the firm's
   lift and stair core in each group of flats (as prototypes/compose.py lays the kit), one core for
   every group of up to the flats a core of the firm's serves on a side; every floor the same.
3. Where a tower may stand: the land step 4 leaves for the height step 2 allows (Table IV's
   setbacks), less the loop road (rule 8(m)'s 9 m, just inside rule 7(a)(viii)'s 2 m green strip,
   round the plot), the land a fire engine turns in at the gate (the front setback and NBC's 9 m)
   and every reading of a water body's buffer (rule 3(a)).
4. Towers stand in columns across the plot, two columns keeping the towers' setback between them
   (rules 7(a)(xii) and 8(j)); a column holds one tower or two, end to end with the same gap. Each
   tower's end lies on the loop road with a 9 m driveway along it, and a 6 m fire lane runs all
   round each tower (NBC Part 3 4.6(c)).
5. Which floor each tower gets, and how tall it stands (step 2's most, or up to MOST_LOWER floors
   lower where that holds the mix with more flats), is chosen over the whole project, so exactly
   40% of the flats are 3BHK and the most flats stand. A lower tower keeps the full height's
   setbacks and gaps, more than its own. A layout that cannot hold the mix exactly is not offered.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from fractions import Fraction
from itertools import combinations
from pathlib import Path

from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan import rules
from siteplan.intake import load_defaults
from siteplan.library import FlatLibrary
from siteplan.steps.inputs import Inputs
from siteplan.steps.setbacks import Setbacks, land_left_at
from siteplan.steps.survey_copy import SurveyCopy
from siteplan.steps.tot_lot import LOWEST_FLOORS, gate_of
from siteplan.units import SQM_PER_ACRE, SQM_PER_SQFT

TWO, THREE = "2BHK", "3BHK"
FLAT_SQFT = {TWO: 1150.0, THREE: 1300.0}  # saleable: the architect's brief (2026-10-12)
THREE_SHARE = 0.4  # of the whole project's flats, never inside one tower: his brief
TOWER_COUNTS = (4, 5, 6)  # his brief: ten layouts of each
VARIANTS = 10
LEAST_PER_SIDE = 2  # a tower has at least this many flats a side of its corridor
MOST_CORES = 3  # a tower has at most this many lift and stair cores
MOST_A_COLUMN = 2  # towers end to end in one column, north and south
MOST_LOWER = 3  # a tower may stand this many floors below step 2's most, to hold the mix exactly
GRID_M = 0.5  # where a column may stand is looked at every this many metres across the plot
OFFSETS = 24  # at most this many places a packed row of columns is tried
DIFFERENT = 0.25  # two layouts whose towers share more than 75% of their ground are copies
FIT_M = 0.01  # a tower this much too long for its room still fits (drawing noise)
SOUTH, NORTH = "south", "north"
WEST, MIDDLE, EAST, SPREAD, OPEN = "west", "middle", "east", "spread", "open"
NARSINGI_FLATS_PER_ACRE = 367 / 3.95  # the approved Narsingi scheme: the architect's check


@dataclass(frozen=True)
class Flat:
    bhk: str
    sqft: float  # saleable, the architect's
    width_m: float  # along the corridor


@dataclass(frozen=True)
class Kit:
    """What a tower is built from: the two flats, their depth, the corridor and the core."""

    two: Flat
    three: Flat
    depth_m: float  # one flat's, from the corridor to the outer wall
    corridor_m: float
    core_m: float  # a core's length along the tower; it spans the whole depth
    per_core: int  # the most flats a core serves on each side
    loading: float  # the common-area share taken off saleable to give a flat's own floor
    longest_m: float | None  # the firm's longest block, when it has one
    source: str

    @property
    def tower_depth_m(self) -> float:
        return 2 * self.depth_m + self.corridor_m


@dataclass(frozen=True)
class Floor:
    """A tower's typical floor: `per_side` flats on each side of the corridor, `threes` of them
    3BHK (the same flat opposite each), in `cores` groups with a core in each."""

    cores: int
    per_side: int
    threes: int
    length_m: float

    @property
    def flats(self) -> int:
        return 2 * self.per_side

    @property
    def three_flats(self) -> int:
        return 2 * self.threes

    @property
    def two_flats(self) -> int:
        return self.flats - self.three_flats

    def order(self) -> list[str]:
        """The flats along one side from the south end: the 3BHKs at the ends first (the corner
        flats, open on two sides), then the next in from each end."""
        out = [TWO] * self.per_side
        seen: list[int] = []
        for pair in zip(range(self.per_side), range(self.per_side - 1, -1, -1), strict=True):
            seen += [i for i in pair if i not in seen]
        for i in seen[:self.threes]:
            out[i] = THREE
        return out


def floors_of(kit: Kit) -> list[Floor]:
    """Every typical floor the kit makes, shortest first: up to the firm's flats a core on a
    side, the fewest cores that serves them; longer north to south than the tower is deep, so it
    runs north to south (his word: never across), and no longer than the firm's longest block."""
    out = []
    for per_side in range(LEAST_PER_SIDE, kit.per_core * MOST_CORES + 1):
        cores = math.ceil(per_side / kit.per_core)
        for threes in range(per_side + 1):
            length = (cores * kit.core_m + threes * kit.three.width_m
                      + (per_side - threes) * kit.two.width_m)
            if length <= kit.tower_depth_m + FIT_M:
                continue
            if kit.longest_m is None or length <= kit.longest_m + FIT_M:
                out.append(Floor(cores, per_side, threes, length))
    return sorted(out, key=lambda f: (f.length_m, f.cores, -f.flats))


@dataclass(frozen=True)
class Tower:
    number: int
    x_m: float  # its west side
    y_m: float  # its south end
    floor: Floor
    floors: int
    depth_m: float
    column: int
    end: str  # SOUTH or NORTH: the end that lies on the road

    @property
    def polygon(self) -> Polygon:
        return box(self.x_m, self.y_m, self.x_m + self.depth_m, self.y_m + self.floor.length_m)

    @property
    def flats(self) -> int:
        return self.floor.flats * self.floors

    @property
    def three_flats(self) -> int:
        return self.floor.three_flats * self.floors

    @property
    def two_flats(self) -> int:
        return self.floor.two_flats * self.floors

    def parts(self, kit: Kit) -> list[tuple[str, Polygon]]:
        """The typical floor drawn: each flat (both sides of the corridor) and each core."""
        out: list[tuple[str, Polygon]] = []
        x0, x1 = self.x_m, self.x_m + self.depth_m
        west, east = x0 + kit.depth_m, x1 - kit.depth_m
        y = self.y_m
        for kind, length in _row(self.floor, kit):
            if kind == "core":
                out.append(("core", box(x0, y, x1, y + length)))
            else:
                out += [(kind, box(x0, y, west, y + length)), (kind, box(east, y, x1, y + length))]
            y += length
        return out


def _row(floor: Floor, kit: Kit) -> list[tuple[str, float]]:
    """Along the tower from the south: the flats in groups, one per core, each core after the
    first half of its group (compose.py's order)."""
    flats = floor.order()
    size, extra = divmod(len(flats), floor.cores)
    out: list[tuple[str, float]] = []
    start = 0
    for g in range(floor.cores):
        group = flats[start:start + size + (1 if g < extra else 0)]
        start += len(group)
        before = math.ceil(len(group) / 2)
        for i, bhk in enumerate(group):
            if i == before:
                out.append(("core", kit.core_m))
            out.append((bhk, kit.three.width_m if bhk == THREE else kit.two.width_m))
        if before >= len(group):
            out.append(("core", kit.core_m))
    return out


@dataclass(frozen=True)
class Layout:
    """One layout the architect may choose: its towers, the driveways along their ends, the fire
    lanes round them, and the idea in words."""

    count: int
    number: int
    idea: str
    towers: tuple[Tower, ...]
    driveways: BaseGeometry  # along each tower's end, joining the loop road
    lanes: BaseGeometry  # the 6 m fire lane round each tower
    kind: tuple = ()  # the idea, for telling ideas apart: (top, columns, doubled, where, ends)
    top: int = 0  # the tallest tower's floors: every tower keeps this height's setbacks
    gap_m: float = 0.0  # between two towers: this height's setback

    @property
    def flats(self) -> int:
        return sum(t.flats for t in self.towers)

    @property
    def three_flats(self) -> int:
        return sum(t.three_flats for t in self.towers)

    @property
    def two_flats(self) -> int:
        return sum(t.two_flats for t in self.towers)

    @property
    def saleable_sqft(self) -> float:
        return self.three_flats * FLAT_SQFT[THREE] + self.two_flats * FLAT_SQFT[TWO]

    @property
    def cores(self) -> int:
        return sum(t.floor.cores for t in self.towers)

    @property
    def footprint(self) -> BaseGeometry:
        return unary_union([t.polygon for t in self.towers])


@dataclass
class Towers:
    inputs: Inputs
    copy: SurveyCopy
    setbacks: Setbacks
    stopped: str | None = None
    ask: str | None = None
    kit: Kit | None = None
    floors: int = 0  # the most step 2 allows
    lowest: int = LOWEST_FLOORS  # the lowest tower worth building
    lands: dict[int, BaseGeometry] = field(default_factory=dict)  # by height: the setbacks' land
    gaps: dict[int, float] = field(default_factory=dict)  # by height: its setback and gap
    rooms: dict[int, BaseGeometry] = field(default_factory=dict)  # by height: where towers fit
    loop: BaseGeometry = field(default_factory=Polygon)  # the 9 m loop road
    approach: BaseGeometry = field(default_factory=Polygon)  # from the gate to the loop
    green: BaseGeometry = field(default_factory=Polygon)  # the 2 m green strip
    gate: BaseGeometry = field(default_factory=Polygon)
    turn: BaseGeometry = field(default_factory=Polygon)  # a fire engine's turn at the gate
    water: BaseGeometry = field(default_factory=Polygon)  # every reading of every buffer
    waiting: tuple[str, ...] = ()  # water whose buffer waits on an answer (step 3)
    groups: dict[int, tuple[Layout, ...]] = field(default_factory=dict)  # by tower count
    tried: dict[int, int] = field(default_factory=dict)  # layouts that held the mix, by count
    most: int = 0  # the most towers that stand north to south here, holding the mix

    @property
    def layouts(self) -> tuple[Layout, ...]:
        return tuple(layout for count in sorted(self.groups) for layout in self.groups[count])

    @property
    def asked(self) -> tuple[int, ...]:
        """The tower counts the brief asks for that stand here."""
        return tuple(c for c in TOWER_COUNTS if self.groups.get(c))

    @property
    def acres(self) -> float:
        net = self.setbacks.widening.net
        return net.area / SQM_PER_ACRE if net is not None else 0.0


def checks(t: Towers, layout: Layout) -> dict[str, bool]:
    """Every rule a layout keeps, measured again on its drawing: what was searched for is not
    taken on trust."""
    towers = layout.towers
    share = Fraction(THREE_SHARE).limit_denominator(100)
    land = t.lands[layout.top]
    roads = unary_union([t.loop, t.approach, t.turn])
    net = t.setbacks.widening.net
    polys = [tw.polygon for tw in towers]

    def outside(p: Polygon, g: BaseGeometry) -> float:
        return p.difference(g).area

    def inside(p: Polygon, g: BaseGeometry) -> float:
        return p.intersection(g).area if not g.is_empty else 0.0

    def noise(p: Polygon) -> float:  # a strip FIT_M wide round the tower: drawing noise
        return FIT_M * p.length

    def on_road(tw: Tower) -> bool:
        y = tw.y_m if tw.end == SOUTH else tw.y_m + tw.floor.length_m
        face = LineString([(tw.x_m, y), (tw.x_m + tw.depth_m, y)])
        parts = [g for g in getattr(layout.driveways, "geoms", [layout.driveways])
                 if g.distance(face) <= FIT_M and g.intersects(roads)]
        along = face.intersection(unary_union(parts).buffer(FIT_M)).length if parts else 0.0
        return along >= tw.depth_m - FIT_M  # the driveway runs the whole end

    gaps = [a.distance(b) for i, a in enumerate(polys) for b in polys[i + 1:]]
    lane = rules.FIRE_TENDER_MIN_WIDTH_M
    return {
        "the towers asked": len(towers) == layout.count,
        "the mix exactly": share.denominator * layout.three_flats
        == share.numerator * layout.flats,
        "north to south": all(tw.floor.length_m > tw.depth_m for tw in towers),
        "inside the setbacks": all(outside(p, land) <= noise(p) for p in polys),
        "the gap between towers": all(g >= layout.gap_m - FIT_M for g in gaps),
        "off the roads and the green strip": all(
            inside(p, unary_union([roads, t.green])) <= noise(p) for p in polys),
        "out of the water's buffer": all(inside(p, t.water) <= noise(p) for p in polys),
        "each tower on a road": all(on_road(tw) for tw in towers),
        "a fire lane all round": all(
            g >= lane - FIT_M for g in gaps) and all(
            outside(p.buffer(lane, join_style="mitre"), net.difference(t.green))
            <= noise(p.buffer(lane, join_style="mitre")) for p in polys),
        "lowest worth building": all(tw.floors >= min(t.lowest, t.floors) for tw in towers),
    }


class NoKit(Exception):
    """The workspace names a flat library that cannot be read."""


def kit_of(workspace: Path | None) -> Kit | None:
    """The tower kit: the architect's two flats, sized on the firm's library (its flat depth,
    corridor, core and flats a core serves) and its common-area loading; None when the workspace
    names no library."""
    if workspace is None:
        return None
    defaults = load_defaults(workspace)
    if not defaults.flat_library:
        return None
    try:
        library = FlatLibrary.model_validate_json(
            (workspace / defaults.flat_library).read_text())
    except (OSError, ValueError) as problem:
        first = str(problem).splitlines()[0]
        raise NoKit(f"{defaults.flat_library} cannot be used: {first}") from problem
    depth = library.flats[0].depth_m
    loading = defaults.common_area_pct / 100

    def flat(bhk: str) -> Flat:
        own_sqm = FLAT_SQFT[bhk] / (1 + loading) * SQM_PER_SQFT
        return Flat(bhk, FLAT_SQFT[bhk], own_sqm / depth)

    return Kit(flat(TWO), flat(THREE), depth, library.corridor_width_m, library.core_width_m,
               library.flats_per_core_per_side, loading, defaults.max_tower_length_m,
               f"{defaults.flat_library}, the firm's flat library in the workspace "
               f"({defaults.standard_status('flat_library')}); the common-area loading "
               f"{defaults.common_area_pct:g}% ({defaults.standard_status('common_area_pct')})")


def place(inputs: Inputs, copy: SurveyCopy, setbacks: Setbacks) -> Towers:
    """Ten layouts of each tower count, the most flats first, each holding the mix exactly; when
    none of the counts asked stands, the most towers that do."""
    t = Towers(inputs, copy, setbacks)
    if setbacks.stopped:
        return _stop(t, "step 4 has no land left for buildings yet, and the towers stand on it",
                     setbacks.ask)
    ask = ("Which flat library does the firm build with? Name it as flat_library in the "
           "workspace's siteplan.workspace.json.")
    try:
        t.kit = kit_of(inputs.workspace)
    except NoKit as problem:
        return _stop(t, f"the firm's flat library cannot be used ({problem})", ask)
    if t.kit is None:
        return _stop(t, "the firm's flats are not known, and a tower's depth, corridor and "
                        "cores come from them", ask)
    net = setbacks.widening.net
    t.floors = setbacks.floors
    green_m = rules.PERIPHERAL_GREEN_STRIP_M if setbacks.high_rise else 0.0
    inside_green = net.buffer(-green_m, join_style="mitre") if green_m else net
    beyond_loop = net.buffer(-(green_m + rules.INTERNAL_ROAD_M), join_style="mitre")
    t.green = net.difference(inside_green)
    t.loop = inside_green.difference(beyond_loop)
    t.gate = gate_of(setbacks)
    t.turn = (t.gate.buffer(setbacks.front_m + rules.FIRE_TURNING_RADIUS_M).intersection(net)
              if not t.gate.is_empty else Polygon())
    t.approach = (t.gate.buffer(green_m + rules.INTERNAL_ROAD_M, cap_style="flat")
                  .intersection(net) if not t.gate.is_empty else Polygon())
    water = setbacks.widening.water
    t.waiting = tuple(w.kind for w in water if w.buffer_m is None)
    t.water = unary_union([g for w in water if w.buffer_m is not None
                           for g in (w.kept_free, w.edge_kept_free)]) if water else Polygon()
    roads = unary_union([t.loop, t.approach, t.turn])
    floors = floors_of(t.kit)
    searches = []
    for top in range(t.floors, min(t.floors, t.lowest) - 1, -1):  # every lower height too
        t.lands[top], t.gaps[top] = land_left_at(setbacks, top)
        t.rooms[top] = t.lands[top].intersection(beyond_loop).difference(
            unary_union([t.turn, t.water]))
        heights = range(top, max(t.lowest, top - MOST_LOWER) - 1, -1)
        searches.append(_Search(t.rooms[top], t.kit.tower_depth_m, t.gaps[top], floors, heights,
                                inside_green, t.water, roads))

    def every(count: int) -> list[Layout]:
        return [layout for search in searches for layout in search.layouts(count)]

    for count in TOWER_COUNTS:
        found = every(count)
        t.tried[count] = len(found)
        t.groups[count] = _pick(found, count)
    t.most = max(t.asked, default=0)
    if not t.most:  # say what does stand
        for count in range(min(TOWER_COUNTS) - 1, 0, -1):
            found = every(count)
            if found:
                t.most, t.tried[count] = count, len(found)
                t.groups[count] = _pick(found, count)
                break
    return t


def _stop(t: Towers, why: str, ask: str | None) -> Towers:
    t.stopped, t.ask = why, ask
    return t


Score = tuple[int, int, int]  # (flats, -cores, -floors given up): the bigger the better
Option = tuple[Floor, int]  # a typical floor and how many floors the tower stands


class _Search:
    """Columns of towers across the room, and which floor each tower gets and how tall it
    stands, so the whole project holds the mix exactly."""

    def __init__(self, room: BaseGeometry, depth: float, gap: float, floors: list[Floor],
                 heights: range, inside_green: BaseGeometry, water: BaseGeometry,
                 roads: BaseGeometry):
        self.room, self.depth, self.gap, self.top = room, depth, gap, max(heights)
        self.inside_green, self.water, self.roads = inside_green, water, roads
        share = Fraction(THREE_SHARE).limit_denominator(100)
        self.num, self.den = share.numerator, share.denominator
        tallest = self.top
        self.options: list[Option] = [(f, n) for f in floors for n in heights]
        self.options.sort(key=lambda o: o[0].length_m)
        self.lengths = [f.length_m for f, _ in self.options]
        self._best: list[dict[int, tuple[Score, Option]]] = []
        best: dict[int, tuple[Score, Option]] = {}
        for option in self.options:  # the best for each balance among those no longer
            f, n = option
            key = self.balance(option)
            score = (f.flats * n, -f.cores, n - tallest)
            if key not in best or score > best[key][0]:
                best = {**best, key: (score, option)}
            self._best.append(best)
        self._stretches: dict[float, list[tuple[float, float]]] = {}
        self._pairs: dict[tuple[float, ...], dict] = {}
        self._mixes: dict[tuple, list | None] = {}

    def balance(self, option: Option) -> int:
        """How far a tower moves the project off the share; zero over the whole project is
        exactly the share."""
        f, n = option
        return (self.den * f.three_flats - self.num * f.flats) * n

    def fit(self, length: float) -> dict[int, tuple[Score, Option]]:
        """The best tower for each balance, no longer than `length`."""
        i = bisect.bisect_right(self.lengths, length + FIT_M)
        return self._best[i - 1] if i else {}

    def stretches(self, x: float) -> list[tuple[float, float]]:
        """The south-to-north runs where a tower as deep as ours, its west side at x, stands
        wholly on the room."""
        key = round(x, 2)
        if key not in self._stretches:
            self._stretches[key] = _runs(self.room, key, self.depth)
        return self._stretches[key]

    def span(self) -> tuple[float, float] | None:
        """The westmost and eastmost places a column may stand, holding the shortest tower."""
        if self.room.is_empty or not self.options:
            return None
        x0, _, x1, _ = self.room.bounds
        shortest = self.lengths[0]
        found = [x for x in _steps(x0, x1 - self.depth)
                 if any(b - a >= shortest - FIT_M for a, b in self.stretches(x))]
        return (found[0], found[-1]) if found else None

    def layouts(self, count: int) -> Iterator[Layout]:
        span = self.span()
        if span is None:
            return
        for columns in range(math.ceil(count / MOST_A_COLUMN), count + 1):
            for xs, where, words in self._places(span, columns):
                for doubled in combinations(range(columns), count - columns):
                    for end in (SOUTH, NORTH):
                        layout = self._lay(count, xs, doubled, end, where, words)
                        if layout is not None:
                            yield layout

    def _places(self, span: tuple[float, float],
                columns: int) -> Iterator[tuple[tuple[float, ...], str, str]]:
        """Where the columns stand: packed side by side from each place along the plot, spread
        evenly across it, or packed against both sides with the room left between two."""
        west, east = span
        pitch = self.depth + self.gap
        slack = east - west - (columns - 1) * pitch
        if slack < -FIT_M:
            return
        slack = max(slack, 0.0)
        tries = min(OFFSETS, int(slack / GRID_M) + 1)
        for k in range(tries):
            offset = slack * k / max(tries - 1, 1)
            share = offset / slack if slack else 0.0
            where = WEST if share < 1 / 3 else EAST if share > 2 / 3 else MIDDLE
            words = ("packed against the west" if k == 0 else
                     "packed against the east" if k == tries - 1 else
                     f"packed side by side {offset:.0f} m in from the west")
            yield tuple(west + offset + i * pitch for i in range(columns)), where, words
        if columns > 1 and slack > GRID_M:
            even = pitch + slack / (columns - 1)
            yield (tuple(west + i * even for i in range(columns)), SPREAD,
                   "spread evenly across the plot")
        for j in range(1, columns if columns > 2 and slack > GRID_M else 0):
            xs = tuple(west + i * pitch + (slack if i >= j else 0.0) for i in range(columns))
            yield xs, f"{OPEN} {j}", f"open ground between columns {j} and {j + 1}"

    def _lay(self, count: int, xs: tuple[float, ...], doubled: tuple[int, ...], end: str,
             where: str, words: str) -> Layout | None:
        picks = self._mix(xs, doubled)
        if picks is None:
            return None
        towers: list[Tower] = []
        for c, (x, pick) in enumerate(zip(xs, picks, strict=True)):
            for y, (floor, storeys), side in pick:
                towers.append(Tower(len(towers) + 1, x, y, floor, storeys, self.depth, c + 1,
                                    side))
        placed = self._ends(towers, end)
        if placed is None:
            return None
        ends = tuple(sorted({t.end for t in placed if t.column - 1 not in doubled}))
        return Layout(count, 0, _idea(xs, doubled, placed, words), tuple(placed),
                      unary_union([self._driveway(t, placed) for t in placed]), _lanes(placed),
                      (self.top, len(xs), doubled, where, ends), self.top, self.gap)

    def _mix(self, xs: tuple[float, ...], doubled: tuple[int, ...]) -> list | None:
        """Each column's towers, chosen together so the project's flats hold the share exactly
        with the most flats (and, between equals, the fewest cores and floors given up); None
        when no choice holds it. A balance the columns still to come cannot bring back to the
        share is dropped as soon as it is reached."""
        key = (tuple(round(x, 2) for x in xs), doubled)
        if key in self._mixes:
            return self._mixes[key]
        maps = [self._column(x, c in doubled) for c, x in enumerate(xs)]
        if not all(maps):
            self._mixes[key] = None
            return None
        low = [0] * (len(maps) + 1)
        high = [0] * (len(maps) + 1)
        for i in range(len(maps) - 1, -1, -1):
            low[i] = low[i + 1] + min(maps[i])
            high[i] = high[i + 1] + max(maps[i])
        total: dict[int, tuple[Score, list]] = {0: ((0, 0, 0), [])}
        for i, options in enumerate(maps):
            nxt: dict[int, tuple[Score, list]] = {}
            for have, (score, picks) in total.items():
                for more, (extra, pick) in options.items():
                    k = have + more
                    if not low[i + 1] <= -k <= high[i + 1]:
                        continue
                    both = (score[0] + extra[0], score[1] + extra[1], score[2] + extra[2])
                    if k not in nxt or both > nxt[k][0]:
                        nxt[k] = (both, [*picks, pick])
            total = nxt
        found = total[0][1] if 0 in total else None
        self._mixes[key] = found
        return found

    def _column(self, x: float, two: bool) -> dict[int, tuple[Score, list]]:
        """For one column: the best towers for each balance, with where each stands (its south
        end, its floor and height, the end that lies on the road)."""
        runs = self.stretches(x)
        out: dict[int, tuple[Score, list]] = {}

        def keep(key: int, score: Score, pick: list) -> None:
            if key not in out or score > out[key][0]:
                out[key] = (score, pick)

        if not two:
            for a, b in runs:
                for key, (score, option) in self.fit(b - a).items():
                    keep(key, score, [(a, option, SOUTH)])  # which end of the run: _ends
            return out
        for i, (a1, b1) in enumerate(runs):
            for a2, b2 in runs[i:]:
                for key, (score, pick) in self._pair(a1, b1, a2, b2).items():
                    keep(key, score, pick)
        return out

    def _pair(self, a1: float, b1: float, a2: float, b2: float) -> dict:
        """Two towers end to end: the south one from the south end of the first run, the north
        one to the north end of the second, the towers' gap between them."""
        cache = (round(a1, 2), round(b1, 2), round(a2, 2), round(b2, 2))
        if cache in self._pairs:
            return self._pairs[cache]
        out: dict[int, tuple[Score, list]] = {}
        tallest = self.top
        for south in self.options:
            f, n = south
            if f.length_m > b1 - a1 + FIT_M:
                break
            room = min(b2 - a2, b2 - (a1 + f.length_m + self.gap))
            for key, (score, north) in self.fit(room).items():
                k = key + self.balance(south)
                both = (score[0] + f.flats * n, score[1] - f.cores, score[2] + n - tallest)
                if k not in out or both > out[k][0]:
                    out[k] = (both, [(a1, south, SOUTH),
                                     (b2 - north[0].length_m, north, NORTH)])
        self._pairs[cache] = out
        return out

    def _ends(self, towers: list[Tower], end: str) -> list[Tower] | None:
        """A tower alone in its column stands with `end` on the road, or its other end when only
        that one reaches a road; a pair keeps its outer ends. None when a tower reaches no
        road."""
        out = []
        for tower in towers:
            alone = sum(1 for t in towers if t.column == tower.column) == 1
            sides = (end, NORTH if end == SOUTH else SOUTH) if alone else (tower.end,)
            run = next((r for r in self.stretches(tower.x_m)
                        if r[0] - FIT_M <= tower.y_m <= r[1] + FIT_M), None)
            placed = None
            for side in sides:
                y = tower.y_m if not alone or run is None else (
                    run[0] if side == SOUTH else run[1] - tower.floor.length_m)
                trial = Tower(tower.number, tower.x_m, y, tower.floor, tower.floors,
                              tower.depth_m, tower.column, side)
                if self._driveway(trial, towers).intersects(self.roads):
                    placed = trial
                    break
            if placed is None:
                return None
            out.append(placed)
        return out

    def _driveway(self, tower: Tower, towers: list[Tower]) -> BaseGeometry:
        """A 9 m driveway along the tower's road end, out to the loop road: inside the green
        strip, out of the water's buffer and off every tower."""
        x0, x1 = tower.x_m, tower.x_m + tower.depth_m
        y = tower.y_m if tower.end == SOUTH else tower.y_m + tower.floor.length_m
        reach = rules.INTERNAL_ROAD_M
        strip = box(x0, y - reach, x1, y) if tower.end == SOUTH else box(x0, y, x1, y + reach)
        others = unary_union([t.polygon for t in towers])
        return strip.intersection(self.inside_green).difference(
            unary_union([self.water, others]))


def _idea(xs: tuple[float, ...], doubled: tuple[int, ...], towers: list[Tower],
          words: str) -> str:
    columns = len(xs)
    doubles = [c + 1 for c in doubled]
    ends = sorted({t.end for t in towers if t.column not in doubles})
    out = f"{columns} column{'s' if columns > 1 else ''} of north-south towers, {words}"
    if doubles:
        out += (f"; two towers end to end in column{'s' if len(doubles) > 1 else ''} "
                f"{', '.join(map(str, doubles))}")
    if len(ends) == 1:
        out += f"; the towers alone in a column on the {ends[0]} road"
    elif ends:
        out += "; the towers alone in a column on the north or south road"
    return out


def _lanes(towers: list[Tower]) -> BaseGeometry:
    """NBC Part 3 4.6(c)'s 6 m of motorable open space all round each tower."""
    footprint = unary_union([t.polygon for t in towers])
    return unary_union([t.polygon.buffer(rules.FIRE_TENDER_MIN_WIDTH_M, join_style="mitre")
                        for t in towers]).difference(footprint)


def _pick(found: list[Layout], count: int) -> tuple[Layout, ...]:
    """Ten different ideas, the most flats first: the best layout of each idea (how many
    columns, which hold two towers, where the columns stand, which road the lone towers' ends
    lie on) before a second of any; and none sharing more than 1 - DIFFERENT of its towers'
    ground with one kept before it."""
    def better(o: Layout) -> tuple:
        return -o.flats, o.cores, -min(t.floors for t in o.towers), o.idea

    ranked = sorted(found, key=better)
    firsts: dict[tuple, Layout] = {}
    for layout in ranked:
        firsts.setdefault(layout.kind, layout)
    kept: list[Layout] = []
    for pool in (list(firsts.values()), ranked):
        for layout in pool:
            if len(kept) == VARIANTS:
                break
            here = layout.footprint
            if all(_overlap(here, k.footprint) < 1 - DIFFERENT for k in kept):
                kept.append(layout)
    return tuple(replace(k, number=n) for n, k in enumerate(sorted(kept, key=better), 1))


def _overlap(a: BaseGeometry, b: BaseGeometry) -> float:
    """The share of the two footprints' ground they have in common."""
    union = a.union(b).area
    return a.intersection(b).area / union if union else 1.0


def _steps(start: float, stop: float) -> list[float]:
    count = int((stop - start) / GRID_M + FIT_M)
    return [start + i * GRID_M for i in range(count + 1)] if stop >= start else []


def _runs(land: BaseGeometry, x: float, depth: float) -> list[tuple[float, float]]:
    """The south-to-north ranges where a band `depth` wide from `x` lies wholly on the land."""
    if land.is_empty:
        return []
    _, y0, _, y1 = land.bounds
    band = box(x, y0 - 1, x + depth, y1 + 1)
    blocked = band.difference(land)
    spans = sorted((g.bounds[1], g.bounds[3]) for g in getattr(blocked, "geoms", [blocked])
                   if not g.is_empty and g.area > FIT_M * FIT_M)
    out, cursor = [], y0 - 1
    for low, high in spans:
        if low > cursor + FIT_M:
            out.append((cursor, low))
        cursor = max(cursor, high)
    if cursor < y1 + 1 - FIT_M:
        out.append((cursor, y1 + 1))
    return [(a, b) for a, b in out if b - a > FIT_M]
