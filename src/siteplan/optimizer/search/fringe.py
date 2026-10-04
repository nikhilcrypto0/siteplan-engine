"""Blocks below the high-rise height on the ground the ring road leaves (stream C3).

The columns stand inside the ring road (layout.py). What lies between the ring and the plot line
(an arm too narrow for the ring, a corner, the band beyond a short column) is the fringe, and a
block below 21 m may stand there wherever its own band's land allows: its Table III setback from
the sides and its Building Line from the stretches facing the access road (land.setback_land), out
of the water buffer and the ground kept for the open space, off the ring road, and a gap from every
block. Between two blocks below 21 m the gap is the side setback of the taller (rule 5(f)(xiii));
beside a high-rise it is the greater of the two blocks' gaps, which holds under every reading of the
open spacing question, and never less than the high-rise's fire lane and the ground its tender
turns on at a corner, which no block below 21 m may stand on.

A block on the fringe opens onto the ring road it stands against or, up to 12 m high, is reached by
a pathway branching out of the ring (rule 8(l)): a straight run of paving as wide as the rule asks,
from a face of the block to the ring, on ground no block, planted strip, buffer or (where roads may
not use it) setback takes. A taller block that no road reaches is not placed: the rule gives a
pathway to a block up to 12 m only.

Blocks are placed one at a time, the one that adds the most saleable area first and, between
equals, the nearer the ring, until the fringe holds no more or the next would leave less free
ground than the club house, the ramp, the open space and the facilities are expected to need
(`Run.reserve_target_sqm`, the estimate the search keeps an end of the plot by): what the rules
ask of the layout comes before another block. The work is done in the turned frame (frame.py),
where every block stands upright as in a column; any prototype of the kit may stand on the
fringe, whatever its depth, since no column has to take it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby

import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel, unary_union

from siteplan.contracts import TowerPrototype
from siteplan.contracts.resolved_rules import HEIGHT_TOL_M
from siteplan.geometry import opening
from siteplan.optimizer.search.columns import STEP_M, Choice, Standing
from siteplan.optimizer.search.fit import fit_rectangle
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.land import EMPTY, Land, Plot, erode, grow, polygons, setback_land
from siteplan.optimizer.search.network import ENTRANCES_TRIED, EPS_M, TOUCH_M, Cluster
from siteplan.optimizer.search.quantities import Quantities
from siteplan.optimizer.search.readings import FloorClass


@dataclass(frozen=True)
class Fringed:
    """A block on the fringe: where it stands (in the turned frame) and the pathway that reaches
    it, in the survey's frame (empty when it stands against the ring road itself)."""

    standing: Standing
    pathway: BaseGeometry


def pathway_serves(q: Quantities, cls: FloorClass) -> bool:
    """Whether rule 8(l) lets a pathway reach a block this tall: up to the height the rule names
    (the physical height, the stilt included, as the validator measures it), or any block where
    the rules read the clause that way; never where the rules give the pathway no width."""
    if q.pathway_m is None:
        return False
    return q.pathway_any_block or cls.physical_m <= q.pathway_max_height_m + HEIGHT_TOL_M


def need_m(q: Quantities, a: FloorClass, b: FloorClass) -> float:
    """What two blocks keep between them: the gap of the one that asks more (rule 5(f)(xiii) for
    two blocks below 21 m; beside a high-rise the greater gap holds under every reading of the open
    spacing question), never less than a high-rise's fire lane and the room its tender turns in at
    a corner, and the firm's margin over it."""
    gap = max(a.gap_m, b.gap_m)
    if a.high_rise or b.high_rise:
        gap = max(gap, q.lane_m, q.reach_m)
    return gap + q.gap_margin_m


def options(kit: Sequence[TowerPrototype], classes: Mapping[str, Sequence[FloorClass]],
            max_floors: int, q: Quantities) -> list[Choice]:
    """The blocks the fringe may take: every prototype of the kit, whatever its depth, at each
    floor count below the high-rise height the profile leaves open, up to the configuration's
    tallest. Of the counts that ask the same of the ground only the tallest is kept, once among
    those a pathway may reach and once among those only a road reaches."""
    found = []
    for prototype in kit:
        best: dict[tuple, FloorClass] = {}
        for cls in classes.get(prototype.id, ()):  # lowest first: the tallest of a kind wins
            if not cls.high_rise and cls.floors <= max_floors:
                best[(*_key(cls), pathway_serves(q, cls))] = cls
        found += [Choice(prototype, cls, prototype.length_m, prototype.depth_m,
                         prototype.per_floor.saleable_sqft * cls.floors) for cls in best.values()]
    return found


def _key(cls: FloorClass) -> tuple[float, float, float]:
    """What a block asks of the ground round it: its front and side setbacks and its gap."""
    return cls.front, cls.setback_m, cls.gap_m


def own_lands(plot: Plot, q: Quantities, classes: Sequence[FloorClass]
              ) -> dict[tuple[float, float], BaseGeometry]:
    """The ground a block below 21 m of each kind stands on, by its band's own setbacks and the
    firm's margin over them (land.setback_land), in the survey's frame: worked out once a run."""
    kinds = {(cls.front, cls.setback_m) for cls in classes if not cls.high_rise}
    return {(front, side): setback_land(plot, front + q.setback_margin_m,
                                        side + q.setback_margin_m) for front, side in kinds}


def place(plot: Plot, q: Quantities, frame: Frame, land: Land, cluster: Cluster,
          standing: Sequence[Standing], choices: Sequence[Choice], *,
          own: Mapping[tuple[float, float], BaseGeometry], kept_clear: BaseGeometry | None,
          roads_in_setback: bool, eps_m: float, room_sqm: float) -> list[Fringed]:
    """The blocks the fringe of this layout holds, most valuable first, each with the pathway that
    reaches it. `standing` are the blocks of the columns; `own` the ground each kind of block
    stands on (`own_lands`); `roads_in_setback` whether the profile lets a road, and so a pathway,
    run inside the setback; `eps_m` how far inside its ground a block stands, so no rounding puts
    it over a line; `room_sqm` the free ground the rest of the layout is expected to need, which no
    block takes."""
    if not choices:
        return []
    ring = frame.to_turned(cluster.ring)
    hull = frame.to_turned(cluster.hull)
    water = [frame.to_turned(plot.excluded)] if not plot.excluded.is_empty else []
    free = frame.to_turned(plot.net).difference(unary_union(
        [frame.to_turned(land.zone), frame.to_turned(land.strip), hull, ring, *water]))
    if free.area < room_sqm:  # the rest of the layout needs all of it: no block can be placed
        return []
    kept = [*water, *([frame.to_turned(kept_clear)] if kept_clear is not None else [])]
    taken = unary_union([hull, ring, *kept])
    blocks = [(box(s.x0, s.y0, s.x1, s.y1), s.choice.cls) for s in standing]
    by_key = {_key(c.cls): c.cls for c in choices}
    lands = {}
    for key, cls in by_key.items():
        near = [grow(b, need_m(q, cls, other)) for b, other in blocks]
        lands[key] = erode(frame.to_turned(own[(cls.front, cls.setback_m)]).difference(
            unary_union([taken, *near])), eps_m)
    fits = _Fits(lands, ring)
    if not any(len(fits.of(c)[0]) for c in choices):
        return []
    paths = _pathway_ground(plot, frame, land, hull, kept, [b for b, _ in blocks],
                            roads_in_setback, eps_m)
    placed: list[Fringed] = []
    while True:
        pick = _best(choices, fits, ring, paths, q, free, room_sqm)
        if pick is None:
            return placed
        footprint, choice, pathway = pick
        x0, y0, _, _ = footprint.bounds
        placed.append(Fringed(Standing(choice, -1, x0, y0),
                              frame.to_survey(pathway) if not pathway.is_empty else EMPTY))
        lands = {key: ground.difference(unary_union([
            grow(footprint, need_m(q, choice.cls, by_key[key])), pathway]))
            for key, ground in lands.items()}
        fits = _Fits(lands, ring)
        paths = paths.difference(grow(footprint, eps_m))
        free = free.difference(_cost(footprint, choice, pathway))


def _cost(footprint: Polygon, choice: Choice, pathway: BaseGeometry) -> BaseGeometry:
    """The free ground a block takes from the rest of the layout: itself, the gap round it that
    another building keeps, and its pathway."""
    return unary_union([grow(footprint, choice.cls.gap_m), pathway])


def _pathway_ground(plot: Plot, frame: Frame, land: Land, hull: BaseGeometry,
                    kept: list[BaseGeometry], blocks: list[Polygon], roads_in_setback: bool,
                    eps_m: float) -> BaseGeometry:
    """Where a pathway may run, in the turned frame: the plot less the planted strip, the buffer,
    the ground kept for the open space, the cluster inside the ring and its blocks, and, where
    roads may not use it, the setback."""
    out = [frame.to_turned(land.strip), hull, *kept, *(grow(b, eps_m) for b in blocks)]
    if not roads_in_setback:
        out.append(frame.to_turned(land.zone))
    return frame.to_turned(plot.net).difference(unary_union([g for g in out if not g.is_empty]))


def _best(choices: Sequence[Choice], fits: _Fits, ring: BaseGeometry, paths: BaseGeometry,
          q: Quantities, free: BaseGeometry, room_sqm: float
          ) -> tuple[Polygon, Choice, BaseGeometry] | None:
    """The most valuable block the fringe still holds that a road or a pathway reaches and that
    leaves the free ground the rest of the layout needs, the nearer the ring the better between
    equals, and its pathway (empty when none is needed). Only the first few are tried, as the
    entrance tries its nearest few, so the blocks of less value are looked at only while tries
    are left."""
    tried = 0
    by_value = sorted(range(len(choices)), key=lambda i: -choices[i].value)
    for _, same in groupby(by_value, key=lambda i: choices[i].value):
        found = []
        for index in same:
            boxes, distances = fits.of(choices[index])
            by_path = pathway_serves(q, choices[index].cls)
            for footprint, distance in zip(boxes, distances, strict=True):
                if distance <= TOUCH_M or by_path:
                    x0, y0, _, _ = footprint.bounds
                    found.append((float(distance), y0, x0, index, footprint))
        for distance, _, _, index, footprint in sorted(found, key=lambda f: f[:4]):
            if tried >= ENTRANCES_TRIED:
                return None
            tried += 1
            pathway = EMPTY if distance <= TOUCH_M else _pathway(footprint, ring, paths, q)
            if pathway is None:
                continue
            if free.difference(_cost(footprint, choices[index], pathway)).area < room_sqm:
                continue
            return footprint, choices[index], pathway
    return None


class _Fits:
    """The upright blocks each land holds on the search's grid, and how far each is from the ring
    road, worked out once for each land and size: the land a block may stand on is opened at its
    depth once for every block that deep."""

    def __init__(self, lands: Mapping[tuple, BaseGeometry], ring: BaseGeometry):
        self.lands, self.ring = lands, ring
        self._rooms: dict[tuple, list[Polygon]] = {}
        self._found: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

    def of(self, choice: Choice) -> tuple[np.ndarray, np.ndarray]:
        key = _key(choice.cls)
        size = (key, choice.depth_m, choice.length_m)
        if size not in self._found:
            if (key, choice.depth_m) not in self._rooms:
                ground = self.lands[key]
                self._rooms[(key, choice.depth_m)] = (
                    [] if ground.is_empty else polygons(opening(ground, choice.depth_m)))
            boxes = _grid(self.lands[key], self._rooms[(key, choice.depth_m)], choice.depth_m,
                          choice.length_m)
            self._found[size] = (boxes, shapely.distance(boxes, self.ring) if len(boxes)
                                 else np.array([]))
        return self._found[size]


def _grid(ground: BaseGeometry, rooms: Sequence[Polygon], depth_m: float, length_m: float
          ) -> np.ndarray:
    """Every upright block of this size, on the search's grid, that lies wholly on the ground:
    `rooms` are the pieces of the ground at least the block's depth wide."""
    out = []
    for piece in rooms:
        minx, miny, maxx, maxy = piece.bounds
        if maxx - minx < depth_m or maxy - miny < length_m:
            continue
        xs = np.arange(minx, maxx - depth_m + EPS_M, STEP_M)
        ys = np.arange(miny, maxy - length_m + EPS_M, STEP_M)
        x, y = (a.ravel() for a in np.meshgrid(xs, ys))
        boxes = shapely.box(x, y, x + depth_m, y + length_m)
        shapely.prepare(ground)
        out.append(boxes[shapely.contains(ground, boxes)])
    return np.concatenate(out) if out else np.array([])


def _pathway(block: Polygon, ring: BaseGeometry, paths: BaseGeometry, q: Quantities
             ) -> Polygon | None:
    """The shortest straight pathway from a face of the block to the ring road on free ground:
    as wide as the rule asks (a hair over, as every road here is drawn), and at least as long as
    it is wide, running on into the ring where the ring is nearer than that, so that it measures
    its width on its own. Tried at both ends and the middle of each face."""
    width = q.pathway_m + 2 * EPS_M
    bounds = block.bounds
    best: tuple[float, Polygon] | None = None
    for axis in (1, 0):  # off the faces across y, then those across x
        for sign in (1, -1):
            found = _from_face(bounds, axis, sign, width, ring, paths)
            if found is not None and (best is None or found[0] < best[0]):
                best = found
    return best[1] if best else None


def _from_face(bounds: tuple[float, float, float, float], axis: int, sign: int, width: float,
               ring: BaseGeometry, paths: BaseGeometry) -> tuple[float, Polygon] | None:
    """The shortest pathway off one face of a block (the face whose outward normal runs `sign`
    along `axis`, 0 for x and 1 for y), at either end of the face or its middle, that runs on free
    ground to the ring: how far the ring is, and the pathway."""
    low, high = bounds[1 - axis], bounds[3 - axis]  # the face's own extent
    if high - low < width:
        return None
    best: tuple[float, Polygon] | None = None
    for start in dict.fromkeys((low, (low + high - width) / 2, high - width)):
        found = _toward_ring(bounds, axis, sign, start, width, ring)
        if found is None:
            continue
        gap, pathway = found
        if pathway.difference(ring).difference(paths).area > EPS_M * width:
            continue
        if best is None or gap < best[0]:
            best = (gap, pathway)
    return best


@dataclass(frozen=True)
class RegionTry:
    """A narrow part of the plot (a region of the envelope's width profile beside its main body)
    and whether a block below 21 m fits there at all: the most valuable that does, or else how
    wide the land such a block may stand on is there, against the narrowest block of the kit."""

    shape: Polygon  # in the survey's frame
    area_sqm: float
    width_m: float  # the widest circle in the region
    fits: Choice | None
    land_width_m: float  # the widest circle in the land a block below 21 m may stand on there
    narrowest_m: float


def try_regions(plot: Plot, regions: Sequence[Polygon], choices: Sequence[Choice],
                angles: Sequence[float], q: Quantities) -> list[RegionTry]:
    """Each narrow region of the plot, tried for every block below 21 m the kit makes, at every
    direction the search lays blocks in: the region's land for a block is the land its own band
    leaves (land.setback_land), out of the water buffer."""
    out = []
    for region in regions:
        best: Choice | None = None
        widest = 0.0
        for choice in sorted(choices, key=lambda c: -c.value):
            cls = choice.cls
            ground = setback_land(plot, cls.front + q.setback_margin_m,
                                  cls.setback_m + q.setback_margin_m).intersection(region)
            if not plot.excluded.is_empty:
                ground = ground.difference(plot.excluded)
            widest = max(widest, _widest(ground))
            if best is None and fit_rectangle(ground, choice.length_m, choice.depth_m,
                                              angles) is not None:
                best = choice
        out.append(RegionTry(region, region.area, _widest(region), best, widest,
                             min((c.depth_m for c in choices), default=0.0)))
    return out


def _widest(ground: BaseGeometry) -> float:
    """The diameter of the widest circle that fits in the ground."""
    return max((2 * p.boundary.distance(polylabel(p, tolerance=EPS_M)) for p in polygons(ground)),
               default=0.0)


def _toward_ring(bounds: tuple[float, float, float, float], axis: int, sign: int, start: float,
                 width: float, ring: BaseGeometry) -> tuple[float, Polygon] | None:
    """A pathway `width` wide from one face of a block, at `start` along it, to the ring road:
    how far the ring is from the face, and the pathway, which runs that far and on into the ring
    (as long as it is wide at least). None when the ring is not that way."""
    x0, y0, x1, y1 = bounds
    rx0, ry0, rx1, ry1 = ring.bounds
    face = (y1 if sign > 0 else y0) if axis == 1 else (x1 if sign > 0 else x0)
    far = ((ry1 if sign > 0 else ry0) if axis == 1 else (rx1 if sign > 0 else rx0)) - face
    if far * sign <= 0:
        return None

    def strip(length: float) -> Polygon:
        a, b = sorted((face, face + sign * length))
        return box(start, a, start + width, b) if axis == 1 else box(a, start, b, start + width)

    cut = strip(abs(far)).intersection(ring)
    if cut.is_empty:
        return None
    cx0, cy0, cx1, cy1 = cut.bounds
    near = (cy0 if sign > 0 else cy1) if axis == 1 else (cx0 if sign > 0 else cx1)
    gap = abs(near - face)
    return gap, strip(max(gap + TOUCH_M, width + EPS_M))
