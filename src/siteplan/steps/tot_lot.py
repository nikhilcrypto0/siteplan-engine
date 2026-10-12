"""Step 5: the tot-lot, the architect's way (2026-10-11), for any site, from step 4's land left.

1. Where a building can stand: the land step 4 leaves after the setbacks, where one of the
   firm's blocks fits (the double-loaded kit and a slim one, one row of flats beside the
   corridor, turned either way). Where none fits, no building stands.
2. The gate, where the main road meets the plot, and the land before it, kept clear.
3. The tot-lot: 10% of the whole plot for a high-rise site or a Group Development Scheme (rules
   7(a)(vii), 8(g)), 5% for any other plot above 750 m² (5(f)(vi)), in pockets at least 3 m
   wide, never outside the land left (the architect, 2026-10-11: no setback, green strip or
   fire lane). First the land left where no building stands, the part farthest from the
   buildings first. What is still needed is split equally over the major corners of the land
   left, a strip along both sides of each, never over the gate; a corner that cannot hold its
   part passes the rest to the others. A water body's buffer may count
   (3(a)(iii)(3)); the gaps between blocks never do (7(a)(xii)).
The club house comes once the tot-lot is right (the architect, same day)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from shapely import set_precision
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import substring, unary_union

from siteplan import rules
from siteplan.geometry import Run, facing_deg, straight_runs
from siteplan.intake import load_defaults
from siteplan.library import FlatLibrary
from siteplan.prototypes.compose import compose_library
from siteplan.steps.gate import on_net
from siteplan.steps.inputs import Inputs, bearing, compass
from siteplan.steps.setbacks import Setbacks
from siteplan.steps.survey_copy import SHORT_RUN_M, SurveyCopy

CUT_TOLERANCE_M = 0.01  # how finely a strip's length or depth is placed; pieces this close are
# one pocket; a width this short of the least still counts (a 3.000 m strip is 3 m wide)
GRID_M = 0.001  # two outlines GEOS cannot overlay are snapped to this grid and tried again
TOT_LOT_DEPTH_M = 6.0  # how far the tot-lot strip reaches into the building land, until the firm
# sets its own: long along the side, not much into the usable space (the architect, 2026-10-11)
CORNER_TURN_DEG = 30.0  # the edge of the building land turns at least this much at a corner
IDLE, WATER, BUILDING = ("land where no building stands", "the water's buffer",
                         "land a block fits on")
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
class Pocket:
    polygon: BaseGeometry  # one piece, or pieces that touch
    lies: str  # where: 'where no building stands', 'at the north corner'
    on_sqm: tuple[tuple[str, float], ...]  # (IDLE, WATER or BUILDING, m²)

    @property
    def area_sqm(self) -> float:
        return self.polygon.area


@dataclass(frozen=True)
class Corner:
    """A major corner of the land left and the tot-lot it takes."""

    number: int
    lies: str  # 'south-west', from the plot's middle
    point: BaseGeometry
    share_sqm: float  # what it was given
    tot_lot: BaseGeometry


@dataclass(frozen=True)
class Placing:
    """Where buildings can stand and the tot-lot, on one reading of the water's buffer."""

    reading: str  # FROM_LINE, FROM_EDGE, or '' when there is no water
    fits: BaseGeometry  # the land left where one of the firm's blocks fits
    idle: BaseGeometry  # the land left where no building stands, in usable pockets
    tot_lot: BaseGeometry
    idle_taken: BaseGeometry  # the tot-lot laid where no building stands
    pockets: tuple[Pocket, ...]
    need_sqm: float
    depth_m: float  # how deep a corner's strip runs into the land left
    gate: BaseGeometry  # where the approach road comes in from the main road
    gate_zone: BaseGeometry  # kept clear before it: no tot-lot
    corners: tuple[Corner, ...]  # the major corners that took the rest, and what each took
    fits_after: BaseGeometry  # where a block still fits once the tot-lot is out

    @property
    def short_sqm(self) -> float:
        return max(0.0, self.need_sqm - self.tot_lot.area)

    def on(self, kind: str) -> float:
        return sum(area for pocket in self.pockets for k, area in pocket.on_sqm if k == kind)


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
    depth_m: float = TOT_LOT_DEPTH_M
    depth_from: str = ""
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
        return _stop(t, "the firm's blocks are not known, and where no building can stand "
                        "is found with them", ask)
    _firm_figures(t)
    water = [w for w in setbacks.widening.water if w.buffer_m is not None]
    t.waiting = tuple(w.kind for w in setbacks.widening.water if w.buffer_m is None)
    readings = [("", None)] if not water else [
        (FROM_LINE, unary_union([w.kept_free for w in water])),
        (FROM_EDGE, unary_union([w.edge_kept_free for w in water]))]
    net = setbacks.widening.net
    gate = gate_of(setbacks)
    zone = (_overlay(gate.buffer(setbacks.front_m + rules.FIRE_TURNING_RADIUS_M), net, MEET)
            if not gate.is_empty else Polygon())
    for reading, buffer in readings:
        left = setbacks.left if buffer is None else _overlay(setbacks.left, buffer, DIFF)
        fits = block_land_in(left, t.blocks)
        t.placings += (place(fits, setbacks.left, buffer, t.need_sqm, t.share, net, gate, zone,
                             t.depth_m, t.blocks, reading),)
    return t


def _stop(t: TotLot, why: str, ask: str | None) -> TotLot:
    t.stopped, t.ask = why, ask
    return t


def _firm_figures(t: TotLot) -> None:
    """The architect's working figures, from the workspace when the firm sets them."""
    defaults = load_defaults(t.inputs.workspace) if t.inputs.workspace else None
    set_depth = defaults is not None and defaults.tot_lot_depth_m is not None
    t.depth_m = defaults.tot_lot_depth_m if set_depth else TOT_LOT_DEPTH_M
    t.depth_from = ("the firm's workspace" if set_depth else
                    "the engine's default for the architect's 'long along the side, not much "
                    "into the usable space', until the firm sets tot_lot_depth_m")


def gate_of(s: Setbacks) -> BaseGeometry:
    """Where the approach road comes in on the net plot: the main road's stretch of its edge, or
    the land given up to widen the main road (steps/gate.py)."""
    return on_net(s.widening.net, s.height.road, s.widening.pieces)


def idle_land(land: BaseGeometry, fits: BaseGeometry, zone: BaseGeometry,
              share: Share) -> BaseGeometry:
    """Where no building stands: the land left where no block of the firm's fits, less the land
    before the gate, in pockets the tot-lot can use. Never outside the land left (the architect,
    2026-10-11)."""
    return pockets_in(_overlay(_overlay(land, fits, DIFF), zone, DIFF).buffer(0), share)


def place(fits: BaseGeometry, land: BaseGeometry, buffer: BaseGeometry | None, need_sqm: float,
          share: Share, plot: Polygon, gate: BaseGeometry, zone: BaseGeometry, depth_m: float,
          blocks: Blocks | None = None, reading: str = "") -> Placing:
    """The tot-lot, inside the land left (`land`): first where no building stands, the part
    farthest from the buildings first; then what is still needed split equally over the land
    left's major corners, never over the gate."""
    def keep(geometry: BaseGeometry) -> BaseGeometry:
        return pockets_in(geometry, share)

    idle = idle_land(land, fits, zone, share)
    first = _far_first(idle, fits if not fits.is_empty else plot.centroid, need_sqm, keep)
    rest = need_sqm - first.area
    corners: tuple[Corner, ...] = ()
    depth = depth_m
    if rest > CUT_TOLERANCE_M:
        shortest = blocks.shortest_m if blocks is not None else 0.0
        seats = [seat for seat in corners_of_land(land, plot, major_edges(plot, shortest))
                 if first.is_empty or seat.point.distance(first) > depth_m]
        corners, depth = _at_corners(seats, land, zone, first, rest, depth_m, plot, keep)
    tot_lot = unary_union([first, *(c.tot_lot for c in corners)])
    pockets = ((Pocket(first, "where no building stands", _stands_on(first, fits, idle, buffer)),)
               if not first.is_empty else ())
    pockets += tuple(Pocket(c.tot_lot, f"at the {c.lies} corner",
                            _stands_on(c.tot_lot, fits, idle, buffer))
                     for c in corners if not c.tot_lot.is_empty)
    after = _overlay(fits, tot_lot, DIFF)
    fits_after = block_land_in(after, blocks) if blocks is not None else after
    return Placing(reading, fits, idle, tot_lot, first, pockets, need_sqm, depth, gate, zone,
                   corners, fits_after)


def _far_first(idle: BaseGeometry, buildings: BaseGeometry, need: float,
               keep) -> BaseGeometry:
    """`need` of the land where no building stands, the part farthest from the buildings first
    (all of it when it holds less)."""
    if idle.is_empty or need <= CUT_TOLERANCE_M:
        return Polygon()
    if idle.area <= need:
        return idle
    low, high = 0.0, idle.hausdorff_distance(buildings)
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if keep(_overlay(idle, buildings.buffer(middle), DIFF)).area >= need:
            low = middle
        else:
            high = middle
    return keep(_overlay(idle, buildings.buffer(low), DIFF))


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
    """Where a corner's strip runs: along the land left's edge (`ring`, anticlockwise), from the
    corner at `at` each way, as far as halfway to the next corner (`back`, `ahead`)."""

    ring: LineString
    at: float
    back: float
    ahead: float

    @property
    def point(self) -> BaseGeometry:
        return self.ring.interpolate(self.at)


def corners_of_land(land: BaseGeometry, net: Polygon,
                    edges: tuple[tuple[str, tuple[Run, ...]], ...]) -> list[Seat]:
    """The major corners: where the land left's edge facing one major edge of the plot turns,
    by at least CORNER_TURN_DEG and outward (a corner, not a notch), into the edge facing the
    next. Each piece of the land's outline faces the plot's stretch nearest it; a stretch facing
    a minor one lies between the two edges and the corner is in its middle."""
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


def _at_corners(seats: list[Seat], land: BaseGeometry, zone: BaseGeometry,
                taken: BaseGeometry, need: float, depth_m: float, plot: Polygon,
                keep) -> tuple[tuple[Corner, ...], float]:
    """`need` split equally over the corners, a strip along both sides of each; a corner that
    cannot hold its part passes the rest to the others equally, and the strips are made deeper
    only when the corners together cannot hold it."""
    if not seats:
        return (), depth_m
    # the corners with the least room first, so shared land goes to the one that needs it
    alone = [_strip(seat, land, zone, taken, math.inf, depth_m, keep).area for seat in seats]
    order = sorted(range(len(seats)), key=lambda i: alone[i])
    queue = [seats[i] for i in order]
    depth = _depth_for(queue, land, zone, taken, need, depth_m, keep)
    room = _water_fill(need, [g.area for g in _sequence(queue, land, zone, taken, depth, keep)])
    shares, placed = [0.0] * len(seats), [Polygon()] * len(seats)
    done: list[BaseGeometry] = [taken] if not taken.is_empty else []
    for i, give in zip(order, room, strict=True):
        shares[i] = give
        placed[i] = _piece(seats[i], land, zone, unary_union(done) if done else Polygon(),
                           give, depth, keep)
        done.append(placed[i])
    middle = (plot.centroid.x, plot.centroid.y)
    return tuple(Corner(number, compass(bearing(middle, (seat.point.x, seat.point.y))),
                        seat.point, give, piece)
                 for number, (seat, give, piece) in enumerate(zip(seats, shares, placed,
                                                                  strict=True), 1)), depth


def _span(ring: LineString, start: float, end: float) -> list[LineString]:
    """The stretch of a closed edge from `start` to `end` (either may lie past its ends)."""
    total = ring.length
    if end - start >= total:
        return [ring]
    shift = math.floor(start / total) * total
    start, end = start - shift, end - shift
    spans = [(start, end)] if end <= total else [(start, total), (0.0, end - total)]
    return [substring(ring, a, b) for a, b in spans if b > a]


def _strip(seat: Seat, land: BaseGeometry, zone: BaseGeometry, taken: BaseGeometry,
           half: float, depth: float, keep) -> BaseGeometry:
    """A strip `depth` deep along both sides of the corner, `half` each way (no further than
    halfway to the next corner), on the land, clear of the gate and of what is taken."""
    if half <= 0:
        return Polygon()
    pieces = _span(seat.ring, seat.at - min(half, seat.back), seat.at + min(half, seat.ahead))
    band = unary_union([p.buffer(depth, cap_style="flat", join_style="mitre") for p in pieces])
    return keep(_overlay(_overlay(_overlay(band, land, MEET), zone, DIFF), taken, DIFF))


def _sequence(seats: list[Seat], land: BaseGeometry, zone: BaseGeometry, taken: BaseGeometry,
              depth: float, keep) -> list[BaseGeometry]:
    """Each corner's whole strip at this depth, less the ones before it (shared land once)."""
    out: list[BaseGeometry] = []
    for seat in seats:
        before = unary_union([taken, *out]) if out else taken
        out.append(_strip(seat, land, zone, before, math.inf, depth, keep))
    return out


def _depth_for(seats: list[Seat], land: BaseGeometry, zone: BaseGeometry, taken: BaseGeometry,
               need: float, depth_m: float, keep) -> float:
    """`depth_m`, or deeper when every corner's whole strip together holds less than the need:
    as deep as it takes, or as deep as the land allows."""
    def holds(depth: float) -> float:
        return sum(g.area for g in _sequence(seats, land, zone, taken, depth, keep))

    if holds(depth_m) >= need:
        return depth_m
    x0, y0, x1, y1 = land.bounds  # no strip is deeper than the land is across
    low, high = depth_m, max(depth_m, x1 - x0, y1 - y0)
    if holds(high) < need:
        return high
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        low, high = (low, middle) if holds(middle) >= need else (middle, high)
    return high


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


def _piece(seat: Seat, land: BaseGeometry, zone: BaseGeometry, taken: BaseGeometry,
           area: float, depth: float, keep) -> BaseGeometry:
    """The shortest strip round the corner that holds `area`."""
    if area <= CUT_TOLERANCE_M:
        return Polygon()
    whole = max(seat.back, seat.ahead)
    if _strip(seat, land, zone, taken, whole, depth, keep).area <= area:
        return _strip(seat, land, zone, taken, whole, depth, keep)
    low, high = 0.0, whole
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if _strip(seat, land, zone, taken, middle, depth, keep).area >= area:
            high = middle
        else:
            low = middle
    return _strip(seat, land, zone, taken, high, depth, keep)


def _stands_on(part: BaseGeometry, fits: BaseGeometry, idle: BaseGeometry,
               buffer: BaseGeometry | None) -> tuple[tuple[str, float], ...]:
    wet = _overlay(part, buffer, MEET).area if buffer is not None else 0.0
    out = [(WATER, wet), (IDLE, _overlay(part, idle, MEET).area - wet),
           (BUILDING, _overlay(part, fits, MEET).area)]
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
