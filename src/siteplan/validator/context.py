"""Everything a check needs, built once: the inputs, the land, the towers, what was drawn.

The envelope is deliberately not here. It is read only by the cross-checks, so no recomputation
can lean on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from siteplan.contracts.candidate import CandidateLayout
from siteplan.contracts.design_brief import DesignBrief
from siteplan.contracts.resolved_rules import STILT_IN_RULE_HEIGHT, ResolvedRules
from siteplan.contracts.site_model import CanonicalSiteModel
from siteplan.provenance import Provenance
from siteplan.validator import drawn as drawing
from siteplan.validator import site_geometry
from siteplan.validator.drawn import Drawn, Gate
from siteplan.validator.measure import HeightClass, TowerGeometry, classify_block, tower_geometries
from siteplan.validator.shapes import union_of_all
from siteplan.validator.site_geometry import SiteGeometry

GATE_ON_BOUNDARY_M = 0.5  # a gate this close to the boundary stands in it


def is_known(sourced) -> bool:
    """A site fact that is stated and not marked UNVERIFIED: an answer of 'unknown' is not an
    answer."""
    return (sourced is not None and sourced.value is not None
            and sourced.status is not Provenance.UNVERIFIED)


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
    entrances: tuple[Gate, ...]  # the gates that stand in the plot's boundary

    @property
    def entrance_land(self) -> BaseGeometry:
        """The ground of the entrances. Only a gate in the boundary is a way in; one drawn
        inside the plot is not, and no lane starts from it and no rule is relaxed for it."""
        return union_of_all([g.shape for g in self.entrances])

    @property
    def net(self) -> Polygon:
        return self.land.net

    @property
    def stilt_readings(self) -> list[str]:
        return self.rules.readings(STILT_IN_RULE_HEIGHT)

    def high_rise(self, reading: str) -> list[TowerGeometry]:
        """The towers that are high-rise under a reading of the stilt (a height exactly at the
        threshold counts: it is high-rise, only its table row is unsettled)."""
        by_name = self.classes.get(reading, {})
        return [t for t in self.towers if t.name in by_name and by_name[t.name].high_rise]

    def high_rise_anywhere(self) -> list[TowerGeometry]:
        names = {t.name for r in self.stilt_readings for t in self.high_rise(r)}
        return [t for t in self.towers if t.name in names]

    def low_rise(self, reading: str) -> list[TowerGeometry]:
        """The towers below the high-rise height under a reading of the stilt: Table III's, not
        Table IV's. Whether a band is modelled is a separate question (`HeightClass.state`)."""
        by_name = self.classes.get(reading, {})
        return [t for t in self.towers if t.name in by_name and not by_name[t.name].high_rise]

    def low_rise_anywhere(self) -> list[TowerGeometry]:
        names = {t.name for r in self.stilt_readings for t in self.low_rise(r)}
        return [t for t in self.towers if t.name in names]

    def low_rise_judged(self) -> list[TowerGeometry]:
        """The towers below the high-rise height, under some reading, in a band the rules model:
        the ones this validator judges on Table III, and so the ones whose other Table III rules
        must not go quietly unsaid."""
        names = {t.name for r in self.stilt_readings for t in self.low_rise(r)
                 if self.classes[r][t.name].settled}
        return [t for t in self.towers if t.name in names]


def build(site: CanonicalSiteModel, rules: ResolvedRules, brief: DesignBrief,
          candidate: CandidateLayout) -> Context | None:
    """None when the site model gives no net plot: there is nothing to judge a layout on."""
    land = site_geometry.build(site, rules)
    if land is None:
        return None
    towers = tower_geometries(candidate, brief)
    classes: dict[str, dict[str, HeightClass]] = {}
    for reading in rules.readings(STILT_IN_RULE_HEIGHT):
        made = {t.name: classify_block(rules, t, reading) for t in towers}
        if None in made.values():
            continue  # a reading this validator cannot evaluate: its checks say so
        classes[reading] = made
    drawn = drawing.read(candidate, brief)
    entrances = tuple(g for g in drawn.gates
                      if g.shape.distance(land.net.boundary) <= GATE_ON_BOUNDARY_M)
    return Context(site, rules, brief, candidate, land, towers, drawn, classes, entrances)
