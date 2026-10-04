"""Made-up land, the prototype kit and quick limits for the full search's tests.

Nothing here comes from a client drawing. A site is a polygon with an access road on one side; the
rules, the envelope and the brief are made from it exactly as the pipeline makes them
(`siteplan.legal`, `siteplan.adapters`), and the kit is composed from the contract fixtures' own
flats (`optimizer_support.LIBRARY`): blocks 31 to 82 m long and 24.13 m deep.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from contract_fixtures.build import project as fixture_project
from optimizer_support import LIBRARY
from shapely.geometry import LineString, Polygon

from siteplan.adapters import brief as make_brief
from siteplan.adapters import site_model
from siteplan.contracts import BuildableEnvelope, CanonicalSiteModel, DesignBrief, ResolvedRules
from siteplan.contracts.common import Line, Provenance, Sourced, SourceKind
from siteplan.contracts.design_brief import DesignMargins, HeightIntent, HeightMode
from siteplan.legal.envelope import envelope as make_envelope
from siteplan.legal.resolve import resolve
from siteplan.optimizer import SearchContext
from siteplan.optimizer.interfaces import Budget
from siteplan.optimizer.search import FullSearchStrategy, Limits
from siteplan.prototypes import compose_library

# Quick enough for a test: three columns' starts, two heights, a few layouts laid out and judged.
FAST = Limits(offsets=3, heights=2, laid_per_profile=3, attempts_per_profile=14,
              judged_per_profile=2, per_profile_proposed=2)


@dataclass(frozen=True)
class Made:
    site: CanonicalSiteModel
    rules: ResolvedRules
    brief: DesignBrief
    envelope: BuildableEnvelope
    kit: tuple

    def context(self, seed: int = 0, budget: Budget | None = None) -> SearchContext:
        return SearchContext(self.site, self.rules, self.brief, self.envelope, self.kit, seed,
                             budget or Budget())


def margin(value: float) -> Sourced[float]:
    return Sourced[float](value=value, status=Provenance.ASSUMED_FOR_TEST,
                          source_kind=SourceKind.FIRM_STANDARD, source="made-up test margin")


def made_up(net: Polygon, *, side: str | None = "S", road_ft: float = 60, nala: LineString | None
            = None, margins: dict[str, float] | None = None, mixed_heights: bool = True,
            floors: HeightIntent | None = None, kit_ids: tuple[str, ...] | None = None) -> Made:
    """A made-up site: the plot, the side its 60 ft (or other) access road runs along, an optional
    nala, and the firm's margins if any. The brief asks for the most the law allows."""
    spec = {"boundary": net, "net": net, "side": side or "S", "road_ft": road_ft,
            "dead_end": False, "join": True, "floors": 8}
    if nala is not None:
        spec["water"] = nala
    made = fixture_project("made-up", spec)
    site = site_model(made, site_id="made-up", boundary=net)
    if nala is not None:
        site.water[0].lines = [Line(points=list(nala.coords))]
    if side is None:  # nobody has said which side the access road runs along
        unknown = site.access.side.model_copy(update={"value": None,
                                                      "status": Provenance.UNVERIFIED})
        site = site.model_copy(update={"access": site.access.model_copy(update={"side": unknown})})
    design = make_brief(made)
    intent = floors or HeightIntent(notation=design.height_intent.notation,
                                    mode=HeightMode.MAX_LEGAL,
                                    mixed_heights_allowed=mixed_heights)
    design = design.model_copy(update={"height_intent": intent})
    if margins:
        design = design.model_copy(update={"design_margins": DesignMargins(
            **{name: margin(value) for name, value in margins.items()})})
    rules = resolve(site)
    kit = compose_library(LIBRARY, design.program.unit_mix.value)
    if kit_ids:
        kit = [p for p in kit if p.id in kit_ids]
    return Made(site, rules, design, make_envelope(site, rules), tuple(kit))


@cache
def rectangle() -> Made:
    """200 x 120 m, the access road along the south side."""
    from shapely.geometry import box  # noqa: PLC0415

    return made_up(box(0, 0, 200, 120))


def strategy(limits: Limits = FAST, **given) -> FullSearchStrategy:
    return FullSearchStrategy(limits=limits, **given)


@cache
def proposal_on_the_rectangle():
    """The quick search on the rectangle, once: the tests that only read a proposal share it."""
    made = rectangle()
    return strategy().propose(made.context())
