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
from shapely.ops import unary_union

from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import FIRE_TURNING_RADIUS, STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import Check, Discrepancy, Family
from siteplan.validator.context import GATE_ON_BOUNDARY_M, Context, is_known
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
from siteplan.validator.shapes import (
    NOISE_SQM,
    mitred,
    opening,
    union_of_all,
    width_along_edge,
)
from siteplan.validator.turning import road_bends, round_block, turning_for
from siteplan.validator.zones import (
    COMPASS_DEG,
    FRONT_SECTOR_DEG,
    angle_between,
    bearings_near,
    compass_name,
)

NON_HIGH_RISE_NOTE = ("Below the high-rise threshold the fire rules of rule 15(a)(i) apply and "
                      "are not modelled yet.")
REACH_MIN_SQM = 1.0  # a lane that only touches a block's band at a point does not reach it
GATE_SLACK_M = 0.05  # a gate may measure this much under the width it declares


def clear_band(footprint: Polygon, lane_m: float) -> BaseGeometry:
    """The ground that must stay clear round a block: the lane's width on every side, corners
    square."""
    return mitred(footprint, lane_m).difference(footprint)


def reached(ctx: Context) -> BaseGeometry:
    """The lanes (ground at least a lane wide) that connect to a gate."""
    lane = ctx.rules.fire.clear_width_m.value
    start = ctx.entrance_land.buffer(0.5)
    if start.is_empty:
        return Polygon()
    passable = opening(ctx.drawn.motorable, lane)
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
    if reading not in ctx.classes:
        return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
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
        problems.append(f"something stands within {lane:g} m of it ("
                        f"{ground.blocked_by(band, t.name)})")
    if band.difference(motorable).area > NOISE_SQM:
        problems.append(f"part of the {lane:g} m round it is not a road or fire lane")
    if stuck:
        problems.append(f"{len(stuck)} of {len(turns)} corner turns blocked ("
                        f"{ground.blocked_by(unary_union(stuck), t.name)})")
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
        if a[STILT_IN_RULE_HEIGHT] not in ctx.classes:
            return unknown_reading(STILT_IN_RULE_HEIGHT, a[STILT_IN_RULE_HEIGHT])
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
        if a[STILT_IN_RULE_HEIGHT] not in ctx.classes:
            return unknown_reading(STILT_IN_RULE_HEIGHT, a[STILT_IN_RULE_HEIGHT])
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


def _road_bearings(ctx: Context) -> list[float]:
    """The bearings of the sides the street runs on, as far as the site model knows: the access
    side the architect gave, else the sides of the roads the survey measured. Empty when none
    is known."""
    side = ctx.site.access.side
    if is_known(side):
        return [float(COMPASS_DEG[side.value])]
    return [float(COMPASS_DEG[r.side]) for r in ctx.site.roads if r.side is not None]


def _gate_problems(ctx: Context) -> tuple[list[str], list[str]]:
    """What is wrong with each gate, and what only makes it doubtful. Every gate is held to it:
    a gate that fails is not a way in, whatever else is drawn."""
    fire = ctx.rules.fire
    least, most = fire.entrance_width_m.value, ctx.rules.circulation.approach_m.value[1]
    bearings = _road_bearings(ctx)
    problems, doubts = [], []
    for n, gate in enumerate(ctx.drawn.gates, 1):
        label = f"gate {n}" if len(ctx.drawn.gates) > 1 else "the gate"
        if gate.shape.distance(ctx.net.boundary) > GATE_ON_BOUNDARY_M:
            problems.append(f"{label} is not on the plot's boundary")
            continue
        width = width_along_edge(gate.shape, ctx.net)
        if width + TOL_M < least:
            problems.append(f"{label} is {width:.2f} m wide")
        elif width > most + TOL_M:
            doubts.append(f"{label} is {width:.1f} m wide, more than the {most:g} m of the widest "
                          "main approach road rule 8(m) allows")
        facing = bearings_near(ctx.net, gate.shape, GATE_ON_BOUNDARY_M)
        if bearings and facing and not any(
                angle_between(f, b) <= FRONT_SECTOR_DEG + 1e-6 for f in facing for b in bearings):
            problems.append(f"{label} is on the {compass_name(facing[0])} side; the road runs on "
                            + ", ".join(sorted({compass_name(b) for b in bearings})))
    return problems, doubts


def entrance_check(ctx: Context, ground: Ground) -> Check:
    fire = ctx.rules.fire
    required = (f">= {fire.entrance_width_m.value:g} m wide, in the plot's boundary on the side "
                f"the road runs; {fire.entrance_clear_height_m.value:g} m clear under anything "
                "built over it")
    if not ctx.drawn.gates:
        return plain(Family.FIRE, "Fire access: entrance", Status.FAIL, "no entrance drawn",
                     required, fire.entrance_width_m.clause,
                     "Roads are drawn but nothing connects them to the street.")
    problems, doubts = _gate_problems(ctx)
    if ground.solid_area(ctx.entrance_land) > NOISE_SQM:
        problems.append("something is built over it")
    widths = [width_along_edge(g.shape, ctx.net) for g in ctx.entrances]
    status = Status.FAIL if problems else Status.UNVERIFIED if doubts else Status.PASS
    shown = "; ".join(problems + doubts) if problems or doubts else (
        f"{max(widths):.2f} m wide; nothing built over it")
    return plain(Family.FIRE, "Fire access: entrance", status, shown, required,
                 fire.entrance_width_m.clause,
                 "The gate folding back against the compound wall is a detail drawing.")


def gate_discrepancies(ctx: Context) -> list[Discrepancy]:
    """A gate that measures narrower than the width it declares flatters the layout."""
    out = []
    for i, gate in enumerate(ctx.drawn.gates, 1):
        measured = width_along_edge(gate.shape, ctx.net)
        if measured + GATE_SLACK_M < gate.declared_width_m:
            out.append(Discrepancy(
                item=f"gate width {i}", source="generator", theirs=f"{gate.declared_width_m:g} m",
                ours=f"{measured:.2f} m", blocks_pass=True))
    return out


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


def street_check(ctx: Context) -> Check:
    fire = ctx.rules.fire
    required = f"joins a street at least {fire.street_join_m.value:g} m wide at one end"
    joins = ctx.site.access.joins_12m_street
    if not is_known(joins):
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
    if not is_known(dead):
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


def fire_checks(ctx: Context, ground: Ground) -> list[Check]:
    """Fire access for every high-rise under any reading of the stilt; none when there is none."""
    if not ctx.high_rise_anywhere():
        return [plain(Family.FIRE, "Fire access", Status.INFO, "no high-rise block",
                      "NBC 4.6 for high-rise", ctx.rules.fire.clear_width_m.clause)]
    out = [street_check(ctx), dead_end_check(ctx)]
    if not ctx.drawn.has_circulation:
        return [*out, _no_layout(ctx), loading_check(ctx)]
    out += tower_checks(ctx, ground)
    out += [loop_turns_check(ctx, ground), reach_check(ctx), entrance_check(ctx, ground),
            obstruction_check(ctx), loading_check(ctx)]
    return out
