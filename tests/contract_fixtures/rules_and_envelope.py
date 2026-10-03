"""ResolvedRules and a BuildableEnvelope for made-up sites, built straight from rules.py.

Test data only: A1's resolver and envelope (src/siteplan/legal/) are the real producers. These
exist so every stream can start against the contracts before A1 lands, and they follow the
contract's rules: heights in metres, no floor count, every open reading carried.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString
from shapely.ops import polylabel, unary_union

from siteplan import parking, rules
from siteplan.contracts.accounting import DeductionKind, LayerKind, Permit, PhysicalUse
from siteplan.contracts.common import (
    Basis,
    Finding,
    Provenance,
    Shape,
    Status,
    digest,
    shapes_from,
)
from siteplan.contracts.envelope import BuildableEnvelope
from siteplan.contracts.resolved_rules import (
    ALL,
    AMENITY_SHARE,
    APPROACH_WIDTH,
    CIRCULATION_IN_SETBACK,
    FIRE_TURNING_RADIUS,
    MIXED_HEIGHT_SPACING,
    OPEN_SPACE_BASIS,
    STILT_IN_RULE_HEIGHT,
    VISITOR_PARKING,
    BandKind,
    HeightMeasure,
    ResolvedRules,
    TableVColumn,
    WhenOpen,
)
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.geometry import opening
from siteplan.provenance import weakest

LAW = {"basis": Basis.LEGAL_RULE, "status": Provenance.VERIFIED}
ENGINE = {"basis": Basis.ENGINE_DESIGN_ASSUMPTION, "status": Provenance.ASSUMED_FOR_TEST}
WIDTHS_REPORTED_M = (10.0, 15.0, 20.0, 25.0, 30.0)
REGION_SPLIT_M = 30.0  # land narrower than this is reported as a region of its own
NON_HIGH_RISE_NOTE = "Table III (rule 5) is not encoded yet: A2 reads it from the order"
ACRE_SQM = 4046.8564224


def interpretations() -> list[dict]:
    return [
        {"id": STILT_IN_RULE_HEIGHT, "selected": ALL,
         "question": "Does the stilt count toward the height that picks the Table IV row and "
                     "the high-rise class?",
         "alternatives": {"counted": "the stilt counts toward the Table IV height",
                          "not_counted": "the stilt does not count toward the Table IV height"},
         "sources": ["rule 2(e) as the engine read it",
                     "G.O.Ms.No.7 of 2016 on parking floors above ground",
                     "the firm's Dhulapally drawing behaves as if not counted (not evidence)"],
         "settles": "a sanctioned plan, or the authority's written reading"},
        {"id": OPEN_SPACE_BASIS, "selected": ALL,
         "question": "Of which area is the 10% organised open space measured?",
         "alternatives": {
             "gross_before_surrender": "the gross site area, before any land is surrendered",
             "gross_after_surrender": "the gross site area less the land surrendered",
             "net_after_surrender": "the net site area after every ownership deduction"},
         "sources": ["rule 8(g)", "rule 5(vi)"], "settles": "a sanctioned plan's area statement"},
        {"id": CIRCULATION_IN_SETBACK, "selected": ALL,
         "question": "May internal roads and fire lanes run inside the mandatory setback?",
         "alternatives": {"allowed": "roads and fire lanes may run inside the setback",
                          "not_allowed": "roads and fire lanes run outside the setback"},
         "sources": ["rule 13(c)(vii) lets ramps use side and rear setbacks leaving 7 m for fire "
                     "vehicles: an implication, not a permission"],
         "settles": "the authority's practice on sanctioned plans"},
        {"id": FIRE_TURNING_RADIUS, "selected": "outer_edge",
         "question": "Where is NBC's 9 m turning radius measured?",
         "alternatives": {"outer_edge": "at the lane's outer edge (inner edge 3 m)",
                          "centreline": "at the lane's centreline"},
         "sources": ["NBC 2016 Part 3 4.6(c)"], "settles": "the fire department's reading"},
        {"id": APPROACH_WIDTH, "selected": "minimum",
         "question": "How wide is the main approach road within rule 8(m)'s 9 to 18 m?",
         "alternatives": {"minimum": "9 m, the least the rule allows",
                          "authority_choice": "what the authority asks within 9 to 18 m"},
         "sources": ["rule 8(m)"], "settles": "the authority's practice"},
        {"id": MIXED_HEIGHT_SPACING, "selected": "taller_governs",
         "question": "Which block's Table IV gap applies between blocks of different heights?",
         "alternatives": {"taller_governs": "the taller block's gap",
                          "each_own": "each block keeps its own gap"},
         "sources": ["rule 7(a)(xii)"], "settles": "a sanctioned plan with mixed heights"},
        {"id": VISITOR_PARKING, "selected": "at_ground",
         "question": "Where must visitors' parking be?",
         "alternatives": {"at_ground": "at ground level", "anywhere": "anywhere parking is"},
         "sources": ["rule 13(c)(xii)"], "settles": "the authority's practice"},
        {"id": AMENITY_SHARE, "selected": "minimum_3_percent",
         "status": Provenance.ASSUMED_FOR_TEST,
         "question": "Is 3% of the built-up area a minimum, or a cap with 50,000 sft?",
         "alternatives": {"minimum_3_percent": "at least 3% (the 2012 wording, kept as the "
                                               "planning minimum)",
                          "up_to_3_percent_or_cap": "up to 3% or 50,000 sft, whichever is "
                                                    "lower (the 2016 wording)"},
         "sources": [rules.AMENITY_CLAUSE], "settles": "the authority's reading of the 2016 text"},
    ]


def resolved_rules(site: CanonicalSiteModel) -> ResolvedRules:
    own = site.ownership
    gross, net = own.gross_sqm.value, own.net_sqm.value
    surrendered = sum(d.area_sqm.value for d in own.deductions
                      if d.kind is DeductionKind.SURRENDER)
    road = site.access_road()
    road_m = road.legal_row_m.value if road and road.legal_row_m else None
    road_status = road.legal_row_m.status if road and road.legal_row_m else Provenance.UNVERIFIED
    columns = rules.parking_columns(site.jurisdiction.authority.value,
                                    site.jurisdiction.inside_cure.value)
    column = (TableVColumn.OPEN if len(columns) > 1 else TableVColumn.GHMC_OR_CURE
              if columns == {rules.PARKING_PERCENT_GHMC} else TableVColumn.ELSEWHERE)
    limits = []
    if road_m is not None:
        top = rules.max_height_for_road(road_m)
        limits.append({"measure": HeightMeasure.RULE_HEIGHT, "max_m": top,
                       "reason": f"the {road_m:.2f} m road serves buildings up to {top:g} m"
                       if top else "the road sets no height limit",
                       "clause": rules.TABLE_IV_CLAUSE,
                       "status": weakest(Provenance.VERIFIED, road_status)})
    dead_end = site.access.dead_end
    limits.append({"measure": HeightMeasure.PHYSICAL_HEIGHT, "max_m": rules.DEAD_END_MAX_HEIGHT_M,
                   "reason": "no dead-end road for a residential building above 30 m",
                   "clause": rules.DEAD_END_CLAUSE,
                   "status": Provenance.UNVERIFIED if dead_end.value is None
                   else Provenance.VERIFIED,
                   "applies_if": f"the access road ends at the plot (site: {dead_end.value})"})
    limits.append({"measure": HeightMeasure.AMSL, "max_m": None,
                   "reason": "no site coordinates: airport and Air Force limits not evaluated",
                   "clause": "G.O.168 rule 3(d)", "status": Provenance.UNVERIFIED})
    if net < rules.MIN_HIGH_RISE_PLOT_SQM:
        limits.append({"measure": HeightMeasure.RULE_HEIGHT, "max_m": rules.HIGH_RISE_THRESHOLD_M,
                       "reason": "the plot is too small for a high-rise",
                       "clause": rules.MIN_HIGH_RISE_PLOT_CLAUSE, "status": Provenance.VERIFIED})
    bands = [{"above_m": 0.0, "up_to_m": rules.HIGH_RISE_THRESHOLD_M,
              "kind": BandKind.NON_HIGH_RISE, "modelled": False,
              "clause": "G.O.168 rule 5, Table III", "status": Provenance.UNVERIFIED}]
    bands += [{"above_m": b.above_m, "up_to_m": b.up_to_m, "kind": BandKind.HIGH_RISE,
               "min_road_m": b.min_road_m, "setback_m": b.min_open_space_m,
               "gap_m": b.min_open_space_m, "clause": rules.TABLE_IV_CLAUSE}
              for b in rules.TABLE_IV if b.above_m >= rules.HIGH_RISE_THRESHOLD_M]
    share = rules.OPEN_SPACE_MIN_FRACTION
    gds = rules.is_group_development(gross)
    return ResolvedRules(
        site_ref=digest(site), rules_digest="rules.py at P0",
        orders=[{"id": "G.O.Ms.No.168 of 2012", "read": "TEXT"},
                {"id": "G.O.Ms.No.7 of 2016", "read": "TEXT"},
                {"id": "G.O.Ms.No.50 of 2019", "read": "SCAN"},
                {"id": "G.O.Ms.No.65 of 2019", "read": "SCAN"},
                {"id": "G.O.Ms.No.95 of 2026", "read": "SCAN"},
                {"id": "G.O.Ms.No.245 of 2012", "read": "UNREAD"},
                {"id": "G.O.Ms.No.103 of 2021", "read": "UNREAD"}],
        category={"group_development": {"value": gds, "clause": rules.GROUP_DEVELOPMENT_CLAUSE,
                                        **LAW},
                  "amenities_from_units": {"value": rules.AMENITY_MIN_UNITS,
                                           "clause": rules.AMENITY_CLAUSE, **LAW},
                  "above_5_acres": {"value": gross > 5 * ACRE_SQM,
                                    "clause": "G.O.168 rule 8(o), p.16", **LAW}},
        jurisdiction={"table_v_column": column, "when_open": WhenOpen.STOP},
        height={"measures": {
                    HeightMeasure.RULE_HEIGHT: "the height Table IV and the high-rise class are "
                    "read on; whether it includes the stilt is stilt_in_rule_height",
                    HeightMeasure.PHYSICAL_HEIGHT: "ground to the top, stilt included",
                    HeightMeasure.AMSL: "height above mean sea level"},
                "high_rise_from_m": {"value": rules.HIGH_RISE_THRESHOLD_M, "unit": "m",
                                     "clause": rules.HIGH_RISE_CLAUSE, **LAW},
                "tdr_band_m": {"value": rules.TDR_BAND_M, "unit": "m",
                               "clause": rules.TDR_BAND_CLAUSE, **LAW},
                "tdr_plot_sqm": {"value": rules.TDR_PLOT_RANGE_SQM, "unit": "m²",
                                 "clause": rules.TDR_BAND_CLAUSE, **LAW},
                "bands": bands, "limits": limits},
        setbacks={"measured_on": {"value": "net plot", "clause": rules.SETBACK_ON_NET_PLOT_CLAUSE,
                                  **LAW},
                  "front": {"value": "Table IV", "clause": rules.FRONT_SETBACK_CLAUSE, **LAW},
                  "concessions": [{"value": "down to 7 m clear on all sides",
                                   "clause": rules.ROAD_WIDENING_CLAUSE,
                                   "note": "applies only when land is surrendered for a road",
                                   **LAW}]},
        spacing={"clause": rules.BLOCK_SPACING_CLAUSE},
        open_space={"share": {"value": share, "clause": rules.OPEN_SPACE_CLAUSE, **LAW},
                    "requirement_sqm_by_reading": {
                        "gross_before_surrender": share * gross,
                        "gross_after_surrender": share * (gross - surrendered),
                        "net_after_surrender": share * net},
                    "min_width_m": {"value": rules.OPEN_SPACE_MIN_WIDTH_M, "unit": "m",
                                    "clause": rules.OPEN_SPACE_CLAUSE, **LAW},
                    "min_pocket_sqm": {"value": rules.OPEN_SPACE_MIN_POCKET_SQM, "unit": "m²",
                                       "clause": rules.OPEN_SPACE_CLAUSE, **LAW},
                    "over_and_above_setbacks": {"value": True, "clause": "G.O.168 rule 5(vi)",
                                                **LAW},
                    "block_gaps_excluded": {"value": True, "clause": rules.BLOCK_SPACING_CLAUSE,
                                            **LAW},
                    "buffer_may_count": {"value": True, "clause": "G.O.168 rule 3(a)(iii)(3)",
                                         **LAW}},
        green_strip={"width_m": {"value": rules.PERIPHERAL_GREEN_STRIP_M, "unit": "m",
                                 "clause": rules.PERIPHERAL_GREEN_STRIP_CLAUSE, **LAW},
                     "where_setback_from_m": {"value": rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M,
                                              "unit": "m",
                                              "clause": rules.PERIPHERAL_GREEN_STRIP_CLAUSE,
                                              **LAW}},
        circulation=_circulation(gds),
        fire=_fire(),
        parking=_parking(column, site),
        amenities={"share_of_built_up": {"value": rules.AMENITY_MIN_BUILT_UP_FRACTION,
                                         "clause": rules.AMENITY_CLAUSE,
                                         "basis": Basis.UNRESOLVED_INTERPRETATION,
                                         "status": Provenance.ASSUMED_FOR_TEST},
                   "cap_sqft_2016": {"value": rules.AMENITY_CAP_SQFT_2016, "unit": "sft",
                                     "clause": rules.AMENITY_CLAUSE, **LAW},
                   "from_units": {"value": rules.AMENITY_MIN_UNITS, "clause": rules.AMENITY_CLAUSE,
                                  **LAW},
                   "separate_block": {"value": "not part of a residential block, unless there is "
                                               "one block", "clause": rules.AMENITY_CLAUSE, **LAW},
                   "large_project_share_of_site": {"value": 0.05, "clause": "G.O.168 rule 8(o), "
                                                   "p.16", "note": "read from the 2012 text on "
                                                   "2026-10-02; not yet a rules.py constant",
                                                   **LAW},
                   "large_project_from_acres": {"value": 5.0, "unit": "acre",
                                                "clause": "G.O.168 rule 8(o), p.16", **LAW}},
        water={"buffer_m_by_class": {"value": dict(rules.WATER_BUFFER_M), "unit": "m",
                                     "clause": rules.WATER_BUFFER_CLAUSE, **LAW}},
        interpretations=interpretations())


def _circulation(gds: bool) -> dict:
    road = {"clause": rules.INTERNAL_ROAD_CLAUSE, **LAW}
    return {"applies": {"value": gds, "clause": rules.GROUP_DEVELOPMENT_CLAUSE, **LAW},
            "approach_m": {"value": rules.MAIN_APPROACH_ROAD_M, "unit": "m", **road},
            "internal_road_m": {"value": rules.INTERNAL_ROAD_M, "unit": "m", **road},
            "cul_de_sac_width_m": {"value": rules.CUL_DE_SAC_WIDTH_M, "unit": "m", **road},
            "cul_de_sac_length_m": {"value": rules.CUL_DE_SAC_LENGTH_M, "unit": "m", **road},
            "cul_de_sac_head_radius_m": {"value": rules.CUL_DE_SAC_HEAD_RADIUS_M, "unit": "m",
                                         **road},
            "pathway_max_block_height_m": {"value": rules.PATHWAY_MAX_BLOCK_HEIGHT_M,
                                           "unit": "m", "clause": rules.PATHWAY_CLAUSE, **LAW},
            "driveway_min_m": {"value": rules.DRIVEWAY_MIN_WIDTH_M, "unit": "m",
                               "clause": rules.DRIVEWAY_CLAUSE, **LAW},
            "driveway_is_road": {"value": False, "clause": rules.INTERNAL_ROAD_CLAUSE, **LAW},
            "block_over_12m_on_road": {"value": True, "clause": rules.PATHWAY_CLAUSE,
                                       "basis": Basis.UNRESOLVED_INTERPRETATION,
                                       "status": Provenance.UNVERIFIED,
                                       "note": "rule 8(l) read as every block above 12 m "
                                               "opening onto a road"}}


def _fire() -> dict:
    fire = {"clause": rules.FIRE_ACCESS_CLAUSE, **LAW}
    return {"applies_from_m": {"value": rules.HIGH_RISE_THRESHOLD_M, "unit": "m",
                               "clause": rules.HIGH_RISE_CLAUSE, **LAW},
            "clear_width_m": {"value": rules.FIRE_TENDER_MIN_WIDTH_M, "unit": "m", **fire},
            "turning_radius_m": {"value": rules.FIRE_TURNING_RADIUS_M, "unit": "m", **fire},
            "entrance_width_m": {"value": rules.GATE_MIN_WIDTH_M, "unit": "m",
                                 "clause": rules.GATE_CLAUSE, **LAW},
            "entrance_clear_height_m": {"value": rules.ENTRANCE_CLEAR_HEIGHT_M, "unit": "m",
                                        "clause": rules.GATE_CLAUSE, **LAW},
            "load_t": {"value": 45.0, "unit": "t", "clause": rules.FIRE_ACCESS_CLAUSE,
                       "basis": Basis.LEGAL_RULE, "status": Provenance.UNVERIFIED,
                       "note": "a paving specification the engine cannot check"},
            "street_join_m": {"value": rules.FIRE_STREET_JOIN_M, "unit": "m",
                              "clause": rules.FIRE_STREET_CLAUSE, **LAW},
            "dead_end_max_physical_m": {"value": rules.DEAD_END_MAX_HEIGHT_M, "unit": "m",
                                        "clause": rules.DEAD_END_CLAUSE, **LAW}}


def _parking(column: TableVColumn, site: CanonicalSiteModel) -> dict:
    share = {TableVColumn.GHMC_OR_CURE: rules.PARKING_PERCENT_GHMC,
             TableVColumn.ELSEWHERE: rules.PARKING_PERCENT_ELSEWHERE}
    table = [(None if math.isinf(up_to) else up_to, m) for up_to, m in
             rules.CELLAR_SETBACK_BY_SITE_SQM]
    return {"share_pct_by_column": share,
            "share_pct": None if column is TableVColumn.OPEN else {
                "value": share[column], "unit": "%", "clause": rules.PARKING_CLAUSE, **LAW},
            "visitors_fraction": {"value": rules.VISITOR_PARKING_FRACTION,
                                  "clause": rules.VISITOR_PARKING_CLAUSE, **LAW},
            "cellar_setback_by_site_sqm": {"value": table, "unit": "m",
                                           "clause": rules.CELLAR_SETBACK_CLAUSE, **LAW},
            "cellar_extra_setback_per_level_m": {"value": rules.CELLAR_EXTRA_SETBACK_PER_LEVEL_M,
                                                 "unit": "m",
                                                 "clause": rules.CELLAR_SETBACK_CLAUSE, **LAW},
            "ramp_single_min_m": {"value": rules.RAMP_SINGLE_MIN_WIDTH_M, "unit": "m",
                                  "clause": rules.RAMP_CLAUSE, **LAW},
            "ramp_pair_min_m": {"value": rules.RAMP_PAIR_MIN_WIDTH_M, "unit": "m",
                                "clause": rules.RAMP_CLAUSE, **LAW},
            "ramp_gradient": {"value": rules.RAMP_MAX_GRADIENT, "clause": rules.RAMP_CLAUSE,
                              **LAW},
            "ramp_in_setbacks": {"value": "never in the front setback or building line; side "
                                          "or rear only leaving 7 m for fire vehicles",
                                 "clause": rules.RAMP_CLAUSE, **LAW},
            "utilities_max_fraction": {"value": rules.CELLAR_UTILITIES_MAX_FRACTION,
                                       "clause": rules.CELLAR_UTILITIES_CLAUSE, **LAW},
            "measurement": {"bay_m": (parking.BAY_WIDTH_M, parking.BAY_DEPTH_M),
                            "aisle_m": parking.AISLE_M,
                            "sqm_per_car": parking.LAID_OUT_SQM_PER_CAR,
                            "note": "the engine's parking standard; no order gives it"}}


def envelope(site: CanonicalSiteModel, resolved: ResolvedRules) -> BuildableEnvelope:
    net = site.net_plot.value.to_shapely()
    exclusions, buffers = [], []
    for water in site.water:
        width = rules.WATER_BUFFER_M[water.water_class.value]
        zone = unary_union([LineString(line.points).buffer(width) for line in water.lines])
        zone = zone.intersection(net)
        if not zone.is_empty:
            buffers.append(zone)
            exclusions.append({"id": f"buffer-{water.id}", "kind": "WATER_BUFFER",
                               "shapes": shapes_from(zone), "clause": rules.WATER_BUFFER_CLAUSE,
                               "source_ref": water.id})
    excluded = unary_union(buffers) if buffers else None
    limit = next((lim.max_m for lim in resolved.height.limits
                  if lim.measure == HeightMeasure.RULE_HEIGHT and lim.max_m), None)
    bands, layers = [], []
    for band in resolved.height.bands:
        if not band.modelled:
            bands.append({"above_m": band.above_m, "up_to_m": band.up_to_m, "kind": band.kind,
                          "modelled": False, "note": NON_HIGH_RISE_NOTE})
            continue
        if limit is not None and band.above_m >= limit:
            continue
        inset = net.buffer(-band.setback_m)
        buildable = inset.difference(excluded) if excluded is not None else inset
        key = f"{band.above_m:g}-{band.up_to_m:g} m"
        bands.append({"above_m": band.above_m, "up_to_m": band.up_to_m, "kind": band.kind,
                      "setback_m": band.setback_m, "setback_envelope": shapes_from(inset),
                      "buildable": shapes_from(buildable), "area_sqm": buildable.area,
                      "green_strip_applies": band.setback_m
                      >= resolved.green_strip.where_setback_from_m.value})
        layers.append(_setback_layer(key, net.difference(inset)))
    for zone in buffers:
        layers.append({"id": f"water-buffer-{len(layers)}", "kind": LayerKind.WATER_BUFFER,
                       "shapes": shapes_from(zone), "clause": rules.WATER_BUFFER_CLAUSE,
                       "area_sqm": zone.area, "permits": [
                           {"use": PhysicalUse.TOWER, "permit": Permit.FORBIDDEN}], **LAW})
    gds = resolved.circulation.applies.value
    return BuildableEnvelope(
        site_ref=digest(site), rules_ref=digest(resolved), exclusions=exclusions, bands=bands,
        width_profiles=[_width_profile("net plot", net)],
        circulation={"access_zones": _access_zones(site, net, excluded),
                     "obligations": [
                         {"id": "gate", "applies": True, "rule_ref": "fire.entrance_width_m"},
                         {"id": "internal roads", "applies": gds,
                          "rule_ref": "circulation.internal_road_m"},
                         {"id": "main approach", "applies": gds,
                          "rule_ref": "circulation.approach_m"},
                         {"id": "fire lanes", "applies": True, "rule_ref": "fire.clear_width_m",
                          "note": "round every high-rise"},
                         {"id": "no dead end above 30 m", "applies": True,
                          "rule_ref": "fire.dead_end_max_physical_m"}]},
        requirements=[{"id": "open space", "applies": True,
                       "rule_ref": "open_space.requirement_sqm_by_reading"},
                      {"id": "club house", "applies": True,
                       "rule_ref": "amenities.share_of_built_up"},
                      {"id": "parking", "applies": True, "rule_ref": "parking.share_pct"},
                      {"id": "cellar setback", "applies": True,
                       "rule_ref": "parking.cellar_setback_by_site_sqm"}],
        rule_layers={"layers": layers},
        facts=[Finding("Group Development Scheme", Status.INFO, f"{'yes' if gds else 'no'}",
                       "4,000 m² and over", rules.GROUP_DEVELOPMENT_CLAUSE),
               Finding("Rule-height limit", Status.INFO,
                       f"{limit:g} m" if limit else "none from the road", "Table IV by road",
                       rules.TABLE_IV_CLAUSE)])


def _setback_layer(key: str, zone) -> dict:
    """A band's setback zone. Roads and fire lanes in it are CONDITIONAL on the open reading
    circulation_in_setback, never simply allowed."""
    conditional = {"permit": Permit.CONDITIONAL, "interpretation_ref": CIRCULATION_IN_SETBACK,
                   "condition": "only under the reading that circulation may run inside the "
                                "setback; not settled by the text"}
    return {"id": f"setback {key}", "kind": LayerKind.SETBACK, "shapes": shapes_from(zone),
            "clause": f"{rules.TABLE_IV_CLAUSE}; {rules.SETBACK_ON_NET_PLOT_CLAUSE}",
            "applies_to": key, "area_sqm": zone.area,
            "permits": [{"use": PhysicalUse.TOWER, "permit": Permit.FORBIDDEN},
                        {"use": PhysicalUse.SURFACE_PARKING, "permit": Permit.FORBIDDEN},
                        {"use": PhysicalUse.ROAD, **conditional},
                        {"use": PhysicalUse.FIRE_HARDSTANDING, **conditional},
                        {"use": PhysicalUse.RAMP, "permit": Permit.CONDITIONAL,
                         "condition": "side or rear setback only, leaving 7 m (13(c)(vii))"}],
            **LAW}


def _width_profile(name: str, land) -> dict:
    """The land split where it narrows below REGION_SPLIT_M, each region with its widest
    inscribed circle: a narrow arm shows as its own region, reported and not judged."""
    wide = opening(land, REGION_SPLIT_M)
    parts = [*_polygons(wide), *_polygons(land.difference(wide))]
    regions = []
    for part in parts:
        centre = polylabel(part, tolerance=0.1)
        width = 2 * part.exterior.distance(centre)
        regions.append({"shape": Shape.from_shapely(part), "area_sqm": part.area,
                        "max_inscribed_width_m": width,
                        "length_m": max(part.length / 2 - width, 0.0)})
    narrower = [(w, land.area - opening(land, w).area) for w in WIDTHS_REPORTED_M]
    return {"applies_to": name, "regions": regions, "area_narrower_than": narrower}


def _polygons(geometry) -> list:
    if geometry.is_empty:
        return []
    parts = getattr(geometry, "geoms", [geometry])
    return [p for p in parts if p.geom_type == "Polygon" and p.area > 1.0]


def _access_zones(site: CanonicalSiteModel, net, excluded) -> list[dict]:
    side = site.access.side.value
    if side is None:
        return []
    minx, miny, maxx, maxy = net.bounds
    edge = {"S": [(minx, miny), (maxx, miny)], "N": [(minx, maxy), (maxx, maxy)],
            "W": [(minx, miny), (minx, maxy)], "E": [(maxx, miny), (maxx, maxy)]}.get(side)
    if edge is None:
        return []
    frontage = LineString(edge).intersection(net.boundary.buffer(0.01))
    if excluded is not None:
        frontage = frontage.difference(excluded)
    lines = [g for g in getattr(frontage, "geoms", [frontage]) if g.geom_type == "LineString"
             and g.length > 1.0]
    return [{"id": f"access-{i}", "road_id": site.access.road_id.value, "side": side,
             "frontage": {"points": list(line.coords)}, "length_m": line.length}
            for i, line in enumerate(lines, 1)]
