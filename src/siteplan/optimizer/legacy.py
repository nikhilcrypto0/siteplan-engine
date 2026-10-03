"""The prototype generator as a strategy, LEGACY: today's search behind the Strategy interface, so
the optimizer core can run, judge and compare it like any other.

The generator itself is untouched. The wrapper turns the contracts into what it takes
(adapters.join_project makes the project file, and runner.load_plot and runner.site_facts read it
exactly as production does), works out the starting floors from the law's metres (floors.py)
instead of a typed number, runs heights.search_heights, and turns each option into a
CandidateLayout (adapters.candidate_from_option). Its replies are the legacy ones: the same
options, in the same order, with the same numbers (tests/test_optimizer_legacy.py).

What it does not use: the buildable envelope and the tower prototypes (it lays its own towers
from a flat library), and per-tower heights (every tower of an option has the option's height).
It runs under one reading of each open question it knows (the stilt, circulation in the setback);
`for_readings` makes one strategy per combination the rules leave open, so each candidate says
which readings it was made under (`interpretation_basis`) and a validator can judge it under all.

The time budget is checked before each height, so a run overruns it by at most one height's
search. What was found at the heights tried is still the best of them; the rest are listed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product

from shapely.geometry import Polygon
from shapely.ops import polygonize, unary_union

from siteplan import rules as law
from siteplan.adapters import Readings, candidate_from_option, join_project
from siteplan.contracts import CanonicalSiteModel, ResolvedRules, digest
from siteplan.contracts.common import Status
from siteplan.contracts.design_brief import HeightIntent, HeightMode
from siteplan.contracts.resolved_rules import CIRCULATION_IN_SETBACK, STILT_IN_RULE_HEIGHT
from siteplan.heights import HeightSearch, heights_to_try, search_heights
from siteplan.layout import LayoutRequest, missing_strategies
from siteplan.library import FlatLibrary
from siteplan.optimizer.floors import READINGS as STILT_READINGS
from siteplan.optimizer.floors import STILT_COUNTED, assess_floors, feasible_floors
from siteplan.optimizer.interfaces import Proposal, SearchContext
from siteplan.runner import load_plot, site_facts, why_none
from siteplan.site_amenities import AmenityLibrary

NAME = "LEGACY"
CIRCULATION_READINGS = ("allowed", "not_allowed")  # the readings of circulation_in_setback it knows
# The generator's own defaults (LayoutRequest): the stilt counts, circulation stays out of the
# setback.
DEFAULT_READINGS = {STILT_IN_RULE_HEIGHT: STILT_COUNTED, CIRCULATION_IN_SETBACK: "not_allowed"}


@dataclass(frozen=True)
class LegacyRun:
    """A run's proposal and the generator's own account of it (every height with its verdict),
    which the pinned Dhulapally baseline is made of."""

    proposal: Proposal
    found: HeightSearch | None  # None when nothing was tried
    request: LayoutRequest | None


class LegacyStrategy:
    name = NAME

    def __init__(self, library: FlatLibrary, amenities: AmenityLibrary | None = None, *,
                 readings: Mapping[str, str] | None = None):
        self.library = library
        self.amenities = amenities
        self.readings = dict(DEFAULT_READINGS if readings is None else readings)

    @classmethod
    def for_readings(cls, rules: ResolvedRules, library: FlatLibrary,
                     amenities: AmenityLibrary | None = None) -> list[LegacyStrategy]:
        """One strategy per combination of the readings the rules leave open: an interpretation
        selected ALL gives each of its readings, a selected one gives itself."""
        return [cls(library, amenities, readings={STILT_IN_RULE_HEIGHT: stilt,
                                                  CIRCULATION_IN_SETBACK: circulation})
                for stilt, circulation in product(rules.readings(STILT_IN_RULE_HEIGHT),
                                                  rules.readings(CIRCULATION_IN_SETBACK))]

    def propose(self, context: SearchContext) -> Proposal:
        return self.run(context).proposal

    def run(self, context: SearchContext) -> LegacyRun:
        site, rules, brief = context.site, context.rules, context.brief
        self._check_readings(rules)
        stop = _cannot_run(site, brief.height_intent)
        if stop:
            return LegacyRun(Proposal(NAME, notes=(stop,)), None, None)
        stilt = self.readings[STILT_IN_RULE_HEIGHT]
        floors = None
        if brief.height_intent.mode is not HeightMode.FIXED:
            open_counts = feasible_floors(rules, brief, None, stilt, site=site)
            if not open_counts:
                return LegacyRun(Proposal(NAME, notes=(_no_count(rules, brief, stilt, site),)),
                                 None, None)
            floors = open_counts[-1].floors  # the most the law allows: where the search starts

        project = join_project(site, brief, Readings(dict(self.readings),
                                                     rules.jurisdiction.when_open),
                               floors_for_max=floors)
        request = project.layout
        heights = heights_for(request, brief.height_intent)
        if not heights:
            return LegacyRun(Proposal(NAME, notes=(
                "no height to try: the generator lays out high-rise blocks only, from "
                f"{law.HIGH_RISE_THRESHOLD_M:g} m (Table III is not encoded)",)), None, request)
        plot, _ = load_plot(project, None)
        keep_out = water_keep_out(site, rules)
        found = search_heights(plot, self.library, request, site_facts(project, keep_out),
                               self.amenities, heights=heights, stop=context.budget.expired)
        tried = {result.floors for result in found.results}
        untried = [h for h in heights if h not in tried]
        refs = (digest(site), digest(rules), digest(brief))
        candidates = tuple(
            candidate_from_option(
                option, plot, candidate_id=f"{NAME.lower()}-{'-'.join(self.readings.values())}-{i}",
                site_ref=refs[0], rules_ref=refs[1], brief_ref=refs[2],
                readings=dict(self.readings), access_side=site.access.side.value,
                keep_out=keep_out, library_note=self.library.note,
            ).model_copy(update={"strategy": NAME, "seed": context.seed})
            for i, option in enumerate(found.options, 1))
        return LegacyRun(Proposal(NAME, candidates, _notes(found, untried),
                                  budget_exhausted=bool(untried)), found, request)

    def _check_readings(self, rules: ResolvedRules) -> None:
        known = {STILT_IN_RULE_HEIGHT: STILT_READINGS, CIRCULATION_IN_SETBACK: CIRCULATION_READINGS}
        for interpretation, reading in self.readings.items():
            if reading not in known.get(interpretation, ()) or reading not in (
                    rules.interpretation(interpretation).alternatives):
                raise ValueError(f"the legacy generator has no reading '{reading}' of "
                                 f"{interpretation} that these rules carry")


def water_keep_out(site: CanonicalSiteModel, rules: ResolvedRules) -> Polygon | None:
    """The land no block may stand on: each water body's rule 3(a)(ii) buffer round the lines
    drawn for it, and any channel those lines close (as runner.load_water, from the site
    model's own lines and the law's buffer in ResolvedRules)."""
    zones = []
    for water in site.water:
        drawn = unary_union([line.to_shapely() for line in water.lines])
        buffer_m = rules.water.buffer_m_by_class.value[water.water_class.value]
        zones.append(unary_union([drawn.buffer(buffer_m), *polygonize(drawn)]))
    return unary_union(zones) if zones else None


def _cannot_run(site: CanonicalSiteModel, intent: HeightIntent) -> str | None:
    """Why the generator cannot be asked at all, before anything is drawn."""
    if site.net_plot is None:
        return ("the net plot is not known (where the surrendered land lies is the architect's "
                "to say): nothing can be laid out")
    if site.net_plot.value.holes:
        return "the generator lays towers on a plot without holes"
    if not intent.has_stilt:
        return "the generator always plans a stilt"
    for water in site.water:
        if not water.lines:
            return (f"{water.id} has no drawn lines, so its buffer cannot be kept clear: "
                    "nothing can be laid out")
    return None


def _no_count(rules: ResolvedRules, brief, stilt: str, site: CanonicalSiteModel) -> str:
    first = next((check.reason for option in assess_floors(rules, brief, None, stilt, site=site)
                  for check in option.limits if check.status is Status.FAIL), None)
    return (f"the law leaves no high-rise floor count open under the '{stilt}' reading of the "
            f"stilt, within the brief's height intent{': ' + first if first else ''}")


def heights_for(request: LayoutRequest, intent: HeightIntent) -> list[int]:
    """The heights to try, top down. A fixed height is itself. Otherwise, from one above the
    most the law allows (so the report can say what stops it) down to the lowest high-rise,
    within the brief's range and its lowest floors. Below the high-rise height the generator
    cannot draw, so those heights are left out."""
    if intent.mode is HeightMode.FIXED:
        tried = [request.floors]
    else:
        low, high = intent.floors_range if intent.mode is HeightMode.RANGE else (1, math.inf)
        low = max(low, intent.min_floors_above_stilt or 1)
        tried = [h for h in heights_to_try(request.model_copy(update={"maximise": True}))
                 if low <= h <= high]
    return [h for h in tried
            if request.model_copy(update={"floors": h}).rule_height_m >= law.HIGH_RISE_THRESHOLD_M]


def _notes(found: HeightSearch, untried: list[int]) -> tuple[str, ...]:
    notes = []
    if found.options:
        notes += missing_strategies(found.options)
    elif found.results:
        notes.append(why_none(found))
    if untried:
        notes.append("stopped on the time budget; heights not tried: "
                     + ", ".join(f"stilt + {h}" for h in untried))
    return tuple(notes)
