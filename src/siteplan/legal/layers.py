"""The regulatory layers of one site, each with what it permits.

A layer is geometry the law cares about and a list of uses it forbids, allows or allows on a
condition. Layers overlap and are never summed. Where the text leaves a use open (roads and fire
lanes inside a setback, visitors' bays in one, a road inside a water buffer) the permission is
CONDITIONAL and names the open reading it rests on: it is never simply allowed. The clauses come
from ResolvedRules, so a layer says what the law it was resolved with says.
"""

from __future__ import annotations

from shapely.geometry import Polygon
from shapely.ops import unary_union

from siteplan.contracts.accounting import (
    LayerKind,
    Permit,
    PhysicalUse,
    RuleLayers,
)
from siteplan.contracts.common import Basis, Provenance, shapes_from
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK, ResolvedRules
from siteplan.legal.bands import BandLand
from siteplan.legal.frontage import front_runs
from siteplan.legal.readings import ROAD_IN_WATER_BUFFER, VISITOR_PARKING_IN_SETBACK

LAW = {"basis": Basis.LEGAL_RULE, "status": Provenance.VERIFIED}


def _permit(use: PhysicalUse, permit: Permit, *, condition: str | None = None,
            reading: str | None = None) -> dict:
    return {"use": use, "permit": permit, "condition": condition, "interpretation_ref": reading}


def _layer(layer_id: str, kind: LayerKind, zone, clause: str, permits: list[dict], *,
           applies_to: str | None = None, reading: str | None = None, **over) -> dict:
    return {"id": layer_id, "kind": kind, "shapes": shapes_from(zone), "clause": clause,
            "applies_to": applies_to, "interpretation_ref": reading, "permits": permits,
            "area_sqm": zone.area, **LAW, **over}


def _setback_permits(rules: ResolvedRules) -> list[dict]:
    """What a high-rise's setback permits. Roads and fire lanes in it rest on the reading
    circulation_in_setback; a visitors' bay on visitor_parking_in_setback. It says nothing of a
    club house: that is a lower block, which keeps its own band's setback (Table III, stream A2),
    not this tower's."""
    roads = {"permit": Permit.CONDITIONAL, "reading": CIRCULATION_IN_SETBACK,
             "condition": "only under the reading that circulation may run inside the setback; "
                          "the text does not settle it"}
    return [
        _permit(PhysicalUse.TOWER, Permit.FORBIDDEN),
        _permit(PhysicalUse.SURFACE_PARKING, Permit.CONDITIONAL,
                reading=VISITOR_PARKING_IN_SETBACK,
                condition=f"visitors' parking only ({rules.parking.visitors_fraction.clause}): "
                          "a side or rear setback wider than the rule names, the green strip "
                          "left out, never the front setback; no other parking"),
        _permit(PhysicalUse.ROAD, **roads),
        _permit(PhysicalUse.FIRE_HARDSTANDING, **roads),
        _permit(PhysicalUse.RAMP, Permit.CONDITIONAL,
                condition=f"a side or rear setback only, after leaving the width kept for "
                          f"fire-fighting vehicles ({rules.parking.ramp_in_setbacks.clause})")]


def _front_zone(net: Polygon, side: str | None, setback_m: float, setback_zone):
    """The front part of a setback: what lies within the setback of the stretches facing the
    access side. None when no stretch is known to face it."""
    runs = front_runs(net, side)
    if not runs:
        return None
    swept = unary_union([run.buffer(setback_m, cap_style="flat") for run in runs])
    return setback_zone.intersection(swept)


def rule_layers(rules: ResolvedRules, net: Polygon, lands: list[BandLand], water: list,
                side: str | None) -> RuleLayers:
    """The setback, green strip and no-ramp layers of every band and the water buffers.

    `water` is (water body id, its buffer clipped to the net plot) for each buffer that reaches
    the plot; `side` is the side the access road runs along, or None when it is not known.
    """
    layers: list[dict] = []
    strip_m = rules.green_strip.width_m.value
    for land in lands:
        band, key = land.band, land.key
        zone = net.difference(land.inset)
        layers.append(_layer(
            f"setback {key}", LayerKind.SETBACK, zone,
            f"{band.clause}; {rules.setbacks.measured_on.clause}", _setback_permits(rules),
            applies_to=key, reading=CIRCULATION_IN_SETBACK, status=band.status))
        if band.setback_m >= rules.green_strip.where_setback_from_m.value:
            strip = net.difference(net.buffer(-strip_m, join_style="mitre"))
            layers.append(_layer(
                f"green strip {key}", LayerKind.GREEN_STRIP_ZONE, strip,
                rules.green_strip.width_m.clause,
                [_permit(PhysicalUse.GREEN_STRIP, Permit.ALLOWED),
                 _permit(PhysicalUse.TOWER, Permit.FORBIDDEN),
                 _permit(PhysicalUse.SURFACE_PARKING, Permit.FORBIDDEN),
                 _permit(PhysicalUse.ROAD, Permit.CONDITIONAL,
                         condition="only where the entrance crosses it")],
                applies_to=key))
        layers.append(_ramp_layer(rules, net, zone, key, band.setback_m, side))
    layers += [_water_layer(rules, water_id, zone) for water_id, zone in water]
    return RuleLayers(layers=layers)


def _ramp_layer(rules: ResolvedRules, net: Polygon, zone, key: str, setback_m: float,
                side: str | None) -> dict:
    """No ramp in the front setback. Where the front cannot be told (no access side, or no
    stretch facing it) every side is treated as the front, which is stricter, and the layer is
    UNVERIFIED."""
    front = _front_zone(net, side, setback_m, zone)
    clause = rules.parking.ramp_in_setbacks.clause
    if front is not None:
        return _layer(f"no ramp, front setback {key}", LayerKind.RAMP_FORBIDDEN, front, clause,
                      [_permit(PhysicalUse.RAMP, Permit.FORBIDDEN)], applies_to=key)
    return _layer(
        f"no ramp, front setback {key}", LayerKind.RAMP_FORBIDDEN, zone, clause,
        [_permit(PhysicalUse.RAMP, Permit.FORBIDDEN,
                 condition="the side the access road runs along is not known, so every side is "
                           "treated as the front")],
        applies_to=key, status=Provenance.UNVERIFIED)


def _water_layer(rules: ResolvedRules, water_id: str, zone) -> dict:
    """A water buffer: no building in it; a road or fire lane only under the open reading; it may
    count as organised open space, never as the setback (rule 3(a)(iii)(3))."""
    roads = {"permit": Permit.CONDITIONAL, "reading": ROAD_IN_WATER_BUFFER,
             "condition": "only under the reading that a road is not building activity; the text "
                          "does not settle it"}
    return _layer(
        f"water buffer {water_id}", LayerKind.WATER_BUFFER, zone,
        rules.water.buffer_m_by_class.clause,
        [_permit(PhysicalUse.TOWER, Permit.FORBIDDEN),
         _permit(PhysicalUse.CLUB_HOUSE, Permit.FORBIDDEN),
         _permit(PhysicalUse.SOFT_OPEN_SPACE, Permit.ALLOWED,
                 condition="it may count as organised open space, never as the setback"),
         _permit(PhysicalUse.ROAD, **roads), _permit(PhysicalUse.FIRE_HARDSTANDING, **roads)],
        reading=ROAD_IN_WATER_BUFFER)
