"""One configuration, laid out: the blocks first, then the circulation they call for, then the rest.

A configuration is a profile (the readings it is built for), a direction for the blocks, where the
columns start across the plot, the tallest floor count it allows, whether blocks below the
high-rise height may stand (C3) and, when the plot has no room to spare, the end of the plot kept
for the open space. `evaluate` is the cheap half: it places the blocks in columns (columns.py) on
the ground their heights allow, then, where blocks below 21 m may stand, on the ground the ring
road leaves (fringe.py), and says what they add. `lay_out` is the exact half: it draws the streets
and the ring road from the blocks that stand, finds the entrance, joins every road into one
network of centre lines (road_graph.py) whose pavement is the layout's roads, and gives the club
house, the ramp, the open space and the facilities their ground, the cellars their levels. A
configuration whose ground cannot give one of them what the rules ask is not laid: it returns why,
and nothing is built over the shortfall.

A block below 21 m is not a high-rise: no fire lane or turning room is laid round it (rule
15(a)(i) gives no figure for it), it keeps the gap and the setback of its Table III band, and the
planting strip that band asks is drawn round the plot whenever such a block may stand.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts import (
    BuildableEnvelope,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    TowerPrototype,
)
from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.design_brief import ClubSize
from siteplan.geometry import frontage
from siteplan.optimizer.search import fringe, ground, network
from siteplan.optimizer.search.build import FIRE_ROADS, Laid, Placement, named_placements
from siteplan.optimizer.search.columns import (
    Choice,
    Standing,
    choices_for,
    free_stretches,
    ground_key,
    plan_column,
)
from siteplan.optimizer.search.frame import Frame, distinct_angles
from siteplan.optimizer.search.land import (
    EMPTY,
    Land,
    Plot,
    erode,
    grow,
    make_land,
    plot_of,
    polygons,
    reserve_end,
    setback_land,
)
from siteplan.optimizer.search.parking_plan import plan_parking, ramp_length_m
from siteplan.optimizer.search.quantities import Quantities, quantities
from siteplan.optimizer.search.readings import FloorClass, Profile, floor_classes
from siteplan.optimizer.search.road_graph import NODE_SNAP_M, Road
from siteplan.optimizer.search.turns import Turning, loop_turns
from siteplan.towers import orientations

EPS_LAND_M = 0.02  # ground a block must stand this far inside, so no rounding puts it over a line
TOUCH_M = 0.5
FACILITY_ROOM_SQM = 300.0
RESERVE_OPEN_FACTOR = 1.15
RESERVE_CLUB_FACTOR = 1.6
RAMP_RESERVE_SQM = 280.0
CLUB_ASSUMED_SHARE_OF_NET = 0.0375  # built-up area over the plot, times the club's share
CLUB_FLOORS = 2  # the club house's storeys when the brief gives none
SIDES = ("N", "S", "E", "W")
MAX_CLUSTERS = 3  # the first cluster of blocks and at most two more, each round its own ring road
ZONE_ANGLES = 4  # a further cluster is tried in its configuration's direction and three of its own


@dataclass(frozen=True)
class Config:
    profile: Profile
    angle_deg: float
    offset_m: float
    max_floors: int
    reserve: str | None = None  # an end of the plot kept for the open space: N, S, E or W
    reserve_scale: float = 1.0
    low_blocks: bool = False  # blocks below the high-rise height may stand (Table III)
    more_clusters: bool = False  # further clusters stand on the land the first leaves (C4-02)
    mixed_depths: bool = False  # columns may be of the kit's other depths too (C4-04)
    fringe_room: bool = True  # the fringe keeps the room the program is reckoned to need; False:
    # the exact half alone says whether the program still has room (C4-07)

    @property
    def key(self) -> tuple:
        return (self.profile.key, round(self.angle_deg, 3), round(self.offset_m, 3),
                self.max_floors, self.reserve or "", self.reserve_scale, self.low_blocks,
                self.more_clusters, self.mixed_depths, self.fringe_room)


@dataclass(frozen=True)
class Run:
    """What does not change over a search: the inputs, the numbers read from them, the prototypes
    and the floor counts each profile leaves open. The columns take the prototypes of one depth
    (`kit`); a block on the ground the ring road leaves may be any of them (`fringe_kit`)."""

    site: CanonicalSiteModel
    rules: ResolvedRules
    brief: DesignBrief
    envelope: BuildableEnvelope
    plot: Plot
    q: Quantities
    kit: tuple[TowerPrototype, ...]
    depth_m: float
    classes: dict[str, dict[str, list[FloorClass]]]  # profile key -> prototype id -> floor counts
    profiles: tuple[Profile, ...] = ()
    fringe_kit: tuple[TowerPrototype, ...] = ()
    own_lands: dict[tuple[float, float], BaseGeometry] = field(default_factory=dict)

    @property
    def other_depths(self) -> tuple[TowerPrototype, ...]:
        """The kit's blocks of another depth than the columns' main one (C4-04)."""
        return tuple(p for p in self.fringe_kit if round(p.depth_m, 2) != self.depth_m)

    def has_low(self, profile: Profile) -> bool:
        """Whether the profile leaves a floor count below the high-rise height open."""
        return any(not c.high_rise for found in self.classes[profile.key].values() for c in found)

    def has_high(self, profile: Profile) -> bool:
        return any(c.high_rise for found in self.classes[profile.key].values() for c in found)

    @property
    def reserve_target_sqm(self) -> float:
        club_floors = self.brief.program.club_house.floors or CLUB_FLOORS
        club = CLUB_ASSUMED_SHARE_OF_NET * self.plot.net.area * 2 / club_floors
        return (RESERVE_OPEN_FACTOR * self.q.open_space_sqm + RESERVE_CLUB_FACTOR * club
                + RAMP_RESERVE_SQM + FACILITY_ROOM_SQM)


def make_run(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
             envelope: BuildableEnvelope, kit: Sequence[TowerPrototype],
             profiles: Sequence[Profile], with_margins: bool = True) -> Run:
    q = quantities(site, rules, brief, with_margins)
    depths: dict[float, list[TowerPrototype]] = {}
    for prototype in kit:
        depths.setdefault(round(prototype.depth_m, 2), []).append(prototype)
    depth, used = max(depths.items(), key=lambda item: (len(item[1]), item[0]))
    classes = {profile.key: {p.id: floor_classes(rules, brief, p, profile) for p in kit}
               for profile in profiles}
    plot = plot_of(site, envelope)
    every = [c for found in classes.values() for counts in found.values() for c in counts]
    return Run(site, rules, brief, envelope, plot, q, tuple(used), depth, classes,
               tuple(profiles), tuple(kit), fringe.own_lands(plot, q, every))


# --- The cheap half: blocks in columns -----------------------------------------------------------


@dataclass(frozen=True)
class Failure:
    """Why a configuration lays nothing; counted and reported, never worked round."""

    reason: str


@dataclass(frozen=True)
class Evaluation:
    config: Config
    frame: Frame
    land: Land
    street_m: float
    standing: tuple[Standing, ...]  # the blocks the ground holds, with the ring roads round them
    streets: tuple[Road, ...]
    clusters: tuple[network.Cluster, ...]  # the first, then any the land it leaves holds
    value: float  # saleable sqft of the blocks that stand
    kept_clear: BaseGeometry | None  # the end of the plot reserved, in the survey's frame
    fringe: tuple[fringe.Fringed, ...] = ()  # blocks below 21 m on the ground the rings leave
    links: tuple[Road, ...] = ()  # the roads that join a further cluster's ring to another's

    @property
    def cluster(self) -> network.Cluster:
        """The first cluster, laid on all the ground the blocks may stand on."""
        return self.clusters[0]

    @property
    def rings(self) -> BaseGeometry:
        """Every ring road's ground, and the links between them."""
        return unary_union([*(c.ring for c in self.clusters), *(r.ground for r in self.links)])

    @property
    def hulls(self) -> BaseGeometry:
        return unary_union([c.hull for c in self.clusters])


def _gap(q: Quantities):
    def between(a: FloorClass, b: FloorClass) -> float:
        return fringe.need_m(q, a, b)
    return between


def evaluate(run: Run, config: Config) -> Evaluation | Failure:
    q, plot = run.q, run.plot
    classes = {pid: [c for c in found if c.floors <= config.max_floors
                     and (c.high_rise or config.low_blocks)]
               for pid, found in run.classes[config.profile.key].items()}
    choices = choices_for(run.kit, classes)
    # C4-04: in a configuration of its own, the kit's other depths may stand in columns too
    others = choices_for(run.other_depths, classes) if config.mixed_depths else []
    if not choices:
        return Failure("no floor count is left open")
    beyond = fringe.options(run.fringe_kit, classes, config.max_floors, q) \
        if config.low_blocks else []
    asked = [c.cls for c in [*choices, *others, *beyond]]
    zone_depth = max(cls.zone_m for cls in asked)
    strip_width = max(cls.strip_m for cls in asked)
    street = max(q.road_m, max(c.cls.gap_m for c in [*choices, *others]) + q.gap_margin_m)
    frame = Frame(config.angle_deg)
    kept_clear = None
    if config.reserve:
        interior_turned = frame.to_turned(erode(plot.net, zone_depth))
        region = reserve_end(interior_turned, config.reserve,
                             run.reserve_target_sqm * config.reserve_scale, q.pocket_width_m)
        if region is None:
            return Failure("the plot has no end with room for the open space")
        kept_clear = frame.to_survey(region)
    land = make_land(plot, zone_depth_m=zone_depth, strip_width_m=strip_width,
                     ring_width_m=q.road_m,
                     roads_may_use_setback=config.profile.roads_may_use_setback,
                     kept_clear=kept_clear)
    if land.cluster_land.is_empty:
        return Failure("the ring road leaves no ground for a block")
    standing, _ = _columns(run, config, frame, land, choices, street, others)
    if not standing:
        return Failure("no block fits the ground")
    fitted, streets, cluster, why = network.fit_cluster(
        standing, frame, street, land, q.road_m, q.legal_road_m,
        [s.choice.value for s in standing])
    if cluster is None:
        return Failure(why)
    if not run.brief.height_intent.mixed_heights_allowed:  # the rest keep the columns' height
        choices = [c for c in choices if c.cls.floors == fitted[0].choice.cls.floors]
        others = [c for c in others if c.cls.floors == fitted[0].choice.cls.floors]
        beyond = [c for c in beyond if c.cls.floors == fitted[0].choice.cls.floors]
    clusters: list[network.Cluster] = [cluster]
    links: list[Road] = []
    if config.more_clusters:
        fitted, streets, clusters, links = _more_clusters(run, config, frame, land, choices,
                                                          others, street, fitted, streets,
                                                          clusters)
        if len(clusters) == 1:
            return Failure("no further cluster stands on the ground the first leaves")
    if config.mixed_depths and all(round(s.choice.depth_m, 2) == run.depth_m for s in fitted):
        return Failure("no column of another depth stands")  # the same as without them
    rings = unary_union([*(c.ring for c in clusters), *(r.ground for r in links)])
    hulls = unary_union([c.hull for c in clusters])
    extra = fringe.place(plot, q, frame, land, rings, hulls, fitted, beyond, own=run.own_lands,
                         kept_clear=kept_clear,
                         roads_in_setback=config.profile.roads_may_use_setback,
                         eps_m=EPS_LAND_M,
                         room_sqm=run.reserve_target_sqm if config.fringe_room else 0.0) \
        if beyond else []
    if config.low_blocks and not extra and all(s.choice.cls.high_rise for s in fitted):
        return Failure("no block below 21 m stands in this configuration")
    return Evaluation(
        config=config, frame=frame, land=land, street_m=street, standing=tuple(fitted),
        streets=tuple(streets), clusters=tuple(clusters),
        value=sum(s.choice.value for s in fitted) + sum(f.standing.choice.value for f in extra),
        kept_clear=kept_clear, fringe=tuple(extra), links=tuple(links))


def _more_clusters(run: Run, config: Config, frame: Frame, land: Land, choices: list[Choice],
                   others: Sequence[Choice], street: float, fitted: list[Standing],
                   streets: list[Road], clusters: list[network.Cluster]
                   ) -> tuple[list[Standing], list[Road], list[network.Cluster], list[Road]]:
    """Further clusters on the ground the first leaves (an arm, a wing the first one's convex
    outline cannot take in): the blocks' land less every cluster and link laid, grown by the
    street between two columns (a ring road and a block gap, so a further cluster's blocks and
    ring keep clear of those laid), its columns fitted round with a ring road of their own, which
    a link joins to a ring already laid; until MAX_CLUSTERS stand, or the ground holds no more, or
    no link can be laid."""
    q = run.q
    fitted, streets, clusters, links = list(fitted), list(streets), list(clusters), []
    angles = [frame.angle_deg] * len(clusters)  # the direction each cluster's blocks run
    spacing = max(street, q.road_m + 2 * NODE_SNAP_M)  # the links' centre lines never touch
    while len(clusters) < MAX_CLUSTERS:
        # the laid clusters and the links laid between them, each with a street's room round it
        taken = unary_union([*(grow(c.hull, spacing) for c in clusters),
                             *(grow(r.ground, spacing) for r in links if not r.ground.is_empty)])
        rest = replace(land, cluster_land=land.cluster_land.difference(taken))
        if rest.cluster_land.is_empty:
            break
        best: tuple | None = None
        smallest = min(c.depth_m * c.length_m for c in [*choices, *others])
        for angle in zone_angles(rest.cluster_land, frame.angle_deg, smallest):  # C4-03
            turned = Frame(angle)
            standing, _ = _columns(run, config, turned, rest, choices, street, others)
            if not standing:
                continue
            more, more_streets, cluster, _ = network.fit_cluster(
                standing, turned, street, rest, q.road_m, q.legal_road_m,
                [s.choice.value for s in standing], ring_id=f"ring-{len(clusters) + 1}",
                first_street=len(streets) + 1)
            if cluster is None or _rings_cross_clusters(cluster, clusters):
                continue
            joined = network.link(cluster, clusters, land.roadable, q.road_m, len(links) + 1)
            if joined is None or _meets_askew(joined, turned, clusters, angles):
                continue
            value = sum(s.choice.value for s in more)
            if best is None or value > best[0]:
                best = (value, turned, more, more_streets, cluster, joined)
        if best is None:
            break
        _, turned, more, more_streets, cluster, joined = best
        fitted += [s if turned.angle_deg == frame.angle_deg else replace(s, frame=turned)
                   for s in more]
        streets += more_streets
        clusters.append(cluster)
        angles.append(turned.angle_deg)
        links.append(joined)
    return fitted, streets, clusters, links


def _meets_askew(joined: Road, turned: Frame, laid: Sequence[network.Cluster],
                 angles: Sequence[float]) -> bool:
    """Whether a further cluster's ring meets the ring it is joined to (their pavements overlap,
    the link has none of its own) while running another way: where two rings overlap at an angle
    the corner of one sticks out of the other in a wedge narrower than a road. A cluster turned to
    its own ground stands apart, joined by a link road."""
    if not joined.ground.is_empty:
        return False
    far = Point(joined.line.coords[-1])
    nearest = min(range(len(laid)), key=lambda i: laid[i].road.line.distance(far))
    return turned.angle_deg != angles[nearest]


def _rings_cross_clusters(cluster: network.Cluster, laid: Sequence[network.Cluster]) -> bool:
    """Whether a further cluster's ring road runs over a laid cluster, or a laid ring over it: the
    clusters keep a street apart, but a ring turned to its own ground reaches further out at its
    mitred corners than along its sides."""
    return any(cluster.ring.intersection(other.hull).area > network.RING_CLIP_SQM
               or other.ring.intersection(cluster.hull).area > network.RING_CLIP_SQM
               for other in laid)


def zone_angles(zone: BaseGeometry, given_deg: float, min_sqm: float) -> list[float]:
    """The directions a further cluster is tried in (C4-03): the configuration's own first, then
    along the principal axis of the ground it would stand on and along and across that ground's
    longest edges, no two within the turned frame's tolerance, ZONE_ANGLES at most. Ground too
    small for a block (`min_sqm`) is tried in the configuration's direction alone."""
    pieces = polygons(zone, min_sqm)
    if not pieces:
        return [given_deg]
    piece = max(pieces, key=lambda p: p.area)
    return distinct_angles([given_deg, _principal_axis_deg(piece),
                            *orientations(piece)])[:ZONE_ANGLES]


def _principal_axis_deg(piece: Polygon) -> float:
    """The direction of the long side of the smallest rectangle round a piece of ground: each
    edge of its convex hull gives a direction to try, the rectangle of least area wins (as
    legal/widths.py measures a region's length)."""
    hull = list(piece.convex_hull.exterior.coords)[:-1]
    best: tuple[float, float] | None = None
    for (x0, y0), (x1, y1) in zip(hull, [*hull[1:], hull[0]], strict=True):
        edge = math.hypot(x1 - x0, y1 - y0)
        if edge == 0:
            continue
        ux, uy = (x1 - x0) / edge, (y1 - y0) / edge
        along = [x * ux + y * uy for x, y in hull]
        across = [y * ux - x * uy for x, y in hull]
        a, b = max(along) - min(along), max(across) - min(across)
        if best is None or a * b < best[0]:
            best = (a * b, math.atan2(uy, ux) if a >= b else math.atan2(ux, -uy))
    return math.degrees(best[1]) % 180 if best else 0.0


def _columns(run: Run, config: Config, frame: Frame, land: Land, choices: list[Choice],
             street: float, others: Sequence[Choice] = ()) -> tuple[list[Standing], float]:
    """The blocks in columns across the land, column after column a street apart: every column of
    the kit's main depth, or (C4-04), where the kit has `others` of other depths, each column of
    whichever depth adds most for the width it takes; the more valuable of the two."""
    q = run.q
    base = frame.to_turned(land.cluster_land)
    net = frame.to_turned(run.plot.net)
    lands = {}
    for setback in sorted({ground_key(c.cls) for c in [*choices, *others]}):
        own = base.intersection(erode(net, setback + q.setback_margin_m))
        lands[setback] = erode(own, EPS_LAND_M)
    minx, _, maxx, _ = base.bounds
    minx, maxx = minx + EPS_LAND_M, maxx - EPS_LAND_M
    best: tuple[list[Standing], float] = ([], 0.0)
    for allowed in _by_floors(run, choices).values():
        found = _lay_columns(run, config, lands, minx, maxx, street, allowed)
        if found[1] > best[1]:
            best = found
    if others:
        for allowed in _by_floors(run, [*choices, *others]).values():
            found = _lay_columns(run, config, lands, minx, maxx, street, allowed)
            if found[1] > best[1]:
                best = found
    return best


def _by_floors(run: Run, choices: Sequence[Choice]) -> dict[int | None, list[Choice]]:
    """The blocks a layout may stand together: any, or where heights may not mix, those of one
    floor count at a time."""
    if run.brief.height_intent.mixed_heights_allowed:
        return {None: list(choices)}
    return {f: [c for c in choices if c.cls.floors == f]
            for f in sorted({c.cls.floors for c in choices})}


def _lay_columns(run: Run, config: Config, lands: dict[float, BaseGeometry], minx: float,
                 maxx: float, street: float, allowed: Sequence[Choice]
                 ) -> tuple[list[Standing], float]:
    """Columns from the configuration's offset across the land: each the depth, of those the
    blocks allowed come in, that adds the most saleable area for the width it takes (its depth and
    the street beside it); a column where none stands takes the main depth's room."""
    depths = sorted({round(c.depth_m, 2) for c in allowed}, reverse=True)
    if not depths:
        return [], 0.0
    by_depth = {d: [c for c in allowed if round(c.depth_m, 2) == d] for d in depths}
    found: list[Standing] = []
    total = 0.0
    x = minx + config.offset_m
    column = 0
    while x + min(depths) <= maxx + 1e-9:
        pick: tuple[float, float, list[Standing], float] | None = None
        for depth in depths:
            if x + depth > maxx + 1e-9:
                continue
            stretches = {s: free_stretches(land_s, x, depth) for s, land_s in lands.items()}
            planned = plan_column(stretches, by_depth[depth], _gap(run.q), column, x)
            density = planned.value / (depth + street)
            if planned.standing and (pick is None or density > pick[0]):
                pick = (density, depth, list(planned.standing), planned.value)
        if pick is None:
            if x + run.depth_m > maxx + 1e-9:
                break
            x += run.depth_m + street
        else:
            found += pick[2]
            total += pick[3]
            x += pick[1] + street
        column += 1
    return found, total


# --- The exact half: the roads, the club house, the ramp, the open space -------------------------


def lay_out(run: Run, ev: Evaluation) -> tuple[Laid | None, str]:
    q, plot = run.q, run.plot
    frame, land, clusters = ev.frame, ev.land, ev.clusters
    placements = named_placements(ev.standing, frame, [f.standing for f in ev.fringe])
    footprints = [p.footprint for p in placements]
    gaps = [p.standing.choice.cls.gap_m for p in placements]
    high = [p.standing.choice.cls.high_rise for p in placements]
    blocks = unary_union(footprints)
    blocked = unary_union([blocks, ev.kept_clear]) if ev.kept_clear is not None else blocks
    entrance, why = network.find_entrance(plot, clusters, blocked, q.approach_m,
                                          land_strip(land, q))
    if entrance is None:
        return None, why
    serving = _pathway_roads(ev, q)
    graph = network.road_graph(clusters, ev.streets, ev.links, entrance,
                               [p for p in serving if p is not None])
    problems = graph.problems()
    if problems:
        return None, f"the roads are not one network: {'; '.join(problems)}"
    roads = graph.ground(FIRE_ROADS)  # a rule 8(l) pathway serves only the block it reaches
    pathways = [r.ground for r in graph.of_kind(RoadKind.PATHWAY)]
    lanes = network.fire_lanes([f for f, tall in zip(footprints, high, strict=True) if tall],
                               roads, plot.net, q.lane_m, blocks)
    reason = _lanes_misplaced(lanes, land)
    if reason:
        return None, reason
    ways = [EMPTY] * len(ev.standing) + [p.ground if p is not None else EMPTY for p in serving]
    unserved = [p.name for p, way in zip(placements, ways, strict=True)
                if not _served(p, roads, way)]
    if unserved:
        return None, f"no road touches {', '.join(unserved)}"
    turnings = [Turning(*t) for t in q.turnings]
    turns_of = [(c, loop_turns(c.ring, turnings)) for c in clusters]
    turns = unary_union([t for _, t in turns_of])
    off = turns.difference(plot.net).area + turns.intersection(
        unary_union([land.strip, plot.excluded])).area
    if off > network.RING_CLIP_SQM:
        return None, (f"a turn of the ring road lies off the plot, on the strip or in the water "
                      f"({off:,.0f} m²)")
    # a block keeps off where the tender turns on every ring but its own cluster's (whose blocks
    # stand within it); a block on the fringe belongs to no cluster
    on_turns = [p.name for i, p in enumerate(placements)
                if any(p.footprint.intersection(t).area > network.RING_CLIP_SQM
                       for c, t in turns_of
                       if i >= len(ev.standing) or not _within(p.footprint, c.hull))]
    if on_turns:
        return None, f"{', '.join(on_turns)} stands where the tender turns on the ring road"
    zones = ground.zones_of(footprints, gaps, roads, lanes, q.reach_m, turns, high,
                            unary_union(pathways) if pathways else EMPTY)
    open_land = ground.open_ground(plot, land, zones)
    buildable = ground.buildable_ground(plot, open_land)

    tower_sqm = sum(p.footprint.area * p.standing.choice.cls.floors for p in placements)
    units = sum(p.standing.choice.prototype.per_floor.flats * p.standing.choice.cls.floors
                for p in placements)
    angles = distinct_angles([frame.angle_deg,
                              *(s.frame.angle_deg for s in ev.standing if s.frame)])
    program = _Program(
        land=land, open_land=open_land, buildable=buildable, zones=zones, placements=placements,
        stilts=_stilts(footprints, unary_union([roads, lanes, *pathways]), q),
        roads=roads, tower_sqm=tower_sqm, units=units, angles=angles, angle_deg=frame.angle_deg,
        anchor=entrance.gate.centroid, cores=_cores(placements),
        # no fire band is laid round a block below the high-rise height, so no cellar runs under
        # one
        low=unary_union([f for f, tall in zip(footprints, high, strict=True) if not tall]))
    furnished, why = _furnish(run, program)
    repair = RAMP_FIRST if why == NO_RAMP else CLUB_OFF_OPEN if why.startswith(NO_OPEN) else None
    if furnished is None and repair is not None:  # C4-07: the same blocks, the program laid again
        furnished = _furnish(run, program, repair)[0]
    if furnished is None:
        return None, why
    strip = land.strip.difference(unary_union([entrance.gate, entrance.approach.buffer(0.01)])) \
        if not land.strip.is_empty else EMPTY
    laid = Laid(
        frame=frame, placements=placements, graph=graph, entrance=entrance,
        lanes=lanes, pockets=furnished.pockets, strip=strip, club=furnished.club,
        club_floors=furnished.club_floors, facilities=furnished.facilities,
        facilities_missed=furnished.missed, ramps=furnished.ramps,
        clipped_rings=frozenset(c.road.id for c in clusters if c.clipped),
        cellars=furnished.plan.cellars, cars=_cars(furnished.plan), zones=zones, land=land)
    return laid, ""


def _stilts(footprints: Sequence[Polygon], way_in: BaseGeometry, q: Quantities
            ) -> list[Polygon]:
    """The blocks whose stilt a car can drive into, the only stilts that hold cars (C4-07): a
    driveway's width of the outline (rule 13(c)(viii)) facing a road, a fire lane or a pathway, as
    the validator holds it, and a hair more. The parking plan counted every stilt."""
    return [f for f in footprints
            if frontage(f, way_in, TOUCH_M) >= q.driveway_m + network.EPS_M]


NO_RAMP = "no room beside a road for the cellar ramp outside the clear ground"
NO_OPEN = "open space:"
RAMP_FIRST, CLUB_OFF_OPEN = "ramp first", "club house off the open space"  # C4-07's repairs


@dataclass(frozen=True)
class _Program:
    """What the program (the club house, the cellars and their ramp, the open space and the
    facilities) is laid on, once the blocks and the roads stand."""

    land: Land
    open_land: BaseGeometry
    buildable: BaseGeometry
    zones: ground.Zones
    placements: list[Placement]
    stilts: list[Polygon]  # the blocks whose stilt a car can drive into
    roads: BaseGeometry
    tower_sqm: float
    units: int
    angles: list[float]
    angle_deg: float  # the configuration's direction: the cellars' and the pockets' grid
    anchor: Point
    cores: list[BaseGeometry]
    low: BaseGeometry


@dataclass(frozen=True)
class _Furnished:
    club: Polygon | None
    club_floors: int
    plan: object
    ramps: list[Polygon]
    pockets: list[Polygon]
    facilities: list
    missed: list[str]


def _furnish(run: Run, program: _Program, repair: str | None = None
             ) -> tuple[_Furnished | None, str]:
    """The program on the ground the blocks and roads leave: the club house first, nearest the
    gate; the cellars and, when they are needed, their ramp beside a road; the open space; the
    facilities. Or (C4-07) one of two repairs, tried when that order left no room for the ramp or
    for the open space: `RAMP_FIRST` lays the ramp, which has the least choice of ground, before
    the club house, which may stand in any of the directions and anywhere its own band allows;
    `CLUB_OFF_OPEN` keeps the club house off the ground the open space may take."""
    q, plot, rules, p = run.q, run.plot, run.rules, program
    angle = p.angle_deg

    def parking(club_sqm: float, ramps: list[Polygon]):
        return plan_parking(plot.net, plot.excluded, rules, q, p.stilts, p.cores, ramps,
                            p.tower_sqm + club_sqm, angle, p.low)

    ramps: list[Polygon] = []
    avoid = p.open_land if repair == CLUB_OFF_OPEN else EMPTY
    if repair == RAMP_FIRST:
        plan, why = parking(_club_size(run, p.tower_sqm, p.units), [])
        if plan is None:
            return None, why
        if plan.levels:
            ramp = ground.place_ramp_beside_road(p.buildable, p.roads, q, ramp_length_m(q),
                                                 p.anchor)
            if ramp is None:
                return None, NO_RAMP
            ramps = [ramp]
            avoid = ramp.buffer(ground.CLEARANCE_M, join_style="mitre")
    club, club_floors, why = _club(run, p.land, p.buildable, p.zones, p.placements, p.tower_sqm,
                                   p.units, p.angles, p.anchor, avoid)
    if why:
        return None, why
    club_sqm = club.area * club_floors if club is not None else 0.0
    plan, why = parking(club_sqm, ramps)
    if plan is None:
        return None, why
    if plan.levels and not ramps:
        after_club = p.buildable.difference(club.buffer(ground.CLEARANCE_M, join_style="mitre")) \
            if club is not None else p.buildable
        ramp = ground.place_ramp_beside_road(after_club, p.roads, q, ramp_length_m(q), p.anchor)
        if ramp is None:
            return None, NO_RAMP
        ramps = [ramp]
        plan, why = parking(club_sqm, ramps)
        if plan is None:
            return None, why
    keep_off = [g.buffer(ground.CLEARANCE_M, join_style="mitre") for g in [club, *ramps]
                if g is not None]
    pocket_room = p.open_land.difference(unary_union(keep_off)) if keep_off else p.open_land
    pockets, total = ground.choose_open_space(
        pocket_room, q, angle, unary_union([pl.footprint for pl in p.placements]))
    if total + 1e-6 < q.open_space_sqm:
        return None, (f"{NO_OPEN} {total:,.0f} m² of pockets 3 m wide, "
                      f"{q.open_space_sqm:,.0f} m² needed")
    room = p.buildable.difference(unary_union(keep_off)) if keep_off else p.buildable
    facilities, missed = ground.place_facilities(run.brief.program.amenities, rules, pockets,
                                                 room, club, p.angles,
                                                 club.centroid if club else p.anchor)
    return _Furnished(club, club_floors, plan, ramps, pockets, facilities, missed), ""


def _pathway_roads(ev: Evaluation, q: Quantities) -> list[Road | None]:
    """The rule 8(l) pathway that reaches each block on the fringe, numbered in their order; None
    for a block that stands against the ring road itself."""
    out: list[Road | None] = []
    for f in ev.fringe:
        out.append(None if f.path is None else network.pathway_road(
            sum(p is not None for p in out) + 1, f.path, fringe.pathway_width_m(q), ev.clusters))
    return out


def _within(footprint: Polygon, hull: Polygon) -> bool:
    return footprint.difference(hull).area <= network.RING_CLIP_SQM


def _served(placement: Placement, roads: BaseGeometry, pathway: BaseGeometry) -> bool:
    """A block opens onto a road, or a pathway that branches out of one reaches it (rule 8(l):
    fringe.py draws one only to a block it may serve)."""
    if placement.footprint.distance(roads) <= TOUCH_M:
        return True
    return (not pathway.is_empty and pathway.distance(roads) <= TOUCH_M
            and placement.footprint.distance(pathway) <= TOUCH_M)


def land_strip(land: Land, q: Quantities) -> float:
    return q.strip_width_m if not land.strip.is_empty else 0.0


def _lanes_misplaced(lanes: BaseGeometry, land: Land) -> str:
    if lanes.is_empty:
        return ""
    if lanes.intersection(land.strip).area > network.RING_CLIP_SQM:
        return "a fire lane runs on the planted strip"
    return ""


def _club_size(run: Run, tower_sqm: float, units: int) -> float:
    """The club house's built-up area: rule 15(a)(x)'s share, or the size the brief states where
    that is larger."""
    asked = run.brief.program.club_house
    size = ground.club_size_sqm(run.q, tower_sqm, units)
    if asked.wanted.value and asked.size is ClubSize.STATED and asked.sqm:
        size = max(size, asked.sqm)
    return size


def _club(run: Run, land: Land, buildable: BaseGeometry, zones: ground.Zones,
          placements: list[Placement], tower_sqm: float, units: int, turns: Sequence[float],
          anchor: Point, avoid: BaseGeometry = EMPTY) -> tuple[Polygon | None, int, str]:
    floors = run.brief.program.club_house.floors or CLUB_FLOORS
    size = _club_size(run, tower_sqm, units)
    if size <= 0:
        return None, floors, ""
    own = _club_gap_m(run.rules, floors * run.q.floor_m)
    keep = unary_union([grow(p.footprint, max(
        p.standing.choice.cls.gap_m, own,
        run.q.reach_m if p.standing.choice.cls.high_rise else 0.0)) for p in placements])
    room = _club_ground(run, land, zones, floors, buildable).difference(
        unary_union([keep, avoid]))
    # C4-07: in the plot's own directions too, where the ground the towers leave often runs
    club = ground.place_club(room, size / floors,
                             distinct_angles([*turns, *orientations(run.plot.net)]), anchor)
    if club is None:
        return None, floors, (f"no room for a {size:,.0f} m² club house (rule 15(a)(x)) a block "
                              "gap from every block, outside the roads and the clear ground")
    return club, floors, ""


def _club_ground(run: Run, land: Land, zones: ground.Zones, floors: int,
                 buildable: BaseGeometry) -> BaseGeometry:
    """Ground the club house may stand on (C4-07): what its own band's setbacks leave, Table III's
    for its height as the validator holds it (rule 15(a)(x) makes it a building of its own), less
    the planted strip, the roads, pathways and lanes, the clear ground and the turns round the
    high-rises, the blocks and the gaps between them, and the statutory exclusions. It stood only
    beyond the setback of the tallest tower, a wider band than its own, which kept it off an arm
    or a strip of the plot it may use. Where the rules model no band for its height, as before."""
    q = run.q
    band = run.rules.height.band_for_block(floors * q.floor_m, 0.0, stilt_counted=False)
    if band is None or not band.modelled or band.setback_m is None:
        return buildable
    front = band.front_m if band.front_setback_m is not None else band.setback_m
    own = setback_land(run.plot, front + q.setback_margin_m, band.setback_m + q.setback_margin_m)
    taken = [g for g in (land.strip, zones.nogo, zones.roads, zones.lanes, zones.gap_zones,
                         zones.blocks, zones.turns, zones.pathways, run.plot.excluded)
             if not g.is_empty]
    return own.difference(unary_union(taken)) if taken else own


def _club_gap_m(rules: ResolvedRules, height_m: float) -> float:
    """The gap the club house's own band asks of a block beside it (it has no stilt): between two
    blocks below 21 m the taller one's side setback governs (rule 5(f)(xiii)), so a block lower
    than the club house keeps the club house's. Nothing where the rules model no band for it."""
    band = rules.height.band_for_block(height_m, 0.0, stilt_counted=False)
    if band is None or not band.modelled or band.setback_m is None:
        return 0.0
    return band.gap_m if band.gap_m is not None else band.setback_m


def _cores(placements: Sequence[Placement]) -> list[BaseGeometry]:
    out: list[BaseGeometry] = []
    for p in placements:
        for zone in p.standing.choice.prototype.core_zones:
            turned = affinity.rotate(zone.shape.to_shapely(), p.rotation_deg, origin=(0, 0))
            out.append(affinity.translate(turned, p.x, p.y))
    return out


def _cars(plan) -> dict[str, int]:
    cars = {"stilt": plan.stilt_cars}
    if plan.cellars is not None:
        for level in range(1, plan.cellars.levels + 1):
            cars[f"cellar {level}"] = plan.cellars.per_level_cars
    return cars


def reserve_sides() -> tuple[str, ...]:
    return SIDES


__all__ = ["Config", "Evaluation", "Failure", "Run", "evaluate", "lay_out", "make_run"]
