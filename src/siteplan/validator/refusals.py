"""The reports for a candidate the validator cannot measure at all.

A gate must answer every candidate the contract lets through, and never answer with a pass it
could not earn. When there is nothing to measure on (no usable net plot), nothing to measure
with (a number that is not a number), or the geometry library gives up, the report says so in one
check that can never be a pass, instead of stopping the run or guessing.
"""

from __future__ import annotations

import math

from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.envelope import BuildableEnvelope
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.contracts.validation import Check, Family, Recomputed, ValidationReport
from siteplan.validator import cross_checks, land_checks, program, report
from siteplan.validator.context import Context
from siteplan.validator.measure import tower_geometries
from siteplan.validator.readings import plain
from siteplan.validator.shapes import union_of_all

SHOWN = 5  # how many offending numbers a report names before it says there are more
MEASURED_PARTS = ("towers", "prototypes_used", "circulation", "program")
MAX_COUNT = 10**15  # a whole number larger than this is not a count of anything on a site
EXTENT_FACTOR = 20  # drawn ground reaching this many plot-widths away is not drawn to scale
EXTENT_FLOOR_M = 2000.0  # ...and never counts as far away within this
MIN_BAY_M = 1.0  # a bay narrower than this is not a car's, and laying cars out in it never ends
LIBRARY_MESSAGE_CHARS = 300  # how much of the geometry library's own message a report keeps


def non_finite(value, path: str = "") -> list[str]:
    """Where a candidate holds a number that is not a number, is infinite, or is a whole number
    too large to count anything, as paths into it."""
    if isinstance(value, float):
        return [] if math.isfinite(value) else [f"{path} = {value}"]
    if isinstance(value, int) and not isinstance(value, bool):
        digits = round(abs(value).bit_length() * 0.30103)  # not str(): that is capped
        return [] if abs(value) <= MAX_COUNT else [f"{path} = a whole number of ~{digits} digits"]
    if isinstance(value, dict):
        return [bad for k, v in value.items() for bad in non_finite(v, f"{path}.{k}".lstrip("."))]
    if isinstance(value, list | tuple):
        return [bad for i, v in enumerate(value) for bad in non_finite(v, f"{path}[{i}]")]
    return []


def non_finite_in(candidate: CandidateLayout) -> list[str]:
    """The numbers of a candidate that are measured (its towers, prototypes, roads and what it
    draws) which are not numbers. Its seed, scores and claims are not measured and may be
    anything: a 64-bit seed is not an absurd count."""
    dump = candidate.model_dump()
    return [bad for part in MEASURED_PARTS for bad in non_finite(dump[part], part)]


def numbers_check(bad: list[str]) -> Check:
    more = f" and {len(bad) - SHOWN} more" if len(bad) > SHOWN else ""
    return plain(Family.CONSISTENCY, "Numbers in the candidate", Status.FAIL,
                 "; ".join(bad[:SHOWN]) + more, "every coordinate and measure a finite number", "",
                 "A layout holding a number that is not a number cannot be measured, so it "
                 "cannot pass.")


def unusable_rules(rules: ResolvedRules) -> list[str]:
    """Rule values the validator divides by or steps through that cannot be used as they stand.
    The contract admits them; a report that names them beats a crash for whoever resolved them."""
    p, found = rules.parking, []
    measure = p.measurement
    if rules.open_space.share.value <= 0:
        found.append("open_space.share must be above zero")
    if p.ramp_gradient.value <= 0:
        found.append("parking.ramp_gradient must be above zero")
    if min(measure.bay_m) < MIN_BAY_M or measure.aisle_m < 0 or measure.sqm_per_car <= 0:
        found.append(f"parking.measurement: a bay of at least {MIN_BAY_M:g} m, an aisle that is "
                     "not negative and a car that takes floor")
    if not p.cellar_setback_by_site_sqm.value:
        found.append("parking.cellar_setback_by_site_sqm has no rows")
    return found


def rules_check(found: list[str]) -> Check:
    return plain(Family.CONSISTENCY, "Rules the validator can use", Status.UNVERIFIED,
                 "; ".join(found), "rule values that can be divided by and stepped through", "",
                 "The rules carry a value that cannot be used as it stands, so nothing is judged "
                 "on them.")


def too_large(ctx: Context) -> Check | None:
    """A candidate drawn on a different scale from the site (millimetres for metres, say) has
    ground a thousand times the plot's, and laying cars out on it would never finish. It is
    refused, with how far it reaches."""
    drawn, net = ctx.drawn, ctx.net
    grounds = [t.footprint for t in ctx.towers] + [
        drawn.club, drawn.fire_hardstanding, drawn.green_strip, drawn.cellar_outline,
        drawn.paved_land, drawn.gate_land_all, *drawn.bays, *drawn.ramps, *drawn.open_space,
        *(a.shape for a in drawn.amenities)]
    box = union_of_all([g for g in grounds if not g.is_empty])
    if box.is_empty:
        return None
    minx, miny, maxx, maxy = box.bounds
    plot = max(net.bounds[2] - net.bounds[0], net.bounds[3] - net.bounds[1])
    reach = max(maxx - minx, maxy - miny)
    if reach <= max(EXTENT_FACTOR * plot, EXTENT_FLOOR_M):
        return None
    return plain(Family.CONSISTENCY, "Scale of the drawing", Status.FAIL,
                 f"the layout reaches {reach:,.0f} m across a plot {plot:,.0f} m wide",
                 f"drawn to the site's scale, within {EXTENT_FACTOR} plot-widths", "",
                 "Ground that far beyond the site is not on the same scale as it (millimetres "
                 "for metres?), and cannot be measured.")


def library_check(error: Exception, what: str = "") -> Check:
    """The geometry library met two shapes it cannot resolve (edges that differ by a hair, say).
    Nobody has judged what it was measuring, so that is UNVERIFIED, and a person has to look.
    `what` names the group of checks it stopped, when the rest still has its verdicts."""
    return plain(Family.CONSISTENCY,
                 f"{what}: could not be measured" if what else
                 "Shapes the geometry library can measure", Status.UNVERIFIED,
                 f"{type(error).__name__}: {str(error)[:LIBRARY_MESSAGE_CHARS]}",
                 "shapes whose edges the geometry library can tell apart", "",
                 "The validator could not finish measuring this, so it is not a pass.")


def unmeasurable(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
                 candidate: CandidateLayout, envelope: BuildableEnvelope | None,
                 why: Check) -> ValidationReport:
    """Nothing about the candidate is measured: the one check says why, and the program is not
    judged."""
    return report.assemble(
        site, rules, brief, candidate, envelope, recomputed=Recomputed(), legal=[why],
        program=[plain(Family.PROGRAM, "Program", Status.UNVERIFIED, "not judged",
                       "the brief's program", "", "The candidate could not be measured.")],
        partition=None, partition_problems=[], rule_layers=None,
        cross_checks=cross_checks.references(site, rules, brief, candidate, envelope))


def no_net_plot(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
                candidate: CandidateLayout, envelope: BuildableEnvelope | None
                ) -> ValidationReport:
    """No usable net plot, so nothing can be measured on the land: the report is one UNVERIFIED
    check, which can never be a pass, with the references and footprints that need no plot."""
    towers = tower_geometries(candidate, brief, rules)
    return report.assemble(
        site, rules, brief, candidate, envelope,
        recomputed=Recomputed(units_by_type=program.units_by_type(towers)),
        legal=[land_checks.no_net_plot_check(site)],
        program=program.program_checks(brief, candidate, towers, rules), partition=None,
        partition_problems=[], rule_layers=None,
        cross_checks=cross_checks.references(site, rules, brief, candidate, envelope)
        + cross_checks.flaws(towers, None) + cross_checks.footprints(towers))
