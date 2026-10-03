"""The independent validator: one candidate, judged from the site model, the rules and the brief.

`validate` recomputes what it judges (the net plot, each tower's footprint and heights, the
Table IV row, setbacks, gaps, roads, fire access, open space, parking, the ledger) from the
site model and the candidate's own geometry. What the generator says about itself (its claims,
its partition, its footprints) and what an envelope says are compared with that recomputation,
never relied on: they only ever add discrepancies.

A site model with no usable net plot, a candidate holding a number that is not a number, or a
shape the geometry library cannot resolve gets a report that says so and cannot pass
(refusals.py).
"""

from __future__ import annotations

from collections.abc import Callable

from shapely.errors import GEOSException, TopologicalError

from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.common import Shape
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.envelope import BuildableEnvelope
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.contracts.validation import Check, Discrepancy, Recomputed, ValidationReport
from siteplan.validator import (
    accounting,
    blocks,
    clubhouse,
    context,
    cross_checks,
    fire,
    land_checks,
    layers,
    open_space,
    parking,
    program,
    refusals,
    report,
    roads,
)
from siteplan.validator.context import Context
from siteplan.validator.ground import Ground
from siteplan.validator.refusals import LIBRARY_MESSAGE_CHARS


def _present(*checks: Check | None) -> list[Check]:
    return [c for c in checks if c is not None]


def _guarded(what: str, build: Callable[[], list[Check]]) -> list[Check]:
    """One group of checks. If the geometry library cannot measure it, the group is one UNVERIFIED
    check saying so and every other group keeps its verdicts: a shape the library chokes on must
    not erase a FAIL found elsewhere."""
    try:
        return build()
    except (GEOSException, TopologicalError) as error:
        return [refusals.library_check(error, what)]


def _legal_checks(ctx: Context, ground: Ground, ledger: accounting.Ledger
                  ) -> tuple[list[Check], dict[str, float]]:
    found: dict[str, float] = {}

    def with_quantities(build: Callable[[], tuple[list[Check], dict[str, float]]]
                        ) -> Callable[[], list[Check]]:
        def run() -> list[Check]:
            checks, quantities = build()
            found.update(quantities)
            return checks
        return run

    def open_space_group() -> tuple[list[Check], dict[str, float]]:
        space, quantities = open_space.open_space_checks(ctx)
        return space + open_space.pocket_checks(ctx), quantities

    groups: list[tuple[str, Callable[[], list[Check]]]] = [
        ("Net plot and heights", lambda: [
            land_checks.net_plot_check(ctx), *blocks.height_class_checks(ctx),
            *_present(blocks.plot_size_check(ctx), blocks.road_width_check(ctx)),
            *blocks.height_limit_checks(ctx), *_present(blocks.tdr_check(ctx)),
            *_present(blocks.prototype_height_check(ctx))]),
        ("Setbacks and gaps", lambda: blocks.setback_checks(ctx) + blocks.spacing_checks(ctx)),
        ("Roads", lambda: roads.road_checks(ctx, ground)
         + _present(roads.setback_circulation_check(ctx))),
        ("Fire access", lambda: fire.fire_checks(ctx, ground)),
        ("Open space", with_quantities(open_space_group)),
        ("Green strip and water", lambda: [land_checks.green_strip_check(ctx),
                                           *_present(land_checks.water_check(ctx))]),
        ("Club house", lambda: [clubhouse.club_house_check(ctx),
                                *_present(clubhouse.club_setback_check(ctx)),
                                *clubhouse.club_gap_checks(ctx),
                                *_present(clubhouse.large_project_check(ctx))]),
        ("Parking", with_quantities(lambda: parking.parking_checks(ctx, ground))),
        ("Egress", lambda: _present(land_checks.egress_check(ctx))),
        ("Every square metre once", lambda: [accounting.ledger_check(ctx, ledger)])]
    legal = [check for what, build in groups for check in _guarded(what, build)]
    return legal, found


def _quantities(ctx: Context, found: dict[str, float], ledger: accounting.Ledger
                ) -> dict[str, float]:
    own = ctx.site.ownership
    return {"net_plot_sqm": ctx.net.area, "net_ownership_sqm": own.net_sqm.value,
            "gross_ownership_sqm": own.gross_sqm.value,
            "tower_floor_sqm": sum(t.built_up_sqm for t in ctx.towers),
            "club_house_built_up_sqm": ctx.drawn.club.area * ctx.drawn.club_floors,
            "units": float(clubhouse.units_of(ctx)),
            "water_buffer_on_site_sqm": ctx.land.keep_out_on_site.area,
            "unallocated_sqm": sum(e.area_sqm for e in ledger.ledger.entries
                                   if e.use.value == "UNALLOCATED"), **found}


def validate(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
             candidate: CandidateLayout, envelope: BuildableEnvelope | None = None
             ) -> ValidationReport:
    """Judge one candidate. Every candidate the contract admits gets a report; one that cannot
    be measured gets a report that is not a pass."""
    bad = refusals.non_finite(candidate.model_dump())
    if bad:
        return refusals.unmeasurable(site, rules, brief, candidate, envelope,
                                     refusals.numbers_check(bad))
    broken = refusals.unusable_rules(rules)
    if broken:
        return refusals.unmeasurable(site, rules, brief, candidate, envelope,
                                     refusals.rules_check(broken))
    try:
        return _judge(site, rules, brief, candidate, envelope)
    except (GEOSException, TopologicalError) as error:
        return refusals.unmeasurable(site, rules, brief, candidate, envelope,
                                     refusals.library_check(error))


def _judge(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
           candidate: CandidateLayout, envelope: BuildableEnvelope | None) -> ValidationReport:
    ctx = context.build(site, rules, brief, candidate)
    if ctx is None:
        return refusals.no_net_plot(site, rules, brief, candidate, envelope)
    far = refusals.too_large(ctx)
    if far is not None:
        return refusals.unmeasurable(site, rules, brief, candidate, envelope, far)
    ground = Ground(ctx)
    ledger = accounting.recompute(ctx)
    legal, found = _legal_checks(ctx, ground, ledger)
    units = program.units_by_type(ctx.towers)
    counting = min((v for k, v in found.items() if k.startswith("open_space_counting_sqm")),
                   default=0.0)
    discrepancies = _discrepancies(ctx, ground, ledger, envelope, legal, found, counting, units)
    try:
        rule_layers = layers.recompute_layers(ctx)
    except (GEOSException, TopologicalError) as error:
        rule_layers = None
        discrepancies.append(Discrepancy(
            item="rule layers", source="generator", theirs="not compared",
            ours=f"could not be recomputed: {type(error).__name__}", blocks_pass=False))
    return report.assemble(
        site, rules, brief, candidate, envelope,
        recomputed=Recomputed(towers=blocks.tower_measures(ctx), pairs=blocks.pair_measures(ctx),
                              quantities=_quantities(ctx, found, ledger), units_by_type=units),
        legal=legal, program=program.program_checks(brief, candidate, ctx.towers, rules),
        partition=ledger.ledger,
        partition_problems=ledger.problems + [
            f"claimed partition: {d.theirs}" for d in discrepancies
            if d.item == "partition invariant"],
        rule_layers=rule_layers, cross_checks=discrepancies)


def _discrepancies(ctx: Context, ground: Ground, ledger: accounting.Ledger,
                   envelope: BuildableEnvelope | None, legal: list[Check],
                   found: dict[str, float], counting: float, units: dict[str, int]
                   ) -> list[Discrepancy]:
    """What the generator and an envelope say, against what was recomputed. A claim that cannot
    be compared (the library chokes on a shape it draws) never costs a verdict: it is recorded,
    and blocks only where the claim is the ledger itself, which then cannot be trusted."""
    candidate = ctx.candidate
    groups: list[tuple[str, Callable[[], list[Discrepancy]]]] = [
        ("references", lambda: cross_checks.references(
            ctx.site, ctx.rules, ctx.brief, candidate, envelope)),
        ("shapes", lambda: cross_checks.flaws(ctx.towers, ctx.drawn)),
        ("footprints", lambda: cross_checks.footprints(ctx.towers)),
        ("claims", lambda: cross_checks.claims(candidate, legal)),
        ("metrics", lambda: cross_checks.metrics(
            ctx, clubhouse.built_up_sqm(ctx), counting, units)),
        ("cars", lambda: cross_checks.cars(candidate, found.get("parking_cars", 0.0))),
        ("road widths", lambda: roads.width_discrepancies(ctx, ground)),
        ("gates", lambda: fire.gate_discrepancies(ctx)),
        ("cellars", lambda: cross_checks.cellars(ctx)),
        ("partition", lambda: cross_checks.partition(
            candidate, ledger, Shape.from_shapely(ctx.net)))]
    if envelope is not None:
        groups.append(("envelope", lambda: cross_checks.envelope_checks(ctx, envelope)))
    out: list[Discrepancy] = []
    for what, build in groups:
        # the claimed ledger is read by the contract's own code, which a malformed ring stops
        catching: tuple[type[Exception], ...] = (GEOSException, TopologicalError)
        if what == "partition":
            catching += (ValueError,)
        try:
            out += build()
        except catching as error:
            out.append(Discrepancy(
                item=f"{what} could not be compared",
                source="envelope" if what == "envelope" else "generator",
                theirs="as the generator or envelope states it",
                ours=f"{type(error).__name__}: {str(error)[:LIBRARY_MESSAGE_CHARS]}",
                blocks_pass=what == "partition"))
    return out
