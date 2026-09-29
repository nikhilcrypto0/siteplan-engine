"""What a site needs besides towers: a club house block and a drive around the buildings.

Both are reserved before any tower is placed, because on a real site plan they take the
land first. The club house sits inside the setback envelope, so it is subtracted from the
land the solver may build on. The driveway runs in the setback band outside the envelope,
which is where the studied drawings put it and where the rules allow it (ramps are the
exception: rule 13(c)(vii) keeps those out of the mandatory setbacks).
"""

from __future__ import annotations

from math import sqrt

from shapely.affinity import rotate
from shapely.geometry import Polygon, box

from siteplan.geometry import straight_runs

CLUB_ASPECT = 1.6  # a hall a bit longer than it is deep
SCAN_STEP_M = 2.0
SPREAD_M = 20.0  # candidates closer together than this are the same idea
EPS_M = 0.01


def club_house(envelope: Polygon, area_sqm: float) -> Polygon | None:
    """The edge-hugging position for the amenities block; None when it does not fit."""
    positions = club_house_options(envelope, area_sqm, limit=1)
    return positions[0] if positions else None


def club_house_options(envelope: Polygon, area_sqm: float, limit: int = 6) -> list[Polygon]:
    """Candidate positions for the amenities block, aligned with the site's longest edges and
    furthest from the middle first. The solver picks between them by what they cost in towers,
    which the shape of the site decides, not the distance from the centre."""
    if area_sqm <= 0 or envelope.is_empty:
        return []
    runs = sorted(straight_runs(envelope), key=lambda r: -r.length)
    angles = [run.angle_deg for run in runs[:2]] or [0.0]
    depth = sqrt(area_sqm / CLUB_ASPECT)
    width = area_sqm / depth
    found: list[tuple[float, Polygon]] = []
    for angle in angles:
        turned = rotate(envelope, -angle, origin="centroid")
        centre = turned.centroid
        # Inset by a hair: a block sitting exactly on the envelope edge is still inside the
        # setback, but floating-point equality on the boundary makes `contains` unreliable.
        minx, miny, maxx, maxy = turned.bounds
        minx, miny = minx + EPS_M, miny + EPS_M
        maxx, maxy = maxx - EPS_M - width, maxy - EPS_M - depth
        for x0 in _steps(minx, maxx):
            for y0 in _steps(miny, maxy):
                block = box(x0, y0, x0 + width, y0 + depth)
                if not turned.contains(block):
                    continue
                # Away from the middle first: the centre of a site is worth more as towers.
                found.append((block.centroid.distance(centre),
                              rotate(block, angle, origin=envelope.centroid)))

    found.sort(key=lambda pair: -pair[0])
    spread: list[Polygon] = []
    seen: set[tuple[int, int]] = set()
    for _, block in found:
        cell = (int(block.centroid.x // SPREAD_M), int(block.centroid.y // SPREAD_M))
        if cell in seen:
            continue
        seen.add(cell)
        spread.append(block)
        if len(spread) == limit:
            break
    return spread


def _steps(low: float, high: float, step: float = SCAN_STEP_M) -> list[float]:
    if high < low:
        return []
    count = int((high - low) / step)
    return [low + i * step for i in range(count + 1)] + [high]


def driveway_ring(plot: Polygon, envelope: Polygon, width_m: float) -> Polygon | None:
    """A drive of *width_m* running around the buildings, between the setback envelope and
    the plot boundary. None when the setback is too shallow to hold it."""
    if width_m <= 0 or envelope.is_empty:
        return None
    ring = envelope.buffer(width_m, join_style="mitre").intersection(plot).difference(envelope)
    if ring.is_empty or ring.area <= 0:
        return None
    return ring
