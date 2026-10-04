"""The club house, rule 15(a)(x): a block of its own, of a size the rules name from 100 units.

How big it must be is an open reading (amenity_share): at least 3% of the built-up area (the 2012
wording, kept as the planning minimum), or up to 3% of it or 50,000 sft, whichever is lower (the
2016 wording, which may make 3% a ceiling and adds a cap). Both are evaluated when the rules say
ALL. The built-up area and the unit count are recomputed from the towers, not taken from the
generator's metrics.
"""

from __future__ import annotations

from dataclasses import replace

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import (
    AMENITY_SHARE,
    MIXED_HEIGHT_SPACING,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.contracts.validation import Check, Family
from siteplan.units import sqft_to_sqm
from siteplan.validator.blocks import gap_cell, gap_clause
from siteplan.validator.context import Context
from siteplan.validator.measure import (
    ALL_ROUND_NOTE,
    TOL_M,
    UNCONFIRMED_NOTE,
    HeightClass,
    classify,
    setback_of,
)
from siteplan.validator.readings import (
    EACH_OWN,
    MINIMUM_SHARE,
    SHARE_OR_CAP,
    TALLER_GOVERNS,
    Assignment,
    Cell,
    check_from,
    plain,
    run,
    unknown_reading,
    verdict,
)
from siteplan.validator.shapes import NOISE_SQM, union_of_all

SIZE_SLACK_SQM = 0.5  # a club house this close to the size asked is that size
TABLE_III_NOTE = ("Below the high-rise threshold Table III (rule 5) applies and is not modelled "
                  "yet: the validator does not judge it.")
TALL_CLUB_NOTE = ("A club house as tall as a high-rise is a block like the towers: its fire access "
                  "and spacing are not modelled for it, so it cannot pass.")


def units_of(ctx: Context) -> int:
    return sum(sum(t.units.values()) for t in ctx.towers)


def built_up_sqm(ctx: Context) -> float:
    """Every floor of every block, the club house included: what the rules measure against."""
    return sum(t.built_up_sqm for t in ctx.towers) + ctx.drawn.club.area * ctx.drawn.club_floors


def club_house_check(ctx: Context) -> Check:
    a, d = ctx.rules.amenities, ctx.drawn
    units, built_up = units_of(ctx), built_up_sqm(ctx)
    provided = d.club.area * d.club_floors
    cap_sqm = sqft_to_sqm(a.cap_sqft_2016.value)
    share = a.share_of_built_up.value
    separate = d.club.intersection(union_of_all([t.footprint for t in ctx.towers])).area
    basis = (f"{a.share_of_built_up.basis.value}, {a.share_of_built_up.status.value}: "
             f"{a.share_of_built_up.note}" if a.share_of_built_up.note else
             f"{a.share_of_built_up.basis.value}, {a.share_of_built_up.status.value}")

    def size_cell(x: Assignment) -> Cell:
        reading = x[AMENITY_SHARE]
        if units < a.from_units.value:
            return Cell(Status.INFO, f"{units} units", f"the clause applies from "
                        f"{a.from_units.value} units")
        if d.club.is_empty and d.buildings_only:
            return Cell(Status.UNVERIFIED, "no club house drawn",
                        "a club house from 100 units", "Only the buildings are drawn.")
        measured = (f"{provided:,.0f} m² ({provided / built_up:.2%} of built-up)"
                    if built_up else "no built-up area")
        if separate > NOISE_SQM:
            return Cell(Status.FAIL, f"{measured}, {separate:,.0f} m² of it inside a residential "
                        "block", "a block that is not part of the residential blocks", basis)
        if reading == MINIMUM_SHARE:
            need = share * built_up
            return Cell(verdict(provided + SIZE_SLACK_SQM >= need), measured,
                        f">= {share:.0%} of built-up area = {need:,.0f} m²", basis)
        if reading == SHARE_OR_CAP:
            ceiling = min(share * built_up, cap_sqm)
            return Cell(verdict(provided <= ceiling + SIZE_SLACK_SQM), measured,
                        f"up to {share:.0%} of built-up or {a.cap_sqft_2016.value:,.0f} sft, "
                        f"whichever is lower = {ceiling:,.0f} m²", basis)
        return unknown_reading(AMENITY_SHARE, reading)

    tall = _club_class(ctx)

    def cell(x: Assignment) -> Cell:
        result = size_cell(x)
        if tall is not None and tall.high_rise and result.status is Status.PASS:
            return replace(result, status=Status.UNVERIFIED,
                           note=" ".join((result.note, TALL_CLUB_NOTE)).strip())
        return result

    return check_from(run(ctx.rules, [AMENITY_SHARE], cell), family=Family.AMENITIES,
                      rule="Amenities (club house)", clause=a.share_of_built_up.clause)


# --- Where the club house stands -----------------------------------------------------------


def _club_height_m(ctx: Context) -> float:
    return ctx.drawn.club_floors * ctx.brief.firm_standards.floor_to_floor_m.value


def _club_class(ctx: Context) -> HeightClass | None:
    """The club house's own band, from its floors and the firm's floor height."""
    if ctx.drawn.club.is_empty:
        return None
    return classify(ctx.rules, _club_height_m(ctx))


def club_setback_check(ctx: Context) -> Check | None:
    """The club house is a building and keeps the setback its own band asks: Table IV's when it
    is as tall as a high-rise (where it cannot pass: it is a block like the towers, with its fire
    access and spacing not modelled), Table III's below that, where the rules model the band. A
    band they do not model is said, not left out."""
    cls = _club_class(ctx)
    if cls is None:
        return None
    rule, clause = "Club house: setback", ctx.rules.setbacks.measured_on.clause
    if cls.state != "ok":
        return plain(Family.SETBACK, rule, Status.NOT_CHECKED,
                     f"{cls.height_m:g} m high: {cls.label}", "the setback its height asks",
                     clause, TABLE_III_NOTE)
    gap = setback_of(ctx.net, ctx.drawn.club)
    required = f">= {cls.setback_m:.2f} m to the net plot line"
    if not cls.high_rise:
        if not cls.confirmed:
            return plain(Family.SETBACK, rule, Status.UNVERIFIED, f"{gap:.2f} m", required,
                         f"{cls.table}; {clause}", f"{ALL_ROUND_NOTE} {UNCONFIRMED_NOTE}")
        return plain(Family.SETBACK, rule, verdict(gap + TOL_M >= cls.setback_m),
                     f"{gap:.2f} m", required, f"{cls.table}; {clause}", ALL_ROUND_NOTE)
    status = verdict(gap + TOL_M >= cls.setback_m)
    return plain(Family.SETBACK, rule, Status.UNVERIFIED if status is Status.PASS else status,
                 f"{gap:.2f} m", required, clause, TALL_CLUB_NOTE if status is Status.PASS else "")


def club_gap_checks(ctx: Context) -> list[Check]:
    """The club house is a block of its own (rule 15(a)(x)), so it keeps a gap from each tower.
    Below the high-rise height in a band the rules model it is judged like any pair of blocks, on
    its own band's gap. A club house the rules do not model has no gap of its own, so the tower's
    gap is the one asked where the taller block governs; where each block keeps its own, the
    tower's half is the least that can be asked and the rest is not known. A club house as tall as
    a high-rise is not modelled."""
    d, cls = ctx.drawn, _club_class(ctx)
    inside = d.club.intersection(union_of_all([t.footprint for t in ctx.towers])).area
    if cls is None or inside > NOISE_SQM:
        return []
    below = cls.settled and not cls.high_rise
    out = []
    for tower in ctx.towers:
        gap = float(tower.footprint.distance(d.club))

        def cell(a: Assignment, tower=tower, gap=gap) -> Cell:
            reading, spacing = a[STILT_IN_RULE_HEIGHT], a[MIXED_HEIGHT_SPACING]
            tower_cls = ctx.classes.get(reading, {}).get(tower.name)
            if tower_cls is None:
                return unknown_reading(STILT_IN_RULE_HEIGHT, reading)
            if below:
                return gap_cell(cls, tower_cls, _club_height_m(ctx), tower.rule_height_m(reading),
                                spacing, gap)
            shown, need = f"{gap:.2f} m", tower_cls.gap_m
            if need is None or cls.state == "ok" or spacing not in (TALLER_GOVERNS, EACH_OWN):
                return Cell(Status.NOT_CHECKED, shown, "a Table IV gap",
                            TABLE_III_NOTE if need is None else
                            "A club house of 21 m or more is a block like the rest: not modelled.")
            fail = Status.FAIL if tower_cls.settled else Status.UNVERIFIED
            if spacing == TALLER_GOVERNS:
                status = Status.PASS if gap + TOL_M >= need else fail
                return Cell(status, shown, f">= {need:.2f} m (the taller block's gap)")
            if gap + TOL_M >= need:
                return Cell(Status.PASS, shown, f">= {need / 2:.2f} m, up to {need:.2f} m")
            status = fail if gap + TOL_M < need / 2 else Status.UNVERIFIED
            return Cell(status, shown, f">= {need / 2:.2f} m, up to {need:.2f} m",
                        "Each block keeps its own gap: the club house's is Table III's, not "
                        "modelled, so only the tower's half is known.")

        pairs = [(cls, classes[tower.name]) for classes in ctx.classes.values()] if below else []
        out.append(check_from(
            run(ctx.rules, [STILT_IN_RULE_HEIGHT, MIXED_HEIGHT_SPACING], cell),
            family=Family.SPACING, rule=f"Club house gap to {tower.name}",
            clause=gap_clause(ctx, pairs), subject=tower.name))
    return out
