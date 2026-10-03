"""Everything a check needs, built once: the inputs, the land, the towers, what was drawn.

The envelope is deliberately not here. It is read only by the cross-checks, so no recomputation
can lean on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon

from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT, ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.validator import drawn as drawing
from siteplan.validator import site_geometry
from siteplan.validator.drawn import Drawn
from siteplan.validator.measure import HeightClass, TowerGeometry, classify, tower_geometries
from siteplan.validator.site_geometry import SiteGeometry


@dataclass(frozen=True)
class Context:
    site: CanonicalSiteModel
    rules: ResolvedRules
    brief: DesignBrief
    candidate: CandidateLayout
    land: SiteGeometry
    towers: tuple[TowerGeometry, ...]
    drawn: Drawn
    classes: dict[str, dict[str, HeightClass]]  # stilt reading -> tower name -> its band

    @property
    def net(self) -> Polygon:
        return self.land.net

    @property
    def stilt_readings(self) -> list[str]:
        return self.rules.readings(STILT_IN_RULE_HEIGHT)

    def tower(self, name: str) -> TowerGeometry:
        return next(t for t in self.towers if t.name == name)

    def high_rise(self, reading: str) -> list[TowerGeometry]:
        """The towers that are high-rise under a reading of the stilt (a height exactly at the
        threshold counts: it is high-rise, only its table row is unsettled)."""
        by_name = self.classes.get(reading, {})
        return [t for t in self.towers if t.name in by_name and by_name[t.name].high_rise]

    def high_rise_anywhere(self) -> list[TowerGeometry]:
        names = {t.name for r in self.stilt_readings for t in self.high_rise(r)}
        return [t for t in self.towers if t.name in names]

    @property
    def tallest(self) -> TowerGeometry | None:
        return max(self.towers, key=lambda t: t.physical_height_m, default=None)


def build(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
          candidate: CandidateLayout) -> Context | None:
    """None when the site model gives no net plot: there is nothing to judge a layout on."""
    land = site_geometry.build(site, rules)
    if land is None:
        return None
    towers = tower_geometries(candidate, brief)
    classes: dict[str, dict[str, HeightClass]] = {}
    for reading in rules.readings(STILT_IN_RULE_HEIGHT):
        heights = {t.name: t.rule_height_m(reading) for t in towers}
        if None in heights.values():
            continue  # a reading this validator cannot evaluate: its checks say so
        classes[reading] = {name: classify(rules, h) for name, h in heights.items()}
    return Context(site, rules, brief, candidate, land, towers, drawing.read(candidate), classes)
