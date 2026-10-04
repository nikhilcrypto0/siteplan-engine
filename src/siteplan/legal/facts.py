"""The facts a reader needs beside the geometry, as findings: the site's category, whether a
high-rise can stand here, every height limit in metres with how far it can be trusted, and each
input the answer still lacks (UNVERIFIED), so no gap in what is known hides behind a drawing.
"""

from __future__ import annotations

from siteplan.contracts.common import Finding, Provenance, SourceKind, Status
from siteplan.contracts.envelope import Obligation
from siteplan.contracts.resolved_rules import (
    Applicability,
    Band,
    BandKind,
    Eligibility,
    HeightLimit,
    HeightMeasure,
    LimitBound,
    ResolvedRules,
    TableVColumn,
)
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.legal.bands import BandLand
from siteplan.provenance import confirmed
from siteplan.rules import PARKING_CLAUSE

LIMIT_NAMES = {HeightMeasure.RULE_HEIGHT: "Rule-height limit",
               HeightMeasure.PHYSICAL_HEIGHT: "Physical-height limit",
               HeightMeasure.AMSL: "Height above sea level",
               HeightMeasure.HEIGHT_ABOVE_STILT: "Height above the stilt"}


def facts(site: CanonicalSiteModel, rules: ResolvedRules, cap: float | None,
          lands: list[BandLand], found: list[Finding]) -> list[Finding]:
    """`found` are the findings the exclusions raised (water or an HT line not placed)."""
    group = rules.category.group_development
    out = [Finding("Group Development Scheme", Status.INFO, "yes" if group.value else "no",
                   "residential development on a campus or site of the size the clause names",
                   group.clause, f"how far the site's area is trusted: {group.status}"),
           _eligibility(rules), _non_high_rise(rules)]
    out += [_limit(limit) for limit in rules.height.limits]
    out += _street_join(site, rules)
    out += _net_plot(site)
    if rules.jurisdiction.table_v_column is TableVColumn.OPEN:
        out.append(Finding("Table V column", Status.UNVERIFIED, "whose rules apply is open",
                           "the column of the authority and CURE", PARKING_CLAUSE,
                           rules.jurisdiction.note))
    return [*out, *found]


ELIGIBILITY_STATUS = {Eligibility.ALLOWED: Status.PASS, Eligibility.PROHIBITED: Status.FAIL,
                      Eligibility.UNVERIFIED: Status.UNVERIFIED}
MET = {True: "met", False: "not met", None: "not known"}


def _eligibility(rules: ResolvedRules) -> Finding:
    """Whether a high-rise may stand here, from its grounds. A FAIL here permits nothing lower."""
    high_rise = rules.height.high_rise
    above = rules.height.high_rise_from_m
    grounds = "; ".join(f"{g.id} {g.measured}, {g.required} ({MET[g.met]}, {g.status})"
                        for g in high_rise.grounds)
    return Finding("High-rise eligibility", ELIGIBILITY_STATUS[high_rise.eligibility],
                   high_rise.eligibility.value, f"a building of {above.value:g} m or more",
                   above.clause, "; ".join(n for n in (grounds, high_rise.note) if n))


def _non_high_rise(rules: ResolvedRules) -> Finding:
    """The permissible height below the high-rise height: the tallest band Table III permits
    here, on the height above the stilt, and the one that might be if what is open were settled
    (the actual permissible non-high-rise height of this site)."""
    heights = rules.height
    allowed = heights.permissible_non_high_rise()
    possible = heights.permissible_non_high_rise(include_unverified=True)
    clause = next((b.clause for b in heights.bands if b.kind is BandKind.NON_HIGH_RISE), "")
    if possible is None:
        return Finding("Non-high-rise height", Status.FAIL, "none permitted",
                       "a band below the high-rise height with a setback", clause,
                       "no stretch below the high-rise height is permitted or open")

    def top(band: Band) -> str:
        return f"{band.up_to_m:g} m" + ("" if band.up_to_inclusive else " (below it)")

    settled = allowed is not None and (allowed.up_to_m, allowed.up_to_inclusive) == (
        possible.up_to_m, possible.up_to_inclusive)
    return Finding("Non-high-rise height", Status.INFO if settled else Status.UNVERIFIED,
                   top(allowed) if allowed else "not settled",
                   "the tallest height Table III permits, the stilt left out", possible.clause,
                   "" if settled else f"up to {top(possible)} if what is open is settled: "
                   f"{possible.permission_note}")


def _limit(limit: HeightLimit) -> Finding:
    unsettled = (limit.status is Provenance.UNVERIFIED or limit.bound is LimitBound.NOT_EVALUATED
                 or limit.applicability is Applicability.UNKNOWN)
    measured = {LimitBound.BOUNDED: f"{limit.max_m:g} m" if limit.max_m else "",
                LimitBound.UNBOUNDED: "no limit",
                LimitBound.NOT_EVALUATED: "not evaluated"}[limit.bound]
    when = limit.condition.text if limit.condition else "always"
    return Finding(LIMIT_NAMES[limit.measure],
                   Status.UNVERIFIED if unsettled else Status.INFO, measured, when, limit.clause,
                   f"{limit.reason} [{limit.status}; {limit.applicability}]")


def _street_join(site: CanonicalSiteModel, rules: ResolvedRules) -> list[Finding]:
    join, rule = site.access.joins_12m_street, rules.fire.street_join_m
    if join.value is None:
        return [Finding("Street join (NBC 4.6(a))", Status.UNVERIFIED, "not known",
                        f"the street joins one of {rule.value:g} m or more", rule.clause)]
    return [Finding("Street join (NBC 4.6(a))",
                    Status.PASS if join.value else Status.FAIL,
                    "joins a wide street" if join.value else "does not join a wide street",
                    f"the street joins one of {rule.value:g} m or more", rule.clause,
                    f"[{join.status}]")]


def _net_plot(site: CanonicalSiteModel) -> list[Finding]:
    """Where the net plot's outline came from, when that is not firm: an outline taken from the
    firm's finished plan is for debugging only and never for a blind run."""
    plot = site.net_plot
    if plot.source_kind is SourceKind.FIRM_FINISHED_PLAN:
        return [Finding("Net plot outline", Status.UNVERIFIED,
                        "taken from the firm's finished plan", "the architect's own outline of "
                        "the land left after surrender", "G.O.168 rule 7(a)(iii)",
                        f"DEBUG ONLY, never on a blind path [{plot.status}]: {plot.source}")]
    if not confirmed(plot.status):
        return [Finding("Net plot outline", Status.UNVERIFIED, f"{plot.status}: {plot.source}",
                        "the architect's own outline of the land left after surrender",
                        "G.O.168 rule 7(a)(iii)")]
    return []


def requirements(rules: ResolvedRules) -> list[Obligation]:
    """What else the law asks of a layout here, as pointers into ResolvedRules (never copies)."""
    group = rules.circulation.applies.value
    return [
        Obligation(id="open space", applies=True,
                   rule_ref="open_space.requirement_sqm_by_reading",
                   note="the area asked under each reading of the denominator"),
        Obligation(id="club house", applies=group, rule_ref="amenities.share_of_built_up",
                   note="from the number of units the rule names"),
        Obligation(id="parking", applies=True, rule_ref="parking.share_pct",
                   note="the share is open while whose rules apply is open"),
        Obligation(id="ramp", applies=True, rule_ref="parking.ramp_single_min_m"),
        Obligation(id="cellar setback", applies=True,
                   rule_ref="parking.cellar_setback_by_site_sqm")]
