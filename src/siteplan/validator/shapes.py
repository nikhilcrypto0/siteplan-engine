"""Geometry the validator measures with, built here so a mistake in the generator's geometry
cannot also be a mistake in the check that is meant to catch it.

Everything is plain shapely on metres: no tower, road or fire-lane logic, only shapes.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel, unary_union
from shapely.validation import explain_validity, make_valid

from siteplan.contracts.common import Shape

EPS_M = 0.01  # a centimetre: below this a drawn edge and its neighbour are the same edge
GRID_M = 1e-6  # shapes are snapped to a micrometre grid: edges drawn to be shared are shared
FLAW_SQM = 1e-4  # a shape mended by less than this (a pinch of float noise) is not a defect
OPENING_SLACK_M = 0.01  # a part this close to the width asked is that wide: a road drawn as
# chords of an arc is a centimetre narrower than the arc it stands for
BEND_RATIO = 1.05  # a strip longer along its middle than its box by this share is bent
NOISE_SQM = 0.5  # less than this of overlap is drawing noise, not a car, a wall or a lane
EDGE_REACH_M = 0.5  # a shape this close to a plot's edge stands in it


def polygons_of(geometry: BaseGeometry | None) -> list[Polygon]:
    """Every polygon in a geometry (a polygon, a multipolygon or a collection); lines, points
    and empty parts are dropped."""
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    return [p for part in getattr(geometry, "geoms", ()) for p in polygons_of(part)]


def union_of_all(geometries) -> BaseGeometry:
    """The union of any number of geometries; empty when there are none."""
    return unary_union([g for g in geometries if g is not None and not g.is_empty])


def snapped(geometry: BaseGeometry) -> BaseGeometry:
    """The geometry on a micrometre grid. Shapes drawn to share an edge (a ring of hardstanding
    round a tower) differ by float noise, which the geometry library's set operations can misread
    (a tower 'on' the ring it only touches); on the grid the shared edge is exactly shared."""
    return shapely.set_precision(geometry, GRID_M)


def mended(geometry: BaseGeometry) -> tuple[BaseGeometry, str]:
    """The geometry as it can be measured, and what was wrong with it ('' when nothing was).
    A shape that crosses itself breaks the geometry library's set operations, so it is rebuilt
    from the ground it encloses, every lobe kept; whoever asks reports the flaw, for a shape
    like that is a defect in the drawing, never something to pass. A pinch of float noise (the
    mending changes the area by less than a square centimetre) is no defect."""
    if geometry.is_valid:
        return snapped(geometry), ""
    repaired = union_of_all(polygons_of(make_valid(geometry)))
    changed = abs(repaired.area - geometry.area) > FLAW_SQM
    return snapped(repaired), explain_validity(geometry) if changed else ""


def bent(shape: BaseGeometry, width_m: float) -> bool:
    """Whether a strip about `width_m` wide runs round a bend (an L, a curve, a switchback that
    folds back on itself): its length along its own middle, which is its area over its width, is
    more than the box round it says. The box is then shorter than the strip."""
    parts = polygons_of(shape)
    if not parts or width_m <= 0:
        return False
    body = max(parts, key=lambda p: p.area)
    long = oriented_box(body)[1]
    return long > 0 and body.area / width_m > BEND_RATIO * long


def mitred(shape: BaseGeometry, distance_m: float) -> BaseGeometry:
    """The shape grown by a distance (shrunk, if negative) with square corners. The geometry
    library's mitre buffer can hand back parts lying inside one another ('nested shells'), which
    break the next set operation; such parts are merged into the one ground they cover."""
    with np.errstate(divide="ignore", invalid="ignore"):  # GEOS notes a collapsed shape
        grown = shape.buffer(distance_m, join_style="mitre")
    if grown.is_valid:
        return grown
    return union_of_all([p if p.is_valid else p.buffer(0) for p in polygons_of(grown)])


def polygon_of(shape: Shape) -> tuple[BaseGeometry, str]:
    """A contract Shape as geometry that can be measured, and what was wrong with it ('' when
    nothing was). A hole too short to be a ring passes the contract but not the geometry library:
    it is dropped; a shape that crosses itself is mended."""
    try:
        return mended(shape.to_shapely())
    except ValueError:
        pass
    holes = [hole for hole in shape.holes if len(hole) >= 3]
    try:
        geometry, flaw = mended(Polygon(shape.outer, holes))
    except ValueError as error:
        return Polygon(), f"not a polygon ({error})"
    return geometry, flaw or "a hole too short to be a ring was dropped"


def opening(shape: BaseGeometry, width_m: float) -> BaseGeometry:
    """The shape without any part narrower than `width_m`: shrunk by half the width and grown
    back. Square (mitre) corners, so a corner that is wide enough on both sides is kept.
    A part within two centimetres of the width is kept: shrunk by exactly half its width a part
    leaves a hairline that the geometry library drops or swells, and a road drawn as chords of
    an arc is a centimetre narrower than the arc, so the shrink stops a centimetre short on each
    side."""
    half = width_m / 2 - OPENING_SLACK_M
    return mitred(mitred(shape, -half), half)


def narrow_part(shape: BaseGeometry, width_m: float) -> BaseGeometry:
    """The parts of a shape narrower than `width_m`."""
    return shape.difference(opening(shape, width_m))


def narrower_than(shape: BaseGeometry, width_m: float) -> bool:
    """Whether any part of the shape worth noticing (more than drawing noise) is thinner than
    `width_m`: a pinch in a long road counts however small a share of the road it is."""
    return narrow_part(shape, width_m).area > NOISE_SQM


def width_in(network: BaseGeometry, part: BaseGeometry, ceiling_m: float) -> float:
    """How wide `part` is as a stretch of `network`: the widest opening of the network that
    keeps all of the part but drawing noise, never above `ceiling_m`. It reads up to two
    centimetres high, the slack `opening` allows, which is what keeps a road drawn exactly as
    wide as the rule asks from reading a hair under it. Measured in the network, so a road's
    end, where it meets another road, is not taken for a narrowing; zero for a part with no
    ground."""
    if part.is_empty or part.area <= 0:
        return 0.0

    def keeps(width: float) -> bool:
        return part.difference(opening(network, width)).area <= NOISE_SQM

    if keeps(ceiling_m):
        return ceiling_m
    low, high = 0.0, ceiling_m
    while high - low > EPS_M / 2:
        mid = (low + high) / 2
        low, high = (mid, high) if keeps(mid) else (low, mid)
    return low


def width_of(shape: BaseGeometry, ceiling_m: float) -> float:
    """How wide a shape is everywhere (to within drawing noise). A road drawn 8.9 m wide measures
    8.9 whatever width it declares."""
    return width_in(shape, shape, ceiling_m)


def healed(shape: BaseGeometry, gap_m: float = 0.05) -> BaseGeometry:
    """The shape with hairline cracks closed: pieces drawn to meet can miss by a hair."""
    return mitred(mitred(shape, gap_m), -gap_m)


def oriented_box(polygon: Polygon) -> tuple[float, float, float]:
    """(angle of the long side in radians, long side, short side) of the smallest rectangle
    round a polygon, found by trying each edge of its convex hull as a side; zeros when the
    polygon has no area."""
    if polygon.is_empty or polygon.area <= 0:
        return 0.0, 0.0, 0.0
    hull = np.array(polygon.convex_hull.exterior.coords)[:-1]
    best: tuple[float, float, float, float] | None = None
    for a, b in zip(hull, np.roll(hull, -1, axis=0), strict=True):
        along = b - a
        length = float(np.hypot(*along))
        if length < 1e-9:
            continue
        u = along / length
        v = np.array([-u[1], u[0]])
        x, y = hull @ u, hull @ v
        width, height = float(x.max() - x.min()), float(y.max() - y.min())
        if best is None or width * height < best[0]:
            angle = math.atan2(u[1], u[0])
            best = (width * height, *((angle, width, height) if width >= height
                                      else (angle + math.pi / 2, height, width)))
    return (best[1], best[2], best[3]) if best else (0.0, 0.0, 0.0)


def sides_of(polygon: Polygon) -> tuple[float, float]:
    """(long, short) side of the smallest rectangle round a polygon."""
    _, long, short = oriented_box(polygon)
    return long, short


def edge_segments(plot: Polygon) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Every straight stretch of a plot's boundary (outer ring and holes), as its two ends."""
    segments = []
    for ring in [plot.exterior, *plot.interiors]:
        coords = list(ring.coords)
        segments += [(a[:2], b[:2]) for a, b in zip(coords, coords[1:], strict=False)
                     if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-9]
    return segments


def _extent_along(shape: BaseGeometry, edge) -> float:
    (x0, y0), (x1, y1) = edge
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    along = [x * ux + y * uy for p in polygons_of(shape) for x, y, *_ in p.exterior.coords]
    return max(along) - min(along)


def width_along_edge(shape: BaseGeometry, plot: Polygon, within_m: float = EDGE_REACH_M) -> float:
    """How far a shape reaches along the stretch of the plot's edge it stands in: a gate's width
    across its opening, however deep it is drawn. A gate at a corner stands in two edges: it lies
    along the one nearer its middle (the other it only touches at an end)."""
    segments = edge_segments(plot)
    if shape.is_empty or not segments:
        return 0.0
    near = [e for e in segments if shape.distance(LineString(e)) <= within_m] or segments
    centre = shape.centroid
    nearest = min(centre.distance(LineString(e)) for e in near)
    along = [e for e in near if centre.distance(LineString(e)) <= nearest + EPS_M]
    return max(_extent_along(shape, e) for e in along)


def end_caps(polygon: Polygon, depth_m: float) -> list[BaseGeometry]:
    """The two ends of a long shape, `depth_m` deep, cut across its long axis."""
    angle, _, _ = oriented_box(polygon)
    turned = rotate(polygon, -angle, origin=(0, 0), use_radians=True)
    minx, miny, maxx, maxy = turned.bounds
    caps = [box(minx - 1, miny - 1, minx + depth_m, maxy + 1),
            box(maxx - depth_m, miny - 1, maxx + 1, maxy + 1)]
    ends = [turned.intersection(c) for c in caps]
    return [rotate(e, angle, origin=(0, 0), use_radians=True) for e in ends if not e.is_empty]


def inscribed_circle(shape: BaseGeometry) -> tuple[float, Point | None]:
    """The radius and centre of the largest circle that fits inside the shape (its widest point);
    (0, None) for a shape with no ground."""
    best, centre = 0.0, None
    for polygon in polygons_of(shape):
        middle = polylabel(polygon, tolerance=0.05)
        radius = polygon.boundary.distance(middle)
        if radius > best:
            best, centre = radius, middle
    return best, centre


def inscribed_radius(shape: BaseGeometry) -> float:
    """The radius of the largest circle that fits inside the shape (its widest point)."""
    return inscribed_circle(shape)[0]


def clean_pieces(geometry: BaseGeometry | None, min_sqm: float = 1e-4) -> list[Polygon]:
    """Polygons of a geometry that are more than a sliver."""
    return [p for p in polygons_of(geometry) if p.area > min_sqm]
