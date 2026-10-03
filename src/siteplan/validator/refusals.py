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
from siteplan.validator.measure import tower_geometries
from siteplan.validator.readings import plain

SHOWN = 5  # how many offending numbers a report names before it says there are more
LIBRARY_MESSAGE_CHARS = 300  # how much of the geometry library's own message a report keeps


def non_finite(value, path: str = "") -> list[str]:
    """Where a candidate holds a number that is not a number or is infinite, as paths into it."""
    if isinstance(value, float):
        return [] if math.isfinite(value) else [f"{path} = {value}"]
    if isinstance(value, dict):
        return [bad for k, v in value.items() for bad in non_finite(v, f"{path}.{k}".lstrip("."))]
    if isinstance(value, list | tuple):
        return [bad for i, v in enumerate(value) for bad in non_finite(v, f"{path}[{i}]")]
    return []


def numbers_check(bad: list[str]) -> Check:
    more = f" and {len(bad) - SHOWN} more" if len(bad) > SHOWN else ""
    return plain(Family.CONSISTENCY, "Numbers in the candidate", Status.FAIL,
                 "; ".join(bad[:SHOWN]) + more, "every coordinate and measure a finite number", "",
                 "A layout holding a number that is not a number cannot be measured, so it "
                 "cannot pass.")


def library_check(error: Exception) -> Check:
    """The geometry library met two shapes it cannot resolve (edges that differ by a hair, say).
    Nobody has judged the layout, so it is UNVERIFIED, and a person has to look."""
    return plain(Family.CONSISTENCY, "Shapes the geometry library can measure", Status.UNVERIFIED,
                 f"{type(error).__name__}: {str(error)[:LIBRARY_MESSAGE_CHARS]}",
                 "shapes whose edges the geometry library can tell apart", "",
                 "The validator could not finish measuring this layout, so it is not a pass.")


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
    towers = tower_geometries(candidate, brief)
    return report.assemble(
        site, rules, brief, candidate, envelope,
        recomputed=Recomputed(units_by_type=program.units_by_type(towers)),
        legal=[land_checks.no_net_plot_check(site)],
        program=program.program_checks(brief, candidate, towers, rules), partition=None,
        partition_problems=[], rule_layers=None,
        cross_checks=cross_checks.references(site, rules, brief, candidate, envelope)
        + cross_checks.flaws(towers, None) + cross_checks.footprints(towers))
