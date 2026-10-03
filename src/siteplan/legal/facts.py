"""The facts a reader needs beside the geometry, as findings: the site's category, whether a
high-rise can stand here, every height limit in metres with how far it can be trusted, and each
input the answer still lacks (UNVERIFIED), so no gap in what is known hides behind a drawing.
"""

from __future__ import annotations

from siteplan.contracts.common import Finding, Provenance, SourceKind, Status
from siteplan.contracts.envelope import Obligation
from siteplan.contracts.resolved_rules import HeightMeasure, ResolvedRules, TableVColumn
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.legal.bands import BandLand
from siteplan.provenance import confirmed
from siteplan.rules import PARKING_CLAUSE

LIMIT_NAMES = {HeightMeasure.RULE_HEIGHT: "Rule-height limit",
               HeightMeasure.PHYSICAL_HEIGHT: "Physical-height limit",
               HeightMeasure.AMSL: "Height above sea level"}


def facts(site: CanonicalSiteModel, rules: ResolvedRules, cap: float | None,
          lands: list[BandLand], found: list[Finding]) -> list[Finding]:
    """`found` are the findings the exclusions raised (water or an HT line not placed)."""
    high_rise_from = rules.height.high_rise_from_m
    group = rules.category.group_development
    out = [Finding("Group Development Scheme", Status.INFO, "yes" if group.value else "no",
                   "residential development on a campus or site of the size the clause names",
                   group.clause, f"how far the site's area is trusted: {group.status}"),
           _eligibility(rules, cap)]
    out += [_limit(limit) for limit in rules.height.limits]
    if lands:
        out.append(Finding(
            f"A building of exactly {high_rise_from.value:g} m", Status.NOT_CHECKED,
            "high-rise, but no band carries it",
            "Table IV's first row, which only that height reaches", high_rise_from.clause,
            f"the bands start above {high_rise_from.value:g} m, so a block of exactly that "
            "height has no setback envelope here"))
    out += _street_join(site, rules)
    out += _net_plot(site)
    if rules.jurisdiction.table_v_column is TableVColumn.OPEN:
        out.append(Finding("Table V column", Status.UNVERIFIED, "whose rules apply is open",
                           "the column of the authority and CURE", PARKING_CLAUSE,
                           rules.jurisdiction.note))
    if rules.category.above_5_acres.value:
        large = rules.category.above_5_acres
        out.append(Finding("Very large project", Status.INFO, "the site is above the size",
                           "common amenities in a share of the site area", large.clause,
                           large.note))
    return [*out, *found]


def _eligibility(rules: ResolvedRules, cap: float | None) -> Finding:
    above = rules.height.high_rise_from_m
    rule = [lim for lim in rules.height.limits if lim.measure is HeightMeasure.RULE_HEIGHT]
    allowed = cap is None or cap > above.value
    unverified = any(lim.status is Provenance.UNVERIFIED for lim in rule)
    status = Status.FAIL if not allowed else Status.UNVERIFIED if unverified else Status.PASS
    measured = ("the rule-height limit is not known" if cap is None
                else f"rule-height limit {cap:g} m")
    return Finding("High-rise eligibility", status, measured, f"above {above.value:g} m",
                   above.clause, "; ".join(lim.reason for lim in rule))


def _limit(limit) -> Finding:
    status = Status.UNVERIFIED if limit.status is Provenance.UNVERIFIED else Status.INFO
    measured = f"{limit.max_m:g} m" if limit.max_m is not None else "no figure"
    return Finding(LIMIT_NAMES[limit.measure], status, measured, limit.applies_if or "always",
                   limit.clause, f"{limit.reason} [{limit.status}]")


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
