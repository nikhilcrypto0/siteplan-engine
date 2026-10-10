"""Made-up land, the prototype kit and quick limits for the full search's tests.

Nothing here comes from a client drawing. A site is a polygon with an access road on one side; the
rules, the envelope and the brief are made from it exactly as the pipeline makes them
(`siteplan.legal`, `siteplan.adapters`), and the kit is composed from the contract fixtures' own
flats (`optimizer_support.LIBRARY`): blocks 31 to 82 m long and 24.13 m deep. A made-up slim block,
13.13 m deep, may be added to it (`slim_prototype`).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from contract_fixtures.build import L_PLOT
from contract_fixtures.build import project as fixture_project
from optimizer_support import LIBRARY
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from siteplan.adapters import brief as make_brief
from siteplan.adapters import site_model
from siteplan.contracts import (
    BuildableEnvelope,
    CanonicalSiteModel,
    DesignBrief,
    ResolvedRules,
    TowerPrototype,
)
from siteplan.contracts.common import Line, Provenance, Shape, Sourced, SourceKind, shapes_from
from siteplan.contracts.design_brief import DesignMargins, HeightIntent, HeightMode
from siteplan.legal.envelope import envelope as make_envelope
from siteplan.legal.resolve import resolve
from siteplan.optimizer import SearchContext
from siteplan.optimizer.interfaces import Budget
from siteplan.optimizer.search import FullSearchStrategy, Limits
from siteplan.prototypes import compose_library
from siteplan.rules import COVERED_PARKING_RAISE_M as RAISE_M

STILT_TOPS_OUT_M = 3.0  # the made-up firm's stilt floor, from the ground (see made_up)

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
    # A made-up firm whose stilt floor tops out 3 m up: the 0.15 m raise the rules give a stilt
    # floor (NBC Part 3 12.1.2) and a 2.85 m stilt, so every height lands where these tests
    # reckon it; test_heights_from_the_ground holds what the raise changes.
    standards = design.firm_standards
    stilt = standards.stilt_height_m.model_copy(update={"value": STILT_TOPS_OUT_M - RAISE_M})
    design = design.model_copy(update={"firm_standards": standards.model_copy(
        update={"stilt_height_m": stilt})})
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
    return made_up(box(0, 0, 200, 120))


def slim_prototype() -> TowerPrototype:
    """A made-up single-loaded block: a 2BHK and a 3BHK on one side of a corridor, a core between
    them, 31 m long and 13.13 m deep, two flats a floor. Made up for the tests, as narrow as a
    block that a 24 m arm can take between Table III's 5 m side setbacks."""
    corridor, flat = 2.13, 11.0
    half = (flat + corridor) / 2
    x = (-15.5, -5.5, 2.0, 15.5)  # 2BHK, the 7.5 m core, 3BHK along the block
    flats = [(box(x[0], corridor - half, x[1], half), "2A", "2BHK", 1190),
             (box(x[2], corridor - half, x[3], half), "3A", "3BHK", 1690)]
    footprint, core = box(x[0], -half, x[3], half), box(x[1], -half, x[2], half)
    own = sum(f.area for f, *_ in flats)
    passage = footprint.difference(core).difference(unary_union([f for f, *_ in flats]))
    return TowerPrototype(
        id="slim-2", family="SINGLE_CORE_SMALL", source_kind=SourceKind.ENGINE_DEFAULT,
        source="made-up test prototype", footprint=Shape.from_shapely(footprint), length_m=31.0,
        depth_m=2 * half, cores=1,
        modules=[{"id": f"m{i}", "type_id": t, "category": c, "shape": Shape.from_shapely(f),
                  "saleable_sqft": s} for i, (f, t, c, s) in enumerate(flats, 1)],
        core_zones=[{"shape": Shape.from_shapely(core), "lifts": 1, "stairs": 1}],
        corridor=shapes_from(passage),
        per_floor={"flats": 2, "flats_by_type": {"2BHK": 1, "3BHK": 1},
                   "gross_floor_sqm": footprint.area, "flats_own_sqm": own,
                   "common_core_sqm": footprint.area - own, "saleable_sqft": 1190 + 1690})


@cache
def l_plot(slim: bool = False) -> Made:
    """The contract fixtures' L-plot (150 x 100 m with a 24 m arm, 60 m long, at its north-west
    corner), the access road along the south side; with the slim block in the kit when asked."""
    made = made_up(L_PLOT)
    return Made(made.site, made.rules, made.brief, made.envelope,
                (*made.kit, slim_prototype()) if slim else made.kit)


@cache
def proposal_on_the_l_plot(slim: bool = False):
    """The quick search on the L-plot, once for each kit: the tests that only read it share it."""
    return strategy().propose(l_plot(slim).context())


def strategy(limits: Limits = FAST, **given) -> FullSearchStrategy:
    return FullSearchStrategy(limits=limits, **given)


@cache
def proposal_on_the_rectangle():
    """The quick search on the rectangle, once: the tests that only read a proposal share it."""
    made = rectangle()
    return strategy().propose(made.context())
