"""The RuleLayers, recomputed: the regulatory geometry of this candidate on this site.

Setbacks, block gaps, the tender's clear ground and turns, water buffers, the green strip, the
open space that qualifies, and where a ramp or a bay may not be. Layers may overlap and are never
summed. Where a zone depends on how an open question is read, one layer is made per distinct
zone and names the question; roads and fire lanes in a setback are CONDITIONAL on
circulation_in_setback, never simply allowed.
"""

from __future__ import annotations

from collections.abc import Callable

from shapely.geometry.base import BaseGeometry

from siteplan.contracts.accounting import (
    LayerKind,
    Permission,
    Permit,
    PhysicalUse,
    RuleLayer,
    RuleLayers,
)
from siteplan.contracts.common import Basis, Provenance, shapes_from
from siteplan.contracts.resolved_rules import (
    CIRCULATION_IN_SETBACK,
    FIRE_TURNING_RADIUS,
    MIXED_HEIGHT_SPACING,
    OPEN_SPACE_BASIS,
    STILT_IN_RULE_HEIGHT,
)
from siteplan.validator.context import Context
from siteplan.validator.fire import clear_band, reached
from siteplan.validator.open_space import certain_ground
from siteplan.validator.parking import cellar_setback_m
from siteplan.validator.shapes import union_of_all
from siteplan.validator.turning import round_block, turning_for
from siteplan.validator.zones import (
    gap_zones,
    green_strip_zone,
    ramp_zones,
    setback_zone,
)

U, P = PhysicalUse, Permit
SAME_ZONE_SQM = 0.01  # two zones that differ by less than this are the same zone
CONDITIONAL = {"permit": P.CONDITIONAL, "interpretation_ref": CIRCULATION_IN_SETBACK,
               "condition": "only under the reading that circulation may run inside the "
                            "setback; not settled by the text"}
FORBID_BUILT = (U.TOWER, U.CLUB_HOUSE, U.OTHER_BUILT)


def _forbid(*uses: PhysicalUse) -> list[Permission]:
    return [Permission(use=u, permit=P.FORBIDDEN) for u in uses]


def _layer(layer_id: str, kind: LayerKind, zone: BaseGeometry, clause: str, *,
           open_reading: str | None = None, applies_to: str | None = None,
           permits: list[Permission] | None = None, basis: Basis = Basis.LEGAL_RULE,
           status: Provenance = Provenance.VERIFIED) -> RuleLayer:
    if open_reading:
        basis, status = Basis.UNRESOLVED_INTERPRETATION, Provenance.UNVERIFIED
    return RuleLayer(id=layer_id, kind=kind, shapes=shapes_from(zone), clause=clause, basis=basis,
                     status=status, interpretation_ref=open_reading, applies_to=applies_to,
                     permits=permits or [], area_sqm=zone.area)


def _by_stilt(ctx: Context, make: Callable[[str], BaseGeometry | None]
              ) -> list[tuple[list[str], BaseGeometry]]:
    """The zone under each reading of the stilt, readings that give the same zone grouped."""
    groups: list[tuple[list[str], BaseGeometry]] = []
    for reading in ctx.stilt_readings:
        zone = make(reading)
        if zone is None or zone.is_empty:
            continue
        for names, other in groups:
            if other.symmetric_difference(zone).area < SAME_ZONE_SQM:
                names.append(reading)
                break
        else:
            groups.append(([reading], zone))
    return groups


def _per_stilt(ctx: Context, base: str, kind: LayerKind, clause: str,
               make: Callable[[str], BaseGeometry | None], reading: str | None = None,
               **kw) -> list[RuleLayer]:
    """One layer per distinct zone; a zone that depends on the stilt names that question,
    otherwise `reading`, the question the layer's use rests on, if any."""
    groups = _by_stilt(ctx, make)
    out = []
    for names, zone in groups:
        many = len(groups) > 1
        out.append(_layer(f"{base} [{'/'.join(names)}]" if many else base, kind, zone, clause,
                          open_reading=STILT_IN_RULE_HEIGHT if many else reading, **kw))
    return out


def _setback_layers(ctx: Context) -> list[RuleLayer]:
    clause = f"{ctx.rules.setbacks.measured_on.clause}; {ctx.rules.setbacks.front.clause}"
    permits = [*_forbid(U.TOWER, U.SURFACE_PARKING), Permission(use=U.ROAD, **CONDITIONAL),
               Permission(use=U.FIRE_HARDSTANDING, **CONDITIONAL),
               Permission(use=U.RAMP, permit=P.CONDITIONAL,
                          condition="side or rear setback only, leaving 7 m (13(c)(vii))")]
    return _per_stilt(ctx, "setback", LayerKind.SETBACK, clause,
                      lambda r: setback_zone(ctx, r), permits=permits)


def _gap_layers(ctx: Context) -> list[RuleLayer]:
    zones: dict[str, list[BaseGeometry]] = {}
    for reading in ctx.stilt_readings:
        for spacing in ctx.rules.readings(MIXED_HEIGHT_SPACING):
            for pair, zone in gap_zones(ctx, reading, spacing):
                zones.setdefault(pair, []).append(zone)
    out = []
    for pair, found in zones.items():
        widest = union_of_all(found)
        if widest.is_empty:
            continue
        differs = any(widest.symmetric_difference(z).area >= SAME_ZONE_SQM for z in found)
        out.append(_layer(f"block gap {pair}", LayerKind.BLOCK_GAP, widest,
                          ctx.rules.spacing.clause, applies_to=pair,
                          open_reading=MIXED_HEIGHT_SPACING if differs else None,
                          permits=_forbid(*FORBID_BUILT)))
    return out


def _fire_layers(ctx: Context) -> list[RuleLayer]:
    clause = ctx.rules.fire.clear_width_m.clause
    lane = ctx.rules.fire.clear_width_m.value
    out = []
    for t in ctx.fire_held_anywhere():
        out.append(_layer(f"fire band {t.name}", LayerKind.FIRE_CLEAR_BAND,
                          clear_band(t.footprint, lane), clause, applies_to=t.name,
                          permits=_forbid(*FORBID_BUILT, U.SURFACE_PARKING, U.HARD_AMENITY,
                                          U.SOFT_OPEN_SPACE)))
        readings = ctx.rules.readings(FIRE_TURNING_RADIUS)
        for reading in readings:
            turning = turning_for(ctx.rules, reading)
            if turning is None:
                continue
            sectors = union_of_all(round_block(t.footprint, turning))
            out.append(_layer(f"turning {t.name} [{reading}]", LayerKind.TURNING_SECTOR, sectors,
                              clause, applies_to=t.name, open_reading=FIRE_TURNING_RADIUS,
                              permits=_forbid(*FORBID_BUILT, U.SURFACE_PARKING, U.HARD_AMENITY)))
    route = reached(ctx)
    if not route.is_empty:
        out.append(_layer("fire access route", LayerKind.FIRE_ACCESS_ROUTE, route, clause))
    return out


def _other_layers(ctx: Context) -> list[RuleLayer]:
    out = []
    for zone in ctx.land.water:
        on_site = zone.keep_out.intersection(ctx.net)
        if not on_site.is_empty:
            out.append(_layer(f"water buffer {zone.id}", LayerKind.WATER_BUFFER, on_site,
                              ctx.rules.water.buffer_m_by_class.clause,
                              permits=_forbid(*FORBID_BUILT)))
    gates = ctx.entrance_land

    def strip(reading: str) -> BaseGeometry | None:
        zone = green_strip_zone(ctx, reading)
        return None if zone is None else zone.difference(gates)

    spacing = ctx.rules.readings(MIXED_HEIGHT_SPACING)[0]
    out += _per_stilt(ctx, "green strip", LayerKind.GREEN_STRIP_ZONE,
                      ctx.rules.green_strip.width_m.clause, strip)
    out += _per_stilt(ctx, "qualifying open space", LayerKind.QUALIFYING_OPEN_SPACE,
                      ctx.rules.open_space.share.clause,
                      lambda r: union_of_all(list(certain_ground(ctx, r, spacing).pockets)),
                      reading=OPEN_SPACE_BASIS)
    return out


def _ramp_and_bay_layers(ctx: Context) -> list[RuleLayer]:
    lane = ctx.rules.fire.clear_width_m.value

    def bays(reading: str) -> BaseGeometry:
        zone = setback_zone(ctx, reading)
        bands = [clear_band(t.footprint, lane) for t in ctx.fire_held(reading)]
        return union_of_all([zone, *bands, ctx.drawn.paved_land, ctx.drawn.fire_hardstanding])

    out = _per_stilt(ctx, "ramps forbidden", LayerKind.RAMP_FORBIDDEN,
                     ctx.rules.parking.ramp_single_min_m.clause,
                     lambda r: ramp_zones(ctx, r)[0], permits=_forbid(U.RAMP))
    out += _per_stilt(ctx, "bays forbidden", LayerKind.BAYS_FORBIDDEN,
                      "G.O.168 rule 13(b)(iii); " + ctx.rules.fire.clear_width_m.clause, bays,
                      permits=_forbid(U.SURFACE_PARKING))
    need = (cellar_setback_m(ctx.rules, ctx.net.area, ctx.drawn.cellar_levels)
            if ctx.drawn.cellar_levels else None)
    if need is not None:
        out.append(_layer("cellar setback", LayerKind.CELLAR_SETBACK,
                          ctx.net.difference(ctx.net.buffer(-need)),
                          ctx.rules.parking.cellar_setback_by_site_sqm.clause))
    return out


def recompute_layers(ctx: Context) -> RuleLayers:
    layers = [*_setback_layers(ctx), *_gap_layers(ctx), *_fire_layers(ctx), *_other_layers(ctx),
              *_ramp_and_bay_layers(ctx)]
    unique = {layer.id: layer for layer in layers}
    return RuleLayers(layers=list(unique.values()))
