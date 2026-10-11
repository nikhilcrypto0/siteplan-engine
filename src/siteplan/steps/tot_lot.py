"""Step 5: the organised open space, the tot-lot. A high-rise site or a Group Development Scheme
keeps at least 10% of its site area (rule 7(a)(vii), rule 8(g)), a smaller plot above 750 m² 5%
(rule 5(f)(vi)), over and above the setbacks, open to the sky, in pockets at least 3 m wide. The
architect's rules (2026-10-11): the share is of the whole plot, and the tot-lot goes first where
no block of the firm's fits, so it costs the least building land. A water body's buffer outside
the setbacks counts too (rule 3(a)(iii)(3)). What is still needed comes from the building land
beside the largest free pocket, or, with none, at the end of the land furthest from the main road.
The gaps between blocks never count (rule 7(a)(xii)): they come with the blocks (step 6)."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from pathlib import Path

from shapely import set_precision
from shapely.errors import GEOSException
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan import rules
from siteplan.intake import load_defaults
from siteplan.library import FlatLibrary
from siteplan.prototypes.compose import compose_library
from siteplan.steps.inputs import Inputs, bearing, compass
from siteplan.steps.setbacks import Setbacks
from siteplan.steps.survey_copy import SurveyCopy

CUT_TOLERANCE_M = 0.01  # how finely a cut is placed; pieces this close are one pocket; a
# width this short of the least still counts (a 3.000 m strip is 3 m wide)
GRID_M = 0.001  # two outlines GEOS cannot overlay are snapped to this grid and tried again
WATER, THIN, BLOCK = "the water's buffer", "land no block fits on", "land a block fits on"
FROM_LINE, FROM_EDGE = "the buffer from the line drawn", "the buffer from the plot's edge"


@dataclass(frozen=True)
class Share:
    """What the rules ask of this site: the share of the site, and the pockets' least size."""

    fraction: float
    min_width_m: float
    min_pocket_sqm: float
    why: str  # 'a high-rise site and a Group Development Scheme'
    clauses: tuple[tuple[str, str], ...]  # (whom the rule holds, its clause)


def share_for(high_rise: bool, group_scheme: bool, plot_sqm: float) -> Share | None:
    """Rule 7(a)(vii) for a high-rise site and 8(g) for a Group Development Scheme (the same 10%,
    not added); rule 5(f)(vi) for any other plot above 750 m²; None below it."""
    if high_rise or group_scheme:
        why = " and ".join(name for name, holds in (("a high-rise site", high_rise),
                                                    ("a Group Development Scheme", group_scheme))
                           if holds)
        clauses = tuple((whom, clause) for whom, clause, holds in (
            ("a high-rise site", rules.OPEN_SPACE_2012_CLAUSE, high_rise),
            ("a Group Development Scheme", rules.GROUP_SCHEME_OPEN_SPACE_CLAUSE, group_scheme))
            if holds)
        return Share(rules.OPEN_SPACE_MIN_FRACTION, rules.OPEN_SPACE_MIN_WIDTH_M,
                     rules.OPEN_SPACE_MIN_POCKET_SQM, why, clauses)
    if plot_sqm > rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:
        return Share(rules.NON_HIGH_RISE_OPEN_SPACE_FRACTION,
                     rules.NON_HIGH_RISE_OPEN_SPACE_MIN_WIDTH_M,
                     rules.NON_HIGH_RISE_OPEN_SPACE_MIN_POCKET_SQM,
                     f"a plot above {rules.NON_HIGH_RISE_OPEN_SPACE_ABOVE_SQM:,.0f} m²",
                     (("a plot below high-rise", rules.NON_HIGH_RISE_OPEN_SPACE_CLAUSE),))
    return None


@dataclass(frozen=True)
class Blocks:
    """The firm's blocks, from its flat library: the land a block fits on is at least as wide as
    the shallowest and holds the smallest."""

    depth_m: float  # the shallowest block's depth
    smallest: tuple[float, float]  # the smallest block's length and depth
    count: int
    source: str  # the file and how far it is confirmed


class NoBlocks(Exception):
    """The workspace names a flat library that cannot be read or composed."""


def firm_blocks(workspace: Path | None) -> Blocks | None:
    """The blocks the firm's flat library composes (the prototype kit, the flats in equal
    shares), or None when the workspace names no library."""
    if workspace is None:
        return None
    defaults = load_defaults(workspace)
    if not defaults.flat_library:
        return None
    try:
        library = FlatLibrary.model_validate_json(
            (workspace / defaults.flat_library).read_text())
        kit = compose_library(library)
    except (OSError, ValueError) as problem:
        first = str(problem).splitlines()[0]
        raise NoBlocks(f"{defaults.flat_library} cannot be used: {first}") from problem
    smallest = min(kit, key=lambda block: block.length_m * block.depth_m)
    return Blocks(min(block.depth_m for block in kit), (smallest.length_m, smallest.depth_m),
                  len(kit), f"{defaults.flat_library}, the firm's flat library in the workspace "
                  f"({defaults.standard_status('flat_library')})")


@dataclass(frozen=True)
class Pocket:
    polygon: BaseGeometry  # one piece, or pieces that touch
    lies: str  # where in the plot: 'north'
    on_sqm: tuple[tuple[str, float], ...]  # (WATER, THIN or BLOCK, m²) it stands on

    @property
    def area_sqm(self) -> float:
        return self.polygon.area


@dataclass(frozen=True)
class Placing:
    """The tot-lot on one reading of the water's buffer."""

    reading: str  # FROM_LINE, FROM_EDGE, or '' when there is no water
    land: BaseGeometry  # step 4's land left for buildings, less the buffer
    water: BaseGeometry  # the buffer outside the setbacks, in pockets that count
    water_lost_sqm: float  # buffer outside the setbacks too thin or small to count
    block_land: BaseGeometry  # where a block of the firm's fits
    thin: BaseGeometry  # land no block fits on, in pockets that count
    tot_lot: BaseGeometry
    pockets: tuple[Pocket, ...]
    grew_from: str  # how the rest was found: 'beside', 'far end', or '' when free land held it
    need_sqm: float
    block_land_after: BaseGeometry  # where a block fits once the tot-lot is out, measured again

    @property
    def short_sqm(self) -> float:
        return max(0.0, self.need_sqm - self.tot_lot.area)

    def on(self, kind: str) -> float:
        return sum(area for pocket in self.pockets for k, area in pocket.on_sqm if k == kind)

    @property
    def after(self) -> BaseGeometry:
        """The land left for buildings, roads and parking once the tot-lot is out."""
        return _overlay(self.land, self.tot_lot, DIFF)


@dataclass
class TotLot:
    inputs: Inputs
    copy: SurveyCopy
    setbacks: Setbacks
    stopped: str | None = None
    ask: str | None = None
    share: Share | None = None
    plot_sqm: float = 0.0  # the whole plot, as the sheet writes it (or as drawn)
    plot_from: str = ""
    blocks: Blocks | None = None
    placings: tuple[Placing, ...] = ()  # the first is the one drawn
    waiting: tuple[str, ...] = ()  # water whose buffer waits on an answer (step 3)

    @property
    def need_sqm(self) -> float:
        return self.share.fraction * self.plot_sqm if self.share else 0.0

    @property
    def net_need_sqm(self) -> float:
        net = self.setbacks.widening.net
        return self.share.fraction * net.area if self.share and net is not None else 0.0


def lay_out(inputs: Inputs, copy: SurveyCopy, setbacks: Setbacks) -> TotLot:
    t = TotLot(inputs, copy, setbacks)
    if setbacks.stopped:
        return _stop(t, "step 4 has no land left for buildings yet, and the tot-lot is taken "
                        "from it", setbacks.ask)
    t.plot_sqm = copy.written_sqm or copy.drawn_sqm
    t.plot_from = "written on the sheet" if copy.written_sqm else "as drawn (none is written)"
    t.share = share_for(setbacks.high_rise, setbacks.widening.group_scheme, t.plot_sqm)
    if t.share is None:
        return t
    ask = ("Which flat library does the firm build with? Name it as flat_library in the "
           "workspace's siteplan.workspace.json.")
    try:
        t.blocks = firm_blocks(inputs.workspace)
    except NoBlocks as problem:
        return _stop(t, f"the firm's flat library cannot be used ({problem})", ask)
    if t.blocks is None:
        return _stop(t, "the firm's blocks are not known, and the tot-lot goes first where none "
                        "of them fits", ask)
    water = [w for w in setbacks.widening.water if w.buffer_m is not None]
    t.waiting = tuple(w.kind for w in setbacks.widening.water if w.buffer_m is None)
    readings = [("", None)] if not water else [
        (FROM_LINE, unary_union([w.kept_free for w in water])),
        (FROM_EDGE, unary_union([w.edge_kept_free for w in water]))]
    road = setbacks.height.road
    start = next((g for g in (road.frontage, road.ground, road.area)
                  if g is not None and not g.is_empty), None)
    for reading, buffer in readings:
        land = setbacks.left if buffer is None else _overlay(setbacks.left, buffer, DIFF)
        wet = None if buffer is None else _overlay(setbacks.left, buffer, MEET)
        t.placings += (place(land, wet, t.need_sqm, t.share, t.blocks, start,
                             setbacks.widening.net, reading),)
    return t


def _stop(t: TotLot, why: str, ask: str | None) -> TotLot:
    t.stopped, t.ask = why, ask
    return t


def place(land: BaseGeometry, wet: BaseGeometry | None, need_sqm: float, share: Share,
          blocks: Blocks, road: BaseGeometry | None, plot: Polygon, reading: str = "") -> Placing:
    """The tot-lot on `land` (and on `wet`, the buffer outside the setbacks): the free pockets
    largest first, the last cut square to its length at its end away from the main road; then, when
    they do not hold the need, the building land on the side of the largest pocket, or at the end
    of the land away from the main road, each cut off by one straight line."""
    def keep(geometry: BaseGeometry) -> BaseGeometry:
        return pockets_in(geometry, share)

    water = keep(wet) if wet is not None else Polygon()
    water_lost = (wet.area - water.area) if wet is not None else 0.0
    block_land = block_land_in(land, blocks)
    thin = keep(_overlay(land, block_land, DIFF))
    free = sorted(_parts(unary_union([water, thin])), key=lambda p: -p.area)
    taken, held = [], 0.0
    for part in free:
        if held >= need_sqm:
            break
        if held + part.area > need_sqm:
            part = _straight_cut(part, _lengthwise(part, road), need_sqm - held, keep)
        taken.append(part)
        held += part.area
    grew_from = ""
    if held < need_sqm and not block_land.is_empty:
        seed = max(taken, key=lambda p: p.area) if taken else None
        toward = (_toward(block_land, seed) if seed is not None
                  else _toward(road, block_land))
        rest = _straight_cut(block_land, toward, need_sqm - held, keep)
        grew_from = "beside" if seed is not None else "far end"
        taken.append(rest)
    tot_lot = unary_union(taken) if taken else Polygon()
    pockets = tuple(Pocket(part, compass(bearing((plot.centroid.x, plot.centroid.y),
                                                 (part.centroid.x, part.centroid.y))),
                           tuple((kind, _overlay(part, ground, MEET).area)
                                 for kind, ground in ((WATER, water), (THIN, thin),
                                                      (BLOCK, block_land))
                                 if _overlay(part, ground, MEET).area > 0))
                    for part in _touching(_parts(tot_lot)))
    after = _overlay(land, tot_lot, DIFF)
    return Placing(reading, land, water, water_lost, block_land, thin, tot_lot, pockets,
                   grew_from, need_sqm, block_land_in(after, blocks))


def pockets_in(geometry: BaseGeometry, share: Share) -> BaseGeometry:
    """The parts of `geometry` that count as tot-lot: at least the least width everywhere (a
    circle that wide rolls through them; corners keep their shape) and each piece at least the
    least pocket."""
    if geometry is None or geometry.is_empty:
        return Polygon()
    half = share.min_width_m / 2 - CUT_TOLERANCE_M
    wide = geometry.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")
    wide = _overlay(wide, geometry, MEET)
    return unary_union([p for p in _parts(wide) if p.area >= share.min_pocket_sqm])


def block_land_in(land: BaseGeometry, blocks: Blocks) -> BaseGeometry:
    """Where one of the firm's blocks fits: land at least as wide as the shallowest block, in
    pieces that hold the smallest."""
    if land.is_empty:
        return Polygon()
    half = blocks.depth_m / 2 - CUT_TOLERANCE_M
    wide = land.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")
    wide = _overlay(wide, land, MEET)
    length, depth = blocks.smallest
    return unary_union([p for p in _parts(wide) if p.area >= length * depth])


MEET, DIFF = "intersection", "difference"


def _overlay(a: BaseGeometry, b: BaseGeometry, how: str) -> BaseGeometry:
    """a's intersection with b, or a less b. GEOS refuses some outlines that meet at a hair's
    breadth ('non-noded intersection'); those are snapped to a millimetre grid and tried again."""
    try:
        return getattr(a, how)(b)
    except GEOSException:
        return getattr(set_precision(a, GRID_M), how)(set_precision(b, GRID_M))


def _parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    return [g for g in getattr(geometry, "geoms", [geometry])
            if isinstance(g, Polygon) and not g.is_empty]


def _touching(parts: list[Polygon]) -> list[BaseGeometry]:
    """The pieces that touch (within the cut's tolerance) as one pocket each, largest first; the
    shapes are kept exactly."""
    groups: list[BaseGeometry] = []
    for part in sorted(parts, key=lambda p: -p.area):
        near = [g for g in groups if g.distance(part) <= CUT_TOLERANCE_M]
        groups = [g for g in groups if all(g is not n for n in near)]
        groups.append(unary_union([part, *near]))
    return sorted(groups, key=lambda g: -g.area)


def _toward(start: BaseGeometry | None, end: BaseGeometry) -> tuple[float, float] | None:
    """The unit direction from one shape's middle to another's; None when they share it."""
    if start is None:
        return None
    a, b = start.centroid, end.centroid
    length = math.hypot(b.x - a.x, b.y - a.y)
    return None if length <= CUT_TOLERANCE_M else ((b.x - a.x) / length, (b.y - a.y) / length)


def _lengthwise(part: BaseGeometry, road: BaseGeometry | None) -> tuple[float, float] | None:
    """The direction along a pocket's length (its smallest enclosing rectangle's long side),
    pointing away from the main road."""
    with warnings.catch_warnings():  # GEOS divides by zero on a rectangle square to the axes
        warnings.simplefilter("ignore", RuntimeWarning)
        rectangle = part.minimum_rotated_rectangle
    if not isinstance(rectangle, Polygon):  # a line or a point: no length to cut along
        return None
    (ax, ay), (bx, by), (cx, cy) = list(rectangle.exterior.coords)[:3]
    dx, dy = max(((bx - ax, by - ay), (cx - bx, cy - by)), key=lambda d: math.hypot(*d))
    length = math.hypot(dx, dy)
    if length <= CUT_TOLERANCE_M:
        return None
    ux, uy = dx / length, dy / length
    away = _toward(road, part)
    return (-ux, -uy) if away is not None and ux * away[0] + uy * away[1] < 0 else (ux, uy)


def _straight_cut(region: BaseGeometry, toward: tuple[float, float] | None, area: float,
                  keep) -> BaseGeometry:
    """The part of `region` furthest along `toward` that holds `area` m² of pockets that count,
    cut off by one straight line square to it. All of it when it holds no more."""
    whole = keep(region)
    toward = toward or _lengthwise(region, None)
    if whole.area <= area or toward is None:
        return whole
    ux, uy = toward
    along = [x * ux + y * uy for part in _parts(region) for x, y in part.exterior.coords]
    reach = sum(abs(c) for c in region.bounds)  # covers every point of the region

    def beyond(at: float) -> BaseGeometry:
        side = reach + abs(at)
        x, y = at * ux, at * uy  # on the line
        half = Polygon([(x - side * uy, y + side * ux),
                        (x - side * uy + side * ux, y + side * ux + side * uy),
                        (x + side * uy + side * ux, y - side * ux + side * uy),
                        (x + side * uy, y - side * ux)])
        return keep(_overlay(region, half, MEET))

    low, high = min(along), max(along)
    while high - low > CUT_TOLERANCE_M:
        middle = (low + high) / 2
        if beyond(middle).area >= area:
            low = middle
        else:
            high = middle
    return beyond(low)
