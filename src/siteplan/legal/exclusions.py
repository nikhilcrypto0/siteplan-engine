"""The statutory exclusions of one site: land where no building may stand, whatever the design.

Only what the law fixes in place is excluded: a water body's buffer, recomputed here from the
lines the survey draws for it and the width the rules give its class, and an HT corridor where a
survey feature gives one. Land is never excluded for being narrow or awkward. What cannot be
excluded for want of an input (water named but its lines not read, an HT line marked with no
corridor) is reported as a finding, not guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from siteplan.contracts.common import Finding, Status, shapes_from
from siteplan.contracts.envelope import Exclusion, ExclusionKind
from siteplan.contracts.resolved_rules import ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel, Water

HT_CLAUSE = "G.O.168 rule 3(c) (electrical lines: a safety distance from high tension lines)"


@dataclass(frozen=True)
class Exclusions:
    items: list[Exclusion] = field(default_factory=list)
    water: list[tuple[str, BaseGeometry]] = field(default_factory=list)  # id, buffer on the plot
    union: BaseGeometry | None = None
    findings: list[Finding] = field(default_factory=list)


def exclusions(site: CanonicalSiteModel, rules: ResolvedRules, net: Polygon) -> Exclusions:
    items: list[Exclusion] = []
    water: list[tuple[str, BaseGeometry]] = []
    findings: list[Finding] = []
    clause = rules.water.buffer_m_by_class.clause
    for body in site.water:
        zone = _water_zone(body, rules.water.buffer_m_by_class.value[body.water_class.value])
        if zone is None:
            findings.append(Finding(
                f"Water body {body.id}", Status.UNVERIFIED, "its lines were not read from the "
                f"survey ({body.drawn_as})", "the buffer of its class kept free", clause,
                "not excluded: nothing is guessed about where the water lies"))
            continue
        on_plot = zone.intersection(net)
        if on_plot.is_empty:
            findings.append(Finding(f"Water body {body.id}", Status.INFO,
                                    "its buffer does not reach the net plot", "-", clause))
            continue
        water.append((body.id, on_plot))
        items.append(Exclusion(id=f"buffer-{body.id}", kind=ExclusionKind.WATER_BUFFER,
                               shapes=shapes_from(on_plot), clause=clause, source_ref=body.id))
    for number, feature in enumerate((f for f in site.features if _is_ht(f)), 1):
        item, finding = _ht_corridor(feature, number, net)
        items += [item] if item else []
        findings += [finding] if finding else []
    zones = [zone for _, zone in water] + [shape.to_shapely() for item in items
                                           if item.kind is ExclusionKind.HT_CORRIDOR
                                           for shape in item.shapes]
    return Exclusions(items, water, unary_union(zones) if zones else None, findings)


def _ht_corridor(feature, number: int, net: Polygon) -> tuple[Exclusion | None, Finding | None]:
    """The corridor a survey feature gives, on the net plot; a finding when it gives none."""
    if not feature.shapes:
        return None, Finding(
            "HT line", Status.UNVERIFIED, feature.text or "an HT line is marked",
            "the safety distance from the line kept free", HT_CLAUSE,
            "not excluded: the survey gives no corridor and the distance depends on the line")
    corridor = unary_union([shape.to_shapely() for shape in feature.shapes]).intersection(net)
    if corridor.is_empty:
        return None, Finding("HT line", Status.INFO, "its corridor does not reach the net plot",
                             "-", HT_CLAUSE)
    return Exclusion(id=f"ht-corridor-{number}", kind=ExclusionKind.HT_CORRIDOR,
                     shapes=shapes_from(corridor), clause=HT_CLAUSE,
                     source_ref=feature.source or None), None


def _is_ht(feature) -> bool:
    return feature.kind == "HT_LINE" or (feature.kind == "MARK"
                                         and feature.text.lower().startswith("ht line"))


def _water_zone(body: Water, buffer_m: float) -> BaseGeometry | None:
    """The buffer round the lines drawn for a water body, and whatever channel they close; None
    when no line was read."""
    parts = [LineString(line.points).buffer(buffer_m) for line in body.lines]
    parts += [shape.to_shapely() for shape in body.channel]
    return unary_union(parts) if parts else None
