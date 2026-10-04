"""Towers: slab blocks built from the flat library, laid in columns with roads between them.

In a frame turned so the towers' long axis runs along y, columns of towers are laid across the
towers' land at a pitch of one tower depth plus one corridor. The corridor between two columns
is a 9 m internal road (rule 8(m)) running from the loop road to the loop road, so it is never a
dead end, and it is at least the Table IV gap between the blocks. Towers in one column are also
a corridor apart, which keeps the fire band round each of them clear.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import Polygon, box

from siteplan.access import ROAD_M, RoadPiece
from siteplan.geometry import angle_gap, straight_runs
from siteplan.library import FlatLibrary, FlatType
from siteplan.prototypes.compose import MixTracker  # the mix rule moved with the composer

EPS_M = 0.01
TOUCH_M = 0.5  # a tower this close to a road opens onto it


@dataclass(frozen=True)
class Tower:
    name: str
    footprint: Polygon
    flats_per_side: tuple[FlatType, ...]  # along one side; the other side mirrors it
    flat_outlines: tuple[Polygon, ...]
    cores: tuple[Polygon, ...]
    column: int = 0  # which column of the layout it stands in

    def flats_per_floor(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for flat in self.flats_per_side:
            counts[flat.bhk] = counts.get(flat.bhk, 0) + 2
        return counts

    def saleable_sqft_per_floor(self) -> float:
        """The flats' own sale areas from the library, both sides of the corridor."""
        return 2 * sum(f.saleable_sqft for f in self.flats_per_side)

    @property
    def length_m(self) -> float:
        """The long side of the block (a footprint is a rectangle, drawn corner to corner)."""
        corners = list(self.footprint.exterior.coords)
        return max(math.dist(corners[0], corners[1]), math.dist(corners[1], corners[2]))

    @property
    def width_m(self) -> float:
        """The short side of the block: two flats deep and the corridor between them."""
        corners = list(self.footprint.exterior.coords)
        return min(math.dist(corners[0], corners[1]), math.dist(corners[1], corners[2]))

    def detail(self, floors: int) -> dict:
        """What an architect asks of a block: its size, flats per floor and cores."""
        per_floor = sum(self.flats_per_floor().values())
        cores = len(self.cores)
        return {"name": self.name, "length_m": round(self.length_m, 1),
                "width_m": round(self.width_m, 1), "floors_above_stilt": floors,
                "flats_per_floor": per_floor, "flats_per_floor_by_type": self.flats_per_floor(),
                "cores": cores, "flats_per_core_per_floor": round(per_floor / cores, 1)
                if cores else 0, "flats": per_floor * floors}


@dataclass(frozen=True)
class Placement:
    angle_deg: float
    towers: tuple[Tower, ...]
    columns: tuple[float, ...]  # x of each column's left edge, in the turned frame
    depth_m: float
    corridor_m: float

    def without(self, dropped: Tower) -> Placement:
        return Placement(self.angle_deg, tuple(t for t in self.towers if t is not dropped),
                         self.columns, self.depth_m, self.corridor_m)


def orientations(plot: Polygon) -> list[float]:
    """Tower directions worth trying: along and across the plot's three longest edges."""
    angles: list[float] = []
    for run in sorted(straight_runs(plot), key=lambda r: -r.length)[:3]:
        for angle in (run.angle_deg, (run.angle_deg + 90) % 180):
            if all(angle_gap(angle, other) > 5 for other in angles):
                angles.append(angle)
    return angles


def _parts(geometry) -> list[Polygon]:
    parts = getattr(geometry, "geoms", [geometry])
    return [p for p in parts if isinstance(p, Polygon) and not p.is_empty]


def free_stretches(envelope, x0: float, width: float) -> list[tuple[float, float]]:
    """Y-ranges where a full-width strip [x0, x0 + width] lies inside the envelope.

    Exact for axis-aligned rectangles: anything of the strip outside the envelope blocks
    its whole y-range, because a tower spans the strip's full width."""
    _, miny, _, maxy = envelope.bounds
    strip = box(x0, miny - 1, x0 + width, maxy + 1)
    blocked = sorted((p.bounds[1], p.bounds[3]) for p in _parts(strip.difference(envelope)))
    stretches, y = [], miny - 1
    for lo, hi in blocked:
        if lo > y:
            stretches.append((y, lo))
        y = max(y, hi)
    if y < maxy + 1:
        stretches.append((y, maxy + 1))
    return [(a, b) for a, b in stretches if b - a > 0]


def tower_length(flats: list[FlatType], library: FlatLibrary) -> float:
    cores = math.ceil(len(flats) / library.flats_per_core_per_side)
    return sum(f.width_m for f in flats) + cores * library.core_width_m


def compose_tower(available_m: float, library: FlatLibrary, mix: MixTracker,
                  min_per_side: int, max_cores: int | None = None) -> list[FlatType] | None:
    """Flats along one side of a block that fits the length available, and, when asked, no
    more of them than max_cores cores serve (flats_per_core_per_side each)."""
    flats: list[FlatType] = []
    pending: dict[str, int] = {}
    most = None if max_cores is None else max_cores * library.flats_per_core_per_side
    while most is None or len(flats) < most:
        for flat in mix.next_choices(library, pending):
            if tower_length([*flats, flat], library) <= available_m + 1e-9:
                flats.append(flat)
                pending[flat.bhk] = pending.get(flat.bhk, 0) + 2
                break
        else:
            break
    if len(flats) < min_per_side:
        return None
    for bhk, n in pending.items():
        mix.counts[bhk] = mix.counts.get(bhk, 0) + n
    return flats


def build_tower(name: str, x0: float, y0: float, flats: list[FlatType], library: FlatLibrary,
                alpha: float, column: int = 0) -> Tower:
    """Lay out one tower in the turned frame, then turn it back onto the site."""
    depth = flats[0].depth_m
    width = library.tower_depth_m
    k = library.flats_per_core_per_side
    groups = [flats[i: i + k] for i in range(0, len(flats), k)]
    outlines, cores, y = [], [], y0
    for group in groups:
        half = math.ceil(len(group) / 2)
        for position, flat in enumerate(group):
            if position == half:
                cores.append(box(x0, y, x0 + width, y + library.core_width_m))
                y += library.core_width_m
            outlines.append(box(x0, y, x0 + depth, y + flat.width_m))
            outlines.append(box(x0 + width - depth, y, x0 + width, y + flat.width_m))
            y += flat.width_m
        if half >= len(group):
            cores.append(box(x0, y, x0 + width, y + library.core_width_m))
            y += library.core_width_m

    def back(p: Polygon) -> Polygon:
        return affinity.rotate(p, -alpha, origin=(0, 0))

    return Tower(name=name, footprint=back(box(x0, y0, x0 + width, y)),
                 flats_per_side=tuple(flats), flat_outlines=tuple(back(p) for p in outlines),
                 cores=tuple(back(p) for p in cores), column=column)


def place(envelope, angle: float, offset: float, library: FlatLibrary,
          unit_mix: dict[str, float], min_per_side: int, corridor_m: float,
          max_length_m: float | None, max_cores: int | None = None) -> Placement:
    """Columns of towers across the envelope, a corridor apart, filling each free stretch."""
    alpha = 90 - angle  # turn the site so the towers' long axis runs along y
    turned = affinity.rotate(envelope, alpha, origin=(0, 0))
    minx, _, maxx, _ = turned.bounds
    width = library.tower_depth_m
    mix = MixTracker(unit_mix)
    towers: list[Tower] = []
    columns: list[float] = []
    x = minx + offset
    while x + width <= maxx + 1e-9:
        column = len(columns)
        columns.append(x)
        for lo, hi in free_stretches(turned, x, width):
            y = lo
            while hi - y > 0:
                available = hi - y if max_length_m is None else min(hi - y, max_length_m)
                flats = compose_tower(available, library, mix, min_per_side, max_cores)
                if flats is None:
                    break
                towers.append(build_tower(f"T{len(towers) + 1}", x, y, flats, library, alpha,
                                          column))
                y += tower_length(flats, library) + corridor_m + EPS_M
        x += width + corridor_m + EPS_M
    return Placement(angle, tuple(towers), tuple(columns), width, corridor_m)


def corridor_roads(placement: Placement, envelope, loop) -> list[RoadPiece]:
    """A 9 m internal road in the corridor between every two neighbouring columns that hold
    towers, from the loop to the loop; and beside a column whose towers no other road reaches."""
    alpha = 90 - placement.angle_deg
    turned = affinity.rotate(envelope, alpha, origin=(0, 0))
    _, miny, _, maxy = turned.bounds
    used = sorted({t.column for t in placement.towers})
    strips: list[Polygon] = []

    def strip(x_left: float) -> list[Polygon]:
        cut = box(x_left, miny - 1, x_left + placement.corridor_m, maxy + 1).intersection(turned)
        return [affinity.rotate(p, -alpha, origin=(0, 0)) for p in _parts(cut)
                if p.area > ROAD_M * ROAD_M / 4]

    for left, right in zip(used, used[1:], strict=False):
        if right == left + 1:
            strips += strip(placement.columns[left] + placement.depth_m)
    served = [*strips, *_parts(loop)]
    for column in used:
        members = [t for t in placement.towers if t.column == column]
        if all(any(t.footprint.distance(s) <= TOUCH_M for s in served) for t in members):
            continue
        x = placement.columns[column]
        for extra in (strip(x + placement.depth_m), strip(x - placement.corridor_m)):
            if extra:
                strips += extra
                served += extra
                break
    return [RoadPiece("internal", s, ROAD_M) for s in strips]
