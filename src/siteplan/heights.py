"""The height search: every height from one above the legal limit down, the law first, then the
ground.

A height the rules allow is not yet a height the site can hold: taller blocks need wider setbacks,
gaps and roads, and more parking. So each height is tested on its own, top down. The legal test
is the road width Table IV asks for that height, the plot size, and NBC 4.6(b)'s dead end above
30 m; a height that fails it is not drawn, and the rule that stops it is recorded. A height that
passes is laid out with every requirement active (layout.search); if nothing passes the
checker, the reasons its candidates failed are recorded instead.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from shapely.geometry import Polygon

from siteplan import rules
from siteplan.findings import Finding, Status
from siteplan.layout import (
    LayoutOption,
    LayoutRequest,
    Search,
    SiteFacts,
    pick_distinct,
    search,
)
from siteplan.library import FlatLibrary
from siteplan.site_amenities import AmenityLibrary

AIRPORT_CLAUSE = "G.O.168 rule 3(d) (airport and Air Force height limits)"


@dataclass(frozen=True)
class HeightResult:
    floors: int
    height_m: float
    legal: tuple[Finding, ...]
    search: Search | None = None  # None when the law already rules the height out

    @property
    def legal_fails(self) -> list[Finding]:
        return [f for f in self.legal if f.status is Status.FAIL]

    @property
    def legal_open(self) -> list[Finding]:
        return [f for f in self.legal if f.status is Status.UNVERIFIED]

    @property
    def options(self) -> list[LayoutOption]:
        return self.search.options if self.search is not None else []

    @property
    def verdict(self) -> str:
        if self.legal_fails:
            return "FAIL (law)"
        if self.search is None:
            return "NOT TRIED"
        return "PASS" if self.options else "FAIL (site)"

    def reasons(self, limit: int = 3) -> list[str]:
        """What stops this height, or what stays open about it."""
        if self.legal_fails:
            return [f"{f.rule}: {f.measured}; needs {f.required}" for f in self.legal_fails]
        if self.search is None or self.options:
            return [f"{f.rule}: {f.measured}" for f in self.legal_open]
        if self.search.problem:
            return [self.search.problem]
        counted = Counter(r.reasons[0] for r in self.search.rejected if r.reasons)
        return [f"{reason} ({n} candidate{'s' if n > 1 else ''})"
                for reason, n in counted.most_common(limit)]


@dataclass
class HeightSearch:
    results: list[HeightResult] = field(default_factory=list)
    options: list[LayoutOption] = field(default_factory=list)

    @property
    def max_legal_floors(self) -> int | None:
        allowed = [r.floors for r in self.results if not r.legal_fails]
        return max(allowed, default=None)

    @property
    def max_feasible_floors(self) -> int | None:
        feasible = [r.floors for r in self.results if r.options]
        return max(feasible, default=None)


def lowest_high_rise_floors(request: LayoutRequest) -> int:
    return math.ceil((rules.HIGH_RISE_THRESHOLD_M - request.stilt_height_m)
                     / request.floor_height_m - 1e-9)


def legal_findings(floors: int, request: LayoutRequest, facts: SiteFacts,
                   plot: Polygon) -> list[Finding]:
    """What the law says about this height before any block is drawn."""
    height = request.stilt_height_m + floors * request.floor_height_m
    band = rules.band_for_height(height)
    found = []
    road = facts.master_plan_road_m or facts.abutting_road_m
    if band is None:
        found.append(Finding("Abutting road width", Status.NOT_CHECKED, f"{height:g} m",
                             "Table IV rows", rules.TABLE_IV_CLAUSE))
    elif road is None:
        found.append(Finding("Abutting road width", Status.UNVERIFIED, "not given",
                             f">= {band.min_road_m:g} m", rules.TABLE_IV_CLAUSE))
    else:
        found.append(Finding(
            "Abutting road width", Status.PASS if road + 1e-6 >= band.min_road_m else Status.FAIL,
            f"{road:.2f} m", f">= {band.min_road_m:g} m for {height:g} m", rules.TABLE_IV_CLAUSE))
    area = plot.area
    found.append(Finding(
        "Plot size for high-rise",
        Status.PASS if area >= rules.MIN_HIGH_RISE_PLOT_SQM else Status.FAIL,
        f"{area:,.0f} m²", f">= {rules.MIN_HIGH_RISE_PLOT_SQM:,.0f} m²",
        rules.MIN_HIGH_RISE_PLOT_CLAUSE))
    limit = rules.DEAD_END_MAX_HEIGHT_M
    if height > limit + 1e-6:
        dead = facts.road_dead_end
        status = (Status.UNVERIFIED if dead is None else Status.FAIL if dead else Status.PASS)
        measured = ("the road's end is not known" if dead is None
                    else "the road ends at the plot" if dead else "the road runs on")
        found.append(Finding("Dead-end road", status, measured,
                             f"no dead end above {limit:g} m", rules.DEAD_END_CLAUSE))
    if facts.site_coordinates is None:
        found.append(Finding("Airport and Air Force height", Status.UNVERIFIED,
                             "no site coordinates", "under the height the maps allow",
                             AIRPORT_CLAUSE, "Does not stop the layouts; confirm on the maps."))
    return found


def heights_to_try(request: LayoutRequest) -> list[int]:
    """With request.maximise, every height from one above request.floors (the most the rules
    allow, which the one above shows) down to the lowest high-rise; otherwise request.floors."""
    if not request.maximise:
        return [request.floors]
    return list(range(request.floors + 1, lowest_high_rise_floors(request) - 1, -1))


def search_heights(plot: Polygon, library: FlatLibrary, request: LayoutRequest,
                   facts: SiteFacts, amenities: AmenityLibrary | None = None) -> HeightSearch:
    """Each height in turn, top down: the law, then the ground; the options are the best
    distinct layouts that pass, whatever their height."""
    result = HeightSearch()
    passing: list[LayoutOption] = []
    for floors in heights_to_try(request):
        at = request.model_copy(update={"floors": floors})
        legal = tuple(legal_findings(floors, at, facts, plot))
        tried = None
        if not any(f.status is Status.FAIL for f in legal):
            tried = search(plot, library, at, facts, amenities)
            passing += tried.options
        result.results.append(HeightResult(floors, at.height_m, legal, tried))
    result.options = pick_distinct(passing, request.options)
    return result
