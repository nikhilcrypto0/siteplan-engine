"""Small geometry helpers shared by the survey readers, the one reading of a compass side that
the envelope, the search and the validator all take (`faces`), and how much of a block faces a
road (`frontage`), which the search and its objective share."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, polygonize, polylabel, unary_union

COMPASS_DEG = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
# A stretch of boundary faces a compass side when its outward normal is within FACING_DEG of the
# side's bearing, the limit included. A side is a label, the nearest of eight compass points to
# where the road really lies, so a diagonal label (SW) may stand for a road facing the south or
# the west edge squarely: those are exactly 45 degrees off it, a knife-edge that a plot turned a
# hair would fall off. A diagonal label reaches half a compass step further.
FACING_DEG = 45.0
DIAGONAL_SLOP_DEG = 22.5


def angle_between(a_deg: float, b_deg: float) -> float:
    """The smaller angle between two bearings, in degrees."""
    return abs((a_deg - b_deg + 180) % 360 - 180)


def faces(bearing_deg: float, side: str) -> bool:
    """Whether a stretch of boundary whose outward normal faces `bearing_deg` (0 north, 90 east)
    faces the side a road is labelled with: within FACING_DEG of the side's bearing, a diagonal
    label DIAGONAL_SLOP_DEG more, the limit included (to a millionth of a degree of float noise).
    The envelope's frontage, the search's setbacks and the validator's front all read it here."""
    centre = COMPASS_DEG[side]
    reach = FACING_DEG + (DIAGONAL_SLOP_DEG if centre % 90 else 0.0)
    return angle_between(bearing_deg, centre) <= reach + 1e-6


@dataclass(frozen=True)
class Run:
    """A straight stretch of a boundary, merged from consecutive near-collinear edges."""

    line: LineString
    angle_deg: float  # direction modulo 180, so a run and its reverse compare equal

    @property
    def length(self) -> float:
        return float(self.line.length)


def _direction(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180


def angle_gap(a_deg: float, b_deg: float) -> float:
    """Smallest difference between two undirected line angles, in degrees."""
    gap = abs(a_deg - b_deg) % 180
    return min(gap, 180 - gap)


def straight_runs(polygon: Polygon, tolerance_deg: float = 3.0) -> list[Run]:
    """The straight stretches of the outline, of every piece when a nala splits the shape."""
    if polygon.geom_type == "MultiPolygon":
        return [run for part in polygon.geoms for run in straight_runs(part, tolerance_deg)]
    coords = list(polygon.exterior.coords)[:-1]
    edges = [(coords[i], coords[(i + 1) % len(coords)]) for i in range(len(coords))]
    edges = [e for e in edges if e[0] != e[1]]
    groups: list[list[tuple]] = [[edges[0]]]
    for edge in edges[1:]:
        if angle_gap(_direction(*edge), _direction(*groups[-1][-1])) <= tolerance_deg:
            groups[-1].append(edge)
        else:
            groups.append([edge])
    wraps = angle_gap(_direction(*groups[-1][-1]), _direction(*groups[0][0])) <= tolerance_deg
    if len(groups) > 1 and wraps:
        groups[0] = groups.pop() + groups[0]
    runs = []
    for group in groups:
        points = [group[0][0]] + [edge[1] for edge in group]
        runs.append(Run(LineString(points), _direction(points[0], points[-1])))
    return runs


def opening(shape, width_m: float):
    """Remove every part of a shape narrower than width_m (shrink by half, grow back)."""
    half = width_m / 2 - 1e-6
    return shape.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")


ELBOW_MIN_TURN_DEG = 45.0  # a reflex corner turning the plot line at least this far is an elbow:
# the plot there is two parts, each running its own way, meeting near a right angle or wider open.
# A shallower corner is a kink in one part, not two parts (a few degrees is the surveyor's hand,
# and a curve is many such corners); Dhulapally's own elbow turns 81.3 degrees.
ELBOW_MIN_PART_SQM = 200.0  # a part of the plot smaller than this is a notch, not a part
ELBOW_MIN_PART_WIDTH_M = 10.0  # nor is a part no wider than this (a jog in the plot line cuts a
# sliver the whole length of the plot)
ELBOW_EDGE_TO_NECK = 0.5  # past an elbow the plot line runs on at least this share of the neck's
# width: a part that runs its own way is as long as the neck is wide, where a notch or a jog cuts
# across the whole plot on edges a few metres long
ELBOW_MAX_CUTS = 8  # the most cuts made across one plot, the sharpest corners first


def elbow_regions(net: Polygon) -> list[Polygon]:
    """The net plot cut into the parts that meet at its elbows: at each reflex corner that turns
    the plot line by ELBOW_MIN_TURN_DEG or more, the plot is cut along the shorter of the two
    lines that carry the corner's own edges on into the plot (the cut across the neck), the
    sharpest corner first, as long as both sides keep ELBOW_MIN_PART_SQM. The parts overlap in
    nothing and make up the plot; a plot with no such corner is one part, itself.

    What the law asks of a building depends on the building, so how deep a setback is asked round
    a plot belongs to the part the buildings stand in (`validator.zones.setback_zone`, the
    search's `land.zone_depths`)."""
    parts = [Polygon(orient(net, 1.0).exterior)]
    for _ in range(ELBOW_MAX_CUTS):
        cut = _sharpest_cut(parts)
        if cut is None:
            break
        parts.remove(cut[0])
        parts.extend(cut[1])
    if len(parts) == 1:
        return [net]
    holes = [Polygon(ring) for ring in net.interiors]
    return [p.difference(h) if (h := _hole_in(p, holes)) is not None else p for p in parts]


def _hole_in(part: Polygon, holes: list[Polygon]):
    inside = [h for h in holes if part.intersects(h)]
    return unary_union(inside) if inside else None


def _sharpest_cut(parts: list[Polygon]) -> tuple[Polygon, list[Polygon]] | None:
    """The part whose sharpest elbow can be cut, and the two pieces it makes; None when no part
    has an elbow that can be cut."""
    options = []
    for part in parts:
        for turn, vertex, directions, longest in _elbows(part):
            for chord in sorted(_chords(part, vertex, directions), key=lambda c: c.length):
                if longest < ELBOW_EDGE_TO_NECK * chord.length:
                    continue
                pieces = _split(part, chord)
                if pieces is not None:
                    options.append((turn, -chord.length, part, pieces))
                    break
    if not options:
        return None
    _, _, part, pieces = max(options, key=lambda o: o[:2])
    return part, pieces


def _elbows(part: Polygon
            ) -> list[tuple[float, tuple[float, float], list[tuple[float, float]], float]]:
    """The reflex corners of a part that turn its outline by ELBOW_MIN_TURN_DEG or more, each with
    how far it turns, where it lies, the two directions its edges run on in and the length of the
    longer edge: the plot line running on in its new direction."""
    ring = list(orient(part, 1.0).exterior.coords)[:-1]
    found = []
    for i, vertex in enumerate(ring):
        before, after = ring[i - 1], ring[(i + 1) % len(ring)]
        ax, ay = vertex[0] - before[0], vertex[1] - before[1]
        bx, by = after[0] - vertex[0], after[1] - vertex[1]
        if not (math.hypot(ax, ay) and math.hypot(bx, by)):
            continue
        turn = math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
        if -turn >= ELBOW_MIN_TURN_DEG:  # counter-clockwise: a right turn is a reflex corner
            found.append((-turn, vertex, [(ax, ay), (-bx, -by)],
                          max(math.hypot(ax, ay), math.hypot(bx, by))))
    return found


def _chords(part: Polygon, vertex: tuple[float, float], directions: list[tuple[float, float]]
            ) -> list[LineString]:
    """The lines from a reflex corner along each of its edges' own directions, on into the part
    as far as its outline."""
    minx, miny, maxx, maxy = part.bounds
    reach = 2 * math.hypot(maxx - minx, maxy - miny) + 1.0
    chords = []
    for dx, dy in directions:
        length = math.hypot(dx, dy)
        ray = LineString([vertex, (vertex[0] + dx / length * reach,
                                   vertex[1] + dy / length * reach)])
        inside = ray.intersection(part)
        pieces = [g for g in getattr(inside, "geoms", [inside])
                  if isinstance(g, LineString) and g.length > 0
                  and g.distance(Point(vertex)) < 1e-6]
        if pieces:
            chords.append(max(pieces, key=lambda g: g.length))
    return chords


def _split(part: Polygon, chord: LineString) -> list[Polygon] | None:
    """The two pieces a chord cuts a part into, when each keeps ELBOW_MIN_PART_SQM and is
    ELBOW_MIN_PART_WIDTH_M wide somewhere."""
    pieces = [p for p in polygonize(unary_union([part.boundary, chord]))
              if part.contains(p.representative_point())]
    if len(pieces) != 2 or min(p.area for p in pieces) < ELBOW_MIN_PART_SQM:
        return None
    if min(_widest_m(p) for p in pieces) < ELBOW_MIN_PART_WIDTH_M:
        return None
    return pieces


def _widest_m(piece: Polygon) -> float:
    """The diameter of the widest circle that fits in a piece."""
    return 2 * piece.boundary.distance(polylabel(piece, tolerance=0.1))


def facing_deg(boundary: Polygon, run: Run) -> float:
    """The compass bearing a run faces out of the plot: 0 north, 90 east (y is north)."""
    (x0, y0), (x1, y1) = run.line.coords[0], run.line.coords[-1]
    nx, ny = (y1 - y0) / run.length, (x0 - x1) / run.length
    mid = run.line.interpolate(0.5, normalized=True)
    if boundary.contains(Point(mid.x + nx * 0.5, mid.y + ny * 0.5)):
        nx, ny = -nx, -ny
    return math.degrees(math.atan2(nx, ny)) % 360


def strip_along_side(boundary: Polygon, side: str, width_m: float) -> Polygon:
    """The plot left after an even strip of that width comes off every run facing that side
    (within 45 degrees), as the architect describes it. Nothing is inferred: the side and the
    width are given; the caller checks the area that comes off against the stated deduction."""
    # A strict 45 degrees for every label, not `faces`: the strip places the net plot itself,
    # which every result after it (the regression's included) rests on.
    runs = [run for run in straight_runs(boundary)
            if abs((facing_deg(boundary, run) - COMPASS_DEG[side] + 180) % 360 - 180) < 45]
    if not runs:
        raise ValueError(f"No side of the plot faces {side}.")
    edge = unary_union([run.line for run in runs])
    rest = boundary.difference(edge.buffer(width_m, cap_style="flat", join_style="mitre"))
    parts = [p for p in getattr(rest, "geoms", [rest]) if p.geom_type == "Polygon"]
    if not parts:
        raise ValueError(f"A {width_m:g} m strip off the {side} side leaves no plot.")
    return max(parts, key=lambda p: p.area)


def frontage(footprint: Polygon, near: BaseGeometry, within_m: float) -> float:
    """The longest unbroken stretch of a block's outline within `within_m` of the ground given (a
    road, a fire lane, a pathway): how much of the block faces it, where a corner that only
    touches it has almost none. The validator measures the same with its own copy."""
    if footprint.is_empty or near.is_empty:
        return 0.0
    close = footprint.exterior.intersection(near.buffer(within_m))
    runs = [g for g in getattr(close, "geoms", [close]) if isinstance(g, LineString) and g.length]
    if not runs:
        return 0.0
    merged = linemerge(runs)  # a stretch over the ring's first point comes back in two pieces
    return max(g.length for g in getattr(merged, "geoms", [merged]))
