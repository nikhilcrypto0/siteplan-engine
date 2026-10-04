"""The land itself: the net plot, the water buffers, the planted strip, and the block's exits.

The net plot is the one fact every other measurement stands on; a site model that cannot place it
is refused (validate.py), and one whose outline does not match the net ownership is not trusted.
"""

from __future__ import annotations

from siteplan.contracts.common import Provenance, Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT
from siteplan.contracts.site_model import NET_PLOT_TOLERANCE, CanonicalSiteModel
from siteplan.contracts.validation import Check, Family
from siteplan.validator.context import Context
from siteplan.validator.readings import Assignment, Cell, check_from, plain, run
from siteplan.validator.shapes import NOISE_SQM, narrower_than, sides_of, union_of_all
from siteplan.validator.zones import (
    StripAsk,
    deepest_setback_m,
    green_strip_zones,
    strips_asked,
)

WATER_OVERLAP_SQM = 0.01  # less than this inside a buffer is floating point, not a block
STRIP_SLACK = 0.01  # the planted strip may fall short of the required one by this share
STRIP_WIDTH_SLACK_M = 0.02


def net_plot_check(ctx: Context) -> Check:
    own = ctx.site.ownership.net_sqm
    drawn = ctx.net.area
    required = f"the net ownership, {own.value:,.1f} m² (within {NET_PLOT_TOLERANCE:.0%})"
    rule = "Net plot"
    clause = "G.O.168 rule 7(a)(iii) (setbacks are measured on the net plot)"
    ok = abs(drawn - own.value) <= NET_PLOT_TOLERANCE * own.value
    confirmed = ctx.site.net_plot.status is not Provenance.UNVERIFIED
    note = ("" if ok else "The outline and the net ownership disagree: the site model is not "
            "consistent, so nothing measured on it can be trusted.") + (
        "" if confirmed else " The outline is not confirmed by anyone.")
    return plain(Family.CONSISTENCY, rule, Status.PASS if ok and confirmed else Status.UNVERIFIED,
                 f"outline {drawn:,.1f} m²", required, clause, note.strip())


def no_net_plot_check(site: CanonicalSiteModel) -> Check:
    """The refusal: a site model with no outline of the net plot to measure on, or with one that
    cannot be measured on."""
    unusable = site.net_plot is not None
    return plain(
        Family.CONSISTENCY, "Net plot", Status.UNVERIFIED,
        "the outline crosses itself or encloses no ground" if unusable else "not known",
        "an outline of the net plot, after every deduction from ownership",
        "G.O.168 rule 7(a)(iii) (setbacks are measured on the net plot)",
        "The validator refuses to certify a layout it cannot measure on the land it stands on: "
        + ("the pipeline stops and asks for an outline that can be measured." if unusable else
           "the site model cannot place the net plot (a deduction's location is not known), so "
           "the pipeline stops and asks where the deduction lies."))


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
    buildings += [("club house", d.club), ("cellar", d.cellar_outline)]
    buildings += [(a.name, a.shape) for a in d.amenities if a.hard]
    inside = [n for n, g in buildings if g.intersection(keep_out).area > WATER_OVERLAP_SQM]
    unsure = [a.name for a in d.amenities
              if a.unknown and a.shape.intersection(keep_out).area > WATER_OVERLAP_SQM]
    status = Status.FAIL if inside else Status.UNVERIFIED if unsure else Status.PASS
    shown = (f"inside it: {', '.join(inside)}" if inside else
             f"in it, surface not stated: {', '.join(unsure)}" if unsure else
             "every block and cellar clear of it")
    return plain(
        Family.WATER, "Water-body buffer", status, shown, required, clause,
        "The buffer may count as tot-lot or organised open space, never as the setback. A paved "
        "amenity is a building here; one whose surface the brief does not say is not judged.")


def electricity_line_check(ctx: Context) -> Check | None:
    """Rule 3(c)(i): a building keeps 3 m from a high-tension line and 1.5 m from a low-tension
    one, vertically and horizontally. The site model marks a line without its geometry or its
    height, so where the survey marks one the distance is said and never passed."""
    marked = [f.text or f.kind for f in ctx.site.features
              if f.kind == "HT_LINE" or "HT line" in f.text or "LT line" in f.text]
    if not marked:
        return None
    lines = ctx.rules.electrical
    return plain(
        Family.OTHER, "Distance from electricity lines", Status.UNVERIFIED,
        "a line is marked on the survey: " + "; ".join(marked),
        f"{lines.ht_clearance_m.value:g} m from a high-tension line, "
        f"{lines.lt_clearance_m.value:g} m from a low-tension line, vertical and horizontal",
        lines.ht_clearance_m.clause,
        "The survey marks the line but not where it runs or how high: the distance cannot be "
        "measured.")


def _where(ask: StripAsk) -> str:
    return ("on all sides" if ask.front and ask.others
            else "along the frontage" if ask.front else "on the sides but the front")


def green_strip_check(ctx: Context) -> Check:
    """The planting the blocks' bands ask: the high-rise strip (rule 7(a)(viii)) where a high-rise
    band's setback reaches 9 m and the band carries none of its own, and the strip a band carries
    (`Band.green_strip_m`: Table III's, along the frontage or round the plot line). A strip lies
    within the setbacks and is never added to them. Where the access road's side is not known a
    strip along only part of the plot line cannot be placed, and what cannot be told is
    UNVERIFIED."""
    green, d = ctx.rules.green_strip, ctx.drawn
    rule, clause = "Peripheral green strip", ctx.rules.green_strip.width_m.clause
    asks = {r: strips_asked(ctx, r) for r in ctx.stilt_readings}
    zones = {r: green_strip_zones(ctx, r) for r in ctx.stilt_readings}
    required_anywhere = any(z is not None for z in zones.values())
    deepest = max((deepest_setback_m(ctx, r) or 0.0 for r in ctx.stilt_readings), default=0.0)
    required = (f">= {green.width_m.value:g} m on sides with a setback of "
                f"{green.where_setback_from_m.value:g} m or more")
    given = [a for found in asks.values() for a in found if a.given]
    if given:
        required = "; ".join(dict.fromkeys(f">= {a.width_m:g} m {_where(a)}"
                                           for found in asks.values() for a in found))
        tables = [c.table for found in ctx.classes.values() for c in found.values()
                  if c.settled and c.band.green_strip_m]
        clause = "; ".join(dict.fromkeys([clause, *tables]))
    known = [deepest_setback_m(ctx, r) for r in ctx.stilt_readings]
    if all(k is None for k in known):
        return plain(Family.GREEN_STRIP, rule, Status.NOT_CHECKED, "setbacks not known",
                     required, clause,
                     "Below the high-rise threshold Table III applies and is not modelled yet.")
    if not required_anywhere:
        low = ctx.low_rise_judged()
        also = (f" The bands of {', '.join(t.name for t in low)} (below "
                f"{ctx.rules.height.high_rise_from_m.value:g} m) ask none." if low else "")
        return plain(Family.GREEN_STRIP, rule, Status.INFO,
                     f"deepest setback here is {deepest:.2f} m", required, clause,
                     f"The strip is required only where the setback reaches "
                     f"{green.where_setback_from_m.value:g} m.{also}")
    strip = d.green_strip

    def cell(a: Assignment) -> Cell:
        reading = a[STILT_IN_RULE_HEIGHT]
        if zones[reading] is None:
            return Cell(Status.PASS, "not required under this reading", required)
        certain, possible = zones[reading]
        if strip.is_empty:
            status = Status.UNVERIFIED if d.buildings_only else Status.FAIL
            return Cell(status, "not drawn", required,
                        "Needs the landscape layer: soft planting nothing drives, parks or is "
                        "built on.")
        covered = union_of_all([strip, ctx.entrance_land])
        narrowest = min(ask.width_m for ask in asks[reading])
        problems, doubts = [], []
        short = certain.difference(covered).area
        if short > max(NOISE_SQM, STRIP_SLACK * certain.area):
            problems.append(f"{short:,.0f} m² of the strip is missing")
        if narrower_than(strip, narrowest - STRIP_WIDTH_SLACK_M):
            problems.append(f"narrower than {narrowest:g} m in places")
        unplaced = possible.difference(covered).area
        if not problems and unplaced > max(NOISE_SQM, STRIP_SLACK * possible.area):
            doubts.append("the access road's side is not known, so which stretch of the plot "
                          "line a strip along only part of it lies on is not known")
        status = Status.FAIL if problems else Status.UNVERIFIED if doubts else Status.PASS
        return Cell(status,
                    "; ".join(problems + doubts) if problems or doubts else
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
