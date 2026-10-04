"""Made-up inputs for the optimizer's tests: the contract fixtures with one fact changed, and
hand-built prototypes and candidates whose properties the tests know exactly.

Nothing here comes from a client drawing. The prototypes are the contract fixtures' own block
repeated: a row of (2BHK | core | 3BHK) modules, four flats a floor to each core.
"""

from __future__ import annotations

from functools import cache

from contract_fixtures import load
from contract_fixtures.rules_and_envelope import resolved_rules
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from siteplan.adapters import candidate_from_option
from siteplan.contracts import CandidateLayout, DesignBrief, ResolvedRules, TowerPrototype, digest
from siteplan.contracts.common import (
    Finding,
    Provenance,
    Shape,
    Sourced,
    SourceKind,
    Status,
    shapes_from,
)
from siteplan.contracts.design_brief import HeightIntent, HeightMode
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK, STILT_IN_RULE_HEIGHT
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.contracts.validation import (
    Check,
    Family,
    ProgramVerdict,
    ValidationReport,
    legal_verdict,
)
from siteplan.library import FlatLibrary
from siteplan.optimizer import LegacyRun, LegacyStrategy, Proposal, SearchContext

LIBRARY = FlatLibrary(  # the contract fixtures' own flats
    flats=[{"name": "2A", "bhk": "2BHK", "width_m": 10.0, "depth_m": 11.0, "saleable_sqft": 1190},
           {"name": "3A", "bhk": "3BHK", "width_m": 13.5, "depth_m": 11.0,
            "saleable_sqft": 1690}],
    core_width_m=7.5)
MODULE_LENGTH_M = 31.0  # one (2BHK | core | 3BHK) module along the block
CORRIDOR_M = 2.13
FLAT_DEPTH_M = 11.0
HALF_DEPTH_M = FLAT_DEPTH_M + CORRIDOR_M / 2
MODULE_SALEABLE_SQFT = 2 * (1190 + 1690)  # per floor, per core


def fixture(name: str = "rectangle") -> tuple[CanonicalSiteModel, ResolvedRules, DesignBrief]:
    return (load(name, "CanonicalSiteModel"), load(name, "ResolvedRules"),
            load(name, "DesignBrief"))


def with_dead_end(site: CanonicalSiteModel, ends_at_plot: bool | None) -> CanonicalSiteModel:
    """The site with the architect's answer to 'does the access road end at the plot'."""
    answer = Sourced[bool | None](
        value=ends_at_plot, source_kind=SourceKind.ARCHITECT, source="made-up test answer",
        status=Provenance.UNVERIFIED if ends_at_plot is None else Provenance.USER_CONFIRMED)
    return site.model_copy(update={"access": site.access.model_copy(update={"dead_end": answer})})


def rules_with_dead_end(ends_at_plot: bool | None, name: str = "rectangle"
                        ) -> tuple[CanonicalSiteModel, ResolvedRules]:
    site = with_dead_end(fixture(name)[0], ends_at_plot)
    return site, resolved_rules(site)


def intent(brief: DesignBrief, **changes) -> DesignBrief:
    """The brief with another height intent (validated, so a FIXED one names its floors)."""
    fields = {"notation": brief.height_intent.notation, **changes}
    return brief.model_copy(update={"height_intent": HeightIntent(**fields)})


def max_legal(brief: DesignBrief) -> DesignBrief:
    return intent(brief, mode=HeightMode.MAX_LEGAL)


@cache
def legacy_run(name: str = "rectangle", stilt: str = "counted", maximise: bool = True
               ) -> LegacyRun:
    """The generator run on a contract fixture, as the wrapped strategy runs it. Cached, since a
    run takes seconds: a test must not change what it returns."""
    site, rules, brief = fixture(name)
    readings = {STILT_IN_RULE_HEIGHT: stilt, CIRCULATION_IN_SETBACK: "not_allowed"}
    return LegacyStrategy(LIBRARY, readings=readings).run(
        SearchContext(site, rules, max_legal(brief) if maximise else brief))


@cache
def generators_layouts(name: str = "rectangle") -> tuple[list, list[CandidateLayout]]:
    """Every option the generator found at every height of a fixture, and each as a candidate."""
    site, rules, brief = fixture(name)
    run = legacy_run(name)
    options = [o for r in run.found.results if r.search for o in r.search.options]
    plot = Polygon(site.net_plot.value.outer)
    readings = {STILT_IN_RULE_HEIGHT: "counted", CIRCULATION_IN_SETBACK: "not_allowed"}
    return options, [candidate_from_option(
        o, plot, candidate_id=f"{i}-{o.strategy}", site_ref=digest(site), rules_ref=digest(rules),
        brief_ref=digest(brief), readings=readings) for i, o in enumerate(options)]


def module_prototype(cores: int, prototype_id: str | None = None) -> TowerPrototype:
    """A block of `cores` modules end to end: 4 flats a floor, 2 BHK and 3 BHK, to each core."""
    left = -MODULE_LENGTH_M * cores / 2
    flats, core_zones = [], []
    for i in range(cores):
        x0 = left + i * MODULE_LENGTH_M
        for y0, y1 in ((CORRIDOR_M / 2, HALF_DEPTH_M), (-HALF_DEPTH_M, -CORRIDOR_M / 2)):
            flats.append((box(x0, y0, x0 + 10.0, y1), "2A", "2BHK", 1190))
            flats.append((box(x0 + 17.5, y0, x0 + 31.0, y1), "3A", "3BHK", 1690))
        core_zones.append(box(x0 + 10.0, -HALF_DEPTH_M, x0 + 17.5, HALF_DEPTH_M))
    footprint = box(left, -HALF_DEPTH_M, -left, HALF_DEPTH_M)
    own = sum(shape.area for shape, *_ in flats)
    corridor = footprint.difference(unary_union([*core_zones, *(f for f, *_ in flats)]))
    by_type = {"2BHK": 2 * cores, "3BHK": 2 * cores}
    return TowerPrototype(
        id=prototype_id or f"made-up-{cores}-core", family="SINGLE_CORE" if cores == 1
        else "TWO_CORE_LARGE", source_kind=SourceKind.ENGINE_DEFAULT, source="made-up test block",
        footprint=Shape.from_shapely(footprint), length_m=MODULE_LENGTH_M * cores,
        depth_m=2 * HALF_DEPTH_M, cores=cores,
        modules=[{"id": f"m{i}", "type_id": t, "category": c, "shape": Shape.from_shapely(f),
                  "saleable_sqft": s} for i, (f, t, c, s) in enumerate(flats, 1)],
        core_zones=[{"shape": Shape.from_shapely(z), "lifts": 2, "stairs": 1}
                    for z in core_zones],
        corridor=shapes_from(corridor),
        per_floor={"flats": 4 * cores, "flats_by_type": by_type,
                   "gross_floor_sqm": footprint.area, "flats_own_sqm": own,
                   "common_core_sqm": footprint.area - own,
                   "saleable_sqft": MODULE_SALEABLE_SQFT * cores})


def tower(name: str, prototype: TowerPrototype, x: float, y: float, floors: int,
          rotation_deg: float = 0.0) -> dict:
    """A PlacedTower as a dict, its footprint worked out from the prototype and the placement."""
    local = prototype.footprint.to_shapely()
    world = affinity.translate(affinity.rotate(local, rotation_deg, origin=(0, 0)), x, y)
    return {"name": name, "prototype_id": prototype.id, "x": x, "y": y,
            "rotation_deg": rotation_deg, "floors_above_stilt": floors,
            "footprint": Shape.from_shapely(world)}


def candidate(candidate_id: str, towers: list[dict], prototypes: list[TowerPrototype], *,
              open_space_sqm: float = 0.0, claims: list[Finding] | None = None,
              refs: tuple[str, str, str] = ("site", "rules", "brief"),
              strategy: str = "made-up") -> CandidateLayout:
    """A candidate holding exactly these towers, `open_space_sqm` of open space and these claims.
    `refs` are the digests of the site model, rules and brief it claims to be made for."""
    site_ref, rules_ref, brief_ref = refs
    side = open_space_sqm ** 0.5
    return CandidateLayout(
        candidate_id=candidate_id, site_ref=site_ref, rules_ref=rules_ref, brief_ref=brief_ref,
        strategy=strategy, prototypes_used=prototypes, towers=towers,
        program={"open_space": [Shape.from_shapely(box(0, 0, side, side))] if side else []},
        generator_claims=claims or [])


def refs_of(site, rules, brief) -> tuple[str, str, str]:
    return digest(site), digest(rules), digest(brief)


class Clock:
    """A clock that ticks `step` seconds every time it is read, so a budget runs out after a
    known number of checks whatever the machine does."""

    def __init__(self, step: float = 1.0):
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Fixed:
    """A strategy that proposes exactly these candidates (and takes `takes` seconds of `clock`)."""

    def __init__(self, candidates, name: str = "FIXED", *, notes=(), exhausted: bool = False,
                 clock: Clock | None = None, takes: float = 0.0):
        self.candidates, self.name, self.notes = list(candidates), name, tuple(notes)
        self.exhausted, self.clock, self.takes = exhausted, clock, takes

    def propose(self, context) -> Proposal:
        if self.clock is not None:
            self.clock.advance(self.takes)
        return Proposal(self.name, tuple(self.candidates), self.notes, self.exhausted)


class Scripted:
    """A validator whose legal verdict is set by candidate id (PASS unless said). A value may be
    a tuple of verdicts, one for each time that candidate is judged (the last one repeats)."""

    def __init__(self, verdicts: dict | None = None, clock: Clock | None = None,
                 takes: float = 0.0):
        self.verdicts, self.clock, self.takes = verdicts or {}, clock, takes
        self.calls: list[str] = []

    def validate(self, site, rules, brief, candidate, envelope=None) -> ValidationReport:
        times = self.calls.count(candidate.candidate_id)
        self.calls.append(candidate.candidate_id)
        if self.clock is not None:
            self.clock.advance(self.takes)
        said = self.verdicts.get(candidate.candidate_id, Status.PASS)
        status = said[min(times, len(said) - 1)] if isinstance(said, tuple) else said
        legal = [Check(family=Family.OTHER, finding=Finding(
            "Scripted check", status, "scripted", "scripted", "made-up test validator"))]
        return ValidationReport(
            candidate_ref=digest(candidate), site_ref=digest(site), rules_ref=digest(rules),
            brief_ref=digest(brief), validator_version="scripted test validator", legal=legal,
            verdict={"legal": legal_verdict(legal, []), "program": ProgramVerdict.MET})


class Claims:
    """A test validator whose verdict is the candidate's own claims (FAIL when a claim fails),
    for tests of the optimizer's mechanics on made-up blocks. The optimizer's real validator
    (siteplan.validator) judges such blocks, with no roads or open space, as the illegal layouts
    they are, so it cannot stand in for a verdict the test needs to set."""

    def validate(self, site, rules, brief, candidate, envelope=None) -> ValidationReport:
        legal = [Check(family=Family.OTHER, finding=claim) for claim in candidate.generator_claims]
        legal = legal or [Check(family=Family.OTHER, finding=Finding(
            "No claim", Status.PASS, "none", "none", "made-up test validator"))]
        return ValidationReport(
            candidate_ref=digest(candidate), site_ref=digest(site), rules_ref=digest(rules),
            brief_ref=digest(brief), validator_version="claims test validator", legal=legal,
            verdict={"legal": legal_verdict(legal, []), "program": ProgramVerdict.MET})
