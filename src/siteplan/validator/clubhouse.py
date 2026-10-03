"""The club house, rule 15(a)(x): a block of its own, of a size the rules name from 100 units.

How big it must be is an open reading (amenity_share): at least 3% of the built-up area (the 2012
wording, kept as the planning minimum), or up to 3% of it or 50,000 sft, whichever is lower (the
2016 wording, which may make 3% a ceiling and adds a cap). Both are evaluated when the rules say
ALL. The built-up area and the unit count are recomputed from the towers, not taken from the
generator's metrics.
"""

from __future__ import annotations

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import AMENITY_SHARE
from siteplan.contracts.validation import Check, Family
from siteplan.units import sqft_to_sqm
from siteplan.validator.context import Context
from siteplan.validator.readings import (
    MINIMUM_SHARE,
    SHARE_OR_CAP,
    Assignment,
    Cell,
    check_from,
    run,
    unknown_reading,
    verdict,
)
from siteplan.validator.shapes import NOISE_SQM, union_of_all

SIZE_SLACK_SQM = 0.5  # a club house this close to the size asked is that size


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

    def cell(x: Assignment) -> Cell:
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

    return check_from(run(ctx.rules, [AMENITY_SHARE], cell), family=Family.AMENITIES,
                      rule="Amenities (club house)", clause=a.share_of_built_up.clause)
