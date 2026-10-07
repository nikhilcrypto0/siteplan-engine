"""A laid-out configuration as a CandidateLayout, with its own ledger and rule layers.

The candidate states what was placed and nothing it cannot back: no claim of legality (the
validator judges that), the generator's own totals worked out from the prototypes it used, a
PartitionLedger that counts every square metre of the net plot once, and the rule layers the layout
rests on. The ledger gives ground to the use that physically has it, in the validator's own order
(a building before a road, a road before a lane), so what is drawn on top of what is drawn shows up
as the claim that lost, not as two uses of one square metre.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import shapely
from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    TowerPrototype,
    digest,
)
from siteplan.contracts.accounting import LayerKind, Permit, PhysicalUse
from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Basis, Provenance, Shape, Surface, shapes_from
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT
from siteplan.optimizer.objective import mix_error
from siteplan.optimizer.search.columns import Standing
from siteplan.optimizer.search.fit import pockets_in
from siteplan.optimizer.search.frame import Frame
from siteplan.optimizer.search.ground import PlacedFacility, Zones, gap_zones
from siteplan.optimizer.search.land import EMPTY, Land, Plot, erode, grow, polygons
from siteplan.optimizer.search.network import Entrance
from siteplan.optimizer.search.parking_plan import Cellars
from siteplan.optimizer.search.quantities import Quantities
from siteplan.optimizer.search.readings import Profile
from siteplan.optimizer.search.road_graph import Road, RoadGraph
from siteplan.units import sqm_to_sqft

SLIVER_SQM = 0.01
GRID_M = 1e-6  # the ledger is drawn on a micrometre grid, as the validator's shapes are
FIRE_ROADS = (RoadKind.LOOP, RoadKind.INTERNAL, RoadKind.APPROACH)  # the roads a fire tender uses
OPEN_SPACE_CLAIM = 0.999  # what is claimed of the open space drawn: never more than counts
ON_POCKET_SHARE = 0.5  # a soft facility more than this much on a pocket is the pocket's own ground
STRATEGY_NAME = "FULL"
GROUND_BY_SURFACE = {Surface.BUILT: PhysicalUse.OTHER_BUILT, Surface.HARD: PhysicalUse.HARD_AMENITY,
                     Surface.SOFT: PhysicalUse.SOFT_OPEN_SPACE}
PARTITION_ORDER = (PhysicalUse.TOWER, PhysicalUse.CLUB_HOUSE, PhysicalUse.OTHER_BUILT,
                   PhysicalUse.RAMP, PhysicalUse.ROAD, PhysicalUse.FIRE_HARDSTANDING,
                   PhysicalUse.SURFACE_PARKING, PhysicalUse.HARD_AMENITY,
                   PhysicalUse.SOFT_OPEN_SPACE, PhysicalUse.GREEN_STRIP, PhysicalUse.BUFFER_LAND)
LAW = {"basis": Basis.LEGAL_RULE, "status": Provenance.VERIFIED}
ENGINE = {"basis": Basis.ENGINE_DESIGN_ASSUMPTION, "status": Provenance.ASSUMED_FOR_TEST}


@dataclass(frozen=True)
class Placement:
    """A block as the contract places it: where its prototype's origin stands and how it is
    turned."""

    standing: Standing
    name: str
    x: float
    y: float
    rotation_deg: float
    footprint: Polygon  # in the survey's frame, from the prototype and the placement


def placement_of(standing: Standing, name: str, frame: Frame) -> Placement:
    """The contract placement that puts this block's footprint exactly where the column holds it,
    in the block's own frame when it has one (a cluster turned to its own ground). In the turned
    frame the prototype stands a quarter turn, its origin an offset from the centre of its own
    footprint."""
    frame = standing.frame or frame
    prototype = standing.choice.prototype
    local = prototype.footprint.to_shapely()
    minx, miny, maxx, maxy = local.bounds
    bx, by = (minx + maxx) / 2, (miny + maxy) / 2
    centre = ((standing.x0 + standing.x1) / 2, (standing.y0 + standing.y1) / 2)
    origin_turned = (centre[0] + by, centre[1] - bx)  # a quarter turn takes (bx, by) to (-by, bx)
    x, y = frame.point_to_survey(*origin_turned)
    footprint = affinity.translate(affinity.rotate(local, frame.angle_deg, origin=(0, 0)), x, y)
    return Placement(standing, name, x, y, frame.angle_deg, footprint)


def _sorted_standing(standing: Sequence[Standing]) -> list[Standing]:
    return sorted(standing, key=lambda s: (s.column, s.y0))


def named_placements(standing: Sequence[Standing], frame: Frame,
                     fringe: Sequence[Standing] = ()) -> list[Placement]:
    """The blocks of the columns, named T1, T2... column by column, then the blocks on the ground
    the ring road leaves, in the order they were placed."""
    ordered = [*_sorted_standing(standing), *fringe]
    return [placement_of(s, f"T{i}", frame) for i, s in enumerate(ordered, 1)]


# --- The ledger -------------------------------------------------------------------------------


def partition(plot: Plot, claims: dict[PhysicalUse, list[tuple[str, BaseGeometry, list[str]]]]
              ) -> dict:
    """The net plot, every square metre once: where two shapes claim the same ground the earlier
    use in PARTITION_ORDER keeps it, and the rest of the plot is UNALLOCATED with its reason.

    Drawn on a micrometre grid (GRID_M), as the validator draws its own shapes: pieces that meet
    share their edge exactly, so no set operation reads float noise along it as ground counted
    twice. Off the grid, GEOS 3.13 read a street's edge against a fire lane's as a 232 m²
    overlap, and dropped a block lining the ring road's hole from a cascaded union (Dhulapally,
    2026-10-06)."""
    net = plot.net
    entries, taken = [], Polygon()
    for use in PARTITION_ORDER:
        for ref, shape, tags in claims.get(use, []):
            on_net = _areal(shapely.intersection(_areal(shape), net, grid_size=GRID_M))
            piece = polygons(shapely.difference(on_net, taken, grid_size=GRID_M), SLIVER_SQM)
            if not piece:
                continue
            ground = shapely.union_all(piece, grid_size=GRID_M)
            taken = _areal(shapely.union(taken, ground, grid_size=GRID_M))
            entries.append({"use": use, "shapes": shapes_from(ground), "area_sqm": ground.area,
                            "ref": ref, "tags": tags})
    left = polygons(shapely.difference(net, taken, grid_size=GRID_M), SLIVER_SQM)
    if left:
        ground = shapely.union_all(left, grid_size=GRID_M)
        entries.append({"use": PhysicalUse.UNALLOCATED, "shapes": shapes_from(ground),
                        "area_sqm": ground.area,
                        "reason": "ground the full search left without a use"})
    return {"net_area_sqm": net.area, "entries": entries}


def _areal(geometry: BaseGeometry) -> BaseGeometry:
    """A geometry's polygons alone: the grid's overlay takes no line or point, and where two
    pieces only touch an overlay on the grid leaves the line they touch along."""
    parts = polygons(geometry)
    return shapely.multipolygons(parts) if parts else EMPTY


# --- The candidate ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Laid:
    """Everything one configuration laid out, in the survey's frame."""

    frame: Frame
    placements: list[Placement]
    graph: RoadGraph  # every road: its centre line, its junctions, the pavement drawn from them
    entrance: Entrance
    lanes: BaseGeometry
    pockets: list[Polygon]
    strip: BaseGeometry
    club: Polygon | None
    club_floors: int
    facilities: list[PlacedFacility]
    facilities_missed: list[str]
    ramps: list[Polygon]
    clipped_rings: frozenset[str]  # the ring roads the ground cut the tip of a corner off
    cellars: Cellars | None
    cars: dict[str, int]
    zones: Zones
    land: Land

    @property
    def ring(self) -> BaseGeometry:
        """Every ring road's ground (one cluster's ring, or each of them)."""
        loops = [r.ground for r in self.graph.of_kind(RoadKind.LOOP)]
        return loops[0] if len(loops) == 1 else unary_union(loops)

    @property
    def streets(self) -> list[BaseGeometry]:
        return [r.ground for r in self.graph.of_kind(RoadKind.INTERNAL)]

    @property
    def pathways(self) -> list[BaseGeometry]:
        """Rule 8(l)'s, to blocks up to 12 m."""
        return [r.ground for r in self.graph.of_kind(RoadKind.PATHWAY)]


def build_candidate(laid: Laid, *, site: CanonicalSiteModel, rules: ResolvedRules,
                    brief: DesignBrief, plot: Plot, q: Quantities, profile: Profile,
                    envelope: BuildableEnvelope, candidate_id: str, seed: int, notes: list[str]
                    ) -> CandidateLayout:
    prototypes = _prototypes_used(laid.placements)
    towers = [{"name": p.name, "prototype_id": p.standing.choice.prototype.id, "x": p.x, "y": p.y,
               "rotation_deg": p.rotation_deg, "mirrored": False,
               "floors_above_stilt": p.standing.choice.cls.floors, "has_stilt": q.has_stilt,
               "footprint": Shape.from_shapely(p.footprint)} for p in laid.placements]
    roads = _roads(laid, q)
    gate = {"shape": Shape.from_shapely(laid.entrance.gate), "side": laid.entrance.side,
            "width_m": laid.entrance.width_m,
            "note": "the entrance on the access side with the shortest approach clear of the "
                    "blocks"}
    program = {
        "open_space": [Shape.from_shapely(p) for p in laid.pockets],
        "green_strip": shapes_from(laid.strip),
        "club_house": ({"shape": Shape.from_shapely(laid.club), "floors": laid.club_floors}
                       if laid.club is not None else None),
        "amenities": [{"name": f.request.name, "shape": Shape.from_shapely(f.shape),
                       "setting": f.request.setting, "use": f.request.use,
                       "surface": f.request.surface} for f in laid.facilities],
        "amenities_missed": list(laid.facilities_missed),
        "ramps": [Shape.from_shapely(r) for r in laid.ramps],
        "cellars": ({"levels": laid.cellars.levels, "outline": shapes_from(laid.cellars.outline),
                     "setback_m": laid.cellars.setback_m} if laid.cellars else None),
        "bays": []}
    return CandidateLayout(
        candidate_id=candidate_id, site_ref=digest(site), rules_ref=digest(rules),
        brief_ref=digest(brief), envelope_ref=digest(envelope), strategy=STRATEGY_NAME, seed=seed,
        interpretation_basis=profile.basis(), prototypes_used=prototypes, towers=towers,
        circulation={"roads": roads, "gates": [gate], "fire_hardstanding": shapes_from(laid.lanes)},
        program=program, partition=partition(plot, _claims(laid, plot, q)),
        rule_layers=_layers(laid, rules, envelope, plot),
        metrics=_metrics(laid, brief, plot, counted_open_space(laid, rules, q, plot)),
        caveats=list(notes))


def _prototypes_used(placements: Sequence[Placement]) -> list[TowerPrototype]:
    seen: dict[str, TowerPrototype] = {}
    for p in placements:
        seen.setdefault(p.standing.choice.prototype.id, p.standing.choice.prototype)
    return list(seen.values())


def _declared_m(road: Road, laid: Laid, q: Quantities) -> float:
    """The width a road declares: the rule's and the firm's margin, the rule's alone for a ring
    the ground cut the tip of a corner off, the entrance's for the approach, the rule's for a
    pathway."""
    if road.kind is RoadKind.LOOP:
        return q.legal_road_m if road.id in laid.clipped_rings else q.road_m
    if road.kind is RoadKind.APPROACH:
        return laid.entrance.width_m
    return q.pathway_m if road.kind is RoadKind.PATHWAY else q.road_m


def _roads(laid: Laid, q: Quantities) -> list[dict]:
    """Every road of the graph, each declaring the width it is drawn at: the validator measures
    the drawing and a declaration wider than the road is a claim it holds against the layout."""
    roads = [{"id": r.id, "kind": r.kind.value, "shapes": shapes_from(r.ground),
              "declared_width_m": _declared_m(r, laid, q),
              **({"tags": ["FIRE_ACCESS"]} if r.kind in FIRE_ROADS else {})}
             for r in laid.graph.roads]
    return [r for r in roads if r["shapes"]]


def _claims(laid: Laid, plot: Plot, q: Quantities
            ) -> dict[PhysicalUse, list[tuple[str, BaseGeometry, list[str]]]]:
    claims: dict[PhysicalUse, list[tuple[str, BaseGeometry, list[str]]]] = {
        use: [] for use in PARTITION_ORDER}
    for p in laid.placements:
        claims[PhysicalUse.TOWER].append((p.name, p.footprint, []))
    if laid.club is not None:
        claims[PhysicalUse.CLUB_HOUSE].append(("club house", laid.club, []))
    for i, ramp in enumerate(laid.ramps, 1):
        claims[PhysicalUse.RAMP].append((f"ramp {i}", ramp, []))
    fire = ["FIRE_ACCESS"]
    for road in laid.graph.roads:
        claims[PhysicalUse.ROAD].append((f"{road.id} {road.kind.value}", road.ground,
                                         fire if road.kind in FIRE_ROADS else []))
    if not laid.lanes.is_empty:
        claims[PhysicalUse.FIRE_HARDSTANDING].append(("fire lanes", laid.lanes, fire))
    pockets = unary_union(laid.pockets) if laid.pockets else EMPTY
    on_pockets = [f for f in laid.facilities
                  if not pockets.is_empty and f.request.surface is Surface.SOFT
                  and f.shape.intersection(pockets).area > ON_POCKET_SHARE * f.shape.area]
    for f in laid.facilities:
        if f in on_pockets:
            continue
        use = GROUND_BY_SURFACE.get(f.request.surface, PhysicalUse.HARD_AMENITY)
        tags = ["SURFACE_UNSTATED"] if f.request.surface is None else (
            [f"AMENITY:{f.request.name}"] if f.request.surface is Surface.SOFT else [])
        claims[use].append((f.request.name, f.shape, tags))
    for i, pocket in enumerate(laid.pockets, 1):
        tags = [f"AMENITY:{f.request.name}" for f in on_pockets
                if f.shape.intersection(pocket).area > ON_POCKET_SHARE * f.shape.area]
        claims[PhysicalUse.SOFT_OPEN_SPACE].append((f"open space {i}", pocket, tags))
    if not laid.strip.is_empty:
        claims[PhysicalUse.GREEN_STRIP].append(("green strip", laid.strip, []))
    if not plot.excluded.is_empty:
        claims[PhysicalUse.BUFFER_LAND].append(("water buffer", plot.excluded, []))
    return claims


def _metrics(laid: Laid, brief: DesignBrief, plot: Plot, counted_sqm: float) -> dict:
    flats: dict[str, int] = {}
    saleable = tower_sqm = own = common = 0.0
    for p in laid.placements:
        proto, floors = p.standing.choice.prototype, p.standing.choice.cls.floors
        saleable += proto.per_floor.saleable_sqft * floors
        tower_sqm += p.footprint.area * floors
        own += proto.per_floor.flats_own_sqm * floors
        common += proto.per_floor.common_core_sqm * floors
        for kind, n in proto.per_floor.flats_by_type.items():
            flats[kind] = flats.get(kind, 0) + n * floors
    club_sqm = laid.club.area * laid.club_floors if laid.club is not None else 0.0
    open_sqm = min(sum(p.area for p in laid.pockets), counted_sqm)
    return {
        "total_flats": sum(flats.values()), "flats_by_type": dict(sorted(flats.items())),
        "saleable_sqft": saleable, "tower_floor_sqft": sqm_to_sqft(tower_sqm),
        "flats_own_sqft": sqm_to_sqft(own), "common_core_sqft": sqm_to_sqft(common),
        "built_up_sqft": sqm_to_sqft(tower_sqm + club_sqm),
        "open_space_sqm": open_sqm * OPEN_SPACE_CLAIM, "open_space_share_pct":
        open_sqm * OPEN_SPACE_CLAIM / plot.net.area * 100,
        "mix_error": mix_error(flats, brief.program.unit_mix.value),
        "extra": {"parking": {"cars": dict(laid.cars)}}}


def counted_open_space(laid: Laid, rules: ResolvedRules, q: Quantities, plot: Plot) -> float:
    """What of the open space drawn counts under the strictest reading of the stilt the rules carry:
    beyond the setback zone and the gaps between blocks as that reading's heights make them, and
    outside the clear ground round the blocks it calls high-rise. A layout built for one reading
    claims no more than counts under them all. Each block's band is the contract's lookup
    (`HeightRules.band_for_block`: Table III's row on the height above the stilt), and the zone is
    taken all round at the larger of a band's front and side figures, never less than counts."""
    pockets = unary_union(laid.pockets) if laid.pockets else EMPTY
    if pockets.is_empty:
        return 0.0
    footprints = [p.footprint for p in laid.placements]
    built = unary_union([*footprints, *([laid.club] if laid.club is not None else []),
                         laid.zones.roads, laid.zones.lanes, *laid.ramps, *laid.pathways])
    least = pockets.area
    stilt = q.stilt_m if q.has_stilt else 0.0
    for reading in rules.readings(STILT_IN_RULE_HEIGHT):
        setbacks, gaps, high = [], [], []
        for p in laid.placements:
            above = p.standing.choice.cls.floors * q.floor_m
            height = above + (stilt if reading == "counted" else 0.0)
            band = rules.height.band_for_block(above, stilt, stilt_counted=reading == "counted")
            usable = band is not None and band.modelled and band.setback_m is not None
            setbacks.append(max(band.setback_m, band.front_m) if usable else 0.0)
            gaps.append((band.gap_m if band.gap_m is not None else band.setback_m) if usable
                        else 0.0)
            if height >= rules.height.high_rise_from_m.value - 1e-6:
                high.append(p.footprint)
        zone = plot.net.difference(erode(plot.net, max(setbacks, default=0.0)))
        clear = unary_union([grow(f, q.lane_m) for f in high]) if high else EMPTY
        taken = unary_union([zone, gap_zones(footprints, gaps), clear, built])
        counted = sum(piece.area for piece in pockets_in(
            pockets.intersection(plot.net).difference(taken), q.pocket_width_m, q.pocket_sqm))
        least = min(least, counted)
    return least


# --- The rule layers --------------------------------------------------------------------------


def _layer(layer_id: str, kind: LayerKind, zone: BaseGeometry, clause: str, *, applies_to: str,
           permits: list[dict] | None = None, basis: dict | None = None) -> dict | None:
    shapes = shapes_from(zone)
    if not shapes:
        return None
    return {"id": layer_id, "kind": kind, "shapes": shapes, "clause": clause,
            "applies_to": applies_to, "permits": permits or [],
            "area_sqm": sum(s.area_sqm for s in shapes), **(basis or LAW)}


def _forbid(*uses: PhysicalUse) -> list[dict]:
    return [{"use": use, "permit": Permit.FORBIDDEN} for use in uses]


def _layers(laid: Laid, rules: ResolvedRules, envelope: BuildableEnvelope, plot: Plot
            ) -> dict:
    """The envelope's layers for this site (the setback of each band, the planted strip, the ramp
    bar, the water buffer) and the layers this layout adds: the gaps between blocks, the clear
    ground round each, the motorable ground and the open space that counts."""
    layers = [layer.model_dump(mode="python") for layer in envelope.rule_layers.layers]
    taken = {layer["id"] for layer in layers}
    lane = rules.fire.clear_width_m.value
    footprints = [p.footprint for p in laid.placements]
    high = [p.footprint for p in laid.placements if p.standing.choice.cls.high_rise]
    bands = unary_union([f.buffer(lane, join_style="mitre") for f in high]).difference(
        unary_union(footprints)) if high else EMPTY
    added = [
        _layer("block gaps", LayerKind.BLOCK_GAP, laid.zones.gap_zones, rules.spacing.clause,
               applies_to="each pair of blocks closer than the gap to both",
               permits=_forbid(PhysicalUse.TOWER)),
        _layer("fire clear bands", LayerKind.FIRE_CLEAR_BAND, bands,
               rules.fire.clear_width_m.clause, applies_to="every high-rise",
               permits=_forbid(PhysicalUse.TOWER, PhysicalUse.CLUB_HOUSE, PhysicalUse.OTHER_BUILT,
                               PhysicalUse.SURFACE_PARKING, PhysicalUse.HARD_AMENITY)),
        _layer("fire access routes", LayerKind.FIRE_ACCESS_ROUTE,
               unary_union([*(r.ground for r in laid.graph.of_kind(RoadKind.LOOP)),
                            laid.entrance.approach,
                            *(r.ground for r in laid.graph.of_kind(RoadKind.INTERNAL)),
                            laid.lanes]), rules.fire.clear_width_m.clause,
               applies_to="the roads and lanes a fire tender uses"),
        _layer("turning room", LayerKind.TURNING_SECTOR,
               laid.zones.nogo.difference(laid.zones.blocks), rules.fire.turning_radius_m.clause,
               applies_to="the corners of every high-rise",
               permits=_forbid(PhysicalUse.TOWER, PhysicalUse.CLUB_HOUSE, PhysicalUse.OTHER_BUILT,
                               PhysicalUse.SURFACE_PARKING, PhysicalUse.HARD_AMENITY),
               basis={"basis": Basis.UNRESOLVED_INTERPRETATION,
                      "status": Provenance.UNVERIFIED}),
        _layer("qualifying open space", LayerKind.QUALIFYING_OPEN_SPACE,
               unary_union(laid.pockets) if laid.pockets else EMPTY, rules.open_space.share.clause,
               applies_to="the open space drawn",
               basis={"basis": Basis.UNRESOLVED_INTERPRETATION, "status": Provenance.UNVERIFIED}),
    ]
    if laid.cellars is not None:  # the rule's band, whatever part of the plot the cellar takes
        band = plot.net.difference(erode(plot.net, laid.cellars.setback_m))
        added.append(_layer("cellar setback", LayerKind.CELLAR_SETBACK, band,
                            rules.parking.cellar_setback_by_site_sqm.clause,
                            applies_to=f"{laid.cellars.levels} cellar level(s)"))
    layers += [layer for layer in added if layer is not None and layer["id"] not in taken]
    return {"layers": layers}
