"""Roads next to the plot, measured across themselves from their drawn edge lines.

Road width decides how tall a building may go (Table IV column 3), so it is read off the
survey rather than typed in. A road running along a side is crossed by a ray out of the plot,
but the roads a plot takes its access from usually end at it, and a ray outward then runs
between their edges without crossing either. So each road is measured across itself: every
few metres along each drawn edge near the plot, a line at right angles to that edge is laid
across the road, and the edge lines it crosses make one cross-section. The lines most
cross-sections agree on are the road's edges, which keeps a footpath drawn in short dashes
(crossed about half the time) and drops a stray crossing.

The width is what is drawn: the carriageway alone on one sheet, the full right of way on
another. The rules want the legal width, so the architect confirms it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from siteplan.survey import Survey
from siteplan.units import M_PER_FT

REACH_M = 40.0  # roads further than this from the plot are not listed
STEP_M = 2.0  # how often a cross-section is taken along each drawn edge
CROSS_M = 30.0  # how far a cross-section reaches either side of its edge
LANE_GAP_M = 12.0  # neighbouring edge lines further apart than this are different roads
PARALLEL_DEG = 8.0
MIN_PIECE_M = 0.01  # anything drawn marks an edge, down to the dots of a dotted line
WINDOW_M = 0.6  # a dot or dash this near a cross-section, along the road, counts as crossed
MIN_SAMPLED_PIECE_M = 1.0  # cross-sections are taken along pieces at least this long
SAME_LINE_M = 0.3  # crossings this close together are one edge line
MIN_SHARE = 0.25  # an edge line must show in this share of a road's cross-sections
MIN_WIDTH_M = 3.0
DIVIDER_MAX_M = 3.0  # an inner strip this narrow, between wider ones, is a divider
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class Road:
    width_m: float  # outermost drawn edge to outermost drawn edge
    lines_m: tuple[float, ...]  # every edge line across the road, measured from the first
    distance_m: float  # from the plot to the road's nearest drawn edge
    side: str  # which side of the plot it lies on, N to NW
    direction_deg: float  # the road's own direction, 0-180, anticlockwise from east
    sections: int  # how many cross-sections were taken
    edges: tuple[LineString, ...] = ()  # the drawn edge lines its width was measured across
    area: Polygon | None = None  # the ground between its outermost edges, where they are drawn

    @property
    def width_ft(self) -> float:
        return self.width_m / M_PER_FT

    @property
    def divided(self) -> bool:
        """An inner strip narrower than the lanes either side of it is a divider; outer narrow
        strips are footpaths."""
        gaps = [b - a for a, b in zip(self.lines_m, self.lines_m[1:], strict=False)]
        return any(
            gaps[i] <= DIVIDER_MAX_M and gaps[i - 1] > gaps[i] < gaps[i + 1]
            for i in range(1, len(gaps) - 1)
        )

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "drawn_width_m": round(self.width_m, 2),
            "drawn_width_ft": round(self.width_ft, 1),
            "edge_lines_m": [round(v, 2) for v in self.lines_m],
            "divided": self.divided,
            "distance_from_plot_m": round(self.distance_m, 2),
            "note": "As drawn: may be the carriageway alone. Confirm the legal road width.",
        }


@dataclass(frozen=True)
class _Section:
    angle: float
    crossings: tuple[tuple[Point, int], ...]  # where each edge line was crossed, and by which piece


def _angle(line: LineString) -> float:
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180


def _angle_gap(a: float, b: float) -> float:
    d = abs(a - b) % 180
    return min(d, 180 - d)


def _normal(angle: float) -> tuple[float, float]:
    rad = math.radians(angle)
    return -math.sin(rad), math.cos(rad)


def _pieces(roads: tuple[LineString, ...]) -> list[LineString]:
    pieces = []
    for road in roads:
        coords = list(road.coords)
        for a, b in zip(coords, coords[1:], strict=False):
            if math.dist(a, b) >= MIN_PIECE_M:
                pieces.append(LineString([a, b]))
    return pieces


def _section(i: int, point: Point, pieces, angles, tree) -> _Section | None:
    """The edge lines crossed by a line laid across piece i at point, kept to the run of lines
    around piece i with no gap wider than a lane."""
    nx, ny = _normal(angles[i])
    ux, uy = ny, -nx  # along the road
    ray = LineString([(point.x - nx * CROSS_M, point.y - ny * CROSS_M),
                      (point.x + nx * CROSS_M, point.y + ny * CROSS_M)])
    crossings = [(0.0, point, i)]
    for j in tree.query(ray.buffer(WINDOW_M, cap_style="flat")):
        if j == i or _angle_gap(angles[i], angles[j]) > PARALLEL_DEG:
            continue
        hit = ray.intersection(pieces[j])
        if hit.geom_type == "Point":
            crossings.append(((hit.x - point.x) * nx + (hit.y - point.y) * ny, hit, int(j)))
        elif pieces[j].length <= 2 * WINDOW_M:  # a dot or dash beside the line, not across it
            mid = pieces[j].centroid
            dx, dy = mid.x - point.x, mid.y - point.y
            if abs(dx * ux + dy * uy) <= WINDOW_M:
                across = dx * nx + dy * ny
                spot = Point(point.x + nx * across, point.y + ny * across)
                crossings.append((across, spot, int(j)))
    crossings.sort(key=lambda c: c[0])
    lo = hi = next(k for k, c in enumerate(crossings) if c[2] == i)
    while lo > 0 and crossings[lo][0] - crossings[lo - 1][0] <= LANE_GAP_M:
        lo -= 1
    while hi < len(crossings) - 1 and crossings[hi + 1][0] - crossings[hi][0] <= LANE_GAP_M:
        hi += 1
    run = crossings[lo:hi + 1]
    if len(run) < 2 or run[-1][0] - run[0][0] < MIN_WIDTH_M:
        return None
    return _Section(angles[i], tuple((p, j) for _, p, j in run))


def _sections(survey: Survey) -> tuple[list[LineString], list[_Section]]:
    pieces = _pieces(survey.roads)
    if not pieces:
        return pieces, []
    angles = [_angle(p) for p in pieces]
    tree = STRtree(pieces)
    plot, ring = survey.boundary, survey.boundary.exterior
    sections = []
    for i, piece in enumerate(pieces):
        if piece.length < MIN_SAMPLED_PIECE_M:
            continue
        for k in range(max(1, int(piece.length // STEP_M))):
            point = piece.interpolate(min((k + 0.5) * STEP_M, piece.length))
            if plot.contains(point) or ring.distance(point) > REACH_M:
                continue
            section = _section(i, point, pieces, angles, tree)
            if section is not None:
                sections.append(section)
    return pieces, sections


def _group(sections: list[_Section]) -> list[tuple[float, list[_Section]]]:
    """Cross-sections of one road share its direction and overlap across it."""
    groups: list[tuple[float, list[_Section], list[float]]] = []
    for s in sections:
        for angle, members, span in groups:
            if _angle_gap(s.angle, angle) > PARALLEL_DEG:
                continue
            nx, ny = _normal(angle)
            across = [p.x * nx + p.y * ny for p, _ in s.crossings]
            if min(across) <= span[1] + SAME_LINE_M and max(across) >= span[0] - SAME_LINE_M:
                members.append(s)
                span[0], span[1] = min(span[0], min(across)), max(span[1], max(across))
                break
        else:
            nx, ny = _normal(s.angle)
            across = [p.x * nx + p.y * ny for p, _ in s.crossings]
            groups.append((s.angle, [s], [min(across), max(across)]))
    return [(angle, members) for angle, members, _ in groups]


def _road(angle: float, members: list[_Section], pieces, survey: Survey) -> Road | None:
    nx, ny = _normal(angle)
    marks = sorted(
        (p.x * nx + p.y * ny, n, j)
        for n, s in enumerate(members) for p, j in s.crossings
    )
    lines: list[list[tuple[float, int, int]]] = []
    for mark in marks:
        if lines and mark[0] - lines[-1][-1][0] <= SAME_LINE_M:
            lines[-1].append(mark)
        else:
            lines.append([mark])
    needed = max(2, MIN_SHARE * len(members))
    kept = [line for line in lines if len({n for _, n, _ in line}) >= needed]
    if len(kept) < 2:
        return None
    across = [median(v for v, _, _ in line) for line in kept]
    width = across[-1] - across[0]
    if width < MIN_WIDTH_M:
        return None
    edges = [pieces[j] for line in kept for _, _, j in line]
    plot = survey.boundary
    distance = min(plot.distance(e) for e in edges)
    # Where the road passes closest: along a road beside a whole side every piece is about
    # equally near, so take the middle of that stretch rather than whichever piece comes first.
    closest = unary_union([e for e in edges if plot.distance(e) <= distance + 1.0]).centroid
    centre = plot.centroid
    bearing = math.degrees(math.atan2(closest.x - centre.x, closest.y - centre.y)) % 360
    drawn = tuple(pieces[j] for j in dict.fromkeys(j for line in kept for _, _, j in line))
    return Road(
        width_m=width,
        lines_m=tuple(v - across[0] for v in across),
        distance_m=distance,
        edges=drawn,
        area=_between(drawn, angle, across[0], across[-1]),
        side=_COMPASS[round(bearing / 45) % 8],
        direction_deg=angle,
        sections=len(members),
    )


def _between(edges: tuple[LineString, ...], angle: float, low: float, high: float) -> Polygon:
    """The ground between the road's outermost edge lines, as far along it as they are drawn."""
    nx, ny = _normal(angle)
    ux, uy = ny, -nx  # along the road
    along = [x * ux + y * uy for edge in edges for x, y in edge.coords]
    start, end = min(along), max(along)
    return Polygon([(t * ux + s * nx, t * uy + s * ny)
                    for t, s in ((start, low), (end, low), (end, high), (start, high))])


def roads_near(survey: Survey) -> tuple[Road, ...]:
    """Every road within REACH_M of the plot, nearest first, measured across itself."""
    pieces, sections = _sections(survey)
    roads = [_road(angle, members, pieces, survey) for angle, members in _group(sections)]
    found = [r for r in roads if r is not None and r.distance_m <= REACH_M]
    return tuple(sorted(found, key=lambda r: (r.distance_m, -r.width_m)))
