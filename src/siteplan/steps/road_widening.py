"""Step 3: take off the land given up for road widening, which leaves the net plot every later
step measures from. Where that land lies comes from the architect or a drawing, never from its
area alone: when nobody has said, or what was said does not add up, the step stops and asks. A
corner where two roads meet is splayed (shown, never taken), and the rewards for the land are
shown beside it, none taken."""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.errors import GEOSException
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import polylabel, split, unary_union

from siteplan import rules
from siteplan.geometry import COMPASS_DEG, angle_gap, facing_deg, straight_runs
from siteplan.runner import NET_AREA_TOLERANCE_SQM, STRIP_AREA_TOLERANCE, load_plot
from siteplan.steps.inputs import Inputs, bearing, compass, compass_word
from siteplan.steps.survey_copy import (
    ALONG,
    ENDS_AT_DEG,
    ROAD_TOUCH_M,
    SurveyCopy,
    outside_water,
)

MIN_PIECE_SQM = 0.5  # a sliver smaller than this between two outlines is rounding, not land
THIN_M = 0.5  # land between two outlines narrower than this is a drawing difference
JUNCTION_REACH_M = 12.0  # a road this near a corner, along each of its two sides, meets there
CORNER_TURN_DEG = 20.0  # a turn of the boundary smaller than this is a bend, not a corner
LABEL_TOLERANCE_M = 0.05  # how finely a piece's widest point is searched for
ON_LINE_M = 0.05  # a piece's edge this close to a side of the plot lies along it
SIDE_DEG = 45.0  # a side facing within this of the side the answers name is that side
WATER_ALONGSIDE_M = 15.0  # the plot's edge within this of a water body's lines faces it
PLACED, OUTLINE, NONE = "placed", "outline", "none"  # how the land given up is known


@dataclass(frozen=True)
class Piece:
    area_sqm: float
    lies: str  # the side of the plot it sits on: 'east'
    widest_m: float
    why: str | None  # why it is land given up; None when nothing says it is
    widens: tuple[str, ...]  # the drawn roads that run along the same side: it widens them
    polygon: Polygon

    @property
    def counted(self) -> bool:
        return self.why is not None


@dataclass(frozen=True)
class Ground:
    """A road that may meet a corner: a drawn one, or the land given up for one."""

    name: str
    ground: BaseGeometry
    width_m: float | None
    width_from: str
    widens: tuple[str, ...] = ()  # for land given up: the drawn roads it widens


@dataclass(frozen=True)
class WaterNear:
    """A water body the project names, carried on with the net plot: rule 3(a)(ii) keeps its
    buffer free of building, and later steps keep to it. Never taken off the plot: the buffer may
    count as open space, never as a setback (rule 3(a)(iii)(3))."""

    kind: str  # 'nala_over_10m'
    buffer_m: float | None  # None for a river: 100 or 50 m, by municipal limits (asked)
    distance_m: float  # from the net plot
    lines: BaseGeometry  # as the survey draws it, outside the plot
    kept_free: BaseGeometry  # the net plot's land within the buffer of the lines drawn
    edge: BaseGeometry  # the net plot's edge the water runs alongside
    edge_kept_free: BaseGeometry  # within the buffer of that edge: if the land between the
    # line drawn and the plot is the water itself, its boundary is the plot's edge


@dataclass(frozen=True)
class Splay:
    corner: tuple[float, float]
    lies: str
    roads: tuple[str, str]
    width_m: float | None  # the wider road's width, None when neither width is known
    width_from: str
    legs_m: tuple[float, ...]  # one figure, or the two a 12 m road falls between
    areas_sqm: tuple[float, ...]
    triangle: Polygon  # for the larger leg


@dataclass
class Widening:
    inputs: Inputs
    copy: SurveyCopy
    stopped: str | None  # the engine's words, when the step stopped
    ask: str | None  # the question that would let it go on
    basis: str  # how the net plot was found, in a sentence
    route: str  # PLACED, OUTLINE or NONE
    declared: list[tuple[str, str, str]]  # what the project says: what, value, where from
    net: Polygon | None = None
    pieces: tuple[Piece, ...] = ()  # the parts at least THIN_M wide, each judged on its own
    slivers: BaseGeometry | None = None  # the parts thinner than THIN_M: drawing differences
    beyond_sqm: float = 0.0  # the net outline's area outside the surveyed boundary
    splays: tuple[Splay, ...] = ()
    water: tuple[WaterNear, ...] = ()
    high_rise_plot: bool | None = None  # rule 7(a)(ii) on the net plot; None within shortfall
    group_scheme: bool = False

    @property
    def given_sqm(self) -> float:
        return sum(p.area_sqm for p in self.pieces if p.counted)

    @property
    def difference_sqm(self) -> float:
        """Land left out of the net plot that nothing says is given up: drawing differences."""
        thin = self.slivers.area if self.slivers is not None else 0.0
        return thin + sum(p.area_sqm for p in self.pieces if not p.counted)

    @property
    def stated_given_sqm(self) -> float | None:
        """What the answers give up: the plot's area as per documents less the stated net."""
        net = self.inputs.project.site.net_sqm()
        documents = self.copy.written_sqm or self.copy.drawn_sqm
        return documents - net if net else None

    @property
    def adds_up(self) -> bool:
        stated = self.stated_given_sqm
        if stated is None or stated <= 0:
            return True
        return abs(self.given_sqm - stated) <= max(NET_AREA_TOLERANCE_SQM,
                                                   STRIP_AREA_TOLERANCE * stated)


def take_off(inputs: Inputs, copy: SurveyCopy) -> Widening:
    site = inputs.project.site
    boundary = inputs.survey.boundary
    documents = copy.written_sqm or copy.drawn_sqm  # the area as per documents
    declared = _declared(inputs)
    group = rules.is_group_development(documents)
    route = (OUTLINE if site.net_plot_m else
             PLACED if site.road_strip_m or (site.road_strip_side and site.road_strip_width_m)
             else NONE)

    def stop(reason: str, ask: str) -> Widening:
        return Widening(inputs, copy, reason, ask, "", route, declared, group_scheme=group)

    try:
        net, basis = load_plot(inputs.project, inputs.survey_path)
    except ValueError as reason:
        if route == PLACED:
            return stop(str(reason), "The strip you describe does not come to the area your "
                        "answers give up. Which is right, the area or the side and width? The "
                        "strip's outline, or the net plot's, settles it.")
        return stop(str(reason), "Where does the land given up lie? Any one of these settles "
                    "it: the side and the width of the strip, the strip's outline, or the net "
                    "plot's outline (a drawing of it is best).")
    except GEOSException as reason:
        return stop(f"The outline given could not be used: {reason}.",
                    "Send the outline again, on the survey's own frame.")
    if not net.is_valid:
        return stop("The net plot's outline crosses itself.", "Send the net plot's outline "
                    "again (a drawing of it is best).")
    beyond = net.difference(boundary).area
    if beyond > max(NET_AREA_TOLERANCE_SQM, STRIP_AREA_TOLERANCE * net.area):
        return stop(f"{beyond:,.0f} m² of the net plot's outline lies outside the surveyed plot: "
                    "it does not sit on the survey.", "Is the outline drawn on another "
                    "drawing's frame? Send it on the survey's own frame.")
    if route == NONE and not site.net_sqm():
        basis = "no land given up is recorded, so the net plot is the whole surveyed plot"
    pieces, slivers = _pieces(boundary, net, copy, site.road_strip_side, route)
    given = sum(p.area_sqm for p in pieces if p.counted)
    return Widening(inputs, copy, None, None, basis, route, declared, net, tuple(pieces),
                    slivers, beyond, tuple(_splays(net, inputs, copy, pieces)),
                    tuple(_water(inputs, net)),
                    rules.high_rise_plot_met(net.area, surrendered=given > 0), group)


def _water(inputs: Inputs, net: Polygon) -> list[WaterNear]:
    """Each water body the project names, as drawn outside the plot, with its buffer by class
    (rule 3(a)(ii)), measured from the lines drawn."""
    lines: dict[str, list] = {}
    for kind, line in outside_water(inputs):
        lines.setdefault(kind, []).append(line)
    out = []
    for kind, drawn in lines.items():
        water = unary_union(drawn)
        edge = _alongside(net, water)
        if kind == "river":  # the 2012 figure depends on municipal limits: asked, not drawn
            out.append(WaterNear(kind, None, water.distance(net), water, Polygon(), edge,
                                 Polygon()))
            continue
        buffer = rules.WATER_BUFFER_M[kind]  # the lake and nala figures are the 2012 text's
        out.append(WaterNear(kind, buffer, water.distance(net), water,
                             net.intersection(water.buffer(buffer)), edge,
                             net.intersection(edge.buffer(buffer)) if not edge.is_empty
                             else Polygon()))
    return out


def _alongside(net: Polygon, water: BaseGeometry) -> BaseGeometry:
    """The net plot's edge that runs alongside the water: within WATER_ALONGSIDE_M of its lines
    and within ENDS_AT_DEG of the direction of the nearest of them."""
    near = net.exterior.intersection(water.buffer(WATER_ALONGSIDE_M))
    banks = [LineString([a, b]) for line in getattr(water, "geoms", [water])
             if line.geom_type == "LineString"
             for a, b in zip(line.coords, line.coords[1:], strict=False) if a != b]
    keep = []
    for part in getattr(near, "geoms", [near]):
        coords = list(getattr(part, "coords", []))
        for a, b in zip(coords, coords[1:], strict=False):
            if a == b:
                continue
            piece = LineString([a, b])
            bank = min(banks, key=lambda k: k.distance(piece.centroid))
            if angle_gap(_angle(piece), _angle(bank)) <= ENDS_AT_DEG:
                keep.append(piece)
    return unary_union(keep) if keep else LineString()


def _angle(line: LineString) -> float:
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180


def _declared(inputs: Inputs) -> list[tuple[str, str, str]]:
    site = inputs.project.site
    out = []
    if site.net_sqm():
        out.append(("The net area", f"{site.net_sqm():,.1f} m²", inputs.told("net_area_sqm")))
    if site.road_strip_side or site.road_strip_width_m:
        where = " ".join(filter(None, (
            f"along the {compass_word(site.road_strip_side)} side" if site.road_strip_side
            else None,
            f"{site.road_strip_width_m:g} m wide" if site.road_strip_width_m else None)))
        out.append(("Where the strip lies", where, inputs.told("road_strip")))
    if site.road_strip_m:
        out.append(("The strip's outline", f"{len(site.road_strip_m)} corners",
                    inputs.told("road_strip_m")))
    if site.net_plot_m:
        out.append(("The net plot's outline", f"{len(site.net_plot_m)} corners",
                    inputs.told("net_plot_m")))
    return out


def _pieces(boundary: Polygon, net: Polygon, copy: SurveyCopy, named: str | None, route: str
            ) -> tuple[list[Piece], BaseGeometry]:
    """What lies between the surveyed plot and the net plot. Land the architect placed (a strip
    by its side and width, or its outline) is land given up, all of it. Where only the net plot's
    outline is given, the parts thinner than THIN_M (two outlines from different drawings
    running side by side) are drawing differences, and each wider part is judged by its own
    side: land given up when that is the side the answers name, or a road runs along it."""
    rest = boundary.difference(net)
    wide = rest
    if route == OUTLINE:
        wide = rest.buffer(-THIN_M / 2, join_style="mitre").buffer(THIN_M / 2,
                                                                     join_style="mitre")
        wide = wide.intersection(rest)
    runs = straight_runs(boundary)
    parts = [g for g in getattr(wide, "geoms", [wide])
             if g.geom_type == "Polygon" and not g.is_empty]
    out = []
    for part in (piece for g in parts for piece in _by_side(g, runs, boundary)):
        if part.area < MIN_PIECE_SQM:
            continue
        edge = part.exterior
        run = max(runs, key=lambda r: edge.intersection(r.line.buffer(ON_LINE_M)).length)
        facing = facing_deg(boundary, run)
        widens = tuple(r.name for r in copy.roads if r.meets == ALONG and r.frontage is not None
                       and r.frontage.intersection(run.line.buffer(ON_LINE_M)).length
                       > ROAD_TOUCH_M)
        if route == PLACED:
            why = "where the strip is placed"
        elif named and abs((facing - COMPASS_DEG[named] + 180) % 360 - 180) < SIDE_DEG:
            why = f"on the {compass_word(named)} side, which the answers name"
        elif widens:
            why = f"on the side {' and '.join(widens)} runs along"
        else:
            why = None
        middle = polylabel(part, LABEL_TOLERANCE_M)
        out.append(Piece(part.area, compass(facing), 2 * middle.distance(edge), why, widens,
                         part))
    return sorted(out, key=lambda p: -p.area_sqm), rest.difference(wide)


def _by_side(part: Polygon, runs, boundary: Polygon) -> list[Polygon]:
    """A piece that runs round a corner of the plot, cut there on the corner's bisector, so the
    land along each side is judged on its own. A bend within one side (both stretches facing
    the same way) is no corner."""
    pieces = [part]
    for a, b in zip(runs, runs[1:] + runs[:1], strict=False):
        if compass(facing_deg(boundary, a)) == compass(facing_deg(boundary, b)):
            continue
        corner = Point(a.line.coords[-1])
        (ax, ay), (bx, by) = a.line.coords[-2], b.line.coords[1]
        ux, uy = ax - corner.x, ay - corner.y
        vx, vy = bx - corner.x, by - corner.y
        ua, ub = math.hypot(ux, uy), math.hypot(vx, vy)
        if ua < 1e-9 or ub < 1e-9:
            continue
        dx, dy = ux / ua + vx / ub, uy / ua + vy / ub  # along the bisector of the corner
        size = math.hypot(dx, dy)
        if size < 1e-9:
            continue
        cut = []
        for piece in pieces:
            if piece.distance(corner) > ON_LINE_M or not _runs_round(piece, a, b):
                cut.append(piece)
                continue
            x0, y0, x1, y1 = piece.bounds
            reach = 2 * math.hypot(x1 - x0, y1 - y0)
            line = LineString([(corner.x - dx / size * reach, corner.y - dy / size * reach),
                               (corner.x + dx / size * reach, corner.y + dy / size * reach)])
            cut += [g for g in split(piece, line).geoms if g.geom_type == "Polygon"]
        pieces = cut
    return pieces


def _runs_round(piece: Polygon, a, b) -> bool:
    """The piece lies along both sides of the corner, each for more than twice its own width:
    a strip along one side only touches the next side across its own end."""
    width = 2 * polylabel(piece, LABEL_TOLERANCE_M).distance(piece.exterior)
    along = [piece.exterior.intersection(run.line.buffer(ON_LINE_M)).length for run in (a, b)]
    return min(along) > 2 * width


def _grounds(copy: SurveyCopy, pieces: list[Piece]) -> list[Ground]:
    """Every road that may meet a corner of the net plot: the drawn ones that reach the plot,
    and the land given up for one (its road's width is not known)."""
    out = []
    for road in (r for r in copy.roads if r.reaches and r.ground is not None):
        if road.legal_width_m:
            out.append(Ground(road.name, road.ground, road.legal_width_m, "its legal width"))
        else:
            out.append(Ground(road.name, road.ground, road.drawn_width_m,
                              "its drawn width (no legal width given)"))
    for k, piece in enumerate((p for p in pieces if p.counted), 1):
        name = (f"the land given up ({piece.lies})" if k == 1 else
                f"the land given up ({piece.lies}, part {k})")
        out.append(Ground(name, piece.polygon, None, "its road's width is not known",
                          piece.widens))
    return out


def _splays(net: Polygon, inputs: Inputs, copy: SurveyCopy, pieces: list[Piece]
            ) -> list[Splay]:
    grounds = _grounds(copy, pieces)
    runs = straight_runs(orient(net, 1.0))
    centre = net.centroid

    def same_road(x: Ground, y: Ground) -> bool:  # a strip and the road it widens
        return x.name == y.name or y.name in x.widens or x.name in y.widens

    candidates = []  # (how near the pair meets the corner, corner, the two sides, the pair)
    for a, b in zip(runs, runs[1:] + runs[:1], strict=False):
        corner = Point(a.line.coords[-1])
        if not _convex(a, b):
            continue
        near_a = a.line.intersection(corner.buffer(JUNCTION_REACH_M))
        near_b = b.line.intersection(corner.buffer(JUNCTION_REACH_M))
        on_a = [g for g in grounds if g.ground.distance(near_a) <= ROAD_TOUCH_M]
        on_b = [g for g in grounds if g.ground.distance(near_b) <= ROAD_TOUCH_M]
        pair = next(((x, y) for x in on_a for y in on_b if not same_road(x, y)), None)
        if pair is not None:
            candidates.append((0.0, corner, a, b, pair))
            continue
        # one road wraps the corner (on both sides) and another runs into it right there:
        # within its own width of the corner
        for wrap in (g for g in on_a if g in on_b):
            for road in (g for g in grounds if g.width_m and not same_road(g, wrap)
                         and g.ground.distance(corner) <= g.width_m):
                candidates.append((road.ground.distance(corner), corner, a, b, (wrap, road)))
    found: list[Splay] = []
    taken: set[frozenset] = set()
    for _, corner, a, b, pair in sorted(candidates, key=lambda c: c[0]):
        names = frozenset(g.name for g in pair)
        if names in taken:  # the same two roads meet once: at the corner nearest both
            continue
        taken.add(names)
        wider = max((g for g in pair if g.width_m), key=lambda g: g.width_m, default=None)
        legs = rules.junction_splay_legs_m(wider.width_m) if wider else ()
        triangles = [_triangle(a, b, leg) for leg in legs]
        others = [g for g in pair if g is not wider and not g.width_m]
        source = (f"{wider.name}: {wider.width_m:.2f} m, {wider.width_from}" if wider
                  else "neither road's width is known")
        if wider and others:
            source += f" ({others[0].name}: {others[0].width_from})"
        found.append(Splay(
            (corner.x, corner.y), compass(bearing((centre.x, centre.y), (corner.x, corner.y))),
            (pair[0].name, pair[1].name), wider.width_m if wider else None, source, legs,
            tuple(t.area for t in triangles), triangles[-1] if triangles else corner.buffer(0.5)))
    return found


def _convex(a, b) -> bool:
    """The boundary turns left (outward corner) at the point where run a meets run b."""
    (x0, y0), (x1, y1) = a.line.coords[-2], a.line.coords[-1]
    (_, _), (x2, y2) = b.line.coords[0], b.line.coords[1]
    ax, ay, bx, by = x1 - x0, y1 - y0, x2 - x1, y2 - y1
    cross, dot = ax * by - ay * bx, ax * bx + ay * by
    return cross > 0 and math.degrees(math.atan2(cross, dot)) >= CORNER_TURN_DEG


def _triangle(a, b, leg: float) -> Polygon:
    back = a.line.interpolate(max(0.0, a.length - leg))
    ahead = b.line.interpolate(min(leg, b.length))
    corner = a.line.coords[-1]
    return Polygon([corner, (back.x, back.y), (ahead.x, ahead.y)])
