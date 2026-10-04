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
    FacilityUse,
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
    HEIGHT_TOL_M,
    MIXED_HEIGHT_SPACING,
    OPEN_SPACE_BASIS,
    OPEN_SPACE_OTHER_USES,
    STILT_IN_RULE_HEIGHT,
    TOT_LOT_SURFACE,
    VISITOR_PARKING,
    Applicability,
    Band,
    BandKind,
    Eligibility,
    EligibilityGround,
    HeightMeasure,
    HighRiseEligibility,
    LimitBound,
    ResolvedRules,
    SiteFact,
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
AIRPORT_CLAUSE = "G.O.168 rule 3(d) (airport and Air Force height limits)"
PROHIBITED_NOTE = ("No building of the high-rise height or more may stand here. That permits "
                   "nothing below it: what may be built below it is the non-high-rise bands' "
                   "(Table III: the permissible height, its setbacks, the road it asks and the "
                   "spacing), each band with its own permission.")


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
         "sources": [f"{rules.OPEN_SPACE_CLAUSE}: 'at least 10% of total site area'",
                     "G.O.168 rule 8(g): 'Minimum of 10% of site area'"],
         "settles": "a sanctioned plan's area statement"},
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
        {"id": TOT_LOT_SURFACE, "selected": ALL,
         "question": "Must a tot-lot stand on soft ground to count as organised open space?",
         "alternatives": {"any_surface": "a tot-lot counts whatever its surface: the rule names "
                                         "the tot-lot and does not say what it is laid on",
                          "soft_only": "a tot-lot counts only on soft ground"},
         "sources": [f"{rules.OPEN_SPACE_CLAUSE}: 'greenery, tot lot or soft landscaping, etc.'"],
         "settles": "a sanctioned plan whose counted tot-lot is paved, or the authority's "
                    "reading"},
        {"id": OPEN_SPACE_OTHER_USES, "selected": ALL,
         "question": "Does the rule's 'etc.' take in open recreation other than the uses it "
                     "names?",
         "alternatives": {"same_kind_only": "only greenery, a tot-lot and soft landscaping "
                                            "count",
                          "any_open_recreation": "any recreation open to the sky counts too (a "
                                                 "court, a pool, a paved deck)"},
         "sources": [f"{rules.OPEN_SPACE_CLAUSE}: 'greenery, tot lot or soft landscaping, etc.'"],
         "settles": "the organised open space a sanctioned plan's area statement counts"},
    ]


def height_bands(site: CanonicalSiteModel) -> list[dict]:
    """Every height in exactly one band. Below the high-rise height the lines of the plot's Table
    III row (read on the height above the stilt) and what the row leaves open; a building of
    exactly the high-rise height takes the Table IV row that reaches it; above it the rows are
    Table IV's own, ALLOWED here: the site's high-rise eligibility comes in through
    HeightRules.band_permission. Written for a site whose access road is given and confirmed,
    which every made-up site is, and short of the real resolver's care for the rest."""
    start = rules.HIGH_RISE_THRESHOLD_M
    at_start = rules.band_for_height(start)
    own = site.ownership
    plot, gds = own.net_sqm.value, rules.is_group_development(own.gross_sqm.value)
    given = site.access_road().legal_row_m if site.access_road() is not None else None
    reckoned = None if given is None else rules.reckoned_road_width_m(given.value)
    below, above, above_inclusive = [], 0.0, False
    for line in rules.table_iii_lines(plot):
        need = 12.0 if gds or line.below else 9.0
        side = line.side_m or 0.0
        met = None if reckoned is None else reckoned >= need
        below.append({
            "above_m": above, "up_to_m": line.up_to_m, "above_inclusive": above_inclusive,
            "up_to_inclusive": not line.below, "kind": BandKind.NON_HIGH_RISE,
            "measure": HeightMeasure.HEIGHT_ABOVE_STILT, "min_road_m": need, "setback_m": side,
            "gap_m": side, "front_setback_m": None if reckoned is None else line.front_m[
                sum(reckoned > edge for edge in rules.TABLE_III_ROAD_UP_TO_M)],
            "permission": (Eligibility.UNVERIFIED if met is None else Eligibility.ALLOWED if met
                           else Eligibility.PROHIBITED),
            "permission_note": f"{need:g} m of road is asked",
            "green_strip_m": rules.NON_HIGH_RISE_FRONTAGE_STRIP_M,
            "green_strip_sides": "ALL" if plot > rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM
            else "FRONTAGE",
            "clause": f"{rules.TABLE_III_CLAUSE}; row {line.row}, up to {line.up_to_m:g} m"})
        above, above_inclusive = line.up_to_m, line.below
    below.append({
        "above_m": above, "up_to_m": start, "above_inclusive": above_inclusive,
        "up_to_inclusive": False, "kind": BandKind.NON_HIGH_RISE,
        "measure": HeightMeasure.HEIGHT_ABOVE_STILT, "permission": Eligibility.UNVERIFIED,
        "permission_note": "no order read gives a setback between the last line of Table III "
                           "and a high-rise", "clause": rules.TDR_BAND_CLAUSE,
        "status": Provenance.UNVERIFIED})

    def high(edges: dict, row) -> dict:
        strip = ({"green_strip_m": rules.PERIPHERAL_GREEN_STRIP_M}
                 if row.min_open_space_m >= rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M else {})
        return {**edges, "kind": BandKind.HIGH_RISE, "min_road_m": row.min_road_m,
                "setback_m": row.min_open_space_m, "gap_m": row.min_open_space_m,
                "clause": rules.TABLE_IV_CLAUSE, **strip}

    return [*below,
            high({"above_m": start, "up_to_m": start, "above_inclusive": True}, at_start),
            *(high({"above_m": b.above_m, "up_to_m": b.up_to_m}, b)
              for b in rules.TABLE_IV if b.above_m >= start)]


def height_limits(site: CanonicalSiteModel) -> list[dict]:
    """The limits on a height here: the road's (Table IV column 3), the dead-end rule's and the
    airport's. Each says whether it has a number, whether it applies, and how far the inputs
    behind the number are confirmed."""
    road = site.access_road()
    row = road.legal_row_m if road is not None else None
    by_road = {"id": "table_iv_road", "measure": HeightMeasure.RULE_HEIGHT,
               "clause": rules.TABLE_IV_CLAUSE}
    if row is None:
        by_road |= {"bound": LimitBound.NOT_EVALUATED, "status": Provenance.UNVERIFIED,
                    "reason": "the access road's legal width is not given"}
    else:
        top = rules.max_height_for_road(row.value)
        by_road["status"] = weakest(Provenance.VERIFIED, row.status)
        if top is None:
            by_road |= {"bound": LimitBound.BOUNDED, "max_m": rules.HIGH_RISE_THRESHOLD_M,
                        "inclusive": False,
                        "reason": f"the {row.value:.2f} m road serves no building of "
                                  f"{rules.HIGH_RISE_THRESHOLD_M:g} m or more; what it allows "
                                  "below that is the non-high-rise bands' (Table III)"}
        elif math.isinf(top):
            by_road |= {"bound": LimitBound.UNBOUNDED,
                        "reason": f"the {row.value:.2f} m road meets every row of Table IV: "
                                  "the road sets no height limit"}
        else:
            by_road |= {"bound": LimitBound.BOUNDED, "max_m": top,
                        "reason": f"the {row.value:.2f} m road serves buildings up to {top:g} m"}
    ends = site.access.dead_end
    dead_end = {
        "id": "dead_end", "measure": HeightMeasure.PHYSICAL_HEIGHT, "bound": LimitBound.BOUNDED,
        "max_m": rules.DEAD_END_MAX_HEIGHT_M, "clause": rules.DEAD_END_CLAUSE,
        "condition": {"fact": SiteFact.ROAD_ENDS_AT_PLOT, "holds_when": True,
                      "text": "the access road ends at the plot"},
        "applicability": {True: Applicability.APPLIES, False: Applicability.DOES_NOT_APPLY,
                          None: Applicability.UNKNOWN}[ends.value],
        # the number is the code's own; whether the road ends here is the applicability
        "status": Provenance.VERIFIED if ends.value is None
        else weakest(Provenance.VERIFIED, ends.status),
        "reason": "no dead-end road for a residential building above "
                  f"{rules.DEAD_END_MAX_HEIGHT_M:g} m"}
    airport = {"id": "airport", "measure": HeightMeasure.AMSL,
               "bound": LimitBound.NOT_EVALUATED, "status": Provenance.UNVERIFIED,
               "clause": AIRPORT_CLAUSE,
               "reason": "airport and Air Force height limits are not evaluated"
               + ("" if site.coordinates else ": the site has no coordinates")}
    return [by_road, dead_end, airport]


def high_rise(site: CanonicalSiteModel) -> dict:
    """Whether the site may take a high-rise at all: its road and its plot size. A site that may
    not is PROHIBITED, which says nothing about what may be built below the high-rise height."""
    road = site.access_road()
    row = road.legal_row_m if road is not None else None
    need = rules.band_for_height(rules.HIGH_RISE_THRESHOLD_M).min_road_m
    net = site.ownership.net_sqm
    grounds = [
        EligibilityGround(
            id="road_width", met=None if row is None else row.value >= need,
            measured="not given" if row is None else f"{row.value:.2f} m",
            required=f"at least {need:g} m", clause=rules.TABLE_IV_CLAUSE,
            status=Provenance.UNVERIFIED if row is None else row.status),
        EligibilityGround(
            id="plot_size", met=net.value >= rules.MIN_HIGH_RISE_PLOT_SQM,
            measured=f"{net.value:,.1f} m²",
            required=f"at least {rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m²",
            clause=rules.MIN_HIGH_RISE_PLOT_CLAUSE, status=net.status)]
    eligibility = HighRiseEligibility.of_grounds(grounds)
    return {"eligibility": eligibility, "grounds": grounds,
            "note": PROHIBITED_NOTE if eligibility is Eligibility.PROHIBITED else ""}


def resolved_rules(site: CanonicalSiteModel) -> ResolvedRules:
    own = site.ownership
    gross, net = own.gross_sqm.value, own.net_sqm.value
    surrendered = sum(d.area_sqm.value for d in own.deductions
                      if d.kind is DeductionKind.SURRENDER)
    columns = rules.parking_columns(site.jurisdiction.authority.value,
                                    site.jurisdiction.inside_cure.value)
    column = (TableVColumn.OPEN if len(columns) > 1 else TableVColumn.GHMC_OR_CURE
              if columns == {rules.PARKING_PERCENT_GHMC} else TableVColumn.ELSEWHERE)
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
                                           "clause": rules.AMENITY_CLAUSE, **LAW}},
        jurisdiction={"table_v_column": column, "when_open": WhenOpen.STOP},
        height={"measures": {
                    HeightMeasure.RULE_HEIGHT: "the height Table IV and the high-rise class are "
                    "read on; whether it includes the stilt is stilt_in_rule_height",
                    HeightMeasure.PHYSICAL_HEIGHT: "ground to the top, stilt included",
                    HeightMeasure.AMSL: "height above mean sea level",
                    HeightMeasure.HEIGHT_ABOVE_STILT: "the stilt left out: what Table III reads"},
                "high_rise_from_m": {"value": rules.HIGH_RISE_THRESHOLD_M, "unit": "m",
                                     "clause": rules.HIGH_RISE_CLAUSE, **LAW},
                "high_rise": high_rise(site),
                "tdr_band_m": {"value": rules.TDR_BAND_M, "unit": "m",
                               "clause": rules.TDR_BAND_CLAUSE, **LAW},
                "tdr_plot_sqm": {"value": rules.TDR_PLOT_RANGE_SQM, "unit": "m²",
                                 "clause": rules.TDR_BAND_CLAUSE, **LAW},
                "bands": height_bands(site),
                "limits": height_limits(site)},
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
                    "over_and_above_setbacks": {"value": True, "clause": rules.OPEN_SPACE_CLAUSE,
                                                **LAW},
                    "block_gaps_excluded": {"value": True, "clause": rules.BLOCK_SPACING_CLAUSE,
                                            **LAW},
                    "buffer_may_count": {"value": True, "clause": rules.WATER_BUFFER_CLAUSE,
                                         **LAW},
                    "qualifying_uses": {
                        "value": [FacilityUse.GREENERY, FacilityUse.TOT_LOT,
                                  FacilityUse.SOFT_LANDSCAPE],
                        "clause": rules.OPEN_SPACE_CLAUSE,
                        "note": "the uses the rule names: 'greenery, tot lot or soft "
                                "landscaping, etc.'", **LAW}},
        green_strip={"width_m": {"value": rules.PERIPHERAL_GREEN_STRIP_M, "unit": "m",
                                 "clause": rules.PERIPHERAL_GREEN_STRIP_CLAUSE, **LAW},
                     "where_setback_from_m": {"value": rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M,
                                              "unit": "m",
                                              "clause": rules.PERIPHERAL_GREEN_STRIP_CLAUSE,
                                              **LAW},
                     "frontage_m": {"value": rules.NON_HIGH_RISE_FRONTAGE_STRIP_M, "unit": "m",
                                    "clause": rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE, **LAW},
                     "periphery_m": {"value": rules.NON_HIGH_RISE_PERIPHERY_STRIP_M, "unit": "m",
                                     "clause": rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE, **LAW},
                     "periphery_above_sqm": {
                         "value": rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM, "unit": "m²",
                         "clause": rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE, **LAW}},
        circulation=_circulation(gds),
        fire=_fire(),
        electrical={"ht_clearance_m": {"value": rules.ELECTRICAL_HT_CLEARANCE_M, "unit": "m",
                                       "clause": rules.ELECTRICAL_CLAUSE, **LAW},
                    "lt_clearance_m": {"value": rules.ELECTRICAL_LT_CLEARANCE_M, "unit": "m",
                                       "clause": rules.ELECTRICAL_CLAUSE, **LAW}},
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
                                               "one block", "clause": rules.AMENITY_CLAUSE,
                                      **LAW}},
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
            "pathway_width_m": {"value": rules.PATHWAY_WIDTH_M, "unit": "m",
                                "clause": rules.PATHWAY_CLAUSE, **LAW},
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
                                          "or rear only leaving the fire clearance",
                                 "clause": rules.RAMP_CLAUSE, **LAW},
            "ramp_fire_clearance_m": {"value": rules.RAMP_FIRE_CLEARANCE_M, "unit": "m",
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
    bands, layers = [], []
    for band in resolved.height.bands:
        permission = resolved.height.band_permission(band)
        common = {"above_m": band.above_m, "up_to_m": band.up_to_m, "kind": band.kind,
                  "front_setback_m": band.front_setback_m, "permission": permission}
        if band.setback_m is None:  # a height nothing permits or that is open: no land to cut
            bands.append({**common, "modelled": True, "note": band.permission_note})
            continue
        if permission is Eligibility.PROHIBITED and band.kind is BandKind.NON_HIGH_RISE:
            bands.append({**common, "setback_m": band.setback_m,
                          "note": f"prohibited: {band.permission_note}"})
            continue
        if not _offered(resolved, band):
            continue
        inset = net.buffer(-max(band.setback_m, band.front_setback_m or 0.0))
        buildable = inset.difference(excluded) if excluded is not None else inset
        key = (f"{band.above_m:g} m" if band.up_to_m == band.above_m
               else f"{band.above_m:g}-{band.up_to_m:g} m")
        bands.append({**common, "setback_m": band.setback_m, "setback_envelope": shapes_from(inset),
                      "buildable": shapes_from(buildable), "area_sqm": buildable.area,
                      "green_strip_applies": band.green_strip_m is not None,
                      "note": ("" if permission is Eligibility.ALLOWED or not band.permission_note
                               else f"{permission.value.lower()}: {band.permission_note}")})
        layers.append(_setback_layer(key, net.difference(inset),
                                     resolved.parking.ramp_fire_clearance_m.value))
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
               Finding("High-rise eligibility", Status.INFO,
                       resolved.height.high_rise.eligibility.value,
                       "; ".join(f"{g.id}: {g.measured}, {g.required}"
                                 for g in resolved.height.high_rise.grounds),
                       rules.MIN_HIGH_RISE_PLOT_CLAUSE, resolved.height.high_rise.note),
               _road_limit_fact(resolved)])


def _offered(resolved: ResolvedRules, band: Band) -> bool:
    """Whether the envelope draws a band: not a high-rise band where a high-rise is prohibited,
    and not one whose lowest height is already beyond a limit that applies or may apply."""
    height = resolved.height
    if (band.kind is BandKind.HIGH_RISE
            and height.high_rise.eligibility is Eligibility.PROHIBITED):
        return False
    lowest = band.above_m if band.above_inclusive else band.above_m + 2 * HEIGHT_TOL_M
    return not any(limit.beyond(lowest) for limit in height.limits
                   if limit.measure is HeightMeasure.RULE_HEIGHT)


def _road_limit_fact(resolved: ResolvedRules) -> Finding:
    limit = next(lim for lim in resolved.height.limits if lim.id == "table_iv_road")
    measured = {LimitBound.BOUNDED: f"{limit.max_m:g} m" if limit.max_m else "",
                LimitBound.UNBOUNDED: "none from the road",
                LimitBound.NOT_EVALUATED: "not evaluated"}[limit.bound]
    return Finding("Rule-height limit", Status.INFO, measured, "Table IV by road",
                   rules.TABLE_IV_CLAUSE, limit.reason)


def _setback_layer(key: str, zone, ramp_clear_m: float) -> dict:
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
                         "condition": f"side or rear setback only, leaving {ramp_clear_m:g} m "
                                      "(13(c)(vii))"}],
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
