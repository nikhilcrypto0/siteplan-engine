"""INTERIM validator: a stand-in until stream D's independent validator (src/siteplan/validator/)
replaces it. Delete this module when D lands and pass D's validator to `optimize`.

It is not independent. It restates the findings the generator attached to a candidate, as the
contract fixtures' reports do, so it can only be as honest as the generator. Two things keep it
from overstating: a standing UNVERIFIED check says nobody independent has looked, so its legal
verdict is never PASS; and it checks on its own what C1 can, with no help from the generator's
claims:

- that the candidate was made for the site, rules and brief it is judged against (a candidate
  left over from an earlier brief is a FAIL);
- each tower's height against the law's limits in metres, under every reading of the stilt the
  rules leave open (a result that holds under only some readings is UNVERIFIED, naming them).

The envelope is ignored: the interim validator cross-checks nothing against it.
"""

from __future__ import annotations

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    ValidationReport,
    digest,
)
from siteplan.contracts.candidate import PlacedTower
from siteplan.contracts.common import Finding, Status
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT, LimitBound
from siteplan.contracts.validation import (
    Check,
    Family,
    Recomputed,
    combine_readings,
    legal_verdict,
    program_verdict,
)
from siteplan.optimizer.floors import assess_floor_count, worst
from siteplan.optimizer.objective import measure

VERSION = ("INTERIM (C1): the generator's own findings restated, plus a floors-from-metres "
           "height check; not an independent validation, replaced by stream D's validator")
ARCHITECTURE = "docs/ARCHITECTURE.md section 6 (D)"
# Which family a generator finding belongs to, by words in its rule's name; the first match wins.
FAMILY_WORDS = (
    (Family.DEAD_END, ("dead-end",)), (Family.FIRE, ("fire",)),
    (Family.PARKING, ("parking", "cellar", "ramp")), (Family.SPACING, ("gap between",)),
    (Family.SETBACK, ("setback",)),
    (Family.HEIGHT, ("height", "high-rise", "plot size", "abutting road")),
    (Family.ROADS, ("road", "driveway")),
    (Family.OPEN_SPACE, ("open space", "open-space", "tot-lot")),
    (Family.AMENITIES, ("amenit", "club")), (Family.WATER, ("water",)),
    (Family.GREEN_STRIP, ("green strip",)), (Family.EGRESS, ("egress",)))
STANDING = Check(family=Family.OTHER, finding=Finding(
    "Independent validation", Status.UNVERIFIED, "the generator's findings restated",
    "an independent validator's own recomputation", ARCHITECTURE,
    "interim validator: no legal PASS is claimed until stream D's validator has judged it"))


def family_of(rule: str) -> Family:
    text = rule.lower()
    return next((family for family, words in FAMILY_WORDS if any(w in text for w in words)),
                Family.OTHER)


class InterimValidator:
    def validate(self, site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
                 candidate: CandidateLayout, envelope: BuildableEnvelope | None = None
                 ) -> ValidationReport:
        legal = [Check(family=family_of(f.rule), finding=f) for f in candidate.generator_claims]
        legal += [_made_for(site, rules, brief, candidate),
                  *(_height(site, rules, brief, candidate, tower) for tower in candidate.towers),
                  STANDING]
        program = [_mix(brief, candidate)]
        net = site.net_plot.value if site.net_plot is not None else None
        return ValidationReport(
            candidate_ref=digest(candidate), site_ref=digest(site), rules_ref=digest(rules),
            brief_ref=digest(brief), validator_version=VERSION,
            recomputed=Recomputed(units_by_type=_units(candidate)),
            legal=legal, program=program,
            accounting={"partition": candidate.partition, "rule_layers": candidate.rule_layers,
                        "partition_problems":
                            candidate.partition.problems(net) if candidate.partition else []},
            not_checked=[f.rule for f in candidate.generator_claims
                         if f.status is Status.NOT_CHECKED] + _unevaluated(rules),
            verdict={"legal": legal_verdict(legal, []), "program": program_verdict(program),
                     "reasons": [f"{c.finding.rule}: {c.finding.status}" for c in legal
                                 if c.finding.status in (Status.FAIL, Status.UNVERIFIED)]})


def _made_for(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
              candidate: CandidateLayout) -> Check:
    """Whether the candidate names the site, rules and brief it is being judged against."""
    other = [name for name, ref, actual in (
        ("site model", candidate.site_ref, digest(site)),
        ("rules", candidate.rules_ref, digest(rules)),
        ("brief", candidate.brief_ref, digest(brief))) if ref != actual]
    return Check(family=Family.CONSISTENCY, finding=Finding(
        "Candidate made for these inputs", Status.FAIL if other else Status.PASS,
        f"made for another {', '.join(other)}" if other else "the same site, rules and brief",
        "made for the site, rules and brief it is judged against",
        "contracts: CandidateLayout refs"))


def _height(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
            candidate: CandidateLayout, tower: PlacedTower) -> Check:
    """One tower's height held against every limit that has a value, under each reading of the
    stilt. A limit with no value (the airport's) is listed in `not_checked`, not passed."""
    prototype = candidate.prototype(tower.prototype_id)
    options = {reading: assess_floor_count(
        rules, brief, prototype, reading, tower.floors_above_stilt,
        has_stilt=tower.has_stilt) for reading in rules.readings(STILT_IN_RULE_HEIGHT)}
    held = {reading: [c for c in option.checks if c.limit_m is not None]
            for reading, option in options.items()}
    by_reading = {reading: worst(checks) for reading, checks in held.items()}
    every = [c for checks in held.values() for c in checks]
    physical = next(iter(options.values())).physical_height_m
    rule_heights = ", ".join(f"{o.rule_height_m:g} m ({r})" for r, o in options.items())
    limits = sorted({f"{c.measure.value.lower().replace('_', ' ')} within {c.limit_m:g} m"
                     for c in every})
    open_or_failed = "; ".join(f"{r}: {c.reason}" for r, checks in held.items()
                               for c in checks if c.status is not Status.PASS)
    return Check(
        family=Family.HEIGHT, subject=tower.name, by_reading={STILT_IN_RULE_HEIGHT: by_reading},
        finding=Finding(
            f"Height: {tower.name}", combine_readings(by_reading),
            f"{physical:g} m physical; rule height {rule_heights}", "; ".join(limits),
            "; ".join(sorted({c.clause for c in every})), open_or_failed))


def _mix(brief: DesignBrief, candidate: CandidateLayout) -> Check:
    error, tolerance = 1 - measure(candidate, brief).mix_fit, brief.program.mix_tolerance
    return Check(family=Family.PROGRAM, finding=Finding(
        "Unit mix", Status.PASS if error <= tolerance else Status.FAIL, f"mix error {error:.3f}",
        f"within {tolerance:g} of {brief.program.unit_mix.value}", "the brief"))


def _units(candidate: CandidateLayout) -> dict[str, int]:
    units: dict[str, int] = {}
    for tower in candidate.towers:
        per_floor = candidate.prototype(tower.prototype_id).per_floor
        for kind, count in per_floor.flats_by_type.items():
            units[kind] = units.get(kind, 0) + count * tower.floors_above_stilt
    return units


def _unevaluated(rules: ResolvedRules) -> list[str]:
    """Limits that cannot be worked out yet (the airport's, without coordinates)."""
    return [limit.reason for limit in rules.height.limits
            if limit.bound is LimitBound.NOT_EVALUATED]
