"""The towers against Table IV: height class, plot size, road width, setbacks, gaps.

Every check is run once per reading of whether the stilt counts toward the rule height (and, for
a gap, per reading of which block's gap governs between blocks of different heights). A tower
that is legal only if the stilt does not count is UNVERIFIED and says so; one that is legal
under every reading is PASS; one that fails under every reading is FAIL.
"""

from __future__ import annotations

from itertools import combinations

from siteplan import rules as law
from siteplan.contracts.accounting import DeductionKind
from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    MIXED_HEIGHT_SPACING,
    STILT_IN_RULE_HEIGHT,
    BandKind,
    Eligibility,
    HeightLimit,
    HeightMeasure,
    LimitBound,
    ResolvedRules,
)
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.contracts.validation import Check, Family, PairMeasure, TowerMeasure
from siteplan.provenance import Provenance
from siteplan.validator.context import Context, is_known
from siteplan.validator.measure import (
    TOL_M,
    HeightClass,
    TowerGeometry,
    required_gap,
    setback_of,
)
from siteplan.validator.readings import (
    EACH_OWN,
    Assignment,
    Cell,
    check_from,
    plain,
    run,
    unknown_reading,
    verdict,
)

UNVERIFIED_DRAWING = "UNVERIFIED_DRAWING_VALUE"  # a road's width as drawn, never confirmed
TABLE_III_NOTE = ("Below the high-rise threshold Table III (rule 5) applies and is not modelled "
                  "yet: the validator does not judge it.")


def _table_clause(rules: ResolvedRules) -> str:
    return next((b.clause for b in rules.height.bands if b.kind is BandKind.HIGH_RISE),
                "G.O.168 rule 7(a)(x), Table IV")


def _classes(ctx: Context, reading: str) -> dict[str, HeightClass] | None:
    return ctx.classes.get(reading)


def _stopped(cls: HeightClass, what: str) -> Cell | None:
    """A cell for a height the table does not cover (Table III, or beyond the bands), which is
    NOT_CHECKED; None when there is a row to hold the block to."""
    if cls.state == "unmodelled":
        return Cell(Status.NOT_CHECKED, f"{cls.height_m:.2f} m: {cls.label}", what, TABLE_III_NOTE)
    return None


# --- Height class, plot size, road width ----------------------------------------------------


def height_class_checks(ctx: Context) -> list[Check]:
    out = []
    for t in ctx.towers:
        parts = []
        for reading in ctx.stilt_readings:
            cls = (_classes(ctx, reading) or {}).get(t.name)
            if cls is not None:
                parts.append(f"{cls.height_m:.2f} m, {cls.label}, if the stilt is {reading}")
        out.append(plain(
            Family.HEIGHT, f"Height class: {t.name}", Status.INFO,
            f"{t.physical_height_m:.2f} m physical (stilt included); rule height "
            + "; ".join(parts),
            f"high-rise from {ctx.rules.height.high_rise_from_m.value:g} m",
            ctx.rules.height.high_rise_from_m.clause, subject=t.name))
    return out


def plot_size_check(ctx: Context) -> Check | None:
    if not ctx.high_rise_anywhere():
        return None
    area, need = ctx.net.area, law.MIN_HIGH_RISE_PLOT_SQM

    def cell(a: Assignment) -> Cell:
        if _classes(ctx, a[STILT_IN_RULE_HEIGHT]) is None:
            return unknown_reading(STILT_IN_RULE_HEIGHT, a[STILT_IN_RULE_HEIGHT])
        required = f">= {need:,.0f} m²"
        if not ctx.high_rise(a[STILT_IN_RULE_HEIGHT]):
            return Cell(Status.NOT_CHECKED, f"{area:,.0f} m²; no high-rise under this reading",
                        required, TABLE_III_NOTE)
        return Cell(verdict(area + TOL_M >= need), f"{area:,.0f} m² (the net plot)", required)

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.HEIGHT,
                      rule="Plot size for high-rise", clause=law.MIN_HIGH_RISE_PLOT_CLAUSE)


def _surrenders_land(site: CanonicalSiteModel) -> bool:
    """Whether the site gives up land for the road (a SURRENDER deduction from ownership)."""
    return any(d.kind is DeductionKind.SURRENDER for d in site.ownership.deductions)


def road_width(site: CanonicalSiteModel) -> tuple[float | None, str, bool]:
    """The width of the access road the rules take, how it is known, and whether that is
    settled. The master plan's width wins where there is one and the widening strip is
    surrendered (otherwise the road is as wide as it is); the width the survey draws is never
    used, and a width read off a drawing and never confirmed is a value, not a settled fact."""
    road = site.access_road()
    if road is None:
        return None, "no access road in the site model", False
    settled = road.row_status != UNVERIFIED_DRAWING
    if is_known(road.master_plan_row_m) and _surrenders_land(site):
        return road.master_plan_row_m.value, "master plan", settled
    if is_known(road.legal_row_m):
        return road.legal_row_m.value, "existing", settled
    return None, "the legal width is not known", False


def road_width_check(ctx: Context) -> Check | None:
    if not ctx.high_rise_anywhere():
        return None
    width, how, settled = road_width(ctx.site)
    road = ctx.site.access_road()
    tallest = max(ctx.high_rise_anywhere(), key=lambda t: t.physical_height_m)
    basis = []
    if road is not None and road.row_status:
        basis.append(f"Width status: {road.row_status}.")
    if road is not None and road.drawn_width_m is not None:
        basis.append(f"The survey measures {road.drawn_width_m:.2f} m of carriageway; the rules "
                     "use the declared width.")
    if how == "master plan":
        basis.append("The master plan's width counts because the road-widening strip is "
                     "surrendered (a deduction from ownership).")
    elif road is not None and is_known(road.master_plan_row_m):
        basis.append(f"The master plan's {road.master_plan_row_m.value:.2f} m is not counted: no "
                     "land is surrendered for the widening, so the road is as wide as it is.")

    def cell(a: Assignment) -> Cell:
        reading = a[STILT_IN_RULE_HEIGHT]
        classes = _classes(ctx, reading)
        if classes is None:
            return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
        high = [classes[t.name] for t in ctx.high_rise(reading)]
        if not high:
            return Cell(Status.NOT_CHECKED, "no high-rise under this reading",
                        "Table IV column 3", TABLE_III_NOTE)
        for cls in high:
            stopped = _stopped(cls, "Table IV column 3")
            if stopped is not None:
                return stopped
        need = max(c.min_road_m or 0.0 for c in high)
        required = f">= {need:g} m"
        if width is None:
            return Cell(Status.UNVERIFIED, f"unknown ({how})", required)
        if not settled:
            return Cell(Status.UNVERIFIED, f"{width:.2f} m ({how}), not confirmed", required,
                        " ".join([*basis, "The width is a drawing's, never confirmed."]))
        if width + TOL_M >= need:
            return Cell(Status.PASS, f"{width:.2f} m ({how})", required, " ".join(basis))
        return Cell(Status.FAIL, f"{width:.2f} m ({how})", required, " ".join(basis))

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.HEIGHT,
                      rule=f"Abutting road width (for {tallest.name})",
                      clause=_table_clause(ctx.rules), subject=tallest.name)


def height_limit_checks(ctx: Context) -> list[Check]:
    """The limits the resolved rules state in metres, held against the towers. A limit above
    sea level (the airport's, the Air Force's) cannot be held to a layout: it is UNVERIFIED."""
    out = []
    above_sea = [lim for lim in ctx.rules.height.limits if lim.measure is HeightMeasure.AMSL]
    if above_sea:
        out.append(plain(
            Family.HEIGHT, "Height above sea level (airport and Air Force)", Status.UNVERIFIED,
            "not evaluated: " + "; ".join(lim.reason for lim in above_sea),
            "below the airport and Air Force limits", above_sea[0].clause,
            "A site with no coordinates, or a survey with no ground level, cannot be held to a "
            "limit above sea level."))
    for limit in ctx.rules.height.limits:
        if limit.measure is HeightMeasure.RULE_HEIGHT and ctx.towers:
            out.append(_rule_height_limit(ctx, limit))
        elif (limit.measure is HeightMeasure.PHYSICAL_HEIGHT and ctx.towers
              and limit.clause != ctx.rules.fire.dead_end_max_physical_m.clause):
            out.append(_physical_height_limit(ctx, limit))  # the dead-end limit is the fire check's
    return out


def _limit_required(limit: HeightLimit) -> str:
    if limit.bound is LimitBound.UNBOUNDED:
        return "no limit from this rule"
    if limit.bound is LimitBound.NOT_EVALUATED:
        return "evaluated once the limit is known"
    return f"{'<=' if limit.inclusive else '<'} {limit.max_m:g} m"


def _limit_note(limit: HeightLimit) -> str:
    """Why a limit's verdict is what it is, beside its own reason: whether it is in force and
    how far the inputs behind it are confirmed (HeightLimit.evaluate reads both)."""
    parts = [limit.reason]
    if limit.condition is not None:
        parts.append(f"it applies only if {limit.condition.text} "
                     f"({limit.applicability.value.lower().replace('_', ' ')})")
    if limit.status is Provenance.UNVERIFIED:
        parts.append("the limit rests on inputs nobody has confirmed, so it settles nothing "
                     "either way")
    return "; ".join(parts) + "."


def _physical_height_limit(ctx: Context, limit: HeightLimit) -> Check:
    """A limit on the height NBC measures (stilt included), whatever the reading of the stilt.
    The verdict is the contract's (HeightLimit.evaluate), as the optimizer's is."""
    tallest = max(ctx.towers, key=lambda t: t.physical_height_m)
    measured = f"{tallest.physical_height_m:.2f} m ({tallest.name})"
    return plain(Family.HEIGHT, f"Physical-height limit: {limit.reason}",
                 limit.evaluate(tallest.physical_height_m), measured, _limit_required(limit),
                 limit.clause, _limit_note(limit), subject=tallest.name)


def prototype_height_check(ctx: Context) -> Check | None:
    """Every height rule is judged on a tower's floors times its floor height, which a prototype
    may set for itself. A floor or stilt shorter than the firm's standard lowers the building under
    every rule at once, so a prototype that does is said, and the height rules rest on it."""
    firm = ctx.brief.firm_standards
    shorter = {}
    for t in ctx.towers:
        heights = t.prototype.heights
        own = [(label, value, standard) for label, value, standard in (
            ("floor", heights.floor_to_floor_m, firm.floor_to_floor_m.value),
            ("stilt", heights.stilt_height_m if t.has_stilt else None, firm.stilt_height_m.value))
            if value is not None and value + TOL_M < standard]
        for label, value, standard in own:
            shorter.setdefault(
                f"{t.prototype.id} {label} {value:g} m against the firm's {standard:g} m",
                []).append(t.name)
    if not shorter:
        return None
    return plain(Family.HEIGHT, "Heights of the prototypes", Status.UNVERIFIED,
                 "; ".join(f"{what} ({', '.join(names)})" for what, names in shorter.items()),
                 "the firm's standard floor and stilt heights, or a reason for the difference", "",
                 "The height rules are judged on the prototype's own heights, as the contract "
                 "says, but nothing here confirms heights below the firm's.")


def tdr_check(ctx: Context) -> Check | None:
    """Rule 17(d)(viii): a building of 18 to 21 m on a plot of 750 to 2,000 m² is permitted only
    through TDR, which a layout cannot show, so it is a question, not a pass."""
    height = ctx.rules.height
    (low, high), (small, large) = height.tdr_band_m.value, height.tdr_plot_sqm.value
    if not small <= ctx.net.area <= large:
        return None
    readings = [r for r in ctx.stilt_readings if r in ctx.classes]
    inside = {r: [t.name for t in ctx.towers if low <= t.rule_height_m(r) < high - TOL_M]
              for r in readings}
    if not any(inside.values()):
        return None

    def cell(a: Assignment) -> Cell:
        names = inside.get(a[STILT_IN_RULE_HEIGHT], [])
        required = f"no building of {low:g} to {high:g} m, unless through TDR"
        if not names:
            return Cell(Status.PASS, "none in that band", required)
        return Cell(Status.UNVERIFIED, f"{', '.join(names)} in that band", required,
                    "Whether TDR is used is not something a layout shows.")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.HEIGHT,
                      rule="TDR for a building of 18 to 21 m", clause=height.tdr_band_m.clause)


def _rule_height_limit(ctx: Context, limit: HeightLimit) -> Check:
    """A limit on the rule height, under each reading of the stilt. The verdict is the
    contract's (HeightLimit.evaluate): a limit that cannot be worked out, rests on unconfirmed
    inputs, or may not apply settles nothing either way."""
    required = _limit_required(limit)

    def cell(a: Assignment) -> Cell:
        reading = a[STILT_IN_RULE_HEIGHT]
        heights = {t.name: t.rule_height_m(reading) for t in ctx.towers}
        if None in heights.values():
            return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
        tallest = max(heights, key=heights.get)
        return Cell(limit.evaluate(heights[tallest]), f"{heights[tallest]:.2f} m ({tallest})",
                    required, _limit_note(limit))

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.HEIGHT,
                      rule=f"Rule-height limit: {limit.reason}", clause=limit.clause)


ELIGIBILITY_STATUS = {Eligibility.ALLOWED: Status.PASS, Eligibility.PROHIBITED: Status.FAIL,
                      Eligibility.UNVERIFIED: Status.UNVERIFIED}


def eligibility_check(ctx: Context) -> Check | None:
    """Whether the site may take a high-rise at all, as the rules resolve it, held against the
    blocks of the high-rise height or more. A prohibition fails such a block; it permits nothing
    lower, and a lower block is Table III's, which this validator does not judge."""
    if not ctx.high_rise_anywhere():
        return None
    high_rise = ctx.rules.height.high_rise
    named = ([g for g in high_rise.grounds if g.settled and g.met is False]
             or [g for g in high_rise.grounds if not g.settled])
    required = "; ".join(f"{g.id} {g.required}" for g in high_rise.grounds)

    def cell(a: Assignment) -> Cell:
        reading = a[STILT_IN_RULE_HEIGHT]
        if _classes(ctx, reading) is None:
            return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
        high = ctx.high_rise(reading)
        if not high:
            return Cell(Status.NOT_CHECKED, "no high-rise under this reading", required,
                        TABLE_III_NOTE)
        measured = (f"{high_rise.eligibility.value}: "
                    + "; ".join(f"{g.id} {g.measured}" for g in named or high_rise.grounds))
        return Cell(ELIGIBILITY_STATUS[high_rise.eligibility], measured, required,
                    high_rise.note)

    clause = "; ".join(sorted({g.clause for g in named or high_rise.grounds}))
    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.HEIGHT,
                      rule="High-rise eligibility", clause=clause)


# --- Setbacks ------------------------------------------------------------------------------


def setback_checks(ctx: Context) -> list[Check]:
    clause = "; ".join((_table_clause(ctx.rules), ctx.rules.setbacks.front.clause,
                        ctx.rules.setbacks.measured_on.clause))
    out = []
    for t in ctx.towers:
        gap = setback_of(ctx.net, t.footprint)
        outside = not ctx.net.contains(t.footprint)

        def cell(a: Assignment, t=t, gap=gap, outside=outside) -> Cell:
            reading = a[STILT_IN_RULE_HEIGHT]
            cls = (_classes(ctx, reading) or {}).get(t.name)
            if cls is None:
                return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
            stopped = _stopped(cls, "Table IV setback")
            if stopped is not None:
                return Cell(stopped.status, f"{gap:.2f} m", stopped.required, stopped.note)
            need = cls.setback_m
            if outside:  # no row of any table is met by a block that is not on the plot
                return Cell(Status.FAIL, f"{gap:.2f} m: not wholly inside the net plot",
                            f">= {need:.2f} m to the net plot line")
            ok = gap + TOL_M >= need
            return Cell(Status.PASS if ok else Status.FAIL, f"{gap:.2f} m",
                        f">= {need:.2f} m to the net plot line",
                        "The front of a high-rise keeps the Table IV figure too, measured on the "
                        "net plot.")

        out.append(check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.SETBACK,
                              rule=f"All-round setback: {t.name}", clause=clause, subject=t.name))
    return out


# --- Gaps between blocks -------------------------------------------------------------------


def _gap_cell(ca: HeightClass, cb: HeightClass, ha: float, hb: float, spacing: str,
              gap: float) -> Cell:
    need, why = required_gap(ca, cb, ha, hb, spacing)
    shown = f"{gap:.2f} m"
    if why == "unmodelled":
        return Cell(Status.NOT_CHECKED, shown, "Table IV gap", TABLE_III_NOTE)
    if why == "unknown":
        return unknown_reading(MIXED_HEIGHT_SPACING, spacing)
    suffix = (" (the mean of the two blocks' gaps, each keeping its own half)"
              if spacing == EACH_OWN else "")
    ok = gap + TOL_M >= need
    return Cell(Status.PASS if ok else Status.FAIL, shown, f">= {need:.2f} m{suffix}",
                "This gap does not count towards the tot-lot.")


def pair_gap(a: TowerGeometry, b: TowerGeometry) -> float:
    return float(a.footprint.distance(b.footprint))


def spacing_checks(ctx: Context) -> list[Check]:
    out = []
    for a, b in combinations(ctx.towers, 2):
        gap = pair_gap(a, b)

        def cell(x: Assignment, a=a, b=b, gap=gap) -> Cell:
            reading, spacing = x[STILT_IN_RULE_HEIGHT], x[MIXED_HEIGHT_SPACING]
            classes = _classes(ctx, reading)
            if classes is None:
                return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
            return _gap_cell(classes[a.name], classes[b.name], a.rule_height_m(reading),
                             b.rule_height_m(reading), spacing, gap)

        out.append(check_from(
            run(ctx.rules, [STILT_IN_RULE_HEIGHT, MIXED_HEIGHT_SPACING], cell),
            family=Family.SPACING, rule=f"Gap between blocks: {a.name} / {b.name}",
            clause=ctx.rules.spacing.clause, subject=f"{a.name}/{b.name}"))
    return out


# --- What was measured, for the report ----------------------------------------------------


def tower_measures(ctx: Context) -> list[TowerMeasure]:
    out = []
    for t in ctx.towers:
        heights, labels, needs = {}, {}, {}
        for reading in ctx.stilt_readings:
            cls = (_classes(ctx, reading) or {}).get(t.name)
            if cls is None:
                continue
            heights[reading], labels[reading] = cls.height_m, cls.label
            if cls.setback_m is not None:
                needs[reading] = cls.setback_m
        out.append(TowerMeasure(
            name=t.name, physical_height_m=t.physical_height_m,
            rule_height_m_by_reading=heights, band_by_reading=labels,
            setback_m=setback_of(ctx.net, t.footprint), required_setback_m_by_reading=needs))
    return out


def pair_measures(ctx: Context) -> list[PairMeasure]:
    out = []
    for a, b in combinations(ctx.towers, 2):
        needs = []
        for reading in ctx.stilt_readings:
            classes = _classes(ctx, reading)
            if classes is None:
                continue
            for spacing in ctx.rules.readings(MIXED_HEIGHT_SPACING):
                need, _ = required_gap(classes[a.name], classes[b.name],
                                       a.rule_height_m(reading), b.rule_height_m(reading),
                                       spacing)
                if need is not None:
                    needs.append(need)
        out.append(PairMeasure(a=a.name, b=b.name, gap_m=pair_gap(a, b),
                               required_m=max(needs) if needs else None))
    return out
