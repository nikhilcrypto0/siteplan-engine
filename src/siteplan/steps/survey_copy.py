"""Step 1: copy the survey. The drawing is checked against what is written on it, the roads are
listed with where each one meets the plot, the ground's levels are read, what is drawn inside
the plot is listed and ignored, and what is drawn outside within 12 m is reported. No building
rule is applied yet: the step's job is to get the plot right, so every later step stands on
the right land."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from statistics import median

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from siteplan import rules
from siteplan.geometry import angle_gap, facing_deg, straight_runs
from siteplan.intake import Mark
from siteplan.roads import Road, roads_near
from siteplan.steps.inputs import Inputs, bearing, compass, compass_word
from siteplan.survey import LineGroup, Terrain
from siteplan.units import written_areas

ROAD_TOUCH_M = 1.0  # a road's drawn edge this close to the plot meets it
ENDS_AT_DEG = 45.0  # a road this far off the boundary's own direction runs into the plot
ROAD_LEVEL_REACH_M = 20.0  # levels on a road this near where it meets the plot give its level
SHORT_RUN_M = 4.0  # a straight stretch of the boundary shorter than this is a jog
SIDE_MATCH_M = 0.05  # a written length's edge and a stretch this close in length are the same
AGREES_PCT = 1.0  # a drawn and a written figure this close agree
WIDTH_MATCH_M = 0.05  # a road drawn this close to the carriageway the project records is it
CARRIED = "ends at the plot (its straight edges stop short; taken on to the plot)"
ENDS, ALONG, APART = "ends at the plot", "runs along the plot", "does not reach the plot"
_LETTER = re.compile(r"[A-Za-z]{2,}")


@dataclass(frozen=True)
class Side:
    number: int
    faces: str
    drawn_m: float
    written_m: float | None  # the length written on the sheet for it, when one was read
    line: LineString

    @property
    def agrees(self) -> bool | None:
        if self.written_m is None:
            return None
        return abs(self.drawn_m / self.written_m - 1) * 100 <= AGREES_PCT


@dataclass(frozen=True)
class RoadSeen:
    name: str
    lies: str  # 'west'
    side_code: str  # 'W'
    drawn_width_m: float
    divided: bool
    distance_m: float
    meets: str  # ENDS, CARRIED, ALONG or APART
    carried_m: float  # how far its straight edges were taken on to reach the plot
    frontage_m: float  # the length of the plot's boundary it meets
    level: tuple[float, float, float, int] | None  # lowest, middle, highest, how many
    legal_width_m: float | None = None
    legal_source: str = ""
    area: Polygon | None = None  # drawing only
    frontage: BaseGeometry | None = None  # drawing only
    ground: Polygon | None = None  # the ground that meets the plot (taken on, or widened)

    @property
    def reaches(self) -> bool:
        return self.meets != APART


@dataclass
class SurveyCopy:
    inputs: Inputs
    plot: Polygon
    drawn_sqm: float
    written_sqm: float | None
    scale: str
    scale_is_a_check: bool  # False when the scale came from the written area itself
    sides_read: bool  # side lengths written on the sheet were read (a PDF sheet's labels)
    boundary_how: str  # how the boundary was chosen, as far as the survey reader says
    sides: list[Side]
    jogs: tuple[int, float]  # stretches shorter than SHORT_RUN_M: how many, how long in all
    roads: list[RoadSeen]
    access: RoadSeen | None
    terrain: Terrain | None
    levels: tuple[int, int]  # on the plot, off it
    inside: list[tuple[str, int]]  # text drawn inside the plot, and how many times
    inside_lines: list[LineGroup]  # line work that crosses the plot, not identified
    outside: list[tuple[str, int]]  # text drawn within the band outside the plot
    near_lines: list[LineGroup]  # line work near the plot that stays outside, not identified
    water: list[tuple[str, float]]  # each water body the project names: its class, how far
    marks: list[Mark]  # marks written on the sheet within the band
    warnings: list[str] = field(default_factory=list)

    @property
    def band(self) -> Polygon:
        return self.plot.buffer(rules.SITE_PLAN_NEIGHBOUR_BAND_M).difference(self.plot)


def copy_survey(inputs: Inputs) -> SurveyCopy:
    survey, plot = inputs.survey, inputs.survey.boundary
    scale, checks = _scale(inputs)
    sides, jogs = _sides(inputs)
    cal = survey.calibration
    named = inputs.water_keys
    unnamed = [g for g in inputs.draft.line_work if g.key.upper() not in named]
    roads = [_seen(i, road, inputs) for i, road in enumerate(roads_near(survey), 1)]
    access = _access(roads, inputs)
    if access is not None:
        roads = [_with_legal(r, inputs) if r is access else r for r in roads]
        access = next(r for r in roads if r.name == access.name)
    band = plot.buffer(rules.SITE_PLAN_NEIGHBOUR_BAND_M)
    inside = _texts([lb for lb in survey.labels if plot.contains(Point(lb.x, lb.y))])
    outside = _texts([lb for lb in survey.labels
                      if band.contains(Point(lb.x, lb.y)) and not plot.contains(Point(lb.x, lb.y))])
    water = {}
    for kind, line in outside_water(inputs):
        water[kind] = min(water.get(kind, math.inf), line.distance(plot))
    return SurveyCopy(
        inputs=inputs, plot=plot, drawn_sqm=plot.area, written_sqm=survey.stated_area_sqm,
        scale=scale, scale_is_a_check=checks,
        sides_read=cal is not None and bool(cal.agreeing or cal.rejected),
        boundary_how=_boundary_how(inputs), sides=sides, jogs=jogs, roads=roads,
        access=access, terrain=survey.terrain(),
        levels=(sum(lv.on_site for lv in survey.levels),
                sum(not lv.on_site for lv in survey.levels)),
        inside=inside, inside_lines=[g for g in unnamed if g.crosses_plot],
        outside=outside, near_lines=[g for g in unnamed if not g.crosses_plot],
        water=sorted(water.items(), key=lambda kv: kv[1]),
        marks=[m for m in inputs.draft.marks if m.distance_m <= rules.SITE_PLAN_NEIGHBOUR_BAND_M],
        warnings=list(dict.fromkeys([*survey.warnings, *inputs.draft.warnings])))


def outside_water(inputs: Inputs) -> list[tuple[str, LineString]]:
    """The water the project names, as drawn outside the plot. A line of the same colour wholly
    inside it (a sump, a tank) is an inside feature: listed with them, ignored."""
    plot = inputs.survey.boundary
    return [(kind, line) for kind, line in inputs.water if not plot.contains(line)]


def _boundary_how(inputs: Inputs) -> str:
    cal, written = inputs.survey.calibration, inputs.survey.stated_area_sqm
    if cal is not None and not cal.agreeing:
        return ("the tightest closed line round the spot levels, scaled to the written area "
                "(the survey reader's choice; see its warning)")
    if written:
        return "the closed line whose area is closest to the written area"
    if cal is not None:
        return "the closed line whose sides agree best with the written lengths"
    return "chosen by its layer and its size, because no area is written"


def _scale(inputs: Inputs) -> tuple[str, bool]:
    cal = inputs.survey.calibration
    if cal is None:
        return "a CAD drawing, read in the unit the file itself declares", True
    if not cal.agreeing:
        return ("taken from the written area, because no side length is written on the sheet; "
                "so the drawn area matches the written one by construction and is no check"), False
    snapped = f", the standard scale 1:{cal.snapped_scale}" if cal.snapped_scale else ""
    return (f"read from {len(cal.agreeing)} side lengths written on the sheet, which agree "
            f"within {cal.max_deviation_pct:.2f}%{snapped}"), True


def _sides(inputs: Inputs) -> tuple[list[Side], tuple[int, float]]:
    plot, cal = inputs.survey.boundary, inputs.survey.calibration
    written = [] if cal is None else [
        (e.drawn_units * cal.metres_per_unit, e.written_m) for e in (*cal.agreeing, *cal.rejected)]
    runs = straight_runs(plot)
    long = [r for r in runs if r.length >= SHORT_RUN_M]
    short = [r for r in runs if r.length < SHORT_RUN_M]
    sides = []
    for number, run in enumerate(long, 1):
        match = min(written, key=lambda w: abs(w[0] - run.length), default=None)
        on_sheet = match[1] if match and abs(match[0] - run.length) <= SIDE_MATCH_M else None
        sides.append(Side(number, compass(facing_deg(plot, run)), run.length, on_sheet,
                          run.line))
    return sides, (len(short), sum(r.length for r in short))


def _grown(road: Road, along: float = 0.0, across: float = 0.0) -> Polygon:
    """The road's ground, taken on along its own direction or widened across it."""
    angle = math.radians(road.direction_deg)
    ux, uy, nx, ny = math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle)
    coords = list(road.area.exterior.coords)
    ts = [x * ux + y * uy for x, y in coords]
    ss = [x * nx + y * ny for x, y in coords]
    t0, t1, s0, s1 = min(ts) - along, max(ts) + along, min(ss) - across, max(ss) + across
    return Polygon([(t * ux + s * nx, t * uy + s * ny)
                    for t, s in ((t0, s0), (t1, s0), (t1, s1), (t0, s1))])


def _drawn_lines(road: Road, raw: tuple[LineString, ...]) -> list[LineString]:
    """The survey's own road lines that hold the edges the road was measured on."""
    return [line for line in raw if any(line.distance(e.centroid) < 1e-6 for e in road.edges)]


def reach(road: Road, plot: Polygon, raw: tuple[LineString, ...]) -> tuple[str, float, Polygon]:
    """How a road meets the plot: it ends at it, runs along it, or does not reach it; how far its
    straight edges were taken on to reach it; and the ground that meets the boundary."""
    if road.area is None:
        return APART, 0.0, Polygon()
    near = road.area.buffer(road.distance_m + ROAD_TOUCH_M)
    end = road.area.buffer(road.distance_m + road.width_m + ROAD_TOUCH_M)
    runs = straight_runs(plot)
    run = max(runs, key=lambda r: (r.line.intersection(near).length, -r.line.distance(road.area)))
    if angle_gap(road.direction_deg, run.angle_deg) > ENDS_AT_DEG:
        touches = road.distance_m <= ROAD_TOUCH_M or any(  # its own line, near its end
            not part.is_empty and part.distance(plot) <= ROAD_TOUCH_M
            for part in (line.intersection(end) for line in _drawn_lines(road, raw)))
        if not touches:
            return APART, 0.0, road.area
        carried = road.distance_m if road.distance_m > ROAD_TOUCH_M else 0.0
        # taken on by its own width as well, so a boundary crossing it at a slant (never more
        # than ENDS_AT_DEG off square) is crossed from edge to edge
        return (CARRIED if carried else ENDS), carried, _grown(
            road, along=road.distance_m + road.width_m + ROAD_TOUCH_M)
    if road.distance_m <= ROAD_TOUCH_M:
        return ALONG, 0.0, _grown(road, across=road.distance_m + ROAD_TOUCH_M)
    return APART, 0.0, road.area


def _frontage(how: str, ground: Polygon, road: Road, plot: Polygon) -> BaseGeometry:
    """The stretch of the plot's boundary a road meets. Along the plot, only the stretches
    running its way count, not the short ends of the sides the widened ground cuts into."""
    if how == APART:
        return LineString()
    met = plot.exterior.intersection(ground)
    if how != ALONG:  # the stretch the road runs into, not a further side the ground reaches
        lines = [g for g in getattr(met, "geoms", [met])
                 if g.geom_type == "LineString" and g.length > 0]
        merged = linemerge(lines) if lines else LineString()
        parts = list(getattr(merged, "geoms", [merged]))
        return min(parts, key=lambda p: p.distance(road.area), default=LineString())
    pieces = []
    for part in getattr(met, "geoms", [met]):
        coords = list(getattr(part, "coords", []))
        pieces += [LineString([a, b]) for a, b in zip(coords, coords[1:], strict=False)
                   if a != b and angle_gap(road.direction_deg, math.degrees(
                       math.atan2(b[1] - a[1], b[0] - a[0])) % 180) <= ENDS_AT_DEG]
    return unary_union(pieces) if pieces else LineString()


def _seen(number: int, road: Road, inputs: Inputs) -> RoadSeen:
    plot = inputs.survey.boundary
    how, carried, ground = reach(road, plot, inputs.survey.roads)
    front = _frontage(how, ground, road, plot)
    level = None
    if not front.is_empty:
        near = front.buffer(ROAD_LEVEL_REACH_M).intersection(ground.buffer(ROAD_TOUCH_M))
        zs = sorted(lv.z for lv in inputs.survey.levels
                    if not lv.on_site and near.contains(Point(lv.x, lv.y)))
        if zs:
            level = (zs[0], median(zs), zs[-1], len(zs))
    return RoadSeen(f"R{number}", compass_word(road.side), road.side, road.width_m,
                    road.divided, road.distance_m, how, carried, front.length, level,
                    area=road.area, frontage=front, ground=ground)


def _access(roads: list[RoadSeen], inputs: Inputs) -> RoadSeen | None:
    """The road the project names as its access: on its side, as wide as its measured
    carriageway, among the roads that meet the plot. None when it cannot be told apart."""
    site = inputs.project.site
    if site.abutting_road_m is None and site.abutting_road_ft is None:
        return None
    found = [r for r in roads if r.reaches]
    if site.access_side:
        found = [r for r in found if r.side_code == site.access_side]
    if site.measured_carriageway_m:
        found = [r for r in found
                 if abs(r.drawn_width_m - site.measured_carriageway_m) <= WIDTH_MATCH_M]
    return found[0] if len(found) == 1 else None


def _with_legal(road: RoadSeen, inputs: Inputs) -> RoadSeen:
    site = inputs.project.site
    told = inputs.told("abutting_road")
    if site.abutting_road_status:
        told += f"; {site.abutting_road_status}"
    return replace(road, legal_width_m=inputs.project.to_site().abutting_road_m,
                   legal_source=told)


def _texts(labels) -> list[tuple[str, int]]:
    """The words written in a place, each with how often: numbers (levels, lengths) and written
    areas are left out."""
    seen: dict[str, int] = {}
    for label in labels:
        text = " ".join(label.text.split())
        if _LETTER.search(text) and not written_areas(text):
            seen[text.upper()] = seen.get(text.upper(), 0) + 1
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))


def side_label_at(side: Side, plot: Polygon, offset_m: float) -> tuple[float, float]:
    """A point just outside a side's middle, for its label."""
    mid = side.line.interpolate(0.5, normalized=True)
    centre = plot.centroid
    angle = math.radians(bearing((centre.x, centre.y), (mid.x, mid.y)))
    return mid.x + offset_m * math.sin(angle), mid.y + offset_m * math.cos(angle)
