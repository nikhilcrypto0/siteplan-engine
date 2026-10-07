"""Fitting a rectangle into free ground, and carving open space out of it.

`fit_rectangle` finds the place nearest an anchor that holds a whole rectangle, at one of the given
turns. Every position of a grid is tried at once; only the winner is built as a shape. `pockets_in`
cuts ground into the pieces the open-space rule counts: at least `min_width_m` across and
`min_sqm` in area, so a piece drawn from it is whole open space and never a part of one.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
import shapely
from shapely.affinity import rotate
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.geometry import opening
from siteplan.optimizer.search.land import polygons

SCAN_STEP_M = 2.0
EPS_M = 0.01
TRIM_ABOVE = 1.2  # a pocket this much bigger than what is still needed is cut down
TRIM_MARGIN = 1.02  # and cut a little over, so rounding never leaves the open space short
TRIM_WIDE_SHARE = 0.98  # the piece cut keeps this share of itself at the full width, or is dropped


def fit_rectangle(room: BaseGeometry, width_m: float, depth_m: float, turns_deg: Sequence[float],
                  anchor: Point | None = None, step_m: float = SCAN_STEP_M) -> Polygon | None:
    """The rectangle (width x depth, turned to each of `turns_deg` and a quarter turn from it)
    that lies wholly in the room, nearest the anchor; None when none does."""
    best: tuple[float, Polygon] | None = None
    area = width_m * depth_m
    for turn in sorted({round(t % 180, 6) for angle in turns_deg for t in (angle, angle + 90)}):
        for part in polygons(room):
            if part.area < area:
                continue
            origin = part.centroid
            turned = rotate(part, -turn, origin=origin)
            minx, miny, maxx, maxy = turned.bounds
            xs = _steps(minx + EPS_M, maxx - width_m - EPS_M, step_m)
            ys = _steps(miny + EPS_M, maxy - depth_m - EPS_M, step_m)
            if not xs or not ys:
                continue
            x0, y0 = (a.ravel() for a in np.meshgrid(xs, ys))
            boxes = shapely.box(x0, y0, x0 + width_m, y0 + depth_m)
            shapely.prepare(turned)
            fits = shapely.contains(turned, boxes)
            if not fits.any():
                continue
            cx, cy = x0[fits] + width_m / 2, y0[fits] + depth_m / 2
            radians = math.radians(turn)
            dx, dy = cx - origin.x, cy - origin.y
            ux = origin.x + dx * math.cos(radians) - dy * math.sin(radians)
            uy = origin.y + dx * math.sin(radians) + dy * math.cos(radians)
            scores = np.hypot(ux - anchor.x, uy - anchor.y) if anchor is not None else np.zeros(
                len(ux))
            pick = int(np.argmin(scores))
            if best is None or scores[pick] < best[0]:
                best = (float(scores[pick]), rotate(boxes[fits][pick], turn, origin=origin))
    return best[1] if best else None


def _steps(low: float, high: float, step: float) -> list[float]:
    if high < low:
        return []
    count = int((high - low) / step)
    return [low + i * step for i in range(count + 1)] + [high]


def pockets_in(room: BaseGeometry, min_width_m: float, min_sqm: float) -> list[Polygon]:
    """The pieces of ground the open-space rule counts: wide enough everywhere and big enough. The
    width is taken a hair over, so a piece never measures a hair under."""
    if room.is_empty:
        return []
    # GEOS raises a floating-point flag on a mitre round a sliver of ground (a corner with no
    # width); numpy turns that into a warning although the piece it returns is sound, and the
    # validator measures every pocket again, so the flag is left unreported here.
    with np.errstate(divide="ignore", invalid="ignore"):
        usable = opening(room, min_width_m + 2 * EPS_M).intersection(room)
    return [p for p in polygons(usable) if p.area >= min_sqm + EPS_M]


def choose_pockets(room: BaseGeometry, target_sqm: float, min_width_m: float, min_sqm: float,
                   turn_deg: float = 0.0, value: Callable[[BaseGeometry], float] | None = None
                   ) -> tuple[list[Polygon], float]:
    """The most valuable pockets first (`value`; the biggest first without one, and between
    equals), until the target is met; the last is cut down to what is still needed, from its more
    valuable end, so the rest of it stays free for the facilities."""
    chosen: list[Polygon] = []
    total = 0.0
    found = pockets_in(room, min_width_m, min_sqm)
    for pocket in sorted(found, key=lambda p: (-value(p) if value else 0.0, -p.area)):
        if total >= target_sqm:
            break
        still = target_sqm - total
        if pocket.area > still * TRIM_ABOVE:
            pocket = _trim(pocket, still * TRIM_MARGIN, turn_deg, min_width_m, min_sqm,
                           value) or pocket
        chosen.append(pocket)
        total += pocket.area
    return chosen, total


def _trim(pocket: Polygon, area: float, turn_deg: float, min_width_m: float, min_sqm: float,
          value: Callable[[BaseGeometry], float] | None = None) -> Polygon | None:
    """The end of a pocket holding `area`, cut square to the turn, when that piece is still a
    pocket the rule counts: its low end, or with `value` whichever end is worth more (the low one
    between equals)."""
    if area < min_sqm + EPS_M:
        return None
    turned = rotate(pocket, -turn_deg, origin=(0, 0))
    ends = (True, False) if value else (True,)
    pieces = [rotate(piece, turn_deg, origin=(0, 0))
              for piece in (_end(turned, area, low) for low in ends)
              if piece is not None and _counts(piece, area, min_width_m, min_sqm)]
    if not pieces:
        return None
    return max(pieces, key=value) if value else pieces[0]


def _end(turned: Polygon, area: float, low: bool) -> Polygon | None:
    """The piece holding `area` at one end of a pocket (in the turn's frame), cut across its long
    side, never along it."""
    minx, miny, maxx, maxy = turned.bounds
    along_x = maxx - minx >= maxy - miny

    def keep(at: float) -> BaseGeometry:
        if low:
            cut = Polygon([(minx - 1, miny - 1), (at, miny - 1), (at, maxy + 1),
                           (minx - 1, maxy + 1)]) if along_x else Polygon(
                [(minx - 1, miny - 1), (maxx + 1, miny - 1), (maxx + 1, at), (minx - 1, at)])
        else:
            cut = Polygon([(at, miny - 1), (maxx + 1, miny - 1), (maxx + 1, maxy + 1),
                           (at, maxy + 1)]) if along_x else Polygon(
                [(minx - 1, at), (maxx + 1, at), (maxx + 1, maxy + 1), (minx - 1, maxy + 1)])
        return turned.intersection(cut)

    first, last = (minx, maxx) if along_x else (miny, maxy)
    short, enough = (first, last) if low else (last, first)  # the end holds too little, enough
    for _ in range(40):
        middle = (short + enough) / 2
        if keep(middle).area < area:
            short = middle
        else:
            enough = middle
    parts = polygons(keep(enough))
    return max(parts, key=lambda p: p.area) if parts else None


def _counts(piece: Polygon, area: float, min_width_m: float, min_sqm: float) -> bool:
    """Whether a piece cut holds what was asked and is still a pocket the rule counts."""
    if piece.area < area / TRIM_MARGIN or piece.area < min_sqm:
        return False
    return opening(piece, min_width_m + 2 * EPS_M).area >= piece.area * TRIM_WIDE_SHARE
