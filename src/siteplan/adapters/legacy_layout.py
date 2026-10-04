"""A layout option from the prototype generator, as a CandidateLayout, and back to the reply the
chat tool gives Hermes.

Each tower becomes a LEGACY_RECTANGLE prototype (its own flats, cores and corridor, in its own
frame, made by prototypes.legacy) placed where it stood. The ground is split into one
PartitionLedger, every square metre once: where two of the generator's shapes overlap, the
earlier use in PARTITION_ORDER keeps the ground, and the rest of the net plot is UNALLOCATED with
its reason. The generator's own findings travel as claims, never as a verdict.
"""

from __future__ import annotations

import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from siteplan import rules
from siteplan.contracts.accounting import (
    LayerKind,
    Permit,
    PhysicalUse,
)
from siteplan.contracts.candidate import CandidateLayout, RoadKind
from siteplan.contracts.common import Basis, Provenance, Shape, Surface, shapes_from
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    FIRE_TURNING_RADIUS,
    OPEN_SPACE_BASIS,
)
from siteplan.layout import LayoutOption, mix_error
from siteplan.prototypes.legacy import legacy_tower
from siteplan.runner import LAYOUT_CAVEAT
from siteplan.site_amenities import AmenityItem, AmenityLibrary
from siteplan.units import sqm_to_sqft

ROAD_KINDS = {"main approach": RoadKind.APPROACH, "loop": RoadKind.LOOP,
              "internal": RoadKind.INTERNAL, "cul-de-sac": RoadKind.CUL_DE_SAC,
              "perimeter": RoadKind.PERIMETER_LANE, "driveway": RoadKind.DRIVEWAY,
              "pathway": RoadKind.PATHWAY}
LEGACY_ROAD_NAMES = {kind: name for name, kind in ROAD_KINDS.items()}
SLIVER_SQM = 0.01  # pieces smaller than this are drawing noise, not ground
ON_GROUND_SHARE = 0.5  # a facility more than this much on a piece of ground stands on it
# The ground a facility stands on, by the surface its library states. A surface nobody stated is
# never read off the facility's name: its ground is entered as an amenity and tagged as unstated.
GROUND_BY_SURFACE = {Surface.BUILT: PhysicalUse.OTHER_BUILT, Surface.HARD: PhysicalUse.HARD_AMENITY,
                     Surface.SOFT: PhysicalUse.SOFT_OPEN_SPACE}
SURFACE_UNSTATED = "SURFACE_UNSTATED"
# Where the generator's shapes overlap, the earlier use keeps the ground.
PARTITION_ORDER = (PhysicalUse.TOWER, PhysicalUse.CLUB_HOUSE, PhysicalUse.OTHER_BUILT,
                   PhysicalUse.RAMP, PhysicalUse.ROAD, PhysicalUse.SURFACE_PARKING,
                   PhysicalUse.FIRE_HARDSTANDING, PhysicalUse.HARD_AMENITY,
                   PhysicalUse.SOFT_OPEN_SPACE, PhysicalUse.GREEN_STRIP, PhysicalUse.BUFFER_LAND)
UNALLOCATED_REASON = "ground the prototype generator left without a use"


def candidate_from_option(option: LayoutOption, plot: Polygon, *, candidate_id: str,
                          site_ref: str, rules_ref: str, brief_ref: str,
                          readings: dict[str, str], access_side: str | None = None,
                          keep_out: Polygon | None = None, library_note: str = "",
                          amenities: AmenityLibrary | None = None) -> CandidateLayout:
    """`amenities` is the library the option's facilities were placed from: each placed facility
    takes its use and surface from the item of its name, when the library states them."""
    stated = _stated(amenities)
    prototypes, towers = [], []
    for tower in option.towers:
        prototype, placed = legacy_tower(tower, option.floors,
                                         f"{candidate_id}-{tower.name}", library_note)
        prototypes.append(prototype)
        towers.append(placed)
    summary = option.summary()
    return CandidateLayout(
        candidate_id=candidate_id, site_ref=site_ref, rules_ref=rules_ref, brief_ref=brief_ref,
        strategy=option.strategy, interpretation_basis=readings, prototypes_used=prototypes,
        towers=towers,
        circulation={
            "roads": [{"id": f"road-{i}", "kind": ROAD_KINDS[r.kind],
                       "shapes": shapes_from(r.shape), "declared_width_m": r.width_m,
                       "tags": ["FIRE_ACCESS"] if option.fire_lanes is not None else []}
                      for i, r in enumerate(option.roads, 1) if shapes_from(r.shape)],
            "gates": [{"shape": s, "side": access_side, "width_m": option.entrance.width_m,
                       "note": option.entrance.note}
                      for s in shapes_from(option.entrance.gate)] if option.entrance else [],
            "fire_hardstanding": shapes_from(option.fire_lanes)},
        program={
            "open_space": [Shape.from_shapely(p) for p in option.open_space],
            "green_strip": shapes_from(option.green_strip),
            "club_house": {"shape": Shape.from_shapely(option.club_house),
                           "floors": option.club_house_floors} if option.club_house else None,
            "amenities": [{"name": a.name, "shape": Shape.from_shapely(a.shape),
                           "use": stated[a.name].use if a.name in stated else None,
                           "surface": stated[a.name].surface if a.name in stated else None}
                          for a in option.amenities],
            "amenities_missed": list(option.amenities_missed),
            "ramps": [Shape.from_shapely(r) for r in option.ramps],
            "cellars": {"levels": option.parking.cellar_levels,
                        "outline": shapes_from(option.parking.cellar_outline),
                        "setback_m": option.parking.cellar_setback_m} if option.parking else None,
            "bays": [Shape.from_shapely(b) for b in option.parking_bays]},
        partition=partition(option, plot, keep_out, amenities),
        rule_layers=rule_layers(option, plot, keep_out),
        metrics={key: summary[key] for key in (
            "total_flats", "flats_by_type", "saleable_sqft", "tower_floor_sqft",
            "flats_own_sqft", "common_core_sqft", "built_up_sqft", "open_space_sqm",
            "open_space_share_pct", "mix_error")} | {"extra": {
                key: value for key, value in summary.items() if key in (
                    "parking", "height_m", "rule_height_m", "physical_height_m",
                    "orientation_deg", "towers_dropped_because", "fire_lanes_sqm")}},
        generator_claims=list(option.findings), scores={"score": option.score},
        pareto_tag=option.strategy or None, caveats=[LAYOUT_CAVEAT])


def _polygons(geometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry] if geometry.area > SLIVER_SQM else []
    return [p for part in getattr(geometry, "geoms", ()) for p in _polygons(part)]


def _stated(amenities: AmenityLibrary | None) -> dict[str, AmenityItem]:
    return {item.name: item for item in amenities.items} if amenities else {}


def partition(option: LayoutOption, plot: Polygon, keep_out: Polygon | None = None,
              amenities: AmenityLibrary | None = None) -> dict:
    """The net plot, every square metre once, by what the generator put on it. A facility's
    ground follows the surface its library states (GROUND_BY_SURFACE)."""
    stated = _stated(amenities)

    def surface(name: str) -> Surface | None:
        return stated[name].surface if name in stated else None

    def on(amenity, ground) -> bool:
        return amenity.shape.intersection(ground).area > ON_GROUND_SHARE * amenity.shape.area

    groups: dict[PhysicalUse, list[tuple[str | None, Polygon, list[str]]]] = {
        use: [] for use in PARTITION_ORDER}
    for tower in option.towers:
        groups[PhysicalUse.TOWER].append((tower.name, tower.footprint, []))
    if option.club_house is not None:
        groups[PhysicalUse.CLUB_HOUSE].append(("club house", option.club_house, []))
    for i, ramp in enumerate(option.ramps, 1):
        groups[PhysicalUse.RAMP].append((f"ramp {i}", ramp, []))
    fire = ["FIRE_ACCESS"] if option.fire_lanes is not None else []
    for i, road in enumerate(option.roads, 1):
        groups[PhysicalUse.ROAD].append((f"road-{i} {road.kind}", road.shape, fire))
    for i, bay in enumerate(option.parking_bays, 1):
        groups[PhysicalUse.SURFACE_PARKING].append((f"bay {i}", bay, []))
    if option.fire_lanes is not None:
        groups[PhysicalUse.FIRE_HARDSTANDING].append(("fire lanes", option.fire_lanes,
                                                      ["FIRE_ACCESS"]))
    open_space = unary_union(list(option.open_space)) if option.open_space else None
    # A facility on the tot-lot whose surface is soft, or not stated, is the tot-lot's ground,
    # tagged below; one stated as hard or built is its own ground, and the tot-lot loses it.
    of_the_pocket = [a for a in option.amenities if open_space is not None
                     and on(a, open_space) and surface(a.name) in (None, Surface.SOFT)]
    kept = {id(a) for a in of_the_pocket}
    for amenity in option.amenities:
        if id(amenity) in kept:
            continue
        kind = surface(amenity.name)
        tags = {None: [SURFACE_UNSTATED], Surface.SOFT: [f"AMENITY:{amenity.name}"]}.get(kind, [])
        groups[GROUND_BY_SURFACE.get(kind, PhysicalUse.HARD_AMENITY)].append(
            (amenity.name, amenity.shape, tags))
    for i, pocket in enumerate(option.open_space, 1):
        tags = [f"AMENITY:{a.name}" for a in of_the_pocket if on(a, pocket)]
        groups[PhysicalUse.SOFT_OPEN_SPACE].append((f"tot-lot {i}", pocket, tags))
    if option.green_strip is not None:
        groups[PhysicalUse.GREEN_STRIP].append(("green strip", option.green_strip, []))
    if keep_out is not None:
        groups[PhysicalUse.BUFFER_LAND].append(("water buffer", keep_out, []))
    entries, claimed = [], Polygon()
    for use in PARTITION_ORDER:
        for ref, shape, tags in groups[use]:
            piece = shape.intersection(plot).difference(claimed)
            pieces = _polygons(piece)
            if not pieces:
                continue
            ground = unary_union(pieces)
            claimed = unary_union([claimed, ground])
            entries.append({"use": use, "shapes": shapes_from(ground), "area_sqm": ground.area,
                            "ref": ref, "tags": tags})
    left = _polygons(plot.difference(claimed))
    if left:
        ground = unary_union(left)
        entries.append({"use": PhysicalUse.UNALLOCATED, "shapes": shapes_from(ground),
                        "area_sqm": ground.area, "reason": UNALLOCATED_REASON})
    return {"net_area_sqm": plot.area, "entries": entries}


def rule_layers(option: LayoutOption, plot: Polygon, keep_out: Polygon | None = None) -> dict:
    """The regulatory geometry as the generator saw it; layers overlap and are never summed."""
    layers = []
    band = rules.band_for_height(option.height_m) if option.height_m else None
    if band is not None:
        zone = plot.difference(plot.buffer(-band.min_open_space_m))
        conditional = {"permit": Permit.CONDITIONAL, "interpretation_ref": CIRCULATION_IN_SETBACK,
                       "condition": "only under the reading that circulation may run inside "
                       "the setback; not settled by the text"}
        layers.append({
            "id": "setback", "kind": LayerKind.SETBACK, "shapes": shapes_from(zone),
            "clause": f"{rules.TABLE_IV_CLAUSE}; {rules.SETBACK_ON_NET_PLOT_CLAUSE}",
            "basis": Basis.LEGAL_RULE, "status": Provenance.VERIFIED,
            "applies_to": f"{band.above_m:g}-{band.up_to_m:g} m", "area_sqm": zone.area,
            "permits": [{"use": PhysicalUse.TOWER, "permit": Permit.FORBIDDEN},
                        {"use": PhysicalUse.SURFACE_PARKING, "permit": Permit.FORBIDDEN},
                        {"use": PhysicalUse.ROAD, **conditional},
                        {"use": PhysicalUse.FIRE_HARDSTANDING, **conditional},
                        {"use": PhysicalUse.RAMP, "permit": Permit.CONDITIONAL,
                         "condition": f"{rules.RAMP_CLAUSE}: never in the front setback or "
                         "building line; in a side or rear setback only leaving "
                         f"{rules.RAMP_FIRE_CLEARANCE_M:g} m for fire vehicles"}]})
    if option.fire_lanes is not None:
        layers.append({
            "id": "fire-clear-bands", "kind": LayerKind.FIRE_CLEAR_BAND,
            "shapes": shapes_from(option.fire_lanes), "clause": rules.FIRE_ACCESS_CLAUSE,
            "basis": Basis.UNRESOLVED_INTERPRETATION, "status": Provenance.UNVERIFIED,
            "interpretation_ref": FIRE_TURNING_RADIUS, "area_sqm": option.fire_lanes.area,
            "permits": [{"use": use, "permit": Permit.FORBIDDEN} for use in (
                PhysicalUse.TOWER, PhysicalUse.CLUB_HOUSE, PhysicalUse.OTHER_BUILT,
                PhysicalUse.SURFACE_PARKING, PhysicalUse.HARD_AMENITY)]})
    if option.green_strip is not None:
        layers.append({
            "id": "green-strip", "kind": LayerKind.GREEN_STRIP_ZONE,
            "shapes": shapes_from(option.green_strip),
            "clause": rules.PERIPHERAL_GREEN_STRIP_CLAUSE, "basis": Basis.LEGAL_RULE,
            "status": Provenance.VERIFIED, "area_sqm": option.green_strip.area})
    if option.open_space:
        ground = unary_union(list(option.open_space))
        layers.append({
            "id": "qualifying-open-space", "kind": LayerKind.QUALIFYING_OPEN_SPACE,
            "shapes": shapes_from(ground), "clause": rules.OPEN_SPACE_CLAUSE,
            "basis": Basis.UNRESOLVED_INTERPRETATION, "status": Provenance.UNVERIFIED,
            "interpretation_ref": OPEN_SPACE_BASIS, "area_sqm": ground.area})
    if keep_out is not None:
        zone = keep_out.intersection(plot)
        layers.append({
            "id": "water-buffer", "kind": LayerKind.WATER_BUFFER, "shapes": shapes_from(zone),
            "clause": rules.WATER_BUFFER_CLAUSE, "basis": Basis.LEGAL_RULE,
            "status": Provenance.VERIFIED, "area_sqm": zone.area,
            "permits": [{"use": PhysicalUse.TOWER, "permit": Permit.FORBIDDEN}]})
    return {"layers": layers}


def option_keys(candidate: CandidateLayout, option: int,
                unit_mix_target: dict[str, float]) -> dict:
    """The reply the chat tool gives for one option (mcp_server.OPTION_KEYS), worked out from
    the candidate's own structure."""
    per_floor: dict[str, int] = {}
    totals: dict[str, int] = {}
    saleable = gross = common = 0.0
    for tower in candidate.towers:
        p = candidate.prototype(tower.prototype_id).per_floor
        for kind, n in p.flats_by_type.items():
            per_floor[kind] = per_floor.get(kind, 0) + n
            totals[kind] = totals.get(kind, 0) + n * tower.floors_above_stilt
        saleable += p.saleable_sqft * tower.floors_above_stilt
        gross += p.gross_floor_sqm * tower.floors_above_stilt
        common += p.common_core_sqm * tower.floors_above_stilt
    club = candidate.program.club_house
    built_up = gross + (club.shape.area_sqm * club.floors if club else 0.0)
    open_space = sum(s.area_sqm for s in candidate.program.open_space)
    net = candidate.partition.net_area_sqm if candidate.partition else math.nan
    count = sum(per_floor.values()) or 1
    return {
        "option": option,
        "floors_above_stilt": candidate.towers[0].floors_above_stilt if candidate.towers else 0,
        "towers": len(candidate.towers),
        "total_flats": sum(totals.values()),
        "flats_by_type": dict(sorted(totals.items())),
        "saleable_sqft": round(saleable),
        "tower_floor_sqft": round(sqm_to_sqft(gross)),
        "common_core_sqft": round(sqm_to_sqft(common)),
        "built_up_sqft": round(sqm_to_sqft(built_up)),
        "open_space_share_pct": round(open_space / net * 100, 2),
        "unit_mix_achieved": {k: round(v / count, 3) for k, v in sorted(per_floor.items())},
        "mix_error": round(mix_error(per_floor, unit_mix_target), 3),
        "parking": (candidate.metrics.extra.get("parking", {}) if candidate.metrics else {}),
        "roads": [{"kind": LEGACY_ROAD_NAMES[r.kind], "width_m": r.declared_width_m,
                   "area_sqm": round(sum(s.area_sqm for s in r.shapes), 1)}
                  for r in candidate.circulation.roads],
        "amenities": [{"name": a.name, "area_sqm": round(a.shape.area_sqm, 1)}
                      for a in candidate.program.amenities],
        "amenities_with_no_room": list(candidate.program.amenities_missed),
        "surface_parking_bays": len(candidate.program.bays),
        "rule_findings": {f.rule: f.status.value for f in candidate.generator_claims},
    }
