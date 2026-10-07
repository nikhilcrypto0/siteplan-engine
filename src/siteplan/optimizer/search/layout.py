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

from collections.abc import Sequence
from dataclasses import dataclass, field

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
from siteplan.optimizer.search import fringe, ground, network
from siteplan.optimizer.search.build import Laid, Placement, named_placements
from siteplan.optimizer.search.columns import (
    Choice,
    Standing,
    choices_for,
    free_stretches,
    ground_key,
    plan_column,
)
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.land import (
    EMPTY,
    Land,
    Plot,
    erode,
    grow,
    make_land,
    plot_of,
    reserve_end,
)
from siteplan.optimizer.search.parking_plan import plan_parking, ramp_length_m
from siteplan.optimizer.search.quantities import Quantities, quantities
from siteplan.optimizer.search.readings import FloorClass, Profile, floor_classes
from siteplan.optimizer.search.road_graph import Road
from siteplan.optimizer.search.turns import Turning, loop_turns

EPS_LAND_M = 0.02  # ground a block must stand this far inside, so no rounding puts it over a line
TOUCH_M = 0.5
FACILITY_ROOM_SQM = 300.0
RESERVE_OPEN_FACTOR = 1.15
RESERVE_CLUB_FACTOR = 1.6
RAMP_RESERVE_SQM = 280.0
CLUB_ASSUMED_SHARE_OF_NET = 0.0375  # built-up area over the plot, times the club's share
CLUB_FLOORS = 2  # the club house's storeys when the brief gives none
SIDES = ("N", "S", "E", "W")
# The roads a vehicle uses; a rule 8(l) pathway serves only the block it reaches.
MOTOR_ROADS = (RoadKind.LOOP, RoadKind.INTERNAL, RoadKind.APPROACH)


@dataclass(frozen=True)
class Config:
    profile: Profile
    angle_deg: float
    offset_m: float
    max_floors: int
    reserve: str | None = None  # an end of the plot kept for the open space: N, S, E or W
    reserve_scale: float = 1.0
    low_blocks: bool = False  # blocks below the high-rise height may stand (Table III)

    @property
    def key(self) -> tuple:
        return (self.profile.key, round(self.angle_deg, 3), round(self.offset_m, 3),
                self.max_floors, self.reserve or "", self.reserve_scale, self.low_blocks)


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
    standing: tuple[Standing, ...]  # the blocks the ground holds, with the ring road round them
    streets: tuple[Road, ...]
    cluster: network.Cluster
    value: float  # saleable sqft of the blocks that stand
    kept_clear: BaseGeometry | None  # the end of the plot reserved, in the survey's frame
    fringe: tuple[fringe.Fringed, ...] = ()  # blocks below 21 m on the ground the ring leaves


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
    if not choices:
        return Failure("no floor count is left open")
    beyond = fringe.options(run.fringe_kit, classes, config.max_floors, q) \
        if config.low_blocks else []
    asked = [c.cls for c in [*choices, *beyond]]
    zone_depth = max(cls.zone_m for cls in asked)
    strip_width = max(cls.strip_m for cls in asked)
    street = max(q.road_m, max(c.cls.gap_m for c in choices) + q.gap_margin_m)
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
    standing, _ = _columns(run, config, frame, land, choices, street)
    if not standing:
        return Failure("no block fits the ground")
    fitted, streets, cluster, why = network.fit_cluster(
        standing, frame, street, land, q.road_m, q.legal_road_m,
        [s.choice.value for s in standing])
    if cluster is None:
        return Failure(why)
    if not run.brief.height_intent.mixed_heights_allowed:  # the fringe keeps the columns' height
        beyond = [c for c in beyond if c.cls.floors == fitted[0].choice.cls.floors]
    extra = fringe.place(plot, q, frame, land, cluster, fitted, beyond, own=run.own_lands,
                         kept_clear=kept_clear,
                         roads_in_setback=config.profile.roads_may_use_setback,
                         eps_m=EPS_LAND_M, room_sqm=run.reserve_target_sqm) if beyond else []
    if config.low_blocks and not extra and all(s.choice.cls.high_rise for s in fitted):
        return Failure("no block below 21 m stands in this configuration")
    return Evaluation(config, frame, land, street, tuple(fitted), tuple(streets), cluster,
                      sum(s.choice.value for s in fitted)
                      + sum(f.standing.choice.value for f in extra), kept_clear, tuple(extra))


def _columns(run: Run, config: Config, frame: Frame, land: Land, choices: list[Choice],
             street: float) -> tuple[list[Standing], float]:
    q = run.q
    base = frame.to_turned(land.cluster_land)
    net = frame.to_turned(run.plot.net)
    lands = {}
    for setback in sorted({ground_key(c.cls) for c in choices}):
        own = base.intersection(erode(net, setback + q.setback_margin_m))
        lands[setback] = erode(own, EPS_LAND_M)
    minx, _, maxx, _ = base.bounds
    minx, maxx = minx + EPS_LAND_M, maxx - EPS_LAND_M
    pitch = run.depth_m + street
    by_floors = ({None: choices} if run.brief.height_intent.mixed_heights_allowed else {
        f: [c for c in choices if c.cls.floors == f] for f in sorted({c.cls.floors
                                                                      for c in choices})})
    best: tuple[list[Standing], float] = ([], 0.0)
    for allowed in by_floors.values():
        found: list[Standing] = []
        total = 0.0
        x = minx + config.offset_m
        column = 0
        while x + run.depth_m <= maxx + 1e-9:
            stretches = {s: free_stretches(land_s, x, run.depth_m) for s, land_s in lands.items()}
            planned = plan_column(stretches, allowed, _gap(q), column, x)
            found += planned.standing
            total += planned.value
            x += pitch
            column += 1
        if total > best[1]:
            best = (found, total)
    return best


# --- The exact half: the roads, the club house, the ramp, the open space -------------------------


def lay_out(run: Run, ev: Evaluation) -> tuple[Laid | None, str]:
    q, plot, rules, brief = run.q, run.plot, run.rules, run.brief
    frame, land, cluster = ev.frame, ev.land, ev.cluster
    placements = named_placements(ev.standing, frame, [f.standing for f in ev.fringe])
    footprints = [p.footprint for p in placements]
    gaps = [p.standing.choice.cls.gap_m for p in placements]
    high = [p.standing.choice.cls.high_rise for p in placements]
    blocks = unary_union(footprints)
    blocked = unary_union([blocks, ev.kept_clear]) if ev.kept_clear is not None else blocks
    entrance, why = network.find_entrance(plot, cluster, blocked, q.approach_m,
                                          land_strip(land, q))
    if entrance is None:
        return None, why
    serving = _pathway_roads(ev, q)
    graph = network.road_graph(cluster, ev.streets, entrance,
                               [p for p in serving if p is not None])
    problems = graph.problems()
    if problems:
        return None, f"the roads are not one network: {'; '.join(problems)}"
    roads = graph.ground(MOTOR_ROADS)
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
    turns = loop_turns(cluster.ring, [Turning(*t) for t in q.turnings])
    off = turns.difference(plot.net).area + turns.intersection(
        unary_union([land.strip, plot.excluded])).area
    if off > network.RING_CLIP_SQM:
        return None, (f"a turn of the ring road lies off the plot, on the strip or in the water "
                      f"({off:,.0f} m²)")
    on_turns = [p.name for p in placements[len(ev.standing):]
                if p.footprint.intersection(turns).area > network.RING_CLIP_SQM]
    if on_turns:
        return None, f"{', '.join(on_turns)} stands where the tender turns on the ring road"
    zones = ground.zones_of(footprints, gaps, roads, lanes, q.reach_m, turns, high,
                            unary_union(pathways) if pathways else EMPTY)
    open_land = ground.open_ground(plot, land, zones)
    buildable = ground.buildable_ground(plot, open_land)

    tower_sqm = sum(p.footprint.area * p.standing.choice.cls.floors for p in placements)
    units = sum(p.standing.choice.prototype.per_floor.flats * p.standing.choice.cls.floors
                for p in placements)
    angles = [frame.angle_deg]
    anchor = entrance.gate.centroid
    club, club_floors, why = _club(run, buildable, zones, placements, tower_sqm, units, angles,
                                   anchor)
    if why:
        return None, why
    club_sqm = club.area * club_floors if club is not None else 0.0
    cores = _cores(placements)
    # no fire band is laid round a block below the high-rise height, so no cellar runs under one
    low = unary_union([f for f, tall in zip(footprints, high, strict=True) if not tall])
    plan, why = plan_parking(plot.net, plot.excluded, rules, q, footprints, cores, [],
                             tower_sqm + club_sqm, frame.angle_deg, low)
    if plan is None:
        return None, why
    ramps: list[Polygon] = []
    after_club = buildable.difference(club.buffer(ground.CLEARANCE_M, join_style="mitre")) \
        if club is not None else buildable
    if plan.levels:
        ramp = ground.place_ramp_beside_road(after_club, roads, q, ramp_length_m(q), anchor)
        if ramp is None:
            return None, "no room beside a road for the cellar ramp outside the clear ground"
        ramps = [ramp]
        plan, why = plan_parking(plot.net, plot.excluded, rules, q, footprints, cores, ramps,
                                 tower_sqm + club_sqm, frame.angle_deg, low)
        if plan is None:
            return None, why
    keep_off = [g.buffer(ground.CLEARANCE_M, join_style="mitre") for g in [club, *ramps]
                if g is not None]
    pocket_room = open_land.difference(unary_union(keep_off)) if keep_off else open_land
    pockets, total = ground.choose_open_space(pocket_room, q, frame.angle_deg)
    if total + 1e-6 < q.open_space_sqm:
        return None, (f"open space: {total:,.0f} m² of pockets 3 m wide, "
                      f"{q.open_space_sqm:,.0f} m² needed")
    room = buildable.difference(unary_union(keep_off)) if keep_off else buildable
    facilities, missed = ground.place_facilities(brief.program.amenities, rules, pockets, room,
                                                 club, angles, club.centroid if club else anchor)
    strip = land.strip.difference(unary_union([entrance.gate, entrance.approach.buffer(0.01)])) \
        if not land.strip.is_empty else EMPTY
    laid = Laid(
        frame=frame, placements=placements, graph=graph, entrance=entrance,
        lanes=lanes, pockets=pockets, strip=strip, club=club, club_floors=club_floors,
        facilities=facilities, facilities_missed=missed, ramps=ramps,
        ring_clipped=cluster.clipped, cellars=plan.cellars,
        cars=_cars(plan), zones=zones, land=land)
    return laid, ""


def _pathway_roads(ev: Evaluation, q: Quantities) -> list[Road | None]:
    """The rule 8(l) pathway that reaches each block on the fringe, numbered in their order; None
    for a block that stands against the ring road itself."""
    out: list[Road | None] = []
    for f in ev.fringe:
        out.append(None if f.path is None else network.pathway_road(
            sum(p is not None for p in out) + 1, f.path, fringe.pathway_width_m(q), ev.cluster))
    return out


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


def _club(run: Run, buildable: BaseGeometry, zones: ground.Zones, placements: list[Placement],
          tower_sqm: float, units: int, turns: Sequence[float], anchor: Point
          ) -> tuple[Polygon | None, int, str]:
    asked = run.brief.program.club_house
    floors = asked.floors or CLUB_FLOORS
    size = ground.club_size_sqm(run.q, tower_sqm, units)
    if asked.wanted.value and asked.size is ClubSize.STATED and asked.sqm:
        size = max(size, asked.sqm)
    if size <= 0:
        return None, floors, ""
    own = _club_gap_m(run.rules, floors * run.q.floor_m)
    keep = unary_union([grow(p.footprint, max(
        p.standing.choice.cls.gap_m, own,
        run.q.reach_m if p.standing.choice.cls.high_rise else 0.0)) for p in placements])
    room = buildable.difference(keep)
    club = ground.place_club(room, size / floors, turns, anchor)
    if club is None:
        return None, floors, (f"no room for a {size:,.0f} m² club house (rule 15(a)(x)) a block "
                              "gap from every block, outside the roads and the clear ground")
    return club, floors, ""


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
