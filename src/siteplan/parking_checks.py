"""Parking findings: Table V, visitors' parking, the cellars and their ramp (rule 13).

A drawn layout carries its parking plan (parking.ParkingPlan): the stilt, the surface bays and
the cellars, each measured from its own geometry. Without one, as when a project file is checked
on its own, only the stilt and surface bays are known and a shortfall is UNVERIFIED rather than a
FAIL, because the rest may be in cellars nobody has drawn.
"""

from __future__ import annotations

from siteplan import rules
from siteplan.findings import Finding, Status

AREA_SLACK_SQM = 0.5


def parking_findings(site) -> list[Finding]:
    plan = site.parking_plan
    if plan is None:
        return [_undrawn(site)]
    findings = [_table_v(site, plan), _visitors(plan)]
    if plan.cellar_levels:
        findings += [_cellar_setback(site, plan), _ramp(site, plan), _utilities(plan)]
    return findings


def _clause(site) -> str:
    clause = rules.PARKING_CLAUSE
    return f"{clause}; {rules.CURE_RULES_CLAUSE}" if site.inside_cure else clause


def _table_v(site, plan) -> Finding:
    need = plan.required_sqm
    parts = [f"stilt {plan.stilt_sqm:,.0f} m²", f"surface {plan.surface_sqm:,.0f} m²"]
    if plan.cellar_levels:
        parts.append(f"{plan.cellar_levels} cellar level{'s' if plan.cellar_levels > 1 else ''} "
                     f"x {plan.cellar_sqm_per_level:,.0f} m²")
    measured = " + ".join(parts) + f" = {plan.provided_sqm:,.0f} m²"
    if plan.cars:
        measured += f"; {sum(plan.cars.values()):,} cars fit in bays and aisles"
    required = f">= {plan.percent:g}% of built-up = {need:,.0f} m² ({plan.basis})"
    if plan.provided_sqm + AREA_SLACK_SQM >= need:
        return Finding("Parking (Table V)", Status.PASS, measured, required, _clause(site))
    lenient = rules.PARKING_PERCENT_ELSEWHERE / 100 * plan.built_up_sqm
    unsettled = plan.percent > rules.PARKING_PERCENT_ELSEWHERE and "not settled" in plan.basis
    if unsettled and plan.provided_sqm + AREA_SLACK_SQM >= lenient:
        return Finding("Parking (Table V)", Status.UNVERIFIED, measured, required, _clause(site),
                       "Enough at 20%, short at 30%: it depends on whose rules apply.")
    return Finding("Parking (Table V)", Status.FAIL,
                   f"{measured}, short by {need - plan.provided_sqm:,.0f} m²", required,
                   _clause(site))


def _visitors(plan) -> Finding:
    need = rules.VISITOR_PARKING_FRACTION * plan.required_sqm
    ok = plan.ground_sqm + AREA_SLACK_SQM >= need
    return Finding(
        "Visitors' parking", Status.PASS if ok else Status.FAIL,
        f"{plan.ground_sqm:,.0f} m² at ground level (stilt and surface)",
        f">= {rules.VISITOR_PARKING_FRACTION:.0%} of the Table V area = {need:,.0f} m², "
        "marked on the ground", rules.VISITOR_PARKING_CLAUSE,
        "Read as parking at ground level, stilt or open, which a visitor can reach from the "
        "entrance; which bays are marked for visitors is for the detailed drawing.",
    )


def _cellar_setback(site, plan) -> Finding:
    need = rules.cellar_setback_m(site.net_plot.area if site.net_plot is not None
                                  else (site.net_area_sqm or 0.0), plan.cellar_levels)
    required = (f">= {need:g} m from the property line for {plan.cellar_levels} cellar "
                f"level{'s' if plan.cellar_levels > 1 else ''}")
    if plan.cellar_outline is None or site.net_plot is None:
        return Finding("Cellar setback", Status.NOT_CHECKED, "no cellar outline", required,
                       rules.CELLAR_SETBACK_CLAUSE)
    gap = site.net_plot.exterior.distance(plan.cellar_outline)
    return Finding("Cellar setback", Status.PASS if gap + 0.01 >= need else Status.FAIL,
                   f"{gap:.2f} m", required, rules.CELLAR_SETBACK_CLAUSE,
                   "Every cellar level keeps the setback of the deepest, the stricter reading.")


def _ramp(site, plan) -> Finding:
    rise = plan.ramp_length_m * rules.RAMP_MAX_GRADIENT
    required = (f"one ramp >= {rules.RAMP_SINGLE_MIN_WIDTH_M:g} m or two >= "
                f"{rules.RAMP_PAIR_MIN_WIDTH_M:g} m, 1 in 8, outside the mandatory setbacks")
    if not plan.ramps:
        return Finding("Cellar ramp", Status.FAIL, "no ramp drawn", required, rules.RAMP_CLAUSE)
    problems = []
    if plan.ramp_width_m + 1e-6 < rules.RAMP_SINGLE_MIN_WIDTH_M:
        problems.append("narrower than 5.4 m")
    setback = max((b for b in _setbacks(site)), default=0.0)
    if site.net_plot is not None and setback:
        inside = site.net_plot.buffer(-(setback - 0.02))
        if any(r.difference(inside).area > AREA_SLACK_SQM for r in plan.ramps):
            problems.append("in the setback")
    road_land = [r.shape for r in site.roads]
    if road_land and not all(any(r.distance(s) < 0.1 for s in road_land) for r in plan.ramps):
        problems.append("not reached from a road")
    measured = (f"{len(plan.ramps)} x {plan.ramp_width_m:g} m wide, {plan.ramp_length_m:g} m "
                f"long for a {rise:g} m drop (1 in 8), beside a road, inside the setbacks")
    return Finding("Cellar ramp", Status.FAIL if problems else Status.PASS,
                   "; ".join(problems) if problems else measured, required, rules.RAMP_CLAUSE,
                   "Each cellar level loses one ramp's footprint to the ramp down to it.")


def _setbacks(site):
    for b in site.buildings:
        band = rules.band_for_height(b.resolved_height() or 0)
        if band is not None:
            yield band.min_open_space_m


def _utilities(plan) -> Finding:
    return Finding(
        "Cellar utilities", Status.INFO,
        f"{plan.utilities_fraction:.0%} of each cellar kept for utilities (STP, DG, electrical)",
        f"up to {rules.CELLAR_UTILITIES_MAX_FRACTION:.0%}", rules.CELLAR_UTILITIES_CLAUSE,
        "Taken in full, so the parking left is not overstated.",
    )


def _undrawn(site) -> Finding:
    """A project checked on its own: stilt and surface only; the rest may be in cellars."""
    percent = rules.parking_percent(site.authority, site.inside_cure)
    required = f">= {percent:g}% of built-up area"
    if site.built_up_sqm is None:
        return Finding("Parking (Table V)", Status.NOT_CHECKED, "built-up area unknown",
                       required, _clause(site))
    need = percent / 100 * site.built_up_sqm
    stilt = sum(b.footprint.area for b in site.buildings if b.footprint is not None)
    provided = stilt + site.surface_parking_sqm
    measured = f"stilt {stilt:,.0f} m² + surface {site.surface_parking_sqm:,.0f} m²"
    note = "No cellars drawn."
    if site.authority is None and site.inside_cure is None:
        note += (" Authority not given, so the 20% column is used; inside GHMC or anywhere in "
                 "CURE it is 30%.")
    if provided + AREA_SLACK_SQM >= need:
        return Finding("Parking (Table V)", Status.PASS, measured,
                       f"{required} = {need:,.0f} m²", _clause(site), note)
    return Finding("Parking (Table V)", Status.UNVERIFIED,
                   f"{measured}, short by {need - provided:,.0f} m²",
                   f"{required} = {need:,.0f} m²", _clause(site),
                   f"{note} Say where the rest goes (cellar or podium) to settle this.")
