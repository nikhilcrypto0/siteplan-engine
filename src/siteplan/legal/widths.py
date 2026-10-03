"""How wide a piece of land is, region by region: reported, never judged.

The land is split where it narrows below REGION_SPLIT_M into a wide body and the narrow parts
(an arm, a tapering tail), and each region says its area, the widest circle that fits inside it
and its length. `area_narrower_than` says how much land is narrower than each of a set of widths.
Whether a narrow region can take a small tower, a low block or a club house is the optimizer's
question: nothing here removes land for being narrow, and no region is classed as unusable.

A width is read with a disk. The land is eroded by half the width (every point a disk of that
width fits round), then grown back with square corners: a right-angle corner of the plot is kept,
which a round regrowth would shave, while a tail that tapers is cut where it narrows below the
width, which an opening with square corners everywhere would not do (it grows a wedge back to its
tip).
"""

from __future__ import annotations

import math

from shapely.geometry import Polygon
from shapely.ops import polylabel, unary_union

from siteplan.contracts.common import Shape, shapes_from
from siteplan.contracts.envelope import WidthProfile, WidthRegion

REGION_SPLIT_M = 30.0  # land narrower than this is a region of its own (about a tower's depth)
REPORTED_WIDTHS_M = (10.0, 15.0, 20.0, 25.0, 30.0)  # the widths `area_narrower_than` reports
MIN_REGION_SQM = 1.0  # smaller pieces are drawing dust, not regions
HAIRLINE_M = 0.01  # a strip this thin, left where two outlines nearly coincide, is not land
MITRE_LIMIT = 2.0  # corners sharper than 60 degrees are cut where the land is regrown
CENTRE_TOLERANCE_M = 0.05  # how finely the widest circle's centre is found


def wide_part(land, width_m: float):
    """The part of the land at least width_m wide (see the module note)."""
    core = land.buffer(-width_m / 2, join_style="mitre")
    if core.is_empty:
        return Polygon()
    return core.buffer(width_m / 2, join_style="mitre", mitre_limit=MITRE_LIMIT
                       ).intersection(land)


def width_profile(applies_to: str, land) -> WidthProfile:
    """The land's regions and how much of it is narrower than each reported width. `land` is a
    shapely polygon or multipolygon (empty land has no regions)."""
    wide = wide_part(land, REGION_SPLIT_M)
    pieces = [*_polygons(wide), *_polygons(land.difference(wide))]
    regions = [_region(piece) for piece in sorted(pieces, key=lambda p: -p.area)]
    narrower = [(width, max(0.0, land.area - wide_part(land, width).area))
                for width in REPORTED_WIDTHS_M]
    return WidthProfile(applies_to=applies_to, regions=regions, area_narrower_than=narrower)


def _polygons(geometry) -> list[Polygon]:
    """The pieces of area in a geometry, with the hairlines a difference of near-coincident
    outlines leaves along the boundary opened away."""
    land = unary_union([shape.to_shapely() for shape in shapes_from(geometry)])
    opened = land.buffer(-HAIRLINE_M, join_style="mitre").buffer(HAIRLINE_M, join_style="mitre")
    return [piece for shape in shapes_from(opened)
            if (piece := shape.to_shapely()).area >= MIN_REGION_SQM]


def _region(piece: Polygon) -> WidthRegion:
    centre = polylabel(piece, tolerance=CENTRE_TOLERANCE_M)
    return WidthRegion(shape=Shape.from_shapely(piece), area_sqm=piece.area,
                       max_inscribed_width_m=2 * piece.boundary.distance(centre),
                       length_m=_length(piece))


def _length(piece: Polygon) -> float:
    """The long side of the region's smallest bounding rectangle: each edge of its convex hull
    gives a direction to try, and the rectangle of least area wins."""
    hull = list(piece.convex_hull.exterior.coords)[:-1]
    best_area, best_long = math.inf, 0.0
    for (x0, y0), (x1, y1) in zip(hull, [*hull[1:], hull[0]], strict=True):
        edge = math.hypot(x1 - x0, y1 - y0)
        if edge == 0:
            continue
        ux, uy = (x1 - x0) / edge, (y1 - y0) / edge
        along = [x * ux + y * uy for x, y in hull]
        across = [y * ux - x * uy for x, y in hull]
        a, b = max(along) - min(along), max(across) - min(across)
        if a * b < best_area:
            best_area, best_long = a * b, max(a, b)
    return best_long
