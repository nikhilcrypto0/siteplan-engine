"""Step 4: setbacks from every side. The net plot (step 3) keeps open space round its edge for
the height step 2 allows: a high-rise keeps Table IV's column 4 on every side and, towards a road,
the higher of that and Table III's Building Line (rule 7(a)(xi)); a building below high-rise
keeps Table III's front towards the bigger road and its column 10 elsewhere (rule 5(f)(iii)).
Inside it a high-rise keeps a 2 m green strip; a water body's buffer is laid over the setbacks,
never added to them. What is left is the land buildings may stand on. The step never draws a
building: what changes with one (its length, a side without windows) is shown, not taken."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan import rules
from siteplan.geometry import facing_deg, straight_runs
from siteplan.steps.inputs import Inputs, compass
from siteplan.steps.main_road_height import TABLE_IV_WAY, Height
from siteplan.steps.road_widening import Widening
from siteplan.steps.survey_copy import ROAD_TOUCH_M, RoadSeen, SurveyCopy

FACES_ALONG_M = 2.0  # a side meets a road when this much of it lies along the road's frontage
LONG_BLOCKS_M = (40.0, 50.0, 60.0, 80.0, 100.0, 120.0)  # block lengths the note is shown for
ARC_SEGMENTS = 16  # a quarter circle's segments, the geometry library's own default
LANE_CROSSES_SQM = 0.5  # less of the fire lane than this in a water's buffer is drawing noise


@dataclass(frozen=True)
class SideSetback:
    number: int
    faces: str  # 'west'
    length_m: float
    roads: tuple[str, ...]  # the roads it meets
    metres: float
    why: str
    line: LineString


@dataclass(frozen=True)
class Option:
    """One height the road allows and the land its setbacks leave."""

    heights: str
    floors: tuple[int, ...]
    open_space_m: float
    front_m: float
    left_sqm: float


@dataclass
class Setbacks:
    inputs: Inputs
    copy: SurveyCopy
    height: Height
    widening: Widening
    stopped: str | None = None
    ask: str | None = None
    floors: int = 0  # the setbacks are drawn for this many floors (step 2's most)
    counted_m: float = 0.0
    high_rise: bool = True
    open_space_m: float = 0.0  # Table IV column 4, or Table III column 10
    front_road: str | None = None  # the front: the main road (high-rise), the bigger (Table III)
    sides: tuple[SideSetback, ...] = ()
    band: BaseGeometry | None = None  # the setback land
    green: BaseGeometry | None = None  # the 2 m green strip, inside the setbacks
    fire_lane: BaseGeometry | None = None  # where a 6 m fire lane can run, inside the green strip
    left: BaseGeometry | None = None  # the land left for buildings, before any water buffer
    left_by_water: tuple[tuple[str, BaseGeometry, BaseGeometry], ...] = ()  # (water, from the
    # line drawn, from the plot's edge): the land left with its buffer laid over the setbacks
    options: tuple[Option, ...] = ()
    long_blocks: tuple[tuple[float, float], ...] = ()  # (length, open space)
    concession: Option | None = None  # rule 16(e), when land was given up: shown, not taken

    @property
    def fire_room_m(self) -> float:
        """The least open space beside the green strip, where a fire lane must run."""
        return min(s.metres for s in self.sides) - (
            rules.PERIPHERAL_GREEN_STRIP_M if self.green is not None else 0.0)

    @property
    def lane_in_water(self) -> tuple[tuple[str, float, float], ...]:
        """(water, m² of the fire lane in its buffer from the line drawn, from the plot's edge),
        for each water body whose buffer the lane crosses."""
        if self.fire_lane is None:
            return ()
        out = []
        for water in self.widening.water:
            if water.buffer_m is None:
                continue
            on_line = self.fire_lane.intersection(water.kept_free).area
            on_edge = self.fire_lane.intersection(water.edge_kept_free).area
            if max(on_line, on_edge) >= LANE_CROSSES_SQM:
                out.append((water.kind, on_line, on_edge))
        return tuple(out)

    @property
    def front_m(self) -> float:
        """The setback towards the front road; the open space when no road meets the plot."""
        return max((side.metres for side in self.sides if self.front_road in side.roads),
                   default=self.open_space_m)


def set_back(inputs: Inputs, copy: SurveyCopy, height: Height, widening: Widening) -> Setbacks:
    s = Setbacks(inputs, copy, height, widening)
    if height.stopped:
        return _stop(s, "step 2 found no height", height.ask)
    if widening.stopped:
        return _stop(s, "step 3 has no net plot yet, and setbacks are measured from it",
                     widening.ask)
    floors = height.allowed_floors
    if floors is None:
        return _stop(s, "the main road sets no height limit, and the setbacks go by the height",
                     "How many floors do you want? The main road allows any height, and the "
                     "setbacks grow with it.")
    if height.way == TABLE_IV_WAY and widening.high_rise_plot is False:
        return _stop(s, "the net plot is too small for a high-rise", "The net plot is under "
                     f"{rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m², so no high-rise is allowed "
                     "(rule 7(a)(ii)). How tall should the buildings be, below 21 m?")
    net = widening.net
    s.floors, s.counted_m = floors, height.storeys.counted_m(floors)
    s.high_rise = height.way == TABLE_IV_WAY
    if not s.high_rise and rules.table_iii_line(net.area, s.counted_m) is None:
        top = rules.table_iii_lines(net.area)[-1]
        return _stop(s, f"the net plot's Table III row does not allow Stilt + {floors}",
                     f"Step 2 read Table III from the plot's written area "
                     f"({height.plot_sqm:,.1f} m²): Stilt + {floors}. After road widening the "
                     f"net plot ({net.area:,.1f} m²) is in a row that stops "
                     f"{'below' if top.below else 'at'} {top.up_to_m:g} m. How many floors "
                     "should the setbacks be drawn for?")
    reach = _road_reach(copy, widening)
    s.front_road = _front_road(s, reach)
    s.sides = _sides(s, net, reach, floors)
    s.open_space_m = _open_space(s, floors)
    s.band, s.left = _band_and_left(net, s.sides)
    if s.high_rise:
        s.green = net.boundary.buffer(rules.PERIPHERAL_GREEN_STRIP_M).intersection(net)
        s.fire_lane = _fire_lane(net, s.green)
        s.long_blocks = tuple((length, rules.long_block_open_space_m(s.open_space_m, length))
                              for length in LONG_BLOCKS_M)
        s.options = _options(s, reach)
        if widening.given_sqm:
            s.concession = _concession(s)
    s.left_by_water = tuple(
        (water.kind, s.left.difference(water.kept_free), s.left.difference(water.edge_kept_free))
        for water in widening.water if water.buffer_m is not None)
    return s


def land_left_at(s: Setbacks, floors: int) -> tuple[BaseGeometry, float]:
    """The land a building of `floors` floors may stand on, each side keeping that height's own
    setback (the rules step 4 applies), and the widest of those setbacks."""
    net = s.widening.net
    sides = _sides(s, net, _road_reach(s.copy, s.widening), floors)
    return _band_and_left(net, sides)[1], max(side.metres for side in sides)


def _stop(s: Setbacks, why: str, ask: str | None) -> Setbacks:
    s.stopped, s.ask = why, ask
    return s


def _road_reach(copy: SurveyCopy, widening: Widening) -> dict[str, BaseGeometry]:
    """Where each road that meets the plot meets the net plot: its frontage on the surveyed
    boundary and any land given up to widen it."""
    out = {}
    for road in copy.roads:
        if not road.reaches or road.frontage is None or road.frontage.is_empty:
            continue
        given = [p.polygon for p in widening.pieces if p.counted and road.name in p.widens]
        out[road.name] = unary_union([road.frontage.buffer(ROAD_TOUCH_M), *given])
    return out


def _width(road: RoadSeen, height: Height) -> tuple[float, str]:
    """A road's width as the rules reckon it, and whether it is the legal or the drawn one."""
    if road is height.road:
        return height.reckoned_m, height.width_from
    if road.legal_width_m:
        return rules.reckoned_road_width_m(road.legal_width_m), "legal"
    return rules.reckoned_road_width_m(road.drawn_width_m), "drawn"


def _front_road(s: Setbacks, reach: dict[str, BaseGeometry]) -> str | None:
    """A high-rise's front is towards the main road; below high-rise, towards the bigger road
    that meets the net plot (rule 5(f)(iii)), the main road between equals."""
    roads = [road for road in s.copy.roads if road.name in reach]
    if s.high_rise or not roads:
        return s.height.road.name
    return max(roads, key=lambda road: (_width(road, s.height)[0], road is s.height.road)).name


def _sides(s: Setbacks, net: Polygon, reach: dict[str, BaseGeometry],
           floors: int) -> tuple[SideSetback, ...]:
    roads = {road.name: road for road in s.copy.roads}
    out = []
    for number, run in enumerate(straight_runs(net), 1):
        meets = tuple(name for name, ground in reach.items()
                      if run.line.intersection(ground).length >= FACES_ALONG_M)
        metres, why = _side_rule(s, floors, [roads[name] for name in meets])
        out.append(SideSetback(number, compass(facing_deg(net, run)), run.length, meets, metres,
                               why, run.line))
    return tuple(out)


def _side_rule(s: Setbacks, floors: int, meets: list[RoadSeen]) -> tuple[float, str]:
    """The open space a side keeps, and why, for a building of that many floors."""
    h = s.height
    counted = h.storeys.counted_m(floors)
    plot = s.widening.net.area
    if s.high_rise:
        col4 = rules.band_for_height(counted).min_open_space_m
        if not meets:
            return col4, "Table IV column 4"
        line = rules.table_iii_lines(plot)[-1]
        lines = [(rules.building_line_m(line, _width(road, h)[0]), road) for road in meets]
        front, road = max(lines, key=lambda pair: pair[0])
        said = f"the Building Line for {road.name}'s {_width(road, h)[1]} width is {front:g} m"
        names = ", ".join(road.name for road in meets)
        if front > col4:
            return front, f"towards {names}: {said}, higher than Table IV"
        return col4, f"towards {names}: Table IV column 4 ({said})"
    line = rules.table_iii_line(plot, counted)
    front = next((road for road in meets if road.name == s.front_road), None)
    if front is not None:
        width, how = _width(front, h)
        return (rules.building_line_m(line, width),
                f"the front, towards {front.name}, the bigger road ({how} width)")
    return line.side_m or 0.0, "Table III column 10"


def _open_space(s: Setbacks, floors: int) -> float:
    counted = s.height.storeys.counted_m(floors)
    if s.high_rise:
        return rules.band_for_height(counted).min_open_space_m
    return rules.table_iii_line(s.widening.net.area, counted).side_m or 0.0


def _band_and_left(net: Polygon, sides) -> tuple[BaseGeometry, BaseGeometry]:
    """Every point within its side's setback of that side; what is left is at least each
    side's setback from that side."""
    band = unary_union([_reach(side.line, side.metres) for side in sides if side.metres > 0])
    band = band.intersection(net)
    return band, net.difference(band)


def _reach(line: LineString, metres: float) -> BaseGeometry:
    """Every point within `metres` of the line, never less: a buffer draws its round ends as
    chords inside the circle, which left land up to 12 mm inside a 10 m setback at an inside
    corner (found in CAD, 2026-10-12); each corner of the line is also covered by a polygon
    drawn round the circle, its edges touching it, so the land left is never nearer."""
    around = metres / math.cos(math.pi / (4 * ARC_SEGMENTS))
    corners = [Point(xy).buffer(around, quad_segs=ARC_SEGMENTS) for xy in line.coords]
    return unary_union([line.buffer(metres, quad_segs=ARC_SEGMENTS), *corners])


def _fire_lane(net: Polygon, green: BaseGeometry) -> BaseGeometry:
    """Where a fire lane can run all round a high-rise (NBC Part 3 4.6(c)): the band the lane's
    width wide just inside the green strip. Where the buildings and roads put it, and its turns,
    are step 6's; where a setback is too narrow for it the band reaches into the land left."""
    reach = rules.PERIPHERAL_GREEN_STRIP_M + rules.FIRE_TENDER_MIN_WIDTH_M
    return net.boundary.buffer(reach).intersection(net).difference(green)


def _options(s: Setbacks, reach: dict[str, BaseGeometry]) -> tuple[Option, ...]:
    """Each Table IV row the road allows, up to step 2's most: the land its setbacks leave."""
    out = []
    for band in s.height.bands:
        floors = tuple(n for n in band.floors if n <= s.floors)
        if not band.served or not floors:
            continue
        sides = _sides(s, s.widening.net, reach, floors[-1])
        _, left = _band_and_left(s.widening.net, sides)
        front = max((side.metres for side in sides if s.front_road in side.roads),
                    default=band.open_space_m)
        out.append(Option(band.heights, floors, band.open_space_m, front, left.area))
    return tuple(out)


def _concession(s: Setbacks) -> Option:
    """Rule 16(e): for land given up, a high-rise may keep its sides and rear down to 7 m clear,
    the front as it is. Every side that meets a road is kept as a front (the stricter reading).
    Shown, not taken: it is one of three rewards, and only for a Master Plan or Road Development
    Plan road."""
    clear = rules.ROAD_SURRENDER_HIGH_RISE_CLEAR_M
    sides = tuple(side if side.roads else SideSetback(
        side.number, side.faces, side.length_m, side.roads, min(side.metres, clear),
        "rule 16(e) concession", side.line) for side in s.sides)
    _, left = _band_and_left(s.widening.net, sides)
    front = max((side.metres for side in sides if side.roads), default=clear)
    return Option("the same height, with the concession", (s.floors,), clear, front, left.area)
