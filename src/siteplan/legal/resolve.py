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
from siteplan.contracts.common import Basis, FacilityUse, Provenance, digest
from siteplan.contracts.resolved_rules import (
    Applicability,
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
from siteplan.contracts.site_model import CanonicalSiteModel, Road
from siteplan.legal import non_high_rise
from siteplan.legal.readings import OPEN_SPACE_READINGS, interpretations
from siteplan.provenance import confirmed, weakest

# The airport clause lives in heights.py too; tests/test_resolve.py keeps the two the same.
AIRPORT_CLAUSE = "G.O.168 rule 3(d) (airport and Air Force height limits)"
LAW = {"basis": Basis.LEGAL_RULE, "status": Provenance.VERIFIED}
YES_NO = {True: "yes", False: "no", None: "not known"}
APPLICABILITY = {True: Applicability.APPLIES, False: Applicability.DOES_NOT_APPLY,
                 None: Applicability.UNKNOWN}
# What a high-rise's prohibition does not say (the user's clarification of 2026-10-03).
PROHIBITED_NOTE = ("No building of the high-rise height or more may stand here. That permits "
                   "nothing below it: what may be built below it is the non-high-rise bands' "
                   "(Table III: the permissible height, its setbacks, the road it asks and the "
                   "spacing), each band with its own permission.")

# The orders ResolvedRules rests on, and how each was read (AGENTS.md); the unread ones are
# listed because they may amend what is relied on.
ORDERS = (
    ("G.O.Ms.No.168 of 2012", "TEXT", "the base rules: the 2012 wording stands where no later "
     "order replaced it"),
    ("G.O.Ms.No.7 of 2016", "TEXT", "green strip, road-widening concessions, amenities, EWS, "
     "river buffer; Table III's parking column and the stilt's use (rule 5)"),
    ("G.O.Ms.No.50 of 2019", "SCAN", "Table IV substituted; rule 15(a)(i) moved to NBC 2016"),
    ("G.O.Ms.No.65 of 2019", "SCAN", "the note under Table IV for buildings over 40 m deleted"),
    ("G.O.Ms.No.95 of 2026", "SCAN", "a high-rise is 21 m; TDR bands (18-21 m on 750-2,000 m², "
     "setback relaxation); no change to rule 5 or Table III"),
    ("G.O.Ms.No.264 of 2019", "SCAN", "rule 17(c) only: TDR certificates usable within the ORR"),
    ("G.O.Ms.No.14 of 2022", "SCAN", "rule 3(j)(vii) only: no height limit on sites of 7.5 acres "
     "or more in Banjara and Jubilee Hills"),
    ("G.O.Ms.No.49 of 2023", "TEXT", "dual piping, EV charging, digital infrastructure"),
    ("G.O.Ms.No.103 of 2021", "SCAN", "rule 7(b) substituted: podium parking for towers, not "
     "Table III"),
    ("G.O.Ms.No.245 of 2012", "UNREAD", "read with G.O.168 by the 2016 and 2019 orders: it may "
     "have changed rule 5"),
    ("G.O.Ms.No.16 of 2026", "UNREAD", ""),
    ("TS-bPASS G.O.201", "UNREAD", "skimmed by OCR only: procedure for bodies other than GHMC; "
     "its own Table III is the user charges"),
)
MEASURES = {
    HeightMeasure.RULE_HEIGHT: "the height Table IV and the high-rise class are read on; whether "
                               "it includes the stilt is the stilt_in_rule_height reading",
    HeightMeasure.PHYSICAL_HEIGHT: "ground to the top, stilt included (NBC Part 3 2.10)",
    HeightMeasure.AMSL: "height above mean sea level (airport and Air Force limits)",
    HeightMeasure.HEIGHT_ABOVE_STILT: "ground to the top with the parking stilt left out: the "
                                      "height Table III is read on (rule 5(c))",
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
                                        rules.PERIPHERAL_GREEN_STRIP_CLAUSE, unit="m"),
            "frontage_m": _rv(rules.NON_HIGH_RISE_FRONTAGE_STRIP_M,
                              rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE, unit="m"),
            "periphery_m": _rv(rules.NON_HIGH_RISE_PERIPHERY_STRIP_M,
                               rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE, unit="m"),
            "periphery_above_sqm": _rv(rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM,
                                       rules.NON_HIGH_RISE_GREEN_STRIP_CLAUSE, unit="m²")},
        circulation=_circulation(group, gross.status),
        fire=_fire(),
        electrical={
            "ht_clearance_m": _rv(rules.ELECTRICAL_HT_CLEARANCE_M, rules.ELECTRICAL_CLAUSE,
                                  unit="m"),
            "lt_clearance_m": _rv(rules.ELECTRICAL_LT_CLEARANCE_M, rules.ELECTRICAL_CLAUSE,
                                  unit="m")},
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
        "amenities_from_units": _rv(rules.AMENITY_MIN_UNITS, rules.AMENITY_CLAUSE)}


# --- Height ----------------------------------------------------------------------------------


def _height(site: CanonicalSiteModel, road: Road | None) -> dict:
    return {
        "measures": MEASURES,
        "high_rise_from_m": _rv(rules.HIGH_RISE_THRESHOLD_M, rules.HIGH_RISE_CLAUSE, unit="m"),
        "high_rise": _high_rise(site, road),
        "tdr_band_m": _rv(rules.TDR_BAND_M, rules.TDR_BAND_CLAUSE, unit="m"),
        "tdr_plot_sqm": _rv(rules.TDR_PLOT_RANGE_SQM, rules.TDR_BAND_CLAUSE, unit="m²"),
        "bands": _bands(site, _widths(road)),
        "limits": [*_road_limits(road), _dead_end_limit(site), _airport_limit(site)]}


def _widths(road: Road | None) -> tuple[non_high_rise.Width, ...]:
    """The access road's legal widths, with how each is known: the road as it stands, and the
    master-plan width when one is given (which counts is the table_iv_road_width reading)."""
    given = (road.legal_row_m, road.master_plan_row_m) if road else ()
    return tuple((w.value, w.status) for w in given if w)


def _bands(site: CanonicalSiteModel, widths: tuple[non_high_rise.Width, ...]) -> list[dict]:
    """Every height in exactly one band. Below the high-rise height, the lines of the plot's
    Table III row, each with its setbacks and the road it asks, then what the row leaves open
    (legal/non_high_rise.py: not permitted, or open through TDR), all read on the height above
    the stilt (rule 5(c)). Then a building of exactly the high-rise height, a high-rise (rule
    2(f)) on the Table IV row that reaches it, in a band of its own, and the rest of Table IV,
    each row with its road, its all-round setback and the gap between two blocks (the same
    figure, rule 7(a)(xii)). A high-rise band is ALLOWED here: the site's high-rise eligibility
    comes in through HeightRules.band_permission."""
    own = site.ownership
    plot = own.net_sqm
    start = rules.HIGH_RISE_THRESHOLD_M
    below = [_below_band(s, plot.value) for s in non_high_rise.stretches(
        plot_sqm=plot.value, plot_status=plot.status, gross_sqm=own.gross_sqm.value,
        gross_status=own.gross_sqm.status, widths=widths, high_rise_from_m=start)]
    exactly = {"above_m": start, "up_to_m": start, "above_inclusive": True}
    high = [_high_rise_band(exactly, rules.band_for_height(start), plot, widths),
            *(_high_rise_band({"above_m": row.above_m, "up_to_m": row.up_to_m}, row, plot, widths)
              for row in rules.TABLE_IV if row.above_m >= start)]
    return [*below, *high]


def _below_band(stretch: non_high_rise.Stretch, plot_sqm: float) -> dict:
    """A stretch below the high-rise height as a band. A line of Table III carries its setbacks
    (the gap between two blocks is the side setback of the taller, rule 5(f)(xiii)) and its
    planting strip (rule 5(f): along the frontage, and on a plot above 300 m² on the other sides
    too); a stretch with no line carries none."""
    band = {"above_m": stretch.above_m, "up_to_m": stretch.up_to_m,
            "above_inclusive": stretch.above_inclusive, "up_to_inclusive": stretch.up_to_inclusive,
            "kind": BandKind.NON_HIGH_RISE, "modelled": True,
            "measure": HeightMeasure.HEIGHT_ABOVE_STILT, "min_road_m": stretch.min_road_m,
            "setback_m": stretch.side_m, "gap_m": stretch.side_m,
            "front_setback_m": stretch.front_m, "permission": stretch.permission,
            "permission_note": stretch.note, "clause": stretch.clause, "status": stretch.status}
    if stretch.side_m is not None:
        around = plot_sqm > rules.NON_HIGH_RISE_PERIPHERY_STRIP_ABOVE_SQM
        band["green_strip_m"] = (max(rules.NON_HIGH_RISE_FRONTAGE_STRIP_M,
                                     rules.NON_HIGH_RISE_PERIPHERY_STRIP_M) if around
                                 else rules.NON_HIGH_RISE_FRONTAGE_STRIP_M)
        band["green_strip_sides"] = "ALL" if around else "FRONTAGE"
    return band


def _high_rise_band(edges: dict, row: rules.HeightBand, plot, widths) -> dict:
    """A row of Table IV as a band. The front is the higher of column 4 and the Building Line
    (rule 7(a)(xi)), kept only where it is higher, and the band says on which road that rests;
    it carries the 2 m planting strip where the setback is 9 m or more (rule 7(a)(viii))."""
    front, settled = non_high_rise.high_rise_front(row.min_open_space_m, plot.value, widths)
    on_the_road = front is not None or not settled
    band = {**edges, "kind": BandKind.HIGH_RISE, "min_road_m": row.min_road_m,
            "setback_m": row.min_open_space_m, "gap_m": row.min_open_space_m,
            "front_setback_m": front,
            "clause": rules.TABLE_IV_CLAUSE
            + (f"; {rules.BUILDING_LINE_HIGH_RISE_CLAUSE}" if on_the_road else ""),
            "status": weakest(Provenance.VERIFIED, *(s for _, s in widths if on_the_road),
                              *([] if settled else [Provenance.UNVERIFIED]))}
    if row.min_open_space_m >= rules.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M:
        band["green_strip_m"] = rules.PERIPHERAL_GREEN_STRIP_M
    return band


def _high_rise(site: CanonicalSiteModel, road: Road | None) -> dict:
    """Whether a high-rise may stand here at all: the road Table IV asks of its first high-rise
    height, and the plot size rule 7(a)(ii) asks. PROHIBITED permits nothing lower."""
    grounds = [_road_ground(road), _plot_ground(site)]
    eligibility = HighRiseEligibility.of_grounds(grounds)
    return {"eligibility": eligibility, "grounds": grounds,
            "note": PROHIBITED_NOTE if eligibility is Eligibility.PROHIBITED else ""}


def _road_ground(road: Road | None) -> EligibilityGround:
    """With a master-plan width as well, the road ground is met only if both widths meet it, not
    met if neither does, and unsettled when it turns on which width counts."""
    need = rules.band_for_height(rules.HIGH_RISE_THRESHOLD_M).min_road_m
    widths = [w for w in ((road.legal_row_m, road.master_plan_row_m) if road else ()) if w]
    if not widths:
        return EligibilityGround(id="road_width", met=None, measured="not given",
                                 required=f"at least {need:g} m", clause=rules.TABLE_IV_CLAUSE,
                                 status=Provenance.UNVERIFIED)
    meets = {w.value >= need for w in widths}
    return EligibilityGround(
        id="road_width", met=meets.pop() if len(meets) == 1 else None,
        measured=" or ".join(f"{w.value:.2f} m ({w.status})" for w in widths),
        required=f"at least {need:g} m", clause=rules.TABLE_IV_CLAUSE,
        status=weakest(Provenance.VERIFIED, *(w.status for w in widths)))


def _plot_ground(site: CanonicalSiteModel) -> EligibilityGround:
    """Rule 7(a)(ii), on the net plot. Rule 7(a)(iii) lets a site left short by road widening
    count when the shortfall is small, which is not modelled: a site that falls just short with
    land surrendered is unsettled rather than refused."""
    own = site.ownership
    net, minimum = own.net_sqm, rules.MIN_HIGH_RISE_PLOT_SQM
    surrendered = any(d.kind is DeductionKind.SURRENDER for d in own.deductions)
    found = rules.high_rise_plot_met(net.value, surrendered)  # the validator reads it the same
    met, near = found is True, found is None
    return EligibilityGround(
        id="plot_size", met=met, measured=f"net plot {net.value:,.0f} m²",
        required=f"at least {minimum:,.0f} m²"
        + (f"; {rules.ROAD_WIDENING_SHORTFALL_CLAUSE} may count a small shortfall left by road "
           "widening, which is not modelled" if near else ""),
        clause=rules.MIN_HIGH_RISE_PLOT_CLAUSE,
        status=Provenance.UNVERIFIED if near else weakest(Provenance.VERIFIED, net.status))


def _road_limits(road: Road | None) -> list[dict]:
    """Table IV column 3 read on the access road's legal width. A master-plan width gives a second
    limit; which of the two is in force turns on whether the strip is surrendered, which no site
    fact settles yet, so both stay UNKNOWN (and the table_iv_road_width reading stays open)."""
    width = road.legal_row_m if road is not None else None
    if width is None:
        return [{"id": "table_iv_road", "measure": HeightMeasure.RULE_HEIGHT,
                 "bound": LimitBound.NOT_EVALUATED,
                 "reason": "the access road's legal width is not given, so Table IV cannot be "
                           "read",
                 "clause": rules.TABLE_IV_CLAUSE, "status": Provenance.UNVERIFIED}]
    plan = road.master_plan_row_m
    if plan is None:
        return [_table_iv_limit("table_iv_road", width.value, width.status, road.row_status,
                                "road", None)]
    surrendered = SiteFact.MASTER_PLAN_LAND_SURRENDERED
    return [_table_iv_limit("table_iv_road", width.value, width.status, road.row_status, "road",
                            {"fact": surrendered, "holds_when": False,
                             "text": "the master-plan strip is not surrendered, so the road "
                                     "stays as it is"}),
            _table_iv_limit("table_iv_master_plan_road", plan.value, plan.status, None,
                            "master-plan road",
                            {"fact": surrendered, "holds_when": True,
                             "text": "the land for the master-plan road is surrendered "
                                     "(rule 16)"})]


def _table_iv_limit(limit_id: str, width_m: float, width_status: Provenance,
                    row_status: str | None, what: str, condition: dict | None) -> dict:
    top = rules.max_height_for_road(width_m)
    tag = f"{row_status}, {width_status}" if row_status else str(width_status)
    road = f"the {width_m:.2f} m {what} ({tag})"
    limit = {"id": limit_id, "measure": HeightMeasure.RULE_HEIGHT,
             "clause": rules.TABLE_IV_CLAUSE,
             "status": weakest(Provenance.VERIFIED, width_status), "condition": condition,
             "applicability": Applicability.APPLIES if condition is None
             else Applicability.UNKNOWN}
    if top is None:
        first = rules.TABLE_IV[0].min_road_m
        return limit | {"bound": LimitBound.BOUNDED, "max_m": rules.HIGH_RISE_THRESHOLD_M,
                        "inclusive": False,
                        "reason": f"{road} is under the {first:g} m Table IV asks of a "
                                  "high-rise, so no building of "
                                  f"{rules.HIGH_RISE_THRESHOLD_M:g} m or more may stand on it; "
                                  "what it allows below that is the non-high-rise bands' (Table "
                                  "III), not this limit's"}
    if math.isinf(top):
        return limit | {"bound": LimitBound.UNBOUNDED,
                        "reason": f"{road} meets every Table IV row: the road sets no height "
                                  "limit, so setbacks, fire and airport norms decide"}
    beyond = next(band for band in rules.TABLE_IV if band.above_m >= top)
    return limit | {"bound": LimitBound.BOUNDED, "max_m": top,
                    "reason": f"{road} serves buildings up to {top:g} m; up to "
                              f"{beyond.up_to_m:g} m needs {beyond.min_road_m:g} m of road"}


def _dead_end_limit(site: CanonicalSiteModel) -> dict:
    """NBC 4.6(b): above 30 m of physical height a residential building may not stand on a road
    that ends at the plot. The limit is always listed; whether it is in force follows the site's
    answer (UNKNOWN while nobody has said where the road leads)."""
    dead_end = site.access.dead_end
    known = {None: "the road's end is not known", True: "the road ends at the plot",
             False: "the road runs on past the plot"}[dead_end.value]
    return {"id": "dead_end", "measure": HeightMeasure.PHYSICAL_HEIGHT,
            "bound": LimitBound.BOUNDED, "max_m": rules.DEAD_END_MAX_HEIGHT_M,
            "condition": {"fact": SiteFact.ROAD_ENDS_AT_PLOT, "holds_when": True,
                          "text": "the access road ends at the plot"},
            "applicability": APPLICABILITY[dead_end.value],
            "reason": "no dead-end road for a residential building above this height, which "
                      f"NBC measures from the ground, stilt included ({known})",
            "clause": rules.DEAD_END_CLAUSE,
            "status": Provenance.VERIFIED if dead_end.value is None else weakest(
                Provenance.VERIFIED, dead_end.status)}


def _airport_limit(site: CanonicalSiteModel) -> dict:
    where = site.coordinates
    reason = ("no site coordinates: airport and Air Force height limits are not evaluated"
              if where is None else
              f"airport and Air Force height limits are not computed; read the maps at "
              f"{where.value[0]:.5f}, {where.value[1]:.5f}")
    return {"id": "airport", "measure": HeightMeasure.AMSL, "bound": LimitBound.NOT_EVALUATED,
            "reason": reason, "clause": AIRPORT_CLAUSE, "status": Provenance.UNVERIFIED}


# --- The rest of the law ---------------------------------------------------------------------


def _setbacks() -> dict:
    return {
        "measured_on": _rv("net plot", rules.SETBACK_ON_NET_PLOT_CLAUSE),
        "front": _rv("a block below 21 m: the Building Line of Table III for the road's width; a "
                     "high-rise: the higher of that and Table IV column 4",
                     rules.BUILDING_LINE_HIGH_RISE_CLAUSE,
                     note="Table III's front is by the abutting road's legal width, reckoned as "
                          "rule 5(f)(xvii) reckons it. A site on more than one road keeps its "
                          "front towards the bigger (rule 5(f)(iii)); the model knows the access "
                          "road only. The clause the legacy checker cites for the front, p.17(b), "
                          "is rule 12(b), for commercial courtyard buildings"),
        "concessions": [
            _rv("down to 7 m clear on all sides", rules.ROAD_WIDENING_CLAUSE,
                note="a high-rise's, when land is surrendered for a road; the engine does not "
                     "apply it, so setbacks stay at the Table IV figure"),
            _rv("a block below 21 m: building line of 6, 3 or 2 m for a road of 30 m or more, "
                "18 m to under 30 m, under 18 m; side and rear 2, 2.5 or 3 m up to 12, 15 or "
                "18 m of height", rules.ROAD_WIDENING_NON_HIGH_RISE_CLAUSE,
                note="the owner's choice when land is surrendered for a road, and the floor of a "
                     f"TDR relaxation ({rules.TDR_NON_HIGH_RISE_SETBACK_CLAUSE}); the engine "
                     "does not apply it, so setbacks stay at the Table III figure")]}


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
        "buffer_may_count": _rv(True, rules.WATER_BUFFER_CLAUSE),
        "qualifying_uses": _rv([FacilityUse.GREENERY, FacilityUse.TOT_LOT,
                                FacilityUse.SOFT_LANDSCAPE], rules.OPEN_SPACE_CLAUSE,
                               note="the uses the rule names: 'greenery, tot lot or soft "
                                    "landscaping, etc.'; the 'etc.' and a tot-lot's surface are "
                                    "open readings")}


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
        "pathway_width_m": _rv(rules.PATHWAY_WIDTH_M, rules.PATHWAY_CLAUSE, unit="m"),
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
        "ramp_fire_clearance_m": _rv(rules.RAMP_FIRE_CLEARANCE_M, rules.RAMP_CLAUSE, unit="m"),
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
                              "apartment block", rules.AMENITY_CLAUSE)}

