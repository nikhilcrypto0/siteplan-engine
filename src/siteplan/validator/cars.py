"""How many cars physically fit on a parking floor: bays and aisles actually laid out.

A floor is laid out in double-loaded modules (a row of bays, an aisle, a row of bays) with the
bay and aisle sizes the rules give, in the best of a few orientations and offsets. The count is
what fits, not what the floor's area divided by a figure would suggest, so a floor that is mostly
cores, columns or odd corners shows how little of it a car can use.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.validator.shapes import polygons_of

EPS_M = 0.01
EDGE_M = 1e-4  # a tenth of a millimetre
OFFSETS_ALONG = (0.0, 1.25)  # where the first bay of a row starts, from the floor's edge
OFFSETS_ACROSS = (0.0, 2.7, 5.3, 8.0, 10.7, 13.3)  # where the first row starts


def _rows(low: float, high: float, bay_depth: float, aisle: float) -> list[float]:
    """Where rows of bays start across a floor: pairs of rows sharing an aisle, then a single
    row if one more bay and aisle still fit."""
    starts, y = [], low
    while y + bay_depth <= high + EPS_M:
        starts.append(y)
        if y + 2 * bay_depth + aisle <= high + EPS_M:
            starts.append(y + bay_depth + aisle)
            y += 2 * bay_depth + aisle
        else:
            y += bay_depth + aisle
    return starts


def _count(part: Polygon, angle_deg: float, bay: tuple[float, float], aisle: float,
           along: float, across: float) -> int:
    width, depth = bay
    # A bay on the floor's own edge is on the floor, whatever turning it did to the last digit.
    turned = rotate(part, -angle_deg, origin="centroid").buffer(EDGE_M, join_style="mitre")
    minx, miny, maxx, maxy = turned.bounds
    minx, miny, maxx, maxy = minx + EDGE_M, miny + EDGE_M, maxx - EDGE_M, maxy - EDGE_M
    rows = _rows(miny + across, maxy, depth, aisle)
    columns = np.arange(minx + along, maxx - width + EPS_M, width)
    if not rows or not len(columns):
        return 0
    x, y = (a.ravel() for a in np.meshgrid(columns, rows))
    shapely.prepare(turned)
    return int(shapely.contains(turned, shapely.box(x, y, x + width, y + depth)).sum())


def cars_on_floor(floor: BaseGeometry, angles_deg: Sequence[float], bay: tuple[float, float],
                  aisle: float) -> int:
    """The most cars that fit on a floor in any of the given orientations (rows turned to each
    angle and a quarter turn from it), part by part."""
    turns = sorted({round(a % 180, 3) for angle in angles_deg for a in (angle, angle + 90)})
    total = 0
    for part in polygons_of(floor):
        if part.area < bay[0] * bay[1]:
            continue
        total += max(_count(part, angle, bay, aisle, along, across)
                     for angle in turns for along in OFFSETS_ALONG for across in OFFSETS_ACROSS)
    return total
