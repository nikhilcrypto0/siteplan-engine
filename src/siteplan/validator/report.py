"""Putting the checks together as a ValidationReport.

The verdict is not decided here: `legal_verdict` and `program_verdict` in the contract are, so
every report is held to the same rule. This module only gathers the checks, the discrepancies and
the reasons a reader needs, and refuses nothing the contract would not.
"""

from __future__ import annotations

from siteplan.contracts.accounting import PartitionLedger, RuleLayers
from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.common import Status, digest
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.envelope import BuildableEnvelope
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.contracts.validation import (
    Accounting,
    Check,
    Discrepancy,
    Recomputed,
    TargetCheck,
    ValidationReport,
    Verdict,
    legal_verdict,
    program_verdict,
)

VALIDATOR_VERSION = "siteplan.validator 1.1: independent recomputation from the site model"


def reasons(legal: list[Check], program: list[Check], cross_checks: list[Discrepancy]) -> list[str]:
    """What stands between the candidate and a clean pass, one line each."""
    out = [f"{c.finding.rule}: {c.finding.status.value}" for c in legal
           if c.finding.status in (Status.FAIL, Status.UNVERIFIED)]
    out += [f"cross-check {d.item}: generator says {d.theirs}, recomputed {d.ours}"
            for d in cross_checks if d.blocks_pass]
    out += [f"program, {c.finding.rule}: {c.finding.status.value}" for c in program
            if c.finding.status in (Status.FAIL, Status.UNVERIFIED)]
    return out


def not_checked(legal: list[Check]) -> list[str]:
    """Every rule the validator met and does not judge, once each, beside the verdict."""
    return list(dict.fromkeys(c.finding.rule for c in legal
                              if c.finding.status is Status.NOT_CHECKED))


def assemble(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
             candidate: CandidateLayout, envelope: BuildableEnvelope | None, *,
             recomputed: Recomputed, legal: list[Check], program: list[Check],
             partition: PartitionLedger | None, partition_problems: list[str],
             rule_layers: RuleLayers | None, cross_checks: list[Discrepancy],
             design_targets: list[TargetCheck] | None = None) -> ValidationReport:
    return ValidationReport(
        candidate_ref=digest(candidate), site_ref=digest(site), rules_ref=digest(rules),
        brief_ref=digest(brief), envelope_ref=digest(envelope) if envelope is not None else None,
        validator_version=VALIDATOR_VERSION, recomputed=recomputed, legal=legal, program=program,
        design_targets=design_targets or [],
        accounting=Accounting(partition=partition, partition_problems=partition_problems,
                              rule_layers=rule_layers),
        cross_checks=cross_checks, not_checked=not_checked(legal),
        verdict=Verdict(legal=legal_verdict(legal, cross_checks),
                        program=program_verdict(program),
                        reasons=reasons(legal, program, cross_checks)))
