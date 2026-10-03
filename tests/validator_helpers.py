"""Shared by the validator tests: a contract fixture's inputs, and copies edited to plant a
violation. The fixtures are made-up land; nothing here touches client data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from contract_fixtures import load
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from siteplan.contracts import (
    BuildableEnvelope,
    CandidateLayout,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    ValidationReport,
    digest,
)
from siteplan.contracts.common import Shape, Status, shapes_from
from siteplan.contracts.validation import Check
from siteplan.validator import validate


@dataclass(frozen=True)
class Inputs:
    site: CanonicalSiteModel
    rules: ResolvedRules
    brief: DesignBrief
    candidate: CandidateLayout
    envelope: BuildableEnvelope | None

    def report(self, envelope: bool = False) -> ValidationReport:
        return validate(self.site, self.rules, self.brief, self.candidate,
                        self.envelope if envelope else None)

    def edited(self, edit: Callable[[CandidateLayout], None]) -> Inputs:
        """A copy whose candidate has been edited in place by `edit`."""
        candidate = self.candidate.model_copy(deep=True)
        edit(candidate)
        return replace(self, candidate=candidate)

    def with_rules(self, edit: Callable[[ResolvedRules], None]) -> Inputs:
        """A copy with edited rules; the candidate is restated as made for them."""
        rules = self.rules.model_copy(deep=True)
        edit(rules)
        return replace(self, rules=rules).restated()

    def with_site(self, edit: Callable[[CanonicalSiteModel], None]) -> Inputs:
        site = self.site.model_copy(deep=True)
        edit(site)
        rules = self.rules.model_copy(update={"site_ref": digest(site)})
        return replace(self, site=site, rules=rules).restated()

    def with_brief(self, edit: Callable[[DesignBrief], None]) -> Inputs:
        brief = self.brief.model_copy(deep=True)
        edit(brief)
        return replace(self, brief=brief).restated()

    def restated(self) -> Inputs:
        """The candidate says it was made for exactly these site, rules and brief."""
        candidate = self.candidate.model_copy(update={
            "site_ref": digest(self.site), "rules_ref": digest(self.rules),
            "brief_ref": digest(self.brief)})
        return replace(self, candidate=candidate)


def fixture(name: str) -> Inputs:
    return Inputs(load(name, "CanonicalSiteModel"), load(name, "ResolvedRules"),
                  load(name, "DesignBrief"), load(name, "CandidateLayout"),
                  load(name, "BuildableEnvelope"))


def select(rules: ResolvedRules, interpretation_id: str, reading: str) -> None:
    """Make the rules choose one reading of an open question (in place)."""
    interpretation = rules.interpretation(interpretation_id)
    assert reading in interpretation.alternatives, (interpretation_id, reading)
    interpretation.selected = reading


def check(report: ValidationReport, rule: str) -> Check:
    found = [c for c in report.legal + report.program if c.finding.rule == rule]
    assert len(found) == 1, (rule, [c.finding.rule for c in report.legal])
    return found[0]


def status(report: ValidationReport, rule: str) -> Status:
    return check(report, rule).finding.status


def statuses(report: ValidationReport) -> dict[str, Status]:
    return {c.finding.rule: c.finding.status for c in report.legal}


def tower(candidate: CandidateLayout, name: str):
    return next(t for t in candidate.towers if t.name == name)


def footprint(candidate: CandidateLayout, name: str) -> Polygon:
    return candidate.placed_footprint(tower(candidate, name))


def move_tower(candidate: CandidateLayout, name: str, dx: float, dy: float) -> None:
    """Move a tower and restate its footprint, as a faithful generator would."""
    t = tower(candidate, name)
    t.x, t.y = t.x + dx, t.y + dy
    t.footprint = Shape.from_shapely(candidate.placed_footprint(t))


def set_floors(candidate: CandidateLayout, name: str, floors: int) -> None:
    tower(candidate, name).floors_above_stilt = floors


def shape(geometry: BaseGeometry) -> Shape:
    return Shape.from_shapely(geometry)


def shapes(geometry: BaseGeometry) -> list[Shape]:
    return shapes_from(geometry)


def rectangle(x0: float, y0: float, x1: float, y1: float) -> Shape:
    return Shape.from_shapely(box(x0, y0, x1, y1))
