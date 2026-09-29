"""Surface parking bays and the entry / exit gates.

Rule 13(b)(iii) puts surface parking in "the open space over and above the setbacks", so bays
are laid inside the setback envelope, on whatever is left after the towers, the amenities
block and the tot-lot; never in the setback band, where only the drive runs. Bays are laid in
rows aligned with the towers, with an aisle between rows, so they read like a parked row and
not like a carpet of rectangles.
"""

from __future__ import annotations

from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from siteplan import rules

BAY_WIDTH_M = 2.5
BAY_DEPTH_M = 5.0
AISLE_M = 6.0
MAX_BAYS = 600  # a site plan stops being readable long before this
EPS_M = 0.01


def bay_area_sqm(bays: int) -> float:
    return bays * BAY_WIDTH_M * BAY_DEPTH_M


def surface_bays(free, angle_deg: float, limit: int = MAX_BAYS) -> list[Polygon]:
    """Bays filling the free area, in rows running along the towers."""
    bays: list[Polygon] = []
    for area in _parts(free):
        if area.area < BAY_WIDTH_M * BAY_DEPTH_M:
            continue
        turned = rotate(area, -angle_deg, origin="centroid")
        minx, miny, maxx, maxy = turned.bounds
        y = miny
        while y + BAY_DEPTH_M <= maxy + EPS_M and len(bays) < limit:
            x = minx
            while x + BAY_WIDTH_M <= maxx + EPS_M and len(bays) < limit:
                bay = box(x, y, x + BAY_WIDTH_M, y + BAY_DEPTH_M)
                if turned.contains(bay):
                    bays.append(rotate(bay, angle_deg, origin=area.centroid))
                x += BAY_WIDTH_M
            y += BAY_DEPTH_M + AISLE_M
    return bays


def free_for_parking(envelope: Polygon, towers, club: Polygon | None, tot_lot) -> Polygon:
    """What is left inside the setbacks once the buildings and the tot-lot have their land."""
    taken = [t.footprint for t in towers] + list(tot_lot)
    if club is not None:
        taken.append(club)
    return envelope.difference(unary_union(taken)) if taken else envelope


def gates(plot: Polygon, frontage: LineString, depth_m: float) -> list[tuple[str, Polygon]]:
    """An entry and an exit on the frontage, cut through the setback band to the drive."""
    inward = _inward(plot, frontage)
    out: list[tuple[str, Polygon]] = []
    for name, position in (("ENTRY", 1 / 3), ("EXIT", 2 / 3)):
        centre = frontage.interpolate(position, normalized=True)
        along = _unit(frontage)
        half = rules.GATE_MIN_WIDTH_M / 2
        corners = [
            (centre.x - along[0] * half, centre.y - along[1] * half),
            (centre.x + along[0] * half, centre.y + along[1] * half),
            (centre.x + along[0] * half + inward[0] * depth_m,
             centre.y + along[1] * half + inward[1] * depth_m),
            (centre.x - along[0] * half + inward[0] * depth_m,
             centre.y - along[1] * half + inward[1] * depth_m),
        ]
        gate = Polygon(corners)
        if gate.is_valid and not gate.is_empty:
            out.append((name, gate))
    return out


def _parts(shape) -> list[Polygon]:
    if shape is None or shape.is_empty:
        return []
    return [shape] if isinstance(shape, Polygon) else [p for p in shape.geoms]


def _unit(line: LineString) -> tuple[float, float]:
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 or 1.0
    return ((x1 - x0) / length, (y1 - y0) / length)


def _inward(plot: Polygon, frontage: LineString) -> tuple[float, float]:
    """The direction from the frontage towards the middle of the site."""
    along = _unit(frontage)
    normal = (-along[1], along[0])
    middle = frontage.interpolate(0.5, normalized=True)
    probe = Polygon(plot).representative_point()
    if (probe.x - middle.x) * normal[0] + (probe.y - middle.y) * normal[1] < 0:
        return (-normal[0], -normal[1])
    return normal
