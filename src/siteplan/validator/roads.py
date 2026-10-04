"""Rule 8(m) and 8(l): the internal roads of a group development scheme, and the setback.

Roads are measured from their drawn shapes, never from the width they declare: a road drawn 8.9 m
wide is 8.9 m wide whatever its label says, and a bay, a facility or a block standing on it takes
that ground from it. A driveway (rule 13(c)(viii), 4.5 m) is never counted as an internal road.
Every road, gate and fire lane that runs inside the mandatory setback is evaluated under both
readings of whether circulation may use it.
"""

from __future__ import annotations

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry

from siteplan import rules as law
from siteplan.contracts.candidate import RoadKind
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    APPROACH_WIDTH,
    CIRCULATION_IN_SETBACK,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.contracts.validation import Check, Discrepancy, Family
from siteplan.validator.context import Context
from siteplan.validator.drawn import DrawnRoad
from siteplan.validator.ground import Ground
from siteplan.validator.measure import TOL_M
from siteplan.validator.network import TOUCH_M, dead_end_check, entrance_connection_check
from siteplan.validator.readings import (
    ALLOWED,
    AUTHORITY_CHOICE,
    MINIMUM_APPROACH,
    NOT_ALLOWED,
    Assignment,
    Cell,
    basis_note,
    check_from,
    plain,
    run,
    unknown_reading,
    verdict,
)
from siteplan.validator.shapes import (
    NOISE_SQM,
    bent,
    healed,
    inscribed_circle,
    opening,
    polygons_of,
    sides_of,
    union_of_all,
    width_in,
    width_of,
)
from siteplan.validator.zones import deepest_setback_m, setback_zone

DECLARED_SLACK_M = 0.05  # a road may measure this much under the width it declares
ROAD_KINDS = (RoadKind.APPROACH, RoadKind.LOOP, RoadKind.INTERNAL, RoadKind.CUL_DE_SAC)
RULE_8M_KINDS = (RoadKind.APPROACH, RoadKind.LOOP, RoadKind.INTERNAL)
BEND_NOTE = ("A road round a bend is longer along its own middle than the box round it, which is "
             "all this validator measures: its length is for a person to check.")


def _clause(ctx: Context) -> str:
    return ctx.rules.circulation.internal_road_m.clause


def _usable(road: DrawnRoad, ground: Ground) -> BaseGeometry:
    """The road's drawn ground less anything built, parked or laid out on it."""
    return road.shape.difference(ground.solid_land)


def _ground_of(ctx: Context, ground: Ground, *kinds: RoadKind) -> BaseGeometry:
    return union_of_all([_usable(r, ground) for r in ctx.drawn.roads_of(*kinds)])


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# --- Main approach, loop and internal roads --------------------------------------------------


def _approach_checks(ctx: Context, ground: Ground, network: BaseGeometry) -> list[Check]:
    low, high = ctx.rules.circulation.approach_m.value
    roads = ctx.drawn.roads_of(RoadKind.APPROACH)
    out = []
    for road in roads:
        usable = _usable(road, ground)
        measured = width_in(network, usable, max(high, road.declared_width_m) + 1.0)
        width = min(measured, road.declared_width_m)

        def cell(a: Assignment, width=width, measured=measured, road=road) -> Cell:
            reading = a[APPROACH_WIDTH]
            shown = (f"{measured:.2f} m wide, from the entrance to the loop road"
                     + ("" if abs(measured - road.declared_width_m) <= DECLARED_SLACK_M
                        else f" (declared {road.declared_width_m:g} m)"))
            required = f">= {low:g} m (the order gives {low:g} to {high:g} m)"
            if width + TOL_M < low:
                return Cell(Status.FAIL, shown, required)
            if reading == MINIMUM_APPROACH:
                return Cell(Status.PASS, shown, required,
                            f"Drawn at the least the order allows; it gives no test for when a "
                            f"main approach road must be wider, so the authority may ask up to "
                            f"{high:g} m.")
            if reading == AUTHORITY_CHOICE:
                status = Status.PASS if width >= high - TOL_M else Status.UNVERIFIED
                return Cell(status, shown, required, f"The authority may ask for up to "
                            f"{high:g} m; only that width settles it.")
            return unknown_reading(APPROACH_WIDTH, reading)

        suffix = f" ({road.id})" if len(roads) > 1 else ""
        out.append(check_from(
            run(ctx.rules, [APPROACH_WIDTH], cell), family=Family.ROADS,
            rule=f"Internal roads: main approach{suffix}", subject=road.id,
            clause=ctx.rules.circulation.approach_m.clause))
    return out


def _network_check(ctx: Context, ground: Ground, network: BaseGeometry) -> Check | None:
    """Every loop, internal and approach road held to 9 m, each against its own ground, so a
    pinch in one road is not lost among the area of the others."""
    nine = ctx.rules.circulation.internal_road_m.value
    loops, inner = ctx.drawn.roads_of(RoadKind.LOOP), ctx.drawn.roads_of(RoadKind.INTERNAL)
    if not (loops or inner):
        return None
    wide = opening(network, nine)
    thin = {r.id: width_in(network, _usable(r, ground), nine)
            for r in ctx.drawn.roads_of(*RULE_8M_KINDS)
            if _usable(r, ground).difference(wide).area > NOISE_SQM}
    declared = [r for r in ctx.drawn.roads_of(*RULE_8M_KINDS)
                if r.declared_width_m + TOL_M < nine]
    what = (f"a loop road and {_plural(len(inner), 'internal road')}" if loops
            else _plural(len(inner), "internal road"))
    problems = []
    if thin:
        problems.append(f"narrower than {nine:g} m in places: " + ", ".join(
            f"{i} ({w:.2f} m)" for i, w in thin.items()))
    if declared:
        problems.append("declared narrower: " + ", ".join(r.id for r in declared))
    return plain(
        Family.ROADS, "Internal roads: loop and other roads", verdict(not problems),
        f"{what}, " + ("; ".join(problems) if problems else f"all at least {nine:g} m"),
        f">= {nine:g} m", _clause(ctx),
        "A driveway (rule 13(c)(viii), 4.5 m) is not counted as an internal road.")


def _perimeter_checks(ctx: Context, ground: Ground) -> list[Check]:
    """A perimeter lane inside the setback (a test assumption) is held to the fire lane, and is
    never taken to satisfy rule 8(m)'s 9 m loop road."""
    ring = ctx.drawn.roads_of(RoadKind.PERIMETER_LANE)
    if not ring:
        return []
    lane = ctx.rules.fire.clear_width_m.value
    usable = union_of_all([_usable(r, ground) for r in ring])
    width = width_of(usable, lane)
    thin = width + TOL_M < lane
    out = [plain(
        Family.ROADS, "Fire lane: perimeter lane inside the setback", verdict(not thin),
        f"narrower than {lane:g} m in places ({width:.2f} m)" if thin else
        f"{width:.2f} m inside the setback band, at least {lane:g} m everywhere",
        f">= {lane:g} m motorable", ctx.rules.fire.clear_width_m.clause,
        "ASSUMED_FOR_TEST: the profile lets circulation run inside the setback. As a fire lane "
        "only; it is not counted as a rule 8(m) road.")]
    if not ctx.drawn.roads_of(RoadKind.LOOP):
        out.append(plain(
            Family.ROADS, "Internal roads: 9 m loop road (rule 8(m))", Status.UNVERIFIED,
            "no 9 m loop road drawn; the perimeter lane inside the setback is not counted as "
            "one", f">= {ctx.rules.circulation.internal_road_m.value:g} m for looped roads",
            _clause(ctx), "Whether a perimeter driveway narrower than 9 m inside the setback may "
            "serve as the group development's loop is not settled; the architect or a sanctioned "
            "plan says."))
    return out


# --- Dead ends and cul-de-sacs ---------------------------------------------------------------


def _head(body: Polygon | None, joint: BaseGeometry, radius_m: float,
          width_m: float) -> tuple[float, Point | None]:
    """The largest circle in the free end of a cul-de-sac (the end furthest from where it joins
    the road) and where it is: a head at the wrong end turns nothing."""
    if body is None:
        return 0.0, None
    if joint.is_empty:
        return inscribed_circle(body)
    anchor = joint.centroid
    far = max((Point(c) for c in body.exterior.coords), key=anchor.distance)
    return inscribed_circle(body.intersection(far.buffer(2 * radius_m + width_m)))


def _stem(body: Polygon | None, head: float, centre: Point | None, width_m: float
          ) -> Polygon | None:
    """The cul-de-sac without its turning head: the head's circle is taken out, and any sliver or
    corner of a head that is not round is opened away."""
    if body is None or centre is None:
        return body
    left = body.difference(centre.buffer(head + 0.1))
    pieces = polygons_of(opening(left, width_m / 2) if not left.is_empty else left)
    return max(pieces, key=lambda p: p.area) if pieces else None


def _cul_de_sac_checks(ctx: Context, ground: Ground) -> list[Check]:
    circ = ctx.rules.circulation
    low, high = circ.cul_de_sac_length_m.value
    wide, radius = circ.cul_de_sac_width_m.value, circ.cul_de_sac_head_radius_m.value
    network = _ground_of(ctx, ground, *RULE_8M_KINDS)
    out = []
    for road in ctx.drawn.roads_of(RoadKind.CUL_DE_SAC):
        usable = _usable(road, ground)
        parts = polygons_of(usable)
        body = max(parts, key=lambda p: p.area) if parts else None
        length = sides_of(body)[0] if body is not None else 0.0
        width = min(width_of(usable, wide), road.declared_width_m)
        joint = usable.buffer(TOUCH_M).intersection(network)
        head, centre = _head(body, joint, radius, wide)
        stem = _stem(body, head, centre, wide)
        crooked = stem is not None and bent(stem, width)
        problems, doubts = [], []
        if width + TOL_M < wide:
            problems.append(f"{width:.2f} m wide")
        if length > high + TOL_M:  # the box is never longer than the road: too long for certain
            problems.append(f"{length:.0f} m long")
        elif length < low - TOL_M:
            (doubts if crooked else problems).append(f"{length:.0f} m long")
        elif crooked:
            doubts.append(f"{length:.0f} m across a bend")
        if head + TOL_M < radius - 0.05:
            problems.append(f"head radius {head:.1f} m")
        if usable.distance(network) > TOUCH_M:
            problems.append("not joined to the road network")
        status = Status.FAIL if problems else Status.UNVERIFIED if doubts else Status.PASS
        shown = "; ".join(problems + doubts) if problems or doubts else (
            f"{width:.2f} m wide, {length:.0f} m long, head radius {head:.1f} m")
        out.append(plain(
            Family.ROADS, f"Internal roads: cul-de-sac {road.id}", status, shown,
            f"{wide:g} m wide, {low:g}-{high:g} m long, a {radius:g} m radius head",
            _clause(ctx), BEND_NOTE if doubts and not problems else "", subject=road.id))
    return out


# --- Blocks above 12 m open onto a road ------------------------------------------------------


def _served_check(ctx: Context, ground: Ground) -> Check | None:
    circ = ctx.rules.circulation
    if not circ.block_over_12m_on_road.value:
        return None  # read as allowing a pathway to any block: nothing to hold them to
    limit = circ.pathway_max_block_height_m.value
    tall = [t for t in ctx.towers if t.physical_height_m > limit]
    roads = _ground_of(ctx, ground, *ROAD_KINDS)
    lane = _ground_of(ctx, ground, RoadKind.PERIMETER_LANE)
    required = f"every block above {limit:g} m on an internal road, not a pathway"
    clause = circ.pathway_max_block_height_m.clause
    off = [t for t in tall if roads.is_empty or t.footprint.distance(roads) > TOUCH_M]
    cut_off = [t.name for t in off if lane.is_empty or t.footprint.distance(lane) > TOUCH_M]
    lane_only = [t.name for t in off if t.name not in cut_off]
    rule = "Internal roads: every block served"
    basis = basis_note(circ.block_over_12m_on_road)
    if cut_off:
        return plain(Family.ROADS, rule, Status.FAIL, f"not on a road: {', '.join(cut_off)}",
                     required, clause, basis)
    if lane_only:
        return plain(Family.ROADS, rule, Status.UNVERIFIED,
                     f"on the perimeter lane only: {', '.join(lane_only)}", required, clause,
                     " ".join(("The perimeter lane is not established as an 8(m) road.", basis)))
    return plain(Family.ROADS, rule, Status.PASS, f"all {len(tall)} blocks", required, clause,
                 basis)


def _pathway_check(ctx: Context, ground: Ground) -> Check | None:
    """Rule 8(l): a block up to 12 m high may take its access through a 6 m pathway branching out
    of an internal road instead of standing on one. Said for the blocks that high which stand on
    no road. It is the complement of `_served_check`: every block is in exactly one of the two.

    INTERIM (contracts 1.2): the candidate cannot draw a pathway (it has no road kind for one) and
    the rules carry no pathway width, so a block up to 12 m high that stands on no road is
    UNVERIFIED ("a pathway is not drawn"), never PASS or FAIL. This is the one place that changes
    when it can."""
    circ = ctx.rules.circulation
    if not circ.block_over_12m_on_road.value:
        return None  # read as allowing a pathway to any block: nothing to hold them to
    limit = circ.pathway_max_block_height_m.value
    short = [t for t in ctx.towers if not t.physical_height_m > limit]
    if not short:
        return None
    roads = _ground_of(ctx, ground, *ROAD_KINDS)
    off = [t.name for t in short if roads.is_empty or t.footprint.distance(roads) > TOUCH_M]
    rule = f"Internal roads: blocks up to {limit:g} m (pathways)"
    required = (f"every block up to {limit:g} m on an internal road, or reached by a pathway "
                "branching out of one")
    clause = circ.pathway_max_block_height_m.clause
    basis = basis_note(circ.block_over_12m_on_road)
    if not off:
        return plain(Family.ROADS, rule, Status.PASS, f"all {len(short)} on an internal road",
                     required, clause, basis)
    return plain(Family.ROADS, rule, Status.UNVERIFIED,
                 f"on no road: {', '.join(off)}; a pathway is not drawn", required, clause,
                 " ".join(("The layout cannot show a pathway, so whether one branches out of an "
                           "internal road to the block is not known.", basis)))


# --- Driveways -------------------------------------------------------------------------------


def driveway_check(ctx: Context, ground: Ground, scheme: bool) -> Check | None:
    """Driveways at least 4.5 m wide, none counted as an internal road. On a group development
    scheme with none drawn it says so; elsewhere there is nothing to say."""
    drives = ctx.drawn.roads_of(RoadKind.DRIVEWAY)
    circ = ctx.rules.circulation
    if not drives:
        return plain(Family.ROADS, "Driveways", Status.PASS,
                     "none drawn: every block opens onto an internal road",
                     f">= {circ.driveway_min_m.value:g} m where one is drawn",
                     circ.driveway_min_m.clause,
                     "No driveway is counted towards the internal-road requirement."
                     ) if scheme else None
    least = circ.driveway_min_m.value
    widths = {d.id: min(width_of(_usable(d, ground), least), d.declared_width_m)
              for d in drives}
    thin = [i for i, w in widths.items() if w + TOL_M < least]
    return plain(
        Family.ROADS, "Driveways", verdict(not thin),
        (f"narrower than {least:g} m: " + ", ".join(thin)) if thin else
        f"{_plural(len(drives), 'driveway')}, at least {least:g} m",
        f">= {least:g} m where one is drawn", circ.driveway_min_m.clause,
        "No driveway is counted towards the internal-road requirement.")


# --- Roads and fire lanes inside the setback -------------------------------------------------


def setback_circulation_check(ctx: Context) -> Check | None:
    """Roads and fire lanes inside the mandatory setback, under both readings of whether
    circulation may use it. The entrance road crossing the setback to the gate is not counted:
    it cannot reach the gate any other way."""
    d = ctx.drawn
    if not d.has_circulation:
        return None
    by_kind = {k: union_of_all([r.shape for r in d.roads_of(k)]) for k in RoadKind}
    rest = union_of_all([by_kind[k] for k in RoadKind if k is not RoadKind.APPROACH]
                        + [d.fire_hardstanding])

    def cell(a: Assignment) -> Cell:
        reading, circulation = a[STILT_IN_RULE_HEIGHT], a[CIRCULATION_IN_SETBACK]
        zone = setback_zone(ctx, reading)
        required = "circulation outside the mandatory setback" if circulation == NOT_ALLOWED \
            else "no limit: roads and fire lanes may run in the setback"
        if circulation not in (ALLOWED, NOT_ALLOWED):
            return unknown_reading(CIRCULATION_IN_SETBACK, circulation)
        if zone is None:
            return Cell(Status.NOT_CHECKED, "no setback known under this reading", required,
                        "Table III is not modelled yet.")
        crossing = ctx.entrance_land.buffer(deepest_setback_m(ctx, reading) + 1.0)
        approach = by_kind[RoadKind.APPROACH].difference(crossing)
        area = union_of_all([rest, approach]).intersection(zone).area
        measured = f"{area:,.0f} m² of road and fire lane inside the setback"
        if circulation == ALLOWED:
            return Cell(Status.PASS, measured, required)
        return Cell(verdict(area <= NOISE_SQM), measured, required)

    return check_from(
        run(ctx.rules, [STILT_IN_RULE_HEIGHT, CIRCULATION_IN_SETBACK], cell),
        family=Family.ROADS, rule="Circulation inside the setback",
        clause=law.SETBACK_ON_NET_PLOT_CLAUSE,
        note="Not settled law: rule 13(c)(vii) lets ramps use side and rear setbacks leaving 7 m "
        "for fire vehicles, which implies circulation there without saying so.")


# --- Declared against drawn ------------------------------------------------------------------


def narrowest_road(ctx: Context, ground: Ground) -> tuple[str, float] | None:
    """The loop, internal or approach road that measures narrowest, and its width (no wider than
    it declares); None when there is none."""
    nine = ctx.rules.circulation.internal_road_m.value
    network = healed(_ground_of(ctx, ground, *RULE_8M_KINDS, RoadKind.PERIMETER_LANE))
    widths = [(r.id, min(width_in(network, _usable(r, ground),
                                  max(nine, r.declared_width_m) + 1.0), r.declared_width_m))
              for r in ctx.drawn.roads_of(*RULE_8M_KINDS)]
    return min(widths, key=lambda w: w[1], default=None)


def width_discrepancies(ctx: Context, ground: Ground) -> list[Discrepancy]:
    """A road that measures narrower than the width it declares: the declaration flatters the
    layout, so it blocks a pass."""
    network = healed(_ground_of(ctx, ground, *ROAD_KINDS, RoadKind.PERIMETER_LANE,
                                RoadKind.DRIVEWAY))
    out = []
    for road in ctx.drawn.roads:
        usable = _usable(road, ground)
        measured = width_in(network, usable, road.declared_width_m + 1.0)
        if measured + DECLARED_SLACK_M < road.declared_width_m:
            out.append(Discrepancy(
                item=f"road width {road.id}", source="generator",
                theirs=f"{road.declared_width_m:g} m wide", ours=f"{measured:.2f} m wide",
                blocks_pass=True))
    return out


# --- All of it -------------------------------------------------------------------------------


def road_checks(ctx: Context, ground: Ground) -> list[Check]:
    circ = ctx.rules.circulation
    area = ctx.site.ownership.gross_sqm.value
    by_the_site = law.is_group_development(area)
    out: list[Check] = []
    if circ.applies.value != by_the_site:
        out.append(plain(
            Family.CONSISTENCY, "Rule 8 and the site agree", Status.UNVERIFIED,
            f"the rules say rule 8 {'applies' if circ.applies.value else 'does not apply'}; the "
            f"site, {area:,.0f} m², {'is' if by_the_site else 'is not'} a Group Development Scheme",
            f"rule 8 applies from {law.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} m²",
            law.GROUP_DEVELOPMENT_CLAUSE,
            "The rules and the site disagree; rule 8 is applied, the stricter."))
    if not (circ.applies.value or by_the_site):
        out.append(plain(
            Family.ROADS, "Internal roads (rule 8)", Status.INFO,
            f"site {area:,.0f} m²: not a Group Development Scheme",
            f"rule 8 applies from {law.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} m²",
            ctx.rules.category.group_development.clause,
            "Rule 8(m)'s internal roads and 8(l)'s pathways do not apply below 4,000 m²."))
    elif not ctx.drawn.roads:
        out.append(plain(Family.ROADS, "Internal roads", Status.UNVERIFIED,
                         "no road layout drawn", "rule 8(m) widths", _clause(ctx),
                         "Without roads drawn nothing here can be passed."))
    elif not ctx.drawn.roads_of(*RULE_8M_KINDS, RoadKind.CUL_DE_SAC, RoadKind.PERIMETER_LANE):
        out.append(plain(Family.ROADS, "Internal roads", Status.FAIL,
                         "only driveways drawn, no main approach, loop or internal road",
                         f"a {ctx.rules.circulation.internal_road_m.value:g} m road network",
                         _clause(ctx), "A driveway (rule 13(c)(viii), 4.5 m) is not counted as an "
                         "internal road."))
    else:
        network = healed(_ground_of(ctx, ground, *RULE_8M_KINDS, RoadKind.PERIMETER_LANE))
        out += _approach_checks(ctx, ground, network)
        network_check = _network_check(ctx, ground, network)
        out += [network_check] if network_check else []
        out += _perimeter_checks(ctx, ground)
        out += _cul_de_sac_checks(ctx, ground)
        served, pathways = _served_check(ctx, ground), _pathway_check(ctx, ground)
        joined = entrance_connection_check(ctx, ground)
        out += [dead_end_check(ctx, ground)] + ([joined] if joined else [])
        out += [served] if served else []
        out += [pathways] if pathways else []
    drive = driveway_check(ctx, ground, circ.applies.value or by_the_site)
    out += [drive] if drive else []
    return out
