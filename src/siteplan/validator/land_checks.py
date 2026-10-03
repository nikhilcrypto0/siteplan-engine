"""The land itself: the net plot, the water buffers, the planted strip, and the block's exits.

The net plot is the one fact every other measurement stands on; a site model that cannot place it
is refused (validate.py), and one whose outline does not match the net ownership is not trusted.
"""

from __future__ import annotations

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT
from siteplan.contracts.site_model import NET_PLOT_TOLERANCE
from siteplan.contracts.validation import Check, Family
from siteplan.validator.context import Context
from siteplan.validator.readings import Assignment, Cell, check_from, plain, run, verdict
from siteplan.validator.shapes import NOISE_SQM, narrower_than, sides_of, union_of_all
from siteplan.validator.zones import deepest_setback_m, green_strip_zone

WATER_OVERLAP_SQM = 0.01  # less than this inside a buffer is floating point, not a block
STRIP_SLACK = 0.01  # the planted strip may fall short of the required one by this share
STRIP_WIDTH_SLACK_M = 0.02


def net_plot_check(ctx: Context) -> Check:
    own = ctx.site.ownership.net_sqm
    drawn = ctx.net.area
    required = f"the net ownership, {own.value:,.1f} m² (within {NET_PLOT_TOLERANCE:.0%})"
    rule = "Net plot"
    clause = "G.O.168 rule 7(a)(iii) (setbacks are measured on the net plot)"
    if not ctx.net.is_valid or drawn <= 0:
        return plain(Family.CONSISTENCY, rule, Status.UNVERIFIED, "the outline is not a valid "
                     "polygon", required, clause)
    ok = abs(drawn - own.value) <= NET_PLOT_TOLERANCE * own.value
    confirmed = ctx.site.net_plot.status is not Provenance.UNVERIFIED
    note = ("" if ok else "The outline and the net ownership disagree: the site model is not "
            "consistent, so nothing measured on it can be trusted.") + (
        "" if confirmed else " The outline is not confirmed by anyone.")
    return plain(Family.CONSISTENCY, rule, Status.PASS if ok and confirmed else Status.UNVERIFIED,
                 f"outline {drawn:,.1f} m²", required, clause, note.strip())


def no_net_plot_check() -> Check:
    return plain(
        Family.CONSISTENCY, "Net plot", Status.UNVERIFIED, "not known",
        "an outline of the net plot, after every deduction from ownership",
        "G.O.168 rule 7(a)(iii) (setbacks are measured on the net plot)",
        "The site model cannot place the net plot (a deduction's location is not known). The "
        "validator refuses to certify a layout it cannot measure on the land it stands on: the "
        "pipeline stops and asks where the deduction lies.")


def water_check(ctx: Context) -> Check | None:
    if not ctx.site.water:
        return None
    clause = ctx.rules.water.buffer_m_by_class.clause
    required = "no building within the water body's buffer"
    if ctx.land.undrawn_water:
        names = ", ".join(z.id for z in ctx.land.undrawn_water)
        return plain(Family.WATER, "Water-body buffer", Status.UNVERIFIED,
                     f"no line or channel in the site model for {names}", required, clause,
                     "A water body with no geometry has no buffer to keep clear.")
    d, keep_out = ctx.drawn, ctx.land.keep_out
    buildings = [(t.name, t.footprint) for t in ctx.towers]
    buildings += [("club house", d.club)] + [(a.name, a.shape) for a in d.amenities if a.roofed]
    buildings += [("cellar", d.cellar_outline)]
    inside = [n for n, g in buildings if g.intersection(keep_out).area > WATER_OVERLAP_SQM]
    return plain(
        Family.WATER, "Water-body buffer", verdict(not inside),
        f"inside it: {', '.join(inside)}" if inside else "every block and cellar clear of it",
        required, clause,
        "The buffer may count as tot-lot or organised open space, never as the setback.")


def green_strip_check(ctx: Context) -> Check:
    green, d = ctx.rules.green_strip, ctx.drawn
    rule, clause = "Peripheral green strip", ctx.rules.green_strip.width_m.clause
    zones = {r: green_strip_zone(ctx, r) for r in ctx.stilt_readings}
    required_anywhere = any(z is not None for z in zones.values())
    deepest = max((deepest_setback_m(ctx, r) or 0.0 for r in ctx.stilt_readings), default=0.0)
    required = (f">= {green.width_m.value:g} m on sides with a setback of "
                f"{green.where_setback_from_m.value:g} m or more")
    known = [deepest_setback_m(ctx, r) for r in ctx.stilt_readings]
    if all(k is None for k in known):
        return plain(Family.GREEN_STRIP, rule, Status.NOT_CHECKED, "setbacks not known",
                     required, clause,
                     "Below the high-rise threshold Table III applies and is not modelled yet.")
    if not required_anywhere:
        return plain(Family.GREEN_STRIP, rule, Status.INFO,
                     f"deepest setback here is {deepest:.2f} m", required, clause,
                     f"The strip is required only where the setback reaches "
                     f"{green.where_setback_from_m.value:g} m.")
    strip = d.green_strip

    def cell(a: Assignment) -> Cell:
        zone = zones[a[STILT_IN_RULE_HEIGHT]]
        if zone is None:
            return Cell(Status.PASS, "not required under this reading", required)
        if strip.is_empty:
            status = Status.UNVERIFIED if d.buildings_only else Status.FAIL
            return Cell(status, "not drawn", required,
                        "Needs the landscape layer: soft planting nothing drives, parks or is "
                        "built on.")
        short = zone.difference(union_of_all([strip, d.gate_land])).area
        thin = narrower_than(strip, green.width_m.value - STRIP_WIDTH_SLACK_M)
        problems = []
        if short > max(NOISE_SQM, STRIP_SLACK * zone.area):
            problems.append(f"{short:,.0f} m² of the strip is missing")
        if thin:
            problems.append(f"narrower than {green.width_m.value:g} m in places")
        return Cell(verdict(not problems),
                    "; ".join(problems) if problems else
                    f"{strip.area:,.0f} m² along the boundary, broken only at the entrance",
                    required, "Soft planting: nothing drives, parks or is built on it.")

    return check_from(run(ctx.rules, [STILT_IN_RULE_HEIGHT], cell), family=Family.GREEN_STRIP,
                      rule=rule, clause=clause)


def egress_check(ctx: Context) -> Check | None:
    """Exits inside a block (travel distance to a staircase, the number of stairs) are not
    modelled, so a long slab's layout is not a full building-code check. Said on every high-rise
    layout, never left out."""
    high = ctx.high_rise_anywhere()
    if not high:
        return None
    longest = max(sides_of(t.footprint)[0] for t in high)
    return plain(
        Family.EGRESS, "INTERNAL_EGRESS", Status.NOT_CHECKED,
        f"longest block {longest:.0f} m; travel distance to a staircase and the exits are not "
        "modelled", "NBC 2016 Part 4 exit requirements inside each block",
        "NBC 2016 Part 4 (not modelled)",
        "Long slabs with few cores need this checked before they are relied on.")
