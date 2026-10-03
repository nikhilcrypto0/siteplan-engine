"""ResolvedRules: what the law asks of one site, in metres and square metres.

`resolve` reads every rule value from rules.py, the site's facts from the CanonicalSiteModel, and
writes each value with its clause, its basis and how far it can be trusted. Heights are limits in
metres on a named measure; turning a height into floors needs the brief's floor heights, so no
floor count appears here. Where the orders leave a question open the answer is an Interpretation
(readings.py), never a quiet choice. Nothing here draws.

A value taken from a site fact (the road's width, the site's area, whose rules apply) is only as
trustworthy as that fact: its status is the weakest of VERIFIED and the fact's own.
"""

from __future__ import annotations

import hashlib
import math

from siteplan import parking, rules
from siteplan.contracts.accounting import DeductionKind
from siteplan.contracts.common import Basis, Provenance, digest
from siteplan.contracts.resolved_rules import (
    BandKind,
    HeightMeasure,
    ResolvedRules,
    TableVColumn,
    WhenOpen,
)
from siteplan.contracts.site_model import CanonicalSiteModel, Road
from siteplan.legal.readings import OPEN_SPACE_READINGS, interpretations
from siteplan.provenance import confirmed, weakest
from siteplan.units import SQM_PER_ACRE

# The airport clause lives in heights.py too; tests/test_resolve.py keeps the two the same.
AIRPORT_CLAUSE = "G.O.168 rule 3(d) (airport and Air Force height limits)"
TABLE_III_CLAUSE = "G.O.168 rule 5, Table III"
LAW = {"basis": Basis.LEGAL_RULE, "status": Provenance.VERIFIED}
YES_NO = {True: "yes", False: "no", None: "not known"}

# The orders ResolvedRules rests on, and how each was read (AGENTS.md); the unread ones are
# listed because they may amend what is relied on.
ORDERS = (
    ("G.O.Ms.No.168 of 2012", "TEXT", "the base rules: the 2012 wording stands where no later "
     "order replaced it"),
    ("G.O.Ms.No.7 of 2016", "TEXT", "green strip, road-widening concessions, amenities, EWS, "
     "river buffer"),
    ("G.O.Ms.No.50 of 2019", "SCAN", "Table IV substituted"),
    ("G.O.Ms.No.65 of 2019", "SCAN", "the note under Table IV for buildings over 40 m deleted"),
    ("G.O.Ms.No.95 of 2026", "SCAN", "a high-rise is 21 m; TDR bands"),
    ("G.O.Ms.No.245 of 2012", "UNREAD", ""),
    ("G.O.Ms.No.103 of 2021", "UNREAD", "podium parking"),
    ("G.O.Ms.No.16 of 2026", "UNREAD", ""),
    ("TS-bPASS G.O.201", "UNREAD", ""),
)
MEASURES = {
    HeightMeasure.RULE_HEIGHT: "the height Table IV and the high-rise class are read on; whether "
                               "it includes the stilt is the stilt_in_rule_height reading",
    HeightMeasure.PHYSICAL_HEIGHT: "ground to the top, stilt included (NBC Part 3 2.10)",
    HeightMeasure.AMSL: "height above mean sea level (airport and Air Force limits)",
}


def rules_digest() -> str:
    """A fingerprint of every value in rules.py: it changes when a rule value does."""
    text = "\n".join(f"{name}={value!r}" for name, value in sorted(vars(rules).items())
                     if name.isupper())
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def resolve(site: CanonicalSiteModel, *, selections: dict[str, str] | None = None,
            when_open: WhenOpen = WhenOpen.STOP) -> ResolvedRules:
    """The law for this site. `selections` maps an open reading's id to the reading a test profile
    takes; `when_open` says what to do when whose rules apply is not established (CONSERVATIVE
    plans the stricter Table V column, labelled as a test mode; STOP leaves the share open)."""
    own, road = site.ownership, site.access_road()
    gross = own.gross_sqm
    column, column_status, jurisdiction_note = _table_v_column(site)
    group = rules.is_group_development(gross.value)
    master_plan = road is not None and road.master_plan_row_m is not None
    return ResolvedRules(
        site_ref=digest(site), rules_digest=rules_digest(),
        orders=[{"id": name, "read": read, "note": note} for name, read, note in ORDERS],
        category=_category(site, group),
        jurisdiction={"table_v_column": column, "when_open": when_open,
                      "note": jurisdiction_note},
        height=_height(site, road),
        setbacks=_setbacks(),
        spacing={"clause": rules.BLOCK_SPACING_CLAUSE},
        open_space=_open_space(site),
        green_strip={
            "width_m": _rv(rules.PERIPHERAL_GREEN_STRIP_M, rules.PERIPHERAL_GREEN_STRIP_CLAUSE,
                           unit="m"),
            "where_setback_from_m": _rv(rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M,
                                        rules.PERIPHERAL_GREEN_STRIP_CLAUSE, unit="m")},
        circulation=_circulation(group, gross.status),
        fire=_fire(),
        parking=_parking(column, column_status, when_open),
        amenities=_amenities(),
        water={"buffer_m_by_class": _rv(dict(rules.WATER_BUFFER_M), rules.WATER_BUFFER_CLAUSE,
                                        unit="m")},
        interpretations=interpretations(master_plan_road=master_plan, selections=selections))


def _rv(value, clause: str, *, unit: str = "", note: str = "", **over) -> dict:
    """One RuleValue, as the fields it is built from: law, read from the order, unless said."""
    return {"value": value, "unit": unit, "clause": clause, "note": note, **LAW, **over}


def _from_site(value, clause: str, fact_status: Provenance) -> dict:
    """A RuleValue that takes a site fact through a rule: as trustworthy as the fact."""
    return _rv(value, clause, status=weakest(Provenance.VERIFIED, fact_status))


def _category(site: CanonicalSiteModel, group: bool) -> dict:
    gross = site.ownership.gross_sqm
    return {
        "group_development": _from_site(group, rules.GROUP_DEVELOPMENT_CLAUSE, gross.status),
        "amenities_from_units": _rv(rules.AMENITY_MIN_UNITS, rules.AMENITY_CLAUSE),
        "above_5_acres": _rv(
            gross.value > rules.LARGE_PROJECT_FROM_ACRES * SQM_PER_ACRE,
            rules.LARGE_PROJECT_AMENITY_CLAUSE, basis=Basis.UNRESOLVED_INTERPRETATION,
            status=Provenance.ASSUMED_FOR_TEST,
            note="a size class only: the 5% amenity share it triggers is written for row and "
                 "cluster housing, not group development, and is not applied here")}


# --- Height ----------------------------------------------------------------------------------


def _height(site: CanonicalSiteModel, road: Road | None) -> dict:
    return {
        "measures": MEASURES,
        "high_rise_from_m": _rv(rules.HIGH_RISE_THRESHOLD_M, rules.HIGH_RISE_CLAUSE, unit="m"),
        "tdr_band_m": _rv(rules.TDR_BAND_M, rules.TDR_BAND_CLAUSE, unit="m"),
        "tdr_plot_sqm": _rv(rules.TDR_PLOT_RANGE_SQM, rules.TDR_BAND_CLAUSE, unit="m²"),
        "bands": _bands(),
        "limits": [*_road_limits(road), *_plot_limit(site), *_dead_end_limit(site),
                   _airport_limit(site)]}


def _bands() -> list[dict]:
    """The non-high-rise band, present and not modelled (Table III is stream A2's), then the
    high-rise rows of Table IV, each with its road, its all-round setback and the gap between two
    blocks (the same figure, rule 7(a)(xii))."""
    below = {"above_m": 0.0, "up_to_m": rules.HIGH_RISE_THRESHOLD_M,
             "kind": BandKind.NON_HIGH_RISE, "modelled": False, "clause": TABLE_III_CLAUSE,
             "status": Provenance.UNVERIFIED}
    return [below, *({"above_m": b.above_m, "up_to_m": b.up_to_m, "kind": BandKind.HIGH_RISE,
                      "min_road_m": b.min_road_m, "setback_m": b.min_open_space_m,
                      "gap_m": b.min_open_space_m, "clause": rules.TABLE_IV_CLAUSE}
                     for b in rules.TABLE_IV if b.above_m >= rules.HIGH_RISE_THRESHOLD_M)]


def _road_limits(road: Road | None) -> list[dict]:
    """Table IV column 3 read on the access road's legal width. A master-plan width gives a second
    limit, each conditional on which width counts (the table_iv_road_width reading)."""
    width = road.legal_row_m if road is not None else None
    if width is None:
        return [{"measure": HeightMeasure.RULE_HEIGHT, "max_m": None,
                 "reason": "the access road's legal width is not given, so Table IV cannot be "
                           "read",
                 "clause": rules.TABLE_IV_CLAUSE, "status": Provenance.UNVERIFIED}]
    plan = road.master_plan_row_m
    if plan is None:
        return [_table_iv_limit(width.value, width.status, road.row_status, "road", None)]
    return [_table_iv_limit(width.value, width.status, road.row_status, "road",
                            "the master-plan strip is not surrendered, so the road stays as it "
                            "is"),
            _table_iv_limit(plan.value, plan.status, None, "master-plan road",
                            "the land for the master-plan road is surrendered (rule 16)")]


def _table_iv_limit(width_m: float, width_status: Provenance, row_status: str | None,
                    what: str, applies_if: str | None) -> dict:
    top = rules.max_height_for_road(width_m)
    tag = f"{row_status}, {width_status}" if row_status else str(width_status)
    road = f"the {width_m:.2f} m {what} ({tag})"
    limit = {"measure": HeightMeasure.RULE_HEIGHT, "clause": rules.TABLE_IV_CLAUSE,
             "status": weakest(Provenance.VERIFIED, width_status), "applies_if": applies_if}
    if top is None:
        first = rules.TABLE_IV[0].min_road_m
        return limit | {"max_m": rules.HIGH_RISE_THRESHOLD_M,
                        "reason": f"{road} is under the {first:g} m Table IV asks of a "
                                  f"high-rise: the building must stay under "
                                  f"{rules.HIGH_RISE_THRESHOLD_M:g} m"}
    if math.isinf(top):
        return limit | {"max_m": None,
                        "reason": f"{road} meets every Table IV row: the road sets no height "
                                  "limit, so setbacks, fire and airport norms decide"}
    beyond = next(band for band in rules.TABLE_IV if band.above_m >= top)
    return limit | {"max_m": top,
                    "reason": f"{road} serves buildings up to {top:g} m; up to "
                              f"{beyond.up_to_m:g} m needs {beyond.min_road_m:g} m of road"}


def _plot_limit(site: CanonicalSiteModel) -> list[dict]:
    """Rule 7(a)(ii): a plot under the minimum cannot take a high-rise, so the building stays
    under the high-rise height. The test is on the net plot; rule 7(a)(iii) lets a site left short
    by road widening count when the shortfall is small, which is not modelled, so a site that
    falls just short of the minimum with land surrendered is UNVERIFIED rather than failed."""
    own = site.ownership
    net, minimum = own.net_sqm, rules.MIN_HIGH_RISE_PLOT_SQM
    if net.value >= minimum:
        return []
    surrendered = any(d.kind is DeductionKind.SURRENDER for d in own.deductions)
    near = surrendered and net.value >= minimum * (1 - rules.ROAD_WIDENING_SHORTFALL_ALLOWANCE)
    reason = (f"a net plot of {net.value:,.0f} m² is under the {minimum:,.0f} m² a high-rise "
              f"needs: the building must stay under {rules.HIGH_RISE_THRESHOLD_M:g} m")
    if near:
        reason += (f"; {rules.ROAD_WIDENING_SHORTFALL_CLAUSE} lets a site left short by road "
                   "widening count when the shortfall is small, which is not modelled (the text "
                   "does not say 10% of what)")
    return [{"measure": HeightMeasure.RULE_HEIGHT, "max_m": rules.HIGH_RISE_THRESHOLD_M,
             "reason": reason, "clause": rules.MIN_HIGH_RISE_PLOT_CLAUSE,
             "status": Provenance.UNVERIFIED if near else weakest(Provenance.VERIFIED,
                                                                  net.status)}]


def _dead_end_limit(site: CanonicalSiteModel) -> list[dict]:
    """NBC 4.6(b): above 30 m of physical height a residential building may not stand on a road
    that ends at the plot. Unknown stays UNVERIFIED; a road known to run on has no such limit."""
    dead_end = site.access.dead_end
    if dead_end.value is False:
        return []
    known = "the road's end is not known" if dead_end.value is None else (
        "the road ends at the plot")
    return [{"measure": HeightMeasure.PHYSICAL_HEIGHT, "max_m": rules.DEAD_END_MAX_HEIGHT_M,
             "reason": "no dead-end road for a residential building above this height, which "
                       f"NBC measures from the ground, stilt included ({known})",
             "clause": rules.DEAD_END_CLAUSE,
             "status": Provenance.UNVERIFIED if dead_end.value is None else weakest(
                 Provenance.VERIFIED, dead_end.status),
             "applies_if": "the access road ends at the plot"}]


def _airport_limit(site: CanonicalSiteModel) -> dict:
    where = site.coordinates
    reason = ("no site coordinates: airport and Air Force height limits are not evaluated"
              if where is None else
              f"airport and Air Force height limits are not computed; read the maps at "
              f"{where.value[0]:.5f}, {where.value[1]:.5f}")
    return {"measure": HeightMeasure.AMSL, "max_m": None, "reason": reason,
            "clause": AIRPORT_CLAUSE, "status": Provenance.UNVERIFIED}


# --- The rest of the law ---------------------------------------------------------------------


def _setbacks() -> dict:
    return {
        "measured_on": _rv("net plot", rules.SETBACK_ON_NET_PLOT_CLAUSE),
        "front": _rv("Table IV column 4, as on every other side", rules.FRONT_SETBACK_CLAUSE,
                     note="rule 7(a)(xi) takes the higher of Table IV column 4 and the Building "
                          "Line of Table III; Table III is not encoded yet (stream A2), so a "
                          "Building Line above the Table IV figure would not show"),
        "concessions": [_rv("down to 7 m clear on all sides", rules.ROAD_WIDENING_CLAUSE,
                            note="applies only when land is surrendered for a road; the engine "
                                 "does not apply it, so setbacks stay at the Table IV figure")]}


def _open_space(site: CanonicalSiteModel) -> dict:
    """The area asked under each reading of the denominator (readings.OPEN_SPACE_READINGS)."""
    own = site.ownership
    surrendered = sum(d.area_sqm.value for d in own.deductions
                      if d.kind is DeductionKind.SURRENDER)
    share = rules.OPEN_SPACE_MIN_FRACTION
    areas = dict(zip(OPEN_SPACE_READINGS,
                     (own.gross_sqm.value, own.gross_sqm.value - surrendered,
                      own.net_sqm.value), strict=True))
    return {
        "share": _rv(share, rules.OPEN_SPACE_CLAUSE),
        "requirement_sqm_by_reading": {reading: share * area for reading, area in areas.items()},
        "min_width_m": _rv(rules.OPEN_SPACE_MIN_WIDTH_M, rules.OPEN_SPACE_CLAUSE, unit="m"),
        "min_pocket_sqm": _rv(rules.OPEN_SPACE_MIN_POCKET_SQM, rules.OPEN_SPACE_CLAUSE,
                              unit="m²"),
        "over_and_above_setbacks": _rv(True, rules.OPEN_SPACE_CLAUSE),
        "block_gaps_excluded": _rv(True, rules.BLOCK_SPACING_CLAUSE),
        "buffer_may_count": _rv(True, rules.WATER_BUFFER_CLAUSE)}


def _circulation(group: bool, gross_status: Provenance) -> dict:
    road = {"clause": rules.INTERNAL_ROAD_CLAUSE}
    return {
        "applies": _from_site(group, rules.GROUP_DEVELOPMENT_CLAUSE, gross_status),
        "approach_m": _rv(rules.MAIN_APPROACH_ROAD_M, unit="m", **road),
        "internal_road_m": _rv(rules.INTERNAL_ROAD_M, unit="m", **road),
        "cul_de_sac_width_m": _rv(rules.CUL_DE_SAC_WIDTH_M, unit="m", **road),
        "cul_de_sac_length_m": _rv(rules.CUL_DE_SAC_LENGTH_M, unit="m", **road),
        "cul_de_sac_head_radius_m": _rv(rules.CUL_DE_SAC_HEAD_RADIUS_M, unit="m", **road),
        "pathway_max_block_height_m": _rv(rules.PATHWAY_MAX_BLOCK_HEIGHT_M, rules.PATHWAY_CLAUSE,
                                          unit="m"),
        "driveway_min_m": _rv(rules.DRIVEWAY_MIN_WIDTH_M, rules.DRIVEWAY_CLAUSE, unit="m"),
        "driveway_is_road": _rv(False, rules.INTERNAL_ROAD_CLAUSE,
                                note="a driveway is never counted as an internal road"),
        "block_over_12m_on_road": _rv(
            True, rules.PATHWAY_CLAUSE,
            note="a block above the pathway height takes its access from an internal road")}


def _fire() -> dict:
    fire = {"clause": rules.FIRE_ACCESS_CLAUSE}
    return {
        "applies_from_m": _rv(rules.HIGH_RISE_THRESHOLD_M, rules.HIGH_RISE_CLAUSE, unit="m"),
        "clear_width_m": _rv(rules.FIRE_TENDER_MIN_WIDTH_M, unit="m", **fire),
        "turning_radius_m": _rv(rules.FIRE_TURNING_RADIUS_M, unit="m", **fire),
        "entrance_width_m": _rv(rules.GATE_MIN_WIDTH_M, rules.GATE_CLAUSE, unit="m"),
        "entrance_clear_height_m": _rv(rules.ENTRANCE_CLEAR_HEIGHT_M, rules.GATE_CLAUSE,
                                       unit="m"),
        "load_t": _rv(rules.FIRE_TENDER_LOAD_T, unit="t", status=Provenance.UNVERIFIED,
                      note="a paving specification the engine cannot check", **fire),
        "street_join_m": _rv(rules.FIRE_STREET_JOIN_M, rules.FIRE_STREET_CLAUSE, unit="m"),
        "dead_end_max_physical_m": _rv(rules.DEAD_END_MAX_HEIGHT_M, rules.DEAD_END_CLAUSE,
                                       unit="m")}


def _table_v_column(site: CanonicalSiteModel) -> tuple[TableVColumn, Provenance, str]:
    """Which Table V column the site takes, how far that is trusted, and why. Only an answer that
    is confirmed counts: a confirmed GHMC, or a confirmed CURE, settles the 30% column alone; the
    20% column needs both confirmed; otherwise both stay possible and the column is OPEN."""
    j = site.jurisdiction
    authority = j.authority.value if confirmed(j.authority.status) else None
    cure = j.inside_cure.value if confirmed(j.inside_cure.status) else None
    columns = rules.parking_columns(authority, cure)
    told = (f"authority {j.authority.value or 'not given'} ({j.authority.status}), inside CURE "
            f"{YES_NO[j.inside_cure.value]} ({j.inside_cure.status})")
    if len(columns) > 1:
        return (TableVColumn.OPEN, Provenance.UNVERIFIED,
                f"{told}: not established, and it decides Table V's share")
    if columns == {rules.PARKING_PERCENT_GHMC}:
        settling = ([j.authority.status] if (authority or "").upper() == "GHMC" else []) + (
            [j.inside_cure.status] if cure is True else [])
        return (TableVColumn.GHMC_OR_CURE, weakest(Provenance.VERIFIED, *settling),
                f"{told}: the GHMC column ({rules.CURE_RULES_CLAUSE})")
    return (TableVColumn.ELSEWHERE, weakest(Provenance.VERIFIED, j.authority.status,
                                            j.inside_cure.status),
            f"{told}: the column for every other area")


def _parking(column: TableVColumn, column_status: Provenance, when_open: WhenOpen) -> dict:
    share_by_column = {TableVColumn.GHMC_OR_CURE: rules.PARKING_PERCENT_GHMC,
                       TableVColumn.ELSEWHERE: rules.PARKING_PERCENT_ELSEWHERE}
    clause = f"{rules.PARKING_CLAUSE}; {rules.CURE_RULES_CLAUSE}"
    if column is not TableVColumn.OPEN:
        share = _rv(share_by_column[column], clause, unit="%", status=column_status)
    elif when_open is WhenOpen.CONSERVATIVE:
        share = _rv(rules.PARKING_PERCENT_GHMC, clause, unit="%",
                    basis=Basis.UNRESOLVED_INTERPRETATION, status=Provenance.ASSUMED_FOR_TEST,
                    note="CONSERVATIVE test mode: whose rules apply is not established, so the "
                         "stricter GHMC column is planned and a pass holds either way")
    else:
        share = None  # the run stops and asks whose rules apply
    table = [(None if math.isinf(up_to) else up_to, m)
             for up_to, m in rules.CELLAR_SETBACK_BY_SITE_SQM]
    return {
        "share_pct_by_column": share_by_column, "share_pct": share,
        "visitors_fraction": _rv(rules.VISITOR_PARKING_FRACTION, rules.VISITOR_PARKING_CLAUSE),
        "cellar_setback_by_site_sqm": _rv(table, rules.CELLAR_SETBACK_CLAUSE, unit="m"),
        "cellar_extra_setback_per_level_m": _rv(rules.CELLAR_EXTRA_SETBACK_PER_LEVEL_M,
                                                rules.CELLAR_SETBACK_CLAUSE, unit="m"),
        "ramp_single_min_m": _rv(rules.RAMP_SINGLE_MIN_WIDTH_M, rules.RAMP_CLAUSE, unit="m"),
        "ramp_pair_min_m": _rv(rules.RAMP_PAIR_MIN_WIDTH_M, rules.RAMP_CLAUSE, unit="m"),
        "ramp_gradient": _rv(rules.RAMP_MAX_GRADIENT, rules.RAMP_CLAUSE),
        "ramp_in_setbacks": _rv("never in the front setback or building line; in a side or rear "
                                "setback only after leaving the width kept for fire vehicles",
                                rules.RAMP_CLAUSE),
        "utilities_max_fraction": _rv(rules.CELLAR_UTILITIES_MAX_FRACTION,
                                      rules.CELLAR_UTILITIES_CLAUSE),
        "measurement": {"bay_m": (parking.BAY_WIDTH_M, parking.BAY_DEPTH_M),
                        "aisle_m": parking.AISLE_M, "sqm_per_car": parking.LAID_OUT_SQM_PER_CAR,
                        "note": parking.BAY_BASIS}}


def _amenities() -> dict:
    return {
        "share_of_built_up": _rv(rules.AMENITY_MIN_BUILT_UP_FRACTION, rules.AMENITY_CLAUSE,
                                 basis=Basis.UNRESOLVED_INTERPRETATION,
                                 status=Provenance.ASSUMED_FOR_TEST,
                                 note="the 2012 minimum, kept as the planning share"),
        "cap_sqft_2016": _rv(rules.AMENITY_CAP_SQFT_2016, rules.AMENITY_CLAUSE, unit="sft",
                             note="the 2016 wording's cap: reported, never applied"),
        "from_units": _rv(rules.AMENITY_MIN_UNITS, rules.AMENITY_CLAUSE),
        "separate_block": _rv("not part of the residential blocks, unless there is a single "
                              "apartment block", rules.AMENITY_CLAUSE),
        "large_project_share_of_site": _rv(
            rules.LARGE_PROJECT_AMENITY_SHARE_OF_SITE, rules.LARGE_PROJECT_AMENITY_CLAUSE,
            basis=Basis.UNRESOLVED_INTERPRETATION, status=Provenance.ASSUMED_FOR_TEST,
            note="written for row and cluster housing, not group development: recorded, never "
                 "applied"),
        "large_project_from_acres": _rv(
            rules.LARGE_PROJECT_FROM_ACRES, rules.LARGE_PROJECT_AMENITY_CLAUSE, unit="acre",
            basis=Basis.UNRESOLVED_INTERPRETATION, status=Provenance.ASSUMED_FOR_TEST,
            note="written for row and cluster housing, not group development: recorded, never "
                 "applied")}

