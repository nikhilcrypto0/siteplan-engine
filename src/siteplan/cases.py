"""Real schemes as tests of the rules: a rule is right only if every sanctioned plan passes it.

A case describes a scheme from the firm's own drawing and, once there is one, its approval
letter: the plot, each building's outline and height, and the roads. `review` runs over it the
same checker our own layouts face. A FAIL on a sanctioned plan means our rule is wrong, not
their drawing. Each case lists the FAILs already understood, with the reason, so a new one
cannot slip in unnoticed, and one that stops failing is reported too: that is a rule fixed.

Cases are client data. They live in gitignored fixtures/cases/, never in git.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from shapely.geometry import Polygon

from siteplan.checks import Building, Finding, Site, Status, check_site

Point = tuple[float, float]


class CaseBuilding(BaseModel):
    name: str
    floors: int = Field(gt=0, description="Floors above the stilt")
    stilt_height_m: float | None = None
    floor_height_m: float | None = None
    height_m: float | None = Field(None, description="As approved; wins over floors x height")
    outline: list[Point] = Field(min_length=3, description="Metres, on the drawing's own axes")


class Case(BaseModel):
    name: str
    evidence: Literal["sanctioned", "firm_drawing"]
    sources: list[str] = Field(min_length=1)
    authority: str | None = None
    gross_area_sqm: float | None = None
    net_area_sqm: float | None = None
    abutting_road_m: float | None = None
    master_plan_road_m: float | None = None
    open_space_sqm: float | None = None
    net_plot: list[Point] = Field(min_length=3)
    buildings: list[CaseBuilding] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    known_disagreements: dict[str, str] = Field(
        default_factory=dict, description="The checker's rule name, and why we think it fails"
    )

    def to_site(self) -> Site:
        buildings = tuple(
            Building(name=b.name, height_m=b.height_m, stilt_height_m=b.stilt_height_m,
                     floors=b.floors, floor_height_m=b.floor_height_m,
                     footprint=Polygon(b.outline))
            for b in self.buildings
        )
        return Site(
            gross_area_sqm=self.gross_area_sqm, net_area_sqm=self.net_area_sqm,
            abutting_road_m=self.abutting_road_m, master_plan_road_m=self.master_plan_road_m,
            open_space_sqm=self.open_space_sqm, net_plot=Polygon(self.net_plot),
            buildings=buildings, authority=self.authority,
        )


@dataclass(frozen=True)
class Review:
    case: Case
    findings: tuple[Finding, ...]

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status is Status.FAIL)

    @property
    def unexplained(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.failures if f.rule not in self.case.known_disagreements)

    @property
    def resolved(self) -> tuple[str, ...]:
        """Disagreements the case lists that no longer fail: a rule has been fixed."""
        failing = {f.rule for f in self.failures}
        return tuple(r for r in self.case.known_disagreements if r not in failing)

    @property
    def settled(self) -> bool:
        """Nothing new has failed and nothing listed has quietly stopped failing."""
        return not self.unexplained and not self.resolved


def review(case: Case) -> Review:
    return Review(case, tuple(check_site(case.to_site())))


def load_cases(folder: Path) -> list[Case]:
    return [Case.model_validate_json(p.read_text()) for p in sorted(folder.glob("*.case.json"))]


_EVIDENCE = {"sanctioned": "sanctioned plan", "firm_drawing": "the firm's drawing, not sanctioned"}


def render(reviews: list[Review]) -> str:
    lines: list[str] = []
    for r in reviews:
        failing = len(r.failures)
        lines.append(f"{r.case.name} ({_EVIDENCE[r.case.evidence]}): "
                     f"{'passes every rule' if not failing else f'{failing} rule FAILs'}")
        for f in r.failures:
            lines.append(f"  FAIL {f.rule}: {f.measured}, rule asks {f.required}")
            why = r.case.known_disagreements.get(f.rule)
            lines.append(f"       {'understood: ' + why if why else 'NEW: not yet understood'}")
        for rule in r.resolved:
            lines.append(f"  NOW PASSES {rule}: remove it from the case's known disagreements")
        lines.extend(f"  assumed: {a}" for a in r.case.assumptions)
    sanctioned = [r for r in reviews if r.case.evidence == "sanctioned"]
    passing = sum(not r.failures for r in sanctioned)
    lines += ["", f"Sanctioned plans passing every rule: {passing} of {len(sanctioned)}."]
    return "\n".join(lines)
