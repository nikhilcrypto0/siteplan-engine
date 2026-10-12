"""Step 5's buildings, the architect's way (2026-10-12): the firm's blocks in straight rows,
each part of the plot along its own longest straight edge (a bent plot's arms each take their
own), the tallest first and lower ones (down to the lowest worth building) into the narrow parts.
Each layout is built round one road idea: a loop round the blocks, or a spine from the gate with
rows facing it. The tot-lot comes after, in what the blocks leave (tot_lot.py).

The rules are the seven files': each height keeps its own setbacks from the plot's edge (step 4's
rules, `setbacks.land_left_at`); two blocks keep the taller one's setback between them (G.O.168
7(a)(xii) for a high-rise, 5(f)(xiii) below); the internal roads are 8(m)'s 9 m; nothing stands in
the gate's way in."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import split, unary_union

from siteplan import rules
from siteplan.geometry import facing_deg, straight_runs
from siteplan.steps.inputs import compass

SWEEP_STEP_M = 1.0  # a row that does not fit is tried again this much further on
NECK_SHARE = 0.5  # a cut no longer than this share of the smaller piece's length parts an arm
APART_DEG = 20.0  # two edges closer than this in direction give the same rows
REFLEX_DEG = 190.0  # the land turns in by more than this at a corner a cut may start from
NECK_SMOOTH_M = 1.0  # the outline is smoothed this much before its inward corners are found
FIT_M = 0.01  # a block this much too long for its stretch still fits (drawing noise)
LOOP, SPINE, SPINE_LOOP = "loop", "spine", "spine and loop"
LOW, HIGH = "low", "high"  # a row sweep starts from the low or the high side of the frame


@dataclass(frozen=True)
class Kind:
    """One of the firm's blocks: its name, length, depth and flats on each floor."""

    what: str
    length_m: float
    depth_m: float
    flats_per_floor: int


@dataclass(frozen=True)
class Block:
    polygon: Polygon
    kind: Kind
    floors: int
    angle_deg: float  # the row's direction
    arm: int

    @property
    def flats(self) -> int:
        return self.kind.flats_per_floor * self.floors


@dataclass(frozen=True)
class Plan:
    """One idea of where the blocks go: a road idea and each arm's row direction."""

    road: str  # LOOP or SPINE
    angles: tuple[float, ...]  # each arm's rows, in degrees
    words: str


@dataclass(frozen=True)
class Layout:
    plan: Plan
    blocks: tuple[Block, ...]
    roads: BaseGeometry  # the loop's band or the spine: no block, no tot-lot
    arms: tuple[Polygon, ...]

    @property
    def flats(self) -> int:
        return sum(b.flats for b in self.blocks)

    @property
    def footprint(self) -> BaseGeometry:
        return unary_union([b.polygon for b in self.blocks]) if self.blocks else Polygon()


def arms_of(land: BaseGeometry, smallest_sqm: float) -> list[Polygon]:
    """The land's arms: a bent piece is cut at its narrowest neck, a cut from an inward corner
    no longer than NECK_SHARE of the smaller piece's length, both pieces big enough for a block
    or two; largest first."""
    todo = [p for p in _parts(land)]
    out: list[Polygon] = []
    while todo:
        part = todo.pop()
        cut = _neck(part, smallest_sqm)
        if cut is None:
            out.append(part)
            continue
        todo.extend(_parts(split(part, cut)))
    return sorted(out, key=lambda p: -p.area)


def _neck(part: Polygon, smallest_sqm: float) -> LineString | None:
    # a rounded inside corner (step 4 rounds them) is one corner once the outline is smoothed
    coords = list(part.simplify(NECK_SMOOTH_M).exterior.coords)[:-1]
    if len(coords) < 4:
        return None
    ccw = part.exterior.is_ccw
    best = None
    x0, y0, x1, y1 = part.bounds
    far = 2 * math.hypot(x1 - x0, y1 - y0)
    for i, v in enumerate(coords):
        u, w = coords[i - 1], coords[(i + 1) % len(coords)]
        (ix, iy), (ox, oy) = (v[0] - u[0], v[1] - u[1]), (w[0] - v[0], w[1] - v[1])
        turn = math.degrees(math.atan2(ix * oy - iy * ox, ix * ox + iy * oy))
        inward = 180 - (turn if ccw else -turn)  # the inside angle at v
        if inward < REFLEX_DEG:
            continue
        for a, b in ((u, v), (w, v)):  # each side running on past the corner
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length == 0:
                continue
            ray = LineString([v, (v[0] + (b[0] - a[0]) / length * far,
                                  v[1] + (b[1] - a[1]) / length * far)])
            inside = ray.intersection(part)
            first = min((g for g in getattr(inside, "geoms", [inside])
                         if g.geom_type == "LineString" and g.length > FIT_M
                         and g.distance(Point(v)) < FIT_M),
                        key=lambda g: g.length, default=None)
            if first is None:
                continue
            pieces = _parts(split(part, first))
            if len(pieces) != 2 or min(p.area for p in pieces) < smallest_sqm:
                continue
            smaller = min(pieces, key=lambda p: p.area)
            length = smaller.length / 2  # half its outline: an elongated piece's length
            if first.length <= NECK_SHARE * length and (best is None
                                                        or first.length < best.length):
                best = first
    return best


def directions(arm: Polygon, net: Polygon, reach_m: float) -> list[tuple[float, str, float]]:
    """The plot's straight edges along an arm, longest first, each with the way its rows run (in
    degrees), the way the edge faces and how long it runs beside the arm; edges within APART_DEG
    of a longer one's direction are left out."""
    near = arm.buffer(reach_m)
    found = []
    for run in straight_runs(net):
        beside = run.line.intersection(near).length
        if beside <= FIT_M:
            continue
        (ax, ay), (bx, by) = run.line.coords[0], run.line.coords[-1]
        found.append((math.degrees(math.atan2(by - ay, bx - ax)) % 180,
                      compass(facing_deg(net, run)), beside))
    out: list[tuple[float, str, float]] = []
    for angle, faces, beside in sorted(found, key=lambda f: -f[2]):
        if all(_apart(angle, kept[0]) >= APART_DEG for kept in out):
            out.append((angle, faces, beside))
    return out


def _apart(a: float, b: float) -> float:
    d = abs(a - b) % 180
    return min(d, 180 - d)


def lay(plan: Plan, arms: tuple[Polygon, ...], lands: list[tuple[int, float, BaseGeometry]],
        kinds: list[Kind], reserved: BaseGeometry, spine: BaseGeometry | None,
        side: str) -> tuple[Block, ...]:
    """The blocks of one plan: for each height, tallest first (`lands`: floors, the setback that
    height keeps, the land it may stand on), rows in every arm along its direction, on the land
    the height allows less the roads and the room every block already placed keeps round it."""
    placed: list[Block] = []
    gaps = {floors: setback for floors, setback, _ in lands}
    for floors, setback, land in lands:
        for k, arm in enumerate(arms):
            kept = [b.polygon.buffer(gaps[max(b.floors, floors)], join_style="mitre")
                    for b in placed]
            free = arm.intersection(land).difference(unary_union([reserved, *kept]))
            if free.is_empty:
                continue
            angle = plan.angles[k]
            if spine is not None and plan.road != LOOP and arm.intersects(spine):
                halves = _halves(free, spine, angle)
                rows = [*_rows(halves[0], angle, setback, kinds, LOW),
                        *_rows(halves[1], angle, setback, kinds, HIGH)]
            else:
                rows = _rows(free, angle, setback, kinds, side)
            placed += [Block(poly, kind, floors, angle, k) for poly, kind in rows]
    return tuple(placed)


def _halves(free: BaseGeometry, spine: BaseGeometry, angle: float) -> tuple[BaseGeometry, ...]:
    """The land on either side of the spine's middle line, in the rows' frame."""
    middle = spine.centroid
    turned = affinity.rotate(free, -angle, origin=(middle.x, middle.y))
    x0, y0, x1, y1 = turned.bounds
    above = box(x0 - 1, middle.y, x1 + 1, y1 + 1)
    below = box(x0 - 1, y0 - 1, x1 + 1, middle.y)
    return tuple(affinity.rotate(turned.intersection(half), angle, origin=(middle.x, middle.y))
                 for half in (above, below))


def _rows(free: BaseGeometry, angle: float, gap: float, kinds: list[Kind],
          side: str) -> list[tuple[Polygon, Kind]]:
    """Rows of blocks on the free land, along `angle`, swept from one side: the deepest blocks
    first, the longest that fit each stretch, `gap` between blocks and between rows; then the
    shallower ones on what the deeper rows leave."""
    if free.is_empty:
        return []
    turned = affinity.rotate(free, -angle, origin=(0, 0))
    if side == HIGH:
        turned = affinity.scale(turned, 1, -1, origin=(0, 0))
    out: list[tuple[Polygon, Kind]] = []
    for depth in sorted({k.depth_m for k in kinds}, reverse=True):
        mine = sorted((k for k in kinds if k.depth_m == depth), key=lambda k: -k.length_m)
        room = turned.difference(unary_union([p.buffer(gap, join_style="mitre")
                                              for p, _ in out])) if out else turned
        if room.is_empty:
            continue
        _, miny, _, maxy = room.bounds
        y = miny
        while y + depth <= maxy + FIT_M:
            row = []
            for a, b in _stretches(room, y, depth):
                cursor = a
                while True:
                    kind = next((k for k in mine if cursor + k.length_m <= b + FIT_M), None)
                    if kind is None:
                        break
                    row.append((box(cursor, y, cursor + kind.length_m, y + depth), kind))
                    cursor += kind.length_m + gap
            if row:
                out += row
                y += depth + gap
            else:
                y += SWEEP_STEP_M
    back = []
    for poly, kind in out:
        if side == HIGH:
            poly = affinity.scale(poly, 1, -1, origin=(0, 0))
        back.append((affinity.rotate(poly, angle, origin=(0, 0)), kind))
    return back


def _stretches(land: BaseGeometry, y: float, depth: float) -> list[tuple[float, float]]:
    """The ranges of x where a band `depth` deep from `y` lies wholly on the land."""
    x0, _, x1, _ = land.bounds
    band = box(x0 - 1, y, x1 + 1, y + depth)
    blocked = sorted((p.bounds[0], p.bounds[2]) for p in _parts(band.difference(land)))
    out, cursor = [], x0 - 1
    for low, high in blocked:
        if low > cursor + FIT_M:
            out.append((cursor, low))
        cursor = max(cursor, high)
    if cursor < x1 + 1 - FIT_M:
        out.append((cursor, x1 + 1))
    return [(a, b) for a, b in out if b - a > FIT_M]


def loop_band(net: Polygon, high_rise: bool, main: Polygon, reach_m: float) -> BaseGeometry:
    """The loop road's land: 8(m)'s 9 m road just inside the 2 m green strip a high-rise site
    keeps (7(a)(viii)), round the main part of the plot (`main`, the largest arm, within
    `reach_m` of it); a narrow arm keeps no loop of its own."""
    inner = (rules.PERIPHERAL_GREEN_STRIP_M if high_rise else 0.0) + rules.INTERNAL_ROAD_M
    band = net.difference(net.buffer(-inner, join_style="mitre"))
    return band.intersection(main.buffer(reach_m + inner, join_style="mitre"))


def _parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    return [g for g in getattr(geometry, "geoms", [geometry])
            if isinstance(g, Polygon) and not g.is_empty]
