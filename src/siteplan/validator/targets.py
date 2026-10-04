"""Design targets: what a layout keeps in hand above each legal minimum.

A row shows the legal minimum the legal check used, the target the brief's design margin puts
above it (the firm's standard, or the engine's assumption of no margin; never law) and what the
layout provides: the tightest setback, the tightest gap between two blocks, the narrowest road,
the organised open space under each reading of its area, and parking. The rows sit beside the
verdict and never in it: the legal checks go on judging the legal minimum alone. Where the firm
set a margin and a layout misses its target, that is a program finding, never a legal one.
"""

from __future__ import annotations

from siteplan.contracts.common import Status
from siteplan.contracts.resolved_rules import OPEN_SPACE_BASIS, STILT_IN_RULE_HEIGHT
from siteplan.contracts.validation import Check, Family, TargetCheck, TargetItem
from siteplan.validator import blocks, roads
from siteplan.validator.context import Context
from siteplan.validator.ground import Ground
from siteplan.validator.open_space import expected_requirement
from siteplan.validator.readings import plain

MARGIN_CLAUSE = "the brief's design margins (the firm's standard, never law)"


def design_targets(ctx: Context, ground: Ground, found: dict[str, float]) -> list[TargetCheck]:
    margins = ctx.brief.design_margins
    rows: list[TargetCheck] = []
    towers = blocks.tower_measures(ctx)
    for reading in ctx.stilt_readings:
        held = [t for t in towers if reading in t.required_setback_m_by_reading]
        if held:
            t = min(held, key=lambda t: t.setback_m - t.required_setback_m_by_reading[reading])
            need = t.required_setback_m_by_reading[reading]
            rows.append(TargetCheck(
                item=TargetItem.SETBACK, subject=t.name, readings={STILT_IN_RULE_HEIGHT: reading},
                unit="m", legal_minimum=need, target=margins.setback_target_m(need),
                provided=t.setback_m, basis=margins.basis("setback_extra_m")))
    pairs = [p for p in blocks.pair_measures(ctx) if p.required_m is not None]
    if pairs:
        p = min(pairs, key=lambda p: p.gap_m - p.required_m)
        rows.append(TargetCheck(
            item=TargetItem.TOWER_GAP, subject=f"{p.a}/{p.b}", unit="m",
            legal_minimum=p.required_m, target=margins.gap_target_m(p.required_m),
            provided=p.gap_m, basis=margins.basis("tower_gap_extra_m"),
            note="the larger of the gaps the open readings ask"))
    narrow = roads.narrowest_road(ctx, ground)
    if narrow is not None:
        need = ctx.rules.circulation.internal_road_m.value
        rows.append(TargetCheck(
            item=TargetItem.ROAD_WIDTH, subject=narrow[0], unit="m", legal_minimum=need,
            target=margins.road_width_target_m(need), provided=narrow[1],
            basis=margins.basis("road_width_extra_m")))
    counted = [v for k, v in found.items() if k.startswith("open_space_counting_sqm")]
    share = ctx.rules.open_space.share.value
    for basis, asked in ctx.rules.open_space.requirement_sqm_by_reading.items():
        if not counted:
            break
        need = max(asked, expected_requirement(ctx, basis) or 0.0)
        rows.append(TargetCheck(
            item=TargetItem.OPEN_SPACE, readings={OPEN_SPACE_BASIS: basis}, unit="m²",
            legal_minimum=need, target=margins.open_space_target_sqm(need, share),
            provided=min(counted), basis=margins.basis("open_space_extra_fraction"),
            note="the least that counts under any reading of the stilt and the spacing"))
    required = [v for k, v in found.items() if k.startswith("parking_required_sqm")]
    if required and "parking_cars" in found:
        need = max(required)
        per_car = ctx.rules.parking.measurement.sqm_per_car
        rows.append(TargetCheck(
            item=TargetItem.PARKING, unit="m²", legal_minimum=need,
            target=margins.parking_target_sqm(need), provided=found["parking_cars"] * per_car,
            basis=margins.basis("parking_extra_fraction"),
            note=f"cars laid out at {per_car:g} m² each, against the stricter Table V column"))
    return rows


def margin_check(ctx: Context, rows: list[TargetCheck]) -> Check | None:
    """Where the firm set a margin: whether the layout keeps it. A program finding only."""
    if not ctx.brief.design_margins.any_set:
        return None
    set_rows = [r for r in rows if r.margin > 0]
    missed = [r for r in set_rows if not r.meets_target]
    shown = "; ".join(f"{r.item.value}{f' {r.subject}' if r.subject else ''}: "
                      f"{r.provided:,.2f} {r.unit} against a target of {r.target:,.2f}"
                      for r in missed) or f"all {len(set_rows)} targets kept"
    return plain(Family.PROGRAM, "Design margins", Status.FAIL if missed else Status.PASS,
                 shown, "the legal minimum plus the firm's margin", MARGIN_CLAUSE,
                 "The legal verdict judges the legal minimum alone; this is the firm's target.")
