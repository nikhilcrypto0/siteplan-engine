"""Fire access (NBC 2016 Part 3 4.6, brought in by G.O.168 rule 15(b)(iv)), measured from the
drawing.

Every high-rise needs 6 m of clear, motorable ground on all sides, room for the tender to turn
round each corner and each bend of the loop road, a lane from a gate to all of it, and nothing
parked or built in it. The bands and the swept turns are built here from the lane width and the
radii in the rules; the generator's fire lanes are only ground the candidate says is motorable.

What a drawing cannot show stays UNVERIFIED: where the street leads, whether the road ends at
the plot, and the 45 t loading, which is a paving specification.
"""

from __future__ import annotations

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import FIRE_TURNING_RADIUS, STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import Check, Family
from siteplan.provenance import Provenance
from siteplan.validator.context import Context
from siteplan.validator.ground import Ground
from siteplan.validator.measure import TOL_M, TowerGeometry
from siteplan.validator.readings import (
    Assignment,
    Cell,
    check_from,
    plain,
    run,
    unknown_reading,
    verdict,
)
from siteplan.validator.shapes import NOISE_SQM, opening, sides_of, union_of_all
from siteplan.validator.turning import road_bends, round_block, turning_for

NON_HIGH_RISE_NOTE = ("Below the high-rise threshold the fire rules of rule 15(a)(i) apply and "
                      "are not modelled yet.")
REACH_MIN_SQM = 1.0  # a lane that only touches a block's band at a point does not reach it


def clear_band(footprint: Polygon, lane_m: float) -> BaseGeometry:
    """The ground that must stay clear round a block: the lane's width on every side, corners
    square."""
    return footprint.buffer(lane_m, join_style="mitre").difference(footprint)


def reached(ctx: Context) -> BaseGeometry:
    """The lanes (ground at least a lane wide) that connect to a gate."""
    lane = ctx.rules.fire.clear_width_m.value
    start = ctx.drawn.gate_land.buffer(0.5)
    if start.is_empty:
        return Polygon()
    passable = opening(ctx.drawn.motorable, lane - 0.02)
    return union_of_all([p for p in getattr(passable, "geoms", [passable])
                         if not p.is_empty and p.intersects(start)])


def _no_layout(ctx: Context) -> Check:
    return plain(
        Family.FIRE, "Fire access: around each block", Status.UNVERIFIED,
        "no road and lane layout drawn",
        f">= {ctx.rules.fire.clear_width_m.value:g} m clear and motorable on all sides",
        ctx.rules.fire.clear_width_m.clause,
        "Without a drawn layout the lanes cannot be measured, so nothing here is passed.")


# --- Each tower -----------------------------------------------------------------------------


def _tower_cell(ctx: Context, ground: Ground, t: TowerGeometry, a: Assignment) -> Cell:
    reading = a[STILT_IN_RULE_HEIGHT]
    lane = ctx.rules.fire.clear_width_m.value
    required = (f">= {lane:g} m motorable on all sides; a "
                f"{ctx.rules.fire.turning_radius_m.value:g} m turn at every corner")
    if t.name not in {x.name for x in ctx.high_rise(reading)}:
        return Cell(Status.NOT_CHECKED, "not high-rise under this reading", required,
                    NON_HIGH_RISE_NOTE)
    turning = turning_for(ctx.rules, a[FIRE_TURNING_RADIUS])
    if turning is None:
        return unknown_reading(FIRE_TURNING_RADIUS, a[FIRE_TURNING_RADIUS])
    band = clear_band(t.footprint, lane)
    motorable = ctx.drawn.motorable
    turns = round_block(t.footprint, turning)
    stuck = [s for s in turns if ground.blocked_area(s, t.name) > NOISE_SQM]
    problems = []
    if ground.blocked_area(band, t.name) > NOISE_SQM:
        problems.append(f"something stands within {lane:g} m of it")
    if band.difference(motorable).area > NOISE_SQM:
        problems.append(f"part of the {lane:g} m round it is not a road or fire lane")
    if stuck:
        problems.append(f"{len(stuck)} of {len(turns)} corner turns blocked")
    measured = ("; ".join(problems) if problems else
                f"{lane:g} m clear on every side; all {len(turns)} corner turns fit")
    return Cell(verdict(not problems), measured, required,
                f"The turn at a corner needs {turning.reach_m:.2f} m of ground beside each face "
                f"under the {turning.reading} reading of the {turning.r_out:g} m radius.")


def tower_checks(ctx: Context, ground: Ground) -> list[Check]:
    out = []
    for t in ctx.high_rise_anywhere():
        out.append(check_from(
            run(ctx.rules, [STILT_IN_RULE_HEIGHT, FIRE_TURNING_RADIUS],
                lambda a, t=t: _tower_cell(ctx, ground, t, a)),
            family=Family.FIRE, rule=f"Fire access: {t.name}", subject=t.name,
            clause=ctx.rules.fire.clear_width_m.clause))
    return out


# --- The loop road, the way in, what stands on the lanes ------------------------------------


def loop_turns_check(ctx: Context, ground: Ground) -> Check:
    loop = union_of_all([r.shape for r in ctx.drawn.roads_of(RoadKind.LOOP,
                                                              RoadKind.PERIMETER_LANE)])
    radius = ctx.rules.fire.turning_radius_m.value

    def cell(a: Assignment) -> Cell:
        if not ctx.high_rise(a[STILT_IN_RULE_HEIGHT]):
            return Cell(Status.NOT_CHECKED, "no high-rise under this reading",
                        f"a {radius:g} m turn at every bend", NON_HIGH_RISE_NOTE)
        turning = turning_for(ctx.rules, a[FIRE_TURNING_RADIUS])
        if turning is None:
            return unknown_reading(FIRE_TURNING_RADIUS, a[FIRE_TURNING_RADIUS])
        bends = road_bends(loop, turning) if not loop.is_empty else []
        stuck = [s for s in bends if ground.blocked_area(s) > NOISE_SQM]
        measured = (f"{len(stuck)} of {len(bends)} bends blocked" if stuck
                    else f"all {len(bends)} bends turn at {radius:g} m")
        return Cell(verdict(not stuck), measured, f"a {radius:g} m turn at every bend")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT, FIRE_TURNING_RADIUS], cell),
                      family=Family.FIRE, rule="Fire access: turns along the loop road",
                      clause=ctx.rules.fire.turning_radius_m.clause)


def reach_check(ctx: Context) -> Check:
    lane = ctx.rules.fire.clear_width_m.value
    network = reached(ctx)

    def cell(a: Assignment) -> Cell:
        towers = ctx.high_rise(a[STILT_IN_RULE_HEIGHT])
        if not towers:
            return Cell(Status.NOT_CHECKED, "no high-rise under this reading",
                        "a continuous way in for a fire tender", NON_HIGH_RISE_NOTE)
        missing = [t.name for t in towers if network.is_empty or
                   clear_band(t.footprint, lane).intersection(network).area < REACH_MIN_SQM]
        measured = (f"cut off: {', '.join(missing)}" if missing
                    else "every block, by a lane or road from a gate")
        return Cell(verdict(not missing), measured, "a continuous way in for a fire tender")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.FIRE,
                      rule="Fire access: reached from the entrance",
                      clause=ctx.rules.fire.clear_width_m.clause)


def entrance_check(ctx: Context, ground: Ground) -> Check:
    fire = ctx.rules.fire
    required = (f">= {fire.entrance_width_m.value:g} m wide; {fire.entrance_clear_height_m.value:g}"
                " m clear under anything built over it")
    gates = ctx.drawn.gates
    if not gates:
        return plain(Family.FIRE, "Fire access: entrance", Status.FAIL, "no entrance drawn",
                     required, fire.entrance_width_m.clause,
                     "Roads are drawn but nothing connects them to the street.")
    widest = max(gates, key=lambda g: sides_of(g.shape)[0])
    width = sides_of(widest.shape)[0]
    built_over = ground.solid_area(ctx.drawn.gate_land)
    problems = []
    if width + TOL_M < fire.entrance_width_m.value:
        problems.append(f"{width:.2f} m wide")
    if built_over > NOISE_SQM:
        problems.append("something is built over it")
    return plain(Family.FIRE, "Fire access: entrance", verdict(not problems),
                 "; ".join(problems) if problems else
                 f"{width:.2f} m wide; nothing built over it", required,
                 fire.entrance_width_m.clause,
                 "The gate folding back against the compound wall is a detail drawing.")


def obstruction_check(ctx: Context) -> Check:
    d = ctx.drawn
    motorable = d.motorable
    kinds = {"tower": union_of_all([t.footprint for t in ctx.towers]), "club house": d.club,
             "amenity": union_of_all([a.shape for a in d.amenities]),
             "parking bay": union_of_all(list(d.bays)),
             "tot-lot": union_of_all(list(d.open_space)), "ramp": union_of_all(list(d.ramps))}
    hit = {k: g.intersection(motorable).area for k, g in kinds.items()
           if g.intersection(motorable).area > NOISE_SQM}
    return plain(
        Family.FIRE, "Fire access: nothing parked or built on it", verdict(not hit),
        ("on a road or fire lane: " + ", ".join(f"{k} {a:,.1f} m²" for k, a in hit.items()))
        if hit else "no tower, bay, facility, ramp or tot-lot on any road or fire lane",
        "kept free of obstructions; never used for parking",
        ctx.rules.fire.clear_width_m.clause)


def _known(sourced) -> bool:
    return sourced.value is not None and sourced.status is not Provenance.UNVERIFIED


def street_check(ctx: Context) -> Check:
    fire = ctx.rules.fire
    required = f"joins a street at least {fire.street_join_m.value:g} m wide at one end"
    joins = ctx.site.access.joins_12m_street
    if not _known(joins):
        return plain(Family.FIRE, "Fire access: the street joins a 12 m street",
                     Status.UNVERIFIED, "not known: a survey does not show where the road leads",
                     required, fire.street_join_m.clause, "The architect's to say.")
    return plain(Family.FIRE, "Fire access: the street joins a 12 m street",
                 verdict(bool(joins.value)),
                 f"{'yes' if joins.value else 'no'}, as the architect says ({joins.status.value})",
                 required, fire.street_join_m.clause)


def dead_end_check(ctx: Context) -> Check:
    fire = ctx.rules.fire
    limit = fire.dead_end_max_physical_m.value
    required = f"no dead-end road for a residential building above {limit:g} m"
    tallest = max((t.physical_height_m for t in ctx.high_rise_anywhere()), default=0.0)
    rule, clause = "Fire access: dead-end road", fire.dead_end_max_physical_m.clause
    if tallest <= limit + TOL_M:
        return plain(Family.DEAD_END, rule, Status.PASS,
                     f"tallest {tallest:g} m, within {limit:g} m", required, clause,
                     f"A dead end is allowed up to {limit:g} m.")
    dead = ctx.site.access.dead_end
    if not _known(dead):
        return plain(Family.DEAD_END, rule, Status.UNVERIFIED,
                     f"tallest {tallest:g} m; the road's end is not known", required, clause)
    return plain(Family.DEAD_END, rule, verdict(not dead.value),
                 f"tallest {tallest:g} m; the road "
                 + ("ends at the plot" if dead.value else "runs on"), required, clause)


def loading_check(ctx: Context) -> Check:
    return plain(
        Family.FIRE, "Fire access: 45 t hard surface", Status.UNVERIFIED,
        "a specification, not a drawing",
        f"roads and fire lanes carry a {ctx.rules.fire.load_t.value:g} t tender",
        ctx.rules.fire.load_t.clause,
        "The paving, and any cellar roof under a road or fire lane, must be designed for it.")


def fire_checks(ctx: Context) -> list[Check]:
    """Fire access for every high-rise under any reading of the stilt; none when there is none."""
    if not ctx.high_rise_anywhere():
        return [plain(Family.FIRE, "Fire access", Status.INFO, "no high-rise block",
                      "NBC 4.6 for high-rise", ctx.rules.fire.clear_width_m.clause)]
    out = [street_check(ctx), dead_end_check(ctx)]
    if not ctx.drawn.has_circulation:
        return [*out, _no_layout(ctx), loading_check(ctx)]
    ground = Ground(ctx)
    out += tower_checks(ctx, ground)
    out += [loop_turns_check(ctx, ground), reach_check(ctx), entrance_check(ctx, ground),
            obstruction_check(ctx), loading_check(ctx)]
    return out
