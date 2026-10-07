"""Fire access (NBC 2016 Part 3 4.6), measured from the drawing.

4.6 is for "high rise buildings and special buildings". G.O.168 rule 15(b)(iv) holds every
high-rise to it. Rule 15(a)(i) holds a block below the state's high-rise height to the Code's
requirements other than heights and setbacks, and so to 4.6 when the block is a special building:
when it stands over a cellar of more than 500 m² or of two levels or more (Part 4 1.2(b)(6), read
as law). Under the nbc_line reading it holds a block of NBC's own 15 m too (Part 4 2.38, measured
as Part 4 2.6 does, the stilt included).

Every block held needs 6 m of clear, motorable ground on all sides, room for the tender to turn
round each corner and each bend of the loop road, a lane from a gate to all of it, and nothing
parked or built in it. The bands and the swept turns are built here from the lane width and the
radii in the rules; the generator's fire lanes are only ground the candidate says is motorable.

What a drawing cannot show stays UNVERIFIED: where the street leads, whether the road ends at
the plot, and the 45 t loading, which is a paving specification. So does a block that fails only
because it might stand over a cellar drawn without its outline.

A block 4.6 does not hold under a reading has nothing asked of it there. What the rest of the
Code asks of a block below the high-rise height is not on a site plan: `low_block_check` says
so, as NOT_CHECKED, and judges nothing.
"""

from __future__ import annotations

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    FIRE_TURNING_RADIUS,
    NBC_FIRE_HEIGHT,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.contracts.validation import Check, Discrepancy, Family
from siteplan.validator.context import GATE_ON_BOUNDARY_M, Context, is_known
from siteplan.validator.ground import Ground
from siteplan.validator.measure import TOL_M, TowerGeometry
from siteplan.validator.readings import (
    NBC_LINE,
    STATE_LINE,
    Assignment,
    Cell,
    check_from,
    plain,
    run,
    unknown_reading,
    verdict,
)
from siteplan.validator.shapes import (
    EPS_M,
    NOISE_SQM,
    mitred,
    opening,
    polygons_of,
    union_of_all,
    width_along_edge,
)
from siteplan.validator.turning import junction_turns, road_bends, round_block, turning_for
from siteplan.validator.zones import bearings_near, compass_name, faces

# Rule 15(a)(i), read on page 20 of fixtures/rules/go168-2012.pdf (the 2012 text). Rule 15(b)(iv)
# brings NBC's fire protection requirements to a high-rise alone; a building below that height is
# held to the Code's requirements other than heights and setbacks, and the rule gives no figure
# for what those ask of a fire vehicle's access.
LOW_FIRE_RULE = ("G.O.168 rule 15(a)(i), p.20: \"The building requirements and standards other "
                 "than heights and setbacks specified in the National Building Code - 2005 shall "
                 "be complied with.\"")
LOW_FIRE_CLAUSE = ("G.O.168 rule 15(a)(i) (a building below the high-rise height: the National "
                   "Building Code's requirements and standards other than heights and setbacks)")
REACH_MIN_SQM = 1.0  # a lane that only touches a block's band at a point does not reach it
GATE_SLACK_M = 0.05  # a gate may measure this much under the width it declares
GATE_TOUCH_M = 0.5  # a lane this close to the entrance's ground starts from it
NOT_ASKED = "nothing: neither a high-rise nor a special building under this reading"
MAYBE_SPECIAL_NOTE = ("A cellar is drawn without its outline, so which blocks stand over it, and "
                      "so which are special buildings held to 4.6, is not known: what fails only "
                      "on that is UNVERIFIED.")


def clear_band(footprint: Polygon, lane_m: float) -> BaseGeometry:
    """The ground that must stay clear round a block: the lane's width on every side, corners
    square."""
    return mitred(footprint, lane_m).difference(footprint)


def reached(ctx: Context) -> BaseGeometry:
    """The lanes (ground at least a lane wide) that connect to a gate."""
    lane = ctx.rules.fire.clear_width_m.value
    start = ctx.entrance_land.buffer(GATE_TOUCH_M)
    if start.is_empty:
        return Polygon()
    passable = opening(ctx.drawn.motorable, lane)
    return union_of_all([p for p in getattr(passable, "geoms", [passable])
                         if not p.is_empty and p.intersects(start)])


def _below_note(ctx: Context) -> str:
    """Said where a fire check meets a block that 4.6 does not hold under a reading."""
    fire = ctx.rules.fire
    return (f"Below {ctx.rules.height.high_rise_from_m.value:g} m a block is held to NBC 4.6 only "
            f"as a special building, over a cellar of more than "
            f"{fire.special_basement_sqm.value:g} m² or of {fire.special_basement_levels.value} "
            f"levels or more, or under the nbc_line reading from NBC's own "
            f"{fire.nbc_high_rise_m.value:g} m (rule 15(a)(i) keeps the Code's requirements "
            "other than heights and setbacks).")


def held_by(ctx: Context, t: TowerGeometry, stilt: str, line: str) -> bool | None:
    """Whether NBC 4.6 holds a block under a reading of the stilt and of NBC's height line: by
    law as a high-rise or a special building, and under the nbc_line reading from NBC's own
    15 m, the stilt included. None when only a cellar drawn without its outline could make it a
    special building."""
    if t.name in {x.name for x in ctx.fire_held(stilt)}:
        return True
    if line == NBC_LINE and t.physical_height_m >= ctx.rules.fire.nbc_high_rise_m.value - TOL_M:
        return True
    return None if ctx.special.get(t.name) is None else False


def fire_subjects(ctx: Context) -> list[TowerGeometry]:
    """Every block NBC 4.6 holds, or may hold, under some reading."""
    lines = ctx.rules.readings(NBC_FIRE_HEIGHT)
    return [t for t in ctx.towers
            if any(held_by(ctx, t, stilt, line) is not False
                   for stilt in ctx.stilt_readings for line in lines)]


def _why_held(ctx: Context, t: TowerGeometry, stilt: str, line: str) -> str:
    """Why 4.6 holds a block that is not a high-rise under this reading of the stilt."""
    if t.name in {x.name for x in ctx.high_rise(stilt)}:
        return ""
    fire, d = ctx.rules.fire, ctx.drawn
    special = ctx.special.get(t.name)
    if special:
        under = max((p.area for p in polygons_of(d.cellar_outline)
                     if p.intersection(t.footprint).area > NOISE_SQM), default=0.0)
        return (f"{t.name} stands over a cellar of {d.cellar_levels} level"
                f"{'s' if d.cellar_levels > 1 else ''}, {under:,.0f} m² a level: a special "
                "building (NBC Part 4 1.2(b)(6)), held to 4.6 whatever its height.")
    if line == NBC_LINE and t.physical_height_m >= fire.nbc_high_rise_m.value - TOL_M:
        return (f"{t.name} is {t.physical_height_m:g} m to its terrace, the stilt included: at "
                f"or above NBC's own {fire.nbc_high_rise_m.value:g} m line (the nbc_line "
                "reading).")
    return MAYBE_SPECIAL_NOTE if special is None else ""


def _held_clause(ctx: Context, t: TowerGeometry) -> str:
    """The clauses that hold a block to 4.6: rule 15(b)(iv)'s for a high-rise; for a block that
    is below the high-rise height under some reading, the special building's and NBC's line
    too, where they could hold it."""
    fire = ctx.rules.fire
    parts = [fire.clear_width_m.clause]
    if any(t.name not in {x.name for x in ctx.high_rise(r)} for r in ctx.stilt_readings):
        if ctx.special.get(t.name) is not False:
            parts.append(fire.special_basement_sqm.clause)
        if _on_nbc_line(ctx, t):
            parts.append(fire.nbc_high_rise_m.clause)
    return "; ".join(parts)


def _on_nbc_line(ctx: Context, t: TowerGeometry) -> bool:
    """Whether a block reaches NBC's own high-rise line and the rules evaluate that reading."""
    return (NBC_LINE in ctx.rules.readings(NBC_FIRE_HEIGHT)
            and t.physical_height_m >= ctx.rules.fire.nbc_high_rise_m.value - TOL_M)


def _readings_known(ctx: Context, a: Assignment) -> Cell | None:
    """A cell for a reading of the stilt or of NBC's line this validator cannot evaluate."""
    if a[STILT_IN_RULE_HEIGHT] not in ctx.classes:
        return unknown_reading(STILT_IN_RULE_HEIGHT, a[STILT_IN_RULE_HEIGHT])
    if a[NBC_FIRE_HEIGHT] not in (STATE_LINE, NBC_LINE):
        return unknown_reading(NBC_FIRE_HEIGHT, a[NBC_FIRE_HEIGHT])
    return None


def _no_layout(ctx: Context) -> Check:
    return plain(
        Family.FIRE, "Fire access: around each block", Status.UNVERIFIED,
        "no road and lane layout drawn",
        f">= {ctx.rules.fire.clear_width_m.value:g} m clear and motorable on all sides",
        ctx.rules.fire.clear_width_m.clause,
        "Without a drawn layout the lanes cannot be measured, so nothing here is passed.")


# --- Each tower -----------------------------------------------------------------------------


def _tower_cell(ctx: Context, ground: Ground, t: TowerGeometry, a: Assignment) -> Cell:
    unknown = _readings_known(ctx, a)
    if unknown is not None:
        return unknown
    lane = ctx.rules.fire.clear_width_m.value
    required = (f">= {lane:g} m motorable on all sides; a "
                f"{ctx.rules.fire.turning_radius_m.value:g} m turn at every corner")
    held = held_by(ctx, t, a[STILT_IN_RULE_HEIGHT], a[NBC_FIRE_HEIGHT])
    if held is False:
        return Cell(Status.PASS, "not held to NBC 4.6 under this reading", NOT_ASKED,
                    _below_note(ctx))
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
    note = " ".join(part for part in (
        f"The turn at a corner needs {turning.reach_m:.2f} m of ground beside each face under "
        f"the {turning.reading} reading of the {turning.r_out:g} m radius.",
        _why_held(ctx, t, a[STILT_IN_RULE_HEIGHT], a[NBC_FIRE_HEIGHT])) if part)
    if problems and held is None:
        return Cell(Status.UNVERIFIED, measured, required, note)
    return Cell(verdict(not problems), measured, required, note)


def tower_checks(ctx: Context, ground: Ground) -> list[Check]:
    out = []
    for t in fire_subjects(ctx):
        out.append(check_from(
            run(ctx.rules, [STILT_IN_RULE_HEIGHT, NBC_FIRE_HEIGHT, FIRE_TURNING_RADIUS],
                lambda a, t=t: _tower_cell(ctx, ground, t, a)),
            family=Family.FIRE, rule=f"Fire access: {t.name}", subject=t.name,
            clause=_held_clause(ctx, t)))
    return out


# --- The loop road, the way in, what stands on the lanes ------------------------------------


def loop_turns_check(ctx: Context, ground: Ground) -> Check:
    loop = union_of_all([r.shape for r in ctx.drawn.roads_of(RoadKind.LOOP,
                                                              RoadKind.PERIMETER_LANE)])
    radius = ctx.rules.fire.turning_radius_m.value
    subjects = fire_subjects(ctx)

    def cell(a: Assignment) -> Cell:
        unknown = _readings_known(ctx, a)
        if unknown is not None:
            return unknown
        held = [h for h in (held_by(ctx, t, a[STILT_IN_RULE_HEIGHT], a[NBC_FIRE_HEIGHT])
                            for t in subjects) if h is not False]
        if not held:
            return Cell(Status.PASS, "no block held to NBC 4.6 under this reading", NOT_ASKED,
                        _below_note(ctx))
        turning = turning_for(ctx.rules, a[FIRE_TURNING_RADIUS])
        if turning is None:
            return unknown_reading(FIRE_TURNING_RADIUS, a[FIRE_TURNING_RADIUS])
        bends = road_bends(loop, turning) if not loop.is_empty else []
        stuck = [s for s in bends if ground.blocked_area(s) > NOISE_SQM]
        measured = (f"{len(stuck)} of {len(bends)} bends blocked" if stuck
                    else f"all {len(bends)} bends turn at {radius:g} m")
        if stuck and True not in held:
            return Cell(Status.UNVERIFIED, measured, f"a {radius:g} m turn at every bend",
                        MAYBE_SPECIAL_NOTE)
        return Cell(verdict(not stuck), measured, f"a {radius:g} m turn at every bend")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT, NBC_FIRE_HEIGHT, FIRE_TURNING_RADIUS],
                          cell),
                      family=Family.FIRE, rule="Fire access: turns along the loop road",
                      clause=ctx.rules.fire.turning_radius_m.clause)


JUNCTION_ROADS = (RoadKind.LOOP, RoadKind.PERIMETER_LANE, RoadKind.INTERNAL, RoadKind.APPROACH,
                  RoadKind.CUL_DE_SAC)  # the roads a tender drives; a pathway or driveway is not


def junction_turns_check(ctx: Context, ground: Ground) -> Check:
    """Where the approach, a street or a link joins the loop road, the tender turns too (C4-15):
    the corners every junction makes are swept as the loop road's bends are, under each reading
    of the 9 m, and nothing may stand in them."""
    loop = union_of_all([r.shape for r in ctx.drawn.roads_of(RoadKind.LOOP,
                                                              RoadKind.PERIMETER_LANE)])
    network = union_of_all([r.shape for r in ctx.drawn.roads_of(*JUNCTION_ROADS)])
    radius = ctx.rules.fire.turning_radius_m.value
    subjects = fire_subjects(ctx)

    def cell(a: Assignment) -> Cell:
        unknown = _readings_known(ctx, a)
        if unknown is not None:
            return unknown
        held = [h for h in (held_by(ctx, t, a[STILT_IN_RULE_HEIGHT], a[NBC_FIRE_HEIGHT])
                            for t in subjects) if h is not False]
        if not held:
            return Cell(Status.PASS, "no block held to NBC 4.6 under this reading", NOT_ASKED,
                        _below_note(ctx))
        turning = turning_for(ctx.rules, a[FIRE_TURNING_RADIUS])
        if turning is None:
            return unknown_reading(FIRE_TURNING_RADIUS, a[FIRE_TURNING_RADIUS])
        turns = junction_turns(network, loop, ctx.net.boundary, turning, EPS_M,
                               GATE_TOUCH_M) if not network.is_empty else []
        stuck = [s for s in turns if ground.blocked_area(s) > NOISE_SQM]
        if stuck:
            measured = (f"{len(stuck)} of {len(turns)} junction turns blocked "
                        f"({ground.blocked_by(stuck[0])})")
        else:
            measured = f"all {len(turns)} junction turns turn at {radius:g} m"
        required = f"a {radius:g} m turn at every junction"
        if stuck and True not in held:
            return Cell(Status.UNVERIFIED, measured, required, MAYBE_SPECIAL_NOTE)
        return Cell(verdict(not stuck), measured, required)

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT, NBC_FIRE_HEIGHT, FIRE_TURNING_RADIUS],
                          cell),
                      family=Family.FIRE, rule="Fire access: turns at the road junctions",
                      clause=ctx.rules.fire.turning_radius_m.clause)


def reach_check(ctx: Context) -> Check:
    lane = ctx.rules.fire.clear_width_m.value
    network = reached(ctx)
    subjects = fire_subjects(ctx)

    def cell(a: Assignment) -> Cell:
        unknown = _readings_known(ctx, a)
        if unknown is not None:
            return unknown
        held = [(t, h) for t in subjects
                if (h := held_by(ctx, t, a[STILT_IN_RULE_HEIGHT], a[NBC_FIRE_HEIGHT]))
                is not False]
        if not held:
            return Cell(Status.PASS, "no block held to NBC 4.6 under this reading", NOT_ASKED,
                        _below_note(ctx))
        missing = [(t.name, h) for t, h in held if network.is_empty or
                   clear_band(t.footprint, lane).intersection(network).area < REACH_MIN_SQM]
        measured = (f"cut off: {', '.join(name for name, _ in missing)}" if missing
                    else "every block, by a lane or road from a gate")
        if missing and all(h is None for _, h in missing):
            return Cell(Status.UNVERIFIED, measured, "a continuous way in for a fire tender",
                        MAYBE_SPECIAL_NOTE)
        return Cell(verdict(not missing), measured, "a continuous way in for a fire tender")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT, NBC_FIRE_HEIGHT], cell),
                      family=Family.FIRE,
                      rule="Fire access: reached from the entrance",
                      clause=ctx.rules.fire.clear_width_m.clause)


def _street_sides(ctx: Context) -> tuple[list[str], list[str]]:
    """The sides the street runs on, as far as the site model knows: the access road's side (the
    architect's) and the sides of the other roads the survey measured. With no access side given
    every measured road counts as the street; with none known, empty."""
    side = ctx.site.access.side
    measured = sorted({str(r.side.value if hasattr(r.side, "value") else r.side)
                       for r in ctx.site.roads if r.side is not None})
    if is_known(side):
        declared = str(side.value)
        return [declared], [m for m in measured if m != declared]
    return measured, []


def _gate_problems(ctx: Context) -> tuple[list[str], list[str]]:
    """What is wrong with each gate, and what only makes it doubtful. Every gate is held to it:
    a gate that fails is not a way in, whatever else is drawn."""
    fire = ctx.rules.fire
    least, most = fire.entrance_width_m.value, ctx.rules.circulation.approach_m.value[1]
    street, others = _street_sides(ctx)
    problems, doubts = [], []
    for n, gate in enumerate(ctx.drawn.gates, 1):
        label = f"gate {n}" if len(ctx.drawn.gates) > 1 else "the gate"
        if gate.shape.distance(ctx.net.boundary) > GATE_ON_BOUNDARY_M:
            problems.append(f"{label} is not on the plot's boundary")
            continue
        width = width_along_edge(gate.shape, ctx.net, GATE_ON_BOUNDARY_M)
        if width + TOL_M < least:
            problems.append(f"{label} is {width:.2f} m wide")
        elif width > most + TOL_M:
            doubts.append(f"{label} is {width:.1f} m wide, more than the {most:g} m of the widest "
                          "main approach road rule 8(m) allows")
        facing = bearings_near(ctx.net, gate.shape, GATE_ON_BOUNDARY_M)
        if not (street and facing) or any(faces(f, side) for f in facing for side in street):
            continue
        name = compass_name(facing[0])
        if any(faces(f, side) for f in facing for side in others):
            doubts.append(f"{label} is on the {name} side, on a road the survey measures that is "
                          "not the access road: whether it may be an entrance is not settled")
        else:
            problems.append(f"{label} is on the {name} side; the road runs on "
                            + ", ".join(sorted(street)))
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
    widths = [width_along_edge(g.shape, ctx.net, GATE_ON_BOUNDARY_M) for g in ctx.entrances]
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
        measured = width_along_edge(gate.shape, ctx.net, GATE_ON_BOUNDARY_M)
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
    tallest = max((t.physical_height_m for t in fire_subjects(ctx)), default=0.0)
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


def _held_text(ctx: Context, t: TowerGeometry) -> str:
    """What holds a block below the high-rise height to NBC 4.6, in a few words."""
    special = ctx.special.get(t.name)
    if special:
        return "a special building over the cellar, held to 4.6"
    if special is None:
        return "over the cellar or not, which is not drawn"
    if _on_nbc_line(ctx, t):
        return f"{t.physical_height_m:g} m, held to 4.6 under the nbc_line reading only"
    return "not held to 4.6"


def low_block_check(ctx: Context) -> Check | None:
    """What a block below the high-rise height is held to, said for each block that is below it
    under any reading of the stilt. Rule 15(a)(i) keeps the National Building Code's requirements
    other than heights and setbacks: 4.6's fire access where the block is a special building, or
    under one reading from NBC's 15 m, judged in that block's own fire access check, and 4.3.2.2's
    30 m pathway, judged with the internal roads. The rest of the Code (exits, the fire protection
    inside a block) is not on a site plan: NOT_CHECKED, listed beside the verdict, never PASS."""
    below = ctx.low_rise_anywhere()
    if not below:
        return None
    fire, threshold = ctx.rules.fire, ctx.rules.height.high_rise_from_m.value
    names = []
    for t in below:
        readings = [r for r in ctx.stilt_readings
                    if t.name in {x.name for x in ctx.low_rise(r)}]
        label = (t.name if len(readings) == len(ctx.stilt_readings)
                 else f"{t.name} (only if the stilt is {', '.join(readings)})")
        names.append(f"{label}: {_held_text(ctx, t)}")
    return plain(
        Family.FIRE, f"Fire access below {threshold:g} m (rule 15(a)(i))", Status.NOT_CHECKED,
        "; ".join(names),
        "the National Building Code's requirements and standards other than heights and "
        "setbacks", LOW_FIRE_CLAUSE,
        f"{LOW_FIRE_RULE} NBC 4.6's fire access is for high-rise and special buildings: a block "
        f"over a cellar of more than {fire.special_basement_sqm.value:g} m² or of "
        f"{fire.special_basement_levels.value} levels or more is one (Part 4 1.2(b)(6)), and so, "
        f"under the nbc_line reading, is a block of NBC's own {fire.nbc_high_rise_m.value:g} m; "
        "each is judged in its own fire access check. The 30 m pathway (Part 3 4.3.2.2) is "
        "judged with the internal roads. The rest of the Code, exits and the fire protection "
        "inside a block, is not shown on a site plan and is not judged here.")


def _as_held(ctx: Context, subjects: list[TowerGeometry], made: Check) -> Check:
    """A check of the whole site that 4.6 asks only where it holds a block: under a reading of the
    stilt and of NBC's line that holds none, nothing is asked (PASS), so a result that holds only
    where some reading holds a block is UNVERIFIED, never FAIL. Under a reading this validator
    cannot evaluate, the check stands as made."""
    f = made.finding

    def cell(a: Assignment) -> Cell:
        stilt, line = a[STILT_IN_RULE_HEIGHT], a[NBC_FIRE_HEIGHT]
        known = stilt in ctx.classes and line in (STATE_LINE, NBC_LINE)
        if known and all(held_by(ctx, t, stilt, line) is False for t in subjects):
            return Cell(Status.PASS, "no block held to NBC 4.6 under this reading", NOT_ASKED,
                        _below_note(ctx))
        return Cell(f.status, f.measured, f.required, f.note)

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT, NBC_FIRE_HEIGHT], cell),
                      family=made.family, rule=f.rule, clause=f.clause, subject=made.subject)


def fire_checks(ctx: Context, ground: Ground) -> list[Check]:
    """Fire access for every block NBC 4.6 holds or may hold under any reading, and what a block
    below the high-rise height is held to."""
    low = low_block_check(ctx)
    below = [low] if low is not None else []
    subjects = fire_subjects(ctx)
    if not subjects:
        return [plain(Family.FIRE, "Fire access", Status.INFO,
                      "no high-rise and no special building",
                      "NBC 4.6 for high-rise and special buildings",
                      ctx.rules.fire.clear_width_m.clause), *below]

    def held(made: Check) -> Check:
        return _as_held(ctx, subjects, made)

    out = [held(street_check(ctx)), held(dead_end_check(ctx))]
    if not ctx.drawn.has_circulation:
        return [*out, held(_no_layout(ctx)), held(loading_check(ctx)), *below]
    out += tower_checks(ctx, ground)
    out += [loop_turns_check(ctx, ground), junction_turns_check(ctx, ground), reach_check(ctx),
            held(entrance_check(ctx, ground)),
            held(obstruction_check(ctx)), held(loading_check(ctx))]
    return [*out, *below]
