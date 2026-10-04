"""Internal roads and fire access: the land vehicles need, laid out before anything else.

A group development scheme's roads are rule 8(m)'s: a main internal approach road from the
entrance, other internal and looped roads, cul-de-sacs only in their own form. A driveway (rule
13(c)(viii), 4.5 m) is not one of them. The layout draws:

- a loop road of 9 m running round the site just inside the 2 m green strip, so every road that
  crosses the site joins it at both ends and none is a dead end;
- the main internal approach road, 9 m, from an entrance on the side the access road runs along;
- a 9 m internal road in every corridor between two columns of towers, from the loop to the loop.

Fire access is NBC 2016 Part 3 4.6(c), brought in by rule 15(b)(iv): 6 m of motorable open space
on every side of a high-rise, a turning radius of 9 m, nothing parked or built in it. The 9 m is
read as the tender's turning circle, the outer edge of the 6 m lane, so a lane turns round a
square corner on an arc of 3 to 9 m. Turning round a tower's corner that way needs 6.88 m of clear
ground beside each face (FIRE_BAND_M), which is the band every high-rise keeps. The turns are
checked as the swept sectors themselves, at every tower corner and every bend of the loop.

Everything here is geometry the checker measures again from the drawing; nothing is taken on
trust from the layout that built it.

The road generators here (`loop_road`, `entrance`, `green_strip`, `inner_plot`, `fire_bands`,
`loop_turns`, and what `grounds.frame` builds with them) are LEGACY, not for production
generation by a language model: kept only for regression comparison. Production generation is
`siteplan.service`. The constants (the lane, the radii, the 9 m road) stay shared.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from siteplan import rules
from siteplan.geometry import COMPASS_DEG, Run, facing_deg, opening, straight_runs

EPS_M = 0.01
LANE_M = rules.FIRE_TENDER_MIN_WIDTH_M
R_OUT = rules.FIRE_TURNING_RADIUS_M
R_IN = R_OUT - LANE_M
# Clear ground beside each face of a rectangular block for a lane that turns round its corners:
# the swept sector reaches R_OUT - R_IN*sin(45 degrees) from each face. This 6.88 m is derived
# from our reading of the 9 m (UNRESOLVED_INTERPRETATION: measured at the lane's outer edge); the
# order gives the 9 m and the 6 m, never this figure. A 9 m centreline would make it 7.76 m.
FIRE_BAND_M = R_OUT - R_IN * math.sin(math.pi / 4)
ROAD_M = rules.INTERNAL_ROAD_M
APPROACH_M = rules.MAIN_APPROACH_ROAD_M[0]
SECTOR_STEPS = 24
SECTOR_TOLERANCE_SQM = 0.5  # arcs are drawn as chords; less than this outside is drawing noise
MIN_TURN_DEG = 5.0  # a bend shallower than this is a straight road


@dataclass(frozen=True)
class RoadPiece:
    kind: str  # 'main approach', 'loop', 'internal' or 'cul-de-sac'
    shape: Polygon
    width_m: float

    def as_dict(self) -> dict:
        return {"kind": self.kind, "width_m": self.width_m, "area_sqm": round(self.shape.area, 1)}


@dataclass(frozen=True)
class Entrance:
    gate: Polygon  # the opening in the boundary
    approach: Polygon  # the main internal approach road, from the gate to the loop
    width_m: float
    note: str  # which side it is on, and why


def green_strip_width(setback_m: float) -> float:
    """Rule 7(a)(viii) as substituted in 2016: 2 m where the setback is 9 m or more."""
    if setback_m >= rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M:
        return rules.PERIPHERAL_GREEN_STRIP_M
    return 0.0


def tower_inset(setback_m: float) -> float:
    """How far towers stand from the plot line: the Table IV setback, or further where the loop
    road and the green strip need more room than the setback gives."""
    return max(setback_m, green_strip_width(setback_m) + ROAD_M)


def inner_plot(plot: Polygon, green_m: float, keep_out=None):
    """The ground vehicles may use: the plot less the green strip and any water buffer."""
    inner = plot.buffer(-green_m, join_style="mitre") if green_m else plot
    return inner.difference(keep_out) if keep_out is not None else inner


def green_strip(plot: Polygon, green_m: float, gate: Polygon | None = None):
    """The planting strip along the boundary, broken only where the entrance crosses it."""
    if not green_m:
        return None
    strip = plot.difference(plot.buffer(-green_m, join_style="mitre"))
    return strip.difference(gate) if gate is not None else strip


def loop_road(envelope, inner):
    """The 9 m loop between the towers' land and the green strip."""
    band = envelope.buffer(ROAD_M + EPS_M, join_style="mitre").intersection(inner)
    return band.difference(envelope)


ENTRANCE_POSITIONS = (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8)  # along the side, middle first
ENTRANCE_STEP_M = 3.0  # where along a side an entrance is tried, when it has to reach a loop
APPROACH_MAX_M = 80.0
LOOP_OVERLAP_SQM = 18.0  # the approach runs 2 m into the loop road, so the two join


def entrance(plot: Polygon, access_side: str | None, depth_m: float, keep_out=None,
             reach=None) -> Entrance:
    """The main entrance and approach road on the side the access road runs along. With a loop
    to `reach`, the entrance goes where the shortest approach joins it, off any water buffer;
    without one, as near the middle of the longest stretch as keeps off the water. With no side
    known it goes on the longest stretch, and the note says so."""
    runs = straight_runs(plot)
    facing = [r for r in runs if access_side and _faces(plot, r, access_side)]
    if facing:
        note = f"on the {access_side} side, where the access road runs"
        # The approach is a straight road as wide as APPROACH_M, so it starts on a stretch of
        # boundary at least that long. A side traced through survey points is jagged, every
        # piece shorter than the road: the road then starts on the side's overall line, and
        # its mouth follows the boundary. Anchored on a short piece, it hung past the piece's
        # ends and was cut to a sliver 9 m wide nowhere (found on Suchitra).
        facing = [r for r in facing if r.length >= APPROACH_M] or [_chord(facing)]
    else:
        facing = [max(runs, key=lambda r: r.length)]
        note = ("ASSUMED on the longest boundary: no access side is known" if not access_side
                else f"ASSUMED on the longest boundary: no side faces {access_side}")
    gate_depth = max(rules.PERIPHERAL_GREEN_STRIP_M, 1.0)
    if reach is None or reach.is_empty:
        run = max(facing, key=lambda r: r.length)
        spots = [run.line.interpolate(f, normalized=True) for f in ENTRANCE_POSITIONS]
        rect = _approach_along(plot, run)
        clear = [p for p in spots if keep_out is None or
                 rect(p, depth_m).intersection(keep_out).area < EPS_M]
        at = clear[0] if clear else spots[0]
        return Entrance(rect(at, gate_depth).intersection(plot),
                        rect(at, depth_m).intersection(plot), APPROACH_M, note)
    best = None
    for run in facing:
        rect = _approach_along(plot, run)
        steps = int((run.length - APPROACH_M) // ENTRANCE_STEP_M)
        for i in range(max(steps, 0) + 1):
            at = run.line.interpolate(APPROACH_M / 2 + i * ENTRANCE_STEP_M)
            depth = _depth_to(rect, at, depth_m, reach, keep_out)
            if depth is not None and (best is None or depth < best[0]):
                best = (depth, rect, at)
    if best is None:  # no approach reaches the loop: keep the plain one, the checker will say
        return entrance(plot, access_side, depth_m, keep_out)
    depth, rect, at = best
    return Entrance(rect(at, gate_depth).intersection(plot),
                    rect(at, depth).intersection(plot), APPROACH_M, note)


def _approach_along(plot: Polygon, run):
    (x0, y0), (x1, y1) = run.line.coords[0], run.line.coords[-1]
    along = ((x1 - x0) / run.length, (y1 - y0) / run.length)
    inward = _inward(plot, run.line, along)
    half = APPROACH_M / 2 + EPS_M

    def rectangle(at, depth: float) -> Polygon:
        a = (at.x - along[0] * half, at.y - along[1] * half)
        b = (at.x + along[0] * half, at.y + along[1] * half)
        return Polygon([a, b, (b[0] + inward[0] * depth, b[1] + inward[1] * depth),
                        (a[0] + inward[0] * depth, a[1] + inward[1] * depth)])

    return rectangle


def _depth_to(rect, at, least: float, reach, keep_out) -> float | None:
    """How deep an approach from `at` must go to run into the loop; None if it cannot, or
    would cross water on the way. The overlap only grows with depth, so it is bisected."""
    def overlap(depth: float) -> float:
        return rect(at, depth).intersection(reach).area

    if overlap(APPROACH_MAX_M) < LOOP_OVERLAP_SQM:
        return None
    lo, hi = least, APPROACH_MAX_M
    if overlap(lo) < LOOP_OVERLAP_SQM:
        for _ in range(12):  # to within 2 cm
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if overlap(mid) >= LOOP_OVERLAP_SQM else (mid, hi)
    else:
        hi = lo
    if keep_out is not None and rect(at, hi).intersection(keep_out).area > EPS_M:
        return None
    return hi


def _chord(runs) -> Run:
    """The straight line between the two points of a chain of runs that lie farthest apart:
    the overall line of a jagged side."""
    points = [p for run in runs for p in run.line.coords]
    a, b = max(((p, q) for i, p in enumerate(points) for q in points[i + 1:]),
               key=lambda pq: math.dist(*pq))
    return Run(LineString([a, b]), math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180)


def _faces(plot: Polygon, run, side: str) -> bool:
    return abs((facing_deg(plot, run) - COMPASS_DEG[side] + 180) % 360 - 180) < 45


def _inward(plot: Polygon, line, along: tuple[float, float]) -> tuple[float, float]:
    """The normal pointing into the plot: tested just off the line's middle, or, when the line
    is a chord that does not lie on the boundary, towards the plot's centre."""
    normal = (-along[1], along[0])
    middle = line.interpolate(0.5, normalized=True)
    ahead = plot.contains(Point(middle.x + normal[0] * 0.5, middle.y + normal[1] * 0.5))
    behind = plot.contains(Point(middle.x - normal[0] * 0.5, middle.y - normal[1] * 0.5))
    if ahead != behind:
        return normal if ahead else (-normal[0], -normal[1])
    centre = plot.centroid
    toward = (centre.x - middle.x) * normal[0] + (centre.y - middle.y) * normal[1]
    return normal if toward > 0 else (-normal[0], -normal[1])


def fire_bands(footprints) -> Polygon | None:
    """The clear ground round each high-rise: FIRE_BAND_M on every side, corners square."""
    if not footprints:
        return None
    bands = unary_union([f.buffer(FIRE_BAND_M, join_style="mitre") for f in footprints])
    return bands.difference(unary_union(list(footprints)))


# Turning sectors ------------------------------------------------------------------------------

def sector(centre: tuple[float, float], r_in: float, r_out: float, start: float,
           sweep: float) -> Polygon:
    """An annular sector: the ground a lane sweeps turning round `centre`, from angle `start`
    through `sweep` radians (negative turns clockwise)."""
    angles = [start + sweep * i / SECTOR_STEPS for i in range(SECTOR_STEPS + 1)]
    cx, cy = centre
    outer = [(cx + r_out * math.cos(a), cy + r_out * math.sin(a)) for a in angles]
    inner = [(cx + r_in * math.cos(a), cy + r_in * math.sin(a)) for a in reversed(angles)]
    return Polygon(outer + inner)


def _corners(polygon: Polygon):
    """(vertex, incoming unit direction, outgoing unit direction, turn) for each corner of an
    anticlockwise outline; turn > 0 is a left turn, a convex corner."""
    ring = list(orient(polygon, 1.0).exterior.coords)[:-1]
    ring = [p for i, p in enumerate(ring) if Point(p).distance(Point(ring[i - 1])) > 1e-6]
    n = len(ring)
    for i in range(n):
        prev, here, nxt = ring[i - 1], ring[i], ring[(i + 1) % n]
        d1 = _unit(prev, here)
        d2 = _unit(here, nxt)
        turn = math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])
        if abs(math.degrees(turn)) >= MIN_TURN_DEG:
            yield here, d1, d2, turn


def _unit(a, b) -> tuple[float, float]:
    length = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return ((b[0] - a[0]) / length, (b[1] - a[1]) / length)


def _right(d):  # the outward normal of an anticlockwise outline's edge
    return (d[1], -d[0])


def _angle(v) -> float:
    return math.atan2(v[1], v[0])


def around_block(footprint: Polygon) -> list[Polygon]:
    """The swept sector at each convex corner of a block, for a lane going round it on the
    outside: the corner touches the lane's inner edge, the sector reaching FIRE_BAND_M out."""
    sectors = []
    for (vx, vy), d1, d2, turn in _corners(footprint):
        if turn <= 0:
            continue  # a notch in the block; the lane does not go into it
        n1, n2 = _right(d1), _right(d2)
        bx, by = n1[0] + n2[0], n1[1] + n2[1]
        size = math.hypot(bx, by) or 1.0
        centre = (vx - R_IN * bx / size, vy - R_IN * by / size)
        sectors.append(sector(centre, R_IN, R_OUT, _angle(n1), turn))
    return sectors


def along_boundary(inner: Polygon) -> list[Polygon]:
    """The swept sector at each bend of the loop road, which runs along the inside of the green
    strip. At a convex corner the lane keeps to the outer edge and turns inside the corner; at a
    reflex one (the boundary stepping into the site) it goes round the step like a block."""
    sectors = []
    parts = getattr(inner, "geoms", [inner])
    for part in parts:
        if part.is_empty or part.geom_type != "Polygon":
            continue
        for (vx, vy), d1, d2, turn in _corners(part):
            n1, n2 = _right(d1), _right(d2)  # pointing out of the site
            if turn > 0:  # convex: centre inside, R_OUT from both edges
                interior = math.pi - turn
                bx, by = -(n1[0] + n2[0]), -(n1[1] + n2[1])
                size = math.hypot(bx, by) or 1.0
                reach = R_OUT / math.sin(interior / 2)
                centre = (vx + reach * bx / size, vy + reach * by / size)
                sectors.append(sector(centre, R_IN, R_OUT, _angle(n1), turn))
            else:  # reflex: the outside is the obstacle, its normals point into the site
                m1, m2 = (-n1[0], -n1[1]), (-n2[0], -n2[1])
                bx, by = m1[0] + m2[0], m1[1] + m2[1]
                size = math.hypot(bx, by) or 1.0
                centre = (vx - R_IN * bx / size, vy - R_IN * by / size)
                sectors.append(sector(centre, R_IN, R_OUT, _angle(m1), turn))
    return sectors


def loop_turns(loop) -> list[Polygon]:
    """The swept sectors along the loop road as drawn: at the bends of its outer edge, as the
    boundary's; round the corners of the land it rings, as a block's."""
    sectors = []
    for part in getattr(loop, "geoms", [loop]):
        if part.is_empty or part.geom_type != "Polygon":
            continue
        sectors += along_boundary(Polygon(part.exterior))
        for hole in part.interiors:
            sectors += around_block(Polygon(hole))
    return sectors


def blocked(sectors: list[Polygon], free) -> list[Polygon]:
    """The sectors that do not lie wholly on free, motorable ground."""
    return [s for s in sectors if s.difference(free).area > SECTOR_TOLERANCE_SQM]


def lane_passes(shape) -> Polygon:
    """Where a 6 m lane can pass: the shape less every part narrower than the lane."""
    return opening(shape, LANE_M - 2 * EPS_M)


END_M = 1.0  # how much of a road's length counts as its end
TOUCH_M = 0.5


def through_roads(pieces: list[RoadPiece], base) -> tuple[list[RoadPiece], list[RoadPiece]]:
    """Split internal roads into those joining the rest of the network at both ends and the
    dead ends. A road running alongside the loop touches it all along its side, so it is its
    two ends that are looked at, not how many times it touches."""
    through, dead = [], []
    for piece in pieces:
        others = [p.shape for p in pieces if p is not piece]
        network = unary_union([base, *others]).buffer(TOUCH_M)
        ends = road_ends(piece.shape)
        (through if ends and all(e.intersects(network) for e in ends) else dead).append(piece)
    return through, dead


def road_ends(shape: Polygon) -> list[Polygon]:
    """The two ends of a road, END_M deep, across its length."""
    angle = _long_axis(shape)
    turned = rotate(shape, -angle, origin=(0, 0))
    minx, miny, maxx, maxy = turned.bounds
    caps = [box(minx - 1, miny - 1, minx + END_M, maxy + 1),
            box(maxx - END_M, miny - 1, maxx + 1, maxy + 1)]
    return [rotate(turned.intersection(cap), angle, origin=(0, 0)) for cap in caps
            if not turned.intersection(cap).is_empty]


def _long_axis(shape: Polygon) -> float:
    """The direction, in degrees, of the long side of the smallest rectangle round the shape."""
    hull = list(shape.convex_hull.exterior.coords)
    best = None
    for (x0, y0), (x1, y1) in zip(hull, hull[1:], strict=False):
        if (x0, y0) == (x1, y1):
            continue
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
        minx, miny, maxx, maxy = rotate(shape, -angle, origin=(0, 0)).bounds
        area = (maxx - minx) * (maxy - miny)
        if best is None or area < best[0]:
            long = angle if maxx - minx >= maxy - miny else angle + 90
            best = (area, long)
    return best[1] if best else 0.0


def healed(shape, gap_m: float = 0.05):
    """The shape with hairline cracks closed: pieces drawn to meet can miss by a hair."""
    return shape.buffer(gap_m, join_style="mitre").buffer(-gap_m, join_style="mitre")
