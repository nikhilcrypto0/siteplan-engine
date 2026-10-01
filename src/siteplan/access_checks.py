"""Road and fire-access findings, measured from the drawn layout, not taken from whatever built it.

Roads (rule 8(m), read with 8(l)): every road at least its width, every high-rise block opening
onto one, no dead end unless it is a cul-de-sac of the form 8(m) allows. Fire access (NBC 2016
Part 3 4.6, through rule 15(b)(iv)): 6 m of clear, motorable ground on every side of every
high-rise, room for the 9 m turn at every corner and every bend of the loop, a way in from the
entrance to all of it, nothing parked or built in it. What the drawing cannot show, where the
street leads, is UNVERIFIED until the architect says.
"""

from __future__ import annotations

from shapely.ops import unary_union

from siteplan import rules
from siteplan.access import (
    FIRE_BAND_M,
    LANE_M,
    around_block,
    blocked,
    healed,
    lane_passes,
    loop_turns,
    through_roads,
)
from siteplan.findings import Finding, Status, narrower_than

TOUCH_M = 0.5  # a block this close to a road opens onto it
OVERLAP_SQM = 0.5  # less than this of overlap is drawing noise, not a car or a wall


def _roads(site, *kinds: str):
    return [r for r in site.roads if not kinds or r.kind in kinds]


def site_area(site) -> float | None:
    """The site's area for rule 2(c): as per documents (the gross), else the net plot."""
    if site.gross_area_sqm:
        return site.gross_area_sqm
    if site.net_area_sqm:
        return site.net_area_sqm
    return site.net_plot.area if site.net_plot is not None else None


def road_findings(site) -> list[Finding]:
    """Rule 8(m): the internal roads, their widths, and that every block and ramp is on one.
    Rule 8 governs a Group Development Scheme (rule 2(c)), so below 4,000 m² it is not applied."""
    clause = rules.INTERNAL_ROAD_CLAUSE
    area = site_area(site)
    if area is not None and not rules.is_group_development(area):
        return [Finding(
            "Internal roads (rule 8)", Status.INFO,
            f"site {area:,.0f} m²: not a Group Development Scheme",
            f"rule 8 applies from {rules.GROUP_DEVELOPMENT_MIN_SITE_SQM:,.0f} m²",
            rules.GROUP_DEVELOPMENT_CLAUSE,
            "Rule 8(m)'s internal roads and 8(l)'s pathways do not apply below 4,000 m².",
        )]
    if not site.roads:
        return [Finding("Internal roads", Status.NOT_CHECKED, "no road layout drawn",
                        "rule 8(m) widths", clause)]
    low, high = rules.MAIN_APPROACH_ROAD_M
    findings = []
    for road in _roads(site, "main approach"):
        thin = narrower_than(road.shape, low - 0.02)
        findings.append(Finding(
            "Internal roads: main approach", Status.FAIL if thin else Status.PASS,
            (f"narrower than {low:g} m in places (drawn {road.width_m:g} m, cut by the "
             "boundary)" if thin else f"{road.width_m:g} m wide") + ", from the entrance to the "
            "loop road",
            f">= {low:g} m (the order gives {low:g} to {high:g} m)", clause,
            f"Drawn at the least the order allows; it gives no test for when a main approach "
            f"road must be wider, so the authority may ask for up to {high:g} m.",
        ))
    others = _roads(site, "loop", "internal")
    network = healed(unary_union([r.shape for r in site.roads])) if others else None
    if network is not None:
        thin = narrower_than(network, rules.INTERNAL_ROAD_M - 0.02)
        loops = len(_roads(site, "loop"))
        inner = len(_roads(site, "internal"))
        findings.append(Finding(
            "Internal roads: loop and other roads", Status.FAIL if thin else Status.PASS,
            f"a loop road and {inner} internal road{'s' if inner != 1 else ''}"
            + (", narrower than 9 m in places" if thin else ", all at least 9 m")
            if loops else f"{inner} internal roads", f">= {rules.INTERNAL_ROAD_M:g} m", clause,
            "A driveway (rule 13(c)(viii), 4.5 m) is not counted as an internal road.",
        ))
    findings.append(_dead_end_finding(site, clause))
    findings.append(_served_finding(site))
    findings.append(Finding(
        "Driveways", Status.PASS,
        "none needed: every block's stilt and the ramp open straight onto an internal road",
        f">= {rules.DRIVEWAY_MIN_WIDTH_M:g} m where one is drawn", rules.DRIVEWAY_CLAUSE,
        "No driveway is counted towards the internal-road requirement.",
    ))
    return findings


def _dead_end_finding(site, clause: str) -> Finding:
    base = unary_union([r.shape for r in _roads(site, "loop", "main approach")])
    _, dead = through_roads(_roads(site, "internal"), base)
    low, high = rules.CUL_DE_SAC_LENGTH_M
    required = (f"through roads; a cul-de-sac only {low:g}-{high:g} m long, "
                f"{rules.CUL_DE_SAC_WIDTH_M:g} m wide, with a "
                f"{rules.CUL_DE_SAC_HEAD_RADIUS_M:g} m radius head")
    if not dead:
        return Finding("Internal roads: dead ends", Status.PASS,
                       "every internal road joins the loop at both ends", required, clause)
    return Finding(
        "Internal roads: dead ends", Status.FAIL,
        f"{len(dead)} road{'s' if len(dead) != 1 else ''} ending without a turning head",
        required, clause, "The layout does not draw cul-de-sac heads, so a dead end fails.",
    )


def _served_finding(site) -> Finding:
    """Rule 8(l) lets 6 m pathways serve blocks up to 12 m only, so every taller block has to
    open onto an internal road."""
    tall = [b for b in site.buildings if b.footprint is not None
            and (b.resolved_height() or 0) > rules.PATHWAY_MAX_BLOCK_HEIGHT_M]
    road_land = unary_union([r.shape for r in site.roads])
    cut_off = [b.name for b in tall if b.footprint.distance(road_land) > TOUCH_M]
    required = (f"every block above {rules.PATHWAY_MAX_BLOCK_HEIGHT_M:g} m on an internal road, "
                "not a pathway")
    return Finding(
        "Internal roads: every block served", Status.FAIL if cut_off else Status.PASS,
        f"not on a road: {', '.join(cut_off)}" if cut_off else f"all {len(tall)} blocks",
        required, rules.PATHWAY_CLAUSE,
    )


def fire_findings(site, high_rise) -> list[Finding]:
    """NBC 4.6: fire tenders reach every side of every high-rise, and can turn."""
    clause = rules.FIRE_ACCESS_CLAUSE
    if not high_rise:
        return [Finding("Fire access", Status.INFO, "no high-rise block", "NBC 4.6 for high-rise",
                        clause)]
    findings = [_street_finding(site), _dead_end_road_finding(site, high_rise)]
    if site.net_plot is None or not site.roads:
        findings.append(Finding(
            "Fire access: around each block", Status.NOT_CHECKED,
            "no road and lane layout drawn", f">= {LANE_M:g} m clear on all sides", clause))
        return findings
    inner = site.net_plot
    if site.green_strip is not None:
        inner = inner.difference(site.green_strip)
    if site.water_buffer is not None:
        inner = inner.difference(site.water_buffer)
    buildings = [b.footprint for b in site.buildings if b.footprint is not None]
    solid = [*buildings, *site.obstructions]
    if site.club_house is not None:
        solid.append(site.club_house)
    free = inner.difference(unary_union(solid)) if solid else inner
    motorable = unary_union([*(r.shape for r in site.roads),
                             *([site.fire_lanes] if site.fire_lanes is not None else [])])
    for b in high_rise:
        if b.footprint is not None:
            findings.append(_block_finding(b, free, motorable, clause))
    findings.append(_loop_turns_finding(site, free, clause))
    findings.append(_reach_finding(site, high_rise, motorable, clause))
    findings.append(_entrance_finding(site))
    findings.append(_obstruction_finding(site, motorable, clause))
    findings.append(Finding(
        "Fire access: 45 t hard surface", Status.UNVERIFIED, "a specification, not a drawing",
        "roads and fire lanes carry a 45 t tender", clause,
        "The paving, and any cellar roof under a road or fire lane, must be designed for it.",
    ))
    return findings


def _block_finding(b, free, motorable, clause: str) -> Finding:
    band = b.footprint.buffer(LANE_M, join_style="mitre").difference(b.footprint)
    not_clear = band.difference(free).area > OVERLAP_SQM
    not_motorable = band.difference(motorable).area > OVERLAP_SQM
    turns = around_block(b.footprint)
    stuck = blocked(turns, free)
    problems = []
    if not_clear:
        problems.append("something stands within 6 m of it")
    if not_motorable:
        problems.append("part of the 6 m round it is not a road or fire lane")
    if stuck:
        problems.append(f"{len(stuck)} of {len(turns)} corner turns blocked")
    measured = ("; ".join(problems) if problems else
                f"{LANE_M:g} m clear on every side; all {len(turns)} corner turns fit")
    return Finding(
        f"Fire access: {b.name}", Status.FAIL if problems else Status.PASS, measured,
        f">= {LANE_M:g} m motorable on all sides; a {rules.FIRE_TURNING_RADIUS_M:g} m turn at "
        "every corner", clause,
        f"UNRESOLVED_INTERPRETATION: the order gives the {rules.FIRE_TURNING_RADIUS_M:g} m, not "
        f"where it is measured. Read here as the outer edge of the {LANE_M:g} m lane, which needs "
        f"{FIRE_BAND_M:.2f} m of clear ground beside each face; that figure is derived from our "
        "reading, not written in the rule (a 9 m centreline would need 7.76 m).",
    )


def _loop_turns_finding(site, free, clause: str) -> Finding:
    """Every bend of the loop road as drawn: its outer edge, and round the land it rings."""
    loops = _roads(site, "loop")
    turns = loop_turns(unary_union([r.shape for r in loops])) if loops else []
    stuck = blocked(turns, free)
    return Finding(
        "Fire access: turns along the loop road", Status.FAIL if stuck else Status.PASS,
        f"{len(stuck)} of {len(turns)} bends blocked" if stuck else
        f"all {len(turns)} bends turn at {rules.FIRE_TURNING_RADIUS_M:g} m",
        f"a {rules.FIRE_TURNING_RADIUS_M:g} m turn at every bend", clause,
    )


def _reach_finding(site, high_rise, motorable, clause: str) -> Finding:
    """A 6 m lane runs from the entrance to the ground round every high-rise."""
    passable = lane_passes(motorable)
    start = site.entrance.approach if site.entrance is not None else None
    parts = list(getattr(passable, "geoms", [passable]))
    reached = [p for p in parts if start is not None and p.intersects(start)]
    network = unary_union(reached) if reached else None
    missing = []
    for b in high_rise:
        if b.footprint is None:
            continue
        band = b.footprint.buffer(LANE_M, join_style="mitre").difference(b.footprint)
        if network is None or not network.intersects(band):
            missing.append(b.name)
    return Finding(
        "Fire access: reached from the entrance", Status.FAIL if missing else Status.PASS,
        f"cut off: {', '.join(missing)}" if missing else "every block, by a 6 m lane or road",
        "a continuous way in for a fire tender", clause,
    )


def _entrance_finding(site) -> Finding:
    clause = rules.GATE_CLAUSE
    required = (f">= {rules.GATE_MIN_WIDTH_M:g} m wide; {rules.ENTRANCE_CLEAR_HEIGHT_M:g} m clear "
                "under anything built over it")
    if site.entrance is None:
        return Finding("Fire access: entrance", Status.NOT_CHECKED, "no entrance drawn",
                       required, clause)
    wide = site.entrance.width_m >= rules.GATE_MIN_WIDTH_M
    return Finding(
        "Fire access: entrance", Status.PASS if wide else Status.FAIL,
        f"{site.entrance.width_m:g} m, {site.entrance.note}; nothing built over it", required,
        clause, "The gate folding back against the compound wall is a detail drawing.",
    )


def _obstruction_finding(site, motorable, clause: str) -> Finding:
    solid = [*site.obstructions] + ([site.club_house] if site.club_house is not None else [])
    hit = [s for s in solid if s.intersection(motorable).area > OVERLAP_SQM]
    return Finding(
        "Fire access: nothing parked or built on it", Status.FAIL if hit else Status.PASS,
        f"{len(hit)} items stand on a road or fire lane" if hit else
        "no bay, facility, ramp or tot-lot on any road or fire lane",
        "kept free of obstructions; never used for parking", clause,
    )


def _street_finding(site) -> Finding:
    required = f"joins a street at least {rules.FIRE_STREET_JOIN_M:g} m wide at one end"
    value = site.street_joins_12m
    if value is None:
        return Finding("Fire access: the street joins a 12 m street", Status.UNVERIFIED,
                       "not known: a survey does not show where the road leads", required,
                       rules.FIRE_STREET_CLAUSE, "The architect's to say.")
    return Finding("Fire access: the street joins a 12 m street",
                   Status.PASS if value else Status.FAIL,
                   "yes, as the architect says" if value else "no, as the architect says",
                   required, rules.FIRE_STREET_CLAUSE)


def _dead_end_road_finding(site, high_rise) -> Finding:
    tallest = max((b.resolved_height() or 0) for b in high_rise)
    limit = rules.DEAD_END_MAX_HEIGHT_M
    required = f"no dead-end road for a residential building above {limit:g} m"
    rule = "Fire access: dead-end road"
    if tallest <= limit + 1e-6:
        return Finding(rule, Status.PASS, f"tallest {tallest:g} m, within {limit:g} m", required,
                       rules.DEAD_END_CLAUSE, "A dead end is allowed up to 30 m.")
    if site.road_dead_end is None:
        return Finding(rule, Status.UNVERIFIED, f"tallest {tallest:g} m; the road's end is not "
                       "known", required, rules.DEAD_END_CLAUSE)
    return Finding(rule, Status.FAIL if site.road_dead_end else Status.PASS,
                   f"tallest {tallest:g} m; the road "
                   + ("ends at the plot" if site.road_dead_end else "runs on"),
                   required, rules.DEAD_END_CLAUSE)
