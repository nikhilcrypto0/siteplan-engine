"""Small geometry helpers shared by the survey readers, the one reading of a compass side that
the envelope, the search and the validator all take (`faces`), and how much of a block faces a
road (`frontage`), which the search and its objective share."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring, unary_union

COMPASS_DEG = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
# A stretch of boundary faces a compass side when its outward normal is within FACING_DEG of the
# side's bearing, the limit included. A side is a label, the nearest of eight compass points to
# where the road really lies, so a diagonal label (SW) may stand for a road facing the south or
# the west edge squarely: those are exactly 45 degrees off it, a knife-edge that a plot turned a
# hair would fall off. A diagonal label reaches half a compass step further.
FACING_DEG = 45.0
DIAGONAL_SLOP_DEG = 22.5


COMPASS_WORDS = {"N": "north", "NE": "north-east", "E": "east", "SE": "south-east",
                 "S": "south", "SW": "south-west", "W": "west", "NW": "north-west"}


def compass_of(bearing_deg: float) -> str:
    """The nearest of the eight compass points to a bearing (0 north, 90 east), as a word."""
    code = min(COMPASS_DEG, key=lambda c: angle_between(bearing_deg, COMPASS_DEG[c]))
    return COMPASS_WORDS[code]


def bearing_to(origin: tuple[float, float], to: tuple[float, float]) -> float:
    """The bearing from one point to another, clockwise from north (y is north)."""
    return math.degrees(math.atan2(to[0] - origin[0], to[1] - origin[1])) % 360


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


def line_runs(line: LineString, tolerance_deg: float = 3.0) -> list[Run]:
    """The straight stretches of an open line, read as `straight_runs` reads an outline: an edge
    whose direction is within `tolerance_deg` of the one before it continues its stretch."""
    coords = [tuple(p[:2]) for p in line.coords]
    coords = [p for k, p in enumerate(coords) if k == 0 or p != coords[k - 1]]
    if len(coords) < 2:
        return []
    groups: list[list[tuple]] = [[coords[0], coords[1]]]
    for a, b in zip(coords[1:], coords[2:], strict=False):
        if angle_gap(_direction(a, b), _direction(*groups[-1][-2:])) <= tolerance_deg:
            groups[-1].append(b)
        else:
            groups.append([a, b])
    return [Run(LineString(g), _direction(g[0], g[-1])) for g in groups]


def opening(shape, width_m: float):
    """Remove every part of a shape narrower than width_m (shrink by half, grow back)."""
    half = width_m / 2 - 1e-6
    return shape.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")


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


STRIP_LENGTH_TOL_M = 0.01  # how closely the length of a strip from a corner is found


@dataclass(frozen=True)
class CornerStrip:
    """Land given up along part of the boundary, from a corner (`strip_from_corner`)."""

    plot: Polygon  # what is left
    strip: BaseGeometry  # the land given up
    stretch: LineString  # the boundary it runs along, from the corner
    corner: tuple[float, float]


def strip_from_corner(boundary: Polygon, corner: str, toward: str, width_m: float,
                      area_sqm: float) -> CornerStrip:
    """The plot left after a strip `width_m` wide, measured square into the plot from the
    boundary, comes off it from the plot's corner furthest toward `corner` (a compass point),
    running along the boundary the way that sets off nearer `toward` and on round any corner it
    meets, for as long as it takes to reach `area_sqm`; it ends cut square. Where the corner it
    starts from is sharper than a right angle, the strip takes all of the tip within its width of
    that side, its inner edge carried on to the plot's other side as a road's edge runs, rather
    than cut square at the tip (2026-10-21: Dhulapally's east tip, where the firm's plan gives up
    the whole tip and a square start left a sliver nobody could use). Nothing is inferred: the
    corner, the direction, the width and the area are the architect's, and the caller checks what
    comes off against the stated deduction."""
    if area_sqm <= 0:
        raise ValueError(f"A strip of {area_sqm:,.0f} m² takes nothing off the plot.")
    ring = list(boundary.exterior.coords)[:-1]
    east, north = math.sin(math.radians(COMPASS_DEG[corner])), math.cos(
        math.radians(COMPASS_DEG[corner]))
    start = max(range(len(ring)), key=lambda i: ring[i][0] * east + ring[i][1] * north)
    onward = [*ring[start:], *ring[:start], ring[start]]
    ways = sorted((onward, onward[::-1]), key=lambda path: angle_between(
        bearing_to(path[0], path[1]), COMPASS_DEG[toward]))
    off = [angle_between(bearing_to(p[0], p[1]), COMPASS_DEG[toward]) for p in ways]
    if off[0] >= off[1]:
        raise ValueError(f"From the {corner} corner both ways along the boundary head as far "
                         f"from {toward}; say which way the strip runs.")
    path = LineString(ways[0])
    back = _tip_reach(ways[0][0], ways[0][1], ways[1][1], width_m)
    (x0, y0), (x1, y1) = ways[0][0], ways[0][1]
    run = math.hypot(x1 - x0, y1 - y0)
    lead = LineString([(x0 - (x1 - x0) / run * back, y0 - (y1 - y0) / run * back),
                       *ways[0]]) if back > 0 else path

    def band(length: float) -> BaseGeometry:
        line = substring(lead, 0, length + back)
        return line.buffer(width_m, cap_style="flat", join_style="mitre").intersection(boundary)

    if band(path.length).area < area_sqm:
        raise ValueError(f"A {width_m:g} m strip all round the plot comes to less than "
                         f"{area_sqm:,.0f} m².")
    short, long = 0.0, path.length
    while long - short > STRIP_LENGTH_TOL_M:
        mid = (short + long) / 2
        short, long = (mid, long) if band(mid).area < area_sqm else (short, mid)
    strip = band(long)
    rest = boundary.difference(strip)
    parts = [p for p in getattr(rest, "geoms", [rest]) if p.geom_type == "Polygon"]
    if not parts:
        raise ValueError(f"A {width_m:g} m strip from the {corner} corner leaves no plot.")
    return CornerStrip(max(parts, key=lambda p: p.area), strip, substring(path, 0, long),
                       ring[start])


def _tip_reach(tip, along, other, width_m: float) -> float:
    """How far before the corner `tip` a strip `width_m` wide running from it toward `along` must
    start to take all of the corner's tip, the other side leaving it toward `other`: none where
    the corner is a right angle or sharper (the other side runs ahead of a square start), else as
    far back as the other side runs within that width of the strip's side, which a square start
    would leave as a sliver (and no further than that side's own length)."""
    ux, uy = along[0] - tip[0], along[1] - tip[1]
    vx, vy = other[0] - tip[0], other[1] - tip[1]
    lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
    if lu == 0 or lv == 0:
        return 0.0
    behind = -(ux * vx + uy * vy) / (lu * lv)  # the other side's run back behind the start
    if behind <= 0:
        return 0.0
    sin = math.sqrt(max(0.0, 1 - behind * behind))
    reach = width_m * behind / sin if sin > 0 else lv
    return min(reach, lv * behind)


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
