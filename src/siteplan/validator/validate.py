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


def _present(*checks: Check | None) -> list[Check]:
    return [c for c in checks if c is not None]


def _legal_checks(ctx: Context, ground: Ground, ledger: accounting.Ledger
                  ) -> tuple[list[Check], dict[str, float]]:
    legal = [land_checks.net_plot_check(ctx), *blocks.height_class_checks(ctx)]
    legal += _present(blocks.plot_size_check(ctx), blocks.road_width_check(ctx))
    legal += blocks.height_limit_checks(ctx) + _present(blocks.tdr_check(ctx))
    legal += blocks.setback_checks(ctx) + blocks.spacing_checks(ctx)
    legal += roads.road_checks(ctx, ground)
    legal += _present(roads.setback_circulation_check(ctx))
    legal += fire.fire_checks(ctx, ground)
    space, space_quantities = open_space.open_space_checks(ctx)
    legal += space + open_space.pocket_checks(ctx)
    legal += [land_checks.green_strip_check(ctx)]
    legal += _present(land_checks.water_check(ctx))
    legal += [clubhouse.club_house_check(ctx)]
    parked, parking_quantities = parking.parking_checks(ctx, ground)
    legal += parked
    legal += _present(land_checks.egress_check(ctx))
    legal += [accounting.ledger_check(ctx, ledger)]
    return legal, {**space_quantities, **parking_quantities}


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
    ground = Ground(ctx)
    ledger = accounting.recompute(ctx)
    legal, found = _legal_checks(ctx, ground, ledger)
    units = program.units_by_type(ctx.towers)
    counting = min((v for k, v in found.items() if k.startswith("open_space_counting_sqm")),
                   default=0.0)
    discrepancies: list[Discrepancy] = [
        *cross_checks.references(site, rules, brief, candidate, envelope),
        *cross_checks.flaws(ctx.towers, ctx.drawn), *cross_checks.footprints(ctx.towers),
        *cross_checks.claims(candidate, legal),
        *cross_checks.metrics(ctx, clubhouse.built_up_sqm(ctx), counting, units),
        *cross_checks.cars(candidate, found.get("parking_cars", 0.0)),
        *roads.width_discrepancies(ctx, ground), *fire.gate_discrepancies(ctx),
        *cross_checks.cellars(ctx),
        *cross_checks.partition(candidate, ledger, Shape.from_shapely(ctx.net))]
    if envelope is not None:
        discrepancies += cross_checks.envelope_checks(ctx, envelope)
    return report.assemble(
        site, rules, brief, candidate, envelope,
        recomputed=Recomputed(towers=blocks.tower_measures(ctx), pairs=blocks.pair_measures(ctx),
                              quantities=_quantities(ctx, found, ledger), units_by_type=units),
        legal=legal, program=program.program_checks(brief, candidate, ctx.towers, rules),
        partition=ledger.ledger,
        partition_problems=ledger.problems + [
            f"claimed partition: {d.theirs}" for d in discrepancies
            if d.item == "partition invariant"],
        rule_layers=layers.recompute_layers(ctx), cross_checks=discrepancies)
