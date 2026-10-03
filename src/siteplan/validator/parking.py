"""Parking (rule 13, Table V): what the stilt, the surface and the cellars really provide.

Table V asks a share of the built-up area, which the validator recomputes from the towers and the
club house as drawn. It is provided in the stilt (each tower's footprint less its cores), in
surface bays (counted only where a bay may be), and in cellars (the outline under the cellar
setback, less cores, ramp and the utilities share). The floor area has to meet the need and so
does what physically fits on it: cars laid out in bays and aisles, counted here by cars.py.

Where the cellars are not drawn at all, a shortfall is UNVERIFIED (the rest may be underground),
not a FAIL: a candidate that says it has no cellars (zero levels) and is short, is.
"""

from __future__ import annotations

from dataclasses import dataclass

import shapely

from siteplan import rules as law
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    STILT_IN_RULE_HEIGHT,
    VISITOR_PARKING,
    ResolvedRules,
    TableVColumn,
)
from siteplan.contracts.validation import Check, Family
from siteplan.validator.cars import cars_on_floor
from siteplan.validator.context import Context
from siteplan.validator.fire import clear_band
from siteplan.validator.ground import BAYS, Ground
from siteplan.validator.readings import (
    ANYWHERE,
    AT_GROUND,
    TABLE_V_COLUMN,
    Assignment,
    Cell,
    check_from,
    plain,
    run,
    unknown_reading,
    verdict,
)
from siteplan.validator.shapes import (
    NOISE_SQM,
    polygons_of,
    sides_of,
    union_of_all,
    width_of,
)
from siteplan.validator.zones import deepest_setback_m, ramp_zones, setback_zone

AREA_SLACK_SQM = 0.5  # parking short of the need by less than this is rounding
BAY_SLACK_M = 0.05  # a bay this close to the standard size is that size
BAY_FILL = 0.95  # a bay fills this much of the rectangle round it: a frame or a triangle is no bay
BAY_OVERLAP_SQM = 0.01  # a bay this much on anything else is on it
CELLAR_SLACK_M = 0.01
RAMP_TOUCH_M = 0.5  # a ramp this close to a road has its top on it
RAMP_SLACK_M = 0.05  # a ramp drawn this close to its size is that size
NO_SETBACK_NOTE = ("The setback is not known under this reading (below the high-rise threshold "
                   "Table III applies and is not modelled), so which ground is outside it is "
                   "not known.")


def table_v_columns(ctx: Context) -> dict[str, float]:
    """Each Table V share the site could take: the one its jurisdiction settles, or both."""
    p = ctx.rules.parking
    if p.share_pct is not None:
        return {ctx.rules.jurisdiction.table_v_column.value: p.share_pct.value}
    return {c.value: pct for c, pct in p.share_pct_by_column.items() if c is not TableVColumn.OPEN}


def bay_standard(ctx: Context) -> tuple[tuple[float, float], float, float]:
    """(bay, aisle, square metres of floor per car): the firm's own sizes where it sets them,
    otherwise the engine's standard in the rules."""
    m, firm = ctx.rules.parking.measurement, ctx.brief.firm_standards
    bay = firm.bay_size_m.value if firm.bay_size_m else m.bay_m
    aisle = firm.aisle_m.value if firm.aisle_m else m.aisle_m
    own = firm.bay_size_m is not None or firm.aisle_m is not None
    return bay, aisle, (bay[0] * (bay[1] + aisle / 2) if own else m.sqm_per_car)


def cellar_setback_m(rules: ResolvedRules, site_sqm: float, levels: int) -> float | None:
    """Rule 13(c)(x): the setback by site size, and 0.5 m more for every cellar beyond the
    first, applied to all of them (the stricter reading of an unsettled clause). None when the
    rules' table has no row for a site this large (it should end 'and above'): which setback
    applies is then not known, and nothing is guessed."""
    table = rules.parking.cellar_setback_by_site_sqm.value
    base = next((m for up_to, m in table if up_to is None or site_sqm <= up_to), None)
    if base is None:
        return None
    return base + rules.parking.cellar_extra_setback_per_level_m.value * max(0, levels - 1)


# --- What is provided, whatever the reading ---------------------------------------------------


@dataclass(frozen=True)
class Floors:
    built_up_sqm: float
    stilt_sqm: float
    stilt_cars: int
    cellar_levels: int
    cellar_drawn: bool
    cellar_sqm_per_level: float
    cellar_cars_per_level: int
    sqm_per_car: float

    @property
    def cellar_sqm(self) -> float:
        return self.cellar_levels * self.cellar_sqm_per_level

    @property
    def cellar_cars(self) -> int:
        return self.cellar_levels * self.cellar_cars_per_level


def measure_floors(ctx: Context) -> Floors:
    d = ctx.drawn
    bay, aisle, sqm_per_car = bay_standard(ctx)
    built_up = sum(t.built_up_sqm for t in ctx.towers) + d.club.area * d.club_floors
    cores_all = union_of_all([c for t in ctx.towers for c in t.cores])
    stilts = [(t, t.footprint.difference(union_of_all(list(t.cores)))) for t in ctx.towers
              if t.has_stilt]
    stilt_sqm = sum(f.area for _, f in stilts)
    stilt_cars = sum(cars_on_floor(f, [t.placed.rotation_deg], bay, aisle) for t, f in stilts)
    per_level, cars_per_level = 0.0, 0
    if d.cellar_levels and not d.cellar_outline.is_empty:
        utilities = ctx.brief.firm_standards.cellar_utilities_share.value
        floor = d.cellar_outline.difference(union_of_all([cores_all, *d.ramps]))
        per_level = floor.area * (1 - utilities)
        angles = sorted({t.placed.rotation_deg for t in ctx.towers} | {0.0})
        cars_per_level = int(cars_on_floor(floor, angles, bay, aisle) * (1 - utilities))
    return Floors(built_up, stilt_sqm, stilt_cars, d.cellar_levels, d.cellar_drawn, per_level,
                  cars_per_level, sqm_per_car)


# --- Surface bays ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Surface:
    valid: int
    problems: dict[str, int]  # why drawn bays do not count, and how many
    setback_known: bool = True  # False: which bays stand in a setback could not be told


def surface_bays(ctx: Context, ground: Ground, reading: str) -> Surface:
    """The drawn bays that may be bays: the right size, on the plot, outside the setback and the
    fire lanes' clear ground, off the roads and every building, and not on another bay."""
    d = ctx.drawn
    bay, _, _ = bay_standard(ctx)
    long_side, short_side = max(bay), min(bay)
    zone = setback_zone(ctx, reading)
    lane = ctx.rules.fire.clear_width_m.value
    bands = union_of_all([clear_band(t.footprint, lane) for t in ctx.high_rise(reading)])
    others = union_of_all([g for owner, g in ground.solids if owner != BAYS])
    tree = shapely.STRtree(list(d.bays))
    problems: dict[str, int] = {}
    valid = 0
    for i, b in enumerate(d.bays):
        long, short = sides_of(b)
        why = None
        if long + BAY_SLACK_M < long_side or short + BAY_SLACK_M < short_side:
            why = "too small for a car"
        elif b.area < BAY_FILL * long * short:
            why = "not a rectangle a car fits in"
        elif b.difference(ctx.net).area > BAY_OVERLAP_SQM:
            why = "off the plot"
        elif zone is not None and b.intersection(zone).area > BAY_OVERLAP_SQM:
            why = "in the setback"
        elif b.intersection(bands).area > BAY_OVERLAP_SQM:
            why = "in a fire lane's clear ground"
        elif b.intersection(d.motorable).area > BAY_OVERLAP_SQM:
            why = "on a road or fire lane"
        elif b.intersection(others).area > BAY_OVERLAP_SQM:
            why = "on a building, ramp or facility"
        elif any(j != i and b.intersection(d.bays[j]).area > BAY_OVERLAP_SQM
                 for j in tree.query(b)):
            why = "on another bay"
        if why:
            problems[why] = problems.get(why, 0) + 1
        else:
            valid += 1
    return Surface(valid, problems, setback_known=zone is not None)


def surface_check(ctx: Context, ground: Ground) -> Check | None:
    if not ctx.drawn.bays:
        return None
    count = len(ctx.drawn.bays)
    bay, _, _ = bay_standard(ctx)

    def cell(a: Assignment) -> Cell:
        s = surface_bays(ctx, ground, a[STILT_IN_RULE_HEIGHT])
        why = ", ".join(f"{n} {w}" for w, n in s.problems.items())
        measured = f"{s.valid} of {count} bays are bays" + (f"; {why}" if why else "")
        required = (f"each {bay[0]:g} x {bay[1]:g} m, outside the setback and the fire lanes, "
                    "off roads and buildings")
        if not s.problems and not s.setback_known:
            return Cell(Status.UNVERIFIED, measured, required, NO_SETBACK_NOTE)
        return Cell(verdict(not s.problems), measured, required,
                    "Bays that are not bays do not count as parking.")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.PARKING,
                      rule="Surface parking bays", clause="G.O.168 rule 13(b)(iii); "
                      + ctx.rules.fire.clear_width_m.clause)


# --- Table V and visitors' parking -----------------------------------------------------------


def _clause(ctx: Context) -> str:
    p = ctx.rules.parking
    base = p.share_pct.clause if p.share_pct is not None else law.PARKING_CLAUSE
    return f"{base}; {law.CURE_RULES_CLAUSE}" if ctx.site.jurisdiction.inside_cure.value else base


def _provision(f: Floors, surface: int, bay_sqm: float) -> tuple[float, float, int]:
    """(floor area, area the cars laid out account for, cars) of stilt, surface and cellars."""
    floor = f.stilt_sqm + surface * bay_sqm + f.cellar_sqm
    cars = f.stilt_cars + surface + f.cellar_cars
    return floor, cars * f.sqm_per_car, cars


def _short_status(ctx: Context) -> Status:
    """What falling short means: UNVERIFIED while the cellars are not drawn, else FAIL."""
    return Status.UNVERIFIED if (not ctx.drawn.cellar_drawn or ctx.drawn.buildings_only) \
        else Status.FAIL


def table_v_check(ctx: Context, ground: Ground, f: Floors) -> Check:
    columns = table_v_columns(ctx)
    bay, _, _ = bay_standard(ctx)
    bay_sqm = bay[0] * bay[1]
    surfaces = {r: surface_bays(ctx, ground, r) for r in ctx.stilt_readings}

    def cell(a: Assignment) -> Cell:
        pct = columns[a[TABLE_V_COLUMN]]
        need = pct / 100 * f.built_up_sqm
        floor, laid_out, cars = _provision(f, surfaces[a[STILT_IN_RULE_HEIGHT]].valid, bay_sqm)
        parts = [f"stilt {f.stilt_sqm:,.0f} m²",
                 f"surface {surfaces[a[STILT_IN_RULE_HEIGHT]].valid * bay_sqm:,.0f} m²"]
        if f.cellar_levels:
            parts.append(f"{f.cellar_levels} cellar level{'s' if f.cellar_levels > 1 else ''} "
                         f"x {f.cellar_sqm_per_level:,.0f} m²")
        measured = (" + ".join(parts) + f" = {floor:,.0f} m² of parking floor; {cars:,} cars fit "
                    f"in bays and aisles = {laid_out:,.0f} m² laid out")
        required = (f">= {pct:g}% of built-up {f.built_up_sqm:,.0f} m² = {need:,.0f} m² "
                    f"(Table V column {a[TABLE_V_COLUMN]}), as floor and as bays and aisles that "
                    "fit")
        provided = min(floor, laid_out)
        if provided + AREA_SLACK_SQM >= need:
            surface = surfaces[a[STILT_IN_RULE_HEIGHT]]
            without = min(_provision(f, 0, bay_sqm)[:2])
            if not surface.setback_known and surface.valid and without + AREA_SLACK_SQM < need:
                return Cell(Status.UNVERIFIED, measured, required,
                            NO_SETBACK_NOTE + " It passes only by counting the surface bays.")
            return Cell(Status.PASS, measured, required)
        short = f"{measured}, short by {need - provided:,.0f} m²"
        note = ("No cellar plan is drawn, so the rest may be underground." if
                _short_status(ctx) is Status.UNVERIFIED else "")
        return Cell(_short_status(ctx), short, required, note)

    return check_from(
        run(ctx.rules, [STILT_IN_RULE_HEIGHT, TABLE_V_COLUMN], cell,
            extra={TABLE_V_COLUMN: list(columns)}),
        family=Family.PARKING, rule="Parking (Table V)", clause=_clause(ctx),
        note="" if len(columns) == 1 else "Whose rules apply is not established: both Table V "
        "columns are evaluated.")


def visitors_check(ctx: Context, ground: Ground, f: Floors) -> Check:
    columns = table_v_columns(ctx)
    fraction = ctx.rules.parking.visitors_fraction.value
    bay, _, _ = bay_standard(ctx)
    surfaces = {r: surface_bays(ctx, ground, r).valid for r in ctx.stilt_readings}

    def cell(a: Assignment) -> Cell:
        reading = a[VISITOR_PARKING]
        if reading not in (AT_GROUND, ANYWHERE):
            return unknown_reading(VISITOR_PARKING, reading)
        need = fraction * columns[a[TABLE_V_COLUMN]] / 100 * f.built_up_sqm
        surface_sqm = surfaces[a[STILT_IN_RULE_HEIGHT]] * bay[0] * bay[1]
        ground_sqm = f.stilt_sqm + surface_sqm
        counted = ground_sqm if reading == AT_GROUND else ground_sqm + f.cellar_sqm
        where = "at ground level (stilt and surface)" if reading == AT_GROUND else "in all parking"
        ok = counted + AREA_SLACK_SQM >= need
        status = Status.PASS if ok else _short_status(ctx)
        return Cell(status, f"{counted:,.0f} m² {where}",
                    f">= {fraction:.0%} of the Table V area = {need:,.0f} m², marked on the ground",
                    "Which bays are marked for visitors is for the detailed drawing.")

    return check_from(
        run(ctx.rules, [STILT_IN_RULE_HEIGHT, VISITOR_PARKING, TABLE_V_COLUMN], cell,
            extra={TABLE_V_COLUMN: list(columns)}),
        family=Family.PARKING, rule="Visitors' parking",
        clause=ctx.rules.parking.visitors_fraction.clause)


# --- Cellars and their ramp ------------------------------------------------------------------


def cellar_setback_check(ctx: Context, f: Floors) -> Check:
    d = ctx.drawn
    need = cellar_setback_m(ctx.rules, ctx.net.area, f.cellar_levels)
    clause = ctx.rules.parking.cellar_setback_by_site_sqm.clause
    if need is None:
        return plain(Family.PARKING, "Cellar setback", Status.UNVERIFIED,
                     f"the rules' table has no row for a site of {ctx.net.area:,.0f} m²",
                     "the setback rule 13(c)(x) gives for this site", clause,
                     "The table should end with a row for sites above its last size; which "
                     "setback applies is not known, so none is held to.")
    required = (f">= {need:g} m from the property line for {f.cellar_levels} cellar "
                f"level{'s' if f.cellar_levels > 1 else ''}")
    if d.cellar_outline.is_empty:
        return plain(Family.PARKING, "Cellar setback", Status.FAIL,
                     "cellar levels but no outline drawn", required, clause)
    inside = ctx.net.contains(d.cellar_outline)
    gap = float(ctx.net.boundary.distance(d.cellar_outline)) if inside else 0.0
    in_water = d.cellar_outline.intersection(ctx.land.keep_out).area > NOISE_SQM
    problems = []
    if gap + CELLAR_SLACK_M < need:
        problems.append(f"{gap:.2f} m from the property line")
    if in_water:
        problems.append("inside a water buffer")
    return plain(Family.PARKING, "Cellar setback", verdict(not problems),
                 "; ".join(problems) if problems else f"{gap:.2f} m", required, clause,
                 "Every cellar level keeps the setback of the deepest, the stricter reading.")


def ramp_check(ctx: Context, f: Floors) -> Check:
    p, d = ctx.rules.parking, ctx.drawn
    single, pair = p.ramp_single_min_m.value, p.ramp_pair_min_m.value
    rise = ctx.brief.firm_standards.cellar_floor_height_m.value
    length_needed = rise / p.ramp_gradient.value
    required = (f"one ramp >= {single:g} m or two >= {pair:g} m, {length_needed:g} m long (1 in "
                f"{1 / p.ramp_gradient.value:g}), from a road down to the cellar, outside the "
                "mandatory setbacks")
    clause = p.ramp_single_min_m.clause
    road_land = d.road_land
    ramps = [r for r in polygons_of(union_of_all(list(d.ramps))) if r.area > NOISE_SQM]

    def cell(a: Assignment) -> Cell:
        reading = a[STILT_IN_RULE_HEIGHT]
        if not ramps:
            return Cell(Status.FAIL, "no ramp drawn", required)
        widths = [width_of(r, max(single, pair) + 1.0) for r in ramps]
        lengths = [sides_of(r)[0] for r in ramps]
        problems = []
        if not (any(w + RAMP_SLACK_M >= single for w in widths)
                or (len(widths) >= 2 and all(w + RAMP_SLACK_M >= pair for w in widths))):
            problems.append(f"width {', '.join(f'{w:.2f}' for w in widths)} m")
        if any(n + RAMP_SLACK_M < length_needed for n in lengths):
            problems.append("too short for a 1 in 8 slope")
        if road_land.is_empty or any(r.distance(road_land) > RAMP_TOUCH_M for r in ramps):
            problems.append("top not on a road")
        if d.cellar_outline.is_empty or all(
                r.distance(d.cellar_outline) > RAMP_TOUCH_M for r in ramps):
            problems.append("does not reach the cellar")
        forbidden, front_only = ramp_zones(ctx, reading)
        into = union_of_all(ramps)
        if into.intersection(forbidden).area > NOISE_SQM:
            problems.append("in a setback where a ramp may not be")
        measured = ("; ".join(problems) if problems else
                    f"{len(ramps)} x {widths[0]:.2f} m wide, {lengths[0]:.1f} m long, beside a "
                    "road, clear of the setbacks")
        if not problems and deepest_setback_m(ctx, reading) is None:
            return Cell(Status.UNVERIFIED, measured, required, NO_SETBACK_NOTE)
        if not problems and into.intersection(front_only).area > NOISE_SQM:
            return Cell(Status.UNVERIFIED, "in a setback; which side is the front is not known",
                        required, "A ramp may use a side or rear setback leaving 7 m, never the "
                        "front, and the access side is not known.")
        return Cell(verdict(not problems), measured, required,
                    "Each cellar level loses one ramp's footprint to the ramp down to it.")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.PARKING,
                      rule="Cellar ramp", clause=clause)


def utilities_check(ctx: Context) -> Check:
    share = ctx.brief.firm_standards.cellar_utilities_share.value
    cap = ctx.rules.parking.utilities_max_fraction
    return plain(Family.PARKING, "Cellar utilities", Status.INFO,
                 f"{share:.0%} of each cellar kept for utilities (STP, DG, electrical)",
                 f"up to {cap.value:.0%}", cap.clause,
                 "Taken in full, so the parking left is not overstated.")


# --- All of it -------------------------------------------------------------------------------


def parking_checks(ctx: Context, ground: Ground) -> tuple[list[Check], dict[str, float]]:
    f = measure_floors(ctx)
    out = [table_v_check(ctx, ground, f), visitors_check(ctx, ground, f)]
    surface = surface_check(ctx, ground)
    out += [surface] if surface else []
    if f.cellar_levels:
        out += [cellar_setback_check(ctx, f), ramp_check(ctx, f), utilities_check(ctx)]
    first = ctx.stilt_readings[0]
    surface_cars = surface_bays(ctx, ground, first).valid
    quantities = {"built_up_sqm": f.built_up_sqm, "parking_stilt_sqm": f.stilt_sqm,
                  "parking_cars": float(f.stilt_cars + f.cellar_cars + surface_cars),
                  "parking_stilt_cars": float(f.stilt_cars),
                  "parking_cellar_levels": float(f.cellar_levels),
                  "parking_cellar_sqm_per_level": f.cellar_sqm_per_level,
                  "parking_cellar_cars": float(f.cellar_cars)}
    for column, pct in table_v_columns(ctx).items():
        quantities[f"parking_required_sqm[{column}]"] = pct / 100 * f.built_up_sqm
    return out, quantities
